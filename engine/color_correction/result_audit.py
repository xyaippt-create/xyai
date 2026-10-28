"""D3 Candidate-vs-Original result audit for HDDE V0.5.6.

D3 does not accept an externally supplied D2 DTO.  Its public entrypoint calls
the frozen D2 factory itself, then immediately applies independent output gates.
Color candidates remain review-only even when every technical gate passes.
"""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Sequence

import cv2
import numpy as np
from PIL import Image

from .color_management import (
    ManagedColorSource,
    encode_color_managed_candidate,
    validate_managed_color_source_provenance,
    verify_color_managed_output,
)
from .objective_diagnosis import build_objective_diagnosis

from .candidate_generation import (
    D2_ENGINE_VERSION,
    D2_SCHEMA_VERSION,
    CandidateExecutor,
    CandidateType,
    CorrectionBudget,
    _D2CandidateResult,
    generate_candidate,
)
from .executors.basic_correction import (
    BASIC_CORRECTION_EXECUTOR_VERSION,
    BasicCorrectionSafetyError,
    execute_basic_correction,
)
from .parameters import CorrectionParameters
from .parameter_decision import bound_parameter_decision
from .quality_evidence import (
    QualityEvidence,
    QualityNetBenefit,
    evaluate_quality_evidence,
)
from .usability_decision import (
    ColorUsabilityDecision,
    D1Action,
    ExposureStatus,
    _resolve_bound_person_regions,
    analyze_color_usability,
    compute_source_fingerprint,
)


D3_SCHEMA_VERSION = "hdde.result-audit.schema.v1"
D3_AUDIT_VERSION = "hdde.d3-result-audit.v1.4"
D2_CANDIDATE_IDENTITY_VERSION = "hdde.d2-candidate-identity.v3"
D3_BASIC_REPLAY_SCHEMA_VERSION = "hdde.basic-color-replay.schema.v1"
D3_BASIC_REPLAY_AUDIT_VERSION = "hdde.d3-basic-color-replay.v1"
D3_BASIC_CANDIDATE_IDENTITY_VERSION = "hdde.basic-color-candidate-identity.v1"
# Opaque-distribution and local-connectivity facts remain diagnostic only.
# Candidate authority comes from a source-and-parameter replay, never from D2
# candidate pixels or the mutable per-attempt pixel trace.
_TRANSPARENT_EDGE_OPAQUE_REFERENCE_QUANTILE = 0.99
_TRANSPARENT_EDGE_MIN_OPAQUE_REFERENCE_PIXELS = 16
_TRANSPARENT_EDGE_CHANNEL_TOLERANCE = 2.0 / 255.0
_TRANSPARENT_EDGE_REFERENCE_DISTANCE_FRACTION = 0.02
_TRANSPARENT_EDGE_MIN_REFERENCE_DISTANCE_PIXELS = 4
_TRANSPARENT_EDGE_MAX_REFERENCE_DISTANCE_PIXELS = 16
_COLOR_CAST_NEUTRAL_CHROMA_LIMIT = 12.0
_COLOR_CAST_NEUTRAL_MIN_COVERAGE = 0.003
_COLOR_CAST_NEUTRAL_MIN_PIXELS = 64
_COLOR_CAST_DIRECTION_TOLERANCE = 0.75
_COLOR_CAST_MAX_A_SHIFT = 12.0
_COLOR_CAST_MAX_B_SHIFT = 14.0
_COLOR_CAST_MAX_VECTOR_SHIFT = 17.0
_COLOR_CAST_MAX_COMBINED_CONTROL_STRENGTH = 1.50
_COLOR_CAST_MAX_POSITIVE_SATURATION_GROWTH = 0.35
_COLOR_CAST_MAX_NEGATIVE_SATURATION_GROWTH = 0.02


class AcceptanceAuthority(str, Enum):
    AUTO_PROVEN = "AUTO_PROVEN"
    REVIEW_ONLY = "REVIEW_ONLY"
    NONE = "NONE"


class FinalAction(str, Enum):
    ACCEPT_CORRECTED = "ACCEPT_CORRECTED"
    ACCEPT_ORIGINAL = "ACCEPT_ORIGINAL"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class NetGain(str, Enum):
    POSITIVE = "POSITIVE"
    INSUFFICIENT = "INSUFFICIENT"
    NEGATIVE = "NEGATIVE"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class _D3AuditResult:
    schema_version: str
    audit_version: str
    status: str
    d2_candidate_identity: str | None
    d2_schema_version: str | None
    d2_engine_version: str | None
    audit_metrics: dict[str, Any]
    pass_status: dict[str, str]
    net_gain: NetGain
    acceptance_authority: AcceptanceAuthority
    final_action: FinalAction
    blocker: str | None

    def to_record(self) -> dict[str, Any]:
        """Return a D4-safe record without image bytes, paths, or identity data."""

        return {
            "schema_version": self.schema_version,
            "audit_version": self.audit_version,
            "status": self.status,
            "D2_CANDIDATE_IDENTITY": self.d2_candidate_identity,
            "D2_SCHEMA_VERSION": self.d2_schema_version,
            "D2_ENGINE_VERSION": self.d2_engine_version,
            "AUDIT_METRICS": dict(self.audit_metrics),
            "PASS_STATUS": dict(self.pass_status),
            "NET_GAIN": self.net_gain.value,
            "ACCEPTANCE_AUTHORITY": self.acceptance_authority.value,
            "FINAL_ACTION": self.final_action.value,
            "BLOCKER": self.blocker,
            "PRIVACY": {
                "original_image_saved": False,
                "candidate_image_saved": False,
                "filesystem_path_saved": False,
                "person_identity_saved": False,
            },
        }


_BASIC_REPLAY_PASS_NAMES = (
    "PARAMETER_CONTRACT_PASS",
    "DTYPE_PASS",
    "DIMENSIONS_PASS",
    "ALPHA_PASS",
    "FINITE_PASS",
    "CHANNEL_RANGE_PASS",
    "CLIPPING_PASS",
    "HIGHLIGHT_PASS",
    "SHADOW_PASS",
    "COLOR_DIRECTION_PASS",
    "COMBINED_COLOR_BUDGET_PASS",
    "SATURATION_BEHAVIOR_PASS",
    "COLOR_CAST_PASS",
    "NEUTRAL_PASS",
    "REPLAY_PASS",
    "OVERALL_EXECUTION_SAFETY_PASS",
)


@dataclass(frozen=True)
class _BasicCorrectionAuditResult:
    schema_version: str
    audit_version: str
    executor_version: str
    status: str
    candidate_identity: str | None
    parameter_record: dict[str, Any] | None
    audit_metrics: dict[str, Any]
    pass_status: dict[str, str]
    acceptance_authority: AcceptanceAuthority
    final_action: FinalAction
    blocker: str | None

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "audit_version": self.audit_version,
            "executor_version": self.executor_version,
            "status": self.status,
            "CANDIDATE_IDENTITY": self.candidate_identity,
            "CORRECTION_PARAMETERS": (
                dict(self.parameter_record) if self.parameter_record is not None else None
            ),
            "AUDIT_METRICS": dict(self.audit_metrics),
            "PASS_STATUS": dict(self.pass_status),
            "ACCEPTANCE_AUTHORITY": self.acceptance_authority.value,
            "FINAL_ACTION": self.final_action.value,
            "BLOCKER": self.blocker,
            "PRIVACY": {
                "original_image_saved": False,
                "candidate_image_saved": False,
                "filesystem_path_saved": False,
            },
        }


def _basic_replay_blocked(
    blocker: str,
    *,
    parameter_record: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    pass_status: dict[str, str] | None = None,
) -> _BasicCorrectionAuditResult:
    passes = {name: "NO" for name in _BASIC_REPLAY_PASS_NAMES}
    if pass_status:
        passes.update(pass_status)
    return _BasicCorrectionAuditResult(
        D3_BASIC_REPLAY_SCHEMA_VERSION,
        D3_BASIC_REPLAY_AUDIT_VERSION,
        BASIC_CORRECTION_EXECUTOR_VERSION,
        "PROTECTION_BLOCKED",
        None,
        parameter_record,
        dict(metrics or {}),
        passes,
        AcceptanceAuthority.NONE,
        FinalAction.ACCEPT_ORIGINAL,
        blocker,
    )


