"""Formal HTTP routes for HDDE batch watermarking."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping

from fastapi import Request, UploadFile
from starlette.datastructures import UploadFile as MultipartUpload

from backend.batch_capacity import batch_size_field, require_batch_capacity
from backend.watermark_presets import register_watermark_presets
from engine.batch_watermark import WatermarkEngine, WatermarkSpec, WatermarkSpecError
from engine.diagnostics.runtime_logging import new_operation_identity
from engine.output.filename_policy import FEATURE_WATERMARK, build_output_filename
from engine.output.metadata_writer import write_hdde_metadata_bytes
from engine.storage.result_reuse import ResultReuseError, resolve_reusable_result_source, result_lineage_fields
from engine.storage.batch_results import BATCH_SCHEMA, batch_reference, item_identity

if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

FEATURE_KEY = "batch_watermark"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_BATCH_FILES = 100
PREVIEW_MAX_EDGE = 1600
ALLOWED_SUFFIXES = frozenset({".png", ".jpg", ".jpeg"})
PRIVATE_TEMP_PREFIX = ".hdde-batch-watermark-"
PRIVATE_TEMP_SUFFIX = ".tmp"

if os.name == "nt":
    _WIN_GENERIC_WRITE = 0x40000000
    _WIN_DELETE = 0x00010000
    _WIN_FILE_SHARE_READ = 0x00000001
    _WIN_FILE_SHARE_WRITE = 0x00000002
    _WIN_FILE_SHARE_DELETE = 0x00000004
    _WIN_CREATE_NEW = 1
    _WIN_FILE_ATTRIBUTE_NORMAL = 0x00000080
    _WIN_FILE_RENAME_INFO = 3
    _WIN_FILE_DISPOSITION_INFO = 4
    _WIN_ERROR_FILE_EXISTS = 80
    _WIN_ERROR_ALREADY_EXISTS = 183
    _WIN_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class _WindowsFileDispositionInfo(ctypes.Structure):
        _fields_ = [("delete_file", wintypes.BOOLEAN)]

    class _WindowsFileRenameInfoHeader(ctypes.Structure):
        _fields_ = [
            ("replace_if_exists", wintypes.BOOLEAN),
            ("root_directory", wintypes.HANDLE),
            ("file_name_length", wintypes.DWORD),
        ]

    _windows_create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
    _windows_create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    _windows_create_file.restype = wintypes.HANDLE
    _windows_close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
    _windows_close_handle.argtypes = (wintypes.HANDLE,)
    _windows_close_handle.restype = wintypes.BOOL
    _windows_set_file_information = ctypes.WinDLL("kernel32", use_last_error=True).SetFileInformationByHandle
    _windows_set_file_information.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    _windows_set_file_information.restype = wintypes.BOOL


def _timestamp(now_provider: Callable[[], float]) -> str:
    return datetime.fromtimestamp(now_provider(), tz=timezone.utc).isoformat()


def _safe_leaf(value: str | None) -> str:
    leaf = Path(str(value or "image.png")).name
    suffix = Path(leaf).suffix.lower()
    stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", Path(leaf).stem, flags=re.UNICODE).strip("_.")
    return f"{stem[:100] or 'image'}{suffix}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _batch_asset_path(app_root: Path, batch_id: str, *parts: str) -> Path:
    if not re.fullmatch(r"watermark_batch_[a-f0-9]{16}", batch_id) or any(
        not part or part in {".", ".."} or Path(part).name != part or ":" in part or "\\" in part
        for part in parts
    ):
        raise ValueError("批次素材标识无效。")
    target = app_root.joinpath(".运行缓存", "watermark-sources", batch_id, *parts)
    if target.resolve() != target:
        raise ValueError("批次素材路径无法安全校验。")
    return target


def _read_batch_asset(path: Path, digest: str, label: str) -> bytes:
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError(f"此批次缺少可核验的{label}记录，请重新发起批次。")
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_UPLOAD_BYTES + 1)
    except OSError as exc:
        raise ValueError(f"{label}已缺失或无法读取，请重新发起批次。") from exc
    if not data or len(data) > MAX_UPLOAD_BYTES or _sha256(data) != digest:
        raise ValueError(f"{label}与原批次记录不一致，请重新发起批次。")
    return data


def _safe_output_root(user_dirs: Mapping[str, Any]) -> tuple[Path, Path]:
    configured_root = Path(str(user_dirs.get("app_data_root") or ""))
    if not configured_root.is_absolute():
        raise RuntimeError("正式目录未就绪。")
    app_root = configured_root.resolve()
    if not app_root.is_dir():
        raise RuntimeError("正式目录未就绪。")
    target = app_root / "输出" / "批量水印"
    cursor = app_root
    for part in ("输出", "批量水印"):
        cursor = cursor / part
        if cursor.exists() and cursor.is_symlink():
            raise RuntimeError("批量水印输出目录不能经过链接目录。")
    resolved = target.resolve()
    if app_root not in resolved.parents:
        raise RuntimeError("批量水印输出目录超出正式根目录。")
    resolved.mkdir(parents=True, exist_ok=True)
    return app_root, resolved


def _output_path_candidates(output_root: Path, original_name: str, moment: datetime | None = None):
    effective_moment = moment or datetime.now()
    source = Path(_safe_leaf(original_name))
    suffix = source.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        suffix = ".png"
    yield output_root / build_output_filename(
        source.name,
        FEATURE_WATERMARK,
        suffix,
        trusted_original_filename=source.name,
        moment=effective_moment,
    )
    index = 2
    while True:
        yield output_root / build_output_filename(
            source.name,
            FEATURE_WATERMARK,
            suffix,
            trusted_original_filename=source.name,
            moment=effective_moment,
            sequence=index,
        )
        index += 1


def _open_owned_private_temp(output_root: Path):
    if os.name != "nt":
        raise RuntimeError("当前平台缺少已验证的私有临时文件句柄所有权能力。")
    while True:
        private_path = output_root / f"{PRIVATE_TEMP_PREFIX}{uuid.uuid4().hex}{PRIVATE_TEMP_SUFFIX}"
        raw_handle = _windows_create_file(
            str(private_path),
            _WIN_GENERIC_WRITE | _WIN_DELETE,
            _WIN_FILE_SHARE_READ | _WIN_FILE_SHARE_WRITE | _WIN_FILE_SHARE_DELETE,
            None,
            _WIN_CREATE_NEW,
            _WIN_FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if raw_handle == _WIN_INVALID_HANDLE_VALUE:
            error_code = ctypes.get_last_error()
            if error_code in {_WIN_ERROR_FILE_EXISTS, _WIN_ERROR_ALREADY_EXISTS}:
                continue
            raise ctypes.WinError(error_code)
        try:
            file_descriptor = msvcrt.open_osfhandle(raw_handle, os.O_BINARY | os.O_WRONLY)
        except Exception:
            _windows_close_handle(raw_handle)
            raise
        try:
            return private_path, os.fdopen(file_descriptor, "wb")
        except Exception:
            os.close(file_descriptor)
            raise


def _mark_owned_temp_for_delete(open_file) -> None:
    if os.name != "nt":
        raise RuntimeError("当前平台缺少已验证的私有临时文件句柄清理能力。")
    disposition = _WindowsFileDispositionInfo(True)
    raw_handle = msvcrt.get_osfhandle(open_file.fileno())
    if not _windows_set_file_information(
        raw_handle,
        _WIN_FILE_DISPOSITION_INFO,
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
    ):
        raise ctypes.WinError(ctypes.get_last_error())


def _atomic_publish_no_replace(open_file, candidate: Path) -> None:
    if os.name != "nt":
        raise RuntimeError("当前平台缺少已验证的原子不覆盖发布能力。")
    candidate_path = os.path.abspath(candidate)
    encoded_path = candidate_path.encode("utf-16-le")
    file_name_offset = _WindowsFileRenameInfoHeader.file_name_length.offset + ctypes.sizeof(wintypes.DWORD)
    rename_buffer = ctypes.create_string_buffer(file_name_offset + len(encoded_path) + ctypes.sizeof(wintypes.WCHAR))
    rename_header = _WindowsFileRenameInfoHeader.from_buffer(rename_buffer)
    rename_header.replace_if_exists = False
    rename_header.root_directory = None
    rename_header.file_name_length = len(encoded_path)
    ctypes.memmove(ctypes.addressof(rename_buffer) + file_name_offset, encoded_path, len(encoded_path))
    raw_handle = msvcrt.get_osfhandle(open_file.fileno())
    if not _windows_set_file_information(
        raw_handle,
        _WIN_FILE_RENAME_INFO,
        rename_buffer,
        len(rename_buffer),
    ):
        error_code = ctypes.get_last_error()
        if error_code in {_WIN_ERROR_FILE_EXISTS, _WIN_ERROR_ALREADY_EXISTS}:
            raise FileExistsError(error_code, ctypes.FormatError(error_code), candidate_path)
        raise ctypes.WinError(error_code)


def _write_without_overwrite(
    output_root: Path,
    original_name: str,
    data: bytes,
    moment: datetime | None = None,
) -> Path:
    _private_path, open_file = _open_owned_private_temp(output_root)
    try:
        written = open_file.write(data)
        if written != len(data):
            raise OSError("批量水印私有临时文件未完整写入。")
        open_file.flush()
        os.fsync(open_file.fileno())
        for candidate in _output_path_candidates(output_root, original_name, moment):
            try:
                _atomic_publish_no_replace(open_file, candidate)
                return candidate
            except FileExistsError:
                continue
        raise RuntimeError("无法分配安全的批量水印输出名称。")
    except BaseException:
        try:
            _mark_owned_temp_for_delete(open_file)
        except Exception as cleanup_error:
            raise RuntimeError("批量水印私有临时文件无法按句柄安全清理。") from cleanup_error
        raise
    finally:
        open_file.close()


def register_batch_watermark_routes(
    app,
    *,
    user_dirs_provider: Callable[[], Mapping[str, Any]],
    shared_task_registry: MutableMapping[str, dict[str, Any]],
    engine: WatermarkEngine | None = None,
    folder_opener: Callable[[str], None] | None = None,
    now_provider: Callable[[], float] = time.time,
    runtime_event_logger: Callable[..., None] | None = None,
) -> dict[str, Any]:
    from fastapi import Body, File, Form, HTTPException
    from fastapi.responses import JSONResponse, Response

    watermark_engine = engine or WatermarkEngine()

    def emit(event: str, **fields: Any) -> None:
        if runtime_event_logger is None:
            return
        try:
            runtime_event_logger(event, **fields)
        except Exception:
            return

    def require_roots() -> tuple[dict[str, Any], Path, Path]:
        user_dirs = dict(user_dirs_provider() or {})
        if user_dirs.get("directory_ready") is False:
            raise HTTPException(
                status_code=503,
                detail={"code": "FORMAL_DIRECTORY_NOT_READY", "message": str(user_dirs.get("directory_message") or "正式目录未就绪。")},
            )
        try:
            app_root, output_root = _safe_output_root(user_dirs)
        except OSError as exc:
            raise HTTPException(status_code=503, detail={"code": "WATERMARK_OUTPUT_UNSAFE", "message": "批量水印输出目录无法访问，请检查目录。"}) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"code": "WATERMARK_OUTPUT_UNSAFE", "message": str(exc)}) from exc
        return user_dirs, app_root, output_root

    def parse_spec(value: str) -> WatermarkSpec:
        try:
            payload = json.loads(value or "{}")
            if not isinstance(payload, Mapping):
                raise WatermarkSpecError("水印参数必须是对象。")
            return WatermarkSpec.from_mapping(payload)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail={"code": "WATERMARK_SPEC_INVALID", "message": "水印参数不是有效 JSON。"}) from exc
        except WatermarkSpecError as exc:
            raise HTTPException(status_code=422, detail={"code": "WATERMARK_SPEC_INVALID", "message": str(exc)}) from exc

    async def read_upload(upload: UploadFile, *, role: str) -> bytes:
        data = await upload.read(MAX_UPLOAD_BYTES + 1)
        if not data:
            raise ValueError(f"{role}为空。")
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError(f"{role}超过 50MB 限制。")
        return data

    def persist(record: dict[str, Any]) -> None:
        facts = {} if record["record_kind"] == "watermark_batch" else {str(record["task_id"]): record}
        reference = batch_reference(record)
        if reference is not None:
            facts[f"output_batch:{reference['batch_id']}"] = reference
        retry_item_ids = set(record.get("retry_item_ids") or [])
        for item in record.get("items", []):
            if retry_item_ids and item["item_id"] not in retry_item_ids:
                continue
            if not item.get("task_id") or item["task_id"] == record["task_id"]:
                continue
            if item.get("task_registered") and item["task_id"] not in shared_task_registry:
                continue
            item["task_registered"] = True
            facts[item["task_id"]] = {
                **item, "record_kind": "task", "feature_key": FEATURE_KEY,
                "task_family": FEATURE_KEY, "processing_type": FEATURE_KEY,
                "task_status": "cancelled" if item["status"] == "canceled" else item["status"],
                "created_at": record["created_at"], "updated_at": _timestamp(now_provider),
                "operation_id": record["operation_id"], "trace_id": record["trace_id"],
                "module_id": record["module_id"],
                "result": dict(item) if item["status"] == "completed" else None,
            }
        facts = copy.deepcopy(facts)
        if callable(getattr(shared_task_registry, "persist_facts", None)):
            shared_task_registry.persist_facts(facts)
        else:
            shared_task_registry.update(facts)

    active_batches: dict[str, dict[str, Any]] = {}

    @app.on_event("startup")
    async def reconcile_interrupted_watermark_batches():
        # Completed child facts are already durable. Never rerender interrupted
        # work or guess a Result from a neighboring filename.
        for record in list(shared_task_registry.values()):
            if record.get("record_kind") not in {"task", "watermark_batch"} or not record.get("batch_schema"):
                continue
            if record["record_kind"] == "watermark_batch" and record.get("batch_id") in shared_task_registry:
                continue
            if record.get("feature_key") != FEATURE_KEY or not record.get("items"):
                continue
            if any(item["status"] in {"pending", "processing"} for item in record["items"]):
                for item in record["items"]:
                    if item["status"] in {"pending", "processing"}:
                        if item["status"] == "processing":
                            item["retry_publication_unknown"] = True
                        item.update(status="failed", failure_reason="服务重启中断了该子项；未重建或猜测 Result。",
                                    result_id="", output_path="", output_sha256="")
                finish_batch(record)
                persist(record)

    def finish_batch(record):
        items = record["items"]
        completed = sum(i["status"] == "completed" for i in items)
        failed = sum(i["status"] == "failed" for i in items)
        canceled = sum(i["status"] == "canceled" for i in items)
        batch_status = "CANCELED" if canceled else "FULL_SUCCESS" if completed == len(items) else "FAILED" if not completed else "PARTIAL_SUCCESS"
        record.update(status="completed" if completed else "cancelled" if canceled else "failed",
                      task_status="completed" if completed else "cancelled" if canceled else "failed",
                      completed_at=_timestamp(now_provider), updated_at=_timestamp(now_provider))
        record["result"] = {
            "batch_id": record["task_id"], "batch_schema": BATCH_SCHEMA, "feature_key": FEATURE_KEY,
            "batch_status": batch_status, "total": len(items), "completed": completed,
            "failed": failed, "canceled": canceled, "output_directory": record["output_directory"],
            "retry_revision": record.get("retry_revision", 0),
            "items": items, "source_protection": "PASS" if all(i["source_unchanged"] for i in items if i["status"] == "completed") else "FAIL",
        }

    def resolve_result(result_id: str, app_root: Path) -> dict[str, Any]:
        try:
            return resolve_reusable_result_source(
                shared_task_registry,
                result_id,
                app_root,
                max_bytes=MAX_UPLOAD_BYTES,
                allowed_suffixes=ALLOWED_SUFFIXES,
            )
        except ResultReuseError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc

    def read_resolved_result(source: Mapping[str, Any]) -> bytes:
        try:
            data = Path(source["source_result_path"]).read_bytes()
        except OSError as exc:
            raise HTTPException(status_code=409, detail={"code": "RESULT_REUSE_FILE_UNREADABLE", "message": "原结果文件当前无法读取。"}) from exc
        if _sha256(data) != str(source.get("source_result_sha256") or ""):
            raise HTTPException(status_code=409, detail={"code": "RESULT_REUSE_INTEGRITY_MISMATCH", "message": "原结果文件在读取期间发生变化，已阻止继续处理。"})
        return data

    async def capture_source(item, entry, app_root, batch_id):
        reuse = entry["reuse"]
        if entry.get("source_result_id"):
            try:
                reuse = resolve_result(entry["source_result_id"], app_root)
            except HTTPException as exc:
                raise ValueError(exc.detail["message"]) from exc
            item["file_name"] = reuse["source_result_file_name"]
        if Path(item["file_name"]).suffix.lower() not in ALLOWED_SUFFIXES:
            raise ValueError("仅支持 PNG、JPG、JPEG 源图片。")
        if reuse:
            source_bytes = entry["data"] if "data" in entry else read_resolved_result(reuse)
        else:
            source_bytes = await read_upload(entry["upload"], role="源图片")
        source_sha = _sha256(source_bytes)
        source_path = _batch_asset_path(app_root, batch_id, item["item_id"], item["file_name"])
        source_path.parent.mkdir(parents=True, exist_ok=True)
        with source_path.open("xb") as stream:
            stream.write(source_bytes)
        item.update(source_path=str(source_path), source_sha_before=source_sha, source_sha256=source_sha,
                    original_bytes=len(source_bytes), **result_lineage_fields(reuse))
        return source_bytes

    def retry_source(item, app_root, batch_id):
        if item.get("retry_publication_unknown"):
            raise ValueError("上次中断时成品写入状态无法确认，请重新发起批次。")
        item_id = str(item.get("item_id") or "")
        if not re.fullmatch(r"watermark_item_[a-f0-9]{12}", item_id):
            raise ValueError("此批次缺少可核验的原图标识，请重新发起批次。")
        try:
            expected = _batch_asset_path(app_root, batch_id, item_id, str(item.get("file_name") or ""))
        except ValueError as exc:
            raise ValueError("原图副本路径无法安全校验，请重新发起批次。") from exc
        digest = str(item.get("source_sha256") or "")
        if Path(str(item.get("source_path") or "")) != expected or digest != item.get("source_sha_before"):
            raise ValueError("此条目缺少可核验的原图副本记录，请重新发起批次。")
        source_bytes = _read_batch_asset(expected, digest, "原图副本")
        if item.get("source_result_id") and not item.get("source_result_sha256"):
            try:
                reuse = resolve_result(item["source_result_id"], app_root)
            except HTTPException as exc:
                raise ValueError("原成品来源无法校验，请重新发起批次。") from exc
            if reuse["source_result_sha256"] != digest:
                raise ValueError("原成品来源与批次记录不一致，请重新发起批次。")
            item.update(result_lineage_fields(reuse))
        return source_bytes

    async def process_batch(record, work, app_root, output_root, spec, watermark_bytes, batch_moment):
        batch_id = record["batch_id"]
        identity = {key: record[key] for key in ("operation_id", "trace_id", "module_id")}
        emit("PROCESS_STARTED", stage="engine_execution", result="started", task_id=batch_id, **identity)
        for item, entry in work:
            if record.get("cancel_requested"):
                item.update(status="canceled", failure_reason="已取消，未创建 Result。")
                item["lifecycle"].append({"status": "canceled", "recorded_at": _timestamp(now_provider)})
                persist(record)
                continue
            item["status"] = "processing"
            item["lifecycle"].append({"status": "processing", "recorded_at": _timestamp(now_provider)})
            try:
                if entry is None:
                    source_bytes = retry_source(item, app_root, batch_id)
                else:
                    source_bytes = await capture_source(item, entry, app_root, batch_id)
                source_sha = _sha256(source_bytes)
                persist(record)
                rendered = await asyncio.to_thread(watermark_engine.render, source_bytes, spec, watermark_bytes=watermark_bytes)
                final_data, output_metadata = write_hdde_metadata_bytes(
                    rendered.data,
                    source_data=source_bytes,
                    normalize_orientation=True,
                )
                result_fields = {
                    "result_id": f"watermark_result_{uuid.uuid4().hex[:16]}",
                    "feature_key": FEATURE_KEY,
                    "status": "completed",
                    "output_sha256": _sha256(final_data),
                    "output_size_bytes": len(final_data),
                    "final_bytes": len(final_data),
                    "source_sha_after": source_sha,
                    "source_unchanged": item["source_sha_before"] == source_sha,
                    "render_facts": rendered.facts(),
                    "output_metadata": output_metadata,
                    "original_filename": item["file_name"],
                }
                output_path = _write_without_overwrite(output_root, item["file_name"], final_data, batch_moment)
                item.update(result_fields, output_path=str(output_path), result_file=str(output_path),
                            output_file_name=output_path.name)
            except OSError:
                item.update(status="failed", failure_reason="无法写入水印素材或成品，请检查目录后重试。")
            except Exception as exc:
                reason = str(exc) or exc.__class__.__name__
                if entry is None and isinstance(exc, ValueError) and "请重新发起批次" not in reason:
                    reason = f"{reason} 请核对原素材后重新发起批次。"
                item.update(status="failed", failure_reason=reason)
            item["lifecycle"].append({"status": item["status"], "recorded_at": _timestamp(now_provider)})
            persist(record)

        finish_batch(record)
        persist(record)
        result = record["result"]
        emit("PROCESS_SUCCEEDED" if result["completed"] else "PROCESS_FAILED", stage="engine_execution", result=result["batch_status"].lower(), task_id=batch_id, **identity)
        return {"success": result["completed"] > 0, "status": result["batch_status"], "data": result}

    register_watermark_presets(app, require_roots, parse_spec, read_upload)

    @app.get("/api/batch-watermark/capabilities")
    async def batch_watermark_capabilities():
        require_roots()
        return {"success": True, "data": {"available": True, "max_files": MAX_BATCH_FILES, "formats": ["png", "jpg", "jpeg"]}}

    def check_batch_capacity(app_root, output_root, source_bytes, logo_bytes):
        require_batch_capacity(
            (app_root / ".运行缓存" / "watermark-sources", source_bytes + logo_bytes, "水印素材缓存"),
            (output_root, source_bytes, "水印输出"),
        )

    @app.post("/api/batch-watermark/batches/preflight")
    async def watermark_batch_preflight(payload: dict = Body(...)):
        source_bytes = batch_size_field(payload, "source_bytes")
        logo_bytes = batch_size_field(payload, "logo_bytes")
        if not 0 < source_bytes <= MAX_BATCH_FILES * MAX_UPLOAD_BYTES or logo_bytes > MAX_UPLOAD_BYTES:
            raise HTTPException(400, detail={"code": "BATCH_SIZE_INVALID", "message": "批次文件体积超出水印输入限制。"})
        _, app_root, output_root = require_roots()
        await asyncio.to_thread(check_batch_capacity, app_root, output_root, source_bytes, logo_bytes)
        return {"success": True}

    @app.post("/api/batch-watermark/preview")
    async def batch_watermark_preview(
        file: UploadFile | None = File(None),
        result_id: str = Form(""),
        spec_json: str = Form(...),
        watermark_file: UploadFile | None = File(None),
        fit_preview: bool = Form(False),
    ):
        _, app_root, _ = require_roots()
        normalized_result_id = str(result_id or "").strip()
        if (file is None) == (not normalized_result_id):
            raise HTTPException(status_code=400, detail={"code": "WATERMARK_SOURCE_INVALID", "message": "必须且只能提供一个上传文件或正式结果编号。"})
        spec = parse_spec(spec_json)
        try:
            source_bytes = read_resolved_result(resolve_result(normalized_result_id, app_root)) if normalized_result_id else await read_upload(file, role="源图片")
            watermark_bytes = await read_upload(watermark_file, role="图片水印") if watermark_file is not None else None
            rendered = watermark_engine.render(
                source_bytes, spec, watermark_bytes=watermark_bytes, output_format="PNG",
                preview_max_edge=PREVIEW_MAX_EDGE if fit_preview else None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "WATERMARK_PREVIEW_REJECTED", "message": str(exc)}) from exc
        return Response(
            content=rendered.data,
            media_type="image/png",
            headers={"X-HDDE-Watermark-Engine": watermark_engine.engine_id, "Cache-Control": "no-store"},
        )

    @app.post("/api/batch-watermark/batches")
    async def create_batch_watermark(
        request: Request,
        files: list[UploadFile] | None = File(None),
        result_ids_json: str = Form("[]"),
        spec_json: str = Form(...),
        watermark_file: UploadFile | None = File(None),
        batch_id: str = Form(""),
        entries_json: str | None = Form(None),
    ):
        _, app_root, output_root = require_roots()
        try:
            parsed_result_ids = json.loads(result_ids_json or "[]")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail={"code": "WATERMARK_RESULT_IDS_INVALID", "message": "继续处理结果列表不是有效 JSON。"}) from exc
        if not isinstance(parsed_result_ids, list) or any(not str(value or "").strip() for value in parsed_result_ids):
            raise HTTPException(status_code=400, detail={"code": "WATERMARK_RESULT_IDS_INVALID", "message": "继续处理结果列表无效。"})
        if entries_json is None:
            reusable_sources = [resolve_result(str(value).strip(), app_root) for value in parsed_result_ids]
            source_entries = [
                {"file_name": _safe_leaf(upload.filename), "upload": upload, "reuse": None}
                for upload in files or []
            ] + [
                {"file_name": source["source_result_file_name"], "upload": None, "reuse": source, "data": read_resolved_result(source)}
                for source in reusable_sources
            ]
        else:
            invalid_entries = HTTPException(400, detail={"code": "WATERMARK_BATCH_ENTRIES_INVALID", "message": "批量水印图片清单无效，请重新选择图片。"})
            try:
                manifest = json.loads(entries_json)
            except json.JSONDecodeError as exc:
                raise invalid_entries from exc
            if not isinstance(manifest, list) or files or parsed_result_ids:
                raise invalid_entries
            if not 1 <= len(manifest) <= MAX_BATCH_FILES:
                raise HTTPException(400, detail={"code": "WATERMARK_BATCH_SIZE_INVALID", "message": "每批请选择 1 到 100 张图片。"})
            form = await request.form()
            source_entries = []
            seen_ids = set()
            for entry in manifest:
                if not isinstance(entry, dict):
                    raise invalid_entries
                client_id = entry.get("id")
                result_id = entry.get("result_id", "")
                file_name = entry.get("file_name", "")
                if (
                    not isinstance(client_id, str) or not re.fullmatch(r"[a-f0-9]{32}", client_id)
                    or client_id in seen_ids or not isinstance(result_id, str) or not isinstance(file_name, str)
                ):
                    raise invalid_entries
                upload_fields = form.getlist(f"file_{client_id}")
                if result_id.strip():
                    if upload_fields:
                        raise invalid_entries
                    upload = None
                else:
                    if len(upload_fields) != 1 or not isinstance(upload_fields[0], MultipartUpload):
                        raise invalid_entries
                    upload = upload_fields[0]
                seen_ids.add(client_id)
                source_entries.append({
                    "client_item_id": client_id,
                    "file_name": _safe_leaf(upload.filename if upload is not None else file_name),
                    "source_result_id": result_id.strip(),
                    "upload": upload,
                    "reuse": None,
                })
        if not source_entries or len(source_entries) > MAX_BATCH_FILES:
            raise HTTPException(status_code=400, detail={"code": "WATERMARK_BATCH_SIZE_INVALID", "message": "每批请选择 1 到 100 张图片。"})
        spec = parse_spec(spec_json)
        try:
            watermark_bytes = await read_upload(watermark_file, role="图片水印") if watermark_file is not None else None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "WATERMARK_LOGO_INVALID", "message": str(exc)}) from exc

        sizes = [int(getattr(entry.get("upload"), "size", 0) or len(entry.get("data") or b"")) for entry in source_entries]
        cache_bytes = sum(size for size in sizes if size <= MAX_UPLOAD_BYTES)
        await asyncio.to_thread(check_batch_capacity, app_root, output_root, cache_bytes, len(watermark_bytes or b""))

        batch_id = batch_id or f"watermark_batch_{uuid.uuid4().hex[:16]}"
        if not re.fullmatch(r"watermark_batch_[a-f0-9]{16}", batch_id):
            raise HTTPException(400, detail="批量水印批次标识无效。")
        if batch_id in shared_task_registry or f"output_batch:{batch_id}" in shared_task_registry:
            raise HTTPException(409, detail="批次已登记，请读取原批次，不能重复创建。")
        identity = new_operation_identity(FEATURE_KEY, module_id="hdde.batch.watermark")
        batch_created_epoch = now_provider()
        batch_moment = datetime.fromtimestamp(batch_created_epoch)
        created_at = datetime.fromtimestamp(batch_created_epoch, tz=timezone.utc).isoformat()
        items = [
            {
                "item_id": f"watermark_item_{uuid.uuid4().hex[:12]}",
                "task_id": f"watermark_{uuid.uuid4().hex[:16]}",
                "result_id": "",
                "output_sha256": "",
                "source_path": "",
                "original_bytes": int(getattr(entry.get("upload"), "size", 0) or len(entry.get("data") or b"")),
                "file_name": entry["file_name"],
                "status": "pending",
                "failure_reason": "",
                "output_path": "",
                "output_file_name": "",
                "source_sha_before": "",
                "source_sha_after": "",
                "source_unchanged": False,
                "lifecycle": [{"status": "pending", "recorded_at": created_at}],
            }
            for entry in source_entries
        ]
        for entry, item in zip(source_entries, items):
            item.update(item_identity(batch_id, item["item_id"], FEATURE_KEY))
            if "client_item_id" in entry:
                item["client_item_id"] = entry["client_item_id"]
            if entry.get("source_result_id"):
                item["source_result_id"] = entry["source_result_id"]
        record = {
            "task_id": batch_id,
            "batch_id": batch_id,
            "batch_schema": BATCH_SCHEMA,
            **identity,
            "record_kind": "task",
            "feature_key": FEATURE_KEY,
            "task_family": FEATURE_KEY,
            "processing_type": FEATURE_KEY,
            "status": "pending",
            "task_status": "pending",
            "created_at": created_at,
            "updated_at": created_at,
            "output_directory": str(output_root),
            "spec": spec.to_dict(),
            "items": items,
            "result": None,
        }
        if spec.kind == "image" and watermark_bytes:
            try:
                logo_path = _batch_asset_path(app_root, batch_id, "logo.png")
                logo_path.parent.mkdir(parents=True, exist_ok=True)
                with logo_path.open("xb") as stream:
                    stream.write(watermark_bytes)
            except (OSError, ValueError) as exc:
                raise HTTPException(503, detail="无法保存原透明 PNG Logo，尚未开始批量水印。") from exc
            record["logo_sha256"] = _sha256(watermark_bytes)
        try:
            persist(record)
        except Exception as exc:
            raise HTTPException(status_code=500, detail={"code": "WATERMARK_TASK_REGISTRATION_FAILED", "message": "无法登记批量水印任务，尚未创建输出。"}) from exc
        emit("TASK_CREATED", stage="task_registration", result="success", task_id=batch_id, **identity)
        record.update({"status": "processing", "task_status": "processing", "updated_at": _timestamp(now_provider)})
        persist(record)
        active_batches[batch_id] = record
        try:
            return await process_batch(record, zip(items, source_entries), app_root, output_root,
                                       spec, watermark_bytes, batch_moment)
        finally:
            active_batches.pop(batch_id, None)

    @app.post("/api/batch-watermark/batches/{batch_id}/retry-failed")
    async def retry_failed_watermark_items(batch_id: str, payload: dict = Body(...)):
        expected_revision = payload.get("retry_revision")
        if set(payload) != {"retry_revision"} or type(expected_revision) is not int or expected_revision < 0:
            raise HTTPException(400, detail="批量水印重试版本无效，请重新打开批次。")
        if batch_id in active_batches:
            raise HTTPException(409, detail="该批次仍在运行，请等待结束。")
        record = shared_task_registry.get(batch_id) or shared_task_registry.get(f"output_batch:{batch_id}")
        if not isinstance(record, Mapping) or record.get("feature_key") != FEATURE_KEY or record.get("batch_id") != batch_id:
            raise HTTPException(404, detail="批量水印任务不存在。")
        result = record.get("result")
        revision = record.get("retry_revision", 0)
        if not result or expected_revision > revision:
            raise HTTPException(409, detail="批次结果尚未就绪，请重新打开批次。")
        failed = [item for item in record["items"] if item["status"] == "failed"]
        if expected_revision < revision or not failed:
            return {"success": result["completed"] > 0, "status": result["batch_status"], "data": result}

        _, app_root, output_root = require_roots()
        if Path(str(record.get("output_directory") or "")) != output_root:
            raise HTTPException(409, detail="批次输出目录与当前正式目录不一致，请重新发起批次。")
        record = copy.deepcopy(record)
        failed = [item for item in record["items"] if item["status"] == "failed"]
        record["retry_revision"] = revision + 1
        record["retry_item_ids"] = [item["item_id"] for item in failed]
        try:
            raw_spec = record.get("spec")
            spec = WatermarkSpec.from_mapping(raw_spec) if isinstance(raw_spec, Mapping) else None
            if spec is None or spec.to_dict() != raw_spec:
                raise ValueError("旧批次缺少完整的原水印参数，请重新发起批次。")
            batch_moment = datetime.fromisoformat(record["created_at"]).astimezone().replace(tzinfo=None)
            watermark_bytes = None
            if spec.kind == "image":
                watermark_bytes = _read_batch_asset(
                    _batch_asset_path(app_root, batch_id, "logo.png"),
                    str(record.get("logo_sha256") or ""), "原透明 PNG Logo",
                )
        except (OSError, ValueError, RuntimeError) as exc:
            reason = str(exc)
            if "请重新发起批次" not in reason:
                reason = "原批次参数或 Logo 无法安全校验，请重新发起批次。"
            for item in failed:
                item["failure_reason"] = reason
            finish_batch(record)
            persist(record)
            result = record["result"]
            return {"success": result["completed"] > 0, "status": result["batch_status"], "data": result}

        record.pop("cancel_requested", None)
        record.update(status="processing", task_status="processing", result=None, updated_at=_timestamp(now_provider))
        for item in failed:
            item.update(status="pending", failure_reason="")
            item["lifecycle"].append({"status": "pending", "recorded_at": _timestamp(now_provider)})
        persist(record)
        active_batches[batch_id] = record
        try:
            return await process_batch(record, ((item, None) for item in failed), app_root, output_root,
                                       spec, watermark_bytes, batch_moment)
        finally:
            active_batches.pop(batch_id, None)

    @app.post("/api/batch-watermark/batches/{batch_id}/control")
    async def cancel_watermark_batch(batch_id: str, payload: dict = Body(...)):
        if payload != {"action": "cancel"}:
            raise HTTPException(400, detail="批量水印仅支持取消尚未开始的子项。")
        record = active_batches.get(batch_id)
        if record is None:
            raise HTTPException(409, detail="该批次已结束或当前没有执行中的批次。")
        record["cancel_requested"] = True
        persist(record)
        return {"success": True, "data": {"batch_id": batch_id, "cancel_requested": True}}

    @app.get("/api/batch-watermark/batches/{batch_id}")
    async def get_batch_watermark(batch_id: str):
        record = shared_task_registry.get(str(batch_id)) or shared_task_registry.get(f"output_batch:{batch_id}")
        if not isinstance(record, Mapping) or record.get("feature_key") != FEATURE_KEY:
            raise HTTPException(status_code=404, detail={"code": "WATERMARK_BATCH_NOT_FOUND", "message": "批量水印任务不存在。"})
        return {"success": True, "status": record.get("status"), "data": record.get("result") or record}

    @app.post("/api/batch-watermark/open-output-folder")
    async def open_batch_watermark_folder(payload: dict = Body(default_factory=dict)):
        _, _, output_root = require_roots()
        batch_id = str(payload.get("batch_id") or "")
        record = shared_task_registry.get(batch_id)
        if not isinstance(record, Mapping) or record.get("feature_key") != FEATURE_KEY:
            raise HTTPException(status_code=404, detail={"code": "WATERMARK_BATCH_NOT_FOUND", "message": "批量水印任务不存在。"})
        if Path(str(record.get("output_directory") or "")).resolve() != output_root:
            raise HTTPException(status_code=409, detail={"code": "WATERMARK_OUTPUT_MISMATCH", "message": "任务输出目录与当前正式目录不一致。"})
        try:
            if folder_opener is not None:
                folder_opener(str(output_root))
            elif os.name == "nt":
                os.startfile(str(output_root))  # noqa: S606 - fixed, validated formal output directory
            else:
                raise OSError("当前环境不支持打开本地文件夹。")
        except OSError as exc:
            raise HTTPException(status_code=500, detail={"code": "WATERMARK_FOLDER_OPEN_FAILED", "message": str(exc)}) from exc
        return JSONResponse({"success": True, "path": str(output_root)})

    return {"engine": watermark_engine, "feature_key": FEATURE_KEY, "active_batches": active_batches}
