"""Engineering-safe HDDE high-definition base.

This module does not introduce a new resize engine or an enhancement model.
It composes the already frozen Pillow LANCZOS 4K executor with explicit source
alpha bypass, a strict no-new-pixel-risk gate, baseline fallback, and lossless
PNG delivery encoding.  It is intentionally not wired to UI, Task/Result/
Delivery, the processing center, Settings, or the formal output directory.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from engine.image_processing_routing.four_k_v1 import (
    FOUR_K_V1_ROUTE,
    FourKV1ProcessingError,
    inspect_4k_v1_source,
    process_4k_v1_image,
)


FORMAL_DATA_ROOT = Path(r"D:\影界文件")
DELIVERY_FORMAT = "PNG"
DELIVERY_COMPRESS_LEVEL = 6


class HDCoreSafeBaseError(RuntimeError):
    """Structured internal safe-base failure."""

    def __init__(self, code: str, stage: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pixel_sha256(path: Path) -> str:
    with Image.open(path) as opened:
        opened.load()
        normalized = ImageOps.exif_transpose(opened)
        payload = normalized.tobytes() + normalized.mode.encode("ascii") + repr(normalized.size).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _normalized_source(path: Path) -> tuple[Image.Image, bytes | None]:
    try:
        with Image.open(path) as opened:
            opened.load()
            icc = opened.info.get("icc_profile")
            image = ImageOps.exif_transpose(opened).copy()
    except Exception as exc:
        raise HDCoreSafeBaseError("SOURCE_DECODE_FAILED", "input", f"输入图片无法解码：{exc}") from exc
    return image, icc if isinstance(icc, bytes) and icc else None


def _gray_probe(image: Image.Image, maximum_edge: int = 512) -> np.ndarray:
    probe = image.convert("RGB")
    if max(probe.size) > maximum_edge:
        probe.thumbnail((maximum_edge, maximum_edge), Image.Resampling.LANCZOS)
    rgb = np.asarray(probe, dtype=np.float32) / 255.0
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


def diagnose_degradation(source_path: str | Path) -> dict[str, Any]:
    """Record non-semantic input facts without enabling a restoration brick."""

    source = Path(source_path)
    source_meta = inspect_4k_v1_source(source)
    image, _ = _normalized_source(source)
    gray = _gray_probe(image)
    dx = np.diff(gray, axis=1) if gray.shape[1] > 1 else np.zeros((gray.shape[0], 0), np.float32)
    dy = np.diff(gray, axis=0) if gray.shape[0] > 1 else np.zeros((0, gray.shape[1]), np.float32)
    laplacian = np.zeros_like(gray)
    if gray.shape[0] > 2 and gray.shape[1] > 2:
        laplacian[1:-1, 1:-1] = (
            4.0 * gray[1:-1, 1:-1]
            - gray[:-2, 1:-1]
            - gray[2:, 1:-1]
            - gray[1:-1, :-2]
            - gray[1:-1, 2:]
        )
    source_format = str(source_meta["input_format"]).upper()
    return {
        "status": "MEASUREMENTS_ONLY_NO_RESTORATION_TRIGGER",
        "semantic_detection_performed": False,
        "restoration_brick_enabled": False,
        "srmd_enabled": False,
        "input_width": source_meta["input_width"],
        "input_height": source_meta["input_height"],
        "input_format": source_format,
        "has_alpha": source_meta["has_alpha"],
        "processing_disposition": source_meta["processing_disposition"],
        "target_width": source_meta["target_width"],
        "target_height": source_meta["target_height"],
        "lossy_codec_present": source_format in {"JPEG", "JPG", "WEBP"},
        "mean_absolute_horizontal_gradient": round(float(np.mean(np.abs(dx))) if dx.size else 0.0, 8),
        "mean_absolute_vertical_gradient": round(float(np.mean(np.abs(dy))) if dy.size else 0.0, 8),
        "laplacian_rms": round(float(np.sqrt(np.mean(laplacian * laplacian))), 8),
        "interpretation": "Measurements are diagnostic facts only; no blur/noise/compression claim or treatment is inferred.",
    }


def _expected_source_alpha(source: Image.Image, target_size: tuple[int, int]) -> Image.Image | None:
    if "A" not in source.getbands() and "transparency" not in source.info:
        return None
    return source.convert("RGBA").getchannel("A").resize(target_size, Image.Resampling.LANCZOS)


def _save_png_atomic(image: Image.Image, destination: Path, icc_profile: bytes | None) -> None:
    if destination.exists():
        raise HDCoreSafeBaseError("OUTPUT_CONFLICT", "delivery_encoding", f"输出已存在：{destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.stem}.", suffix=".tmp.png", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    options: dict[str, Any] = {
        "format": DELIVERY_FORMAT,
        "compress_level": DELIVERY_COMPRESS_LEVEL,
        "optimize": False,
    }
    if icc_profile:
        options["icc_profile"] = icc_profile
    try:
        image.save(temporary, **options)
        with Image.open(temporary) as verified:
            verified.load()
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def apply_source_alpha_bypass(
    source_path: str | Path,
    baseline_path: str | Path,
    candidate_path: str | Path,
) -> dict[str, Any]:
    """Reattach alpha derived only from the source channel at target geometry."""

    source, icc = _normalized_source(Path(source_path))
    baseline_path = Path(baseline_path)
    with Image.open(baseline_path) as opened:
        opened.load()
        baseline = opened.copy()
    expected_alpha = _expected_source_alpha(source, baseline.size)
    if expected_alpha is None:
        candidate = baseline.convert("RGB")
        alpha_status = "NOT_APPLICABLE"
    else:
        candidate = baseline.convert("RGBA")
        candidate.putalpha(expected_alpha)
        alpha_status = "SOURCE_CHANNEL_BYPASS_APPLIED"
    destination = Path(candidate_path)
    _save_png_atomic(candidate, destination, icc)
    return {
        "status": alpha_status,
        "candidate_path": str(destination.resolve()),
        "expected_alpha_present": expected_alpha is not None,
    }


def _alpha_gradient_mask(alpha: np.ndarray) -> np.ndarray:
    mask = np.zeros(alpha.shape, dtype=bool)
    if alpha.shape[1] > 1:
        horizontal = alpha[:, 1:] != alpha[:, :-1]
        mask[:, 1:] |= horizontal
        mask[:, :-1] |= horizontal
    if alpha.shape[0] > 1:
        vertical = alpha[1:, :] != alpha[:-1, :]
        mask[1:, :] |= vertical
        mask[:-1, :] |= vertical
    return mask


def _composite(rgb: np.ndarray, alpha: np.ndarray, background: int) -> np.ndarray:
    weight = alpha.astype(np.float32)[..., None] / 255.0
    return np.rint(rgb.astype(np.float32) * weight + float(background) * (1.0 - weight)).astype(np.uint8)


def _alpha_audit(
    source_path: Path,
    baseline_rgba: np.ndarray,
    candidate_rgba: np.ndarray,
    target_size: tuple[int, int],
) -> dict[str, Any]:
    source, _ = _normalized_source(source_path)
    expected_image = _expected_source_alpha(source, target_size)
    baseline_alpha = baseline_rgba[..., 3]
    candidate_alpha = candidate_rgba[..., 3]
    if expected_image is None:
        return {
            "status": "NOT_APPLICABLE",
            "source_alpha_present": False,
            "alpha_pixel_delta_count": 0,
            "maximum_alpha_delta": 0,
            "semi_transparent_pixel_count": 0,
            "alpha_gradient_pixel_count": 0,
            "protected_pixel_count": 0,
            "protected_rgb_changed_pixel_count": 0,
            "black_composite_maximum_delta": 0,
            "white_composite_maximum_delta": 0,
        }
    expected = np.asarray(expected_image, dtype=np.uint8)
    delta = np.abs(candidate_alpha.astype(np.int16) - expected.astype(np.int16))
    baseline_delta = np.abs(baseline_alpha.astype(np.int16) - expected.astype(np.int16))
    semi_transparent = np.logical_and(expected > 0, expected < 255)
    gradient = _alpha_gradient_mask(expected)
    protected = np.logical_or(semi_transparent, gradient)
    rgb_delta = np.max(
        np.abs(candidate_rgba[..., :3].astype(np.int16) - baseline_rgba[..., :3].astype(np.int16)),
        axis=2,
    )
    black_delta = np.max(
        np.abs(
            _composite(candidate_rgba[..., :3], candidate_alpha, 0).astype(np.int16)
            - _composite(baseline_rgba[..., :3], baseline_alpha, 0).astype(np.int16)
        )
    )
    white_delta = np.max(
        np.abs(
            _composite(candidate_rgba[..., :3], candidate_alpha, 255).astype(np.int16)
            - _composite(baseline_rgba[..., :3], baseline_alpha, 255).astype(np.int16)
        )
    )
    baseline_matches_source = bool(np.max(baseline_delta) == 0)
    candidate_matches_source = bool(np.max(delta) == 0)
    return {
        "status": "PASS" if baseline_matches_source and candidate_matches_source else "FAIL",
        "source_alpha_present": True,
        "baseline_matches_source_resized_alpha": baseline_matches_source,
        "candidate_matches_source_resized_alpha": candidate_matches_source,
        "alpha_pixel_delta_count": int(np.count_nonzero(delta)),
        "maximum_alpha_delta": int(np.max(delta)),
        "semi_transparent_pixel_count": int(np.count_nonzero(semi_transparent)),
        "alpha_gradient_pixel_count": int(np.count_nonzero(gradient)),
        "protected_pixel_count": int(np.count_nonzero(protected)),
        "protected_rgb_changed_pixel_count": int(np.count_nonzero(np.logical_and(protected, rgb_delta > 0))),
        "maximum_protected_rgb_delta": int(np.max(rgb_delta[protected])) if np.any(protected) else 0,
        "black_composite_maximum_delta": int(black_delta),
        "white_composite_maximum_delta": int(white_delta),
    }


def _high_frequency_l1(rgb: np.ndarray) -> float:
    gray = (
        0.299 * rgb[..., 0].astype(np.float32)
        + 0.587 * rgb[..., 1].astype(np.float32)
        + 0.114 * rgb[..., 2].astype(np.float32)
    )
    dx = np.abs(np.diff(gray, axis=1)) if gray.shape[1] > 1 else np.zeros((gray.shape[0], 0))
    dy = np.abs(np.diff(gray, axis=0)) if gray.shape[0] > 1 else np.zeros((0, gray.shape[1]))
    total = float(np.sum(dx, dtype=np.float64) + np.sum(dy, dtype=np.float64))
    count = dx.size + dy.size
    return 0.0 if count == 0 else total / count


def assess_baseline_risk(
    source_path: str | Path,
    baseline_path: str | Path,
    candidate_path: str | Path,
) -> dict[str, Any]:
    """Reject every candidate RGB deviation from the already-safe baseline."""

    baseline_path = Path(baseline_path)
    candidate_path = Path(candidate_path)
    with Image.open(baseline_path) as opened:
        opened.load()
        baseline_size = opened.size
        baseline_format = str(opened.format or "UNKNOWN").upper()
        baseline_rgba = np.asarray(opened.convert("RGBA"), dtype=np.uint8)
    with Image.open(candidate_path) as opened:
        opened.load()
        candidate_size = opened.size
        candidate_format = str(opened.format or "UNKNOWN").upper()
        candidate_rgba = np.asarray(opened.convert("RGBA"), dtype=np.uint8)
    geometry_pass = candidate_size == baseline_size
    if not geometry_pass:
        return {
            "status": "FAIL",
            "fallback_required": True,
            "reasons": ["GEOMETRY_CHANGED"],
            "baseline_size": list(baseline_size),
            "candidate_size": list(candidate_size),
        }
    rgb_delta = np.abs(candidate_rgba[..., :3].astype(np.int16) - baseline_rgba[..., :3].astype(np.int16))
    changed_pixels = np.max(rgb_delta, axis=2) > 0
    maximum_rgb_delta = int(np.max(rgb_delta))
    baseline_hf = _high_frequency_l1(baseline_rgba[..., :3])
    candidate_hf = _high_frequency_l1(candidate_rgba[..., :3])
    alpha = _alpha_audit(Path(source_path), baseline_rgba, candidate_rgba, baseline_size)
    reasons: list[str] = []
    if maximum_rgb_delta != 0:
        reasons.append("RGB_DIFFERS_FROM_SAFE_BASELINE")
    if baseline_format != DELIVERY_FORMAT or candidate_format != DELIVERY_FORMAT:
        reasons.append("DELIVERY_FORMAT_NOT_PNG")
    if alpha["status"] == "FAIL":
        reasons.append("SOURCE_ALPHA_BYPASS_MISMATCH")
    return {
        "status": "PASS" if not reasons else "FAIL",
        "fallback_required": bool(reasons),
        "reasons": reasons,
        "baseline_size": list(baseline_size),
        "candidate_size": list(candidate_size),
        "baseline_format": baseline_format,
        "candidate_format": candidate_format,
        "rgb_changed_pixel_count": int(np.count_nonzero(changed_pixels)),
        "maximum_rgb_delta": maximum_rgb_delta,
        "high_frequency_l1_baseline": round(baseline_hf, 8),
        "high_frequency_l1_candidate": round(candidate_hf, 8),
        "high_frequency_l1_delta": round(candidate_hf - baseline_hf, 8),
        "new_halo_possible": maximum_rgb_delta != 0,
        "new_double_edge_possible": maximum_rgb_delta != 0,
        "alpha": alpha,
    }


def _copy_atomic(source: Path, destination: Path) -> None:
    if destination.exists():
        raise HDCoreSafeBaseError("OUTPUT_CONFLICT", "delivery_encoding", f"输出已存在：{destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.stem}.", suffix=".tmp.png", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        with Image.open(temporary) as opened:
            opened.load()
            if str(opened.format or "").upper() != DELIVERY_FORMAT:
                raise HDCoreSafeBaseError("OUTPUT_FORMAT_INVALID", "delivery_encoding", "交付编码不是PNG。")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def finalize_with_baseline_fallback(
    baseline_path: str | Path,
    candidate_path: str | Path,
    destination_path: str | Path,
    risk: dict[str, Any],
) -> dict[str, Any]:
    """Select candidate only when strict risk checks pass; otherwise copy baseline."""

    baseline = Path(baseline_path)
    candidate = Path(candidate_path)
    candidate_allowed = risk.get("status") == "PASS" and risk.get("fallback_required") is False
    selected = candidate if candidate_allowed else baseline
    route = "FALLBACK_TO_EXISTING_4K_BASELINE" if selected == baseline else "SAFE_BASE_CANDIDATE"
    destination = Path(destination_path)
    _copy_atomic(selected, destination)
    return {
        "selected_route": route,
        "fallback_applied": selected == baseline,
        "selected_path": str(selected.resolve()),
        "final_output_path": str(destination.resolve()),
        "final_sha256": _sha256_file(destination),
        "final_pixel_sha256": _pixel_sha256(destination),
        "final_size_bytes": destination.stat().st_size,
    }


def _canonical_windows_path(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=False)
    return Path(os.path.normcase(os.path.normpath(str(resolved))))


def _is_same_or_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(root))) == str(root)
    except ValueError:
        return False


def _validate_workspace(source: Path, workspace_root: Path) -> Path:
    root = _canonical_windows_path(workspace_root)
    formal = _canonical_windows_path(FORMAL_DATA_ROOT)
    if _is_same_or_within(root, formal) or _is_same_or_within(formal, root):
        raise HDCoreSafeBaseError("FORMAL_OUTPUT_FORBIDDEN", "input", "内部安全底座不得写入正式数据根目录。")
    if root == _canonical_windows_path(source).parent:
        raise HDCoreSafeBaseError("SOURCE_DIRECTORY_OUTPUT_FORBIDDEN", "input", "内部输出不得写入原图目录。")
    return root


def process_hd_core_safe_base(source_path: str | Path, workspace_root: str | Path) -> dict[str, Any]:
    """Run the internal safe base through the frozen 4K baseline exactly once."""

    source = Path(source_path)
    root = _validate_workspace(source, Path(workspace_root))
    source_before = _sha256_file(source)
    diagnosis = diagnose_degradation(source)
    if diagnosis["processing_disposition"] == "NO_PROCESSING_NEEDED":
        return {
            "status": "NO_PROCESSING_NEEDED",
            "baseline_route": FOUR_K_V1_ROUTE,
            "diagnosis": diagnosis,
            "source_hash_unchanged": _sha256_file(source) == source_before,
            "final_output_path": "",
        }
    baseline_root = root / "baseline_executor"
    baseline_path = baseline_root / "输出" / "4K画质增强" / "baseline.png"
    candidate_path = root / "internal" / "alpha_bypass_candidate.png"
    final_path = root / "delivery" / "safe_base.png"
    started = time.perf_counter()
    try:
        baseline_result = process_4k_v1_image(source, baseline_root, output_path=baseline_path)
    except FourKV1ProcessingError as exc:
        raise HDCoreSafeBaseError(exc.code, f"baseline:{exc.stage}", str(exc)) from exc
    alpha_bypass = apply_source_alpha_bypass(source, baseline_path, candidate_path)
    risk = assess_baseline_risk(source, baseline_path, candidate_path)
    finalized = finalize_with_baseline_fallback(baseline_path, candidate_path, final_path, risk)
    final_risk = assess_baseline_risk(source, baseline_path, final_path)
    source_unchanged = _sha256_file(source) == source_before
    if not source_unchanged:
        raise HDCoreSafeBaseError("SOURCE_HASH_CHANGED", "output_verify", "原图哈希发生变化。")
    if final_risk["status"] != "PASS":
        final_path.unlink(missing_ok=True)
        raise HDCoreSafeBaseError("FINAL_RISK_GATE_FAILED", "output_verify", str(final_risk["reasons"]))
    with Image.open(final_path) as opened:
        opened.load()
        output_width, output_height = opened.size
        output_mode = opened.mode
        output_format = str(opened.format or "UNKNOWN").upper()
    target = (diagnosis["target_width"], diagnosis["target_height"])
    if (output_width, output_height) != target:
        final_path.unlink(missing_ok=True)
        raise HDCoreSafeBaseError("OUTPUT_DIMENSIONS_MISMATCH", "output_verify", "交付尺寸与安全基线计划不一致。")
    return {
        "status": "COMPLETED",
        "hd_core_safe_base": "RUN_GATES_PASSED",
        "pipeline": [
            "INPUT",
            "MEASUREMENTS_ONLY_DEGRADATION_DIAGNOSIS",
            "EXISTING_4K_SAFE_RECONSTRUCTION",
            "SOURCE_ALPHA_CHANNEL_BYPASS",
            "STRICT_BASELINE_PIXEL_RISK_GATE",
            "LOSSLESS_PNG_DELIVERY_ENCODING",
        ],
        "baseline_route": FOUR_K_V1_ROUTE,
        "baseline_executor": "engine.image_processing_routing.four_k_v1.process_4k_v1_image",
        "baseline_result_quality_conclusion": baseline_result["quality_conclusion"],
        "diagnosis": diagnosis,
        "alpha_bypass": alpha_bypass,
        "risk": risk,
        "final_risk": final_risk,
        "fallback": finalized,
        "source_path": str(source.resolve()),
        "source_sha256": source_before,
        "source_hash_unchanged": source_unchanged,
        "baseline_output_path": str(baseline_path.resolve()),
        "baseline_output_sha256": _sha256_file(baseline_path),
        "baseline_output_pixel_sha256": _pixel_sha256(baseline_path),
        "final_output_path": str(final_path.resolve()),
        "final_output_sha256": _sha256_file(final_path),
        "final_output_pixel_sha256": _pixel_sha256(final_path),
        "output_width": output_width,
        "output_height": output_height,
        "output_mode": output_mode,
        "output_format": output_format,
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "srmd_enabled": False,
        "model_enabled": False,
        "semantic_detection_enabled": False,
    }


__all__ = [
    "HDCoreSafeBaseError",
    "apply_source_alpha_bypass",
    "assess_baseline_risk",
    "diagnose_degradation",
    "finalize_with_baseline_fallback",
    "process_hd_core_safe_base",
]
