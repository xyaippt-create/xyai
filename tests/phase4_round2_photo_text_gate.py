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
from PIL import Image, ImageDraw


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.algorithms.low_quality_fidelity import phase4_restoration_masks  # noqa: E402
from engine.pipeline import process_v046_delivery  # noqa: E402


INPUT_DIR = PROJECT_ROOT / "tests" / "fixtures" / "v046_phase4_real_photo_inputs"
GOLDEN_ROOT = PROJECT_ROOT / "tests" / "golden_v046"
RESULT_ROOT = PROJECT_ROOT / "tests" / "results" / "v046_phase4_round2_photo_text_gate"

DIRS = {
    "phase3": RESULT_ROOT / "01_phase3_frozen",
    "phase4": RESULT_ROOT / "02_phase4_round2",
    "comparison": RESULT_ROOT / "03_full_comparison",
    "crops": RESULT_ROOT / "04_crops_100pct",
    "masks": RESULT_ROOT / "05_masks",
    "metrics": RESULT_ROOT / "06_metrics",
}

REAL_SAMPLES = [
    {
        "sample_id": "real_activity_outdoor_01",
        "filename": "Image_1781400827720_384.jpg",
        "content_type": "outdoor activity photo with building background",
        "degradation": "jpeg_compression|dirty_shadow|incidental_text",
    },
    {
        "sample_id": "real_stage_activity_02",
        "filename": "Image_1781401065544_514.jpg",
        "content_type": "stage activity photo",
        "degradation": "jpeg_compression|low_light|LED_text_background",
    },
    {
        "sample_id": "real_meeting_room_03",
        "filename": "Image_1781401115713_986.jpg",
        "content_type": "indoor meeting activity photo",
        "degradation": "jpeg_compression|low_contrast|meeting_text",
    },
    {
        "sample_id": "real_group_meeting_04",
        "filename": "Image_1781401182218_413.jpg",
        "content_type": "group meeting photo with projection screen",
        "degradation": "soft_focus|low_contrast|projection_text",
    },
]

PROTECTION_SAMPLES = [
    {
        "sample_id": "protect_cn_small_text",
        "relative_path": "smoke/text_poster_cn_small_legacy.png",
        "mode": "text_safe",
        "output_format": "png",
        "content_type": "Chinese small text protection",
        "degradation": "text_protection_control",
    },
    {
        "sample_id": "protect_brand_kv_proxy",
        "relative_path": "synthetic/brand_color_bars.png",
        "mode": "fidelity",
        "output_format": "png",
        "content_type": "high quality commercial KV protection proxy",
        "degradation": "brand_color_protection_control",
    },
]


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_bgr(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"failed to decode {path}")
    return image


def color_metrics(path_a: Path, path_b: Path) -> dict[str, Any]:
    image_a = load_bgr(path_a)
    image_b = load_bgr(path_b)
    if image_a.shape[:2] != image_b.shape[:2]:
        image_b = cv2.resize(image_b, (image_a.shape[1], image_a.shape[0]), interpolation=cv2.INTER_AREA)
    lab_a = cv2.cvtColor(image_a, cv2.COLOR_BGR2LAB).astype("float32")
    lab_b = cv2.cvtColor(image_b, cv2.COLOR_BGR2LAB).astype("float32")
    delta = np.linalg.norm(lab_a - lab_b, axis=2)
    hsv_a = cv2.cvtColor(image_a, cv2.COLOR_BGR2HSV).astype("float32")
    hsv_b = cv2.cvtColor(image_b, cv2.COLOR_BGR2HSV).astype("float32")
    sat_a = hsv_a[:, :, 1] / 255.0
    sat_b = hsv_b[:, :, 1] / 255.0
    skin = (
        (hsv_a[:, :, 0] >= 0)
        & (hsv_a[:, :, 0] <= 25)
        & (sat_a >= 0.12)
        & (sat_a <= 0.68)
        & (hsv_a[:, :, 2] >= 45)
    )
    return {
        "mean_delta_e": round(float(np.mean(delta)), 6),
        "p95_delta_e": round(float(np.percentile(delta, 95)), 6),
        "saturation_delta": round(float(np.mean(sat_b) - np.mean(sat_a)), 6),
        "high_saturation_pixel_ratio_delta": round(float(np.mean(sat_b > 0.68) - np.mean(sat_a > 0.68)), 6),
        "skin_region_delta_e": round(float(np.mean(delta[skin])), 6) if np.any(skin) else None,
    }


