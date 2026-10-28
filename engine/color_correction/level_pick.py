"""User-selected strength colour correction for AI-generated images (S64).

The user is the acceptance authority: this module measures the cast, renders
light / medium / strong candidates and checks their safety, but never decides
whether an image should be corrected.  The method and constants are the ones
frozen by S63-AICOLOR-POC (artifacts/s63_aicolor_poc/REPORT.md).
"""

from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .color_management import ManagedColorSource, load_color_managed_source


LEVEL_PICK_VERSION = "hdde.color-level-pick.v1"
LEVELS: dict[str, float] = {"light": 0.4, "medium": 0.7, "strong": 1.0}
LEVEL_LABELS = {"original": "原图", "light": "轻", "medium": "中", "strong": "强"}

ANALYSIS_LONG_EDGE = 768
VISIBLE_ALPHA_MIN = 3  # alpha <= ~1% carries no visible colour evidence

NEUTRAL_MAX_CHROMA = 30.0
NEUTRAL_RADIUS = 6.0
NEUTRAL_MIN_SHARE = 0.03
NEUTRAL_MIN_CELLS = 4
TONE_BANDS = ((15, 35), (35, 55), (55, 70), (70, 82), (82, 92), (92, 99))
BAND_RADIUS = 9.0

CAST_MIN_AB = 6.0
HAZE_MIN = 0.06
VEIL_MAX_CHROMA = 12.0

GAMUT_KNEE = 0.85
GAMUT_CEILING = 0.995
GAMUT_FLOOR = 0.002
SKIN_KEEP = 0.8

# Safety gates every rendered level must pass before it may be offered.
GATE_CLIP_GROWTH = 0.005
GATE_SKIN_HUE_SHIFT = 10.0
GATE_SKIN_CHROMA_KEEP = 0.6
SKIN_MIN_CHROMA_FOR_HUE = 10.0

_SRGB_TO_XYZ = np.array(
    [[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]]
)
_XYZ_TO_SRGB = np.linalg.inv(_SRGB_TO_XYZ)
_BRADFORD = np.array([[0.8951, 0.2664, -0.1614], [-0.7502, 1.7135, 0.0367], [0.0389, -0.0685, 1.0296]])
_D65 = np.array([0.95047, 1.0, 1.08883])
_Y_ROW = _SRGB_TO_XYZ[1].astype(np.float32)


class LevelPickError(ValueError):
    """A request the level-pick contract cannot serve (unknown level, unsafe output)."""


# ------------------------------------------------------------- colour math ---

def _to_linear(srgb: np.ndarray) -> np.ndarray:
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4).astype(np.float32)


# Exact per-value table of _to_linear for 8-bit input: same float32 arithmetic, ~10x faster.
_LINEAR_LUT = _to_linear(np.arange(256, dtype=np.float32) / 255.0)


def _to_srgb(linear: np.ndarray) -> np.ndarray:
    linear = np.clip(linear, 0.0, 1.0)
    return np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055).astype(np.float32)


def _lab(rgb: np.ndarray) -> np.ndarray:
    """Lab of uint8 or 0..1 float RGB (OpenCV D65, L in 0..100)."""

    data = rgb.astype(np.float32) / 255.0 if rgb.dtype == np.uint8 else rgb.astype(np.float32)
    return cv2.cvtColor(data, cv2.COLOR_RGB2LAB)


