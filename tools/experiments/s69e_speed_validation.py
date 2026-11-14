"""S69-E: time the real level-pick / reference API on 3840x2160 PNG input and fingerprint the pixels.

Run once before and once after the change with a label; compare with --compare.
Uses the API test harness (real routes, temporary formal directory). Samples are read-only.
Evidence: artifacts/s69_color_full_scan/s69e_speed_<label>.json
"""
from __future__ import annotations

import hashlib
import io
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
from PIL import Image

from tests.image_compression_ui.test_level_pick_color_api import LevelPickApiTests

OUT = REPO / "artifacts" / "s69_color_full_scan"
TARGET = Path(r"D:\HDDE样本\AI4K\ChatGPT Image 2026年9月12日 13_08_42.png")
REFERENCE = Path(r"D:\HDDE样本\AI4K\ChatGPT Image 2026年9月12日 13_12_46.png")
ROUNDS = 3


def png_4k(path: Path, cast: bool) -> bytes:
    rgb = np.asarray(Image.open(path).convert("RGB").resize((3840, 2160), Image.LANCZOS)).copy()
    if cast:  # a visible warm cast so every level differs from the source
        rgb[..., 2] = (rgb[..., 2].astype(np.float32) * 0.82).astype(np.uint8)
    stream = io.BytesIO()
    Image.fromarray(rgb).save(stream, format="PNG", compress_level=1)
    return stream.getvalue()


def pixels_sha(path: Path) -> str:
    with Image.open(path) as opened:
        return hashlib.sha256(np.asarray(opened.convert("RGBA")).tobytes()).hexdigest()


def main() -> int:
    if "--compare" in sys.argv:
        before = json.loads((OUT / "s69e_speed_before.json").read_text(encoding="utf-8"))
        after = json.loads((OUT / "s69e_speed_after.json").read_text(encoding="utf-8"))
        for mode in ("level", "reference"):
            for key in ("preview_seconds", "run_seconds"):
                b, a = before[mode][key + "_median"], after[mode][key + "_median"]
                print(f"{mode:9s} {key:16s} {b:6.2f}s -> {a:6.2f}s  ({(1 - a / b) * 100:+.0f}% faster)")
            same = before[mode]["preview_pixel_sha256"] == after[mode]["preview_pixel_sha256"] and before[mode]["result_pixel_sha256"] == after[mode]["result_pixel_sha256"]
            print(f"{mode:9s} pixels identical: {same}; result bytes {before[mode]['result_bytes']} -> {after[mode]['result_bytes']}"
                  f" ({(after[mode]['result_bytes'] / before[mode]['result_bytes'] - 1) * 100:+.1f}%)")
        return 0
    label = sys.argv[1]
    target, reference = png_4k(TARGET, True), png_4k(REFERENCE, False)
    report = {}
    for mode in ("level", "reference"):
        previews, runs, row = [], [], {}
        for _ in range(ROUNDS):
            case = LevelPickApiTests("test_capabilities_announce_level_pick")
            case.setUp()
            try:
                source = case.intake_bytes(target, "target.png")
                payload = {"source_token": source["source_token"]}
                if mode == "reference":
                    payload["reference_source_token"] = case.intake_bytes(reference, "reference.png")["source_token"]
                started = time.perf_counter()
                response = case.client.post("/api/color-correction/level-preview", json=payload)
                previews.append(time.perf_counter() - started)
                assert response.status_code == 200, response.text
                data = response.json()["data"]
                session = case.state["color_level_preview_sessions"][data["preview_id"]]
                row["preview_pixel_sha256"] = {name: item["pixel_sha256"] for name, item in session["levels"].items()}
                started = time.perf_counter()
                run = case.run_level(data, "medium")
                runs.append(time.perf_counter() - started)
                assert run.status_code == 200, run.text
                output = Path(run.json()["data"]["result"]["output_path"])
                row["result_pixel_sha256"] = pixels_sha(output)
                row["result_bytes"] = output.stat().st_size
                with Image.open(output) as written:
                    row["result_format"] = [written.format, written.mode, bool(written.info.get("icc_profile"))]
            finally:
                case.tearDown()
        row.update({"preview_seconds": [round(v, 2) for v in previews], "run_seconds": [round(v, 2) for v in runs],
                    "preview_seconds_median": round(statistics.median(previews), 2), "run_seconds_median": round(statistics.median(runs), 2)})
        report[mode] = row
        print(mode, row["preview_seconds"], row["run_seconds"], row["result_bytes"], flush=True)
    (OUT / f"s69e_speed_{label}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
