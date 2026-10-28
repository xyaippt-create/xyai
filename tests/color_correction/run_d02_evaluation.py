"""Run the fixed D-01 samples against the D-02 global executor upgrade."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.color_correction.core import process_single_image
from tests.color_correction.run_d01_evaluation import SAMPLE_LABELS, _checks


PROTECTED_SAMPLE_IDS = {"01", "05", "07", "08", "09", "10", "11", "12", "13", "14", "15"}
GT_SAMPLE_IDS = {"02", "03", "04"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "sha256": _sha256(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(ImageOps.exif_transpose(image).convert("RGB"))


def _pixel_changed(source: Path, output: Path) -> bool:
    return not np.array_equal(_load_rgb(source), _load_rgb(output))


def _lab_distance(reference: Path, candidate: Path) -> float:
    reference_rgb = _load_rgb(reference)
    candidate_rgb = _load_rgb(candidate)
    if reference_rgb.shape != candidate_rgb.shape:
        raise RuntimeError(f"GT comparison dimensions differ: {reference} vs {candidate}")
    reference_lab = cv2.cvtColor(reference_rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    candidate_lab = cv2.cvtColor(candidate_rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    return float(np.linalg.norm(reference_lab - candidate_lab, axis=2).mean())


def _luma_mae(reference: Path, candidate: Path) -> float:
    reference = _load_rgb(reference).astype(np.float32)
    candidate = _load_rgb(candidate).astype(np.float32)
    reference_luma = 0.2126 * reference[..., 0] + 0.7152 * reference[..., 1] + 0.0722 * reference[..., 2]
    candidate_luma = 0.2126 * candidate[..., 0] + 0.7152 * candidate[..., 1] + 0.0722 * candidate[..., 2]
    return float(np.abs(reference_luma - candidate_luma).mean())


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
    ):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _contact_sheet(records: list[dict[str, Any]], path: Path) -> None:
    tile_width, tile_height = 720, 400
    sheet = Image.new("RGB", (tile_width * 3, tile_height * 5), "#d8d8d8")
    title_font = _font(17)
    meta_font = _font(13)
    for index, record in enumerate(records):
        tile = Image.new("RGB", (tile_width, tile_height), "white")
        with Image.open(record["source_path"]) as image:
            before = ImageOps.contain(ImageOps.exif_transpose(image).convert("RGB"), (335, 292))
        with Image.open(record["output_path"]) as image:
            after = ImageOps.contain(image.convert("RGB"), (335, 292))
        tile.paste(before, ((350 - before.width) // 2, 68 + (292 - before.height) // 2))
        tile.paste(after, (370 + (335 - after.width) // 2, 68 + (292 - after.height) // 2))
        draw = ImageDraw.Draw(tile)
        draw.text((12, 8), f"{record['sample_id']} {record['label']}", fill="black", font=title_font)
        draw.text((12, 34), f"BEFORE                          AFTER", fill="#333333", font=meta_font)
        draw.text(
            (12, 52),
            f"decision={record['decision']}  execution={record['algorithm_execution']}",
            fill="#333333",
            font=meta_font,
        )
        draw.text(
            (12, 375),
            f"algorithm_applied={record['algorithm_applied']}  pixel_changed={record['pixel_changed']}  matrix={record['matrix_status']}",
            fill="#333333",
            font=meta_font,
        )
        sheet.paste(tile, ((index % 3) * tile_width, (index // 3) * tile_height))
    sheet.save(path, quality=94, subsampling=0)


def _discover(input_root: Path) -> dict[str, Path]:
    discovered: dict[str, Path] = {}
    for path in input_root.glob("D01_*.*"):
        parts = path.stem.split("_")
        sample_id = parts[1] if len(parts) >= 2 else ""
        if sample_id in SAMPLE_LABELS:
            if sample_id in discovered:
                raise RuntimeError(f"duplicate sample: {sample_id}")
            discovered[sample_id] = path
    if set(discovered) != set(SAMPLE_LABELS):
        raise RuntimeError(
            f"D-02 samples must be the fixed 15 D-01 inputs; "
            f"missing={sorted(set(SAMPLE_LABELS) - set(discovered))}, "
            f"extra={sorted(set(discovered) - set(SAMPLE_LABELS))}"
        )
    return discovered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--d01-baseline", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    input_root = args.inputs.resolve()
    baseline_report_path = args.d01_baseline.resolve()
    output_root = args.output.resolve()
    if output_root.exists():
        raise RuntimeError(f"D-02 output must be a fresh isolated directory: {output_root}")
    output_root.mkdir(parents=True)
    result_root = output_root / "results"
    result_root.mkdir()

    settings_path = PROJECT_ROOT / "settings" / "settings.json"
    settings_before = _fingerprint(settings_path)
    settings_data = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else {}
    formal_output = Path(str(settings_data.get("default_output_dir", ""))).resolve() if settings_data.get("default_output_dir") else None
    if formal_output and (output_root == formal_output or formal_output in output_root.parents):
        raise RuntimeError("D-02 evaluation output must not use the formal output directory")

    baseline = json.loads(baseline_report_path.read_text(encoding="utf-8"))
    baseline_records = {record["sample_id"]: record for record in baseline["records"]}
    if set(baseline_records) != set(SAMPLE_LABELS):
        raise RuntimeError("D-01 baseline report does not contain the fixed 15 samples")

    discovered = _discover(input_root)
    source_before = {sample_id: _fingerprint(path) for sample_id, path in discovered.items()}
    records: list[dict[str, Any]] = []
    checks = _checks()
    for sample_id in sorted(discovered):
        source = discovered[sample_id]
        target = result_root / source.name
        result = process_single_image(source, target).to_dict()
        analysis = result["analysis"]
        pixel_changed = _pixel_changed(source, target)
        matrix_checks = [
            {"name": name, "pass": bool(predicate(analysis))}
            for name, predicate in checks[sample_id]
        ]
        baseline_record = baseline_records[sample_id]
        regression_checks = {
            "decision_unchanged": analysis["processing_decision"] == baseline_record["decision"],
            "output_policy_unchanged": analysis["output_policy"] == baseline_record["output_policy"],
        }
        if sample_id in PROTECTED_SAMPLE_IDS:
            regression_checks["protected_output_unchanged"] = result["output_sha256"] == baseline_record["output_sha256"]
        semantic_checks = {
            "original_has_no_algorithm": analysis["processing_decision"] != "ORIGINAL" or not analysis["algorithm_applied"],
            "original_protected_has_no_algorithm": analysis["output_policy"] != "ORIGINAL_PROTECTED" or not analysis["algorithm_applied"],
            "algorithm_pixel_flag_consistent": bool(analysis["algorithm_pixel_changed"]) == bool(analysis["algorithm_applied"] and pixel_changed),
        }
        records.append(
            {
                "sample_id": sample_id,
                "label": SAMPLE_LABELS[sample_id],
                "source_path": str(source),
                "output_path": str(target),
                "source_sha256": source_before[sample_id]["sha256"],
                "output_sha256": result["output_sha256"],
                "pixel_changed": pixel_changed,
                "algorithm_applied": bool(analysis["algorithm_applied"]),
                "algorithm_pixel_changed": bool(analysis["algorithm_pixel_changed"]),
                "algorithm_execution": analysis["algorithm_execution"],
                "decision": analysis["processing_decision"],
                "scope": analysis["processing_scope"],
                "output_policy": analysis["output_policy"],
                "strategy": analysis["strategy_id"],
                "final_candidate_level": analysis["final_candidate_level"],
                "matrix_checks": matrix_checks,
                "regression_checks": regression_checks,
                "semantic_checks": semantic_checks,
                "matrix_status": "PASS" if all(item["pass"] for item in matrix_checks) else "FAIL",
                "result": result,
            }
        )

    record_map = {record["sample_id"]: record for record in records}
    gt_path = discovered["01"]
    gt_trend: dict[str, Any] = {}
    for sample_id in sorted(GT_SAMPLE_IDS):
        source = discovered[sample_id]
        baseline_output = Path(baseline_records[sample_id]["output_path"])
        final_output = Path(record_map[sample_id]["output_path"])
        input_lab = _lab_distance(gt_path, source)
        baseline_lab = _lab_distance(gt_path, baseline_output)
        final_lab = _lab_distance(gt_path, final_output)
        input_luma = _luma_mae(gt_path, source)
        baseline_luma = _luma_mae(gt_path, baseline_output)
        final_luma = _luma_mae(gt_path, final_output)
        luma_target_ok = final_luma < input_luma if sample_id == "04" else final_luma <= 2.0
        gt_trend[sample_id] = {
            "label": SAMPLE_LABELS[sample_id],
            "input_lab_distance": round(input_lab, 4),
            "d01_lab_distance": round(baseline_lab, 4),
            "d02_lab_distance": round(final_lab, 4),
            "input_luma_mae": round(input_luma, 4),
            "d01_luma_mae": round(baseline_luma, 4),
            "d02_luma_mae": round(final_luma, 4),
            "improved_vs_input": final_lab < input_lab and luma_target_ok,
            "improved_vs_d01": final_lab < baseline_lab and final_luma < baseline_luma,
            "luma_target_ok": luma_target_ok,
        }

    b2 = record_map["04"]
    c2 = record_map["06"]
    c2_baseline = baseline_records["06"]["result"]["after_metrics"]
    c2_final = c2["result"]["after_metrics"]
    c2_parameters = c2["result"]["parameters"]
    gates = {
        "wb_execution": all(
            record_map[sample_id]["algorithm_execution"] == "global_white_balance"
            and gt_trend[sample_id]["improved_vs_input"]
            and gt_trend[sample_id]["improved_vs_d01"]
            for sample_id in ("02", "03")
        ),
        "tonal_execution": (
            b2["algorithm_execution"] == "coordinated_global_tonal_recovery"
            and gt_trend["04"]["improved_vs_input"]
            and gt_trend["04"]["improved_vs_d01"]
        ),
        "transparency_layering": (
            c2["algorithm_execution"] == "transparency_and_layering"
            and c2_final["black_point"] <= c2_baseline["black_point"] - 6.0
            and c2_final["dynamic_range"] >= c2_baseline["dynamic_range"] + 10.0
            and c2_final["local_contrast"] >= c2_baseline["local_contrast"] + 0.15
            and abs(c2_final["mean_luminance"] - c2_baseline["mean_luminance"]) <= 8.0
            and c2_final["mean_saturation"] <= c2_baseline["mean_saturation"] + 0.02
            and c2_parameters["clarity_strength"] == 0.0
            and c2_parameters["selective_color_strength"] == 0.0
        ),
        "natural_color": all(gt_trend[sample_id]["improved_vs_d01"] for sample_id in GT_SAMPLE_IDS),
        "d01_regression_protection": all(
            all(record["regression_checks"].values()) for record in records
        ),
        "original_semantics": all(all(record["semantic_checks"].values()) for record in records),
    }

    source_after = {sample_id: _fingerprint(path) for sample_id, path in discovered.items()}
    settings_after = _fingerprint(settings_path)
    settings_protection = settings_before == settings_after
    original_protection = source_before == source_after
    matrix_pass = all(record["matrix_status"] == "PASS" for record in records)
    outputs_valid = all(Path(record["output_path"]).is_file() and Path(record["output_path"]).stat().st_size > 0 for record in records)
    contact_sheet_path = output_root / "before_after_contact_sheet.jpg"
    _contact_sheet(records, contact_sheet_path)
    contact_sheet_valid = contact_sheet_path.is_file() and contact_sheet_path.stat().st_size > 0

    summary = {
        "evaluation": "HDDE D-02 global color executor quality upgrade",
        "sample_run": f"{len(records)}/15",
        "matrix_status": "PASS" if matrix_pass else "FAIL",
        "outputs_valid": outputs_valid,
        "contact_sheet_valid": contact_sheet_valid,
        "contact_sheet_path": str(contact_sheet_path),
        "sources_unchanged": original_protection,
        "settings_unchanged": settings_protection,
        "formal_output_used": False,
        "input_root": str(input_root),
        "output_root": str(output_root),
        "d01_baseline": str(baseline_report_path),
        "gt_trend": gt_trend,
        "c2_transparency_metrics": {
            "d01": c2_baseline,
            "d02": c2_final,
        },
        "gates": {
            **gates,
            "sample_run": len(records) == 15,
            "real_outputs": outputs_valid and contact_sheet_valid,
            "settings_protection": settings_protection,
            "original_protection": original_protection,
        },
        "records": records,
    }
    report_path = output_root / "d02_evaluation_records.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = matrix_pass and outputs_valid and contact_sheet_valid and all(summary["gates"].values())
    print(json.dumps({key: value for key, value in summary.items() if key != "records"}, ensure_ascii=False, indent=2))
    for record in records:
        print(
            f"{record['sample_id']} {record['matrix_status']} decision={record['decision']} "
            f"execution={record['algorithm_execution']} algorithm_applied={record['algorithm_applied']} "
            f"pixel_changed={record['pixel_changed']}"
        )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
