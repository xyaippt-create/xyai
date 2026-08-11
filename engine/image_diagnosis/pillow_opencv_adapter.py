from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .contracts import DecodedDiagnosisImage, ImageDiagnosisError


MAX_DIAGNOSIS_PIXELS = 100_000_000
MAX_DIAGNOSIS_FILE_BYTES = 250 * 1024 * 1024
SAFE_EXIF_TAGS = {
    271: "make",
    272: "model",
    274: "orientation",
    305: "software",
    306: "datetime",
    36867: "datetime_original",
    40961: "color_space",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_exif_value(value: Any) -> str | int | float | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, bytes):
        return None
    text = str(value or "").strip()
    return text[:160] if text else None


def _format_name(value: str | None) -> str:
    name = str(value or "UNKNOWN").upper()
    return "JPEG" if name == "JPG" else name


class PillowOpenCvDiagnosisAdapter:
    """Read-only decoder boundary used by the D1 diagnosis engine."""

    adapter_id = "pillow-opencv-readonly-v1"

    def decode(self, source_path: Path) -> DecodedDiagnosisImage:
        path = Path(source_path).expanduser().resolve()
        if not path.is_file():
            raise ImageDiagnosisError("诊断源图片不存在或不是文件。")
        stat_before = path.stat()
        if stat_before.st_size <= 0 or stat_before.st_size > MAX_DIAGNOSIS_FILE_BYTES:
            raise ImageDiagnosisError("诊断源图片为空或超过250MB安全限制。")
        source_sha256 = _sha256(path)

        try:
            with Image.open(path) as opened:
                stored_width, stored_height = opened.size
                if stored_width <= 0 or stored_height <= 0 or stored_width * stored_height > MAX_DIAGNOSIS_PIXELS:
                    raise ImageDiagnosisError("诊断源图片尺寸无效或超过一亿像素安全限制。")
                image_format = _format_name(opened.format)
                color_mode = str(opened.mode or "UNKNOWN")
                try:
                    exif = opened.getexif()
                    exif_fields = {
                        name: safe_value
                        for tag, name in SAFE_EXIF_TAGS.items()
                        if (safe_value := _safe_exif_value(exif.get(tag))) is not None
                    }
                except Exception:
                    exif = {}
                    exif_fields = {}

                has_alpha = "A" in opened.getbands() or "transparency" in opened.info
                if has_alpha:
                    rgba = opened.convert("RGBA")
                    alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
                    transparent_ratio = float(np.mean(alpha < 255))
                else:
                    transparent_ratio = 0.0

                oriented = ImageOps.exif_transpose(opened)
                rgb = np.asarray(oriented.convert("RGB"), dtype=np.uint8)
                height, width = rgb.shape[:2]
        except ImageDiagnosisError:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ImageDiagnosisError("图片无法安全解码，诊断未执行。") from exc

        divisor = math.gcd(width, height)
        pixels = width * height
        facts = {
            "width": width,
            "height": height,
            "stored_width": stored_width,
            "stored_height": stored_height,
            "aspect_ratio": round(width / height, 6),
            "aspect_ratio_label": f"{width // divisor}:{height // divisor}",
            "megapixels": round(pixels / 1_000_000, 4),
            "format": image_format,
            "file_size_bytes": stat_before.st_size,
            "bytes_per_pixel": round(stat_before.st_size / max(pixels, 1), 4),
            "color_mode": color_mode,
            "has_alpha": has_alpha,
            "transparent_pixel_ratio": round(transparent_ratio, 6),
            "exif": {
                "present": bool(exif_fields),
                "field_count": len(exif_fields),
                "fields": exif_fields,
            },
        }
        return DecodedDiagnosisImage(
            source_path=path,
            bgr=cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
            image_facts=facts,
            source_sha256=source_sha256,
            source_mtime_ns=stat_before.st_mtime_ns,
            source_size_bytes=stat_before.st_size,
        )
