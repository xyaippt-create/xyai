"""Run the fixed 15-image Color Core V2 production integration regression."""

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

from engine.color_correction.core import COLOR_CORRECTION_ENGINE_VERSION, process_single_image
from engine.color_correction.color_core_v2 import COLOR_CORE_V2_VERSION, GLOBAL_ROUTE_NAME, LOCAL_ROUTE_NAME
from tests.color_correction.run_d01_evaluation import SAMPLE_LABELS


IMPROVEMENT_IDS = ("02", "03", "04", "05", "06", "08")
PROTECTION_IDS = ("01", "07", "09", "10", "11", "12", "13", "14", "15")
EXPECTED_EXECUTIONS = {
    "02": GLOBAL_ROUTE_NAME,
    "03": GLOBAL_ROUTE_NAME,
    "04": "coordinated_global_tonal_recovery",
    "05": "local_person_exposure",
    "06": "transparency_and_layering",
    "08": LOCAL_ROUTE_NAME,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fingerprint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {"exists": True, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": _sha256(path)}


def _tree_fingerprint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "files": []}
    files = []
    for item in sorted((entry for entry in path.rglob("*") if entry.is_file()), key=lambda value: str(value).lower()):
        stat = item.stat()
        files.append({"path": str(item.relative_to(path)), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return {"exists": True, "files": files}


def _load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(ImageOps.exif_transpose(image).convert("RGB"))


def _discover(path: Path) -> dict[str, Path]:
    discovered: dict[str, Path] = {}
    for item in path.iterdir():
        if item.is_file() and item.stem.startswith("D01_"):
            sample_id = item.stem.split("_")[-1]
            if sample_id in SAMPLE_LABELS:
                discovered[sample_id] = item
    return discovered


def _lab_distance(reference: np.ndarray, candidate: np.ndarray) -> float:
    reference_lab = cv2.cvtColor(reference.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    candidate_lab = cv2.cvtColor(candidate.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    return float(np.linalg.norm(reference_lab - candidate_lab, axis=2).mean())


def _pixel_delta(reference: np.ndarray, candidate: np.ndarray) -> dict[str, Any]:
    difference = np.abs(reference.astype(np.float32) - candidate.astype(np.float32))
    return {
        "pixel_equal": bool(np.array_equal(reference, candidate)),
        "rgb_mae": round(float(difference.mean()), 6),
        "rgb_max": int(difference.max()),
        "changed_pixel_ratio": round(float(np.any(reference != candidate, axis=2).mean()), 6),
    }


def _font(size: int) -> ImageFont.ImageFont:
    for path in (
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ):
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _native_triptych(source: Path, current: Path, final: Path, label: str, target: Path) -> None:
    panels = [ImageOps.exif_transpose(Image.open(path)).convert("RGB") for path in (source, current, final)]
    width, height = panels[0].size
    if any(panel.size != (width, height) for panel in panels):
        raise RuntimeError(f"native comparison dimension mismatch: {label}")
    header = 72
    canvas = Image.new("RGB", (width * 3, height + header), "#111318")
    draw = ImageDraw.Draw(canvas)
    title_font = _font(max(18, min(34, width // 38)))
    captions = ("ORIGINAL", "CURRENT_HDDE", "COLOR_CORE_V2_FINAL")
    for index, (panel, caption) in enumerate(zip(panels, captions)):
        left = index * width
        canvas.paste(panel, (left, header))
        draw.text((left + 18, 18), caption, fill="#F5F7FA", font=title_font)
        if index:
            draw.line((left, 0, left, height + header), fill="#657080", width=2)
    draw.text((width * 3 - 18, 18), label, fill="#AFC7FF", font=title_font, anchor="ra")
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, format="PNG", compress_level=6)


def _overview(rows: list[tuple[str, Path]], target: Path) -> None:
    row_width, panel_width, row_height, gap = 2700, 900, 520, 12
    title_height = 82
    canvas = Image.new("RGB", (row_width, title_height + len(rows) * (row_height + gap)), "#0E1116")
    draw = ImageDraw.Draw(canvas)
    title_font, label_font = _font(30), _font(24)
    for index, caption in enumerate(("ORIGINAL", "CURRENT_HDDE", "COLOR_CORE_V2_FINAL")):
        draw.text((index * panel_width + 24, 24), caption, fill="#F5F7FA", font=title_font)
    for row_index, (label, triptych_path) in enumerate(rows):
        with Image.open(triptych_path) as triptych:
            triptych = triptych.convert("RGB")
            panel_source_width = triptych.width // 3
            source_height = triptych.height - 72
            y = title_height + row_index * (row_height + gap)
            for panel_index in range(3):
                crop = triptych.crop((panel_index * panel_source_width, 72, (panel_index + 1) * panel_source_width, 72 + source_height))
                fitted = ImageOps.contain(crop, (panel_width, row_height), Image.Resampling.LANCZOS)
                x = panel_index * panel_width + (panel_width - fitted.width) // 2
                canvas.paste(fitted, (x, y + (row_height - fitted.height) // 2))
            draw.rectangle((10, y + 8, 530, y + 48), fill="#111318")
            draw.text((22, y + 12), label, fill="#AFC7FF", font=label_font)
            if row_index:
                draw.line((0, y - gap // 2, row_width, y - gap // 2), fill="#343B46", width=2)
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, format="JPEG", quality=94, subsampling=0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--baseline-record", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--formal-output", type=Path, required=True)
    args = parser.parse_args()

    inputs = _discover(args.inputs.resolve())
    if set(inputs) != set(SAMPLE_LABELS):
        raise RuntimeError(f"fixed sample set mismatch: {sorted(inputs)}")
    baseline_document = json.loads(args.baseline_record.resolve().read_text(encoding="utf-8"))
    baseline_records = {record["sample_id"]: record for record in baseline_document["records"]}
    if set(baseline_records) != set(SAMPLE_LABELS):
        raise RuntimeError("CURRENT_HDDE baseline does not contain 15 samples")

    output_root = args.output_root.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError("output root must be new and empty")
    results_dir, native_dir = output_root / "runtime_results", output_root / "native_comparisons"
    results_dir.mkdir(parents=True)
    native_dir.mkdir(parents=True)

    source_before = {sample_id: _fingerprint(path) for sample_id, path in inputs.items()}
    settings_before = _fingerprint(args.settings.resolve())
    formal_before = _tree_fingerprint(args.formal_output.resolve())
    runtime_sources = [PROJECT_ROOT / "engine/color_correction/core.py", PROJECT_ROOT / "engine/color_correction/color_core_v2.py"]
    runtime_source_text = "\n".join(path.read_text(encoding="utf-8") for path in runtime_sources)
    runtime_path_contract = bool(
        "tools.experiments" not in runtime_source_text
        and "output/evaluation" not in runtime_source_text
        and "SAMPLE_LABELS" not in runtime_source_text
    )

    records: list[dict[str, Any]] = []
    native_rows: list[tuple[str, Path]] = []
    for sample_id in sorted(inputs):
        source = inputs[sample_id]
        baseline = Path(baseline_records[sample_id]["output_path"]).resolve()
        target = results_dir / source.name
        result = process_single_image(source, target).to_dict()
        source_rgb, baseline_rgb, final_rgb = _load_rgb(source), _load_rgb(baseline), _load_rgb(target)
        delta = _pixel_delta(baseline_rgb, final_rgb)
        analysis = result["analysis"]
        triptych = native_dir / f"D01_{sample_id}_ORIGINAL_CURRENT_HDDE_COLOR_CORE_V2_FINAL.png"
        _native_triptych(source, baseline, target, SAMPLE_LABELS[sample_id], triptych)
        native_rows.append((SAMPLE_LABELS[sample_id], triptych))
        records.append(
            {
                "sample_id": sample_id,
                "label": SAMPLE_LABELS[sample_id],
                "role": "IMPROVEMENT" if sample_id in IMPROVEMENT_IDS else "PROTECTION",
                "source_path": str(source),
                "current_hdde_path": str(baseline),
                "color_core_v2_path": str(target.resolve()),
                "native_comparison_path": str(triptych.resolve()),
                "source_sha256": _sha256(source),
                "current_hdde_sha256": _sha256(baseline),
                "color_core_v2_sha256": _sha256(target),
                "pixel_delta_vs_current_hdde": delta,
                "processing_decision": analysis["processing_decision"],
                "algorithm_execution": analysis["algorithm_execution"],
                "global_execution": analysis["global_execution"],
                "local_execution": analysis["local_execution"],
                "safety_gate_v2": analysis["safety_gate_v2"],
                "runtime_ground_truth_used": analysis["runtime_ground_truth_used"],
                "result": result,
            }
        )

    record_map = {record["sample_id"]: record for record in records}
    reference_rgb = _load_rgb(inputs["01"])
    global_recovery: dict[str, Any] = {}
    for sample_id in ("02", "03"):
        baseline_rgb = _load_rgb(Path(record_map[sample_id]["current_hdde_path"]))
        final_rgb = _load_rgb(Path(record_map[sample_id]["color_core_v2_path"]))
        before_distance = _lab_distance(reference_rgb, baseline_rgb)
        final_distance = _lab_distance(reference_rgb, final_rgb)
        global_recovery[sample_id] = {
            "current_hdde_lab_distance": round(before_distance, 4),
            "color_core_v2_lab_distance": round(final_distance, 4),
            "distance_reduction": round(before_distance - final_distance, 4),
            "pass": bool(final_distance <= before_distance - 0.70),
        }

    unchanged_improvements = all(
        record_map[sample_id]["pixel_delta_vs_current_hdde"]["pixel_equal"]
        and record_map[sample_id]["algorithm_execution"] == EXPECTED_EXECUTIONS[sample_id]
        for sample_id in ("04", "05", "06")
    )
    led_gate = record_map["08"]["safety_gate_v2"]["local"]
    led_metrics = led_gate.get("attempts", [{}])[-1].get("review", {}).get("metrics", {})
    led_pass = bool(
        led_gate.get("status") == "PASS"
        and not led_gate.get("fallback")
        and record_map["08"]["algorithm_execution"] == LOCAL_ROUTE_NAME
        and float(led_metrics.get("screen_mae", 99.0)) <= 0.10
        and float(led_metrics.get("outside_person_mae", 99.0)) <= 0.05
    )
    improvement_gate = bool(
        all(item["pass"] for item in global_recovery.values())
        and unchanged_improvements
        and led_pass
        and all(record_map[sample_id]["algorithm_execution"] == EXPECTED_EXECUTIONS[sample_id] for sample_id in IMPROVEMENT_IDS)
    )
    protection_gate = bool(
        all(record_map[sample_id]["pixel_delta_vs_current_hdde"]["pixel_equal"] for sample_id in PROTECTION_IDS)
        and all(
            record_map[sample_id]["safety_gate_v2"]["global"]["status"] == "NOT_APPLICABLE"
            and record_map[sample_id]["safety_gate_v2"]["local"]["status"] == "NOT_APPLICABLE"
            for sample_id in PROTECTION_IDS
        )
    )
    safety_gate = bool(
        record_map["02"]["safety_gate_v2"]["global"]["status"] == "PASS"
        and record_map["03"]["safety_gate_v2"]["global"]["status"] == "PASS"
        and led_gate.get("status") == "PASS"
        and all(record["safety_gate_v2"]["position"] == "FORMAL_FINAL_COLOR_OUTPUT_CHAIN" for record in records)
    )
    runtime_no_ground_truth = bool(
        runtime_path_contract and all(record["runtime_ground_truth_used"] is False for record in records)
    )

    source_after = {sample_id: _fingerprint(path) for sample_id, path in inputs.items()}
    settings_after = _fingerprint(args.settings.resolve())
    formal_after = _tree_fingerprint(args.formal_output.resolve())
    source_protection = source_before == source_after
    settings_protection = settings_before == settings_after
    formal_output_protection = formal_before == formal_after
    overview_path = output_root / "color_core_v2_15_sample_overview.jpg"
    _overview(native_rows, overview_path)
    gates = {
        "sample_run_15_of_15": len(records) == 15,
        "improvement_regression": improvement_gate,
        "protection_regression": protection_gate,
        "safety_gate_v2_runtime": safety_gate,
        "runtime_ground_truth_unused": runtime_no_ground_truth,
        "runtime_path_contract": runtime_path_contract,
        "source_protection": source_protection,
        "settings_protection": settings_protection,
        "formal_output_protection": formal_output_protection,
        "native_comparisons_15": len(list(native_dir.glob("*.png"))) == 15,
        "overview_exists": overview_path.is_file(),
    }
    status = "ENGINEERING_PASS_HUMAN_REVIEW_PENDING" if all(gates.values()) else "FAIL"
    document = {
        "evaluation": "HDDE V2-B Color Core V2 production integration",
        "status": status,
        "human_final_review": "PENDING",
        "engine_version": COLOR_CORRECTION_ENGINE_VERSION,
        "color_core_v2_version": COLOR_CORE_V2_VERSION,
        "frozen_runtime_routes": {"global": GLOBAL_ROUTE_NAME, "local": LOCAL_ROUTE_NAME},
        "sample_run": "15/15",
        "input_root": str(args.inputs.resolve()),
        "current_hdde_record": str(args.baseline_record.resolve()),
        "output_root": str(output_root),
        "native_results_path": str(native_dir.resolve()),
        "contact_sheet_path": str(overview_path.resolve()),
        "runtime_ground_truth_used": False,
        "global_recovery": global_recovery,
        "led_local_gate_metrics": led_metrics,
        "gates": gates,
        "safety": {
            "settings_before": settings_before,
            "settings_after": settings_after,
            "formal_output_before": formal_before,
            "formal_output_after": formal_after,
        },
        "records": records,
    }
    record_path = output_root / "color_core_v2_evaluation.json"
    record_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": status,
        "sample_run": "15/15",
        "gates": gates,
        "global_recovery": global_recovery,
        "led_local_gate_metrics": led_metrics,
        "native_results_path": str(native_dir.resolve()),
        "contact_sheet_path": str(overview_path.resolve()),
        "evaluation_record_path": str(record_path.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0 if status == "ENGINEERING_PASS_HUMAN_REVIEW_PENDING" else 1


if __name__ == "__main__":
    raise SystemExit(main())
