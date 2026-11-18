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
    _detect_text_gate,
    _fuse_detail,
    _run_super_resolution,
    _structure_maps,
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
    del sr_native, maps, text_gate
    if fuse_size != tuple(target_size):
        fused = np.asarray(Image.fromarray(fused).resize(target_size, Image.Resampling.LANCZOS))
        if plan["residual_scale"] >= SHARPEN_MIN_RESIDUAL:
            fused = _sharpen_luma(fused, plan["residual_scale"])
    info = {
        "method": "SR_FUSION",
        "model": FOUR_K_V1_SR_MODEL,
        "fuse_width": fuse_size[0],
        "fuse_height": fuse_size[1],
        "residual_scale": round(plan["residual_scale"], 3),
        "text_enhancement": text_info.get("status", ""),
    }
    return Image.fromarray(fused, "RGB"), info
