"""4K v4 isolated candidate PoC (not wired into the product).

Compares, at the 4K target size of each sample:
  LANCZOS  - plain upscale of the original
  v3       - the frozen formal route (same internals as process_4k_v1_image)
  v4a/v4b  - candidate: relaxed low-band back-projection (A), mid-band recovery
             from SR with clamped local contrast (B), source-bounded fine band
             without texture re-injection plus skin damping (C), and SR-free
             stroke handling for tiny text (D). a = moderate, b = strong.

NOTE: the "v3" column called the pre-v4 formal fusion; after v4 was integrated on
2026-11-13 main() can no longer be re-run as is (v4() and metrics() remain valid).

Reads originals read-only; writes only under artifacts/e4k_v4_poc/.
Usage: .venv/Scripts/python.exe tools/experiments/e4k_v4_candidate_poc.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from engine.image_processing_routing import four_k_v1 as v3  # noqa: E402

OUT = ROOT / "artifacts" / "e4k_v4_poc"
GOLD = ROOT / "artifacts" / "4k_stage1_baseline" / "golden_samples"

SAMPLES = {
    "P1": (Path(r"D:/影界文件/输出/1080P画质/.输入缓存/ChatGPT Image 2026年6月28日 16_00_09.png"), {
        "face_eye": (720, 320, 200, 130), "hair": (470, 250, 180, 180), "smalltext": (130, 960, 160, 90),
        "sweater": (560, 900, 220, 180), "english": (1040, 40, 70, 250), "face_50pct": (600, 250, 480, 420),
    }),
    "S03": (GOLD / "S03__andy_lau_commercial_portrait.png", {
        "face": (480, 170, 160, 180), "hair": (470, 110, 170, 90), "smalltext": (217, 575, 175, 50),
    }),
    "S07": (GOLD / "S07__chengdu_yanhuo.png", {
        "tinytext": (70, 420, 510, 55), "buildings": (403, 876, 175, 105),
    }),
    "S01": (GOLD / "S01__jewelry_yaoshi_zhiguang.png", {
        "smalltext": (167, 335, 355, 47), "ring": (167, 650, 140, 150),
    }),
    "S05": (GOLD / "S05__dji_horizontal_infographic.png", {
        "smalltext": (1627, 155, 265, 130), "drones": (1292, 48, 190, 95),
    }),
}

PARAMS = {
    "v4a": dict(mid_sr=0.8, mid_sr_cap=0.6, mid_gain=1.6, struct_gain=1.10, fine_gain=0.8, fine_env=0.8, skin_damp=0.4,
                skin_base_fine=0.5, txt_gain=0.9, clamp=0.010, bp_sigma=2.5, bp_iter=2),
    "v4b": dict(mid_sr=0.9, mid_sr_cap=0.6, mid_gain=2.2, struct_gain=1.20, fine_gain=1.0, fine_env=1.0, skin_damp=0.4,
                skin_base_fine=0.5, txt_gain=1.2, clamp=0.012, bp_sigma=2.5, bp_iter=2),
}


def G(x: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(x, (0, 0), sigma)


def ycc(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)


def skin_mask(base_ycc: np.ndarray) -> np.ndarray:
    cr = base_ycc[..., 1] * 255.0
    cb = base_ycc[..., 2] * 255.0
    m = v3._ramp(cr, (133, 140)) * (1 - v3._ramp(cr, (170, 178))) * v3._ramp(cb, (80, 87)) * (1 - v3._ramp(cb, (128, 135)))
    return G(m.astype(np.float32), 3.0)


def v4(rgb: Image.Image, sr_x4: np.ndarray, target: tuple[int, int], maps, p: dict) -> np.ndarray:
    texture, _edge, stroke = maps
    s = target[0] / rgb.width
    base = np.asarray(rgb.resize(target, Image.Resampling.LANCZOS), dtype=np.float32) / 255.0
    sr = cv2.resize(sr_x4, target, interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    yb_all = ycc(base)
    yb = yb_all[..., 0]
    ys = v3._luma(sr)
    del sr

    sf, sm, sl = 0.5 * s, 2.0 * s, 4.0 * s
    skin = skin_mask(yb_all)
    yb_f, yb_m, ys_f, ys_m = G(yb, sf), G(yb, sm), G(ys, sf), G(ys, sm)
    yb_l = G(yb, sl)
    mid_b = yb_f - yb_m
    mid_s = ys_f - ys_m
    # B: mid band (1-4 source px, the scale that reads as sharpness at screen size) follows
    # the SR, then a mostly uniform clamped local-contrast gain; a light structure-band lift.
    # SR may only move the mid band by a fraction of the local source structure amplitude,
    # so it sharpens existing transitions but cannot draw new lines (knit, fabric).
    env_m = np.sqrt(G(mid_b * mid_b, sl)) * p["mid_sr_cap"] + 1e-4
    delta = env_m * np.tanh((mid_s - mid_b) / env_m)
    mid = mid_b + p["mid_sr"] * (1.0 - stroke) * (1.0 - 0.5 * skin) * delta
    mid *= 1.0 + (p["mid_gain"] - 1.0) * (0.6 + 0.4 * texture) * (1.0 - stroke)
    struct = (yb_m - yb_l) * (1.0 + (p["struct_gain"] - 1.0) * (1.0 - stroke))
    # C: SR fine band bounded by the local amplitude of real source structure, no texture
    # re-injection; damped on flat areas and skin (skin keeps part of the source micro-texture).
    env = np.sqrt(G(mid_b * mid_b, sm)) * p["fine_env"] + 1e-4
    fine = env * np.tanh((ys - ys_f) / env)
    fine *= p["fine_gain"] * (0.4 + 0.6 * texture) * (1.0 - p["skin_damp"] * skin) * (1.0 - stroke)
    fine += p["skin_base_fine"] * skin * (1.0 - stroke) * (yb - yb_f)
    y = yb_l + struct + mid + fine
    del mid_b, mid_s, mid, env, env_m, delta, fine, yb_f, ys_f, ys_m, struct, yb_l

    # D: tiny strokes from the clean LANCZOS base only, sharpened at stroke scale within its local range.
    k5 = np.ones((5, 5), np.uint8)
    ytxt = np.clip(yb + p["txt_gain"] * (yb - G(yb, 0.6 * s)), cv2.erode(yb, k5), cv2.dilate(yb, k5))
    y = stroke * ytxt + (1.0 - stroke) * y
    del ytxt

    # Halo clamp: stay within the local range of base and SR.
    lo = np.minimum(cv2.erode(yb, k5), cv2.erode(ys, k5)) - p["clamp"]
    hi = np.maximum(cv2.dilate(yb, k5), cv2.dilate(ys, k5)) + p["clamp"]
    y = np.clip(y, lo, hi)
    del lo, hi, ys, yb_m

    # A: relaxed back-projection - only the low band must match the original (tone/colour lock).
    y_src = v3._luma(np.asarray(rgb, dtype=np.float32) / 255.0)
    src_size = (rgb.width, rgb.height)
    for _ in range(p["bp_iter"]):
        down = cv2.resize(y, src_size, interpolation=cv2.INTER_AREA)
        res = G(y_src - down, p["bp_sigma"])
        y = y + cv2.resize(res, target, interpolation=cv2.INTER_LINEAR)

    yb_all[..., 0] = np.clip(y, 0.0, 1.0)
    out = np.clip(cv2.cvtColor(yb_all, cv2.COLOR_YCrCb2RGB), 0.0, 1.0)
    return (out * 255.0 + 0.5).astype(np.uint8)


def metrics(img: np.ndarray, lz: np.ndarray, src: np.ndarray, texture: np.ndarray, stroke: np.ndarray, s: float) -> dict:
    y = v3._luma(img.astype(np.float32) / 255.0) * 255
    yl = v3._luma(lz.astype(np.float32) / 255.0) * 255
    sf, sm = 0.45 * s, 1.5 * s

    def bands(a):
        f = a - G(a, sf)
        m = G(a, sf) - G(a, sm)
        return f, m

    f, m = bands(y)
    fl, ml = bands(yl)
    flat = (texture < 0.05) & (stroke < 0.05)
    down = cv2.resize(img, (src.shape[1], src.shape[0]), interpolation=cv2.INTER_AREA)
    lab_a = cv2.cvtColor(down.astype(np.float32) / 255, cv2.COLOR_RGB2Lab)
    lab_b = cv2.cvtColor(src.astype(np.float32) / 255, cv2.COLOR_RGB2Lab)
    de = np.sqrt(((G(lab_a, 1.2) - G(lab_b, 1.2)) ** 2).sum(-1))
    k5 = np.ones((5, 5), np.uint8)
    over = (y > cv2.dilate(yl, k5) + 5) | (y < cv2.erode(yl, k5) - 5)
    def view_sharp(a):
        h, w = a.shape
        k = 1600 / max(h, w)
        v = cv2.resize(a, (round(w * k), round(h * k)), interpolation=cv2.INTER_AREA)
        return (v - G(v, 1.0)).std()

    return {
        "view_sharp_ratio": round(float(view_sharp(y) / view_sharp(yl)), 3),
        "mid_ratio": round(float(m.std() / ml.std()), 3),
        "fine_ratio": round(float(f.std() / fl.std()), 3),
        "flat_grain": round(float(f[flat].std()), 3),
        "lowband_dE76_mean": round(float(de.mean()), 3),
        "lowband_dE76_p99": round(float(np.percentile(de, 99)), 3),
        "overshoot_pct": round(float(over.mean() * 100), 3),
    }


def png_size(img: np.ndarray, path: Path) -> int:
    Image.fromarray(img, "RGB").save(path, format="PNG", compress_level=6)
    return path.stat().st_size


def panel(images: dict[str, np.ndarray], box, k: float, half: bool) -> Image.Image:
    x, y, w, h = box
    b = tuple(int(round(v * k)) for v in (x, y, x + w, y + h))
    crops = []
    for name, img in images.items():
        c = Image.fromarray(img[b[1]:b[3], b[0]:b[2]], "RGB")
        if half:
            c = c.resize((c.width // 2, c.height // 2), Image.Resampling.LANCZOS)
        crops.append((name, c))
    cw, ch = crops[0][1].size
    vertical = cw > ch * 1.6
    gap, label = 8, 26
    if vertical:
        sheet = Image.new("RGB", (cw, (ch + label + gap) * len(crops)), "white")
    else:
        sheet = Image.new("RGB", ((cw + gap) * len(crops), ch + label), "white")
    from PIL import ImageDraw
    d = ImageDraw.Draw(sheet)
    for i, (name, c) in enumerate(crops):
        ox, oy = (0, i * (ch + label + gap)) if vertical else (i * (cw + gap), 0)
        d.text((ox + 6, oy + 6), name, fill=(0, 0, 0))
        sheet.paste(c, (ox, oy + label))
    return sheet


def main() -> None:
    (OUT / "cache").mkdir(parents=True, exist_ok=True)
    (OUT / "crops").mkdir(exist_ok=True)
    (OUT / "full").mkdir(exist_ok=True)
    report = {}
    for name, (path, regions) in SAMPLES.items():
        if not path.is_file():
            print(f"[skip] {name}: source missing {path}")
            continue
        src_sha_before = v3._sha256_file(path)
        with Image.open(path) as opened:
            rgb = ImageOps.exif_transpose(opened).convert("RGB")
        plan = v3.plan_4k_v1_dimensions(rgb.width, rgb.height)
        target = (plan["target_width"], plan["target_height"])
        cache = OUT / "cache" / f"{name}_x4plus.png"
        if cache.is_file():
            sr_x4 = np.asarray(Image.open(cache).convert("RGB"))
        else:
            t = time.time()
            sr_x4 = v3._run_super_resolution(rgb, OUT / "cache")
            Image.fromarray(sr_x4).save(cache, compress_level=1)
            print(f"{name}: SR {time.time() - t:.1f}s")
        maps = v3._structure_maps(rgb, target)
        lz = np.asarray(rgb.resize(target, Image.Resampling.LANCZOS))
        results = {"LANCZOS": lz}
        times = {}
        t = time.time()
        results["v3"] = v3._back_project(v3._fuse_detail(sr_x4, rgb, target, maps), rgb, maps[2])
        times["v3"] = round(time.time() - t, 1)
        for key, p in PARAMS.items():
            t = time.time()
            results[key] = v4(rgb, sr_x4, target, maps, p)
            times[key] = round(time.time() - t, 1)
        src = np.asarray(rgb)
        s = target[0] / rgb.width
        entry = {"source": str(path), "source_size": [rgb.width, rgb.height], "target": list(target), "methods": {}}
        for key, img in results.items():
            mtr = metrics(img, lz, src, maps[0], maps[2], s)
            mtr["png_bytes"] = png_size(img, OUT / "full" / f"{name}_{key}.png")
            mtr["fusion_seconds"] = times.get(key)
            entry["methods"][key] = mtr
        entry["source_sha_unchanged"] = v3._sha256_file(path) == src_sha_before
        for region, box in regions.items():
            panel(results, box, s, region.endswith("50pct")).save(OUT / "crops" / f"{name}_{region}.png")
        report[name] = entry
        print(name, json.dumps(entry["methods"], ensure_ascii=False))
    (OUT / "metrics.json").write_text(json.dumps({"params": PARAMS, "samples": report}, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    main()
