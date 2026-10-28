from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.hd_core.candidate_framework import (
    ACTUAL_RUN_BINDING_VERSION,
    COMPARISON_SURFACE_VERSION,
    CONTROL_FRAMEWORK,
    FRAMEWORK_VERSION,
    REPLAY_BINDING_AUTHORITY,
    REVIEW,
    CandidateDefinition,
    E102EvaluationContext,
    identity_test_candidate,
    run_4k_candidate,
    sha256_file,
)
from tools.experiments.e1_01_real_information_baseline import (
    OUTPUT_ROOT as E1_01_ROOT,
    atomic_write_json,
    directory_state,
    relative_path,
    validate_manifest,
)
from tools.experiments.e1_02_quality_delivery_gate import OUTPUT_ROOT as E1_02_ROOT


OUTPUT_ROOT = REPO_ROOT / "artifacts" / "e4k_02_candidate_framework_v1"
E1_01_MANIFEST = E1_01_ROOT / "manifest.json"
ARTIFACT_VERSION = "E4K_02_CANDIDATE_FRAMEWORK_ARTIFACT_V1"

PROTECTED_FILES = {
    "formal_4k_executor": REPO_ROOT / "engine" / "image_processing_routing" / "four_k_v1.py",
    "api": REPO_ROOT / "main.py",
    "product_version": REPO_ROOT / "product_version.json",
    "e1_01_source": REPO_ROOT / "tools" / "experiments" / "e1_01_real_information_baseline.py",
    "e1_02_source": REPO_ROOT / "tools" / "experiments" / "e1_02_quality_delivery_gate.py",
}


class E4K02BuildError(RuntimeError):
    pass


def _protected_file_hashes() -> dict[str, dict[str, str]]:
    return {
        name: {"path": relative_path(path), "sha256": sha256_file(path)}
        for name, path in PROTECTED_FILES.items()
    }


