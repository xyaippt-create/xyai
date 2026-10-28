"""Frozen Color Core V2 executors and target-conditioned Safety Gate 2.0.

This production module operates only on the current image, D-01 facts, and
runtime masks.  It never reads evaluation artifacts, sample identities, or
ground-truth images.  The caller supplies the established D-04 non-color
review functions so the V2 color gates extend rather than relax them.
"""

from __future__ import annotations

from typing import Any, Callable

import cv2
import numpy as np


COLOR_CORE_V2_VERSION = "hdde.color-core-v2.1"
GLOBAL_ROUTE_NAME = "cross_affine_balanced"
LOCAL_ROUTE_NAME = "guided_rgb_lab_field_selective"

_TARGET_NEUTRAL_AB = np.array([1.5, 2.4], dtype=np.float32)
_GLOBAL_ROUTE: dict[str, Any] = {
    "basis": "affine",
    "ridge": 0.030,
    "neutral_strength": 1.00,
    "skin_strength": 1.00,
    "skin_weight": 1.50,
    "protected_weight": 0.20,
}
_LOCAL_ROUTE: dict[str, float] = {
    "skin_strength": 1.34,
    "shirt_strength": 1.20,
    "skin_cap": 52.0,
    "neutral_cap": 26.0,
    "affine_mix": 0.24,
    "field_sigma": 0.044,
    "ridge": 0.060,
}


def _global_eligible(analysis: dict[str, Any]) -> bool:
    key_color = analysis.get("key_color") or {}
    return bool(
        analysis.get("processing_decision") == "NORMAL"
        and analysis.get("cast_interpretation") == "global_error_cast"
        and analysis.get("global_cast_direction") in {"warm", "cool"}
        and float(analysis.get("global_cast_confidence") or 0.0) >= 0.65
        and not analysis.get("mixed_light")
        and not analysis.get("strong_local_light")
        and not analysis.get("legitimate_warm")
        and not analysis.get("legitimate_dark")
        and key_color.get("probable_product_or_screen_color") == "none"
    )


def _basis(rgb01: np.ndarray) -> np.ndarray:
    return np.column_stack((rgb01, np.ones(len(rgb01), dtype=np.float32)))


def _global_evidence(
    rgb: np.ndarray,
    faces: list[tuple[int, int, int, int]],
    strong_color_mask: np.ndarray,
    person_masks: Callable[[tuple[int, int], list[tuple[int, int, int, int]]], tuple[np.ndarray, np.ndarray]],
) -> dict[str, Any]:
    lab = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    hsv = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
    ycc = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2YCrCb)
    a_axis, b_axis = lab[..., 1] - 128.0, lab[..., 2] - 128.0
    saturation = hsv[..., 1] / 255.0
    neutral = (
        (saturation < 0.22)
        & (lab[..., 0] > 35.0)
        & (lab[..., 0] < 235.0)
        & (strong_color_mask < 0.25)
    )
    face_mask, person_mask = person_masks(rgb.shape[:2], faces)
    skin = (
        (face_mask >= 0.25)
        & (ycc[..., 0] > 40)
        & (ycc[..., 1] >= 128)
        & (ycc[..., 1] <= 180)
        & (ycc[..., 2] >= 75)
        & (ycc[..., 2] <= 138)
        & (a_axis > 3.0)
        & (a_axis < 30.0)
        & (b_axis > -2.0)
        & (b_axis < 35.0)
    )
    protected = (strong_color_mask >= 0.45) & (person_mask <= 0.08)
    return {
        "lab": lab,
        "neutral": neutral,
        "skin": skin,
        "protected": protected,
        "face_mask": face_mask,
        "person_mask": person_mask,
    }


