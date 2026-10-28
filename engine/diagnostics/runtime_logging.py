from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
import threading
import traceback
import uuid
from collections import deque
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Mapping


LOGGER_NAME = "hdde.runtime"
LOG_RELATIVE_PATH = Path("诊断") / "日志" / "hdde.log"
MAX_LOG_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3
RUNTIME_ROOT_OVERRIDE_ENV = "HDDE_RUNTIME_ROOT_OVERRIDE"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

PRODUCT_ERROR = "PRODUCT_ERROR"
ENVIRONMENT_ERROR = "ENVIRONMENT_ERROR"
CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
USER_ACTION_REQUIRED = "USER_ACTION_REQUIRED"
ERROR_CATEGORIES = {
    PRODUCT_ERROR,
    ENVIRONMENT_ERROR,
    CONFIGURATION_ERROR,
    USER_ACTION_REQUIRED,
}

_HANDLER_MARKER = "_hdde_runtime_handler"
_CONSOLE_KIND = "console"
_FILE_KIND = "file"
_LOCK = threading.RLock()
_RECENT_EVENTS: deque[dict[str, Any]] = deque(maxlen=256)
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|token|cookie|authorization|password|secret)\s*[:=]\s*[^\s,;|]+"
)
_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\)[^,;|\r\n]+")
_POSIX_ABSOLUTE_PATH = re.compile(r"(?<![\w:])/(?:[^,;|\r\n]+)")
_BUSINESS_FILENAME_PATTERN = re.compile(
    r"(?iu)(?<![\w./\\-])[^\s,;|]+\.(png|jpe?g|webp|tiff?|bmp|gif)(?![\w])"
)


def _new_runtime_id() -> str:
    timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    return f"RUN-{timestamp}-{uuid.uuid4().hex[:10].upper()}"


_RUNTIME_ID = _new_runtime_id()
_PRODUCT_VERSION = ""
_BUILD_ID = ""


class _RuntimeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        return f"{timestamp} | {record.levelname} | {record.getMessage()}"


def _runtime_handlers(logger: logging.Logger, kind: str | None = None) -> list[logging.Handler]:
    handlers = [handler for handler in logger.handlers if getattr(handler, _HANDLER_MARKER, None)]
    if kind is None:
        return handlers
    return [handler for handler in handlers if getattr(handler, _HANDLER_MARKER, None) == kind]


def initialize_console_logging() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    with _LOCK:
        if not _runtime_handlers(logger, _CONSOLE_KIND):
            handler = logging.StreamHandler(sys.stderr)
            setattr(handler, _HANDLER_MARKER, _CONSOLE_KIND)
            handler.setFormatter(_RuntimeFormatter())
            logger.addHandler(handler)
    return logger


def _safe_value(value: Any, *, field: str = "") -> str:
    if isinstance(value, Path):
        text = str(value)
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif value is None:
        text = ""
    else:
        text = str(value)
    text = " ".join(text.replace("|", "/").splitlines()).strip()
    text = _SECRET_PATTERN.sub(r"\1=<redacted>", text)
    if field == "path" and (
        _WINDOWS_ABSOLUTE_PATH.match(text) or _POSIX_ABSOLUTE_PATH.match(text)
    ):
        normalized = text.replace("\\", "/")
        filename = normalized.rstrip("/").rsplit("/", 1)[-1]
        if filename.lower() == "hdde.log":
            return "诊断/日志/hdde.log"
        suffix = Path(filename).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}:
            reference = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]
            return f"file_{reference}{suffix}"
        return f"<redacted_path>{suffix}" if suffix else "<redacted_path>"
    if field not in {"route", "route_family"}:
        text = _WINDOWS_ABSOLUTE_PATH.sub("<redacted_path>", text)
        text = _POSIX_ABSOLUTE_PATH.sub("<redacted_path>", text)
    if field not in {"code_location", "runtime_log_reference"}:
        text = _BUSINESS_FILENAME_PATTERN.sub(lambda match: f"<redacted_file>.{match.group(1).lower()}", text)
    return text


