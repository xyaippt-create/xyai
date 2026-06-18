from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from engine.algorithms.color_fidelity import lock_color_to_reference
from engine.algorithms.text_clarity import detect_text_like_regions


def phase4_quality_probes(image: np.ndarray) -> dict[str, float]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype("float32")
    height, width = gray.shape[:2]
    if height < 2 or width < 2:
        return {
            "compression_risk": 0.0,
            "shadow_dirt_risk": 0.0,
            "local_contrast": 0.0,
            "blur_risk": 1.0,
        }

    vertical = np.abs(gray[:, 1:] - gray[:, :-1])
    horizontal = np.abs(gray[1:, :] - gray[:-1, :])
    v_boundary = vertical[:, 7::8]
    v_inner = vertical[:, 3::8]
    h_boundary = horizontal[7::8, :]
    h_inner = horizontal[3::8, :]
    boundary = float(np.mean(v_boundary)) + float(np.mean(h_boundary))
    inner = float(np.mean(v_inner)) + float(np.mean(h_inner))
    compression_risk = float(np.clip((boundary - inner * 1.08) / 10.0, 0.0, 1.0))

    shadow = gray < 76.0
    if np.any(shadow):
        shadow_std = float(np.std(gray[shadow]))
        shadow_ratio = float(np.mean(shadow))
        shadow_dirt_risk = float(np.clip(shadow_ratio * 1.25 + shadow_std / 95.0, 0.0, 1.0))
    else:
        shadow_dirt_risk = 0.0

    mean = cv2.GaussianBlur(gray, (0, 0), 2.0)
    mean_sq = cv2.GaussianBlur(gray * gray, (0, 0), 2.0)
    local_std = np.sqrt(np.maximum(mean_sq - mean * mean, 0.0))
    local_contrast = float(np.clip(float(np.mean(local_std)) / 22.0, 0.0, 1.0))

    lap_var = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    blur_risk = float(np.clip((130.0 - lap_var) / 130.0, 0.0, 1.0))
    return {
        "compression_risk": round(compression_risk, 6),
        "shadow_dirt_risk": round(shadow_dirt_risk, 6),
        "local_contrast": round(local_contrast, 6),
        "blur_risk": round(blur_risk, 6),
    }


def phase4_low_quality_policy(
    profile: str,
    mode: str,
    image_type: str,
    has_alpha: bool = False,
    type_features: dict[str, Any] | None = None,
    text_density: float = 0.0,
    input_width: int = 0,
    input_height: int = 0,
    input_size_bytes: int = 0,
    input_suffix: str = "",
    before_probes: dict[str, float] | None = None,
) -> dict[str, Any]:
    features = type_features or {}
    probes = before_probes or {}
    texture_density = float(features.get("texture_density") or 0.0)
    edge_density = float(features.get("edge_density") or 0.0)
    low_saturation_ratio = float(features.get("low_saturation_ratio") or 0.0)
    compression_risk = float(probes.get("compression_risk") or 0.0)
    shadow_dirt_risk = float(probes.get("shadow_dirt_risk") or 0.0)
    local_contrast = float(probes.get("local_contrast") or 0.0)
    blur_risk = float(probes.get("blur_risk") or 0.0)

    min_side = min(int(input_width or 0), int(input_height or 0))
    low_resolution = min_side > 0 and min_side < 420
    jpeg_like = input_suffix.lower() in {".jpg", ".jpeg"}
    low_contrast = local_contrast < 0.34
    soft_focus = blur_risk > 0.18
    dirty_shadow = shadow_dirt_risk > 0.18
    jpeg_compression = jpeg_like and (compression_risk > 0.018 or input_size_bytes < max(1, input_width * input_height * 0.18))

    text_risk = bool(mode == "text_safe" or image_type in {"text_poster", "ppt_page"} or text_density >= 0.018)
    gradient_risk = bool(texture_density < 0.003 and edge_density < 0.003)
    fine_line_risk = bool(edge_density >= 0.10 and low_saturation_ratio > 0.65)
    high_chroma_brand_risk = bool(low_saturation_ratio < 0.08 and edge_density < 0.025 and texture_density < 0.045)
    brand_kv_risk = bool(
        (image_type == "product_kv" and not (low_resolution or jpeg_compression or dirty_shadow or soft_focus))
        or high_chroma_brand_risk
    )
    alpha_risk = bool(has_alpha)

    reasons: list[str] = []
    if low_resolution:
        reasons.append("low_resolution")
    if jpeg_compression:
        reasons.append("jpeg_compression")
    if soft_focus:
        reasons.append("soft_focus")
    if low_contrast:
        reasons.append("low_contrast")
    if dirty_shadow:
        reasons.append("dirty_shadow")

    active = bool(reasons)
    low_contrast_only = reasons == ["low_contrast"]
    skip_reason = "eligible"
    if profile == "preview_light":
        active = False
        skip_reason = "preview_light_profile"
    elif text_risk:
        active = False
        skip_reason = "text_or_dense_layout_protected"
    elif alpha_risk:
        active = False
        skip_reason = "alpha_protected"
    elif gradient_risk:
        active = False
        skip_reason = "synthetic_gradient_protected"
    elif fine_line_risk:
        active = False
        skip_reason = "fine_line_protected"
    elif brand_kv_risk:
        active = False
        skip_reason = "clean_brand_kv_protected"
    elif low_contrast_only and (image_type in {"unknown", "portrait", "product_kv"} or low_saturation_ratio > 0.92):
        active = False
        skip_reason = "low_contrast_only_conservative"
    elif not active:
        skip_reason = "no_low_quality_signal"

    strength = 0.0
    if active:
        strength = 0.025
        if low_resolution:
            strength += 0.018
        if jpeg_compression:
            strength += 0.014
        if dirty_shadow:
            strength += 0.012
        if low_contrast:
            strength += 0.008
        if soft_focus:
            strength += 0.006
        if image_type == "portrait":
            strength *= 0.56
            skip_reason = "portrait_fidelity_safe"
        elif image_type in {"architecture", "landscape"}:
            strength *= 1.04
        elif image_type == "product_kv":
            strength *= 0.55
        if text_density > 0.006:
            strength *= 0.72
            if skip_reason == "eligible":
                skip_reason = "text_presence_reduced"

    strength = float(np.clip(strength, 0.0, 0.115))
    if strength <= 0:
        active = False

    if len(reasons) >= 3:
        profile_name = "mixed_degradation"
    elif reasons:
        profile_name = reasons[0]
    else:
        profile_name = "none"

    return {
        "phase4_low_quality_active": bool(active),
        "phase4_degradation_profile": profile_name,
        "phase4_restoration_strength": round(strength, 4),
        "phase4_skip_reason": skip_reason,
        "compression_risk_before": round(compression_risk, 6),
        "shadow_dirt_risk_before": round(shadow_dirt_risk, 6),
        "local_contrast_before": round(local_contrast, 6),
    }


