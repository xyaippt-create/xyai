from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class StableStringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class OperationMode(StableStringEnum):
    LOSSLESS_COMPRESSION = "LOSSLESS_COMPRESSION"
    RESIZE_REDUCTION = "RESIZE_REDUCTION"
    UPLOAD_ADAPTATION = "UPLOAD_ADAPTATION"


class TechnicalStatus(StableStringEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    NO_PROCESSING_NEEDED = "NO_PROCESSING_NEEDED"
    TARGET_MET = "TARGET_MET"
    TARGET_MET_WITH_REENCODE = "TARGET_MET_WITH_REENCODE"
    CANNOT_MEET_SAFELY = "CANNOT_MEET_SAFELY"
    PROCESSING_FAILED = "PROCESSING_FAILED"


class VisualReviewStatus(StableStringEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    PASS = "PASS"
    PASS_WITH_NOTES = "PASS_WITH_NOTES"
    FAIL = "FAIL"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class DeliveryGateStatus(StableStringEnum):
    DELIVERY_READY = "DELIVERY_READY"
    DELIVERY_READY_WITH_NOTES = "DELIVERY_READY_WITH_NOTES"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CANNOT_MEET_SAFELY = "CANNOT_MEET_SAFELY"


class CandidateDeliveryRole(StableStringEnum):
    SOURCE_NO_PROCESSING = "SOURCE_NO_PROCESSING"
    DELIVERY_CANDIDATE = "DELIVERY_CANDIDATE"
    EVIDENCE_ONLY = "EVIDENCE_ONLY"
    NONE = "NONE"


@dataclass(frozen=True)
class DeliveryDecision:
    status: DeliveryGateStatus
    eligible: bool
    reason: str
    candidate_role: CandidateDeliveryRole
    risk_reasons: tuple[str, ...] = ()


def _coerce_enum(value: object, enum_type: type[StableStringEnum]) -> StableStringEnum | None:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except (TypeError, ValueError):
        return None


def evaluate_delivery_gate(
    technical_status: TechnicalStatus | str,
    visual_review_status: VisualReviewStatus | str,
    *,
    strict_lossless_evidence: bool = False,
    evidence_candidate: bool = False,
    risk_reasons: Iterable[str] = (),
) -> DeliveryDecision:
    """Pure, fail-closed delivery decision. It never reads or writes image files."""

    technical = _coerce_enum(technical_status, TechnicalStatus)
    visual = _coerce_enum(visual_review_status, VisualReviewStatus)
    risks = tuple(sorted({str(item) for item in risk_reasons if str(item)}))

    if technical in {TechnicalStatus.INVALID_REQUEST, TechnicalStatus.PROCESSING_FAILED}:
        return DeliveryDecision(
            DeliveryGateStatus.CANNOT_MEET_SAFELY,
            False,
            "Request validation or processing failed; no delivery candidate is available.",
            CandidateDeliveryRole.NONE,
            risks,
        )
    if technical is TechnicalStatus.CANNOT_MEET_SAFELY:
        return DeliveryDecision(
            DeliveryGateStatus.CANNOT_MEET_SAFELY,
            False,
            "The selected capability cannot meet the request safely.",
            CandidateDeliveryRole.EVIDENCE_ONLY if evidence_candidate else CandidateDeliveryRole.NONE,
            risks,
        )
    if technical is TechnicalStatus.NO_PROCESSING_NEEDED:
        if visual is VisualReviewStatus.NOT_REQUIRED:
            return DeliveryDecision(
                DeliveryGateStatus.DELIVERY_READY,
                True,
                "The source already meets the request and no copy was created.",
                CandidateDeliveryRole.SOURCE_NO_PROCESSING,
                risks,
            )
        return DeliveryDecision(
            DeliveryGateStatus.REVIEW_REQUIRED,
            False,
            "No-processing evidence conflicts with the visual status.",
            CandidateDeliveryRole.SOURCE_NO_PROCESSING,
            risks,
        )

    processed = technical in {TechnicalStatus.TARGET_MET, TechnicalStatus.TARGET_MET_WITH_REENCODE}
    if processed and visual is VisualReviewStatus.FAIL:
        return DeliveryDecision(
            DeliveryGateStatus.CANNOT_MEET_SAFELY,
            False,
            "Visual review failed; the candidate is evidence only.",
            CandidateDeliveryRole.EVIDENCE_ONLY,
            risks,
        )
    if processed and visual is VisualReviewStatus.PASS:
        return DeliveryDecision(
            DeliveryGateStatus.DELIVERY_READY,
            True,
            "Technical checks and visual review passed.",
            CandidateDeliveryRole.DELIVERY_CANDIDATE,
            risks,
        )
    if processed and visual is VisualReviewStatus.PASS_WITH_NOTES:
        return DeliveryDecision(
            DeliveryGateStatus.DELIVERY_READY_WITH_NOTES,
            True,
            "Technical checks passed and visual review passed with notes.",
            CandidateDeliveryRole.DELIVERY_CANDIDATE,
            risks,
        )
    if processed and visual is VisualReviewStatus.PENDING:
        return DeliveryDecision(
            DeliveryGateStatus.REVIEW_REQUIRED,
            False,
            "A changed image requires visual review before delivery.",
            CandidateDeliveryRole.EVIDENCE_ONLY,
            risks,
        )
    if processed and visual is VisualReviewStatus.NOT_REQUIRED and strict_lossless_evidence:
        return DeliveryDecision(
            DeliveryGateStatus.DELIVERY_READY,
            True,
            "Strict lossless hard evidence is complete; visual review is not required.",
            CandidateDeliveryRole.DELIVERY_CANDIDATE,
            risks,
        )
    if processed:
        return DeliveryDecision(
            DeliveryGateStatus.REVIEW_REQUIRED,
            False,
            "Visual evidence is unavailable, conflicting, or insufficient.",
            CandidateDeliveryRole.EVIDENCE_ONLY,
            risks,
        )
    return DeliveryDecision(
        DeliveryGateStatus.REVIEW_REQUIRED,
        False,
        "Unknown or conflicting status evidence; delivery fails closed.",
        CandidateDeliveryRole.EVIDENCE_ONLY if evidence_candidate else CandidateDeliveryRole.NONE,
        risks,
    )


STATUS_REGISTRY = {
    "operation_mode": tuple(item.value for item in OperationMode),
    "technical_status": tuple(item.value for item in TechnicalStatus),
    "visual_review_status": tuple(item.value for item in VisualReviewStatus),
    "delivery_gate_status": tuple(item.value for item in DeliveryGateStatus),
    "candidate_delivery_role": tuple(item.value for item in CandidateDeliveryRole),
}
