"""Product binding for the frozen reference decision; no matching mathematics."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from .objective_diagnosis import build_objective_diagnosis
from .reference_matching import LIMITS, ReferenceMatchingDecision, decide_reference_matching
from .usability_decision import analyze_color_usability, compute_source_fingerprint


def reference_decision_record(decision: ReferenceMatchingDecision) -> dict:
    """Keep replay/provenance facts, never private source paths in public evidence."""
    record = decision.to_record()
    for role in ("TARGET", "REFERENCE"):
        record[f"{role}_PROFILE"][f"{role}_SOURCE"].pop("PATH", None)
    return record


def reference_decision_digest(decision: ReferenceMatchingDecision) -> str:
    payload = json.dumps(reference_decision_record(decision), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "hdde.reference-decision.v1:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_reference_binding(decision, source, parameters, *, input_order="RGB") -> None:
    if type(decision) is not ReferenceMatchingDecision:
        raise ValueError("REFERENCE_DECISION_TYPE_INVALID")
    if decision.match_strength != LIMITS.default_strength:
        raise ValueError("REFERENCE_PRODUCT_STRENGTH_NOT_VALIDATED")
    if decision.target.source.source_fingerprint != compute_source_fingerprint(source, input_order=input_order):
        raise ValueError("REFERENCE_TARGET_SOURCE_IDENTITY_MISMATCH")
    if decision.parameters.to_record() != parameters.to_record():
        raise ValueError("REFERENCE_PARAMETER_IDENTITY_MISMATCH")
    # Recompute only the frozen scalar decision, not an image transform. D3
    # must not accept mutated controls or a status supplied by an API client.
    expected = decide_reference_matching(decision.target, decision.reference)
    if expected.to_record() != decision.to_record():
        raise ValueError("REFERENCE_DECISION_INTEGRITY_MISMATCH")


def candidate_reference_values(candidate, decision, *, input_order="RGB") -> dict:
    """Measure candidate in the same existing profile domains as the two inputs."""
    diagnosis = build_objective_diagnosis(analyze_color_usability(candidate, input_order=input_order))
    profile = replace(
        decision.target,
        source=replace(decision.target.source, source_fingerprint=diagnosis.source_fingerprint),
        diagnosis_json=json.dumps(diagnosis.to_dict(), sort_keys=True, allow_nan=False),
    )
    return profile.values()