def _basic_candidate_identity(
    original: np.ndarray,
    candidate: np.ndarray,
    parameters: CorrectionParameters,
    *,
    input_order: str,
) -> str:
    source_fingerprint = compute_source_fingerprint(original, input_order=input_order)
    candidate_array = np.ascontiguousarray(candidate)
    contract = {
        "source_fingerprint": source_fingerprint,
        "parameter_record": parameters.to_record(),
        "executor_version": BASIC_CORRECTION_EXECUTOR_VERSION,
        "candidate_shape": list(candidate_array.shape),
        "candidate_dtype": candidate_array.dtype.str,
    }
    digest = hashlib.sha256()
    digest.update(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    digest.update(candidate_array.tobytes(order="C"))
    return f"{D3_BASIC_CANDIDATE_IDENTITY_VERSION}:{digest.hexdigest()}"


def replay_basic_correction(
    original: np.ndarray,
    parameter_record: dict[str, Any],
    *,
    input_order: str = "RGB",
) -> np.ndarray:
    """Strictly deserialize and replay recorded controls from source pixels."""

    parameters = CorrectionParameters.from_record(parameter_record)
    return execute_basic_correction(
        original,
        parameters,
        input_order=input_order,
    ).candidate_image


def _basic_color_cast_gate(
    original: np.ndarray,
    replayed: np.ndarray,
    parameters: CorrectionParameters,
    *,
    input_order: str,
) -> tuple[dict[str, Any], bool, bool, bool, bool]:
    """Independently bound requested color direction and aggregate risk."""

    source_rgb, _, source_visible = _as_rgb01(original, input_order)
    candidate_rgb, _, candidate_visible = _as_rgb01(replayed, input_order)
    if not np.array_equal(source_visible, candidate_visible):
        raise ValueError("basic color-cast audit visibility mismatch")
    source_lab = cv2.cvtColor(source_rgb.astype(np.float32), cv2.COLOR_RGB2LAB)
    candidate_lab = cv2.cvtColor(candidate_rgb.astype(np.float32), cv2.COLOR_RGB2LAB)
    source_chroma = np.linalg.norm(source_lab[..., 1:3], axis=2)
    source_lightness = source_lab[..., 0]
    neutral = (
        source_visible
        & (source_chroma <= _COLOR_CAST_NEUTRAL_CHROMA_LIMIT)
        & (source_lightness > 12.0)
        & (source_lightness < 94.0)
    )
    required_neutral = max(
        _COLOR_CAST_NEUTRAL_MIN_PIXELS,
        int(np.count_nonzero(source_visible) * _COLOR_CAST_NEUTRAL_MIN_COVERAGE),
    )
    evidence_mask = neutral if int(np.count_nonzero(neutral)) >= required_neutral else source_visible
    evidence_source_ab = np.median(source_lab[..., 1:3][evidence_mask], axis=0)
    evidence_candidate_ab = np.median(candidate_lab[..., 1:3][evidence_mask], axis=0)
    evidence_shift = evidence_candidate_ab - evidence_source_ab
    global_source_ab = np.median(source_lab[..., 1:3][source_visible], axis=0)
    global_candidate_ab = np.median(candidate_lab[..., 1:3][source_visible], axis=0)
    global_shift = global_candidate_ab - global_source_ab
    shift_vector = float(np.linalg.norm(evidence_shift))

    color_values = (
        parameters.temperature,
        parameters.tint,
        parameters.saturation,
        parameters.vibrance,
    )
    color_controls_neutral = all(value == 0.0 for value in color_values)
    requested_wb_vector = np.asarray(
        (parameters.tint, parameters.temperature),
        dtype=np.float64,
    )
    requested_wb_norm = float(np.linalg.norm(requested_wb_vector))
    direction_alignment = float(
        np.dot(requested_wb_vector, evidence_shift.astype(np.float64))
    )
    direction_pass = bool(
        requested_wb_norm == 0.0
        or direction_alignment
        >= -_COLOR_CAST_DIRECTION_TOLERANCE * requested_wb_norm
    )
    combined_strength = float(
        np.linalg.norm(np.asarray(color_values, dtype=np.float64) / 100.0)
    )
    combined_pass = combined_strength <= _COLOR_CAST_MAX_COMBINED_CONTROL_STRENGTH

    source_hsv = cv2.cvtColor(source_rgb.astype(np.float32), cv2.COLOR_RGB2HSV)
    candidate_hsv = cv2.cvtColor(candidate_rgb.astype(np.float32), cv2.COLOR_RGB2HSV)
    saturation_before = float(source_hsv[..., 1][source_visible].mean())
    saturation_after = float(candidate_hsv[..., 1][source_visible].mean())
    saturation_growth = saturation_after - saturation_before
    if parameters.saturation == 0.0 and parameters.vibrance == 0.0:
        saturation_behavior_pass = True
    elif parameters.saturation <= 0.0 and parameters.vibrance <= 0.0:
        saturation_behavior_pass = (
            saturation_growth <= _COLOR_CAST_MAX_NEGATIVE_SATURATION_GROWTH
        )
    elif parameters.saturation >= 0.0 and parameters.vibrance >= 0.0:
        saturation_behavior_pass = bool(
            saturation_growth <= _COLOR_CAST_MAX_POSITIVE_SATURATION_GROWTH
        )
    else:
        saturation_behavior_pass = bool(
            abs(saturation_growth) <= _COLOR_CAST_MAX_POSITIVE_SATURATION_GROWTH
        )

    if color_controls_neutral:
        magnitude_pass = bool(
            abs(float(evidence_shift[0])) <= _COLOR_CAST_DIRECTION_TOLERANCE
            and abs(float(evidence_shift[1])) <= _COLOR_CAST_DIRECTION_TOLERANCE
        )
    else:
        magnitude_pass = bool(
            abs(float(evidence_shift[0])) <= _COLOR_CAST_MAX_A_SHIFT
            and abs(float(evidence_shift[1])) <= _COLOR_CAST_MAX_B_SHIFT
            and shift_vector <= _COLOR_CAST_MAX_VECTOR_SHIFT
            and abs(float(global_shift[0])) <= _COLOR_CAST_MAX_A_SHIFT
            and abs(float(global_shift[1])) <= _COLOR_CAST_MAX_B_SHIFT
        )
    color_cast_pass = bool(
        direction_pass
        and magnitude_pass
        and combined_pass
        and saturation_behavior_pass
    )
    metrics = {
        "color_cast_evidence": "SOURCE_NEUTRAL_PIXELS" if evidence_mask is neutral else "SOURCE_GLOBAL_FALLBACK",
        "source_visible_pixel_count": int(np.count_nonzero(source_visible)),
        "source_neutral_pixel_count": int(np.count_nonzero(neutral)),
        "source_evidence_median_lab_ab": [round(float(value), 6) for value in evidence_source_ab],
        "candidate_evidence_median_lab_ab": [round(float(value), 6) for value in evidence_candidate_ab],
        "evidence_median_lab_ab_shift": [round(float(value), 6) for value in evidence_shift],
        "global_median_lab_ab_shift": [round(float(value), 6) for value in global_shift],
        "evidence_lab_shift_magnitude": round(shift_vector, 6),
        "requested_temperature_direction": int(np.sign(parameters.temperature)),
        "requested_tint_direction": int(np.sign(parameters.tint)),
        "requested_wb_direction_alignment": round(direction_alignment, 6),
        "combined_color_control_strength": round(combined_strength, 6),
        "combined_color_control_limit": _COLOR_CAST_MAX_COMBINED_CONTROL_STRENGTH,
        "executor_parameter_range_fractions": {
            "temperature": round(abs(parameters.temperature) / 100.0, 6),
            "tint": round(abs(parameters.tint) / 100.0, 6),
            "saturation": round(abs(parameters.saturation) / 100.0, 6),
            "vibrance": round(abs(parameters.vibrance) / 100.0, 6),
        },
        "mean_saturation_before": round(saturation_before, 6),
        "mean_saturation_after": round(saturation_after, 6),
        "mean_saturation_growth": round(saturation_growth, 6),
        "color_direction_pass": direction_pass,
        "color_magnitude_pass": magnitude_pass,
        "combined_color_budget_pass": combined_pass,
        "saturation_behavior_pass": saturation_behavior_pass,
    }
    return metrics, direction_pass, combined_pass, saturation_behavior_pass, color_cast_pass


def audit_basic_correction(
    original: np.ndarray,
    candidate: np.ndarray,
    parameter_record: dict[str, Any],
    *,
    input_order: str = "RGB",
) -> _BasicCorrectionAuditResult:
    """Audit a candidate by independently replaying the recorded controls.

    D60-02 does not grant automatic delivery authority. A non-neutral safe
    candidate remains review-only until the later product-quality gate exists.
    """

    try:
        parameters = CorrectionParameters.from_record(parameter_record)
    except (TypeError, ValueError):
        return _basic_replay_blocked("CORRECTION_PARAMETER_CONTRACT_INVALID")
    canonical_record = parameters.to_record()
    parameter_passes = {"PARAMETER_CONTRACT_PASS": "YES"}
    try:
        replay = execute_basic_correction(
            original,
            parameters,
            input_order=input_order,
        )
    except BasicCorrectionSafetyError as exc:
        return _basic_replay_blocked(
            "BASIC_CORRECTION_EXECUTION_SAFETY_FAILED",
            parameter_record=canonical_record,
            metrics=exc.metrics,
            pass_status=parameter_passes,
        )
    except (cv2.error, TypeError, ValueError):
        return _basic_replay_blocked(
            "BASIC_CORRECTION_REPLAY_FAILED",
            parameter_record=canonical_record,
            pass_status=parameter_passes,
        )

    original_array = np.asarray(original)
    candidate_array = np.asarray(candidate)
    replay_array = replay.candidate_image
    shape_match = bool(candidate_array.shape == original_array.shape == replay_array.shape)
    dtype_match = bool(candidate_array.dtype == original_array.dtype == replay_array.dtype)
    alpha_match = bool(
        original_array.ndim == 3
        and candidate_array.ndim == 3
        and original_array.shape[2] == candidate_array.shape[2]
        and (
            original_array.shape[2] == 3
            or np.array_equal(original_array[..., 3], candidate_array[..., 3])
        )
    )
    replay_match = bool(
        shape_match
        and dtype_match
        and np.array_equal(candidate_array, replay_array)
    )
    if shape_match and np.issubdtype(candidate_array.dtype, np.number):
        replay_max_abs_error = float(
            np.abs(candidate_array.astype(np.float64) - replay_array.astype(np.float64)).max(
                initial=0.0
            )
        )
    else:
        replay_max_abs_error = float("inf")

    execution_metrics = dict(replay.metrics)
    finite_pass = bool(execution_metrics.get("finite"))
    channel_range_pass = bool(
        float(execution_metrics.get("channel_min", -1.0)) >= 0.0
        and float(execution_metrics.get("channel_max", 2.0)) <= 1.0
    )
    clipping_pass = bool(
        float(execution_metrics.get("new_channel_low_clip_ratio", 1.0)) <= 0.002
        and float(execution_metrics.get("new_channel_high_clip_ratio", 1.0)) <= 0.002
    )
    highlight_pass = float(execution_metrics.get("highlight_clip_growth", 1.0)) <= 0.002
    shadow_pass = float(execution_metrics.get("shadow_clip_growth", 1.0)) <= 0.002
    try:
        (
            color_cast_metrics,
            color_direction_pass,
            combined_color_budget_pass,
            saturation_behavior_pass,
            color_cast_pass,
        ) = _basic_color_cast_gate(
            original_array,
            replay_array,
            parameters,
            input_order=input_order,
        )
    except (cv2.error, TypeError, ValueError):
        color_cast_metrics = {"color_cast_evidence": "UNAVAILABLE"}
        color_direction_pass = False
        combined_color_budget_pass = False
        saturation_behavior_pass = False
        color_cast_pass = False
    neutral_pass = bool(
        not parameters.is_neutral or np.array_equal(candidate_array, original_array)
    )
    overall = all(
        (
            shape_match,
            dtype_match,
            alpha_match,
            finite_pass,
            channel_range_pass,
            clipping_pass,
            highlight_pass,
            shadow_pass,
            color_direction_pass,
            combined_color_budget_pass,
            saturation_behavior_pass,
            color_cast_pass,
            neutral_pass,
            replay_match,
        )
    )
    passes = {
        "PARAMETER_CONTRACT_PASS": "YES",
        "DTYPE_PASS": _yes(dtype_match),
        "DIMENSIONS_PASS": _yes(shape_match),
        "ALPHA_PASS": _yes(alpha_match),
        "FINITE_PASS": _yes(finite_pass),
        "CHANNEL_RANGE_PASS": _yes(channel_range_pass),
        "CLIPPING_PASS": _yes(clipping_pass),
        "HIGHLIGHT_PASS": _yes(highlight_pass),
        "SHADOW_PASS": _yes(shadow_pass),
        "COLOR_DIRECTION_PASS": _yes(color_direction_pass),
        "COMBINED_COLOR_BUDGET_PASS": _yes(combined_color_budget_pass),
        "SATURATION_BEHAVIOR_PASS": _yes(saturation_behavior_pass),
        "COLOR_CAST_PASS": _yes(color_cast_pass),
        "NEUTRAL_PASS": _yes(neutral_pass),
        "REPLAY_PASS": _yes(replay_match),
        "OVERALL_EXECUTION_SAFETY_PASS": _yes(overall),
    }
    metrics = {
        **execution_metrics,
        **color_cast_metrics,
        "trusted_executor_reference_source": "D3_SOURCE_PARAMETER_REPLAY",
        "replay_exact_match": replay_match,
        "replay_max_abs_error": (
            round(replay_max_abs_error, 8)
            if np.isfinite(replay_max_abs_error)
            else None
        ),
    }
    if not overall:
        blocker = (
            "BASIC_CORRECTION_CANDIDATE_REPLAY_MISMATCH"
            if not replay_match
            else "BASIC_CORRECTION_EXECUTION_SAFETY_FAILED"
        )
        return _basic_replay_blocked(
            blocker,
            parameter_record=canonical_record,
            metrics=metrics,
            pass_status=passes,
        )

    identity = _basic_candidate_identity(
        original_array,
        candidate_array,
        parameters,
        input_order=input_order,
    )
    final_action = (
        FinalAction.ACCEPT_ORIGINAL
        if parameters.is_neutral
        else FinalAction.REVIEW_REQUIRED
    )
    authority = (
        AcceptanceAuthority.NONE
        if parameters.is_neutral
        else AcceptanceAuthority.REVIEW_ONLY
    )
    return _BasicCorrectionAuditResult(
        D3_BASIC_REPLAY_SCHEMA_VERSION,
        D3_BASIC_REPLAY_AUDIT_VERSION,
        BASIC_CORRECTION_EXECUTOR_VERSION,
        "AUDIT_COMPLETE",
        identity,
        canonical_record,
        metrics,
        passes,
        authority,
        final_action,
        None,
    )


def _blocked(blocker: str) -> _D3AuditResult:
    passes = {name: "NOT_AUDITED" for name in _PASS_NAMES}
    return _D3AuditResult(
        D3_SCHEMA_VERSION,
        D3_AUDIT_VERSION,
        "PROTECTION_BLOCKED",
        None,
        None,
        None,
        {},
        passes,
        NetGain.UNCERTAIN,
        AcceptanceAuthority.NONE,
        FinalAction.REVIEW_REQUIRED,
        blocker,
    )


def _as_rgb01(
    image: np.ndarray,
    input_order: str,
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray]:
    array = np.asarray(image)
    if array.ndim != 3 or array.shape[2] not in {3, 4}:
        raise ValueError("D3 expects an RGB/BGR or RGBA/BGRA image array")
    order = input_order.upper()
    if order not in {"RGB", "BGR"}:
        raise ValueError("input_order must be RGB or BGR")
    color = array[..., :3]
    alpha = array[..., 3].copy() if array.shape[2] == 4 else None
    if order == "BGR":
        color = color[..., ::-1]
    if np.issubdtype(color.dtype, np.integer):
        scale = float(np.iinfo(color.dtype).max)
    elif np.issubdtype(color.dtype, np.floating):
        maximum = float(np.nanmax(color)) if color.size else 0.0
        scale = 1.0 if maximum <= 1.5 else 255.0
    else:
        raise TypeError(f"unsupported D3 image dtype: {color.dtype}")
    rgb01 = color.astype(np.float32) / scale
    if not np.isfinite(rgb01).all():
        raise ValueError("D3 image contains non-finite values")
    if alpha is None:
        analysis_mask = np.ones(color.shape[:2], dtype=bool)
    elif np.issubdtype(alpha.dtype, np.integer):
        alpha_scale = float(np.iinfo(alpha.dtype).max)
        analysis_mask = alpha.astype(np.float32) > alpha_scale * 0.01
    else:
        alpha_float = np.nan_to_num(
            alpha.astype(np.float32),
            nan=0.0,
            posinf=255.0,
            neginf=0.0,
        )
        alpha_scale = 1.0 if float(alpha_float.max(initial=0.0)) <= 1.0 else 255.0
        analysis_mask = alpha_float > alpha_scale * 0.01
    return (
        np.clip(rgb01, 0.0, 1.0),
        alpha,
        np.ascontiguousarray(analysis_mask, dtype=bool),
    )


def _candidate_identity(source_fingerprint: str, result: _D2CandidateResult) -> str:
    if result.candidate_image is None:
        raise ValueError("candidate identity requires candidate pixels")
    candidate = np.ascontiguousarray(result.candidate_image)
    region_context = {
        "source_fingerprint": source_fingerprint,
        "attempts": [
            {
                "executor": attempt.executor.value,
                "budget": attempt.budget.value,
                "person_regions": [
                    [int(value) for value in box]
                    for box in attempt.person_regions
                ],
            }
            for attempt in result.attempts
        ],
    }
    region_digest = hashlib.sha256(
        json.dumps(
            region_context,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    contract = {
        "source_fingerprint": source_fingerprint,
        "d2_schema_version": result.schema_version,
        "d2_engine_version": result.engine_version,
        "plan": result.plan.to_dict(),
        "executor": result.executor.value,
        "executor_parameters": result.executor_parameters,
        "person_region_context_digest": region_digest,
        "candidate_shape": list(candidate.shape),
        "candidate_dtype": str(candidate.dtype),
    }
    digest = hashlib.sha256()
    digest.update(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    digest.update(candidate.tobytes(order="C"))
    return f"{D2_CANDIDATE_IDENTITY_VERSION}:{digest.hexdigest()}"


def _generated_result_blocker(
    decision: ColorUsabilityDecision,
    result: object,
) -> str | None:
    if type(result) is not _D2CandidateResult:
        return "D2_INTERNAL_RESULT_TYPE_INVALID"
    if result.schema_version != D2_SCHEMA_VERSION:
        return "UNSUPPORTED_D2_SCHEMA_VERSION" if result.schema_version else "MISSING_D2_SCHEMA_VERSION"
    if result.engine_version != D2_ENGINE_VERSION:
        return "UNSUPPORTED_D2_ENGINE_VERSION" if result.engine_version else "MISSING_D2_ENGINE_VERSION"
    if result.plan.schema_version != D2_SCHEMA_VERSION:
        return "UNSUPPORTED_D2_PLAN_SCHEMA_VERSION" if result.plan.schema_version else "MISSING_D2_PLAN_SCHEMA_VERSION"
    if result.plan.engine_version != D2_ENGINE_VERSION:
        return "UNSUPPORTED_D2_PLAN_ENGINE_VERSION" if result.plan.engine_version else "MISSING_D2_PLAN_ENGINE_VERSION"

    if result.plan.d1_action != getattr(decision, "d1_action", None):
        return "D1_ACTION_MISMATCH"
    if result.status == "PROTECTION_BLOCKED":
        return result.blocker or "D2_PROTECTION_BLOCKED"
    if result.status == "EXECUTOR_LIMIT":
        return result.blocker or "D2_EXECUTOR_LIMIT"
    if result.status not in {"CANDIDATE_READY", "NOT_APPLICABLE"}:
        return "D2_RESULT_STATUS_INVALID"
    return None


def _region_mask(shape: tuple[int, int], regions: tuple[tuple[int, int, int, int], ...]) -> np.ndarray:
    height, width = shape
    mask = np.zeros(shape, dtype=bool)
    for x, y, box_width, box_height in regions:
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + box_width), min(height, y + box_height)
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = True
    return mask


def _mask_stats(values: np.ndarray, mask: np.ndarray) -> dict[str, float | None]:
    selected = values[mask]
    if not selected.size:
        return {"coverage": 0.0, "mean": None, "p95": None}
    return {
        "coverage": round(float(mask.mean()), 6),
        "mean": round(float(np.mean(selected)), 6),
        "p95": round(float(np.percentile(selected, 95)), 6),
    }


def _yes(condition: bool) -> str:
    return "YES" if condition else "NO"


def _contract_number(parameters: dict[str, Any], key: str) -> float:
    value = parameters.get(key)
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value,
        (int, float, np.integer, np.floating),
    ):
        raise ValueError(f"invalid executor parameter: {key}")
    number = float(value)
    if not np.isfinite(number):
        raise ValueError(f"non-finite executor parameter: {key}")
    return number


def _require_contract_number(
    parameters: dict[str, Any],
    key: str,
    expected: float,
    *,
    tolerance: float = 1e-6,
) -> None:
    if abs(_contract_number(parameters, key) - float(expected)) > tolerance:
        raise ValueError(f"executor parameter mismatch: {key}")


def _contract_regions(
    recorded_regions: object,
    original_rgb: np.ndarray,
    requested_regions: tuple[tuple[int, int, int, int], ...],
) -> tuple[tuple[int, int, int, int], ...]:
    if not isinstance(recorded_regions, tuple):
        raise ValueError("missing executor person-region contract")
    regions: list[tuple[int, int, int, int]] = []
    height, width = original_rgb.shape[:2]
    for raw_box in recorded_regions:
        if not isinstance(raw_box, (list, tuple)) or len(raw_box) != 4:
            raise ValueError("malformed executor person-region contract")
        if any(
            isinstance(value, (bool, np.bool_))
            or not isinstance(value, (int, np.integer))
            for value in raw_box
        ):
            raise ValueError("non-integer executor person-region contract")
        x, y, box_width, box_height = (int(value) for value in raw_box)
        if (
            box_width <= 0
            or box_height <= 0
            or x >= width
            or y >= height
            or x + box_width <= 0
            or y + box_height <= 0
        ):
            raise ValueError("out-of-bounds executor person-region contract")
        regions.append((x, y, box_width, box_height))
    resolved = tuple(regions)
    if resolved != requested_regions:
        raise ValueError("executor person regions do not match the D1-bound contract")
    return resolved


def _replay_box_mask(
    shape: tuple[int, int],
    regions: tuple[tuple[int, int, int, int], ...],
    *,
    expansion: float = 0.0,
) -> np.ndarray:
    height, width = shape
    mask = np.zeros(shape, dtype=bool)
    for x, y, box_width, box_height in regions:
        pad_x = int(round(box_width * expansion))
        pad_y = int(round(box_height * expansion))
        x0, y0 = max(0, x - pad_x), max(0, y - pad_y)
        x1 = min(width, x + box_width + pad_x)
        y1 = min(height, y + box_height + pad_y)
        mask[y0:y1, x0:x1] = True
    return mask


def _replay_protection_masks(
    rgb01: np.ndarray,
    regions: tuple[tuple[int, int, int, int], ...],
    analysis_mask: np.ndarray,
) -> dict[str, np.ndarray]:
    visible = np.asarray(analysis_mask, dtype=bool)
    if visible.shape != rgb01.shape[:2] or not visible.any():
        raise ValueError("D3 replay mask must contain visible source pixels")
    lab = cv2.cvtColor(rgb01.astype(np.float32), cv2.COLOR_RGB2LAB)
    hsv = cv2.cvtColor(rgb01.astype(np.float32), cv2.COLOR_RGB2HSV)
    chroma = np.linalg.norm(lab[..., 1:3], axis=2)
    saturation = hsv[..., 1]
    lightness = lab[..., 0]
    face = _replay_box_mask(rgb01.shape[:2], regions).astype(np.float32)
    person = _replay_box_mask(
        rgb01.shape[:2],
        regions,
        expansion=0.55,
    ).astype(np.float32)
    skin = (
        visible & (face >= 0.25)
        & (lab[..., 1] > 3.0)
        & (lab[..., 1] < 30.0)
        & (lab[..., 2] > -2.0)
        & (lab[..., 2] < 35.0)
        & (lightness > 12.0)
        & (lightness < 94.0)
    )
    strong = (
        visible
        & (saturation >= 0.38)
        & (lightness > 7.0)
        & (lightness < 98.0)
        & (person <= 0.08)
    )
    endpoint = np.clip(
        np.minimum(lightness / 12.0, (100.0 - lightness) / 10.0),
        0.0,
        1.0,
    )
    return {
        "lab": lab,
        "skin": skin,
        "strong": strong,
        "endpoint": endpoint.astype(np.float32),
        "analysis": visible,
    }


def _replay_safe_wb_reference(
    original_rgb: np.ndarray,
    decision: ColorUsabilityDecision,
    budget: CorrectionBudget,
    parameters: dict[str, Any],
    recorded_regions: tuple[tuple[int, int, int, int], ...],
    requested_regions: tuple[tuple[int, int, int, int], ...],
    analysis_mask: np.ndarray,
) -> np.ndarray:
    expected_strength = 0.36 if budget == CorrectionBudget.MILD else 0.58
    if (
        parameters.get("implementation") != "existing_safe_wb_wrapped_by_d2_budget"
        or parameters.get("luminance_policy") != "SOURCE_L_PRESERVED"
        or parameters.get("non_color_enhancement") is not False
    ):
        raise ValueError("invalid Safe-WB executor contract")
    _require_contract_number(parameters, "budget_strength", expected_strength)
    _require_contract_number(parameters, "skin_scale", 0.72)
    _require_contract_number(parameters, "strong_color_scale", 0.28)
    regions = _contract_regions(
        recorded_regions,
        original_rgb,
        requested_regions,
    )

    rgb_u8 = np.rint(original_rgb * 255.0).astype(np.uint8)
    array = rgb_u8.astype(np.float32)
    maximum = array.max(axis=2)
    minimum = array.min(axis=2)
    saturation = np.divide(maximum - minimum, np.maximum(maximum, 1.0))
    luminance = (
        0.2126 * array[..., 0]
        + 0.7152 * array[..., 1]
        + 0.0722 * array[..., 2]
    )
    visible = np.asarray(analysis_mask, dtype=bool)
    if visible.shape != original_rgb.shape[:2] or not visible.any():
        raise ValueError("Safe-WB replay requires visible source pixels")
    neutral = visible & (saturation < 0.18) & (luminance > 38) & (luminance < 238)
    visible_count = int(visible.sum())
    neutral_ratio = float(neutral.sum() / visible_count)
    if int(neutral.sum()) < max(64, int(visible_count * 0.003)):
        raise ValueError("selected Safe-WB attempt lacks replayable neutral evidence")

    lab = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2LAB).astype(np.float32)
    neutral_facts = decision.neutral_color_facts
    cast_a = float(neutral_facts.get("median_lab_a", 0.0))
    cast_b = float(neutral_facts.get("median_lab_b", 0.0))
    confidence = float(np.clip(decision.confidence, 0.0, 1.0))
    direction = str(
        decision.color_appearance_evidence.get("direction") or "NEUTRAL"
    ).lower()
    correction_strength = (
        float(np.clip(0.86 + 0.14 * confidence, 0.0, 1.0))
        if direction != "none"
        else 0.0
    )
    delta_a = float((1.2 - cast_a) * correction_strength)
    delta_b = float((1.8 - cast_b) * correction_strength)
    chroma_slope = 0.90 - 0.25 * confidence

    raw_info = parameters.get("raw_white_balance")
    if not isinstance(raw_info, dict):
        raise ValueError("missing Safe-WB execution facts")
    for key, expected in (
        ("white_balance_confidence", round(confidence, 3)),
        ("neutral_pixel_ratio", round(neutral_ratio, 4)),
        ("color_cast_magnitude", round(float(np.hypot(cast_a, cast_b)), 3)),
        ("lab_neutral_cast_a", round(cast_a, 3)),
        ("lab_neutral_cast_b", round(cast_b, 3)),
        ("white_balance_target_lab_a", 1.2),
        ("white_balance_target_lab_b", 1.8),
        ("white_balance_lab_delta_a", round(delta_a, 4)),
        ("white_balance_lab_delta_b", round(delta_b, 4)),
        ("white_balance_execution_strength", round(correction_strength, 4)),
        ("white_balance_chroma_slope", round(chroma_slope, 4)),
    ):
        _require_contract_number(raw_info, key, expected)
    if (
        raw_info.get("white_balance_applied")
        is not bool(direction != "none" and correction_strength >= 0.08)
        or raw_info.get("white_balance_execution")
        != ("spatial_neutral_target" if direction != "none" else "blocked")
    ):
        raise ValueError("Safe-WB execution facts do not match D1")

    endpoint_protection = np.clip(luminance / 24.0, 0.25, 1.0) * np.clip(
        (255.0 - luminance) / 24.0,
        0.25,
        1.0,
    )
    raw_mask = (
        np.clip(1.0 - saturation * chroma_slope, 0.40, 1.0)
        * endpoint_protection
    )
    corrected_lab = lab.copy()
    corrected_lab[..., 1] = np.clip(
        corrected_lab[..., 1] + delta_a * raw_mask,
        0,
        255,
    )
    corrected_lab[..., 2] = np.clip(
        corrected_lab[..., 2] + delta_b * raw_mask,
        0,
        255,
    )
    raw = cv2.cvtColor(
        corrected_lab.astype(np.uint8),
        cv2.COLOR_LAB2RGB,
    ).astype(np.float32)
    source_means = np.maximum(array[visible].mean(axis=0), 1.0)
    gains = np.clip(raw[visible].mean(axis=0) / source_means, 0.85, 1.18)
    recorded_gains = parameters.get("raw_white_balance_gains")
    if (
        not isinstance(recorded_gains, list)
        or len(recorded_gains) != 3
        or any(
            abs(_contract_number({"gain": actual}, "gain") - round(float(expected), 4))
            > 1e-6
            for actual, expected in zip(recorded_gains, gains)
        )
    ):
        raise ValueError("Safe-WB gain facts do not match source replay")

    masks = _replay_protection_masks(original_rgb, regions, visible)
    chroma = np.linalg.norm(masks["lab"][..., 1:3], axis=2)
    chroma_protection = np.clip((48.0 - chroma) / 36.0, 0.18, 1.0)
    weight = expected_strength * chroma_protection * masks["endpoint"]
    weight[masks["skin"]] *= 0.72
    weight[masks["strong"]] *= 0.28
    blended = original_rgb + (
        np.clip(raw / 255.0, 0.0, 1.0) - original_rgb
    ) * weight[..., None]
    blended_lab = cv2.cvtColor(
        np.clip(blended, 0.0, 1.0).astype(np.float32),
        cv2.COLOR_RGB2LAB,
    )
    blended_lab[..., 0] = masks["lab"][..., 0]
    return np.clip(
        cv2.cvtColor(blended_lab, cv2.COLOR_LAB2RGB),
        0.0,
        1.0,
    )


def _independent_cross_affine_fit(
    original_rgb: np.ndarray,
    regions: tuple[tuple[int, int, int, int], ...],
    analysis_mask: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any], dict[str, Any]]:
    """Rebuild Cross-Affine source evidence without D2 helpers or parameters."""

    visible = np.asarray(analysis_mask, dtype=bool)
    if visible.shape != original_rgb.shape[:2] or not visible.any():
        raise ValueError("Cross-Affine replay requires visible source pixels")
    rgb_u8 = np.rint(original_rgb * 255.0).astype(np.uint8)

    protection_lab = cv2.cvtColor(original_rgb.astype(np.float32), cv2.COLOR_RGB2LAB)
    protection_hsv = cv2.cvtColor(original_rgb.astype(np.float32), cv2.COLOR_RGB2HSV)
    face = _replay_box_mask(original_rgb.shape[:2], regions).astype(np.float32) * visible
    person = (
        _replay_box_mask(original_rgb.shape[:2], regions, expansion=0.55).astype(np.float32)
        * visible
    )
    strong = (
        visible
        & (protection_hsv[..., 1] >= 0.38)
        & (protection_lab[..., 0] > 7.0)
        & (protection_lab[..., 0] < 98.0)
        & (person <= 0.08)
    )

    lab = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2LAB).astype(np.float32)
    hsv = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2HSV).astype(np.float32)
    ycc = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2YCrCb)
    a_axis = lab[..., 1] - 128.0
    b_axis = lab[..., 2] - 128.0
    saturation = hsv[..., 1] / 255.0
    neutral = (
        visible
        & (saturation < 0.22)
        & (lab[..., 0] > 35.0)
        & (lab[..., 0] < 235.0)
        & ~strong
    )
    skin = (
        visible
        & (face >= 0.25)
        & (ycc[..., 0] > 40)
        & (ycc[..., 1] >= 128)
        & (ycc[..., 1] <= 180)
        & (ycc[..., 2] >= 75)
        & (ycc[..., 2] <= 138)
        & (a_axis > 3.0)
        & (a_axis < 30.0)
        & (b_axis > -2.0)
        & (b_axis < 35.0)
    )
    protected = visible & strong & (person <= 0.08)
    if int(neutral.sum()) < max(96, int(visible.sum() * 0.005)):
        raise ValueError("insufficient neutral evidence for Cross-Affine replay")

    neutral_before = np.median(lab[..., 1:3][neutral] - 128.0, axis=0)
    neutral_target_lab = lab.copy()
    neutral_target_lab[..., 1] = np.clip(
        neutral_target_lab[..., 1] + (1.5 - neutral_before[0]),
        0.0,
        255.0,
    )
    neutral_target_lab[..., 2] = np.clip(
        neutral_target_lab[..., 2] + (2.4 - neutral_before[1]),
        0.0,
        255.0,
    )
    neutral_target = cv2.cvtColor(
        neutral_target_lab.astype(np.uint8),
        cv2.COLOR_LAB2RGB,
    )

    skin_target = rgb_u8.copy()
    skin_before: list[float] | None = None
    skin_target_ab: list[float] | None = None
    face_visible_count = int((face >= 0.25).sum())
    if int(skin.sum()) >= max(64, int(face_visible_count * 0.04)):
        skin_before_array = np.median(lab[..., 1:3][skin] - 128.0, axis=0)
        skin_target_lab = lab.copy()
        skin_target_lab[..., 1] = np.clip(
            skin_target_lab[..., 1] + 14.0 - skin_before_array[0],
            0.0,
            255.0,
        )
        skin_target_lab[..., 2] = np.clip(
            skin_target_lab[..., 2] + 20.2 - skin_before_array[1],
            0.0,
            255.0,
        )
        skin_target = cv2.cvtColor(skin_target_lab.astype(np.uint8), cv2.COLOR_LAB2RGB)
        skin_before = [round(float(value), 4) for value in skin_before_array]
        skin_target_ab = [14.0, 20.2]

    visible_count = int(visible.sum())
    neutral_ratio = float(neutral.sum() / visible_count)
    confidence = float(
        np.clip(
            0.52 * float(neutral_ratio / 0.20)
            + 0.28 * float(min(1.0, skin.sum() / max(face_visible_count * 0.20, 1.0)))
            + 0.20,
            0.0,
            1.0,
        )
    )
    prediction = {
        "neutral_pixels": int(neutral.sum()),
        "neutral_ratio": round(neutral_ratio, 4),
        "neutral_before_ab": [round(float(value), 4) for value in neutral_before],
        "neutral_target_ab": [
            float(value)
            for value in np.array([1.5, 2.4], dtype=np.float32)
        ],
        "skin_pixels": int(skin.sum()),
        "skin_before_ab": skin_before,
        "skin_target_ab": skin_target_ab,
        "target_confidence": round(confidence, 4),
        "target_uncertainty": round(1.0 - confidence, 4),
        "runtime_ground_truth_used": False,
    }

    source_flat = rgb_u8.reshape(-1, 3).astype(np.float32) / 255.0
    inputs: list[np.ndarray] = []
    outputs: list[np.ndarray] = []
    weights: list[np.ndarray] = []
    support_counts: dict[str, int] = {}
    rng = np.random.default_rng(20260813)
    for name, mask, target, weight, limit in (
        ("neutral", neutral, neutral_target, 1.0, 9000),
        ("skin", skin, skin_target, 1.50, 6000),
        ("protected", protected, rgb_u8, 0.20, 5000),
    ):
        indexes = np.flatnonzero(mask)
        if len(indexes) == 0:
            support_counts[name] = 0
            continue
        indexes = rng.choice(indexes, min(limit, len(indexes)), replace=False)
        inputs.append(
            np.column_stack(
                (source_flat[indexes], np.ones(len(indexes), dtype=np.float32))
            )
        )
        outputs.append(target.reshape(-1, 3)[indexes].astype(np.float32) / 255.0)
        weights.append(np.full(len(indexes), weight, dtype=np.float32))
        support_counts[name] = int(len(indexes))

    design = np.vstack(inputs)
    target_values = np.vstack(outputs)
    sample_weights = np.concatenate(weights)
    weighted = design * np.sqrt(sample_weights)[:, None]
    weighted_target = target_values * np.sqrt(sample_weights)[:, None]
    identity = np.zeros((4, 3), dtype=np.float32)
    identity[:3] = np.eye(3, dtype=np.float32)
    regularizer = np.diag(np.array([1.0, 1.0, 1.0, 0.25], dtype=np.float32))
    ridge = 0.030 * len(design)
    system = weighted.T @ weighted + ridge * regularizer
    matrix = np.linalg.solve(
        system,
        weighted.T @ weighted_target + ridge * regularizer @ identity,
    )
    matrix[:3] = np.clip(matrix[:3], -0.25, 1.35)
    for channel in range(3):
        matrix[channel, channel] = np.clip(matrix[channel, channel], 0.65, 1.35)
    matrix[-1] = np.clip(matrix[-1], -0.10, 0.10)
    fit = {
        "basis": "full_cross_channel_affine",
        "coefficients": [
            [round(float(value), 6) for value in row]
            for row in matrix
        ],
        "support_counts": support_counts,
        "ridge": 0.030,
        "condition_number": round(float(np.linalg.cond(system)), 4),
    }
    return matrix.astype(np.float32), prediction, fit


