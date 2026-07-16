from __future__ import annotations

import copy
import unittest

from engine.image_compression.legacy_adapters import adapt_lossless_record, adapt_resize_record, adapt_upload_record
from engine.image_compression.statuses import CandidateDeliveryRole, DeliveryGateStatus, VisualReviewStatus


class LegacyEvidenceAdapterTests(unittest.TestCase):
    def test_input_is_not_modified_and_not_applicable_becomes_null(self) -> None:
        record = {
            "task_id": "legacy-lossless",
            "status": "TARGET_MET",
            "visual_review": "not_applicable",
            "candidate_path": "candidate.png",
            "legacy_metric": "not_applicable",
        }
        before = copy.deepcopy(record)
        result = adapt_lossless_record(record)
        self.assertEqual(record, before)
        self.assertIsNone(result.evidence_paths["legacy_record"]["legacy_metric"])
        self.assertNotEqual(result.visual_review_status, "not_applicable")

    def test_composite_visual_text_fails_closed(self) -> None:
        result = adapt_resize_record(
            {
                "task_id": "legacy-resize",
                "status": "TARGET_MET",
                "visual_review": "requires_human_review:text_and_logo",
                "candidate_path": "candidate.png",
            }
        )
        self.assertEqual(result.visual_review_status, VisualReviewStatus.PENDING)
        self.assertEqual(result.delivery_gate_status, DeliveryGateStatus.REVIEW_REQUIRED)
        self.assertFalse(result.delivery_eligible)
        self.assertEqual(result.candidate_delivery_role, CandidateDeliveryRole.EVIDENCE_ONLY)
        self.assertIn("LEGACY_VISUAL_TEXT_NOT_A_FORMAL_ENUM", result.warnings)

    def test_final_path_is_not_automatically_delivery_candidate(self) -> None:
        result = adapt_upload_record(
            {
                "task_id": "legacy-upload",
                "status": "TARGET_MET",
                "visual_review": "PENDING",
                "final_path": "final.png",
            }
        )
        self.assertFalse(result.delivery_eligible)
        self.assertEqual(result.candidate_delivery_role, CandidateDeliveryRole.EVIDENCE_ONLY)

    def test_real_alpha_d_failure_is_preserved(self) -> None:
        result = adapt_upload_record(
            {
                "task_id": "real_alpha__D",
                "status": "TARGET_MET",
                "visual_review": "PASS",
                "final_path": "real_alpha.png",
            }
        )
        self.assertEqual(result.visual_review_status, VisualReviewStatus.FAIL)
        self.assertEqual(result.delivery_gate_status, DeliveryGateStatus.CANNOT_MEET_SAFELY)
        self.assertFalse(result.delivery_eligible)
        self.assertEqual(result.candidate_delivery_role, CandidateDeliveryRole.EVIDENCE_ONLY)

    def test_final_path_pass_is_still_evidence_only(self) -> None:
        result = adapt_upload_record(
            {
                "task_id": "legacy-upload-pass",
                "status": "TARGET_MET",
                "visual_review": "PASS",
                "final_path": "final.png",
            }
        )
        self.assertFalse(result.delivery_eligible)
        self.assertEqual(result.candidate_delivery_role, CandidateDeliveryRole.EVIDENCE_ONLY)
        self.assertIn("LEGACY_FINAL_PATH_EVIDENCE_ONLY", result.warnings)

    def test_real_alpha_d_sample_id_is_preserved(self) -> None:
        result = adapt_upload_record(
            {
                "sample_id": "real_alpha__D",
                "status": "TARGET_MET",
                "visual_review": "PASS",
                "candidate_path": "candidate.png",
            }
        )
        self.assertEqual(result.visual_review_status, VisualReviewStatus.FAIL)

    def test_no_processing_uses_source_without_creating_copy(self) -> None:
        result = adapt_upload_record(
            {
                "task_id": "no-change",
                "status": "NO_PROCESSING_NEEDED",
                "visual_review": "NOT_REQUIRED_NO_CHANGE",
                "source_path": "source.png",
                "source_sha256": "abc",
                "source_dimensions": "10x20",
                "source_size_bytes": 100,
            }
        )
        self.assertFalse(result.output_created)
        self.assertEqual(result.output_path, "source.png")
        self.assertEqual(result.candidate_delivery_role, CandidateDeliveryRole.SOURCE_NO_PROCESSING)


if __name__ == "__main__":
    unittest.main()
