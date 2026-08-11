from __future__ import annotations

import json
import unittest
from pathlib import Path

from engine.image_processing_routing import (
    FOUR_K_V1_MODE,
    FOUR_K_V1_OUTPUT_PROFILE,
    FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY,
    FOUR_K_V1_ROUTE,
    FOUR_K_V1_TARGET_LONG_EDGE,
    get_4k_v1_contract,
    plan_4k_v1_dimensions,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FourKV1ContractTests(unittest.TestCase):
    def test_route_and_capability_are_unique_and_truthful(self):
        contract = get_4k_v1_contract()

        self.assertEqual(FOUR_K_V1_ROUTE, "PILLOW_LANCZOS_SAFE_RESIZE")
        self.assertEqual(contract["route"], FOUR_K_V1_ROUTE)
        self.assertEqual(contract["mode"], FOUR_K_V1_MODE)
        self.assertEqual(contract["output_profile"], FOUR_K_V1_OUTPUT_PROFILE)
        self.assertEqual(
            contract["quality_capability_boundary"],
            FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY,
        )
        self.assertEqual(
            contract["frozen_evidence"]["route_b_product_adoption"],
            "NO",
        )
        self.assertNotIn("candidate_routes", contract)
        self.assertNotIn(
            "QUALITY_GAIN_PROVEN",
            contract["quality_semantics"]["allowed_conclusions"],
        )

    def test_dimension_policy_matches_frozen_stage1_standard(self):
        standard = json.loads(
            (
                PROJECT_ROOT
                / "artifacts"
                / "4k_stage1_baseline"
                / "4k_standard_v1.json"
            ).read_text(encoding="utf-8")
        )
        contract = get_4k_v1_contract()

        self.assertEqual(standard["target_long_edge"], FOUR_K_V1_TARGET_LONG_EDGE)
        self.assertEqual(
            standard["aspect_ratio_policy"],
            contract["dimensions"]["aspect_ratio_policy"],
        )
        self.assertEqual(
            standard["rounding_policy"],
            contract["dimensions"]["rounding_policy"],
        )
        self.assertEqual(
            standard["already_4k_policy"],
            contract["dimensions"]["source_long_edge_ge_3840"],
        )
        self.assertEqual(standard["source_policy"], contract["source"]["policy"])
        self.assertEqual(standard["crop_policy"], contract["dimensions"]["crop_policy"])
        self.assertEqual(standard["stretch_policy"], contract["dimensions"]["stretch_policy"])
        self.assertEqual(standard["padding_policy"], contract["dimensions"]["padding_policy"])

    def test_frozen_baseline_and_negative_poc_decision_are_bound(self):
        contract = get_4k_v1_contract()
        selection = json.loads(
            (
                PROJECT_ROOT
                / "artifacts"
                / "4k_stage1_baseline"
                / "results"
                / "baseline_selection.json"
            ).read_text(encoding="utf-8")
        )
        closure = (
            PROJECT_ROOT
            / "artifacts"
            / "4k_stage2_ai_poc"
            / "4K_STAGE_2_POC_VALUE_NOT_PROVEN_CLOSURE_REPORT.md"
        ).read_text(encoding="utf-8")

        self.assertEqual(selection["status"], "FROZEN")
        self.assertEqual(selection["selected_method"], "pillow_lanczos")
        self.assertIn("CURRENT_ROUTE_B_PRODUCT_ADOPTION: NO", closure)
        self.assertIn("AI_SAFE_GAIN_STATUS: NOT_PROVEN", closure)
        for relative_path in contract["frozen_evidence"].values():
            if relative_path == "NO":
                continue
            self.assertTrue((PROJECT_ROOT / relative_path).is_file(), relative_path)

    def test_dimensions_cover_landscape_portrait_square_and_already_4k(self):
        cases = {
            (1600, 900): ("READY", (3840, 2160)),
            (900, 1600): ("READY", (2160, 3840)),
            (1000, 1000): ("READY", (3840, 3840)),
            (1000, 700): ("READY", (3840, 2688)),
            (3840, 2160): ("NO_PROCESSING_NEEDED", (3840, 2160)),
            (2160, 4000): ("NO_PROCESSING_NEEDED", (2160, 4000)),
        }

        for source, (status, target) in cases.items():
            with self.subTest(source=source):
                plan = plan_4k_v1_dimensions(*source)
                self.assertEqual(plan["preflight_status"], status)
                self.assertEqual((plan["target_width"], plan["target_height"]), target)

    def test_invalid_dimensions_are_blocked(self):
        for source in ((0, 1), (1, 0), (-1, 4), (True, 4), (4, False)):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "INVALID_SOURCE_DIMENSIONS"):
                    plan_4k_v1_dimensions(*source)

    def test_single_image_loop_fields_cover_next_stage(self):
        contract = get_4k_v1_contract()
        fields = contract["single_image_loop_fields"]

        self.assertEqual(
            contract["request"]["fixed_parameters"],
            {
                "mode": "4k_v1",
                "output_profile": "delivery_4k_v1",
                "output_format": "png",
            },
        )
        self.assertTrue(
            {
                "task_id",
                "task_status",
                "task_progress",
                "streamEndpoint",
                "originalUrl",
            }.issubset(fields["upload_response"])
        )
        self.assertTrue(
            {
                "input_width",
                "input_height",
                "output_width",
                "output_height",
                "final_output_url",
                "quality_conclusion",
            }.issubset(fields["task"])
        )
        self.assertIn("final_output_url", fields["comparison"])
        self.assertIn("quality_capability_boundary", fields["report"])
        self.assertIn("output_directory_token", fields["open_result"])

    def test_contract_callers_cannot_mutate_the_authority(self):
        first = get_4k_v1_contract()
        first["route"] = "MUTATED"
        first["dimensions"]["target_long_edge"] = 1

        second = get_4k_v1_contract()
        self.assertEqual(second["route"], FOUR_K_V1_ROUTE)
        self.assertEqual(
            second["dimensions"]["target_long_edge"],
            FOUR_K_V1_TARGET_LONG_EDGE,
        )


if __name__ == "__main__":
    unittest.main()
