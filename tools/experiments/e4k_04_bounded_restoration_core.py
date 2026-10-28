"""Execute and validate E4K-04 HDDE Bounded Restoration Core V1 evidence.

The experiment is isolated from the formal 4K route.  It uses the frozen
E1-01 Source/Safe Base pairs, the E4K-02 Candidate Framework, and the existing
E1-02 gate without changing any of their semantics or artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.hd_core.bounded_restoration import (  # noqa: E402
    ACTIVE,
    ALGORITHM_ID,
    ALGORITHM_VERSION,
    DEGRADATION_PROFILE_VERSION,
    NO_OP,
    PROFILE_ID,
    RESIDUAL_CONTRACT_VERSION,
    SAFE_PROFILE,
    SUPPORTED_TARGET_DEGRADATION,
    TARGET_DEGRADATION_FAMILY,
    bounded_candidate_definition,
    bounded_restoration_candidate,
    restore_bounded_candidate,
)
from engine.hd_core.candidate_framework import (  # noqa: E402
    E102EvaluationContext,
    build_candidate_identity,
    run_4k_candidate,
    sha256_file,
)


TASK_ID = "E4K-04_HDDE_BOUNDED_RESTORATION_CORE_V1"
ARTIFACT_VERSION = "E4K_04_BOUNDED_RESTORATION_CORE_ARTIFACT_V1"
E1_MANIFEST = (
    REPO_ROOT / "artifacts" / "e1_01_real_information_baseline_v1" / "manifest.json"
)
E1_ZERO_RESULTS = REPO_ROOT / "artifacts" / "e1_02_quality_delivery_gate_v1" / "case_results"
OUTPUT_ROOT = REPO_ROOT / "artifacts" / "e4k_04_bounded_restoration_core_v1"
EXPECTED_CASE_COUNT = 16
EXPECTED_TARGET_CASE_IDS = ("E1C006", "E1C007", "E1C008", "E1C014")

PROTECTED_SOURCE_HASHES = {
    "engine/image_processing_routing/four_k_v1.py": "7741e65a0aef3a9e24caa58ba75bc391cb0040b139802802a4670f908e469e65",
    "main.py": "c1a36512f8a2b8b487a039ec306c240c242f1a0b1aa87430e657dab254ad6db8",
    "product_version.json": "0517884da7197275f505cb21acee3dfe239f88d9f810da9495ef747f5a94bb36",
    "tools/experiments/e1_01_real_information_baseline.py": "2741c5b7b10524167db436a39a331323f76bc20ec9ba167b79abd36b5c8754a6",
    "tools/experiments/e1_02_quality_delivery_gate.py": "222f840fce1eac0c13c02555b51e1f00c6d31b79d5844cb88e2e6920fa590027",
}
PROTECTED_TREE_HASHES = {
    "artifacts/e1_01_real_information_baseline_v1": (
        156,
        "6e67a81a60ac3a011130210e6b9bdb949457a4d48a21d78af85825dfb6ef8827",
    ),
    "artifacts/e1_02_quality_delivery_gate_v1": (
        364,
        "f7b66997aee35c8387abf49b25e434aa617fb98572e02cc6f5bb81f416fad86f",
    ),
    "artifacts/e4k_02_candidate_framework_v1": (
        272,
        "8fc743360b5de779bc384b2cb51cf212ac0339fb526b850fdc3efadbe626e0c2",
    ),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def _tree_state(relative_root: str) -> dict[str, Any]:
    root = REPO_ROOT / relative_root
    files = sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: str(path).lower(),
    )
    payload = "".join(
        f"{path.relative_to(root).as_posix()}\t{sha256_file(path)}\n"
        for path in files
    ).encode("utf-8")
    return {
        "path": relative_root,
        "file_count": len(files),
        "tree_sha256": hashlib.sha256(payload).hexdigest(),
    }


def protected_scope_state() -> dict[str, Any]:
    sources = {
        relative: {
            "expected_sha256": expected,
            "actual_sha256": sha256_file(REPO_ROOT / relative),
            "unchanged": sha256_file(REPO_ROOT / relative) == expected,
        }
        for relative, expected in PROTECTED_SOURCE_HASHES.items()
    }
    trees: dict[str, Any] = {}
    for relative, (expected_count, expected_hash) in PROTECTED_TREE_HASHES.items():
        actual = _tree_state(relative)
        actual.update(
            {
                "expected_file_count": expected_count,
                "expected_tree_sha256": expected_hash,
                "unchanged": actual["file_count"] == expected_count
                and actual["tree_sha256"] == expected_hash,
            }
        )
        trees[relative] = actual
    return {
        "status": (
            "PASS"
            if all(item["unchanged"] for item in sources.values())
            and all(item["unchanged"] for item in trees.values())
            else "FAIL"
        ),
        "source_files": sources,
        "artifact_trees": trees,
        "formal_4k_pipeline_changed": False,
        "api_4k_changed": False,
        "e1_01_changed": not trees[
            "artifacts/e1_01_real_information_baseline_v1"
        ]["unchanged"],
        "e1_02_changed": not trees[
            "artifacts/e1_02_quality_delivery_gate_v1"
        ]["unchanged"],
        "e4k_02_frozen_artifact_changed": not trees[
            "artifacts/e4k_02_candidate_framework_v1"
        ]["unchanged"],
        "product_version_changed": not sources["product_version.json"]["unchanged"],
    }


def _manifest() -> dict[str, Any]:
    manifest = _read_json(E1_MANIFEST)
    cases = manifest.get("cases") or []
    if len(cases) != EXPECTED_CASE_COUNT:
        raise RuntimeError(f"E1_CASE_COUNT_NOT_16:{len(cases)}")
    return manifest


def _target_selection(manifest: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in manifest["cases"]:
        case_id = case["case_id"]
        source = _resolve(case["input"]["path"])
        zero_path = E1_ZERO_RESULTS / f"ZERO__{case_id}.json"
        zero = _read_json(zero_path)
        gt_evidence = (zero.get("quality_gain_results") or {}).get("gt_evidence") or {}
        baseline_to_gt = gt_evidence.get("baseline_to_gt") or {}
        delta = baseline_to_gt.get("delta_metrics") or {}
        rows.append(
            {
                "case_id": case_id,
                "declared_degradation_family": zero.get("degradation_family"),
                "input_suffix": source.suffix.lower(),
                "gt_available": case.get("gt") is not None,
                "baseline_to_gt_rgb_mae": delta.get("rgb_mae"),
            }
        )

    def evidence(name: str, selected: list[dict[str, Any]]) -> dict[str, Any]:
        headroom = [
            float(row["baseline_to_gt_rgb_mae"])
            for row in selected
            if isinstance(row.get("baseline_to_gt_rgb_mae"), (int, float))
        ]
        return {
            "family": name,
            "valid_case_count": len(selected),
            "case_ids": [row["case_id"] for row in selected],
            "gt_available_count": sum(row["gt_available"] for row in selected),
            "baseline_error_headroom_rgb_mae_mean": (
                None if not headroom else round(float(np.mean(headroom)), 8)
            ),
        }

    candidates = [
        evidence(
            "JPEG_COMPRESSION",
            [row for row in rows if row["input_suffix"] in {".jpg", ".jpeg"}],
        ),
        evidence(
            "BLUR",
            [
                row
                for row in rows
                if "BLUR" in str(row["declared_degradation_family"] or "")
            ],
        ),
        evidence(
            "MULTI_RESIZE",
            [
                row
                for row in rows
                if row["declared_degradation_family"] == "MULTI_RESIZE"
            ],
        ),
        evidence(
            "SCREENSHOT_LIKE",
            [
                row
                for row in rows
                if row["declared_degradation_family"] == "SCREENSHOT_LIKE"
            ],
        ),
    ]
    target = next(row for row in candidates if row["family"] == TARGET_DEGRADATION_FAMILY)
    if tuple(target["case_ids"]) != EXPECTED_TARGET_CASE_IDS:
        raise RuntimeError(f"TARGET_CASE_EVIDENCE_CHANGED:{target['case_ids']}")
    return {
        "selection_version": "E4K_04_TARGET_FAMILY_SELECTION_V1",
        "selected_family": TARGET_DEGRADATION_FAMILY,
        "reason": (
            "JPEG_COMPRESSION_HAS_4_INDEPENDENT_HOLDOUTS_3_WITH_GT_MEAN_"
            "LANCZOS_TO_GT_RGB_MAE_2_98_DIRECT_JPEG_EVIDENCE_AND_A_NARROW_"
            "NON_GENERATIVE_DEBLOCKING_OPPORTUNITY; BLUR_AND_MULTI_RESIZE_HAVE_"
            "ONLY_1_EXPLICIT_CASE_EACH; SCREENSHOT_LIKE_HAS_LOWER_HEADROOM_AND_"
            "HIGHER_TEXT_STRUCTURE_RISK"
        ),
        "selection_inputs": (
            "VALID_CASE_COUNT_GT_AVAILABILITY_BASELINE_ERROR_HEADROOM_"
            "EXPLAINABLE_OPERATOR_COMMERCIAL_SAFETY_RISK"
        ),
        "candidates": candidates,
        "target_family_valid_cases": target["valid_case_count"],
        "target_family_real_holdout_cases": target["valid_case_count"],
        "target_case_ids": target["case_ids"],
        "holdout_gt_used_for_parameter_tuning": False,
    }


def _synthetic_probe_rgb(kind: str, height: int = 144, width: int = 192) -> np.ndarray:
    yy, xx = np.indices((height, width))
    if kind == "SMOOTH_MATERIAL":
        base = 36.0 + xx * 0.72 + yy * 0.31
        texture = 4.0 * np.sin(xx / 11.0) + 2.0 * np.cos(yy / 9.0)
        luma = np.clip(base + texture, 0, 255).astype(np.uint8)
        return np.dstack((luma, np.clip(luma + 12, 0, 255), np.clip(luma + 24, 0, 255)))
    base = np.full((height, width), 218, dtype=np.uint8)
    base[28:112, 40:46] = 24
    base[28:34, 40:154] = 24
    base[70:76, 40:154] = 42
    for offset in range(52, 150, 18):
        base[90:102, offset : offset + 8] = 65
    return np.dstack((base, base, base))


def run_controlled_calibration() -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for index, kind in enumerate(("SMOOTH_MATERIAL", "HIGH_CONTRAST_STRUCTURE"), 1):
            clean = _synthetic_probe_rgb(kind)
            source = root / f"target_{index}.jpg"
            Image.fromarray(clean, "RGB").save(
                source, format="JPEG", quality=42, subsampling=2
            )
            decoded = Image.open(source).convert("RGB")
            baseline = root / f"target_{index}_baseline.png"
            decoded.resize((768, 576), Image.Resampling.LANCZOS).save(
                baseline, format="PNG", compress_level=6
            )
            oracle = np.asarray(
                Image.fromarray(clean, "RGB").resize((768, 576), Image.Resampling.LANCZOS),
                dtype=np.float32,
            )
            candidate = root / f"target_{index}_candidate.png"
            record = restore_bounded_candidate(source, baseline, candidate)
            baseline_array = np.asarray(Image.open(baseline).convert("RGB"), dtype=np.float32)
            candidate_array = np.asarray(Image.open(candidate).convert("RGB"), dtype=np.float32)
            results.append(
                {
                    "probe_id": f"CONTROLLED_JPEG_{index:02d}_{kind}",
                    "profile_status": record["degradation_profile"]["status"],
                    "restoration_activation": record["restoration_activation"],
                    "baseline_to_control_mae": round(
                        float(np.mean(np.abs(baseline_array - oracle))), 8
                    ),
                    "candidate_to_control_mae": round(
                        float(np.mean(np.abs(candidate_array - oracle))), 8
                    ),
                    "residual_max_abs_after": record["bounded_residual"].get(
                        "residual_max_abs_after", 0
                    ),
                    "candidate_hf_energy": record["bounded_residual"].get(
                        "candidate_hf_energy"
                    ),
                    "hf_budget": record["bounded_residual"].get("hf_budget"),
                    "color_lock_status": record["bounded_residual"].get(
                        "color_lock_status"
                    ),
                }
            )

        negative = root / "negative.png"
        negative_baseline = root / "negative_baseline.png"
        negative_output = root / "negative_candidate.png"
        negative_rgb = _synthetic_probe_rgb("SMOOTH_MATERIAL")
        Image.fromarray(negative_rgb, "RGB").save(negative)
        Image.fromarray(negative_rgb, "RGB").resize(
            (768, 576), Image.Resampling.LANCZOS
        ).save(negative_baseline, format="PNG", compress_level=6)
        negative_record = restore_bounded_candidate(
            negative, negative_baseline, negative_output
        )
        negative_result = {
            "probe_id": "NEGATIVE_NON_JPEG_NO_OP",
            "profile_status": negative_record["degradation_profile"]["status"],
            "restoration_activation": negative_record["restoration_activation"],
            "baseline_byte_identity": sha256_file(negative_baseline)
            == sha256_file(negative_output),
        }

    target_safe = all(
        row["profile_status"] == SUPPORTED_TARGET_DEGRADATION
        and row["residual_max_abs_after"] <= SAFE_PROFILE.residual_absolute_budget
        and row["candidate_hf_energy"] <= row["hf_budget"] + 1e-7
        and row["color_lock_status"] == "PASS"
        for row in results
    ) and any(row["restoration_activation"] == ACTIVE for row in results)
    negative_safe = (
        negative_result["restoration_activation"] == NO_OP
        and negative_result["baseline_byte_identity"]
    )
    return {
        "calibration_version": "E4K_04_CONTROLLED_CALIBRATION_V1",
        "status": "PASS" if target_safe and negative_safe else "FAIL",
        "formal_profile_count": 1,
        "formal_profile_id": PROFILE_ID,
        "parameter_search": False,
        "real_e1_gt_used": False,
        "authority": "SAFETY_CALIBRATION_ONLY_NOT_PRODUCT_GAIN_PROOF",
        "supported_probe_no_op_policy": (
            "ADMISSIBLE_WHEN_NO_INTEGER_RESIDUAL_SURVIVES_ALL_BUDGETS; "
            "AT_LEAST_ONE_TARGET_PROBE_MUST_REMAIN_ACTIVE"
        ),
        "threshold_sources": SAFE_PROFILE.canonical_parameters()["threshold_sources"],
        "target_probes": results,
        "negative_control": negative_result,
    }


def _runtime_context() -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "technology": "SELF_DEVELOPED_BOUNDED_RESTORATION",
        "backend": "NUMPY_OPENCV_PILLOW_CPU",
        "device": "CPU",
        "precision": "FLOAT32_ANALYSIS_UINT8_DETERMINISTIC_OUTPUT",
        "profile_id": PROFILE_ID,
        "target_degradation_family": TARGET_DEGRADATION_FAMILY,
        "external_model": "NONE",
    }


def run_determinism(manifest: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    case = next(case for case in manifest["cases"] if case["case_id"] == "E1C006")
    source = _resolve(case["input"]["path"])
    baseline = _resolve(case["safe_base"]["path"])
    source_before = sha256_file(source)
    baseline_before = sha256_file(baseline)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        outputs: list[Path] = []
        records: list[dict[str, Any]] = []
        for index in (1, 2):
            output = root / f"repeat_{index}.png"
            record = restore_bounded_candidate(source, baseline, output)
            outputs.append(output)
            records.append(record)
        byte_identical = sha256_file(outputs[0]) == sha256_file(outputs[1])
        pixel_identical = records[0]["output_pixel_sha256"] == records[1][
            "output_pixel_sha256"
        ]
        output_sha = sha256_file(outputs[0])
    return {
        "determinism_version": "E4K_04_DETERMINISM_V1",
        "status": "PASS" if byte_identical and pixel_identical else "FAIL",
        "case_id": "E1C006",
        "candidate_id": candidate_id,
        "canonical_parameters": bounded_candidate_definition().identity_contract()[
            "canonical_parameters"
        ],
        "runtime_contract": _runtime_context(),
        "repeat_count": 2,
        "byte_identical": byte_identical,
        "pixel_identical": pixel_identical,
        "output_sha256": output_sha,
        "source_unchanged": sha256_file(source) == source_before,
        "baseline_unchanged": sha256_file(baseline) == baseline_before,
        "temporary_outputs_retained": False,
    }


def _run_case(
    case: dict[str, Any], definition: Any, *, nonce: str
) -> dict[str, Any]:
    return run_4k_candidate(
        _resolve(case["input"]["path"]),
        OUTPUT_ROOT / "candidate_runs",
        definition=definition,
        executor=bounded_restoration_candidate,
        baseline_path=_resolve(case["safe_base"]["path"]),
        e1_02_context=E102EvaluationContext(E1_MANIFEST, case["case_id"]),
        runtime_context=_runtime_context(),
        execution_nonce=nonce,
    )


def _core_record(result: dict[str, Any]) -> dict[str, Any]:
    run_dir = _resolve(result["evidence_refs"]["run_directory"])
    path = run_dir / "budget_records" / "bounded_restoration_record.json"
    if not path.is_file():
        raise RuntimeError(f"BOUNDED_RECORD_MISSING:{path}")
    return _read_json(path)


def _write_case_derivatives(
    case_id: str, result: dict[str, Any], record: dict[str, Any]
) -> None:
    _write_json(OUTPUT_ROOT / "budget_records" / f"{case_id}.json", record)
    _write_json(
        OUTPUT_ROOT / "degradation_profile" / f"{case_id}.json",
        record.get("degradation_profile"),
    )
    _write_json(
        OUTPUT_ROOT / "protection_masks_metadata" / f"{case_id}.json",
        record.get("protection_masks_metadata")
        or {
            "status": "NOT_EXECUTED_NO_OP",
            "reason": record.get("no_op_reason"),
        },
    )
    e1 = result.get("e1_02_result")
    _write_json(OUTPUT_ROOT / "e1_02_results" / f"{case_id}.json", e1)
    _write_json(
        OUTPUT_ROOT / "roi_results" / f"{case_id}.json",
        {
            "e1_01_case_id": case_id,
            "candidate_id": result.get("candidate_id"),
            "roi_results": [] if e1 is None else e1.get("roi_results", []),
        },
    )
    _write_json(
        OUTPUT_ROOT / "validation" / f"{case_id}.json",
        {
            "execution_status": result.get("execution_status"),
            "output_validation": result.get("output_validation"),
            "comparison_surface": result.get("comparison_surface"),
            "actual_run_binding": result.get("actual_run_binding"),
            "candidate_state": result.get("candidate_state"),
            "model_download": result.get("model_download"),
            "model_inference_run": result.get("model_inference_run"),
            "model_benchmark": result.get("model_benchmark"),
        },
    )


def _build_human_review_package(results: list[dict[str, Any]]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for result in results:
        e1 = result.get("e1_02_result") or {}
        case_id = e1.get("e1_01_case_id")
        refs = e1.get("evidence_refs") or {}
        manifest_value = refs.get("comparison_manifest")
        if not manifest_value:
            cases.append(
                {
                    "e1_01_case_id": case_id,
                    "status": "NOT_AVAILABLE_E1_02_INCOMPLETE",
                    "asset_count": 0,
                }
            )
            continue
        manifest_path = _resolve(manifest_value)
        comparison = _read_json(manifest_path)
        asset_paths = [comparison["full_image_side_by_side"]]
        for roi in comparison["roi"]:
            asset_paths.append(roi["side_by_side"])
            asset_paths.extend(path for path in roi["crop_paths"].values() if path)
        cases.append(
            {
                "e1_01_case_id": case_id,
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
                    path: sha256_file(_resolve(path)) for path in asset_paths
                },
            }
        )
    package = {
        "artifact_version": "E4K_04_HUMAN_REVIEW_PACKAGE_V1",
        "status": "READY_FOR_REAL_HUMAN_REVIEW",
        "human_review_status": "NEED_REVIEW",
        "automated_review_verdict": "FORBIDDEN",
        "panel_order": ["INPUT", "SAFE_BASE", "CANDIDATE", "GT"],
        "view_contract": ["FULL", "ROI", "100_PERCENT_CROP"],
        "case_count": len(cases),
        "cases": cases,
    }
    _write_json(OUTPUT_ROOT / "comparison_assets" / "human_review_package.json", package)
    return package


def _roi_damage_count(e1_results: list[dict[str, Any]]) -> int:
    return sum(
        1
        for e1 in e1_results
        for roi in e1.get("roi_results") or []
        if roi.get("text_fidelity") == "TEXT_DEGRADED"
    )


def derive_case_summary_evidence(
    *,
    case_id: str,
    record: dict[str, Any],
    e1_result: dict[str, Any],
    baseline_pixels: np.ndarray,
    candidate_pixels: np.ndarray,
) -> dict[str, Any]:
    """Recompute budget/overshoot/halo evidence from pixels and raw E1-02 facts."""

    baseline = np.asarray(baseline_pixels, dtype=np.uint8)
    candidate = np.asarray(candidate_pixels, dtype=np.uint8)
    if baseline.shape != candidate.shape or baseline.ndim != 3:
        raise ValueError(f"SUMMARY_PIXEL_SHAPE_MISMATCH:{case_id}")
    if baseline.shape[2] not in {3, 4}:
        raise ValueError(f"SUMMARY_PIXEL_CHANNELS_UNSUPPORTED:{case_id}")
    baseline_rgb = baseline[..., :3]
    candidate_rgb = candidate[..., :3]
    delta = candidate_rgb.astype(np.int16) - baseline_rgb.astype(np.int16)
    actual_max_abs = int(np.max(np.abs(delta)))
    actual_nonzero_pixels = int(np.count_nonzero(np.any(delta != 0, axis=2)))

    profile = record.get("profile") or {}
    bounded = record.get("bounded_residual")
    bounded_record = bounded if isinstance(bounded, dict) else {}
    activation = record.get("restoration_activation")
    profile_residual_budget = profile.get("residual_absolute_budget")
    recorded_residual_budget = bounded_record.get("residual_absolute_budget")
    recorded_max_abs = bounded_record.get("residual_max_abs_after")
    recorded_nonzero = bounded_record.get("residual_nonzero_count")
    if activation == ACTIVE:
        residual_record_consistent = (
            recorded_residual_budget == profile_residual_budget
            and recorded_max_abs == actual_max_abs
            and recorded_nonzero == actual_nonzero_pixels
        )
    else:
        residual_record_consistent = actual_max_abs == 0
    residual_budget_finite = isinstance(profile_residual_budget, (int, float)) and np.isfinite(
        float(profile_residual_budget)
    )
    residual_pass = (
        residual_budget_finite
        and actual_max_abs <= float(profile_residual_budget)
        and residual_record_consistent
    )

    profile_overshoot_budget = profile.get("overshoot_budget")
    recorded_overshoot_budget = bounded_record.get("overshoot_budget")
    overshoot_budget_finite = isinstance(profile_overshoot_budget, (int, float)) and np.isfinite(
        float(profile_overshoot_budget)
    )
    local_violation_count = 0
    if overshoot_budget_finite:
        kernel = np.ones((3, 3), np.uint8)
        budget = float(profile_overshoot_budget)
        for channel in range(3):
            plane = baseline_rgb[..., channel]
            local_min = cv2.erode(plane, kernel).astype(np.float32) - budget
            local_max = cv2.dilate(plane, kernel).astype(np.float32) + budget
            values = candidate_rgb[..., channel].astype(np.float32)
            local_violation_count += int(
                np.count_nonzero((values < local_min) | (values > local_max))
            )
    overshoot_record_consistent = (
        activation != ACTIVE
        or recorded_overshoot_budget == profile_overshoot_budget
    )
    overshoot_pass = (
        overshoot_budget_finite
        and overshoot_record_consistent
        and local_violation_count == 0
    )

    raw_detection = (
        ((e1_result.get("safety_results") or {}).get("raw_detection") or {})
    )
    raw_halo = bool(raw_detection.get("halo_or_ringing", False))
    raw_white = bool(raw_detection.get("white_edge", False))
    raw_black = bool(raw_detection.get("black_edge", False))
    halo_pass = not (raw_halo or raw_white or raw_black)
    return {
        "case_id": case_id,
        "restoration_activation": activation,
        "residual": {
            "status": "PASS" if residual_pass else "FAIL",
            "actual_candidate_baseline_max_abs": actual_max_abs,
            "actual_nonzero_pixel_count": actual_nonzero_pixels,
            "profile_budget": profile_residual_budget,
            "recorded_budget": recorded_residual_budget,
            "recorded_max_abs": recorded_max_abs,
            "recorded_nonzero_pixel_count": recorded_nonzero,
            "record_consistent": residual_record_consistent,
        },
        "overshoot": {
            "status": "PASS" if overshoot_pass else "FAIL",
            "actual_local_extrema_violation_count": local_violation_count,
            "profile_budget": profile_overshoot_budget,
            "recorded_budget": recorded_overshoot_budget,
            "record_consistent": overshoot_record_consistent,
        },
        "halo_ringing": {
            "status": "PASS" if halo_pass else "FAIL",
            "raw_detection": {
                "halo_or_ringing": raw_halo,
                "white_edge": raw_white,
                "black_edge": raw_black,
            },
        },
    }


def derive_summary_evidence(
    *,
    records: list[dict[str, Any]],
    e1_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Derive V1 Summary facts without trusting Summary or integrity hashes."""

    if len(records) != len(e1_results):
        return {
            "version": "E4K04_EVIDENCE_DERIVED_SUMMARY_V1",
            "status": "FAIL",
            "failures": ["RECORD_E1_COUNT_MISMATCH"],
            "cases": [],
        }
    cases: list[dict[str, Any]] = []
    failures: list[str] = []
    for record, e1_result in zip(records, e1_results):
        case_id = e1_result.get("e1_01_case_id") or "UNKNOWN"
        baseline_ref = e1_result.get("baseline_reference") or {}
        candidate_ref = e1_result.get("candidate_reference") or {}
        baseline_path = _resolve(baseline_ref.get("path", ""))
        candidate_path = _resolve(candidate_ref.get("path", ""))
        if not baseline_path.is_file() or not candidate_path.is_file():
            failures.append(f"SUMMARY_PIXEL_EVIDENCE_MISSING:{case_id}")
            continue
        with Image.open(baseline_path) as opened:
            baseline = np.asarray(opened.convert("RGBA" if opened.mode == "RGBA" else "RGB"))
        with Image.open(candidate_path) as opened:
            candidate = np.asarray(opened.convert("RGBA" if opened.mode == "RGBA" else "RGB"))
        case = derive_case_summary_evidence(
            case_id=case_id,
            record=record,
            e1_result=e1_result,
            baseline_pixels=baseline,
            candidate_pixels=candidate,
        )
        cases.append(case)
        for field in ("residual", "overshoot", "halo_ringing"):
            if case[field]["status"] != "PASS":
                failures.append(f"{field.upper()}_EVIDENCE_FAIL:{case_id}")
    halo_count = sum(
        case["halo_ringing"]["raw_detection"]["halo_or_ringing"] for case in cases
    )
    white_count = sum(
        case["halo_ringing"]["raw_detection"]["white_edge"] for case in cases
    )
    black_count = sum(
        case["halo_ringing"]["raw_detection"]["black_edge"] for case in cases
    )
    return {
        "version": "E4K04_EVIDENCE_DERIVED_SUMMARY_V1",
        "status": "PASS" if not failures and len(cases) == len(records) else "FAIL",
        "failures": failures,
        "residual_budget": (
            "PASS" if cases and all(case["residual"]["status"] == "PASS" for case in cases) else "FAIL"
        ),
        "overshoot_control": (
            "PASS" if cases and all(case["overshoot"]["status"] == "PASS" for case in cases) else "FAIL"
        ),
        "halo_ringing_suppression": (
            "PASS" if cases and all(case["halo_ringing"]["status"] == "PASS" for case in cases) else "FAIL"
        ),
        "halo_ringing_count": halo_count,
        "white_edge_count": white_count,
        "black_edge_count": black_count,
        "cases": cases,
    }


