"""Experimental HDDE bounded restoration core for E4K-04.

The core is source-direct, non-generative, deterministic, and anchored to the
existing Pillow LANCZOS baseline.  It currently supports one deliberately
narrow target: JPEG/compression evidence.  Every unsupported or uncertain
input returns the baseline byte-for-byte.

This module is not connected to the formal 4K route, API, Task/Result,
Delivery, or UI.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps

from engine.algorithms.low_quality_fidelity import (
    phase4_quality_probes,
    phase4_restoration_masks,
    phase4_text_protection_stats,
)

from .candidate_framework import PRODUCT, CandidateDefinition, CandidateExecutionRequest


ALGORITHM_ID = "HDDE_BOUNDED_RESTORATION_CORE"
ALGORITHM_VERSION = "V1"
PROFILE_ID = "BOUNDED_RESTORATION_SAFE_PROFILE_V1"
DEGRADATION_PROFILE_VERSION = "BOUNDED_DEGRADATION_PROFILE_V1"
RESIDUAL_CONTRACT_VERSION = "BOUNDED_RESIDUAL_CONTRACT_V1"
HIGH_FREQUENCY_BUDGET_VERSION = "HIGH_FREQUENCY_BUDGET_V1"
HALO_RINGING_SUPPRESSION_VERSION = "HALO_RINGING_SUPPRESSION_V1"
PROTECTED_STRUCTURE_MASK_VERSION = "PROTECTED_STRUCTURE_MASK_V1"
THRESHOLD_PROVENANCE_VERSION = "THRESHOLD_PROVENANCE_V1"
TARGET_DEGRADATION_FAMILY = "JPEG_COMPRESSION"

SUPPORTED_TARGET_DEGRADATION = "SUPPORTED_TARGET_DEGRADATION"
UNSUPPORTED = "UNSUPPORTED"
NEED_PROOF = "NEED_PROOF"
ACTIVE = "ACTIVE"
NO_OP = "NO_OP"


def _round(value: float, digits: int = 8) -> float:
    return round(float(value), digits)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pixel_sha256(array: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(array)
    payload = (
        contiguous.tobytes()
        + str(contiguous.dtype).encode("ascii")
        + repr(contiguous.shape).encode("ascii")
    )
    return hashlib.sha256(payload).hexdigest()


def _json_finite(value: Any) -> Any:
    """Replace non-finite numeric evidence with an explicit JSON-safe marker."""

    if isinstance(value, dict):
        return {key: _json_finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_finite(item) for item in value]
    if isinstance(value, (float, np.floating)) and not math.isfinite(float(value)):
        return f"NONFINITE:{value!r}"
    return value


@dataclass(frozen=True)
class BoundedRestorationProfile:
    """The only formal E4K-04 V1 Candidate profile."""

    profile_id: str = PROFILE_ID
    target_degradation_family: str = TARGET_DEGRADATION_FAMILY
    source_deblock_strength: float = 0.25
    source_correction_budget: float = 2.0
    jpeg_boundary_jump_floor: float = 2.0
    jpeg_side_gradient_ceiling: float = 12.0
    jpeg_strong_edge_ceiling: float = 24.0
    residual_absolute_budget: float = 1.0
    local_gradient_budget: float = 2.0
    high_frequency_ratio_budget: float = 1.02
    overshoot_budget: float = 0.0
    protected_region_budget: float = 0.0
    flat_region_residual_scale: float = 0.5
    color_chroma_delta_budget: float = 0.0
    protection_working_edge: int = 960
    high_frequency_working_edge: int = 960

    def canonical_parameters(self) -> dict[str, Any]:
        values = _json_finite(asdict(self))
        provenance = build_threshold_provenance(self)
        values["threshold_provenance"] = provenance
        values["threshold_sources"] = {
            item["threshold_name"]: item["source_type"]
            for item in provenance["thresholds"]
        }
        return values


SAFE_PROFILE = BoundedRestorationProfile()


_THRESHOLD_SPECS: dict[str, dict[str, Any]] = {
    "source_deblock_strength": {
        "unit": "ratio",
        "source_type": "CONTROL_CALIBRATION",
        "source_evidence": "E4K04_V1_CONTROLLED_JPEG_PROBES",
        "calibration_dataset": "E4K04_V1_CONTROLLED_SYNTHETIC_PROBES",
        "calibration_method": "SAFETY_GRID_WITH_NEGATIVE_CONTROL",
        "allowed_range": [0.0, 1.0],
    },
    "source_correction_budget": {
        "unit": "source_luma_level",
        "source_type": "CONTROL_CALIBRATION",
        "source_evidence": "E4K04_V1_CONTROLLED_JPEG_PROBES",
        "calibration_dataset": "E4K04_V1_CONTROLLED_SYNTHETIC_PROBES",
        "calibration_method": "MAX_SOURCE_DELTA_SAFETY_GRID",
        "allowed_range": [0.0, 8.0],
    },
    "jpeg_boundary_jump_floor": {
        "unit": "source_luma_level",
        "source_type": "CONTROL_CALIBRATION",
        "source_evidence": "E4K04_V1_CONTROLLED_JPEG_BOUNDARY_RESPONSE",
        "calibration_dataset": "E4K04_V1_CONTROLLED_SYNTHETIC_PROBES",
        "calibration_method": "KNOWN_JPEG_BOUNDARY_RESPONSE_CALIBRATION",
        "allowed_range": [0.0, 32.0],
    },
    "jpeg_side_gradient_ceiling": {
        "unit": "source_luma_level",
        "source_type": "CONTROL_CALIBRATION",
        "source_evidence": "E4K04_V1_CONTROLLED_EDGE_NEGATIVE_CONTROLS",
        "calibration_dataset": "E4K04_V1_CONTROLLED_SYNTHETIC_PROBES",
        "calibration_method": "EDGE_EXCLUSION_SAFETY_CALIBRATION",
        "allowed_range": [0.0, 64.0],
    },
    "jpeg_strong_edge_ceiling": {
        "unit": "source_luma_level",
        "source_type": "CONTROL_CALIBRATION",
        "source_evidence": "E4K04_V1_CONTROLLED_EDGE_NEGATIVE_CONTROLS",
        "calibration_dataset": "E4K04_V1_CONTROLLED_SYNTHETIC_PROBES",
        "calibration_method": "STRONG_EDGE_EXCLUSION_SAFETY_CALIBRATION",
        "allowed_range": [0.0, 128.0],
    },
    "residual_absolute_budget": {
        "unit": "target_uint8_level",
        "source_type": "CONTROL_CALIBRATION",
        "source_evidence": "E4K04_V1_CONTROLLED_OUTPUT_RESIDUALS",
        "calibration_dataset": "E4K04_V1_CONTROLLED_SYNTHETIC_PROBES",
        "calibration_method": "MAX_ABSOLUTE_RESIDUAL_SAFETY_CALIBRATION",
        "allowed_range": [0.0, 1.0],
    },
    "local_gradient_budget": {
        "unit": "target_uint8_level_per_pixel",
        "source_type": "CONTROL_CALIBRATION",
        "source_evidence": "E4K04_V1_CONTROLLED_LOCAL_GRADIENT_RESPONSES",
        "calibration_dataset": "E4K04_V1_CONTROLLED_SYNTHETIC_PROBES",
        "calibration_method": "LOCAL_RESIDUAL_GRADIENT_SAFETY_CALIBRATION",
        "allowed_range": [0.0, 2.0],
    },
    "high_frequency_ratio_budget": {
        "unit": "candidate_to_baseline_hf_ratio",
        "source_type": "EXISTING_GATE_LIMIT",
        "source_evidence": "E1_02_HIGH_FREQUENCY_AND_OVERSHARPEN_GATES",
        "calibration_dataset": "E1_02_GATE_CONTRACT_V1",
        "calibration_method": "CONSERVATIVE_SUBSET_OF_EXISTING_GATE_LIMIT",
        "allowed_range": [1.0, 1.02],
    },
    "overshoot_budget": {
        "unit": "target_uint8_level_outside_local_extrema",
        "source_type": "EXISTING_GATE_LIMIT",
        "source_evidence": "E1_02_ZERO_NEW_OVERSHOOT_POLICY",
        "calibration_dataset": "E1_02_GATE_CONTRACT_V1",
        "calibration_method": "ZERO_NEW_LOCAL_EXTREMA_CONTRACT",
        "allowed_range": [0.0, 0.0],
    },
    "protected_region_budget": {
        "unit": "target_uint8_level",
        "source_type": "EXISTING_GATE_LIMIT",
        "source_evidence": "HDDE_TEXT_LOGO_STRUCTURE_FAIL_CLOSED_POLICY",
        "calibration_dataset": "E1_02_PROTECTED_ROI_CONTRACT_V1",
        "calibration_method": "ZERO_BUDGET_WHEN_STRUCTURE_IS_PROTECTED",
        "allowed_range": [0.0, 0.0],
    },
    "flat_region_residual_scale": {
        "unit": "ratio",
        "source_type": "CONTROL_CALIBRATION",
        "source_evidence": "E4K04_V1_CONTROLLED_FLAT_REGION_NEGATIVE_CONTROLS",
        "calibration_dataset": "E4K04_V1_CONTROLLED_SYNTHETIC_PROBES",
        "calibration_method": "FLAT_REGION_FALSE_TEXTURE_SAFETY_CALIBRATION",
        "allowed_range": [0.0, 0.5],
    },
    "color_chroma_delta_budget": {
        "unit": "rgb_channel_difference_level",
        "source_type": "EXISTING_GATE_LIMIT",
        "source_evidence": "HDDE_LUMA_ONLY_COLOR_LOCK_CONTRACT",
        "calibration_dataset": "E1_02_COLOR_SAFETY_CONTRACT_V1",
        "calibration_method": "ZERO_CHROMA_DIFFERENCE_DRIFT_CONTRACT",
        "allowed_range": [0.0, 0.0],
    },
    "protection_working_edge": {
        "unit": "pixel",
        "source_type": "CONTROL_CALIBRATION",
        "source_evidence": "E4K04_V1_MASK_STABILITY_AND_RUNTIME_PROBES",
        "calibration_dataset": "E4K04_V1_CONTROLLED_SYNTHETIC_PROBES",
        "calibration_method": "MASK_STABILITY_RUNTIME_CALIBRATION",
        "allowed_range": [256, 960],
    },
    "high_frequency_working_edge": {
        "unit": "pixel",
        "source_type": "CONTROL_CALIBRATION",
        "source_evidence": "E4K04_V1_HF_MEASUREMENT_STABILITY_PROBES",
        "calibration_dataset": "E4K04_V1_CONTROLLED_SYNTHETIC_PROBES",
        "calibration_method": "HF_MEASUREMENT_STABILITY_RUNTIME_CALIBRATION",
        "allowed_range": [256, 960],
    },
}

_ALLOWED_THRESHOLD_SOURCE_TYPES = {
    "EXISTING_GATE_LIMIT",
    "CONTROL_CALIBRATION",
    "SOURCE_DERIVED_RUNTIME_STATISTIC",
}


def build_threshold_provenance(
    profile: BoundedRestorationProfile = SAFE_PROFILE,
) -> dict[str, Any]:
    """Return complete provenance; changed constants are uncalibrated."""

    default_profile = BoundedRestorationProfile()
    thresholds: list[dict[str, Any]] = []
    for name, spec in _THRESHOLD_SPECS.items():
        value = getattr(profile, name)
        default_value = getattr(default_profile, name)
        unchanged = (
            isinstance(value, (int, float))
            and math.isfinite(float(value))
            and float(value) == float(default_value)
        )
        low, high = spec["allowed_range"]
        within_range = unchanged and float(low) <= float(value) <= float(high)
        source_evidence = spec["source_evidence"]
        if not unchanged:
            source_evidence = (
                f"VALUE_DIFFERS_FROM_FROZEN_V1:{default_value!r}->{value!r}"
            )
        thresholds.append(
            {
                "threshold_name": name,
                "threshold_value": _json_finite(value),
                "unit": spec["unit"],
                "source_type": spec["source_type"],
                "source_evidence": source_evidence,
                "calibration_dataset": spec["calibration_dataset"],
                "calibration_method": spec["calibration_method"],
                "allowed_range": list(spec["allowed_range"]),
                "status": "VALID" if within_range else "NEED_CALIBRATION",
            }
        )

    failures: list[str] = []
    expected = set(_THRESHOLD_SPECS)
    actual = {item["threshold_name"] for item in thresholds}
    if actual != expected:
        failures.append("THRESHOLD_SET_INCOMPLETE")
    for item in thresholds:
        name = item["threshold_name"]
        value = item["threshold_value"]
        if item["source_type"] not in _ALLOWED_THRESHOLD_SOURCE_TYPES:
            failures.append(f"SOURCE_TYPE_INVALID:{name}")
        if item["source_type"] == "SOURCE_DERIVED_RUNTIME_STATISTIC":
            failures.append(f"FIXED_THRESHOLD_MISLABELED_SOURCE_DERIVED:{name}")
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            failures.append(f"THRESHOLD_NONFINITE:{name}")
        if not all(
            isinstance(item[field], str) and bool(item[field].strip())
            for field in (
                "unit",
                "source_evidence",
                "calibration_dataset",
                "calibration_method",
            )
        ):
            failures.append(f"THRESHOLD_PROVENANCE_INCOMPLETE:{name}")
        if item["status"] != "VALID":
            failures.append(f"THRESHOLD_NEEDS_CALIBRATION:{name}")
    uncalibrated = sum(item["status"] != "VALID" for item in thresholds)
    return {
        "version": THRESHOLD_PROVENANCE_VERSION,
        "status": "PASS" if not failures else "NEED_CALIBRATION",
        "uncalibrated_threshold_count": uncalibrated,
        "failures": failures,
        "thresholds": thresholds,
    }


def bounded_candidate_definition(
    *,
    profile: BoundedRestorationProfile = SAFE_PROFILE,
) -> CandidateDefinition:
    """Bind the full self-developed algorithm contract to one Candidate ID."""

    return CandidateDefinition(
        algorithm_id=ALGORITHM_ID,
        algorithm_version=ALGORITHM_VERSION,
        parameters={
            "model_plan": "SELF_DEVELOPED_BOUNDED_RESTORATION",
            "external_enhancement_model": "NONE",
            "formal_baseline": "PILLOW_LANCZOS",
            "target_degradation_family": TARGET_DEGRADATION_FAMILY,
            "degradation_profile": DEGRADATION_PROFILE_VERSION,
            "restoration_profile": profile.canonical_parameters(),
            "raw_proposal": "SOURCE_LUMA_JPEG_8X8_BOUNDARY_CORRECTION_V1",
            "bounded_residual_contract": RESIDUAL_CONTRACT_VERSION,
            "high_frequency_budget": HIGH_FREQUENCY_BUDGET_VERSION,
            "halo_ringing_suppression": HALO_RINGING_SUPPRESSION_VERSION,
            "protection_policy": PROTECTED_STRUCTURE_MASK_VERSION,
            "color_lock": "BASELINE_CHROMA_DIFFERENCE_IDENTITY",
            "alpha_lock": "BASELINE_ALPHA_BYTE_IDENTITY",
            "unsupported_or_uncertain": NO_OP,
        },
        backend_identity="NUMPY_OPENCV_PILLOW_CPU",
        precision_identity="FLOAT32_ANALYSIS_UINT8_DETERMINISTIC_OUTPUT",
        candidate_class=PRODUCT,
        model_id="NONE",
        model_version="NONE",
        model_sha256="NONE",
        normalization={
            "version": "BOUNDED_RESTORATION_NORMALIZATION_V1",
            "operations": [
                "SOURCE_EXIF_TRANSPOSE",
                "SOURCE_LUMA_PROPOSAL",
                "PILLOW_LANCZOS_COMPARISON_ALIGNMENT",
            ],
            "implicit_resize": False,
            "implicit_crop_or_padding": False,
            "implicit_color_conversion": False,
        },
        color_profile_policy="PRESERVE_BASELINE_PROFILE",
        control_fixture_only=False,
    )


def _normalized_image(path: Path) -> tuple[Image.Image, bytes | None, str | None]:
    with Image.open(path) as opened:
        opened.load()
        image_format = opened.format
        icc = opened.info.get("icc_profile")
        image = ImageOps.exif_transpose(opened).copy()
    return image, icc if isinstance(icc, bytes) and icc else None, image_format


def _working_rgb(image: Image.Image, maximum_edge: int) -> np.ndarray:
    working = image.convert("RGB")
    if max(working.size) > maximum_edge:
        working.thumbnail((maximum_edge, maximum_edge), Image.Resampling.LANCZOS)
    return np.asarray(working, dtype=np.uint8)


def _jpeg_quantization_evidence(path: Path) -> dict[str, Any]:
    with Image.open(path) as opened:
        tables = getattr(opened, "quantization", None) or {}
        image_format = opened.format
    normalized: dict[int, list[float]] = {}
    for key, values in tables.items():
        try:
            table = [float(value) for value in values]
        except (TypeError, ValueError):
            continue
        if len(table) == 64 and all(math.isfinite(value) and value > 0 for value in table):
            normalized[int(key)] = table
    luma = normalized.get(0)
    return {
        "decoded_format": image_format,
        "jpeg_extension": path.suffix.lower() in {".jpg", ".jpeg"},
        "quantization_table_count": len(normalized),
        "luma_quantization_table_valid": luma is not None,
        "luma_quantization_mean": None if luma is None else _round(np.mean(luma), 6),
        "luma_quantization_max": None if luma is None else _round(np.max(luma), 6),
    }


def build_degradation_profile(
    source_path: str | Path,
    *,
    profile: BoundedRestorationProfile = SAFE_PROFILE,
) -> dict[str, Any]:
    """Measure narrow evidence; this is not an accuracy claim or AI classifier."""

    path = Path(source_path)
    source, _icc, decoded_format = _normalized_image(path)
    rgb = _working_rgb(source, profile.protection_working_edge)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    existing_probes = phase4_quality_probes(bgr)
    try:
        text_stats = phase4_text_protection_stats(bgr)
        text_measurement_status = "MEASURED"
    except Exception as exc:  # fail closed at the profile boundary
        text_stats = {
            "text_region_count": None,
            "text_mask_ratio": None,
            "largest_text_region_ratio": None,
            "measurement_error": f"{type(exc).__name__}:{exc}",
        }
        text_measurement_status = NEED_PROOF

    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    noise_residual = np.abs(gray.astype(np.float32) - blurred.astype(np.float32))
    edges = cv2.Canny(blurred, 90, 190)
    gray_float = gray.astype(np.float32)
    local_mean = cv2.blur(gray_float, (9, 9))
    local_square_mean = cv2.blur(gray_float * gray_float, (9, 9))
    local_std = np.sqrt(np.maximum(local_square_mean - local_mean * local_mean, 0.0))
    quantization = _jpeg_quantization_evidence(path)

    direct_jpeg_evidence = (
        decoded_format == "JPEG"
        and quantization["jpeg_extension"]
        and quantization["luma_quantization_table_valid"]
    )
    partial_jpeg_evidence = (
        decoded_format == "JPEG" or bool(quantization["jpeg_extension"])
    ) and not direct_jpeg_evidence
    if text_measurement_status == NEED_PROOF:
        status = NEED_PROOF
        reason = "TEXT_STRUCTURE_RISK_MEASUREMENT_UNCERTAIN"
    elif direct_jpeg_evidence:
        status = SUPPORTED_TARGET_DEGRADATION
        reason = "JPEG_CONTAINER_EXTENSION_AND_QUANTIZATION_TABLES_AGREE"
    elif partial_jpeg_evidence:
        status = NEED_PROOF
        reason = "JPEG_CONTAINER_EVIDENCE_INCOMPLETE_OR_CONFLICTING"
    else:
        status = UNSUPPORTED
        reason = "NO_DIRECT_JPEG_CONTAINER_EVIDENCE"

    return {
        "profile_version": DEGRADATION_PROFILE_VERSION,
        "target_degradation_family": TARGET_DEGRADATION_FAMILY,
        "status": status,
        "reason": reason,
        "restoration_activation": ACTIVE if status == SUPPORTED_TARGET_DEGRADATION else NO_OP,
        "evidence_claim_scope": "HEURISTIC_MEASUREMENTS_PLUS_DIRECT_CONTAINER_EVIDENCE_NOT_ACCURACY_CLAIM",
        "compression_evidence": {
            **quantization,
            "existing_block_boundary_risk": existing_probes.get("compression_risk"),
        },
        "blur_evidence": {
            "existing_blur_risk": existing_probes.get("blur_risk"),
            "laplacian_variance": _round(cv2.Laplacian(gray, cv2.CV_32F).var(), 6),
        },
        "noise_evidence": {
            "median_absolute_high_pass": _round(np.median(noise_residual), 6),
            "p90_absolute_high_pass": _round(np.percentile(noise_residual, 90), 6),
        },
        "edge_evidence": {
            "canny_edge_fraction": _round(np.mean(edges > 0), 8),
        },
        "text_like_risk": {
            "measurement_status": text_measurement_status,
            **text_stats,
        },
        "flat_region_risk": {
            "local_std_lt_3_fraction": _round(np.mean(local_std < 3.0), 8),
            "local_std_lt_6_fraction": _round(np.mean(local_std < 6.0), 8),
        },
    }


def _deblock_luma(
    gray: np.ndarray,
    profile: BoundedRestorationProfile,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Apply a narrow 8x8 boundary correction in source luminance only."""

    source = np.asarray(gray, dtype=np.float32)
    restored = source.copy()
    corrected = np.zeros(source.shape, dtype=bool)
    boundary_count = 0

    def correct_vertical(
        work: np.ndarray,
        original: np.ndarray,
        corrected_work: np.ndarray,
    ) -> None:
        nonlocal boundary_count
        height, width = original.shape
        for x in range(8, width, 8):
            if x < 2 or x + 1 >= width:
                continue
            p1 = original[:, x - 2]
            p0 = original[:, x - 1]
            q0 = original[:, x]
            q1 = original[:, x + 1]
            jump = q0 - p0
            side = 0.5 * (np.abs(p0 - p1) + np.abs(q1 - q0))
            mask = (
                (np.abs(jump) >= side + profile.jpeg_boundary_jump_floor)
                & (np.abs(jump) <= profile.jpeg_strong_edge_ceiling)
                & (np.abs(p0 - p1) <= profile.jpeg_side_gradient_ceiling)
                & (np.abs(q1 - q0) <= profile.jpeg_side_gradient_ceiling)
            )
            excess = np.sign(jump) * np.maximum(np.abs(jump) - side, 0.0)
            delta = np.clip(
                excess * profile.source_deblock_strength,
                -profile.source_correction_budget,
                profile.source_correction_budget,
            )
            delta = np.where(mask, delta, 0.0)
            work[:, x - 1] += delta
            work[:, x] -= delta
            corrected_work[:, x - 1] |= mask
            corrected_work[:, x] |= mask
            boundary_count += 1

    correct_vertical(restored, source, corrected)
    # Transposition reuses the exact same deterministic rule horizontally.
    transposed_before = restored.T.copy()
    transposed_original = source.T
    transposed_corrected = corrected.T.copy()
    correct_vertical(transposed_before, transposed_original, transposed_corrected)
    restored = transposed_before.T
    corrected = transposed_corrected.T
    restored = np.clip(restored, 0.0, 255.0)
    delta = restored - source
    return restored, {
        "operator": "SOURCE_LUMA_JPEG_8X8_BOUNDARY_CORRECTION_V1",
        "boundary_lines_examined": int(boundary_count),
        "source_pixels_corrected": int(np.count_nonzero(corrected)),
        "source_correction_max_abs": _round(np.max(np.abs(delta)), 6),
        "source_correction_mean_abs": _round(np.mean(np.abs(delta)), 8),
        "generative": False,
        "sharpening_operator": False,
    }


