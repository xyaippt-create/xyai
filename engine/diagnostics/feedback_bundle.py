from __future__ import annotations

import hashlib
import io
import json
import os
import re
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from engine.diagnostics.feedback_context import build_feedback_context, feedback_context_preview
from engine.diagnostics.runtime_logging import sanitize_diagnostic_value


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FEEDBACK_SCHEMA_VERSION = "HDDE-user-feedback-v3"
FEEDBACK_ZIP_ENTRIES = ("feedback.json", "related.log", "timeline.json", "manifest.json")
PAYLOAD_ENTRIES = FEEDBACK_ZIP_ENTRIES[:3]
EVALUATION_DECISIONS = frozenset({"ACCEPTED", "NEEDS_ADJUSTMENT", "UNUSABLE"})
EVALUATION_REASONS = frozenset({
    "EFFECT_TOO_WEAK",
    "OVER_PROCESSED",
    "COLOR_ABNORMAL",
    "QUALITY_DEGRADED",
    "LOCAL_DAMAGE",
    "TEXT_OR_LOGO_DAMAGE",
    "EDGE_ARTIFACT",
    "RESULT_NOT_AS_EXPECTED",
    "WORKFLOW_PROBLEM",
    "OTHER",
})
IMAGE_EVIDENCE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".avif", ".heic", ".heif"})
COMMON_CONTEXT_FIELDS = (
    "feature_key",
    "module_id",
    "operation_id",
    "trace_id",
    "task_id",
    "result_id",
    "delivery_id",
    "batch_id",
    "route",
    "stage",
    "status",
    "task_status",
    "result_status",
    "output_created",
    "second_edit_used",
    "context_binding",
    "started_at",
    "completed_at",
    "error_id",
    "error_code",
    "error_fingerprint",
    "runtime_id",
    "build_id",
)
RELATION_ID_FIELDS = (
    "operation_id",
    "trace_id",
    "task_id",
    "result_id",
    "delivery_id",
    "batch_id",
    "error_id",
)
SECRET_PATTERNS = (
    re.compile(
        r"(?i)(api[_-]?key|token|cookie|authorization|password|secret)"
        r"[\"']?\s*[:=]\s*[\"']?[^\"'\s,}\]]+"
    ),
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
)
ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?i)(?:[a-z]:[\\/]|\\\\|/(?:Users|home|var|tmp|etc)/)[^\s\"'<>|]*"
)
CRITICAL_INFO_MARKERS = (
    "START",
    "CREATE",
    "SELECT",
    "ROUTE",
    "PROCESS",
    "RESULT",
    "DELIVERY",
    "TASK",
    "ERROR",
    "FAIL",
    "SUCCEED",
    "COMPLETE",
    "FEEDBACK",
    "IMPORT",
)


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


