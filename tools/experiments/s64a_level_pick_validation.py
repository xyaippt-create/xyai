"""S64-A end-to-end validation: the 15 S63 samples through the level-pick API.

Uses an isolated formal root under the system temp directory; never writes D:\\影界文件.
Writes the evidence to artifacts/s64a_level_pick/validation.json.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend.image_compression_api import register_image_compression_routes  # noqa: E402
from engine.storage.shared_task_registry import SharedTaskRegistry  # noqa: E402
from engine.color_correction.level_pick import delta_e2000  # noqa: E402
from main import DEFAULT_TMP_DIR_NAME  # noqa: E402

S63 = REPO_ROOT / "artifacts" / "s63_aicolor_poc"
OUT = REPO_ROOT / "artifacts" / "s64a_level_pick"
LEVEL_FILES = {"light": "1_light.png", "medium": "2_medium.png", "strong": "3_strong.png"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    rows = json.loads((S63 / "summary.json").read_text(encoding="utf-8"))["rows"]
    with tempfile.TemporaryDirectory() as tmp:
        formal = Path(tmp) / "formal"
        cache = formal / DEFAULT_TMP_DIR_NAME
        cache.mkdir(parents=True)
        output_root = formal / "输出"
        registry = SharedTaskRegistry(formal)
        app = FastAPI()
        register_image_compression_routes(
            app, user_dirs_provider=lambda: {"normal_output_dir": output_root, "tmp_dir": cache},
            shared_task_registry=registry, now_provider=time.time,
            output_settings_provider=lambda: {"built_in_default_root": str(formal), "saved_default_root": str(formal)},
            output_dir_validator=lambda v: {"valid": True, "writable": True, "normalized_path": str(Path(v).resolve())},
            folder_opener=lambda v: None, runtime_event_logger=lambda event, **fields: None,
        )
        client = TestClient(app)
        results = []
        # Pick per sample: the level the delegated S63 review chose, else "light"; S04 exercises "original".
        chosen = {"S01": "medium", "S02": "medium", "S09": "medium", "S04": "original"}
        for row in rows:
            sid, source = row["sample_id"], Path(row["source_path"])
            source_sha_before = sha256(source)
            intake = client.post("/api/image-compression/intake", files={"file": (source.name, source.read_bytes(), "image/png")}).json()["data"]
            t0 = time.perf_counter()
            preview = client.post("/api/color-correction/level-preview", json={"source_token": intake["source_token"]})
            preview_seconds = time.perf_counter() - t0
            data = preview.json()["data"]
            parity, served_levels = {}, {}
            for item in data["levels"][1:]:
                served = np.asarray(Image.open(__import__("io").BytesIO(client.get(item["preview_url"]).content)).convert("RGB"))
                frozen = np.asarray(Image.open(S63 / "outputs" / sid / LEVEL_FILES[item["level"]]).convert("RGB"))
                served_levels[item["level"]] = served
                diff = (served != frozen).any(-1)
                parity[item["level"]] = {
                    "exact": bool(not diff.any()), "differing_pixels": int(diff.sum()),
                    "max_abs": int(np.abs(served.astype(int) - frozen.astype(int)).max()),
                    "delta_e00_mean": round(float(delta_e2000(served, frozen).mean()), 5),
                }
            level = chosen.get(sid, "light")
            run = client.post("/api/color-correction/level-run", json={"preview_id": data["preview_id"], "level": level, "current_task_output_root": str(output_root)})
            body = run.json()["data"]
            entry = {
                "sample_id": sid, "source": source.name, "preview_status": preview.status_code,
                "preview_seconds": round(preview_seconds, 2), "server_preview_ms": data["processing_time_ms"],
                "measurement": data["measurement"], "selectable": {i["level"]: i["selectable"] for i in data["levels"]},
                "parity_with_s63": parity, "selected_level": level, "run_status": run.status_code,
                "source_unchanged": sha256(source) == source_sha_before,
            }
            if level != "original":
                output = Path(body["ui"]["output_path"])
                selected = np.asarray(Image.open(output).convert("RGB"))
                entry.update({
                    "output_name": output.name, "output_matches_preview": bool(np.array_equal(selected, served_levels[level])),
                    "output_sha_recorded": body["result"]["output_sha256"] == sha256(output),
                    "icc": bool(Image.open(output).info.get("icc_profile")),
                    "delivery_authority": body["result"]["delivery_acceptance_authority"],
                    "delivery_eligible": body["result"]["delivery_eligible"],
                })
            results.append(entry)
            print(sid, preview.status_code, f"{preview_seconds:.2f}s", level, run.status_code, entry.get("output_matches_preview"), flush=True)

        items = client.get("/api/output-center/items").json()["data"]["items"]
        files = sorted(p.name for p in (output_root / "颜色校正").iterdir())

        # Timing on a ~4K input (the S62 Lanczos 4K output of one sample).
        big = REPO_ROOT / "artifacts" / "s62_ai4k_poc" / "outputs" / "S02" / "00_lanczos_baseline.png"
        big_intake = client.post("/api/image-compression/intake", files={"file": ("big.png", big.read_bytes(), "image/png")}).json()["data"]
        t0 = time.perf_counter()
        big_preview = client.post("/api/color-correction/level-preview", json={"source_token": big_intake["source_token"]})
        big_seconds = time.perf_counter() - t0
        with Image.open(big) as opened:
            big_size = opened.size
        client.close()

    summary = {
        "samples": results,
        "all_previews_ok": all(r["preview_status"] == 200 for r in results),
        "s63_exact_levels": sum(v["exact"] for r in results for v in r["parity_with_s63"].values()),
        "s63_levels": sum(len(r["parity_with_s63"]) for r in results),
        "s63_differing_pixels": sum(v["differing_pixels"] for r in results for v in r["parity_with_s63"].values()),
        "s63_max_abs": max(v["max_abs"] for r in results for v in r["parity_with_s63"].values()),
        "s63_worst_delta_e00_mean": max(v["delta_e00_mean"] for r in results for v in r["parity_with_s63"].values()),
        "max_preview_seconds": max(r["preview_seconds"] for r in results),
        "runs_ok": all(r["run_status"] == 200 for r in results),
        "outputs_match_preview": all(r.get("output_matches_preview", True) for r in results),
        "sources_unchanged": all(r["source_unchanged"] for r in results),
        "output_files": len(files),
        "expected_output_files": sum(r["selected_level"] != "original" for r in results),
        "output_center_items": len(items),
        "output_center_all_deliverable": all(i["delivery_eligible"] for i in items),
        "four_k_input": {"size": big_size, "preview_status": big_preview.status_code, "seconds": round(big_seconds, 2)},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "validation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "samples"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
