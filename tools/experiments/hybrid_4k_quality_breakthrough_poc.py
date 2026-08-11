from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "output"
GOLDEN_MANIFEST = REPO_ROOT / "artifacts" / "4k_stage1_baseline" / "golden_samples_manifest.json"
ROI_MANIFEST = REPO_ROOT / "artifacts" / "4k_stage1_baseline" / "comparisons" / "comparison_manifest.json"
GOLDEN_SNAPSHOTS = REPO_ROOT / "artifacts" / "4k_stage1_baseline" / "golden_samples"
SETTINGS_PATH = REPO_ROOT / "settings" / "settings.json"
FROZEN_ROOTS = (
    REPO_ROOT / "artifacts" / "4k_stage1_baseline",
    REPO_ROOT / "artifacts" / "4k_stage2_ai_poc",
)
WAIFU_ROOT = (
    REPO_ROOT
    / "output"
    / "4k_quality_poc_20260730_093959"
    / "runtime"
    / "waifu2x"
    / "waifu2x-ncnn-vulkan-20250915-windows"
)
WAIFU_EXE = WAIFU_ROOT / "waifu2x-ncnn-vulkan.exe"
TARGET_LONG_EDGE = 3840
MODEL_SCALE = 2
MODEL_TILE = 128
ROUTE_ORDER = ("PHOTO_BALANCED", "CUNET_DEPTH")
VISUAL_PENDING = "PENDING_HUMAN_VISUAL_REVIEW"


@dataclass(frozen=True)
class RouteConfig:
    model_dir: str
    generic_weight: float
    texture_weight: float
    protected_cap: float
    luma_delta_limit: int
    microcontrast_gain: float