def _global_targets(
    rgb: np.ndarray,
    evidence: dict[str, Any],
    valid_mask: np.ndarray | None = None,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    lab = evidence["lab"]
    neutral = evidence["neutral"]
    skin = evidence["skin"]
    visible = (
        np.ones(neutral.shape, dtype=bool)
        if valid_mask is None
        else np.asarray(valid_mask, dtype=bool)
    )
    if visible.shape != neutral.shape or not visible.any():
        raise RuntimeError("invalid visible-pixel evidence for Color Core V2")
    visible_count = int(visible.sum())
    if int(neutral.sum()) < max(96, int(visible_count * 0.005)):
        raise RuntimeError("insufficient neutral evidence for Color Core V2")
    neutral_before = np.median(lab[..., 1:3][neutral] - 128.0, axis=0)
    neutral_target_lab = lab.copy()
    neutral_target_lab[..., 1] = np.clip(
        neutral_target_lab[..., 1] + (_TARGET_NEUTRAL_AB[0] - neutral_before[0]), 0.0, 255.0
    )
    neutral_target_lab[..., 2] = np.clip(
        neutral_target_lab[..., 2] + (_TARGET_NEUTRAL_AB[1] - neutral_before[1]), 0.0, 255.0
    )
    neutral_target = cv2.cvtColor(neutral_target_lab.astype(np.uint8), cv2.COLOR_LAB2RGB)

    skin_target = rgb.copy()
    skin_before: list[float] | None = None
    skin_target_ab: list[float] | None = None
    if int(skin.sum()) >= max(64, int((evidence["face_mask"] >= 0.25).sum() * 0.04)):
        skin_before_array = np.median(lab[..., 1:3][skin] - 128.0, axis=0)
        target_a, target_b = 14.0, 20.2
        skin_target_lab = lab.copy()
        skin_target_lab[..., 1] = np.clip(skin_target_lab[..., 1] + target_a - skin_before_array[0], 0.0, 255.0)
        skin_target_lab[..., 2] = np.clip(skin_target_lab[..., 2] + target_b - skin_before_array[1], 0.0, 255.0)
        skin_target = cv2.cvtColor(skin_target_lab.astype(np.uint8), cv2.COLOR_LAB2RGB)
        skin_before = [round(float(value), 4) for value in skin_before_array]
        skin_target_ab = [target_a, target_b]

    confidence = float(
        np.clip(
            0.52 * float((neutral.sum() / visible_count) / 0.20)
            + 0.28 * float(min(1.0, skin.sum() / max((evidence["face_mask"] >= 0.25).sum() * 0.20, 1.0)))
            + 0.20,
            0.0,
            1.0,
        )
    )
    return {"neutral": neutral_target, "skin": skin_target, "protected": rgb}, {
        "neutral_pixels": int(neutral.sum()),
        "neutral_ratio": round(float(neutral.sum() / visible_count), 4),
        "neutral_before_ab": [round(float(value), 4) for value in neutral_before],
        "neutral_target_ab": [float(value) for value in _TARGET_NEUTRAL_AB],
        "skin_pixels": int(skin.sum()),
        "skin_before_ab": skin_before,
        "skin_target_ab": skin_target_ab,
        "target_confidence": round(confidence, 4),
        "target_uncertainty": round(1.0 - confidence, 4),
        "runtime_ground_truth_used": False,
    }


def _fit_global_mapping(
    rgb: np.ndarray,
    evidence: dict[str, Any],
    targets: dict[str, np.ndarray],
) -> tuple[np.ndarray, dict[str, Any]]:
    rng = np.random.default_rng(20260813)
    source_flat = rgb.reshape(-1, 3).astype(np.float32) / 255.0
    inputs: list[np.ndarray] = []
    outputs: list[np.ndarray] = []
    weights: list[np.ndarray] = []
    support_counts: dict[str, int] = {}
    for name, target, weight, limit in (
        ("neutral", targets["neutral"], 1.0, 9000),
        ("skin", targets["skin"], float(_GLOBAL_ROUTE["skin_weight"]), 6000),
        ("protected", targets["protected"], float(_GLOBAL_ROUTE["protected_weight"]), 5000),
    ):
        indexes = np.flatnonzero(evidence[name])
        if len(indexes) == 0:
            support_counts[name] = 0
            continue
        indexes = rng.choice(indexes, min(limit, len(indexes)), replace=False)
        inputs.append(_basis(source_flat[indexes]))
        outputs.append(target.reshape(-1, 3)[indexes].astype(np.float32) / 255.0)
        weights.append(np.full(len(indexes), weight, dtype=np.float32))
        support_counts[name] = int(len(indexes))
    design = np.vstack(inputs)
    target_values = np.vstack(outputs)
    sample_weights = np.concatenate(weights)
    weighted = design * np.sqrt(sample_weights)[:, None]
    weighted_target = target_values * np.sqrt(sample_weights)[:, None]
    identity = np.zeros((4, 3), dtype=np.float32)
    identity[:3] = np.eye(3, dtype=np.float32)
    regularizer = np.diag(np.array([1.0, 1.0, 1.0, 0.25], dtype=np.float32))
    ridge = float(_GLOBAL_ROUTE["ridge"]) * len(design)
    matrix = np.linalg.solve(
        weighted.T @ weighted + ridge * regularizer,
        weighted.T @ weighted_target + ridge * regularizer @ identity,
    )
    matrix[:3] = np.clip(matrix[:3], -0.25, 1.35)
    for channel in range(3):
        matrix[channel, channel] = np.clip(matrix[channel, channel], 0.65, 1.35)
    matrix[-1] = np.clip(matrix[-1], -0.10, 0.10)
    return matrix.astype(np.float32), {
        "basis": "full_cross_channel_affine",
        "coefficients": [[round(float(value), 6) for value in row] for row in matrix],
        "support_counts": support_counts,
        "ridge": float(_GLOBAL_ROUTE["ridge"]),
        "condition_number": round(float(np.linalg.cond(weighted.T @ weighted + ridge * regularizer)), 4),
    }


def _apply_global_mapping(rgb: np.ndarray, matrix: np.ndarray, strength: float) -> np.ndarray:
    source = rgb.reshape(-1, 3).astype(np.float32) / 255.0
    mapped = _basis(source) @ matrix
    blended = source * (1.0 - strength) + mapped * strength
    output = np.clip(np.rint(blended.reshape(rgb.shape) * 255.0), 0.0, 255.0).astype(np.uint8)
    source_lab = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2LAB)
    output_lab = cv2.cvtColor(output, cv2.COLOR_RGB2LAB)
    output_lab[..., 0] = source_lab[..., 0]
    output = cv2.cvtColor(output_lab, cv2.COLOR_LAB2RGB)
    for channel in range(3):
        low = (rgb[..., channel] > 1) & (output[..., channel] <= 1)
        high = (rgb[..., channel] < 254) & (output[..., channel] >= 254)
        output[..., channel][low] = 2
        output[..., channel][high] = 253
    return output


def _target_distance(lab: np.ndarray, mask: np.ndarray, target: list[float] | np.ndarray | None) -> float | None:
    if target is None or int(mask.sum()) < 48:
        return None
    values = np.median(lab[..., 1:3][mask] - 128.0, axis=0)
    return float(np.linalg.norm(values - np.asarray(target, dtype=np.float32)))


