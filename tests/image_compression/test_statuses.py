from __future__ import annotations

import itertools
import unittest

from engine.image_compression.statuses import (
    CandidateDeliveryRole,
    DeliveryGateStatus,
    STATUS_REGISTRY,
    TechnicalStatus,
    VisualReviewStatus,
    evaluate_delivery_gate,
)


class StatusTests(unittest.TestCase):
    def test_enum_registry_counts_are_frozen(self) -> None:
        self.assertEqual([len(STATUS_REGISTRY[name]) for name in STATUS_REGISTRY], [3, 6, 6, 4, 4])

    def test_full_status_cross_product_is_decidable(self) -> None:
        for technical, visual in itertools.product(TechnicalStatus, VisualReviewStatus):
            with self.subTest(technical=technical, visual=visual):
                decision = evaluate_delivery_gate(technical, visual)
                self.assertIsInstance(decision.status, DeliveryGateStatus)
                self.assertIsInstance(decision.eligible, bool)

    def test_frozen_truth_table(self) -> None:
        rows = (
            (TechnicalStatus.INVALID_REQUEST, VisualReviewStatus.NOT_AVAILABLE, False, False, DeliveryGateStatus.CANNOT_MEET_SAFELY, False, CandidateDeliveryRole.NONE),
            (TechnicalStatus.PROCESSING_FAILED, VisualReviewStatus.NOT_AVAILABLE, False, False, DeliveryGateStatus.CANNOT_MEET_SAFELY, False, CandidateDeliveryRole.NONE),
            (TechnicalStatus.CANNOT_MEET_SAFELY, VisualReviewStatus.NOT_AVAILABLE, False, False, DeliveryGateStatus.CANNOT_MEET_SAFELY, False, CandidateDeliveryRole.NONE),
            (TechnicalStatus.NO_PROCESSING_NEEDED, VisualReviewStatus.NOT_REQUIRED, False, False, DeliveryGateStatus.DELIVERY_READY, True, CandidateDeliveryRole.SOURCE_NO_PROCESSING),
            (TechnicalStatus.TARGET_MET, VisualReviewStatus.NOT_REQUIRED, True, True, DeliveryGateStatus.DELIVERY_READY, True, CandidateDeliveryRole.DELIVERY_CANDIDATE),
            (TechnicalStatus.TARGET_MET, VisualReviewStatus.PENDING, False, True, DeliveryGateStatus.REVIEW_REQUIRED, False, CandidateDeliveryRole.EVIDENCE_ONLY),
            (TechnicalStatus.TARGET_MET, VisualReviewStatus.PASS, False, True, DeliveryGateStatus.DELIVERY_READY, True, CandidateDeliveryRole.DELIVERY_CANDIDATE),
            (TechnicalStatus.TARGET_MET, VisualReviewStatus.PASS_WITH_NOTES, False, True, DeliveryGateStatus.DELIVERY_READY_WITH_NOTES, True, CandidateDeliveryRole.DELIVERY_CANDIDATE),
            (TechnicalStatus.TARGET_MET, VisualReviewStatus.FAIL, False, True, DeliveryGateStatus.CANNOT_MEET_SAFELY, False, CandidateDeliveryRole.EVIDENCE_ONLY),
            (TechnicalStatus.TARGET_MET_WITH_REENCODE, VisualReviewStatus.NOT_AVAILABLE, False, True, DeliveryGateStatus.REVIEW_REQUIRED, False, CandidateDeliveryRole.EVIDENCE_ONLY),
        )
        for technical, visual, strict, evidence, status, eligible, role in rows:
            with self.subTest(technical=technical, visual=visual):
                decision = evaluate_delivery_gate(technical, visual, strict_lossless_evidence=strict, evidence_candidate=evidence)
                self.assertEqual((decision.status, decision.eligible, decision.candidate_role), (status, eligible, role))

    def test_technical_target_does_not_imply_delivery(self) -> None:
        decision = evaluate_delivery_gate(TechnicalStatus.TARGET_MET, VisualReviewStatus.PENDING)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.status, DeliveryGateStatus.REVIEW_REQUIRED)

    def test_unknown_state_fails_closed(self) -> None:
        decision = evaluate_delivery_gate("UNKNOWN", "UNKNOWN")
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.status, DeliveryGateStatus.REVIEW_REQUIRED)


if __name__ == "__main__":
    unittest.main()
