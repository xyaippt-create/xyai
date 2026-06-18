from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.algorithms.color_stability import phase5_color_metrics  # noqa: E402
from engine.pipeline import process_v046_delivery  # noqa: E402


GOLDEN_ROOT = PROJECT_ROOT / "tests" / "golden_v046"
GOLDEN_MANIFEST = GOLDEN_ROOT / "manifest.json"
TARGET_ROOT = PROJECT_ROOT / "tests" / "results" / "v046_phase5_targeted"
GOLDEN_RESULT_ROOT = PROJECT_ROOT / "tests" / "results" / "v046_phase5_golden_regression"


def _ensure_synthetic_cast_photo() -> Path:
    path = TARGET_ROOT / "00_generated_inputs" / "synthetic_neutral_yellow_cast_portrait.png"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    height, width = 420, 640
    y = np.linspace(0.0, 1.0, height, dtype="float32")[:, None]
    x = np.linspace(0.0, 1.0, width, dtype="float32")[None, :]
    base = np.zeros((height, width, 3), dtype="float32")
    base[:, :, 0] = 82 + 32 * x + 10 * y
    base[:, :, 1] = 84 + 28 * y + 8 * x
    base[:, :, 2] = 88 + 24 * (1.0 - x) + 6 * y
    rng = np.random.default_rng(46)
    noise = rng.normal(0, 5.0, base.shape).astype("float32")
    image = np.clip(base + noise, 0, 255).astype("uint8")
    cv2.ellipse(image, (320, 185), (82, 106), 0, 0, 360, (122, 146, 176), -1)
    cv2.ellipse(image, (288, 174), (10, 7), 0, 0, 360, (52, 56, 63), -1)
    cv2.ellipse(image, (350, 174), (10, 7), 0, 0, 360, (52, 56, 63), -1)
    cv2.ellipse(image, (320, 270), (145, 70), 0, 0, 360, (84, 91, 108), -1)
    image = cv2.GaussianBlur(image, (3, 3), 0)
    cast = np.zeros_like(image, dtype="float32")
    cast[:, :, 1] = 13.0
    cast[:, :, 2] = 20.0
    image = np.clip(image.astype("float32") + cast, 0, 255).astype("uint8")
    Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB)).save(path)
    return path


TARGET_SAMPLES = [
    {
        "sample_id": "huawei_enterprise",
        "path": PROJECT_ROOT / "tests" / "fixtures" / "v046_phase3_freeze_inputs" / "ChatGPT Image 2026年5月24日 21_05_18 (2).png",
        "mode": "fidelity",
        "format": "png",
        "correction_expected": False,
    },
    {
        "sample_id": "real_low_light_person",
        "path": PROJECT_ROOT / "tests" / "fixtures" / "v046_phase4_real_photo_inputs" / "Image_1781400827720_384.jpg",
        "mode": "fidelity",
        "format": "jpg",
        "correction_expected": True,
    },
    {
        "sample_id": "real_product_lowquality",
        "path": PROJECT_ROOT / "tests" / "fixtures" / "v046_phase4_real_photo_inputs" / "05_real_product_lowquality.jpg",
        "mode": "fidelity",
        "format": "jpg",
        "correction_expected": False,
    },
    {
        "sample_id": "real_architecture_lowquality",
        "path": PROJECT_ROOT / "tests" / "fixtures" / "v046_phase4_real_photo_inputs" / "06_real_architecture_lowquality.jpg",
        "mode": "fidelity",
        "format": "jpg",
        "correction_expected": True,
    },
    {
        "sample_id": "synthetic_brand_color_bars",
        "path": GOLDEN_ROOT / "synthetic" / "brand_color_bars.png",
        "mode": "fidelity",
        "format": "png",
        "correction_expected": False,
    },
    {
        "sample_id": "synthetic_gradient_band",
        "path": GOLDEN_ROOT / "synthetic" / "gradient_band.png",
        "mode": "fidelity",
        "format": "png",
        "correction_expected": False,
    },
    {
        "sample_id": "smoke_text_poster_cn_small_legacy",
        "path": GOLDEN_ROOT / "smoke" / "text_poster_cn_small_legacy.png",
        "mode": "text_safe",
        "format": "png",
        "correction_expected": False,
    },
    {
        "sample_id": "synthetic_highlight_clip",
        "path": GOLDEN_ROOT / "synthetic" / "highlight_clip.png",
        "mode": "fidelity",
        "format": "png",
        "correction_expected": False,
    },
    {
        "sample_id": "synthetic_neutral_yellow_cast_portrait",
        "path": _ensure_synthetic_cast_photo(),
        "mode": "fidelity",
        "format": "png",
        "correction_expected": True,
    },
]


