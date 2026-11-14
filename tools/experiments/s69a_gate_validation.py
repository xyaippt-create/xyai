"""S69-A gate validation: frozen S64 measurement (git HEAD) vs the current level_pick.

Ground truth = clean image + known synthetic cast / midtone cast / haze, so the distance of the
strong level to the true colour is measurable. TUNE images set constants; HOLDOUT only scores.
Read-only on samples. Evidence: artifacts/s69_color_full_scan/s69a_gates.json
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
from PIL import Image

from engine.color_correction import level_pick as new
from engine.color_correction.level_pick import _adaptation_matrix, _gamut_pull, _lab, _to_linear, _to_srgb, delta_e2000

OUT = REPO / "artifacts" / "s69_color_full_scan"
AI4K, AIC = Path(r"D:\HDDE样本\AI4K"), Path(r"D:\HDDE样本\AIColor")
TUNE = {
    "S03_fashion": AI4K / "ChatGPT Image 2026年6月28日 16_05_17.png",
    "S04_ink": AI4K / "ChatGPT Image 2026年6月28日 16_54_53.png",
    "S05_tsingtao": AI4K / "ChatGPT Image 2026年6月30日 12_20_14.png",
    "S07_orange": AI4K / "ChatGPT Image 2026年9月12日 13_08_42.png",
    "S08_sky": AI4K / "ChatGPT Image 2026年9月12日 13_12_46.png",
    "S11_nvidia": AIC / "ChatGPT Image 2026年7月1日 12_19_04 (1).png",
    "S13_huawei": AIC / "ChatGPT Image 2026年7月8日 10_02_36.png",
    "S14_oppo": AIC / "ChatGPT Image 2026年7月8日 10_05_23.png",
}
HOLDOUT = {
    "C01_meeting": Path(r"D:\HDDE样本\AIColorControl\真实照片_会议室_颜色正常.jpg"),
    "S01_flower": AI4K / "2.png",
    "S09_flower": AI4K / "ChatGPT Image 2026年9月13日 13_59_42.png",
}
VISIBLE_CAST_DE = 4.0
DESIGN_TONE_TEMP = ["S03_fashion", "S08_sky", "C01_meeting"]  # temporary gate 5 samples
CASTS = {"yellow8": ((0.0, 8.0), "YELLOW"), "yellow14": ((0.0, 14.0), "YELLOW"), "yellow24": ((0.0, 24.0), "YELLOW"),
         "blue12": ((0.0, -12.0), "BLUE"), "green10": ((-10.0, 0.0), "TINT"), "magenta8": ((8.0, 0.0), "TINT")}


def frozen_module() -> types.ModuleType:
    src = subprocess.run(["git", "show", "HEAD:engine/color_correction/level_pick.py"], cwd=REPO,
                         capture_output=True, check=True).stdout.decode("utf-8")
    src = src.replace("from .color_management import", "from engine.color_correction.color_management import")
    mod = types.ModuleType("level_pick_s64_frozen")
    sys.modules[mod.__name__] = mod  # dataclasses resolve annotations through sys.modules
    exec(compile(src, "level_pick_s64_frozen", "exec"), mod.__dict__)
    return mod


def load(path: Path) -> np.ndarray:
    im = Image.open(path).convert("RGB")
    s = 1536 / max(im.size)
    if s < 1:
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    return np.asarray(im).copy()


def add_cast(rgb, ab):
    lin = _to_linear(rgb.astype(np.float32) / 255.0) @ _adaptation_matrix((0.0, 0.0), ab).T
    return (np.clip(_to_srgb(_gamut_pull(lin)), 0, 1) * 255 + 0.5).astype(np.uint8)


def add_midtone_cast(rgb, ab):
    lin = _to_linear(rgb.astype(np.float32) / 255.0)
    cast = np.clip(lin @ _adaptation_matrix((0.0, 0.0), ab).T, 0, 1)
    w = np.clip(1 - np.abs(_lab(rgb)[..., 0:1] / 100.0 - 0.5) / 0.45, 0, 1)
    return (np.clip(_to_srgb(lin + w * (cast - lin)), 0, 1) * 255 + 0.5).astype(np.uint8)


def add_haze(rgb, amt=0.12):
    return ((rgb.astype(np.float32) / 255.0 * (1 - amt) + amt * 0.55) * 255 + 0.5).astype(np.uint8)


def mde(a, b) -> float:
    return round(float(delta_e2000(a, b).mean()), 3)


def colour_tag(category: str) -> str | None:
    return next((t for t in category.split("+") if t in ("YELLOW", "BLUE", "TINT")), None)


def evaluate(mod, img, truth):
    t0 = time.perf_counter()
    an = mod.analyze_level_pick(img)
    seconds = time.perf_counter() - t0
    strong = mod.render_level(img, an, "strong")
    return {"category": an.category, "offset": an.measured_offset, "recommended": an.recommended_level,
            "hints": list(an.intent_hints), "seconds": round(seconds, 3),
            "strong_de": mde(strong, truth), "strong_safe": mod.level_safety(img, strong, an)["passed"],
            "cast": getattr(an, "cast", None)}


def main() -> int:
    old_mod = frozen_module()
    rows = []
    for group, srcs in (("TUNE", TUNE), ("HOLDOUT", HOLDOUT)):
        for name, path in srcs.items():
            clean = load(path)
            cases = [("clean", "CLEAN", clean, None)]
            cases += [(c, "GT", add_cast(clean, ab), tag) for c, (ab, tag) in CASTS.items()]
            cases += [("mid_yellow14", "GT_MID", add_midtone_cast(clean, (0.0, 14.0)), "YELLOW"),
                      ("haze", "GT_HAZE", add_haze(clean), None)]
            for cast, kind, img, truth_tag in cases:
                row = {"case": f"{name}__{cast}", "image": name, "group": group, "kind": kind, "truth_tag": truth_tag,
                       "cast_de": mde(img, clean), "old": evaluate(old_mod, img, clean), "new": evaluate(new, img, clean)}
                rows.append(row)
            print(name, "done", flush=True)
    summary = {g: gates([r for r in rows if r["group"] in sel]) for g, sel in
               (("TUNE", ("TUNE",)), ("HOLDOUT", ("HOLDOUT",)), ("ALL", ("TUNE", "HOLDOUT")))}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "s69a_gates.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


def gates(rows):
    out = {}
    every_gt = [r for r in rows if r["kind"] == "GT"]
    # Gate ruling 2026-11-14: gates 1 and 2 score only clearly visible casts (mean dE00 >= 4).
    gt = [r for r in every_gt if r["cast_de"] >= VISIBLE_CAST_DE]
    small = [r for r in every_gt if r["cast_de"] < VISIBLE_CAST_DE]
    for side in ("old", "new"):
        red = [1 - r[side]["strong_de"] / r["cast_de"] for r in gt]
        small_red = [1 - r[side]["strong_de"] / r["cast_de"] for r in small]
        wrong = [r["case"] for r in gt + [x for x in rows if x["kind"] == "GT_MID"]
                 if colour_tag(r[side]["category"]) not in (None, r["truth_tag"])]
        clean = [r for r in rows if r["kind"] == "CLEAN"]
        haze = [r for r in rows if r["kind"] == "GT_HAZE"]
        out[side] = {
            "visible_cases": len(gt),
            "g1b_visible_recommended_correction": sum(r[side]["recommended"] != "original" for r in gt),
            "small_cases": len(small),
            "small_recommended_correction": [r["case"] for r in small if r[side]["recommended"] != "original"],
            "small_strong_reduction_median": round(float(np.median(small_red)), 3) if small_red else None,
            "small_worse_than_cast": [r["case"] for r, x in zip(small, small_red) if x < 0],
            "g1_strong_reduction_median": round(float(np.median(red)), 3) if red else None,
            "g2_worse_than_cast": [r["case"] for r, x in zip(gt, red) if x < 0],
            "g3_wrong_direction": wrong,
            "g4_clean_recommended_correction": [r["case"] for r in clean if r[side]["recommended"] != "original"],
            "g5_design_tone_temp": {r["case"]: r[side]["recommended"] for r in clean if r["image"] in DESIGN_TONE_TEMP},
            "haze_strong_de": {r["case"]: r[side]["strong_de"] for r in haze},
            "mid_worse_than_cast": [r["case"] for r in rows if r["kind"] == "GT_MID" and r[side]["strong_de"] > r["cast_de"]],
            "unsafe_strong": [r["case"] for r in rows if not r[side]["strong_safe"]],
            "max_seconds": max(r[side]["seconds"] for r in rows),
        }
    out["g6_haze_worse_than_old"] = [r["case"] for r in rows if r["kind"] == "GT_HAZE"
                                     and r["new"]["strong_de"] > r["old"]["strong_de"] + 0.05]
    out["g7_extra_seconds_median"] = round(float(np.median([r["new"]["seconds"] - r["old"]["seconds"] for r in rows])), 3)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