def sanitize_diagnostic_value(value: Any, *, field: str = "") -> str:
    """Shared privacy boundary for logs, exception summaries and feedback context."""

    return _safe_value(value, field=field)


def begin_runtime(*, product_version: str = "", build_id: str = "") -> str:
    """Establish one runtime identity before any event for a new app instance."""

    global _RUNTIME_ID, _PRODUCT_VERSION, _BUILD_ID
    with _LOCK:
        _RUNTIME_ID = _new_runtime_id()
        _PRODUCT_VERSION = str(product_version or "").strip()
        _BUILD_ID = str(build_id or "").strip()
        _RECENT_EVENTS.clear()
        return _RUNTIME_ID


def configure_runtime_identity(*, product_version: str = "", build_id: str = "") -> dict[str, str]:
    global _PRODUCT_VERSION, _BUILD_ID
    with _LOCK:
        if product_version:
            _PRODUCT_VERSION = str(product_version).strip()
        if build_id:
            _BUILD_ID = str(build_id).strip()
        return runtime_identity()


def runtime_identity() -> dict[str, str]:
    return {
        "product_version": _PRODUCT_VERSION,
        "build_id": _BUILD_ID,
        "runtime_id": _RUNTIME_ID,
        "run_kind": "test" if os.environ.get(RUNTIME_ROOT_OVERRIDE_ENV) else "product",
    }


def new_operation_identity(feature_key: str, *, module_id: str = "") -> dict[str, str]:
    """Create the durable identity for one real user-triggered business operation."""

    normalized_feature = str(feature_key or "").strip()
    if not normalized_feature:
        raise ValueError("FEATURE_KEY_REQUIRED")
    timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    return {
        "feature_key": normalized_feature,
        "module_id": str(module_id or f"hdde.{normalized_feature}").strip(),
        "operation_id": f"OP-{timestamp}-{uuid.uuid4().hex[:10].upper()}",
        "trace_id": f"TRACE-{uuid.uuid4().hex[:12].upper()}",
    }


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return chain


def _project_frames(exc: BaseException) -> list[traceback.FrameSummary]:
    frames: list[traceback.FrameSummary] = []
    for candidate in reversed(_exception_chain(exc)):
        frames.extend(traceback.extract_tb(candidate.__traceback__))
    selected: list[traceback.FrameSummary] = []
    for frame in frames:
        try:
            Path(frame.filename).resolve().relative_to(PROJECT_ROOT)
        except (OSError, ValueError):
            continue
        selected.append(frame)
    return selected


def _code_location(exc: BaseException) -> tuple[str, str]:
    frames = _project_frames(exc)
    if not frames:
        module = exc.__class__.__module__ or "runtime"
        return f"{module}::{exc.__class__.__name__}", module
    frame = frames[-1]
    relative = Path(frame.filename).resolve().relative_to(PROJECT_ROOT).as_posix()
    module = Path(relative).with_suffix("").as_posix().replace("/", ".")
    return f"{relative}:{frame.lineno}::{frame.name}", module


def _normalized_reason(value: str) -> str:
    text = _safe_value(value, field="reason").lower()
    text = re.sub(r"\b(?:[0-9a-f]{8,}|\d{4,})\b", "<id>", text)
    text = re.sub(r"\b\d+\b", "<n>", text)
    return text[:300]


