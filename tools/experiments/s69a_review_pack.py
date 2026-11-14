"""S69-A review pack: frozen S64 measurement (git HEAD) vs the current level_pick on real samples.

One sheet per image: original | old recommended | new recommended | old strong | new strong.
Read-only on samples. Output: artifacts/s69_color_full_scan/s69a_review_pack/
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools" / "experiments"))

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import s69a_gate_validation as gv
from engine.color_correction import level_pick as new

OUT = REPO / "artifacts" / "s69_color_full_scan" / "s69a_review_pack"
TILE = 720
LABELS = {"original": "原图", "light": "轻", "medium": "中", "strong": "强"}


def tile(rgb: np.ndarray, caption: str, font) -> Image.Image:
    im = Image.fromarray(rgb)
    im.thumbnail((TILE, TILE), Image.LANCZOS)
    sheet = Image.new("RGB", (TILE, TILE + 56), "white")
    sheet.paste(im, ((TILE - im.width) // 2, (TILE - im.height) // 2))
    ImageDraw.Draw(sheet).text((12, TILE + 12), caption, fill="black", font=font)
    return sheet


def render(mod, img, analysis, level):
    return img if level == "original" else mod.render_level(img, analysis, level)


def main() -> int:
    old = gv.frozen_module()
    clean = {p.resolve() for p in gv.TUNE.values()}  # the two holdout flower images stay in the pack
    paths = [Path(p) for p in sorted(glob.glob(str(gv.AIC / "*.png"))) + sorted(glob.glob(str(gv.AI4K / "*.png")))]
    paths = [p for p in paths if p.resolve() not in clean]
    font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 24)
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, path in enumerate(paths, 1):
        img = gv.load(path)
        a_old, a_new = old.analyze_level_pick(img), new.analyze_level_pick(img)
        tiles = [tile(img, "原图", font)]
        row = {"sheet": f"R{index:02d}.jpg", "source": str(path)}
        for side, mod, an in (("old", old, a_old), ("new", new, a_new)):
            safety = {lv: mod.level_safety(img, mod.render_level(img, an, lv), an)["passed"] for lv in new.LEVELS}
            row[side] = {"category": an.category, "measured_offset": an.measured_offset, "recommended": an.recommended_level,
                         "hints": list(an.intent_hints), "levels_safe": safety}
        for side, mod, an, name in (("old", old, a_old, "旧"), ("new", new, a_new, "新")):
            tiles.append(tile(render(mod, img, an, an.recommended_level), f"{name}·建议：{LABELS[an.recommended_level]}", font))
        for side, mod, an, name in (("old", old, a_old, "旧"), ("new", new, a_new, "新")):
            tiles.append(tile(mod.render_level(img, an, "strong"), f"{name}·强档" + ("" if row[side]["levels_safe"]["strong"] else "（安全检查未过，不提供）"), font))
        sheet = Image.new("RGB", (TILE * len(tiles), TILE + 56), "white")
        for i, t in enumerate(tiles):
            sheet.paste(t, (i * TILE, 0))
        sheet.save(OUT / row["sheet"], quality=92)
        rows.append(row)
        print(row["sheet"], path.name, row["old"]["recommended"], "->", row["new"]["recommended"], flush=True)
    (OUT / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
