"""S63-AICOLOR-POC: isolated three-strength cast / haze correction for AI-generated images.

Not part of the formal color chain. Reads samples read-only, writes only under
artifacts/s63_aicolor_poc, blocks network in-process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image, ImageCms, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "S63-AICOLOR-POC"
SAMPLE_ROOTS = (Path(r"D:\HDDE样本\AI4K"), Path(r"D:\HDDE样本\AIColor"))
OUTPUT_ROOT = REPO_ROOT / "artifacts" / "s63_aicolor_poc"
TEXT_DETECTOR = REPO_ROOT / "models" / "s62_ai4k_poc" / "ch_PP-OCRv4_det_infer.onnx"

LEVELS = {"light": 0.4, "medium": 0.7, "strong": 1.0}
ANALYSIS_LONG_EDGE = 768

# Initial gates from the approved card; calibrated by the PoC, never loosened by the executor.
# Owner calibration 2026-10-27: visibility is pre-checked on the neutral region (where the
# correction acts); the owner's visual review is the final judge, so a miss is flagged, not blocking.
GATE_MEDIUM_DE_ON_CAST = 3.0
GATE_MEDIUM_DE_ON_CONTROL = 1.5
GATE_CLIP_GROWTH = 0.005
GATE_SECONDS_THREE_LEVELS = 5.0
GATE_SKIN_HUE_SHIFT = 10.0
SKIN_MIN_CHROMA_FOR_HUE = 10.0

# Classification of the measured problem (not a gate): offset of the neutral cluster in a*b*.
CAST_MIN_AB = 6.0
HAZE_MIN = 0.06
DARK_VEIL_MAX_CHROMA = 12.0
TONE_BANDS = ((15, 35), (35, 55), (55, 70), (70, 82), (82, 92), (92, 99))
BAND_RADIUS = 9.0
GAMUT_KNEE = 0.85
GAMUT_CEILING = 0.995
GAMUT_FLOOR = 0.002
SKIN_KEEP = 0.8

# Neutral search: chroma window wide enough to still contain cast neutrals.
NEUTRAL_MAX_CHROMA = 30.0
NEUTRAL_RADIUS = 6.0
NEUTRAL_MIN_SHARE = 0.03
NEUTRAL_MIN_CELLS = 4

SRGB_TO_XYZ = np.array(
    [[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]]
)
XYZ_TO_SRGB = np.linalg.inv(SRGB_TO_XYZ)
BRADFORD = np.array([[0.8951, 0.2664, -0.1614], [-0.7502, 1.7135, 0.0367], [0.0389, -0.0685, 1.0296]])
D65 = np.array([0.95047, 1.0, 1.08883])


class _OfflineSocket(socket.socket):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("NETWORK_BLOCKED_BY_S63_POC")


def block_network() -> None:
    socket.socket = _OfflineSocket  # type: ignore[misc]
    socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("NETWORK_BLOCKED_BY_S63_POC"))  # type: ignore[assignment]


def safe_output_path(relative: str) -> Path:
    root = OUTPUT_ROOT.resolve()
    target = (root / relative).resolve()
    if root not in target.parents:
        raise RuntimeError(f"PATH_ESCAPE: {relative}")
    probe = target.parent
    while probe != root:
        if probe.exists() and (probe.is_symlink() or probe.resolve() != probe):
            raise RuntimeError(f"REPARSE_POINT_REJECTED: {probe}")
        probe = probe.parent
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ------------------------------------------------------------- color math ---

def to_linear(srgb: np.ndarray) -> np.ndarray:
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)


def to_srgb(linear: np.ndarray) -> np.ndarray:
    linear = np.clip(linear, 0.0, 1.0)
    return np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)


def lab_of(rgb8: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb8.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)


def lab_to_xyz(lab: np.ndarray) -> np.ndarray:
    l, a, b = lab
    fy = (l + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200

    def finv(t: float) -> float:
        return t**3 if t**3 > 0.008856 else (t - 16 / 116) / 7.787

    return np.array([finv(fx), finv(fy), finv(fz)]) * D65


def adaptation_matrix(src_ab: tuple[float, float], dst_ab: tuple[float, float]) -> np.ndarray:
    """Linear-sRGB matrix that maps a grey of chromaticity src_ab to dst_ab (Bradford, Y preserved)."""

    ws = lab_to_xyz(np.array([100.0, *src_ab]))
    wd = lab_to_xyz(np.array([100.0, *dst_ab]))
    ws, wd = ws / ws[1], wd / wd[1]
    cone = np.diag((BRADFORD @ wd) / (BRADFORD @ ws))
    return XYZ_TO_SRGB @ np.linalg.inv(BRADFORD) @ cone @ BRADFORD @ SRGB_TO_XYZ


def delta_e2000(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    lab1 = lab_of(a).reshape(-1, 3).astype(np.float64)
    lab2 = lab_of(b).reshape(-1, 3).astype(np.float64)
    l1, a1, b1 = lab1.T
    l2, a2, b2 = lab2.T
    c1, c2 = np.hypot(a1, b1), np.hypot(a2, b2)
    cbar = (c1 + c2) / 2
    g = 0.5 * (1 - np.sqrt(cbar**7 / (cbar**7 + 25.0**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p, h2p = np.degrees(np.arctan2(b1, a1p)) % 360, np.degrees(np.arctan2(b2, a2p)) % 360
    dlp, dcp = l2 - l1, c2p - c1p
    dh = h2p - h1p
    dh = np.where(c1p * c2p == 0, 0, np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh)))
    dhp = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh / 2))
    lbar, cbarp = (l1 + l2) / 2, (c1p + c2p) / 2
    hsum = h1p + h2p
    hbar = np.where(
        c1p * c2p == 0, hsum, np.where(np.abs(h1p - h2p) <= 180, hsum / 2, np.where(hsum < 360, (hsum + 360) / 2, (hsum - 360) / 2))
    )
    t = 1 - 0.17 * np.cos(np.radians(hbar - 30)) + 0.24 * np.cos(np.radians(2 * hbar)) + 0.32 * np.cos(
        np.radians(3 * hbar + 6)
    ) - 0.20 * np.cos(np.radians(4 * hbar - 63))
    sl = 1 + 0.015 * (lbar - 50) ** 2 / np.sqrt(20 + (lbar - 50) ** 2)
    sc, sh = 1 + 0.045 * cbarp, 1 + 0.015 * cbarp * t
    rt = -2 * np.sqrt(cbarp**7 / (cbarp**7 + 25.0**7)) * np.sin(np.radians(60 * np.exp(-(((hbar - 275) / 25) ** 2))))
    return np.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dhp / sh) ** 2 + rt * (dcp / sc) * (dhp / sh))


# --------------------------------------------------------------- analysis ---

def analysis_view(rgb8: np.ndarray) -> np.ndarray:
    h, w, _ = rgb8.shape
    scale = min(1.0, ANALYSIS_LONG_EDGE / max(h, w))
    if scale == 1.0:
        return rgb8
    return cv2.resize(rgb8, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)


def estimate_neutral(rgb8: np.ndarray) -> dict[str, Any]:
    """Find the dominant low-chroma cluster: the colour the image's greys/whites actually have.

    Pixels above NEUTRAL_MAX_CHROMA (brand reds, orange fields, green walls) never vote, so a
    saturated design colour cannot be mistaken for the illuminant.
    """

    view = analysis_view(rgb8)
    lab = lab_of(view)
    l, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    chroma = np.hypot(a, b)
    clipped = (view.max(axis=-1) >= 254) | (view.min(axis=-1) <= 1)
    cand = (l > 15) & (l < 97) & (chroma <= NEUTRAL_MAX_CHROMA) & ~clipped
    if cand.sum() < 200:
        return {"reliable": False, "reason": "TOO_FEW_LOW_CHROMA_PIXELS", "ab": [0.0, 0.0]}

    # Weighted 2-D histogram over a*b*; lower chroma and mid-high lightness weigh more.
    weight = (1 - chroma[cand] / NEUTRAL_MAX_CHROMA) * np.clip((l[cand] - 15) / 50, 0.2, 1.0)
    edges = np.arange(-NEUTRAL_MAX_CHROMA, NEUTRAL_MAX_CHROMA + 1.0, 1.0)
    hist, _, _ = np.histogram2d(a[cand], b[cand], bins=[edges, edges], weights=weight)
    hist = cv2.GaussianBlur(hist.astype(np.float32), (0, 0), 2.0)
    # Several low-chroma clusters may exist (white clouds and blue sky, grey floor and green
    # glass). Take the one closest to neutral that is still substantial: a real cast moves all
    # of them, so no near-origin cluster survives; a coloured background is only one of them.
    local_max = (hist == cv2.dilate(hist, np.ones((5, 5), np.uint8))) & (hist > hist.max() * 0.05)
    peaks = []
    for ia, ib in zip(*np.nonzero(local_max)):
        centre = np.array([edges[ia] + 0.5, edges[ib] + 0.5])
        share = float((cand & (np.hypot(a - centre[0], b - centre[1]) <= NEUTRAL_RADIUS)).mean())
        if share >= NEUTRAL_MIN_SHARE:
            peaks.append((float(np.hypot(*centre)), centre))
    if not peaks:
        ia, ib = np.unravel_index(int(hist.argmax()), hist.shape)
        peaks = [(0.0, np.array([edges[ia] + 0.5, edges[ib] + 0.5]))]
    peak = min(peaks, key=lambda item: item[0])[1]

    near = cand & (np.hypot(a - peak[0], b - peak[1]) <= NEUTRAL_RADIUS)
    if near.sum() >= 50:
        peak = np.array([float(np.median(a[near])), float(np.median(b[near]))])
        near = cand & (np.hypot(a - peak[0], b - peak[1]) <= NEUTRAL_RADIUS)
    share = float(near.mean())
    gh, gw = near.shape[0] // 4, near.shape[1] // 4
    cells = sum(int(near[r * gh : (r + 1) * gh, c * gw : (c + 1) * gw].mean() > 0.01) for r in range(4) for c in range(4))
    reliable = share >= NEUTRAL_MIN_SHARE and cells >= NEUTRAL_MIN_CELLS
    return {
        "reliable": reliable,
        "reason": "OK" if reliable else ("NEUTRAL_SHARE_LOW" if share < NEUTRAL_MIN_SHARE else "NEUTRAL_NOT_SPREAD"),
        "ab": [round(float(peak[0]), 2), round(float(peak[1]), 2)],
        "share": round(share, 4),
        "grid_cells": cells,
        "tone_curve": tone_cast_curve(l, a, b, cand, peak) if reliable else [],
        "mask_view": near,
    }


def tone_cast_curve(l: np.ndarray, a: np.ndarray, b: np.ndarray, cand: np.ndarray, peak: np.ndarray) -> list[list[float]]:
    """Cast per lightness band: [L*, a*, b*] knots; white pinned to neutral, black extends the darkest band.

    AI renders often keep clean whites while midtones carry the cast; one global value would
    over-correct the whites (blue, clipped) or, if whites are protected, miss the cast.
    A band only counts when its neutral pixels sit close to the global neutral and are spread
    over the frame, so a sky or a tinted backdrop in one band cannot set that band's cast.
    """

    knots: list[list[float]] = []
    gh, gw = l.shape[0] // 4, l.shape[1] // 4
    for lo, hi in TONE_BANDS:
        band = cand & (l >= lo) & (l < hi)
        near = band & (np.hypot(a - peak[0], b - peak[1]) <= BAND_RADIUS)
        if near.sum() < 0.005 * l.size:
            continue
        cells = sum(int(near[r * gh : (r + 1) * gh, c * gw : (c + 1) * gw].mean() > 0.005) for r in range(4) for c in range(4))
        if cells < NEUTRAL_MIN_CELLS:
            continue
        knots.append([round((lo + hi) / 2, 1), round(float(np.median(a[near])), 2), round(float(np.median(b[near])), 2)])
    if not knots:
        return []
    return [[0.0, knots[0][1], knots[0][2]], *knots, [100.0, 0.0, 0.0]]


def tone_weighted_offset(neutral: dict[str, Any]) -> float:
    """The cast the correction will actually act on: mean |a*b*| of the measured tone knots."""

    inner = neutral.get("tone_curve", [])[1:-1]
    return round(float(np.mean([np.hypot(k[1], k[2]) for k in inner])), 2) if inner else 0.0


def estimate_haze(rgb8: np.ndarray) -> dict[str, float]:
    """Lifted black point and missing white headroom on L* (scaled to 0..1)."""

    lab = lab_of(analysis_view(rgb8))
    luma, chroma = lab[..., 0] / 100.0, np.hypot(lab[..., 1], lab[..., 2])
    lo, hi = float(np.percentile(luma, 0.5)), float(np.percentile(luma, 99.5))
    # A veil is greyish. When the darkest pixels are clearly coloured (an orange design with no
    # black in it, a tinted dark backdrop), the missing black is content, not haze.
    darkest = luma <= np.percentile(luma, 2)
    dark_chroma = float(np.median(chroma[darkest]))
    lift = max(0.0, lo - 0.03) if dark_chroma <= DARK_VEIL_MAX_CHROMA else 0.0
    brightest = luma >= np.percentile(luma, 98)
    light_chroma = float(np.median(chroma[brightest]))
    headroom = max(0.0, 0.95 - hi) if light_chroma <= DARK_VEIL_MAX_CHROMA else 0.0
    return {
        "black_p05": round(lo, 4), "white_p995": round(hi, 4),
        "darkest_chroma": round(dark_chroma, 2), "brightest_chroma": round(light_chroma, 2),
        "lift": round(lift, 4), "headroom": round(headroom, 4), "haze": round(lift + headroom, 4),
    }


def intent_hint(rgb8: np.ndarray) -> list[str]:
    """Signals that the colour may be deliberate. They only lower the recommended level."""

    lab = lab_of(analysis_view(rgb8))
    l, chroma = lab[..., 0], np.hypot(lab[..., 1], lab[..., 2])
    hints = []
    if float(np.median(l)) > 78:
        hints.append("HIGH_KEY")
    if float(np.median(l)) < 28:
        hints.append("LOW_KEY")
    if float((chroma > 45).mean()) > 0.35:
        hints.append("DOMINANT_SATURATED_COLOUR")
    return hints


# ------------------------------------------------------------- correction ---

def gamut_pull(lin: np.ndarray) -> np.ndarray:
    """Pull channels outside [0, 1] toward the pixel's own luminance instead of clipping them."""

    y = (lin @ SRGB_TO_XYZ[1].astype(np.float32))[..., None]
    y = np.clip(y, 0.0, 1.0)
    hi_c, lo_c = lin.max(axis=-1, keepdims=True), lin.min(axis=-1, keepdims=True)
    # Soft shoulder above GAMUT_KNEE: the brightest channel approaches 1 without reaching it, so
    # corrected highlights keep their gradation instead of piling up at 255.
    span = GAMUT_CEILING - GAMUT_KNEE
    allowed = np.where(hi_c > GAMUT_KNEE, GAMUT_KNEE + span * np.tanh((hi_c - GAMUT_KNEE) / span), hi_c)
    t = np.ones_like(y)
    t = np.where((hi_c > GAMUT_KNEE) & (hi_c - y > 1e-4), np.minimum(t, (allowed - y) / np.maximum(hi_c - y, 1e-6)), t)
    # Toe: a channel pushed below 0 lands just above it (at most GAMUT_FLOOR), continuous at 0.
    floor = GAMUT_FLOOR * np.tanh(-np.minimum(lo_c, 0.0) / GAMUT_FLOOR)
    t = np.where(lo_c < 0.0, np.minimum(t, (y - floor) / np.maximum(y - lo_c, 1e-6)), t)
    return y + (lin - y) * np.clip(t, 0.0, 1.0)


