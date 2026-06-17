from __future__ import annotations

import csv
import json
import shutil
import sys
import time
import traceback
from hashlib import sha256
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.pipeline import process_v046_delivery  # noqa: E402


GOLDEN_ROOT = PROJECT_ROOT / "tests" / "golden_v046"
MANIFEST_PATH = GOLDEN_ROOT / "manifest.json"
PHASE2_ROOT = PROJECT_ROOT / "tests" / "results" / "v046_phase2_round2_golden_regression" / "phase2_round2"
RESULT_ROOT = PROJECT_ROOT / "tests" / "results" / "v046_phase3_round1_decision"

DECISION_SAMPLE_IDS = [
    "smoke_text_poster_cn_small_legacy",
    "smoke_transparent_png_legacy",
    "smoke_original_unprocessed_jpg",
    "smoke_portrait_ready",
    "smoke_architecture_low",
    "synthetic_fine_line_table",
]


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mode_for(sample: dict[str, Any]) -> str:
    return "text_safe" if sample.get("image_type_expected") == "text_poster" else "fidelity"


def output_format_for(path: Path, sample: dict[str, Any]) -> str:
    if bool(sample.get("has_alpha")):
        return "png"
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return "jpg"
    return "png"


def image_alpha_info(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        return {
            "mode": image.mode,
            "width": image.width,
            "height": image.height,
            "alpha_present": image.mode in {"RGBA", "LA"} or "transparency" in image.info,
        }


def strongest_edge_crop_box(path: Path, crop_w: int = 360, crop_h: int = 240) -> tuple[int, int, int, int]:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        crop_w = min(crop_w, width)
        crop_h = min(crop_h, height)
        gray = cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2GRAY)
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad = cv2.magnitude(grad_x, grad_y)
    pooled = cv2.blur(grad, (max(8, crop_w // 6), max(8, crop_h // 6)))
    y, x = np.unravel_index(int(np.argmax(pooled)), pooled.shape)
    left = max(0, min(width - crop_w, int(x - crop_w / 2)))
    top = max(0, min(height - crop_h, int(y - crop_h / 2)))
    return left, top, left + crop_w, top + crop_h


def save_crop(source: Path, target: Path, box: tuple[int, int, int, int]) -> None:
    with Image.open(source) as image:
        image.crop(box).save(target)


def copy_phase2(sample_id: str, out_dir: Path) -> dict[str, Any]:
    result_path = PHASE2_ROOT / sample_id / "result.json"
    diag_path = PHASE2_ROOT / sample_id / "diagnostic.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    diagnostic = json.loads(diag_path.read_text(encoding="utf-8"))
    phase2_source = Path(result["output_path"])
    copied = out_dir / phase2_source.name
    shutil.copy2(phase2_source, copied)
    return {
        "result": result,
        "diagnostic": diagnostic,
        "copied_path": copied,
    }


def summarize_payload(sample: dict[str, Any], input_path: Path, payload: dict[str, Any], elapsed: float) -> dict[str, Any]:
    final_path = Path(payload.get("final_output_path") or "")
    debug_quality = payload.get("debug_quality") or {}
    task_report = payload.get("task_report") or {}
    return {
        "sample_id": sample["sample_id"],
        "expected_type": sample.get("image_type_expected"),
        "image_type": payload.get("image_type"),
        "mode": mode_for(sample),
        "input_path": str(input_path),
        "input_sha256": file_sha256(input_path),
        "output_path": str(final_path),
        "output_exists": final_path.exists(),
        "output_sha256": file_sha256(final_path) if final_path.exists() else "",
        "input_size_bytes": input_path.stat().st_size,
        "output_size_bytes": final_path.stat().st_size if final_path.exists() else None,
        "file_size_ratio": payload.get("file_size_ratio"),
        "quality_1080p_pass": payload.get("quality_1080p_pass"),
        "quality_1080p_level": payload.get("quality_1080p_level"),
        "clarity_gain": debug_quality.get("clarity_gain"),
        "text_clarity_gain": debug_quality.get("text_clarity_gain"),
        "edge_quality_gain": debug_quality.get("edge_quality_gain"),
        "detail_stability_score": debug_quality.get("detail_stability_score"),
        "color_fidelity_score": debug_quality.get("color_fidelity_score"),
        "pseudo_hd_risk": debug_quality.get("pseudo_hd_risk"),
        "over_smoothing_risk": debug_quality.get("over_smoothing_risk"),
        "texture_loss_risk": debug_quality.get("texture_loss_risk"),
        "phase2_material_strength": debug_quality.get("phase2_material_strength"),
        "phase2_skip_reason": debug_quality.get("phase2_skip_reason"),
        "phase3_edge_strength": debug_quality.get("phase3_edge_strength"),
        "phase3_edge_skip_reason": debug_quality.get("phase3_edge_skip_reason"),
        "edge_contrast_risk": debug_quality.get("edge_contrast_risk"),
        "halo_risk": debug_quality.get("halo_risk"),
        "ringing_risk": debug_quality.get("ringing_risk"),
        "alpha_edge_risk": debug_quality.get("alpha_edge_risk"),
        "text_edge_risk": debug_quality.get("text_edge_risk"),
        "warnings": task_report.get("warnings") or payload.get("warnings") or [],
        "elapsed_seconds": round(elapsed, 6),
    }


def run_sample(sample: dict[str, Any]) -> dict[str, Any]:
    sample_id = sample["sample_id"]
    input_path = GOLDEN_ROOT / sample["relative_path"]
    sample_root = RESULT_ROOT / sample_id
    phase2_dir = sample_root / "phase2_frozen"
    phase3_dir = sample_root / "phase3_candidate"
    crop_dir = sample_root / "crops_100"
    for folder in (phase2_dir, phase3_dir, crop_dir):
        folder.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    try:
        phase2 = copy_phase2(sample_id, phase2_dir)
        payload = process_v046_delivery(
            {
                "input_path": input_path,
                "output_root": phase3_dir,
                "mode": mode_for(sample),
                "output_profile": "delivery_1080p",
                "output_format": output_format_for(input_path, sample),
                "debug_keep_intermediate": False,
            }
        )
        elapsed = time.perf_counter() - started
        phase3_record = summarize_payload(sample, input_path, payload, elapsed)
        phase2_result = phase2["result"]
        phase2_debug = (phase2["diagnostic"].get("debug_quality") or {})
        phase3_path = Path(phase3_record["output_path"])
        crop_box = strongest_edge_crop_box(phase3_path)
        phase2_crop = crop_dir / f"{sample_id}__phase2_frozen_crop.png"
        phase3_crop = crop_dir / f"{sample_id}__phase3_candidate_crop.png"
        save_crop(phase2["copied_path"], phase2_crop, crop_box)
        save_crop(phase3_path, phase3_crop, crop_box)
        record = {
            **phase3_record,
            "status": "completed" if phase3_record["output_exists"] else "failed",
            "error": "",
            "phase2_output_path": str(phase2["copied_path"]),
            "phase2_output_size_bytes": phase2_result.get("output_size_bytes"),
            "phase2_quality_1080p_pass": phase2_result.get("quality_1080p_pass_after")
            if "quality_1080p_pass_after" in phase2_result
            else phase2["diagnostic"].get("quality_1080p_pass"),
            "clarity_delta_vs_phase2": round((phase3_record.get("clarity_gain") or 0) - (phase2_debug.get("clarity_gain") or 0), 4),
            "text_delta_vs_phase2": round((phase3_record.get("text_clarity_gain") or 0) - (phase2_debug.get("text_clarity_gain") or 0), 4),
            "edge_delta_vs_phase2": round((phase3_record.get("edge_quality_gain") or 0) - (phase2_debug.get("edge_quality_gain") or 0), 4),
            "detail_delta_vs_phase2": round((phase3_record.get("detail_stability_score") or 0) - (phase2_debug.get("detail_stability_score") or 0), 4),
            "color_delta_vs_phase2": round((phase3_record.get("color_fidelity_score") or 0) - (phase2_debug.get("color_fidelity_score") or 0), 4),
            "output_size_delta_vs_phase2": (phase3_record.get("output_size_bytes") or 0) - (phase2_result.get("output_size_bytes") or 0),
            "crop_box": crop_box,
            "phase2_crop_path": str(phase2_crop),
            "phase3_crop_path": str(phase3_crop),
            "phase2_alpha": image_alpha_info(phase2["copied_path"]),
            "phase3_alpha": image_alpha_info(phase3_path),
        }
        (phase3_dir / "diagnostic.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        record = {
            "sample_id": sample_id,
            "status": "failed",
            "error": traceback.format_exc(),
            "elapsed_seconds": round(time.perf_counter() - started, 6),
        }
    (sample_root / "result.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return record


def write_summary(records: list[dict[str, Any]]) -> None:
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    summary = {
        "task": "V0.4.6 Phase 3 round1 edge and halo decision samples",
        "total": len(records),
        "completed": sum(1 for item in records if item.get("status") == "completed"),
        "failed": sum(1 for item in records if item.get("status") != "completed"),
        "results": records,
    }
    (RESULT_ROOT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = [
        "sample_id",
        "status",
        "image_type",
        "phase3_edge_strength",
        "phase3_edge_skip_reason",
        "quality_1080p_pass",
        "clarity_delta_vs_phase2",
        "text_delta_vs_phase2",
        "edge_delta_vs_phase2",
        "detail_delta_vs_phase2",
        "color_delta_vs_phase2",
        "output_size_delta_vs_phase2",
        "file_size_ratio",
        "pseudo_hd_risk",
        "over_smoothing_risk",
        "texture_loss_risk",
        "phase2_output_path",
        "output_path",
        "error",
    ]
    with (RESULT_ROOT / "summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in records:
            writer.writerow({field: item.get(field, "") for field in fields})
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    samples_by_id = {item["sample_id"]: item for item in manifest["samples"]}
    records = [run_sample(samples_by_id[sample_id]) for sample_id in DECISION_SAMPLE_IDS]
    write_summary(records)
    return 0 if all(item.get("status") == "completed" for item in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