def _lab_to_xyz(l: float, a: float, b: float) -> np.ndarray:
    fy = (l + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200

    def finv(t: float) -> float:
        return t**3 if t**3 > 0.008856 else (t - 16 / 116) / 7.787

    return np.array([finv(fx), finv(fy), finv(fz)]) * _D65


def _adaptation_matrix(src_ab: tuple[float, float], dst_ab: tuple[float, float]) -> np.ndarray:
    """Linear-sRGB Bradford matrix moving a grey of chromaticity src_ab to dst_ab, Y preserved."""

    ws = _lab_to_xyz(100.0, *src_ab)
    wd = _lab_to_xyz(100.0, *dst_ab)
    ws, wd = ws / ws[1], wd / wd[1]
    cone = np.diag((_BRADFORD @ wd) / (_BRADFORD @ ws))
    return (_XYZ_TO_SRGB @ np.linalg.inv(_BRADFORD) @ cone @ _BRADFORD @ _SRGB_TO_XYZ).astype(np.float32)


def _gamut_pull(lin: np.ndarray) -> np.ndarray:
    """Pull out-of-range channels toward the pixel's luminance with a soft shoulder and toe.

    The brightest channel approaches GAMUT_CEILING without reaching 1 and a channel pushed
    below 0 lands at most GAMUT_FLOOR above it, so corrected highlights and deep colours
    keep their gradation instead of piling up at 255 or 0.
    """

    y = np.clip(np.einsum("...k,k->...", lin, _Y_ROW)[..., None], 0.0, 1.0)
    hi_c, lo_c = lin.max(axis=-1, keepdims=True), lin.min(axis=-1, keepdims=True)
    t = np.ones_like(y)
    # Only pixels near the gamut edge need the shoulder/toe; t stays exactly 1 elsewhere.
    edge = (hi_c > GAMUT_KNEE) | (lo_c < 0.0)
    if edge.any():
        ye, he, le = y[edge], hi_c[edge], lo_c[edge]
        span = GAMUT_CEILING - GAMUT_KNEE
        allowed = np.where(he > GAMUT_KNEE, GAMUT_KNEE + span * np.tanh((he - GAMUT_KNEE) / span), he)
        te = np.ones_like(ye)
        te = np.where((he > GAMUT_KNEE) & (he - ye > 1e-4), np.minimum(te, (allowed - ye) / np.maximum(he - ye, 1e-6)), te)
        floor = GAMUT_FLOOR * np.tanh(-np.minimum(le, 0.0) / GAMUT_FLOOR)
        te = np.where(le < 0.0, np.minimum(te, (ye - floor) / np.maximum(ye - le, 1e-6)), te)
        t[edge] = te
    return y + (lin - y) * np.clip(t, 0.0, 1.0)


def delta_e2000(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Per-pixel CIEDE2000 between two RGB arrays of the same shape."""

    l1, a1, b1 = _lab(a).reshape(-1, 3).astype(np.float64).T
    l2, a2, b2 = _lab(b).reshape(-1, 3).astype(np.float64).T
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
        c1p * c2p == 0, hsum,
        np.where(np.abs(h1p - h2p) <= 180, hsum / 2, np.where(hsum < 360, (hsum + 360) / 2, (hsum - 360) / 2)),
    )
    t = (1 - 0.17 * np.cos(np.radians(hbar - 30)) + 0.24 * np.cos(np.radians(2 * hbar))
         + 0.32 * np.cos(np.radians(3 * hbar + 6)) - 0.20 * np.cos(np.radians(4 * hbar - 63)))
    sl = 1 + 0.015 * (lbar - 50) ** 2 / np.sqrt(20 + (lbar - 50) ** 2)
    sc, sh = 1 + 0.045 * cbarp, 1 + 0.015 * cbarp * t
    rt = -2 * np.sqrt(cbarp**7 / (cbarp**7 + 25.0**7)) * np.sin(np.radians(60 * np.exp(-(((hbar - 275) / 25) ** 2))))
    return np.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dhp / sh) ** 2 + rt * (dcp / sc) * (dhp / sh))


# ---------------------------------------------------------------- analysis ---

def _analysis_scale(shape: tuple[int, ...]) -> float:
    return min(1.0, ANALYSIS_LONG_EDGE / max(shape[0], shape[1]))


def _analysis_view(rgb: np.ndarray, visible: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    scale = _analysis_scale(rgb.shape)
    if scale == 1.0:
        return rgb, visible
    size = (round(rgb.shape[1] * scale), round(rgb.shape[0] * scale))
    view = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
    mask = cv2.resize(visible.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST).astype(bool)
    return view, mask


def _grid_cells(mask: np.ndarray, minimum: float) -> int:
    gh, gw = mask.shape[0] // 4, mask.shape[1] // 4
    if gh == 0 or gw == 0:
        return 0
    return sum(int(mask[r * gh:(r + 1) * gh, c * gw:(c + 1) * gw].mean() > minimum) for r in range(4) for c in range(4))


def _estimate_neutral(view: np.ndarray, visible: np.ndarray) -> dict[str, Any]:
    """Dominant low-chroma cluster closest to neutral, plus a per-lightness cast curve.

    Pixels above NEUTRAL_MAX_CHROMA (brand reds, orange fields, green walls) never vote.
    When several low-chroma clusters exist (white clouds and blue sky) the one closest to
    neutral wins: a real cast moves all of them, a coloured backdrop is only one of them.
    """

    lab = _lab(view)
    l, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    chroma = np.hypot(a, b)
    clipped = (view.max(axis=-1) >= 254) | (view.min(axis=-1) <= 1)
    cand = visible & (l > 15) & (l < 97) & (chroma <= NEUTRAL_MAX_CHROMA) & ~clipped
    unreliable = {"reliable": False, "ab": [0.0, 0.0], "share": 0.0, "grid_cells": 0, "tone_curve": []}
    if cand.sum() < 200:
        return {**unreliable, "reason": "TOO_FEW_LOW_CHROMA_PIXELS"}

    weight = (1 - chroma[cand] / NEUTRAL_MAX_CHROMA) * np.clip((l[cand] - 15) / 50, 0.2, 1.0)
    edges = np.arange(-NEUTRAL_MAX_CHROMA, NEUTRAL_MAX_CHROMA + 1.0, 1.0)
    hist, _, _ = np.histogram2d(a[cand], b[cand], bins=[edges, edges], weights=weight)
    hist = cv2.GaussianBlur(hist.astype(np.float32), (0, 0), 2.0)
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
    cells = _grid_cells(near, 0.01)
    reliable = share >= NEUTRAL_MIN_SHARE and cells >= NEUTRAL_MIN_CELLS
    return {
        "reliable": reliable,
        "reason": "OK" if reliable else ("NEUTRAL_SHARE_LOW" if share < NEUTRAL_MIN_SHARE else "NEUTRAL_NOT_SPREAD"),
        "ab": [round(float(peak[0]), 2), round(float(peak[1]), 2)],
        "share": round(share, 4),
        "grid_cells": cells,
        "tone_curve": _tone_cast_curve(l, a, b, cand, peak) if reliable else [],
    }


def _tone_cast_curve(l: np.ndarray, a: np.ndarray, b: np.ndarray, cand: np.ndarray, peak: np.ndarray) -> list[list[float]]:
    """[L*, a*, b*] knots per lightness band; white pinned neutral, black extends the darkest band.

    AI renders often keep clean whites while midtones carry the cast. A band counts only when
    its neutral pixels sit close to the global neutral and are spread over the frame.
    """

    knots: list[list[float]] = []
    for lo, hi in TONE_BANDS:
        near = cand & (l >= lo) & (l < hi) & (np.hypot(a - peak[0], b - peak[1]) <= BAND_RADIUS)
        if near.sum() < 0.005 * l.size or _grid_cells(near, 0.005) < NEUTRAL_MIN_CELLS:
            continue
        knots.append([round((lo + hi) / 2, 1), round(float(np.median(a[near])), 2), round(float(np.median(b[near])), 2)])
    if not knots:
        return []
    return [[0.0, knots[0][1], knots[0][2]], *knots, [100.0, 0.0, 0.0]]


def _estimate_haze(view: np.ndarray, visible: np.ndarray) -> dict[str, float]:
    """Lifted black point / missing white headroom on L*, only when that veil is greyish."""

    lab = _lab(view)
    luma, chroma = lab[..., 0][visible] / 100.0, np.hypot(lab[..., 1], lab[..., 2])[visible]
    if luma.size == 0:
        return {"black": 0.0, "white": 1.0, "lift": 0.0, "headroom": 0.0, "haze": 0.0}
    lo, hi = float(np.percentile(luma, 0.5)), float(np.percentile(luma, 99.5))
    dark_chroma = float(np.median(chroma[luma <= np.percentile(luma, 2)]))
    light_chroma = float(np.median(chroma[luma >= np.percentile(luma, 98)]))
    lift = max(0.0, lo - 0.03) if dark_chroma <= VEIL_MAX_CHROMA else 0.0
    headroom = max(0.0, 0.95 - hi) if light_chroma <= VEIL_MAX_CHROMA else 0.0
    return {"black": round(lo, 4), "white": round(hi, 4), "lift": round(lift, 4), "headroom": round(headroom, 4), "haze": round(lift + headroom, 4)}


def _intent_hints(view: np.ndarray, visible: np.ndarray) -> list[str]:
    lab = _lab(view)
    l, chroma = lab[..., 0][visible], np.hypot(lab[..., 1], lab[..., 2])[visible]
    if l.size == 0:
        return []
    hints = []
    if float(np.median(l)) > 78:
        hints.append("HIGH_KEY")
    if float(np.median(l)) < 28:
        hints.append("LOW_KEY")
    if float((chroma > 45).mean()) > 0.35:
        hints.append("DOMINANT_SATURATED_COLOUR")
    return hints


def _faces(rgb: np.ndarray) -> list[list[int]]:
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    found = cascade.detectMultiScale(gray, 1.1, 6, minSize=(max(40, gray.shape[0] // 25),) * 2)
    return [[int(v) for v in box] for box in found]


def _skin_weight(rgb: np.ndarray, face_boxes: list[list[int]]) -> np.ndarray | None:
    """Feathered 0..1 map of skin-coloured pixels around detected faces."""

    h, w, _ = rgb.shape
    region = np.zeros((h, w), np.float32)
    for x, y, fw, fh in face_boxes:
        region[max(0, y - fh // 2):min(h, y + 3 * fh), max(0, x - fw):min(w, x + 2 * fw)] = 1.0
    if not region.any():
        return None
    lab = _lab(rgb)
    hue = np.degrees(np.arctan2(lab[..., 2], lab[..., 1]))
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    skin = (hue >= 15) & (hue <= 80) & (chroma >= 6) & (chroma <= 50) & (lab[..., 0] >= 25) & (lab[..., 0] <= 92)
    return cv2.GaussianBlur(skin.astype(np.float32) * region, (0, 0), max(2.0, min(h, w) / 300))


def _skin_hue(rgb: np.ndarray, box: list[int]) -> tuple[float, float]:
    x, y, w, h = box
    lab = _lab(rgb[y + h // 4:y + 3 * h // 4, x + w // 4:x + 3 * w // 4]).reshape(-1, 3)
    a, b = float(np.median(lab[:, 1])), float(np.median(lab[:, 2]))
    return float(np.degrees(np.arctan2(b, a))), float(np.hypot(a, b))


@dataclass
class LevelPickAnalysis:
    """Measurement of one source plus the reusable state needed to render every level."""

    source_shape: tuple[int, ...]
    neutral: dict[str, Any]
    haze: dict[str, float]
    intent_hints: list[str]
    face_boxes: list[list[int]]
    category: str
    measured_offset: float
    recommended_level: str
    neutral_mask_view: np.ndarray = field(repr=False)
    skin: np.ndarray | None = field(default=None, repr=False)

    def to_record(self) -> dict[str, Any]:
        return {
            "level_pick_version": LEVEL_PICK_VERSION,
            "category": self.category,
            "measured_offset": self.measured_offset,
            "recommended_level": self.recommended_level,
            "intent_hints": list(self.intent_hints),
            "neutral": dict(self.neutral),
            "haze": dict(self.haze),
            "faces": len(self.face_boxes),
        }


def _classify(neutral: dict[str, Any], haze: dict[str, float]) -> tuple[str, float]:
    inner = neutral.get("tone_curve", [])[1:-1]
    offset = round(float(np.mean([np.hypot(k[1], k[2]) for k in inner])), 2) if neutral["reliable"] and inner else 0.0
    tags = []
    if offset >= CAST_MIN_AB:
        a, b = neutral["ab"]
        if abs(b) >= abs(a):
            tags.append("YELLOW" if b > 0 else "BLUE")
        else:
            tags.append("TINT")
    if haze["haze"] >= HAZE_MIN:
        tags.append("GREY")
    return ("+".join(tags) if tags else "NO_CAST"), offset


def analyze_level_pick(pixels: np.ndarray) -> LevelPickAnalysis:
    """Measure cast, haze and protection regions of an RGB/RGBA uint8 working-domain image."""

    rgb = np.ascontiguousarray(pixels[..., :3])
    visible = pixels[..., 3] >= VISIBLE_ALPHA_MIN if pixels.shape[2] == 4 else np.ones(rgb.shape[:2], bool)
    view, visible_view = _analysis_view(rgb, visible)
    neutral = _estimate_neutral(view, visible_view)
    haze = _estimate_haze(view, visible_view)
    hints = _intent_hints(view, visible_view)
    category, offset = _classify(neutral, haze)
    # Recommendation only: a measured problem gets a level, deliberate-looking colour a gentler one.
    recommended = "original" if category == "NO_CAST" else ("light" if hints else "medium")
    lab = _lab(view)
    near = (
        visible_view
        & (np.hypot(lab[..., 1] - neutral["ab"][0], lab[..., 2] - neutral["ab"][1]) <= NEUTRAL_RADIUS)
        & (np.hypot(lab[..., 1], lab[..., 2]) <= NEUTRAL_MAX_CHROMA)
        if neutral["reliable"] else np.zeros(view.shape[:2], bool)
    )
    face_boxes = _faces(rgb)
    return LevelPickAnalysis(
        source_shape=tuple(pixels.shape),
        neutral=neutral,
        haze=haze,
        intent_hints=hints,
        face_boxes=face_boxes,
        category=category,
        measured_offset=offset,
        recommended_level=recommended,
        neutral_mask_view=near,
        skin=_skin_weight(rgb, face_boxes),
    )


# --------------------------------------------------------------- rendering ---

@dataclass(frozen=True)
class _RenderBase:
    """Level-independent state of one source: computed once, shared by every level."""

    pixels: np.ndarray
    src: np.ndarray
    # Per knot: flat indices of the pixels it touches, their blend weights and linear RGB.
    # Each pixel sits between two knots, so this is ~2N work instead of N per knot.
    knot_pixels: list[tuple[np.ndarray, np.ndarray, np.ndarray]]
    knots: np.ndarray | None


def _prepare_render(pixels: np.ndarray, analysis: LevelPickAnalysis) -> _RenderBase:
    if tuple(pixels.shape) != analysis.source_shape:
        raise LevelPickError("LEVEL_PICK_ANALYSIS_SOURCE_MISMATCH")
    src = pixels[..., :3].astype(np.float32) / 255.0
    curve = analysis.neutral.get("tone_curve") or []
    if not (analysis.neutral["reliable"] and len(curve) > 2):
        return _RenderBase(pixels, src, [], None)
    knots = np.array(curve, dtype=np.float64)
    pixel_l = cv2.cvtColor(src, cv2.COLOR_RGB2LAB)[..., 0]
    lin_flat = _LINEAR_LUT[pixels[..., :3]].reshape(-1, 3)
    knot_pixels = []
    # Piecewise-linear blend weights of each tone knot by the pixel's own L*.
    for k, (kl, _ka, _kb) in enumerate(knots):
        left = knots[k - 1, 0] if k > 0 else kl - 1.0
        right = knots[k + 1, 0] if k + 1 < len(knots) else kl + 1.0
        w = np.where(pixel_l <= kl, (pixel_l - left) / max(kl - left, 1e-6), (right - pixel_l) / max(right - kl, 1e-6))
        w = np.clip(w, 0.0, 1.0)[..., None].astype(np.float32)
        if k == 0:
            w = np.where(pixel_l[..., None] <= kl, 1.0, w)
        if k + 1 == len(knots):
            w = np.where(pixel_l[..., None] >= kl, 1.0, w)
        w_flat = w.reshape(-1)
        # A zero weight only ever adds +/-0.0, so skipping those pixels leaves the sum unchanged.
        idx = np.flatnonzero(w_flat)
        knot_pixels.append((idx, w_flat[idx][:, None], lin_flat[idx]))
    return _RenderBase(pixels, src, knot_pixels, knots)


def _render_prepared(base: _RenderBase, analysis: LevelPickAnalysis, level: str) -> np.ndarray:
    if level not in LEVELS:
        raise LevelPickError("LEVEL_PICK_UNKNOWN_LEVEL")
    strength = LEVELS[level]
    pixels, src = base.pixels, base.src
    img = src
    if base.knots is not None:
        out = np.zeros((src.shape[0] * src.shape[1], 3), np.float32)
        for (kl, ka, kb), (idx, w, lin) in zip(base.knots, base.knot_pixels):
            m = _adaptation_matrix((ka, kb), (ka * (1 - strength), kb * (1 - strength)))
            out[idx] += w * np.einsum("ij,kj->ik", lin, m)
        img = _to_srgb(_gamut_pull(out.reshape(src.shape)))
    if analysis.haze["haze"] >= HAZE_MIN:
        lo, hi = analysis.haze["black"], analysis.haze["white"]
        lo_t, hi_t = lo - strength * analysis.haze["lift"], hi + strength * analysis.haze["headroom"]
        lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        lab[..., 0] = np.interp(lab[..., 0] / 100.0, [0.0, lo, hi, 1.0], [0.0, lo_t, hi_t, 1.0]).astype(np.float32) * 100.0
        img = _to_srgb(_gamut_pull(_to_linear(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB))))
    if analysis.skin is not None:
        img = img + (SKIN_KEEP * analysis.skin)[..., None] * (src - img)
    rgb = (np.clip(img, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    if pixels.shape[2] == 3:
        return rgb
    out_rgba = np.dstack((rgb, pixels[..., 3]))
    transparent = pixels[..., 3] == 0
    out_rgba[transparent] = pixels[transparent]
    return out_rgba


def render_level(pixels: np.ndarray, analysis: LevelPickAnalysis, level: str) -> np.ndarray:
    """Deterministically render one level; alpha and fully transparent RGB stay byte-identical."""

    if level not in LEVELS:
        raise LevelPickError("LEVEL_PICK_UNKNOWN_LEVEL")
    return _render_prepared(_prepare_render(pixels, analysis), analysis, level)


def _clip_ratio(rgb: np.ndarray) -> float:
    return float(((rgb.max(axis=-1) >= 255) | (rgb.min(axis=-1) <= 0)).mean())


def level_safety(pixels: np.ndarray, candidate: np.ndarray, analysis: LevelPickAnalysis) -> dict[str, Any]:
    """Hard gates a level must pass before it may be offered or published."""

    failures: list[str] = []
    if candidate.shape != pixels.shape or candidate.dtype != np.uint8:
        failures.append("GEOMETRY_OR_DEPTH_CHANGED")
    if pixels.shape[2] == 4 and not np.array_equal(candidate[..., 3], pixels[..., 3]):
        failures.append("ALPHA_CHANGED")
    clip_growth = _clip_ratio(candidate[..., :3]) - _clip_ratio(pixels[..., :3])
    if clip_growth > GATE_CLIP_GROWTH:
        failures.append("CLIPPING_GROWTH")
    skin = []
    for box in analysis.face_boxes:
        hue0, chroma0 = _skin_hue(pixels[..., :3], box)
        if chroma0 < SKIN_MIN_CHROMA_FOR_HUE or not 15 <= hue0 <= 80:
            continue  # the box centre is not skin-coloured: detector false positive
        hue1, chroma1 = _skin_hue(candidate[..., :3], box)
        skin.append({"hue_before": round(hue0, 1), "hue_after": round(hue1, 1), "chroma_before": round(chroma0, 1), "chroma_after": round(chroma1, 1)})
        if abs(hue1 - hue0) > GATE_SKIN_HUE_SHIFT or chroma1 < chroma0 * GATE_SKIN_CHROMA_KEEP:
            failures.append("SKIN_COLOUR_SHIFT")
    scale = _analysis_scale(pixels.shape)
    size = (round(pixels.shape[1] * scale), round(pixels.shape[0] * scale))
    src_view = cv2.resize(pixels[..., :3], size, interpolation=cv2.INTER_AREA) if scale < 1 else pixels[..., :3]
    out_view = cv2.resize(candidate[..., :3], size, interpolation=cv2.INTER_AREA) if scale < 1 else candidate[..., :3]
    de = delta_e2000(src_view, out_view).reshape(src_view.shape[:2])
    mask = analysis.neutral_mask_view
    return {
        "passed": not failures,
        "failures": sorted(set(failures)),
        "clip_growth": round(clip_growth, 5),
        "delta_e00_mean": round(float(de.mean()), 3),
        "neutral_delta_e00_mean": round(float(de[mask].mean()), 3) if mask.shape == de.shape and mask.any() else None,
        "skin": skin,
    }


def pixel_sha256(pixels: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(str(pixels.shape).encode())
    digest.update(np.ascontiguousarray(pixels).tobytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class LevelPickPreview:
    source: ManagedColorSource
    analysis: LevelPickAnalysis
    levels: dict[str, np.ndarray]
    safety: dict[str, dict[str, Any]]
    pixel_sha256: dict[str, str]
    processing_time_ms: int


def build_level_pick_preview(source_path: str | Path) -> LevelPickPreview:
    """Decode through the formal colour-management boundary and render every level."""

    started = time.perf_counter()
    source = load_color_managed_source(source_path)
    pixels = source.pixels
    analysis = analyze_level_pick(pixels)
    # The levels render in parallel threads. Every matrix product on this path is einsum, not
    # BLAS: concurrent OpenBLAS calls from several threads crashed (access violation) on 4K input.
    base = _prepare_render(pixels, analysis)

    def one(name: str) -> tuple[np.ndarray, dict[str, Any]]:
        candidate = _render_prepared(base, analysis, name)
        return candidate, level_safety(pixels, candidate, analysis)

    with ThreadPoolExecutor(max_workers=len(LEVELS)) as pool:
        rendered = dict(zip(LEVELS, pool.map(one, LEVELS)))
    levels = {name: item[0] for name, item in rendered.items()}
    safety = {name: item[1] for name, item in rendered.items()}
    return LevelPickPreview(
        source=source,
        analysis=analysis,
        levels=levels,
        safety=safety,
        pixel_sha256={name: pixel_sha256(candidate) for name, candidate in levels.items()},
        processing_time_ms=int(round((time.perf_counter() - started) * 1000)),
    )


__all__ = [
    "LEVEL_LABELS",
    "LEVEL_PICK_VERSION",
    "LEVELS",
    "LevelPickAnalysis",
    "LevelPickError",
    "LevelPickPreview",
    "analyze_level_pick",
    "build_level_pick_preview",
    "delta_e2000",
    "level_safety",
    "pixel_sha256",
    "render_level",
]
