from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Mapping

from engine.diagnostics.runtime_logging import sanitize_diagnostic_value


PASS = "PASS"
DEFERRED_BY_A_LINE = "DEFERRED_BY_A_LINE"
NOT_APPLICABLE = "NOT_APPLICABLE"

RECENT_FEATURE_COVERAGE = {
    "enhancement_1080p": PASS,
    "enhancement_4k": PASS,
    "image_compression": PASS,
    "color_correction": PASS,
    "batch_processing": PASS,
    "processing_center": PASS,
    "quality_confirm": PASS,
    "output_center": PASS,
    "smart_delivery": PASS,
    "local_retouch": PASS,
    "image_diagnosis": PASS,
    "runtime_failure": PASS,
}

FEATURE_NAMES = {
    "enhancement_1080p": "1080P高清处理",
    "enhancement_4k": "4K高清画质增强",
    "image_compression": "图片压缩",
    "color_correction": "单图自动颜色校正",
    "batch_processing": "多图批处理 / 任务队列",
    "processing_center": "处理中心",
    "quality_confirm": "对比质检 / 人工结果确认",
    "output_center": "输出中心",
    "smart_delivery": "智能交付 / 批量命名",
    "local_retouch": "交付标记与局部修整",
    "image_diagnosis": "图片诊断",
    "runtime_failure": "正式启动 / 本地运行异常",
}

_RUNTIME_FIELDS = {
    "app_version",
    "product_version",
    "build_id",
    "runtime_id",
    "runtime_status",
    "backend_health",
    "backend_connection_status",
    "frontend_connection_status",
    "settings_status",
    "formal_root_status",
    "host",
    "port",
    "runtime_log_reference",
    "runtime_log_available",
    "error_type",
    "error_code",
    "error_stage",
    "error_summary",
}
def _text(value: Any, *, limit: int = 1000) -> str:
    text = sanitize_diagnostic_value(value)
    return text[:limit]


def _file_reference(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    suffix = re.split(r"[\\/]", text)[-1]
    suffix = "." + suffix.rsplit(".", 1)[-1].lower() if "." in suffix else ""
    reference = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"file_{reference}{suffix[:12]}"


def _code_reference(value: Any, *, limit: int = 600) -> str:
    text = " ".join(str(value or "").replace("\\", "/").splitlines()).strip()
    if not text or re.match(r"^[A-Za-z]:/|^/", text):
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_./:<>= -]+", text):
        return ""
    return text[:limit]


def _file_size_bucket(value: Any) -> str:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return ""
    if size < 1024 * 1024:
        return "<1MB"
    if size < 5 * 1024 * 1024:
        return "1-5MB"
    if size < 20 * 1024 * 1024:
        return "5-20MB"
    if size < 50 * 1024 * 1024:
        return "20-50MB"
    return ">=50MB"


def _safe_input_metadata(record: Mapping[str, Any]) -> dict[str, Any]:
    task_context = record.get("task_context") if isinstance(record.get("task_context"), Mapping) else {}
    stored = task_context.get("safe_input_metadata") if isinstance(task_context.get("safe_input_metadata"), Mapping) else {}
    source = record.get("source_metadata") if isinstance(record.get("source_metadata"), Mapping) else {}
    metadata = stored or source
    width = metadata.get("width")
    height = metadata.get("height")
    channels = metadata.get("channels")
    return {
        "format": _text(metadata.get("format"), limit=16),
        "width": int(width) if isinstance(width, int) and not isinstance(width, bool) and width > 0 else None,
        "height": int(height) if isinstance(height, int) and not isinstance(height, bool) and height > 0 else None,
        "color_mode": _text(metadata.get("color_mode") or metadata.get("mode"), limit=24),
        "channels": int(channels) if isinstance(channels, int) and not isinstance(channels, bool) and channels > 0 else None,
        "alpha": bool(metadata.get("alpha") if "alpha" in metadata else metadata.get("has_alpha")),
        "orientation": int(metadata["orientation"]) if isinstance(metadata.get("orientation"), int) else None,
        "file_size_bucket": _text(metadata.get("file_size_bucket"), limit=24)
        or _file_size_bucket(metadata.get("size_bytes")),
    }


