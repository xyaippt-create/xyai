from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def _resize_reference(reference: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    if reference.shape[:2] == candidate.shape[:2]:
        return reference
    return cv2.resize(reference, (candidate.shape[1], candidate.shape[0]), interpolation=cv2.INTER_CUBIC)


def _risk_level(value: float, medium: float, high: float) -> str:
    if value >= high:
        return "high"
    if value >= medium:
        return "medium"
    return "low"


def phase6_smooth_region_metrics(reference: np.ndarray, candidate: np.ndarray) -> dict[str, Any]:
    ref = _resize_reference(reference, candidate)
    ref_gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY).astype("float32")
    out_gray = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY).astype("float32")
    ref_blur = cv2.GaussianBlur(ref_gray, (0, 0), 2.2)
    out_blur = cv2.GaussianBlur(out_gray, (0, 0), 2.2)
    ref_grad_x = cv2.Sobel(ref_blur, cv2.CV_32F, 1, 0, ksize=3)
    ref_grad_y = cv2.Sobel(ref_blur, cv2.CV_32F, 0, 1, ksize=3)
    out_grad_x = cv2.Sobel(out_blur, cv2.CV_32F, 1, 0, ksize=3)
    out_grad_y = cv2.Sobel(out_blur, cv2.CV_32F, 0, 1, ksize=3)
    ref_grad = cv2.magnitude(ref_grad_x, ref_grad_y)
    out_grad = cv2.magnitude(out_grad_x, out_grad_y)
    flat_mask = ref_grad < 5.5
    if float(np.mean(flat_mask)) < 0.03:
        flat_mask = ref_grad < 8.5

    diff = np.abs(out_blur - ref_blur)
    flat_diff = float(np.mean(diff[flat_mask])) if np.any(flat_mask) else float(np.mean(diff))
    flat_uniformity = max(0.0, min(1.0, 1.0 - flat_diff / 18.0))
    band_signal = float(np.percentile(np.abs(out_grad[flat_mask] - ref_grad[flat_mask]), 95)) if np.any(flat_mask) else 0.0

    ref_hsv = cv2.cvtColor(ref, cv2.COLOR_BGR2HSV).astype("float32")
    out_hsv = cv2.cvtColor(candidate, cv2.COLOR_BGR2HSV).astype("float32")
    highlight_mask = (ref_hsv[:, :, 2] > 218) & (ref_hsv[:, :, 1] > 10)
    if np.any(highlight_mask):
        highlight_sat_delta = float(np.mean((out_hsv[:, :, 1] - ref_hsv[:, :, 1])[highlight_mask]) / 255.0)
    else:
        highlight_sat_delta = 0.0
    highlight_pollution_score = max(0.0, highlight_sat_delta)

    gradient_score = max(0.0, flat_diff / 18.0)
    band_score = max(0.0, band_signal / 22.0)
    smooth_fallback = gradient_score >= 0.72 or band_score >= 0.72 or highlight_pollution_score >= 0.08
    return {
        "phase6_gradient_risk": _risk_level(gradient_score, 0.42, 0.72),
        "phase6_band_risk": _risk_level(band_score, 0.42, 0.72),
        "phase6_highlight_pollution_risk": _risk_level(highlight_pollution_score, 0.035, 0.08),
        "phase6_flat_region_uniformity": round(float(flat_uniformity), 6),
        "phase6_smooth_region_fallback": bool(smooth_fallback),
        "phase6_smooth_region_fallback_reason": "smooth_region_guard" if smooth_fallback else "",
    }


def phase6_delivery_guard_policy(
    *,
    input_size_bytes: int,
    main_size_bytes: int,
    optimized_size_bytes: int,
    final_size_bytes: int,
    main_metrics: dict[str, Any],
    candidate_metrics: dict[str, Any],
    compression: dict[str, Any],
    quality_1080p_pass: bool,
    final_quality_source: str,
    image_type: str,
    smooth_metrics: dict[str, Any],
) -> dict[str, Any]:
    clarity_gain = max(0.0, float(main_metrics.get("clarity_gain") or 0.0))
    text_gain = max(0.0, float(main_metrics.get("text_clarity_gain") or 0.0))
    edge_gain = max(0.0, float(main_metrics.get("edge_quality_gain") or 0.0))
    detail_score = float(main_metrics.get("detail_stability_score") or 0.0)
    color_score = float(main_metrics.get("color_fidelity_score") or 0.0)
    detail_bonus = max(0.0, (detail_score - 78.0) / 12.0)
    color_bonus = max(0.0, (color_score - 94.0) / 8.0)
    visible_benefit = round(clarity_gain * 0.32 + text_gain * 0.18 + edge_gain * 0.24 + detail_bonus * 0.16 + color_bonus * 0.10, 6)
    size_growth_ratio = round(float(final_size_bytes) / max(float(input_size_bytes), 1.0), 6)
    benefit_size_ratio = round(visible_benefit / max(size_growth_ratio, 0.001), 6)
    optimized_smaller = optimized_size_bytes < main_size_bytes
    safe_optimized = bool(compression.get("compression_allowed") and optimized_smaller)

    size_fallback = False
    fallback_reason = ""
    if size_growth_ratio > 8.0 and visible_benefit < 0.35:
        size_fallback = True
        fallback_reason = "large_size_low_visible_benefit"
    elif size_growth_ratio > 14.0 and visible_benefit < 0.85:
        size_fallback = True
        fallback_reason = "very_large_size_limited_benefit"

    if not quality_1080p_pass:
        delivery_status = "PASS_WITH_LIMITATION"
        delivery_reason = "quality_1080p_gate_not_fully_passed"
        risk_level = "medium"
    elif smooth_metrics.get("phase6_smooth_region_fallback"):
        delivery_status = "PASS_WITH_LIMITATION"
        delivery_reason = smooth_metrics.get("phase6_smooth_region_fallback_reason") or "smooth_region_guard"
        risk_level = "medium"
    elif size_fallback:
        delivery_status = "PASS_WITH_LIMITATION"
        delivery_reason = fallback_reason
        risk_level = "medium"
    else:
        delivery_status = "PASS"
        delivery_reason = "delivery_guard_pass"
        risk_level = "low"

    if image_type in {"text_poster", "ppt_page"} and not quality_1080p_pass:
        recommended = "manual_review_required"
    elif size_growth_ratio > 8.0:
        recommended = "screen_1080p;web_delivery;manual_review_required"
    else:
        recommended = "screen_1080p;ppt_delivery;web_delivery"

    return {
        "phase6_delivery_guard_active": True,
        "phase6_visible_benefit_score": visible_benefit,
        "phase6_size_growth_ratio": size_growth_ratio,
        "phase6_benefit_size_ratio": benefit_size_ratio,
        "phase6_encoding_profile": final_quality_source,
        "phase6_size_fallback_triggered": bool(size_fallback),
        "phase6_size_fallback_reason": fallback_reason,
        "phase6_safe_optimized_available": safe_optimized,
        "phase6_candidate_quality_drop": round(float(candidate_metrics.get("visual_score", 0.0)) - float(main_metrics.get("visual_score", 0.0)), 6),
        "final_delivery_status": delivery_status,
        "final_delivery_reason": delivery_reason,
        "final_delivery_risk_level": risk_level,
        "final_delivery_recommended_usage": recommended,
    }
