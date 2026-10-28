"""Run E4K-04 Source-Domain Restoration Candidate V2.

Calibration uses only newly generated controlled probes.  E1 Source/Safe Base
pairs remain a final Holdout and are never used for parameter search.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import shutil
import sys
import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.hd_core.bounded_restoration import (  # noqa: E402
    ACTIVE,
    NO_OP,
    SAFE_PROFILE,
    apply_bounded_residual,
    build_degradation_profile,
    build_protection_scale,
)
from engine.hd_core.candidate_framework import (  # noqa: E402
    E102EvaluationContext,
    build_candidate_identity,
    run_4k_candidate,
    sha256_file,
)
from engine.hd_core.source_domain_restoration import (  # noqa: E402
    ALGORITHM_ID,
    ALGORITHM_VERSION,
    CALIBRATION_AUTHORITY_BINDING_VERSION,
    OPERATOR_TYPE,
    PROFILE_ID,
    QUALIFICATION_RULE_VERSION,
    RUNTIME_CALIBRATION_AUTHORIZATION_GATE_VERSION,
    SAFE_PROFILE_V2,
    TARGET_DEGRADATION_FAMILY,
    build_calibration_authority_binding,
    build_raw_source_proposal,
    build_source_degradation_profile,
    build_v2_threshold_provenance,
    restore_source_domain_candidate,
    source_domain_candidate_definition,
    source_domain_restoration_candidate,
    validate_runtime_calibration_authorization,
)
from tools.experiments.e1_02_quality_delivery_gate import (  # noqa: E402
    QUALITY_GAIN_NOT_PROVEN,
    QUALITY_GAIN_PROVEN,
    QUALITY_GAIN_REJECTED,
    evaluate_arrays,
)
from tools.experiments.e4k_04_bounded_restoration_core import (  # noqa: E402
    derive_case_summary_evidence,
    protected_scope_state,
    validate_summary_raw_evidence,
)


TASK_ID = "E4K-04_SOURCE_DOMAIN_RESTORATION_CANDIDATE_V2"
ARTIFACT_VERSION = "E4K_04_SOURCE_DOMAIN_RESTORATION_ARTIFACT_V2"
E1_MANIFEST = (
    REPO_ROOT / "artifacts" / "e1_01_real_information_baseline_v1" / "manifest.json"
)
E1_ZERO_RESULTS = REPO_ROOT / "artifacts" / "e1_02_quality_delivery_gate_v1" / "case_results"
V1_ARTIFACT = REPO_ROOT / "artifacts" / "e4k_04_bounded_restoration_core_v1"
OUTPUT_ROOT = REPO_ROOT / "artifacts" / "e4k_04_source_domain_restoration_v2"
EXPECTED_CASE_COUNT = 16
CALIBRATION_RATIOS = (0.02, 0.03, 0.04, 0.05)
CALIBRATION_LEVELS = {"MILD": 92, "MODERATE": 76}
CALIBRATION_SEMANTIC_RECOMPUTE_VERSION = "V2_CALIBRATION_SEMANTIC_RECOMPUTE_V1"
STEP0_TEST_EXECUTION_VERSION = "E4K04_STEP0_TEST_EXECUTION_V1"
CORRECTION_TEST_EXECUTION_VERSION = "E4K04_V2_CORRECTION_TEST_EXECUTION_V1"
ARTIFACT_PATH_CANONICALIZATION_VERSION = "ARTIFACT_PATH_CANONICALIZATION_V1"
RUNTIME_AUTHORIZATION_SEMANTIC_PROJECTION_VERSION = (
    "RUNTIME_AUTHORIZATION_SEMANTIC_PROJECTION_V1"
)
_SEMANTIC_SAFETY_CACHE: dict[tuple[str, str, str], str] = {}


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


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def _relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def runtime_authorization_semantic_projection(
    record: dict[str, Any],
) -> dict[str, Any]:
    """Return the strict authorization identity without host path spelling."""

    return {
        "version": RUNTIME_AUTHORIZATION_SEMANTIC_PROJECTION_VERSION,
        "authorization": {
            key: value
            for key, value in record.items()
            if key != "calibration_artifact_path"
        },
    }


def validate_calibration_artifact_path_binding(
    *,
    artifact_root: str | Path,
    recorded_calibration_path: str | Path | None,
    expected_calibration_path: str | Path,
) -> dict[str, Any]:
    """Resolve the recorded path and keep it inside the canonical artifact root."""

    root = Path(artifact_root).resolve()
    expected = Path(expected_calibration_path).resolve()
    failures: list[str] = []
    resolved: Path | None = None
    if recorded_calibration_path is None or str(recorded_calibration_path).strip() == "":
        failures.append("CALIBRATION_PATH_REQUIRED")
    else:
        try:
            recorded = Path(recorded_calibration_path)
            resolved = (
                recorded.resolve()
                if recorded.is_absolute()
                else (root / recorded).resolve()
            )
        except (OSError, RuntimeError, ValueError) as exc:
            failures.append(f"CALIBRATION_PATH_INVALID:{type(exc).__name__}")
    if resolved is not None:
        try:
            resolved.relative_to(root)
        except ValueError:
            failures.append("CALIBRATION_PATH_OUTSIDE_ARTIFACT_ROOT")
        if resolved != expected:
            failures.append("CALIBRATION_PATH_TARGET_MISMATCH")
        if not resolved.is_file():
            failures.append("CALIBRATION_PATH_TARGET_MISSING")
    unique_failures = sorted(set(failures))
    return {
        "version": ARTIFACT_PATH_CANONICALIZATION_VERSION,
        "status": "PASS" if not unique_failures else "FAIL",
        "failures": unique_failures,
        "resolved_calibration_artifact_path": (
            str(resolved) if resolved is not None else None
        ),
        "expected_calibration_artifact_path": str(expected),
        "artifact_root": str(root),
    }


def _tree_state(root: Path) -> dict[str, Any]:
    files = sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: str(path).lower(),
    )
    payload = "".join(
        f"{path.relative_to(root).as_posix()}\t{sha256_file(path)}\n"
        for path in files
    ).encode("utf-8")
    return {
        "path": _relative(root),
        "file_count": len(files),
        "tree_sha256": hashlib.sha256(payload).hexdigest(),
    }


def _rgba(rgb: np.ndarray, alpha: np.ndarray | None = None) -> np.ndarray:
    values = np.asarray(rgb, dtype=np.uint8)
    if values.ndim == 3 and values.shape[2] == 4:
        return values
    if alpha is None:
        alpha = np.full(values.shape[:2], 255, dtype=np.uint8)
    return np.dstack((values[..., :3], np.asarray(alpha, dtype=np.uint8)))


def _mae(reference: np.ndarray, candidate: np.ndarray) -> float:
    return float(
        np.mean(
            np.abs(
                np.asarray(reference, dtype=np.float32)[..., :3]
                - np.asarray(candidate, dtype=np.float32)[..., :3]
            )
        )
    )


def _synthetic_reference(kind: str, width: int = 384, height: int = 288) -> np.ndarray:
    yy, xx = np.indices((height, width), dtype=np.float32)
    if kind == "MATERIAL":
        base = 92.0 + 54.0 * (xx / max(width - 1, 1)) + 12.0 * np.sin(xx / 7.0)
        weave = 5.0 * np.sin((xx + yy) / 3.7) + 3.0 * np.cos((xx - yy) / 5.3)
        r = np.clip(base + weave + 18.0, 0, 255)
        g = np.clip(base + weave * 0.7 + 7.0, 0, 255)
        b = np.clip(base + weave * 0.4 - 9.0, 0, 255)
        rgb = np.dstack((r, g, b)).astype(np.uint8)
        image = Image.fromarray(rgb, "RGB")
        draw = ImageDraw.Draw(image)
        draw.ellipse((54, 54, 174, 174), outline=(50, 82, 118), width=5)
        draw.rectangle((230, 70, 338, 210), outline=(205, 190, 160), width=4)
        return np.asarray(image)
    if kind == "STRUCTURE":
        rgb = np.full((height, width, 3), (128, 136, 144), dtype=np.uint8)
        image = Image.fromarray(rgb, "RGB")
        draw = ImageDraw.Draw(image)
        for offset in range(18, width, 32):
            draw.line((offset, 16, offset, height - 16), fill=(42, 48, 55), width=2)
        for offset in range(20, height, 36):
            draw.line((16, offset, width - 16, offset), fill=(214, 220, 225), width=2)
        draw.rectangle((72, 62, 312, 226), outline=(20, 24, 28), width=5)
        draw.line((72, 226, 312, 62), fill=(238, 236, 230), width=3)
        return np.asarray(image)
    raise ValueError(f"UNKNOWN_CONTROL_KIND:{kind}")


def _safety_facts(
    baseline: np.ndarray, candidate: np.ndarray, *, gt: np.ndarray | None = None
) -> dict[str, Any]:
    evaluation = evaluate_arrays(
        _rgba(baseline),
        _rgba(candidate),
        gt_rgba=None if gt is None else _rgba(gt),
        candidate_class="PRODUCT",
    )
    raw = (evaluation.get("hard_safety_gate") or {}).get("raw_detection") or {}
    return {
        "status": (evaluation.get("hard_safety_gate") or {}).get("status"),
        "raw_detection": raw,
        "gt_evidence": evaluation.get("gt_evidence"),
        "quality_gain_status": evaluation.get("quality_gain_status"),
    }


def _calibration_variant(
    *,
    root: Path,
    clean: np.ndarray,
    kind: str,
    level: str,
    jpeg_quality: int,
    ratio: float,
) -> dict[str, Any]:
    case_root = root / f"{kind}_{level}_Q{jpeg_quality}_R{ratio:.2f}"
    case_root.mkdir(parents=True, exist_ok=True)
    source_path = case_root / "source.jpg"
    Image.fromarray(clean, "RGB").save(
        source_path, format="JPEG", quality=jpeg_quality, subsampling=2
    )
    with Image.open(source_path) as opened:
        source_decoded = np.asarray(opened.convert("RGB"))
    target_size = (clean.shape[1] * 2, clean.shape[0] * 2)
    baseline = np.asarray(
        Image.fromarray(source_decoded, "RGB").resize(
            target_size, Image.Resampling.LANCZOS
        )
    )
    gt = np.asarray(
        Image.fromarray(clean, "RGB").resize(target_size, Image.Resampling.LANCZOS)
    )
    profile = replace(SAFE_PROFILE_V2, dct_soft_threshold_ratio=ratio)
    raw_proposal, raw_residual, evidence, raw_record = build_raw_source_proposal(
        source_path, baseline, profile=profile
    )
    protection, protection_record = build_protection_scale(
        baseline, profile=SAFE_PROFILE
    )
    pre_bounded = np.clip(
        baseline.astype(np.float32) + raw_residual[..., None], 0, 255
    )
    pre_bounded = np.rint(pre_bounded).astype(np.uint8)
    candidate, bounded_record = apply_bounded_residual(
        baseline,
        raw_residual,
        protection_scale=protection,
        protection_reliable=protection_record["status"] == "PASS",
        profile=SAFE_PROFILE,
    )
    baseline_error = _mae(gt, baseline)
    raw_error = _mae(gt, raw_proposal)
    pre_error = _mae(gt, pre_bounded)
    candidate_error = _mae(gt, candidate)
    raw_safety = _safety_facts(baseline, raw_proposal, gt=gt)
    final_safety = _safety_facts(baseline, candidate, gt=gt)
    Image.fromarray(gt, "RGB").save(case_root / "gt.png", format="PNG")
    Image.fromarray(baseline, "RGB").save(case_root / "baseline.png", format="PNG")
    Image.fromarray(raw_proposal, "RGB").save(
        case_root / "raw_proposal.png", format="PNG"
    )
    Image.fromarray(candidate, "RGB").save(case_root / "candidate.png", format="PNG")
    return {
        "probe_id": f"CONTROL_{kind}_{level}",
        "kind": kind,
        "level": level,
        "jpeg_quality": jpeg_quality,
        "ratio": ratio,
        "source_degradation_error": round(_mae(clean, source_decoded), 10),
        "baseline_to_gt_error": round(baseline_error, 10),
        "raw_proposal_to_gt_error": round(raw_error, 10),
        "pre_bounding_to_gt_error": round(pre_error, 10),
        "candidate_to_gt_error": round(candidate_error, 10),
        "raw_relative_mae_improvement": round(
            (baseline_error - raw_error) / max(baseline_error, 1e-12), 12
        ),
        "pre_bounding_relative_mae_improvement": round(
            (baseline_error - pre_error) / max(baseline_error, 1e-12), 12
        ),
        "post_bounding_relative_mae_improvement": round(
            (baseline_error - candidate_error) / max(baseline_error, 1e-12), 12
        ),
        "raw_recovery_direction": (
            "POSITIVE_RECOVERY_DIRECTION" if raw_error < baseline_error else "NOT_POSITIVE"
        ),
        "pre_bounding_recovery_direction": (
            "POSITIVE_RECOVERY_DIRECTION" if pre_error < baseline_error else "NOT_POSITIVE"
        ),
        "post_bounding_recovery_direction": (
            "POSITIVE_RECOVERY_DIRECTION" if candidate_error < baseline_error else "NOT_POSITIVE"
        ),
        "raw_proposal_safety": raw_safety,
        "final_safety": final_safety,
        "raw_record": raw_record,
        "bounded_record": bounded_record,
        "protection_record": protection_record,
        "evidence_pixel_fraction": round(float(np.mean(evidence > 0)), 8),
        "residual_max_abs_after": int(
            np.max(np.abs(candidate.astype(np.int16) - baseline.astype(np.int16)))
        ),
        "rgb_channel_difference_identity": bool(
            np.array_equal(
                candidate.astype(np.int16)[..., 0] - candidate.astype(np.int16)[..., 1],
                baseline.astype(np.int16)[..., 0] - baseline.astype(np.int16)[..., 1],
            )
            and np.array_equal(
                candidate.astype(np.int16)[..., 2] - candidate.astype(np.int16)[..., 1],
                baseline.astype(np.int16)[..., 2] - baseline.astype(np.int16)[..., 1],
            )
        ),
        "asset_directory": str(case_root),
    }


def run_controlled_calibration(root: Path) -> dict[str, Any]:
    calibration_root = root / "controlled_calibration"
    grid_root = calibration_root / "grid"
    rows: list[dict[str, Any]] = []
    for ratio in CALIBRATION_RATIOS:
        for kind in ("MATERIAL", "STRUCTURE"):
            clean = _synthetic_reference(kind)
            for level, jpeg_quality in CALIBRATION_LEVELS.items():
                rows.append(
                    _calibration_variant(
                        root=grid_root,
                        clean=clean,
                        kind=kind,
                        level=level,
                        jpeg_quality=jpeg_quality,
                        ratio=ratio,
                    )
                )
    by_ratio: list[dict[str, Any]] = []
    for ratio in CALIBRATION_RATIOS:
        subset = [row for row in rows if row["ratio"] == ratio]
        all_positive = all(
            row["post_bounding_recovery_direction"] == "POSITIVE_RECOVERY_DIRECTION"
            for row in subset
        )
        all_safe = all(row["final_safety"]["status"] == "PASS" for row in subset)
        by_ratio.append(
            {
                "ratio": ratio,
                "case_count": len(subset),
                "all_post_bounding_positive": all_positive,
                "all_final_safety_pass": all_safe,
                "minimum_post_bounding_relative_mae_improvement": round(
                    min(row["post_bounding_relative_mae_improvement"] for row in subset),
                    12,
                ),
                "mean_post_bounding_relative_mae_improvement": round(
                    float(
                        np.mean(
                            [
                                row["post_bounding_relative_mae_improvement"]
                                for row in subset
                            ]
                        )
                    ),
                    12,
                ),
            }
        )
    qualified = [
        item
        for item in by_ratio
        if item["all_post_bounding_positive"] and item["all_final_safety_pass"]
    ]
    selected = (
        max(
            qualified,
            key=lambda item: (
                item["minimum_post_bounding_relative_mae_improvement"],
                -item["ratio"],
            ),
        )
        if qualified
        else None
    )
    formal_ratio = SAFE_PROFILE_V2.dct_soft_threshold_ratio
    formal_rows = [row for row in rows if row["ratio"] == formal_ratio]
    mild_positive = bool(formal_rows) and all(
        row["post_bounding_recovery_direction"] == "POSITIVE_RECOVERY_DIRECTION"
        for row in formal_rows
        if row["level"] == "MILD"
    )
    moderate_positive = bool(formal_rows) and all(
        row["post_bounding_recovery_direction"] == "POSITIVE_RECOVERY_DIRECTION"
        for row in formal_rows
        if row["level"] == "MODERATE"
    )
    hard_safety = bool(formal_rows) and all(
        row["final_safety"]["status"] == "PASS" for row in formal_rows
    )
    selected_matches_formal = selected is not None and selected["ratio"] == formal_ratio
    result = {
        "calibration_version": "E4K04_V2_CONTROLLED_CALIBRATION_V1",
        "status": (
            "PASS"
            if mild_positive and moderate_positive and hard_safety and selected_matches_formal
            else "FAIL"
        ),
        "calibration_set": "NEW_CONTROLLED_SYNTHETIC_JPEG_PROBES_ONLY",
        "holdout_set": "E1_01_16_CASES_FINAL_ONLY",
        "holdout_used_for_tuning": False,
        "parameter_search_phase": "PRE_HOLDOUT_ONLY",
        "parameter_grid": list(CALIBRATION_RATIOS),
        "selection_rule": "MAXIMIZE_WORST_CASE_POSITIVE_RELATIVE_MAE_GAIN_THEN_LOWEST_STRENGTH",
        "ratio_summaries": by_ratio,
        "selected_ratio": None if selected is None else selected["ratio"],
        "formal_ratio": formal_ratio,
        "selected_matches_formal_profile": selected_matches_formal,
        "controlled_mild_recovery_direction": "POSITIVE" if mild_positive else "NOT_POSITIVE",
        "controlled_moderate_recovery_direction": (
            "POSITIVE" if moderate_positive else "NOT_POSITIVE"
        ),
        "controlled_hard_safety": "PASS" if hard_safety else "FAIL",
        "raw_proposal_gain_evidence": (
            "POSITIVE"
            if formal_rows
            and all(
                row["raw_recovery_direction"] == "POSITIVE_RECOVERY_DIRECTION"
                for row in formal_rows
            )
            else "NOT_POSITIVE_FOR_ALL_PROBES"
        ),
        "pre_bounding_gain_evidence": (
            "POSITIVE"
            if formal_rows
            and all(
                row["pre_bounding_recovery_direction"] == "POSITIVE_RECOVERY_DIRECTION"
                for row in formal_rows
            )
            else "NOT_POSITIVE_FOR_ALL_PROBES"
        ),
        "post_bounding_gain_evidence": (
            "POSITIVE"
            if mild_positive and moderate_positive
            else "NOT_POSITIVE_FOR_ALL_PROBES"
        ),
        "gain_loss_stage": (
            "NONE"
            if mild_positive and moderate_positive
            else "BOUNDED_SAFETY_SYSTEM"
            if formal_rows
            and all(
                row["raw_recovery_direction"] == "POSITIVE_RECOVERY_DIRECTION"
                for row in formal_rows
            )
            else "SOURCE_OPERATOR"
        ),
        "formal_rows": formal_rows,
        "all_grid_rows": rows,
    }
    _write_json(calibration_root / "controlled_calibration.json", result)
    return result


def _read_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as opened:
        opened.load()
        return np.asarray(opened.convert("RGB"), dtype=np.uint8)


def _ratio_from_asset_directory(value: Any) -> tuple[str, float, str]:
    name = Path(str(value)).name
    if "_R" not in name:
        raise ValueError(f"CALIBRATION_ASSET_RATIO_MISSING:{name}")
    ratio = float(name.rsplit("_R", 1)[1])
    if "_MILD_" in name:
        level = "MILD"
    elif "_MODERATE_" in name:
        level = "MODERATE"
    else:
        raise ValueError(f"CALIBRATION_ASSET_LEVEL_MISSING:{name}")
    return name, ratio, level


def recompute_calibration_semantics(
    root: Path,
    calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Independently rebuild V2 calibration conclusions from stored pixels.

    This validator intentionally does not call ``run_controlled_calibration`` or
    reuse its final selection/status logic.  Only the shared low-level safety
    metric evaluator is reused.
    """

    calibration_path = root / "controlled_calibration" / "controlled_calibration.json"
    stored = calibration if calibration is not None else _read_json(calibration_path)
    rows = stored.get("all_grid_rows")
    failures: list[str] = []
    if not isinstance(rows, list):
        return {
            "version": CALIBRATION_SEMANTIC_RECOMPUTE_VERSION,
            "status": "FAIL",
            "failures": ["CALIBRATION_GRID_ROWS_INVALID"],
            "controlled_rows_recomputed": 0,
        }

    metric_mismatches: list[str] = []
    direction_mismatches: list[str] = []
    safety_mismatches: list[str] = []
    row_contract_mismatches: list[str] = []
    recomputed_rows: list[dict[str, Any]] = []
    seen_assets: set[str] = set()
    for index, row in enumerate(rows):
        row_id = str(row.get("probe_id") or f"ROW_{index:02d}")
        try:
            asset_name, ratio, level = _ratio_from_asset_directory(
                row.get("asset_directory")
            )
            asset_root = root / "controlled_calibration" / "grid" / asset_name
            if asset_name in seen_assets:
                raise ValueError(f"CALIBRATION_ASSET_DUPLICATED:{asset_name}")
            seen_assets.add(asset_name)
            gt = _read_rgb(asset_root / "gt.png")
            baseline = _read_rgb(asset_root / "baseline.png")
            candidate = _read_rgb(asset_root / "candidate.png")
            if gt.shape != baseline.shape or gt.shape != candidate.shape:
                raise ValueError(f"CALIBRATION_IMAGE_SHAPE_MISMATCH:{asset_name}")
            baseline_error = _mae(gt, baseline)
            candidate_error = _mae(gt, candidate)
            relative_improvement = (baseline_error - candidate_error) / max(
                baseline_error, 1e-12
            )
            direction = (
                "POSITIVE_RECOVERY_DIRECTION"
                if candidate_error < baseline_error
                else "NOT_POSITIVE"
            )
            safety_key = (
                sha256_file(asset_root / "baseline.png"),
                sha256_file(asset_root / "candidate.png"),
                sha256_file(asset_root / "gt.png"),
            )
            safety_status = _SEMANTIC_SAFETY_CACHE.get(safety_key)
            if safety_status is None:
                safety_status = _safety_facts(baseline, candidate, gt=gt)["status"]
                _SEMANTIC_SAFETY_CACHE[safety_key] = safety_status
        except Exception as exc:
            failures.append(
                f"CALIBRATION_ROW_RECOMPUTE_FAILED:{row_id}:{type(exc).__name__}:{exc}"
            )
            continue

        try:
            stored_ratio = float(row.get("ratio"))
        except (TypeError, ValueError):
            stored_ratio = float("nan")
        if not math.isfinite(stored_ratio) or stored_ratio != ratio:
            row_contract_mismatches.append(f"RATIO:{row_id}")
        if row.get("level") != level:
            row_contract_mismatches.append(f"LEVEL:{row_id}")
        for field, recomputed in (
            ("baseline_to_gt_error", baseline_error),
            ("candidate_to_gt_error", candidate_error),
            ("post_bounding_relative_mae_improvement", relative_improvement),
        ):
            try:
                stored_value = float(row.get(field))
            except (TypeError, ValueError):
                stored_value = float("nan")
            if not math.isfinite(stored_value) or not math.isclose(
                stored_value, recomputed, rel_tol=0.0, abs_tol=1e-9
            ):
                metric_mismatches.append(f"{field}:{row_id}@{ratio:.2f}")
        if row.get("post_bounding_recovery_direction") != direction:
            direction_mismatches.append(f"{row_id}@{ratio:.2f}")
        stored_safety = (row.get("final_safety") or {}).get("status")
        if stored_safety != safety_status:
            safety_mismatches.append(f"{row_id}@{ratio:.2f}")
        recomputed_rows.append(
            {
                "probe_id": row_id,
                "asset_directory": asset_name,
                "ratio": ratio,
                "level": level,
                "baseline_to_gt_error": round(baseline_error, 10),
                "candidate_to_gt_error": round(candidate_error, 10),
                "post_bounding_relative_mae_improvement": round(
                    relative_improvement, 12
                ),
                "positive_recovery_direction": direction,
                "hard_safety_status": safety_status,
            }
        )

    ratio_summaries: list[dict[str, Any]] = []
    for ratio in sorted({row["ratio"] for row in recomputed_rows}):
        subset = [row for row in recomputed_rows if row["ratio"] == ratio]
        improvements = [
            row["post_bounding_relative_mae_improvement"] for row in subset
        ]
        ratio_summaries.append(
            {
                "ratio": ratio,
                "case_count": len(subset),
                "all_post_bounding_positive": bool(subset)
                and all(
                    row["positive_recovery_direction"]
                    == "POSITIVE_RECOVERY_DIRECTION"
                    for row in subset
                ),
                "all_final_safety_pass": bool(subset)
                and all(row["hard_safety_status"] == "PASS" for row in subset),
                "minimum_post_bounding_relative_mae_improvement": round(
                    min(improvements), 12
                ),
                "mean_post_bounding_relative_mae_improvement": round(
                    float(np.mean(improvements)), 12
                ),
            }
        )
    qualified = [
        item
        for item in ratio_summaries
        if item["all_post_bounding_positive"]
        and item["all_final_safety_pass"]
    ]
    selected = (
        max(
            qualified,
            key=lambda item: (
                item["minimum_post_bounding_relative_mae_improvement"],
                -item["ratio"],
            ),
        )
        if qualified
        else None
    )
    selected_ratio = None if selected is None else selected["ratio"]
    formal_ratio = SAFE_PROFILE_V2.dct_soft_threshold_ratio
    formal_rows = [row for row in recomputed_rows if row["ratio"] == formal_ratio]
    mild_rows = [row for row in formal_rows if row["level"] == "MILD"]
    moderate_rows = [row for row in formal_rows if row["level"] == "MODERATE"]
    mild_positive = bool(mild_rows) and all(
        row["positive_recovery_direction"] == "POSITIVE_RECOVERY_DIRECTION"
        for row in mild_rows
    )
    moderate_positive = bool(moderate_rows) and all(
        row["positive_recovery_direction"] == "POSITIVE_RECOVERY_DIRECTION"
        for row in moderate_rows
    )
    hard_safety = bool(formal_rows) and all(
        row["hard_safety_status"] == "PASS" for row in formal_rows
    )
    recomputed_calibration_status = (
        "PASS"
        if mild_positive
        and moderate_positive
        and hard_safety
        and selected_ratio == formal_ratio
        else "FAIL"
    )

    qualification_mismatches: list[str] = []
    stored_summaries = stored.get("ratio_summaries")
    if not isinstance(stored_summaries, list):
        qualification_mismatches.append("RATIO_SUMMARIES_MISSING")
    else:
        stored_by_ratio = {item.get("ratio"): item for item in stored_summaries}
        for summary in ratio_summaries:
            current = stored_by_ratio.get(summary["ratio"])
            if current is None:
                qualification_mismatches.append(
                    f"RATIO_SUMMARY_MISSING:{summary['ratio']:.2f}"
                )
                continue
            for field in (
                "case_count",
                "all_post_bounding_positive",
                "all_final_safety_pass",
                "minimum_post_bounding_relative_mae_improvement",
                "mean_post_bounding_relative_mae_improvement",
            ):
                if current.get(field) != summary[field]:
                    qualification_mismatches.append(
                        f"RATIO_QUALIFICATION:{summary['ratio']:.2f}:{field}"
                    )
    if stored.get("parameter_grid") != [item["ratio"] for item in ratio_summaries]:
        qualification_mismatches.append("PARAMETER_GRID_MISMATCH")
    if stored.get("selected_ratio") != selected_ratio:
        qualification_mismatches.append("SELECTED_RATIO_MISMATCH")
    if stored.get("status") != recomputed_calibration_status:
        qualification_mismatches.append("CALIBRATION_STATUS_MISMATCH")

    if len(recomputed_rows) != 16:
        failures.append(f"CONTROLLED_ROW_COUNT_MISMATCH:{len(recomputed_rows)}")
    failures.extend(f"METRIC_MISMATCH:{item}" for item in metric_mismatches)
    failures.extend(f"DIRECTION_MISMATCH:{item}" for item in direction_mismatches)
    failures.extend(f"SAFETY_MISMATCH:{item}" for item in safety_mismatches)
    failures.extend(f"ROW_CONTRACT_MISMATCH:{item}" for item in row_contract_mismatches)
    failures.extend(qualification_mismatches)
    return {
        "version": CALIBRATION_SEMANTIC_RECOMPUTE_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "controlled_rows_recomputed": len(recomputed_rows),
        "metric_mismatch_count": len(metric_mismatches),
        "direction_mismatch_count": len(direction_mismatches),
        "hard_safety_mismatch_count": len(safety_mismatches),
        "row_contract_mismatch_count": len(row_contract_mismatches),
        "qualification_mismatch_count": len(qualification_mismatches),
        "recomputed_qualified_ratios": [item["ratio"] for item in qualified],
        "recomputed_selected_ratio": selected_ratio,
        "recomputed_calibration_status": recomputed_calibration_status,
        "qualification_rule_version": QUALIFICATION_RULE_VERSION,
        "ratio_summaries": ratio_summaries,
        "rows": recomputed_rows,
    }


