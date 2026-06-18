from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from engine.algorithms.color_fidelity import lock_color_to_reference


def _resize_reference(reference: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    if reference.shape[:2] == candidate.shape[:2]:
        return reference
    return cv2.resize(reference, (candidate.shape[1], candidate.shape[0]), interpolation=cv2.INTER_CUBIC)


def _delta_e(reference: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    ref = _resize_reference(reference, candidate)
    ref_lab = cv2.cvtColor(ref, cv2.COLOR_BGR2LAB).astype("float32")
    out_lab = cv2.cvtColor(candidate, cv2.COLOR_BGR2LAB).astype("float32")
    return np.linalg.norm(ref_lab - out_lab, axis=2)


def _hue_distance(ref_hue: np.ndarray, out_hue: np.ndarray) -> np.ndarray:
    diff = np.abs(ref_hue.astype("float32") - out_hue.astype("float32"))
    return np.minimum(diff, 180.0 - diff) * 2.0


def _mask_mean(values: np.ndarray, mask: np.ndarray) -> float:
    if mask is None or not np.any(mask):
        return 0.0
    return float(np.mean(values[mask]))


def phase5_color_metrics(reference: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
    ref = _resize_reference(reference, candidate)
    delta = _delta_e(ref, candidate)
    ref_hsv = cv2.cvtColor(ref, cv2.COLOR_BGR2HSV).astype("float32")
    out_hsv = cv2.cvtColor(candidate, cv2.COLOR_BGR2HSV).astype("float32")
    ref_sat = ref_hsv[:, :, 1] / 255.0
    out_sat = out_hsv[:, :, 1] / 255.0
    ref_val = ref_hsv[:, :, 2] / 255.0
    hue_delta = _hue_distance(ref_hsv[:, :, 0], out_hsv[:, :, 0])

    red_mask = ((ref_hsv[:, :, 0] <= 8) | (ref_hsv[:, :, 0] >= 170)) & (ref_sat > 0.42) & (ref_val > 0.16)
    skin_mask = (
        (ref_hsv[:, :, 0] >= 2)
        & (ref_hsv[:, :, 0] <= 24)
        & (ref_sat >= 0.10)
        & (ref_sat <= 0.58)
        & (ref_val >= 0.28)
        & (ref_val <= 0.96)
    )
    highlight_mask = (ref_val > 0.82) & (ref_sat > 0.05)
    shadow_mask = (ref_val < 0.22) & (ref_sat > 0.05)

    return {
        "mean_delta_e": round(float(np.mean(delta)), 6),
        "p95_delta_e": round(float(np.percentile(delta, 95)), 6),
        "saturation_delta": round(float(np.mean(out_sat) - np.mean(ref_sat)), 6),
        "high_saturation_pixel_ratio_delta": round(
            float(np.mean(out_sat > 0.68) - np.mean(ref_sat > 0.68)),
            6,
        ),
        "mean_hue_delta": round(float(np.mean(hue_delta)), 6),
        "skin_tone_delta": round(_mask_mean(delta, skin_mask), 6),
        "brand_color_delta": round(_mask_mean(delta, red_mask), 6),
        "highlight_color_delta": round(_mask_mean(delta, highlight_mask), 6),
        "shadow_color_delta": round(_mask_mean(delta, shadow_mask), 6),
    }


def _clamp_saturation(reference: np.ndarray, candidate: np.ndarray, margin: float = 0.008) -> np.ndarray:
    ref = _resize_reference(reference, candidate)
    ref_hsv = cv2.cvtColor(ref, cv2.COLOR_BGR2HSV).astype("float32")
    out_hsv = cv2.cvtColor(candidate, cv2.COLOR_BGR2HSV).astype("float32")
    ref_sat = ref_hsv[:, :, 1] / 255.0
    out_sat = out_hsv[:, :, 1] / 255.0
    sat_limit = np.clip(ref_sat + margin, 0.0, 1.0)
    over = out_sat > sat_limit
    if np.any(over):
        out_hsv[:, :, 1] = np.where(over, sat_limit * 255.0, out_hsv[:, :, 1])
    return cv2.cvtColor(np.clip(out_hsv, 0, 255).astype("uint8"), cv2.COLOR_HSV2BGR)


def _drift_reasons(metrics: dict[str, float], image_type: str, correction_enabled: bool) -> list[str]:
    reasons: list[str] = []
    sat_limit = 0.010 if not correction_enabled else 0.014
    high_sat_limit = 0.014 if not correction_enabled else 0.018
    p95_limit = 4.2 if image_type in {"text_poster", "product_kv"} else 3.6
    if abs(float(metrics.get("saturation_delta") or 0.0)) > sat_limit:
        reasons.append(f"saturation_delta={metrics['saturation_delta']}")
    if abs(float(metrics.get("high_saturation_pixel_ratio_delta") or 0.0)) > high_sat_limit:
        reasons.append(f"high_saturation_pixel_ratio_delta={metrics['high_saturation_pixel_ratio_delta']}")
    if float(metrics.get("p95_delta_e") or 0.0) > p95_limit:
        reasons.append(f"p95_delta_e={metrics['p95_delta_e']}")
    if float(metrics.get("skin_tone_delta") or 0.0) > 3.0:
        reasons.append(f"skin_tone_delta={metrics['skin_tone_delta']}")
    if float(metrics.get("brand_color_delta") or 0.0) > 2.8:
        reasons.append(f"brand_color_delta={metrics['brand_color_delta']}")
    if float(metrics.get("highlight_color_delta") or 0.0) > 3.4:
        reasons.append(f"highlight_color_delta={metrics['highlight_color_delta']}")
    if float(metrics.get("shadow_color_delta") or 0.0) > 3.4:
        reasons.append(f"shadow_color_delta={metrics['shadow_color_delta']}")
    return reasons


def phase5_default_color_stability(
    reference: np.ndarray,
    candidate: np.ndarray,
    *,
    image_type: str = "unknown",
    enabled: bool = True,
    color_correction_enabled: bool = False,
) -> tuple[np.ndarray, dict[str, Any]]:
    before = phase5_color_metrics(reference, candidate)
    policy: dict[str, Any] = {
        "phase5_color_stability_active": bool(enabled),
        "phase5_color_lock_mode": "disabled" if not enabled else "monitor",
        "phase5_color_drift_detected": False,
        "phase5_color_fallback_triggered": False,
        "phase5_color_fallback_reason": "",
        "phase5_metrics_before": before,
        "phase5_metrics_after": before,
    }
    if not enabled:
        return candidate, policy

    reasons = _drift_reasons(before, image_type, color_correction_enabled)
    if not reasons:
        policy["phase5_color_lock_mode"] = "monitor_pass"
        return candidate, policy

    if any(reason.startswith(("saturation_delta=", "high_saturation_pixel_ratio_delta=")) for reason in reasons):
        locked = _clamp_saturation(reference, candidate, margin=0.006)
        lock_mode = "saturation_guard"
    else:
        locked = lock_color_to_reference(reference, candidate, chroma_strength=1.0, luma_strength=0.0)
        locked = _clamp_saturation(reference, locked, margin=0.006)
        lock_mode = "chroma_saturation_guard"
    after = phase5_color_metrics(reference, locked)
    if (
        float(after.get("p95_delta_e") or 0.0) > float(before.get("p95_delta_e") or 0.0) + 0.5
        or float(after.get("mean_delta_e") or 0.0) > float(before.get("mean_delta_e") or 0.0) + 0.35
    ):
        policy.update(
            {
                "phase5_color_lock_mode": "delta_e_guard_preserve_phase4",
                "phase5_color_drift_detected": True,
                "phase5_color_fallback_triggered": True,
                "phase5_color_fallback_reason": "delta_e_guard",
                "phase5_metrics_after": before,
            }
        )
        return candidate, policy
    policy.update(
        {
            "phase5_color_lock_mode": lock_mode,
            "phase5_color_drift_detected": True,
            "phase5_color_fallback_triggered": False,
            "phase5_color_fallback_reason": ";".join(reasons),
            "phase5_metrics_after": after,
        }
    )
    return locked, policy
