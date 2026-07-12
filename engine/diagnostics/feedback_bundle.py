from __future__ import annotations

import json
import os
import platform
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
                is_project_tmp = (PROJECT_ROOT / "tmp" / "runtime_data").resolve() in saved_path.resolve().parents
            except Exception:
                is_project_tmp = False
            if not is_project_tmp:
                return saved_path
    if os.name == "nt" and Path("D:/").exists():
        return Path("D:/影界文件")
    documents = (Path(os.environ["USERPROFILE"]) / "Documents") if os.name == "nt" and os.environ.get("USERPROFILE") else Path.home() / "Documents"
    return documents / "影界HDDE"


DEFAULT_FEEDBACK_DIR = _default_app_data_root() / "诊断反馈"

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
    if re.search(r"[A-Za-z]:\\|/", text):
        path = Path(text)
        if path.suffix:
            return f"<redacted_path>/{path.name}"
        return "<redacted_path>"
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    if user:
        text = text.replace(user, "<redacted_user>")
    return text


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, Path):
        return _redact_string(str(value))
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(redact(payload), ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _delivery_status_explanation() -> dict[str, Any]:
    return {
        "scope": "diagnostic_zip_only",
        "raw_status_note": (
            "final_delivery_status 为后端原始交付状态，用于表示任务处理与后端门禁结果；"
            "前台会根据文字清晰度、纹理保持力、边缘质量、限制原因等指标进行二次解释。"
        ),
        "user_visible_status_note": (
            "若核心指标偏低，即使后端原始状态为 PASS，前台仍会显示为“建议人工复核 / 1080P 本地预览”。"
            "请以前台交付状态作为面向用户的最终交付口径。"
        ),
        "resolution_rules": [
            {
                "backend_raw_status": "PASS",
                "condition": "text_clarity_score >= 60, texture_score >= 60, edge_quality_score >= 65 and no limitation reason",
                "frontend_status": "可交付",
                "frontend_badge": "1080P 高清成品",
            },
            {
                "backend_raw_status": "PASS_WITH_LIMITATION",
                "condition": "any limitation reason from backend delivery guard",
                "frontend_status": "建议人工复核",
                "frontend_badge": "1080P 本地预览",
            },
            {
                "backend_raw_status": "PASS",
                "condition": "text_clarity_score < 60 or texture_score < 60 or edge_quality_score < 65",
                "frontend_status": "建议人工复核",
                "frontend_badge": "1080P 本地预览",
            },
            {
                "backend_raw_status": "FAIL or REJECT",
                "condition": "backend delivery guard failed or rejected",
                "frontend_status": "不建议交付",
                "frontend_badge": "不建议交付",
            },
        ],
    }


def generate_feedback_bundle(task_id: str, task: dict[str, Any] | None, output_dir: Path | None = None) -> dict[str, Any]:
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

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_task_id = _safe_filename(task_id or "unknown_task")
    bundle_path = target_dir / f"影界诊断_V046_{safe_task_id}_{timestamp}.zip"
    task = dict(task or {})
    task_result = dict(task.get("task_result") or {})
    task_report = dict(task.get("task_report") or {})
    diagnostics = dict(task.get("debug_quality") or {})
    pipeline_trace = {
        "task_id": task.get("task_id") or task_id,
        "status": task.get("task_status") or task.get("status"),
        "mode": task.get("mode"),
        "output_profile": task.get("output_profile"),
        "output_format": task.get("output_format"),
        "final_output_url": task.get("final_output_url") or task.get("enhancedUrl"),
        "pipeline_call_count": task.get("pipeline_call_count", 1 if task.get("task_status") == "completed" else 0),
        "debug_timing": task.get("debug_timing") or {},
    }
    manifest = {
        "bundle_version": "V046-feedback-v1",
        "task_id": task.get("task_id") or task_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "contains_original_image": False,
        "contains_final_output": False,
        "redacted": True,
        "files": [
            "manifest.json",
            "task_summary.json",
            "diagnostics.json",
            "pipeline_trace.json",
            "quality_metrics.json",
            "system_info.json",
            "error_summary.txt",
            "README.txt",
        ],
    }
    system_info = {
        "app_version": "V0.4.6",
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }
    error_summary = task.get("error_message") or task.get("task_error") or ""
    delivery_explanation = _delivery_status_explanation()
    task_summary_payload = dict(task_result or task)
    task_summary_payload["delivery_status_explanation"] = delivery_explanation
    readme = (
        "VisualMasterPro local feedback bundle.\n"
        "This archive is redacted by default and does not include original images or final outputs.\n"
        "Use it to inspect task status, quality metrics, pipeline trace and errors.\n"
        "\n"
        "交付状态说明：\n"
        "final_delivery_status 为后端原始交付状态，用于表示任务处理与后端门禁结果；前台会根据文字清晰度、纹理保持力、边缘质量、限制原因等指标进行二次解释。\n"
        "若核心指标偏低，即使后端原始状态为 PASS，前台仍会显示为“建议人工复核 / 1080P 本地预览”。请以前台交付状态作为面向用户的最终交付口径。\n"
        "映射规则：raw PASS 且核心指标通过 -> 可交付 / 1080P 高清成品；PASS_WITH_LIMITATION -> 建议人工复核 / 1080P 本地预览；raw PASS 但 text_clarity_score < 60 或 texture_score < 60 或 edge_quality_score < 65 -> 建议人工复核 / 1080P 本地预览；FAIL / REJECT -> 不建议交付。\n"
    )

    try:
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", _json_bytes(manifest))
            archive.writestr("task_summary.json", _json_bytes(task_summary_payload))
            archive.writestr("diagnostics.json", _json_bytes(diagnostics))
            archive.writestr("pipeline_trace.json", _json_bytes(pipeline_trace))
            archive.writestr("quality_metrics.json", _json_bytes(task_report))
            archive.writestr("system_info.json", _json_bytes(system_info))
            archive.writestr("error_summary.txt", _redact_string(str(error_summary)).encode("utf-8"))
            archive.writestr("README.txt", readme.encode("utf-8"))
    except Exception as exc:
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
    }
