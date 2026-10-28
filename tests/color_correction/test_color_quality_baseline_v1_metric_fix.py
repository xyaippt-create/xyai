from __future__ import annotations

import unittest

import numpy as np

from tests.color_correction import run_color_quality_baseline_v1 as baseline


def _metrics(grade: str, ratio: float, *, brand_status: str = "NOT_REQUIRED") -> dict:
    return {
        "grade": grade,
        "recovery_ratio": ratio,
        "regions": {},
        "regional_absolute_gate": {
            "regions": {"brand": {"status": brand_status}},
        },
    }


def _row(
    executor: str,
    recipe: str,
    safety: str,
    grade: str,
    ratio: float,
    *,
    categories: tuple[str, ...] = ("PERSON",),
    brand_status: str = "NOT_REQUIRED",
    reference_id: str = "REF_1",
) -> dict:
    color_metrics = _metrics(grade, ratio, brand_status=brand_status)
    color_grade = safety if safety in {"RISK", "EXECUTOR_LIMIT"} else grade
    return {
        "case_id": f"{reference_id}_{recipe}",
        "reference_id": reference_id,
        "executor": executor,
        "recipe": recipe,
        "executor_internal_safety": safety,
        "reference_categories": list(categories),
        "COLOR_EXECUTOR_GRADE": color_grade,
        "EXPOSURE_EXECUTOR_GRADE": "NOT_APPLICABLE",
        "EXPOSURE_STAGE_INCREMENT_GRADE": "NOT_APPLICABLE",
        "COMBINED_PIPELINE_GRADE": "NOT_APPLICABLE",
        "COMMERCIAL_DELIVERY_DECISION": "NOT_AUTHORIZED",
        "COLOR_EXECUTOR_CREDIT": (
            "YES"
            if safety == "PASS" and color_grade in baseline.POSITIVE_GRADES
            else "NO"
        ),
        "COMBINED_ATTRIBUTION": "NOT_APPLICABLE",
        "error_path": f"errors/{reference_id}_{recipe}.png",
        "candidate_path": f"candidates/{executor}/{reference_id}_{recipe}.png",
        "RAW_REFERENCE_METRICS": {"COLOR_STAGE": color_metrics},
        "metrics": color_metrics,
    }