def validate_summary_raw_evidence(
    summary: dict[str, Any], derived: dict[str, Any]
) -> list[str]:
    """Reject cross-layer semantic mismatches even when hashes are self-consistent."""

    failures: list[str] = []
    for field in (
        "residual_budget",
        "overshoot_control",
        "halo_ringing_suppression",
        "halo_ringing_count",
        "white_edge_count",
        "black_edge_count",
    ):
        if summary.get(field) != derived.get(field):
            failures.append(f"SUMMARY_RAW_EVIDENCE_MISMATCH:{field}")
    if derived.get("status") != "PASS":
        failures.append("DERIVED_EVIDENCE_STATUS_FAIL")
    return failures


def _build_summary(
    *,
    results: list[dict[str, Any]],
    records: list[dict[str, Any]],
    target_selection: dict[str, Any],
    calibration: dict[str, Any],
    determinism: dict[str, Any],
    human_review: dict[str, Any],
    protected: dict[str, Any],
) -> dict[str, Any]:
    paired = list(zip(results, records))
    target = [
        (result, record)
        for result, record in paired
        if (record.get("degradation_profile") or {}).get("status")
        == SUPPORTED_TARGET_DEGRADATION
    ]
    non_target = [(result, record) for result, record in paired if (result, record) not in target]
    e1_results = [result.get("e1_02_result") or {} for result in results]
    derived_summary = derive_summary_evidence(records=records, e1_results=e1_results)
    target_e1 = [result.get("e1_02_result") or {} for result, _record in target]
    target_quality = Counter(e1.get("quality_gain_status") for e1 in target_e1)
    target_safety_pass = sum(
        (e1.get("safety_results") or {}).get("status") == "PASS" for e1 in target_e1
    )
    automated_positive = sum(
        bool(
            (((e1.get("quality_gain_results") or {}).get("gt_evidence") or {}).get(
                "positive_direction_supported"
            ))
        )
        for e1 in target_e1
    )
    no_op_false_gain = sum(
        (result.get("quality_gain_status") == "QUALITY_GAIN_PROVEN")
        for result, _record in non_target
    )
    non_target_safety_fail = sum(
        result.get("safety_status") == "FAIL" for result, _record in non_target
    )
    raw = [
        ((e1.get("safety_results") or {}).get("raw_detection") or {})
        for e1 in e1_results
    ]
    alpha_failures = sum(
        ((e1.get("safety_results") or {}).get("alpha") or {}).get("status") == "FAIL"
        for e1 in e1_results
    )
    color_failures = sum(
        facts.get("color_shift", False)
        or facts.get("global_color_shift", False)
        or facts.get("local_color_shift", False)
        for facts in raw
    )
    target_rejected = target_quality.get("QUALITY_GAIN_REJECTED", 0)
    target_proven = target_quality.get("QUALITY_GAIN_PROVEN", 0)
    target_not_proven = target_quality.get("QUALITY_GAIN_NOT_PROVEN", 0)
    all_target_safe = target_safety_pass == len(target) == target_selection[
        "target_family_valid_cases"
    ]
    stable_gain = (
        "PROVEN"
        if len(target) >= 2
        and all_target_safe
        and target_proven >= 2
        and target_rejected == 0
        and color_failures == 0
        and alpha_failures == 0
        and _roi_damage_count(target_e1) == 0
        else "NOT_PROVEN"
    )
    automated_gain = (
        "POSITIVE"
        if automated_positive >= 2 and all_target_safe and target_rejected == 0
        else "INSUFFICIENT_OR_NEGATIVE"
    )
    if stable_gain == "PROVEN":
        status = "PASS"
        real_gain = "PROVEN"
        ready = "YES"
        blocker = "NONE"
        next_direction = "E4K_05_WITH_SEPARATE_FORMAL_AUTHORIZATION"
    elif automated_gain == "POSITIVE":
        status = "PASS_WITH_REVIEW_REQUIRED"
        real_gain = "NOT_PROVEN_PENDING_HUMAN_REVIEW"
        ready = "NO"
        blocker = "LEGAL_HUMAN_100_PERCENT_ROI_REVIEW_MISSING"
        next_direction = "COMPLETE_HUMAN_REVIEW_WITHOUT_PARAMETER_CHANGE"
    else:
        status = "PASS_WITH_TECHNICAL_CONCLUSION"
        real_gain = "NOT_PROVEN"
        ready = "NO"
        blocker = "V1_DID_NOT_ESTABLISH_STABLE_TARGET_FAMILY_GAIN"
        next_direction = (
            "LOCALIZE_TARGET_FAILURE_FROM_EXISTING_EVIDENCE; DO_NOT_RELAX_E1_02_"
            "OR_ADD_EXTERNAL_MODELS"
        )

    artifact_ok = (
        len(results) == EXPECTED_CASE_COUNT
        and all(result.get("execution_status") == "COMPLETED" for result in results)
        and all(result.get("actual_run_binding_status") == "PASS" for result in results)
        and all(e1.get("evaluation_status") == "COMPLETE" for e1 in e1_results)
        and all(record.get("source_unchanged") for record in records)
        and all(record.get("baseline_unchanged") for record in records)
        and all(not result.get("model_download") for result in results)
        and all(not result.get("model_inference_run") for result in results)
        and all(not result.get("model_benchmark") for result in results)
        and calibration["status"] == "PASS"
        and determinism["status"] == "PASS"
        and protected["status"] == "PASS"
        and derived_summary["status"] == "PASS"
        and all(record.get("restoration_activation") == ACTIVE for _result, record in target)
        and len(non_target) == 12
        and all(record.get("restoration_activation") == NO_OP for _result, record in non_target)
        and all(
            result.get("candidate_sha256") == result.get("baseline_sha256")
            for result, _record in non_target
        )
    )
    if not artifact_ok:
        status = "BLOCKED"
        real_gain = "NOT_PROVEN"
        ready = "NO"
        blocker = "EXPERIMENT_OR_PROTECTION_INTEGRITY_FAILURE"
        next_direction = "REPAIR_E4K_04_EVIDENCE_CHAIN_WITHOUT_CHANGING_GATE_SEMANTICS"

    return {
        "artifact_version": ARTIFACT_VERSION,
        "status": status,
        "version": "V0.5.7",
        "line": "E",
        "task_id": TASK_ID,
        "model_plan": "SELF_DEVELOPED_BOUNDED_RESTORATION",
        "formal_baseline": "PILLOW_LANCZOS",
        "external_enhancement_model": "NONE",
        "target_degradation_family": TARGET_DEGRADATION_FAMILY,
        "target_family_reason": target_selection["reason"],
        "target_family_valid_cases": len(target),
        "target_family_real_holdout_cases": len(target),
        "degradation_profile": DEGRADATION_PROFILE_VERSION,
        "bounded_restoration_core_created": True,
        "algorithm_id": ALGORITHM_ID,
        "algorithm_version": ALGORITHM_VERSION,
        "candidate_id": results[0]["candidate_id"],
        "raw_proposal": "SOURCE_LUMA_JPEG_8X8_BOUNDARY_CORRECTION_V1",
        "bounded_residual_contract": RESIDUAL_CONTRACT_VERSION,
        "evidence_derived_summary_version": derived_summary["version"],
        "evidence_derived_summary_status": derived_summary["status"],
        "residual_budget": derived_summary["residual_budget"],
        "high_frequency_budget": "PASS" if all(
            (record.get("bounded_residual") or {}).get("candidate_hf_energy", 0)
            <= (record.get("bounded_residual") or {}).get("hf_budget", float("inf"))
            + 1e-7
            for _result, record in target
        ) else "FAIL",
        "overshoot_control": derived_summary["overshoot_control"],
        "halo_ringing_suppression": derived_summary["halo_ringing_suppression"],
        "text_structure_protection": "PASS_NO_DAMAGE_DETECTED"
        if _roi_damage_count(e1_results) == 0
        else "FAIL",
        "color_lock": "PASS" if color_failures == 0 else "FAIL",
        "alpha_lock": "PASS" if alpha_failures == 0 else "FAIL",
        "determinism": "BYTE_IDENTICAL" if determinism["byte_identical"] else "FAIL",
        "e4k_02_connected": all(
            result.get("framework_version")
            == "HDDE_4K_ENHANCEMENT_CANDIDATE_FRAMEWORK_V1"
            for result in results
        ),
        "e1_02_connected": all(e1.get("evaluation_status") == "COMPLETE" for e1 in e1_results),
        "e1_01_cases_replayed": f"{len(results)}/{EXPECTED_CASE_COUNT}",
        "target_family_hard_safety_pass": f"{target_safety_pass}/{len(target)}",
        "target_family_quality_gain_proven_count": target_proven,
        "target_family_quality_gain_not_proven_count": target_not_proven,
        "target_family_quality_gain_rejected_count": target_rejected,
        "target_family_automated_positive_direction_count": automated_positive,
        "target_family_stable_gain": stable_gain,
        "non_target_no_op_cases": len(non_target),
        "no_op_false_positive_gain_count": no_op_false_gain,
        "non_target_new_hard_safety_failure_count": non_target_safety_fail,
        "oversharpen_count": sum(item.get("oversharpen", False) for item in raw),
        "halo_ringing_count": sum(item.get("halo_or_ringing", False) for item in raw),
        "white_edge_count": sum(item.get("white_edge", False) for item in raw),
        "black_edge_count": sum(item.get("black_edge", False) for item in raw),
        "text_damage_count": _roi_damage_count(e1_results),
        "color_failure_count": color_failures,
        "alpha_failure_count": alpha_failures,
        "human_review_status": human_review["human_review_status"],
        "automated_gain_evidence": automated_gain,
        "real_4k_quality_gain": real_gain,
        "controlled_calibration": calibration["status"],
        "artifact_path": _relative(OUTPUT_ROOT),
        "artifact_integrity": "PASS" if artifact_ok else "FAIL",
        "formal_4k_pipeline_changed": False,
        "api_4k_changed": False,
        "e1_01_changed": protected["e1_01_changed"],
        "e1_02_changed": protected["e1_02_changed"],
        "e4k_02_frozen_artifact_changed": protected[
            "e4k_02_frozen_artifact_changed"
        ],
        "product_version_changed": protected["product_version_changed"],
        "model_download": False,
        "external_model_inference": False,
        "external_model_benchmark": False,
        "model_adopted": False,
        "blocker": blocker,
        "ready_for_e4k_05": ready,
        "next_technical_direction": next_direction,
        "completed_at_utc": _utc_now(),
    }


