from __future__ import annotations

import concurrent.futures
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


def _extract_task_id(payload: dict) -> str | None:
    return payload.get("taskId") or (payload.get("data") or {}).get("taskId") or payload.get("task_id")


def _extract_stream_endpoint(payload: dict) -> str | None:
    return payload.get("streamEndpoint") or (payload.get("data") or {}).get("streamEndpoint")


def _public_status(payload: dict) -> str:
    data = payload.get("data") or payload
    return str(data.get("status") or data.get("task_status") or "unknown")


def _extract_task_data(payload: dict) -> dict:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _extract_closure_value(app, route_path: str, name: str):
    for route in app.routes:
        if getattr(route, "path", None) != route_path:
            continue
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None or endpoint.__closure__ is None:
            continue
        for var_name, cell in zip(endpoint.__code__.co_freevars, endpoint.__closure__):
            if var_name == name:
                return cell.cell_contents
    return None


def _read_sse(client, endpoint: str) -> dict:
    response = client.get(endpoint)
    text = response.text
    return {
        "status_code": response.status_code,
        "done": "[DONE]" in text,
        "has_restoration_log": "restoration.log" in text,
        "has_failed_status": '"task_status":"failed"' in text or '"task_status": "failed"' in text,
        "has_completed_status": '"task_status":"completed"' in text or '"task_status": "completed"' in text,
        "line_count": len([line for line in text.splitlines() if line.strip()]),
        "text_head": text[:500],
    }


def _verify_final_output(client, task_payload: dict) -> dict:
    task = _extract_task_data(task_payload)
    result = task.get("task_result") or {}
    final_url = result.get("final_output_url") or task.get("final_output_url") or task.get("enhancedUrl")
    output_path = result.get("output_path") or task.get("output_path")
    output_filename = result.get("output_filename")
    url_status = None
    if final_url:
        url_status = client.get(final_url).status_code
    return {
        "final_output_url": final_url,
        "final_output_url_status": url_status,
        "final_output_url_ok": url_status == 200,
        "output_path": output_path,
        "output_path_exists": bool(output_path and Path(output_path).exists()),
        "output_filename": output_filename,
    }


def run_upload_poll(client, sample: dict, output_dir: Path, poll_timeout_sec: int = 20) -> dict:
    item = {
        "sample": sample["kind"],
        "input_path": str(sample["path"]),
        "api_upload": "NOT_TESTED",
        "task_poll": "NOT_TESTED",
        "sse": "NOT_TESTED",
        "sse_reconnect": "NOT_TESTED",
        "sse_double_subscribe": "NOT_TESTED",
        "final_output_url_check": "NOT_TESTED",
        "http_status": None,
        "raw_response_text": "",
        "json_complete": False,
        "task_id": None,
        "streamEndpoint": None,
        "task_status_history": [],
        "task_registry_registered": None,
        "health_after_upload": None,
        "final_status": None,
        "final_output": {},
        "sse_result": {},
        "sse_reconnect_result": {},
        "sse_double_subscribe_result": {},
        "exception_type": None,
        "traceback": "",
    }
    try:
        if not sample["path"].exists():
            raise FileNotFoundError(sample["path"])
        with sample["path"].open("rb") as handle:
            response = client.post(
                "/api/upload",
                files={"file": (sample["path"].name, handle, "application/octet-stream")},
                data={
                    "mode": sample["mode"],
                    "output_profile": "delivery_1080p",
                    "output_format": sample["format"],
                    "format": sample["format"],
                    "scale": "2",
                    "output_dir": str(output_dir),
                },
            )
        item["http_status"] = response.status_code
        item["raw_response_text"] = response.text
        try:
            payload = response.json()
            item["json_complete"] = True
        except Exception:
            payload = {}
        task_id = _extract_task_id(payload)
        stream_endpoint = _extract_stream_endpoint(payload)
        item["task_id"] = task_id
        item["streamEndpoint"] = stream_endpoint
        item["api_upload"] = "PASS" if response.status_code == 200 and bool(task_id) else "FAIL"
        item["task_registry_registered"] = bool(task_id)

        try:
            health = client.get("/api/health")
            item["health_after_upload"] = {"status_code": health.status_code, "ok": health.status_code == 200}
        except Exception as exc:
            item["health_after_upload"] = {"status_code": None, "ok": False, "error": str(exc)}

        if not task_id:
            item["task_poll"] = "NOT_TESTED"
            return item

        deadline = time.perf_counter() + poll_timeout_sec
        final_status = None
        status_payload = {}
        while time.perf_counter() < deadline:
            status_response = client.get(f"/api/v1/tasks/{task_id}")
            try:
                status_payload = status_response.json()
            except Exception:
                status_payload = {"raw": status_response.text}
            status = _public_status(status_payload)
            item["task_status_history"].append(
                {
                    "status_code": status_response.status_code,
                    "status": status,
                }
            )
            final_status = status
            if status in {"completed", "failed", "success", "error"}:
                break
            time.sleep(1)
        item["final_status"] = final_status
        if final_status in {"completed", "success"}:
            item["task_poll"] = "PASS"
        elif final_status in {"failed", "error"}:
            item["task_poll"] = "FAIL"
        else:
            item["task_poll"] = "TIMEOUT"

        if status_payload:
            item["final_output"] = _verify_final_output(client, status_payload)
            item["final_output_url_check"] = "PASS" if item["final_output"].get("final_output_url_ok") else "FAIL"

        if stream_endpoint and item["task_poll"] == "PASS":
            before_path = item["final_output"].get("output_path")
            sse_result = _read_sse(client, stream_endpoint)
            item["sse_result"] = sse_result
            item["sse"] = "PASS" if sse_result["status_code"] == 200 and sse_result["done"] else "FAIL"

            reconnect_result = _read_sse(client, stream_endpoint)
            item["sse_reconnect_result"] = reconnect_result
            after_payload = client.get(f"/api/v1/tasks/{task_id}").json()
            after_path = _verify_final_output(client, after_payload).get("output_path")
            item["sse_reconnect"] = "PASS" if reconnect_result["done"] and before_path == after_path else "FAIL"

            def fetch_stream():
                return _read_sse(client, stream_endpoint)

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                first, second = list(executor.map(lambda _: fetch_stream(), range(2)))
            final_payload = client.get(f"/api/v1/tasks/{task_id}").json()
            final_path = _verify_final_output(client, final_payload).get("output_path")
            item["sse_double_subscribe_result"] = {"first": first, "second": second}
            item["sse_double_subscribe"] = "PASS" if first["done"] and second["done"] and before_path == final_path else "FAIL"
    except BaseException as exc:  # noqa: BLE001 - diagnostic script must capture request-layer exceptions.
        item["api_upload"] = "FAIL"
        item["exception_type"] = type(exc).__name__
        item["traceback"] = traceback.format_exc()
    return item


