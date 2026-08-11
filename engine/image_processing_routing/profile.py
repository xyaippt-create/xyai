from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from .contracts import PreflightContractError


MIME_TYPES = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "TIFF": "image/tiff",
    "WEBP": "image/webp",
}


def resolution_bucket(short_side: int) -> str:
    if short_side < 600:
        return "SHORT_SIDE_LT_600"
    if short_side < 1080:
        return "SHORT_SIDE_600_1079"
    if short_side < 1440:
        return "SHORT_SIDE_1080_1439"
    if short_side < 2160:
        return "SHORT_SIDE_1440_2159"
    if short_side < 4320:
        return "SHORT_SIDE_2160_4319"
    return "SHORT_SIDE_GE_4320"


def build_image_profile(path: str | Path, *, width: int | None = None, height: int | None = None) -> dict[str, Any]:
    """Read an objective image profile without creating any processing output."""

    source = Path(path)
    try:
        with Image.open(source) as image:
            image_format = str(image.format or "").upper()
            raw_width, raw_height = image.size
            frame_count = int(getattr(image, "n_frames", 1) or 1)
            is_animated = bool(getattr(image, "is_animated", False)) and image_format in {"PNG", "WEBP", "GIF"}
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            for index in range(frame_count):
                image.seek(index)
                image.load()
    except Exception as exc:
        raise PreflightContractError("IMAGE_DECODE_FAILED", status_code=422) from exc

    effective_width = int(width or raw_width)
    effective_height = int(height or raw_height)
    short_side = min(effective_width, effective_height)
    long_side = max(effective_width, effective_height)
    is_long = effective_height / effective_width >= 3 or effective_height >= 4000
    is_ultra_wide = effective_width / effective_height >= 3
    warnings: list[str] = []
    if is_animated:
        warnings.append("ANIMATED_IMAGE_NOT_SUPPORTED")
    elif frame_count > 1:
        warnings.append("MULTI_FRAME_IMAGE_NOT_SUPPORTED")
    if image_format not in {"PNG", "JPEG"}:
        warnings.append("FORMAT_NOT_SUPPORTED")
    if is_long:
        warnings.append("LONG_IMAGE_DETECTED")
    if is_ultra_wide:
        warnings.append("ULTRA_WIDE_IMAGE_DETECTED")
    if has_alpha:
        warnings.append("ALPHA_CHANNEL_PRESENT")

    unsupported = is_animated or frame_count > 1 or image_format not in {"PNG", "JPEG"}
    eligibility = "UNSUPPORTED" if unsupported else ("ELIGIBLE_WITH_WARNING" if warnings else "ELIGIBLE")
    size_bytes = source.stat().st_size
    return {
        "format": image_format,
        "mime_type": MIME_TYPES.get(image_format, "application/octet-stream"),
        "width": effective_width,
        "height": effective_height,
        "short_side": short_side,
        "long_side": long_side,
        "aspect_ratio": round(effective_width / effective_height, 6),
        "orientation": "LANDSCAPE" if effective_width > effective_height else ("PORTRAIT" if effective_height > effective_width else "SQUARE"),
        "size_bytes": size_bytes,
        "size_kb": round(size_bytes / 1024, 6),
        "size_mb": round(size_bytes / 1048576, 6),
        "has_alpha": has_alpha,
        "is_animated": is_animated,
        "frame_count": frame_count,
        "is_long_image": is_long,
        "is_ultra_wide": is_ultra_wide,
        "resolution_bucket": resolution_bucket(short_side),
        "processing_eligibility": eligibility,
        "warnings": warnings,
    }
