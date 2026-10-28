"""Isolated Hybrid Poster 4K recovery and size-budget PoC.

This experiment is bound to one real poster sample. It is deliberately not
connected to the formal 4K route, API, UI, Task/Result, or product delivery
chain. One allow-listed, non-GAN ESPCN model proposes luma detail only inside
sample-bound photographic regions. Bound hard-masked regions remain anchored
to the pixel-exact Pillow LANCZOS baseline; complete text/logo/icon coverage is
not proven.

Sharpness and high-frequency metrics are diagnostics only. They never prove
real information gain.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image, ImageDraw, ImageFont, ImageOps


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.algorithms.low_quality_fidelity import phase4_restoration_masks  # noqa: E402


TASK_ID = "E4K-04_REOPEN_GATE_01"
CLOSURE_TASK_ID = "E4K-04_REOPEN_GATE_02"
ARTIFACT_VERSION = "HDDE_E4K04_HYBRID_POSTER_POC_V1"
SOURCE_PATH = Path(
    r"C:\Users\xyppt\Desktop\临时文件\ChatGPT Image 2026年7月9日 15_06_26 (2).png"
)
BASELINE_PATH = Path(
    r"D:\影界文件\输出\4K高清增强\ChatGPT Image 2026年7月9日 15_06_26 (2)_影界4K适配_20260822_145149_13bf64f9.png"
)
MODEL_PATH = REPO_ROOT / "models" / "e4k_poc" / "super-resolution-10.onnx"
OUTPUT_ROOT = REPO_ROOT / "artifacts" / "e4k_04_reopen_gate_01"

EXPECTED_SOURCE_SHA256 = "a4ab21b491397c1f6b279dc3c7de1989a6cfce5f441f69eb625ec166eb1399a7"
EXPECTED_BASELINE_SHA256 = "fe4a1a15cae2537b2ec763195a8d646c8ef3bcf369eb3ebd89a2753216e1ca3b"
EXPECTED_MODEL_SHA256 = "85f36ff88cc504a24af5e0602148bc56a8aa09a58eca8c0da2756f3e8186035e"
MODEL_ID = "ONNX_MODEL_ZOO_ESPCN_X3_OPSET10"
MODEL_VERSION = "super-resolution-10@395472c4b6b92f788357237983d83fd913cfe7e3"
MODEL_LICENSE = "Apache-2.0"
MODEL_PAGE_URL = "https://huggingface.co/onnxmodelzoo/super-resolution-10"
MODEL_DOWNLOAD_URL = (
    "https://huggingface.co/onnxmodelzoo/super-resolution-10/resolve/"
    "395472c4b6b92f788357237983d83fd913cfe7e3/super-resolution-10.onnx"
)
MODEL_LICENSE_URL = "https://github.com/onnx/models/blob/main/LICENSE"

TARGET_LONG_EDGE = 3840
MAX_OUTPUT_BYTES = 8_104_186
MODEL_INPUT_EDGE = 224
MODEL_SCALE = 3
TILE_STRIDE = 192
MODEL_BLEND = 0.58
MODEL_RESIDUAL_LIMIT = 8.0
APPLIED_LUMA_LIMIT = 4.5
LOCAL_EXTREMA_MARGIN = 1.0

USER_VISIBLE_CLARITY_VERDICT = "BELOW_EXPECTATION"
CODEX_VISUAL_SCREEN = "COMPLETED"
INDEPENDENT_HUMAN_SAFETY_REVIEW = "PENDING"
ALL_TEXT_LOGO_ICON_COVERAGE = "NOT_PROVEN"
CONTENT_REGION_METHOD = "MANUAL_BOUND_SAMPLE_ANNOTATION"
AUTOMATIC_CONTENT_RECOGNITION = "NOT_PROVEN"
GENERALIZATION = "NOT_CLAIMED"
CURRENT_MODEL_DECISION = "NOT_PROVEN_ON_BOUND_SAMPLE"


class PocError(RuntimeError):
    """Fail-closed PoC error."""


@dataclass(frozen=True)
class Region:
    region_id: str
    box: tuple[int, int, int, int]


# Source-coordinate annotations are intentionally bound to this one sample.
# They are evidence annotations for the PoC, not a reusable routing system.
PHOTO_REGIONS = (
    Region("comparison_photos", (68, 356, 665, 578)),
    Region("hero_street_photo", (828, 35, 1668, 548)),
    Region("construction_photos", (65, 625, 885, 815)),
    Region("physical_scale_model", (55, 760, 1110, 940)),
)

PROTECTED_REGIONS = (
    Region("top_title", (55, 48, 835, 174)),
    Region("subtitle", (55, 170, 840, 228)),
    Region("top_icon_buttons", (55, 225, 600, 302)),
    Region("comparison_heading", (50, 305, 310, 372)),
    Region("comparison_labels", (62, 512, 670, 582)),
    Region("vertical_city_sign", (1490, 125, 1615, 365)),
    Region("hero_caption", (1270, 420, 1668, 555)),
    Region("process_heading", (55, 578, 315, 645)),
    Region("process_photo_labels", (58, 716, 890, 820)),
    Region("data_heading", (905, 548, 1195, 620)),
    Region("data_cards_and_small_text", (900, 600, 1672, 865)),
    Region("bottom_caption", (735, 825, 1120, 941)),
)

QUALITY_ROIS = (
    Region("ROI01_top_title", (55, 48, 835, 174)),
    Region("ROI02_subtitle_small_text", (55, 165, 845, 235)),
    Region("ROI03_city_memory_sign", (1475, 115, 1625, 375)),
    Region("ROI04_building_windows", (930, 62, 1490, 350)),
    Region("ROI05_trees_and_people", (835, 160, 1665, 545)),
    Region("ROI06_bottom_data_cards", (900, 550, 1668, 870)),
    Region("ROI07_glass_high_contrast_edges", (45, 285, 905, 640)),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pixel_sha256(array: np.ndarray) -> str:
    values = np.ascontiguousarray(array)
    digest = hashlib.sha256()
    digest.update(values.tobytes())
    digest.update(str(values.dtype).encode("ascii"))
    digest.update(repr(values.shape).encode("ascii"))
    return digest.hexdigest()


def closure_evidence() -> dict[str, Any]:
    """Return the truth-scoped Gate 02 closure record without running inference."""
    return {
        "closure_task_id": CLOSURE_TASK_ID,
        "status": "PASS",
        "user_visible_clarity_verdict": USER_VISIBLE_CLARITY_VERDICT,
        "codex_visual_screen": CODEX_VISUAL_SCREEN,
        "independent_human_safety_review": INDEPENDENT_HUMAN_SAFETY_REVIEW,
        "masked_region_identity": "PASS",
        "all_text_logo_icon_coverage": ALL_TEXT_LOGO_ICON_COVERAGE,
        "text_protection": "PENDING_COVERAGE_REVIEW",
        "content_region_method": CONTENT_REGION_METHOD,
        "automatic_content_recognition": AUTOMATIC_CONTENT_RECOGNITION,
        "generalization": GENERALIZATION,
        "model_id": MODEL_ID,
        "model_scale": MODEL_SCALE,
        "current_model_decision": CURRENT_MODEL_DECISION,
        "visible_clarity_gain": USER_VISIBLE_CLARITY_VERDICT,
        "real_4k_quality_gain": "NOT_PROVEN",
        "continue_strength_tuning": "NO",
        "ready_for_formal_candidate": "NO",
        "checked_protected_files_changed": "NO",
        "full_frozen_tree_pre_post_proof": "NOT_AVAILABLE",
    }


def target_size(source_size: tuple[int, int], long_edge: int = TARGET_LONG_EDGE) -> tuple[int, int]:
    width, height = source_size
    if min(width, height) <= 0:
        raise PocError("INVALID_SOURCE_SIZE")
    if width >= height:
        return long_edge, max(1, int(round(height * long_edge / width)))
    return max(1, int(round(width * long_edge / height))), long_edge


def load_rgb(path: Path) -> tuple[Image.Image, dict[str, Any]]:
    if not path.is_file():
        raise PocError(f"INPUT_MISSING:{path}")
    with Image.open(path) as opened:
        raw_mode = opened.mode
        alpha_present = "A" in opened.getbands() or "transparency" in opened.info
        icc_present = bool(opened.info.get("icc_profile"))
        image = ImageOps.exif_transpose(opened).convert("RGB")
    return image, {
        "path": str(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "raw_mode": raw_mode,
        "alpha_present": alpha_present,
        "icc_present": icc_present,
        "size": list(image.size),
    }


def verify_model(model_path: Path) -> tuple[ort.InferenceSession, dict[str, Any]]:
    if not model_path.is_file():
        raise PocError(f"MODEL_MISSING:{model_path}")
    actual_sha = sha256_file(model_path)
    if actual_sha != EXPECTED_MODEL_SHA256:
        raise PocError(f"MODEL_SHA256_MISMATCH:{actual_sha}")
    options = ort.SessionOptions()
    options.log_severity_level = 3
    session = ort.InferenceSession(
        str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
    )
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or len(outputs) != 1:
        raise PocError("MODEL_IO_COUNT_NOT_ELIGIBLE")
    if list(inputs[0].shape)[1:] != [1, MODEL_INPUT_EDGE, MODEL_INPUT_EDGE]:
        raise PocError(f"MODEL_INPUT_CONTRACT_MISMATCH:{inputs[0].shape}")
    if list(outputs[0].shape)[1:] != [1, MODEL_INPUT_EDGE * 3, MODEL_INPUT_EDGE * 3]:
        raise PocError(f"MODEL_OUTPUT_CONTRACT_MISMATCH:{outputs[0].shape}")
    probe = np.linspace(0.0, 1.0, MODEL_INPUT_EDGE * MODEL_INPUT_EDGE, dtype=np.float32)
    probe = probe.reshape(1, 1, MODEL_INPUT_EDGE, MODEL_INPUT_EDGE)
    started = time.perf_counter()
    result = session.run([outputs[0].name], {inputs[0].name: probe})[0]
    elapsed = time.perf_counter() - started
    if result.shape != (1, 1, 672, 672) or not np.isfinite(result).all():
        raise PocError("MODEL_RUNTIME_PROBE_FAILED")
    return session, {
        "status": "PASS",
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "model_path": str(model_path),
        "model_bytes": model_path.stat().st_size,
        "model_sha256": actual_sha,
        "expected_sha256": EXPECTED_MODEL_SHA256,
        "license": MODEL_LICENSE,
        "model_page_url": MODEL_PAGE_URL,
        "download_url": MODEL_DOWNLOAD_URL,
        "license_url": MODEL_LICENSE_URL,
        "architecture": "ESPCN_X3_LUMA_SUBPIXEL_CNN",
        "gan": False,
        "diffusion": False,
        "face_specific_redraw_model": False,
        "text_specific_redraw_model": False,
        "text_inference_scope": (
            "BLOCKED_ONLY_WITHIN_BOUND_HARD_MASK; COMPLETE_TEXT_LOGO_ICON_COVERAGE_NOT_PROVEN"
        ),
        "topaz_weight": False,
        "local_inference_only": True,
        "runtime_backend": "ONNXRUNTIME_CPUExecutionProvider",
        "runtime_version": ort.__version__,
        "providers": session.get_providers(),
        "input": {"name": inputs[0].name, "shape": list(inputs[0].shape), "type": inputs[0].type},
        "output": {"name": outputs[0].name, "shape": list(outputs[0].shape), "type": outputs[0].type},
        "runtime_probe": {
            "finite": True,
            "min": float(result.min()),
            "max": float(result.max()),
            "elapsed_seconds": round(elapsed, 6),
            "output_shape": list(result.shape),
        },
        "model_card_contract_note": (
            "The model card says dynamic image sizes, but the downloaded graph is fixed at "
            "224x224. This PoC honors the graph contract with overlapped tiling."
        ),
        "qualification_scope": "LOCAL_PRODUCT_RESEARCH_POC_ONLY",
    }


def tile_positions(length: int, tile: int = MODEL_INPUT_EDGE, stride: int = TILE_STRIDE) -> list[int]:
    if length < tile:
        raise PocError(f"SOURCE_AXIS_SMALLER_THAN_MODEL_TILE:{length}")
    positions = list(range(0, length - tile + 1, stride))
    final = length - tile
    if not positions or positions[-1] != final:
        positions.append(final)
    return positions


def _axis_feather(tile_out: int, previous_overlap: int, next_overlap: int) -> np.ndarray:
    weight = np.ones(tile_out, dtype=np.float32)
    if previous_overlap > 0:
        ramp = np.linspace(0.0, 1.0, previous_overlap, endpoint=False, dtype=np.float32)
        weight[:previous_overlap] = np.minimum(weight[:previous_overlap], ramp)
    if next_overlap > 0:
        ramp = np.linspace(1.0, 0.0, next_overlap, endpoint=False, dtype=np.float32)
        weight[-next_overlap:] = np.minimum(weight[-next_overlap:], ramp)
    return weight


def infer_tiled_luma(
    session: ort.InferenceSession, source_y: np.ndarray
) -> tuple[np.ndarray, dict[str, Any]]:
    values = np.asarray(source_y, dtype=np.uint8)
    height, width = values.shape
    xs = tile_positions(width)
    ys = tile_positions(height)
    scale = MODEL_SCALE
    tile_out = MODEL_INPUT_EDGE * scale
    accumulator = np.zeros((height * scale, width * scale), dtype=np.float32)
    weights = np.zeros_like(accumulator)
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name
    tile_times: list[float] = []
    seams_x: list[int] = []
    seams_y: list[int] = []
    for yi, y in enumerate(ys):
        prev_y_overlap = 0 if yi == 0 else (ys[yi - 1] + MODEL_INPUT_EDGE - y) * scale
        next_y_overlap = 0 if yi + 1 == len(ys) else (y + MODEL_INPUT_EDGE - ys[yi + 1]) * scale
        wy = _axis_feather(tile_out, prev_y_overlap, next_y_overlap)
        if yi:
            seams_y.append(y * scale)
        for xi, x in enumerate(xs):
            tile = values[y : y + MODEL_INPUT_EDGE, x : x + MODEL_INPUT_EDGE]
            tensor = tile.astype(np.float32)[None, None, :, :] / 255.0
            started = time.perf_counter()
            result = session.run([output_name], {input_name: tensor})[0]
            tile_times.append(time.perf_counter() - started)
            if result.shape != (1, 1, tile_out, tile_out) or not np.isfinite(result).all():
                raise PocError(f"MODEL_TILE_OUTPUT_INVALID:{x}:{y}:{result.shape}")
            out = np.clip(result[0, 0] * 255.0, 0.0, 255.0)
            prev_x_overlap = 0 if xi == 0 else (xs[xi - 1] + MODEL_INPUT_EDGE - x) * scale
            next_x_overlap = 0 if xi + 1 == len(xs) else (x + MODEL_INPUT_EDGE - xs[xi + 1]) * scale
            wx = _axis_feather(tile_out, prev_x_overlap, next_x_overlap)
            if yi == 0 and xi:
                seams_x.append(x * scale)
            feather = wy[:, None] * wx[None, :]
            oy, ox = y * scale, x * scale
            accumulator[oy : oy + tile_out, ox : ox + tile_out] += out * feather
            weights[oy : oy + tile_out, ox : ox + tile_out] += feather
    if float(weights.min()) <= 0.0:
        raise PocError("TILE_WEIGHT_COVERAGE_GAP")
    merged = accumulator / weights

    def seam_ratio(axis: int, seams: Iterable[int]) -> float:
        ratios: list[float] = []
        for seam in seams:
            if axis == 1:
                jump = float(np.mean(np.abs(merged[:, seam] - merged[:, seam - 1])))
                local = float(np.mean(np.abs(np.diff(merged[:, seam - 4 : seam + 4], axis=1))))
            else:
                jump = float(np.mean(np.abs(merged[seam] - merged[seam - 1])))
                local = float(np.mean(np.abs(np.diff(merged[seam - 4 : seam + 4], axis=0))))
            ratios.append(jump / max(local, 1e-6))
        return max(ratios, default=0.0)

    return merged, {
        "tile_edge": MODEL_INPUT_EDGE,
        "stride": TILE_STRIDE,
        "overlap": MODEL_INPUT_EDGE - TILE_STRIDE,
        "scale": MODEL_SCALE,
        "tile_count": len(xs) * len(ys),
        "x_positions": xs,
        "y_positions": ys,
        "model_surface_size": [width * scale, height * scale],
        "tile_time_seconds_total": round(sum(tile_times), 6),
        "tile_time_seconds_max": round(max(tile_times), 6),
        "seam_jump_ratio_max_x": round(seam_ratio(1, seams_x), 6),
        "seam_jump_ratio_max_y": round(seam_ratio(0, seams_y), 6),
        "finite": bool(np.isfinite(merged).all()),
    }


def map_box(
    box: tuple[int, int, int, int], source_size: tuple[int, int], target: tuple[int, int]
) -> tuple[int, int, int, int]:
    source_w, source_h = source_size
    target_w, target_h = target
    x0, y0, x1, y1 = box
    mapped = (
        int(math.floor(x0 * target_w / source_w)),
        int(math.floor(y0 * target_h / source_h)),
        int(math.ceil(x1 * target_w / source_w)),
        int(math.ceil(y1 * target_h / source_h)),
    )
    return (
        max(0, min(target_w, mapped[0])),
        max(0, min(target_h, mapped[1])),
        max(0, min(target_w, mapped[2])),
        max(0, min(target_h, mapped[3])),
    )


def _fill_regions(mask: np.ndarray, regions: Iterable[Region], source_size: tuple[int, int]) -> list[dict[str, Any]]:
    height, width = mask.shape
    records: list[dict[str, Any]] = []
    for region in regions:
        x0, y0, x1, y1 = map_box(region.box, source_size, (width, height))
        if x1 <= x0 or y1 <= y0:
            raise PocError(f"INVALID_REGION:{region.region_id}")
        mask[y0:y1, x0:x1] = 1.0
        records.append(
            {
                "region_id": region.region_id,
                "source_box": list(region.box),
                "target_box": [x0, y0, x1, y1],
            }
        )
    return records


def build_masks(baseline_rgb: np.ndarray, source_size: tuple[int, int]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    height, width = baseline_rgb.shape[:2]
    bgr = cv2.cvtColor(baseline_rgb, cv2.COLOR_RGB2BGR)
    reused = phase4_restoration_masks(bgr, {"phase4_product_photo_eligible": True})
    text = np.asarray(reused["text_mask"], dtype=np.float32)
    flat = np.asarray(reused["flat_region_mask"], dtype=np.float32)
    restoration = np.asarray(reused["restoration_mask"], dtype=np.float32)
    if any(item.shape != (height, width) for item in (text, flat, restoration)):
        raise PocError("REUSED_MASK_SHAPE_MISMATCH")
    if not all(np.isfinite(item).all() for item in (text, flat, restoration)):
        raise PocError("REUSED_MASK_NONFINITE")

    photo_hard = np.zeros((height, width), dtype=np.float32)
    photo_records = _fill_regions(photo_hard, PHOTO_REGIONS, source_size)
    photo_soft = cv2.GaussianBlur(photo_hard, (0, 0), 10.0)
    photo_soft = np.clip(photo_soft, 0.0, 1.0)

    manual_protect = np.zeros((height, width), dtype=np.float32)
    protected_records = _fill_regions(manual_protect, PROTECTED_REGIONS, source_size)
    text_hard = cv2.dilate((text > 0.05).astype(np.uint8), np.ones((9, 9), np.uint8), iterations=1)
    hard_protect = np.maximum(manual_protect, text_hard.astype(np.float32))

    activation = photo_soft * np.clip(restoration, 0.0, 1.0)
    activation *= 1.0 - np.clip(flat, 0.0, 1.0) * 0.72
    activation *= MODEL_BLEND
    activation[hard_protect > 0.0] = 0.0
    activation = cv2.GaussianBlur(activation, (0, 0), 1.0)
    activation[hard_protect > 0.0] = 0.0
    activation = np.clip(activation, 0.0, MODEL_BLEND).astype(np.float32)
    if float(np.max(activation)) <= 0.0:
        raise PocError("NO_PHOTO_ACTIVATION")
    return {
        "activation": activation,
        "manual_protect": manual_protect,
        "text_hard": text_hard.astype(np.float32),
        "hard_protect": hard_protect,
        "flat": flat,
        "photo_hard": photo_hard,
    }, {
        "mask_contract": "SAMPLE_BOUND_PHOTO_ROI_PLUS_TEXT_FLAT_GLASS_PROTECTION_V1",
        "photo_regions": photo_records,
        "protected_regions": protected_records,
        "photo_fraction": round(float(np.mean(photo_hard > 0.0)), 8),
        "manual_protected_fraction": round(float(np.mean(manual_protect > 0.0)), 8),
        "auto_text_protected_fraction": round(float(np.mean(text_hard > 0.0)), 8),
        "flat_fraction": round(float(np.mean(flat > 0.6)), 8),
        "activation_fraction": round(float(np.mean(activation > 1e-6)), 8),
        "activation_mean": round(float(np.mean(activation)), 8),
        "activation_max": round(float(np.max(activation)), 8),
        "ocr_used": False,
        "annotation_scope": "ONE_BOUND_REAL_SAMPLE_ONLY",
        "content_region_method": CONTENT_REGION_METHOD,
        "automatic_content_recognition": AUTOMATIC_CONTENT_RECOGNITION,
        "generalization": GENERALIZATION,
    }


def build_candidate(
    baseline_rgb: np.ndarray,
    model_y_target: np.ndarray,
    masks: dict[str, np.ndarray],
) -> tuple[np.ndarray, dict[str, Any]]:
    baseline = np.asarray(baseline_rgb, dtype=np.uint8)
    baseline_y = np.asarray(Image.fromarray(baseline, "RGB").convert("YCbCr").split()[0], dtype=np.float32)
    proposal = np.asarray(model_y_target, dtype=np.float32)
    if proposal.shape != baseline_y.shape or not np.isfinite(proposal).all():
        raise PocError("MODEL_PROPOSAL_INVALID")
    raw_residual = proposal - baseline_y
    local_bias = cv2.GaussianBlur(raw_residual, (0, 0), 6.0)
    source_grounded_residual = raw_residual - local_bias
    bounded = np.clip(source_grounded_residual, -MODEL_RESIDUAL_LIMIT, MODEL_RESIDUAL_LIMIT)
    delta = bounded * masks["activation"]
    delta = np.clip(delta, -APPLIED_LUMA_LIMIT, APPLIED_LUMA_LIMIT)

    local_min = cv2.erode(baseline_y, np.ones((3, 3), np.uint8)) - LOCAL_EXTREMA_MARGIN
    local_max = cv2.dilate(baseline_y, np.ones((3, 3), np.uint8)) + LOCAL_EXTREMA_MARGIN
    proposed_y = np.clip(baseline_y + delta, local_min, local_max)
    delta = proposed_y - baseline_y
    delta[masks["hard_protect"] > 0.0] = 0.0

    base_f = baseline.astype(np.float32)
    lower = -np.min(base_f, axis=2)
    upper = 255.0 - np.max(base_f, axis=2)
    delta = np.minimum(np.maximum(delta, lower), upper)
    applied_integer = np.rint(delta).astype(np.int16)
    applied_integer[masks["hard_protect"] > 0.0] = 0
    candidate = np.clip(base_f + applied_integer[:, :, None], 0.0, 255.0).astype(np.uint8)
    return candidate, {
        "operator": "ESPCN_X3_LUMA_RESIDUAL_SOFT_ROI_BLEND_V1",
        "global_sharpen": False,
        "unsharp_mask": False,
        "model_blend_max": MODEL_BLEND,
        "raw_residual": summary(raw_residual),
        "local_bias": summary(local_bias),
        "source_grounded_residual": summary(source_grounded_residual),
        "bounded_residual": summary(bounded),
        "applied_integer_delta": summary(applied_integer),
        "changed_pixel_fraction": round(float(np.mean(applied_integer != 0)), 8),
        "changed_pixels": int(np.count_nonzero(applied_integer)),
        "residual_limit": MODEL_RESIDUAL_LIMIT,
        "applied_luma_limit": APPLIED_LUMA_LIMIT,
        "local_extrema_margin": LOCAL_EXTREMA_MARGIN,
        "color_method": "EQUAL_RGB_LUMA_DELTA_WITH_CLIP_GUARD",
    }


def summary(values: np.ndarray) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float32)
    return {
        "min": round(float(np.min(array)), 6),
        "max": round(float(np.max(array)), 6),
        "mean": round(float(np.mean(array)), 8),
        "mean_abs": round(float(np.mean(np.abs(array))), 8),
        "p01": round(float(np.percentile(array, 1)), 6),
        "p50": round(float(np.percentile(array, 50)), 6),
        "p99": round(float(np.percentile(array, 99)), 6),
    }


def _luma(rgb: np.ndarray) -> np.ndarray:
    # Keep generation and safety review on the exact same Pillow YCbCr-Y
    # convention. Mixing this with OpenCV GRAY creates one-level rounding
    # disagreements that look like extrema violations but are not overshoot.
    image = Image.fromarray(np.asarray(rgb, dtype=np.uint8), "RGB")
    return np.asarray(image.convert("YCbCr").split()[0], dtype=np.float32)


def _lab_delta(reference: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    ref = cv2.cvtColor(reference.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    out = cv2.cvtColor(candidate.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    return np.linalg.norm(out - ref, axis=2)


def _hf_energy(gray: np.ndarray, mask: np.ndarray | None = None) -> float:
    energy = np.abs(cv2.Laplacian(gray.astype(np.float32), cv2.CV_32F, ksize=3))
    if mask is None:
        return float(np.mean(energy))
    selected = np.asarray(mask) > 0
    return float(np.mean(energy[selected])) if np.any(selected) else 0.0


def assess_safety(
    source_rgb: np.ndarray,
    baseline_rgb: np.ndarray,
    candidate_rgb: np.ndarray,
    masks: dict[str, np.ndarray],
) -> dict[str, Any]:
    diff = candidate_rgb.astype(np.int16) - baseline_rgb.astype(np.int16)
    abs_diff = np.abs(diff)
    hard = masks["hard_protect"] > 0.0
    manual = masks["manual_protect"] > 0.0
    auto_text = masks["text_hard"] > 0.0
    flat = masks["flat"] > 0.6
    baseline_y = _luma(baseline_rgb)
    candidate_y = _luma(candidate_rgb)
    local_min = cv2.erode(baseline_y, np.ones((3, 3), np.uint8)) - 2.0
    local_max = cv2.dilate(baseline_y, np.ones((3, 3), np.uint8)) + 2.0
    extrema_violation = (candidate_y < local_min) | (candidate_y > local_max)
    lab_delta = _lab_delta(baseline_rgb, candidate_rgb)
    base_hsv = cv2.cvtColor(baseline_rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    cand_hsv = cv2.cvtColor(candidate_rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    saturation_delta = np.abs(cand_hsv[:, :, 1] - base_hsv[:, :, 1])

    baseline_flat_hf = _hf_energy(baseline_y, flat)
    candidate_flat_hf = _hf_energy(candidate_y, flat)
    flat_hf_ratio = candidate_flat_hf / max(baseline_flat_hf, 1e-8)
    flat_changed_fraction = float(np.mean(np.any(abs_diff[flat] > 0, axis=1))) if np.any(flat) else 0.0

    source_image = Image.fromarray(source_rgb, "RGB")
    baseline_down = np.asarray(Image.fromarray(baseline_rgb, "RGB").resize(source_image.size, Image.Resampling.LANCZOS))
    candidate_down = np.asarray(Image.fromarray(candidate_rgb, "RGB").resize(source_image.size, Image.Resampling.LANCZOS))
    baseline_cycle_mae = float(np.mean(np.abs(baseline_down.astype(np.float32) - source_rgb.astype(np.float32))))
    candidate_cycle_mae = float(np.mean(np.abs(candidate_down.astype(np.float32) - source_rgb.astype(np.float32))))

    manual_max = int(abs_diff[manual].max()) if np.any(manual) else 0
    text_max = int(abs_diff[auto_text].max()) if np.any(auto_text) else 0
    hard_max = int(abs_diff[hard].max()) if np.any(hard) else 0
    masked_identity_pass = bool(manual_max == 0 and text_max == 0 and hard_max == 0)
    safety_pass = bool(
        masked_identity_pass
        and float(np.mean(extrema_violation)) <= 1e-6
        and float(np.mean(lab_delta)) <= 0.6
        and float(np.percentile(lab_delta, 95)) <= 2.0
        and flat_hf_ratio <= 1.03
    )
    return {
        "status": "PASS" if safety_pass else "FAIL",
        "status_scope": "AUTOMATED_SCREENS_ONLY",
        "masked_region_identity": {
            "status": "PASS" if masked_identity_pass else "FAIL",
            "all_hard_protected_rgb_max_abs_delta": hard_max,
        },
        "text_protection": {
            "status": "PENDING_COVERAGE_REVIEW",
            "masked_pixels_byte_exact": "PASS" if masked_identity_pass else "FAIL",
            "all_text_logo_icon_coverage": ALL_TEXT_LOGO_ICON_COVERAGE,
            "manual_protected_rgb_max_abs_delta": manual_max,
            "auto_text_rgb_max_abs_delta": text_max,
            "all_hard_protected_rgb_max_abs_delta": hard_max,
            "scope": "BOUND_TEXT_LOGO_ICON_LABEL_REGIONS_PLUS_HEURISTIC_TEXT_MASK",
        },
        "color_lock": {
            "status": "PASS" if float(np.mean(lab_delta)) <= 0.6 and float(np.percentile(lab_delta, 95)) <= 2.0 else "FAIL",
            "delta_e76_mean": round(float(np.mean(lab_delta)), 6),
            "delta_e76_p95": round(float(np.percentile(lab_delta, 95)), 6),
            "delta_e76_max": round(float(np.max(lab_delta)), 6),
            "saturation_delta_mean": round(float(np.mean(saturation_delta)), 6),
            "saturation_delta_p95": round(float(np.percentile(saturation_delta, 95)), 6),
        },
        "halo_ringing": {
            "status": "PASS" if float(np.mean(extrema_violation)) <= 1e-6 else "FAIL",
            "local_extrema_violation_fraction": round(float(np.mean(extrema_violation)), 10),
            "method": "3X3_BASELINE_LOCAL_EXTREMA_ENVELOPE",
            "automated_screen_only": True,
        },
        "false_texture": {
            "status": "SCREEN_PASS" if flat_hf_ratio <= 1.03 else "SCREEN_FAIL",
            "flat_region_hf_ratio": round(float(flat_hf_ratio), 6),
            "flat_region_changed_fraction": round(flat_changed_fraction, 8),
            "reference_proof": "NOT_AVAILABLE_FOR_SINGLE_REAL_SAMPLE",
        },
        "fidelity": {
            "rgb_mean_abs_delta": round(float(np.mean(abs_diff)), 6),
            "rgb_p95_abs_delta": round(float(np.percentile(abs_diff, 95)), 6),
            "rgb_max_abs_delta": int(np.max(abs_diff)),
            "baseline_source_cycle_mae": round(baseline_cycle_mae, 6),
            "candidate_source_cycle_mae": round(candidate_cycle_mae, 6),
            "cycle_metric_role": "SOURCE_FIDELITY_DIAGNOSTIC_NOT_REAL_INFORMATION_GAIN_PROOF",
        },
    }


def roi_metrics(
    baseline_rgb: np.ndarray,
    candidate_rgb: np.ndarray,
    source_size: tuple[int, int],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for roi in QUALITY_ROIS:
        x0, y0, x1, y1 = map_box(roi.box, source_size, (baseline_rgb.shape[1], baseline_rgb.shape[0]))
        base = baseline_rgb[y0:y1, x0:x1]
        cand = candidate_rgb[y0:y1, x0:x1]
        diff = np.abs(cand.astype(np.int16) - base.astype(np.int16))
        base_hf = _hf_energy(_luma(base))
        cand_hf = _hf_energy(_luma(cand))
        records.append(
            {
                "roi_id": roi.region_id,
                "source_box": list(roi.box),
                "target_box": [x0, y0, x1, y1],
                "target_size": [x1 - x0, y1 - y0],
                "rgb_mean_abs_delta": round(float(np.mean(diff)), 6),
                "rgb_max_abs_delta": int(np.max(diff)),
                "hf_ratio_diagnostic": round(cand_hf / max(base_hf, 1e-8), 6),
                "quality_claim": "NOT_DERIVED_FROM_HF_RATIO",
            }
        )
    return records


def encode_delivery(image: Image.Image, output: Path) -> dict[str, Any]:
    image.save(output, format="WEBP", lossless=True, quality=100, method=6, exact=True)
    size = output.stat().st_size
    if size <= MAX_OUTPUT_BYTES:
        return {
            "format": "WEBP",
            "lossless": True,
            "quality": 100,
            "method": 6,
            "exact": True,
            "bytes": size,
            "max_output_bytes": MAX_OUTPUT_BYTES,
            "size_budget_pass": True,
        }
    output.unlink()
    selected: dict[str, Any] | None = None
    for quality in range(100, 79, -1):
        image.save(output, format="WEBP", lossless=False, quality=quality, method=6, exact=True)
        size = output.stat().st_size
        if size <= MAX_OUTPUT_BYTES:
            selected = {
                "format": "WEBP",
                "lossless": False,
                "quality": quality,
                "method": 6,
                "exact": True,
                "bytes": size,
                "max_output_bytes": MAX_OUTPUT_BYTES,
                "size_budget_pass": True,
            }
            break
    if selected is None:
        raise PocError("SIZE_BUDGET_UNACHIEVABLE_AT_MINIMUM_ALLOWED_WEBP_QUALITY")
    return selected


def _font() -> ImageFont.ImageFont:
    return ImageFont.load_default(size=18)


def save_roi_evidence(
    root: Path,
    source: Image.Image,
    baseline: Image.Image,
    candidate: Image.Image,
) -> list[dict[str, Any]]:
    roi_root = root / "roi_100pct"
    roi_root.mkdir(parents=True, exist_ok=False)
    records: list[dict[str, Any]] = []
    for roi in QUALITY_ROIS:
        source_crop = source.crop(roi.box)
        target_box = map_box(roi.box, source.size, baseline.size)
        baseline_crop = baseline.crop(target_box)
        candidate_crop = candidate.crop(target_box)
        source_path = roi_root / f"{roi.region_id}__SOURCE_100P.png"
        baseline_path = roi_root / f"{roi.region_id}__LANCZOS_100P.png"
        candidate_path = roi_root / f"{roi.region_id}__CANDIDATE_100P.png"
        source_crop.save(source_path, compress_level=9)
        baseline_crop.save(baseline_path, compress_level=9)
        candidate_crop.save(candidate_path, compress_level=9)

        pad = 12
        header = 34
        panels = (
            ("SOURCE 100%", source_crop),
            ("LANCZOS 100%", baseline_crop),
            ("CANDIDATE 100%", candidate_crop),
        )
        canvas_w = sum(panel.width for _, panel in panels) + pad * (len(panels) + 1)
        canvas_h = max(panel.height for _, panel in panels) + header + pad * 2
        canvas = Image.new("RGB", (canvas_w, canvas_h), (28, 30, 34))
        draw = ImageDraw.Draw(canvas)
        x = pad
        for label, panel in panels:
            draw.text((x, 8), f"{label}  {panel.width}x{panel.height}", fill="white", font=_font())
            canvas.paste(panel, (x, header + pad))
            x += panel.width + pad
        triptych_path = roi_root / f"{roi.region_id}__TRIPTYCH_NATIVE_100P.png"
        canvas.save(triptych_path, compress_level=9)

        pair_w = baseline_crop.width * 2 + pad * 3
        pair_h = baseline_crop.height + header + pad * 2
        pair = Image.new("RGB", (pair_w, pair_h), (28, 30, 34))
        pair_draw = ImageDraw.Draw(pair)
        pair_draw.text((pad, 8), "LANCZOS 100%", fill="white", font=_font())
        pair_draw.text((baseline_crop.width + pad * 2, 8), "CANDIDATE 100%", fill="white", font=_font())
        pair.paste(baseline_crop, (pad, header + pad))
        pair.paste(candidate_crop, (baseline_crop.width + pad * 2, header + pad))
        pair_path = roi_root / f"{roi.region_id}__TARGET_PAIR_100P.png"
        pair.save(pair_path, compress_level=9)
        records.append(
            {
                "roi_id": roi.region_id,
                "source_box": list(roi.box),
                "target_box": list(target_box),
                "source_100pct": str(source_path.relative_to(root)),
                "lanczos_100pct": str(baseline_path.relative_to(root)),
                "candidate_100pct": str(candidate_path.relative_to(root)),
                "triptych_native_100pct": str(triptych_path.relative_to(root)),
                "target_pair_100pct": str(pair_path.relative_to(root)),
                "layout_note": "No panel pixels are resized in the evidence sheets.",
            }
        )
    return records


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_reports(root: Path, manifest: dict[str, Any]) -> None:
    model = manifest["model_eligibility"]
    model_md = f"""# Model Eligibility\n\n- STATUS: {model['status']}\n- MODEL_ID: {model['model_id']}\n- MODEL_VERSION: {model['model_version']}\n- MODEL_SCALE: {MODEL_SCALE}\n- SHA256: `{model['model_sha256']}`\n- BYTES: {model['model_bytes']}\n- LICENSE: {model['license']}\n- MODEL_PAGE: {model['model_page_url']}\n- DOWNLOAD: {model['download_url']}\n- LICENSE_SOURCE: {model['license_url']}\n- RUNTIME: {model['runtime_backend']} / ONNX Runtime {model['runtime_version']}\n- INPUT: {model['input']['shape']}\n- OUTPUT: {model['output']['shape']}\n- LOCAL_INFERENCE_ONLY: YES\n- GAN: NO\n- DIFFUSION: NO\n- FACE_SPECIFIC_REDRAW_MODEL: NO\n- TEXT_SPECIFIC_REDRAW_MODEL: NO\n- TEXT_INFERENCE_SCOPE: blocked only inside the bound hard mask; complete text/logo/icon coverage is not proven\n- TOPAZ_WEIGHT: NO\n\n## Qualification note\n\n{model['model_card_contract_note']}\n"""
    (root / "MODEL_ELIGIBILITY.md").write_text(model_md, encoding="utf-8")
    write_json(root / "MODEL_ELIGIBILITY.json", model)

    decision = manifest["decision"]
    encoding = manifest["encoding"]
    safety = manifest["safety"]
    closure = manifest["closure"]
    report = f"""# {CLOSURE_TASK_ID}｜Evidence Truth Correction & Current Candidate Closure\n\n## Closure outcome\n\n- STATUS: {closure['status']}\n- USER_VISIBLE_CLARITY_VERDICT: {closure['user_visible_clarity_verdict']}\n- CODEX_VISUAL_SCREEN: {closure['codex_visual_screen']}\n- INDEPENDENT_HUMAN_SAFETY_REVIEW: {closure['independent_human_safety_review']}\n- CURRENT_MODEL_DECISION: {closure['current_model_decision']}\n- MODEL_ID: {closure['model_id']}\n- MODEL_SCALE: {closure['model_scale']}\n- REAL_4K_QUALITY_GAIN: {closure['real_4k_quality_gain']}\n- CONTINUE_STRENGTH_TUNING: {closure['continue_strength_tuning']}\n- READY_FOR_FORMAL_CANDIDATE: {closure['ready_for_formal_candidate']}\n- SIZE_BUDGET_PASS: {encoding['size_budget_pass']} ({encoding['bytes']} / {encoding['max_output_bytes']} bytes)\n\nThe user confirmed only that visible clarity is below expectation. Codex visual screening is not an independent human safety review. Sharpness/HF changes remain diagnostic only and are not real-information-gain proof. The x2 label requested during closure conflicts with the bound graph: this asset is the recorded ESPCN x3 model.\n\n## Evidence scope\n\n- MASKED_REGION_IDENTITY: {closure['masked_region_identity']}\n- ALL_TEXT_LOGO_ICON_COVERAGE: {closure['all_text_logo_icon_coverage']}\n- TEXT_PROTECTION: {closure['text_protection']}\n- CONTENT_REGION_METHOD: {closure['content_region_method']}\n- AUTOMATIC_CONTENT_RECOGNITION: {closure['automatic_content_recognition']}\n- GENERALIZATION: {closure['generalization']}\n- COLOR_LOCK_AUTOMATED_SCREEN: {safety['color_lock']['status']}\n- HALO_RINGING_AUTOMATED_SCREEN: {safety['halo_ringing']['status']}\n- FALSE_TEXTURE_FLAT_REGION_SCREEN: {safety['false_texture']['status']}\n\nNo user claim is made for false windows, synthetic leaf texture, Halo, Ringing, or complete text safety. The legacy filename `HUMAN_VISUAL_REVIEW.md` now records review scope and does not claim a completed human safety review.\n\n## Isolation\n\n- FORMAL_PIPELINE_CHANGED: NO\n- API_CHANGED: NO\n- UI_CHANGED: NO\n- PRODUCT_VERSION_CHANGED: NO\n- CHECKED_PROTECTED_FILES_CHANGED: {closure['checked_protected_files_changed']}\n- FULL_FROZEN_TREE_PRE_POST_PROOF: {closure['full_frozen_tree_pre_post_proof']}\n- GIT_WRITE: NONE\n\nSee `manifest.json`, `MODEL_ELIGIBILITY.json`, `QUALITY_SAFETY.json`, and `roi_100pct/manifest.json` for machine-readable evidence.\n"""
    (root / "REPORT.md").write_text(report, encoding="utf-8")