def _apply_independent_cross_affine(
    rgb_u8: np.ndarray,
    matrix: np.ndarray,
    strength: float,
) -> np.ndarray:
    source = rgb_u8.reshape(-1, 3).astype(np.float32) / 255.0
    basis = np.column_stack((source, np.ones(len(source), dtype=np.float32)))
    mapped = basis @ matrix
    blended = source * (1.0 - strength) + mapped * strength
    output = np.clip(
        np.rint(blended.reshape(rgb_u8.shape) * 255.0),
        0.0,
        255.0,
    ).astype(np.uint8)
    source_lab = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2LAB)
    output_lab = cv2.cvtColor(output, cv2.COLOR_RGB2LAB)
    output_lab[..., 0] = source_lab[..., 0]
    output = cv2.cvtColor(output_lab, cv2.COLOR_LAB2RGB)
    for channel in range(3):
        low = (rgb_u8[..., channel] > 1) & (output[..., channel] <= 1)
        high = (rgb_u8[..., channel] < 254) & (output[..., channel] >= 254)
        output[..., channel][low] = 2
        output[..., channel][high] = 253
    return output


def _replay_cross_affine_reference(
    original_rgb: np.ndarray,
    budget: CorrectionBudget,
    parameters: dict[str, Any],
    recorded_regions: tuple[tuple[int, int, int, int], ...],
    requested_regions: tuple[tuple[int, int, int, int], ...],
    analysis_mask: np.ndarray,
) -> np.ndarray:
    expected_strength = 0.34 if budget == CorrectionBudget.MILD else 0.56
    if (
        parameters.get("implementation") != "cross_affine_balanced"
        or parameters.get("luminance_policy") != "SOURCE_L_PRESERVED"
        or parameters.get("non_color_enhancement") is not False
    ):
        raise ValueError("invalid cross-affine executor contract")
    _require_contract_number(parameters, "budget_strength", expected_strength)
    regions = _contract_regions(
        recorded_regions,
        original_rgb,
        requested_regions,
    )
    matrix, prediction, fit = _independent_cross_affine_fit(
        original_rgb,
        regions,
        analysis_mask,
    )
    if parameters.get("prediction") != prediction or parameters.get("fit") != fit:
        raise ValueError("Cross-Affine parameters do not match independent source fit")
    rgb_u8 = np.rint(original_rgb * 255.0).astype(np.uint8)
    output = _apply_independent_cross_affine(rgb_u8, matrix, expected_strength)
    return output.astype(np.float64) / 255.0