def phase4_low_quality_restore(
    reference: np.ndarray,
    image: np.ndarray,
    policy: dict[str, Any] | None,
) -> np.ndarray:
    policy = policy or {}
    strength = float(policy.get("phase4_restoration_strength") or 0.0)
    if strength <= 0:
        return image

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype("float32")
    luma = lab[:, :, 0]

    denoised = cv2.bilateralFilter(image, 5, 10 + strength * 28, 8 + strength * 24)
    den_luma = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB).astype("float32")[:, :, 0]

    luma_u8 = np.clip(luma, 0, 255).astype("uint8")
    clahe = cv2.createCLAHE(clipLimit=1.18, tileGridSize=(8, 8))
    contrast = clahe.apply(luma_u8).astype("float32")

    base = cv2.GaussianBlur(luma, (0, 0), 1.6)
    broad = cv2.GaussianBlur(luma, (0, 0), 5.8)
    structure = np.clip((base - broad) * 0.42, -4.2, 4.2)

    mean = cv2.GaussianBlur(luma, (0, 0), 2.2)
    mean_sq = cv2.GaussianBlur(luma * luma, (0, 0), 2.2)
    local_std = np.sqrt(np.maximum(mean_sq - mean * mean, 0.0))
    texture_mask = np.clip((local_std - 1.0) / 13.0, 0.0, 1.0)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 75, 170)
    edge_guard = 1.0 - cv2.dilate(edges, np.ones((5, 5), dtype=np.uint8), iterations=1).astype("float32") / 255.0 * 0.72
    highlight_guard = np.clip((242.0 - luma) / 28.0, 0.0, 1.0)
    shadow_guard = np.clip((luma - 6.0) / 26.0, 0.0, 1.0)

    text_guard = 1.0
    try:
        text_mask = detect_text_like_regions(image)
        if float(np.mean(text_mask > 0.08)) > 0.0004:
            text_mask = cv2.dilate((text_mask > 0.06).astype("uint8"), np.ones((5, 5), dtype=np.uint8), iterations=1)
            text_guard = 1.0 - np.clip(text_mask.astype("float32") * 0.94, 0.0, 0.94)
    except Exception:
        text_guard = 1.0

    tonal_mask = np.clip(edge_guard * highlight_guard * shadow_guard * text_guard, 0.0, 1.0)
    clean_blend = np.clip((0.16 + texture_mask * 0.24) * tonal_mask * strength, 0.0, 0.04)
    contrast_blend = np.clip((0.09 + texture_mask * 0.22) * tonal_mask * strength, 0.0, 0.026)
    structure_blend = np.clip(texture_mask * tonal_mask * strength, 0.0, 0.04)

    restored_luma = luma * (1.0 - clean_blend) + den_luma * clean_blend
    restored_luma = restored_luma * (1.0 - contrast_blend) + contrast * contrast_blend
    restored_luma = restored_luma + structure * structure_blend

    lab[:, :, 0] = np.clip(restored_luma, 0, 255)
    restored = cv2.cvtColor(lab.astype("uint8"), cv2.COLOR_LAB2BGR)
    return lock_color_to_reference(reference, restored, chroma_strength=0.995, luma_strength=0.018)