def _review_global(
    source_rgb: np.ndarray,
    candidate_rgb: np.ndarray,
    evidence: dict[str, Any],
    prediction: dict[str, Any],
    before_metrics: dict[str, float],
    focus_mask: np.ndarray,
    background_mask: np.ndarray,
    metrics_fn: Callable[..., dict[str, float]],
    noise_fn: Callable[[np.ndarray, np.ndarray], dict[str, Any]],
    halo_fn: Callable[[np.ndarray, np.ndarray], dict[str, Any]],
) -> dict[str, Any]:
    source_lab = cv2.cvtColor(source_rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    candidate_lab = cv2.cvtColor(candidate_rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    neutral_before = _target_distance(source_lab, evidence["neutral"], prediction["neutral_target_ab"])
    neutral_after = _target_distance(candidate_lab, evidence["neutral"], prediction["neutral_target_ab"])
    skin_before = _target_distance(source_lab, evidence["skin"], prediction["skin_target_ab"])
    skin_after = _target_distance(candidate_lab, evidence["skin"], prediction["skin_target_ab"])
    protected = evidence["protected"]
    delta_e = np.linalg.norm(candidate_lab - source_lab, axis=2)
    protected_mean = float(delta_e[protected].mean()) if protected.any() else 0.0
    protected_p95 = float(np.percentile(delta_e[protected], 95)) if protected.any() else 0.0
    after_metrics = metrics_fn(candidate_rgb, focus_mask, background_mask)
    noise = noise_fn(source_rgb, candidate_rgb)
    halo = halo_fn(source_rgb, candidate_rgb)
    highlight_delta = float(after_metrics["highlight_ratio"] - before_metrics["highlight_ratio"])
    black_delta = float(abs(after_metrics["black_point"] - before_metrics["black_point"]))
    luma_delta = float(abs(after_metrics["mean_luminance"] - before_metrics["mean_luminance"]))
    source_clipped = ((source_rgb <= 1) | (source_rgb >= 254)).any(axis=2)
    candidate_clipped = ((candidate_rgb <= 1) | (candidate_rgb >= 254)).any(axis=2)
    clipping_growth = float(candidate_clipped.mean() - source_clipped.mean())
    confidence = float(prediction["target_confidence"])
    violations: list[str] = []
    if neutral_before is None or neutral_after is None or neutral_after > neutral_before - max(0.35, neutral_before * 0.18):
        violations.append("NEUTRAL_TARGET_NOT_APPROACHED")
    if neutral_after is not None and neutral_after > 3.2:
        violations.append("NEW_OR_RESIDUAL_GLOBAL_CAST")
    if skin_before is not None and skin_after is not None:
        allowed = skin_before - 0.25 if skin_before > 1.0 else skin_before + 0.8
        if skin_after > allowed:
            violations.append("SKIN_TARGET_NOT_APPROACHED")
    if protected_mean > 4.5 + 2.0 * confidence or protected_p95 > 13.0:
        violations.append("PROTECTED_COLOR_DRIFT")
    if confidence < 0.58:
        violations.append("TARGET_UNCERTAINTY_HIGH")
    if highlight_delta > 0.004:
        violations.append("HIGHLIGHT_LOSS")
    if black_delta > 2.0:
        violations.append("BLACK_POINT_DRIFT")
    if luma_delta > 2.5:
        violations.append("LUMINANCE_DRIFT")
    if clipping_growth > 0.006:
        violations.append("CLIPPING_GROWTH")
    if noise["status"] == "RISK":
        violations.append("NOISE_AMPLIFICATION")
    if halo["status"] == "RISK":
        violations.append("HALO_OR_OVERSHOOT")
    return {
        "status": "PASS" if not violations else "RISK",
        "violations": violations,
        "target_metrics": {
            "neutral_distance_before": round(float(neutral_before), 4) if neutral_before is not None else None,
            "neutral_distance_after": round(float(neutral_after), 4) if neutral_after is not None else None,
            "skin_distance_before": round(float(skin_before), 4) if skin_before is not None else None,
            "skin_distance_after": round(float(skin_after), 4) if skin_after is not None else None,
            "protected_delta_e_mean": round(protected_mean, 4),
            "protected_delta_e_p95": round(protected_p95, 4),
            "target_confidence": round(confidence, 4),
        },
        "non_color_metrics": {
            "black_point_delta": round(black_delta, 4),
            "highlight_ratio_delta": round(highlight_delta, 6),
            "mean_luminance_delta": round(luma_delta, 4),
            "clipping_growth": round(clipping_growth, 6),
            "noise_review": noise,
            "halo_review": halo,
        },
    }


def run_global_recovery(
    source_rgb: np.ndarray,
    fallback_rgb: np.ndarray,
    analysis: dict[str, Any],
    faces: list[tuple[int, int, int, int]],
    strong_color_mask: np.ndarray,
    before_metrics: dict[str, float],
    focus_mask: np.ndarray,
    background_mask: np.ndarray,
    *,
    person_masks: Callable[..., tuple[np.ndarray, np.ndarray]],
    metrics_fn: Callable[..., dict[str, float]],
    noise_fn: Callable[[np.ndarray, np.ndarray], dict[str, Any]],
    halo_fn: Callable[[np.ndarray, np.ndarray], dict[str, Any]],
) -> tuple[np.ndarray, dict[str, Any]]:
    if not _global_eligible(analysis):
        return fallback_rgb.copy(), {
            "version": COLOR_CORE_V2_VERSION,
            "route": GLOBAL_ROUTE_NAME,
            "status": "NOT_APPLICABLE",
            "action": "KEEP_D04_RESULT",
            "runtime_ground_truth_used": False,
        }
    try:
        evidence = _global_evidence(source_rgb, faces, strong_color_mask, person_masks)
        targets, prediction = _global_targets(source_rgb, evidence)
        matrix, fit = _fit_global_mapping(source_rgb, evidence, targets)
        raw = _apply_global_mapping(source_rgb, matrix, 1.0)
        attempts: list[dict[str, Any]] = []
        for strength in (1.0, 0.82, 0.65, 0.50):
            candidate = raw if strength == 1.0 else _apply_global_mapping(source_rgb, matrix, strength)
            review = _review_global(
                source_rgb, candidate, evidence, prediction, before_metrics, focus_mask, background_mask,
                metrics_fn, noise_fn, halo_fn,
            )
            attempts.append({"strength": strength, "review": review})
            if review["status"] == "PASS":
                return candidate, {
                    "version": COLOR_CORE_V2_VERSION,
                    "route": GLOBAL_ROUTE_NAME,
                    "status": "PASS",
                    "action": "ACCEPT_RAW" if strength == 1.0 else "REDUCE_STRENGTH",
                    "selected_strength": strength,
                    "strength_reduced": strength < 1.0,
                    "fallback": False,
                    "prediction": prediction,
                    "fit": fit,
                    "attempts": attempts,
                    "raw_candidate_changed": bool(not np.array_equal(source_rgb, raw)),
                    "runtime_ground_truth_used": False,
                }
        return fallback_rgb.copy(), {
            "version": COLOR_CORE_V2_VERSION,
            "route": GLOBAL_ROUTE_NAME,
            "status": "FALLBACK",
            "action": "FALLBACK_D04_RESULT",
            "selected_strength": 0.0,
            "strength_reduced": True,
            "fallback": True,
            "prediction": prediction,
            "fit": fit,
            "attempts": attempts,
            "raw_candidate_changed": bool(not np.array_equal(source_rgb, raw)),
            "runtime_ground_truth_used": False,
        }
    except (RuntimeError, ValueError, np.linalg.LinAlgError) as exc:
        return fallback_rgb.copy(), {
            "version": COLOR_CORE_V2_VERSION,
            "route": GLOBAL_ROUTE_NAME,
            "status": "FALLBACK",
            "action": "FALLBACK_D04_RESULT",
            "selected_strength": 0.0,
            "strength_reduced": True,
            "fallback": True,
            "reason": str(exc),
            "runtime_ground_truth_used": False,
        }


def _normalized_field(seed: np.ndarray, support: np.ndarray, sigma_ratio: float) -> np.ndarray:
    height, width = seed.shape
    low_width = max(48, int(round(width / 12.0)))
    low_height = max(36, int(round(height / 12.0)))
    low_seed = cv2.resize(seed.astype(np.float32), (low_width, low_height), interpolation=cv2.INTER_AREA)
    low_support = cv2.resize(support.astype(np.float32), (low_width, low_height), interpolation=cv2.INTER_AREA)
    sigma = max(1.2, min(low_width, low_height) * sigma_ratio)
    numerator = cv2.GaussianBlur(low_seed * low_support, (0, 0), sigmaX=sigma, sigmaY=sigma)
    denominator = cv2.GaussianBlur(low_support, (0, 0), sigmaX=sigma, sigmaY=sigma)
    low_field = numerator / np.maximum(denominator, 1e-4)
    low_field = cv2.bilateralFilter(low_field.astype(np.float32), 7, 0.12, 3.0)
    return np.clip(cv2.resize(low_field, (width, height), interpolation=cv2.INTER_CUBIC), 0.0, 1.0)


def _local_evidence(
    rgb: np.ndarray,
    faces: list[tuple[int, int, int, int]],
    field_sigma: float,
    person_masks: Callable[..., tuple[np.ndarray, np.ndarray]],
    color_features: Callable[..., tuple[np.ndarray, np.ndarray, dict[str, Any]]],
) -> dict[str, Any]:
    lab = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    hsv = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
    lightness = lab[..., 0]
    a_axis = lab[..., 1] - 128.0
    b_axis = lab[..., 2] - 128.0
    saturation = hsv[..., 1] / 255.0
    face_mask, person_mask = person_masks(rgb.shape[:2], faces)
    face_core = face_mask >= 0.55
    yy = np.indices(face_mask.shape)[0]
    torso_floor = min(y + h * 0.88 for _, y, _, h in faces)
    trusted_skin = (
        face_core & (lightness > 40.0) & (a_axis > 4.0) & (a_axis < 30.0)
        & (b_axis >= 4.0) & (b_axis < 30.0) & (saturation < 0.72)
    )
    polluted_skin = (
        face_core & (lightness > 35.0) & (a_axis > 2.0) & (a_axis < 38.0) & (b_axis < 2.0)
    )
    neutral_material = (
        (person_mask >= 0.20) & (yy > torso_floor) & (lightness > 122.0) & (lightness < 235.0)
        & (saturation < 0.40) & (a_axis > -8.0) & (a_axis < 18.0)
    )
    polluted_neutral = neutral_material & (b_axis < 3.0)
    trusted_neutral = neutral_material & (b_axis >= 1.0) & (b_axis <= 10.0) & (np.abs(a_axis) <= 8.0)
    if trusted_skin.any():
        warm_reference = trusted_skin & (b_axis >= np.percentile(b_axis[trusted_skin], 52))
        target_a = float(np.clip(np.median(a_axis[warm_reference]), 9.0, 18.0))
        target_b = float(np.clip(np.median(b_axis[warm_reference]), 10.0, 19.0))
    else:
        target_a, target_b = 14.0, 16.0
    face_need = np.clip((4.0 - b_axis) / 46.0, 0.0, 1.0)
    neutral_need = np.clip((3.0 - b_axis) / 24.0, 0.0, 1.0)
    skin_likelihood = (
        face_mask * np.clip((lightness - 30.0) / 34.0, 0.0, 1.0)
        * np.clip((a_axis - 3.0) / 7.0, 0.0, 1.0)
        * np.clip((42.0 - a_axis) / 12.0, 0.0, 1.0)
    )
    torso_gate = np.clip((yy.astype(np.float32) - float(torso_floor) + 12.0) / 28.0, 0.0, 1.0)
    neutral_likelihood = (
        person_mask * torso_gate * np.clip((lightness - 108.0) / 34.0, 0.0, 1.0)
        * np.clip((238.0 - lightness) / 24.0, 0.0, 1.0)
        * np.clip((0.44 - saturation) / 0.20, 0.0, 1.0)
        * np.clip((20.0 - np.abs(a_axis - 2.0)) / 16.0, 0.0, 1.0)
    )
    skin_likelihood *= b_axis < 4.0
    neutral_likelihood *= b_axis < 3.0
    face_seed = skin_likelihood * np.power(face_need, 0.48)
    neutral_seed = neutral_likelihood * np.power(neutral_need, 0.52)
    seed = np.maximum(face_seed, neutral_seed * 0.92)
    support = np.clip(
        skin_likelihood + face_mask * trusted_skin.astype(np.float32)
        + neutral_likelihood * 0.72 + person_mask * trusted_neutral.astype(np.float32) * 0.45,
        0.0, 1.0,
    )
    smooth_field = _normalized_field(seed, support, field_sigma)
    smooth_field = np.clip(np.maximum(smooth_field, seed * 0.74) * person_mask, 0.0, 1.0)
    strong_color_mask, screen_mask, _ = color_features(rgb)
    screen_region = (screen_mask >= 0.35) & (person_mask <= 0.08)
    protected_environment = person_mask <= 0.02
    trusted_ratio = float(trusted_skin.sum() / max(face_core.sum(), 1))
    polluted_ratio = float(polluted_skin.sum() / max(face_core.sum(), 1))
    neutral_ratio = float(polluted_neutral.sum() / max((person_mask >= 0.20).sum(), 1))
    confidence = float(np.clip(0.42 + 0.75 * trusted_ratio + 0.45 * polluted_ratio + 0.28 * neutral_ratio, 0.0, 1.0))
    return {
        "lab": lab,
        "face_mask": face_mask,
        "person_mask": person_mask,
        "face_core": face_core,
        "trusted_skin": trusted_skin,
        "polluted_skin": polluted_skin,
        "polluted_neutral": polluted_neutral,
        "skin_likelihood": skin_likelihood,
        "neutral_likelihood": neutral_likelihood,
        "protected_non_material": (
            (person_mask > 0.02) & (skin_likelihood < 0.025) & (neutral_likelihood < 0.025)
        ),
        "screen_region": screen_region,
        "protected_environment": protected_environment,
        "field": smooth_field,
        "face_need": face_need,
        "neutral_need": neutral_need,
        "target_skin_ab": np.array([target_a, target_b], dtype=np.float32),
        "target_neutral_ab": _TARGET_NEUTRAL_AB.copy(),
        "target_confidence": confidence,
    }


def _local_eligible(
    analysis: dict[str, Any],
    rgb: np.ndarray,
    faces: list[tuple[int, int, int, int]],
    person_masks: Callable[..., tuple[np.ndarray, np.ndarray]],
    color_features: Callable[..., tuple[np.ndarray, np.ndarray, dict[str, Any]]],
) -> tuple[bool, dict[str, Any]]:
    person = analysis.get("person") or {}
    key_color = analysis.get("key_color") or {}
    fact_gate = bool(
        analysis.get("processing_decision") == "LOCAL_REQUIRED"
        and analysis.get("cast_interpretation") == "strong_local_light"
        and analysis.get("strong_local_light")
        and not analysis.get("mixed_light")
        and person.get("local_light_contamination")
        and key_color.get("probable_product_or_screen_color") == "screen"
        and key_color.get("protect_strength") == "high"
        and "screen_color" in (analysis.get("protection_needs") or [])
    )
    if not fact_gate or not faces:
        return False, {"reason": "d01_multi_illuminant_screen_person_facts_not_satisfied", "fact_gate": fact_gate, "face_count": len(faces)}
    evidence = _local_evidence(rgb, faces, float(_LOCAL_ROUTE["field_sigma"]), person_masks, color_features)
    face_core = evidence["face_core"]
    required = max(96, int(face_core.sum() * 0.025))
    evidence_gate = bool(
        int(evidence["trusted_skin"].sum()) >= required
        and int(evidence["polluted_skin"].sum()) >= required
        and int(evidence["polluted_neutral"].sum()) >= 128
        and float(evidence["target_confidence"]) >= 0.62
    )
    return evidence_gate, {
        "reason": "trusted_local_skin_neutral_and_blue_field" if evidence_gate else "insufficient_local_color_field_evidence",
        "fact_gate": fact_gate,
        "evidence_gate": evidence_gate,
        "face_count": len(faces),
        "face_pixels": int(face_core.sum()),
        "trusted_skin_pixels": int(evidence["trusted_skin"].sum()),
        "polluted_skin_pixels": int(evidence["polluted_skin"].sum()),
        "polluted_neutral_pixels": int(evidence["polluted_neutral"].sum()),
        "target_confidence": round(float(evidence["target_confidence"]), 4),
        "target_uncertainty": round(1.0 - float(evidence["target_confidence"]), 4),
    }


def _fit_local_affine(
    rgb: np.ndarray,
    target_rgb: np.ndarray,
    target_weight: np.ndarray,
    identity_weight: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any]]:
    rng = np.random.default_rng(20260813)
    flat_rgb = rgb.reshape(-1, 3).astype(np.float32) / 255.0
    flat_target = target_rgb.reshape(-1, 3).astype(np.float32) / 255.0
    basis = _basis(flat_rgb)
    input_rows: list[np.ndarray] = []
    output_rows: list[np.ndarray] = []
    row_weights: list[np.ndarray] = []
    counts: dict[str, int] = {}
    for name, mask, desired, weight, limit in (
        ("target", target_weight, flat_target, 1.0, 14000),
        ("identity", identity_weight, flat_rgb, 0.55, 7000),
    ):
        indexes = np.flatnonzero(mask.reshape(-1) > 0.04)
        if len(indexes) > limit:
            indexes = rng.choice(indexes, limit, replace=False)
        counts[name] = int(len(indexes))
        if not len(indexes):
            continue
        input_rows.append(basis[indexes])
        output_rows.append(desired[indexes])
        row_weights.append((np.maximum(mask.reshape(-1)[indexes], 0.08) * weight).astype(np.float32))
    design = np.vstack(input_rows)
    desired = np.vstack(output_rows)
    weights = np.concatenate(row_weights)
    weighted_design = design * np.sqrt(weights)[:, None]
    weighted_desired = desired * np.sqrt(weights)[:, None]
    identity = np.zeros((4, 3), dtype=np.float32)
    identity[:3] = np.eye(3, dtype=np.float32)
    ridge = float(_LOCAL_ROUTE["ridge"] * len(design))
    regularizer = np.diag(np.array([1.0, 1.0, 1.0, 0.25], dtype=np.float32))
    matrix = np.linalg.solve(
        weighted_design.T @ weighted_design + ridge * regularizer,
        weighted_design.T @ weighted_desired + ridge * regularizer @ identity,
    )
    matrix[:3] = np.clip(matrix[:3], -0.24, 1.34)
    for channel in range(3):
        matrix[channel, channel] = np.clip(matrix[channel, channel], 0.68, 1.34)
    matrix[-1] = np.clip(matrix[-1], -0.09, 0.09)
    return matrix.astype(np.float32), {
        "basis": "full_cross_channel_affine",
        "coefficients": [[round(float(value), 6) for value in row] for row in matrix],
        "support_counts": counts,
        "condition_number": round(float(np.linalg.cond(weighted_design.T @ weighted_design + ridge * regularizer)), 4),
    }


def _apply_local_field(
    current_rgb: np.ndarray,
    faces: list[tuple[int, int, int, int]],
    scale: float,
    person_masks: Callable[..., tuple[np.ndarray, np.ndarray]],
    color_features: Callable[..., tuple[np.ndarray, np.ndarray, dict[str, Any]]],
) -> tuple[np.ndarray, dict[str, Any], dict[str, Any]]:
    evidence = _local_evidence(current_rgb, faces, float(_LOCAL_ROUTE["field_sigma"]), person_masks, color_features)
    lab = evidence["lab"]
    a_axis, b_axis = lab[..., 1] - 128.0, lab[..., 2] - 128.0
    target_skin = evidence["target_skin_ab"]
    target_neutral = evidence["target_neutral_ab"]
    field = evidence["field"]
    skin_gate = evidence["skin_likelihood"] * np.power(evidence["face_need"], 0.42)
    neutral_gate = evidence["neutral_likelihood"] * np.power(evidence["neutral_need"], 0.46)
    skin_write = np.clip(
        np.maximum(field * 0.90, np.power(np.clip(skin_gate, 0.0, 1.0), 0.72) * 0.82)
        * skin_gate * float(_LOCAL_ROUTE["skin_strength"]) * scale, 0.0, 1.0,
    )
    neutral_write = np.clip(
        np.maximum(field * 0.82, np.power(np.clip(neutral_gate, 0.0, 1.0), 0.72) * 0.86)
        * neutral_gate * float(_LOCAL_ROUTE["shirt_strength"]) * scale, 0.0, 1.0,
    )
    write = np.maximum(skin_write, neutral_write)
    _, screen_mask, _ = color_features(current_rgb)
    background_screen = screen_mask * (evidence["person_mask"] <= 0.08)
    write *= np.clip(1.0 - background_screen * 0.999, 0.0, 1.0)
    target_lab = lab.copy()
    skin_b_shift = np.clip(target_skin[1] - b_axis, 0.0, float(_LOCAL_ROUTE["skin_cap"]))
    skin_a_shift = np.clip(target_skin[0] - a_axis, -12.0, 12.0) * 0.48
    neutral_b_shift = np.clip(target_neutral[1] - b_axis, 0.0, float(_LOCAL_ROUTE["neutral_cap"]))
    neutral_a_shift = np.clip(target_neutral[0] - a_axis, -10.0, 10.0) * 0.82
    skin_select = skin_write > 0.0
    neutral_select = neutral_write > skin_write
    target_lab[..., 1] = np.clip(target_lab[..., 1] + skin_a_shift * skin_select + neutral_a_shift * neutral_select, 0.0, 255.0)
    target_lab[..., 2] = np.clip(target_lab[..., 2] + skin_b_shift * skin_select + neutral_b_shift * neutral_select, 0.0, 255.0)
    target_lab[..., 0] = lab[..., 0]
    target_rgb = cv2.cvtColor(target_lab.astype(np.uint8), cv2.COLOR_LAB2RGB)
    identity_weight = np.clip(
        evidence["protected_environment"].astype(np.float32)
        + evidence["screen_region"].astype(np.float32)
        + evidence["trusted_skin"].astype(np.float32), 0.0, 1.0,
    )
    matrix, fit = _fit_local_affine(current_rgb, target_rgb, write, identity_weight)
    mapped = _basis(current_rgb.reshape(-1, 3).astype(np.float32) / 255.0) @ matrix
    mapped_rgb = np.clip(np.rint(mapped.reshape(current_rgb.shape) * 255.0), 0.0, 255.0).astype(np.uint8)
    mapped_lab = cv2.cvtColor(mapped_rgb, cv2.COLOR_RGB2LAB)
    mapped_lab[..., 0] = lab[..., 0].astype(np.uint8)
    mapped_rgb = cv2.cvtColor(mapped_lab, cv2.COLOR_LAB2RGB)
    chromatic_target = np.clip(
        target_rgb.astype(np.float32) * (1.0 - float(_LOCAL_ROUTE["affine_mix"]))
        + mapped_rgb.astype(np.float32) * float(_LOCAL_ROUTE["affine_mix"]), 0.0, 255.0,
    )
    output = np.clip(
        current_rgb.astype(np.float32) * (1.0 - write[..., None]) + chromatic_target * write[..., None], 0.0, 255.0,
    ).astype(np.uint8)
    output[write <= 0.005] = current_rgb[write <= 0.005]
    output_lab = cv2.cvtColor(output, cv2.COLOR_RGB2LAB)
    output_lab[..., 0] = lab[..., 0].astype(np.uint8)
    output = cv2.cvtColor(output_lab, cv2.COLOR_LAB2RGB)
    output[write <= 0.005] = current_rgb[write <= 0.005]
    return output, {
        "mode": "edge_preserving_low_res_rgb_lab_local_chromatic_field",
        "faces_used": len(faces),
        "skin_target_ab": [round(float(v), 4) for v in target_skin],
        "neutral_target_ab": [round(float(v), 4) for v in target_neutral],
        "target_confidence": round(float(evidence["target_confidence"]), 4),
        "target_uncertainty": round(1.0 - float(evidence["target_confidence"]), 4),
        "field_nonzero_ratio": round(float((write > 0.01).mean()), 6),
        "field_mean": round(float(write.mean()), 6),
        "field_max": round(float(write.max()), 6),
        "skin_write_pixels": int((skin_write > 0.02).sum()),
        "neutral_write_pixels": int((neutral_write > 0.02).sum()),
        "luminance_preserved": True,
        "fit": fit,
        "runtime_ground_truth_used": False,
    }, {**evidence, "write": write, "skin_write": skin_write, "neutral_write": neutral_write}


def _median_ab(lab: np.ndarray, mask: np.ndarray) -> np.ndarray | None:
    if int(mask.sum()) < 48:
        return None
    return np.median(lab[..., 1:3][mask] - 128.0, axis=0)


def _distance(values: np.ndarray | None, target: np.ndarray) -> float | None:
    return None if values is None else float(np.linalg.norm(values - target))


def _review_local(
    current_rgb: np.ndarray,
    candidate_rgb: np.ndarray,
    evidence: dict[str, Any],
    noise_fn: Callable[[np.ndarray, np.ndarray], dict[str, Any]],
    halo_fn: Callable[[np.ndarray, np.ndarray], dict[str, Any]],
) -> dict[str, Any]:
    before_lab = cv2.cvtColor(current_rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    after_lab = cv2.cvtColor(candidate_rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    delta_rgb = np.abs(candidate_rgb.astype(np.float32) - current_rgb.astype(np.float32)).mean(axis=2)
    delta_e = np.linalg.norm(after_lab - before_lab, axis=2)
    skin_before = _distance(_median_ab(before_lab, evidence["polluted_skin"]), evidence["target_skin_ab"])
    skin_after = _distance(_median_ab(after_lab, evidence["polluted_skin"]), evidence["target_skin_ab"])
    neutral_before = _distance(_median_ab(before_lab, evidence["polluted_neutral"]), evidence["target_neutral_ab"])
    neutral_after = _distance(_median_ab(after_lab, evidence["polluted_neutral"]), evidence["target_neutral_ab"])
    trusted, screen = evidence["trusted_skin"], evidence["screen_region"]
    outside, non_material = evidence["protected_environment"], evidence["protected_non_material"]
    transition = (evidence["person_mask"] > 0.01) & (evidence["person_mask"] < 0.28)
    delta_gradient = np.maximum(
        np.abs(cv2.Sobel(delta_rgb, cv2.CV_32F, 1, 0, ksize=3)) / 4.0,
        np.abs(cv2.Sobel(delta_rgb, cv2.CV_32F, 0, 1, ksize=3)) / 4.0,
    )
    field_gradient = np.maximum(
        np.abs(cv2.Sobel(evidence["field"].astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)) / 4.0,
        np.abs(cv2.Sobel(evidence["field"].astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)) / 4.0,
    )
    before_l, after_l = before_lab[..., 0], after_lab[..., 0]
    before_b, after_b = before_lab[..., 2] - 128.0, after_lab[..., 2] - 128.0
    source_clipped = ((current_rgb <= 1) | (current_rgb >= 254)).any(axis=2)
    candidate_clipped = ((candidate_rgb <= 1) | (candidate_rgb >= 254)).any(axis=2)

    def mean(values: np.ndarray, mask: np.ndarray) -> float:
        return float(values[mask].mean()) if mask.any() else 0.0

    def percentile(values: np.ndarray, mask: np.ndarray, value: float) -> float:
        return float(np.percentile(values[mask], value)) if mask.any() else 0.0

    noise, halo = noise_fn(current_rgb, candidate_rgb), halo_fn(current_rgb, candidate_rgb)
    metrics: dict[str, Any] = {
        "polluted_skin_target_distance_before": skin_before,
        "polluted_skin_target_distance_after": skin_after,
        "polluted_neutral_target_distance_before": neutral_before,
        "polluted_neutral_target_distance_after": neutral_after,
        "polluted_skin_b_median_before": float(np.median(before_b[evidence["polluted_skin"]])),
        "polluted_skin_b_median_after": float(np.median(after_b[evidence["polluted_skin"]])),
        "polluted_skin_b_p10_after": float(np.percentile(after_b[evidence["polluted_skin"]], 10)),
        "polluted_neutral_b_median_after": float(np.median(after_b[evidence["polluted_neutral"]])),
        "trusted_skin_delta_e_mean": mean(delta_e, trusted),
        "trusted_skin_delta_e_p95": percentile(delta_e, trusted, 95),
        "screen_mae": mean(delta_rgb, screen),
        "screen_p99": percentile(delta_rgb, screen, 99),
        "outside_person_mae": mean(delta_rgb, outside),
        "outside_person_p99": percentile(delta_rgb, outside, 99),
        "protected_non_material_mae": mean(delta_rgb, non_material),
        "protected_non_material_p99": percentile(delta_rgb, non_material, 99),
        "transition_delta_gradient_p99": percentile(delta_gradient, transition, 99),
        "field_gradient_p99": percentile(field_gradient, evidence["person_mask"] > 0.02, 99),
        "luminance_mae": float(np.abs(after_l - before_l).mean()),
        "clipping_growth": float(candidate_clipped.mean() - source_clipped.mean()),
        "noise_review": noise,
        "halo_review": halo,
    }
    violations: list[str] = []
    if skin_before is None or skin_after is None or skin_after > skin_before - max(3.5, skin_before * 0.22):
        violations.append("POLLUTED_SKIN_TARGET_NOT_APPROACHED")
    if neutral_before is None or neutral_after is None or neutral_after > neutral_before - max(1.5, neutral_before * 0.18):
        violations.append("POLLUTED_NEUTRAL_TARGET_NOT_APPROACHED")
    if metrics["polluted_skin_b_median_after"] > 4.0 or metrics["polluted_skin_b_p10_after"] > -4.0:
        violations.append("LOCAL_ENVIRONMENT_RELATION_OVERCORRECTED")
    if metrics["polluted_neutral_b_median_after"] > 3.5:
        violations.append("LOCAL_NEUTRAL_OVERCORRECTED")
    if metrics["trusted_skin_delta_e_mean"] > 0.85 or metrics["trusted_skin_delta_e_p95"] > 2.5:
        violations.append("UNPOLLUTED_SKIN_DRIFT")
    if metrics["screen_mae"] > 0.10 or metrics["screen_p99"] > 0.75:
        violations.append("LED_SCREEN_DRIFT")
    if metrics["outside_person_mae"] > 0.05 or metrics["outside_person_p99"] > 0.50:
        violations.append("ENVIRONMENT_COLOR_DRIFT")
    if metrics["protected_non_material_mae"] > 0.08 or metrics["protected_non_material_p99"] > 0.75:
        violations.append("NON_MATERIAL_LOCAL_DRIFT")
    if metrics["transition_delta_gradient_p99"] > 4.0 or metrics["field_gradient_p99"] > 0.18:
        violations.append("LOCAL_BLEND_BOUNDARY_RISK")
    if metrics["luminance_mae"] > 0.75:
        violations.append("LUMINANCE_DRIFT")
    if metrics["clipping_growth"] > 0.004:
        violations.append("CLIPPING_GROWTH")
    if noise["status"] == "RISK":
        violations.append("NOISE_AMPLIFICATION")
    if halo["status"] == "RISK":
        violations.append("HALO_OR_OVERSHOOT")
    return {
        "status": "PASS" if not violations else "RISK",
        "violations": violations,
        "metrics": {key: round(float(value), 6) if isinstance(value, (float, np.floating)) else value for key, value in metrics.items()},
    }


def run_local_recovery(
    current_rgb: np.ndarray,
    analysis: dict[str, Any],
    faces: list[tuple[int, int, int, int]],
    *,
    person_masks: Callable[..., tuple[np.ndarray, np.ndarray]],
    color_features: Callable[..., tuple[np.ndarray, np.ndarray, dict[str, Any]]],
    noise_fn: Callable[[np.ndarray, np.ndarray], dict[str, Any]],
    halo_fn: Callable[[np.ndarray, np.ndarray], dict[str, Any]],
) -> tuple[np.ndarray, dict[str, Any]]:
    try:
        eligible, trigger = _local_eligible(analysis, current_rgb, faces, person_masks, color_features)
        if not eligible:
            return current_rgb.copy(), {
                "version": COLOR_CORE_V2_VERSION,
                "route": LOCAL_ROUTE_NAME,
                "status": "NOT_APPLICABLE",
                "action": "KEEP_D03_RESULT",
                "trigger": trigger,
                "runtime_ground_truth_used": False,
            }
        raw, execution, raw_evidence = _apply_local_field(current_rgb, faces, 1.0, person_masks, color_features)
        attempts: list[dict[str, Any]] = []
        for strength in (1.0, 0.82, 0.65, 0.50):
            if strength == 1.0:
                candidate, evidence = raw, raw_evidence
            else:
                candidate, _, evidence = _apply_local_field(current_rgb, faces, strength, person_masks, color_features)
            review = _review_local(current_rgb, candidate, evidence, noise_fn, halo_fn)
            attempts.append({"strength": strength, "review": review})
            if review["status"] == "PASS":
                return candidate, {
                    "version": COLOR_CORE_V2_VERSION,
                    "route": LOCAL_ROUTE_NAME,
                    "status": "PASS",
                    "action": "ACCEPT_RAW" if strength == 1.0 else "REDUCE_STRENGTH",
                    "selected_strength": strength,
                    "strength_reduced": strength < 1.0,
                    "fallback": False,
                    "trigger": trigger,
                    "execution": execution,
                    "attempts": attempts,
                    "raw_candidate_changed": bool(not np.array_equal(current_rgb, raw)),
                    "runtime_ground_truth_used": False,
                }
        return current_rgb.copy(), {
            "version": COLOR_CORE_V2_VERSION,
            "route": LOCAL_ROUTE_NAME,
            "status": "FALLBACK",
            "action": "FALLBACK_D03_RESULT",
            "selected_strength": 0.0,
            "strength_reduced": True,
            "fallback": True,
            "trigger": trigger,
            "execution": execution,
            "attempts": attempts,
            "raw_candidate_changed": bool(not np.array_equal(current_rgb, raw)),
            "runtime_ground_truth_used": False,
        }
    except (RuntimeError, ValueError, np.linalg.LinAlgError) as exc:
        return current_rgb.copy(), {
            "version": COLOR_CORE_V2_VERSION,
            "route": LOCAL_ROUTE_NAME,
            "status": "FALLBACK",
            "action": "FALLBACK_D03_RESULT",
            "selected_strength": 0.0,
            "strength_reduced": True,
            "fallback": True,
            "reason": str(exc),
            "runtime_ground_truth_used": False,
        }
