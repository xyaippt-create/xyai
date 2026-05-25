import cv2
import numpy as np


def _clamp01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def recover_mid_frequency_structure(image, analysis, profile, rule_pack: dict | None = None, strategy=None):
    _ = rule_pack
    mid_score = getattr(analysis, "mid_frequency_score", 0.45)
    high_frequency = getattr(analysis, "high_frequency_pollution", 0.35)
    strategy_mid = getattr(strategy, "mid_frequency_restore_strength", 0.35)

    need = _clamp01(max(1.0 - mid_score, strategy_mid))
    if need <= 0.05:
        return image

    gray_guard = 1.0 - high_frequency * 0.45
    amount = min(0.28, need * 0.22 * gray_guard + profile.micro_contrast * 0.08)

    low = cv2.GaussianBlur(image, (0, 0), 5.0)
    mid = cv2.GaussianBlur(image, (0, 0), 1.4)
    band = cv2.subtract(mid, low)
    restored = cv2.addWeighted(image, 1.0, band, amount, 0)

    return np.clip(restored, 0, 255).astype("uint8")


def protect_skin_like_midtones(image, strength: float):
    strength = _clamp01(strength)
    if strength <= 0:
        return image
    return cv2.bilateralFilter(image, 5, 12 + strength * 12, 12 + strength * 12)


def restore_commercial_structure(image, analysis, profile, rule_pack: dict | None = None, strategy=None):
    result = recover_mid_frequency_structure(image, analysis, profile, rule_pack, strategy)
    if profile.name in {"cosmetics", "cinematic"}:
        result = protect_skin_like_midtones(result, 0.18)
    return result
