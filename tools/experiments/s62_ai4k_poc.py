"""S62-AI4K-POC: local faithful 4K enhancement candidates for AI-generated images.

Research-only and isolated from the formal 4K/1080P pipelines, API, UI,
Settings and the output center.  Every write goes to OUTPUT_ROOT.  Inputs in
the user sample folder are read-only and re-hashed after the run.

Candidate routes (both run fully offline; sockets are blocked in-process):
  R1  Real-ESRGAN x2plus -> LANCZOS to 3840 -> back-projection lock -> text guard
  R2  Real-ESRGAN x4plus -> LANCZOS to 3840 -> back-projection lock -> text guard

The weights are accepted for local PoC evaluation only; their training-data
rights are not cleared for HDDE product use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import onnxruntime as ort
import psutil
import torch
from PIL import Image, ImageDraw
from torch import nn
from torch.nn import functional as F


REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "S62-AI4K-POC"
SAMPLE_ROOT = Path(r"D:\HDDE样本\AI4K")
OUTPUT_ROOT = REPO_ROOT / "artifacts" / "s62_ai4k_poc"
MODEL_ROOT = REPO_ROOT / "models" / "s62_ai4k_poc"
TARGET_LONG_EDGE = 3840
# Tiles overlap by 2*TILE_PAD and are feather-blended; a hard core cut left a visible
# detail-onset seam on S07 in the first review.
TILE = 256
TILE_PAD = 48
GATE_SEAM_DETAIL_JUMP = 2.0

# Gates from the approved principle; never loosened inside the PoC.
# GATE_SIZE_RATIO calibrated 1.5 -> 2.0 by the product owner on 2026-10-27.
GATE_ROUNDTRIP_PSNR_DB = 38.0
GATE_DELTA_E2000_MEAN = 1.0
GATE_SECONDS_PER_IMAGE = 120.0
GATE_SIZE_RATIO = 2.0

MODELS = {
    "R1_REALESRGAN_X2PLUS": {
        "file": "RealESRGAN_x2plus.pth",
        "sha256": "49fafd45f8fd7aa8d31ab2a22d14d91b536c34494a5cfe31eb5d89c2fa266abb",
        "scale": 2,
        "source": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth",
    },
    "R2_REALESRGAN_X4PLUS": {
        "file": "RealESRGAN_x4plus.pth",
        "sha256": "4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1",
        "scale": 4,
        "source": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
    },
}
TEXT_DETECTOR = {
    "file": "ch_PP-OCRv4_det_infer.onnx",
    "sha256": "d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9",
    "source": "https://huggingface.co/SWHL/RapidOCR/resolve/main/PP-OCRv4/ch_PP-OCRv4_det_infer.onnx",
}

# Non-text marks the text detector cannot see.  Normalized xyxy on the source.
MANUAL_PROTECT_BOXES: dict[str, list[list[float]]] = {
    # Brush-calligraphy title "墨刃" is missed by the DB detector.
    "ChatGPT Image 2026年6月28日 16_54_53.png": [[0.19, 0.04, 0.40, 0.84]],
    # Bottle emblems, "SINCE 1903" ring and embossed glass lettering are logos, not detected text.
    "ChatGPT Image 2026年6月30日 12_20_14.png": [
        [0.42, 0.235, 0.53, 0.328],
        [0.378, 0.476, 0.581, 0.725],
        [0.41, 0.373, 0.55, 0.407],
    ],
}


# ---------------------------------------------------------------- safety ---

class _OfflineSocket(socket.socket):
    def __init__(self, *args, **kwargs):  # noqa: D401
        raise RuntimeError("NETWORK_BLOCKED_BY_S62_POC")


def block_network() -> None:
    socket.socket = _OfflineSocket  # type: ignore[misc]
    socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("NETWORK_BLOCKED_BY_S62_POC"))  # type: ignore[assignment]


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


def peak_working_set_mb() -> float:
    """Process-lifetime peak working set (Windows), so it is cumulative across samples."""

    return round(psutil.Process().memory_info().peak_wset / 2**20, 1)


# --------------------------------------------------------------- RRDBNet ---

class ResidualDenseBlock(nn.Module):
    def __init__(self, nf: int = 64, gc: int = 32) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(nf, gc, 3, 1, 1)
        self.conv2 = nn.Conv2d(nf + gc, gc, 3, 1, 1)
        self.conv3 = nn.Conv2d(nf + 2 * gc, gc, 3, 1, 1)
        self.conv4 = nn.Conv2d(nf + 3 * gc, gc, 3, 1, 1)
        self.conv5 = nn.Conv2d(nf + 4 * gc, nf, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(0.2, inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x1 = self.lrelu(self.conv1(x))
        x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
        x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
        x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
        x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
        return x5 * 0.2 + x


class RRDB(nn.Module):
    def __init__(self, nf: int = 64, gc: int = 32) -> None:
        super().__init__()
        self.rdb1 = ResidualDenseBlock(nf, gc)
        self.rdb2 = ResidualDenseBlock(nf, gc)
        self.rdb3 = ResidualDenseBlock(nf, gc)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.rdb3(self.rdb2(self.rdb1(x))) * 0.2 + x


class RRDBNet(nn.Module):
    def __init__(self, scale: int, nf: int = 64, nb: int = 23, gc: int = 32) -> None:
        super().__init__()
        self.scale = scale
        in_ch = 3 * (16 if scale == 1 else 4 if scale == 2 else 1)
        self.conv_first = nn.Conv2d(in_ch, nf, 3, 1, 1)
        self.body = nn.Sequential(*[RRDB(nf, gc) for _ in range(nb)])
        self.conv_body = nn.Conv2d(nf, nf, 3, 1, 1)
        self.conv_up1 = nn.Conv2d(nf, nf, 3, 1, 1)
        self.conv_up2 = nn.Conv2d(nf, nf, 3, 1, 1)
        self.conv_hr = nn.Conv2d(nf, nf, 3, 1, 1)
        self.conv_last = nn.Conv2d(nf, 3, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(0.2, inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.scale == 2:
            x = F.pixel_unshuffle(x, 2)
        elif self.scale == 1:
            x = F.pixel_unshuffle(x, 4)
        feat = self.conv_first(x)
        feat = feat + self.conv_body(self.body(feat))
        feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode="nearest")))
        feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode="nearest")))
        return self.conv_last(self.lrelu(self.conv_hr(feat)))


def load_model(route: str) -> RRDBNet:
    spec = MODELS[route]
    path = MODEL_ROOT / spec["file"]
    if sha256_file(path) != spec["sha256"]:
        raise RuntimeError(f"MODEL_SHA_MISMATCH: {route}")
    state = torch.load(path, map_location="cpu", weights_only=True)
    state = state.get("params_ema") or state.get("params") or state
    model = RRDBNet(spec["scale"])
    model.load_state_dict(state, strict=True)
    return model.eval()


@torch.inference_mode()
def run_tiled(model: RRDBNet, rgb: np.ndarray) -> tuple[np.ndarray, list[int], list[int]]:
    """Overlapping tiles blended with linear ramps across each 2*TILE_PAD overlap."""

    scale = model.scale
    h, w, _ = rgb.shape
    tensor = torch.from_numpy(rgb.astype(np.float32) / 255.0).permute(2, 0, 1).unsqueeze(0)
    out = torch.zeros((1, 3, h * scale, w * scale), dtype=torch.float32)
    weight = torch.zeros((1, 1, h * scale, w * scale), dtype=torch.float32)

    def ramp(n: int, open_start: bool, open_end: bool) -> torch.Tensor:
        idx = torch.arange(n, dtype=torch.float32) + 0.5
        r = torch.ones(n)
        width = 2 * TILE_PAD * scale
        if open_start:
            r = torch.minimum(r, idx / width)
        if open_end:
            r = torch.minimum(r, (n - idx) / width)
        return r.clamp_(min=1e-3)
    xs = list(range(0, w, TILE))
    ys = list(range(0, h, TILE))
    for y in ys:
        for x in xs:
            x0, y0 = max(x - TILE_PAD, 0), max(y - TILE_PAD, 0)
            x1, y1 = min(x + TILE + TILE_PAD, w), min(y + TILE + TILE_PAD, h)
            tile = tensor[:, :, y0:y1, x0:x1]
            ph, pw = (-tile.shape[2]) % 2, (-tile.shape[3]) % 2
            if ph or pw:
                tile = F.pad(tile, (0, pw, 0, ph), mode="reflect")
            result = model(tile)[:, :, : (y1 - y0) * scale, : (x1 - x0) * scale]
            wy = ramp((y1 - y0) * scale, y0 > 0, y1 < h)
            wx = ramp((x1 - x0) * scale, x0 > 0, x1 < w)
            wmap = (wy[:, None] * wx[None, :])[None, None]
            out[:, :, y0 * scale : y1 * scale, x0 * scale : x1 * scale] += result * wmap
            weight[:, :, y0 * scale : y1 * scale, x0 * scale : x1 * scale] += wmap
    array = (out / weight).squeeze(0).permute(1, 2, 0).clamp_(0, 1).numpy()
    return (array * 255.0).round().astype(np.uint8), [v * scale for v in xs[1:]], [v * scale for v in ys[1:]]


# ----------------------------------------------------------- text guard ---

def detect_text_mask(rgb: np.ndarray, session: ort.InferenceSession) -> tuple[np.ndarray, list[list[int]]]:
    """PP-OCRv4 DB detector on the source; returns a source-size boolean mask and boxes."""

    h, w, _ = rgb.shape
    limit = 1920
    ratio = min(1.0, limit / max(h, w))
    rh, rw = max(32, int(round(h * ratio / 32)) * 32), max(32, int(round(w * ratio / 32)) * 32)
    resized = cv2.resize(rgb, (rw, rh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    norm = (resized - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    prob = session.run(None, {session.get_inputs()[0].name: norm.transpose(2, 0, 1)[None]})[0][0, 0]
    binary = (prob > 0.3).astype(np.uint8)
    binary = cv2.dilate(binary, np.ones((3, 3), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
    mask = np.zeros((h, w), dtype=np.uint8)
    boxes: list[list[int]] = []
    for idx in range(1, count):
        x, y, bw, bh, area = stats[idx]
        if area < 12 or float(prob[labels == idx].mean()) < 0.5:
            continue
        # DB shrinks text regions; expand like the official unclip, then map to source.
        pad = int(max(3, 0.6 * min(bw, bh)))
        sx0, sy0 = int((x - pad) * w / rw), int((y - pad) * h / rh)
        sx1, sy1 = int((x + bw + pad) * w / rw), int((y + bh + pad) * h / rh)
        sx0, sy0, sx1, sy1 = max(sx0, 0), max(sy0, 0), min(sx1, w), min(sy1, h)
        mask[sy0:sy1, sx0:sx1] = 1
        boxes.append([sx0, sy0, sx1, sy1])
    return mask.astype(bool), boxes


def upscale_mask(mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return cv2.resize(mask.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST).astype(bool)


# ------------------------------------------------------------- pipeline ---

def lanczos(array: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return np.asarray(Image.fromarray(array).resize(size, Image.Resampling.LANCZOS))


def lanczos_float(array: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    channels = [
        np.asarray(Image.fromarray(array[:, :, c].astype(np.float32), mode="F").resize(size, Image.Resampling.LANCZOS))
        for c in range(3)
    ]
    return np.stack(channels, axis=2)


def back_project(candidate: np.ndarray, source: np.ndarray, iterations: int = 4) -> np.ndarray:
    """Push the candidate until its LANCZOS reduction matches the source (structure/colour lock)."""

    h, w, _ = source.shape
    big = (candidate.shape[1], candidate.shape[0])
    current = candidate.astype(np.float32)
    src = source.astype(np.float32)
    for _ in range(iterations):
        residual = src - lanczos_float(current, (w, h))
        current = np.clip(current + lanczos_float(residual, big), 0, 255)
    return current.round().astype(np.uint8)


def guard_text(candidate: np.ndarray, baseline: np.ndarray, mask_hr: np.ndarray, feather: int = 6) -> np.ndarray:
    """Feather outside the mask only, then re-impose the hard protected zone (SKILL 18.8)."""

    if not mask_hr.any():
        return candidate
    outside = cv2.distanceTransform((~mask_hr).astype(np.uint8), cv2.DIST_L2, 3)
    weight = np.clip(outside / float(feather), 0.0, 1.0)[..., None]
    blended = baseline.astype(np.float32) * (1 - weight) + candidate.astype(np.float32) * weight
    result = blended.round().astype(np.uint8)
    result[mask_hr] = baseline[mask_hr]
    return result


# -------------------------------------------------------------- metrics ---

def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2))
    return 99.0 if mse == 0 else round(10 * np.log10(255.0**2 / mse), 3)


def delta_e2000_mean(a: np.ndarray, b: np.ndarray) -> float:
    lab1 = cv2.cvtColor(a.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float64)
    lab2 = cv2.cvtColor(b.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float64)
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
    de = np.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dhp / sh) ** 2 + rt * (dcp / sc) * (dhp / sh))
    return round(float(de.mean()), 4)


def detail_energy(array: np.ndarray) -> dict[str, float]:
    gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gx, gy = cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    lap = cv2.Laplacian(gray, cv2.CV_32F)
    return {"gradient_mean": float(np.mean(np.hypot(gx, gy))), "laplacian_var": float(lap.var())}


def seam_ratio(array: np.ndarray, xs: list[int], ys: list[int]) -> float:
    """Mean jump across tile borders divided by the mean jump across ordinary neighbouring lines."""

    gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY).astype(np.float32)
    col = np.abs(np.diff(gray, axis=1)).mean(axis=0)
    row = np.abs(np.diff(gray, axis=0)).mean(axis=1)
    border = [col[x - 1] for x in xs if 0 < x < gray.shape[1]] + [row[y - 1] for y in ys if 0 < y < gray.shape[0]]
    if not border:
        return 1.0
    return round(float(np.mean(border)) / max(float((col.mean() + row.mean()) / 2), 1e-6), 4)


def seam_detail_jump(final: np.ndarray, baseline: np.ndarray, xs: list[float], ys: list[float]) -> float:
    """Largest change of local detail across a tile border, relative to the same change in LANCZOS.

    Catches a model that adds texture on one side of a border only (S07 in the first review),
    which the brightness-based seam_ratio cannot see.
    """

    def energy(a: np.ndarray) -> np.ndarray:
        g = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY).astype(np.float32)
        return cv2.GaussianBlur(np.abs(cv2.Laplacian(g, cv2.CV_32F)), (0, 0), 2)

    ef, eb = energy(final), energy(baseline)
    h, w = ef.shape
    # Border segments are one tile long, so a jump confined to one tile is not averaged away.
    seg = max(64, int(round(xs[0] if xs else ys[0] if ys else w)))
    worst = 1.0
    for axis, positions, length in ((0, ys, w), (1, xs, h)):
        for pos in (int(round(p)) for p in positions):
            if not 30 < pos < (h if axis == 0 else w) - 30:
                continue
            for s in range(0, length - seg + 1, seg):
                if axis == 0:
                    a, b = np.s_[pos - 30 : pos - 8, s : s + seg], np.s_[pos + 8 : pos + 30, s : s + seg]
                else:
                    a, b = np.s_[s : s + seg, pos - 30 : pos - 8], np.s_[s : s + seg, pos + 8 : pos + 30]
                if abs(float(ef[b].mean() - ef[a].mean())) <= 3:
                    continue
                rf = (ef[b].mean() + 0.5) / (ef[a].mean() + 0.5)
                rb = (eb[b].mean() + 0.5) / (eb[a].mean() + 0.5)
                worst = max(worst, float(max(rf / rb, rb / rf)))
    return round(worst, 3)


def png_size(array: np.ndarray, path: Path) -> int:
    Image.fromarray(array).save(path, format="PNG", compress_level=6)
    with Image.open(path) as check:
        check.load()
        if check.size != (array.shape[1], array.shape[0]):
            raise RuntimeError("OUTPUT_DIMENSIONS_MISMATCH")
    return path.stat().st_size


# --------------------------------------------------------- review assets ---

def pick_rois(source: np.ndarray, text_boxes: list[list[int]], size_hr: tuple[int, int]) -> list[dict[str, Any]]:
    h, w, _ = source.shape
    sx, sy = size_hr[0] / w, size_hr[1] / h
    crop = 480
    rois: list[dict[str, Any]] = []

    def add(kind: str, cx: float, cy: float) -> None:
        x0 = int(np.clip(cx * sx - crop / 2, 0, size_hr[0] - crop))
        y0 = int(np.clip(cy * sy - crop / 2, 0, size_hr[1] - crop))
        rois.append({"kind": kind, "box_hr": [x0, y0, x0 + crop, y0 + crop]})

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = cascade.detectMultiScale(cv2.cvtColor(source, cv2.COLOR_RGB2GRAY), 1.1, 6, minSize=(40, 40))
    if len(faces):
        x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        add("FACE", x + fw / 2, y + fh / 2)
    if text_boxes:
        x0, y0, x1, y1 = min(text_boxes, key=lambda b: (b[3] - b[1]))  # smallest text = hardest
        add("SMALL_TEXT", (x0 + x1) / 2, (y0 + y1) / 2)
    gray = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY).astype(np.float32)
    energy = cv2.boxFilter(np.abs(cv2.Laplacian(gray, cv2.CV_32F)), -1, (96, 96))
    yy, xx = np.unravel_index(int(np.argmax(energy)), energy.shape)
    add("TEXTURE", xx, yy)
    return rois


def review_panel(panels: list[tuple[str, np.ndarray]], path: Path, cell: int) -> None:
    pad, label_h = 8, 26
    canvas = Image.new("RGB", (len(panels) * (cell + pad) + pad, cell + label_h + pad), "white")
    draw = ImageDraw.Draw(canvas)
    for i, (label, array) in enumerate(panels):
        tile = Image.fromarray(array)
        tile.thumbnail((cell, cell), Image.Resampling.LANCZOS) if max(tile.size) > cell else None
        x = pad + i * (cell + pad)
        canvas.paste(tile, (x, label_h))
        draw.text((x, 6), label, fill="black")
    canvas.save(path, quality=92)


# ------------------------------------------------------------------ main ---

def summarize_routes(matrix: list[dict[str, Any]], routes: list[str]) -> dict[str, Any]:
    """Route matrix (SKILL 18.1); time and size budgets are mandatory technical gates."""

    summary: dict[str, Any] = {}
    for route in routes:
        rows = [m for m in matrix if m["route"] == route]
        failed = sorted(
            {
                gate
                for m in rows
                for gate in ("geometry_gate", "tile_seam_gate", "time_budget_gate", "size_budget_gate")
                if m[gate] != "PASS"
            }
        )
        tech = not failed
        safe = all(m["structure_safety_gate"] == "PASS" for m in rows)
        summary[route] = {
            "TECHNICAL_STATUS": "PASS" if tech else "FAIL",
            "STRUCTURE_SAFETY_STATUS": "PASS" if safe else "FAIL",
            "VISUAL_GAIN_STATUS": "PENDING_HUMAN_REVIEW" if tech and safe else "NOT_RUN",
            "ROUTE_DECISION": "PENDING_HUMAN_REVIEW" if tech and safe else ("REJECTED_TECHNICAL" if not tech else "REJECTED_UNSAFE"),
            "REJECTION_REASON": "NOT_APPLICABLE" if tech and safe else ",".join(failed) or "STRUCTURE_SAFETY_GATE",
            "time_budget_pass": f"{sum(m['time_budget_gate'] == 'PASS' for m in rows)}/{len(rows)}",
            "size_budget_pass": f"{sum(m['size_budget_gate'] == 'PASS' for m in rows)}/{len(rows)}",
            "structure_safety_pass": f"{sum(m['structure_safety_gate'] == 'PASS' for m in rows)}/{len(rows)}",
            "median_runtime_seconds": float(np.median([m["runtime_seconds"] for m in rows])) if rows else None,
            "max_size_ratio_vs_lanczos": max((m["size_ratio_vs_lanczos"] for m in rows), default=None),
        }
    return summary


def resummarize() -> int:
    """Recompute the route matrix from the recorded execution matrix without re-running models."""

    path = safe_output_path("summary.json")
    summary = json.loads(path.read_text(encoding="utf-8"))
    for m in summary["execution_matrix"]:
        m["size_budget_gate"] = "PASS" if m["size_ratio_vs_lanczos"] <= GATE_SIZE_RATIO else "FAIL"
    summary["gates"]["size_ratio_vs_lanczos_max"] = GATE_SIZE_RATIO
    routes = list(dict.fromkeys(m["route"] for m in summary["execution_matrix"]))
    summary["route_status_matrix"] = summarize_routes(summary["execution_matrix"], routes)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary["route_status_matrix"], ensure_ascii=False, indent=1))
    return 0


def target_size(w: int, h: int) -> tuple[int, int]:
    scale = TARGET_LONG_EDGE / max(w, h)
    return max(1, int(np.floor(w * scale + 0.5))), max(1, int(np.floor(h * scale + 0.5)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--routes", default=",".join(MODELS))
    parser.add_argument("--resummarize", action="store_true")
    args = parser.parse_args()
    if args.resummarize:
        return resummarize()

    block_network()
    torch.set_num_threads(max(1, torch.get_num_threads()))
    started = datetime.now(timezone.utc).isoformat()

    samples = sorted(p for p in SAMPLE_ROOT.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
    if args.limit:
        samples = samples[: args.limit]
    before = {p.name: sha256_file(p) for p in samples}
    routes = [r for r in args.routes.split(",") if r]

    detector_path = MODEL_ROOT / TEXT_DETECTOR["file"]
    if sha256_file(detector_path) != TEXT_DETECTOR["sha256"]:
        raise RuntimeError("TEXT_DETECTOR_SHA_MISMATCH")
    detector = ort.InferenceSession(str(detector_path), providers=["CPUExecutionProvider"])
    models = {route: load_model(route) for route in routes}

    matrix: list[dict[str, Any]] = []
    for index, sample in enumerate(samples, 1):
        sid = f"S{index:02d}"
        with Image.open(sample) as opened:
            has_alpha = "A" in opened.getbands() or "transparency" in opened.info
            source = np.asarray(opened.convert("RGB"))
        h, w, _ = source.shape
        size_hr = target_size(w, h)

        t0 = time.perf_counter()
        baseline = lanczos(source, size_hr)
        baseline_seconds = time.perf_counter() - t0
        baseline_path = safe_output_path(f"outputs/{sid}/00_lanczos_baseline.png")
        baseline_bytes = png_size(baseline, baseline_path)

        text_mask, text_boxes = detect_text_mask(source, detector)
        for box in MANUAL_PROTECT_BOXES.get(sample.name, []):
            text_mask[int(box[1] * h) : int(box[3] * h), int(box[0] * w) : int(box[2] * w)] = True
        mask_hr = upscale_mask(text_mask, size_hr)
        mask_preview = source.copy()
        mask_preview[text_mask] = (mask_preview[text_mask] * 0.4 + np.array([255, 0, 0]) * 0.6).astype(np.uint8)
        Image.fromarray(mask_preview).save(safe_output_path(f"review/{sid}/protect_mask.jpg"), quality=88)

        base_down = lanczos(baseline, (w, h))
        base_detail = detail_energy(baseline)
        rois = pick_rois(source, text_boxes, size_hr)
        source_nearest = np.asarray(Image.fromarray(source).resize(size_hr, Image.Resampling.NEAREST))
        roi_panels: dict[str, list[tuple[str, np.ndarray]]] = {}
        for r in rois:
            x0, y0, x1, y1 = r["box_hr"]
            roi_panels[r["kind"]] = [("SOURCE (nearest)", source_nearest[y0:y1, x0:x1]), ("LANCZOS", baseline[y0:y1, x0:x1])]
        full_panels: list[tuple[str, np.ndarray]] = [("SOURCE", source), ("LANCZOS", baseline)]

        for route in routes:
            t1 = time.perf_counter()
            raw, xs, ys = run_tiled(models[route], source)
            model_seconds = time.perf_counter() - t1
            resized = lanczos(raw, size_hr)
            locked = back_project(resized, source)
            final = guard_text(locked, baseline, mask_hr)
            seconds = time.perf_counter() - t1

            out_path = safe_output_path(f"outputs/{sid}/{route}.png")
            out_bytes = png_size(final, out_path)
            down = lanczos(final, (w, h))
            raw_down = lanczos(resized, (w, h))
            protect_changed = int(np.count_nonzero(np.any(final[mask_hr] != baseline[mask_hr], axis=-1))) if mask_hr.any() else 0
            detail = detail_energy(final)
            sx = raw.shape[1] / w
            seam = seam_ratio(raw, [int(x) for x in xs], [int(y) for y in ys])
            fx, fy = size_hr[0] / raw.shape[1], size_hr[1] / raw.shape[0]
            detail_jump = seam_detail_jump(final, baseline, [x * fx for x in xs], [y * fy for y in ys])
            seam_ok = seam < 1.5 and detail_jump <= GATE_SEAM_DETAIL_JUMP

            roundtrip = psnr(down, source)
            de = delta_e2000_mean(down, source)
            structure_ok = roundtrip >= GATE_ROUNDTRIP_PSNR_DB and de <= GATE_DELTA_E2000_MEAN and protect_changed == 0
            technical_ok = final.shape[:2] == (size_hr[1], size_hr[0]) and seam_ok and not has_alpha
            matrix.append(
                {
                    "sample_id": sid,
                    "route": route,
                    "source_path": str(sample),
                    "baseline_path": str(baseline_path.relative_to(REPO_ROOT)),
                    "candidate_path": str(out_path.relative_to(REPO_ROOT)),
                    "runtime_seconds": round(seconds, 2),
                    "model_seconds": round(model_seconds, 2),
                    "lanczos_seconds": round(baseline_seconds, 3),
                    "output_size_bytes": out_bytes,
                    "lanczos_size_bytes": baseline_bytes,
                    "size_ratio_vs_lanczos": round(out_bytes / baseline_bytes, 3),
                    "dimensions": f"{size_hr[0]}x{size_hr[1]}",
                    "source_dimensions": f"{w}x{h}",
                    "model_native_scale": sx,
                    "format": "PNG",
                    "alpha_status": "NOT_APPLICABLE_NO_ALPHA_SAMPLE" if not has_alpha else "NOT_SUPPORTED_IN_POC",
                    "roundtrip_psnr_db": roundtrip,
                    "roundtrip_psnr_before_lock_db": psnr(raw_down, source),
                    "lanczos_roundtrip_psnr_db": psnr(base_down, source),
                    "delta_e2000_mean": de,
                    "protected_pixels_hr": int(mask_hr.sum()),
                    "protected_pixels_changed": protect_changed,
                    "text_boxes": len(text_boxes),
                    "manual_protect_boxes": len(MANUAL_PROTECT_BOXES.get(sample.name, [])),
                    "gradient_ratio_vs_lanczos": round(detail["gradient_mean"] / max(base_detail["gradient_mean"], 1e-6), 3),
                    "laplacian_var_ratio_vs_lanczos": round(detail["laplacian_var"] / max(base_detail["laplacian_var"], 1e-6), 3),
                    "tile_seam_ratio": seam,
                    "tile_seam_detail_jump": detail_jump,
                    "geometry_gate": "PASS" if final.shape[:2] == (size_hr[1], size_hr[0]) else "FAIL",
                    "tile_seam_gate": "PASS" if seam_ok else "REVIEW",
                    "structure_safety_gate": "PASS" if structure_ok else "FAIL",
                    "time_budget_gate": "PASS" if seconds <= GATE_SECONDS_PER_IMAGE else "FAIL",
                    "size_budget_gate": "PASS" if out_bytes <= GATE_SIZE_RATIO * baseline_bytes else "FAIL",
                    "technical_status": "PASS" if technical_ok else "FAIL",
                    "route_decision": "PENDING_HUMAN_REVIEW" if technical_ok and structure_ok else ("REJECTED_TECHNICAL" if not technical_ok else "REJECTED_UNSAFE"),
                    "peak_working_set_mb": peak_working_set_mb(),
                }
            )
            print(json.dumps(matrix[-1], ensure_ascii=False), flush=True)
            full_panels.append((route, final))
            for r in rois:
                x0, y0, x1, y1 = r["box_hr"]
                roi_panels[r["kind"]].append((route, final[y0:y1, x0:x1]))

        review_panel(full_panels, safe_output_path(f"review/{sid}/full.jpg"), 900)
        for kind, panels in roi_panels.items():
            review_panel(panels, safe_output_path(f"review/{sid}/roi_{kind.lower()}_100pct.png"), 480)

    after = {p.name: sha256_file(p) for p in samples}
    route_summary = summarize_routes(matrix, routes)
    summary = {
        "task_id": TASK_ID,
        "started_at_utc": started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "network": "BLOCKED_IN_PROCESS_SOCKET_GUARD",
        "environment": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "onnxruntime": ort.__version__,
            "opencv": cv2.__version__,
            "cpu": platform.processor(),
            "torch_threads": torch.get_num_threads(),
            "cuda": torch.cuda.is_available(),
        },
        "gates": {
            "roundtrip_psnr_db_min": GATE_ROUNDTRIP_PSNR_DB,
            "delta_e2000_mean_max": GATE_DELTA_E2000_MEAN,
            "seconds_per_image_max": GATE_SECONDS_PER_IMAGE,
            "size_ratio_vs_lanczos_max": GATE_SIZE_RATIO,
            "tile_seam_detail_jump_max": GATE_SEAM_DETAIL_JUMP,
        },
        "tiling": {"tile": TILE, "pad": TILE_PAD, "blend": "linear_feather"},
        "samples_sha256_before": before,
        "samples_sha256_after": after,
        "samples_unchanged": before == after,
        "route_status_matrix": route_summary,
        "execution_matrix": matrix,
    }
    safe_output_path("summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"route_status_matrix": route_summary, "samples_unchanged": before == after}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
