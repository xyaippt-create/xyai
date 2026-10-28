from __future__ import annotations

import hashlib
import io
import tempfile
import time
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageOps

from engine.output.filename_policy import FEATURE_COMPRESSION, build_output_path, resolve_collision_path
from engine.output.publish_safety import publish_image_bytes_with_metadata, publish_prepared_bytes_no_overwrite

from .common import CompressionRuntimeError, optimise_png_data, read_image_info
from .jpg_quality_gate import JPG_QUALITY_GATE_VERSION, evaluate_jpg_quality, prepare_jpg_source_analysis
from .lossless_verifier import verify_lossless_png_files, verify_lossless_webp_files
from .statuses import TechnicalStatus


DELIVERY_OPTIMIZATION_MODE = "DELIVERY_OPTIMIZATION"
SMART_COMPRESSION_TARGET_FORMAT = "SMART_COMPRESSION"
PRESERVE_FORMAT_TARGET_FORMAT = "PRESERVE_FORMAT"
PNG_LOSSLESS_SCHEME = "png_lossless"
WEBP_LOSSLESS_SCHEME = "webp_lossless"
JPG_HIGH_QUALITY_SCHEME = "jpg_high_quality"
JPG_BALANCED_SCHEME = "jpg_balanced"
KEEP_ORIGINAL_SCHEME = "keep_original"
SINGLE_WINNER_POLICY = "SINGLE_WINNER_QUALITY_V2"
SUPPORTED_TARGET_FORMATS = frozenset({
    SMART_COMPRESSION_TARGET_FORMAT,
    PRESERVE_FORMAT_TARGET_FORMAT,
    "JPEG",
    "PNG",
    "WEBP",
})
LARGE_LOW_GAIN_MAX_SAVING_PERCENT = 20.0  # Search trigger only; never a quality threshold.

# Size changes search effort only. JPG quality acceptance remains exclusively
# controlled by JPG_DELIVERY_QUALITY_V1.
SIZE_SEARCH_PROFILE: dict[str, dict[str, Any]] = {
    "SMALL": {
        "max_bytes": 500 * 1024,
        "coarse_qualities": (98, 95, 92, 88, 85),
        "quality_floor": 84,
        "max_encodings": 7,
        "min_jpg_saved_bytes": 8 * 1024,
        "min_jpg_saved_percent": 4.0,
    },
    "MEDIUM": {
        "max_bytes": 2 * 1024 * 1024,
        "coarse_qualities": (98, 95, 92, 88, 85, 82),
        "quality_floor": 80,
        "max_encodings": 8,
        "min_jpg_saved_bytes": 16 * 1024,
        "min_jpg_saved_percent": 2.0,
    },
    "LARGE": {
        "max_bytes": 5 * 1024 * 1024,
        "coarse_qualities": (98, 95, 92, 88, 85, 82, 78),
        "quality_floor": 76,
        "max_encodings": 9,
        "min_jpg_saved_bytes": 32 * 1024,
        "min_jpg_saved_percent": 1.0,
    },
    "VERY_LARGE": {
        "max_bytes": None,
        "coarse_qualities": (98, 95, 92, 88, 85, 82, 78, 74),
        "quality_floor": 72,
        "max_encodings": 10,
        "min_jpg_saved_bytes": 64 * 1024,
        "min_jpg_saved_percent": 0.5,
    },
}

CONTENT_RISK_PROFILE: dict[str, dict[str, Any]] = {
    "TEXT_LINE_HIGH_RISK": {"subsampling_order": (0, 2), "secondary_search": "LIMITED"},
    "PHOTO_NORMAL": {"subsampling_order": (2, 0), "secondary_search": "STANDARD"},
    "LOW_FREQUENCY_FRIENDLY": {"subsampling_order": (2, 0), "secondary_search": "STANDARD"},
    "HIGH_FREQUENCY_COMPLEX": {"subsampling_order": (0, 2), "secondary_search": "LIMITED"},
    "REAL_TRANSPARENCY": {"subsampling_order": (), "secondary_search": "DISABLED"},
}

_SCHEMES = (
    {
        "scheme_id": PNG_LOSSLESS_SCHEME,
        "display_name": "PNG 无损",
        "format": "PNG",
        "applicable_scene": "文字、图标、界面截图与需保留透明通道的高保真交付",
        "quality": None,
    },
    {
        "scheme_id": JPG_HIGH_QUALITY_SCHEME,
        "display_name": "JPG 高质量",
        "format": "JPG",
        "applicable_scene": "照片、海报与不含透明区域的高质量交付",
        "quality": 95,
    },
    {
        "scheme_id": JPG_BALANCED_SCHEME,
        "display_name": "JPG 平衡",
        "format": "JPG",
        "applicable_scene": "邮件、即时通讯与体积优先的日常交付",
        "quality": 85,
    },
)

