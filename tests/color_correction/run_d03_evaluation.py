"""Run the fixed 15-image D-03 local-person correction evaluation."""

from __future__ import annotations

import argparse
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
from engine.color_correction.core import (
    _color_region_features,
    _detect_faces,
    _detect_local_faces,
    _local_person_masks,
)
from tests.color_correction.run_d01_evaluation import SAMPLE_LABELS, _checks
from tests.color_correction.run_d02_evaluation import _discover, _fingerprint, _font, _load_rgb, _sha256


LOCAL_IDS = {"05", "08"}
PERSON_REVIEW_IDS = ("01", "05", "07", "08", "13")


def _pixel_changed(left: Path, right: Path) -> bool:
    return not np.array_equal(_load_rgb(left), _load_rgb(right))


def _contact_sheet(records: list[dict[str, Any]], path: Path) -> None:
    tile_width, tile_height = 720, 400
    sheet = Image.new("RGB", (tile_width * 3, tile_height * 5), "#d8d8d8")
    title_font = _font(17)
    meta_font = _font(13)
    for index, record in enumerate(records):
        tile = Image.new("RGB", (tile_width, tile_height), "white")
        with Image.open(record["pre_local_path"]) as image:
            before = ImageOps.contain(image.convert("RGB"), (335, 292))
        with Image.open(record["output_path"]) as image:
            after = ImageOps.contain(image.convert("RGB"), (335, 292))
        tile.paste(before, ((350 - before.width) // 2, 68 + (292 - before.height) // 2))
        tile.paste(after, (370 + (335 - after.width) // 2, 68 + (292 - after.height) // 2))
        draw = ImageDraw.Draw(tile)
        draw.text((12, 8), f"{record['sample_id']} {record['label']}", fill="black", font=title_font)
        draw.text((12, 34), "BEFORE (D-02)                 AFTER (D-03)", fill="#333333", font=meta_font)
        draw.text(
            (12, 52),
            f"decision={record['decision']}  execution={record['execution']}",
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


def _person_crop(image: Image.Image, faces: list[tuple[int, int, int, int]]) -> Image.Image:
    width, height = image.size
    if not faces:
        return ImageOps.fit(image.convert("RGB"), (560, 320), method=Image.Resampling.LANCZOS)
    left = min(x - int(w * 0.75) for x, _, w, _ in faces)
    top = min(y - int(h * 0.40) for _, y, _, h in faces)
    right = max(x + int(w * 1.75) for x, _, w, _ in faces)
    bottom = max(y + int(h * 3.05) for _, y, _, h in faces)
    left, top, right, bottom = max(0, left), max(0, top), min(width, right), min(height, bottom)
    target_aspect = 560.0 / 320.0
    crop_width = max(1, right - left)
    crop_height = max(1, bottom - top)
    if crop_width / crop_height < target_aspect:
        desired_width = min(width, int(round(crop_height * target_aspect)))
        center_x = (left + right) // 2
        left = max(0, min(width - desired_width, center_x - desired_width // 2))
        right = left + desired_width
    else:
        desired_height = min(height, int(round(crop_width / target_aspect)))
        center_y = (top + bottom) // 2
        top = max(0, min(height - desired_height, center_y - desired_height // 2))
        bottom = top + desired_height
    box = (left, top, right, bottom)
    crop = image.convert("RGB").crop(box)
    return crop.resize((560, 320), Image.Resampling.LANCZOS)


def _person_contact_sheet(records: dict[str, dict[str, Any]], path: Path) -> None:
    tile_height = 390
    sheet = Image.new("RGB", (1200, tile_height * len(PERSON_REVIEW_IDS)), "#d8d8d8")
    title_font = _font(18)
    meta_font = _font(13)
    for row, sample_id in enumerate(PERSON_REVIEW_IDS):
        record = records[sample_id]
        source_rgb = _load_rgb(Path(record["source_path"]))
        faces = _detect_local_faces(source_rgb, _detect_faces(source_rgb))
        with Image.open(record["pre_local_path"]) as before_image:
            before = _person_crop(before_image, faces)
        with Image.open(record["output_path"]) as after_image:
            after = _person_crop(after_image, faces)
        tile = Image.new("RGB", (1200, tile_height), "white")
        tile.paste(before, (24, 42))
        tile.paste(after, (616, 42))
        draw = ImageDraw.Draw(tile)
        draw.text((24, 8), f"{sample_id} {record['label']} | BEFORE (D-02)", fill="black", font=title_font)
        draw.text((616, 8), f"AFTER (D-03) | {record['execution']}", fill="black", font=title_font)
        draw.text(
            (24, 370),
            f"decision={record['decision']}  local_applied={record['local_executor_applied']}  pixel_changed={record['pixel_changed']}",
            fill="#333333",
            font=meta_font,
        )
        sheet.paste(tile, (0, row * tile_height))
    sheet.save(path, quality=95, subsampling=0)


def _local_metrics(source_path: Path, pre_local_path: Path, output_path: Path) -> dict[str, float]:
    source = _load_rgb(source_path)
    before = _load_rgb(pre_local_path)
    after = _load_rgb(output_path)
    faces = _detect_local_faces(source, _detect_faces(source))
    face_mask, person_mask = _local_person_masks(source.shape[:2], faces)
    face_core = face_mask >= 0.55
    before_lab = cv2.cvtColor(before, cv2.COLOR_RGB2LAB).astype(np.float32)
    after_lab = cv2.cvtColor(after, cv2.COLOR_RGB2LAB).astype(np.float32)
    delta = np.abs(after.astype(np.float32) - before.astype(np.float32)).mean(axis=2)
    outside = person_mask <= 0.02
    strong_blue = face_core & ((before_lab[..., 2] - 128.0) < -8.0)
    unpolluted = face_core & ((before_lab[..., 2] - 128.0) >= 2.0)
    _, screen_mask, _ = _color_region_features(source)
    screen = (screen_mask >= 0.35) & (person_mask <= 0.08)
    before_luma = 0.2126 * before[..., 0] + 0.7152 * before[..., 1] + 0.0722 * before[..., 2]
    after_luma = 0.2126 * after[..., 0] + 0.7152 * after[..., 1] + 0.0722 * after[..., 2]
    face_chroma_delta = np.linalg.norm(after_lab[..., 1:3] - before_lab[..., 1:3], axis=2)
    return {
        "local_face_count": float(len(faces)),
        "face_l_median_before": round(float(np.median(before_lab[..., 0][face_core])), 3),
        "face_l_median_after": round(float(np.median(after_lab[..., 0][face_core])), 3),
        "face_chroma_mae": round(float(face_chroma_delta[face_core].mean()), 4),
        "strong_blue_b_mean_before": round(float((before_lab[..., 2][strong_blue] - 128.0).mean()), 3) if strong_blue.any() else 0.0,
        "strong_blue_b_mean_after": round(float((after_lab[..., 2][strong_blue] - 128.0).mean()), 3) if strong_blue.any() else 0.0,
        "face_b_p10_before": round(float(np.percentile(before_lab[..., 2][face_core] - 128.0, 10)), 3),
        "face_b_p10_after": round(float(np.percentile(after_lab[..., 2][face_core] - 128.0, 10)), 3),
        "unpolluted_face_chroma_mae": round(float(face_chroma_delta[unpolluted].mean()), 4) if unpolluted.any() else 0.0,
        "outside_person_mae": round(float(delta[outside].mean()), 4) if outside.any() else 0.0,
        "screen_mae": round(float(delta[screen].mean()), 4) if screen.any() else 0.0,
        "highlight_ratio_before": round(float((before_luma > 242.0).mean()), 5),
        "highlight_ratio_after": round(float((after_luma > 242.0).mean()), 5),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--d02-baseline", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    input_root = args.inputs.resolve()
    baseline_path = args.d02_baseline.resolve()
    output_root = args.output.resolve()
    if output_root.exists():
        raise RuntimeError(f"D-03 output must be a fresh isolated directory: {output_root}")
    output_root.mkdir(parents=True)
    result_root = output_root / "results"
    result_root.mkdir()

    settings_path = PROJECT_ROOT / "settings" / "settings.json"
    settings_before = _fingerprint(settings_path)
    settings_data = json.loads(settings_path.read_text(encoding="utf-8"))
    formal_output = Path(str(settings_data["default_output_dir"])).resolve()
    if output_root == formal_output or formal_output in output_root.parents:
        raise RuntimeError("D-03 evaluation must not use the formal output directory")

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
        baseline_record = baseline_records[sample_id]
        matrix_checks = [
            {"name": name, "pass": bool(predicate(analysis))}
            for name, predicate in checks[sample_id]
        ]
        records.append({
            "sample_id": sample_id,
            "label": SAMPLE_LABELS[sample_id],
            "source_path": str(source),
            "pre_local_path": baseline_record["output_path"],
            "output_path": str(target),
            "source_sha256": source_before[sample_id]["sha256"],
            "pre_local_sha256": baseline_record["output_sha256"],
            "output_sha256": result["output_sha256"],
            "decision": analysis["processing_decision"],
            "output_policy": analysis["output_policy"],
            "local_output_policy": analysis["local_output_policy"],
            "execution": analysis["algorithm_execution"],
            "algorithm_applied": bool(analysis["algorithm_applied"]),
            "local_executor_applied": bool(analysis["local_executor_applied"]),
            "pixel_changed": _pixel_changed(source, target),
            "pre_local_pixel_changed": _pixel_changed(Path(baseline_record["output_path"]), target),
            "decision_unchanged": analysis["processing_decision"] == baseline_record["decision"],
            "output_policy_unchanged": analysis["output_policy"] == baseline_record["output_policy"],
            "d02_output_unchanged": result["output_sha256"] == baseline_record["output_sha256"],
            "matrix_checks": matrix_checks,
            "matrix_status": "PASS" if all(item["pass"] for item in matrix_checks) else "FAIL",
            "result": result,
        })

    record_map = {record["sample_id"]: record for record in records}
    local_metrics = {
        sample_id: _local_metrics(
            Path(record_map[sample_id]["source_path"]),
            Path(record_map[sample_id]["pre_local_path"]),
            Path(record_map[sample_id]["output_path"]),
        )
        for sample_id in LOCAL_IDS
    }
    c1 = record_map["05"]
    c4 = record_map["08"]
    c1_parameters = c1["result"]["parameters"]["local_executor"]
    c4_parameters = c4["result"]["parameters"]["local_executor"]
    triggered = {record["sample_id"] for record in records if record["local_executor_applied"]}
    protected_ids = set(SAMPLE_LABELS) - LOCAL_IDS
    gates = {
        "local_person_exposure": (
            c1["execution"] == "local_person_exposure"
            and c1["local_executor_applied"]
            and 6.0 <= local_metrics["05"]["face_l_median_after"] - local_metrics["05"]["face_l_median_before"] <= 22.0
        ),
        "skin_environment_separation": (
            local_metrics["05"]["face_chroma_mae"] <= 1.5
            and local_metrics["08"]["unpolluted_face_chroma_mae"] <= 1.5
        ),
        "led_local_contamination": (
            c4["execution"] == "led_local_contamination"
            and c4["local_executor_applied"]
            and local_metrics["08"]["face_b_p10_after"] >= local_metrics["08"]["face_b_p10_before"] + 8.0
            and local_metrics["08"]["strong_blue_b_mean_after"] >= local_metrics["08"]["strong_blue_b_mean_before"] + 5.0
            and local_metrics["08"]["face_b_p10_after"] <= -8.0
        ),
        "local_blend_quality": (
            c1_parameters["blend_gate"] and c4_parameters["blend_gate"]
            and c1_parameters["transition_gradient_p99"] <= 4.0
            and c4_parameters["transition_gradient_p99"] <= 4.0
        ),
        "non_target_drift": (
            c1_parameters["non_target_drift_gate"] and c4_parameters["non_target_drift_gate"]
            and local_metrics["05"]["outside_person_mae"] <= 0.08
            and local_metrics["08"]["outside_person_mae"] <= 0.08
            and local_metrics["05"]["screen_mae"] <= 0.10
            and local_metrics["08"]["screen_mae"] <= 0.10
        ),
        "d02_regression_protection": (
            all(record["decision_unchanged"] and record["output_policy_unchanged"] for record in records)
            and all(record_map[sample_id]["d02_output_unchanged"] for sample_id in protected_ids)
            and triggered == LOCAL_IDS
        ),
        "original_semantics": all(
            record["decision"] != "ORIGINAL" or not record["algorithm_applied"]
            for record in records
        ),
        "a2_c3_c9_protection": all(record_map[sample_id]["d02_output_unchanged"] for sample_id in ("01", "07", "13")),
    }

    source_after = {sample_id: _fingerprint(path) for sample_id, path in discovered.items()}
    settings_after = _fingerprint(settings_path)
    full_sheet = output_root / "before_after_contact_sheet.jpg"
    person_sheet = output_root / "person_local_before_after_contact_sheet.jpg"
    _contact_sheet(records, full_sheet)
    _person_contact_sheet(record_map, person_sheet)
    outputs_valid = all(Path(record["output_path"]).is_file() and Path(record["output_path"]).stat().st_size > 0 for record in records)
    summary = {
        "evaluation": "HDDE D-03 local person and complex-light correction",
        "sample_run": f"{len(records)}/15",
        "matrix_status": "PASS" if all(record["matrix_status"] == "PASS" for record in records) else "FAIL",
        "outputs_valid": outputs_valid,
        "contact_sheet_path": str(full_sheet),
        "person_contact_sheet_path": str(person_sheet),
        "contact_sheets_valid": all(path.is_file() and path.stat().st_size > 0 for path in (full_sheet, person_sheet)),
        "sources_unchanged": source_before == source_after,
        "settings_unchanged": settings_before == settings_after,
        "formal_output_used": False,
        "input_root": str(input_root),
        "output_root": str(output_root),
        "d02_baseline": str(baseline_path),
        "triggered_local_samples": sorted(triggered),
        "local_metrics": local_metrics,
        "gates": gates,
        "records": records,
    }
    report_path = output_root / "d03_evaluation_records.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = bool(
        len(records) == 15
        and summary["matrix_status"] == "PASS"
        and outputs_valid
        and summary["contact_sheets_valid"]
        and summary["sources_unchanged"]
        and summary["settings_unchanged"]
        and all(gates.values())
    )
    print(json.dumps({key: value for key, value in summary.items() if key != "records"}, ensure_ascii=False, indent=2))
    for record in records:
        print(
            f"{record['sample_id']} {record['matrix_status']} decision={record['decision']} "
            f"execution={record['execution']} local_applied={record['local_executor_applied']} "
            f"pixel_changed={record['pixel_changed']}"
        )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
