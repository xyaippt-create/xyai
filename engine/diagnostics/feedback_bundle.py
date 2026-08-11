from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from engine.diagnostics.feedback_context import build_feedback_context, feedback_context_preview
from engine.diagnostics.runtime_logging import sanitize_diagnostic_value


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FEEDBACK_SCHEMA_VERSION = "HDDE-user-feedback-v2"


def _default_app_data_root() -> Path:
    settings_path = PROJECT_ROOT / "settings" / "settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    except Exception:
        settings = {}
    if isinstance(settings, dict):
        configured = str(settings.get("app_data_root") or "").strip()
        if configured:
            return Path(configured).expanduser()
        saved = str(settings.get("last_app_data_root") or "").strip()
        if saved:
            saved_path = Path(saved).expanduser()
            try:
                project_tmp = (PROJECT_ROOT / "tmp" / "runtime_data").resolve()
                is_project_tmp = project_tmp == saved_path.resolve() or project_tmp in saved_path.resolve().parents
            except Exception:
                is_project_tmp = False
            if not is_project_tmp:
                return saved_path
    if os.name == "nt" and Path("D:/").exists():
        return Path("D:/影界文件")
    documents = (
        Path(os.environ["USERPROFILE"]) / "Documents"
        if os.name == "nt" and os.environ.get("USERPROFILE")
        else Path.home() / "Documents"
    )
    return documents / "影界HDDE"


DEFAULT_FEEDBACK_DIR = _default_app_data_root() / "诊断" / "反馈包"

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|cookie|authorization|password|secret)[\"']?\s*[:=]\s*[\"']?[^\"'\s,}]+"),
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
]


