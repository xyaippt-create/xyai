from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from engine.diagnostics.runtime_logging import sanitize_diagnostic_value


PASS = "PASS"
DEFERRED_BY_A_LINE = "DEFERRED_BY_A_LINE"
NOT_APPLICABLE = "NOT_APPLICABLE"
LINKED = "LINKED"
NOT_CREATED = "NOT_CREATED"
FEEDBACK_TRACE_CONTRACT_VERSION = "HDDE-feedback-trace-contract-v1"

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
    "system_settings": PASS,
    "runtime_failure": PASS,
}

FEATURE_NAMES = {
    "enhancement_1080p": "1080P画质",
    "enhancement_4k": "4K画质增强",
    "image_compression": "图片压缩",
    "color_correction": "单图自动颜色校正",
    "batch_processing": "多图批处理 / 任务队列",
    "processing_center": "处理中心",
    "quality_confirm": "对比质检 / 人工结果确认",
    "output_center": "输出中心",
    "smart_delivery": "文件交付",
    "local_retouch": "瑕疵修复",
    "runtime_failure": "正式启动 / 本地运行异常",
}

FEATURE_NAMES["system_settings"] = "\u7cfb\u7edf\u8bbe\u7f6e"

FEATURE_TRACE_CONTRACTS = {
    "enhancement_1080p": {"module_id": "hdde.enhancement.1080p", "task": True, "result": True, "delivery": True},
    "enhancement_4k": {"module_id": "hdde.enhancement.4k", "task": True, "result": True, "delivery": True},
    "image_compression": {"module_id": "hdde.image.compression", "task": True, "result": True, "delivery": True},
    "color_correction": {"module_id": "hdde.color.correction", "task": True, "result": True, "delivery": True},
    "batch_processing": {"module_id": "hdde.processing.batch", "task": True, "result": True, "delivery": True},
    "processing_center": {"module_id": "hdde.processing.center", "task": True, "result": True, "delivery": True},
    "quality_confirm": {"module_id": "hdde.quality.confirm", "task": True, "result": True, "delivery": False},
    "output_center": {"module_id": "hdde.output.center", "task": False, "result": True, "delivery": True},
    "smart_delivery": {"module_id": "hdde.smart.delivery", "task": False, "result": False, "delivery": True},
    "local_retouch": {"module_id": "hdde.local.retouch", "task": True, "result": True, "delivery": True},
    "system_settings": {"module_id": "hdde.system.settings", "task": False, "result": False, "delivery": False},
    "runtime_failure": {"module_id": "hdde.runtime.failure", "task": False, "result": False, "delivery": False},
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
        "module_id",
        "operation_id",
        "task_id",
        "batch_id",
        "result_id",
        "delivery_id",
        "stage",
        "result",
        "status",
        "naming_mode",
        "file_count",
        "completed_count",
        "failed_count",
        "error_category",
        "error_code",
        "error_id",
        "error_fingerprint",
        "exception_type",
        "code_location",
        "module",
        "trace_id",
        "reason",
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
    requested_key = str(requested or "").strip()
    if requested_key in RECENT_FEATURE_COVERAGE:
        return requested_key
    task_context = task.get("task_context") if isinstance(task.get("task_context"), Mapping) else {}
    key = str(task_context.get("feature_key") or task.get("feature_key") or task.get("source_feature") or "").strip()
    if key in RECENT_FEATURE_COVERAGE:
        return key
    if task.get("task_family") == "color_correction":
        return "color_correction"
    return "processing_center"


def _identifier(*values: Any, limit: int = 160) -> str | None:
    for value in values:
        text = _text(value, limit=limit)
        if text:
            return text
    return None


def _explicit_boolean(*values: Any) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "yes", "1"}:
                return True
            if normalized in {"false", "no", "0"}:
                return False
    return None


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        try:
            converted = converter()
        except Exception:
            return {}
        return dict(converted) if isinstance(converted, Mapping) else {}
    return {}


