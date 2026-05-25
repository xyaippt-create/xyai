from dataclasses import dataclass

import cv2
import numpy as np

from engine.algorithms import apply_commercial_light, control_ai_noise, restore_commercial_structure


@dataclass(frozen=True)
class PipelineContext:
    """Runtime data shared by mode-specific commercial visual pipelines."""

    analysis: object
    profile: object
    rule_pack: dict
    strategy: object


def clamp01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def apply_foundation(image, context: PipelineContext, include_light: bool = True):
    """Shared base cleanup; each mode adds its own visual language after this."""

    result = control_ai_noise(
        image,
        context.analysis,
        context.profile,
        context.rule_pack,
        context.strategy,
    )
    result = restore_commercial_structure(
        result,
        context.analysis,
        context.profile,
        context.rule_pack,
        context.strategy,
    )
    if include_light:
        result = apply_commercial_light(
            result,
            context.analysis,
            context.profile,
            context.rule_pack,
            context.strategy,
        )
    return result


def soft_glow(image, strength: float, sigma: float = 1.2):
    strength = clamp01(strength)
    glow = cv2.GaussianBlur(image, (0, 0), sigma)
    return cv2.addWeighted(image, 1.0 - strength * 0.22, glow, strength * 0.22, 0)


def tune_saturation(image, factor: float):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype("float32")
    hsv[:, :, 1] *= factor
    hsv[:, :, 1] = np.clip(hsv[:, :, 1], 0, 255)
    return cv2.cvtColor(hsv.astype("uint8"), cv2.COLOR_HSV2BGR)


def warm_highlights(image, strength: float):
    strength = clamp01(strength)
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    light = lab[:, :, 0]
    mask = cv2.GaussianBlur((light > 150).astype("float32"), (0, 0), 4.0)[:, :, None]
    warm = image.astype("float32").copy()
    warm[:, :, 2] += 16 * strength
    warm[:, :, 1] += 5 * strength
    return np.clip(image.astype("float32") * (1.0 - mask * strength) + warm * mask * strength, 0, 255).astype("uint8")


def cool_shadows(image, strength: float):
    strength = clamp01(strength)
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    light = lab[:, :, 0]
    mask = cv2.GaussianBlur((light < 92).astype("float32"), (0, 0), 5.0)[:, :, None]
    cool = image.astype("float32").copy()
    cool[:, :, 0] += 12 * strength
    cool[:, :, 2] -= 6 * strength
    return np.clip(image.astype("float32") * (1.0 - mask * strength) + cool * mask * strength, 0, 255).astype("uint8")


def add_controlled_clarity(image, amount: float, radius: float = 2.0):
    amount = clamp01(amount)
    blur = cv2.GaussianBlur(image, (0, 0), radius)
    return cv2.addWeighted(image, 1.0 + amount * 0.32, blur, -amount * 0.32, 0)


def add_atmosphere(image, strength: float):
    strength = clamp01(strength)
    haze = cv2.GaussianBlur(image, (0, 0), 8.0)
    lifted = cv2.addWeighted(image, 0.82, haze, 0.18, 8)
    return cv2.addWeighted(image, 1.0 - strength * 0.45, lifted, strength * 0.45, 0)


def compress_specular(image, strength: float):
    strength = clamp01(strength)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype("float32")
    value = hsv[:, :, 2]
    mask = value > 210
    value[mask] = 210 + (value[mask] - 210) * (1.0 - strength * 0.45)
    hsv[:, :, 2] = np.clip(value, 0, 255)
    return cv2.cvtColor(hsv.astype("uint8"), cv2.COLOR_HSV2BGR)


def protect_text_edges(image, strength: float):
    strength = clamp01(strength)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 70, 170)
    edge_mask = cv2.GaussianBlur(edges, (0, 0), 0.55).astype("float32") / 255.0
    edge_mask = edge_mask[:, :, None] * strength
    crisp = add_controlled_clarity(image, 0.28, radius=1.0)
    return np.clip(image.astype("float32") * (1.0 - edge_mask) + crisp.astype("float32") * edge_mask, 0, 255).astype("uint8")
