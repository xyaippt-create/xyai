"""Close E4K-04 V3 at the real-E1 feasibility gate when evidence is insufficient.

This tool never develops or executes a restoration operator.  It reads the
frozen E1-01/E1-02 evidence, proves whether Blur/Multi-Resize have enough real
holdout replication, and fails closed before calibration or E1 replay.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.hd_core.bounded_restoration import build_degradation_profile  # noqa: E402
from engine.hd_core.candidate_framework import sha256_file  # noqa: E402
from tools.experiments.e4k_04_bounded_restoration_core import (  # noqa: E402
    protected_scope_state,
)


VERSION = "V0.5.7"
LINE = "E"
TASK_ID = "E4K-04_SOURCE_RECOVERY_CANDIDATE_V3"
ARTIFACT_VERSION = "E4K_04_SOURCE_RECOVERY_V3_FEASIBILITY_ARTIFACT_V1"
FEASIBILITY_VERSION = "E4K04_V3_REAL_E1_FEASIBILITY_V1"
TARGET_SELECTION_VERSION = "E4K04_V3_TARGET_FAMILY_SELECTION_V1"
TEST_EXECUTION_VERSION = "E4K04_V3_TEST_EXECUTION_V1"
REGRESSION_EXECUTION_VERSION = "E4K04_V3_HD_CORE_REGRESSION_V1"
EXPECTED_E1_CASE_COUNT = 16
MINIMUM_REAL_HOLDOUT_CASES = 2

E1_MANIFEST = (
    REPO_ROOT / "artifacts" / "e1_01_real_information_baseline_v1" / "manifest.json"
)
E1_ZERO_RESULTS = (
    REPO_ROOT / "artifacts" / "e1_02_quality_delivery_gate_v1" / "case_results"
)
OUTPUT_ROOT = REPO_ROOT / "artifacts" / "e4k_04_source_recovery_v3"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None


def _asset_is_bound(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    path_value = record.get("path")
    expected_sha = record.get("sha256")
    if not isinstance(path_value, str) or not isinstance(expected_sha, str):
        return False
    path = (REPO_ROOT / path_value).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError:
        return False
    return path.is_file() and sha256_file(path) == expected_sha


def _blur_case(case: dict[str, Any]) -> bool:
    params = case.get("degradation_params") or {}
    return (
        case.get("degradation_type") == "BLUR_JPEG"
        and _finite_number(params.get("blur_radius")) is not None
    )


def _multi_resize_case(case: dict[str, Any]) -> bool:
    params = case.get("degradation_params") or {}
    scales = params.get("scales")
    return (
        case.get("degradation_type") == "MULTI_RESIZE"
        and isinstance(scales, list)
        and len(scales) >= 2
        and all(
            (value := _finite_number(item)) is not None and 0.0 < value < 1.0
            for item in scales
        )
    )


def _blur_multi_resize_case(case: dict[str, Any]) -> bool:
    params = case.get("degradation_params") or {}
    scales = params.get("scales")
    return (
        _finite_number(params.get("blur_radius")) is not None
        and isinstance(scales, list)
        and len(scales) >= 2
        and all(
            (value := _finite_number(item)) is not None and 0.0 < value < 1.0
            for item in scales
        )
    )


FAMILY_MATCHERS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "BLUR": _blur_case,
    "MULTI_RESIZE": _multi_resize_case,
    "BLUR_MULTI_RESIZE": _blur_multi_resize_case,
}


def _historical_case_evidence(case: dict[str, Any]) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "")
    result_path = E1_ZERO_RESULTS / f"ZERO__{case_id}.json"
    failures: list[str] = []
    for field in ("input", "safe_base", "gt"):
        if not _asset_is_bound(case.get(field)):
            failures.append(f"{field.upper()}_ASSET_BINDING_INVALID")
    if not result_path.is_file():
        failures.append("FROZEN_E1_02_ZERO_RESULT_MISSING")
        result: dict[str, Any] = {}
    else:
        result = _read_json(result_path)
    if result.get("e1_01_case_id") != case_id:
        failures.append("E1_02_CASE_BINDING_MISMATCH")
    if (result.get("eligibility") or {}).get("status") != "ELIGIBLE":
        failures.append("E1_02_RESULT_NOT_ELIGIBLE")
    gt_evidence = ((result.get("quality_gain_results") or {}).get("gt_evidence") or {})
    baseline_delta = ((gt_evidence.get("baseline_to_gt") or {}).get("delta_metrics") or {})
    required_metrics = {
        name: _finite_number(baseline_delta.get(name))
        for name in (
            "rgb_mae",
            "global_ssim",
            "sharpness_ratio",
            "high_frequency_ratio",
            "edge_continuity_ratio",
            "delta_e76_mean",
            "delta_e76_p95",
        )
    }
    if any(value is None for value in required_metrics.values()):
        failures.append("BASELINE_GT_METRIC_NONFINITE_OR_MISSING")
    input_path = (REPO_ROOT / case["input"]["path"]).resolve()
    source_profile = build_degradation_profile(input_path)
    return {
        "case_id": case_id,
        "sample_id": case.get("sample_id"),
        "source_class": case.get("source_class"),
        "evidence_role": case.get("evidence_role"),
        "degradation_type": case.get("degradation_type"),
        "degradation_params": case.get("degradation_params"),
        "input_sha256": (case.get("input") or {}).get("sha256"),
        "safe_base_sha256": (case.get("safe_base") or {}).get("sha256"),
        "gt_sha256": (case.get("gt") or {}).get("sha256"),
        "roi_types": [str(item.get("roi_type") or "UNKNOWN") for item in case.get("roi", [])],
        "reference_evidence": "FROZEN_E1_01_GT_AND_E1_02_ZERO_BASELINE_MEASUREMENT",
        "baseline_to_gt": required_metrics,
        "source_probes": {
            "evidence_scope": source_profile.get("evidence_claim_scope"),
            "compression_evidence": source_profile.get("compression_evidence"),
            "blur_evidence": source_profile.get("blur_evidence"),
            "edge_evidence": source_profile.get("edge_evidence"),
            "text_like_risk": source_profile.get("text_like_risk"),
        },
        "status": "VALID" if not failures else "INVALID",
        "failures": failures,
    }


def _family_row(
    family: str,
    cases: list[dict[str, Any]],
    matcher: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    matched = [case for case in cases if matcher(case)]
    evidence = [_historical_case_evidence(case) for case in matched]
    valid = [item for item in evidence if item["status"] == "VALID"]
    real_holdout = [
        item
        for item in valid
        if item["source_class"] == "REAL_COMMERCIAL_IMAGE"
        and item["evidence_role"] == "CONTROLLED_GT_PRIMARY"
        and item["gt_sha256"] is not None
    ]
    headroom = [item["baseline_to_gt"]["rgb_mae"] for item in valid]
    edge_ratios = [
        ((item["source_probes"].get("edge_evidence") or {}).get("canny_edge_fraction"))
        for item in valid
    ]
    text_ratios = [
        ((item["source_probes"].get("text_like_risk") or {}).get("text_mask_ratio"))
        for item in valid
    ]
    color_mean = [item["baseline_to_gt"]["delta_e76_mean"] for item in valid]
    color_p95 = [item["baseline_to_gt"]["delta_e76_p95"] for item in valid]
    reference_count = sum(
        item["gt_sha256"] is not None
        and item["baseline_to_gt"]["rgb_mae"] is not None
        for item in valid
    )
    feasible = (
        len(real_holdout) >= MINIMUM_REAL_HOLDOUT_CASES
        and reference_count >= MINIMUM_REAL_HOLDOUT_CASES
    )
    degradation_parameters = [item["degradation_params"] for item in valid]
    return {
        "family": family,
        "case_ids": [item["case_id"] for item in evidence],
        "valid_case_count": len(valid),
        "gt_available_count": sum(item["gt_sha256"] is not None for item in valid),
        "real_holdout_count": len(real_holdout),
        "real_holdout_definition": (
            "REAL_COMMERCIAL_IMAGE_AND_CONTROLLED_GT_PRIMARY_AND_BOUND_GT"
        ),
        "reference_evidence_count": reference_count,
        "baseline_error_headroom": {
            "status": "MEASURED_FROM_FROZEN_E1_02_ZERO_RESULTS" if headroom else "NONE",
            "rgb_mae_by_case": {
                item["case_id"]: item["baseline_to_gt"]["rgb_mae"] for item in valid
            },
            "mean_rgb_mae": (
                round(sum(headroom) / len(headroom), 8) if headroom else None
            ),
        },
        "source_degradation_strength": {
            "status": "FROZEN_GENERATION_METADATA_AND_SOURCE_PROBES" if valid else "NONE",
            "degradation_parameters": degradation_parameters,
            "blur_probe_by_case": {
                item["case_id"]: item["source_probes"].get("blur_evidence")
                for item in valid
            },
        },
        "recoverable_structure_evidence": {
            "status": "BASELINE_LOSS_MEASURED_NOT_RECOVERY_PROOF" if valid else "NONE",
            "mean_strong_edge_ratio": (
                round(
                    sum(float(value) for value in edge_ratios if _finite_number(value) is not None)
                    / sum(_finite_number(value) is not None for value in edge_ratios),
                    8,
                )
                if any(_finite_number(value) is not None for value in edge_ratios)
                else None
            ),
            "baseline_gt_ratios_by_case": {
                item["case_id"]: {
                    name: item["baseline_to_gt"][name]
                    for name in (
                        "global_ssim",
                        "sharpness_ratio",
                        "high_frequency_ratio",
                        "edge_continuity_ratio",
                    )
                }
                for item in valid
            },
            "sharpness_or_hf_is_recovery_proof": False,
        },
        "text_structure_risk": {
            "status": "MEASURED" if valid else "NONE",
            "roi_types_by_case": {item["case_id"]: item["roi_types"] for item in valid},
            "mean_text_like_ratio": (
                round(
                    sum(float(value) for value in text_ratios if _finite_number(value) is not None)
                    / sum(_finite_number(value) is not None for value in text_ratios),
                    8,
                )
                if any(_finite_number(value) is not None for value in text_ratios)
                else None
            ),
        },
        "color_risk": {
            "status": "MEASURED_FROM_BASELINE_TO_GT" if valid else "NONE",
            "mean_delta_e76": round(sum(color_mean) / len(color_mean), 8) if color_mean else None,
            "maximum_p95_delta_e76": max(color_p95) if color_p95 else None,
        },
        "alpha_risk": {
            "status": "NOT_APPLICABLE_TARGET_CASES_RGB" if valid else "NONE",
            "alpha_e1_evidence": "NOT_APPLICABLE",
        },
        "operator_applicability": (
            "NOT_EVALUABLE_WITH_REQUIRED_REPLICATION" if valid else "NO_CASE_EVIDENCE"
        ),
        "commercial_safety_risk": (
            "FACE_IDENTITY_HIGH" if family == "BLUR" and valid
            else "LOGO_TEXT_STRUCTURE_HIGH" if family == "MULTI_RESIZE" and valid
            else "UNKNOWN_NO_CASE_EVIDENCE"
        ),
        "feasibility_pass": feasible,
        "case_evidence": evidence,
    }


def build_feasibility(manifest: dict[str, Any]) -> dict[str, Any]:
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_E1_CASE_COUNT:
        raise RuntimeError("E1_CASE_COUNT_NOT_16")
    rows = [
        _family_row(family, cases, matcher)
        for family, matcher in FAMILY_MATCHERS.items()
    ]
    feasible = [row for row in rows if row["feasibility_pass"]]
    return {
        "version": FEASIBILITY_VERSION,
        "status": (
            "PASS" if feasible else "INSUFFICIENT_REAL_EVALUATION_EVIDENCE"
        ),
        "minimum_real_holdout_cases": MINIMUM_REAL_HOLDOUT_CASES,
        "e1_manifest_path": E1_MANIFEST.relative_to(REPO_ROOT).as_posix(),
        "e1_manifest_sha256": sha256_file(E1_MANIFEST),
        "e1_case_count": len(cases),
        "e1_gt_pixels_read_for_parameter_tuning": False,
        "holdout_used_for_tuning": False,
        "synthetic_holdout_created": False,
        "families": rows,
        "feasible_families": [row["family"] for row in feasible],
        "failure_stage": None if feasible else "FEASIBILITY",
        "blocker": None if feasible else "INSUFFICIENT_REAL_EVALUATION_EVIDENCE",
    }


def build_target_selection(feasibility: dict[str, Any]) -> dict[str, Any]:
    feasible = list(feasibility.get("feasible_families") or [])
    return {
        "version": TARGET_SELECTION_VERSION,
        "status": "PASS" if len(feasible) == 1 else "UNRESOLVED",
        "selection_rule": (
            "REAL_HOLDOUT_GTE_2_AND_REFERENCE_EVIDENCE_GTE_2_THEN_UNIQUE_STRUCTURED_SELECTION"
        ),
        "weighted_score_used": False,
        "target_degradation_family": feasible[0] if len(feasible) == 1 else "UNRESOLVED",
        "selection_evidence": (
            "UNIQUE_FEASIBLE_FAMILY" if len(feasible) == 1
            else "NO_FAMILY_MEETS_REAL_HOLDOUT_GTE_2" if not feasible
            else "MULTIPLE_FEASIBLE_FAMILIES_REQUIRE_STRUCTURED_RESOLUTION"
        ),
        "development_authorized": len(feasible) == 1,
    }


def _summary(
    feasibility: dict[str, Any],
    selection: dict[str, Any],
    protected: dict[str, Any],
    test_record: dict[str, Any] | None = None,
    regression_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = {row["family"]: row for row in feasibility["families"]}
    tests = (
        f"V3_FROM_EXECUTION_RECORD:{test_record['tests_passed']}/{test_record['tests_total']}:{test_record['status']}"
        if test_record
        else "PENDING_TEST_EXECUTION_RECORD"
    )
    regression = (
        f"HD_CORE_FROM_EXECUTION_RECORD:{regression_record['tests_passed']}/{regression_record['tests_total']}:{regression_record['status']}"
        if regression_record
        else "PENDING_HD_CORE_REGRESSION_RECORD"
    )
    return {
        "artifact_version": ARTIFACT_VERSION,
        "status": "PASS_WITH_TECHNICAL_CONCLUSION",
        "version": VERSION,
        "line": LINE,
        "task_id": TASK_ID,
        "model_plan": "SELF_DEVELOPED_NON_GENERATIVE_SOURCE_RECOVERY",
        "formal_baseline": "PILLOW_LANCZOS",
        "external_enhancement_model": "NONE",
        "model_download": "NO",
        "model_inference": "NO",
        "model_benchmark": "NO",
        "blur_valid_cases": rows["BLUR"]["valid_case_count"],
        "blur_gt_cases": rows["BLUR"]["gt_available_count"],
        "blur_real_holdout_cases": rows["BLUR"]["real_holdout_count"],
        "multi_resize_valid_cases": rows["MULTI_RESIZE"]["valid_case_count"],
        "multi_resize_gt_cases": rows["MULTI_RESIZE"]["gt_available_count"],
        "multi_resize_real_holdout_cases": rows["MULTI_RESIZE"]["real_holdout_count"],
        "blur_multi_resize_valid_cases": rows["BLUR_MULTI_RESIZE"]["valid_case_count"],
        "blur_multi_resize_gt_cases": rows["BLUR_MULTI_RESIZE"]["gt_available_count"],
        "blur_multi_resize_real_holdout_cases": rows["BLUR_MULTI_RESIZE"]["real_holdout_count"],
        "v3_feasibility": feasibility["status"],
        "target_degradation_family": selection["target_degradation_family"],
        "target_family_selection_evidence": selection["selection_evidence"],
        "source_recovery_operator_v3": "NOT_DEVELOPED_FEASIBILITY_GATE_STOP",
        "operator_selection_evidence": "NOT_APPLICABLE_FEASIBILITY_GATE_STOP",
        "raw_proposal_source_binding": "NOT_CREATED_FEASIBILITY_GATE_STOP",
        "recovery_direction_rule": (
            "CANDIDATE_TO_GT_ERROR_LT_BASELINE_TO_GT_ERROR_REQUIRED"
        ),
        "sharpness_hf_gain_rule": "NOT_RECOVERY_PROOF",
        "calibration_set": "NOT_CREATED_FEASIBILITY_GATE_STOP",
        "holdout_used_for_tuning": False,
        "controlled_gate": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "controlled_mild_recovery_direction": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "controlled_moderate_recovery_direction": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "controlled_hard_safety": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "raw_proposal_recovery_direction": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "pre_bounding_gain_evidence": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "post_bounding_gain_evidence": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "gain_loss_stage": "NOT_APPLICABLE_FEASIBILITY_GATE_STOP",
        "threshold_provenance_status": "NOT_CREATED_FEASIBILITY_GATE_STOP",
        "runtime_authorization": "NOT_CREATED_FEASIBILITY_GATE_STOP",
        "uncalibrated_parameter_policy": "NO_OP_IF_OPERATOR_EXISTS",
        "invalid_runtime_authorization_policy": "NO_OP_IF_OPERATOR_EXISTS",
        "nonfinite_parameter_policy": "FAIL_CLOSED_NOT_IDENTITY_ELIGIBLE",
        "high_frequency_budget_status": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "overshoot_control_status": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "halo_ringing_suppression_status": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "text_structure_protection_status": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "color_lock_status": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "alpha_lock_status": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "determinism": "NOT_APPLICABLE_NO_CANDIDATE",
        "candidate_id": None,
        "e4k_02_connected": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "controlled_pass_e4k_02_policy": "REQUIRED_IF_REACHED_NOT_REACHED",
        "e1_02_connected": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "e1_cases_replayed": "0/16",
        "target_family_hard_safety_pass": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "target_family_quality_gain_proven_count": 0,
        "target_family_quality_gain_not_proven_count": 0,
        "target_family_quality_gain_rejected_count": 0,
        "target_family_stable_gain": "NOT_PROVEN",
        "non_target_no_op_cases": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "non_target_no_op_policy": "REQUIRED_IF_E1_REACHED_NOT_REACHED",
        "no_op_false_positive_gain_count": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "non_target_new_hard_safety_failure_count": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "oversharpen_count": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "halo_ringing_count": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "white_edge_count": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "black_edge_count": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "text_damage_count": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "color_failure_count": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "alpha_failure_count": "NOT_RUN_FEASIBILITY_GATE_STOP",
        "alpha_e1_evidence": "NOT_APPLICABLE",
        "human_review_status": "NOT_TRIGGERED_NO_E1_CANDIDATE",
        "real_4k_quality_gain": "NOT_PROVEN",
        "tests": tests,
        "regression": regression,
        "artifact_path": OUTPUT_ROOT.relative_to(REPO_ROOT).as_posix(),
        "artifact_integrity": "PASS",
        "formal_4k_pipeline_changed": protected["formal_4k_pipeline_changed"],
        "api_4k_changed": protected["api_4k_changed"],
        "product_version_changed": protected["product_version_changed"],
        "e1_01_changed": protected["e1_01_changed"],
        "e1_02_changed": protected["e1_02_changed"],
        "e4k_02_frozen_artifact_changed": protected[
            "e4k_02_frozen_artifact_changed"
        ],
        "failure_stage": "FEASIBILITY",
        "blocker": "INSUFFICIENT_REAL_EVALUATION_EVIDENCE",
        "stop_v3_operator": "YES",
        "stop_e4k_04": "YES",
        "ready_for_e4k_05": "NO",
        "next": (
            "KEEP_PILLOW_LANCZOS; REOPEN_ONLY_WITH_NEW_ALGORITHM_EVIDENCE_OR_"
            "NEW_VALID_DATASET_OR_NEW_LEGAL_MODEL_OR_NEW_HARDWARE_CAPABILITY"
        ),
        "completed_at_utc": _utc_now(),
    }


def _write_integrity_manifest(root: Path) -> dict[str, Any]:
    destination = root / "integrity_manifest.json"
    files = [
        path
        for path in sorted(root.rglob("*"), key=lambda item: str(item).lower())
        if path.is_file() and path.resolve() != destination.resolve()
    ]
    entries = [
        {
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in files
    ]
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    result = {
        "version": "E4K04_V3_ARTIFACT_INTEGRITY_V1",
        "status": "PASS",
        "file_count_excluding_manifest": len(entries),
        "tree_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "files": entries,
    }
    _write_json(destination, result)
    return result


def _refresh_summary_and_integrity(root: Path) -> dict[str, Any]:
    feasibility = _read_json(root / "feasibility" / "e1_target_family_feasibility.json")
    selection = _read_json(
        root / "target_family_selection" / "target_family_selection_v3.json"
    )
    protected = (_read_json(root / "validation" / "protected_scope.json").get("after") or {})
    test_path = root / "validation" / "test_execution.json"
    regression_path = root / "validation" / "hd_core_regression_execution.json"
    test_record = _read_json(test_path) if test_path.is_file() else None
    regression_record = _read_json(regression_path) if regression_path.is_file() else None
    summary = _summary(feasibility, selection, protected, test_record, regression_record)
    _write_json(root / "summary.json", summary)
    integrity = _write_integrity_manifest(root)
    return {"summary": summary, "integrity": integrity}


def validate_artifact(root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    root = Path(root).resolve()
    failures: list[str] = []
    required = {
        "FEASIBILITY_MISSING": root / "feasibility" / "e1_target_family_feasibility.json",
        "TARGET_SELECTION_MISSING": root / "target_family_selection" / "target_family_selection_v3.json",
        "PROTECTED_SCOPE_MISSING": root / "validation" / "protected_scope.json",
        "SUMMARY_MISSING": root / "summary.json",
        "INTEGRITY_MANIFEST_MISSING": root / "integrity_manifest.json",
    }
    for code, path in required.items():
        if not path.is_file():
            failures.append(code)
    if failures:
        return {"status": "BLOCKED", "failures": failures}
    manifest = _read_json(E1_MANIFEST)
    expected_feasibility = build_feasibility(manifest)
    stored_feasibility = _read_json(required["FEASIBILITY_MISSING"])
    if stored_feasibility != expected_feasibility:
        failures.append("FEASIBILITY_RECOMPUTE_MISMATCH")
    expected_selection = build_target_selection(expected_feasibility)
    if _read_json(required["TARGET_SELECTION_MISSING"]) != expected_selection:
        failures.append("TARGET_SELECTION_RECOMPUTE_MISMATCH")
    current_protected = protected_scope_state()
    stored_protected = _read_json(required["PROTECTED_SCOPE_MISSING"])
    if stored_protected.get("after") != current_protected:
        failures.append("PROTECTED_SCOPE_CHANGED_AFTER_RUN")
    if current_protected["status"] != "PASS":
        failures.append("PROTECTED_SCOPE_NOT_PASS")
    summary = _read_json(required["SUMMARY_MISSING"])
    expected_summary = {
        "status": "PASS_WITH_TECHNICAL_CONCLUSION",
        "task_id": TASK_ID,
        "v3_feasibility": "INSUFFICIENT_REAL_EVALUATION_EVIDENCE",
        "target_degradation_family": "UNRESOLVED",
        "source_recovery_operator_v3": "NOT_DEVELOPED_FEASIBILITY_GATE_STOP",
        "candidate_id": None,
        "holdout_used_for_tuning": False,
        "e1_cases_replayed": "0/16",
        "real_4k_quality_gain": "NOT_PROVEN",
        "failure_stage": "FEASIBILITY",
        "stop_v3_operator": "YES",
        "stop_e4k_04": "YES",
        "ready_for_e4k_05": "NO",
    }
    for field, value in expected_summary.items():
        if summary.get(field) != value:
            failures.append(f"SUMMARY_FIELD_MISMATCH:{field}")
    forbidden_directories = (
        "controlled_calibration",
        "threshold_provenance",
        "candidate_identity",
        "raw_proposal_evidence",
        "bounding_evidence",
        "candidate_runs",
        "e1_02_results",
        "roi_review_assets",
    )
    for name in forbidden_directories:
        if (root / name).exists():
            failures.append(f"FEASIBILITY_STOP_FORBIDDEN_ARTIFACT_PRESENT:{name}")
    test_path = root / "validation" / "test_execution.json"
    regression_path = root / "validation" / "hd_core_regression_execution.json"
    for path, version, code in (
        (test_path, TEST_EXECUTION_VERSION, "V3_TEST_EXECUTION"),
        (regression_path, REGRESSION_EXECUTION_VERSION, "HD_CORE_REGRESSION"),
    ):
        if path.is_file():
            record = _read_json(path)
            if record.get("version") != version:
                failures.append(f"{code}_VERSION_MISMATCH")
            if record.get("status") != "PASS":
                failures.append(f"{code}_NOT_PASS")
    expected_integrity = _read_json(required["INTEGRITY_MANIFEST_MISSING"])
    files = [
        path
        for path in sorted(root.rglob("*"), key=lambda item: str(item).lower())
        if path.is_file() and path.resolve() != required["INTEGRITY_MANIFEST_MISSING"].resolve()
    ]
    entries = [
        {
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in files
    ]
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    tree_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if len(entries) != expected_integrity.get("file_count_excluding_manifest"):
        failures.append("FILE_COUNT_MISMATCH")
    if tree_sha != expected_integrity.get("tree_sha256"):
        failures.append("TREE_SHA256_MISMATCH")
    return {
        "status": "PASS" if not failures else "BLOCKED",
        "failures": failures,
        "file_count": len(entries),
        "tree_sha256": tree_sha,
        "v3_feasibility": expected_feasibility["status"],
        "target_degradation_family": expected_selection["target_degradation_family"],
        "e1_cases_replayed": summary.get("e1_cases_replayed"),
        "real_4k_quality_gain": summary.get("real_4k_quality_gain"),
        "stop_e4k_04": summary.get("stop_e4k_04"),
    }


def run_feasibility(root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    before = protected_scope_state()
    if before["status"] != "PASS":
        raise RuntimeError("PROTECTED_SCOPE_NOT_PASS_AT_START")
    manifest = _read_json(E1_MANIFEST)
    feasibility = build_feasibility(manifest)
    selection = build_target_selection(feasibility)
    if feasibility["status"] != "INSUFFICIENT_REAL_EVALUATION_EVIDENCE":
        raise RuntimeError("V3_DEVELOPMENT_REQUIRES_SEPARATE_AUTHORIZED_PATH")
    _write_json(root / "feasibility" / "e1_target_family_feasibility.json", feasibility)
    _write_json(
        root / "target_family_selection" / "target_family_selection_v3.json",
        selection,
    )
    after = protected_scope_state()
    _write_json(root / "validation" / "protected_scope.json", {"before": before, "after": after})
    if after["status"] != "PASS":
        raise RuntimeError("PROTECTED_SCOPE_CHANGED_DURING_V3_FEASIBILITY")
    refreshed = _refresh_summary_and_integrity(root)
    validation = validate_artifact(root)
    if validation["status"] != "PASS":
        raise RuntimeError(f"V3_FEASIBILITY_ARTIFACT_INVALID:{validation['failures']}")
    return {**refreshed, "validation": validation}


def _run_suite(suite: unittest.TestSuite) -> dict[str, Any]:
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
    failed = len(result.failures) + len(result.errors) + len(result.unexpectedSuccesses)
    skipped = len(result.skipped)
    return {
        "status": "PASS" if failed == 0 and skipped == 0 else "FAIL",
        "tests_total": result.testsRun,
        "tests_passed": result.testsRun - failed - skipped,
        "tests_failed": failed,
        "tests_skipped": skipped,
        "runner_output": stream.getvalue().strip(),
    }


def record_v3_tests(root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    from tests.hd_core import test_source_recovery_v3

    result = _run_suite(
        unittest.defaultTestLoader.loadTestsFromModule(test_source_recovery_v3)
    )
    record = {
        "version": TEST_EXECUTION_VERSION,
        **result,
        "executed_at_utc": _utc_now(),
    }
    _write_json(root / "validation" / "test_execution.json", record)
    _refresh_summary_and_integrity(root)
    return record


def record_hd_core_regression(root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(REPO_ROOT / "tests" / "hd_core"),
        pattern="test_*.py",
        top_level_dir=str(REPO_ROOT),
    )
    result = _run_suite(suite)
    record = {
        "version": REGRESSION_EXECUTION_VERSION,
        **result,
        "executed_at_utc": _utc_now(),
    }
    _write_json(root / "validation" / "hd_core_regression_execution.json", record)
    _refresh_summary_and_integrity(root)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=("run", "validate", "record-tests", "record-regression"),
    )
    args = parser.parse_args()
    if args.phase == "run":
        result = run_feasibility()
    elif args.phase == "validate":
        result = validate_artifact()
    elif args.phase == "record-tests":
        result = record_v3_tests()
    else:
        result = record_hd_core_regression()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    status = result.get("status", (result.get("validation") or {}).get("status"))
    return 1 if status in {"FAIL", "BLOCKED"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
