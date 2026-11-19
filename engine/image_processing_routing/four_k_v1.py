from __future__ import annotations

import copy
import hashlib
import io
import math
import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageCms, ImageOps

from engine.output.filename_policy import FEATURE_4K, build_output_path
from engine.output.metadata_writer import _read_effective_dpi
from engine.output.publish_safety import OutputMetadataStageError, publish_image_file_with_metadata
from runtime.system_info import resource_root


FOUR_K_V1_CONTRACT_VERSION = "4k_v1_contract_2.3"
FOUR_K_V1_ROUTE = "REALESRGAN_X4PLUS_FIDELITY_FUSION"
FOUR_K_V1_MODE = "4k_v1"
FOUR_K_V1_OUTPUT_PROFILE = "delivery_4k_v1"
FOUR_K_V1_TARGET_RESOLUTION = "4K"
FOUR_K_V1_TARGET_LONG_EDGE = 3840
FOUR_K_V1_OUTPUT_FORMAT = "PNG"
FOUR_K_V1_OUTPUT_DIRECTORY = "输出/4K画质增强"
FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY = "SR_DETAIL_ENHANCEMENT_WITH_SOURCE_FIDELITY_GUARD"
FOUR_K_V1_COMPLETED_CONCLUSION = "DETAIL_ENHANCEMENT_COMPLETED"
# Route identifier kept for compatibility with already registered results; the
# model actually used is FOUR_K_V1_SR_MODEL (reported in the contract).
FOUR_K_V1_SR_MODEL = "realesr-animevideov3-x3"
FOUR_K_V1_SR_SCALE = 3
FOUR_K_V1_SR_TIMEOUT_SECONDS = 1500
# Fidelity fusion (v4), luminance only; chroma is the LANCZOS upscale of the original,
# so the SR can never shift colour. Band limits are in source pixels.
FOUR_K_V1_FINE_SIGMA = 0.5
FOUR_K_V1_MID_SIGMA = 2.0
FOUR_K_V1_STRUCT_SIGMA = 4.0
# Mid band (the scale that reads as sharpness at viewing size) follows the SR, but the
# SR may only move it by a fraction of the local source structure amplitude, so it
# sharpens existing transitions and cannot draw new lines (knit, fabric).
FOUR_K_V1_MID_SR_FOLLOW = 0.9
FOUR_K_V1_MID_SR_CAP = 0.25
FOUR_K_V1_MID_GAIN = 2.2
FOUR_K_V1_STRUCT_GAIN = 1.2
# Fine band from the SR, bounded by the local source structure amplitude; weaker on
# flat areas (measured on the source) and skin, where part of the source micro-texture
# is kept instead. No SR on tiny strokes.
FOUR_K_V1_FLAT_STD_RANGE = (0.015, 0.07)
FOUR_K_V1_FINE_GAIN = 1.0
FOUR_K_V1_FINE_FLAT_SHARE = 0.4
FOUR_K_V1_MID_FLAT_SHARE = 0.6
FOUR_K_V1_SKIN_FINE_DAMP = 0.4
FOUR_K_V1_SKIN_SOURCE_FINE = 0.5
FOUR_K_V1_HALO_CLAMP = 0.012
# Tiny text: dense clusters of thin high-contrast strokes. They come from the clean
# LANCZOS base only, sharpened at stroke scale within the base's local range, so
# strokes are never thinned, broken or outlined by the SR.
FOUR_K_V1_EDGE_RANGE = (0.18, 0.45)
FOUR_K_V1_STROKE_HAT = 0.20
FOUR_K_V1_STROKE_DENSITY_RANGE = (0.18, 0.30)
FOUR_K_V1_STROKE_SHARPEN = 1.2
FOUR_K_V1_STROKE_SHARPEN_SIGMA = 0.6
# Back-projection: only the low band of the result must match the original when
# scaled back (tone lock). Sharpening inside the source band is allowed.
FOUR_K_V1_BACK_PROJECTION_SIGMA = 2.5
FOUR_K_V1_BACK_PROJECTION_ITERATIONS = 2
# Chroma follow: the luminance is sharpened but the chroma is the softer LANCZOS upscale,
# so at saturated colour edges the two disagree (pale rims, dark or purple outlines).
# Where the source has a clear two-colour edge (high chroma spread, chroma tightly tied
# to luma), the chroma moves along the local colour line by the luma sharpening, clamped
# to the local range of the LANCZOS chroma: no new colours, luminance untouched.
FOUR_K_V1_CHROMA_FOLLOW_SIGMA = 1.0
FOUR_K_V1_CHROMA_FOLLOW_STD_RANGE = (0.06, 0.14)
FOUR_K_V1_CHROMA_FOLLOW_R2_RANGE = (0.75, 0.95)
# Text clarity: inside text found by the PP-OCRv3 Chinese detector (OpenCV zoo, Apache-2.0),
# the luminance follows the SR, bounded by the local range of the LANCZOS base (no halo, no
# new tone) and by a stroke-area guard (SR may not thin or thicken strokes). Display-size
# type is left to v4. Outside the detected text the result is the v4 result, pixel for pixel.
FOUR_K_V1_TEXT_MODEL_RELATIVE = Path("models") / "text_detection" / "text_detection_cn_ppocrv3_2023may.onnx"
FOUR_K_V1_TEXT_MODEL_SHA256 = "03f550c6b406fda8bf54bd8327815f6c7e2edd98cea02348c93d879254366587"
FOUR_K_V1_TEXT_DETECT_MAX_SIDE = 2560
FOUR_K_V1_TEXT_DETECT_MIN_SIDE = 960
FOUR_K_V1_TEXT_PROB_THRESHOLD = 0.3
FOUR_K_V1_TEXT_MAX_KERNEL_THICK = 24
FOUR_K_V1_TEXT_RANGE_RADIUS = 3.0
FOUR_K_V1_TEXT_GUARD_SIGMA = 2.0
FOUR_K_V1_TEXT_GUARD_DEVIATION = (0.08, 0.20)


