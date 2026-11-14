"""S67-AUTOCOLOR-POC: "automatic level pick" on top of the frozen level pick (hdde.color-level-pick.v2).

Rule under test (card revision 2026-11-14): cast offset >= 10 and the three estimates agree
-> correct automatically at "light" (main) or "medium" (comparison variant); otherwise keep the
original and say why. Everything is taken from build_level_pick_preview, so each automatic result
is the level-pick render of the same level by construction. Samples are read-only.
Output: artifacts/s67_autocolor_poc/
"""
from __future__ import annotations

import glob
import hashlib
import json
import re
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools" / "experiments"))

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import s69a_gate_validation as gv
from engine.color_correction import level_pick as lp
from engine.color_correction.color_management import load_color_managed_source
from engine.color_correction.formal_runtime import run_formal_color_runtime

OUT = REPO / "artifacts" / "s67_autocolor_poc"
SHEETS = OUT / "sheets"
S65_INPUTS = REPO / "artifacts" / "s65_refcolor_poc" / "inputs"
CLEAN = {**gv.TUNE, **{k: v for k, v in gv.HOLDOUT.items() if k != "C01_meeting"}}
RULES = {"main": "light", "variant": "medium"}
VISIBLE_CAST_DE = 4.0
TILE = 640
LABELS = {"original": "保留原图", "light": "轻", "medium": "中"}


def metric_view(rgb: np.ndarray) -> np.ndarray:
    scale = min(1.0, 1536 / max(rgb.shape[:2]))
    if scale == 1.0:
        return rgb
    return cv2.resize(rgb, (round(rgb.shape[1] * scale), round(rgb.shape[0] * scale)), interpolation=cv2.INTER_AREA)


def mde(a: np.ndarray, b: np.ndarray) -> float:
    return round(float(lp.delta_e2000(metric_view(a[..., :3]), metric_view(b[..., :3])).mean()), 3)


def samples() -> list[dict]:
    rows = []
    for path in sorted(S65_INPUTS.glob("*.png")):
        name = path.stem.rsplit("_", 1)[0]
        rows.append({"group": "A", "id": path.stem, "label": path.stem, "path": path, "truth": CLEAN[name]})
    real = sorted(glob.glob(str(gv.AIC / "*"))) + sorted(glob.glob(str(gv.AI4K / "*")))
    for index, p in enumerate([Path(p) for p in real if p.lower().endswith((".png", ".jpg", ".jpeg"))], 1):
        rows.append({"group": "B", "id": f"B{index:02d}", "label": p.name, "path": p, "truth": None})
    for line in (OUT / "C_GROUP_CONFIRMED.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\| (\d+) \| (.+?) \| `(.+?)` \| `([0-9a-f]{64})` \|", line)
        if m:
            num, label, rel, sha = m.groups()
            path = Path(rel) if Path(rel).is_absolute() else REPO / rel
            rows.append({"group": "C", "id": f"C{int(num):02d}", "label": label, "path": path, "truth": None, "sha_expected": sha})
    return rows


def reason(analysis: lp.LevelPickAnalysis, light_safe: bool) -> str:
    cast = analysis.cast
    if analysis.recommended_level != "original":
        return "偏色明确，但轻档未通过安全检查，保留原图" if not light_safe else f"偏色量 {analysis.measured_offset}，三种估计一致"
    if analysis.measured_offset < lp.CAST_MIN_WHITE:
        return f"偏色量 {analysis.measured_offset} 低于 {lp.CAST_MIN_WHITE:g}，按颜色正常处理"
    return f"偏色量 {analysis.measured_offset}，但三种估计{'方向相反' if cast.get('opposed') else '不一致'}，可能是设计色调"


