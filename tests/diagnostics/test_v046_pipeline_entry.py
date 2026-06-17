from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


RESULT_PATH = PROJECT_ROOT / "tests" / "diagnostics" / "v046_pipeline_entry_results.json"
OUTPUT_DIR = PROJECT_ROOT / "tests" / "diagnostics" / "output" / "pipeline_entry"
SAMPLE_PATH = PROJECT_ROOT / "tests" / "golden_v046" / "smoke" / "product_png_legacy.png"


def read_sse(client, endpoint: str) -> dict:
    text_parts: list[str] = []
    with client.stream("GET", endpoint) as response:
        for chunk in response.iter_text():
            text_parts.append(chunk)
            if "[DONE]" in chunk:
                break
    text = "".join(text_parts)
    return {
        "status_code": response.status_code,
        "done": "[DONE]" in text,
        "has_completed_status": '"task_status": "completed"' in text or '"task_status":"completed"' in text,
    }


def main() -> int:
    from fastapi.testclient import TestClient
    import engine.pipeline as engine_pipeline
    from main import build_web_app

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    calls: list[dict] = []
    original = engine_pipeline.process_v046_delivery

    def spy(context):
        calls.append(
            {
                "input_path": str(context.get("input_path")),
                "output_root": str(context.get("output_root")),
                "mode": context.get("mode"),
                "output_profile": context.get("output_profile"),
                "output_format": context.get("output_format"),
            }
        )
        return original(context)

    engine_pipeline.process_v046_delivery = spy
    try:
        client = TestClient(build_web_app())
        with SAMPLE_PATH.open("rb") as handle:
            response = client.post(
                "/api/upload",
                data={
                    "mode": "fidelity",
                    "output_profile": "delivery_1080p",
                    "output_format": "png",
                    "output_dir": str(OUTPUT_DIR),
                },
                files={"file": (SAMPLE_PATH.name, handle, "application/octet-stream")},
            )
        payload = response.json()
        task_id = payload.get("task_id") or payload.get("taskId") or (payload.get("data") or {}).get("task_id")
        stream_endpoint = payload.get("streamEndpoint") or (payload.get("data") or {}).get("streamEndpoint")
        task_payload = {}
        for _ in range(80):
            status_response = client.get(f"/api/v1/tasks/{task_id}")
            task_payload = (status_response.json().get("data") or {}) if status_response.status_code == 200 else {}
            if task_payload.get("task_status") in {"completed", "failed"}:
                break
            time.sleep(0.25)
        final_url = task_payload.get("final_output_url") or task_payload.get("enhancedUrl")
        final_response = client.get(final_url) if final_url else None
        sse = read_sse(client, stream_endpoint) if stream_endpoint else {}
        result = {
            "api_status_code": response.status_code,
            "task_id": task_id,
            "task_status": task_payload.get("task_status"),
            "pipeline_call_count": len(calls),
            "pipeline_calls": calls,
            "final_output_url": final_url,
            "final_output_url_ok": bool(final_response and final_response.status_code == 200),
            "sse": sse,
            "passed": bool(
                response.status_code == 200
                and task_payload.get("task_status") == "completed"
                and len(calls) == 1
                and final_response
                and final_response.status_code == 200
                and sse.get("done")
            ),
        }
    finally:
        engine_pipeline.process_v046_delivery = original

    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
