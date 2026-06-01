from __future__ import annotations

import cv2
import numpy as np

from engine.analysis.edge_classifier import normalized_mask, true_edge_mask


def recover_structure(image: np.ndarray, image_type: str = "general", strength: float = 0.24) -> np.ndarray:
    """Recover mid/high-frequency structural cues without global hard sharpening."""
    type_multiplier = {
        "architecture": 1.28,
        "artifact": 1.18,
        "text_poster": 0.95,
        "portrait_indoor": 0.72,
        "ink_gray": 0.56,
        "general": 1.0,
    }.get(image_type, 1.0)
    strength = float(np.clip(strength * type_multiplier, 0.0, 0.72))
    if strength <= 0:
        return image

    mask = normalized_mask(true_edge_mask(image))[:, :, None]
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype("float32")
    l = lab[:, :, 0]
    small = cv2.GaussianBlur(l, (0, 0), 0.75)
    medium = cv2.GaussianBlur(l, (0, 0), 2.2)
    detail_small = l - small
    detail_mid = small - medium
    detail = detail_small * 0.55 + detail_mid * 0.9
    detail = np.sign(detail) * np.minimum(np.abs(detail), 10.0)
    restored = l + detail * strength
    lab[:, :, 0] = l * (1.0 - mask[:, :, 0]) + restored * mask[:, :, 0]
    return cv2.cvtColor(np.clip(lab, 0, 255).astype("uint8"), cv2.COLOR_LAB2BGR)