def _redact_string(value: str, *, field: str = "") -> str:
    text = str(value)
    if field == "archive_path" and re.fullmatch(
        r"evidence/(?:source|result)\.[a-z0-9]{1,5}",
        text,
    ):
        return text
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("<redacted>", text)
    code_frames = text.split(" <- ")
    if code_frames and all(
        re.fullmatch(r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+:\d+::[A-Za-z0-9_<>-]+", frame)
        for frame in code_frames
    ):
        return text
    text = sanitize_diagnostic_value(text, field=field)
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    if user:
        text = text.replace(user, "<已隐藏用户>")
    return text


def redact(value: Any, *, field: str = "") -> Any:
    if isinstance(value, Mapping):
        return {str(key): redact(item, field=str(key)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item, field=field) for item in value]
    if isinstance(value, Path):
        return _redact_string(str(value), field=field)
    if isinstance(value, str):
        return _redact_string(value, field=field)
    return value


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(redact(payload), ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


def _file_name(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return re.split(r"[\\/]", text)[-1][:240] or None


def _evidence_dimensions(value: Any) -> tuple[int | None, int | None]:
    dimensions = value if isinstance(value, Mapping) else {}
    width = dimensions.get("width")
    height = dimensions.get("height")
    return (
        int(width) if isinstance(width, int) and not isinstance(width, bool) and width > 0 else None,
        int(height) if isinstance(height, int) and not isinstance(height, bool) and height > 0 else None,
    )


def _registered_size(value: Any) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _output_validation(path_value: Any) -> dict[str, Any]:
    if not path_value:
        return {
            "status": "NOT_APPLICABLE",
            "exists": False,
            "decodable": False,
            "width": None,
            "height": None,
            "format": "",
        }
    path = Path(str(path_value))
    if not path.exists() or not path.is_file():
        return {
            "status": "MISSING",
            "exists": False,
            "decodable": False,
            "width": None,
            "height": None,
            "format": "",
        }
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            image_format = str(image.format or "")
        return {
            "status": "PASS",
            "exists": True,
            "decodable": True,
            "width": width,
            "height": height,
            "format": image_format,
        }
    except Exception:
        return {
            "status": "PARTIAL",
            "exists": True,
            "decodable": False,
            "width": None,
            "height": None,
            "format": "",
        }


def _normalized_common_context(context: Mapping[str, Any]) -> dict[str, Any]:
    trace_contract = context.get("feedback_trace_contract")
    trace_contract = trace_contract if isinstance(trace_contract, Mapping) else {}
    common = trace_contract.get("common_context")
    common = common if isinstance(common, Mapping) else context.get("common_context")
    common = common if isinstance(common, Mapping) else {}
    return {key: redact(common.get(key), field=key) for key in COMMON_CONTEXT_FIELDS}


def _normalized_module_context(context: Mapping[str, Any]) -> dict[str, Any]:
    trace_contract = context.get("feedback_trace_contract")
    trace_contract = trace_contract if isinstance(trace_contract, Mapping) else {}
    module = trace_contract.get("module_context")
    module = module if isinstance(module, Mapping) else context.get("module_context")
    return redact(dict(module), field="module_context") if isinstance(module, Mapping) else {}


def _link_status(context: Mapping[str, Any], link_name: str) -> str:
    trace_contract = context.get("feedback_trace_contract")
    trace_contract = trace_contract if isinstance(trace_contract, Mapping) else {}
    links = trace_contract.get("links")
    links = links if isinstance(links, Mapping) else {}
    value = str(links.get(link_name) or "").upper()
    if value == "LINKED":
        return "PASS"
    if value == "NOT_APPLICABLE":
        return "NOT_APPLICABLE"
    if value in {"NOT_CREATED", "MISSING", "NOT_FOUND"}:
        return "NOT_FOUND"
    return "PARTIAL" if value else "NOT_FOUND"


def _event_value(event: Mapping[str, Any], field: str) -> str:
    if field == "feature_key":
        return str(event.get("feature_key") or event.get("feature") or "").strip()
    return str(event.get(field) or "").strip()


def _event_relation(event: Mapping[str, Any], common: Mapping[str, Any]) -> str:
    expected_task = str(common.get("task_id") or "").strip()
    expected_result = str(common.get("result_id") or "").strip()
    expected_delivery = str(common.get("delivery_id") or "").strip()
    actual_task = _event_value(event, "task_id")
    actual_result = _event_value(event, "result_id")
    actual_delivery = _event_value(event, "delivery_id")
    task_matches = bool(expected_task and actual_task == expected_task)
    result_matches = bool(expected_result and actual_result == expected_result)
    delivery_matches = bool(expected_delivery and actual_delivery == expected_delivery)

    if expected_task and actual_task and not task_matches:
        return "EXCLUDE"
    if expected_result and actual_result and not result_matches:
        return "EXCLUDE"
    if expected_delivery and actual_delivery and not delivery_matches:
        if not (task_matches and result_matches):
            return "EXCLUDE"

    expected_feature = str(common.get("feature_key") or "").strip()
    actual_feature = _event_value(event, "feature_key")
    if actual_feature and expected_feature and actual_feature != expected_feature:
        if not (
            task_matches
            and (result_matches or delivery_matches)
            and _event_value(event, "source_feature_key") == expected_feature
        ):
            return "EXCLUDE"

    expected_operation = str(common.get("operation_id") or "").strip()
    expected_trace = str(common.get("trace_id") or "").strip()
    actual_operation = _event_value(event, "operation_id")
    actual_trace = _event_value(event, "trace_id")
    operation_matches = bool(expected_operation and actual_operation == expected_operation)
    trace_matches = bool(expected_trace and actual_trace == expected_trace)
    parent_operation_matches = bool(
        expected_operation and _event_value(event, "parent_operation_id") == expected_operation
    )
    parent_trace_matches = bool(expected_trace and _event_value(event, "parent_trace_id") == expected_trace)
    child_business_link = bool(
        task_matches
        and (result_matches or delivery_matches)
        and _event_value(event, "source_feature_key") == expected_feature
    )
    if actual_operation and expected_operation and not operation_matches:
        if not (child_business_link or parent_operation_matches):
            return "EXCLUDE"
    if actual_trace and expected_trace and not trace_matches:
        if not (child_business_link or parent_trace_matches):
            return "EXCLUDE"

    for field in ("batch_id", "error_id"):
        actual = _event_value(event, field)
        expected = str(common.get(field) or "").strip()
        if actual and expected and actual != expected:
            return "EXCLUDE"

    if any((task_matches, result_matches, delivery_matches, operation_matches, trace_matches)):
        return "P1"

    event_runtime = _event_value(event, "runtime_id")
    expected_runtime = str(common.get("runtime_id") or "").strip()
    if not event_runtime or not expected_runtime or event_runtime != expected_runtime:
        return "EXCLUDE"
    if actual_feature and expected_feature and actual_feature != expected_feature:
        return "EXCLUDE"
    event_stage = _event_value(event, "stage")
    event_route = _event_value(event, "route") or _event_value(event, "route_family")
    expected_stage = str(common.get("stage") or "").strip()
    expected_route = str(common.get("route") or "").strip()
    if (event_stage and expected_stage and event_stage == expected_stage) or (
        event_route and expected_route and event_route == expected_route
    ) or (expected_feature == "runtime_failure" and actual_feature == expected_feature):
        return "P2"
    return "EXCLUDE"


def _filtered_related_events(
    context: Mapping[str, Any],
    common: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    raw_events = context.get("related_events")
    raw_events = raw_events if isinstance(raw_events, list) else []
    accepted: list[dict[str, Any]] = []
    excluded = 0
    for event in raw_events:
        if not isinstance(event, Mapping):
            continue
        relation = _event_relation(event, common)
        if relation == "EXCLUDE":
            excluded += 1
            continue
        accepted.append({**redact(dict(event)), "relation_priority": relation})
    return accepted, excluded


def _parse_log_line(line: str) -> dict[str, Any]:
    parts = [part.strip() for part in str(line).split(" | ")]
    fields: dict[str, str] = {}
    for part in parts[2:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key.strip()] = value.strip()
    return {
        "raw": str(line).rstrip("\r\n"),
        "timestamp": parts[0] if parts else "",
        "level": parts[1].upper() if len(parts) > 1 else "",
        "fields": fields,
    }


def _log_candidates(log_path: Path | None) -> list[Path]:
    if not log_path:
        return []
    path = Path(log_path)
    candidates = [Path(f"{path}.{index}") for index in range(3, 0, -1)] + [path]
    return [candidate for candidate in candidates if candidate.is_file()]


def _event_signature(event: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        _event_value(event, "timestamp"),
        _event_value(event, "event"),
        _event_value(event, "stage"),
        _event_value(event, "runtime_id"),
    )


def _safe_log_line(parsed: Mapping[str, Any]) -> str:
    fields = parsed.get("fields") if isinstance(parsed.get("fields"), Mapping) else {}
    safe_fields = [
        f"{key}={_redact_string(str(value), field=str(key))}"
        for key, value in fields.items()
    ]
    prefix = [
        _redact_string(str(parsed.get("timestamp") or ""), field="timestamp"),
        _redact_string(str(parsed.get("level") or ""), field="level"),
    ]
    return " | ".join(prefix + safe_fields)


def _select_related_log(
    log_path: Path | None,
    common: Mapping[str, Any],
    related_events: list[dict[str, Any]],
) -> tuple[bytes, str, dict[str, int], list[dict[str, Any]]]:
    event_signatures = {_event_signature(event) for event in related_events}
    selected: list[tuple[dict[str, Any], str]] = []
    source_line_count = 0
    for candidate in _log_candidates(log_path):
        try:
            lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        source_line_count += len(lines)
        for line in lines:
            parsed = _parse_log_line(line)
            fields = parsed["fields"]
            relation = _event_relation(fields, common)
            if relation == "EXCLUDE":
                continue
            if relation == "P2":
                signature = (
                    parsed["timestamp"],
                    str(fields.get("event") or ""),
                    str(fields.get("stage") or ""),
                    str(fields.get("runtime_id") or ""),
                )
                if signature not in event_signatures:
                    continue
            event_name = str(fields.get("event") or "").upper()
            if parsed["level"] == "INFO" and not any(marker in event_name for marker in CRITICAL_INFO_MARKERS):
                continue
            selected.append((parsed, relation))

    if len(selected) > 120:
        selected = selected[-120:]
    p1_count = sum(1 for _, relation in selected if relation == "P1")
    p2_count = sum(1 for _, relation in selected if relation == "P2")
    status = "PASS" if p1_count else ("PARTIAL" if p2_count else "NOT_FOUND")
    header = [
        f"RELATED_LOG_STATUS={status}",
        f"P1_MATCH_COUNT={p1_count}",
        f"P2_MATCH_COUNT={p2_count}",
        "TIME_WINDOW_USED=NO",
    ]
    if status == "NOT_FOUND":
        header.append("DETAIL=No safely isolated runtime log evidence was found.")
    body = [_safe_log_line(parsed) for parsed, _ in selected]
    text = "\n".join(header + ([""] + body if body else [])) + "\n"
    selected_events = [
        {
            "timestamp": parsed.get("timestamp") or "",
            **dict(parsed.get("fields") or {}),
            "relation_priority": relation,
        }
        for parsed, relation in selected
    ]
    return text.encode("utf-8"), status, {
        "source_line_count": source_line_count,
        "included_line_count": len(selected),
        "p1_match_count": p1_count,
        "p2_match_count": p2_count,
    }, selected_events


def _timeline_record(event: Mapping[str, Any]) -> dict[str, Any] | None:
    timestamp = str(event.get("timestamp") or event.get("recorded_at") or event.get("created_at") or "").strip()
    event_type = str(event.get("event") or event.get("event_type") or "").strip()
    if not timestamp or not event_type:
        return None
    summary = (
        event.get("summary")
        or event.get("reason")
        or event.get("impact")
        or event.get("message")
        or event.get("result")
        or ""
    )
    return redact({
        "timestamp": timestamp,
        "event_type": event_type,
        "feature_key": _event_value(event, "feature_key") or None,
        "trace_id": event.get("trace_id") or None,
        "task_id": event.get("task_id") or None,
        "result_id": event.get("result_id") or None,
        "delivery_id": event.get("delivery_id") or None,
        "stage": event.get("stage") or None,
        "status": event.get("status") or event.get("result") or None,
        "error_id": event.get("error_id") or None,
        "summary": summary or None,
    })


def _timeline_sort_key(event: Mapping[str, Any]) -> tuple[int, str]:
    timestamp = str(event.get("timestamp") or "")
    try:
        normalized = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).isoformat()
        return (0, normalized)
    except ValueError:
        return (1, timestamp)


def _build_timeline(
    task: Mapping[str, Any],
    context: Mapping[str, Any],
    common: Mapping[str, Any],
    related_events: list[dict[str, Any]],
    log_events: list[dict[str, Any]],
    *,
    generated_at: str,
) -> tuple[dict[str, Any], str]:
    events: list[dict[str, Any]] = []
    business_event_count = 0
    for event in [*related_events, *log_events]:
        record = _timeline_record(event)
        if record:
            events.append(record)
            business_event_count += 1

    for item in list(task.get("lifecycle") or []) + list(task.get("stage_events") or []):
        if not isinstance(item, Mapping):
            continue
        candidate = {
            **item,
            "event": item.get("event") or "TASK_STATUS_CHANGED",
            "feature_key": item.get("feature_key") or common.get("feature_key"),
            "operation_id": item.get("operation_id") or task.get("operation_id"),
            "trace_id": item.get("trace_id") or task.get("trace_id"),
            "task_id": item.get("task_id") or task.get("task_id"),
        }
        if _event_relation(candidate, common) == "EXCLUDE":
            continue
        record = _timeline_record(candidate)
        if record:
            events.append(record)
            business_event_count += 1

    feedback_base = {
        "feature_key": common.get("feature_key"),
        "trace_id": common.get("trace_id"),
        "task_id": common.get("task_id"),
        "result_id": common.get("result_id"),
        "delivery_id": common.get("delivery_id"),
        "stage": "user_feedback",
        "status": "completed",
    }
    captured_at = str(context.get("context_captured_at") or "").strip()
    if captured_at:
        opened = _timeline_record({
            **feedback_base,
            "timestamp": captured_at,
            "event": "FEEDBACK_OPENED",
            "summary": "Feedback context snapshot captured.",
        })
        if opened:
            events.append(opened)
    generated = _timeline_record({
        **feedback_base,
        "timestamp": generated_at,
        "event": "FEEDBACK_GENERATED",
        "summary": "V3 feedback payload generated.",
    })
    if generated:
        events.append(generated)

    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for event in events:
        key = (
            event.get("timestamp"),
            event.get("event_type"),
            event.get("trace_id"),
            event.get("task_id"),
            event.get("stage"),
        )
        unique[key] = event
    ordered = sorted(unique.values(), key=_timeline_sort_key)
    business_event_names = [
        str(event.get("event_type") or "")
        for event in ordered
        if str(event.get("event_type") or "") not in {"FEEDBACK_OPENED", "FEEDBACK_GENERATED"}
    ]
    required_events: list[str] = []
    if common.get("task_id"):
        required_events.extend(("PROCESS_STARTED", "PROCESS_SUCCEEDED"))
    if common.get("result_id"):
        required_events.append("RESULT_REGISTERED")
    if common.get("delivery_id"):
        required_events.extend(("DELIVERY_CREATED", "DELIVERY_STARTED", "DELIVERY_SUCCEEDED"))
    if "DELIVERY_FAILED" in business_event_names:
        required_events.extend(("DELIVERY_FAILED", "DELIVERY_RETRY_STARTED"))
    required_events.extend(("FEEDBACK_OPENED", "FEEDBACK_GENERATED"))
    missing_required_events = [name for name in dict.fromkeys(required_events) if name not in [
        str(event.get("event_type") or "") for event in ordered
    ]]
    retry_order_complete = True
    if "DELIVERY_FAILED" in business_event_names:
        failed_index = max(index for index, name in enumerate(business_event_names) if name == "DELIVERY_FAILED")
        retry_indices = [
            index for index, name in enumerate(business_event_names)
            if name == "DELIVERY_RETRY_STARTED" and index > failed_index
        ]
        success_indices = [
            index for index, name in enumerate(business_event_names)
            if name == "DELIVERY_SUCCEEDED" and index > failed_index
        ]
        retry_order_complete = bool(retry_indices and success_indices and min(retry_indices) < max(success_indices))
    timeline_present = bool(business_event_names)
    timeline_complete = bool(required_events) and not missing_required_events and retry_order_complete
    status = "PASS" if timeline_complete else ("PARTIAL" if timeline_present or ordered else "NOT_AVAILABLE")
    return {
        "timeline_status": status,
        "timeline_present": timeline_present,
        "timeline_complete": timeline_complete,
        "required_events": list(dict.fromkeys(required_events)),
        "missing_required_events": missing_required_events,
        "retry_order_complete": retry_order_complete,
        "event_count": len(ordered),
        "events": ordered,
    }, status


def _privacy_review(
    payloads: Mapping[str, bytes],
    *,
    selected_events: list[dict[str, Any]],
    common: Mapping[str, Any],
    attachments: list[dict[str, Any]],
    image_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    combined = "\n".join(payload.decode("utf-8", errors="replace") for payload in payloads.values())
    contains_absolute_paths = bool(ABSOLUTE_PATH_PATTERN.search(combined))
    contains_sensitive_credentials = any(pattern.search(combined) for pattern in SECRET_PATTERNS)
    contains_other_tasks = any(_event_relation(event, common) == "EXCLUDE" for event in selected_events)
    source_included = bool(
        isinstance(image_evidence.get("source_image"), Mapping)
        and image_evidence["source_image"].get("included")
    )
    result_included = bool(
        isinstance(image_evidence.get("result_image"), Mapping)
        and image_evidence["result_image"].get("included")
    )
    consent_enforced = all(
        not isinstance(item, Mapping)
        or not item.get("included")
        or item.get("requested_by_user") is True
        for item in (image_evidence.get("source_image"), image_evidence.get("result_image"))
    )
    summary = {
        "redacted": True,
        "contains_original_image": source_included,
        "contains_output_image": result_included,
        "contains_screenshot": False,
        "contains_absolute_paths": contains_absolute_paths,
        "contains_other_tasks": contains_other_tasks,
        "contains_sensitive_credentials": contains_sensitive_credentials,
        "selected_attachments": attachments,
        "attachments_included": False,
        "image_evidence_included": source_included or result_included,
        "image_consent_enforced": consent_enforced,
        "auto_upload": False,
    }
    summary["review_status"] = "PASS" if not any((
        summary["contains_screenshot"],
        summary["contains_absolute_paths"],
        summary["contains_other_tasks"],
        summary["contains_sensitive_credentials"],
        not consent_enforced,
    )) else "FAIL"
    return summary


def _safe_attachments(value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for item in list(value or [])[:10]:
        if not isinstance(item, Mapping):
            continue
        try:
            size_bytes = max(0, int(item.get("size_bytes") or 0))
        except (TypeError, ValueError):
            size_bytes = 0
        attachments.append({
            "extension": str(item.get("extension") or "")[:16].lower(),
            "size_bytes": size_bytes,
            "selected_by_user": bool(item.get("selected_by_user")),
            "included_in_bundle": False,
        })
    return attachments


def normalize_feedback_evaluation(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value in (None, {}):
        return {"decision": None, "reasons": []}
    if not isinstance(value, Mapping) or set(value) - {"decision", "reasons"}:
        raise ValueError("FEEDBACK_EVALUATION_INVALID")
    decision = str(value.get("decision") or "").strip().upper()
    if not decision and value.get("reasons") in (None, []):
        return {"decision": None, "reasons": []}
    if decision not in EVALUATION_DECISIONS:
        raise ValueError("FEEDBACK_EVALUATION_DECISION_INVALID")
    raw_reasons = value.get("reasons") or []
    if not isinstance(raw_reasons, list) or len(raw_reasons) > 3:
        raise ValueError("FEEDBACK_EVALUATION_REASONS_INVALID")
    reasons = []
    for item in raw_reasons:
        reason = str(item or "").strip().upper()
        if reason not in EVALUATION_REASONS:
            raise ValueError("FEEDBACK_EVALUATION_REASON_INVALID")
        if reason not in reasons:
            reasons.append(reason)
    if decision == "ACCEPTED" and reasons:
        raise ValueError("FEEDBACK_EVALUATION_REASON_NOT_APPLICABLE")
    if decision in {"NEEDS_ADJUSTMENT", "UNUSABLE"} and not reasons:
        raise ValueError("FEEDBACK_EVALUATION_REASON_REQUIRED")
    return {"decision": decision, "reasons": reasons}


def normalize_evidence_consent(value: Mapping[str, Any] | None) -> dict[str, bool]:
    if value in (None, {}):
        return {"include_source_image": False, "include_result_image": False}
    if not isinstance(value, Mapping) or set(value) - {"include_source_image", "include_result_image"}:
        raise ValueError("FEEDBACK_EVIDENCE_CONSENT_INVALID")
    return {
        "include_source_image": value.get("include_source_image") is True,
        "include_result_image": value.get("include_result_image") is True,
    }


def _image_evidence(
    task: Mapping[str, Any],
    consent: Mapping[str, bool],
    allowed_root: Path | None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    task_result = _as_mapping(task.get("task_result"))
    result = _as_mapping(task.get("result"))
    source_metadata = _as_mapping(task.get("source_metadata"))
    source_width, source_height = _evidence_dimensions(result.get("source_dimensions"))
    result_width, result_height = _evidence_dimensions(result.get("output_dimensions"))
    task_id = str(task.get("task_id") or task_result.get("task_id") or result.get("task_id") or "")
    result_id = str(task.get("result_id") or task_result.get("result_id") or "")
    trace_id = str(task.get("trace_id") or task_result.get("trace_id") or "")
    is_compression = str(task.get("feature_key") or task.get("task_family") or "") == "image_compression"
    candidates = {
        "source_image": {
            "requested": consent.get("include_source_image") is True,
            "path": task.get("source_path") or task.get("input_path") or task_result.get("source_path") or task_result.get("input_path"),
            "stem": "source",
            "format": result.get("source_format") or source_metadata.get("format"),
            "width": source_width or source_metadata.get("width"),
            "height": source_height or source_metadata.get("height"),
            "registered_size_bytes": _registered_size(result.get("source_size_bytes"))
            if result.get("source_size_bytes") is not None else _registered_size(source_metadata.get("size_bytes")),
            "registered_sha256": str(result.get("source_sha256") or task_result.get("source_sha256") or source_metadata.get("sha256") or "").lower() or None,
            "file_name": _file_name(task.get("original_filename") or source_metadata.get("filename") or result.get("source_path") or task.get("source_path")),
            "missing_code": "SOURCE_NOT_FOUND",
        },
        "result_image": {
            "requested": consent.get("include_result_image") is True,
            "path": task_result.get("output_path") or task_result.get("result_file") or task_result.get("final_output_path")
            or result.get("output_path") or result.get("result_file") or result.get("final_output_path")
            or task.get("output_path") or task.get("result_file") or task.get("expected_output_path"),
            "stem": "result",
            "format": result.get("output_format"),
            "width": result_width,
            "height": result_height,
            "registered_size_bytes": _registered_size(result.get("output_size_bytes")),
            "registered_sha256": str(result.get("output_sha256") or task_result.get("output_sha256") or task.get("output_sha256") or "").lower() or None,
            "file_name": _file_name(result.get("output_path") or task_result.get("output_path") or task.get("output_path")),
            "missing_code": "RESULT_NOT_FOUND",
        },
    }
    records: dict[str, Any] = {}
    payloads: dict[str, bytes] = {}
    root = None
    if allowed_root is not None:
        try:
            root = Path(allowed_root).resolve()
        except OSError:
            root = None
    for key, candidate in candidates.items():
        requested = candidate["requested"]
        raw_path = candidate["path"]
        stem = candidate["stem"]
        expected_size = candidate["registered_size_bytes"]
        expected_sha256 = candidate["registered_sha256"]
        raw_suffix = Path(str(raw_path)).suffix.lower() if raw_path else ""
        record = {
            "requested_by_user": requested,
            "included": False,
            "status": "NOT_AUTHORIZED" if not requested else "CONTEXT_UNAVAILABLE",
            "failure_code": None,
            "archive_path": None,
            "file_name": candidate["file_name"],
            "format": str(candidate["format"] or "").upper() or None,
            "width": candidate["width"] if isinstance(candidate["width"], int) else None,
            "height": candidate["height"] if isinstance(candidate["height"], int) else None,
            "extension": raw_suffix or None,
            "size_bytes": 0,
            "sha256": None,
            "registered_size_bytes": expected_size,
            "registered_sha256": expected_sha256,
            "task_id": task_id or None,
            "result_id": result_id or None,
            "trace_id": trace_id or None,
        }
        if not requested:
            records[key] = record
            continue
        if is_compression and not task_id:
            record["failure_code"] = "TASK_BINDING_MISSING"
            records[key] = record
            continue
        if is_compression and key == "result_image" and not result_id:
            record["failure_code"] = "RESULT_BINDING_MISSING"
            records[key] = record
            continue
        if not raw_path:
            record.update(status="FILE_NOT_FOUND", failure_code=candidate["missing_code"])
            records[key] = record
            continue
        if root is None:
            record.update(status="PATH_NOT_ALLOWED", failure_code="PATH_NOT_ALLOWED")
            records[key] = record
            continue
        try:
            path = Path(str(raw_path)).resolve()
            if path != root and root not in path.parents:
                record.update(status="PATH_NOT_ALLOWED", failure_code="PATH_NOT_ALLOWED")
                records[key] = record
                continue
            if not path.is_file():
                record.update(status="FILE_NOT_FOUND", failure_code=candidate["missing_code"])
                records[key] = record
                continue
            suffix = path.suffix.lower()
            if suffix not in IMAGE_EVIDENCE_EXTENSIONS:
                record.update(status="UNSUPPORTED_IMAGE", failure_code="FILE_READ_FAILED")
                records[key] = record
                continue
            payload = path.read_bytes()
            actual_sha256 = _sha256_bytes(payload)
            if (expected_sha256 and actual_sha256 != expected_sha256) or (
                expected_size is not None and len(payload) != expected_size
            ):
                record.update(
                    status="FILE_CHANGED",
                    failure_code="FILE_CHANGED",
                    extension=suffix,
                    size_bytes=len(payload),
                    sha256=actual_sha256,
                )
                records[key] = record
                continue
            with Image.open(io.BytesIO(payload)) as image:
                image.verify()
            archive_path = f"evidence/{stem}{suffix}"
            payloads[archive_path] = payload
            record.update(
                included=True,
                status="INCLUDED",
                archive_path=archive_path,
                extension=suffix,
                size_bytes=len(payload),
                sha256=actual_sha256,
            )
        except FileNotFoundError:
            record.update(status="FILE_NOT_FOUND", failure_code=candidate["missing_code"])
        except (OSError, ValueError):
            record.update(status="FILE_READ_FAILED", failure_code="FILE_READ_FAILED")
        except Exception:
            record.update(status="FILE_READ_FAILED", failure_code="FILE_READ_FAILED")
        records[key] = record
    requested_records = [item for item in records.values() if item["requested_by_user"]]
    overall_status = (
        "NOT_REQUESTED"
        if not requested_records
        else "PASS"
        if all(item["included"] for item in requested_records)
        else "PARTIAL"
    )
    return {
        "status": overall_status,
        "failure_code": "EVIDENCE_ATTACHMENT_FAILED" if overall_status == "PARTIAL" else None,
        **records,
    }, payloads


def _manifest(
    *,
    bundle_id: str,
    generated_at: str,
    common: Mapping[str, Any],
    module_context: Mapping[str, Any],
    payloads: Mapping[str, bytes],
    related_log_status: str,
    timeline_status: str,
    privacy: Mapping[str, Any],
    image_evidence: Mapping[str, Any],
    evidence_payloads: Mapping[str, bytes],
) -> dict[str, Any]:
    return {
        "package_schema_version": FEEDBACK_SCHEMA_VERSION,
        "feedback_bundle_id": bundle_id,
        "generated_at": generated_at,
        "trace_id": common.get("trace_id"),
        "feature_key": common.get("feature_key"),
        "context_binding": {
            "task_id": common.get("task_id"),
            "result_id": common.get("result_id"),
            "trace_id": common.get("trace_id"),
            "operation_id": common.get("operation_id"),
            "module_context": dict(module_context),
        },
        "payload_files": {
            name: {"size_bytes": len(payloads[name]), "sha256": _sha256_bytes(payloads[name])}
            for name in PAYLOAD_ENTRIES
        },
        "evidence_files": {
            name: {"size_bytes": len(payload), "sha256": _sha256_bytes(payload)}
            for name, payload in evidence_payloads.items()
        },
        "image_evidence": image_evidence,
        "completeness": {
            "feedback_json": "PASS",
            "related_log": related_log_status,
            "timeline": timeline_status,
        },
        "privacy": {
            key: privacy[key]
            for key in (
                "redacted",
                "contains_original_image",
                "contains_output_image",
                "contains_screenshot",
                "contains_absolute_paths",
                "contains_other_tasks",
                "contains_sensitive_credentials",
            )
        },
        "package_validation_status": "PASS",
    }


def _write_candidate_zip(
    path: Path,
    payloads: Mapping[str, bytes],
    manifest: Mapping[str, Any],
    evidence_payloads: Mapping[str, bytes],
) -> None:
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in PAYLOAD_ENTRIES:
            archive.writestr(name, payloads[name])
        for name, payload in evidence_payloads.items():
            archive.writestr(name, payload)
        archive.writestr("manifest.json", _json_bytes(manifest))


def _validate_zip_payload(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        feedback = json.loads(archive.read("feedback.json").decode("utf-8"))
        related_log = archive.read("related.log").decode("utf-8")
        timeline = json.loads(archive.read("timeline.json").decode("utf-8"))
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        evidence_files = manifest.get("evidence_files") or {}
        if not isinstance(evidence_files, Mapping):
            raise ValueError("FEEDBACK_MANIFEST_EVIDENCE_INVALID")
        image_evidence = manifest.get("image_evidence") or {}
        if not isinstance(image_evidence, Mapping):
            raise ValueError("FEEDBACK_MANIFEST_EVIDENCE_INVALID")
        evidence_records = [
            image_evidence.get("source_image"),
            image_evidence.get("result_image"),
        ]
        declared_paths = {
            str(item.get("archive_path"))
            for item in evidence_records
            if isinstance(item, Mapping) and item.get("included") is True
        }
        if declared_paths != set(evidence_files):
            raise ValueError("FEEDBACK_MANIFEST_EVIDENCE_MISMATCH")
        if any(
            isinstance(item, Mapping)
            and item.get("included") is True
            and item.get("requested_by_user") is not True
            for item in evidence_records
        ):
            raise ValueError("FEEDBACK_EVIDENCE_CONSENT_INVALID")
        expected_names = [*PAYLOAD_ENTRIES, *evidence_files.keys(), "manifest.json"]
        if names != expected_names:
            raise ValueError("FEEDBACK_ZIP_STRUCTURE_INVALID")
        if manifest.get("package_schema_version") != FEEDBACK_SCHEMA_VERSION:
            raise ValueError("FEEDBACK_MANIFEST_SCHEMA_INVALID")
        payload_files = manifest.get("payload_files")
        if not isinstance(payload_files, Mapping) or set(payload_files) != set(PAYLOAD_ENTRIES):
            raise ValueError("FEEDBACK_MANIFEST_PAYLOAD_INVALID")
        for name in PAYLOAD_ENTRIES:
            payload = archive.read(name)
            entry = payload_files[name]
            if int(entry.get("size_bytes") or -1) != len(payload):
                raise ValueError(f"FEEDBACK_PAYLOAD_SIZE_INVALID:{name}")
            if str(entry.get("sha256") or "") != _sha256_bytes(payload):
                raise ValueError(f"FEEDBACK_PAYLOAD_SHA_INVALID:{name}")
        for name, entry in evidence_files.items():
            if not re.fullmatch(r"evidence/(?:source|result)\.[a-z0-9]{1,5}", str(name)):
                raise ValueError("FEEDBACK_EVIDENCE_NAME_INVALID")
            payload = archive.read(name)
            if int(entry.get("size_bytes") or -1) != len(payload):
                raise ValueError(f"FEEDBACK_EVIDENCE_SIZE_INVALID:{name}")
            if str(entry.get("sha256") or "") != _sha256_bytes(payload):
                raise ValueError(f"FEEDBACK_EVIDENCE_SHA_INVALID:{name}")
        if not related_log.startswith("RELATED_LOG_STATUS="):
            raise ValueError("FEEDBACK_RELATED_LOG_INVALID")
        if not isinstance(feedback, Mapping) or not isinstance(timeline, Mapping):
            raise ValueError("FEEDBACK_JSON_PAYLOAD_INVALID")
    return {
        "zip_structure": "PASS",
        "manifest_sha": "PASS",
        "zip_validation": "PASS",
    }


def validate_feedback_bundle(path: Path) -> dict[str, Any]:
    """Revalidate a promoted V3 package before it is exposed for download."""

    return _validate_zip_payload(Path(path))


def _failure_result(exc: BaseException) -> dict[str, Any]:
    return {
        "feedback_bundle_status": "FAIL",
        "feedback_bundle_path": "",
        "feedback_bundle_name": "",
        "feedback_bundle_size": 0,
        "feedback_bundle_redacted": True,
        "feedback_bundle_error": _redact_string(str(exc) or exc.__class__.__name__),
        "feedback_schema_version": FEEDBACK_SCHEMA_VERSION,
    }


def generate_feedback_bundle(
    task_id: str,
    task: dict[str, Any] | None,
    output_dir: Path | None = None,
    *,
    context_snapshot: dict[str, Any] | None = None,
    attachment_manifest: list[dict[str, Any]] | None = None,
    feedback_bundle_id: str = "",
    runtime_log_path: Path | None = None,
    evaluation: Mapping[str, Any] | None = None,
    evidence_consent: Mapping[str, Any] | None = None,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    target_dir = Path(output_dir) if output_dir else DEFAULT_FEEDBACK_DIR
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return _failure_result(exc)

    task = dict(task or {})
    task_result = task.get("task_result") if isinstance(task.get("task_result"), Mapping) else {}
    generated_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
    bundle_id = feedback_bundle_id or f"FB-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:12].upper()}"
    bundle_name = f"影界HDDE_问题反馈_{bundle_id}.zip"
    bundle_path = target_dir / bundle_name
    temporary_path = target_dir / f".{bundle_name}.{uuid.uuid4().hex}.tmp"
    context = redact(context_snapshot) if isinstance(context_snapshot, Mapping) else build_feedback_context(
        task,
        source_feature=str(task.get("source_feature") or "") or None,
        runtime=task.get("runtime_context") if isinstance(task.get("runtime_context"), Mapping) else None,
        user_description=str(task.get("user_description") or ""),
    )
    common = _normalized_common_context(context)
    module_context = _normalized_module_context(context)
    related_events, excluded_event_count = _filtered_related_events(context, common)
    related_log_bytes, related_log_status, log_stats, log_events = _select_related_log(
        runtime_log_path,
        common,
        related_events,
    )
    timeline, timeline_status = _build_timeline(
        task,
        context,
        common,
        related_events,
        log_events,
        generated_at=generated_at,
    )
    timeline_bytes = _json_bytes(timeline)
    attachments = _safe_attachments(attachment_manifest)
    try:
        normalized_evaluation = normalize_feedback_evaluation(evaluation)
        normalized_consent = normalize_evidence_consent(evidence_consent)
    except ValueError as exc:
        return _failure_result(exc)
    image_evidence, evidence_payloads = _image_evidence(task, normalized_consent, evidence_root)
    output_path = (
        task_result.get("output_path")
        or task_result.get("result_file")
        or task.get("output_path")
        or task.get("result_file")
        or task.get("expected_output_path")
    )
    output_validation = _output_validation(output_path)
    runtime = context.get("runtime") if isinstance(context.get("runtime"), Mapping) else {}
    package_completeness = {
        "trace_context": _link_status(context, "trace"),
        "task_context": _link_status(context, "task"),
        "result_context": _link_status(context, "result"),
        "delivery_context": _link_status(context, "delivery"),
        "related_log": related_log_status,
        "timeline": timeline_status,
        "image_evidence": (
            "NOT_APPLICABLE"
            if image_evidence["status"] == "NOT_REQUESTED"
            else "PASS"
            if image_evidence["status"] == "PASS"
            else "PARTIAL"
        ),
    }
    feedback = {
        "feedback_identity": {
            "schema_version": FEEDBACK_SCHEMA_VERSION,
            "feedback_bundle_id": bundle_id,
            "generated_at": generated_at,
            "context_captured_at": context.get("context_captured_at") or None,
        },
        "application_runtime": {
            "product": "影界 HDDE",
            "product_version": runtime.get("product_version") or runtime.get("app_version") or "unavailable",
            "build_id": common.get("build_id") or runtime.get("build_id") or "unavailable",
            "runtime_id": common.get("runtime_id") or runtime.get("runtime_id") or "unavailable",
            "runtime_status": runtime.get("runtime_status") or "unavailable",
            "backend_health": runtime.get("backend_health") or "unavailable",
            "settings_status": runtime.get("settings_status") or "unavailable",
            "formal_root_status": runtime.get("formal_root_status") or "unavailable",
        },
        "user_description": _redact_string(str(context.get("user_description") or task.get("user_description") or "")),
        "evaluation": normalized_evaluation,
        "common_context": common,
        "module_context": module_context,
        "safe_input_metadata": redact(context.get("safe_input_metadata") or {}),
        "output_validation": output_validation,
        "package_completeness": package_completeness,
        "image_evidence": image_evidence,
        "privacy_summary": {
            "redacted": True,
            "contains_original_image": image_evidence["source_image"]["included"],
            "contains_output_image": image_evidence["result_image"]["included"],
            "contains_screenshot": False,
            "contains_absolute_paths": False,
            "contains_other_tasks": False,
            "contains_sensitive_credentials": False,
            "selected_attachments": attachments,
            "attachments_included": False,
            "auto_upload": False,
        },
    }
    feedback_bytes = _json_bytes(feedback)
    preliminary_payloads = {
        "feedback.json": feedback_bytes,
        "related.log": related_log_bytes,
        "timeline.json": timeline_bytes,
    }
    privacy = _privacy_review(
        preliminary_payloads,
        selected_events=[*related_events, *log_events],
        common=common,
        attachments=attachments,
        image_evidence=image_evidence,
    )
    if privacy["review_status"] != "PASS":
        return _failure_result(RuntimeError("FEEDBACK_PRIVACY_REVIEW_FAILED"))
    feedback["privacy_summary"] = privacy
    feedback_bytes = _json_bytes(feedback)
    payloads = {
        "feedback.json": feedback_bytes,
        "related.log": related_log_bytes,
        "timeline.json": timeline_bytes,
    }
    manifest = _manifest(
        bundle_id=bundle_id,
        generated_at=generated_at,
        common=common,
        module_context=module_context,
        payloads=payloads,
        related_log_status=related_log_status,
        timeline_status=timeline_status,
        privacy=privacy,
        image_evidence=image_evidence,
        evidence_payloads=evidence_payloads,
    )

    try:
        if bundle_path.exists():
            raise FileExistsError("FEEDBACK_BUNDLE_ALREADY_EXISTS")
        _write_candidate_zip(temporary_path, payloads, manifest, evidence_payloads)
        validation = _validate_zip_payload(temporary_path)
        os.link(temporary_path, bundle_path)
        try:
            temporary_path.unlink()
        except OSError:
            pass
    except Exception as exc:
        for path in (temporary_path,):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return _failure_result(exc)

    self_check = {
        "TRACE_CONTEXT": package_completeness["trace_context"],
        "TASK_CONTEXT": package_completeness["task_context"],
        "RESULT_CONTEXT": package_completeness["result_context"],
        "DELIVERY_CONTEXT": package_completeness["delivery_context"],
        "RELATED_LOG": related_log_status,
        "TIMELINE": timeline_status,
        "PRIVACY_REVIEW": privacy["review_status"],
        "MANIFEST_SHA": validation["manifest_sha"],
        "ZIP_VALIDATION": validation["zip_validation"],
        "IMAGE_EVIDENCE": image_evidence["status"],
    }
    return {
        "feedback_bundle_status": "PASS",
        "feedback_bundle_path": str(bundle_path),
        "feedback_bundle_name": bundle_name,
        "feedback_bundle_size": bundle_path.stat().st_size,
        "feedback_bundle_redacted": True,
        "feedback_bundle_error": "",
        "feedback_bundle_id": bundle_id,
        "feedback_schema_version": FEEDBACK_SCHEMA_VERSION,
        "generated_at": generated_at,
        "context_captured_at": context.get("context_captured_at") or "unavailable",
        "context_preview": feedback_context_preview(context),
        "bundle_payload": redact(feedback),
        "package_self_check": self_check,
        "log_isolation": {
            **log_stats,
            "excluded_related_event_count": excluded_event_count,
            "status": "PASS",
        },
        "atomic_package_write": "PASS",
    }
