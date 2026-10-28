from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from tools.experiments import e4k_04_hybrid_poster_poc as poc


class HybridPosterPocContractTest(unittest.TestCase):
    def test_target_size_matches_bound_sample(self) -> None:
        self.assertEqual(poc.target_size((1672, 941)), (3840, 2161))

    def test_tile_positions_cover_axis_without_gaps(self) -> None:
        positions = poc.tile_positions(1672)
        self.assertEqual(positions[0], 0)
        self.assertEqual(positions[-1], 1672 - poc.MODEL_INPUT_EDGE)
        self.assertTrue(all(b - a <= poc.MODEL_INPUT_EDGE for a, b in zip(positions, positions[1:])))

    def test_protected_pixels_are_byte_exact(self) -> None:
        baseline = np.full((16, 24, 3), 128, dtype=np.uint8)
        proposal = np.full((16, 24), 150, dtype=np.float32)
        hard = np.zeros((16, 24), dtype=np.float32)
        hard[3:10, 5:14] = 1.0
        activation = np.full((16, 24), poc.MODEL_BLEND, dtype=np.float32)
        masks = {"activation": activation, "hard_protect": hard}
        candidate, record = poc.build_candidate(baseline, proposal, masks)
        self.assertTrue(np.array_equal(candidate[3:10, 5:14], baseline[3:10, 5:14]))
        self.assertLessEqual(record["applied_integer_delta"]["max"], poc.APPLIED_LUMA_LIMIT)

    def test_lossless_webp_budget_encoder_is_pixel_exact(self) -> None:
        rng = np.random.default_rng(7)
        pixels = rng.integers(0, 256, (48, 64, 3), dtype=np.uint8)
        image = Image.fromarray(pixels, "RGB")
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "delivery.webp"
            record = poc.encode_delivery(image, output)
            with Image.open(output) as decoded:
                actual = np.asarray(decoded.convert("RGB"), dtype=np.uint8)
        self.assertTrue(record["size_budget_pass"])
        self.assertTrue(record["lossless"])
        self.assertTrue(np.array_equal(actual, pixels))

    def test_model_allowlist_hash_matches_download(self) -> None:
        self.assertTrue(poc.MODEL_PATH.is_file())
        self.assertEqual(poc.sha256_file(poc.MODEL_PATH), poc.EXPECTED_MODEL_SHA256)

    def test_closure_evidence_is_truth_scoped(self) -> None:
        closure = poc.closure_evidence()
        self.assertEqual(closure["status"], "PASS")
        self.assertEqual(closure["user_visible_clarity_verdict"], "BELOW_EXPECTATION")
        self.assertEqual(closure["codex_visual_screen"], "COMPLETED")
        self.assertEqual(closure["independent_human_safety_review"], "PENDING")
        self.assertEqual(closure["masked_region_identity"], "PASS")
        self.assertEqual(closure["all_text_logo_icon_coverage"], "NOT_PROVEN")
        self.assertEqual(closure["content_region_method"], "MANUAL_BOUND_SAMPLE_ANNOTATION")
        self.assertEqual(closure["automatic_content_recognition"], "NOT_PROVEN")
        self.assertEqual(closure["generalization"], "NOT_CLAIMED")
        self.assertEqual(closure["model_id"], "ONNX_MODEL_ZOO_ESPCN_X3_OPSET10")
        self.assertEqual(closure["model_scale"], 3)
        self.assertEqual(closure["current_model_decision"], "NOT_PROVEN_ON_BOUND_SAMPLE")
        self.assertEqual(closure["real_4k_quality_gain"], "NOT_PROVEN")
        self.assertEqual(closure["continue_strength_tuning"], "NO")
        self.assertEqual(closure["ready_for_formal_candidate"], "NO")
        self.assertEqual(closure["full_frozen_tree_pre_post_proof"], "NOT_AVAILABLE")

    def test_report_generator_preserves_corrected_evidence_scope(self) -> None:
        model = {
            "status": "PASS",
            "model_id": poc.MODEL_ID,
            "model_version": poc.MODEL_VERSION,
            "model_sha256": poc.EXPECTED_MODEL_SHA256,
            "model_bytes": 1,
            "license": poc.MODEL_LICENSE,
            "model_page_url": poc.MODEL_PAGE_URL,
            "download_url": poc.MODEL_DOWNLOAD_URL,
            "license_url": poc.MODEL_LICENSE_URL,
            "runtime_backend": "TEST_ONLY_NO_INFERENCE",
            "runtime_version": "test",
            "input": {"shape": [1, 1, 224, 224]},
            "output": {"shape": [1, 1, 672, 672]},
            "model_card_contract_note": "test fixture",
        }
        manifest = {
            "model_eligibility": model,
            "decision": {
                "status": "NOT_PROVEN",
                "visible_clarity_gain": "BELOW_EXPECTATION",
                "real_4k_quality_gain": "NOT_PROVEN",
                "ready_for_formal_candidate": "NO",
            },
            "encoding": {"size_budget_pass": True, "bytes": 1, "max_output_bytes": 2},
            "safety": {
                "text_protection": {"status": "PENDING_COVERAGE_REVIEW"},
                "color_lock": {"status": "PASS"},
                "halo_ringing": {"status": "PASS"},
                "false_texture": {"status": "SCREEN_PASS"},
            },
            "closure": poc.closure_evidence(),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            poc.write_reports(root, manifest)
            report = (root / "REPORT.md").read_text(encoding="utf-8")
        self.assertIn("USER_VISIBLE_CLARITY_VERDICT: BELOW_EXPECTATION", report)
        self.assertIn("INDEPENDENT_HUMAN_SAFETY_REVIEW: PENDING", report)
        self.assertIn("ALL_TEXT_LOGO_ICON_COVERAGE: NOT_PROVEN", report)
        self.assertIn("FULL_FROZEN_TREE_PRE_POST_PROOF: NOT_AVAILABLE", report)
        self.assertNotIn("HUMAN_VISUAL_REVIEW: COMPLETE", report)
        self.assertNotIn("FROZEN_EVIDENCE_CHANGED", report)
        self.assertNotIn("TEXT_PROTECTION: PASS", report)


if __name__ == "__main__":
    unittest.main()
