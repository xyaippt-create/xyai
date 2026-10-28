"""Reference-driven level pick (S66): move the target's white toward the reference's white.

The user picks the level; this module only measures how far the target's white sits from
the reference's, renders light / medium / strong and checks their safety. The method and
constants are the ones frozen by S65-REFCOLOR-POC route R3 (artifacts/s65_refcolor_poc).

Near-neutral pixels of both images are aligned in log-chromaticity (log R/G, log B/G of
linear RGB), where an illuminant cast is a pure translation at every lightness. The best
shift per lightness band is removed with linear-light channel gains that keep each
pixel's luminance. The reference contributes nothing else: no colours, no tone, no content.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .color_management import ManagedColorSource, load_color_managed_source
from .level_pick import (
    LEVELS,
    SKIN_KEEP,
    VISIBLE_ALPHA_MIN,
    LevelPickAnalysis,
    LevelPickError,
    LevelPickPreview,
    _gamut_pull,
    _lab,
    _to_linear,
    _to_srgb,
    analyze_level_pick,
    level_safety,
    pixel_sha256,
)


REFERENCE_LEVEL_PICK_VERSION = "hdde.color-reference-level-pick.v1"

ALIGN_REF_MAX_CHROMA = 30.0     # reference: only near-neutral pixels define "what white looks like"
ALIGN_TARGET_MAX_CHROMA = 50.0  # target: wide enough to still contain cast-shifted neutrals
ALIGN_BIN = 0.01                # log-chroma bin (~1% channel ratio)
ALIGN_RANGE = 0.8               # histogram covers ±0.8 in each axis
ALIGN_MAX_SHIFT = 0.40          # search window, ±0.40 (±49% channel ratio)
ALIGN_BANDS = ((15, 40), (40, 70), (70, 99))
ALIGN_MIN_PIXELS = 400
ALIGN_MIN_PEAK_RATIO = 1.15
ALIGN_BAND_MAX_DEVIATION = 0.15
ANALYSIS_LONG_EDGE = 768

# Description only (not a gate): a mid-grey moved by the measured shift, in Lab units.
NOTICEABLE_OFFSET = 3.0

_Y_ROW = np.array([0.2126729, 0.7151522, 0.0721750], np.float32)


def _view(rgb: np.ndarray, visible: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    scale = min(1.0, ANALYSIS_LONG_EDGE / max(rgb.shape[:2]))
    if scale == 1.0:
        return rgb, visible
    size = (round(rgb.shape[1] * scale), round(rgb.shape[0] * scale))
    return (
        cv2.resize(rgb, size, interpolation=cv2.INTER_AREA),
        cv2.resize(visible.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST).astype(bool),
    )


def _log_chroma(view: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lin = _to_linear(view.astype(np.float32) / 255.0) + 1e-4
    return np.log(lin[..., 0] / lin[..., 1]), np.log(lin[..., 2] / lin[..., 1]), _lab(view)


def _uv_hist(u: np.ndarray, v: np.ndarray, mask: np.ndarray) -> np.ndarray:
    n = int(round(2 * ALIGN_RANGE / ALIGN_BIN)) + 1
    edges = (np.arange(n + 1) - 0.5) * ALIGN_BIN - ALIGN_RANGE
    hist, _, _ = np.histogram2d(u[mask], v[mask], bins=[edges, edges])
    # sqrt keeps one large surface from outvoting every other neutral surface
    return cv2.GaussianBlur(np.sqrt(hist).astype(np.float32), (0, 0), 1.5)


def _align_shift(tu, tv, tmask, ru, rv, rmask) -> dict[str, Any]:
    """Shift d (log R/G, log B/G) such that target ≈ reference + d over near-neutral pixels."""

    if tmask.sum() < ALIGN_MIN_PIXELS or rmask.sum() < ALIGN_MIN_PIXELS:
        return {"reliable": False, "reason": "TOO_FEW_PIXELS", "shift": [0.0, 0.0]}
    ht, hr = _uv_hist(tu, tv, tmask), _uv_hist(ru, rv, rmask)
    pad = 2 * ht.shape[0]
    corr = np.fft.fftshift(np.real(np.fft.ifft2(np.fft.fft2(ht, (pad, pad)) * np.conj(np.fft.fft2(hr, (pad, pad))))))
    c = pad // 2
    k = int(round(ALIGN_MAX_SHIFT / ALIGN_BIN))
    window = corr[c - k:c + k + 1, c - k:c + k + 1]
    ia, ib = np.unravel_index(int(window.argmax()), window.shape)
    # sub-bin refinement: centroid of the 3x3 neighbourhood of the peak
    lo_a, lo_b = max(ia - 1, 0), max(ib - 1, 0)
    patch = np.clip(window[lo_a:ia + 2, lo_b:ib + 2], 0, None)
    ys, xs = np.mgrid[lo_a:lo_a + patch.shape[0], lo_b:lo_b + patch.shape[1]]
    du = (float((patch * ys).sum() / max(patch.sum(), 1e-9)) - k) * ALIGN_BIN
    dv = (float((patch * xs).sum() / max(patch.sum(), 1e-9)) - k) * ALIGN_BIN
    positive = window[window > 0]
    peak_ratio = float(window.max() / max(float(np.median(positive)) if positive.size else 1e-9, 1e-9))
    reliable = peak_ratio >= ALIGN_MIN_PEAK_RATIO
    return {"reliable": reliable, "reason": "OK" if reliable else "FLAT_ALIGNMENT",
            "shift": [round(du, 4), round(dv, 4)], "peak_ratio": round(peak_ratio, 2)}


def describe_shift(shift: list[float]) -> dict[str, Any]:
    """How a mid-grey of the target differs from the reference's, in words and Lab units."""

    grey = np.full((1, 1, 3), 0.18, np.float32) * np.array([np.exp(shift[0]), 1.0, np.exp(shift[1])], np.float32)
    grey = grey / float((grey[0, 0] @ _Y_ROW) / 0.18)
    lab = cv2.cvtColor(_to_srgb(grey).astype(np.float32), cv2.COLOR_RGB2LAB)[0, 0]
    a, b = float(lab[1]), float(lab[2])
    parts = []
    if abs(b) >= 1.5:
        parts.append("偏黄" if b > 0 else "偏蓝")
    if abs(a) >= 1.5:
        parts.append("偏品红" if a > 0 else "偏绿")
    offset = round(float(np.hypot(a, b)), 1)
    return {"lab_a": round(a, 1), "lab_b": round(b, 1), "offset": offset,
            "summary": ("目标图比参考图" + "、".join(parts)) if parts and offset >= NOTICEABLE_OFFSET else "两张图的色调已接近"}