ROUTES = {
    "PHOTO_BALANCED": RouteConfig(
        model_dir="models-upconv_7_photo",
        generic_weight=0.40,
        texture_weight=0.55,
        protected_cap=0.10,
        luma_delta_limit=8,
        microcontrast_gain=0.12,
    ),
    "CUNET_DEPTH": RouteConfig(
        model_dir="models-cunet",
        generic_weight=0.50,
        texture_weight=0.70,
        protected_cap=0.10,
        luma_delta_limit=12,
        microcontrast_gain=0.18,
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def round_half_up(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def target_dimensions(width: int, height: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise ValueError("INVALID_SOURCE_DIMENSIONS")
    if width >= height:
        return TARGET_LONG_EDGE, max(1, round_half_up(height * TARGET_LONG_EDGE / width))
    return max(1, round_half_up(width * TARGET_LONG_EDGE / height)), TARGET_LONG_EDGE


def ensure_isolated_output(path: Path) -> Path:
    resolved = path.resolve(strict=False)
    output_resolved = OUTPUT_ROOT.resolve(strict=False)
    if resolved.parent != output_resolved:
        raise ValueError("POC_OUTPUT_MUST_BE_DIRECT_CHILD_OF_REPO_OUTPUT")
    if not resolved.name.startswith("4k_quality_breakthrough_"):
        raise ValueError("POC_OUTPUT_NAME_MUST_BE_UNIQUE_BREAKTHROUGH_PREFIX")
    if resolved.exists():
        raise FileExistsError(f"POC_OUTPUT_ALREADY_EXISTS:{resolved}")
    return resolved


def new_output_path() -> Path:
    return OUTPUT_ROOT / f"4k_quality_breakthrough_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def file_record(path: Path, relative_to: Path | None = None) -> dict[str, Any]:
    with Image.open(path) as image:
        image.load()
        record = {
            "path": str(path.relative_to(relative_to) if relative_to else path),
            "file_name": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": sha256(path),
            "format": image.format,
            "mode": image.mode,
            "width": image.width,
            "height": image.height,
            "decodable": True,
            "icc_sha256": hashlib.sha256(image.info.get("icc_profile", b"")).hexdigest()
            if image.info.get("icc_profile")
            else None,
        }
    return record


def generic_file_record(path: Path, relative_to: Path | None = None) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(relative_to) if relative_to else path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def tree_fingerprint(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {"root": str(root), "exists": False}
    digest = hashlib.sha256()
    count = 0
    size = 0
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        file_hash = sha256(path)
        stat = path.stat()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
        count += 1
        size += stat.st_size
    return {
        "root": str(root),
        "exists": True,
        "file_count": count,
        "size_bytes": size,
        "aggregate_sha256": digest.hexdigest(),
    }


def settings_fingerprint() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {"path": str(SETTINGS_PATH), "exists": False}
    stat = SETTINGS_PATH.stat()
    return {
        "path": str(SETTINGS_PATH),
        "exists": True,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256(SETTINGS_PATH),
    }


def formal_root_from_settings() -> Path | None:
    if not SETTINGS_PATH.exists():
        return None
    data = json_read(SETTINGS_PATH)
    value = data.get("app_data_root") or data.get("workdir") or data.get("root_dir")
    return Path(value) if isinstance(value, str) and value.strip() else None


def safety_snapshot() -> dict[str, Any]:
    formal_root = formal_root_from_settings()
    return {
        "settings": settings_fingerprint(),
        "formal_root": tree_fingerprint(formal_root) if formal_root else {"root": None, "exists": False},
        "frozen_roots": [tree_fingerprint(path) for path in FROZEN_ROOTS],
    }


def load_source(path: Path) -> tuple[Image.Image, bytes | None, int | None]:
    with Image.open(path) as opened:
        orientation = opened.getexif().get(274)
        icc_profile = opened.info.get("icc_profile")
        image = ImageOps.exif_transpose(opened)
        image.load()
    mode = "RGBA" if "A" in image.getbands() else "RGB"
    return image.convert(mode), icc_profile, orientation


def resize_rgba_premultiplied(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.float32)
    alpha = rgba[:, :, 3:4] / 255.0
    premultiplied = np.concatenate((rgba[:, :, :3] * alpha, rgba[:, :, 3:4]), axis=2).astype(np.uint8)
    resized = np.asarray(Image.fromarray(premultiplied, "RGBA").resize(size, Image.Resampling.LANCZOS), dtype=np.float32)
    target_alpha = resized[:, :, 3:4]
    rgb = np.zeros_like(resized[:, :, :3])
    np.divide(
        resized[:, :, :3] * 255.0,
        target_alpha,
        out=rgb,
        where=target_alpha > 0,
    )
    result = np.concatenate((np.clip(rgb, 0, 255), target_alpha), axis=2).astype(np.uint8)
    return Image.fromarray(result, "RGBA")


def lanczos_baseline(image: Image.Image, target: tuple[int, int]) -> Image.Image:
    if "A" in image.getbands():
        return resize_rgba_premultiplied(image, target)
    return image.convert("RGB").resize(target, Image.Resampling.LANCZOS)


def save_png(image: Image.Image, path: Path, icc_profile: bytes | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {"format": "PNG", "compress_level": 6}
    if icc_profile:
        kwargs["icc_profile"] = icc_profile
    image.save(path, **kwargs)


def runtime_preflight() -> dict[str, Any]:
    required = [WAIFU_EXE]
    for route in ROUTES.values():
        model_root = WAIFU_ROOT / route.model_dir
        required.extend((model_root / "scale2.0x_model.bin", model_root / "scale2.0x_model.param"))
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("MISSING_WAIFU_RUNTIME:" + ";".join(missing))
    return {
        "runtime": "waifu2x-ncnn-vulkan-20250915-windows",
        "runtime_path": str(WAIFU_EXE),
        "runtime_sha256": sha256(WAIFU_EXE),
        "official_source": "https://github.com/nihui/waifu2x-ncnn-vulkan",
        "license": "MIT",
        "hardware_api": "Vulkan",
        "model_files": {
            name: [generic_file_record(path) for path in sorted((WAIFU_ROOT / config.model_dir).glob("scale2.0x_model.*"))]
            for name, config in ROUTES.items()
        },
    }


def waifu_command(source: Path, destination: Path, config: RouteConfig) -> list[str]:
    return [
        str(WAIFU_EXE),
        "-i",
        str(source),
        "-o",
        str(destination),
        "-n",
        "-1",
        "-s",
        str(MODEL_SCALE),
        "-t",
        str(MODEL_TILE),
        "-m",
        str(WAIFU_ROOT / config.model_dir),
        "-g",
        "0",
        "-j",
        "1:2:1",
        "-f",
        "png",
        "-v",
    ]


def run_waifu(source: Path, destination: Path, config: RouteConfig) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = waifu_command(source, destination, config)
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=WAIFU_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    elapsed = time.perf_counter() - started
    record = {
        "command": command,
        "exit_code": completed.returncode,
        "inference_seconds": round(elapsed, 3),
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-4000:],
        "output_exists": destination.exists(),
    }
    if completed.returncode != 0 or not destination.exists():
        raise RuntimeError("WAIFU2X_FAILED:" + json.dumps(record, ensure_ascii=False))
    return record


def _mask_ratio(mask: np.ndarray) -> float:
    return round(float(np.mean(mask > 0)), 6)


def _proxy_image(rgb: np.ndarray, max_edge: int = 1600) -> tuple[np.ndarray, float]:
    height, width = rgb.shape[:2]
    scale = min(1.0, max_edge / max(height, width))
    if scale == 1.0:
        return rgb, scale
    return cv2.resize(rgb, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA), scale


def build_protection_masks(baseline_rgb: np.ndarray, alpha: np.ndarray | None) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    proxy, scale = _proxy_image(baseline_rgb)
    gray = cv2.cvtColor(proxy, cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(proxy, cv2.COLOR_RGB2HSV)
    ycrcb = cv2.cvtColor(proxy, cv2.COLOR_RGB2YCrCb)
    edges = cv2.Canny(gray, 65, 165)
    adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        8,
    )
    text_like = cv2.bitwise_and(adaptive, cv2.dilate(edges, np.ones((3, 3), np.uint8)))
    text_like = cv2.dilate(text_like, np.ones((5, 5), np.uint8), iterations=1)
    high_contrast = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    _, saturation, value = cv2.split(hsv)
    skin = (
        (ycrcb[:, :, 1] > 132)
        & (ycrcb[:, :, 1] < 178)
        & (ycrcb[:, :, 2] > 84)
        & (ycrcb[:, :, 2] < 138)
        & (saturation > 20)
        & (value > 75)
    ).astype(np.uint8) * 255
    skin = cv2.morphologyEx(skin, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=1)
    brand = ((saturation > 105) & (value > 70)).astype(np.uint8) * 255
    brand = cv2.dilate(brand, np.ones((5, 5), np.uint8), iterations=1)

    local_mean = cv2.GaussianBlur(gray.astype(np.float32), (0, 0), 5.0)
    local_sq = cv2.GaussianBlur(gray.astype(np.float32) ** 2, (0, 0), 5.0)
    variance = np.maximum(0.0, local_sq - local_mean**2)
    gradient = cv2.magnitude(
        cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3),
        cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3),
    )
    smooth_gradient = ((variance < 55.0) & (gradient < 22.0)).astype(np.uint8) * 255
    detail = np.abs(cv2.Laplacian(gray, cv2.CV_32F, ksize=3))
    threshold = max(8.0, float(np.percentile(detail, 72)))
    texture = ((detail >= threshold) & (variance >= 35.0)).astype(np.uint8) * 255

    faces = np.zeros_like(gray, dtype=np.uint8)
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(cascade_path))
    face_boxes: list[list[int]] = []
    if not detector.empty():
        for x, y, width, height in detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(48, 48)):
            pad = round(max(width, height) * 0.16)
            x0, y0 = max(0, x - pad), max(0, y - pad)
            x1, y1 = min(gray.shape[1], x + width + pad), min(gray.shape[0], y + height + pad)
            faces[y0:y1, x0:x1] = 255
            face_boxes.append([int(x0), int(y0), int(x1), int(y1)])
    if not face_boxes and np.mean(skin > 0) > 0.025:
        faces = cv2.dilate(skin, np.ones((31, 31), np.uint8), iterations=1)
        face_mode = "CONSERVATIVE_SKIN_CONTEXT_FALLBACK"
    else:
        face_mode = "HAAR_FACE_BOXES" if face_boxes else "NO_FACE_SIGNAL"

    target_size = (baseline_rgb.shape[1], baseline_rgb.shape[0])
    proxy_masks = {
        "text_logo": text_like,
        "high_contrast": high_contrast,
        "face": faces,
        "skin": skin,
        "brand": brand,
        "smooth_gradient": smooth_gradient,
        "texture": texture,
    }
    masks = {
        name: cv2.resize(mask, target_size, interpolation=cv2.INTER_NEAREST)
        for name, mask in proxy_masks.items()
    }
    if alpha is None:
        masks["alpha_edge"] = np.zeros(target_size[::-1], dtype=np.uint8)
    else:
        alpha_edges = cv2.Canny(alpha, 1, 254)
        semi = ((alpha > 0) & (alpha < 255)).astype(np.uint8) * 255
        masks["alpha_edge"] = cv2.dilate(cv2.bitwise_or(alpha_edges, semi), np.ones((9, 9), np.uint8), iterations=1)

    hard = np.zeros_like(masks["text_logo"])
    for name in ("text_logo", "high_contrast", "face", "alpha_edge"):
        hard = cv2.bitwise_or(hard, masks[name])
    masks["hard_protect"] = hard
    metadata = {
        "source": "MINIMAL_REUSE_OF_EXISTING_1080P_PROTECTION_HEURISTICS",
        "proxy_scale": round(scale, 6),
        "face_detection_mode": face_mode,
        "face_boxes_proxy": face_boxes,
        "ratios": {name: _mask_ratio(mask) for name, mask in masks.items()},
        "semantic_limit": "HEURISTIC_MASKS_DO_NOT_PROVE_TEXT_LOGO_FACE_OR_BRAND_SAFETY",
    }
    return masks, metadata


def blend_weights(masks: dict[str, np.ndarray], config: RouteConfig) -> np.ndarray:
    weights = np.full(masks["hard_protect"].shape, config.generic_weight, dtype=np.float32)
    weights[masks["texture"] > 0] = config.texture_weight
    capped = (
        (masks["skin"] > 0)
        | (masks["smooth_gradient"] > 0)
        | (masks["brand"] > 0)
    )
    weights[capped] = np.minimum(weights[capped], config.protected_cap)
    weights = cv2.GaussianBlur(weights, (0, 0), 1.1)
    # Feathering must never raise a protected pixel above its explicit cap.
    weights[capped] = np.minimum(weights[capped], config.protected_cap)
    weights[masks["hard_protect"] > 0] = 0.0
    return np.clip(weights, 0.0, config.texture_weight)


def fuse_luminance(
    baseline: Image.Image,
    model_exact: Image.Image,
    config: RouteConfig,
) -> tuple[Image.Image, dict[str, Any], dict[str, np.ndarray]]:
    baseline_rgba = np.asarray(baseline.convert("RGBA"), dtype=np.uint8)
    baseline_rgb = baseline_rgba[:, :, :3]
    alpha = baseline_rgba[:, :, 3] if "A" in baseline.getbands() else None
    model_rgb = np.asarray(model_exact.convert("RGB"), dtype=np.uint8)
    masks, mask_metadata = build_protection_masks(baseline_rgb, alpha)
    weights = blend_weights(masks, config)

    base_ycc = cv2.cvtColor(baseline_rgb, cv2.COLOR_RGB2YCrCb)
    model_ycc = cv2.cvtColor(model_rgb, cv2.COLOR_RGB2YCrCb)
    base_y = base_ycc[:, :, 0].astype(np.float32)
    residual = model_ycc[:, :, 0].astype(np.float32) - base_y
    local_mean = cv2.GaussianBlur(base_y, (0, 0), 3.0)
    local_detail = base_y - local_mean
    midtone = np.clip(np.minimum((base_y - 16.0) / 32.0, (239.0 - base_y) / 32.0), 0.0, 1.0)
    combined_delta = (residual + local_detail * config.microcontrast_gain) * weights * midtone
    combined_delta = np.clip(combined_delta, -config.luma_delta_limit, config.luma_delta_limit)
    combined_delta[masks["hard_protect"] > 0] = 0.0

    candidate_ycc = base_ycc.copy()
    candidate_ycc[:, :, 0] = np.clip(np.rint(base_y + combined_delta), 0, 255).astype(np.uint8)
    candidate_rgb = cv2.cvtColor(candidate_ycc, cv2.COLOR_YCrCb2RGB)
    candidate_rgb[masks["hard_protect"] > 0] = baseline_rgb[masks["hard_protect"] > 0]

    encoded_ycc = cv2.cvtColor(candidate_rgb, cv2.COLOR_RGB2YCrCb)
    encoded_luma_delta = encoded_ycc[:, :, 0].astype(np.int16) - base_ycc[:, :, 0].astype(np.int16)
    chroma_delta = np.max(
        np.abs(encoded_ycc[:, :, 1:].astype(np.int16) - base_ycc[:, :, 1:].astype(np.int16)),
        axis=2,
    )
    unsafe = (np.abs(encoded_luma_delta) > config.luma_delta_limit) | (chroma_delta > 1)
    candidate_rgb[unsafe] = baseline_rgb[unsafe]

    final_ycc = cv2.cvtColor(candidate_rgb, cv2.COLOR_RGB2YCrCb)
    final_luma_delta = final_ycc[:, :, 0].astype(np.int16) - base_ycc[:, :, 0].astype(np.int16)
    final_chroma_delta = np.abs(final_ycc[:, :, 1:].astype(np.int16) - base_ycc[:, :, 1:].astype(np.int16))
    hard_changed = np.any(candidate_rgb[masks["hard_protect"] > 0] != baseline_rgb[masks["hard_protect"] > 0], axis=1)
    result_array = (
        np.dstack((candidate_rgb, baseline_rgba[:, :, 3]))
        if "A" in baseline.getbands()
        else candidate_rgb
    )
    result = Image.fromarray(result_array, "RGBA" if result_array.shape[2] == 4 else "RGB")
    metrics = {
        "configured_generic_weight": config.generic_weight,
        "configured_texture_weight": config.texture_weight,
        "configured_protected_cap": config.protected_cap,
        "configured_luma_delta_limit": config.luma_delta_limit,
        "actual_weight_min": round(float(weights.min()), 6),
        "actual_weight_max": round(float(weights.max()), 6),
        "actual_weight_mean": round(float(weights.mean()), 6),
        "actual_max_abs_luma_delta": int(np.max(np.abs(final_luma_delta))),
        "actual_mean_abs_luma_delta": round(float(np.mean(np.abs(final_luma_delta))), 6),
        "actual_max_abs_chroma_delta": int(final_chroma_delta.max()),
        "actual_mean_abs_chroma_delta": round(float(final_chroma_delta.mean()), 6),
        "hard_protected_changed_pixels": int(hard_changed.sum()),
        "overflow_restored_pixels": int(unsafe.sum()),
        "baseline_clipped_pixels": int(np.sum((base_ycc[:, :, 0] == 0) | (base_ycc[:, :, 0] == 255))),
        "candidate_clipped_pixels": int(np.sum((final_ycc[:, :, 0] == 0) | (final_ycc[:, :, 0] == 255))),
        "mask_evidence": mask_metadata,
    }
    return result, metrics, masks


def alpha_metrics(baseline: Image.Image, candidate: Image.Image, hard_mask: np.ndarray) -> dict[str, Any]:
    if "A" not in baseline.getbands():
        return {"status": "NOT_APPLICABLE", "has_alpha": False}
    base = np.asarray(baseline.convert("RGBA"), dtype=np.uint8)
    cand = np.asarray(candidate.convert("RGBA"), dtype=np.uint8)
    alpha_delta = np.abs(base[:, :, 3].astype(np.int16) - cand[:, :, 3].astype(np.int16))
    semi = (base[:, :, 3] > 0) & (base[:, :, 3] < 255)
    protected_rgb_delta = np.abs(base[:, :, :3].astype(np.int16) - cand[:, :, :3].astype(np.int16))
    protected = hard_mask > 0
    return {
        "status": "PASS"
        if int(alpha_delta.max()) == 0 and int(protected_rgb_delta[protected].max(initial=0)) == 0
        else "FAIL",
        "has_alpha": True,
        "semi_transparent_pixels": int(semi.sum()),
        "alpha_changed_pixels": int(np.sum(alpha_delta > 0)),
        "max_alpha_delta": int(alpha_delta.max()),
        "protected_rgb_changed_pixels": int(np.sum(np.any(protected_rgb_delta > 0, axis=2) & protected)),
        "black_white_composite_required": True,
    }


def tile_seam_metrics(model_master: Image.Image, model_input: Image.Image) -> dict[str, Any]:
    master_rgb = np.asarray(model_master.convert("RGB"), dtype=np.uint8)
    reference = np.asarray(model_input.convert("RGB").resize(model_master.size, Image.Resampling.LANCZOS), dtype=np.uint8)
    master_y = cv2.cvtColor(master_rgb, cv2.COLOR_RGB2YCrCb)[:, :, 0].astype(np.float32)
    ref_y = cv2.cvtColor(reference, cv2.COLOR_RGB2YCrCb)[:, :, 0].astype(np.float32)
    residual = master_y - ref_y
    boundary = MODEL_TILE * MODEL_SCALE
    seam_values: list[float] = []
    neighbor_values: list[float] = []
    for x in range(boundary, residual.shape[1], boundary):
        seam_values.append(float(np.mean(np.abs(residual[:, x] - residual[:, x - 1]))))
        if x + 4 < residual.shape[1]:
            neighbor_values.append(float(np.mean(np.abs(residual[:, x + 4] - residual[:, x + 3]))))
    for y in range(boundary, residual.shape[0], boundary):
        seam_values.append(float(np.mean(np.abs(residual[y] - residual[y - 1]))))
        if y + 4 < residual.shape[0]:
            neighbor_values.append(float(np.mean(np.abs(residual[y + 4] - residual[y + 3]))))
    if not seam_values or not neighbor_values:
        return {"status": "REVIEW", "reason": "NO_MEASURABLE_INTERNAL_TILE_BOUNDARY"}
    seam_p95 = float(np.percentile(seam_values, 95))
    neighbor_p95 = float(np.percentile(neighbor_values, 95))
    ratio = seam_p95 / max(neighbor_p95, 0.01)
    return {
        "status": "PASS" if ratio <= 2.0 and seam_p95 <= 5.0 else "REVIEW",
        "evidence_source": "MODEL_RESIDUAL_DISCONTINUITY_AT_KNOWN_128PX_X2_TILE_BOUNDARIES",
        "tile_size_input_pixels": MODEL_TILE,
        "seam_count": len(seam_values),
        "seam_p95": round(seam_p95, 6),
        "neighbor_p95": round(neighbor_p95, 6),
        "seam_to_neighbor_ratio": round(ratio, 6),
        "human_visible_seam_status": VISUAL_PENDING,
    }


def technical_gates(
    source_before_hash: str,
    source_path: Path,
    source_size: tuple[int, int],
    target: tuple[int, int],
    model_master: Image.Image,
    model_input: Image.Image,
    baseline_path: Path,
    candidate_path: Path,
    runtime: dict[str, Any],
    fusion: dict[str, Any],
    alpha: dict[str, Any],
    operation_trace: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_record = file_record(baseline_path)
    candidate = file_record(candidate_path)
    source_after_hash = sha256(source_path)
    source_ratio = source_size[0] / source_size[1]
    output_ratio = candidate["width"] / candidate["height"]
    geometry_pass = (
        (candidate["width"], candidate["height"]) == target
        and max(target) == TARGET_LONG_EDGE
        and abs(output_ratio - source_ratio) <= 1.0 / min(target)
        and [event["operation"] for event in operation_trace]
        == ["exif_transpose", "lanczos_resize", "waifu2x_x2", "lanczos_exact_resize", "luminance_only_blend", "png_encode_decode"]
        and not any(event.get("crop") or event.get("pad") or event.get("stretch") for event in operation_trace)
    )
    seam = tile_seam_metrics(model_master, model_input)
    clipping_growth = fusion["candidate_clipped_pixels"] - fusion["baseline_clipped_pixels"]
    gate_values = {
        "source_hash_unchanged": "PASS" if source_before_hash == source_after_hash else "FAIL",
        "process_exit": "PASS" if runtime["exit_code"] == 0 else "FAIL",
        "decode": "PASS" if candidate["decodable"] else "FAIL",
        "geometry": "PASS" if geometry_pass else "FAIL",
        "icc_preservation": "PASS"
        if candidate["icc_sha256"] == baseline_record["icc_sha256"]
        else "FAIL",
        "alpha_preservation": alpha["status"],
        "mask_boundary": "PASS" if fusion["hard_protected_changed_pixels"] == 0 else "FAIL",
        "color_drift": "PASS" if fusion["actual_max_abs_chroma_delta"] <= 1 else "FAIL",
        "luma_limit": "PASS"
        if fusion["actual_max_abs_luma_delta"] <= fusion["configured_luma_delta_limit"]
        else "FAIL",
        "luma_clipping": "PASS" if clipping_growth <= 0 else "REVIEW",
        "tile_seam_precheck": seam["status"],
        "output_path_isolation": "PASS"
        if candidate_path.resolve().is_relative_to(OUTPUT_ROOT.resolve())
        else "FAIL",
        "performance": "PASS" if runtime["inference_seconds"] <= 60.0 else "FAIL",
    }
    blocking = [name for name, status in gate_values.items() if status == "FAIL"]
    review = [name for name, status in gate_values.items() if status == "REVIEW"]
    return {
        "status": "PASS" if not blocking and not review else ("FAIL" if blocking else "REVIEW_REQUIRED"),
        "gates": gate_values,
        "blocking_gates": blocking,
        "review_required_gates": review,
        "source_sha256_before": source_before_hash,
        "source_sha256_after": source_after_hash,
        "geometry_evidence": {
            "source_dimensions": list(source_size),
            "target_dimensions_formula": "long edge=3840; other edge=ROUND_HALF_UP(source_other*3840/source_long)",
            "expected_dimensions": list(target),
            "actual_dimensions": [candidate["width"], candidate["height"]],
            "source_aspect_ratio": source_ratio,
            "output_aspect_ratio": output_ratio,
            "aspect_ratio_absolute_error": abs(output_ratio - source_ratio),
            "operation_trace": operation_trace,
        },
        "tile_seam_evidence": seam,
        "clipping_growth_pixels": clipping_growth,
        "candidate": candidate,
    }


def blind_order(batch_id: str, sample_id: str) -> list[str]:
    values = ["LANCZOS", *ROUTE_ORDER]
    seed = int(hashlib.sha256(f"{batch_id}:{sample_id}:blind-v1".encode()).hexdigest()[:16], 16)
    random.Random(seed).shuffle(values)
    return values


def fitted_panel(image: Image.Image, size: tuple[int, int], label: str) -> Image.Image:
    width, height = size
    canvas = Image.new("RGB", size, (22, 25, 31))
    content = ImageOps.contain(image.convert("RGB"), (width - 20, height - 56), Image.Resampling.LANCZOS)
    canvas.paste(content, ((width - content.width) // 2, 46 + (height - 56 - content.height) // 2))
    draw = ImageDraw.Draw(canvas)
    draw.text((14, 14), label, fill=(235, 239, 246), font=ImageFont.load_default())
    return canvas


def native_512_panel(image: Image.Image, label: str) -> Image.Image:
    if image.size != (512, 512):
        raise ValueError(f"NATIVE_ROI_MUST_BE_512X512:{image.size}")
    canvas = Image.new("RGB", (512, 548), (22, 25, 31))
    canvas.paste(image.convert("RGB"), (0, 36))
    ImageDraw.Draw(canvas).text((10, 12), label, fill=(235, 239, 246), font=ImageFont.load_default())
    return canvas


def horizontal_contact_sheet(panels: list[Image.Image]) -> Image.Image:
    width = sum(panel.width for panel in panels)
    height = max(panel.height for panel in panels)
    result = Image.new("RGB", (width, height), (16, 18, 22))
    x = 0
    for panel in panels:
        result.paste(panel, (x, 0))
        x += panel.width
    return result


def crop_box_from_normalized(box: dict[str, float], size: tuple[int, int]) -> tuple[int, int, int, int]:
    width, height = size
    return (
        max(0, min(width - 1, round_half_up(box["x0"] * width))),
        max(0, min(height - 1, round_half_up(box["y0"] * height))),
        max(1, min(width, round_half_up(box["x1"] * width))),
        max(1, min(height, round_half_up(box["y1"] * height))),
    )


def build_review_package(
    batch_root: Path,
    batch_id: str,
    samples: list[dict[str, Any]],
    rois: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    package = batch_root / "review_package"
    full_dir = package / "blind" / "full"
    roi_dir = package / "blind" / "roi"
    full_dir.mkdir(parents=True, exist_ok=True)
    roi_dir.mkdir(parents=True, exist_ok=True)
    by_key = {(record["sample_id"], record["route"]): Path(record["candidate_path"]) for record in records}
    baseline_by_sample = {record["sample_id"]: Path(record["baseline_path"]) for record in records if record["route"] == ROUTE_ORDER[0]}
    source_by_sample = {record["sample_id"]: Path(record["source_copy_path"]) for record in records if record["route"] == ROUTE_ORDER[0]}
    mappings: dict[str, Any] = {}
    full_entries: list[dict[str, Any]] = []
    roi_entries: list[dict[str, Any]] = []
    for sample in samples:
        sample_id = sample["sample_id"]
        order = blind_order(batch_id, sample_id)
        aliases = {f"OPTION_{chr(65 + index)}": route for index, route in enumerate(order)}
        mappings[sample_id] = aliases
        source_image = Image.open(source_by_sample[sample_id])
        option_images = {
            "LANCZOS": Image.open(baseline_by_sample[sample_id]),
            **{route: Image.open(by_key[(sample_id, route)]) for route in ROUTE_ORDER},
        }
        panels = [fitted_panel(source_image, (480, 1080), "ORIGINAL")]
        for index, route in enumerate(order):
            panels.append(fitted_panel(option_images[route], (480, 1080), f"OPTION {chr(65 + index)}"))
        full_path = full_dir / f"{sample_id}__blind_full_1920x1080.png"
        horizontal_contact_sheet(panels).save(full_path, format="PNG", compress_level=6)
        full_entries.append(
            {
                "sample_id": sample_id,
                "path": str(full_path.relative_to(batch_root)),
                "status": VISUAL_PENDING,
                "selected_option": None,
                "clearly_better_than_lanczos": None,
                "structure_regression": None,
                "notes": None,
            }
        )
        for image in option_images.values():
            image.close()
        source_image.close()

    roi_counts: dict[str, int] = {}
    for roi in rois:
        sample_id = roi["sample_id"]
        roi_counts[sample_id] = roi_counts.get(sample_id, 0) + 1
        roi_number = roi_counts[sample_id]
        source_image = Image.open(source_by_sample[sample_id])
        baseline = Image.open(baseline_by_sample[sample_id])
        candidates = {route: Image.open(by_key[(sample_id, route)]) for route in ROUTE_ORDER}
        target_box = tuple(roi["candidate_native_100_percent"]["pillow_lanczos"]["pixel_box"][key] for key in ("x0", "y0", "x1", "y1"))
        source_box = crop_box_from_normalized(roi["normalized_box"], source_image.size)
        source_crop = source_image.crop(source_box).resize((512, 512), Image.Resampling.LANCZOS)
        options = {"LANCZOS": baseline.crop(target_box), **{route: image.crop(target_box) for route, image in candidates.items()}}
        order = blind_order(batch_id, sample_id)
        panels = [native_512_panel(source_crop, "ORIGINAL MAPPED")]
        for index, route in enumerate(order):
            panels.append(native_512_panel(options[route], f"OPTION {chr(65 + index)}"))
        roi_path = roi_dir / f"{sample_id}__R{roi_number:02d}__blind_roi.png"
        horizontal_contact_sheet(panels).save(roi_path, format="PNG", compress_level=6)
        roi_entries.append(
            {
                "sample_id": sample_id,
                "roi_id": f"R{roi_number:02d}",
                "risk": roi["risk"],
                "path": str(roi_path.relative_to(batch_root)),
                "source_normalized_box": roi["normalized_box"],
                "candidate_native_pixel_box": dict(zip(("x0", "y0", "x1", "y1"), target_box)),
                "mapping_policy": "SAME_NORMALIZED_SOURCE_REGION_AND_EXACT_512PX_TARGET_CROP",
                "status": VISUAL_PENDING,
                "selected_option": None,
                "clearly_better_than_lanczos": None,
                "structure_regression": None,
                "notes": None,
            }
        )
        source_image.close()
        baseline.close()
        for image in candidates.values():
            image.close()
    mapping_path = package / "blind_mapping_DO_NOT_OPEN_BEFORE_REVIEW.json"
    json_write(mapping_path, {"batch_id": batch_id, "mapping": mappings})
    checklist = {
        "status": VISUAL_PENDING,
        "success_gate": {
            "full_frames_clearly_better": "at least 6 of 8",
            "rois_clearly_better": "at least 10 of 14",
            "zero_regressions": ["Chinese text", "Logo", "face identity", "product contour", "brand color", "gradient", "alpha edge"],
            "accepted_gain": "real depth, material separation, clarity; not hardness, oversharpening, or contrast-only change",
        },
        "full_frames": full_entries,
        "rois": roi_entries,
    }
    json_write(package / "human_review_checklist.json", checklist)
    lines = [
        "# 4K真实画质突破PoC人工盲评清单",
        "",
        f"- 批次：`{batch_id}`",
        "- 当前状态：`PENDING_HUMAN_VISUAL_REVIEW`",
        "- 完整画面：至少6/8明确优于LANCZOS。",
        "- ROI：至少10/14明确优于LANCZOS。",
        "- 中文、Logo、脸部身份、产品轮廓、品牌色、渐变、透明边缘必须零退化。",
        "- 先填写选项与退化情况，再打开盲序映射。",
        "",
        "## 完整画面",
        "",
        "| 样本 | 盲评图 | 选择 | 明确优于LANCZOS | 结构退化 | 备注 |",
        "|---|---|---|---|---|---|",
    ]
    for entry in full_entries:
        lines.append(f"| {entry['sample_id']} | `{entry['path']}` |  |  |  |  |")
    lines.extend(["", "## 等区域100% ROI", "", "| 样本/ROI | 风险 | 盲评图 | 选择 | 明确优于LANCZOS | 结构退化 | 备注 |", "|---|---|---|---|---|---|---|"])
    for entry in roi_entries:
        lines.append(f"| {entry['sample_id']}/{entry['roi_id']} | {entry['risk']} | `{entry['path']}` |  |  |  |  |")
    (package / "human_review_checklist.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"package": package, "checklist": checklist, "mapping": mappings}


def build_alpha_composites(batch_root: Path, records: list[dict[str, Any]], rois: list[dict[str, Any]]) -> list[str]:
    alpha_roi = next((roi for roi in rois if roi["sample_id"] == "S08"), None)
    if not alpha_roi:
        return []
    target_box = tuple(alpha_roi["candidate_native_100_percent"]["pillow_lanczos"]["pixel_box"][key] for key in ("x0", "y0", "x1", "y1"))
    paths: list[str] = []
    sample_records = [record for record in records if record["sample_id"] == "S08"]
    if not sample_records:
        return []
    baseline_path = Path(sample_records[0]["baseline_path"])
    images = [("LANCZOS", Image.open(baseline_path).convert("RGBA"))]
    images.extend((record["route"], Image.open(record["candidate_path"]).convert("RGBA")) for record in sample_records)
    panels: list[Image.Image] = []
    for background_value, label in ((0, "BLACK"), (255, "WHITE")):
        for route, image in images:
            crop = image.crop(target_box)
            background = Image.new("RGBA", crop.size, (background_value, background_value, background_value, 255))
            composite = Image.alpha_composite(background, crop).convert("RGB")
            panels.append(fitted_panel(composite, (512, 568), f"{label} / {route}"))
    output = batch_root / "review_package" / "alpha" / "S08__black_white_composites.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    horizontal_contact_sheet(panels[:3]).save(output, format="PNG", compress_level=6)
    output2 = output.with_name("S08__white_composites.png")
    horizontal_contact_sheet(panels[3:]).save(output2, format="PNG", compress_level=6)
    for _, image in images:
        image.close()
    paths.extend((str(output.relative_to(batch_root)), str(output2.relative_to(batch_root))))
    return paths


def copy_source(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if sha256(source) != sha256(destination):
        raise RuntimeError("SOURCE_COPY_HASH_MISMATCH")


def process_sample(
    batch_root: Path,
    batch_id: str,
    sample: dict[str, Any],
    runtime_info: dict[str, Any],
) -> list[dict[str, Any]]:
    sample_id = sample["sample_id"]
    source = GOLDEN_SNAPSHOTS / sample["snapshot_file_name"]
    if not source.exists() or sha256(source) != sample["sha256"]:
        raise RuntimeError(f"FROZEN_GOLDEN_SAMPLE_MISMATCH:{sample_id}")
    source_before_hash = sha256(source)
    source_copy = batch_root / "review_package" / "originals" / source.name
    copy_source(source, source_copy)
    image, icc_profile, orientation = load_source(source)
    target = target_dimensions(*image.size)
    baseline = lanczos_baseline(image, target)
    baseline_path = batch_root / "review_package" / "lanczos" / f"{sample_id}__LANCZOS_4K.png"
    save_png(baseline, baseline_path, icc_profile)

    model_input = image.convert("RGB")
    model_input_path = batch_root / "work" / "inputs" / f"{sample_id}__model_input_rgb.png"
    save_png(model_input, model_input_path, icc_profile)
    records: list[dict[str, Any]] = []
    for route_name in ROUTE_ORDER:
        config = ROUTES[route_name]
        master_path = batch_root / "model_masters" / route_name / f"{sample_id}__{route_name}__x2_master.png"
        runtime = run_waifu(model_input_path, master_path, config)
        model_master = Image.open(master_path)
        model_master.load()
        expected_master = (model_input.width * MODEL_SCALE, model_input.height * MODEL_SCALE)
        if model_master.size != expected_master:
            raise RuntimeError(f"MODEL_SCALE_CONTRACT_BROKEN:{sample_id}:{route_name}:{model_master.size}")
        model_exact = model_master.convert("RGB").resize(target, Image.Resampling.LANCZOS)
        candidate, fusion_metrics, masks = fuse_luminance(baseline, model_exact, config)
        candidate_path = batch_root / "review_package" / "candidates" / route_name / f"{sample_id}__{route_name}__4K.png"
        save_png(candidate, candidate_path, icc_profile)
        alpha = alpha_metrics(baseline, candidate, masks["hard_protect"])
        trace = [
            {"operation": "exif_transpose", "applied": orientation not in (None, 1), "before": [sample["width"], sample["height"]], "after": list(image.size), "crop": False, "pad": False, "stretch": False},
            {"operation": "lanczos_resize", "applied": True, "before": list(image.size), "after": list(target), "crop": False, "pad": False, "stretch": False},
            {"operation": "waifu2x_x2", "applied": True, "before": list(model_input.size), "after": list(model_master.size), "crop": False, "pad": False, "stretch": False},
            {"operation": "lanczos_exact_resize", "applied": model_master.size != target, "before": list(model_master.size), "after": list(target), "crop": False, "pad": False, "stretch": False},
            {"operation": "luminance_only_blend", "applied": True, "before": list(target), "after": list(candidate.size), "crop": False, "pad": False, "stretch": False},
            {"operation": "png_encode_decode", "applied": True, "before": list(candidate.size), "after": [file_record(candidate_path)["width"], file_record(candidate_path)["height"]], "crop": False, "pad": False, "stretch": False},
        ]
        gates = technical_gates(
            source_before_hash,
            source,
            image.size,
            target,
            model_master,
            model_input,
            baseline_path,
            candidate_path,
            runtime,
            fusion_metrics,
            alpha,
            trace,
        )
        record = {
            "batch_id": batch_id,
            "sample_id": sample_id,
            "route": route_name,
            "route_config": asdict(config),
            "source_path": str(source),
            "source_copy_path": str(source_copy),
            "source_sha256": source_before_hash,
            "source_dimensions": list(image.size),
            "baseline_path": str(baseline_path),
            "baseline_sha256": sha256(baseline_path),
            "target_dimensions": list(target),
            "model_master_path": str(master_path),
            "model_master_sha256": sha256(master_path),
            "candidate_path": str(candidate_path),
            "candidate_sha256": sha256(candidate_path),
            "runtime": runtime,
            "runtime_identity": runtime_info["runtime"],
            "fusion_metrics": fusion_metrics,
            "alpha_metrics": alpha,
            "technical": gates,
            "TECHNICAL_STATUS": gates["status"],
            "STRUCTURE_SAFETY_STATUS": VISUAL_PENDING,
            "VISUAL_GAIN_STATUS": VISUAL_PENDING,
            "ROUTE_DECISION_STATUS": "PENDING_HUMAN_REVIEW",
            "fallback_rule": "FALLBACK_NO_PROVEN_GAIN",
            "fallback_applied": False,
            "fallback_reason": "NOT_EVALUATED_PENDING_HUMAN_REVIEW",
        }
        evidence_path = batch_root / "evidence" / route_name / f"{sample_id}__evidence.json"
        json_write(evidence_path, record)
        record["evidence_path"] = str(evidence_path)
        records.append(record)
        model_master.close()
    return records


def sha256_manifest(root: Path, excluded: Iterable[Path] = ()) -> list[dict[str, Any]]:
    excluded_resolved = {path.resolve() for path in excluded}
    return [
        generic_file_record(path, root)
        for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix())
        if path.resolve() not in excluded_resolved
    ]


def aggregate_status(records: list[dict[str, Any]], safety_unchanged: bool) -> dict[str, Any]:
    technical = [record["TECHNICAL_STATUS"] for record in records]
    return {
        "TECHNICAL_STATUS": "PASS" if technical and all(status == "PASS" for status in technical) else "BLOCKED",
        "STRUCTURE_SAFETY_STATUS": VISUAL_PENDING,
        "VISUAL_GAIN_STATUS": VISUAL_PENDING,
        "ROUTE_DECISION_STATUS": "PENDING_HUMAN_REVIEW",
        "PACKAGE_STATUS": "TECHNICAL_PACKAGE_DRAFT",
        "FORMAL_STATE_PROTECTION": "PASS" if safety_unchanged else "FAIL",
        "fallback_policy": "A route/sample without proven safe gain must use LANCZOS and record FALLBACK_NO_PROVEN_GAIN.",
        "value_claim": "NOT_MADE",
    }


def revalidate_existing(output: Path) -> dict[str, Any]:
    resolved = output.resolve(strict=True)
    if resolved.parent != OUTPUT_ROOT.resolve() or not resolved.name.startswith("4k_quality_breakthrough_"):
        raise ValueError("NOT_AN_ISOLATED_BREAKTHROUGH_OUTPUT")
    manifest_path = resolved / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("MISSING_EXISTING_POC_MANIFEST")
    manifest = json_read(manifest_path)
    records: list[dict[str, Any]] = []
    for evidence_path in sorted((resolved / "evidence").glob("*/*.json")):
        record = json_read(evidence_path)
        baseline_record = file_record(Path(record["baseline_path"]))
        candidate_record = file_record(Path(record["candidate_path"]))
        gates = record["technical"]["gates"]
        gates["icc_preservation"] = (
            "PASS" if candidate_record["icc_sha256"] == baseline_record["icc_sha256"] else "FAIL"
        )
        blocking = [name for name, status in gates.items() if status == "FAIL"]
        review = [name for name, status in gates.items() if status == "REVIEW"]
        technical_status = "PASS" if not blocking and not review else ("FAIL" if blocking else "REVIEW_REQUIRED")
        record["technical"]["status"] = technical_status
        record["technical"]["blocking_gates"] = blocking
        record["technical"]["review_required_gates"] = review
        record["technical"]["candidate"] = candidate_record
        record["TECHNICAL_STATUS"] = technical_status
        json_write(evidence_path, record)
        records.append(record)
    records.sort(key=lambda item: (item["sample_id"], ROUTE_ORDER.index(item["route"])))
    manifest["records"] = records
    manifest["status"] = aggregate_status(records, bool(manifest["safety"]["unchanged"]))
    manifest["evidence_revalidation"] = {
        "reason": "REPLACE_FIXED_ICC_PASS_WITH_REAL_BASELINE_VS_CANDIDATE_ICC_HASH_COMPARISON",
        "revalidated_at": datetime.now().astimezone().isoformat(),
        "model_rerun": False,
        "image_regeneration": False,
    }
    json_write(manifest_path, manifest)
    json_write(resolved / "execution_matrix.json", records)
    hash_path = resolved / "sha256_manifest.json"
    json_write(hash_path, {"excluded_self": str(hash_path.name), "files": sha256_manifest(resolved, [hash_path])})
    return manifest


def rebuild_existing_review_package(output: Path) -> dict[str, Any]:
    resolved = output.resolve(strict=True)
    if resolved.parent != OUTPUT_ROOT.resolve() or not resolved.name.startswith("4k_quality_breakthrough_"):
        raise ValueError("NOT_AN_ISOLATED_BREAKTHROUGH_OUTPUT")
    manifest_path = resolved / "manifest.json"
    manifest = json_read(manifest_path)
    golden = json_read(GOLDEN_MANIFEST)
    roi_manifest = json_read(ROI_MANIFEST)
    selected = set(manifest["samples"])
    samples = [sample for sample in golden["samples"] if sample["sample_id"] in selected]
    rois = [roi for roi in roi_manifest["comparisons"] if roi["sample_id"] in selected]
    review = build_review_package(resolved, manifest["batch_id"], samples, rois, manifest["records"])
    manifest["human_review"]["status"] = VISUAL_PENDING
    manifest["human_review"]["checklist"] = str(
        (review["package"] / "human_review_checklist.json").relative_to(resolved)
    )
    manifest["review_package_rebuild"] = {
        "reason": "RESTORE_EXACT_512X512_ONE_TO_ONE_CANDIDATE_ROI_PRESENTATION",
        "rebuilt_at": datetime.now().astimezone().isoformat(),
        "model_rerun": False,
        "candidate_image_regeneration": False,
        "review_panels_regenerated": True,
    }
    json_write(manifest_path, manifest)
    hash_path = resolved / "sha256_manifest.json"
    json_write(hash_path, {"excluded_self": str(hash_path.name), "files": sha256_manifest(resolved, [hash_path])})
    return manifest


def run(output: Path, sample_ids: set[str] | None = None) -> dict[str, Any]:
    output = ensure_isolated_output(output)
    runtime_info = runtime_preflight()
    golden = json_read(GOLDEN_MANIFEST)
    roi_manifest = json_read(ROI_MANIFEST)
    samples = [sample for sample in golden["samples"] if sample_ids is None or sample["sample_id"] in sample_ids]
    if not samples:
        raise ValueError("NO_GOLDEN_SAMPLES_SELECTED")
    expected = sample_ids or {sample["sample_id"] for sample in golden["samples"]}
    actual = {sample["sample_id"] for sample in samples}
    if actual != expected:
        raise ValueError(f"UNKNOWN_SAMPLE_IDS:{sorted(expected - actual)}")
    rois = [roi for roi in roi_manifest["comparisons"] if roi["sample_id"] in actual]
    output.mkdir(parents=True, exist_ok=False)
    batch_id = output.name
    before = safety_snapshot()
    source_hashes_before = {
        sample["sample_id"]: sha256(GOLDEN_SNAPSHOTS / sample["snapshot_file_name"])
        for sample in samples
    }
    records: list[dict[str, Any]] = []
    started = time.perf_counter()
    for sample in samples:
        print(f"[{sample['sample_id']}] processing", flush=True)
        records.extend(process_sample(output, batch_id, sample, runtime_info))
    review = build_review_package(output, batch_id, samples, rois, records)
    alpha_composites = build_alpha_composites(output, records, rois)
    after = safety_snapshot()
    source_hashes_after = {
        sample["sample_id"]: sha256(GOLDEN_SNAPSHOTS / sample["snapshot_file_name"])
        for sample in samples
    }
    safety_unchanged = before == after and source_hashes_before == source_hashes_after
    status = aggregate_status(records, safety_unchanged)
    manifest = {
        "manifest_version": "4K_QUALITY_BREAKTHROUGH_POC_V1",
        "batch_id": batch_id,
        "created_at": datetime.now().astimezone().isoformat(),
        "scope": "ISOLATED_POC_ONLY_NO_FORMAL_ROUTE_OR_API_CHANGE",
        "contract": "long edge 3840; direct from original; preserve aspect; no crop/stretch/pad",
        "runtime": runtime_info,
        "routes": {name: asdict(config) for name, config in ROUTES.items()},
        "samples": [sample["sample_id"] for sample in samples],
        "roi_count": len(rois),
        "execution_record_count": len(records),
        "execution_seconds": round(time.perf_counter() - started, 3),
        "status": status,
        "records": records,
        "alpha_composites": alpha_composites,
        "safety": {"before": before, "after": after, "unchanged": safety_unchanged},
        "source_hashes": {"before": source_hashes_before, "after": source_hashes_after},
        "human_review": {
            "status": VISUAL_PENDING,
            "checklist": str((review["package"] / "human_review_checklist.json").relative_to(output)),
            "blind_mapping": str((review["package"] / "blind_mapping_DO_NOT_OPEN_BEFORE_REVIEW.json").relative_to(output)),
        },
    }
    manifest_path = output / "manifest.json"
    json_write(manifest_path, manifest)
    matrix_path = output / "execution_matrix.json"
    json_write(matrix_path, records)
    readme = output / "review_package" / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# 4K真实画质突破PoC技术与人工盲评包",
                "",
                f"- 批次：`{batch_id}`",
                "- 正式4K路线：未修改；本目录为隔离PoC。",
                "- 输出合同：长边3840、保持比例、不裁切、不拉伸、不补边。",
                "- 路线：PHOTO_BALANCED与CUNET_DEPTH；均为waifu2x x2无降噪后，仅融合亮度细节残差。",
                "- 色度：来自LANCZOS基线；文字/高反差线/脸部/Alpha边缘为零权重保护。",
                "- 技术门禁来自真实文件、退出码、尺寸、像素和运行时间；不证明主观画质增益。",
                "- 结构安全与画质突破当前均为PENDING_HUMAN_VISUAL_REVIEW。",
                "- 先填写human_review_checklist，再打开blind_mapping_DO_NOT_OPEN_BEFORE_REVIEW.json。",
                "- 未证明安全增益的样本必须回退LANCZOS并记录FALLBACK_NO_PROVEN_GAIN。",
                "",
                "## 人工成功门禁",
                "",
                "完整画面至少6/8、ROI至少10/14明确优于LANCZOS，且中文、Logo、脸部身份、产品轮廓、品牌色、渐变和透明边缘零退化。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    hash_path = output / "sha256_manifest.json"
    json_write(hash_path, {"excluded_self": str(hash_path.name), "files": sha256_manifest(output, [hash_path])})
    return manifest


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Isolated 4K luminance-residual quality breakthrough PoC")
    parser.add_argument("--output", type=Path, default=None, help="Unique direct child of repo output/")
    parser.add_argument("--samples", nargs="*", default=None, help="Optional subset such as S01 S08")
    parser.add_argument("--revalidate-existing", action="store_true", help="Recompute evidence only; never rerun models")
    parser.add_argument("--rebuild-review-existing", action="store_true", help="Rebuild blind review panels only")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    output = args.output or new_output_path()
    try:
        if args.revalidate_existing and args.rebuild_review_existing:
            raise ValueError("CHOOSE_ONE_EXISTING_PACKAGE_OPERATION")
        if args.revalidate_existing:
            manifest = revalidate_existing(output)
        elif args.rebuild_review_existing:
            manifest = rebuild_existing_review_package(output)
        else:
            manifest = run(output, set(args.samples) if args.samples else None)
    except Exception as exc:
        print(f"POC_FAILED:{type(exc).__name__}:{exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output": str(output), "status": manifest["status"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
