from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def phase3_edge_policy(
    profile: str,
    mode: str,
    image_type: str,
    has_alpha: bool = False,
    type_features: dict[str, Any] | None = None,
    text_density: float = 0.0,
) -> dict[str, Any]:
    features = type_features or {}
    texture_density = float(features.get("texture_density") or 0.0)
    edge_density = float(features.get("edge_density") or 0.0)
    dark_ratio = float(features.get("dark_ratio") or 0.0)
    low_saturation_ratio = float(features.get("low_saturation_ratio") or 0.0)
    text_edge_risk = bool(mode == "text_safe" or image_type in {"text_poster", "ppt_page"} or text_density >= 0.018)
    alpha_edge_risk = bool(has_alpha)
    gradient_risk = bool(texture_density < 0.003 and edge_density < 0.003)
    fine_line_risk = bool(edge_density >= 0.10 and low_saturation_ratio > 0.65)
    edge_contrast_risk = bool(edge_density >= 0.008 or dark_ratio >= 0.12)
    halo_risk = bool(edge_contrast_risk or alpha_edge_risk)
    ringing_risk = bool(texture_density >= 0.075 or fine_line_risk)

    strength = 0.05
    skip_reason = "eligible"
    if profile == "preview_light":
        strength = 0.0
        skip_reason = "preview_light_profile"
    elif text_edge_risk:
        strength = 0.0
        skip_reason = "text_edge_protected"
    elif gradient_risk:
        strength = 0.0
        skip_reason = "gradient_protected"
    elif fine_line_risk:
        strength = 0.0
        skip_reason = "fine_line_protected"
    elif not (edge_contrast_risk or alpha_edge_risk or ringing_risk):
        strength = 0.0
        skip_reason = "no_edge_risk"
    else:
        if image_type == "portrait":
            strength = 0.035
            skip_reason = "portrait_skin_safe"
        elif alpha_edge_risk:
            strength = 0.025
            skip_reason = "alpha_edge_safe"
        elif ringing_risk:
            strength = 0.04
            skip_reason = "ringing_guard"
        elif image_type in {"architecture", "product_kv"} or edge_contrast_risk:
            strength = 0.045

    strength = float(np.clip(strength, 0.0, 0.12))
    return {
        "phase3_edge_strength": round(strength, 4),
        "phase3_edge_skip_reason": skip_reason,
        "edge_contrast_risk": edge_contrast_risk,
        "halo_risk": halo_risk,
        "ringing_risk": ringing_risk,
        "alpha_edge_risk": alpha_edge_risk,
        "text_edge_risk": text_edge_risk,
    }


def phase3_edge_halo_control(
    before_edge: np.ndarray,
    after_edge: np.ndarray,
    policy: dict[str, Any] | None,
) -> np.ndarray:
    policy = policy or {}
    strength = float(policy.get("phase3_edge_strength") or 0.0)
    if strength <= 0:
        return after_edge

    lab_before = cv2.cvtColor(before_edge, cv2.COLOR_BGR2LAB).astype("float32")
    lab_after = cv2.cvtColor(after_edge, cv2.COLOR_BGR2LAB).astype("float32")
    l_before = lab_before[:, :, 0]
    l_after = lab_after[:, :, 0]

    local_min = cv2.erode(l_before, np.ones((3, 3), dtype=np.uint8))
    local_max = cv2.dilate(l_before, np.ones((3, 3), dtype=np.uint8))
    margin = 3.2 if policy.get("alpha_edge_risk") else 4.6
    clipped = np.clip(l_after, local_min - margin, local_max + margin)

    gray = cv2.cvtColor(before_edge, cv2.COLOR_BGR2GRAY)
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad = cv2.magnitude(grad_x, grad_y)
    edge_mask = np.clip((grad - 12.0) / 42.0, 0.0, 1.0)
    edge_mask = cv2.GaussianBlur(edge_mask, (0, 0), 0.85)

    overshoot = np.maximum(l_after - (local_max + margin), (local_min - margin) - l_after)
    overshoot_mask = np.clip(overshoot / 10.0, 0.0, 1.0)
    blend = np.clip(edge_mask * (0.35 + overshoot_mask * 0.65) * strength, 0.0, 0.16)

    l_controlled = l_after * (1.0 - blend) + clipped * blend
    if policy.get("ringing_risk"):
        smooth = cv2.GaussianBlur(l_controlled, (0, 0), 0.55)
        ring_detail = np.abs(l_after - cv2.GaussianBlur(l_after, (0, 0), 0.75))
        ring_mask = np.clip((ring_detail - 9.0) / 18.0, 0.0, 1.0) * edge_mask
        ring_blend = np.clip(ring_mask * strength * 0.22, 0.0, 0.06)
        l_controlled = l_controlled * (1.0 - ring_blend) + smooth * ring_blend

    lab_after[:, :, 0] = np.clip(l_controlled, 0, 255)
    return cv2.cvtColor(lab_after.astype("uint8"), cv2.COLOR_LAB2BGR)