def _raw_source_direct_residual(
    source: Image.Image,
    target_size: tuple[int, int],
    profile: BoundedRestorationProfile,
) -> tuple[np.ndarray, dict[str, Any]]:
    source_luma = np.asarray(source.convert("L"), dtype=np.uint8)
    restored_luma, operator_record = _deblock_luma(source_luma, profile)
    original_surface = np.asarray(
        Image.fromarray(source_luma, "L").resize(target_size, Image.Resampling.LANCZOS),
        dtype=np.float32,
    )
    proposal_surface = np.asarray(
        Image.fromarray(np.rint(restored_luma).astype(np.uint8), "L").resize(
            target_size, Image.Resampling.LANCZOS
        ),
        dtype=np.float32,
    )
    residual = proposal_surface - original_surface
    operator_record.update(
        {
            "alignment_surface": "PILLOW_LANCZOS_TARGET_SIZE",
            "target_width": int(target_size[0]),
            "target_height": int(target_size[1]),
            "raw_residual_min": _round(np.min(residual), 6),
            "raw_residual_max": _round(np.max(residual), 6),
            "raw_residual_mean_abs": _round(np.mean(np.abs(residual)), 8),
            "raw_residual_nonzero_fraction": _round(np.mean(residual != 0), 8),
        }
    )
    return residual, operator_record


