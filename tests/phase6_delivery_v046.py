from __future__ import annotations

import json
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.pipeline import process_v046_delivery  # noqa: E402


GOLDEN_ROOT = PROJECT_ROOT / "tests" / "golden_v046"
GOLDEN_MANIFEST = GOLDEN_ROOT / "manifest.json"
RESULT_ROOT = PROJECT_ROOT / "tests" / "results" / "v046_phase6_targeted"
GOLDEN_RESULT_ROOT = PROJECT_ROOT / "tests" / "results" / "v046_phase6_golden_regression"


def _find_huawei_sample() -> Path:
    root = PROJECT_ROOT / "tests" / "fixtures" / "v046_phase3_freeze_inputs"
    matches = list(root.glob("*.png"))
    if not matches:
        raise FileNotFoundError(root)
    return matches[0]


TARGET_SAMPLES = [
    ("cn_small_text", GOLDEN_ROOT / "smoke" / "text_poster_cn_small_legacy.png", "text_safe", "png"),
    ("ordinary_jpg", GOLDEN_ROOT / "smoke" / "original_unprocessed_low_quality.jpg", "fidelity", "jpg"),
    ("ordinary_png", GOLDEN_ROOT / "smoke" / "product_png_legacy.png", "fidelity", "png"),
    ("transparent_png", GOLDEN_ROOT / "smoke" / "transparent_png_legacy.png", "fidelity", "png"),
    ("real_person_photo", PROJECT_ROOT / "tests" / "fixtures" / "v046_phase4_real_photo_inputs" / "Image_1781400827720_384.jpg", "fidelity", "jpg"),
    ("real_product_photo", PROJECT_ROOT / "tests" / "fixtures" / "v046_phase4_real_photo_inputs" / "05_real_product_lowquality.jpg", "fidelity", "jpg"),
    ("real_architecture_photo", PROJECT_ROOT / "tests" / "fixtures" / "v046_phase4_real_photo_inputs" / "06_real_architecture_lowquality.jpg", "fidelity", "jpg"),
    ("huawei_color_sample", _find_huawei_sample(), "fidelity", "png"),
    ("synthetic_gradient", GOLDEN_ROOT / "synthetic" / "gradient_band.png", "fidelity", "png"),
    ("synthetic_highlight", GOLDEN_ROOT / "synthetic" / "highlight_clip.png", "fidelity", "png"),
]