def run(
    source_path: Path = SOURCE_PATH,
    baseline_path: Path = BASELINE_PATH,
    model_path: Path = MODEL_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    if output_root.exists():
        raise PocError(f"OUTPUT_ROOT_ALREADY_EXISTS:{output_root}")
    source, source_record = load_rgb(source_path)
    baseline, baseline_record = load_rgb(baseline_path)
    if source_record["sha256"] != EXPECTED_SOURCE_SHA256:
        raise PocError(f"SOURCE_BINDING_MISMATCH:{source_record['sha256']}")
    if baseline_record["sha256"] != EXPECTED_BASELINE_SHA256:
        raise PocError(f"BASELINE_BINDING_MISMATCH:{baseline_record['sha256']}")
    expected_target = target_size(source.size)
    if baseline.size != expected_target:
        raise PocError(f"BASELINE_SIZE_MISMATCH:{baseline.size}:{expected_target}")
    regenerated = source.resize(expected_target, Image.Resampling.LANCZOS)
    baseline_rgb = np.asarray(baseline, dtype=np.uint8)
    regenerated_rgb = np.asarray(regenerated, dtype=np.uint8)
    if not np.array_equal(baseline_rgb, regenerated_rgb):
        raise PocError("BASELINE_NOT_PIXEL_EXACT_PILLOW_LANCZOS")

    session, model_record = verify_model(model_path)
    source_y = np.asarray(source.convert("YCbCr").split()[0], dtype=np.uint8)
    model_y_x3, tile_record = infer_tiled_luma(session, source_y)
    model_y_target = np.asarray(
        Image.fromarray(np.rint(model_y_x3).astype(np.uint8), "L").resize(
            expected_target, Image.Resampling.LANCZOS
        ),
        dtype=np.float32,
    )
    masks, mask_record = build_masks(baseline_rgb, source.size)
    candidate_rgb, candidate_record = build_candidate(baseline_rgb, model_y_target, masks)
    source_rgb = np.asarray(source, dtype=np.uint8)
    safety = assess_safety(source_rgb, baseline_rgb, candidate_rgb, masks)
    rois = roi_metrics(baseline_rgb, candidate_rgb, source.size)
    if safety["status"] != "PASS":
        raise PocError(f"SAFETY_GATE_FAILED:{safety}")
    if np.array_equal(candidate_rgb, baseline_rgb):
        raise PocError("CANDIDATE_EQUALS_BASELINE")

    output_root.mkdir(parents=True, exist_ok=False)
    baseline_output = output_root / "01_lanczos_baseline.png"
    candidate_output = output_root / "02_candidate_quality_master.png"
    delivery_output = output_root / "03_candidate_delivery.webp"
    mask_output = output_root / "04_sr_activation_mask.png"
    protect_output = output_root / "05_hard_protection_mask.png"
    regenerated.save(baseline_output, format="PNG", compress_level=9, optimize=True)
    candidate_image = Image.fromarray(candidate_rgb, "RGB")
    candidate_image.save(candidate_output, format="PNG", compress_level=9, optimize=True)
    Image.fromarray(np.rint(masks["activation"] / MODEL_BLEND * 255.0).astype(np.uint8), "L").save(mask_output, compress_level=9)
    Image.fromarray(np.rint(np.clip(masks["hard_protect"], 0.0, 1.0) * 255.0).astype(np.uint8), "L").save(protect_output, compress_level=9)
    encoding = encode_delivery(candidate_image, delivery_output)
    roi_files = save_roi_evidence(output_root, source, regenerated, candidate_image)

    with Image.open(delivery_output) as decoded:
        decoded_rgb = np.asarray(decoded.convert("RGB"), dtype=np.uint8)
    delivery_pixel_exact = bool(np.array_equal(decoded_rgb, candidate_rgb))
    if encoding["lossless"] and not delivery_pixel_exact:
        raise PocError("LOSSLESS_WEBP_DECODE_NOT_PIXEL_EXACT")
    if not encoding["size_budget_pass"] or encoding["bytes"] > MAX_OUTPUT_BYTES:
        raise PocError("SIZE_BUDGET_FAILED")
    encoding["decoded_pixel_exact_to_quality_master"] = delivery_pixel_exact

    files = {}
    for path in sorted(item for item in output_root.rglob("*") if item.is_file()):
        files[str(path.relative_to(output_root))] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    decision = {
        "status": "NOT_PROVEN",
        "visible_clarity_gain": USER_VISIBLE_CLARITY_VERDICT,
        "real_4k_quality_gain": "NOT_PROVEN",
        "ready_for_formal_candidate": "NO",
        "reasons": [
            "AUTOMATED_SAFETY_AND_SIZE_GATES_PASS",
            "REAL_INFORMATION_GAIN_CANNOT_BE_PROVEN_BY_SHARPNESS_OR_HF_METRICS",
            "ONE_REAL_SAMPLE_HAS_NO_TARGET_RESOLUTION_GROUND_TRUTH",
            "USER_REPORTED_VISIBLE_CLARITY_BELOW_EXPECTATION",
            "INDEPENDENT_HUMAN_SAFETY_REVIEW_PENDING",
        ],
    }
    manifest: dict[str, Any] = {
        "artifact_version": ARTIFACT_VERSION,
        "task_id": TASK_ID,
        "created_at_utc": utc_now(),
        "source": source_record,
        "current_baseline": baseline_record,
        "baseline_verification": {
            "pixel_exact_pillow_lanczos": True,
            "pixel_sha256": pixel_sha256(baseline_rgb),
            "target_size": list(expected_target),
            "resampling": "PIL.Image.Resampling.LANCZOS",
        },
        "model_eligibility": model_record,
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "processor": platform.processor(),
            "onnxruntime": ort.__version__,
            "providers": session.get_providers(),
            "pid": os.getpid(),
        },
        "tiling": tile_record,
        "masking": mask_record,
        "candidate": candidate_record,
        "safety": safety,
        "roi_metrics": rois,
        "encoding": encoding,
        "roi_evidence": roi_files,
        "decision": decision,
        "closure": closure_evidence(),
        "claim_policy": {
            "sharpness_is_real_gain_proof": False,
            "high_frequency_is_real_gain_proof": False,
            "single_sample_no_gt_can_prove_real_4k_gain": False,
        },
        "isolation": {
            "formal_pipeline_changed": False,
            "api_changed": False,
            "ui_changed": False,
            "product_version_changed": False,
            "formal_output_chain_connected": False,
            "checked_protected_files_changed": False,
            "full_frozen_tree_pre_post_proof": "NOT_AVAILABLE",
            "git_write": "NONE",
        },
    }
    write_json(output_root / "QUALITY_SAFETY.json", safety)
    write_json(output_root / "roi_100pct" / "manifest.json", {"rois": roi_files, "metrics": rois})
    write_reports(output_root, manifest)
    files = {}
    for path in sorted(item for item in output_root.rglob("*") if item.is_file()):
        files[str(path.relative_to(output_root))] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    manifest["files"] = files
    write_json(output_root / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_PATH)
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    try:
        manifest = run(args.source, args.baseline, args.model, args.output_root)
    except Exception as exc:
        print(f"STATUS=BLOCKED\nERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        return 1
    print(f"STATUS={manifest['decision']['status']}")
    print(f"MODEL_ELIGIBILITY={manifest['model_eligibility']['status']}")
    print(f"MODEL_ID={manifest['model_eligibility']['model_id']}")
    print(f"MODEL_SHA256={manifest['model_eligibility']['model_sha256']}")
    print(f"RUNTIME_BACKEND={manifest['model_eligibility']['runtime_backend']}")
    print(f"DELIVERY_SIZE_BYTES={manifest['encoding']['bytes']}")
    print(f"SIZE_BUDGET_PASS={manifest['encoding']['size_budget_pass']}")
    print(f"REAL_4K_QUALITY_GAIN={manifest['decision']['real_4k_quality_gain']}")
    print(f"E4K04_CLOSURE_STATUS={manifest['closure']['status']}")
    print(f"REPORT={args.output_root / 'REPORT.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