def _replay_exposure_reference(
    original_rgb: np.ndarray,
    decision: ColorUsabilityDecision,
    budget: CorrectionBudget,
    parameters: dict[str, Any],
    analysis_mask: np.ndarray,
) -> np.ndarray:
    if (
        parameters.get("curve") != "MONOTONIC_LAB_L_GAMMA"
        or parameters.get("color_channels") != "LAB_AB_UNCHANGED"
        or parameters.get("clahe") is not False
        or parameters.get("hdr") is not False
        or parameters.get("sharpen") is not False
        or parameters.get("contrast_enhancement") is not False
    ):
        raise ValueError("invalid exposure executor contract")
    source_lab = cv2.cvtColor(
        original_rgb.astype(np.float32),
        cv2.COLOR_RGB2LAB,
    )
    lightness = source_lab[..., 0] / 100.0
    visible = np.asarray(analysis_mask, dtype=bool)
    if visible.shape != lightness.shape or not visible.any():
        raise ValueError("exposure replay requires visible source pixels")
    median = float(np.median(lightness[visible]))
    if decision.exposure_status == ExposureStatus.TOO_DARK:
        target = 0.35 if budget == CorrectionBudget.MILD else 0.42
        raw_gamma = float(
            np.log(max(target, 1e-4)) / np.log(max(median, 1e-4))
        )
        gamma = float(
            np.clip(
                raw_gamma,
                0.82 if budget == CorrectionBudget.MILD else 0.68,
                1.0,
            )
        )
    elif decision.exposure_status == ExposureStatus.TOO_BRIGHT:
        target = 0.72 if budget == CorrectionBudget.MILD else 0.66
        raw_gamma = float(
            np.log(max(target, 1e-4)) / np.log(max(median, 1e-4))
        )
        gamma = float(
            np.clip(
                raw_gamma,
                1.0,
                1.22 if budget == CorrectionBudget.MILD else 1.50,
            )
        )
    else:
        raise ValueError("exposure replay requires a D1 exposure finding")
    maximum_delta = 0.08 if budget == CorrectionBudget.MILD else 0.16
    _require_contract_number(parameters, "gamma", round(gamma, 6))
    _require_contract_number(parameters, "target_median", target)
    _require_contract_number(
        parameters,
        "maximum_luminance_delta",
        maximum_delta,
    )
    curved = np.power(np.clip(lightness, 0.0, 1.0), gamma)
    delta = np.clip(curved - lightness, -maximum_delta, maximum_delta)
    endpoint = np.clip(
        np.sin(np.pi * np.clip(lightness, 0.0, 1.0)),
        0.0,
        1.0,
    ) ** 0.35
    corrected_lab = source_lab.copy()
    corrected_lab[..., 0] = np.clip(
        (lightness + delta * endpoint) * 100.0,
        0.0,
        100.0,
    )
    return np.clip(
        cv2.cvtColor(corrected_lab, cv2.COLOR_LAB2RGB),
        0.0,
        1.0,
    )


