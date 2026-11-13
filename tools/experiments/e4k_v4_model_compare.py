"""4K v4 model comparison (isolated; not wired into the product).

Runs the three bundled Real-ESRGAN ncnn models on the PoC samples and compares
(a) the raw SR output resized to the 4K target and (b) the v4b fusion built on it.
Reads originals read-only; writes only under artifacts/e4k_v4_poc/.
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
from e4k_v4_candidate_poc import v3  # noqa: E402

MODELS = {
    "x4plus": ("realesrgan-x4plus", 4),
    "animev3x3": ("realesr-animevideov3-x3", 3),
    "x4anime": ("realesrgan-x4plus-anime", 4),
}
OUT = poc.OUT


def run_sr(rgb: Image.Image, key: str, name: str) -> tuple[np.ndarray, float | None]:
    cache = OUT / "cache" / f"{name}_{key}.png"
    if cache.is_file():
        return np.asarray(Image.open(cache).convert("RGB")), None
    model, scale = MODELS[key]
    old = v3.FOUR_K_V1_SR_MODEL, v3.FOUR_K_V1_SR_SCALE
    v3.FOUR_K_V1_SR_MODEL, v3.FOUR_K_V1_SR_SCALE = model, scale
    try:
        t = time.time()
        out = v3._run_super_resolution(rgb, OUT / "cache")
        seconds = round(time.time() - t, 1)
    finally:
        v3.FOUR_K_V1_SR_MODEL, v3.FOUR_K_V1_SR_SCALE = old
    Image.fromarray(out).save(cache, compress_level=1)
    return out, seconds


def main() -> None:
    (OUT / "crops_models").mkdir(parents=True, exist_ok=True)
    (OUT / "full").mkdir(exist_ok=True)
    report = {}
    for name, (path, regions) in poc.SAMPLES.items():
        if not path.is_file():
            print(f"[skip] {name}")
            continue
        sha = v3._sha256_file(path)
        with Image.open(path) as opened:
            rgb = ImageOps.exif_transpose(opened).convert("RGB")
        plan = v3.plan_4k_v1_dimensions(rgb.width, rgb.height)
        target = (plan["target_width"], plan["target_height"])
        s = target[0] / rgb.width
        maps = v3._structure_maps(rgb, target)
        src = np.asarray(rgb)
        lz = np.asarray(rgb.resize(target, Image.Resampling.LANCZOS))
        raw = {"LANCZOS": lz}
        fused = {"LANCZOS": lz}
        entry = {}
        for key in MODELS:
            sr, seconds = run_sr(rgb, key, name)
            raw[key] = cv2.resize(sr, target, interpolation=cv2.INTER_AREA)
            fused[key] = poc.v4(rgb, sr, target, maps, poc.PARAMS["v4b"])
            m_raw = poc.metrics(raw[key], lz, src, maps[0], maps[2], s)
            m_fused = poc.metrics(fused[key], lz, src, maps[0], maps[2], s)
            m_fused["png_bytes"] = poc.png_size(fused[key], OUT / "full" / f"{name}_v4b_{key}.png")
            entry[key] = {"sr_seconds": seconds, "raw": m_raw, "v4b": m_fused}
            print(name, key, "sr_s", seconds,
                  "| raw view", m_raw["view_sharp_ratio"], "mid", m_raw["mid_ratio"], "grain", m_raw["flat_grain"],
                  "| v4b view", m_fused["view_sharp_ratio"], "mid", m_fused["mid_ratio"], "grain", m_fused["flat_grain"],
                  "dE", m_fused["lowband_dE76_mean"], "MB", round(m_fused["png_bytes"] / 1e6, 2), flush=True)
        entry["source_sha_unchanged"] = v3._sha256_file(path) == sha
        for region, box in regions.items():
            half = region.endswith("50pct")
            poc.panel(raw, box, s, half).save(OUT / "crops_models" / f"{name}_{region}_raw.png")
            poc.panel(fused, box, s, half).save(OUT / "crops_models" / f"{name}_{region}_v4b.png")
        report[name] = entry
    (OUT / "metrics_models.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    main()
