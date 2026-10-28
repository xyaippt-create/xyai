"""Run the fixed 15-image D-04.2 effective-gain evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.color_correction.core import process_single_image
from tests.color_correction.run_d01_evaluation import SAMPLE_LABELS, _checks
from tests.color_correction.run_d02_evaluation import (
    _discover,
    _fingerprint,
    _font,
    _lab_distance,
    _luma_mae,
)
from tests.color_correction.run_d04_evaluation import _tree_fingerprint


IMPROVEMENT_IDS = ("02", "03", "04", "05", "06", "08")
PROTECTION_IDS = tuple(sample_id for sample_id in SAMPLE_LABELS if sample_id not in IMPROVEMENT_IDS)


def _full_contact_sheet(records: list[dict[str, Any]], path: Path) -> None:
    tile_width, tile_height = 720, 410
    sheet = Image.new("RGB", (tile_width * 3, tile_height * 5), "#d8d8d8")
    for index, record in enumerate(records):
        tile = Image.new("RGB", (tile_width, tile_height), "white")
        with Image.open(record["source_path"]) as image:
            before = ImageOps.contain(ImageOps.exif_transpose(image).convert("RGB"), (335, 292))
        with Image.open(record["output_path"]) as image:
            after = ImageOps.contain(image.convert("RGB"), (335, 292))
        tile.paste(before, ((350 - before.width) // 2, 74 + (292 - before.height) // 2))
        tile.paste(after, (370 + (335 - after.width) // 2, 74 + (292 - after.height) // 2))
        draw = ImageDraw.Draw(tile)
        draw.text((12, 8), f"{record['sample_id']} {record['label']}", fill="black", font=_font(17))
        draw.text((12, 34), "ORIGINAL INPUT                 D-04.2 FINAL", fill="#333333", font=_font(13))
        draw.text(
            (12, 53),
            f"execution={record['execution_path']}  global={record['global_applied']}  local={record['local_applied']}",
            fill="#333333",
            font=_font(12),
        )
        draw.text(
            (12, 385),
            f"gate={record['quality_gate']['global']} / {record['quality_gate']['local']}  rollback={record['rollback']}",
            fill="#333333",
            font=_font(12),
        )
        sheet.paste(tile, ((index % 3) * tile_width, (index // 3) * tile_height))
    sheet.save(path, quality=95, subsampling=0)


def _improvement_contact_sheet(records: list[dict[str, Any]], path: Path) -> None:
    row_width, row_height = 1800, 720
    canvas = Image.new("RGB", (row_width, row_height * len(records)), "#e5e5e5")
    for index, record in enumerate(records):
        row = Image.new("RGB", (row_width, row_height), "white")
        with Image.open(record["source_path"]) as image:
            before = ImageOps.contain(ImageOps.exif_transpose(image).convert("RGB"), (850, 590))
        with Image.open(record["output_path"]) as image:
            after = ImageOps.contain(image.convert("RGB"), (850, 590))
        row.paste(before, (20 + (850 - before.width) // 2, 92 + (590 - before.height) // 2))
        row.paste(after, (930 + (850 - after.width) // 2, 92 + (590 - after.height) // 2))
        draw = ImageDraw.Draw(row)
        draw.text((20, 10), f"{record['sample_id']} {record['label']} | ORIGINAL INPUT", fill="black", font=_font(22))
        draw.text((930, 10), f"{record['sample_id']} {record['label']} | D-04.2 FINAL", fill="black", font=_font(22))
        before_metrics = record["objective_metrics"]["before"]
        after_metrics = record["objective_metrics"]["after"]
        draw.text(
            (20, 48),
            f"mean={before_metrics['mean_luminance']} black={before_metrics['black_point']} mid={before_metrics['midtone_point']} white={before_metrics['white_point']} local={before_metrics['local_contrast']}",
            fill="#333333",
            font=_font(14),
        )
        draw.text(
            (930, 48),
            f"mean={after_metrics['mean_luminance']} black={after_metrics['black_point']} mid={after_metrics['midtone_point']} white={after_metrics['white_point']} local={after_metrics['local_contrast']}",
            fill="#333333",
            font=_font(14),
        )
        draw.text(
            (20, 690),
            f"execution={record['execution_path']} | candidate={record['strength']['candidate_level']} | gate={record['quality_gate']['global']}/{record['quality_gate']['local']} | rollback={record['rollback']}",
            fill="#333333",
            font=_font(14),
        )
        canvas.paste(row, (0, index * row_height))
    canvas.save(path, quality=96, subsampling=0)


def _delta(after: dict[str, float], before: dict[str, float]) -> dict[str, float]:
    return {
        key: round(float(after[key]) - float(before[key]), 4)
        for key in (
            "mean_luminance",
            "foreground_luminance",
            "background_luminance",
            "black_point",
            "midtone_point",
            "white_point",
            "dynamic_range",
            "local_contrast",
            "mean_saturation",
            "highlight_ratio",
        )
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--d041-baseline", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    input_root = args.inputs.resolve()
    baseline_path = args.d041_baseline.resolve()
    output_root = args.output.resolve()
    if output_root.exists():
        raise RuntimeError(f"D-04.2 output must be a fresh isolated directory: {output_root}")
    output_root.mkdir(parents=True)
    result_root = output_root / "results"
    result_root.mkdir()

    settings_path = PROJECT_ROOT / "settings" / "settings.json"
    settings_before = _fingerprint(settings_path)
    settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else {}
    formal_output = Path(str(settings["default_output_dir"])).resolve() if settings.get("default_output_dir") else None
    if formal_output and (output_root == formal_output or formal_output in output_root.parents):
        raise RuntimeError("D-04.2 evaluation must not use the formal output directory")
    formal_before = _tree_fingerprint(formal_output)

    discovered = _discover(input_root)
    if set(discovered) != set(SAMPLE_LABELS):
        raise RuntimeError("D-04.2 input does not contain the fixed 15 samples")
    source_before = {sample_id: _fingerprint(path) for sample_id, path in discovered.items()}
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline_records = {record["sample_id"]: record for record in baseline["records"]}
    if set(baseline_records) != set(SAMPLE_LABELS):
        raise RuntimeError("D-04.1 baseline does not contain the fixed 15 samples")

    matrix = _checks()
    records: list[dict[str, Any]] = []
    for sample_id in sorted(discovered):
        source = discovered[sample_id]
        target = result_root / source.name
        result = process_single_image(source, target).to_dict()
        analysis = result["analysis"]
        control = result["parameters"]["quality_control"]
        parameters = result["parameters"]
        baseline_record = baseline_records[sample_id]
        baseline_result = baseline_record["result"]
        matrix_checks = [{"name": name, "pass": bool(predicate(analysis))} for name, predicate in matrix[sample_id]]
        records.append({
            "sample_id": sample_id,
            "label": SAMPLE_LABELS[sample_id],
            "sample_role": "IMPROVEMENT" if sample_id in IMPROVEMENT_IDS else "PROTECTION",
            "source_path": str(source),
            "baseline_path": baseline_record["output_path"],
            "output_path": str(target),
            "source_sha256": source_before[sample_id]["sha256"],
            "baseline_output_sha256": baseline_record["output_sha256"],
            "output_sha256": result["output_sha256"],
            "changed_vs_d041": result["output_sha256"] != baseline_record["output_sha256"],
            "initial_decision": control["initial_decision"],
            "execution_path": analysis["algorithm_execution"],
            "global_applied": bool(control["global_applied"]),
            "local_applied": bool(control["local_applied"]),
            "strength": {
                "candidate_level": analysis["final_candidate_level"],
                "convergence_scales": parameters["convergence_scales"],
                "tonal_curve_strength": parameters["tonal_curve_strength"],
                "spatial_layering_strength": parameters["spatial_layering_strength"],
                "local_executor": parameters["local_executor"],
                "white_balance_execution_strength": analysis.get("white_balance_execution_strength", 0.0),
            },
            "quality_gate": {
                "post_process": analysis["post_process_review"]["status"],
                "global": control["global_quality_gate"],
                "local": control["local_quality_gate"],
                "remaining_violations": analysis["post_process_review"]["remaining_violations"],
                "quality_flags": control["quality_flags"],
            },
            "rollback": control["rollback_level"],
            "final_decision": control["final_decision"],
            "objective_metrics": {
                "before": result["before_metrics"],
                "d041_baseline": baseline_result["after_metrics"],
                "after": result["after_metrics"],
                "delta_vs_input": _delta(result["after_metrics"], result["before_metrics"]),
                "delta_vs_d041": _delta(result["after_metrics"], baseline_result["after_metrics"]),
            },
            "decision_unchanged": analysis["processing_decision"] == baseline_result["analysis"]["processing_decision"],
            "output_policy_unchanged": analysis["output_policy"] == baseline_result["analysis"]["output_policy"],
            "matrix_checks": matrix_checks,
            "matrix_status": "PASS" if all(item["pass"] for item in matrix_checks) else "FAIL",
            "result": result,
        })

    record_map = {record["sample_id"]: record for record in records}
    gt = discovered["01"]
    reference_trends: dict[str, Any] = {}
    for sample_id in ("02", "03", "04"):
        source = discovered[sample_id]
        baseline_output = Path(record_map[sample_id]["baseline_path"])
        final_output = Path(record_map[sample_id]["output_path"])
        reference_trends[sample_id] = {
            "input_lab_distance": round(_lab_distance(gt, source), 4),
            "d041_lab_distance": round(_lab_distance(gt, baseline_output), 4),
            "d042_lab_distance": round(_lab_distance(gt, final_output), 4),
            "input_luma_mae": round(_luma_mae(gt, source), 4),
            "d041_luma_mae": round(_luma_mae(gt, baseline_output), 4),
            "d042_luma_mae": round(_luma_mae(gt, final_output), 4),
        }

    full_sheet = output_root / "before_after_contact_sheet.jpg"
    improvement_sheet = output_root / "improvement_samples_before_after_contact_sheet.jpg"
    _full_contact_sheet(records, full_sheet)
    _improvement_contact_sheet([record_map[sample_id] for sample_id in IMPROVEMENT_IDS], improvement_sheet)

    c1 = record_map["05"]
    c2 = record_map["06"]
    c4 = record_map["08"]
    c1_local = c1["strength"]["local_executor"]
    c1_baseline_local = baseline_records["05"]["result"]["parameters"]["local_executor"]
    c4_local = c4["strength"]["local_executor"]
    c4_baseline_local = baseline_records["08"]["result"]["parameters"]["local_executor"]
    b2_delta = record_map["04"]["objective_metrics"]["delta_vs_d041"]
    c2_delta = c2["objective_metrics"]["delta_vs_d041"]
    gates = {
        "improvement_sample_execution": all(
            record_map[sample_id]["changed_vs_d041"]
            and record_map[sample_id]["final_decision"] == "FINAL_ACCEPTED"
            for sample_id in IMPROVEMENT_IDS
        ),
        "protection_sample_regression": all(
            not record_map[sample_id]["changed_vs_d041"]
            and record_map[sample_id]["decision_unchanged"]
            and record_map[sample_id]["output_policy_unchanged"]
            for sample_id in PROTECTION_IDS
        ),
        "wb_effectiveness": all(
            reference_trends[sample_id]["d042_lab_distance"] <= reference_trends[sample_id]["d041_lab_distance"] - 0.10
            and record_map[sample_id]["execution_path"] == "global_white_balance"
            and record_map[sample_id]["quality_gate"]["post_process"] == "PASS"
            for sample_id in ("02", "03")
        ),
        "tonal_effectiveness": bool(
            reference_trends["04"]["d042_lab_distance"] < reference_trends["04"]["d041_lab_distance"]
            and reference_trends["04"]["d042_luma_mae"] < reference_trends["04"]["d041_luma_mae"]
            and b2_delta["midtone_point"] >= 3.0
            and b2_delta["white_point"] >= 1.0
            and record_map["04"]["quality_gate"]["post_process"] == "PASS"
        ),
        "local_person_effectiveness": bool(
            c1["execution_path"] == "local_person_exposure"
            and c1_local["target_gain"] >= c1_baseline_local["target_gain"]
            and c1_local["quality_gate"]
            and c1_local["non_target_mae"] <= 0.08
            and c1["changed_vs_d041"]
        ),
        "perceptual_transparency": bool(
            c2["execution_path"] == "transparency_and_layering"
            and c2_delta["dynamic_range"] >= 5.0
            and c2_delta["local_contrast"] >= 0.10
            and c2_delta["midtone_point"] >= 1.0
            and abs(c2_delta["mean_luminance"]) <= 5.0
            and c2["result"]["parameters"]["clarity_strength"] == 0.0
            and c2["result"]["parameters"]["selective_color_strength"] == 0.0
        ),
        "led_local_effectiveness": bool(
            c4["execution_path"] == "led_local_contamination"
            and c4_local["target_gain"] >= c4_baseline_local["target_gain"] + 1.0
            and c4_local["quality_gate"]
            and c4_local["screen_mae"] <= 0.10
            and c4["changed_vs_d041"]
        ),
        "naturalness_safety_gate": all(
            record_map[sample_id]["quality_gate"]["post_process"] == "PASS"
            and not record_map[sample_id]["quality_gate"]["remaining_violations"]
            and record_map[sample_id]["final_decision"] == "FINAL_ACCEPTED"
            for sample_id in IMPROVEMENT_IDS
        ),
        "matrix": all(record["matrix_status"] == "PASS" for record in records),
        "sample_run": len(records) == 15,
        "real_outputs": all(Path(record["output_path"]).is_file() and Path(record["output_path"]).stat().st_size > 0 for record in records),
        "contact_sheets": all(path.is_file() and path.stat().st_size > 0 for path in (full_sheet, improvement_sheet)),
    }

    source_after = {sample_id: _fingerprint(path) for sample_id, path in discovered.items()}
    settings_after = _fingerprint(settings_path)
    formal_after = _tree_fingerprint(formal_output)
    protections = {
        "source_protection": source_before == source_after,
        "settings_protection": settings_before == settings_after,
        "formal_output_protection": formal_before == formal_after,
        "formal_output_used": False,
    }
    summary = {
        "evaluation": "HDDE D-04.2 automatic color correction effective gain",
        "human_visual_review": "PENDING",
        "sample_run": f"{len(records)}/15",
        "input_root": str(input_root),
        "output_root": str(output_root),
        "d041_baseline": str(baseline_path),
        "contact_sheet_path": str(full_sheet),
        "improvement_contact_sheet_path": str(improvement_sheet),
        "reference_trends": reference_trends,
        "gates": gates,
        "protections": protections,
        "changed_samples": [record["sample_id"] for record in records if record["changed_vs_d041"]],
        "records": records,
    }
    report_path = output_root / "d042_evaluation_records.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "records"}, ensure_ascii=False, indent=2))
    protection_pass = bool(
        protections["source_protection"]
        and protections["settings_protection"]
        and protections["formal_output_protection"]
        and not protections["formal_output_used"]
    )
    return 0 if all(gates.values()) and protection_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
