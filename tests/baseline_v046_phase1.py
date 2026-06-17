from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

RESULT_ROOT = PROJECT_ROOT / "tests" / "results" / "v046_phase1_baseline"
DIAG_ROOT = PROJECT_ROOT / "runtime" / "diagnostics" / "v046_t01"
V0453_HISTORY_ROOT = PROJECT_ROOT / "tests" / "diagnostics" / "output" / "core"

SAMPLES = [
    {
        "sample_id": "jpg_core",
        "label": "JPG",
        "path": PROJECT_ROOT / "tests" / "outputs" / "v036_api_validation" / "output" / "images" / "case_original_jpg_vmp_v036_optimized.jpg",
        "mode": "fidelity",
        "format": "jpg",
        "risk": "Filename contains optimized; text-like poster; low-resolution upscale.",
        "v0453_dir": V0453_HISTORY_ROOT / "JPG",
    },
    {
        "sample_id": "png_core",
        "label": "普通PNG",
        "path": PROJECT_ROOT / "runtime" / "v044_validation" / "inputs" / "test_1.png",
        "mode": "fidelity",
        "format": "png",
        "risk": "Very small source; known high file-size ratio; current quality gate may fail.",
        "v0453_dir": V0453_HISTORY_ROOT / "普通PNG",
    },
    {
        "sample_id": "transparent_png_core",
        "label": "透明PNG",
        "path": PROJECT_ROOT / "tests" / "outputs" / "v036_backend_validation_final" / "input" / "realalpha.png",
        "mode": "fidelity",
        "format": "png",
        "risk": "Real alpha channel must be preserved; PNG output expected.",
        "v0453_dir": V0453_HISTORY_ROOT / "透明PNG",
    },
    {
        "sample_id": "cn_small_text_core",
        "label": "中文小字图",
        "path": PROJECT_ROOT / "backend" / "backend_uploads" / "高清测试.png",
        "mode": "text_safe",
        "format": "png",
        "risk": "Chinese small-text readability; known quality_1080p_pass=false.",
        "v0453_dir": V0453_HISTORY_ROOT / "中文小字图",
    },
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_text(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        return (completed.stdout or completed.stderr).strip()
    except Exception as exc:  # noqa: BLE001
        return f"not_available: {exc}"


def package_versions() -> dict[str, Any]:
    versions: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "venv_path": str(PROJECT_ROOT / ".venv"),
        "node": run_text(["node", "--version"]),
        "npm": run_text(["npm.cmd", "--version"]),
    }
    try:
        import cv2
        import fastapi
        import numpy
        import PIL
        import uvicorn

        versions.update(
            {
                "fastapi": fastapi.__version__,
                "uvicorn": uvicorn.__version__,
                "opencv": cv2.__version__,
                "numpy": numpy.__version__,
                "pillow": PIL.__version__,
            }
        )
    except Exception as exc:  # noqa: BLE001
        versions["python_packages_error"] = str(exc)

    try:
        package = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))
        deps = {}
        deps.update(package.get("dependencies") or {})
        deps.update(package.get("devDependencies") or {})
        versions.update(
            {
                "react": deps.get("react"),
                "vite": deps.get("vite"),
                "tailwindcss": deps.get("tailwindcss"),
            }
        )
    except Exception as exc:  # noqa: BLE001
        versions["node_packages_error"] = str(exc)
    return versions


def git_baseline() -> dict[str, Any]:
    return {
        "branch": run_text(["git", "branch", "--show-current"]),
        "head": run_text(["git", "rev-parse", "HEAD"]),
        "head_short": run_text(["git", "rev-parse", "--short", "HEAD"]),
        "head_time": run_text(["git", "log", "-1", "--format=%ci"]),
        "head_subject": run_text(["git", "log", "-1", "--format=%s"]),
        "status_short": run_text(["git", "status", "--short"]).splitlines(),
        "tags_at_head": run_text(["git", "tag", "--points-at", "HEAD"]).splitlines(),
        "stash_list": run_text(["git", "stash", "list"]).splitlines(),
        "merge_base_780d49b_head": run_text(["git", "merge-base", "780d49b", "HEAD"]),
        "is_780d49b_ancestor_of_head": run_text(["git", "merge-base", "--is-ancestor", "780d49b", "HEAD"]) == "",
    }


def image_info(path: Path) -> dict[str, Any]:
    from PIL import Image

    with Image.open(path) as image:
        return {
            "format": image.format,
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
            "has_alpha": image.mode in {"RGBA", "LA"} or ("transparency" in image.info),
        }


