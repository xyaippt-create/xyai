from __future__ import annotations

import cv2
import numpy as np

from engine.analysis.edge_classifier import compression_block_mask, normalized_mask, true_edge_mask


def repair_compression_artifacts(image, strength: float = 0.22):
    """Reduce block/compression damage before enlargement while keeping real texture."""
    strength = float(np.clip(strength, 0.0, 1.0))
    if strength <= 0:
        return image

    block_mask = normalized_mask(compression_block_mask(image))
    edge_keep = normalized_mask(true_edge_mask(image, exclude_highlights=False))
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    lap = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
    flat_mask = np.clip(1.0 - lap / 18.0, 0.0, 1.0)
    repair_mask = np.clip(block_mask * 0.8 + flat_mask * 0.42, 0.0, 1.0)
    repair_mask *= 1.0 - edge_keep * 0.72
    repair_mask = cv2.GaussianBlur(repair_mask.astype("float32"), (0, 0), 0.7)[:, :, None]

    bilateral = cv2.bilateralFilter(image, 5, 12 + strength * 20, 9 + strength * 18)
    denoised = cv2.fastNlMeansDenoisingColored(
        image,
        None,
        h=2.0 + strength * 3.5,
        hColor=2.0 + strength * 3.0,
        templateWindowSize=7,
        searchWindowSize=15,
    )
    repaired = cv2.addWeighted(bilateral, 0.72, denoised, 0.28, 0)
    blend = np.clip(repair_mask * strength * 0.72, 0.0, 0.72)
    result = image.astype("float32") * (1.0 - blend) + repaired.astype("float32") * blend
    return np.clip(result, 0, 255).astype("uint8")
