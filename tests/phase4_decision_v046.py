from __future__ import annotations

import csv
import json
import sys
import time
import traceback
from contextlib import contextmanager
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
RESULT_ROOT = PROJECT_ROOT / "tests" / "results" / "v046_phase4_round1_decision"

DECISION_SAMPLE_IDS = [
    "smoke_original_unprocessed_jpg",
    "smoke_portrait_ready",
    "smoke_architecture_low",
    "core_product_low_png",
    "smoke_text_poster_cn_small_legacy",
    "synthetic_brand_color_bars",
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


def strongest_texture_crop_box(path: Path, crop_w: int = 360, crop_h: int = 240) -> tuple[int, int, int, int]:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        crop_w = min(crop_w, width)
        crop_h = min(crop_h, height)
        gray = cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2GRAY).astype("float32")
    local = cv2.Laplacian(gray, cv2.CV_32F)
    score = cv2.blur(np.abs(local), (max(8, crop_w // 6), max(8, crop_h // 6)))
    y, x = np.unravel_index(int(np.argmax(score)), score.shape)
    left = max(0, min(width - crop_w, int(x - crop_w / 2)))
    top = max(0, min(height - crop_h, int(y - crop_h / 2)))
    return left, top, left + crop_w, top + crop_h


def save_crop(source: Path, target: Path, box: tuple[int, int, int, int]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.crop(box).save(target)


def mean_lab_delta(path_a: Path, path_b: Path) -> float:
    image_a = cv2.imdecode(np.fromfile(str(path_a), dtype=np.uint8), cv2.IMREAD_COLOR)
    image_b = cv2.imdecode(np.fromfile(str(path_b), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image_a is None or image_b is None:
        return 0.0
    if image_a.shape[:2] != image_b.shape[:2]:
        image_b = cv2.resize(image_b, (image_a.shape[1], image_a.shape[0]), interpolation=cv2.INTER_AREA)
    lab_a = cv2.cvtColor(image_a, cv2.COLOR_BGR2LAB).astype("float32")
    lab_b = cv2.cvtColor(image_b, cv2.COLOR_BGR2LAB).astype("float32")
    return round(float(np.mean(np.linalg.norm(lab_a - lab_b, axis=2))), 6)


@contextmanager
def phase4_disabled():
    import backend.v036_output_core as core

    original_policy = core.phase4_low_quality_policy
    original_restore = core.phase4_low_quality_restore

    def inactive_policy(*args, **kwargs):
        before = kwargs.get("before_probes") or {}
        return {
            "phase4_low_quality_active": False,
            "phase4_degradation_profile": "disabled_for_phase3_baseline",
            "phase4_restoration_strength": 0.0,
            "phase4_skip_reason": "phase3_frozen_baseline",
            "compression_risk_before": round(float(before.get("compression_risk") or 0.0), 6),
            "shadow_dirt_risk_before": round(float(before.get("shadow_dirt_risk") or 0.0), 6),
            "local_contrast_before": round(float(before.get("local_contrast") or 0.0), 6),
        }

    def identity_restore(reference, image, policy):
        return image

    core.phase4_low_quality_policy = inactive_policy
    core.phase4_low_quality_restore = identity_restore
    try:
        yield
    finally:
        core.phase4_low_quality_policy = original_policy
        core.phase4_low_quality_restore = original_restore


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
        "phase4_low_quality_active": debug_quality.get("phase4_low_quality_active"),
        "phase4_degradation_profile": debug_quality.get("phase4_degradation_profile"),
        "phase4_restoration_strength": debug_quality.get("phase4_restoration_strength"),
        "phase4_skip_reason": debug_quality.get("phase4_skip_reason"),
        "compression_risk_before": debug_quality.get("compression_risk_before"),
        "compression_risk_after": debug_quality.get("compression_risk_after"),
        "shadow_dirt_risk_before": debug_quality.get("shadow_dirt_risk_before"),
        "shadow_dirt_risk_after": debug_quality.get("shadow_dirt_risk_after"),
        "local_contrast_before": debug_quality.get("local_contrast_before"),
        "local_contrast_after": debug_quality.get("local_contrast_after"),
        "has_alpha": debug_quality.get("has_alpha"),
        "alpha_used": debug_quality.get("alpha_used"),
        "warnings": task_report.get("warnings") or payload.get("warnings") or [],
        "elapsed_seconds": round(elapsed, 6),
    }


def run_pipeline(sample: dict[str, Any], input_path: Path, output_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    payload = process_v046_delivery(
        {
            "input_path": input_path,
            "output_root": output_root,
            "mode": mode_for(sample),
            "output_profile": "delivery_1080p",
            "output_format": output_format_for(input_path, sample),
            "debug_keep_intermediate": False,
        }
    )
    return payload, summarize_payload(sample, input_path, payload, time.perf_counter() - started)


def run_sample(sample: dict[str, Any]) -> dict[str, Any]:
    sample_id = sample["sample_id"]
    input_path = GOLDEN_ROOT / sample["relative_path"]
    sample_root = RESULT_ROOT / sample_id
    phase3_dir = sample_root / "01_phase3_frozen"
    phase4_dir = sample_root / "02_phase4_candidate"
    crop_dir = sample_root / "03_crops_100pct"
    for folder in (phase3_dir, phase4_dir, crop_dir):
        folder.mkdir(parents=True, exist_ok=True)
    try:
        with phase4_disabled():
            phase3_payload, phase3_record = run_pipeline(sample, input_path, phase3_dir)
        phase4_payload, phase4_record = run_pipeline(sample, input_path, phase4_dir)
        phase3_path = Path(phase3_record["output_path"])
        phase4_path = Path(phase4_record["output_path"])
        crop_box = strongest_texture_crop_box(phase4_path)
        phase3_crop = crop_dir / f"{sample_id}__phase3_frozen_crop.png"
        phase4_crop = crop_dir / f"{sample_id}__phase4_candidate_crop.png"
        save_crop(phase3_path, phase3_crop, crop_box)
        save_crop(phase4_path, phase4_crop, crop_box)
        record = {
            **phase4_record,
            "status": "completed" if phase4_record["output_exists"] and phase3_record["output_exists"] else "failed",
            "error": "",
            "phase3_output_path": str(phase3_path),
            "phase3_output_size_bytes": phase3_record.get("output_size_bytes"),
            "phase3_quality_1080p_pass": phase3_record.get("quality_1080p_pass"),
            "clarity_delta_vs_phase3": round((phase4_record.get("clarity_gain") or 0) - (phase3_record.get("clarity_gain") or 0), 4),
            "text_delta_vs_phase3": round((phase4_record.get("text_clarity_gain") or 0) - (phase3_record.get("text_clarity_gain") or 0), 4),
            "edge_delta_vs_phase3": round((phase4_record.get("edge_quality_gain") or 0) - (phase3_record.get("edge_quality_gain") or 0), 4),
            "detail_delta_vs_phase3": round((phase4_record.get("detail_stability_score") or 0) - (phase3_record.get("detail_stability_score") or 0), 4),
            "color_delta_vs_phase3": round((phase4_record.get("color_fidelity_score") or 0) - (phase3_record.get("color_fidelity_score") or 0), 4),
            "mean_lab_delta_vs_phase3": mean_lab_delta(phase3_path, phase4_path),
            "output_size_delta_vs_phase3": (phase4_record.get("output_size_bytes") or 0) - (phase3_record.get("output_size_bytes") or 0),
            "crop_box": crop_box,
            "phase3_crop_path": str(phase3_crop),
            "phase4_crop_path": str(phase4_crop),
            "phase3_alpha": image_alpha_info(phase3_path),
            "phase4_alpha": image_alpha_info(phase4_path),
        }
        (phase3_dir / "diagnostic.json").write_text(
            json.dumps(phase3_payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (phase4_dir / "diagnostic.json").write_text(
            json.dumps(phase4_payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        record = {
            "sample_id": sample_id,
            "status": "failed",
            "error": traceback.format_exc(),
        }
    (sample_root / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return record


def write_summary(records: list[dict[str, Any]]) -> None:
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    summary = {
        "task": "V0.4.6 Phase 4 round1 low-quality fidelity decision samples",
        "total": len(records),
        "completed": sum(1 for item in records if item.get("status") == "completed"),
        "failed": sum(1 for item in records if item.get("status") != "completed"),
        "sample_gap": {
            "real_low_quality_portrait_or_activity_photo": "partial",
            "notes": "golden set has portrait_ready as the closest portrait proxy; no separate real event/activity photo was found",
        },
        "results": records,
    }
    (RESULT_ROOT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = [
        "sample_id",
        "status",
        "image_type",
        "phase4_low_quality_active",
        "phase4_degradation_profile",
        "phase4_restoration_strength",
        "phase4_skip_reason",
        "compression_risk_before",
        "compression_risk_after",
        "shadow_dirt_risk_before",
        "shadow_dirt_risk_after",
        "local_contrast_before",
        "local_contrast_after",
        "quality_1080p_pass",
        "clarity_delta_vs_phase3",
        "text_delta_vs_phase3",
        "edge_delta_vs_phase3",
        "detail_delta_vs_phase3",
        "color_delta_vs_phase3",
        "mean_lab_delta_vs_phase3",
        "output_size_delta_vs_phase3",
        "file_size_ratio",
        "phase3_output_path",
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