def _read_bgr(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"decode failed: {path}")
    return image


def _format_for(path: Path, sample: dict[str, Any]) -> str:
    if sample.get("format"):
        return str(sample["format"])
    return "jpg" if path.suffix.lower() in {".jpg", ".jpeg"} else "png"


def _run(sample: dict[str, Any], output_dir: Path, *, stability: bool, correction: bool) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    payload = process_v046_delivery(
        {
            "input_path": sample["path"],
            "output_root": output_dir,
            "mode": sample.get("mode") or "fidelity",
            "output_profile": "delivery_1080p",
            "output_format": _format_for(sample["path"], sample),
            "debug_keep_intermediate": False,
            "color_stability_enabled": stability,
            "color_correction_enabled": correction,
        }
    )
    return payload, round((time.perf_counter() - started) * 1000.0, 3)


def _copy_original(path: Path, target_dir: Path, sample_id: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{sample_id}{path.suffix.lower()}"
    shutil.copy2(path, target)
    return target


def _comparison(paths: list[Path], target: Path, labels: list[str]) -> None:
    images = [Image.open(path).convert("RGB") for path in paths]
    thumb_w = max(image.width for image in images)
    thumb_h = max(image.height for image in images)
    canvas = Image.new("RGB", (thumb_w * len(images), thumb_h + 42), "white")
    draw = ImageDraw.Draw(canvas)
    for index, image in enumerate(images):
        scale = min(thumb_w / image.width, thumb_h / image.height)
        resized = image.resize((int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS)
        x = index * thumb_w + (thumb_w - resized.width) // 2
        y = 42 + (thumb_h - resized.height) // 2
        canvas.paste(resized, (x, y))
        draw.text((index * thumb_w + 12, 12), labels[index], fill=(0, 0, 0))
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target)


def _record(sample: dict[str, Any], phase4: dict[str, Any], phase5: dict[str, Any], correction: dict[str, Any], elapsed: dict[str, float]) -> dict[str, Any]:
    p4_path = Path(phase4["final_output_path"])
    p5_path = Path(phase5["final_output_path"])
    correction_path = Path(correction["final_output_path"]) if correction else None
    original_resized = cv2.resize(_read_bgr(sample["path"]), (_read_bgr(p5_path).shape[1], _read_bgr(p5_path).shape[0]), interpolation=cv2.INTER_CUBIC)
    p4_image = _read_bgr(p4_path)
    p5_image = _read_bgr(p5_path)
    metrics_p4 = phase5_color_metrics(original_resized, p4_image)
    metrics_p5 = phase5_color_metrics(original_resized, p5_image)
    correction_metrics = phase5_color_metrics(original_resized, _read_bgr(correction_path)) if correction_path else {}
    debug5 = phase5.get("debug_quality") or {}
    debug_c = correction.get("debug_quality") if correction else {}
    return {
        "sample_id": sample["sample_id"],
        "input_path": str(sample["path"]),
        "phase4_path": str(p4_path),
        "phase5_default_path": str(p5_path),
        "phase5_correction_path": str(correction_path) if correction_path else "",
        "phase4_quality_1080p_pass": phase4.get("quality_1080p_pass"),
        "phase5_quality_1080p_pass": phase5.get("quality_1080p_pass"),
        "phase4_metrics": metrics_p4,
        "phase5_default_metrics": metrics_p5,
        "phase5_correction_metrics": correction_metrics,
        "phase5_color_lock_mode": debug5.get("phase5_color_lock_mode"),
        "phase5_color_drift_detected": debug5.get("phase5_color_drift_detected"),
        "phase5_color_fallback_triggered": debug5.get("phase5_color_fallback_triggered"),
        "phase5_color_fallback_reason": debug5.get("phase5_color_fallback_reason"),
        "phase5_correction_enabled": bool((debug_c or {}).get("phase5_color_correction_enabled")),
        "phase5_correction_active": bool((debug_c or {}).get("phase5_correction_active")),
        "phase5_correction_skip_reason": (debug_c or {}).get("phase5_correction_skip_reason", ""),
        "phase5_cast_direction": (debug_c or {}).get("phase5_cast_direction", ""),
        "phase5_cast_strength": (debug_c or {}).get("phase5_cast_strength", 0.0),
        "mean_delta_e_change": round(metrics_p5["mean_delta_e"] - metrics_p4["mean_delta_e"], 6),
        "p95_delta_e_change": round(metrics_p5["p95_delta_e"] - metrics_p4["p95_delta_e"], 6),
        "saturation_delta_change": round(metrics_p5["saturation_delta"] - metrics_p4["saturation_delta"], 6),
        "output_size_delta": Path(p5_path).stat().st_size - Path(p4_path).stat().st_size,
        "processing_time_ms": elapsed,
    }


def run_targeted() -> dict[str, Any]:
    for sub in ("00_original", "01_phase4_frozen", "02_phase5_default", "03_phase5_correction", "04_comparison", "05_metrics"):
        (TARGET_ROOT / sub).mkdir(parents=True, exist_ok=True)
    results = []
    for sample in TARGET_SAMPLES:
        if not sample["path"].exists():
            raise RuntimeError(f"missing target sample: {sample['path']}")
        _copy_original(sample["path"], TARGET_ROOT / "00_original", sample["sample_id"])
        phase4, t4 = _run(sample, TARGET_ROOT / "01_phase4_frozen" / sample["sample_id"], stability=False, correction=False)
        phase5, t5 = _run(sample, TARGET_ROOT / "02_phase5_default" / sample["sample_id"], stability=True, correction=False)
        correction, tc = _run(sample, TARGET_ROOT / "03_phase5_correction" / sample["sample_id"], stability=True, correction=True)
        paths = [Path(phase4["final_output_path"]), Path(phase5["final_output_path"]), Path(correction["final_output_path"])]
        _comparison(paths, TARGET_ROOT / "04_comparison" / f"{sample['sample_id']}__comparison.jpg", ["Phase 4", "Phase 5", "Correction"])
        record = _record(sample, phase4, phase5, correction, {"phase4": t4, "phase5": t5, "correction": tc})
        results.append(record)
        (TARGET_ROOT / "05_metrics" / f"{sample['sample_id']}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"[target] {sample['sample_id']} {record['phase5_color_lock_mode']} sat {record['phase4_metrics']['saturation_delta']} -> {record['phase5_default_metrics']['saturation_delta']}")
    manifest = {
        "total": len(results),
        "completed": len(results),
        "results": results,
    }
    (TARGET_ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return manifest


def _golden_samples() -> list[dict[str, Any]]:
    manifest = json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8"))
    return [sample for sample in manifest["samples"] if sample.get("status") == "ready"]


def run_golden() -> dict[str, Any]:
    for sub in ("01_phase4_frozen", "02_phase5_default", "03_metrics"):
        (GOLDEN_RESULT_ROOT / sub).mkdir(parents=True, exist_ok=True)
    results = []
    for index, sample in enumerate(_golden_samples(), start=1):
        sample_id = sample["sample_id"]
        path = GOLDEN_ROOT / sample["relative_path"]
        run_sample = {
            "sample_id": sample_id,
            "path": path,
            "mode": "text_safe" if sample.get("image_type_expected") == "text_poster" else "fidelity",
            "format": "png" if bool(sample.get("has_alpha")) or path.suffix.lower() == ".png" else "jpg",
        }
        phase4, t4 = _run(run_sample, GOLDEN_RESULT_ROOT / "01_phase4_frozen" / sample_id, stability=False, correction=False)
        phase5, t5 = _run(run_sample, GOLDEN_RESULT_ROOT / "02_phase5_default" / sample_id, stability=True, correction=False)
        record = _record(run_sample, phase4, phase5, {}, {"phase4": t4, "phase5": t5})
        record["expected_type"] = sample.get("image_type_expected")
        record["has_alpha"] = bool(sample.get("has_alpha"))
        record["phase5_color_correction_enabled"] = False
        results.append(record)
        (GOLDEN_RESULT_ROOT / "03_metrics" / f"{sample_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"[{index}/{len(_golden_samples())}] {sample_id} {record['phase5_color_lock_mode']} q {record['phase4_quality_1080p_pass']}->{record['phase5_quality_1080p_pass']}")
    summary = {
        "total": len(results),
        "completed": len(results),
        "failed": 0,
        "phase5_stability_count": sum(1 for r in results if r["phase5_color_lock_mode"] not in {"disabled", "monitor_pass"}),
        "phase5_color_fallback_count": sum(1 for r in results if r["phase5_color_fallback_triggered"]),
        "phase5_correction_count": 0,
        "quality_pass_before": sum(1 for r in results if r["phase4_quality_1080p_pass"]),
        "quality_pass_after": sum(1 for r in results if r["phase5_quality_1080p_pass"]),
        "results": results,
    }
    (GOLDEN_RESULT_ROOT / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


def main() -> int:
    targeted = run_targeted()
    golden = run_golden()
    print(
        json.dumps(
            {
                "targeted_completed": targeted["completed"],
                "golden_completed": golden["completed"],
                "phase5_stability_count": golden["phase5_stability_count"],
                "phase5_color_fallback_count": golden["phase5_color_fallback_count"],
                "quality_pass_before": golden["quality_pass_before"],
                "quality_pass_after": golden["quality_pass_after"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