def _trusted_executor_reference(
    original: np.ndarray,
    decision: ColorUsabilityDecision,
    result: _D2CandidateResult,
    input_order: str,
    requested_regions: tuple[tuple[int, int, int, int], ...],
) -> tuple[np.ndarray | None, str | None, dict[str, Any] | None]:
    """Replay the selected transform from source facts, never D2 output pixels."""

    matching_attempts = [
        attempt
        for attempt in result.attempts
        if attempt.executor == result.executor
        and attempt.budget == result.plan.correction_budget
        and attempt.safety_status == "PASS"
        and not attempt.violations
    ]
    if len(matching_attempts) != 1:
        return None, "D2_TRUSTED_EXECUTOR_REFERENCE_INVALID", None
    selected_attempt = matching_attempts[0]
    if selected_attempt.parameters != result.executor_parameters:
        return None, "D2_TRUSTED_EXECUTOR_PARAMETERS_MISMATCH", None

    basic_replay_record: dict[str, Any] | None = None
    try:
        original_rgb, _, analysis_mask = _as_rgb01(original, input_order)
        parameters = result.executor_parameters
        if not isinstance(parameters, dict):
            raise ValueError("executor parameters must be a dictionary")
        _contract_regions(
            selected_attempt.person_regions,
            original_rgb,
            requested_regions,
        )
        if result.executor == CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION:
            correction_parameters = CorrectionParameters.from_record(parameters)
            replayed_candidate = execute_basic_correction(
                original,
                correction_parameters,
                input_order=input_order,
            ).candidate_image
            replay_audit = audit_basic_correction(
                original,
                replayed_candidate,
                parameters,
                input_order=input_order,
            )
            basic_replay_record = replay_audit.to_record()
            if replay_audit.status != "AUDIT_COMPLETE":
                return (
                    None,
                    replay_audit.blocker or "BASIC_CORRECTION_EXECUTION_SAFETY_FAILED",
                    basic_replay_record,
                )
            reference, _, _ = _as_rgb01(replayed_candidate, input_order)
        else:
            raise ValueError("unsupported executor replay contract")
    except (cv2.error, KeyError, TypeError, ValueError):
        return None, "D2_TRUSTED_EXECUTOR_REFERENCE_INVALID", basic_replay_record
    if (
        reference.shape != original_rgb.shape
        or not np.issubdtype(reference.dtype, np.number)
        or not np.isfinite(reference).all()
        or float(reference.min(initial=0.0)) < -1e-6
        or float(reference.max(initial=0.0)) > 1.0 + 1e-6
    ):
        return None, "D2_TRUSTED_EXECUTOR_REFERENCE_INVALID", basic_replay_record
    return np.clip(reference.astype(np.float64), 0.0, 1.0), None, basic_replay_record


def _local_component_opaque_support(
    alpha_positive: np.ndarray,
    semi_transparent: np.ndarray,
    opaque: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, int, int, int]:
    """Measure bounded Alpha-connected opaque reachability for diagnostics."""

    supported = np.zeros(semi_transparent.shape, dtype=bool)
    reference_distance = np.zeros(semi_transparent.shape, dtype=np.float32)
    semi_transparent_component_count = 0
    unsupported_component_count = 0
    short_edge = max(1, min(semi_transparent.shape))
    distance_limit = int(np.clip(
        np.ceil(short_edge * _TRANSPARENT_EDGE_REFERENCE_DISTANCE_FRACTION),
        _TRANSPARENT_EDGE_MIN_REFERENCE_DISTANCE_PIXELS,
        _TRANSPARENT_EDGE_MAX_REFERENCE_DISTANCE_PIXELS,
    ))
    connectivity_kernel = np.ones((3, 3), dtype=np.uint8)

    component_count, component_labels = cv2.connectedComponents(
        alpha_positive.astype(np.uint8),
        connectivity=8,
    )
    for component_id in range(1, component_count):
        component = component_labels == component_id
        component_semi = semi_transparent & component
        if not component_semi.any():
            continue
        semi_transparent_component_count += 1
        component_opaque = opaque & component
        if int(np.count_nonzero(component_opaque)) < _TRANSPARENT_EDGE_MIN_OPAQUE_REFERENCE_PIXELS:
            unsupported_component_count += 1
            continue

        component_y, component_x = np.nonzero(component)
        y0, y1 = int(component_y.min()), int(component_y.max()) + 1
        x0, x1 = int(component_x.min()), int(component_x.max()) + 1
        component_crop = component[y0:y1, x0:x1]
        component_semi_crop = component_semi[y0:y1, x0:x1]
        reached = component_opaque[y0:y1, x0:x1].copy()
        frontier = reached.copy()
        component_distance = np.zeros(component_crop.shape, dtype=np.float32)
        for distance in range(1, distance_limit + 1):
            expanded = cv2.dilate(
                frontier.astype(np.uint8),
                connectivity_kernel,
                iterations=1,
            ).astype(bool)
            frontier = expanded & component_crop & ~reached
            if not frontier.any():
                break
            component_distance[frontier] = float(distance)
            reached |= frontier

        component_supported = component_semi_crop & reached
        supported_crop = supported[y0:y1, x0:x1]
        reference_distance_crop = reference_distance[y0:y1, x0:x1]
        supported_crop |= component_supported
        reference_distance_crop[component_supported] = component_distance[
            component_supported
        ]
        if int(np.count_nonzero(component_supported)) != int(
            np.count_nonzero(component_semi_crop)
        ):
            unsupported_component_count += 1

    return (
        supported,
        reference_distance,
        distance_limit,
        semi_transparent_component_count,
        unsupported_component_count,
    )


_PASS_NAMES = (
    "COLOR_PASS",
    "EXPOSURE_PASS",
    "HIGHLIGHT_PASS",
    "SHADOW_PASS",
    "SKIN_PASS",
    "NEUTRAL_PASS",
    "BRAND_COLOR_PASS",
    "COLOR_CONSISTENCY_PASS",
    "REVERSE_CAST_PASS",
    "SCENE_INTENT_PASS",
    "SIDE_EFFECT_PASS",
    "NET_GAIN_PASS",
    "OVERALL_USABILITY_PASS",
)


