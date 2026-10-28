from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.experiments.e4k_03_first_real_candidate import (
    _build_runtime_summary,
    _derive_candidate_comparison_outcome,
    _e4k_02_reporting_scope,
    _selection_key,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CURRENT_COMPARISON = REPO_ROOT / "artifacts" / "E4K_03_CANDIDATE_COMPARISON.json"
CURRENT_CANDIDATE_ROOT = (
    REPO_ROOT
    / "artifacts"
    / "e4k_03_candidates"
    / "candidate_a7e8332b2a88abb11d6c0bd0aa06e3ca2332775853b9c43bef2722b45b8f3d05"
)
CURRENT_ELIGIBILITY_ROOT = REPO_ROOT / "artifacts" / "e4k_03_model_eligibility"
STALE_MEMORY_FIELDS = {
    "observed_peak_rss_bytes",
    "peak_memory",
    "true_peak_memory_bytes",
}


def _row(
    *,
    candidate_id: str | None,
    eligibility: str,
    final_status: str,
    selection_evidence: dict[str, int | float] | None = None,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "model_id": candidate_id or "BLOCKED_MODEL",
        "eligibility": eligibility,
        "final_status": final_status,
        "selection_evidence": selection_evidence,
    }


def _selection_evidence(
    *,
    proven: int = 4,
    mandatory: int = 16,
    safety_fail: int = 0,
    rejected: int = 0,
    commercial_risk: int = 0,
    human_better: int = 4,
    runtime_seconds: float = 10.0,
) -> dict[str, int | float]:
    return {
        "quality_gain_proven_case_count": proven,
        "mandatory_gate_complete_case_count": mandatory,
        "hard_safety_fail_count": safety_fail,
        "quality_gain_rejected_case_count": rejected,
        "commercial_high_risk_failure_count": commercial_risk,
        "human_review_confirmed_better_count": human_better,
        "observed_runtime_cost_seconds": runtime_seconds,
    }


def _contains_stale_memory_field(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            key in STALE_MEMORY_FIELDS or _contains_stale_memory_field(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_stale_memory_field(item) for item in value)
    return False


def _active_e4k_03_json_paths() -> list[Path]:
    paths = [
        CURRENT_COMPARISON,
        CURRENT_CANDIDATE_ROOT / "summary.json",
        CURRENT_CANDIDATE_ROOT / "candidate_manifest.json",
        CURRENT_CANDIDATE_ROOT / "validation" / "smoke_summary.json",
    ]
    paths.extend(sorted((CURRENT_CANDIDATE_ROOT / "runtime").glob("*.json")))
    paths.extend(sorted(CURRENT_ELIGIBILITY_ROOT.rglob("*.json")))
    return paths


class E4K03ReportingTest(unittest.TestCase):
    def _assert_nonfinite_order_independent(self, value: float) -> None:
        rows = [
            _row(
                candidate_id="A_NONFINITE",
                eligibility="PASS",
                final_status="ADOPT",
                selection_evidence=_selection_evidence(runtime_seconds=value),
            ),
            _row(
                candidate_id="B_FINITE",
                eligibility="PASS",
                final_status="ADOPT",
                selection_evidence=_selection_evidence(runtime_seconds=1.0),
            ),
        ]
        outcomes = [
            _derive_candidate_comparison_outcome(rows),
            _derive_candidate_comparison_outcome(list(reversed(rows))),
        ]
        expected = {
            "best_candidate": "UNRESOLVED_MULTI_ADOPT",
            "best_candidate_reason": "INVALID_OR_NONFINITE_SELECTION_EVIDENCE",
            "model_adoption": "NEEDS_SELECTION_REVIEW",
            "selection_evidence_finite_gate": "SELECTION_EVIDENCE_FINITE_GATE_V1",
            "selection_evidence_status": "INVALID_OR_NONFINITE",
            "status": "BLOCKED_WITH_SELECTION_REVIEW_REQUIRED",
            "real_4k_quality_gain": "NOT_PROVEN",
        }
        for outcome in outcomes:
            self.assertEqual(
                {field: outcome[field] for field in expected},
                expected,
            )

    def test_comparison_no_adopt_returns_none(self) -> None:
        outcome = _derive_candidate_comparison_outcome(
            [_row(candidate_id="candidate_reject", eligibility="PASS", final_status="REJECT")]
        )
        self.assertEqual(outcome["best_candidate"], "NONE")
        self.assertEqual(outcome["model_adoption"], "NONE")
        self.assertEqual(outcome["adopted_candidate_count"], 0)
        self.assertEqual(outcome["real_4k_quality_gain"], "NOT_PROVEN")
        self.assertEqual(outcome["status"], "PASS_WITH_TECHNICAL_CONCLUSION")

    def test_comparison_one_valid_adopt_selects_candidate(self) -> None:
        outcome = _derive_candidate_comparison_outcome(
            [
                _row(
                    candidate_id="candidate_valid",
                    eligibility="PASS",
                    final_status="ADOPT",
                    selection_evidence=_selection_evidence(),
                )
            ]
        )
        self.assertEqual(outcome["best_candidate"], "candidate_valid")
        self.assertEqual(outcome["model_adoption"], "candidate_valid")
        self.assertEqual(outcome["adopted_candidate_count"], 1)
        self.assertEqual(outcome["real_4k_quality_gain"], "PROVEN")
        self.assertEqual(outcome["status"], "PASS")

    def test_comparison_rejected_candidate_cannot_become_best(self) -> None:
        outcome = _derive_candidate_comparison_outcome(
            [_row(candidate_id="candidate_reject", eligibility="PASS", final_status="REJECT")]
        )
        self.assertEqual(outcome["best_candidate"], "NONE")

    def test_comparison_blocked_candidate_cannot_become_best(self) -> None:
        outcome = _derive_candidate_comparison_outcome(
            [_row(candidate_id="candidate_blocked", eligibility="BLOCKED", final_status="ADOPT")]
        )
        self.assertEqual(outcome["best_candidate"], "NONE")

    def test_keep_for_research_candidate_cannot_become_best(self) -> None:
        outcome = _derive_candidate_comparison_outcome(
            [
                _row(
                    candidate_id="candidate_research",
                    eligibility="PASS",
                    final_status="KEEP_FOR_RESEARCH",
                )
            ]
        )
        self.assertEqual(outcome["best_candidate"], "NONE")

    def test_multi_adopt_higher_proven_gain_wins(self) -> None:
        outcome = _derive_candidate_comparison_outcome(
            [
                _row(
                    candidate_id="a_candidate",
                    eligibility="PASS",
                    final_status="ADOPT",
                    selection_evidence=_selection_evidence(
                        proven=4, runtime_seconds=1.0
                    ),
                ),
                _row(
                    candidate_id="z_candidate",
                    eligibility="PASS",
                    final_status="ADOPT",
                    selection_evidence=_selection_evidence(
                        proven=5, runtime_seconds=100.0
                    ),
                ),
            ]
        )
        self.assertEqual(outcome["best_candidate"], "z_candidate")

    def test_multi_adopt_fewer_safety_failures_wins(self) -> None:
        outcome = _derive_candidate_comparison_outcome(
            [
                _row(
                    candidate_id="a_candidate",
                    eligibility="PASS",
                    final_status="ADOPT",
                    selection_evidence=_selection_evidence(safety_fail=2),
                ),
                _row(
                    candidate_id="z_candidate",
                    eligibility="PASS",
                    final_status="ADOPT",
                    selection_evidence=_selection_evidence(safety_fail=1),
                ),
            ]
        )
        self.assertEqual(outcome["best_candidate"], "z_candidate")

    def test_multi_adopt_runtime_only_used_after_quality_tie(self) -> None:
        outcome = _derive_candidate_comparison_outcome(
            [
                _row(
                    candidate_id="a_candidate",
                    eligibility="PASS",
                    final_status="ADOPT",
                    selection_evidence=_selection_evidence(runtime_seconds=20.0),
                ),
                _row(
                    candidate_id="z_candidate",
                    eligibility="PASS",
                    final_status="ADOPT",
                    selection_evidence=_selection_evidence(runtime_seconds=10.0),
                ),
            ]
        )
        self.assertEqual(outcome["best_candidate"], "z_candidate")

    def test_selection_rejects_nan(self) -> None:
        row = _row(
            candidate_id="candidate_nan",
            eligibility="PASS",
            final_status="ADOPT",
            selection_evidence=_selection_evidence(runtime_seconds=float("nan")),
        )
        self.assertIsNone(_selection_key(row))

    def test_selection_rejects_positive_infinity(self) -> None:
        row = _row(
            candidate_id="candidate_pos_inf",
            eligibility="PASS",
            final_status="ADOPT",
            selection_evidence=_selection_evidence(runtime_seconds=float("inf")),
        )
        self.assertIsNone(_selection_key(row))

    def test_selection_rejects_negative_infinity(self) -> None:
        row = _row(
            candidate_id="candidate_neg_inf",
            eligibility="PASS",
            final_status="ADOPT",
            selection_evidence=_selection_evidence(runtime_seconds=float("-inf")),
        )
        self.assertIsNone(_selection_key(row))

    def test_finite_gate_covers_every_selection_evidence_field(self) -> None:
        evidence = _selection_evidence()
        for field in evidence:
            with self.subTest(field=field):
                invalid = dict(evidence)
                invalid[field] = float("nan")
                row = _row(
                    candidate_id="candidate_nonfinite",
                    eligibility="PASS",
                    final_status="ADOPT",
                    selection_evidence=invalid,
                )
                self.assertIsNone(_selection_key(row))

    def test_multi_adopt_nan_order_independent(self) -> None:
        self._assert_nonfinite_order_independent(float("nan"))

    def test_multi_adopt_positive_infinity_order_independent(self) -> None:
        self._assert_nonfinite_order_independent(float("inf"))

    def test_multi_adopt_negative_infinity_order_independent(self) -> None:
        self._assert_nonfinite_order_independent(float("-inf"))

    def test_single_adopt_with_nonfinite_required_evidence_not_auto_selected(
        self,
    ) -> None:
        outcome = _derive_candidate_comparison_outcome(
            [
                _row(
                    candidate_id="candidate_nan",
                    eligibility="PASS",
                    final_status="ADOPT",
                    selection_evidence=_selection_evidence(runtime_seconds=float("nan")),
                )
            ]
        )
        self.assertEqual(outcome["best_candidate"], "UNRESOLVED_MULTI_ADOPT")
        self.assertEqual(
            outcome["best_candidate_reason"],
            "INVALID_OR_NONFINITE_SELECTION_EVIDENCE",
        )
        self.assertEqual(outcome["model_adoption"], "NEEDS_SELECTION_REVIEW")
        self.assertEqual(outcome["status"], "BLOCKED_WITH_SELECTION_REVIEW_REQUIRED")
        self.assertEqual(outcome["real_4k_quality_gain"], "NOT_PROVEN")

    def test_runtime_nonfinite_cannot_act_as_tiebreaker(self) -> None:
        self._assert_nonfinite_order_independent(float("nan"))

    def test_multi_adopt_full_tie_returns_unresolved(self) -> None:
        evidence = _selection_evidence()
        outcome = _derive_candidate_comparison_outcome(
            [
                _row(
                    candidate_id="a_candidate",
                    eligibility="PASS",
                    final_status="ADOPT",
                    selection_evidence=evidence,
                ),
                _row(
                    candidate_id="z_candidate",
                    eligibility="PASS",
                    final_status="ADOPT",
                    selection_evidence=evidence,
                ),
            ]
        )
        self.assertEqual(outcome["best_candidate"], "UNRESOLVED_MULTI_ADOPT")
        self.assertEqual(outcome["model_adoption"], "NEEDS_SELECTION_REVIEW")
        self.assertEqual(
            outcome["best_candidate_reason"], "NO_EVIDENCE_BASED_UNIQUE_WINNER"
        )

    def test_candidate_id_lexical_order_has_no_authority(self) -> None:
        outcome = _derive_candidate_comparison_outcome(
            [
                _row(
                    candidate_id="z_candidate",
                    eligibility="PASS",
                    final_status="ADOPT",
                    selection_evidence=_selection_evidence(proven=6),
                ),
                _row(
                    candidate_id="a_candidate",
                    eligibility="PASS",
                    final_status="ADOPT",
                    selection_evidence=_selection_evidence(proven=1),
                ),
            ]
        )
        self.assertEqual(outcome["best_candidate"], "z_candidate")

    def test_current_swin2sr_artifact_still_returns_no_adopt(self) -> None:
        current = json.loads(CURRENT_COMPARISON.read_text(encoding="utf-8"))
        outcome = _derive_candidate_comparison_outcome(current["candidates"])
        self.assertEqual(outcome["best_candidate"], "NONE")
        self.assertEqual(outcome["model_adoption"], "NONE")
        self.assertEqual(outcome["real_4k_quality_gain"], "NOT_PROVEN")
        self.assertEqual(
            outcome["selection_evidence_finite_gate"],
            "SELECTION_EVIDENCE_FINITE_GATE_V1",
        )
        self.assertEqual(outcome["selection_evidence_status"], "NOT_APPLICABLE")

    def test_memory_report_uses_sampled_rss_term(self) -> None:
        summary = _build_runtime_summary(
            [
                {
                    "model_load_time_seconds": 0.1,
                    "inference_time_seconds": 1.0,
                    "total_processing_time_seconds": 1.2,
                    "observed_peak_rss_bytes": 123,
                    "input_pixels": 10,
                    "output_pixels": 40,
                    "tile_count": 2,
                }
            ]
        )
        self.assertEqual(summary["observed_sampled_rss_max_bytes"], 123)
        self.assertNotIn("peak_memory", summary)
        self.assertNotIn("observed_peak_rss_bytes", summary)

    def test_true_peak_memory_remains_not_proven(self) -> None:
        summary = _build_runtime_summary(
            [
                {
                    "model_load_time_seconds": 0.1,
                    "inference_time_seconds": 1.0,
                    "total_processing_time_seconds": 1.2,
                    "observed_peak_rss_bytes": 123,
                    "input_pixels": 10,
                    "output_pixels": 40,
                    "tile_count": 2,
                }
            ]
        )
        self.assertEqual(summary["true_peak_memory"], "NOT_PROVEN")

    def test_candidate_manifest_uses_sampled_rss_term(self) -> None:
        manifest = json.loads(
            (CURRENT_CANDIDATE_ROOT / "candidate_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(_contains_stale_memory_field(manifest))

    def test_comparison_uses_sampled_rss_term(self) -> None:
        comparison = json.loads(CURRENT_COMPARISON.read_text(encoding="utf-8"))
        self.assertFalse(_contains_stale_memory_field(comparison))

    def test_active_artifact_has_no_misleading_peak_memory_field(self) -> None:
        stale = [
            path
            for path in _active_e4k_03_json_paths()
            if _contains_stale_memory_field(
                json.loads(path.read_text(encoding="utf-8"))
            )
        ]
        self.assertEqual(stale, [])

    def test_e4k_02_reporting_scope_is_explicit(self) -> None:
        scope = _e4k_02_reporting_scope()
        self.assertFalse(scope["e4k_02_artifact_changed"])
        self.assertFalse(scope["e4k_02_control_semantics_changed"])
        self.assertTrue(scope["e4k_02_shared_source_extended"])
        self.assertEqual(
            scope["extended_source"], "engine/hd_core/candidate_framework.py"
        )


if __name__ == "__main__":
    unittest.main()
