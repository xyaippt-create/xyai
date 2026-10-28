"""D2 decision-to-parameter adapter for the deterministic HDDE color executor.

D2 consumes the frozen D1 decision contract.  It may produce a candidate for
later D3 comparison, but it never promotes a candidate to a formal result.
Color and exposure keep separate D1 policy, but share one pixel executor.
"""

from __future__ import annotations

import hmac
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Iterable, Sequence

import cv2
import numpy as np

from .executors.basic_correction import (
    BasicCorrectionSafetyError,
    execute_basic_correction,
    white_balance_controls_for_lab_shift,
)
from .parameters import CorrectionParameters
from .parameter_decision import (
    ParameterDecision,
    ParameterDecisionOutcome,
    bound_parameter_decision,
)
from .usability_decision import (
    ColorObservability,
    ColorUsabilityDecision,
    D1Action,
    ExposureStatus,
    _resolve_bound_person_regions,
    compute_source_fingerprint,
)


D2_SCHEMA_VERSION = "hdde.color-candidate.schema.v1"
D2_ENGINE_VERSION = "hdde.d2-safe-candidate.v1.3"
D2_SUPPORTED_D1_SCHEMA_VERSION = "hdde.color-usability.schema.v2"
D2_SUPPORTED_D1_ENGINE_VERSION = "hdde.d1-color-usability.v1.7"
D2_SUPPORTED_D1_RULE_VERSION = "hdde.color-usability.rules.v1.7"
D2_SUPPORTED_SOURCE_FINGERPRINT_VERSION = "hdde.source-fingerprint.v1"
SAFE_NEUTRAL_TARGET_AB = np.array([1.5, 2.4], dtype=np.float32)
_COLOR_BUDGET_STRENGTH = {
    "MILD": 0.24,
    "MODERATE": 0.42,
}
_EXPOSURE_BUDGET_EV = {
    ExposureStatus.TOO_DARK: {
        "MILD": 0.35,
        "MODERATE": 0.65,
    },
    ExposureStatus.TOO_BRIGHT: {
        "MILD": -0.06,
        "MODERATE": -0.10,
    },
}


class CandidateType(str, Enum):
    NONE = "NONE"
    COLOR_REVIEW_CANDIDATE = "COLOR_REVIEW_CANDIDATE"
    AUTO_EXPOSURE_CANDIDATE = "AUTO_EXPOSURE_CANDIDATE"


class CorrectionBudget(str, Enum):
    NONE = "NONE"
    MILD = "MILD"
    MODERATE = "MODERATE"


class CorrectionTarget(str, Enum):
    NONE = "NONE"
    SAFE_COLOR_ZONE = "SAFE_COLOR_ZONE"
    SAFE_EXPOSURE_ZONE = "SAFE_EXPOSURE_ZONE"


class CandidateExecutor(str, Enum):
    NONE = "NONE"
    DETERMINISTIC_BASIC_CORRECTION = "DETERMINISTIC_BASIC_CORRECTION"


@dataclass(frozen=True)
class _CorrectionPlan:
    schema_version: str
    engine_version: str
    d1_action: D1Action
    candidate_type: CandidateType
    correction_target: CorrectionTarget
    correction_budget: CorrectionBudget
    executor_candidates: tuple[CandidateExecutor, ...]
    protection_profile: dict[str, Any]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
            "d1_action": self.d1_action.value,
            "candidate_type": self.candidate_type.value,
            "correction_target": self.correction_target.value,
            "correction_budget": self.correction_budget.value,
            "executor_candidates": [item.value for item in self.executor_candidates],
            "protection_profile": dict(self.protection_profile),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class _ExecutorAttempt:
    executor: CandidateExecutor
    budget: CorrectionBudget
    candidate_rgb01: np.ndarray
    parameters: dict[str, Any]
    before_metrics: dict[str, Any]
    after_metrics: dict[str, Any]
    safety_status: str
    violations: tuple[str, ...]
    score: float
    person_regions: tuple[tuple[int, int, int, int], ...] = ()

    def to_record(self) -> dict[str, Any]:
        return {
            "executor": self.executor.value,
            "correction_budget": self.budget.value,
            "executor_parameters": dict(self.parameters),
            "before_metrics": dict(self.before_metrics),
            "after_metrics": dict(self.after_metrics),
            "safety_status": self.safety_status,
            "violations": list(self.violations),
            "score": round(float(self.score), 6),
        }


@dataclass(frozen=True)
class _D2CandidateResult:
    schema_version: str
    engine_version: str
    status: str
    plan: _CorrectionPlan
    candidate_image: np.ndarray | None
    executor: CandidateExecutor
    executor_parameters: dict[str, Any]
    before_metrics: dict[str, Any]
    after_metrics: dict[str, Any]
    attempts: tuple[_ExecutorAttempt, ...]
    disposition: str
    blocker: str | None

    @property
    def modified(self) -> bool:
        return self.candidate_image is not None

    def to_record(self) -> dict[str, Any]:
        """Return the privacy-minimal D2 -> D3 record without image bytes."""

        return {
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
            "status": self.status,
            "D1_ACTION": self.plan.d1_action.value,
            "CANDIDATE_TYPE": self.plan.candidate_type.value,
            "CORRECTION_TARGET": self.plan.correction_target.value,
            "CORRECTION_BUDGET": self.plan.correction_budget.value,
            "EXECUTOR": self.executor.value,
            "EXECUTOR_PARAMETERS": dict(self.executor_parameters),
            "PROTECTION_PROFILE": dict(self.plan.protection_profile),
            "BEFORE_METRICS": dict(self.before_metrics),
            "AFTER_METRICS": dict(self.after_metrics),
            "CANDIDATE_AVAILABLE": self.modified,
            "DISPOSITION": self.disposition,
            "BLOCKER": self.blocker,
            "ATTEMPTS": [attempt.to_record() for attempt in self.attempts],
        }