def run_failed_sse_check(app, client) -> dict:
    result = {
        "status": "NOT_TESTED",
        "task_id": "diagnostic_failed_task",
        "sse": {},
        "reason": "",
    }
    registry = _extract_closure_value(app, "/api/v1/tasks/{task_id}", "task_registry")
    if not isinstance(registry, dict):
        result["status"] = "FAIL"
        result["reason"] = "task_registry closure not found"
        return result
    registry[result["task_id"]] = {
        "task_id": result["task_id"],
        "taskId": result["task_id"],
        "task_status": "failed",
        "status": "failed",
        "execution_state": "failed",
        "task_progress": 100,
        "mode": "fidelity",
        "target_resolution": "1080P",
        "output_profile": "delivery_1080p",
        "output_format": "png",
        "task_result": None,
        "task_report": {"warnings": ["diagnostic forced failure"]},
        "error_message": "diagnostic forced failure",
        "task_error": "diagnostic forced failure",
        "input_path": str(SAMPLES[0]["path"]),
        "output_root": str(PROJECT_ROOT / "tests" / "diagnostics" / "output" / "api"),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    sse = _read_sse(client, f"/api/v1/tasks/{result['task_id']}/stream")
    result["sse"] = sse
    result["status"] = "PASS" if sse["status_code"] == 200 and sse["done"] and sse["has_failed_status"] else "FAIL"
    return result


def main() -> int:
    from fastapi.testclient import TestClient
    from main import build_web_app

    output_dir = PROJECT_ROOT / "tests" / "diagnostics" / "output" / "api"
    output_dir.mkdir(parents=True, exist_ok=True)
    app = build_web_app()
    client = TestClient(app)
    started = time.time()
    health = client.get("/api/health")
    results = []
    for sample in SAMPLES:
        results.append(run_upload_poll(client, sample, output_dir))
    failure_sse = run_failed_sse_check(app, client)
    summary = {
        "script": str(Path(__file__).resolve()),
        "project_root": str(PROJECT_ROOT),
        "health": {"status_code": health.status_code, "body": health.text},
        "poll_timeout_sec": 20,
        "duration_sec": round(time.time() - started, 6),
        "results": results,
        "failure_sse": failure_sse,
    }
    out_path = PROJECT_ROOT / "tests" / "diagnostics" / "v0453_api_pipeline_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
