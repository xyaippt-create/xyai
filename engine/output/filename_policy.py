"""The single user-visible filename contract for HDDE final images."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


FEATURE_4K = "4k"
FEATURE_1080P = "1080p"
FEATURE_COLOR = "color_correction"
FEATURE_RETOUCH = "local_retouch"
FEATURE_COMPRESSION = "image_compression"
FEATURE_WATERMARK = "batch_watermark"

FUNCTION_SHORT_NAMES = {
    FEATURE_4K: "4K",
    FEATURE_1080P: "1080P",
    FEATURE_COLOR: "校色",
    FEATURE_RETOUCH: "修复",
    FEATURE_COMPRESSION: "压缩",
    FEATURE_WATERMARK: "水印",
}

_FEATURE_ALIASES = {
    "4k_v1": FEATURE_4K,
    "enhancement_4k": FEATURE_4K,
    "4k画质增强": FEATURE_4K,
    "delivery_1080p": FEATURE_1080P,
    "enhancement_1080p": FEATURE_1080P,
    "1080p画质": FEATURE_1080P,
    "颜色校正": FEATURE_COLOR,
    "校色": FEATURE_COLOR,
    "瑕疵修复": FEATURE_RETOUCH,
    "修复": FEATURE_RETOUCH,
    "compression": FEATURE_COMPRESSION,
    "lossless_compression": FEATURE_COMPRESSION,
    "resize_reduction": FEATURE_COMPRESSION,
    "upload_adaptation": FEATURE_COMPRESSION,
    "图片压缩": FEATURE_COMPRESSION,
    "压缩": FEATURE_COMPRESSION,
    "批量水印": FEATURE_WATERMARK,
    "水印": FEATURE_WATERMARK,
}

_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def _normalise_feature(value: str) -> str:
    key = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    key = _FEATURE_ALIASES.get(key, key)
    if key not in FUNCTION_SHORT_NAMES:
        raise ValueError(f"UNSUPPORTED_OUTPUT_FEATURE:{value}")
    return key


def _safe_stem(value: str | Path) -> str:
    leaf = Path(str(value or "图片")).name
    stem = Path(leaf).stem.strip() or "图片"
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).rstrip(" .") or "图片"
    if cleaned.upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned[:120].rstrip(" .") or "图片"


def _safe_extension(value: str | Path) -> str:
    raw = str(value or "").strip().lower()
    suffix = Path(raw).suffix if not raw.startswith(".") else raw
    if suffix == ".jpeg":
        suffix = ".jpg"
    if suffix not in {".png", ".jpg", ".webp"}:
        raise ValueError(f"UNSUPPORTED_OUTPUT_EXTENSION:{value}")
    return suffix


def build_output_filename(
    current_filename: str | Path,
    feature: str,
    extension: str | Path,
    *,
    trusted_original_filename: str | Path | None = None,
    moment: datetime | None = None,
    sequence: int | None = None,
) -> str:
    """Build one filename without guessing away any part of a user stem.

    A trusted original name wins when supplied by the formal task provenance.
    Otherwise the current real filename is used verbatim after Windows-safe
    character normalisation (SAFE_NO_STRIP).
    """

    source_name = trusted_original_filename if str(trusted_original_filename or "").strip() else current_filename
    stem = _safe_stem(source_name)
    short_name = FUNCTION_SHORT_NAMES[_normalise_feature(feature)]
    date_text = (moment or datetime.now()).strftime("%y%m%d")
    sequence_text = ""
    if sequence is not None:
        if isinstance(sequence, bool) or int(sequence) < 2:
            raise ValueError("OUTPUT_SEQUENCE_MUST_START_AT_02")
        sequence_text = f"_{int(sequence):02d}"
    return f"{stem}_影界{short_name}_{date_text}{sequence_text}{_safe_extension(extension)}"


def build_output_path(
    output_directory: str | Path,
    current_filename: str | Path,
    feature: str,
    extension: str | Path,
    *,
    trusted_original_filename: str | Path | None = None,
    moment: datetime | None = None,
) -> Path:
    directory = Path(output_directory)
    candidate = directory / build_output_filename(
        current_filename,
        feature,
        extension,
        trusted_original_filename=trusted_original_filename,
        moment=moment,
    )
    sequence = 2
    while candidate.exists():
        candidate = directory / build_output_filename(
            current_filename,
            feature,
            extension,
            trusted_original_filename=trusted_original_filename,
            moment=moment,
            sequence=sequence,
        )
        sequence += 1
    return candidate


def resolve_collision_path(output_directory: str | Path, filename: str | Path) -> Path:
    """Preserve a requested filename and allocate _02, _03... on collision."""

    directory = Path(output_directory)
    leaf = Path(str(filename)).name
    if not leaf or leaf in {".", ".."}:
        raise ValueError("OUTPUT_FILENAME_REQUIRED")
    stem = _safe_stem(leaf)
    suffix = _safe_extension(Path(leaf).suffix)
    candidate = directory / f"{stem}{suffix}"
    sequence = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{sequence:02d}{suffix}"
        sequence += 1
    return candidate
