from __future__ import annotations

import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping

from fastapi import UploadFile

from engine.image_diagnosis import IMAGE_DIAGNOSIS_FEATURE_KEY, ImageDiagnosisEngine


MAX_UPLOAD_BYTES = 250 * 1024 * 1024
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}


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


def _safe_child(path: Path, root: Path) -> Path:
    resolved_root = Path(root).resolve()
    resolved = Path(path).resolve()
    if not _is_within(resolved, resolved_root):
        raise RuntimeError("图片诊断临时目录安全校验失败。")
    cursor = resolved_root
    for part in resolved.relative_to(resolved_root).parts:
        cursor = cursor / part
        if cursor.exists() and cursor.is_symlink():
            raise RuntimeError("图片诊断临时目录不能经过链接目录。")
    return resolved


def register_image_diagnosis_routes(
    app,
    *,
    user_dirs_provider: Callable[[], Mapping[str, Any]],
    shared_task_registry: MutableMapping[str, dict[str, Any]],
    engine: ImageDiagnosisEngine | None = None,
    now_provider: Callable[[], float] = time.time,
    runtime_event_logger: Callable[..., None] | None = None,
) -> dict[str, Any]:
    from fastapi import File, HTTPException
    from fastapi.responses import FileResponse

    diagnosis_engine = engine or ImageDiagnosisEngine()

    def timestamp(value: float | None = None) -> str:
        return datetime.fromtimestamp(value if value is not None else now_provider(), tz=timezone.utc).isoformat()

    def emit_runtime_event(event: str, **fields: Any) -> None:
        if runtime_event_logger is None:
            return
        try:
            runtime_event_logger(event, **fields)
        except Exception:
            return

    def event_fields(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "feature_key": IMAGE_DIAGNOSIS_FEATURE_KEY,
            "task_id": record.get("task_id") or "",
            "result_id": record.get("result_id") or "",
            "status": record.get("status") or "",
        }

    def require_runtime_root() -> tuple[Path, Path]:
        user_dirs = dict(user_dirs_provider() or {})
        if user_dirs.get("directory_ready") is False:
            raise HTTPException(
                status_code=409,
                detail={"code": "FORMAL_DIRECTORY_NOT_READY", "message": str(user_dirs.get("directory_message") or "正式目录未就绪。")},
            )
        app_root = Path(user_dirs.get("app_data_root") or "").resolve()
        if not app_root.is_dir():
            raise HTTPException(status_code=409, detail={"code": "FORMAL_DIRECTORY_NOT_READY", "message": "正式目录未就绪。"})
        runtime_root = _safe_child(Path(user_dirs.get("tmp_dir") or (app_root / "临时文件")) / "image-diagnosis", app_root)
        runtime_root.mkdir(parents=True, exist_ok=True)
        return app_root, runtime_root

    def next_task_id() -> str:
        task_id = f"diagnosis_task_{uuid.uuid4().hex[:16]}"
        while task_id in shared_task_registry:
            task_id = f"diagnosis_task_{uuid.uuid4().hex[:16]}"
        return task_id

    def next_result_id() -> str:
        registered = {
            str(record.get("result_id") or "")
            for record in shared_task_registry.values()
            if isinstance(record, Mapping)
        }
        result_id = f"diagnosis_result_{uuid.uuid4().hex[:16]}"
        while result_id in registered or result_id in shared_task_registry:
            result_id = f"diagnosis_result_{uuid.uuid4().hex[:16]}"
        return result_id

    def transition(record: dict[str, Any], status: str, progress: int, *, reason: str = "") -> None:
        recorded_at = timestamp()
        record.update(
            {
                "status": status,
                "task_status": status,
                "progress": progress,
                "task_progress": progress,
                "updated_at": recorded_at,
                "failure_reason": reason or None,
                "error_message": reason,
            }
        )
        record.setdefault("lifecycle", []).append(
            {"task_id": record["task_id"], "status": status, "progress": progress, "recorded_at": recorded_at}
        )
        if status in {"completed", "failed"}:
            record["completed_at"] = recorded_at

    def public_payload(record: Mapping[str, Any]) -> dict[str, Any]:
        result = record.get("result") if isinstance(record.get("result"), Mapping) else {}
        public_result = dict(result)
        public_result.pop("source", None)
        task_id = str(record.get("task_id") or "")
        return {
            "feature_key": IMAGE_DIAGNOSIS_FEATURE_KEY,
            "task_id": task_id,
            "task_status": record.get("status") or "",
            "result_id": record.get("result_id") or "",
            "source_display_name": record.get("original_filename") or "诊断图片",
            "source_preview_url": f"/api/image-diagnosis/tasks/{task_id}/source" if task_id else "",
            "result": public_result,
        }

    @app.get("/api/image-diagnosis/capabilities")
    async def image_diagnosis_capabilities():
        require_runtime_root()
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "data": {
                "available": True,
                "feature_key": IMAGE_DIAGNOSIS_FEATURE_KEY,
                "engine_id": diagnosis_engine.engine_id,
                "adapter_id": diagnosis_engine.adapter_id,
                "supported_formats": sorted(suffix.lstrip(".").upper() for suffix in ALLOWED_SUFFIXES),
                "max_upload_bytes": MAX_UPLOAD_BYTES,
            },
        }

    @app.post("/api/image-diagnosis/tasks")
    async def create_image_diagnosis_task(file: UploadFile = File(...)):
        _, runtime_root = require_runtime_root()
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(
                status_code=415,
                detail={"code": "DIAGNOSIS_FORMAT_UNSUPPORTED", "message": "请选择受支持的图片格式。"},
            )

        task_id = next_task_id()
        task_root = _safe_child(runtime_root / task_id, runtime_root)
        task_root.mkdir(parents=True, exist_ok=False)
        source_path = _safe_child(task_root / _safe_filename(file.filename or f"image{suffix}"), task_root)
        temporary_path = _safe_child(task_root / f".source.writing{suffix}", task_root)
        size_bytes = 0
        try:
            with temporary_path.open("xb") as output:
                while chunk := await file.read(1024 * 1024):
                    size_bytes += len(chunk)
                    if size_bytes > MAX_UPLOAD_BYTES:
                        raise ValueError("图片超过250MB安全限制。")
                    output.write(chunk)
            if size_bytes <= 0:
                raise ValueError("图片文件为空。")
            os.replace(temporary_path, source_path)
        except Exception as exc:
            temporary_path.unlink(missing_ok=True)
            source_path.unlink(missing_ok=True)
            try:
                task_root.rmdir()
            except OSError:
                pass
            status_code = 413 if size_bytes > MAX_UPLOAD_BYTES else 422
            raise HTTPException(
                status_code=status_code,
                detail={"code": "DIAGNOSIS_SOURCE_INVALID", "message": str(exc) or "无法安全读取图片。"},
            ) from exc
        finally:
            await file.close()

        created_at = timestamp()
        task_record: dict[str, Any] = {
            "task_id": task_id,
            "feature_key": IMAGE_DIAGNOSIS_FEATURE_KEY,
            "task_family": IMAGE_DIAGNOSIS_FEATURE_KEY,
            "operation_mode": "IMAGE_DIAGNOSIS",
            "processing_type": IMAGE_DIAGNOSIS_FEATURE_KEY,
            "source": str(source_path),
            "source_path": source_path,
            "input_path": source_path,
            "source_preview_url": f"/api/image-diagnosis/tasks/{task_id}/source",
            "original_filename": Path(file.filename or source_path.name).name,
            "input_size_bytes": size_bytes,
            "input_format": suffix.lstrip(".").upper(),
            "created_at": created_at,
            "updated_at": created_at,
            "status": "pending",
            "task_status": "pending",
            "progress": 0,
            "task_progress": 0,
            "processing_stage": "task_registered",
            "failure_reason": None,
            "error_message": "",
            "result_id": "",
            "result": None,
            "task_result": None,
            "final_output_exists": False,
            "result_review_status": "not_required",
            "lifecycle": [
                {"task_id": task_id, "status": "pending", "progress": 0, "recorded_at": created_at}
            ],
            "task_context": {
                "task_id": task_id,
                "feature_key": IMAGE_DIAGNOSIS_FEATURE_KEY,
                "purpose": "image_quality_diagnosis",
                "route_family": "image_diagnosis",
            },
        }
        try:
            shared_task_registry[task_id] = task_record
        except Exception as exc:
            source_path.unlink(missing_ok=True)
            try:
                task_root.rmdir()
            except OSError:
                pass
            raise HTTPException(
                status_code=500,
                detail={"code": "DIAGNOSIS_TASK_REGISTRATION_FAILED", "message": "无法建立图片诊断任务，尚未调用诊断引擎。"},
            ) from exc

        emit_runtime_event(
            "TASK_CREATED",
            stage="task_registration",
            result="success",
            impact="unified_task_available",
            **event_fields(task_record),
        )
        transition(task_record, "processing", 15)
        task_record["processing_stage"] = "diagnosis_engine"
        emit_runtime_event(
            "PROCESS_STARTED",
            stage="diagnosis_engine",
            result="started",
            impact="diagnosis_running",
            **event_fields(task_record),
        )

        try:
            diagnosis = diagnosis_engine.diagnose(source_path).to_dict()
            result_id = next_result_id()
            completed_at = timestamp()
            result_data = {
                "result_id": result_id,
                "task_id": task_id,
                "feature_key": IMAGE_DIAGNOSIS_FEATURE_KEY,
                "result_type": "structured_image_diagnosis",
                "status": "completed",
                "source": str(source_path),
                "image_facts": diagnosis["image_facts"],
                "diagnosis_findings": diagnosis["quality_issues"],
                "recommended_action": diagnosis["recommended_action"],
                "source_integrity": diagnosis["source_integrity"],
                "contract_version": diagnosis["contract_version"],
                "engine_id": diagnosis["engine_id"],
                "adapter_id": diagnosis["adapter_id"],
                "created_at": completed_at,
            }
            task_record.update(
                {
                    "result_id": result_id,
                    "result": result_data,
                    "task_result": result_data,
                    "processing_stage": "diagnosis_completed",
                    "safe_input_metadata": {
                        **diagnosis["image_facts"],
                        "size_bytes": diagnosis["image_facts"].get("file_size_bytes"),
                    },
                }
            )
            transition(task_record, "completed", 100)
        except Exception as exc:
            transition(task_record, "failed", task_record.get("progress", 15), reason=str(exc) or exc.__class__.__name__)
            task_record["processing_stage"] = "diagnosis_failed"
            emit_runtime_event(
                "PROCESS_FAILED",
                level=logging.ERROR,
                stage="diagnosis_engine",
                result="failed",
                reason=str(exc) or exc.__class__.__name__,
                impact="diagnosis_result_unavailable",
                exception=exc,
                **event_fields(task_record),
            )
            raise HTTPException(
                status_code=422,
                detail={"code": "DIAGNOSIS_ENGINE_FAILED", "message": str(exc) or "图片诊断失败，请更换图片后重试。"},
            ) from exc

        emit_runtime_event(
            "PROCESS_SUCCEEDED",
            stage="diagnosis_result",
            result="success",
            impact="structured_diagnosis_available",
            **event_fields(task_record),
        )
        emit_runtime_event(
            "RESULT_REGISTERED",
            stage="result_registry",
            result="success",
            impact="structured_result_available",
            **event_fields(task_record),
        )
        return {"code": 200, "status": "success", "success": True, "data": public_payload(task_record)}

    @app.get("/api/image-diagnosis/tasks/{task_id}")
    async def image_diagnosis_task(task_id: str):
        record = shared_task_registry.get(str(task_id or ""))
        if not record or record.get("feature_key") != IMAGE_DIAGNOSIS_FEATURE_KEY:
            raise HTTPException(status_code=404, detail={"code": "DIAGNOSIS_TASK_NOT_FOUND", "message": "图片诊断任务不存在。"})
        return {"code": 200, "status": "success", "success": True, "data": public_payload(record)}

    @app.get("/api/image-diagnosis/tasks/{task_id}/source")
    async def image_diagnosis_source(task_id: str):
        record = shared_task_registry.get(str(task_id or ""))
        path = Path(record.get("source_path") or "") if record else Path()
        if not record or record.get("feature_key") != IMAGE_DIAGNOSIS_FEATURE_KEY or not path.is_file():
            raise HTTPException(status_code=404, detail={"code": "DIAGNOSIS_SOURCE_NOT_FOUND", "message": "诊断源图片不可用。"})
        return FileResponse(path, headers={"Cache-Control": "private, no-store"})

    state = {
        "feature_key": IMAGE_DIAGNOSIS_FEATURE_KEY,
        "engine": diagnosis_engine,
        "shared_task_registry": shared_task_registry,
    }
    app.state.image_diagnosis_api_state = state
    return state
