"""4K v4 strength check (isolated): frozen v4 vs a stronger candidate level on all PoC
samples, real photos and the owner's flower image. Same SR model (animevideov3-x3).
Reads originals read-only; writes only under artifacts/e4k_v4_poc/strength/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e4k_v4_candidate_poc as poc  # noqa: E402
from e4k_v4_candidate_poc import v3 as formal  # noqa: E402

OUT = poc.OUT / "strength"
ROOT = poc.ROOT
FROZEN = dict(poc.PARAMS["v4b"], mid_sr_cap=0.25)
LEVELS = {
    "v4 (frozen)": FROZEN,
    "stronger": dict(FROZEN, mid_gain=3.0, struct_gain=1.35, fine_gain=1.4, clamp=0.02),
}
SAMPLES = dict(poc.SAMPLES)
SAMPLES["W1"] = (Path(r"D:/影界文件/输出/1080P画质/.输入缓存/Work.png"), {
    "stamen": (966, 372, 150, 165), "glitter": (1290, 300, 170, 170), "bokeh": (186, 186, 200, 200),
})
SAMPLES["R1"] = (ROOT / "tests/fixtures/color_correction/d60_03r/real_mountain_lake_landscape.jpg", {})
SAMPLES["R2"] = (ROOT / "tests/fixtures/color_correction/d60_03r/real_sunset_landscape.jpg", {})
SAMPLES["R3"] = (poc.GOLD / "S04__real_group_meeting_04.jpg", {})


def sr_for(name: str, rgb: Image.Image) -> np.ndarray:
    cache = OUT / "cache" / f"{name}.png"
    for known in (poc.OUT / "cache" / f"{name}_animev3x3.png", cache):
        if known.is_file():
            return np.asarray(Image.open(known).convert("RGB"))
    out = formal._run_super_resolution(rgb, OUT / "cache")
    Image.fromarray(out).save(cache, compress_level=1)
    return out


def auto_boxes(rgb: Image.Image) -> dict:
    import cv2
    luma = np.asarray(rgb.convert("L"), dtype=np.float32)
    size = 200
    energy = cv2.blur(np.abs(cv2.Laplacian(luma, cv2.CV_32F)), (size, size))
    half = size // 2
    energy[:half], energy[-half:], energy[:, :half], energy[:, -half:] = 0, 0, 0, 0
    y, x = np.unravel_index(int(energy.argmax()), energy.shape)
    return {"detail": (int(x - half), int(y - half), size, size), "center": (rgb.width // 2 - half, rgb.height // 2 - half, size, size)}


def main() -> None:
    (OUT / "cache").mkdir(parents=True, exist_ok=True)
    report = {}
    for name, (path, regions) in SAMPLES.items():
        sha = formal._sha256_file(path)
        with Image.open(path) as opened:
            rgb = ImageOps.exif_transpose(opened).convert("RGB")
        plan = formal.plan_4k_v1_dimensions(rgb.width, rgb.height)
        target = (plan["target_width"], plan["target_height"])
        s = target[0] / rgb.width
        sr = sr_for(name, rgb)
        maps = formal._structure_maps(rgb, target)
        lz = np.asarray(rgb.resize(target, Image.Resampling.LANCZOS))
        results = {"LANCZOS": lz}
        entry = {}
        for key, params in LEVELS.items():
            results[key] = poc.v4(rgb, sr, target, maps, params)
            m = poc.metrics(results[key], lz, np.asarray(rgb), maps[0], maps[2], s)
            m["png_mb"] = round(poc.png_size(results[key], OUT / "cache" / "_size.png") / 1e6, 2)
            entry[key] = m
            print(name, key, "view", m["view_sharp_ratio"], "grain", m["flat_grain"], "over%", m["overshoot_pct"],
                  "dE", m["lowband_dE76_mean"], m["lowband_dE76_p99"], "MB", m["png_mb"], flush=True)
        entry["source_sha_unchanged"] = formal._sha256_file(path) == sha
        for region, box in (regions or auto_boxes(rgb)).items():
            poc.panel(results, box, s, region.endswith("50pct")).save(OUT / f"{name}_{region}.png")
        report[name] = entry
    (OUT / "cache" / "_size.png").unlink(missing_ok=True)
    (OUT / "metrics.json").write_text(json.dumps({"levels": LEVELS, "samples": report}, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    main()