@contextmanager
def phase4_disabled():
    import backend.v036_output_core as core

    original_policy = core.phase4_low_quality_policy
    original_restore = core.phase4_low_quality_restore

    def inactive_policy(*args, **kwargs):
        before = kwargs.get("before_probes") or {}
        text_stats = kwargs.get("text_stats") or {}
        return {
            "phase4_photo_eligible": False,
            "phase4_low_quality_active": False,
            "phase4_text_mask_ratio": float(text_stats.get("text_mask_ratio") or 0.0),
            "phase4_text_protection_mode": "global",
            "phase4_nontext_restoration_active": False,
            "phase4_global_skip_reason": "phase3_frozen_baseline",
            "phase4_degradation_profile": "disabled_for_phase3_baseline",
            "phase4_restoration_strength": 0.0,
            "phase4_skip_reason": "phase3_frozen_baseline",
            "photographicity_score": 0.0,
            "face_or_person_detected": False,
            "local_texture_score": 0.0,
            "text_region_count": int(text_stats.get("text_region_count") or 0),
            "largest_text_region_ratio": float(text_stats.get("largest_text_region_ratio") or 0.0),
            "text_region_distribution": text_stats.get("text_region_distribution") or {},
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
    debug = payload.get("debug_quality") or {}
    final = Path(payload.get("final_output_path") or "")
    return {
        "sample_id": sample["sample_id"],
        "input_path": str(input_path),
        "output_path": str(final),
        "output_exists": final.exists(),
        "output_size_bytes": final.stat().st_size if final.exists() else None,
        "quality_1080p_pass": payload.get("quality_1080p_pass"),
        "image_type": payload.get("image_type"),
        "phase4_photo_eligible": debug.get("phase4_photo_eligible"),
        "phase4_low_quality_active": debug.get("phase4_low_quality_active"),
        "phase4_text_mask_ratio": debug.get("phase4_text_mask_ratio"),
        "phase4_text_protection_mode": debug.get("phase4_text_protection_mode"),
        "phase4_nontext_restoration_active": debug.get("phase4_nontext_restoration_active"),
        "phase4_global_skip_reason": debug.get("phase4_global_skip_reason"),
        "phase4_degradation_profile": debug.get("phase4_degradation_profile"),
        "phase4_restoration_strength": debug.get("phase4_restoration_strength"),
        "phase4_skip_reason": debug.get("phase4_skip_reason"),
        "photographicity_score": debug.get("photographicity_score"),
        "face_or_person_detected": debug.get("face_or_person_detected"),
        "local_texture_score": debug.get("local_texture_score"),
        "text_region_count": debug.get("text_region_count"),
        "largest_text_region_ratio": debug.get("largest_text_region_ratio"),
        "text_region_distribution": debug.get("text_region_distribution"),
        "compression_risk_before": debug.get("compression_risk_before"),
        "compression_risk_after": debug.get("compression_risk_after"),
        "shadow_dirt_risk_before": debug.get("shadow_dirt_risk_before"),
        "shadow_dirt_risk_after": debug.get("shadow_dirt_risk_after"),
        "local_contrast_before": debug.get("local_contrast_before"),
        "local_contrast_after": debug.get("local_contrast_after"),
        "clarity_gain": debug.get("clarity_gain"),
        "text_clarity_gain": debug.get("text_clarity_gain"),
        "edge_quality_gain": debug.get("edge_quality_gain"),
        "detail_stability_score": debug.get("detail_stability_score"),
        "processing_time_ms": int(round(elapsed * 1000)),
        "warnings": payload.get("warnings") or (payload.get("task_report") or {}).get("warnings") or [],
    }


def run_pipeline(sample: dict[str, Any], input_path: Path, output_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    payload = process_v046_delivery(
        {
            "input_path": input_path,
            "output_root": output_root,
            "mode": sample.get("mode", "fidelity"),
            "output_profile": "delivery_1080p",
            "output_format": sample.get("output_format", "jpg" if input_path.suffix.lower() in {".jpg", ".jpeg"} else "png"),
            "debug_keep_intermediate": False,
        }
    )
    return payload, summarize_payload(sample, input_path, payload, time.perf_counter() - started)


def crop_boxes(path: Path, real: bool) -> list[dict[str, Any]]:
    image = load_bgr(path)
    height, width = image.shape[:2]
    cw = min(420, max(180, width // 4))
    ch = min(300, max(150, height // 4))
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype("float32")
    lap = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
    dark = np.clip((105 - gray) / 105, 0, 1)
    grad = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))
    maps = [
        ("face_or_texture", cv2.blur(lap, (max(8, cw // 5), max(8, ch // 5)))),
        ("shadow_or_compression", cv2.blur(dark, (max(8, cw // 5), max(8, ch // 5)))),
        ("background_text_edge", cv2.blur(grad, (max(8, cw // 5), max(8, ch // 5)))),
        ("center_subject", None),
    ]
    boxes: list[dict[str, Any]] = []

    def add(label: str, x: int, y: int) -> None:
        left = max(0, min(width - cw, int(x - cw / 2)))
        top = max(0, min(height - ch, int(y - ch / 2)))
        box = [left, top, left + cw, top + ch]
        if box not in [item["box"] for item in boxes]:
            boxes.append({"label": label, "box": box})

    for label, score in maps:
        if score is None:
            add(label, width // 2, height // 2)
        else:
            y, x = np.unravel_index(int(np.argmax(score)), score.shape)
            add(label, int(x), int(y))
    return boxes[:4 if real else 3]


def save_crop(source: Path, target: Path, box: list[int]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.crop(tuple(box)).save(target)


def save_mask_previews(source: Path, target_dir: Path) -> dict[str, str]:
    image = load_bgr(source)
    masks = phase4_restoration_masks(image, {"phase4_text_protection_mode": "local"})
    target_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for key, mask in masks.items():
        out = target_dir / f"{key}_preview.png"
        preview = np.clip(mask * 255.0, 0, 255).astype("uint8")
        cv2.imwrite(str(out), preview)
        outputs[key] = str(out)
    protected_overlay = image.copy()
    red = np.zeros_like(protected_overlay)
    red[:, :, 2] = 255
    alpha = masks["protected_mask"][:, :, None] * 0.45
    overlay = protected_overlay.astype("float32") * (1.0 - alpha) + red.astype("float32") * alpha
    overlay_path = target_dir / "protected_region_preview.png"
    cv2.imwrite(str(overlay_path), np.clip(overlay, 0, 255).astype("uint8"))
    outputs["protected_region_preview"] = str(overlay_path)
    return outputs


def make_comparison(paths: list[Path], labels: list[str], output: Path) -> None:
    images = [Image.open(path).convert("RGB") for path in paths]
    title_h = 42
    max_w = 560
    resized = []
    for image in images:
        scale = min(max_w / image.width, 1.0)
        resized.append(image.resize((int(image.width * scale), int(image.height * scale)), Image.LANCZOS))
    width = sum(image.width for image in resized)
    height = max(image.height for image in resized) + title_h
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    x = 0
    for image, label in zip(resized, labels):
        draw.text((x + 8, 12), label, fill=(0, 0, 0))
        canvas.paste(image, (x, title_h))
        x += image.width
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def run_sample(sample: dict[str, Any]) -> dict[str, Any]:
    sid = sample["sample_id"]
    input_path = Path(sample["input_path"])
    phase3_dir = DIRS["phase3"] / sid
    phase4_dir = DIRS["phase4"] / sid
    crop_dir = DIRS["crops"] / sid
    metric_dir = DIRS["metrics"] / sid
    for folder in (phase3_dir, phase4_dir, crop_dir, metric_dir):
        folder.mkdir(parents=True, exist_ok=True)
    with phase4_disabled():
        phase3_payload, phase3 = run_pipeline(sample, input_path, phase3_dir)
    phase4_payload, phase4 = run_pipeline(sample, input_path, phase4_dir)
    phase3_path = Path(phase3["output_path"])
    phase4_path = Path(phase4["output_path"])
    color = color_metrics(phase3_path, phase4_path)
    boxes = crop_boxes(phase4_path, sample["kind"] == "real_low_quality_photo")
    crop_records = []
    for index, item in enumerate(boxes, 1):
        phase3_crop = crop_dir / f"{sid}_{index:02d}_{item['label']}_phase3.png"
        phase4_crop = crop_dir / f"{sid}_{index:02d}_{item['label']}_phase4.png"
        save_crop(phase3_path, phase3_crop, item["box"])
        save_crop(phase4_path, phase4_crop, item["box"])
        crop_records.append({"label": item["label"], "box": item["box"], "phase3_crop": str(phase3_crop), "phase4_crop": str(phase4_crop)})
    comparison_path = DIRS["comparison"] / f"{sid}_comparison.jpg"
    make_comparison([input_path, phase3_path, phase4_path], ["original", "Phase 3 frozen", "Phase 4 Round 2"], comparison_path)
    masks = save_mask_previews(phase4_path, DIRS["masks"] / sid) if sample["kind"] == "real_low_quality_photo" else {}
    record = {
        **sample,
        "status": "completed",
        "input_sha256": file_sha256(input_path),
        "phase3_output_path": str(phase3_path),
        "phase4_output_path": str(phase4_path),
        "phase3_quality_1080p_pass": phase3["quality_1080p_pass"],
        "phase4_quality_1080p_pass": phase4["quality_1080p_pass"],
        "phase3_output_size_bytes": phase3["output_size_bytes"],
        "phase4_output_size_bytes": phase4["output_size_bytes"],
        "output_size_delta": (phase4["output_size_bytes"] or 0) - (phase3["output_size_bytes"] or 0),
        "phase4_photo_eligible": phase4["phase4_photo_eligible"],
        "phase4_low_quality_active": phase4["phase4_low_quality_active"],
        "phase4_text_mask_ratio": phase4["phase4_text_mask_ratio"],
        "phase4_text_protection_mode": phase4["phase4_text_protection_mode"],
        "phase4_nontext_restoration_active": phase4["phase4_nontext_restoration_active"],
        "phase4_global_skip_reason": phase4["phase4_global_skip_reason"],
        "phase4_degradation_profile": phase4["phase4_degradation_profile"],
        "phase4_restoration_strength": phase4["phase4_restoration_strength"],
        "phase4_skip_reason": phase4["phase4_skip_reason"],
        "photographicity_score": phase4["photographicity_score"],
        "face_or_person_detected": phase4["face_or_person_detected"],
        "local_texture_score": phase4["local_texture_score"],
        "text_region_count": phase4["text_region_count"],
        "largest_text_region_ratio": phase4["largest_text_region_ratio"],
        "text_region_distribution": phase4["text_region_distribution"],
        "compression_risk_before": phase4["compression_risk_before"],
        "compression_risk_after": phase4["compression_risk_after"],
        "shadow_dirt_risk_before": phase4["shadow_dirt_risk_before"],
        "shadow_dirt_risk_after": phase4["shadow_dirt_risk_after"],
        "local_contrast_before": phase4["local_contrast_before"],
        "local_contrast_after": phase4["local_contrast_after"],
        "clarity_delta": round((phase4.get("clarity_gain") or 0) - (phase3.get("clarity_gain") or 0), 4),
        "text_delta": round((phase4.get("text_clarity_gain") or 0) - (phase3.get("text_clarity_gain") or 0), 4),
        "edge_delta": round((phase4.get("edge_quality_gain") or 0) - (phase3.get("edge_quality_gain") or 0), 4),
        "detail_delta": round((phase4.get("detail_stability_score") or 0) - (phase3.get("detail_stability_score") or 0), 4),
        **color,
        "processing_time_ms": phase4["processing_time_ms"],
        "comparison_path": str(comparison_path),
        "crops": crop_records,
        "mask_previews": masks,
        "phase4_warnings": phase4.get("warnings") or [],
    }
    (metric_dir / "phase3_payload.json").write_text(json.dumps(phase3_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (metric_dir / "phase4_payload.json").write_text(json.dumps(phase4_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (metric_dir / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return record


def main() -> int:
    for folder in DIRS.values():
        folder.mkdir(parents=True, exist_ok=True)
    samples = []
    for item in REAL_SAMPLES:
        sample = dict(item)
        sample["kind"] = "real_low_quality_photo"
        sample["input_path"] = str(INPUT_DIR / item["filename"])
        sample["mode"] = "fidelity"
        sample["output_format"] = "jpg"
        samples.append(sample)
    for item in PROTECTION_SAMPLES:
        sample = dict(item)
        sample["kind"] = "protection_control"
        sample["input_path"] = str(GOLDEN_ROOT / item["relative_path"])
        samples.append(sample)

    records = []
    for sample in samples:
        try:
            records.append(run_sample(sample))
        except Exception:  # noqa: BLE001
            records.append({**sample, "status": "failed", "error": traceback.format_exc()})

    manifest = {
        "task": "V0.4.6 Phase 4 Round 2 local photo text gate",
        "result_root": str(RESULT_ROOT),
        "completed": sum(1 for item in records if item.get("status") == "completed"),
        "total": len(records),
        "sample_gaps": {
            "real_product_photo": "missing",
            "standalone_architecture_photo": "missing",
        },
        "results": records,
    }
    (RESULT_ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    with (RESULT_ROOT / "summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = [
            "sample_id",
            "status",
            "phase4_photo_eligible",
            "phase4_low_quality_active",
            "phase4_text_mask_ratio",
            "phase4_text_protection_mode",
            "phase4_restoration_strength",
            "phase4_skip_reason",
            "compression_risk_before",
            "compression_risk_after",
            "shadow_dirt_risk_before",
            "shadow_dirt_risk_after",
            "local_contrast_before",
            "local_contrast_after",
            "clarity_delta",
            "detail_delta",
            "mean_delta_e",
            "p95_delta_e",
            "saturation_delta",
            "skin_region_delta_e",
            "output_size_delta",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in records:
            writer.writerow({field: item.get(field, "") for field in fields})

    lines = [
        "# V0.4.6 Phase 4 Round 2 Photo Text Gate",
        "",
        f"- completed: {manifest['completed']}/{manifest['total']}",
        "- note: originals and outputs are local test assets and are not intended for git commit.",
        "",
        "## Results",
    ]
    for item in records:
        lines.append(
            f"- {item['sample_id']}: active={item.get('phase4_low_quality_active')}, "
            f"text_mode={item.get('phase4_text_protection_mode')}, "
            f"text_mask={item.get('phase4_text_mask_ratio')}, "
            f"strength={item.get('phase4_restoration_strength')}, "
            f"skip={item.get('phase4_skip_reason')}, "
            f"clarity_delta={item.get('clarity_delta')}, detail_delta={item.get('detail_delta')}, "
            f"mean_delta_e={item.get('mean_delta_e')}, p95_delta_e={item.get('p95_delta_e')}"
        )
    lines.extend(
        [
            "",
            "## Sample Gaps",
            "- real product photo: missing",
            "- standalone architecture photo: missing",
        ]
    )
    (RESULT_ROOT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return 0 if manifest["completed"] == manifest["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
