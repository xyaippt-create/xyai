"""Run the fixed 15-image D-04.1 low-contrast transparency convergence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.color_correction.core import process_single_image
from tests.color_correction.run_d01_evaluation import SAMPLE_LABELS, _checks
from tests.color_correction.run_d02_evaluation import _discover, _fingerprint, _font, _load_rgb
from tests.color_correction.run_d04_evaluation import _tree_fingerprint


C2_ID = "06"


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
        draw.text((12, 34), "ORIGINAL INPUT                 D-04.1 FINAL", fill="#333333", font=meta_font)
        draw.text(
            (12, 52),
            f"execution={record['execution']}  gate={record['quality_gate']}",
            fill="#333333",
            font=meta_font,
        )
        draw.text(
            (12, 375),
            f"changed_vs_d04={not record['d04_output_unchanged']}  matrix={record['matrix_status']}",
            fill="#333333",
            font=meta_font,
        )
        sheet.paste(tile, ((index % 3) * tile_width, (index // 3) * tile_height))
    sheet.save(path, quality=94, subsampling=0)


def _c2_detail(record: dict[str, Any], path: Path) -> None:
    canvas = Image.new("RGB", (1800, 1120), "white")
    with Image.open(record["baseline_path"]) as image:
        before = ImageOps.contain(image.convert("RGB"), (860, 930))
    with Image.open(record["output_path"]) as image:
        after = ImageOps.contain(image.convert("RGB"), (860, 930))
    canvas.paste(before, (20 + (860 - before.width) // 2, 100 + (930 - before.height) // 2))
    canvas.paste(after, (920 + (860 - after.width) // 2, 100 + (930 - after.height) // 2))
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 18), "C2 | D-04 BASELINE", fill="black", font=_font(22))
    draw.text((920, 18), "C2 | D-04.1 CANDIDATE", fill="black", font=_font(22))
    before = record["baseline_metrics"]
    after = record["result"]["after_metrics"]
    draw.text(
        (20, 54),
        f"black={before['black_point']} mid={before['midtone_point']} white={before['white_point']} local={before['local_contrast']} range={before['dynamic_range']}",
        fill="#333333",
        font=_font(14),
    )
    draw.text(
        (920, 54),
        f"black={after['black_point']} mid={after['midtone_point']} white={after['white_point']} local={after['local_contrast']} range={after['dynamic_range']}",
        fill="#333333",
        font=_font(14),
    )
    draw.text(
        (20, 1075),
        "Review: black stability | midtones | people/background separation | spatial depth | color cleanliness | processing feel",
        fill="#333333",
        font=_font(15),
    )
    canvas.save(path, quality=95, subsampling=0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--d04-baseline", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    input_root = args.inputs.resolve()
    baseline_path = args.d04_baseline.resolve()
    output_root = args.output.resolve()
    if output_root.exists():
        raise RuntimeError(f"D-04.1 output must be a fresh isolated directory: {output_root}")
    output_root.mkdir(parents=True)
    result_root = output_root / "results"
    result_root.mkdir()

    settings_path = PROJECT_ROOT / "settings" / "settings.json"
    settings_before = _fingerprint(settings_path)
    settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else {}
    formal_output = Path(str(settings["default_output_dir"])).resolve() if settings.get("default_output_dir") else None
    if formal_output and (output_root == formal_output or formal_output in output_root.parents):
        raise RuntimeError("D-04.1 evaluation must not use the formal output directory")
    formal_before = _tree_fingerprint(formal_output)

    discovered = _discover(input_root)
    source_before = {sample_id: _fingerprint(path) for sample_id, path in discovered.items()}
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline_records = {record["sample_id"]: record for record in baseline["records"]}
    checks = _checks()
    records: list[dict[str, Any]] = []
    for sample_id in sorted(discovered):
        source = discovered[sample_id]
        target = result_root / source.name
        result = process_single_image(source, target).to_dict()
        analysis = result["analysis"]
        matrix_checks = [{"name": name, "pass": bool(predicate(analysis))} for name, predicate in checks[sample_id]]
        baseline_record = baseline_records[sample_id]
        records.append({
            "sample_id": sample_id,
            "label": SAMPLE_LABELS[sample_id],
            "source_path": str(source),
            "baseline_path": baseline_record["output_path"],
            "output_path": str(target),
            "source_sha256": source_before[sample_id]["sha256"],
            "d04_output_sha256": baseline_record["output_sha256"],
            "output_sha256": result["output_sha256"],
            "d04_output_unchanged": result["output_sha256"] == baseline_record["output_sha256"],
            "decision_unchanged": analysis["processing_decision"] == baseline_record["initial_decision"],
            "output_policy_unchanged": analysis["output_policy"] == baseline_record["result"]["analysis"]["output_policy"],
            "execution": analysis["algorithm_execution"],
            "quality_gate": analysis["global_quality_gate"],
            "quality_flags": analysis["quality_flags"],
            "matrix_checks": matrix_checks,
            "matrix_status": "PASS" if all(item["pass"] for item in matrix_checks) else "FAIL",
            "baseline_metrics": baseline_record["result"]["after_metrics"],
            "result": result,
        })

    record_map = {record["sample_id"]: record for record in records}
    c2 = record_map[C2_ID]
    c2_before = c2["baseline_metrics"]
    c2_after = c2["result"]["after_metrics"]
    c2_parameters = c2["result"]["parameters"]
    other_ids = set(SAMPLE_LABELS) - {C2_ID}
    source_after = {sample_id: _fingerprint(path) for sample_id, path in discovered.items()}
    settings_after = _fingerprint(settings_path)
    formal_after = _tree_fingerprint(formal_output)
    contact_sheet = output_root / "before_after_contact_sheet.jpg"
    c2_detail = output_root / "c2_quality_before_after.jpg"
    _contact_sheet(records, contact_sheet)
    _c2_detail(c2, c2_detail)

    gates = {
        "c2_trigger": bool(
            c2["execution"] == "transparency_and_layering"
            and c2["result"]["analysis"]["low_contrast"]
            and c2["result"]["analysis"]["floating_black"]
            and c2_parameters["spatial_layering_strength"] > 0.0
        ),
        "c2_transparency_gain": bool(
            c2_after["dynamic_range"] >= c2_before["dynamic_range"] + 5.0
            and c2_after["white_point"] >= c2_before["white_point"] + 3.0
            and c2_after["black_point"] <= c2_before["black_point"] - 1.0
        ),
        "c2_layering_gain": bool(c2_after["local_contrast"] >= c2_before["local_contrast"] + 0.20),
        "naturalness": bool(
            c2["quality_gate"] in {"ACCEPTED_FULL", "ACCEPTED_REDUCED"}
            and not c2["quality_flags"]
            and abs(c2_after["mean_luminance"] - c2_before["mean_luminance"]) <= 2.0
            and c2_after["highlight_ratio"] <= c2_before["highlight_ratio"] + 0.002
            and c2_after["mean_saturation"] <= c2_before["mean_saturation"] + 0.01
            and c2_parameters["clarity_strength"] == 0.0
            and c2_parameters["selective_color_strength"] == 0.0
        ),
        "d04_quality_gate": bool(c2["quality_gate"] in {"ACCEPTED_FULL", "ACCEPTED_REDUCED"}),
        "other_14_regression_protection": all(
            record_map[sample_id]["d04_output_unchanged"]
            and record_map[sample_id]["decision_unchanged"]
            and record_map[sample_id]["output_policy_unchanged"]
            for sample_id in other_ids
        ),
        "matrix": all(record["matrix_status"] == "PASS" for record in records),
        "sample_run": len(records) == 15,
        "real_outputs": all(Path(record["output_path"]).is_file() and Path(record["output_path"]).stat().st_size > 0 for record in records),
        "contact_sheets": all(path.is_file() and path.stat().st_size > 0 for path in (contact_sheet, c2_detail)),
        "source_protection": source_before == source_after,
        "settings_protection": settings_before == settings_after,
        "formal_output_protection": formal_before == formal_after,
    }
    summary = {
        "evaluation": "HDDE D-04.1 low-contrast transparency convergence",
        "sample_run": f"{len(records)}/15",
        "matrix_status": "PASS" if gates["matrix"] else "FAIL",
        "contact_sheet_path": str(contact_sheet),
        "c2_detail_path": str(c2_detail),
        "input_root": str(input_root),
        "output_root": str(output_root),
        "d04_baseline": str(baseline_path),
        "sources_unchanged": source_before == source_after,
        "settings_unchanged": settings_before == settings_after,
        "formal_output_unchanged": formal_before == formal_after,
        "formal_output_used": False,
        "changed_samples": [record["sample_id"] for record in records if not record["d04_output_unchanged"]],
        "c2_metrics": {"d04": c2_before, "d041": c2_after},
        "c2_parameters": {
            key: c2_parameters[key]
            for key in (
                "tonal_curve_strength",
                "tonal_curve_source_points",
                "tonal_curve_target_points",
                "local_contrast_strength",
                "spatial_layering_strength",
                "clarity_strength",
                "selective_color_strength",
            )
        },
        "gates": gates,
        "records": records,
    }
    report_path = output_root / "d041_evaluation_records.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "records"}, ensure_ascii=False, indent=2))
    return 0 if all(gates.values()) and summary["changed_samples"] == [C2_ID] else 1


if __name__ == "__main__":
    raise SystemExit(main())