def _pixel_audit(
    original: np.ndarray,
    candidate: np.ndarray,
    trusted_executor_rgb: np.ndarray,
    decision: ColorUsabilityDecision,
    candidate_type: CandidateType,
    input_order: str,
    person_regions: tuple[tuple[int, int, int, int], ...],
) -> tuple[dict[str, Any], dict[str, str], NetGain]:
    original_array = np.asarray(original)
    candidate_array = np.asarray(candidate)
    if original_array.shape != candidate_array.shape or original_array.dtype != candidate_array.dtype:
        metrics = {"shape_dtype_match": False}
        passes = {name: "NO" for name in _PASS_NAMES}
        return metrics, passes, NetGain.NEGATIVE

    original_rgb, original_alpha, analysis_mask = _as_rgb01(original_array, input_order)
    candidate_rgb, candidate_alpha, candidate_analysis_mask = _as_rgb01(
        candidate_array,
        input_order,
    )
    trusted_executor_rgb = np.asarray(trusted_executor_rgb, dtype=np.float64)
    alpha_pass = (
        (original_alpha is None and candidate_alpha is None)
        or (
            original_alpha is not None
            and candidate_alpha is not None
            and np.array_equal(original_alpha, candidate_alpha)
        )
    )
    analysis_mask_pass = bool(np.array_equal(analysis_mask, candidate_analysis_mask))
    trusted_executor_reference_mask = (
        np.ones(original_rgb.shape[:2], dtype=bool)
        if original_alpha is None
        else original_alpha > 0
    )
    trusted_executor_reference_pixel_count = int(
        np.count_nonzero(trusted_executor_reference_mask)
    )
    trusted_executor_reference_abs_error = np.max(
        np.abs(candidate_rgb.astype(np.float64) - trusted_executor_rgb),
        axis=2,
    )
    trusted_executor_reference_max_abs_error = (
        float(
            trusted_executor_reference_abs_error[
                trusted_executor_reference_mask
            ].max(initial=0.0)
        )
        if trusted_executor_reference_pixel_count
        else 0.0
    )
    trusted_executor_reference_match = bool(
        trusted_executor_reference_pixel_count > 0
        and trusted_executor_reference_max_abs_error
        <= _TRANSPARENT_EDGE_CHANNEL_TOLERANCE + 1e-6
    )
    transparent_pixel_count = 0
    transparent_rgb_changed_pixel_count = 0
    transparent_rgb_max_abs_delta = 0.0
    transparent_rgb_pass = True
    semi_transparent_pixel_count = 0
    semi_transparent_rgb_max_abs_delta = 0.0
    opaque_reference_pixel_count = 0
    opaque_rgb_max_abs_delta = 0.0
    opaque_rgb_reference_p99 = 0.0
    opaque_rgb_reference_limit = 0.0
    trusted_semi_reference_max_abs_delta = 0.0
    trusted_semi_reference_limit = 0.0
    opaque_rgb_delta_lower_p01 = np.zeros(3, dtype=np.float64)
    opaque_rgb_delta_upper_p99 = np.zeros(3, dtype=np.float64)
    black_composite_max_abs_delta = 0.0
    white_composite_max_abs_delta = 0.0
    local_opaque_reference_supported_pixel_count = 0
    local_opaque_reference_unsupported_pixel_count = 0
    local_opaque_reference_max_distance = 0.0
    local_opaque_reference_distance_limit = 0
    semi_transparent_component_count = 0
    unsupported_semi_transparent_component_count = 0
    semi_transparent_rgb_local_vector_max_abs_error = 0.0
    semi_transparent_rgb_local_vector_max_l2_error = 0.0
    composite_local_continuity_max_abs_error = 0.0
    composite_local_edge_jump_max = 0.0
    composite_background_delta_equivalent = True
    composite_local_continuity_pass = True
    opaque_reference_sufficient = True
    semi_transparent_rgb_magnitude_within_reference = True
    semi_transparent_rgb_vector_within_reference = True
    semi_transparent_rgb_within_reference = True
    black_composite_edge_pass = True
    white_composite_edge_pass = True
    semi_transparent_edge_pass = True
    if original_alpha is not None and candidate_alpha is not None:
        transparent = original_alpha == 0
        transparent_pixel_count = int(np.count_nonzero(transparent))
        if transparent_pixel_count:
            transparent_delta = np.abs(
                candidate_array[..., :3][transparent].astype(np.float64)
                - original_array[..., :3][transparent].astype(np.float64)
            )
            transparent_rgb_changed_pixel_count = int(
                np.count_nonzero(np.any(transparent_delta != 0, axis=1))
            )
            transparent_rgb_max_abs_delta = float(transparent_delta.max(initial=0.0))
            transparent_rgb_pass = transparent_rgb_changed_pixel_count == 0

        if np.issubdtype(original_alpha.dtype, np.integer):
            alpha_scale = float(np.iinfo(original_alpha.dtype).max)
        else:
            observed_alpha_max = float(np.nanmax(original_alpha)) if original_alpha.size else 0.0
            alpha_scale = 1.0 if observed_alpha_max <= 1.0 else 255.0
        semi_transparent = (original_alpha > 0) & (original_alpha < alpha_scale)
        opaque = original_alpha >= alpha_scale
        semi_transparent_pixel_count = int(np.count_nonzero(semi_transparent))
        opaque_reference_pixel_count = int(np.count_nonzero(opaque))
        rgb_delta = candidate_rgb - original_rgb
        rgb_abs_delta = np.max(np.abs(rgb_delta), axis=2)
        trusted_rgb_delta = trusted_executor_rgb - original_rgb.astype(np.float64)
        trusted_rgb_abs_delta = np.max(np.abs(trusted_rgb_delta), axis=2)
        if opaque.any():
            opaque_rgb_max_abs_delta = float(rgb_abs_delta[opaque].max(initial=0.0))
        if semi_transparent_pixel_count:
            semi_transparent_rgb_max_abs_delta = float(
                rgb_abs_delta[semi_transparent].max(initial=0.0)
            )
            trusted_semi_reference_max_abs_delta = float(
                trusted_rgb_abs_delta[semi_transparent].max(initial=0.0)
            )
            trusted_semi_reference_limit = min(
                1.0,
                trusted_semi_reference_max_abs_delta
                + _TRANSPARENT_EDGE_CHANNEL_TOLERANCE,
            )
            opaque_reference_sufficient = bool(
                opaque_reference_pixel_count >= _TRANSPARENT_EDGE_MIN_OPAQUE_REFERENCE_PIXELS
            )
            if opaque_reference_sufficient:
                opaque_deltas = np.sort(
                    trusted_rgb_abs_delta[opaque].astype(np.float64),
                    axis=None,
                )
                reference_index = int(np.floor(
                    (opaque_deltas.size - 1) * _TRANSPARENT_EDGE_OPAQUE_REFERENCE_QUANTILE
                ))
                opaque_rgb_reference_p99 = float(opaque_deltas[reference_index])
                opaque_rgb_reference_limit = min(
                    1.0,
                    opaque_rgb_reference_p99 + _TRANSPARENT_EDGE_CHANNEL_TOLERANCE,
                )
                opaque_channel_deltas = np.sort(
                    trusted_rgb_delta[opaque].astype(np.float64),
                    axis=0,
                )
                lower_index = int(np.ceil(
                    (opaque_channel_deltas.shape[0] - 1)
                    * (1.0 - _TRANSPARENT_EDGE_OPAQUE_REFERENCE_QUANTILE)
                ))
                upper_index = int(np.floor(
                    (opaque_channel_deltas.shape[0] - 1)
                    * _TRANSPARENT_EDGE_OPAQUE_REFERENCE_QUANTILE
                ))
                opaque_rgb_delta_lower_p01 = opaque_channel_deltas[lower_index]
                opaque_rgb_delta_upper_p99 = opaque_channel_deltas[upper_index]
            semi_transparent_rgb_magnitude_within_reference = bool(
                semi_transparent_rgb_max_abs_delta
                <= trusted_semi_reference_limit + 1e-6
            )
            semi_delta = rgb_delta[semi_transparent].astype(np.float64)
            (
                local_opaque_reference_supported,
                local_opaque_reference_distance,
                local_opaque_reference_distance_limit,
                semi_transparent_component_count,
                unsupported_semi_transparent_component_count,
            ) = _local_component_opaque_support(
                original_alpha > 0,
                semi_transparent,
                opaque,
            )
            local_opaque_reference_supported_pixel_count = int(
                np.count_nonzero(local_opaque_reference_supported & semi_transparent)
            )
            local_opaque_reference_unsupported_pixel_count = (
                semi_transparent_pixel_count - local_opaque_reference_supported_pixel_count
            )
            if local_opaque_reference_supported_pixel_count:
                local_opaque_reference_max_distance = float(
                    local_opaque_reference_distance[
                        local_opaque_reference_supported & semi_transparent
                    ].max(initial=0.0)
                )
            local_vector_error = (
                semi_delta - trusted_rgb_delta[semi_transparent]
            )
            local_vector_abs_error = np.abs(local_vector_error)
            semi_transparent_rgb_local_vector_max_abs_error = float(
                local_vector_abs_error.max(initial=0.0)
            )
            semi_transparent_rgb_local_vector_max_l2_error = float(
                np.linalg.norm(local_vector_error, axis=1).max(initial=0.0)
            )
            semi_transparent_rgb_vector_within_reference = bool(
                semi_transparent_rgb_local_vector_max_abs_error
                <= _TRANSPARENT_EDGE_CHANNEL_TOLERANCE + 1e-6
                and semi_transparent_rgb_local_vector_max_l2_error
                <= np.sqrt(3.0) * _TRANSPARENT_EDGE_CHANNEL_TOLERANCE + 1e-6
            )
            semi_transparent_rgb_within_reference = bool(
                semi_transparent_rgb_magnitude_within_reference
                and semi_transparent_rgb_vector_within_reference
            )
            alpha01 = np.clip(original_alpha.astype(np.float32) / alpha_scale, 0.0, 1.0)[..., None]
            black_before = original_rgb * alpha01
            black_after = candidate_rgb * alpha01
            white_before = black_before + (1.0 - alpha01)
            white_after = black_after + (1.0 - alpha01)
            black_composite_delta = np.max(np.abs(black_after - black_before), axis=2)
            white_composite_delta = np.max(np.abs(white_after - white_before), axis=2)
            black_composite_max_abs_delta = float(
                black_composite_delta[semi_transparent].max(initial=0.0)
            )
            white_composite_max_abs_delta = float(
                white_composite_delta[semi_transparent].max(initial=0.0)
            )
            semi_alpha = alpha01[semi_transparent].astype(np.float64)
            black_composite_delta_signed = (black_after - black_before)[semi_transparent]
            white_composite_delta_signed = (white_after - white_before)[semi_transparent]
            composite_background_delta_equivalent = bool(
                np.allclose(
                    black_composite_delta_signed,
                    white_composite_delta_signed,
                    atol=1e-7,
                    rtol=0.0,
                )
            )
            composite_local_error = np.zeros_like(rgb_delta, dtype=np.float64)
            composite_local_error[semi_transparent] = semi_alpha * local_vector_error
            composite_local_continuity_max_abs_error = float(
                np.abs(composite_local_error[semi_transparent]).max(initial=0.0)
            )
            horizontal_jump = float(
                np.abs(composite_local_error[:, 1:] - composite_local_error[:, :-1]).max(
                    initial=0.0
                )
            )
            vertical_jump = float(
                np.abs(composite_local_error[1:] - composite_local_error[:-1]).max(
                    initial=0.0
                )
            )
            composite_local_edge_jump_max = max(horizontal_jump, vertical_jump)
            composite_local_continuity_pass = bool(
                composite_background_delta_equivalent
                and composite_local_continuity_max_abs_error
                <= _TRANSPARENT_EDGE_CHANNEL_TOLERANCE + 1e-6
                and composite_local_edge_jump_max
                <= 2.0 * _TRANSPARENT_EDGE_CHANNEL_TOLERANCE + 1e-6
            )
            # With unchanged Alpha, black- and white-background correction deltas
            # are mathematically identical. Keep both legacy diagnostics aligned
            # with the single physical composite-continuity authority.
            black_composite_edge_pass = composite_local_continuity_pass
            white_composite_edge_pass = composite_local_continuity_pass
            semi_transparent_edge_pass = bool(
                semi_transparent_rgb_within_reference
                and composite_local_continuity_pass
            )
    original_lab = cv2.cvtColor(original_rgb, cv2.COLOR_RGB2LAB)
    candidate_lab = cv2.cvtColor(candidate_rgb, cv2.COLOR_RGB2LAB)
    delta_lab = candidate_lab - original_lab
    delta_e = np.linalg.norm(delta_lab, axis=2)
    delta_ab = np.linalg.norm(delta_lab[..., 1:3], axis=2)
    original_l = original_lab[..., 0] / 100.0
    candidate_l = candidate_lab[..., 0] / 100.0
    original_chroma = np.linalg.norm(original_lab[..., 1:3], axis=2)

    rgb8 = np.rint(original_rgb * 255.0).astype(np.uint8)
    ycrcb = cv2.cvtColor(rgb8, cv2.COLOR_RGB2YCrCb)
    cr, cb = ycrcb[..., 1], ycrcb[..., 2]
    skin = analysis_mask & (cr >= 133) & (cr <= 180) & (cb >= 77) & (cb <= 135)
    if person_regions:
        skin &= _region_mask(skin.shape, person_regions)
    neutral = (
        analysis_mask
        & (original_chroma <= 18.0)
        & (original_l >= 0.08)
        & (original_l <= 0.96)
        & ~skin
    )
    brand = analysis_mask & (original_chroma >= 35.0) & ~skin

    neutral_original_ab = (
        np.median(original_lab[..., 1:3][neutral], axis=0) if neutral.any() else np.array([0.0, 0.0])
    )
    neutral_candidate_ab = (
        np.median(candidate_lab[..., 1:3][neutral], axis=0) if neutral.any() else np.array([0.0, 0.0])
    )
    neutral_original_distance = float(np.linalg.norm(neutral_original_ab))
    neutral_candidate_distance = float(np.linalg.norm(neutral_candidate_ab))
    neutral_improvement = neutral_original_distance - neutral_candidate_distance
    reverse_cast = not (
        float(np.dot(neutral_original_ab, neutral_candidate_ab)) < 0.0
        and neutral_candidate_distance > 3.0
    )

    cell_vectors: list[np.ndarray] = []
    height, width = original_l.shape
    for row in range(3):
        for column in range(3):
            y0, y1 = row * height // 3, (row + 1) * height // 3
            x0, x1 = column * width // 3, (column + 1) * width // 3
            cell_mask = analysis_mask[y0:y1, x0:x1]
            cell = delta_lab[y0:y1, x0:x1, 1:3][cell_mask]
            if cell.size:
                cell_vectors.append(np.median(cell, axis=0))
    cell_array = np.asarray(cell_vectors, dtype=np.float32)
    if cell_array.size:
        cell_center = np.median(cell_array, axis=0)
        cell_deviation = np.linalg.norm(cell_array - cell_center, axis=1)
        color_consistency_p95 = float(np.percentile(cell_deviation, 95))
    else:
        color_consistency_p95 = float("inf")

    highlight_before = float((np.max(original_rgb, axis=2) >= 0.995)[analysis_mask].mean())
    highlight_after = float((np.max(candidate_rgb, axis=2) >= 0.995)[analysis_mask].mean())
    shadow_before = float((np.max(original_rgb, axis=2) <= 0.005)[analysis_mask].mean())
    shadow_after = float((np.max(candidate_rgb, axis=2) <= 0.005)[analysis_mask].mean())
    highlight_growth = highlight_after - highlight_before
    shadow_growth = shadow_after - shadow_before

    after_decision = analyze_color_usability(
        candidate_array,
        input_order=input_order,
        person_regions=person_regions,
    )
    skin_stats = _mask_stats(delta_e, skin)
    skin_ab_stats = _mask_stats(delta_ab, skin)
    neutral_stats = _mask_stats(delta_e, neutral)
    neutral_ab_stats = _mask_stats(delta_ab, neutral)
    brand_stats = _mask_stats(delta_e, brand)

    reverse_pass = reverse_cast
    highlight_pass = highlight_growth <= 0.003
    shadow_pass = shadow_growth <= 0.003
    if candidate_type == CandidateType.AUTO_EXPOSURE_CANDIDATE:
        # Exposure is expected to move skin luminance; audit its chroma instead
        # of treating the intended L* change as skin-color damage.
        skin_pass = (
            skin_ab_stats["mean"] is None
            or (float(skin_ab_stats["mean"]) <= 1.5 and float(skin_ab_stats["p95"]) <= 3.0)
        )
    else:
        skin_pass = (
            skin_stats["mean"] is None
            or (float(skin_stats["mean"]) <= 4.0 and float(skin_stats["p95"]) <= 10.0)
        )
    # Keep the pre-existing full Delta-E brand protection gate for every route.
    # A route-specific a/b threshold cannot be frozen before D57-COLOR-02 has
    # supplied authoritative brand references and validation evidence.
    brand_pass = (
        brand_stats["mean"] is None
        or (
            float(brand_stats["mean"]) <= 6.0
            and float(brand_stats["p95"]) <= 12.0
        )
    )
    consistency_pass = color_consistency_p95 <= 4.0

    if candidate_type == CandidateType.COLOR_REVIEW_CANDIDATE:
        color_pass = neutral.any() and neutral_improvement >= 0.35 and reverse_pass
        exposure_pass = (
            abs(
                float(np.median(candidate_l[analysis_mask]))
                - float(np.median(original_l[analysis_mask]))
            )
            <= 0.015
            and after_decision.exposure_status == decision.exposure_status
        )
        neutral_pass = neutral.any() and neutral_improvement >= -0.10 and reverse_pass
        scene_intent_pass = (
            decision.scene_intent
            not in {"LEGITIMATE_WARM", "LEGITIMATE_COOL", "LEGITIMATE_DARK", "DOMINANT_COLOR_DESIGN", "MIXED_LIGHT"}
            and not decision.skin_color_facts.get("local_person_color_risk")
        )
    else:
        color_pass = (
            float(np.mean(delta_ab[analysis_mask])) <= 0.75
            and float(np.percentile(delta_ab[analysis_mask], 95)) <= 2.0
        )
        exposure_pass = after_decision.exposure_status == ExposureStatus.PASS
        neutral_pass = neutral_ab_stats["mean"] is None or float(neutral_ab_stats["mean"]) <= 1.5
        scene_intent_pass = (
            after_decision.color_status.value in {"NORMAL", decision.color_status.value}
            and not (
                decision.spatial_color_facts.get("field_status") != "MIXED"
                and after_decision.spatial_color_facts.get("field_status") == "MIXED"
            )
        )

    side_effect_pass = all(
        (
            alpha_pass,
            analysis_mask_pass,
            transparent_rgb_pass,
            trusted_executor_reference_match,
            semi_transparent_edge_pass,
            highlight_pass,
            shadow_pass,
            skin_pass,
            neutral_pass,
            brand_pass,
            consistency_pass,
            reverse_pass,
            exposure_pass if candidate_type == CandidateType.COLOR_REVIEW_CANDIDATE else color_pass,
            scene_intent_pass,
        )
    )
    target_pass = color_pass if candidate_type == CandidateType.COLOR_REVIEW_CANDIDATE else exposure_pass
    if not side_effect_pass:
        net_gain = NetGain.NEGATIVE
    elif not target_pass:
        net_gain = NetGain.INSUFFICIENT
    else:
        net_gain = NetGain.POSITIVE
    overall = side_effect_pass and target_pass and net_gain == NetGain.POSITIVE

    metrics = {
        "candidate_type": candidate_type.value,
        "independent_metric_source": "D3_LAB_REGION_AND_RESIDUAL_AUDIT",
        "analysis_pixel_count": int(analysis_mask.sum()),
        "analysis_pixel_ratio": round(float(analysis_mask.mean()), 6),
        "analysis_mask_unchanged": analysis_mask_pass,
        "delta_e_mean": round(float(np.mean(delta_e[analysis_mask])), 6),
        "delta_e_p95": round(float(np.percentile(delta_e[analysis_mask], 95)), 6),
        "lab_ab_delta_mean": round(float(np.mean(delta_ab[analysis_mask])), 6),
        "lab_ab_delta_p95": round(float(np.percentile(delta_ab[analysis_mask], 95)), 6),
        "luminance_p50_before": round(float(np.median(original_l[analysis_mask])), 6),
        "luminance_p50_after": round(float(np.median(candidate_l[analysis_mask])), 6),
        "residual_color_status": after_decision.color_status.value,
        "residual_exposure_status": after_decision.exposure_status.value,
        "neutral_original_distance": round(neutral_original_distance, 6),
        "neutral_candidate_distance": round(neutral_candidate_distance, 6),
        "neutral_improvement": round(neutral_improvement, 6),
        "skin_delta_e": skin_stats,
        "skin_delta_ab": skin_ab_stats,
        "neutral_delta_e": neutral_stats,
        "brand_delta_e": brand_stats,
        "highlight_clip_growth": round(highlight_growth, 6),
        "shadow_clip_growth": round(shadow_growth, 6),
        "spatial_ab_consistency_p95": round(color_consistency_p95, 6),
        "alpha_unchanged": alpha_pass,
        "trusted_executor_reference_source": "D3_SOURCE_PARAMETER_REPLAY",
        "trusted_executor_reference_pixel_count": (
            trusted_executor_reference_pixel_count
        ),
        "trusted_executor_reference_max_abs_error": round(
            trusted_executor_reference_max_abs_error,
            6,
        ),
        "trusted_executor_reference_match": trusted_executor_reference_match,
        "transparent_pixel_count": transparent_pixel_count,
        "transparent_rgb_changed_pixel_count": transparent_rgb_changed_pixel_count,
        "transparent_rgb_max_abs_delta": round(transparent_rgb_max_abs_delta, 6),
        "transparent_rgb_unchanged": transparent_rgb_pass,
        "semi_transparent_pixel_count": semi_transparent_pixel_count,
        "semi_transparent_rgb_max_abs_delta": round(semi_transparent_rgb_max_abs_delta, 6),
        "opaque_reference_pixel_count": opaque_reference_pixel_count,
        "opaque_rgb_max_abs_delta": round(opaque_rgb_max_abs_delta, 6),
        "opaque_rgb_reference_p99": round(opaque_rgb_reference_p99, 6),
        "opaque_rgb_reference_limit": round(opaque_rgb_reference_limit, 6),
        "trusted_semi_reference_max_abs_delta": round(
            trusted_semi_reference_max_abs_delta,
            6,
        ),
        "trusted_semi_reference_limit": round(
            trusted_semi_reference_limit,
            6,
        ),
        "opaque_rgb_delta_lower_p01": [
            round(float(value), 6) for value in opaque_rgb_delta_lower_p01
        ],
        "opaque_rgb_delta_upper_p99": [
            round(float(value), 6) for value in opaque_rgb_delta_upper_p99
        ],
        "opaque_reference_sufficient": opaque_reference_sufficient,
        "local_opaque_reference_supported_pixel_count": (
            local_opaque_reference_supported_pixel_count
        ),
        "local_opaque_reference_unsupported_pixel_count": (
            local_opaque_reference_unsupported_pixel_count
        ),
        "local_opaque_reference_max_distance": round(
            local_opaque_reference_max_distance,
            6,
        ),
        "local_opaque_reference_distance_limit": (
            local_opaque_reference_distance_limit
        ),
        "local_opaque_reference_authority_used": False,
        "semi_transparent_component_count": semi_transparent_component_count,
        "unsupported_semi_transparent_component_count": (
            unsupported_semi_transparent_component_count
        ),
        "semi_transparent_rgb_local_vector_max_abs_error": round(
            semi_transparent_rgb_local_vector_max_abs_error,
            6,
        ),
        "semi_transparent_rgb_local_vector_max_l2_error": round(
            semi_transparent_rgb_local_vector_max_l2_error,
            6,
        ),
        "semi_transparent_rgb_magnitude_within_reference": (
            semi_transparent_rgb_magnitude_within_reference
        ),
        "semi_transparent_rgb_vector_within_reference": (
            semi_transparent_rgb_vector_within_reference
        ),
        "semi_transparent_rgb_within_reference": semi_transparent_rgb_within_reference,
        "black_composite_max_abs_delta": round(black_composite_max_abs_delta, 6),
        "white_composite_max_abs_delta": round(white_composite_max_abs_delta, 6),
        "composite_background_delta_equivalent": composite_background_delta_equivalent,
        "composite_local_continuity_max_abs_error": round(
            composite_local_continuity_max_abs_error,
            6,
        ),
        "composite_local_edge_jump_max": round(composite_local_edge_jump_max, 6),
        "composite_local_continuity_safe": composite_local_continuity_pass,
        "black_composite_edge_safe": black_composite_edge_pass,
        "white_composite_edge_safe": white_composite_edge_pass,
        "semi_transparent_edge_safe": semi_transparent_edge_pass,
    }
    passes = {
        "COLOR_PASS": _yes(color_pass),
        "EXPOSURE_PASS": _yes(exposure_pass),
        "HIGHLIGHT_PASS": _yes(highlight_pass),
        "SHADOW_PASS": _yes(shadow_pass),
        "SKIN_PASS": _yes(skin_pass),
        "NEUTRAL_PASS": _yes(neutral_pass),
        "BRAND_COLOR_PASS": _yes(brand_pass),
        "COLOR_CONSISTENCY_PASS": _yes(consistency_pass),
        "REVERSE_CAST_PASS": _yes(reverse_pass),
        "SCENE_INTENT_PASS": _yes(scene_intent_pass),
        "SIDE_EFFECT_PASS": _yes(side_effect_pass),
        "NET_GAIN_PASS": _yes(net_gain == NetGain.POSITIVE),
        "OVERALL_USABILITY_PASS": _yes(overall),
    }
    return metrics, passes, net_gain


