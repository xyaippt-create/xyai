"""Objective, serializable color diagnosis built from the existing D1 facts.

The module deliberately contains no product action and no correction parameter
selection.  It reuses the current color-managed D1 measurements, then gives the
later decision layer stable names for the observed image state and its evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from .usability_decision import ColorObservability, ColorUsabilityDecision


OBJECTIVE_DIAGNOSIS_SCHEMA_VERSION = "hdde.objective-color-diagnosis.v1"
OBJECTIVE_DIAGNOSIS_ENGINE_VERSION = "hdde.d60-03-objective-diagnosis.v1"


class DiagnosisSeverity(str, Enum):
    NONE = "NONE"
    MILD = "MILD"
    MODERATE = "MODERATE"
    STRONG = "STRONG"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class DiagnosticFinding:
    state: str
    severity: DiagnosisSeverity
    confidence: float
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["severity"] = self.severity.value
        return value


@dataclass(frozen=True)
class ObjectiveColorDiagnosis:
    schema_version: str
    engine_version: str
    source_fingerprint: str
    exposure: DiagnosticFinding
    white_balance: DiagnosticFinding
    color_cast: DiagnosticFinding
    brightness_distribution: DiagnosticFinding
    contrast: DiagnosticFinding
    saturation: DiagnosticFinding
    highlights: DiagnosticFinding
    shadows: DiagnosticFinding
    neutral_color_evidence: DiagnosticFinding
    skin_risk: DiagnosticFinding
    scene_risk: DiagnosticFinding
    clipping: DiagnosticFinding
    dynamic_range: DiagnosticFinding
    diagnosis_confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
            "source_fingerprint": self.source_fingerprint,
            "EXPOSURE": self.exposure.to_dict(),
            "WHITE_BALANCE": self.white_balance.to_dict(),
            "COLOR_CAST": self.color_cast.to_dict(),
            "BRIGHTNESS_DISTRIBUTION": self.brightness_distribution.to_dict(),
            "CONTRAST": self.contrast.to_dict(),
            "SATURATION": self.saturation.to_dict(),
            "HIGHLIGHTS": self.highlights.to_dict(),
            "SHADOWS": self.shadows.to_dict(),
            "NEUTRAL_COLOR_EVIDENCE": self.neutral_color_evidence.to_dict(),
            "SKIN_RISK": self.skin_risk.to_dict(),
            "SCENE_RISK": self.scene_risk.to_dict(),
            "CLIPPING": self.clipping.to_dict(),
            "DYNAMIC_RANGE": self.dynamic_range.to_dict(),
            "DIAGNOSIS_CONFIDENCE": self.diagnosis_confidence,
        }


def _bounded_confidence(value: float) -> float:
    return round(float(min(1.0, max(0.0, value))), 4)


def _severity(value: float, mild: float, moderate: float, *, higher_is_worse: bool = True) -> DiagnosisSeverity:
    if higher_is_worse:
        if value >= moderate:
            return DiagnosisSeverity.STRONG
        if value >= mild:
            return DiagnosisSeverity.MODERATE
        return DiagnosisSeverity.MILD
    if value <= moderate:
        return DiagnosisSeverity.STRONG
    if value <= mild:
        return DiagnosisSeverity.MODERATE
    return DiagnosisSeverity.MILD


def build_objective_diagnosis(decision: ColorUsabilityDecision) -> ObjectiveColorDiagnosis:
    """Translate current D1 measurements into an action-free diagnosis.

    D1's legacy ``d1_action`` and correction justification are intentionally
    ignored.  Only measured facts and risk observations enter this contract.
    """

    image = decision.image_facts
    global_facts = decision.global_color_facts
    neutral = decision.neutral_color_facts
    spatial = decision.spatial_color_facts
    skin = decision.skin_color_facts

    p01 = float(image.get("luminance_p01", 0.0))
    p05 = float(image.get("luminance_p05", 0.0))
    p50 = float(image.get("luminance_p50", 0.5))
    p95 = float(image.get("luminance_p95", 1.0))
    p99 = float(image.get("luminance_p99", 1.0))
    mean_luminance = float(image.get("mean_luminance", p50))
    shadow_ratio = float(image.get("shadow_ratio", 0.0))
    shadow_clip = float(image.get("shadow_clip_ratio", 0.0))
    highlight_clip = float(image.get("highlight_clip_ratio", 0.0))
    maximum_color_channel_clip = float(image.get("maximum_color_channel_clip_ratio", 0.0))
    color_clipped_pixel_ratio = float(image.get("color_clipped_pixel_ratio", 0.0))
    dynamic_range = float(image.get("luminance_dynamic_range_p95_p05", p95 - p05))
    valid_ratio = float(image.get("valid_pixel_ratio", 1.0))

    underexposed = mean_luminance < 0.31 and p95 < 0.68 and p50 < 0.30 and shadow_ratio >= 0.30
    overexposed = p05 > 0.58 and p50 > 0.82
    if underexposed:
        exposure_severity = _severity(p50, 0.27, 0.18, higher_is_worse=False)
        exposure_state = "UNDEREXPOSED"
    elif overexposed:
        exposure_severity = _severity(p50, 0.84, 0.90)
        exposure_state = "OVEREXPOSED"
    else:
        exposure_severity = DiagnosisSeverity.NONE
        exposure_state = "ACCEPTABLE"
    exposure = DiagnosticFinding(
        exposure_state,
        exposure_severity,
        _bounded_confidence(0.72 + 0.18 * valid_ratio),
        {
            "luminance_p05": p05,
            "luminance_p50": p50,
            "luminance_p95": p95,
            "mean_luminance": mean_luminance,
            "shadow_ratio": shadow_ratio,
        },
    )

    if p50 < 0.34 and p95 >= 0.68:
        brightness_state = "LOW_MIDTONES"
        brightness_severity = DiagnosisSeverity.MILD if p50 >= 0.27 else DiagnosisSeverity.MODERATE
    elif p50 > 0.76 and p05 <= 0.58:
        brightness_state = "HIGH_MIDTONES"
        brightness_severity = DiagnosisSeverity.MILD if p50 <= 0.82 else DiagnosisSeverity.MODERATE
    else:
        brightness_state = "BALANCED"
        brightness_severity = DiagnosisSeverity.NONE
    brightness = DiagnosticFinding(
        brightness_state,
        brightness_severity,
        _bounded_confidence(0.70 + 0.20 * valid_ratio),
        {"luminance_p05": p05, "luminance_p50": p50, "luminance_p95": p95},
    )

    if dynamic_range < 0.30:
        contrast_state, contrast_severity = "LOW", DiagnosisSeverity.STRONG
    elif dynamic_range < 0.48:
        contrast_state, contrast_severity = "LOW", DiagnosisSeverity.MODERATE
    elif dynamic_range > 0.93:
        contrast_state, contrast_severity = "HIGH", DiagnosisSeverity.STRONG
    elif dynamic_range > 0.86:
        contrast_state, contrast_severity = "HIGH", DiagnosisSeverity.MODERATE
    else:
        contrast_state, contrast_severity = "ACCEPTABLE", DiagnosisSeverity.NONE
    contrast = DiagnosticFinding(
        contrast_state,
        contrast_severity,
        _bounded_confidence(0.76 + 0.14 * valid_ratio),
        {"luminance_p05": p05, "luminance_p95": p95, "dynamic_range_p95_p05": dynamic_range},
    )

    saturation_mean = float(global_facts.get("saturation_mean", 0.0))
    saturation_p50 = float(global_facts.get("saturation_p50", saturation_mean))
    saturation_p90 = float(global_facts.get("saturation_p90", saturation_mean))
    strong_color_ratio = float(global_facts.get("strong_color_ratio", 0.0))
    if saturation_p90 < 0.16:
        saturation_state, saturation_severity = "VERY_LOW_UNIFORM", DiagnosisSeverity.INDETERMINATE
    elif saturation_mean < 0.18 and saturation_p90 < 0.42:
        if strong_color_ratio >= 0.10 or saturation_p90 >= 0.30:
            saturation_state, saturation_severity = "LOW", DiagnosisSeverity.MODERATE
        else:
            saturation_state, saturation_severity = "LOW_AMBIGUOUS", DiagnosisSeverity.INDETERMINATE
    elif (
        saturation_mean > 0.64
        or saturation_p50 > 0.68
        or (saturation_mean > 0.40 and saturation_p90 > 0.84)
    ):
        saturation_state, saturation_severity = "HIGH", DiagnosisSeverity.STRONG
    elif saturation_mean > 0.48 or saturation_p50 > 0.54:
        saturation_state, saturation_severity = "HIGH", DiagnosisSeverity.MODERATE
    else:
        saturation_state, saturation_severity = "ACCEPTABLE", DiagnosisSeverity.NONE
    saturation = DiagnosticFinding(
        saturation_state,
        saturation_severity,
        _bounded_confidence(0.75 + 0.15 * valid_ratio),
        {
            "saturation_mean": saturation_mean,
            "saturation_p50": saturation_p50,
            "saturation_p90": saturation_p90,
            "strong_color_ratio": strong_color_ratio,
        },
    )

    if highlight_clip >= 0.08:
        highlight_state = "CLIPPED"
        highlight_severity = _severity(highlight_clip, 0.08, 0.18)
    elif highlight_clip >= 0.015:
        highlight_state, highlight_severity = "AT_RISK", DiagnosisSeverity.MILD
    else:
        highlight_state, highlight_severity = "ACCEPTABLE", DiagnosisSeverity.NONE
    highlights = DiagnosticFinding(
        highlight_state,
        highlight_severity,
        _bounded_confidence(0.78 + 0.12 * valid_ratio),
        {"luminance_p95": p95, "luminance_p99": p99, "highlight_clip_ratio": highlight_clip},
    )

    if shadow_clip >= 0.12:
        shadow_state = "CRUSHED"
        shadow_severity = _severity(shadow_clip, 0.12, 0.28)
    elif shadow_clip >= 0.025:
        shadow_state, shadow_severity = "AT_RISK", DiagnosisSeverity.MILD
    else:
        shadow_state, shadow_severity = "ACCEPTABLE", DiagnosisSeverity.NONE
    shadows = DiagnosticFinding(
        shadow_state,
        shadow_severity,
        _bounded_confidence(0.78 + 0.12 * valid_ratio),
        {"luminance_p01": p01, "luminance_p05": p05, "shadow_clip_ratio": shadow_clip},
    )

    neutral_ratio = float(neutral.get("pixel_ratio", 0.0))
    neutral_a = float(neutral.get("median_lab_a", 0.0))
    neutral_b = float(neutral.get("median_lab_b", 0.0))
    neutral_chroma = float(neutral.get("median_chroma", 0.0))
    eligible_cells = int(spatial.get("eligible_cell_count", 0))
    field_status = str(spatial.get("field_status", "UNKNOWN"))
    boundary_unstable = bool(decision.color_appearance_evidence.get("boundary_unstable"))
    if boundary_unstable:
        neutral_state = "UNSTABLE"
    elif field_status == "MIXED":
        neutral_state = "MIXED_FIELD"
    elif neutral_ratio >= 0.025 and eligible_cells >= 3:
        neutral_state = "SUFFICIENT"
    else:
        neutral_state = "INSUFFICIENT"
    neutral_confidence = {
        ColorObservability.HIGH: 0.92,
        ColorObservability.MEDIUM: 0.76,
        ColorObservability.LOW: 0.34,
    }[decision.color_observability]
    neutral_finding = DiagnosticFinding(
        neutral_state,
        DiagnosisSeverity.NONE if neutral_state == "SUFFICIENT" else DiagnosisSeverity.INDETERMINATE,
        _bounded_confidence(neutral_confidence),
        {
            "pixel_ratio": neutral_ratio,
            "median_lab_a": neutral_a,
            "median_lab_b": neutral_b,
            "median_chroma": neutral_chroma,
            "eligible_spatial_cells": eligible_cells,
            "spatial_field": field_status,
            "quantization_boundary_unstable": boundary_unstable,
        },
    )

    appearance = str(decision.color_appearance_evidence.get("direction", "UNKNOWN"))
    if appearance == "OTHER":
        wb_state = "MAGENTA" if neutral_a > 0.0 else "GREEN"
        wb_axis = abs(neutral_a)
    elif appearance in {"WARM", "COOL"}:
        wb_state = appearance
        wb_axis = abs(neutral_b)
    elif appearance == "NEUTRAL":
        wb_state, wb_axis = "NEUTRAL", neutral_chroma
    elif appearance == "MIXED":
        wb_state, wb_axis = "MIXED", neutral_chroma
    else:
        wb_state, wb_axis = "UNKNOWN", neutral_chroma
    if wb_state == "NEUTRAL":
        wb_severity = DiagnosisSeverity.NONE
    elif wb_state in {"UNKNOWN", "MIXED"} or neutral_state != "SUFFICIENT":
        wb_severity = DiagnosisSeverity.INDETERMINATE
    elif wb_axis >= 14.0:
        wb_severity = DiagnosisSeverity.STRONG
    elif wb_axis >= 8.0:
        wb_severity = DiagnosisSeverity.MODERATE
    else:
        wb_severity = DiagnosisSeverity.MILD
    wb_confidence = neutral_confidence if neutral_state == "SUFFICIENT" else min(0.49, neutral_confidence)
    white_balance = DiagnosticFinding(
        wb_state,
        wb_severity,
        _bounded_confidence(wb_confidence),
        {
            "neutral_lab_a": neutral_a,
            "neutral_lab_b": neutral_b,
            "neutral_chroma": neutral_chroma,
            "neutral_evidence_state": neutral_state,
            "spatial_direction_consistency": float(spatial.get("direction_consistency", 0.0)),
        },
    )
    color_cast = DiagnosticFinding(
        (
            "UNIFORM_DIRECTIONAL_APPEARANCE"
            if wb_state in {"WARM", "COOL", "GREEN", "MAGENTA"} and field_status == "UNIFORM"
            else "MIXED_DIRECTIONAL_APPEARANCE"
            if field_status == "MIXED"
            else "NO_DIRECTIONAL_CAST_OBSERVED"
            if wb_state == "NEUTRAL"
            else "UNRESOLVED"
        ),
        wb_severity,
        _bounded_confidence(wb_confidence),
        {"direction": wb_state, "spatial_field": field_status, "neutral_evidence_state": neutral_state},
    )

    local_skin_color = bool(skin.get("local_person_color_risk"))
    local_skin_exposure = bool(skin.get("local_person_exposure_risk"))
    person_present = bool(skin.get("person_present"))
    if local_skin_color or local_skin_exposure:
        skin_state, skin_severity = "HIGH", DiagnosisSeverity.STRONG
    elif person_present:
        skin_state, skin_severity = "MEDIUM", DiagnosisSeverity.MODERATE
    else:
        skin_state, skin_severity = "LOW", DiagnosisSeverity.NONE
    skin_risk = DiagnosticFinding(
        skin_state,
        skin_severity,
        0.9 if skin_state == "HIGH" else 0.72 if skin_state == "MEDIUM" else 0.8,
        {
            "person_present": person_present,
            "local_person_color_risk": local_skin_color,
            "local_person_exposure_risk": local_skin_exposure,
            "trusted_skin_pixel_ratio": float(skin.get("trusted_skin_pixel_ratio", 0.0)),
        },
    )

    scene_intent = str(decision.scene_intent)
    if scene_intent == "GENERAL" and p50 > 0.82 and p95 > 0.97:
        scene_intent = "PROBABLE_HIGH_KEY_OR_BACKLIGHT"
    high_risk_intents = {
        "MIXED_LIGHT",
        "LEGITIMATE_DARK",
        "LEGITIMATE_HIGH_KEY",
        "LEGITIMATE_WARM",
        "LEGITIMATE_COOL",
        "DOMINANT_COLOR_DESIGN",
        "LOCAL_PERSON_COLOR_RISK",
        "PROBABLE_HIGH_KEY_OR_BACKLIGHT",
    }
    directional_neutral_cast = bool(
        neutral_state == "SUFFICIENT"
        and field_status == "UNIFORM"
        and wb_state in {"WARM", "COOL", "GREEN", "MAGENTA"}
    )
    if (
        scene_intent in high_risk_intents
        and not (scene_intent == "DOMINANT_COLOR_DESIGN" and directional_neutral_cast)
    ) or (
        scene_intent == "GENERAL"
        and decision.dominant_color_risk == "MEDIUM"
        and not directional_neutral_cast
    ):
        scene_state, scene_severity = "HIGH", DiagnosisSeverity.STRONG
    elif (
        scene_intent == "PERSON_SCENE"
        or decision.dominant_color_risk == "MEDIUM"
        or (scene_intent == "DOMINANT_COLOR_DESIGN" and directional_neutral_cast)
    ):
        scene_state, scene_severity = "MEDIUM", DiagnosisSeverity.MODERATE
    else:
        scene_state, scene_severity = "LOW", DiagnosisSeverity.NONE
    scene_risk = DiagnosticFinding(
        scene_state,
        scene_severity,
        0.86,
        {
            "scene_intent": scene_intent,
            "dominant_color_risk": decision.dominant_color_risk,
            "spatial_field": field_status,
        },
    )

    combined_clip = shadow_clip + highlight_clip
    effective_clip = max(combined_clip, maximum_color_channel_clip, color_clipped_pixel_ratio)
    if effective_clip >= 0.35:
        clip_state, clip_severity = "SEVERE", DiagnosisSeverity.STRONG
    elif effective_clip >= 0.12:
        clip_state, clip_severity = "ELEVATED", DiagnosisSeverity.MODERATE
    elif effective_clip >= 0.025:
        clip_state, clip_severity = "MILD", DiagnosisSeverity.MILD
    else:
        clip_state, clip_severity = "ACCEPTABLE", DiagnosisSeverity.NONE
    clipping = DiagnosticFinding(
        clip_state,
        clip_severity,
        _bounded_confidence(0.82 + 0.10 * valid_ratio),
        {
            "shadow_clip_ratio": shadow_clip,
            "highlight_clip_ratio": highlight_clip,
            "combined_clip_ratio": combined_clip,
            "maximum_color_channel_clip_ratio": maximum_color_channel_clip,
            "color_clipped_pixel_ratio": color_clipped_pixel_ratio,
        },
    )
    if dynamic_range < 0.22:
        range_state, range_severity = "COMPRESSED", DiagnosisSeverity.STRONG
    elif dynamic_range < 0.34:
        range_state, range_severity = "NARROW", DiagnosisSeverity.MODERATE
    elif dynamic_range > 0.82:
        range_state, range_severity = "EXTREME", DiagnosisSeverity.STRONG
    else:
        range_state, range_severity = "ACCEPTABLE", DiagnosisSeverity.NONE
    dynamic_range_finding = DiagnosticFinding(
        range_state,
        range_severity,
        _bounded_confidence(0.80 + 0.10 * valid_ratio),
        {"p05": p05, "p95": p95, "p95_minus_p05": dynamic_range},
    )

    confidence = _bounded_confidence(
        0.30 * exposure.confidence
        + 0.25 * contrast.confidence
        + 0.20 * saturation.confidence
        + 0.25 * neutral_finding.confidence
    )
    return ObjectiveColorDiagnosis(
        OBJECTIVE_DIAGNOSIS_SCHEMA_VERSION,
        OBJECTIVE_DIAGNOSIS_ENGINE_VERSION,
        decision.source_fingerprint,
        exposure,
        white_balance,
        color_cast,
        brightness,
        contrast,
        saturation,
        highlights,
        shadows,
        neutral_finding,
        skin_risk,
        scene_risk,
        clipping,
        dynamic_range_finding,
        confidence,
    )


__all__ = [
    "OBJECTIVE_DIAGNOSIS_SCHEMA_VERSION",
    "OBJECTIVE_DIAGNOSIS_ENGINE_VERSION",
    "DiagnosisSeverity",
    "DiagnosticFinding",
    "ObjectiveColorDiagnosis",
    "build_objective_diagnosis",
]
