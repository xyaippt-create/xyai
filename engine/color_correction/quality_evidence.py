"""D60-04 source-vs-candidate quality evidence for deterministic color correction.

This module is deliberately not an executor and does not own the final Result
action.  It compares one D60-02 candidate with its source under the exact
recorded ``CorrectionParameters`` and returns JSON-safe evidence for D3.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Iterable, Sequence

import cv2
import numpy as np

from .parameters import PARAMETER_SPECS, CorrectionParameters
from .objective_diagnosis import DiagnosisSeverity, ObjectiveColorDiagnosis
from .usability_decision import compute_source_fingerprint


QUALITY_EVIDENCE_SCHEMA_VERSION = "hdde.color-quality-evidence.schema.v1"
QUALITY_EVIDENCE_ENGINE_VERSION = "hdde.d60-04-quality-comparison.v2"

# All D60-04 tolerances live here so that the evidence semantics are auditable.
_MIN_ANALYSIS_PIXELS = 64
_MIN_TARGET_DELTA = {
    "exposure": 0.008,
    "brightness": 0.002,
    "contrast": 0.005,
    "temperature": 0.15,
    "tint": 0.15,
    "saturation": 0.004,
    "vibrance": 0.003,
    "highlights": 0.001,
    "shadows": 0.001,
}
_MAX_NEW_CHANNEL_CLIP = 0.005
_MAX_NEW_LUMINANCE_CLIP = 0.005
_MAX_UNINTENDED_TONE_SHIFT = 0.035
_MAX_UNINTENDED_NEUTRAL_SHIFT = 2.5
_MAX_NEUTRAL_AXIS_ABS = (12.0, 14.0)
_MAX_SKIN_DELTA_E_MEDIAN = 8.0
_MAX_SKIN_DELTA_E_P95 = 16.0
_MAX_SKIN_CHROMA_DELTA = 6.0
_MAX_BRAND_HUE_SHIFT_DEGREES = 8.0
_MAX_WB_BRAND_HUE_SHIFT_DEGREES = 15.0
_MAX_DYNAMIC_RANGE_LOSS = 0.08
_POSTERIZATION_BIN_RATIO_LIMIT = 0.60
_POSTERIZATION_MAX_BINS = 96
_BANDING_ZERO_STEP_GROWTH_LIMIT = 0.18
_BANDING_WINDOW = 32
_BANDING_MIN_SPAN = 4.0  # 8-bit perceptual luminance levels
_BANDING_MAX_SOURCE_STEP = 2.5
_BANDING_MIN_NEW_STEP = 3.0
_BANDING_STEP_MULTIPLIER = 1.8
_BANDING_MAX_DAMAGED_WINDOW_RATIO = 0.03
_TARGET_CONFIDENCE_MIN = 0.5
_SATURATION_P50_CEILING = 0.54
_SATURATION_P90_CEILING = 0.84
_DIAGNOSTIC_LUMINANCE_WEIGHTS = (0.2126, 0.7152, 0.0722)  # D60-03/D1 encoded-sRGB domain
_TARGET_INTERVALS = {
    "tone": (0.34, 0.76),
    "contrast": (0.48, 0.86),
    "temperature": (1.4, 3.4),
    "tint": (0.5, 2.5),
    "saturation": (0.18, 0.48),
    "highlights": (0.65, 0.95),
    "shadows": (0.08, 0.35),
}


class EvidenceVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INCONCLUSIVE = "INCONCLUSIVE"


class QualityNetBenefit(str, Enum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class QualityMetricEvidence:
    source_metric: Any
    candidate_metric: Any
    delta: Any
    verdict: EvidenceVerdict
    reason: str

    def to_record(self) -> dict[str, Any]:
        return {
            "SOURCE_METRIC": _json_safe(self.source_metric),
            "CANDIDATE_METRIC": _json_safe(self.candidate_metric),
            "DELTA": _json_safe(self.delta),
            "VERDICT": self.verdict.value,
            "REASON": self.reason,
        }


@dataclass(frozen=True)
class QualityEvidence:
    schema_version: str
    engine_version: str
    source_fingerprint: str
    candidate_fingerprint: str
    parameter_digest: str
    parameter_decision_digest: str | None
    active_parameters: tuple[str, ...]
    targeted_issue_improvement: QualityMetricEvidence
    exposure_quality: QualityMetricEvidence
    white_balance_quality: QualityMetricEvidence
    color_cast_quality: QualityMetricEvidence
    contrast_quality: QualityMetricEvidence
    saturation_quality: QualityMetricEvidence
    highlight_quality: QualityMetricEvidence
    shadow_quality: QualityMetricEvidence
    skin_protection: QualityMetricEvidence
    neutral_protection: QualityMetricEvidence
    brand_color_protection: QualityMetricEvidence
    clipping_delta: QualityMetricEvidence
    dynamic_range_delta: QualityMetricEvidence
    banding_risk: QualityMetricEvidence
    posterization_risk: QualityMetricEvidence
    channel_saturation_risk: QualityMetricEvidence
    alpha_integrity: QualityMetricEvidence
    dimension_integrity: QualityMetricEvidence
    format_integrity: QualityMetricEvidence
    targeted_gain: bool
    protected_damage: bool
    new_artifact: bool
    net_benefit: QualityNetBenefit
    evidence_fingerprint: str

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
            "SOURCE_FINGERPRINT": self.source_fingerprint,
            "CANDIDATE_FINGERPRINT": self.candidate_fingerprint,
            "PARAMETER_DIGEST": self.parameter_digest,
            "PARAMETER_DECISION_DIGEST": self.parameter_decision_digest,
            "ACTIVE_PARAMETERS": list(self.active_parameters),
        }
        for item in fields(self):
            if isinstance(getattr(self, item.name), QualityMetricEvidence):
                record[item.name.upper()] = getattr(self, item.name).to_record()
        record.update(
            {
                "TARGETED_GAIN": self.targeted_gain,
                "PROTECTED_DAMAGE": self.protected_damage,
                "NEW_ARTIFACT": self.new_artifact,
                "NET_BENEFIT": self.net_benefit.value,
                "EVIDENCE_FINGERPRINT": self.evidence_fingerprint,
            }
        )
        return record


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return round(number, 6) if np.isfinite(number) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    return value


def _digest(payload: Any, prefix: str) -> str:
    encoded = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return prefix + hashlib.sha256(encoded).hexdigest()


def _array_fingerprint(image: np.ndarray) -> str:
    array = np.ascontiguousarray(np.asarray(image))
    digest = hashlib.sha256()
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(json.dumps(list(array.shape), separators=(",", ":")).encode("ascii"))
    digest.update(array.tobytes())
    return "hdde.quality-pixels.v1:" + digest.hexdigest()


def _metric(source: Any, candidate: Any, delta: Any, passed: bool, reason: str) -> QualityMetricEvidence:
    return QualityMetricEvidence(
        _json_safe(source),
        _json_safe(candidate),
        _json_safe(delta),
        EvidenceVerdict.PASS if passed else EvidenceVerdict.FAIL,
        reason,
    )


def _not_applicable(source: Any, candidate: Any, delta: Any, reason: str) -> QualityMetricEvidence:
    return QualityMetricEvidence(
        _json_safe(source),
        _json_safe(candidate),
        _json_safe(delta),
        EvidenceVerdict.NOT_APPLICABLE,
        reason,
    )


def _inconclusive(source: Any, candidate: Any, delta: Any, reason: str) -> QualityMetricEvidence:
    return QualityMetricEvidence(
        _json_safe(source),
        _json_safe(candidate),
        _json_safe(delta),
        EvidenceVerdict.INCONCLUSIVE,
        reason,
    )


def _rgb01(image: np.ndarray, input_order: str) -> tuple[np.ndarray, np.ndarray | None, np.ndarray]:
    array = np.asarray(image)
    if array.ndim != 3 or array.shape[2] not in {3, 4}:
        raise ValueError("QUALITY_EVIDENCE_REQUIRES_RGB_OR_RGBA")
    if array.dtype != np.uint8:
        raise ValueError("QUALITY_EVIDENCE_REQUIRES_UINT8")
    order = input_order.upper()
    if order not in {"RGB", "BGR"}:
        raise ValueError("QUALITY_EVIDENCE_INPUT_ORDER_INVALID")
    rgb = array[..., :3][:, :, ::-1] if order == "BGR" else array[..., :3]
    alpha = array[..., 3] if array.shape[2] == 4 else None
    visible = np.ones(array.shape[:2], dtype=bool) if alpha is None else alpha > 0
    return rgb.astype(np.float32) / 255.0, alpha, visible


def _region_mask(shape: tuple[int, int], regions: Iterable[Sequence[int]]) -> np.ndarray:
    mask = np.zeros(shape, dtype=bool)
    height, width = shape
    for region in regions:
        if len(region) != 4:
            continue
        x, y, w, h = (int(value) for value in region)
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + max(0, w)), min(height, y + max(0, h))
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = True
    return mask


def _masked_percentile(values: np.ndarray, mask: np.ndarray, percentile: float) -> float:
    selected = values[mask]
    return float(np.percentile(selected, percentile)) if selected.size else 0.0


def _tone_metrics(rgb: np.ndarray, lab: np.ndarray, mask: np.ndarray) -> dict[str, float]:
    luminance = lab[..., 0] / 100.0
    selected = luminance[mask]
    maximum = np.max(rgb, axis=2)[mask]
    minimum = np.min(rgb, axis=2)[mask]
    return {
        "mean": float(np.mean(selected)),
        "p01": float(np.percentile(selected, 1)),
        "p05": float(np.percentile(selected, 5)),
        "p50": float(np.percentile(selected, 50)),
        "p95": float(np.percentile(selected, 95)),
        "p99": float(np.percentile(selected, 99)),
        "shadow_clip_ratio": float(np.mean(maximum <= 0.005)),
        "highlight_clip_ratio": float(np.mean(minimum >= 0.995)),
        "channel_low_clip_ratio": float(np.mean(rgb[mask] <= 0.005)),
        "channel_high_clip_ratio": float(np.mean(rgb[mask] >= 0.995)),
        "dynamic_range": float(np.percentile(selected, 99) - np.percentile(selected, 1)),
        "contrast_range": float(np.percentile(selected, 95) - np.percentile(selected, 5)),
    }


def _color_metrics(rgb: np.ndarray, lab: np.ndarray, mask: np.ndarray) -> dict[str, float]:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    chroma = np.linalg.norm(lab[..., 1:3], axis=2)
    selected_sat = hsv[..., 1][mask]
    return {
        "saturation_mean": float(np.mean(selected_sat)),
        "saturation_p50": float(np.percentile(selected_sat, 50)),
        "saturation_p90": float(np.percentile(selected_sat, 90)),
        "chroma_mean": float(np.mean(chroma[mask])),
        "chroma_p50": float(np.percentile(chroma[mask], 50)),
    }


def _mask_lab_metrics(lab: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
    count = int(np.count_nonzero(mask))
    if count < _MIN_ANALYSIS_PIXELS:
        return {"pixel_count": count, "median_l": None, "median_a": None, "median_b": None, "median_chroma": None}
    selected = lab[mask]
    return {
        "pixel_count": count,
        "median_l": float(np.median(selected[:, 0]) / 100.0),
        "median_a": float(np.median(selected[:, 1])),
        "median_b": float(np.median(selected[:, 2])),
        "median_chroma": float(np.median(np.linalg.norm(selected[:, 1:3], axis=1))),
    }


def _metric_delta(source: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    for key, source_value in source.items():
        candidate_value = candidate.get(key)
        if isinstance(source_value, (int, float)) and isinstance(candidate_value, (int, float)):
            delta[key] = float(candidate_value) - float(source_value)
        else:
            delta[key] = None
    return delta


def _circular_hue_delta(source_hue: np.ndarray, candidate_hue: np.ndarray) -> np.ndarray:
    difference = np.abs(candidate_hue - source_hue)
    return np.minimum(difference, 360.0 - difference)


def _artifact_metrics(luminance: np.ndarray, mask: np.ndarray) -> dict[str, float | int]:
    gray = np.clip(np.rint(luminance * 255.0), 0, 255).astype(np.uint8)
    selected = gray[mask]
    occupied = int(np.unique(selected).size)
    horizontal_valid = mask[:, 1:] & mask[:, :-1]
    vertical_valid = mask[1:, :] & mask[:-1, :]
    horizontal = np.abs(gray[:, 1:].astype(np.int16) - gray[:, :-1].astype(np.int16))[horizontal_valid]
    vertical = np.abs(gray[1:, :].astype(np.int16) - gray[:-1, :].astype(np.int16))[vertical_valid]
    steps = np.concatenate((horizontal, vertical))
    return {
        "occupied_luminance_bins": occupied,
        "zero_step_ratio": float(np.mean(steps == 0)) if steps.size else 1.0,
        "small_step_ratio": float(np.mean(steps <= 1)) if steps.size else 1.0,
        "neighbor_step_count": int(steps.size),
    }


def _banding_evidence(source: np.ndarray, candidate: np.ndarray, mask: np.ndarray) -> QualityMetricEvidence:
    """Compare source-selected continuous scanlines, not flat fields or hard edges.

    Small local windows retain spatial evidence even when unaffected image
    regions keep every global luminance level occupied (posterization PASS).
    """
    before, after = [], []
    for src, dst, valid in ((source, candidate, mask), (source.T, candidate.T, mask.T)):
        width = src.shape[1] // _BANDING_WINDOW * _BANDING_WINDOW
        if not width:
            continue
        a = (src[:, :width] * 255.0).reshape(-1, _BANDING_WINDOW)
        b = (dst[:, :width] * 255.0).reshape(-1, _BANDING_WINDOW)
        visible = valid[:, :width].reshape(-1, _BANDING_WINDOW).all(axis=1)
        da, db = np.diff(a, axis=1), np.diff(b, axis=1)
        span = np.abs(a[:, -1] - a[:, 0])
        # A continuous monotonic source ramp has no material reversal or hard
        # jump. Pure colors have no span; text and logo boundaries have jumps.
        smooth = visible & (span >= _BANDING_MIN_SPAN)
        smooth &= np.max(np.abs(da), axis=1) <= _BANDING_MAX_SOURCE_STEP
        smooth &= np.sum(np.abs(da), axis=1) <= span * 1.1
        for steps, target in ((da[smooth], before), (db[smooth], after)):
            if steps.size:
                absolute = np.abs(steps)
                target.append(np.stack((np.mean(absolute < 0.1, axis=1), np.max(absolute, axis=1)), axis=1))
    if not before:
        return _not_applicable({"smooth_windows": 0}, {"smooth_windows": 0}, {}, "NO_SOURCE_CONTINUOUS_GRADIENT_EVIDENCE")
    a, b = np.concatenate(before), np.concatenate(after)
    loss = b[:, 0] - a[:, 0]
    damaged = (loss > _BANDING_ZERO_STEP_GROWTH_LIMIT) & (
        b[:, 1] >= np.maximum(_BANDING_MIN_NEW_STEP, a[:, 1] * _BANDING_STEP_MULTIPLIER)
    )
    count, ratio = int(np.count_nonzero(damaged)), float(np.mean(damaged))
    passed = not (count >= 2 and ratio > _BANDING_MAX_DAMAGED_WINDOW_RATIO)
    return _metric(
        {"smooth_windows": len(a), "zero_step_ratio": float(a[:, 0].mean()), "maximum_step": float(a[:, 1].max())},
        {"smooth_windows": len(b), "zero_step_ratio": float(b[:, 0].mean()), "maximum_step": float(b[:, 1].max())},
        {"damaged_windows": count, "damaged_window_ratio": ratio, "zero_step_growth": float(loss.mean())},
        passed, "SOURCE_GRADIENT_CONTINUITY_PRESERVED" if passed else "NEW_LOCAL_GRADIENT_TRANSITION_LOSS",
    )


def _target_evidence(
    diagnosis: ObjectiveColorDiagnosis | None,
    active: tuple[str, ...],
    values: dict[str, float],
    source_tone: dict[str, float],
    candidate_tone: dict[str, float],
    source_color: dict[str, float],
    candidate_color: dict[str, float],
    source_neutral: dict[str, Any],
    candidate_neutral: dict[str, Any],
    source_low_sat_mean: float | None,
    candidate_low_sat_mean: float | None,
) -> QualityMetricEvidence:
    if not active:
        return _not_applicable({}, {}, {}, "NEUTRAL_PARAMETERS_HAVE_NO_TARGETED_ISSUE")
    if diagnosis is None:
        return _inconclusive({}, {}, {"UNSUPPORTED_ADJUSTMENT": True, "PARAMETERS": active}, "OBJECTIVE_DIAGNOSIS_MISSING")

    # Each entry is one observed issue, with an ordered primary/supporting
    # control family. This is assessment only; no parameter is generated here.
    rules = (
        ("exposure", diagnosis.exposure, {"UNDEREXPOSED": 1, "OVEREXPOSED": -1}, ("exposure", "brightness", "shadows", "highlights"), "tone", source_tone["p50"], candidate_tone["p50"]),
        ("brightness", diagnosis.brightness_distribution, {"LOW_MIDTONES": 1, "HIGH_MIDTONES": -1}, ("brightness", "exposure"), "tone", source_tone["p50"], candidate_tone["p50"]),
        ("contrast", diagnosis.contrast, {"LOW": 1, "HIGH": -1}, ("contrast",), "contrast", source_tone["contrast_range"], candidate_tone["contrast_range"]),
        ("temperature", diagnosis.white_balance, {"WARM": -1, "COOL": 1}, ("temperature",), "temperature", source_neutral["median_b"], candidate_neutral["median_b"]),
        ("tint", diagnosis.white_balance, {"GREEN": 1, "MAGENTA": -1}, ("tint",), "tint", source_neutral["median_a"], candidate_neutral["median_a"]),
        ("saturation", diagnosis.saturation, {"LOW": 1, "HIGH": -1}, ("saturation", "vibrance"), "saturation", source_color, candidate_color),
        ("highlights", diagnosis.highlights, {"AT_RISK": -1, "CLIPPED": -1}, ("highlights", "exposure"), "highlights", source_tone["highlight_region_mean"], candidate_tone["highlight_region_mean"]),
        ("shadows", diagnosis.shadows, {"AT_RISK": 1, "CRUSHED": 1}, ("shadows", "exposure"), "shadows", source_tone["shadow_region_mean"], candidate_tone["shadow_region_mean"]),
    )
    records, supported = [], set()
    for family, finding, directions, controls, interval, before, after in rules:
        participating = [name for name in controls if name in active and name not in supported]
        if finding.state not in directions or not participating:
            continue
        supported.update(participating)
        reliable = finding.severity != DiagnosisSeverity.INDETERMINATE and finding.confidence >= _TARGET_CONFIDENCE_MIN
        if family in {"temperature", "tint"}:
            reliable &= diagnosis.neutral_color_evidence.state == "SUFFICIENT"
        sign = directions[finding.state]
        direction_ok = all(values[name] * sign > 0.0 for name in participating)
        low, high = _TARGET_INTERVALS[interval]
        def error(value):
            if family == "saturation":
                # D60-03 can diagnose high saturation from its upper tail,
                # even when the whole-image mean is inside the normal band.
                return max(low - value["saturation_mean"], value["saturation_mean"] - high,
                           value["saturation_p50"] - _SATURATION_P50_CEILING,
                           value["saturation_p90"] - _SATURATION_P90_CEILING, 0.0)
            return max(low - value, value - high, 0.0)
        improvement = None if before is None or after is None else error(before) - error(after)
        threshold = _MIN_TARGET_DELTA[participating[0]]
        verdict = EvidenceVerdict.INCONCLUSIVE if not reliable or improvement is None else (
            EvidenceVerdict.PASS if direction_ok and improvement >= threshold else EvidenceVerdict.FAIL
        )
        records.append({
            "TARGET_ISSUE": f"{family.upper()}_{finding.state}",
            "PRIMARY_PARAMETER": participating[0], "SUPPORTING_PARAMETER": participating[1:],
            "DIAGNOSIS_EVIDENCE": finding.to_dict(), "REASONABLE_INTERVAL": [low, high],
            "SOURCE_METRIC": before, "CANDIDATE_METRIC": after,
            "SOURCE_ERROR": error(before) if before is not None else None,
            "CANDIDATE_ERROR": error(after) if after is not None else None,
            "IMPROVEMENT": improvement, "MINIMUM_IMPROVEMENT": threshold,
            "DIRECTION_SUPPORTED": direction_ok, "VERDICT": verdict.value,
            **({"SATURATION_P50_CEILING": _SATURATION_P50_CEILING,
                "SATURATION_P90_CEILING": _SATURATION_P90_CEILING,
                "SOURCE_LOW_SATURATION_MEAN": source_low_sat_mean,
                "CANDIDATE_LOW_SATURATION_MEAN": candidate_low_sat_mean} if family == "saturation" else {}),
        })
    unsupported = [name for name in active if name not in supported]
    inconclusive = bool(unsupported) or any(row["VERDICT"] == "INCONCLUSIVE" for row in records)
    verdict = EvidenceVerdict.INCONCLUSIVE if inconclusive else (
        EvidenceVerdict.PASS if records and all(row["VERDICT"] == "PASS" for row in records) else EvidenceVerdict.FAIL
    )
    return QualityMetricEvidence(
        {"OBJECTIVE_DIAGNOSIS": diagnosis.to_dict()},
        {"ISSUES": _json_safe(records)},
        {"UNSUPPORTED_ADJUSTMENT": bool(unsupported), "UNSUPPORTED_PARAMETERS": unsupported},
        verdict, "DIAGNOSED_ERROR_REDUCED" if verdict == EvidenceVerdict.PASS else (
            "INSUFFICIENT_TARGET_EVIDENCE" if inconclusive else "DIAGNOSED_ERROR_REDUCTION_NOT_PROVEN"
        ),
    )


def _reference_target_evidence(source, candidate, parameters, decision, input_order):
    from .reference_integration import candidate_reference_values, reference_decision_digest, validate_reference_binding

    validate_reference_binding(decision, source, parameters, input_order=input_order)
    active = tuple(name for name, value in parameters.values().items() if value != 0.0)
    if not active:
        return _not_applicable({}, {}, {}, "NEUTRAL_PARAMETERS_HAVE_NO_REFERENCE_ADJUSTMENT")
    measured = candidate_reference_values(candidate, decision, input_order=input_order)
    source_values, reference_values = decision.target.values(), decision.reference.values()
    rows = []
    for name in active:
        before, after, target = source_values[name], measured[name], reference_values[name]
        # Exposure's frozen profile is log2(encoded mean). Use the existing
        # quality minimum in its encoded-luminance domain, not EV units.
        if name == "exposure":
            before, after, target = 2 ** before, 2 ** after, 2 ** target
        improvement = abs(target - before) - abs(target - after)
        dimension = next(item for item in decision.dimensions if item.name == name)
        reliable = dimension.confidence >= _TARGET_CONFIDENCE_MIN
        verdict = EvidenceVerdict.INCONCLUSIVE if not reliable else (
            EvidenceVerdict.PASS if improvement >= _MIN_TARGET_DELTA[name] else EvidenceVerdict.FAIL
        )
        rows.append({"PARAMETER": name, "SOURCE_METRIC": before, "REFERENCE_METRIC": target,
                     "CANDIDATE_METRIC": after, "IMPROVEMENT": improvement,
                     "MINIMUM_IMPROVEMENT": _MIN_TARGET_DELTA[name], "VERDICT": verdict.value})
    verdict = EvidenceVerdict.INCONCLUSIVE if any(row["VERDICT"] == "INCONCLUSIVE" for row in rows) else (
        EvidenceVerdict.PASS if all(row["VERDICT"] == "PASS" for row in rows) else EvidenceVerdict.FAIL
    )
    return QualityMetricEvidence(
        {"INTENT": "REFERENCE_COLOR", "REFERENCE_SOURCE_FINGERPRINT": decision.reference.source.encoded_sha256,
         "REFERENCE_DECISION_DIGEST": reference_decision_digest(decision)},
        {"ISSUES": rows}, {}, verdict,
        "REFERENCE_ERROR_REDUCED" if verdict == EvidenceVerdict.PASS else "REFERENCE_ERROR_REDUCTION_NOT_PROVEN",
    )


def evaluate_quality_evidence(
    source: np.ndarray,
    candidate: np.ndarray,
    parameters: CorrectionParameters,
    *,
    input_order: str = "RGB",
    active_parameters: Iterable[str] | None = None,
    source_fingerprint: str | None = None,
    parameter_decision_digest: str | None = None,
    objective_diagnosis: ObjectiveColorDiagnosis | None = None,
    person_regions: Iterable[Sequence[int]] = (),
    source_format: str | None = None,
    expected_output_format: str | None = None,
    candidate_format: str | None = None,
    reference_decision=None,
) -> QualityEvidence:
    """Return deterministic source/candidate evidence without changing pixels."""

    if type(parameters) is not CorrectionParameters:
        raise TypeError("QUALITY_EVIDENCE_REQUIRES_CORRECTION_PARAMETERS")
    source_array = np.asarray(source)
    candidate_array = np.asarray(candidate)
    if objective_diagnosis is not None:
        if type(objective_diagnosis) is not ObjectiveColorDiagnosis:
            raise TypeError("QUALITY_EVIDENCE_REQUIRES_OBJECTIVE_DIAGNOSIS")
        actual_fingerprint = compute_source_fingerprint(source_array, input_order=input_order)
        if objective_diagnosis.source_fingerprint != actual_fingerprint or (
            source_fingerprint is not None and source_fingerprint != actual_fingerprint
        ):
            raise ValueError("QUALITY_DIAGNOSIS_SOURCE_IDENTITY_MISMATCH")
    if source_array.shape != candidate_array.shape:
        raise ValueError("QUALITY_EVIDENCE_DIMENSION_MISMATCH")
    source_rgb, source_alpha, source_mask = _rgb01(source_array, input_order)
    candidate_rgb, candidate_alpha, candidate_mask = _rgb01(candidate_array, input_order)
    if not np.array_equal(source_mask, candidate_mask) or int(np.count_nonzero(source_mask)) < _MIN_ANALYSIS_PIXELS:
        raise ValueError("QUALITY_EVIDENCE_VISIBLE_PIXEL_CONTRACT_INVALID")

    parameter_values = parameters.values()
    derived_active = tuple(name for name in PARAMETER_SPECS if parameter_values[name] != 0.0)
    active = tuple(active_parameters) if active_parameters is not None else derived_active
    if active != derived_active or len(set(active)) != len(active):
        raise ValueError("QUALITY_EVIDENCE_ACTIVE_PARAMETER_MISMATCH")

    source_lab = cv2.cvtColor(source_rgb, cv2.COLOR_RGB2LAB)
    candidate_lab = cv2.cvtColor(candidate_rgb, cv2.COLOR_RGB2LAB)
    source_tone = _tone_metrics(source_rgb, source_lab, source_mask)
    candidate_tone = _tone_metrics(candidate_rgb, candidate_lab, source_mask)
    source_luminance = source_lab[..., 0] / 100.0
    candidate_luminance = candidate_lab[..., 0] / 100.0
    highlight_region = source_mask & (source_luminance >= 0.65)
    shadow_region = source_mask & (source_luminance <= 0.35)
    if np.count_nonzero(highlight_region) < _MIN_ANALYSIS_PIXELS:
        highlight_region = source_mask & (
            source_luminance >= _masked_percentile(source_luminance, source_mask, 75)
        )
    if np.count_nonzero(shadow_region) < _MIN_ANALYSIS_PIXELS:
        shadow_region = source_mask & (
            source_luminance <= _masked_percentile(source_luminance, source_mask, 25)
        )
    source_tone["highlight_region_mean"] = float(np.mean(source_luminance[highlight_region]))
    candidate_tone["highlight_region_mean"] = float(np.mean(candidate_luminance[highlight_region]))
    source_tone["shadow_region_mean"] = float(np.mean(source_luminance[shadow_region]))
    candidate_tone["shadow_region_mean"] = float(np.mean(candidate_luminance[shadow_region]))
    tone_delta = _metric_delta(source_tone, candidate_tone)
    source_color = _color_metrics(source_rgb, source_lab, source_mask)
    candidate_color = _color_metrics(candidate_rgb, candidate_lab, source_mask)
    color_delta = _metric_delta(source_color, candidate_color)

    source_chroma = np.linalg.norm(source_lab[..., 1:3], axis=2)
    source_l = source_lab[..., 0] / 100.0
    rgb8 = np.clip(np.rint(source_rgb * 255.0), 0, 255).astype(np.uint8)
    ycrcb = cv2.cvtColor(rgb8, cv2.COLOR_RGB2YCrCb)
    skin = source_mask & (ycrcb[..., 1] >= 133) & (ycrcb[..., 1] <= 180) & (ycrcb[..., 2] >= 77) & (ycrcb[..., 2] <= 135)
    regions = tuple(tuple(int(value) for value in region) for region in person_regions)
    if regions:
        skin &= _region_mask(source_mask.shape, regions)
    neutral = source_mask & (source_chroma <= 18.0) & (source_l >= 0.08) & (source_l <= 0.96) & ~skin
    brand = source_mask & (source_chroma >= 35.0) & ~skin

    source_neutral = _mask_lab_metrics(source_lab, neutral)
    candidate_neutral = _mask_lab_metrics(candidate_lab, neutral)
    neutral_delta = _metric_delta(source_neutral, candidate_neutral)
    source_skin = _mask_lab_metrics(source_lab, skin)
    candidate_skin = _mask_lab_metrics(candidate_lab, skin)
    skin_delta = _metric_delta(source_skin, candidate_skin)

    source_hsv = cv2.cvtColor(source_rgb, cv2.COLOR_RGB2HSV)
    candidate_hsv = cv2.cvtColor(candidate_rgb, cv2.COLOR_RGB2HSV)
    low_sat = source_mask & (source_hsv[..., 1] >= 0.03) & (source_hsv[..., 1] <= 0.45)
    source_low_sat_mean = float(np.mean(source_hsv[..., 1][low_sat])) if np.count_nonzero(low_sat) >= _MIN_ANALYSIS_PIXELS else None
    candidate_low_sat_mean = float(np.mean(candidate_hsv[..., 1][low_sat])) if np.count_nonzero(low_sat) >= _MIN_ANALYSIS_PIXELS else None

    # Target residuals use the same luminance domain as Objective Diagnosis;
    # the pre-existing perceptual-Lab protection metrics remain separate.
    target_tones = []
    diagnostic_source_l = source_rgb @ np.asarray(_DIAGNOSTIC_LUMINANCE_WEIGHTS, dtype=np.float32)
    target_highlights = source_mask & (diagnostic_source_l >= _TARGET_INTERVALS["highlights"][1])
    target_shadows = source_mask & (diagnostic_source_l <= _TARGET_INTERVALS["shadows"][0])
    for rgb in (source_rgb, candidate_rgb):
        luminance = rgb @ np.asarray(_DIAGNOSTIC_LUMINANCE_WEIGHTS, dtype=np.float32)
        selected = luminance[source_mask]
        target_tones.append({
            "p50": float(np.median(selected)),
            "contrast_range": float(np.percentile(selected, 95) - np.percentile(selected, 5)),
            "highlight_region_mean": float(np.mean(luminance[target_highlights])) if target_highlights.any() else None,
            "shadow_region_mean": float(np.mean(luminance[target_shadows])) if target_shadows.any() else None,
        })
    targeted = _target_evidence(
            objective_diagnosis,
            active,
            parameter_values,
            target_tones[0],
            target_tones[1],
            source_color,
            candidate_color,
            source_neutral,
            candidate_neutral,
            source_low_sat_mean,
            candidate_low_sat_mean,
    )
    if reference_decision is not None:
        targeted = _reference_target_evidence(
            source_array, candidate_array, parameters, reference_decision, input_order,
        )

    tone_active = bool(set(active) & {"exposure", "brightness", "contrast", "highlights", "shadows"})
    exposure_pass = tone_active or abs(tone_delta["p50"]) <= _MAX_UNINTENDED_TONE_SHIFT
    exposure = _metric(source_tone, candidate_tone, tone_delta, exposure_pass, "INTENDED_TONE_CHANGE" if tone_active else ("UNINTENDED_TONE_SHIFT_WITHIN_LIMIT" if exposure_pass else "UNINTENDED_TONE_SHIFT_EXCEEDED"))

    wb_active = bool(set(active) & {"temperature", "tint"})
    neutral_available = source_neutral["median_a"] is not None
    if not neutral_available:
        white_balance = _inconclusive(source_neutral, candidate_neutral, neutral_delta, "NEUTRAL_WHITE_BALANCE_EVIDENCE_UNAVAILABLE")
    else:
        source_distance = float(np.hypot(source_neutral["median_a"] - 1.5, source_neutral["median_b"] - 2.4))
        candidate_distance = float(np.hypot(candidate_neutral["median_a"] - 1.5, candidate_neutral["median_b"] - 2.4))
        wb_pass = (candidate_distance <= source_distance + 0.75) if wb_active else (candidate_distance - source_distance <= _MAX_UNINTENDED_NEUTRAL_SHIFT)
        white_balance = _metric(
            {**source_neutral, "distance_to_neutral_reference": source_distance},
            {**candidate_neutral, "distance_to_neutral_reference": candidate_distance},
            {**neutral_delta, "distance_to_neutral_reference": candidate_distance - source_distance},
            wb_pass,
            "INTENDED_WHITE_BALANCE_MOVES_TOWARD_REFERENCE" if wb_active and wb_pass else ("WHITE_BALANCE_PROTECTED" if wb_pass else "WHITE_BALANCE_DEGRADED"),
        )

    if neutral_available:
        source_abs = (abs(float(source_neutral["median_a"])), abs(float(source_neutral["median_b"])))
        candidate_abs = (abs(float(candidate_neutral["median_a"])), abs(float(candidate_neutral["median_b"])))
        cast_pass = (
            (candidate_abs[0] <= _MAX_NEUTRAL_AXIS_ABS[0] or candidate_abs[0] <= source_abs[0] + 0.75)
            and (candidate_abs[1] <= _MAX_NEUTRAL_AXIS_ABS[1] or candidate_abs[1] <= source_abs[1] + 0.75)
        )
        color_cast = _metric(source_neutral, candidate_neutral, neutral_delta, cast_pass, "NO_NEW_ABNORMAL_NEUTRAL_CAST" if cast_pass else "NEW_OR_WORSENED_NEUTRAL_COLOR_CAST")
    else:
        color_cast = _inconclusive(source_neutral, candidate_neutral, neutral_delta, "COLOR_CAST_NEUTRAL_EVIDENCE_UNAVAILABLE")

    contrast_active = "contrast" in active
    dynamic_delta = tone_delta["dynamic_range"]
    contrast_pass = contrast_active or dynamic_delta >= -_MAX_DYNAMIC_RANGE_LOSS
    contrast = _metric(source_tone["dynamic_range"], candidate_tone["dynamic_range"], dynamic_delta, contrast_pass, "INTENDED_CONTRAST_CHANGE" if contrast_active else ("DYNAMIC_RANGE_PRESERVED" if contrast_pass else "UNINTENDED_DYNAMIC_RANGE_COLLAPSE"))

    saturation_active = bool(set(active) & {"saturation", "vibrance"})
    saturation_shift = color_delta["saturation_mean"]
    saturation_pass = (
        (candidate_color["saturation_mean"] <= 0.92 or candidate_color["saturation_mean"] <= source_color["saturation_mean"] + 0.20)
        and (candidate_color["saturation_mean"] >= 0.02 or candidate_color["saturation_mean"] >= source_color["saturation_mean"] - 0.25)
    )
    saturation = _metric(source_color, candidate_color, color_delta, saturation_pass, "INTENDED_SATURATION_CHANGE_WITHIN_SAFETY_LIMIT" if saturation_active and saturation_pass else ("SATURATION_DISTRIBUTION_PROTECTED" if saturation_pass else "SATURATION_DEGRADATION"))

    highlight_growth = tone_delta["highlight_clip_ratio"]
    shadow_growth = tone_delta["shadow_clip_ratio"]
    highlight_pass = highlight_growth <= _MAX_NEW_LUMINANCE_CLIP
    shadow_pass = shadow_growth <= _MAX_NEW_LUMINANCE_CLIP
    highlight = _metric(source_tone, candidate_tone, tone_delta, highlight_pass, "HIGHLIGHT_DETAIL_PROTECTED" if highlight_pass else "NEW_HIGHLIGHT_CLIPPING")
    shadow = _metric(source_tone, candidate_tone, tone_delta, shadow_pass, "SHADOW_DETAIL_PROTECTED" if shadow_pass else "NEW_SHADOW_CLIPPING")

    lab_delta = candidate_lab - source_lab
    delta_e = np.linalg.norm(lab_delta, axis=2)
    if np.count_nonzero(skin) < _MIN_ANALYSIS_PIXELS:
        skin_evidence = _not_applicable(source_skin, candidate_skin, skin_delta, "NO_RELIABLE_SKIN_REGION")
    else:
        skin_median = float(np.median(delta_e[skin]))
        skin_p95 = float(np.percentile(delta_e[skin], 95))
        skin_chroma_delta = abs(float(skin_delta["median_chroma"]))
        skin_pass = skin_median <= _MAX_SKIN_DELTA_E_MEDIAN and skin_p95 <= _MAX_SKIN_DELTA_E_P95 and skin_chroma_delta <= _MAX_SKIN_CHROMA_DELTA
        skin_evidence = _metric({**source_skin, "delta_e_median": 0.0, "delta_e_p95": 0.0}, {**candidate_skin, "delta_e_median": skin_median, "delta_e_p95": skin_p95}, {**skin_delta, "delta_e_median": skin_median, "delta_e_p95": skin_p95}, skin_pass, "SKIN_CHANGE_WITHIN_INTENDED_LIMIT" if skin_pass else "SKIN_COLOR_OR_TONE_DAMAGE")

    if not neutral_available:
        neutral_evidence = _not_applicable(source_neutral, candidate_neutral, neutral_delta, "NO_RELIABLE_NEUTRAL_REGION")
    else:
        neutral_ab_shift = float(np.hypot(neutral_delta["median_a"], neutral_delta["median_b"]))
        neutral_pass = wb_active or neutral_ab_shift <= _MAX_UNINTENDED_NEUTRAL_SHIFT
        if wb_active:
            neutral_pass = white_balance.verdict == EvidenceVerdict.PASS and color_cast.verdict == EvidenceVerdict.PASS
        neutral_evidence = _metric(source_neutral, candidate_neutral, {**neutral_delta, "median_ab_shift": neutral_ab_shift}, neutral_pass, "INTENDED_NEUTRAL_ADJUSTMENT_SAFE" if wb_active and neutral_pass else ("NEUTRAL_REGION_PROTECTED" if neutral_pass else "NEUTRAL_REGION_COLOR_CONTAMINATION"))

    if np.count_nonzero(brand) < _MIN_ANALYSIS_PIXELS:
        brand_evidence = _not_applicable({"pixel_count": int(np.count_nonzero(brand))}, {"pixel_count": int(np.count_nonzero(brand))}, {}, "NO_RELIABLE_STRONG_COLOR_REGION")
    else:
        hue_delta = _circular_hue_delta(source_hsv[..., 0][brand], candidate_hsv[..., 0][brand])
        brand_hue_median = float(np.median(hue_delta))
        brand_hue_p95 = float(np.percentile(hue_delta, 95))
        hue_limit = _MAX_WB_BRAND_HUE_SHIFT_DEGREES if wb_active else _MAX_BRAND_HUE_SHIFT_DEGREES
        brand_pass = brand_hue_median <= hue_limit and brand_hue_p95 <= hue_limit * 2.0
        brand_evidence = _metric({"pixel_count": int(np.count_nonzero(brand)), "hue_shift_median_degrees": 0.0, "hue_shift_p95_degrees": 0.0}, {"pixel_count": int(np.count_nonzero(brand)), "hue_shift_median_degrees": brand_hue_median, "hue_shift_p95_degrees": brand_hue_p95}, {"hue_shift_median_degrees": brand_hue_median, "hue_shift_p95_degrees": brand_hue_p95}, brand_pass, "STRONG_COLOR_HUE_STABLE" if brand_pass else "BRAND_OR_STRONG_COLOR_HUE_DRIFT")

    channel_low_growth = tone_delta["channel_low_clip_ratio"]
    channel_high_growth = tone_delta["channel_high_clip_ratio"]
    clipping_pass = channel_low_growth <= _MAX_NEW_CHANNEL_CLIP and channel_high_growth <= _MAX_NEW_CHANNEL_CLIP
    clipping = _metric({"channel_low_clip_ratio": source_tone["channel_low_clip_ratio"], "channel_high_clip_ratio": source_tone["channel_high_clip_ratio"]}, {"channel_low_clip_ratio": candidate_tone["channel_low_clip_ratio"], "channel_high_clip_ratio": candidate_tone["channel_high_clip_ratio"]}, {"channel_low_clip_ratio": channel_low_growth, "channel_high_clip_ratio": channel_high_growth}, clipping_pass, "CHANNEL_CLIPPING_NOT_MATERIALLY_INCREASED" if clipping_pass else "NEW_CHANNEL_CLIPPING")
    dynamic_pass = dynamic_delta >= -_MAX_DYNAMIC_RANGE_LOSS or ("contrast" in active and parameter_values["contrast"] < 0.0)
    dynamic = _metric(source_tone["dynamic_range"], candidate_tone["dynamic_range"], dynamic_delta, dynamic_pass, "DYNAMIC_RANGE_CHANGE_IS_INTENDED_OR_BOUNDED" if dynamic_pass else "DYNAMIC_RANGE_LOSS_EXCEEDED")

    source_artifact = _artifact_metrics(source_l, source_mask)
    candidate_artifact = _artifact_metrics(candidate_lab[..., 0] / 100.0, source_mask)
    artifact_delta = _metric_delta(source_artifact, candidate_artifact)
    bin_ratio = candidate_artifact["occupied_luminance_bins"] / max(1, source_artifact["occupied_luminance_bins"])
    posterization_pass = not (source_artifact["occupied_luminance_bins"] >= 32 and candidate_artifact["occupied_luminance_bins"] <= _POSTERIZATION_MAX_BINS and bin_ratio < _POSTERIZATION_BIN_RATIO_LIMIT)
    posterization = _metric({**source_artifact, "bin_ratio": 1.0}, {**candidate_artifact, "bin_ratio": bin_ratio}, {**artifact_delta, "bin_ratio": bin_ratio - 1.0}, posterization_pass, "LUMINANCE_LEVEL_OCCUPANCY_PRESERVED" if posterization_pass else "POSTERIZATION_LEVEL_COLLAPSE")
    banding = _banding_evidence(source_l, candidate_luminance, source_mask)

    channel_saturation_pass = clipping_pass and candidate_color["saturation_p90"] <= max(0.98, source_color["saturation_p90"] + 0.15)
    channel_saturation = _metric({"saturation_p90": source_color["saturation_p90"], "channel_low_clip_ratio": source_tone["channel_low_clip_ratio"], "channel_high_clip_ratio": source_tone["channel_high_clip_ratio"]}, {"saturation_p90": candidate_color["saturation_p90"], "channel_low_clip_ratio": candidate_tone["channel_low_clip_ratio"], "channel_high_clip_ratio": candidate_tone["channel_high_clip_ratio"]}, {"saturation_p90": color_delta["saturation_p90"], "channel_low_clip_ratio": channel_low_growth, "channel_high_clip_ratio": channel_high_growth}, channel_saturation_pass, "CHANNEL_SATURATION_WITHIN_SOURCE_RELATIVE_LIMIT" if channel_saturation_pass else "CHANNEL_SATURATION_OR_CLIPPING_RISK")

    alpha_pass = (source_alpha is None and candidate_alpha is None) or (source_alpha is not None and candidate_alpha is not None and np.array_equal(source_alpha, candidate_alpha))
    alpha = _metric({"present": source_alpha is not None, "sha256": _array_fingerprint(source_alpha) if source_alpha is not None else None}, {"present": candidate_alpha is not None, "sha256": _array_fingerprint(candidate_alpha) if candidate_alpha is not None else None}, {"changed": not alpha_pass}, alpha_pass, "D3_REUSED_ALPHA_INTEGRITY_PASS" if alpha_pass else "ALPHA_INTEGRITY_FAILED")
    dimension_pass = source_array.shape == candidate_array.shape
    dimension = _metric(list(source_array.shape), list(candidate_array.shape), {"changed": not dimension_pass}, dimension_pass, "D3_REUSED_DIMENSION_INTEGRITY_PASS" if dimension_pass else "DIMENSION_INTEGRITY_FAILED")
    source_format_record = {"SOURCE_FORMAT": source_format, "EXPECTED_OUTPUT_FORMAT": expected_output_format}
    candidate_format_record = {"ACTUAL_CANDIDATE_FORMAT": candidate_format}
    if not all((source_format, expected_output_format, candidate_format)):
        format_evidence = _inconclusive(source_format_record, candidate_format_record, {}, "ENCODED_FORMAT_EVIDENCE_MISSING")
    else:
        format_pass = candidate_format.upper() == expected_output_format.upper()
        format_evidence = _metric(source_format_record, candidate_format_record, {"MATCHES_OUTPUT_CONTRACT": format_pass}, format_pass, "ENCODED_FORMAT_MATCHES_OUTPUT_CONTRACT" if format_pass else "ENCODED_FORMAT_VIOLATES_OUTPUT_CONTRACT")

    protected_items = (exposure, white_balance, color_cast, contrast, saturation, highlight, shadow, skin_evidence, neutral_evidence, brand_evidence, clipping, dynamic, channel_saturation, alpha, dimension, format_evidence)
    artifact_items = (banding, posterization)
    protected_damage = any(item.verdict == EvidenceVerdict.FAIL for item in protected_items)
    new_artifact = any(item.verdict == EvidenceVerdict.FAIL for item in artifact_items)
    targeted_gain = targeted.verdict == EvidenceVerdict.PASS
    if protected_damage or new_artifact:
        net_benefit = QualityNetBenefit.NEGATIVE
    elif targeted.verdict == EvidenceVerdict.INCONCLUSIVE or format_evidence.verdict == EvidenceVerdict.INCONCLUSIVE:
        net_benefit = QualityNetBenefit.INCONCLUSIVE
    elif not active or targeted.verdict == EvidenceVerdict.FAIL:
        net_benefit = QualityNetBenefit.NEUTRAL
    else:
        net_benefit = QualityNetBenefit.POSITIVE

    parameter_digest = _digest(parameters.to_record(), "hdde.quality-parameters.v1:")
    evidence_values: dict[str, Any] = {
        "schema_version": QUALITY_EVIDENCE_SCHEMA_VERSION,
        "engine_version": QUALITY_EVIDENCE_ENGINE_VERSION,
        "source_fingerprint": source_fingerprint or _array_fingerprint(source_array),
        "candidate_fingerprint": _array_fingerprint(candidate_array),
        "parameter_digest": parameter_digest,
        "parameter_decision_digest": parameter_decision_digest,
        "active_parameters": list(active),
        "metrics": {
            "targeted_issue_improvement": targeted.to_record(),
            "exposure_quality": exposure.to_record(),
            "white_balance_quality": white_balance.to_record(),
            "color_cast_quality": color_cast.to_record(),
            "contrast_quality": contrast.to_record(),
            "saturation_quality": saturation.to_record(),
            "highlight_quality": highlight.to_record(),
            "shadow_quality": shadow.to_record(),
            "skin_protection": skin_evidence.to_record(),
            "neutral_protection": neutral_evidence.to_record(),
            "brand_color_protection": brand_evidence.to_record(),
            "clipping_delta": clipping.to_record(),
            "dynamic_range_delta": dynamic.to_record(),
            "banding_risk": banding.to_record(),
            "posterization_risk": posterization.to_record(),
            "channel_saturation_risk": channel_saturation.to_record(),
            "alpha_integrity": alpha.to_record(),
            "dimension_integrity": dimension.to_record(),
            "format_integrity": format_evidence.to_record(),
        },
        "targeted_gain": targeted_gain,
        "protected_damage": protected_damage,
        "new_artifact": new_artifact,
        "net_benefit": net_benefit.value,
    }
    evidence_fingerprint = _digest(evidence_values, "hdde.quality-evidence.v1:")
    return QualityEvidence(
        QUALITY_EVIDENCE_SCHEMA_VERSION,
        QUALITY_EVIDENCE_ENGINE_VERSION,
        str(evidence_values["source_fingerprint"]),
        str(evidence_values["candidate_fingerprint"]),
        parameter_digest,
        parameter_decision_digest,
        active,
        targeted,
        exposure,
        white_balance,
        color_cast,
        contrast,
        saturation,
        highlight,
        shadow,
        skin_evidence,
        neutral_evidence,
        brand_evidence,
        clipping,
        dynamic,
        banding,
        posterization,
        channel_saturation,
        alpha,
        dimension,
        format_evidence,
        targeted_gain,
        protected_damage,
        new_artifact,
        net_benefit,
        evidence_fingerprint,
    )


__all__ = [
    "QUALITY_EVIDENCE_SCHEMA_VERSION",
    "QUALITY_EVIDENCE_ENGINE_VERSION",
    "EvidenceVerdict",
    "QualityNetBenefit",
    "QualityMetricEvidence",
    "QualityEvidence",
    "evaluate_quality_evidence",
]
