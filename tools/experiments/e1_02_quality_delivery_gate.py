from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.algorithms.text_clarity import detect_text_like_regions
from engine.analysis.image_type_detector import detect_image_type
from engine.analysis.quality_compare import compare_quality
from engine.analysis.quality_metrics import compute_quality_metrics
from tools.experiments.e1_01_real_information_baseline import (
    OUTPUT_ROOT as E1_01_ROOT,
    atomic_write_json,
    directory_state,
    map_normalized_box,
    relative_path,
    rerender_candidate_comparisons,
    sha256_file,
    validate_manifest,
)


E1_01_MANIFEST = E1_01_ROOT / "manifest.json"
OUTPUT_ROOT = REPO_ROOT / "artifacts" / "e1_02_quality_delivery_gate_v1"

GATE_VERSION = "HDDE_E1_02_QUALITY_DELIVERY_GATE_V1"
METRIC_PROTOCOL_VERSION = "E1_02_METRICS_V1_CONTROL_CALIBRATED_NOT_PRODUCTION_CALIBRATED"
EVALUATION_SCHEMA_VERSION = "E1_02_EVALUATION_SCHEMA_V1"
REPLAY_BINDING_VERSION = "REPLAY_BINDING_V1"
HUMAN_REVIEW_SCHEMA_VERSION = "HUMAN_REVIEW_EVIDENCE_V1"
MANDATORY_GATE_AGGREGATION_VERSION = "MANDATORY_GATE_AGGREGATION_V1"
PRODUCT_DELIVERY_AUTHORITY_VERSION = "PRODUCT_DELIVERY_AUTHORITY_V1"
NO_PROCESSING_NEEDED_CANDIDATE_POLICY = "BYPASS"
NO_PROCESSING_NEEDED_BASELINE_ARTIFACT = "NONE"
NO_PROCESSING_NEEDED_FALLBACK = "NOT_APPLICABLE"

PRODUCT = "PRODUCT"
CONTROL_ZERO = "CONTROL_ZERO"
CONTROL_NEGATIVE = "CONTROL_NEGATIVE"
CONTROL_ORACLE = "CONTROL_ORACLE"
CANDIDATE_CLASSES = {PRODUCT, CONTROL_ZERO, CONTROL_NEGATIVE, CONTROL_ORACLE}

QUALITY_GAIN_PROVEN = "QUALITY_GAIN_PROVEN"
QUALITY_GAIN_NOT_PROVEN = "QUALITY_GAIN_NOT_PROVEN"
QUALITY_GAIN_REJECTED = "QUALITY_GAIN_REJECTED"

MANDATORY_GATE_NAMES = (
    "ELIGIBILITY_GATE",
    "REPLAY_BINDING_GATE",
    "HARD_SAFETY_GATE",
    "GEOMETRY_SAFETY_GATE",
    "ALPHA_SAFETY_GATE",
    "EDGE_ARTIFACT_GATE",
    "HIGH_FREQUENCY_GATE",
    "COLOR_SAFETY_GATE",
    "TEXT_FIDELITY_GATE",
    "DETAIL_GAIN_GATE",
    "HUMAN_REVIEW_BINDING_GATE",
)
MANDATORY_GATE_STATUSES = frozenset({"PASS", "FAIL", "NEED_PROOF", "NOT_APPLICABLE"})
NOT_APPLICABLE_ALLOWLIST: frozenset[str] = frozenset()

REQUIRED_SPEC_FIELDS = (
    "candidate_id",
    "candidate_class",
    "candidate_identity",
    "algorithm_identity",
    "parameters",
    "canonical_parameters",
    "source_binding_sha256",
    "baseline_binding_sha256",
    "gt_binding_sha256_or_none",
    "roi_set_sha256",
    "replay_identity",
    "replay_contract",
    "evaluation_schema_version",
)

# These thresholds validate the V1 gate against declared controls. They are not
# production-adoption thresholds and cannot prove a product Candidate.
CONTROL_THRESHOLDS = {
    "blur_sharpness_ratio_max": 0.72,
    "oversharpen_sharpness_ratio_min": 1.35,
    "overshoot_fraction_delta_min": 0.001,
    "ringing_large_delta_fraction_min": 0.025,
    "ringing_bipolar_fraction_min": 0.08,
    "high_frequency_ratio_max": 1.85,
    "flat_noise_delta_max": 1.8,
    "high_frequency_tile_mean_p95_max": 12.0,
    "color_delta_e76_mean_max": 6.0,
    "lightness_delta_abs_max": 8.0,
    "saturation_delta_abs_max": 12.0,
    "gt_mae_relative_improvement_min": 0.08,
    "gt_ssim_improvement_min": 0.0001,
    "gt_ssim_headroom_relative_min": 0.05,
    "geometry_translation_review_px": 1.5,
    "geometry_phase_translation_analysis_px_min": 1.5,
    "geometry_scale_delta_max": 0.025,
    "geometry_shear_max": 0.008,
    "geometry_ecc_confidence_min": 0.35,
    "geometry_phase_translation_confidence_min": 0.85,
    "geometry_constant_padding_range_max": 1.0,
    "geometry_constant_padding_reference_range_min": 4.0,
    "geometry_constant_padding_border_mae_min": 4.0,
    "local_color_delta_e76_p99_max": 28.0,
    "local_color_severe_fraction_max": 0.015,
    "black_edge_fraction_max": 0.012,
    "white_edge_fraction_max": 0.012,
    "text_edge_continuity_min": 0.72,
    "text_foreground_ratio_min": 0.72,
    "text_foreground_ratio_max": 1.35,
    "text_double_edge_fraction_max": 0.08,
}


class E102Error(RuntimeError):
    pass


