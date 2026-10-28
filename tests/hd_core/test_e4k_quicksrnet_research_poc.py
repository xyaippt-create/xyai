from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

import numpy as np
import torch

from tools.experiments import e4k_quicksrnet_research_poc as poc


class QuickSRNetResearchPocTests(unittest.TestCase):
    def setUp(self) -> None:
        torch.manual_seed(0)
        torch.use_deterministic_algorithms(True)
        torch.set_num_threads(1)

    def test_checkpoint_loads_strictly_and_doubles_shape(self) -> None:
        model, record = poc.load_model(poc.MODEL_PATH)
        output = model(torch.zeros((1, 3, 17, 19), dtype=torch.float32))
        self.assertEqual(tuple(output.shape), (1, 3, 34, 38))
        self.assertEqual(record["status"], "PASS_RESEARCH_ONLY")
        self.assertEqual(record["formal_product_eligibility"], "NO")

    def test_halo_tiling_matches_direct_inference(self) -> None:
        model = poc.QuickSRNetLarge().eval()
        source = np.random.default_rng(4).integers(0, 256, (65, 71, 3), dtype=np.uint8)
        tiled, record = poc.infer_tiled_x2(model, source, core=32, halo=16)
        tensor = torch.from_numpy(source.transpose(2, 0, 1).copy()).float().unsqueeze(0) / 255.0
        with torch.inference_mode():
            direct = model(tensor)[0].permute(1, 2, 0).numpy()
        direct_u8 = np.clip(np.rint(direct * 255.0), 0, 255).astype(np.uint8)
        self.assertTrue(np.array_equal(tiled, direct_u8))
        self.assertEqual(record["coverage_min"], 1)
        self.assertEqual(record["coverage_max"], 1)

    def test_bound_hard_protection_is_pixel_identical(self) -> None:
        height, width = 40, 52
        baseline = np.full((height, width, 3), 120, dtype=np.uint8)
        proposal = baseline.copy()
        proposal[:, :, 0] = 150
        hard = np.zeros((height, width), dtype=np.float32)
        hard[5:20, 7:30] = 1.0
        masks = {
            "activation": np.full((height, width), poc.legacy.MODEL_BLEND, dtype=np.float32),
            "hard_protect": hard,
            "manual_protect": hard.copy(),
            "text_hard": hard.copy(),
            "flat": np.zeros((height, width), dtype=np.float32),
            "photo_hard": np.ones((height, width), dtype=np.float32),
        }
        candidate, _, _ = poc.build_candidate(baseline, proposal, masks, poc.VARIANTS[0])
        self.assertTrue(np.array_equal(candidate[5:20, 7:30], baseline[5:20, 7:30]))

    def test_structure_gate_stays_pending_until_complete_coverage_is_proven(self) -> None:
        safety = {
            "status": "PASS",
            "text_protection": {
                "status": "PENDING_COVERAGE_REVIEW",
                "all_text_logo_icon_coverage": "NOT_PROVEN",
            },
        }
        annotated = poc.annotate_structure_safety_gate(safety)
        self.assertEqual(annotated["structure_safety_gate"], "PENDING_COVERAGE_REVIEW")
        self.assertNotIn("structure_safety_gate", safety)

    def test_structure_gate_pass_requires_both_text_status_and_coverage_proof(self) -> None:
        safety = {
            "status": "PASS",
            "text_protection": {
                "status": "PASS",
                "all_text_logo_icon_coverage": "PROVEN",
            },
        }
        self.assertEqual(poc.derive_structure_safety_gate(safety), "PASS")
        safety["status"] = "FAIL"
        self.assertEqual(poc.derive_structure_safety_gate(safety), "BLOCKED_AUTOMATED_SAFETY")

    def test_bound_semantic_coverage_is_complete_and_fail_closed(self) -> None:
        target_size = (1000, 564)
        source_size = (1668, 941)
        mask, regions = poc.build_bound_coverage_mask(target_size, source_size)
        annotation = {
            "annotation_status": "COMPLETE_FOR_ONE_BOUND_SAMPLE",
            "proof_scope": "ONE_BOUND_POSTER_ONLY",
            "generalization": "NOT_CLAIMED",
            "automatic_content_recognition": "NOT_PROVEN",
            "visible_logo_count": 0,
            "logo_inventory_status": "NONE_VISIBLE_IN_BOUND_SAMPLE_CODEX_SCREEN",
            "coverage_region_count": len(regions),
            "semantic_item_count": sum(len(item["content_items"]) for item in regions),
            "regions": regions,
        }
        baseline = np.zeros((target_size[1], target_size[0], 3), dtype=np.uint8)
        candidate = baseline.copy()
        verified = poc.verify_bound_semantic_coverage(baseline, candidate, mask, annotation)
        self.assertEqual(verified["status"], "PASS")
        self.assertEqual(verified["all_text_logo_icon_coverage"], "PROVEN")
        self.assertEqual(verified["coverage_region_count"], len(poc.BOUND_SEMANTIC_COVERAGE))
        broken = mask.copy()
        x0, y0, _, _ = regions[0]["target_box"]
        broken[y0, x0] = 0.0
        with self.assertRaisesRegex(poc.PocError, "BOUND_SEMANTIC_COVERAGE_FAILED"):
            poc.verify_bound_semantic_coverage(baseline, candidate, broken, annotation)

    def test_execution_record_rejects_uncontrolled_route_decision(self) -> None:
        record = {
            "technical_status": "PASS_AUTOMATED_SCREENS",
            "structure_safety_gate": "PENDING_COVERAGE_REVIEW",
            "visual_gain_status": "NOT_RUN",
            "route_decision": "BLOCKED_PENDING_TEXT_LOGO_ICON_COVERAGE_REVIEW",
        }
        with self.assertRaisesRegex(poc.PocError, "INVALID_ROUTE_DECISION"):
            poc.validate_execution_matrix_record(record)

    def test_execution_record_requires_structure_pass_before_visual_review(self) -> None:
        record = {
            "technical_status": "PASS_AUTOMATED_SCREENS",
            "structure_safety_gate": "PENDING_COVERAGE_REVIEW",
            "visual_gain_status": "PENDING_HUMAN_REVIEW",
            "route_decision": "PENDING_HUMAN_REVIEW",
        }
        with self.assertRaisesRegex(poc.PocError, "HUMAN_VISUAL_REVIEW_PRECONDITION_NOT_MET"):
            poc.validate_execution_matrix_record(record)
        record.update(
            {
                "visual_gain_status": "NOT_RUN",
                "route_decision": "REJECTED_UNSAFE",
            }
        )
        poc.validate_execution_matrix_record(record)

    def test_run_refuses_existing_output_root_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(poc.PocError, "OUTPUT_ROOT_ALREADY_EXISTS"):
                poc.run(output_root=root)

    def test_generated_manifest_and_delivery_are_integral(self) -> None:
        manifest_path = poc.OUTPUT_ROOT / "manifest.json"
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["decision"]["status"], "REVIEW_PACKAGE_READY")
        self.assertEqual(manifest["decision"]["stage_result"], "REVIEW_PACKAGE_READY")
        self.assertEqual(
            manifest["decision"]["final_status"],
            "PENDING_HUMAN_VISUAL_REVIEW",
        )
        self.assertEqual(manifest["decision"]["freeze_status"], "NOT_READY")
        self.assertEqual(manifest["decision"]["self_audit"], "PASS")
        self.assertEqual(manifest["decision"]["real_4k_quality_gain"], "NOT_PROVEN")
        self.assertEqual(
            manifest["decision"]["ai_safe_gain_status"],
            "PENDING_HUMAN_REVIEW",
        )
        self.assertEqual(manifest["model_eligibility"]["formal_product_eligibility"], "NO")
        self.assertEqual(
            manifest["model_eligibility"]["license_source"],
            "https://github.com/quic/aimet-model-zoo/blob/develop/LICENSE.md",
        )
        self.assertEqual(manifest["safety"]["masked_region_identity"]["status"], "PASS")
        self.assertEqual(manifest["safety"]["structure_safety_gate"], "PASS")
        self.assertEqual(manifest["all_text_logo_icon_coverage"], "PROVEN")
        self.assertEqual(manifest["structure_coverage"]["status"], "PASS")
        self.assertEqual(
            manifest["structure_coverage"]["coverage_region_count"],
            len(poc.BOUND_SEMANTIC_COVERAGE),
        )
        for region in manifest["structure_coverage"]["regions"]:
            self.assertEqual(region["status"], "PASS")
            self.assertEqual(region["hard_mask_coverage_fraction"], 1.0)
            self.assertEqual(region["candidate_vs_lanczos_rgb_max_abs_delta"], 0)
        self.assertEqual(
            manifest["execution_matrix"][0]["structure_safety_gate"],
            "PASS",
        )
        self.assertEqual(
            manifest["execution_matrix"][0]["visual_gain_status"],
            "PENDING_HUMAN_REVIEW",
        )
        self.assertEqual(
            manifest["execution_matrix"][0]["route_decision"],
            "PENDING_HUMAN_REVIEW",
        )
        self.assertEqual(
            manifest["execution_matrix"][0]["rejection_reason"],
            "NOT_APPLICABLE_ROUTE_NOT_REJECTED",
        )
        poc.validate_execution_matrix_record(manifest["execution_matrix"][0])
        self.assertEqual(
            manifest["decision"]["visible_clarity_gain"],
            "PENDING_HUMAN_REVIEW",
        )
        self.assertEqual(
            manifest["decision"]["human_visual_review"],
            "PENDING",
        )
        self.assertTrue(manifest["encoding"]["size_budget_pass"])
        self.assertLessEqual(manifest["encoding"]["bytes"], poc.MAX_OUTPUT_BYTES)
        self.assertEqual(manifest["candidate_delivery_identity"]["status"], "PIXEL_EXACT")
        for record in manifest["files"].values():
            path = poc.OUTPUT_ROOT / record["path"]
            self.assertTrue(path.is_file(), path)
            self.assertEqual(path.stat().st_size, record["bytes"])
            self.assertEqual(poc.legacy.sha256_file(path), record["sha256"])


if __name__ == "__main__":
    unittest.main()
