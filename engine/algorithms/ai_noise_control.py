import cv2
import numpy as np


def _clamp01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def suppress_diffusion_texture(image, strength: float):
    strength = _clamp01(strength)
    if strength <= 0:
        return image

    denoised = cv2.fastNlMeansDenoisingColored(
        image,
        None,
        2 + int(strength * 5),
        2 + int(strength * 4),
        7,
        21,
    )
    return cv2.addWeighted(image, 1.0 - strength * 0.45, denoised, strength * 0.45, 0)


def control_fake_hdr(image, strength: float):
    strength = _clamp01(strength)
    if strength <= 0:
        return image

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype("float32")
    value = hsv[:, :, 2]
    saturation = hsv[:, :, 1]

    highlight_mask = value > 205
    saturation[highlight_mask] *= 1.0 - strength * 0.18
    value[highlight_mask] = 205 + (value[highlight_mask] - 205) * (1.0 - strength * 0.22)

    hsv[:, :, 1] = np.clip(saturation, 0, 255)
    hsv[:, :, 2] = np.clip(value, 0, 255)
    return cv2.cvtColor(hsv.astype("uint8"), cv2.COLOR_HSV2BGR)


def soften_electronic_edges(image, strength: float):
    strength = _clamp01(strength)
    if strength <= 0:
        return image

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 90, 190)
    edge_mask = cv2.GaussianBlur(edges, (0, 0), 0.8).astype("float32") / 255.0
    edge_mask = edge_mask[:, :, None] * strength * 0.35
    softened = cv2.bilateralFilter(image, 5, 18, 18)
    return np.clip(image.astype("float32") * (1.0 - edge_mask) + softened.astype("float32") * edge_mask, 0, 255).astype("uint8")


def control_ai_noise(image, analysis, profile, rule_pack: dict | None = None, strategy=None):
    _ = rule_pack
    dirty = getattr(analysis, "ai_dirty_score", 0.35)
    high_frequency = getattr(analysis, "high_frequency_pollution", 0.35)
    highlight = getattr(analysis, "highlight_risk", 0.25)
    strategy_noise = getattr(strategy, "noise_reduction_strength", profile.cleanup_strength)
    strategy_frequency = getattr(strategy, "high_frequency_control_strength", high_frequency)

    strength = _clamp01(max(dirty, high_frequency * 0.82, strategy_noise))
    result = suppress_diffusion_texture(image, strength)
    result = control_fake_hdr(result, _clamp01(highlight * 0.75 + dirty * 0.25))
    result = soften_electronic_edges(result, _clamp01(max(high_frequency, strategy_frequency)))
    return result
