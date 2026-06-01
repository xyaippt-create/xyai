from __future__ import annotations

import cv2
import numpy as np


def _score(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return float(np.clip((value - low) / (high - low) * 100.0, 0.0, 100.0))


def compute_basic_metrics(image) -> dict[str, float]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return {
        "brightness": float(gray.mean()),
        "contrast": float(gray.std()),
        "sharpness": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
    }


def compute_quality_metrics(image) -> dict[str, float]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_32F)
    edges = cv2.Canny(gray, 55, 150, L2gradient=True)
    edge_density = float(np.count_nonzero(edges) / edges.size)
    local_mean = cv2.blur(gray.astype("float32"), (9, 9))
    local_contrast = float(np.mean(np.abs(gray.astype("float32") - local_mean)))
    small = cv2.GaussianBlur(gray, (0, 0), 0.75)
    medium = cv2.GaussianBlur(gray, (0, 0), 2.2)
    mid_detail = float(np.mean(np.abs(small.astype("float32") - medium.astype("float32"))))
    high_detail = float(np.mean(np.abs(gray.astype("float32") - small.astype("float32"))))

    flat_mask = np.abs(lap) < 2.5
    noise = float(np.std(gray[flat_mask])) if np.any(flat_mask) else float(np.std(gray) * 0.35)

    return {
        "brightness": round(float(gray.mean()), 4),
        "contrast": round(float(gray.std()), 4),
        "sharpness": round(float(lap.var()), 4),
        "edge_density": round(edge_density, 6),
        "clarity_score": round(_score(lap.var(), 35.0, 1150.0) * 0.58 + _score(local_contrast, 4.0, 22.0) * 0.42, 4),
        "structure_score": round(_score(mid_detail, 1.2, 13.5) * 0.55 + _score(edge_density, 0.015, 0.145) * 0.45, 4),
        "texture_score": round(_score(high_detail, 0.9, 12.0), 4),
        "noise_score": round(_score(noise, 1.8, 18.0), 4),
    }
