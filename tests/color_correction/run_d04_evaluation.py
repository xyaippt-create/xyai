"""Run the fixed 15-image D-04 post-quality-gate convergence evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.color_correction.core import process_single_image
from engine.color_correction.core import _apply_local_person_correction, _metrics, _post_process_review
from tests.color_correction.run_d01_evaluation import SAMPLE_LABELS, _checks
from tests.color_correction.run_d02_evaluation import (
    _discover,
    _fingerprint,
    _font,
    _lab_distance,
    _load_rgb,
    _luma_mae,
)


CORE_IDS = ("02", "03", "04", "05", "06", "08")
GT_IDS = ("02", "03", "04")
TRACE_FIELDS = (
    "initial_decision",
    "global_applied",
    "global_execution",
    "global_quality_gate",
    "local_applied",
    "local_execution",
    "local_quality_gate",
    "strength_reduced",
    "rollback_level",
    "quality_flags",
    "final_decision",
    "algorithm_applied",
)


def _tree_fingerprint(root: Path | None) -> dict[str, Any]:
    if root is None or not root.exists():
        return {"exists": False}
    digest = hashlib.sha256()
    file_count = 0
    total_size = 0
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: str(item).lower()):
        stat = path.stat()
        relative = path.relative_to(root).as_posix()
        digest.update(f"{relative}|{stat.st_size}|{stat.st_mtime_ns}\n".encode("utf-8"))
        file_count += 1
        total_size += stat.st_size
    return {
        "exists": True,
        "file_count": file_count,
        "total_size": total_size,
        "metadata_sha256": digest.hexdigest(),
    }


def _controlled_branch_checks() -> dict[str, Any]:
    source = np.full((96, 128, 3), 180, dtype=np.uint8)
    source[:8] = 230
    focus = np.ones(source.shape[:2], dtype=np.float32)
    background = np.zeros_like(focus)
    strong_color = np.zeros_like(focus)
    analysis = {
        "strategy_id": "TONAL_DEPTH_RECOVERY",
        "person_local_adjustment_enabled": False,
        "person_region_reliably_detected": False,
        "strong_color_protection_enabled": False,
        "white_balance_applied": False,
    }
    generated: list[dict[str, float]] = []

    def highlight_factory(scales):
        generated.append(dict(scales))
        candidate = source.copy()
        candidate[:8] = int(np.clip(round(220.0 + 35.0 * float(scales["tone"])), 0, 255))
        return candidate, {"convergence_scales": dict(scales)}, {}

    full = {"tone": 1.0, "white_balance": 1.0, "shadow": 1.0, "person": 1.0, "skin": 1.0, "detail": 1.0, "color": 1.0}
    initial, _, _ = highlight_factory(full)
    highlight_result, highlight_review = _post_process_review(
        source,
        initial,
        _metrics(source, focus, background),
        focus,
        background,
        strong_color,
        analysis,
        np.zeros_like(focus),
        highlight_factory,
    )
    reduced_keys = set(highlight_review["strength_reduction_items"])

    def unsafe_factory(scales):
        return np.full_like(source, 255), {"convergence_scales": dict(scales)}, {}

    unsafe, _, _ = unsafe_factory(full)
    fallback_result, fallback_review = _post_process_review(
        source,
        unsafe,
        _metrics(source, focus, background),
        focus,
        background,
        strong_color,
        analysis,
        np.zeros_like(focus),
        unsafe_factory,
    )
    global_accepted = np.full((180, 240, 3), 92, dtype=np.uint8)
    local_result, local_parameters, local_analysis = _apply_local_person_correction(
        global_accepted,
        [(80, 32, 64, 64)],
        {
            "processing_decision": "LOCAL_REQUIRED",
            "output_policy": "LOCAL_REQUIRED",
            "person": {"local_light_contamination": False},
        },
        np.ones(global_accepted.shape[:2], dtype=np.float32),
    )
    return {
        "dynamic_strength_reduction": {
            "pass": bool(
                highlight_review["strength_reduced"]
                and "HIGHLIGHT_LOSS" in highlight_review["quality_flags"]
                and reduced_keys == {"tone"}
                and not np.array_equal(highlight_result, source)
            ),
            "reduced_parameters": sorted(reduced_keys),
            "quality_flags": highlight_review["quality_flags"],
            "attempt_count": len(highlight_review["attempts"]),
        },
        "original_fallback": {
            "pass": bool(
                fallback_review["final_candidate_level"] == "ORIGINAL"
                and np.array_equal(fallback_result, source)
            ),
            "final_candidate_level": fallback_review["final_candidate_level"],
            "attempt_count": len(fallback_review["attempts"]),
        },
        "local_rollback": {
            "pass": bool(
                local_analysis["local_rollback_applied"]
                and not local_analysis["local_executor_applied"]
                and local_analysis["local_target_quality_pass"] is False
                and np.array_equal(local_result, global_accepted)
            ),
            "mode": local_parameters["mode"],
            "execution": local_analysis["local_execution"],
        },
    }


def _draw_pair(record: dict[str, Any], tile_size: tuple[int, int]) -> Image.Image:
    tile_width, tile_height = tile_size
    tile = Image.new("RGB", tile_size, "white")
    image_width = (tile_width - 48) // 2
    image_height = tile_height - 126
    with Image.open(record["source_path"]) as image:
        original = ImageOps.contain(ImageOps.exif_transpose(image).convert("RGB"), (image_width, image_height))
    with Image.open(record["output_path"]) as image:
        final = ImageOps.contain(image.convert("RGB"), (image_width, image_height))
    tile.paste(original, (12 + (image_width - original.width) // 2, 72 + (image_height - original.height) // 2))
    tile.paste(final, (36 + image_width + (image_width - final.width) // 2, 72 + (image_height - final.height) // 2))
    draw = ImageDraw.Draw(tile)
    title_font = _font(17)
    meta_font = _font(12)
    draw.text((12, 6), f"{record['sample_id']} {record['label']}", fill="black", font=title_font)
    draw.text((12, 31), "ORIGINAL INPUT", fill="#333333", font=meta_font)
    draw.text((36 + image_width, 31), "FINAL RESULT", fill="#333333", font=meta_font)
    draw.text(
        (12, 49),
        f"initial={record['initial_decision']}  global={record['global_execution']} / {record['global_quality_gate']}",
        fill="#333333",
        font=meta_font,
    )
    reduced = ",".join(record["reduced_parameters"]) or "none"
    draw.text(
        (12, tile_height - 48),
        f"local={record['local_execution']} / {record['local_quality_gate']}  reduced={reduced}",
        fill="#333333",
        font=meta_font,
    )
    draw.text(
        (12, tile_height - 27),
        f"rollback={record['rollback_level']}  final={record['final_decision']}  matrix={record['matrix_status']}",
        fill="#333333",
        font=meta_font,
    )
    return tile


def _contact_sheet(records: list[dict[str, Any]], path: Path, columns: int, tile_size: tuple[int, int]) -> None:
    rows = (len(records) + columns - 1) // columns
    sheet = Image.new("RGB", (tile_size[0] * columns, tile_size[1] * rows), "#d8d8d8")
    for index, record in enumerate(records):
        sheet.paste(_draw_pair(record, tile_size), ((index % columns) * tile_size[0], (index // columns) * tile_size[1]))
    sheet.save(path, quality=94, subsampling=0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--d03-baseline", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    input_root = args.inputs.resolve()
    baseline_path = args.d03_baseline.resolve()
    output_root = args.output.resolve()
    if output_root.exists():
        raise RuntimeError(f"D-04 output must be a fresh isolated directory: {output_root}")
    output_root.mkdir(parents=True)
    result_root = output_root / "results"
    result_root.mkdir()

    settings_path = PROJECT_ROOT / "settings" / "settings.json"
    settings_before = _fingerprint(settings_path)
    settings_data = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else {}
    formal_output = Path(str(settings_data["default_output_dir"])).resolve() if settings_data.get("default_output_dir") else None
    if formal_output and (output_root == formal_output or formal_output in output_root.parents):
        raise RuntimeError("D-04 evaluation must not use the formal output directory")
    formal_before = _tree_fingerprint(formal_output)

    discovered = _discover(input_root)
    source_before = {sample_id: _fingerprint(path) for sample_id, path in discovered.items()}
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline_records = {record["sample_id"]: record for record in baseline["records"]}
    if set(baseline_records) != set(SAMPLE_LABELS):
        raise RuntimeError("D-03 baseline report does not contain the fixed 15 samples")

    checks = _checks()
    records: list[dict[str, Any]] = []
    for sample_id in sorted(discovered):
        source = discovered[sample_id]
        target = result_root / source.name
        result = process_single_image(source, target).to_dict()
        analysis = result["analysis"]
        quality_control = result["parameters"]["quality_control"]
        matrix_checks = [{"name": name, "pass": bool(predicate(analysis))} for name, predicate in checks[sample_id]]
        trace_complete = bool(
            all(field in analysis and field in quality_control for field in TRACE_FIELDS)
            and [stage["stage"] for stage in analysis["processing_stages"]]
            == ["ORIGINAL", "GLOBAL_CANDIDATE", "GLOBAL_ACCEPTED", "LOCAL_CANDIDATE", "FINAL"]
        )
        reduction_items = analysis["strength_reduction_items"]
        responsibility_traceable = all(item["responsible_quality_flags"] for item in reduction_items.values())
        baseline_record = baseline_records[sample_id]
        records.append({
            "sample_id": sample_id,
            "label": SAMPLE_LABELS[sample_id],
            "source_path": str(source),
            "output_path": str(target),
            "source_sha256": source_before[sample_id]["sha256"],
            "output_sha256": result["output_sha256"],
            "d03_output_sha256": baseline_record["output_sha256"],
            "d03_output_unchanged": result["output_sha256"] == baseline_record["output_sha256"],
            "decision_unchanged": analysis["processing_decision"] == baseline_record["decision"],
            "output_policy_unchanged": analysis["output_policy"] == baseline_record["output_policy"],
            "initial_decision": analysis["initial_decision"],
            "global_execution": analysis["global_execution"],
            "global_applied": analysis["global_applied"],
            "global_quality_gate": analysis["global_quality_gate"],
            "local_execution": analysis["local_execution"],
            "local_applied": analysis["local_applied"],
            "local_quality_gate": analysis["local_quality_gate"],
            "strength_reduced": analysis["strength_reduced"],
            "reduced_parameters": sorted(reduction_items),
            "responsibility_traceable": responsibility_traceable,
            "rollback_level": analysis["rollback_level"],
            "quality_flags": analysis["quality_flags"],
            "final_decision": analysis["final_decision"],
            "algorithm_applied": analysis["algorithm_applied"],
            "trace_complete": trace_complete,
            "matrix_checks": matrix_checks,
            "matrix_status": "PASS" if all(item["pass"] for item in matrix_checks) else "FAIL",
            "result": result,
        })

    record_map = {record["sample_id"]: record for record in records}
    gt_path = discovered["01"]
    gt_trend: dict[str, Any] = {}
    for sample_id in GT_IDS:
        source = discovered[sample_id]
        baseline_output = Path(baseline_records[sample_id]["output_path"])
        final_output = Path(record_map[sample_id]["output_path"])
        gt_trend[sample_id] = {
            "input_lab_distance": round(_lab_distance(gt_path, source), 4),
            "d03_lab_distance": round(_lab_distance(gt_path, baseline_output), 4),
            "d04_lab_distance": round(_lab_distance(gt_path, final_output), 4),
            "input_luma_mae": round(_luma_mae(gt_path, source), 4),
            "d03_luma_mae": round(_luma_mae(gt_path, baseline_output), 4),
            "d04_luma_mae": round(_luma_mae(gt_path, final_output), 4),
            "d03_gain_preserved": record_map[sample_id]["d03_output_unchanged"],
        }

    controlled = _controlled_branch_checks()
    source_after = {sample_id: _fingerprint(path) for sample_id, path in discovered.items()}
    settings_after = _fingerprint(settings_path)
    formal_after = _tree_fingerprint(formal_output)
    full_sheet = output_root / "before_after_contact_sheet.jpg"
    core_sheet = output_root / "core_quality_before_after_contact_sheet.jpg"
    _contact_sheet(records, full_sheet, columns=3, tile_size=(760, 430))
    _contact_sheet([record_map[sample_id] for sample_id in CORE_IDS], core_sheet, columns=2, tile_size=(900, 480))

    natural_reductions = {
        record["sample_id"]: record["reduced_parameters"] for record in records if record["strength_reduced"]
    }
    natural_local_rollbacks = [record["sample_id"] for record in records if record["local_quality_gate"] == "ROLLED_BACK_TO_GLOBAL"]
    natural_original_fallbacks = [record["sample_id"] for record in records if record["global_quality_gate"] == "FALLBACK_ORIGINAL"]
    outputs_valid = all(Path(record["output_path"]).is_file() and Path(record["output_path"]).stat().st_size > 0 for record in records)
    sheets_valid = all(path.is_file() and path.stat().st_size > 0 for path in (full_sheet, core_sheet))
    gates = {
        "post_quality_gate": all(record["trace_complete"] for record in records),
        "dynamic_strength_reduction": controlled["dynamic_strength_reduction"]["pass"],
        "local_rollback": controlled["local_rollback"]["pass"],
        "original_fallback": controlled["original_fallback"]["pass"],
        "responsibility_specific_reduction": all(record["responsibility_traceable"] for record in records),
        "positive_gain_preservation": all(record_map[sample_id]["d03_output_unchanged"] for sample_id in CORE_IDS),
        "d01_d03_regression_protection": all(
            record["decision_unchanged"] and record["output_policy_unchanged"] and record["d03_output_unchanged"]
            for record in records
        ),
        "a2_offline_gt": all(gt_trend[sample_id]["d03_gain_preserved"] for sample_id in GT_IDS),
        "sample_matrix": all(record["matrix_status"] == "PASS" for record in records),
        "sample_run": len(records) == 15,
        "real_outputs": outputs_valid and sheets_valid,
        "source_protection": source_before == source_after,
        "settings_protection": settings_before == settings_after,
        "formal_output_protection": formal_before == formal_after,
    }
    summary = {
        "evaluation": "HDDE D-04 post-quality-gate final convergence",
        "sample_run": f"{len(records)}/15",
        "matrix_status": "PASS" if gates["sample_matrix"] else "FAIL",
        "outputs_valid": outputs_valid,
        "contact_sheets_valid": sheets_valid,
        "before_after_contact_sheet_path": str(full_sheet),
        "core_quality_before_after_contact_sheet_path": str(core_sheet),
        "sources_unchanged": source_before == source_after,
        "settings_unchanged": settings_before == settings_after,
        "formal_output_unchanged": formal_before == formal_after,
        "formal_output_used": False,
        "input_root": str(input_root),
        "output_root": str(output_root),
        "d03_baseline": str(baseline_path),
        "b2_final_convergence": "KEEP_BASELINE" if record_map["04"]["d03_output_unchanged"] else "FAIL",
        "c2_final_convergence": "KEEP_BASELINE" if record_map["06"]["d03_output_unchanged"] else "FAIL",
        "natural_strength_reductions": natural_reductions,
        "natural_local_rollbacks": natural_local_rollbacks,
        "natural_original_fallbacks": natural_original_fallbacks,
        "controlled_branch_evidence": controlled,
        "a2_offline_gt_trend": gt_trend,
        "formal_output_fingerprint_before": formal_before,
        "formal_output_fingerprint_after": formal_after,
        "gates": gates,
        "records": records,
    }
    report_path = output_root / "d04_evaluation_records.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = all(gates.values()) and summary["b2_final_convergence"] != "FAIL" and summary["c2_final_convergence"] != "FAIL"
    print(json.dumps({key: value for key, value in summary.items() if key != "records"}, ensure_ascii=False, indent=2))
    for record in records:
        print(
            f"{record['sample_id']} {record['matrix_status']} initial={record['initial_decision']} "
            f"global_gate={record['global_quality_gate']} local_gate={record['local_quality_gate']} "
            f"reduced={record['reduced_parameters']} rollback={record['rollback_level']} final={record['final_decision']}"
        )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
