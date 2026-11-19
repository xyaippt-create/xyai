"""Same-pixel-mask scheduling over the existing single-image retouch contract."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import os
import re
import tempfile
import uuid
from pathlib import Path

from fastapi import Body, File, Form, HTTPException, UploadFile
from PIL import Image


def batch_retouch_path(app_root, batch_id):
    return app_root / "诊断" / "任务记录" / "瑕疵修复批次" / batch_id


def atomic_write(path, content):
    handle = tempfile.NamedTemporaryFile(dir=path.parent, delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def register_batch_local_retouch_routes(
    app, *, sessions, require_roots, create_session, session_payload,
    process, confirm, save, max_mask_bytes, registry, safe_path, sha256_file,
):
    batches = {}
    # Retain background tasks until completion; no separate batch infrastructure.
    workers = set()

    def fail(message, code=409):
        raise HTTPException(status_code=code, detail={"message": message})

    def batch_folder(app_root, batch_id):
        if not re.fullmatch(r"[0-9a-f]{32}", batch_id):
            fail("批次编号无效。", 404)
        return safe_path(batch_retouch_path(app_root, batch_id), app_root)

    def checkpoint(batch):
        folder = batch["_folder"]
        stored = {key: value for key, value in batch.items() if not key.startswith("_")}
        stored["sessions"] = dict(batch.get("_excluded_sessions", {}))
        for item in batch["items"]:
            for session_id in (item.get("source_session_id"), (item.get("candidate") or {}).get("session_id"),
                               (item.get("preview") or {}).get("session_id")):
                if session_id in sessions:
                    stored["sessions"][session_id] = {
                        key: value for key, value in sessions[session_id].items() if not key.startswith("_")
                    }
        try:
            atomic_write(safe_path(folder / "batch.json", folder), json.dumps(stored, ensure_ascii=False, default=str).encode())
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail={"message": "批次进度未能写入，请检查数据目录后重试。"}) from exc
        referenced = mask_files(batch)
        for digest in batch.get("_mask_files", set()) - referenced:
            try:
                safe_path(folder / f"mask-{digest}.png", folder).unlink(missing_ok=True)
            except (OSError, RuntimeError):
                pass
        batch["_mask_files"] = referenced

    def mask_files(batch):
        masks = [group.get(key) for group in batch["groups"].values() for key in ("draft", "snapshot")]
        masks.extend(item.get("attempt_mask") for item in batch["items"]
                     if item["status"] in {"ready", "queued", "processing", "failed"}
                     or (item["status"] == "candidate" and item.get("retried")))
        return {
            digest for mask in masks
            if (digest := (mask or {}).get("mask_file_sha256"))
            and re.fullmatch(r"[0-9a-f]{64}", digest)
        }

    def verified_file(value, root, digest):
        if not value or not digest:
            raise ValueError("missing file identity")
        path = safe_path(Path(value), root)
        if not path.is_file() or sha256_file(path) != digest:
            raise ValueError("missing or changed file")
        return path

    def restore_session(folder, session_id, state):
        if not re.fullmatch(r"[0-9a-f]{32}", session_id) or state.get("session_id") != session_id:
            raise ValueError("invalid session identity")
        root = safe_path(folder / "sessions" / session_id, folder)
        state = dict(state, root=root, processing=False, confirmed=False, confirmed_at=None, output=None)
        for key in ("upload_path", "working_path", "previous_working_path"):
            if state.get(key):
                state[key] = safe_path(Path(state[key]), root)
        for entry in state.get("working_history", []):
            entry["path"] = safe_path(Path(entry["path"]), root)
        sessions[session_id] = state
        return state

    def restore(folder, batch_id, output_root):
        try:
            stored = json.loads(safe_path(folder / "batch.json", folder).read_text(encoding="utf-8"))
            if stored["batch_id"] != batch_id or stored["schema"] not in (1, 2) or not isinstance(stored["items"], list):
                raise ValueError("invalid batch identity")
            states = stored.pop("sessions")
            if stored["schema"] == 1:
                # Preserve historical exclusions, candidates and mask identities as recorded.
                stored.update(schema=2, groups={})
                if stored.get("width") and stored.get("height"):
                    key = f"{stored['width']}x{stored['height']}"
                    group = {field: stored.pop(field, None) for field in ("width", "height", "draft", "snapshot")}
                    stored["groups"][key] = dict(group, group_id=key, status=stored["status"])
                    for item in stored["items"]:
                        if item["status"] != "excluded":
                            item["group_id"] = key
                    if stored["busy"]:
                        stored["running_group_id"] = key
        except FileNotFoundError:
            fail("找不到该批次的恢复记录。", 404)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            fail("批次恢复记录无法读取。")

        stored.update(_folder=folder, _mask_files=mask_files(stored), busy=False)
        interrupted = stored["status"] == "processing"
        if interrupted:
            stored["status"] = "cancelled" if stored["cancel_requested"] else "interrupted"
            running = stored["groups"].get(stored.get("running_group_id"))
            if running:
                running["status"] = stored["status"]
        stored["running_group_id"] = None
        # Older checkpoints only kept the batch snapshot. Use it when a failed
        # task proves it belongs to that item.
        legacy_failed = {item["item_id"]: item for item in stored["items"]
                         if item["status"] == "failed" and "attempt_mask" not in item}
        if legacy_failed:
            for record in registry.values():
                item = legacy_failed.get(record.get("batch_item_id"))
                previous_mask = (stored["groups"].get(item["group_id"], {}).get("snapshot") or {}) if item else {}
                if (item and record.get("batch_id") == batch_id and record.get("status") == "failed"
                        and previous_mask.get("mask_file_sha256")
                        and record.get("source_id") == item.get("source_session_id")
                        and identity(record) == identity(previous_mask)):
                    item["attempt_mask"] = previous_mask
        for item in stored["items"]:
            if item["status"] == "excluded":
                # Old dimension exclusions may still own an imported source. Keep its
                # checkpoint on subsequent edits without opening it for processing.
                source_id = item.get("source_session_id")
                if source_id in states:
                    stored.setdefault("_excluded_sessions", {})[source_id] = states[source_id]
                continue
            item.pop("source_error", None)
            item.pop("candidate_error", None)
            if item["status"] in {"processing", "queued"}:
                if stored["cancel_requested"] and item["status"] == "queued":
                    cancel_item(item)
                else:
                    item["status"] = "ready"
            source_id = item.get("source_session_id")
            try:
                source = restore_session(folder, source_id, states[source_id])
                verified_file(source["upload_path"], source["root"], source["source_sha256"])
                verified_file(source["working_path"], source["root"], source["working_sha256"])
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                item["source_error"] = "该图片的原图或工作底图已缺失或改变，已跳过。"
            for key in ("candidate", "preview"):
                data = item.get(key)
                if not data:
                    continue
                try:
                    state = restore_session(folder, data["session_id"], states[data["session_id"]])
                    record = registry.get(data["task_id"]) or {}
                    if any(record.get(field) != expected for field, expected in {
                        "batch_id": batch_id, "batch_item_id": item["item_id"], "source_id": source_id,
                        "mask_revision": data["mask_revision"], "mask_sha256": data["mask_sha256"],
                    }.items()):
                        raise ValueError("candidate lineage mismatch")
                    result = record.get("result") or {}
                    if key == "candidate" and record.get("result_id"):
                        item["status"] = "saved"
                        if result.get("result_id") != record["result_id"]:
                            raise ValueError("result identity mismatch")
                        path = verified_file(result.get("output_path"), output_root, result.get("output_sha256"))
                        state["output"] = {
                            "result_id": record["result_id"], "task_id": data["task_id"],
                            "path": path, "file_name": path.name, "directory_name": path.parent.name,
                            "sha256": result["output_sha256"],
                        }
                        state["confirmed"] = True
                    elif item["status"] == "saved" and key == "candidate":
                        raise ValueError("saved result registration missing")
                    else:
                        if record.get("status") != "completed" or record.get("working_sha256") != state["working_sha256"]:
                            raise ValueError("candidate completion missing")
                        verified_file(state["working_path"], state["root"], state["working_sha256"])
                        if key == "candidate" and not item.get("source_error"):
                            verified_file(state["upload_path"], state["root"], state["source_sha256"])
                    item[key] = session_payload(state) | {"mask_sha256": data["mask_sha256"]}
                except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                    if key == "candidate":
                        item["candidate_error"] = ("已另存成品无法校验，请检查输出中心。" if item["status"] == "saved"
                                                   else "候选已失效，可继续修复该图。")
                        if item["status"] == "candidate":
                            item.update(status="ready", candidate=None)
                    else:
                        item["preview"] = None
        return stored

    def require_batch(batch_id, *, idle=False):
        _, app_root, _, output_root = require_roots()
        folder = batch_folder(app_root, batch_id)
        batch = batches.get(folder)
        if batch is None:
            batch = batches[folder] = restore(folder, batch_id, output_root)
        if idle and batch["busy"]:
            fail("当前批次仍在处理中，请等待完成或取消后再操作。")
        return batch

    def require_group(batch, group_id):
        groups = batch["groups"]
        if not group_id and len(groups) == 1:
            return next(iter(groups.values()))
        if group_id not in groups:
            fail("请选择本批次内有效的尺寸组。")
        return groups[group_id]

    def require_item(batch, group, item_id):
        item = next((item for item in batch["items"] if item["item_id"] == item_id), None)
        if item is None or not item.get("source_session_id") or item["status"] == "excluded":
            fail("该图片未通过导入校验。")
        if item.get("group_id") != group["group_id"]:
            fail("图片不属于当前尺寸组。")
        if item.get("source_error"):
            fail(item["source_error"])
        return item

    def snapshot(group, payload):
        revision = payload.get("mask_revision")
        if type(revision) is not int or revision < 1:
            fail("选区版本无效，请重新标记。", 400)
        encoded = str(payload.get("mask_png_base64") or "")
        encoded = encoded.partition(",")[2] if encoded.startswith("data:") else encoded
        if len(encoded) > (max_mask_bytes * 4 // 3 + 8):
            fail("选区数据过大。", 400)
        try:
            raw = base64.b64decode(encoded, validate=True)
            if not raw or len(raw) > max_mask_bytes:
                raise ValueError("mask size")
            with Image.open(io.BytesIO(raw)) as opened:
                if opened.format != "PNG" or opened.size != (group["width"], group["height"]):
                    raise ValueError("mask geometry")
                uses_alpha = "A" in opened.getbands() or "transparency" in opened.info
                mask = opened.convert("RGBA").getchannel("A") if uses_alpha else opened.convert("L")
                mask.load()
                if mask.getextrema()[1] < 128:
                    raise ValueError("empty mask")
                digest = hashlib.sha256(mask.tobytes()).hexdigest()
                if not uses_alpha:
                    overlay = Image.new("RGBA", mask.size, "white")
                    overlay.putalpha(mask)
                    encoded_mask = io.BytesIO()
                    overlay.save(encoded_mask, "PNG")
                    raw = encoded_mask.getvalue()
                    if len(raw) > max_mask_bytes:
                        raise ValueError("normalized mask size")
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"message": "选区为空、损坏或与基准图尺寸不一致。"}) from exc
        return {"mask_revision": revision, "mask_sha256": digest, "mask_file_sha256": hashlib.sha256(raw).hexdigest()}, raw

    def store_mask(batch, group, payload):
        frozen, raw = snapshot(group, payload)
        draft = group.get("draft") or {}
        if frozen["mask_revision"] < draft.get("mask_revision", 0) or (
            frozen["mask_revision"] == draft.get("mask_revision") and identity(frozen) != identity(draft)
        ):
            fail("选区版本已变化，请重新恢复批次后操作。")
        folder = batch["_folder"]
        path = safe_path(folder / f"mask-{frozen['mask_file_sha256']}.png", folder)
        try:
            if not path.is_file() or sha256_file(path) != frozen["mask_file_sha256"]:
                atomic_write(path, raw)
        except OSError as exc:
            raise HTTPException(status_code=503, detail={"message": "共用选区未能写入，请检查数据目录。"}) from exc
        return frozen

    def read_mask(batch, frozen):
        digest = frozen["mask_file_sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid mask identity")
        folder = batch["_folder"]
        raw = safe_path(folder / f"mask-{digest}.png", folder).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("mask changed")
        return raw

    def identity(value):
        return (value.get("mask_revision"), value.get("mask_sha256"))

    def public(batch):
        items = []
        for item in batch["items"]:
            source = sessions.get(item.get("source_session_id")) if not item.get("source_error") else None
            items.append({
                key: value for key, value in item.items()
                if key not in {"source_session_id", "attempt_mask", "intake_fingerprint"}
            } | {"source": session_payload(source) if source else None})
        eligible = [item for item in items if item["status"] != "excluded"]
        finished = sum(item["status"] in {"candidate", "saved", "failed", "cancelled"} for item in eligible)
        groups = [{
            "group_id": key, "width": group["width"], "height": group["height"], "status": group["status"],
            "draft_revision": (group.get("draft") or {}).get("mask_revision"),
            "mask_revision": (group.get("snapshot") or {}).get("mask_revision"),
            "mask_sha256": (group.get("snapshot") or {}).get("mask_sha256"),
        } for key, group in batch["groups"].items()]
        single = groups[0] if len(groups) == 1 else {}
        return {
            "batch_id": batch["batch_id"], "groups": groups, "running_group_id": batch.get("running_group_id"),
            **{key: single.get(key) for key in ("width", "height", "draft_revision", "mask_revision", "mask_sha256")},
            "status": batch["status"], "busy": batch["busy"], "cancel_requested": batch["cancel_requested"],
            "error": batch.get("_error", ""),
            "total": len(eligible), "finished": finished, "items": items,
        }

    def response(batch):
        return {"success": True, "data": public(batch)}

    async def candidate(batch, item, frozen, encoded):
        try:
            original = sessions[item["source_session_id"]]
            source_sha256 = original["source_sha256"]
            path = safe_path(original["upload_path"], original["root"])
            content = path.read_bytes()
        except FileNotFoundError:
            item["source_error"] = "该图片的原图已缺失，已跳过。可恢复原文件后重试。"
        except OSError:
            item["source_error"] = "该图片的原图无法读取，请检查文件权限后重试。"
        except (KeyError, TypeError, ValueError, RuntimeError):
            item["source_error"] = "该图片的原图记录或路径已失效，已跳过。"
        else:
            item.pop("source_error", None)
            if hashlib.sha256(content).hexdigest() != source_sha256:
                item["source_error"] = "该图片的原图已改变，已跳过。可恢复原文件后重试。"
            elif item.get("retried"):
                try:
                    verified_file(original["working_path"], original["root"], original["working_sha256"])
                except (KeyError, OSError, ValueError, RuntimeError):
                    item["source_error"] = "该图片的工作底图已缺失、改变或无法读取，已跳过。"
        if item.get("source_error"):
            fail(item["source_error"])
        child = create_session(content, original["file_name"], batch_id=batch["batch_id"])
        session = sessions[child["session_id"]]
        session.update({
            "batch_id": batch["batch_id"], "batch_item_id": item["item_id"],
            "source_id": item["source_session_id"], "mask_revision": frozen["mask_revision"],
            "mask_sha256": frozen["mask_sha256"], "_batch_processing": True,
        })
        try:
            result = await process(session["session_id"], {
                "mask_png_base64": encoded, "mask_revision": frozen["mask_revision"],
            })
            return result["data"] | {"mask_sha256": frozen["mask_sha256"]}
        finally:
            session["_batch_processing"] = False

    def cancel_item(item):
        if item.get("retried"):
            item.update(status="failed", error="已取消该图片的重试，可再次重试。")
        else:
            item["status"] = "cancelled"

    async def run(batch, group, work):
        try:
            attempts = {item["item_id"]: (frozen, encoded) for item, frozen, encoded, _ in work}
            for item in batch["items"]:
                if item["item_id"] not in attempts:
                    continue
                frozen, encoded = attempts[item["item_id"]]
                if batch["cancel_requested"]:
                    cancel_item(item)
                    checkpoint(batch)
                    continue
                item["status"] = "processing"
                checkpoint(batch)
                try:
                    item["candidate"] = await candidate(batch, item, frozen, encoded)
                    item["status"] = "candidate"
                except Exception:
                    item["status"] = "failed"
                    item["error"] = ("" if item.get("source_error") else
                                     "该图片修复失败。请排除临时错误后重试。")
                checkpoint(batch)
            batch.update(status="cancelled" if batch["cancel_requested"] else "completed", busy=False)
            group["status"] = batch["status"]
            batch["running_group_id"] = None
            checkpoint(batch)
        except HTTPException as exc:
            batch.update(status="interrupted", _error=exc.detail["message"])
            group["status"] = "interrupted"
            for item in batch["items"]:
                if item["status"] in {"queued", "processing"}:
                    item["status"] = "ready"
        finally:
            batch["busy"] = False
            batch["running_group_id"] = None

    @app.post("/api/local-retouch/batches")
    async def create_batch():
        _, app_root, _, _ = require_roots()
        batch_id = uuid.uuid4().hex
        folder = batch_folder(app_root, batch_id)
        folder.mkdir(parents=True, exist_ok=False)
        batch = {"batch_id": batch_id, "groups": {}, "items": [], "schema": 2,
                 "status": "editing", "busy": False, "cancel_requested": False, "_folder": folder}
        checkpoint(batch)
        batches[folder] = batch
        return response(batch)

    @app.get("/api/local-retouch/batches")
    async def list_batches():
        _, app_root, _, _ = require_roots()
        root = safe_path(batch_retouch_path(app_root, ""), app_root)
        entries = []
        for folder in root.glob("*"):
            if not re.fullmatch(r"[0-9a-f]{32}", folder.name):
                continue
            try:
                path = safe_path(folder / "batch.json", root)
                stored = json.loads(path.read_text(encoding="utf-8"))
                items = stored["items"]
                if items:
                    entries.append({
                        "batch_id": folder.name, "file_name": items[0]["file_name"],
                        "count": len(items), "updated_at": path.stat().st_mtime,
                    })
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                continue
        return {"success": True, "data": sorted(entries, key=lambda entry: entry["updated_at"], reverse=True)}

    @app.get("/api/local-retouch/batches/{batch_id}")
    async def read_batch(batch_id: str):
        return response(require_batch(batch_id))

    @app.get("/api/local-retouch/batches/{batch_id}/selection")
    async def read_selection(batch_id: str, group_id: str = ""):
        batch = require_batch(batch_id)
        group = require_group(batch, group_id) if batch["groups"] or group_id else {}
        draft = group.get("draft") or {}
        encoded, error = "", ""
        if draft.get("mask_file_sha256"):
            try:
                encoded = base64.b64encode(read_mask(batch, draft)).decode()
            except (OSError, ValueError, RuntimeError):
                error = "共用选区已缺失或损坏，请重新标记后继续未完成项。"
        return {"success": True, "data": {"mask_revision": draft.get("mask_revision"),
                "mask_png_base64": encoded, "error": error}}

    @app.put("/api/local-retouch/batches/{batch_id}/selection")
    async def edit_selection(batch_id: str, payload: dict = Body(...), group_id: str = ""):
        batch = require_batch(batch_id, idle=True)
        group = require_group(batch, group_id)
        revision = payload.get("mask_revision")
        if type(revision) is not int or revision < 1:
            fail("选区版本无效，请重新标记。", 400)
        previous = group.get("draft")
        if previous and revision < previous["mask_revision"]:
            fail("选区版本已变化，请重新恢复批次后操作。")
        draft = store_mask(batch, group, payload) if payload.get("mask_png_base64") else {"mask_revision": revision}
        if previous and revision == previous["mask_revision"]:
            if identity(previous) != identity(draft):
                fail("选区版本已变化，请重新恢复批次后操作。")
            return {"success": True}
        group["draft"] = draft
        try:
            checkpoint(batch)
        except HTTPException:
            group["draft"] = previous
            raise
        return {"success": True}

    @app.post("/api/local-retouch/batches/{batch_id}/items")
    async def import_item(batch_id: str, file: UploadFile = File(...), client_item_id: str = Form(default="")):
        if client_item_id and not re.fullmatch(r"[0-9a-f]{32}", client_item_id):
            fail("导入编号无效。", 400)
        content = await file.read()
        batch = require_batch(batch_id)
        file_name = Path(str(file.filename or "图片")).name
        fingerprint = [file_name, hashlib.sha256(content).hexdigest()] if client_item_id else None
        if client_item_id:
            for existing in batch["items"]:
                if existing.get("client_item_id") != client_item_id:
                    continue
                if existing.get("intake_fingerprint") != fingerprint:
                    fail("导入编号已用于另一张图片，请重新选择图片。")
                return response(batch)
        if batch["busy"] or any(group["snapshot"] for group in batch["groups"].values()):
            fail("批次已开始试修或执行，请新建批次后导入。")
        new_group = None
        item = {"item_id": uuid.uuid4().hex, "file_name": file_name,
                "status": "ready", "error": "", "candidate": None, "preview": None}
        if client_item_id:
            item.update(client_item_id=client_item_id, intake_fingerprint=fingerprint)
        try:
            data = create_session(content, str(file.filename or ""), batch_id=batch_id)
            item["source_session_id"] = data["session_id"]
            item["file_name"] = data["file_name"]
            width, height = data["width"], data["height"]
            key = f"{width}x{height}"
            if key not in batch["groups"]:
                new_group = key
                batch["groups"][key] = {"group_id": key, "width": width, "height": height,
                                        "status": "editing", "draft": None, "snapshot": None}
            item["group_id"] = key
        except HTTPException as exc:
            if exc.status_code not in {400, 413, 415, 422}:
                raise
            item.update(status="excluded", error="已排除：图片损坏、格式不支持或超过导入安全限制。")
        batch["items"].append(item)
        try:
            checkpoint(batch)
        except HTTPException:
            batch["items"].pop()
            if new_group:
                del batch["groups"][new_group]
            raise
        return response(batch)

    @app.post("/api/local-retouch/batches/{batch_id}/preview")
    async def preview_item(batch_id: str, payload: dict = Body(...), group_id: str = ""):
        batch = require_batch(batch_id, idle=True)
        group = require_group(batch, group_id)
        if set(payload) != {"item_id", "mask_revision", "mask_png_base64"}:
            fail("试修请求字段不正确。", 400)
        item = require_item(batch, group, payload["item_id"])
        frozen = store_mask(batch, group, payload)
        group["draft"] = frozen
        if group["snapshot"] is None:
            group["snapshot"] = frozen
        batch["busy"] = True
        try:
            checkpoint(batch)
            item["preview"] = await candidate(batch, item, frozen, base64.b64encode(read_mask(batch, frozen)).decode())
        finally:
            batch["busy"] = False
            checkpoint(batch)
        return response(batch)

    def schedule(batch, group, work, frozen=None):
        if work:
            if frozen is not None:
                group.update(snapshot=frozen, draft=frozen)
            group["status"] = "processing"
            batch.update(busy=True, status="processing", cancel_requested=False, running_group_id=group["group_id"])
            batch.pop("_error", None)
            for item, mask, _, retried in work:
                item.update(status="queued", candidate=None, preview=None, error="", attempt_mask=mask)
                if retried:
                    item["retried"] = True
                else:
                    item.pop("retried", None)
                item.pop("candidate_error", None)
        try:
            checkpoint(batch)
        except HTTPException:
            batches.pop(batch["_folder"], None)
            raise
        if work:
            worker = asyncio.create_task(run(batch, group, work))
            workers.add(worker)
            worker.add_done_callback(workers.discard)
        return response(batch)

    def retry_work(batch, pending):
        work, encoded_masks = [], {}
        for item in pending:
            frozen = item.get("attempt_mask")
            if not frozen:
                item["error"] = "无法确认这张图片失败时使用的选区。请重新标记并新建批次处理该图。"
                continue
            digest = frozen.get("mask_file_sha256")
            if digest not in encoded_masks:
                try:
                    encoded_masks[digest] = base64.b64encode(read_mask(batch, frozen)).decode()
                except (KeyError, OSError, TypeError, ValueError, RuntimeError):
                    encoded_masks[digest] = None
            encoded = encoded_masks[digest]
            if encoded is None:
                item["error"] = "这张图片原先使用的选区已缺失或损坏。请新建批次并重新标记该图。"
                continue
            work.append((item, frozen, encoded, True))
        return work

    def launch(batch, group, payload, statuses, *, resuming=False):
        members = [item for item in batch["items"] if item.get("group_id") == group["group_id"]]
        resumed_retries = [item for item in members if resuming and item["status"] == "ready" and item.get("retried")]
        pending = [item for item in members if item["status"] in statuses
                   and not item.get("source_error") and not (resuming and item.get("retried"))]
        if not pending and not resumed_retries:
            fail("没有可继续处理的图片。")
        if set(payload) != {"mask_revision", "mask_png_base64"} and (pending or payload):
            fail("批量请求字段不正确。", 400)
        frozen, work = None, []
        if pending:
            frozen = store_mask(batch, group, payload)
            encoded = base64.b64encode(read_mask(batch, frozen)).decode()
            work.extend((item, frozen, encoded, False) for item in pending)
        work.extend(retry_work(batch, resumed_retries))
        return schedule(batch, group, work, frozen)

    @app.post("/api/local-retouch/batches/{batch_id}/start")
    async def start_batch(batch_id: str, payload: dict = Body(...), group_id: str = ""):
        batch = require_batch(batch_id, idle=True)
        return launch(batch, require_group(batch, group_id), payload, {"ready", "candidate", "failed", "cancelled"})

    @app.post("/api/local-retouch/batches/{batch_id}/resume")
    async def resume_batch(batch_id: str, payload: dict = Body(...), group_id: str = ""):
        batch = require_batch(batch_id, idle=True)
        return launch(batch, require_group(batch, group_id), payload, {"ready"}, resuming=True)

    @app.post("/api/local-retouch/batches/{batch_id}/retry-failed")
    async def retry_failed(batch_id: str, group_id: str = ""):
        batch = require_batch(batch_id, idle=True)
        group = require_group(batch, group_id)
        failed = [item for item in batch["items"] if item["status"] == "failed" and item.get("group_id") == group["group_id"]]
        if not failed:
            fail("当前批次没有失败项。")
        return schedule(batch, group, retry_work(batch, failed))

    @app.post("/api/local-retouch/batches/{batch_id}/cancel")
    async def cancel_batch(batch_id: str, group_id: str = ""):
        batch = require_batch(batch_id)
        group = require_group(batch, group_id)
        if batch.get("running_group_id") != group["group_id"]:
            fail("当前尺寸组没有正在执行的任务。")
        batch["cancel_requested"] = True
        checkpoint(batch)
        return response(batch)

    @app.post("/api/local-retouch/batches/{batch_id}/confirm-save")
    async def save_items(batch_id: str, payload: dict = Body(...), group_id: str = ""):
        batch = require_batch(batch_id, idle=True)
        group = require_group(batch, group_id)
        if (set(payload) not in ({"items"}, {"items", "mask_revision", "mask_png_base64"})
                or not isinstance(payload["items"], list) or not payload["items"]):
            fail("请选择已查看且满意的候选后确认另存。", 400)
        current = None
        selected = []
        for selection in payload["items"]:
            if not isinstance(selection, dict) or set(selection) != {"item_id", "session_id"}:
                fail("候选绑定不完整。", 400)
            item = require_item(batch, group, selection["item_id"])
            result = item.get("candidate") or {}
            if item["status"] not in {"candidate", "saved"} or selection["session_id"] != result.get("session_id"):
                fail("图片或选区版本与当前候选不一致，请重新查看结果。")
            if item.get("retried"):
                expected = item.get("attempt_mask") or {}
            else:
                if current is None:
                    current, _ = snapshot(group, payload)
                    if identity(current) != identity(group.get("draft") or {}):
                        fail("选区已变化，请重新执行批量修复后再确认。")
                expected = current
            if identity(result) != identity(expected):
                fail("图片或选区版本与当前候选不一致，请重新查看结果。")
            selected.append(item)
        batch["busy"] = True
        try:
            for item in selected:
                if item["status"] == "saved":
                    continue
                session = sessions[item["candidate"]["session_id"]]
                session["_batch_saving"] = True
                try:
                    candidate_result = item["candidate"]
                    await confirm(session["session_id"], {"mask_revision": candidate_result["mask_revision"]})
                    saved = await save(session["session_id"], {})
                    item["candidate"] = saved["data"] | {"mask_sha256": candidate_result["mask_sha256"]}
                    item.update(status="saved", error="")
                except Exception:
                    item["error"] = "另存失败，未覆盖原图；可重新确认另存该候选。"
                finally:
                    session["_batch_saving"] = False
                checkpoint(batch)
        finally:
            batch["busy"] = False
        return response(batch)

    return batches
