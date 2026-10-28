"""S66-A end-to-end validation: every S65 test group through the reference level-pick API.

Uses an isolated formal root under the system temp directory; never writes the user's
output root or D:\\影界文件. Evidence goes to artifacts/s66a_reference_level_pick/validation.json.
"""

from __future__ import annotations

import hashlib
import io
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
sys.path.insert(0, str(REPO_ROOT / "tools" / "experiments"))

from backend.image_compression_api import register_image_compression_routes  # noqa: E402
from engine.color_correction.level_pick import delta_e2000  # noqa: E402
from engine.storage.shared_task_registry import SharedTaskRegistry  # noqa: E402
from main import DEFAULT_TMP_DIR_NAME  # noqa: E402
import s65_refcolor_poc as s65  # noqa: E402

S65 = REPO_ROOT / "artifacts" / "s65_refcolor_poc"
OUT = REPO_ROOT / "artifacts" / "s66a_reference_level_pick"
SOURCES = {**s65.CLEAN, **s65.SERIES}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def case_files(case: str) -> tuple[Path, Path]:
    parts = case.split("_")
    if case.startswith("GT_"):
        name = "_".join(parts[1:3])
        return S65 / "inputs" / f"{name}_{parts[3]}.png", SOURCES[name]
    if case.startswith("SERIES_"):
        return S65 / "inputs" / f"{'_'.join(parts[1:3])}_{parts[3]}.png", SOURCES["_".join(parts[5:7])]
    if case.startswith("IDENTITY_"):
        name = case[len("IDENTITY_"):]
        return SOURCES[name], SOURCES[name]
    return {"SAMETONE_S13_ref_S14": (SOURCES["S13_huawei"], SOURCES["S14_oppo"]),
            "SAMETONE_S01_ref_S09": (SOURCES["S01_flower"], SOURCES["S09_flower"])}[case]


def main() -> int:
    rows = json.loads((S65 / "summary.json").read_text(encoding="utf-8"))["rows"]
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

        def intake(path: Path) -> dict:
            response = client.post("/api/image-compression/intake", files={"file": (path.name, path.read_bytes(), "image/png")})
            return response.json()["data"]

        results = []
        for index, row in enumerate(rows):
            case = row["case"]
            target_path, reference_path = case_files(case)
            reference_sha = sha256(reference_path)
            target, reference = intake(target_path), intake(reference_path)
            t0 = time.perf_counter()
            preview = client.post("/api/color-correction/level-preview", json={
                "source_token": target["source_token"], "reference_source_token": reference["source_token"]})
            seconds = time.perf_counter() - t0
            data = preview.json()["data"]
            served, parity = {}, {}
            for item in data["levels"][1:]:
                served[item["level"]] = np.asarray(Image.open(io.BytesIO(client.get(item["preview_url"]).content)).convert("RGB"))
                frozen = np.asarray(Image.open(S65 / "outputs" / case / f"R3_ALIGN_{item['level']}.png").convert("RGB"))
                diff = (served[item["level"]] != frozen).any(-1)
                parity[item["level"]] = {"exact": bool(not diff.any()), "differing_pixels": int(diff.sum()),
                                         "delta_e00_mean": round(float(delta_e2000(served[item["level"]], frozen).mean()), 5)}
            # rotate the chosen level so original / light / medium / strong are all exercised
            level = ("medium", "strong", "light", "original")[index % 4]
            run = client.post("/api/color-correction/level-run", json={
                "preview_id": data["preview_id"], "level": level, "current_task_output_root": str(output_root)})
            body = run.json()["data"]
            entry = {"case": case, "preview_status": preview.status_code, "seconds": round(seconds, 2),
                     "summary": data["measurement"]["summary"], "selectable": [i["selectable"] for i in data["levels"]],
                     "parity_with_s65": parity, "selected_level": level, "run_status": run.status_code,
                     "reference_unchanged": sha256(reference_path) == reference_sha}
            if level != "original":
                output = Path(body["ui"]["output_path"])
                produced = np.asarray(Image.open(output).convert("RGB"))
                entry.update({"output_matches_preview": bool(np.array_equal(produced, served[level])),
                              "mode": body["task"]["operation_mode"],
                              "authority": body["result"]["delivery_acceptance_authority"],
                              "reference_recorded": body["result"]["parameters"].get("reference_sha256") == reference_sha})
            results.append(entry)
            print(case, preview.status_code, f"{seconds:.2f}s", level, run.status_code, entry.get("output_matches_preview"), flush=True)

        items = client.get("/api/output-center/items").json()["data"]["items"]
        files = sorted(p.name for p in (output_root / "颜色校正").iterdir())
        leftover_previews = sorted(p.name for p in (cache / "color-level-preview").iterdir()) if (cache / "color-level-preview").exists() else []
        client.close()

    levels = [v for r in results for v in r["parity_with_s65"].values()]
    summary = {
        "groups": len(results),
        "previews_ok": all(r["preview_status"] == 200 for r in results),
        "s65_exact_levels": f"{sum(v['exact'] for v in levels)}/{len(levels)}",
        "s65_worst_delta_e00": max(v["delta_e00_mean"] for v in levels),
        "runs_ok": all(r["run_status"] == 200 for r in results),
        "outputs_match_preview": all(r.get("output_matches_preview", True) for r in results),
        "references_unchanged": all(r["reference_unchanged"] for r in results),
        "references_recorded": all(r.get("reference_recorded", True) for r in results),
        "output_files": len(files),
        "expected_output_files": sum(r["selected_level"] != "original" for r in results),
        "output_center_items": len(items),
        "output_center_all_deliverable": all(i["delivery_eligible"] for i in items),
        "leftover_preview_dirs": leftover_previews,
        "max_seconds": max(r["seconds"] for r in results),
        "median_seconds": sorted(r["seconds"] for r in results)[len(results) // 2],
        "samples": results,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "validation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "samples"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
