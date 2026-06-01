from __future__ import annotations

import cv2
import numpy as np

from engine.analysis.edge_classifier import normalized_mask, true_edge_mask


def enhance_true_edges(image: np.ndarray, strength: float = 0.26, mask: np.ndarray | None = None) -> np.ndarray:
    """Enhance stable edges only; avoid random noise and reflective highlights."""
    strength = float(np.clip(strength, 0.0, 0.8))
    if strength <= 0:
        return image
    edge_mask = true_edge_mask(image) if mask is None else mask
    mask_f = normalized_mask(edge_mask)[:, :, None]

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype("float32")
    l = lab[:, :, 0]
    base = cv2.GaussianBlur(l, (0, 0), 0.9)
    detail = l - base
    # Soft threshold prevents flat noise from being lifted.
    detail = np.sign(detail) * np.maximum(np.abs(detail) - 1.5, 0.0)
    l_enhanced = l + detail * strength
    lab[:, :, 0] = l * (1.0 - mask_f[:, :, 0]) + l_enhanced * mask_f[:, :, 0]
    return cv2.cvtColor(np.clip(lab, 0, 255).astype("uint8"), cv2.COLOR_LAB2BGR)