def _resolve_action(
    candidate_type: CandidateType,
    passes: dict[str, str],
    net_gain: NetGain,
) -> tuple[AcceptanceAuthority, FinalAction]:
    if candidate_type == CandidateType.COLOR_REVIEW_CANDIDATE:
        if net_gain in {NetGain.NEGATIVE, NetGain.INSUFFICIENT}:
            return AcceptanceAuthority.NONE, FinalAction.ACCEPT_ORIGINAL
        return AcceptanceAuthority.REVIEW_ONLY, FinalAction.REVIEW_REQUIRED
    if candidate_type == CandidateType.AUTO_EXPOSURE_CANDIDATE:
        if passes["OVERALL_USABILITY_PASS"] == "YES" and net_gain == NetGain.POSITIVE:
            return AcceptanceAuthority.AUTO_PROVEN, FinalAction.ACCEPT_CORRECTED
        return AcceptanceAuthority.NONE, FinalAction.ACCEPT_ORIGINAL
    return AcceptanceAuthority.NONE, FinalAction.ACCEPT_ORIGINAL


def _resolve_quality_evidence_action(
    evidence: QualityEvidence,
    *,
    d3_safety_pass: bool,
) -> tuple[NetGain, AcceptanceAuthority, FinalAction]:
    """Let D3 translate D60-04 evidence into the existing final actions."""

    if not d3_safety_pass or evidence.net_benefit == QualityNetBenefit.NEGATIVE:
        return NetGain.NEGATIVE, AcceptanceAuthority.NONE, FinalAction.ACCEPT_ORIGINAL
    if evidence.net_benefit == QualityNetBenefit.NEUTRAL:
        return NetGain.INSUFFICIENT, AcceptanceAuthority.NONE, FinalAction.ACCEPT_ORIGINAL
    if evidence.net_benefit == QualityNetBenefit.INCONCLUSIVE:
        return NetGain.UNCERTAIN, AcceptanceAuthority.REVIEW_ONLY, FinalAction.REVIEW_REQUIRED
    return NetGain.POSITIVE, AcceptanceAuthority.AUTO_PROVEN, FinalAction.ACCEPT_CORRECTED


