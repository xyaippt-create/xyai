from __future__ import annotations

import base64
import hashlib
import io
import logging
import math
import mimetypes
import os
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping

from fastapi import UploadFile
from PIL import Image, ImageOps

from engine.diagnostics.runtime_logging import build_exception_diagnostics, new_operation_identity
from engine.local_retouch import LocalRetouchEngine
from engine.output.filename_policy import FEATURE_RETOUCH, build_output_path
from engine.output.metadata_writer import write_hdde_metadata
from engine.storage.result_reuse import (
    ResultReuseError,
    resolve_reusable_result_source,
    result_lineage_fields,
)


MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_MASK_BYTES = 64 * 1024 * 1024
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg"}
LOCAL_RETOUCH_FEATURE_KEY = "local_retouch"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_dpi(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return None
    try:
        dpi = (float(value[0]), float(value[1]))
    except (TypeError, ValueError):
        return None
    return dpi if all(math.isfinite(item) and item > 0 for item in dpi) else None


def _safe_filename(value: str) -> str:
    leaf = Path(str(value or "")).name
    stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", Path(leaf).stem, flags=re.UNICODE).strip("_.")
    suffix = Path(leaf).suffix.lower()
    return f"{stem[:96] or 'image'}{suffix}"


def _is_within(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False


def _ensure_safe_directory(path: Path, root: Path) -> Path:
    resolved_root = Path(root).resolve()
    resolved = Path(path).resolve()
    if not _is_within(resolved, resolved_root):
        raise RuntimeError("瑕疵修复目录安全校验失败。")
    cursor = resolved_root
    try:
        relative = resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError("瑕疵修复目录安全校验失败。") from exc
    for part in relative.parts:
        cursor = cursor / part
        if cursor.exists() and cursor.is_symlink():
            raise RuntimeError("瑕疵修复目录不能经过链接目录。")
    return resolved


def register_local_retouch_routes(
    app,
    *,
    user_dirs_provider: Callable[[], Mapping[str, Any]],
    shared_task_registry: MutableMapping[str, dict[str, Any]],
    engine: LocalRetouchEngine | None = None,
    folder_opener: Callable[[str], None] | None = None,
    now_provider: Callable[[], float] = time.time,
    runtime_event_logger: Callable[..., None] | None = None,
) -> dict[str, Any]:
    from fastapi import Body, File, HTTPException
    from fastapi.responses import FileResponse

    retouch_engine = engine or LocalRetouchEngine()
    sessions: dict[str, dict[str, Any]] = {}

    def emit_runtime_event(event: str, **fields: Any) -> None:
        if runtime_event_logger is None:
            return
        try:
            runtime_event_logger(event, **fields)
        except Exception:
            return

    def task_event_fields(record: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
        return {
            "feature_key": LOCAL_RETOUCH_FEATURE_KEY,
            "module_id": record.get("module_id") or "",
            "operation_id": record.get("operation_id") or "",
            "trace_id": record.get("trace_id") or "",
            "task_id": record.get("task_id") or "",
            "result_id": record.get("result_id") or "",
            "status": record.get("status") or "",
            **extra,
        }

    def timestamp(value: float | None = None) -> str:
        return datetime.fromtimestamp(value if value is not None else now_provider(), tz=timezone.utc).isoformat()

    def next_task_id() -> str:
        task_id = f"retouch_task_{uuid.uuid4().hex[:16]}"
        while task_id in shared_task_registry:
            task_id = f"retouch_task_{uuid.uuid4().hex[:16]}"
        return task_id

    def next_result_id() -> str:
        registered_result_ids = {
            str(record.get("result_id") or "")
            for record in shared_task_registry.values()
            if isinstance(record, Mapping)
        }
        result_id = f"retouch_result_{uuid.uuid4().hex[:16]}"
        while result_id in shared_task_registry or result_id in registered_result_ids:
            result_id = f"retouch_result_{uuid.uuid4().hex[:16]}"
        return result_id

    def transition_task(
        record: dict[str, Any],
        status: str,
        progress: int,
        *,
        failure_reason: str | None = None,
    ) -> None:
        recorded_at = timestamp()
        record.update(
            {
                "status": status,
                "task_status": status,
                "progress": progress,
                "task_progress": progress,
                "updated_at": recorded_at,
                "failure_reason": failure_reason,
                "error_message": failure_reason or "",
            }
        )
        record.setdefault("lifecycle", []).append(
            {"task_id": record["task_id"], "status": status, "progress": progress, "recorded_at": recorded_at}
        )
        if status in {"completed", "failed"}:
            record["completed_at"] = recorded_at
            try:
                shared_task_registry[str(record["task_id"])] = record
            except Exception:
                # Preview lifecycle persistence must not change the existing product path.
                pass

    def attach_error_context(record: dict[str, Any], exc: BaseException, stage: str) -> dict[str, str]:
        diagnostics = build_exception_diagnostics(
            exc,
            error_category="ENVIRONMENT_ERROR" if isinstance(exc, OSError) else "PRODUCT_ERROR",
            error_stage=stage,
            trace_id=str(record.get("trace_id") or ""),
        )
        record["error_context"] = dict(diagnostics)
        return diagnostics

    def require_task_for_session(session: Mapping[str, Any]) -> dict[str, Any]:
        task_id = str(session.get("task_id") or "")
        task = shared_task_registry.get(task_id)
        if not task or task.get("feature_key") != LOCAL_RETOUCH_FEATURE_KEY:
            raise HTTPException(
                status_code=409,
                detail={"code": "RETOUCH_TASK_MISSING", "message": "当前修整任务记录已失效，请重新处理。"},
            )
        return task

    def require_roots() -> tuple[dict[str, Any], Path, Path, Path]:
        user_dirs = dict(user_dirs_provider() or {})
        if user_dirs.get("directory_ready") is False:
            raise HTTPException(
                status_code=409,
                detail={"code": "FORMAL_DIRECTORY_NOT_READY", "message": str(user_dirs.get("directory_message") or "正式目录未就绪。")},
            )
        app_root = Path(user_dirs.get("app_data_root") or "").resolve()
        if not app_root.is_dir():
            raise HTTPException(status_code=409, detail={"code": "FORMAL_DIRECTORY_NOT_READY", "message": "正式目录未就绪。"})
        runtime_root = _ensure_safe_directory(Path(user_dirs.get("tmp_dir") or (app_root / "临时文件")) / "local-retouch", app_root)
        output_root = _ensure_safe_directory(app_root / "输出" / "瑕疵修复", app_root)
        return user_dirs, app_root, runtime_root, output_root

    def require_session(session_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{32}", str(session_id or "")):
            raise HTTPException(status_code=404, detail={"code": "RETOUCH_SESSION_NOT_FOUND", "message": "当前修整会话已失效，请重新导入图片。"})
        session = sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail={"code": "RETOUCH_SESSION_NOT_FOUND", "message": "当前修整会话已失效，请重新导入图片。"})
        return session

    def session_payload(session: Mapping[str, Any]) -> dict[str, Any]:
        result = session.get("result") or {}
        output = session.get("output") or {}
        session_id = str(session["session_id"])
        task_id = str(session.get("task_id") or "")
        task = shared_task_registry.get(task_id) if task_id else {}
        working_revision = int(session.get("working_revision") or 0)
        previous_working_revision = session.get("previous_working_revision")
        can_back_to_previous = (
            not bool(output)
            and not bool(session.get("processing"))
            and len(session.get("working_history") or []) > 1
            and isinstance(previous_working_revision, int)
            and previous_working_revision >= 0
        )
        return {
            "session_id": session_id,
            "feature_key": LOCAL_RETOUCH_FEATURE_KEY,
            "module_id": str((task or {}).get("module_id") or ""),
            "operation_id": str((task or {}).get("operation_id") or ""),
            "trace_id": str((task or {}).get("trace_id") or ""),
            "task_id": task_id,
            "task_status": str((task or {}).get("status") or ""),
            "file_name": session["file_name"],
            "width": session["width"],
            "height": session["height"],
            "format": session["format"],
            "source_sha256": session["source_sha256"],
            "source_origin": str(session.get("source_origin") or ""),
            "source_result_id": str(session.get("source_result_id") or ""),
            "source_task_id": str(session.get("source_task_id") or ""),
            "source_feature_key": str(session.get("source_feature_key") or ""),
            "source_result_sha256": str(session.get("source_result_sha256") or ""),
            "source_url": f"/api/local-retouch/sessions/{session_id}/source",
            "working_source_url": f"/api/local-retouch/sessions/{session_id}/working-source",
            "result_url": f"/api/local-retouch/sessions/{session_id}/result" if result else "",
            "previous_result_url": (
                f"/api/local-retouch/sessions/{session_id}/previous-result"
                if session.get("previous_working_path")
                else ""
            ),
            "working_revision": working_revision,
            "previous_working_revision": previous_working_revision,
            "working_sha256": session["working_sha256"],
            "can_back_to_previous": can_back_to_previous,
            "processing": bool(session.get("processing")),
            "mask_revision": result.get("mask_revision"),
            "engine_id": result.get("engine_id") or "",
            "inference_seconds": result.get("inference_seconds"),
            "confirmed": bool(session.get("confirmed")),
            "saved": bool(output),
            "result_id": output.get("result_id") or "",
            "output_file_name": output.get("file_name") or "",
            "output_directory_name": output.get("directory_name") or "",
            "output_url": f"/api/local-retouch/sessions/{session_id}/output" if output else "",
            "retry_source": "working_source",
        }

    def resume_authority(task_id: str, result_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        normalized_task_id = str(task_id or "").strip()
        normalized_result_id = str(result_id or "").strip()

        def decision(status: str, *, session: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
            available = status == "AVAILABLE" and session is not None
            return (
                {
                    "available": available,
                    "status": status,
                    "task_id": normalized_task_id,
                    "result_id": normalized_result_id,
                    "session_id": str(session.get("session_id") or "") if available else "",
                },
                session if available else None,
            )

        if not normalized_task_id or not normalized_result_id:
            return decision("INVALID_BINDING")
        task = shared_task_registry.get(normalized_task_id)
        if not isinstance(task, Mapping) or task.get("feature_key") != LOCAL_RETOUCH_FEATURE_KEY:
            return decision("TASK_MISSING")
        registered_result_id = str(task.get("result_id") or "")
        task_result = task.get("result") or task.get("task_result") or {}
        if not registered_result_id or not isinstance(task_result, Mapping) or not task_result:
            return decision("RESULT_MISSING")
        if registered_result_id != normalized_result_id or str(task_result.get("result_id") or "") != normalized_result_id:
            return decision("INVALID_BINDING")

        candidates = []
        committed_candidates = []
        for session in sessions.values():
            if not isinstance(session, Mapping):
                continue
            output = session.get("output") or {}
            if (
                str(output.get("task_id") or "") == normalized_task_id
                and str(output.get("result_id") or "") == normalized_result_id
            ):
                candidates.append(session)
            elif (
                not output
                and str(session.get("task_id") or "") == normalized_task_id
                and str(session.get("resume_committed_result_id") or "") == normalized_result_id
            ):
                committed_candidates.append(session)
        if not candidates and committed_candidates:
            candidates = committed_candidates
        if not candidates:
            return decision("SESSION_MISSING")
        if len(candidates) != 1:
            return decision("INVALID_BINDING")

        session = candidates[0]
        output = session.get("output") or {}
        if str(session.get("task_id") or "") != normalized_task_id:
            return decision("INVALID_BINDING")
        if session.get("processing"):
            return decision("UNAVAILABLE")
        source_path = Path(session.get("upload_path") or "")
        working_path = Path(session.get("working_path") or "")
        output_path = Path(output.get("path") or task_result.get("output_path") or task_result.get("result_file") or "")
        required_assets = (
            (source_path, str(session.get("source_sha256") or "")),
            (working_path, str(session.get("working_sha256") or "")),
            (output_path, str(output.get("sha256") or task_result.get("output_sha256") or "")),
        )
        try:
            assets_valid = all(path.is_file() and expected and _sha256(path) == expected for path, expected in required_assets)
        except OSError:
            assets_valid = False
        if not assets_valid or not session.get("result"):
            return decision("EXPIRED")
        return decision("AVAILABLE", session=session)

    def resume_response_data(session: Mapping[str, Any], *, phase: str, result_id: str, duplicate: bool = False) -> dict[str, Any]:
        return {
            **session_payload(session),
            "resume_phase": phase,
            "resume_result_id": result_id,
            "resume_duplicate": duplicate,
        }

    @app.get("/api/local-retouch/capabilities")
    async def local_retouch_capabilities():
        require_roots()
        capabilities = retouch_engine.capabilities()
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "data": {
                "available": bool(capabilities.get("available")),
                "engine": "Local Retouch Engine",
                "adapter": "LaMa",
                "reason": str(capabilities.get("reason") or ""),
                "supported_formats": ["PNG", "JPEG"],
                "max_upload_bytes": MAX_UPLOAD_BYTES,
                "max_image_pixels": MAX_IMAGE_PIXELS,
            },
        }

    def create_local_retouch_session(
        content: bytes,
        raw_name: str,
        lineage: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        _, app_root, runtime_root, _ = require_roots()
        if not raw_name or raw_name != Path(raw_name).name or "/" in raw_name or "\\" in raw_name:
            raise HTTPException(status_code=400, detail={"code": "RETOUCH_FILENAME_INVALID", "message": "文件名不得包含目录信息。"})
        safe_name = _safe_filename(raw_name)
        suffix = Path(safe_name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=415, detail={"code": "RETOUCH_FORMAT_UNSUPPORTED", "message": "仅支持PNG、JPG和JPEG图片。"})
        if not content or len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail={"code": "RETOUCH_FILE_TOO_LARGE", "message": "图片为空或超过50MB限制。"})
        try:
            with Image.open(io.BytesIO(content)) as opened:
                opened.verify()
            with Image.open(io.BytesIO(content)) as opened:
                source_dpi = _valid_dpi(opened.info.get("dpi"))
                normalized = ImageOps.exif_transpose(opened)
                normalized.load()
                width, height = normalized.size
                if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                    raise ValueError("图片像素数量超出安全范围。")
                if normalized.mode not in {"RGB", "RGBA"}:
                    normalized = normalized.convert("RGBA" if "A" in normalized.getbands() else "RGB")
                working = normalized.copy()
                source_format = "PNG" if opened.format == "PNG" else "JPEG"
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"code": "RETOUCH_IMAGE_INVALID", "message": "图片损坏、无法解码或尺寸超出安全范围。"}) from exc

        session_id = uuid.uuid4().hex
        session_root = _ensure_safe_directory(runtime_root / session_id, app_root)
        session_root.mkdir(parents=True, exist_ok=False)
        upload_path = _ensure_safe_directory(session_root / safe_name, app_root)
        working_path = _ensure_safe_directory(session_root / "working_source.png", app_root)
        try:
            upload_path.write_bytes(content)
            save_options = {"dpi": source_dpi} if source_dpi is not None else {}
            working.save(working_path, format="PNG", optimize=False, **save_options)
            with Image.open(working_path) as verified:
                verified.load()
                if verified.size != (width, height):
                    raise RuntimeError("工作图尺寸验证失败。")
        except Exception:
            shutil.rmtree(session_root, ignore_errors=True)
            raise

        lineage_fields = result_lineage_fields(lineage)
        sessions[session_id] = {
            "session_id": session_id,
            "root": session_root,
            "upload_path": upload_path,
            "working_path": working_path,
            "file_name": safe_name,
            "source_sha256": hashlib.sha256(content).hexdigest(),
            "source_size_bytes": len(content),
            "source_mtime_ns": upload_path.stat().st_mtime_ns,
            "working_sha256": _sha256(working_path),
            "working_revision": 0,
            "previous_working_path": None,
            "previous_working_revision": None,
            "working_history": [
                {
                    "working_revision": 0,
                    "parent_working_revision": None,
                    "path": working_path,
                    "sha256": _sha256(working_path),
                    "task_id": "",
                    "result": None,
                }
            ],
            "width": width,
            "height": height,
            "format": source_format,
            "created_at": now_provider(),
            "result": None,
            "confirmed": False,
            "confirmed_at": None,
            "task_id": "",
            "output": None,
            "processing": False,
            "resume_committed_result_id": "",
            "resume_committed_task_id": "",
            **lineage_fields,
        }
        return session_payload(sessions[session_id])

    @app.post("/api/local-retouch/intake")
    async def local_retouch_intake(file: UploadFile = File(...)):
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        data = create_local_retouch_session(content, str(file.filename or ""))
        return {"code": 200, "status": "success", "success": True, "data": data}

    @app.post("/api/local-retouch/intake-result")
    async def local_retouch_intake_result(payload: dict[str, Any] = Body(default_factory=dict)):
        if set(payload) != {"result_id"}:
            raise HTTPException(
                status_code=400,
                detail={"code": "RESULT_REUSE_REQUEST_INVALID", "message": "继续处理请求字段不正确。"},
            )
        _, app_root, _, _ = require_roots()
        try:
            reusable = resolve_reusable_result_source(
                shared_task_registry,
                str(payload.get("result_id") or ""),
                app_root,
                max_bytes=MAX_UPLOAD_BYTES,
                allowed_suffixes=ALLOWED_SUFFIXES,
            )
            content = Path(reusable["source_result_path"]).read_bytes()
            if hashlib.sha256(content).hexdigest() != reusable["source_result_sha256"]:
                raise ResultReuseError(
                    "RESULT_REUSE_INTEGRITY_MISMATCH",
                    "原结果文件在读取时发生变化，已阻止继续处理。",
                )
            data = create_local_retouch_session(content, reusable["source_result_file_name"], reusable)
        except ResultReuseError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "RESULT_REUSE_FILE_UNREADABLE", "message": "原结果文件当前无法读取。"},
            ) from exc
        return {"code": 200, "status": "success", "success": True, "data": data}

    @app.post("/api/local-retouch/sessions/{session_id}/process")
    async def local_retouch_process(session_id: str, payload: dict[str, Any] = Body(...)):
        session = require_session(session_id)
        require_roots()
        if session.get("processing"):
            raise HTTPException(
                status_code=409,
                detail={"code": "RETOUCH_PROCESSING", "message": "当前修整仍在处理中，请等待完成后再继续。"},
            )
        allowed = {"mask_png_base64", "mask_revision"}
        if set(payload) - allowed:
            raise HTTPException(status_code=400, detail={"code": "RETOUCH_REQUEST_INVALID", "message": "修整请求包含未知字段。"})
        revision = payload.get("mask_revision")
        if not isinstance(revision, int) or revision < 1:
            raise HTTPException(status_code=400, detail={"code": "RETOUCH_MASK_REVISION_INVALID", "message": "选区版本无效。"})
        encoded = str(payload.get("mask_png_base64") or "")
        if encoded.startswith("data:"):
            encoded = encoded.partition(",")[2]
        try:
            mask_bytes = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail={"code": "RETOUCH_MASK_INVALID", "message": "无法读取当前选区。"}) from exc
        if not mask_bytes or len(mask_bytes) > MAX_MASK_BYTES:
            raise HTTPException(status_code=400, detail={"code": "RETOUCH_MASK_INVALID", "message": "当前选区为空或数据过大。"})
        try:
            with Image.open(io.BytesIO(mask_bytes)) as opened:
                has_alpha = "A" in opened.getbands() or "transparency" in opened.info
                mask = opened.convert("RGBA").getchannel("A") if has_alpha else opened.convert("L")
                mask.load()
            if mask.size != (session["width"], session["height"]):
                raise ValueError("mask dimensions")
            extrema = mask.getextrema()
            if not extrema or extrema[1] < 128:
                raise ValueError("empty mask")
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"code": "RETOUCH_MASK_INVALID", "message": "选区为空或与原图尺寸不一致。"}) from exc

        if session.get("output"):
            raise HTTPException(
                status_code=409,
                detail={"code": "RETOUCH_FORMAL_RESULT_LOCKED", "message": "当前会话已生成正式结果，请重新导入后再开始新的修整。"},
            )
        upload_path = Path(session["upload_path"]).resolve()
        if _sha256(upload_path) != session["source_sha256"]:
            raise HTTPException(
                status_code=409,
                detail={"code": "RETOUCH_SOURCE_CHANGED", "message": "导入源文件发生变化，已停止处理。"},
            )
        working_path = Path(session["working_path"]).resolve()
        expected_working_sha256 = str(session["working_sha256"])
        if not working_path.is_file() or _sha256(working_path) != expected_working_sha256:
            raise HTTPException(
                status_code=409,
                detail={"code": "RETOUCH_WORKING_RESULT_CHANGED", "message": "当前稳定工作结果发生变化，请重新导入。"},
            )

        root = Path(session["root"])
        mask_path = _ensure_safe_directory(root / "current_mask.png", root)
        temporary_mask = mask_path.with_name(".mask.writing.png")
        mask.save(temporary_mask, format="PNG")
        os.replace(temporary_mask, mask_path)
        task_id = next_task_id()
        operation_identity = new_operation_identity(
            LOCAL_RETOUCH_FEATURE_KEY,
            module_id="hdde.local.retouch",
        )
        input_working_revision = int(session.get("working_revision") or 0)
        next_working_revision = input_working_revision + 1
        candidate_path = _ensure_safe_directory(root / f".candidate_{task_id}.png", root)
        stable_path = _ensure_safe_directory(root / f"working_v{next_working_revision:04d}.png", root)
        if stable_path.exists():
            stable_path = _ensure_safe_directory(root / f"working_v{next_working_revision:04d}_{task_id}.png", root)
        created_at = timestamp()
        source_path = upload_path
        source_lineage = result_lineage_fields(session)
        task_record = {
            "task_id": task_id,
            **operation_identity,
            "task_family": LOCAL_RETOUCH_FEATURE_KEY,
            "operation_mode": "LOCAL_RETOUCH",
            "processing_type": LOCAL_RETOUCH_FEATURE_KEY,
            "source": str(source_path),
            "source_path": source_path,
            "input_path": source_path,
            **source_lineage,
            "engine_source_path": working_path,
            "input_working_revision": input_working_revision,
            "working_revision": next_working_revision,
            "original_filename": session["file_name"],
            "input_size_bytes": session["source_size_bytes"],
            "input_format": session["format"],
            "created_at": created_at,
            "updated_at": created_at,
            "status": "pending",
            "task_status": "pending",
            "progress": 0,
            "task_progress": 0,
            "failure_reason": None,
            "error_message": "",
            "result_review_status": "pending",
            "result_id": "",
            "result": None,
            "task_result": None,
            "error_context": {},
            "task_context": {
                "task_id": task_id,
                **operation_identity,
                "purpose": "LOCAL_RETOUCH",
                "route": "/retouch",
                "route_family": "local_retouch",
                **source_lineage,
            },
            "lifecycle": [
                {"task_id": task_id, "status": "pending", "progress": 0, "recorded_at": created_at}
            ],
        }
        try:
            shared_task_registry[task_id] = task_record
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail={"code": "RETOUCH_TASK_REGISTRATION_FAILED", "message": "无法建立瑕疵修复任务，尚未调用处理引擎。"},
            ) from exc
        emit_runtime_event(
            "TASK_CREATED",
            stage="task_registration",
            result="success",
            impact="unified_task_available",
            **task_event_fields(task_record),
        )
        transition_task(task_record, "processing", 10)
        emit_runtime_event(
            "PROCESS_STARTED",
            stage="engine_execution",
            result="started",
            impact="local_retouch_running",
            **task_event_fields(task_record),
        )
        session["processing"] = True
        try:
            processed = retouch_engine.process(working_path, mask_path, candidate_path)
        except ValueError as exc:
            session["processing"] = False
            candidate_path.unlink(missing_ok=True)
            diagnostics = attach_error_context(task_record, exc, "engine_execution")
            transition_task(task_record, "failed", task_record["progress"], failure_reason=str(exc))
            emit_runtime_event(
                "PROCESS_FAILED",
                level=logging.ERROR,
                stage="engine_execution",
                result="failed",
                impact="preview_unavailable",
                **{**task_event_fields(task_record), **diagnostics},
            )
            raise HTTPException(status_code=422, detail={"code": "RETOUCH_PROCESS_REJECTED", "message": str(exc)}) from exc
        except Exception as exc:
            session["processing"] = False
            candidate_path.unlink(missing_ok=True)
            diagnostics = attach_error_context(task_record, exc, "engine_execution")
            transition_task(task_record, "failed", task_record["progress"], failure_reason=str(exc) or exc.__class__.__name__)
            emit_runtime_event(
                "PROCESS_FAILED",
                level=logging.ERROR,
                stage="engine_execution",
                result="failed",
                impact="preview_unavailable",
                **{**task_event_fields(task_record), **diagnostics},
            )
            raise HTTPException(status_code=500, detail={"code": "RETOUCH_ENGINE_FAILED", "message": f"瑕疵修复失败：{exc}"}) from exc
        if processed.source_sha256 != expected_working_sha256 or _sha256(working_path) != expected_working_sha256:
            session["processing"] = False
            candidate_path.unlink(missing_ok=True)
            diagnostics = attach_error_context(
                task_record,
                RuntimeError("local_retouch_working_source_changed"),
                "source_integrity",
            )
            transition_task(task_record, "failed", task_record["progress"], failure_reason="当前工作图发生变化。")
            emit_runtime_event(
                "PROCESS_FAILED",
                level=logging.ERROR,
                stage="source_integrity",
                result="failed",
                impact="preview_discarded",
                **{**task_event_fields(task_record), **diagnostics},
            )
            raise HTTPException(status_code=409, detail={"code": "RETOUCH_SOURCE_CHANGED", "message": "当前工作图发生变化，请重新导入。"})
        try:
            with Image.open(candidate_path) as opened:
                opened.load()
                if opened.size != (session["width"], session["height"]) or opened.format != "PNG":
                    raise RuntimeError("候选工作结果验证失败。")
            if stable_path.exists():
                raise FileExistsError(stable_path)
            candidate_sha256 = _sha256(candidate_path)
            os.replace(candidate_path, stable_path)
            if _sha256(stable_path) != candidate_sha256:
                raise RuntimeError("稳定工作结果完整性验证失败。")
        except Exception as exc:
            session["processing"] = False
            candidate_path.unlink(missing_ok=True)
            stable_path.unlink(missing_ok=True)
            diagnostics = attach_error_context(task_record, exc, "working_result_promotion")
            transition_task(task_record, "failed", task_record["progress"], failure_reason=str(exc) or exc.__class__.__name__)
            emit_runtime_event(
                "PROCESS_FAILED",
                level=logging.ERROR,
                stage="working_result_promotion",
                result="failed",
                impact="stable_working_result_preserved",
                **{**task_event_fields(task_record), **diagnostics},
            )
            raise HTTPException(
                status_code=500,
                detail={"code": "RETOUCH_WORKING_RESULT_INVALID", "message": "本轮候选结果无效，已保留上一稳定工作结果。"},
            ) from exc

        session["processing"] = False
        previous_task_id = str(session.get("task_id") or "")
        previous_task = shared_task_registry.get(previous_task_id) if previous_task_id else None
        previous_working_path = working_path
        session["previous_working_path"] = previous_working_path
        session["previous_working_revision"] = input_working_revision
        session["working_path"] = stable_path
        session["working_sha256"] = candidate_sha256
        session["working_revision"] = next_working_revision
        session["task_id"] = task_id
        session["confirmed"] = False
        session["confirmed_at"] = None
        result_data = {
            "task_id": task_id,
            "feature_key": LOCAL_RETOUCH_FEATURE_KEY,
            "module_id": task_record.get("module_id") or "",
            "operation_id": task_record.get("operation_id") or "",
            "trace_id": task_record.get("trace_id") or "",
            **source_lineage,
            "mask_revision": revision,
            "input_working_revision": input_working_revision,
            "working_revision": next_working_revision,
            "working_sha256": candidate_sha256,
            "engine_id": processed.engine_id,
            "mask_pixels": processed.mask_pixels,
            "inference_seconds": processed.inference_seconds,
            "width": processed.width,
            "height": processed.height,
            "format": processed.format,
            "created_at": now_provider(),
        }
        session["result"] = result_data
        session.setdefault("working_history", []).append(
            {
                "working_revision": next_working_revision,
                "parent_working_revision": input_working_revision,
                "path": stable_path,
                "sha256": candidate_sha256,
                "task_id": task_id,
                "result": dict(result_data),
            }
        )
        if previous_task and not previous_task.get("result_id"):
            previous_task["preview_path"] = None
            previous_task["processing_stage"] = "preview_superseded"
            previous_task["result_review_status"] = "superseded"
        task_record.update(
            {
                "engine_id": processed.engine_id,
                "preview_path": stable_path,
                "working_sha256": candidate_sha256,
                "processing_stage": "stable_working_result_ready",
            }
        )
        transition_task(task_record, "completed", 100)
        emit_runtime_event(
            "PROCESS_SUCCEEDED",
            stage="working_result_promotion",
            result="success",
            impact="stable_working_result_advanced",
            **task_event_fields(task_record),
        )
        return {"code": 200, "status": "success", "success": True, "data": session_payload(session)}

    @app.post("/api/local-retouch/sessions/{session_id}/back-to-previous")
    async def local_retouch_back_to_previous(session_id: str, payload: dict[str, Any] = Body(default={})):
        session = require_session(session_id)
        require_roots()
        if payload:
            raise HTTPException(
                status_code=400,
                detail={"code": "RETOUCH_BACK_REQUEST_INVALID", "message": "回到上一结果不接受额外参数。"},
            )
        if session.get("processing"):
            raise HTTPException(
                status_code=409,
                detail={"code": "RETOUCH_PROCESSING", "message": "当前修整仍在处理中，暂时不能回到上一结果。"},
            )
        if session.get("output"):
            raise HTTPException(
                status_code=409,
                detail={"code": "RETOUCH_FORMAL_RESULT_LOCKED", "message": "当前会话已生成正式结果，不能再回退工作结果。"},
            )
        upload_path = Path(session["upload_path"]).resolve()
        if not upload_path.is_file() or _sha256(upload_path) != session["source_sha256"]:
            raise HTTPException(
                status_code=409,
                detail={"code": "RETOUCH_SOURCE_CHANGED", "message": "导入源文件发生变化，已停止结果回退。"},
            )

        history = list(session.get("working_history") or [])
        if len(history) <= 1:
            raise HTTPException(
                status_code=409,
                detail={"code": "RETOUCH_PREVIOUS_RESULT_UNAVAILABLE", "message": "当前已是原图版本，无法继续回退。"},
            )
        current_entry = history[-1]
        target_entry = history[-2]
        older_entry = history[-3] if len(history) > 2 else None
        root = Path(session["root"]).resolve()
        current_path = _ensure_safe_directory(Path(current_entry["path"]), root)
        target_path = _ensure_safe_directory(Path(target_entry["path"]), root)
        older_path = _ensure_safe_directory(Path(older_entry["path"]), root) if older_entry else None
        if (
            not current_path.is_file()
            or _sha256(current_path) != str(current_entry.get("sha256") or "")
            or not target_path.is_file()
            or _sha256(target_path) != str(target_entry.get("sha256") or "")
            or (older_path is not None and (not older_path.is_file() or _sha256(older_path) != str(older_entry.get("sha256") or "")))
            or current_path != Path(session["working_path"]).resolve()
            or str(current_entry.get("sha256") or "") != str(session.get("working_sha256") or "")
            or int(current_entry.get("working_revision", -1)) != int(session.get("working_revision") or 0)
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "RETOUCH_WORKING_RESULT_CHANGED", "message": "稳定工作结果完整性校验失败，无法回退。"},
            )
        target_working_revision = int(target_entry.get("working_revision", -1))
        target_result = target_entry.get("result")
        target_task_id = str(target_entry.get("task_id") or "")
        target_task = shared_task_registry.get(target_task_id) if target_task_id else None
        target_is_source = target_working_revision == 0
        source_entry_invalid = target_is_source and (
            target_entry.get("parent_working_revision") is not None
            or target_task_id
            or target_result is not None
            or target_path != _ensure_safe_directory(root / "working_source.png", root)
        )
        result_entry_invalid = not target_is_source and (
            not isinstance(target_result, Mapping)
            or not target_task
            or target_task.get("feature_key") != LOCAL_RETOUCH_FEATURE_KEY
            or older_entry is None
        )
        if target_working_revision < 0 or source_entry_invalid or result_entry_invalid:
            raise HTTPException(
                status_code=409,
                detail={"code": "RETOUCH_PREVIOUS_RESULT_UNAVAILABLE", "message": "上一稳定结果记录不完整，无法回退。"},
            )

        mask_path = _ensure_safe_directory(root / "current_mask.png", root)
        mask_path.unlink(missing_ok=True)
        abandoned_task_id = str(current_entry.get("task_id") or "")
        abandoned_task = shared_task_registry.get(abandoned_task_id)
        if abandoned_task and not abandoned_task.get("result_id"):
            abandoned_task["preview_path"] = None
            abandoned_task["processing_stage"] = "working_result_rolled_back"
            abandoned_task["result_review_status"] = "superseded"
        if target_task:
            target_task["preview_path"] = target_path
            target_task["processing_stage"] = "stable_working_result_ready"
            target_task["result_review_status"] = "pending"

        session["working_history"] = history[:-1]
        session["working_path"] = target_path
        session["working_sha256"] = str(target_entry["sha256"])
        session["working_revision"] = target_working_revision
        session["previous_working_path"] = older_path
        session["previous_working_revision"] = int(older_entry["working_revision"]) if older_entry else None
        session["task_id"] = target_task_id
        session["result"] = dict(target_result) if isinstance(target_result, Mapping) else None
        session["confirmed"] = False
        session["confirmed_at"] = None
        emit_runtime_event(
            "WORKING_RESULT_ROLLED_BACK",
            stage="workspace_history",
            result="success",
            impact="previous_stable_working_result_restored",
            from_working_revision=current_entry.get("working_revision"),
            to_working_revision=target_entry.get("working_revision"),
            **task_event_fields(target_task or {}),
        )
        return {"code": 200, "status": "success", "success": True, "data": session_payload(session)}

    @app.post("/api/local-retouch/sessions/{session_id}/confirm")
    async def local_retouch_confirm(session_id: str, payload: dict[str, Any] = Body(...)):
        session = require_session(session_id)
        result = session.get("result")
        if not result:
            raise HTTPException(status_code=409, detail={"code": "RETOUCH_RESULT_REQUIRED", "message": "请先生成并查看修整结果。"})
        if set(payload) != {"mask_revision"} or payload.get("mask_revision") != result.get("mask_revision"):
            raise HTTPException(status_code=409, detail={"code": "RETOUCH_RESULT_STALE", "message": "选区已变化，请重新处理后再确认。"})
        task_record = require_task_for_session(session)
        session["confirmed"] = True
        session["confirmed_at"] = now_provider()
        task_record["result_review_status"] = "confirmed"
        task_record["result_reviewed_at"] = timestamp(float(session["confirmed_at"]))
        emit_runtime_event(
            "USER_CONFIRMED",
            stage="user_confirmation",
            result="success",
            impact="formal_result_registration_allowed",
            **task_event_fields(task_record),
        )
        return {"code": 200, "status": "success", "success": True, "data": session_payload(session)}

    def next_output_path(output_root: Path, source_name: str) -> Path:
        return build_output_path(
            output_root,
            source_name,
            FEATURE_RETOUCH,
            ".png",
            trusted_original_filename=source_name,
            moment=datetime.fromtimestamp(now_provider()),
        )

    @app.post("/api/local-retouch/sessions/{session_id}/save")
    async def local_retouch_save(session_id: str, payload: dict[str, Any] = Body(default={})):
        session = require_session(session_id)
        _, app_root, _, output_root = require_roots()
        if payload:
            raise HTTPException(status_code=400, detail={"code": "RETOUCH_SAVE_REQUEST_INVALID", "message": "保存派生结果不接受额外参数。"})
        if not session.get("confirmed") or not session.get("result"):
            raise HTTPException(status_code=409, detail={"code": "RETOUCH_CONFIRMATION_REQUIRED", "message": "请先人工确认当前修整结果。"})
        existing_output = session.get("output") or {}
        existing_result_id = str(existing_output.get("result_id") or "")
        if existing_result_id:
            existing_task_id = str(existing_output.get("task_id") or session.get("task_id") or "")
            existing_record = shared_task_registry.get(existing_task_id)
            existing_path = Path(existing_output.get("path") or "")
            if existing_record and existing_record.get("result_id") == existing_result_id and existing_path.is_file():
                return {"code": 200, "status": "success", "success": True, "data": session_payload(session)}
            raise HTTPException(
                status_code=409,
                detail={"code": "RETOUCH_RESULT_REGISTRATION_LOST", "message": "派生结果登记状态异常，请重新导入后再保存。"},
            )
        if _sha256(Path(session["upload_path"])) != session["source_sha256"]:
            raise HTTPException(status_code=409, detail={"code": "RETOUCH_SOURCE_CHANGED", "message": "导入源文件发生变化，已停止保存。"})
        preview = Path(session["working_path"]).resolve()
        if not preview.is_file():
            raise HTTPException(status_code=409, detail={"code": "RETOUCH_RESULT_MISSING", "message": "当前修整结果已失效，请重新处理。"})
        if _sha256(preview) != session["working_sha256"]:
            raise HTTPException(status_code=409, detail={"code": "RETOUCH_RESULT_MISSING", "message": "当前修整结果完整性校验失败，请重新导入。"})
        task_record = require_task_for_session(session)
        task_id = str(task_record["task_id"])
        output_root = _ensure_safe_directory(output_root, app_root)
        output_root.mkdir(parents=True, exist_ok=True)
        destination = _ensure_safe_directory(next_output_path(output_root, session["file_name"]), output_root)
        temporary = destination.with_name(f".{destination.stem}.writing.png")
        output_metadata: dict[str, Any] | None = None
        destination_created = False
        try:
            shutil.copyfile(preview, temporary)
            output_metadata = write_hdde_metadata(
                temporary,
                source_path=Path(session["upload_path"]),
                normalize_orientation=True,
            )
            with Image.open(temporary) as opened:
                opened.load()
                if opened.size != (session["width"], session["height"]) or opened.format != "PNG":
                    raise RuntimeError("派生结果验证失败。")
            if destination.exists():
                raise FileExistsError(destination)
            try:
                os.link(temporary, destination)
                destination_created = True
                temporary.unlink()
            except FileExistsError:
                raise
            except OSError:
                with temporary.open("rb") as source_handle, destination.open("xb") as target_handle:
                    destination_created = True
                    shutil.copyfileobj(source_handle, target_handle)
                    target_handle.flush()
                    os.fsync(target_handle.fileno())
                if _sha256(temporary) != _sha256(destination):
                    destination.unlink(missing_ok=True)
                    raise RuntimeError("派生结果发布校验失败。")
                temporary.unlink()
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            if destination_created:
                destination.unlink(missing_ok=True)
            diagnostics = attach_error_context(task_record, exc, "result_file_write")
            try:
                shared_task_registry[task_id] = task_record
            except Exception:
                pass
            emit_runtime_event(
                "RESULT_REGISTER_FAILED",
                level=logging.ERROR,
                stage="result_file_write",
                result="failed",
                impact="formal_result_unavailable",
                **{**task_event_fields(task_record), **diagnostics},
            )
            raise HTTPException(status_code=500, detail={"code": "RETOUCH_SAVE_FAILED", "message": "派生结果保存失败，未覆盖任何原文件。"}) from exc
        source_path = Path(session["upload_path"]).resolve()
        output_sha256 = _sha256(destination)
        completed_at = timestamp()
        result_id = next_result_id()
        result_data = {
            "result_id": result_id,
            "task_id": task_id,
            "feature_key": LOCAL_RETOUCH_FEATURE_KEY,
            "module_id": task_record.get("module_id") or "",
            "operation_id": task_record.get("operation_id") or "",
            "trace_id": task_record.get("trace_id") or "",
            **result_lineage_fields(session),
            "processing_type": LOCAL_RETOUCH_FEATURE_KEY,
            "status": "completed",
            "source": str(source_path),
            "source_path": str(source_path),
            "source_sha256": session["source_sha256"],
            "result_file": str(destination),
            "output_path": str(destination),
            "output_filename": destination.name,
            "output_dir": str(output_root),
            "output_size_bytes": destination.stat().st_size,
            "final_output_exists": True,
            "output_sha256": output_sha256,
            "source_hash_unchanged": _sha256(source_path) == session["source_sha256"],
            "source_preview_url": f"/api/local-retouch/sessions/{session_id}/source",
            "preview_output_url": f"/api/v1/tasks/{task_id}/result-file",
            "working_revision": int(session.get("working_revision") or 0),
            "input_width": session["width"],
            "input_height": session["height"],
            "output_width": session["width"],
            "output_height": session["height"],
            "output_format": "PNG",
            "width": session["width"],
            "height": session["height"],
            "format": "PNG",
            "created_at": completed_at,
            "output_metadata": output_metadata,
        }
        record = {
            **task_record,
            "task_id": task_id,
            "result_id": result_id,
            "feature_key": LOCAL_RETOUCH_FEATURE_KEY,
            "task_family": LOCAL_RETOUCH_FEATURE_KEY,
            "operation_mode": "LOCAL_RETOUCH",
            "processing_type": LOCAL_RETOUCH_FEATURE_KEY,
            "completed_at": completed_at,
            "status": "completed",
            "task_status": "completed",
            "progress": 100,
            "task_progress": 100,
            "failure_reason": None,
            "source": str(source_path),
            "source_path": source_path,
            "input_path": source_path,
            "result_file": str(destination),
            "output_path": destination,
            "output_dir": output_root,
            "source_sha256": session["source_sha256"],
            "source_hash_unchanged": result_data["source_hash_unchanged"],
            "source_preview_url": result_data["source_preview_url"],
            "preview_output_url": result_data["preview_output_url"],
            "input_width": session["width"],
            "input_height": session["height"],
            "output_width": session["width"],
            "output_height": session["height"],
            "output_format": "PNG",
            "result_review_status": "confirmed",
            "result_reviewed_at": timestamp(float(session.get("confirmed_at") or now_provider())),
            "result": result_data,
            "task_result": result_data,
            "output_directory": str(output_root),
            "final_output_exists": True,
            "output_metadata": output_metadata,
        }
        output_data = {
            "result_id": result_id,
            "task_id": task_id,
            "feature_key": LOCAL_RETOUCH_FEATURE_KEY,
            "path": destination,
            "file_name": destination.name,
            "directory_name": output_root.name,
            "size_bytes": destination.stat().st_size,
            "sha256": output_sha256,
        }
        try:
            shared_task_registry[task_id] = record
            session["output"] = output_data
            session["resume_committed_result_id"] = ""
            session["resume_committed_task_id"] = ""
        except Exception as exc:
            destination.unlink(missing_ok=True)
            diagnostics = attach_error_context(task_record, exc, "result_registry")
            try:
                shared_task_registry[task_id] = task_record
            except Exception:
                pass
            emit_runtime_event(
                "RESULT_REGISTER_FAILED",
                level=logging.ERROR,
                stage="result_registry",
                result="failed",
                impact="formal_result_rolled_back",
                **{**task_event_fields({**task_record, "result_id": result_id}), **diagnostics},
            )
            raise HTTPException(
                status_code=500,
                detail={"code": "RETOUCH_RESULT_REGISTRATION_FAILED", "message": "派生结果登记失败，未保留孤立文件或记录。"},
            ) from exc
        emit_runtime_event(
            "RESULT_REGISTERED",
            stage="result_registry",
            result="success",
            impact="formal_result_available",
            **task_event_fields(record),
        )
        return {"code": 200, "status": "success", "success": True, "data": session_payload(session)}

    @app.get("/api/local-retouch/resume-authority")
    async def local_retouch_resume_authority(task_id: str = "", result_id: str = ""):
        require_roots()
        authority, _ = resume_authority(task_id, result_id)
        return {"code": 200, "status": "success", "success": True, "data": authority}

    @app.post("/api/local-retouch/sessions/{session_id}/resume-adjustment")
    async def local_retouch_resume_adjustment(session_id: str, payload: dict[str, Any] = Body(...)):
        session = require_session(session_id)
        require_roots()
        if set(payload) != {"result_id"} or not str(payload.get("result_id") or "").strip():
            raise HTTPException(
                status_code=400,
                detail={"code": "RETOUCH_RESUME_REQUEST_INVALID", "message": "返回调整请求缺少有效结果标识。"},
            )
        result_id = str(payload["result_id"]).strip()
        output = session.get("output") or {}
        task_id = str(
            output.get("task_id")
            or session.get("task_id")
            or session.get("resume_committed_task_id")
            or ""
        )
        authority, authorized_session = resume_authority(task_id, result_id)
        if not authority["available"] or authorized_session is not session:
            raise HTTPException(
                status_code=409,
                detail={"code": f"RETOUCH_RESUME_{authority['status']}", "message": "当前正式结果不可恢复，请重新处理。"},
            )
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "data": resume_response_data(session, phase="PREPARED", result_id=result_id),
        }

    @app.post("/api/local-retouch/sessions/{session_id}/resume-adjustment/commit")
    async def local_retouch_resume_adjustment_commit(session_id: str, payload: dict[str, Any] = Body(...)):
        session = require_session(session_id)
        require_roots()
        if set(payload) != {"result_id"} or not str(payload.get("result_id") or "").strip():
            raise HTTPException(
                status_code=400,
                detail={"code": "RETOUCH_RESUME_REQUEST_INVALID", "message": "返回调整请求缺少有效结果标识。"},
            )
        result_id = str(payload["result_id"]).strip()
        output = session.get("output") or {}
        task_id = str(
            output.get("task_id")
            or session.get("task_id")
            or session.get("resume_committed_task_id")
            or ""
        )
        authority, authorized_session = resume_authority(task_id, result_id)
        if not authority["available"] or authorized_session is not session:
            raise HTTPException(
                status_code=409,
                detail={"code": f"RETOUCH_RESUME_{authority['status']}", "message": "当前正式结果不可恢复，请重新处理。"},
            )
        if not output and str(session.get("resume_committed_result_id") or "") == result_id:
            return {
                "code": 200,
                "status": "success",
                "success": True,
                "data": resume_response_data(session, phase="COMMITTED", result_id=result_id, duplicate=True),
            }

        task_record = shared_task_registry[task_id]
        session["output"] = None
        session["confirmed"] = False
        session["confirmed_at"] = None
        session["resume_committed_result_id"] = result_id
        session["resume_committed_task_id"] = task_id
        emit_runtime_event(
            "RETOUCH_ADJUSTMENT_RESUMED",
            stage="result_revision",
            result="success",
            impact="stable_working_result_resumed",
            **task_event_fields(task_record),
        )
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "data": resume_response_data(session, phase="COMMITTED", result_id=result_id),
        }

    @app.get("/api/local-retouch/sessions/{session_id}/source")
    async def local_retouch_source(session_id: str):
        session = require_session(session_id)
        path = Path(session["upload_path"]).resolve()
        if not path.is_file() or _sha256(path) != session["source_sha256"]:
            raise HTTPException(
                status_code=409,
                detail={"code": "RETOUCH_SOURCE_CHANGED", "message": "导入源文件发生变化，无法读取原图预览。"},
            )
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, no-store"})

    @app.get("/api/local-retouch/sessions/{session_id}/working-source")
    async def local_retouch_working_source(session_id: str):
        session = require_session(session_id)
        path = Path(session["working_path"]).resolve()
        if not path.is_file() or _sha256(path) != session["working_sha256"]:
            raise HTTPException(
                status_code=409,
                detail={"code": "RETOUCH_WORKING_RESULT_CHANGED", "message": "当前工作底图发生变化，请重新导入。"},
            )
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, no-store"})

    @app.get("/api/local-retouch/sessions/{session_id}/result")
    async def local_retouch_result(session_id: str):
        session = require_session(session_id)
        if not session.get("result"):
            raise HTTPException(status_code=404, detail={"code": "RETOUCH_RESULT_MISSING", "message": "当前尚无修整结果。"})
        path = Path(session["working_path"]).resolve()
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, no-store"})

    @app.get("/api/local-retouch/sessions/{session_id}/previous-result")
    async def local_retouch_previous_result(session_id: str):
        session = require_session(session_id)
        path = Path(session.get("previous_working_path") or "")
        if not path.is_file():
            raise HTTPException(status_code=404, detail={"code": "RETOUCH_PREVIOUS_RESULT_MISSING", "message": "当前会话尚无上一稳定工作结果。"})
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, no-store"})

    @app.get("/api/local-retouch/sessions/{session_id}/output")
    async def local_retouch_output(session_id: str):
        session = require_session(session_id)
        output = session.get("output") or {}
        path = Path(output.get("path") or "")
        if not output or not path.is_file():
            raise HTTPException(status_code=404, detail={"code": "RETOUCH_OUTPUT_MISSING", "message": "派生结果不存在。"})
        media_type = mimetypes.guess_type(path.name)[0] or "image/png"
        return FileResponse(path, media_type=media_type, filename=path.name)

    @app.post("/api/local-retouch/sessions/{session_id}/open-folder")
    async def local_retouch_open_folder(session_id: str):
        session = require_session(session_id)
        output = session.get("output") or {}
        path = Path(output.get("path") or "")
        if not output or not path.is_file():
            raise HTTPException(status_code=404, detail={"code": "RETOUCH_OUTPUT_MISSING", "message": "派生结果不存在。"})
        try:
            if folder_opener is not None:
                folder_opener(str(path.parent))
            elif os.name == "nt":
                os.startfile(str(path.parent))  # noqa: S606 - registry-bound formal result directory
            else:
                raise OSError("当前系统不支持自动打开目录。")
        except Exception as exc:
            raise HTTPException(status_code=400, detail={"code": "RETOUCH_OPEN_FOLDER_FAILED", "message": "无法打开派生结果目录。"}) from exc
        return {"code": 200, "status": "success", "success": True, "data": {"directory_name": path.parent.name}}

    state = {
        "feature_key": LOCAL_RETOUCH_FEATURE_KEY,
        "sessions": sessions,
        "engine": retouch_engine,
        "shared_task_registry": shared_task_registry,
    }
    app.state.local_retouch_api_state = state
    return state
