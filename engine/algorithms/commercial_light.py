import cv2
import numpy as np


def _clamp01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def compress_highlights(image, strength: float):
    strength = _clamp01(strength)
    if strength <= 0:
        return image

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype("float32")
    lightness = lab[:, :, 0]
    mask = lightness > 190
    lightness[mask] = 190 + (lightness[mask] - 190) * (1.0 - strength * 0.28)
    lab[:, :, 0] = np.clip(lightness, 0, 255)
    return cv2.cvtColor(lab.astype("uint8"), cv2.COLOR_LAB2BGR)


def breathe_shadows(image, strength: float):
    strength = _clamp01(strength)
    if strength <= 0:
        return image

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype("float32")
    lightness = lab[:, :, 0]
    mask = lightness < 72
    lightness[mask] = lightness[mask] + (72 - lightness[mask]) * strength * 0.18
    lab[:, :, 0] = np.clip(lightness, 0, 255)
    return cv2.cvtColor(lab.astype("uint8"), cv2.COLOR_LAB2BGR)


def smooth_light_transition(image, strength: float):
    strength = _clamp01(strength)
    if strength <= 0:
        return image

    smooth = cv2.bilateralFilter(image, 7, 18 + strength * 22, 18 + strength * 22)
    return cv2.addWeighted(image, 1.0 - strength * 0.22, smooth, strength * 0.22, 0)


def apply_commercial_light(image, analysis, profile, rule_pack: dict | None = None, strategy=None):
    _ = rule_pack
    highlight = getattr(analysis, "highlight_risk", 0.25)
    atmosphere_gap = getattr(analysis, "atmosphere_deficiency", 0.35)
    light_strength = getattr(strategy, "light_compression_strength", highlight)
    atmosphere_strength = getattr(strategy, "atmosphere_strength", atmosphere_gap)

    result = compress_highlights(image, _clamp01(max(highlight, light_strength) * 0.8 + 0.12))
    result = breathe_shadows(result, _clamp01(0.18 + max(atmosphere_gap, atmosphere_strength) * 0.35))
    result = smooth_light_transition(result, _clamp01(0.12 + max(atmosphere_gap, atmosphere_strength) * 0.22))

    if profile.name in {"cinematic", "ai_commercial_kv", "cosmetics"}:
        soft = cv2.GaussianBlur(result, (0, 0), 0.35)
        result = cv2.addWeighted(result, 0.82, soft, 0.18, 0)

    return result
