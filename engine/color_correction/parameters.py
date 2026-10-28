"""Serializable parameter contract for the deterministic HDDE color executor.

This module contains no image diagnosis or automatic parameter-selection logic.
Every value is an explicit caller decision and is clamped once at the contract
boundary before it can reach the pixel executor.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from math import isfinite
from numbers import Real
from typing import Any, Mapping


CORRECTION_PARAMETERS_SCHEMA_VERSION = "hdde.correction-parameters.v1"
CORRECTION_WORKING_COLOR_SPACE = "sRGB IEC61966-2.1"
CORRECTION_EXECUTION_ORDER = (
    "exposure",
    "temperature",
    "tint",
    "brightness",
    "contrast",
    "highlights",
    "shadows",
    "saturation",
    "vibrance",
)


@dataclass(frozen=True)
class ParameterSpec:
    minimum: float
    maximum: float
    neutral: float
    unit: str
    semantic: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "minimum": self.minimum,
            "maximum": self.maximum,
            "neutral": self.neutral,
            "unit": self.unit,
            "semantic": self.semantic,
        }


PARAMETER_SPECS: dict[str, ParameterSpec] = {
    "exposure": ParameterSpec(
        -2.0,
        2.0,
        0.0,
        "EV",
        "Linear-light exposure gain; positive is brighter and negative is darker.",
    ),
    "brightness": ParameterSpec(
        -100.0,
        100.0,
        0.0,
        "percent",
        "Perceptual L* brightness offset with endpoint protection.",
    ),
    "contrast": ParameterSpec(
        -100.0,
        100.0,
        0.0,
        "percent",
        "Endpoint-preserving contrast around fixed perceptual mid-grey.",
    ),
    "temperature": ParameterSpec(
        -100.0,
        100.0,
        0.0,
        "percent",
        "Blue-to-yellow white-balance axis; positive is warmer.",
    ),
    "tint": ParameterSpec(
        -100.0,
        100.0,
        0.0,
        "percent",
        "Green-to-magenta white-balance axis; positive is magenta.",
    ),
    "saturation": ParameterSpec(
        -100.0,
        100.0,
        0.0,
        "percent",
        "Uniform perceptual chroma scaling.",
    ),
    "vibrance": ParameterSpec(
        -100.0,
        100.0,
        0.0,
        "percent",
        "Chroma scaling weighted toward low-saturation colors.",
    ),
    "highlights": ParameterSpec(
        -100.0,
        100.0,
        0.0,
        "percent",
        "Perceptual luminance control concentrated above mid-grey.",
    ),
    "shadows": ParameterSpec(
        -100.0,
        100.0,
        0.0,
        "percent",
        "Perceptual luminance control concentrated below mid-grey.",
    ),
}


def parameter_contract() -> dict[str, dict[str, Any]]:
    """Return a JSON-safe copy of the authoritative parameter definitions."""

    return {name: PARAMETER_SPECS[name].to_dict() for name in PARAMETER_SPECS}


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a finite number")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _clamp(name: str, value: object) -> float:
    number = _finite_number(name, value)
    spec = PARAMETER_SPECS[name]
    clamped = min(spec.maximum, max(spec.minimum, number))
    return 0.0 if clamped == 0.0 else float(clamped)


@dataclass(frozen=True)
class CorrectionParameters:
    """Nine explicit, bounded controls consumed by the basic executor.

    Direct construction and ``from_mapping`` clamp finite values to the public
    range. ``from_record`` is intentionally strict: a recorded D2 contract must
    already contain valid applied values and may not be silently repaired by D3.
    """

    exposure: float = 0.0
    brightness: float = 0.0
    contrast: float = 0.0
    temperature: float = 0.0
    tint: float = 0.0
    saturation: float = 0.0
    vibrance: float = 0.0
    highlights: float = 0.0
    shadows: float = 0.0

    def __post_init__(self) -> None:
        for item in fields(self):
            object.__setattr__(self, item.name, _clamp(item.name, getattr(self, item.name)))

    @classmethod
    def from_mapping(cls, values: Mapping[str, object] | None = None) -> "CorrectionParameters":
        supplied = dict(values or {})
        unknown = set(supplied) - set(PARAMETER_SPECS)
        if unknown:
            raise ValueError("unknown correction parameters: " + ",".join(sorted(unknown)))
        return cls(**{name: supplied.get(name, 0.0) for name in PARAMETER_SPECS})

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "CorrectionParameters":
        if not isinstance(record, Mapping):
            raise TypeError("correction parameter record must be a mapping")
        if record.get("schema_version") != CORRECTION_PARAMETERS_SCHEMA_VERSION:
            raise ValueError("unsupported correction parameter schema")
        if record.get("working_color_space") != CORRECTION_WORKING_COLOR_SPACE:
            raise ValueError("correction working color space mismatch")
        if tuple(record.get("execution_order") or ()) != CORRECTION_EXECUTION_ORDER:
            raise ValueError("correction execution order mismatch")
        if record.get("contract") != parameter_contract():
            raise ValueError("correction parameter definitions mismatch")
        values = record.get("values")
        if not isinstance(values, Mapping) or set(values) != set(PARAMETER_SPECS):
            raise ValueError("correction parameter values are incomplete")
        strict_values: dict[str, float] = {}
        for name, spec in PARAMETER_SPECS.items():
            number = _finite_number(name, values[name])
            if number < spec.minimum or number > spec.maximum:
                raise ValueError(f"recorded {name} is out of range")
            strict_values[name] = number
        return cls(**strict_values)

    @property
    def is_neutral(self) -> bool:
        return all(getattr(self, name) == PARAMETER_SPECS[name].neutral for name in PARAMETER_SPECS)

    def values(self) -> dict[str, float]:
        return {name: float(getattr(self, name)) for name in PARAMETER_SPECS}

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": CORRECTION_PARAMETERS_SCHEMA_VERSION,
            "working_color_space": CORRECTION_WORKING_COLOR_SPACE,
            "execution_order": list(CORRECTION_EXECUTION_ORDER),
            "values": self.values(),
            "contract": parameter_contract(),
        }


__all__ = [
    "CORRECTION_PARAMETERS_SCHEMA_VERSION",
    "CORRECTION_WORKING_COLOR_SPACE",
    "CORRECTION_EXECUTION_ORDER",
    "PARAMETER_SPECS",
    "ParameterSpec",
    "CorrectionParameters",
    "parameter_contract",
]
