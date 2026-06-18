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


DEFAULT_FEEDBACK_DIR = Path("D:/影界文件/诊断反馈") if os.name == "nt" else Path.home() / "影界文件" / "诊断反馈"

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
    readme = (
        "VisualMasterPro local feedback bundle.\n"
        "This archive is redacted by default and does not include original images or final outputs.\n"
        "Use it to inspect task status, quality metrics, pipeline trace and errors.\n"
    )

    try:
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", _json_bytes(manifest))
            archive.writestr("task_summary.json", _json_bytes(task_result or task))
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
