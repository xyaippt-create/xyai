"""Print upscaling: reuse the frozen 4K detail reconstruction before enlarging to the print size.

The 4K route's super-resolution and source-fidelity fusion are called unchanged; only the
fusion size and the final LANCZOS step to the print pixels are decided here.
"""

import math

import cv2
import numpy as np
from PIL import Image

from engine.image_processing_routing.four_k_v1 import (
    FOUR_K_V1_SR_MODEL,
    FOUR_K_V1_SR_SCALE,
    FOUR_K_V1_TEXT_DETECT_MAX_SIDE,
    FOUR_K_V1_TEXT_DETECT_MIN_SIDE,
    FOUR_K_V1_TEXT_PROB_THRESHOLD,
    _detect_text_gate,
    _fuse_detail,
    _run_super_resolution,
    _structure_maps,
    _text_detector,
)

# Below this enlargement plain LANCZOS is already close to the source detail.
SR_MIN_SCALE = 1.25
# SR runs at about 39 s per megapixel on integrated graphics; larger sources go straight to LANCZOS.
SR_MAX_SOURCE_PIXELS = 4_000_000
# The fusion keeps a dozen float32 planes at fusion size.
FUSE_MAX_PIXELS = 40_000_000
# Remaining LANCZOS enlargement after reconstruction that gets the light print sharpening.
SHARPEN_MIN_RESIDUAL = 1.05
SHARPEN_AMOUNT = 0.35
# Text edge tightening (print only): window radius per unit of total enlargement, the
# luminance step an edge needs before it is touched, and how far the transition is steepened.
TEXT_RADIUS_PER_SCALE = 0.6
TEXT_MIN_STEP = (0.18, 0.30)
TEXT_STEEPEN = 0.7
# The 4K fusion leaves large display text out of its gate (thick kernels); a print headline is
# exactly what viewers read up close, so the print gate accepts kernels up to this share of
# the short side.
TEXT_MAX_KERNEL_SHARE = 0.08


def plan_print_upscale(source_width, source_height, target_width, target_height, *, color=True):
    """Decide whether to reconstruct detail and at which size to fuse; pure arithmetic."""

    scale = max(target_width / source_width, target_height / source_height)
    pixels = source_width * source_height
    if not color or scale < SR_MIN_SCALE or pixels > SR_MAX_SOURCE_PIXELS:
        reason = "SMALL_SCALE" if scale < SR_MIN_SCALE else "SOURCE_TOO_LARGE" if pixels > SR_MAX_SOURCE_PIXELS else "GRAYSCALE"
        return {"method": "LANCZOS", "reason": reason, "scale": scale, "fuse_scale": 1.0, "residual_scale": scale}
    fuse_scale = min(scale, math.sqrt(FUSE_MAX_PIXELS / pixels))
    return {
        "method": "SR_FUSION",
        "reason": "",
        "scale": scale,
        "fuse_scale": fuse_scale,
        "residual_scale": scale / fuse_scale,
        # Detail per print inch after reconstruction: the model adds at most its native factor.
        "detail_scale": min(scale, FOUR_K_V1_SR_SCALE),
    }


