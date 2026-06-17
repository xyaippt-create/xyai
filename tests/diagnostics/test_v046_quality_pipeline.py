from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SAMPLES = [
    {
        "kind": "JPG",
        "path": PROJECT_ROOT / "tests" / "outputs" / "v036_api_validation" / "output" / "images" / "case_original_jpg_vmp_v036_optimized.jpg",
        "mode": "fidelity",
        "format": "jpg",
    },
    {
        "kind": "普通PNG",
        "path": PROJECT_ROOT / "runtime" / "v044_validation" / "inputs" / "test_1.png",
        "mode": "fidelity",
        "format": "png",
    },
    {
        "kind": "透明PNG",
        "path": PROJECT_ROOT / "tests" / "outputs" / "v036_backend_validation_final" / "input" / "realalpha.png",
        "mode": "fidelity",
        "format": "png",
    },
    {
        "kind": "中文小字图",
        "path": PROJECT_ROOT / "backend" / "backend_uploads" / "高清测试.png",
        "mode": "text_safe",
        "format": "png",
    },
]


def run_sample(sample: dict) -> dict:
    from backend.v036_output_core import process_v036_output

    started = time.perf_counter()
    output_dir = PROJECT_ROOT / "tests" / "diagnostics" / "output" / "v046_quality" / sample["kind"]
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "sample": sample["kind"],
        "input_path": str(sample["path"]),
        "status": "NOT_TESTED",
        "duration_sec": None,
        "checks": {},
        "metrics": {},
        "output_file": None,
        "traceback": "",
    }
    try:
        if not sample["path"].exists():
            raise FileNotFoundError(str(sample["path"]))
        payload = process_v036_output(
            sample["path"],
            output_dir,
            mode=sample["mode"],
            output_profile="delivery_1080p",
            output_format=sample["format"],
            debug_keep_intermediate=False,
        )
        output_file = Path(payload["final_output_path"])
        debug_quality = payload.get("debug_quality") or {}
        task_report = payload.get("task_report") or {}
        checks = {
            "completed": True,
            "output_exists": output_file.exists(),
            "keeps_aspect_no_downscale": bool(payload.get("resolution_gate_pass") and not payload.get("was_downscaled")),
            "color_fidelity_ok": float(debug_quality.get("color_fidelity_score") or 0) >= 91.0,
            "artifact_safe": debug_quality.get("artifact_risk") != "high",
            "texture_not_high_risk": debug_quality.get("texture_loss_risk") != "high",
        }
        if sample["kind"] == "JPG":
            checks["jpg_stays_1080p_pass"] = bool(payload.get("quality_1080p_pass"))
            checks["jpg_level_not_failed"] = payload.get("quality_1080p_level") != "failed"
        if sample["kind"] == "中文小字图":
            checks["small_text_engine_active"] = bool(task_report.get("v046_text_engine_active"))
            checks["small_text_detected"] = payload.get("image_type") in {"text_poster", "ppt_page"}
            checks["small_text_readability_floor"] = float(task_report.get("small_text_readability_score") or 0) >= 24.0
            checks["text_clarity_floor"] = float(task_report.get("text_clarity_score") or 0) >= 24.0
        result.update(
            {
                "status": "PASS" if all(checks.values()) else "FAIL",
                "duration_sec": round(time.perf_counter() - started, 6),
                "checks": checks,
                "metrics": {
                    "image_type": payload.get("image_type"),
                    "output_width": payload.get("output_width"),
                    "output_height": payload.get("output_height"),
                    "quality_1080p_pass": payload.get("quality_1080p_pass"),
                    "quality_1080p_level": payload.get("quality_1080p_level"),
                    "clarity_score": task_report.get("clarity_score"),
                    "text_clarity_score": task_report.get("text_clarity_score"),
                    "text_edge_clean_score": task_report.get("text_edge_clean_score"),
                    "small_text_readability_score": task_report.get("small_text_readability_score"),
                    "color_fidelity_score": task_report.get("color_fidelity_score"),
                    "delivery_score": task_report.get("delivery_score"),
                    "file_size_ratio": payload.get("file_size_ratio"),
                    "v046_text_engine_active": task_report.get("v046_text_engine_active"),
                    "warnings": task_report.get("warnings") or [],
                },
                "output_file": str(output_file),
            }
        )
    except Exception:  # noqa: BLE001 - diagnostic must capture the full failure payload.
        result.update(
            {
                "status": "FAIL",
                "duration_sec": round(time.perf_counter() - started, 6),
                "traceback": traceback.format_exc(),
            }
        )
    return result


def main() -> int:
    started = time.time()
    results = [run_sample(sample) for sample in SAMPLES]
    summary = {
        "script": str(Path(__file__).resolve()),
        "project_root": str(PROJECT_ROOT),
        "started_at": started,
        "duration_sec": round(time.time() - started, 6),
        "all_passed": all(item["status"] == "PASS" for item in results),
        "results": results,
    }
    out_path = PROJECT_ROOT / "tests" / "diagnostics" / "v046_quality_pipeline_results.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