@dataclass(frozen=True)
class _ImageDomain:
    dtype: np.dtype[Any]
    scale: float
    input_order: str
    alpha: np.ndarray | None
    source_color: np.ndarray | None
    source_channels: int
    bit_depth: int
    analysis_mask: np.ndarray


def _normalise_image(image: np.ndarray, input_order: str) -> tuple[np.ndarray, _ImageDomain]:
    array = np.asarray(image)
    if array.ndim != 3 or array.shape[2] not in {3, 4}:
        raise ValueError("D2 expects an RGB/BGR or RGBA/BGRA image array")
    order = input_order.upper()
    if order not in {"RGB", "BGR"}:
        raise ValueError("input_order must be RGB or BGR")
    color = array[..., :3]
    alpha = array[..., 3].copy() if array.shape[2] == 4 else None
    source_color = color.copy() if alpha is not None else None
    if order == "BGR":
        color = color[..., ::-1]
    if np.issubdtype(color.dtype, np.integer):
        scale = float(np.iinfo(color.dtype).max)
    elif np.issubdtype(color.dtype, np.floating):
        finite = color[np.isfinite(color)]
        if finite.size == 0:
            raise ValueError("D2 input contains no finite pixels")
        minimum, maximum = float(finite.min()), float(finite.max())
        if minimum < 0.0 or maximum > 255.0:
            raise ValueError("floating D2 input range must be 0..1 or 0..255")
        scale = 1.0 if maximum <= 1.0 else 255.0
    else:
        raise ValueError(f"unsupported D2 input dtype: {color.dtype}")
    rgb01 = np.nan_to_num(color.astype(np.float32), nan=0.0, posinf=scale, neginf=0.0) / scale
    if alpha is None:
        analysis_mask = np.ones(color.shape[:2], dtype=bool)
    elif np.issubdtype(alpha.dtype, np.integer):
        alpha_scale = float(np.iinfo(alpha.dtype).max)
        analysis_mask = alpha.astype(np.float32) > alpha_scale * 0.01
    else:
        alpha_float = np.nan_to_num(alpha.astype(np.float32), nan=0.0, posinf=255.0, neginf=0.0)
        alpha_scale = 1.0 if float(alpha_float.max(initial=0.0)) <= 1.0 else 255.0
        analysis_mask = alpha_float > alpha_scale * 0.01
    domain = _ImageDomain(
        dtype=array.dtype,
        scale=scale,
        input_order=order,
        alpha=alpha,
        source_color=source_color,
        source_channels=array.shape[2],
        bit_depth=int(array.dtype.itemsize * 8),
        analysis_mask=np.ascontiguousarray(analysis_mask, dtype=bool),
    )
    return np.ascontiguousarray(np.clip(rgb01, 0.0, 1.0)), domain


def _restore_image(rgb01: np.ndarray, domain: _ImageDomain) -> np.ndarray:
    color = np.clip(rgb01, 0.0, 1.0)
    if np.issubdtype(domain.dtype, np.integer):
        color = np.rint(color * domain.scale).astype(domain.dtype)
    else:
        color = (color * domain.scale).astype(domain.dtype)
    if domain.input_order == "BGR":
        color = color[..., ::-1]
    if domain.source_channels == 4:
        if domain.alpha is None or domain.source_color is None:
            raise ValueError("RGBA restoration requires the frozen source Alpha and color facts")
        transparent = domain.alpha == 0
        if transparent.any():
            color = color.copy()
            color[transparent] = domain.source_color[transparent]
        color = np.dstack((color, domain.alpha))
    return np.ascontiguousarray(color)


def _budget_min(left: CorrectionBudget, right: CorrectionBudget) -> CorrectionBudget:
    order = {CorrectionBudget.NONE: 0, CorrectionBudget.MILD: 1, CorrectionBudget.MODERATE: 2}
    return left if order[left] <= order[right] else right


def _preplan_blocked_result(
    decision: ColorUsabilityDecision,
    blocker: str,
) -> _D2CandidateResult:
    """Return a compatibility-safe no-op record without forming an executable plan."""

    action = getattr(decision, "d1_action", D1Action.REVIEW_REQUIRED)
    if not isinstance(action, D1Action):
        try:
            action = D1Action(str(action))
        except ValueError:
            action = D1Action.REVIEW_REQUIRED
    plan = _CorrectionPlan(
        D2_SCHEMA_VERSION,
        D2_ENGINE_VERSION,
        action,
        CandidateType.NONE,
        CorrectionTarget.NONE,
        CorrectionBudget.NONE,
        (),
        {
            "SKIN": "PROTECT",
            "NEUTRAL": "PROTECT",
            "BRAND_COLOR": "PROTECT",
            "HIGHLIGHT": "PROTECT",
            "SHADOW": "PROTECT",
            "SCENE_INTENT": "D1_AUTHORITY",
            "NON_COLOR_ENHANCEMENT": "DISABLED",
            "blockers": [blocker],
        },
        "pre-plan D1 contract gate blocked candidate generation",
    )
    return _D2CandidateResult(
        D2_SCHEMA_VERSION,
        D2_ENGINE_VERSION,
        "PROTECTION_BLOCKED",
        plan,
        None,
        CandidateExecutor.NONE,
        {},
        {},
        {},
        (),
        "KEEP_ORIGINAL_OR_REVIEW",
        blocker,
    )


