"""Durable batch orchestration around the unchanged single-image optimizer.

Batch facts use the existing shared registry. Sources and pre-publication receipts
live in the existing private compression cache, never in Output Center.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
import re
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, File, Form, HTTPException, UploadFile

from engine.image_compression.delivery_options import (
    PRESERVE_FORMAT_TARGET_FORMAT,
    SMART_COMPRESSION_TARGET_FORMAT,
    SUPPORTED_TARGET_FORMATS,
)
from engine.output.publish_safety import publish_verified_file_copy_no_overwrite
from engine.storage.shared_task_registry import SharedTaskRegistryError
from engine.storage.batch_results import BATCH_SCHEMA, item_identity, mapping, value


LOGGER = logging.getLogger(__name__)
BATCH_KIND = "compression_batch"
DEFAULT_WORKERS = 2
MAX_WORKERS = 3
MAX_FILES = 100
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
# Do not run several large, full-resolution quality analyses at once.
ACTIVE_PIXEL_BUDGET = 8_000_000
TERMINAL = {"COMPLETED", "KEEP_ORIGINAL", "FAILED", "CANCELED"}


def normalize_target_format(value, *, allow_legacy=False):
    normalized = str(value or SMART_COMPRESSION_TARGET_FORMAT).strip().upper()
    if allow_legacy and normalized in {"AUTO", "SYSTEM_AUTO"}:
        normalized = PRESERVE_FORMAT_TARGET_FORMAT
    if normalized not in SUPPORTED_TARGET_FORMATS:
        raise ValueError("BATCH_TARGET_FORMAT_INVALID")
    return normalized


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def contained(path, root):
    resolved, boundary = Path(path).resolve(), Path(root).resolve()
    if not resolved.is_relative_to(boundary) or resolved == boundary:
        raise ValueError("BATCH_PATH_OUTSIDE_APPROVED_ROOT")
    return resolved


def result_outcome(record, item):
    result = record.get("result")
    result = result.to_dict() if hasattr(result, "to_dict") else result
    if not isinstance(result, Mapping) or record.get("status") != "completed":
        raise ValueError("BATCH_SINGLE_RESULT_NOT_COMPLETED")
    if (record.get("task_id") != item["task_id"]
            or result.get("task_id") != item["task_id"]
            or result.get("source_sha256") != item["source"]["sha256"]
            or result.get("source_size_bytes") != item["original_bytes"]):
        raise ValueError("BATCH_SOURCE_RESULT_IDENTITY_MISMATCH")
    if record.get("winner_scheme_id") == "keep_original":
        if record.get("result_id") or record.get("public_output_count") != 0 or result.get("output_created"):
            raise ValueError("BATCH_KEEP_ORIGINAL_CONTRACT_INVALID")
        return {"status": "KEEP_ORIGINAL", "final_bytes": item["original_bytes"], "result_id": "", "output_path": "", "output_sha256": ""}
    candidates = [c for c in record.get("candidate_options", []) if c.get("status") == "AVAILABLE"]
    if (len(candidates) != 1 or record.get("public_output_count") != 1
            or not result.get("output_created") or not result.get("delivery_eligible")
            or record.get("result_id") != item["reserved_result_id"]
            or candidates[0].get("scheme_id") != record.get("winner_scheme_id")
            or candidates[0].get("quality_gate", {}).get("status") != "PASS"):
        raise ValueError("BATCH_UNIQUE_WINNER_CONTRACT_INVALID")
    output = Path(result["output_path"])
    requested_target = normalize_target_format(
        record.get("request", {}).get("target_format"),
        allow_legacy=True,
    )
    format_conversion = result.get("source_format") != result.get("output_format")
    explicit_conversion = requested_target in {"JPEG", "PNG", "WEBP"} and format_conversion
    if (file_sha(output) != result.get("output_sha256")
            or result.get("output_sha256") != candidates[0].get("output_sha256")
            or not 0 < output.stat().st_size == result.get("output_size_bytes", 0)
            or (not explicit_conversion and output.stat().st_size >= item["original_bytes"])):
        raise ValueError("RESULT_IDENTITY_MISMATCH")
    return {"status": "COMPLETED", "final_bytes": result["output_size_bytes"],
            "output_path": str(output),
            "result_id": record["result_id"], "output_sha256": result["output_sha256"],
            "format_conversion": format_conversion}


def retained_result_view(record, item):
    """Join retained Result facts to their original batch verification receipt.

    This is only a read-time validation view, never a replacement Task/Result.
    The private image may be gone; the formal file must still pass result_outcome.
    """
    result = record["result"]
    task_result = record["task_result"]
    receipt = item["prepared"]
    generated = receipt["generated"]
    if (record.get("record_kind") != "result"
            or record.get("source_task_id") != item["task_id"]
            or task_result.get("task_id") != item["task_id"]
            or task_result.get("result_id") != item["reserved_result_id"]
            or generated["source"]["sha256"] != result["source_sha256"]
            or task_result.get("source_sha256") != result["source_sha256"]):
        raise ValueError("BATCH_SOURCE_RESULT_IDENTITY_MISMATCH")
    if (task_result.get("output_sha256") != result["output_sha256"]
            or generated["winner"].get("output_sha256") != result["output_sha256"]
            or any(not path or Path(path).resolve() != Path(result["output_path"]).resolve()
                   for path in (receipt.get("target"), record.get("output_path"), record.get("result_file"),
                                task_result.get("output_path"), task_result.get("result_file")))):
        raise ValueError("RESULT_IDENTITY_MISMATCH")
    return {**record, "candidate_options": generated["candidates"],
            "request": {"target_format": generated.get("target_format")},
            "effective_target_format": generated.get("effective_target_format"),
            "format_policy": generated.get("format_policy"),
            "format_conversion": generated.get("format_conversion"),
            "winner_scheme_id": generated["winner_scheme_id"],
            "public_output_count": generated["public_output_count"]}


class BatchJob:
    def __init__(self, service, batch, item):
        self.service, self.batch, self.item = service, batch, item
        self._checked_source = None

    @property
    def source(self):
        source = dict(self.item["source"])
        source["path"] = contained(source["path"], self.service.cache_root())
        if file_sha(source["path"]) != source["sha256"]:
            raise ValueError("SOURCE_IDENTITY_MISMATCH")
        return source

    async def checked_source(self):
        """Verify the saved Source once when this job starts.

        Work, the compression adapter and generate() all need it back to back; later
        checks that must see fresh bytes (after encoding, after publication) still
        use .source.
        """
        if self._checked_source is None:
            self._checked_source = await asyncio.to_thread(lambda: self.source)
        return dict(self._checked_source)

    async def generate(self, producer, output_dir):
        """Recover verified bytes, or run the frozen pipeline once in private staging.

        The receipt is durable BEFORE any public copy. A crash after that point
        reuses the SHA-bound artifact and reserved identity, never re-encodes it.
        """
        source = await self.checked_source()
        output_dir = Path(output_dir).resolve()
        if output_dir != Path(self.batch["output_directory"]).resolve():
            raise ValueError("BATCH_OUTPUT_DIRECTORY_CHANGED")
        receipt = self.item.get("prepared")
        verified_private = None
        if receipt is None:
            stage = contained(Path(self.batch["cache_directory"]) / self.item["id"] / uuid.uuid4().hex,
                              self.service.cache_root())
            stage.mkdir(parents=True, exist_ok=False)
            generated = await producer(stage)
            if generated["source"]["sha256"] != source["sha256"]:
                raise ValueError("SOURCE_IDENTITY_MISMATCH")
            # Encoding metadata bytes are no longer needed after verification.
            # Keep the exact source identity consumed by Result registration;
            # the immutable source file and candidate verification retain metadata.
            generated["source"] = {key: generated["source"][key]
                                   for key in ("path", "sha256", "format", "size_bytes")}
            target = None
            if generated["public_output_count"]:
                winner = generated["winner"]
                private = contained(winner["output_path"], stage)
                if await asyncio.to_thread(file_sha, private) != winner["output_sha256"]:
                    raise ValueError("RESULT_IDENTITY_MISMATCH")
                verified_private = private
                # Preserve the optimizer's formal name and the existing _02 style.
                reserved = self.service.reserved_outputs()
                target = output_dir / private.name
                sequence = 2
                while target.exists() or str(target) in reserved:
                    target = output_dir / f"{private.stem}_{sequence:02d}{private.suffix}"
                    sequence += 1
            receipt = {"generated": copy.deepcopy(generated), "target": str(target) if target else None}
            self.item["prepared"] = receipt
            self.service.persist(self.batch)
        generated = copy.deepcopy(receipt["generated"])
        if generated["source"]["sha256"] != (await asyncio.to_thread(lambda: self.source))["sha256"]:
            raise ValueError("SOURCE_IDENTITY_MISMATCH")
        if generated["public_output_count"]:
            winner = generated["winner"]
            private = contained(winner["output_path"], self.batch["cache_directory"])
            target = contained(receipt["target"], output_dir)
            if target.parent != output_dir:
                raise ValueError("BATCH_PUBLIC_PATH_INVALID")
            expected = winner["output_sha256"]
            # A receipt recovered from an earlier run is re-checked; one this call just
            # verified above is not hashed again.
            if private != verified_private and await asyncio.to_thread(file_sha, private) != expected:
                raise ValueError("RESULT_IDENTITY_MISMATCH")
            newly_published = False
            if target.exists():
                if await asyncio.to_thread(file_sha, target) != expected:
                    raise ValueError("RESULT_IDENTITY_MISMATCH")
            else:
                # The publisher re-reads the persisted copy and rejects any SHA mismatch.
                await asyncio.to_thread(publish_verified_file_copy_no_overwrite, private, [target], expected_sha256=expected)
                newly_published = True
            try:
                await asyncio.to_thread(lambda: self.source)  # Source must also remain bound across the publication.
            except Exception:
                if newly_published and await asyncio.to_thread(file_sha, target) == expected:
                    target.unlink()  # Only this attempt's just-published, SHA-bound file.
                raise
            winner["output_path"] = str(target)
            for candidate in generated["candidates"]:
                if candidate["scheme_id"] == winner["scheme_id"]:
                    candidate["output_path"] = str(target)
        return generated


class CompressionBatchService:
    def __init__(self, *, registry, roots, output_directory, intake, execute, source_preview_url):
        self.registry, self.roots, self.output_directory = registry, roots, output_directory
        self.intake, self.execute, self.source_preview_url = intake, execute, source_preview_url
        self.batches = {}
        self.loaded = False
        self.loaded_root = None
        self.closing = False
        self.pump = None
        self.active = {}
        self.session_id = uuid.uuid4().hex

    def cache_root(self):
        return Path(self.roots()["tmp_dir"]).resolve() / "compression-batches"

    def persist(self, batch):
        if self.registry is None:
            raise HTTPException(503, detail="批量压缩需要正式共享任务登记。")
        batch["updated_at"] = time.time()
        batch.update(batch_schema=BATCH_SCHEMA, feature_type="image_compression")
        facts = {}
        for item in batch["items"]:
            item.update(item_identity(batch["batch_id"], item["id"], "image_compression", item.get("source_id", "")))
            for field in ("result_id", "output_path", "output_sha256"):
                item.setdefault(field, "")
            current = mapping(self.registry.get(item["task_id"]))
            if item["status"] == "COMPLETED" and not item["output_path"]:
                result = mapping(self.registry.get(item["result_id"])) or current
                if str(value(result, "result_id")) == item["result_id"] and str(value(result, "task_id")) == item["task_id"]:
                    item["output_path"] = str(value(result, "output_path") or value(result, "result_file"))
            elif item["status"] in TERMINAL - {"COMPLETED"}:
                item.update(result_id="", output_path="", output_sha256="")
            # Reserve actual Task facts for import failures / queued cancellation.
            # Never recreate a Task that the user has already cleared.
            if item.pop("register_task", False) or (current and current.get("batch_item_id") == item["id"] and not current.get("result") and current.get("status") != "processing"):
                state = {"QUEUED": "pending", "CANCELED": "cancelled"}.get(item["status"], item["status"].lower())
                facts[item["task_id"]] = {
                    **current, **item_identity(batch["batch_id"], item["id"], "image_compression", item["source_id"]),
                    "record_kind": "task", "task_id": item["task_id"], "feature_key": "image_compression",
                    "task_family": "image_compression", "status": state, "task_status": state,
                    "created_at": current.get("created_at") or datetime.fromtimestamp(batch["created_at"], tz=timezone.utc).isoformat(),
                    "source_path": item.get("source", {}).get("path", ""),
                    "source_metadata": item.get("source", {}), "original_filename": item["name"],
                    "failure_reason": item.get("error", ""), "result_id": "", "result": None,
                }
        batch["revision"] = int(batch.get("revision", 0)) + 1
        facts[batch["batch_id"]] = copy.deepcopy(batch)
        if callable(getattr(self.registry, "persist_facts", None)):
            self.registry.persist_facts(facts)
        else:
            self.registry.update(facts)

    def reserved_outputs(self):
        return {item["prepared"]["target"] for batch in self.batches.values() for item in batch["items"]
                if item.get("prepared", {}).get("target")}

    def reconcile_item(self, batch, item):
        """Task/Result facts outrank a stale batch row, including after cancellation.

        Reuse the existing identity/quality checks, never re-register a Result or
        accept a changed file. True means the registered terminal fact was handled
        (possibly rejected), so callers must not turn it into QUEUED/CANCELED.
        """
        record = self.registry.get(item["task_id"], {})
        use_retained_result = record.get("status") != "completed"
        if use_retained_result:
            # Task deletion retains the exact Result under its existing ID.
            # An invalid retained fact is a failure, never permission to execute.
            record = self.registry.get(item["reserved_result_id"])
            if record is None:
                return False
        try:
            BatchJob(self, batch, item).source
            if use_retained_result:
                record = retained_result_view(record, item)
            result = record.get("result")
            result = result.to_dict() if hasattr(result, "to_dict") else result
            if isinstance(result, Mapping) and result.get("output_created"):
                contained(result["output_path"], batch["output_directory"])
            item.update(result_outcome(record, item), error="", recovery_active=False)
        except Exception as exc:
            code = str(exc)
            item.update(status="FAILED", result_id="", final_bytes=None, output_sha256="", recovery_active=False,
                        error=code if re.fullmatch(r"[A-Z0-9_]+", code) else "BATCH_REGISTERED_RESULT_UNAVAILABLE")
        return True

    def reconcile_batch(self, batch):
        changed = False
        for item in batch["items"]:
            if item["status"] in {"COMPLETED", "KEEP_ORIGINAL"}:
                continue
            before = dict(item)
            self.reconcile_item(batch, item)
            changed = changed or item != before
        return changed

    def load(self):
        if self.loaded:
            if self.loaded_root != str(self.cache_root()):
                raise HTTPException(409, detail="正式目录已变化，请重启应用后恢复对应目录中的批次。")
            return
        if self.registry is None:
            raise HTTPException(503, detail="批量压缩需要正式共享任务登记。")
        self.roots()
        for record in list(self.registry.values()):
            if record.get("record_kind") != BATCH_KIND:
                continue
            batch = copy.deepcopy(record)
            batch["target_format"] = normalize_target_format(batch.get("target_format"), allow_legacy=True)
            contained(batch["cache_directory"], self.cache_root())
            self.reconcile_batch(batch)
            for item in batch["items"]:
                if item["status"] != "PROCESSING":
                    continue
                item.update(status="QUEUED", recovery_active=True,
                            error="服务已重启，将从已保存的原图或交付凭据继续。")
            if batch["control"] == "IMPORTING":
                for item in batch["items"]:
                    if not item.get("source") and item["status"] == "QUEUED":
                        item.update(status="FAILED", error="导入被中断，请重新添加该图片。")
                batch["control"] = "PAUSED"
            self.batches[batch["batch_id"]] = batch
            self.persist(batch)
        self.loaded = True
        self.loaded_root = str(self.cache_root())

    def ensure_running(self):
        self.load()
        if not self.closing and (self.pump is None or self.pump.done()):
            self.pump = asyncio.create_task(self.dispatch())

    async def dispatch(self):
        while not self.closing:
            for task in [task for task in self.active if task.done()]:
                batch_id, _pixels, item = self.active.pop(task)
                failure = asyncio.CancelledError() if task.cancelled() else task.exception()
                if failure is not None:
                    # Remove the finished task before handling it: re-raising here would
                    # leave it in active and kill every later dispatcher run.
                    self.contain_worker_failure(self.batches[batch_id], item, failure)
            for batch in self.batches.values():
                for item in batch["items"]:
                    if item["status"] != "QUEUED" or (batch["control"] != "RUNNING" and not item.get("recovery_active")):
                        continue
                    own_count = sum(info[0] == batch["batch_id"] for info in self.active.values())
                    if own_count >= batch["workers"] or len(self.active) >= MAX_WORKERS:
                        break
                    pixels = int(item["source"]["width"]) * int(item["source"]["height"])
                    if self.active and sum(info[1] for info in self.active.values()) + pixels > ACTIVE_PIXEL_BUDGET:
                        continue
                    item.update(status="PROCESSING", started_at=item.get("started_at") or time.time(), finished_at=None, error="", recovery_active=False)
                    try:
                        self.persist(batch)
                    except SharedTaskRegistryError:
                        item.update(status="QUEUED", error="处理前无法保存任务状态，请检查登记目录后继续。")
                        batch["control"] = "PAUSED"
                        break
                    task = asyncio.create_task(self.work(batch, item))
                    self.active[task] = (batch["batch_id"], pixels, item)
            if not self.active:
                return
            await asyncio.wait(self.active, return_when=asyncio.FIRST_COMPLETED)

    def contain_worker_failure(self, batch, item, failure):
        """Never silently discard a registry/writer failure, and never let it stop the batch queue."""
        LOGGER.error(
            "Compression batch worker failed outside its own recovery: batch_id=%s item_id=%s task_id=%s status=%s; "
            "batch paused, item kept recoverable from its saved receipt.",
            batch["batch_id"], item.get("id"), item.get("task_id"), item.get("status"),
            exc_info=(type(failure), failure, failure.__traceback__),
        )
        batch["control"] = "PAUSED"
        if item["status"] == "PROCESSING":
            item.update(status="QUEUED", recovery_active=False,
                        error="该图片状态未能完整保存，批次已暂停；继续时将核对原有凭据，不会重复生成成品。")
        try:
            self.persist(batch)
        except Exception:
            LOGGER.exception("Compression batch state could not be saved after worker failure: batch_id=%s", batch["batch_id"])

    async def work(self, batch, item):
        try:
            if self.reconcile_item(batch, item):
                return
            if str(Path(self.output_directory()).resolve()) != batch["output_directory"]:
                raise ValueError("BATCH_OUTPUT_DIRECTORY_CHANGED")
            job = BatchJob(self, batch, item)
            await job.checked_source()  # Check the saved Source before using any existing Result.
            existing = self.registry.get(item["task_id"], {})
            if existing.get("status") != "completed":
                await self.execute({
                    "operation_mode": "DELIVERY_OPTIMIZATION",
                    "params": {"target_format": normalize_target_format(batch.get("target_format"))},
                }, batch_job=job)
                existing = self.registry.get(item["task_id"], {})
            item.update(result_outcome(existing, item), error="")
        except Exception as exc:
            code = str(getattr(exc, "failure_code", "") or str(exc))
            if self.reconcile_item(batch, item):
                batch["control"] = "PAUSED"
            elif isinstance(exc, (OSError, SharedTaskRegistryError)) and item.get("prepared"):
                # A validated artifact may already have been published. Keep its
                # receipt and identity recoverable, never report an orphan as FAILED
                # or generate a second Winner. Identity mismatches do NOT enter here.
                batch["control"] = "PAUSED"
                item.update(status="QUEUED", result_id="", final_bytes=None, output_sha256="", error="登记或文件写入中断；请检查目录后继续，将核对原有凭据而非重新生成成品。")
            elif self.closing and not isinstance(exc, ValueError):
                # The app is closing: the launcher stops waiting and the runtime refuses
                # new thread work, so an encode in progress cannot finish now. That is an
                # interruption, not a bad image; resume it on the next start (a saved
                # receipt is reused). Identity/path checks (ValueError) still fail.
                LOGGER.warning(
                    "Compression batch item interrupted by shutdown: batch_id=%s item_id=%s task_id=%s reason=%s; kept for recovery.",
                    batch["batch_id"], item.get("id"), item.get("task_id"), exc,
                )
                item.update(status="QUEUED", recovery_active=True, result_id="", final_bytes=None, output_sha256="",
                            error="应用关闭时处理被中断，下次启动将从已保存的原图或凭据继续。")
            else:
                item.update(status="FAILED", error=code if re.fullmatch(r"[A-Z0-9_]+", code) else "该图片处理失败，请核对原图；其他图片继续处理。")
        finally:
            item["finished_at"] = time.time()
            try:
                self.persist(batch)
            except SharedTaskRegistryError:
                # A completed Result is independently durable even when this batch
                # snapshot cannot be saved. Never erase its authoritative identity.
                batch["control"] = "PAUSED"
                if not self.reconcile_item(batch, item):
                    item.update(status="QUEUED", result_id="", final_bytes=None, output_sha256="", error="共享任务登记暂时不可写，请检查目录后继续；不会重复生成成品。")

    def public(self, batch):
        items = []
        for item in batch["items"]:
            final = item.get("final_bytes")
            original = item["original_bytes"]
            items.append({"id": item["id"], "name": item["name"], "status": item["status"],
                          **item_identity(batch["batch_id"], item["id"], "image_compression", item.get("source_id", "")),
                          "task_id": item["task_id"], "result_id": item.get("result_id", ""),
                          "output_path": item.get("output_path", ""), "output_sha256": item.get("output_sha256", ""),
                          "originalBytes": original, "finalBytes": final,
                          "formatConversion": item.get("format_conversion") is True,
                          "savedPercent": (original-final)*100/original if final is not None and original else None,
                          "taskId": item["task_id"], "resultId": item.get("result_id", ""),
                          "sourceSha256": item.get("source", {}).get("sha256", ""),
                          "sourcePreviewUrl": self.source_preview_url(item.get("source") or {}, item["name"]),
                          "outputSha256": item.get("output_sha256", ""), "error": item.get("error", ""),
                          "elapsedSeconds": max(0, int((item.get("finished_at") or time.time())-item["started_at"])) if item.get("started_at") else 0})
        counts = {state: sum(i["status"] == state for i in items) for state in TERMINAL | {"QUEUED", "PROCESSING"}}
        state = ("CANCELING" if batch["control"] == "CANCELED" else "PAUSING" if batch["control"] == "PAUSED" else "RUNNING") if counts["PROCESSING"] else (
            "PAUSED" if counts["QUEUED"] and batch["control"] != "RUNNING" else "RUNNING" if counts["QUEUED"] else "CANCELED" if counts["CANCELED"] else "COMPLETED")
        if batch["control"] == "IMPORTING":
            state = "IMPORTING"
        prepared_count = sum(
            bool(item.get("source")) or item.get("status") == "FAILED"
            for item in batch["items"]
        )
        preparing_name = next(
            (
                str(item.get("name") or "")
                for item in batch["items"]
                if not item.get("source") and item.get("status") != "FAILED"
            ),
            "",
        ) if batch["control"] == "IMPORTING" else ""
        return {"batchId": batch["batch_id"], "serverSessionId": self.session_id, "revision": batch.get("revision", 0), "items": items, "state": state, "control": batch["control"],
                "targetFormat": normalize_target_format(batch.get("target_format")),
                "running": bool(counts["PROCESSING"] or (counts["QUEUED"] and batch["control"] == "RUNNING")),
                "workers": batch["workers"], "recoverable": True,
                "preparedCount": prepared_count, "preparingName": preparing_name}

    async def shutdown(self):
        self.closing = True
        # Graceful restarts drain current encodes/publications; never cancel a writer.
        if self.pump is not None:
            await self.pump
        if self.active:
            await asyncio.gather(*self.active)


def register_batch_compression_routes(app, *, registry, roots, output_directory, intake, execute, source_preview_url):
    service = CompressionBatchService(
        registry=registry, roots=roots, output_directory=output_directory,
        intake=intake, execute=execute, source_preview_url=source_preview_url,
    )

    @app.on_event("startup")
    async def recover_compression_batches():
        if registry is not None and any(record.get("record_kind") == BATCH_KIND for record in registry.values()):
            service.ensure_running()

    @app.on_event("shutdown")
    async def drain_compression_batches():
        await service.shutdown()

    @app.post("/api/image-compression/batches")
    async def create_batch(
        files: list[UploadFile] = File(...),
        batch_id: str = Form(...),
        workers: int = Form(DEFAULT_WORKERS),
        target_format: str = Form(SMART_COMPRESSION_TARGET_FORMAT),
    ):
        service.load()
        if not re.fullmatch(r"compression_batch_[a-f0-9]{32}", batch_id) or not 1 <= len(files) <= MAX_FILES or not 1 <= workers <= MAX_WORKERS:
            raise HTTPException(400, detail="每批支持1至100张图片、1至3个处理任务；批次标识必须有效。")
        try:
            target_format = normalize_target_format(target_format)
        except ValueError as exc:
            raise HTTPException(
                400,
                detail="目标格式仅支持 SMART_COMPRESSION、PRESERVE_FORMAT、JPEG、PNG 或 WEBP。",
            ) from exc
        if batch_id in service.batches:
            raise HTTPException(409, detail="批次已登记，请恢复此批次，不能重复创建。")
        cache = contained(service.cache_root() / batch_id, service.cache_root())
        batch = {"record_kind": BATCH_KIND, "batch_id": batch_id, "control": "IMPORTING", "workers": workers,
                 "target_format": target_format,
                 "created_at": time.time(), "cache_directory": str(cache), "output_directory": str(Path(output_directory()).resolve()), "items": []}
        for file in files:
            batch["items"].append({"id": uuid.uuid4().hex, "task_id": f"compression_{uuid.uuid4().hex[:16]}",
                                   "reserved_result_id": f"compression_result_{uuid.uuid4().hex[:16]}",
                                   "name": file.filename or "", "original_bytes": file.size or 0, "status": "QUEUED", "register_task": True})
        service.batches[batch_id] = batch
        service.persist(batch)
        for upload, item in zip(files, batch["items"]):
            try:
                content = await upload.read(MAX_UPLOAD_BYTES + 1)
                source = await asyncio.to_thread(intake, content, upload.filename or "")
                del content
                snapshot = contained(cache / item["id"] / Path(source["path"]).name, cache)
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(publish_verified_file_copy_no_overwrite, source["path"], [snapshot], expected_sha256=source["sha256"])
                item.update(source={**source, "path": str(snapshot)}, original_bytes=source["size_bytes"])
            except Exception:
                item.update(status="FAILED", error="图片无法完整解码、格式不支持或超过50MB限制，请检查原图。")
            finally:
                await upload.close()
            service.persist(batch)
        batch["control"] = "RUNNING"
        service.persist(batch)
        service.ensure_running()
        return {"success": True, "data": service.public(batch)}

    def get_batch(batch_id):
        service.load()
        batch = service.batches.get(batch_id)
        if batch is None:
            raise HTTPException(404, detail="当前正式目录中不存在此批次；不会猜测或恢复其他批次。")
        if service.reconcile_batch(batch):
            service.persist(batch)
        return batch

    @app.get("/api/image-compression/batches/{batch_id}/import-progress")
    async def batch_import_progress(batch_id: str):
        service.load()
        if not re.fullmatch(r"compression_batch_[a-f0-9]{32}", batch_id):
            return {"success": True, "data": {"registered": False, "preparedCount": 0, "preparingName": ""}}
        batch = service.batches.get(batch_id)
        if batch is None:
            # The create request may still be uploading its multipart body. This
            # read-only observer must not turn that expected interval into a 404
            # or change the durable exact-ID recovery contract.
            return {"success": True, "data": {"registered": False, "preparedCount": 0, "preparingName": ""}}
        public = service.public(batch)
        return {"success": True, "data": {
            "registered": True,
            "preparedCount": public["preparedCount"],
            "preparingName": public["preparingName"],
        }}

    @app.get("/api/image-compression/batches/{batch_id}")
    async def batch_status(batch_id: str):
        batch = get_batch(batch_id)
        service.ensure_running()
        return {"success": True, "data": service.public(batch)}

    @app.post("/api/image-compression/batches/{batch_id}/control")
    async def batch_control(batch_id: str, payload: dict = Body(...)):
        batch = get_batch(batch_id)
        action = payload.get("action")
        if set(payload) != {"action"} or action not in {"pause", "resume", "cancel"}:
            raise HTTPException(400, detail="仅支持暂停、继续或取消。")
        if batch["control"] == "IMPORTING":
            raise HTTPException(409, detail="正在保存原图，请等待导入完成。")
        if action == "resume" and batch["control"] == "CANCELED":
            raise HTTPException(409, detail="已取消项不会重新执行；请新建批次。")
        batch["control"] = {"pause": "PAUSED", "resume": "RUNNING", "cancel": "CANCELED"}[action]
        if action == "cancel":
            for item in batch["items"]:
                if item["status"] == "QUEUED":
                    if item.get("prepared"):
                        # An interrupted publication is already started work. Drain
                        # its existing SHA-bound receipt; never orphan its Winner.
                        item["recovery_active"] = True
                    else:
                        item.update(status="CANCELED", finished_at=time.time())
        service.persist(batch)
        service.ensure_running()
        return {"success": True, "data": service.public(batch)}

    return service
