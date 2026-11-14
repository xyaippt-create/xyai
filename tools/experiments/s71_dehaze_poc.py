"""S71 dehaze PoC (isolated, not wired into the product).

Synthetic haze I = J*t + A*(1-t), t = exp(-beta*d) in linear light; J (the source) is the ground truth.
Split (task card section 5A, fixed before coding):
  tune       = 8 S69-A TUNE images with haze H1 (top far), plus their clean versions
  validation = 3 HOLDOUT images with H1, all 11 standard images with H2 (left far, bluish),
               13 design-tone images and the 3 HOLDOUT clean images as controls
  review     = every image of the sample library with H2
Usage: s71_dehaze_poc.py --tune | --validate | --review
Read-only on samples. Evidence: artifacts/s71_dehaze_poc/
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools" / "experiments"))

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import s69a_gate_validation as s69a
from engine.color_correction.level_pick import _to_linear, _to_srgb, analyze_level_pick, level_safety

OUT = REPO / "artifacts" / "s71_dehaze_poc"
DESIGN = REPO / "artifacts" / "s69_color_full_scan" / "s69a_design_tone_recheck"
LIBRARY = [Path(r"D:\HDDE样本\AI4K"), Path(r"D:\HDDE样本\AIColor"), Path(r"D:\HDDE样本\AIColorControl")]
LEVELS = {"light": 0.4, "medium": 0.7, "strong": 1.0}

# Method parameters (chosen on the tune set only).
OMEGA = 0.95          # share of the dark-channel haze estimate removed at full strength
T_FLOOR = 0.3         # transmission never goes below this: caps the gain at 3.3x
SKY_K = 0.08          # linear distance to the airlight under which a pixel is treated as sky-like
FLOOR_MIN = 0.05      # linear: some full row or column of a 6x6 grid has every block's darkest content lifted
GUIDE_EPS = 1e-3


# ------------------------------------------------------------------ synthesis ---

def to_lin(rgb: np.ndarray) -> np.ndarray:
    return _to_linear(rgb.astype(np.float32) / 255.0)


def to_u8(lin: np.ndarray) -> np.ndarray:
    return (np.clip(_to_srgb(np.clip(lin, 0.0, 1.0)), 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def add_haze(rgb: np.ndarray, shape: str) -> np.ndarray:
    h, w = rgb.shape[:2]
    if shape == "H1":
        d, beta, colour = np.repeat(1 - np.linspace(0, 1, h)[:, None], w, 1), 1.2, (0.9, 0.9, 0.9)
    else:
        d, beta, colour = np.repeat(1 - np.linspace(0, 1, w)[None, :], h, 0), 0.9, (0.82, 0.86, 0.92)
    t = np.exp(-beta * d).astype(np.float32)[..., None]
    a = _to_linear(np.array(colour, np.float32))
    return to_u8(to_lin(rgb) * t + a * (1 - t))


# -------------------------------------------------------------------- method ---

def _box(x: np.ndarray, r: int) -> np.ndarray:
    return cv2.boxFilter(x, -1, (2 * r + 1, 2 * r + 1), borderType=cv2.BORDER_REFLECT)


def _guided(guide: np.ndarray, src: np.ndarray, r: int, eps: float) -> np.ndarray:
    mg, ms = _box(guide, r), _box(src, r)
    a = (_box(guide * src, r) - mg * ms) / (_box(guide * guide, r) - mg * mg + eps)
    return _box(a, r) * guide + _box(ms - a * mg, r)


def _block_floors(dark: np.ndarray, rows: int, cols: int) -> np.ndarray:
    """5th percentile of the dark channel in each block of a rows x cols grid."""
    h, w = dark.shape
    return np.array([[np.percentile(dark[i * h // rows:(i + 1) * h // rows, j * w // cols:(j + 1) * w // cols], 5)
                      for j in range(cols)] for i in range(rows)], np.float32)


@dataclass
class Plan:
    airlight: np.ndarray
    transmission: np.ndarray
    haze: float
    hazy: bool


def plan_dehaze(rgb: np.ndarray) -> Plan:
    lin = to_lin(rgb[..., :3])
    h, w = lin.shape[:2]
    patch = max(7, round(max(h, w) * 0.01)) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (patch, patch))
    dark = cv2.erode(lin.min(axis=2), kernel)
    n = max(1, int(dark.size * 0.001))
    brightest = np.argpartition(dark.ravel(), -n)[-n:]
    airlight = np.clip(lin.reshape(-1, 3)[brightest].mean(axis=0), 0.05, 1.0).astype(np.float32)
    raw = 1.0 - OMEGA * cv2.erode((lin / airlight).min(axis=2), kernel)
    grey = cv2.cvtColor(rgb[..., :3], cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    t = _guided(grey, raw.astype(np.float32), 4 * patch, GUIDE_EPS)
    # Pixels close to the airlight (sky, white walls) carry no dark-channel evidence: relax them.
    distance = np.abs(lin - airlight).max(axis=2)
    t = np.minimum(np.maximum(SKY_K / np.maximum(distance, 1e-4), 1.0) * t, 1.0)
    t = np.clip(t, T_FLOOR, 1.0).astype(np.float32)
    # Haze can be no denser than the darkest content nearby allows: a local lower envelope of block
    # floors bounds it, so bright objects (white walls, pale designs) are not taken for thick fog.
    minimum = lin.min(axis=2)
    gy, gx = max(4, round(h / max(h, w) * 24)), max(4, round(w / max(h, w) * 24))
    envelope = cv2.erode(_block_floors(minimum, gy, gx), np.ones((3, 3), np.uint8), borderType=cv2.BORDER_REPLICATE)
    bound = 1.0 - OMEGA * cv2.resize(envelope, (w, h), interpolation=cv2.INTER_CUBIC) / float(airlight.min())
    t = np.clip(np.maximum(t, bound), T_FLOOR, 1.0).astype(np.float32)
    # Hazy when some whole row or column of a coarse grid has its darkest content lifted.
    floors = _block_floors(minimum, 6, 6)
    haze = float(max(floors.min(axis=1).max(), floors.min(axis=0).max()))
    return Plan(airlight, t, round(haze, 4), haze >= FLOOR_MIN)


def render(rgb: np.ndarray, plan: Plan, level: str) -> np.ndarray:
    if not plan.hazy:
        return rgb.copy()
    s = LEVELS[level]
    t = np.maximum(1.0 - s * (1.0 - plan.transmission), T_FLOOR)[..., None]
    out = to_u8((to_lin(rgb[..., :3]) - plan.airlight) / t + plan.airlight)
    return np.dstack((out, rgb[..., 3])) if rgb.shape[2] == 4 else out


# ------------------------------------------------------------------- metrics ---

def _gray(rgb):
    return cv2.cvtColor(rgb[..., :3], cv2.COLOR_RGB2GRAY).astype(np.float32)


def _clip(rgb):
    rgb = rgb[..., :3]
    return float(((rgb.max(axis=-1) >= 255) | (rgb.min(axis=-1) <= 0)).mean())


def noise_ratio(out, truth):
    g = _gray(truth)
    grad = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
    flat = grad <= np.percentile(grad, 20)
    hp = lambda x: x - cv2.GaussianBlur(x, (0, 0), 2)  # noqa: E731
    return round(float(hp(_gray(out))[flat].std() / max(hp(g)[flat].std(), 1.0)), 3)


def halo_ratio(out, truth):
    edges = cv2.Canny(_gray(truth).astype(np.uint8), 100, 200) > 0
    near = cv2.dilate(edges.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    band = (cv2.dilate(edges.astype(np.uint8), np.ones((25, 25), np.uint8)) > 0) & ~near
    lab = lambda x: cv2.cvtColor(x[..., :3].astype(np.float32) / 255, cv2.COLOR_RGB2LAB)[..., 0]  # noqa: E731
    err = np.abs(lab(out) - lab(truth))
    far = ~(band | near)
    if not band.any() or not far.any():
        return 1.0
    return round(float(err[band].mean() / max(err[far].mean(), 0.5)), 3)


def evaluate(img, truth):
    plan = plan_dehaze(img)
    row = {"haze": plan.haze, "hazy": plan.hazy, "input_de": s69a.mde(img, truth)}
    analysis = analyze_level_pick(img)
    for level in LEVELS:
        out = render(img, plan, level)
        row[level] = s69a.mde(out, truth)
        if level == "strong":
            row["identical"] = bool(np.array_equal(out, img))
            # Gate 5 (owner ruling 2026-11-14): clipping is judged against the ground truth, skin as before.
            safety = level_safety(img, out, analysis)
            clip_ok = _clip(out) <= _clip(truth) + 0.005
            skin_ok = not [f for f in safety["failures"] if f != "CLIPPING_GROWTH"]
            row["clip"], row["truth_clip"] = round(_clip(out), 4), round(_clip(truth), 4)
            row["safe"] = row["identical"] or (clip_ok and skin_ok)
            row["noise"] = noise_ratio(out, truth)
            row["halo"] = halo_ratio(out, truth)
    return row


# --------------------------------------------------------------------- runs ---

def cases(mode):
    """(case, group, kind, hazy_image, truth)."""
    for group, srcs in (("TUNE", s69a.TUNE), ("HOLDOUT", s69a.HOLDOUT)):
        for name, path in srcs.items():
            clean = s69a.load(path)
            if group == "TUNE":
                yield f"{name}__H1", "TUNE", "HAZE", add_haze(clean, "H1"), clean
                yield f"{name}__clean", "TUNE", "CONTROL", clean, clean
            if mode == "validate":
                if group == "HOLDOUT":
                    yield f"{name}__H1", "VALIDATION", "HAZE", add_haze(clean, "H1"), clean
                    yield f"{name}__clean", "VALIDATION", "CONTROL", clean, clean
                yield f"{name}__H2", "VALIDATION", "HAZE", add_haze(clean, "H2"), clean
    if mode == "validate":
        for path in sorted(DESIGN.glob("C*.jpg")):
            img = s69a.load(path)
            yield f"design_{path.stem}", "VALIDATION", "CONTROL", img, img


def gates(rows):
    haze = [r for r in rows if r["kind"] == "HAZE"]
    control = [r for r in rows if r["kind"] == "CONTROL"]
    red = [1 - r["strong"] / r["input_de"] for r in haze]
    return {
        "haze_cases": len(haze),
        "g1_detected": sum(r["hazy"] for r in haze),
        "g1_missed": [r["case"] for r in haze if not r["hazy"]],
        "g1_strong_reduction_median": round(float(np.median(red)), 3) if red else None,
        "g1_worse": {r["case"]: round(r["strong"] - r["input_de"], 3) for r in haze if r["strong"] > r["input_de"]},
        "g1_light_worse": [r["case"] for r in haze if r["light"] > r["input_de"]],
        "g2_control_flagged": [r["case"] for r in control if r["hazy"]],
        "g2_unflagged_not_identical": [r["case"] for r in control if not r["hazy"] and not r["identical"]],
        "g3_noise_over": {r["case"]: r["noise"] for r in rows if r["noise"] > 1.5},
        "g4_halo_over": {r["case"]: r["halo"] for r in rows if r["halo"] > 1.5},
        "g5_unsafe": [r["case"] for r in rows if not r["safe"]],
    }


def alpha_and_determinism():
    clean = s69a.load(s69a.TUNE["S07_orange"])
    hazy = add_haze(clean, "H1")
    alpha = np.full(hazy.shape[:2], 255, np.uint8)
    alpha[:, :40] = 0
    alpha[:, 40:60] = 128
    rgba = np.dstack((hazy, alpha))
    plan = plan_dehaze(rgba)
    a, b = render(rgba, plan, "strong"), render(rgba, plan_dehaze(rgba), "strong")
    return {"alpha_identical": bool(np.array_equal(a[..., 3], alpha)), "deterministic": bool(np.array_equal(a, b)),
            "shape_identical": a.shape == rgba.shape}


def timing_4k():
    src = np.asarray(Image.open(s69a.TUNE["S07_orange"]).convert("RGB").resize((3840, 2160), Image.LANCZOS))
    hazy = add_haze(src, "H1")
    t0 = time.perf_counter()
    plan = plan_dehaze(hazy)
    t1 = time.perf_counter()
    render(hazy, plan, "strong")
    t2 = time.perf_counter()
    return {"plan_seconds": round(t1 - t0, 2), "render_seconds": round(t2 - t1, 2), "one_level_total": round(t2 - t0, 2)}


def review():
    """Contact sheets: H2 haze, light, medium, strong, ground truth; full frame plus a 100% crop."""
    dest = OUT / "review"
    dest.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 22)
    labels = ["加雾（H2）", "轻", "中", "强", "原图（标准答案）"]
    index = []
    files = [p for d in LIBRARY for p in sorted(d.iterdir()) if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
    for i, path in enumerate(files, 1):
        clean = s69a.load(path)
        hazy = add_haze(clean, "H2")
        plan = plan_dehaze(hazy)
        frames = [hazy] + [render(hazy, plan, lv) for lv in LEVELS] + [clean]
        h, w = clean.shape[:2]
        cw = min(512, w // 2)
        x0, y0 = max(0, w // 4 - cw // 2), max(0, h // 2 - cw // 2)  # far (dense) side of H2
        thumb_w = 360
        th = round(h * thumb_w / w)
        sheet = Image.new("RGB", (5 * (thumb_w + 10) + 10, th + cw * thumb_w // cw + 90), "white")
        draw = ImageDraw.Draw(sheet)
        for k, frame in enumerate(frames):
            x = 10 + k * (thumb_w + 10)
            draw.text((x, 6), labels[k], fill="black", font=font)
            sheet.paste(Image.fromarray(frame[..., :3]).resize((thumb_w, th), Image.LANCZOS), (x, 40))
            crop = Image.fromarray(frame[y0:y0 + cw, x0:x0 + cw, :3])
            sheet.paste(crop.resize((thumb_w, thumb_w), Image.NEAREST), (x, 50 + th))
        name = f"{i:02d}_{path.stem[-12:].replace(' ', '_')}.png"
        sheet.save(dest / name)
        index.append({"sheet": name, "source": str(path), "haze": plan.haze, "hazy": plan.hazy,
                      "input_de": s69a.mde(hazy, clean), **{lv: s69a.mde(f, clean) for lv, f in zip(LEVELS, frames[1:4])}})
        print(name, index[-1]["hazy"], index[-1]["input_de"], index[-1]["strong"], flush=True)
    (dest / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if "--review" in sys.argv:
        review()
        return 0
    mode = "validate" if "--validate" in sys.argv else "tune"
    rows = []
    for case, group, kind, img, truth in cases(mode):
        row = {"case": case, "group": group, "kind": kind, **evaluate(img, truth)}
        rows.append(row)
        print(f'{case:24s} {kind:7s} haze={row["haze"]:.3f} hazy={row["hazy"]} in={row["input_de"]:.2f} '
              f'L={row["light"]:.2f} M={row["medium"]:.2f} S={row["strong"]:.2f} noise={row["noise"]} halo={row["halo"]} safe={row["safe"]}', flush=True)
    report = {"mode": mode, "params": {"OMEGA": OMEGA, "T_FLOOR": T_FLOOR, "SKY_K": SKY_K, "FLOOR_MIN": FLOOR_MIN},
              "gates": {g: gates([r for r in rows if r["group"] == g]) for g in sorted({r["group"] for r in rows})}}
    if mode == "validate":
        report["all"] = gates(rows)
        report["g5_alpha_determinism"] = alpha_and_determinism()
        report["g6_timing_4k"] = timing_4k()
    report["rows"] = rows
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False, indent=1))
    (OUT / f"{mode}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
