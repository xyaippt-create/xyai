"""4K v4 real-photo check (isolated): formal route (animevideov3-x3) vs the same
fusion on realesrgan-x4plus vs plain LANCZOS, on real photographs.
Reads originals read-only; writes only under artifacts/e4k_v4_poc/real_photos/.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e4k_v4_candidate_poc as poc  # noqa: E402
from e4k_v4_candidate_poc import v3 as formal  # noqa: E402

ROOT = poc.ROOT
OUT = poc.OUT / "real_photos"
PHOTOS = {
    "R1_mountain_lake": ROOT / "tests/fixtures/color_correction/d60_03r/real_mountain_lake_landscape.jpg",
    "R2_sunset": ROOT / "tests/fixtures/color_correction/d60_03r/real_sunset_landscape.jpg",
    "R3_group_meeting": poc.GOLD / "S04__real_group_meeting_04.jpg",
}
MODELS = {"animev3x3": ("realesr-animevideov3-x3", 3), "x4plus": ("realesrgan-x4plus", 4)}


def run_sr(rgb: Image.Image, key: str, name: str) -> tuple[np.ndarray, float | None]:
    cache = OUT / "cache" / f"{name}_{key}.png"
    if cache.is_file():
        return np.asarray(Image.open(cache).convert("RGB")), None
    old = formal.FOUR_K_V1_SR_MODEL, formal.FOUR_K_V1_SR_SCALE
    formal.FOUR_K_V1_SR_MODEL, formal.FOUR_K_V1_SR_SCALE = MODELS[key]
    try:
        t = time.time()
        out = formal._run_super_resolution(rgb, OUT / "cache")
        seconds = round(time.time() - t, 1)
    finally:
        formal.FOUR_K_V1_SR_MODEL, formal.FOUR_K_V1_SR_SCALE = old
    Image.fromarray(out).save(cache, compress_level=1)
    return out, seconds


def busiest_boxes(rgb: Image.Image, size: int = 200) -> dict[str, tuple[int, int, int, int]]:
    luma = np.asarray(rgb.convert("L"), dtype=np.float32)
    energy = cv2.blur(np.abs(cv2.Laplacian(luma, cv2.CV_32F)), (size, size))
    h, w = luma.shape
    half = size // 2
    energy[:half], energy[-half:], energy[:, :half], energy[:, -half:] = 0, 0, 0, 0
    y, x = np.unravel_index(int(energy.argmax()), energy.shape)
    return {
        "detail": (int(x - half), int(y - half), size, size),
        "center": (w // 2 - half, h // 2 - half, size, size),
    }


def main() -> None:
    (OUT / "cache").mkdir(parents=True, exist_ok=True)
    report = {}
    for name, path in PHOTOS.items():
        sha = formal._sha256_file(path)
        with Image.open(path) as opened:
            rgb = ImageOps.exif_transpose(opened).convert("RGB")
        plan = formal.plan_4k_v1_dimensions(rgb.width, rgb.height)
        target = (plan["target_width"], plan["target_height"])
        s = target[0] / rgb.width
        maps = formal._structure_maps(rgb, target)
        lz = np.asarray(rgb.resize(target, Image.Resampling.LANCZOS))
        results = {"LANCZOS": lz}
        entry = {"source_size": [rgb.width, rgb.height], "target": list(target)}
        for key in MODELS:
            sr, seconds = run_sr(rgb, key, name)
            results[key] = formal._fuse_detail(sr, rgb, target, maps)
            m = poc.metrics(results[key], lz, np.asarray(rgb), maps[0], maps[2], s)
            m["sr_seconds"] = seconds
            entry[key] = m
            print(name, key, json.dumps(m), flush=True)
        entry["source_sha_unchanged"] = formal._sha256_file(path) == sha
        for region, box in busiest_boxes(rgb).items():
            poc.panel(results, box, s, False).save(OUT / f"{name}_{region}.png")
        report[name] = entry
    (OUT / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    main()
