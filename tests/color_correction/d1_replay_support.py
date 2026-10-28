"""Minimal deterministic fixtures for D1/D2/D3 safety regressions."""

from __future__ import annotations

import numpy as np


def _neutral_base() -> np.ndarray:
    height, width = 180, 240
    yy, xx = np.indices((height, width))
    levels = np.asarray([0.22, 0.38, 0.56, 0.74], dtype=np.float32)
    value = levels[((yy // 30) + (xx // 40)) % len(levels)]
    return np.repeat(value[..., None], 3, axis=2)


def _tint(image: np.ndarray, gains: tuple[float, float, float]) -> np.ndarray:
    return np.clip(image * np.asarray(gains, dtype=np.float32), 0.0, 1.0)


def build_replay_image(recipe: str) -> tuple[np.ndarray, list[tuple[int, int, int, int]] | None]:
    base = _neutral_base()
    if recipe == "yellow_cast":
        return _tint(base, (1.13, 1.05, 0.76)), None
    if recipe == "blue_cast":
        return _tint(base, (0.76, 0.91, 1.16)), None
    if recipe == "too_dark":
        return np.clip(base * 0.34, 0.0, 1.0), None
    if recipe == "too_bright":
        return np.clip(0.72 + base * 0.42, 0.0, 1.0), None
    if recipe == "normal_warm":
        return _tint(base, (1.08, 1.02, 0.88)), None
    if recipe == "normal_cool":
        return _tint(base, (0.88, 0.97, 1.08)), None
    if recipe == "normal_dark":
        image = base * 0.25
        image[10:34, 10:230] = 0.68
        return image, None
    if recipe == "person_skin":
        image = base.copy()
        image[35:145, 85:155] = (0.72, 0.48, 0.34)
        return image, [(80, 25, 80, 130)]
    if recipe == "local_person_led_blue":
        image = base.copy()
        image[:82] = (0.08, 0.22, 0.78)
        image[35:145, 85:120] = (0.72, 0.48, 0.34)
        image[35:145, 120:155] = (0.24, 0.37, 0.72)
        return image, [(80, 25, 80, 130)]
    if recipe == "neutral_scene":
        return base, None
    if recipe == "dominant_brand_red":
        image = np.full_like(base, (0.82, 0.08, 0.09))
        image[65:115, 95:145] = 0.60
        return image, None
    if recipe == "mixed_light":
        image = base.copy()
        image[:, :120] = _tint(base[:, :120], (1.13, 1.04, 0.76))
        image[:, 120:] = _tint(base[:, 120:], (0.76, 0.91, 1.16))
        return image, None
    raise KeyError(f"unknown D1 replay recipe: {recipe}")
