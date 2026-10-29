"""S68-REFTONE-POC: reference colour = white (frozen S66) + global tone + saturation, in three levels.

Isolated experiment. Samples are read-only; nothing is written to the formal output root.
Evidence goes to artifacts/s68_reftone_poc/.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools" / "experiments"))

from engine.color_correction.level_pick import (  # noqa: E402
    GAMUT_FLOOR, GAMUT_KNEE, LEVELS, SKIN_KEEP, _adaptation_matrix, _gamut_pull, _to_linear, _to_srgb, delta_e2000, level_safety,
)
from engine.color_correction.reference_level_pick import ReferencePlan, plan_reference, render_reference_level  # noqa: E402
import s65_refcolor_poc as s65  # noqa: E402

OUT = REPO_ROOT / "artifacts" / "s68_reftone_poc"
REF_SERIES = Path(r"D:\HDDE样本\RefSeries")
INTAKE = Path(r"D:\影界文件\输出\图片压缩\.运行缓存\image-compression-intake")

# Initial caps and gates from the approved card; calibrated by the PoC, never loosened by the executor.
CAP_MEDIAN_SHIFT = 15.0          # L* the median may move at any level
CAP_SPAN = (0.80, 1.25)          # p5..p95 span scale
CAP_CHROMA = (0.80, 1.35)        # chroma scale
GUARD_MEDIAN_GAP = 25.0          # median L* gap that marks a different scene
GUARD_STRENGTH = LEVELS["light"]
GATE_G_STRONG_REDUCTION = 0.50
GATE_G_METRIC_REDUCTION = 0.60
GATE_IDENTITY_MAX_DE = 0.5
GATE_HUE_MAX_DEG = 3.0
GATE_EXTRA_SECONDS = 1.0
# A G sample whose degradation pushed more than this share of pixels to pure black/white has
# no recoverable truth; it is reported in its own column, never dropped.
G_MAX_DESTROYED_SHARE = 0.02
# Owner ruling 2026-10-29: the >=60% reduction applies only to visible initial gaps,
# and no item may end further from the reference than it started.
GATE_METRIC_MIN_GAP = {"median": 0.5, "span": 3.0, "chroma": float(np.log(1.15))}
# Owner ruling 2026-10-29: large blue sky / single-colour background plus a cast is a known
# limitation of the frozen S66 white step; reported separately, not part of the G gates.
KNOWN_LIMITATION_CASES = {"G_S08_sky_blue_bright_vivid": "KNOWN_LIMITATION_S66_WHITE"}
STATS_LONG_EDGE = 768


# ---------- measurement ----------

def _lab_f(rgb_u8: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb_u8[..., :3].astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)


def _view(rgb_u8: np.ndarray) -> np.ndarray:
    h, w = rgb_u8.shape[:2]
    scale = min(1.0, STATS_LONG_EDGE / max(h, w))
    return cv2.resize(rgb_u8[..., :3], (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else rgb_u8[..., :3]


def tone_stats(rgb_u8: np.ndarray) -> dict[str, float]:
    lab = _lab_f(_view(rgb_u8)).reshape(-1, 3)
    # p10/p90 rather than p5/p95: pure black or white areas clip the outer percentiles
    p5, p50, p95 = np.percentile(lab[:, 0], [10, 50, 90])
    # chroma of near-black pixels is noise; measure saturation where colour is visible
    lit = lab[:, 0] > 15
    chroma = np.hypot(lab[lit, 1], lab[lit, 2]) if lit.sum() > 500 else np.hypot(lab[:, 1], lab[:, 2])
    c50, c90 = np.percentile(chroma, [50, 90])
    return {"L_p5": float(p5), "L_p50": float(p50), "L_p95": float(p95),
            "span": float(p95 - p5), "C_p50": float(c50), "C_p90": float(c90),
            "black_share": float((lab[:, 0] <= 1.0).mean()), "white_share": float((lab[:, 0] >= 99.0).mean())}


# ---------- tone curve (monotone cubic, Fritsch-Carlson) ----------

def _pchip(xs: np.ndarray, ys: np.ndarray, x: np.ndarray) -> np.ndarray:
    h = np.diff(xs)
    delta = np.diff(ys) / h
    m = np.zeros_like(ys)
    m[0], m[-1] = delta[0], delta[-1]
    for k in range(1, len(xs) - 1):
        if delta[k - 1] * delta[k] > 0:
            w1, w2 = 2 * h[k] + h[k - 1], h[k] + 2 * h[k - 1]
            m[k] = (w1 + w2) / (w1 / delta[k - 1] + w2 / delta[k])
    idx = np.clip(np.searchsorted(xs, x) - 1, 0, len(xs) - 2)
    t = (x - xs[idx]) / h[idx]
    h00, h10, h01, h11 = 2 * t**3 - 3 * t**2 + 1, t**3 - 2 * t**2 + t, -2 * t**3 + 3 * t**2, t**3 - t**2
    return h00 * ys[idx] + h10 * h[idx] * m[idx] + h01 * ys[idx + 1] + h11 * h[idx] * m[idx + 1]


def tone_plan(target: dict[str, float], reference: dict[str, float], strength: float) -> dict[str, Any]:
    guard = abs(reference["L_p50"] - target["L_p50"]) > GUARD_MEDIAN_GAP
    s = min(strength, GUARD_STRENGTH) if guard else strength
    shift = float(np.clip(s * (reference["L_p50"] - target["L_p50"]), -CAP_MEDIAN_SHIFT, CAP_MEDIAN_SHIFT))
    # Shadows and highlights stretch separately; a side clipped at pure black or white in either
    # image says nothing about contrast, so the clean side stands in for it.
    low = (reference["L_p50"] - reference["L_p5"]) / max(target["L_p50"] - target["L_p5"], 1.0)
    high = (reference["L_p95"] - reference["L_p50"]) / max(target["L_p95"] - target["L_p50"], 1.0)
    # a side counts as clipped only when pure black/white covers the percentile that measures it
    low_clipped = max(target.get("black_share", 0.0), reference.get("black_share", 0.0)) >= 0.10
    high_clipped = max(target.get("white_share", 0.0), reference.get("white_share", 0.0)) >= 0.10
    if low_clipped and high_clipped:
        low = high = 1.0
    elif low_clipped:
        low = high
    elif high_clipped:
        high = low
    low_ratio = float(np.clip(1.0 + s * (low - 1.0), *CAP_SPAN))
    high_ratio = float(np.clip(1.0 + s * (high - 1.0), *CAP_SPAN))
    span_ratio = float(np.sqrt(low_ratio * high_ratio))
    d50 = float(np.clip(target["L_p50"] + shift, 2.0, 98.0))
    d5 = float(np.clip(d50 - (target["L_p50"] - target["L_p5"]) * low_ratio, 0.5, d50 - 1.0))
    d95 = float(np.clip(d50 + (target["L_p95"] - target["L_p50"]) * high_ratio, d50 + 1.0, 99.5))
    # Inner anchors too close to an endpoint or each other would make the curve ill-defined
    # (dark images put p5 at L*~0); drop them and let the neighbours carry the shape.
    inner = [(target["L_p5"], d5), (target["L_p50"], d50), (target["L_p95"], d95)]
    anchors = [[0.0, 0.0]]
    for x, y in inner:
        if x - anchors[-1][0] >= 2.0 and 100.0 - x >= 2.0 and y > anchors[-1][1]:
            anchors.append([float(x), float(y)])
    anchors.append([100.0, 100.0])
    # saturation = how vivid the colourful part is (p90 of chroma among lit pixels)
    ratio_c = (reference["C_p90"] + 1.0) / (target["C_p90"] + 1.0)
    chroma = float(np.clip(1.0 + s * (ratio_c - 1.0), *CAP_CHROMA))
    return {"guard": guard, "strength": s, "median_shift": round(shift, 2), "span_ratio": round(span_ratio, 3),
            "chroma_scale": round(chroma, 3),
            "anchors": anchors}


def describe_tone(plan: dict[str, Any]) -> str:
    words = []
    if plan["median_shift"] >= 2:
        words.append("变亮")
    elif plan["median_shift"] <= -2:
        words.append("变暗")
    if plan["span_ratio"] >= 1.04:
        words.append("对比更强")
    elif plan["span_ratio"] <= 0.96:
        words.append("对比更柔")
    if plan["chroma_scale"] >= 1.05:
        words.append("更鲜艳")
    elif plan["chroma_scale"] <= 0.95:
        words.append("更淡雅")
    return "、".join(words)


# ---------- render ----------

def _apply(white: np.ndarray, skin: np.ndarray | None, tp: dict[str, Any]) -> np.ndarray:
    """Tone curve + saturation on an S66 white-aligned RGB uint8 image."""

    lab = _lab_f(white)
    xs = np.array([a[0] for a in tp["anchors"]], np.float64)
    ys = np.array([a[1] for a in tp["anchors"]], np.float64)
    lut_x = np.linspace(0.0, 100.0, 1001)
    lab[..., 0] = np.interp(lab[..., 0], lut_x, _pchip(xs, ys, lut_x)).astype(np.float32)
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    # near-neutral pixels keep the white the S66 step set; skin keeps most of its chroma
    weight = np.clip((chroma - 2.0) / 8.0, 0.0, 1.0)
    if skin is not None:
        weight = weight * (1.0 - SKIN_KEEP * skin)
    scale = 1.0 + (tp["chroma_scale"] - 1.0) * weight
    lab[..., 1] *= scale
    lab[..., 2] *= scale
    rgb = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    # Only colours pushed out of range take the soft gamut pull; in-range pixels convert as is,
    # so a no-op plan leaves the S66 pixels untouched.
    # Pixels the step pushed brighter into the shoulder or darker into the toe also take it,
    # so no new pure white or pure black appears.
    base = white[..., :3].astype(np.float32) / 255.0
    def linear(v):
        return np.where(v <= 0.04045, v / 12.92, np.sign(v) * ((np.abs(v) + 0.055) / 1.055) ** 2.4).astype(np.float32)
    brighter = rgb.max(axis=-1) > base.max(axis=-1) + 1e-4
    darker = rgb.min(axis=-1) < base.min(axis=-1) - 1e-4
    need = ((rgb < 0.0) | (rgb > 1.0)).any(axis=-1) | (brighter & (rgb.max(axis=-1) > 0.93)) | (darker & (rgb.min(axis=-1) < 0.03))
    if need.any():
        lin = _gamut_pull(linear(rgb[need]))
        floor = np.minimum(linear(base[need]), GAMUT_FLOOR)
        rgb[need] = _to_srgb(np.where(darker[need][:, None], np.maximum(lin, floor), lin))
    return (np.clip(rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def _close_loop(white: np.ndarray, skin: np.ndarray | None, stats: dict[str, float],
                planned: dict[str, Any], tp: dict[str, Any]) -> dict[str, Any]:
    """One feedback step on the small view: the planned targets for p10/p50/p90 and chroma p90
    are compared with what the curve actually produced (neutral, skin and gamut handling all
    dampen it), and the anchors and chroma scale are corrected once, inside the same caps."""

    view = _view(white)
    skin_view = cv2.resize(skin.astype(np.float32), (view.shape[1], view.shape[0]), interpolation=cv2.INTER_AREA) if skin is not None else None
    got = tone_stats(_apply(view, skin_view, tp))
    wanted = {round(a[0], 6): a[1] for a in planned["anchors"]}
    measured = {round(stats["L_p5"], 6): got["L_p5"], round(stats["L_p50"], 6): got["L_p50"], round(stats["L_p95"], 6): got["L_p95"]}
    anchors = [[0.0, 0.0]]
    for x, y in tp["anchors"][1:-1]:
        key = round(x, 6)
        y2 = y + (wanted[key] - measured[key]) if key in measured else y
        if key == round(stats["L_p50"], 6):
            y2 = float(np.clip(y2, x - CAP_MEDIAN_SHIFT, x + CAP_MEDIAN_SHIFT))
        y2 = float(np.clip(y2, anchors[-1][1] + 0.5, 99.5))
        anchors.append([x, y2])
    anchors.append([100.0, 100.0])
    wanted_c90 = (stats["C_p90"] + 1.0) * planned["chroma_scale"] - 1.0
    chroma = float(np.clip(tp["chroma_scale"] * (wanted_c90 + 1.0) / (got["C_p90"] + 1.0), *CAP_CHROMA))
    return {**tp, "anchors": anchors, "chroma_scale": round(chroma, 3)}


def render_tone_level(pixels: np.ndarray, plan: ReferencePlan, level: str, reference_stats: dict[str, float],
                      target_stats: dict[str, float], tone: bool = True) -> tuple[np.ndarray, dict[str, Any]]:
    white = render_reference_level(pixels, plan, level)
    if not tone:
        return white, {}
    # tone and saturation are measured after the white step: removing a cast changes chroma too
    stats = tone_stats(white)
    planned = tone_plan(stats, reference_stats, LEVELS[level])
    tp = planned
    for _ in range(2):  # two small-view feedback steps toward the planned (capped) targets
        tp = _close_loop(white, plan.target.skin, stats, planned, tp)
    rgb = _apply(white, plan.target.skin, tp)
    # Safeguard on the full image: saturation must never end further from the reference than
    # the target started; if it does, re-aim the scale once at the planned value.
    got = tone_stats(rgb)
    def c_gap(c90: float) -> float:
        return abs(float(np.log((c90 + 1.0) / (reference_stats["C_p90"] + 1.0))))
    if c_gap(got["C_p90"]) > c_gap(target_stats["C_p90"]):
        wanted = (stats["C_p90"] + 1.0) * planned["chroma_scale"] - 1.0
        if c_gap(wanted) > c_gap(target_stats["C_p90"]):
            wanted = target_stats["C_p90"]
        tp = {**tp, "chroma_scale": round(float(np.clip(tp["chroma_scale"] * (wanted + 1.0) / (got["C_p90"] + 1.0), *CAP_CHROMA)), 3),
              "safeguard": "CHROMA_REAIMED"}
        rgb = _apply(white, plan.target.skin, tp)
    if pixels.shape[2] == 4:
        rgb = np.dstack((rgb, pixels[..., 3]))
        transparent = pixels[..., 3] == 0
        rgb[transparent] = pixels[transparent]
    return rgb, tp


# ---------- samples ----------

G_COMBOS = {
    # cast ab, gamma on L* (>1 darker), contrast k (<0 flatter, >0 punchier), chroma scale.
    # Black and white points stay fixed so the degradation loses no information, like a real
    # difference in lighting or rendering would.
    "yellow_dark_flat_dull": ((0.0, 10.0), 1.25, -0.40, 0.80),
    "blue_bright_vivid": ((0.0, -9.0), 0.82, 0.35, 1.20),
    "green_dark_dull": ((-8.0, 0.0), 1.15, -0.25, 0.75),
}


def degrade(clean: np.ndarray, cast, gamma, contrast, chroma) -> np.ndarray:
    lin = _to_linear(clean.astype(np.float32) / 255.0) @ _adaptation_matrix((0.0, 0.0), cast).T
    cast_rgb = (np.clip(_to_srgb(_gamut_pull(lin)), 0, 1) * 255 + 0.5).astype(np.uint8)
    lab = _lab_f(cast_rgb)
    x = np.clip(lab[..., 0] / 100.0, 0.0, 1.0) ** gamma
    x = x + contrast * ((3 * x**2 - 2 * x**3) - x)
    lab[..., 0] = x * 100.0
    lab[..., 1] *= chroma
    lab[..., 2] *= chroma
    rgb = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    out = ((rgb < 0.0) | (rgb > 1.0)).any(axis=-1)
    if out.any():
        o = rgb[out]
        rgb[out] = _to_srgb(_gamut_pull(np.where(o <= 0.04045, o / 12.92, np.sign(o) * ((np.abs(o) + 0.055) / 1.055) ** 2.4).astype(np.float32)))
    return (np.clip(rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


def mean_de(a: np.ndarray, b: np.ndarray) -> float:
    return float(delta_e2000(_view(a), _view(b)).mean())


def hue_change(before: np.ndarray, after: np.ndarray) -> float:
    la, lb = _lab_f(_view(before)).reshape(-1, 3), _lab_f(_view(after)).reshape(-1, 3)
    ca, cb = np.hypot(la[:, 1], la[:, 2]), np.hypot(lb[:, 1], lb[:, 2])
    mask = (ca > 10) & (cb > 10)
    if not mask.any():
        return 0.0
    d = np.degrees(np.arctan2(lb[mask, 2], lb[mask, 1]) - np.arctan2(la[mask, 2], la[mask, 1]))
    return float(np.abs((d + 180) % 360 - 180).mean())


def gap(stats: dict[str, float], ref: dict[str, float]) -> dict[str, float]:
    return {"median": abs(stats["L_p50"] - ref["L_p50"]), "span": abs(stats["span"] - ref["span"]),
            "chroma": abs(np.log((stats["C_p90"] + 1) / (ref["C_p90"] + 1)))}


def sheet(path: Path, tiles: list[tuple[str, np.ndarray]]) -> None:
    font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 22)
    width = 360
    cells = []
    for label, im in tiles:
        pic = Image.fromarray(im[..., :3])
        pic = pic.resize((width, max(1, int(width * pic.height / pic.width))))
        cells.append((label, pic))
    height = max(pic.height for _, pic in cells) + 36
    canvas = Image.new("RGB", (len(cells) * (width + 8), height), "white")
    draw = ImageDraw.Draw(canvas)
    for i, (label, pic) in enumerate(cells):
        canvas.paste(pic, (i * (width + 8), 36))
        draw.text((i * (width + 8) + 4, 4), label, fill="black", font=font)
    canvas.save(path, quality=90)


def destroyed_share(clean: np.ndarray, degraded: np.ndarray) -> float:
    """Share of pixels the degradation newly pushed to L* ~0 or ~100 (information lost)."""
    lc, ld = _lab_f(_view(clean))[..., 0], _lab_f(_view(degraded))[..., 0]
    return float((((ld <= 0.5) & (lc > 0.5)) | ((ld >= 99.5) & (lc < 99.5))).mean())


def run_case(case: str, group: str, target: np.ndarray, reference: np.ndarray, truth: np.ndarray | None) -> dict[str, Any]:
    t0 = time.perf_counter()
    plan = plan_reference(target, reference)
    t_white = time.perf_counter() - t0
    ts, rs = tone_stats(target), tone_stats(reference)
    row: dict[str, Any] = {"case": case, "group": group, "usable": plan.usable,
                           "white_summary": plan.description.get("summary"), "target_stats": ts, "reference_stats": rs, "levels": {}}
    tiles = [("目标", target), ("参考", reference)]
    extra = 0.0
    for level in ("light", "medium", "strong"):
        s = time.perf_counter()
        white = render_reference_level(target, plan, level)
        white_seconds = time.perf_counter() - s
        s = time.perf_counter()
        out, tp = render_tone_level(target, plan, level, rs, ts)
        # extra cost over S66 = the full render minus the S66 white render it contains
        extra += max(0.0, time.perf_counter() - s - white_seconds)
        compat, _ = render_tone_level(target, plan, level, rs, ts, tone=False)
        safety = level_safety(target, out, plan.target)
        os_ = tone_stats(out)
        item = {"tone_plan": {k: v for k, v in tp.items() if k != "anchors"}, "tone_words": describe_tone(tp),
                "compat_equals_s66": bool(np.array_equal(compat, white)),
                "hue_change_vs_white_deg": round(hue_change(white, out), 2),
                "safety": {"passed": safety["passed"], "failures": safety["failures"], "clip_growth": safety["clip_growth"]},
                "de_vs_target": round(mean_de(target, out), 2), "out_stats": os_,
                "gap_before": gap(ts, rs), "gap_after": gap(os_, rs)}
        if truth is not None:
            item["de_to_truth"] = round(mean_de(out, truth), 2)
        row["levels"][level] = item
        tiles.append(({"light": "轻", "medium": "中", "strong": "强"}[level], out))
    if truth is not None:
        row["de_target_to_truth"] = round(mean_de(target, truth), 2)
        tiles.append(("标准答案", truth))
    row["seconds_white_plan"] = round(t_white, 2)
    row["seconds_tone_extra_per_level"] = round(extra / 3, 3)
    sheet(OUT / "sheets" / f"{case}.jpg", tiles)
    return row


def main() -> int:
    (OUT / "sheets").mkdir(parents=True, exist_ok=True)
    (OUT / "inputs").mkdir(parents=True, exist_ok=True)
    rows, hashes = [], {}
    sources = {**s65.CLEAN, **s65.SERIES}
    for name, path in sources.items():
        hashes[str(path)] = sha256(path)
        clean = load(path)
        for combo, params in G_COMBOS.items():
            target = degrade(clean, *params)
            Image.fromarray(target).save(OUT / "inputs" / f"G_{name}_{combo}.png")
            row = run_case(f"G_{name}_{combo}", "G", target, clean, clean)
            row["destroyed_share"] = round(destroyed_share(clean, target), 4)
            row["group"] = "G" if row["destroyed_share"] <= G_MAX_DESTROYED_SHARE else "G_DESTROYED"
            if row["case"] in KNOWN_LIMITATION_CASES and row["group"] == "G":
                row["group"] = KNOWN_LIMITATION_CASES[row["case"]]
            rows.append(row)
    # identity
    clean = load(s65.CLEAN["S03_fashion"])
    ident = run_case("IDENTITY_S03_fashion", "IDENTITY", clean, clean, None)
    rows.append(ident)
    # X: the owner's different-scene pairs (copied from the intake cache, read-only)
    flower = s65.SERIES["S01_flower"]
    x_pairs = {"X_hall_ref_flower": INTAKE / "intake_b1bdeae00e38491396d4e994f9a02860" / "Image_1781401319675_392.jpg",
               "X_meeting_ref_flower": Path(r"D:\HDDE样本\AIColorControl\真实照片_会议室_颜色正常.jpg")}
    for case, tpath in x_pairs.items():
        if not tpath.is_file():
            rows.append({"case": case, "group": "X", "missing": str(tpath)})
            continue
        local = OUT / "inputs" / f"{case}{tpath.suffix.lower()}"
        shutil.copyfile(tpath, local)
        hashes[str(tpath)] = sha256(tpath)
        rows.append(run_case(case, "X", load(local), load(flower), None))
    # S: owner's same-series pairs, if present
    pairs = sorted(p for p in REF_SERIES.iterdir() if p.is_dir()) if REF_SERIES.is_dir() else []
    for folder in pairs:
        images = sorted(f for f in folder.iterdir() if f.suffix.lower() in {".png", ".jpg", ".jpeg"})
        tgt = [f for f in images if "目标" in f.stem] or images[:1]
        ref = [f for f in images if "参考" in f.stem] or images[1:2]
        if tgt and ref:
            for f in (tgt[0], ref[0]):
                hashes[str(f)] = sha256(f)
            rows.append(run_case(f"S_{folder.name}", "S", load(tgt[0]), load(ref[0]), None))
    hashes_after = {p: sha256(Path(p)) for p in hashes}

    g = [r for r in rows if r.get("group") == "G"]
    def reduction(r, level):
        return 1.0 - r["levels"][level]["de_to_truth"] / max(r["de_target_to_truth"], 1e-6)
    metric_red = []
    for r in g:
        b, a = r["levels"]["strong"]["gap_before"], r["levels"]["strong"]["gap_after"]
        metric_red.append({k: 1.0 - a[k] / b[k] for k in b if b[k] >= GATE_METRIC_MIN_GAP[k]})
    all_levels = [lv for r in rows if "levels" in r for lv in r["levels"].values()]
    gates = {
        "G_strong_de_reduction_min": round(min(reduction(r, "strong") for r in g), 3),
        "G_strong_de_reduction_median": round(float(np.median([reduction(r, "strong") for r in g])), 3),
        "G_monotonic": all(r["levels"]["light"]["de_to_truth"] >= r["levels"]["medium"]["de_to_truth"] >= r["levels"]["strong"]["de_to_truth"] for r in g),
        "G_never_further": all(r["levels"][lv]["de_to_truth"] <= r["de_target_to_truth"] for r in g for lv in ("light", "medium", "strong")),
        "G_metric_reduction_min": {k: round(min(m[k] for m in metric_red if k in m), 3) for k in ("median", "span", "chroma")},
        "G_metric_enlarged": [(r["case"], k, round(r["levels"]["strong"]["gap_before"][k], 3), round(r["levels"]["strong"]["gap_after"][k], 3))
                              for r in g for k in ("median", "span", "chroma")
                              if r["levels"]["strong"]["gap_after"][k] > r["levels"]["strong"]["gap_before"][k]],
        "known_limitation": [{"case": r["case"], "target": r["de_target_to_truth"], **{lv: r["levels"][lv]["de_to_truth"] for lv in ("light", "medium", "strong")}}
                             for r in rows if str(r.get("group", "")).startswith("KNOWN_LIMITATION")],
        "identity_strong_de": ident["levels"]["strong"]["de_vs_target"],
        "compat_all_equal_s66": all(lv["compat_equals_s66"] for lv in all_levels),
        "hue_change_max_deg": max(lv["hue_change_vs_white_deg"] for lv in all_levels),
        "safety_failures": [(r["case"], k, v["safety"]["failures"]) for r in rows if "levels" in r for k, v in r["levels"].items() if not v["safety"]["passed"]],
        "X_guard": {r["case"]: r["levels"]["strong"]["tone_plan"]["guard"] for r in rows if r.get("group") == "X" and "levels" in r},
        "tone_extra_seconds_max": max(r["seconds_tone_extra_per_level"] for r in rows if "levels" in r),
        "samples_unchanged": hashes == hashes_after,
        "S_pairs": len([r for r in rows if r.get("group") == "S"]),
    }
    gd = [r for r in rows if r.get("group") == "G_DESTROYED"]
    gates["G_valid_count"], gates["G_destroyed"] = len(g), [
        {"case": r["case"], "destroyed_share": r["destroyed_share"], "target": r["de_target_to_truth"],
         "light": r["levels"]["light"]["de_to_truth"], "medium": r["levels"]["medium"]["de_to_truth"], "strong": r["levels"]["strong"]["de_to_truth"]} for r in gd]
    gates["G_failing"] = [{"case": r["case"], "target": r["de_target_to_truth"], **{lv: r["levels"][lv]["de_to_truth"] for lv in ("light", "medium", "strong")}}
                          for r in g if reduction(r, "strong") < GATE_G_STRONG_REDUCTION
                          or not (r["levels"]["light"]["de_to_truth"] >= r["levels"]["medium"]["de_to_truth"] >= r["levels"]["strong"]["de_to_truth"])
                          or any(r["levels"][lv]["de_to_truth"] > r["de_target_to_truth"] for lv in ("light", "medium", "strong"))]
    gates["hue_worst"] = max(((lv["hue_change_vs_white_deg"], r["case"]) for r in rows if "levels" in r for lv in r["levels"].values()))
    gates["pass"] = {
        "G_reduction": gates["G_strong_de_reduction_min"] >= GATE_G_STRONG_REDUCTION,
        "G_metric": all(v >= GATE_G_METRIC_REDUCTION for v in gates["G_metric_reduction_min"].values()),
        "G_metric_not_enlarged": not gates["G_metric_enlarged"],
        "G_monotonic": gates["G_monotonic"], "G_never_further": gates["G_never_further"],
        "identity": gates["identity_strong_de"] <= GATE_IDENTITY_MAX_DE,
        "compat": gates["compat_all_equal_s66"], "hue": gates["hue_change_max_deg"] <= GATE_HUE_MAX_DEG,
        "safety": not gates["safety_failures"], "X_guard": all(gates["X_guard"].values()) and bool(gates["X_guard"]),
        "time": gates["tone_extra_seconds_max"] <= GATE_EXTRA_SECONDS, "samples_unchanged": gates["samples_unchanged"],
    }
    (OUT / "summary.json").write_text(json.dumps({"gates": gates, "rows": rows}, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(json.dumps(gates, ensure_ascii=False, default=float, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