def _resize_mask(mask: np.ndarray, shape: tuple[int, int], interpolation: int) -> np.ndarray:
    height, width = shape
    return cv2.resize(mask.astype(np.float32), (width, height), interpolation=interpolation)


def build_protection_scale(
    baseline_rgb: np.ndarray,
    *,
    profile: BoundedRestorationProfile = SAFE_PROFILE,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Build text/structure hard locks plus a reduced flat-region budget."""

    rgb = np.asarray(baseline_rgb, dtype=np.uint8)
    height, width = rgb.shape[:2]
    scale = min(1.0, profile.protection_working_edge / max(height, width))
    if scale < 1.0:
        working = cv2.resize(
            rgb,
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    else:
        working = rgb
    bgr = cv2.cvtColor(working, cv2.COLOR_RGB2BGR)
    try:
        reused = phase4_restoration_masks(bgr, {})
        text = np.asarray(reused["text_mask"], dtype=np.float32)
        flat = np.asarray(reused["flat_region_mask"], dtype=np.float32)
        if text.shape != working.shape[:2] or flat.shape != working.shape[:2]:
            raise ValueError("PROTECTION_MASK_SHAPE_MISMATCH")
        if not np.isfinite(text).all() or not np.isfinite(flat).all():
            raise ValueError("PROTECTION_MASK_NONFINITE")
    except Exception as exc:
        return np.zeros((height, width), dtype=np.float32), {
            "version": PROTECTED_STRUCTURE_MASK_VERSION,
            "status": NEED_PROOF,
            "reason": f"PROTECTION_MASK_UNCERTAIN:{type(exc).__name__}:{exc}",
            "restoration_strength": 0.0,
            "text_region_budget": profile.protected_region_budget,
            "structure_region_budget": profile.protected_region_budget,
        }

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    edge = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 90, 190)
    structure = cv2.dilate(edge, np.ones((5, 5), np.uint8), iterations=1) > 0
    text_binary = text > 0.05
    flat_binary = flat > 0.6

    work_scale = np.ones(working.shape[:2], dtype=np.float32)
    work_scale[flat_binary] *= profile.flat_region_residual_scale
    work_scale[text_binary | structure] = profile.protected_region_budget

    full_scale = _resize_mask(work_scale, (height, width), cv2.INTER_LINEAR)
    full_text = _resize_mask(text_binary.astype(np.float32), (height, width), cv2.INTER_NEAREST) > 0
    full_structure = (
        _resize_mask(structure.astype(np.float32), (height, width), cv2.INTER_NEAREST) > 0
    )
    full_scale[full_text | full_structure] = profile.protected_region_budget
    full_scale = np.clip(full_scale, 0.0, 1.0).astype(np.float32)
    return full_scale, {
        "version": PROTECTED_STRUCTURE_MASK_VERSION,
        "status": "PASS",
        "reason": "EXISTING_TEXT_MASK_PLUS_EDGE_STRUCTURE_LOCK",
        "working_width": int(working.shape[1]),
        "working_height": int(working.shape[0]),
        "text_mask_fraction": _round(np.mean(text_binary), 8),
        "structure_mask_fraction": _round(np.mean(structure), 8),
        "flat_region_fraction": _round(np.mean(flat_binary), 8),
        "zero_budget_fraction": _round(np.mean(full_scale == 0.0), 8),
        "reduced_budget_fraction": _round(np.mean((full_scale > 0.0) & (full_scale < 1.0)), 8),
        "text_region_budget": profile.protected_region_budget,
        "structure_region_budget": profile.protected_region_budget,
        "flat_region_scale": profile.flat_region_residual_scale,
        "ocr_used": False,
    }


def _hf_energy(gray: np.ndarray, maximum_edge: int) -> float:
    values = np.asarray(gray, dtype=np.float32)
    height, width = values.shape
    scale = min(1.0, maximum_edge / max(height, width))
    if scale < 1.0:
        values = cv2.resize(
            values,
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    return float(np.mean(np.abs(cv2.Laplacian(values, cv2.CV_32F, ksize=3))))


def _summary(array: np.ndarray) -> dict[str, float]:
    values = np.asarray(array, dtype=np.float32)
    return {
        "min": _round(np.min(values), 6),
        "max": _round(np.max(values), 6),
        "p01": _round(np.percentile(values, 1), 6),
        "p50": _round(np.percentile(values, 50), 6),
        "p99": _round(np.percentile(values, 99), 6),
    }


def apply_bounded_residual(
    baseline_rgb: np.ndarray,
    raw_residual: np.ndarray,
    *,
    protection_scale: np.ndarray | None = None,
    protection_reliable: bool = True,
    profile: BoundedRestorationProfile = SAFE_PROFILE,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Apply all bounded contracts; invalid evidence returns the baseline."""

    baseline = np.asarray(baseline_rgb, dtype=np.uint8)
    residual = np.asarray(raw_residual, dtype=np.float32)
    if baseline.ndim != 3 or baseline.shape[2] != 3:
        raise ValueError("BASELINE_RGB_REQUIRED")
    if residual.shape != baseline.shape[:2]:
        raise ValueError("RESIDUAL_SHAPE_MISMATCH")
    if protection_scale is None:
        protection = np.ones(residual.shape, dtype=np.float32)
    else:
        protection = np.asarray(protection_scale, dtype=np.float32)
    record: dict[str, Any] = {
        "contract_version": RESIDUAL_CONTRACT_VERSION,
        "profile_id": profile.profile_id,
        "threshold_provenance": build_threshold_provenance(profile),
        "fail_closed": False,
        "fail_closed_reason": None,
        "residual_absolute_budget": _json_finite(profile.residual_absolute_budget),
        "local_gradient_budget": _json_finite(profile.local_gradient_budget),
        "high_frequency_budget_version": HIGH_FREQUENCY_BUDGET_VERSION,
        "high_frequency_ratio_budget": _json_finite(
            profile.high_frequency_ratio_budget
        ),
        "overshoot_budget": _json_finite(profile.overshoot_budget),
        "protected_region_budget": _json_finite(profile.protected_region_budget),
        "color_delta_budget": _json_finite(profile.color_chroma_delta_budget),
    }
    record["threshold_status"] = record["threshold_provenance"]["status"]
    if record["threshold_status"] != "PASS":
        record.update(
            {
                "fail_closed": True,
                "fail_closed_reason": "THRESHOLD_PROVENANCE_NEEDS_CALIBRATION",
                "restoration_activation": NO_OP,
                "residual_nonzero_count": 0,
                "residual_max_abs_after": 0,
            }
        )
        return baseline.copy(), record
    if (
        not protection_reliable
        or protection.shape != residual.shape
        or not np.isfinite(protection).all()
    ):
        record.update(
            {
                "fail_closed": True,
                "fail_closed_reason": "PROTECTION_EVIDENCE_UNCERTAIN",
                "restoration_activation": NO_OP,
            }
        )
        return baseline.copy(), record
    if not np.isfinite(residual).all():
        record.update(
            {
                "fail_closed": True,
                "fail_closed_reason": "NONFINITE_RESIDUAL",
                "restoration_activation": NO_OP,
            }
        )
        return baseline.copy(), record
    if profile.residual_absolute_budget <= 0:
        record.update(
            {
                "fail_closed": False,
                "fail_closed_reason": "ZERO_RESIDUAL_BUDGET",
                "restoration_activation": NO_OP,
                "residual_nonzero_count": 0,
            }
        )
        return baseline.copy(), record

    raw_abs = np.abs(residual)
    bounded = np.clip(
        residual,
        -profile.residual_absolute_budget,
        profile.residual_absolute_budget,
    )
    absolute_clamped = int(np.count_nonzero(np.abs(bounded - residual) > 1e-7))
    bounded *= np.clip(protection, 0.0, 1.0)

    dx = float(np.max(np.abs(np.diff(bounded, axis=1)))) if bounded.shape[1] > 1 else 0.0
    dy = float(np.max(np.abs(np.diff(bounded, axis=0)))) if bounded.shape[0] > 1 else 0.0
    maximum_local_gradient = max(dx, dy)
    local_gradient_scale = 1.0
    if maximum_local_gradient > profile.local_gradient_budget > 0:
        local_gradient_scale = profile.local_gradient_budget / maximum_local_gradient
        bounded *= local_gradient_scale
    elif profile.local_gradient_budget <= 0 and maximum_local_gradient > 0:
        local_gradient_scale = 0.0
        bounded.fill(0.0)

    base_gray = cv2.cvtColor(baseline, cv2.COLOR_RGB2GRAY).astype(np.float32)
    baseline_hf = _hf_energy(base_gray, profile.high_frequency_working_edge)
    proposal_hf = _hf_energy(base_gray + residual, profile.high_frequency_working_edge)
    hf_budget = baseline_hf * profile.high_frequency_ratio_budget
    candidate_hf_pre = _hf_energy(base_gray + bounded, profile.high_frequency_working_edge)
    hf_clamped = False
    hf_shrink_steps = 0
    while candidate_hf_pre > hf_budget + 1e-7 and hf_shrink_steps < 12:
        bounded *= 0.5
        hf_clamped = True
        hf_shrink_steps += 1
        candidate_hf_pre = _hf_energy(
            base_gray + bounded, profile.high_frequency_working_edge
        )
    if candidate_hf_pre > hf_budget + 1e-7:
        bounded.fill(0.0)
        hf_clamped = True
        hf_shrink_steps += 1

    rounded_delta = np.rint(bounded).astype(np.int16)
    kernel = np.ones((3, 3), np.uint8)
    lower = np.full(baseline.shape[:2], -255, dtype=np.int16)
    upper = np.full(baseline.shape[:2], 255, dtype=np.int16)
    local_min_summary: dict[str, Any] = {}
    local_max_summary: dict[str, Any] = {}
    for channel, label in enumerate(("R", "G", "B")):
        plane = baseline[..., channel]
        local_min = cv2.erode(plane, kernel).astype(np.int16)
        local_max = cv2.dilate(plane, kernel).astype(np.int16)
        lower = np.maximum(lower, local_min - plane.astype(np.int16))
        upper = np.minimum(upper, local_max - plane.astype(np.int16))
        local_min_summary[label] = _summary(local_min)
        local_max_summary[label] = _summary(local_max)
    if profile.overshoot_budget > 0:
        lower = np.floor(lower - profile.overshoot_budget).astype(np.int16)
        upper = np.ceil(upper + profile.overshoot_budget).astype(np.int16)
    post_delta = np.minimum(np.maximum(rounded_delta, lower), upper)
    overshoot_clamped_count = int(np.count_nonzero(post_delta != rounded_delta))
    candidate_int = baseline.astype(np.int16) + post_delta[..., None]
    candidate = np.clip(candidate_int, 0, 255).astype(np.uint8)

    base_differences = baseline.astype(np.int16)
    candidate_differences = candidate.astype(np.int16)
    chroma_drift = np.maximum(
        np.abs(
            (candidate_differences[..., 0] - candidate_differences[..., 1])
            - (base_differences[..., 0] - base_differences[..., 1])
        ),
        np.abs(
            (candidate_differences[..., 2] - candidate_differences[..., 1])
            - (base_differences[..., 2] - base_differences[..., 1])
        ),
    )
    maximum_chroma_drift = float(np.max(chroma_drift))
    color_lock_status = "PASS"
    if maximum_chroma_drift > profile.color_chroma_delta_budget:
        candidate = baseline.copy()
        post_delta.fill(0)
        color_lock_status = "FAIL_CLOSED_TO_BASELINE"
        record["fail_closed"] = True
        record["fail_closed_reason"] = "COLOR_CHROMA_DELTA_BUDGET_EXCEEDED"

    baseline_saturation = cv2.cvtColor(baseline, cv2.COLOR_RGB2HSV)[..., 1]
    candidate_saturation = cv2.cvtColor(candidate, cv2.COLOR_RGB2HSV)[..., 1]
    final_gray = cv2.cvtColor(candidate, cv2.COLOR_RGB2GRAY).astype(np.float32)
    candidate_hf = _hf_energy(final_gray, profile.high_frequency_working_edge)
    if candidate_hf > hf_budget + 1e-7:
        candidate = baseline.copy()
        post_delta.fill(0)
        candidate_hf = baseline_hf
        record["fail_closed"] = True
        record["fail_closed_reason"] = "POST_QUANTIZATION_HF_BUDGET_EXCEEDED"
        hf_clamped = True

    record.update(
        {
            "restoration_activation": (
                NO_OP if np.array_equal(candidate, baseline) else ACTIVE
            ),
            "raw_residual_min": _round(np.min(residual), 6),
            "raw_residual_max": _round(np.max(residual), 6),
            "raw_residual_mean_abs": _round(np.mean(raw_abs), 8),
            "absolute_budget_clamped_count": absolute_clamped,
            "maximum_local_residual_gradient_before": _round(maximum_local_gradient, 6),
            "local_gradient_scale": _round(local_gradient_scale, 8),
            "baseline_hf_energy": _round(baseline_hf, 8),
            "proposal_hf_energy": _round(proposal_hf, 8),
            "candidate_hf_energy": _round(candidate_hf, 8),
            "hf_budget": _round(hf_budget, 8),
            "hf_clamped": hf_clamped,
            "hf_shrink_steps": hf_shrink_steps,
            "local_min": local_min_summary,
            "local_max": local_max_summary,
            "candidate_pre_clamp": _summary(
                baseline.astype(np.int16) + rounded_delta[..., None]
            ),
            "candidate_post_clamp": _summary(candidate),
            "overshoot_clamped_count": overshoot_clamped_count,
            "halo_ringing_suppression": {
                "version": HALO_RINGING_SUPPRESSION_VERSION,
                "edge_and_text_residual_lock": True,
                "local_extrema_lock": True,
                "high_frequency_shrink": True,
            },
            "residual_nonzero_count": int(np.count_nonzero(post_delta)),
            "residual_max_abs_after": int(np.max(np.abs(post_delta))),
            "baseline_color_metrics": {
                "saturation_mean": _round(np.mean(baseline_saturation), 8),
            },
            "candidate_color_metrics": {
                "saturation_mean": _round(np.mean(candidate_saturation), 8),
            },
            "color_delta": {
                "maximum_chroma_difference_drift": _round(maximum_chroma_drift, 8),
                "saturation_mean_delta": _round(
                    np.mean(candidate_saturation.astype(np.float32))
                    - np.mean(baseline_saturation.astype(np.float32)),
                    8,
                ),
                "rgb_mean_absolute_delta": _round(
                    np.mean(
                        np.abs(
                            candidate.astype(np.int16) - baseline.astype(np.int16)
                        )
                    ),
                    8,
                ),
            },
            "color_lock_status": color_lock_status,
            "color_operator_scope": "LUMINANCE_RESIDUAL_ONLY_NO_HUE_OR_SATURATION_OPERATOR",
        }
    )
    return candidate, record


def attach_baseline_alpha(candidate_rgb: np.ndarray, baseline: np.ndarray) -> np.ndarray:
    """Reattach baseline alpha byte-identically; RGB processing never sees alpha."""

    rgb = np.asarray(candidate_rgb, dtype=np.uint8)
    base = np.asarray(baseline, dtype=np.uint8)
    if base.ndim != 3 or base.shape[2] != 4:
        raise ValueError("RGBA_BASELINE_REQUIRED")
    if rgb.shape[:2] != base.shape[:2] or rgb.shape[2] != 3:
        raise ValueError("ALPHA_ATTACHMENT_SHAPE_MISMATCH")
    return np.dstack((rgb, base[..., 3].copy()))


def restore_bounded_candidate(
    source_path: str | Path,
    baseline_path: str | Path,
    output_path: str | Path,
    *,
    record_path: str | Path | None = None,
    profile: BoundedRestorationProfile = SAFE_PROFILE,
) -> dict[str, Any]:
    """Execute one bounded Candidate and always fail closed to the baseline."""

    source_file = Path(source_path)
    baseline_file = Path(baseline_path)
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    source_sha_before = _sha256_file(source_file)
    baseline_sha_before = _sha256_file(baseline_file)
    degradation: dict[str, Any] | None = None
    record: dict[str, Any]
    try:
        degradation = build_degradation_profile(source_file, profile=profile)
        if degradation["status"] != SUPPORTED_TARGET_DEGRADATION:
            shutil.copyfile(baseline_file, output_file)
            record = {
                "algorithm_id": ALGORITHM_ID,
                "algorithm_version": ALGORITHM_VERSION,
                "profile": profile.canonical_parameters(),
                "degradation_profile": degradation,
                "restoration_activation": NO_OP,
                "no_op_reason": degradation["reason"],
                "raw_proposal": "NOT_EXECUTED",
                "bounded_residual": "ZERO",
                "alpha_lock_status": "BASELINE_BYTE_IDENTITY",
                "output_pixel_sha256": None,
            }
        else:
            source, _source_icc, _source_format = _normalized_image(source_file)
            baseline, baseline_icc, _baseline_format = _normalized_image(baseline_file)
            if baseline.mode not in {"RGB", "RGBA"}:
                raise ValueError(f"BASELINE_MODE_UNSUPPORTED:{baseline.mode}")
            baseline_array = np.asarray(baseline, dtype=np.uint8)
            baseline_rgb = baseline_array[..., :3]
            raw_residual, raw_record = _raw_source_direct_residual(
                source, baseline.size, profile
            )
            protection_scale, protection_record = build_protection_scale(
                baseline_rgb, profile=profile
            )
            candidate_rgb, budget_record = apply_bounded_residual(
                baseline_rgb,
                raw_residual,
                protection_scale=protection_scale,
                protection_reliable=protection_record["status"] == "PASS",
                profile=profile,
            )
            if baseline.mode == "RGBA":
                output_array = attach_baseline_alpha(candidate_rgb, baseline_array)
                alpha_lock_status = (
                    "PASS"
                    if np.array_equal(output_array[..., 3], baseline_array[..., 3])
                    else "FAIL"
                )
                output_image = Image.fromarray(output_array, "RGBA")
            else:
                output_array = candidate_rgb
                alpha_lock_status = "PASS_NOT_APPLICABLE_OPAQUE"
                output_image = Image.fromarray(output_array, "RGB")
            if np.array_equal(output_array, baseline_array):
                shutil.copyfile(baseline_file, output_file)
                output_encoding = "BASELINE_BYTE_IDENTITY"
            else:
                save_kwargs: dict[str, Any] = {
                    "format": "PNG",
                    "compress_level": 6,
                    "optimize": False,
                }
                if baseline_icc:
                    save_kwargs["icc_profile"] = baseline_icc
                output_image.save(output_file, **save_kwargs)
                output_encoding = "DETERMINISTIC_PNG_COMPRESS_LEVEL_6"
            record = {
                "algorithm_id": ALGORITHM_ID,
                "algorithm_version": ALGORITHM_VERSION,
                "profile": profile.canonical_parameters(),
                "degradation_profile": degradation,
                "restoration_activation": budget_record["restoration_activation"],
                "no_op_reason": budget_record.get("fail_closed_reason"),
                "raw_proposal": raw_record,
                "protection_masks_metadata": protection_record,
                "bounded_residual": budget_record,
                "alpha_lock_status": alpha_lock_status,
                "output_encoding": output_encoding,
                "output_pixel_sha256": _pixel_sha256(output_array),
            }
    except Exception as exc:
        shutil.copyfile(baseline_file, output_file)
        record = {
            "algorithm_id": ALGORITHM_ID,
            "algorithm_version": ALGORITHM_VERSION,
            "profile": profile.canonical_parameters(),
            "degradation_profile": degradation,
            "restoration_activation": NO_OP,
            "no_op_reason": f"FAIL_CLOSED:{type(exc).__name__}:{exc}",
            "raw_proposal": "NOT_ADMISSIBLE",
            "bounded_residual": {
                "contract_version": RESIDUAL_CONTRACT_VERSION,
                "fail_closed": True,
                "fail_closed_reason": f"{type(exc).__name__}:{exc}",
            },
            "alpha_lock_status": "BASELINE_BYTE_IDENTITY",
            "output_pixel_sha256": None,
        }

    source_unchanged = _sha256_file(source_file) == source_sha_before
    baseline_unchanged = _sha256_file(baseline_file) == baseline_sha_before
    record.update(
        {
            "source_unchanged": source_unchanged,
            "baseline_unchanged": baseline_unchanged,
            "output_sha256": _sha256_file(output_file),
        }
    )
    if not source_unchanged or not baseline_unchanged:
        raise RuntimeError("READ_ONLY_INPUT_INTEGRITY_VIOLATION")
    if record_path is not None:
        target = Path(record_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    return record


def bounded_restoration_candidate(request: CandidateExecutionRequest) -> None:
    """E4K-02 Candidate Framework executor adapter."""

    restore_bounded_candidate(
        request.source_path,
        request.baseline_path,
        request.output_path,
        record_path=request.run_directory
        / "budget_records"
        / "bounded_restoration_record.json",
    )


__all__ = [
    "ACTIVE",
    "ALGORITHM_ID",
    "ALGORITHM_VERSION",
    "BoundedRestorationProfile",
    "DEGRADATION_PROFILE_VERSION",
    "HALO_RINGING_SUPPRESSION_VERSION",
    "HIGH_FREQUENCY_BUDGET_VERSION",
    "NEED_PROOF",
    "NO_OP",
    "PROFILE_ID",
    "PROTECTED_STRUCTURE_MASK_VERSION",
    "RESIDUAL_CONTRACT_VERSION",
    "SAFE_PROFILE",
    "SUPPORTED_TARGET_DEGRADATION",
    "TARGET_DEGRADATION_FAMILY",
    "THRESHOLD_PROVENANCE_VERSION",
    "UNSUPPORTED",
    "apply_bounded_residual",
    "attach_baseline_alpha",
    "bounded_restoration_candidate",
    "bounded_candidate_definition",
    "build_degradation_profile",
    "build_threshold_provenance",
    "build_protection_scale",
    "restore_bounded_candidate",
]
