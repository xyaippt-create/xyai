from __future__ import annotations

import time
from typing import Any, Mapping

from . import lossless, resize, upload_adaptation
from .common import CompressionRuntimeError, FaultInjector, apply_delivery_gate, runtime_failure_result
from .contracts import ImageCompressionResult, TaskValidationResult, validate_task
from .statuses import OperationMode, TechnicalStatus, VisualReviewStatus, evaluate_delivery_gate


def _invalid_request_result(payload: Mapping[str, Any], validation: TaskValidationResult) -> ImageCompressionResult:
    result = ImageCompressionResult(
        task_id=str(payload.get("task_id") or ""),
        operation_mode=str(payload.get("operation_mode") or ""),
        run_id=payload.get("run_id") if isinstance(payload.get("run_id"), str) else None,
        test_case_id=payload.get("test_case_id") if isinstance(payload.get("test_case_id"), str) else None,
        diagnostic_session_id=payload.get("diagnostic_session_id") if isinstance(payload.get("diagnostic_session_id"), str) else None,
        issue_report_id=payload.get("issue_report_id") if isinstance(payload.get("issue_report_id"), str) else None,
        technical_status=TechnicalStatus.INVALID_REQUEST,
        visual_review_status=VisualReviewStatus.NOT_AVAILABLE,
        source_path=payload.get("source_path") if isinstance(payload.get("source_path"), str) else None,
        failure_code=validation.primary_failure_code,
        failure_reason=validation.validation_failures[0].reason if validation.validation_failures else "Invalid request.",
        validation_status="FAIL",
        validation_failures=[item.to_dict() for item in validation.validation_failures],
    )
    return apply_delivery_gate(result, evidence_candidate=False)


def process_image_compression(
    request: Mapping[str, Any],
    *,
    visual_review_status: VisualReviewStatus | str | None = None,
    fault_injector: FaultInjector | None = None,
    check_resources: bool = True,
) -> ImageCompressionResult:
    started = time.perf_counter()
    validation = validate_task(request, check_resources=check_resources)
    if not validation.valid or validation.task is None:
        return _invalid_request_result(request, validation)
    task = validation.task
    try:
        if task.operation_mode is OperationMode.LOSSLESS_COMPRESSION:
            return lossless.process_lossless(task, fault_injector=fault_injector)
        if task.operation_mode is OperationMode.RESIZE_REDUCTION:
            return resize.process_resize(task, visual_review_status=visual_review_status, fault_injector=fault_injector)
        if task.operation_mode is OperationMode.UPLOAD_ADAPTATION:
            return upload_adaptation.process_upload_adaptation(
                task,
                visual_review_status=visual_review_status,
                fault_injector=fault_injector,
            )
        raise CompressionRuntimeError("OPERATION_MODE_INVALID", "The selected operation mode is not routable.")
    except CompressionRuntimeError as exc:
        return runtime_failure_result(task, None, exc, started)
    except Exception as exc:
        error = CompressionRuntimeError("PROCESSING_EXCEPTION", f"Unhandled processing exception: {exc}")
        return runtime_failure_result(task, None, error, started)


def evaluate_fixture_case(case: Mapping[str, Any]) -> dict[str, Any]:
    """Execute the frozen request-validation and pure-decision portions of one fixture case."""

    request = case.get("request") or {}
    validation = validate_task(request, check_resources=False)
    expected_validation = case["expected_validation"]
    request_contract = "VALID" if validation.valid else "INVALID"
    validation_code = validation.primary_failure_code if not validation.valid else None
    expected_request_code = expected_validation.get("failure_code") if expected_validation["request_contract"] == "INVALID" else None
    technical = TechnicalStatus(case["expected_technical_status"])
    visual = VisualReviewStatus(case["expected_visual_review_status"])
    strict_lossless = (
        case.get("operation_mode") == OperationMode.LOSSLESS_COMPRESSION.value
        and visual is VisualReviewStatus.NOT_REQUIRED
    )
    decision = evaluate_delivery_gate(
        technical,
        visual,
        strict_lossless_evidence=strict_lossless,
        evidence_candidate=bool(case["expected_output_created"]),
    )
    checks = {
        "request_contract": request_contract == expected_validation["request_contract"],
        "request_failure_code": validation_code == expected_request_code,
        "delivery_gate_status": decision.status.value == case["expected_delivery_gate_status"],
        "delivery_eligible": decision.eligible is bool(case["expected_delivery_eligible"]),
        "case_level_test_setup": "test_setup" not in request,
    }
    if case.get("case_id") == "S3C-021-save-permission-failed":
        setup = case.get("test_setup") or {}
        checks.update(
            runtime_failure_code=expected_validation.get("failure_code") == "OUTPUT_WRITE_PERMISSION_DENIED",
            permission_fault_stage=(setup.get("fault_injection") or {}).get("stage") == "ATOMIC_WRITE",
            directory_precheck=setup.get("output_directory_precheck") == "PASS",
        )
    return {
        "case_id": case.get("case_id"),
        "passed": all(checks.values()),
        "checks": checks,
        "validation": validation.to_dict(),
        "delivery_decision": {
            "delivery_gate_status": decision.status.value,
            "delivery_eligible": decision.eligible,
            "candidate_delivery_role": decision.candidate_role.value,
        },
    }


route = process_image_compression