class ColorQualityBaselineMetricFixTests(unittest.TestCase):
    def test_invalid_color_stage_cannot_receive_combined_improvement_credit(self) -> None:
        interpretation = baseline._stage_interpretation(
            recipe="CAST_PLUS_EXPOSURE",
            safety_status="EXECUTOR_LIMIT",
            color_metrics=_metrics("IMPROVED", 0.30),
            exposure_stage_increment_metrics=_metrics("IMPROVED", 0.33),
            exposure_only_metrics=_metrics("IMPROVED", 0.32),
            combined_metrics=_metrics("IMPROVED", 0.31),
        )

        self.assertEqual(interpretation["COLOR_EXECUTOR_GRADE"], "EXECUTOR_LIMIT")
        self.assertEqual(interpretation["EXPOSURE_EXECUTOR_GRADE"], "IMPROVED")
        self.assertEqual(interpretation["EXPOSURE_STAGE_INCREMENT_GRADE"], "IMPROVED")
        self.assertEqual(interpretation["COMBINED_PIPELINE_GRADE"], "IMPROVED")
        self.assertEqual(interpretation["COLOR_EXECUTOR_CREDIT"], "NO")
        self.assertEqual(interpretation["COMBINED_ATTRIBUTION"], "EXPOSURE_ONLY")
        self.assertEqual(interpretation["COMMERCIAL_DELIVERY_DECISION"], "NOT_AUTHORIZED")

    def test_exposure_only_requires_positive_actual_stage_increment(self) -> None:
        interpretation = baseline._stage_interpretation(
            recipe="CAST_PLUS_EXPOSURE",
            safety_status="RISK",
            color_metrics=_metrics("UNCHANGED", 0.05),
            exposure_stage_increment_metrics=_metrics("UNCHANGED", 0.10),
            exposure_only_metrics=_metrics("IMPROVED", 0.32),
            combined_metrics=_metrics("IMPROVED", 0.31),
        )

        self.assertEqual(interpretation["COLOR_EXECUTOR_CREDIT"], "NO")
        self.assertEqual(interpretation["EXPOSURE_EXECUTOR_GRADE"], "IMPROVED")
        self.assertEqual(interpretation["EXPOSURE_STAGE_INCREMENT_GRADE"], "UNCHANGED")
        self.assertEqual(interpretation["COMBINED_PIPELINE_GRADE"], "IMPROVED")
        self.assertEqual(interpretation["COMBINED_ATTRIBUTION"], "COMBINED_UNATTRIBUTED")

    def test_safe_but_unchanged_pure_stage_receives_no_color_credit(self) -> None:
        interpretation = baseline._stage_interpretation(
            recipe="YELLOW_CAST",
            safety_status="PASS",
            color_metrics=_metrics("UNCHANGED", 0.05),
            exposure_stage_increment_metrics=None,
            exposure_only_metrics=None,
            combined_metrics=None,
        )

        self.assertEqual(interpretation["COLOR_EXECUTOR_GRADE"], "UNCHANGED")
        self.assertEqual(interpretation["COLOR_EXECUTOR_CREDIT"], "NO")

    def test_safe_but_unattributed_combined_stage_receives_no_color_credit(self) -> None:
        interpretation = baseline._stage_interpretation(
            recipe="CAST_PLUS_EXPOSURE",
            safety_status="PASS",
            color_metrics=_metrics("UNCHANGED", 0.05),
            exposure_stage_increment_metrics=_metrics("UNCHANGED", 0.05),
            exposure_only_metrics=_metrics("UNCHANGED", 0.05),
            combined_metrics=_metrics("UNCHANGED", 0.05),
        )

        self.assertEqual(interpretation["COMBINED_ATTRIBUTION"], "COMBINED_UNATTRIBUTED")
        self.assertEqual(interpretation["COLOR_EXECUTOR_CREDIT"], "NO")

    def test_positive_color_contribution_receives_credit(self) -> None:
        pure = baseline._stage_interpretation(
            recipe="YELLOW_CAST",
            safety_status="PASS",
            color_metrics=_metrics("IMPROVED", 0.30),
            exposure_stage_increment_metrics=None,
            exposure_only_metrics=None,
            combined_metrics=None,
        )
        combined = baseline._stage_interpretation(
            recipe="CAST_PLUS_EXPOSURE",
            safety_status="PASS",
            color_metrics=_metrics("IMPROVED", 0.30),
            exposure_stage_increment_metrics=_metrics("UNCHANGED", 0.05),
            exposure_only_metrics=_metrics("UNCHANGED", 0.05),
            combined_metrics=_metrics("IMPROVED", 0.30),
        )

        self.assertEqual(pure["COLOR_EXECUTOR_CREDIT"], "YES")
        self.assertEqual(combined["COMBINED_ATTRIBUTION"], "COLOR_ONLY")
        self.assertEqual(combined["COLOR_EXECUTOR_CREDIT"], "YES")

    def test_color_summary_excludes_combined_recipes_and_counts_invalid_pure_attempts(self) -> None:
        rows = [
            _row("SAFE_WB", "YELLOW_CAST", "PASS", "IMPROVED", 0.30),
            _row("SAFE_WB", "BLUE_CAST", "EXECUTOR_LIMIT", "IMPROVED", 0.40),
            _row("SAFE_WB", "CAST_PLUS_EXPOSURE", "EXECUTOR_LIMIT", "IMPROVED", 0.90),
        ]

        summary = baseline._executor_summary(rows, "SAFE_WB")

        self.assertEqual(summary["pure_color_attempt_count"], 2)
        self.assertEqual(summary["eligible_color_attempt_count"], 1)
        self.assertEqual(summary["IMPROVED"], 1)
        self.assertEqual(summary["EXECUTOR_LIMIT"], 1)
        self.assertNotIn("CAST_PLUS_EXPOSURE", summary["recipe_grades"])

    def test_category_ranking_is_not_authorized_before_evidence_policy(self) -> None:
        rows = [
            _row("SAFE_WB", "YELLOW_CAST", "PASS", "IMPROVED", 0.20),
            _row("cross_affine_balanced", "YELLOW_CAST", "PASS", "IMPROVED", 0.30),
            _row("SAFE_WB", "CAST_PLUS_EXPOSURE", "PASS", "IMPROVED", 0.99),
        ]

        means, winners, evidence = baseline._category_rankings(rows)

        self.assertEqual(winners["PERSON"], "NOT_EVALUABLE")
        self.assertAlmostEqual(means["PERSON"]["SAFE_WB"], 0.20)
        self.assertAlmostEqual(means["PERSON"]["cross_affine_balanced"], 0.30)
        self.assertEqual(evidence["PERSON"]["paired_case_count"], 1)
        self.assertEqual(evidence["PERSON"]["distinct_reference_count"], 1)
        self.assertEqual(
            evidence["PERSON"]["authority"],
            "DESCRIPTIVE_ONLY_NOT_EVALUABLE_PENDING_D57_COLOR_02_EVIDENCE_POLICY",
        )

    def test_category_descriptive_means_use_only_paired_pure_cases(self) -> None:
        rows = [
            _row("SAFE_WB", "YELLOW_CAST", "PASS", "IMPROVED", 0.20),
            _row("cross_affine_balanced", "YELLOW_CAST", "PASS", "IMPROVED", 0.30),
            _row(
                "SAFE_WB",
                "BLUE_CAST",
                "PASS",
                "IMPROVED",
                0.80,
                reference_id="REF_2",
            ),
            _row(
                "cross_affine_balanced",
                "OTHER_GLOBAL_CAST",
                "PASS",
                "IMPROVED",
                0.90,
                reference_id="REF_3",
            ),
        ]

        means, winners, evidence = baseline._category_rankings(rows)

        self.assertEqual(winners["PERSON"], "NOT_EVALUABLE")
        self.assertAlmostEqual(means["PERSON"]["SAFE_WB"], 0.20)
        self.assertAlmostEqual(means["PERSON"]["cross_affine_balanced"], 0.30)
        self.assertEqual(evidence["PERSON"]["paired_case_count"], 1)
        self.assertEqual(evidence["PERSON"]["distinct_reference_count"], 1)
        self.assertEqual(
            evidence["PERSON"]["unpaired_eligible_case_count_by_executor"],
            {"SAFE_WB": 1, "cross_affine_balanced": 1},
        )

    def test_metric_contract_status_fails_closed(self) -> None:
        gates = {
            "pixel_reuse": {"status": "PASS"},
            "combined_attribution": {"status": "FAIL"},
        }

        self.assertEqual(baseline._derive_metric_contract_status(gates), "FAIL")

    def test_metric_contract_gate_rejects_inconsistent_color_credit(self) -> None:
        rows = [
            _row("SAFE_WB", "YELLOW_CAST", "PASS", "UNCHANGED", 0.05),
            _row(
                "cross_affine_balanced",
                "YELLOW_CAST",
                "PASS",
                "UNCHANGED",
                0.05,
            ),
        ]
        for row in rows:
            row["COLOR_EXECUTOR_CREDIT"] = "YES"

        gates = baseline._metric_contract_gates(
            rows,
            reference_records=[{} for _ in baseline.REFERENCES],
            expected_cases=1,
            best_by_category={},
            category_evidence={},
            pixel_reuse={"errors": {"status": "PASS"}, "candidates": {"status": "PASS"}},
        )

        self.assertEqual(gates["invalid_color_credit"]["status"], "FAIL")
        self.assertEqual(gates["invalid_color_credit"]["violation_count"], 2)
        self.assertEqual(baseline._derive_metric_contract_status(gates), "FAIL")

        missing_credit_rows = [
            _row("SAFE_WB", "YELLOW_CAST", "PASS", "IMPROVED", 0.30),
            _row(
                "cross_affine_balanced",
                "YELLOW_CAST",
                "PASS",
                "IMPROVED",
                0.30,
            ),
        ]
        for row in missing_credit_rows:
            row["COLOR_EXECUTOR_CREDIT"] = "NO"

        missing_credit_gates = baseline._metric_contract_gates(
            missing_credit_rows,
            reference_records=[{} for _ in baseline.REFERENCES],
            expected_cases=1,
            best_by_category={},
            category_evidence={},
            pixel_reuse={"errors": {"status": "PASS"}, "candidates": {"status": "PASS"}},
        )

        self.assertEqual(missing_credit_gates["invalid_color_credit"]["status"], "FAIL")
        self.assertEqual(
            missing_credit_gates["invalid_color_credit"]["violation_count"],
            2,
        )
        self.assertEqual(
            baseline._derive_metric_contract_status(missing_credit_gates),
            "FAIL",
        )

    def test_recovered_requires_present_neutral_region_absolute_gate(self) -> None:
        reference = np.full((16, 16, 3), 128, dtype=np.uint8)
        error = reference.copy()
        error[..., 0] = 170
        masks = {
            "neutral": np.ones((16, 16), dtype=bool),
            "skin": np.zeros((16, 16), dtype=bool),
            "strong": np.zeros((16, 16), dtype=bool),
        }

        metrics = baseline._reference_metrics(
            reference,
            error,
            reference,
            masks,
            reference_categories=("WHITE_GRAY_NEUTRAL",),
        )

        self.assertEqual(metrics["regional_absolute_gate"]["overall"], "PASS")
        self.assertEqual(metrics["regional_absolute_gate"]["regions"]["neutral"]["status"], "PASS")
        self.assertEqual(metrics["grade"], "RECOVERED")

    def test_missing_authoritative_brand_roi_is_not_evaluable_and_cannot_recover(self) -> None:
        reference = np.full((16, 16, 3), 128, dtype=np.uint8)
        error = reference.copy()
        error[..., 2] = 180
        masks = {
            "neutral": np.ones((16, 16), dtype=bool),
            "skin": np.zeros((16, 16), dtype=bool),
            "strong": np.ones((16, 16), dtype=bool),
        }

        metrics = baseline._reference_metrics(
            reference,
            error,
            reference,
            masks,
            reference_categories=("BRAND_COLOR",),
        )

        self.assertEqual(metrics["regional_absolute_gate"]["regions"]["brand"]["status"], "NOT_EVALUABLE")
        self.assertEqual(metrics["regional_absolute_gate"]["overall"], "NOT_EVALUABLE")
        self.assertNotEqual(metrics["grade"], "RECOVERED")


if __name__ == "__main__":
    unittest.main()
