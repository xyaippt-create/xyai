from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image, ImageOps

from engine.output.metadata_writer import (
    HDDE_COMMENT,
    HDDE_KEYWORDS,
    HDDE_SOFTWARE,
    _extract_xmp,
    _merged_xmp,
    read_hdde_metadata,
)

from .common import read_image_info


_PROTECTED_EXIF_TAGS = (
    270,    # ImageDescription
    271,    # Make
    272,    # Model
    315,    # Artist
    33432,  # Copyright
    34853,  # GPSInfo
    36867,  # DateTimeOriginal
    37386,  # FocalLength
    40091,  # XPTitle
    40093,  # XPAuthor
    42036,  # LensModel
)
_METADATA_REPORT_GATES = (
    "written",
    "decoded_pixel_content_unchanged",
    "alpha_unchanged",
    "icc_unchanged",
    "dpi_unchanged",
    "orientation_preserved",
    "title_preserved",
    "author_preserved",
    "source_metadata_preserved",
)


def _has_alpha_storage(image: Image.Image) -> bool:
    return "A" in image.getbands() or "transparency" in image.info


def _protected_exif_facts(path: Path) -> dict[int, str]:
    with Image.open(path) as image:
        image.load()
        exif = image.getexif()
        return {tag: repr(exif.get(tag)) for tag in _PROTECTED_EXIF_TAGS if tag in exif}


def _dpi_matches(source_dpi: Any, output_dpi: Any) -> bool:
    if source_dpi is None or output_dpi is None:
        return source_dpi is None and output_dpi is None
    if not isinstance(source_dpi, (tuple, list)) or not isinstance(output_dpi, (tuple, list)):
        return False
    if len(source_dpi) < 2 or len(output_dpi) < 2:
        return False
    try:
        # PNG pHYs stores integer pixels/metre, so cross-format conversion can
        # round a JPEG DPI value by a few thousandths without changing its meaning.
        return all(abs(float(source_dpi[index]) - float(output_dpi[index])) <= 0.02 for index in (0, 1))
    except (TypeError, ValueError):
        return False


def _decode_displayed(path: Path) -> tuple[Image.Image, bool]:
    with Image.open(path) as opened:
        if bool(getattr(opened, "is_animated", False)) or int(getattr(opened, "n_frames", 1)) != 1:
            raise ValueError("MULTI_FRAME_IMAGE_UNSUPPORTED")
        opened.load()
        has_alpha = _has_alpha_storage(opened)
        displayed = ImageOps.exif_transpose(opened).convert("RGBA")
    with Image.open(path) as verified:
        verified.verify()
    return displayed, has_alpha


