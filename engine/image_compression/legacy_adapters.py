from __future__ import annotations

import copy
from typing import Any, Mapping

from .common import apply_delivery_gate
from .contracts import ImageCompressionResult
from .statuses import CandidateDeliveryRole, DeliveryGateStatus, OperationMode, TechnicalStatus, VisualReviewStatus


def _normalise(value: Any) -> Any:
    if isinstance(value, str) and value.strip().lower() == "not_applicable":
        return None
    if isinstance(value, Mapping):
        return {str(key): _normalise(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalise(item) for item in value]
    return value


def _technical_status(record: Mapping[str, Any]) -> TechnicalStatus:
    raw = record.get("technical_status") or record.get("status")
    try:
        return TechnicalStatus(str(raw))
    except ValueError:
        return TechnicalStatus.CANNOT_MEET_SAFELY


def _visual_status(record: Mapping[str, Any], technical: TechnicalStatus) -> tuple[VisualReviewStatus, list[str]]:
    warnings: list[str] = []
    replay_ids = (
        record.get("replay_task_id"),
        record.get("task_id"),
        record.get("sample_id"),
        record.get("test_case_id"),
    )
    evidence_reference = str(record.get("evidence_reference") or "")
    if any(str(value or "") == "real_alpha__D" for value in replay_ids) or "real_alpha__D" in evidence_reference:
        return VisualReviewStatus.FAIL, warnings
    raw = record.get("visual_review_status") or record.get("visual_review") or record.get("review_status")
    if raw == "NOT_REQUIRED_NO_CHANGE" and technical is TechnicalStatus.NO_PROCESSING_NEEDED:
        return VisualReviewStatus.NOT_REQUIRED, warnings
    try:
        return VisualReviewStatus(str(raw)), warnings
    except ValueError:
        if technical in {TechnicalStatus.INVALID_REQUEST, TechnicalStatus.PROCESSING_FAILED, TechnicalStatus.CANNOT_MEET_SAFELY}:
            return VisualReviewStatus.NOT_AVAILABLE, warnings
        warnings.append("LEGACY_VISUAL_TEXT_NOT_A_FORMAL_ENUM")
        return VisualReviewStatus.PENDING, warnings


def _parse_dimensions(value: Any) -> tuple[dict[str, int] | None, bool]:
    if isinstance(value, dict) and all(isinstance(value.get(key), int) for key in ("width", "height")):
        return {"width": int(value["width"]), "height": int(value["height"])}, False
    if isinstance(value, str) and "x" in value.lower():
        try:
            width, height = (int(item.strip()) for item in value.lower().split("x", 1))
            if width > 0 and height > 0:
                return {"width": width, "height": height}, False
        except (TypeError, ValueError):
            pass
    return None, value is not None


def adapt_legacy_result(operation_mode: OperationMode | str, record: Mapping[str, Any]) -> ImageCompressionResult:
    """Read-only adapter. The complete normalised legacy record remains attached as evidence."""

    frozen = copy.deepcopy(dict(record))
    normalised = _normalise(frozen)
    mode = OperationMode(operation_mode)
    technical = _technical_status(normalised)
    visual, warnings = _visual_status(normalised, technical)
    source_dimensions = normalised.get("source_dimensions") or normalised.get("original_dimensions")
    output_dimensions = normalised.get("output_dimensions") or normalised.get("final_dimensions")
    source_dimensions, source_dimensions_unmapped = _parse_dimensions(source_dimensions)
    output_dimensions, output_dimensions_unmapped = _parse_dimensions(output_dimensions)
    source_path = normalised.get("source_path") or normalised.get("original_path")
    explicit_output_path = normalised.get("output_path") or normalised.get("candidate_path")
    final_path_only = not explicit_output_path and bool(normalised.get("final_path"))
    output_path = explicit_output_path or normalised.get("final_path")
    output_created = bool(output_path) and technical in {TechnicalStatus.TARGET_MET, TechnicalStatus.TARGET_MET_WITH_REENCODE}
    if technical is TechnicalStatus.NO_PROCESSING_NEEDED:
        output_path = source_path
        output_created = False
    result = ImageCompressionResult(
        task_id=str(normalised.get("task_id") or normalised.get("sample_id") or "legacy"),
        operation_mode=mode,
        run_id=normalised.get("run_id"),
        test_case_id=normalised.get("test_case_id") or normalised.get("sample_id"),
        technical_status=technical,
        visual_review_status=visual,
        source_path=source_path,
        source_sha256=normalised.get("source_sha256") or normalised.get("original_sha256"),
        source_format=normalised.get("source_format") or normalised.get("original_format"),
        source_dimensions=source_dimensions if isinstance(source_dimensions, dict) else None,
        source_size_bytes=normalised.get("source_size_bytes") or normalised.get("original_size_bytes"),
        output_created=output_created,
        output_path=output_path,
        output_sha256=normalised.get("output_sha256") or normalised.get("candidate_sha256") or normalised.get("final_sha256"),
        output_format=normalised.get("output_format") or normalised.get("source_format") or normalised.get("original_format"),
        output_dimensions=output_dimensions if isinstance(output_dimensions, dict) else None,
        output_size_bytes=normalised.get("output_size_bytes") or normalised.get("candidate_size_bytes") or normalised.get("final_size_bytes"),
        lossy=normalised.get("lossy"),
        reencoded=normalised.get("reencoded"),
        resized=normalised.get("resized"),
        processing_seconds=float(normalised.get("processing_seconds") or normalised.get("elapsed_seconds") or 0.0),
        warnings=list(normalised.get("warnings") or []) if isinstance(normalised.get("warnings"), list) else [],
        failure_code=normalised.get("failure_code") or normalised.get("rejection_reason"),
        failure_reason=normalised.get("failure_reason"),
        risk_reasons=list(normalised.get("risk_reasons") or normalised.get("delivery_risk_reasons") or []),
        evidence_paths={"legacy_record": normalised, "adapter": f"{mode.value}.v1"},
        validation_status="PASS" if technical not in {TechnicalStatus.INVALID_REQUEST, TechnicalStatus.PROCESSING_FAILED} else "FAIL",
        validation_failures=list(normalised.get("validation_failures") or []),
    )
    result.warnings.extend(warnings)
    if source_dimensions_unmapped or output_dimensions_unmapped:
        result.warnings.append("LEGACY_DIMENSIONS_UNMAPPABLE")
    if final_path_only:
        result.warnings.append("LEGACY_FINAL_PATH_EVIDENCE_ONLY")
    if technical is TechnicalStatus.NO_PROCESSING_NEEDED:
        result.output_sha256 = result.source_sha256
        result.output_format = result.source_format
        result.output_dimensions = result.source_dimensions
        result.output_size_bytes = result.source_size_bytes
        result.size_reduction_bytes = 0
        result.size_reduction_ratio = 0.0
        result.dimension_scale_ratio = 1.0
        result.lossy = False
        result.reencoded = False
        result.resized = False
    strict = mode is OperationMode.LOSSLESS_COMPRESSION and visual is VisualReviewStatus.NOT_REQUIRED
    result = apply_delivery_gate(result, strict_lossless_evidence=strict, evidence_candidate=output_created)
    # A legacy record that exposes only ``final_path`` has no proof that the
    # path is a fresh delivery candidate. Keep it as evidence even when the
    # legacy text says PASS; never promote it automatically.
    if final_path_only and result.output_created and result.delivery_eligible:
        result.delivery_eligible = False
        result.delivery_gate_status = DeliveryGateStatus.REVIEW_REQUIRED
        result.delivery_decision_reason = "Legacy final_path is evidence only until an explicit candidate path is confirmed."
        result.candidate_delivery_role = CandidateDeliveryRole.EVIDENCE_ONLY
    return result


def adapt_lossless_record(record: Mapping[str, Any]) -> ImageCompressionResult:
    return adapt_legacy_result(OperationMode.LOSSLESS_COMPRESSION, record)


def adapt_resize_record(record: Mapping[str, Any]) -> ImageCompressionResult:
    return adapt_legacy_result(OperationMode.RESIZE_REDUCTION, record)


def adapt_upload_record(record: Mapping[str, Any]) -> ImageCompressionResult:
    return adapt_legacy_result(OperationMode.UPLOAD_ADAPTATION, record)
