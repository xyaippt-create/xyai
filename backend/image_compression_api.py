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
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote

from engine.diagnostics.feedback_context import build_feedback_context, feedback_context_preview
from engine.diagnostics.runtime_logging import build_exception_diagnostics, related_runtime_events
from engine.storage.app_data_migration import resolve_migrated_formal_output_path


ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
TOKEN_TTL_SECONDS = 60 * 60
IMAGE_COMPRESSION_API_VERSION = "hdde.image-compression-api.v1"
LONG_IMAGE_WIDTH_RISK_POLICY_VERSION = "PRODUCT_PREFLIGHT_HEURISTIC_V1"
FUNCTION_DIRECTORY_BY_MODE = {
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
SMART_DELIVERY_PLAN_TTL_SECONDS = 30 * 60
SMART_DELIVERY_TEMPLATE_TOKENS = {"prefix", "base", "suffix", "date", "seq"}
COLOR_CORRECTION_FEATURE_KEY = "color_correction"


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
    source = Path(source_name)
    stem = _readable_label(source.stem)
    operation, parameters = _operation_and_parameter_labels(request)
    operation = _readable_label(operation, limit=24)
    parameters = [_readable_label(value, limit=24) for value in parameters if value]
    short_id = _readable_label(task_id.rsplit("_", 1)[-1][-4:], limit=8)
    timestamp = datetime.fromtimestamp(now_value).strftime("%Y%m%d-%H%M%S")
    output_stem = _readable_label("_".join([stem, operation, *parameters, timestamp, short_id]), limit=160)
    suffix = output_suffix.lower() if output_suffix.lower() in {".png", ".jpg", ".jpeg"} else source.suffix.lower()
    return _safe_name(f"{output_stem}{suffix}")


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
    shared_task_registry: Mapping[str, Mapping[str, Any]] | None = None,
    output_center_user_dirs_provider: Callable[[], dict[str, Path]] | None = None,
    feedback_runtime_provider: Callable[[], Mapping[str, Any]] | None = None,
    runtime_event_logger: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Register the local Stage 4 API on the already-created FastAPI app."""

    from fastapi import Body, File, HTTPException, Request, UploadFile
    from fastapi.responses import FileResponse, Response

    from engine.image_compression.common import apply_delivery_gate, read_image_info
    from engine.image_compression.contracts import (
        RESULT_FIELD_NAMES,
        RESULT_CONTRACT_VERSION,
        TASK_CONTRACT_VERSION,
    )
    from engine.image_compression.router import process_image_compression
    from engine.image_compression.statuses import (
        OperationMode,
        TechnicalStatus,
        VisualReviewStatus,
    )
    from engine.color_correction import COLOR_CORRECTION_ENGINE_VERSION, process_single_image
    from PIL import Image

    token_registry: dict[str, dict[str, Any]] = {}
    expired_feedback_tokens: set[str] = set()
    task_registry: dict[str, dict[str, Any]] = {}
    color_batch_registry: dict[str, dict[str, Any]] = {}
    color_batch_queue: queue.Queue[str] = queue.Queue()
    color_batch_worker_lock = threading.Lock()
    color_batch_worker_state: dict[str, threading.Thread | None] = {"thread": None}
    server_session_id = uuid.uuid4().hex
    output_center_index: dict[str, dict[str, Any]] = {}
    smart_delivery_plan_registry: dict[str, dict[str, Any]] = {}
    smart_delivery_run_registry: dict[str, dict[str, Any]] = {}

    def emit_runtime_event(event: str, **fields: Any) -> None:
        if runtime_event_logger is None:
            return
        try:
            runtime_event_logger(event, **fields)
        except Exception:
            # Diagnostic logging must never alter the product path.
            return

    def prune_tokens() -> None:
        now = now_provider()
        expired = [token for token, item in token_registry.items() if item.get("expires_at", 0) <= now]
        for token in expired:
            item = token_registry.pop(token, None) or {}
            if item.get("role") == "feedback_package":
                expired_feedback_tokens.add(token)
                continue
            if item.get("role") == "source":
                path = Path(item.get("path", ""))
                try:
                    if path.exists():
                        path.unlink()
                    parent = path.parent
                    if parent.name.startswith("intake_") and parent.exists() and not any(parent.iterdir()):
                        parent.rmdir()
                except OSError:
                    pass

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

    def output_center_sources() -> list[dict[str, Any]]:
        """Return the finite set of formal directories owned by real product contracts."""

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
                "label": "1080P高清处理",
                "paths": [
                    Path(user_dirs.get("normal_output_dir") or (output_root / "1080P标准增强")).resolve(),
                    Path(user_dirs.get("safe_beta_output_dir") or (output_root / "1080P安全增强")).resolve(),
                ],
            },
            {
                "category": "4k",
                "label": "4K高清增强",
                "paths": [output_root / "4K高清增强"],
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
                "label": "标记修整",
                "paths": [output_root / "标记修整"],
            },
        ]

    def output_center_active_records(formal_root: Path) -> dict[Path, Mapping[str, Any]]:
        records: dict[Path, Mapping[str, Any]] = {}
        registries = [task_registry]
        if shared_task_registry is not None:
            registries.append(shared_task_registry)
        for registry in registries:
            for record in registry.values():
                if not isinstance(record, Mapping):
                    continue
                result = record.get("result")
                if hasattr(result, "to_dict"):
                    result = result.to_dict()
                if not isinstance(result, Mapping):
                    result = {}
                raw_path = (
                    record.get("output_path")
                    or record.get("result_file")
                    or result.get("output_path")
                    or result.get("final_output_path")
                    or result.get("result_file")
                )
                if not raw_path:
                    continue
                try:
                    path = resolve_migrated_formal_output_path(str(raw_path), formal_root)
                except (OSError, ValueError):
                    continue
                records[path] = record
        return records

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

    def output_center_record_meta(record: Mapping[str, Any] | None, formal_root: Path) -> dict[str, Any]:
        if not record:
            return {}
        result = record.get("result")
        if hasattr(result, "to_dict"):
            result = result.to_dict()
        if not isinstance(result, Mapping):
            result = {}
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
        feature_key = str(record.get("feature_key") or result.get("feature_key") or "")
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
            "feature_key": feature_key,
            "result_file": result_file,
            "batch_id": batch_id,
            "compare_url": compare_url,
            "review_status": str(record.get("review_status") or ""),
            "status": str(record.get("status") or result.get("status") or ""),
        }

    def read_output_center_image_info(path: Path) -> dict[str, Any]:
        with Image.open(path) as opened:
            opened.load()
            image_format = "JPEG" if opened.format == "JPG" else str(opened.format or "").upper()
            if image_format not in {"PNG", "JPEG"}:
                raise ValueError("unsupported output format")
            return {"width": opened.width, "height": opened.height, "format": image_format}

    def build_output_center_snapshot() -> dict[str, Any]:
        user_dirs = (output_center_user_dirs_provider or user_dirs_provider)()
        formal_root = Path(user_dirs.get("app_data_root") or ".").resolve()
        active_records = output_center_active_records(formal_root)
        output_center_index.clear()
        items: list[dict[str, Any]] = []
        skipped_unavailable = 0
        seen_paths: set[Path] = set()
        for source in output_center_sources():
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
                        if resolved in seen_paths or resolved.stat().st_size <= 0:
                            continue
                        info = read_output_center_image_info(resolved)
                        stat = resolved.stat()
                    except Exception:
                        skipped_unavailable += 1
                        continue
                    seen_paths.add(resolved)
                    record_meta = output_center_record_meta(active_records.get(resolved), formal_root)
                    source_path = record_meta.get("source_path")
                    compare_url = str(record_meta.get("compare_url") or "")
                    mapping_source = "task_registry" if source_path else ""
                    if source["category"] == "color_correction" and source_path is None:
                        source_path = find_managed_color_source(resolved, user_dirs)
                        if source_path is not None:
                            mapping_source = "unique_managed_intake_match"
                    item_id = hashlib.sha256(f"{source['category']}|{resolved}".encode("utf-8")).hexdigest()[:24]
                    unified_result = bool(
                        record_meta.get("result_id")
                        and record_meta.get("task_id")
                        and record_meta.get("feature_key")
                        and source_path
                        and record_meta.get("result_file") == resolved
                    )
                    output_center_index[item_id] = {
                        "output_path": resolved,
                        "source_path": source_path,
                        "category": source["category"],
                        "result_id": record_meta.get("result_id") or "",
                        "task_id": record_meta.get("task_id") or "",
                        "feature_key": record_meta.get("feature_key") or "",
                        "unified_result": unified_result,
                    }
                    items.append({
                        "id": item_id,
                        "file_name": resolved.name,
                        "processing_type": source["category"],
                        "processing_label": source["label"],
                        "result_id": record_meta.get("result_id") or "",
                        "task_id": record_meta.get("task_id") or "",
                        "feature_key": record_meta.get("feature_key") or "",
                        "unified_result": unified_result,
                        "delivery_eligible": (
                            unified_result
                            or source["category"] != "local_retouch"
                            or bool(record_meta.get("result_id") and mapping_source == "task_registry")
                        ),
                        "status": record_meta.get("status") or "completed",
                        "width": int(info["width"]),
                        "height": int(info["height"]),
                        "format": str(info.get("format") or resolved.suffix.lstrip(".")).upper(),
                        "size_bytes": int(stat.st_size),
                        "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                        "preview_url": f"/api/output-center/items/{item_id}/preview",
                        "source_preview_url": f"/api/output-center/items/{item_id}/source-preview" if source_path else "",
                        "compare_available": bool(source_path),
                        "compare_url": compare_url or (f"/outputs/compare?item={item_id}" if source_path else ""),
                        "mapping_source": mapping_source,
                        "review_status": record_meta.get("review_status") or "",
                        "available": True,
                    })
        items.sort(key=lambda item: item["created_at"], reverse=True)
        categories = [
            {"key": source["category"], "label": source["label"], "count": sum(1 for item in items if item["processing_type"] == source["category"])}
            for source in output_center_sources()
        ]
        categories = [item for item in categories if item["count"] > 0]
        return {
            "items": items,
            "categories": [{"key": "all", "label": "全部", "count": len(items)}, *categories],
            "count": len(items),
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

        def text_value(name: str, default: str = "") -> str:
            value = str(source.get(name, default) or "").strip()
            return value[:512]

        try:
            sequence_start = int(source.get("sequence_start", 1))
            sequence_padding = int(source.get("sequence_padding", 2))
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "SMART_DELIVERY_RULE_INVALID", "message": "连续编号必须使用有效数字。"},
            ) from exc
        if sequence_start < 0 or sequence_start > 999999:
            raise HTTPException(
                status_code=400,
                detail={"code": "SMART_DELIVERY_RULE_INVALID", "message": "连续编号起始值超出允许范围。"},
            )
        if sequence_padding < 1 or sequence_padding > 6:
            raise HTTPException(
                status_code=400,
                detail={"code": "SMART_DELIVERY_RULE_INVALID", "message": "连续编号位数必须为1到6。"},
            )
        base_mode = text_value("base_mode", "original")
        if base_mode not in {"original", "custom"}:
            raise HTTPException(
                status_code=400,
                detail={"code": "SMART_DELIVERY_RULE_INVALID", "message": "基础名称模式无效。"},
            )
        return {
            "base_mode": base_mode,
            "base_name": text_value("base_name"),
            "prefix": text_value("prefix"),
            "suffix": text_value("suffix"),
            "find_text": text_value("find_text"),
            "replace_text": text_value("replace_text"),
            "sequence_enabled": source.get("sequence_enabled") is not False,
            "sequence_start": sequence_start,
            "sequence_padding": sequence_padding,
            "date_enabled": source.get("date_enabled") is not False,
            "template": text_value("template", "{prefix}{base}{suffix}_{date}_{seq}"),
        }

    def smart_delivery_name_issues(stem: str, suffix: str) -> list[tuple[str, str]]:
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
        snapshot_by_id = {item["id"]: item for item in snapshot["items"]}
        snapshot_by_result_id = {
            item["result_id"]: item
            for item in snapshot["items"]
            if item.get("unified_result") and item.get("result_id")
        }
        if result_mode:
            selected_items = []
            for result_id in selection_ids:
                public_item = snapshot_by_result_id.get(result_id)
                if public_item is None:
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

        unknown_tokens = {
            token
            for token in re.findall(r"\{([^{}]+)\}", rules["template"])
            if token not in SMART_DELIVERY_TEMPLATE_TOKENS
        }
        template_remainder = re.sub(r"\{(?:prefix|base|suffix|date|seq)\}", "", rules["template"])
        if unknown_tokens or "{" in template_remainder or "}" in template_remainder:
            issues.append({
                "code": "TEMPLATE_INVALID",
                "item_id": "",
                "file_name": "",
                "message": "组合模板只能使用 {prefix}、{base}、{suffix}、{date}、{seq}。",
            })
        if not rules["template"]:
            issues.append({
                "code": "TEMPLATE_EMPTY",
                "item_id": "",
                "file_name": "",
                "message": "组合模板不能为空。",
            })
        if rules["base_mode"] == "custom" and not rules["base_name"]:
            issues.append({
                "code": "CUSTOM_BASE_EMPTY",
                "item_id": "",
                "file_name": "",
                "message": "使用自定义基础名称时，名称不能为空。",
            })

        date_text = datetime.fromtimestamp(now_provider()).strftime("%Y%m%d") if rules["date_enabled"] else ""
        for index, item_id in enumerate(item_ids):
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
            source_processing_type = str(public_item.get("processing_type") or "")
            source_mapping = str(public_item.get("mapping_source") or "")
            if source_processing_type == "local_retouch" and (
                not source_result_id
                or source_mapping != "task_registry"
                or (result_mode and not public_item.get("unified_result"))
            ):
                issues.append({
                    "code": "UNIFIED_RESULT_REQUIRED",
                    "item_id": item_id,
                    "file_name": str(public_item.get("file_name") or ""),
                    "message": "标记修整成品缺少完整的统一正式结果引用，不能进入智能交付。",
                })
            indexed = require_output_center_item(item_id)
            source_path = Path(indexed["output_path"]).resolve()
            source_stat = source_path.stat()
            base = source_path.stem if rules["base_mode"] == "original" else rules["base_name"]
            if rules["find_text"]:
                base = base.replace(rules["find_text"], rules["replace_text"])
            sequence_text = ""
            if rules["sequence_enabled"]:
                sequence_text = str(rules["sequence_start"] + index).zfill(rules["sequence_padding"])
            values = {
                "prefix": rules["prefix"],
                "base": base,
                "suffix": rules["suffix"],
                "date": date_text,
                "seq": sequence_text,
            }
            stem = rules["template"]
            for token, value in values.items():
                stem = stem.replace(f"{{{token}}}", value)
            destination_name = f"{stem}{source_path.suffix}"
            for code, message in smart_delivery_name_issues(stem, source_path.suffix):
                issues.append({"code": code, "item_id": item_id, "file_name": destination_name, "message": message})
            name_key = destination_name.casefold()
            if name_key in seen_names:
                issues.append({
                    "code": "DUPLICATE_FINAL_NAME",
                    "item_id": item_id,
                    "file_name": destination_name,
                    "message": "批次内存在重复的最终交付文件名。",
                })
            else:
                seen_names[name_key] = item_id
            destination_path = (delivery_root / destination_name).resolve()
            if destination_path.parent != delivery_root:
                issues.append({
                    "code": "DELIVERY_PATH_ESCAPE",
                    "item_id": item_id,
                    "file_name": destination_name,
                    "message": "最终交付文件名超出安全目录边界。",
                })
            elif destination_path.exists():
                issues.append({
                    "code": "TARGET_ALREADY_EXISTS",
                    "item_id": item_id,
                    "file_name": destination_name,
                    "message": "正式交付目录中已存在同名文件，不会覆盖。",
                })
            entries.append({
                "item_id": item_id,
                "source_result_id": source_result_id,
                "source_task_id": source_task_id,
                "source_feature_key": source_feature_key,
                "source_processing_type": source_processing_type,
                "source_file_name": source_path.name,
                "delivery_file_name": destination_name,
                "processing_label": public_item["processing_label"],
                "preview_url": public_item["preview_url"],
                "_source_path": source_path,
                "_destination_path": destination_path,
                "_source_size": int(source_stat.st_size),
                "_source_mtime_ns": int(source_stat.st_mtime_ns),
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
                    "source_processing_type": entry["source_processing_type"],
                    "source_file_name": entry["source_file_name"],
                    "delivery_file_name": entry["delivery_file_name"],
                    "processing_label": entry["processing_label"],
                    "preview_url": entry["preview_url"],
                }
                for entry in plan["entries"]
            ],
        }

    def copy_delivery_item(source_path: Path, destination_path: Path) -> dict[str, Any]:
        source_hash_before = _sha256_file(source_path)
        try:
            with source_path.open("rb") as source_file, destination_path.open("xb") as destination_file:
                shutil.copyfileobj(source_file, destination_file, length=1024 * 1024)
                destination_file.flush()
                os.fsync(destination_file.fileno())
            delivery_hash = _sha256_file(destination_path)
            source_hash_after = _sha256_file(source_path)
            if source_hash_before != source_hash_after or delivery_hash != source_hash_before:
                raise OSError("交付副本完整性验证失败。")
            return {
                "source_sha256": source_hash_after,
                "delivery_sha256": delivery_hash,
                "source_unchanged": True,
                "size_bytes": destination_path.stat().st_size,
            }
        except Exception:
            try:
                if destination_path.exists():
                    destination_path.unlink()
            except OSError:
                pass
            raise

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
        output_path = Path(result.output_path) if result.output_path else None
        if not result.output_created or output_path is None or not output_path.is_file():
            return function_dir, output_path
        output_name = readable_output_name(str(source.get("filename") or output_path.name), output_path.suffix, request, task_id, now_value)
        final_path = function_dir / output_name
        if final_path.exists():
            index = 1
            while True:
                alternative = final_path.with_name(f"{final_path.stem}_{index}{final_path.suffix}")
                if not alternative.exists():
                    final_path = alternative
                    break
                index += 1
        output_path.replace(final_path)
        result.output_path = str(final_path)
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
        return {
            "task_id": task_id,
            "feature_key": COLOR_CORRECTION_FEATURE_KEY,
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
        record["failure_reason"] = failure_reason if status == "failed" else None
        record["completed_at"] = recorded_at if status in {"completed", "failed"} else None
        record.setdefault("lifecycle", []).append({
            "task_id": record["task_id"],
            "status": status,
            "progress": progress,
            "recorded_at": recorded_at,
        })

    def public_task(record: Mapping[str, Any]) -> dict[str, Any]:
        output_path = record.get("output_path")
        return {
            "task_id": record["task_id"],
            "feature_key": record.get("feature_key") or "",
            "result_id": record.get("result_id") or "",
            "delivery_id": record.get("delivery_id") or "",
            "task_family": record.get("task_family") or "",
            "result_file": str(record.get("result_file") or ""),
            "operation_mode": record["operation_mode"],
            "source_path": str(record["source_path"]),
            "status": record["status"],
            "progress": record["progress"],
            "output_path": str(output_path) if output_path else None,
            "failure_reason": record.get("failure_reason"),
            "created_at": record["created_at"],
            "completed_at": record.get("completed_at"),
            "lifecycle": [dict(item) for item in record.get("lifecycle", [])],
            "batch_id": record.get("batch_id"),
            "batch_index": record.get("batch_index"),
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
        stem = source_name.stem[:80].strip(" ._") or "图片"
        stamp = datetime.fromtimestamp(now_value).strftime("%Y%m%d_%H%M%S")
        return f"{stem}_影界自动校正_{stamp}{suffix}"

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

    def public_color_result(record: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(record.get("result") or {})
        output_path = Path(record["output_path"]) if record.get("output_path") else None
        source_preview = preview_url(record.get("source_preview_token"))
        output_preview = preview_url(record.get("output_preview_token")) if output_path and output_path.is_file() else None
        return {
            "task": public_task(record),
            "result": result or None,
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
            },
        }

    def create_color_task_record(
        source: Mapping[str, Any],
        output_root: Mapping[str, Any],
        *,
        batch_id: str | None = None,
        batch_index: int | None = None,
    ) -> dict[str, Any]:
        effective_root = Path(str(output_root["normalized_path"])).resolve()
        output_dir = color_output_dir(effective_root)
        task_created_at = now_provider()
        task_id = f"color_{uuid.uuid4().hex[:16]}"
        output_path = unique_output_path(
            output_dir,
            color_output_name(str(source.get("filename") or "图片.png"), task_created_at),
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
            "result": None,
            "result_id": "",
            "result_file": "",
            "feedback_report": None,
            "feedback_report_token": None,
            "result_review_status": "not_available",
            "result_reviewed_at": None,
        }
        record["task_context"] = frozen_color_task_context(task_id, source, batch_id=batch_id)
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
            result = process_single_image(source_path, output_path)
            if _sha256_file(source_path) != source_sha_before or result.source_sha256 != source_sha_before:
                raise RuntimeError("原图完整性校验失败，任务已阻断。")
            if result.output_sha256 == source_sha_before:
                raise RuntimeError("颜色校正输出验证失败：未检测到真实像素处理。")
            if not output_path.is_file() or output_path.stat().st_size <= 0:
                raise RuntimeError("颜色校正输出验证失败：输出文件不存在或为空。")
            verified = read_image_info(output_path)
            expected_suffix = ".png" if result.output_format == "PNG" else ".jpg"
            if (
                verified["format"] != result.output_format
                or verified["dimensions"] != {"width": result.width, "height": result.height}
                or verified["sha256"] != result.output_sha256
                or output_path.suffix.lower() != expected_suffix
            ):
                raise RuntimeError("颜色校正输出验证失败：格式、尺寸或文件摘要不一致。")
            result_data = result.to_dict()
            result_id = f"color_result_{uuid.uuid4().hex[:16]}"
            result_data.update({
                "result_id": result_id,
                "task_id": record["task_id"],
                "feature_key": record["feature_key"],
                "source": str(record["source_path"]),
                "source_path": str(record["source_path"]),
                "result_file": str(output_path),
                "output_path": str(output_path),
            })
            result_data["improvements"] = [
                *result_data.get("improvements", []),
                "原图哈希保持不变，未覆盖或修改原图",
                "输出已完成存在、解码、尺寸、格式与摘要验证",
            ]
            record.update({
                "result": result_data,
                "task_result": result_data,
                "result_id": result_id,
                "result_file": str(output_path),
                "output_path": output_path,
                "output_preview_token": preview_token_for(output_path, role="output_preview"),
                "result_review_status": "pending",
                "result_reviewed_at": None,
            })
            transition_task(record, "completed", 100)
            emit_runtime_event(
                "PROCESS_SUCCEEDED",
                stage="output_verification",
                result="success",
                impact="verified_output_available",
                **color_task_event_fields(record),
            )
            emit_runtime_event(
                "RESULT_REGISTERED",
                stage="result_registry",
                result="success",
                impact="formal_result_available",
                **color_task_event_fields(record),
            )
            emit_runtime_event(
                "COLOR_CORRECTION_TASK_SUCCEEDED",
                stage="output_verification",
                result="success",
                status="completed",
                impact="verified_output_available",
                action="review_or_deliver_output",
                **color_task_event_fields(record),
            )
        except Exception as exc:
            failed_stage = str(getattr(exc, "stage", "color_correction_execution"))
            error_category = "ENVIRONMENT_ERROR" if isinstance(exc, OSError) else "PRODUCT_ERROR"
            diagnostics = build_exception_diagnostics(
                exc,
                error_category=error_category,
                error_stage=failed_stage,
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
                **color_task_event_fields(record),
                **diagnostics,
            )
            emit_runtime_event(
                "PROCESS_FAILED",
                level=logging.ERROR,
                stage=failed_stage,
                result="failed",
                status="failed",
                impact="formal_result_unavailable",
                **color_task_event_fields(record),
                **diagnostics,
            )
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            record["output_path"] = None
            record["result"] = None
            record["output_preview_token"] = None
            if record.get("status") == "processing":
                transition_task(record, "failed", record["progress"], failure_reason=str(exc) or exc.__class__.__name__)

    def refresh_color_batch(batch: dict[str, Any]) -> None:
        items = [task_registry[task_id] for task_id in batch["task_ids"]]
        completed_count = sum(item.get("status") == "completed" for item in items)
        failed_count = sum(item.get("status") == "failed" for item in items)
        finished_count = completed_count + failed_count
        batch["completed_count"] = completed_count
        batch["failed_count"] = failed_count
        batch["progress"] = round((finished_count / max(1, batch["total_count"])) * 100)
        batch["current_task_id"] = next((item["task_id"] for item in items if item.get("status") == "processing"), None)

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
        emit_runtime_event(
            "COLOR_BATCH_STARTED",
            stage="batch_execution",
            result="started",
            feature_key=COLOR_CORRECTION_FEATURE_KEY,
            feature=COLOR_CORRECTION_FEATURE_KEY,
            operation="AUTO_COLOR_CORRECTION",
            batch_id=batch_id,
            status="processing",
            total_count=batch["total_count"],
            impact="batch_processing_running",
            action="process_queue_sequentially",
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
        emit_runtime_event(
            "COLOR_BATCH_COMPLETED",
            level=logging.INFO if batch["completed_count"] else logging.ERROR,
            stage="batch_completion",
            result="success" if batch["completed_count"] else "failed",
            error_category="" if batch["completed_count"] else "PRODUCT_ERROR",
            feature_key=COLOR_CORRECTION_FEATURE_KEY,
            feature=COLOR_CORRECTION_FEATURE_KEY,
            operation="AUTO_COLOR_CORRECTION",
            batch_id=batch_id,
            status=batch["status"],
            total_count=batch["total_count"],
            completed_count=batch["completed_count"],
            failed_count=batch["failed_count"],
            impact="batch_results_available" if batch["completed_count"] else "batch_output_unavailable",
            action="review_completed_items" if batch["completed_count"] else "check_task_failures_in_runtime_log",
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
                )
                emit_runtime_event(
                    "COLOR_BATCH_FAILED",
                    level=logging.ERROR,
                    stage="batch_worker",
                    result="failed",
                    feature_key=COLOR_CORRECTION_FEATURE_KEY,
                    feature=COLOR_CORRECTION_FEATURE_KEY,
                    operation="AUTO_COLOR_CORRECTION",
                    batch_id=batch_id,
                    status=str(batch.get("status") or "failed"),
                    total_count=batch.get("total_count"),
                    completed_count=batch.get("completed_count"),
                    failed_count=batch.get("failed_count"),
                    impact="batch_worker_stopped",
                    action="check_runtime_log_and_restart_backend",
                    **diagnostics,
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

    @app.post("/api/image-compression/intake")
    async def image_compression_intake(file: UploadFile = File(...)):
        user_dirs = require_compression_directory()
        prune_tokens()
        raw_filename = str(file.filename or "")
        if not raw_filename or raw_filename != Path(raw_filename).name or "/" in raw_filename or "\\" in raw_filename:
            raise HTTPException(status_code=400, detail="文件名不得包含目录或路径穿越片段。")
        filename = _safe_name(raw_filename)
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=415, detail="仅支持 PNG、JPG、JPEG 文件。")
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="文件超过本地安全接收上限 50 MB。")
        intake_root = Path(user_dirs["tmp_dir"]).resolve() / "image-compression-intake"
        task_dir = intake_root / f"intake_{uuid.uuid4().hex}"
        task_dir.mkdir(parents=True, exist_ok=True)
        stored = task_dir / filename
        try:
            stored.write_bytes(content)
            info = read_image_info(stored)
        except Exception as exc:
            shutil.rmtree(task_dir, ignore_errors=True)
            code = getattr(exc, "failure_code", None) or "SOURCE_DECODE_FAILED"
            raise HTTPException(status_code=400, detail=error_result("图片无法通过完整解码校验。", code=code)) from exc
        expected_format = "PNG" if suffix == ".png" else "JPEG"
        if info["format"] != expected_format:
            shutil.rmtree(task_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=error_result("文件扩展名与图片实际格式不一致。", code="SOURCE_EXTENSION_MAGIC_MISMATCH"))
        oriented_width, oriented_height = dimensions_after_exif_orientation(
            info["dimensions"]["width"],
            info["dimensions"]["height"],
            info.get("exif_orientation"),
        )
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
        }
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
        if mode not in {item.value for item in OperationMode}:
            raise HTTPException(status_code=400, detail="不支持的压缩能力模式。")

        allowed_params = {
            OperationMode.LOSSLESS_COMPRESSION.value: set(),
            OperationMode.RESIZE_REDUCTION.value: {"target_short_side", "scale_ratio", "target_width", "target_height"},
            OperationMode.UPLOAD_ADAPTATION.value: {"max_width", "max_height", "max_file_size_bytes"},
        }[mode]
        unknown_params = sorted(str(key) for key in params if key not in allowed_params)
        if unknown_params:
            raise HTTPException(status_code=400, detail=f"当前模式包含未知参数：{', '.join(unknown_params)}。")

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
            "preserve_format": True,
            "quality_policy": "LOSSLESS_ONLY" if mode == OperationMode.LOSSLESS_COMPRESSION.value else ("SAME_FORMAT_HIGH_QUALITY" if mode == OperationMode.RESIZE_REDUCTION.value else "UPLOAD_ADAPTATION_V1"),
            "metadata_policy": "PRESERVE_SUPPORTED_STRICT",
            "overwrite_policy": "FAIL_IF_EXISTS",
            "output_naming_policy": "TASK_ID_SUFFIX",
            "visual_review_policy": "STRICT_LOSSLESS_EVIDENCE" if mode == OperationMode.LOSSLESS_COMPRESSION.value else "VALIDATION_STRICT",
            "request_context": {"surface": "compression_ui", "api_version": IMAGE_COMPRESSION_API_VERSION},
            "client_context": payload.get("client_context") if isinstance(payload.get("client_context"), Mapping) else None,
            "run_id": payload.get("run_id") if isinstance(payload.get("run_id"), str) else None,
            "test_case_id": payload.get("test_case_id") if isinstance(payload.get("test_case_id"), str) else None,
            "diagnostic_session_id": payload.get("diagnostic_session_id") if isinstance(payload.get("diagnostic_session_id"), str) else None,
            "issue_report_id": payload.get("issue_report_id") if isinstance(payload.get("issue_report_id"), str) else None,
            "expected_status": payload.get("expected_status") if isinstance(payload.get("expected_status"), str) else None,
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
        user_dirs = require_compression_directory()
        token = str(payload.get("source_token") or "")
        source = require_token(token, role="source")
        product_preflight(payload, source)
        task_id = f"compression_{uuid.uuid4().hex[:16]}"
        task_created_at = now_provider()
        preflight_output = Path(user_dirs["tmp_dir"]).resolve() / "image-compression-preflight"
        request = build_task_request(payload, source, task_id, preflight_output)
        output_root = effective_output_root(payload)
        effective_root = Path(output_root["normalized_path"])
        output_dir = function_output_dir(str(request["operation_mode"]), effective_root)
        request["output_directory"] = str(output_dir)
        source_preview = preview_token_for(Path(source["path"]), role="source_preview")
        record = {
            "task_id": task_id,
            "feature_key": "image_compression",
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
            "long_image_validation": None,
            "resize_validation": None,
            "feedback_package": None,
            "feedback_package_token": None,
            "feedback_artifact_stem": None,
        }
        task_registry[task_id] = record
        if shared_task_registry is not None:
            shared_task_registry[task_id] = record
        transition_task(record, "pending", 0)
        emit_runtime_event(
            "TASK_CREATED",
            stage="task_registration",
            result="success",
            feature_key="image_compression",
            task_id=task_id,
            status="pending",
            impact="unified_task_available",
        )
        try:
            transition_task(record, "processing", 10)
            emit_runtime_event(
                "PROCESS_STARTED",
                stage="engine_adapter",
                result="started",
                feature_key="image_compression",
                task_id=task_id,
                status="processing",
                impact="image_compression_running",
            )
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
                verified = read_image_info(output_path)
                expected_dimensions = result.output_dimensions or {}
                if (
                    verified["format"] != result.output_format
                    or verified["dimensions"] != expected_dimensions
                ):
                    raise RuntimeError("压缩输出验证失败：输出格式或尺寸与任务结果不一致。")

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
                ).stem,
            })
            if result.output_created and output_path:
                result_id = f"compression_result_{uuid.uuid4().hex[:16]}"
                task_result = {
                    "result_id": result_id,
                    "task_id": task_id,
                    "feature_key": "image_compression",
                    "source": str(record["source_path"]),
                    "source_path": str(record["source_path"]),
                    "result_file": str(output_path),
                    "output_path": str(output_path),
                    "status": "completed",
                }
                record.update({
                    "result_id": result_id,
                    "result_file": str(output_path),
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
                    feature_key="image_compression",
                    task_id=task_id,
                    status="failed",
                    reason=record.get("failure_reason") or "processing_failed",
                    impact="formal_result_unavailable",
                )
            else:
                transition_task(record, "completed", 100)
                emit_runtime_event(
                    "PROCESS_SUCCEEDED",
                    stage="output_verification",
                    result="success",
                    feature_key="image_compression",
                    task_id=task_id,
                    result_id=record.get("result_id") or "",
                    status="completed",
                    impact="verified_output_available" if record.get("result_id") else "no_output_required",
                )
                if record.get("result_id"):
                    emit_runtime_event(
                        "RESULT_REGISTERED",
                        stage="result_registry",
                        result="success",
                        feature_key="image_compression",
                        task_id=task_id,
                        result_id=record["result_id"],
                        status="completed",
                        impact="formal_result_available",
                    )
        except Exception as exc:
            if record.get("status") == "processing":
                transition_task(record, "failed", record["progress"], failure_reason=str(exc) or exc.__class__.__name__)
            emit_runtime_event(
                "PROCESS_FAILED",
                level=logging.ERROR,
                stage="engine_adapter",
                result="failed",
                feature_key="image_compression",
                task_id=task_id,
                status="failed",
                reason=str(exc) or exc.__class__.__name__,
                impact="formal_result_unavailable",
            )
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
                "engine_version": COLOR_CORRECTION_ENGINE_VERSION,
                "server_session_id": server_session_id,
                "operation_mode": "AUTO_COLOR_CORRECTION",
                "supported_formats": ["PNG", "JPEG"],
                "max_upload_bytes": MAX_UPLOAD_BYTES,
                "content_generation": False,
                "manual_adjustments": False,
                "batch_available": True,
                "max_batch_size": 20,
                "queue_mode": "local_sequential",
            },
        }

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
        return {"code": 200, "status": "success", "success": True, "data": public_color_result(record)}

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
        records = [
            create_color_task_record(source, output_root, batch_id=batch_id, batch_index=index)
            for index, source in enumerate(sources, start=1)
        ]
        batch = {
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
        }
        color_batch_registry[batch_id] = batch
        emit_runtime_event(
            "COLOR_BATCH_QUEUED",
            stage="batch_queue",
            result="queued",
            feature_key=COLOR_CORRECTION_FEATURE_KEY,
            feature=COLOR_CORRECTION_FEATURE_KEY,
            operation="AUTO_COLOR_CORRECTION",
            batch_id=batch_id,
            status="pending",
            total_count=batch["total_count"],
            impact="batch_waiting_for_local_worker",
            action="process_queue_sequentially",
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
        record = task_registry.get(str(task_id or ""))
        if not record or record.get("task_family") != "color_correction":
            raise HTTPException(status_code=404, detail={"code": "COLOR_CORRECTION_TASK_NOT_FOUND", "message": "颜色校正任务不存在。"})
        return {"code": 200, "status": "success", "success": True, "data": public_color_result(record)}

    @app.post("/api/color-correction/tasks/{task_id}/review")
    async def color_correction_task_review(task_id: str, payload: dict = Body(default_factory=dict)):
        require_compression_directory()
        if set(payload) != {"status"}:
            raise HTTPException(status_code=400, detail={"code": "COLOR_REVIEW_REQUEST_INVALID", "message": "人工确认请求只能包含status字段。"})
        record = task_registry.get(str(task_id or ""))
        if not record or record.get("task_family") != "color_correction":
            raise HTTPException(status_code=404, detail={"code": "COLOR_CORRECTION_TASK_NOT_FOUND", "message": "颜色校正任务不存在。"})
        review_status = str(payload.get("status") or "").strip().lower()
        if review_status not in {"pending", "confirmed"}:
            raise HTTPException(status_code=400, detail={"code": "COLOR_REVIEW_STATUS_INVALID", "message": "人工确认状态必须为pending或confirmed。"})
        output_path = Path(record["output_path"]).resolve() if record.get("output_path") else None
        result = dict(record.get("result") or {})
        if record.get("status") != "completed" or not output_path or not output_path.is_file():
            raise HTTPException(status_code=409, detail={"code": "COLOR_REVIEW_RESULT_UNAVAILABLE", "message": "当前任务没有可供人工确认的真实结果。"})
        if not result.get("output_sha256") or _sha256_file(output_path) != result["output_sha256"]:
            raise HTTPException(status_code=409, detail={"code": "COLOR_REVIEW_RESULT_CHANGED", "message": "当前结果文件与任务记录不一致，不能写入人工确认状态。"})
        record["result_review_status"] = review_status
        record["result_reviewed_at"] = lifecycle_timestamp() if review_status == "confirmed" else None
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
            task_id=task_id,
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
                "color_correction_engine_version": COLOR_CORRECTION_ENGINE_VERSION,
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
            )
            emit_runtime_event(
                "FEEDBACK_REPORT_GENERATION_FAILED",
                level=logging.ERROR,
                stage="feedback_report_write",
                result="failed",
                status=record.get("status") or "",
                impact="feedback_report_unavailable",
                action="check_runtime_log_and_output_directory",
                **color_task_event_fields(record),
                **diagnostics,
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
            )
            emit_runtime_event(
                "FEEDBACK_REPORT_GENERATION_FAILED",
                level=logging.ERROR,
                stage="feedback_report_registration",
                result="failed",
                status=record.get("status") or "",
                impact="feedback_report_download_unavailable",
                action="check_runtime_log_and_report_registry",
                **color_task_event_fields(record),
                **diagnostics,
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
        record = task_registry.get(str(task_id or ""))
        if not record or record.get("task_family") != "color_correction":
            raise HTTPException(status_code=404, detail={"code": "COLOR_CORRECTION_TASK_NOT_FOUND", "message": "颜色校正任务不存在。"})
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
        return item

    @app.get("/api/output-center/items")
    async def output_center_items():
        snapshot = build_output_center_snapshot()
        return {"code": 200, "status": "success", "success": True, "data": snapshot}

    @app.get("/api/output-center/items/{item_id}/preview")
    async def output_center_preview(item_id: str):
        item = require_output_center_item(item_id)
        path = Path(item["output_path"]).resolve()
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type, filename=_safe_name(path.name))

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
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type, filename=_safe_name(path.name))

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

    @app.post("/api/smart-delivery/execute")
    async def smart_delivery_execute(payload: dict = Body(default_factory=dict)):
        prune_smart_delivery_plans()
        plan_id = str(payload.get("plan_id") or "")
        plan = smart_delivery_plan_registry.get(plan_id)
        if not plan:
            raise HTTPException(
                status_code=404,
                detail={"code": "SMART_DELIVERY_PLAN_EXPIRED", "message": "交付预检已失效，请重新检查名称。"},
            )
        if payload.get("confirmed") is not True:
            raise HTTPException(
                status_code=400,
                detail={"code": "SMART_DELIVERY_CONFIRMATION_REQUIRED", "message": "生成交付副本前必须完成用户确认。"},
            )
        refreshed = build_smart_delivery_plan(
            plan["item_ids"] if plan["selection_mode"] == "item_ids" else None,
            plan["result_ids"] if plan["selection_mode"] == "result_ids" else None,
            plan["rules"],
            store=False,
        )
        if not refreshed["ready"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "SMART_DELIVERY_PREFLIGHT_BLOCKED",
                    "message": "交付条件已变化，请处理阻断项后重新确认。",
                    "preflight": public_smart_delivery_plan(refreshed),
                },
            )
        if refreshed["signature"] != plan["signature"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "SMART_DELIVERY_PREVIEW_CHANGED",
                    "message": "源成品或名称预览已经变化，请重新确认。",
                    "preflight": public_smart_delivery_plan(refreshed),
                },
            )

        delivery_id = f"delivery_{datetime.fromtimestamp(now_provider()).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        delivery_root = smart_delivery_root()
        try:
            delivery_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            emit_runtime_event(
                "DELIVERY_FAILED",
                level=logging.ERROR,
                stage="delivery_directory",
                result="failed",
                feature_key="smart_delivery",
                delivery_id=delivery_id,
                reason=str(exc) or exc.__class__.__name__,
                impact="delivery_copy_unavailable",
            )
            raise HTTPException(
                status_code=400,
                detail={"code": "SMART_DELIVERY_DIRECTORY_UNAVAILABLE", "message": "正式智能交付目录不可用。"},
            ) from exc

        results: list[dict[str, Any]] = []
        for entry in refreshed["entries"]:
            delivery_item_id = uuid.uuid4().hex[:16]
            result_id = entry["source_result_id"] or delivery_item_id
            source_path = Path(entry["_source_path"]).resolve()
            destination_path = Path(entry["_destination_path"]).resolve()
            emit_runtime_event(
                "DELIVERY_STARTED",
                stage="delivery_copy",
                result="started",
                feature_key=entry["source_feature_key"] or "smart_delivery",
                task_id=entry["source_task_id"],
                result_id=entry["source_result_id"],
                delivery_id=delivery_id,
                impact="delivery_copy_running",
            )
            try:
                if source_path.stat().st_size != entry["_source_size"] or source_path.stat().st_mtime_ns != entry["_source_mtime_ns"]:
                    raise OSError("源成品在确认后发生变化。")
                copied = copy_delivery_item(source_path, destination_path)
                results.append({
                    "result_id": result_id,
                    "delivery_item_id": delivery_item_id,
                    "delivery_id": delivery_id,
                    "item_id": entry["item_id"],
                    "source_result_id": entry["source_result_id"],
                    "task_id": entry["source_task_id"],
                    "feature_key": entry["source_feature_key"],
                    "source_processing_type": entry["source_processing_type"],
                    "source_file_name": entry["source_file_name"],
                    "delivery_file_name": entry["delivery_file_name"],
                    "status": "completed",
                    "failure_reason": "",
                    **copied,
                    "_destination_path": destination_path,
                })
                emit_runtime_event(
                    "DELIVERY_SUCCEEDED",
                    stage="delivery_copy",
                    result="success",
                    feature_key=entry["source_feature_key"] or "smart_delivery",
                    task_id=entry["source_task_id"],
                    result_id=entry["source_result_id"],
                    delivery_id=delivery_id,
                    impact="delivery_copy_available",
                )
            except Exception as exc:
                results.append({
                    "result_id": result_id,
                    "delivery_item_id": delivery_item_id,
                    "delivery_id": delivery_id,
                    "item_id": entry["item_id"],
                    "source_result_id": entry["source_result_id"],
                    "task_id": entry["source_task_id"],
                    "feature_key": entry["source_feature_key"],
                    "source_processing_type": entry["source_processing_type"],
                    "source_file_name": entry["source_file_name"],
                    "delivery_file_name": entry["delivery_file_name"],
                    "status": "failed",
                    "failure_reason": str(exc) or "生成交付副本失败。",
                    "source_sha256": "",
                    "delivery_sha256": "",
                    "source_unchanged": False,
                    "size_bytes": 0,
                    "_destination_path": None,
                })
                emit_runtime_event(
                    "DELIVERY_FAILED",
                    level=logging.ERROR,
                    stage="delivery_copy",
                    result="failed",
                    feature_key=entry["source_feature_key"] or "smart_delivery",
                    task_id=entry["source_task_id"],
                    result_id=entry["source_result_id"],
                    delivery_id=delivery_id,
                    reason=str(exc) or exc.__class__.__name__,
                    impact="delivery_copy_unavailable",
                )

        succeeded = sum(1 for result in results if result["status"] == "completed")
        failed = len(results) - succeeded
        run = {
            "delivery_id": delivery_id,
            "status": "completed" if failed == 0 else ("partial" if succeeded else "failed"),
            "success_count": succeeded,
            "failure_count": failed,
            "delivery_location_label": "正式目录 / 输出 / 智能交付",
            "delivery_root": delivery_root,
            "results": results,
        }
        smart_delivery_run_registry[delivery_id] = run
        if shared_task_registry is not None:
            for result in results:
                if result.get("status") != "completed":
                    continue
                task_record = shared_task_registry.get(str(result.get("task_id") or ""))
                if not isinstance(task_record, dict):
                    continue
                delivery_trace = {
                    "delivery_id": delivery_id,
                    "delivery_item_id": result["delivery_item_id"],
                    "result_id": result.get("source_result_id") or result.get("result_id") or "",
                    "delivery_file": result.get("delivery_path") or "",
                    "status": "completed",
                }
                task_record["delivery_id"] = delivery_id
                task_record.setdefault("deliveries", []).append(delivery_trace)
                task_result = task_record.get("task_result")
                if isinstance(task_result, dict):
                    task_result["delivery_id"] = delivery_id
        public_results = [
            {key: value for key, value in result.items() if not key.startswith("_")}
            for result in results
        ]
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "data": {
                "delivery_id": delivery_id,
                "status": run["status"],
                "success_count": succeeded,
                "failure_count": failed,
                "delivery_location_label": run["delivery_location_label"],
                "results": public_results,
            },
        }

    def require_smart_delivery_run(delivery_id: str) -> dict[str, Any]:
        run = smart_delivery_run_registry.get(str(delivery_id or ""))
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
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type, filename=_safe_name(item.get("filename") or path.name))

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

    state = {
        "token_registry": token_registry,
        "expired_feedback_tokens": expired_feedback_tokens,
        "task_registry": task_registry,
        "color_batch_registry": color_batch_registry,
        "color_batch_queue": color_batch_queue,
        "output_center_index": output_center_index,
        "server_session_id": server_session_id,
    }
    app.state.image_compression_api_state = state
    return state