def _sharpen_luma(rgb, residual):
    """Light unsharp mask on luminance, clamped to the local 3x3 range so no halo is added."""

    # Float round trip: an 8-bit YCrCb round trip shifts the chroma of every pixel.
    ycc = cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2YCrCb)
    luma = ycc[..., 0].copy()
    blurred = cv2.GaussianBlur(luma, (0, 0), 0.8 * residual)
    k3 = np.ones((3, 3), np.uint8)
    ycc[..., 0] = np.clip(luma + SHARPEN_AMOUNT * (luma - blurred), cv2.erode(luma, k3), cv2.dilate(luma, k3))
    return (np.clip(cv2.cvtColor(ycc, cv2.COLOR_YCrCb2RGB), 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def _smoothstep(x, lo, hi):
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _print_text_gate(rgb):
    """Text mask at source size from the 4K route's detector, headlines included; None if absent."""

    session, _ = _text_detector()
    if session is None:
        return None
    width, height = rgb.size
    factor = min(1.0, FOUR_K_V1_TEXT_DETECT_MAX_SIDE / max(width, height))
    if max(width, height) * factor < FOUR_K_V1_TEXT_DETECT_MIN_SIDE:
        factor = FOUR_K_V1_TEXT_DETECT_MIN_SIDE / max(width, height)
    det_w = max(32, int(round(width * factor / 32)) * 32)
    det_h = max(32, int(round(height * factor / 32)) * 32)
    pixels = np.asarray(rgb.resize((det_w, det_h), Image.Resampling.BILINEAR), dtype=np.float32) / 255.0
    pixels = (pixels - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    try:
        output = session.run(None, {session.get_inputs()[0].name: pixels.transpose(2, 0, 1)[None]})[0]
    except Exception:
        return None
    probability = cv2.resize(np.asarray(output, np.float32).reshape(det_h, det_w), (width, height))
    kernels = (probability > FOUR_K_V1_TEXT_PROB_THRESHOLD).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(kernels, 8)
    max_thick = max(24, TEXT_MAX_KERNEL_SHARE * min(width, height))
    gate = np.zeros((height, width), np.uint8)
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        thickness = max(1, min(w, h))
        if area < 6 or thickness > max_thick:
            continue
        grow = max(1, int(round(0.5 * thickness)))  # detector kernels are shrunk text boxes
        x0, y0 = max(0, x - grow), max(0, y - grow)
        x1, y1 = min(width, x + w + grow), min(height, y + h + grow)
        region = (labels[y0:y1, x0:x1] == index).astype(np.uint8)
        region = cv2.dilate(region, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
        gate[y0:y1, x0:x1] = np.maximum(gate[y0:y1, x0:x1], region)
    if not gate.any():
        return None
    return np.clip(cv2.GaussianBlur(gate.astype(np.float32), (0, 0), 1.0), 0.0, 1.0)


def _tighten_text_edges(rgb, gate, scale):
    """Narrow the transition band of strong text edges on luminance only.

    Each pixel is placed on its local dark-to-light step (t = 0..1) and moved along a
    smoothstep that keeps both ends and the midpoint: the stroke outline (the midpoint
    contour) stays where it is, nothing leaves the local range so no halo appears, and
    flat areas (low gradient), weak steps and ramps wider than the window are left untouched. Pixels outside the text
    gate are returned unchanged. ``gate`` is the detector mask at any size.
    """

    height, width = rgb.shape[:2]
    radius = max(2, int(math.ceil(TEXT_RADIUS_PER_SCALE * scale)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    wide = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (4 * radius + 1, 4 * radius + 1))
    small = (gate > 0.01).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(small, 8)
    fx, fy = width / gate.shape[1], height / gate.shape[0]
    margin = 2 * radius + 6
    out = rgb.copy()
    touched = 0
    for index in range(1, count):
        gx, gy, gw, gh, _ = (int(v) for v in stats[index])
        x0, y0 = int(gx * fx), int(gy * fy)
        x1, y1 = min(width, int(math.ceil((gx + gw) * fx))), min(height, int(math.ceil((gy + gh) * fy)))
        cx0, cy0, cx1, cy1 = max(0, x0 - margin), max(0, y0 - margin), min(width, x1 + margin), min(height, y1 + margin)
        crop = rgb[cy0:cy1, cx0:cx1]
        ycc = cv2.cvtColor(crop.astype(np.float32) / 255.0, cv2.COLOR_RGB2YCrCb)
        luma = ycc[..., 0]
        lo, hi = cv2.erode(luma, kernel), cv2.dilate(luma, kernel)
        step = hi - lo
        # A ramp wider than the window would be cut into terraces; only steps that already
        # reach their plateaus inside the window (same range at twice the radius) qualify.
        contained = step / np.maximum(cv2.dilate(luma, wide) - cv2.erode(luma, wide), 1e-4)
        t = (luma - lo) / np.maximum(step, 1e-4)
        steep = lo + step * (t + TEXT_STEEPEN * (t * t * (3.0 - 2.0 * t) - t))
        gx_, gy_ = cv2.Sobel(luma, cv2.CV_32F, 1, 0, ksize=3) / 8.0, cv2.Sobel(luma, cv2.CV_32F, 0, 1, ksize=3) / 8.0
        # Inside a transition the gradient is about step / width; on a plateau it is near zero.
        slope = cv2.GaussianBlur(np.hypot(gx_, gy_), (0, 0), 1.0) * (2 * radius) / np.maximum(step, 1e-4)
        local_gate = cv2.resize(gate[gy:gy + gh, gx:gx + gw].astype(np.float32), (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR)
        weight = np.zeros_like(luma)
        weight[y0 - cy0:y1 - cy0, x0 - cx0:x1 - cx0] = np.clip(local_gate, 0.0, 1.0)
        weight *= _smoothstep(step, *TEXT_MIN_STEP) * _smoothstep(slope, 0.25, 0.6) * _smoothstep(contained, 0.85, 0.97)
        if not weight.any():
            continue
        ycc[..., 0] = luma + weight * (steep - luma)
        result = (np.clip(cv2.cvtColor(ycc, cv2.COLOR_YCrCb2RGB), 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        inner = (slice(y0 - cy0, y1 - cy0), slice(x0 - cx0, x1 - cx0))
        changed = weight[inner] > 0
        # Write only weighted pixels: untouched pixels keep their exact original bytes.
        out[y0:y1, x0:x1][changed] = result[inner][changed]
        touched += int(changed.sum())
    return out, touched


def upscale_rgb_for_print(rgb, target_size, work_dir, plan):
    """RGB PIL image -> RGB PIL image at target_size following plan_print_upscale."""

    if plan["method"] != "SR_FUSION":
        return rgb.resize(target_size, Image.Resampling.LANCZOS), {"method": "LANCZOS", "reason": plan["reason"]}
    fuse_size = target_size
    if plan["residual_scale"] > 1.0:
        fuse_size = (max(1, round(rgb.width * plan["fuse_scale"])), max(1, round(rgb.height * plan["fuse_scale"])))
    sr_native = _run_super_resolution(rgb, work_dir)
    maps = _structure_maps(rgb, fuse_size)
    text_gate, text_info = _detect_text_gate(rgb, fuse_size)
    fused = _fuse_detail(sr_native, rgb, fuse_size, maps, text_gate)
    del sr_native, maps
    if fuse_size != tuple(target_size):
        fused = np.asarray(Image.fromarray(fused).resize(target_size, Image.Resampling.LANCZOS))
        if plan["residual_scale"] >= SHARPEN_MIN_RESIDUAL:
            fused = _sharpen_luma(fused, plan["residual_scale"])
    del text_gate
    tightened = 0
    print_gate = _print_text_gate(rgb)
    if print_gate is not None:
        fused, tightened = _tighten_text_edges(fused, print_gate, plan["scale"])
    info = {
        "method": "SR_FUSION",
        "model": FOUR_K_V1_SR_MODEL,
        "fuse_width": fuse_size[0],
        "fuse_height": fuse_size[1],
        "residual_scale": round(plan["residual_scale"], 3),
        "text_enhancement": text_info.get("status", ""),
        "text_edge_pixels": tightened,
    }
    return Image.fromarray(fused, "RGB"), info