def latest_file(folder: Path, pattern: str) -> str | None:
    if not folder.exists():
        return None
    files = [path for path in folder.glob(pattern) if path.is_file()]
    if not files:
        return None
    return str(max(files, key=lambda path: path.stat().st_mtime))


def v0453_historical_file(folder: Path) -> str | None:
    """Pick the latest 08:xx historical output before V0.4.6 Phase 1 edits."""
    if not folder.exists():
        return None
    files = [
        path
        for path in folder.glob("*20260617_08*.png")
        if path.is_file()
    ]
    if not files:
        return latest_file(folder, "*")
    return str(max(files, key=lambda path: path.stat().st_mtime))


def collect_sample(sample: dict[str, Any]) -> dict[str, Any]:
    from backend.v036_output_core import process_v036_output

    path = Path(sample["path"])
    before_hash = sha256_file(path)
    before_stat = path.stat()
    info = image_info(path)
    started = time.perf_counter()
    output_dir = RESULT_ROOT / sample["label"]
    output_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {}
    error = ""
    try:
        payload = process_v036_output(
            path,
            output_dir,
            mode=sample["mode"],
            output_profile="delivery_1080p",
            output_format=sample["format"],
            debug_keep_intermediate=False,
        )
    except Exception:  # noqa: BLE001
        error = traceback.format_exc()
    after_hash = sha256_file(path)
    after_stat = path.stat()
    duration = round(time.perf_counter() - started, 6)
    output_path = Path(payload["final_output_path"]) if payload.get("final_output_path") else None
    debug_quality = payload.get("debug_quality") or {}
    task_report = payload.get("task_report") or {}
    expected_issue = sample["sample_id"] in {"png_core", "cn_small_text_core"} and payload.get("quality_1080p_pass") is False
    status = "FAIL"
    if error:
        status = "FAIL"
    elif output_path and output_path.exists():
        status = "PASS_WITH_KNOWN_ISSUE" if expected_issue else "PASS"
    v0453_output = v0453_historical_file(sample["v0453_dir"])
    return {
        "sample_id": sample["sample_id"],
        "label": sample["label"],
        "input": {
            "path": str(path),
            "filename": path.name,
            "sha256_before": before_hash,
            "sha256_after": after_hash,
            "hash_unchanged": before_hash == after_hash,
            "size_bytes_before": before_stat.st_size,
            "size_bytes_after": after_stat.st_size,
            "size_unchanged": before_stat.st_size == after_stat.st_size,
            "format": info["format"],
            "width": info["width"],
            "height": info["height"],
            "mode": info["mode"],
            "has_alpha": info["has_alpha"],
            "risk": sample["risk"],
        },
        "v0453_baseline_output": {
            "status": "historical_output_found" if v0453_output else "historical_output_missing",
            "path": v0453_output,
            "source": str(sample["v0453_dir"]),
            "selection_rule": "latest file matching *20260617_08*.png; this avoids using post-Phase-1 14:xx rerun outputs",
        },
        "v046_phase1_output": {
            "path": str(output_path) if output_path else None,
            "exists": bool(output_path and output_path.exists()),
            "size_bytes": output_path.stat().st_size if output_path and output_path.exists() else None,
            "sha256": sha256_file(output_path) if output_path and output_path.exists() else None,
            "format": output_path.suffix.lower().lstrip(".") if output_path else None,
            "width": payload.get("output_width"),
            "height": payload.get("output_height"),
            "processing_time_sec": payload.get("debug_timing", {}).get("total_time", duration),
        },
        "diagnostics": {
            "image_type": payload.get("image_type"),
            "quality_1080p_pass": payload.get("quality_1080p_pass"),
            "quality_1080p_level": payload.get("quality_1080p_level"),
            "text_clarity_score": task_report.get("text_clarity_score"),
            "small_text_readability_score": task_report.get("small_text_readability_score"),
            "text_edge_clean_score": task_report.get("text_edge_clean_score"),
            "before_text_region_density": debug_quality.get("before_text_region_density"),
            "after_text_region_density": debug_quality.get("after_text_region_density"),
            "text_region_density_delta": debug_quality.get("text_region_density_delta"),
            "v046_text_engine_active": task_report.get("v046_text_engine_active"),
            "v046_quality_profile": debug_quality.get("v046_quality_profile"),
            "pseudo_hd_risk": task_report.get("pseudo_hd_risk"),
            "artifact_risk": task_report.get("artifact_risk"),
            "color_fidelity_score": task_report.get("color_fidelity_score"),
            "delivery_score": task_report.get("delivery_score"),
            "warnings": task_report.get("warnings") or [],
        },
        "result": status,
        "error": error,
    }


