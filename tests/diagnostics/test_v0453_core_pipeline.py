from __future__ import annotations

import json
import multiprocessing as mp
import os
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
        "kind": "鏅€歅NG",
        "path": PROJECT_ROOT / "runtime" / "v044_validation" / "inputs" / "test_1.png",
        "mode": "fidelity",
        "format": "png",
    },
    {
        "kind": "閫忔槑PNG",
        "path": PROJECT_ROOT / "tests" / "outputs" / "v036_backend_validation_final" / "input" / "realalpha.png",
        "mode": "fidelity",
        "format": "png",
    },
    {
        "kind": "涓枃灏忓瓧鍥?,
        "path": PROJECT_ROOT / "backend" / "backend_uploads" / "楂樻竻娴嬭瘯.png",
        "mode": "text_safe",
        "format": "png",
    },
]


def _worker(sample: dict, output_dir: str, queue: mp.Queue) -> None:
    started = time.perf_counter()
    payload = {
        "sample": sample["kind"],
        "input_path": str(sample["path"]),
        "started": True,
        "completed": False,
        "duration_sec": None,
        "input_width": None,
        "input_height": None,
        "output_width": None,
        "output_height": None,
        "output_file": None,
        "exception_type": None,
        "traceback": "",
        "last_pipeline_stage": "process_v036_output:start",
    }
    try:
        from backend.v036_output_core import process_v036_output

        result = process_v036_output(
            Path(sample["path"]),
            Path(output_dir),
            mode=sample["mode"],
            output_profile="delivery_1080p",
            output_format=sample["format"],
            debug_keep_intermediate=False,
        )
        payload.update(
            {
                "completed": True,
                "duration_sec": round(time.perf_counter() - started, 6),
                "input_width": result.get("input_width"),
                "input_height": result.get("input_height"),
                "output_width": result.get("output_width"),
                "output_height": result.get("output_height"),
                "output_file": result.get("final_output_path"),
                "last_pipeline_stage": "process_v036_output:completed",
                "task_result": result.get("task_result"),
                "task_report": result.get("task_report"),
                "debug_timing": result.get("debug_timing"),
            }
        )
    except BaseException as exc:  # noqa: BLE001 - diagnostic script must capture process-fatal exceptions too.
        payload.update(
            {
                "duration_sec": round(time.perf_counter() - started, 6),
                "exception_type": type(exc).__name__,
                "traceback": traceback.format_exc(),
                "last_pipeline_stage": "process_v036_output:exception",
            }
        )
    queue.put(payload)


def run_sample(sample: dict, timeout_sec: int = 120) -> dict:
    output_dir = PROJECT_ROOT / "tests" / "diagnostics" / "output" / "core" / sample["kind"]
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "sample": sample["kind"],
        "input_path": str(sample["path"]),
        "status": "NOT_TESTED",
        "process_exit_code": None,
        "process_exited": False,
        "timeout_sec": timeout_sec,
        "data": None,
    }
    if not sample["path"].exists():
        result.update({"status": "FAIL", "data": {"exception_type": "FileNotFoundError", "traceback": "sample not found"}})
        return result

    queue: mp.Queue = mp.Queue()
    process = mp.Process(target=_worker, args=(sample, str(output_dir), queue), daemon=False)
    process.start()
    process.join(timeout=timeout_sec)
    if process.is_alive():
        process.terminate()
        process.join(5)
        result.update({"status": "TIMEOUT", "process_exit_code": process.exitcode, "process_exited": False})
        return result

    result["process_exit_code"] = process.exitcode
    result["process_exited"] = True
    if process.exitcode not in (0, None):
        result["status"] = "PROCESS_EXIT"
        result["data"] = {"exception_type": "ProcessExit", "traceback": f"child process exit code {process.exitcode}"}
        return result

    if queue.empty():
        result["status"] = "PROCESS_EXIT"
        result["data"] = {"exception_type": "NoResult", "traceback": "child process exited without diagnostic payload"}
        return result

    data = queue.get()
    result["data"] = data
    result["status"] = "PASS" if data.get("completed") else "FAIL"
    return result


def main() -> int:
    started = time.time()
    results = [run_sample(sample) for sample in SAMPLES]
    summary = {
        "script": str(Path(__file__).resolve()),
        "project_root": str(PROJECT_ROOT),
        "python": sys.version,
        "pid": os.getpid(),
        "started_at": started,
        "duration_sec": round(time.time() - started, 6),
        "results": results,
    }
    out_path = PROJECT_ROOT / "tests" / "diagnostics" / "v0453_core_pipeline_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