def _run_sample(sample_id: str, path: Path, mode: str, output_format: str, output_root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    payload = process_v046_delivery(
        {
            "input_path": path,
            "output_root": output_root / sample_id,
            "mode": mode,
            "output_profile": "delivery_1080p",
            "output_format": output_format,
            "debug_keep_intermediate": False,
            "color_stability_enabled": True,
            "color_correction_enabled": False,
        }
    )
    elapsed = round((time.perf_counter() - started) * 1000.0, 3)
    debug = payload.get("debug_quality") or {}
    final_path = Path(payload["final_output_path"])
    return {
        "sample_id": sample_id,
        "input_path": str(path),
        "final_path": str(final_path),
        "final_exists": final_path.exists(),
        "image_type": payload.get("image_type"),
        "quality_1080p_pass": payload.get("quality_1080p_pass"),
        "quality_1080p_level": payload.get("quality_1080p_level"),
        "final_delivery_status": payload.get("final_delivery_status") or debug.get("final_delivery_status"),
        "final_delivery_reason": payload.get("final_delivery_reason") or debug.get("final_delivery_reason"),
        "final_delivery_risk_level": payload.get("final_delivery_risk_level") or debug.get("final_delivery_risk_level"),
        "final_delivery_recommended_usage": payload.get("final_delivery_recommended_usage") or debug.get("final_delivery_recommended_usage"),
        "input_size_bytes": payload.get("input_size_bytes"),
        "final_size_bytes": payload.get("final_size_bytes"),
        "file_size_ratio": payload.get("file_size_ratio"),
        "phase6_visible_benefit_score": debug.get("phase6_visible_benefit_score"),
        "phase6_size_growth_ratio": debug.get("phase6_size_growth_ratio"),
        "phase6_benefit_size_ratio": debug.get("phase6_benefit_size_ratio"),
        "phase6_encoding_profile": debug.get("phase6_encoding_profile"),
        "phase6_size_fallback_triggered": debug.get("phase6_size_fallback_triggered"),
        "phase6_size_fallback_reason": debug.get("phase6_size_fallback_reason"),
        "phase6_gradient_risk": debug.get("phase6_gradient_risk"),
        "phase6_band_risk": debug.get("phase6_band_risk"),
        "phase6_highlight_pollution_risk": debug.get("phase6_highlight_pollution_risk"),
        "phase6_flat_region_uniformity": debug.get("phase6_flat_region_uniformity"),
        "phase6_smooth_region_fallback": debug.get("phase6_smooth_region_fallback"),
        "has_alpha": payload.get("has_alpha"),
        "alpha_used": payload.get("alpha_used"),
        "phase5_color_lock_mode": debug.get("phase5_color_lock_mode"),
        "processing_time_ms": elapsed,
    }


def run_targeted() -> dict[str, Any]:
    if RESULT_ROOT.exists():
        shutil.rmtree(RESULT_ROOT)
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    results = []
    for sample_id, path, mode, output_format in TARGET_SAMPLES:
        if not path.exists():
            results.append({"sample_id": sample_id, "input_path": str(path), "error": "missing_input"})
            continue
        record = _run_sample(sample_id, path, mode, output_format, RESULT_ROOT / "outputs")
        results.append(record)
        (RESULT_ROOT / "metrics").mkdir(parents=True, exist_ok=True)
        (RESULT_ROOT / "metrics" / f"{sample_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    manifest = {"total": len(results), "completed": sum(1 for r in results if r.get("final_exists")), "results": results}
    (RESULT_ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return manifest


def _golden_samples() -> list[dict[str, Any]]:
    manifest = json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8"))
    return [sample for sample in manifest["samples"] if sample.get("status") == "ready"]


def run_golden() -> dict[str, Any]:
    if GOLDEN_RESULT_ROOT.exists():
        shutil.rmtree(GOLDEN_RESULT_ROOT)
    GOLDEN_RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    results = []
    for sample in _golden_samples():
        sample_id = sample["sample_id"]
        path = GOLDEN_ROOT / sample["relative_path"]
        mode = "text_safe" if sample.get("image_type_expected") == "text_poster" else "fidelity"
        output_format = "png" if bool(sample.get("has_alpha")) or path.suffix.lower() == ".png" else "jpg"
        record = _run_sample(sample_id, path, mode, output_format, GOLDEN_RESULT_ROOT / "outputs")
        record["expected_type"] = sample.get("image_type_expected")
        results.append(record)
        (GOLDEN_RESULT_ROOT / "metrics").mkdir(parents=True, exist_ok=True)
        (GOLDEN_RESULT_ROOT / "metrics" / f"{sample_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    summary = {
        "total": len(results),
        "completed": sum(1 for r in results if r.get("final_exists")),
        "quality_pass_count": sum(1 for r in results if r.get("quality_1080p_pass")),
        "delivery_pass_count": sum(1 for r in results if r.get("final_delivery_status") == "PASS"),
        "delivery_limited_count": sum(1 for r in results if r.get("final_delivery_status") == "PASS_WITH_LIMITATION"),
        "delivery_fail_count": sum(1 for r in results if r.get("final_delivery_status") == "FAIL"),
        "size_fallback_count": sum(1 for r in results if r.get("phase6_size_fallback_triggered")),
        "smooth_fallback_count": sum(1 for r in results if r.get("phase6_smooth_region_fallback")),
        "avg_file_size_ratio": round(sum(float(r.get("file_size_ratio") or 0.0) for r in results) / max(len(results), 1), 6),
        "results": results,
    }
    (GOLDEN_RESULT_ROOT / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


def run_api_checks() -> dict[str, Any]:
    from fastapi.testclient import TestClient
    import engine.pipeline as engine_pipeline
    from main import build_web_app, default_output_dir

    calls: list[dict[str, Any]] = []
    original = engine_pipeline.process_v046_delivery

    def spy(context):
        calls.append({"input_path": str(context.get("input_path")), "output_root": str(context.get("output_root"))})
        return original(context)

    engine_pipeline.process_v046_delivery = spy
    try:
        client = TestClient(build_web_app())
        health = client.get("/api/health").json()
        default_dir = health.get("data", {}).get("default_output_dir")
        output_dir = RESULT_ROOT / "api_output"
        output_dir.mkdir(parents=True, exist_ok=True)
        sample_path = GOLDEN_ROOT / "smoke" / "product_png_legacy.png"
        with sample_path.open("rb") as handle:
            upload = client.post(
                "/api/upload",
                data={"mode": "fidelity", "output_profile": "delivery_1080p", "output_format": "png", "output_dir": str(output_dir)},
                files={"file": (sample_path.name, handle, "application/octet-stream")},
            )
        payload = upload.json()
        task_id = payload.get("task_id") or (payload.get("data") or {}).get("task_id")
        stream_endpoint = payload.get("streamEndpoint") or (payload.get("data") or {}).get("streamEndpoint")
        task_payload = {}
        for _ in range(100):
            status = client.get(f"/api/v1/tasks/{task_id}")
            task_payload = status.json().get("data") or {}
            if task_payload.get("task_status") in {"completed", "failed"}:
                break
            time.sleep(0.25)
        final_url = task_payload.get("final_output_url") or task_payload.get("enhancedUrl")
        final_ok = bool(final_url and client.get(final_url).status_code == 200)
        sse_text = client.get(stream_endpoint).text if stream_endpoint else ""
        bundle_response = client.post(f"/api/v1/tasks/{task_id}/feedback-bundle")
        bundle = bundle_response.json().get("data") or {}
    finally:
        engine_pipeline.process_v046_delivery = original

    rename_dir = RESULT_ROOT / "rename_output"
    rename_dir.mkdir(parents=True, exist_ok=True)
    first = _run_sample("rename_collision", sample_path, "fidelity", "png", rename_dir)
    second = _run_sample("rename_collision", sample_path, "fidelity", "png", rename_dir)

    bad_output_file = RESULT_ROOT / "not_a_directory.txt"
    bad_output_file.write_text("not a directory", encoding="utf-8")
    with sample_path.open("rb") as handle:
        bad_upload = client.post(
            "/api/upload",
            data={"mode": "fidelity", "output_profile": "delivery_1080p", "output_format": "png", "output_dir": str(bad_output_file)},
            files={"file": (sample_path.name, handle, "application/octet-stream")},
        )

    bundle_entries = []
    bundle_path = Path(bundle.get("feedback_bundle_path") or "")
    if bundle_path.exists():
        with zipfile.ZipFile(bundle_path, "r") as archive:
            bundle_entries = archive.namelist()

    result = {
        "health_default_output_dir": default_dir,
        "expected_default_output_dir": str(default_output_dir()),
        "default_output_dir_match": default_dir == str(default_output_dir()),
        "upload_status": upload.status_code,
        "task_status": task_payload.get("task_status"),
        "pipeline_call_count": len(calls),
        "final_output_url_ok": final_ok,
        "sse_done": "[DONE]" in sse_text,
        "feedback_bundle_status": bundle.get("feedback_bundle_status"),
        "feedback_bundle_path": bundle.get("feedback_bundle_path"),
        "feedback_bundle_size": bundle.get("feedback_bundle_size"),
        "feedback_bundle_redacted": bundle.get("feedback_bundle_redacted"),
        "feedback_bundle_entries": bundle_entries,
        "rename_collision_distinct": first.get("final_path") != second.get("final_path"),
        "permission_failure_status": bad_upload.status_code,
        "permission_failure_ok": bad_upload.status_code == 400,
    }
    (RESULT_ROOT / "api_checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result


def main() -> int:
    targeted = run_targeted()
    golden = run_golden()
    api = run_api_checks()
    summary = {"targeted": targeted, "golden": golden, "api": api}
    (RESULT_ROOT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "targeted_completed": targeted["completed"],
        "golden_completed": golden["completed"],
        "delivery_pass_count": golden["delivery_pass_count"],
        "delivery_limited_count": golden["delivery_limited_count"],
        "api_pass": bool(api["final_output_url_ok"] and api["sse_done"] and api["pipeline_call_count"] == 1),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
