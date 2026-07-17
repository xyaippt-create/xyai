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
import math
import mimetypes
import os
import platform
import secrets
import shutil
import subprocess
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote


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


def register_image_compression_routes(
    app,
    *,
    user_dirs_provider: Callable[[], dict[str, Path]],
    now_provider: Callable[[], float] = time.time,
    folder_opener: Callable[[str], None] | None = None,
    output_settings_provider: Callable[[], Mapping[str, Any]] | None = None,
    output_default_saver: Callable[[str], None] | None = None,
    output_dir_validator: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Register the local Stage 4 API on the already-created FastAPI app."""

    from fastapi import Body, File, HTTPException, UploadFile
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

    token_registry: dict[str, dict[str, Any]] = {}
    expired_feedback_tokens: set[str] = set()
    task_registry: dict[str, dict[str, Any]] = {}
    server_session_id = uuid.uuid4().hex

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
        fallback = Path(user_dirs_provider()["normal_output_dir"]).resolve() / "图片压缩输出"
        built_in = str(configured.get("built_in_default_root") or fallback)
        saved = str(configured.get("saved_default_root") or built_in)
        return {"built_in_default_root": built_in, "saved_default_root": saved}

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

    def effective_output_root(payload: Mapping[str, Any]) -> dict[str, Any]:
        current = str(payload.get("current_task_output_root") or "").strip()
        settings = output_settings()
        selected = current or settings["saved_default_root"]
        return validate_output_root(selected, source="current_task" if current else "saved_default")

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
        if set(payload) != {"output_root"}:
            raise HTTPException(status_code=400, detail={"code": "OUTPUT_DIRECTORY_INVALID", "message": "默认输出目录请求字段不正确。"})
        checked = validate_output_root(str(payload.get("output_root") or ""), source="saved_default")
        if output_default_saver is None:
            raise HTTPException(status_code=503, detail={"code": "OUTPUT_SETTINGS_UNAVAILABLE", "message": "当前运行环境无法保存默认输出目录。"})
        output_default_saver(checked["normalized_path"])
        return {"code": 200, "status": "success", "success": True, "data": {"saved_default_root": checked["normalized_path"], "effective_output_root": checked["normalized_path"], "output_root_writable": True}}

    @app.post("/api/image-compression/output-settings/restore")
    async def image_compression_restore_default_output(payload: dict = Body(default_factory=dict)):
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
        intake_root = Path(user_dirs_provider()["tmp_dir"]).resolve() / "image-compression-intake"
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
        token = str(payload.get("source_token") or "")
        source = require_token(token, role="source")
        product_preflight(payload, source)
        task_id = f"compression_{uuid.uuid4().hex[:16]}"
        task_created_at = now_provider()
        preflight_output = Path(user_dirs_provider()["tmp_dir"]).resolve() / "image-compression-preflight"
        request = build_task_request(payload, source, task_id, preflight_output)
        output_root = effective_output_root(payload)
        effective_root = Path(output_root["normalized_path"])
        output_dir = function_output_dir(str(request["operation_mode"]), effective_root)
        request["output_directory"] = str(output_dir)
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
        source_preview = preview_token_for(Path(source["path"]), role="source_preview")
        output_preview = preview_token_for(output_path, role="output_preview") if output_path and output_path.exists() else None
        long_image_validation = build_long_image_validation(source, request)
        resize_validation = build_resize_validation(source, request, result)
        record = {
            "task_id": task_id,
            "created_at": datetime.fromtimestamp(task_created_at, tz=timezone.utc).isoformat(),
            "request": request,
            "result": result,
            "source_path": Path(source["path"]),
            "output_path": output_path,
            "output_dir": output_dir,
            "effective_output_root": effective_root,
            "output_root_source": output_root["source"],
            "source_preview_token": source_preview,
            "output_preview_token": output_preview,
            "review_note": "",
            "reviewed_at": None,
            "review_output_sha256_before": result.output_sha256,
            "review_output_sha256_after": None,
            "source_metadata": dict(source),
            "long_image_validation": long_image_validation,
            "resize_validation": resize_validation,
            "feedback_package": None,
            "feedback_package_token": None,
            "feedback_artifact_stem": output_path.stem if result.output_created and output_path else Path(
                readable_output_name(
                    str(source.get("filename") or "image.png"),
                    Path(str(source.get("filename") or "image.png")).suffix or ".png",
                    request,
                    task_id,
                    task_created_at,
                )
            ).stem,
        }
        task_registry[task_id] = record
        return {"code": 200, "status": "success", "success": True, "data": public_result(record)}

    @app.post("/api/image-compression/test-feedback-package")
    async def image_compression_test_feedback_package(payload: dict = Body(default_factory=dict)):
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
        return {"code": 200, "status": "success", "success": True, "data": public_result(record)}

    @app.post("/api/image-compression/open-output-folder")
    async def image_compression_open_output_folder(payload: dict = Body(default_factory=dict)):
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

    @app.get("/api/image-compression/preview/{token}")
    async def image_compression_preview(token: str):
        item = require_token(token)
        path = Path(item["path"]).resolve()
        if item.get("role") not in {"source_preview", "output_preview"}:
            raise HTTPException(status_code=403, detail="预览令牌用途不正确。")
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type, filename=_safe_name(item.get("filename") or path.name))

    @app.get("/api/image-compression/feedback-package/{token}")
    async def image_compression_feedback_package_download(token: str):
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
        "server_session_id": server_session_id,
    }
    app.state.image_compression_api_state = state
    return state