@dataclass
class ReferencePlan:
    """Measured target-vs-reference shift plus the target's protection state."""

    target: LevelPickAnalysis
    usable: bool
    reason: str
    overall: dict[str, Any]
    bands: list[dict[str, Any]]
    description: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        offset = float(self.description.get("offset") or 0.0)
        recommended = "medium" if self.usable and offset >= NOTICEABLE_OFFSET else "original"
        return {
            "reference_level_pick_version": REFERENCE_LEVEL_PICK_VERSION,
            "usable": self.usable,
            "reason": self.reason,
            "overall_shift": list(self.overall.get("shift") or [0.0, 0.0]),
            "peak_ratio": self.overall.get("peak_ratio"),
            "bands": [dict(b) for b in self.bands],
            "description": dict(self.description),
            "recommended_level": recommended,
            "faces": len(self.target.face_boxes),
        }


def plan_reference(target: np.ndarray, reference: np.ndarray) -> ReferencePlan:
    """Measure how far the target's white sits from the reference's (RGB/RGBA uint8)."""

    t_visible = target[..., 3] >= VISIBLE_ALPHA_MIN if target.shape[2] == 4 else np.ones(target.shape[:2], bool)
    r_visible = reference[..., 3] >= VISIBLE_ALPHA_MIN if reference.shape[2] == 4 else np.ones(reference.shape[:2], bool)
    tview, tvis = _view(np.ascontiguousarray(target[..., :3]), t_visible)
    rview, rvis = _view(np.ascontiguousarray(reference[..., :3]), r_visible)
    tu, tv, tlab = _log_chroma(tview)
    ru, rv, rlab = _log_chroma(rview)

    def valid(view, lab, visible, max_chroma):
        clipped = (view.max(axis=-1) >= 254) | (view.min(axis=-1) <= 1)
        return visible & (lab[..., 0] > 15) & (lab[..., 0] < 99) & ~clipped & (np.hypot(lab[..., 1], lab[..., 2]) <= max_chroma)

    tm = valid(tview, tlab, tvis, ALIGN_TARGET_MAX_CHROMA)
    rm = valid(rview, rlab, rvis, ALIGN_REF_MAX_CHROMA)
    overall = _align_shift(tu, tv, tm, ru, rv, rm)
    bands = []
    for lo, hi in ALIGN_BANDS:
        res = _align_shift(tu, tv, tm & (tlab[..., 0] >= lo) & (tlab[..., 0] < hi), ru, rv, rm & (rlab[..., 0] >= lo) & (rlab[..., 0] < hi))
        # A band without its own evidence, or one that disagrees sharply with the whole image
        # (it locked onto a different surface), follows the whole-image alignment.
        own = res["reliable"] and float(np.hypot(res["shift"][0] - overall["shift"][0], res["shift"][1] - overall["shift"][1])) <= ALIGN_BAND_MAX_DEVIATION
        bands.append({"L": (lo + hi) / 2, "shift": res["shift"] if own else overall["shift"], "own": own,
                      "peak_ratio": res.get("peak_ratio"), "reason": res.get("reason")})
    usable = bool(overall["reliable"])
    return ReferencePlan(
        target=analyze_level_pick(target),
        usable=usable,
        reason=overall["reason"],
        overall=overall,
        bands=bands,
        description=describe_shift(overall["shift"]) if usable else {"summary": "这张参考图不适合用来校色（没有可用的中性区域）", "offset": 0.0},
    )