def _resolve_reference(value: str | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def _tree_content_sha256(root: Path) -> tuple[int, int, str]:
    digest = hashlib.sha256()
    count = 0
    size = 0
    for path in sorted(
        item
        for item in root.rglob("*")
        if item.is_file() and item != root / "validation.json"
    ):
        relative = path.relative_to(root).as_posix()
        file_hash = sha256_file(path)
        file_size = path.stat().st_size
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\0")
        digest.update(str(file_size).encode("ascii"))
        digest.update(b"\n")
        count += 1
        size += file_size
    return count, size, digest.hexdigest()


def validate_artifact(
    root: Path = OUTPUT_ROOT,
    *,
    protected_before: dict[str, Any] | None = None,
    e1_01_before: dict[str, Any] | None = None,
    e1_02_before: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest_path = root / "framework_manifest.json"
    failures: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "status": "BLOCKED",
            "failures": [f"FRAMEWORK_MANIFEST_INVALID:{type(exc).__name__}"],
        }

    case_entries = manifest.get("case_results", [])
    if len(case_entries) != 16:
        failures.append("CASE_RESULT_COUNT_NOT_16")
    run_ids: set[str] = set()
    candidate_ids: set[str] = set()
    e1_case_ids: set[str] = set()
    states: list[str] = []
    quality_statuses: list[str] = []
    delivery_statuses: list[str] = []
    candidate_results: list[dict[str, Any]] = []
    reference_checks = 0
    reference_missing_count = 0
    source_binding_mismatch_count = 0
    baseline_binding_mismatch_count = 0
    actual_run_binding_pass_count = 0
    correct_pair_replay_count = 0

    for entry in case_entries:
        result_path = _resolve_reference(entry.get("candidate_result_path"))
        replay_path = _resolve_reference(entry.get("replay_result_path"))
        fallback_path = _resolve_reference(entry.get("fallback_result_path"))
        for label, path in (
            ("CANDIDATE_RESULT", result_path),
            ("REPLAY_RESULT", replay_path),
            ("FALLBACK_RESULT", fallback_path),
        ):
            reference_checks += 1
            if path is None or not path.is_file():
                reference_missing_count += 1
                failures.append(f"{label}_MISSING:{entry.get('e1_01_case_id')}")
        if result_path is None or not result_path.is_file():
            continue
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            failures.append(f"CANDIDATE_RESULT_JSON_INVALID:{entry.get('e1_01_case_id')}")
            continue
        candidate_results.append(result)
        run_ids.add(str(result.get("run_id")))
        candidate_ids.add(str(result.get("candidate_id")))
        e1_case_ids.add(str(entry.get("e1_01_case_id")))
        states.append(str(result.get("candidate_state")))
        quality_statuses.append(str(result.get("quality_gain_status")))
        delivery_statuses.append(str(result.get("delivery_status")))
        for label, value in (
            ("SOURCE", result.get("source_reference")),
            ("BASELINE", result.get("baseline_reference")),
            ("CANDIDATE", result.get("candidate_reference")),
        ):
            path = _resolve_reference(value)
            reference_checks += 1
            if path is None or not path.is_file():
                reference_missing_count += 1
                failures.append(f"{label}_REFERENCE_UNRESOLVED:{entry.get('e1_01_case_id')}")
        candidate_path = _resolve_reference(result.get("candidate_reference"))
        if candidate_path is not None and candidate_path.is_file():
            if sha256_file(candidate_path) != result.get("candidate_sha256"):
                failures.append(f"CANDIDATE_HASH_MISMATCH:{entry.get('e1_01_case_id')}")
        e1_result = result.get("e1_02_result") or {}
        e1_refs = e1_result.get("evidence_refs") or {}
        for label, value in (
            ("E1_COMPARISON_MANIFEST", e1_refs.get("comparison_manifest")),
            ("E1_FULL_IMAGE", e1_refs.get("full_image")),
            ("E1_ROI_RESULTS", e1_refs.get("roi_results")),
        ):
            path = _resolve_reference(value)
            reference_checks += 1
            if path is None or not path.is_file():
                reference_missing_count += 1
                failures.append(f"{label}_UNRESOLVED:{entry.get('e1_01_case_id')}")
        if result.get("candidate_class") != CONTROL_FRAMEWORK:
            failures.append(f"FRAMEWORK_CLASS_CHANGED:{entry.get('e1_01_case_id')}")
        if result.get("e1_02_candidate_class") != "CONTROL_ZERO":
            failures.append(f"E1_CONTROL_ADAPTER_INVALID:{entry.get('e1_01_case_id')}")
        if result.get("e1_02_replay_identity") != (result.get("e1_02_spec") or {}).get("replay_identity"):
            failures.append(f"REPLAY_IDENTITY_NOT_FROM_E1_02:{entry.get('e1_01_case_id')}")
        e1_spec = result.get("e1_02_spec") or {}
        actual_binding = result.get("actual_run_binding") or {}
        actual_source = result.get("actual_source_sha256")
        actual_baseline = result.get("actual_baseline_sha256")
        expected_source = e1_spec.get("source_binding_sha256")
        expected_baseline = e1_spec.get("baseline_binding_sha256")
        source_binding_valid = (
            isinstance(actual_source, str)
            and actual_source == result.get("source_sha256")
            and actual_source == expected_source
            and result.get("expected_source_binding_sha256") == expected_source
            and result.get("source_binding_match") is True
            and actual_binding.get("actual_source_sha256") == actual_source
            and actual_binding.get("expected_source_binding_sha256") == expected_source
            and actual_binding.get("source_binding_match") is True
        )
        baseline_binding_valid = (
            isinstance(actual_baseline, str)
            and actual_baseline == result.get("baseline_sha256")
            and actual_baseline == expected_baseline
            and result.get("expected_baseline_binding_sha256") == expected_baseline
            and result.get("baseline_binding_match") is True
            and actual_binding.get("actual_baseline_sha256") == actual_baseline
            and actual_binding.get("expected_baseline_binding_sha256") == expected_baseline
            and actual_binding.get("baseline_binding_match") is True
        )
        if not source_binding_valid:
            source_binding_mismatch_count += 1
            failures.append(f"SOURCE_BINDING_MISMATCH:{entry.get('e1_01_case_id')}")
        if not baseline_binding_valid:
            baseline_binding_mismatch_count += 1
            failures.append(f"BASELINE_BINDING_MISMATCH:{entry.get('e1_01_case_id')}")
        binding_gate_pass = (
            result.get("actual_run_binding_status") == "PASS"
            and actual_binding.get("binding_version") == ACTUAL_RUN_BINDING_VERSION
            and actual_binding.get("actual_run_binding_status") == "PASS"
            and source_binding_valid
            and baseline_binding_valid
        )
        if binding_gate_pass:
            actual_run_binding_pass_count += 1
        else:
            failures.append(f"ACTUAL_RUN_BINDING_GATE_NOT_PASS:{entry.get('e1_01_case_id')}")
        e1_replay_pass = (
            (result.get("e1_02_result") or {})
            .get("eligibility", {})
            .get("replay_binding_gate")
            == "PASS"
        )
        if not e1_replay_pass:
            failures.append(f"REPLAY_BINDING_GATE_NOT_PASS:{entry.get('e1_01_case_id')}")
        if binding_gate_pass and e1_replay_pass:
            correct_pair_replay_count += 1
        if result.get("output_validation", {}).get("status") != "PASS":
            failures.append(f"OUTPUT_VALIDATION_NOT_PASS:{entry.get('e1_01_case_id')}")
        if result.get("comparison_surface", {}).get("status") != "ELIGIBLE":
            failures.append(f"COMPARISON_SURFACE_NOT_ELIGIBLE:{entry.get('e1_01_case_id')}")
        if result.get("candidate_accepted") is not False or result.get("candidate_rejected") is not False:
            failures.append(f"CONTROL_REVIEW_SEMANTICS_INVALID:{entry.get('e1_01_case_id')}")

    expected_cases = {f"E1C{index:03d}" for index in range(1, 17)}
    if e1_case_ids != expected_cases:
        failures.append("E1_01_CASE_REUSE_INCOMPLETE")
    if len(run_ids) != 16:
        failures.append("RUN_IDS_NOT_UNIQUE")
    if len(candidate_ids) != 1:
        failures.append("CANDIDATE_IDENTITY_NOT_STABLE")
    if any(result.get("run_id") == result.get("candidate_id") for result in candidate_results):
        failures.append("CANDIDATE_RUN_ID_NOT_SEPARATE")
    if states != [REVIEW] * len(states):
        failures.append("CONTROL_FRAMEWORK_STATE_NOT_REVIEW")
    if any(value != "QUALITY_GAIN_NOT_PROVEN" for value in quality_statuses):
        failures.append("CONTROL_FRAMEWORK_FALSE_QUALITY_GAIN")
    if any(value != "REVIEW" for value in delivery_statuses):
        failures.append("CONTROL_FRAMEWORK_DELIVERY_NOT_REVIEW")

    protected_after = _protected_file_hashes()
    e1_01_after = directory_state(E1_01_ROOT)
    e1_02_after = directory_state(E1_02_ROOT)
    if protected_before is not None and protected_after != protected_before:
        failures.append("PROTECTED_SOURCE_CHANGED")
    if e1_01_before is not None and e1_01_after != e1_01_before:
        failures.append("E1_01_CHANGED")
    if e1_02_before is not None and e1_02_after != e1_02_before:
        failures.append("E1_02_ARTIFACT_CHANGED")

    product_proven_count = sum(
        result.get("candidate_class") == "PRODUCT"
        and result.get("quality_gain_status") == "QUALITY_GAIN_PROVEN"
        for result in candidate_results
    )
    json_file_count = 0
    json_parse_failure_count = 0
    for json_path in root.rglob("*.json"):
        if json_path == root / "validation.json":
            continue
        json_file_count += 1
        try:
            json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            json_parse_failure_count += 1
            failures.append(
                f"JSON_INVALID:{json_path.relative_to(root).as_posix()}"
            )
    statistics_consistent = (
        len(case_entries) == 16
        and len(candidate_results) == 16
        and len(run_ids) == 16
        and len(candidate_ids) == 1
        and source_binding_mismatch_count == 0
        and baseline_binding_mismatch_count == 0
        and actual_run_binding_pass_count == 16
        and correct_pair_replay_count == 16
        and json_parse_failure_count == 0
        and reference_missing_count == 0
    )
    if not statistics_consistent:
        failures.append("STATISTICS_INCONSISTENT")
    file_count, total_size, tree_hash = _tree_content_sha256(root)
    return {
        "validation_version": "E4K_02_CANDIDATE_FRAMEWORK_VALIDATION_V1",
        "status": "PASS" if not failures else "BLOCKED",
        "failures": failures,
        "checks": {
            "candidate_framework_created": manifest.get("framework_version") == FRAMEWORK_VERSION,
            "unique_candidate_entry": manifest.get("candidate_unified_entry")
            == "engine.hd_core.candidate_framework.run_4k_candidate",
            "candidate_identity_stable": len(candidate_ids) == 1,
            "run_identity_unique": len(run_ids) == 16,
            "candidate_run_identity_separate": not any(
                result.get("run_id") == result.get("candidate_id")
                for result in candidate_results
            ),
            "e1_02_is_only_replay_authority": manifest.get("replay_binding_authority")
            == REPLAY_BINDING_AUTHORITY,
            "actual_run_binding_gate": (
                source_binding_mismatch_count == 0
                and baseline_binding_mismatch_count == 0
                and actual_run_binding_pass_count == 16
            ),
            "parallel_replay_binding_created": False,
            "all_e1_01_cases_replayed": e1_case_ids == expected_cases,
            "all_outputs_valid": all(
                result.get("output_validation", {}).get("status") == "PASS"
                for result in candidate_results
            ),
            "all_comparison_surfaces_eligible": all(
                result.get("comparison_surface", {}).get("status") == "ELIGIBLE"
                for result in candidate_results
            ),
            "all_real_e1_02_evaluations_complete": all(
                (result.get("e1_02_result") or {}).get("evaluation_status") == "COMPLETE"
                for result in candidate_results
            ),
            "all_replay_bindings_pass": all(
                (result.get("e1_02_result") or {}).get("eligibility", {}).get(
                    "replay_binding_gate"
                )
                == "PASS"
                for result in candidate_results
            ) and correct_pair_replay_count == 16,
            "control_to_product_block": all(
                result.get("candidate_class") == CONTROL_FRAMEWORK
                and result.get("e1_02_candidate_class") == "CONTROL_ZERO"
                and result.get("candidate_accepted") is False
                for result in candidate_results
            ),
            "product_quality_gain_proven_count_zero": product_proven_count == 0,
            "e1_01_unchanged": e1_01_before is None or e1_01_after == e1_01_before,
            "e1_02_semantics_unchanged": protected_before is None
            or protected_after["e1_02_source"] == protected_before["e1_02_source"],
            "e1_02_artifact_unchanged": e1_02_before is None or e1_02_after == e1_02_before,
            "formal_4k_pipeline_unchanged": protected_before is None
            or protected_after["formal_4k_executor"]
            == protected_before["formal_4k_executor"],
            "api_4k_unchanged": protected_before is None
            or protected_after["api"] == protected_before["api"],
            "product_version_unchanged": protected_before is None
            or protected_after["product_version"]
            == protected_before["product_version"],
            "all_references_resolved": not any("UNRESOLVED" in failure or "MISSING" in failure for failure in failures),
            "all_json_parseable": not any(
                failure.startswith("JSON_INVALID:") for failure in failures
            ),
            "statistics_consistent": statistics_consistent,
            "real_model_work_absent": True,
        },
        "statistics": {
            "e1_01_cases_replayed": len(e1_case_ids),
            "candidate_id_count": len(candidate_ids),
            "run_id_count": len(run_ids),
            "reference_checks": reference_checks,
            "reference_missing_count": reference_missing_count,
            "source_binding_mismatch_count": source_binding_mismatch_count,
            "baseline_binding_mismatch_count": baseline_binding_mismatch_count,
            "actual_run_binding_pass_count": actual_run_binding_pass_count,
            "correct_pair_replay_count": correct_pair_replay_count,
            "json_parse_failures": json_parse_failure_count,
            "product_candidate_quality_gain_proven_count": product_proven_count,
            "candidate_state_counts": {
                state: states.count(state) for state in sorted(set(states))
            },
            "json_file_count_excluding_validation": json_file_count,
            "artifact_file_count_excluding_validation": file_count,
            "artifact_total_size_bytes_excluding_validation": total_size,
            "artifact_tree_content_sha256_excluding_validation": tree_hash,
        },
        "protected_before": protected_before,
        "protected_after": protected_after,
        "e1_01_before": e1_01_before,
        "e1_01_after": e1_01_after,
        "e1_02_before": e1_02_before,
        "e1_02_after": e1_02_after,
        "product_candidate_quality_gain_proven_count": product_proven_count,
        "real_4k_quality_gain": "NOT_PROVEN",
        "ACTUAL_RUN_BINDING_GATE": (
            "PASS"
            if source_binding_mismatch_count == 0
            and baseline_binding_mismatch_count == 0
            and actual_run_binding_pass_count == 16
            else "FAIL"
        ),
        "SOURCE_BINDING_MISMATCH_COUNT": source_binding_mismatch_count,
        "BASELINE_BINDING_MISMATCH_COUNT": baseline_binding_mismatch_count,
        "CORRECT_PAIR_REPLAY_COUNT": correct_pair_replay_count,
        "JSON_PARSE_FAILURES": json_parse_failure_count,
        "REFERENCE_MISSING": reference_missing_count,
        "STATISTICS_CONSISTENT": "YES" if statistics_consistent else "NO",
        "artifact_integrity": "PASS" if not failures else "FAIL",
    }


def build(
    output_root: Path = OUTPUT_ROOT,
    manifest_path: Path = E1_01_MANIFEST,
) -> dict[str, Any]:
    root = output_root.expanduser().resolve()
    if root.exists():
        raise E4K02BuildError(f"OUTPUT_ROOT_ALREADY_EXISTS:{root}")
    validation = validate_manifest(manifest_path)
    if validation.get("status") != "PASS" or validation.get("case_count") != 16:
        raise E4K02BuildError("E1_01_VALIDATION_NOT_READY")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    protected_before = _protected_file_hashes()
    e1_01_before = directory_state(E1_01_ROOT)
    e1_02_before = directory_state(E1_02_ROOT)

    root.mkdir(parents=True)
    for name in (
        "candidate_runs",
        "candidate_results",
        "replay_results",
        "fallback_results",
    ):
        (root / name).mkdir()

    definition = CandidateDefinition(
        algorithm_id="IDENTITY_TEST_CANDIDATE",
        algorithm_version="V1",
        parameters={
            "operation": "BASELINE_BYTE_IDENTITY",
            "purpose": "FRAMEWORK_INTERFACE_AND_E1_02_INTEGRATION_ONLY",
        },
        backend_identity="PYTHON_SHUTIL",
        precision_identity="BYTE_EXACT",
    )
    case_entries: list[dict[str, Any]] = []
    for case in manifest["cases"]:
        case_id = case["case_id"]
        source = REPO_ROOT / case["input"]["path"]
        baseline = REPO_ROOT / case["safe_base"]["path"]
        result = run_4k_candidate(
            source,
            root / "candidate_runs",
            definition=definition,
            executor=identity_test_candidate,
            baseline_path=baseline,
            e1_02_context=E102EvaluationContext(manifest_path, case_id),
            runtime_context={
                "framework_version": FRAMEWORK_VERSION,
                "executor_identity": "identity_test_candidate",
                "artifact_build": ARTIFACT_VERSION,
                "e1_01_case_id": case_id,
            },
            execution_nonce=f"{ARTIFACT_VERSION}:{case_id}",
        )
        result_path = root / "candidate_results" / f"{case_id}.json"
        replay_path = root / "replay_results" / f"{case_id}.json"
        fallback_path = root / "fallback_results" / f"{case_id}.json"
        atomic_write_json(result_path, result)
        atomic_write_json(
            replay_path,
            {
                "e1_01_case_id": case_id,
                "run_id": result["run_id"],
                "candidate_id": result["candidate_id"],
                "replay_binding_authority": result["replay_binding_authority"],
                "e1_02_replay_identity": result["e1_02_replay_identity"],
                "actual_run_binding": result["actual_run_binding"],
                "e1_02_candidate_class_adapter": {
                    "framework_candidate_class": result["candidate_class"],
                    "e1_02_candidate_class": result["e1_02_candidate_class"],
                },
                "e1_02_spec": result["e1_02_spec"],
                "e1_02_result": result["e1_02_result"],
            },
        )
        atomic_write_json(
            fallback_path,
            {
                "e1_01_case_id": case_id,
                "run_id": result["run_id"],
                "candidate_state": result["candidate_state"],
                "safe_reference_selected": result["safe_reference_selected"],
                "safe_reference_path": result["baseline_reference"],
                "fallback_kind": result["fallback_kind"],
                "fallback_reason": result["fallback_reason"],
                "actual_run_binding_status": result[
                    "actual_run_binding_status"
                ],
                "actual_run_binding_reason": result[
                    "actual_run_binding_reason"
                ],
                "candidate_accepted": result["candidate_accepted"],
                "candidate_rejected": result["candidate_rejected"],
            },
        )
        case_entries.append(
            {
                "e1_01_case_id": case_id,
                "run_id": result["run_id"],
                "candidate_id": result["candidate_id"],
                "candidate_class": result["candidate_class"],
                "candidate_state": result["candidate_state"],
                "quality_gain_status": result["quality_gain_status"],
                "delivery_status": result["delivery_status"],
                "actual_run_binding_status": result[
                    "actual_run_binding_status"
                ],
                "candidate_result_path": relative_path(result_path),
                "replay_result_path": relative_path(replay_path),
                "fallback_result_path": relative_path(fallback_path),
            }
        )

    framework_manifest = {
        "artifact_version": ARTIFACT_VERSION,
        "framework_version": FRAMEWORK_VERSION,
        "status": "PENDING_VALIDATION",
        "version": "V0.5.7",
        "line": "E",
        "task_id": "E4K-02_4K_ENHANCEMENT_CANDIDATE_FRAMEWORK_V1",
        "experimental_only": True,
        "candidate_unified_entry": "engine.hd_core.candidate_framework.run_4k_candidate",
        "candidate_class": CONTROL_FRAMEWORK,
        "candidate_definition": definition.identity_contract(),
        "candidate_id": definition.candidate_id,
        "comparison_surface": COMPARISON_SURFACE_VERSION,
        "actual_run_binding_gate": ACTUAL_RUN_BINDING_VERSION,
        "replay_binding_authority": REPLAY_BINDING_AUTHORITY,
        "parallel_replay_binding_created": False,
        "e1_01_manifest": relative_path(manifest_path),
        "e1_01_manifest_sha256": sha256_file(manifest_path),
        "e1_01_case_reuse": "ALL_VALID_CASES",
        "e1_01_cases_replayed": len(case_entries),
        "e1_02_integration": "REAL_EVALUATE_CASE_NOT_MOCK",
        "e1_02_candidate_class_adapter": {
            "framework_candidate_class": CONTROL_FRAMEWORK,
            "e1_02_candidate_class": "CONTROL_ZERO",
            "semantics": "ZERO_GAIN_CONTROL_NOT_PRODUCT",
            "e1_02_gate_semantics_changed": False,
        },
        "model_plan": {
            "model_plan": "CANDIDATE_FRAMEWORK_ONLY",
            "formal_baseline": "PILLOW_LANCZOS",
            "experimental_model": "NONE",
            "model_download": False,
            "model_inference_run": False,
            "model_benchmark": False,
            "model_adopted": False,
            "rejected_models": ["FIDESR_OPENVINO"],
            "reference_only_models": [
                "TOPAZ_WONDER_3",
                "TOPAZ_GMP_V2",
                "TOPAZ_TRF",
                "TOPAZ_GFP",
                "TOPAZ_IRWN",
                "TOPAZ_GCLC",
                "TOPAZ_LDCLC",
                "TOPAZ_SSD",
            ],
        },
        "control_markers": [
            "CONTROL_FIXTURE_ONLY",
            "NOT_PRODUCT_CANDIDATE",
            "NOT_ENHANCEMENT_ALGORITHM",
            "NOT_PRODUCTION_EVIDENCE",
        ],
        "product_candidate_quality_gain_proven_count": 0,
        "real_4k_quality_gain": "NOT_PROVEN",
        "case_results": case_entries,
    }
    atomic_write_json(root / "framework_manifest.json", framework_manifest)
    draft_validation = validate_artifact(
        root,
        protected_before=protected_before,
        e1_01_before=e1_01_before,
        e1_02_before=e1_02_before,
    )
    framework_manifest["status"] = draft_validation["status"]
    framework_manifest["validation"] = relative_path(root / "validation.json")
    atomic_write_json(root / "framework_manifest.json", framework_manifest)
    artifact_validation = validate_artifact(
        root,
        protected_before=protected_before,
        e1_01_before=e1_01_before,
        e1_02_before=e1_02_before,
    )
    atomic_write_json(root / "validation.json", artifact_validation)
    if artifact_validation["status"] != "PASS":
        raise E4K02BuildError(
            "ARTIFACT_VALIDATION_BLOCKED:" + ";".join(artifact_validation["failures"])
        )
    return {
        "status": "PASS",
        "framework_version": FRAMEWORK_VERSION,
        "candidate_id": definition.candidate_id,
        "e1_01_cases_replayed": len(case_entries),
        "product_candidate_quality_gain_proven_count": 0,
        "real_4k_quality_gain": "NOT_PROVEN",
        "artifact_path": relative_path(root),
        "artifact_integrity": artifact_validation["artifact_integrity"],
        "source_binding_mismatch_count": artifact_validation[
            "SOURCE_BINDING_MISMATCH_COUNT"
        ],
        "baseline_binding_mismatch_count": artifact_validation[
            "BASELINE_BINDING_MISMATCH_COUNT"
        ],
        "correct_pair_replay_count": artifact_validation[
            "CORRECT_PAIR_REPLAY_COUNT"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build E4K-02 experimental Candidate Framework evidence."
    )
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--manifest", type=Path, default=E1_01_MANIFEST)
    args = parser.parse_args()
    try:
        result = build(args.output_root, args.manifest)
    except Exception as exc:
        print(
            json.dumps(
                {"status": "BLOCKED", "error": f"{type(exc).__name__}:{exc}"},
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
