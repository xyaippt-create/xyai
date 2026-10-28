from __future__ import annotations

import copy
import json
import math
import unittest

from tools.experiments.e4k_04_bounded_restoration_core import protected_scope_state
from tools.experiments.e4k_04_source_recovery_v3 import (
    E1_MANIFEST,
    MINIMUM_REAL_HOLDOUT_CASES,
    OUTPUT_ROOT,
    _blur_case,
    build_feasibility,
    build_target_selection,
    validate_artifact,
)


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class SourceRecoveryV3FeasibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = _read_json(E1_MANIFEST)
        cls.feasibility = _read_json(
            OUTPUT_ROOT / "feasibility" / "e1_target_family_feasibility.json"
        )
        cls.selection = _read_json(
            OUTPUT_ROOT
            / "target_family_selection"
            / "target_family_selection_v3.json"
        )
        cls.summary = _read_json(OUTPUT_ROOT / "summary.json")
        cls.families = {
            row["family"]: row for row in cls.feasibility["families"]
        }

    def test_v3_feasibility_uses_real_e1_facts(self) -> None:
        recomputed = build_feasibility(self.manifest)
        self.assertEqual(recomputed, self.feasibility)
        self.assertEqual(self.feasibility["e1_case_count"], 16)
        self.assertEqual(
            self.families["BLUR"]["case_ids"],
            ["E1C006"],
        )
        self.assertEqual(
            self.families["MULTI_RESIZE"]["case_ids"],
            ["E1C010"],
        )
        self.assertEqual(self.families["BLUR_MULTI_RESIZE"]["case_ids"], [])

    def test_family_detection_uses_metadata_not_case_name(self) -> None:
        misleading = copy.deepcopy(self.manifest["cases"][0])
        misleading["case_id"] = "BLUR_IN_NAME_ONLY"
        misleading["degradation_type"] = "NONE"
        misleading["degradation_params"] = {"blur_radius": 1.2}
        self.assertFalse(_blur_case(misleading))

    def test_target_family_evidence_is_complete(self) -> None:
        required = {
            "baseline_error_headroom",
            "source_degradation_strength",
            "recoverable_structure_evidence",
            "text_structure_risk",
            "color_risk",
            "alpha_risk",
            "operator_applicability",
            "commercial_safety_risk",
        }
        for row in self.feasibility["families"]:
            self.assertTrue(required.issubset(row), row["family"])
        for family in ("BLUR", "MULTI_RESIZE"):
            values = self.families[family]["baseline_error_headroom"][
                "rgb_mae_by_case"
            ].values()
            self.assertTrue(values)
            self.assertTrue(all(math.isfinite(value) for value in values))

    def test_insufficient_holdout_stops_v3(self) -> None:
        counts = {
            family: (
                row["valid_case_count"],
                row["gt_available_count"],
                row["real_holdout_count"],
            )
            for family, row in self.families.items()
        }
        self.assertEqual(counts["BLUR"], (1, 1, 1))
        self.assertEqual(counts["MULTI_RESIZE"], (1, 1, 1))
        self.assertEqual(counts["BLUR_MULTI_RESIZE"], (0, 0, 0))
        self.assertTrue(
            all(value[2] < MINIMUM_REAL_HOLDOUT_CASES for value in counts.values())
        )
        self.assertEqual(
            self.feasibility["status"],
            "INSUFFICIENT_REAL_EVALUATION_EVIDENCE",
        )
        self.assertEqual(self.summary["stop_v3_operator"], "YES")

    def test_holdout_not_used_for_tuning(self) -> None:
        self.assertFalse(self.feasibility["e1_gt_pixels_read_for_parameter_tuning"])
        self.assertFalse(self.feasibility["holdout_used_for_tuning"])
        self.assertFalse(self.feasibility["synthetic_holdout_created"])
        self.assertFalse(self.summary["holdout_used_for_tuning"])
        self.assertEqual(
            self.summary["calibration_set"],
            "NOT_CREATED_FEASIBILITY_GATE_STOP",
        )

    def test_target_selection_remains_unresolved_without_weighting(self) -> None:
        self.assertEqual(build_target_selection(self.feasibility), self.selection)
        self.assertEqual(self.selection["status"], "UNRESOLVED")
        self.assertEqual(self.selection["target_degradation_family"], "UNRESOLVED")
        self.assertFalse(self.selection["weighted_score_used"])
        self.assertFalse(self.selection["development_authorized"])

    def test_raw_proposal_source_bound_not_fabricated(self) -> None:
        self.assertEqual(
            self.summary["raw_proposal_source_binding"],
            "NOT_CREATED_FEASIBILITY_GATE_STOP",
        )
        self.assertFalse((OUTPUT_ROOT / "raw_proposal_evidence").exists())

    def test_sharpness_only_not_recovery_gain(self) -> None:
        self.assertEqual(self.summary["sharpness_hf_gain_rule"], "NOT_RECOVERY_PROOF")
        self.assertEqual(
            self.summary["recovery_direction_rule"],
            "CANDIDATE_TO_GT_ERROR_LT_BASELINE_TO_GT_ERROR_REQUIRED",
        )
        for row in self.feasibility["families"]:
            self.assertFalse(
                row["recoverable_structure_evidence"][
                    "sharpness_or_hf_is_recovery_proof"
                ]
            )

    def test_mild_controlled_recovery_not_run(self) -> None:
        self.assertEqual(
            self.summary["controlled_mild_recovery_direction"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )

    def test_moderate_controlled_recovery_not_run(self) -> None:
        self.assertEqual(
            self.summary["controlled_moderate_recovery_direction"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )

    def test_controlled_safety_gate_not_run(self) -> None:
        self.assertEqual(
            self.summary["controlled_hard_safety"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )
        self.assertEqual(
            self.summary["controlled_gate"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )

    def test_uncalibrated_parameter_contract_is_no_op(self) -> None:
        self.assertEqual(
            self.summary["uncalibrated_parameter_policy"],
            "NO_OP_IF_OPERATOR_EXISTS",
        )
        self.assertEqual(
            self.summary["threshold_provenance_status"],
            "NOT_CREATED_FEASIBILITY_GATE_STOP",
        )

    def test_invalid_runtime_authorization_contract_is_no_op(self) -> None:
        self.assertEqual(
            self.summary["invalid_runtime_authorization_policy"],
            "NO_OP_IF_OPERATOR_EXISTS",
        )
        self.assertEqual(
            self.summary["runtime_authorization"],
            "NOT_CREATED_FEASIBILITY_GATE_STOP",
        )

    def test_nonfinite_parameter_fails_closed(self) -> None:
        blur_case = next(
            case for case in self.manifest["cases"] if case["case_id"] == "E1C006"
        )
        invalid = copy.deepcopy(blur_case)
        invalid["degradation_params"]["blur_radius"] = float("nan")
        self.assertFalse(_blur_case(invalid))
        self.assertEqual(
            self.summary["nonfinite_parameter_policy"],
            "FAIL_CLOSED_NOT_IDENTITY_ELIGIBLE",
        )

    def test_hf_budget_not_claimed_without_operator(self) -> None:
        self.assertEqual(
            self.summary["high_frequency_budget_status"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )

    def test_overshoot_control_not_claimed_without_operator(self) -> None:
        self.assertEqual(
            self.summary["overshoot_control_status"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )

    def test_halo_ringing_control_not_claimed_without_operator(self) -> None:
        self.assertEqual(
            self.summary["halo_ringing_suppression_status"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )
        for field in ("halo_ringing_count", "white_edge_count", "black_edge_count"):
            self.assertEqual(
                self.summary[field],
                "NOT_RUN_FEASIBILITY_GATE_STOP",
            )

    def test_text_structure_protection_not_claimed_without_operator(self) -> None:
        self.assertEqual(
            self.summary["text_structure_protection_status"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )
        self.assertEqual(
            self.summary["text_damage_count"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )

    def test_color_lock_not_claimed_without_operator(self) -> None:
        self.assertEqual(
            self.summary["color_lock_status"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )
        self.assertEqual(
            self.summary["color_failure_count"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )

    def test_alpha_identity_not_claimed_as_real_e1_evidence(self) -> None:
        self.assertEqual(self.summary["alpha_e1_evidence"], "NOT_APPLICABLE")
        self.assertEqual(
            self.summary["alpha_lock_status"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )
        self.assertEqual(
            self.summary["alpha_failure_count"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )

    def test_determinism_not_applicable_without_candidate(self) -> None:
        self.assertIsNone(self.summary["candidate_id"])
        self.assertEqual(self.summary["determinism"], "NOT_APPLICABLE_NO_CANDIDATE")

    def test_controlled_fail_does_not_run_e1(self) -> None:
        self.assertEqual(self.summary["e1_cases_replayed"], "0/16")
        self.assertEqual(
            self.summary["e1_02_connected"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )
        self.assertFalse((OUTPUT_ROOT / "e1_02_results").exists())

    def test_controlled_pass_requires_e4k_02_but_was_not_reached(self) -> None:
        self.assertEqual(
            self.summary["controlled_pass_e4k_02_policy"],
            "REQUIRED_IF_REACHED_NOT_REACHED",
        )
        self.assertEqual(
            self.summary["e4k_02_connected"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )

    def test_non_target_no_op_was_not_run(self) -> None:
        self.assertEqual(
            self.summary["non_target_no_op_policy"],
            "REQUIRED_IF_E1_REACHED_NOT_REACHED",
        )
        self.assertEqual(
            self.summary["non_target_no_op_cases"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )

    def test_no_op_false_gain_zero_not_fabricated(self) -> None:
        self.assertEqual(
            self.summary["no_op_false_positive_gain_count"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )
        self.assertEqual(
            self.summary["non_target_new_hard_safety_failure_count"],
            "NOT_RUN_FEASIBILITY_GATE_STOP",
        )
        self.assertEqual(self.summary["real_4k_quality_gain"], "NOT_PROVEN")

    def test_formal_4k_unchanged(self) -> None:
        self.assertFalse(self.summary["formal_4k_pipeline_changed"])

    def test_api_unchanged(self) -> None:
        self.assertFalse(self.summary["api_4k_changed"])

    def test_e1_01_unchanged(self) -> None:
        self.assertFalse(self.summary["e1_01_changed"])

    def test_e1_02_unchanged(self) -> None:
        self.assertFalse(self.summary["e1_02_changed"])

    def test_e4k_02_frozen_artifact_unchanged(self) -> None:
        self.assertFalse(self.summary["e4k_02_frozen_artifact_changed"])

    def test_product_version_unchanged(self) -> None:
        self.assertFalse(self.summary["product_version_changed"])

    def test_artifact_is_minimal_valid_and_live_protected(self) -> None:
        allowed = {
            "feasibility/e1_target_family_feasibility.json",
            "target_family_selection/target_family_selection_v3.json",
            "validation/protected_scope.json",
            "validation/test_execution.json",
            "validation/hd_core_regression_execution.json",
            "summary.json",
            "integrity_manifest.json",
        }
        actual = {
            path.relative_to(OUTPUT_ROOT).as_posix()
            for path in OUTPUT_ROOT.rglob("*")
            if path.is_file()
        }
        self.assertTrue(actual.issubset(allowed), sorted(actual - allowed))
        validation = validate_artifact()
        self.assertEqual(validation["status"], "PASS", validation["failures"])
        self.assertEqual(protected_scope_state()["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