def _positive_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _finite_ratio(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    ratio = float(value)
    return ratio if -1000.0 <= ratio <= 1.0 else None


def _dimension_value(value: Any, name: str) -> int | None:
    dimensions = value if isinstance(value, Mapping) else {}
    number = dimensions.get(name)
    return int(number) if isinstance(number, int) and not isinstance(number, bool) and number > 0 else None


def _base_name(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return re.split(r"[\\/]", text)[-1][:240] or None


def _route_identifier(*values: Any) -> str | None:
    for value in values:
        text = " ".join(str(value or "").splitlines()).strip()
        if not text:
            continue
        if re.fullmatch(r"/[A-Za-z0-9/_-]{1,159}", text) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", text):
            return text
    return None


def _link_status(value: Any, applicable: bool) -> str:
    if isinstance(value, bool):
        return LINKED if value else (NOT_CREATED if applicable else NOT_APPLICABLE)
    if value not in (None, "", [], {}):
        return LINKED
    return NOT_CREATED if applicable else NOT_APPLICABLE


def _module_context(
    record: Mapping[str, Any],
    *,
    feature_key: str,
    review_status: Any,
    runtime_context: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep specialist diagnostics out of the shared trace contract."""

    if feature_key in {"enhancement_1080p", "enhancement_4k"}:
        return {
            "mode": _text(record.get("mode"), limit=80),
            "target_resolution": _text(record.get("target_resolution"), limit=40),
            "output_profile": _text(record.get("output_profile"), limit=80),
            "processing_disposition": _text(record.get("processing_disposition"), limit=120),
            "quality_conclusion": _text(record.get("quality_conclusion"), limit=160),
        }
    if feature_key == "image_compression":
        result = _as_mapping(record.get("result"))
        task_result = _as_mapping(record.get("task_result"))
        request = _as_mapping(record.get("request"))
        params = _as_mapping(request.get("params"))
        source_dimensions = result.get("source_dimensions")
        output_dimensions = result.get("output_dimensions")
        source_bytes = _positive_int(result.get("source_size_bytes"))
        output_bytes = _positive_int(result.get("output_size_bytes"))
        ratio = _finite_ratio(result.get("size_reduction_ratio"))
        if ratio is None and source_bytes and output_bytes is not None:
            ratio = (source_bytes - output_bytes) / source_bytes
        output_created = result.get("output_created") is True
        keep_original = bool(
            str(record.get("winner_scheme_id") or "") == "KEEP_ORIGINAL"
            or _as_mapping(record.get("winner_public")).get("source_selected") is True
        )
        target_format_mode = _text(
            record.get("target_format") or params.get("target_format"),
            limit=24,
        )
        source_sha256 = _text(
            result.get("source_sha256")
            or task_result.get("source_sha256")
            or _as_mapping(record.get("source_metadata")).get("sha256"),
            limit=64,
        ) or None
        result_sha256 = _text(
            result.get("output_sha256") or task_result.get("output_sha256"),
            limit=64,
        ) if output_created else ""
        return {
            "operation_mode": _text(record.get("operation_mode"), limit=80),
            "technical_status": _text(result.get("technical_status"), limit=80),
            "visual_review_status": _text(result.get("visual_review_status"), limit=80),
            "source_format": _text(result.get("source_format"), limit=16) or None,
            "target_format_mode": target_format_mode or None,
            "output_format": _text(result.get("output_format"), limit=16) or None,
            "source_width": _dimension_value(source_dimensions, "width"),
            "source_height": _dimension_value(source_dimensions, "height"),
            "result_width": _dimension_value(output_dimensions, "width"),
            "result_height": _dimension_value(output_dimensions, "height"),
            "source_bytes": source_bytes,
            "result_bytes": output_bytes,
            "real_compression_ratio": ratio,
            "keep_original": keep_original,
            "source_file_name": _base_name(record.get("original_filename") or result.get("source_path") or record.get("source_path")),
            "result_file_name": _base_name(result.get("output_path") or task_result.get("output_path") or record.get("output_path")) if output_created else None,
            "source_sha256": source_sha256,
            "result_sha256": result_sha256 or None,
            "has_alpha": _explicit_boolean(
                record.get("source_has_real_transparency"),
                _as_mapping(result.get("alpha_details")).get("alpha_present"),
            ),
            "output_created": output_created,
        }
    if feature_key == "color_correction":
        return {
            "operation_mode": _text(record.get("operation_mode"), limit=80),
            "batch_index": record.get("batch_index") if isinstance(record.get("batch_index"), int) else None,
            "review_status": _text(review_status, limit=80),
        }
    if feature_key == "batch_processing":
        return {
            "item_count": record.get("item_count") if isinstance(record.get("item_count"), int) else None,
            "completed_count": record.get("completed_count") if isinstance(record.get("completed_count"), int) else None,
            "failed_count": record.get("failed_count") if isinstance(record.get("failed_count"), int) else None,
        }
    if feature_key in {"processing_center", "quality_confirm", "output_center"}:
        return {
            "task_family": _text(record.get("task_family"), limit=80),
            "review_status": _text(review_status, limit=80),
        }
    if feature_key == "smart_delivery":
        return {
            "success_count": record.get("success_count") if isinstance(record.get("success_count"), int) else None,
            "failure_count": record.get("failure_count") if isinstance(record.get("failure_count"), int) else None,
        }
    if feature_key == "local_retouch":
        return {
            "session_status": _text(record.get("session_status") or record.get("status"), limit=80),
            "review_status": _text(review_status, limit=80),
        }
    if feature_key == "system_settings":
        return {
            "settings_status": _text(runtime_context.get("settings_status"), limit=80),
            "formal_root_status": _text(runtime_context.get("formal_root_status"), limit=80),
        }
    return {
        "runtime_status": _text(runtime_context.get("runtime_status"), limit=80),
        "backend_health": _text(runtime_context.get("backend_health"), limit=80),
        "error_code": _text(runtime_context.get("error_code"), limit=120),
    }


def build_feedback_context(
    task: Mapping[str, Any] | None,
    *,
    source_feature: str | None = None,
    runtime: Mapping[str, Any] | None = None,
    user_description: str = "",
    captured_at: str = "",
    route: str = "",
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
    result_status = record.get("result_status") or result.get("result_status") or result.get("status")
    output_created = _explicit_boolean(record.get("output_created"), result.get("output_created"))
    if output_created is None and output_path:
        try:
            output_created = Path(str(output_path)).is_file()
        except OSError:
            output_created = None
    second_edit_used = _explicit_boolean(
        record.get("second_edit_used"),
        result.get("second_edit_used"),
        task_context.get("second_edit_used"),
    )
    runtime_context = _runtime_context(runtime)
    review = record.get("review") if isinstance(record.get("review"), Mapping) else {}
    review_status = (
        record.get("result_review_status")
        or review.get("status")
        or result.get("review_status")
        or "not_available"
    )
    contract = FEATURE_TRACE_CONTRACTS[feature_key]
    operation_id = _identifier(
        task_context.get("operation_id"),
        record.get("operation_id"),
        result.get("operation_id"),
    )
    trace_id = _identifier(
        task_context.get("trace_id"),
        record.get("trace_id"),
        result.get("trace_id"),
        error_context.get("trace_id"),
    )
    module_id = contract["module_id"]
    batch_id = _identifier(task_context.get("batch_id"), record.get("batch_id"))
    error_id = _identifier(error_context.get("error_id"), record.get("error_id"), limit=80)
    business_error_present = bool(
        error_context
        or record.get("failure_reason")
        or record.get("error_message")
        or record.get("task_error")
        or str(status or "").lower() in {"failed", "blocked"}
    )
    error_code = _identifier(record.get("error_code"), result.get("error_code"))
    if not error_code and not business_error_present:
        error_code = _identifier(runtime_context.get("error_code"))
    error_fingerprint = _identifier(error_context.get("error_fingerprint"), limit=80)
    related_events = _related_events(record.get("related_events"))
    route_value = _route_identifier(
        route,
        task_context.get("route"),
        record.get("route"),
        task_context.get("route_family"),
        record.get("route_family"),
    )
    started_at = _identifier(record.get("started_at"), record.get("created_at"), last_lifecycle.get("recorded_at"), limit=80)
    completed_at = _identifier(record.get("completed_at"), limit=80)
    common_context = {
        "feature_key": feature_key,
        "module_id": module_id,
        "operation_id": operation_id,
        "trace_id": trace_id,
        "task_id": _identifier(task_id),
        "result_id": _identifier(result_id),
        "delivery_id": _identifier(delivery_id),
        "batch_id": batch_id,
        "route": route_value,
        "stage": _text(stage, limit=120),
        "status": _text(status, limit=120),
        "task_status": _text(status, limit=120) or None,
        "result_status": _text(result_status, limit=120) or None,
        "output_created": output_created,
        "second_edit_used": second_edit_used,
        "context_binding": "LINKED" if task_id or result_id else "UNAVAILABLE",
        "started_at": started_at,
        "completed_at": completed_at,
        "error_id": error_id,
        "error_code": error_code,
        "error_fingerprint": error_fingerprint,
        "runtime_id": _identifier(runtime_context.get("runtime_id"), limit=120),
        "build_id": _identifier(runtime_context.get("build_id"), limit=180),
    }
    links = {
        "operation": _link_status(operation_id, bool(record)),
        "trace": _link_status(trace_id, bool(record) or bool(error_id)),
        "task": _link_status(task_id, bool(contract["task"])),
        "result": _link_status(result_id, bool(contract["result"])),
        "delivery": _link_status(delivery_id, bool(contract["delivery"])),
        "error": _link_status(error_id, bool(error_code)),
        "log": _link_status(runtime_context.get("runtime_log_available"), True),
        "event": _link_status(related_events, bool(operation_id or trace_id or task_id or error_id)),
    }
    module_context = _module_context(
        record,
        feature_key=feature_key,
        review_status=review_status,
        runtime_context=runtime_context,
    )
    return {
        "context_version": "HDDE-feedback-context-v3",
        "feedback_trace_contract": {
            "version": FEEDBACK_TRACE_CONTRACT_VERSION,
            "fact_policy": "existing_facts_only",
            "common_context": common_context,
            "module_context": module_context,
            "links": links,
        },
        "common_context": common_context,
        "module_context": module_context,
        "context_captured_at": _text(captured_at, limit=80)
        or datetime.now().isoformat(timespec="milliseconds"),
        "product_version": runtime_context.get("product_version") or runtime_context.get("app_version") or "",
        "feature_key": feature_key,
        "module_id": module_id,
        "operation_id": operation_id,
        "trace_id": trace_id,
        "feature": {
            "key": feature_key,
            "name": FEATURE_NAMES[feature_key],
            "coverage_status": RECENT_FEATURE_COVERAGE[feature_key],
        },
        "operation": _text(record.get("operation_mode") or record.get("mode"), limit=120),
        "purpose": _text(task_context.get("purpose") or record.get("purpose"), limit=120),
        "route_family": _text(task_context.get("route_family") or record.get("route_family"), limit=120),
        "stage": _text(stage, limit=120),
        "task_id": common_context["task_id"],
        "result_id": common_context["result_id"],
        "delivery_id": common_context["delivery_id"],
        "batch_id": batch_id,
        "status": _text(status, limit=120),
        "task_status": _text(status, limit=120),
        "formal_root_status": runtime_context.get("formal_root_status") or "",
        "error": {
            "code": error_code or "",
            "stage": _text(error_context.get("error_stage") or record.get("error_stage") or record.get("failed_stage"), limit=160),
            "error_id": error_id or "",
            "error_fingerprint": error_fingerprint or "",
            "exception_type": _text(error_context.get("exception_type"), limit=160),
            "code_location": _code_reference(error_context.get("code_location"), limit=300),
            "module": _text(error_context.get("module"), limit=200),
            "trace_id": trace_id or "",
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
        "related_events": related_events,
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
        "source_reference_available": bool(
            isinstance(context.get("references"), Mapping)
            and context.get("references", {}).get("source")
        ),
    }