def build_exception_diagnostics(
    exc: BaseException,
    *,
    error_category: str,
    error_stage: str,
    trace_id: str = "",
) -> dict[str, str]:
    """Create or reuse the diagnostic identity of one propagated root exception."""

    chain = _exception_chain(exc)
    existing = next(
        (
            candidate
            for candidate in chain
            if getattr(candidate, "hdde_error_id", "")
        ),
        None,
    )
    if existing is not None:
        diagnostics = dict(getattr(existing, "hdde_diagnostics", {}) or {})
        if diagnostics:
            try:
                setattr(exc, "hdde_error_id", diagnostics["error_id"])
                setattr(exc, "hdde_diagnostics", diagnostics)
            except Exception:
                pass
            return diagnostics

    root = chain[-1]
    code_location, module = _code_location(exc)
    exception_type = root.__class__.__name__
    safe_reason = _safe_value(str(root) or exception_type, field="reason")
    fingerprint_basis = "|".join(
        (
            exception_type,
            str(error_category or "UNKNOWN"),
            re.sub(r":\d+::", "::", code_location),
            _normalized_reason(safe_reason),
        )
    )
    diagnostics = {
        "error_id": f"ERR-{datetime.now().astimezone().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}",
        "error_fingerprint": f"EFP-{hashlib.sha256(fingerprint_basis.encode('utf-8')).hexdigest()[:16].upper()}",
        "exception_type": exception_type,
        "code_location": code_location,
        "module": module,
        "trace_id": str(trace_id or f"TRACE-{uuid.uuid4().hex[:12].upper()}").strip(),
        "trace_summary": " <- ".join(
            f"{Path(frame.filename).resolve().relative_to(PROJECT_ROOT).as_posix()}:{frame.lineno}::{frame.name}"
            for frame in _project_frames(exc)[-3:]
        ) or code_location,
        "reason": safe_reason,
        "error_stage": str(error_stage or "unknown"),
        "error_category": str(error_category or "UNKNOWN"),
    }
    for candidate in chain:
        try:
            setattr(candidate, "hdde_error_id", diagnostics["error_id"])
            setattr(candidate, "hdde_diagnostics", diagnostics)
        except Exception:
            pass
    return diagnostics


def log_runtime_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    exception = fields.pop("exception", None)
    if isinstance(exception, BaseException):
        fields.update(
            build_exception_diagnostics(
                exception,
                error_category=str(fields.get("error_category") or PRODUCT_ERROR),
                error_stage=str(fields.get("error_stage") or fields.get("stage") or "unknown"),
                trace_id=str(fields.get("trace_id") or ""),
            )
        )
    identity = runtime_identity()
    fields.setdefault("runtime_id", identity["runtime_id"])
    fields.setdefault("run_kind", identity["run_kind"])
    if level >= logging.ERROR or fields.get("error_id"):
        fields.setdefault("product_version", identity["product_version"])
        fields.setdefault("build_id", identity["build_id"] or "unavailable")
    logger = initialize_console_logging()
    ordered_keys = (
        "stage",
        "result",
        "error_category",
        "product_version",
        "build_id",
        "runtime_id",
        "run_kind",
        "feature_key",
        "feature",
        "module_id",
        "operation",
        "operation_id",
        "task_id",
        "result_id",
        "delivery_id",
        "batch_id",
        "status",
        "error_code",
        "error_stage",
        "error_id",
        "error_fingerprint",
        "exception_type",
        "code_location",
        "module",
        "trace_id",
        "trace_summary",
        "purpose",
        "route",
        "route_family",
        "source_reference",
        "source_extension",
        "source_hash_short",
        "batch_index",
        "format",
        "width",
        "height",
        "color_mode",
        "channels",
        "alpha",
        "orientation",
        "file_size_bucket",
        "duration_ms",
        "total_count",
        "completed_count",
        "failed_count",
        "path",
        "runtime_log_reference",
        "reason",
        "impact",
        "action",
        "directory_ready",
        "file_logging",
    )
    parts = [f"event={_safe_value(event, field='event')}"]
    emitted: set[str] = set()
    for key in ordered_keys:
        if key in fields and fields[key] not in (None, ""):
            parts.append(f"{key}={_safe_value(fields[key], field=key)}")
            emitted.add(key)
    for key in sorted(fields):
        if key not in emitted and fields[key] not in (None, ""):
            parts.append(f"{key}={_safe_value(fields[key], field=key)}")
    message = " | ".join(parts)
    try:
        logger.log(level, message)
        safe_record = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "event": _safe_value(event, field="event"),
        }
        for key, value in fields.items():
            if value not in (None, ""):
                safe_record[key] = _safe_value(value, field=key)
        with _LOCK:
            _RECENT_EVENTS.append(safe_record)
    except Exception:
        # Logging must never change product behavior.
        return


