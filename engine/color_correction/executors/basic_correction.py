"""Deterministic nine-control pixel executor for HDDE basic color correction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from ..parameters import CORRECTION_EXECUTION_ORDER, CorrectionParameters


BASIC_CORRECTION_EXECUTOR_VERSION = "hdde.basic-color-executor.v1"

# Authoritative effect constants. Parameter ranges and public semantics live in
# parameters.py; implementation magnitudes live here and nowhere else.
_BRIGHTNESS_LSTAR_LIMIT = 18.0
_CONTRAST_CURVE_LIMIT = 0.50
_TEMPERATURE_LAB_B_LIMIT = 10.0
_TINT_LAB_A_LIMIT = 8.0
_HIGHLIGHT_LSTAR_LIMIT = 25.0
_SHADOW_LSTAR_LIMIT = 25.0
_SATURATION_POSITIVE_LIMIT = 0.65
_VIBRANCE_POSITIVE_LIMIT = 0.80
_VISIBLE_ALPHA_THRESHOLD = 0
_RGB_CLIP_LOW = 1.0 / 255.0
_RGB_CLIP_HIGH = 254.0 / 255.0
# Stay strictly inside the uint8 rounding cells for values 2 and 253. Merely
# landing on 1/255 or 254/255 would still create a newly clipped output sample.
_RGB_SAFE_LOW = 1.501 / 255.0
_RGB_SAFE_HIGH = 253.499 / 255.0
_MAX_NEW_CLIP_RATIO = 0.002
_MAX_TONE_ONLY_MEDIAN_AB_DRIFT = 0.75


class BasicCorrectionSafetyError(ValueError):
    """Fail-closed execution error with machine-readable safety evidence."""

    def __init__(
        self,
        violations: tuple[str, ...],
        metrics: dict[str, Any] | None = None,
    ) -> None:
        self.violations = tuple(violations)
        self.metrics = dict(metrics or {})
        super().__init__("BASIC_CORRECTION_SAFETY_BLOCKED:" + ",".join(self.violations))


@dataclass(frozen=True)
class BasicCorrectionResult:
    executor_version: str
    candidate_image: np.ndarray
    parameter_record: dict[str, Any]
    execution_order: tuple[str, ...]
    metrics: dict[str, Any]
    safety_status: str
    violations: tuple[str, ...]

    @property
    def modified(self) -> bool:
        return bool(self.metrics.get("changed_pixel_count", 0))

    def to_record(self) -> dict[str, Any]:
        return {
            "executor_version": self.executor_version,
            "parameters": dict(self.parameter_record),
            "execution_order": list(self.execution_order),
            "metrics": dict(self.metrics),
            "safety_status": self.safety_status,
            "violations": list(self.violations),
            "candidate_available": True,
        }


def _smoothstep(value: np.ndarray) -> np.ndarray:
    bounded = np.clip(value, 0.0, 1.0)
    return bounded * bounded * (3.0 - 2.0 * bounded)


def _srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    return np.where(
        rgb <= 0.04045,
        rgb / 12.92,
        np.power((rgb + 0.055) / 1.055, 2.4),
    )


def _linear_to_srgb(rgb: np.ndarray) -> np.ndarray:
    return np.where(
        rgb <= 0.0031308,
        rgb * 12.92,
        1.055 * np.power(np.maximum(rgb, 0.0), 1.0 / 2.4) - 0.055,
    )


def _lab(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(np.ascontiguousarray(rgb, dtype=np.float32), cv2.COLOR_RGB2LAB)


def _rgb(lab: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(np.ascontiguousarray(lab, dtype=np.float32), cv2.COLOR_LAB2RGB)


def white_balance_controls_for_lab_shift(
    *,
    delta_a: float,
    delta_b: float,
    strength: float,
) -> tuple[float, float]:
    """Map an explicit Lab correction request to the executor's WB controls.

    This is a unit conversion only. It performs no image diagnosis and keeps
    the Temperature/Tint effect limits next to the sole pixel primitive.
    """

    values = np.asarray((delta_a, delta_b, strength), dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError("white-balance control conversion requires finite values")
    if strength < 0.0 or strength > 1.0:
        raise ValueError("white-balance control strength must be within 0..1")
    temperature = float(delta_b) * float(strength) * 100.0 / _TEMPERATURE_LAB_B_LIMIT
    tint = float(delta_a) * float(strength) * 100.0 / _TINT_LAB_A_LIMIT
    bounded = CorrectionParameters(temperature=temperature, tint=tint)
    return bounded.temperature, bounded.tint


def _apply_exposure(rgb: np.ndarray, exposure_ev: float) -> np.ndarray:
    if exposure_ev == 0.0:
        return rgb
    linear = _srgb_to_linear(rgb)
    gain = float(2.0**exposure_ev)
    if exposure_ev > 0.0:
        # A normalized shoulder retains the 2^EV mid-tone direction without
        # turning pre-existing white detail into a larger clipped region.
        proposed = gain * linear / (1.0 + (gain - 1.0) * linear)
    else:
        proposed = linear * gain
    return np.clip(_linear_to_srgb(proposed), 0.0, 1.0)


def _apply_white_balance(lab: np.ndarray, temperature: float, tint: float) -> np.ndarray:
    if temperature == 0.0 and tint == 0.0:
        return lab
    output = lab.copy()
    lightness01 = np.clip(output[..., 0] / 100.0, 0.0, 1.0)
    endpoint_weight = np.maximum(np.sin(np.pi * lightness01), 0.0) ** 0.35
    if temperature != 0.0:
        output[..., 2] += (
            temperature / 100.0 * _TEMPERATURE_LAB_B_LIMIT * endpoint_weight
        )
    if tint != 0.0:
        output[..., 1] += tint / 100.0 * _TINT_LAB_A_LIMIT * endpoint_weight
    output[..., 1:3] = np.clip(output[..., 1:3], -127.0, 127.0)
    return output


def _apply_brightness(lightness: np.ndarray, brightness: float) -> np.ndarray:
    if brightness == 0.0:
        return lightness
    value = np.clip(lightness / 100.0, 0.0, 1.0)
    endpoint_weight = np.maximum(np.sin(np.pi * value), 0.0) ** 0.45
    delta = brightness / 100.0 * _BRIGHTNESS_LSTAR_LIMIT * endpoint_weight
    return np.clip(lightness + delta, 0.0, 100.0)


def _apply_contrast(lightness: np.ndarray, contrast: float) -> np.ndarray:
    if contrast == 0.0:
        return lightness
    value = np.clip(lightness / 100.0, 0.0, 1.0)
    strength = contrast / 100.0 * _CONTRAST_CURVE_LIMIT
    curved = value + strength * 4.0 * value * (1.0 - value) * (value - 0.5)
    return np.clip(curved * 100.0, 0.0, 100.0)


def _apply_highlights(lightness: np.ndarray, highlights: float) -> np.ndarray:
    if highlights == 0.0:
        return lightness
    value = np.clip(lightness / 100.0, 0.0, 1.0)
    weight = _smoothstep((value - 0.50) / 0.50)
    amount = highlights / 100.0
    if amount > 0.0:
        proposed = value + amount * (_HIGHLIGHT_LSTAR_LIMIT / 100.0) * weight * (1.0 - value)
    else:
        proposed = value + amount * (_HIGHLIGHT_LSTAR_LIMIT / 100.0) * weight * value
    return np.clip(proposed * 100.0, 0.0, 100.0)


def _apply_shadows(lightness: np.ndarray, shadows: float) -> np.ndarray:
    if shadows == 0.0:
        return lightness
    value = np.clip(lightness / 100.0, 0.0, 1.0)
    weight = 1.0 - _smoothstep(value / 0.50)
    amount = shadows / 100.0
    if amount > 0.0:
        proposed = value + amount * (_SHADOW_LSTAR_LIMIT / 100.0) * weight * (1.0 - value)
    else:
        proposed = value + amount * (_SHADOW_LSTAR_LIMIT / 100.0) * weight * value
    return np.clip(proposed * 100.0, 0.0, 100.0)


def _apply_saturation(rgb: np.ndarray, saturation: float) -> np.ndarray:
    if saturation == 0.0:
        return rgb
    source_lab = _lab(rgb)
    if saturation > 0.0:
        factor = 1.0 + saturation / 100.0 * _SATURATION_POSITIVE_LIMIT
    else:
        factor = 1.0 + saturation / 100.0
    source_lab[..., 1:3] *= factor
    source_lab[..., 1:3] = np.clip(source_lab[..., 1:3], -127.0, 127.0)
    return np.clip(_rgb(source_lab), 0.0, 1.0)


def _apply_vibrance(rgb: np.ndarray, vibrance: float) -> np.ndarray:
    if vibrance == 0.0:
        return rgb
    source_lab = _lab(rgb)
    chroma = np.linalg.norm(source_lab[..., 1:3], axis=2)
    normalized_chroma = np.clip(chroma / 80.0, 0.0, 1.0)
    low_saturation_weight = np.power(1.0 - normalized_chroma, 1.5)
    if vibrance > 0.0:
        factor = 1.0 + vibrance / 100.0 * _VIBRANCE_POSITIVE_LIMIT * low_saturation_weight
    else:
        reduction = (-vibrance / 100.0) * (0.65 + 0.35 * low_saturation_weight)
        factor = np.clip(1.0 - reduction, 0.0, 1.0)
    source_lab[..., 1] *= factor
    source_lab[..., 2] *= factor
    source_lab[..., 1:3] = np.clip(source_lab[..., 1:3], -127.0, 127.0)
    return np.clip(_rgb(source_lab), 0.0, 1.0)


def _prevent_new_channel_clipping(source: np.ndarray, proposed: np.ndarray) -> np.ndarray:
    """Bound the source-to-result vector before final uint8 quantisation."""

    delta = proposed - source
    scale = np.ones(source.shape[:2], dtype=np.float64)
    for channel in range(3):
        source_channel = source[..., channel]
        delta_channel = delta[..., channel]
        rising = delta_channel > 0.0
        falling = delta_channel < 0.0
        rising_limit = np.ones_like(source_channel)
        falling_limit = np.ones_like(source_channel)
        rising_limit[rising] = (
            (_RGB_SAFE_HIGH - source_channel[rising]) / delta_channel[rising]
        )
        falling_limit[falling] = (
            (_RGB_SAFE_LOW - source_channel[falling]) / delta_channel[falling]
        )
        # Existing endpoint pixels may move inward but may never be pushed
        # farther out of gamut.
        rising_limit[rising & (source_channel >= _RGB_CLIP_HIGH)] = 0.0
        falling_limit[falling & (source_channel <= _RGB_CLIP_LOW)] = 0.0
        scale = np.minimum(scale, np.clip(rising_limit, 0.0, 1.0))
        scale = np.minimum(scale, np.clip(falling_limit, 0.0, 1.0))
    return np.clip(source + delta * scale[..., None], 0.0, 1.0)


def _clip_metrics(rgb: np.ndarray, visible: np.ndarray) -> dict[str, float]:
    selected = rgb[visible]
    return {
        "channel_low_clip_ratio": float((selected <= _RGB_CLIP_LOW).mean()),
        "channel_high_clip_ratio": float((selected >= _RGB_CLIP_HIGH).mean()),
        "shadow_clip_ratio": float((np.max(selected, axis=1) <= _RGB_CLIP_LOW).mean()),
        "highlight_clip_ratio": float((np.max(selected, axis=1) >= _RGB_CLIP_HIGH).mean()),
    }


def execute_basic_correction(
    image: np.ndarray,
    parameters: CorrectionParameters,
    *,
    input_order: str = "RGB",
) -> BasicCorrectionResult:
    """Apply explicit parameters without diagnosis or hidden enhancement."""

    if not isinstance(parameters, CorrectionParameters):
        raise TypeError("parameters must be CorrectionParameters")
    source_array = np.asarray(image)
    if source_array.ndim != 3 or source_array.shape[2] not in {3, 4}:
        raise ValueError("basic correction expects RGB/BGR or RGBA/BGRA pixels")
    if source_array.dtype != np.uint8:
        raise TypeError("basic correction supports uint8 managed-color pixels only")
    order = str(input_order).upper()
    if order not in {"RGB", "BGR"}:
        raise ValueError("input_order must be RGB or BGR")

    source = np.ascontiguousarray(source_array)
    source_color = source[..., :3]
    source_rgb = source_color[..., ::-1] if order == "BGR" else source_color
    source_rgb01 = source_rgb.astype(np.float64) / 255.0
    alpha = source[..., 3].copy() if source.shape[2] == 4 else None
    visible = (
        np.ones(source.shape[:2], dtype=bool)
        if alpha is None
        else alpha > _VISIBLE_ALPHA_THRESHOLD
    )
    if not visible.any():
        raise ValueError("basic correction requires at least one visible pixel")

    if parameters.is_neutral:
        candidate = source.copy()
        candidate_rgb01 = source_rgb01.copy()
    else:
        working = _apply_exposure(source_rgb01, parameters.exposure)
        working_lab = _apply_white_balance(
            _lab(working),
            parameters.temperature,
            parameters.tint,
        )
        working_lab[..., 0] = _apply_brightness(
            working_lab[..., 0],
            parameters.brightness,
        )
        working_lab[..., 0] = _apply_contrast(
            working_lab[..., 0],
            parameters.contrast,
        )
        working_lab[..., 0] = _apply_highlights(
            working_lab[..., 0],
            parameters.highlights,
        )
        working_lab[..., 0] = _apply_shadows(
            working_lab[..., 0],
            parameters.shadows,
        )
        working = np.clip(_rgb(working_lab), 0.0, 1.0)
        working = _apply_saturation(working, parameters.saturation)
        working = _apply_vibrance(working, parameters.vibrance)
        candidate_rgb01 = _prevent_new_channel_clipping(source_rgb01, working)
        quantized_rgb = np.clip(np.rint(candidate_rgb01 * 255.0), 0.0, 255.0).astype(np.uint8)
        if alpha is not None:
            transparent = alpha == 0
            quantized_rgb[transparent] = source_rgb[transparent]
        restored_color = quantized_rgb[..., ::-1] if order == "BGR" else quantized_rgb
        candidate = (
            np.dstack((restored_color, alpha))
            if alpha is not None
            else restored_color
        )
        candidate = np.ascontiguousarray(candidate)
        candidate_rgb01 = quantized_rgb.astype(np.float64) / 255.0

    source_clips = _clip_metrics(source_rgb01, visible)
    candidate_clips = _clip_metrics(candidate_rgb01, visible)
    source_lab = _lab(source_rgb01)
    candidate_lab = _lab(candidate_rgb01)
    changed = np.any(candidate != source, axis=2)
    alpha_unchanged = alpha is None or np.array_equal(candidate[..., 3], alpha)
    metrics: dict[str, Any] = {
        "dtype": str(candidate.dtype),
        "dimensions": [int(candidate.shape[1]), int(candidate.shape[0])],
        "channels": int(candidate.shape[2]),
        "finite": bool(np.isfinite(candidate_rgb01).all()),
        "channel_min": round(float(candidate_rgb01.min(initial=0.0)), 8),
        "channel_max": round(float(candidate_rgb01.max(initial=0.0)), 8),
        "alpha_unchanged": bool(alpha_unchanged),
        "changed_pixel_count": int(changed.sum()),
        "changed_pixel_ratio": round(float(changed.mean()), 8),
        "maximum_channel_delta": round(
            float(np.abs(candidate_rgb01 - source_rgb01).max(initial=0.0)),
            8,
        ),
        "mean_lstar_before": round(float(source_lab[..., 0][visible].mean()), 6),
        "mean_lstar_after": round(float(candidate_lab[..., 0][visible].mean()), 6),
        "median_lab_a_shift": round(
            float(np.median(candidate_lab[..., 1][visible] - source_lab[..., 1][visible])),
            6,
        ),
        "median_lab_b_shift": round(
            float(np.median(candidate_lab[..., 2][visible] - source_lab[..., 2][visible])),
            6,
        ),
        "source_clipping": {name: round(value, 8) for name, value in source_clips.items()},
        "candidate_clipping": {name: round(value, 8) for name, value in candidate_clips.items()},
        "new_channel_low_clip_ratio": round(
            max(0.0, candidate_clips["channel_low_clip_ratio"] - source_clips["channel_low_clip_ratio"]),
            8,
        ),
        "new_channel_high_clip_ratio": round(
            max(0.0, candidate_clips["channel_high_clip_ratio"] - source_clips["channel_high_clip_ratio"]),
            8,
        ),
        "shadow_clip_growth": round(
            candidate_clips["shadow_clip_ratio"] - source_clips["shadow_clip_ratio"],
            8,
        ),
        "highlight_clip_growth": round(
            candidate_clips["highlight_clip_ratio"] - source_clips["highlight_clip_ratio"],
            8,
        ),
        "hidden_enhancements": [],
    }

    violations: list[str] = []
    if candidate.shape != source.shape:
        violations.append("DIMENSIONS_CHANGED")
    if candidate.dtype != source.dtype:
        violations.append("DTYPE_CHANGED")
    if not alpha_unchanged:
        violations.append("ALPHA_CHANGED")
    if not metrics["finite"]:
        violations.append("NON_FINITE_OUTPUT")
    if metrics["channel_min"] < 0.0 or metrics["channel_max"] > 1.0:
        violations.append("CHANNEL_OUT_OF_RANGE")
    if metrics["new_channel_low_clip_ratio"] > _MAX_NEW_CLIP_RATIO:
        violations.append("CHANNEL_LOW_CLIP_GROWTH")
    if metrics["new_channel_high_clip_ratio"] > _MAX_NEW_CLIP_RATIO:
        violations.append("CHANNEL_HIGH_CLIP_GROWTH")
    if metrics["shadow_clip_growth"] > _MAX_NEW_CLIP_RATIO:
        violations.append("SHADOW_CRUSH_GROWTH")
    if metrics["highlight_clip_growth"] > _MAX_NEW_CLIP_RATIO:
        violations.append("HIGHLIGHT_CLIP_GROWTH")
    if parameters.is_neutral and not np.array_equal(candidate, source):
        violations.append("NEUTRAL_PIXEL_DRIFT")
    if (
        parameters.temperature == 0.0
        and parameters.tint == 0.0
        and parameters.saturation == 0.0
        and parameters.vibrance == 0.0
        and (
            abs(float(metrics["median_lab_a_shift"])) > _MAX_TONE_ONLY_MEDIAN_AB_DRIFT
            or abs(float(metrics["median_lab_b_shift"])) > _MAX_TONE_ONLY_MEDIAN_AB_DRIFT
        )
    ):
        violations.append("UNEXPECTED_GLOBAL_COLOR_CAST")
    if violations:
        raise BasicCorrectionSafetyError(tuple(violations), metrics)

    return BasicCorrectionResult(
        BASIC_CORRECTION_EXECUTOR_VERSION,
        candidate,
        parameters.to_record(),
        CORRECTION_EXECUTION_ORDER,
        metrics,
        "PASS",
        (),
    )


__all__ = [
    "BASIC_CORRECTION_EXECUTOR_VERSION",
    "BasicCorrectionResult",
    "BasicCorrectionSafetyError",
    "execute_basic_correction",
    "white_balance_controls_for_lab_shift",
]
