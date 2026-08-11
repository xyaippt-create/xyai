from __future__ import annotations

import base64
import hashlib
import io
import logging
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

from engine.local_retouch import LocalRetouchEngine


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
        raise RuntimeError("局部修整目录安全校验失败。")
    cursor = resolved_root
    try:
        relative = resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError("局部修整目录安全校验失败。") from exc
    for part in relative.parts:
        cursor = cursor / part
        if cursor.exists() and cursor.is_symlink():
            raise RuntimeError("局部修整目录不能经过链接目录。")
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
        output_root = _ensure_safe_directory(app_root / "输出" / "标记修整", app_root)
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
        return {
            "session_id": session_id,
            "feature_key": LOCAL_RETOUCH_FEATURE_KEY,
            "task_id": task_id,
            "task_status": str((task or {}).get("status") or ""),
            "file_name": session["file_name"],
            "width": session["width"],
            "height": session["height"],
            "format": session["format"],
            "source_sha256": session["source_sha256"],
            "source_url": f"/api/local-retouch/sessions/{session_id}/source",
            "result_url": f"/api/local-retouch/sessions/{session_id}/result" if result else "",
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

    @app.post("/api/local-retouch/intake")
    async def local_retouch_intake(file: UploadFile = File(...)):
        _, app_root, runtime_root, _ = require_roots()
        raw_name = str(file.filename or "")
        if not raw_name or raw_name != Path(raw_name).name or "/" in raw_name or "\\" in raw_name:
            raise HTTPException(status_code=400, detail={"code": "RETOUCH_FILENAME_INVALID", "message": "文件名不得包含目录信息。"})
        safe_name = _safe_filename(raw_name)
        suffix = Path(safe_name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=415, detail={"code": "RETOUCH_FORMAT_UNSUPPORTED", "message": "仅支持PNG、JPG和JPEG图片。"})
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if not content or len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail={"code": "RETOUCH_FILE_TOO_LARGE", "message": "图片为空或超过50MB限制。"})
        try:
            with Image.open(io.BytesIO(content)) as opened:
                opened.verify()
            with Image.open(io.BytesIO(content)) as opened:
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
            working.save(working_path, format="PNG", optimize=False)
            with Image.open(working_path) as verified:
                verified.load()
                if verified.size != (width, height):
                    raise RuntimeError("工作图尺寸验证失败。")
        except Exception:
            shutil.rmtree(session_root, ignore_errors=True)
            raise

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
            "width": width,
            "height": height,
            "format": source_format,
            "created_at": now_provider(),
            "result": None,
            "confirmed": False,
            "confirmed_at": None,
            "task_id": "",
            "output": None,
        }
        return {"code": 200, "status": "success", "success": True, "data": session_payload(sessions[session_id])}

    @app.post("/api/local-retouch/sessions/{session_id}/process")
    async def local_retouch_process(session_id: str, payload: dict[str, Any] = Body(...)):
        session = require_session(session_id)
        require_roots()
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
                mask = opened.convert("L")
                mask.load()
            if mask.size != (session["width"], session["height"]):
                raise ValueError("mask dimensions")
            extrema = mask.getextrema()
            if not extrema or extrema[1] < 128:
                raise ValueError("empty mask")
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"code": "RETOUCH_MASK_INVALID", "message": "选区为空或与原图尺寸不一致。"}) from exc

        root = Path(session["root"])
        mask_path = _ensure_safe_directory(root / "current_mask.png", root)
        result_path = _ensure_safe_directory(root / "current_result.png", root)
        temporary_mask = mask_path.with_name(".mask.writing.png")
        mask.save(temporary_mask, format="PNG")
        os.replace(temporary_mask, mask_path)
        previous_task_id = str(session.get("task_id") or "")
        previous_task = shared_task_registry.get(previous_task_id) if previous_task_id else None
        if previous_task and not previous_task.get("result_id"):
            previous_task["preview_path"] = None
            previous_task["processing_stage"] = "preview_superseded"
            previous_task["result_review_status"] = "superseded"
        session["result"] = None
        session["confirmed"] = False
        session["confirmed_at"] = None
        session["output"] = None
        task_id = next_task_id()
        created_at = timestamp()
        source_path = Path(session["upload_path"]).resolve()
        task_record = {
            "task_id": task_id,
            "feature_key": LOCAL_RETOUCH_FEATURE_KEY,
            "task_family": LOCAL_RETOUCH_FEATURE_KEY,
            "operation_mode": "LOCAL_RETOUCH",
            "processing_type": LOCAL_RETOUCH_FEATURE_KEY,
            "source": str(source_path),
            "source_path": source_path,
            "input_path": source_path,
            "engine_source_path": Path(session["working_path"]).resolve(),
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
            "lifecycle": [
                {"task_id": task_id, "status": "pending", "progress": 0, "recorded_at": created_at}
            ],
        }
        try:
            shared_task_registry[task_id] = task_record
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail={"code": "RETOUCH_TASK_REGISTRATION_FAILED", "message": "无法建立局部修整任务，尚未调用处理引擎。"},
            ) from exc
        session["task_id"] = task_id
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
        try:
            processed = retouch_engine.process(Path(session["working_path"]), mask_path, result_path)
        except ValueError as exc:
            result_path.unlink(missing_ok=True)
            transition_task(task_record, "failed", task_record["progress"], failure_reason=str(exc))
            emit_runtime_event(
                "PROCESS_FAILED",
                level=logging.ERROR,
                stage="engine_execution",
                result="failed",
                reason=str(exc),
                impact="preview_unavailable",
                **task_event_fields(task_record),
            )
            raise HTTPException(status_code=422, detail={"code": "RETOUCH_PROCESS_REJECTED", "message": str(exc)}) from exc
        except Exception as exc:
            result_path.unlink(missing_ok=True)
            transition_task(task_record, "failed", task_record["progress"], failure_reason=str(exc) or exc.__class__.__name__)
            emit_runtime_event(
                "PROCESS_FAILED",
                level=logging.ERROR,
                stage="engine_execution",
                result="failed",
                reason=str(exc) or exc.__class__.__name__,
                impact="preview_unavailable",
                **task_event_fields(task_record),
            )
            raise HTTPException(status_code=500, detail={"code": "RETOUCH_ENGINE_FAILED", "message": f"局部修整失败：{exc}"}) from exc
        if processed.source_sha256 != session["working_sha256"]:
            result_path.unlink(missing_ok=True)
            transition_task(task_record, "failed", task_record["progress"], failure_reason="当前工作图发生变化。")
            emit_runtime_event(
                "PROCESS_FAILED",
                level=logging.ERROR,
                stage="source_integrity",
                result="failed",
                reason="source_changed",
                impact="preview_discarded",
                **task_event_fields(task_record),
            )
            raise HTTPException(status_code=409, detail={"code": "RETOUCH_SOURCE_CHANGED", "message": "当前工作图发生变化，请重新导入。"})
        session["result"] = {
            "task_id": task_id,
            "feature_key": LOCAL_RETOUCH_FEATURE_KEY,
            "mask_revision": revision,
            "engine_id": processed.engine_id,
            "mask_pixels": processed.mask_pixels,
            "inference_seconds": processed.inference_seconds,
            "width": processed.width,
            "height": processed.height,
            "format": processed.format,
            "created_at": now_provider(),
        }
        task_record.update(
            {
                "engine_id": processed.engine_id,
                "preview_path": result_path,
                "processing_stage": "preview_ready",
            }
        )
        transition_task(task_record, "completed", 100)
        emit_runtime_event(
            "PROCESS_SUCCEEDED",
            stage="preview_ready",
            result="success",
            impact="temporary_preview_available",
            **task_event_fields(task_record),
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
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(now_provider()))
        stem = _safe_filename(source_name).rsplit(".", 1)[0]
        base = f"{stem}_影界局部修整_{stamp}"
        candidate = output_root / f"{base}.png"
        counter = 2
        while candidate.exists():
            candidate = output_root / f"{base}_{counter}.png"
            counter += 1
        return candidate

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
        preview = Path(session["root"]) / "current_result.png"
        if not preview.is_file():
            raise HTTPException(status_code=409, detail={"code": "RETOUCH_RESULT_MISSING", "message": "当前修整结果已失效，请重新处理。"})
        task_record = require_task_for_session(session)
        task_id = str(task_record["task_id"])
        output_root = _ensure_safe_directory(output_root, app_root)
        output_root.mkdir(parents=True, exist_ok=True)
        destination = _ensure_safe_directory(next_output_path(output_root, session["file_name"]), output_root)
        temporary = destination.with_name(f".{destination.stem}.writing.png")
        try:
            shutil.copyfile(preview, temporary)
            with Image.open(temporary) as opened:
                opened.load()
                if opened.size != (session["width"], session["height"]) or opened.format != "PNG":
                    raise RuntimeError("派生结果验证失败。")
            if destination.exists():
                raise FileExistsError(destination)
            os.replace(temporary, destination)
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            emit_runtime_event(
                "RESULT_REGISTER_FAILED",
                level=logging.ERROR,
                stage="result_file_write",
                result="failed",
                reason=str(exc) or exc.__class__.__name__,
                impact="formal_result_unavailable",
                **task_event_fields(task_record),
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
            "width": session["width"],
            "height": session["height"],
            "format": "PNG",
            "created_at": completed_at,
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
            "result_review_status": "confirmed",
            "result_reviewed_at": timestamp(float(session.get("confirmed_at") or now_provider())),
            "result": result_data,
            "task_result": result_data,
            "output_directory": str(output_root),
            "final_output_exists": True,
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
        except Exception as exc:
            destination.unlink(missing_ok=True)
            emit_runtime_event(
                "RESULT_REGISTER_FAILED",
                level=logging.ERROR,
                stage="result_registry",
                result="failed",
                reason=str(exc) or exc.__class__.__name__,
                impact="formal_result_rolled_back",
                **task_event_fields({**task_record, "result_id": result_id}),
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

    @app.get("/api/local-retouch/sessions/{session_id}/source")
    async def local_retouch_source(session_id: str):
        session = require_session(session_id)
        path = Path(session["working_path"])
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, no-store"})

    @app.get("/api/local-retouch/sessions/{session_id}/result")
    async def local_retouch_result(session_id: str):
        session = require_session(session_id)
        if not session.get("result"):
            raise HTTPException(status_code=404, detail={"code": "RETOUCH_RESULT_MISSING", "message": "当前尚无修整结果。"})
        path = Path(session["root"]) / "current_result.png"
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