def related_runtime_events(
    *,
    feature_key: str = "",
    operation_id: str = "",
    trace_id: str = "",
    task_id: str = "",
    result_id: str = "",
    delivery_id: str = "",
    batch_id: str = "",
    error_id: str = "",
    limit: int = 7,
) -> list[dict[str, Any]]:
    criteria = {
        key: str(value)
        for key, value in (
            ("feature_key", feature_key),
            ("operation_id", operation_id),
            ("trace_id", trace_id),
            ("task_id", task_id),
            ("result_id", result_id),
            ("delivery_id", delivery_id),
            ("batch_id", batch_id),
            ("error_id", error_id),
        )
        if value
    }
    if not criteria:
        return []
    with _LOCK:
        matches = [
            dict(item)
            for item in _RECENT_EVENTS
            if any(str(item.get(key) or "") == value for key, value in criteria.items())
        ]
    return matches[-max(1, min(int(limit), 120)):]


def initialize_file_logging(app_data_root: Path) -> dict[str, Any]:
    logger = initialize_console_logging()
    override = str(os.environ.get(RUNTIME_ROOT_OVERRIDE_ENV) or "").strip()
    root = Path(override).expanduser().resolve() if override else Path(app_data_root)
    log_path = root / LOG_RELATIVE_PATH
    with _LOCK:
        current_handlers = _runtime_handlers(logger, _FILE_KIND)
        for handler in current_handlers:
            if Path(getattr(handler, "baseFilename", "")) == log_path.absolute():
                return {
                    "initialized": True,
                    "degraded": False,
                    "path": log_path,
                    "reason": "already_initialized",
                    "isolated": bool(override),
                    "run_kind": "test" if override else "product",
                }

        for handler in current_handlers:
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=MAX_LOG_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
            )
            setattr(file_handler, _HANDLER_MARKER, _FILE_KIND)
            file_handler.setFormatter(_RuntimeFormatter())
        except Exception as exc:
            log_runtime_event(
                "RUNTIME_LOGGING_DEGRADED",
                level=logging.WARNING,
                stage="file_logging_initialization",
                result="console_only",
                error_category=ENVIRONMENT_ERROR,
                path=log_path,
                reason=str(exc),
                impact="file_logging_unavailable",
                action="check_diagnostic_log_directory_permissions",
            )
            return {
                "initialized": False,
                "degraded": True,
                "path": log_path,
                "reason": str(exc),
                "isolated": bool(override),
                "run_kind": "test" if override else "product",
            }

        logger.addHandler(file_handler)

    log_runtime_event(
        "RUNTIME_LOGGING_INITIALIZED",
        stage="file_logging_initialization",
        result="success",
        path=log_path,
        impact="runtime_events_persisted",
        action="none",
    )
    return {
        "initialized": True,
        "degraded": False,
        "path": log_path,
        "reason": "",
        "isolated": bool(override),
        "run_kind": "test" if override else "product",
    }


def runtime_logging_state() -> dict[str, Any]:
    logger = initialize_console_logging()
    file_handlers = _runtime_handlers(logger, _FILE_KIND)
    path = Path(getattr(file_handlers[0], "baseFilename")) if file_handlers else None
    return {
        "console_initialized": bool(_runtime_handlers(logger, _CONSOLE_KIND)),
        "file_initialized": bool(file_handlers),
        "file_handler_count": len(file_handlers),
        "path": path,
        "runtime_id": _RUNTIME_ID,
        "isolated": bool(os.environ.get(RUNTIME_ROOT_OVERRIDE_ENV)),
        "run_kind": "test" if os.environ.get(RUNTIME_ROOT_OVERRIDE_ENV) else "product",
    }


def reset_runtime_logging_for_tests() -> None:
    logger = logging.getLogger(LOGGER_NAME)
    with _LOCK:
        for handler in list(_runtime_handlers(logger)):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
        _RECENT_EVENTS.clear()
    initialize_console_logging()