def _source_binding_blocker(
    decision: ColorUsabilityDecision,
    image: np.ndarray,
    input_order: str,
) -> str | None:
    claimed = getattr(decision, "source_fingerprint", None)
    if not isinstance(claimed, str) or not claimed:
        return "MISSING_SOURCE_FINGERPRINT"
    prefix = f"{D2_SUPPORTED_SOURCE_FINGERPRINT_VERSION}:"
    encoded_digest = claimed[len(prefix):] if claimed.startswith(prefix) else ""
    if len(encoded_digest) != 64 or any(character not in "0123456789abcdef" for character in encoded_digest):
        return "INVALID_SOURCE_FINGERPRINT"
    current = compute_source_fingerprint(image, input_order=input_order)
    if not hmac.compare_digest(claimed, current):
        return "SOURCE_FINGERPRINT_MISMATCH"
    return None


def _version_gate_blocker(decision: ColorUsabilityDecision) -> str | None:
    supported = (
        ("schema_version", D2_SUPPORTED_D1_SCHEMA_VERSION, "D1_SCHEMA_VERSION"),
        ("engine_version", D2_SUPPORTED_D1_ENGINE_VERSION, "D1_ENGINE_VERSION"),
        ("rule_version", D2_SUPPORTED_D1_RULE_VERSION, "D1_RULE_VERSION"),
    )
    for field, expected, label in supported:
        actual = getattr(decision, field, None)
        if not isinstance(actual, str) or not actual:
            return f"MISSING_{label}"
        if actual != expected:
            return f"UNSUPPORTED_{label}"
    return None


def _color_blockers(decision: ColorUsabilityDecision) -> list[str]:
    blockers: list[str] = []
    if decision.color_observability == ColorObservability.LOW:
        blockers.append("LOW_COLOR_OBSERVABILITY")
    if decision.spatial_color_facts.get("field_status") == "MIXED":
        blockers.append("MIXED_COLOR_FIELD")
    if decision.skin_color_facts.get("local_person_color_risk"):
        blockers.append("LOCAL_PERSON_COLOR_RISK")
    if decision.dominant_color_risk == "HIGH":
        blockers.append("DOMINANT_COLOR_HIGH_RISK")
    if decision.color_appearance_evidence.get("boundary_unstable"):
        blockers.append("QUANTIZATION_BOUNDARY_UNSTABLE")
    if decision.scene_intent in {
        "LEGITIMATE_WARM", "LEGITIMATE_COOL", "LEGITIMATE_DARK", "DOMINANT_COLOR_DESIGN",
    }:
        blockers.append("SCENE_INTENT_PROTECTED")
    return blockers


def _build_correction_plan(
    decision: ColorUsabilityDecision,
    parameter_decision: ParameterDecision | None = None,
) -> _CorrectionPlan:
    """Build a plan only after generate_candidate has passed both contract gates."""

    base_profile = {
        "SKIN": "PROTECT",
        "NEUTRAL": "MOVE_TOWARD_SAFE_ZONE_WITHOUT_CROSSING",
        "BRAND_COLOR": "STRONG_CHROMA_PROTECT",
        "HIGHLIGHT": "NO_NEW_CLIPPING",
        "SHADOW": "NO_NEW_CRUSH",
        "SCENE_INTENT": "D1_AUTHORITY",
        "NON_COLOR_ENHANCEMENT": "DISABLED",
    }
    if parameter_decision is not None:
        d60_profile = {
            **base_profile,
            "SCENE_INTENT": "D60_03_PARAMETER_DECISION_AUTHORITY",
            "PARAMETER_DECISION_SCHEMA": parameter_decision.schema_version,
            "PARAMETER_DECISION_DIGEST": parameter_decision.decision_digest,
        }
        if parameter_decision.outcome != ParameterDecisionOutcome.CORRECTION_NEEDED:
            return _CorrectionPlan(
                D2_SCHEMA_VERSION,
                D2_ENGINE_VERSION,
                decision.d1_action,
                CandidateType.NONE,
                CorrectionTarget.NONE,
                CorrectionBudget.NONE,
                (),
                {
                    **d60_profile,
                    "blockers": [parameter_decision.outcome.value],
                },
                "D60-03 decision produced no executable correction parameters",
            )
        values = parameter_decision.correction_parameters
        active_parameters = parameter_decision.active_parameters
        active = set(active_parameters)
        pure_exposure = active == {"exposure"}
        candidate_type = (
            CandidateType.AUTO_EXPOSURE_CANDIDATE
            if pure_exposure
            else CandidateType.COLOR_REVIEW_CANDIDATE
        )
        target = (
            CorrectionTarget.SAFE_EXPOSURE_ZONE
            if pure_exposure
            else CorrectionTarget.SAFE_COLOR_ZONE
        )
        budget = (
            CorrectionBudget.MILD
            if parameter_decision.maximum_active_severity.value == "MILD"
            else CorrectionBudget.MODERATE
        )
        return _CorrectionPlan(
            D2_SCHEMA_VERSION,
            D2_ENGINE_VERSION,
            decision.d1_action,
            candidate_type,
            target,
            budget,
            (CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION,),
            {
                **d60_profile,
                "blockers": [],
                "active_parameters": list(active_parameters),
                "explicit_parameter_record": values.to_record(),
            },
            "D60-03 source-bound parameter decision authorizes deterministic replay",
        )
    if decision.d1_action == D1Action.KEEP_ORIGINAL:
        return _CorrectionPlan(
            D2_SCHEMA_VERSION, D2_ENGINE_VERSION, decision.d1_action,
            CandidateType.NONE, CorrectionTarget.NONE, CorrectionBudget.NONE, (),
            {**base_profile, "blockers": ["D1_KEEP_ORIGINAL"]},
            "D1 requires immutable original",
        )

    if (
        decision.d1_action == D1Action.AUTO_CORRECT
        and decision.exposure_status in {ExposureStatus.TOO_DARK, ExposureStatus.TOO_BRIGHT}
    ):
        p50 = float(decision.image_facts.get("luminance_p50", 0.5))
        severe = (
            decision.exposure_status == ExposureStatus.TOO_DARK and p50 < 0.24
        ) or (
            decision.exposure_status == ExposureStatus.TOO_BRIGHT and p50 > 0.86
        )
        budget = CorrectionBudget.MODERATE if severe else CorrectionBudget.MILD
        return _CorrectionPlan(
            D2_SCHEMA_VERSION, D2_ENGINE_VERSION, decision.d1_action,
            CandidateType.AUTO_EXPOSURE_CANDIDATE, CorrectionTarget.SAFE_EXPOSURE_ZONE,
            budget, (CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION,),
            {**base_profile, "blockers": []},
            f"D1 authorized independent {decision.exposure_status.value} exposure correction",
        )

    appearance = str(decision.color_appearance_evidence.get("direction") or "NEUTRAL")
    blockers = _color_blockers(decision)
    if decision.d1_action == D1Action.REVIEW_REQUIRED:
        if blockers:
            return _CorrectionPlan(
                D2_SCHEMA_VERSION, D2_ENGINE_VERSION, decision.d1_action,
                CandidateType.NONE, CorrectionTarget.NONE, CorrectionBudget.NONE, (),
                {**base_profile, "blockers": blockers},
                "D1 review state contains a global-color protection blocker",
            )
        if appearance not in {"WARM", "COOL", "OTHER"}:
            return _CorrectionPlan(
                D2_SCHEMA_VERSION, D2_ENGINE_VERSION, decision.d1_action,
                CandidateType.NONE, CorrectionTarget.NONE, CorrectionBudget.NONE, (),
                {**base_profile, "blockers": ["NO_UNIFORM_DIRECTIONAL_COLOR_APPEARANCE"]},
                "D1 review state has no uniform directional color appearance for a global candidate",
            )
        neutral = decision.neutral_color_facts
        distance = float(np.hypot(
            float(neutral.get("median_lab_a", SAFE_NEUTRAL_TARGET_AB[0])) - SAFE_NEUTRAL_TARGET_AB[0],
            float(neutral.get("median_lab_b", SAFE_NEUTRAL_TARGET_AB[1])) - SAFE_NEUTRAL_TARGET_AB[1],
        ))
        budget = CorrectionBudget.MODERATE if distance >= 4.0 else CorrectionBudget.MILD
        return _CorrectionPlan(
            D2_SCHEMA_VERSION, D2_ENGINE_VERSION, decision.d1_action,
            CandidateType.COLOR_REVIEW_CANDIDATE, CorrectionTarget.SAFE_COLOR_ZONE,
            budget, (CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION,),
            {**base_profile, "blockers": []},
            "visible color appearance may receive a review-only candidate; color AUTO remains disabled",
        )

    return _CorrectionPlan(
        D2_SCHEMA_VERSION, D2_ENGINE_VERSION, decision.d1_action,
        CandidateType.NONE, CorrectionTarget.NONE, CorrectionBudget.NONE, (),
        {**base_profile, "blockers": ["D1_ROUTE_NOT_ELIGIBLE"]},
        "D1 route does not authorize a D2 candidate",
    )