def audit_candidate(
    original: np.ndarray,
    decision: ColorUsabilityDecision,
    *,
    input_order: str = "RGB",
    person_regions: Iterable[Sequence[int]] | None = None,
    budget_cap: CorrectionBudget = CorrectionBudget.MODERATE,
    managed_source: ManagedColorSource | None = None,
    expected_output_format: str | None = None,
) -> _D3AuditResult:
    """Generate and audit one Candidate inside the authoritative D2->D3 call chain."""

    try:
        d2_person_regions = None if person_regions is None else tuple(person_regions)
    except TypeError:
        return _blocked("INVALID_PERSON_REGION_REQUEST")
    try:
        d2_result = generate_candidate(
            original,
            decision,
            input_order=input_order,
            person_regions=d2_person_regions,
            budget_cap=budget_cap,
        )
        blocker = _generated_result_blocker(decision, d2_result)
    except (AttributeError, KeyError, TypeError, ValueError):
        return _blocked("MALFORMED_D1_OR_D2_CONTRACT")
    if blocker is not None:
        return _blocked(blocker)
    assert type(d2_result) is _D2CandidateResult
    try:
        regions = _resolve_bound_person_regions(decision, d2_person_regions)
    except ValueError as exc:
        return _blocked(str(exc))

    if d2_result.status != "CANDIDATE_READY" or d2_result.candidate_image is None:
        final_action = (
            FinalAction.ACCEPT_ORIGINAL
            if decision.d1_action == D1Action.KEEP_ORIGINAL or d2_result.plan.candidate_type == CandidateType.NONE
            else FinalAction.REVIEW_REQUIRED
        )
        passes = {name: "NOT_APPLICABLE" for name in _PASS_NAMES}
        return _D3AuditResult(
            D3_SCHEMA_VERSION,
            D3_AUDIT_VERSION,
            "AUDIT_NOT_APPLICABLE",
            None,
            d2_result.schema_version,
            d2_result.engine_version,
            {},
            passes,
            NetGain.INSUFFICIENT,
            AcceptanceAuthority.NONE,
            final_action,
            d2_result.blocker,
        )

    if d2_result.executor == CandidateExecutor.NONE or d2_result.blocker is not None:
        return _blocked("D2_EXECUTOR_CONTRACT_INVALID")
    (
        trusted_executor_rgb,
        trusted_reference_blocker,
        basic_replay_record,
    ) = _trusted_executor_reference(
        original,
        decision,
        d2_result,
        input_order,
        regions,
    )
    if trusted_reference_blocker is not None or trusted_executor_rgb is None:
        return _blocked(
            trusted_reference_blocker or "D2_TRUSTED_EXECUTOR_REFERENCE_INVALID"
        )
    metrics, passes, net_gain = _pixel_audit(
        original,
        d2_result.candidate_image,
        trusted_executor_rgb,
        decision,
        d2_result.plan.candidate_type,
        input_order,
        regions,
    )
    if basic_replay_record is not None:
        metrics["basic_correction_replay"] = basic_replay_record
    source_fingerprint = getattr(decision, "source_fingerprint", None)
    if not isinstance(source_fingerprint, str) or not source_fingerprint:
        return _blocked("MISSING_SOURCE_FINGERPRINT")
    candidate_identity = _candidate_identity(source_fingerprint, d2_result)

    parameter_decision = bound_parameter_decision(decision)
    if parameter_decision is not None:
        try:
            source_format = actual_format = None
            if managed_source is not None:
                provenance = validate_managed_color_source_provenance(managed_source)
                if not provenance.valid or managed_source.input_order != input_order or not np.array_equal(
                    managed_source.pixels, original
                ):
                    return _blocked("D60_04_ENCODING_SOURCE_IDENTITY_MISMATCH")
                # Encode privately only after the independent source replay.
                # No output is published before D3 makes its final decision.
                payload = encode_color_managed_candidate(d2_result.candidate_image, managed_source)
                verify_color_managed_output(payload, d2_result.candidate_image, managed_source)
                with Image.open(BytesIO(payload)) as encoded:
                    encoded.load()
                    actual_format = encoded.format
                source_format = managed_source.source_format
                metrics["candidate_encoding"] = {
                    "SOURCE_FORMAT": source_format,
                    "EXPECTED_OUTPUT_FORMAT": expected_output_format,
                    "ACTUAL_CANDIDATE_FORMAT": actual_format,
                    "ENCODED_SHA256": hashlib.sha256(payload).hexdigest(),
                    "COLOR_MANAGED_OUTPUT_VERIFIED": True,
                }
            quality_evidence = evaluate_quality_evidence(
                original,
                d2_result.candidate_image,
                parameter_decision.correction_parameters,
                input_order=input_order,
                active_parameters=parameter_decision.active_parameters,
                source_fingerprint=source_fingerprint,
                parameter_decision_digest=parameter_decision.decision_digest,
                objective_diagnosis=build_objective_diagnosis(decision),
                person_regions=regions,
                source_format=source_format,
                expected_output_format=expected_output_format,
                candidate_format=actual_format,
            )
        except (cv2.error, TypeError, ValueError):
            return _blocked("D60_04_QUALITY_EVIDENCE_FAILED")
        metrics["QUALITY_EVIDENCE"] = quality_evidence.to_record()
        d3_safety_pass = all(
            passes.get(name) == "YES"
            for name in (
                "HIGHLIGHT_PASS",
                "SHADOW_PASS",
                "SKIN_PASS",
                "NEUTRAL_PASS",
                "BRAND_COLOR_PASS",
                "COLOR_CONSISTENCY_PASS",
                "REVERSE_CAST_PASS",
                "SIDE_EFFECT_PASS",
            )
        )
        passes["QUALITY_EVIDENCE_PASS"] = _yes(
            quality_evidence.net_benefit == QualityNetBenefit.POSITIVE
        )
        net_gain, authority, final_action = _resolve_quality_evidence_action(
            quality_evidence,
            d3_safety_pass=d3_safety_pass,
        )
        passes["NET_GAIN_PASS"] = _yes(net_gain == NetGain.POSITIVE)
        passes["OVERALL_USABILITY_PASS"] = _yes(final_action == FinalAction.ACCEPT_CORRECTED)
    else:
        authority, final_action = _resolve_action(d2_result.plan.candidate_type, passes, net_gain)

    return _D3AuditResult(
        D3_SCHEMA_VERSION,
        D3_AUDIT_VERSION,
        "AUDIT_COMPLETE",
        candidate_identity,
        d2_result.schema_version,
        d2_result.engine_version,
        metrics,
        passes,
        net_gain,
        authority,
        final_action,
        None,
    )


def audit_reference_candidate(original, decision, reference_decision, *, managed_source, input_order="RGB"):
    """D3-owned reference candidate generation, independent replay and quality action.

    The reference contributes scalar intent only. All candidate pixels and the
    trusted replay come from TARGET plus the frozen CorrectionParameters.
    """
    from .reference_integration import reference_decision_digest, validate_reference_binding

    try:
        parameters = reference_decision.parameters
        validate_reference_binding(reference_decision, original, parameters, input_order=input_order)
        provenance = validate_managed_color_source_provenance(managed_source)
        if not provenance.valid or managed_source.input_order != input_order or not np.array_equal(managed_source.pixels, original):
            return _blocked("D60_04_ENCODING_SOURCE_IDENTITY_MISMATCH")
        regions = _resolve_bound_person_regions(decision, None)
        candidate = execute_basic_correction(original, parameters, input_order=input_order).candidate_image
        replay_audit = audit_basic_correction(original, candidate, parameters.to_record(), input_order=input_order)
        if replay_audit.status != "AUDIT_COMPLETE":
            return _blocked(replay_audit.blocker or "BASIC_CORRECTION_EXECUTION_SAFETY_FAILED")
        trusted = replay_basic_correction(original, parameters.to_record(), input_order=input_order)
        trusted_rgb, _, _ = _as_rgb01(trusted, input_order)
        metrics, passes, _ = _pixel_audit(
            original, candidate, trusted_rgb, decision, CandidateType.COLOR_REVIEW_CANDIDATE,
            input_order, regions,
        )
        metrics["basic_correction_replay"] = replay_audit.to_record()
        payload = encode_color_managed_candidate(candidate, managed_source)
        verify_color_managed_output(payload, candidate, managed_source)
        with Image.open(BytesIO(payload)) as encoded:
            encoded.load()
            actual_format = encoded.format
        metrics["candidate_encoding"] = {
            "SOURCE_FORMAT": managed_source.source_format,
            "EXPECTED_OUTPUT_FORMAT": managed_source.source_format,
            "ACTUAL_CANDIDATE_FORMAT": actual_format,
            "ENCODED_SHA256": hashlib.sha256(payload).hexdigest(),
            "COLOR_MANAGED_OUTPUT_VERIFIED": True,
        }
        quality = evaluate_quality_evidence(
            original, candidate, parameters, input_order=input_order,
            source_fingerprint=decision.source_fingerprint,
            parameter_decision_digest=reference_decision_digest(reference_decision),
            objective_diagnosis=build_objective_diagnosis(decision), person_regions=regions,
            source_format=managed_source.source_format,
            expected_output_format=managed_source.source_format, candidate_format=actual_format,
            reference_decision=reference_decision,
        )
        metrics["QUALITY_EVIDENCE"] = quality.to_record()
        safety = all(passes.get(name) == "YES" for name in (
            "HIGHLIGHT_PASS", "SHADOW_PASS", "SKIN_PASS", "NEUTRAL_PASS", "BRAND_COLOR_PASS",
            "COLOR_CONSISTENCY_PASS", "REVERSE_CAST_PASS", "SIDE_EFFECT_PASS",
        ))
        net_gain, authority, final_action = _resolve_quality_evidence_action(quality, d3_safety_pass=safety)
        passes["QUALITY_EVIDENCE_PASS"] = _yes(quality.net_benefit == QualityNetBenefit.POSITIVE)
        passes["NET_GAIN_PASS"] = _yes(net_gain == NetGain.POSITIVE)
        passes["OVERALL_USABILITY_PASS"] = _yes(final_action == FinalAction.ACCEPT_CORRECTED)
        return _D3AuditResult(
            D3_SCHEMA_VERSION, D3_AUDIT_VERSION, "AUDIT_COMPLETE", replay_audit.candidate_identity,
            D2_SCHEMA_VERSION, D2_ENGINE_VERSION, metrics, passes, net_gain, authority, final_action, None,
        )
    except (BasicCorrectionSafetyError, cv2.error, AttributeError, KeyError, TypeError, ValueError):
        return _blocked("REFERENCE_CANDIDATE_CONTRACT_OR_SAFETY_FAILED")


__all__ = [
    "D3_SCHEMA_VERSION",
    "D3_AUDIT_VERSION",
    "D2_CANDIDATE_IDENTITY_VERSION",
    "D3_BASIC_REPLAY_SCHEMA_VERSION",
    "D3_BASIC_REPLAY_AUDIT_VERSION",
    "D3_BASIC_CANDIDATE_IDENTITY_VERSION",
    "AcceptanceAuthority",
    "FinalAction",
    "NetGain",
    "replay_basic_correction",
    "audit_basic_correction",
    "audit_candidate",
    "audit_reference_candidate",
]
