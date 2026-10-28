"""One-pass global reference intent -> the frozen nine controls (D60-05C).

Profiles contain measured D1/D60-03 facts, never reference pixels. This module
does not execute, publish, register Results, or grant D3 acceptance authority.
Matching units/limits below are conservative policy, not executor mathematics.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from math import hypot, isfinite, log2
from numbers import Real
from pathlib import Path
from types import MappingProxyType

from .color_management import (
    acquire_validated_managed_source_snapshot, load_color_managed_source,
)
from .executors.basic_correction import (
    _SATURATION_POSITIVE_LIMIT, _VIBRANCE_POSITIVE_LIMIT, _srgb_to_linear,
    white_balance_controls_for_lab_shift,
)
from .objective_diagnosis import build_objective_diagnosis
from .parameters import CorrectionParameters, PARAMETER_SPECS
from .usability_decision import analyze_color_usability

REFERENCE_SCHEMA = "hdde.global-reference-matching.v1"


@dataclass(frozen=True)
class MatchingLimits:
    default_strength: float = 0.45
    maximum_strength: float = 0.65
    medium_comparability_scale: float = 0.5
    low_luminance_distance: float = 0.40
    medium_luminance_distance: float = 0.12
    incompatible_scene_distance: float = 0.25
    medium_range_distance: float = 0.22
    low_color_distribution_distance: float = 0.80
    medium_color_distribution_distance: float = 0.40
    minimum_dynamic_range: float = 0.045
    minimum_neutral_ratio: float = 0.025
    monochrome_coverage: float = 0.90
    monochrome_minimum_strong_ratio: float = 0.50
    strong_color_protection_ratio: float = 0.12
    possible_skin_ratio: float = 0.025
    highlight_risk: float = 0.015
    shadow_risk: float = 0.025
    minimum_luminance: float = 0.01
    minimum_saturation_denominator: float = 0.10
    minimum_applied_percent: float = 1.0
    minimum_applied_ev: float = 0.02
    reliable_profile_confidence: float = 0.75
    axis_minimum_cells: int = 6
    axis_minimum_neutral_ratio: float = 0.10
    response_denominator_floor: float = 0.10
    low_saturation_p90: float = 0.50
    low_saturation_uniform_share: float = 0.50
    exposure_headroom_p95: float = 0.75


LIMITS = MatchingLimits()


@dataclass(frozen=True)
class FinalCalibrationLimits:
    # Matching-policy budgets, NOT QualityEvidence acceptance thresholds.
    # Source-ROI/percentile proxies are bounded estimates; encoded validation
    # and human review remain necessary. Executor effect units are imported.
    wb_vector_lab_budget: float = 4.0
    skin_chroma_lab_budget: float = 5.0
    relative_chroma_budget: float = 0.35
    selective_chroma_share: float = 0.75
    neutral_a_bound: float = 8.0
    neutral_b_bound: float = 12.0
    encoded_highlight_ceiling: float = 0.90


CALIBRATION_LIMITS = FinalCalibrationLimits()
# gain: parameter units / measured-statistic unit. Caps remain strength-scaled
# on the conservative path; a proven per-axis budget may use the physical cap.
# Tail controls use absolute endpoints. Their shared global-tone budget is
# reduced below; a p05-p50 residual can invert the intended shadow direction
# when the reference lifts its midtones, so it is not a shadow target.
POLICY = MappingProxyType({
    "exposure": (0.50, 0.65, 0.08, "LUMINANCE", "log2(mean RGB luminance)"),
    "brightness": (65.0, 18.0, 0.015, "LUMINANCE", "median RGB luminance [0,1]"),
    "contrast": (80.0, 24.0, 0.025, "LUMINANCE", "p95-p05 RGB luminance"),
    "temperature": (1.0, 36.0, 0.30, "COLOR", "neutral Lab b*"),
    "tint": (1.0, 30.0, 0.30, "COLOR", "neutral Lab a*"),
    "saturation": (65.0, 24.0, 0.025, "SATURATION", "HSV saturation p90"),
    "vibrance": (45.0, 20.0, 0.025, "SATURATION", "HSV saturation p50/p90 balance"),
    "highlights": (100.0, 24.0, 0.015, "LUMINANCE", "p95 RGB luminance"),
    "shadows": (100.0, 24.0, 0.015, "LUMINANCE", "p05 RGB luminance"),
})
SKIN_CAPS = MappingProxyType({
    "exposure": 0.32, "brightness": 12.0, "contrast": 16.0,
    "temperature": 18.0, "tint": 14.0, "saturation": 14.0,
    "vibrance": 12.0, "highlights": 16.0, "shadows": 16.0,
})
# Applied universally as an identity budget, with tighter strong-color limits.
# These are not brand/product recognition; an unknown product is still protected.
IDENTITY_CAPS = MappingProxyType({
    "temperature": 24.0, "tint": 20.0, "saturation": 20.0, "vibrance": 16.0,
})
STRONG_COLOR_CAPS = MappingProxyType({
    "temperature": 10.0, "tint": 8.0, "saturation": 12.0, "vibrance": 10.0,
})


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class ColorSource:
    path: str
    encoded_sha256: str
    managed_pixel_sha256: str
    source_fingerprint: str
    color_management: str
    source_format: str
    source_dpi: tuple[float, float] | None

    def to_record(self):
        return {
            "PATH": self.path, "ENCODED_SHA256": self.encoded_sha256,
            "MANAGED_PIXEL_SHA256": self.managed_pixel_sha256,
            "SOURCE_FINGERPRINT": self.source_fingerprint,
            "COLOR_MANAGEMENT": self.color_management,
            "WORKING_SPACE": "sRGB IEC61966-2.1", "FORMAT": self.source_format,
            "DPI": list(self.source_dpi) if self.source_dpi else None,
        }


@dataclass(frozen=True)
class _ColorProfile:
    source: ColorSource
    # Canonical JSON snapshots prevent mutable D1 evidence aliasing.
    diagnosis_json: str
    distribution_json: str

    def __post_init__(self):
        if type(self.source) is not ColorSource:
            raise TypeError("REFERENCE_MATCH_SOURCE_CONTRACT_INVALID")
        diagnosis, distribution = self.diagnosis, self.distribution
        # No NaN/Infinity or mutable caller evidence enters a recorded profile.
        object.__setattr__(self, "diagnosis_json", _json(diagnosis))
        object.__setattr__(self, "distribution_json", _json(distribution))
        if diagnosis["source_fingerprint"] != self.source.source_fingerprint:
            raise ValueError("REFERENCE_MATCH_PROFILE_SOURCE_IDENTITY_MISMATCH")
        if not 0 <= diagnosis["DIAGNOSIS_CONFIDENCE"] <= 1:
            raise ValueError("REFERENCE_MATCH_CONFIDENCE_INVALID")
        for value in (*self.values().values(), *distribution["family_coverage"].values()):
            if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
                raise ValueError("REFERENCE_MATCH_STATISTIC_INVALID")

    @property
    def diagnosis(self):
        return json.loads(self.diagnosis_json)

    @property
    def distribution(self):
        return json.loads(self.distribution_json)

    def values(self):
        d = self.diagnosis
        l = d["EXPOSURE"]["evidence"]
        s = d["SATURATION"]["evidence"]
        return {
            "exposure": log2(max(l["mean_luminance"], LIMITS.minimum_luminance)),
            "brightness": l["luminance_p50"],
            "contrast": l["luminance_p95"] - l["luminance_p05"],
            "temperature": d["WHITE_BALANCE"]["evidence"]["neutral_lab_b"],
            "tint": d["WHITE_BALANCE"]["evidence"]["neutral_lab_a"],
            "saturation": s["saturation_p90"],
            "vibrance": s["saturation_p50"] / max(
                s["saturation_p90"], LIMITS.minimum_saturation_denominator),
            "highlights": l["luminance_p95"],
            "shadows": l["luminance_p05"],
        }

    def to_record(self):
        prefix = "REFERENCE" if isinstance(self, ReferenceColorTarget) else "TARGET"
        d = self.diagnosis
        b = self.values()["temperature"]
        a = self.values()["tint"]
        return {
            "SCHEMA_VERSION": REFERENCE_SCHEMA, f"{prefix}_SOURCE": self.source.to_record(),
            f"{prefix}_LUMINANCE_PROFILE": d["EXPOSURE"],
            f"{prefix}_WHITE_BALANCE": d["WHITE_BALANCE"],
            f"{prefix}_TEMPERATURE_STATE": {"LAB_B": b, "DIRECTION": "WARM" if b > 0 else "COOL" if b < 0 else "NEUTRAL"},
            f"{prefix}_TINT_STATE": {"LAB_A": a, "DIRECTION": "MAGENTA" if a > 0 else "GREEN" if a < 0 else "NEUTRAL"},
            f"{prefix}_CONTRAST_PROFILE": d["CONTRAST"],
            f"{prefix}_SATURATION_PROFILE": d["SATURATION"],
            f"{prefix}_VIBRANCE_PROFILE": {"P50_P90_BALANCE": self.values()["vibrance"], "SEMANTIC": "low/mid saturation relative to upper saturation; percentile proxy, not a spatial mask"},
            f"{prefix}_HIGHLIGHT_PROFILE": d["HIGHLIGHTS"],
            f"{prefix}_SHADOW_PROFILE": d["SHADOWS"],
            f"{prefix}_NEUTRAL_EVIDENCE": d["NEUTRAL_COLOR_EVIDENCE"],
            f"{prefix}_COLOR_CAST": d["COLOR_CAST"],
            f"{prefix}_CONFIDENCE": d["DIAGNOSIS_CONFIDENCE"],
            "OBJECTIVE_DIAGNOSIS": d, "COLOR_DISTRIBUTION": self.distribution,
        }


@dataclass(frozen=True)
class TargetColorProfile(_ColorProfile):
    pass


@dataclass(frozen=True)
class ReferenceColorTarget(_ColorProfile):
    pass


def _load_profile(path, profile_type):
    source_path = Path(path).resolve(strict=True)
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    managed = load_color_managed_source(source_path)
    snapshot = acquire_validated_managed_source_snapshot(managed)
    if not snapshot.valid:
        raise ValueError(snapshot.blocker)
    observations = analyze_color_usability(snapshot.pixels, input_order="RGB")
    diagnosis = build_objective_diagnosis(observations)
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != digest:
        raise ValueError("REFERENCE_MATCH_SOURCE_CHANGED_DURING_ANALYSIS")
    source = ColorSource(
        str(source_path), digest, snapshot.processing_snapshot_sha256,
        diagnosis.source_fingerprint, managed.profile_status,
        managed.source_format, managed.source_dpi,
    )
    distribution = {
        "family_coverage": observations.global_color_facts["family_coverage"],
        "strong_color_ratio": observations.global_color_facts["strong_color_ratio"],
        "dominant_color_risk": observations.dominant_color_risk,
        "skin_like_pixel_ratio": observations.skin_color_facts["skin_like_pixel_ratio"],
        "skin_headroom_facts": observations.skin_color_facts,
        # Preserve existing frozen D1 scalar evidence, without changing D1/D60-03
        # diagnosis or retaining pixels. A class-boundary flip is not necessarily
        # an uncertain *axis difference* under an explicit reference intent.
        "neutral_axis_evidence": {
            "quantization": observations.color_appearance_evidence["quantization_stability"],
            "spatial": observations.spatial_color_facts,
        },
    }
    return profile_type(source, _json(diagnosis.to_dict()), _json(distribution))


def load_target_color_profile(path: str | Path) -> TargetColorProfile:
    return _load_profile(path, TargetColorProfile)


def load_reference_color_target(path: str | Path) -> ReferenceColorTarget:
    return _load_profile(path, ReferenceColorTarget)


@dataclass(frozen=True)
class ColorDifference:
    # Fixed parameter order; scalar-only evidence, no reference image/mask.
    items: tuple[tuple[str, float, float, float], ...]

    @classmethod
    def between(cls, target: TargetColorProfile, reference: ReferenceColorTarget):
        if type(target) is not TargetColorProfile or type(reference) is not ReferenceColorTarget:
            raise TypeError("REFERENCE_MATCH_PROFILE_ROLES_INVALID")
        left, right = target.values(), reference.values()
        return cls(tuple((n, left[n], right[n], right[n] - left[n]) for n in PARAMETER_SPECS))

    def to_record(self):
        return {n: {"SOURCE_VALUE": s, "REFERENCE_VALUE": r, "RAW_DELTA": delta,
                    "UNIT": POLICY[n][4]} for n, s, r, delta in self.items}


@dataclass(frozen=True)
class ReferenceTargetComparability:
    luminance: str
    color: str
    saturation: str
    reasons: tuple[str, ...]

    def to_record(self):
        return {"LUMINANCE_COMPARABILITY": self.luminance,
                "COLOR_COMPARABILITY": self.color,
                "SATURATION_COMPARABILITY": self.saturation, "REASONS": list(self.reasons)}


def compare_profiles(target: TargetColorProfile, reference: ReferenceColorTarget):
    ColorDifference.between(target, reference)  # validates role contract
    td, rd = target.diagnosis, reference.diagnosis
    tv, rv = target.values(), reference.values()
    reasons = []
    center_distance = abs(tv["brightness"] - rv["brightness"])
    ts, rs = (d["SCENE_RISK"]["evidence"]["scene_intent"] for d in (td, rd))
    scene_mismatch = (ts != rs and ("LEGITIMATE_DARK" in (ts, rs) or "LEGITIMATE_HIGH_KEY" in (ts, rs)))
    if center_distance > LIMITS.low_luminance_distance or (scene_mismatch and center_distance > LIMITS.incompatible_scene_distance):
        lum = "LOW"
        reasons.append("INCOMPARABLE_LUMINANCE_SCENE")
    elif (center_distance > LIMITS.medium_luminance_distance
          or abs(tv["contrast"] - rv["contrast"]) > LIMITS.medium_range_distance
          or td["SKIN_RISK"]["evidence"]["person_present"] != rd["SKIN_RISK"]["evidence"]["person_present"]):
        lum = "MEDIUM"
        reasons.append("PARTIAL_LUMINANCE_COMPARABILITY")
    else:
        lum = "HIGH"
    neutrals = [d["NEUTRAL_COLOR_EVIDENCE"]["state"] for d in (td, rd)]
    color = "HIGH" if all(n == "SUFFICIENT" for n in neutrals) else "LOW"
    if color == "LOW":
        reasons.append("NO_COMMON_STABLE_NEUTRAL_ANCHOR")
    left, right = target.distribution, reference.distribution
    distribution_distance = sum(abs(left["family_coverage"][n] - right["family_coverage"][n])
                                for n in left["family_coverage"])
    if distribution_distance > LIMITS.low_color_distribution_distance:
        saturation = "LOW"
        reasons.append("INCOMPARABLE_COLOR_DISTRIBUTION")
    elif distribution_distance > LIMITS.medium_color_distribution_distance:
        saturation = "MEDIUM"
        reasons.append("PARTIAL_COLOR_DISTRIBUTION_COMPARABILITY")
    else:
        saturation = "HIGH"
    return ReferenceTargetComparability(lum, color, saturation, tuple(reasons))


@dataclass(frozen=True)
class MatchingDimension:
    name: str
    source_value: float
    reference_value: float
    raw_delta: float
    allowed_delta: float
    final_parameter: float
    confidence: float
    limit_reasons: tuple[str, ...]
    budget_json: str = "{}"
    trace_json: str = "[]"

    def to_record(self):
        return {"SOURCE_VALUE": self.source_value, "REFERENCE_VALUE": self.reference_value,
                "RAW_DELTA": self.raw_delta, "ALLOWED_DELTA": self.allowed_delta,
                "FINAL_PARAMETER": self.final_parameter, "CONFIDENCE": self.confidence,
                "UNIT": POLICY[self.name][4], "LIMIT_REASON": list(self.limit_reasons),
                "RISK_AWARE_MATCH_BUDGET": json.loads(self.budget_json),
                "LIMIT_CONTRIBUTION_TRACE": json.loads(self.trace_json)}


@dataclass(frozen=True)
class ReferenceMatchingDecision:
    target: TargetColorProfile
    reference: ReferenceColorTarget
    difference: ColorDifference
    comparability: ReferenceTargetComparability
    match_strength: float
    status: str
    parameters: CorrectionParameters
    dimensions: tuple[MatchingDimension, ...]
    reasons: tuple[str, ...]

    def to_record(self):
        return {
            "SCHEMA_VERSION": REFERENCE_SCHEMA,
            "TARGET_PROFILE": self.target.to_record(),
            "REFERENCE_PROFILE": self.reference.to_record(),
            "COLOR_DIFFERENCE": self.difference.to_record(),
            **self.comparability.to_record(), "MATCH_STRENGTH": self.match_strength,
            "REFERENCE_MATCH_STATUS": self.status, "REASONS": list(self.reasons),
            "DIMENSIONS": {item.name: item.to_record() for item in self.dimensions},
            "CORRECTION_PARAMETERS": self.parameters.to_record(),
            "D3_ACCEPTANCE_AUTHORITY": "NOT_GRANTED_BY_REFERENCE_MATCHING",
            "MATCH_BUDGET_MODEL": "hdde.reference-risk-budget.v2",
            "MATCH_TIER": ("ASSERTIVE_SAFE" if any(
                json.loads(i.budget_json).get("final_calibration", {}).get("AMPLIFIED", False)
                for i in self.dimensions) else "PROTECTED" if self.status == "INSUFFICIENT_EVIDENCE"
                else "CONSERVATIVE" if self.status != "FULL_MATCH" else "STANDARD"),
        }


def _coherent_tint_delta(target, reference, comparability):
    """Axis-specific comparability, NOT a replacement WB diagnosis or fallback.

    Only existing perturbation envelopes and spatial scalar facts are used.
    Require the intended a* shift to dominate both quantization uncertainty and
    each image's spatial a* spread. A varying b* field must not erase a reliable
    a* relation, but actual strong-color mixed lighting remains disallowed.
    """
    result = {"eligible": False, "reason": "NO_RELIABLE_TINT_AXIS_DELTA"}
    if comparability.luminance != "HIGH" or comparability.saturation != "HIGH":
        return result
    ranges, spans = [], []
    for profile in (target, reference):
        d = profile.diagnosis
        facts = profile.distribution.get("neutral_axis_evidence")
        if (not facts or d["NEUTRAL_COLOR_EVIDENCE"]["state"] not in {"SUFFICIENT", "UNSTABLE"}
                or d["SKIN_RISK"]["state"] == "HIGH"
                or d["CLIPPING"]["state"] in {"ELEVATED", "SEVERE"}):
            return result
        spatial, quant = facts["spatial"], facts["quantization"]
        cells = spatial["cells"]
        if (spatial["strong_color_mixed"] or len(cells) < LIMITS.axis_minimum_cells
                or quant["feature_ranges"]["neutral_ratio"][0] < LIMITS.axis_minimum_neutral_ratio
                or d["NEUTRAL_COLOR_EVIDENCE"]["confidence"] < LIMITS.reliable_profile_confidence):
            return result
        ranges.append(quant["feature_ranges"]["neutral_a"])
        spans.append(max(c["a"] for c in cells) - min(c["a"] for c in cells))
    interval = (ranges[1][0] - ranges[0][1], ranges[1][1] - ranges[0][0])
    raw_delta = reference.values()["tint"] - target.values()["tint"]
    certain_delta = min(abs(v) for v in interval)
    result.update(delta_interval=list(interval), spatial_axis_spans=spans)
    if (interval[0] * interval[1] <= 0 or abs(raw_delta) <= POLICY["tint"][2]
            or certain_delta <= max(*spans, POLICY["tint"][2])):
        return result
    result.update(eligible=True, reason="QUANTIZED_CLASS_BOUNDARY_BUT_COHERENT_TINT_DELTA",
                  confidence_scale=min(1.0, certain_delta / abs(raw_delta)))
    return result


def _risk_aware_budget(target, reference, comparability, name, delta, tint_evidence):
    """Grant per-dimension headroom, never a global match-strength increase."""
    td, rd = target.diagnosis, reference.diagnosis
    result = {"eligible": False, "mode": "PROTECTED_LIMITED_MATCH",
              "gain_multiplier": 1.0, "uniform_share": 1.0,
              "deduplicate_strong_color_proxy": False, "reliable_medium": False}
    if (min(td["DIAGNOSIS_CONFIDENCE"], rd["DIAGNOSIS_CONFIDENCE"]) < LIMITS.reliable_profile_confidence
            or any(p.distribution["dominant_color_risk"] == "HIGH" for p in (target, reference))
            or any(d["SKIN_RISK"]["state"] == "HIGH"
                   or d["SKIN_RISK"]["evidence"]["local_person_color_risk"]
                   or d["CLIPPING"]["state"] in {"ELEVATED", "SEVERE"}
                   for d in (td, rd))):
        return result
    if name == "tint" and comparability.color == "LOW" and tint_evidence["eligible"]:
        return {**result, "eligible": True, "mode": "COHERENT_TINT_AXIS",
                "deduplicate_strong_color_proxy": True, "axis_evidence": tint_evidence}
    scenes = [d["SCENE_RISK"]["evidence"]["scene_intent"] for d in (td, rd)]
    people = [d["SKIN_RISK"]["evidence"]["person_present"] for d in (td, rd)]
    compatible_scene = scenes[0] == scenes[1] and scenes[0] in {"GENERAL", "PERSON_SCENE"}
    if not compatible_scene or people[0] != people[1] or comparability.saturation != "HIGH":
        return result
    # A coherent person-to-person relation must not also be charged the generic
    # 'possibly a brand' strong-color proxy. The skin and identity caps remain.
    paired_person = all(people)
    if not paired_person and any(p.distribution["dominant_color_risk"] != "LOW"
                                 or p.distribution["strong_color_ratio"] >= LIMITS.strong_color_protection_ratio
                                 for p in (target, reference)):
        return result
    if name == "exposure" and (td["EXPOSURE"]["state"] == "UNDEREXPOSED" and delta > 0
            and rd["EXPOSURE"]["state"] == "ACCEPTABLE"
            and target.values()["highlights"] < LIMITS.exposure_headroom_p95
            and comparability.luminance != "LOW"):
        result.update(eligible=True, mode="OBJECTIVE_UNDEREXPOSURE_HEADROOM", reliable_medium=True,
                      gain_multiplier=1.0 / POLICY["exposure"][0])
    if comparability.luminance != "HIGH":
        return result
    if (name == "temperature" and comparability.color == "HIGH"
            and td["WHITE_BALANCE"]["state"] in {"WARM", "COOL"}
            and target.values()[name] * delta < 0):
        result.update(eligible=True, mode="CORRECTIVE_TEMPERATURE_HEADROOM")
    if name == "contrast" and delta > 0 and td["CONTRAST"]["state"] != "HIGH":
        source_range = target.values()["contrast"]
        # Endpoint-preserving contrast has weak response near the ends of the
        # range. Normalize this existing statistic-to-control policy by its
        # bounded source response; this does not execute or inspect a candidate.
        result.update(eligible=True, mode="COMPARABLE_CONTRAST_HEADROOM",
                      gain_multiplier=1.0 / max(LIMITS.response_denominator_floor,
                                                source_range * (1.0 - source_range)))
    sat = td["SATURATION"]["evidence"]
    sat_delta = reference.values()["saturation"] - target.values()["saturation"]
    wb_similar = all(abs(reference.values()[n] - target.values()[n]) <= POLICY[n][2]
                     for n in ("temperature", "tint"))
    neutral_facts = [p.distribution.get("neutral_axis_evidence") for p in (target, reference)]
    if (all(neutral_facts)
            and td["WHITE_BALANCE"]["state"] == rd["WHITE_BALANCE"]["state"] == "NEUTRAL"):
        envelopes = [f["quantization"]["feature_ranges"] for f in neutral_facts]
        # A label alone is not evidence of the same WB intent. Both measured
        # axes must overlap within the existing input-quantization envelopes.
        wb_similar |= all(max(e[n][0] for e in envelopes) <= min(e[n][1] for e in envelopes)
                          for n in ("neutral_a", "neutral_b"))
    if name in {"saturation", "vibrance"} and wb_similar and abs(sat_delta) > POLICY["saturation"][2]:
        result.update(eligible=True, mode="COMPARABLE_CHROMA_HEADROOM")
        if sat_delta > 0 and sat["saturation_p90"] < LIMITS.low_saturation_p90:
            if name == "saturation":
                result["uniform_share"] = LIMITS.low_saturation_uniform_share
            else:
                result["gain_multiplier"] = 1.0 / max(LIMITS.minimum_saturation_denominator, sat["saturation_p50"])
            result["mode"] = "LOW_SATURATION_VIBRANCE_PRIORITY"
    if result["eligible"]:
        result["deduplicate_strong_color_proxy"] = paired_person
    return result


def _decide_conservative_reference_matching(
    target: TargetColorProfile, reference: ReferenceColorTarget,
    *, match_strength: float = LIMITS.default_strength,
) -> ReferenceMatchingDecision:
    if isinstance(match_strength, bool) or not isinstance(match_strength, Real):
        raise TypeError("MATCH_STRENGTH_MUST_BE_FINITE_NUMBER")
    if not isfinite(match_strength):
        raise ValueError("MATCH_STRENGTH_MUST_BE_FINITE_NUMBER")
    strength = min(LIMITS.maximum_strength, max(0.0, float(match_strength)))
    difference = ColorDifference.between(target, reference)
    comparability = compare_profiles(target, reference)
    td, rd = target.diagnosis, reference.diagnosis
    reasons = list(comparability.reasons)
    blocked = []
    for label, profile in (("REFERENCE", reference), ("TARGET", target)):
        d = profile.diagnosis
        dist = profile.distribution
        if d["CLIPPING"]["state"] == "SEVERE":
            blocked.append(f"{label}_SEVERE_CLIPPING")
        if d["DYNAMIC_RANGE"]["evidence"]["p95_minus_p05"] < LIMITS.minimum_dynamic_range:
            blocked.append(f"{label}_UNSTABLE_OR_FLAT_STATISTICS")
        if (dist["strong_color_ratio"] >= LIMITS.monochrome_minimum_strong_ratio
                and max(dist["family_coverage"].values()) / dist["strong_color_ratio"] >= LIMITS.monochrome_coverage
                and d["NEUTRAL_COLOR_EVIDENCE"]["evidence"]["pixel_ratio"] < LIMITS.minimum_neutral_ratio):
            blocked.append(f"{label}_EXTREME_MONOCHROME")
        # Mixed neutral evidence disables WB via COLOR_COMPARABILITY. It does
        # not invalidate independently comparable saturation/luminance facts.
        # The same applies to D1's neutral quantization-boundary warning: it
        # is not a claim that luminance or saturation quantiles are unstable.
        # Unreliable neutral AND unrelated color distributions are insufficient.
        if d["NEUTRAL_COLOR_EVIDENCE"]["state"] in {"MIXED_FIELD", "UNSTABLE"} and comparability.saturation == "LOW":
            blocked.append(f"{label}_INCOMPARABLE_MIXED_LIGHTING")
    if all(getattr(comparability, axis) == "LOW" for axis in ("luminance", "color", "saturation")):
        blocked.append("NO_COMPARABLE_DIMENSION")
    if blocked:
        reasons += ["REFERENCE_INSUFFICIENT_EVIDENCE", *blocked]
    skin = (td["SKIN_RISK"]["state"] != "LOW"
            or target.distribution["skin_like_pixel_ratio"] >= LIMITS.possible_skin_ratio)
    strong_color = (target.distribution["strong_color_ratio"] >= LIMITS.strong_color_protection_ratio
                    or target.distribution["dominant_color_risk"] != "LOW")
    values, items = {}, []
    tint_evidence = _coherent_tint_delta(target, reference, comparability)
    raw_deltas = {n: delta for n, _, _, delta in difference.items}
    for name, source_value, reference_value, delta in difference.items:
        gain, cap, deadband, axis, unit = POLICY[name]
        item_reasons = ["BOUNDED_MATCH_STRENGTH"]
        budget = _risk_aware_budget(target, reference, comparability, name, delta, tint_evidence)
        if blocked:
            budget.update(eligible=False, mode="INSUFFICIENT_EVIDENCE",
                          gain_multiplier=1.0, uniform_share=1.0,
                          deduplicate_strong_color_proxy=False, reliable_medium=False)
        if name in {"temperature", "tint"}:
            temp, tint = white_balance_controls_for_lab_shift(
                delta_a=1.0, delta_b=1.0, strength=1.0)
            gain = temp if name == "temperature" else tint
        gain *= budget["gain_multiplier"]
        trace = [{"STEP": "RAW_DELTA", "RAW_DELTA": delta, "UNIT": unit,
                  "PARAMETER_GAIN": gain, "OUTPUT_PARAMETER": delta * gain}]
        value = delta * gain

        def apply_step(step, next_value, **evidence):
            nonlocal value
            trace.append({"STEP": step, "INPUT_PARAMETER": value,
                          "OUTPUT_PARAMETER": next_value,
                          "INPUT_ALLOWED_DELTA": value / gain,
                          "OUTPUT_ALLOWED_DELTA": next_value / gain, **evidence})
            value = next_value

        apply_step("MATCH_STRENGTH", value * strength, STRENGTH=strength)
        apply_step("UNIFORM_SELECTIVE_CHROMA_ALLOCATION", value * budget["uniform_share"],
                   SHARE=budget["uniform_share"])
        level = getattr(comparability, axis.lower())
        scale = {"HIGH": 1.0, "MEDIUM": LIMITS.medium_comparability_scale, "LOW": 0.0}[level]
        if level != "HIGH":
            item_reasons.append(f"{axis}_COMPARABILITY_{level}")
        if budget["mode"] == "COHERENT_TINT_AXIS":
            scale = tint_evidence["confidence_scale"]
            item_reasons.append(tint_evidence["reason"])
        elif budget["reliable_medium"] and level == "MEDIUM":
            scale = 1.0
            item_reasons.append("INDEPENDENT_OBJECTIVE_EXPOSURE_EVIDENCE")
        apply_step("AXIS_COMPARABILITY", value * scale, GLOBAL_LEVEL=level,
                   EFFECTIVE_SCALE=scale, BUDGET_MODE=budget["mode"])
        if name in {"contrast", "highlights", "shadows"} and (
                values.get("exposure", 0.0) or values.get("brightness", 0.0)):
            if name == "contrast" and budget["eligible"]:
                apply_step("SHARED_GLOBAL_TONE_BUDGET", value,
                           REASON="COMPARABLE_CONTRAST_HAS_INDEPENDENT_PHYSICAL_CAP")
                item_reasons.append("COMPARABLE_CONTRAST_HAS_INDEPENDENT_PHYSICAL_CAP")
            else:
                scale *= LIMITS.medium_comparability_scale
                apply_step("SHARED_GLOBAL_TONE_BUDGET", value * LIMITS.medium_comparability_scale,
                           SCALE=LIMITS.medium_comparability_scale)
                item_reasons.append("SHARED_GLOBAL_TONE_BUDGET")
        stops = []
        if name == "vibrance" and delta * raw_deltas["saturation"] < 0 and abs(raw_deltas["saturation"]) > POLICY["saturation"][2]:
            stops.append("NO_OPPOSING_UNIFORM_AND_SELECTIVE_CHROMA")
        exposure_state = td["EXPOSURE"]["state"]
        exposure_corrective = ((exposure_state == "UNDEREXPOSED" and delta > 0)
                               or (exposure_state == "OVEREXPOSED" and delta < 0))
        if name == "exposure" and (not exposure_corrective or td["SCENE_RISK"]["evidence"]["scene_intent"] == "LEGITIMATE_DARK"):
            stops.append("EXPOSURE_ONLY_FOR_TARGET_OBJECTIVE_DEFECT")
        if name == "brightness" and exposure_state in {"UNDEREXPOSED", "OVEREXPOSED"}:
            stops.append("NO_DUPLICATE_EXPOSURE_AND_BRIGHTNESS")
        clip = td["CLIPPING"]["evidence"]
        if (name in {"exposure", "brightness", "contrast", "highlights"} and delta > 0
                and clip["highlight_clip_ratio"] >= LIMITS.highlight_risk):
            stops.append("TARGET_HIGHLIGHT_PROTECTION")
        if (name in {"exposure", "brightness", "shadows"} and delta < 0
                and clip["shadow_clip_ratio"] >= LIMITS.shadow_risk):
            stops.append("TARGET_SHADOW_PROTECTION")
        if name == "contrast" and delta > 0 and td["CONTRAST"]["state"] == "HIGH":
            stops.append("TARGET_CONTRAST_ALREADY_HIGH")
        if abs(delta) <= deadband:
            stops.append("WITHIN_STATISTIC_DEADBAND")
        stops.extend(blocked)
        for reason in stops:
            apply_step(reason, 0.0)
        item_reasons.extend(stops)
        # Strength/observability have already reduced the request. Low-risk,
        # axis-specific headroom must not charge them a second time to the
        # physical skin/identity cap. Unproven cases retain the old budget.
        cap_scale = 1.0 if budget["eligible"] else strength * scale
        caps = [("TARGET_AMPLITUDE_CAP", cap)]
        if name in IDENTITY_CAPS:
            caps.append(("GLOBAL_CONTENT_IDENTITY_BUDGET", IDENTITY_CAPS[name]))
        if skin:
            caps.append(("SKIN_OR_POSSIBLE_SKIN_LIMIT", SKIN_CAPS[name]))
        if strong_color and name in STRONG_COLOR_CAPS:
            if budget["deduplicate_strong_color_proxy"]:
                apply_step("STRONG_COLOR_PRODUCT_BRAND_NEUTRAL_LIMIT", value,
                           REASON="DEDUPLICATED_PROXY_SKIN_AND_IDENTITY_CAPS_RETAINED")
                item_reasons.append("DEDUPLICATED_PROXY_SKIN_AND_IDENTITY_CAPS_RETAINED")
            else:
                caps.append(("STRONG_COLOR_PRODUCT_BRAND_NEUTRAL_LIMIT", STRONG_COLOR_CAPS[name]))
        for reason, physical_cap in caps:
            limit = physical_cap * cap_scale
            apply_step(reason, min(limit, max(-limit, value)),
                       PHYSICAL_CAP=physical_cap, CAP_SCALE=cap_scale, EFFECTIVE_CAP=limit)
            item_reasons.append(reason)
        spec = PARAMETER_SPECS[name]
        apply_step("CORRECTION_PARAMETER_LEGAL_RANGE",
                   min(spec.maximum, max(spec.minimum, value)), MIN=spec.minimum, MAX=spec.maximum)
        # Suppress sub-unit controls, never amplify them. In the 8-bit encoded
        # experiments these small combined controls were dominated by rounding
        # and other active axes. This policy floor is not an executor change.
        floor = LIMITS.minimum_applied_ev if name == "exposure" else LIMITS.minimum_applied_percent
        if 0 < abs(value) < floor:
            apply_step("BELOW_RELIABLE_COMBINED_CONTROL_BUDGET", 0.0, FLOOR=floor)
            item_reasons.append("BELOW_RELIABLE_COMBINED_CONTROL_BUDGET")
        apply_step("FINAL_ALLOWED_DELTA", round(value, 8) if value else 0.0)
        values[name] = value
        confidence = min(td["DIAGNOSIS_CONFIDENCE"], rd["DIAGNOSIS_CONFIDENCE"]) * (0.0 if stops else scale)
        budget.update(effective_gain=gain, cap_scale=cap_scale, effective_comparability_scale=scale)
        items.append(MatchingDimension(name, source_value, reference_value, delta,
                                       value / gain, value, confidence, tuple(item_reasons),
                                       _json(budget), _json(trace)))
    parameters = CorrectionParameters(**values)
    if blocked:
        status = "INSUFFICIENT_EVIDENCE"
    elif comparability.luminance == "LOW" and (parameters.temperature or parameters.tint or parameters.saturation or parameters.vibrance):
        status = "COLOR_ONLY_MATCH"
    elif any(getattr(comparability, a) != "HIGH" for a in ("luminance", "color", "saturation")) or skin or strong_color:
        status = "LIMITED_MATCH"
    else:
        status = "FULL_MATCH"
    if parameters.is_neutral and not blocked:
        reasons.append("NO_SAFE_DIFFERENCE" if strength else "ZERO_MATCH_STRENGTH")
    return ReferenceMatchingDecision(target, reference, difference, comparability, strength,
                                     status, parameters, tuple(items), tuple(reasons))


def _positive_exposure_for_encoded_level(source, desired):
    """Scalar inverse of D2's positive-EV response, not a pixel executor.

    A mean/quantile is only a response proxy (transfer of a mean is not mean
    transfer). Reuse the frozen sRGB unit conversion; solve g*x/(1+(g-1)*x)=y.
    No candidate generation, historical output access, or optimization loop.
    """
    x, y = float(_srgb_to_linear(source)), float(_srgb_to_linear(desired))
    if not 0 < x <= y < 1:
        return 0.0
    return log2(y * (1.0-x) / (x * (1.0-y)))


def _final_axis_calibration(baseline, item):
    target, reference = baseline.target, baseline.reference
    td, rd = target.diagnosis, reference.diagnosis
    budget = json.loads(item.budget_json)
    b, name = item.final_parameter, item.name
    evidence = {
        "RAW_DELTA": item.raw_delta, "B_FINAL_PARAMETER": b,
        "CURRENT_REFERENCE_GAP": {"SOURCE_TO_REFERENCE": item.raw_delta,
                                  "B_ENCODED_TO_REFERENCE": "EXTERNAL_VALIDATION_ONLY"},
        "COMPARABILITY": baseline.comparability.to_record(), "CONFIDENCE": item.confidence,
        "SKIN_HEADROOM": None, "BRAND_HEADROOM": None, "CLIPPING_HEADROOM": None,
        "EXPOSURE_HEADROOM": None, "COLOR_CAST_HEADROOM": None,
        "C_ALLOWED_PARAMETER": b, "AMPLIFIED": False,
        "AMPLIFICATION_REASON": "KEEP_CONSERVATIVE_SCALAR_DECISION",
        "LIMIT_REASON": "NO_ADDITIONAL_AXIS_HEADROOM_PROVEN",
        "HEADROOM_AUTHORITY": "CONSERVATIVE_SCALAR_ESTIMATE_NOT_QUALITY_ACCEPTANCE",
    }
    modes = {"CORRECTIVE_TEMPERATURE_HEADROOM", "COHERENT_TINT_AXIS",
             "LOW_SATURATION_VIBRANCE_PRIORITY", "COMPARABLE_CHROMA_HEADROOM",
             "OBJECTIVE_UNDEREXPOSURE_HEADROOM"}
    if not b or not budget["eligible"] or budget["mode"] not in modes:
        return b, budget["effective_gain"], evidence
    # B's high-risk/mixed-field/scene checks still apply. Require additional
    # actual local facts before spending any budget above B's parameter caps.
    people = [d["SKIN_RISK"]["evidence"]["person_present"] for d in (td, rd)]
    facts = [p.distribution.get("skin_headroom_facts") for p in (target, reference)]
    if (not all(facts) or people[0] != people[1]
            or any(f["local_person_color_risk"] or f["local_person_exposure_risk"] for f in facts)):
        return b, budget["effective_gain"], evidence
    skin_chroma = 0.0
    if any(people):
        for f in facts:
            if (f["trusted_skin_pixel_ratio"] < LIMITS.possible_skin_ratio
                    or f["trusted_skin_median_lab_a"] is None or f["trusted_skin_median_lab_b"] is None):
                return b, budget["effective_gain"], evidence
        skin_chroma = hypot(facts[0]["trusted_skin_median_lab_a"], facts[0]["trusted_skin_median_lab_b"])
    elif any(f["skin_like_pixel_ratio"] >= LIMITS.possible_skin_ratio for f in facts):
        return b, budget["effective_gain"], evidence
    paired_person = all(people)
    if any((p.distribution["dominant_color_risk"] != "LOW"
            or p.distribution["strong_color_ratio"] >= LIMITS.strong_color_protection_ratio)
           for p in (target, reference)) and not (paired_person and (
               budget["deduplicate_strong_color_proxy"] or name == "exposure")):
        return b, budget["effective_gain"], evidence
    if (any(d["CLIPPING"]["state"] in {"ELEVATED", "SEVERE"} for d in (td, rd))
            or td["CLIPPING"]["evidence"]["highlight_clip_ratio"] >= LIMITS.highlight_risk):
        return b, budget["effective_gain"], evidence
    limits = CALIBRATION_LIMITS
    evidence.update(
        SKIN_HEADROOM={"FACTS": facts[0], "TRUSTED_MEDIAN_CHROMA": skin_chroma,
                       "WB_VECTOR_LAB_BUDGET": limits.wb_vector_lab_budget,
                       "CHROMA_LAB_BUDGET": limits.skin_chroma_lab_budget},
        BRAND_HEADROOM={"PAIRED_PERSON_PROXY_DISAMBIGUATED": paired_person,
                        "TARGET_DOMINANT_RISK": target.distribution["dominant_color_risk"],
                        "OBJECTIVE_TONE_ONLY_BUDGET": name == "exposure",
                        "RECOGNIZED_BRAND_AUTHORITY": False},
        CLIPPING_HEADROOM={"SOURCE_FACTS": td["CLIPPING"]["evidence"],
                           "ELEVATED_OR_SEVERE": False, "D2_GAMUT_PROTECTION_REQUIRED": True},
        EXPOSURE_HEADROOM={"SOURCE_P95": target.values()["highlights"],
                           "LOCAL_PERSON_EXPOSURE_RISK": facts[0]["local_person_exposure_risk"]},
        COLOR_CAST_HEADROOM={"A_BOUND": limits.neutral_a_bound, "B_BOUND": limits.neutral_b_bound,
                             "NO_UNREQUESTED_WB_AXIS_CHANGE": True},
    )
    fraction = baseline.match_strength * item.confidence
    raw_request, allowed = b, b
    if name in {"temperature", "tint"}:
        unit_temp, unit_tint = white_balance_controls_for_lab_shift(delta_a=1, delta_b=1, strength=1)
        units = {"temperature": unit_temp, "tint": unit_tint}
        values = baseline.parameters.values()
        other = "tint" if name == "temperature" else "temperature"
        # Reserve the existing other-axis/WB and chroma effects. Use maximum
        # selective response (weight <= 1), not a flattering skin prediction.
        reserve = abs(values[other]) / units[other]
        sat_reserve = abs(values["saturation"]) * (_SATURATION_POSITIVE_LIMIT if values["saturation"] > 0 else 1.0) / 100
        vin_reserve = abs(values["vibrance"]) * (_VIBRANCE_POSITIVE_LIMIT if values["vibrance"] > 0 else 1.0) / 100
        reserve += skin_chroma * (sat_reserve + vin_reserve + sat_reserve*vin_reserve)
        axis_bound = limits.neutral_b_bound if name == "temperature" else limits.neutral_a_bound
        cast_room = max(0.0, axis_bound - (item.source_value if b > 0 else -item.source_value))
        lab_room = min(max(0.0, limits.wb_vector_lab_budget-reserve), cast_room)
        raw_request = item.raw_delta * fraction * units[name]
        cap = min(POLICY[name][1], lab_room * units[name])
        allowed = min(cap, abs(raw_request)) * (1 if b > 0 else -1)
        evidence["SKIN_HEADROOM"].update(RESERVED_OTHER_LAB=reserve, REMAINING_AXIS_LAB=lab_room)
        evidence["COLOR_CAST_HEADROOM"]["DIRECTIONAL_LAB_ROOM"] = cast_room
        reason = "RELIABLE_AXIS_DIFFERENCE_WITH_RESERVED_LAB_DISPLACEMENT_BUDGET"
    elif name in {"saturation", "vibrance"}:
        tv, rv = target.values(), reference.values()
        relative = (rv["saturation"]-tv["saturation"]) / max(tv["saturation"], LIMITS.minimum_saturation_denominator)
        requested = relative * fraction
        cap = limits.relative_chroma_budget
        if skin_chroma:
            cap = min(cap, limits.skin_chroma_lab_budget / skin_chroma)
        bounded = min(cap, abs(requested)) * (1 if requested > 0 else -1)
        if requested > 0 and budget["mode"] != "LOW_SATURATION_VIBRANCE_PRIORITY":
            return b, budget["effective_gain"], evidence

        def control(relative_change):
            if relative_change < 0:
                # Negative Vibrance stays at B. Reserve its maximum response
                # before assigning any additional uniform chroma reduction.
                vin_floor = min(0.0, baseline.parameters.vibrance) / 100
                return ((1.0+relative_change)/(1.0+vin_floor)-1.0)*100 if name == "saturation" else b
            uniform_floor = max(0.0, baseline.parameters.saturation) * _SATURATION_POSITIVE_LIMIT / 100
            selective_floor = max(0.0, baseline.parameters.vibrance) * _VIBRANCE_POSITIVE_LIMIT / 100
            if (1.0+uniform_floor)*(1.0+selective_floor)-1.0 >= relative_change:
                return b  # B already spends this pool; no new budget exists.
            uniform = min(max(uniform_floor, relative_change * (1.0-limits.selective_chroma_share)),
                          (1.0+relative_change)/(1.0+selective_floor)-1.0)
            return (uniform / _SATURATION_POSITIVE_LIMIT * 100 if name == "saturation"
                    else (relative_change-uniform) / ((1.0+uniform)*_VIBRANCE_POSITIVE_LIMIT) * 100)

        raw_request, allowed = control(requested), control(bounded)
        evidence["SKIN_HEADROOM"].update(MAXIMUM_RELATIVE_CHROMA=cap,
                                         PREDICTED_UPPER_CHROMA_DISPLACEMENT=abs(bounded)*skin_chroma)
        evidence["CHROMA_ALLOCATION"] = {
            "REFERENCE_RELATIVE_P90_GAP": relative, "REQUESTED_RELATIVE_CHANGE": requested,
            "BOUNDED_RELATIVE_CHANGE": bounded, "SELECTIVE_SHARE": limits.selective_chroma_share,
            "B_SATURATION_RESERVED": baseline.parameters.saturation,
            "B_VIBRANCE_RESERVED": baseline.parameters.vibrance,
            "VIBRANCE_WEIGHT_UPPER_BOUND": 1.0,
            "SEMANTIC": "shared relative-chroma intent; HSV-to-Lab response remains a proxy",
        }
        reason = "RELATIVE_CHROMA_INTENT_WITH_ONE_SHARED_SKIN_BUDGET"
    elif name == "exposure":
        source_mean = td["EXPOSURE"]["evidence"]["mean_luminance"]
        desired_mean = source_mean + (rd["EXPOSURE"]["evidence"]["mean_luminance"]-source_mean)*fraction
        raw_request = _positive_exposure_for_encoded_level(source_mean, desired_mean)
        source_p95 = target.values()["highlights"]
        high_bound = min(limits.encoded_highlight_ceiling, reference.values()["highlights"])
        high_ev = _positive_exposure_for_encoded_level(source_p95, max(source_p95, high_bound))
        allowed = min(raw_request, high_ev, POLICY["exposure"][1])
        evidence["EXPOSURE_HEADROOM"].update(DESIRED_ENCODED_MEAN=desired_mean,
                                            ENCODED_P95_BOUND=high_bound, P95_EV_ROOM=high_ev)
        reason = "ENCODED_LUMINANCE_INTENT_TO_LINEAR_EV_WITH_HIGHLIGHT_ROOM"
    else:
        return b, budget["effective_gain"], evidence
    evidence.update(UNBOUNDED_C_PARAMETER=raw_request,
                    LIMIT_REASON="MIN_REFERENCE_FRACTION_AND_AXIS_HEADROOM; NO_FULL_COPY; NO_QUALITY_AUTHORITY")
    if abs(allowed) <= abs(b) or allowed*b <= 0:
        return b, budget["effective_gain"], evidence
    allowed = round(allowed, 8)
    evidence.update(C_ALLOWED_PARAMETER=allowed, AMPLIFIED=True, AMPLIFICATION_REASON=reason)
    # ALLOWED_DELTA remains an allocation of the recorded statistic gap, NOT
    # a claim that a nonlinear executor will reproduce that statistic exactly.
    equivalent_gain = abs(raw_request / (item.raw_delta * fraction))
    return allowed, equivalent_gain, evidence


def decide_reference_matching(target, reference, *, match_strength=LIMITS.default_strength):
    """B scalar policy plus final per-axis calibration; exactly zero pixel runs."""
    baseline = _decide_conservative_reference_matching(target, reference, match_strength=match_strength)
    values, dimensions = baseline.parameters.values(), []
    for item in baseline.dimensions:
        value, gain, evidence = _final_axis_calibration(baseline, item)
        budget, trace = json.loads(item.budget_json), json.loads(item.trace_json)
        budget["final_calibration"] = evidence
        if evidence["AMPLIFIED"]:
            budget["final_equivalent_allocation_gain"] = gain
            trace[-1]["STEP"] = "B_FINAL_PARAMETER"
            trace.append({"STEP": "FINAL_CALIBRATION", "INPUT_PARAMETER": item.final_parameter,
                          "OUTPUT_PARAMETER": value, "INPUT_ALLOWED_DELTA": item.allowed_delta,
                          "OUTPUT_ALLOWED_DELTA": value/gain, "EQUIVALENT_ALLOCATION_GAIN": gain,
                          "REASON": evidence["AMPLIFICATION_REASON"]})
            trace.append({"STEP": "FINAL_ALLOWED_DELTA", "INPUT_PARAMETER": value,
                          "OUTPUT_PARAMETER": value, "INPUT_ALLOWED_DELTA": value/gain,
                          "OUTPUT_ALLOWED_DELTA": value/gain})
            values[item.name] = value
        dimensions.append(replace(item, final_parameter=value, allowed_delta=value/gain,
                                  limit_reasons=item.limit_reasons + ((evidence["AMPLIFICATION_REASON"], evidence["LIMIT_REASON"])
                                                                   if evidence["AMPLIFIED"] else ()),
                                  budget_json=_json(budget), trace_json=_json(trace)))
    return replace(baseline, parameters=CorrectionParameters(**values), dimensions=tuple(dimensions))