def _box_mask(shape: tuple[int, int], boxes: Iterable[Sequence[int]], expansion: float = 0.0) -> np.ndarray:
    height, width = shape
    mask = np.zeros(shape, dtype=bool)
    for box in boxes:
        x, y, box_width, box_height = (int(value) for value in box)
        pad_x, pad_y = int(round(box_width * expansion)), int(round(box_height * expansion))
        x0, y0 = max(0, x - pad_x), max(0, y - pad_y)
        x1 = min(width, x + max(0, box_width) + pad_x)
        y1 = min(height, y + max(0, box_height) + pad_y)
        mask[y0:y1, x0:x1] = True
    return mask


def _person_masks(
    shape: tuple[int, int], boxes: list[tuple[int, int, int, int]],
) -> tuple[np.ndarray, np.ndarray]:
    face = _box_mask(shape, boxes).astype(np.float32)
    person = _box_mask(shape, boxes, expansion=0.55).astype(np.float32)
    return face, person


def _protection_masks(
    rgb01: np.ndarray,
    boxes: list[tuple[int, int, int, int]],
    analysis_mask: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    visible = (
        np.ones(rgb01.shape[:2], dtype=bool)
        if analysis_mask is None
        else np.asarray(analysis_mask, dtype=bool)
    )
    if visible.shape != rgb01.shape[:2] or not visible.any():
        raise ValueError("D2 analysis mask must contain visible source pixels")
    lab = cv2.cvtColor(rgb01.astype(np.float32), cv2.COLOR_RGB2LAB)
    hsv = cv2.cvtColor(rgb01.astype(np.float32), cv2.COLOR_RGB2HSV)
    chroma = np.linalg.norm(lab[..., 1:3], axis=2)
    saturation = hsv[..., 1]
    lightness = lab[..., 0]
    face, person = _person_masks(rgb01.shape[:2], boxes)
    skin_like = (
        visible & (face >= 0.25)
        & (lab[..., 1] > 3.0) & (lab[..., 1] < 30.0)
        & (lab[..., 2] > -2.0) & (lab[..., 2] < 35.0)
        & (lightness > 12.0) & (lightness < 94.0)
    )
    strong = visible & (saturation >= 0.38) & (lightness > 7.0) & (lightness < 98.0)
    neutral = visible & (chroma <= 12.0) & (lightness > 12.0) & (lightness < 94.0) & ~skin_like
    endpoint = np.clip(np.minimum(lightness / 12.0, (100.0 - lightness) / 10.0), 0.0, 1.0)
    return {
        "lab": lab,
        "neutral": neutral,
        "skin": skin_like,
        "strong": strong & (person <= 0.08),
        "endpoint": endpoint.astype(np.float32),
        "face": face,
        "person": person,
        "analysis": visible,
    }


def _execute_basic_rgb01(
    rgb01: np.ndarray,
    parameters: CorrectionParameters,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Execute the sole D2 pixel primitive on normalized managed RGB."""

    rgb_u8 = np.rint(np.clip(rgb01, 0.0, 1.0) * 255.0).astype(np.uint8)
    result = execute_basic_correction(rgb_u8, parameters, input_order="RGB")
    return (
        result.candidate_image.astype(np.float32) / 255.0,
        result.parameter_record,
    )


def _basic_color_candidate(
    rgb01: np.ndarray,
    decision: ColorUsabilityDecision,
    budget: CorrectionBudget,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Convert the existing D1/D2 neutral target into explicit WB controls."""

    neutral = decision.neutral_color_facts
    strength = _COLOR_BUDGET_STRENGTH[budget.value]
    delta_a = SAFE_NEUTRAL_TARGET_AB[0] - float(
        neutral.get("median_lab_a", SAFE_NEUTRAL_TARGET_AB[0])
    )
    delta_b = SAFE_NEUTRAL_TARGET_AB[1] - float(
        neutral.get("median_lab_b", SAFE_NEUTRAL_TARGET_AB[1])
    )
    temperature, tint = white_balance_controls_for_lab_shift(
        delta_a=float(delta_a),
        delta_b=float(delta_b),
        strength=strength,
    )
    return _execute_basic_rgb01(
        rgb01,
        CorrectionParameters(temperature=temperature, tint=tint),
    )


def _clip_ratios(
    rgb01: np.ndarray,
    analysis_mask: np.ndarray | None = None,
) -> tuple[float, float]:
    visible = (
        np.ones(rgb01.shape[:2], dtype=bool)
        if analysis_mask is None
        else np.asarray(analysis_mask, dtype=bool)
    )
    if visible.shape != rgb01.shape[:2] or not visible.any():
        raise ValueError("D2 clip metrics require visible source pixels")
    shadow = float(np.all(rgb01 <= (1.0 / 255.0), axis=2)[visible].mean())
    highlight = float(np.all(rgb01 >= (254.0 / 255.0), axis=2)[visible].mean())
    return shadow, highlight


def _color_metrics(
    source: np.ndarray,
    candidate: np.ndarray,
    masks: dict[str, np.ndarray],
) -> tuple[dict[str, Any], dict[str, Any], tuple[str, ...], float]:
    source_lab = masks["lab"]
    after_lab = cv2.cvtColor(candidate.astype(np.float32), cv2.COLOR_RGB2LAB)
    neutral = masks["neutral"]
    skin = masks["skin"]
    strong = masks["strong"]
    visible = masks["analysis"]
    if int(neutral.sum()) < max(64, int(visible.sum() * 0.003)):
        raise RuntimeError("insufficient skin-excluded neutral pixels for D2 color candidate")
    before_ab = np.median(source_lab[..., 1:3][neutral], axis=0)
    after_ab = np.median(after_lab[..., 1:3][neutral], axis=0)
    before_distance = float(np.linalg.norm(before_ab - SAFE_NEUTRAL_TARGET_AB))
    after_distance = float(np.linalg.norm(after_ab - SAFE_NEUTRAL_TARGET_AB))
    crossed = bool(float(np.dot(before_ab - SAFE_NEUTRAL_TARGET_AB, after_ab - SAFE_NEUTRAL_TARGET_AB)) < 0.0)
    delta_e = np.linalg.norm(after_lab - source_lab, axis=2)

    def masked_mean(mask: np.ndarray) -> float:
        return float(delta_e[mask].mean()) if mask.any() else 0.0

    def masked_p95(mask: np.ndarray) -> float:
        return float(np.percentile(delta_e[mask], 95)) if mask.any() else 0.0

    source_shadow, source_highlight = _clip_ratios(source, visible)
    after_shadow, after_highlight = _clip_ratios(candidate, visible)
    source_hsv = cv2.cvtColor(source.astype(np.float32), cv2.COLOR_RGB2HSV)
    after_hsv = cv2.cvtColor(candidate.astype(np.float32), cv2.COLOR_RGB2HSV)
    before = {
        "neutral_ab": [round(float(value), 5) for value in before_ab],
        "neutral_distance_to_safe_zone": round(before_distance, 5),
        "mean_luminance": round(float(source_lab[..., 0][visible].mean() / 100.0), 6),
        "shadow_clip_ratio": round(source_shadow, 6),
        "highlight_clip_ratio": round(source_highlight, 6),
        "mean_saturation": round(float(source_hsv[..., 1][visible].mean()), 6),
    }
    luma_mae = float(np.abs(after_lab[..., 0] - source_lab[..., 0])[visible].mean())
    skin_mean, skin_p95 = masked_mean(skin), masked_p95(skin)
    brand_mean, brand_p95 = masked_mean(strong), masked_p95(strong)
    after = {
        "neutral_ab": [round(float(value), 5) for value in after_ab],
        "neutral_distance_to_safe_zone": round(after_distance, 5),
        "neutral_improvement": round(before_distance - after_distance, 5),
        "neutral_target_crossed": crossed,
        "skin_delta_e_mean": round(skin_mean, 5),
        "skin_delta_e_p95": round(skin_p95, 5),
        "brand_delta_e_mean": round(brand_mean, 5),
        "brand_delta_e_p95": round(brand_p95, 5),
        "luminance_mae": round(luma_mae, 6),
        "shadow_clip_ratio": round(after_shadow, 6),
        "highlight_clip_ratio": round(after_highlight, 6),
        "shadow_clip_growth": round(after_shadow - source_shadow, 6),
        "highlight_clip_growth": round(after_highlight - source_highlight, 6),
        "mean_saturation": round(float(after_hsv[..., 1][visible].mean()), 6),
        "saturation_growth": round(float(after_hsv[..., 1][visible].mean() - source_hsv[..., 1][visible].mean()), 6),
        "mean_rgb_delta": round(float(np.abs(candidate - source)[visible].mean()), 6),
    }
    violations: list[str] = []
    if after_distance >= before_distance - 0.20:
        violations.append("SAFE_COLOR_ZONE_NOT_APPROACHED")
    if crossed:
        violations.append("REVERSE_COLOR_RISK")
    if skin_mean > 3.5 or skin_p95 > 9.0:
        violations.append("SKIN_PROTECTION_FAILURE")
    if brand_mean > 6.5 or brand_p95 > 13.0:
        violations.append("BRAND_COLOR_PROTECTION_FAILURE")
    if luma_mae > 0.75:
        violations.append("COLOR_EXPOSURE_COUPLING")
    if after_shadow - source_shadow > 0.003:
        violations.append("SHADOW_CRUSH_GROWTH")
    if after_highlight - source_highlight > 0.003:
        violations.append("HIGHLIGHT_CLIP_GROWTH")
    if float(after_hsv[..., 1][visible].mean() - source_hsv[..., 1][visible].mean()) > 0.025:
        violations.append("SATURATION_BOOST")
    score = (
        (before_distance - after_distance)
        - 0.12 * skin_mean
        - 0.06 * brand_mean
        - 0.8 * luma_mae
        - 50.0 * max(0.0, after_shadow - source_shadow)
        - 50.0 * max(0.0, after_highlight - source_highlight)
    )
    return before, after, tuple(violations), float(score)


def _run_color_attempts(
    rgb01: np.ndarray,
    decision: ColorUsabilityDecision,
    budget: CorrectionBudget,
    boxes: list[tuple[int, int, int, int]],
    analysis_mask: np.ndarray | None = None,
) -> tuple[_ExecutorAttempt, ...]:
    masks = _protection_masks(rgb01, boxes, analysis_mask)
    executor = CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION
    try:
        candidate, parameters = _basic_color_candidate(rgb01, decision, budget)
        before, after, violations, score = _color_metrics(rgb01, candidate, masks)
        return (_ExecutorAttempt(
            executor, budget, candidate, parameters, before, after,
            "PASS" if not violations else "RISK", violations, score, tuple(boxes),
        ),)
    except (BasicCorrectionSafetyError, RuntimeError, ValueError, np.linalg.LinAlgError) as exc:
        return (_ExecutorAttempt(
            executor, budget, rgb01.copy(), {"error": str(exc)}, {}, {},
            "EXECUTOR_LIMIT", ("EXECUTOR_LIMIT",), float("-inf"), tuple(boxes),
        ),)


def _luminance_metrics(
    rgb01: np.ndarray,
    analysis_mask: np.ndarray | None = None,
) -> dict[str, float]:
    lab = cv2.cvtColor(rgb01.astype(np.float32), cv2.COLOR_RGB2LAB)
    lightness = lab[..., 0] / 100.0
    visible = (
        np.ones(lightness.shape, dtype=bool)
        if analysis_mask is None
        else np.asarray(analysis_mask, dtype=bool)
    )
    if visible.shape != lightness.shape or not visible.any():
        raise ValueError("D2 luminance metrics require visible source pixels")
    selected_lightness = lightness[visible]
    p01, p05, p50, p95, p99 = np.percentile(selected_lightness, [1, 5, 50, 95, 99])
    shadow, highlight = _clip_ratios(rgb01, visible)
    return {
        "luminance_p01": round(float(p01), 6),
        "luminance_p05": round(float(p05), 6),
        "luminance_p50": round(float(p50), 6),
        "luminance_p95": round(float(p95), 6),
        "luminance_p99": round(float(p99), 6),
        "mean_luminance": round(float(selected_lightness.mean()), 6),
        "shadow_clip_ratio": round(shadow, 6),
        "highlight_clip_ratio": round(highlight, 6),
    }


def _exposure_candidate(
    rgb01: np.ndarray,
    status: ExposureStatus,
    budget: CorrectionBudget,
    analysis_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    visible = (
        np.ones(rgb01.shape[:2], dtype=bool)
        if analysis_mask is None
        else np.asarray(analysis_mask, dtype=bool)
    )
    if visible.shape != rgb01.shape[:2] or not visible.any():
        raise ValueError("D2 exposure candidate requires visible source pixels")
    if status == ExposureStatus.TOO_DARK:
        exposure = _EXPOSURE_BUDGET_EV[status][budget.value]
    elif status == ExposureStatus.TOO_BRIGHT:
        exposure = _EXPOSURE_BUDGET_EV[status][budget.value]
    else:
        raise ValueError("exposure executor requires TOO_DARK or TOO_BRIGHT")
    return _execute_basic_rgb01(
        rgb01,
        CorrectionParameters(exposure=exposure),
    )


def _exposure_attempt(
    rgb01: np.ndarray,
    status: ExposureStatus,
    budget: CorrectionBudget,
    analysis_mask: np.ndarray | None = None,
    person_regions: tuple[tuple[int, int, int, int], ...] = (),
) -> _ExecutorAttempt:
    visible = (
        np.ones(rgb01.shape[:2], dtype=bool)
        if analysis_mask is None
        else np.asarray(analysis_mask, dtype=bool)
    )
    candidate, parameters = _exposure_candidate(rgb01, status, budget, visible)
    before = _luminance_metrics(rgb01, visible)
    after = _luminance_metrics(candidate, visible)
    source_lab = cv2.cvtColor(rgb01.astype(np.float32), cv2.COLOR_RGB2LAB)
    after_lab = cv2.cvtColor(candidate.astype(np.float32), cv2.COLOR_RGB2LAB)
    ab_delta = np.linalg.norm(after_lab[..., 1:3] - source_lab[..., 1:3], axis=2)
    after.update({
        "lab_ab_delta_mean": round(float(ab_delta[visible].mean()), 6),
        "lab_ab_delta_p95": round(float(np.percentile(ab_delta[visible], 95)), 6),
        "shadow_clip_growth": round(after["shadow_clip_ratio"] - before["shadow_clip_ratio"], 6),
        "highlight_clip_growth": round(after["highlight_clip_ratio"] - before["highlight_clip_ratio"], 6),
        "mean_rgb_delta": round(float(np.abs(candidate - rgb01)[visible].mean()), 6),
    })
    violations: list[str] = []
    # A MILD plan is intentionally permitted to stop after a smaller but still
    # measurable move.  MODERATE keeps the stronger minimum; both retain the
    # same clipping and colour-coupling gates below.
    minimum_improvement = 0.012 if budget == CorrectionBudget.MILD else 0.02
    if status == ExposureStatus.TOO_DARK and after["luminance_p50"] <= before["luminance_p50"] + minimum_improvement:
        violations.append("DARK_EXPOSURE_NOT_IMPROVED")
    if status == ExposureStatus.TOO_BRIGHT and after["luminance_p50"] >= before["luminance_p50"] - minimum_improvement:
        violations.append("BRIGHT_EXPOSURE_NOT_IMPROVED")
    if after["shadow_clip_growth"] > 0.002:
        violations.append("SHADOW_CRUSH_GROWTH")
    if after["highlight_clip_growth"] > 0.002:
        violations.append("HIGHLIGHT_CLIP_GROWTH")
    if after["lab_ab_delta_mean"] > 1.50 or after["lab_ab_delta_p95"] > 4.00:
        violations.append("EXPOSURE_COLOR_COUPLING")
    improvement = (
        after["luminance_p50"] - before["luminance_p50"]
        if status == ExposureStatus.TOO_DARK
        else before["luminance_p50"] - after["luminance_p50"]
    )
    return _ExecutorAttempt(
        CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION, budget, candidate, parameters,
        before, after, "PASS" if not violations else "RISK", tuple(violations), float(improvement),
        person_regions,
    )


def generate_candidate(
    image: np.ndarray,
    decision: ColorUsabilityDecision,
    *,
    input_order: str = "RGB",
    person_regions: Iterable[Sequence[int]] | None = None,
    budget_cap: CorrectionBudget = CorrectionBudget.MODERATE,
) -> _D2CandidateResult:
    """Generate one bounded D2 candidate; final acceptance belongs to D3."""

    binding_blocker = _source_binding_blocker(decision, image, input_order)
    if binding_blocker is not None:
        return _preplan_blocked_result(decision, binding_blocker)
    version_blocker = _version_gate_blocker(decision)
    if version_blocker is not None:
        return _preplan_blocked_result(decision, version_blocker)
    try:
        parameter_decision = bound_parameter_decision(decision)
    except ValueError as exc:
        return _preplan_blocked_result(decision, str(exc))
    try:
        bound_person_regions = _resolve_bound_person_regions(decision, person_regions)
    except ValueError as exc:
        return _preplan_blocked_result(decision, str(exc))

    plan = _build_correction_plan(decision, parameter_decision)
    if plan.candidate_type == CandidateType.NONE:
        status = (
            "NOT_APPLICABLE"
            if parameter_decision is not None or decision.d1_action == D1Action.KEEP_ORIGINAL
            else "PROTECTION_BLOCKED"
        )
        disposition = (
            parameter_decision.outcome.value
            if parameter_decision is not None
            else "KEEP_ORIGINAL_OR_REVIEW"
        )
        return _D2CandidateResult(
            D2_SCHEMA_VERSION, D2_ENGINE_VERSION, status, plan, None,
            CandidateExecutor.NONE, {}, {}, {}, (), disposition, None if status == "NOT_APPLICABLE" else plan.reason,
        )

    rgb01, domain = _normalise_image(image, input_order)
    budget = _budget_min(plan.correction_budget, budget_cap)
    if budget == CorrectionBudget.NONE:
        return _D2CandidateResult(
            D2_SCHEMA_VERSION, D2_ENGINE_VERSION, "PROTECTION_BLOCKED", plan, None,
            CandidateExecutor.NONE, {}, {}, {}, (), "KEEP_ORIGINAL_OR_REVIEW", "BUDGET_NONE",
        )

    if parameter_decision is not None:
        if budget != plan.correction_budget:
            return _D2CandidateResult(
                D2_SCHEMA_VERSION,
                D2_ENGINE_VERSION,
                "PROTECTION_BLOCKED",
                plan,
                None,
                CandidateExecutor.NONE,
                {},
                {},
                {},
                (),
                "REVIEW_REQUIRED",
                "D60_03_BUDGET_CAP_WOULD_CHANGE_EXPLICIT_PARAMETERS",
            )
        try:
            execution = execute_basic_correction(
                image,
                parameter_decision.correction_parameters,
                input_order=input_order,
            )
            candidate_rgb01, candidate_domain = _normalise_image(
                execution.candidate_image,
                input_order,
            )
            if (
                candidate_domain.dtype != domain.dtype
                or candidate_domain.source_channels != domain.source_channels
                or not np.array_equal(candidate_domain.analysis_mask, domain.analysis_mask)
            ):
                raise ValueError("D60_03_EXECUTOR_DOMAIN_MISMATCH")
            before = _luminance_metrics(rgb01, domain.analysis_mask)
            after = _luminance_metrics(candidate_rgb01, domain.analysis_mask)
            after["executor_safety_metrics"] = dict(execution.metrics)
            after["mean_rgb_delta"] = round(
                float(np.abs(candidate_rgb01 - rgb01)[domain.analysis_mask].mean()),
                6,
            )
            attempt = _ExecutorAttempt(
                CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION,
                budget,
                candidate_rgb01,
                execution.parameter_record,
                before,
                after,
                "PASS",
                (),
                after["mean_rgb_delta"],
                tuple(bound_person_regions),
            )
        except (BasicCorrectionSafetyError, RuntimeError, TypeError, ValueError) as exc:
            failed = _ExecutorAttempt(
                CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION,
                budget,
                rgb01.copy(),
                {"error": str(exc)},
                {},
                {},
                "EXECUTOR_LIMIT",
                ("EXECUTOR_LIMIT",),
                float("-inf"),
                tuple(bound_person_regions),
            )
            return _D2CandidateResult(
                D2_SCHEMA_VERSION,
                D2_ENGINE_VERSION,
                "EXECUTOR_LIMIT",
                plan,
                None,
                CandidateExecutor.NONE,
                {},
                {},
                {},
                (failed,),
                "KEEP_ORIGINAL_OR_REVIEW",
                "D60_03_EXPLICIT_PARAMETER_EXECUTION_FAILED",
            )
        return _D2CandidateResult(
            D2_SCHEMA_VERSION,
            D2_ENGINE_VERSION,
            "CANDIDATE_READY",
            plan,
            execution.candidate_image,
            CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION,
            execution.parameter_record,
            before,
            after,
            (attempt,),
            "D3_AUDIT_REQUIRED" if plan.candidate_type == CandidateType.AUTO_EXPOSURE_CANDIDATE else "D3_REVIEW_REQUIRED",
            None,
        )

    if plan.candidate_type == CandidateType.COLOR_REVIEW_CANDIDATE:
        # The reused color executors are 8-bit camera-rendered sRGB routes.
        # Refuse unsupported precision instead of silently quantising 16-bit data.
        if np.issubdtype(domain.dtype, np.integer) and domain.bit_depth != 8:
            return _D2CandidateResult(
                D2_SCHEMA_VERSION, D2_ENGINE_VERSION, "PROTECTION_BLOCKED", plan, None,
                CandidateExecutor.NONE, {}, {}, {}, (), "REVIEW_REQUIRED",
                "UNSUPPORTED_COLOR_EXECUTOR_BIT_DEPTH",
            )
        boxes = list(bound_person_regions)
        attempts = _run_color_attempts(rgb01, decision, budget, boxes, domain.analysis_mask)
        passing = [attempt for attempt in attempts if attempt.safety_status == "PASS"]
        if not passing:
            return _D2CandidateResult(
                D2_SCHEMA_VERSION, D2_ENGINE_VERSION, "EXECUTOR_LIMIT", plan, None,
                CandidateExecutor.NONE, {}, {}, {}, attempts, "REVIEW_REQUIRED", "NO_SAFE_COLOR_EXECUTOR",
            )
        selected = max(passing, key=lambda item: item.score)
        selected_plan = _CorrectionPlan(
            plan.schema_version, plan.engine_version, plan.d1_action, plan.candidate_type,
            plan.correction_target, budget, plan.executor_candidates, plan.protection_profile, plan.reason,
        )
        return _D2CandidateResult(
            D2_SCHEMA_VERSION, D2_ENGINE_VERSION, "CANDIDATE_READY", selected_plan,
            _restore_image(selected.candidate_rgb01, domain), selected.executor,
            selected.parameters, selected.before_metrics, selected.after_metrics, attempts,
            "D3_REVIEW_REQUIRED", None,
        )

    attempt = _exposure_attempt(
        rgb01,
        decision.exposure_status,
        budget,
        domain.analysis_mask,
        bound_person_regions,
    )
    selected_plan = _CorrectionPlan(
        plan.schema_version, plan.engine_version, plan.d1_action, plan.candidate_type,
        plan.correction_target, budget, plan.executor_candidates, plan.protection_profile, plan.reason,
    )
    if attempt.safety_status != "PASS":
        return _D2CandidateResult(
            D2_SCHEMA_VERSION, D2_ENGINE_VERSION, "EXECUTOR_LIMIT", selected_plan, None,
            CandidateExecutor.NONE, {}, attempt.before_metrics, attempt.after_metrics, (attempt,),
            "KEEP_ORIGINAL_OR_REVIEW", "EXPOSURE_PROTECTION_FAILURE",
        )
    return _D2CandidateResult(
        D2_SCHEMA_VERSION, D2_ENGINE_VERSION, "CANDIDATE_READY", selected_plan,
        _restore_image(attempt.candidate_rgb01, domain), attempt.executor,
        attempt.parameters, attempt.before_metrics, attempt.after_metrics, (attempt,),
        "D3_AUDIT_REQUIRED", None,
    )


__all__ = [
    "D2_SCHEMA_VERSION",
    "D2_ENGINE_VERSION",
    "D2_SUPPORTED_D1_SCHEMA_VERSION",
    "D2_SUPPORTED_D1_ENGINE_VERSION",
    "D2_SUPPORTED_D1_RULE_VERSION",
    "D2_SUPPORTED_SOURCE_FINGERPRINT_VERSION",
    "CandidateType",
    "CorrectionBudget",
    "CorrectionTarget",
    "CandidateExecutor",
    "generate_candidate",
]
