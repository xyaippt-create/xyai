"""Stage 4 local image-compression API adapter.

This module is intentionally a thin integration layer around the frozen
``engine.image_compression.router`` contract.  It owns only local intake,
opaque file tokens, task lifetime, safe previews, and the user visual-review
decision.  It never accepts an arbitrary filesystem path from the client.
"""

import asyncio
import hashlib
import io
import json
import logging
import math
import mimetypes
import os
import platform
import queue
import re
import secrets
import shutil
import subprocess
import threading
import time
import unicodedata
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping
from urllib.parse import quote

from engine.storage.batch_results import batch_views, item_identity
from backend.output_center_preview import read_image_header

from engine.diagnostics.feedback_context import build_feedback_context, feedback_context_preview
from engine.diagnostics.runtime_logging import build_exception_diagnostics, new_operation_identity, related_runtime_events
from engine.output.filename_policy import (
    FEATURE_COLOR,
    FEATURE_COMPRESSION,
    build_output_filename,
    build_output_path,
)
from engine.output.publish_safety import (
    OutputIdentityMismatchError,
    publish_image_file_with_metadata,
    publish_verified_file_copy_no_overwrite,
)
from engine.storage.app_data_migration import resolve_migrated_formal_output_path
from engine.storage.result_reuse import (
    ResultReuseError,
    resolve_reusable_result_source,
    result_lineage_fields,
    result_lineage,
    result_reuse_denial,
)
from engine.image_compression.delivery_options import (
    DELIVERY_OPTIMIZATION_MODE,
    KEEP_ORIGINAL_SCHEME,
    PNG_LOSSLESS_SCHEME,
    PRESERVE_FORMAT_TARGET_FORMAT,
    SMART_COMPRESSION_TARGET_FORMAT,
    SUPPORTED_TARGET_FORMATS,
    WEBP_LOSSLESS_SCHEME,
    generate_delivery_candidates,
)


logger = logging.getLogger(__name__)
IMAGE_FILE_CONTRACTS = {
    ".png": {"pil_format": "PNG", "media_type": "image/png", "thumbnail_suffix": ".png"},
    ".jpg": {"pil_format": "JPEG", "media_type": "image/jpeg", "thumbnail_suffix": ".jpg"},
    ".jpeg": {"pil_format": "JPEG", "media_type": "image/jpeg", "thumbnail_suffix": ".jpg"},
    ".webp": {"pil_format": "WEBP", "media_type": "image/webp", "thumbnail_suffix": ".webp"},
}
ALLOWED_EXTENSIONS = frozenset(IMAGE_FILE_CONTRACTS)
COMPRESSION_INTAKE_EXTENSIONS = ALLOWED_EXTENSIONS
OUTPUT_CENTER_IMAGE_FORMATS = frozenset(
    str(contract["pil_format"])
    for contract in IMAGE_FILE_CONTRACTS.values()
)
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
LOCAL_RETOUCH_REUSE_MAX_PIXELS = 40_000_000
TOKEN_TTL_SECONDS = 60 * 60
IMAGE_COMPRESSION_API_VERSION = "hdde.image-compression-api.v1"
LONG_IMAGE_WIDTH_RISK_POLICY_VERSION = "PRODUCT_PREFLIGHT_HEURISTIC_V1"
FUNCTION_DIRECTORY_BY_MODE = {
    DELIVERY_OPTIMIZATION_MODE: "交付优化",
    "LOSSLESS_COMPRESSION": "PNG无损压缩",
    "RESIZE_REDUCTION": "尺寸缩小",
    "UPLOAD_ADAPTATION": "上传适配",
}
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
SMART_DELIVERY_MAX_ITEMS = 100
SMART_DELIVERY_MAX_FILENAME_CHARS = 180
WINDOWS_SAFE_PATH_UTF16_UNITS = 240
SMART_DELIVERY_PLAN_TTL_SECONDS = 30 * 60
SMART_DELIVERY_REQUEST_FACT_PREFIX = "delivery_request:"
SMART_DELIVERY_ELIGIBILITY_FACT_PREFIX = "delivery_eligibility:"
# A PROCESSING request left by another backend session (crash/restart) is treated as
# interrupted after this long; the copy of one Result never takes minutes.
SMART_DELIVERY_PROCESSING_STALE_SECONDS = 10 * 60
SMART_DELIVERY_RUN_CACHE_SIZE = 64
SMART_DELIVERY_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^delivery_request_[A-Za-z0-9_-]{16,96}$")
SMART_DELIVERY_ELIGIBILITY_INVALIDATING_CODES = frozenset({
    "RESULT_IDENTITY_MISMATCH",
    "RESULT_NOT_DELIVERABLE",
    "RESULT_ARTIFACT_MISSING",
    "UNIFIED_RESULT_NOT_FOUND",
    "UNIFIED_RESULT_REQUIRED",
    "COLOR_RESULT_NOT_ACCEPTED",
})
OUTPUT_CENTER_THUMBNAIL_MAX_EDGE = 768
OUTPUT_CENTER_THUMBNAIL_CACHE_VERSION = "v2"
OUTPUT_CENTER_THUMBNAIL_MAX_PIXELS = 40_000_000
OUTPUT_CENTER_THUMBNAIL_MAX_CONCURRENCY = 4
RESULT_IDENTITY_MISMATCH = "RESULT_IDENTITY_MISMATCH"
LEGACY_HDDE_RETOUCH_FILENAME_TOKENS = (
    "_影界瑕疵修整_",
    "_影界局部修复_",
    "_影界局部修整_",
    "_影界标记修整_",
)
CURRENT_HDDE_RETOUCH_FILENAME_TOKEN = "_影界瑕疵修复_"
HDDE_RETOUCH_GENERATED_SUFFIX_PATTERN = re.compile(
    rf"^(?P<token>{'|'.join(re.escape(token) for token in (*LEGACY_HDDE_RETOUCH_FILENAME_TOKENS, CURRENT_HDDE_RETOUCH_FILENAME_TOKEN))})"
    r"(?P<timestamp>\d{8}_\d{6})(?P<counter>_\d+)?$"
)
COLOR_CORRECTION_FEATURE_KEY = "color_correction"
BATCH_NAMING_DELIVERY_FACT_PREFIX = "delivery:"
CONTINUE_PROCESSOR_SPECS = (
    {"key": "image_enhancement", "label": "画质增强"},
    {"key": "color_correction", "label": "颜色校正"},
    {"key": "image_compression", "label": "图片压缩"},
    {"key": "local_retouch", "label": "瑕疵修复"},
    {"key": "batch_watermark", "label": "添加水印"},
)
CONTINUE_FEATURE_PROCESSORS = {
    "image_processing": "image_enhancement",
    "enhancement_1080p": "image_enhancement",
    "enhancement_4k": "image_enhancement",
    "color_correction": "color_correction",
    "image_compression": "image_compression",
    "local_retouch": "local_retouch",
    "batch_watermark": "batch_watermark",
}


def normalize_hdde_generated_filename(
    stem: str,
    processing_type: str,
    original_filename: str,
) -> tuple[str, str]:
    """Normalize a proven HDDE-generated retouch suffix without touching the user stem."""

    source_stem = str(stem or "")
    if str(processing_type or "") != "local_retouch":
        return source_stem, "NOT_APPLICABLE"
    trusted_original_name = str(original_filename or "").strip()
    original_stem = Path(trusted_original_name).stem if trusted_original_name else ""
    if not original_stem or not source_stem.startswith(original_stem):
        return source_stem, "UNAVAILABLE"
    system_part = source_stem[len(original_stem):]
    match = HDDE_RETOUCH_GENERATED_SUFFIX_PATTERN.fullmatch(system_part)
    if match is None:
        return source_stem, "UNAVAILABLE"
    token = match.group("token")
    if token in LEGACY_HDDE_RETOUCH_FILENAME_TOKENS:
        system_part = f"{CURRENT_HDDE_RETOUCH_FILENAME_TOKEN}{system_part[len(token):]}"
    return f"{original_stem}{system_part}", "VERIFIED"


def batch_naming_delivery_fact_key(run_id: str) -> str:
    normalized = str(run_id or "").strip()
    if not normalized:
        raise ValueError("BATCH_NAMING_RUN_ID_REQUIRED")
    return f"{BATCH_NAMING_DELIVERY_FACT_PREFIX}{normalized}"


def smart_delivery_name_issues(stem: str, suffix: str) -> list[tuple[str, str]]:
    """Validate the unmodified source-result filename before collision allocation."""

    issues: list[tuple[str, str]] = []
    if not stem:
        issues.append(("EMPTY_FILE_NAME", "最终交付文件名不能为空。"))
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', stem):
        issues.append(("WINDOWS_INVALID_CHARACTER", "文件名包含Windows不允许的字符。"))
    if stem.endswith((" ", ".")):
        issues.append(("WINDOWS_INVALID_ENDING", "文件名不得以空格或句点结尾。"))
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        issues.append(("WINDOWS_RESERVED_NAME", "文件名属于Windows保留名称。"))
    if len(f"{stem}{suffix}") > SMART_DELIVERY_MAX_FILENAME_CHARS:
        issues.append(("FILE_NAME_TOO_LONG", f"文件名不得超过{SMART_DELIVERY_MAX_FILENAME_CHARS}个字符。"))
    if suffix.lower() not in ALLOWED_EXTENSIONS:
        issues.append(("EXTENSION_INVALID", "源成品扩展名不属于当前支持的图片格式。"))
    return issues


def image_media_type(path: str | Path) -> str:
    contract = IMAGE_FILE_CONTRACTS.get(Path(path).suffix.lower())
    if contract is not None:
        return str(contract["media_type"])
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def _positive_dimension(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def is_long_image(width: Any, height: Any) -> bool:
    """Stage 4 product-layer long-image classification."""

    if not _positive_dimension(width) or not _positive_dimension(height) or height <= width:
        return False
    ratio = height / width
    return ratio >= 3 or (height >= 4000 and ratio > (16 / 9))


def dimensions_after_exif_orientation(width: Any, height: Any, orientation: Any) -> tuple[int, int]:
    if not _positive_dimension(width) or not _positive_dimension(height):
        raise ValueError("source dimensions must be positive integers")
    return (height, width) if orientation in {5, 6, 7, 8} else (width, height)


def calculate_target_by_short_side(source_width: Any, source_height: Any, target_short_side: Any) -> dict[str, Any]:
    """Calculate proportional dimensions using the source short side.

    Positive values ending in exactly .5 use the same half-up rule as the
    frozen Stage 3 resize engine.
    """

    if not _positive_dimension(source_width):
        raise ValueError("source_width must be a positive integer")
    if not _positive_dimension(source_height):
        raise ValueError("source_height must be a positive integer")
    if not _positive_dimension(target_short_side):
        raise ValueError("target_short_side must be a positive integer")
    source_short_side = min(source_width, source_height)
    source_long_side = max(source_width, source_height)
    scale = target_short_side / source_short_side
    return {
        "source_width": source_width,
        "source_height": source_height,
        "source_short_side": source_short_side,
        "source_long_side": source_long_side,
        "target_short_side": target_short_side,
        "scale": scale,
        "target_width": max(1, int(math.floor(source_width * scale + 0.5))),
        "target_height": max(1, int(math.floor(source_height * scale + 0.5))),
    }


def estimate_product_dimensions(width: int, height: int, mode: str, params: Mapping[str, Any]) -> dict[str, Any]:
    if not _positive_dimension(width) or not _positive_dimension(height):
        return {"width": None, "height": None, "scale": None}
    scale = 1.0
    if mode == "RESIZE_REDUCTION":
        if params.get("target_short_side") is not None:
            calculated = calculate_target_by_short_side(width, height, params["target_short_side"])
            return {
                "width": calculated["target_width"],
                "height": calculated["target_height"],
                "scale": calculated["scale"],
            }
        if params.get("scale_ratio") is not None:
            scale = min(1.0, float(params["scale_ratio"]))
        elif params.get("target_width") is not None:
            scale = min(1.0, int(params["target_width"]) / width)
        elif params.get("target_height") is not None:
            scale = min(1.0, int(params["target_height"]) / height)
    elif mode == "UPLOAD_ADAPTATION":
        ratios = [1.0]
        if params.get("max_width") is not None:
            ratios.append(int(params["max_width"]) / width)
        if params.get("max_height") is not None:
            ratios.append(int(params["max_height"]) / height)
        scale = min(value for value in ratios if value > 0)
    return {
        "width": max(1, round(width * scale)),
        "height": max(1, round(height * scale)),
        "scale": scale,
    }


def classify_long_image_width(width: Any) -> dict[str, Any]:
    value = int(width) if isinstance(width, (int, float)) and not isinstance(width, bool) else 0
    if value < 600:
        return {
            "level": "BLOCKED",
            "blocked": True,
            "confirmation_required": False,
            "message": f"当前限制会将长图宽度缩小至约 {max(0, value)} 像素，可能导致文字无法阅读。请提高高度限制、取消最大高度，或改用更大的输出宽度。",
        }
    if value < 750:
        return {"level": "CONFIRMATION_REQUIRED", "blocked": False, "confirmation_required": True, "message": "长图文字可能明显难以阅读，继续前必须确认风险。"}
    if value < 900:
        return {"level": "STRONG_WARNING", "blocked": False, "confirmation_required": False, "message": "小字清晰度风险明显，请在100%模式下重点复核。"}
    if value < 1080:
        return {"level": "REVIEW_NOTICE", "blocked": False, "confirmation_required": False, "message": "可能影响细小文字，请在100%模式下复核。"}
    return {"level": "LOWER_RISK", "blocked": False, "confirmation_required": False, "message": "宽度风险较低，处理后仍需人工复核。"}


def build_long_image_validation(source: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    width = int(source.get("width") or 0)
    height = int(source.get("height") or 0)
    detected = is_long_image(width, height)
    mode = str(request.get("operation_mode") or "")
    request_context = request.get("request_context") if isinstance(request.get("request_context"), Mapping) else {}
    params = {name: request.get(name) for name in ("scale_ratio", "target_width", "target_height", "max_width", "max_height", "max_file_size_bytes")}
    if request_context.get("resize_strategy") == "SHORT_SIDE":
        params["target_short_side"] = request_context.get("target_short_side")
    estimated = estimate_product_dimensions(width, height, mode, params)
    risk = classify_long_image_width(estimated["width"]) if detected else {"level": None, "message": ""}
    warnings = []
    if detected:
        warnings = ["已识别为长图。建议优先限制宽度和文件体积，不限制总高度。", risk["message"]]
    return {
        "is_long_image": detected,
        "source_aspect_ratio": (height / width) if width and height else None,
        "source_width": width or None,
        "source_height": height or None,
        "preview_default_mode": "fit-width" if detected else "overview",
        "estimated_output_width": estimated["width"],
        "estimated_output_height": estimated["height"],
        "long_image_risk_level": risk["level"],
        "long_image_warnings": warnings,
        "height_limit_applied": bool(request.get("max_height")),
        "width_limit_applied": bool(request.get("max_width") or request.get("target_width") or request.get("scale_ratio")),
        "file_size_limit_applied": bool(request.get("max_file_size_bytes")),
        "long_image_width_risk_policy_version": LONG_IMAGE_WIDTH_RISK_POLICY_VERSION,
    }


def build_resize_validation(source: Mapping[str, Any], request: Mapping[str, Any], result: Any | None = None) -> dict[str, Any]:
    request_context = request.get("request_context") if isinstance(request.get("request_context"), Mapping) else {}
    strategy = str(request_context.get("resize_strategy") or "")
    if str(request.get("operation_mode") or "") != "RESIZE_REDUCTION":
        return {}
    source_width = int(source.get("width") or 0)
    source_height = int(source.get("height") or 0)
    estimated = estimate_product_dimensions(
        source_width,
        source_height,
        "RESIZE_REDUCTION",
        {
            "target_short_side": request_context.get("target_short_side") if strategy == "SHORT_SIDE" else None,
            "scale_ratio": request.get("scale_ratio"),
            "target_width": request.get("target_width") if strategy != "SHORT_SIDE" else None,
            "target_height": request.get("target_height") if strategy != "SHORT_SIDE" else None,
        },
    )
    actual_dimensions = getattr(result, "output_dimensions", None) if result is not None else None
    actual_width = int((actual_dimensions or {}).get("width") or 0) or None
    actual_height = int((actual_dimensions or {}).get("height") or 0) or None
    aspect_ratio_preserved = None
    if actual_width and actual_height and source_width and source_height:
        aspect_ratio_preserved = abs(round(source_width * actual_height / source_height) - actual_width) <= 1
    return {
        "resize_strategy": strategy or None,
        "source_width": source_width or None,
        "source_height": source_height or None,
        "source_short_side": min(source_width, source_height) if source_width and source_height else None,
        "target_short_side": request_context.get("target_short_side") if strategy == "SHORT_SIDE" else None,
        "calculated_scale": estimated["scale"],
        "estimated_target_width": estimated["width"],
        "estimated_target_height": estimated["height"],
        "actual_target_width": actual_width,
        "actual_target_height": actual_height,
        "aspect_ratio_preserved": aspect_ratio_preserved,
        "crop_applied": False,
        "padding_applied": False,
        "upscale_applied": False,
    }


def _readable_label(value: str, *, limit: int = 54) -> str:
    cleaned = "".join("_" if char in '<>:"/\\|?*' or ord(char) < 32 else char for char in str(value)).strip(" ._")
    cleaned = (cleaned or "图片")[:limit].rstrip(" ._")
    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def _format_limit_label(value: Any) -> str | None:
    if not value:
        return None
    size = int(value)
    if size % (1024 * 1024) == 0:
        return f"{size // (1024 * 1024)}MB"
    if size % 1024 == 0:
        return f"{size // 1024}KB"
    return f"{size}B"


def _operation_and_parameter_labels(request: Mapping[str, Any]) -> tuple[str, list[str]]:
    mode = str(request.get("operation_mode") or "")
    request_context = request.get("request_context") if isinstance(request.get("request_context"), Mapping) else {}
    if mode == "LOSSLESS_COMPRESSION":
        return "PNG无损压缩", []
    if mode == "RESIZE_REDUCTION":
        if request_context.get("resize_strategy") == "SHORT_SIDE":
            return "尺寸缩小", [f"短边{int(request_context['target_short_side'])}"]
        if request_context.get("resize_strategy") == "WIDTH":
            return "尺寸缩小", [f"宽度{int(request_context['target_width'])}"]
        if request_context.get("resize_strategy") == "HEIGHT":
            return "尺寸缩小", [f"高度{int(request_context['target_height'])}"]
        if request.get("target_width"):
            return "尺寸缩小", [f"宽度{int(request['target_width'])}"]
        if request.get("target_height"):
            return "尺寸缩小", [f"高度{int(request['target_height'])}"]
        return "尺寸缩小", [f"{round(float(request.get('scale_ratio') or 0) * 100)}"]
    parameters: list[str] = []
    if request.get("max_width"):
        parameters.append(f"短边{int(request['max_width'])}")
    if request.get("max_height"):
        parameters.append(f"高度{int(request['max_height'])}")
    size_label = _format_limit_label(request.get("max_file_size_bytes"))
    if size_label:
        parameters.append(size_label)
    return "上传适配", parameters


def readable_output_name(source_name: str, output_suffix: str, request: Mapping[str, Any], task_id: str, now_value: float) -> str:
    del request, task_id
    source = Path(source_name)
    suffix = output_suffix.lower() if output_suffix.lower() in {".png", ".jpg", ".jpeg"} else source.suffix.lower()
    return build_output_filename(
        source.name,
        FEATURE_COMPRESSION,
        suffix,
        trusted_original_filename=source.name,
        moment=datetime.fromtimestamp(now_value),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(filename: str | None) -> str:
    original = Path(str(filename or "image.png")).name
    cleaned = "".join("_" if char in '<>:"/\\|?*' or ord(char) < 32 else char for char in original).strip(" .")
    return cleaned or "image.png"


def _format_bytes(value: int | None) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{int(value or 0)} B"


def _is_non_product_output_name(filename: str) -> bool:
    """Exclude explicit development/test artifacts without guessing from timestamps or extensions."""

    normalized = str(filename or "").lower()
    exact_markers = (
        "playwright",
        "processing-center",
        "front_upload_test",
        "review_package",
        "evidence_",
        "audit_",
    )
    return (
        any(marker in normalized for marker in exact_markers)
        or re.match(r"^\d{2}-(?:processing|task|compare|report)-", normalized) is not None
        or re.match(r"^s\d{2}__", normalized) is not None
        or normalized.startswith("sample_")
    )


def register_image_compression_routes(
    app,
    *,
    user_dirs_provider: Callable[[], dict[str, Path]],
    now_provider: Callable[[], float] = time.time,
    folder_opener: Callable[[str], None] | None = None,
    output_settings_provider: Callable[[], Mapping[str, Any]] | None = None,
    color_output_settings_provider: Callable[[], Mapping[str, Any]] | None = None,
    output_default_saver: Callable[[str], None] | None = None,
    output_dir_validator: Callable[[str], Mapping[str, Any]] | None = None,
    shared_task_registry: MutableMapping[str, dict[str, Any]] | None = None,
    output_center_user_dirs_provider: Callable[[], dict[str, Path]] | None = None,
    feedback_runtime_provider: Callable[[], Mapping[str, Any]] | None = None,
    runtime_event_logger: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Register the local Stage 4 API on the already-created FastAPI app."""

    from fastapi import Body, File, HTTPException, Request, UploadFile
    from fastapi.responses import FileResponse, Response

    from engine.image_compression.common import apply_delivery_gate, read_image_info
    from engine.image_compression.contracts import (
        ImageCompressionResult,
        RESULT_FIELD_NAMES,
        RESULT_CONTRACT_VERSION,
        TASK_CONTRACT_VERSION,
    )
    from engine.image_compression.router import process_image_compression
    from engine.image_compression.statuses import (
        CandidateDeliveryRole,
        DeliveryGateStatus,
        OperationMode,
        TechnicalStatus,
        VisualReviewStatus,
    )
    from engine.color_correction import FORMAL_COLOR_RUNTIME_VERSION, run_formal_color_runtime
    from engine.color_correction.color_management import ColorManagementError, load_color_managed_source, srgb_profile_bytes
    from engine.color_correction.formal_runtime import _write_verified_candidate
    from engine.color_correction.level_pick import (
        LEVEL_LABELS,
        LEVEL_PICK_VERSION,
        LEVELS,
        analyze_level_pick,
        build_level_pick_preview,
        level_safety,
        pixel_sha256,
        render_level,
    )
    from engine.color_correction.reference_level_pick import (
        REFERENCE_LEVEL_PICK_VERSION,
        build_reference_level_pick_preview,
        plan_reference,
        render_reference_level,
    )
    from PIL import Image

    token_registry: dict[str, dict[str, Any]] = {}
    expired_feedback_tokens: set[str] = set()
    task_registry: dict[str, dict[str, Any]] = {}
    color_batch_registry: dict[str, dict[str, Any]] = {}
    # Level-pick previews live only in this process: a restart invalidates them, so a
    # formal Result can never be produced from a preview the user did not see in this run.
    color_level_preview_sessions: dict[str, dict[str, Any]] = {}
    color_batch_queue: queue.Queue[str] = queue.Queue()
    color_batch_worker_lock = threading.Lock()
    color_batch_worker_state: dict[str, threading.Thread | None] = {"thread": None}
    server_session_id = uuid.uuid4().hex
    output_center_index: dict[str, dict[str, Any]] = {}
    output_center_batch_bindings: dict[str, dict[str, Any]] = {}
    # Scope is exact identity at backend startup, never filename/mtime grouping.
    output_center_history_ids = set(shared_task_registry or {}) | {
        str(record.get(key) or "")
        for record in (shared_task_registry or {}).values()
        for key in ("task_id", "batch_id")
    }

    def output_record_scope(record):
        identity = str(record.get("batch_id") or record.get("task_id") or "")
        return "current" if identity and identity not in output_center_history_ids else "history"

    def output_child_record_id(child):
        return f"batch_item:{child['batch_id']}:{child['batch_item_id']}"

    def output_remaining_batch(batch, remaining):
        summary = dict(batch["summary"])
        for key, status in (("completed", "COMPLETED"), ("keep_original", "KEEP_ORIGINAL"),
                            ("failed", "FAILED"), ("canceled", "CANCELED"), ("pending", "QUEUED"), ("processing", "PROCESSING")):
            summary[key] = sum(item["status"] == status for item in remaining)
        original = sum(item["original_bytes"] for item in remaining)
        final = sum(item["final_bytes"] if item["status"] in {"COMPLETED", "KEEP_ORIGINAL"} and item["final_bytes"] is not None else item["original_bytes"] for item in remaining)
        summary.update(total=len(remaining), original_bytes=original, final_bytes=final,
                       saved_bytes=original-final, saved_percent=(original-final)*100/original if original else None,
                       unavailable=sum(item["status"] == "COMPLETED" and not item["available"] for item in remaining))
        return {**batch, "items": remaining, "summary": summary,
                "file_name": f"{batch['processing_label']} · {len(remaining)} 张"}

    def output_file_missing(path):
        if not path:
            return False
        try:
            Path(path).stat()
        except FileNotFoundError:
            return True
        except OSError:
            # Permission/temporary IO failure is not proven deletion.
            return False
        return False
    output_center_thumbnail_semaphore = asyncio.Semaphore(OUTPUT_CENTER_THUMBNAIL_MAX_CONCURRENCY)
    output_center_thumbnail_locks: dict[str, threading.Lock] = {}
    output_center_thumbnail_locks_guard = threading.Lock()
    smart_delivery_plan_registry: dict[str, dict[str, Any]] = {}
    smart_delivery_run_registry: dict[str, dict[str, Any]] = {}
    smart_delivery_request_registry: dict[str, dict[str, Any]] = {}
    smart_delivery_eligibility_registry: dict[str, dict[str, Any]] = {}
    smart_delivery_request_lock = threading.RLock()
    smart_delivery_eligibility_lock = threading.RLock()
    smart_delivery_hash_cache: dict[tuple[str, int, int, int], str] = {}
    smart_delivery_executing_plans: set[str] = set()

    def emit_runtime_event(event: str, **fields: Any) -> None:
        if runtime_event_logger is None:
            return
        try:
            runtime_event_logger(event, **fields)
        except Exception:
            # Diagnostic logging must never alter the product path.
            return

    def operation_event_fields(record: Mapping[str, Any]) -> dict[str, str]:
        context = record.get("task_context") if isinstance(record.get("task_context"), Mapping) else {}
        return {
            "feature_key": str(record.get("feature_key") or context.get("feature_key") or ""),
            "module_id": str(record.get("module_id") or context.get("module_id") or ""),
            "operation_id": str(record.get("operation_id") or context.get("operation_id") or ""),
            "trace_id": str(record.get("trace_id") or context.get("trace_id") or ""),
        }
    def claim_task_execution(record: dict[str, Any]) -> bool:
        task_id = str(record.get("task_id") or "").strip()
        if not task_id:
            return False
        claim = getattr(shared_task_registry, "claim_task_execution", None)
        if callable(claim):
            claimed = bool(claim(task_id))
        else:
            status = str(record.get("task_status") or record.get("status") or "").lower()
            claimed = status in {"pending", "queued"} and not bool(record.get("execution_started"))
        if claimed:
            record["execution_started"] = True
            record["execution_state"] = "scheduled"
        return claimed

    def registered_image_paths() -> set[Path]:
        """Derive retention from existing facts, including retained Result facts.

        No token/pin database: deleting a Task releases only its own references;
        SharedTaskRegistry.delete_task_fact keeps the existing Result references.
        Reference previews require the private reference input while that Task
        exists. A future explicit asset collector can use the same predicate.
        """
        records = list((shared_task_registry if shared_task_registry is not None else task_registry).values())
        if shared_task_registry is not None:
            records.extend(record for record in list(task_registry.values())
                           if record.get("status") in {"pending", "queued", "processing", "running"})
        paths: set[Path] = set()
        pending = list(records)
        while pending:
            value = pending.pop()
            if hasattr(value, "to_dict"):
                value = value.to_dict()
            if isinstance(value, (list, tuple)):
                pending.extend(value)
            elif isinstance(value, Mapping):
                for field in ("source", "source_path", "source_file", "input_path", "result_file",
                              "output_path", "final_output_path", "source_result_path", "path",
                              "delivery_file", "delivery_path"):
                    raw = value.get(field)
                    if isinstance(raw, (str, Path)) and str(raw).strip():
                        paths.add(Path(raw).resolve())
                for field in ("result", "task_result", "source_metadata", "reference_metadata",
                              "source", "items", "sources", "deliveries"):
                    child = value.get(field)
                    if child is not None and not isinstance(child, (str, Path)):
                        pending.append(child)
        return paths

    def prune_tokens() -> None:
        now = now_provider()
        expired_inputs = []
        for token, item in list(token_registry.items()):
            if item.get("expires_at", 0) > now:
                continue
            token_registry.pop(token, None)
            if item.get("role") == "feedback_package":
                expired_feedback_tokens.add(token)
            elif item.get("role") in {"source", "source_preview"}:
                # A preview can outlive a duplicate source token. Reconsider
                # its intake only after the last live authorization expires.
                expired_inputs.append(item.get("path"))
        if not expired_inputs:
            return
        try:
            protected = registered_image_paths()
            protected.update(Path(item["path"]).resolve() for item in list(token_registry.values())
                             if item.get("expires_at", 0) > now)
            dirs = require_compression_directory()
            formal_root = Path(dirs.get("app_data_root") or Path(dirs["normal_output_dir"]).parent).resolve()
            cache_root = Path(dirs["tmp_dir"]).resolve()
            if formal_root not in cache_root.parents:
                return
            intake_root = cache_root / "image-compression-intake"
            for raw in expired_inputs:
                path = Path(raw)
                # Only an owned intake leaf may be unlinked. Never follow a
                # traversal, symlink/junction, or a token pointing at an output.
                if not path.is_absolute() or ".." in path.parts:
                    continue
                resolved = path.resolve()
                if (resolved != path or resolved in protected or path.parent.parent != intake_root
                        or not re.fullmatch(r"intake_[0-9a-f]{32}", path.parent.name)
                        or path.suffix.lower() not in ALLOWED_EXTENSIONS):
                    continue
                if any(part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction())
                       for part in (path, path.parent, intake_root)):
                    continue
                if path.is_file():
                    path.unlink()
                if path.parent.is_dir() and not any(path.parent.iterdir()):
                    path.parent.rmdir()
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, HTTPException):
            # Authorization is already revoked. Uncertain ownership/root/file
            # facts must preserve data, never trigger a broader cleanup.
            return

    def issue_token(path: Path, *, role: str, filename: str, **metadata: Any) -> str:
        token = secrets.token_urlsafe(32)
        expired_feedback_tokens.discard(token)
        expires_at = now_provider() + TOKEN_TTL_SECONDS
        token_registry[token] = {
            "path": path,
            "role": role,
            "filename": filename,
            "expires_at": expires_at,
            **metadata,
        }
        return token

    def require_token(token: str, *, role: str | None = None) -> dict[str, Any]:
        prune_tokens()
        item = token_registry.get(str(token or ""))
        if not item or (role and item.get("role") != role):
            raise HTTPException(
                status_code=404,
                detail={"code": "TOKEN_NOT_FOUND_OR_EXPIRED", "message": "图片会话已失效，请重新选择图片。"},
            )
        path = Path(item["path"])
        if not path.exists() or not path.is_file():
            raise HTTPException(
                status_code=404,
                detail={"code": "TOKEN_NOT_FOUND_OR_EXPIRED", "message": "图片会话已失效，请重新选择图片。"},
            )
        return item

    def output_center_sources(user_dirs: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Return the finite set of formal directories owned by real product contracts."""

        if user_dirs is None:
            user_dirs = (output_center_user_dirs_provider or user_dirs_provider)()
        app_root = Path(
            user_dirs.get("app_data_root")
            or Path(user_dirs.get("normal_output_dir") or ".").resolve().parent
        ).resolve()
        output_root = app_root / "输出"
        compression_root = Path(user_dirs.get("image_compression_output_dir") or (output_root / "图片压缩")).resolve()
        return [
            {
                "category": "1080p",
                "label": "1080P画质",
                "paths": [
                    Path(user_dirs.get("normal_output_dir") or (output_root / "1080P画质")).resolve(),
                ],
            },
            {
                "category": "4k",
                "label": "4K画质增强",
                "paths": [output_root / "4K画质增强"],
            },
            {
                "category": "compression",
                "label": "图片压缩",
                "paths": [compression_root / directory for directory in FUNCTION_DIRECTORY_BY_MODE.values()],
            },
            {
                "category": "color_correction",
                "label": "颜色校正",
                "paths": [output_root / "颜色校正"],
            },
            {
                "category": "local_retouch",
                "label": "瑕疵修复",
                "paths": [output_root / "瑕疵修复"],
            },
            {
                "category": "batch_watermark",
                "label": "批量水印",
                "paths": [output_root / "批量水印"],
            },
        ]

    def output_center_active_records(
        formal_root: Path,
        target_paths: set[Path] | None = None,
    ) -> tuple[dict[Path, Mapping[str, Any]], dict[str, list[Mapping[str, Any]]]]:
        records: dict[Path, Mapping[str, Any]] = {}
        result_records: dict[str, list[Mapping[str, Any]]] = {}
        normalized_targets = {path.resolve() for path in target_paths or set()}
        target_keys = {os.path.normcase(str(path)) for path in normalized_targets}

        def register_result(candidate: Mapping[str, Any]) -> None:
            candidate_result = candidate.get("result")
            if hasattr(candidate_result, "to_dict"):
                candidate_result = candidate_result.to_dict()
            if not isinstance(candidate_result, Mapping):
                candidate_result = {}
            task_result = candidate.get("task_result")
            if not isinstance(task_result, Mapping):
                task_result = {}
            result_id = str(
                candidate.get("result_id")
                or task_result.get("result_id")
                or candidate_result.get("result_id")
                or ""
            ).strip()
            if not result_id:
                return
            bucket = result_records.setdefault(result_id, [])
            signature = (
                str(candidate.get("task_id") or task_result.get("task_id") or candidate_result.get("task_id") or ""),
                str(candidate.get("result_file") or candidate.get("output_path") or task_result.get("result_file") or candidate_result.get("result_file") or candidate_result.get("output_path") or ""),
                str(candidate.get("output_sha256") or task_result.get("output_sha256") or candidate_result.get("output_sha256") or ""),
            )
            if any(existing.get("_continue_identity") == signature for existing in bucket):
                return
            bucket.append({**candidate, "_continue_identity": signature})

        def resolve_target(raw_path: Any) -> Path | None:
            if not raw_path:
                return None
            raw_candidate = Path(str(raw_path))
            if normalized_targets and raw_candidate.is_absolute():
                raw_key = os.path.normcase(str(raw_candidate))
                if raw_key not in target_keys:
                    return None
            try:
                resolved = resolve_migrated_formal_output_path(str(raw_path), formal_root)
            except (OSError, ValueError):
                return None
            if normalized_targets and resolved not in normalized_targets:
                return None
            return resolved

        registries = [task_registry]
        if shared_task_registry is not None:
            registries.append(shared_task_registry)
        removed_results = {record.get("removed_result_id") for record in (shared_task_registry or {}).values()
                           if record.get("record_kind") == "output_center_hidden" and record.get("removed_result_id")}
        for registry in registries:
            for record in registry.values():
                if not isinstance(record, Mapping):
                    continue
                if record.get("record_kind") == "output_center_hidden":
                    continue  # Listing visibility facts are never Task/Result metadata.
                register_result(record)
                if str(record.get("result_id") or "") in removed_results:
                    continue
                result = record.get("result")
                if hasattr(result, "to_dict"):
                    result = result.to_dict()
                if not isinstance(result, Mapping):
                    result = {}
                nested_items = result.get("items") if isinstance(result.get("items"), list) else record.get("items")
                if isinstance(nested_items, list) and record.get("record_kind") != "compression_batch":
                    for nested in nested_items:
                        if not isinstance(nested, Mapping) or not nested.get("output_path"):
                            continue
                        nested_record = {
                            **record,
                            **nested,
                            "task_id": nested.get("task_id") or record.get("task_id") or "",
                            "result_id": nested.get("result_id") or "",
                            "result_file": nested.get("output_path") or "",
                            "output_path": nested.get("output_path") or "",
                            "output_sha256": nested.get("output_sha256") or "",
                            "status": nested.get("status") or record.get("status"),
                            "task_result": dict(nested),
                            "result": dict(nested),
                        }
                        register_result(nested_record)
                        nested_path = resolve_target(nested["output_path"])
                        if nested_path is None:
                            continue
                        records[nested_path] = nested_record
                raw_path = (
                    record.get("output_path")
                    or record.get("result_file")
                    or result.get("output_path")
                    or result.get("final_output_path")
                    or result.get("result_file")
                )
                if not raw_path:
                    continue
                path = resolve_target(raw_path)
                if path is None:
                    continue
                records[path] = record
        return records, result_records

    def find_managed_color_source(output_path: Path, user_dirs: Mapping[str, Any]) -> Path | None:
        match = re.fullmatch(r"(.+)_影界自动校正_\d{8}_\d{6}(?:_\d+)?", output_path.stem)
        if not match:
            return None
        compression_root = Path(
            user_dirs.get("image_compression_output_dir")
            or (Path(user_dirs.get("app_data_root") or output_path.parents[2]) / "输出" / "图片压缩")
        ).resolve()
        intake_root = compression_root / ".运行缓存" / "image-compression-intake"
        if not intake_root.is_dir():
            return None
        expected_name = f"{match.group(1)}{output_path.suffix}"
        matches: list[Path] = []
        try:
            intake_directories = [item for item in intake_root.iterdir() if item.is_dir() and item.name.startswith("intake_")]
        except OSError:
            return None
        for directory in intake_directories:
            candidate = directory / expected_name
            if candidate.is_file():
                matches.append(candidate.resolve())
                if len(matches) > 1:
                    return None
        return matches[0] if len(matches) == 1 else None

    def delivery_eligibility_fact_key(result_id: str) -> str:
        return f"{SMART_DELIVERY_ELIGIBILITY_FACT_PREFIX}{result_id}"

    def load_delivery_eligibility(result_id: str) -> dict[str, Any] | None:
        if not result_id:
            return None
        record: Any = None
        with smart_delivery_eligibility_lock:
            if shared_task_registry is not None:
                record = shared_task_registry.get(delivery_eligibility_fact_key(result_id))
            if not isinstance(record, Mapping):
                record = smart_delivery_eligibility_registry.get(result_id)
            if (
                not isinstance(record, Mapping)
                or str(record.get("record_kind") or "") != "delivery_eligibility"
                or str(record.get("result_id") or "") != result_id
            ):
                return None
            return dict(record)

    def persist_delivery_eligibility(
        result_id: str,
        *,
        eligible: bool,
        code: str = "",
        reason: str = "",
        registered_output_sha256: str = "",
        current_output_sha256: str = "",
    ) -> dict[str, Any] | None:
        normalized_result_id = str(result_id or "").strip()
        if not normalized_result_id:
            return None
        record = {
            "record_kind": "delivery_eligibility",
            "result_id": normalized_result_id,
            "delivery_eligible": bool(eligible),
            "failure_code": "" if eligible else str(code or "RESULT_NOT_DELIVERABLE"),
            "failure_reason": "" if eligible else str(reason or "当前 Result 不满足交付条件。"),
            "registered_output_sha256": str(registered_output_sha256 or "").lower(),
            "current_output_sha256": str(current_output_sha256 or "").lower(),
            "updated_at": datetime.fromtimestamp(now_provider(), tz=timezone.utc).isoformat(),
        }
        with smart_delivery_eligibility_lock:
            if shared_task_registry is not None:
                shared_task_registry[delivery_eligibility_fact_key(normalized_result_id)] = record
            smart_delivery_eligibility_registry[normalized_result_id] = record
        return dict(record)

    def output_center_record_meta(record: Mapping[str, Any] | None, formal_root: Path) -> dict[str, Any]:
        if not record:
            return {}
        result = record.get("result")
        if hasattr(result, "to_dict"):
            result = result.to_dict()
        if not isinstance(result, Mapping):
            result = {}
        task_result = record.get("task_result")
        if not isinstance(task_result, Mapping):
            task_result = {}
        source_path = (
            record.get("source")
            or record.get("source_path")
            or record.get("input_path")
            or result.get("source")
            or result.get("source_path")
            or result.get("input_path")
        )
        result_path = (
            record.get("result_file")
            or record.get("output_path")
            or result.get("result_file")
            or result.get("output_path")
            or result.get("final_output_path")
        )
        task_id = str(record.get("task_id") or result.get("task_id") or "")
        result_id = str(record.get("result_id") or result.get("result_id") or "")
        delivery_eligibility = load_delivery_eligibility(result_id)
        registered_output_sha256 = str(
            record.get("output_sha256")
            or result.get("output_sha256")
            or task_result.get("output_sha256")
            or ""
        ).lower()
        delivery_eligible = next(
            (
                bool(source.get("delivery_eligible"))
                for source in (record, result, task_result)
                if "delivery_eligible" in source
            ),
            None,
        )
        feature_key = str(record.get("feature_key") or result.get("feature_key") or "")
        module_id = str(record.get("module_id") or result.get("module_id") or "")
        operation_id = str(record.get("operation_id") or result.get("operation_id") or "")
        trace_id = str(record.get("trace_id") or result.get("trace_id") or "")
        original_filename = str(record.get("original_filename") or result.get("original_filename") or "")
        batch_id = str(record.get("batch_id") or result.get("batch_id") or "")
        task_family = str(record.get("task_family") or "")
        source = None
        if source_path:
            try:
                candidate = resolve_migrated_formal_output_path(str(source_path), formal_root)
                if candidate.is_file():
                    source = candidate
            except (OSError, ValueError):
                source = None
        result_file = None
        if result_path:
            try:
                candidate = resolve_migrated_formal_output_path(str(result_path), formal_root)
                if candidate.is_file():
                    result_file = candidate
            except (OSError, ValueError):
                result_file = None
        compare_url = ""
        if source and task_id and task_family == "color_correction":
            query = f"task_id={quote(task_id, safe='')}&from=outputs"
            if batch_id:
                query += f"&batch={quote(batch_id, safe='')}"
            compare_url = f"/color-correction/result?{query}"
        return {
            "source_path": source,
            "task_id": task_id,
            "result_id": result_id,
            "registered_output_sha256": registered_output_sha256,
            "delivery_eligible": delivery_eligible,
            "delivery_eligibility_override": (
                bool(delivery_eligibility.get("delivery_eligible"))
                if delivery_eligibility is not None
                else None
            ),
            "delivery_failure_code": str((delivery_eligibility or {}).get("failure_code") or ""),
            "delivery_failure_reason": str((delivery_eligibility or {}).get("failure_reason") or ""),
            "feature_key": feature_key,
            "module_id": module_id,
            "operation_id": operation_id,
            "trace_id": trace_id,
            "original_filename": original_filename,
            "result_file": result_file,
            "batch_id": batch_id,
            "batch_item_id": str(record.get("batch_item_id") or result.get("batch_item_id") or ""),
            "source_id": str(record.get("source_id") or result.get("source_id") or ""),
            "compare_url": compare_url,
            "review_status": str(record.get("review_status") or ""),
            "status": str(record.get("status") or result.get("status") or ""),
            "d3_final_action": str(record.get("d3_final_action") or result.get("d3_final_action") or ""),
            "result_action": str(record.get("result_action") or result.get("result_action") or ""),
            "output_selected": str(record.get("output_selected") or result.get("output_selected") or ""),
            "result_review_status": str(record.get("result_review_status") or result.get("result_review_status") or ""),
            "delivery_acceptance_authority": str(
                record.get("delivery_acceptance_authority")
                or result.get("delivery_acceptance_authority")
                or ""
            ),
        }

    def continue_record_value(record: Mapping[str, Any], field: str) -> Any:
        for source in (
            record,
            record.get("task_result"),
            record.get("result"),
            record.get("source_metadata"),
        ):
            if isinstance(source, Mapping) and source.get(field) not in (None, ""):
                return source.get(field)
        return ""

    def continue_processor_history(
        result_id: str,
        result_records: Mapping[str, list[Mapping[str, Any]]],
    ) -> tuple[set[str], bool]:
        processors: set[str] = set()
        visited: set[str] = set()
        current_id = str(result_id or "").strip()
        identity_conflict = False
        while current_id and current_id not in visited and len(visited) < 64:
            visited.add(current_id)
            matches = result_records.get(current_id, [])
            identities = {
                tuple(match.get("_continue_identity") or ())
                for match in matches
                if tuple(match.get("_continue_identity") or ()) != ("", "", "")
            }
            if len(identities) > 1:
                identity_conflict = True
                break
            if not matches:
                break
            record = next(
                (
                    match
                    for match in matches
                    if str(continue_record_value(match, "status") or "").lower() == "completed"
                ),
                matches[0],
            )
            feature_key = str(continue_record_value(record, "feature_key") or "").strip()
            processor_key = CONTINUE_FEATURE_PROCESSORS.get(feature_key)
            if processor_key:
                processors.add(processor_key)
            current_id = str(continue_record_value(record, "source_result_id") or "").strip()
        return processors, identity_conflict

    def build_continue_eligibility(
        *,
        record_meta: Mapping[str, Any],
        result_records: Mapping[str, list[Mapping[str, Any]]],
        unified_result: bool,
        size_bytes: int,
        width: int,
        height: int,
        image_format: str,
    ) -> list[dict[str, Any]]:
        history, identity_conflict = continue_processor_history(
            str(record_meta.get("result_id") or ""),
            result_records,
        )
        common_reason = ""
        if identity_conflict:
            common_reason = "Result 身份记录存在冲突，无法安全继续处理。"
        elif not unified_result:
            common_reason = "当前成品缺少完整 Result 来源关系。"
        elif str(record_meta.get("status") or "").lower() != "completed":
            common_reason = "只有已完成的正式 Result 可以继续处理。"
        elif result_reuse_denial(record_meta):
            common_reason = result_reuse_denial(record_meta)
        elif not str(record_meta.get("registered_output_sha256") or ""):
            common_reason = "当前 Result 缺少完整性校验记录。"
        elif int(size_bytes) > MAX_UPLOAD_BYTES:
            common_reason = "当前成品超过处理器的 50MB 输入限制。"

        eligibility: list[dict[str, Any]] = []
        for spec in CONTINUE_PROCESSOR_SPECS:
            key = str(spec["key"])
            history_status = "PROCESSED" if key in history else "NOT_PROCESSED"
            repeatable = key != "image_enhancement"
            status = "AVAILABLE"
            reason = "可作为新任务继续处理。"
            if common_reason:
                status = "UNAVAILABLE"
                reason = common_reason
            elif image_format == "WEBP" and key in {"image_enhancement", "local_retouch", "batch_watermark"}:
                status = "UNAVAILABLE"
                reason = "该处理器当前仅支持 PNG / JPG；当前 WebP 可继续压缩。"
            elif key == "image_enhancement" and history_status == "PROCESSED":
                status = "UNAVAILABLE"
                reason = "已完成画质增强。"
            elif key == "local_retouch" and int(width) * int(height) > LOCAL_RETOUCH_REUSE_MAX_PIXELS:
                status = "UNAVAILABLE"
                reason = "当前图片像素总量超过瑕疵修复输入限制。"
            elif key == "image_enhancement" and max(int(width), int(height)) >= 3840:
                status = "UNAVAILABLE"
                reason = "当前成品已达到 4K 长边规格，无需重复增强。"
            elif history_status == "PROCESSED":
                reason = "已处理，可再次处理。"
            eligibility.append({
                "key": key,
                "label": str(spec["label"]),
                "history_status": history_status,
                "eligibility": status,
                "repeatable": repeatable,
                "status": status,
                "reason": reason,
            })
        return eligibility

    def output_center_thumbnail_cache_root(user_dirs: Mapping[str, Any]) -> Path:
        formal_root = Path(
            user_dirs.get("app_data_root")
            or Path(user_dirs.get("normal_output_dir") or ".").resolve().parent
        ).resolve()
        output_root = (formal_root / "输出").resolve()
        runtime_cache = Path(
            user_dirs.get("tmp_dir")
            or (output_root / "图片压缩" / ".运行缓存")
        ).resolve()
        try:
            runtime_cache.relative_to(formal_root)
        except ValueError as exc:
            raise RuntimeError("output center thumbnail cache escaped the formal data root") from exc
        cache_root = (runtime_cache / "output-center-thumbnails").resolve()
        if not cache_root.is_relative_to(runtime_cache):
            raise RuntimeError("output center thumbnail directory escaped the cache root")
        return cache_root

    def output_center_thumbnail_entry(
        path: Path,
        user_dirs: Mapping[str, Any] | None = None,
        *,
        cache_root: Path | None = None,
    ) -> dict[str, Any]:
        if cache_root is None:
            if user_dirs is None:
                user_dirs = (output_center_user_dirs_provider or user_dirs_provider)()
            cache_root = output_center_thumbnail_cache_root(user_dirs)
        source = path.resolve()
        stat = source.stat()
        signature = hashlib.sha256(
            (
                f"{OUTPUT_CENTER_THUMBNAIL_CACHE_VERSION}|{OUTPUT_CENTER_THUMBNAIL_MAX_EDGE}|"
                f"{source}|{stat.st_size}|{stat.st_mtime_ns}"
            ).encode("utf-8")
        ).hexdigest()
        source_contract = IMAGE_FILE_CONTRACTS.get(source.suffix.lower())
        if source_contract is None:
            raise ValueError("unsupported output format")
        suffix = str(source_contract["thumbnail_suffix"])
        thumbnail_contract = IMAGE_FILE_CONTRACTS[suffix]
        cache_path = (cache_root / f"{signature}{suffix}").resolve()
        if not cache_path.is_relative_to(cache_root):
            raise RuntimeError("output center thumbnail file escaped the cache root")
        return {
            "cache_path": cache_path,
            "signature": signature,
            "source_size": int(stat.st_size),
            "source_mtime_ns": int(stat.st_mtime_ns),
            "media_type": str(thumbnail_contract["media_type"]),
            "thumbnail_format": str(thumbnail_contract["pil_format"]),
        }

    def ensure_output_center_thumbnail(path: Path) -> tuple[Path, dict[str, Any], bool]:
        entry = output_center_thumbnail_entry(path)
        cache_path = Path(entry["cache_path"])
        def valid_cache() -> bool:
            try:
                if not cache_path.is_file() or not 0 < cache_path.stat().st_size <= 8 * 1024 * 1024:
                    return False
                info = read_image_header(cache_path)
                if max(int(info["width"]), int(info["height"])) > OUTPUT_CENTER_THUMBNAIL_MAX_EDGE:
                    return False
                if info["format"] != entry["thumbnail_format"]:
                    return False
                with Image.open(cache_path) as cached:
                    cached.load()
                return True
            except (OSError, ValueError, RuntimeError, Image.DecompressionBombError):
                return False
        if valid_cache():
            return cache_path, entry, True
        with output_center_thumbnail_locks_guard:
            lock = output_center_thumbnail_locks.setdefault(str(entry["signature"]), threading.Lock())
        with lock:
            if valid_cache():
                return cache_path, entry, True
            info = read_image_header(path)
            pixel_limit = min(OUTPUT_CENTER_THUMBNAIL_MAX_PIXELS, Image.MAX_IMAGE_PIXELS or OUTPUT_CENTER_THUMBNAIL_MAX_PIXELS)
            if int(info["width"]) * int(info["height"]) > pixel_limit:
                raise ValueError("source exceeds the thumbnail pixel budget")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_name(f".{cache_path.stem}.{uuid.uuid4().hex}.tmp{cache_path.suffix}")
            try:
                with Image.open(path) as opened:
                    image_format = "JPEG" if opened.format == "JPG" else str(opened.format or "").upper()
                    if image_format not in OUTPUT_CENTER_IMAGE_FORMATS:
                        raise ValueError("unsupported output format")
                    opened.thumbnail(
                        (OUTPUT_CENTER_THUMBNAIL_MAX_EDGE, OUTPUT_CENTER_THUMBNAIL_MAX_EDGE),
                        Image.Resampling.LANCZOS,
                    )
                    thumbnail_format = str(entry["thumbnail_format"])
                    if thumbnail_format == "PNG":
                        opened.save(temporary, format="PNG")
                    elif thumbnail_format == "JPEG":
                        thumbnail = opened if opened.mode == "RGB" else opened.convert("RGB")
                        thumbnail.save(temporary, format="JPEG", quality=82, progressive=True)
                    else:
                        target_mode = "RGBA" if "A" in opened.getbands() else "RGB"
                        thumbnail = opened if opened.mode == target_mode else opened.convert(target_mode)
                        thumbnail.save(temporary, format="WEBP", quality=82, method=4)
                current = path.stat()
                if (
                    int(current.st_size) != entry["source_size"]
                    or int(current.st_mtime_ns) != entry["source_mtime_ns"]
                ):
                    raise OSError("source changed while thumbnail was generated")
                os.replace(temporary, cache_path)
            finally:
                temporary.unlink(missing_ok=True)
            return cache_path, entry, False

    def read_output_center_image_info(path: Path) -> dict[str, Any]:
        return read_image_header(path)

    def select_output_center_page(
        sources: list[dict[str, Any]],
        *,
        batches: list[dict[str, Any]],
        limit: int | None,
        offset: int,
        query: str,
        sort_order: str,
        category: str,
        scope: str = "all",
    ) -> dict[str, Any]:
        light_items: list[dict[str, Any]] = []
        seen_paths: set[Path] = set()
        skipped_unavailable = 0
        live_item_ids: set[str] = set()
        file_candidates: dict[tuple[str, Path], list[dict[str, Any]]] = {}
        for source in sources:
            for raw_directory in source["paths"]:
                directory = Path(raw_directory).resolve()
                if not directory.is_dir():
                    continue
                try:
                    candidates = list(directory.iterdir())
                except OSError:
                    skipped_unavailable += 1
                    continue
                for path in candidates:
                    if (
                        not path.is_file()
                        or path.suffix.lower() not in ALLOWED_EXTENSIONS
                        or _is_non_product_output_name(path.name)
                    ):
                        continue
                    try:
                        resolved = path.resolve()
                        if resolved in seen_paths:
                            continue
                        stat = resolved.stat()
                        if stat.st_size <= 0:
                            continue
                        info = read_output_center_image_info(resolved)
                    except Exception:
                        skipped_unavailable += 1
                        continue
                    seen_paths.add(resolved)
                    file_candidates.setdefault((source["category"], raw_directory), []).append({
                        "path": resolved, "stat": stat, "info": info,
                    })
                    item_id = hashlib.sha256(f"{source['category']}|{resolved}".encode("utf-8")).hexdigest()[:24]
                    live_item_ids.add(item_id)
                    output_center_index[item_id] = {
                        **output_center_index.get(item_id, {}),
                        "output_path": resolved,
                        "category": source["category"],
                    }
                    light_items.append({
                        "id": item_id,
                        "path": resolved,
                        "file_name": resolved.name,
                        "processing_type": source["category"],
                        "processing_label": source["label"],
                        "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    })
        # Missing cards require durable, explicit Result identity. Never infer a
        # Result from a directory entry, filename or neighbouring task/time.
        directories = {Path(p).resolve(): source for source in sources for p in source["paths"]}
        directory_keys = {os.path.normcase(str(path)): (path, source) for path, source in directories.items()}
        seen_keys = {os.path.normcase(str(path)) for path in seen_paths}
        batch_path_keys = {
            child["output_path"]: str(Path(child["output_path"]).resolve())
            for batch in batches for child in batch["items"] if child["output_path"]
        }
        batch_paths = set(batch_path_keys.values())
        registries = [task_registry, shared_task_registry or {}]
        path_scopes = {}
        removal_facts = [record for record in (shared_task_registry or {}).values() if record.get("record_kind") == "output_center_hidden"]
        removed_results = {record.get("removed_result_id") for record in removal_facts if record.get("removed_result_id")}
        active_result_paths = set()
        for registry in registries:
            for record in registry.values():
                if not isinstance(record, Mapping):
                    continue
                if record.get("record_kind") == "output_center_hidden":
                    continue  # A removal cannot assign the new Result's scope or details.
                result = record.get("result")
                if hasattr(result, "to_dict"):
                    result = result.to_dict()
                fact = {**(result if isinstance(result, Mapping) else {}), **record}
                raw_path = fact.get("output_path") or fact.get("result_file")
                if fact.get("result_id") in removed_results:
                    continue
                if raw_path and fact.get("result_id") and str(fact.get("status") or "").upper() == "COMPLETED":
                    active_result_paths.add(os.path.normcase(str(raw_path)))
                if raw_path:
                    path_scopes[os.path.normcase(str(raw_path))] = output_record_scope(fact)
                if (not raw_path or not fact.get("result_id") or not fact.get("task_id")
                    or not fact.get("output_sha256") or fact.get("batch_id")
                    or str(fact.get("status") or "").upper() != "COMPLETED"):
                    continue
                try:
                    candidate = Path(str(raw_path))
                    directory_entry = directory_keys.get(os.path.normcase(str(candidate.parent)))
                    if (not candidate.is_absolute() or not directory_entry
                        or os.path.normcase(str(candidate)) in seen_keys
                        or candidate.suffix.lower() not in ALLOWED_EXTENSIONS
                        or _is_non_product_output_name(candidate.name)):
                        continue
                    directory, source = directory_entry
                    resolved = directory / candidate.name
                    if str(resolved) in batch_paths or resolved.exists():
                        continue
                except (OSError, ValueError, RuntimeError):
                    continue
                seen_paths.add(resolved)
                seen_keys.add(os.path.normcase(str(resolved)))
                item_id = hashlib.sha256(f"{source['category']}|{resolved}".encode("utf-8")).hexdigest()[:24]
                live_item_ids.add(item_id)
                output_center_index[item_id] = {"output_path": resolved, "category": source["category"]}
                light_items.append({
                    "id": item_id, "path": resolved, "file_name": resolved.name,
                    "processing_type": source["category"], "processing_label": source["label"],
                    "created_at": str(fact.get("created_at") or ""), "_missing": fact,
                })
        for stale_item_id in set(output_center_index) - live_item_ids:
            output_center_index.pop(stale_item_id, None)

        # Group before pagination, so a page boundary cannot split a batch.
        # Only persisted Batch Item -> Result paths can claim a file.
        by_path = {str(item["path"]): item for item in light_items}
        output_center_batch_bindings.clear()
        hidden = {str(record.get("item_id") or "") for record in removal_facts
                  if str(record.get("item_id") or "").startswith("batch_item:") or not record.get("removed_result_id")
                  or os.path.normcase(str(record.get("output_path") or "")) not in active_result_paths}
        suppressed_paths = set()
        claims: dict[str, list[dict[str, Any]]] = {}
        result_claims: dict[str, int] = {}
        for batch in batches:
            batch["_paths"] = set()
            for child in batch["items"]:
                if not child["output_path"] or not child["result_id"]:
                    continue
                path_key = batch_path_keys[child["output_path"]]
                if batch["id"] in hidden or output_child_record_id(child) in hidden:
                    suppressed_paths.add(path_key)
                    continue
                claims.setdefault(path_key, []).append(child)
                result_claims[child["result_id"]] = result_claims.get(child["result_id"], 0) + 1
        claimed_paths = {Path(path) for path in suppressed_paths if path not in claims}
        for batch in batches:
            for child in batch["items"]:
                if not child["output_path"] or not child["result_id"]:
                    continue
                path_key = batch_path_keys[child["output_path"]]
                if batch["id"] in hidden or output_child_record_id(child) in hidden:
                    continue
                candidate = by_path.get(path_key)
                if len(claims[path_key]) != 1 or result_claims[child["result_id"]] != 1:
                    child["binding_error"] = "批次中的 Result 文件关系存在冲突。"
                elif candidate and candidate["processing_type"] == batch["processing_type"]:
                    batch["_paths"].add(candidate["path"])
                    claimed_paths.add(candidate["path"])
                if candidate:
                    output_center_batch_bindings[candidate["id"]] = child
        light_items = [item for item in light_items if item["path"] not in claimed_paths and item["id"] not in hidden]
        for item in light_items:
            item["list_scope"] = path_scopes.get(os.path.normcase(str(item["path"])), "history")
        for batch in batches:
            # Suppress the listing only; persisted nine-field Result facts remain intact.
            remaining = [child for child in batch["items"] if output_child_record_id(child) not in hidden]
            if batch["id"] in hidden or not remaining:
                continue
            if len(remaining) != len(batch["items"]):
                batch = output_remaining_batch(batch, remaining)
                batch["_paths"] &= {Path(batch_path_keys[child["output_path"]]) for child in remaining if child["output_path"]}
            batch["list_scope"] = output_record_scope(batch)
            light_items.append(batch)
        scope_counts = {key: sum(i["list_scope"] == key for i in light_items) for key in ("current", "history")}
        if scope != "all":
            light_items = [item for item in light_items if item["list_scope"] == scope]
        light_items.sort(key=lambda item: item["created_at"], reverse=sort_order != "oldest")
        categories = [
            {
                "key": source["category"],
                "label": source["label"],
                "count": sum(1 for item in light_items if item["processing_type"] == source["category"]),
            }
            for source in sources
        ]
        categories = [item for item in categories if item["count"] > 0]
        normalized_category = str(category or "all").strip()
        filtered_items = light_items
        if normalized_category and normalized_category != "all":
            filtered_items = [item for item in filtered_items if item["processing_type"] == normalized_category]
        normalized_query = str(query or "").strip().casefold()
        if normalized_query:
            filtered_items = [
                item
                for item in filtered_items
                if normalized_query in item["file_name"].casefold()
                or normalized_query in item["processing_label"].casefold()
                or any(normalized_query in child["file_name"].casefold() for child in item.get("items", []))
            ]
        total_count = len(filtered_items)
        page_limit = None if limit is None else max(1, min(int(limit), 100))
        page_offset = max(0, int(offset))
        page_items = (
            filtered_items[page_offset:]
            if page_limit is None
            else filtered_items[page_offset:page_offset + page_limit]
        )
        next_offset = page_offset + len(page_items)
        selected_paths = {path for item in page_items for path in (item["_paths"] if item.get("card_type") == "batch" else {item["path"]})}
        return {
            "selected_paths": selected_paths,
            "scope_counts": scope_counts,
            "scope": scope,
            "item_scopes": {item["id"]: item["list_scope"] for item in page_items},
            "selected_files": {
                key: [item for item in candidates if item["path"] in selected_paths]
                for key, candidates in file_candidates.items()
            },
            "selected_batches": [item for item in page_items if item.get("card_type") == "batch"],
            "single_ids": {item["id"] for item in page_items if item.get("card_type") != "batch"},
            "missing_items": [item for item in page_items if item.get("_missing")],
            "categories": [{"key": "all", "label": "全部", "count": len(light_items)}, *categories],
            "total_count": total_count,
            "returned_count": len(page_items),
            "offset": page_offset,
            "limit": page_limit,
            "has_more": next_offset < total_count,
            "next_offset": next_offset if next_offset < total_count else None,
            "query": str(query or ""),
            "sort_order": sort_order,
            "category": normalized_category or "all",
            "skipped_unavailable_count": skipped_unavailable,
        }

    def build_output_center_snapshot(
        *,
        limit: int | None = None,
        offset: int = 0,
        query: str = "",
        sort_order: str = "newest",
        category: str = "all",
        scope: str = "all",
    ) -> dict[str, Any]:
        user_dirs = (output_center_user_dirs_provider or user_dirs_provider)()
        formal_root = Path(
            user_dirs.get("app_data_root")
            or Path(user_dirs.get("normal_output_dir") or ".").resolve().parent
        ).resolve()
        sources = output_center_sources(user_dirs)
        page = select_output_center_page(
            sources,
            batches=batch_views(shared_task_registry),
            limit=limit,
            offset=offset,
            query=query,
            sort_order=sort_order,
            category=category,
            scope=scope,
        )
        selected_paths = page["selected_paths"]
        try:
            thumbnail_cache_root = output_center_thumbnail_cache_root(user_dirs)
        except (OSError, ValueError, RuntimeError):
            thumbnail_cache_root = None
        # Missing cards already carry persisted Result facts; probe only live details.
        detail_paths = selected_paths.difference(item["path"] for item in page["missing_items"])
        active_records, result_records = (
            output_center_active_records(formal_root, detail_paths) if detail_paths else ({}, {})
        )
        # A removed historical claim cannot choose metadata for a new explicit binding.
        for item_id, child in output_center_batch_bindings.items():
            path = output_center_index[item_id]["output_path"]
            if path not in detail_paths or child.get("binding_error"):
                continue
            fact = (shared_task_registry or {}).get(child["task_id"]) or (shared_task_registry or {}).get(child["result_id"])
            if isinstance(fact, Mapping) and str(fact.get("task_id")) == child["task_id"] and str(fact.get("result_id")) == child["result_id"]:
                active_records[path] = fact
        items: list[dict[str, Any]] = []
        registries = [task_registry]
        if shared_task_registry is not None and shared_task_registry is not task_registry:
            registries.append(shared_task_registry)
        unavailable_result_ids = {
            str(record.get("result_id") or record_id)
            for registry in registries
            for record_id, record in registry.items()
            if isinstance(record, Mapping)
            and str(record.get("record_kind") or "") == "result"
            and record.get("result_available") is False
        }
        skipped_unavailable = len(unavailable_result_ids) + int(page["skipped_unavailable_count"])
        seen_paths: set[Path] = set()
        for source in sources:
            for raw_directory in source["paths"]:
                # Reuse this request's inventory. Only the selected page needs details.
                candidates = page["selected_files"].get((source["category"], raw_directory), [])
                for candidate in candidates:
                    item_id = ""
                    try:
                        resolved = candidate["path"]
                        if resolved not in selected_paths or resolved in seen_paths:
                            continue
                        item_id = hashlib.sha256(f"{source['category']}|{resolved}".encode("utf-8")).hexdigest()[:24]
                        stat, info = candidate["stat"], candidate["info"]
                    except Exception:
                        if item_id:
                            output_center_index.pop(item_id, None)
                        skipped_unavailable += 1
                        continue
                    seen_paths.add(resolved)
                    try:
                        if thumbnail_cache_root is None:
                            raise RuntimeError("output center thumbnail cache is unavailable")
                        thumbnail = output_center_thumbnail_entry(resolved, user_dirs, cache_root=thumbnail_cache_root)
                        thumbnail_status = "cached" if Path(thumbnail["cache_path"]).is_file() else "not_cached"
                    except (OSError, ValueError, RuntimeError):
                        thumbnail = None
                        thumbnail_status = "unavailable"
                    record_meta = output_center_record_meta(active_records.get(resolved), formal_root)
                    source_path = record_meta.get("source_path")
                    compare_url = str(record_meta.get("compare_url") or "")
                    mapping_source = "task_registry" if source_path else ""
                    if source["category"] == "color_correction" and source_path is None:
                        source_path = find_managed_color_source(resolved, user_dirs)
                        if source_path is not None:
                            mapping_source = "unique_managed_intake_match"
                    unified_result = bool(
                        record_meta.get("result_id")
                        and record_meta.get("task_id")
                        and record_meta.get("feature_key")
                        and record_meta.get("result_file") == resolved
                    )
                    continue_eligibility = build_continue_eligibility(
                        record_meta=record_meta,
                        result_records=result_records,
                        unified_result=unified_result,
                        size_bytes=int(stat.st_size),
                        width=int(info["width"]),
                        height=int(info["height"]),
                        image_format=str(info["format"]),
                    )
                    continue_eligibility_version = hashlib.sha256(
                        (
                            f"{record_meta.get('result_id') or ''}|{record_meta.get('task_id') or ''}|"
                            f"{record_meta.get('feature_key') or ''}|{record_meta.get('registered_output_sha256') or ''}|"
                            f"{stat.st_size}|{stat.st_mtime_ns}|"
                            + "|".join(
                                f"{entry['key']}:{entry['history_status']}:{entry['status']}:{entry['repeatable']}"
                                for entry in continue_eligibility
                            )
                        ).encode("utf-8")
                    ).hexdigest()[:20]
                    output_center_index[item_id] = {
                        "output_path": resolved,
                        "source_path": source_path,
                        "category": source["category"],
                        "result_id": record_meta.get("result_id") or "",
                        "task_id": record_meta.get("task_id") or "",
                        "feature_key": record_meta.get("feature_key") or "",
                        "module_id": record_meta.get("module_id") or "",
                        "operation_id": record_meta.get("operation_id") or "",
                        "trace_id": record_meta.get("trace_id") or "",
                        "original_filename": record_meta.get("original_filename") or "",
                        "unified_result": unified_result,
                        "registered_output_sha256": record_meta.get("registered_output_sha256") or "",
                        "continue_eligibility": continue_eligibility,
                        "continue_eligibility_version": continue_eligibility_version,
                    }
                    color_auto_delivery_eligible = (
                        unified_result
                        and record_meta.get("result_action") == "ACCEPT_CORRECTED"
                        and record_meta.get("d3_final_action") == "ACCEPT_CORRECTED"
                        and record_meta.get("output_selected") == "CORRECTED_CANDIDATE"
                    )
                    color_human_delivery_eligible = (
                        unified_result
                        and record_meta.get("result_action") == "REVIEW_REQUIRED"
                        and record_meta.get("d3_final_action") == "REVIEW_REQUIRED"
                        and record_meta.get("output_selected") == "REVIEW_CANDIDATE"
                        and record_meta.get("result_review_status") == "confirmed"
                        and record_meta.get("delivery_acceptance_authority") == "HUMAN_CONFIRMED_REVIEW"
                    )
                    color_delivery_eligible = color_auto_delivery_eligible or color_human_delivery_eligible
                    base_delivery_eligible = (
                        color_delivery_eligible
                        if source["category"] == "color_correction"
                        else (
                            bool(record_meta.get("delivery_eligible"))
                            if unified_result and record_meta.get("delivery_eligible") is not None
                            else (
                                unified_result
                                or source["category"] != "local_retouch"
                                or bool(record_meta.get("result_id") and mapping_source == "task_registry")
                            )
                        )
                    )
                    output_center_index[item_id]["delivery_eligible_base"] = bool(base_delivery_eligible)
                    continue_processor_keys = [
                        entry["key"]
                        for entry in continue_eligibility
                        if entry["status"] == "AVAILABLE"
                    ]
                    items.append({
                        "id": item_id,
                        "file_name": resolved.name,
                        "processing_type": source["category"],
                        "processing_label": source["label"],
                        "result_id": record_meta.get("result_id") or "",
                        "task_id": record_meta.get("task_id") or "",
                        "batch_id": record_meta.get("batch_id") or "",
                        "batch_item_id": record_meta.get("batch_item_id") or "",
                        "source_id": record_meta.get("source_id") or "",
                        "feature_key": record_meta.get("feature_key") or "",
                        "module_id": record_meta.get("module_id") or "",
                        "operation_id": record_meta.get("operation_id") or "",
                        "trace_id": record_meta.get("trace_id") or "",
                        "unified_result": unified_result,
                        "delivery_eligible": bool(
                            base_delivery_eligible
                            and record_meta.get("delivery_eligibility_override") is not False
                        ),
                        "delivery_failure_code": (
                            record_meta.get("delivery_failure_code")
                            if record_meta.get("delivery_eligibility_override") is False
                            else ""
                        ),
                        "delivery_failure_reason": (
                            record_meta.get("delivery_failure_reason")
                            if record_meta.get("delivery_eligibility_override") is False
                            else ""
                        ),
                        "d3_final_action": record_meta.get("d3_final_action") or "",
                        "result_action": record_meta.get("result_action") or "",
                        "output_selected": record_meta.get("output_selected") or "",
                        "status": record_meta.get("status") or "completed",
                        "width": int(info["width"]),
                        "height": int(info["height"]),
                        "format": str(info.get("format") or resolved.suffix.lstrip(".")).upper(),
                        "size_bytes": int(stat.st_size),
                        "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                        "preview_url": f"/api/output-center/items/{item_id}/preview",
                        "thumbnail_url": (
                            f"/api/output-center/items/{item_id}/thumbnail"
                            f"?v={thumbnail['signature'][:16]}"
                        ) if thumbnail else "",
                        "thumbnail_status": thumbnail_status,
                        "source_preview_url": f"/api/output-center/items/{item_id}/source-preview" if source_path else "",
                        "compare_available": bool(source_path),
                        "compare_url": compare_url or (f"/outputs/compare?item={item_id}" if source_path else ""),
                        "mapping_source": mapping_source,
                        "review_status": record_meta.get("review_status") or "",
                        "available": True,
                        "continue_eligible": bool(continue_processor_keys),
                        "continue_processor_keys": continue_processor_keys,
                        "continue_eligibility_version": continue_eligibility_version,
                        "continue_unavailable_reason": (
                            ""
                            if continue_processor_keys
                            else "当前成品缺少完整 Result 来源关系，或超出目标处理器的输入限制。"
                        ),
                    })
        for missing in page["missing_items"]:
            fact = missing["_missing"]
            items.append({
                **{key: missing[key] for key in ("id", "file_name", "processing_type", "processing_label", "created_at")},
                "result_id": str(fact["result_id"]), "task_id": str(fact["task_id"]),
                "feature_key": str(fact.get("feature_key") or ""),
                "width": int(fact.get("width") or 0), "height": int(fact.get("height") or 0),
                "format": str(fact.get("format") or Path(missing["path"]).suffix.lstrip(".")).upper(),
                "size_bytes": 0, "available": False, "file_status": "MISSING",
                "availability_reason": "正式文件缺失。", "status": str(fact["status"]),
                "thumbnail_url": "", "thumbnail_status": "unavailable", "preview_url": "",
                "compare_available": False, "delivery_eligible": False, "continue_eligible": False,
                "continue_eligibility": [],
            })
        hydrated = {str(output_center_index[item["id"]]["output_path"]): item for item in items}
        items = [item for item in items if item["id"] in page["single_ids"]]
        for batch in page["selected_batches"]:
            children = []
            for child in batch["items"]:
                bound = hydrated.get(str(Path(child["output_path"]).resolve())) if child["output_path"] else None
                valid = (bound is not None and not child.get("binding_error")
                         and child["status"] == "COMPLETED" and bool(child["output_sha256"])
                         and bound["result_id"] == child["result_id"] and bound["task_id"] == child["task_id"])
                if valid:
                    try:
                        valid = _sha256_file(Path(child["output_path"])) == child["output_sha256"]
                    except OSError:
                        valid = False
                if valid:
                    output_center_index[bound["id"]]["batch_bound"] = True
                    output_center_index[bound["id"]]["registered_output_sha256"] = child["output_sha256"]
                    child = {**bound, **child, "source_file_name": child["file_name"],
                             "file_name": bound["file_name"], "output_file_name": bound["file_name"], "available": True}
                elif child["status"] == "COMPLETED":
                    child = {**child, "availability_reason": child.get("binding_error") or "正式文件缺失或与登记的 Result / SHA 不一致。"}
                child["record_id"] = output_child_record_id(child)
                child.setdefault("id", child["record_id"])
                child["file_status"] = "MISSING" if child["status"] == "COMPLETED" and not child["available"] and output_file_missing(child["output_path"]) else "PRESENT" if child["available"] else "UNAVAILABLE"
                child["list_scope"] = batch["list_scope"]
                children.append(child)
            batch = {key: val for key, val in batch.items() if key != "_paths"}
            batch["items"] = children
            batch["summary"]["unavailable"] = sum(i["status"] == "COMPLETED" and not i["available"] for i in children)
            items.append(batch)
        items.sort(key=lambda item: item["created_at"], reverse=sort_order != "oldest")
        for item in items:
            item["list_scope"] = page["item_scopes"][item["id"]]
        return {
            "items": items,
            "scope": page["scope"],
            "scope_counts": page["scope_counts"],
            "categories": page["categories"],
            "count": page["total_count"],
            "total_count": page["total_count"],
            "returned_count": len(items),
            "offset": page["offset"],
            "limit": page["limit"],
            "has_more": page["has_more"],
            "next_offset": page["next_offset"],
            "query": page["query"],
            "sort_order": page["sort_order"],
            "category": page["category"],
            "skipped_unavailable_count": skipped_unavailable,
            "scan_scope": "formal_contract_directories_only",
            "recursive_scan": False,
        }

    def smart_delivery_root() -> Path:
        user_dirs = (output_center_user_dirs_provider or user_dirs_provider)()
        app_root = Path(
            user_dirs.get("app_data_root")
            or Path(user_dirs.get("normal_output_dir") or ".").resolve().parent
        ).resolve()
        output_root = (app_root / "输出").resolve()
        delivery_root = (output_root / "智能交付").resolve()
        if delivery_root.parent != output_root:
            raise HTTPException(
                status_code=500,
                detail={"code": "SMART_DELIVERY_ROOT_INVALID", "message": "智能交付目录安全校验失败。"},
            )
        return delivery_root

    def prune_smart_delivery_plans() -> None:
        now = now_provider()
        expired = [
            plan_id
            for plan_id, plan in smart_delivery_plan_registry.items()
            if float(plan.get("expires_at") or 0) <= now
        ]
        for plan_id in expired:
            smart_delivery_plan_registry.pop(plan_id, None)
        while len(smart_delivery_plan_registry) > 32:
            oldest = min(
                smart_delivery_plan_registry,
                key=lambda key: float(smart_delivery_plan_registry[key].get("created_at_epoch") or 0),
            )
            smart_delivery_plan_registry.pop(oldest, None)

    def normalize_smart_delivery_rules(raw: Mapping[str, Any] | None) -> dict[str, Any]:
        source = raw if isinstance(raw, Mapping) else {}
        retired_fields = {
            "base_name",
            "content_names",
            "prefix",
            "suffix",
            "find_text",
            "replace_text",
            "sequence_enabled",
            "sequence_start",
            "sequence_padding",
            "date_enabled",
            "template",
        }
        has_retired_rule = any(
            key in source and source.get(key) not in (None, "", False, {}, [])
            for key in retired_fields
        )
        base_mode = str(source.get("base_mode") or "original").strip()
        if base_mode != "original" or has_retired_rule:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "DELIVERY_NAMING_RULES_RETIRED",
                    "message": "独立文件命名规则已经退场；公共交付仅保留源成品文件名并执行安全去重。",
                },
            )
        return {"base_mode": "original"}
    def windows_path_utf16_units(path: Path) -> int:
        return len(str(path).encode("utf-16-le")) // 2

    def windows_filename_key(value: str) -> str:
        return unicodedata.normalize("NFC", str(value or "")).casefold()

    def result_id_is_registered(result_id: str) -> bool:
        if load_delivery_eligibility(result_id) is not None:
            return True
        records = shared_task_registry if shared_task_registry is not None else task_registry
        return any(
            isinstance(record, Mapping) and str(record.get("result_id") or "") == result_id
            for record in list(records.values())
        )

    def cached_output_sha256(path: Path) -> str:
        """Reuse a plan hash while the file's stat identity is unchanged.

        Preflight and the execute-time refresh hash the same files back to back. The
        delivery copy re-verifies the real bytes against the registered SHA, so a
        cached plan hash can never let changed content reach a Delivery.
        """
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ino)
        digest = smart_delivery_hash_cache.get(key)
        if digest is None:
            digest = _sha256_file(path)
            smart_delivery_hash_cache[key] = digest
            while len(smart_delivery_hash_cache) > 512:
                smart_delivery_hash_cache.pop(next(iter(smart_delivery_hash_cache)))
        return digest

    def source_still_matches(path: Path, expected_sha256: str) -> bool:
        try:
            return path.is_file() and _sha256_file(path) == expected_sha256
        except OSError:
            return False

    def reconcile_smart_delivery_eligibility(
        plan: Mapping[str, Any],
        *,
        allow_restore: bool,
    ) -> None:
        entries = [entry for entry in list(plan.get("entries") or []) if isinstance(entry, Mapping)]
        entries_by_item_id = {str(entry.get("item_id") or ""): entry for entry in entries}
        invalidated_result_ids: set[str] = set()
        for issue in list(plan.get("issues") or []):
            if not isinstance(issue, Mapping):
                continue
            code = str(issue.get("code") or "")
            if code not in SMART_DELIVERY_ELIGIBILITY_INVALIDATING_CODES:
                continue
            entry = entries_by_item_id.get(str(issue.get("item_id") or ""), {})
            result_id = str(issue.get("result_id") or entry.get("source_result_id") or "")
            if not result_id:
                continue
            invalidated_result_ids.add(result_id)
            persist_delivery_eligibility(
                result_id,
                eligible=False,
                code=code,
                reason=str(issue.get("message") or "当前 Result 不满足交付条件。"),
                registered_output_sha256=str(entry.get("_registered_output_sha256") or ""),
                current_output_sha256=str(entry.get("_current_output_sha256") or ""),
            )

        if not allow_restore or not bool(plan.get("ready")):
            return
        for entry in entries:
            result_id = str(entry.get("source_result_id") or "")
            registered_sha256 = str(entry.get("_registered_output_sha256") or "").lower()
            current_sha256 = str(entry.get("_current_output_sha256") or "").lower()
            if (
                result_id
                and result_id not in invalidated_result_ids
                and registered_sha256
                and current_sha256 == registered_sha256
            ):
                persist_delivery_eligibility(
                    result_id,
                    eligible=True,
                    registered_output_sha256=registered_sha256,
                    current_output_sha256=current_sha256,
                )

    def build_smart_delivery_plan(
        raw_item_ids: Any,
        raw_result_ids: Any,
        raw_rules: Mapping[str, Any] | None,
        *,
        store: bool,
    ) -> dict[str, Any]:
        item_mode = isinstance(raw_item_ids, list)
        result_mode = isinstance(raw_result_ids, list)
        if item_mode == result_mode:
            raise HTTPException(
                status_code=400,
                detail={"code": "SMART_DELIVERY_SELECTION_INVALID", "message": "请选择正式输出中心成品。"},
            )
        selection_values = raw_item_ids if item_mode else raw_result_ids
        selection_ids = [str(value or "").strip() for value in selection_values]
        if not selection_ids or any(not value for value in selection_ids):
            raise HTTPException(
                status_code=400,
                detail={"code": "SMART_DELIVERY_SELECTION_EMPTY", "message": "至少选择一份真实成品。"},
            )
        if len(selection_ids) > SMART_DELIVERY_MAX_ITEMS:
            raise HTTPException(
                status_code=400,
                detail={"code": "SMART_DELIVERY_SELECTION_TOO_LARGE", "message": "单次交付最多选择100份成品。"},
            )

        rules = normalize_smart_delivery_rules(raw_rules)
        snapshot = build_output_center_snapshot()
        snapshot_items = [
            *snapshot["items"],
            # Batch Results are nested under their batch card. Only a child whose file
            # is present and SHA-bound to its Result is a real output item.
            *(
                child
                for item in snapshot["items"]
                for child in (item.get("items") or [])
                if child.get("available") and child.get("id") in output_center_index
            ),
        ]
        snapshot_by_id = {item["id"]: item for item in snapshot_items}
        snapshot_by_result_id = {
            item["result_id"]: item
            for item in snapshot_items
            if item.get("unified_result") and item.get("result_id")
        }
        if result_mode:
            selected_items = []
            for result_id in selection_ids:
                public_item = snapshot_by_result_id.get(result_id)
                if public_item is None:
                    if result_id_is_registered(result_id):
                        # Only a real Result loses eligibility; arbitrary request ids
                        # must not create persistent facts from a read-only check.
                        persist_delivery_eligibility(
                            result_id,
                            eligible=False,
                            code="UNIFIED_RESULT_NOT_FOUND",
                            reason="正式结果不存在或不满足统一结果合同。",
                        )
                    raise HTTPException(
                        status_code=404,
                        detail={"code": "UNIFIED_RESULT_NOT_FOUND", "message": "正式结果不存在或不满足统一结果合同。"},
                    )
                selected_items.append(public_item)
            item_ids = [item["id"] for item in selected_items]
            result_ids = selection_ids
            selection_mode = "result_ids"
        else:
            item_ids = selection_ids
            result_ids = []
            selection_mode = "item_ids"

        delivery_root = smart_delivery_root()
        issues: list[dict[str, Any]] = []
        entries: list[dict[str, Any]] = []
        seen_item_ids: set[str] = set()
        seen_names: dict[str, str] = {}

        for item_id in item_ids:
            if item_id in seen_item_ids:
                issues.append({
                    "code": "DUPLICATE_SELECTION",
                    "item_id": item_id,
                    "file_name": "",
                    "message": "同一份源成品不能重复加入交付清单。",
                })
                continue
            seen_item_ids.add(item_id)
            public_item = snapshot_by_id.get(item_id)
            if public_item is None:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "OUTPUT_ITEM_NOT_FOUND", "message": "所选成品已不存在，请返回输出中心重新选择。"},
                )

            source_result_id = str(public_item.get("result_id") or "")
            source_task_id = str(public_item.get("task_id") or "")
            source_feature_key = str(public_item.get("feature_key") or "")
            source_module_id = str(public_item.get("module_id") or "")
            source_operation_id = str(public_item.get("operation_id") or "")
            source_trace_id = str(public_item.get("trace_id") or "")
            source_processing_type = str(public_item.get("processing_type") or "")
            source_mapping = str(public_item.get("mapping_source") or "")
            indexed = require_output_center_item(item_id)
            base_delivery_eligible = bool(indexed.get("delivery_eligible_base"))
            if source_processing_type == "color_correction" and not base_delivery_eligible:
                issues.append({
                    "code": "COLOR_RESULT_NOT_ACCEPTED",
                    "item_id": item_id,
                    "result_id": source_result_id,
                    "file_name": str(public_item.get("file_name") or ""),
                    "message": "颜色结果尚未获得 D3 ACCEPT_CORRECTED 权限，不能交付。",
                })
            elif source_result_id and not base_delivery_eligible:
                issues.append({
                    "code": "RESULT_NOT_DELIVERABLE",
                    "item_id": item_id,
                    "result_id": source_result_id,
                    "file_name": str(public_item.get("file_name") or ""),
                    "message": "当前 Result 未获得正式交付资格。",
                })
            if source_processing_type == "local_retouch" and (
                not source_result_id
                or source_mapping != "task_registry"
                or (result_mode and not public_item.get("unified_result"))
            ):
                issues.append({
                    "code": "UNIFIED_RESULT_REQUIRED",
                    "item_id": item_id,
                    "result_id": source_result_id,
                    "file_name": str(public_item.get("file_name") or ""),
                    "message": "瑕疵修复成品缺少完整的统一正式结果引用，不能交付。",
                })

            source_path = Path(indexed["output_path"]).resolve()
            try:
                source_stat = source_path.stat()
                source_size, source_mtime_ns = int(source_stat.st_size), int(source_stat.st_mtime_ns)
            except OSError:
                # Locked, permission-denied or removed after lookup: block, never 500.
                source_size, source_mtime_ns = 0, 0
                issues.append({
                    "code": "DELIVERY_SOURCE_UNREADABLE",
                    "item_id": item_id,
                    "result_id": source_result_id,
                    "file_name": source_path.name,
                    "message": "源成品文件当前无法读取，请确认文件未被占用或移动后重新检查。",
                })
            registered_output_sha256 = str(indexed.get("registered_output_sha256") or "").lower()
            try:
                current_output_sha256 = cached_output_sha256(source_path).lower()
            except OSError:
                current_output_sha256 = ""
            if source_result_id and (
                not registered_output_sha256
                or current_output_sha256 != registered_output_sha256
            ):
                issues.append({
                    "code": RESULT_IDENTITY_MISMATCH,
                    "item_id": item_id,
                    "result_id": source_result_id,
                    "file_name": str(public_item.get("file_name") or source_path.name),
                    "message": "当前成品内容与 Result 登记身份不一致，不能交付。",
                })
            source_name = source_path.name
            source_name_issues = smart_delivery_name_issues(source_path.stem, source_path.suffix)
            for code, message in source_name_issues:
                issues.append({"code": code, "item_id": item_id, "file_name": source_name, "message": message})

            destination_path = (delivery_root / source_name).resolve()
            if not source_name_issues:
                collision_sequence = 2
                while destination_path.exists() or windows_filename_key(destination_path.name) in seen_names:
                    destination_path = (
                        delivery_root / f"{source_path.stem}_{collision_sequence:02d}{source_path.suffix}"
                    ).resolve()
                    collision_sequence += 1
            destination_name = destination_path.name

            if not source_name_issues:
                for code, message in smart_delivery_name_issues(destination_path.stem, destination_path.suffix):
                    issues.append({"code": code, "item_id": item_id, "file_name": destination_name, "message": message})
            name_key = windows_filename_key(destination_name)
            if name_key in seen_names:
                issues.append({
                    "code": "DUPLICATE_FINAL_NAME",
                    "item_id": item_id,
                    "file_name": destination_name,
                    "message": "批次内存在重复的交付文件名。",
                })
            else:
                seen_names[name_key] = item_id
            if destination_path.parent != delivery_root:
                issues.append({
                    "code": "DELIVERY_PATH_ESCAPE",
                    "item_id": item_id,
                    "file_name": destination_name,
                    "message": "交付文件名超出安全目录边界。",
                })
            if windows_path_utf16_units(destination_path) > WINDOWS_SAFE_PATH_UTF16_UNITS:
                issues.append({
                    "code": "DELIVERY_PATH_TOO_LONG",
                    "item_id": item_id,
                    "file_name": destination_name,
                    "message": "交付路径过长，系统不会静默缩短文件名。",
                })

            entries.append({
                "item_id": item_id,
                "source_result_id": source_result_id,
                "source_task_id": source_task_id,
                "source_feature_key": source_feature_key,
                "source_module_id": source_module_id,
                "source_operation_id": source_operation_id,
                "source_trace_id": source_trace_id,
                "source_processing_type": source_processing_type,
                "source_file_name": source_name,
                "source_filename": source_name,
                "suggested_filename": source_name,
                "final_filename": destination_name,
                "naming_source": "SOURCE_RESULT_FILENAME",
                "naming_evidence": [{
                    "source": "SOURCE_RESULT_FILENAME",
                    "value": source_path.stem,
                    "available": True,
                    "reliable": True,
                    "accepted": True,
                }],
                "delivery_file_name": destination_name,
                "content_name": "",
                "content_name_source": "",
                "_provenance_boundary": "VERIFIED_SOURCE_RESULT_FILENAME",
                "processing_label": public_item["processing_label"],
                "preview_url": public_item["preview_url"],
                "_source_path": source_path,
                "_destination_path": destination_path,
                "_source_size": source_size,
                "_source_mtime_ns": source_mtime_ns,
                "_registered_output_sha256": registered_output_sha256,
                "_current_output_sha256": current_output_sha256,
            })

        signature_payload = {
            "selection_mode": selection_mode,
            "item_ids": item_ids,
            "result_ids": result_ids,
            "rules": rules,
            "entries": [
                {
                    "item_id": entry["item_id"],
                    "source_result_id": entry["source_result_id"],
                    "source_task_id": entry["source_task_id"],
                    "source_feature_key": entry["source_feature_key"],
                    "source_processing_type": entry["source_processing_type"],
                    "delivery_file_name": entry["delivery_file_name"],
                    "source_size": entry["_source_size"],
                    "source_mtime_ns": entry["_source_mtime_ns"],
                    "registered_output_sha256": entry["_registered_output_sha256"],
                    "current_output_sha256": entry["_current_output_sha256"],
                }
                for entry in entries
            ],
        }
        signature = hashlib.sha256(
            json.dumps(signature_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        created_epoch = now_provider()
        plan = {
            "plan_id": uuid.uuid4().hex,
            "selection_mode": selection_mode,
            "item_ids": item_ids,
            "result_ids": result_ids,
            "rules": rules,
            "entries": entries,
            "issues": issues,
            "ready": not issues and len(entries) == len(item_ids),
            "signature": signature,
            "created_at_epoch": created_epoch,
            "expires_at": created_epoch + SMART_DELIVERY_PLAN_TTL_SECONDS,
            "delivery_location_label": "正式目录 / 输出 / 智能交付",
        }
        if store:
            reconcile_smart_delivery_eligibility(plan, allow_restore=True)
            prune_smart_delivery_plans()
            smart_delivery_plan_registry[plan["plan_id"]] = plan
        return plan
    def public_smart_delivery_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "plan_id": plan["plan_id"],
            "ready": bool(plan["ready"]),
            "item_count": len(plan["entries"]),
            "delivery_location_label": plan["delivery_location_label"],
            "issues": list(plan["issues"]),
            "items": [
                {
                    "item_id": entry["item_id"],
                    "source_result_id": entry["source_result_id"],
                    "result_id": entry["source_result_id"],
                    "task_id": entry["source_task_id"],
                    "feature_key": entry["source_feature_key"],
                    "module_id": entry["source_module_id"],
                    "operation_id": entry["source_operation_id"],
                    "trace_id": entry["source_trace_id"],
                    "source_processing_type": entry["source_processing_type"],
                    "source_file_name": entry["source_file_name"],
                    "source_filename": entry["source_filename"],
                    "suggested_filename": entry["suggested_filename"],
                    "final_filename": entry["final_filename"],
                    "naming_source": entry["naming_source"],
                    "naming_evidence": entry["naming_evidence"],
                    "delivery_file_name": entry["delivery_file_name"],
                    "content_name": entry["content_name"],
                    "content_name_source": entry["content_name_source"],
                    "processing_label": entry["processing_label"],
                    "preview_url": entry["preview_url"],
                }
                for entry in plan["entries"]
            ],
        }

    def copy_delivery_item(
        source_path: Path,
        destination_path: Path,
        *,
        registered_output_sha256: str,
    ) -> dict[str, Any]:
        published_path, integrity = publish_verified_file_copy_no_overwrite(
            source_path,
            [destination_path],
            expected_sha256=registered_output_sha256,
        )
        if published_path.resolve() != destination_path.resolve():
            raise RuntimeError("交付发布路径与预检目标不一致。")
        return {
            "registered_output_sha256": str(integrity["registered_output_sha256"]),
            "source_sha256": str(integrity["source_sha256"]),
            "delivery_sha256": str(integrity["delivery_sha256"]),
            "source_unchanged": bool(integrity["source_unchanged"]),
            "size_bytes": int(integrity["size_bytes"]),
        }

    def feedback_package_url(token: str) -> str:
        return f"/api/image-compression/feedback-package/{token}"

    def validate_registered_feedback_package_file(
        record: Mapping[str, Any],
        package: Mapping[str, Any],
        package_path: Path,
        *,
        token_item: Mapping[str, Any] | None = None,
    ) -> str:
        path = package_path.resolve()
        registered_path = Path(str(package.get("display_path") or package.get("feedback_package_path") or "")).resolve()
        function_dir = Path(record["output_dir"]).resolve()
        effective_root = Path(record["effective_output_root"]).resolve()
        if (
            path != registered_path
            or path.parent != function_dir
            or effective_root not in function_dir.parents
            or path.suffix.lower() != ".zip"
        ):
            raise HTTPException(
                status_code=403,
                detail={"code": "FEEDBACK_PACKAGE_PATH_INVALID", "message": "测试反馈包登记路径安全校验失败。"},
            )
        if not path.exists() or not path.is_file():
            raise HTTPException(
                status_code=404,
                detail={"code": "FEEDBACK_PACKAGE_FILE_MISSING", "message": "测试反馈包文件已不存在，请重新生成。"},
            )
        if not zipfile.is_zipfile(path):
            raise HTTPException(
                status_code=409,
                detail={"code": "FEEDBACK_PACKAGE_FILE_INVALID", "message": "测试反馈包文件已损坏，请重新生成。"},
            )
        actual_sha256 = _sha256_file(path)
        expected_sha256 = str(package.get("package_sha256") or package.get("feedback_package_sha256") or "")
        token_sha256 = str(token_item.get("sha256") or "") if token_item is not None else actual_sha256
        if not expected_sha256 or actual_sha256 != expected_sha256 or actual_sha256 != token_sha256:
            raise HTTPException(
                status_code=409,
                detail={"code": "FEEDBACK_PACKAGE_SHA_MISMATCH", "message": "测试反馈包完整性校验失败，请重新生成。"},
            )
        return actual_sha256

    def register_feedback_package(
        record: dict[str, Any],
        package_path: Path,
        *,
        package_id: str,
        output_stem: str,
        package_sha256: str,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        previous_token = str(record.get("feedback_package_token") or "")
        if previous_token:
            previous_item = token_registry.pop(previous_token, None)
            if (
                previous_item
                and previous_item.get("role") == "feedback_package"
                and previous_item.get("expires_at", 0) <= now_provider()
            ):
                expired_feedback_tokens.add(previous_token)
        package_path = package_path.resolve()
        token = issue_token(
            package_path,
            role="feedback_package",
            filename=package_path.name,
            task_id=record["task_id"],
            sha256=package_sha256,
        )
        token_item = token_registry[token]
        created_at_value = created_at or datetime.fromtimestamp(now_provider(), tz=timezone.utc).isoformat()
        expires_at_value = datetime.fromtimestamp(token_item["expires_at"], tz=timezone.utc).isoformat()
        feedback_package = {
            "task_id": record["task_id"],
            "package_name": package_path.name,
            "package_size_bytes": package_path.stat().st_size,
            "package_sha256": package_sha256,
            "download_url": feedback_package_url(token),
            "display_path": str(package_path),
            "function_directory_path": str(package_path.parent),
            "created_at": created_at_value,
            "expires_at": expires_at_value,
            "can_open_folder": True,
            "feedback_package_id": package_id,
            "feedback_package_version": "hdde.image-compression-feedback.v1",
            "feedback_package_path": str(package_path),
            "feedback_package_sha256": package_sha256,
            "output_stem": output_stem,
            "source_image_included": False,
            "output_image_included": False,
        }
        record["feedback_package"] = feedback_package
        record["feedback_package_token"] = token
        return feedback_package

    def require_feedback_package_token(token: str) -> tuple[dict[str, Any], Path]:
        raw_token = str(token or "")
        prune_tokens()
        if raw_token in expired_feedback_tokens:
            raise HTTPException(
                status_code=410,
                detail={"code": "FEEDBACK_PACKAGE_TOKEN_EXPIRED", "message": "测试反馈包下载链接已过期，请重新生成。"},
            )
        item = token_registry.get(raw_token)
        if not item or item.get("role") != "feedback_package":
            raise HTTPException(
                status_code=404,
                detail={"code": "FEEDBACK_PACKAGE_TOKEN_NOT_FOUND", "message": "测试反馈包下载链接无效。"},
            )
        task_id = str(item.get("task_id") or "")
        record = task_registry.get(task_id)
        package = record.get("feedback_package") if record else None
        if not record or not isinstance(package, Mapping) or record.get("feedback_package_token") != raw_token:
            raise HTTPException(
                status_code=403,
                detail={"code": "FEEDBACK_PACKAGE_TASK_MISMATCH", "message": "测试反馈包链接与当前登记任务不一致。"},
            )
        path = Path(item["path"]).resolve()
        validate_registered_feedback_package_file(record, package, path, token_item=item)
        return item, path

    def output_settings() -> dict[str, str]:
        configured = dict(output_settings_provider() or {}) if output_settings_provider else {}
        user_dirs = user_dirs_provider()
        fallback = Path(
            user_dirs.get("image_compression_output_dir")
            or (Path(user_dirs["normal_output_dir"]).resolve().parent / "图片压缩")
        ).resolve()
        built_in = str(configured.get("built_in_default_root") or fallback)
        saved = str(configured.get("saved_default_root") or built_in)
        return {"built_in_default_root": built_in, "saved_default_root": saved}

    def color_output_settings() -> dict[str, str]:
        if color_output_settings_provider is not None:
            configured = dict(color_output_settings_provider() or {})
            built_in = str(configured.get("built_in_default_root") or "")
            saved = str(configured.get("saved_default_root") or built_in)
            if built_in and saved:
                return {"built_in_default_root": built_in, "saved_default_root": saved}
        return output_settings()

    def validate_output_root(value: str, *, source: str) -> dict[str, Any]:
        raw = str(value or "").strip().strip('"').strip()
        if not raw or "\x00" in raw:
            raise HTTPException(status_code=400, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": "输出目录为空或包含非法字符。"})
        normalized_parts = raw.replace("\\", "/").split("/")
        if ".." in normalized_parts:
            raise HTTPException(status_code=400, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": "输出目录不得包含路径穿越片段。"})
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            raise HTTPException(status_code=400, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": "输出目录必须为绝对目录。"})
        checked = dict(output_dir_validator(raw) or {}) if output_dir_validator else {}
        if output_dir_validator:
            if not checked.get("valid"):
                raise HTTPException(status_code=400, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": str(checked.get("message") or "输出目录不可用。")})
            target = Path(str(checked.get("normalized_path") or raw)).resolve()
        else:
            try:
                target = candidate.resolve()
                target.mkdir(parents=True, exist_ok=True)
                if not target.is_dir():
                    raise OSError("目标不是目录")
                probe = target / f".hdde_compression_write_test_{uuid.uuid4().hex}.tmp"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
            except Exception as exc:
                raise HTTPException(status_code=400, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": f"输出目录不可写：{exc}"}) from exc
            checked = {"valid": True, "writable": True, "normalized_path": str(target)}
        if not target.exists() or not target.is_dir():
            raise HTTPException(status_code=400, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": "输出路径不是可用目录。"})
        for directory_name in FUNCTION_DIRECTORY_BY_MODE.values():
            directory = (target / directory_name).resolve()
            if target not in directory.parents:
                raise HTTPException(status_code=500, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": "固定功能目录安全校验失败。"})
            directory.mkdir(parents=True, exist_ok=True)
            if not directory.is_dir():
                raise HTTPException(status_code=400, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": f"固定功能目录不可用：{directory_name}。"})
        return {**checked, "valid": True, "writable": True, "normalized_path": str(target), "source": source}

    def validate_color_output_root(value: str, *, source: str) -> dict[str, Any]:
        raw = str(value or "").strip().strip('"').strip()
        if not raw or "\x00" in raw or ".." in raw.replace("\\", "/").split("/"):
            raise HTTPException(status_code=400, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": "颜色校正输出目录为空或包含非法路径片段。"})
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            raise HTTPException(status_code=400, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": "颜色校正输出目录必须为绝对路径。"})
        checked = dict(output_dir_validator(raw) or {}) if output_dir_validator else {}
        if output_dir_validator:
            if not checked.get("valid"):
                raise HTTPException(status_code=400, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": str(checked.get("message") or "颜色校正输出目录不可用。")})
            target = Path(str(checked.get("normalized_path") or raw)).resolve()
        else:
            target = candidate.resolve()
            try:
                target.mkdir(parents=True, exist_ok=True)
                probe = target / f".hdde_color_write_test_{uuid.uuid4().hex}.tmp"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
            except Exception as exc:
                raise HTTPException(status_code=400, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": f"颜色校正输出目录不可写：{exc}"}) from exc
            checked = {"valid": True, "writable": True, "normalized_path": str(target)}
        if not target.exists() or not target.is_dir():
            raise HTTPException(status_code=400, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": "颜色校正输出路径不是可用目录。"})
        return {**checked, "valid": True, "writable": True, "normalized_path": str(target), "source": source}

    def effective_output_root(payload: Mapping[str, Any]) -> dict[str, Any]:
        current = str(payload.get("current_task_output_root") or "").strip()
        settings = output_settings()
        selected = current or settings["saved_default_root"]
        return validate_output_root(selected, source="current_task" if current else "saved_default")

    def effective_color_output_root(payload: Mapping[str, Any]) -> dict[str, Any]:
        current = str(payload.get("current_task_output_root") or "").strip()
        settings = color_output_settings()
        selected = current or settings["saved_default_root"]
        return validate_color_output_root(selected, source="current_task" if current else "saved_default")

    def function_output_dir(mode: str, root: Path) -> Path:
        root = root.resolve()
        directory_name = FUNCTION_DIRECTORY_BY_MODE.get(mode)
        if not directory_name:
            raise HTTPException(status_code=400, detail="不支持的压缩能力模式。")
        target = (root / directory_name).resolve()
        if root not in target.parents:
            raise HTTPException(status_code=500, detail="压缩输出目录安全校验失败。")
        target.mkdir(parents=True, exist_ok=True)
        return target

    def finalize_readable_output(
        result,
        *,
        source: Mapping[str, Any],
        request: Mapping[str, Any],
        task_id: str,
        root: Path,
        function_dir: Path,
        now_value: float,
    ) -> tuple[Path, Path | None]:
        del request, task_id, root
        output_path = Path(result.output_path) if result.output_path else None
        if not result.output_created or output_path is None or not output_path.is_file():
            return function_dir, output_path
        source_name = str(source.get("filename") or output_path.name)
        moment = datetime.fromtimestamp(now_value)
        expected_dimensions = result.output_dimensions or {}

        def verify_private(data: bytes) -> dict[str, Any]:
            with Image.open(io.BytesIO(data)) as opened:
                opened.load()
                verified = {
                    "format": "JPEG" if opened.format == "JPG" else str(opened.format or "").upper(),
                    "dimensions": {"width": opened.width, "height": opened.height},
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size_bytes": len(data),
                }
            if verified["format"] != result.output_format or verified["dimensions"] != expected_dimensions:
                raise RuntimeError("压缩私有成品验证失败：输出格式或尺寸与任务结果不一致。")
            return verified

        while True:
            final_path = build_output_path(
                function_dir,
                source_name,
                FEATURE_COMPRESSION,
                output_path.suffix,
                trusted_original_filename=source_name,
                moment=moment,
            )
            try:
                final_path, output_metadata, verified = publish_image_file_with_metadata(
                    output_path,
                    final_path,
                    source_path=Path(str(source["path"])),
                    normalize_orientation=False,
                    verify_private=verify_private,
                )
                break
            except FileExistsError:
                continue
        output_path.unlink()
        result.output_path = str(final_path)
        result.output_sha256 = verified["sha256"]
        result.output_size_bytes = verified["size_bytes"]
        result.metadata_details = {
            **dict(result.metadata_details or {}),
            "hdde_output_metadata": output_metadata,
        }
        result.evidence_paths = {
            **dict(result.evidence_paths or {}),
            "output_metadata": output_metadata,
        }
        return function_dir, final_path

    def preview_token_for(path: Path, *, role: str) -> str | None:
        if not path.exists() or not path.is_file():
            return None
        return issue_token(path, role=role, filename=path.name)

    def preview_url(token: str | None) -> str | None:
        return f"/api/image-compression/preview/{token}" if token else None

    def lifecycle_timestamp() -> str:
        return datetime.fromtimestamp(now_provider(), tz=timezone.utc).isoformat()

    def file_size_bucket(value: Any) -> str:
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

    def safe_input_metadata(source: Mapping[str, Any]) -> dict[str, Any]:
        width = source.get("width")
        height = source.get("height")
        channels = source.get("channels")
        return {
            "format": str(source.get("format") or "")[:16],
            "width": width if isinstance(width, int) and not isinstance(width, bool) and width > 0 else None,
            "height": height if isinstance(height, int) and not isinstance(height, bool) and height > 0 else None,
            "color_mode": str(source.get("color_mode") or "")[:24],
            "channels": channels if isinstance(channels, int) and not isinstance(channels, bool) and channels > 0 else None,
            "alpha": bool(source.get("has_alpha")),
            "orientation": source.get("exif_orientation") if isinstance(source.get("exif_orientation"), int) else None,
            "file_size_bucket": file_size_bucket(source.get("size_bytes")),
        }

    def frozen_color_task_context(
        task_id: str,
        source: Mapping[str, Any],
        *,
        batch_id: str | None,
    ) -> dict[str, Any]:
        source_hash = str(source.get("sha256") or "")
        source_extension = ".png" if str(source.get("format") or "").upper() == "PNG" else ".jpg"
        source_hash_short = source_hash[:12] if source_hash else ""
        operation_identity = new_operation_identity(COLOR_CORRECTION_FEATURE_KEY, module_id="hdde.color.correction")
        return {
            "task_id": task_id,
            **operation_identity,
            "purpose": "COLOR_FIDELITY_CORRECTION",
            "batch_id": batch_id,
            "route_family": "color_correction",
            "source_reference": f"file_{source_hash_short}" if source_hash_short else "file_unavailable",
            "source_extension": source_extension,
            "source_hash_short": source_hash_short,
            "safe_input_metadata": safe_input_metadata(source),
        }

    def color_task_event_fields(record: Mapping[str, Any]) -> dict[str, Any]:
        context = record.get("task_context") if isinstance(record.get("task_context"), Mapping) else {}
        metadata = context.get("safe_input_metadata") if isinstance(context.get("safe_input_metadata"), Mapping) else {}
        feature_key = record.get("feature_key") or context.get("feature_key") or COLOR_CORRECTION_FEATURE_KEY
        return {
            "feature_key": feature_key,
            "feature": feature_key,
            "module_id": record.get("module_id") or context.get("module_id") or "",
            "operation_id": record.get("operation_id") or context.get("operation_id") or "",
            "trace_id": record.get("trace_id") or context.get("trace_id") or "",
            "operation": record.get("operation_mode") or "AUTO_COLOR_CORRECTION",
            "task_id": context.get("task_id") or record.get("task_id"),
            "result_id": record.get("result_id") or "",
            "delivery_id": record.get("delivery_id") or "",
            "batch_id": context.get("batch_id") or "",
            "purpose": context.get("purpose") or "",
            "route_family": context.get("route_family") or "",
            "source_reference": context.get("source_reference") or "",
            "source_extension": context.get("source_extension") or "",
            "source_hash_short": context.get("source_hash_short") or "",
            "batch_index": record.get("batch_index"),
            **dict(metadata),
        }

    def transition_task(record: dict[str, Any], status: str, progress: int, *, failure_reason: str | None = None) -> None:
        allowed = {
            None: {"pending"},
            "pending": {"processing"},
            "processing": {"completed", "failed"},
        }
        current = record.get("status")
        if status not in allowed.get(current, set()):
            raise RuntimeError(f"Invalid compression task transition: {current!r} -> {status!r}")
        if status == "pending" and progress != 0:
            raise RuntimeError("Pending compression tasks must start at progress 0.")
        if status == "processing" and not 0 < progress < 100:
            raise RuntimeError("Processing compression tasks must have progress between 0 and 100.")
        if status == "completed" and progress != 100:
            raise RuntimeError("Completed compression tasks must end at progress 100.")
        if status == "failed" and progress >= 100:
            raise RuntimeError("Failed compression tasks cannot report progress 100.")

        recorded_at = lifecycle_timestamp()
        record["status"] = status
        record["progress"] = progress
        record["task_status"] = status
        record["task_progress"] = progress
        record["execution_state"] = {
            "pending": "queued",
            "processing": "processing",
            "completed": "completed",
            "failed": "failed",
        }[status]
        record["failure_reason"] = failure_reason if status == "failed" else None
        record["completed_at"] = recorded_at if status in {"completed", "failed"} else None
        record.setdefault("lifecycle", []).append({
            "task_id": record["task_id"],
            "status": status,
            "progress": progress,
            "recorded_at": recorded_at,
        })
        if shared_task_registry is not None:
            shared_task_registry[str(record["task_id"])] = record

    def public_task(record: Mapping[str, Any]) -> dict[str, Any]:
        output_path = record.get("output_path")
        return {
            "task_id": record["task_id"],
            "feature_key": record.get("feature_key") or "",
            "module_id": record.get("module_id") or "",
            "operation_id": record.get("operation_id") or "",
            "trace_id": record.get("trace_id") or "",
            "result_id": record.get("result_id") or "",
            "delivery_id": record.get("delivery_id") or "",
            "task_family": record.get("task_family") or "",
            "result_file": str(record.get("result_file") or ""),
            "preview_output_url": str(record.get("preview_output_url") or ""),
            "operation_mode": record["operation_mode"],
            "source_path": str(record["source_path"]),
            "status": record["status"],
            "progress": record["progress"],
            "task_status": record["task_status"],
            "task_progress": record["task_progress"],
            "execution_state": record["execution_state"],
            "output_path": str(output_path) if output_path else None,
            "d3_status": record.get("d3_status") or "",
            "d3_final_action": record.get("d3_final_action") or "",
            "result_action": record.get("result_action") or "",
            "output_selected": record.get("output_selected") or "",
            "failure_reason": record.get("failure_reason"),
            "created_at": record["created_at"],
            "completed_at": record.get("completed_at"),
            "lifecycle": [dict(item) for item in record.get("lifecycle", [])],
            "batch_id": record.get("batch_id"),
            "batch_index": record.get("batch_index"),
            "source_origin": record.get("source_origin") or "",
            "source_result_id": record.get("source_result_id") or "",
            "source_task_id": record.get("source_task_id") or "",
            "source_feature_key": record.get("source_feature_key") or "",
        }

    def color_output_dir(root: Path) -> Path:
        root = root.resolve()
        target = (root / "颜色校正").resolve()
        if root not in target.parents:
            raise HTTPException(status_code=500, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": "颜色校正输出目录安全校验失败。"})
        target.mkdir(parents=True, exist_ok=True)
        if not target.is_dir():
            raise HTTPException(status_code=400, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": "颜色校正输出目录不可用。"})
        return target

    def color_output_name(filename: str, now_value: float) -> str:
        source_name = Path(_safe_name(filename))
        suffix = source_name.suffix.lower()
        suffix = ".png" if suffix == ".png" else ".jpg"
        return build_output_filename(
            source_name.name,
            FEATURE_COLOR,
            suffix,
            trusted_original_filename=source_name.name,
            moment=datetime.fromtimestamp(now_value),
        )

    def unique_output_path(directory: Path, filename: str) -> Path:
        candidate = directory / filename
        index = 1
        while candidate.exists():
            candidate = directory / f"{Path(filename).stem}_{index}{Path(filename).suffix}"
            index += 1
        return candidate

    def color_result_review_status(record: Mapping[str, Any]) -> str:
        output_path = Path(record["output_path"]) if record.get("output_path") else None
        if record.get("status") != "completed" or not output_path or not output_path.is_file():
            return "not_available"
        status = str(record.get("result_review_status") or "pending")
        return status if status in {"pending", "confirmed"} else "pending"

    def require_color_record(task_id: str) -> dict[str, Any]:
        record = task_registry.get(str(task_id or ""))
        if record is None and shared_task_registry is not None:
            persisted = shared_task_registry.get(str(task_id or ""))
            # Reference Result reading must survive a process restart. Read the
            # existing terminal fact; never recreate a Task or rerun a decision.
            if (
                isinstance(persisted, dict)
                and persisted.get("task_id") == task_id
                and persisted.get("task_family") == "color_correction"
                and persisted.get("status") in {"completed", "failed"}
            ):
                record = persisted
                task_registry[task_id] = record
        if not record or record.get("task_family") != "color_correction":
            raise HTTPException(status_code=404, detail={"code": "COLOR_CORRECTION_TASK_NOT_FOUND", "message": "颜色校正任务不存在。"})
        return record

    def public_color_result(record: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(record.get("result") or {})
        decision = dict(record.get("decision") or result)
        reference_preview = None
        cache_root = Path(require_compression_directory()["tmp_dir"]).resolve()
        if record.get("operation_mode") in {"REFERENCE_COLOR_CORRECTION", "REFERENCE_LEVEL_PICK_COLOR_CORRECTION"}:
            reference = record.get("reference_metadata") or {}
            reference_path = Path(str(reference.get("path") or "")).resolve()
            if cache_root in reference_path.parents and reference_path.is_file() and _sha256_file(reference_path) == reference.get("sha256"):
                token = record.get("reference_preview_token")
                if token not in token_registry or token_registry[token]["expires_at"] <= now_provider():
                    token = preview_token_for(reference_path, role="source_preview")
                    record["reference_preview_token"] = token
                reference_preview = preview_url(token)
        # Both color modes recover preview authorization from registered file
        # identity; expired source tokens remain unusable for new processing.
        for field, path, expected_hash, role, root in (
            ("source_preview_token", record.get("source_path"), record.get("source_metadata", {}).get("sha256"), "source_preview", cache_root),
            ("output_preview_token", record.get("output_path"), result.get("output_sha256"), "output_preview", Path(record["effective_output_root"]).resolve()),
        ):
            token = record.get(field)
            if token not in token_registry or token_registry[token]["expires_at"] <= now_provider():
                image_path = Path(str(path or "")).resolve()
                record[field] = (
                    preview_token_for(image_path, role=role)
                    if path and expected_hash and root in image_path.parents and image_path.is_file()
                    and _sha256_file(image_path) == expected_hash else None
                )
        output_path = Path(record["output_path"]) if record.get("output_path") else None
        source_preview = preview_url(record.get("source_preview_token"))
        output_preview = preview_url(record.get("output_preview_token")) if output_path and output_path.is_file() else None
        return {
            "task": public_task(record),
            "result": result or None,
            "decision": decision or None,
            "review": {
                "status": color_result_review_status(record),
                "reviewed_at": record.get("result_reviewed_at"),
                "meaning": "用户已查看并接受当前结果，不代表自动视觉评分或质量通过。",
            },
            "ui": {
                "source_display_name": Path(record["source_path"]).name,
                "output_display_name": output_path.name if output_path else None,
                "source_preview_url": source_preview,
                "output_preview_url": output_preview,
                "output_path": str(output_path) if output_path else None,
                "output_directory": str(record["output_dir"]),
                "effective_output_root": str(record["effective_output_root"]),
                "output_root_source": record.get("output_root_source") or "saved_default",
                "can_open_output": bool(output_path and output_path.is_file()),
                "can_open_folder": bool(output_path and output_path.is_file()),
                "feedback_report": record.get("feedback_report"),
                "display_task_number": record.get("display_task_number"),
                "batch_id": record.get("batch_id"),
                **({
                    "reference_preview_url": reference_preview,
                    "reference_display_name": str(record.get("reference_metadata", {}).get("filename") or "参考图"),
                    "reference_match_status": record.get("reference_provenance", {}).get("reference_match_status"),
                    "reference_notice_code": "REFERENCE_INSUFFICIENT_EVIDENCE" if record.get("reference_provenance", {}).get("reference_match_status") == "INSUFFICIENT_EVIDENCE" else None,
                } if record.get("operation_mode") == "REFERENCE_COLOR_CORRECTION" else {}),
                **({
                    "level_pick": {
                        "level": record["level_pick"]["level"],
                        "label": LEVEL_LABELS[record["level_pick"]["level"]],
                        "measurement": public_level_measurement(record["level_pick"].get("analysis") or {}),
                    },
                } if record.get("operation_mode") == "LEVEL_PICK_COLOR_CORRECTION" else {}),
                **({
                    "level_pick": {
                        "level": record["level_pick"]["level"],
                        "label": LEVEL_LABELS[record["level_pick"]["level"]],
                        "measurement": public_reference_measurement(record["level_pick"].get("analysis") or {}),
                    },
                    "reference_preview_url": reference_preview,
                    "reference_display_name": str(record.get("reference_metadata", {}).get("filename") or "参考图"),
                } if record.get("operation_mode") == "REFERENCE_LEVEL_PICK_COLOR_CORRECTION" else {}),
            },
        }

    def create_color_task_record(
        source: Mapping[str, Any],
        output_root: Mapping[str, Any],
        *,
        batch_id: str | None = None,
        batch_index: int | None = None,
        reference: Mapping[str, Any] | None = None,
        level_pick: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        effective_root = Path(str(output_root["normalized_path"])).resolve()
        output_dir = color_output_dir(effective_root)
        task_created_at = now_provider()
        task_id = f"color_{uuid.uuid4().hex[:16]}"
        source_filename = str(source.get("filename") or "图片.png")
        source_suffix = Path(source_filename).suffix.lower()
        output_suffix = ".png" if source_suffix == ".png" else ".jpg"
        output_path = build_output_path(
            output_dir,
            source_filename,
            FEATURE_COLOR,
            output_suffix,
            trusted_original_filename=source_filename,
            moment=datetime.fromtimestamp(task_created_at),
        )
        record = {
            "task_id": task_id,
            "feature_key": COLOR_CORRECTION_FEATURE_KEY,
            "task_family": "color_correction",
            "batch_id": batch_id,
            "batch_index": batch_index,
            "display_task_number": datetime.fromtimestamp(task_created_at).strftime("CC-%Y%m%d-%H%M%S"),
            "operation_mode": "AUTO_COLOR_CORRECTION",
            "created_at": datetime.fromtimestamp(task_created_at, tz=timezone.utc).isoformat(),
            "completed_at": None,
            "status": None,
            "progress": 0,
            "failure_reason": None,
            "lifecycle": [],
            "source_path": Path(str(source["path"])).resolve(),
            "output_path": None,
            "planned_output_path": output_path,
            "output_dir": output_dir,
            "effective_output_root": effective_root,
            "output_root_source": output_root["source"],
            "source_preview_token": preview_token_for(Path(str(source["path"])), role="source_preview"),
            "output_preview_token": None,
            "source_metadata": dict(source),
            "original_filename": source_filename,
            "result": None,
            "decision": None,
            "result_id": "",
            "result_file": "",
            "feedback_report": None,
            "feedback_report_token": None,
            "result_review_status": "not_available",
            "result_reviewed_at": None,
            **result_lineage_fields(source),
        }
        record["task_context"] = frozen_color_task_context(task_id, source, batch_id=batch_id)
        if reference is not None:
            record.update({
                "operation_mode": "REFERENCE_COLOR_CORRECTION",
                "reference_metadata": dict(reference),
                "reference_preview_token": preview_token_for(Path(str(reference["path"])), role="source_preview"),
            })
            record["task_context"]["purpose"] = "REFERENCE_COLOR_MATCHING"
        if level_pick is not None:
            record.update({"operation_mode": "LEVEL_PICK_COLOR_CORRECTION", "level_pick": dict(level_pick)})
            record["task_context"]["purpose"] = "AI_LEVEL_PICK_COLOR_CORRECTION"
            if level_pick.get("reference"):
                reference_source = level_pick["reference"]
                record.update({
                    "operation_mode": "REFERENCE_LEVEL_PICK_COLOR_CORRECTION",
                    "reference_metadata": dict(reference_source),
                    "reference_preview_token": preview_token_for(Path(str(reference_source["path"])), role="source_preview"),
                })
                record["task_context"]["purpose"] = "REFERENCE_LEVEL_PICK_COLOR_CORRECTION"
        record.update(operation_event_fields(record["task_context"]))
        record["error_context"] = {}
        record["related_events"] = []
        task_registry[task_id] = record
        if shared_task_registry is not None:
            shared_task_registry[task_id] = record
        transition_task(record, "pending", 0)
        emit_runtime_event(
            "TASK_CREATED",
            stage="task_registration",
            result="success",
            impact="unified_task_available",
            **color_task_event_fields(record),
        )
        return record

    def execute_color_task(record: dict[str, Any]) -> None:
        if not claim_task_execution(record):
            return
        output_path = Path(record["planned_output_path"])
        try:
            emit_runtime_event(
                "PROCESS_STARTED",
                stage="engine_adapter",
                result="started",
                status="processing",
                impact="color_correction_running",
                **color_task_event_fields(record),
            )
            emit_runtime_event(
                "COLOR_CORRECTION_TASK_STARTED",
                stage="color_correction_execution",
                result="started",
                status="processing",
                impact="color_correction_running",
                action="process_and_verify_output",
                **color_task_event_fields(record),
            )
            transition_task(record, "processing", 12)
            source_path = Path(record["source_path"]).resolve()
            source_sha_before = _sha256_file(source_path)
            created_moment = datetime.fromisoformat(str(record["created_at"])).astimezone()
            while True:
                output_path = build_output_path(
                    record["output_dir"],
                    record["original_filename"],
                    FEATURE_COLOR,
                    Path(record["original_filename"]).suffix,
                    trusted_original_filename=record["original_filename"],
                    moment=created_moment,
                )
                record["planned_output_path"] = output_path
                try:
                    if record.get("operation_mode") == "REFERENCE_COLOR_CORRECTION":
                        result = run_formal_color_runtime(
                            source_path, output_path,
                            reference_path=Path(record["reference_metadata"]["path"]),
                        )
                    else:
                        result = run_formal_color_runtime(source_path, output_path)
                    break
                except FileExistsError:
                    continue
            if _sha256_file(source_path) != source_sha_before or result.source_sha256 != source_sha_before:
                raise RuntimeError("原图完整性校验失败，任务已阻断。")
            final_action = str(result.result_action)
            if record.get("operation_mode") == "REFERENCE_COLOR_CORRECTION":
                record["reference_provenance"] = dict(result.analysis.get("REFERENCE_PROVENANCE") or {})
            if result.d3_final_action != final_action:
                raise RuntimeError("D3 与正式 Result 最终动作不一致，任务已阻断。")
            selected_output = str(result.output_selected)
            candidate_selected = selected_output in {"CORRECTED_CANDIDATE", "REVIEW_CANDIDATE"}
            output_metadata: dict[str, Any] | None = None
            verified_after_metadata: dict[str, Any] | None = None
            if candidate_selected:
                if not output_path.is_file() or output_path.stat().st_size <= 0:
                    raise RuntimeError("颜色校正候选验证失败：输出文件不存在或为空。")
                verified = read_image_info(output_path)
                expected_suffix = ".png" if result.output_format == "PNG" else ".jpg"
                if (
                    verified["format"] != result.output_format
                    or verified["dimensions"] != {"width": result.width, "height": result.height}
                    or verified["sha256"] != result.output_sha256
                    or output_path.suffix.lower() != expected_suffix
                ):
                    raise RuntimeError("颜色校正候选验证失败：格式、尺寸或文件摘要不一致。")
                output_metadata = dict(result.output_metadata or {})
                if not output_metadata.get("written"):
                    raise RuntimeError("颜色校正候选缺少发布前统一元数据验证。")
                verified_after_metadata = read_image_info(output_path)
                if (
                    verified_after_metadata["format"] != result.output_format
                    or verified_after_metadata["dimensions"] != {"width": result.width, "height": result.height}
                ):
                    raise RuntimeError("颜色校正元数据写入后验证失败：格式或尺寸发生变化。")
            elif output_path.exists():
                raise RuntimeError("D3 未选择 Candidate，但正式输出路径出现了修改文件。")
            if final_action == "ACCEPT_CORRECTED" and selected_output != "CORRECTED_CANDIDATE":
                raise RuntimeError("ACCEPT_CORRECTED 缺少已验证 Candidate，任务已阻断。")
            if final_action == "ACCEPT_ORIGINAL" and selected_output != "ORIGINAL" and result.d3_status != "PROTECTION_BLOCKED":
                raise RuntimeError("ACCEPT_ORIGINAL 未绑定原图，任务已阻断。")
            if final_action == "REVIEW_REQUIRED" and selected_output == "CORRECTED_CANDIDATE":
                raise RuntimeError("REVIEW_REQUIRED 不得映射为正式校正输出。")
            if result.d3_status == "PROTECTION_BLOCKED" or selected_output == "NONE":
                blocked_reason = "保护门禁阻止生成可审核结果。"
                record.update({
                    "result": None,
                    "task_result": None,
                    "result_id": "",
                    "result_file": "",
                    "output_path": None,
                    "output_preview_token": None,
                    "preview_output_url": "",
                    "d3_status": result.d3_status,
                    "d3_final_action": result.d3_final_action,
                    "result_action": final_action,
                    "output_selected": selected_output,
                    "result_review_status": "not_available",
                    "result_reviewed_at": None,
                    "output_metadata": None,
                })
                transition_task(record, "failed", record["progress"], failure_reason=blocked_reason)
                emit_runtime_event(
                    "COLOR_CORRECTION_TASK_FAILED",
                    level=logging.WARNING,
                    stage="output_verification",
                    result="blocked",
                    status="failed",
                    reason=blocked_reason,
                    impact="no_deliverable_result",
                    action="return_adjust_and_reprocess",
                    **color_task_event_fields(record),
                )
                emit_runtime_event(
                    "PROCESS_FAILED",
                    level=logging.WARNING,
                    stage="output_verification",
                    result="blocked",
                    status="failed",
                    reason=blocked_reason,
                    impact="formal_result_unavailable",
                    **color_task_event_fields(record),
                )
                return
            result_data = result.to_dict()
            if verified_after_metadata is not None:
                result_data["output_sha256"] = verified_after_metadata["sha256"]
                result_data["output_size_bytes"] = verified_after_metadata["size_bytes"]
            publishes_result = candidate_selected
            result_id = f"color_result_{uuid.uuid4().hex[:16]}" if publishes_result else ""
            formal_result_file = (
                str(output_path)
                if final_action == "ACCEPT_CORRECTED"
                else ""
            )
            candidate_output_path = str(output_path) if candidate_selected else ""
            result_data.update({
                "result_id": result_id,
                "task_id": record["task_id"],
                "feature_key": record["feature_key"],
                "source": str(record["source_path"]),
                "source_path": str(record["source_path"]),
                "status": final_action,
                "result_file": formal_result_file,
                "output_path": candidate_output_path,
                **result_lineage_fields(record.get("source_metadata")),
            })
            if record.get("operation_mode") == "REFERENCE_COLOR_CORRECTION":
                result_data.update({
                    "operation_mode": "REFERENCE_COLOR_CORRECTION",
                    "reference_provenance": dict(record["reference_provenance"]),
                })
            if candidate_selected:
                verification_improvement = "候选文件已完成存在、解码、尺寸、格式与摘要验证"
                improvements = list(result_data.get("improvements", []))
                if verification_improvement not in improvements:
                    improvements.append(verification_improvement)
                result_data["improvements"] = improvements
            output_preview_token = preview_token_for(output_path, role="output_preview") if candidate_selected else None
            published_result = result_data if publishes_result else None
            record.update({
                "decision": result_data,
                "result": published_result,
                "task_result": published_result,
                "result_id": result_id,
                "result_file": formal_result_file,
                "output_path": output_path if candidate_selected else None,
                "output_preview_token": output_preview_token,
                "preview_output_url": preview_url(output_preview_token) if output_preview_token else "",
                "d3_status": result.d3_status,
                "d3_final_action": result.d3_final_action,
                "result_action": final_action,
                "output_selected": selected_output,
                "result_review_status": "pending" if candidate_selected else "not_available",
                "result_reviewed_at": None,
                "output_metadata": output_metadata,
            })
            if not publishes_result:
                raise RuntimeError("本次保留原图，未生成新颜色校正文件；可更换图片或参考图后再次处理。")
            if shared_task_registry is None:
                raise RuntimeError("颜色校正 Result 登记服务不可用，任务未完成。")
            # Publish completion only after the existing registry commits it.
            # transition_task mutates its argument before writing, so a private
            # terminal snapshot keeps a failed commit from completing this task.
            finalized = {**record, "lifecycle": list(record.get("lifecycle", []))}
            transition_task(finalized, "completed", 100)
            record.update(finalized)
            task_registry[record["task_id"]] = finalized
            event_result = {
                "ACCEPT_CORRECTED": "success",
                "ACCEPT_ORIGINAL": "original_selected",
                "REVIEW_REQUIRED": "review_required",
            }[final_action]
            event_impact = {
                "ACCEPT_CORRECTED": "verified_corrected_output_available",
                "ACCEPT_ORIGINAL": "original_preserved_no_new_result",
                "REVIEW_REQUIRED": "formal_review_required",
            }[final_action]
            emit_runtime_event(
                "PROCESS_SUCCEEDED",
                stage="output_verification",
                result=event_result,
                impact=event_impact,
                **color_task_event_fields(record),
            )
            if publishes_result:
                emit_runtime_event(
                    "RESULT_REGISTERED",
                    stage="result_registry",
                    result=event_result,
                    impact=event_impact,
                    **color_task_event_fields(record),
                )
            final_event = {
                "ACCEPT_CORRECTED": "COLOR_CORRECTION_TASK_SUCCEEDED",
                "ACCEPT_ORIGINAL": "COLOR_CORRECTION_ORIGINAL_SELECTED",
                "REVIEW_REQUIRED": "COLOR_CORRECTION_REVIEW_REQUIRED",
            }[final_action]
            emit_runtime_event(
                final_event,
                stage="output_verification",
                result=event_result,
                status="completed",
                impact=event_impact,
                action={
                    "ACCEPT_CORRECTED": "review_or_deliver_output",
                    "ACCEPT_ORIGINAL": "use_original",
                    "REVIEW_REQUIRED": "review_candidate_without_delivery",
                }[final_action],
                **color_task_event_fields(record),
            )
        except Exception as exc:
            if record.get("operation_mode") == "REFERENCE_COLOR_CORRECTION" and record.get("output_selected") != "ORIGINAL":
                # Keep exception class/stage for diagnosis, never user image paths
                # or chained decoder messages in reference-mode public/log data.
                exc = RuntimeError(f"参考图校色执行失败（{type(exc).__name__}），未转为自动校色，请重新选择图片或查看任务诊断。")
            record_color_task_failure(record, exc)

    def record_color_task_failure(record: dict[str, Any], exc: BaseException) -> None:
        """Shared terminal failure path for every color operation mode."""

        failed_stage = str(getattr(exc, "stage", "color_correction_execution"))
        error_category = "ENVIRONMENT_ERROR" if isinstance(exc, OSError) else "PRODUCT_ERROR"
        diagnostics = build_exception_diagnostics(
            exc,
            error_category=error_category,
            error_stage=failed_stage,
            trace_id=str(record.get("trace_id") or ""),
        )
        record["error_context"] = dict(diagnostics)
        emit_runtime_event(
            "COLOR_CORRECTION_TASK_FAILED",
            level=logging.ERROR,
            stage=failed_stage,
            result="failed",
            status="failed",
            impact="color_correction_output_unavailable",
            action="check_runtime_log_and_source_file",
            **{**color_task_event_fields(record), **diagnostics},
        )
        emit_runtime_event(
            "PROCESS_FAILED",
            level=logging.ERROR,
            stage=failed_stage,
            result="failed",
            status="failed",
            impact="formal_result_unavailable",
            **{**color_task_event_fields(record), **diagnostics},
        )
        record["output_path"] = None
        record["result"] = None
        record["task_result"] = None
        record["result_id"] = ""
        record["result_file"] = ""
        record["output_preview_token"] = None
        record["preview_output_url"] = ""
        if record.get("status") == "processing":
            try:
                transition_task(record, "failed", record["progress"], failure_reason=str(exc) or exc.__class__.__name__)
            except Exception as registration_error:
                emit_runtime_event(
                    "COLOR_CORRECTION_TASK_FAILED", level=logging.ERROR,
                    stage="result_registry", result="failed", status="failed",
                    reason=registration_error.__class__.__name__,
                    impact="failed_task_not_persisted", action="check_result_registry",
                    **color_task_event_fields(record),
                )

    def public_level_measurement(analysis: Mapping[str, Any]) -> dict[str, Any]:
        category = str(analysis.get("category") or "NO_CAST")
        hints = list(analysis.get("intent_hints") or [])
        labels = {"YELLOW": "画面偏黄", "BLUE": "画面偏蓝", "TINT": "画面偏绿或偏品红", "GREY": "画面发灰"}
        parts = [labels[tag] for tag in category.split("+") if tag in labels]
        return {
            "category": category,
            "summary": "、".join(parts) if parts else "未测到明显偏色",
            "measured_offset": analysis.get("measured_offset"),
            "recommended_level": analysis.get("recommended_level") or "original",
            "recommended_label": LEVEL_LABELS.get(str(analysis.get("recommended_level") or "original"), "原图"),
            "intent_hints": hints,
            "possible_design_colour": bool(hints) or category == "NO_CAST",
            "notice": "可能是有意的设计色调，建议先看原图；最终由你选择。" if hints else "",
        }

    def remove_level_preview_files(preview_id: str, directory: Path) -> None:
        cache_root = Path(require_compression_directory()["tmp_dir"]).resolve() / "color-level-preview"
        directory = directory.resolve()
        # Only a directory a preview session created, inside the managed cache.
        if cache_root in directory.parents and directory.name == f"preview_{preview_id}":
            shutil.rmtree(directory, ignore_errors=True)

    def release_used_level_preview(session: dict[str, Any]) -> None:
        """A used preview can never produce another Result, so its images are not kept."""

        for item in session["levels"].values():
            token_registry.pop(str(item.get("preview_token") or ""), None)
        remove_level_preview_files(session["preview_id"], Path(session["directory"]))

    def public_reference_measurement(analysis: Mapping[str, Any]) -> dict[str, Any]:
        description = dict(analysis.get("description") or {})
        usable = bool(analysis.get("usable"))
        recommended = str(analysis.get("recommended_level") or "original")
        return {
            "category": "REFERENCE_SHIFT" if usable else "REFERENCE_UNUSABLE",
            "summary": str(description.get("summary") or ""),
            "measured_offset": description.get("offset"),
            "recommended_level": recommended,
            "recommended_label": LEVEL_LABELS.get(recommended, "原图"),
            "intent_hints": [],
            "reference_usable": usable,
            "notice": "结果会采用参考图的白，请选同一系列、同一光线的参考图。" if usable else "这张参考图不适合用来校色，请换一张有白色或灰色区域的参考图。",
        }

    def prune_level_preview_sessions() -> None:
        cache_root = Path(require_compression_directory()["tmp_dir"]).resolve() / "color-level-preview"
        for preview_id, session in list(color_level_preview_sessions.items()):
            if session["expires_at"] > now_provider() or session.get("running_task_id"):
                continue
            color_level_preview_sessions.pop(preview_id, None)
            remove_level_preview_files(preview_id, Path(session["directory"]))
        # Sessions live only in this process, so directories left by an earlier run are
        # never pruned above; remove those older than one preview lifetime.
        if cache_root.is_dir():
            live = {f"preview_{preview_id}" for preview_id in color_level_preview_sessions}
            for directory in cache_root.iterdir():
                if (
                    directory.is_dir() and not directory.is_symlink()
                    and directory.name.startswith("preview_") and directory.name not in live
                    and directory.stat().st_mtime + TOKEN_TTL_SECONDS <= now_provider()
                ):
                    remove_level_preview_files(directory.name[len("preview_"):], directory)

    def execute_level_pick_task(record: dict[str, Any], session: dict[str, Any]) -> None:
        """Materialise exactly the level the user saw; the user's choice is the acceptance."""

        if not claim_task_execution(record):
            return
        level = str(record["level_pick"]["level"])
        try:
            emit_runtime_event(
                "PROCESS_STARTED", stage="engine_adapter", result="started", status="processing",
                impact="color_correction_running", **color_task_event_fields(record),
            )
            transition_task(record, "processing", 12)
            started = time.perf_counter()
            source_path = Path(record["source_path"]).resolve()
            source_sha = _sha256_file(source_path)
            if source_sha != session["source_sha256"]:
                raise RuntimeError("原图内容已变化，预览已失效，请重新生成预览。")
            managed = load_color_managed_source(source_path)
            reference_source = record["level_pick"].get("reference")
            if reference_source:
                reference_path = Path(str(reference_source["path"])).resolve()
                if _sha256_file(reference_path) != session["reference_sha256"]:
                    raise RuntimeError("参考图内容已变化，预览已失效，请重新生成预览。")
                reference_plan = plan_reference(managed.pixels, load_color_managed_source(reference_path).pixels)
                if not reference_plan.usable:
                    raise RuntimeError("参考图没有可用的中性区域，不能生成结果。")
                analysis = reference_plan.target
                candidate = render_reference_level(managed.pixels, reference_plan, level)
            else:
                analysis = analyze_level_pick(managed.pixels)
                candidate = render_level(managed.pixels, analysis, level)
            if pixel_sha256(candidate) != session["levels"][level]["pixel_sha256"]:
                raise RuntimeError("正式结果与所选预览不一致，任务已阻断。")
            safety = level_safety(managed.pixels, candidate, analysis)
            if not safety["passed"]:
                raise RuntimeError("所选档位未通过安全检查，任务已阻断。")
            created_moment = datetime.fromisoformat(str(record["created_at"])).astimezone()
            while True:
                output_path = build_output_path(
                    record["output_dir"], record["original_filename"], FEATURE_COLOR,
                    Path(record["original_filename"]).suffix,
                    trusted_original_filename=record["original_filename"], moment=created_moment,
                )
                record["planned_output_path"] = output_path
                try:
                    verified = _write_verified_candidate(candidate, output_path, source=managed, source_path=source_path)
                    break
                except FileExistsError:
                    continue
            if _sha256_file(source_path) != source_sha:
                raise RuntimeError("原图完整性校验失败，任务已阻断。")
            output_path = Path(verified["output_path"])
            info = read_image_info(output_path)
            if (
                info["format"] != verified["output_format"]
                or info["dimensions"] != {"width": int(candidate.shape[1]), "height": int(candidate.shape[0])}
                or info["sha256"] != verified["output_sha256"]
                or not dict(verified.get("output_metadata") or {}).get("written")
            ):
                raise RuntimeError("挑档校色结果验证失败：格式、尺寸、摘要或元数据不一致。")
            result_id = f"color_result_{uuid.uuid4().hex[:16]}"
            reviewed_at = lifecycle_timestamp()
            analysis_record = reference_plan.to_record() if reference_source else analysis.to_record()
            mode = "REFERENCE_LEVEL_PICK_COLOR_CORRECTION" if reference_source else "LEVEL_PICK_COLOR_CORRECTION"
            version = REFERENCE_LEVEL_PICK_VERSION if reference_source else LEVEL_PICK_VERSION
            result_data = {
                "engine_version": version,
                "runtime_schema_version": version,
                "source_sha256": source_sha,
                "source_format": managed.source_format,
                "width": int(candidate.shape[1]),
                "height": int(candidate.shape[0]),
                "source_size_bytes": source_path.stat().st_size,
                "output_path": str(output_path),
                "output_sha256": info["sha256"],
                "output_format": info["format"],
                "output_size_bytes": info["size_bytes"],
                "processing_time_ms": int(round((time.perf_counter() - started) * 1000)),
                # The existing human-confirmed review contract carries this Result:
                # no D3 auto acceptance is claimed and no new FinalAction is introduced.
                "d1_action": "NOT_APPLICABLE_USER_LEVEL_PICK",
                "d3_status": "LEVEL_PICK_USER_SELECTED",
                "d3_final_action": "REVIEW_REQUIRED",
                "result_action": "REVIEW_REQUIRED",
                "actual_final_action": "REVIEW_REQUIRED",
                "output_selected": "REVIEW_CANDIDATE",
                "acceptance_authority": "REVIEW_ONLY",
                "delivery_acceptance_authority": "HUMAN_CONFIRMED_REVIEW",
                "result_review_status": "confirmed",
                "delivery_eligible": True,
                "candidate_identity": session["levels"][level]["pixel_sha256"],
                "analysis": {
                    ("REFERENCE_LEVEL_PICK" if reference_source else "LEVEL_PICK"): analysis_record,
                    "LEVEL_PICK_SAFETY": safety,
                    "SELECTED_LEVEL": level,
                    **({"REFERENCE_PROVENANCE": {
                        "reference_source_fingerprint": session["reference_sha256"],
                        "reference_display_name": str(reference_source.get("filename") or ""),
                    }} if reference_source else {}),
                },
                "before_metrics": {},
                "after_metrics": {"delta_e00_mean": safety["delta_e00_mean"], "neutral_delta_e00_mean": safety["neutral_delta_e00_mean"], "clip_growth": safety["clip_growth"]},
                "detected_issues": (["REFERENCE_SHIFT"] if analysis_record.get("recommended_level") == "medium" else []) if reference_source
                else [tag for tag in analysis.category.split("+") if tag != "NO_CAST"],
                "improvements": ["原图哈希保持不变，未覆盖或修改原图", f"按用户选择的“{LEVEL_LABELS[level]}”档生成，与预览逐像素一致", "候选文件已完成存在、解码、尺寸、格式与摘要验证"],
                "review_points": ["用户在四档预览中选定该档，视为人工确认"],
                "applied_actions": ["USER_SELECTED_LEVEL_COLOR_CORRECTION"],
                "parameters": {"level": level, "strength": LEVELS[level], "level_pick_version": version,
                               **({"reference_sha256": session["reference_sha256"]} if reference_source else {})},
                "result_id": result_id,
                "task_id": record["task_id"],
                "feature_key": record["feature_key"],
                "source": str(record["source_path"]),
                "source_path": str(record["source_path"]),
                "status": "REVIEW_REQUIRED",
                "result_file": str(output_path),
                "operation_mode": mode,
                "selected_level": level,
                **result_lineage_fields(record.get("source_metadata")),
            }
            output_preview_token = preview_token_for(output_path, role="output_preview")
            record["level_pick"] = {**record["level_pick"], "analysis": analysis_record, "safety": safety}
            record.update({
                "decision": result_data,
                "result": result_data,
                "task_result": dict(result_data),
                "result_id": result_id,
                "result_file": str(output_path),
                "output_path": output_path,
                "output_preview_token": output_preview_token,
                "preview_output_url": preview_url(output_preview_token) if output_preview_token else "",
                "d3_status": result_data["d3_status"],
                "d3_final_action": "REVIEW_REQUIRED",
                "result_action": "REVIEW_REQUIRED",
                "output_selected": "REVIEW_CANDIDATE",
                "result_review_status": "confirmed",
                "result_reviewed_at": reviewed_at,
                "delivery_eligible": True,
                "delivery_acceptance_authority": "HUMAN_CONFIRMED_REVIEW",
                "output_metadata": dict(verified.get("output_metadata") or {}),
            })
            if shared_task_registry is None:
                raise RuntimeError("颜色校正 Result 登记服务不可用，任务未完成。")
            finalized = {**record, "lifecycle": list(record.get("lifecycle", []))}
            transition_task(finalized, "completed", 100)
            record.update(finalized)
            task_registry[record["task_id"]] = finalized
            for event, stage, impact in (
                ("PROCESS_SUCCEEDED", "output_verification", "user_selected_level_output_available"),
                ("RESULT_REGISTERED", "result_registry", "human_confirmed_unified_result_available"),
                ("USER_CONFIRMED", "human_quality_review", "color_level_selected"),
                ("RESULT_CONFIRMED", "result_registry", "human_confirmed_unified_result_available"),
                ("COLOR_CORRECTION_LEVEL_PICK_SUCCEEDED", "output_verification", "user_selected_level_output_available"),
            ):
                emit_runtime_event(
                    event, stage=stage, result="success", status="completed", impact=impact,
                    acceptance_authority="HUMAN_CONFIRMED_REVIEW", selected_level=level,
                    **color_task_event_fields(record),
                )
        except Exception as exc:
            record_color_task_failure(record, exc)

    def refresh_color_batch(batch: dict[str, Any]) -> None:
        items = [task_registry[task_id] for task_id in batch["task_ids"] if task_id in task_registry]
        batch["task_ids"] = [item["task_id"] for item in items]
        batch["total_count"] = len(items)
        completed_count = sum(item.get("status") == "completed" for item in items)
        failed_count = sum(item.get("status") == "failed" for item in items)
        finished_count = completed_count + failed_count
        batch["completed_count"] = completed_count
        batch["failed_count"] = failed_count
        batch["progress"] = 100 if not items else round((finished_count / len(items)) * 100)
        batch["current_task_id"] = next((item["task_id"] for item in items if item.get("status") == "processing"), None)

    def remove_task_runtime_references(task_id: str) -> None:
        normalized_id = str(task_id or "").strip()
        record = task_registry.pop(normalized_id, None)
        if isinstance(record, Mapping):
            for field in ("source_preview_token", "reference_preview_token", "output_preview_token", "feedback_report_token", "feedback_package_token"):
                token = str(record.get(field) or "")
                if token:
                    token_registry.pop(token, None)
        for batch in color_batch_registry.values():
            if normalized_id not in batch.get("task_ids", []):
                continue
            batch["task_ids"] = [value for value in batch["task_ids"] if value != normalized_id]
            refresh_color_batch(batch)
            if not batch["task_ids"]:
                batch["status"] = "cancelled"
                batch["completed_at"] = lifecycle_timestamp()
        for item_id, item in list(output_center_index.items()):
            if str(item.get("task_id") or "") == normalized_id:
                output_center_index.pop(item_id, None)

    def public_color_batch(batch: Mapping[str, Any]) -> dict[str, Any]:
        records = [task_registry[task_id] for task_id in batch["task_ids"]]
        items = [public_color_result(record) for record in records]
        confirmed_count = sum(color_result_review_status(record) == "confirmed" for record in records)
        pending_review_count = sum(color_result_review_status(record) == "pending" for record in records)
        return {
            "batch_id": batch["batch_id"],
            "status": batch["status"],
            "progress": batch["progress"],
            "total_count": batch["total_count"],
            "completed_count": batch["completed_count"],
            "failed_count": batch["failed_count"],
            "confirmed_count": confirmed_count,
            "pending_review_count": pending_review_count,
            "created_at": batch["created_at"],
            "completed_at": batch.get("completed_at"),
            "current_task_id": batch.get("current_task_id"),
            "output_directory": str(batch["output_dir"]),
            "items": items,
        }

    def process_color_batch(batch_id: str) -> None:
        batch = color_batch_registry.get(batch_id)
        if not batch:
            return
        batch["status"] = "processing"
        batch["started_at"] = lifecycle_timestamp()
        batch["processing_stage"] = "batch_execution"
        if shared_task_registry is not None:
            shared_task_registry[batch_id] = batch
        emit_runtime_event(
            "COLOR_BATCH_STARTED",
            stage="batch_execution",
            result="started",
            operation="AUTO_COLOR_CORRECTION",
            batch_id=batch_id,
            status="processing",
            total_count=batch["total_count"],
            impact="batch_processing_running",
            action="process_queue_sequentially",
            feature_key=COLOR_CORRECTION_FEATURE_KEY,
            **{key: batch[key] for key in ("module_id", "operation_id", "trace_id")},
        )
        for task_id in batch["task_ids"]:
            record = task_registry.get(task_id)
            if not record or record.get("status") != "pending":
                continue
            batch["current_task_id"] = task_id
            execute_color_task(record)
            refresh_color_batch(batch)
        refresh_color_batch(batch)
        batch["status"] = "completed" if batch["completed_count"] > 0 else "failed"
        batch["progress"] = 100
        batch["current_task_id"] = None
        batch["completed_at"] = lifecycle_timestamp()
        batch["processing_stage"] = "batch_completion"
        if shared_task_registry is not None:
            shared_task_registry[batch_id] = batch
        emit_runtime_event(
            "COLOR_BATCH_COMPLETED",
            level=logging.INFO if batch["completed_count"] else logging.ERROR,
            stage="batch_completion",
            result="success" if batch["completed_count"] else "failed",
            error_category="" if batch["completed_count"] else "PRODUCT_ERROR",
            operation="AUTO_COLOR_CORRECTION",
            batch_id=batch_id,
            status=batch["status"],
            total_count=batch["total_count"],
            completed_count=batch["completed_count"],
            failed_count=batch["failed_count"],
            impact="batch_results_available" if batch["completed_count"] else "batch_output_unavailable",
            action="review_completed_items" if batch["completed_count"] else "check_task_failures_in_runtime_log",
            feature_key=COLOR_CORRECTION_FEATURE_KEY,
            **{key: batch[key] for key in ("module_id", "operation_id", "trace_id")},
        )

    def color_batch_worker_loop() -> None:
        while True:
            batch_id = color_batch_queue.get()
            try:
                process_color_batch(batch_id)
            except Exception as exc:
                batch = color_batch_registry.get(batch_id) or {}
                diagnostics = build_exception_diagnostics(
                    exc,
                    error_category="ENVIRONMENT_ERROR" if isinstance(exc, OSError) else "PRODUCT_ERROR",
                    error_stage="batch_worker",
                    trace_id=str(batch.get("trace_id") or ""),
                )
                if batch:
                    batch["status"] = "failed"
                    batch["processing_stage"] = "batch_worker"
                    batch["completed_at"] = lifecycle_timestamp()
                    batch["error_context"] = dict(diagnostics)
                    if shared_task_registry is not None:
                        shared_task_registry[batch_id] = batch
                emit_runtime_event(
                    "COLOR_BATCH_FAILED",
                    level=logging.ERROR,
                    stage="batch_worker",
                    result="failed",
                    operation="AUTO_COLOR_CORRECTION",
                    batch_id=batch_id,
                    status=str(batch.get("status") or "failed"),
                    total_count=batch.get("total_count"),
                    completed_count=batch.get("completed_count"),
                    failed_count=batch.get("failed_count"),
                    impact="batch_worker_stopped",
                    action="check_runtime_log_and_restart_backend",
                    **{
                        "feature_key": COLOR_CORRECTION_FEATURE_KEY,
                        "module_id": str(batch.get("module_id") or ""),
                        "operation_id": str(batch.get("operation_id") or ""),
                        **diagnostics,
                    },
                )
                raise
            finally:
                color_batch_queue.task_done()

    def ensure_color_batch_worker() -> None:
        with color_batch_worker_lock:
            worker = color_batch_worker_state.get("thread")
            if worker and worker.is_alive():
                return
            worker = threading.Thread(
                target=color_batch_worker_loop,
                name="hdde-color-batch-worker",
                daemon=True,
            )
            color_batch_worker_state["thread"] = worker
            worker.start()

    def invalidate_candidate_identity(
        record: dict[str, Any],
        candidate: dict[str, Any],
        *,
        current_output_sha256: str,
    ) -> None:
        registered_output_sha256 = str(candidate.get("output_sha256") or "").lower()
        candidate.update({
            "status": "INVALIDATED",
            "identity_status": RESULT_IDENTITY_MISMATCH,
            "current_output_sha256": current_output_sha256,
            "delivery_eligible": False,
            "preview_token": None,
            "reason": "当前候选文件内容与 Result 登记身份不一致，既有严格无损证据已失效。",
        })
        candidate["artifact_identity"] = {
            **dict(candidate.get("artifact_identity") or {}),
            "result_id": str(record.get("result_id") or ""),
            "candidate_id": str(candidate.get("candidate_id") or candidate.get("scheme_id") or ""),
            "registered_output_sha256": registered_output_sha256,
            "current_output_sha256": current_output_sha256,
            "matches_registered_output": False,
        }
        if str(record.get("winner_scheme_id") or "") == str(candidate.get("scheme_id") or ""):
            record["winner_public"] = {
                **dict(record.get("winner_public") or {}),
                "status": "INVALIDATED",
                "identity_status": RESULT_IDENTITY_MISMATCH,
                "delivery_eligible": False,
                "reason": "当前正式结果内容与登记身份不一致，既有质量证据已失效。",
                "quality_gate": {
                    "status": "FAIL",
                    "failure_reasons": [RESULT_IDENTITY_MISMATCH],
                },
            }
        if str(record.get("selected_scheme_id") or "") == str(candidate.get("scheme_id") or ""):
            result = record["result"]
            result.technical_status = TechnicalStatus.CANNOT_MEET_SAFELY
            result.delivery_gate_status = DeliveryGateStatus.CANNOT_MEET_SAFELY
            result.delivery_eligible = False
            result.delivery_decision_reason = "Result identity mismatch; registered evidence does not apply to current bytes."
            result.candidate_delivery_role = CandidateDeliveryRole.EVIDENCE_ONLY
            result.validation_status = "FAIL"
            result.validation_failures = [{
                "stage": 7,
                "code": RESULT_IDENTITY_MISMATCH,
                "message": "当前候选文件内容与登记 output_sha256 不一致。",
            }]
            result.failure_code = RESULT_IDENTITY_MISMATCH
            result.failure_reason = "当前候选文件内容与 Result 登记身份不一致。"
            result.metadata_preserved = False
            result.alpha_preserved = False
            result.metadata_details = {
                **dict(result.metadata_details or {}),
                "artifact_identity": dict(candidate["artifact_identity"]),
            }
            result.evidence_paths = {
                **dict(result.evidence_paths or {}),
                "artifact_identity": dict(candidate["artifact_identity"]),
                "lossless_verification": None,
            }
            task_result = record.get("task_result")
            if isinstance(task_result, dict):
                task_result.update({
                    "delivery_eligible": False,
                    "failure_code": RESULT_IDENTITY_MISMATCH,
                    "artifact_identity": dict(candidate["artifact_identity"]),
                })
        if shared_task_registry is not None:
            shared_task_registry[str(record["task_id"])] = record

    def delivery_candidate_public(record: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
        path_text = str(candidate.get("output_path") or "")
        output_path = Path(path_text) if path_text else None
        available = bool(candidate.get("status") == "AVAILABLE" and output_path and output_path.is_file())
        identity_valid = str(candidate.get("identity_status") or "") != RESULT_IDENTITY_MISMATCH
        public_status = str(candidate.get("status") or "NOT_AVAILABLE")
        if public_status == "AVAILABLE" and not available:
            public_status = "NOT_AVAILABLE"
        return {
            "scheme_id": str(candidate.get("scheme_id") or ""),
            "candidate_id": str(candidate.get("candidate_id") or candidate.get("scheme_id") or ""),
            "display_name": str(candidate.get("display_name") or ""),
            "format": str(candidate.get("format") or ""),
            "file_size": candidate.get("file_size"),
            "width": candidate.get("width"),
            "height": candidate.get("height"),
            "output_path": path_text or None,
            "applicable_scene": str(candidate.get("applicable_scene") or ""),
            "recommended": bool(candidate.get("recommended")),
            "reason": str(candidate.get("reason") or ""),
            "status": public_status,
            "selected": str(candidate.get("scheme_id") or "") == str(record.get("selected_scheme_id") or ""),
            "preview_url": preview_url(candidate.get("preview_token")) if available else None,
            "visual_review_status": str(candidate.get("visual_review_status") or VisualReviewStatus.NOT_AVAILABLE.value),
            "delivery_eligible": bool(candidate.get("delivery_eligible")) if identity_valid else False,
            "identity_status": str(candidate.get("identity_status") or "VALID"),
            "pixel_identical": candidate.get("pixel_identical") if identity_valid else None,
            "pixel_diff_count": candidate.get("pixel_diff_count") if identity_valid else None,
            "max_channel_diff": candidate.get("max_channel_diff") if identity_valid else None,
            "lossless_verified": candidate.get("lossless_verified") if identity_valid else False,
            "source_size": candidate.get("source_size"),
            "output_size": candidate.get("output_size"),
            "saved_bytes": candidate.get("saved_bytes"),
            "saved_percent": candidate.get("saved_percent"),
            "lossless_gain": candidate.get("lossless_gain"),
            "alpha_optimized": candidate.get("alpha_optimized") if identity_valid else None,
            "verification_status": candidate.get("verification_status") if identity_valid else "FAIL",
            "quality_gate": dict(candidate.get("quality_gate") or {}) if identity_valid else {
                "status": "FAIL",
                "failure_reasons": [RESULT_IDENTITY_MISMATCH],
            },
        }

    def select_delivery_candidate(record: dict[str, Any], candidate: dict[str, Any]) -> None:
        if (
            record.get("selection_policy")
            and str(candidate.get("scheme_id") or "") != str(record.get("winner_scheme_id") or "")
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "CANDIDATE_SELECTION_LOCKED", "message": "当前任务只允许交付自动择优结果。"},
            )
        path_text = str(candidate.get("output_path") or "")
        output_path = Path(path_text).resolve() if path_text else None
        if candidate.get("status") != "AVAILABLE" or output_path is None or not output_path.is_file():
            raise HTTPException(status_code=409, detail={"code": "CANDIDATE_NOT_APPLICABLE", "message": str(candidate.get("reason") or "当前方案不可用。")})
        output_dir = Path(record["output_dir"]).resolve()
        if output_dir not in output_path.parents:
            raise HTTPException(status_code=403, detail={"code": "CANDIDATE_PATH_OUTSIDE_OUTPUT", "message": "候选文件不在受控输出目录内。"})

        registered_output_sha256 = str(candidate.get("output_sha256") or "").lower()
        try:
            current_output_sha256 = _sha256_file(output_path).lower()
        except OSError:
            current_output_sha256 = ""
        if not registered_output_sha256 or current_output_sha256 != registered_output_sha256:
            invalidate_candidate_identity(
                record,
                candidate,
                current_output_sha256=current_output_sha256,
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": RESULT_IDENTITY_MISMATCH,
                    "message": "当前候选文件内容与登记身份不一致，不能继续选择或交付。",
                },
            )

        result = record["result"]
        is_lossless = str(candidate.get("scheme_id")) in {
            PNG_LOSSLESS_SCHEME,
            WEBP_LOSSLESS_SCHEME,
        }
        automated_quality_passed = bool(
            not is_lossless and dict(candidate.get("quality_gate") or {}).get("status") == "PASS"
        )
        lossless_verification = dict((candidate.get("metadata_details") or {}).get("lossless_verification") or {})
        artifact_identity = dict(candidate.get("artifact_identity") or {})
        if is_lossless and not (
            candidate.get("lossless_verified") is True
            and candidate.get("pixel_identical") is True
            and candidate.get("pixel_diff_count") == 0
            and candidate.get("max_channel_diff") == 0
            and candidate.get("verification_status") == "PASS"
            and lossless_verification.get("artifact_identity_stable") is True
            and str(lossless_verification.get("output_sha256") or "").lower() == registered_output_sha256
            and str(artifact_identity.get("lossless_verification_output_sha256") or "").lower() == registered_output_sha256
        ):
            raise HTTPException(status_code=409, detail={"code": "LOSSLESS_VERIFICATION_REQUIRED", "message": "无损格式方案缺少零像素变化硬证据。"})
        if not is_lossless and not automated_quality_passed:
            raise HTTPException(status_code=409, detail={"code": "JPG_QUALITY_GATE_REQUIRED", "message": "JPG 方案缺少自动质量安全门通过证据。"})
        source_size = result.source_size_bytes
        output_size = int(candidate["file_size"])
        candidate_format = str(candidate.get("format") or "")
        output_format = {"JPG": "JPEG", "PNG": "PNG", "WEBP": "WEBP"}.get(candidate_format)
        if output_format is None:
            raise HTTPException(status_code=409, detail={"code": "CANDIDATE_FORMAT_INVALID", "message": "候选格式无效。"})
        result.technical_status = TechnicalStatus.TARGET_MET if is_lossless else TechnicalStatus.TARGET_MET_WITH_REENCODE
        result.visual_review_status = VisualReviewStatus(str(candidate.get("visual_review_status") or VisualReviewStatus.NOT_REQUIRED.value))
        result.output_created = True
        result.output_path = str(output_path)
        result.output_sha256 = str(candidate.get("output_sha256") or "")
        result.output_format = output_format
        result.output_dimensions = {"width": int(candidate["width"]), "height": int(candidate["height"])}
        result.output_size_bytes = output_size
        result.size_reduction_bytes = source_size - output_size if source_size is not None else None
        result.size_reduction_ratio = result.size_reduction_bytes / source_size if source_size else None
        result.dimension_scale_ratio = 1.0
        result.lossy = not is_lossless
        result.reencoded = True
        result.resized = False
        result.metadata_preserved = bool(lossless_verification.get("metadata_verified")) if is_lossless else automated_quality_passed
        result.metadata_details = {
            **dict(result.metadata_details or {}),
            "hdde_output_metadata": dict(candidate.get("metadata_details") or {}),
            "target_format": str(record.get("target_format") or ""),
            "effective_target_format": str(record.get("effective_target_format") or ""),
            "format_policy": str(record.get("format_policy") or ""),
            "smart_compression": dict(record.get("smart_compression_details") or {}),
        }
        source_has_real_transparency = bool(record.get("source_has_real_transparency"))
        alpha_handling = dict(record.get("alpha_handling") or {})
        result.alpha_preserved = bool(lossless_verification.get("alpha_preserved")) if is_lossless else not source_has_real_transparency
        result.alpha_details = {
            **dict(result.alpha_details or {}),
            "alpha_present": source_has_real_transparency,
            "alpha_channel_preserved": bool(lossless_verification.get("alpha_preserved")) if is_lossless else not source_has_real_transparency,
            "alpha_exact": bool(lossless_verification.get("alpha_exact")) if is_lossless else None,
            "alpha_optimized": bool(candidate.get("alpha_optimized")) if is_lossless else False,
            "conversion_action": alpha_handling.get("action"),
            "conversion_background_rgb": alpha_handling.get("background_rgb"),
        }
        result.warnings = (
            ["透明区域已使用白色背景合成后输出 JPG。"]
            if alpha_handling.get("action") == "FLATTEN_ON_WHITE"
            else []
        )
        result.failure_code = None
        result.failure_reason = None
        result.risk_reasons = []
        result.validation_status = str(candidate.get("verification_status") or "PASS") if is_lossless else "PASS"
        result.validation_failures = []
        result.evidence_paths = {
            "generation_parent": "SOURCE",
            "source_sha256": result.source_sha256,
            "output_metadata": dict(candidate.get("metadata_details") or {}),
            "lossless_verification": lossless_verification if is_lossless else None,
            "automated_quality_gate": dict(candidate.get("quality_gate") or {}) if not is_lossless else None,
            "target_format": str(record.get("target_format") or ""),
            "effective_target_format": str(record.get("effective_target_format") or ""),
            "format_policy": str(record.get("format_policy") or ""),
            "alpha_handling": alpha_handling,
            "artifact_identity": artifact_identity,
        }
        apply_delivery_gate(
            result,
            strict_lossless_evidence=is_lossless,
            automated_quality_evidence=automated_quality_passed,
            evidence_candidate=True,
        )
        candidate["visual_review_status"] = str(result.visual_review_status)
        candidate["delivery_eligible"] = bool(result.delivery_eligible)
        record.update({
            "selected_scheme_id": str(candidate["scheme_id"]),
            "output_path": output_path,
            "output_sha256": result.output_sha256,
            "output_preview_token": candidate.get("preview_token"),
            "review_note": str(candidate.get("review_note") or ""),
            "review_output_sha256_before": result.output_sha256,
            "review_output_sha256_after": result.output_sha256,
            "result_file": str(output_path),
        })
        task_result = record.get("task_result")
        if isinstance(task_result, dict):
            task_result.update({
                "result_file": str(output_path),
                "output_path": str(output_path),
                "selected_scheme_id": str(candidate["scheme_id"]),
                "candidate_id": str(candidate.get("candidate_id") or candidate["scheme_id"]),
                "source_sha256": result.source_sha256,
                "output_sha256": result.output_sha256,
                "delivery_eligible": bool(result.delivery_eligible),
                "artifact_identity": artifact_identity,
            })
        if shared_task_registry is not None:
            shared_task_registry[str(record["task_id"])] = record

    def select_source_winner(record: dict[str, Any], winner: Mapping[str, Any]) -> None:
        result = record["result"]
        result.technical_status = TechnicalStatus.NO_PROCESSING_NEEDED
        result.visual_review_status = VisualReviewStatus.NOT_REQUIRED
        result.output_created = False
        result.output_path = str(result.source_path)
        result.output_sha256 = str(result.source_sha256)
        result.output_format = str(result.source_format)
        result.output_dimensions = dict(result.source_dimensions or {})
        result.output_size_bytes = result.source_size_bytes
        result.size_reduction_bytes = 0
        result.size_reduction_ratio = 0.0
        result.dimension_scale_ratio = 1.0
        result.lossy = False
        result.reencoded = False
        result.resized = False
        result.metadata_preserved = True
        result.metadata_details = {
            **dict(result.metadata_details or {}),
            "target_format": str(record.get("target_format") or ""),
            "effective_target_format": str(record.get("effective_target_format") or ""),
            "format_policy": str(record.get("format_policy") or ""),
            "smart_compression": dict(record.get("smart_compression_details") or {}),
        }
        result.alpha_preserved = True
        result.alpha_details = {
            **dict(result.alpha_details or {}),
            "alpha_present": bool(record.get("source_has_real_transparency")),
            "alpha_channel_preserved": True,
            "alpha_exact": True,
            "alpha_optimized": False,
        }
        result.warnings = []
        result.failure_code = None
        result.failure_reason = None
        result.risk_reasons = []
        result.validation_status = "PASS"
        result.validation_failures = []
        result.evidence_paths = {
            "generation_parent": "SOURCE",
            "source_sha256": result.source_sha256,
            "selection_policy": record.get("selection_policy"),
            "winner": dict(winner),
        }
        apply_delivery_gate(result, evidence_candidate=False)
        record.update({
            "selected_scheme_id": KEEP_ORIGINAL_SCHEME,
            "output_path": None,
            "output_sha256": result.source_sha256,
            "output_preview_token": None,
            "review_note": "",
            "review_output_sha256_before": result.source_sha256,
            "review_output_sha256_after": result.source_sha256,
            "result_file": None,
        })

    def public_result(record: dict[str, Any]) -> dict[str, Any]:
        result = record["result"]
        raw = result.to_dict()
        source_path = Path(record["source_path"])
        output_path = Path(record["output_path"]) if record.get("output_path") else None
        output_exists = bool(result.output_created and output_path and output_path.exists())
        candidate_available = output_exists and raw.get("candidate_delivery_role") != "NONE"
        source_preview_url = preview_url(record.get("source_preview_token"))
        output_preview_url = preview_url(record.get("output_preview_token")) if candidate_available else None
        request = record.get("request") or {}
        long_validation = record.get("long_image_validation") or build_long_image_validation(record.get("source_metadata") or {}, request)
        resize_validation = record.get("resize_validation") or build_resize_validation(record.get("source_metadata") or {}, request, result)
        ui = {
            "source_display_name": source_path.name,
            "output_display_name": output_path.name if candidate_available else None,
            "source_preview_url": source_preview_url,
            "output_preview_url": output_preview_url,
            "display_path": str(record["output_dir"]) if candidate_available else None,
            "effective_output_root": str(record["effective_output_root"]),
            "output_directory": str(record["output_dir"]) if candidate_available else None,
            "output_root_source": record.get("output_root_source") or "saved_default",
            "can_open_folder": candidate_available,
            "candidate_available": candidate_available,
            "visual_review_required": candidate_available and raw.get("visual_review_status") == VisualReviewStatus.PENDING.value,
            "review_note": record.get("review_note") or "",
            "feedback_package": record.get("feedback_package"),
            "smart_compression_summary": str(record.get("smart_compression_summary") or ""),
            "smart_compression_details": dict(record.get("smart_compression_details") or {}),
            "applied_limits": {
                "max_width": request.get("max_width"),
                "max_height": request.get("max_height"),
                "max_file_size_bytes": request.get("max_file_size_bytes"),
                "target_width": request.get("target_width"),
                "target_height": request.get("target_height"),
                "scale_ratio": request.get("scale_ratio"),
                "target_short_side": resize_validation.get("target_short_side"),
            },
            **long_validation,
            **resize_validation,
        }
        candidate_options = [
            delivery_candidate_public(record, candidate)
            for candidate in list(record.get("candidate_options") or [])
            if str(candidate.get("scheme_id") or "") == str(record.get("winner_scheme_id") or "")
            and candidate.get("status") == "AVAILABLE"
        ]
        winner_public = dict(record.get("winner_public") or {})
        winner_candidate = next((
            candidate for candidate in list(record.get("candidate_options") or [])
            if str(candidate.get("scheme_id") or "") == str(record.get("winner_scheme_id") or "")
        ), None)
        if winner_candidate is not None:
            winner_public = {
                **delivery_candidate_public(record, winner_candidate),
                "source_selected": False,
            }
        if record.get("selection_policy"):
            raw.update({
                "candidates": candidate_options,
                "winner": winner_public,
                "winner_scheme_id": record.get("winner_scheme_id"),
                "selection_policy": record.get("selection_policy"),
                "public_output_count": int(record.get("public_output_count") or 0),
                "recommended_scheme_id": record.get("recommended_scheme_id"),
                "selected_scheme_id": record.get("selected_scheme_id"),
                "recommendation_reason": record.get("recommendation_reason") or "",
            })
            ui.update({
                "candidate_count": len(candidate_options),
                "available_candidate_count": sum(item["status"] == "AVAILABLE" for item in candidate_options),
                "winner_scheme_id": record.get("winner_scheme_id"),
                "winner_is_source": record.get("winner_scheme_id") == KEEP_ORIGINAL_SCHEME,
                "public_output_count": int(record.get("public_output_count") or 0),
                "recommended_scheme_id": record.get("recommended_scheme_id"),
                "selected_scheme_id": record.get("selected_scheme_id"),
            })
        return {
            "task": public_task(record),
            "result": raw,
            "ui": ui,
        }

    def feedback_task_parameters(record: Mapping[str, Any]) -> dict[str, Any]:
        request = record.get("request") if isinstance(record.get("request"), Mapping) else {}
        request_context = request.get("request_context") if isinstance(request.get("request_context"), Mapping) else {}
        mode = str(request.get("operation_mode") or "")
        if mode == OperationMode.LOSSLESS_COMPRESSION.value:
            return {}
        if mode == OperationMode.RESIZE_REDUCTION.value:
            strategy = str(request_context.get("resize_strategy") or "")
            if strategy == "SHORT_SIDE":
                return {"target_short_side": request_context.get("target_short_side")}
            if strategy == "RATIO":
                return {"scale_ratio": request.get("scale_ratio")}
            if strategy == "WIDTH":
                return {"target_width": request_context.get("target_width")}
            if strategy == "HEIGHT":
                return {"target_height": request_context.get("target_height")}
            return {
                name: request.get(name)
                for name in ("scale_ratio", "target_width", "target_height")
                if request.get(name) is not None
            }
        return {
            name: request.get(name)
            for name in ("max_width", "max_height", "max_file_size_bytes")
            if request.get(name) is not None
        }

    def build_feedback_task(record: Mapping[str, Any], result_data: Mapping[str, Any]) -> dict[str, Any]:
        source = record.get("source_metadata") if isinstance(record.get("source_metadata"), Mapping) else {}
        return {
            "contract_version": result_data.get("task_contract_version"),
            "task_id": result_data.get("task_id"),
            "operation_mode": result_data.get("operation_mode"),
            "parameters": feedback_task_parameters(record),
            "source": {
                "display_name": Path(str(source.get("filename") or result_data.get("source_path") or "image")).name,
                "format": result_data.get("source_format"),
                "dimensions": result_data.get("source_dimensions"),
                "size_bytes": result_data.get("source_size_bytes"),
            },
            "output_root_type": record.get("output_root_source"),
            "function_directory_name": Path(str(record.get("output_dir") or "")).name,
            "created_at": record.get("created_at"),
        }

    def build_feedback_review(record: Mapping[str, Any], result_data: Mapping[str, Any]) -> dict[str, Any]:
        visual_status = str(result_data.get("visual_review_status") or VisualReviewStatus.NOT_AVAILABLE.value)
        output_sha256 = result_data.get("output_sha256")
        reason = result_data.get("delivery_decision_reason")
        if visual_status == VisualReviewStatus.NOT_REQUIRED.value:
            return {
                "review_required": False,
                "visual_review_status": visual_status,
                "review_result": VisualReviewStatus.NOT_REQUIRED.value,
                "review_note": None,
                "reviewed_at": None,
                "output_sha256": output_sha256,
                "reason": reason,
            }
        if visual_status == VisualReviewStatus.PENDING.value:
            return {
                "review_required": True,
                "visual_review_status": visual_status,
                "review_result": VisualReviewStatus.PENDING.value,
                "review_note": None,
                "reviewed_at": None,
                "output_sha256": output_sha256,
                "reason": reason,
            }
        if visual_status in {
            VisualReviewStatus.PASS.value,
            VisualReviewStatus.PASS_WITH_NOTES.value,
            VisualReviewStatus.FAIL.value,
        }:
            return {
                "review_required": True,
                "visual_review_status": visual_status,
                "review_result": visual_status,
                "review_note": record.get("review_note") or None,
                "reviewed_at": record.get("reviewed_at"),
                "output_sha256": output_sha256,
                "output_sha256_before": record.get("review_output_sha256_before") or output_sha256,
                "output_sha256_after": record.get("review_output_sha256_after") or output_sha256,
                "reason": reason,
            }
        return {
            "review_required": False,
            "visual_review_status": visual_status,
            "review_result": VisualReviewStatus.NOT_AVAILABLE.value,
            "review_note": None,
            "reviewed_at": None,
            "output_sha256": output_sha256,
            "reason": result_data.get("failure_reason") or reason or "当前任务没有可供人工复核的候选结果。",
        }

    def safe_node_version() -> str:
        try:
            completed = subprocess.run(
                ["node", "--version"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            version = str(completed.stdout or "").strip()
            return version if completed.returncode == 0 and version else "unavailable"
        except (OSError, subprocess.SubprocessError):
            return "unavailable"

    def build_feedback_environment(generated_at: str) -> dict[str, Any]:
        try:
            from runtime import APP_VERSION
        except Exception:
            APP_VERSION = "unknown"
        frontend_version = "unknown"
        package_json = Path(__file__).resolve().parents[1] / "package.json"
        try:
            frontend_version = str(json.loads(package_json.read_text(encoding="utf-8")).get("version") or "unknown")
        except (OSError, ValueError, TypeError):
            pass
        return {
            "application_name": "影界 HDDE",
            "application_version": APP_VERSION,
            "api_version": IMAGE_COMPRESSION_API_VERSION,
            "frontend_build_version": frontend_version,
            "python_version": platform.python_version(),
            "node_version": safe_node_version(),
            "operating_system": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
            },
            "generated_at": generated_at,
        }

    def build_feedback_validation(
        record: Mapping[str, Any],
        result_data: Mapping[str, Any],
        review_data: Mapping[str, Any],
        package_path: Path,
    ) -> dict[str, Any]:
        request = record.get("request") if isinstance(record.get("request"), Mapping) else {}
        resize_validation = record.get("resize_validation") if isinstance(record.get("resize_validation"), Mapping) else {}
        long_validation = record.get("long_image_validation") if isinstance(record.get("long_image_validation"), Mapping) else {}
        source_path = Path(str(record.get("source_path") or ""))
        output_path = Path(str(record.get("output_path") or "")) if record.get("output_path") else None
        output_info = None
        output_decode_error = None
        if output_path is not None and output_path.is_file():
            try:
                output_info = read_image_info(output_path)
            except Exception as exc:
                output_decode_error = type(exc).__name__
        source_sha256_current = _sha256_file(source_path) if source_path.is_file() else None
        output_dimensions = result_data.get("output_dimensions") if isinstance(result_data.get("output_dimensions"), Mapping) else {}
        source_dimensions = result_data.get("source_dimensions") if isinstance(result_data.get("source_dimensions"), Mapping) else {}
        output_width = int(output_dimensions.get("width") or 0)
        output_height = int(output_dimensions.get("height") or 0)
        source_width = int(source_dimensions.get("width") or 0)
        source_height = int(source_dimensions.get("height") or 0)
        aspect_ratio_preserved = None
        if source_width and source_height and output_width and output_height:
            aspect_ratio_preserved = abs(round(source_width * output_height / source_height) - output_width) <= 1
        output_created = bool(result_data.get("output_created"))
        output_directory = Path(str(record.get("output_dir") or "")).resolve()
        output_path_aligned = bool(output_path and output_path.is_file() and output_path.resolve().parent == output_directory)
        upload_limits = {
            "max_width": request.get("max_width"),
            "max_height": request.get("max_height"),
            "max_file_size_bytes": request.get("max_file_size_bytes"),
        }
        upload_limit_validation = {
            **upload_limits,
            "width_within_limit": (
                output_width <= int(request["max_width"])
                if output_created and request.get("max_width") is not None
                else None
            ),
            "height_within_limit": (
                output_height <= int(request["max_height"])
                if output_created and request.get("max_height") is not None
                else None
            ),
            "size_within_limit": (
                int(result_data.get("output_size_bytes") or 0) <= int(request["max_file_size_bytes"])
                if output_created and request.get("max_file_size_bytes") is not None
                else None
            ),
        }
        return {
            "task_contract_validation": {
                "status": "PASS" if request.get("contract_version") == result_data.get("task_contract_version") else "FAIL",
                "contract_version": request.get("contract_version"),
                "task_id_aligned": request.get("task_id") == result_data.get("task_id"),
            },
            "result_contract_validation": {
                "status": "PASS" if tuple(result_data) == RESULT_FIELD_NAMES and len(result_data) == 50 else "FAIL",
                "contract_version": result_data.get("contract_version"),
                "field_count": len(result_data),
            },
            "source_sha256_protected": bool(
                source_sha256_current
                and source_sha256_current == result_data.get("source_sha256")
            ),
            "source_sha256": result_data.get("source_sha256"),
            "output_created": output_created,
            "output_full_decode": (
                bool(output_info)
                if output_created
                else None
            ),
            "output_decode_error": output_decode_error,
            "format_validation": (
                bool(output_info and output_info.get("format") == result_data.get("output_format"))
                if output_created
                else None
            ),
            "dimension_validation": (
                bool(output_info and output_info.get("dimensions") == result_data.get("output_dimensions"))
                if output_created
                else None
            ),
            "aspect_ratio_preserved": aspect_ratio_preserved,
            "crop_applied": False if output_created else None,
            "padding_applied": False if output_created else None,
            "stretch_applied": (
                not aspect_ratio_preserved
                if output_created and aspect_ratio_preserved is not None
                else None
            ),
            "upscale_applied": (
                bool(output_width > source_width or output_height > source_height)
                if output_created and source_width and source_height
                else None
            ),
            "output_directory_alignment": output_path_aligned if output_created else None,
            "output_filename_alignment": (
                output_path.name == Path(str(result_data.get("output_path") or "")).name
                if output_created and output_path
                else None
            ),
            "feedback_package_directory_alignment": package_path.resolve().parent == output_directory,
            "output_sha256": result_data.get("output_sha256"),
            "review_output_sha256_before": review_data.get("output_sha256_before") or review_data.get("output_sha256"),
            "review_output_sha256_after": review_data.get("output_sha256_after") or review_data.get("output_sha256"),
            "delivery_gate_status": result_data.get("delivery_gate_status"),
            "delivery_eligible": result_data.get("delivery_eligible"),
            "fixed_short_side_validation": {
                "applicable": resize_validation.get("resize_strategy") == "SHORT_SIDE",
                "target_short_side": resize_validation.get("target_short_side"),
                "actual_target_width": resize_validation.get("actual_target_width"),
                "actual_target_height": resize_validation.get("actual_target_height"),
                "actual_short_side": (
                    min(output_width, output_height)
                    if output_created and output_width and output_height
                    else None
                ),
                "passed": (
                    min(output_width, output_height) == int(resize_validation["target_short_side"])
                    if output_created
                    and output_width
                    and output_height
                    and resize_validation.get("resize_strategy") == "SHORT_SIDE"
                    and resize_validation.get("target_short_side") is not None
                    else None
                ),
            },
            "upload_limit_validation": upload_limit_validation,
            "is_long_image": bool(long_validation.get("is_long_image")),
        }

    def build_feedback_long_validation(
        record: Mapping[str, Any],
        result_data: Mapping[str, Any],
    ) -> dict[str, Any]:
        long_validation = dict(record.get("long_image_validation") or {})
        visual_status = str(result_data.get("visual_review_status") or "")
        if visual_status == VisualReviewStatus.PENDING.value:
            segment_status = VisualReviewStatus.PENDING.value
        elif visual_status == VisualReviewStatus.NOT_REQUIRED.value:
            segment_status = VisualReviewStatus.NOT_REQUIRED.value
        else:
            segment_status = "NOT_RECORDED"
        actual_dimensions = result_data.get("output_dimensions") if isinstance(result_data.get("output_dimensions"), Mapping) else None
        return {
            "is_long_image": True,
            "detection_basis": {
                "source_width": long_validation.get("source_width"),
                "source_height": long_validation.get("source_height"),
                "minimum_aspect_ratio": 3,
                "minimum_height": 4000,
            },
            "source_aspect_ratio": long_validation.get("source_aspect_ratio"),
            "preview_default_mode": long_validation.get("preview_default_mode"),
            "estimated_output_dimensions": {
                "width": long_validation.get("estimated_output_width"),
                "height": long_validation.get("estimated_output_height"),
            },
            "actual_output_dimensions": actual_dimensions,
            "maximum_height_applied": bool(long_validation.get("height_limit_applied")),
            "width_risk_level": long_validation.get("long_image_risk_level"),
            "text_risk_warnings": list(long_validation.get("long_image_warnings") or []),
            "segment_review_status": {
                "top": segment_status,
                "middle": segment_status,
                "bottom": segment_status,
            },
            "width_risk_policy_version": long_validation.get("long_image_width_risk_policy_version"),
        }

    def feedback_summary_conclusion(result_data: Mapping[str, Any]) -> str:
        technical = str(result_data.get("technical_status") or "")
        visual = str(result_data.get("visual_review_status") or "")
        delivery = str(result_data.get("delivery_gate_status") or "")
        mode = str(result_data.get("operation_mode") or "")
        if technical == TechnicalStatus.PROCESSING_FAILED.value:
            return "处理执行失败，反馈包仅用于诊断，不代表存在正式交付文件。"
        if (
            technical == TechnicalStatus.CANNOT_MEET_SAFELY.value
            or visual == VisualReviewStatus.FAIL.value
            or delivery == "CANNOT_MEET_SAFELY"
        ):
            return "当前任务未形成可安全交付的结果，请查看失败原因和风险信息。"
        if visual == VisualReviewStatus.PASS_WITH_NOTES.value:
            return "结果可用，但包含人工复核备注，请结合备注交付。"
        if visual == VisualReviewStatus.PENDING.value or delivery == "REVIEW_REQUIRED":
            return "处理结果已经生成，但图片尺寸或编码发生变化，需要完成实际视觉复核后才能确认交付。"
        if (
            mode == OperationMode.LOSSLESS_COMPRESSION.value
            and visual == VisualReviewStatus.NOT_REQUIRED.value
            and delivery == "DELIVERY_READY"
        ):
            if technical == TechnicalStatus.NO_PROCESSING_NEEDED.value:
                return "原图已经满足严格无损请求，未生成重复文件，无需人工视觉复核，可以交付原图。"
            return "严格无损证据完整，图片尺寸和解码像素保持一致，无需人工视觉复核，可以交付。"
        if result_data.get("delivery_eligible"):
            return "当前技术与复核证据满足交付门禁，可以按当前结论交付。"
        return "当前证据不足以确认交付，请查看验证、风险和失败信息。"

    def build_feedback_summary(
        package_id: str,
        result_data: Mapping[str, Any],
        validation_data: Mapping[str, Any],
    ) -> str:
        warnings = list(result_data.get("warnings") or [])
        lines = [
            "# 影界图片压缩测试反馈包",
            "",
            f"- 反馈包编号：`{package_id}`",
            f"- 任务编号：`{result_data.get('task_id')}`",
            f"- 处理模式：`{result_data.get('operation_mode')}`",
            f"- 技术状态：`{result_data.get('technical_status')}`",
            f"- 视觉状态：`{result_data.get('visual_review_status')}`",
            f"- 交付状态：`{result_data.get('delivery_gate_status')}`",
            f"- 是否可以交付：`{str(bool(result_data.get('delivery_eligible'))).lower()}`",
            f"- 是否需要人工复核：`{str(result_data.get('visual_review_status') == VisualReviewStatus.PENDING.value).lower()}`",
            f"- 输出是否生成：`{str(bool(result_data.get('output_created'))).lower()}`",
            f"- failure_code：`{result_data.get('failure_code') if result_data.get('failure_code') is not None else 'null'}`",
            f"- warnings：`{json.dumps(warnings, ensure_ascii=False)}`",
            f"- 已识别为长图：`{str(bool(validation_data.get('is_long_image'))).lower()}`",
            "",
            f"最终结论：{feedback_summary_conclusion(result_data)}",
            "",
            "本包默认不包含用户原图、输出图片、私人绝对路径、账号信息、密钥或任何在线上传内容。",
        ]
        return "\n".join(lines) + "\n"

    def error_result(message: str, *, code: str = "IMAGE_COMPRESSION_API_ERROR") -> dict[str, Any]:
        return {"code": code, "message": message}

    def require_compression_directory() -> dict[str, Path]:
        return user_dirs_provider()

    @app.get("/api/image-compression/capabilities")
    async def image_compression_capabilities():
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "data": {
                "api_version": IMAGE_COMPRESSION_API_VERSION,
                "server_session_id": server_session_id,
                "task_contract_version": TASK_CONTRACT_VERSION,
                "result_contract_version": RESULT_CONTRACT_VERSION,
                "status": "BETA",
                "modes": [
                    {
                        "value": DELIVERY_OPTIMIZATION_MODE,
                        "label": "交付方案",
                        "formats": ["PNG", "JPEG", "WEBP"],
                        "target_formats": ["SMART_COMPRESSION", "PRESERVE_FORMAT", "JPEG", "PNG", "WEBP"],
                        "visual_review": "PER_SELECTED_CANDIDATE",
                        "candidate_schemes": ["PNG_LOSSLESS", "JPG_HIGH_QUALITY", "JPG_BALANCED", "WEBP_LOSSLESS"],
                    },
                    {
                        "value": OperationMode.LOSSLESS_COMPRESSION.value,
                        "label": "PNG 无损压缩",
                        "formats": ["PNG"],
                        "visual_review": "NOT_REQUIRED",
                    },
                    {
                        "value": OperationMode.RESIZE_REDUCTION.value,
                        "label": "尺寸缩减",
                        "formats": ["PNG", "JPEG"],
                        "visual_review": "REQUIRED_FOR_CHANGED_OUTPUT",
                    },
                    {
                        "value": OperationMode.UPLOAD_ADAPTATION.value,
                        "label": "上传适配",
                        "formats": ["PNG", "JPEG"],
                        "visual_review": "REQUIRED_FOR_CHANGED_OUTPUT",
                    },
                ],
                "limits": {"max_upload_bytes": MAX_UPLOAD_BYTES, "max_upload_label": _format_bytes(MAX_UPLOAD_BYTES)},
                "defaults": {
                    "resize_strategy": "SHORT_SIDE",
                    "resize_target_short_side": 1080,
                    "resize_scale_ratio": 0.75,
                    "upload_max_width": 1920,
                    "upload_max_height": 1080,
                    "upload_max_file_size_bytes": 2 * 1024 * 1024,
                    "long_image_upload_max_width": 1080,
                    "long_image_upload_max_height": None,
                },
                "long_image_detection": {"minimum_aspect_ratio": 3, "minimum_height": 4000, "ordinary_portrait_ratio_excluded_through": "9:16"},
                "long_image_width_risk_policy_version": LONG_IMAGE_WIDTH_RISK_POLICY_VERSION,
                "jpeg_lossless_supported": False,
                "online_upload": False,
                "output_settings_endpoint": "/api/image-compression/output-settings",
                "fixed_function_directories": dict(FUNCTION_DIRECTORY_BY_MODE),
            },
        }

    @app.get("/api/image-compression/output-settings")
    async def image_compression_output_settings():
        require_compression_directory()
        settings = output_settings()
        checked = validate_output_root(settings["saved_default_root"], source="saved_default")
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "data": {
                **settings,
                "effective_output_root": checked["normalized_path"],
                "output_root_writable": bool(checked.get("writable")),
                "fixed_function_directories": {
                    mode: str(Path(checked["normalized_path"]) / directory_name)
                    for mode, directory_name in FUNCTION_DIRECTORY_BY_MODE.items()
                },
                "folder_selection_endpoint": "/api/output/select-popup",
            },
        }

    @app.post("/api/image-compression/output-settings/default")
    async def image_compression_set_default_output(payload: dict = Body(default_factory=dict)):
        require_compression_directory()
        if set(payload) != {"output_root"}:
            raise HTTPException(status_code=400, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": "默认输出目录请求字段不正确。"})
        checked = validate_output_root(str(payload.get("output_root") or ""), source="saved_default")
        if output_default_saver is None:
            raise HTTPException(status_code=503, detail={"code": "OUTPUT_SETTINGS_UNAVAILABLE", "message": "当前运行环境无法保存默认输出目录。"})
        output_default_saver(checked["normalized_path"])
        return {"code": 200, "status": "success", "success": True, "data": {"saved_default_root": checked["normalized_path"], "effective_output_root": checked["normalized_path"], "output_root_writable": True}}

    @app.post("/api/image-compression/output-settings/restore")
    async def image_compression_restore_default_output(payload: dict = Body(default_factory=dict)):
        require_compression_directory()
        if payload:
            raise HTTPException(status_code=400, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": "恢复默认目录不接受附加字段。"})
        settings = output_settings()
        checked = validate_output_root(settings["built_in_default_root"], source="built_in_default")
        if output_default_saver is None:
            raise HTTPException(status_code=503, detail={"code": "OUTPUT_SETTINGS_UNAVAILABLE", "message": "当前运行环境无法保存默认输出目录。"})
        output_default_saver(checked["normalized_path"])
        return {"code": 200, "status": "success", "success": True, "data": {"saved_default_root": checked["normalized_path"], "effective_output_root": checked["normalized_path"], "output_root_writable": True}}

    def create_compression_intake(
        content: bytes,
        raw_filename: str,
        lineage: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        user_dirs = require_compression_directory()
        prune_tokens()
        if not raw_filename or raw_filename != Path(raw_filename).name or "/" in raw_filename or "\\" in raw_filename:
            raise HTTPException(status_code=400, detail="文件名不得包含目录或路径穿越片段。")
        filename = _safe_name(raw_filename)
        suffix = Path(filename).suffix.lower()
        if suffix not in COMPRESSION_INTAKE_EXTENSIONS:
            raise HTTPException(status_code=415, detail="仅支持 PNG、JPG、JPEG、WebP 文件。")
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="文件超过本地安全接收上限 50 MB。")
        intake_root = Path(user_dirs["tmp_dir"]).resolve() / "image-compression-intake"
        task_dir = intake_root / f"intake_{uuid.uuid4().hex}"
        task_dir.mkdir(parents=True, exist_ok=True)
        stored = task_dir / filename
        try:
            stored.write_bytes(content)
            info = read_image_info(stored, allow_webp=True)
        except Exception as exc:
            shutil.rmtree(task_dir, ignore_errors=True)
            code = getattr(exc, "failure_code", None) or "SOURCE_DECODE_FAILED"
            raise HTTPException(status_code=400, detail=error_result("图片无法通过完整解码校验。", code=code)) from exc
        expected_format = {".png": "PNG", ".webp": "WEBP"}.get(suffix, "JPEG")
        if info["format"] != expected_format:
            shutil.rmtree(task_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=error_result("文件扩展名与图片实际格式不一致。", code="SOURCE_EXTENSION_MAGIC_MISMATCH"))
        oriented_width, oriented_height = dimensions_after_exif_orientation(
            info["dimensions"]["width"],
            info["dimensions"]["height"],
            info.get("exif_orientation"),
        )
        lineage_fields = result_lineage_fields(lineage)
        source_token = issue_token(
            stored,
            role="source",
            filename=filename,
            sha256=info["sha256"],
            format=info["format"],
            width=oriented_width,
            height=oriented_height,
            exif_orientation=info.get("exif_orientation"),
            color_mode=info.get("mode"),
            channels=len(str(info.get("mode") or "")),
            has_alpha=bool(info.get("alpha_present")),
            size_bytes=info.get("size_bytes"),
            **lineage_fields,
        )
        expires_at = token_registry[source_token]["expires_at"]
        data = {
            "source_token": source_token,
            "display_name": filename,
            "format": info["format"],
            "width": oriented_width,
            "height": oriented_height,
            "size_bytes": info["size_bytes"],
            "has_alpha": bool(info.get("alpha_present")),
            "source_sha256": info["sha256"],
            "safe_preview_url": preview_url(issue_token(stored, role="source_preview", filename=filename)),
            "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
            **lineage_fields,
        }
        return data

    @app.post("/api/image-compression/intake")
    async def image_compression_intake(file: UploadFile = File(...)):
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        # Full decode + hashing of up to 50 MB must not stall other requests.
        data = await asyncio.to_thread(create_compression_intake, content, str(file.filename or ""))
        return {"code": 200, "status": "success", "success": True, "data": data}

    def create_reusable_result_intake(result_id: str) -> dict[str, Any]:
        user_dirs = require_compression_directory()
        try:
            reusable = resolve_reusable_result_source(
                shared_task_registry,
                str(result_id or ""),
                Path(user_dirs["app_data_root"]),
                max_bytes=MAX_UPLOAD_BYTES,
                allowed_suffixes=COMPRESSION_INTAKE_EXTENSIONS,
            )
            content = Path(reusable["source_result_path"]).read_bytes()
            if hashlib.sha256(content).hexdigest() != reusable["source_result_sha256"]:
                raise ResultReuseError(
                    "RESULT_REUSE_INTEGRITY_MISMATCH",
                    "原结果文件在读取时发生变化，已阻止继续处理。",
                )
            return create_compression_intake(content, reusable["source_result_file_name"], reusable)
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

    @app.post("/api/image-compression/intake-result")
    async def image_compression_intake_result(payload: dict = Body(default_factory=dict)):
        if set(payload) != {"result_id"}:
            raise HTTPException(
                status_code=400,
                detail={"code": "RESULT_REUSE_REQUEST_INVALID", "message": "继续处理请求字段不正确。"},
            )
        data = await asyncio.to_thread(create_reusable_result_intake, str(payload.get("result_id") or ""))
        return {"code": 200, "status": "success", "success": True, "data": data}

    @app.post("/api/image-processing/preflight")
    async def image_processing_preflight(request: Request):
        require_compression_directory()
        from engine.image_processing_routing import (
            PreflightContractError,
            build_image_profile,
            route_preflight,
            validate_preflight_request,
        )

        try:
            try:
                payload = await request.json()
            except Exception as exc:
                raise PreflightContractError("INVALID_REQUEST_BODY") from exc
            normalized = validate_preflight_request(payload)
            source = require_token(normalized["file_token"], role="source")
            profile = build_image_profile(
                Path(source["path"]),
                width=source.get("width"),
                height=source.get("height"),
            )
            return route_preflight(profile, normalized)
        except PreflightContractError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc

    def build_task_request(payload: Mapping[str, Any], source: dict[str, Any], task_id: str, output_dir: Path) -> dict[str, Any]:
        allowed_fields = {
            "source_token",
            "operation_mode",
            "params",
            "client_context",
            "run_id",
            "test_case_id",
            "diagnostic_session_id",
            "issue_report_id",
            "expected_status",
            "current_task_output_root",
            "long_image_risk_confirmation",
        }
        unknown_fields = sorted(str(key) for key in payload if key not in allowed_fields)
        if unknown_fields:
            raise HTTPException(status_code=400, detail=f"请求包含未知字段：{', '.join(unknown_fields)}。")
        mode = str(payload.get("operation_mode") or "").strip().upper()
        if payload.get("params") is not None and not isinstance(payload.get("params"), Mapping):
            raise HTTPException(status_code=400, detail="params 必须为对象。")
        params = dict(payload.get("params") or {})
        supported_modes = {item.value for item in OperationMode} | {DELIVERY_OPTIMIZATION_MODE}
        if mode not in supported_modes:
            raise HTTPException(status_code=400, detail="不支持的压缩能力模式。")

        allowed_params = {
            DELIVERY_OPTIMIZATION_MODE: {"target_format"},
            OperationMode.LOSSLESS_COMPRESSION.value: set(),
            OperationMode.RESIZE_REDUCTION.value: {"target_short_side", "scale_ratio", "target_width", "target_height"},
            OperationMode.UPLOAD_ADAPTATION.value: {"max_width", "max_height", "max_file_size_bytes"},
        }[mode]
        unknown_params = sorted(str(key) for key in params if key not in allowed_params)
        if unknown_params:
            raise HTTPException(status_code=400, detail=f"当前模式包含未知参数：{', '.join(unknown_params)}。")
        target_format = params.get("target_format")
        target_format = str(target_format or SMART_COMPRESSION_TARGET_FORMAT).strip().upper()
        if target_format not in SUPPORTED_TARGET_FORMATS:
            raise HTTPException(
                status_code=400,
                detail="目标格式仅支持 SMART_COMPRESSION、PRESERVE_FORMAT、JPEG、PNG 或 WEBP。",
            )

        def positive_int(name: str) -> int | None:
            value = params.get(name)
            if value in (None, ""):
                return None
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise HTTPException(status_code=400, detail=f"{name} 必须为正整数。")
            return value

        request: dict[str, Any] = {
            "contract_version": TASK_CONTRACT_VERSION,
            "task_id": task_id,
            "operation_mode": mode,
            "source_path": str(source["path"]),
            "source_sha256_expected": source.get("sha256"),
            "output_directory": str(output_dir),
            "preserve_format": bool(
                mode != DELIVERY_OPTIMIZATION_MODE
                or target_format == PRESERVE_FORMAT_TARGET_FORMAT
                or target_format == source.get("format")
            ),
            "quality_policy": (
                "FIXED_DELIVERY_OPTIONS_V1"
                if mode == DELIVERY_OPTIMIZATION_MODE
                else "LOSSLESS_ONLY"
                if mode == OperationMode.LOSSLESS_COMPRESSION.value
                else "SAME_FORMAT_HIGH_QUALITY"
                if mode == OperationMode.RESIZE_REDUCTION.value
                else "UPLOAD_ADAPTATION_V1"
            ),
            "metadata_policy": "PRESERVE_SUPPORTED_STRICT",
            "overwrite_policy": "FAIL_IF_EXISTS",
            "output_naming_policy": "TASK_ID_SUFFIX",
            "visual_review_policy": (
                "PER_SELECTED_CANDIDATE"
                if mode == DELIVERY_OPTIMIZATION_MODE
                else "STRICT_LOSSLESS_EVIDENCE"
                if mode == OperationMode.LOSSLESS_COMPRESSION.value
                else "VALIDATION_STRICT"
            ),
            "request_context": {"surface": "compression_ui", "api_version": IMAGE_COMPRESSION_API_VERSION},
            "client_context": payload.get("client_context") if isinstance(payload.get("client_context"), Mapping) else None,
            "run_id": payload.get("run_id") if isinstance(payload.get("run_id"), str) else None,
            "test_case_id": payload.get("test_case_id") if isinstance(payload.get("test_case_id"), str) else None,
            "diagnostic_session_id": payload.get("diagnostic_session_id") if isinstance(payload.get("diagnostic_session_id"), str) else None,
            "issue_report_id": payload.get("issue_report_id") if isinstance(payload.get("issue_report_id"), str) else None,
            "expected_status": payload.get("expected_status") if isinstance(payload.get("expected_status"), str) else None,
        }
        if mode == DELIVERY_OPTIMIZATION_MODE:
            request["target_format"] = target_format
            request["request_context"] = {
                **dict(request.get("request_context") or {}),
                "target_format_policy": (
                    "SMART_SAFE_FORMAT_SELECTION"
                    if target_format == SMART_COMPRESSION_TARGET_FORMAT
                    else
                    "PRESERVE_SOURCE_FORMAT"
                    if target_format == PRESERVE_FORMAT_TARGET_FORMAT
                    else "USER_SELECTED_TARGET_FORMAT"
                ),
            }
        if mode == OperationMode.RESIZE_REDUCTION.value:
            dimension_fields = [
                name
                for name in ("target_short_side", "scale_ratio", "target_width", "target_height")
                if params.get(name) not in (None, "")
            ]
            if len(dimension_fields) != 1:
                raise HTTPException(status_code=400, detail="尺寸缩小必须且只能提交一种尺寸参数。")
            selected_field = dimension_fields[0]
            source_width = int(source.get("width") or 0)
            source_height = int(source.get("height") or 0)
            if source_width <= 0 or source_height <= 0:
                raise HTTPException(status_code=400, detail="原图尺寸信息不可用。")
            request_context = dict(request.get("request_context") or {})
            if selected_field == "scale_ratio":
                ratio = params.get("scale_ratio")
                if isinstance(ratio, bool):
                    raise HTTPException(status_code=400, detail="缩放比例必须大于 0 且小于 1。")
                try:
                    parsed_ratio = float(ratio)
                except (TypeError, ValueError) as exc:
                    raise HTTPException(status_code=400, detail="缩放比例必须大于 0 且小于 1。") from exc
                if not 0 < parsed_ratio < 1:
                    raise HTTPException(status_code=400, detail="缩放比例必须大于 0 且小于 1。")
                request["scale_ratio"] = parsed_ratio
                request_context.update({"resize_strategy": "RATIO", "scale_ratio": parsed_ratio})
            elif selected_field == "target_short_side":
                short_side = positive_int("target_short_side")
                calculated = calculate_target_by_short_side(source_width, source_height, short_side)
                request["target_width"] = calculated["target_width"]
                request["target_height"] = calculated["target_height"]
                request_context.update(
                    {
                        "resize_strategy": "SHORT_SIDE",
                        "target_short_side": short_side,
                        "source_short_side": calculated["source_short_side"],
                        "calculated_scale": calculated["scale"],
                        "estimated_target_width": calculated["target_width"],
                        "estimated_target_height": calculated["target_height"],
                    }
                )
            else:
                width = positive_int("target_width")
                height = positive_int("target_height")
                if width is None:
                    if int(height) >= source_height:
                        raise HTTPException(status_code=400, detail="目标高度必须小于原图高度，尺寸缩小禁止放大。")
                    width = max(1, round(source_width * int(height) / source_height))
                    strategy = "HEIGHT"
                if height is None:
                    if int(width) >= source_width:
                        raise HTTPException(status_code=400, detail="目标宽度必须小于原图宽度，尺寸缩小禁止放大。")
                    height = max(1, round(source_height * int(width) / source_width))
                    strategy = "WIDTH"
                request["target_width"] = width
                request["target_height"] = height
                request_context.update(
                    {
                        "resize_strategy": strategy,
                        "target_width": int(params["target_width"]) if strategy == "WIDTH" else None,
                        "target_height": int(params["target_height"]) if strategy == "HEIGHT" else None,
                    }
                )
            request["request_context"] = request_context
            request["resize_policy"] = "LANCZOS_HIGH_QUALITY"
        elif mode == OperationMode.UPLOAD_ADAPTATION.value:
            request["max_width"] = positive_int("max_width")
            request["max_height"] = positive_int("max_height")
            request["max_file_size_bytes"] = positive_int("max_file_size_bytes")
            if all(request[name] is None for name in ("max_width", "max_height", "max_file_size_bytes")):
                raise HTTPException(status_code=400, detail="上传适配至少需要一个限制条件。")
        return request

    def product_preflight(payload: Mapping[str, Any], source: Mapping[str, Any]) -> None:
        mode = str(payload.get("operation_mode") or "").strip().upper()
        source_format = str(source.get("format") or "").upper()
        if source_format == "WEBP" and mode != DELIVERY_OPTIMIZATION_MODE:
            raise HTTPException(status_code=409, detail={"code": "MODE_NOT_APPLICABLE", "message": "WebP 当前仅支持交付方案中的保格式压缩或明确格式转换。"})
        if mode == OperationMode.LOSSLESS_COMPRESSION.value and source_format != "PNG":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "MODE_NOT_APPLICABLE",
                    "failure_code": "JPEG_COEFFICIENT_LOSSLESS_NOT_IMPLEMENTED",
                    "message": "当前图片为JPEG，暂不支持真正无损压缩。请选择“尺寸缩小”或“上传适配”。",
                },
            )
        if mode in {OperationMode.RESIZE_REDUCTION.value, OperationMode.UPLOAD_ADAPTATION.value} and source.get("exif_orientation") not in (None, 1):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "EXIF_ORIENTATION_REQUIRES_NORMALIZATION",
                    "message": "图片包含旋转方向信息，系统已按显示方向识别尺寸，但当前安全处理链路暂不执行方向归一化。请先将图片旋转后另存再处理。",
                },
            )
        width = int(source.get("width") or 0)
        height = int(source.get("height") or 0)
        params = payload.get("params")
        if mode == OperationMode.RESIZE_REDUCTION.value and isinstance(params, Mapping) and params.get("target_short_side") not in (None, ""):
            try:
                target_short_side = params["target_short_side"]
                if not _positive_dimension(target_short_side):
                    raise ValueError
                calculated = calculate_target_by_short_side(width, height, target_short_side)
            except (TypeError, ValueError):
                return
            source_short_side = calculated["source_short_side"]
            if target_short_side > source_short_side:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "TARGET_SHORT_SIDE_UPSCALE_BLOCKED",
                        "message": f"目标短边大于原图短边，图片不会被放大。请选择不超过 {source_short_side} 像素的目标短边。",
                        "source_short_side": source_short_side,
                    },
                )
            if target_short_side == source_short_side:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "NO_PROCESSING_NEEDED",
                        "message": "目标短边等于原图短边，无需处理，也不会为了生成文件而重新编码。",
                        "source_short_side": source_short_side,
                    },
                )
        if not is_long_image(width, height) or mode not in {OperationMode.RESIZE_REDUCTION.value, OperationMode.UPLOAD_ADAPTATION.value}:
            return
        if not isinstance(params, Mapping):
            return
        try:
            estimated = estimate_product_dimensions(width, height, mode, params)
        except (TypeError, ValueError, ZeroDivisionError):
            return
        risk = classify_long_image_width(estimated.get("width"))
        if risk["blocked"]:
            raise HTTPException(
                status_code=409,
                detail={"code": "LONG_IMAGE_WIDTH_TOO_LOW", "message": risk["message"], "estimated_output_width": estimated["width"], "estimated_output_height": estimated["height"]},
            )
        if risk["confirmation_required"] and payload.get("long_image_risk_confirmation") is not True:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "LONG_IMAGE_WIDTH_CONFIRMATION_REQUIRED",
                    "message": "长图文字可能明显难以阅读。继续前请确认：我已了解长图小字可能明显变弱。",
                    "estimated_output_width": estimated["width"],
                    "estimated_output_height": estimated["height"],
                },
            )

    @app.post("/api/image-compression/run")
    async def image_compression_run(payload: dict = Body(default_factory=dict)):
        return await execute_compression(payload)

    async def execute_compression(payload: dict, *, batch_job=None):
        user_dirs = require_compression_directory()
        token = str(payload.get("source_token") or "")
        source = await batch_job.checked_source() if batch_job is not None else require_token(token, role="source")
        source_lineage = result_lineage_fields(source)
        if batch_job is not None:
            source_lineage.update(item_identity(batch_job.batch["batch_id"], batch_job.item["id"], "image_compression", batch_job.item.get("source_id", "")))
        product_preflight(payload, source)
        task_id = batch_job.item["task_id"] if batch_job is not None else f"compression_{uuid.uuid4().hex[:16]}"
        operation_identity = new_operation_identity("image_compression", module_id="hdde.image.compression")
        task_created_at = batch_job.batch["created_at"] if batch_job is not None else now_provider()
        preflight_output = Path(user_dirs["tmp_dir"]).resolve() / "image-compression-preflight"
        request = build_task_request(payload, source, task_id, preflight_output)
        output_root = effective_output_root(payload)
        effective_root = Path(output_root["normalized_path"])
        output_dir = function_output_dir(str(request["operation_mode"]), effective_root)
        request["output_directory"] = str(output_dir)
        source_preview = preview_token_for(Path(source["path"]), role="source_preview")
        record = {
            "task_id": task_id,
            **operation_identity,
            "task_family": "image_compression",
            "operation_mode": str(request["operation_mode"]),
            "created_at": datetime.fromtimestamp(task_created_at, tz=timezone.utc).isoformat(),
            "completed_at": None,
            "status": None,
            "progress": 0,
            "failure_reason": None,
            "lifecycle": [],
            "request": request,
            "result": None,
            "result_id": "",
            "result_file": "",
            "task_result": None,
            "source": str(Path(source["path"]).resolve()),
            "source_path": Path(source["path"]),
            "output_path": None,
            "output_dir": output_dir,
            "effective_output_root": effective_root,
            "output_root_source": output_root["source"],
            "source_preview_token": source_preview,
            "output_preview_token": None,
            "review_note": "",
            "reviewed_at": None,
            "review_output_sha256_before": None,
            "review_output_sha256_after": None,
            "source_metadata": dict(source),
            **source_lineage,
            "original_filename": str(source.get("filename") or ""),
            "long_image_validation": None,
            "resize_validation": None,
            "feedback_package": None,
            "feedback_package_token": None,
            "feedback_artifact_stem": None,
            "task_context": {
                "task_id": task_id,
                **operation_identity,
                "purpose": "IMAGE_COMPRESSION",
                "route": "/compression",
                "route_family": "image_compression",
                **source_lineage,
            },
            "error_context": {},
        }
        task_registry[task_id] = record
        if shared_task_registry is not None:
            shared_task_registry[task_id] = record
        transition_task(record, "pending", 0)
        emit_runtime_event(
            "TASK_CREATED",
            stage="task_registration",
            result="success",
            task_id=task_id,
            status="pending",
            impact="unified_task_available",
            **operation_identity,
        )
        try:
            if not claim_task_execution(record):
                task_registry.pop(task_id, None)
                raise HTTPException(
                    status_code=409,
                    detail={"code": "TASK_REMOVED_BEFORE_EXECUTION", "message": "Task was removed before execution started."},
                )
            transition_task(record, "processing", 10)
            emit_runtime_event(
                "PROCESS_STARTED",
                stage="engine_adapter",
                result="started",
                task_id=task_id,
                status="processing",
                impact="image_compression_running",
                **operation_identity,
            )
            processing_started = time.perf_counter()
            if str(request["operation_mode"]) == DELIVERY_OPTIMIZATION_MODE:
                async def generate_into(directory):
                    return await asyncio.to_thread(
                        generate_delivery_candidates,
                        Path(source["path"]),
                        directory,
                        source_filename=str(source.get("filename") or Path(source["path"]).name),
                        moment=datetime.fromtimestamp(task_created_at),
                        target_format=str(request["target_format"]),
                    )

                generated = (await batch_job.generate(generate_into, output_dir)
                             if batch_job is not None else await generate_into(output_dir))
                candidates = list(generated["candidates"])
                for candidate in candidates:
                    candidate_path = Path(str(candidate.get("output_path") or ""))
                    candidate["preview_token"] = (
                        preview_token_for(candidate_path, role="output_preview")
                        if candidate.get("status") == "AVAILABLE" and candidate_path.is_file()
                        else None
                    )
                    is_lossless_candidate = str(candidate.get("scheme_id")) in {
                        PNG_LOSSLESS_SCHEME,
                        WEBP_LOSSLESS_SCHEME,
                    }
                    lossless_hard_evidence = bool(
                        is_lossless_candidate
                        and candidate.get("lossless_verified") is True
                        and candidate.get("pixel_identical") is True
                        and candidate.get("pixel_diff_count") == 0
                        and candidate.get("max_channel_diff") == 0
                        and candidate.get("verification_status") == "PASS"
                    )
                    jpg_quality_evidence = bool(
                        not is_lossless_candidate
                        and dict(candidate.get("quality_gate") or {}).get("status") == "PASS"
                    )
                    candidate["visual_review_status"] = (
                        VisualReviewStatus.NOT_REQUIRED.value
                        if (lossless_hard_evidence or jpg_quality_evidence) and candidate.get("status") == "AVAILABLE"
                        else VisualReviewStatus.NOT_AVAILABLE.value
                    )
                    candidate["delivery_eligible"] = bool(
                        (lossless_hard_evidence or jpg_quality_evidence) and candidate.get("status") == "AVAILABLE"
                    )
                    candidate["review_note"] = ""
                source_info = generated["source"]
                result = ImageCompressionResult(
                    task_id=task_id,
                    operation_mode=DELIVERY_OPTIMIZATION_MODE,
                    run_id=request.get("run_id"),
                    test_case_id=request.get("test_case_id"),
                    diagnostic_session_id=request.get("diagnostic_session_id"),
                    issue_report_id=request.get("issue_report_id"),
                    source_path=str(source_info["path"]),
                    source_sha256=str(source_info["sha256"]),
                    source_format=str(source_info["format"]),
                    source_dimensions=dict(generated["source_display_dimensions"]),
                    source_size_bytes=int(source_info["size_bytes"]),
                    processing_seconds=max(0.0, time.perf_counter() - processing_started),
                    stage_seconds={"fixed_candidate_generation": max(0.0, time.perf_counter() - processing_started)},
                    slowest_stage="fixed_candidate_generation",
                    validation_status="PASS",
                )
                winner = dict(generated["winner"])
                winner_is_source = str(generated["winner_scheme_id"]) == KEEP_ORIGINAL_SCHEME
                result_id = None if winner_is_source else (
                    batch_job.item["reserved_result_id"] if batch_job is not None
                    else f"compression_result_{uuid.uuid4().hex[:16]}"
                )
                for candidate in candidates:
                    registered_output_sha256 = str(candidate.get("output_sha256") or "")
                    candidate["artifact_identity"] = {
                        **dict(candidate.get("artifact_identity") or {}),
                        "result_id": result_id,
                        "candidate_id": str(candidate.get("candidate_id") or candidate.get("scheme_id") or ""),
                        "source_sha256": str(source_info["sha256"]),
                        "output_sha256": registered_output_sha256 or None,
                    }
                winner_public = {
                    "scheme_id": str(winner.get("scheme_id") or ""),
                    "candidate_id": str(winner.get("candidate_id") or winner.get("scheme_id") or ""),
                    "display_name": str(winner.get("display_name") or ""),
                    "format": str(winner.get("format") or ""),
                    "file_size": winner.get("file_size"),
                    "width": winner.get("width"),
                    "height": winner.get("height"),
                    "applicable_scene": str(winner.get("applicable_scene") or ""),
                    "recommended": True,
                    "reason": str(generated.get("recommendation_reason") or winner.get("reason") or ""),
                    "status": "AVAILABLE",
                    "selected": True,
                    "quality_gate": dict(winner.get("quality_gate") or {}),
                    "saved_bytes": winner.get("saved_bytes", 0),
                    "saved_percent": winner.get("saved_percent", 0.0),
                    "source_selected": winner_is_source,
                }
                record.update({
                    "result": result,
                    "result_id": result_id,
                    "candidate_options": candidates,
                    "winner_public": winner_public,
                    "winner_scheme_id": str(generated["winner_scheme_id"]),
                    "selection_policy": str(generated["selection_policy"]),
                    "public_output_count": int(generated["public_output_count"]),
                    "recommended_scheme_id": str(generated["recommended_scheme_id"]),
                    "recommendation_reason": str(generated["recommendation_reason"]),
                    "source_has_real_transparency": bool(generated["source_has_real_transparency"]),
                    "target_format": str(generated["target_format"]),
                    "effective_target_format": str(generated["effective_target_format"]),
                    "format_conversion": bool(generated["format_conversion"]),
                    "format_policy": str(generated["format_policy"]),
                    "alpha_handling": dict(generated["alpha_handling"]),
                    "smart_compression_summary": str(generated.get("smart_compression_summary") or ""),
                    "smart_compression_details": dict(generated.get("smart_compression_details") or {}),
                })
                if winner_is_source:
                    select_source_winner(record, winner)
                    output_path = None
                else:
                    selected_candidate = next(
                        candidate
                        for candidate in candidates
                        if candidate["scheme_id"] == generated["winner_scheme_id"]
                    )
                    select_delivery_candidate(record, selected_candidate)
                    output_path = Path(str(selected_candidate["output_path"])).resolve()
            else:
                result = await asyncio.to_thread(process_image_compression, request)
                output_dir, output_path = finalize_readable_output(
                    result,
                    source=source,
                    request=request,
                    task_id=task_id,
                    root=effective_root,
                    function_dir=output_dir,
                    now_value=task_created_at,
                )
            if result.output_created:
                if output_path is None or not output_path.is_file() or output_path.stat().st_size <= 0:
                    raise RuntimeError("压缩输出验证失败：输出文件不存在或为空。")
                output_metadata = dict((result.metadata_details or {}).get("hdde_output_metadata") or {})
                if not output_metadata.get("written"):
                    raise RuntimeError("压缩输出缺少发布前统一元数据验证。")
                # Metadata is written during publication, so one full decode of the
                # published file verifies the final bytes; keep it off the event loop.
                verified = await asyncio.to_thread(read_image_info, output_path, allow_webp=True)
                expected_dimensions = result.output_dimensions or {}
                if verified["format"] != result.output_format or verified["dimensions"] != expected_dimensions:
                    raise RuntimeError("压缩输出验证失败：输出格式或尺寸与任务结果不一致。")
                result.output_sha256 = verified["sha256"]
                result.output_size_bytes = verified["size_bytes"]
                if result.source_size_bytes is not None:
                    result.size_reduction_bytes = result.source_size_bytes - result.output_size_bytes
                    result.size_reduction_ratio = result.size_reduction_bytes / result.source_size_bytes

            record.update({
                "result": result,
                "output_path": output_path,
                "output_dir": output_dir,
                "output_preview_token": preview_token_for(output_path, role="output_preview") if output_path and output_path.exists() else None,
                "review_output_sha256_before": result.output_sha256,
                "long_image_validation": build_long_image_validation(source, request),
                "resize_validation": build_resize_validation(source, request, result),
                "feedback_artifact_stem": output_path.stem if result.output_created and output_path else Path(
                    readable_output_name(
                        str(source.get("filename") or "image.png"),
                        Path(str(source.get("filename") or "image.png")).suffix or ".png",
                        request,
                        task_id,
                        task_created_at,
                    )
                ).stem + f"_{task_id[-8:]}",
            })
            if result.output_created and output_path:
                result_id = str(record.get("result_id") or f"compression_result_{uuid.uuid4().hex[:16]}")
                task_result = {
                    "result_id": result_id,
                    "task_id": task_id,
                    "feature_key": "image_compression",
                    "module_id": operation_identity["module_id"],
                    "operation_id": operation_identity["operation_id"],
                    "trace_id": operation_identity["trace_id"],
                    "source": str(record["source_path"]),
                    "source_path": str(record["source_path"]),
                    "result_file": str(output_path),
                    "output_path": str(output_path),
                    "source_sha256": result.source_sha256,
                    "output_sha256": result.output_sha256,
                    "delivery_eligible": bool(result.delivery_eligible),
                    "status": "completed",
                    **source_lineage,
                }
                if record.get("candidate_options"):
                    task_result.update({
                        "recommended_scheme_id": record.get("recommended_scheme_id"),
                        "selected_scheme_id": record.get("selected_scheme_id"),
                    })
                record.update({
                    "result_id": result_id,
                    "result_file": str(output_path),
                    "output_sha256": result.output_sha256,
                    "task_result": task_result,
                })
            if str(result.technical_status) in {
                TechnicalStatus.INVALID_REQUEST.value,
                TechnicalStatus.CANNOT_MEET_SAFELY.value,
                TechnicalStatus.PROCESSING_FAILED.value,
            }:
                transition_task(record, "failed", record["progress"], failure_reason=result.failure_reason or result.failure_code or "图片压缩失败。")
                emit_runtime_event(
                    "PROCESS_FAILED",
                    level=logging.ERROR,
                    stage="engine_adapter",
                    result="failed",
                    task_id=task_id,
                    status="failed",
                    reason=record.get("failure_reason") or "processing_failed",
                    impact="formal_result_unavailable",
                    **operation_identity,
                )
            else:
                transition_task(record, "completed", 100)
                emit_runtime_event(
                    "PROCESS_SUCCEEDED",
                    stage="output_verification",
                    result="success",
                    task_id=task_id,
                    result_id=record.get("result_id") or "",
                    status="completed",
                    impact="verified_output_available" if record.get("result_id") else "no_output_required",
                    **operation_identity,
                )
                if record.get("result_id"):
                    emit_runtime_event(
                        "RESULT_REGISTERED",
                        stage="result_registry",
                        result="success",
                        task_id=task_id,
                        result_id=record["result_id"],
                        status="completed",
                        impact="formal_result_available",
                        **operation_identity,
                    )
        except Exception as exc:
            if record.get("status") == "processing":
                transition_task(record, "failed", record["progress"], failure_reason=str(exc) or exc.__class__.__name__)
            diagnostics = build_exception_diagnostics(
                exc,
                error_category="ENVIRONMENT_ERROR" if isinstance(exc, OSError) else "PRODUCT_ERROR",
                error_stage="engine_adapter",
                trace_id=operation_identity["trace_id"],
            )
            failure_code = str(getattr(exc, "failure_code", "") or "")
            if failure_code:
                diagnostics["error_code"] = failure_code
                record["failure_code"] = failure_code
            record["error_context"] = dict(diagnostics)
            if shared_task_registry is not None:
                shared_task_registry[task_id] = record
            emit_runtime_event(
                "PROCESS_FAILED",
                level=logging.ERROR,
                stage="engine_adapter",
                result="failed",
                task_id=task_id,
                status="failed",
                impact="formal_result_unavailable",
                **{**operation_identity, **diagnostics},
            )
            if failure_code in {
                "JPG_NO_VALID_CANDIDATE",
                "PNG_NO_VALID_CANDIDATE",
                "WEBP_NO_VALID_CANDIDATE",
                "PNG_LOSSLESS_VERIFICATION_FAILED",
                "WEBP_LOSSLESS_VERIFICATION_FAILED",
                "SOURCE_COLOR_MODE_UNSUPPORTED",
            }:
                raise HTTPException(status_code=409, detail={"code": failure_code, "message": str(exc), "task_id": task_id}) from exc
            raise
        return {"code": 200, "status": "success", "success": True, "data": public_result(record)}

    @app.post("/api/image-compression/test-feedback-package")
    async def image_compression_test_feedback_package(payload: dict = Body(default_factory=dict)):
        require_compression_directory()
        if set(payload) != {"task_id"}:
            raise HTTPException(status_code=400, detail={"code": "FEEDBACK_PACKAGE_REQUEST_INVALID", "message": "测试反馈包只接受已登记的 task_id。"})
        task_id = str(payload.get("task_id") or "")
        record = task_registry.get(task_id)
        if not record:
            raise HTTPException(status_code=404, detail={"code": "FEEDBACK_PACKAGE_TASK_NOT_FOUND", "message": "压缩任务不存在。"})
        output_path = Path(record["output_path"]).resolve() if record.get("output_path") else None
        package_root = Path(record["output_dir"]).resolve()
        effective_root = Path(record["effective_output_root"]).resolve()
        raw_result = record["result"].to_dict()
        if effective_root not in package_root.parents:
            raise HTTPException(status_code=500, detail={"code": "FEEDBACK_PACKAGE_PATH_INVALID", "message": "反馈包目录安全校验失败。"})
        candidate_available = bool(
            record["result"].output_created
            and raw_result.get("candidate_delivery_role") != "NONE"
            and output_path is not None
            and output_path.is_file()
            and output_path.parent == package_root
        )
        if output_path is not None and record["result"].output_created and not candidate_available:
            raise HTTPException(status_code=409, detail={"code": "FEEDBACK_PACKAGE_PATH_INVALID", "message": "候选输出与反馈包目录不一致。"})
        output_stem = output_path.stem if candidate_available else str(record.get("feedback_artifact_stem") or "")
        if not output_stem:
            raise HTTPException(status_code=500, detail={"code": "FEEDBACK_PACKAGE_PATH_INVALID", "message": "无法生成安全的反馈包文件名。"})
        package_id = f"{output_stem}_测试反馈包"
        package_path = package_root / f"{package_id}.zip"
        existing_package = record.get("feedback_package")
        if existing_package and package_path.is_file():
            prune_tokens()
            existing_token = str(record.get("feedback_package_token") or "")
            token_item = token_registry.get(existing_token)
            package_sha256 = validate_registered_feedback_package_file(
                record,
                existing_package,
                package_path,
                token_item=token_item if token_item and token_item.get("role") == "feedback_package" else None,
            )
            if (
                token_item
                and token_item.get("role") == "feedback_package"
                and token_item.get("task_id") == task_id
                and Path(token_item.get("path", "")).resolve() == package_path.resolve()
                and token_item.get("expires_at", 0) > now_provider()
            ):
                return {"code": 200, "status": "success", "success": True, "data": existing_package}
            renewed = register_feedback_package(
                record,
                package_path,
                package_id=package_id,
                output_stem=output_stem,
                package_sha256=package_sha256,
                created_at=str(existing_package.get("created_at") or "") or None,
            )
            return {"code": 200, "status": "success", "success": True, "data": renewed}
        if package_path.exists():
            raise HTTPException(status_code=409, detail={"code": "FEEDBACK_PACKAGE_EXISTS", "message": "同名测试反馈包已存在，未覆盖既有文件。"})
        result_data = record["result"].to_dict()
        redacted_result = {
            **result_data,
            "source_path": Path(result_data["source_path"]).name if result_data.get("source_path") else None,
            "output_path": Path(result_data["output_path"]).name if result_data.get("output_path") else None,
            "evidence_paths": {},
            "asset_manifest_path": None,
            "asset_comparison_path": None,
            "execution_log_path": None,
        }
        generated_at = datetime.fromtimestamp(now_provider(), tz=timezone.utc).isoformat()
        task_data = build_feedback_task(record, result_data)
        review_data = build_feedback_review(record, result_data)
        environment_data = build_feedback_environment(generated_at)
        warnings_data = {
            "warnings": list(result_data.get("warnings") or []),
            "risk_reasons": list(result_data.get("risk_reasons") or []),
            "failure_code": result_data.get("failure_code"),
            "failure_reason": result_data.get("failure_reason"),
        }
        validation = build_feedback_validation(record, result_data, review_data, package_path)
        evidence_readme = "\n".join(
            [
                "# 证据目录说明",
                "",
                "1. 默认不包含用户原图。",
                "2. 默认不包含输出图片。",
                "3. 默认只记录文件名、格式、尺寸、体积和SHA256。",
                "4. 未执行任何在线上传。",
                "5. 未包含账号、密钥、token和私人绝对路径。",
                "6. evidence目录为空是正常隐私默认，不代表反馈包缺失。",
                "",
            ]
        )
        files = {
            "summary.md": build_feedback_summary(package_id, result_data, validation),
            "task.json": json.dumps(task_data, ensure_ascii=False, indent=2) + "\n",
            "result.json": json.dumps(redacted_result, ensure_ascii=False, indent=2) + "\n",
            "review.json": json.dumps(review_data, ensure_ascii=False, indent=2) + "\n",
            "environment.json": json.dumps(environment_data, ensure_ascii=False, indent=2) + "\n",
            "validation.json": json.dumps(validation, ensure_ascii=False, indent=2) + "\n",
            "warnings.json": json.dumps(warnings_data, ensure_ascii=False, indent=2) + "\n",
            "evidence/README.md": evidence_readme,
        }
        if bool((record.get("long_image_validation") or {}).get("is_long_image")):
            files["long_image_validation.json"] = json.dumps(
                build_feedback_long_validation(record, result_data),
                ensure_ascii=False,
                indent=2,
            ) + "\n"
        file_manifest = [
            {
                "path": name,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "size_bytes": len(content.encode("utf-8")),
            }
            for name, content in sorted(files.items())
        ]
        files["manifest.json"] = json.dumps(
            {
                "package_id": package_id,
                "contract_version": "hdde.image-compression-feedback.v1",
                "output_stem": output_stem,
                "files": file_manifest,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        files["manifest.sha256"] = "".join(
            f"{item['sha256']}  {item['path']}\n"
            for item in file_manifest
        )
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in sorted(files.items()):
                archive.writestr(name, content.encode("utf-8"))
        archive_bytes = archive_buffer.getvalue()
        try:
            with package_path.open("xb") as handle:
                handle.write(archive_bytes)
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail={"code": "FEEDBACK_PACKAGE_EXISTS", "message": "同名测试反馈包已存在，未覆盖既有文件。"}) from exc
        package_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        feedback_package = register_feedback_package(
            record,
            package_path,
            package_id=package_id,
            output_stem=output_stem,
            package_sha256=package_sha256,
        )
        return {"code": 200, "status": "success", "success": True, "data": feedback_package}

    @app.post("/api/image-compression/select-candidate")
    async def image_compression_select_candidate(payload: dict = Body(default_factory=dict)):
        require_compression_directory()
        if set(payload) != {"task_id", "scheme_id"}:
            raise HTTPException(status_code=400, detail={"code": "CANDIDATE_SELECTION_INVALID", "message": "方案选择只接受 task_id 与 scheme_id。"})
        task_id = str(payload.get("task_id") or "")
        scheme_id = str(payload.get("scheme_id") or "")
        record = task_registry.get(task_id)
        if not record:
            raise HTTPException(status_code=404, detail={"code": "CANDIDATE_TASK_NOT_FOUND", "message": "交付优化任务不存在。"})
        if str(record.get("operation_mode") or "") != DELIVERY_OPTIMIZATION_MODE:
            raise HTTPException(status_code=409, detail={"code": "CANDIDATE_SELECTION_NOT_SUPPORTED", "message": "当前任务不是多方案交付任务。"})
        candidate = next(
            (item for item in list(record.get("candidate_options") or []) if str(item.get("scheme_id") or "") == scheme_id),
            None,
        )
        if candidate is None:
            raise HTTPException(status_code=404, detail={"code": "CANDIDATE_NOT_FOUND", "message": "交付方案不存在。"})
        select_delivery_candidate(record, candidate)
        emit_runtime_event(
            "RESULT_CANDIDATE_SELECTED",
            stage="result_selection",
            result="success",
            task_id=task_id,
            result_id=record.get("result_id") or "",
            status="completed",
            impact="legacy_result_binding_updated",
            scheme_id=scheme_id,
            **operation_event_fields(record),
        )
        return {"code": 200, "status": "success", "success": True, "data": public_result(record)}

    @app.post("/api/image-compression/review")
    async def image_compression_review(payload: dict = Body(default_factory=dict)):
        require_compression_directory()
        unknown_fields = sorted(str(key) for key in payload if key not in {"task_id", "decision", "note"})
        if unknown_fields:
            raise HTTPException(status_code=400, detail=f"人工复核请求包含未知字段：{', '.join(unknown_fields)}。")
        task_id = str(payload.get("task_id") or "")
        record = task_registry.get(task_id)
        if not record:
            raise HTTPException(status_code=404, detail="压缩任务不存在。")
        result = record["result"]
        technical = str(result.technical_status)
        if technical not in {TechnicalStatus.TARGET_MET.value, TechnicalStatus.TARGET_MET_WITH_REENCODE.value}:
            raise HTTPException(status_code=409, detail="当前任务没有可供人工复核的技术候选。")
        if str(result.visual_review_status) != VisualReviewStatus.PENDING.value:
            raise HTTPException(status_code=409, detail="当前任务不处于待人工复核状态。")
        decision = str(payload.get("decision") or "").strip().upper()
        if decision not in {VisualReviewStatus.PASS.value, VisualReviewStatus.PASS_WITH_NOTES.value, VisualReviewStatus.FAIL.value}:
            raise HTTPException(status_code=400, detail="人工复核结论必须为 PASS、PASS_WITH_NOTES 或 FAIL。")
        note = str(payload.get("note") or "").strip()
        if decision == VisualReviewStatus.PASS_WITH_NOTES.value and not note:
            raise HTTPException(status_code=400, detail="PASS_WITH_NOTES 必须填写复核说明。")
        if len(note) > 500:
            raise HTTPException(status_code=400, detail="复核说明不得超过 500 个字符。")
        result.visual_review_status = VisualReviewStatus(decision)
        record["review_note"] = note if decision == VisualReviewStatus.PASS_WITH_NOTES.value else ""
        record["reviewed_at"] = datetime.fromtimestamp(now_provider(), tz=timezone.utc).isoformat()
        record["review_output_sha256_before"] = record.get("review_output_sha256_before") or result.output_sha256
        apply_delivery_gate(result, evidence_candidate=bool(result.output_created))
        record["review_output_sha256_after"] = result.output_sha256
        if str(record.get("operation_mode") or "") == DELIVERY_OPTIMIZATION_MODE:
            selected_scheme_id = str(record.get("selected_scheme_id") or "")
            selected_candidate = next(
                (
                    item
                    for item in list(record.get("candidate_options") or [])
                    if str(item.get("scheme_id") or "") == selected_scheme_id
                ),
                None,
            )
            if selected_candidate is not None:
                selected_candidate["visual_review_status"] = decision
                selected_candidate["delivery_eligible"] = bool(result.delivery_eligible)
                selected_candidate["review_note"] = record["review_note"]
            if shared_task_registry is not None:
                shared_task_registry[task_id] = record
        emit_runtime_event(
            "QUALITY_REVIEW_UPDATED",
            stage="human_quality_review",
            result="success",
            feature="quality_confirm",
            operation=record.get("operation_mode") or "",
            task_id=task_id,
            status=decision,
            impact="delivery_gate_updated",
            action="continue_delivery_or_reprocess",
        )
        return {"code": 200, "status": "success", "success": True, "data": public_result(record)}

    @app.post("/api/image-compression/open-output-folder")
    async def image_compression_open_output_folder(payload: dict = Body(default_factory=dict)):
        require_compression_directory()
        if set(payload) != {"task_id"}:
            raise HTTPException(status_code=400, detail="只能通过已登记的 task_id 打开输出目录。")
        task_id = str(payload.get("task_id") or "")
        record = task_registry.get(task_id)
        if not record:
            raise HTTPException(status_code=404, detail="压缩任务不存在。")
        result = record["result"]
        if not result.output_created or not record.get("output_path") or not Path(record["output_path"]).is_file():
            raise HTTPException(status_code=409, detail="当前任务没有可打开的输出文件。")
        target = Path(record["output_dir"]).resolve()
        root = Path(record["effective_output_root"]).resolve()
        if root not in target.parents or not target.exists() or not target.is_dir():
            raise HTTPException(status_code=403, detail="输出目录不在受控范围内。")
        if folder_opener is None and os.name != "nt":
            return {"code": 400, "status": "error", "success": False, "message": "当前系统不支持自动打开本地目录。"}
        try:
            if folder_opener is not None:
                folder_opener(str(target))
            else:
                os.startfile(str(target))  # noqa: S606 - validated local directory only
        except Exception as exc:
            raise HTTPException(status_code=400, detail="打开输出目录失败。") from exc
        return {"code": 200, "status": "success", "success": True, "data": {"directory_label": target.name}}

    @app.post("/api/image-compression/open-function-folder")
    async def image_compression_open_function_folder(payload: dict = Body(default_factory=dict)):
        require_compression_directory()
        allowed_fields = {"operation_mode", "current_task_output_root"}
        if not set(payload).issubset(allowed_fields) or "operation_mode" not in payload:
            raise HTTPException(status_code=400, detail="打开功能目录请求字段不正确。")
        mode = str(payload.get("operation_mode") or "").strip().upper()
        if mode not in FUNCTION_DIRECTORY_BY_MODE:
            raise HTTPException(status_code=400, detail="不支持的压缩能力模式。")
        output_root = effective_output_root(payload)
        root = Path(output_root["normalized_path"]).resolve()
        target = function_output_dir(mode, root)
        if folder_opener is None and os.name != "nt":
            return {"code": 400, "status": "error", "success": False, "message": "当前系统不支持自动打开本地目录。"}
        try:
            if folder_opener is not None:
                folder_opener(str(target))
            else:
                os.startfile(str(target))  # noqa: S606 - validated local directory only
        except Exception as exc:
            raise HTTPException(status_code=400, detail="打开输出目录失败。") from exc
        return {"code": 200, "status": "success", "success": True, "data": {"directory_label": target.name}}

    @app.get("/api/color-correction/capabilities")
    async def color_correction_capabilities():
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "data": {
                "api_version": "hdde.color-correction-api.v1",
                "engine_version": FORMAL_COLOR_RUNTIME_VERSION,
                "server_session_id": server_session_id,
                "operation_mode": "AUTO_COLOR_CORRECTION",
                "supported_formats": ["PNG", "JPEG"],
                "max_upload_bytes": MAX_UPLOAD_BYTES,
                "content_generation": False,
                "manual_adjustments": False,
                "reference_available": True,
                "reference_endpoint": "/api/color-correction/reference-run",
                "level_pick_available": True,
                "level_pick_version": LEVEL_PICK_VERSION,
                "level_pick_preview_endpoint": "/api/color-correction/level-preview",
                "level_pick_run_endpoint": "/api/color-correction/level-run",
                "level_pick_levels": ["original", *LEVELS],
                "reference_level_pick_available": True,
                "reference_level_pick_version": REFERENCE_LEVEL_PICK_VERSION,
                "batch_available": True,
                "max_batch_size": 20,
                "queue_mode": "local_sequential",
            },
        }

    @app.post("/api/color-correction/intake-result")
    async def color_correction_intake_result(payload: dict = Body(default_factory=dict)):
        if set(payload) != {"result_id"}:
            raise HTTPException(
                status_code=400,
                detail={"code": "RESULT_REUSE_REQUEST_INVALID", "message": "继续处理请求字段不正确。"},
            )
        data = create_reusable_result_intake(str(payload.get("result_id") or ""))
        return {"code": 200, "status": "success", "success": True, "data": data}

    @app.get("/api/color-correction/output-settings")
    async def color_correction_output_settings():
        require_compression_directory()
        settings = color_output_settings()
        checked = validate_color_output_root(settings["saved_default_root"], source="saved_default")
        root = Path(checked["normalized_path"]).resolve()
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "data": {
                **settings,
                "effective_output_root": str(root),
                "output_root_writable": bool(checked.get("writable")),
                "function_output_directory": str(color_output_dir(root)),
                "folder_selection_endpoint": "/api/output/select-popup",
            },
        }

    @app.post("/api/color-correction/run")
    async def color_correction_run(payload: dict = Body(default_factory=dict)):
        require_compression_directory()
        allowed_fields = {"source_token", "current_task_output_root", "client_context"}
        unknown = sorted(str(key) for key in payload if key not in allowed_fields)
        if unknown:
            raise HTTPException(status_code=400, detail={"code": "COLOR_CORRECTION_REQUEST_INVALID", "message": f"颜色校正请求包含未知字段：{', '.join(unknown)}。"})
        source = require_token(str(payload.get("source_token") or ""), role="source")
        output_root = effective_color_output_root(payload)
        record = create_color_task_record(source, output_root)
        await asyncio.to_thread(execute_color_task, record)
        if record.get("status") == "failed":
            from fastapi.responses import JSONResponse
            blocked = record.get("d3_status") == "PROTECTION_BLOCKED"
            return JSONResponse(status_code=422 if blocked or record.get("output_selected") == "ORIGINAL" else 500, content={
                "code": "PROTECTION_BLOCKED" if blocked else "COLOR_OUTPUT_UNAVAILABLE", "status": "failed", "success": False,
                "message": record["failure_reason"], "data": public_color_result(record),
            })
        return {"code": 200, "status": "success", "success": True, "data": public_color_result(record)}

    @app.post("/api/color-correction/reference-run")
    async def color_correction_reference_run(payload: dict = Body(default_factory=dict)):
        from engine.color_correction.color_management import ColorManagementError, load_color_managed_source

        require_compression_directory()
        allowed = {"target_source_token", "reference_source_token", "current_task_output_root", "client_context"}
        if set(payload) - allowed:
            raise HTTPException(status_code=400, detail={"code": "REFERENCE_REQUEST_INVALID", "message": "参考图校色请求字段不正确。"})
        # Check both expiries before the shared token resolver prunes entries.
        for role, label in (("TARGET", "目标图片"), ("REFERENCE", "参考图片")):
            token = payload.get(f"{role.lower()}_source_token")
            item = token_registry.get(token) if isinstance(token, str) else None
            if not item or item.get("role") != "source":
                raise HTTPException(status_code=404, detail={"code": f"{role}_TOKEN_INVALID", "message": f"{label}会话无效，请重新选择。"})
            if item["expires_at"] <= now_provider():
                raise HTTPException(status_code=410, detail={"code": f"{role}_TOKEN_EXPIRED", "message": f"{label}会话已过期，请重新选择。"})
        inputs = {}
        for role, label in (("TARGET", "目标图片"), ("REFERENCE", "参考图片")):
            try:
                source = require_token(payload[f"{role.lower()}_source_token"], role="source")
            except HTTPException as exc:
                raise HTTPException(status_code=404, detail={"code": f"{role}_TOKEN_INVALID", "message": f"{label}不可用，请重新选择。"}) from exc
            if _sha256_file(Path(source["path"])) != source.get("sha256"):
                raise HTTPException(status_code=409, detail={"code": f"{role}_SOURCE_IDENTITY_CHANGED", "message": f"{label}内容发生变化，请重新选择。"})
            try:
                await asyncio.to_thread(load_color_managed_source, Path(source["path"]))
            except ColorManagementError as exc:
                raise HTTPException(status_code=415, detail={"code": f"UNSUPPORTED_{role}_FORMAT", "message": f"{label}的格式或色彩信息不受支持，请选择合法 PNG 或 JPEG 图片。"}) from exc
            inputs[role] = source
        output_root = effective_color_output_root(payload)
        record = create_color_task_record(inputs["TARGET"], output_root, reference=inputs["REFERENCE"])
        await asyncio.to_thread(execute_color_task, record)
        if record.get("status") == "failed":
            from fastapi.responses import JSONResponse
            blocked = record.get("d3_status") == "PROTECTION_BLOCKED"
            no_output = record.get("output_selected") == "ORIGINAL"
            return JSONResponse(status_code=422 if blocked or no_output else 500, content={
                "code": "PROTECTION_BLOCKED" if blocked else "COLOR_OUTPUT_UNAVAILABLE" if no_output else "RUNTIME_FAILURE",
                "status": "failed", "success": False,
                "message": "本次未采用参考调整，已保留原图。" if blocked else record["failure_reason"],
                "data": public_color_result(record),
            })
        return {"code": 200, "status": "success", "success": True, "data": public_color_result(record)}

    @app.post("/api/color-correction/level-preview")
    async def color_correction_level_preview(payload: dict = Body(default_factory=dict)):
        require_compression_directory()
        allowed_fields = {"source_token", "reference_source_token", "client_context"}
        unknown = sorted(str(key) for key in payload if key not in allowed_fields)
        if unknown:
            raise HTTPException(status_code=400, detail={"code": "LEVEL_PREVIEW_REQUEST_INVALID", "message": f"挑档校色请求包含未知字段：{', '.join(unknown)}。"})
        source = require_token(str(payload.get("source_token") or ""), role="source")
        source_path = Path(str(source["path"])).resolve()
        if _sha256_file(source_path) != source.get("sha256"):
            raise HTTPException(status_code=409, detail={"code": "SOURCE_IDENTITY_CHANGED", "message": "图片内容发生变化，请重新选择。"})
        reference_source = None
        if payload.get("reference_source_token"):
            try:
                reference_source = require_token(str(payload["reference_source_token"]), role="source")
            except HTTPException as exc:
                raise HTTPException(status_code=404, detail={"code": "REFERENCE_TOKEN_INVALID", "message": "参考图片会话无效，请重新选择。"}) from exc
            reference_path = Path(str(reference_source["path"])).resolve()
            if _sha256_file(reference_path) != reference_source.get("sha256"):
                raise HTTPException(status_code=409, detail={"code": "REFERENCE_IDENTITY_CHANGED", "message": "参考图片内容发生变化，请重新选择。"})
        prune_level_preview_sessions()
        try:
            if reference_source is None:
                preview = await asyncio.to_thread(build_level_pick_preview, source_path)
            else:
                preview = await asyncio.to_thread(build_reference_level_pick_preview, source_path, reference_path)
        except ColorManagementError as exc:
            raise HTTPException(status_code=415, detail={"code": "UNSUPPORTED_SOURCE_FORMAT", "message": "图片的格式或色彩信息不受支持，请选择合法 PNG 或 JPEG 图片。"}) from exc
        reference_usable = reference_source is None or bool(preview.plan.usable)
        preview_id = uuid.uuid4().hex
        directory = Path(require_compression_directory()["tmp_dir"]).resolve() / "color-level-preview" / f"preview_{preview_id}"
        directory.mkdir(parents=True, exist_ok=False)
        expires_at = now_provider() + TOKEN_TTL_SECONDS
        icc = srgb_profile_bytes()

        def write_preview(name: str) -> Path:
            pixels = preview.levels[name]
            path = directory / f"{name}.png"
            Image.fromarray(pixels, mode="RGBA" if pixels.shape[2] == 4 else "RGB").save(
                path, format="PNG", icc_profile=icc, compress_level=1,
            )
            return path

        def write_all_previews() -> dict[str, Path]:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=len(preview.levels)) as pool:
                return dict(zip(preview.levels, pool.map(write_preview, preview.levels)))

        paths = await asyncio.to_thread(write_all_previews)
        levels: dict[str, dict[str, Any]] = {}
        for name, path in paths.items():
            levels[name] = {
                "pixel_sha256": preview.pixel_sha256[name],
                "path": str(path),
                "preview_token": preview_token_for(path, role="output_preview"),
                "safety": preview.safety[name],
                # an unusable reference leaves every level unchanged; none of them may be produced
                "selectable": bool(preview.safety[name]["passed"]) and reference_usable,
            }
        analysis_record = preview.plan.to_record() if reference_source is not None else preview.analysis.to_record()
        color_level_preview_sessions[preview_id] = {
            "preview_id": preview_id,
            "source": dict(source),
            "source_sha256": str(source["sha256"]),
            "reference": dict(reference_source) if reference_source is not None else None,
            "reference_sha256": str(reference_source["sha256"]) if reference_source is not None else None,
            "directory": str(directory),
            "levels": levels,
            "analysis": analysis_record,
            "expires_at": expires_at,
            "running_task_id": None,
            "used_by_task_id": None,
        }
        emit_runtime_event(
            "COLOR_LEVEL_PREVIEW_CREATED", stage="level_pick_preview", result="success",
            impact="level_preview_available",
            operation="REFERENCE_LEVEL_PICK_COLOR_CORRECTION" if reference_source is not None else "LEVEL_PICK_COLOR_CORRECTION",
            feature_key=COLOR_CORRECTION_FEATURE_KEY,
            category=analysis_record.get("category") or ("REFERENCE_SHIFT" if reference_usable else "REFERENCE_UNUSABLE"),
            processing_time_ms=preview.processing_time_ms,
        )
        return {"code": 200, "status": "success", "success": True, "data": {
            "preview_id": preview_id,
            "level_pick_version": LEVEL_PICK_VERSION,
            "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
            "processing_time_ms": preview.processing_time_ms,
            "measurement": public_reference_measurement(analysis_record) if reference_source is not None else public_level_measurement(analysis_record),
            **({"reference_preview_url": preview_url(preview_token_for(reference_path, role="source_preview")),
                "reference_display_name": str(reference_source.get("filename") or "参考图")} if reference_source is not None else {}),
            "levels": [
                {"level": "original", "label": LEVEL_LABELS["original"], "preview_url": preview_url(preview_token_for(source_path, role="source_preview")), "selectable": True, "failures": []},
                *({
                    "level": name, "label": LEVEL_LABELS[name], "preview_url": preview_url(item["preview_token"]),
                    "selectable": item["selectable"], "failures": list(item["safety"]["failures"]),
                    "delta_e00_mean": item["safety"]["delta_e00_mean"], "neutral_delta_e00_mean": item["safety"]["neutral_delta_e00_mean"],
                } for name, item in levels.items()),
            ],
        }}

    @app.post("/api/color-correction/level-run")
    async def color_correction_level_run(payload: dict = Body(default_factory=dict)):
        require_compression_directory()
        allowed_fields = {"preview_id", "level", "current_task_output_root", "client_context"}
        unknown = sorted(str(key) for key in payload if key not in allowed_fields)
        if unknown or not payload.get("preview_id") or not payload.get("level"):
            raise HTTPException(status_code=400, detail={"code": "LEVEL_RUN_REQUEST_INVALID", "message": "挑档校色请求需要 preview_id 与 level，且不能包含其他字段。"})
        level = str(payload["level"])
        if level not in LEVEL_LABELS:
            raise HTTPException(status_code=400, detail={"code": "LEVEL_PICK_UNKNOWN_LEVEL", "message": "档位只能是原图、轻、中或强。"})
        session = color_level_preview_sessions.get(str(payload["preview_id"]))
        if session is None:
            raise HTTPException(status_code=404, detail={"code": "LEVEL_PREVIEW_NOT_FOUND", "message": "预览已失效（可能服务已重启），请重新生成预览。"})
        if session["expires_at"] <= now_provider():
            raise HTTPException(status_code=410, detail={"code": "LEVEL_PREVIEW_EXPIRED", "message": "预览已过期，请重新生成预览。"})
        if session.get("used_by_task_id") or session.get("running_task_id"):
            raise HTTPException(status_code=409, detail={"code": "LEVEL_PREVIEW_ALREADY_USED", "message": "这组预览已经生成过结果，请重新生成预览后再选择。"})
        if level != "original" and not session["levels"][level]["selectable"]:
            raise HTTPException(status_code=409, detail={"code": "LEVEL_NOT_SELECTABLE", "message": "该档位未通过安全检查，不能选择。"})
        source_path = Path(str(session["source"]["path"])).resolve()
        if not source_path.is_file() or _sha256_file(source_path) != session["source_sha256"]:
            raise HTTPException(status_code=409, detail={"code": "SOURCE_IDENTITY_CHANGED", "message": "原图已变化或不存在，请重新选择图片。"})
        if session.get("reference"):
            reference_path = Path(str(session["reference"]["path"])).resolve()
            if not reference_path.is_file() or _sha256_file(reference_path) != session["reference_sha256"]:
                raise HTTPException(status_code=409, detail={"code": "REFERENCE_IDENTITY_CHANGED", "message": "参考图已变化或不存在，请重新选择参考图。"})
        if level == "original":
            session["used_by_task_id"] = "ORIGINAL_SELECTED"
            release_used_level_preview(session)
            emit_runtime_event(
                "COLOR_LEVEL_PICK_ORIGINAL_SELECTED", stage="human_quality_review", result="original_selected",
                impact="original_preserved_no_new_result",
                operation="REFERENCE_LEVEL_PICK_COLOR_CORRECTION" if session.get("reference") else "LEVEL_PICK_COLOR_CORRECTION",
                feature_key=COLOR_CORRECTION_FEATURE_KEY, category=session["analysis"].get("category") or "REFERENCE_SHIFT",
            )
            return {"code": 200, "status": "success", "success": True, "data": {
                "selected_level": "original", "task": None, "result": None,
                "message": "已选择原图，未生成新文件。",
            }}
        output_root = effective_color_output_root(payload)
        record = create_color_task_record(session["source"], output_root, level_pick={
            "preview_id": session["preview_id"], "level": level, "analysis": dict(session["analysis"]),
            **({"reference": dict(session["reference"])} if session.get("reference") else {}),
        })
        session["running_task_id"] = record["task_id"]
        try:
            await asyncio.to_thread(execute_level_pick_task, record, session)
        finally:
            session["running_task_id"] = None
        if record.get("status") != "completed":
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=500, content={
                "code": "LEVEL_PICK_OUTPUT_UNAVAILABLE", "status": "failed", "success": False,
                "message": record.get("failure_reason") or "挑档校色未能生成结果。",
                "data": public_color_result(record),
            })
        session["used_by_task_id"] = record["task_id"]
        release_used_level_preview(session)
        return {"code": 200, "status": "success", "success": True, "data": {
            "selected_level": level, **public_color_result(record),
        }}

    @app.post("/api/color-correction/batches", status_code=202)
    async def color_correction_batch_create(payload: dict = Body(default_factory=dict)):
        require_compression_directory()
        allowed_fields = {"source_tokens", "current_task_output_root", "client_context"}
        unknown = sorted(str(key) for key in payload if key not in allowed_fields)
        if unknown:
            raise HTTPException(status_code=400, detail={"code": "COLOR_BATCH_REQUEST_INVALID", "message": f"批量颜色校正请求包含未知字段：{', '.join(unknown)}。"})
        source_tokens = payload.get("source_tokens")
        if not isinstance(source_tokens, list) or not 2 <= len(source_tokens) <= 20:
            raise HTTPException(status_code=400, detail={"code": "COLOR_BATCH_REQUEST_INVALID", "message": "批量颜色校正每次需要选择2至20张图片。"})
        normalized_tokens = [str(token or "") for token in source_tokens]
        if len(set(normalized_tokens)) != len(normalized_tokens):
            raise HTTPException(status_code=400, detail={"code": "COLOR_BATCH_REQUEST_INVALID", "message": "同一批次不能重复提交同一张图片。"})
        sources = [require_token(token, role="source") for token in normalized_tokens]
        output_root = effective_color_output_root(payload)
        output_dir = color_output_dir(Path(str(output_root["normalized_path"])).resolve())
        batch_created_at = now_provider()
        batch_id = f"color_batch_{uuid.uuid4().hex[:16]}"
        batch_operation = new_operation_identity("batch_processing", module_id="hdde.processing.batch")
        records = [
            create_color_task_record(source, output_root, batch_id=batch_id, batch_index=index)
            for index, source in enumerate(sources, start=1)
        ]
        batch = {
            "record_kind": "batch",
            **batch_operation,
            "batch_id": batch_id,
            "status": "pending",
            "progress": 0,
            "total_count": len(records),
            "completed_count": 0,
            "failed_count": 0,
            "created_at": datetime.fromtimestamp(batch_created_at, tz=timezone.utc).isoformat(),
            "started_at": None,
            "completed_at": None,
            "current_task_id": None,
            "output_dir": output_dir,
            "task_ids": [record["task_id"] for record in records],
            "processing_stage": "batch_queue",
            "error_context": {},
            "task_context": {
                **batch_operation,
                "batch_id": batch_id,
                "purpose": "COLOR_CORRECTION_BATCH",
                "route": "/color-correction",
                "route_family": "color_correction",
            },
        }
        color_batch_registry[batch_id] = batch
        if shared_task_registry is not None:
            shared_task_registry[batch_id] = batch
        emit_runtime_event(
            "COLOR_BATCH_QUEUED",
            stage="batch_queue",
            result="queued",
            operation="AUTO_COLOR_CORRECTION",
            batch_id=batch_id,
            status="pending",
            total_count=batch["total_count"],
            impact="batch_waiting_for_local_worker",
            action="process_queue_sequentially",
            feature_key=COLOR_CORRECTION_FEATURE_KEY,
            **{key: batch_operation[key] for key in ("module_id", "operation_id", "trace_id")},
        )
        ensure_color_batch_worker()
        color_batch_queue.put(batch_id)
        return {"code": 202, "status": "accepted", "success": True, "data": public_color_batch(batch)}

    @app.get("/api/color-correction/batches")
    async def color_correction_batch_list():
        require_compression_directory()
        batches = sorted(
            color_batch_registry.values(),
            key=lambda item: str(item.get("created_at") or ""),
            reverse=True,
        )
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "data": {"batches": [public_color_batch(batch) for batch in batches], "count": len(batches)},
        }

    @app.get("/api/color-correction/batches/{batch_id}")
    async def color_correction_batch_status(batch_id: str):
        require_compression_directory()
        batch = color_batch_registry.get(str(batch_id or ""))
        if not batch:
            raise HTTPException(status_code=404, detail={"code": "COLOR_BATCH_NOT_FOUND", "message": "批量颜色校正任务不存在。"})
        return {"code": 200, "status": "success", "success": True, "data": public_color_batch(batch)}

    @app.get("/api/color-correction/tasks/{task_id}")
    async def color_correction_task(task_id: str):
        require_compression_directory()
        record = require_color_record(task_id)
        return {"code": 200, "status": "success", "success": True, "data": public_color_result(record)}

    @app.post("/api/color-correction/tasks/{task_id}/review")
    async def color_correction_task_review(task_id: str, payload: dict = Body(default_factory=dict)):
        require_compression_directory()
        if set(payload) != {"status"}:
            raise HTTPException(status_code=400, detail={"code": "COLOR_REVIEW_REQUEST_INVALID", "message": "人工确认请求只能包含status字段。"})
        record = require_color_record(task_id)
        review_status = str(payload.get("status") or "").strip().lower()
        if review_status not in {"pending", "confirmed"}:
            raise HTTPException(status_code=400, detail={"code": "COLOR_REVIEW_STATUS_INVALID", "message": "人工确认状态必须为pending或confirmed。"})
        output_path = Path(record["output_path"]).resolve() if record.get("output_path") else None
        result = dict(record.get("result") or {})
        if record.get("status") != "completed" or not output_path or not output_path.is_file():
            raise HTTPException(status_code=409, detail={"code": "COLOR_REVIEW_RESULT_UNAVAILABLE", "message": "当前任务没有可供人工确认的真实结果。"})
        if not result.get("output_sha256") or _sha256_file(output_path) != result["output_sha256"]:
            raise HTTPException(status_code=409, detail={"code": "COLOR_REVIEW_RESULT_CHANGED", "message": "当前结果文件与任务记录不一致，不能写入人工确认状态。"})
        is_review_candidate = (
            record.get("d3_final_action") == "REVIEW_REQUIRED"
            and record.get("result_action") == "REVIEW_REQUIRED"
            and record.get("output_selected") == "REVIEW_CANDIDATE"
        )
        record["result_review_status"] = review_status
        record["result_reviewed_at"] = lifecycle_timestamp() if review_status == "confirmed" else None
        if is_review_candidate:
            formal_result_file = str(output_path) if review_status == "confirmed" else ""
            delivery_eligible = review_status == "confirmed"
            delivery_authority = "HUMAN_CONFIRMED_REVIEW" if delivery_eligible else ""
            result.update({
                "result_file": formal_result_file,
                "delivery_eligible": delivery_eligible,
                "delivery_acceptance_authority": delivery_authority,
                "result_review_status": review_status,
            })
            record.update({
                "result": result,
                "task_result": dict(result),
                "result_file": formal_result_file,
                "delivery_eligible": delivery_eligible,
                "delivery_acceptance_authority": delivery_authority,
            })
        if shared_task_registry is not None:
            shared_task_registry[str(record["task_id"])] = record
        if is_review_candidate and review_status == "confirmed":
            previous_eligibility = load_delivery_eligibility(str(result.get("result_id") or ""))
            # The verified human confirmation supersedes only the earlier
            # REVIEW rejection, never an artifact/identity safety failure.
            if (
                previous_eligibility is not None
                and previous_eligibility.get("failure_code") == "COLOR_RESULT_NOT_ACCEPTED"
            ):
                persist_delivery_eligibility(
                    str(result["result_id"]),
                    eligible=True,
                    registered_output_sha256=str(result["output_sha256"]),
                    current_output_sha256=str(result["output_sha256"]),
                )
        emit_runtime_event(
            "QUALITY_REVIEW_UPDATED",
            stage="human_quality_review",
            result="success",
            status=review_status,
            impact="color_result_review_updated",
            action="continue_delivery" if review_status == "confirmed" else "review_result",
            **color_task_event_fields(record),
        )
        if review_status == "confirmed":
            emit_runtime_event(
                "USER_CONFIRMED",
                stage="human_quality_review",
                result="success",
                impact="color_result_confirmed",
                **color_task_event_fields(record),
            )
            if is_review_candidate:
                emit_runtime_event(
                    "RESULT_CONFIRMED",
                    stage="result_registry",
                    result="success",
                    impact="human_confirmed_unified_result_available",
                    acceptance_authority="HUMAN_CONFIRMED_REVIEW",
                    **color_task_event_fields(record),
                )
        return {"code": 200, "status": "success", "success": True, "data": public_color_result(record)}

    @app.post("/api/color-correction/feedback-report")
    async def color_correction_feedback_report(payload: dict = Body(default_factory=dict)):
        require_compression_directory()
        if not set(payload).issubset({"task_id", "category", "description"}) or "task_id" not in payload:
            raise HTTPException(status_code=400, detail={"code": "FEEDBACK_REPORT_REQUEST_INVALID", "message": "问题反馈请求字段不正确。"})
        task_id = str(payload.get("task_id") or "")
        record = task_registry.get(task_id)
        if not record or record.get("task_family") != "color_correction":
            raise HTTPException(status_code=404, detail={"code": "COLOR_CORRECTION_TASK_NOT_FOUND", "message": "颜色校正任务不存在。"})
        if record.get("status") != "completed" or not record.get("result"):
            raise HTTPException(status_code=409, detail={"code": "FEEDBACK_REPORT_TASK_INCOMPLETE", "message": "任务完成后才能生成问题反馈报告。"})
        existing = record.get("feedback_report")
        if isinstance(existing, Mapping) and Path(str(existing.get("report_path") or "")).is_file():
            return {"code": 200, "status": "success", "success": True, "data": dict(existing)}
        description = str(payload.get("description") or "").strip()
        if len(description) > 1000:
            raise HTTPException(status_code=400, detail={"code": "FEEDBACK_REPORT_REQUEST_INVALID", "message": "问题描述不得超过1000个字符。"})
        result = dict(record["result"])
        output_path = Path(record["output_path"]).resolve()
        report_path = unique_output_path(Path(record["output_dir"]), f"影界HDDE_问题反馈_{task_id}.json")
        generated_at = lifecycle_timestamp()
        runtime_context = dict(feedback_runtime_provider() or {}) if feedback_runtime_provider else {}
        error_context = record.get("error_context") if isinstance(record.get("error_context"), Mapping) else {}
        record["related_events"] = related_runtime_events(
            feature_key=str(record.get("feature_key") or ""),
            operation_id=str(record.get("operation_id") or ""),
            trace_id=str(record.get("trace_id") or error_context.get("trace_id") or ""),
            task_id=task_id,
            result_id=str(record.get("result_id") or ""),
            delivery_id=str(record.get("delivery_id") or ""),
            batch_id=str(record.get("batch_id") or ""),
            error_id=str(error_context.get("error_id") or ""),
        )
        feedback_context = build_feedback_context(
            record,
            runtime=runtime_context,
            user_description=description,
        )
        report_data = {
            "report_version": "hdde.color-correction-feedback.v1",
            "created_at": generated_at,
            "environment": {
                **build_feedback_environment(generated_at),
                "color_correction_engine_version": FORMAL_COLOR_RUNTIME_VERSION,
            },
            "task": {
                "task_id": task_id,
                "processing_type": record["operation_mode"],
                "status": record["status"],
                "created_at": record["created_at"],
                "completed_at": record.get("completed_at"),
                "lifecycle": [dict(item) for item in record.get("lifecycle", [])],
                "failure_code": None,
                "failure_reason": record.get("failure_reason"),
            },
            "files": {
                "source_reference": feedback_context["references"]["source"],
                "output_reference": feedback_context["references"]["result"],
                "output_directory_label": "formal_color_output",
                "source_sha256": result.get("source_sha256"),
                "output_sha256": result.get("output_sha256"),
                "source": {
                    "width": result.get("width"),
                    "height": result.get("height"),
                    "format": result.get("source_format"),
                    "size_bytes": result.get("source_size_bytes"),
                },
                "output": {
                    "width": result.get("width"),
                    "height": result.get("height"),
                    "format": result.get("output_format"),
                    "size_bytes": result.get("output_size_bytes"),
                },
            },
            "processing": {
                "engine_version": result.get("engine_version"),
                "analysis": result.get("analysis"),
                "before_metrics": result.get("before_metrics"),
                "after_metrics": result.get("after_metrics"),
                "detected_issues": result.get("detected_issues"),
                "applied_actions": result.get("applied_actions"),
                "parameters": result.get("parameters"),
                "processing_time_ms": result.get("processing_time_ms"),
            },
            "user_feedback": {
                "category": str(payload.get("category") or "结果不符合预期")[:80],
                "description": description,
            },
            "context": feedback_context,
            "validation": {
                "output_exists": output_path.is_file(),
                "output_size_positive": output_path.is_file() and output_path.stat().st_size > 0,
                "output_decoded": True,
                "dimensions_preserved": True,
                "format_and_extension_consistent": True,
                "source_unchanged": True,
                "formal_output_directory_ready": True,
                "project_tmp_fallback_used": False,
            },
            "privacy": {
                "source_image_included": False,
                "output_image_included": False,
                "absolute_paths_included": False,
                "external_upload_performed": False,
            },
        }
        report_bytes = (json.dumps(report_data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        try:
            with report_path.open("xb") as handle:
                handle.write(report_bytes)
        except FileExistsError as exc:
            emit_runtime_event(
                "FEEDBACK_REPORT_GENERATION_FAILED",
                level=logging.WARNING,
                stage="feedback_report_write",
                result="blocked",
                error_category="USER_ACTION_REQUIRED",
                status=record.get("status") or "",
                error_code="FEEDBACK_REPORT_EXISTS",
                error_stage="feedback_report_write",
                reason="feedback_report_already_exists",
                impact="new_feedback_report_not_created",
                action="use_existing_feedback_report",
                **color_task_event_fields(record),
            )
            raise HTTPException(status_code=409, detail={"code": "FEEDBACK_REPORT_EXISTS", "message": "同名问题反馈报告已存在，未覆盖既有文件。"}) from exc
        except Exception as exc:
            diagnostics = build_exception_diagnostics(
                exc,
                error_category="ENVIRONMENT_ERROR" if isinstance(exc, OSError) else "PRODUCT_ERROR",
                error_stage="feedback_report_write",
                trace_id=str(record.get("trace_id") or ""),
            )
            emit_runtime_event(
                "FEEDBACK_REPORT_GENERATION_FAILED",
                level=logging.ERROR,
                stage="feedback_report_write",
                result="failed",
                status=record.get("status") or "",
                impact="feedback_report_unavailable",
                action="check_runtime_log_and_output_directory",
                **{**color_task_event_fields(record), **diagnostics},
            )
            raise
        try:
            token = issue_token(
                report_path,
                role="color_feedback_report",
                filename=report_path.name,
                task_id=task_id,
                sha256=hashlib.sha256(report_bytes).hexdigest(),
            )
        except Exception as exc:
            diagnostics = build_exception_diagnostics(
                exc,
                error_category="PRODUCT_ERROR",
                error_stage="feedback_report_registration",
                trace_id=str(record.get("trace_id") or ""),
            )
            emit_runtime_event(
                "FEEDBACK_REPORT_GENERATION_FAILED",
                level=logging.ERROR,
                stage="feedback_report_registration",
                result="failed",
                status=record.get("status") or "",
                impact="feedback_report_download_unavailable",
                action="check_runtime_log_and_report_registry",
                **{**color_task_event_fields(record), **diagnostics},
            )
            raise
        feedback = {
            "task_id": task_id,
            "report_name": report_path.name,
            "report_path": str(report_path),
            "report_size_bytes": len(report_bytes),
            "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "download_url": f"/api/color-correction/feedback-report/{token}",
            "source_image_included": False,
            "output_image_included": False,
            "absolute_paths_included": False,
            "external_upload_performed": False,
            "context_preview": feedback_context_preview(feedback_context),
        }
        record["feedback_report"] = feedback
        record["feedback_report_token"] = token
        emit_runtime_event(
            "FEEDBACK_REPORT_GENERATED",
            stage="feedback_report_generation",
            result="success",
            status=record.get("status") or "",
            runtime_log_reference=str(runtime_context.get("runtime_log_reference") or ""),
            impact="feedback_report_available",
            action="user_review_and_decide_whether_to_send",
            **color_task_event_fields(record),
        )
        return {"code": 200, "status": "success", "success": True, "data": feedback}

    def validated_color_target(task_id: str, *, output_file: bool) -> tuple[dict[str, Any], Path]:
        record = require_color_record(task_id)
        target = Path(record["output_path"] if output_file else record["output_dir"]).resolve()
        root = Path(record["effective_output_root"]).resolve()
        if root not in target.parents or not target.exists() or (output_file and not target.is_file()) or (not output_file and not target.is_dir()):
            raise HTTPException(status_code=403, detail={"code": "COLOR_CORRECTION_OUTPUT_INVALID", "message": "颜色校正结果不在受控输出目录内。"})
        return record, target

    @app.post("/api/color-correction/open-output")
    async def color_correction_open_output(payload: dict = Body(default_factory=dict)):
        require_compression_directory()
        if set(payload) != {"task_id"}:
            raise HTTPException(status_code=400, detail={"code": "COLOR_CORRECTION_OPEN_INVALID", "message": "只能通过已登记的任务打开结果。"})
        _, target = validated_color_target(str(payload.get("task_id") or ""), output_file=True)
        try:
            if folder_opener is not None:
                folder_opener(str(target))
            elif os.name == "nt":
                os.startfile(str(target))  # noqa: S606 - validated local output file only
            else:
                raise OSError("当前系统不支持自动打开本地结果。")
        except Exception as exc:
            raise HTTPException(status_code=400, detail={"code": "COLOR_CORRECTION_OPEN_FAILED", "message": "打开校正结果失败。"}) from exc
        return {"code": 200, "status": "success", "success": True, "data": {"file_label": target.name}}

    @app.post("/api/color-correction/open-output-folder")
    async def color_correction_open_output_folder(payload: dict = Body(default_factory=dict)):
        require_compression_directory()
        if set(payload) != {"task_id"}:
            raise HTTPException(status_code=400, detail={"code": "COLOR_CORRECTION_OPEN_INVALID", "message": "只能通过已登记的任务打开输出目录。"})
        _, target = validated_color_target(str(payload.get("task_id") or ""), output_file=False)
        try:
            if folder_opener is not None:
                folder_opener(str(target))
            elif os.name == "nt":
                os.startfile(str(target))  # noqa: S606 - validated local output directory only
            else:
                raise OSError("当前系统不支持自动打开本地目录。")
        except Exception as exc:
            raise HTTPException(status_code=400, detail={"code": "COLOR_CORRECTION_OPEN_FAILED", "message": "打开输出目录失败。"}) from exc
        return {"code": 200, "status": "success", "success": True, "data": {"directory_label": target.name}}

    @app.get("/api/color-correction/feedback-report/{token}")
    async def color_correction_feedback_report_download(token: str):
        require_compression_directory()
        item = require_token(token, role="color_feedback_report")
        path = Path(item["path"]).resolve()
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != str(item.get("sha256") or ""):
            raise HTTPException(status_code=409, detail={"code": "FEEDBACK_REPORT_SHA_MISMATCH", "message": "问题反馈报告完整性校验失败。"})
        filename = _safe_name(item.get("filename") or path.name)
        return Response(
            content=content,
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, no-store",
            },
        )

    def require_output_center_item(item_id: str) -> dict[str, Any]:
        item_key = str(item_id or "")
        item = output_center_index.get(item_key)
        if not item:
            build_output_center_snapshot()
            item = output_center_index.get(item_key)
        if not item:
            raise HTTPException(
                status_code=404,
                detail={"code": "OUTPUT_ITEM_NOT_FOUND", "message": "该成品已不存在或不属于当前正式输出。"},
            )
        output_path = Path(item["output_path"]).resolve()
        if not output_path.is_file():
            raise HTTPException(
                status_code=404,
                detail={"code": "OUTPUT_ITEM_MISSING", "message": "该成品文件已不存在。"},
            )
        binding = output_center_batch_bindings.get(item_key)
        if binding:
            try:
                user_dirs = (output_center_user_dirs_provider or user_dirs_provider)()
                source = resolve_reusable_result_source(shared_task_registry, binding["result_id"], Path(user_dirs["app_data_root"]), max_bytes=MAX_UPLOAD_BYTES, allowed_suffixes=ALLOWED_EXTENSIONS)
                if (binding.get("binding_error") or source["source_task_id"] != binding["task_id"]
                        or source["source_result_path"] != output_path
                        or source["source_result_sha256"] != binding["output_sha256"]):
                    raise ValueError("BATCH_RESULT_BINDING_MISMATCH")
            except (ResultReuseError, OSError, ValueError) as exc:
                raise HTTPException(409, detail={"code": "RESULT_IDENTITY_MISMATCH", "message": "当前文件与批次 Result 的身份或 SHA 不一致，已停止操作。"}) from exc
        return item

    @app.post("/api/output-center/items/{item_id}/clear")
    async def clear_output_center_record(item_id: str):
        if shared_task_registry is None:
            raise HTTPException(503, detail="输出记录暂时无法保存。")
        snapshot = build_output_center_snapshot()
        card = next((entry for entry in snapshot["items"] if entry["id"] == item_id), None)
        parent = next((entry for entry in snapshot["items"] if entry.get("card_type") == "batch"
                       and any(child.get("record_id") == item_id or child["id"] == item_id for child in entry["items"])), None)
        if card is None and parent:
            card = next(child for child in parent["items"] if child.get("record_id") == item_id or child["id"] == item_id)
        if card is None:
            raise HTTPException(404, detail="输出记录不存在。")
        if card.get("running") or (parent and parent.get("running")):
            raise HTTPException(409, detail="请等待批次结束后再清除记录。")
        removed = persist_output_record_removals([card])
        return {"success": True, "data": {"item_id": item_id, "removed_ids": removed,
            **output_removal_counts(snapshot, removed), "files_deleted": False}}

    def output_removal_counts(snapshot, removed):
        removed = set(removed)
        counts = dict(snapshot["scope_counts"])
        cards = []
        batches = []
        for card in snapshot["items"]:
            remaining = [child for child in card.get("items", []) if child["id"] not in removed and child["record_id"] not in removed]
            emptied = card.get("card_type") == "batch" and not remaining
            if card["id"] in removed or emptied:
                counts[card["list_scope"]] -= 1
                cards.append({"id": card["id"], "scope": card["list_scope"], "category": card["processing_type"]})
            elif remaining and len(remaining) != len(card["items"]):
                updated = output_remaining_batch(card, remaining)
                batches.append({key: updated[key] for key in ("id", "file_name", "summary")})
        return {"scope_counts": counts, "removed_cards": cards, "updated_batches": batches}

    def persist_output_record_removals(records):
        removed = set()
        by_id = {}
        for record in records:
            removed.add(record["id"])
            by_id[record["id"]] = record
            if record.get("record_id"):
                removed.add(record["record_id"])
                by_id[record["record_id"]] = record
        facts = {f"output_center_hidden:{identity}": {
            "record_kind": "output_center_hidden", "item_id": identity,
            "removed_result_id": str(by_id[identity].get("result_id") or ""),
            "output_path": str(by_id[identity].get("output_path") or output_center_index.get(by_id[identity]["id"], {}).get("output_path") or ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        } for identity in removed}
        persist = getattr(shared_task_registry, "persist_facts", None)
        if persist:
            persist(facts)
        else:
            shared_task_registry.update(facts)
        return sorted(removed)

    @app.post("/api/output-center/cleanup")
    async def cleanup_output_center(body: dict = Body(...)):
        if shared_task_registry is None:
            raise HTTPException(503, detail="输出记录暂时无法保存。")
        scope, mode = body.get("scope"), body.get("mode")
        if not isinstance(scope, str) or not isinstance(mode, str) or scope not in {"current", "history"} or mode not in {"missing", "all"}:
            raise HTTPException(422, detail="请选择当前或历史列表及清理方式。")
        snapshot = build_output_center_snapshot(scope=scope)
        targets = []
        for card in snapshot["items"]:
            if card.get("running"):
                continue
            if mode == "all":
                targets.append(card)
            elif card.get("card_type") == "batch":
                targets.extend(child for child in card["items"] if child.get("file_status") == "MISSING")
            elif card.get("file_status") == "MISSING":
                targets.append(card)
        removed = persist_output_record_removals(targets)
        return {"success": True, "data": {"scope": scope, "mode": mode,
            "removed_ids": removed, "removed_count": len(targets),
            **output_removal_counts(snapshot, removed), "files_deleted": False}}

    @app.get("/api/output-center/items")
    async def output_center_items(
        limit: int | None = None,
        offset: int = 0,
        query: str = "",
        sort: str = "newest",
        category: str = "all",
        scope: str = "all",
    ):
        if scope not in {"all", "current", "history"}:
            raise HTTPException(422, detail="列表范围无效。")
        sort_order = "oldest" if sort == "oldest" else "newest"
        data = build_output_center_snapshot(
            limit=limit,
            offset=offset,
            query=query,
            sort_order=sort_order,
            category=category,
            scope=scope,
        )
        return {"code": 200, "status": "success", "success": True, "data": data}

    @app.get("/api/output-center/items/{item_id}/continue-eligibility")
    async def output_center_continue_eligibility(item_id: str):
        # This endpoint intentionally serves only the request-local list snapshot.
        # Strict file/root/SHA/processor validation remains on each intake action.
        item = output_center_index.get(str(item_id or ""))
        eligibility = item.get("continue_eligibility") if isinstance(item, Mapping) else None
        if not isinstance(eligibility, list):
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "OUTPUT_CONTINUE_SNAPSHOT_EXPIRED",
                    "message": "当前成品状态已变化，请刷新输出中心后重试。",
                },
            )
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "data": {
                "version": str(item.get("continue_eligibility_version") or ""),
                "processors": [dict(entry) for entry in eligibility],
            },
        }

    @app.get("/api/output-center/results/{result_id}/lineage")
    async def output_center_result_lineage(result_id: str):
        try:
            data = result_lineage(shared_task_registry or {}, result_id)
        except ResultReuseError as exc:
            raise HTTPException(exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
        return {"success": True, "data": data}

    @app.get("/api/output-center/items/{item_id}/preview")
    async def output_center_preview(item_id: str):
        item = require_output_center_item(item_id)
        path = Path(item["output_path"]).resolve()
        return FileResponse(path, media_type=image_media_type(path), filename=_safe_name(path.name))

    @app.get("/api/output-center/items/{item_id}/thumbnail")
    async def output_center_thumbnail(item_id: str):
        item = require_output_center_item(item_id)
        source_path = Path(item["output_path"]).resolve()
        try:
            async with output_center_thumbnail_semaphore:
                cache_path, entry, cache_hit = await asyncio.to_thread(
                    ensure_output_center_thumbnail,
                    source_path,
                )
        except (OSError, ValueError, RuntimeError, Image.DecompressionBombError) as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "OUTPUT_THUMBNAIL_UNAVAILABLE",
                    "message": "当前成品缩略图暂时无法生成，正式成品未被修改。",
                },
            ) from exc
        return FileResponse(
            cache_path,
            media_type=str(entry["media_type"]),
            headers={
                "Cache-Control": "private, max-age=31536000, immutable",
                "ETag": f'"{entry["signature"]}"',
                "X-HDDE-Thumbnail-Cache": "HIT" if cache_hit else "MISS",
                "X-HDDE-Thumbnail-Max-Edge": str(OUTPUT_CENTER_THUMBNAIL_MAX_EDGE),
            },
        )

    @app.get("/api/output-center/items/{item_id}/source-preview")
    async def output_center_source_preview(item_id: str):
        item = require_output_center_item(item_id)
        source_path = item.get("source_path")
        if not source_path or not Path(source_path).is_file():
            raise HTTPException(
                status_code=404,
                detail={"code": "OUTPUT_SOURCE_MAPPING_UNAVAILABLE", "message": "当前成品没有可靠的原图映射。"},
            )
        path = Path(source_path).resolve()
        return FileResponse(path, media_type=image_media_type(path), filename=_safe_name(path.name))

    def open_output_center_target(item_id: str, *, directory: bool) -> dict[str, Any]:
        item = require_output_center_item(item_id)
        output_path = Path(item["output_path"]).resolve()
        target = output_path.parent if directory else output_path
        try:
            if folder_opener is not None:
                folder_opener(str(target))
            elif os.name == "nt":
                os.startfile(str(target))  # noqa: S606 - server-indexed formal output only
            else:
                raise OSError("当前系统不支持自动打开本地文件。")
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "OUTPUT_ITEM_OPEN_FAILED", "message": "打开成品位置失败，请确认文件仍可访问。"},
            ) from exc
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "data": {"file_name": output_path.name, "directory_name": output_path.parent.name},
        }

    @app.post("/api/output-center/items/{item_id}/open")
    async def output_center_open(item_id: str):
        return open_output_center_target(item_id, directory=False)

    @app.post("/api/output-center/items/{item_id}/open-folder")
    async def output_center_open_folder(item_id: str):
        return open_output_center_target(item_id, directory=True)

    @app.post("/api/smart-delivery/preflight")
    async def smart_delivery_preflight(payload: dict = Body(default_factory=dict)):
        plan = build_smart_delivery_plan(
            payload.get("item_ids"),
            payload.get("result_ids"),
            payload.get("rules"),
            store=True,
        )
        return {"code": 200, "status": "success", "success": True, "data": public_smart_delivery_plan(plan)}

    def normalize_delivery_idempotency_key(raw: Any) -> str:
        value = str(raw or "").strip()
        if not value:
            return ""
        if not SMART_DELIVERY_IDEMPOTENCY_KEY_PATTERN.fullmatch(value):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "SMART_DELIVERY_IDEMPOTENCY_KEY_INVALID",
                    "message": "交付请求身份无效，请重新发起批量交付。",
                },
            )
        return value

    def delivery_request_fact_key(idempotency_key: str) -> str:
        return f"{SMART_DELIVERY_REQUEST_FACT_PREFIX}{idempotency_key}"

    def load_delivery_request(idempotency_key: str) -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        record: Any = None
        if shared_task_registry is not None:
            record = shared_task_registry.get(delivery_request_fact_key(idempotency_key))
        memory_record = smart_delivery_request_registry.get(idempotency_key)
        if not isinstance(record, Mapping):
            record = memory_record
        elif (
            isinstance(memory_record, Mapping)
            and str(record.get("status") or "").upper() == "PROCESSING"
            and str(memory_record.get("status") or "").upper() != "PROCESSING"
            and memory_record.get("delivery_id") == record.get("delivery_id")
        ):
            # This process settled the request but the registry rejected the overwrite.
            record = memory_record
        if not isinstance(record, Mapping) or str(record.get("record_kind") or "") != "delivery_request":
            return None
        return dict(record)

    def persist_delivery_request(record: Mapping[str, Any]) -> dict[str, Any]:
        idempotency_key = str(record.get("idempotency_key") or "")
        normalized = dict(record)
        if not idempotency_key:
            raise RuntimeError("SMART_DELIVERY_IDEMPOTENCY_KEY_REQUIRED")
        if shared_task_registry is not None:
            shared_task_registry[delivery_request_fact_key(idempotency_key)] = normalized
        smart_delivery_request_registry[idempotency_key] = normalized
        return normalized

    def processing_request_is_stale(record: Mapping[str, Any]) -> bool:
        if str(record.get("server_session_id") or "") == server_session_id:
            return False  # Execution of this process settles its own requests.
        try:
            created = datetime.fromisoformat(str(record.get("created_at") or "")).timestamp()
        except ValueError:
            return False  # Unknown age: never declare another process's work dead.
        return now_provider() - created > SMART_DELIVERY_PROCESSING_STALE_SECONDS

    def replay_delivery_request(record: Mapping[str, Any]) -> dict[str, Any]:
        status = str(record.get("status") or "").upper()
        if status == "PROCESSING" and processing_request_is_stale(record):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "SMART_DELIVERY_OUTCOME_UNCONFIRMED",
                    "message": "上次交付在服务重启前中断，结果无法确认；请到智能交付目录核对后再重新交付。",
                    "delivery_id": str(record.get("delivery_id") or ""),
                    "idempotent_replay": True,
                },
            )
        if status == "PROCESSING":
            return {
                "code": 200,
                "status": "success",
                "success": True,
                "data": {
                    "delivery_id": str(record.get("delivery_id") or ""),
                    "result_id": str(record.get("result_id") or ""),
                    "idempotency_key": str(record.get("idempotency_key") or ""),
                    "status": "processing",
                    "idempotent_replay": True,
                    "results": [],
                },
            }
        response_data = record.get("response_data")
        if isinstance(response_data, Mapping):
            replay_data = dict(response_data)
            replay_data["idempotent_replay"] = True
            return {"code": 200, "status": "success", "success": True, "data": replay_data}
        detail = record.get("error_detail")
        if isinstance(detail, Mapping):
            replay_detail = dict(detail)
            replay_detail["idempotent_replay"] = True
            raise HTTPException(status_code=int(record.get("http_status") or 409), detail=replay_detail)
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SMART_DELIVERY_REQUEST_STATE_INVALID",
                "message": "交付请求状态无法确认，未创建新的 Delivery。",
                "idempotent_replay": True,
            },
        )

    @app.get("/api/smart-delivery/requests/{idempotency_key}")
    async def smart_delivery_request_status(idempotency_key: str, result_id: str = ""):
        normalized_key = normalize_delivery_idempotency_key(idempotency_key)
        normalized_result_id = str(result_id or "").strip()
        if not normalized_result_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "SMART_DELIVERY_REQUEST_RESULT_REQUIRED",
                    "message": "确认交付请求时必须提供绑定的 Result。",
                },
            )
        with smart_delivery_request_lock:
            record = load_delivery_request(normalized_key)
            if record is None:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "SMART_DELIVERY_REQUEST_NOT_FOUND",
                        "message": "服务端尚未登记该交付请求。",
                    },
                )
            if str(record.get("result_id") or "") != normalized_result_id:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "SMART_DELIVERY_IDEMPOTENCY_CONFLICT",
                        "message": "交付请求身份与 Result 不匹配。",
                    },
                )
            return replay_delivery_request(record)

    def latest_failed_delivery_for_entry(entry: Mapping[str, Any]) -> str:
        source_task_id = str(entry.get("source_task_id") or "")
        source_result_id = str(entry.get("source_result_id") or "")
        task_record = task_registry.get(source_task_id)
        if not isinstance(task_record, Mapping) and shared_task_registry is not None:
            task_record = shared_task_registry.get(source_task_id)
        if not isinstance(task_record, Mapping) and shared_task_registry is not None:
            result_reference_for_task = getattr(shared_task_registry, "result_reference_for_task", None)
            if callable(result_reference_for_task):
                task_record = result_reference_for_task(source_task_id)
        if not isinstance(task_record, Mapping):
            return ""
        matching_attempts = [
            attempt
            for attempt in list(task_record.get("deliveries") or [])
            if isinstance(attempt, Mapping)
            and str(attempt.get("result_id") or "") == source_result_id
        ]
        if not matching_attempts:
            return ""
        latest_attempt = matching_attempts[-1]
        if str(latest_attempt.get("status") or "") != "failed":
            return ""
        return str(latest_attempt.get("delivery_id") or "")

    def settle_interrupted_delivery_request(
        record: Mapping[str, Any],
        results: list[dict[str, Any]],
        response_data: Mapping[str, Any] | None,
        exc: BaseException,
    ) -> None:
        """Never leave a request PROCESSING after its execution stopped in this process."""
        current = load_delivery_request(str(record.get("idempotency_key") or ""))
        if current is not None and str(current.get("status") or "").upper() != "PROCESSING":
            return  # Already settled with a definite outcome before the exception.
        updated_at = datetime.fromtimestamp(now_provider(), tz=timezone.utc).isoformat()
        if response_data is not None:
            # Copies finished and were verified; only the later registration failed.
            failed = int(response_data.get("failure_count") or 0)
            settled = {
                **record,
                "status": "COMPLETED" if failed == 0 else "FAILED_DEFINITE",
                "delivery_sha256": next(
                    (str(item.get("delivery_sha256") or "") for item in response_data.get("results") or []
                     if item.get("status") == "completed"),
                    "",
                ),
                "http_status": 200,
                "response_data": dict(response_data),
                "registration_error": exc.__class__.__name__,
            }
        elif any(item.get("status") == "completed" for item in results):
            settled = {
                **record,
                "status": "FAILED_UNCONFIRMED",
                "http_status": 409,
                "error_detail": {
                    "code": "SMART_DELIVERY_OUTCOME_UNCONFIRMED",
                    "message": "交付副本可能已生成，但交付记录未能完成；请到智能交付目录核对后再重新交付。",
                },
            }
        else:
            detail = exc.detail if isinstance(exc, HTTPException) and isinstance(exc.detail, Mapping) else {}
            settled = {
                **record,
                "status": "FAILED_DEFINITE",
                "http_status": 409,
                "error_detail": {
                    "code": str(detail.get("code") or "SMART_DELIVERY_INTERRUPTED"),
                    "message": str(detail.get("message") or "交付在生成副本前中断，未生成交付文件，可以重新交付。"),
                },
            }
        settled["updated_at"] = updated_at
        try:
            persist_delivery_request(settled)
        except Exception:
            # Keep the definite outcome for this process; load_delivery_request prefers it
            # over the PROCESSING fact the registry could not overwrite.
            smart_delivery_request_registry[str(settled["idempotency_key"])] = settled
            logger.exception(
                "Smart delivery request could not be settled in the shared registry: delivery_id=%s status=%s",
                settled.get("delivery_id"), settled["status"],
            )

    @app.post("/api/smart-delivery/execute")
    async def smart_delivery_execute(payload: dict = Body(default_factory=dict)):
        # Copies now run off the event loop, so the same plan could be submitted twice
        # while its first run is still copying; never run one plan concurrently.
        plan_id = str(payload.get("plan_id") or "")
        if plan_id in smart_delivery_executing_plans:
            raise HTTPException(
                status_code=409,
                detail={"code": "SMART_DELIVERY_IN_PROGRESS", "message": "该交付清单正在生成副本，请等待完成。"},
            )
        smart_delivery_executing_plans.add(plan_id)
        try:
            return await execute_smart_delivery_plan(payload)
        finally:
            smart_delivery_executing_plans.discard(plan_id)

    async def execute_smart_delivery_plan(payload: dict) -> dict[str, Any]:
        prune_smart_delivery_plans()
        plan_id = str(payload.get("plan_id") or "")
        plan = smart_delivery_plan_registry.get(plan_id)
        if not plan:
            raise HTTPException(
                status_code=404,
                detail={"code": "SMART_DELIVERY_PLAN_EXPIRED", "message": "交付预检已失效，请重新执行安全检查。"},
            )
        if payload.get("confirmed") is not True:
            raise HTTPException(
                status_code=400,
                detail={"code": "SMART_DELIVERY_CONFIRMATION_REQUIRED", "message": "生成交付副本前必须完成用户确认。"},
            )
        idempotency_key = normalize_delivery_idempotency_key(
            payload.get("idempotency_key") or payload.get("delivery_request_id")
        )
        idempotency_result_id = ""
        if idempotency_key:
            planned_result_ids = [
                str(entry.get("source_result_id") or "").strip()
                for entry in list(plan.get("entries") or [])
            ]
            if (
                str(plan.get("selection_mode") or "") != "result_ids"
                or len(planned_result_ids) != 1
                or not planned_result_ids[0]
            ):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "SMART_DELIVERY_IDEMPOTENCY_SCOPE_INVALID",
                        "message": "批量交付请求身份必须绑定且只绑定一个正式 Result。",
                    },
                )
            idempotency_result_id = planned_result_ids[0]
            with smart_delivery_request_lock:
                existing_request = load_delivery_request(idempotency_key)
                if existing_request is not None:
                    if str(existing_request.get("result_id") or "") != idempotency_result_id:
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "code": "SMART_DELIVERY_IDEMPOTENCY_CONFLICT",
                                "message": "交付请求身份已经绑定到另一个 Result，未创建新的 Delivery。",
                            },
                        )
                    return replay_delivery_request(existing_request)
        refreshed = build_smart_delivery_plan(
            plan["item_ids"] if plan["selection_mode"] == "item_ids" else None,
            plan["result_ids"] if plan["selection_mode"] == "result_ids" else None,
            plan["rules"],
            store=False,
        )
        reconcile_smart_delivery_eligibility(refreshed, allow_restore=False)
        if not refreshed["ready"]:
            preflight_code = (
                RESULT_IDENTITY_MISMATCH
                if any(issue.get("code") == RESULT_IDENTITY_MISMATCH for issue in refreshed["issues"])
                else "SMART_DELIVERY_PREFLIGHT_BLOCKED"
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": preflight_code,
                    "message": "交付条件已变化，请处理阻断项后重新确认。",
                    "preflight": public_smart_delivery_plan(refreshed),
                },
            )
        if refreshed["signature"] != plan["signature"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "SMART_DELIVERY_PREVIEW_CHANGED",
                    "message": "源成品或交付目标已经变化，请重新确认。",
                    "preflight": public_smart_delivery_plan(refreshed),
                },
            )

        delivery_id = f"delivery_{datetime.fromtimestamp(now_provider()).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        delivery_operation = new_operation_identity("smart_delivery", module_id="hdde.smart.delivery")
        delivery_request_record: dict[str, Any] | None = None
        if idempotency_key:
            request_now = datetime.fromtimestamp(now_provider(), tz=timezone.utc).isoformat()
            delivery_request_record = {
                "record_kind": "delivery_request",
                "idempotency_key": idempotency_key,
                "result_id": idempotency_result_id,
                "delivery_id": delivery_id,
                "status": "PROCESSING",
                "delivery_sha256": "",
                "plan_signature": str(refreshed.get("signature") or ""),
                "server_session_id": server_session_id,
                "created_at": request_now,
                "updated_at": request_now,
            }
            with smart_delivery_request_lock:
                concurrent_request = load_delivery_request(idempotency_key)
                if concurrent_request is not None:
                    if str(concurrent_request.get("result_id") or "") != idempotency_result_id:
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "code": "SMART_DELIVERY_IDEMPOTENCY_CONFLICT",
                                "message": "交付请求身份已经绑定到另一个 Result，未创建新的 Delivery。",
                            },
                        )
                    return replay_delivery_request(concurrent_request)
                persist_delivery_request(delivery_request_record)
        results: list[dict[str, Any]] = []
        response_data: dict[str, Any] | None = None
        try:
            delivery_root = smart_delivery_root()
            try:
                delivery_root.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                emit_runtime_event(
                    "DELIVERY_FAILED",
                    level=logging.ERROR,
                    stage="delivery_directory",
                    result="failed",
                    delivery_id=delivery_id,
                    reason=str(exc) or exc.__class__.__name__,
                    impact="delivery_copy_unavailable",
                    **delivery_operation,
                )
                failure_detail = {"code": "SMART_DELIVERY_DIRECTORY_UNAVAILABLE", "message": "正式智能交付目录不可用。"}
                if delivery_request_record is not None:
                    persist_delivery_request({
                        **delivery_request_record,
                        "status": "FAILED_DEFINITE",
                        "http_status": 400,
                        "error_detail": failure_detail,
                        "updated_at": datetime.fromtimestamp(now_provider(), tz=timezone.utc).isoformat(),
                    })
                raise HTTPException(
                    status_code=400,
                    detail=failure_detail,
                ) from exc

            for entry in refreshed["entries"]:
                delivery_item_id = uuid.uuid4().hex[:16]
                result_id = entry["source_result_id"] or delivery_item_id
                source_path = Path(entry["_source_path"]).resolve()
                destination_path = Path(entry["_destination_path"]).resolve()
                retry_of_delivery_id = latest_failed_delivery_for_entry(entry)
                correlation_fields = {
                    "source_feature_key": entry["source_feature_key"] or "",
                    "source_module_id": entry["source_module_id"] or "",
                    "parent_operation_id": entry["source_operation_id"] or "",
                    "parent_trace_id": entry["source_trace_id"] or "",
                    "retry_of_delivery_id": retry_of_delivery_id,
                }
                emit_runtime_event(
                    "DELIVERY_CREATED",
                    stage="delivery_registry",
                    result="created",
                    task_id=entry["source_task_id"],
                    result_id=entry["source_result_id"],
                    delivery_id=delivery_id,
                    impact="delivery_identity_registered",
                    **correlation_fields,
                    **delivery_operation,
                )
                if retry_of_delivery_id:
                    emit_runtime_event(
                        "DELIVERY_RETRY_STARTED",
                        stage="delivery_copy",
                        result="started",
                        task_id=entry["source_task_id"],
                        result_id=entry["source_result_id"],
                        delivery_id=delivery_id,
                        impact="delivery_retry_running",
                        **correlation_fields,
                        **delivery_operation,
                    )
                emit_runtime_event(
                    "DELIVERY_STARTED",
                    stage="delivery_copy",
                    result="started",
                    task_id=entry["source_task_id"],
                    result_id=entry["source_result_id"],
                    delivery_id=delivery_id,
                    impact="delivery_copy_running",
                    **correlation_fields,
                    **delivery_operation,
                )
                try:
                    copied = await asyncio.to_thread(
                        copy_delivery_item,
                        source_path,
                        destination_path,
                        registered_output_sha256=entry["_registered_output_sha256"],
                    )
                    results.append({
                        "result_id": result_id,
                        "delivery_item_id": delivery_item_id,
                        "delivery_id": delivery_id,
                        "item_id": entry["item_id"],
                        "source_result_id": entry["source_result_id"],
                        "task_id": entry["source_task_id"],
                        "feature_key": entry["source_feature_key"],
                        "module_id": entry["source_module_id"],
                        "operation_id": entry["source_operation_id"],
                        "trace_id": entry["source_trace_id"],
                        "parent_operation_id": entry["source_operation_id"],
                        "parent_trace_id": entry["source_trace_id"],
                        "retry_of_delivery_id": retry_of_delivery_id,
                        "source_processing_type": entry["source_processing_type"],
                        "source_file_name": entry["source_file_name"],
                        "source_filename": entry["source_filename"],
                        "suggested_filename": entry["suggested_filename"],
                        "final_filename": entry["final_filename"],
                        "naming_source": entry["naming_source"],
                        "naming_evidence": entry["naming_evidence"],
                        "delivery_file_name": entry["delivery_file_name"],
                        "content_name": entry["content_name"],
                        "content_name_source": entry["content_name_source"],
                        "status": "completed",
                        "failure_reason": "",
                        **copied,
                        "_destination_path": destination_path,
                        "_delivery_path": str(destination_path),
                    })
                    emit_runtime_event(
                        "DELIVERY_SUCCEEDED",
                        stage="delivery_copy",
                        result="success",
                        task_id=entry["source_task_id"],
                        result_id=entry["source_result_id"],
                        delivery_id=delivery_id,
                        impact="delivery_copy_available",
                        **correlation_fields,
                        **delivery_operation,
                    )
                except Exception as exc:
                    failure_code = (
                        RESULT_IDENTITY_MISMATCH
                        if isinstance(exc, OutputIdentityMismatchError)
                        else "SMART_DELIVERY_COPY_FAILED"
                    )
                    if failure_code == RESULT_IDENTITY_MISMATCH:
                        persist_delivery_eligibility(
                            str(entry.get("source_result_id") or ""),
                            eligible=False,
                            code=RESULT_IDENTITY_MISMATCH,
                            reason="实际复制字节与 Result 登记身份不一致，未发布 Delivery。",
                            registered_output_sha256=str(entry.get("_registered_output_sha256") or ""),
                        )
                    diagnostics = build_exception_diagnostics(
                        exc,
                        error_category="ENVIRONMENT_ERROR" if isinstance(exc, OSError) else "PRODUCT_ERROR",
                        error_stage="delivery_copy",
                        trace_id=delivery_operation["trace_id"],
                    )
                    results.append({
                        "result_id": result_id,
                        "delivery_item_id": delivery_item_id,
                        "delivery_id": delivery_id,
                        "item_id": entry["item_id"],
                        "source_result_id": entry["source_result_id"],
                        "task_id": entry["source_task_id"],
                        "feature_key": entry["source_feature_key"],
                        "module_id": entry["source_module_id"],
                        "operation_id": entry["source_operation_id"],
                        "trace_id": entry["source_trace_id"],
                        "parent_operation_id": entry["source_operation_id"],
                        "parent_trace_id": entry["source_trace_id"],
                        "retry_of_delivery_id": retry_of_delivery_id,
                        "source_processing_type": entry["source_processing_type"],
                        "source_file_name": entry["source_file_name"],
                        "source_filename": entry["source_filename"],
                        "suggested_filename": entry["suggested_filename"],
                        "final_filename": entry["final_filename"],
                        "naming_source": entry["naming_source"],
                        "naming_evidence": entry["naming_evidence"],
                        "delivery_file_name": entry["delivery_file_name"],
                        "content_name": entry["content_name"],
                        "content_name_source": entry["content_name_source"],
                        "status": "failed",
                        "failure_code": failure_code,
                        "failure_reason": str(exc) or "生成交付副本失败。",
                        "source_sha256": "",
                        "delivery_sha256": "",
                        "source_unchanged": False,
                        "size_bytes": 0,
                        "_destination_path": None,
                        "_delivery_path": "",
                        "_error_context": diagnostics,
                    })
                    emit_runtime_event(
                        "DELIVERY_FAILED",
                        level=logging.ERROR,
                        stage="delivery_copy",
                        result="failed",
                        task_id=entry["source_task_id"],
                        result_id=entry["source_result_id"],
                        delivery_id=delivery_id,
                        impact="delivery_copy_unavailable",
                        **correlation_fields,
                        **{**delivery_operation, **diagnostics},
                    )

            succeeded = sum(1 for result in results if result["status"] == "completed")
            failed = len(results) - succeeded
            run = {
                **delivery_operation,
                "delivery_id": delivery_id,
                "idempotency_key": idempotency_key,
                "status": "completed" if failed == 0 else ("partial" if succeeded else "failed"),
                "success_count": succeeded,
                "failure_count": failed,
                "delivery_location_label": "正式目录 / 输出 / 智能交付",
                "delivery_root": delivery_root,
                "results": results,
            }
            # Built before any registry write so an interrupted registration can still
            # settle the request with the copies that really exist.
            public_results = [
                {key: value for key, value in result.items() if not key.startswith("_")}
                for result in results
            ]
            current_result_context = None
            if len(public_results) == 1:
                item = public_results[0]
                current_result_context = {
                    "feature_key": item.get("feature_key") or "",
                    "module_id": item.get("module_id") or "",
                    "operation_id": item.get("operation_id") or "",
                    "trace_id": item.get("trace_id") or "",
                    "task_id": item.get("task_id") or "",
                    "result_id": item.get("source_result_id") or item.get("result_id") or "",
                    "delivery_id": delivery_id,
                }
            response_data = {
                "delivery_id": delivery_id,
                "idempotency_key": idempotency_key,
                "idempotent_replay": False,
                "operation_id": delivery_operation["operation_id"],
                "trace_id": delivery_operation["trace_id"],
                "delivery_operation_id": delivery_operation["operation_id"],
                "delivery_trace_id": delivery_operation["trace_id"],
                "current_result_context": current_result_context,
                "status": run["status"],
                "success_count": succeeded,
                "failure_count": failed,
                "delivery_location_label": run["delivery_location_label"],
                "results": public_results,
            }
            smart_delivery_run_registry[delivery_id] = run
            # Recent runs only: older ones are rebuilt from their persisted delivery fact.
            while len(smart_delivery_run_registry) > SMART_DELIVERY_RUN_CACHE_SIZE:
                smart_delivery_run_registry.pop(next(iter(smart_delivery_run_registry)))
            if shared_task_registry is not None:
                first_error = next(
                    (dict(item.get("_error_context") or {}) for item in results if item.get("_error_context")),
                    {},
                )
                delivery_fact = {
                    "record_kind": "delivery",
                    **delivery_operation,
                    "delivery_id": delivery_id,
                    "idempotency_key": idempotency_key,
                    "status": run["status"],
                    "processing_stage": "delivery_copy",
                    "success_count": succeeded,
                    "failure_count": failed,
                    "error_code": next(
                        (str(item.get("failure_code") or "SMART_DELIVERY_COPY_FAILED") for item in results if item.get("status") == "failed"),
                        "",
                    ),
                    "error_context": first_error,
                    "created_at": datetime.fromtimestamp(now_provider(), tz=timezone.utc).isoformat(),
                    "completed_at": datetime.fromtimestamp(now_provider(), tz=timezone.utc).isoformat(),
                    "task_context": {
                        **delivery_operation,
                        "purpose": "SMART_DELIVERY",
                        "route": "/smart-delivery",
                        "route_family": "smart_delivery",
                    },
                    "result_ids": [str(item.get("source_result_id") or "") for item in results if item.get("source_result_id")],
                    "source_task_ids": [str(item.get("task_id") or "") for item in results if item.get("task_id")],
                    "naming_items": [
                        {
                            "source_result_id": str(item.get("source_result_id") or ""),
                            "source_filename": str(item.get("source_filename") or item.get("source_file_name") or ""),
                            "suggested_filename": str(item.get("suggested_filename") or ""),
                            "final_filename": str(item.get("final_filename") or item.get("delivery_file_name") or ""),
                            "naming_source": str(item.get("naming_source") or ""),
                            "naming_evidence": list(item.get("naming_evidence") or []),
                            "delivery_id": delivery_id,
                            "delivery_item_id": str(item.get("delivery_item_id") or ""),
                            "delivery_path": str(item.get("_delivery_path") or ""),
                            "trace_id": delivery_operation["trace_id"],
                            "parent_operation_id": str(item.get("parent_operation_id") or ""),
                            "parent_trace_id": str(item.get("parent_trace_id") or ""),
                            "retry_of_delivery_id": str(item.get("retry_of_delivery_id") or ""),
                            "status": str(item.get("status") or ""),
                            "error": {
                                "code": str(item.get("failure_code") or "") if item.get("status") == "failed" else "",
                                "message": str(item.get("failure_reason") or ""),
                                "error_id": str((item.get("_error_context") or {}).get("error_id") or ""),
                            },
                        }
                        for item in results
                    ],
                }
                shared_task_registry[batch_naming_delivery_fact_key(delivery_id)] = delivery_fact
            for result in results:
                source_task_id = str(result.get("task_id") or "")
                task_record_key = source_task_id
                task_record = task_registry.get(source_task_id)
                if not isinstance(task_record, dict) and shared_task_registry is not None:
                    task_record = shared_task_registry.get(source_task_id)
                if not isinstance(task_record, dict) and shared_task_registry is not None:
                    result_reference_for_task = getattr(shared_task_registry, "result_reference_for_task", None)
                    if callable(result_reference_for_task):
                        task_record = result_reference_for_task(source_task_id)
                        task_record_key = str((task_record or {}).get("result_id") or "")
                if not isinstance(task_record, dict):
                    continue
                delivery_trace = {
                    **delivery_operation,
                    "delivery_id": delivery_id,
                    "idempotency_key": idempotency_key,
                    "delivery_item_id": result["delivery_item_id"],
                    "result_id": result.get("source_result_id") or result.get("result_id") or "",
                    "source_filename": result.get("source_filename") or result.get("source_file_name") or "",
                    "suggested_filename": result.get("suggested_filename") or "",
                    "final_filename": result.get("final_filename") or result.get("delivery_file_name") or "",
                    "naming_source": result.get("naming_source") or "",
                    "naming_evidence": list(result.get("naming_evidence") or []),
                    "delivery_file": result.get("_delivery_path") or "",
                    "delivery_path": result.get("_delivery_path") or "",
                    "content_name": result.get("content_name") or "",
                    "content_name_source": result.get("content_name_source") or "",
                    "parent_operation_id": result.get("parent_operation_id") or "",
                    "parent_trace_id": result.get("parent_trace_id") or "",
                    "retry_of_delivery_id": result.get("retry_of_delivery_id") or "",
                    "status": str(result.get("status") or ""),
                    "error": {
                        "code": str(result.get("failure_code") or "") if result.get("status") == "failed" else "",
                        "message": str(result.get("failure_reason") or ""),
                        "error_id": str((result.get("_error_context") or {}).get("error_id") or ""),
                    },
                }
                task_record["delivery_id"] = delivery_id
                task_record.setdefault("deliveries", []).append(delivery_trace)
                task_result = task_record.get("task_result")
                if isinstance(task_result, dict):
                    task_result["delivery_id"] = delivery_id
                if source_task_id in task_registry:
                    task_registry[source_task_id] = task_record
                if shared_task_registry is not None and task_record_key:
                    shared_task_registry[task_record_key] = task_record
            if any(result.get("failure_code") == RESULT_IDENTITY_MISMATCH for result in results):
                failure_detail = {
                    "code": RESULT_IDENTITY_MISMATCH,
                    "message": "实际复制字节与 Result 登记身份不一致，交付文件未发布。",
                    "delivery_id": delivery_id,
                    "idempotency_key": idempotency_key,
                    "idempotent_replay": False,
                    "status": run["status"],
                    "success_count": succeeded,
                    "failure_count": failed,
                }
                if delivery_request_record is not None:
                    persist_delivery_request({
                        **delivery_request_record,
                        "status": "FAILED_DEFINITE",
                        "http_status": 409,
                        "error_detail": failure_detail,
                        "updated_at": datetime.fromtimestamp(now_provider(), tz=timezone.utc).isoformat(),
                    })
                raise HTTPException(
                    status_code=409,
                    detail=failure_detail,
                )
            if delivery_request_record is not None:
                delivery_sha256 = next(
                    (str(result.get("delivery_sha256") or "") for result in public_results if result.get("status") == "completed"),
                    "",
                )
                persist_delivery_request({
                    **delivery_request_record,
                    "status": "COMPLETED" if failed == 0 else "FAILED_DEFINITE",
                    "delivery_sha256": delivery_sha256,
                    "http_status": 200,
                    "response_data": response_data,
                    "updated_at": datetime.fromtimestamp(now_provider(), tz=timezone.utc).isoformat(),
                })
            return {
                "code": 200,
                "status": "success",
                "success": True,
                "data": response_data,
            }
        except Exception as exc:
            if delivery_request_record is not None:
                settle_interrupted_delivery_request(delivery_request_record, results, response_data, exc)
            raise

    def run_from_delivery_fact(delivery_id: str) -> dict[str, Any] | None:
        """Rebuild an open-able run after a restart or cache eviction.

        Only paths recorded in the delivery fact are used; open_smart_delivery_target
        still requires them to sit directly in the formal smart-delivery directory.
        """
        if shared_task_registry is None or not delivery_id:
            return None
        fact = shared_task_registry.get(batch_naming_delivery_fact_key(delivery_id))
        if not isinstance(fact, Mapping) or fact.get("record_kind") != "delivery" or fact.get("delivery_id") != delivery_id:
            return None
        return {
            "delivery_id": delivery_id,
            "delivery_root": smart_delivery_root(),
            "results": [
                {
                    "result_id": str(item.get("source_result_id") or item.get("delivery_item_id") or ""),
                    "delivery_item_id": str(item.get("delivery_item_id") or ""),
                    "status": str(item.get("status") or ""),
                    "_destination_path": Path(str(item["delivery_path"])) if item.get("delivery_path") else None,
                }
                for item in list(fact.get("naming_items") or [])
                if isinstance(item, Mapping)
            ],
        }

    def require_smart_delivery_run(delivery_id: str) -> dict[str, Any]:
        run = smart_delivery_run_registry.get(str(delivery_id or "")) or run_from_delivery_fact(str(delivery_id or ""))
        if not run:
            raise HTTPException(
                status_code=404,
                detail={"code": "SMART_DELIVERY_RUN_NOT_FOUND", "message": "当前交付结果已失效。"},
            )
        return run

    def open_smart_delivery_target(delivery_id: str, result_id: str = "") -> dict[str, Any]:
        run = require_smart_delivery_run(delivery_id)
        target = Path(run["delivery_root"]).resolve()
        file_name = ""
        if result_id:
            result = next(
                (
                    item
                    for item in run["results"]
                    if item["result_id"] == result_id or item.get("delivery_item_id") == result_id
                ),
                None,
            )
            if not result or result.get("status") != "completed" or not result.get("_destination_path"):
                raise HTTPException(
                    status_code=404,
                    detail={"code": "SMART_DELIVERY_RESULT_NOT_FOUND", "message": "交付文件不存在或未成功生成。"},
                )
            target = Path(result["_destination_path"]).resolve()
            file_name = target.name
        delivery_root = smart_delivery_root()
        if target != delivery_root and target.parent != delivery_root:
            raise HTTPException(
                status_code=403,
                detail={"code": "SMART_DELIVERY_TARGET_INVALID", "message": "交付文件不在正式智能交付目录中。"},
            )
        if not target.exists():
            raise HTTPException(
                status_code=404,
                detail={"code": "SMART_DELIVERY_TARGET_MISSING", "message": "交付文件或目录已不存在。"},
            )
        try:
            if folder_opener is not None:
                folder_opener(str(target))
            elif os.name == "nt":
                os.startfile(str(target))  # noqa: S606 - server-registered formal delivery target only
            else:
                raise OSError("当前系统不支持自动打开本地文件。")
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "SMART_DELIVERY_OPEN_FAILED", "message": "打开交付结果失败。"},
            ) from exc
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "data": {"file_name": file_name, "directory_name": delivery_root.name},
        }

    @app.post("/api/smart-delivery/runs/{delivery_id}/open-folder")
    async def smart_delivery_open_folder(delivery_id: str):
        return open_smart_delivery_target(delivery_id)

    @app.post("/api/smart-delivery/runs/{delivery_id}/items/{result_id}/open")
    async def smart_delivery_open_file(delivery_id: str, result_id: str):
        return open_smart_delivery_target(delivery_id, result_id)

    @app.get("/api/image-compression/preview/{token}")
    async def image_compression_preview(token: str):
        require_compression_directory()
        item = require_token(token)
        path = Path(item["path"]).resolve()
        if item.get("role") not in {"source_preview", "output_preview"}:
            raise HTTPException(status_code=403, detail="预览令牌用途不正确。")
        return FileResponse(
            path,
            media_type=image_media_type(path),
            filename=_safe_name(item.get("filename") or path.name),
        )

    @app.get("/api/image-compression/feedback-package/{token}")
    async def image_compression_feedback_package_download(token: str):
        require_compression_directory()
        item, path = require_feedback_package_token(token)
        record = task_registry.get(str(item.get("task_id") or ""))
        package = record.get("feedback_package") if record else None
        if not record or not isinstance(package, Mapping):
            raise HTTPException(
                status_code=403,
                detail={"code": "FEEDBACK_PACKAGE_TASK_MISMATCH", "message": "测试反馈包链接与当前登记任务不一致。"},
            )
        registered_size = int(package.get("package_size_bytes") or 0)
        if registered_size <= 0 or path.stat().st_size != registered_size:
            raise HTTPException(
                status_code=409,
                detail={"code": "FEEDBACK_PACKAGE_SHA_MISMATCH", "message": "测试反馈包完整性校验失败，请重新生成。"},
            )
        archive_bytes = path.read_bytes()
        actual_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        expected_sha256 = str(package.get("package_sha256") or package.get("feedback_package_sha256") or "")
        if (
            len(archive_bytes) != registered_size
            or not zipfile.is_zipfile(io.BytesIO(archive_bytes))
            or actual_sha256 != expected_sha256
            or actual_sha256 != str(item.get("sha256") or "")
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "FEEDBACK_PACKAGE_SHA_MISMATCH", "message": "测试反馈包完整性校验失败，请重新生成。"},
            )
        filename = _safe_name(item.get("filename") or path.name)
        disposition = f"attachment; filename*=UTF-8''{quote(filename, safe='')}"
        return Response(
            content=archive_bytes,
            media_type="application/zip",
            headers={
                "Content-Disposition": disposition,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, no-store",
            },
        )

    from backend.batch_compression_api import register_batch_compression_routes

    def batch_intake(content, filename):
        intake = create_compression_intake(content, filename)
        return dict(require_token(intake["source_token"], role="source"))

    batch_preview_tokens: dict[tuple[str, str], str] = {}

    def batch_source_preview_url(source, filename):
        path = Path(str(source.get("path") or "")).resolve()
        source_sha256 = str(source.get("sha256") or "")
        cache_root = Path(require_compression_directory()["tmp_dir"]).resolve() / "compression-batches"
        if not source_sha256 or cache_root not in path.parents or not path.is_file():
            return ""
        key = (str(path), source_sha256)
        token = batch_preview_tokens.get(key, "")
        token_item = token_registry.get(token)
        if not token_item or token_item.get("expires_at", 0) <= now_provider():
            if _sha256_file(path) != source_sha256:
                return ""
            token = issue_token(path, role="source_preview", filename=filename)
            # Forget entries whose authorization has already been pruned.
            for stale_key in [k for k, v in batch_preview_tokens.items() if v not in token_registry]:
                batch_preview_tokens.pop(stale_key, None)
            batch_preview_tokens[key] = token
        return preview_url(token)

    batch_service = register_batch_compression_routes(
        app, registry=shared_task_registry, roots=require_compression_directory,
        output_directory=lambda: function_output_dir(
            DELIVERY_OPTIMIZATION_MODE, Path(effective_output_root({})["normalized_path"])),
        intake=batch_intake, execute=execute_compression, source_preview_url=batch_source_preview_url,
    )
    state = {
        "batch_service": batch_service,
        "token_registry": token_registry,
        "expired_feedback_tokens": expired_feedback_tokens,
        "task_registry": task_registry,
        "color_batch_registry": color_batch_registry,
        "color_level_preview_sessions": color_level_preview_sessions,
        "color_batch_queue": color_batch_queue,
        "output_center_index": output_center_index,
        "smart_delivery_run_registry": smart_delivery_run_registry,
        "server_session_id": server_session_id,
        "remove_task_runtime_references": remove_task_runtime_references,
    }
    app.state.image_compression_api_state = state
    return state