_FOUR_K_V1_CONTRACT: dict[str, Any] = {
    "contract_version": FOUR_K_V1_CONTRACT_VERSION,
    "freeze_status": "FROZEN",
    "route": FOUR_K_V1_ROUTE,
    "mode": FOUR_K_V1_MODE,
    "output_profile": FOUR_K_V1_OUTPUT_PROFILE,
    "target_resolution": FOUR_K_V1_TARGET_RESOLUTION,
    "quality_capability_boundary": FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY,
    "request": {
        "endpoint": "/api/upload",
        "content_type": "multipart/form-data",
        "required_fields": ["file", "mode", "output_profile", "output_format"],
        "fixed_parameters": {
            "mode": FOUR_K_V1_MODE,
            "output_profile": FOUR_K_V1_OUTPUT_PROFILE,
            "output_format": "png",
        },
        "forbidden_overrides": [
            "scale",
            "target_width",
            "target_height",
            "target_long_edge",
            "resize_method",
            "ai_model",
            "enhancement_strength",
        ],
    },
    "dimensions": {
        "target_long_edge": FOUR_K_V1_TARGET_LONG_EDGE,
        "aspect_ratio_policy": "PRESERVE",
        "rounding_policy": "ROUND_HALF_UP",
        "maximum_aspect_ratio_error_pixels": 1,
        "source_long_edge_lt_3840": "UPSCALE_LONG_EDGE_TO_3840",
        "source_long_edge_ge_3840": "NO_PROCESSING_NEEDED",
        "crop_policy": "FORBIDDEN",
        "stretch_policy": "FORBIDDEN",
        "padding_policy": "FORBIDDEN",
    },
    "source": {
        "policy": "DIRECT_FROM_ORIGINAL",
        "original_write_policy": "READ_ONLY",
        "forbidden_sources": [
            "1080P_STANDARD_OUTPUT",
            "1080P_SAFE_OUTPUT",
            "OTHER_RESIZED_OR_ENHANCED_INTERMEDIATE",
        ],
        "required_integrity_fields": [
            "input_hash",
            "input_width",
            "input_height",
            "input_format",
            "has_alpha",
        ],
    },
    "output": {
        "directory_relative_to_formal_root": FOUR_K_V1_OUTPUT_DIRECTORY,
        "directory_failure_policy": "BLOCK_NO_FALLBACK",
        "file_name_pattern": "{original_stem}_影界4K_{YYMMDD}.png",
        "collision_policy": "CREATE_UNIQUE_NO_OVERWRITE",
        "format": FOUR_K_V1_OUTPUT_FORMAT,
        "extension": ".png",
        "lossless_encoding": True,
        "super_resolution": {
            "engine": "realesrgan-ncnn-vulkan",
            "model": FOUR_K_V1_SR_MODEL,
            "native_scale": FOUR_K_V1_SR_SCALE,
            "to_target": "OpenCV.INTER_AREA_OR_CUBIC",
            "failure_policy": "FAIL_TASK_NO_LANCZOS_FALLBACK",
        },
        "fidelity_fusion": {
            "version": "v4",
            "low_frequency_source": "Pillow.Image.Resampling.LANCZOS(original)",
            "chroma_source": "Pillow.Image.Resampling.LANCZOS(original)+CHROMA_FOLLOW_AT_COLOUR_EDGES",
            "band_sigmas_source_px": [FOUR_K_V1_FINE_SIGMA, FOUR_K_V1_MID_SIGMA, FOUR_K_V1_STRUCT_SIGMA],
            "mid_sr_follow": FOUR_K_V1_MID_SR_FOLLOW,
            "mid_sr_cap": FOUR_K_V1_MID_SR_CAP,
            "mid_gain": FOUR_K_V1_MID_GAIN,
            "struct_gain": FOUR_K_V1_STRUCT_GAIN,
            "fine_gain": FOUR_K_V1_FINE_GAIN,
            "skin_fine_damp": FOUR_K_V1_SKIN_FINE_DAMP,
            "halo_clamp": FOUR_K_V1_HALO_CLAMP,
            "tiny_stroke_source": "LANCZOS_BASE_ONLY",
            "tiny_stroke_sharpen": FOUR_K_V1_STROKE_SHARPEN,
            "back_projection_sigma_source_px": FOUR_K_V1_BACK_PROJECTION_SIGMA,
            "back_projection_iterations": FOUR_K_V1_BACK_PROJECTION_ITERATIONS,
            "chroma_follow_sigma_source_px": FOUR_K_V1_CHROMA_FOLLOW_SIGMA,
            "chroma_follow_gate": {
                "chroma_std": list(FOUR_K_V1_CHROMA_FOLLOW_STD_RANGE),
                "luma_chroma_r2": list(FOUR_K_V1_CHROMA_FOLLOW_R2_RANGE),
            },
        },
        "text_enhancement": {
            "detector": "PP-OCRv3 Chinese text detection (opencv/text_detection_ppocr, ONNX Runtime CPU)",
            "model_file": FOUR_K_V1_TEXT_MODEL_RELATIVE.as_posix(),
            "model_sha256": FOUR_K_V1_TEXT_MODEL_SHA256,
            "model_license": "Apache-2.0",
            "luma_source_in_text": "SR_CLAMPED_TO_LOCAL_LANCZOS_RANGE_WITH_STROKE_AREA_GUARD",
            "range_radius_source_px": FOUR_K_V1_TEXT_RANGE_RADIUS,
            "stroke_guard_deviation": list(FOUR_K_V1_TEXT_GUARD_DEVIATION),
            "max_kernel_thickness_source_px": FOUR_K_V1_TEXT_MAX_KERNEL_THICK,
            "outside_text": "IDENTICAL_TO_V4",
            "detector_unavailable_policy": "V4_RESULT_WITH_REPORT_WARNING",
        },
        "input_normalization": {
            "high_bit_depth_gray": "SCALE_16BIT_TO_8BIT",
            "non_rgb_icc": "CONVERT_TO_SRGB_EMBED_SRGB",
            "transparent_pixels": "HIDDEN_RGB_FILLED_FROM_VISIBLE_NEIGHBOURS",
        },
        "resample": "Pillow.Image.Resampling.LANCZOS",
        "preserve_icc_profile_when_present": True,
        "preserve_alpha_with_premultiplied_resize": True,
        "success_gates": [
            "OUTPUT_EXISTS",
            "OUTPUT_DECODES",
            "OUTPUT_DIMENSIONS_MATCH_PLAN",
            "SOURCE_HASH_UNCHANGED",
        ],
    },
    "state_semantics": {
        "preflight_statuses": ["READY", "NO_PROCESSING_NEEDED", "BLOCKED"],
        "task_statuses": ["pending", "processing", "completed", "failed", "blocked"],
        "progress_range": [0, 100],
        "completed_requires": [
            "OUTPUT_EXISTS",
            "OUTPUT_DECODES",
            "OUTPUT_DIMENSIONS_MATCH_PLAN",
        ],
        "blocked_before_execution": [
            "FORMAL_DIRECTORY_NOT_READY",
            "SOURCE_NOT_ORIGINAL",
            "SOURCE_UNAVAILABLE",
            "UNSUPPORTED_OR_UNDECODABLE_IMAGE",
            "INVALID_4K_REQUEST",
        ],
        "failed_after_execution_started": [
            "SOURCE_READ_FAILED",
            "SR_ENGINE_UNAVAILABLE",
            "SR_ENGINE_FAILED",
            "RESIZE_FAILED",
            "OUTPUT_WRITE_FAILED",
            "OUTPUT_VERIFY_FAILED",
        ],
        "forbidden_success_fallbacks": [
            "PROJECT_TMP",
            "RUNTIME_DATA",
            "SOURCE_AS_RESULT",
            "STALE_OUTPUT",
        ],
    },
    "quality_semantics": {
        "allowed_conclusions": [
            "NOT_ASSESSED",
            FOUR_K_V1_COMPLETED_CONCLUSION,
            "NO_PROCESSING_NEEDED",
            "BLOCKED",
            "FAILED",
        ],
        "completed_conclusion": FOUR_K_V1_COMPLETED_CONCLUSION,
        "already_4k_conclusion": "NO_PROCESSING_NEEDED",
        "prohibited_claims": [
            "QUALITY_GAIN_PROVEN",
        ],
    },
    "single_image_loop_fields": {
        "upload_response": [
            "task_id",
            "task_status",
            "task_progress",
            "streamEndpoint",
            "originalUrl",
        ],
        "task": [
            "task_id",
            "task_status",
            "task_progress",
            "processing_stage",
            "processing_disposition",
            "mode",
            "route",
            "target_resolution",
            "original_filename",
            "input_hash",
            "input_width",
            "input_height",
            "target_width",
            "target_height",
            "output_width",
            "output_height",
            "output_format",
            "final_output_url",
            "final_output_exists",
            "quality_conclusion",
            "error_code",
            "error_message",
        ],
        "sse": [
            "task_id",
            "task_status",
            "task_progress",
            "processing_stage",
            "message",
            "error_code",
        ],
        "comparison": [
            "originalUrl",
            "final_output_url",
            "input_width",
            "input_height",
            "output_width",
            "output_height",
        ],
        "report": [
            "mode",
            "route",
            "quality_capability_boundary",
            "quality_conclusion",
            "input_width",
            "input_height",
            "output_width",
            "output_height",
            "output_format",
            "source_hash_unchanged",
            "warnings",
        ],
        "open_result": [
            "final_output_url",
            "final_output_exists",
            "output_directory_token",
        ],
        "backend_only": [
            "input_path",
            "expected_output_path",
            "output_path",
            "output_dir",
        ],
    },
    "frozen_evidence": {
        "stage1_standard": "artifacts/4k_stage1_baseline/4k_standard_v1.json",
        "stage1_baseline_selection": "artifacts/4k_stage1_baseline/results/baseline_selection.json",
        "stage2_negative_closure": "artifacts/4k_stage2_ai_poc/4K_STAGE_2_POC_VALUE_NOT_PROVEN_CLOSURE_REPORT.md",
        "route_b_product_adoption": "YES_PRODUCT_OWNER_DECISION_20261028",
    },
}


