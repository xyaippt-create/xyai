from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def _resize_reference(reference: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    if reference.shape[:2] == candidate.shape[:2]:
        return reference
    return cv2.resize(reference, (candidate.shape[1], candidate.shape[0]), interpolation=cv2.INTER_CUBIC)


def _cast_direction(a_offset: float, b_offset: float) -> str:
    if abs(a_offset) >= abs(b_offset):
        return "magenta" if a_offset > 0 else "green"
    return "yellow" if b_offset > 0 else "blue"


def phase5_color_correction_policy(
    reference: np.ndarray,
    candidate: np.ndarray,
    *,
    enabled: bool = False,
    image_type: str = "unknown",
    has_alpha: bool = False,
    text_density: float = 0.0,
) -> dict[str, Any]:
    ref = _resize_reference(reference, candidate)
    hsv = cv2.cvtColor(ref, cv2.COLOR_BGR2HSV).astype("float32")
    lab = cv2.cvtColor(ref, cv2.COLOR_BGR2LAB).astype("float32")
    sat = hsv[:, :, 1] / 255.0
    value = hsv[:, :, 2] / 255.0
    neutral = (sat < 0.32) & (value > 0.22) & (value < 0.88)
    neutral_confidence = float(np.mean(neutral))
    high_sat_ratio = float(np.mean(sat > 0.62))
    brand_or_layout_type = image_type in {"text_poster", "ppt_page"} or (
        image_type == "product_kv" and (high_sat_ratio > 0.035 or text_density > 0.015)
    )
    brand_color_risk = bool(high_sat_ratio > 0.10 or brand_or_layout_type or text_density > 0.05)

    if neutral_confidence > 0:
        a_offset = float(np.mean(lab[:, :, 1][neutral]) - 128.0)
        b_offset = float(np.mean(lab[:, :, 2][neutral]) - 128.0)
    else:
        a_offset = 0.0
        b_offset = 0.0
    cast_strength = float(np.sqrt(a_offset * a_offset + b_offset * b_offset))
    direction = _cast_direction(a_offset, b_offset) if cast_strength >= 1.4 else "none"

    skip_reason = ""
    correction_strength = 0.0
    active = False
    if not enabled:
        skip_reason = "disabled_by_user"
    elif has_alpha:
        skip_reason = "alpha_protected"
    elif brand_color_risk:
        skip_reason = "brand_or_text_color_protected"
    elif neutral_confidence < 0.035:
        skip_reason = "low_neutral_confidence"
    elif cast_strength < 1.8:
        skip_reason = "no_reliable_cast"
    else:
        active = True
        correction_strength = float(np.clip(cast_strength / 18.0, 0.035, 0.16))

    return {
        "phase5_color_correction_enabled": bool(enabled),
        "phase5_cast_detected": bool(cast_strength >= 1.8 and neutral_confidence >= 0.035),
        "phase5_cast_direction": direction,
        "phase5_cast_strength": round(cast_strength, 6),
        "phase5_correction_strength": round(correction_strength, 6),
        "phase5_correction_skip_reason": "" if active else skip_reason,
        "neutral_region_confidence": round(neutral_confidence, 6),
        "global_cast_direction": direction,
        "global_cast_strength": round(cast_strength, 6),
        "skin_region_confidence": 0.0,
        "brand_color_risk": brand_color_risk,
        "highlight_neutrality": round(float(np.mean((sat < 0.12) & (value > 0.82))), 6),
        "shadow_cast": round(float(np.mean((sat > 0.24) & (value < 0.20))), 6),
        "phase5_correction_active": active,
    }


def apply_phase5_single_image_color_correction(
    reference: np.ndarray,
    candidate: np.ndarray,
    policy: dict[str, Any],
) -> np.ndarray:
    if not policy.get("phase5_correction_active"):
        return candidate
    ref = _resize_reference(reference, candidate)
    ref_lab = cv2.cvtColor(ref, cv2.COLOR_BGR2LAB).astype("float32")
    out_lab = cv2.cvtColor(candidate, cv2.COLOR_BGR2LAB).astype("float32")
    hsv = cv2.cvtColor(ref, cv2.COLOR_BGR2HSV).astype("float32")
    sat = hsv[:, :, 1] / 255.0
    value = hsv[:, :, 2] / 255.0
    neutral = (sat < 0.32) & (value > 0.22) & (value < 0.88)
    if not np.any(neutral):
        return candidate

    a_offset = float(np.mean(ref_lab[:, :, 1][neutral]) - 128.0)
    b_offset = float(np.mean(ref_lab[:, :, 2][neutral]) - 128.0)
    strength = float(policy.get("phase5_correction_strength") or 0.0)
    high_sat_guard = np.clip((sat - 0.42) / 0.22, 0.0, 1.0)
    highlight_guard = np.clip((0.96 - value) / 0.18, 0.0, 1.0)
    shadow_guard = np.clip((value - 0.06) / 0.18, 0.0, 1.0)
    blend = np.clip((1.0 - high_sat_guard * 0.88) * highlight_guard * shadow_guard * strength, 0.0, 0.16)
    out_lab[:, :, 1] = out_lab[:, :, 1] - a_offset * blend
    out_lab[:, :, 2] = out_lab[:, :, 2] - b_offset * blend
    return cv2.cvtColor(np.clip(out_lab, 0, 255).astype("uint8"), cv2.COLOR_LAB2BGR)
