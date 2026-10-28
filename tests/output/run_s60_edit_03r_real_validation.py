from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import time
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode(path: Path) -> dict[str, Any]:
    with Image.open(path) as opened:
        opened.load()
        return {"decode": "PASS", "width": opened.width, "height": opened.height, "format": opened.format}


def data(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    payload = response.json()
    if payload.get("success") is False:
        raise RuntimeError(json.dumps(payload, ensure_ascii=False))
    return payload["data"]


def find_output_items(client: httpx.Client) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = data(client.get("/api/output-center/items", params={"limit": 100, "offset": offset}))
        items.extend(page["items"])
        if not page.get("has_more"):
            return items
        offset = int(page["next_offset"])


def result_fact(
    *,
    name: str,
    task_id: str,
    result_id: str,
    source_result_id: str,
    source_task_id: str,
    source_feature_key: str,
    path: Path,
    registered_sha: str,
    output_items: list[dict[str, Any]],
) -> dict[str, Any]:
    actual_sha = sha256(path)
    if actual_sha != registered_sha:
        raise AssertionError(f"{name} SHA mismatch: {actual_sha} != {registered_sha}")
    decoded = decode(path)
    item = next((entry for entry in output_items if entry.get("result_id") == result_id), None)
    if item is None:
        raise AssertionError(f"{name} not visible in Output Center")
    return {
        "name": name,
        "task_id": task_id,
        "result_id": result_id,
        "source_result_id": source_result_id,
        "source_task_id": source_task_id,
        "source_feature_key": source_feature_key,
        "result_path": str(path),
        "result_sha": actual_sha,
        **decoded,
        "output_center_visible": True,
        "can_continue": bool(item.get("continue_eligible")),
        "output_center_item_id": item["id"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--verify-result-id", default="")
    parser.add_argument("--verify-color-task-id", default="")
    parser.add_argument("--create-enhancement", action="store_true")
    args = parser.parse_args()
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    sample = args.sample.resolve()
    runtime_root = args.runtime_root.resolve()
    compression_output_root = runtime_root / "输出" / "图片压缩"
    color_output_root = runtime_root / "输出"
    source_sha_before = sha256(sample)

    with httpx.Client(base_url=args.base_url, timeout=180.0) as client:
        capabilities = data(client.get("/api/local-retouch/capabilities"))
        if not capabilities.get("available"):
            raise AssertionError(f"formal Retouch engine unavailable: {capabilities}")
        if args.create_enhancement:
            enhancement_root = runtime_root / "输出" / "1080P画质"
            with sample.open("rb") as stream:
                upload = client.post(
                    "/api/upload",
                    data={
                        "mode": "fidelity",
                        "output_profile": "delivery_1080p",
                        "output_format": "png",
                        "output_dir": str(enhancement_root),
                    },
                    files={"file": (sample.name, stream, "image/png")},
                )
            upload.raise_for_status()
            upload_payload = upload.json()
            task_id = upload_payload.get("task_id") or (upload_payload.get("data") or {}).get("task_id")
            if not task_id:
                raise AssertionError(f"enhancement task id missing: {upload_payload}")
            task = None
            for _ in range(240):
                task = data(client.get(f"/api/v1/tasks/{task_id}"))
                if task.get("task_status") in {"completed", "failed"}:
                    break
                time.sleep(0.5)
            if not task or task.get("task_status") != "completed" or not task.get("result_id"):
                raise AssertionError(f"enhancement did not complete: {task}")
            items = find_output_items(client)
            item = next((entry for entry in items if entry.get("result_id") == task["result_id"]), None)
            if item is None:
                raise AssertionError("enhancement Result not visible in Output Center")
            processors = data(client.get(
                f"/api/output-center/items/{item['id']}/continue-eligibility"
            ))["processors"]
            enhancement = next(entry for entry in processors if entry["key"] == "image_enhancement")
            if enhancement["history_status"] != "PROCESSED" or enhancement["status"] != "UNAVAILABLE":
                raise AssertionError(f"enhancement repeat policy mismatch: {enhancement}")
            enhancement_report = {"task": task, "item": item, "processors": processors}
            enhancement_path = args.evidence_dir / "enhancement-repeat-result.json"
            enhancement_path.write_text(json.dumps(enhancement_report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"report": str(enhancement_path), **enhancement_report}, ensure_ascii=False, indent=2))
            return 0
        if args.verify_result_id:
            output_items = find_output_items(client)
            item = next((entry for entry in output_items if entry.get("result_id") == args.verify_result_id), None)
            if item is None:
                raise AssertionError("expected Result did not recover after restart")
            eligibility = data(client.get(
                f"/api/output-center/items/{item['id']}/continue-eligibility"
            ))["processors"]
            color_task = data(client.get(f"/api/v1/tasks/{args.verify_color_task_id}")) if args.verify_color_task_id else None
            if color_task and (
                color_task.get("result_action") != "ACCEPT_ORIGINAL"
                or color_task.get("result") is not None
                or color_task.get("result_id")
            ):
                raise AssertionError("ACCEPT_ORIGINAL no-Result contract did not survive restart")
            restart_report = {
                "recovered_after_restart": True,
                "result_id": args.verify_result_id,
                "output_center_item_id": item["id"],
                "continue_eligible": item["continue_eligible"],
                "processors": eligibility,
                "accept_original_task": color_task,
            }
            restart_path = args.evidence_dir / "restart-verification.json"
            restart_path.write_text(json.dumps(restart_report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"report": str(restart_path), **restart_report}, ensure_ascii=False, indent=2))
            return 0

        with sample.open("rb") as stream:
            intake_a = data(client.post(
                "/api/image-compression/intake",
                files={"file": (sample.name, stream, "image/png")},
            ))
        run_a = data(client.post("/api/image-compression/run", json={
            "source_token": intake_a["source_token"],
            "operation_mode": "RESIZE_REDUCTION",
            "params": {"target_short_side": 480},
            "current_task_output_root": str(compression_output_root),
        }))
        task_a = run_a["task"]
        result_a = run_a["result"]
        result_a_id = task_a["result_id"]
        path_a = Path(result_a["output_path"]).resolve()

        intake_b = data(client.post("/api/local-retouch/intake-result", json={"result_id": result_a_id}))
        width = int(intake_b["width"])
        height = int(intake_b["height"])
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).ellipse(
            (int(width * 0.70), int(height * 0.68), int(width * 0.88), int(height * 0.79)),
            fill=255,
        )
        mask_stream = io.BytesIO()
        mask.save(mask_stream, format="PNG")
        mask_data = "data:image/png;base64," + base64.b64encode(mask_stream.getvalue()).decode("ascii")
        process_b = data(client.post(
            f"/api/local-retouch/sessions/{intake_b['session_id']}/process",
            json={"mask_png_base64": mask_data, "mask_revision": 1},
        ))
        if process_b.get("engine_id") != "lama_onnx_2025jan":
            raise AssertionError(f"unexpected Retouch engine: {process_b.get('engine_id')}")
        data(client.post(
            f"/api/local-retouch/sessions/{intake_b['session_id']}/confirm",
            json={"mask_revision": process_b["mask_revision"]},
        ))
        save_b = data(client.post(f"/api/local-retouch/sessions/{intake_b['session_id']}/save", json={}))
        task_b_record = data(client.get(f"/api/v1/tasks/{save_b['task_id']}"))
        path_b = Path(task_b_record["result_file"]).resolve()

        intake_c = data(client.post("/api/image-compression/intake-result", json={"result_id": save_b["result_id"]}))
        run_c = data(client.post("/api/image-compression/run", json={
            "source_token": intake_c["source_token"],
            "operation_mode": "RESIZE_REDUCTION",
            "params": {"target_short_side": 400},
            "current_task_output_root": str(compression_output_root),
        }))
        task_c = run_c["task"]
        result_c = run_c["result"]
        result_c_id = task_c["result_id"]
        path_c = Path(result_c["output_path"]).resolve()

        watermark_d = data(client.post(
            "/api/batch-watermark/batches",
            data={
                "result_ids_json": json.dumps([result_c_id]),
                "spec_json": json.dumps({"kind": "text", "text": "S60 REAL"}, ensure_ascii=False),
            },
        ))
        result_d = watermark_d["items"][0]
        path_d = Path(result_d["output_path"]).resolve()

        color_first = data(client.post(
            "/api/color-correction/intake-result", json={"result_id": result_a_id}
        ))
        color_first_run = data(client.post(
            "/api/color-correction/run", json={
                "source_token": color_first["source_token"],
                "current_task_output_root": str(color_output_root),
            }
        ))
        first_decision = color_first_run.get("decision") or color_first_run.get("result") or {}
        legal_color_source_result_id = (
            (color_first_run.get("result") or {}).get("result_id") or result_a_id
        )
        color_second = data(client.post(
            "/api/color-correction/intake-result", json={"result_id": legal_color_source_result_id}
        ))
        color_second_run = data(client.post(
            "/api/color-correction/run", json={
                "source_token": color_second["source_token"],
                "current_task_output_root": str(color_output_root),
            }
        ))
        second_decision = color_second_run.get("decision") or color_second_run.get("result") or {}

        output_items = find_output_items(client)
        facts = [
            result_fact(
                name="A", task_id=task_a["task_id"], result_id=result_a_id,
                source_result_id=str(task_a.get("source_result_id") or ""),
                source_task_id=str(task_a.get("source_task_id") or ""),
                source_feature_key=str(task_a.get("source_feature_key") or ""),
                path=path_a, registered_sha=result_a["output_sha256"], output_items=output_items,
            ),
            result_fact(
                name="B", task_id=save_b["task_id"], result_id=save_b["result_id"],
                source_result_id=save_b["source_result_id"], source_task_id=save_b["source_task_id"],
                source_feature_key=save_b["source_feature_key"], path=path_b,
                registered_sha=task_b_record["task_result"]["output_sha256"], output_items=output_items,
            ),
            result_fact(
                name="C", task_id=task_c["task_id"], result_id=result_c_id,
                source_result_id=task_c["source_result_id"], source_task_id=task_c["source_task_id"],
                source_feature_key=task_c["source_feature_key"], path=path_c,
                registered_sha=result_c["output_sha256"], output_items=output_items,
            ),
            result_fact(
                name="D", task_id=watermark_d["batch_id"], result_id=result_d["result_id"],
                source_result_id=result_d["source_result_id"], source_task_id=result_d["source_task_id"],
                source_feature_key=result_d["source_feature_key"], path=path_d,
                registered_sha=result_d["output_sha256"], output_items=output_items,
            ),
        ]
        if len({fact["task_id"] for fact in facts}) != 4 or len({fact["result_id"] for fact in facts}) != 4:
            raise AssertionError("multi-round Task/Result identity is not unique")
        if len({fact["result_path"] for fact in facts}) != 4:
            raise AssertionError("multi-round output path was overwritten")
        if sha256(sample) != source_sha_before:
            raise AssertionError("real source sample was modified")
        if any(not fact["can_continue"] for fact in facts):
            raise AssertionError("one or more real Results cannot continue processing")

        eligibility_item = next(entry for entry in output_items if entry["result_id"] == result_d["result_id"])
        eligibility = data(client.get(
            f"/api/output-center/items/{eligibility_item['id']}/continue-eligibility"
        ))["processors"]
        eligibility_by_key = {entry["key"]: entry for entry in eligibility}

        report = {
            "runtime": {"base_url": args.base_url, "retouch_capabilities": capabilities},
            "sample": {"path": str(sample), "sha256_before": source_sha_before, "sha256_after": sha256(sample), **decode(sample)},
            "mask": {"width": width, "height": height, "selected_pixels": sum(mask.histogram()[128:]), "real_selection": True},
            "chain": facts,
            "repeat_policy_after_d": eligibility_by_key,
            "color_repeat": {
                "first_task_id": color_first_run["task"]["task_id"],
                "first_action": first_decision.get("result_action"),
                "first_result_id": (color_first_run.get("result") or {}).get("result_id") or None,
                "first_result_is_none": color_first_run.get("result") is None,
                "legal_source_result_id_for_second_run": legal_color_source_result_id,
                "second_task_id": color_second_run["task"]["task_id"],
                "second_action": second_decision.get("result_action"),
                "second_result_id": (color_second_run.get("result") or {}).get("result_id") or None,
                "second_result_is_none": color_second_run.get("result") is None,
                "repeat_intake_source_result_id": color_second["source_result_id"],
            },
            "output_center_result_ids": [entry.get("result_id") for entry in output_items if entry.get("result_id")],
        }
        report_path = args.evidence_dir / "real-multi-round.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(report_path), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