def directory_audit() -> dict[str, Any]:
    candidates = {
        "user_original_sample_locations": [str(item["path"]) for item in SAMPLES],
        "runtime_uploads": str(PROJECT_ROOT / "runtime" / "uploads"),
        "runtime_v04_inputs": str(PROJECT_ROOT / "runtime" / "v04_inputs"),
        "runtime_work": str(PROJECT_ROOT / "runtime" / "work"),
        "runtime_logs": str(PROJECT_ROOT / "logs"),
        "runtime_diagnostics": str(DIAG_ROOT),
        "tests_golden_v046": str(PROJECT_ROOT / "tests" / "golden_v046"),
        "test_output_dir": str(RESULT_ROOT),
        "api_test_output_dir": str(PROJECT_ROOT / "tests" / "diagnostics" / "output" / "api"),
        "default_formal_output_dir": "C:/Users/xyppt/Desktop/雪原Ai增强引擎/输出成品",
    }
    return {
        "paths": candidates,
        "exists": {key: Path(value).exists() if isinstance(value, str) else None for key, value in candidates.items()},
        "notes": [
            "T01 sample outputs are isolated under tests/results/v046_phase1_baseline.",
            "API diagnostic outputs use tests/diagnostics/output/api as requested output_dir.",
            "runtime/work is used for temporary main/optimized candidates and should not contain formal final files.",
        ],
    }


def main() -> int:
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    DIAG_ROOT.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now().isoformat(timespec="seconds")
    samples = [collect_sample(sample) for sample in SAMPLES]
    summary = {
        "task": "T01 freeze V0.4.6 Phase 1 baseline",
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "environment": package_versions(),
        "git": git_baseline(),
        "commands": {
            "backend_start": f"{PROJECT_ROOT / '.venv' / 'Scripts' / 'python.exe'} main.py --web",
            "frontend_start": "npm.cmd run dev",
            "baseline_test": f"{PROJECT_ROOT / '.venv' / 'Scripts' / 'python.exe'} tests/baseline_v046_phase1.py",
            "api_regression": f"{PROJECT_ROOT / '.venv' / 'Scripts' / 'python.exe'} tests/diagnostics/test_v0453_api_pipeline.py",
        },
        "ports": {"backend": 8787, "frontend": 5173},
        "environment_variables": {
            key: "SET"
            for key in sorted(os.environ)
            if key.startswith(("VITE", "VISUAL", "VMP", "PYTHON", "NODE", "PORT", "HOST", "APP", "ENV"))
        },
        "samples": samples,
        "directory_audit": directory_audit(),
        "summary_table": [
            {
                "sample_id": item["sample_id"],
                "image_type": item["diagnostics"].get("image_type"),
                "input_format": item["input"].get("format"),
                "input_size": item["input"].get("size_bytes_before"),
                "output_format": item["v046_phase1_output"].get("format"),
                "output_dimensions": f"{item['v046_phase1_output'].get('width')}x{item['v046_phase1_output'].get('height')}",
                "output_size": item["v046_phase1_output"].get("size_bytes"),
                "processing_time": item["v046_phase1_output"].get("processing_time_sec"),
                "quality_1080p_pass": item["diagnostics"].get("quality_1080p_pass"),
                "quality_1080p_level": item["diagnostics"].get("quality_1080p_level"),
                "text_clarity_score": item["diagnostics"].get("text_clarity_score"),
                "small_text_readability_score": item["diagnostics"].get("small_text_readability_score"),
                "text_edge_clean_score": item["diagnostics"].get("text_edge_clean_score"),
                "pseudo_hd_risk": item["diagnostics"].get("pseudo_hd_risk"),
                "artifact_risk": item["diagnostics"].get("artifact_risk"),
                "final_output_exists": item["v046_phase1_output"].get("exists"),
                "result": item["result"],
            }
            for item in samples
        ],
    }
    output_path = DIAG_ROOT / "v046_t01_baseline.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if all(item["result"] in {"PASS", "PASS_WITH_KNOWN_ISSUE"} for item in samples) else 1


if __name__ == "__main__":
    raise SystemExit(main())
