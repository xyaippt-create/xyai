"""Single authoritative Safe-WB implementation.

The implementation is migrated byte-for-byte at the operation level from the
legacy color core.  D1 remains responsible for authorization and D2 remains
responsible for budget and protection masks.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def apply_safe_white_balance(
    rgb: np.ndarray,
    perception: dict[str, Any],
    *,
    valid_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, list[float], dict[str, Any]]:
    array = rgb.astype(np.float32)
    if valid_mask is None:
        valid = np.ones(array.shape[:2], dtype=bool)
    else:
        valid = np.asarray(valid_mask, dtype=bool)
        if valid.shape != array.shape[:2] or not valid.any():
            raise ValueError("Safe-WB valid mask must contain visible source pixels")
    maximum = array.max(axis=2)
    minimum = array.min(axis=2)
    saturation = np.divide(maximum - minimum, np.maximum(maximum, 1.0))
    luminance = 0.2126 * array[..., 0] + 0.7152 * array[..., 1] + 0.0722 * array[..., 2]
    neutral = valid & (saturation < 0.18) & (luminance > 38) & (luminance < 238)
    valid_count = int(valid.sum())
    neutral_ratio = float(neutral.sum() / valid_count)
    if int(neutral.sum()) < max(64, int(valid_count * 0.003)):
        return array, [1.0, 1.0, 1.0], {
            "white_balance_confidence": 0.0,
            "neutral_pixel_ratio": round(neutral_ratio, 4),
            "color_cast": "中性色证据不足",
            "color_cast_magnitude": 0.0,
            "white_balance_applied": False,
        }
    lab = cv2.cvtColor(array.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    cast_a = float(perception.get("neutral_cast_a", np.median(lab[..., 1][neutral]) - 128.0))
    cast_b = float(perception.get("neutral_cast_b", np.median(lab[..., 2][neutral]) - 128.0))
    cast_magnitude = float(np.hypot(cast_a, cast_b))
    confidence = float(np.clip(perception.get("global_cast_confidence", 0.0), 0.0, 1.0))
    direction = str(perception.get("global_cast_direction") or "none")
    correction_strength = float(np.clip(0.86 + 0.14 * confidence, 0.0, 1.0)) if direction != "none" else 0.0
    target_a = 1.2
    target_b = 1.8
    delta_a = float((target_a - cast_a) * correction_strength)
    delta_b = float((target_b - cast_b) * correction_strength)
    chroma_slope = 0.90 - 0.25 * confidence
    chroma_protection = np.clip(1.0 - saturation * chroma_slope, 0.40, 1.0)
    endpoint_protection = np.clip(luminance / 24.0, 0.25, 1.0) * np.clip((255.0 - luminance) / 24.0, 0.25, 1.0)
    correction_mask = chroma_protection * endpoint_protection
    corrected_lab = lab.copy()
    corrected_lab[..., 1] = np.clip(corrected_lab[..., 1] + delta_a * correction_mask, 0, 255)
    corrected_lab[..., 2] = np.clip(corrected_lab[..., 2] + delta_b * correction_mask, 0, 255)
    corrected = cv2.cvtColor(corrected_lab.astype(np.uint8), cv2.COLOR_LAB2RGB).astype(np.float32)
    source_means = np.maximum(array[valid].mean(axis=0), 1.0)
    corrected_means = corrected[valid].mean(axis=0)
    gains = np.clip(corrected_means / source_means, 0.85, 1.18)

    if direction == "none" or cast_magnitude < 1.5:
        cast_label = "未检测到明显偏色"
    elif direction == "warm":
        cast_label = "偏黄"
    elif direction == "cool":
        cast_label = "偏蓝/青"
    else:
        labels: list[str] = []
        if cast_a >= 1.5:
            labels.append("偏红")
        elif cast_a <= -1.5:
            labels.append("偏绿")
        if cast_b >= 1.5:
            labels.append("偏黄")
        elif cast_b <= -1.5:
            labels.append("偏蓝/青")
        cast_label = "、".join(labels) or "轻微混合偏色"
    info = {
        "white_balance_confidence": round(confidence, 3),
        "neutral_pixel_ratio": round(neutral_ratio, 4),
        "color_cast": cast_label,
        "color_cast_magnitude": round(cast_magnitude, 3),
        "white_balance_applied": bool(direction != "none" and correction_strength >= 0.08),
        "lab_neutral_cast_a": round(cast_a, 3),
        "lab_neutral_cast_b": round(cast_b, 3),
        "white_balance_target_lab_a": target_a,
        "white_balance_target_lab_b": target_b,
        "white_balance_lab_delta_a": round(delta_a, 4),
        "white_balance_lab_delta_b": round(delta_b, 4),
        "white_balance_execution_strength": round(correction_strength, 4),
        "white_balance_chroma_slope": round(chroma_slope, 4),
        "white_balance_execution": "spatial_neutral_target" if direction != "none" else "blocked",
    }
    return corrected, [round(float(value), 4) for value in gains], info


__all__ = ["apply_safe_white_balance"]