def _verify_lossless_files(
    source_path: str | Path,
    candidate_path: str | Path,
    *,
    expected_format: str,
    metadata_report: Mapping[str, Any],
    rows_per_block: int = 128,
) -> dict[str, Any]:
    """Verify canonical displayed RGBA and metadata from two persisted files."""

    source_file = Path(source_path).resolve()
    candidate_file = Path(candidate_path).resolve()
    source_info = read_image_info(source_file, allow_webp=True)
    output_info = read_image_info(candidate_file, allow_webp=True)
    source_rgba, source_has_alpha = _decode_displayed(source_file)
    output_rgba, output_has_alpha = _decode_displayed(candidate_file)

    dimensions_equal = source_rgba.size == output_rgba.size
    pixel_diff_count = 0
    alpha_diff_count = 0
    max_channel_diff = 0
    if dimensions_equal:
        width, height = source_rgba.size
        block_height = max(1, int(rows_per_block))
        for top in range(0, height, block_height):
            bottom = min(height, top + block_height)
            source_block = np.frombuffer(
                source_rgba.crop((0, top, width, bottom)).tobytes(),
                dtype=np.uint8,
            ).reshape((bottom - top, width, 4))
            output_block = np.frombuffer(
                output_rgba.crop((0, top, width, bottom)).tobytes(),
                dtype=np.uint8,
            ).reshape((bottom - top, width, 4))
            difference = np.abs(source_block.astype(np.int16) - output_block.astype(np.int16))
            pixel_diff_count += int(np.count_nonzero(np.any(difference != 0, axis=2)))
            alpha_diff_count += int(np.count_nonzero(difference[:, :, 3]))
            if difference.size:
                max_channel_diff = max(max_channel_diff, int(difference.max()))

    source_alpha_extrema = source_rgba.getchannel("A").getextrema()
    source_has_real_transparency = int(source_alpha_extrema[0]) < 255
    alpha_exact = dimensions_equal and alpha_diff_count == 0
    alpha_preserved = alpha_exact and (not source_has_real_transparency or output_has_alpha)
    pixel_identical = dimensions_equal and pixel_diff_count == 0 and max_channel_diff == 0

    source_metadata = read_hdde_metadata(source_file)
    output_metadata = read_hdde_metadata(candidate_file)
    report_gates_pass = all(bool(metadata_report.get(key)) for key in _METADATA_REPORT_GATES)
    controlled_conflicts_clear = (
        int(metadata_report.get("iptc_controlled_conflicts", -1)) == 0
        and int(metadata_report.get("xmp_controlled_conflicts", -1)) == 0
    )
    hdde_metadata_valid = (
        output_metadata.get("software") == HDDE_SOFTWARE
        and output_metadata.get("comment") == HDDE_COMMENT
        and output_metadata.get("keywords") == HDDE_KEYWORDS
    )
    identity_metadata_preserved = all(
        output_metadata.get(key) == source_metadata.get(key)
        for key in ("title", "author", "copyright")
    )
    exif_preserved = _protected_exif_facts(source_file) == _protected_exif_facts(candidate_file)
    icc_preserved = source_info.get("icc_sha256") == output_info.get("icc_sha256")
    dpi_preserved = _dpi_matches(source_info.get("dpi"), output_info.get("dpi"))
    source_data = source_file.read_bytes()
    output_data = candidate_file.read_bytes()
    source_sha256 = hashlib.sha256(source_data).hexdigest()
    output_sha256 = hashlib.sha256(output_data).hexdigest()
    artifact_identity_stable = (
        source_sha256 == source_info.get("sha256")
        and output_sha256 == output_info.get("sha256")
    )
    xmp_preserved = _extract_xmp(output_data) == _merged_xmp(output_data, source_data)
    metadata_verified = all((
        artifact_identity_stable,
        report_gates_pass,
        controlled_conflicts_clear,
        hdde_metadata_valid,
        identity_metadata_preserved,
        exif_preserved,
        icc_preserved,
        dpi_preserved,
        xmp_preserved,
    ))
    decodable = output_info.get("format") == expected_format
    lossless_verified = bool(decodable and pixel_identical and alpha_preserved and metadata_verified)

    return {
        "verification_status": "PASS" if lossless_verified else "FAIL",
        "lossless_verified": lossless_verified,
        "source_sha256": source_sha256,
        "output_sha256": output_sha256,
        "artifact_identity_stable": artifact_identity_stable,
        "pixel_identical": pixel_identical,
        "pixel_diff_count": pixel_diff_count if dimensions_equal else None,
        "max_channel_diff": max_channel_diff if dimensions_equal else None,
        "dimensions_equal": dimensions_equal,
        "source_dimensions": {"width": source_rgba.width, "height": source_rgba.height},
        "output_dimensions": {"width": output_rgba.width, "height": output_rgba.height},
        "alpha_exact": alpha_exact,
        "alpha_diff_count": alpha_diff_count if dimensions_equal else None,
        "source_has_alpha": source_has_alpha,
        "output_has_alpha": output_has_alpha,
        "source_has_real_transparency": source_has_real_transparency,
        "alpha_preserved": alpha_preserved,
        "alpha_optimized": bool(source_has_alpha and not source_has_real_transparency and not output_has_alpha),
        "metadata_verified": metadata_verified,
        "metadata_report_gates_pass": report_gates_pass,
        "controlled_conflicts_clear": controlled_conflicts_clear,
        "hdde_metadata_valid": hdde_metadata_valid,
        "identity_metadata_preserved": identity_metadata_preserved,
        "exif_preserved": exif_preserved,
        "icc_preserved": icc_preserved,
        "dpi_preserved": dpi_preserved,
        "xmp_preserved": xmp_preserved,
        "decodable": decodable,
    }


def verify_lossless_png_files(
    source_path: str | Path,
    candidate_path: str | Path,
    *,
    metadata_report: Mapping[str, Any],
    rows_per_block: int = 128,
) -> dict[str, Any]:
    return _verify_lossless_files(
        source_path,
        candidate_path,
        expected_format="PNG",
        metadata_report=metadata_report,
        rows_per_block=rows_per_block,
    )


def verify_lossless_webp_files(
    source_path: str | Path,
    candidate_path: str | Path,
    *,
    metadata_report: Mapping[str, Any],
    rows_per_block: int = 128,
) -> dict[str, Any]:
    return _verify_lossless_files(
        source_path,
        candidate_path,
        expected_format="WEBP",
        metadata_report=metadata_report,
        rows_per_block=rows_per_block,
    )


__all__ = ["verify_lossless_png_files", "verify_lossless_webp_files"]
