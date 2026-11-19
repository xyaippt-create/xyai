"""Real-engine API/file validation; never substitutes for UI or owner sign-off."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageOps

from backend.image_compression_api import register_image_compression_routes
from backend.local_retouch_api import register_local_retouch_routes
from engine.output.metadata_writer import _dpi_equal, _read_effective_dpi
from engine.storage.shared_task_registry import SharedTaskRegistry


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("sources", nargs=3, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--existing-task-ids", nargs=3)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    evidence = args.evidence_dir.resolve()
    if not evidence.is_relative_to(repo / "output"):
        raise ValueError("Evidence must stay in repository output")
    evidence.mkdir(parents=True, exist_ok=True)
    report_path = evidence / "real-validation.json"
    if report_path.exists():
        raise FileExistsError(report_path)
    settings_path = repo / "settings/settings.json"
    settings_before = sha(settings_path)
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    formal = Path(settings["app_data_root"]).resolve(strict=True)
    originals = {str(source.resolve()): sha(source) for source in args.sources}
    dims = []
    for source in args.sources:
        with Image.open(source) as opened:
            dims.append(ImageOps.exif_transpose(opened).size)
    if len(set(dims)) != 1:
        raise ValueError("Sources must have identical orientation-normalized geometry")
    width, height = dims[0]
    # Absolute-pixel rectangles, brush and final erasure. No resize/crop of inputs.
    mask = Image.new("RGBA", dims[0])
    draw = ImageDraw.Draw(mask)
    draw.rectangle((3000, 4700, 3099, 4769), fill="white")
    draw.rectangle((3200, 4850, 3289, 4909), fill="white")
    draw.line((3010, 4950, 3100, 4990, 3180, 4950), fill="white", width=30)
    draw.rectangle((3040, 4710, 3060, 4730), fill=(0, 0, 0, 0))
    if width < 3300 or height < 5010:
        raise ValueError("This fixed real-photo mask needs at least 3300 by 5010 pixels")
    mask.save(evidence / "mask.png")
    stream = io.BytesIO()
    mask.save(stream, "PNG")
    frozen = {"mask_revision": 1, "mask_png_base64": base64.b64encode(stream.getvalue()).decode()}
    registry = SharedTaskRegistry(formal)
    app = FastAPI()
    dirs = {"directory_ready": True, "app_data_root": formal, "tmp_dir": formal / "输出/图片压缩/.运行缓存"}
    state = register_local_retouch_routes(app, user_dirs_provider=lambda: dirs, shared_task_registry=registry)
    rows = []
    report = {"scope": "IN_PROCESS_REAL_API_ENGINE_FORMAL_FILES_AND_REGISTRY", "ui": "NOT_VERIFIED", "owner_review": "PENDING", "sources_before": originals, "formal_root": str(formal)}
    started = time.monotonic()
    with TestClient(app) as client:
        # Only read Output Center here; do not start unrelated compression recovery workers.
        # Its read routes run unchanged against the real shared registry and formal files.
        register_image_compression_routes(app, user_dirs_provider=lambda: dirs, shared_task_registry=registry)
        def data(response):
            if response.status_code != 200:
                raise RuntimeError(f"{response.status_code}: {response.text}")
            return response.json()["data"]
        batch = data(client.post("/api/local-retouch/batches")) if not args.existing_task_ids else None
        if not args.existing_task_ids:
            url = f"/api/local-retouch/batches/{batch['batch_id']}"
            for index, source in enumerate(args.sources):
                batch = data(client.post(url + "/items", files={"file": (f"验收_同位置批量_20261104_{index + 1}_{source.name}", source.read_bytes(), "image/jpeg")}))
                print("imported", source.name, flush=True)
            assert batch["total"] == 3
            assert (batch["width"], batch["height"]) == dims[0]
            preview = data(client.post(url + "/preview", json=frozen | {"item_id": batch["items"][0]["item_id"]}))
            assert not preview["items"][0]["preview"]["confirmed"]
            data(client.post(url + "/start", json=frozen))
            deadline = time.monotonic() + 240
            while True:
                batch = data(client.get(url))
                if not batch["busy"]:
                    break
                if time.monotonic() > deadline:
                    client.post(url + "/cancel")
                    raise TimeoutError("Real batch exceeded validation deadline; cancellation requested")
                time.sleep(.1)
            assert [item["status"] for item in batch["items"]] == ["candidate"] * 3
            ids = [item["candidate"]["task_id"] for item in batch["items"]]
            assert len(set(ids)) == 3
            assert all(not registry[task_id].get("result_id") for task_id in ids)
            selections = [{"item_id": item["item_id"], "session_id": item["candidate"]["session_id"]} for item in batch["items"]]
            stale = client.post(url + "/confirm-save", json=frozen | {"mask_revision": 2, "items": selections})
            assert stale.status_code == 409
            before_save = data(client.get("/api/output-center/items", params={"query": "验收_同位置批量_20261104", "limit": 100}))
            assert not any(item.get("task_id") in ids for item in before_save["items"])
            # Explicit API acceptance actions test the same user-confirm/save contract.
            # These validation actions do not represent the product owner's visual sign-off.
            batch = data(client.post(url + "/confirm-save", json=frozen | {"items": selections}))
            assert [item["status"] for item in batch["items"]] == ["saved"] * 3
        else:
            records = [registry[task_id] for task_id in args.existing_task_ids]
            assert all(record['source_sha256'] == sha(source) for record, source in zip(records, args.sources))
            assert len({record['batch_id'] for record in records}) == 1
            assert len({record['batch_item_id'] for record in records}) == 3
            ids = list(args.existing_task_ids)
            batch = {'batch_id': records[0]['batch_id'], 'items': [
                {'candidate': {'task_id': record['task_id']}} for record in records]}
            report['api_execution_note'] = 'Validate explicitly supplied persisted task identities; no repeat processing or repeat publication'
        overview = Image.new("RGB", (1200, 330), "#202020")
        native = Image.new("RGB", (1200, 1440), "#202020")
        inside = np.asarray(mask.getchannel("A")) >= 128
        for index, item in enumerate(batch["items"]):
            record = registry[item["candidate"]["task_id"]]
            result = record["result"]
            path = Path(result["output_path"])
            with Image.open(args.sources[index]) as source, Image.open(path) as output:
                normal = ImageOps.exif_transpose(source).convert("RGB")
                output.load()
                assert output.size == normal.size == dims[0]
                assert output.getexif().get(274, 1) == 1
                assert _dpi_equal(_read_effective_dpi(args.sources[index].read_bytes()), _read_effective_dpi(path.read_bytes()))
                a, b = np.asarray(normal), np.asarray(output.convert("RGB"))
                outside_changed = 0
                inside_changed = 0
                for y in range(0, height, 128):
                    changed = np.any(a[y:y + 128] != b[y:y + 128], axis=2)
                    outside_changed += int(np.count_nonzero(changed & ~inside[y:y + 128]))
                    inside_changed += int(np.count_nonzero(changed & inside[y:y + 128]))
                assert outside_changed == 0 and inside_changed > 0
                for col, image in enumerate((normal, output.convert("RGB"))):
                    thumb = image.copy()
                    thumb.thumbnail((190, 600))
                    overview.paste(thumb, (index * 400 + col * 200, 30))
                    native.paste(image.crop((2850, 4600, 3450, 5080)), (col * 600, index * 480))
                row = {"source_path": str(args.sources[index]), "source_id": result["source_id"], "batch_id": result["batch_id"], "batch_item_id": result["batch_item_id"], "task_id": record["task_id"], "result_id": result["result_id"], "output_path": str(path), "size_bytes": path.stat().st_size, "sha256": sha(path), "dimensions": list(output.size), "dpi": list(output.info["dpi"]), "orientation": output.getexif().get(274, 1), "alpha": "NO_ALPHA_IN_ORIGINAL", "outside_changed_pixels": outside_changed, "inside_changed_pixels": inside_changed, "mask_sha256": result["mask_sha256"]}
            assert row["sha256"] == result["output_sha256"]
            assert row["size_bytes"] == result["output_size_bytes"]
            assert record["result_review_status"] == "confirmed"
            rows.append(row)
            print("verified", path.name, "outside=0", flush=True)
        overview.save(evidence / "before-after-overview.jpg", quality=94)
        native.save(evidence / "before-after-native.png")
        center = data(client.get("/api/output-center/items", params={"query": "验收_同位置批量_20261104", "limit": 100}))
        matched = [item for item in center["items"] if item.get("result_id") in {row["result_id"] for row in rows}]
        assert len(matched) == 3
        report["output_center_matches"] = matched
        report["stale_save_http"] = stale.status_code if not args.existing_task_ids else "COVERED_BY_DIRECT_REGRESSION"
        report["batch_id"] = batch["batch_id"]
        reloaded = SharedTaskRegistry(formal)
        assert all(reloaded[row["task_id"]]["result"]["output_sha256"] == row["sha256"] for row in rows)
        assert all(reloaded[row["task_id"]]["result"]["batch_id"] == report["batch_id"] for row in rows)
        cancel_batch = data(client.post("/api/local-retouch/batches"))
        cancel_url = f"/api/local-retouch/batches/{cancel_batch['batch_id']}"
        for index, source in enumerate(args.sources):
            data(client.post(cancel_url + "/items", files={"file": (f"验收_取消_{index + 1}.jpg", source.read_bytes(), "image/jpeg")}))
        data(client.post(cancel_url + "/start", json=frozen))
        cancel_started = time.monotonic()
        data(client.post(cancel_url + "/cancel"))
        cancel_response_seconds = time.monotonic() - cancel_started
        deadline = time.monotonic() + 120
        while True:
            cancelled = data(client.get(cancel_url))
            if not cancelled["busy"]:
                break
            if time.monotonic() > deadline:
                raise TimeoutError("Current image did not finish after cancellation")
            time.sleep(.1)
        statuses = [item["status"] for item in cancelled["items"]]
        assert statuses == ["candidate", "cancelled", "cancelled"], statuses
        assert all(not (item.get("candidate") or {}).get("result_id") for item in cancelled["items"])
        report["cancellation"] = {"batch_id": cancelled["batch_id"], "statuses": statuses, "response_seconds": round(cancel_response_seconds, 3), "completed_candidate_preserved": True, "formal_results": 0}
    report.update(rows=rows, elapsed_seconds=round(time.monotonic() - started, 3), source_hashes_unchanged=all(sha(path) == digest for path, digest in originals.items()), settings_hash_unchanged=sha(settings_path) == settings_before)
    assert report["source_hashes_unchanged"] and report["settings_hash_unchanged"]
    assert len({row["mask_sha256"] for row in rows}) == 1
    report["technical_file_validation"] = "PASS"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("Evidence:", report_path, flush=True)


if __name__ == "__main__":
    main()