def run_step0_tests_and_record(root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    from tests.hd_core import test_bounded_restoration

    suite = unittest.defaultTestLoader.loadTestsFromModule(test_bounded_restoration)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
    failed = len(result.failures) + len(result.errors) + len(result.unexpectedSuccesses)
    skipped = len(result.skipped)
    passed = result.testsRun - failed - skipped
    record = {
        "version": STEP0_TEST_EXECUTION_VERSION,
        "status": "PASS" if failed == 0 and skipped == 0 else "FAIL",
        "suite": "tests.hd_core.test_bounded_restoration",
        "tests_total": result.testsRun,
        "tests_passed": passed,
        "tests_failed": failed,
        "tests_skipped": skipped,
        "runner_output": stream.getvalue().strip(),
        "executed_at_utc": _utc_now(),
    }
    _write_json(root / "validation" / "step0_test_execution.json", record)
    return record


def _run_unittest_suite(suite: unittest.TestSuite) -> dict[str, Any]:
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
    failed = len(result.failures) + len(result.errors) + len(result.unexpectedSuccesses)
    skipped = len(result.skipped)
    passed = result.testsRun - failed - skipped
    return {
        "status": "PASS" if failed == 0 and skipped == 0 else "FAIL",
        "tests_total": result.testsRun,
        "tests_passed": passed,
        "tests_failed": failed,
        "tests_skipped": skipped,
        "runner_output": stream.getvalue().strip(),
    }


def run_correction_tests_and_record(root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    from tests.hd_core import test_source_domain_restoration

    v2_suite = unittest.defaultTestLoader.loadTestsFromModule(
        test_source_domain_restoration
    )
    v2_result = _run_unittest_suite(v2_suite)
    hd_core_suite = unittest.defaultTestLoader.discover(
        start_dir=str(REPO_ROOT / "tests" / "hd_core"),
        pattern="test_*.py",
        top_level_dir=str(REPO_ROOT),
    )
    hd_core_result = _run_unittest_suite(hd_core_suite)
    record = {
        "version": CORRECTION_TEST_EXECUTION_VERSION,
        "status": (
            "PASS"
            if v2_result["status"] == "PASS" and hd_core_result["status"] == "PASS"
            else "FAIL"
        ),
        "v2_specialized": v2_result,
        "hd_core_regression": hd_core_result,
        "executed_at_utc": _utc_now(),
    }
    _write_json(root / "validation" / "correction_test_execution.json", record)
    return record


def run_controlled_determinism(
    calibration: dict[str, Any],
    candidate_id: str,
    calibration_authority: dict[str, Any],
    calibration_artifact_path: Path,
    threshold_provenance: dict[str, Any],
) -> dict[str, Any]:
    formal_rows = calibration.get("formal_rows") or []
    if not formal_rows:
        return {
            "version": "E4K04_V2_CONTROLLED_DETERMINISM_V1",
            "status": "FAIL",
            "reason": "FORMAL_CONTROL_ROW_MISSING",
        }
    asset_root = Path(formal_rows[0]["asset_directory"])
    source = asset_root / "source.jpg"
    baseline = asset_root / "baseline.png"
    source_before = sha256_file(source)
    baseline_before = sha256_file(baseline)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        first = root / "first.png"
        second = root / "second.png"
        first_record = restore_source_domain_candidate(
            source,
            baseline,
            first,
            calibration_authority=calibration_authority,
            calibration_artifact_path=calibration_artifact_path,
            threshold_provenance=threshold_provenance,
            candidate_id=candidate_id,
        )
        second_record = restore_source_domain_candidate(
            source,
            baseline,
            second,
            calibration_authority=calibration_authority,
            calibration_artifact_path=calibration_artifact_path,
            threshold_provenance=threshold_provenance,
            candidate_id=candidate_id,
        )
        byte_identical = sha256_file(first) == sha256_file(second)
        pixel_identical = first_record.get("output_pixel_sha256") == second_record.get(
            "output_pixel_sha256"
        )
    unchanged = (
        sha256_file(source) == source_before and sha256_file(baseline) == baseline_before
    )
    return {
        "version": "E4K04_V2_CONTROLLED_DETERMINISM_V1",
        "status": "PASS" if byte_identical and pixel_identical and unchanged else "FAIL",
        "candidate_id": candidate_id,
        "control_probe_id": formal_rows[0]["probe_id"],
        "repeat_count": 2,
        "byte_identical": byte_identical,
        "pixel_sha256_identical": pixel_identical,
        "source_and_baseline_unchanged": unchanged,
        "e1_holdout_used": False,
    }


def _build_controlled_stop_summary(
    *,
    selection: dict[str, Any],
    calibration: dict[str, Any],
    candidate_id: str,
    determinism: dict[str, Any],
    protected: dict[str, Any],
    calibration_authority: dict[str, Any],
    threshold: dict[str, Any],
    runtime_authorization: dict[str, Any],
    semantic_recompute: dict[str, Any],
    step0_tests: dict[str, Any],
    correction_tests: dict[str, Any] | None = None,
) -> dict[str, Any]:
    formal_rows = calibration.get("formal_rows") or []
    final_raw = [
        (row.get("final_safety") or {}).get("raw_detection") or {}
        for row in formal_rows
    ]
    raw_proposal = [
        (row.get("raw_proposal_safety") or {}).get("raw_detection") or {}
        for row in formal_rows
    ]
    residual_pass = bool(formal_rows) and all(
        row.get("residual_max_abs_after", 999)
        <= SAFE_PROFILE.residual_absolute_budget
        for row in formal_rows
    )
    hf_pass = bool(formal_rows) and all(
        (row.get("bounded_record") or {}).get("candidate_hf_energy", 0)
        <= (row.get("bounded_record") or {}).get("hf_budget", float("inf")) + 1e-7
        for row in formal_rows
    )
    overshoot_pass = bool(formal_rows) and all(
        (row.get("bounded_record") or {}).get("overshoot_budget") == 0.0
        for row in formal_rows
    )
    color_pass = bool(formal_rows) and all(
        row.get("rgb_channel_difference_identity") is True for row in formal_rows
    )
    return {
        "artifact_version": ARTIFACT_VERSION,
        "status": "PASS_WITH_TECHNICAL_CONCLUSION",
        "version": "V0.5.7",
        "line": "E",
        "task_id": TASK_ID,
        "correction_task_id": "E4K-04_V2_PATH_CANONICALIZATION_CORRECTION_03",
        "model_plan": "SELF_DEVELOPED_SOURCE_DOMAIN_RESTORATION",
        "formal_baseline": "PILLOW_LANCZOS",
        "external_enhancement_model": "NONE",
        "v1_route_status": "STOPPED_NO_RETUNE",
        "step0_evidence_derived_summary": (
            "PASS_FROM_TEST_EXECUTION_RECORD_AND_V1_PIXEL_RECOMPUTE"
            if step0_tests.get("status") == "PASS"
            else "FAIL_OR_MISSING_TEST_EXECUTION_RECORD"
        ),
        "step0_tests_total": step0_tests.get("tests_total"),
        "step0_tests_passed": step0_tests.get("tests_passed"),
        "step0_tests_failed": step0_tests.get("tests_failed"),
        "step0_test_count_source": "validation/step0_test_execution.json",
        "step0_threshold_provenance": threshold["status"],
        "target_degradation_family": selection["target_degradation_family"],
        "target_family_selection_evidence": selection["status"],
        "target_family_real_holdout_cases": selection[
            "target_family_real_holdout_cases"
        ],
        "source_domain_operator": OPERATOR_TYPE,
        "operator_selection_reason": (
            "DIRECT_JPEG_QUANTIZATION_EVIDENCE_AND_PRE_HOLDOUT_CONTROLLED_COMPARISON"
        ),
        "operator_status": "STOPPED_CONTROLLED_MILD_NOT_POSITIVE",
        "stop_v2_operator": "YES",
        "algorithm_id": ALGORITHM_ID,
        "algorithm_version": ALGORITHM_VERSION,
        "candidate_id": candidate_id,
        "calibration_set": calibration["calibration_set"],
        "holdout_set": calibration["holdout_set"],
        "holdout_used_for_tuning": False,
        "calibration_authority_binding": calibration_authority["binding_status"],
        "calibration_artifact_sha256": calibration_authority[
            "calibration_artifact_sha256"
        ],
        "current_calibration_status": calibration_authority["calibration_status"],
        "current_selected_ratio": calibration_authority["selected_ratio"],
        "candidate_execution_authorized": calibration_authority[
            "candidate_execution_authorized"
        ],
        "runtime_calibration_authorization_gate": (
            "PASS"
            if runtime_authorization["status"] == "FAIL"
            and runtime_authorization["candidate_execution_authorized"] is False
            else "FAIL"
        ),
        "runtime_calibration_authorization_status": runtime_authorization["status"],
        "runtime_calibration_authorization_gate_version": runtime_authorization[
            "version"
        ],
        "current_qualified_ratios": len(
            runtime_authorization.get("qualified_ratios", [])
        ),
        "calibration_sha_binding": (
            "PASS"
            if runtime_authorization.get("actual_calibration_sha256")
            == runtime_authorization.get("bound_calibration_artifact_sha256")
            else "FAIL"
        ),
        "current_source_operator_executed": False,
        "calibration_fail_execution_result": "NO_OP_BASELINE_BYTE_IDENTITY",
        "controlled_mild_recovery_direction": calibration[
            "controlled_mild_recovery_direction"
        ],
        "controlled_moderate_recovery_direction": calibration[
            "controlled_moderate_recovery_direction"
        ],
        "controlled_hard_safety": calibration["controlled_hard_safety"],
        "raw_proposal_source_bound": "PASS",
        "raw_proposal_gain_evidence": calibration["raw_proposal_gain_evidence"],
        "bounded_residual_contract": "PASS" if residual_pass else "FAIL",
        "pre_bounding_gain_evidence": calibration["pre_bounding_gain_evidence"],
        "post_bounding_gain_evidence": calibration["post_bounding_gain_evidence"],
        "gain_loss_stage": calibration["gain_loss_stage"],
        "high_frequency_budget": "PASS" if hf_pass else "FAIL",
        "residual_budget": "PASS" if residual_pass else "FAIL",
        "overshoot_control": "PASS" if overshoot_pass else "FAIL",
        "halo_ringing_suppression": (
            "PASS"
            if all(
                not item.get("halo_or_ringing", False)
                and not item.get("white_edge", False)
                and not item.get("black_edge", False)
                for item in final_raw
            )
            else "FAIL"
        ),
        "text_structure_protection": "PASS_CONTROLLED_MASK_ENFORCED",
        "color_lock": "PASS" if color_pass else "FAIL",
        "alpha_lock": "PASS_UNIT_PATH_NOT_E1_EXECUTED",
        "determinism": (
            "BYTE_IDENTICAL" if determinism.get("byte_identical") else "FAIL"
        ),
        "threshold_provenance_status": threshold["status"],
        "uncalibrated_threshold_count": threshold["uncalibrated_threshold_count"],
        "v2_calibration_semantic_recompute": semantic_recompute["status"],
        "controlled_rows_recomputed": semantic_recompute[
            "controlled_rows_recomputed"
        ],
        "metric_mismatch_count": semantic_recompute["metric_mismatch_count"],
        "direction_mismatch_count": semantic_recompute[
            "direction_mismatch_count"
        ],
        "recomputed_qualified_ratios": semantic_recompute[
            "recomputed_qualified_ratios"
        ],
        "recomputed_selected_ratio": semantic_recompute[
            "recomputed_selected_ratio"
        ],
        "recomputed_calibration_status": semantic_recompute[
            "recomputed_calibration_status"
        ],
        "e4k_02_connected": "IMPLEMENTED_AND_UNIT_VERIFIED_NO_HOLDOUT_RUN",
        "e1_02_connected": "NOT_RUN_CONTROLLED_GATE_STOP",
        "e1_cases_replayed": "0/16",
        "target_family_hard_safety_pass": "NOT_RUN_CONTROLLED_GATE_STOP",
        "target_family_quality_gain_proven_count": 0,
        "target_family_quality_gain_not_proven_count": 0,
        "target_family_quality_gain_rejected_count": 0,
        "target_family_stable_gain": "NOT_PROVEN",
        "non_target_no_op_cases": "NOT_RUN_CONTROLLED_GATE_STOP",
        "no_op_false_positive_gain_count": 0,
        "non_target_new_hard_safety_failure_count": 0,
        "raw_proposal_oversharpen_count": sum(
            item.get("oversharpen", False) for item in raw_proposal
        ),
        "raw_proposal_halo_ringing_count": sum(
            item.get("halo_or_ringing", False) for item in raw_proposal
        ),
        "raw_proposal_white_edge_count": sum(
            item.get("white_edge", False) for item in raw_proposal
        ),
        "raw_proposal_black_edge_count": sum(
            item.get("black_edge", False) for item in raw_proposal
        ),
        "oversharpen_count": sum(item.get("oversharpen", False) for item in final_raw),
        "halo_ringing_count": sum(
            item.get("halo_or_ringing", False) for item in final_raw
        ),
        "white_edge_count": sum(item.get("white_edge", False) for item in final_raw),
        "black_edge_count": sum(item.get("black_edge", False) for item in final_raw),
        "text_damage_count": 0,
        "color_failure_count": 0 if color_pass else 1,
        "alpha_failure_count": 0,
        "human_review_status": "NOT_TRIGGERED_NO_E1_AUTOMATED_POSITIVE",
        "automated_gain_evidence": "INSUFFICIENT_OR_NEGATIVE_CONTROLLED",
        "real_4k_quality_gain": "NOT_PROVEN",
        "tests": (
            f"V2_FROM_EXECUTION_RECORD:"
            f"{((correction_tests or {}).get('v2_specialized') or {}).get('tests_passed')}"
            f"/{((correction_tests or {}).get('v2_specialized') or {}).get('tests_total')}:"
            f"{((correction_tests or {}).get('v2_specialized') or {}).get('status')}"
            if correction_tests
            else (
                f"STEP0_FROM_EXECUTION_RECORD:{step0_tests.get('tests_passed')}"
                f"/{step0_tests.get('tests_total')}:{step0_tests.get('status')}"
            )
        ),
        "regression": (
            f"HD_CORE_FROM_EXECUTION_RECORD:"
            f"{((correction_tests or {}).get('hd_core_regression') or {}).get('tests_passed')}"
            f"/{((correction_tests or {}).get('hd_core_regression') or {}).get('tests_total')}:"
            f"{((correction_tests or {}).get('hd_core_regression') or {}).get('status')}"
            if correction_tests
            else "PENDING_FINAL_REGRESSION"
        ),
        "artifact_path": _relative(OUTPUT_ROOT),
        "artifact_integrity": "PASS",
        "formal_4k_pipeline_changed": False,
        "api_4k_changed": False,
        "e1_01_changed": protected["e1_01_changed"],
        "e1_02_changed": protected["e1_02_changed"],
        "e4k_02_frozen_artifact_changed": protected[
            "e4k_02_frozen_artifact_changed"
        ],
        "product_version_changed": protected["product_version_changed"],
        "blocker": "SOURCE_OPERATOR_CONTROLLED_MILD_RECOVERY_NOT_POSITIVE",
        "ready_for_e4k_05": "NO",
        "next_technical_direction": (
            "STOP_DCT_SHRINKAGE_V2; REQUIRE_FUNDAMENTALLY_NEW_CONTROLLED_SOURCE_RECOVERY_EVIDENCE"
        ),
        "completed_at_utc": _utc_now(),
    }


def _case_source_risk(case: dict[str, Any]) -> dict[str, Any]:
    source_path = _resolve(case["input"]["path"])
    inherited = build_degradation_profile(source_path)
    with Image.open(source_path) as opened:
        rgba = np.asarray(opened.convert("RGBA"), dtype=np.uint8)
    hsv = cv2.cvtColor(rgba[..., :3], cv2.COLOR_RGB2HSV)
    alpha_nonopaque = float(np.mean(rgba[..., 3] != 255))
    return {
        "case_id": case["case_id"],
        "text_like_roi_ratio": (inherited.get("text_like_risk") or {}).get("text_mask_ratio"),
        "strong_edge_ratio": (inherited.get("edge_evidence") or {}).get("canny_edge_fraction"),
        "protected_structure_ratio": "NEED_PROOF_UNTIL_COMPARISON_SURFACE",
        "color_saturation_p95_ratio": round(float(np.percentile(hsv[..., 1], 95)) / 255.0, 8),
        "alpha_nonopaque_ratio": round(alpha_nonopaque, 8),
    }


def _historical_baseline_headroom(case_id: str) -> float | None:
    path = E1_ZERO_RESULTS / f"ZERO__{case_id}.json"
    if not path.is_file():
        return None
    result = _read_json(path)
    gt = ((result.get("quality_gain_results") or {}).get("gt_evidence") or {})
    return (((gt.get("baseline_to_gt") or {}).get("delta_metrics") or {}).get("rgb_mae"))


def build_target_family_selection(manifest: dict[str, Any]) -> dict[str, Any]:
    cases = manifest["cases"]
    source_profiles = {
        case["case_id"]: build_source_degradation_profile(_resolve(case["input"]["path"]))
        for case in cases
    }
    risks = {case["case_id"]: _case_source_risk(case) for case in cases}
    families: dict[str, list[dict[str, Any]]] = {
        "BLUR": [case for case in cases if case["degradation_type"] == "BLUR_JPEG"],
        "MULTI_RESIZE": [
            case for case in cases if case["degradation_type"] == "MULTI_RESIZE"
        ],
        TARGET_DEGRADATION_FAMILY: [
            case
            for case in cases
            if source_profiles[case["case_id"]]["status"]
            == "SUPPORTED_TARGET_DEGRADATION"
        ],
        "SCREENSHOT_LIKE": [
            case for case in cases if case["degradation_type"] == "SCREENSHOT_LIKE"
        ],
    }
    rows: list[dict[str, Any]] = []
    for family, subset in families.items():
        risk_rows = [risks[case["case_id"]] for case in subset]
        headroom = [
            value
            for value in (_historical_baseline_headroom(case["case_id"]) for case in subset)
            if isinstance(value, (int, float))
        ]
        quant_means = [
            source_profiles[case["case_id"]]["compression_evidence"][
                "luma_quantization_mean"
            ]
            for case in subset
            if source_profiles[case["case_id"]]["compression_evidence"][
                "luma_quantization_mean"
            ]
            is not None
        ]
        direct_operator = family == TARGET_DEGRADATION_FAMILY and len(subset) >= 2
        gt_count = sum(case.get("gt") is not None for case in subset)
        selection_rule_pass = len(subset) >= 2 and gt_count >= 2 and direct_operator
        rows.append(
            {
                "family": family,
                "case_ids": [case["case_id"] for case in subset],
                "valid_case_count": len(subset),
                "real_holdout_count": len(subset),
                "gt_available_count": gt_count,
                "baseline_error_headroom": {
                    "status": "HISTORICAL_FROZEN_E1_BASELINE_ONLY_NOT_PARAMETER_TUNING",
                    "mean_rgb_mae": round(float(np.mean(headroom)), 8) if headroom else None,
                    "case_count": len(headroom),
                },
                "source_degradation_strength": {
                    "status": "MEASURED" if quant_means else "NEED_PROOF",
                    "mean_luma_quantization_step": (
                        round(float(np.mean(quant_means)), 8) if quant_means else None
                    ),
                },
                "recoverable_structure_evidence": {
                    "status": "MEASURED" if direct_operator else "NEED_PROOF",
                    "mean_strong_edge_ratio": (
                        round(
                            float(
                                np.mean(
                                    [
                                        row["strong_edge_ratio"]
                                        for row in risk_rows
                                        if isinstance(row["strong_edge_ratio"], (int, float))
                                    ]
                                )
                            ),
                            8,
                        )
                        if any(
                            isinstance(row["strong_edge_ratio"], (int, float))
                            for row in risk_rows
                        )
                        else None
                    ),
                    "direct_quantization_response": direct_operator,
                },
                "text_structure_risk": {
                    "status": "MEASURED" if risk_rows else "NEED_PROOF",
                    "mean_text_like_roi_ratio": (
                        round(
                            float(
                                np.mean(
                                    [
                                        row["text_like_roi_ratio"]
                                        for row in risk_rows
                                        if isinstance(row["text_like_roi_ratio"], (int, float))
                                    ]
                                )
                            ),
                            8,
                        )
                        if any(
                            isinstance(row["text_like_roi_ratio"], (int, float))
                            for row in risk_rows
                        )
                        else None
                    ),
                    "mean_strong_edge_ratio": (
                        round(
                            float(
                                np.mean(
                                    [
                                        row["strong_edge_ratio"]
                                        for row in risk_rows
                                        if isinstance(row["strong_edge_ratio"], (int, float))
                                    ]
                                )
                            ),
                            8,
                        )
                        if any(
                            isinstance(row["strong_edge_ratio"], (int, float))
                            for row in risk_rows
                        )
                        else None
                    ),
                    "protected_structure_ratio": "NEED_PROOF_UNTIL_COMPARISON_SURFACE",
                },
                "color_risk": {
                    "status": "MEASURED" if risk_rows else "NEED_PROOF",
                    "mean_saturation_p95_ratio": (
                        round(
                            float(
                                np.mean(
                                    [row["color_saturation_p95_ratio"] for row in risk_rows]
                                )
                            ),
                            8,
                        )
                        if risk_rows
                        else None
                    ),
                },
                "alpha_risk": {
                    "status": "MEASURED" if risk_rows else "NEED_PROOF",
                    "maximum_nonopaque_ratio": (
                        max(row["alpha_nonopaque_ratio"] for row in risk_rows)
                        if risk_rows
                        else None
                    ),
                },
                "operator_applicability": (
                    "DIRECT_JPEG_QUANTIZATION_EVIDENCE"
                    if direct_operator
                    else "UNSUPPORTED_BY_SELECTED_OPERATOR"
                ),
                "selection_rule_pass": selection_rule_pass,
            }
        )
    selected = [row for row in rows if row["selection_rule_pass"]]
    if len(selected) != 1:
        raise RuntimeError(f"TARGET_FAMILY_SELECTION_NOT_UNIQUE:{len(selected)}")
    return {
        "version": "TARGET_FAMILY_SELECTION_V2",
        "status": "PASS",
        "selection_rule": (
            "VALID_CASES_GTE_2_AND_GT_GTE_2_AND_DIRECT_OPERATOR_EVIDENCE_REQUIRED"
        ),
        "unsupported_reason_strings_used_as_numeric_fact": False,
        "e1_gt_pixels_read_for_parameter_tuning": False,
        "target_degradation_family": selected[0]["family"],
        "target_family_real_holdout_cases": selected[0]["real_holdout_count"],
        "target_case_ids": selected[0]["case_ids"],
        "families": rows,
    }


def _runtime_context() -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "technology": "SELF_DEVELOPED_SOURCE_DOMAIN_RESTORATION",
        "backend": "NUMPY_OPENCV_PILLOW_CPU",
        "device": "CPU",
        "precision": "FLOAT32_ANALYSIS_UINT8_DETERMINISTIC_OUTPUT",
        "profile_id": PROFILE_ID,
        "target_degradation_family": TARGET_DEGRADATION_FAMILY,
        "external_model": "NONE",
    }


def _run_case(
    case: dict[str, Any],
    definition: Any,
    *,
    nonce: str,
    calibration_authority: dict[str, Any],
    calibration_artifact_path: Path,
    threshold_provenance: dict[str, Any],
) -> dict[str, Any]:
    return run_4k_candidate(
        _resolve(case["input"]["path"]),
        OUTPUT_ROOT / "candidate_runs",
        definition=definition,
        executor=partial(
            source_domain_restoration_candidate,
            calibration_authority=calibration_authority,
            calibration_artifact_path=calibration_artifact_path,
            threshold_provenance=threshold_provenance,
        ),
        baseline_path=_resolve(case["safe_base"]["path"]),
        e1_02_context=E102EvaluationContext(E1_MANIFEST, case["case_id"]),
        runtime_context=_runtime_context(),
        execution_nonce=nonce,
    )


def _core_record(result: dict[str, Any]) -> dict[str, Any]:
    run_dir = _resolve(result["evidence_refs"]["run_directory"])
    path = run_dir / "budget_records" / "source_domain_restoration_record.json"
    if not path.is_file():
        raise RuntimeError(f"SOURCE_DOMAIN_RECORD_MISSING:{path}")
    return _read_json(path)


def _raw_proposal_safety(result: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    raw_path_value = record.get("raw_proposal_path")
    if not raw_path_value:
        return {
            "status": "NOT_APPLICABLE_NO_OP",
            "raw_detection": {
                "oversharpen": False,
                "halo_or_ringing": False,
                "white_edge": False,
                "black_edge": False,
            },
        }
    raw_path = Path(raw_path_value)
    if not raw_path.is_absolute():
        raw_path = _resolve(raw_path)
    e1 = result.get("e1_02_result") or {}
    baseline_path = _resolve((e1.get("baseline_reference") or {})["path"])
    with Image.open(baseline_path) as opened:
        baseline = np.asarray(opened.convert("RGB"))
    with Image.open(raw_path) as opened:
        raw = np.asarray(opened.convert("RGB"))
    return _safety_facts(baseline, raw)


def _write_case_derivatives(
    case_id: str, result: dict[str, Any], record: dict[str, Any]
) -> dict[str, Any]:
    raw_safety = _raw_proposal_safety(result, record)
    record = dict(record)
    record["raw_proposal_safety"] = raw_safety
    _write_json(OUTPUT_ROOT / "budget_records" / f"{case_id}.json", record)
    _write_json(
        OUTPUT_ROOT / "degradation_profiles" / f"{case_id}.json",
        record.get("degradation_profile"),
    )
    _write_json(
        OUTPUT_ROOT / "raw_proposal_records" / f"{case_id}.json",
        {
            "case_id": case_id,
            "raw_proposal": record.get("raw_proposal"),
            "raw_proposal_path": record.get("raw_proposal_path"),
            "raw_proposal_safety": raw_safety,
        },
    )
    _write_json(
        OUTPUT_ROOT / "protection_records" / f"{case_id}.json",
        record.get("protection_masks_metadata"),
    )
    _write_json(OUTPUT_ROOT / "case_results" / f"{case_id}.json", result)
    _write_json(
        OUTPUT_ROOT / "e1_02_results" / f"{case_id}.json",
        result.get("e1_02_result"),
    )
    _write_json(
        OUTPUT_ROOT / "roi_comparisons" / f"{case_id}.json",
        {
            "case_id": case_id,
            "evidence": (result.get("evidence_refs") or {}).get("e1_02"),
        },
    )
    return record


def run_determinism(
    manifest: dict[str, Any],
    candidate_id: str,
    calibration_authority: dict[str, Any],
    calibration_artifact_path: Path,
    threshold_provenance: dict[str, Any],
) -> dict[str, Any]:
    target = next(
        case
        for case in manifest["cases"]
        if build_source_degradation_profile(_resolve(case["input"]["path"]))["status"]
        == "SUPPORTED_TARGET_DEGRADATION"
    )
    source = _resolve(target["input"]["path"])
    baseline = _resolve(target["safe_base"]["path"])
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        first = root / "first.png"
        second = root / "second.png"
        first_record = restore_source_domain_candidate(
            source,
            baseline,
            first,
            calibration_authority=calibration_authority,
            calibration_artifact_path=calibration_artifact_path,
            threshold_provenance=threshold_provenance,
            candidate_id=candidate_id,
        )
        second_record = restore_source_domain_candidate(
            source,
            baseline,
            second,
            calibration_authority=calibration_authority,
            calibration_artifact_path=calibration_artifact_path,
            threshold_provenance=threshold_provenance,
            candidate_id=candidate_id,
        )
        byte_identical = sha256_file(first) == sha256_file(second)
        pixel_identical = first_record["output_pixel_sha256"] == second_record[
            "output_pixel_sha256"
        ]
    return {
        "version": "E4K04_V2_DETERMINISM_V1",
        "status": "PASS" if byte_identical and pixel_identical else "FAIL",
        "case_id": target["case_id"],
        "candidate_id": candidate_id,
        "repeat_count": 2,
        "byte_identical": byte_identical,
        "pixel_sha256_identical": pixel_identical,
    }


def _adapt_record_for_derived_summary(record: dict[str, Any]) -> dict[str, Any]:
    adapted = dict(record)
    profile = record.get("profile") or {}
    adapted["profile"] = profile.get("bounded_safety_profile") or {}
    return adapted


def _derived_summary(
    records: list[dict[str, Any]], results: list[dict[str, Any]]
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    failures: list[str] = []
    for record, result in zip(records, results):
        e1 = result.get("e1_02_result") or {}
        baseline_path = _resolve((e1.get("baseline_reference") or {})["path"])
        candidate_path = _resolve((e1.get("candidate_reference") or {})["path"])
        with Image.open(baseline_path) as opened:
            baseline = np.asarray(opened.convert("RGB"))
        with Image.open(candidate_path) as opened:
            candidate = np.asarray(opened.convert("RGB"))
        case = derive_case_summary_evidence(
            case_id=e1.get("e1_01_case_id") or "UNKNOWN",
            record=_adapt_record_for_derived_summary(record),
            e1_result=e1,
            baseline_pixels=baseline,
            candidate_pixels=candidate,
        )
        cases.append(case)
        for field in ("residual", "overshoot", "halo_ringing"):
            if case[field]["status"] != "PASS":
                failures.append(f"{field.upper()}_FAIL:{case['case_id']}")
    return {
        "version": "E4K04_EVIDENCE_DERIVED_SUMMARY_V1",
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "residual_budget": "PASS" if all(case["residual"]["status"] == "PASS" for case in cases) else "FAIL",
        "overshoot_control": "PASS" if all(case["overshoot"]["status"] == "PASS" for case in cases) else "FAIL",
        "halo_ringing_suppression": "PASS" if all(case["halo_ringing"]["status"] == "PASS" for case in cases) else "FAIL",
        "halo_ringing_count": sum(
            case["halo_ringing"]["raw_detection"]["halo_or_ringing"] for case in cases
        ),
        "white_edge_count": sum(
            case["halo_ringing"]["raw_detection"]["white_edge"] for case in cases
        ),
        "black_edge_count": sum(
            case["halo_ringing"]["raw_detection"]["black_edge"] for case in cases
        ),
        "cases": cases,
    }


def _build_human_review_package(
    results: list[dict[str, Any]], target_case_ids: set[str]
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for result in results:
        e1 = result.get("e1_02_result") or {}
        case_id = e1.get("e1_01_case_id")
        if case_id not in target_case_ids:
            continue
        positive = bool(
            (((e1.get("quality_gain_results") or {}).get("gt_evidence") or {}).get(
                "positive_direction_supported"
            ))
        )
        if not positive:
            continue
        cases.append(
            {
                "case_id": case_id,
                "source": (e1.get("original_reference") or {}).get("path"),
                "baseline": (e1.get("baseline_reference") or {}).get("path"),
                "candidate": (e1.get("candidate_reference") or {}).get("path"),
                "gt": (e1.get("gt_reference_or_none") or {}).get("path"),
                "full_and_roi_assets": (result.get("evidence_refs") or {}).get("e1_02"),
                "required_views": [
                    "FULL",
                    "100_PERCENT_CROP",
                    "TEXT_ROI",
                    "EDGE_ROI",
                    "MATERIAL_ROI",
                    "HIGH_CONTRAST_ROI",
                ],
                "human_verdict": "PENDING",
            }
        )
    package = {
        "version": "E4K04_V2_HUMAN_REVIEW_PACKAGE_V1",
        "status": "READY" if cases else "NOT_TRIGGERED_NO_AUTOMATED_POSITIVE",
        "human_review_status": "NEED_REVIEW" if cases else "NOT_TRIGGERED",
        "automated_verdict_forbidden": True,
        "case_count": len(cases),
        "cases": cases,
    }
    _write_json(OUTPUT_ROOT / "roi_comparisons" / "human_review_package.json", package)
    return package


def _build_summary(
    *,
    results: list[dict[str, Any]],
    records: list[dict[str, Any]],
    selection: dict[str, Any],
    calibration: dict[str, Any],
    determinism: dict[str, Any],
    protected: dict[str, Any],
    human_review: dict[str, Any],
    threshold: dict[str, Any],
    calibration_authority: dict[str, Any],
    semantic_recompute: dict[str, Any],
    step0_tests: dict[str, Any],
) -> dict[str, Any]:
    target_ids = set(selection["target_case_ids"])
    paired = list(zip(results, records))
    target = [
        (result, record)
        for result, record in paired
        if (result.get("e1_02_result") or {}).get("e1_01_case_id") in target_ids
    ]
    non_target = [item for item in paired if item not in target]
    target_e1 = [result.get("e1_02_result") or {} for result, _record in target]
    all_e1 = [result.get("e1_02_result") or {} for result in results]
    quality = Counter(e1.get("quality_gain_status") for e1 in target_e1)
    target_safe = sum(
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
    raw_final = [
        ((e1.get("safety_results") or {}).get("raw_detection") or {}) for e1 in all_e1
    ]
    raw_proposal = [
        ((record.get("raw_proposal_safety") or {}).get("raw_detection") or {})
        for record in records
    ]
    derived = _derived_summary(records, results)
    no_op_false_gain = sum(
        (result.get("quality_gain_status") == QUALITY_GAIN_PROVEN)
        for result, _record in non_target
    )
    non_target_safety_fail = sum(
        result.get("safety_status") == "FAIL" for result, _record in non_target
    )
    all_target_safe = target_safe == len(target) == len(target_ids)
    rejected = quality.get(QUALITY_GAIN_REJECTED, 0)
    automated_gain = (
        "POSITIVE"
        if automated_positive >= 2 and all_target_safe and rejected == 0
        else "INSUFFICIENT_OR_NEGATIVE"
    )
    if automated_gain == "POSITIVE":
        status = "PASS_WITH_REVIEW_REQUIRED"
        stable_gain = "NOT_PROVEN_PENDING_HUMAN_REVIEW"
        real_gain = "NOT_PROVEN_PENDING_HUMAN_REVIEW"
        blocker = "LEGAL_HUMAN_100_PERCENT_ROI_REVIEW_MISSING"
        next_direction = "COMPLETE_HUMAN_REVIEW_WITHOUT_PARAMETER_CHANGE"
    else:
        status = "PASS_WITH_TECHNICAL_CONCLUSION"
        stable_gain = "NOT_PROVEN"
        real_gain = "NOT_PROVEN"
        blocker = "E1_02_AUTOMATED_TARGET_GAIN_BELOW_TWO_SAFE_CASES"
        next_direction = "STOP_V2_OPERATOR_AND_LOCALIZE_FAILURE_STAGE"
    artifact_ok = (
        len(results) == EXPECTED_CASE_COUNT
        and len(target) == len(target_ids)
        and all(record.get("restoration_activation") == ACTIVE for _result, record in target)
        and all(record.get("restoration_activation") == NO_OP for _result, record in non_target)
        and all(
            result.get("candidate_sha256") == result.get("baseline_sha256")
            for result, _record in non_target
        )
        and all(result.get("actual_run_binding_status") == "PASS" for result in results)
        and all(e1.get("evaluation_status") == "COMPLETE" for e1 in all_e1)
        and calibration["status"] == "PASS"
        and determinism["status"] == "PASS"
        and protected["status"] == "PASS"
        and derived["status"] == "PASS"
    )
    if not artifact_ok:
        status = "BLOCKED"
        real_gain = "NOT_PROVEN"
        stable_gain = "NOT_PROVEN"
        blocker = "EXPERIMENT_OR_EVIDENCE_INTEGRITY_FAILURE"
        next_direction = "REPAIR_EVIDENCE_CHAIN_WITHOUT_RERUNNING_HOLDOUT_PARAMETERS"
    color_failures = sum(
        raw.get("color_shift", False)
        or raw.get("global_color_shift", False)
        or raw.get("local_color_shift", False)
        for raw in raw_final
    )
    alpha_failures = sum(
        ((e1.get("safety_results") or {}).get("alpha") or {}).get("status") == "FAIL"
        for e1 in all_e1
    )
    text_damage = sum(
        roi.get("text_fidelity") == "TEXT_DEGRADED"
        for e1 in all_e1
        for roi in (e1.get("roi_results") or [])
    )
    return {
        "artifact_version": ARTIFACT_VERSION,
        "status": status,
        "version": "V0.5.7",
        "line": "E",
        "task_id": TASK_ID,
        "model_plan": "SELF_DEVELOPED_SOURCE_DOMAIN_RESTORATION",
        "formal_baseline": "PILLOW_LANCZOS",
        "external_enhancement_model": "NONE",
        "v1_route_status": "STOPPED_NO_RETUNE",
        "step0_evidence_derived_summary": derived["status"],
        "step0_tests_total": step0_tests.get("tests_total"),
        "step0_tests_passed": step0_tests.get("tests_passed"),
        "step0_tests_failed": step0_tests.get("tests_failed"),
        "step0_test_count_source": "validation/step0_test_execution.json",
        "step0_threshold_provenance": threshold["status"],
        "target_degradation_family": selection["target_degradation_family"],
        "target_family_selection_evidence": selection["status"],
        "target_family_real_holdout_cases": selection["target_family_real_holdout_cases"],
        "source_domain_operator": OPERATOR_TYPE,
        "operator_selection_reason": "CONTROLLED_GT_DIRECTION_AND_DIRECT_JPEG_QUANTIZATION_EVIDENCE",
        "algorithm_id": ALGORITHM_ID,
        "algorithm_version": ALGORITHM_VERSION,
        "candidate_id": results[0]["candidate_id"],
        "calibration_set": calibration["calibration_set"],
        "holdout_set": calibration["holdout_set"],
        "holdout_used_for_tuning": False,
        "calibration_authority_binding": calibration_authority["binding_status"],
        "current_calibration_status": calibration_authority["calibration_status"],
        "current_selected_ratio": calibration_authority["selected_ratio"],
        "candidate_execution_authorized": calibration_authority[
            "candidate_execution_authorized"
        ],
        "controlled_mild_recovery_direction": calibration[
            "controlled_mild_recovery_direction"
        ],
        "controlled_moderate_recovery_direction": calibration[
            "controlled_moderate_recovery_direction"
        ],
        "controlled_hard_safety": calibration["controlled_hard_safety"],
        "raw_proposal_source_bound": "PASS",
        "raw_proposal_gain_evidence": calibration["raw_proposal_gain_evidence"],
        "bounded_residual_contract": "BOUNDED_RESIDUAL_CONTRACT_V1",
        "pre_bounding_gain_evidence": calibration["pre_bounding_gain_evidence"],
        "post_bounding_gain_evidence": calibration["post_bounding_gain_evidence"],
        "gain_loss_stage": calibration["gain_loss_stage"],
        "high_frequency_budget": "PASS" if all(
            (record.get("bounded_residual") or {}).get("candidate_hf_energy", 0)
            <= (record.get("bounded_residual") or {}).get("hf_budget", float("inf"))
            + 1e-7
            for _result, record in target
        ) else "FAIL",
        "residual_budget": derived["residual_budget"],
        "overshoot_control": derived["overshoot_control"],
        "halo_ringing_suppression": derived["halo_ringing_suppression"],
        "text_structure_protection": "PASS" if text_damage == 0 else "FAIL",
        "color_lock": "PASS" if color_failures == 0 else "FAIL",
        "alpha_lock": "PASS" if alpha_failures == 0 else "FAIL",
        "determinism": "BYTE_IDENTICAL" if determinism["byte_identical"] else "FAIL",
        "threshold_provenance_status": threshold["status"],
        "uncalibrated_threshold_count": threshold["uncalibrated_threshold_count"],
        "v2_calibration_semantic_recompute": semantic_recompute["status"],
        "controlled_rows_recomputed": semantic_recompute[
            "controlled_rows_recomputed"
        ],
        "metric_mismatch_count": semantic_recompute["metric_mismatch_count"],
        "direction_mismatch_count": semantic_recompute[
            "direction_mismatch_count"
        ],
        "recomputed_qualified_ratios": semantic_recompute[
            "recomputed_qualified_ratios"
        ],
        "recomputed_selected_ratio": semantic_recompute[
            "recomputed_selected_ratio"
        ],
        "recomputed_calibration_status": semantic_recompute[
            "recomputed_calibration_status"
        ],
        "e4k_02_connected": all(
            result.get("framework_version")
            == "HDDE_4K_ENHANCEMENT_CANDIDATE_FRAMEWORK_V1"
            for result in results
        ),
        "e1_02_connected": all(e1.get("evaluation_status") == "COMPLETE" for e1 in all_e1),
        "e1_cases_replayed": f"{len(results)}/{EXPECTED_CASE_COUNT}",
        "target_family_hard_safety_pass": f"{target_safe}/{len(target)}",
        "target_family_quality_gain_proven_count": quality.get(QUALITY_GAIN_PROVEN, 0),
        "target_family_quality_gain_not_proven_count": quality.get(
            QUALITY_GAIN_NOT_PROVEN, 0
        ),
        "target_family_quality_gain_rejected_count": rejected,
        "target_family_automated_positive_direction_count": automated_positive,
        "target_family_stable_gain": stable_gain,
        "non_target_no_op_cases": len(non_target),
        "no_op_false_positive_gain_count": no_op_false_gain,
        "non_target_new_hard_safety_failure_count": non_target_safety_fail,
        "raw_proposal_oversharpen_count": sum(
            item.get("oversharpen", False) for item in raw_proposal
        ),
        "raw_proposal_halo_ringing_count": sum(
            item.get("halo_or_ringing", False) for item in raw_proposal
        ),
        "raw_proposal_white_edge_count": sum(
            item.get("white_edge", False) for item in raw_proposal
        ),
        "raw_proposal_black_edge_count": sum(
            item.get("black_edge", False) for item in raw_proposal
        ),
        "oversharpen_count": sum(item.get("oversharpen", False) for item in raw_final),
        "halo_ringing_count": derived["halo_ringing_count"],
        "white_edge_count": derived["white_edge_count"],
        "black_edge_count": derived["black_edge_count"],
        "text_damage_count": text_damage,
        "color_failure_count": color_failures,
        "alpha_failure_count": alpha_failures,
        "human_review_status": human_review["human_review_status"],
        "automated_gain_evidence": automated_gain,
        "real_4k_quality_gain": real_gain,
        "tests": (
            f"STEP0_FROM_EXECUTION_RECORD:{step0_tests.get('tests_passed')}"
            f"/{step0_tests.get('tests_total')}:{step0_tests.get('status')}"
        ),
        "regression": "PENDING_FINAL_REGRESSION",
        "artifact_path": _relative(OUTPUT_ROOT),
        "artifact_integrity": "PASS" if artifact_ok else "FAIL",
        "formal_4k_pipeline_changed": False,
        "api_4k_changed": False,
        "e1_01_changed": protected["e1_01_changed"],
        "e1_02_changed": protected["e1_02_changed"],
        "e4k_02_frozen_artifact_changed": protected["e4k_02_frozen_artifact_changed"],
        "product_version_changed": protected["product_version_changed"],
        "blocker": blocker,
        "ready_for_e4k_05": "NO" if real_gain != "PROVEN" else "YES",
        "next_technical_direction": next_direction,
        "completed_at_utc": _utc_now(),
    }


def _write_integrity_manifest(root: Path = OUTPUT_ROOT) -> dict[str, Any]:
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
        "version": "E4K04_V2_ARTIFACT_INTEGRITY_V1",
        "status": "PASS",
        "file_count_excluding_manifest": len(entries),
        "tree_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "files": entries,
    }
    _write_json(destination, result)
    return result


def validate_artifact(root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    root = Path(root).resolve()
    failures: list[str] = []
    manifest_path = root / "integrity_manifest.json"
    summary_path = root / "summary.json"
    calibration_path = root / "controlled_calibration" / "controlled_calibration.json"
    provenance_path = root / "threshold_provenance" / "threshold_provenance_v2.json"
    semantic_path = root / "validation" / "calibration_semantic_recompute.json"
    step0_path = root / "validation" / "step0_test_execution.json"
    candidate_identity_path = root / "candidate_identity.json"
    runtime_authorization_path = (
        root / "validation" / "runtime_calibration_authorization.json"
    )
    for path, code in (
        (manifest_path, "INTEGRITY_MANIFEST_MISSING"),
        (summary_path, "SUMMARY_MISSING"),
        (calibration_path, "CONTROLLED_CALIBRATION_MISSING"),
        (provenance_path, "THRESHOLD_PROVENANCE_MISSING"),
        (semantic_path, "CALIBRATION_SEMANTIC_RECOMPUTE_MISSING"),
        (step0_path, "STEP0_TEST_EXECUTION_RECORD_MISSING"),
        (candidate_identity_path, "CANDIDATE_IDENTITY_MISSING"),
        (
            runtime_authorization_path,
            "RUNTIME_CALIBRATION_AUTHORIZATION_MISSING",
        ),
    ):
        if not path.is_file():
            failures.append(code)
    if failures:
        return {"status": "BLOCKED", "failures": failures}
    expected = _read_json(manifest_path)
    files = [
        path
        for path in sorted(root.rglob("*"), key=lambda item: str(item).lower())
        if path.is_file() and path.resolve() != manifest_path.resolve()
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
    if len(entries) != expected.get("file_count_excluding_manifest"):
        failures.append("FILE_COUNT_MISMATCH")
    if tree_sha != expected.get("tree_sha256"):
        failures.append("TREE_SHA256_MISMATCH")

    calibration = _read_json(calibration_path)
    semantic = recompute_calibration_semantics(root, calibration)
    if semantic["status"] != "PASS":
        failures.extend(
            f"CALIBRATION_SEMANTIC:{item}" for item in semantic["failures"]
        )
    stored_semantic = _read_json(semantic_path)
    if stored_semantic != semantic:
        failures.append("CALIBRATION_SEMANTIC_RECORD_MISMATCH")

    calibration_hash = sha256_file(calibration_path)
    authority = build_calibration_authority_binding(
        calibration,
        calibration_artifact_sha256=calibration_hash,
    )
    if authority["binding_status"] != "PASS":
        failures.extend(
            f"CALIBRATION_AUTHORITY_BINDING:{item}"
            for item in authority["binding_failures"]
        )
    expected_provenance = build_v2_threshold_provenance(
        SAFE_PROFILE_V2,
        calibration_authority=authority,
    )
    stored_provenance = _read_json(provenance_path)
    if stored_provenance != expected_provenance:
        failures.append("THRESHOLD_PROVENANCE_BINDING_MISMATCH")

    definition = source_domain_candidate_definition(
        calibration_authority=authority
    )
    expected_candidate_id, expected_identity = build_candidate_identity(definition)
    stored_identity = _read_json(candidate_identity_path)
    if stored_identity.get("candidate_id") != expected_candidate_id:
        failures.append("CANDIDATE_ID_CALIBRATION_BINDING_MISMATCH")
    if stored_identity.get("candidate_identity_contract") != expected_identity:
        failures.append("CANDIDATE_IDENTITY_CONTRACT_MISMATCH")
    if (
        stored_identity.get("candidate_execution_authorized")
        is not authority["candidate_execution_authorized"]
    ):
        failures.append("CANDIDATE_IDENTITY_AUTHORIZATION_MISMATCH")
    runtime_authorization = validate_runtime_calibration_authorization(
        calibration_artifact_path=calibration_path,
        calibration_authority=authority,
        threshold_provenance=stored_provenance,
        candidate_id=expected_candidate_id,
        profile=SAFE_PROFILE_V2,
    )
    stored_runtime_authorization = _read_json(runtime_authorization_path)
    path_binding = validate_calibration_artifact_path_binding(
        artifact_root=root,
        recorded_calibration_path=stored_runtime_authorization.get(
            "calibration_artifact_path"
        ),
        expected_calibration_path=calibration_path,
    )
    if path_binding["status"] != "PASS":
        failures.extend(path_binding["failures"])
    stored_runtime_projection = runtime_authorization_semantic_projection(
        stored_runtime_authorization
    )
    runtime_projection = runtime_authorization_semantic_projection(
        runtime_authorization
    )
    if stored_runtime_projection != runtime_projection:
        failures.append("RUNTIME_CALIBRATION_AUTHORIZATION_RECORD_MISMATCH")

    step0_tests = _read_json(step0_path)
    if step0_tests.get("version") != STEP0_TEST_EXECUTION_VERSION:
        failures.append("STEP0_TEST_EXECUTION_VERSION_MISMATCH")
    if step0_tests.get("status") != "PASS":
        failures.append("STEP0_TEST_EXECUTION_NOT_PASS")
    correction_path = root / "validation" / "correction_test_execution.json"
    correction_tests = _read_json(correction_path) if correction_path.is_file() else None
    if correction_tests is not None:
        if correction_tests.get("version") != CORRECTION_TEST_EXECUTION_VERSION:
            failures.append("CORRECTION_TEST_EXECUTION_VERSION_MISMATCH")
        if correction_tests.get("status") != "PASS":
            failures.append("CORRECTION_TEST_EXECUTION_NOT_PASS")
    summary = _read_json(summary_path)
    controlled_stop = (
        summary.get("status") == "PASS_WITH_TECHNICAL_CONCLUSION"
        and summary.get("blocker")
        == "SOURCE_OPERATOR_CONTROLLED_MILD_RECOVERY_NOT_POSITIVE"
    )
    required = {
        "holdout_used_for_tuning": False,
        "no_op_false_positive_gain_count": 0,
        "non_target_new_hard_safety_failure_count": 0,
        "formal_4k_pipeline_changed": False,
        "api_4k_changed": False,
        "e1_01_changed": False,
        "e1_02_changed": False,
        "e4k_02_frozen_artifact_changed": False,
        "product_version_changed": False,
        "calibration_authority_binding": authority["binding_status"],
        "current_calibration_status": authority["calibration_status"],
        "current_selected_ratio": authority["selected_ratio"],
        "candidate_execution_authorized": authority[
            "candidate_execution_authorized"
        ],
        "runtime_calibration_authorization_gate": (
            "PASS"
            if calibration.get("status") == "FAIL"
            and runtime_authorization["status"] == "FAIL"
            and runtime_authorization["candidate_execution_authorized"] is False
            else "FAIL"
        ),
        "runtime_calibration_authorization_status": runtime_authorization["status"],
        "runtime_calibration_authorization_gate_version": (
            RUNTIME_CALIBRATION_AUTHORIZATION_GATE_VERSION
        ),
        "current_qualified_ratios": len(authority["qualified_ratios"]),
        "calibration_sha_binding": (
            "PASS"
            if runtime_authorization.get("actual_calibration_sha256")
            == runtime_authorization.get("bound_calibration_artifact_sha256")
            else "FAIL"
        ),
        "current_source_operator_executed": False,
        "calibration_fail_execution_result": "NO_OP_BASELINE_BYTE_IDENTITY",
        "threshold_provenance_status": expected_provenance["status"],
        "uncalibrated_threshold_count": expected_provenance[
            "uncalibrated_threshold_count"
        ],
        "v2_calibration_semantic_recompute": semantic["status"],
        "controlled_rows_recomputed": semantic["controlled_rows_recomputed"],
        "metric_mismatch_count": semantic["metric_mismatch_count"],
        "direction_mismatch_count": semantic["direction_mismatch_count"],
        "recomputed_qualified_ratios": semantic[
            "recomputed_qualified_ratios"
        ],
        "recomputed_selected_ratio": semantic["recomputed_selected_ratio"],
        "recomputed_calibration_status": semantic[
            "recomputed_calibration_status"
        ],
        "step0_tests_total": step0_tests["tests_total"],
        "step0_tests_passed": step0_tests["tests_passed"],
        "step0_tests_failed": step0_tests["tests_failed"],
        "step0_test_count_source": "validation/step0_test_execution.json",
    }
    for field, value in required.items():
        if summary.get(field) != value:
            failures.append(f"SUMMARY_FIELD_MISMATCH:{field}")
    if correction_tests is not None:
        v2_tests = correction_tests.get("v2_specialized") or {}
        regression_tests = correction_tests.get("hd_core_regression") or {}
        expected_tests = (
            f"V2_FROM_EXECUTION_RECORD:{v2_tests.get('tests_passed')}"
            f"/{v2_tests.get('tests_total')}:{v2_tests.get('status')}"
        )
        expected_regression = (
            f"HD_CORE_FROM_EXECUTION_RECORD:{regression_tests.get('tests_passed')}"
            f"/{regression_tests.get('tests_total')}:{regression_tests.get('status')}"
        )
        if summary.get("tests") != expected_tests:
            failures.append("SUMMARY_TEST_EXECUTION_RECORD_MISMATCH")
        if summary.get("regression") != expected_regression:
            failures.append("SUMMARY_REGRESSION_EXECUTION_RECORD_MISMATCH")
    if controlled_stop:
        stop_required = {
            "controlled_mild_recovery_direction": "NOT_POSITIVE",
            "controlled_hard_safety": "PASS",
            "e1_cases_replayed": "0/16",
            "e1_02_connected": "NOT_RUN_CONTROLLED_GATE_STOP",
            "real_4k_quality_gain": "NOT_PROVEN",
            "ready_for_e4k_05": "NO",
            "threshold_provenance_status": "NEED_CALIBRATION",
            "candidate_execution_authorized": False,
            "current_calibration_status": "FAIL",
            "current_selected_ratio": None,
            "recomputed_qualified_ratios": [],
            "recomputed_selected_ratio": None,
            "recomputed_calibration_status": "FAIL",
            "stop_v2_operator": "YES",
            "runtime_calibration_authorization_gate": "PASS",
            "runtime_calibration_authorization_status": "FAIL",
            "current_qualified_ratios": 0,
            "current_source_operator_executed": False,
            "calibration_fail_execution_result": "NO_OP_BASELINE_BYTE_IDENTITY",
        }
        for field, value in stop_required.items():
            if summary.get(field) != value:
                failures.append(f"STOP_SUMMARY_FIELD_MISMATCH:{field}")
        if calibration.get("status") != "FAIL":
            failures.append("CONTROLLED_FAILURE_EVIDENCE_MISSING")
        if expected_provenance["uncalibrated_threshold_count"] < 1:
            failures.append("FAILED_CALIBRATION_HAS_NO_UNCALIBRATED_THRESHOLD")
        if authority["candidate_execution_authorized"] is not False:
            failures.append("FAILED_CALIBRATION_EXECUTION_AUTHORIZED")
        if any((root / "case_results").glob("E1C*.json")):
            failures.append("E1_HOLDOUT_RAN_AFTER_CONTROLLED_STOP")
        return {
            "status": "PASS" if not failures else "BLOCKED",
            "failures": failures,
            "file_count": len(entries),
            "tree_sha256": tree_sha,
            "summary_status": summary.get("status"),
            "real_4k_quality_gain": summary.get("real_4k_quality_gain"),
            "controlled_stop": True,
            "calibration_authority_binding": authority["binding_status"],
            "candidate_execution_authorized": authority[
                "candidate_execution_authorized"
            ],
            "threshold_provenance_status": expected_provenance["status"],
            "uncalibrated_threshold_count": expected_provenance[
                "uncalibrated_threshold_count"
            ],
            "stop_v2_operator": summary.get("stop_v2_operator"),
            "runtime_authorization": runtime_authorization,
            "calibration_path_binding": path_binding,
            "runtime_authorization_semantic_projection": runtime_projection,
            "semantic_recompute": semantic,
        }
    full_run_required = {
        "e1_cases_replayed": "16/16",
        "e4k_02_connected": True,
        "e1_02_connected": True,
        "non_target_no_op_cases": 12,
    }
    for field, value in full_run_required.items():
        if summary.get(field) != value:
            failures.append(f"SUMMARY_FIELD_MISMATCH:{field}")
    record_files = {
        path.stem: path for path in (root / "budget_records").glob("E1C*.json")
    }
    result_files = {
        path.stem: path for path in (root / "case_results").glob("E1C*.json")
    }
    if set(record_files) != set(result_files) or len(record_files) != EXPECTED_CASE_COUNT:
        failures.append("CASE_SET_MISMATCH")
    else:
        case_ids = sorted(record_files)
        records = [_read_json(record_files[case_id]) for case_id in case_ids]
        results = [_read_json(result_files[case_id]) for case_id in case_ids]
        try:
            derived = _derived_summary(records, results)
            failures.extend(validate_summary_raw_evidence(summary, derived))
        except Exception as exc:
            failures.append(f"SUMMARY_RECOMPUTE_FAILED:{type(exc).__name__}:{exc}")
        candidate_ids = {result.get("candidate_id") for result in results}
        if len(candidate_ids) != 1 or None in candidate_ids:
            failures.append("CANDIDATE_ID_NOT_UNIQUE")
    return {
        "status": "PASS" if not failures else "BLOCKED",
        "failures": failures,
        "file_count": len(entries),
        "tree_sha256": tree_sha,
        "summary_status": summary.get("status"),
        "real_4k_quality_gain": summary.get("real_4k_quality_gain"),
        "calibration_path_binding": path_binding,
        "runtime_authorization_semantic_projection": runtime_projection,
        "semantic_recompute": semantic,
    }


def refresh_derived_artifact(root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    """Refresh only evidence derived from the frozen V2 Controlled assets."""

    calibration_path = root / "controlled_calibration" / "controlled_calibration.json"
    calibration = _read_json(calibration_path)
    semantic = recompute_calibration_semantics(root, calibration)
    if semantic["status"] != "PASS":
        raise RuntimeError(f"CALIBRATION_SEMANTIC_RECOMPUTE_FAILED:{semantic['failures']}")
    if (
        semantic["controlled_rows_recomputed"] != 16
        or semantic["recomputed_qualified_ratios"]
        or semantic["recomputed_selected_ratio"] is not None
        or semantic["recomputed_calibration_status"] != "FAIL"
    ):
        raise RuntimeError("FROZEN_V2_NEGATIVE_CONCLUSION_CHANGED")

    authority = build_calibration_authority_binding(
        calibration,
        calibration_artifact_sha256=sha256_file(calibration_path),
    )
    threshold = build_v2_threshold_provenance(
        SAFE_PROFILE_V2,
        calibration_authority=authority,
    )
    if (
        authority["binding_status"] != "PASS"
        or authority["candidate_execution_authorized"] is not False
        or threshold["status"] != "NEED_CALIBRATION"
        or threshold["uncalibrated_threshold_count"] < 1
    ):
        raise RuntimeError("FAILED_CALIBRATION_AUTHORITY_DID_NOT_FAIL_CLOSED")

    step0_path = root / "validation" / "step0_test_execution.json"
    if not step0_path.is_file():
        raise RuntimeError("STEP0_TEST_EXECUTION_RECORD_REQUIRED")
    step0_tests = _read_json(step0_path)
    if step0_tests.get("status") != "PASS":
        raise RuntimeError("STEP0_TEST_EXECUTION_NOT_PASS")
    correction_path = root / "validation" / "correction_test_execution.json"
    correction_tests = _read_json(correction_path) if correction_path.is_file() else None
    if correction_tests is not None and correction_tests.get("status") != "PASS":
        raise RuntimeError("CORRECTION_TEST_EXECUTION_NOT_PASS")

    selection = _read_json(
        root / "target_family_selection" / "target_family_selection_v2.json"
    )
    determinism = _read_json(root / "validation" / "controlled_determinism.json")
    protected_record = _read_json(root / "validation" / "protected_scope.json")
    protected = protected_record.get("after") or {}
    definition = source_domain_candidate_definition(
        calibration_authority=authority
    )
    candidate_id, identity = build_candidate_identity(definition)
    runtime_authorization = validate_runtime_calibration_authorization(
        calibration_artifact_path=calibration_path,
        calibration_authority=authority,
        threshold_provenance=threshold,
        candidate_id=candidate_id,
        profile=SAFE_PROFILE_V2,
    )
    if (
        runtime_authorization["status"] != "FAIL"
        or runtime_authorization["candidate_execution_authorized"] is not False
    ):
        raise RuntimeError("FAILED_CALIBRATION_RUNTIME_AUTHORIZATION_NOT_CLOSED")
    _write_json(
        root / "candidate_identity.json",
        {
            "candidate_id": candidate_id,
            "candidate_identity_contract": identity,
            "status": "STOPPED_CALIBRATION_NOT_AUTHORIZED",
            "calibration_authority_binding": authority,
            "candidate_execution_authorized": False,
            "runtime_calibration_authorization_gate_version": (
                RUNTIME_CALIBRATION_AUTHORIZATION_GATE_VERSION
            ),
            "frozen_before_holdout": False,
            "holdout_executed": False,
            "refreshed_at_utc": _utc_now(),
        },
    )
    _write_json(
        root / "threshold_provenance" / "threshold_provenance_v2.json",
        threshold,
    )
    _write_json(
        root / "validation" / "calibration_authority_binding.json",
        authority,
    )
    _write_json(
        root / "validation" / "calibration_semantic_recompute.json",
        semantic,
    )
    _write_json(
        root / "validation" / "runtime_calibration_authorization.json",
        runtime_authorization,
    )
    summary = _build_controlled_stop_summary(
        selection=selection,
        calibration=calibration,
        candidate_id=candidate_id,
        determinism=determinism,
        protected=protected,
        calibration_authority=authority,
        threshold=threshold,
        runtime_authorization=runtime_authorization,
        semantic_recompute=semantic,
        step0_tests=step0_tests,
        correction_tests=correction_tests,
    )
    _write_json(root / "summary.json", summary)
    integrity = _write_integrity_manifest(root)
    validation = validate_artifact(root)
    if validation["status"] != "PASS":
        raise RuntimeError(f"REFRESHED_ARTIFACT_VALIDATION_FAILED:{validation['failures']}")
    return {"summary": summary, "integrity": integrity, "validation": validation}


def run_experiment() -> dict[str, Any]:
    manifest = _read_json(E1_MANIFEST)
    if len(manifest["cases"]) != EXPECTED_CASE_COUNT:
        raise RuntimeError("E1_MANIFEST_CASE_COUNT_MISMATCH")
    v1_before = _tree_state(V1_ARTIFACT)
    protected_before = protected_scope_state()
    if protected_before["status"] != "PASS":
        raise RuntimeError("PROTECTED_SCOPE_NOT_CLEAN_AT_V2_START")
    for name in (
        "target_family_selection",
        "threshold_provenance",
        "controlled_calibration",
        "degradation_profiles",
        "raw_proposal_records",
        "budget_records",
        "protection_records",
        "candidate_runs",
        "e1_02_results",
        "roi_comparisons",
        "case_results",
        "validation",
    ):
        (OUTPUT_ROOT / name).mkdir(parents=True, exist_ok=True)
    calibration = run_controlled_calibration(OUTPUT_ROOT)
    calibration_path = (
        OUTPUT_ROOT / "controlled_calibration" / "controlled_calibration.json"
    )
    semantic = recompute_calibration_semantics(OUTPUT_ROOT, calibration)
    if semantic["status"] != "PASS":
        raise RuntimeError(f"V2_CALIBRATION_SEMANTIC_INVALID:{semantic['failures']}")
    authority = build_calibration_authority_binding(
        calibration,
        calibration_artifact_sha256=sha256_file(calibration_path),
    )
    threshold = build_v2_threshold_provenance(
        SAFE_PROFILE_V2,
        calibration_authority=authority,
    )
    _write_json(
        OUTPUT_ROOT / "threshold_provenance" / "threshold_provenance_v2.json",
        threshold,
    )
    _write_json(
        OUTPUT_ROOT / "validation" / "calibration_authority_binding.json",
        authority,
    )
    _write_json(
        OUTPUT_ROOT / "validation" / "calibration_semantic_recompute.json",
        semantic,
    )
    if authority["binding_status"] != "PASS":
        raise RuntimeError("V2_CALIBRATION_AUTHORITY_BINDING_INVALID")
    if calibration["status"] == "PASS" and threshold["status"] != "PASS":
        raise RuntimeError("VALID_CALIBRATION_DID_NOT_AUTHORIZE_THRESHOLD")
    if calibration["status"] != "PASS" and threshold["status"] != "NEED_CALIBRATION":
        raise RuntimeError("FAILED_CALIBRATION_DID_NOT_BLOCK_THRESHOLD")
    selection = build_target_family_selection(manifest)
    _write_json(
        OUTPUT_ROOT / "target_family_selection" / "target_family_selection_v2.json",
        selection,
    )
    _write_json(
        OUTPUT_ROOT / "degradation_profiles" / "selection_case_profiles.json",
        {
            case["case_id"]: build_source_degradation_profile(
                _resolve(case["input"]["path"])
            )
            for case in manifest["cases"]
        },
    )
    definition = source_domain_candidate_definition(
        calibration_authority=authority
    )
    candidate_id, identity = build_candidate_identity(definition)
    runtime_authorization = validate_runtime_calibration_authorization(
        calibration_artifact_path=calibration_path,
        calibration_authority=authority,
        threshold_provenance=threshold,
        candidate_id=candidate_id,
        profile=SAFE_PROFILE_V2,
    )
    if calibration["status"] == "PASS":
        if (
            runtime_authorization["status"] != "PASS"
            or runtime_authorization["candidate_execution_authorized"] is not True
        ):
            raise RuntimeError("VALID_CALIBRATION_RUNTIME_AUTHORIZATION_FAILED")
    elif (
        runtime_authorization["status"] != "FAIL"
        or runtime_authorization["candidate_execution_authorized"] is not False
    ):
        raise RuntimeError("FAILED_CALIBRATION_RUNTIME_AUTHORIZATION_NOT_CLOSED")
    _write_json(
        OUTPUT_ROOT / "candidate_identity.json",
        {
            "candidate_id": candidate_id,
            "candidate_identity_contract": identity,
            "status": (
                "FROZEN_FOR_HOLDOUT"
                if authority["candidate_execution_authorized"]
                else "STOPPED_CALIBRATION_NOT_AUTHORIZED"
            ),
            "calibration_authority_binding": authority,
            "candidate_execution_authorized": authority[
                "candidate_execution_authorized"
            ],
            "runtime_calibration_authorization_gate_version": (
                RUNTIME_CALIBRATION_AUTHORIZATION_GATE_VERSION
            ),
            "frozen_before_holdout": authority["candidate_execution_authorized"],
            "holdout_executed": calibration["status"] == "PASS",
            "created_at_utc": _utc_now(),
        },
    )
    controlled_determinism = run_controlled_determinism(
        calibration,
        candidate_id,
        authority,
        calibration_path,
        threshold,
    )
    _write_json(
        OUTPUT_ROOT / "validation" / "controlled_determinism.json",
        controlled_determinism,
    )
    _write_json(
        OUTPUT_ROOT / "validation" / "runtime_calibration_authorization.json",
        runtime_authorization,
    )
    step0_tests = run_step0_tests_and_record(OUTPUT_ROOT)
    if calibration["status"] != "PASS":
        protected_after = protected_scope_state()
        v1_after = _tree_state(V1_ARTIFACT)
        if v1_after != v1_before:
            protected_after = dict(protected_after)
            protected_after["status"] = "FAIL"
            protected_after["v1_artifact_changed"] = True
        else:
            protected_after["v1_artifact_changed"] = False
        _write_json(
            OUTPUT_ROOT / "validation" / "protected_scope.json",
            {
                "before": protected_before,
                "after": protected_after,
                "v1_artifact_before": v1_before,
                "v1_artifact_after": v1_after,
            },
        )
        _write_json(
            OUTPUT_ROOT / "raw_proposal_records" / "controlled_formal_rows.json",
            {
                "formal_ratio": calibration["formal_ratio"],
                "rows": [
                    {
                        "probe_id": row["probe_id"],
                        "raw_record": row["raw_record"],
                        "raw_proposal_safety": row["raw_proposal_safety"],
                    }
                    for row in calibration["formal_rows"]
                ],
            },
        )
        _write_json(
            OUTPUT_ROOT / "budget_records" / "controlled_formal_rows.json",
            {
                row["probe_id"]: row["bounded_record"]
                for row in calibration["formal_rows"]
            },
        )
        _write_json(
            OUTPUT_ROOT / "protection_records" / "controlled_formal_rows.json",
            {
                row["probe_id"]: row["protection_record"]
                for row in calibration["formal_rows"]
            },
        )
        _write_json(
            OUTPUT_ROOT / "e1_02_results" / "not_run.json",
            {
                "status": "NOT_RUN_CONTROLLED_GATE_STOP",
                "reason": "CONTROLLED_MILD_RECOVERY_DIRECTION_NOT_POSITIVE",
            },
        )
        _write_json(
            OUTPUT_ROOT / "roi_comparisons" / "not_generated.json",
            {
                "status": "NOT_TRIGGERED",
                "reason": "E1_HOLDOUT_NOT_RUN",
            },
        )
        stop_summary = _build_controlled_stop_summary(
            selection=selection,
            calibration=calibration,
            candidate_id=candidate_id,
            determinism=controlled_determinism,
            protected=protected_after,
            calibration_authority=authority,
            threshold=threshold,
            runtime_authorization=runtime_authorization,
            semantic_recompute=semantic,
            step0_tests=step0_tests,
        )
        _write_json(OUTPUT_ROOT / "summary.json", stop_summary)
        integrity = _write_integrity_manifest()
        validation = validate_artifact(OUTPUT_ROOT)
        if validation["status"] != "PASS":
            raise RuntimeError(
                f"CONTROLLED_STOP_ARTIFACT_VALIDATION_FAILED:{validation['failures']}"
            )
        return {"summary": stop_summary, "integrity": integrity, "validation": validation}
    determinism = run_determinism(
        manifest,
        candidate_id,
        authority,
        calibration_path,
        threshold,
    )
    _write_json(OUTPUT_ROOT / "validation" / "determinism.json", determinism)
    if determinism["status"] != "PASS":
        raise RuntimeError("DETERMINISM_FAILED")
    results: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for index, case in enumerate(manifest["cases"], start=1):
        case_id = case["case_id"]
        print(f"E4K04_V2_START={index}/16;CASE={case_id}", flush=True)
        result = _run_case(
            case,
            definition,
            nonce=f"E4K04_V2_FINAL_HOLDOUT_{case_id}",
            calibration_authority=authority,
            calibration_artifact_path=calibration_path,
            threshold_provenance=threshold,
        )
        if result.get("candidate_id") != candidate_id:
            raise RuntimeError(f"CANDIDATE_ID_MISMATCH:{case_id}")
        record = _core_record(result)
        record = _write_case_derivatives(case_id, result, record)
        results.append(result)
        records.append(record)
        print(
            f"E4K04_V2_DONE={index}/16;CASE={case_id};"
            f"ACTIVATION={record.get('restoration_activation')};"
            f"SAFETY={result.get('safety_status')};"
            f"QUALITY={result.get('quality_gain_status')}",
            flush=True,
        )
    protected_after = protected_scope_state()
    v1_after = _tree_state(V1_ARTIFACT)
    if v1_after != v1_before:
        protected_after = dict(protected_after)
        protected_after["status"] = "FAIL"
        protected_after["v1_artifact_changed"] = True
    else:
        protected_after["v1_artifact_changed"] = False
    _write_json(
        OUTPUT_ROOT / "validation" / "protected_scope.json",
        {
            "before": protected_before,
            "after": protected_after,
            "v1_artifact_before": v1_before,
            "v1_artifact_after": v1_after,
        },
    )
    human_review = _build_human_review_package(
        results, set(selection["target_case_ids"])
    )
    summary = _build_summary(
        results=results,
        records=records,
        selection=selection,
        calibration=calibration,
        determinism=determinism,
        protected=protected_after,
        human_review=human_review,
        threshold=threshold,
        calibration_authority=authority,
        semantic_recompute=semantic,
        step0_tests=step0_tests,
    )
    _write_json(OUTPUT_ROOT / "summary.json", summary)
    integrity = _write_integrity_manifest()
    validation = validate_artifact(OUTPUT_ROOT)
    if validation["status"] != "PASS":
        raise RuntimeError(f"ARTIFACT_VALIDATION_FAILED:{validation['failures']}")
    return {"summary": summary, "integrity": integrity, "validation": validation}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=(
            "run",
            "validate",
            "record-step0-tests",
            "record-correction-tests",
            "refresh-derived",
        ),
    )
    args = parser.parse_args()
    if args.phase == "run":
        result = run_experiment()
    elif args.phase == "validate":
        result = validate_artifact(OUTPUT_ROOT)
    elif args.phase == "record-step0-tests":
        result = run_step0_tests_and_record(OUTPUT_ROOT)
    elif args.phase == "record-correction-tests":
        result = run_correction_tests_and_record(OUTPUT_ROOT)
    else:
        result = refresh_derived_artifact(OUTPUT_ROOT)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), flush=True)
    status = result.get("status", (result.get("validation") or {}).get("status"))
    return 1 if status == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
