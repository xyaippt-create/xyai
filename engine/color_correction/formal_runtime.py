"""Formal D1 -> parameters -> deterministic executor -> quality -> D3 binding.

This module is intentionally a thin production adapter.  D3 remains the only
acceptance authority; D2 is re-run only to materialise the exact candidate that
D3 audited, and its identity must match before any output is written.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from engine.output.publish_safety import publish_image_bytes_with_metadata

from .candidate_generation import CandidateExecutor, generate_candidate
from .color_management import (
    ManagedColorSource,
    encode_color_managed_candidate,
    load_color_managed_source,
    verify_color_managed_output,
)
from .result_audit import (
    D3_AUDIT_VERSION,
    D3_SCHEMA_VERSION,
    AcceptanceAuthority,
    FinalAction,
    _candidate_identity,
    audit_candidate,
    audit_reference_candidate,
    _basic_candidate_identity,
)
from .objective_diagnosis import build_objective_diagnosis
from .parameter_decision import (
    bind_parameter_decision,
    decide_correction_parameters,
)
from .usability_decision import analyze_color_usability


FORMAL_COLOR_RUNTIME_VERSION = "hdde.d4-formal-color-runtime.v1.4"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_source(path: Path) -> ManagedColorSource:
    """Decode through the sole formal color-management boundary."""

    return load_color_managed_source(path)


def _encoded_bytes(
    candidate: np.ndarray,
    *,
    source: ManagedColorSource,
) -> bytes:
    return encode_color_managed_candidate(candidate, source)


def _write_verified_candidate(
    candidate: np.ndarray,
    output_path: Path,
    *,
    source: ManagedColorSource,
    source_path: Path,
    audited_encoding_sha256: str | None = None,
) -> dict[str, Any]:
    expected_suffix = ".png" if source.source_format == "PNG" else ".jpg"
    if output_path.suffix.lower() != expected_suffix:
        raise ValueError("FORMAL_OUTPUT_EXTENSION_MISMATCH")
    payload = _encoded_bytes(
        candidate,
        source=source,
    )
    if audited_encoding_sha256 is not None and hashlib.sha256(payload).hexdigest() != audited_encoding_sha256:
        raise ValueError("D3_AUDITED_ENCODING_IDENTITY_MISMATCH")

    def verify_private(data: bytes) -> None:
        verify_color_managed_output(data, candidate, source)

    published_path, metadata_report, _validation = publish_image_bytes_with_metadata(
        payload,
        output_path,
        source_data=source_path.read_bytes(),
        normalize_orientation=True,
        verify_private=verify_private,
    )
    with Image.open(published_path) as published:
        published.load()
        actual_output_format = published.format
    return {
        "output_path": str(published_path),
        "output_sha256": _sha256_file(published_path),
        "output_size_bytes": published_path.stat().st_size,
        "output_format": actual_output_format,
        "output_metadata": metadata_report,
    }


@dataclass(frozen=True)
class _FormalColorRuntimeResult:
    engine_version: str
    source_sha256: str
    source_format: str
    width: int
    height: int
    source_size_bytes: int
    output_path: str | None
    output_sha256: str | None
    output_format: str | None
    output_size_bytes: int
    processing_time_ms: int
    d1_action: str
    d3_status: str
    d3_final_action: str
    result_action: str
    output_selected: str
    acceptance_authority: str
    candidate_identity: str | None
    analysis: dict[str, Any]
    before_metrics: dict[str, Any]
    after_metrics: dict[str, Any]
    detected_issues: list[str]
    improvements: list[str]
    review_points: list[str]
    applied_actions: list[str]
    parameters: dict[str, Any]
    output_metadata: dict[str, Any] | None

    @property
    def delivery_eligible(self) -> bool:
        return (
            self.result_action == FinalAction.ACCEPT_CORRECTED.value
            and self.output_selected == "CORRECTED_CANDIDATE"
            and bool(self.output_path)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_version": self.engine_version,
            "runtime_schema_version": FORMAL_COLOR_RUNTIME_VERSION,
            "source_sha256": self.source_sha256,
            "source_format": self.source_format,
            "width": self.width,
            "height": self.height,
            "source_size_bytes": self.source_size_bytes,
            "output_path": self.output_path,
            "output_sha256": self.output_sha256,
            "output_format": self.output_format,
            "output_size_bytes": self.output_size_bytes,
            "processing_time_ms": self.processing_time_ms,
            "d1_action": self.d1_action,
            "d3_status": self.d3_status,
            "d3_final_action": self.d3_final_action,
            "result_action": self.result_action,
            "actual_final_action": self.result_action,
            "output_selected": self.output_selected,
            "acceptance_authority": self.acceptance_authority,
            "candidate_identity": self.candidate_identity,
            "delivery_eligible": self.delivery_eligible,
            "analysis": dict(self.analysis),
            "before_metrics": dict(self.before_metrics),
            "after_metrics": dict(self.after_metrics),
            "detected_issues": list(self.detected_issues),
            "improvements": list(self.improvements),
            "review_points": list(self.review_points),
            "applied_actions": list(self.applied_actions),
            "parameters": dict(self.parameters),
        }

    def to_metric_record(self, *, sample_id: str, expected_action: str) -> dict[str, Any]:
        return {
            "sample_id": str(sample_id),
            "expected_action": str(expected_action),
            "actual_final_action": self.result_action,
            "D1_action": self.d1_action,
            "D3_final_action": self.d3_final_action,
            "result_action": self.result_action,
            "output_selected": self.output_selected,
        }


def _validate_result_contract_before_publish(
    *,
    d3_final_action: str,
    result_action: str,
    output_selected: str,
    output_will_exist: bool,
) -> None:
    """Validate result-state invariants without reading or mutating an output path."""

    if d3_final_action != result_action:
        raise RuntimeError("D3_RESULT_ACTION_MISMATCH")
    if result_action == FinalAction.ACCEPT_CORRECTED.value and (
        output_selected != "CORRECTED_CANDIDATE" or not output_will_exist
    ):
        raise RuntimeError("CORRECTED_RESULT_WITHOUT_VERIFIED_OUTPUT")
    if result_action == FinalAction.ACCEPT_ORIGINAL.value and output_will_exist:
        raise RuntimeError("ORIGINAL_RESULT_MUST_NOT_MATERIALIZE_CANDIDATE")


def run_formal_color_runtime(
    source_path: str | Path,
    output_path: str | Path,
    *,
    reference_path: str | Path | None = None,
) -> _FormalColorRuntimeResult:
    """Run the only formal color Result path and materialise D3-selected output."""

    started = time.perf_counter()
    source = Path(source_path).resolve()
    planned_output = Path(output_path).resolve()
    if not source.is_file():
        raise FileNotFoundError("FORMAL_COLOR_SOURCE_NOT_FOUND")
    source_sha = _sha256_file(source)
    source_size = source.stat().st_size
    managed_source = _load_source(source)
    image = managed_source.pixels
    input_order = managed_source.input_order
    source_format = managed_source.source_format
    decision = analyze_color_usability(image, input_order=input_order)
    objective_diagnosis = build_objective_diagnosis(decision)
    reference_decision = None
    reference_source = None
    parameter_decision = None
    if reference_path is None:
        parameter_decision = decide_correction_parameters(objective_diagnosis)
        bind_parameter_decision(decision, parameter_decision)
        audit = audit_candidate(
            image, decision, input_order=input_order,
            managed_source=managed_source, expected_output_format=source_format,
        )
        correction_parameters = parameter_decision.correction_parameters
    else:
        from .reference_matching import load_target_color_profile, load_reference_color_target, decide_reference_matching
        reference_source = Path(reference_path).resolve()
        target_profile = load_target_color_profile(source)
        reference_profile = load_reference_color_target(reference_source)
        if target_profile.source.encoded_sha256 != source_sha:
            raise RuntimeError("FORMAL_COLOR_SOURCE_INTEGRITY_CHANGED")
        reference_decision = decide_reference_matching(target_profile, reference_profile)
        correction_parameters = reference_decision.parameters
        audit = audit_reference_candidate(
            image, decision, reference_decision, managed_source=managed_source, input_order=input_order,
        )

    final_action = audit.final_action.value
    output_will_exist = bool(
        final_action in {FinalAction.ACCEPT_CORRECTED.value, FinalAction.REVIEW_REQUIRED.value}
        and audit.d2_candidate_identity
    )
    if output_will_exist:
        output_selected = (
            "CORRECTED_CANDIDATE"
            if final_action == FinalAction.ACCEPT_CORRECTED.value
            else "REVIEW_CANDIDATE"
        )
    else:
        output_selected = "ORIGINAL" if final_action == FinalAction.ACCEPT_ORIGINAL.value else "NONE"
    _validate_result_contract_before_publish(
        d3_final_action=final_action,
        result_action=final_action,
        output_selected=output_selected,
        output_will_exist=output_will_exist,
    )
    materialized_path: str | None = None
    output_sha: str | None = source_sha if output_selected == "ORIGINAL" else None
    output_format: str | None = source_format if output_selected == "ORIGINAL" else None
    output_size = source_size if output_selected == "ORIGINAL" else 0
    output_metadata: dict[str, Any] | None = None
    before_metrics: dict[str, Any] = {}
    after_metrics: dict[str, Any] = {}
    applied_actions: list[str] = []
    parameters: dict[str, Any] = {
        "d3_schema_version": D3_SCHEMA_VERSION,
        "d3_audit_version": D3_AUDIT_VERSION,
        "correction_parameters": correction_parameters.to_record(),
    }
    if parameter_decision is not None:
        parameters.update({
        "parameter_decision_schema_version": parameter_decision.schema_version,
        "parameter_decision_engine_version": parameter_decision.engine_version,
        "parameter_decision_digest": parameter_decision.decision_digest,
        "parameter_decision_outcome": parameter_decision.outcome.value,
        "correction_parameters": parameter_decision.correction_parameters.to_record(),
        "parameter_decisions": {
            name: item.to_dict()
            for name, item in parameter_decision.parameter_decisions.items()
        },
        })
    else:
        from .reference_integration import reference_decision_digest, reference_decision_record
        parameters.update({
            "reference_decision_digest": reference_decision_digest(reference_decision),
            "reference_matching": reference_decision_record(reference_decision),
        })

    if output_will_exist:
        if reference_decision is not None:
            from .executors.basic_correction import execute_basic_correction
            candidate = execute_basic_correction(image, correction_parameters, input_order=input_order)
            identity = _basic_candidate_identity(image, candidate.candidate_image, correction_parameters, input_order=input_order)
        else:
            candidate = generate_candidate(image, decision, input_order=input_order)
        if candidate.candidate_image is None or (reference_decision is None and candidate.status != "CANDIDATE_READY"):
            raise RuntimeError("D2_CANDIDATE_REMATERIALIZATION_FAILED")
        if reference_decision is None and candidate.executor != CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION:
            raise RuntimeError("FORMAL_COLOR_EXECUTOR_NOT_DETERMINISTIC_BASIC_CORRECTION")
        recorded_parameters = candidate.parameter_record if reference_decision is not None else candidate.executor_parameters
        if recorded_parameters != correction_parameters.to_record():
            raise RuntimeError("FORMAL_COLOR_PARAMETER_DECISION_MISMATCH")
        if reference_decision is None:
            identity = _candidate_identity(decision.source_fingerprint, candidate)
        if identity != audit.d2_candidate_identity:
            raise RuntimeError("D2_D3_CANDIDATE_IDENTITY_MISMATCH")
        if _sha256_file(source) != source_sha:
            raise RuntimeError("FORMAL_COLOR_SOURCE_INTEGRITY_CHANGED")
        if reference_source is not None and _sha256_file(reference_source) != reference_decision.reference.source.encoded_sha256:
            raise RuntimeError("FORMAL_REFERENCE_SOURCE_INTEGRITY_CHANGED")
        verified = _write_verified_candidate(
            candidate.candidate_image,
            planned_output,
            source=managed_source,
            source_path=source,
            audited_encoding_sha256=audit.audit_metrics.get("candidate_encoding", {}).get("ENCODED_SHA256"),
        )
        materialized_path = str(verified["output_path"])
        output_sha = str(verified["output_sha256"])
        output_format = str(verified["output_format"])
        output_size = int(verified["output_size_bytes"])
        output_metadata = dict(verified["output_metadata"])
        applied_actions = [CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION.value]
        if reference_decision is None:
            before_metrics = dict(candidate.before_metrics)
            after_metrics = dict(candidate.after_metrics)
            parameters.update({
            "d2_schema_version": candidate.schema_version,
            "d2_engine_version": candidate.engine_version,
            "candidate_type": candidate.plan.candidate_type.value,
            "correction_target": candidate.plan.correction_target.value,
            "correction_budget": candidate.plan.correction_budget.value,
            "executor": candidate.executor.value,
            "executor_parameters": dict(candidate.executor_parameters),
            "d3_basic_replay": dict(
                audit.audit_metrics.get("basic_correction_replay") or {}
            ),
            })
        else:
            from .reference_integration import candidate_reference_values
            before_metrics = reference_decision.target.values()
            after_metrics = candidate_reference_values(candidate.candidate_image, reference_decision, input_order=input_order)
            parameters.update({
                "executor": CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION.value,
                "executor_parameters": recorded_parameters,
                "d3_basic_replay": dict(audit.audit_metrics.get("basic_correction_replay") or {}),
            })

    if _sha256_file(source) != source_sha:
        raise RuntimeError("FORMAL_COLOR_SOURCE_INTEGRITY_CHANGED")
    if reference_source is not None and _sha256_file(reference_source) != reference_decision.reference.source.encoded_sha256:
        raise RuntimeError("FORMAL_REFERENCE_SOURCE_INTEGRITY_CHANGED")

    improvements = ["原图哈希保持不变，未覆盖或修改原图"]
    review_points: list[str] = []
    if output_selected == "CORRECTED_CANDIDATE":
        improvements.append("D3 已确认目标问题具有正向净收益并完成输出验证")
    elif output_selected == "REVIEW_CANDIDATE":
        improvements.append("候选文件已完成存在、解码、尺寸、格式与摘要验证")
        review_points.append("颜色 Candidate 仅供复核，未获得自动交付权限")
    elif output_selected == "ORIGINAL":
        improvements.append("D3 选择保留原图，未生成正式修改结果")
    else:
        review_points.append("当前证据不足以生成可审核 Candidate")

    detected_issues = []
    if objective_diagnosis.white_balance.state not in {"NEUTRAL", "UNKNOWN"}:
        detected_issues.append(objective_diagnosis.white_balance.state)
    if objective_diagnosis.exposure.state != "ACCEPTABLE":
        detected_issues.append(objective_diagnosis.exposure.state)
    if objective_diagnosis.contrast.state != "ACCEPTABLE":
        detected_issues.append(f"CONTRAST_{objective_diagnosis.contrast.state}")
    if objective_diagnosis.saturation.state != "ACCEPTABLE":
        detected_issues.append(f"SATURATION_{objective_diagnosis.saturation.state}")
    result = _FormalColorRuntimeResult(
        engine_version=FORMAL_COLOR_RUNTIME_VERSION,
        source_sha256=source_sha,
        source_format=source_format,
        width=int(image.shape[1]),
        height=int(image.shape[0]),
        source_size_bytes=source_size,
        output_path=materialized_path,
        output_sha256=output_sha,
        output_format=output_format,
        output_size_bytes=output_size,
        processing_time_ms=int(round((time.perf_counter() - started) * 1000)),
        d1_action=decision.d1_action.value,
        d3_status=audit.status,
        d3_final_action=final_action,
        result_action=final_action,
        output_selected=output_selected,
        acceptance_authority=audit.acceptance_authority.value,
        candidate_identity=audit.d2_candidate_identity,
        analysis={
            "D1_ACTION": decision.d1_action.value,
            "OBJECTIVE_DIAGNOSIS": objective_diagnosis.to_dict(),
            "PARAMETER_DECISION": parameter_decision.to_dict() if parameter_decision is not None else None,
            "PARAMETER_DECISION_OUTCOME": parameter_decision.outcome.value if parameter_decision is not None else "REFERENCE_MATCHING",
            "COLOR_STATUS": decision.color_status.value,
            "EXPOSURE_STATUS": decision.exposure_status.value,
            "D3_STATUS": audit.status,
            "D3_FINAL_ACTION": final_action,
            "D3_PASS_STATUS": dict(audit.pass_status),
            "D3_AUDIT_METRICS": dict(audit.audit_metrics),
            "QUALITY_EVIDENCE": dict(
                audit.audit_metrics.get("QUALITY_EVIDENCE") or {}
            ),
            "D3_NET_GAIN": audit.net_gain.value,
            "D3_BLOCKER": audit.blocker,
            **({"REFERENCE_MATCHING": parameters["reference_matching"],
                "REFERENCE_PROVENANCE": {
                    "reference_source_fingerprint": reference_decision.reference.source.encoded_sha256,
                    "reference_match_status": reference_decision.status,
                    "reference_decision_digest": parameters["reference_decision_digest"],
                }} if reference_decision is not None else {}),
        },
        before_metrics=before_metrics,
        after_metrics=after_metrics,
        detected_issues=detected_issues,
        improvements=improvements,
        review_points=review_points,
        applied_actions=applied_actions,
        parameters=parameters,
        output_metadata=output_metadata,
    )
    return result


__all__ = ["FORMAL_COLOR_RUNTIME_VERSION", "run_formal_color_runtime"]