def _safe_filename(value: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .") or "task"


def _redact_string(value: str) -> str:
    text = str(value)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("<redacted>", text)
    code_frames = text.split(" <- ")
    if code_frames and all(
        re.fullmatch(r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+:\d+::[A-Za-z0-9_<>-]+", frame)
        for frame in code_frames
    ):
        return text
    text = sanitize_diagnostic_value(text)
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    if user:
        text = text.replace(user, "<已隐藏用户>")
    return text


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, Path):
        return _redact_string(str(value))
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(redact(payload), ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _path_summary(path_value: Any, formal_root: Path | None, *, safe_reference: str = "") -> dict[str, Any]:
    if not path_value:
        return {"available": False, "file_name": "", "location": "", "in_formal_root": False}
    path = Path(str(path_value))
    suffix = path.suffix.lower()[:12]
    reference = str(safe_reference or "").strip()
    if not reference:
        reference = f"file_{hashlib.sha256(str(path_value).encode('utf-8', errors='replace')).hexdigest()[:12]}"
    safe_name = reference if reference.lower().endswith(suffix) else f"{reference}{suffix}"
    location = "external"
    in_formal_root = False
    if formal_root:
        try:
            path.resolve().relative_to(formal_root.resolve())
            location = "formal_root"
            in_formal_root = True
        except Exception:
            location = "external"
    return {
        "available": path.exists(),
        "file_name": safe_name,
        "reference": reference,
        "location": location,
        "in_formal_root": in_formal_root,
    }


def _output_validation(path_value: Any) -> dict[str, Any]:
    if not path_value:
        return {"exists": False, "decodable": False, "width": None, "height": None, "format": ""}
    path = Path(str(path_value))
    if not path.exists() or not path.is_file():
        return {"exists": False, "decodable": False, "width": None, "height": None, "format": ""}
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            image_format = str(image.format or "")
        return {
            "exists": True,
            "decodable": True,
            "width": width,
            "height": height,
            "format": image_format,
        }
    except Exception:
        return {"exists": True, "decodable": False, "width": None, "height": None, "format": ""}


def _task_log(task: dict[str, Any]) -> str:
    lines: list[str] = []
    for event in list(task.get("stage_events") or [])[-24:]:
        if not isinstance(event, dict):
            continue
        time_value = event.get("created_at") or event.get("timestamp") or ""
        stage = event.get("stage") or event.get("name") or "task"
        progress = event.get("progress")
        message = event.get("message") or ""
        progress_text = f" {progress}%" if progress is not None else ""
        lines.append(_redact_string(f"{time_value} [{stage}]{progress_text} {message}".strip()))
    if not lines:
        status = task.get("task_status") or task.get("status") or "unknown"
        stage = task.get("current_stage") or task.get("stage") or ""
        error = task.get("error_message") or task.get("task_error") or ""
        lines.append(_redact_string(f"任务状态: {status}; 当前阶段: {stage}; 错误: {error or '无'}"))
    return "\n".join(lines) + "\n"


def generate_feedback_bundle(
    task_id: str,
    task: dict[str, Any] | None,
    output_dir: Path | None = None,
    *,
    context_snapshot: dict[str, Any] | None = None,
    attachment_manifest: list[dict[str, Any]] | None = None,
    feedback_bundle_id: str = "",
) -> dict[str, Any]:
    target_dir = Path(output_dir) if output_dir else DEFAULT_FEEDBACK_DIR
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {
            "feedback_bundle_status": "FAIL",
            "feedback_bundle_path": "",
            "feedback_bundle_size": 0,
            "feedback_bundle_redacted": True,
            "feedback_bundle_error": f"feedback directory unavailable: {exc}",
        }

    generated_at = datetime.now().isoformat(timespec="milliseconds")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_id = feedback_bundle_id or f"FB-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:12].upper()}"
    safe_task_id = _safe_filename(task_id or "unknown_task")
    bundle_path = target_dir / f"影界HDDE_问题反馈_{safe_task_id}_{timestamp}.zip"
    task = dict(task or {})
    task_result = dict(task.get("task_result") or {})
    task_report = dict(task.get("task_report") or {})
    formal_root_value = task.get("formal_root")
    formal_root = Path(str(formal_root_value)) if formal_root_value else None
    output_path = (
        task_result.get("output_path")
        or task.get("output_path")
        or task.get("expected_output_path")
    )
    validation = _output_validation(output_path)
    context = redact(context_snapshot) if isinstance(context_snapshot, dict) else build_feedback_context(
        task,
        source_feature=str(task.get("source_feature") or "") or None,
        runtime=task.get("runtime_context") if isinstance(task.get("runtime_context"), dict) else None,
        user_description=str(task.get("user_description") or ""),
    )
    safe_attachments: list[dict[str, Any]] = []
    for item in list(attachment_manifest or [])[:10]:
        if not isinstance(item, dict):
            continue
        try:
            size_bytes = max(0, int(item.get("size_bytes") or 0))
        except (TypeError, ValueError):
            size_bytes = 0
        safe_attachments.append({
            "extension": str(item.get("extension") or "")[:16].lower(),
            "size_bytes": size_bytes,
            "selected_by_user": bool(item.get("selected_by_user")),
            "included_in_bundle": False,
        })

    report = {
        "feedback_schema_version": FEEDBACK_SCHEMA_VERSION,
        "feedback_version": FEEDBACK_SCHEMA_VERSION,
        "feedback_bundle_id": bundle_id,
        "generated_at": generated_at,
        "created_at": generated_at,
        "context_captured_at": context.get("context_captured_at") or "unavailable",
        "application": {
            "product": "影界 HDDE",
            "version": context["runtime"].get("app_version")
            or context["runtime"].get("product_version")
            or task.get("app_version")
            or "unavailable",
            "build": context["runtime"].get("build_id")
            or task.get("build_info")
            or task.get("contract_version")
            or task_result.get("contract_version")
            or "unavailable",
            "runtime_id": context["runtime"].get("runtime_id") or "unavailable",
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "task": {
            "task_id": task.get("task_id") or None,
            "status": task.get("task_status") or task.get("status"),
            "current_stage": task.get("processing_stage") or task.get("current_stage"),
            "mode": task.get("mode"),
            "output_profile": task.get("output_profile"),
            "created_at": task.get("created_at"),
            "completed_at": task.get("completed_at") or task.get("updated_at"),
            "duration_ms": task.get("duration_ms") or task_result.get("duration_ms"),
            "error_code": task.get("error_code") or "",
            "input_width": task.get("input_width") or task_result.get("input_width"),
            "input_height": task.get("input_height") or task_result.get("input_height"),
            "input_format": task.get("input_format") or task_result.get("input_format"),
            "input_size_bytes": task.get("input_size_bytes") or task_result.get("input_size_bytes"),
            "target_width": task.get("target_width") or task_result.get("target_width"),
            "target_height": task.get("target_height") or task_result.get("target_height"),
            "target_resolution": task.get("target_resolution") or task_result.get("target_resolution"),
            "output_width": task.get("output_width") or task_result.get("output_width"),
            "output_height": task.get("output_height") or task_result.get("output_height"),
            "output_format": task.get("output_format") or task_result.get("output_format"),
            "error": task.get("error_message") or task.get("task_error") or "",
        },
        "files": {
            "input": _path_summary(
                task.get("input_path") or task.get("source_path"),
                formal_root,
                safe_reference=str(context["references"].get("source") or ""),
            ),
            "output": _path_summary(
                output_path,
                formal_root,
                safe_reference=str(context["references"].get("result") or ""),
            ),
        },
        "output_validation": validation,
        "processing": {
            "route": task.get("route") or task_result.get("route"),
            "contract_version": task.get("contract_version") or task_result.get("contract_version"),
            "formal_directory_available": bool(
                task.get("formal_directory_available")
                if task.get("formal_directory_available") is not None
                else formal_root and formal_root.exists()
            ),
        },
        "quality": {
            "delivery_status": task_report.get("final_delivery_status")
            or task_result.get("final_delivery_status")
            or task.get("final_delivery_status"),
            "delivery_score": task_report.get("delivery_score")
            or task_result.get("delivery_score"),
            "warnings": list(task_report.get("warnings") or task_result.get("warnings") or []),
        },
        "context": context,
        "related_events": list(context.get("related_events") or [])[-7:],
        "trace_summary": (context.get("error") or {}).get("trace_summary") or "",
        "attachment_manifest": safe_attachments,
        "privacy_manifest": {
            "contains_original_image": False,
            "contains_output_image": False,
            "contains_screenshot": False,
            "contains_settings": False,
            "contains_full_absolute_paths": False,
            "contains_other_tasks": False,
            "redacted": True,
            "attachments_require_user_action": True,
            "auto_upload": False,
        },
    }
    report["privacy"] = report["privacy_manifest"]
    text_report = (
        "影界 HDDE 用户问题反馈\n"
        f"生成时间: {report['created_at']}\n"
        f"反馈包编号: {bundle_id}\n"
        f"反馈合同: {FEEDBACK_SCHEMA_VERSION}\n"
        f"任务ID: {report['task']['task_id']}\n"
        f"任务状态: {report['task']['status'] or '未知'}\n"
        f"功能来源: {context['feature']['name']}\n"
        f"发生阶段: {context['stage'] or '未知'}\n"
        f"处理模式: {report['task']['mode'] or '未知'}\n"
        f"输入尺寸: {report['task']['input_width'] or '-'} × {report['task']['input_height'] or '-'}\n"
        f"输出尺寸: {report['task']['output_width'] or '-'} × {report['task']['output_height'] or '-'}\n"
        f"输出文件: {report['files']['output']['file_name'] or '未生成'}\n"
        f"输出可读取: {'是' if validation['decodable'] else '否'}\n"
        f"错误摘要: {report['task']['error'] or '无'}\n"
        "\n本反馈包仅包含当前任务的脱敏文本信息，不包含原图、结果图、截图、Settings 或完整绝对路径。\n"
    )

    try:
        with zipfile.ZipFile(bundle_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("feedback_report.txt", _redact_string(text_report).encode("utf-8"))
            archive.writestr("feedback_report.json", _json_bytes(report))
            archive.writestr("task_log.txt", _task_log(task).encode("utf-8"))
    except Exception as exc:
        if bundle_path.exists():
            try:
                bundle_path.unlink()
            except Exception:
                pass
        return {
            "feedback_bundle_status": "FAIL",
            "feedback_bundle_path": "",
            "feedback_bundle_size": 0,
            "feedback_bundle_redacted": True,
            "feedback_bundle_error": str(exc),
        }

    return {
        "feedback_bundle_status": "PASS",
        "feedback_bundle_path": str(bundle_path),
        "feedback_bundle_size": bundle_path.stat().st_size,
        "feedback_bundle_redacted": True,
        "feedback_bundle_error": "",
        "feedback_bundle_id": bundle_id,
        "feedback_schema_version": FEEDBACK_SCHEMA_VERSION,
        "generated_at": generated_at,
        "context_captured_at": context.get("context_captured_at") or "unavailable",
        "context_preview": feedback_context_preview(context),
        "bundle_payload": redact(report),
    }
