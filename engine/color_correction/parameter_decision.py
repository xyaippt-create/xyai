"""Explainable D60-03 diagnosis-to-parameter decision layer.

This module never reads or writes pixels.  It converts one source-bound
objective diagnosis into the frozen nine-control ``CorrectionParameters``
contract and records a reason for every active and neutral control.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .objective_diagnosis import DiagnosisSeverity, ObjectiveColorDiagnosis
from .parameters import PARAMETER_SPECS, CorrectionParameters


PARAMETER_DECISION_SCHEMA_VERSION = "hdde.parameter-decision.v1"
PARAMETER_DECISION_ENGINE_VERSION = "hdde.d60-03-parameter-decision.v1"
_BOUND_PARAMETER_DECISION_ATTRIBUTE = "_d60_03_parameter_decision"


class ParameterDecisionOutcome(str, Enum):
    CORRECTION_NEEDED = "CORRECTION_NEEDED"
    NO_CORRECTION_REQUIRED = "NO_CORRECTION_REQUIRED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ParameterDirection(str, Enum):
    NEUTRAL = "NEUTRAL"
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    WARMER = "WARMER"
    COOLER = "COOLER"
    TOWARD_MAGENTA = "TOWARD_MAGENTA"
    TOWARD_GREEN = "TOWARD_GREEN"


# The complete severity-to-magnitude policy is centralized here.  Values stay
# far inside the D60-02 public bounds; STRONG means stronger evidence, not an
# instruction to touch the executor's limit.
SEVERITY_PARAMETER_MAGNITUDES: dict[str, dict[DiagnosisSeverity, float]] = {
    "exposure": {
        DiagnosisSeverity.MILD: 0.16,
        DiagnosisSeverity.MODERATE: 0.32,
        DiagnosisSeverity.STRONG: 0.52,
    },
    "brightness": {
        DiagnosisSeverity.MILD: 4.0,
        DiagnosisSeverity.MODERATE: 8.0,
        DiagnosisSeverity.STRONG: 12.0,
    },
    "contrast": {
        DiagnosisSeverity.MILD: 6.0,
        DiagnosisSeverity.MODERATE: 12.0,
        DiagnosisSeverity.STRONG: 20.0,
    },
    "temperature": {
        DiagnosisSeverity.MILD: 6.0,
        DiagnosisSeverity.MODERATE: 12.0,
        DiagnosisSeverity.STRONG: 20.0,
    },
    "tint": {
        DiagnosisSeverity.MILD: 6.0,
        DiagnosisSeverity.MODERATE: 12.0,
        DiagnosisSeverity.STRONG: 20.0,
    },
    "saturation": {
        DiagnosisSeverity.MILD: 6.0,
        DiagnosisSeverity.MODERATE: 12.0,
        DiagnosisSeverity.STRONG: 20.0,
    },
    "vibrance": {
        DiagnosisSeverity.MILD: 8.0,
        DiagnosisSeverity.MODERATE: 16.0,
        DiagnosisSeverity.STRONG: 24.0,
    },
    "highlights": {
        DiagnosisSeverity.MILD: 6.0,
        DiagnosisSeverity.MODERATE: 12.0,
        DiagnosisSeverity.STRONG: 20.0,
    },
    "shadows": {
        DiagnosisSeverity.MILD: 6.0,
        DiagnosisSeverity.MODERATE: 12.0,
        DiagnosisSeverity.STRONG: 20.0,
    },
}

# Only mild, independently credible midtone errors may extend the low-risk
# tonal policy to a person scene. Endpoint values are normalized luminance.
_PERSON_MIDTONE_MIN_CONFIDENCE = 0.80
_PERSON_MIDTONE_MIN_DIAGNOSIS_CONFIDENCE = 0.65
_PERSON_MIDTONE_MAX_HIGHLIGHT_P99 = 0.97
_PERSON_MIDTONE_MIN_SHADOW_P01 = 0.025


@dataclass(frozen=True)
class ParameterDecisionItem:
    value: float
    direction: ParameterDirection
    reason: str
    source_evidence: tuple[str, ...]
    confidence: float
    limit_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "VALUE": self.value,
            "DIRECTION": self.direction.value,
            "REASON": self.reason,
            "SOURCE_EVIDENCE": list(self.source_evidence),
            "CONFIDENCE": self.confidence,
            "LIMIT_REASON": self.limit_reason,
        }


@dataclass(frozen=True)
class ParameterDecision:
    schema_version: str
    engine_version: str
    source_fingerprint: str
    diagnosis_schema_version: str
    outcome: ParameterDecisionOutcome
    correction_parameters: CorrectionParameters
    parameter_decisions: dict[str, ParameterDecisionItem]
    no_correction_reasons: tuple[str, ...]
    insufficient_evidence_reasons: tuple[str, ...]
    decision_confidence: float
    active_parameters: tuple[str, ...]
    maximum_active_severity: DiagnosisSeverity
    decision_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
            "source_fingerprint": self.source_fingerprint,
            "diagnosis_schema_version": self.diagnosis_schema_version,
            "OUTCOME": self.outcome.value,
            "CORRECTION_PARAMETERS": self.correction_parameters.to_record(),
            "PARAMETER_DECISIONS": {
                name: self.parameter_decisions[name].to_dict()
                for name in PARAMETER_SPECS
            },
            "NO_CORRECTION_REASON": list(self.no_correction_reasons),
            "INSUFFICIENT_EVIDENCE_REASON": list(self.insufficient_evidence_reasons),
            "DECISION_CONFIDENCE": self.decision_confidence,
            "ACTIVE_PARAMETERS": list(self.active_parameters),
            "MAXIMUM_ACTIVE_SEVERITY": self.maximum_active_severity.value,
            "DECISION_DIGEST": self.decision_digest,
        }


def magnitude_for(parameter: str, severity: DiagnosisSeverity) -> float:
    if parameter not in SEVERITY_PARAMETER_MAGNITUDES:
        raise ValueError(f"unknown decision parameter: {parameter}")
    if severity not in SEVERITY_PARAMETER_MAGNITUDES[parameter]:
        raise ValueError(f"{severity.value} has no active magnitude for {parameter}")
    value = float(SEVERITY_PARAMETER_MAGNITUDES[parameter][severity])
    spec = PARAMETER_SPECS[parameter]
    if not spec.minimum < value < spec.maximum:
        raise RuntimeError(f"decision magnitude is outside the frozen {parameter} contract")
    return value


def _evidence(name: str, finding: Any, *keys: str) -> tuple[str, ...]:
    values = finding.evidence
    return tuple(f"{name}:{key}={values.get(key)}" for key in keys)


def _neutral_item(reason: str, evidence: tuple[str, ...], confidence: float, limit: str | None = None) -> ParameterDecisionItem:
    return ParameterDecisionItem(0.0, ParameterDirection.NEUTRAL, reason, evidence, round(float(confidence), 4), limit)


def _active_item(
    value: float,
    direction: ParameterDirection,
    reason: str,
    evidence: tuple[str, ...],
    confidence: float,
    limit: str | None = None,
) -> ParameterDecisionItem:
    return ParameterDecisionItem(round(float(value), 4), direction, reason, evidence, round(float(confidence), 4), limit)


def _previous_active_severity(severity: DiagnosisSeverity) -> DiagnosisSeverity:
    return {
        DiagnosisSeverity.STRONG: DiagnosisSeverity.MODERATE,
        DiagnosisSeverity.MODERATE: DiagnosisSeverity.MILD,
        DiagnosisSeverity.MILD: DiagnosisSeverity.MILD,
    }.get(severity, DiagnosisSeverity.MILD)


def _conclusive_global_exposure_error(diagnosis: ObjectiveColorDiagnosis) -> bool:
    """Require endpoint evidence before overriding scene or person risk."""

    evidence = diagnosis.exposure.evidence
    if diagnosis.exposure.severity != DiagnosisSeverity.STRONG:
        return False
    if diagnosis.exposure.state == "UNDEREXPOSED":
        return bool(
            float(evidence.get("luminance_p50", 1.0)) <= 0.18
            and float(evidence.get("luminance_p95", 1.0)) <= 0.58
            and float(evidence.get("shadow_ratio", 0.0)) >= 0.45
            and diagnosis.shadows.state in {"AT_RISK", "CRUSHED"}
        )
    if diagnosis.exposure.state == "OVEREXPOSED":
        return bool(
            float(evidence.get("luminance_p05", 0.0)) >= 0.68
            and float(evidence.get("luminance_p50", 0.0)) >= 0.90
            and diagnosis.highlights.state in {"AT_RISK", "CLIPPED"}
        )
    return False


def _person_midtone_blocker(diagnosis: ObjectiveColorDiagnosis) -> str | None:
    """Keep local person risk, intent and directional headroom authoritative."""

    midtones = diagnosis.brightness_distribution
    if not (
        midtones.severity == DiagnosisSeverity.MILD
        and midtones.confidence >= _PERSON_MIDTONE_MIN_CONFIDENCE
        and diagnosis.diagnosis_confidence >= _PERSON_MIDTONE_MIN_DIAGNOSIS_CONFIDENCE
    ):
        return "PERSON_MIDTONE_EVIDENCE_OUTSIDE_MILD_CONFIDENT_POLICY"
    if diagnosis.scene_risk.state != "MEDIUM" or diagnosis.scene_risk.evidence.get("scene_intent") != "PERSON_SCENE":
        return "PERSON_MIDTONE_SCENE_INTENT_CONFLICT"
    if (
        diagnosis.skin_risk.state not in {"LOW", "MEDIUM"}
        or diagnosis.skin_risk.evidence.get("local_person_exposure_risk") is not False
        or diagnosis.skin_risk.evidence.get("local_person_color_risk") is not False
    ):
        return "PERSON_MIDTONE_LOCAL_RISK_NOT_SAFE"
    if diagnosis.clipping.state not in {"ACCEPTABLE", "MILD"}:
        return "PERSON_MIDTONE_CLIPPING_LIMITS_RELIABLE_DECISION"
    if (
        diagnosis.exposure.state != "ACCEPTABLE"
        or diagnosis.contrast.state != "ACCEPTABLE"
        or diagnosis.white_balance.state != "NEUTRAL"
        or diagnosis.neutral_color_evidence.state != "SUFFICIENT"
        or diagnosis.saturation.state != "ACCEPTABLE"
    ):
        return "PERSON_MIDTONE_OTHER_CORRECTION_EVIDENCE_CONFLICT"
    if midtones.state == "LOW_MIDTONES":
        if diagnosis.highlights.state != "ACCEPTABLE" or not (
            0.0 <= float(diagnosis.highlights.evidence.get("luminance_p99", 1.0)) <= _PERSON_MIDTONE_MAX_HIGHLIGHT_P99
        ):
            return "PERSON_MIDTONE_HIGHLIGHT_HEADROOM_INSUFFICIENT"
    elif diagnosis.shadows.state != "ACCEPTABLE" or not (
        _PERSON_MIDTONE_MIN_SHADOW_P01 <= float(diagnosis.shadows.evidence.get("luminance_p01", 0.0)) <= 1.0
    ):
        return "PERSON_MIDTONE_SHADOW_HEADROOM_INSUFFICIENT"
    return None


def _decision_payload(
    diagnosis: ObjectiveColorDiagnosis,
    outcome: ParameterDecisionOutcome,
    parameters: CorrectionParameters,
    decisions: dict[str, ParameterDecisionItem],
    no_correction_reasons: tuple[str, ...],
    insufficient_reasons: tuple[str, ...],
    confidence: float,
    active: tuple[str, ...],
    maximum_severity: DiagnosisSeverity,
) -> dict[str, Any]:
    return {
        "schema_version": PARAMETER_DECISION_SCHEMA_VERSION,
        "engine_version": PARAMETER_DECISION_ENGINE_VERSION,
        "source_fingerprint": diagnosis.source_fingerprint,
        "diagnosis_schema_version": diagnosis.schema_version,
        "outcome": outcome.value,
        "correction_parameters": parameters.to_record(),
        "parameter_decisions": {name: decisions[name].to_dict() for name in PARAMETER_SPECS},
        "no_correction_reasons": list(no_correction_reasons),
        "insufficient_evidence_reasons": list(insufficient_reasons),
        "decision_confidence": confidence,
        "active_parameters": list(active),
        "maximum_active_severity": maximum_severity.value,
    }


def _payload_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "hdde.parameter-decision-digest.v1:" + hashlib.sha256(encoded).hexdigest()


def decide_correction_parameters(diagnosis: ObjectiveColorDiagnosis) -> ParameterDecision:
    """Choose the smallest evidence-supported set of correction controls."""

    decisions: dict[str, ParameterDecisionItem] = {
        "exposure": _neutral_item(
            "EXPOSURE_ALREADY_ACCEPTABLE",
            _evidence("EXPOSURE", diagnosis.exposure, "luminance_p50", "luminance_p95"),
            diagnosis.exposure.confidence,
        ),
        "brightness": _neutral_item(
            "BRIGHTNESS_DISTRIBUTION_ALREADY_ACCEPTABLE",
            _evidence("BRIGHTNESS_DISTRIBUTION", diagnosis.brightness_distribution, "luminance_p50"),
            diagnosis.brightness_distribution.confidence,
        ),
        "contrast": _neutral_item(
            "CONTRAST_ALREADY_ACCEPTABLE",
            _evidence("CONTRAST", diagnosis.contrast, "dynamic_range_p95_p05"),
            diagnosis.contrast.confidence,
        ),
        "temperature": _neutral_item(
            "WHITE_BALANCE_TEMPERATURE_ALREADY_ACCEPTABLE",
            _evidence("WHITE_BALANCE", diagnosis.white_balance, "neutral_lab_b", "neutral_evidence_state"),
            diagnosis.white_balance.confidence,
        ),
        "tint": _neutral_item(
            "WHITE_BALANCE_TINT_ALREADY_ACCEPTABLE",
            _evidence("WHITE_BALANCE", diagnosis.white_balance, "neutral_lab_a", "neutral_evidence_state"),
            diagnosis.white_balance.confidence,
        ),
        "saturation": _neutral_item(
            "SATURATION_ALREADY_ACCEPTABLE",
            _evidence("SATURATION", diagnosis.saturation, "saturation_mean", "saturation_p50", "saturation_p90"),
            diagnosis.saturation.confidence,
        ),
        "vibrance": _neutral_item(
            "LOW_SATURATION_COMPENSATION_NOT_REQUIRED",
            _evidence("SATURATION", diagnosis.saturation, "saturation_mean", "saturation_p90"),
            diagnosis.saturation.confidence,
        ),
        "highlights": _neutral_item(
            "HIGHLIGHTS_ALREADY_ACCEPTABLE",
            _evidence("HIGHLIGHTS", diagnosis.highlights, "luminance_p99", "highlight_clip_ratio"),
            diagnosis.highlights.confidence,
        ),
        "shadows": _neutral_item(
            "SHADOWS_ALREADY_ACCEPTABLE",
            _evidence("SHADOWS", diagnosis.shadows, "luminance_p01", "shadow_clip_ratio"),
            diagnosis.shadows.confidence,
        ),
    }
    active_severities: list[DiagnosisSeverity] = []
    scene_intent = str(diagnosis.scene_risk.evidence.get("scene_intent", "GENERAL"))
    high_scene_risk = diagnosis.scene_risk.state == "HIGH"
    high_skin_risk = diagnosis.skin_risk.state == "HIGH"
    medium_skin_risk = diagnosis.skin_risk.state == "MEDIUM"
    severe_clipping = diagnosis.clipping.state == "SEVERE"
    exposure_unresolved_reason: str | None = None
    midtone_unresolved_reason: str | None = None

    # Exposure owns global level.  Brightness never duplicates an active
    # exposure decision; local endpoints are also held neutral in that case.
    if diagnosis.exposure.state in {"UNDEREXPOSED", "OVEREXPOSED"}:
        protected_intent = (
            diagnosis.exposure.state == "UNDEREXPOSED" and scene_intent == "LEGITIMATE_DARK"
        ) or (
            diagnosis.exposure.state == "OVEREXPOSED" and scene_intent == "LEGITIMATE_HIGH_KEY"
        )
        probable_high_key_or_backlight = scene_intent == "PROBABLE_HIGH_KEY_OR_BACKLIGHT"
        exposure_risk = probable_high_key_or_backlight or high_scene_risk or high_skin_risk
        local_person_exposure_risk = bool(
            diagnosis.skin_risk.evidence.get("local_person_exposure_risk")
        )
        conclusive_global_error = _conclusive_global_exposure_error(diagnosis)
        confidence_supports_risk_override = bool(
            diagnosis.exposure.confidence >= 0.80
            and diagnosis.diagnosis_confidence >= 0.65
        )
        person_evidence_supports_correction = bool(
            not high_skin_risk or local_person_exposure_risk
        )
        if protected_intent:
            decisions["exposure"] = _neutral_item(
                "SCENE_EXPOSURE_INTENT_PROTECTED",
                _evidence("EXPOSURE", diagnosis.exposure, "luminance_p50", "luminance_p95"),
                diagnosis.exposure.confidence,
                scene_intent,
            )
        elif severe_clipping:
            decisions["exposure"] = _neutral_item(
                "EXPOSURE_EVIDENCE_LIMITED_BY_SEVERE_CLIPPING",
                _evidence("CLIPPING", diagnosis.clipping, "combined_clip_ratio"),
                min(diagnosis.exposure.confidence, diagnosis.clipping.confidence),
                "SEVERE_CLIPPING_REQUIRES_QUALITY_GATE",
            )
            exposure_unresolved_reason = "SEVERE_CLIPPING_LIMITS_RELIABLE_EXPOSURE_DECISION"
        elif exposure_risk and not (
            conclusive_global_error
            and confidence_supports_risk_override
            and person_evidence_supports_correction
        ):
            decisions["exposure"] = _neutral_item(
                "EXPOSURE_INTENT_OR_PERSON_EVIDENCE_CONFLICT",
                (
                    *_evidence(
                        "EXPOSURE",
                        diagnosis.exposure,
                        "luminance_p05",
                        "luminance_p50",
                        "luminance_p95",
                        "shadow_ratio",
                    ),
                    *_evidence(
                        "SCENE_RISK",
                        diagnosis.scene_risk,
                        "scene_intent",
                        "dominant_color_risk",
                    ),
                    *_evidence(
                        "SKIN_RISK",
                        diagnosis.skin_risk,
                        "person_present",
                        "local_person_exposure_risk",
                    ),
                ),
                min(
                    diagnosis.exposure.confidence,
                    diagnosis.scene_risk.confidence,
                    diagnosis.skin_risk.confidence,
                ),
                "INSUFFICIENT_EVIDENCE_FOR_GLOBAL_EXPOSURE",
            )
            exposure_unresolved_reason = "EXPOSURE_INTENT_OR_PERSON_EVIDENCE_CONFLICT"
        else:
            sign = 1.0 if diagnosis.exposure.state == "UNDEREXPOSED" else -1.0
            direction = ParameterDirection.INCREASE if sign > 0 else ParameterDirection.DECREASE
            severity = diagnosis.exposure.severity
            limited_for_risk = exposure_risk
            applied_severity = DiagnosisSeverity.MILD if limited_for_risk else severity
            decisions["exposure"] = _active_item(
                sign * magnitude_for("exposure", applied_severity),
                direction,
                (
                    "GLOBAL_UNDEREXPOSURE_PERSON_SCENE_LIMITED"
                    if sign > 0 and limited_for_risk
                    else "GLOBAL_OVEREXPOSURE_PERSON_SCENE_LIMITED"
                    if sign < 0 and limited_for_risk
                    else "GLOBAL_UNDEREXPOSURE"
                    if sign > 0
                    else "GLOBAL_OVEREXPOSURE"
                ),
                _evidence("EXPOSURE", diagnosis.exposure, "luminance_p05", "luminance_p50", "luminance_p95", "mean_luminance"),
                min(diagnosis.exposure.confidence, diagnosis.diagnosis_confidence),
                (
                    "SCENE_OR_PERSON_RISK_LIMITED_TO_MILD_EXPOSURE"
                    if limited_for_risk
                    else "BRIGHTNESS_HIGHLIGHTS_SHADOWS_HELD_TO_AVOID_TONE_STACKING"
                ),
            )
            active_severities.append(applied_severity)
            for name in ("brightness", "highlights", "shadows"):
                decisions[name] = _neutral_item(
                    "GLOBAL_EXPOSURE_OWNS_TONAL_LEVEL",
                    decisions[name].source_evidence,
                    decisions[name].confidence,
                    "EXPOSURE_ACTIVE_AVOIDS_DUPLICATE_TONE_COMPENSATION",
                )
    elif diagnosis.scene_risk.state == "LOW" and diagnosis.clipping.state in {"ACCEPTABLE", "MILD"}:
        if diagnosis.contrast.state in {"LOW", "HIGH"}:
            severity = diagnosis.contrast.severity
            sign = 1.0 if diagnosis.contrast.state == "LOW" else -1.0
            decisions["contrast"] = _active_item(
                sign * magnitude_for("contrast", severity),
                ParameterDirection.INCREASE if sign > 0 else ParameterDirection.DECREASE,
                "LOW_DYNAMIC_RANGE" if sign > 0 else "EXCESSIVE_DYNAMIC_RANGE",
                _evidence("CONTRAST", diagnosis.contrast, "luminance_p05", "luminance_p95", "dynamic_range_p95_p05"),
                diagnosis.contrast.confidence,
                "BRIGHTNESS_AND_ENDPOINT_CONTROLS_HELD_TO_AVOID_TONE_STACKING",
            )
            active_severities.append(severity)
        elif diagnosis.brightness_distribution.state in {"LOW_MIDTONES", "HIGH_MIDTONES"}:
            severity = diagnosis.brightness_distribution.severity
            sign = 1.0 if diagnosis.brightness_distribution.state == "LOW_MIDTONES" else -1.0
            decisions["brightness"] = _active_item(
                sign * magnitude_for("brightness", severity),
                ParameterDirection.INCREASE if sign > 0 else ParameterDirection.DECREASE,
                "MIDTONE_BRIGHTNESS_LOW" if sign > 0 else "MIDTONE_BRIGHTNESS_HIGH",
                _evidence("BRIGHTNESS_DISTRIBUTION", diagnosis.brightness_distribution, "luminance_p05", "luminance_p50", "luminance_p95"),
                diagnosis.brightness_distribution.confidence,
                "EXPOSURE_HELD_NEUTRAL_BECAUSE_GLOBAL_ENDPOINTS_ARE_ACCEPTABLE",
            )
            active_severities.append(severity)
        elif diagnosis.highlights.state in {"AT_RISK", "CLIPPED"} and diagnosis.shadows.state == "ACCEPTABLE":
            severity = diagnosis.highlights.severity
            decisions["highlights"] = _active_item(
                -magnitude_for("highlights", severity),
                ParameterDirection.DECREASE,
                "HIGHLIGHT_HEADROOM_LIMITED",
                _evidence("HIGHLIGHTS", diagnosis.highlights, "luminance_p95", "luminance_p99", "highlight_clip_ratio"),
                diagnosis.highlights.confidence,
            )
            active_severities.append(severity)
        elif diagnosis.shadows.state in {"AT_RISK", "CRUSHED"} and diagnosis.highlights.state == "ACCEPTABLE":
            severity = diagnosis.shadows.severity
            decisions["shadows"] = _active_item(
                magnitude_for("shadows", severity),
                ParameterDirection.INCREASE,
                "SHADOW_DETAIL_COMPRESSED",
                _evidence("SHADOWS", diagnosis.shadows, "luminance_p01", "luminance_p05", "shadow_clip_ratio"),
                diagnosis.shadows.confidence,
            )
            active_severities.append(severity)

    elif (
        diagnosis.brightness_distribution.state in {"LOW_MIDTONES", "HIGH_MIDTONES"}
        and diagnosis.skin_risk.evidence.get("person_present") is True
    ):
        midtone_unresolved_reason = _person_midtone_blocker(diagnosis)
        evidence = (
            *_evidence("BRIGHTNESS_DISTRIBUTION", diagnosis.brightness_distribution, "luminance_p05", "luminance_p50", "luminance_p95"),
            *_evidence("SKIN_RISK", diagnosis.skin_risk, "person_present", "local_person_exposure_risk", "local_person_color_risk"),
            *_evidence("SCENE_RISK", diagnosis.scene_risk, "scene_intent"),
            *_evidence("HIGHLIGHTS", diagnosis.highlights, "luminance_p99", "highlight_clip_ratio"),
            *_evidence("SHADOWS", diagnosis.shadows, "luminance_p01", "shadow_clip_ratio"),
            *_evidence("CLIPPING", diagnosis.clipping, "combined_clip_ratio", "color_clipped_pixel_ratio"),
        )
        confidence = min(diagnosis.brightness_distribution.confidence, diagnosis.diagnosis_confidence)
        if midtone_unresolved_reason:
            decisions["brightness"] = _neutral_item(
                "PERSON_MIDTONE_ABNORMALITY_PROTECTED_OR_UNRESOLVED",
                evidence, confidence, midtone_unresolved_reason,
            )
        else:
            sign = 1.0 if diagnosis.brightness_distribution.state == "LOW_MIDTONES" else -1.0
            decisions["brightness"] = _active_item(
                sign * magnitude_for("brightness", DiagnosisSeverity.MILD),
                ParameterDirection.INCREASE if sign > 0 else ParameterDirection.DECREASE,
                "PERSON_MIDTONE_BRIGHTNESS_LOW" if sign > 0 else "PERSON_MIDTONE_BRIGHTNESS_HIGH",
                evidence, confidence, "PERSON_MIDTONE_LIMITED_TO_MILD_BRIGHTNESS_WITH_DIRECTIONAL_HEADROOM",
            )
            active_severities.append(DiagnosisSeverity.MILD)

    # A reliable uniform neutral field may drive only its measured WB axis.
    # Scene/skin risk blocks or reduces that decision rather than creating a
    # fallback algorithm.
    wb_state = diagnosis.white_balance.state
    neutral_sufficient = diagnosis.neutral_color_evidence.state == "SUFFICIENT"
    wb_active = False
    tone_primary = decisions["exposure"].value != 0.0
    if wb_state in {"WARM", "COOL", "GREEN", "MAGENTA"}:
        parameter = "temperature" if wb_state in {"WARM", "COOL"} else "tint"
        evidence_key = "neutral_lab_b" if parameter == "temperature" else "neutral_lab_a"
        if tone_primary:
            decisions[parameter] = _neutral_item(
                "GLOBAL_EXPOSURE_OWNS_PRIMARY_CORRECTION",
                _evidence("WHITE_BALANCE", diagnosis.white_balance, evidence_key, "neutral_evidence_state"),
                diagnosis.white_balance.confidence,
                "TONE_AND_COLOR_FAMILIES_NOT_STACKED_IN_ONE_AUTOMATIC_DECISION",
            )
        elif diagnosis.clipping.state in {"ELEVATED", "SEVERE"}:
            decisions[parameter] = _neutral_item(
                "WHITE_BALANCE_EVIDENCE_LIMITED_BY_CLIPPING",
                _evidence("CLIPPING", diagnosis.clipping, "combined_clip_ratio"),
                min(diagnosis.white_balance.confidence, diagnosis.clipping.confidence),
                "CLIPPING_LIMITS_RELIABLE_NEUTRAL_COLOR_DECISION",
            )
        elif not neutral_sufficient:
            decisions[parameter] = _neutral_item(
                "WHITE_BALANCE_DIRECTION_NOT_ACTIONABLE",
                _evidence("WHITE_BALANCE", diagnosis.white_balance, evidence_key, "neutral_evidence_state"),
                diagnosis.white_balance.confidence,
                "NO_RELIABLE_NEUTRAL_EVIDENCE",
            )
        elif high_scene_risk:
            decisions[parameter] = _neutral_item(
                "SCENE_COLOR_INTENT_PROTECTED",
                _evidence("SCENE_RISK", diagnosis.scene_risk, "scene_intent", "dominant_color_risk", "spatial_field"),
                min(diagnosis.white_balance.confidence, diagnosis.scene_risk.confidence),
                scene_intent,
            )
        elif high_skin_risk:
            decisions[parameter] = _neutral_item(
                "LOCAL_SKIN_COLOR_RISK_PROTECTED",
                _evidence("SKIN_RISK", diagnosis.skin_risk, "person_present", "local_person_color_risk"),
                min(diagnosis.white_balance.confidence, diagnosis.skin_risk.confidence),
                "GLOBAL_WHITE_BALANCE_BLOCKED",
            )
        else:
            severity = diagnosis.white_balance.severity
            limited_severity = _previous_active_severity(severity) if medium_skin_risk else severity
            magnitude = magnitude_for(parameter, limited_severity)
            if wb_state == "WARM":
                value, direction, reason = -magnitude, ParameterDirection.COOLER, "WARM_NEUTRAL_CAST"
            elif wb_state == "COOL":
                value, direction, reason = magnitude, ParameterDirection.WARMER, "COOL_NEUTRAL_CAST"
            elif wb_state == "GREEN":
                value, direction, reason = magnitude, ParameterDirection.TOWARD_MAGENTA, "GREEN_NEUTRAL_CAST"
            else:
                value, direction, reason = -magnitude, ParameterDirection.TOWARD_GREEN, "MAGENTA_NEUTRAL_CAST"
            decisions[parameter] = _active_item(
                value,
                direction,
                reason,
                _evidence("WHITE_BALANCE", diagnosis.white_balance, "neutral_lab_a", "neutral_lab_b", "neutral_chroma", "spatial_direction_consistency"),
                diagnosis.white_balance.confidence,
                "PERSON_SCENE_REDUCED_TO_LOWER_SEVERITY" if medium_skin_risk and limited_severity != severity else None,
            )
            active_severities.append(limited_severity)
            wb_active = True

    if high_scene_risk:
        for name in ("saturation", "vibrance"):
            decisions[name] = _neutral_item(
                "SCENE_COLOR_INTENT_PROTECTED",
                decisions[name].source_evidence,
                min(diagnosis.saturation.confidence, diagnosis.scene_risk.confidence),
                scene_intent,
            )
    elif tone_primary:
        for name in ("saturation", "vibrance"):
            decisions[name] = _neutral_item(
                "GLOBAL_EXPOSURE_OWNS_PRIMARY_CORRECTION",
                decisions[name].source_evidence,
                decisions[name].confidence,
                "TONE_AND_COLOR_FAMILIES_NOT_STACKED_IN_ONE_AUTOMATIC_DECISION",
            )
    elif wb_active:
        for name in ("saturation", "vibrance"):
            decisions[name] = _neutral_item(
                "WHITE_BALANCE_OWNS_COLOR_CORRECTION",
                decisions[name].source_evidence,
                decisions[name].confidence,
                "WB_ACTIVE_AVOIDS_CHROMA_STACKING",
            )
    elif diagnosis.saturation.state == "LOW" and diagnosis.clipping.state in {"ACCEPTABLE", "MILD"}:
        severity = diagnosis.saturation.severity
        decisions["vibrance"] = _active_item(
            magnitude_for("vibrance", severity),
            ParameterDirection.INCREASE,
            "LOW_SATURATION_REGIONS",
            _evidence("SATURATION", diagnosis.saturation, "saturation_mean", "saturation_p50", "saturation_p90"),
            diagnosis.saturation.confidence,
            "VIBRANCE_USED_INSTEAD_OF_GLOBAL_SATURATION",
        )
        decisions["saturation"] = _neutral_item(
            "VIBRANCE_OWNS_LOW_SATURATION_COMPENSATION",
            decisions["saturation"].source_evidence,
            decisions["saturation"].confidence,
            "AVOID_SATURATION_VIBRANCE_STACKING",
        )
        active_severities.append(severity)
    elif diagnosis.saturation.state == "HIGH" and not severe_clipping:
        severity = diagnosis.saturation.severity
        decisions["saturation"] = _active_item(
            -magnitude_for("saturation", severity),
            ParameterDirection.DECREASE,
            "GLOBAL_SATURATION_HIGH",
            _evidence("SATURATION", diagnosis.saturation, "saturation_mean", "saturation_p50", "saturation_p90", "strong_color_ratio"),
            diagnosis.saturation.confidence,
            "VIBRANCE_HELD_NEUTRAL_TO_AVOID_CHROMA_STACKING",
        )
        active_severities.append(severity)
    elif diagnosis.saturation.state == "HIGH":
        decisions["saturation"] = _neutral_item(
            "SATURATION_MEASUREMENT_UNRELIABLE_DUE_TO_CLIPPING",
            (
                *_evidence(
                    "SATURATION",
                    diagnosis.saturation,
                    "saturation_mean",
                    "saturation_p50",
                    "saturation_p90",
                    "strong_color_ratio",
                ),
                *_evidence(
                    "CLIPPING",
                    diagnosis.clipping,
                    "combined_clip_ratio",
                    "maximum_color_channel_clip_ratio",
                    "color_clipped_pixel_ratio",
                ),
            ),
            min(diagnosis.saturation.confidence, diagnosis.clipping.confidence),
            "CLIPPED_COLOR_INFORMATION_CANNOT_BE_RECOVERED",
        )

    values = {name: decisions[name].value for name in PARAMETER_SPECS}
    parameters = CorrectionParameters.from_mapping(values)
    active = tuple(name for name in PARAMETER_SPECS if getattr(parameters, name) != 0.0)
    unresolved: list[str] = []
    if exposure_unresolved_reason:
        unresolved.append(exposure_unresolved_reason)
    if midtone_unresolved_reason:
        unresolved.append(midtone_unresolved_reason)
    if diagnosis.neutral_color_evidence.state in {"UNSTABLE", "MIXED_FIELD"}:
        unresolved.append(
            "QUANTIZATION_BOUNDARY_UNSTABLE"
            if diagnosis.neutral_color_evidence.state == "UNSTABLE"
            else "MIXED_COLOR_FIELD"
        )
    elif diagnosis.neutral_color_evidence.state == "INSUFFICIENT" and not high_scene_risk:
        unresolved.append("NO_RELIABLE_NEUTRAL_EVIDENCE")
    if diagnosis.saturation.state in {"VERY_LOW_UNIFORM", "LOW_AMBIGUOUS"} and not high_scene_risk:
        unresolved.append("SATURATION_INTENT_UNRESOLVED")
    if (
        diagnosis.saturation.state in {"LOW", "HIGH"}
        and diagnosis.clipping.state == "SEVERE"
        and not active
    ):
        unresolved.append("CLIPPING_LIMITS_SATURATION_EVIDENCE")
    if (
        diagnosis.white_balance.state in {"WARM", "COOL", "GREEN", "MAGENTA"}
        and diagnosis.clipping.state in {"ELEVATED", "SEVERE"}
        and not active
    ):
        unresolved.append("CLIPPING_LIMITS_COLOR_EVIDENCE")
    if (
        (
            diagnosis.highlights.state in {"AT_RISK", "CLIPPED"}
            or diagnosis.shadows.state in {"AT_RISK", "CRUSHED"}
        )
        and diagnosis.clipping.state in {"ELEVATED", "SEVERE"}
        and not active
    ):
        unresolved.append("CLIPPING_LIMITS_ENDPOINT_TONE_DECISION")
    if severe_clipping and not active:
        unresolved.append("SEVERE_CLIPPING_LIMITS_RELIABLE_DECISION")

    if active:
        outcome = ParameterDecisionOutcome.CORRECTION_NEEDED
        no_correction_reasons: tuple[str, ...] = ()
    elif unresolved:
        outcome = ParameterDecisionOutcome.INSUFFICIENT_EVIDENCE
        no_correction_reasons = ()
    else:
        outcome = ParameterDecisionOutcome.NO_CORRECTION_REQUIRED
        reasons = [item.reason for item in decisions.values() if item.value == 0.0]
        no_correction_reasons = tuple(dict.fromkeys(reasons))

    confidence_sources = [decisions[name].confidence for name in active] if active else [diagnosis.diagnosis_confidence]
    confidence = round(float(min(confidence_sources)), 4)
    if outcome == ParameterDecisionOutcome.INSUFFICIENT_EVIDENCE:
        confidence = round(float(min(confidence, 0.49)), 4)
    severity_order = {
        DiagnosisSeverity.NONE: 0,
        DiagnosisSeverity.MILD: 1,
        DiagnosisSeverity.MODERATE: 2,
        DiagnosisSeverity.STRONG: 3,
        DiagnosisSeverity.INDETERMINATE: -1,
    }
    maximum_severity = max(active_severities, key=lambda item: severity_order[item]) if active_severities else DiagnosisSeverity.NONE
    insufficient_reasons = tuple(dict.fromkeys(unresolved))
    payload = _decision_payload(
        diagnosis,
        outcome,
        parameters,
        decisions,
        no_correction_reasons,
        insufficient_reasons,
        confidence,
        active,
        maximum_severity,
    )
    return ParameterDecision(
        PARAMETER_DECISION_SCHEMA_VERSION,
        PARAMETER_DECISION_ENGINE_VERSION,
        diagnosis.source_fingerprint,
        diagnosis.schema_version,
        outcome,
        parameters,
        decisions,
        no_correction_reasons,
        insufficient_reasons,
        confidence,
        active,
        maximum_severity,
        _payload_digest(payload),
    )


def validate_parameter_decision(decision: ParameterDecision, *, source_fingerprint: str) -> None:
    if type(decision) is not ParameterDecision:
        raise ValueError("INVALID_PARAMETER_DECISION_TYPE")
    if decision.schema_version != PARAMETER_DECISION_SCHEMA_VERSION:
        raise ValueError("UNSUPPORTED_PARAMETER_DECISION_SCHEMA")
    if decision.engine_version != PARAMETER_DECISION_ENGINE_VERSION:
        raise ValueError("UNSUPPORTED_PARAMETER_DECISION_ENGINE")
    if decision.source_fingerprint != source_fingerprint:
        raise ValueError("PARAMETER_DECISION_SOURCE_MISMATCH")
    if set(decision.parameter_decisions) != set(PARAMETER_SPECS):
        raise ValueError("INCOMPLETE_PARAMETER_DECISION")
    for name in PARAMETER_SPECS:
        if decision.parameter_decisions[name].value != getattr(decision.correction_parameters, name):
            raise ValueError("PARAMETER_DECISION_VALUE_MISMATCH")
    payload = {
        "schema_version": decision.schema_version,
        "engine_version": decision.engine_version,
        "source_fingerprint": decision.source_fingerprint,
        "diagnosis_schema_version": decision.diagnosis_schema_version,
        "outcome": decision.outcome.value,
        "correction_parameters": decision.correction_parameters.to_record(),
        "parameter_decisions": {name: decision.parameter_decisions[name].to_dict() for name in PARAMETER_SPECS},
        "no_correction_reasons": list(decision.no_correction_reasons),
        "insufficient_evidence_reasons": list(decision.insufficient_evidence_reasons),
        "decision_confidence": decision.decision_confidence,
        "active_parameters": list(decision.active_parameters),
        "maximum_active_severity": decision.maximum_active_severity.value,
    }
    if _payload_digest(payload) != decision.decision_digest:
        raise ValueError("PARAMETER_DECISION_DIGEST_MISMATCH")
    if decision.outcome == ParameterDecisionOutcome.CORRECTION_NEEDED and not decision.active_parameters:
        raise ValueError("CORRECTION_NEEDED_WITHOUT_PARAMETERS")
    if decision.outcome != ParameterDecisionOutcome.CORRECTION_NEEDED and decision.active_parameters:
        raise ValueError("NON_CORRECTION_OUTCOME_WITH_ACTIVE_PARAMETERS")


def bind_parameter_decision(owner: Any, parameter_decision: ParameterDecision) -> None:
    """Bind a validated source-specific D60-03 decision to the D1 runtime owner."""

    source_fingerprint = getattr(owner, "source_fingerprint", None)
    if not isinstance(source_fingerprint, str):
        raise ValueError("PARAMETER_DECISION_OWNER_HAS_NO_SOURCE")
    validate_parameter_decision(parameter_decision, source_fingerprint=source_fingerprint)
    object.__setattr__(owner, _BOUND_PARAMETER_DECISION_ATTRIBUTE, parameter_decision)


def bound_parameter_decision(owner: Any) -> ParameterDecision | None:
    value = getattr(owner, _BOUND_PARAMETER_DECISION_ATTRIBUTE, None)
    if value is None:
        return None
    source_fingerprint = getattr(owner, "source_fingerprint", None)
    validate_parameter_decision(value, source_fingerprint=source_fingerprint)
    return value


__all__ = [
    "PARAMETER_DECISION_SCHEMA_VERSION",
    "PARAMETER_DECISION_ENGINE_VERSION",
    "SEVERITY_PARAMETER_MAGNITUDES",
    "ParameterDecisionOutcome",
    "ParameterDirection",
    "ParameterDecisionItem",
    "ParameterDecision",
    "magnitude_for",
    "decide_correction_parameters",
    "validate_parameter_decision",
    "bind_parameter_decision",
    "bound_parameter_decision",
]