def render_reference_level(pixels: np.ndarray, plan: ReferencePlan, level: str) -> np.ndarray:
    """Deterministically render one level; alpha and fully transparent RGB stay byte-identical."""

    if level not in LEVELS:
        raise LevelPickError("LEVEL_PICK_UNKNOWN_LEVEL")
    if tuple(pixels.shape) != plan.target.source_shape:
        raise LevelPickError("LEVEL_PICK_ANALYSIS_SOURCE_MISMATCH")
    strength = LEVELS[level]
    src = pixels[..., :3].astype(np.float32) / 255.0
    img = src
    if plan.usable:
        lin = _to_linear(src)
        pixel_l = cv2.cvtColor(src, cv2.COLOR_RGB2LAB)[..., 0]
        # per-pixel shift, piecewise linear over band centres and flat beyond them (no pins)
        centres = np.array([b["L"] for b in plan.bands])
        du = np.interp(pixel_l, centres, [b["shift"][0] for b in plan.bands]).astype(np.float32)
        dv = np.interp(pixel_l, centres, [b["shift"][1] for b in plan.bands]).astype(np.float32)
        gain_r, gain_b = np.exp(-strength * du), np.exp(-strength * dv)
        # keep each pixel's luminance: only the chromaticity moves toward the reference
        norm = 1.0 / (_Y_ROW[0] * gain_r + _Y_ROW[1] + _Y_ROW[2] * gain_b)
        img = _to_srgb(_gamut_pull(lin * np.stack((gain_r * norm, norm, gain_b * norm), axis=-1)))
    if plan.target.skin is not None:
        img = img + (SKIN_KEEP * plan.target.skin)[..., None] * (src - img)
    rgb = (np.clip(img, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    if pixels.shape[2] == 3:
        return rgb
    out = np.dstack((rgb, pixels[..., 3]))
    transparent = pixels[..., 3] == 0
    out[transparent] = pixels[transparent]
    return out


@dataclass(frozen=True)
class ReferenceLevelPickPreview(LevelPickPreview):
    plan: ReferencePlan | None = None
    reference: ManagedColorSource | None = None


def build_reference_level_pick_preview(target_path: str | Path, reference_path: str | Path) -> ReferenceLevelPickPreview:
    """Decode both images through the formal colour-management boundary and render every level."""

    started = time.perf_counter()
    target = load_color_managed_source(target_path)
    reference = load_color_managed_source(reference_path)
    plan = plan_reference(target.pixels, reference.pixels)
    levels = {name: render_reference_level(target.pixels, plan, name) for name in LEVELS}
    safety = {name: level_safety(target.pixels, candidate, plan.target) for name, candidate in levels.items()}
    return ReferenceLevelPickPreview(
        source=target,
        analysis=plan.target,
        levels=levels,
        safety=safety,
        pixel_sha256={name: pixel_sha256(candidate) for name, candidate in levels.items()},
        processing_time_ms=int(round((time.perf_counter() - started) * 1000)),
        plan=plan,
        reference=reference,
    )


__all__ = [
    "REFERENCE_LEVEL_PICK_VERSION",
    "ReferenceLevelPickPreview",
    "ReferencePlan",
    "build_reference_level_pick_preview",
    "describe_shift",
    "plan_reference",
    "render_reference_level",
]