_WEBP_SCHEME = {
    "scheme_id": WEBP_LOSSLESS_SCHEME,
    "display_name": "WebP 无损",
    "format": "WEBP",
    "applicable_scene": "需要保持原始像素与透明通道的现代图片交付",
    "quality": None,
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_source_identity(source_file: Path) -> tuple[bytes, str, int]:
    data = source_file.read_bytes()
    return data, _sha256_bytes(data), len(data)


def _require_source_identity(
    source_file: Path,
    *,
    registered_sha256: str,
    registered_size: int,
) -> bytes:
    try:
        current_data, current_sha256, current_size = _read_source_identity(source_file)
    except OSError as exc:
        raise CompressionRuntimeError(
            "SOURCE_IDENTITY_MISMATCH",
            "发布前无法重新读取已登记 Source。",
            TechnicalStatus.CANNOT_MEET_SAFELY,
        ) from exc
    if current_sha256 != registered_sha256 or current_size != registered_size:
        raise CompressionRuntimeError(
            "SOURCE_IDENTITY_MISMATCH",
            "当前 Source 内容与任务开始时登记的身份不一致。",
            TechnicalStatus.CANNOT_MEET_SAFELY,
        )
    return current_data


def _real_transparency(image: Image.Image) -> bool:
    if "A" not in image.getbands() and "transparency" not in image.info:
        return False
    alpha = image.convert("RGBA").getchannel("A")
    minimum, _maximum = alpha.getextrema()
    return int(minimum) < 255


def _has_alpha_storage(image: Image.Image) -> bool:
    return "A" in image.getbands() or "transparency" in image.info


def _save_kwargs(source: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if source.get("icc_profile"):
        kwargs["icc_profile"] = source["icc_profile"]
    if source.get("dpi"):
        kwargs["dpi"] = tuple(source["dpi"])
    return kwargs


def _encode_jpg_candidate(
    image: Image.Image,
    source: dict[str, Any],
    *,
    quality: int,
    subsampling: int,
) -> bytes:
    stream = io.BytesIO()
    kwargs = _save_kwargs(source)
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    rgb.save(
        stream,
        format="JPEG",
        quality=int(quality),
        subsampling=int(subsampling),
        optimize=True,
        progressive=False,
        **kwargs,
    )
    return stream.getvalue()


def _jpg_reference_image(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    background.alpha_composite(rgba)
    return background.convert("RGB")


def _encode_webp_candidate(image: Image.Image, source: dict[str, Any]) -> bytes:
    stream = io.BytesIO()
    target = image.convert("RGBA") if _has_alpha_storage(image) else image.convert("RGB")
    target.save(
        stream,
        format="WEBP",
        lossless=True,
        quality=100,
        method=6,
        exact=True,
        **_save_kwargs(source),
    )
    return stream.getvalue()


def _size_search_profile(source_size: int) -> tuple[str, dict[str, Any]]:
    for profile_id, profile in SIZE_SEARCH_PROFILE.items():
        maximum = profile["max_bytes"]
        if maximum is None or source_size <= int(maximum):
            return profile_id, dict(profile)
    raise AssertionError("SIZE_SEARCH_PROFILE must contain an unbounded final profile")


def _content_risk_profile(image: Image.Image, *, has_real_transparency: bool) -> tuple[str, dict[str, float]]:
    if has_real_transparency:
        return "REAL_TRANSPARENCY", {
            "edge_density": 0.0,
            "strong_edge_density": 0.0,
            "smooth_fraction": 0.0,
            "high_frequency_mean": 0.0,
        }
    analysis = image.convert("RGB")
    analysis.thumbnail((512, 512), Image.Resampling.LANCZOS)
    gray = np.asarray(analysis.convert("L"), dtype=np.float32)
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return "LOW_FREQUENCY_FRIENDLY", {
            "edge_density": 0.0,
            "strong_edge_density": 0.0,
            "smooth_fraction": 1.0,
            "high_frequency_mean": 0.0,
        }
    dx = np.abs(np.diff(gray, axis=1))[:-1, :]
    dy = np.abs(np.diff(gray, axis=0))[:, :-1]
    gradient = np.maximum(dx, dy)
    laplacian = np.abs(
        -4.0 * gray[1:-1, 1:-1]
        + gray[:-2, 1:-1]
        + gray[2:, 1:-1]
        + gray[1:-1, :-2]
        + gray[1:-1, 2:]
    )
    metrics = {
        "edge_density": round(float(np.mean(gradient >= 18.0)), 6),
        "strong_edge_density": round(float(np.mean(gradient >= 40.0)), 6),
        "smooth_fraction": round(float(np.mean(gradient <= 4.0)), 6),
        "high_frequency_mean": round(float(np.mean(laplacian)), 6),
    }
    if metrics["smooth_fraction"] >= 0.55 and metrics["edge_density"] >= 0.035:
        profile_id = "TEXT_LINE_HIGH_RISK"
    elif (
        metrics["edge_density"] >= 0.34
        or metrics["high_frequency_mean"] >= 30.0
        or (
            metrics["smooth_fraction"] < 0.30
            and metrics["high_frequency_mean"] >= 24.0
        )
    ):
        profile_id = "HIGH_FREQUENCY_COMPLEX"
    elif metrics["smooth_fraction"] >= 0.82 and metrics["edge_density"] < 0.025:
        profile_id = "LOW_FREQUENCY_FRIENDLY"
    else:
        profile_id = "PHOTO_NORMAL"
    return profile_id, metrics


def _jpg_scheme(quality: int, subsampling: int) -> dict[str, Any]:
    if quality == 95 and subsampling == 0:
        return dict(_SCHEMES[1])
    if quality == 85 and subsampling == 0:
        return dict(_SCHEMES[2])
    subsampling_label = "444" if subsampling == 0 else "420"
    return {
        "scheme_id": f"jpg_adaptive_q{quality}_{subsampling_label}",
        "display_name": "JPG 自适应",
        "format": "JPG",
        "applicable_scene": "不含真实透明区域、通过质量安全门且体积更小的日常交付",
        "quality": quality,
    }


def _encode_png_variant(
    image: Image.Image,
    source: dict[str, Any],
    *,
    optimize: bool,
    compress_level: int,
    remove_opaque_alpha: bool = False,
) -> bytes:
    stream = io.BytesIO()
    target = image.convert("RGB") if remove_opaque_alpha else (
        image.convert("RGBA") if _has_alpha_storage(image) else image
    )
    target.save(
        stream,
        format="PNG",
        optimize=optimize,
        compress_level=compress_level,
        **_save_kwargs(source),
    )
    return stream.getvalue()


def _png_variant_payloads(
    displayed: Image.Image,
    source: dict[str, Any],
    source_data: bytes,
) -> list[tuple[str, bytes]]:
    variants = [
        ("a01_pillow_optimize", _encode_png_variant(displayed, source, optimize=True, compress_level=9)),
        ("pillow_deflate_9", _encode_png_variant(displayed, source, optimize=False, compress_level=9)),
        ("pillow_deflate_6", _encode_png_variant(displayed, source, optimize=False, compress_level=6)),
    ]
    if source.get("format") == "PNG" and source.get("exif_orientation") in (None, 1):
        structurally_optimized, _details = optimise_png_data(source_data)
        variants.append(("source_idat_optimized", structurally_optimized))
    if _has_alpha_storage(displayed) and not _real_transparency(displayed):
        variants.extend((
            ("opaque_alpha_to_rgb_optimize", _encode_png_variant(
                displayed,
                source,
                optimize=True,
                compress_level=9,
                remove_opaque_alpha=True,
            )),
            ("opaque_alpha_to_rgb_deflate_9", _encode_png_variant(
                displayed,
                source,
                optimize=False,
                compress_level=9,
                remove_opaque_alpha=True,
            )),
        ))
    return variants


def _basic_png_verifier(data: bytes, *, expected_dimensions: tuple[int, int]) -> dict[str, Any]:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if str(image.format or "").upper() != "PNG" or image.size != expected_dimensions:
            raise RuntimeError("PNG 候选格式或尺寸验证失败。")
    return {
        "format": "PNG",
        "dimensions": {"width": expected_dimensions[0], "height": expected_dimensions[1]},
        "sha256": _sha256_bytes(data),
        "size_bytes": len(data),
    }


def _lossless_gain(source_size: int, output_size: int) -> tuple[int, float, str]:
    saved_bytes = source_size - output_size
    saved_percent = (saved_bytes / source_size * 100.0) if source_size else 0.0
    if saved_bytes <= 0:
        level = "NONE"
    elif saved_percent < 5.0:
        level = "LOW"
    else:
        level = "MEANINGFUL"
    return saved_bytes, round(saved_percent, 4), level


def _target_candidates(requested_path: Path) -> Iterable[Path]:
    yield requested_path
    while True:
        yield resolve_collision_path(requested_path.parent, requested_path.name)


def _generate_verified_png_candidate(
    source_file: Path,
    output_root: Path,
    *,
    source_filename: str,
    source: dict[str, Any],
    source_data: bytes,
    displayed: Image.Image,
    moment: datetime,
) -> dict[str, Any]:
    width, height = displayed.size
    variant_evidence: list[dict[str, Any]] = []
    passing: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix=".hdde-a02-lossless-", dir=output_root) as temporary_name:
        temporary_root = Path(temporary_name)
        for index, (variant_id, encoded) in enumerate(_png_variant_payloads(displayed, source, source_data), start=1):
            try:
                temporary_path, metadata_report, _private = publish_image_bytes_with_metadata(
                    encoded,
                    temporary_root / f"{index:02d}-{variant_id}.png",
                    source_data=source_data,
                    normalize_orientation=True,
                    verify_private=lambda data: _basic_png_verifier(data, expected_dimensions=(width, height)),
                )
                verification = verify_lossless_png_files(
                    source_file,
                    temporary_path,
                    metadata_report=metadata_report,
                )
                evidence = {
                    "variant_id": variant_id,
                    "output_size": temporary_path.stat().st_size,
                    "verification_status": verification["verification_status"],
                    "pixel_diff_count": verification["pixel_diff_count"],
                    "max_channel_diff": verification["max_channel_diff"],
                    "alpha_optimized": verification["alpha_optimized"],
                }
                variant_evidence.append(evidence)
                if verification["lossless_verified"]:
                    passing.append({
                        "variant_id": variant_id,
                        "path": temporary_path,
                        "metadata_report": metadata_report,
                        "verification": verification,
                        "output_size": temporary_path.stat().st_size,
                    })
            except Exception as exc:
                variant_evidence.append({
                    "variant_id": variant_id,
                    "output_size": None,
                    "verification_status": "FAIL",
                    "failure_reason": str(exc) or exc.__class__.__name__,
                })

        if not passing:
            raise CompressionRuntimeError(
                "PNG_LOSSLESS_VERIFICATION_FAILED",
                "所有 PNG 严格无损候选均未通过正式文件验证。",
                TechnicalStatus.CANNOT_MEET_SAFELY,
            )
        selected = min(passing, key=lambda item: (int(item["output_size"]), str(item["variant_id"])))
        baseline = next(
            (item for item in passing if item["variant_id"] == "a01_pillow_optimize"),
            None,
        )
        selected_data = Path(selected["path"]).read_bytes()
        selected_sha256 = _sha256_bytes(selected_data)
        requested_path = build_output_path(
            output_root,
            source_filename,
            FEATURE_COMPRESSION,
            ".png",
            trusted_original_filename=source_filename,
            moment=moment,
        )
        publish_integrity: dict[str, Any] = {}

        def verify_selected_bytes(data: bytes) -> dict[str, Any]:
            if _sha256_bytes(data) != selected_sha256:
                raise RuntimeError("已验证候选在正式发布前发生变化。")
            return _basic_png_verifier(data, expected_dimensions=(width, height))

        published_path, verified = publish_prepared_bytes_no_overwrite(
            selected_data,
            _target_candidates(requested_path),
            verify_private=verify_selected_bytes,
            integrity_report=publish_integrity,
        )
        final_metadata_report = {
            **dict(selected["metadata_report"]),
            "publish_integrity": publish_integrity,
        }
        final_verification = verify_lossless_png_files(
            source_file,
            published_path,
            metadata_report=final_metadata_report,
        )
        if not final_verification["lossless_verified"]:
            raise CompressionRuntimeError(
                "PNG_FORMAL_FILE_VERIFICATION_FAILED",
                "PNG 正式输出文件未通过严格零像素变化验证。",
                TechnicalStatus.CANNOT_MEET_SAFELY,
            )

    source_size = int(source["size_bytes"])
    output_size = int(verified["size_bytes"])
    saved_bytes, saved_percent, gain = _lossless_gain(source_size, output_size)
    metadata_details = {
        **final_metadata_report,
        "lossless_verification": final_verification,
        "lossless_optimization": {
            "selected_variant": str(selected["variant_id"]),
            "evaluated_variants": variant_evidence,
            "baseline_size": int(baseline["output_size"]) if baseline is not None else None,
            "best_size": output_size,
            "lossless_gain": gain,
        },
    }
    return {
        "scheme_id": PNG_LOSSLESS_SCHEME,
        "candidate_id": PNG_LOSSLESS_SCHEME,
        "display_name": "PNG 无损",
        "format": "PNG",
        "file_size": output_size,
        "width": width,
        "height": height,
        "output_path": str(published_path),
        "applicable_scene": _SCHEMES[0]["applicable_scene"],
        "recommended": False,
        "reason": "已从源文件生成，并通过正式文件零像素变化验证。",
        "status": "AVAILABLE",
        "output_sha256": str(final_verification["output_sha256"]),
        "artifact_identity": {
            "candidate_id": PNG_LOSSLESS_SCHEME,
            "source_sha256": str(final_verification["source_sha256"]),
            "output_sha256": str(final_verification["output_sha256"]),
            "lossless_verification_output_sha256": str(final_verification["output_sha256"]),
        },
        "direct_source_lineage": True,
        "metadata_details": metadata_details,
        "pixel_identical": bool(final_verification["pixel_identical"]),
        "pixel_diff_count": final_verification["pixel_diff_count"],
        "max_channel_diff": final_verification["max_channel_diff"],
        "lossless_verified": bool(final_verification["lossless_verified"]),
        "source_size": source_size,
        "output_size": output_size,
        "saved_bytes": saved_bytes,
        "saved_percent": saved_percent,
        "lossless_gain": gain,
        "alpha_optimized": bool(final_verification["alpha_optimized"]),
        "verification_status": str(final_verification["verification_status"]),
    }


def _basic_webp_verifier(data: bytes, *, expected_dimensions: tuple[int, int]) -> dict[str, Any]:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if str(image.format or "").upper() != "WEBP" or image.size != expected_dimensions:
            raise RuntimeError("WebP 候选格式或尺寸验证失败。")
    return {
        "format": "WEBP",
        "dimensions": {"width": expected_dimensions[0], "height": expected_dimensions[1]},
        "sha256": _sha256_bytes(data),
        "size_bytes": len(data),
    }


def _generate_verified_webp_candidate(
    source_file: Path,
    output_root: Path,
    *,
    source_filename: str,
    source: dict[str, Any],
    source_data: bytes,
    displayed: Image.Image,
    moment: datetime,
) -> dict[str, Any]:
    width, height = displayed.size
    encoded = _encode_webp_candidate(displayed, source)
    requested_path = build_output_path(
        output_root,
        source_filename,
        FEATURE_COMPRESSION,
        ".webp",
        trusted_original_filename=source_filename,
        moment=moment,
    )
    published_path, metadata_report, verified = publish_image_bytes_with_metadata(
        encoded,
        requested_path,
        source_data=source_data,
        normalize_orientation=True,
        collision_base_path=requested_path,
        verify_private=lambda data: _basic_webp_verifier(data, expected_dimensions=(width, height)),
    )
    verification = verify_lossless_webp_files(
        source_file,
        published_path,
        metadata_report=metadata_report,
    )
    if not verification["lossless_verified"]:
        published_path.unlink(missing_ok=True)
        raise CompressionRuntimeError(
            "WEBP_LOSSLESS_VERIFICATION_FAILED",
            "WebP 候选未通过零像素变化与元数据验证。",
            TechnicalStatus.CANNOT_MEET_SAFELY,
        )
    source_size = int(source["size_bytes"])
    output_size = int(verified["size_bytes"])
    saved_bytes, saved_percent, gain = _lossless_gain(source_size, output_size)
    return {
        "scheme_id": WEBP_LOSSLESS_SCHEME,
        "candidate_id": WEBP_LOSSLESS_SCHEME,
        "display_name": "WebP 无损",
        "format": "WEBP",
        "file_size": output_size,
        "width": width,
        "height": height,
        "output_path": str(published_path),
        "applicable_scene": _WEBP_SCHEME["applicable_scene"],
        "recommended": False,
        "reason": "已从源文件生成，并通过正式文件零像素变化验证。",
        "status": "AVAILABLE",
        "output_sha256": str(verification["output_sha256"]),
        "artifact_identity": {
            "candidate_id": WEBP_LOSSLESS_SCHEME,
            "source_sha256": str(verification["source_sha256"]),
            "output_sha256": str(verification["output_sha256"]),
            "lossless_verification_output_sha256": str(verification["output_sha256"]),
        },
        "direct_source_lineage": True,
        "metadata_details": {
            **metadata_report,
            "lossless_verification": verification,
            "lossless_optimization": {
                "selected_variant": "webp_lossless_method_6",
                "best_size": output_size,
                "lossless_gain": gain,
            },
        },
        "quality_gate": {
            "version": "WEBP_LOSSLESS_V1",
            "status": "PASS",
            "checks": {
                "pixel_identical": bool(verification["pixel_identical"]),
                "alpha_verified": bool(verification["alpha_preserved"]),
                "metadata_verified": bool(verification["metadata_verified"]),
            },
            "failure_reasons": [],
        },
        "pixel_identical": bool(verification["pixel_identical"]),
        "pixel_diff_count": verification["pixel_diff_count"],
        "max_channel_diff": verification["max_channel_diff"],
        "lossless_verified": bool(verification["lossless_verified"]),
        "source_size": source_size,
        "output_size": output_size,
        "saved_bytes": saved_bytes,
        "saved_percent": saved_percent,
        "lossless_gain": gain,
        "alpha_optimized": False,
        "verification_status": str(verification["verification_status"]),
    }


def _unavailable_candidate(scheme: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "scheme_id": scheme["scheme_id"],
        "candidate_id": scheme["scheme_id"],
        "display_name": scheme["display_name"],
        "format": scheme["format"],
        "file_size": None,
        "width": None,
        "height": None,
        "output_path": None,
        "applicable_scene": scheme["applicable_scene"],
        "recommended": False,
        "reason": reason,
        "status": "NOT_APPLICABLE",
        "output_sha256": None,
        "artifact_identity": {
            "candidate_id": scheme["scheme_id"],
            "source_sha256": None,
            "output_sha256": None,
        },
        "direct_source_lineage": True,
        "metadata_details": {},
        "quality_gate": {
            "version": JPG_QUALITY_GATE_VERSION,
            "status": "NOT_APPLICABLE",
            "failure_reasons": ["SOURCE_HAS_REAL_TRANSPARENCY"],
        },
    }


def _source_candidate(source: dict[str, Any], *, width: int, height: int) -> dict[str, Any]:
    return {
        "scheme_id": KEEP_ORIGINAL_SCHEME,
        "candidate_id": KEEP_ORIGINAL_SCHEME,
        "display_name": "保留原图",
        "format": "JPG" if source["format"] == "JPEG" else str(source["format"]),
        "file_size": int(source["size_bytes"]),
        "width": width,
        "height": height,
        "output_path": str(source["path"]),
        "applicable_scene": "原图已经是当前质量与体积约束下的最优交付结果",
        "recommended": False,
        "reason": "没有内部候选同时通过质量安全门并获得正向体积收益。",
        "status": "AVAILABLE",
        "output_sha256": str(source["sha256"]),
        "artifact_identity": {
            "candidate_id": KEEP_ORIGINAL_SCHEME,
            "source_sha256": str(source["sha256"]),
            "output_sha256": str(source["sha256"]),
        },
        "direct_source_lineage": True,
        "metadata_details": {},
        "quality_gate": {
            "version": SINGLE_WINNER_POLICY,
            "status": "PASS",
            "checks": {"source_identity": True},
            "failure_reasons": [],
        },
        "saved_bytes": 0,
        "saved_percent": 0.0,
    }


def _evaluate_jpg_trial(
    *,
    displayed: Image.Image,
    source: dict[str, Any],
    source_data: bytes,
    source_snapshot: Path,
    evaluation_root: Path,
    width: int,
    height: int,
    quality: int,
    subsampling: int,
    encode_index: int,
    size_profile_id: str,
    content_risk_id: str,
    alpha_handling: dict[str, Any] | None = None,
    full_resolution: bool = False,
    _source_analysis: Any | None = None,
) -> dict[str, Any]:
    scheme = _jpg_scheme(quality, subsampling)
    started = time.perf_counter()
    encoded = _encode_jpg_candidate(
        displayed,
        source,
        quality=quality,
        subsampling=subsampling,
    )
    encoded_at = time.perf_counter()

    def verify_private(data: bytes) -> dict[str, Any]:
        with Image.open(io.BytesIO(data)) as verified_image:
            verified_image.load()
            actual_format = "JPEG" if verified_image.format == "JPG" else str(verified_image.format or "").upper()
            if actual_format != "JPEG" or verified_image.size != (width, height):
                raise RuntimeError("交付候选格式或尺寸验证失败。")
            return {
                "format": actual_format,
                "dimensions": {"width": verified_image.width, "height": verified_image.height},
                "sha256": _sha256_bytes(data),
                "size_bytes": len(data),
            }

    evaluation_path = evaluation_root / f"{encode_index:02d}-{scheme['scheme_id']}.jpg"
    published_path, metadata_report, verified = publish_image_bytes_with_metadata(
        encoded,
        evaluation_path,
        source_data=source_data,
        normalize_orientation=True,
        collision_base_path=evaluation_path,
        verify_private=verify_private,
    )
    persisted_at = time.perf_counter()
    quality_gate = evaluate_jpg_quality(
        source_snapshot,
        published_path,
        metadata_report=metadata_report,
        source_has_real_transparency=False,
        full_resolution=full_resolution,
        _decoded_source=displayed,
        _source_analysis=_source_analysis,
    )
    quality_passed = quality_gate["status"] == "PASS"
    return {
        "scheme_id": scheme["scheme_id"],
        "candidate_id": scheme["scheme_id"],
        "display_name": scheme["display_name"],
        "format": scheme["format"],
        "file_size": int(verified["size_bytes"]),
        "width": width,
        "height": height,
        "output_path": str(published_path),
        "applicable_scene": scheme["applicable_scene"],
        "recommended": False,
        "reason": "候选已直接从不可变 Source 快照生成并完成 JPG 质量安全门检查。",
        "status": "AVAILABLE" if quality_passed else "QUALITY_REJECTED",
        "output_sha256": str(verified["sha256"]),
        "artifact_identity": {
            "candidate_id": scheme["scheme_id"],
            "source_sha256": str(source["sha256"]),
            "output_sha256": str(verified["sha256"]),
        },
        "direct_source_lineage": True,
        "metadata_details": {
            **metadata_report,
            **({"alpha_handling": dict(alpha_handling)} if alpha_handling else {}),
        },
        "quality_gate": quality_gate,
        "search_details": {
            "size_profile": size_profile_id,
            "content_risk_profile": content_risk_id,
            "quality": quality,
            "subsampling": "4:4:4" if subsampling == 0 else "4:2:0",
            "optimize": True,
            "progressive": False,
            "encode_index": encode_index,
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "encode_seconds": round(encoded_at - started, 6),
            "metadata_publish_seconds": round(persisted_at - encoded_at, 6),
            "quality_gate_seconds": round(time.perf_counter() - persisted_at, 6),
        },
    }


def _large_jpg_candidates(**kwargs) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from .jpg_large_search import plan_large_jpg_search

    started = time.perf_counter()
    order = tuple(CONTENT_RISK_PROFILE[kwargs["content_risk_id"]]["subsampling_order"])
    plans, roi_summary = plan_large_jpg_search(kwargs["displayed"], order)
    candidates: list[dict[str, Any]] = []
    evaluated: dict[tuple[int, int], dict[str, Any]] = {}
    boundaries = {}
    trial_args = {key: value for key, value in kwargs.items() if key not in {"size_profile", "lossless_bytes"}}
    target_bytes = min(int(kwargs["source"]["size_bytes"]), int(kwargs["lossless_bytes"]))

    def evaluate(quality, mode):
        key = (quality, mode)
        if key not in evaluated:
            candidate = _evaluate_jpg_trial(**trial_args, quality=quality, subsampling=mode, full_resolution=True,
                                            encode_index=len(candidates) + 1)
            candidate["search_details"]["policy"] = "LARGE_NATIVE_ROI_V1"
            evaluated[key] = candidate
            candidates.append(candidate)
        return evaluated[key]

    def passed(candidate):
        return candidate["quality_gate"]["status"] == "PASS"

    def refine(mode, safe, failed):
        while safe - failed > 1:
            middle = (safe + failed) // 2
            if passed(evaluate(middle, mode)):
                safe = middle
            else:
                failed = middle
        boundaries[mode] = {"last_pass": safe, "first_fail": failed, "scope": "FULL_RESOLUTION"}
        return safe

    for plan in plans:
        mode, quality = plan["subsampling"], plan["quality"]
        if not passed(evaluate(quality, mode)):
            failed, step = quality, 2
            while quality < 100:
                quality = min(100, quality + step)
                if passed(evaluate(quality, mode)):
                    refine(mode, quality, failed)
                    break
                failed, step = quality, step * 2
            else:
                boundaries[mode] = {"last_pass": None, "first_fail": 100, "scope": "FULL_RESOLUTION"}

    # Each mode has already been searched to an adjacent native-ROI boundary.
    # If a full-size PASS beats the current lossless result, that is a useful
    # winner (stop condition A); do not repeat the entire ROI search at full size.
    # ROI predictions may be conservative or wrong. If they give no useful
    # winner, continue full-size coarse/fine exploration before retaining PNG.
    refined = set(boundaries)
    stop_reason = "FULL_RESOLUTION_REJECTED_BOTH_MODES"
    while True:
        passing = [item for item in candidates if passed(item)]
        if not passing:
            break
        best = min(passing, key=lambda item: int(item["file_size"]))
        if int(best["file_size"]) < target_bytes and _has_winner_size_benefit(
            best, source_size=int(kwargs["source"]["size_bytes"]), size_profile=kwargs["size_profile"],
        ):
            stop_reason = "SMALLER_FULL_RESOLUTION_PASS_AT_NATIVE_ROI_BOUNDARY"
            break
        mode = 0 if best["search_details"]["subsampling"] == "4:4:4" else 2
        if mode in refined:
            remaining = [item for item in passing if (0 if item["search_details"]["subsampling"] == "4:4:4" else 2) not in refined]
            if not remaining:
                stop_reason = "FULL_RESOLUTION_PASS_FAIL_BOUNDARY_NO_SMALLER_WINNER"
                break
            best = min(remaining, key=lambda item: int(item["file_size"]))
            mode = 0 if best["search_details"]["subsampling"] == "4:4:4" else 2
        safe, step = int(best["search_details"]["quality"]), 1
        while safe > 1:
            quality = max(1, safe - step)
            if passed(evaluate(quality, mode)):
                safe, step = quality, step * 2
            else:
                safe = refine(mode, safe, quality)
                break
        if safe == 1:
            boundaries[mode] = {"last_pass": 1, "first_fail": None, "scope": "FULL_RESOLUTION_FLOOR"}
        refined.add(mode)

    passing = [item for item in candidates if passed(item)]
    lowest = min(passing, key=lambda item: item["search_details"]["quality"], default=None)
    best = min(passing, key=lambda item: item["file_size"], default=None)
    return candidates, {
        "policy": "LARGE_NATIVE_ROI_V1", "size_profile": kwargs["size_profile_id"],
        "content_risk_profile": kwargs["content_risk_id"], "quality_floor": 1,
        "max_encodings": 200, "encode_count": len(candidates), "full_image_encode_count": len(candidates),
        "subsampling_order": ["4:4:4" if mode == 0 else "4:2:0" for mode in order],
        "lowest_safe_quality": lowest["search_details"]["quality"] if lowest else None,
        "lowest_safe_subsampling": lowest["search_details"]["subsampling"] if lowest else None,
        "best_passing_bytes": best["file_size"] if best else None,
        "entry_reason": "LARGE_LOW_GAIN_CONTINUE_SEARCH",
        "low_gain_max_saving_percent": LARGE_LOW_GAIN_MAX_SAVING_PERCENT,
        "stop_reason": stop_reason,
        "lowest_safe_quality_scope": "SEARCHED_NATIVE_ROI_BOUNDARY_WITH_FULL_RESOLUTION_VALIDATION",
        "roi_boundaries": [dict(plan) for plan in plans],
        "boundaries": {"4:4:4" if mode == 0 else "4:2:0": evidence for mode, evidence in boundaries.items()},
        "roi_probe": roi_summary, "elapsed_seconds": round(time.perf_counter() - started, 6),
    }


def _adaptive_jpg_candidates(
    *,
    displayed: Image.Image,
    source: dict[str, Any],
    source_data: bytes,
    source_snapshot: Path,
    evaluation_root: Path,
    width: int,
    height: int,
    size_profile_id: str,
    size_profile: dict[str, Any],
    content_risk_id: str,
    lossless_bytes: int | None = None,
    alpha_handling: dict[str, Any] | None = None,
    _source_analysis: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lossless_gain = (1.0 - lossless_bytes / int(source["size_bytes"])) * 100.0 if lossless_bytes is not None else None
    if size_profile_id in {"LARGE", "VERY_LARGE"} and (
        lossless_gain is not None and lossless_gain < LARGE_LOW_GAIN_MAX_SAVING_PERCENT
    ):
        return _large_jpg_candidates(
            displayed=displayed, source=source, source_data=source_data, source_snapshot=source_snapshot,
            evaluation_root=evaluation_root, width=width, height=height, size_profile_id=size_profile_id,
            size_profile=size_profile, content_risk_id=content_risk_id,
            lossless_bytes=lossless_bytes if lossless_bytes is not None else int(source["size_bytes"]),
            alpha_handling=alpha_handling,
            _source_analysis=_source_analysis,
        )
    started = time.perf_counter()
    candidates: list[dict[str, Any]] = []
    evaluated: dict[tuple[int, int], dict[str, Any]] = {}
    max_encodings = int(size_profile["max_encodings"])
    quality_floor = int(size_profile["quality_floor"])
    coarse = [
        int(value)
        for value in size_profile["coarse_qualities"]
        if int(value) >= quality_floor
    ]
    subsampling_order = tuple(CONTENT_RISK_PROFILE[content_risk_id]["subsampling_order"])

    def evaluate(quality: int, subsampling: int) -> dict[str, Any] | None:
        key = (quality, subsampling)
        if key in evaluated:
            return evaluated[key]
        if len(candidates) >= max_encodings:
            return None
        candidate = _evaluate_jpg_trial(
            displayed=displayed,
            source=source,
            source_data=source_data,
            source_snapshot=source_snapshot,
            evaluation_root=evaluation_root,
            width=width,
            height=height,
            quality=quality,
            subsampling=subsampling,
            encode_index=len(candidates) + 1,
            size_profile_id=size_profile_id,
            content_risk_id=content_risk_id,
            alpha_handling=alpha_handling,
            full_resolution=True,
            _source_analysis=_source_analysis,
        )
        evaluated[key] = candidate
        candidates.append(candidate)
        return candidate

    # Preserve A01's two JPEG concepts as real Source-derived probes.
    evaluate(95, 0)
    evaluate(85, 0)

    for mode_index, subsampling in enumerate(subsampling_order):
        pass_quality: int | None = None
        fail_below: int | None = None
        # Risky secondary chroma mode is intentionally limited, but never judged
        # by a different quality threshold.
        mode_limit = max_encodings
        if mode_index == 0 and len(subsampling_order) > 1:
            mode_limit = max(len(candidates), max_encodings - 2)
        if (
            mode_index > 0
            and CONTENT_RISK_PROFILE[content_risk_id]["secondary_search"] == "LIMITED"
        ):
            mode_limit = min(max_encodings, len(candidates) + 3)
        for quality in coarse:
            if len(candidates) >= mode_limit:
                break
            candidate = evaluate(quality, int(subsampling))
            if candidate is None:
                break
            if candidate["quality_gate"]["status"] == "PASS":
                pass_quality = quality if pass_quality is None else min(pass_quality, quality)
            elif pass_quality is not None and quality < pass_quality:
                fail_below = quality
                break
        if pass_quality is None or fail_below is None:
            continue
        low = max(quality_floor, fail_below + 1)
        high = pass_quality - 1
        while low <= high and len(candidates) < mode_limit:
            quality = (low + high) // 2
            candidate = evaluate(quality, int(subsampling))
            if candidate is None:
                break
            if candidate["quality_gate"]["status"] == "PASS":
                pass_quality = quality
                high = quality - 1
            else:
                low = quality + 1

    passing = [candidate for candidate in candidates if candidate["quality_gate"]["status"] == "PASS"]
    lowest_safe = min(
        passing,
        key=lambda item: (
            int(item["search_details"]["quality"]),
            int(item["file_size"]),
        ),
        default=None,
    )
    best_size = min(passing, key=lambda item: int(item["file_size"]), default=None)
    summary = {
        "policy": "BOUNDED_COARSE_TO_FINE_V1",
        "size_profile": size_profile_id,
        "content_risk_profile": content_risk_id,
        "max_encodings": max_encodings,
        "encode_count": len(candidates),
        "quality_floor": quality_floor,
        "subsampling_order": ["4:4:4" if value == 0 else "4:2:0" for value in subsampling_order],
        "lowest_safe_quality": (
            int(lowest_safe["search_details"]["quality"])
            if lowest_safe is not None
            else None
        ),
        "lowest_safe_subsampling": (
            str(lowest_safe["search_details"]["subsampling"])
            if lowest_safe is not None
            else None
        ),
        "best_passing_bytes": int(best_size["file_size"]) if best_size is not None else None,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
    }
    return candidates, summary


def _has_winner_size_benefit(
    candidate: dict[str, Any],
    *,
    source_size: int,
    size_profile: dict[str, Any],
) -> bool:
    output_size = int(candidate.get("file_size") or source_size)
    saved_bytes = source_size - output_size
    if saved_bytes <= 0:
        return False
    if candidate.get("format") in {"PNG", "WEBP"}:
        return True
    saved_percent = (saved_bytes / source_size * 100.0) if source_size else 0.0
    return bool(
        saved_bytes >= int(size_profile["min_jpg_saved_bytes"])
        and saved_percent >= float(size_profile["min_jpg_saved_percent"])
    )


def _publish_winner(
    candidate: dict[str, Any],
    *,
    source_file: Path,
    output_root: Path,
    source_filename: str,
    source: dict[str, Any],
    has_real_transparency: bool,
    moment: datetime,
    jpg_reference_image: Image.Image | None = None,
    _source_analysis: Any | None = None,
) -> dict[str, Any]:
    evaluation_path = Path(str(candidate["output_path"])).resolve()
    evaluation_data = evaluation_path.read_bytes()
    evaluation_sha256 = _sha256_bytes(evaluation_data)
    if evaluation_sha256 != candidate.get("output_sha256"):
        raise CompressionRuntimeError(
            "CANDIDATE_IDENTITY_MISMATCH",
            "内部候选在正式发布前发生变化。",
            TechnicalStatus.CANNOT_MEET_SAFELY,
        )
    suffix = {"PNG": ".png", "WEBP": ".webp", "JPG": ".jpg"}[str(candidate["format"])]
    requested_path = build_output_path(
        output_root,
        source_filename,
        FEATURE_COMPRESSION,
        suffix,
        trusted_original_filename=source_filename,
        moment=moment,
    )
    publish_integrity: dict[str, Any] = {}

    def verify_exact_winner(data: bytes) -> dict[str, Any]:
        if _sha256_bytes(data) != evaluation_sha256:
            raise RuntimeError("内部胜出候选在正式发布时发生变化。")
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            actual_format = "JPEG" if image.format == "JPG" else str(image.format or "").upper()
            expected_format = {"JPG": "JPEG", "PNG": "PNG", "WEBP": "WEBP"}[str(candidate["format"])]
            if actual_format != expected_format or image.size != (candidate["width"], candidate["height"]):
                raise RuntimeError("正式胜出结果格式或尺寸验证失败。")
        return {
            "format": actual_format,
            "dimensions": {"width": image.width, "height": image.height},
            "sha256": _sha256_bytes(data),
            "size_bytes": len(data),
        }

    published_path, verified = publish_prepared_bytes_no_overwrite(
        evaluation_data,
        _target_candidates(requested_path),
        verify_private=verify_exact_winner,
        integrity_report=publish_integrity,
    )
    metadata_report = {
        **dict(candidate.get("metadata_details") or {}),
        "winner_publish_integrity": publish_integrity,
    }
    is_lossless = candidate["format"] in {"PNG", "WEBP"}
    if is_lossless:
        verifier = verify_lossless_png_files if candidate["format"] == "PNG" else verify_lossless_webp_files
        final_verification = verifier(
            source_file,
            published_path,
            metadata_report=metadata_report,
        )
        if not final_verification["lossless_verified"]:
            published_path.unlink(missing_ok=True)
            raise CompressionRuntimeError(
                f"{candidate['format']}_FORMAL_FILE_VERIFICATION_FAILED",
                f"{candidate['format']} 正式胜出结果未通过严格零像素变化验证。",
                TechnicalStatus.CANNOT_MEET_SAFELY,
            )
        candidate["metadata_details"] = {
            **metadata_report,
            "lossless_verification": final_verification,
        }
        candidate["output_sha256"] = str(final_verification["output_sha256"])
        candidate["pixel_identical"] = bool(final_verification["pixel_identical"])
        candidate["pixel_diff_count"] = int(final_verification["pixel_diff_count"])
        candidate["max_channel_diff"] = int(final_verification["max_channel_diff"])
        candidate["lossless_verified"] = bool(final_verification["lossless_verified"])
        candidate["verification_status"] = str(final_verification["verification_status"])
        candidate["quality_gate"] = {
            "version": "A02_STRICT_LOSSLESS_V1" if candidate["format"] == "PNG" else "WEBP_LOSSLESS_V1",
            "status": "PASS",
            "checks": {
                "pixel_identical": bool(final_verification["pixel_identical"]),
                "alpha_verified": bool(final_verification["alpha_preserved"]),
                "metadata_verified": bool(final_verification["metadata_verified"]),
            },
            "failure_reasons": [],
        }
    else:
        final_gate = evaluate_jpg_quality(
            source_file,
            published_path,
            metadata_report=metadata_report,
            source_has_real_transparency=False,
            full_resolution=True,
            _decoded_source=jpg_reference_image,
            _source_analysis=_source_analysis,
        )
        if final_gate["status"] != "PASS":
            published_path.unlink(missing_ok=True)
            raise CompressionRuntimeError(
                "JPG_FORMAL_QUALITY_GATE_FAILED",
                "JPG 正式胜出结果未通过质量安全门。",
                TechnicalStatus.CANNOT_MEET_SAFELY,
            )
        candidate["metadata_details"] = metadata_report
        candidate["quality_gate"] = final_gate
        candidate["output_sha256"] = str(verified["sha256"])

    candidate["output_path"] = str(published_path)
    candidate["file_size"] = int(verified["size_bytes"])
    candidate["output_size"] = int(verified["size_bytes"])
    candidate["recommended"] = True
    candidate["status"] = "AVAILABLE"
    candidate["artifact_identity"] = {
        "candidate_id": str(candidate["candidate_id"]),
        "source_sha256": str(source["sha256"]),
        "output_sha256": str(candidate["output_sha256"]),
        **(
            {"lossless_verification_output_sha256": str(candidate["output_sha256"])}
            if is_lossless
            else {}
        ),
    }
    return candidate


def generate_delivery_candidates(
    source_path: str | Path,
    output_directory: str | Path,
    *,
    source_filename: str,
    moment: datetime,
    target_format: str | None = SMART_COMPRESSION_TARGET_FORMAT,
) -> dict[str, Any]:
    """Run smart, preserve-format, or one explicitly requested format route."""

    source_file = Path(source_path).resolve()
    output_root = Path(output_directory).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    normalized_target = str(target_format or SMART_COMPRESSION_TARGET_FORMAT).strip().upper()
    if normalized_target not in SUPPORTED_TARGET_FORMATS:
        raise CompressionRuntimeError(
            "TARGET_FORMAT_INVALID",
            "目标格式仅支持 SMART_COMPRESSION、PRESERVE_FORMAT、JPEG、PNG 或 WEBP。",
        )
    source = read_image_info(source_file, allow_webp=True)
    source_format = str(source["format"])
    policy_target = (
        source_format
        if normalized_target in {SMART_COMPRESSION_TARGET_FORMAT, PRESERVE_FORMAT_TARGET_FORMAT}
        else normalized_target
    )
    explicit_conversion = (
        normalized_target not in {SMART_COMPRESSION_TARGET_FORMAT, PRESERVE_FORMAT_TARGET_FORMAT}
        and policy_target != source_format
    )
    source_sha256 = str(source["sha256"])
    source_size = int(source["size_bytes"])
    source_data = _require_source_identity(
        source_file,
        registered_sha256=source_sha256,
        registered_size=source_size,
    )
    try:
        with Image.open(io.BytesIO(source_data)) as opened:
            if bool(getattr(opened, "is_animated", False)) or int(getattr(opened, "n_frames", 1)) != 1:
                raise CompressionRuntimeError(
                    "MULTI_FRAME_SOURCE_UNSUPPORTED",
                    "多帧图片不在当前交付优化安全范围内。",
                    TechnicalStatus.CANNOT_MEET_SAFELY,
                )
            opened.load()
            if opened.mode not in {"1", "L", "LA", "P", "RGB", "RGBA"}:
                raise CompressionRuntimeError(
                    "SOURCE_COLOR_MODE_UNSUPPORTED",
                    "当前交付优化仅支持单帧 8-bit 灰度、RGB 或 RGBA 图片。",
                    TechnicalStatus.CANNOT_MEET_SAFELY,
                )
            displayed = ImageOps.exif_transpose(opened).copy()
    except CompressionRuntimeError:
        raise
    except Exception as exc:
        raise CompressionRuntimeError("SOURCE_DECODE_FAILED", f"图片无法完整解码：{exc}") from exc

    width, height = displayed.size
    has_real_transparency = _real_transparency(displayed)
    smart_opaque_png = bool(
        normalized_target == SMART_COMPRESSION_TARGET_FORMAT
        and source_format == "PNG"
        and not has_real_transparency
    )
    jpg_reference = _jpg_reference_image(displayed) if policy_target == "JPEG" or smart_opaque_png else None
    alpha_handling = {
        "source_has_real_transparency": has_real_transparency,
        "action": "FLATTEN_ON_WHITE" if policy_target == "JPEG" and has_real_transparency else "PRESERVE",
        "background_rgb": [255, 255, 255] if policy_target == "JPEG" and has_real_transparency else None,
    }
    size_profile_id, size_profile = _size_search_profile(source_size)
    content_risk_id, content_risk_metrics = _content_risk_profile(
        jpg_reference if jpg_reference is not None else displayed,
        has_real_transparency=False if jpg_reference is not None else has_real_transparency,
    )
    candidates: list[dict[str, Any]] = []
    jpg_search_summary: dict[str, Any] = {
        "policy": "NOT_APPLICABLE",
        "size_profile": size_profile_id,
        "content_risk_profile": content_risk_id,
        "max_encodings": int(size_profile["max_encodings"]),
        "encode_count": 0,
        "lowest_safe_quality": None,
        "lowest_safe_subsampling": None,
        "best_passing_bytes": None,
        "elapsed_seconds": 0.0,
    }
    source_candidate = _source_candidate(source, width=width, height=height)
    source_analysis_context = (
        prepare_jpg_source_analysis(jpg_reference, full_resolution=True)
        if jpg_reference is not None
        else nullcontext(None)
    )
    with source_analysis_context as jpg_source_analysis, tempfile.TemporaryDirectory(
        prefix=".hdde-a03-candidates-", dir=output_root,
    ) as temporary_name:
        evaluation_root = Path(temporary_name)
        source_snapshot = evaluation_root / f"source-snapshot{source_file.suffix.lower() or '.img'}"
        source_snapshot.write_bytes(source_data)
        if _sha256_bytes(source_snapshot.read_bytes()) != source_sha256:
            raise CompressionRuntimeError(
                "SOURCE_SNAPSHOT_WRITE_FAILED",
                "Source 私有快照未能保持已绑定的内容身份。",
                TechnicalStatus.CANNOT_MEET_SAFELY,
            )
        png_candidate = None
        if policy_target == "PNG" or smart_opaque_png:
            png_candidate = _generate_verified_png_candidate(
                source_snapshot,
                evaluation_root,
                source_filename=source_filename,
                source=source,
                source_data=source_data,
                displayed=displayed,
                moment=moment,
            )
            png_candidate["quality_gate"] = {
                "version": "A02_STRICT_LOSSLESS_V1",
                "status": "PASS",
                "checks": {
                    "pixel_identical": bool(png_candidate["pixel_identical"]),
                    "alpha_verified": bool(
                        png_candidate["metadata_details"]["lossless_verification"].get("alpha_preserved")
                    ),
                    "metadata_verified": bool(
                        png_candidate["metadata_details"]["lossless_verification"].get("metadata_verified")
                    ),
                },
                "failure_reasons": [],
            }
            candidates.append(png_candidate)
        if smart_opaque_png:
            jpg_candidates, jpg_search_summary = _adaptive_jpg_candidates(
                displayed=jpg_reference,
                source=source,
                source_data=source_data,
                source_snapshot=source_snapshot,
                evaluation_root=evaluation_root,
                width=width,
                height=height,
                size_profile_id=size_profile_id,
                size_profile=size_profile,
                content_risk_id=content_risk_id,
                lossless_bytes=int(png_candidate["file_size"]),
                alpha_handling=alpha_handling,
                _source_analysis=jpg_source_analysis,
            )
            candidates.extend(jpg_candidates)
        elif policy_target == "WEBP":
            candidates.append(_generate_verified_webp_candidate(
                source_snapshot,
                evaluation_root,
                source_filename=source_filename,
                source=source,
                source_data=source_data,
                displayed=displayed,
                moment=moment,
            ))
        elif policy_target == "JPEG":
            jpg_candidates, jpg_search_summary = _adaptive_jpg_candidates(
                displayed=jpg_reference,
                source=source,
                source_data=source_data,
                source_snapshot=source_snapshot,
                evaluation_root=evaluation_root,
                width=width,
                height=height,
                size_profile_id=size_profile_id,
                size_profile=size_profile,
                content_risk_id=content_risk_id,
                lossless_bytes=source_size,
                alpha_handling=alpha_handling,
                _source_analysis=jpg_source_analysis,
            )
            candidates.extend(jpg_candidates)

        eligible = [
            item for item in candidates
            if item["status"] == "AVAILABLE"
            and item.get("quality_gate", {}).get("status") == "PASS"
            and (explicit_conversion or _has_winner_size_benefit(
                item,
                source_size=source_size,
                size_profile=size_profile,
            ))
        ]
        if eligible:
            winner = min(
                eligible,
                key=lambda item: (
                    int(item["file_size"]),
                    str(item["scheme_id"]),
                ),
            )
            _require_source_identity(
                source_file,
                registered_sha256=source_sha256,
                registered_size=source_size,
            )
            winner = _publish_winner(
                winner,
                source_file=source_snapshot,
                output_root=output_root,
                source_filename=source_filename,
                source=source,
                has_real_transparency=has_real_transparency,
                moment=moment,
                jpg_reference_image=jpg_reference,
                _source_analysis=jpg_source_analysis,
            )
            saved_bytes, saved_percent, _gain = _lossless_gain(
                int(source["size_bytes"]), int(winner["file_size"])
            )
            winner["saved_bytes"] = saved_bytes
            winner["saved_percent"] = saved_percent
            recommendation_reason = (
                f"{winner['display_name']}通过质量安全门，并在合格候选中体积最小，"
                f"较原图节省 {saved_percent:.2f}%。"
            ) if saved_bytes > 0 else f"{policy_target} 转换完成，质量检查通过；最终文件未变小，未获得压缩收益。"
            winner["reason"] = recommendation_reason
        else:
            if explicit_conversion:
                target_label = "JPG" if policy_target == "JPEG" else policy_target
                raise CompressionRuntimeError(
                    f"{target_label}_NO_VALID_CANDIDATE",
                    f"未找到通过质量检查的 {target_label}，未生成转换结果。",
                    TechnicalStatus.CANNOT_MEET_SAFELY,
                )
            _require_source_identity(
                source_file,
                registered_sha256=source_sha256,
                registered_size=source_size,
            )
            winner = source_candidate
            any_target_pass = any(
                item.get("quality_gate", {}).get("status") == "PASS"
                for item in candidates
            )
            source_candidate["reason"] = (
                "通过质量安全门的同格式候选未获得足够体积收益，已保留原图。"
                if any_target_pass
                else "没有内部候选同时通过质量安全门并获得有效体积收益，已保留原图。"
            )
            recommendation_reason = str(source_candidate["reason"])
            winner["recommended"] = True

        winner_output_format = {
            "JPG": "JPEG",
            "PNG": "PNG",
            "WEBP": "WEBP",
        }.get(str(winner.get("format") or ""), source_format)
        format_conversion = winner_output_format != source_format

        smart_summary = ""
        smart_details: dict[str, Any] = {
            "comparison_performed": smart_opaque_png,
            "png_candidate_bytes": int(png_candidate["file_size"]) if png_candidate is not None else None,
            "jpeg_candidate_bytes": None,
            "jpeg_gate_result": "NOT_RUN",
            "jpeg_rejection_reason": None,
        }
        if smart_opaque_png:
            jpg_items = [item for item in candidates if item.get("format") == "JPG"]
            passing_jpg = [item for item in jpg_items if item.get("quality_gate", {}).get("status") == "PASS"]
            best_jpg = min(
                passing_jpg or jpg_items,
                key=lambda item: int(item.get("file_size") or source_size),
                default=None,
            )
            if best_jpg is not None:
                smart_details["jpeg_candidate_bytes"] = int(best_jpg["file_size"])
                smart_details["jpeg_gate_result"] = str(best_jpg.get("quality_gate", {}).get("status") or "UNKNOWN")
            if winner_output_format == "JPEG":
                smart_summary = "智能压缩已在质量要求范围内选择更小的交付格式。"
            else:
                smart_summary = "已保持 PNG，未找到质量达标且更小的 JPG 结果。"
                if not passing_jpg:
                    reasons = sorted({
                        str(reason)
                        for item in jpg_items
                        for reason in item.get("quality_gate", {}).get("failure_reasons", [])
                        if reason
                    })
                    smart_details["jpeg_rejection_reason"] = ", ".join(reasons) or "JPEG_QUALITY_GATE_REJECTED"
                elif png_candidate is not None and int(best_jpg["file_size"]) >= int(png_candidate["file_size"]):
                    smart_details["jpeg_rejection_reason"] = "JPEG_NOT_SMALLER_THAN_PNG"
                else:
                    smart_details["jpeg_rejection_reason"] = "JPEG_GAIN_BELOW_MINIMUM"

        winner_scheme_id = str(winner["scheme_id"])
        for candidate in candidates:
            if candidate["scheme_id"] == winner_scheme_id:
                continue
            evaluation_sha256 = candidate.get("output_sha256")
            candidate["artifact_identity"] = {
                "candidate_id": str(candidate["candidate_id"]),
                "source_sha256": str(source_sha256),
                "evaluation_output_sha256": evaluation_sha256,
                "output_sha256": None,
            }
            candidate["output_path"] = None
            candidate["output_sha256"] = None
            if candidate["status"] == "AVAILABLE":
                candidate["status"] = "INTERNAL_ONLY"
            candidate["recommended"] = False

    return {
        "source": source,
        "target_format": normalized_target,
        "effective_target_format": winner_output_format,
        "format_conversion": format_conversion,
        "format_policy": (
            "SMART_SAFE_FORMAT_SELECTION"
            if normalized_target == SMART_COMPRESSION_TARGET_FORMAT
            else "PRESERVE_SOURCE_FORMAT"
            if normalized_target == PRESERVE_FORMAT_TARGET_FORMAT
            else "USER_SELECTED_TARGET_FORMAT"
        ),
        "smart_compression_summary": smart_summary,
        "smart_compression_details": smart_details,
        "alpha_handling": alpha_handling,
        "source_identity": {
            "sha256": source_sha256,
            "size_bytes": source_size,
            "binding": "SOURCE_BYTES_SNAPSHOT",
        },
        "source_candidate": source_candidate,
        "source_display_dimensions": {"width": width, "height": height},
        "source_has_real_transparency": has_real_transparency,
        "size_search_profile": {
            "profile_id": size_profile_id,
            **size_profile,
        },
        "content_risk_profile": {
            "profile_id": content_risk_id,
            "metrics": content_risk_metrics,
            **dict(CONTENT_RISK_PROFILE[content_risk_id]),
        },
        "jpg_search": jpg_search_summary,
        "candidates": candidates,
        "winner": winner,
        "winner_scheme_id": winner_scheme_id,
        "recommended_scheme_id": winner_scheme_id,
        "recommendation_reason": recommendation_reason,
        "selection_policy": SINGLE_WINNER_POLICY,
        "public_output_count": 0 if winner_scheme_id == KEEP_ORIGINAL_SCHEME else 1,
    }


__all__ = [
    "CONTENT_RISK_PROFILE",
    "DELIVERY_OPTIMIZATION_MODE",
    "JPG_BALANCED_SCHEME",
    "JPG_HIGH_QUALITY_SCHEME",
    "KEEP_ORIGINAL_SCHEME",
    "PNG_LOSSLESS_SCHEME",
    "SIZE_SEARCH_PROFILE",
    "SINGLE_WINNER_POLICY",
    "SUPPORTED_TARGET_FORMATS",
    "SMART_COMPRESSION_TARGET_FORMAT",
    "PRESERVE_FORMAT_TARGET_FORMAT",
    "WEBP_LOSSLESS_SCHEME",
    "generate_delivery_candidates",
]