def aggregate_mandatory_gates(statuses: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize the fixed mandatory gate set without trusting caller summaries."""
    supplied = statuses if isinstance(statuses, dict) else {}
    normalized: dict[str, str] = {}
    blockers: list[dict[str, str]] = []
    for name in MANDATORY_GATE_NAMES:
        raw = supplied.get(name)
        if raw is None:
            normalized[name] = "NEED_PROOF"
            blockers.append({"gate": name, "status": "NEED_PROOF", "reason": "MISSING_GATE_STATUS"})
        elif raw not in MANDATORY_GATE_STATUSES:
            normalized[name] = "NEED_PROOF"
            blockers.append({"gate": name, "status": "NEED_PROOF", "reason": "UNKNOWN_GATE_STATUS"})
        elif raw == "NOT_APPLICABLE" and name not in NOT_APPLICABLE_ALLOWLIST:
            normalized[name] = "NOT_APPLICABLE"
            blockers.append({"gate": name, "status": "NOT_APPLICABLE", "reason": "NOT_APPLICABLE_NOT_ALLOWLISTED"})
        else:
            normalized[name] = raw
            if raw != "PASS":
                blockers.append({"gate": name, "status": raw, "reason": f"MANDATORY_GATE_{raw}"})

    for name in sorted(set(supplied) - set(MANDATORY_GATE_NAMES)):
        blockers.append({"gate": str(name), "status": "NEED_PROOF", "reason": "UNKNOWN_GATE_NAME"})

    return {
        "aggregation_version": MANDATORY_GATE_AGGREGATION_VERSION,
        "sub_gate_statuses": normalized,
        "blocking_gates": blockers,
        "mandatory_gate_complete": not blockers and all(value == "PASS" for value in normalized.values()),
        "not_applicable_allowlist": sorted(NOT_APPLICABLE_ALLOWLIST),
    }


def _validated_mandatory_aggregation(value: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    supplied = value if isinstance(value, dict) else {}
    recomputed = aggregate_mandatory_gates(supplied.get("sub_gate_statuses"))
    structurally_valid = (
        supplied.get("aggregation_version") == MANDATORY_GATE_AGGREGATION_VERSION
        and supplied.get("sub_gate_statuses") == recomputed["sub_gate_statuses"]
        and supplied.get("blocking_gates") == recomputed["blocking_gates"]
        and supplied.get("mandatory_gate_complete") is recomputed["mandatory_gate_complete"]
    )
    if structurally_valid:
        return recomputed, True
    invalid = aggregate_mandatory_gates({})
    invalid["blocking_gates"].insert(
        0,
        {"gate": "MANDATORY_GATE_AGGREGATION", "status": "NEED_PROOF", "reason": "AGGREGATION_INVALID_OR_MISSING"},
    )
    invalid["mandatory_gate_complete"] = False
    return invalid, False


def authorize_product_delivery(
    *,
    quality_gain_status: str,
    hard_safety_status: str,
    mandatory_gate_aggregation: dict[str, Any] | None,
    human_review_required: bool,
    review_product_admissible: bool,
    test_vector_only: bool,
) -> dict[str, Any]:
    """The sole authority for a PRODUCT delivery decision."""
    aggregation, aggregation_valid = _validated_mandatory_aggregation(mandatory_gate_aggregation)
    statuses = aggregation["sub_gate_statuses"]
    failure_gates = [name for name, status in statuses.items() if status in {"FAIL", "NOT_APPLICABLE"}]
    need_proof_gates = [name for name, status in statuses.items() if status == "NEED_PROOF"]
    reasons: list[str] = []

    if hard_safety_status == "FAIL":
        reasons.append("HARD_SAFETY_FAIL")
    elif hard_safety_status != "PASS":
        reasons.append("HARD_SAFETY_NEED_PROOF")
    if failure_gates:
        reasons.extend(f"MANDATORY_FAIL:{name}" for name in failure_gates)
    if not aggregation_valid:
        reasons.append("MANDATORY_AGGREGATION_INVALID_OR_MISSING")
    if need_proof_gates:
        reasons.extend(f"MANDATORY_NEED_PROOF:{name}" for name in need_proof_gates)
    if quality_gain_status == QUALITY_GAIN_REJECTED:
        reasons.append("QUALITY_GAIN_REJECTED")
    elif quality_gain_status != QUALITY_GAIN_PROVEN:
        reasons.append("QUALITY_GAIN_NOT_PROVEN")
    if human_review_required and not review_product_admissible:
        reasons.append("PRODUCT_REVIEW_NOT_ADMISSIBLE")

    if hard_safety_status == "FAIL" or failure_gates or quality_gain_status == QUALITY_GAIN_REJECTED:
        prospective = "FAIL"
    elif (
        hard_safety_status != "PASS"
        or not aggregation_valid
        or need_proof_gates
        or not aggregation["mandatory_gate_complete"]
        or quality_gain_status != QUALITY_GAIN_PROVEN
        or (human_review_required and not review_product_admissible)
    ):
        prospective = "REVIEW"
    else:
        prospective = "PASS"

    delivery = "REVIEW" if test_vector_only and prospective == "PASS" else prospective
    if test_vector_only:
        reasons.append("CONTRACT_TEST_VECTOR_NOT_PRODUCT_AUTHORIZATION")
    return {
        "authority_version": PRODUCT_DELIVERY_AUTHORITY_VERSION,
        "delivery_status": delivery,
        "production_authorized": delivery == "PASS" and not test_vector_only,
        "decision_reasons": list(dict.fromkeys(reasons)),
        "mandatory_gate_complete": aggregation["mandatory_gate_complete"],
        "mandatory_gate_aggregation": aggregation,
        "contract_test_expected_delivery": prospective if test_vector_only else None,
        "test_vector_only": bool(test_vector_only),
    }


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_parameters(parameters: Any) -> dict[str, Any]:
    if parameters is None:
        raise E102Error("PARAMETERS_NONE")
    if not isinstance(parameters, dict):
        raise E102Error("PARAMETERS_NOT_OBJECT")
    try:
        encoded = json.dumps(parameters, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise E102Error("PARAMETERS_NOT_CANONICAL_JSON") from exc
    if not isinstance(decoded, dict):
        raise E102Error("PARAMETERS_NOT_OBJECT")
    return decoded


def _replay_contract(
    case: dict[str, Any],
    candidate_sha256: str,
    algorithm_identity: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    return {
        "binding_version": REPLAY_BINDING_VERSION,
        "case_id": case["case_id"],
        "source_sha256": case["input"]["sha256"],
        "baseline_sha256": case["safe_base"]["sha256"],
        "candidate_sha256": candidate_sha256,
        "gt_sha256_or_none": "NONE" if case["gt"] is None else case["gt"]["sha256"],
        "roi_manifest_hash": _canonical_sha256(case["roi"]),
        "algorithm_identity": algorithm_identity,
        "canonical_parameters": parameters,
        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
    }


def compute_replay_identity(
    case: dict[str, Any],
    candidate_sha256: str,
    algorithm_identity: str,
    parameters: Any,
) -> tuple[str, dict[str, Any]]:
    canonical = _canonical_parameters(parameters)
    contract = _replay_contract(case, candidate_sha256, algorithm_identity, canonical)
    return _canonical_sha256(contract), contract


def _array_sha256(array: np.ndarray) -> str:
    payload = hashlib.sha256()
    payload.update(str(array.dtype).encode("ascii"))
    payload.update(str(tuple(array.shape)).encode("ascii"))
    payload.update(np.ascontiguousarray(array).tobytes())
    return payload.hexdigest()


def _manifest_asset(path_value: str) -> Path:
    path = Path(path_value)
    resolved = path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise E102Error(f"E1_01_ASSET_OUTSIDE_REPOSITORY:{resolved}") from exc
    if not resolved.is_file():
        raise E102Error(f"E1_01_ASSET_MISSING:{resolved}")
    return resolved


def _load_rgba(path: Path) -> np.ndarray:
    try:
        with Image.open(path) as opened:
            opened.load()
            normalized = ImageOps.exif_transpose(opened).convert("RGBA")
            return np.asarray(normalized, dtype=np.uint8)
    except Exception as exc:
        raise E102Error(f"IMAGE_DECODE_FAILED:{path}") from exc


def _analysis_bgr(rgba: np.ndarray, maximum_edge: int = 960) -> np.ndarray:
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise E102Error("RGBA_ARRAY_REQUIRED")
    alpha = rgba[..., 3:4].astype(np.float32) / 255.0
    rgb = rgba[..., :3].astype(np.float32)
    composited = np.rint(rgb * alpha + 127.0 * (1.0 - alpha)).astype(np.uint8)
    bgr = cv2.cvtColor(composited, cv2.COLOR_RGB2BGR)
    height, width = bgr.shape[:2]
    scale = min(1.0, float(maximum_edge) / float(max(height, width)))
    if scale < 1.0:
        target = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
        bgr = cv2.resize(bgr, target, interpolation=cv2.INTER_AREA)
    return bgr


def _resize_like(reference: np.ndarray, target: np.ndarray) -> np.ndarray:
    if reference.shape[:2] == target.shape[:2]:
        return reference
    interpolation = cv2.INTER_AREA if reference.shape[0] > target.shape[0] else cv2.INTER_CUBIC
    return cv2.resize(reference, (target.shape[1], target.shape[0]), interpolation=interpolation)


def _gray(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)


def _global_ssim(reference: np.ndarray, candidate: np.ndarray) -> float:
    ref = _gray(_resize_like(reference, candidate))
    out = _gray(candidate)
    mean_ref = float(ref.mean())
    mean_out = float(out.mean())
    var_ref = float(ref.var())
    var_out = float(out.var())
    covariance = float(np.mean((ref - mean_ref) * (out - mean_out)))
    c1 = (0.01 * 255.0) ** 2
    c2 = (0.03 * 255.0) ** 2
    numerator = (2.0 * mean_ref * mean_out + c1) * (2.0 * covariance + c2)
    denominator = (mean_ref**2 + mean_out**2 + c1) * (var_ref + var_out + c2)
    return 1.0 if denominator == 0.0 else float(np.clip(numerator / denominator, -1.0, 1.0))


def _edge_facts(reference: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
    ref = _gray(_resize_like(reference, candidate))
    out = _gray(candidate)
    ref_u8 = np.clip(ref, 0, 255).astype(np.uint8)
    out_u8 = np.clip(out, 0, 255).astype(np.uint8)
    ref_blur = cv2.GaussianBlur(ref_u8, (5, 5), 0)
    out_blur = cv2.GaussianBlur(out_u8, (5, 5), 0)
    ref_edges = cv2.Canny(ref_blur, 50, 150, L2gradient=True) > 0
    out_edges = cv2.Canny(out_blur, 50, 150, L2gradient=True) > 0
    kernel3 = np.ones((3, 3), np.uint8)
    kernel7 = np.ones((7, 7), np.uint8)
    ref_near = cv2.dilate(ref_edges.astype(np.uint8), kernel3) > 0
    out_near = cv2.dilate(out_edges.astype(np.uint8), kernel3) > 0
    continuity = float(np.count_nonzero(ref_edges & out_near) / max(np.count_nonzero(ref_edges), 1))
    band = (cv2.dilate(ref_edges.astype(np.uint8), kernel7) > 0) & ~ref_edges
    difference = out - ref
    local_max = cv2.dilate(ref, np.ones((5, 5), np.uint8))
    local_min = cv2.erode(ref, np.ones((5, 5), np.uint8))
    overshoot = ((out > local_max + 4.0) | (out < local_min - 4.0)) & (band | ref_near)
    band_values = difference[band]
    if band_values.size:
        large = np.abs(band_values) >= 10.0
        positive = band_values >= 8.0
        negative = band_values <= -8.0
        large_fraction = float(np.mean(large))
        bipolar_fraction = float(min(np.mean(positive), np.mean(negative)) * 2.0)
        band_mae = float(np.mean(np.abs(band_values)))
        white_edge_fraction = float(np.mean(band_values >= 18.0))
        black_edge_fraction = float(np.mean(band_values <= -18.0))
    else:
        large_fraction = 0.0
        bipolar_fraction = 0.0
        band_mae = 0.0
        white_edge_fraction = 0.0
        black_edge_fraction = 0.0
    return {
        "reference_edge_density": round(float(np.mean(ref_edges)), 8),
        "candidate_edge_density": round(float(np.mean(out_edges)), 8),
        "edge_continuity_ratio": round(continuity, 8),
        "edge_band_mae": round(band_mae, 8),
        "edge_band_large_delta_fraction": round(large_fraction, 8),
        "edge_band_bipolar_fraction": round(bipolar_fraction, 8),
        "overshoot_fraction": round(float(np.mean(overshoot)), 8),
        "white_edge_fraction": round(white_edge_fraction, 8),
        "black_edge_fraction": round(black_edge_fraction, 8),
    }


def _pair_metrics(reference: np.ndarray, candidate: np.ndarray) -> dict[str, Any]:
    ref = _resize_like(reference, candidate)
    ref_f = ref.astype(np.float32)
    out_f = candidate.astype(np.float32)
    delta = out_f - ref_f
    abs_delta = np.abs(delta)
    ref_gray = _gray(ref)
    out_gray = _gray(candidate)
    ref_lap = cv2.Laplacian(ref_gray, cv2.CV_32F)
    out_lap = cv2.Laplacian(out_gray, cv2.CV_32F)
    ref_hf = np.abs(ref_gray - cv2.GaussianBlur(ref_gray, (0, 0), 0.8))
    out_hf = np.abs(out_gray - cv2.GaussianBlur(out_gray, (0, 0), 0.8))
    hf_delta = out_hf - ref_hf
    tile_means = [
        float(np.mean(hf_delta[y : y + 16, x : x + 16]))
        for y in range(0, max(hf_delta.shape[0] - 15, 1), 16)
        for x in range(0, max(hf_delta.shape[1] - 15, 1), 16)
    ]
    hf_tile_mean_p95 = float(np.percentile(tile_means, 95)) if tile_means else float(np.mean(hf_delta))
    ref_smooth = cv2.GaussianBlur(ref_gray, (0, 0), 2.0)
    out_smooth = cv2.GaussianBlur(out_gray, (0, 0), 2.0)
    ref_gradient = cv2.magnitude(
        cv2.Sobel(ref_smooth, cv2.CV_32F, 1, 0, ksize=3),
        cv2.Sobel(ref_smooth, cv2.CV_32F, 0, 1, ksize=3),
    )
    out_gradient = cv2.magnitude(
        cv2.Sobel(out_smooth, cv2.CV_32F, 1, 0, ksize=3),
        cv2.Sobel(out_smooth, cv2.CV_32F, 0, 1, ksize=3),
    )
    flat_mask = (ref_gradient < 5.0) & (out_gradient < 5.0)
    structural_edges = (
        (cv2.Canny(np.clip(ref_smooth, 0, 255).astype(np.uint8), 30, 90, L2gradient=True) > 0)
        | (cv2.Canny(np.clip(out_smooth, 0, 255).astype(np.uint8), 30, 90, L2gradient=True) > 0)
    )
    structural_band = cv2.dilate(structural_edges.astype(np.uint8), np.ones((17, 17), np.uint8)) > 0
    flat_mask &= ~structural_band
    ref_flat_noise = float(np.std(ref_hf[flat_mask])) if np.any(flat_mask) else float(np.std(ref_hf))
    out_flat_noise = float(np.std(out_hf[flat_mask])) if np.any(flat_mask) else float(np.std(out_hf))
    ref_flat_p90 = float(np.percentile(ref_hf[flat_mask], 90)) if np.any(flat_mask) else float(np.percentile(ref_hf, 90))
    out_flat_p90 = float(np.percentile(out_hf[flat_mask], 90)) if np.any(flat_mask) else float(np.percentile(out_hf, 90))
    ref_lab = cv2.cvtColor(ref.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)
    out_lab = cv2.cvtColor(candidate.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)
    delta_e = np.linalg.norm(out_lab - ref_lab, axis=2)
    ref_low = cv2.GaussianBlur(ref.astype(np.float32) / 255.0, (0, 0), 3.0)
    out_low = cv2.GaussianBlur(candidate.astype(np.float32) / 255.0, (0, 0), 3.0)
    ref_low_lab = cv2.cvtColor(ref_low, cv2.COLOR_BGR2LAB)
    out_low_lab = cv2.cvtColor(out_low, cv2.COLOR_BGR2LAB)
    local_color_delta = np.linalg.norm(out_low_lab - ref_low_lab, axis=2)
    ref_low_hsv = cv2.cvtColor(np.clip(ref_low * 255.0, 0, 255).astype(np.uint8), cv2.COLOR_BGR2HSV)
    out_low_hsv = cv2.cvtColor(np.clip(out_low * 255.0, 0, 255).astype(np.uint8), cv2.COLOR_BGR2HSV)
    ref_hsv = cv2.cvtColor(ref, cv2.COLOR_BGR2HSV)
    out_hsv = cv2.cvtColor(candidate, cv2.COLOR_BGR2HSV)
    reference_metrics = compute_quality_metrics(ref)
    candidate_metrics = compute_quality_metrics(candidate)
    proxy = compare_quality(ref, candidate)
    edge = _edge_facts(ref, candidate)
    sharpness_ratio = float(candidate_metrics["sharpness"] / max(reference_metrics["sharpness"], 1e-6))
    high_frequency_ratio = float(out_hf.mean() / max(float(ref_hf.mean()), 1e-6))
    return {
        "measurement_domain": {
            "width": int(candidate.shape[1]),
            "height": int(candidate.shape[0]),
            "color_space": "sRGB_assumed_BGR_for_OpenCV; Lab_float_D65_OpenCV",
            "alpha_composite_background": 127,
        },
        "reference_metrics": reference_metrics,
        "candidate_metrics": candidate_metrics,
        "delta_metrics": {
            "rgb_mae": round(float(abs_delta.mean()), 8),
            "rgb_max_abs_delta": int(np.max(abs_delta)),
            "rgb_changed_fraction": round(float(np.mean(np.max(abs_delta, axis=2) > 0)), 8),
            "global_ssim": round(_global_ssim(ref, candidate), 8),
            "sharpness_ratio": round(sharpness_ratio, 8),
            "high_frequency_ratio": round(high_frequency_ratio, 8),
            "flat_noise_delta": round(out_flat_noise - ref_flat_noise, 8),
            "flat_noise_p90_delta": round(out_flat_p90 - ref_flat_p90, 8),
            "high_frequency_tile_mean_p95": round(hf_tile_mean_p95, 8),
            "delta_e76_mean": round(float(delta_e.mean()), 8),
            "delta_e76_p95": round(float(np.percentile(delta_e, 95)), 8),
            "local_color_delta_e76_p99": round(float(np.percentile(local_color_delta, 99)), 8),
            "local_color_severe_fraction": round(float(np.mean(local_color_delta >= 24.0)), 8),
            "low_frequency_color_delta_e76_mean": round(float(np.mean(local_color_delta)), 8),
            "low_frequency_lightness_delta": round(float(out_low_lab[..., 0].mean() - ref_low_lab[..., 0].mean()), 8),
            "low_frequency_saturation_delta": round(
                float(out_low_hsv[..., 1].astype(np.float32).mean() - ref_low_hsv[..., 1].astype(np.float32).mean()),
                8,
            ),
            "lightness_delta": round(float(out_lab[..., 0].mean() - ref_lab[..., 0].mean()), 8),
            "saturation_delta": round(
                float(out_hsv[..., 1].astype(np.float32).mean() - ref_hsv[..., 1].astype(np.float32).mean()),
                8,
            ),
            **edge,
        },
        "existing_quality_compare_proxy": proxy,
    }


def _alpha_facts(baseline_rgba: np.ndarray, candidate_rgba: np.ndarray) -> dict[str, Any]:
    if baseline_rgba.shape[:2] != candidate_rgba.shape[:2]:
        return {"status": "FAIL", "reason": "ALPHA_GEOMETRY_MISMATCH"}
    baseline = baseline_rgba[..., 3].astype(np.int16)
    candidate = candidate_rgba[..., 3].astype(np.int16)
    delta = np.abs(candidate - baseline)
    semi = (baseline > 0) & (baseline < 255)
    gradient_x = np.zeros_like(semi)
    gradient_y = np.zeros_like(semi)
    gradient_x[:, 1:] = baseline[:, 1:] != baseline[:, :-1]
    gradient_y[1:, :] = baseline[1:, :] != baseline[:-1, :]
    boundary = gradient_x | gradient_y
    return {
        "status": "PASS" if int(np.max(delta)) == 0 else "FAIL",
        "alpha_identity": bool(int(np.max(delta)) == 0),
        "alpha_pixel_delta_count": int(np.count_nonzero(delta)),
        "maximum_alpha_delta": int(np.max(delta)),
        "semi_transparent_pixel_count": int(np.count_nonzero(semi)),
        "alpha_boundary_pixel_count": int(np.count_nonzero(boundary)),
        "alpha_boundary_delta_count": int(np.count_nonzero((delta > 0) & boundary)),
    }


def _geometry_measurement(baseline_rgba: np.ndarray, candidate_rgba: np.ndarray) -> dict[str, Any]:
    baseline_height, baseline_width = baseline_rgba.shape[:2]
    candidate_height, candidate_width = candidate_rgba.shape[:2]
    dimensions = {
        "baseline": [baseline_width, baseline_height],
        "candidate": [candidate_width, candidate_height],
    }
    if (baseline_height, baseline_width) != (candidate_height, candidate_width):
        return {
            "status": "FAIL",
            "decision": "DIMENSIONS_OR_ASPECT_RATIO_CHANGED",
            "decision_reason": "DIMENSIONS_OR_ASPECT_RATIO_CHANGED",
            "dimensions": dimensions,
            "estimated_transform": None,
            "confidence": 1.0,
            "residual_or_error": None,
        }

    baseline = _analysis_bgr(baseline_rgba, maximum_edge=240)
    candidate = _analysis_bgr(candidate_rgba, maximum_edge=240)
    ref = _gray(baseline).astype(np.float32) / 255.0
    out = _gray(candidate).astype(np.float32) / 255.0
    if np.array_equal(baseline_rgba, candidate_rgba):
        return {
            "status": "PASS",
            "decision": "PIXEL_IDENTICAL_GEOMETRY",
            "decision_reason": "PIXEL_IDENTICAL_GEOMETRY",
            "dimensions": dimensions,
            "estimated_transform": {"matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], "translation_px": [0.0, 0.0], "translation_magnitude_px": 0.0, "translation_method": "PIXEL_IDENTITY", "scale": [1.0, 1.0], "shear": 0.0},
            "confidence": 1.0,
            "residual_or_error": 0.0,
        }

    gradient_energy = float(np.mean(cv2.magnitude(
        cv2.Sobel(ref, cv2.CV_32F, 1, 0, ksize=3),
        cv2.Sobel(ref, cv2.CV_32F, 0, 1, ksize=3),
    )))
    if gradient_energy < 0.003:
        return {
            "status": "REVIEW",
            "decision": "LOW_TEXTURE_GEOMETRY_NEED_PROOF",
            "decision_reason": "LOW_TEXTURE_GEOMETRY_NEED_PROOF",
            "dimensions": dimensions,
            "estimated_transform": None,
            "confidence": 0.0,
            "residual_or_error": None,
        }

    border_width = max(2, int(round(min(ref.shape) * 0.05)))
    border_mask = np.zeros(ref.shape, dtype=bool)
    border_mask[:border_width, :] = True
    border_mask[-border_width:, :] = True
    border_mask[:, :border_width] = True
    border_mask[:, -border_width:] = True
    candidate_border = candidate[border_mask]
    reference_border = baseline[border_mask]
    candidate_border_range = float(np.max(candidate_border) - np.min(candidate_border))
    reference_border_range = float(np.max(reference_border) - np.min(reference_border))
    border_mean_absolute_delta = float(np.mean(np.abs(candidate_border.astype(np.float32) - reference_border.astype(np.float32))))
    constant_padding_border_detected = (
        candidate_border_range <= CONTROL_THRESHOLDS["geometry_constant_padding_range_max"]
        and reference_border_range >= CONTROL_THRESHOLDS["geometry_constant_padding_reference_range_min"]
        and border_mean_absolute_delta >= CONTROL_THRESHOLDS["geometry_constant_padding_border_mae_min"]
    )

    window = cv2.createHanningWindow((ref.shape[1], ref.shape[0]), cv2.CV_32F)
    phase_shift, phase_response = cv2.phaseCorrelate(ref, out, window)
    warp = np.eye(2, 3, dtype=np.float32)
    ecc_confidence = 0.0
    ecc_error: str | None = None
    try:
        ecc_confidence, warp = cv2.findTransformECC(
            ref,
            out,
            warp,
            cv2.MOTION_AFFINE,
            (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 15, 1e-4),
            None,
            3,
        )
    except cv2.error as exc:
        ecc_error = str(exc).splitlines()[0]

    a, b, tx = (float(value) for value in warp[0])
    c, d, ty = (float(value) for value in warp[1])
    scale_x = float(np.hypot(a, c))
    scale_y = float(np.hypot(b, d))
    shear = float(abs(a * b + c * d))
    phase_scale_x = baseline_width / float(ref.shape[1])
    phase_scale_y = baseline_height / float(ref.shape[0])
    phase_translation_x = float(phase_shift[0] * phase_scale_x)
    phase_translation_y = float(phase_shift[1] * phase_scale_y)
    phase_translation_magnitude = float(np.hypot(phase_translation_x, phase_translation_y))
    phase_translation_analysis_magnitude = float(np.hypot(float(phase_shift[0]), float(phase_shift[1])))
    ecc_translation_x = float(tx * phase_scale_x)
    ecc_translation_y = float(ty * phase_scale_y)
    ecc_translation_magnitude = float(np.hypot(ecc_translation_x, ecc_translation_y))
    phase_translation_authoritative = (
        float(phase_response) >= CONTROL_THRESHOLDS["geometry_phase_translation_confidence_min"]
        and phase_translation_magnitude > CONTROL_THRESHOLDS["geometry_translation_review_px"]
        and phase_translation_analysis_magnitude > CONTROL_THRESHOLDS["geometry_phase_translation_analysis_px_min"]
    )
    if phase_translation_authoritative:
        translation_x = phase_translation_x
        translation_y = phase_translation_y
        translation_magnitude = phase_translation_magnitude
        decision_warp = np.array(
            [[1.0, 0.0, float(phase_shift[0])], [0.0, 1.0, float(phase_shift[1])]],
            dtype=np.float32,
        )
        decision_scale_x = 1.0
        decision_scale_y = 1.0
        decision_shear = 0.0
        translation_method = "PHASE_CORRELATION"
    else:
        translation_x = ecc_translation_x
        translation_y = ecc_translation_y
        translation_magnitude = ecc_translation_magnitude
        decision_warp = warp
        decision_scale_x = scale_x
        decision_scale_y = scale_y
        decision_shear = shear
        translation_method = "ECC_AFFINE"
    aligned = cv2.warpAffine(
        out,
        decision_warp,
        (ref.shape[1], ref.shape[0]),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_REFLECT,
    )
    residual = float(np.mean(np.abs(aligned - ref)))
    confidence_source = float(phase_response) if phase_translation_authoritative else max(float(phase_response), float(ecc_confidence))
    confidence = float(max(0.0, min(1.0, confidence_source)))
    scale_delta = max(abs(scale_x - 1.0), abs(scale_y - 1.0))

    if constant_padding_border_detected:
        status = "FAIL"
        decision = "CROP_PADDING_OR_STRETCH_DETECTED"
    elif phase_translation_authoritative:
        status = "FAIL"
        decision = "TRANSLATION_OR_GEOMETRIC_DRIFT_DETECTED"
    elif scale_delta > CONTROL_THRESHOLDS["geometry_scale_delta_max"] or shear > CONTROL_THRESHOLDS["geometry_shear_max"]:
        status = "FAIL"
        decision = "CROP_PADDING_OR_STRETCH_DETECTED"
    elif translation_magnitude > CONTROL_THRESHOLDS["geometry_translation_review_px"]:
        status = "FAIL"
        decision = "TRANSLATION_OR_GEOMETRIC_DRIFT_DETECTED"
    elif confidence < CONTROL_THRESHOLDS["geometry_ecc_confidence_min"]:
        status = "REVIEW"
        decision = "GEOMETRY_MEASUREMENT_UNCERTAIN"
    else:
        status = "PASS"
        decision = "GEOMETRY_ALIGNED"
    return {
        "status": status,
        "decision": decision,
        "decision_reason": decision,
        "dimensions": dimensions,
        "estimated_transform": {
            "matrix": [
                [round(float(decision_warp[0, 0]), 8), round(float(decision_warp[0, 1]), 8), round(float(decision_warp[0, 2]), 8)],
                [round(float(decision_warp[1, 0]), 8), round(float(decision_warp[1, 1]), 8), round(float(decision_warp[1, 2]), 8)],
            ],
            "translation_px": [round(translation_x, 8), round(translation_y, 8)],
            "translation_magnitude_px": round(translation_magnitude, 8),
            "translation_method": translation_method,
            "phase_translation_px": [round(phase_translation_x, 8), round(phase_translation_y, 8)],
            "phase_translation_analysis_px": [round(float(phase_shift[0]), 8), round(float(phase_shift[1]), 8)],
            "phase_translation_analysis_magnitude_px": round(phase_translation_analysis_magnitude, 8),
            "scale": [round(decision_scale_x, 8), round(decision_scale_y, 8)],
            "shear": round(decision_shear, 8),
            "ecc_scale": [round(scale_x, 8), round(scale_y, 8)],
            "ecc_shear": round(shear, 8),
            "ecc_translation_px": [round(ecc_translation_x, 8), round(ecc_translation_y, 8)],
            "ecc_translation_magnitude_px": round(ecc_translation_magnitude, 8),
        },
        "confidence": round(confidence, 8),
        "phase_response": round(float(phase_response), 8),
        "ecc_confidence": round(float(ecc_confidence), 8),
        "constant_padding_border_detected": constant_padding_border_detected,
        "candidate_border_range": round(candidate_border_range, 8),
        "reference_border_range": round(reference_border_range, 8),
        "border_mean_absolute_delta": round(border_mean_absolute_delta, 8),
        "residual_or_error": round(residual, 8),
        "ecc_error": ecc_error,
    }


def _text_structure_facts(baseline_bgr: np.ndarray, candidate_bgr: np.ndarray) -> dict[str, Any]:
    baseline = _resize_like(baseline_bgr, candidate_bgr)
    reference_gray = np.clip(_gray(baseline), 0, 255).astype(np.uint8)
    candidate_gray = np.clip(_gray(candidate_bgr), 0, 255).astype(np.uint8)

    def foreground(gray: np.ndarray) -> np.ndarray:
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        _, dark = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        _, light = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        return (dark if np.mean(dark > 0) <= np.mean(light > 0) else light) > 0

    reference_foreground = foreground(reference_gray)
    candidate_foreground = foreground(candidate_gray)
    reference_fraction = float(np.mean(reference_foreground))
    candidate_fraction = float(np.mean(candidate_foreground))
    foreground_ratio = candidate_fraction / max(reference_fraction, 1e-6)

    def component_count(mask: np.ndarray) -> int:
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
        return int(sum(1 for area in stats[1:, cv2.CC_STAT_AREA] if area >= 3)) if count > 1 else 0

    reference_components = component_count(reference_foreground)
    candidate_components = component_count(candidate_foreground)
    component_ratio = candidate_components / max(reference_components, 1)
    edge = _edge_facts(baseline, candidate_bgr)
    edge_density_ratio = edge["candidate_edge_density"] / max(edge["reference_edge_density"], 1e-6)
    reliable = reference_fraction >= 0.005 and reference_components > 0 and edge["reference_edge_density"] >= 0.002
    broken = reliable and (
        edge["edge_continuity_ratio"] < CONTROL_THRESHOLDS["text_edge_continuity_min"]
        or (component_ratio > 1.25 and edge["edge_continuity_ratio"] < 0.99)
        or (foreground_ratio < CONTROL_THRESHOLDS["text_foreground_ratio_min"] and component_ratio > 1.15)
    )
    sticking = reliable and (
        foreground_ratio > CONTROL_THRESHOLDS["text_foreground_ratio_max"]
        or (component_ratio < 0.65 and foreground_ratio > 1.08)
    )
    double_edge = reliable and (
        (
            edge["edge_band_bipolar_fraction"] > CONTROL_THRESHOLDS["text_double_edge_fraction_max"]
            and edge_density_ratio > 1.08
        )
        or (
            edge_density_ratio > 1.18
            and 1.05 < foreground_ratio < CONTROL_THRESHOLDS["text_foreground_ratio_max"]
            and 0.8 <= component_ratio <= 1.2
        )
    )
    if broken or sticking or double_edge:
        status = "TEXT_DEGRADED"
    elif np.array_equal(baseline, candidate_bgr):
        status = "TEXT_STABLE"
    elif not reliable:
        status = "NEED_PROOF"
    else:
        status = "TEXT_RISK"
    return {
        "status": status,
        "reliable": bool(reliable),
        "raw_detection": {
            "broken_stroke": bool(broken),
            "sticking": bool(sticking),
            "double_edge": bool(double_edge),
        },
        "metrics": {
            "reference_foreground_fraction": round(reference_fraction, 8),
            "candidate_foreground_fraction": round(candidate_fraction, 8),
            "foreground_ratio": round(float(foreground_ratio), 8),
            "reference_components": reference_components,
            "candidate_components": candidate_components,
            "component_ratio": round(float(component_ratio), 8),
            "edge_density_ratio": round(float(edge_density_ratio), 8),
            "edge_continuity_ratio": edge["edge_continuity_ratio"],
            "edge_band_bipolar_fraction": edge["edge_band_bipolar_fraction"],
        },
    }


def _case_text_structure(
    roi_set: list[dict[str, Any]],
    baseline_rgba: np.ndarray,
    candidate_rgba: np.ndarray,
) -> dict[str, Any] | None:
    records: list[dict[str, Any]] = []
    for roi in roi_set:
        if str(roi.get("roi_type") or "") not in {"CHINESE_TEXT", "TEXT", "LOGO"}:
            continue
        box = map_normalized_box(roi["normalized_box"], (baseline_rgba.shape[1], baseline_rgba.shape[0]))
        baseline = baseline_rgba[box["y0"] : box["y1"], box["x0"] : box["x1"]]
        candidate = candidate_rgba[box["y0"] : box["y1"], box["x0"] : box["x1"]]
        facts = _text_structure_facts(_analysis_bgr(baseline, 720), _analysis_bgr(candidate, 720))
        records.append({"roi_id": roi["roi_id"], **facts})
    if not records:
        return None
    raw = {
        name: any(record["raw_detection"][name] for record in records)
        for name in ("broken_stroke", "sticking", "double_edge")
    }
    if any(raw.values()):
        status = "TEXT_DEGRADED"
    elif any(record["status"] == "NEED_PROOF" for record in records):
        status = "NEED_PROOF"
    elif all(record["status"] == "TEXT_STABLE" for record in records):
        status = "TEXT_STABLE"
    else:
        status = "TEXT_RISK"
    return {
        "status": status,
        "reliable": all(record["reliable"] for record in records),
        "raw_detection": raw,
        "roi_records": records,
    }


def _gt_improvement(
    baseline_bgr: np.ndarray,
    candidate_bgr: np.ndarray,
    gt_bgr: np.ndarray | None,
) -> dict[str, Any]:
    if gt_bgr is None:
        return {"status": "NOT_APPLICABLE", "gt_reference": "NONE"}
    baseline_to_gt = _pair_metrics(gt_bgr, baseline_bgr)
    candidate_to_gt = _pair_metrics(gt_bgr, candidate_bgr)
    baseline_mae = float(baseline_to_gt["delta_metrics"]["rgb_mae"])
    candidate_mae = float(candidate_to_gt["delta_metrics"]["rgb_mae"])
    baseline_ssim = float(baseline_to_gt["delta_metrics"]["global_ssim"])
    candidate_ssim = float(candidate_to_gt["delta_metrics"]["global_ssim"])
    relative = (baseline_mae - candidate_mae) / max(baseline_mae, 1e-6)
    ssim_gain = candidate_ssim - baseline_ssim
    ssim_headroom_relative = ssim_gain / max(1.0 - baseline_ssim, 1e-6)
    supported = (
        relative >= CONTROL_THRESHOLDS["gt_mae_relative_improvement_min"]
        and (
            ssim_gain >= CONTROL_THRESHOLDS["gt_ssim_improvement_min"]
            or ssim_headroom_relative >= CONTROL_THRESHOLDS["gt_ssim_headroom_relative_min"]
        )
    )
    return {
        "status": "IMPROVED" if supported else "NOT_IMPROVED",
        "baseline_to_gt": baseline_to_gt,
        "candidate_to_gt": candidate_to_gt,
        "rgb_mae_improvement": round(baseline_mae - candidate_mae, 8),
        "relative_mae_improvement": round(relative, 8),
        "ssim_improvement": round(ssim_gain, 8),
        "relative_ssim_headroom_improvement": round(ssim_headroom_relative, 8),
        "positive_direction_supported": bool(supported),
    }


def _classify_safety(
    baseline_pair: dict[str, Any],
    alpha: dict[str, Any],
    geometry: dict[str, Any],
    text_structure: dict[str, Any] | None,
) -> dict[str, Any]:
    delta = baseline_pair["delta_metrics"]
    failures: list[str] = []
    review: list[str] = []
    if alpha.get("status") == "FAIL":
        failures.append("ALPHA_IDENTITY_FAILED")
    if geometry["status"] == "FAIL":
        failures.append(geometry["decision"])
    elif geometry["status"] != "PASS":
        review.append(geometry["decision"])

    blur = (
        delta["sharpness_ratio"] <= CONTROL_THRESHOLDS["blur_sharpness_ratio_max"]
        and delta["high_frequency_ratio"] <= 0.80
    )
    oversharpen = (
        delta["sharpness_ratio"] >= CONTROL_THRESHOLDS["oversharpen_sharpness_ratio_min"]
        and delta["overshoot_fraction"] >= CONTROL_THRESHOLDS["overshoot_fraction_delta_min"]
    )
    ringing = (
        delta["edge_band_large_delta_fraction"] >= CONTROL_THRESHOLDS["ringing_large_delta_fraction_min"]
        and delta["edge_band_bipolar_fraction"] >= CONTROL_THRESHOLDS["ringing_bipolar_fraction_min"]
    )
    high_frequency = (
        delta["high_frequency_tile_mean_p95"] >= CONTROL_THRESHOLDS["high_frequency_tile_mean_p95_max"]
        or (
            delta["high_frequency_ratio"] >= CONTROL_THRESHOLDS["high_frequency_ratio_max"]
            and delta["flat_noise_p90_delta"] >= CONTROL_THRESHOLDS["flat_noise_delta_max"]
        )
    )
    color_shift = (
        delta["low_frequency_color_delta_e76_mean"] >= CONTROL_THRESHOLDS["color_delta_e76_mean_max"]
        or abs(delta["low_frequency_lightness_delta"]) >= CONTROL_THRESHOLDS["lightness_delta_abs_max"]
        or abs(delta["low_frequency_saturation_delta"]) >= CONTROL_THRESHOLDS["saturation_delta_abs_max"]
    )
    local_color_shift = (
        delta["local_color_delta_e76_p99"] >= CONTROL_THRESHOLDS["local_color_delta_e76_p99_max"]
        and delta["local_color_severe_fraction"] >= CONTROL_THRESHOLDS["local_color_severe_fraction_max"]
    )
    black_edge = delta["black_edge_fraction"] >= CONTROL_THRESHOLDS["black_edge_fraction_max"]
    white_edge = delta["white_edge_fraction"] >= CONTROL_THRESHOLDS["white_edge_fraction_max"]
    if blur:
        failures.append("DETAIL_BLUR_DETECTED")
    if oversharpen:
        failures.append("OVERSHARPEN_DETECTED")
    if ringing:
        failures.append("HALO_OR_RINGING_DETECTED")
    if high_frequency:
        failures.append("HIGH_FREQUENCY_ARTIFACT_DETECTED")
    if black_edge:
        failures.append("BLACK_EDGE_DETECTED")
    if white_edge:
        failures.append("WHITE_EDGE_DETECTED")
    if color_shift:
        failures.append("GLOBAL_COLOR_SHIFT_DETECTED")
    if local_color_shift:
        failures.append("LOCAL_COLOR_SHIFT_DETECTED")
    if text_structure is not None and text_structure["status"] == "TEXT_DEGRADED":
        for name, detected in text_structure["raw_detection"].items():
            if detected:
                failures.append(f"TEXT_{name.upper()}_DETECTED")
    elif text_structure is not None and text_structure["status"] == "NEED_PROOF":
        review.append("TEXT_STRUCTURE_NEED_PROOF")

    status = "FAIL" if failures else ("REVIEW" if review else "PASS")
    return {
        "status": status,
        "failures": failures,
        "review_reasons": review,
        "raw_detection": {
            "blur": bool(blur),
            "oversharpen": bool(oversharpen),
            "halo_or_ringing": bool(ringing),
            "high_frequency_anomaly": bool(high_frequency),
            "color_shift": bool(color_shift),
            "global_color_shift": bool(color_shift),
            "local_color_shift": bool(local_color_shift),
            "black_edge": bool(black_edge),
            "white_edge": bool(white_edge),
        },
        "alpha": alpha,
        "geometry": geometry,
        "text_structure": text_structure,
    }


def _roi_result(
    roi: dict[str, Any],
    baseline_rgba: np.ndarray,
    candidate_rgba: np.ndarray,
    gt_rgba: np.ndarray | None,
    safety_status: str,
) -> dict[str, Any]:
    def crop(array: np.ndarray) -> np.ndarray:
        box = map_normalized_box(roi["normalized_box"], (array.shape[1], array.shape[0]))
        return array[box["y0"] : box["y1"], box["x0"] : box["x1"]]

    baseline_bgr = _analysis_bgr(crop(baseline_rgba), maximum_edge=720)
    candidate_bgr = _analysis_bgr(crop(candidate_rgba), maximum_edge=720)
    gt_bgr = None if gt_rgba is None else _analysis_bgr(crop(gt_rgba), maximum_edge=720)
    pair = _pair_metrics(baseline_bgr, candidate_bgr)
    gt_evidence = _gt_improvement(baseline_bgr, candidate_bgr, gt_bgr)
    roi_type = str(roi.get("roi_type") or "UNKNOWN")
    is_text = roi_type in {"CHINESE_TEXT", "TEXT", "LOGO"}
    text_mask_coverage = {
        "baseline": round(float(np.mean(detect_text_like_regions(baseline_bgr) > 0.28)), 8),
        "candidate": round(float(np.mean(detect_text_like_regions(candidate_bgr) > 0.28)), 8),
    }
    text_structure = _text_structure_facts(baseline_bgr, candidate_bgr) if is_text else None
    if not is_text:
        text_status = "NOT_APPLICABLE"
    elif text_structure is not None and text_structure["status"] == "TEXT_DEGRADED":
        text_status = "TEXT_DEGRADED"
    elif text_structure is not None and text_structure["status"] == "NEED_PROOF":
        text_status = "NEED_PROOF"
    elif safety_status == "FAIL":
        text_status = "TEXT_RISK"
    elif gt_evidence.get("positive_direction_supported"):
        text_status = "TEXT_IMPROVED"
    elif pair["delta_metrics"]["rgb_changed_fraction"] == 0.0:
        text_status = "TEXT_STABLE"
    else:
        text_status = "TEXT_RISK"
    if roi_type == "MATERIAL" and gt_rgba is None:
        material_status = "NEED_PROOF"
    elif safety_status == "FAIL":
        material_status = "RISK"
    elif gt_evidence.get("positive_direction_supported"):
        material_status = "IMPROVED"
    else:
        material_status = "STABLE_OR_NOT_PROVEN"
    return {
        "roi_id": roi["roi_id"],
        "roi_type": roi_type,
        "label": roi.get("label"),
        "normalized_box": roi["normalized_box"],
        "baseline_candidate_metrics": pair,
        "gt_evidence": gt_evidence,
        "text_fidelity": text_status,
        "text_mask_coverage": text_mask_coverage,
        "text_structure": text_structure,
        "material_texture": material_status,
    }


REVIEW_VERDICTS = {"BETTER", "SAME", "WORSE", "RISK"}
REVIEW_CONTEXT_FIELDS = (
    "case_id",
    "comparison_asset_set",
    "original_hash",
    "baseline_hash",
    "candidate_hash",
    "gt_hash_or_none",
    "roi_asset_hashes",
)


def build_human_review_evidence(
    context: dict[str, Any],
    verdict: str,
    *,
    control_fixture_only: bool = True,
    test_vector_only: bool = False,
) -> dict[str, Any]:
    if verdict not in REVIEW_VERDICTS:
        raise E102Error(f"HUMAN_REVIEW_VERDICT_INVALID:{verdict}")
    missing = [field for field in REVIEW_CONTEXT_FIELDS if field not in context]
    if missing:
        raise E102Error(f"HUMAN_REVIEW_CONTEXT_MISSING:{','.join(missing)}")
    body = {
        "review_schema_version": HUMAN_REVIEW_SCHEMA_VERSION,
        **{field: context[field] for field in REVIEW_CONTEXT_FIELDS},
        "review_verdict": verdict,
        "control_fixture_only": bool(control_fixture_only),
        "test_vector_only": bool(test_vector_only),
    }
    return {**body, "review_evidence_id": _canonical_sha256(body)}


def validate_human_review_evidence(
    context: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    if context is None or not isinstance(evidence, dict):
        return {
            "status": "UNBOUND",
            "binding_valid": False,
            "failures": ["HUMAN_REVIEW_EVIDENCE_MISSING"],
            "verdict": None,
            "evidence_id": None,
            "control_fixture_only": None,
            "test_vector_only": None,
            "product_admissible": False,
            "contract_test_product_admissible": False,
        }
    failures: list[str] = []
    if evidence.get("review_schema_version") != HUMAN_REVIEW_SCHEMA_VERSION:
        failures.append("REVIEW_SCHEMA_VERSION_MISMATCH")
    if evidence.get("review_verdict") not in REVIEW_VERDICTS:
        failures.append("REVIEW_VERDICT_INVALID")
    if not isinstance(evidence.get("control_fixture_only"), bool):
        failures.append("REVIEW_CONTROL_FIXTURE_MARKER_INVALID")
    if not isinstance(evidence.get("test_vector_only"), bool):
        failures.append("REVIEW_TEST_VECTOR_MARKER_INVALID")
    for field in REVIEW_CONTEXT_FIELDS:
        if evidence.get(field) != context.get(field):
            failures.append(f"REVIEW_{field.upper()}_MISMATCH")
    body = {key: value for key, value in evidence.items() if key != "review_evidence_id"}
    expected_id = _canonical_sha256(body)
    if evidence.get("review_evidence_id") != expected_id:
        failures.append("REVIEW_EVIDENCE_ID_INVALID")
    binding_valid = not failures
    control_fixture_only = evidence.get("control_fixture_only") if isinstance(evidence.get("control_fixture_only"), bool) else None
    test_vector_only = evidence.get("test_vector_only") if isinstance(evidence.get("test_vector_only"), bool) else None
    return {
        "status": "BOUND" if binding_valid else "UNBOUND",
        "binding_valid": binding_valid,
        "failures": failures,
        "verdict": evidence.get("review_verdict") if binding_valid else None,
        "evidence_id": evidence.get("review_evidence_id") if binding_valid else None,
        "control_fixture_only": control_fixture_only,
        "test_vector_only": test_vector_only,
        "product_admissible": bool(binding_valid and not control_fixture_only and not test_vector_only),
        "contract_test_product_admissible": bool(binding_valid and not control_fixture_only and test_vector_only),
    }


def array_review_context(
    case_id: str,
    original_rgba: np.ndarray,
    baseline_rgba: np.ndarray,
    candidate_rgba: np.ndarray,
    gt_rgba: np.ndarray | None,
    *,
    comparison_asset_set: dict[str, str] | None = None,
    roi_asset_hashes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "comparison_asset_set": comparison_asset_set or {"fixture": _array_sha256(candidate_rgba)},
        "original_hash": _array_sha256(original_rgba),
        "baseline_hash": _array_sha256(baseline_rgba),
        "candidate_hash": _array_sha256(candidate_rgba),
        "gt_hash_or_none": "NONE" if gt_rgba is None else _array_sha256(gt_rgba),
        "roi_asset_hashes": roi_asset_hashes or [],
    }


def evaluate_arrays(
    baseline_rgba: np.ndarray,
    candidate_rgba: np.ndarray,
    *,
    gt_rgba: np.ndarray | None = None,
    candidate_class: str = PRODUCT,
    roi_types: tuple[str, ...] = (),
    text_structure_override: dict[str, Any] | None = None,
    human_review_context: dict[str, Any] | None = None,
    human_review_evidence: dict[str, Any] | None = None,
    mandatory_gate_aggregation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if candidate_class not in CANDIDATE_CLASSES:
        raise E102Error(f"CANDIDATE_CLASS_INVALID:{candidate_class}")
    review = validate_human_review_evidence(human_review_context, human_review_evidence)
    review_binding_valid = bool(review["binding_valid"])
    review_product_admissible = bool(review["product_admissible"])
    review_test_vector_only = bool(review["test_vector_only"])
    human_review_required = candidate_class == PRODUCT
    default_aggregation = aggregate_mandatory_gates({})
    supplied_aggregation = mandatory_gate_aggregation or default_aggregation
    if baseline_rgba.shape != candidate_rgba.shape:
        geometry = _geometry_measurement(baseline_rgba, candidate_rgba)
        authority = authorize_product_delivery(
            quality_gain_status=QUALITY_GAIN_REJECTED,
            hard_safety_status="FAIL",
            mandatory_gate_aggregation=supplied_aggregation,
            human_review_required=human_review_required,
            review_product_admissible=review_product_admissible,
            test_vector_only=review_test_vector_only,
        ) if candidate_class == PRODUCT else None
        return {
            "candidate_class": candidate_class,
            "hard_safety_gate": {
                "status": "FAIL",
                "failures": ["DIMENSIONS_OR_ASPECT_RATIO_CHANGED"],
                "review_reasons": [],
                "raw_detection": {},
                "alpha": {"status": "NOT_EVALUATED_GEOMETRY_FAILED"},
                "geometry": geometry,
                "text_structure": None,
            },
            "net_quality_gain_evaluated": False,
            "gt_evidence": {"status": "NOT_EVALUATED_HARD_SAFETY_NOT_PASS", "positive_direction_supported": False},
            "quality_gain_status": QUALITY_GAIN_REJECTED,
            "delivery_status": authority["delivery_status"] if authority else "FAIL",
            "delivery_authority": authority,
            "mandatory_gate_aggregation": authority["mandatory_gate_aggregation"] if authority else default_aggregation,
            "mandatory_gate_complete": authority["mandatory_gate_complete"] if authority else False,
            "human_review_required": human_review_required,
            "human_review_pending": human_review_required and not review_product_admissible,
            "human_review_completed": review_binding_valid,
            "human_review_verdict": review["verdict"],
            "human_review_evidence_id": review["evidence_id"],
            "human_review_status": review["status"],
            "human_review_binding_valid": review_binding_valid,
            "human_review_control_fixture_only": review["control_fixture_only"],
            "human_review_product_admissible": review_product_admissible,
            "test_vector_only": review_test_vector_only,
            "human_review_failures": review["failures"],
            "human_review_reason": "HARD_SAFETY_FAILED_BEFORE_PRODUCT_AUTHORIZATION",
        }
    baseline_bgr = _analysis_bgr(baseline_rgba)
    candidate_bgr = _analysis_bgr(candidate_rgba)
    baseline_pair = _pair_metrics(baseline_bgr, candidate_bgr)
    alpha = _alpha_facts(baseline_rgba, candidate_rgba)
    geometry = _geometry_measurement(baseline_rgba, candidate_rgba)
    text_types = {"CHINESE_TEXT", "TEXT", "LOGO"}
    text_structure = text_structure_override or (
        _text_structure_facts(baseline_bgr, candidate_bgr)
        if text_types.intersection(roi_types)
        else None
    )
    safety = _classify_safety(baseline_pair, alpha, geometry, text_structure)
    if safety["status"] == "PASS":
        gt_bgr = None if gt_rgba is None else _analysis_bgr(gt_rgba)
        gt_evidence = _gt_improvement(baseline_bgr, candidate_bgr, gt_bgr)
    else:
        gt_evidence = {
            "status": "NOT_EVALUATED_HARD_SAFETY_NOT_PASS",
            "gt_reference": "BOUND" if gt_rgba is not None else "NONE",
            "positive_direction_supported": False,
        }
    context_scale = min(1.0, 240.0 / float(max(baseline_bgr.shape[:2])))
    context_size = (
        max(1, int(round(baseline_bgr.shape[1] * context_scale))),
        max(1, int(round(baseline_bgr.shape[0] * context_scale))),
    )
    context_baseline = cv2.resize(baseline_bgr, context_size, interpolation=cv2.INTER_AREA)
    context_candidate = cv2.resize(candidate_bgr, context_size, interpolation=cv2.INTER_AREA)
    reference_type = detect_image_type(context_baseline)
    candidate_type = detect_image_type(context_candidate)
    image_type_proxy = {
        "authority": "PROXY_ONLY_NOT_ROUTING_OR_QUALITY_TRUTH",
        "reference": {
            "image_type": reference_type.image_type,
            "confidence": round(reference_type.confidence, 8),
            "scores": reference_type.scores,
        },
        "candidate": {
            "image_type": candidate_type.image_type,
            "confidence": round(candidate_type.confidence, 8),
            "scores": candidate_type.scores,
        },
    }
    exact_zero = baseline_pair["delta_metrics"]["rgb_changed_fraction"] == 0.0 and alpha["status"] == "PASS"
    positive = bool(gt_evidence.get("positive_direction_supported"))
    review_completed = review_binding_valid
    review_verdict = review["verdict"]
    if safety["status"] == "FAIL":
        quality = QUALITY_GAIN_REJECTED
    elif safety["status"] != "PASS":
        quality = QUALITY_GAIN_NOT_PROVEN
    elif exact_zero:
        quality = QUALITY_GAIN_NOT_PROVEN
    elif positive and candidate_class == CONTROL_ORACLE:
        quality = QUALITY_GAIN_PROVEN
    elif candidate_class == PRODUCT and review_product_admissible and review_verdict in {"WORSE", "RISK"}:
        quality = QUALITY_GAIN_REJECTED
    elif positive and candidate_class == PRODUCT and review_product_admissible and review_verdict == "BETTER":
        quality = QUALITY_GAIN_PROVEN
    else:
        quality = QUALITY_GAIN_NOT_PROVEN
    if candidate_class == PRODUCT:
        authority = authorize_product_delivery(
            quality_gain_status=quality,
            hard_safety_status=safety["status"],
            mandatory_gate_aggregation=supplied_aggregation,
            human_review_required=human_review_required,
            review_product_admissible=review_product_admissible,
            test_vector_only=review_test_vector_only,
        )
        delivery = authority["delivery_status"]
        normalized_aggregation = authority["mandatory_gate_aggregation"]
    else:
        authority = None
        delivery = "FAIL" if quality == QUALITY_GAIN_REJECTED else (
            "PASS" if quality == QUALITY_GAIN_PROVEN and safety["status"] == "PASS" else "REVIEW"
        )
        normalized_aggregation, _ = _validated_mandatory_aggregation(supplied_aggregation)
    if not text_types.intersection(roi_types):
        text_fidelity = "NOT_APPLICABLE"
    elif text_structure is not None and text_structure["status"] == "TEXT_DEGRADED":
        text_fidelity = "TEXT_DEGRADED"
    elif text_structure is not None and text_structure["status"] == "NEED_PROOF":
        text_fidelity = "NEED_PROOF"
    elif positive:
        text_fidelity = "TEXT_IMPROVED"
    elif exact_zero:
        text_fidelity = "TEXT_STABLE"
    else:
        text_fidelity = "TEXT_RISK"
    material = "NEED_PROOF" if "MATERIAL" in roi_types and gt_rgba is None else "NOT_APPLICABLE"
    if candidate_class != PRODUCT or review_product_admissible:
        review_reason = "NONE"
    elif not review_binding_valid:
        review_reason = "UNBOUND_OR_NOT_COMPLETED"
    elif review["control_fixture_only"]:
        review_reason = "CONTROL_FIXTURE_NOT_PRODUCT_ADMISSIBLE"
    elif review["test_vector_only"]:
        review_reason = "TEST_VECTOR_NOT_PRODUCT_ADMISSIBLE"
    else:
        review_reason = "REVIEW_NOT_PRODUCT_ADMISSIBLE"
    return {
        "candidate_class": candidate_class,
        "metric_protocol_version": METRIC_PROTOCOL_VERSION,
        "baseline_metrics": baseline_pair["reference_metrics"],
        "candidate_metrics": baseline_pair["candidate_metrics"],
        "delta_metrics": baseline_pair["delta_metrics"],
        "existing_quality_compare_proxy": baseline_pair["existing_quality_compare_proxy"],
        "image_type_heuristic_proxy": image_type_proxy,
        "hard_safety_gate": safety,
        "net_quality_gain_evaluated": safety["status"] == "PASS",
        "gt_evidence": gt_evidence,
        "text_fidelity": text_fidelity,
        "material_texture": material,
        "quality_gain_status": quality,
        "delivery_status": delivery,
        "delivery_authority": authority,
        "mandatory_gate_aggregation": normalized_aggregation,
        "mandatory_gate_complete": normalized_aggregation["mandatory_gate_complete"],
        "human_review_required": human_review_required,
        "human_review_pending": human_review_required and not review_product_admissible,
        "human_review_completed": review_completed,
        "human_review_verdict": review_verdict,
        "human_review_evidence_id": review["evidence_id"],
        "human_review_status": review["status"],
        "human_review_binding_valid": review_binding_valid,
        "human_review_control_fixture_only": review["control_fixture_only"],
        "human_review_product_admissible": review_product_admissible,
        "test_vector_only": review_test_vector_only,
        "human_review_failures": review["failures"],
        "human_review_reason": review_reason,
    }


def _eligibility(case: dict[str, Any], candidate_path: Path, spec: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in REQUIRED_SPEC_FIELDS if field not in spec]
    failures: list[str] = []
    if missing:
        failures.extend(f"MISSING:{field}" for field in missing)
    if spec.get("candidate_class") not in CANDIDATE_CLASSES:
        failures.append("CANDIDATE_CLASS_INVALID")
    actual_candidate_sha: str | None = None
    if not candidate_path.is_file():
        failures.append("CANDIDATE_OUTPUT_MISSING")
    else:
        try:
            with Image.open(candidate_path) as opened:
                opened.load()
                size = opened.size
            expected_size = (int(case["safe_base"]["width"]), int(case["safe_base"]["height"]))
            if size != expected_size:
                failures.append("CANDIDATE_DIMENSIONS_MISMATCH")
            actual_candidate_sha = sha256_file(candidate_path)
            if spec.get("candidate_identity") != actual_candidate_sha:
                failures.append("CANDIDATE_SHA_CHANGED")
        except Exception:
            failures.append("CANDIDATE_DECODE_FAILED")
    expected = {
        "source_binding_sha256": case["input"]["sha256"],
        "baseline_binding_sha256": case["safe_base"]["sha256"],
        "gt_binding_sha256_or_none": "NONE" if case["gt"] is None else case["gt"]["sha256"],
        "roi_set_sha256": _canonical_sha256(case["roi"]),
    }
    mismatch_codes = {
        "source_binding_sha256": "SOURCE_BINDING_CHANGED",
        "baseline_binding_sha256": "BASELINE_BINDING_CHANGED",
        "gt_binding_sha256_or_none": "GT_BINDING_CHANGED",
        "roi_set_sha256": "ROI_BINDING_CHANGED",
    }
    for field, value in expected.items():
        if spec.get(field) != value:
            failures.append(mismatch_codes[field])
    algorithm_identity = str(spec.get("algorithm_identity") or "").strip()
    if not algorithm_identity:
        failures.append("ALGORITHM_IDENTITY_EMPTY")
    if spec.get("evaluation_schema_version") != EVALUATION_SCHEMA_VERSION:
        failures.append("EVALUATION_SCHEMA_VERSION_MISMATCH")

    canonical: dict[str, Any] | None = None
    try:
        canonical = _canonical_parameters(spec.get("parameters"))
    except E102Error as exc:
        failures.append(str(exc))
    if canonical is not None and spec.get("canonical_parameters") != canonical:
        failures.append("PARAMETERS_CHANGED")

    expected_replay_id: str | None = None
    expected_replay_contract: dict[str, Any] | None = None
    if actual_candidate_sha is not None and algorithm_identity and canonical is not None:
        expected_replay_id, expected_replay_contract = compute_replay_identity(
            case,
            actual_candidate_sha,
            algorithm_identity,
            canonical,
        )
        if spec.get("replay_contract") != expected_replay_contract or spec.get("replay_identity") != expected_replay_id:
            failures.append("INVALID_REPLAY_ID")

    asset_bindings = (
        ("SOURCE_SHA_CHANGED", case["input"]),
        ("BASELINE_SHA_CHANGED", case["safe_base"]),
        ("GT_SHA_CHANGED", case["gt"]),
    )
    for code, record in asset_bindings:
        if record is None:
            continue
        if not isinstance(record.get("path"), str):
            failures.append(code)
            continue
        try:
            if sha256_file(_manifest_asset(record["path"])) != record["sha256"]:
                failures.append(code)
        except E102Error:
            failures.append(code)
    failures = list(dict.fromkeys(failures))
    return {
        "status": "ELIGIBLE" if not failures else "INELIGIBLE",
        "replay_binding_gate": "PASS" if not failures else "FAIL",
        "missing_fields": missing,
        "failures": failures,
        "expected_bindings": expected,
        "expected_replay_identity": expected_replay_id,
        "expected_replay_contract": expected_replay_contract,
    }


def _review_context_from_comparison(
    case: dict[str, Any],
    candidate_path: Path,
    comparison: dict[str, Any],
) -> dict[str, Any]:
    asset_paths = [comparison["full_image_side_by_side"]]
    for roi in comparison["roi"]:
        asset_paths.append(roi["side_by_side"])
        asset_paths.extend(path for path in roi["crop_paths"].values() if path)
    asset_set: dict[str, str] = {}
    for path_value in sorted(set(asset_paths)):
        path = Path(path_value)
        resolved = path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()
        if not resolved.is_file():
            raise E102Error(f"REVIEW_ASSET_MISSING:{resolved}")
        asset_set[path_value] = sha256_file(resolved)
    roi_hashes = [asset_set[path] for path in sorted(asset_set) if "roi_" in path or "roi_comparisons" in path]
    return {
        "case_id": case["case_id"],
        "comparison_asset_set": asset_set,
        "original_hash": case["input"]["sha256"],
        "baseline_hash": case["safe_base"]["sha256"],
        "candidate_hash": sha256_file(candidate_path),
        "gt_hash_or_none": "NONE" if case["gt"] is None else case["gt"]["sha256"],
        "roi_asset_hashes": roi_hashes,
    }


def _case_mandatory_gate_statuses(
    eligibility: dict[str, Any],
    evaluation: dict[str, Any],
    candidate_class: str,
) -> dict[str, str]:
    safety = evaluation["hard_safety_gate"]
    geometry_status = safety.get("geometry", {}).get("status")
    alpha_status = safety.get("alpha", {}).get("status")
    raw = safety.get("raw_detection", {})

    def safety_status(value: Any) -> str:
        if value == "PASS":
            return "PASS"
        if value == "FAIL":
            return "FAIL"
        return "NEED_PROOF"

    text_value = evaluation.get("text_fidelity")
    if text_value in {"TEXT_STABLE", "TEXT_IMPROVED"}:
        text_status = "PASS"
    elif text_value in {"TEXT_DEGRADED", "TEXT_RISK"}:
        text_status = "FAIL"
    else:
        text_status = "NEED_PROOF"

    quality_value = evaluation.get("quality_gain_status")
    if quality_value == QUALITY_GAIN_PROVEN:
        detail_status = "PASS"
    elif quality_value == QUALITY_GAIN_REJECTED:
        detail_status = "FAIL"
    else:
        detail_status = "NEED_PROOF"

    if candidate_class == PRODUCT:
        review_status = "PASS" if evaluation.get("human_review_product_admissible") is True else "NEED_PROOF"
    else:
        review_status = "NEED_PROOF"

    hard_status = safety_status(safety.get("status"))
    return {
        "ELIGIBILITY_GATE": "PASS" if eligibility.get("status") == "ELIGIBLE" else "FAIL",
        "REPLAY_BINDING_GATE": "PASS" if eligibility.get("replay_binding_gate") == "PASS" else "FAIL",
        "HARD_SAFETY_GATE": hard_status,
        "GEOMETRY_SAFETY_GATE": safety_status(geometry_status),
        "ALPHA_SAFETY_GATE": safety_status(alpha_status),
        "EDGE_ARTIFACT_GATE": "FAIL" if any(raw.get(name) is True for name in ("black_edge", "white_edge", "halo_or_ringing")) else ("PASS" if raw else "NEED_PROOF"),
        "HIGH_FREQUENCY_GATE": "FAIL" if raw.get("high_frequency_anomaly") is True else ("PASS" if raw else "NEED_PROOF"),
        "COLOR_SAFETY_GATE": "FAIL" if raw.get("color_shift") is True or raw.get("local_color_shift") is True else ("PASS" if raw else "NEED_PROOF"),
        "TEXT_FIDELITY_GATE": text_status,
        "DETAIL_GAIN_GATE": detail_status,
        "HUMAN_REVIEW_BINDING_GATE": review_status,
    }


def control_fixture_product_authorization_count(results: list[dict[str, Any]]) -> int:
    return sum(
        item.get("candidate_class") == PRODUCT
        and item.get("human_review_control_fixture_only") is True
        and (
            item.get("quality_gain_status") == QUALITY_GAIN_PROVEN
            or item.get("delivery_status") == "PASS"
        )
        for item in results
    )


def validate_product_pass_global_invariant(results: list[dict[str, Any]]) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    product_pass_count = 0
    for index, item in enumerate(results):
        if item.get("candidate_class") != PRODUCT or item.get("delivery_status") != "PASS":
            continue
        product_pass_count += 1
        safety = item.get("safety_results") or item.get("hard_safety_gate") or {}
        authority = item.get("delivery_authority") or {}
        failed: list[str] = []
        if item.get("quality_gain_status") != QUALITY_GAIN_PROVEN:
            failed.append("QUALITY_GAIN_NOT_PROVEN")
        if safety.get("status") != "PASS":
            failed.append("HARD_SAFETY_NOT_PASS")
        if item.get("mandatory_gate_complete") is not True:
            failed.append("MANDATORY_GATE_INCOMPLETE")
        if item.get("human_review_control_fixture_only") is not False:
            failed.append("CONTROL_FIXTURE_AUTHORIZATION")
        if item.get("test_vector_only") is not False:
            failed.append("TEST_VECTOR_AUTHORIZATION")
        if item.get("human_review_required") is True and item.get("human_review_product_admissible") is not True:
            failed.append("PRODUCT_REVIEW_NOT_ADMISSIBLE")
        if authority.get("authority_version") != PRODUCT_DELIVERY_AUTHORITY_VERSION or authority.get("production_authorized") is not True:
            failed.append("PRODUCT_DELIVERY_AUTHORITY_BYPASSED")
        if failed:
            violations.append({
                "case_id": item.get("case_id", f"INDEX_{index}"),
                "violations": failed,
            })
    return {
        "status": "PASS" if not violations else "FAIL",
        "product_pass_count": product_pass_count,
        "violation_count": len(violations),
        "violations": violations,
    }


def evaluate_case(
    manifest_path: Path,
    case_id: str,
    candidate_path: Path,
    spec: dict[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = [item for item in manifest.get("cases", []) if item.get("case_id") == case_id]
    if len(matches) != 1:
        raise E102Error(f"CASE_ID_NOT_UNIQUE_OR_MISSING:{case_id}")
    case = matches[0]
    eligibility = _eligibility(case, candidate_path, spec)
    if eligibility["status"] != "ELIGIBLE":
        statuses = {name: "NEED_PROOF" for name in MANDATORY_GATE_NAMES}
        statuses["ELIGIBILITY_GATE"] = "FAIL"
        statuses["REPLAY_BINDING_GATE"] = "FAIL"
        aggregation = aggregate_mandatory_gates(statuses)
        return {
            "case_id": case_id,
            "candidate_class": spec.get("candidate_class", "UNKNOWN"),
            "evaluation_status": "INELIGIBLE",
            "eligibility": eligibility,
            "quality_gain_status": QUALITY_GAIN_NOT_PROVEN,
            "quality_gain_proven": "FORBIDDEN",
            "delivery_status": "FAIL",
            "mandatory_gate_aggregation": aggregation,
            "mandatory_gate_complete": False,
        }
    comparison = rerender_candidate_comparisons(manifest_path, case_id, candidate_path, output_root)
    original_path = _manifest_asset(case["input"]["path"])
    baseline_path = _manifest_asset(case["safe_base"]["path"])
    gt_path = None if case["gt"] is None else _manifest_asset(case["gt"]["path"])
    baseline_rgba = _load_rgba(baseline_path)
    candidate_rgba = _load_rgba(candidate_path)
    gt_rgba = None if gt_path is None else _load_rgba(gt_path)
    review_context = _review_context_from_comparison(case, candidate_path, comparison)
    text_structure = _case_text_structure(case["roi"], baseline_rgba, candidate_rgba)
    evaluation = evaluate_arrays(
        baseline_rgba,
        candidate_rgba,
        gt_rgba=gt_rgba,
        candidate_class=spec["candidate_class"],
        roi_types=tuple(str(roi.get("roi_type") or "") for roi in case["roi"]),
        text_structure_override=text_structure,
        human_review_context=review_context,
        human_review_evidence=spec.get("human_review_evidence"),
    )
    roi_results = [
        _roi_result(
            roi,
            baseline_rgba,
            candidate_rgba,
            gt_rgba,
            evaluation["hard_safety_gate"]["status"],
        )
        for roi in case["roi"]
    ]
    text_values = [item["text_fidelity"] for item in roi_results if item["text_fidelity"] != "NOT_APPLICABLE"]
    if "TEXT_DEGRADED" in text_values:
        evaluation["text_fidelity"] = "TEXT_DEGRADED"
    elif "NEED_PROOF" in text_values:
        evaluation["text_fidelity"] = "NEED_PROOF"
    elif "TEXT_RISK" in text_values:
        evaluation["text_fidelity"] = "TEXT_RISK"
    elif "TEXT_IMPROVED" in text_values:
        evaluation["text_fidelity"] = "TEXT_IMPROVED"
    elif text_values:
        evaluation["text_fidelity"] = "TEXT_STABLE"
    case_gate_statuses = _case_mandatory_gate_statuses(eligibility, evaluation, spec["candidate_class"])
    case_aggregation = aggregate_mandatory_gates(case_gate_statuses)
    evaluation["mandatory_gate_aggregation"] = case_aggregation
    evaluation["mandatory_gate_complete"] = case_aggregation["mandatory_gate_complete"]
    if spec["candidate_class"] == PRODUCT:
        evaluation["delivery_authority"] = authorize_product_delivery(
            quality_gain_status=evaluation["quality_gain_status"],
            hard_safety_status=evaluation["hard_safety_gate"]["status"],
            mandatory_gate_aggregation=case_aggregation,
            human_review_required=evaluation["human_review_required"],
            review_product_admissible=evaluation["human_review_product_admissible"],
            test_vector_only=evaluation["test_vector_only"],
        )
        evaluation["delivery_status"] = evaluation["delivery_authority"]["delivery_status"]
    result = {
        "gate_version": GATE_VERSION,
        "case_id": spec["candidate_id"],
        "source_id": case["sample_id"],
        "e1_01_case_id": case_id,
        "degradation_family": case["degradation_type"],
        "original_reference": case["input"],
        "baseline_reference": case["safe_base"],
        "candidate_reference": comparison["candidate"],
        "gt_reference_or_none": case["gt"],
        "candidate_class": spec["candidate_class"],
        "candidate_contract": spec,
        "algorithm_identity": spec["algorithm_identity"],
        "canonical_parameters": spec["canonical_parameters"],
        "replay_identity": spec["replay_identity"],
        "roi_set": case["roi"],
        "evaluation_status": "COMPLETE",
        "eligibility": eligibility,
        "baseline_metrics": evaluation["baseline_metrics"],
        "candidate_metrics": evaluation["candidate_metrics"],
        "delta_metrics": evaluation["delta_metrics"],
        "safety_results": evaluation["hard_safety_gate"],
        "quality_gain_results": {
            "gt_evidence": evaluation["gt_evidence"],
            "text_fidelity": evaluation["text_fidelity"],
            "material_texture": evaluation["material_texture"],
            "existing_quality_compare_proxy": evaluation["existing_quality_compare_proxy"],
            "image_type_heuristic_proxy": evaluation["image_type_heuristic_proxy"],
        },
        "human_review_required": evaluation["human_review_required"],
        "human_review_pending": evaluation["human_review_pending"],
        "human_review_completed": evaluation["human_review_completed"],
        "human_review_verdict": evaluation["human_review_verdict"],
        "human_review_evidence_id": evaluation["human_review_evidence_id"],
        "human_review_status": evaluation["human_review_status"],
        "human_review_binding_valid": evaluation["human_review_binding_valid"],
        "human_review_control_fixture_only": evaluation["human_review_control_fixture_only"],
        "human_review_product_admissible": evaluation["human_review_product_admissible"],
        "test_vector_only": evaluation["test_vector_only"],
        "human_review_reason": evaluation["human_review_reason"],
        "quality_gain_status": evaluation["quality_gain_status"],
        "delivery_status": evaluation["delivery_status"],
        "delivery_authority": evaluation["delivery_authority"],
        "mandatory_gate_aggregation": evaluation["mandatory_gate_aggregation"],
        "mandatory_gate_complete": evaluation["mandatory_gate_complete"],
        "evidence_refs": {
            "comparison_manifest": relative_path(output_root / "comparison_manifest.json"),
            "full_image": comparison["full_image_side_by_side"],
            "roi_results": relative_path(output_root.parent.parent / "roi_results" / f"{spec['candidate_id']}.json"),
        },
        "roi_results": roi_results,
        "control_isolation": {
            "counts_as_product_quality_gain": (
                spec["candidate_class"] == PRODUCT
                and evaluation["human_review_control_fixture_only"] is False
                and evaluation["test_vector_only"] is False
            ),
            "oracle_positive_control_only": spec["candidate_class"] == CONTROL_ORACLE,
            "not_product_candidate": spec["candidate_class"] != PRODUCT,
            "not_enhancement_algorithm": spec["candidate_class"] in {CONTROL_ZERO, CONTROL_NEGATIVE, CONTROL_ORACLE},
            "not_production_evidence": spec["candidate_class"] != PRODUCT,
        },
    }
    return result


def _save_control_candidate(source: Path, destination: Path, control_type: str) -> None:
    with Image.open(source) as opened:
        opened.load()
        icc = opened.info.get("icc_profile")
        rgba = np.asarray(opened.convert("RGBA"), dtype=np.uint8)
    rgb = cv2.cvtColor(rgba[..., :3], cv2.COLOR_RGB2BGR)
    if control_type == "NEGATIVE_BLUR":
        changed = cv2.GaussianBlur(rgb, (0, 0), 3.2)
    elif control_type == "NEGATIVE_OVERSHARPEN":
        softened = cv2.GaussianBlur(rgb, (0, 0), 1.15)
        changed = np.clip(rgb.astype(np.float32) * 2.8 - softened.astype(np.float32) * 1.8, 0, 255).astype(np.uint8)
    elif control_type == "NEGATIVE_HALO_OR_RINGING":
        near = cv2.GaussianBlur(rgb, (0, 0), 0.75).astype(np.float32)
        far = cv2.GaussianBlur(rgb, (0, 0), 2.8).astype(np.float32)
        changed = np.clip(rgb.astype(np.float32) + (near - far) * 2.6, 0, 255).astype(np.uint8)
    elif control_type == "NEGATIVE_COLOR_SHIFT":
        hsv = cv2.cvtColor(rgb, cv2.COLOR_BGR2HSV).astype(np.int16)
        hsv[..., 1] = np.clip(hsv[..., 1] + 42, 0, 255)
        changed = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.int16)
        changed[..., 0] = np.clip(changed[..., 0] + 24, 0, 255)
        changed[..., 2] = np.clip(changed[..., 2] - 18, 0, 255)
        changed = changed.astype(np.uint8)
    else:
        raise E102Error(f"CONTROL_TYPE_UNKNOWN:{control_type}")
    out_rgb = cv2.cvtColor(changed, cv2.COLOR_BGR2RGB)
    out = np.dstack((out_rgb, rgba[..., 3]))
    destination.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(out, "RGBA")
    if np.all(rgba[..., 3] == 255):
        image = image.convert("RGB")
    options: dict[str, Any] = {"format": "PNG", "compress_level": 6}
    if isinstance(icc, bytes) and icc:
        options["icc_profile"] = icc
    image.save(destination, **options)


def _save_oracle_candidate(gt_path: Path, baseline_path: Path, destination: Path) -> None:
    with Image.open(baseline_path) as baseline_opened:
        baseline_opened.load()
        baseline = baseline_opened.convert("RGBA")
        target_size = baseline.size
        icc = baseline_opened.info.get("icc_profile")
    with Image.open(gt_path) as gt_opened:
        gt_opened.load()
        gt = ImageOps.exif_transpose(gt_opened).convert("RGBA")
    gt_aligned = gt.convert("RGBa").resize(target_size, Image.Resampling.LANCZOS).convert("RGBA")
    oracle = Image.blend(baseline.convert("RGB"), gt_aligned.convert("RGB"), 0.12).convert("RGBA")
    oracle.putalpha(baseline.getchannel("A"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    options: dict[str, Any] = {"format": "PNG", "compress_level": 6}
    if isinstance(icc, bytes) and icc:
        options["icc_profile"] = icc
    if baseline.getextrema()[3] == (255, 255):
        oracle = oracle.convert("RGB")
    oracle.save(destination, **options)


def _candidate_spec(case: dict[str, Any], candidate_path: Path, candidate_id: str, candidate_class: str, algorithm: str) -> dict[str, Any]:
    candidate_sha = sha256_file(candidate_path)
    parameters = {"gate_fixture": algorithm, "version": "V1"}
    replay_identity, replay_contract = compute_replay_identity(case, candidate_sha, algorithm, parameters)
    return {
        "candidate_id": candidate_id,
        "candidate_class": candidate_class,
        "candidate_identity": candidate_sha,
        "algorithm_identity": algorithm,
        "parameters": parameters,
        "canonical_parameters": _canonical_parameters(parameters),
        "source_binding_sha256": case["input"]["sha256"],
        "baseline_binding_sha256": case["safe_base"]["sha256"],
        "gt_binding_sha256_or_none": "NONE" if case["gt"] is None else case["gt"]["sha256"],
        "roi_set_sha256": _canonical_sha256(case["roi"]),
        "replay_identity": replay_identity,
        "replay_contract": replay_contract,
        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
        "human_review_evidence": None,
    }


def _validation_fixture_rgba(width: int = 384, height: int = 256) -> np.ndarray:
    canvas = np.full((height, width, 3), 118, dtype=np.uint8)
    cv2.rectangle(canvas, (24, 28), (width - 28, height - 32), (28, 220, 238), 5)
    cv2.line(canvas, (35, height - 48), (width - 45, 45), (245, 35, 35), 4)
    cv2.putText(canvas, "HDDE 4K", (45, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 4, cv2.LINE_AA)
    for x in range(40, width - 35, 18):
        cv2.line(canvas, (x, height // 2 + 35), (x, height // 2 + 60), (30, 30, 30), 2)
    return np.dstack((cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB), np.full((height, width), 255, dtype=np.uint8)))


def _validation_gt_pair(*, severe: bool) -> tuple[np.ndarray, np.ndarray]:
    gt = _validation_fixture_rgba()
    if severe:
        small = cv2.resize(gt[..., :3], (24, 16), interpolation=cv2.INTER_AREA)
        baseline_rgb = cv2.resize(small, (gt.shape[1], gt.shape[0]), interpolation=cv2.INTER_LINEAR)
    else:
        baseline_rgb = cv2.GaussianBlur(gt[..., :3], (0, 0), 2.6)
    return np.dstack((baseline_rgb, gt[..., 3])), gt


def _validation_text_bgr() -> np.ndarray:
    image = np.full((128, 320, 3), 245, dtype=np.uint8)
    cv2.putText(image, "HDDE 4K", (18, 78), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (20, 20, 20), 4, cv2.LINE_8)
    cv2.rectangle(image, (15, 15), (304, 108), (25, 25, 25), 2)
    return image


def _mandatory_control_validation(
    manifest: dict[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    base = _validation_fixture_rgba()
    severe_baseline, gt = _validation_gt_pair(severe=True)
    local_color_candidate = gt.copy()
    local_width = int(round(local_color_candidate.shape[1] * 0.04))
    local_color_candidate[:, :local_width, :3] = np.array([255, 0, 255], dtype=np.uint8)
    local_precondition = _gt_improvement(
        _analysis_bgr(severe_baseline),
        _analysis_bgr(local_color_candidate),
        _analysis_bgr(gt),
    )
    local_result = evaluate_arrays(severe_baseline, local_color_candidate, gt_rgba=gt, candidate_class=PRODUCT)

    hf_candidate = gt.copy().astype(np.int16)
    checker = ((np.indices((gt.shape[0], 16)).sum(axis=0) % 2) * 2 - 1) * 44
    hf_candidate[:, 150:166, :3] = np.clip(hf_candidate[:, 150:166, :3] + checker[..., None], 0, 255)
    hf_candidate = hf_candidate.astype(np.uint8)
    hf_precondition = _gt_improvement(_analysis_bgr(severe_baseline), _analysis_bgr(hf_candidate), _analysis_bgr(gt))
    hf_result = evaluate_arrays(severe_baseline, hf_candidate, gt_rgba=gt, candidate_class=PRODUCT)

    geometry_base = base.copy()
    rng = np.random.default_rng(20260821)
    geometry_base[..., :3] = np.clip(
        geometry_base[..., :3].astype(np.int16) + rng.integers(-12, 13, geometry_base[..., :3].shape, dtype=np.int16),
        0,
        255,
    ).astype(np.uint8)
    height, width = geometry_base.shape[:2]
    shift_3 = cv2.warpAffine(
        geometry_base,
        np.float32([[1.0, 0.0, 3.0], [0.0, 1.0, 0.0]]),
        (width, height),
        borderMode=cv2.BORDER_REFLECT,
    )
    shift_8 = cv2.warpAffine(
        geometry_base,
        np.float32([[1.0, 0.0, 8.0], [0.0, 1.0, 0.0]]),
        (width, height),
        borderMode=cv2.BORDER_REFLECT,
    )
    geometry_controls = {
        "GEOMETRY_SHIFT_3PX": _geometry_measurement(geometry_base, shift_3),
        "GEOMETRY_SHIFT_8PX": _geometry_measurement(geometry_base, shift_8),
    }
    crop = cv2.resize(geometry_base[12:-12, 18:-18], (width, height), interpolation=cv2.INTER_LINEAR)
    geometry_controls["GEOMETRY_CROP"] = _geometry_measurement(geometry_base, crop)
    inner = cv2.resize(geometry_base, (width - 40, height - 32), interpolation=cv2.INTER_AREA)
    padded = cv2.copyMakeBorder(inner, 16, 16, 20, 20, cv2.BORDER_CONSTANT, value=(127, 127, 127, 255))
    geometry_controls["GEOMETRY_PADDING"] = _geometry_measurement(geometry_base, padded)
    stretch_matrix = np.float32([[0.75, 0.0, width * 0.125], [0.0, 1.0, 0.0]])
    stretched = cv2.warpAffine(geometry_base, stretch_matrix, (width, height), borderMode=cv2.BORDER_REFLECT)
    geometry_controls["GEOMETRY_STRETCH"] = _geometry_measurement(geometry_base, stretched)
    low_texture = np.full((128, 192, 4), 128, dtype=np.uint8)
    low_texture_changed = low_texture.copy()
    low_texture_changed[0, 0, 0] = 129
    geometry_controls["GEOMETRY_UNCERTAIN"] = _geometry_measurement(low_texture, low_texture_changed)

    text = _validation_text_bgr()
    broken = text.copy()
    broken[:, 80:86] = 245
    broken[:, 150:156] = 245
    dark = np.all(text < 100, axis=2).astype(np.uint8)
    stuck_mask = cv2.dilate(dark, np.ones((9, 9), np.uint8), iterations=1)
    stuck = np.repeat(np.where(stuck_mask[..., None] > 0, 20, 245), 3, axis=2).astype(np.uint8)
    text_edges = cv2.Canny(cv2.cvtColor(text, cv2.COLOR_BGR2GRAY), 50, 150)
    doubled = text.copy()
    doubled[np.roll(text_edges, 3, axis=1) > 0] = (15, 15, 15)
    text_controls = {
        "TEXT_BROKEN_STROKE": _text_structure_facts(text, broken),
        "TEXT_STICKING": _text_structure_facts(text, stuck),
        "TEXT_DOUBLE_EDGE": _text_structure_facts(text, doubled),
    }

    edge_rgba = np.dstack((text[..., ::-1], np.full(text.shape[:2], 255, np.uint8)))
    edge_map = cv2.Canny(cv2.cvtColor(text, cv2.COLOR_BGR2GRAY), 50, 150)
    edge_ring = (cv2.dilate(edge_map, np.ones((5, 5), np.uint8)) > 0) & (edge_map == 0)
    black = text.copy()
    black[edge_ring] = 0
    white = text.copy()
    white[edge_ring] = 255
    black_result = evaluate_arrays(edge_rgba, np.dstack((black[..., ::-1], edge_rgba[..., 3])), candidate_class=CONTROL_NEGATIVE)
    white_result = evaluate_arrays(edge_rgba, np.dstack((white[..., ::-1], edge_rgba[..., 3])), candidate_class=CONTROL_NEGATIVE)

    alpha_candidate = base.copy()
    alpha_candidate[30:50, 40:70, 3] = 96
    alpha_result = evaluate_arrays(base, alpha_candidate, candidate_class=PRODUCT)

    moderate_baseline, moderate_gt = _validation_gt_pair(severe=False)
    review_candidate = moderate_baseline.copy()
    review_candidate[..., :3] = np.clip(
        moderate_baseline[..., :3].astype(np.float32) * 0.88 + moderate_gt[..., :3].astype(np.float32) * 0.12,
        0,
        255,
    ).astype(np.uint8)
    review_context = array_review_context("CONTROL_REVIEW", moderate_gt, moderate_baseline, review_candidate, moderate_gt)
    invalid_review_evidence = build_human_review_evidence(review_context, "BETTER")
    invalid_review_evidence["review_evidence_id"] = "0" * 64
    unbound_review = evaluate_arrays(
        moderate_baseline,
        review_candidate,
        gt_rgba=moderate_gt,
        candidate_class=PRODUCT,
        human_review_context=review_context,
        human_review_evidence=invalid_review_evidence,
    )
    bound_better = evaluate_arrays(
        moderate_baseline,
        review_candidate,
        gt_rgba=moderate_gt,
        candidate_class=PRODUCT,
        human_review_context=review_context,
        human_review_evidence=build_human_review_evidence(review_context, "BETTER"),
    )
    bound_worse = evaluate_arrays(
        moderate_baseline,
        review_candidate,
        gt_rgba=moderate_gt,
        candidate_class=PRODUCT,
        human_review_context=review_context,
        human_review_evidence=build_human_review_evidence(review_context, "WORSE"),
    )
    mismatched_review_context = {**review_context, "case_id": "CONTROL_REVIEW_MISMATCH"}
    case_mismatch = evaluate_arrays(
        moderate_baseline,
        review_candidate,
        gt_rgba=moderate_gt,
        candidate_class=PRODUCT,
        human_review_context=mismatched_review_context,
        human_review_evidence=build_human_review_evidence(review_context, "BETTER"),
    )
    asset_mismatch_context = {**review_context, "comparison_asset_set": {"fixture": "0" * 64}}
    asset_mismatch = evaluate_arrays(
        moderate_baseline,
        review_candidate,
        gt_rgba=moderate_gt,
        candidate_class=PRODUCT,
        human_review_context=asset_mismatch_context,
        human_review_evidence=build_human_review_evidence(review_context, "BETTER"),
    )

    replay_case = next(item for item in manifest["cases"] if item["case_id"] == "E1C002")
    replay_candidate = _manifest_asset(replay_case["safe_base"]["path"])
    valid_replay = _candidate_spec(replay_case, replay_candidate, "CONTROL_REPLAY", CONTROL_ZERO, "BASELINE_IDENTITY_CONTROL")
    replay_specs: dict[str, dict[str, Any]] = {}
    replay_specs["INVALID_REPLAY_ID"] = {**valid_replay, "replay_identity": "0" * 64}
    replay_specs["PARAMETERS_NONE"] = {**valid_replay, "parameters": None}
    replay_specs["PARAMETERS_CHANGED"] = {**valid_replay, "parameters": {"changed": True}}
    replay_specs["CANDIDATE_SHA_CHANGED"] = {**valid_replay, "candidate_identity": "f" * 64}
    replay_specs["ROI_BINDING_CHANGED"] = {**valid_replay, "roi_set_sha256": "e" * 64}
    replay_controls = {
        name: _eligibility(replay_case, replay_candidate, spec)
        for name, spec in replay_specs.items()
    }

    zero = [item for item in results if item["candidate_class"] == CONTROL_ZERO]
    negatives = [item for item in results if item["candidate_class"] == CONTROL_NEGATIVE]
    oracles = [item for item in results if item["candidate_class"] == CONTROL_ORACLE]
    all_eligible = all(item["eligibility"]["status"] == "ELIGIBLE" for item in results)
    replay_expected = {
        "INVALID_REPLAY_ID": "INVALID_REPLAY_ID",
        "PARAMETERS_NONE": "PARAMETERS_NONE",
        "PARAMETERS_CHANGED": "PARAMETERS_CHANGED",
        "CANDIDATE_SHA_CHANGED": "CANDIDATE_SHA_CHANGED",
        "ROI_BINDING_CHANGED": "ROI_BINDING_CHANGED",
    }
    replay_pass = all(
        replay_controls[name]["status"] == "INELIGIBLE" and code in replay_controls[name]["failures"]
        for name, code in replay_expected.items()
    )
    geometry_expected = {
        "GEOMETRY_SHIFT_3PX": ("FAIL", "TRANSLATION_OR_GEOMETRIC_DRIFT_DETECTED"),
        "GEOMETRY_SHIFT_8PX": ("FAIL", "TRANSLATION_OR_GEOMETRIC_DRIFT_DETECTED"),
        "GEOMETRY_CROP": ("FAIL", "CROP_PADDING_OR_STRETCH_DETECTED"),
        "GEOMETRY_PADDING": ("FAIL", "CROP_PADDING_OR_STRETCH_DETECTED"),
        "GEOMETRY_STRETCH": ("FAIL", "CROP_PADDING_OR_STRETCH_DETECTED"),
        "GEOMETRY_UNCERTAIN": ("REVIEW", "LOW_TEXTURE_GEOMETRY_NEED_PROOF"),
    }
    geometry_pass = all(
        geometry_controls[name]["status"] == expected_status
        and geometry_controls[name]["decision"] == expected_decision
        and geometry_controls[name]["decision_reason"] == expected_decision
        and (
            geometry_controls[name]["estimated_transform"] is not None
            and isinstance(geometry_controls[name]["confidence"], float)
            and isinstance(geometry_controls[name]["residual_or_error"], float)
            if name != "GEOMETRY_UNCERTAIN"
            else geometry_controls[name]["estimated_transform"] is None
            and geometry_controls[name]["confidence"] == 0.0
            and geometry_controls[name]["residual_or_error"] is None
        )
        for name, (expected_status, expected_decision) in geometry_expected.items()
    )
    geometry_pass = geometry_pass and all(
        geometry_controls[name]["estimated_transform"]["translation_method"] == "PHASE_CORRELATION"
        and abs(geometry_controls[name]["estimated_transform"]["translation_magnitude_px"] - expected_magnitude) <= 1.0
        and geometry_controls[name]["confidence"] >= CONTROL_THRESHOLDS["geometry_phase_translation_confidence_min"]
        for name, expected_magnitude in {"GEOMETRY_SHIFT_3PX": 3.0, "GEOMETRY_SHIFT_8PX": 8.0}.items()
    )
    text_pass = all(
        text_controls[name]["raw_detection"][flag]
        for name, flag in {
            "TEXT_BROKEN_STROKE": "broken_stroke",
            "TEXT_STICKING": "sticking",
            "TEXT_DOUBLE_EDGE": "double_edge",
        }.items()
    )
    edge_pass = (
        black_result["hard_safety_gate"]["raw_detection"]["black_edge"]
        and white_result["hard_safety_gate"]["raw_detection"]["white_edge"]
        and any(item["safety_results"]["raw_detection"]["halo_or_ringing"] for item in negatives)
    )
    mandatory = {
        "ELIGIBILITY_GATE": "PASS" if all_eligible else "FAIL",
        "REPLAY_BINDING_GATE": "PASS" if all_eligible and replay_pass else "FAIL",
        "HARD_SAFETY_GATE": "PASS" if local_result["delivery_status"] == "FAIL" and hf_result["delivery_status"] == "FAIL" else "FAIL",
        "GEOMETRY_SAFETY_GATE": "PASS" if geometry_pass else "FAIL",
        "ALPHA_SAFETY_GATE": "PASS" if "ALPHA_IDENTITY_FAILED" in alpha_result["hard_safety_gate"]["failures"] else "FAIL",
        "EDGE_ARTIFACT_GATE": "PASS" if edge_pass else "FAIL",
        "HIGH_FREQUENCY_GATE": "PASS" if hf_result["hard_safety_gate"]["raw_detection"]["high_frequency_anomaly"] else "FAIL",
        "COLOR_SAFETY_GATE": "PASS" if local_result["hard_safety_gate"]["raw_detection"]["local_color_shift"] else "FAIL",
        "TEXT_FIDELITY_GATE": "PASS" if text_pass else "FAIL",
        "DETAIL_GAIN_GATE": "PASS" if all(item["quality_gain_status"] == QUALITY_GAIN_NOT_PROVEN for item in zero) and all(item["quality_gain_status"] == QUALITY_GAIN_PROVEN for item in oracles) else "FAIL",
        "HUMAN_REVIEW_BINDING_GATE": "PASS" if (
            unbound_review["quality_gain_status"] != QUALITY_GAIN_PROVEN
            and bound_better["human_review_binding_valid"]
            and bound_better["human_review_control_fixture_only"]
            and not bound_better["human_review_product_admissible"]
            and bound_better["quality_gain_status"] == QUALITY_GAIN_NOT_PROVEN
            and bound_better["delivery_status"] != "PASS"
            and bound_worse["human_review_binding_valid"]
            and bound_worse["human_review_control_fixture_only"]
            and not bound_worse["human_review_product_admissible"]
            and bound_worse["quality_gain_status"] == QUALITY_GAIN_NOT_PROVEN
            and bound_worse["delivery_status"] != "PASS"
            and case_mismatch["human_review_status"] == "UNBOUND"
            and asset_mismatch["human_review_status"] == "UNBOUND"
        ) else "FAIL",
    }
    fixture_authorization_count = sum(
        item["human_review_control_fixture_only"] is True
        and (item["quality_gain_status"] == QUALITY_GAIN_PROVEN or item["delivery_status"] == "PASS")
        for item in (bound_better, bound_worse)
    )
    return {
        "control_scope": "CONTROL_FIXTURE_ONLY_NOT_PRODUCTION_EVIDENCE",
        "mandatory_sub_gates": mandatory,
        "gt_cross_safety": {
            "GT_POSITIVE_WITH_LOCAL_COLOR_DAMAGE": {"precondition": local_precondition, "result": local_result},
            "GT_POSITIVE_WITH_HIGH_FREQUENCY_DAMAGE": {"precondition": hf_precondition, "result": hf_result},
        },
        "geometry_controls": geometry_controls,
        "replay_controls": replay_controls,
        "text_controls": text_controls,
        "edge_controls": {
            "BLACK_EDGE": black_result["hard_safety_gate"],
            "WHITE_EDGE": white_result["hard_safety_gate"],
        },
        "alpha_control": alpha_result["hard_safety_gate"],
        "human_review_controls": {
            "UNBOUND_BETTER": unbound_review,
            "VALID_BOUND_BETTER": bound_better,
            "VALID_BOUND_WORSE": bound_worse,
            "REVIEW_CASE_MISMATCH": case_mismatch,
            "REVIEW_ASSET_HASH_MISMATCH": asset_mismatch,
        },
        "control_fixture_product_authorization_count": fixture_authorization_count,
    }


def build(output_root: Path = OUTPUT_ROOT, manifest_path: Path = E1_01_MANIFEST) -> dict[str, Any]:
    root = output_root.expanduser().resolve()
    if root.exists():
        raise E102Error(f"OUTPUT_ROOT_ALREADY_EXISTS:{root}")
    validation = validate_manifest(manifest_path)
    if validation.get("status") != "PASS" or validation.get("case_count") != 16:
        raise E102Error("E1_01_VALIDATION_NOT_READY")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    e1_before = directory_state(E1_01_ROOT)
    root.mkdir(parents=True)
    for name in ("case_results", "roi_results", "comparison_assets", "control_candidates"):
        (root / name).mkdir()

    results: list[dict[str, Any]] = []

    def record(case: dict[str, Any], candidate: Path, candidate_id: str, candidate_class: str, algorithm: str) -> None:
        spec = _candidate_spec(case, candidate, candidate_id, candidate_class, algorithm)
        comparison_root = root / "comparison_assets" / candidate_id
        result = evaluate_case(manifest_path, case["case_id"], candidate, spec, comparison_root)
        case_payload = {key: value for key, value in result.items() if key != "roi_results"}
        case_path = root / "case_results" / f"{candidate_id}.json"
        roi_path = root / "roi_results" / f"{candidate_id}.json"
        atomic_write_json(case_path, case_payload)
        atomic_write_json(roi_path, {"case_id": candidate_id, "roi_results": result["roi_results"]})
        results.append({**case_payload, "case_result_path": relative_path(case_path), "roi_result_path": relative_path(roi_path)})

    for case in manifest["cases"]:
        baseline = _manifest_asset(case["safe_base"]["path"])
        record(case, baseline, f"ZERO__{case['case_id']}", CONTROL_ZERO, "BASELINE_IDENTITY_CONTROL")

    negative_case = next(case for case in manifest["cases"] if case["case_id"] == "E1C002")
    negative_baseline = _manifest_asset(negative_case["safe_base"]["path"])
    for control_type in (
        "NEGATIVE_BLUR",
        "NEGATIVE_OVERSHARPEN",
        "NEGATIVE_HALO_OR_RINGING",
        "NEGATIVE_COLOR_SHIFT",
    ):
        candidate = root / "control_candidates" / f"{control_type}.png"
        _save_control_candidate(negative_baseline, candidate, control_type)
        record(negative_case, candidate, control_type, CONTROL_NEGATIVE, control_type)

    for case in (item for item in manifest["cases"] if item["gt"] is not None):
        baseline = _manifest_asset(case["safe_base"]["path"])
        gt = _manifest_asset(case["gt"]["path"])
        candidate_id = f"ORACLE__{case['case_id']}"
        candidate = root / "control_candidates" / f"{candidate_id}.png"
        _save_oracle_candidate(gt, baseline, candidate)
        record(case, candidate, candidate_id, CONTROL_ORACLE, "ORACLE_POSITIVE_CONTROL_ONLY")

    all_product = [item for item in results if item["candidate_class"] == PRODUCT]
    product = [
        item for item in all_product
        if item.get("human_review_control_fixture_only") is not True
        and item.get("test_vector_only") is not True
    ]
    zero = [item for item in results if item["candidate_class"] == CONTROL_ZERO]
    negatives = [item for item in results if item["candidate_class"] == CONTROL_NEGATIVE]
    oracles = [item for item in results if item["candidate_class"] == CONTROL_ORACLE]
    product_counts = {
        "PRODUCT_CANDIDATE_QUALITY_GAIN_PROVEN_COUNT": sum(item["quality_gain_status"] == QUALITY_GAIN_PROVEN for item in product),
        "PRODUCT_CANDIDATE_QUALITY_GAIN_NOT_PROVEN_COUNT": sum(item["quality_gain_status"] == QUALITY_GAIN_NOT_PROVEN for item in product),
        "PRODUCT_CANDIDATE_QUALITY_GAIN_REJECTED_COUNT": sum(item["quality_gain_status"] == QUALITY_GAIN_REJECTED for item in product),
    }
    control_counts = {
        "CONTROL_ORACLE_POSITIVE_TOTAL": len(oracles),
        "CONTROL_ORACLE_POSITIVE_DETECTED_COUNT": sum(item["quality_gain_status"] == QUALITY_GAIN_PROVEN for item in oracles),
        "CONTROL_ORACLE_FALSE_NEGATIVE_COUNT": sum(item["quality_gain_status"] != QUALITY_GAIN_PROVEN for item in oracles),
        "CONTROL_ZERO_GAIN_TOTAL": len(zero),
        "CONTROL_ZERO_GAIN_FALSE_POSITIVE_COUNT": sum(item["quality_gain_status"] == QUALITY_GAIN_PROVEN for item in zero),
        "CONTROL_NEGATIVE_TOTAL": len(negatives),
        "CONTROL_NEGATIVE_FALSE_POSITIVE_COUNT": sum(item["quality_gain_status"] == QUALITY_GAIN_PROVEN for item in negatives),
    }
    negative_detection = {
        item["case_id"]: {
            "quality_gain_status": item["quality_gain_status"],
            "delivery_status": item["delivery_status"],
            "failures": item["safety_results"]["failures"],
            "raw_detection": item["safety_results"]["raw_detection"],
        }
        for item in negatives
    }
    expected_negative = {
        "NEGATIVE_BLUR": "blur",
        "NEGATIVE_OVERSHARPEN": "oversharpen",
        "NEGATIVE_HALO_OR_RINGING": "halo_or_ringing",
        "NEGATIVE_COLOR_SHIFT": "color_shift",
    }
    negative_complete = all(
        negative_detection.get(name, {}).get("raw_detection", {}).get(flag) is True
        and negative_detection[name]["quality_gain_status"] == QUALITY_GAIN_REJECTED
        for name, flag in expected_negative.items()
    )
    control_validation = _mandatory_control_validation(manifest, results)
    mandatory_sub_gates = control_validation["mandatory_sub_gates"]
    mandatory_aggregation = aggregate_mandatory_gates(mandatory_sub_gates)
    mandatory_complete = mandatory_aggregation["mandatory_gate_complete"]
    control_fixture_authorizations = (
        control_fixture_product_authorization_count(results)
        + int(control_validation["control_fixture_product_authorization_count"])
    )
    product_invariant = validate_product_pass_global_invariant(results)
    statistics_consistent = (
        sum(product_counts.values()) == len(product)
        and control_counts["CONTROL_ORACLE_POSITIVE_TOTAL"] == len(oracles)
        and control_counts["CONTROL_ZERO_GAIN_TOTAL"] == len(zero)
        and control_counts["CONTROL_NEGATIVE_TOTAL"] == len(negatives)
        and control_fixture_authorizations == 0
    )
    e1_after = directory_state(E1_01_ROOT)
    e1_unchanged = e1_before == e1_after
    all_cases_reused = {item["e1_01_case_id"] for item in zero} == {item["case_id"] for item in manifest["cases"]}
    oracle_complete = control_counts["CONTROL_ORACLE_FALSE_NEGATIVE_COUNT"] == 0 and len(oracles) == manifest["gt_case_count"]
    zero_complete = control_counts["CONTROL_ZERO_GAIN_FALSE_POSITIVE_COUNT"] == 0 and len(zero) == manifest["case_count"]
    gate_complete = (
        all_cases_reused
        and e1_unchanged
        and zero_complete
        and negative_complete
        and oracle_complete
        and mandatory_complete
        and control_fixture_authorizations == 0
        and product_invariant["status"] == "PASS"
        and statistics_consistent
    )
    summary = {
        "gate_version": GATE_VERSION,
        "metric_protocol_version": METRIC_PROTOCOL_VERSION,
        "status": "PASS" if gate_complete else "BLOCKED",
        "GATE_VALIDATION_COMPLETE": "YES" if gate_complete else "NO",
        "GATE_COMPLETE": "YES" if gate_complete else "NO",
        "MANDATORY_GATE_AGGREGATION_VERSION": MANDATORY_GATE_AGGREGATION_VERSION,
        "MANDATORY_GATE_COMPLETE": "YES" if mandatory_complete else "NO",
        "MANDATORY_GATE_AGGREGATION": mandatory_aggregation,
        "CONTROL_FIXTURE_PRODUCT_AUTHORIZATION_COUNT": control_fixture_authorizations,
        "PRODUCT_PASS_GLOBAL_INVARIANT": product_invariant["status"],
        "PRODUCT_PASS_GLOBAL_INVARIANT_EVIDENCE": product_invariant,
        "STATISTICS_CONSISTENT": "YES" if statistics_consistent else "NO",
        "E1_01_CASE_REUSE": "ALL_VALID_CASES" if all_cases_reused else "INCOMPLETE",
        "E1_01_CASES_REUSED": len({item["e1_01_case_id"] for item in zero}),
        "GT_CASES_USED": len(oracles),
        "ROI_BINDING": "PASS" if all(item["eligibility"]["status"] == "ELIGIBLE" for item in results) else "FAIL",
        "RERENDER_CANDIDATE_COMPARISONS_REUSED": "YES",
        "ZERO_GAIN_CONTROL": "PASS" if zero_complete else "FAIL",
        "NEGATIVE_CONTROLS": negative_detection,
        "ORACLE_POSITIVE_CONTROL": "PASS" if oracle_complete else "FAIL",
        "ORACLE_MARKERS": [
            "ORACLE_POSITIVE_CONTROL_ONLY",
            "NOT_PRODUCT_CANDIDATE",
            "NOT_ENHANCEMENT_ALGORITHM",
            "NOT_PRODUCTION_EVIDENCE",
        ],
        **mandatory_sub_gates,
        **product_counts,
        **control_counts,
        "REAL_4K_QUALITY_GAIN": "NOT_PROVEN",
        "e1_01_before": e1_before,
        "e1_01_after": e1_after,
        "e1_01_unchanged": e1_unchanged,
    }
    manifest_payload = {
        "manifest_version": GATE_VERSION,
        "status": summary["status"],
        "source_manifest": relative_path(manifest_path),
        "source_manifest_sha256": sha256_file(manifest_path),
        "thresholds": CONTROL_THRESHOLDS,
        "threshold_scope": "CONTROL_VALIDATION_ONLY_NOT_PRODUCTION_ADOPTION",
        "mandatory_sub_gates": mandatory_sub_gates,
        "mandatory_gate_aggregation": mandatory_aggregation,
        "control_validation": relative_path(root / "control_validation.json"),
        "reuse_decisions": {
            "rerender_candidate_comparisons": "REUSED_FOR_FULL_IMAGE_ROI_AND_COMPARISON_CONTRACT",
            "quality_compare": "REUSED_AS_PROXY_FACTS_ONLY_NOT_DELIVERY_AUTHORITY",
            "quality_metrics": "REUSED_AS_RAW_PROXY_FACTS_ONLY",
            "text_clarity": "REUSED_AS_TEXT_LIKE_MASK_PROXY_NOT_OCR_TRUTH",
            "image_type_detector": "REUSED_AS_HEURISTIC_CONTEXT_NOT_ROUTING_TRUTH",
            "hd_core_safe_base": "REUSED_ALPHA_IDENTITY_AND_FAIL_CLOSED_CONTRACT; RGB_EQUIVALENCE_GATE_NOT_USED_AS_GAIN_AUTHORITY",
            "hd_core_pipeline": "REVIEWED_NOT_CALLED; EXPERIMENT_REMAINS_ISOLATED_FROM_FORMAL_4K",
        },
        "no_processing_needed_policy": {
            "candidate_policy": NO_PROCESSING_NEEDED_CANDIDATE_POLICY,
            "baseline_artifact": NO_PROCESSING_NEEDED_BASELINE_ARTIFACT,
            "fallback": NO_PROCESSING_NEEDED_FALLBACK,
        },
        "case_results": [
            {
                "case_id": item["case_id"],
                "e1_01_case_id": item["e1_01_case_id"],
                "candidate_class": item["candidate_class"],
                "quality_gain_status": item["quality_gain_status"],
                "delivery_status": item["delivery_status"],
                "mandatory_gate_complete": item["mandatory_gate_complete"],
                "human_review_control_fixture_only": item["human_review_control_fixture_only"],
                "human_review_product_admissible": item["human_review_product_admissible"],
                "test_vector_only": item["test_vector_only"],
                "case_result_path": item["case_result_path"],
                "roi_result_path": item["roi_result_path"],
                "comparison_manifest": item["evidence_refs"]["comparison_manifest"],
            }
            for item in results
        ],
        "summary": summary,
    }
    atomic_write_json(root / "gate_summary.json", summary)
    atomic_write_json(root / "manifest.json", manifest_payload)
    atomic_write_json(root / "control_validation.json", control_validation)
    atomic_write_json(
        root / "validation.json",
        {
            "status": summary["status"],
            "gate_validation_complete": gate_complete,
            "checks": {
                "all_e1_01_cases_reused": all_cases_reused,
                "e1_01_unchanged": e1_unchanged,
                "zero_gain_no_false_positive": zero_complete,
                "four_negative_controls_detected": negative_complete,
                "oracle_positive_detected": oracle_complete,
                "oracle_product_statistics_isolated": product_counts["PRODUCT_CANDIDATE_QUALITY_GAIN_PROVEN_COUNT"] == 0,
                "mandatory_sub_gates_complete": mandatory_complete,
                "control_fixture_product_authorization_count_zero": control_fixture_authorizations == 0,
                "product_pass_global_invariant": product_invariant["status"] == "PASS",
                "statistics_consistent": statistics_consistent,
                "formal_4k_integration": False,
            },
            "mandatory_sub_gates": mandatory_sub_gates,
            "mandatory_gate_aggregation": mandatory_aggregation,
            "product_pass_global_invariant": product_invariant,
            "summary": summary,
        },
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the isolated HDDE E1-02 quality and delivery gate evidence.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--manifest", type=Path, default=E1_01_MANIFEST)
    args = parser.parse_args()
    result = build(args.output_root, args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