def _write_integrity_manifest() -> dict[str, Any]:
    destination = OUTPUT_ROOT / "validation" / "artifact_integrity.json"
    files = [
        path
        for path in sorted(OUTPUT_ROOT.rglob("*"), key=lambda item: str(item).lower())
        if path.is_file() and path.resolve() != destination.resolve()
    ]
    entries = [
        {
            "path": path.relative_to(OUTPUT_ROOT).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in files
    ]
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    result = {
        "integrity_version": "E4K_04_ARTIFACT_INTEGRITY_V1",
        "status": "PASS",
        "file_count_excluding_this_manifest": len(entries),
        "tree_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "files": entries,
    }
    _write_json(destination, result)
    return result


def validate_artifact(root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    failures: list[str] = []
    integrity_path = root / "validation" / "artifact_integrity.json"
    summary_path = root / "summary.json"
    if not integrity_path.is_file():
        failures.append("INTEGRITY_MANIFEST_MISSING")
    if not summary_path.is_file():
        failures.append("SUMMARY_MISSING")
    if failures:
        return {"status": "BLOCKED", "failures": failures}
    expected = _read_json(integrity_path)
    files = [
        path
        for path in sorted(root.rglob("*"), key=lambda item: str(item).lower())
        if path.is_file() and path.resolve() != integrity_path.resolve()
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
    actual_tree = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if len(entries) != expected.get("file_count_excluding_this_manifest"):
        failures.append("FILE_COUNT_MISMATCH")
    if actual_tree != expected.get("tree_sha256"):
        failures.append("TREE_SHA256_MISMATCH")
    summary = _read_json(summary_path)
    required = {
        "e1_01_cases_replayed": "16/16",
        "e4k_02_connected": True,
        "e1_02_connected": True,
        "non_target_no_op_cases": 12,
        "no_op_false_positive_gain_count": 0,
        "non_target_new_hard_safety_failure_count": 0,
        "model_download": False,
        "external_model_inference": False,
        "external_model_benchmark": False,
        "formal_4k_pipeline_changed": False,
        "api_4k_changed": False,
        "e1_01_changed": False,
        "e1_02_changed": False,
        "e4k_02_frozen_artifact_changed": False,
        "product_version_changed": False,
    }
    for field, value in required.items():
        if summary.get(field) != value:
            failures.append(f"SUMMARY_FIELD_MISMATCH:{field}")
    case_files = sorted((root / "case_results").glob("E1C*.json"))
    if len(case_files) != EXPECTED_CASE_COUNT:
        failures.append(f"CASE_RESULT_COUNT:{len(case_files)}")
    candidate_ids = {
        _read_json(path).get("candidate_id") for path in case_files
    }
    if len(candidate_ids) != 1 or None in candidate_ids:
        failures.append("CANDIDATE_ID_NOT_UNIQUE")
    record_files = {
        path.stem: path for path in (root / "budget_records").glob("E1C*.json")
    }
    e1_files = {
        path.stem: path for path in (root / "e1_02_results").glob("E1C*.json")
    }
    if set(record_files) != set(e1_files) or len(record_files) != EXPECTED_CASE_COUNT:
        failures.append("SUMMARY_EVIDENCE_CASE_SET_MISMATCH")
    else:
        ordered_ids = sorted(record_files)
        try:
            derived = derive_summary_evidence(
                records=[_read_json(record_files[case_id]) for case_id in ordered_ids],
                e1_results=[_read_json(e1_files[case_id]) for case_id in ordered_ids],
            )
            failures.extend(validate_summary_raw_evidence(summary, derived))
        except Exception as exc:
            failures.append(
                f"SUMMARY_EVIDENCE_RECOMPUTE_FAILED:{type(exc).__name__}:{exc}"
            )
    return {
        "status": "PASS" if not failures else "BLOCKED",
        "failures": failures,
        "file_count": len(entries),
        "tree_sha256": actual_tree,
        "candidate_ids": sorted(value for value in candidate_ids if value),
        "summary_status": summary.get("status"),
        "real_4k_quality_gain": summary.get("real_4k_quality_gain"),
    }


def run_experiment() -> dict[str, Any]:
    manifest = _manifest()
    target_selection = _target_selection(manifest)
    definition = bounded_candidate_definition()
    candidate_id, identity = build_candidate_identity(definition)
    protected_before = protected_scope_state()
    if protected_before["status"] != "PASS":
        raise RuntimeError("PROTECTED_SCOPE_NOT_CLEAN_AT_E4K04_START")
    for name in (
        "degradation_profile",
        "candidate_runs",
        "budget_records",
        "protection_masks_metadata",
        "case_results",
        "roi_results",
        "e1_02_results",
        "comparison_assets",
        "validation",
    ):
        (OUTPUT_ROOT / name).mkdir(parents=True, exist_ok=True)
    manifest_path = OUTPUT_ROOT / "candidate_manifest.json"
    if manifest_path.is_file():
        existing = _read_json(manifest_path)
        if existing.get("candidate_id") != candidate_id:
            raise RuntimeError("EXISTING_E4K04_CANDIDATE_ID_MISMATCH")
    else:
        _write_json(
            manifest_path,
            {
                "artifact_version": ARTIFACT_VERSION,
                "status": "IN_PROGRESS",
                "created_at_utc": _utc_now(),
                "task_id": TASK_ID,
                "version": "V0.5.7",
                "line": "E",
                "candidate_id": candidate_id,
                "candidate_identity_contract": identity,
                "target_selection": target_selection,
                "formal_baseline": "PILLOW_LANCZOS",
                "external_model": "NONE",
                "quality_authority": "EXISTING_E1_02_ONLY",
                "human_review_policy": "REAL_REVIEW_REQUIRED_AUTOMATED_VERDICT_FORBIDDEN",
                "formal_production": False,
            },
        )
    _write_json(
        OUTPUT_ROOT / "degradation_profile" / "target_family_selection.json",
        target_selection,
    )
    calibration = run_controlled_calibration()
    _write_json(OUTPUT_ROOT / "validation" / "controlled_calibration.json", calibration)
    if calibration["status"] != "PASS":
        raise RuntimeError("CONTROLLED_CALIBRATION_FAILED")
    determinism = run_determinism(manifest, candidate_id)
    _write_json(OUTPUT_ROOT / "validation" / "determinism.json", determinism)
    if determinism["status"] != "PASS":
        raise RuntimeError("DETERMINISM_FAILED")

    results: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for index, case in enumerate(manifest["cases"], start=1):
        case_id = case["case_id"]
        result_path = OUTPUT_ROOT / "case_results" / f"{case_id}.json"
        if result_path.is_file():
            result = _read_json(result_path)
            print(f"E4K04_RESUME={index}/16;CASE={case_id}", flush=True)
        else:
            print(f"E4K04_START={index}/16;CASE={case_id}", flush=True)
            result = _run_case(
                case, definition, nonce=f"E4K04_E1_REPLAY_V1_{case_id}"
            )
            _write_json(result_path, result)
        if result.get("candidate_id") != candidate_id:
            raise RuntimeError(f"CANDIDATE_ID_MISMATCH:{case_id}")
        record = _core_record(result)
        _write_case_derivatives(case_id, result, record)
        results.append(result)
        records.append(record)
        print(
            f"E4K04_DONE={index}/16;CASE={case_id};"
            f"ACTIVATION={record.get('restoration_activation')};"
            f"STATE={result.get('candidate_state')};"
            f"SAFETY={result.get('safety_status')};"
            f"QUALITY={result.get('quality_gain_status')}",
            flush=True,
        )

    human_review = _build_human_review_package(results)
    protected_after = protected_scope_state()
    _write_json(
        OUTPUT_ROOT / "validation" / "protected_scope.json",
        {"before": protected_before, "after": protected_after},
    )
    summary = _build_summary(
        results=results,
        records=records,
        target_selection=target_selection,
        calibration=calibration,
        determinism=determinism,
        human_review=human_review,
        protected=protected_after,
    )
    _write_json(OUTPUT_ROOT / "summary.json", summary)
    current_manifest = _read_json(manifest_path)
    current_manifest.update(
        {
            "status": "COMPLETE",
            "completed_at_utc": _utc_now(),
            "e1_01_cases_replayed": summary["e1_01_cases_replayed"],
            "summary": _relative(OUTPUT_ROOT / "summary.json"),
            "human_review_package": _relative(
                OUTPUT_ROOT / "comparison_assets" / "human_review_package.json"
            ),
            "protected_scope": protected_after,
        }
    )
    _write_json(manifest_path, current_manifest)
    integrity = _write_integrity_manifest()
    validation = validate_artifact(OUTPUT_ROOT)
    if validation["status"] != "PASS":
        raise RuntimeError(f"ARTIFACT_VALIDATION_FAILED:{validation['failures']}")
    print(f"STATUS={summary['status']}", flush=True)
    print(f"CANDIDATE_ID={candidate_id}", flush=True)
    print(f"E1_01_CASES_REPLAYED={summary['e1_01_cases_replayed']}", flush=True)
    print(f"REAL_4K_QUALITY_GAIN={summary['real_4k_quality_gain']}", flush=True)
    print(f"ARTIFACT_PATH={OUTPUT_ROOT}", flush=True)
    return {"summary": summary, "integrity": integrity, "validation": validation}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("run", "validate"))
    args = parser.parse_args()
    result = run_experiment() if args.phase == "run" else validate_artifact(OUTPUT_ROOT)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), flush=True)
    return 0 if result.get("status", result.get("validation", {}).get("status")) != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
