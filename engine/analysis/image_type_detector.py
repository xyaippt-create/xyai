from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from engine.algorithms.text_clarity import detect_text_like_regions
from engine.analysis.edge_classifier import highlight_mask


@dataclass(frozen=True)
class ImageTypeResult:
    image_type: str
    confidence: float
    scores: dict[str, float]


def _edge_density(image) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 55, 155)
    return float(np.count_nonzero(edges) / edges.size)


def _line_score(image) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=55, minLineLength=max(24, min(gray.shape) // 18), maxLineGap=5)
    if lines is None:
        return 0.0
    return float(np.clip(len(lines) / 90.0, 0.0, 1.0))


def _skin_score(image) -> float:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    ycrcb = cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb)
    hsv_mask = (hsv[:, :, 0] <= 24) & (hsv[:, :, 1] >= 28) & (hsv[:, :, 1] <= 175) & (hsv[:, :, 2] >= 55)
    ycc_mask = (ycrcb[:, :, 1] >= 133) & (ycrcb[:, :, 1] <= 178) & (ycrcb[:, :, 2] >= 77) & (ycrcb[:, :, 2] <= 135)
    return float(np.count_nonzero(hsv_mask & ycc_mask) / hsv_mask.size)


def _gray_ink_score(image) -> float:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    low_saturation = float(np.count_nonzero(saturation < 34) / saturation.size)
    tone_range = float(value.std() / 80.0)
    return float(np.clip(low_saturation * 0.75 + tone_range * 0.25, 0.0, 1.0))


def detect_image_type(image) -> ImageTypeResult:
    text_mask = detect_text_like_regions(image)
    text_score = float(np.mean(text_mask > 0.28))
    edge_score = _edge_density(image)
    line_score = _line_score(image)
    skin_score = _skin_score(image)
    ink_score = _gray_ink_score(image)
    highlight_score = float(np.count_nonzero(highlight_mask(image)) / image.shape[0] / image.shape[1])

    artifact_base = highlight_score * 1.8 + edge_score * 0.55 - line_score * 0.35
    artifact_score = float(np.clip(artifact_base if highlight_score > 0.015 else edge_score * 0.18, 0.0, 1.0))
    architecture_score = float(np.clip(line_score * 0.75 + edge_score * 0.8 - skin_score * 1.2, 0.0, 1.0))
    text_poster_score = float(np.clip(text_score * 36.0 + edge_score * 1.2 + line_score * 0.25, 0.0, 1.0))
    portrait_score = float(np.clip(skin_score * 3.0 + highlight_score * 0.25, 0.0, 1.0))

    candidates = {
        "text_poster": text_poster_score,
        "architecture": architecture_score,
        "artifact": artifact_score,
        "portrait_indoor": portrait_score,
        "ink_gray": ink_score if ink_score > 0.62 and text_score < 0.001 else 0.0,
        "general": 0.28,
    }
    image_type = max(candidates, key=candidates.get)
    confidence = float(np.clip(candidates[image_type], 0.0, 1.0))
    return ImageTypeResult(
        image_type=image_type,
        confidence=confidence,
        scores={key: round(float(value), 4) for key, value in candidates.items()},
    )
