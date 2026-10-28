"""Build the HDDE V0.5.6 controlled-reference color quality baseline.

This is an evaluation-only runner.  It does not change D1/D2/D3 decisions,
runtime routing, or executor parameters.  Every synthetic error is derived from
one SHA-verified D01 authority image, and that unchanged image is the sole
ground truth for recovery measurements.

Canonical invocation from the repository root:
    .venv/Scripts/python.exe -m tests.color_correction.run_color_quality_baseline_v1
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from engine.color_correction import analyze_color_usability
from engine.color_correction.candidate_generation import (
    D2_ENGINE_VERSION,
    CandidateExecutor,
    CorrectionBudget,
    ExposureStatus,
    _exposure_candidate,
    _protection_masks,
    _run_color_attempts,
)
from engine.color_correction.usability_decision import _detect_faces
from tests.color_correction.test_color_usability_decision import (
    _load_authoritative_d01_dataset,
)


ROOT = Path(__file__).resolve().parents[2]
OLD_OUTPUT_ROOT = ROOT / "output" / "evaluation" / "color_quality_baseline_v1_20260819"
PRIOR_METRIC_FIX_OUTPUT_ROOT = (
    ROOT / "output" / "evaluation" / "color_quality_baseline_v1_metric_fix_20260823"
)
PRIOR_METRIC_CONTRACT_OUTPUT_ROOT = (
    ROOT / "output" / "evaluation" / "color_quality_baseline_v1_metric_contract_fix_20260823"
)
OUTPUT_ROOT = (
    ROOT / "output" / "evaluation" / "color_quality_baseline_v1_metric_credit_fix_20260823"
)
PIXEL_BASELINE_ROOTS = {
    "REVOKED_BASELINE": OLD_OUTPUT_ROOT,
    "PRIOR_METRIC_FIX": PRIOR_METRIC_FIX_OUTPUT_ROOT,
    "PRIOR_METRIC_CONTRACT": PRIOR_METRIC_CONTRACT_OUTPUT_ROOT,
}

REFERENCES: dict[str, tuple[str, ...]] = {
    "D01_01": ("PERSON", "SKIN", "WHITE_GRAY_NEUTRAL", "INDOOR"),
    "D01_10": ("BRAND_COLOR", "PRODUCT", "WHITE_GRAY_NEUTRAL"),
    "D01_11": ("PRODUCT", "WHITE_GRAY_NEUTRAL", "DARK_MATERIAL"),
    "D01_12": ("WHITE_GRAY_NEUTRAL", "INDOOR", "HIGHLIGHT"),
    "D01_13": ("PERSON", "SKIN", "INDOOR", "LEGITIMATE_WARM"),
}
REFERENCE_COVERAGE_GAPS = ("OUTDOOR", "AUTHORITATIVE_GT_B_BRAND_ROI")
PURE_COLOR_RECIPES = ("YELLOW_CAST", "BLUE_CAST", "OTHER_GLOBAL_CAST")
EVALUABLE_GRADES = {"RECOVERED", "IMPROVED", "UNCHANGED", "DEGRADED"}
POSITIVE_GRADES = {"RECOVERED", "IMPROVED"}
BLOCKING_COLOR_STATUSES = {"RISK", "EXECUTOR_LIMIT"}
# Frozen D57 historical evidence labels. They intentionally remain plain
# strings now that the production CandidateExecutor no longer exposes either
# retired implementation.
CATEGORY_EXECUTORS = ("SAFE_WB", "cross_affine_balanced")
CATEGORY_RANKING_AUTHORITY = (
    "DESCRIPTIVE_ONLY_NOT_EVALUABLE_PENDING_D57_COLOR_02_EVIDENCE_POLICY"
)
REGION_CATEGORY_MAP = {
    "WHITE_GRAY_NEUTRAL": "neutral",
    "SKIN": "skin",
    "BRAND_COLOR": "brand",
}

# Fixed before observing executor results.  Lab offsets isolate color from
# exposure; the combined case also applies one deterministic L-channel scale.
ERROR_RECIPES: dict[str, dict[str, Any]] = {
    "YELLOW_CAST": {"lab_delta_a": 2.0, "lab_delta_b": 16.0, "lab_l_scale": 1.0},
    "BLUE_CAST": {"lab_delta_a": -2.0, "lab_delta_b": -16.0, "lab_l_scale": 1.0},
    "OTHER_GLOBAL_CAST": {"lab_delta_a": -14.0, "lab_delta_b": 2.0, "lab_l_scale": 1.0},
    "CAST_PLUS_EXPOSURE": {
        "lab_delta_a": 2.0,
        "lab_delta_b": 16.0,
        "lab_l_scale": 0.68,
        "exposure_executor": "TOO_DARK",
    },
}

CLASSIFICATION_POLICY = {
    "RECOVERED": {
        "minimum_recovery_ratio": 0.70,
        "maximum_global_delta_e_mean": 4.0,
        "maximum_residual_cast_delta_e": 3.0,
        "requires_no_side_effect": True,
    },
    "IMPROVED": {
        "minimum_recovery_ratio": 0.20,
        "minimum_global_delta_e_reduction": 1.0,
        "requires_no_side_effect": True,
    },
    "DEGRADED": {
        "global_delta_e_growth": 0.5,
        "regional_delta_e_growth": 1.0,
        "clip_growth": 0.003,
        "reverse_cast_minimum": 1.0,
    },
    "UNCHANGED": "all remaining candidates with no material degradation",
    "REGIONAL_ABSOLUTE_REFERENCE_GATE": {
        "maximum_delta_e_mean": 4.0,
        "requires_no_worsening": True,
        "scope": "CONTROLLED_BASELINE_ONLY_NOT_COMMERCIAL_PRODUCT_THRESHOLD",
        "brand_roi_authority": "GT_B_REQUIRED_STRONG_MASK_IS_NOT_BRAND_AUTHORITY",
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as opened:
        return np.asarray(ImageOps.exif_transpose(opened).convert("RGB"), dtype=np.uint8)


def _save_rgb(path: Path, rgb: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", np.ascontiguousarray(rgb[..., ::-1]))
    if not ok:
        raise RuntimeError(f"failed to encode PNG: {path}")
    path.write_bytes(encoded.tobytes())


def _rgb01(rgb: np.ndarray) -> np.ndarray:
    return rgb.astype(np.float32) / 255.0


def _u8(rgb01: np.ndarray) -> np.ndarray:
    return np.rint(np.clip(rgb01, 0.0, 1.0) * 255.0).astype(np.uint8)


def _apply_error(reference: np.ndarray, recipe: dict[str, Any]) -> np.ndarray:
    lab = cv2.cvtColor(_rgb01(reference), cv2.COLOR_RGB2LAB)
    changed = lab.copy()
    changed[..., 0] = np.clip(changed[..., 0] * float(recipe["lab_l_scale"]), 0.0, 100.0)
    changed[..., 1] = np.clip(changed[..., 1] + float(recipe["lab_delta_a"]), -127.0, 127.0)
    changed[..., 2] = np.clip(changed[..., 2] + float(recipe["lab_delta_b"]), -127.0, 127.0)
    return _u8(cv2.cvtColor(changed, cv2.COLOR_LAB2RGB))


def _delta_e(reference_lab: np.ndarray, sample_lab: np.ndarray, mask: np.ndarray | None = None) -> dict[str, float | None]:
    distance = np.linalg.norm(sample_lab - reference_lab, axis=2)
    if mask is not None:
        if int(mask.sum()) < 64:
            return {"mean": None, "p95": None, "coverage": round(float(mask.mean()), 6)}
        distance = distance[mask]
        coverage = float(mask.mean())
    else:
        coverage = 1.0
    return {
        "mean": round(float(distance.mean()), 6),
        "p95": round(float(np.percentile(distance, 95)), 6),
        "coverage": round(coverage, 6),
    }


def _clip_ratios(rgb01: np.ndarray) -> dict[str, float]:
    lab = cv2.cvtColor(rgb01.astype(np.float32), cv2.COLOR_RGB2LAB)
    return {
        "shadow": round(float((lab[..., 0] <= 1.0).mean()), 6),
        "highlight": round(float((lab[..., 0] >= 99.0).mean()), 6),
    }


def _reference_metrics(
    reference: np.ndarray,
    error: np.ndarray,
    candidate: np.ndarray,
    reference_masks: dict[str, np.ndarray],
    *,
    reference_categories: tuple[str, ...],
    brand_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    reference01, error01, candidate01 = _rgb01(reference), _rgb01(error), _rgb01(candidate)
    reference_lab = cv2.cvtColor(reference01, cv2.COLOR_RGB2LAB)
    error_lab = cv2.cvtColor(error01, cv2.COLOR_RGB2LAB)
    candidate_lab = cv2.cvtColor(candidate01, cv2.COLOR_RGB2LAB)
    before = _delta_e(reference_lab, error_lab)
    after = _delta_e(reference_lab, candidate_lab)
    before_mean = float(before["mean"])
    after_mean = float(after["mean"])
    recovery_ratio = (before_mean - after_mean) / max(before_mean, 1e-6)

    region_masks: dict[str, np.ndarray | None] = {
        "neutral": reference_masks["neutral"],
        "skin": reference_masks["skin"],
        "strong": reference_masks["strong"],
        "brand": brand_mask,
    }
    region_metrics: dict[str, dict[str, Any]] = {}
    for name, mask in region_masks.items():
        if mask is None:
            before_region = {"mean": None, "p95": None, "coverage": 0.0}
            after_region = {"mean": None, "p95": None, "coverage": 0.0}
            pixel_count = 0
        else:
            before_region = _delta_e(reference_lab, error_lab, mask)
            after_region = _delta_e(reference_lab, candidate_lab, mask)
            pixel_count = int(mask.sum())
        region_before = before_region["mean"]
        region_after = after_region["mean"]
        region_reduction = (
            None
            if region_before is None or region_after is None
            else float(region_before) - float(region_after)
        )
        region_ratio = (
            None
            if region_reduction is None
            else region_reduction / max(float(region_before), 1e-6)
        )
        region_metrics[name] = {
            "before": before_region,
            "after": after_region,
            "pixel_count": pixel_count,
            "delta_e_reduction": None if region_reduction is None else round(region_reduction, 6),
            "recovery_ratio": None if region_ratio is None else round(region_ratio, 6),
        }

    required_regions = {
        "neutral": "WHITE_GRAY_NEUTRAL" in reference_categories,
        "skin": "SKIN" in reference_categories,
        "brand": "BRAND_COLOR" in reference_categories,
    }
    region_authority = {
        "neutral": "REFERENCE_DERIVED_NEUTRAL_MASK",
        "skin": "REFERENCE_DERIVED_SKIN_MASK",
        "brand": "GT_B_BRAND_ROI" if brand_mask is not None else "MISSING_GT_B_BRAND_ROI",
    }
    regional_gate_entries: dict[str, dict[str, Any]] = {}
    absolute_limit = float(
        CLASSIFICATION_POLICY["REGIONAL_ABSOLUTE_REFERENCE_GATE"]["maximum_delta_e_mean"]
    )
    for name in ("neutral", "skin", "brand"):
        values = region_metrics[name]
        required = required_regions[name]
        gate_before_mean = values["before"]["mean"]
        gate_after_mean = values["after"]["mean"]
        if not required:
            status = "NOT_REQUIRED"
        elif gate_before_mean is None or gate_after_mean is None:
            status = "NOT_EVALUABLE"
        elif (
            float(gate_after_mean) <= absolute_limit
            and float(gate_after_mean) <= float(gate_before_mean) + 1e-6
        ):
            status = "PASS"
        else:
            status = "FAIL"
        regional_gate_entries[name] = {
            "required": required,
            "authority": region_authority[name],
            "pixel_count": values["pixel_count"],
            "maximum_delta_e_mean": absolute_limit if required else None,
            "before_delta_e_mean": gate_before_mean,
            "after_delta_e_mean": gate_after_mean,
            "status": status,
        }

    required_statuses = [
        entry["status"]
        for entry in regional_gate_entries.values()
        if entry["required"]
    ]
    if "NOT_EVALUABLE" in required_statuses:
        regional_gate_overall = "NOT_EVALUABLE"
    elif "FAIL" in required_statuses:
        regional_gate_overall = "FAIL"
    elif required_statuses:
        regional_gate_overall = "PASS"
    else:
        regional_gate_overall = "NOT_APPLICABLE"

    anchor_mask = reference_masks["neutral"]
    if int(anchor_mask.sum()) < 64:
        anchor_mask = np.ones(reference.shape[:2], dtype=bool)
    before_vector = np.mean((error_lab - reference_lab)[anchor_mask][:, 1:3], axis=0)
    after_vector = np.mean((candidate_lab - reference_lab)[anchor_mask][:, 1:3], axis=0)
    before_cast = float(np.linalg.norm(before_vector))
    after_cast = float(np.linalg.norm(after_vector))
    reverse_cast = bool(float(np.dot(before_vector, after_vector)) < 0.0 and after_cast >= 1.0)

    error_clip, candidate_clip = _clip_ratios(error01), _clip_ratios(candidate01)
    side_effects: list[str] = []
    if after_mean > before_mean + 0.5:
        side_effects.append("GLOBAL_DEGRADATION")
    for name, values in region_metrics.items():
        region_before = values["before"]["mean"]
        region_after = values["after"]["mean"]
        if region_before is not None and region_after is not None and float(region_after) > float(region_before) + 1.0:
            side_effects.append(f"{name.upper()}_DEGRADATION")
    if candidate_clip["shadow"] - error_clip["shadow"] > 0.003:
        side_effects.append("SHADOW_CLIP_GROWTH")
    if candidate_clip["highlight"] - error_clip["highlight"] > 0.003:
        side_effects.append("HIGHLIGHT_CLIP_GROWTH")
    if reverse_cast:
        side_effects.append("REVERSE_CAST")

    reduction = before_mean - after_mean
    if side_effects:
        grade = "DEGRADED"
    elif (
        recovery_ratio >= 0.70
        and after_mean <= 4.0
        and after_cast <= 3.0
        and regional_gate_overall == "PASS"
    ):
        grade = "RECOVERED"
    elif recovery_ratio >= 0.20 and reduction >= 1.0:
        grade = "IMPROVED"
    else:
        grade = "UNCHANGED"

    return {
        "reference_distance_before": before,
        "reference_distance_after": after,
        "recovery_ratio": round(float(recovery_ratio), 6),
        "delta_e_reduction": round(float(reduction), 6),
        "regions": region_metrics,
        "regional_absolute_gate": {
            "scope": "CONTROLLED_BASELINE_ONLY_NOT_COMMERCIAL_PRODUCT_THRESHOLD",
            "overall": regional_gate_overall,
            "regions": regional_gate_entries,
        },
        "residual_cast": {
            "before_ab": [round(float(value), 6) for value in before_vector],
            "after_ab": [round(float(value), 6) for value in after_vector],
            "before_delta_e": round(before_cast, 6),
            "after_delta_e": round(after_cast, 6),
            "reverse_cast": reverse_cast,
        },
        "clip_ratios": {"error": error_clip, "candidate": candidate_clip},
        "side_effects": side_effects,
        "grade": grade,
    }


def _stage_interpretation(
    *,
    recipe: str,
    safety_status: str,
    color_metrics: dict[str, Any],
    exposure_stage_increment_metrics: dict[str, Any] | None,
    exposure_only_metrics: dict[str, Any] | None,
    combined_metrics: dict[str, Any] | None,
) -> dict[str, str]:
    if safety_status in BLOCKING_COLOR_STATUSES:
        color_grade = safety_status
    elif safety_status == "PASS":
        color_grade = str(color_metrics["grade"])
    else:
        color_grade = "NOT_EVALUABLE"

    if recipe != "CAST_PLUS_EXPOSURE":
        return {
            "COLOR_EXECUTOR_GRADE": color_grade,
            "EXPOSURE_EXECUTOR_GRADE": "NOT_APPLICABLE",
            "EXPOSURE_STAGE_INCREMENT_GRADE": "NOT_APPLICABLE",
            "COMBINED_PIPELINE_GRADE": "NOT_APPLICABLE",
            "COMMERCIAL_DELIVERY_DECISION": "NOT_AUTHORIZED",
            "COLOR_EXECUTOR_CREDIT": (
                "YES"
                if recipe in PURE_COLOR_RECIPES
                and safety_status == "PASS"
                and color_grade in POSITIVE_GRADES
                else "NO"
            ),
            "COMBINED_ATTRIBUTION": "NOT_APPLICABLE",
        }

    exposure_grade = (
        str(exposure_only_metrics["grade"])
        if exposure_only_metrics is not None
        else "NOT_EVALUABLE"
    )
    exposure_stage_increment_grade = (
        str(exposure_stage_increment_metrics["grade"])
        if exposure_stage_increment_metrics is not None
        else "NOT_EVALUABLE"
    )
    combined_grade = (
        str(combined_metrics["grade"])
        if combined_metrics is not None
        else "NOT_EVALUABLE"
    )
    combined_positive = combined_grade in POSITIVE_GRADES
    exposure_attribution_proven = (
        exposure_grade in POSITIVE_GRADES
        and exposure_stage_increment_grade in POSITIVE_GRADES
        and combined_positive
    )
    color_attribution_proven = (
        safety_status == "PASS"
        and color_grade in POSITIVE_GRADES
        and combined_positive
    )
    if safety_status in BLOCKING_COLOR_STATUSES:
        attribution = "EXPOSURE_ONLY" if exposure_attribution_proven else "COMBINED_UNATTRIBUTED"
    elif color_attribution_proven and exposure_attribution_proven:
        attribution = "COLOR_PLUS_EXPOSURE"
    elif exposure_attribution_proven:
        attribution = "EXPOSURE_ONLY"
    elif color_attribution_proven:
        attribution = "COLOR_ONLY"
    else:
        attribution = "COMBINED_UNATTRIBUTED"
    return {
        "COLOR_EXECUTOR_GRADE": color_grade,
        "EXPOSURE_EXECUTOR_GRADE": exposure_grade,
        "EXPOSURE_STAGE_INCREMENT_GRADE": exposure_stage_increment_grade,
        "COMBINED_PIPELINE_GRADE": combined_grade,
        "COMMERCIAL_DELIVERY_DECISION": "NOT_AUTHORIZED",
        "COLOR_EXECUTOR_CREDIT": (
            "YES" if attribution in {"COLOR_ONLY", "COLOR_PLUS_EXPOSURE"} else "NO"
        ),
        "COMBINED_ATTRIBUTION": attribution,
    }


def _thumbnail(rgb: np.ndarray, width: int = 240, height: int = 160) -> Image.Image:
    image = Image.fromarray(rgb, mode="RGB")
    image.thumbnail((width, height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), "white")
    canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
    return canvas


def _write_contact_sheet(executor: str, rows: list[dict[str, Any]]) -> None:
    cell_width, image_height, label_height = 240, 160, 34
    sheet = Image.new("RGB", (cell_width * 3, (image_height + label_height) * len(rows)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, row in enumerate(rows):
        y = index * (image_height + label_height)
        reference = _load_rgb(ROOT / row["reference_path"])
        error = _load_rgb(OUTPUT_ROOT / row["error_path"])
        candidate = _load_rgb(OUTPUT_ROOT / row["candidate_path"])
        for column, image in enumerate((reference, error, candidate)):
            sheet.paste(_thumbnail(image), (column * cell_width, y))
        combined = row["COMBINED_PIPELINE_GRADE"]
        display_grade = row["COLOR_EXECUTOR_GRADE"] if combined == "NOT_APPLICABLE" else combined
        label = (
            f"{row['case_id']} | {executor} | C={row['COLOR_EXECUTOR_GRADE']} "
            f"| F={display_grade} | R={row['metrics']['recovery_ratio']:.3f}"
        )
        draw.text((4, y + image_height + 5), label, fill="black")
    sheet.save(OUTPUT_ROOT / f"contact_sheet_{executor.lower()}.jpg", quality=92)


def _executor_summary(rows: list[dict[str, Any]], executor: str) -> dict[str, Any]:
    selected = [
        row
        for row in rows
        if row["executor"] == executor and row["recipe"] in PURE_COLOR_RECIPES
    ]
    grades = Counter(row["COLOR_EXECUTOR_GRADE"] for row in selected)
    eligible = [row for row in selected if row["COLOR_EXECUTOR_GRADE"] in EVALUABLE_GRADES]
    ratios = [
        float(row["RAW_REFERENCE_METRICS"]["COLOR_STAGE"]["recovery_ratio"])
        for row in eligible
    ]
    recipe_grades = {
        recipe: dict(Counter(
            row["COLOR_EXECUTOR_GRADE"]
            for row in selected
            if row["recipe"] == recipe
        ))
        for recipe in PURE_COLOR_RECIPES
    }
    return {
        "pure_color_attempt_count": len(selected),
        "eligible_color_attempt_count": len(eligible),
        "RECOVERED": grades["RECOVERED"],
        "IMPROVED": grades["IMPROVED"],
        "UNCHANGED": grades["UNCHANGED"],
        "DEGRADED": grades["DEGRADED"],
        "RISK": grades["RISK"],
        "EXECUTOR_LIMIT": grades["EXECUTOR_LIMIT"],
        "NOT_EVALUABLE": grades["NOT_EVALUABLE"],
        "recovery_ratio": {
            "minimum": None if not ratios else round(min(ratios), 6),
            "median": None if not ratios else round(float(np.median(ratios)), 6),
            "mean": None if not ratios else round(float(np.mean(ratios)), 6),
            "maximum": None if not ratios else round(max(ratios), 6),
        },
        "recipe_grades": recipe_grades,
    }


def _category_metric(row: dict[str, Any], category: str) -> float | None:
    color_metrics = row["RAW_REFERENCE_METRICS"]["COLOR_STAGE"]
    region_name = REGION_CATEGORY_MAP.get(category)
    if region_name is None:
        return float(color_metrics["recovery_ratio"])
    gate = color_metrics["regional_absolute_gate"]["regions"][region_name]
    if gate["status"] == "NOT_EVALUABLE":
        return None
    ratio = color_metrics["regions"][region_name]["recovery_ratio"]
    return None if ratio is None else float(ratio)


def _category_rankings(
    rows: list[dict[str, Any]],
) -> tuple[
    dict[str, dict[str, float]],
    dict[str, str],
    dict[str, dict[str, Any]],
]:
    categories = sorted({category for row in rows for category in row["reference_categories"]})
    category_scores: dict[str, dict[str, dict[tuple[str, str], float]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    pure_attempt_counts: dict[str, Counter[str]] = defaultdict(Counter)
    excluded_grade_counts: dict[str, dict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    excluded_metric_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if row["recipe"] not in PURE_COLOR_RECIPES:
            continue
        for category in row["reference_categories"]:
            executor = row["executor"]
            pure_attempt_counts[category][executor] += 1
            if row["COLOR_EXECUTOR_GRADE"] not in EVALUABLE_GRADES:
                excluded_grade_counts[category][executor][row["COLOR_EXECUTOR_GRADE"]] += 1
                continue
            score = _category_metric(row, category)
            if score is None:
                excluded_metric_counts[category][executor] += 1
                continue
            key = (row["reference_id"], row["recipe"])
            if key in category_scores[category][executor]:
                raise AssertionError(f"duplicate category evidence row: {category}/{executor}/{key}")
            category_scores[category][executor][key] = score
    category_ratio_means: dict[str, dict[str, float]] = {}
    best_by_category: dict[str, str] = {}
    evidence_by_category: dict[str, dict[str, Any]] = {}
    for category in categories:
        executor_keys = {
            executor: set(category_scores[category][executor])
            for executor in CATEGORY_EXECUTORS
        }
        paired_keys = set.intersection(*(executor_keys[executor] for executor in CATEGORY_EXECUTORS))
        means = {
            executor: round(float(np.mean([
                category_scores[category][executor][key]
                for key in sorted(paired_keys)
            ])), 6)
            for executor in CATEGORY_EXECUTORS
            if paired_keys
        }
        category_ratio_means[category] = means
        best_by_category[category] = "NOT_EVALUABLE"
        evidence_by_category[category] = {
            "authority": CATEGORY_RANKING_AUTHORITY,
            "paired_case_count": len(paired_keys),
            "distinct_reference_count": len({key[0] for key in paired_keys}),
            "paired_reference_ids": sorted({key[0] for key in paired_keys}),
            "paired_case_ids": [f"{reference_id}_{recipe}" for reference_id, recipe in sorted(paired_keys)],
            "pure_attempt_count_by_executor": {
                executor: pure_attempt_counts[category][executor]
                for executor in CATEGORY_EXECUTORS
            },
            "eligible_attempt_count_by_executor": {
                executor: len(executor_keys[executor])
                for executor in CATEGORY_EXECUTORS
            },
            "excluded_grade_counts_by_executor": {
                executor: dict(excluded_grade_counts[category][executor])
                for executor in CATEGORY_EXECUTORS
            },
            "excluded_metric_not_evaluable_count_by_executor": {
                executor: excluded_metric_counts[category][executor]
                for executor in CATEGORY_EXECUTORS
            },
            "unpaired_eligible_case_count_by_executor": {
                executor: len(executor_keys[executor] - paired_keys)
                for executor in CATEGORY_EXECUTORS
            },
        }
    return category_ratio_means, best_by_category, evidence_by_category


def _combined_pipeline_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    selected = [row for row in rows if row["recipe"] == "CAST_PLUS_EXPOSURE"]
    return {
        "combined_attempt_count": len(selected),
        "pipeline_grades": dict(Counter(row["COMBINED_PIPELINE_GRADE"] for row in selected)),
        "exposure_executor_grades": dict(Counter(row["EXPOSURE_EXECUTOR_GRADE"] for row in selected)),
        "exposure_stage_increment_grades": dict(Counter(
            row["EXPOSURE_STAGE_INCREMENT_GRADE"] for row in selected
        )),
        "attribution": dict(Counter(row["COMBINED_ATTRIBUTION"] for row in selected)),
        "color_executor_credit_no": sum(row["COLOR_EXECUTOR_CREDIT"] == "NO" for row in selected),
    }


def _verify_pixel_reuse(rows: list[dict[str, Any]]) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    for label, key, expected_count in (
        ("errors", "error_path", len(REFERENCES) * len(ERROR_RECIPES)),
        ("candidates", "candidate_path", len(rows)),
    ):
        paths = sorted({row[key] for row in rows})
        if len(paths) != expected_count:
            raise AssertionError(f"{label} unique path count changed: {len(paths)} != {expected_count}")
        baseline_checks: dict[str, dict[str, Any]] = {}
        for baseline_name, baseline_root in PIXEL_BASELINE_ROOTS.items():
            mismatches: list[str] = []
            for relative in paths:
                baseline_path = baseline_root / relative
                new_path = OUTPUT_ROOT / relative
                if (
                    not baseline_path.is_file()
                    or not new_path.is_file()
                    or _sha256(baseline_path) != _sha256(new_path)
                ):
                    mismatches.append(relative)
            if mismatches:
                raise AssertionError(
                    f"{label} pixel evidence changed against {baseline_name}: {mismatches}"
                )
            baseline_checks[baseline_name] = {
                "root": baseline_root.relative_to(ROOT).as_posix(),
                "matched": expected_count,
                "status": "PASS",
            }
        checks[label] = {
            "expected": expected_count,
            "matched": expected_count,
            "baselines": baseline_checks,
            "status": "PASS",
        }
    return checks


def _derive_metric_contract_status(gates: dict[str, dict[str, Any]]) -> str:
    return "PASS" if gates and all(gate.get("status") == "PASS" for gate in gates.values()) else "FAIL"


def _metric_contract_gates(
    rows: list[dict[str, Any]],
    *,
    reference_records: list[dict[str, Any]],
    expected_cases: int,
    best_by_category: dict[str, str],
    category_evidence: dict[str, dict[str, Any]],
    pixel_reuse: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    required_fields = {
        "COLOR_EXECUTOR_GRADE",
        "EXPOSURE_EXECUTOR_GRADE",
        "EXPOSURE_STAGE_INCREMENT_GRADE",
        "COMBINED_PIPELINE_GRADE",
        "COMMERCIAL_DELIVERY_DECISION",
        "COLOR_EXECUTOR_CREDIT",
        "COMBINED_ATTRIBUTION",
    }
    missing_field_rows = sum(not required_fields.issubset(row) for row in rows)
    invalid_color_credit_rows = 0
    for row in rows:
        if row["recipe"] in PURE_COLOR_RECIPES:
            expected_color_credit = (
                "YES"
                if row["executor_internal_safety"] == "PASS"
                and row["COLOR_EXECUTOR_GRADE"] in POSITIVE_GRADES
                else "NO"
            )
        elif row["recipe"] == "CAST_PLUS_EXPOSURE":
            expected_color_credit = (
                "YES"
                if row["COMBINED_ATTRIBUTION"] in {"COLOR_ONLY", "COLOR_PLUS_EXPOSURE"}
                else "NO"
            )
        else:
            expected_color_credit = "NO"
        invalid_color_credit_rows += row["COLOR_EXECUTOR_CREDIT"] != expected_color_credit
    pure_separation_rows = sum(
        row["recipe"] in PURE_COLOR_RECIPES
        and (
            row["EXPOSURE_EXECUTOR_GRADE"] != "NOT_APPLICABLE"
            or row["EXPOSURE_STAGE_INCREMENT_GRADE"] != "NOT_APPLICABLE"
            or row["COMBINED_PIPELINE_GRADE"] != "NOT_APPLICABLE"
            or row["COMBINED_ATTRIBUTION"] != "NOT_APPLICABLE"
        )
        for row in rows
    )
    attribution_violation_rows = 0
    for row in rows:
        if row["recipe"] != "CAST_PLUS_EXPOSURE":
            continue
        color_positive = (
            row["executor_internal_safety"] == "PASS"
            and row["COLOR_EXECUTOR_GRADE"] in POSITIVE_GRADES
            and row["COMBINED_PIPELINE_GRADE"] in POSITIVE_GRADES
        )
        exposure_positive = (
            row["EXPOSURE_EXECUTOR_GRADE"] in POSITIVE_GRADES
            and row["EXPOSURE_STAGE_INCREMENT_GRADE"] in POSITIVE_GRADES
            and row["COMBINED_PIPELINE_GRADE"] in POSITIVE_GRADES
        )
        expected_attribution = (
            "COLOR_PLUS_EXPOSURE"
            if color_positive and exposure_positive
            else "EXPOSURE_ONLY"
            if exposure_positive
            else "COLOR_ONLY"
            if color_positive
            else "COMBINED_UNATTRIBUTED"
        )
        attribution_violation_rows += row["COMBINED_ATTRIBUTION"] != expected_attribution
    category_authority_violations = sum(
        winner != "NOT_EVALUABLE"
        or category_evidence.get(category, {}).get("authority") != CATEGORY_RANKING_AUTHORITY
        for category, winner in best_by_category.items()
    )
    recovered_region_violations = sum(
        row["RAW_REFERENCE_METRICS"]["COLOR_STAGE"]["grade"] == "RECOVERED"
        and row["RAW_REFERENCE_METRICS"]["COLOR_STAGE"]["regional_absolute_gate"]["overall"] != "PASS"
        for row in rows
    )
    brand_gate_violations = sum(
        "BRAND_COLOR" in row["reference_categories"]
        and row["RAW_REFERENCE_METRICS"]["COLOR_STAGE"]["regional_absolute_gate"]["regions"]["brand"]["status"]
        != "NOT_EVALUABLE"
        for row in rows
    )
    commercial_authorization_rows = sum(
        row["COMMERCIAL_DELIVERY_DECISION"] != "NOT_AUTHORIZED" for row in rows
    )
    count_ok = (
        len(reference_records) == len(REFERENCES)
        and len(rows) == expected_cases * len(CATEGORY_EXECUTORS)
        and len({row["error_path"] for row in rows}) == expected_cases
    )
    pixel_reuse_ok = bool(pixel_reuse) and all(
        gate.get("status") == "PASS" for gate in pixel_reuse.values()
    )
    return {
        "controlled_counts": {"status": "PASS" if count_ok else "FAIL"},
        "required_stage_fields": {
            "status": "PASS" if missing_field_rows == 0 else "FAIL",
            "violation_count": missing_field_rows,
        },
        "invalid_color_credit": {
            "status": "PASS" if invalid_color_credit_rows == 0 else "FAIL",
            "violation_count": invalid_color_credit_rows,
        },
        "pure_recipe_separation": {
            "status": "PASS" if pure_separation_rows == 0 else "FAIL",
            "violation_count": pure_separation_rows,
        },
        "combined_attribution": {
            "status": "PASS" if attribution_violation_rows == 0 else "FAIL",
            "violation_count": attribution_violation_rows,
        },
        "category_winner_authority": {
            "status": "PASS" if category_authority_violations == 0 else "FAIL",
            "violation_count": category_authority_violations,
        },
        "regional_recovered_gate": {
            "status": "PASS" if recovered_region_violations == 0 else "FAIL",
            "violation_count": recovered_region_violations,
        },
        "missing_brand_roi_fail_closed": {
            "status": "PASS" if brand_gate_violations == 0 else "FAIL",
            "violation_count": brand_gate_violations,
        },
        "commercial_delivery_not_authorized": {
            "status": "PASS" if commercial_authorization_rows == 0 else "FAIL",
            "violation_count": commercial_authorization_rows,
        },
        "pixel_reuse": {"status": "PASS" if pixel_reuse_ok else "FAIL"},
    }


def main() -> None:
    authority = _load_authoritative_d01_dataset(ROOT)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    reference_records: list[dict[str, Any]] = []

    for sample_id, categories in REFERENCES.items():
        source_path, label = authority[sample_id]
        if label["decision"] != "ORIGINAL" or label["cast"] != "none" or bool(label["wb"]):
            raise AssertionError(f"reference is not a frozen unchanged color authority: {sample_id}")
        reference = _load_rgb(source_path)
        reference01 = _rgb01(reference)
        reference_boxes = _detect_faces(reference01)
        reference_masks = _protection_masks(reference01, reference_boxes)
        reference_records.append({
            "sample_id": sample_id,
            "source_path": source_path.relative_to(ROOT).as_posix(),
            "source_sha256": _sha256(source_path),
            "authority_source": "candidate_v6_summary.json",
            "authority_decision": label["decision"],
            "authority_cast": label["cast"],
            "authority_wb": label["wb"],
            "categories": list(categories),
            "face_regions": len(reference_boxes),
            "mask_coverage": {
                name: round(float(reference_masks[name].mean()), 6)
                for name in ("neutral", "skin", "strong")
            },
            "brand_roi_authority": "MISSING_GT_B_BRAND_ROI" if "BRAND_COLOR" in categories else "NOT_REQUIRED",
        })

        for recipe_name, recipe in ERROR_RECIPES.items():
            case_id = f"{sample_id}_{recipe_name}"
            error = _apply_error(reference, recipe)
            error_rel = Path("errors") / f"{case_id}.png"
            _save_rgb(OUTPUT_ROOT / error_rel, error)
            error01 = _rgb01(error)
            error_boxes = _detect_faces(error01)
            decision = analyze_color_usability(error, person_regions=error_boxes)
            attempts = _run_color_attempts(error01, decision, CorrectionBudget.MODERATE, error_boxes)
            by_executor = {attempt.executor: attempt for attempt in attempts}

            for executor in (CandidateExecutor.SAFE_WB, CandidateExecutor.CROSS_AFFINE_BALANCED):
                attempt = by_executor[executor]
                color_candidate01 = attempt.candidate_rgb01
                color_candidate = _u8(color_candidate01)
                color_metrics = _reference_metrics(
                    reference,
                    error,
                    color_candidate,
                    reference_masks,
                    reference_categories=categories,
                )
                exposure_parameters = None
                exposure_only_parameters = None
                exposure_only_metrics = None
                exposure_stage_increment_metrics = None
                combined_metrics = None
                if recipe_name == "CAST_PLUS_EXPOSURE":
                    candidate01, exposure_parameters = _exposure_candidate(
                        color_candidate01,
                        ExposureStatus.TOO_DARK,
                        CorrectionBudget.MODERATE,
                    )
                    candidate = _u8(candidate01)
                    exposure_stage_increment_metrics = _reference_metrics(
                        reference,
                        color_candidate,
                        candidate,
                        reference_masks,
                        reference_categories=categories,
                    )
                    exposure_only01, exposure_only_parameters = _exposure_candidate(
                        error01,
                        ExposureStatus.TOO_DARK,
                        CorrectionBudget.MODERATE,
                    )
                    exposure_only_metrics = _reference_metrics(
                        reference,
                        error,
                        _u8(exposure_only01),
                        reference_masks,
                        reference_categories=categories,
                    )
                    combined_metrics = _reference_metrics(
                        reference,
                        error,
                        candidate,
                        reference_masks,
                        reference_categories=categories,
                    )
                else:
                    candidate = color_candidate
                executor_slug = "safe_wb" if executor == CandidateExecutor.SAFE_WB else "cross_affine"
                candidate_rel = Path("candidates") / executor_slug / f"{case_id}.png"
                _save_rgb(OUTPUT_ROOT / candidate_rel, candidate)
                final_metrics = combined_metrics if combined_metrics is not None else color_metrics
                interpretation = _stage_interpretation(
                    recipe=recipe_name,
                    safety_status=attempt.safety_status,
                    color_metrics=color_metrics,
                    exposure_stage_increment_metrics=exposure_stage_increment_metrics,
                    exposure_only_metrics=exposure_only_metrics,
                    combined_metrics=combined_metrics,
                )
                rows.append({
                    "case_id": case_id,
                    "reference_id": sample_id,
                    "reference_categories": list(categories),
                    "reference_path": source_path.relative_to(ROOT).as_posix(),
                    "reference_sha256": _sha256(source_path),
                    "recipe": recipe_name,
                    "recipe_parameters": recipe,
                    "error_path": error_rel.as_posix(),
                    "error_sha256": _sha256(OUTPUT_ROOT / error_rel),
                    "executor": executor.value,
                    "executor_budget": CorrectionBudget.MODERATE.value,
                    "executor_parameters": attempt.parameters,
                    "executor_internal_safety": attempt.safety_status,
                    "executor_internal_violations": list(attempt.violations),
                    "exposure_parameters": exposure_parameters,
                    "exposure_only_parameters": exposure_only_parameters,
                    "candidate_path": candidate_rel.as_posix(),
                    "candidate_sha256": _sha256(OUTPUT_ROOT / candidate_rel),
                    "d1_observation_only": {
                        "color_status": decision.color_status.value,
                        "exposure_status": decision.exposure_status.value,
                        "d1_action": decision.d1_action.value,
                    },
                    "RAW_REFERENCE_METRICS": {
                        "COLOR_STAGE": color_metrics,
                        "EXPOSURE_STAGE_INCREMENT": exposure_stage_increment_metrics,
                        "EXPOSURE_ONLY": exposure_only_metrics,
                        "COMBINED_PIPELINE": combined_metrics,
                    },
                    **interpretation,
                    "metrics": final_metrics,
                })

    expected_cases = len(REFERENCES) * len(ERROR_RECIPES)
    if len(rows) != expected_cases * 2:
        raise AssertionError("every controlled error must have exactly two executor candidates")
    for row in rows:
        for key in ("error_path", "candidate_path"):
            decoded = cv2.imread(str(OUTPUT_ROOT / row[key]), cv2.IMREAD_UNCHANGED)
            if decoded is None or decoded.dtype != np.uint8 or decoded.ndim != 3:
                raise AssertionError(f"invalid output image: {row[key]}")

    summaries = {
        CandidateExecutor.SAFE_WB.value: _executor_summary(rows, CandidateExecutor.SAFE_WB.value),
        CandidateExecutor.CROSS_AFFINE_BALANCED.value: _executor_summary(
            rows, CandidateExecutor.CROSS_AFFINE_BALANCED.value,
        ),
    }
    category_ratio_means, best_by_category, category_evidence = _category_rankings(rows)
    combined_summary = _combined_pipeline_summary(rows)
    pixel_reuse = _verify_pixel_reuse(rows)
    metric_contract_gates = _metric_contract_gates(
        rows,
        reference_records=reference_records,
        expected_cases=expected_cases,
        best_by_category=best_by_category,
        category_evidence=category_evidence,
        pixel_reuse=pixel_reuse,
    )
    metric_contract_status = _derive_metric_contract_status(metric_contract_gates)

    result = {
        "benchmark": "HDDE_V0.5.6_COLOR_QUALITY_BASELINE_V1",
        "benchmark_kind": "CONTROLLED_REFERENCE_CORRECTION_QUALITY_ONLY_NOT_RELEASE_BENCHMARK",
        "PREVIOUS_BASELINE_AUTHORITY": "REVOKED",
        "METRIC_CONTRACT_STATUS": metric_contract_status,
        "QUALITY_BASELINE_AUTHORITY": (
            "VALID_FOR_CONTROLLED_METRIC_USE"
            if metric_contract_status == "PASS"
            else "REVOKED"
        ),
        "COLOR_EXECUTOR_CAPABILITY": "NOT_PROVEN",
        "COMMERCIAL_COLOR_RESTORATION_V1": "NOT_PROVEN",
        "d2_engine_version": D2_ENGINE_VERSION,
        "ground_truth_policy": "UNCHANGED_SHA_VERIFIED_D01_AUTHORITY_REFERENCE_IS_THE_ONLY_GROUND_TRUTH",
        "preprocessing": "NONE",
        "input_order": "RGB",
        "input_dtype": "uint8",
        "metric_domain": "OpenCV float32 RGB 0..1 to Lab L 0..100 a/b signed; DeltaE76",
        "classification_policy": CLASSIFICATION_POLICY,
        "reference_count": len(reference_records),
        "reference_coverage_gaps": list(REFERENCE_COVERAGE_GAPS),
        "controlled_error_case_count": expected_cases,
        "candidate_count": len(rows),
        "evaluation_only_exposure_control_count": sum(
            row["RAW_REFERENCE_METRICS"]["EXPOSURE_ONLY"] is not None for row in rows
        ),
        "references": reference_records,
        "recipes": ERROR_RECIPES,
        "metric_attribution_contract": {
            "color": "COLOR_STAGE_BEFORE_EXPOSURE",
            "exposure": "STANDALONE_EXISTING_EXPOSURE_EXECUTOR_FROM_CONTROLLED_ERROR_INPUT",
            "exposure_chain_increment": "COLOR_STAGE_OUTPUT_TO_FINAL_COMBINED_OUTPUT",
            "exposure_only_attribution_requires": [
                "EXPOSURE_ONLY_POSITIVE",
                "EXPOSURE_STAGE_INCREMENT_POSITIVE",
                "COMBINED_PIPELINE_POSITIVE",
            ],
            "combined": "CONTROLLED_ERROR_TO_FINAL_COLOR_PLUS_EXPOSURE_OUTPUT",
            "color_executor_credit": {
                "pure_color": "YES_ONLY_IF_COLOR_EXECUTOR_GRADE_IS_RECOVERED_OR_IMPROVED",
                "combined": "YES_ONLY_IF_COMBINED_ATTRIBUTION_INCLUDES_COLOR",
                "all_other_results": "NO",
            },
            "invalid_color_credit": "NEVER",
            "commercial_delivery": "NOT_AUTHORIZED_BY_THIS_EVALUATION",
        },
        "executor_summary": summaries,
        "combined_pipeline_summary": combined_summary,
        "category_ranking_authority": CATEGORY_RANKING_AUTHORITY,
        "category_recovery_ratio_means": category_ratio_means,
        "best_executor_by_category": best_by_category,
        "category_ranking_evidence": category_evidence,
        "metric_contract_gates": metric_contract_gates,
        "pixel_reuse_verification": pixel_reuse,
        "old_baseline_results_sha256": _sha256(OLD_OUTPUT_ROOT / "baseline_results.json"),
        "prior_metric_fix_results_sha256": _sha256(
            PRIOR_METRIC_FIX_OUTPUT_ROOT / "baseline_results.json"
        ),
        "prior_metric_contract_results_sha256": _sha256(
            PRIOR_METRIC_CONTRACT_OUTPUT_ROOT / "baseline_results.json"
        ),
        "cases": rows,
    }
    (OUTPUT_ROOT / "baseline_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for executor in (CandidateExecutor.SAFE_WB.value, CandidateExecutor.CROSS_AFFINE_BALANCED.value):
        _write_contact_sheet(executor, [row for row in rows if row["executor"] == executor])
    print(json.dumps({
        "reference_count": result["reference_count"],
        "controlled_error_case_count": result["controlled_error_case_count"],
        "candidate_count": result["candidate_count"],
        "executor_summary": summaries,
        "combined_pipeline_summary": combined_summary,
        "best_executor_by_category": best_by_category,
        "category_ranking_authority": result["category_ranking_authority"],
        "metric_contract_gates": metric_contract_gates,
        "pixel_reuse_verification": pixel_reuse,
        "METRIC_CONTRACT_STATUS": result["METRIC_CONTRACT_STATUS"],
        "COLOR_EXECUTOR_CAPABILITY": result["COLOR_EXECUTOR_CAPABILITY"],
        "output": str(OUTPUT_ROOT.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))
    if metric_contract_status != "PASS":
        raise AssertionError(f"metric contract failed: {metric_contract_gates}")


if __name__ == "__main__":
    main()
