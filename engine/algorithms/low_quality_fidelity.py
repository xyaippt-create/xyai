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


def _phase4_flat_region_mask(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype("float32")
    mean = cv2.GaussianBlur(gray, (0, 0), 3.2)
    mean_sq = cv2.GaussianBlur(gray * gray, (0, 0), 3.2)
    local_std = np.sqrt(np.maximum(mean_sq - mean * mean, 0.0))
    edges = cv2.Canny(np.clip(gray, 0, 255).astype("uint8"), 55, 135)
    edge_soft = cv2.dilate(edges, np.ones((5, 5), dtype=np.uint8), iterations=1).astype("float32") / 255.0
    flat = np.clip((4.8 - local_std) / 4.8, 0.0, 1.0)
    flat *= 1.0 - edge_soft * 0.88
    flat = cv2.GaussianBlur(flat, (0, 0), 3.0)
    return np.clip(flat, 0.0, 1.0).astype("float32")


def phase4_low_frequency_risk(reference: np.ndarray, candidate: np.ndarray) -> float:
    if reference.shape[:2] != candidate.shape[:2]:
        reference = cv2.resize(reference, (candidate.shape[1], candidate.shape[0]), interpolation=cv2.INTER_AREA)
    ref_l = cv2.cvtColor(reference, cv2.COLOR_BGR2LAB).astype("float32")[:, :, 0]
    out_l = cv2.cvtColor(candidate, cv2.COLOR_BGR2LAB).astype("float32")[:, :, 0]
    flat = _phase4_flat_region_mask(reference)
    low_diff = np.abs(cv2.GaussianBlur(out_l - ref_l, (0, 0), 7.0))
    if float(np.mean(flat > 0.45)) < 0.004:
        return 0.0
    risk = float(np.percentile(low_diff[flat > 0.45], 95))
    return round(float(np.clip(risk / 4.0, 0.0, 1.0)), 6)


def phase4_color_drift_metrics(reference: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
    if reference.shape[:2] != candidate.shape[:2]:
        reference = cv2.resize(reference, (candidate.shape[1], candidate.shape[0]), interpolation=cv2.INTER_AREA)
    ref_lab = cv2.cvtColor(reference, cv2.COLOR_BGR2LAB).astype("float32")
    out_lab = cv2.cvtColor(candidate, cv2.COLOR_BGR2LAB).astype("float32")
    delta = np.linalg.norm(ref_lab - out_lab, axis=2)
    ref_hsv = cv2.cvtColor(reference, cv2.COLOR_BGR2HSV).astype("float32")
    out_hsv = cv2.cvtColor(candidate, cv2.COLOR_BGR2HSV).astype("float32")
    ref_sat = ref_hsv[:, :, 1] / 255.0
    out_sat = out_hsv[:, :, 1] / 255.0
    return {
        "mean_delta_e": round(float(np.mean(delta)), 6),
        "p95_delta_e": round(float(np.percentile(delta, 95)), 6),
        "saturation_delta": round(float(np.mean(out_sat) - np.mean(ref_sat)), 6),
        "high_saturation_pixel_ratio_delta": round(float(np.mean(out_sat > 0.68) - np.mean(ref_sat > 0.68)), 6),
    }


def phase4_text_protection_stats(image: np.ndarray) -> dict[str, Any]:
    try:
        text_mask = detect_text_like_regions(image)
    except Exception:
        text_mask = np.zeros(image.shape[:2], dtype="float32")
    binary = (text_mask > 0.06).astype("uint8")
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    total_area = max(1, binary.shape[0] * binary.shape[1])
    regions = []
    largest = 0
    height, width = binary.shape[:2]
    thirds = {"top": 0, "middle": 0, "bottom": 0}
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < 12:
            continue
        largest = max(largest, area)
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        w = int(stats[label, cv2.CC_STAT_WIDTH])
        h = int(stats[label, cv2.CC_STAT_HEIGHT])
        center_y = y + h * 0.5
        if center_y < height / 3:
            thirds["top"] += area
        elif center_y < height * 2 / 3:
            thirds["middle"] += area
        else:
            thirds["bottom"] += area
        regions.append(area)
    ratio = float(np.count_nonzero(binary) / total_area)
    distribution = {key: round(value / total_area, 6) for key, value in thirds.items()}
    return {
        "text_region_count": int(len(regions)),
        "text_mask_ratio": round(ratio, 6),
        "largest_text_region_ratio": round(float(largest / total_area), 6),
        "text_region_distribution": distribution,
    }


def phase4_restoration_masks(image: np.ndarray, policy: dict[str, Any] | None = None) -> dict[str, np.ndarray]:
    policy = policy or {}
    try:
        text_mask = detect_text_like_regions(image)
    except Exception:
        text_mask = np.zeros(image.shape[:2], dtype="float32")
    text_binary = (text_mask > 0.055).astype("uint8")
    protected = cv2.dilate(text_binary, np.ones((7, 7), dtype=np.uint8), iterations=1).astype("float32")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 90, 190)
    small_edges = cv2.dilate(edges, np.ones((3, 3), dtype=np.uint8), iterations=1).astype("float32") / 255.0
    protected = np.maximum(protected, small_edges * 0.42)
    flat_mask = _phase4_flat_region_mask(image)
    flat_strength = 0.82 if policy.get("phase4_product_photo_eligible") else 0.94
    protected = np.maximum(protected, flat_mask * flat_strength)

    protected = cv2.GaussianBlur(protected, (0, 0), 2.0)
    protected = np.clip(protected, 0.0, 1.0)
    if policy.get("phase4_text_protection_mode") == "global":
        protected = np.ones_like(protected, dtype="float32")
    restoration = 1.0 - protected
    return {
        "text_mask": np.clip(text_binary.astype("float32"), 0.0, 1.0),
        "flat_region_mask": flat_mask.astype("float32"),
        "protected_mask": protected.astype("float32"),
        "restoration_mask": restoration.astype("float32"),
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
    text_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    features = type_features or {}
    probes = before_probes or {}
    texture_density = float(features.get("texture_density") or 0.0)
    edge_density = float(features.get("edge_density") or 0.0)
    skin_ratio = float(features.get("skin_ratio") or 0.0)
    dark_ratio = float(features.get("dark_ratio") or 0.0)
    low_saturation_ratio = float(features.get("low_saturation_ratio") or 0.0)
    compression_risk = float(probes.get("compression_risk") or 0.0)
    shadow_dirt_risk = float(probes.get("shadow_dirt_risk") or 0.0)
    local_contrast = float(probes.get("local_contrast") or 0.0)
    blur_risk = float(probes.get("blur_risk") or 0.0)
    text_info = text_stats or {}
    text_mask_ratio = float(text_info.get("text_mask_ratio", text_density) or 0.0)
    largest_text_region_ratio = float(text_info.get("largest_text_region_ratio") or 0.0)
    flat_region_ratio = float(
        np.clip(
            low_saturation_ratio * 0.58
            + (1.0 - min(texture_density / 0.03, 1.0)) * 0.28
            + (1.0 - min(edge_density / 0.04, 1.0)) * 0.14,
            0.0,
            1.0,
        )
    )

    photographicity_score = float(
        np.clip(
            skin_ratio * 1.35
            + texture_density * 1.05
            + min(dark_ratio, 0.45) * 0.34
            + (0.08 if image_type == "portrait" else 0.0),
            0.0,
            1.0,
        )
    )
    face_or_person_detected = bool(image_type == "portrait" or skin_ratio >= 0.035)

    min_side = min(int(input_width or 0), int(input_height or 0))
    low_resolution = min_side > 0 and min_side < 420
    jpeg_like = input_suffix.lower() in {".jpg", ".jpeg"}
    low_contrast = local_contrast < 0.34
    soft_focus = blur_risk > 0.18
    dirty_shadow = shadow_dirt_risk > 0.18
    jpeg_compression = jpeg_like and (compression_risk > 0.018 or input_size_bytes < max(1, input_width * input_height * 0.18))
    product_photo_eligible = bool(
        jpeg_like
        and min_side >= 640
        and image_type in {"text_poster", "product_kv", "unknown"}
        and 0.002 <= text_mask_ratio <= 0.09
        and largest_text_region_ratio < 0.022
        and edge_density < 0.018
        and low_saturation_ratio > 0.34
        and (jpeg_compression or soft_focus or low_contrast)
    )

    pure_text_layout = bool(
        mode == "text_safe"
        or (
            image_type in {"text_poster", "ppt_page"}
            and photographicity_score < 0.20
        )
        or (
            text_mask_ratio >= 0.16
            and largest_text_region_ratio >= 0.028
            and photographicity_score < 0.28
        )
    )
    incidental_text_photo = bool(
        not pure_text_layout
        and text_mask_ratio >= 0.006
        and photographicity_score >= 0.12
        and (face_or_person_detected or texture_density >= 0.045)
    )
    text_risk = bool(pure_text_layout or (text_density >= 0.018 and not incidental_text_photo))
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
    elif pure_text_layout:
        active = False
        skip_reason = "text_or_dense_layout_protected"
    elif text_risk:
        active = False
        skip_reason = "text_heavy_non_photo_protected"
    elif alpha_risk:
        active = False
        skip_reason = "alpha_protected"
    elif gradient_risk and not product_photo_eligible:
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
        if product_photo_eligible:
            strength *= 0.45
            skip_reason = "product_photo_fidelity_safe"
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
                skip_reason = "local_text_protected"

    strength = float(np.clip(strength, 0.0, 0.115))
    if strength <= 0:
        active = False
    text_mode = "global" if pure_text_layout else ("local" if incidental_text_photo or text_mask_ratio > 0 else "none")

    if len(reasons) >= 3:
        profile_name = "mixed_degradation"
    elif reasons:
        profile_name = reasons[0]
    else:
        profile_name = "none"

    return {
        "phase4_photo_eligible": bool(active and not pure_text_layout),
        "phase4_low_quality_active": bool(active),
        "phase4_product_photo_eligible": product_photo_eligible,
        "phase4_flat_region_protected": bool(flat_region_ratio >= 0.46 or gradient_risk),
        "phase4_product_subject_active": bool(active and product_photo_eligible),
        "phase4_gradient_background_protected": bool(gradient_risk or flat_region_ratio >= 0.58),
        "phase4_flat_region_ratio": round(flat_region_ratio, 6),
        "phase4_text_mask_ratio": round(text_mask_ratio, 6),
        "phase4_text_protection_mode": text_mode,
        "phase4_nontext_restoration_active": bool(active and text_mode in {"local", "none"}),
        "phase4_global_skip_reason": skip_reason if not active else "",
        "phase4_degradation_profile": profile_name,
        "phase4_restoration_strength": round(strength, 4),
        "phase4_skip_reason": skip_reason,
        "photographicity_score": round(photographicity_score, 6),
        "face_or_person_detected": face_or_person_detected,
        "local_texture_score": round(texture_density, 6),
        "text_region_count": int(text_info.get("text_region_count") or 0),
        "largest_text_region_ratio": round(largest_text_region_ratio, 6),
        "text_region_distribution": text_info.get("text_region_distribution") or {},
        "compression_risk_before": round(compression_risk, 6),
        "shadow_dirt_risk_before": round(shadow_dirt_risk, 6),
        "local_contrast_before": round(local_contrast, 6),
        "phase4_low_frequency_risk_before": 0.0,
        "phase4_low_frequency_risk_after": 0.0,
        "phase4_color_drift_risk": "low",
        "phase4_fallback_triggered": False,
        "phase4_fallback_reason": "",
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

    masks = phase4_restoration_masks(image, policy)
    text_guard = masks["restoration_mask"]

    tonal_mask = np.clip(edge_guard * highlight_guard * shadow_guard * text_guard, 0.0, 1.0)
    clean_blend = np.clip((0.16 + texture_mask * 0.24) * tonal_mask * strength, 0.0, 0.04)
    contrast_blend = np.clip((0.09 + texture_mask * 0.22) * tonal_mask * strength, 0.0, 0.026)
    structure_blend = np.clip(texture_mask * tonal_mask * strength, 0.0, 0.04)

    restored_luma = luma * (1.0 - clean_blend) + den_luma * clean_blend
    restored_luma = restored_luma * (1.0 - contrast_blend) + contrast * contrast_blend
    restored_luma = restored_luma + structure * structure_blend
    max_luma_delta = 1.55 if policy.get("phase4_product_photo_eligible") else 2.35
    restored_luma = np.clip(restored_luma, luma - max_luma_delta, luma + max_luma_delta)

    lab[:, :, 0] = np.clip(restored_luma, 0, 255)
    restored = cv2.cvtColor(lab.astype("uint8"), cv2.COLOR_LAB2BGR)
    restored = lock_color_to_reference(image, restored, chroma_strength=1.0, luma_strength=0.0)
    low_freq_before = phase4_low_frequency_risk(image, image)
    low_freq_after = phase4_low_frequency_risk(image, restored)
    color = phase4_color_drift_metrics(image, restored)
    policy["phase4_low_frequency_risk_before"] = low_freq_before
    policy["phase4_low_frequency_risk_after"] = low_freq_after
    is_product_photo = bool(policy.get("phase4_product_photo_eligible"))
    is_real_photo_like = bool(
        is_product_photo
        or policy.get("face_or_person_detected")
        or float(policy.get("photographicity_score") or 0.0) >= 0.34
        or float(policy.get("local_texture_score") or 0.0) >= 0.08
    )
    low_freq_limit = 0.42 if is_product_photo else (0.34 if is_real_photo_like else 0.22)
    saturation_limit = 0.025 if is_product_photo else (0.018 if is_real_photo_like else 0.012)
    high_sat_limit = 0.018 if is_product_photo else (0.014 if is_real_photo_like else 0.01)
    policy["phase4_color_drift_risk"] = "high" if (
        color["p95_delta_e"] > 3.0
        or abs(color["saturation_delta"]) > saturation_limit
        or abs(color["high_saturation_pixel_ratio_delta"]) > high_sat_limit
    ) else "low"
    fallback_reasons: list[str] = []
    if low_freq_after > low_freq_limit:
        fallback_reasons.append(f"low_frequency_risk={low_freq_after}")
    if color["p95_delta_e"] > 3.0:
        fallback_reasons.append(f"p95_delta_e={color['p95_delta_e']}")
    if abs(color["saturation_delta"]) > saturation_limit:
        fallback_reasons.append(f"saturation_delta={color['saturation_delta']}")
    if fallback_reasons:
        policy["phase4_fallback_triggered"] = True
        policy["phase4_fallback_reason"] = ";".join(fallback_reasons)
        policy["phase4_low_quality_active"] = False
        policy["phase4_restoration_strength"] = 0.0
        return image
    policy["phase4_fallback_triggered"] = False
    policy["phase4_fallback_reason"] = ""
    return restored