def _related_events(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    allowed = {
        "timestamp",
        "event",
        "runtime_id",
        "run_kind",
        "feature_key",
        "feature",
        "task_id",
        "batch_id",
        "result_id",
        "delivery_id",
        "stage",
        "result",
        "status",
        "error_id",
        "error_fingerprint",
        "exception_type",
        "code_location",
        "module",
        "impact",
    }
    events: list[dict[str, Any]] = []
    for item in value[-7:]:
        if not isinstance(item, Mapping):
            continue
        events.append({key: _text(item.get(key), limit=300) for key in allowed if item.get(key) not in (None, "")})
    return events


def _runtime_context(value: Mapping[str, Any] | None) -> dict[str, Any]:
    runtime = value if isinstance(value, Mapping) else {}
    normalized: dict[str, Any] = {}
    for key in _RUNTIME_FIELDS:
        item = runtime.get(key)
        if key == "port":
            normalized[key] = int(item) if isinstance(item, int) and not isinstance(item, bool) else None
        elif key in {"runtime_log_available"}:
            normalized[key] = bool(item)
        elif key == "runtime_log_reference":
            reference = str(item or "").replace("\\", "/")
            parts = [part for part in reference.split("/") if part]
            relative = "/".join(parts[-3:])
            normalized[key] = (
                f"<已隐藏路径>/{relative}"
                if re.match(r"^[A-Za-z]:/|^/", reference)
                else relative
            )[-160:]
        else:
            normalized[key] = _text(item, limit=300) if item not in (None, "") else ""
    return normalized


def _feature_key(task: Mapping[str, Any], requested: str | None) -> str:
    task_context = task.get("task_context") if isinstance(task.get("task_context"), Mapping) else {}
    key = str(task_context.get("feature_key") or task.get("feature_key") or requested or task.get("source_feature") or "").strip()
    if key in RECENT_FEATURE_COVERAGE:
        return key
    if task.get("task_family") == "color_correction":
        return "color_correction"
    return "processing_center"


def build_feedback_context(
    task: Mapping[str, Any] | None,
    *,
    source_feature: str | None = None,
    runtime: Mapping[str, Any] | None = None,
    user_description: str = "",
    captured_at: str = "",
) -> dict[str, Any]:
    record = task if isinstance(task, Mapping) else {}
    result = record.get("result") if isinstance(record.get("result"), Mapping) else {}
    if not result:
        result = record.get("task_result") if isinstance(record.get("task_result"), Mapping) else {}
    lifecycle = record.get("lifecycle") if isinstance(record.get("lifecycle"), list) else []
    last_lifecycle = lifecycle[-1] if lifecycle and isinstance(lifecycle[-1], Mapping) else {}
    task_context = record.get("task_context") if isinstance(record.get("task_context"), Mapping) else {}
    error_context = record.get("error_context") if isinstance(record.get("error_context"), Mapping) else {}
    feature_key = _feature_key(record, source_feature)
    status = record.get("task_status") or record.get("status") or last_lifecycle.get("status")
    stage = (
        record.get("processing_stage")
        or record.get("current_stage")
        or last_lifecycle.get("stage")
        or last_lifecycle.get("status")
        or status
    )
    task_id = task_context.get("task_id") or record.get("task_id")
    result_id = record.get("result_id") or result.get("result_id")
    source_path = record.get("source_path") or record.get("input_path")
    output_path = record.get("result_file") or record.get("output_path") or result.get("result_file") or result.get("output_path") or result.get("final_output_path")
    delivery_id = record.get("delivery_id") or result.get("delivery_id")
    runtime_context = _runtime_context(runtime)
    review = record.get("review") if isinstance(record.get("review"), Mapping) else {}
    review_status = (
        record.get("result_review_status")
        or review.get("status")
        or result.get("review_status")
        or "not_available"
    )
    return {
        "context_version": "HDDE-feedback-context-v3",
        "context_captured_at": _text(captured_at, limit=80)
        or datetime.now().isoformat(timespec="milliseconds"),
        "product_version": runtime_context.get("product_version") or runtime_context.get("app_version") or "",
        "feature_key": feature_key,
        "feature": {
            "key": feature_key,
            "name": FEATURE_NAMES[feature_key],
            "coverage_status": RECENT_FEATURE_COVERAGE[feature_key],
        },
        "operation": _text(record.get("operation_mode") or record.get("mode"), limit=120),
        "purpose": _text(task_context.get("purpose") or record.get("purpose"), limit=120),
        "route_family": _text(task_context.get("route_family") or record.get("route_family"), limit=120),
        "stage": _text(stage, limit=120),
        "task_id": _text(task_id, limit=160) if task_id else None,
        "result_id": _text(result_id, limit=160) if result_id else None,
        "delivery_id": _text(delivery_id, limit=160) if delivery_id else None,
        "batch_id": _text(task_context.get("batch_id") or record.get("batch_id"), limit=160)
        if task_context.get("batch_id") or record.get("batch_id")
        else None,
        "status": _text(status, limit=120),
        "task_status": _text(status, limit=120),
        "formal_root_status": runtime_context.get("formal_root_status") or "",
        "error": {
            "code": _text(record.get("error_code") or result.get("error_code"), limit=160),
            "stage": _text(error_context.get("error_stage") or record.get("error_stage") or record.get("failed_stage"), limit=160),
            "error_id": _text(error_context.get("error_id"), limit=80),
            "error_fingerprint": _text(error_context.get("error_fingerprint"), limit=80),
            "exception_type": _text(error_context.get("exception_type"), limit=160),
            "code_location": _code_reference(error_context.get("code_location"), limit=300),
            "module": _text(error_context.get("module"), limit=200),
            "trace_id": _text(error_context.get("trace_id"), limit=80),
            "trace_summary": _code_reference(error_context.get("trace_summary"), limit=600),
            "summary": _text(
                error_context.get("reason")
                or record.get("failure_reason")
                or record.get("error_message")
                or record.get("task_error")
                or result.get("failure_reason"),
                limit=500,
            ),
        },
        "references": {
            "source": _text(task_context.get("source_reference"), limit=100) or _file_reference(source_path),
            "result": _file_reference(output_path),
        },
        "safe_input_metadata": _safe_input_metadata(record),
        "related_events": _related_events(record.get("related_events")),
        "review_status": _text(review_status, limit=120),
        "runtime": runtime_context,
        "user_description": _text(user_description, limit=1000),
    }


def feedback_context_preview(context: Mapping[str, Any]) -> dict[str, Any]:
    feature = context.get("feature") if isinstance(context.get("feature"), Mapping) else {}
    runtime = context.get("runtime") if isinstance(context.get("runtime"), Mapping) else {}
    error = context.get("error") if isinstance(context.get("error"), Mapping) else {}
    return {
        "feature_name": str(feature.get("name") or "当前功能"),
        "stage": str(context.get("stage") or "不可用"),
        "status": str(context.get("status") or "不可用"),
        "app_version": str(runtime.get("app_version") or "不可用"),
        "build_id": str(runtime.get("build_id") or "不可用"),
        "runtime_id": str(runtime.get("runtime_id") or "不可用"),
        "error_id": str(error.get("error_id") or "不可用"),
        "error_fingerprint": str(error.get("error_fingerprint") or "不可用"),
        "backend_health": str(runtime.get("backend_health") or "不可用"),
        "runtime_log_available": bool(runtime.get("runtime_log_available")),
        "task_reference_available": bool(context.get("task_id")),
        "result_reference_available": bool(context.get("result_id")),
        "delivery_reference_available": bool(context.get("delivery_id")),
    }
