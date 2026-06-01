from __future__ import annotations

import cv2
import numpy as np

from engine.analysis.edge_classifier import highlight_mask, normalized_mask


def build_highlight_protection_mask(image: np.ndarray) -> np.ndarray:
    return highlight_mask(image)


def protect_highlights(reference: np.ndarray, processed: np.ndarray, strength: float = 0.86) -> np.ndarray:
    """Blend bright reflective areas back toward the reference to prevent false detail."""
    strength = float(np.clip(strength, 0.0, 1.0))
    ref = reference
    if ref.shape[:2] != processed.shape[:2]:
        ref = cv2.resize(ref, (processed.shape[1], processed.shape[0]), interpolation=cv2.INTER_CUBIC)
    mask = build_highlight_protection_mask(ref)
    mask_f = normalized_mask(mask)[:, :, None] * strength
    result = processed.astype("float32") * (1.0 - mask_f) + ref.astype("float32") * mask_f
    return np.clip(result, 0, 255).astype("uint8")


def compress_clipped_highlights(image: np.ndarray, amount: float = 0.18) -> np.ndarray:
    """Gently reduce only clipped luminance while preserving original color intent."""
    amount = float(np.clip(amount, 0.0, 0.5))
    if amount <= 0:
        return image
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype("float32")
    l = lab[:, :, 0]
    over = l > 238
    if np.any(over):
        l[over] = 238 + (l[over] - 238) * (1.0 - amount)
    lab[:, :, 0] = np.clip(l, 0, 255)
    return cv2.cvtColor(lab.astype("uint8"), cv2.COLOR_LAB2BGR)