def get_4k_v1_contract() -> dict[str, Any]:
    """Return an isolated copy of the frozen 4K V1 product contract."""

    return copy.deepcopy(_FOUR_K_V1_CONTRACT)


def plan_4k_v1_dimensions(width: int, height: int) -> dict[str, Any]:
    """Plan the frozen long-edge 4K size treatment without touching image data."""

    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
    ):
        raise ValueError("INVALID_SOURCE_DIMENSIONS")

    source_long_edge = max(width, height)
    if source_long_edge >= FOUR_K_V1_TARGET_LONG_EDGE:
        return {
            "preflight_status": "NO_PROCESSING_NEEDED",
            "processing_disposition": "NO_PROCESSING_NEEDED",
            "input_width": width,
            "input_height": height,
            "target_width": width,
            "target_height": height,
            "scale": 1.0,
            "quality_conclusion": "NO_PROCESSING_NEEDED",
        }

    scale = FOUR_K_V1_TARGET_LONG_EDGE / source_long_edge
    target_width = max(1, int(math.floor(width * scale + 0.5)))
    target_height = max(1, int(math.floor(height * scale + 0.5)))
    return {
        "preflight_status": "READY",
        "processing_disposition": "UPSCALE_LONG_EDGE_TO_3840",
        "input_width": width,
        "input_height": height,
        "target_width": target_width,
        "target_height": target_height,
        "scale": scale,
        "quality_conclusion": "NOT_ASSESSED",
    }