def skin_weight(rgb8: np.ndarray, face_boxes: list[list[int]]) -> np.ndarray:
    """Feathered 0..1 map of skin-coloured pixels around detected faces (face, neck, nearby skin)."""

    h, w, _ = rgb8.shape
    region = np.zeros((h, w), np.float32)
    for x, y, fw, fh in face_boxes:
        region[max(0, y - fh // 2) : min(h, y + 3 * fh), max(0, x - fw) : min(w, x + 2 * fw)] = 1.0
    if not region.any():
        return region
    lab = lab_of(rgb8)
    hue = np.degrees(np.arctan2(lab[..., 2], lab[..., 1]))
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    skin = (hue >= 15) & (hue <= 80) & (chroma >= 6) & (chroma <= 50) & (lab[..., 0] >= 25) & (lab[..., 0] <= 92)
    mask = (skin.astype(np.float32) * region)
    return cv2.GaussianBlur(mask, (0, 0), max(2.0, min(h, w) / 300))


def correct(rgb8: np.ndarray, neutral: dict[str, Any], haze: dict[str, float], strength: float, skin: np.ndarray | None = None) -> np.ndarray:
    """One deterministic pass: Bradford adaptation of the measured neutral, then a luma-anchored levels stretch.

    Skin keeps SKIN_KEEP of its original colour: removing a yellow cast from a scene must not
    strip the warmth skin is supposed to have.
    """

    src = rgb8.astype(np.float32) / 255.0
    img = src.copy()
    if neutral["reliable"] and len(neutral["tone_curve"]) > 2:
        # One adaptation matrix per tone knot, blended by each pixel's own L* (piecewise linear).
        knots = np.array(neutral["tone_curve"], dtype=np.float64)
        lin = to_linear(img)
        pixel_l = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)[..., 0]
        out = np.zeros_like(lin)
        for k, (kl, ka, kb) in enumerate(knots):
            left = knots[k - 1, 0] if k > 0 else kl - 1.0
            right = knots[k + 1, 0] if k + 1 < len(knots) else kl + 1.0
            w = np.where(pixel_l <= kl, (pixel_l - left) / max(kl - left, 1e-6), (right - pixel_l) / max(right - kl, 1e-6))
            w = np.clip(w, 0.0, 1.0)[..., None].astype(np.float32)
            if k == 0:
                w = np.where(pixel_l[..., None] <= kl, 1.0, w)
            if k + 1 == len(knots):
                w = np.where(pixel_l[..., None] >= kl, 1.0, w)
            m = adaptation_matrix((ka, kb), (ka * (1 - strength), kb * (1 - strength))).astype(np.float32)
            out += w * (lin @ m.T)
        img = to_srgb(gamut_pull(out)).astype(np.float32)
    if haze["haze"] >= HAZE_MIN:
        # Piecewise-linear L* curve through (0,0), (lo,lo_t), (hi,hi_t), (1,1): end points fixed,
        # so the stretch itself never clips; hue and a*b* stay as they are.
        lo, hi = haze["black_p05"], haze["white_p995"]
        lo_t = lo - strength * haze["lift"]
        hi_t = hi + strength * haze["headroom"]
        lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        lab[..., 0] = np.interp(lab[..., 0] / 100.0, [0.0, lo, hi, 1.0], [0.0, lo_t, hi_t, 1.0]).astype(np.float32) * 100.0
        img = to_srgb(gamut_pull(to_linear(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)))).astype(np.float32)
    if skin is not None and skin.any():
        keep = (SKIN_KEEP * skin)[..., None]
        img = img + keep * (src - img)
    return (np.clip(img, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


# ----------------------------------------------------------------- checks ---

def clip_ratio(rgb8: np.ndarray) -> float:
    return float(((rgb8.max(axis=-1) >= 255) | (rgb8.min(axis=-1) <= 0)).mean())


def faces(rgb8: np.ndarray) -> list[list[int]]:
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    gray = cv2.cvtColor(rgb8, cv2.COLOR_RGB2GRAY)
    found = casc.detectMultiScale(gray, 1.1, 6, minSize=(max(40, gray.shape[0] // 25),) * 2)
    return [[int(v) for v in f] for f in found]


def skin_hue(rgb8: np.ndarray, box: list[int]) -> list[float]:
    """[hue degrees, chroma] of the face centre; hue is only meaningful when chroma is not tiny."""

    x, y, w, h = box
    patch = rgb8[y + h // 4 : y + 3 * h // 4, x + w // 4 : x + 3 * w // 4]
    lab = lab_of(patch).reshape(-1, 3)
    a, b = float(np.median(lab[:, 1])), float(np.median(lab[:, 2]))
    return [round(float(np.degrees(np.arctan2(b, a))), 1), round(float(np.hypot(a, b)), 1)]


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cast = [r for r in rows if r["category_measured"] != "CONTROL"]
    control = [r for r in rows if r["category_measured"] == "CONTROL"]
    mono = [r["sample_id"] for r in cast if r["levels"]["light"]["delta_e00_mean"] < r["levels"]["medium"]["delta_e00_mean"] < r["levels"]["strong"]["delta_e00_mean"]]
    visible = [r["sample_id"] for r in cast if (r["levels"]["medium"].get("neutral_delta_e00_mean") or 0.0) >= GATE_MEDIUM_DE_ON_CAST]
    calm = [r["sample_id"] for r in control if r["levels"]["medium"]["delta_e00_mean"] <= GATE_MEDIUM_DE_ON_CONTROL]
    clip = [[r["sample_id"], n, v["clip_growth"]] for r in rows for n, v in r["levels"].items() if v["clip_growth"] > GATE_CLIP_GROWTH]
    skin = []
    for r in rows:
        for i, (hue0, chroma0) in enumerate(r["skin_hue_source_deg"]):
            if chroma0 < SKIN_MIN_CHROMA_FOR_HUE or not 15 <= hue0 <= 80:
                continue  # detector false positive: the box centre is not skin-coloured
            for n, v in r["levels"].items():
                hue1, chroma1 = v["skin_hue_deg"][i]
                if abs(hue1 - hue0) > GATE_SKIN_HUE_SHIFT or chroma1 < chroma0 * 0.6:
                    skin.append([r["sample_id"], n, hue0, hue1, chroma0, chroma1])
    return {
        "cast_samples": [r["sample_id"] for r in cast],
        "control_samples": [r["sample_id"] for r in control],
        "monotonic": f"{len(mono)}/{len(cast)}",
        "medium_visible_precheck": f"{len(visible)}/{len(cast)}", "medium_visible_ids": visible,
        "medium_visible_flag_for_review": [r["sample_id"] for r in cast if r["sample_id"] not in visible],
        "medium_visible_authority": "OWNER_VISUAL_REVIEW",
        "control_calm": f"{len(calm)}/{len(control)}", "control_calm_ids": calm,
        "clip_violations": clip,
        "skin_violations": skin,
        "max_seconds": max(r["seconds_three_levels"] for r in rows),
        "geometry_all_same": all(v["geometry_same"] for r in rows for v in r["levels"].values()),
    }


def detect_text_boxes(rgb8: np.ndarray, session: ort.InferenceSession) -> list[list[int]]:
    h, w, _ = rgb8.shape
    ratio = min(1.0, 1920 / max(h, w))
    rh, rw = max(32, int(round(h * ratio / 32)) * 32), max(32, int(round(w * ratio / 32)) * 32)
    resized = cv2.resize(rgb8, (rw, rh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    norm = (resized - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    prob = session.run(None, {session.get_inputs()[0].name: norm.transpose(2, 0, 1)[None]})[0][0, 0]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate((prob > 0.3).astype(np.uint8), np.ones((3, 3), np.uint8)))
    boxes = []
    for idx in range(1, count):
        x, y, bw, bh, area = stats[idx]
        if area < 12 or float(prob[labels == idx].mean()) < 0.5:
            continue
        pad = int(max(3, 0.6 * min(bw, bh)))
        boxes.append([max(0, int((x - pad) * w / rw)), max(0, int((y - pad) * h / rh)), min(w, int((x + bw + pad) * w / rw)), min(h, int((y + bh + pad) * h / rh))])
    return boxes


def neutral_offset_after(rgb8: np.ndarray, mask_view: np.ndarray) -> float:
    """Chroma of the original neutral pixels after correction (same pixels, so levels are comparable)."""

    lab = lab_of(analysis_view(rgb8))
    if not mask_view.any():
        return 0.0
    return round(float(np.hypot(np.median(lab[..., 1][mask_view]), np.median(lab[..., 2][mask_view]))), 2)


def save_png_srgb(rgb8: np.ndarray, path: Path) -> int:
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.fromarray(rgb8).save(path, format="PNG", icc_profile=icc, compress_level=6)
    with Image.open(path) as check:
        check.load()
        if check.size != (rgb8.shape[1], rgb8.shape[0]) or not check.info.get("icc_profile"):
            raise RuntimeError("OUTPUT_VERIFY_FAILED")
    return path.stat().st_size


def review_sheet(sid: str, label: str, panels: list[tuple[str, np.ndarray]], mask_view: np.ndarray, path: Path) -> None:
    cell = 520
    thumbs = []
    for title, arr in panels:
        im = Image.fromarray(arr)
        im.thumbnail((cell, cell))
        thumbs.append((title, im))
    h = max(t.height for _, t in thumbs)
    sheet = Image.new("RGB", (len(thumbs) * (cell + 10) + cell // 2 + 10, h + 70), "white")
    try:
        font = ImageFont.truetype("msyh.ttc", 22)
    except OSError:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(sheet)
    draw.text((10, 6), f"{sid}  {label}", fill="black", font=font)
    x = 0
    for title, im in thumbs:
        sheet.paste(im, (x, 40))
        draw.text((x + 4, 40 + im.height + 2), title, fill="black", font=font)
        x += cell + 10
    m = Image.fromarray((mask_view * 255).astype(np.uint8)).convert("RGB")
    m.thumbnail((cell // 2, cell // 2))
    sheet.paste(m, (x, 40))
    draw.text((x + 4, 40 + m.height + 2), "中性区域", fill="black", font=font)
    sheet.save(path, quality=90)


# ------------------------------------------------------------------- main ---

def classify(neutral: dict[str, Any], haze: dict[str, float]) -> str:
    # Same measure the correction acts on, so a sample is not "control" while being corrected.
    ab = tone_weighted_offset(neutral) if neutral["reliable"] else 0.0
    tags = []
    if ab >= CAST_MIN_AB:
        tags.append("YELLOW" if neutral["ab"][1] > 0 and abs(neutral["ab"][1]) >= abs(neutral["ab"][0]) else "BLUE" if neutral["ab"][1] < 0 and abs(neutral["ab"][1]) >= abs(neutral["ab"][0]) else "TINT")
    if haze["haze"] >= HAZE_MIN:
        tags.append("GREY")
    return "+".join(tags) if tags else "CONTROL"


def recommend(category: str, hints: list[str]) -> str:
    if category == "CONTROL":
        return "original"
    return "light" if hints else "medium"


def resummarize() -> int:
    """Recompute neutral-region ΔE from the saved outputs and re-evaluate gates; no correction is re-run."""

    path = safe_output_path("summary.json")
    summary = json.loads(path.read_text(encoding="utf-8"))
    for r in summary["rows"]:
        with Image.open(r["source_path"]) as opened:
            source = np.asarray(opened.convert("RGB"))
        mask_view = estimate_neutral(source).get("mask_view", np.zeros((1, 1), bool))
        for v in r["levels"].values():
            with Image.open(REPO_ROOT / v["path"]) as opened:
                out = np.asarray(opened.convert("RGB"))
            de = delta_e2000(analysis_view(source), analysis_view(out)).reshape(mask_view.shape) if mask_view.size > 1 else None
            v["neutral_delta_e00_mean"] = round(float(de[mask_view].mean()), 3) if de is not None and mask_view.any() else None
    summary["gates"]["medium_visibility_measure"] = "NEUTRAL_REGION_MEAN_DELTA_E00_PRECHECK_OWNER_REVIEW_FINAL"
    summary["gate_results"] = evaluate(summary["rows"])
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary["gate_results"], ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resummarize", action="store_true")
    args = parser.parse_args()
    if args.resummarize:
        return resummarize()
    block_network()
    started = datetime.now(timezone.utc).isoformat()

    samples = [p for root in SAMPLE_ROOTS for p in sorted(root.iterdir()) if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
    if args.limit:
        samples = samples[: args.limit]
    before = {str(p): sha256_file(p) for p in samples}
    detector = ort.InferenceSession(str(TEXT_DETECTOR), providers=["CPUExecutionProvider"])

    rows: list[dict[str, Any]] = []
    for index, sample in enumerate(samples, 1):
        sid = f"S{index:02d}"
        with Image.open(sample) as opened:
            has_alpha = "A" in opened.getbands()
            source = np.asarray(opened.convert("RGB"))

        t0 = time.perf_counter()
        neutral = estimate_neutral(source)
        haze = estimate_haze(source)
        face_boxes = faces(source)
        skin = skin_weight(source, face_boxes)
        outputs = {name: correct(source, neutral, haze, s, skin) for name, s in LEVELS.items()}
        seconds = time.perf_counter() - t0

        category = classify(neutral, haze)
        hints = intent_hint(source)
        text_boxes = detect_text_boxes(source, detector)
        text_mask = np.zeros(source.shape[:2], bool)
        for x0, y0, x1, y1 in text_boxes:
            text_mask[y0:y1, x0:x1] = True
        src_clip = clip_ratio(source)
        mask_view = neutral.get("mask_view", np.zeros((1, 1), bool))

        levels: dict[str, Any] = {}
        for name, out in outputs.items():
            path = safe_output_path(f"outputs/{sid}/{list(LEVELS).index(name) + 1}_{name}.png")
            size = save_png_srgb(out, path)
            de = delta_e2000(analysis_view(source), analysis_view(out))
            de_text = float(delta_e2000(source[text_mask][None], out[text_mask][None]).mean()) if text_mask.any() else None
            levels[name] = {
                "path": str(path.relative_to(REPO_ROOT)),
                "bytes": size,
                "delta_e00_mean": round(float(de.mean()), 3),
                "delta_e00_p95": round(float(np.percentile(de, 95)), 3),
                "neutral_delta_e00_mean": round(float(de.reshape(mask_view.shape)[mask_view].mean()), 3) if mask_view.any() and mask_view.size == de.size else None,
                "neutral_offset_after": neutral_offset_after(out, mask_view) if neutral["reliable"] else None,
                "clip_growth": round(clip_ratio(out) - src_clip, 5),
                "text_region_delta_e00": round(de_text, 3) if de_text is not None else None,
                "skin_hue_deg": [skin_hue(out, b) for b in face_boxes],
                "geometry_same": out.shape == source.shape,
            }
        review_sheet(
            sid, f"{category}  推荐:{recommend(category, hints)}  {sample.name}",
            [("原图", source), ("轻", outputs["light"]), ("中", outputs["medium"]), ("强", outputs["strong"])],
            mask_view, safe_output_path(f"review/{sid}_compare.jpg"),
        )
        row = {
            "sample_id": sid,
            "source_path": str(sample),
            "dimensions": f"{source.shape[1]}x{source.shape[0]}",
            "has_alpha": has_alpha,
            "category_measured": category,
            "intent_hints": hints,
            "recommended_level": recommend(category, hints),
            "neutral": {k: v for k, v in neutral.items() if k != "mask_view"},
            "neutral_offset_before": round(float(np.hypot(*neutral["ab"])), 2) if neutral["reliable"] else None,
            "tone_weighted_offset": tone_weighted_offset(neutral) if neutral["reliable"] else None,
            "haze": haze,
            "faces": len(face_boxes),
            "skin_hue_source_deg": [skin_hue(source, b) for b in face_boxes],
            "text_boxes": len(text_boxes),
            "seconds_three_levels": round(seconds, 3),
            "levels": levels,
        }
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("sample_id", "category_measured", "neutral_offset_before", "seconds_three_levels")}
                         | {n: (v["delta_e00_mean"], v["neutral_offset_after"], v["clip_growth"]) for n, v in levels.items()}, ensure_ascii=False), flush=True)

    after = {str(p): sha256_file(p) for p in samples}
    summary = {
        "task_id": TASK_ID,
        "started_at_utc": started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "network": "BLOCKED_IN_PROCESS_SOCKET_GUARD",
        "levels": LEVELS,
        "gates": {
            "medium_delta_e00_on_cast_min": GATE_MEDIUM_DE_ON_CAST,
            "medium_delta_e00_on_control_max": GATE_MEDIUM_DE_ON_CONTROL,
            "clip_growth_max": GATE_CLIP_GROWTH,
            "seconds_three_levels_max": GATE_SECONDS_THREE_LEVELS,
            "medium_visibility_measure": "NEUTRAL_REGION_MEAN_DELTA_E00_PRECHECK_OWNER_REVIEW_FINAL",
            "skin_hue_shift_max_deg": GATE_SKIN_HUE_SHIFT,
            "skin_chroma_keep_min": 0.6,
        },
        "samples_sha256_before": before,
        "samples_unchanged": before == after,
        "gate_results": evaluate(rows),
        "rows": rows,
    }
    safe_output_path("summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