def tile(rgb: np.ndarray, caption: str, font) -> Image.Image:
    im = Image.fromarray(np.ascontiguousarray(rgb[..., :3]))
    im.thumbnail((TILE, TILE), Image.LANCZOS)
    sheet = Image.new("RGB", (TILE, TILE + 52), "white")
    sheet.paste(im, ((TILE - im.width) // 2, (TILE - im.height) // 2))
    ImageDraw.Draw(sheet).text((10, TILE + 10), caption, fill="black", font=font)
    return sheet


def baseline(path: Path, src: np.ndarray, tmp: Path) -> dict:
    """The current formal automatic chain on the same file."""

    out = tmp / (path.stem + "_out" + path.suffix.lower().replace(".jpeg", ".jpg"))
    try:
        result = run_formal_color_runtime(path, out)
    except Exception as exc:  # the formal chain rejects some inputs; that is a finding, not a PoC failure
        return {"error": repr(exc)[:160], "pixels": src, "changed": False}
    if result.output_path and Path(result.output_path).is_file() and result.output_selected:
        pixels = load_color_managed_source(result.output_path).pixels
        if pixels.shape == src.shape:
            return {"final": str(result.d3_final_action), "pixels": pixels, "changed": True}
    return {"final": str(result.d3_final_action), "pixels": src, "changed": False}


def run_one(sample: dict, tmp: Path, font) -> dict:
    path: Path = sample["path"]
    row = {"group": sample["group"], "id": sample["id"], "label": sample["label"], "path": str(path)}
    if not path.is_file():
        return {**row, "status": "MISSING"}
    row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    if "sha_expected" in sample:
        row["sha_ok"] = row["sha256"] == sample["sha_expected"]
    try:
        preview = lp.build_level_pick_preview(path)
    except Exception as exc:  # e.g. greyscale files: the colour page rejects them today (S69-D scope)
        return {**row, "status": "UNSUPPORTED_INPUT", "error": repr(exc)[:160]}
    src, analysis = preview.source.pixels, preview.analysis
    started = time.perf_counter()
    timed = lp.render_level(src, lp.analyze_level_pick(src), "light")
    row["seconds_measure_plus_one_level"] = round(time.perf_counter() - started, 2)
    row["render_matches_level_pick"] = bool(np.array_equal(timed, preview.levels["light"]))
    row["size"] = [int(src.shape[1]), int(src.shape[0])]
    row.update({"category": analysis.category, "measured_offset": analysis.measured_offset,
                "trusted": bool(analysis.cast.get("trusted")), "hints": list(analysis.intent_hints)})
    truth = load_color_managed_source(sample["truth"]).pixels if sample["truth"] else None
    if truth is not None:
        row["cast_de"] = mde(src, truth)
    base = baseline(path, src, tmp)
    row["baseline"] = {k: v for k, v in base.items() if k != "pixels"} | {"change_de": mde(base["pixels"], src)}
    if truth is not None:
        row["baseline"]["de_to_truth"] = mde(base["pixels"], truth)
    tiles = [tile(src, f"{sample['id']} 原图", font), tile(base["pixels"], "现行自动校色" + ("" if base["changed"] else "（未改）"), font)]
    for rule, level in RULES.items():
        safe = bool(preview.safety[level]["passed"])
        fixed = analysis.recommended_level != "original" and safe
        pixels = preview.levels[level] if fixed else src
        row[rule] = {"decision": level if fixed else "original", "level_safe": safe, "reason": reason(analysis, safe),
                     "change_de": mde(pixels, src) if fixed else 0.0,
                     "neutral_change_de": preview.safety[level]["neutral_delta_e00_mean"] if fixed else 0.0}
        if truth is not None:
            row[rule]["de_to_truth"] = mde(pixels, truth)
        name = "新规则" if rule == "main" else "对照"
        tiles.append(tile(pixels, f"{name}：{LABELS[row[rule]['decision']]}", font))
    if truth is not None:
        tiles.append(tile(truth, "标准答案", font))
    sheet = Image.new("RGB", (TILE * len(tiles), TILE + 52), "white")
    for i, t in enumerate(tiles):
        sheet.paste(t, (i * TILE, 0))
    sheet.save(SHEETS / f"{sample['id']}.jpg", quality=90)
    return row


def summarize(rows: list[dict]) -> dict:
    done = [r for r in rows if "main" in r]
    a = [r for r in done if r["group"] == "A"]
    visible = [r for r in a if r["cast_de"] >= VISIBLE_CAST_DE]
    out = {"missing": [r["id"] for r in rows if r.get("status") == "MISSING"],
           "unsupported_input": [r["id"] for r in rows if r.get("status") == "UNSUPPORTED_INPUT"],
           "c_sha_mismatch": [r["id"] for r in done if r.get("sha_ok") is False],
           "render_mismatch": [r["id"] for r in done if not r["render_matches_level_pick"]],
           "max_seconds": max(r["seconds_measure_plus_one_level"] for r in done),
           "a_total": len(a), "a_visible": len(visible)}
    for rule in RULES:
        fixed = [r for r in visible if r[rule]["decision"] != "original"]
        reduction = [1 - r[rule]["de_to_truth"] / r["cast_de"] for r in fixed]
        out[rule] = {
            "a_visible_fixed": len(fixed),
            "a_fixed_reduction_median": round(float(np.median(reduction)), 3) if reduction else None,
            "a_fixed_worse": [r["id"] for r, x in zip(fixed, reduction) if x < 0],
            "a_all_fixed_worse": [r["id"] for r in a if r[rule]["decision"] != "original" and r[rule]["de_to_truth"] > r["cast_de"]],
            "a_wrong_direction": [r["id"] for r in a if r[rule]["decision"] != "original"
                                  and gv.colour_tag(r["category"]) != {"yellow": "YELLOW", "blue": "BLUE", "green": "TINT"}[r["id"].rsplit("_", 1)[1]]],
            "b_fixed": [r["id"] for r in done if r["group"] == "B" and r[rule]["decision"] != "original"],
            "c_fixed": [r["id"] for r in done if r["group"] == "C" and r[rule]["decision"] != "original"],
            "unsafe_blocked": [r["id"] for r in done if "安全检查" in r[rule]["reason"]],
        }
    out["baseline"] = {"a_visible_changed": sum(r["baseline"]["change_de"] >= 0.5 for r in visible),
                       "b_changed": [r["id"] for r in done if r["group"] == "B" and r["baseline"]["change_de"] >= 0.5],
                       "c_changed": [r["id"] for r in done if r["group"] == "C" and r["baseline"]["change_de"] >= 0.5]}
    return out


def human_review(rows: list[dict]) -> str:
    lines = ["# S67 自动挑档 PoC｜人工复核表", "",
             "每张图看 `sheets/<编号>.jpg`：原图｜现行自动校色｜新规则（轻）｜对照（中）。",
             "请在后三列填写：自动决定对不对（对/不对）、结果能否直接用（能/不能）、有没有伤害（无/有）。", "",
             "| 编号 | 图片 | 新规则决定 | 原因 | 改动量 ΔE | 对照（中）改动量 | 决定对不对 | 能否直接用 | 有无伤害 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["group"] in ("B", "C") and "main" in r:
            lines.append(f"| {r['id']} | {r['label']} | {LABELS[r['main']['decision']]} | {r['main']['reason']} | "
                         f"{r['main']['change_de']} | {r['variant']['change_de']} | | | |")
    return "\n".join(lines) + "\n"


def main() -> int:
    SHEETS.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 22)
    rows = []
    done = {}
    if "--resume" in sys.argv and (OUT / "summary.json").is_file():
        done = {r["id"]: r for r in json.loads((OUT / "summary.json").read_text(encoding="utf-8"))["rows"]}
    with tempfile.TemporaryDirectory() as td:
        for sample in samples():
            row = done.get(sample["id"]) or run_one(sample, Path(td), font)
            rows.append(row)
            print(row["id"], row.get("status") or f"{row['main']['decision']} | {row['main']['reason']} | base {row['baseline']['change_de']}", flush=True)
            (OUT / "summary.json").write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = summarize(rows)
    (OUT / "summary.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "HUMAN_REVIEW.md").write_text(human_review(rows), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