class FourKV1ProcessingError(RuntimeError):
    """Structured failure raised by the frozen 4K V1 execution route."""

    def __init__(self, code: str, stage: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.hdde_failed_stage = stage


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _emit_stage(callback, stage: str, progress: int, message: str) -> None:
    if callback is not None:
        callback(stage, progress, message)


def _sr_tool_dir() -> Path:
    return resource_root() / "external_tools" / "realesrgan-ncnn-vulkan"


def _run_super_resolution(rgb: Image.Image, work_dir: Path, stage_callback=None) -> np.ndarray:
    """Run the bundled Real-ESRGAN model on an RGB image and return its native-scale result as uint8 RGB."""

    tool_dir = _sr_tool_dir()
    exe = tool_dir / "realesrgan-ncnn-vulkan.exe"
    model_files = [tool_dir / "models" / f"{FOUR_K_V1_SR_MODEL}{suffix}" for suffix in (".param", ".bin")]
    missing = [str(path) for path in (exe, *model_files) if not path.is_file()]
    if missing:
        raise FourKV1ProcessingError(
            "SR_ENGINE_UNAVAILABLE",
            "image_processing",
            f"4K超分引擎缺失，无法执行画质增强：{', '.join(missing)}",
        )

    token = uuid.uuid4().hex
    sr_input = work_dir / f".sr_in.{token}.png"
    sr_output = work_dir / f".sr_out.{token}.png"
    try:
        rgb.save(sr_input, format="PNG", compress_level=1)
        command = [
            str(exe), "-i", str(sr_input), "-o", str(sr_output),
            "-n", FOUR_K_V1_SR_MODEL, "-s", str(FOUR_K_V1_SR_SCALE), "-f", "png",
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        tail: list[str] = []
        last_reported = -1
        timed_out = threading.Event()
        try:
            process = subprocess.Popen(
                command,
                cwd=str(tool_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
        except OSError as exc:
            raise FourKV1ProcessingError("SR_ENGINE_UNAVAILABLE", "image_processing", f"4K超分引擎无法启动：{exc}") from exc
        # Reading stdout blocks until the engine closes it, so the deadline is enforced by a
        # watchdog that kills the process; a hung engine would otherwise block forever.
        def expire() -> None:
            timed_out.set()
            process.kill()

        watchdog = threading.Timer(FOUR_K_V1_SR_TIMEOUT_SECONDS, expire)
        watchdog.daemon = True
        watchdog.start()
        try:
            assert process.stdout is not None
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                tail = (tail + [line])[-8:]
                match = re.fullmatch(r"(\d+(?:\.\d+)?)%", line)
                if match:
                    # Map SR progress onto the 45–75 band of the task progress.
                    progress = 45 + int(float(match.group(1)) * 0.30)
                    if progress >= last_reported + 3:
                        last_reported = progress
                        _emit_stage(stage_callback, "image_processing", progress, f"正在进行4K超分细节重建（{match.group(1)}%）")
            returncode = process.wait()
        finally:
            watchdog.cancel()
            if process.poll() is None:  # leaving on an exception: never orphan the engine
                process.kill()
                process.wait()
            process.stdout.close()
        if timed_out.is_set():
            raise FourKV1ProcessingError(
                "SR_ENGINE_FAILED",
                "image_processing",
                f"4K超分引擎超时（{FOUR_K_V1_SR_TIMEOUT_SECONDS}s），已停止。",
            )
        if returncode != 0 or not sr_output.is_file():
            raise FourKV1ProcessingError(
                "SR_ENGINE_FAILED",
                "image_processing",
                f"4K超分引擎执行失败（exit={returncode}）：{' | '.join(tail) or '无输出'}",
            )
        with Image.open(sr_output) as produced:
            result = np.asarray(produced.convert("RGB"))
        expected = (rgb.height * FOUR_K_V1_SR_SCALE, rgb.width * FOUR_K_V1_SR_SCALE)
        if result.shape[:2] != expected:
            raise FourKV1ProcessingError(
                "SR_ENGINE_FAILED",
                "image_processing",
                f"4K超分结果尺寸异常：{result.shape[1]}x{result.shape[0]}，预期{expected[1]}x{expected[0]}。",
            )
        return result
    finally:
        sr_input.unlink(missing_ok=True)
        sr_output.unlink(missing_ok=True)


def _luma(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_RGB2YCrCb)[..., 0]


def _ramp(values: np.ndarray, bounds: tuple[float, float]) -> np.ndarray:
    low, high = bounds
    return np.clip((values - low) / (high - low), 0.0, 1.0)


def _structure_maps(rgb: Image.Image, target_size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Measure on the source where it is textured, where hard contours and where tiny strokes are."""

    luma = _luma(np.asarray(rgb, dtype=np.float32) / 255.0)
    upscale = lambda values: cv2.resize(values, target_size, interpolation=cv2.INTER_LINEAR)
    k3 = np.ones((3, 3), np.uint8)
    mean = cv2.blur(luma, (5, 5))
    std = np.sqrt(np.clip(cv2.blur(luma * luma, (5, 5)) - mean * mean, 0.0, None))
    texture = upscale(_ramp(std, FOUR_K_V1_FLAT_STD_RANGE))
    edge = _ramp(upscale(cv2.dilate(luma, k3) - cv2.erode(luma, k3)), FOUR_K_V1_EDGE_RANGE)
    k5 = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    hat = np.maximum(cv2.morphologyEx(luma, cv2.MORPH_BLACKHAT, k5), cv2.morphologyEx(luma, cv2.MORPH_TOPHAT, k5))
    strong = (hat > FOUR_K_V1_STROKE_HAT).astype(np.float32)
    stroke = cv2.morphologyEx(strong, cv2.MORPH_CLOSE, k3) * _ramp(cv2.blur(strong, (7, 7)), FOUR_K_V1_STROKE_DENSITY_RANGE)
    stroke = upscale(cv2.GaussianBlur(cv2.dilate(stroke, k3), (0, 0), 1.0))
    return texture, edge, stroke


def _blur(values: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(values, (0, 0), sigma)


def _skin_mask(ycc: np.ndarray) -> np.ndarray:
    cr = ycc[..., 1] * 255.0
    cb = ycc[..., 2] * 255.0
    mask = _ramp(cr, (133, 140)) * (1.0 - _ramp(cr, (170, 178))) * _ramp(cb, (80, 87)) * (1.0 - _ramp(cb, (128, 135)))
    return _blur(mask.astype(np.float32), 3.0)


def _fuse_detail(
    sr_native: np.ndarray,
    rgb: Image.Image,
    target_size: tuple[int, int],
    maps: tuple[np.ndarray, np.ndarray, np.ndarray],
    text_gate: np.ndarray | None = None,
) -> np.ndarray:
    """Fuse SR luminance detail onto the LANCZOS base of the original; returns uint8 RGB at target size."""

    texture, _edge, stroke = maps
    scale = target_size[0] / rgb.width
    fine_sigma = FOUR_K_V1_FINE_SIGMA * scale
    mid_sigma = FOUR_K_V1_MID_SIGMA * scale
    struct_sigma = FOUR_K_V1_STRUCT_SIGMA * scale
    base = cv2.cvtColor(
        np.asarray(rgb.resize(target_size, Image.Resampling.LANCZOS), dtype=np.float32) / 255.0,
        cv2.COLOR_RGB2YCrCb,
    )
    shrink = sr_native.shape[1] >= target_size[0]
    sr_luma = _luma(
        cv2.resize(sr_native, target_size, interpolation=cv2.INTER_AREA if shrink else cv2.INTER_CUBIC).astype(np.float32)
        / 255.0
    )
    base_luma = base[..., 0].copy()
    skin = _skin_mask(base)
    keep = 1.0 - stroke

    base_fine, base_mid = _blur(base_luma, fine_sigma), _blur(base_luma, mid_sigma)
    sr_fine, sr_mid = _blur(sr_luma, fine_sigma), _blur(sr_luma, mid_sigma)
    base_struct = _blur(base_luma, struct_sigma)
    mid_base = base_fine - base_mid
    cap = np.sqrt(_blur(mid_base * mid_base, struct_sigma)) * FOUR_K_V1_MID_SR_CAP + 1e-4
    delta = cap * np.tanh(((sr_fine - sr_mid) - mid_base) / cap)
    mid = mid_base + FOUR_K_V1_MID_SR_FOLLOW * keep * (1.0 - 0.5 * skin) * delta
    mid *= 1.0 + (FOUR_K_V1_MID_GAIN - 1.0) * (FOUR_K_V1_MID_FLAT_SHARE + (1.0 - FOUR_K_V1_MID_FLAT_SHARE) * texture) * keep
    struct = (base_mid - base_struct) * (1.0 + (FOUR_K_V1_STRUCT_GAIN - 1.0) * keep)
    envelope = np.sqrt(_blur(mid_base * mid_base, mid_sigma)) + 1e-4
    fine = envelope * np.tanh((sr_luma - sr_fine) / envelope)
    fine *= (
        FOUR_K_V1_FINE_GAIN
        * (FOUR_K_V1_FINE_FLAT_SHARE + (1.0 - FOUR_K_V1_FINE_FLAT_SHARE) * texture)
        * (1.0 - FOUR_K_V1_SKIN_FINE_DAMP * skin)
        * keep
    )
    fine += FOUR_K_V1_SKIN_SOURCE_FINE * skin * keep * (base_luma - base_fine)
    luma = base_struct + struct + mid + fine
    del mid_base, cap, delta, mid, struct, envelope, fine, base_fine, base_mid, sr_fine, sr_mid, base_struct, skin

    k5 = np.ones((5, 5), np.uint8)
    strokes = np.clip(
        base_luma + FOUR_K_V1_STROKE_SHARPEN * (base_luma - _blur(base_luma, FOUR_K_V1_STROKE_SHARPEN_SIGMA * scale)),
        cv2.erode(base_luma, k5),
        cv2.dilate(base_luma, k5),
    )
    luma = stroke * strokes + keep * luma
    del strokes
    # Halo clamp: stay within the local range of the base and the SR.
    luma = np.clip(
        luma,
        np.minimum(cv2.erode(base_luma, k5), cv2.erode(sr_luma, k5)) - FOUR_K_V1_HALO_CLAMP,
        np.maximum(cv2.dilate(base_luma, k5), cv2.dilate(sr_luma, k5)) + FOUR_K_V1_HALO_CLAMP,
    )
    luma = np.clip(_back_project(luma, rgb), 0.0, 1.0)
    if text_gate is not None:
        luma = _sharpen_text(luma, sr_luma, base_luma, text_gate, scale)
    del sr_luma
    _chroma_follow(base, base_luma, luma, scale)
    base[..., 0] = luma
    return (np.clip(cv2.cvtColor(base, cv2.COLOR_YCrCb2RGB), 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def _sharpen_text(
    luma: np.ndarray, sr_luma: np.ndarray, base_luma: np.ndarray, gate: np.ndarray, scale: float
) -> np.ndarray:
    """Inside detected text, take the SR luminance within the local base range and stroke-area guard."""

    size = int(2 * round(FOUR_K_V1_TEXT_RANGE_RADIUS * scale) + 1)
    kernel = np.ones((size, size), np.uint8)
    low, high = cv2.erode(base_luma, kernel), cv2.dilate(base_luma, kernel)
    candidate = np.clip(sr_luma, low, high)
    mid = (low + high) / 2.0
    dark_ink = _blur(base_luma, FOUR_K_V1_TEXT_GUARD_SIGMA * scale) > mid
    ink_base = np.where(dark_ink, base_luma < mid, base_luma > mid).astype(np.float32)
    ink_sr = np.where(dark_ink, candidate < mid, candidate > mid).astype(np.float32)
    sigma = FOUR_K_V1_TEXT_GUARD_SIGMA * scale
    area_base, area_sr = _blur(ink_base, sigma), _blur(ink_sr, sigma)
    deviation = np.abs(area_sr - area_base) / np.maximum(area_base, 0.05)
    trust = 1.0 - _ramp(deviation, FOUR_K_V1_TEXT_GUARD_DEVIATION)
    return luma + gate * trust * (candidate - luma)


_TEXT_DETECTOR: Any = None


def _text_detector() -> tuple[Any, str]:
    """Return (ONNX session, "") or (None, reason); the model must match the recorded SHA-256."""

    global _TEXT_DETECTOR
    if _TEXT_DETECTOR is not None:
        return _TEXT_DETECTOR, ""
    model = resource_root() / FOUR_K_V1_TEXT_MODEL_RELATIVE
    if not model.is_file():
        return None, f"文字检测模型缺失：{model}"
    if _sha256_file(model) != FOUR_K_V1_TEXT_MODEL_SHA256:
        return None, f"文字检测模型校验不一致：{model}"
    try:
        import onnxruntime as ort

        _TEXT_DETECTOR = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    except Exception as exc:  # runtime missing or model unreadable: v4 result, reported
        return None, f"文字检测模型无法加载：{exc}"
    return _TEXT_DETECTOR, ""


def _detect_text_gate(rgb: Image.Image, target_size: tuple[int, int]) -> tuple[np.ndarray | None, dict[str, Any]]:
    """Text mask at target size from the detector's probability map, or None with the reason."""

    session, reason = _text_detector()
    if session is None:
        return None, {"status": "DETECTOR_UNAVAILABLE", "reason": reason}
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
        probability = cv2.resize(np.asarray(output, np.float32).reshape(det_h, det_w), (width, height))
    except Exception as exc:
        return None, {"status": "DETECTOR_UNAVAILABLE", "reason": f"文字检测执行失败：{exc}"}

    kernels = (probability > FOUR_K_V1_TEXT_PROB_THRESHOLD).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(kernels, 8)
    gate = np.zeros((height, width), np.float32)
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        thickness = max(1, min(w, h))
        if area < 6 or thickness > FOUR_K_V1_TEXT_MAX_KERNEL_THICK:
            continue
        grow = max(1, int(round(0.5 * thickness)))  # detector kernels are shrunk text boxes
        x0, y0 = max(0, x - grow), max(0, y - grow)
        x1, y1 = min(width, x + w + grow), min(height, y + h + grow)
        region = (labels[y0:y1, x0:x1] == index).astype(np.uint8)
        region = cv2.dilate(region, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
        gate[y0:y1, x0:x1] = np.maximum(gate[y0:y1, x0:x1], region)
    if not gate.any():
        return None, {"status": "NO_TEXT_FOUND"}
    gate = np.clip(cv2.resize(_blur(gate, 1.0), target_size, interpolation=cv2.INTER_LINEAR), 0.0, 1.0)
    return gate, {"status": "APPLIED", "text_area_percent": round(float((gate > 0).mean() * 100), 2)}


def _chroma_follow(base: np.ndarray, base_luma: np.ndarray, luma: np.ndarray, scale: float) -> None:
    """Move the LANCZOS chroma (in place) with the luma sharpening at clear two-colour edges."""

    sigma = FOUR_K_V1_CHROMA_FOLLOW_SIGMA * scale
    size = int(2 * round(sigma) + 1)
    kernel = np.ones((size, size), np.uint8)
    mean_y = _blur(base_luma, sigma)
    var_y = _blur(base_luma * base_luma, sigma) - mean_y * mean_y + 1e-5
    sharpening = luma - base_luma
    for channel in (1, 2):
        chroma = base[..., channel]
        mean_c = _blur(chroma, sigma)
        cov = _blur(base_luma * chroma, sigma) - mean_y * mean_c
        var_c = np.clip(_blur(chroma * chroma, sigma) - mean_c * mean_c, 0.0, None)
        gate = _ramp(np.sqrt(var_c), FOUR_K_V1_CHROMA_FOLLOW_STD_RANGE) * _ramp(
            cov * cov / (var_y * (var_c + 1e-6)), FOUR_K_V1_CHROMA_FOLLOW_R2_RANGE
        )
        followed = chroma + gate * (cov / var_y) * sharpening
        base[..., channel] = np.clip(followed, cv2.erode(chroma, kernel), cv2.dilate(chroma, kernel))


def _back_project(luma: np.ndarray, rgb: Image.Image) -> np.ndarray:
    """Lock the low band of the fused luminance to the original (no tone drift)."""

    source = _luma(np.asarray(rgb, dtype=np.float32) / 255.0)
    source_size = (rgb.width, rgb.height)
    target_size = (luma.shape[1], luma.shape[0])
    for _ in range(FOUR_K_V1_BACK_PROJECTION_ITERATIONS):
        residual = _blur(source - cv2.resize(luma, source_size, interpolation=cv2.INTER_AREA), FOUR_K_V1_BACK_PROJECTION_SIGMA)
        luma = luma + cv2.resize(residual, target_size, interpolation=cv2.INTER_LINEAR)
    return luma


def _to_8bit_display(image: Image.Image) -> Image.Image:
    """16-bit / 32-bit gray would be clipped to white by Pillow's convert; scale it instead."""

    if image.mode.startswith("I;16") or image.mode in {"I", "F"}:
        values = np.asarray(image, dtype=np.float64)
        if image.mode == "F":
            peak = 1.0 if values.size and float(np.nanmax(values)) <= 1.0 else 65535.0
        else:
            peak = 255.0 if values.size and float(values.max()) <= 255 else 65535.0
        return Image.fromarray((np.clip(np.nan_to_num(values) / peak, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8))
    return image


def _working_rgb(image: Image.Image, icc_profile: object) -> tuple[Image.Image, bytes | None]:
    """RGB pixels to process and the ICC profile to embed in the PNG.

    A CMYK or gray ICC profile cannot describe RGB pixels, so such images are converted to
    sRGB through their own profile and tagged sRGB; RGB profiles are kept as they are.
    """

    image = _to_8bit_display(image)
    icc = icc_profile if isinstance(icc_profile, bytes) and icc_profile else None
    color = image.convert("CMYK" if image.mode == "CMYK" else ("L" if image.mode in {"L", "LA"} else "RGB"))
    if icc is not None:
        try:
            profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            space = str(profile.profile.xcolor_space).strip().upper()
        except Exception:
            profile, space = None, ""
        if profile is not None and space in {"CMYK", "GRAY"} and color.mode in {"CMYK", "L"}:
            srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
            converted = ImageCms.profileToProfile(
                color, profile, srgb, renderingIntent=ImageCms.Intent.PERCEPTUAL, outputMode="RGB"
            )
            return converted, srgb.tobytes()
        if space and space != "RGB":
            icc = None  # Unusable for RGB pixels; an untagged PNG reads as sRGB.
    return color.convert("RGB"), icc


def _fill_transparent_rgb(rgb: Image.Image, alpha: Image.Image) -> Image.Image:
    """Replace the colour hidden under fully transparent pixels by the nearby visible colour.

    Exports often store black (or junk) there; SR and sharpening would treat the boundary
    between subject and that hidden colour as a real edge and draw rims along the cutout.
    """

    weight = (np.asarray(alpha, dtype=np.float32) > 0).astype(np.float32)
    if weight.all() or not weight.any():
        return rgb
    color = np.asarray(rgb, dtype=np.float32)
    levels = [(color * weight[..., None], weight)]
    while min(levels[-1][1].shape) > 1:
        c, w = levels[-1]
        size = (max(1, w.shape[1] // 2), max(1, w.shape[0] // 2))
        levels.append((cv2.resize(c, size, interpolation=cv2.INTER_AREA), cv2.resize(w, size, interpolation=cv2.INTER_AREA)))
    c, w = levels[-1]
    filled = c / np.maximum(w, 1e-6)[..., None]
    for c, w in reversed(levels[:-1]):
        coarse = cv2.resize(filled, (w.shape[1], w.shape[0]), interpolation=cv2.INTER_LINEAR)
        share = np.clip(w, 0.0, 1.0)[..., None]
        filled = np.where(share > 0, c / np.maximum(w, 1e-6)[..., None] * share + coarse * (1.0 - share), coarse)
    filled = np.where(weight[..., None] > 0, color, filled)
    return Image.fromarray(np.clip(filled + 0.5, 0, 255).astype(np.uint8), "RGB")


def build_4k_v1_output_path(
    source_path: str | Path,
    formal_root: str | Path,
    *,
    timestamp: datetime | None = None,
    short_id: str | None = None,
    trusted_original_filename: str | Path | None = None,
) -> Path:
    """Build a unique formal output path from the frozen output contract."""

    source = Path(source_path)
    root = Path(formal_root).expanduser().resolve()
    output_dir = (root / Path(FOUR_K_V1_OUTPUT_DIRECTORY)).resolve()
    if output_dir != root and root not in output_dir.parents:
        raise FourKV1ProcessingError("FORMAL_DIRECTORY_NOT_READY", "contract_validation", "4K输出目录超出正式目录。")

    del short_id  # Compatibility-only input; internal IDs are forbidden in final names.
    return build_output_path(
        output_dir,
        source.name,
        FEATURE_4K,
        ".png",
        trusted_original_filename=trusted_original_filename,
        moment=timestamp,
    )


def inspect_4k_v1_source(source_path: str | Path) -> dict[str, Any]:
    """Read only the uploaded source and return contract facts."""

    source = Path(source_path)
    if not source.is_file():
        raise FourKV1ProcessingError("SOURCE_UNAVAILABLE", "contract_validation", "找不到待处理的原始图片。")
    try:
        source_hash = _sha256_file(source)
        with Image.open(source) as opened:
            source_format = str(opened.format or source.suffix.lstrip(".") or "UNKNOWN").upper()
            has_alpha = "A" in opened.getbands() or "transparency" in opened.info
            icc_profile = opened.info.get("icc_profile")
            display_image = ImageOps.exif_transpose(opened)
            display_image.load()
            width, height = display_image.size
    except FourKV1ProcessingError:
        raise
    except Exception as exc:
        raise FourKV1ProcessingError(
            "UNSUPPORTED_OR_UNDECODABLE_IMAGE",
            "contract_validation",
            f"图片无法解码：{exc}",
        ) from exc

    plan = plan_4k_v1_dimensions(width, height)
    return {
        **plan,
        "input_hash": source_hash,
        "input_format": source_format,
        "has_alpha": bool(has_alpha),
        "icc_profile_present": isinstance(icc_profile, bytes) and bool(icc_profile),
    }


def process_4k_v1_image(
    source_path: str | Path,
    formal_root: str | Path,
    *,
    output_path: str | Path | None = None,
    stage_callback=None,
) -> dict[str, Any]:
    """Execute the 4K route: Real-ESRGAN detail reconstruction with source-fidelity fusion."""

    source = Path(source_path)
    root = Path(formal_root).expanduser().resolve()
    _emit_stage(stage_callback, "contract_validation", 20, "正在核对4K处理合同与原图信息")
    source_meta = inspect_4k_v1_source(source)
    destination = Path(output_path) if output_path else build_4k_v1_output_path(source, root)
    destination = destination.expanduser().resolve()
    expected_root = (root / Path(FOUR_K_V1_OUTPUT_DIRECTORY)).resolve()
    if destination.parent != expected_root:
        raise FourKV1ProcessingError("INVALID_4K_REQUEST", "contract_validation", "4K成品必须写入正式4K输出目录。")

    common = {
        "mode": FOUR_K_V1_MODE,
        "route": FOUR_K_V1_ROUTE,
        "output_profile": FOUR_K_V1_OUTPUT_PROFILE,
        "target_resolution": FOUR_K_V1_TARGET_RESOLUTION,
        "quality_capability_boundary": FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY,
        "input_hash": source_meta["input_hash"],
        "input_width": source_meta["input_width"],
        "input_height": source_meta["input_height"],
        "input_format": source_meta["input_format"],
        "has_alpha": source_meta["has_alpha"],
        "target_width": source_meta["target_width"],
        "target_height": source_meta["target_height"],
        "processing_disposition": source_meta["processing_disposition"],
        "resize_policy": source_meta["processing_disposition"],
        "output_format": FOUR_K_V1_OUTPUT_FORMAT,
    }

    if source_meta["processing_disposition"] == "NO_PROCESSING_NEEDED":
        _emit_stage(stage_callback, "output_verify", 100, "原图长边已达到4K门槛，无需重复放大")
        report = {
            **common,
            "quality_conclusion": "NO_PROCESSING_NEEDED",
            "source_hash_unchanged": _sha256_file(source) == source_meta["input_hash"],
            "warnings": ["原图长边已达到3840像素，未执行像素放大。"],
        }
        return {
            **common,
            "task_result": {
                **common,
                "output_width": source_meta["input_width"],
                "output_height": source_meta["input_height"],
                "final_output_exists": False,
                "final_output_url": "",
                "quality_conclusion": "NO_PROCESSING_NEEDED",
            },
            "task_report": report,
            "quality_conclusion": "NO_PROCESSING_NEEDED",
            "source_hash_unchanged": report["source_hash_unchanged"],
            "final_output_path": "",
            "final_output_exists": False,
        }

    temp_path: Path | None = None
    text_enhancement: dict[str, Any] = {"status": "NOT_RUN"}
    try:
        _emit_stage(stage_callback, "image_processing", 45, "正在进行4K超分细节重建")
        # Same authority as the metadata writer that verifies the result: Pillow reports a
        # made-up 72 dpi for a JPEG whose EXIF has no resolution, which then fails that check.
        source_dpi = _read_effective_dpi(source.read_bytes())
        with Image.open(source) as opened:
            icc_profile = opened.info.get("icc_profile")
            image = ImageOps.exif_transpose(opened)
            image.load()
        target_size = (source_meta["target_width"], source_meta["target_height"])
        rgb, icc_profile = _working_rgb(image, icc_profile)
        alpha = None
        if source_meta["has_alpha"]:
            alpha = _to_8bit_display(image).convert("RGBA").getchannel("A")
            rgb = _fill_transparent_rgb(rgb, alpha)
        destination.parent.mkdir(parents=True, exist_ok=True)
        sr_native = _run_super_resolution(rgb, destination.parent, stage_callback)
        _emit_stage(stage_callback, "image_processing", 78, "正在进行原图保真融合与细节校准")
        maps = _structure_maps(rgb, target_size)
        text_gate, text_enhancement = _detect_text_gate(rgb, target_size)
        resized = Image.fromarray(_fuse_detail(sr_native, rgb, target_size, maps, text_gate), "RGB")
        del text_gate
        del sr_native
        if alpha is not None:
            # Alpha is never generated by SR; it is upscaled with LANCZOS from the original.
            resized.putalpha(alpha.resize(target_size, Image.Resampling.LANCZOS))

        _emit_stage(stage_callback, "output_file_write", 84, "正在写入正式4K成品")
        temp_path = destination.with_name(f".{destination.stem}.{uuid.uuid4().hex}.tmp.png")
        save_options: dict[str, Any] = {"format": "PNG", "compress_level": 6}
        if isinstance(icc_profile, bytes) and icc_profile:
            save_options["icc_profile"] = icc_profile
        if source_dpi is not None:
            save_options["dpi"] = source_dpi
        resized.save(temp_path, **save_options)
    except FourKV1ProcessingError:
        raise
    except OSError as exc:
        raise FourKV1ProcessingError("OUTPUT_WRITE_FAILED", "output_file_write", f"4K成品写入失败：{exc}") from exc
    except Exception as exc:
        raise FourKV1ProcessingError("RESIZE_FAILED", "image_processing", f"4K画质增强失败：{exc}") from exc
    collision_base = destination
    collision_match = re.fullmatch(r"(.+_影界4K_\d{6})(?:_\d{2})?(\.png)", destination.name)
    if collision_match:
        collision_base = destination.with_name(f"{collision_match.group(1)}{collision_match.group(2)}")
    source_hash_unchanged = _sha256_file(source) == source_meta["input_hash"]
    if not source_hash_unchanged:
        temp_path.unlink(missing_ok=True)
        raise FourKV1ProcessingError("SOURCE_HASH_CHANGED", "output_verify", "原图完整性校验失败，已停止发布4K成品。")

    def verify_private_output(data: bytes) -> tuple[int, int]:
        with Image.open(io.BytesIO(data)) as output_image:
            output_image.load()
            dimensions = output_image.size
        if dimensions != (source_meta["target_width"], source_meta["target_height"]):
            raise ValueError("OUTPUT_DIMENSIONS_MISMATCH")
        return dimensions

    try:
        destination, metadata_report, verified_dimensions = publish_image_file_with_metadata(
            temp_path,
            destination,
            source_path=source,
            normalize_orientation=True,
            collision_base_path=collision_base,
            verify_private=verify_private_output,
        )
    except OutputMetadataStageError as exc:
        raise FourKV1ProcessingError(
            "OUTPUT_METADATA_FAILED",
            "output_metadata_write",
            f"4K成品元数据写入失败：{exc}",
        ) from exc
    except Exception as exc:
        raise FourKV1ProcessingError(
            "OUTPUT_WRITE_FAILED",
            "output_file_write",
            f"4K成品排他发布失败：{exc}",
        ) from exc
    finally:
        temp_path.unlink(missing_ok=True)

    _emit_stage(stage_callback, "output_verify", 90, "正在核对成品文件与像素尺寸")
    output_width, output_height = verified_dimensions
    output_sha256 = str((metadata_report.get("publish_integrity") or {}).get("committed_sha256") or "")
    if not output_sha256:
        raise FourKV1ProcessingError(
            "OUTPUT_IDENTITY_MISSING",
            "output_verify",
            "4K成品缺少正式发布身份，已停止登记结果。",
        )

    _emit_stage(stage_callback, "completed", 100, "4K画质增强完成")
    task_result = {
        **common,
        "output_filename": destination.name,
        "output_path": str(destination),
        "final_output_path": str(destination),
        "output_width": output_width,
        "output_height": output_height,
        "output_size": destination.stat().st_size,
        "output_sha256": output_sha256,
        "final_output_exists": True,
        "quality_conclusion": FOUR_K_V1_COMPLETED_CONCLUSION,
        "source_hash_unchanged": source_hash_unchanged,
        "output_metadata": metadata_report,
        "text_enhancement": text_enhancement,
    }
    task_report = {
        **common,
        "output_width": output_width,
        "output_height": output_height,
        "quality_conclusion": FOUR_K_V1_COMPLETED_CONCLUSION,
        "source_hash_unchanged": source_hash_unchanged,
        "text_enhancement": text_enhancement,
        "warnings": [
            "保持原图比例与构图，长边提升至3840像素：Real-ESRGAN x4超分重建细节后，以原图低频保真融合，防止色偏、重绘与过锐光晕。",
            *(
                ["文字检测模型不可用，本次未做文字清晰度加强，其余处理照常完成。"]
                if text_enhancement.get("status") == "DETECTOR_UNAVAILABLE"
                else []
            ),
        ],
    }
    return {
        **common,
        "task_result": task_result,
        "task_report": task_report,
        "quality_conclusion": FOUR_K_V1_COMPLETED_CONCLUSION,
        "source_hash_unchanged": source_hash_unchanged,
        "final_output_path": str(destination),
        "final_output_exists": True,
        "output_width": output_width,
        "output_height": output_height,
        "output_format": FOUR_K_V1_OUTPUT_FORMAT,
    }


__all__ = [
    "FOUR_K_V1_COMPLETED_CONCLUSION",
    "FOUR_K_V1_CONTRACT_VERSION",
    "FOUR_K_V1_MODE",
    "FOUR_K_V1_OUTPUT_DIRECTORY",
    "FOUR_K_V1_OUTPUT_FORMAT",
    "FOUR_K_V1_OUTPUT_PROFILE",
    "FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY",
    "FOUR_K_V1_ROUTE",
    "FOUR_K_V1_TARGET_LONG_EDGE",
    "FOUR_K_V1_TARGET_RESOLUTION",
    "FourKV1ProcessingError",
    "build_4k_v1_output_path",
    "get_4k_v1_contract",
    "inspect_4k_v1_source",
    "plan_4k_v1_dimensions",
    "process_4k_v1_image",
]
