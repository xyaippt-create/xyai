"""Run the eligible E4K-03 Swin2SR candidate through smoke and E1-02.

This tool is experimental-only.  It writes only under E4K-03 artifact roots,
uses the frozen E1-01 source/Safe Base pairs, and delegates every quality and
delivery decision to the existing E1-02 gate through ``run_4k_candidate``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.hd_core.candidate_framework import (  # noqa: E402
    E102EvaluationContext,
    build_candidate_identity,
    run_4k_candidate,
    sha256_file,
)
from engine.hd_core.swin2sr_candidate import (  # noqa: E402
    MODEL_ID,
    Swin2SRCandidateAdapter,
    build_swin2sr_definition,
)


TASK_ID = "E4K-03_FIRST_REAL_ENHANCEMENT_CANDIDATE"
REUSE_CORRECTION_TASK_ID = "E4K-03_REUSE_CORRECTION_03"
ARTIFACT_VERSION = "E4K_03_FIRST_REAL_CANDIDATE_ARTIFACT_V1"
CANDIDATE_SELECTION_CONTRACT = "CANDIDATE_SELECTION_CONTRACT_V1"
SELECTION_EVIDENCE_FINITE_GATE = "SELECTION_EVIDENCE_FINITE_GATE_V1"
CANDIDATE_SELECTION_PRIORITY = (
    ("quality_gain_proven_case_count", "DESC"),
    ("mandatory_gate_complete_case_count", "DESC"),
    ("hard_safety_fail_count", "ASC"),
    ("quality_gain_rejected_case_count", "ASC"),
    ("commercial_high_risk_failure_count", "ASC"),
    ("human_review_confirmed_better_count", "DESC"),
    ("observed_runtime_cost_seconds", "ASC"),
)
STALE_ACTIVE_MEMORY_FIELDS = {
    "observed_peak_rss_bytes",
    "peak_memory",
    "true_peak_memory_bytes",
}
E1_MANIFEST = REPO_ROOT / "artifacts" / "e1_01_real_information_baseline_v1" / "manifest.json"
ELIGIBILITY_ROOT = REPO_ROOT / "artifacts" / "e4k_03_model_eligibility"
MODEL_ROOT = (
    REPO_ROOT
    / "artifacts"
    / "e4k_03_models"
    / "caidas__swin2SR-realworld-sr-x4-64-bsrgan-psnr"
)
CANDIDATES_ROOT = REPO_ROOT / "artifacts" / "e4k_03_candidates"
COMPARISON_PATH = REPO_ROOT / "artifacts" / "E4K_03_CANDIDATE_COMPARISON.json"
SMOKE_CASE_ID = "E1C015"
SMOKE_REPEAT_COUNT = 2
SMOKE_MAX_INFERENCE_SECONDS_PER_RUN = 120.0
SMOKE_MAX_PROCESS_RSS_BYTES = 8 * 1024**3


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def _resolve_reference(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def _case_by_id(manifest: dict[str, Any], case_id: str) -> dict[str, Any]:
    matches = [case for case in manifest["cases"] if case["case_id"] == case_id]
    if len(matches) != 1:
        raise RuntimeError(f"CASE_ID_NOT_UNIQUE_OR_MISSING:{case_id}")
    return matches[0]


def _eligibility_record_path() -> Path:
    return (
        ELIGIBILITY_ROOT
        / "records"
        / "caidas__swin2SR-realworld-sr-x4-64-bsrgan-psnr.json"
    )


def _load_frozen_candidate() -> tuple[dict[str, Any], Any, Any, Path]:
    eligibility = _read_json(_eligibility_record_path())
    if eligibility.get("model_id") != MODEL_ID:
        raise RuntimeError("ELIGIBILITY_MODEL_ID_MISMATCH")
    if eligibility.get("model_eligibility") != "PASS":
        raise RuntimeError("MODEL_ELIGIBILITY_NOT_PASS")
    model_path = _resolve_reference(eligibility["model_file"])
    if not model_path.is_file():
        raise RuntimeError(f"MODEL_FILE_MISSING:{model_path}")
    if sha256_file(model_path) != eligibility.get("model_sha256"):
        raise RuntimeError("MODEL_SHA256_CHANGED_AFTER_ELIGIBILITY")
    revision_prefix = "huggingface_revision_"
    version = str(eligibility.get("model_version") or "")
    if not version.startswith(revision_prefix):
        raise RuntimeError("MODEL_REVISION_NOT_FROZEN")
    revision = version[len(revision_prefix) :]
    definition = build_swin2sr_definition(model_path, revision=revision)
    adapter = Swin2SRCandidateAdapter(MODEL_ROOT)
    candidate_id, identity = build_candidate_identity(definition)
    return eligibility, definition, adapter, model_path


def _runtime_context() -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "backend": "PYTORCH_RESEARCH_RUNTIME",
        "device": "CPU",
        "precision": "FP32",
        "tile_core": 224,
        "tile_context": 16,
        "production_backend_proven": False,
    }


def _run_one(
    *,
    case: dict[str, Any],
    workspace: Path,
    definition: Any,
    adapter: Any,
    nonce: str,
) -> dict[str, Any]:
    return run_4k_candidate(
        REPO_ROOT / case["input"]["path"],
        workspace,
        definition=definition,
        executor=adapter,
        baseline_path=REPO_ROOT / case["safe_base"]["path"],
        e1_02_context=E102EvaluationContext(E1_MANIFEST, case["case_id"]),
        runtime_context=_runtime_context(),
        execution_nonce=nonce,
    )


def _runtime_for_result(result: dict[str, Any]) -> dict[str, Any]:
    run_dir = _resolve_reference(result["evidence_refs"]["run_directory"])
    runtime_path = run_dir / "candidate_runtime.json"
    if not runtime_path.is_file():
        if result.get("execution_status") == "COMPLETED":
            raise RuntimeError(f"CANDIDATE_RUNTIME_MISSING:{runtime_path}")
        return {
            "runtime_status": "MISSING_DUE_TO_EXECUTION_FAILURE",
            "runtime_path": _relative(runtime_path),
            "model_load_time_seconds": 0.0,
            "inference_time_seconds": 0.0,
            "total_processing_time_seconds": 0.0,
            "observed_peak_rss_bytes": 0,
            "input_pixels": 0,
            "output_pixels": 0,
            "tile_count": 0,
        }
    return _read_json(runtime_path)


def _observed_sampled_rss(runtime: dict[str, Any]) -> int:
    value = runtime.get(
        "observed_sampled_rss_max_bytes", runtime.get("observed_peak_rss_bytes")
    )
    if not isinstance(value, int) or value < 0:
        raise RuntimeError("OBSERVED_SAMPLED_RSS_INVALID")
    return value


def _build_runtime_summary(runtimes: list[dict[str, Any]]) -> dict[str, Any]:
    if not runtimes:
        raise RuntimeError("RUNTIME_RECORDS_EMPTY")
    return {
        "model_load_time_seconds": max(
            runtime["model_load_time_seconds"] for runtime in runtimes
        ),
        "inference_time_seconds_total": sum(
            runtime["inference_time_seconds"] for runtime in runtimes
        ),
        "total_processing_time_seconds": sum(
            runtime["total_processing_time_seconds"] for runtime in runtimes
        ),
        "observed_sampled_rss_max_bytes": max(
            _observed_sampled_rss(runtime) for runtime in runtimes
        ),
        "true_peak_memory": "NOT_PROVEN",
        "input_pixels_total": sum(runtime["input_pixels"] for runtime in runtimes),
        "output_pixels_total": sum(runtime["output_pixels"] for runtime in runtimes),
        "tile_count_total": sum(runtime["tile_count"] for runtime in runtimes),
    }


def _normalize_runtime_report(runtime: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(runtime)
    normalized["observed_sampled_rss_max_bytes"] = _observed_sampled_rss(runtime)
    normalized["true_peak_memory"] = "NOT_PROVEN"
    normalized.pop("observed_peak_rss_bytes", None)
    normalized.pop("peak_memory", None)
    return normalized


def _e4k_02_reporting_scope() -> dict[str, Any]:
    return {
        "e4k_02_artifact_changed": False,
        "e4k_02_control_semantics_changed": False,
        "e4k_02_shared_source_extended": True,
        "extended_source": "engine/hd_core/candidate_framework.py",
        "extension_reason": "E4K_03_REAL_PRODUCT_CANDIDATE_SUPPORT",
        "e1_02_gate_semantics_changed": False,
    }


def _selection_evidence_from_summary(summary: dict[str, Any]) -> dict[str, int | float]:
    quality = summary.get("quality_gain_counts") or {}
    safety = summary.get("hard_safety_counts") or {}
    category = summary.get("category_safety") or {}
    commercial_risk_fields = (
        "text_safety",
        "logo_structure_safety",
        "person_safety",
        "material_safety",
        "edge_artifact_safety",
        "color_safety",
        "alpha_safety",
    )
    runtime = summary.get("runtime") or {}
    return {
        "quality_gain_proven_case_count": int(
            quality.get("QUALITY_GAIN_PROVEN", 0)
        ),
        "mandatory_gate_complete_case_count": int(
            summary.get("mandatory_gate_complete_count", 0)
        ),
        "hard_safety_fail_count": int(safety.get("FAIL", 0)),
        "quality_gain_rejected_case_count": int(
            quality.get("QUALITY_GAIN_REJECTED", 0)
        ),
        "commercial_high_risk_failure_count": sum(
            category.get(field) == "FAIL" for field in commercial_risk_fields
        ),
        "human_review_confirmed_better_count": int(
            summary.get("human_review_confirmed_better_count", 0)
        ),
        "observed_runtime_cost_seconds": float(
            runtime.get("total_processing_time_seconds", 0.0)
        ),
    }


def _selection_key(row: dict[str, Any]) -> tuple[int | float, ...] | None:
    evidence = row.get("selection_evidence")
    if not isinstance(evidence, dict):
        return None
    values: list[int | float] = []
    for field, direction in CANDIDATE_SELECTION_PRIORITY:
        value = evidence.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            is_finite = math.isfinite(value)
        except (OverflowError, TypeError):
            return None
        if not is_finite or value < 0:
            return None
        values.append(-value if direction == "DESC" else value)
    return tuple(values)


def _unresolved_adopted_selection(
    adopted_count: int,
    *,
    reason: str,
    evidence_status: str,
) -> dict[str, Any]:
    evidence_invalid = evidence_status == "INVALID_OR_NONFINITE"
    return {
        "candidate_selection_contract": CANDIDATE_SELECTION_CONTRACT,
        "selection_evidence_finite_gate": SELECTION_EVIDENCE_FINITE_GATE,
        "selection_evidence_status": evidence_status,
        "status": (
            "BLOCKED_WITH_SELECTION_REVIEW_REQUIRED"
            if evidence_invalid
            else "PASS_WITH_SELECTION_REVIEW_REQUIRED"
        ),
        "best_candidate": "UNRESOLVED_MULTI_ADOPT",
        "best_candidate_reason": reason,
        "model_adoption": "NEEDS_SELECTION_REVIEW",
        "adopted_candidate_count": adopted_count,
        "real_4k_quality_gain": "NOT_PROVEN" if evidence_invalid else "PROVEN",
    }


def _derive_candidate_comparison_outcome(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    adopted = [
        row
        for row in rows
        if row.get("eligibility") == "PASS"
        and row.get("final_status") == "ADOPT"
        and isinstance(row.get("candidate_id"), str)
        and bool(str(row["candidate_id"]).strip())
    ]
    if not adopted:
        return {
            "candidate_selection_contract": CANDIDATE_SELECTION_CONTRACT,
            "selection_evidence_finite_gate": SELECTION_EVIDENCE_FINITE_GATE,
            "selection_evidence_status": "NOT_APPLICABLE",
            "status": "PASS_WITH_TECHNICAL_CONCLUSION",
            "best_candidate": "NONE",
            "best_candidate_reason": (
                "NO_CANDIDATE_SATISFIED_ALL_SAFETY_GAIN_REVIEW_AND_DELIVERY_GATES"
            ),
            "model_adoption": "NONE",
            "adopted_candidate_count": 0,
            "real_4k_quality_gain": "NOT_PROVEN",
        }
    ranked = [(_selection_key(row), row) for row in adopted]
    if any(key is None for key, _row in ranked):
        return _unresolved_adopted_selection(
            len(adopted),
            reason="INVALID_OR_NONFINITE_SELECTION_EVIDENCE",
            evidence_status="INVALID_OR_NONFINITE",
        )
    if len(adopted) == 1:
        best = adopted[0]
    else:
        best_key = min(key for key, _row in ranked if key is not None)
        winners = [row for key, row in ranked if key == best_key]
        if len(winners) != 1:
            return _unresolved_adopted_selection(
                len(adopted),
                reason="NO_EVIDENCE_BASED_UNIQUE_WINNER",
                evidence_status="VALID_FINITE",
            )
        best = winners[0]
    return {
        "candidate_selection_contract": CANDIDATE_SELECTION_CONTRACT,
        "selection_evidence_finite_gate": SELECTION_EVIDENCE_FINITE_GATE,
        "selection_evidence_status": "VALID_FINITE",
        "status": "PASS",
        "best_candidate": best["candidate_id"],
        "best_candidate_reason": (
            "ONLY_ADOPT_ELIGIBLE_CANDIDATE"
            if len(adopted) == 1
            else "EVIDENCE_PRIORITY_UNIQUE_WINNER"
        ),
        "model_adoption": best["candidate_id"],
        "adopted_candidate_count": len(adopted),
        "real_4k_quality_gain": "PROVEN",
    }


def _apply_dynamic_summary_reporting(summary: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(summary)
    normalized["runtime"] = _normalize_runtime_report(summary["runtime"])
    normalized["selection_evidence"] = _selection_evidence_from_summary(normalized)
    outcome = _derive_candidate_comparison_outcome(
        [
            {
                "candidate_id": summary.get("candidate_id"),
                "model_id": summary.get("model_id"),
                "eligibility": "PASS",
                "final_status": summary.get("model_status"),
                "selection_evidence": normalized["selection_evidence"],
            }
        ]
    )
    normalized.update(outcome)
    normalized.update(_e4k_02_reporting_scope())
    return normalized


def _initial_manifest(
    *, candidate_id: str, identity: dict[str, Any], eligibility: dict[str, Any]
) -> dict[str, Any]:
    return {
        "artifact_version": ARTIFACT_VERSION,
        "status": "IN_PROGRESS",
        "created_at_utc": _utc_now(),
        "task_id": TASK_ID,
        "version": "V0.5.7",
        "line": "E",
        "candidate_id": candidate_id,
        "candidate_identity_contract": identity,
        "model_eligibility_record": _relative(_eligibility_record_path()),
        "model_eligibility": eligibility["model_eligibility"],
        "formal_baseline": "PILLOW_LANCZOS",
        "e1_01_manifest": _relative(E1_MANIFEST),
        "e1_01_case_policy": "ALL_16_VALID_CASES_AFTER_SMOKE_PASS",
        "quality_authority": "EXISTING_E1_02_ONLY",
        "human_review_policy": "REAL_REVIEW_REQUIRED; AUTOMATED_FIXTURE_FORBIDDEN",
        "production_backend_status": "NOT_PROVEN",
        "formal_production": False,
        "smoke_contract": {
            "case_id": SMOKE_CASE_ID,
            "repeat_count": SMOKE_REPEAT_COUNT,
            "maximum_inference_seconds_per_run": SMOKE_MAX_INFERENCE_SECONDS_PER_RUN,
            "maximum_process_rss_bytes": SMOKE_MAX_PROCESS_RSS_BYTES,
            "quality_adoption_authority": False,
            "hard_safety_authority": "E1_02_BENCHMARK_NOT_SMOKE_SHORTCUT",
        },
        "protected_scope": {
            "formal_4k_pipeline_changed": False,
            "api_4k_changed": False,
            "product_version_changed": False,
            "e1_01_changed": False,
            "e1_02_changed": False,
            "e4k_02_artifact_changed": False,
        },
    }


def _update_eligibility_usage(*, inference: bool, benchmark: bool) -> None:
    record_path = _eligibility_record_path()
    record = _read_json(record_path)
    record["model_inference_run"] = inference
    record["model_benchmark"] = benchmark
    _write_json(record_path, record)
    summary_path = ELIGIBILITY_ROOT / "summary.json"
    summary = _read_json(summary_path)
    summary["model_inference_run"] = 1 if inference else 0
    summary["models_inference_run"] = 1 if inference else 0
    summary["models_benchmarked"] = 1 if benchmark else 0
    summary["phase"] = (
        "BENCHMARK_COMPLETE"
        if benchmark
        else "SMOKE_COMPLETE" if inference else summary.get("phase")
    )
    _write_json(summary_path, summary)


def run_smoke() -> dict[str, Any]:
    eligibility, definition, adapter, _ = _load_frozen_candidate()
    candidate_id, identity = build_candidate_identity(definition)
    root = CANDIDATES_ROOT / candidate_id
    if root.exists():
        raise RuntimeError(f"CANDIDATE_ARTIFACT_ALREADY_EXISTS:{root}")
    for name in (
        "runtime",
        "case_results",
        "roi_results",
        "comparison_assets",
        "e1_02_results",
        "validation",
    ):
        (root / name).mkdir(parents=True, exist_ok=False)
    _write_json(
        root / "candidate_manifest.json",
        _initial_manifest(
            candidate_id=candidate_id, identity=identity, eligibility=eligibility
        ),
    )

    manifest = _read_json(E1_MANIFEST)
    case = _case_by_id(manifest, SMOKE_CASE_ID)
    results: list[dict[str, Any]] = []
    runtimes: list[dict[str, Any]] = []
    for index in range(1, SMOKE_REPEAT_COUNT + 1):
        print(f"SMOKE_START={index}/{SMOKE_REPEAT_COUNT}", flush=True)
        result = _run_one(
            case=case,
            workspace=root / "smoke_runs",
            definition=definition,
            adapter=adapter,
            nonce=f"E4K03_SMOKE_REPEAT_{index:02d}",
        )
        runtime = _runtime_for_result(result)
        results.append(result)
        runtimes.append(runtime)
        _write_json(root / "validation" / f"smoke_run_{index:02d}.json", result)
        _write_json(root / "runtime" / f"smoke_run_{index:02d}.json", runtime)
        print(
            "SMOKE_DONE="
            f"{index}/{SMOKE_REPEAT_COUNT};"
            f"EXECUTION={result['execution_status']};"
            f"SURFACE={(result.get('comparison_surface') or {}).get('status')};"
            f"SAFETY={result.get('safety_status')};"
            f"INFERENCE_SECONDS={runtime['inference_time_seconds']:.6f}",
            flush=True,
        )

    candidate_hashes = [result.get("candidate_sha256") for result in results]
    raw_color = [
        ((result.get("e1_02_result") or {}).get("safety_results") or {}).get(
            "raw_detection", {}
        )
        for result in results
    ]
    checks = {
        "model_load": all(runtime["model_load_time_seconds"] >= 0 for runtime in runtimes),
        "single_image_inference": all(
            result.get("execution_status") == "COMPLETED" for result in results
        ),
        "output_decodes": all(
            result["output_validation"]["checks"]["decode_success"] for result in results
        ),
        "expected_dimensions": all(
            (result.get("comparison_surface") or {}).get("checks", {}).get(
                "same_target_dimensions"
            )
            is True
            for result in results
        ),
        "deterministic_repeat": len(set(candidate_hashes)) == 1
        and None not in candidate_hashes,
        "memory_acceptable": all(
            _observed_sampled_rss(runtime) <= SMOKE_MAX_PROCESS_RSS_BYTES
            for runtime in runtimes
        ),
        "runtime_acceptable": all(
            runtime["inference_time_seconds"]
            <= SMOKE_MAX_INFERENCE_SECONDS_PER_RUN
            for runtime in runtimes
        ),
        "no_catastrophic_color_channel_error": all(
            not facts.get("global_color_shift", False)
            and not facts.get("local_color_shift", False)
            for facts in raw_color
        )
        and all(
            (result.get("comparison_surface") or {}).get("checks", {}).get(
                "compatible_channel_contract"
            )
            is True
            for result in results
        ),
        "alpha_contract": all(
            (result.get("comparison_surface") or {}).get("checks", {}).get(
                "compatible_alpha_contract"
            )
            is True
            for result in results
        ),
        "candidate_framework_accepts_output": all(
            (result.get("comparison_surface") or {}).get("status") == "ELIGIBLE"
            and (result.get("e1_02_result") or {}).get("evaluation_status")
            == "COMPLETE"
            for result in results
        ),
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    summary = {
        "artifact_version": ARTIFACT_VERSION,
        "phase": "SMOKE",
        "status": status,
        "candidate_id": candidate_id,
        "case_id": SMOKE_CASE_ID,
        "checks": checks,
        "candidate_sha256_repeats": candidate_hashes,
        "determinism_status": "PASS" if checks["deterministic_repeat"] else "FAIL",
        "hard_safety_observations_not_smoke_override": [
            result.get("safety_status") for result in results
        ],
        "quality_adoption_decision": "NOT_AUTHORIZED_BY_SMOKE",
        "runtime": _build_runtime_summary(runtimes),
        "benchmark_authorized": status == "PASS",
        "completed_at_utc": _utc_now(),
    }
    _write_json(root / "validation" / "smoke_summary.json", summary)
    manifest_record = _read_json(root / "candidate_manifest.json")
    manifest_record["smoke_test"] = summary
    manifest_record["status"] = "SMOKE_PASS" if status == "PASS" else "SMOKE_FAIL"
    _write_json(root / "candidate_manifest.json", manifest_record)
    _update_eligibility_usage(inference=True, benchmark=False)
    print(f"SMOKE_STATUS={status}", flush=True)
    print(f"CANDIDATE_ID={candidate_id}", flush=True)
    print(f"CANDIDATE_ROOT={root}", flush=True)
    return summary


def _category_status(values: Iterable[str]) -> str:
    items = list(values)
    if not items:
        return "NOT_APPLICABLE"
    if any(item in {"FAIL", "RISK", "TEXT_DEGRADED"} for item in items):
        return "FAIL"
    if any(
        item
        in {
            "REVIEW",
            "NEED_PROOF",
            "TEXT_RISK",
            "STABLE_OR_NOT_PROVEN",
        }
        for item in items
    ):
        return "NEED_PROOF"
    return "PASS"


def _aggregate_safety(
    cases: list[dict[str, Any]], results: list[dict[str, Any]]
) -> dict[str, str]:
    by_id = {case["case_id"]: case for case in cases}
    text: list[str] = []
    logo_structure: list[str] = []
    person: list[str] = []
    material: list[str] = []
    edge: list[str] = []
    color: list[str] = []
    alpha: list[str] = []
    for result in results:
        e1 = result.get("e1_02_result") or {}
        case_id = e1.get("e1_01_case_id")
        if case_id not in by_id:
            edge.append("FAIL")
            color.append("NEED_PROOF")
            continue
        case = by_id[case_id]
        safety = e1.get("safety_results") or {}
        raw = safety.get("raw_detection") or {}
        edge.append(
            "FAIL"
            if any(
                raw.get(name, False)
                for name in (
                    "blur",
                    "oversharpen",
                    "halo_or_ringing",
                    "high_frequency_anomaly",
                    "black_edge",
                    "white_edge",
                )
            )
            else "PASS"
        )
        color.append(
            "FAIL"
            if raw.get("global_color_shift", False)
            or raw.get("local_color_shift", False)
            else "PASS"
        )
        alpha_status = (safety.get("alpha") or {}).get("status")
        if alpha_status not in {None, "NOT_APPLICABLE"}:
            alpha.append(alpha_status)
        roi_types = {roi["roi_type"] for roi in case["roi"]}
        for roi in e1.get("roi_results") or []:
            roi_type = roi.get("roi_type")
            if roi_type in {"CHINESE_TEXT", "TEXT"}:
                text.append(roi.get("text_fidelity", "NEED_PROOF"))
            if roi_type == "LOGO":
                logo_structure.append(roi.get("text_fidelity", "NEED_PROOF"))
            if roi_type == "PRODUCT_STRUCTURE":
                logo_structure.append(roi.get("material_texture", "NEED_PROOF"))
            if roi_type == "MATERIAL":
                material.append(roi.get("material_texture", "NEED_PROOF"))
        if "FACE" in roi_types:
            person.append("NEED_PROOF")
    return {
        "text_safety": _category_status(text),
        "logo_structure_safety": _category_status(logo_structure),
        "person_safety": _category_status(person),
        "material_safety": _category_status(material),
        "edge_artifact_safety": _category_status(edge),
        "color_safety": _category_status(color),
        "alpha_safety": _category_status(alpha),
    }


def _build_comparison_asset_index(
    root: Path, results: list[dict[str, Any]]
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for result in results:
        e1 = result.get("e1_02_result")
        if not e1:
            cases.append(
                {
                    "e1_01_case_id": None,
                    "run_id": result.get("run_id"),
                    "status": "NOT_AVAILABLE_E1_02_INCOMPLETE",
                    "asset_count": 0,
                }
            )
            continue
        manifest_path = _resolve_reference(e1["evidence_refs"]["comparison_manifest"])
        comparison = _read_json(manifest_path)
        asset_paths = [comparison["full_image_side_by_side"]]
        for roi in comparison["roi"]:
            asset_paths.append(roi["side_by_side"])
            asset_paths.extend(path for path in roi["crop_paths"].values() if path)
        cases.append(
            {
                "e1_01_case_id": e1["e1_01_case_id"],
                "comparison_manifest": _relative(manifest_path),
                "full_image": comparison["full_image_side_by_side"],
                "roi_100_percent_crops": [
                    {
                        "roi_id": roi["roi_id"],
                        "roi_type": roi["roi_type"],
                        "crop_paths": roi["crop_paths"],
                        "side_by_side": roi["side_by_side"],
                    }
                    for roi in comparison["roi"]
                ],
                "asset_count": len(asset_paths),
                "asset_sha256": {
                    path: sha256_file(_resolve_reference(path)) for path in asset_paths
                },
            }
        )
    index = {
        "artifact_version": "E4K_03_HUMAN_REVIEW_PACKAGE_V1",
        "status": "READY_FOR_REAL_HUMAN_REVIEW",
        "human_review_status": "NEED_REVIEW",
        "automated_review_verdict": "FORBIDDEN",
        "panel_order": ["INPUT", "SAFE_BASE", "CANDIDATE", "GT"],
        "case_count": len(cases),
        "cases": cases,
    }
    _write_json(root / "comparison_assets" / "human_review_package.json", index)
    return index


def _write_artifact_integrity(root: Path) -> dict[str, Any]:
    destination = root / "validation" / "artifact_integrity.json"
    files = [
        path
        for path in sorted(root.rglob("*"))
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
        "integrity_version": "E4K_03_ARTIFACT_INTEGRITY_V1",
        "status": "PASS",
        "file_count_excluding_this_manifest": len(entries),
        "tree_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "files": entries,
    }
    _write_json(destination, result)
    return result


def _build_candidate_comparison(
    *, candidate_id: str, summary: dict[str, Any]
) -> dict[str, Any]:
    eligibility_summary = _read_json(ELIGIBILITY_ROOT / "summary.json")
    rows: list[dict[str, Any]] = []
    for relative_record in eligibility_summary["records"]:
        record = _read_json(ELIGIBILITY_ROOT / relative_record)
        is_benchmarked = record["model_id"] == MODEL_ID
        rows.append(
            {
                "model_id": record["model_id"],
                "model_role": record["model_role"],
                "eligibility": record["model_eligibility"],
                "runtime": (
                    summary["runtime"]
                    if is_benchmarked
                    else "NOT_RUN_ELIGIBILITY_BLOCKED"
                ),
                "safety": (
                    summary["hard_safety"]
                    if is_benchmarked
                    else "NOT_EVALUATED"
                ),
                "quality_gain": (
                    summary["quality_gain_counts"]
                    if is_benchmarked
                    else "NOT_EVALUATED"
                ),
                "text": (
                    summary["category_safety"]["text_safety"]
                    if is_benchmarked
                    else "NOT_EVALUATED"
                ),
                "logo": (
                    summary["category_safety"]["logo_structure_safety"]
                    if is_benchmarked
                    else "NOT_EVALUATED"
                ),
                "structure": (
                    summary["category_safety"]["logo_structure_safety"]
                    if is_benchmarked
                    else "NOT_EVALUATED"
                ),
                "material": (
                    summary["category_safety"]["material_safety"]
                    if is_benchmarked
                    else "NOT_EVALUATED"
                ),
                "artifact_risk": (
                    summary["category_safety"]["edge_artifact_safety"]
                    if is_benchmarked
                    else "NOT_EVALUATED"
                ),
                "human_review": "NEED_REVIEW" if is_benchmarked else "NOT_RUN",
                "selection_evidence": (
                    _selection_evidence_from_summary(summary)
                    if is_benchmarked
                    else "NOT_EVALUATED"
                ),
                "final_status": (
                    summary["model_status"] if is_benchmarked else "BLOCKED"
                ),
                "reason": (
                    summary["model_rejection_reason"]
                    if is_benchmarked
                    else record.get("block_reasons", [])
                ),
                "candidate_id": candidate_id if is_benchmarked else None,
            }
        )
    outcome = _derive_candidate_comparison_outcome(rows)
    result = {
        "artifact_version": "E4K_03_CANDIDATE_COMPARISON_V1",
        "candidate_selection_contract": CANDIDATE_SELECTION_CONTRACT,
        "selection_priority": [
            {"field": field, "direction": direction}
            for field, direction in CANDIDATE_SELECTION_PRIORITY
        ],
        "commercial_high_risk_failure_definition": (
            "COUNT_OF_FAIL_STATUSES_IN_EXISTING_E1_02_CATEGORY_SAFETY_FACTS"
        ),
        "runtime_role": "QUALITY_AND_SAFETY_TIEBREAKER",
        "candidate_id_selection_authority": "NONE",
        "full_tie_result": "UNRESOLVED_MULTI_ADOPT",
        "ranking_policy": "NO_AVERAGE_METRIC_RANKING; SAFETY_AND_REAL_EVIDENCE_FIRST",
        "initial_candidate_count": len(rows),
        "eligible_candidate_count": sum(
            row.get("eligibility") == "PASS" for row in rows
        ),
        "benchmarked_candidate_count": sum(
            row.get("candidate_id") is not None for row in rows
        ),
        "candidates": rows,
        **outcome,
        **_e4k_02_reporting_scope(),
        "next_technical_direction": (
            "PROCEED_TO_PRODUCTION_ADOPTION_GATE; FORMAL_PRODUCTION_NOT_AUTHORIZED"
            if outcome["adopted_candidate_count"]
            else "USE_FAILURE_LOCALIZATION_AS_INPUT_TO_HDDE_SELF_DEVELOPED_"
            "RESTORATION_CORE; DO_NOT_LOWER_E1_02_OR_REOPEN_FIDESR"
        ),
        "generated_at_utc": _utc_now(),
    }
    return result


def _write_candidate_comparison(
    *, candidate_id: str, summary: dict[str, Any]
) -> dict[str, Any]:
    result = _build_candidate_comparison(candidate_id=candidate_id, summary=summary)
    _write_json(COMPARISON_PATH, result)
    return result


def run_benchmark() -> dict[str, Any]:
    eligibility, definition, adapter, _ = _load_frozen_candidate()
    candidate_id, _ = build_candidate_identity(definition)
    root = CANDIDATES_ROOT / candidate_id
    smoke_path = root / "validation" / "smoke_summary.json"
    if not smoke_path.is_file():
        raise RuntimeError("SMOKE_ARTIFACT_MISSING")
    smoke = _read_json(smoke_path)
    if smoke.get("status") != "PASS" or smoke.get("benchmark_authorized") is not True:
        raise RuntimeError("SMOKE_NOT_PASS_BENCHMARK_FORBIDDEN")
    manifest = _read_json(E1_MANIFEST)
    cases = manifest["cases"]
    if len(cases) != 16:
        raise RuntimeError(f"E1_CASE_COUNT_NOT_16:{len(cases)}")

    results: list[dict[str, Any]] = []
    runtime_records: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        case_id = case["case_id"]
        case_result_path = root / "case_results" / f"{case_id}.json"
        if case_result_path.exists():
            result = _read_json(case_result_path)
            print(f"BENCHMARK_RESUME={index}/16;CASE={case_id}", flush=True)
        else:
            print(
                f"BENCHMARK_START={index}/16;CASE={case_id};"
                f"INPUT_PIXELS={case['input']['width'] * case['input']['height']}",
                flush=True,
            )
            result = _run_one(
                case=case,
                workspace=root / "benchmark_runs",
                definition=definition,
                adapter=adapter,
                nonce="E4K03_FULL_BENCHMARK_V1",
            )
            _write_json(case_result_path, result)
        runtime = _runtime_for_result(result)
        runtime_records.append(runtime)
        results.append(result)
        _write_json(root / "runtime" / f"{case_id}.json", runtime)
        _write_json(
            root / "roi_results" / f"{case_id}.json",
            {
                "e1_01_case_id": case_id,
                "candidate_id": candidate_id,
                "roi_results": (result.get("e1_02_result") or {}).get(
                    "roi_results", []
                ),
            },
        )
        _write_json(
            root / "e1_02_results" / f"{case_id}.json",
            result.get("e1_02_result"),
        )
        _write_json(
            root / "validation" / f"{case_id}.json",
            {
                "execution_status": result.get("execution_status"),
                "output_validation": result.get("output_validation"),
                "comparison_surface": result.get("comparison_surface"),
                "actual_run_binding": result.get("actual_run_binding"),
                "candidate_state": result.get("candidate_state"),
                "safe_reference_selected": result.get("safe_reference_selected"),
            },
        )
        print(
            f"BENCHMARK_DONE={index}/16;CASE={case_id};"
            f"EXECUTION={result.get('execution_status')};"
            f"STATE={result.get('candidate_state')};"
            f"SAFETY={result.get('safety_status')};"
            f"QUALITY={result.get('quality_gain_status')};"
            f"INFERENCE_SECONDS={runtime['inference_time_seconds']:.6f}",
            flush=True,
        )

    binding_pass = sum(
        result.get("actual_run_binding_status") == "PASS" for result in results
    )
    execution_pass = sum(
        result.get("execution_status") == "COMPLETED" for result in results
    )
    e1_complete = sum(
        (result.get("e1_02_result") or {}).get("evaluation_status") == "COMPLETE"
        for result in results
    )
    safety_counts = Counter(result.get("safety_status") for result in results)
    quality_counts = Counter(result.get("quality_gain_status") for result in results)
    mandatory_complete = sum(
        result.get("mandatory_gate_complete") is True for result in results
    )
    delivery_pass = sum(
        result.get("delivery_status") == "PASS" for result in results
    )
    category = _aggregate_safety(cases, results)
    if execution_pass != 16 or binding_pass != 16 or e1_complete != 16:
        model_status = "REJECT"
        rejection_reason = "INCOMPLETE_16_CASE_EXECUTION_BINDING_OR_E1_02_EVALUATION"
    elif safety_counts.get("FAIL", 0) > 0:
        model_status = "REJECT"
        rejection_reason = "E1_02_HARD_SAFETY_FAILURE_HAS_ABSOLUTE_VETO"
    elif (
        quality_counts.get("QUALITY_GAIN_PROVEN", 0) > 0
        and mandatory_complete == 16
        and delivery_pass == 16
    ):
        model_status = "ADOPT"
        rejection_reason = "NONE"
    else:
        model_status = "KEEP_FOR_RESEARCH"
        rejection_reason = (
            "REAL_NET_GAIN_AND_REQUIRED_HUMAN_REVIEW_NOT_COMPLETE_FOR_ADOPTION"
        )

    review_package = _build_comparison_asset_index(root, results)
    runtime_summary = _build_runtime_summary(runtime_records)
    human_review_confirmed_better_count = sum(
        (result.get("e1_02_result") or {}).get("human_review_completed") is True
        and (result.get("e1_02_result") or {}).get(
            "human_review_product_admissible"
        )
        is True
        and (result.get("e1_02_result") or {}).get("human_review_verdict")
        == "BETTER"
        for result in results
    )
    summary = {
        "artifact_version": ARTIFACT_VERSION,
        "task_id": TASK_ID,
        "candidate_id": candidate_id,
        "model_id": MODEL_ID,
        "model_version": eligibility["model_version"],
        "model_sha256": eligibility["model_sha256"],
        "model_size": eligibility["model_size"],
        "backend": eligibility["backend"],
        "precision": eligibility["precision"],
        "smoke_test": "PASS",
        "e1_02_cases": f"{e1_complete}/16",
        "actual_run_binding_pass_count": binding_pass,
        "execution_pass_count": execution_pass,
        "hard_safety": (
            "FAIL"
            if safety_counts.get("FAIL", 0)
            else "REVIEW" if safety_counts.get("REVIEW", 0) else "PASS"
        ),
        "hard_safety_counts": dict(safety_counts),
        "mandatory_gates": (
            "PASS" if mandatory_complete == 16 else "NOT_COMPLETE"
        ),
        "mandatory_gate_complete_count": mandatory_complete,
        "quality_gain_counts": {
            "QUALITY_GAIN_PROVEN": quality_counts.get("QUALITY_GAIN_PROVEN", 0),
            "QUALITY_GAIN_NOT_PROVEN": quality_counts.get(
                "QUALITY_GAIN_NOT_PROVEN", 0
            ),
            "QUALITY_GAIN_REJECTED": quality_counts.get(
                "QUALITY_GAIN_REJECTED", 0
            ),
        },
        "delivery_pass_count": delivery_pass,
        "category_safety": category,
        "human_review_status": "NEED_REVIEW",
        "human_review_confirmed_better_count": human_review_confirmed_better_count,
        "human_review_package": _relative(
            root / "comparison_assets" / "human_review_package.json"
        ),
        "runtime": runtime_summary,
        "model_status": model_status,
        "model_rejection_reason": rejection_reason,
        "formal_production": False,
        "completed_at_utc": _utc_now(),
    }
    summary = _apply_dynamic_summary_reporting(summary)
    _write_json(root / "runtime" / "summary.json", runtime_summary)
    _write_json(root / "summary.json", summary)
    manifest_record = _read_json(root / "candidate_manifest.json")
    manifest_record["status"] = "BENCHMARK_COMPLETE"
    manifest_record["benchmark_summary"] = summary
    manifest_record["human_review_package"] = review_package
    _write_json(root / "candidate_manifest.json", manifest_record)
    _update_eligibility_usage(inference=True, benchmark=True)
    comparison = _write_candidate_comparison(
        candidate_id=candidate_id, summary=summary
    )
    summary["candidate_comparison"] = _relative(COMPARISON_PATH)
    summary["candidate_comparison_sha256"] = sha256_file(COMPARISON_PATH)
    summary["artifact_integrity"] = {
        "manifest": _relative(root / "validation" / "artifact_integrity.json"),
        "tree_hash_and_file_count": "SEE_INTEGRITY_MANIFEST",
    }
    _write_json(root / "summary.json", summary)
    integrity = _write_artifact_integrity(root)
    print(f"BENCHMARK_STATUS={summary['status']}", flush=True)
    print(f"MODEL_STATUS={model_status}", flush=True)
    print(f"REAL_4K_QUALITY_GAIN={summary['real_4k_quality_gain']}", flush=True)
    print(f"CANDIDATE_ROOT={root}", flush=True)
    print(f"COMPARISON={COMPARISON_PATH}", flush=True)
    return {"summary": summary, "comparison": comparison}


def _assert_frozen_current_swin2sr_facts(summary: dict[str, Any]) -> None:
    expected = {
        "e1_02_cases": "16/16",
        "hard_safety_counts": {"FAIL": 14, "PASS": 2},
        "quality_gain_counts": {
            "QUALITY_GAIN_PROVEN": 0,
            "QUALITY_GAIN_NOT_PROVEN": 2,
            "QUALITY_GAIN_REJECTED": 14,
        },
        "model_status": "REJECT",
    }
    for field, value in expected.items():
        if summary.get(field) != value:
            raise RuntimeError(f"FROZEN_SWIN2SR_FACT_MISMATCH:{field}")
    if summary.get("model_id") != MODEL_ID:
        raise RuntimeError("FROZEN_SWIN2SR_MODEL_ID_MISMATCH")


def _normalize_active_runtime_artifacts(root: Path) -> None:
    for path in sorted((root / "runtime").glob("*.json")):
        _write_json(path, _normalize_runtime_report(_read_json(path)))

    smoke_summary_path = root / "validation" / "smoke_summary.json"
    smoke_summary = _read_json(smoke_summary_path)
    smoke_summary["runtime"] = _normalize_runtime_report(smoke_summary["runtime"])
    _write_json(smoke_summary_path, smoke_summary)


def _contains_stale_active_memory_field(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key in STALE_ACTIVE_MEMORY_FIELDS
            or _contains_stale_active_memory_field(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_stale_active_memory_field(item) for item in value)
    return False


def _active_e4k_03_json_paths(root: Path) -> list[Path]:
    paths = [
        COMPARISON_PATH,
        root / "summary.json",
        root / "candidate_manifest.json",
        root / "validation" / "smoke_summary.json",
    ]
    paths.extend(sorted((root / "runtime").glob("*.json")))
    paths.extend(sorted(ELIGIBILITY_ROOT.rglob("*.json")))
    return paths


def _stale_active_peak_memory_field_count(root: Path) -> int:
    return sum(
        _contains_stale_active_memory_field(_read_json(path))
        for path in _active_e4k_03_json_paths(root)
    )


def refresh_derived_summaries() -> dict[str, Any]:
    summary_paths = sorted(CANDIDATES_ROOT.glob("candidate_*/summary.json"))
    matches = [
        path
        for path in summary_paths
        if _read_json(path).get("model_id") == MODEL_ID
    ]
    if len(matches) != 1:
        raise RuntimeError(f"SWIN2SR_SUMMARY_NOT_UNIQUE:{len(matches)}")

    summary_path = matches[0]
    root = summary_path.parent
    current = _read_json(summary_path)
    _assert_frozen_current_swin2sr_facts(current)
    summary = _apply_dynamic_summary_reporting(current)
    if (
        summary["best_candidate"] != "NONE"
        or summary["model_adoption"] != "NONE"
        or summary["adopted_candidate_count"] != 0
        or summary["real_4k_quality_gain"] != "NOT_PROVEN"
    ):
        raise RuntimeError("CURRENT_SWIN2SR_DYNAMIC_OUTCOME_CHANGED")

    comparison = _build_candidate_comparison(
        candidate_id=summary["candidate_id"], summary=summary
    )
    if (
        comparison["best_candidate"] != "NONE"
        or comparison["model_adoption"] != "NONE"
        or comparison["adopted_candidate_count"] != 0
        or comparison["real_4k_quality_gain"] != "NOT_PROVEN"
    ):
        raise RuntimeError("CURRENT_COMPARISON_DYNAMIC_OUTCOME_CHANGED")

    summary["reuse_correction"] = {
        "task_id": REUSE_CORRECTION_TASK_ID,
        "derived_files_only": True,
        "new_model_download": False,
        "new_model_inference": False,
        "new_model_benchmark": False,
        "swin2sr_retest": False,
        "refreshed_at_utc": _utc_now(),
    }
    summary["active_schema_stale_peak_field_count"] = 0
    _normalize_active_runtime_artifacts(root)
    _write_json(root / "runtime" / "summary.json", summary["runtime"])
    _write_json(COMPARISON_PATH, comparison)
    summary["candidate_comparison"] = _relative(COMPARISON_PATH)
    summary["candidate_comparison_sha256"] = sha256_file(COMPARISON_PATH)
    summary["artifact_integrity"] = {
        "manifest": _relative(root / "validation" / "artifact_integrity.json"),
        "tree_hash_and_file_count": "SEE_INTEGRITY_MANIFEST",
    }
    _write_json(summary_path, summary)

    manifest_path = root / "candidate_manifest.json"
    manifest = _read_json(manifest_path)
    manifest["smoke_test"] = _read_json(root / "validation" / "smoke_summary.json")
    manifest["benchmark_summary"] = summary
    protected_scope = dict(manifest.get("protected_scope") or {})
    protected_scope.update(_e4k_02_reporting_scope())
    manifest["protected_scope"] = protected_scope
    manifest["reuse_correction"] = summary["reuse_correction"]
    _write_json(manifest_path, manifest)
    stale_active_field_count = _stale_active_peak_memory_field_count(root)
    if stale_active_field_count:
        raise RuntimeError(
            f"STALE_ACTIVE_PEAK_MEMORY_FIELD_COUNT:{stale_active_field_count}"
        )
    integrity = _write_artifact_integrity(root)
    return {
        "status": "PASS",
        "task_id": REUSE_CORRECTION_TASK_ID,
        "summary": summary,
        "comparison": comparison,
        "stale_active_peak_memory_field_count": stale_active_field_count,
        "artifact_integrity": integrity,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("smoke", "benchmark", "refresh-summary"))
    args = parser.parse_args()
    if args.phase == "smoke":
        result = run_smoke()
    elif args.phase == "benchmark":
        result = run_benchmark()
    else:
        result = refresh_derived_summaries()
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
