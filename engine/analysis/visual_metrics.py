from dataclasses import asdict, dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class VisualMetrics:
    high_frequency_pollution: float
    ai_dirty_score: float
    sharpening_risk: float
    dirty_highlight_score: float
    mid_frequency_structure: float
    premium_baseline: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def _normalize(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return float(np.clip((value - low) / (high - low), 0.0, 1.0))


def analyze_high_frequency_pollution(image) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    return _normalize(float(laplacian.var()), 120.0, 1200.0)


def analyze_ai_dirty_feel(image) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    local_mean = cv2.GaussianBlur(gray, (0, 0), 4.0)
    residual = cv2.absdiff(gray, local_mean)
    return _normalize(float(residual.mean()), 4.0, 26.0)


def analyze_sharpening_risk(image) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 180)
    edge_density = float((edges > 0).mean())
    return _normalize(edge_density, 0.04, 0.22)


def analyze_dirty_highlights(image) -> float:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    value = hsv[:, :, 2]
    saturation = hsv[:, :, 1]
    highlight_mask = value > 210
    if not np.any(highlight_mask):
        return 0.0
    highlight_saturation = float(saturation[highlight_mask].mean())
    highlight_texture = float(cv2.Laplacian(value, cv2.CV_64F)[highlight_mask].var())
    saturation_risk = _normalize(highlight_saturation, 12.0, 80.0)
    texture_risk = _normalize(highlight_texture, 20.0, 650.0)
    return float(np.clip((saturation_risk + texture_risk) / 2.0, 0.0, 1.0))


def analyze_mid_frequency_structure(image) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    low = cv2.GaussianBlur(gray, (0, 0), 6.0)
    mid = cv2.GaussianBlur(gray, (0, 0), 1.2)
    band = cv2.absdiff(mid, low)
    return _normalize(float(band.std()), 4.0, 32.0)


def analyze_premium_baseline(image) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    brightness = _normalize(float(gray.mean()), 70.0, 190.0)
    contrast = 1.0 - abs(_normalize(float(gray.std()), 20.0, 82.0) - 0.58)
    dirt = 1.0 - analyze_ai_dirty_feel(image)
    high_frequency = 1.0 - analyze_high_frequency_pollution(image) * 0.55
    return float(np.clip((brightness * 0.2) + (contrast * 0.25) + (dirt * 0.3) + (high_frequency * 0.25), 0.0, 1.0))


def compute_visual_metrics(image) -> VisualMetrics:
    return VisualMetrics(
        high_frequency_pollution=analyze_high_frequency_pollution(image),
        ai_dirty_score=analyze_ai_dirty_feel(image),
        sharpening_risk=analyze_sharpening_risk(image),
        dirty_highlight_score=analyze_dirty_highlights(image),
        mid_frequency_structure=analyze_mid_frequency_structure(image),
        premium_baseline=analyze_premium_baseline(image),
    )
