from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from engine.algorithms.color_fidelity import lock_color_to_reference
from engine.algorithms.edge_halo_control import phase3_edge_halo_control, phase3_edge_policy
from engine.algorithms.edge_safe_enhance import enhance_true_edges
from engine.algorithms.highlight_protection import compress_clipped_highlights, protect_highlights
from engine.algorithms.low_quality_fidelity import (
    phase4_low_quality_policy,
    phase4_low_quality_restore,
    phase4_quality_probes,
)
from engine.algorithms.text_clarity import detect_text_like_regions, enhance_text_regions
from runtime.logger import logs_dir


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PROJECT_ROOT / "runtime"
OUTPUT_PROFILES = {"delivery_1080p", "preview_light", "fidelity_original"}
OUTPUT_FORMATS = {"auto", "png", "jpg", "jpeg", "webp"}
FORMAL_NOISE_MARKERS = (
    "_main",
    "_optimized",
    "_candidate",
    "_temp",
    "_debug",
    "async_test",
    "smoke_test",
    "demo_test",
    "vmp_async_test",
)

DELIVERY_METADATA = {
    "author_name": "雪原Ai·PPT设计",
    "author_wechat": "893812410",
    "author_contact": "微信：893812410",
    "copyright": "© 雪原Ai·PPT设计",
    "software_name": "影界 / VisualMasterPro",
    "metadata_description": "由影界高清交付引擎生成，用于中文商业视觉高清交付",
}


def _xp_text(value: str) -> bytes:
    return (str(value) + "\x00").encode("utf-16le")


def write_delivery_metadata(path: Path) -> dict[str, Any]:
    """Write silent delivery metadata into the output file.

    This must never block normal image export. Windows exposes common JPEG EXIF
    fields more reliably than PNG text chunks; PNG metadata is still written for
    tooling/Pillow/ExifTool verification.
    """
    target = Path(path)
    status = {
        "written": False,
        "format": target.suffix.lower().lstrip("."),
        "method": "",
        "error": "",
    }
    try:
        from PIL import Image
        from PIL.PngImagePlugin import PngInfo
    except Exception as exc:
        status["error"] = f"Pillow unavailable: {exc}"
        return status

    suffix = target.suffix.lower()
    try:
        if suffix in {".jpg", ".jpeg"}:
            with Image.open(target) as image:
                exif = image.getexif()
                exif[315] = DELIVERY_METADATA["author_name"]  # Artist
                exif[305] = DELIVERY_METADATA["software_name"]  # Software
                exif[33432] = DELIVERY_METADATA["copyright"]  # Copyright
                exif[270] = DELIVERY_METADATA["metadata_description"]  # ImageDescription
                exif[37510] = b"UNICODE\x00" + DELIVERY_METADATA["author_contact"].encode("utf-16le")
                exif[40091] = _xp_text("影界高清交付图")
                exif[40092] = _xp_text(DELIVERY_METADATA["author_contact"])
                exif[40093] = _xp_text(DELIVERY_METADATA["author_name"])
                exif[40095] = _xp_text(DELIVERY_METADATA["metadata_description"])
                save_kwargs = {"exif": exif}
                if image.format == "JPEG":
                    save_kwargs.update({"quality": "keep", "subsampling": "keep"})
                else:
                    save_kwargs.update({"quality": 95, "subsampling": 0})
                if image.mode not in {"RGB", "L"}:
                    image = image.convert("RGB")
                image.save(target, **save_kwargs)
            status.update({"written": True, "method": "jpeg_exif"})
            return status

        if suffix == ".png":
            with Image.open(target) as image:
                pnginfo = PngInfo()
                for key, value in (image.info or {}).items():
                    if isinstance(value, str):
                        pnginfo.add_text(key, value)
                png_entries = {
                    "Author": DELIVERY_METADATA["author_name"],
                    "Artist": DELIVERY_METADATA["author_name"],
                    "Creator": DELIVERY_METADATA["author_name"],
                    "Software": DELIVERY_METADATA["software_name"],
                    "Copyright": DELIVERY_METADATA["copyright"],
                    "Description": DELIVERY_METADATA["metadata_description"],
                    "Comment": DELIVERY_METADATA["author_contact"],
                    "Contact": DELIVERY_METADATA["author_contact"],
                    "WeChat": DELIVERY_METADATA["author_wechat"],
                    "VisualMasterPro.Author": DELIVERY_METADATA["author_name"],
                    "VisualMasterPro.WeChat": DELIVERY_METADATA["author_wechat"],
                    "VisualMasterPro.Contact": DELIVERY_METADATA["author_contact"],
                    "VisualMasterPro.Software": DELIVERY_METADATA["software_name"],
                }
                for key, value in png_entries.items():
                    pnginfo.add_text(key, value)
                image.save(target, pnginfo=pnginfo)
            status.update({"written": True, "method": "png_text"})
            return status

        status["error"] = "unsupported_format"
        return status
    except Exception as exc:
        status["error"] = str(exc)
        return status


def normalize_output_root(output_root: Path) -> Path:
    root = Path(output_root)
    return root


def safe_filename_part(value: str, fallback: str = "image") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or fallback)).strip(" .")
    return cleaned or fallback


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_output_profile(value: str | None) -> str:
    profile = str(value or "delivery_1080p").strip().lower()
    return profile if profile in OUTPUT_PROFILES else "delivery_1080p"


def normalize_output_format(value: str | None) -> str:
    fmt = str(value or "auto").strip().lower().lstrip(".")
    if fmt == "jpeg":
        fmt = "jpg"
    return fmt if fmt in OUTPUT_FORMATS else "auto"


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "debug"}


def load_image_with_alpha(path: Path) -> tuple[np.ndarray, np.ndarray | None, bool, bool]:
    data = np.fromfile(str(path), dtype=np.uint8)
    decoded = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if decoded is None:
        raise RuntimeError("图片读取失败。")
    if decoded.ndim == 2:
        return cv2.cvtColor(decoded, cv2.COLOR_GRAY2BGR), None, False, False
    if decoded.shape[2] == 4:
        alpha = decoded[:, :, 3]
        has_real_alpha = bool(np.any(alpha < 250))
        return cv2.cvtColor(decoded, cv2.COLOR_BGRA2BGR), alpha, True, has_real_alpha
    return decoded[:, :, :3], None, False, False


def aspect_label(width: int, height: int) -> tuple[float, str]:
    ratio = width / max(height, 1)
    presets = {
        "16:9": 16 / 9,
        "21:9": 21 / 9,
        "1:1": 1.0,
        "9:16": 9 / 16,
    }
    for name, value in presets.items():
        if abs(ratio - value) <= 0.025:
            return round(ratio, 6), name
    return round(ratio, 6), "custom"


def target_size(width: int, height: int, output_profile: str) -> tuple[int, int, str, str, bool, str, bool, bool]:
    profile = normalize_output_profile(output_profile)
    ratio, preset = aspect_label(width, height)
    if profile == "fidelity_original":
        return width, height, preset, "保持原尺寸，仅做忠实清洁增强。", True, "keep_original_size_clean_enhance", False, False

    if ratio >= 2.05:
        if width >= 2048:
            target_width, target_height = width, height
            resize_policy = "keep_original_size_clean_enhance"
        else:
            target_width = 2048
            target_height = int(round(height * (target_width / max(width, 1))))
            resize_policy = "upscale_long_edge_to_2048_keep_aspect"
    elif preset == "16:9":
        if width <= 1920 and height <= 1080:
            target_width, target_height = 1920, 1080
            resize_policy = "upscale_to_1920x1080_keep_aspect"
        else:
            scale = max(1.0, 1920 / max(width, 1), 1080 / max(height, 1))
            target_width = int(round(width * scale))
            target_height = int(round(height * scale))
            resize_policy = "upscale_to_1920x1080_keep_aspect" if scale > 1.0 else "keep_original_size_clean_enhance"
    elif preset == "1:1":
        scale = max(1.0, 1080 / max(width, 1), 1080 / max(height, 1))
        target_width = int(round(width * scale))
        target_height = int(round(height * scale))
        resize_policy = "upscale_to_1080_square_keep_aspect" if scale > 1.0 else "keep_original_size_clean_enhance"
    elif preset == "9:16":
        scale = max(1.0, 1080 / max(width, 1), 1920 / max(height, 1))
        target_width = int(round(width * scale))
        target_height = int(round(height * scale))
        resize_policy = "upscale_to_1080x1920_keep_aspect" if scale > 1.0 else "keep_original_size_clean_enhance"
    else:
        if width >= 1080 and height >= 1080:
            target_width, target_height = width, height
            resize_policy = "keep_original_size_clean_enhance"
        elif width >= height:
            scale = max(1.0, 1080 / max(height, 1))
            target_width = int(round(width * scale))
            target_height = int(round(height * scale))
            resize_policy = "upscale_short_edge_to_1080_keep_aspect"
        else:
            scale = max(1.0, 1080 / max(width, 1))
            target_width = int(round(width * scale))
            target_height = int(round(height * scale))
            resize_policy = "upscale_short_edge_to_1080_keep_aspect" if scale > 1.0 else "keep_original_size_clean_enhance"

    target_width = max(1, int(target_width))
    target_height = max(1, int(target_height))
    if target_width < width or target_height < height:
        target_width, target_height = width, height
        resize_policy = "keep_original_size_clean_enhance"
    was_upscaled = target_width > width or target_height > height
    was_downscaled = target_width < width or target_height < height
    scale_policy = "保持原比例，不裁切、不拉伸、不补边，以 1080P 高清交付基准输出。"
    resolution_gate_pass = target_width > 0 and target_height > 0 and not was_downscaled
    return target_width, target_height, preset, scale_policy, resolution_gate_pass, resize_policy, was_upscaled, was_downscaled


def estimate_text_density(image: np.ndarray) -> float:
    try:
        mask = detect_text_like_regions(image)
        return float(np.mean(mask > 0.18))
    except Exception:
        return 0.0


def skin_mask_ratio(image: np.ndarray) -> float:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lower = np.array([0, 20, 55], dtype=np.uint8)
    upper = np.array([28, 190, 245], dtype=np.uint8)
    mask_a = cv2.inRange(hsv, lower, upper)
    lower_b = np.array([160, 20, 55], dtype=np.uint8)
    upper_b = np.array([179, 175, 245], dtype=np.uint8)
    mask_b = cv2.inRange(hsv, lower_b, upper_b)
    return float(np.mean((mask_a | mask_b) > 0))


def edge_density(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 55, 145)
    return float(np.mean(edges > 0))


def texture_density(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    high = cv2.absdiff(gray, cv2.GaussianBlur(gray, (0, 0), 1.35))
    return float(np.mean(high > 8))


def classify_image_type(image: np.ndarray, text_density: float) -> tuple[str, dict[str, float]]:
    """Lightweight type hints for V0.3.7 strategy selection without OCR/model dependencies."""
    skin_ratio = skin_mask_ratio(image)
    edge_ratio = edge_density(image)
    tex_ratio = texture_density(image)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    saturation = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 1]
    dark_ratio = float(np.mean(gray < 72))
    low_sat_ratio = float(np.mean(saturation < 42))
    ratio = image.shape[1] / max(image.shape[0], 1)

    if skin_ratio >= 0.045 and dark_ratio >= 0.18:
        image_type = "portrait"
    elif ratio >= 2.0 and edge_ratio >= 0.075 and low_sat_ratio >= 0.55:
        image_type = "ppt_page"
    elif text_density >= 0.045 and edge_ratio >= 0.055:
        image_type = "ppt_page"
    elif text_density >= 0.018:
        image_type = "text_poster"
    elif edge_ratio >= 0.11 and low_sat_ratio >= 0.34:
        image_type = "architecture"
    elif tex_ratio >= 0.12 or (edge_ratio >= 0.095 and low_sat_ratio >= 0.36):
        image_type = "mixed"
    elif edge_ratio < 0.035 and low_sat_ratio < 0.42:
        image_type = "product_kv"
    else:
        image_type = "unknown"

    return image_type, {
        "skin_ratio": round(skin_ratio, 6),
        "edge_density": round(edge_ratio, 6),
        "texture_density": round(tex_ratio, 6),
        "dark_ratio": round(dark_ratio, 6),
        "low_saturation_ratio": round(low_sat_ratio, 6),
    }


def classify_degradation_type(image: np.ndarray, input_size_bytes: int = 0) -> str:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    high = cv2.absdiff(gray, cv2.GaussianBlur(gray, (0, 0), 1.2))
    noise_score = float(np.std(high))
    h, w = image.shape[:2]
    if min(w, h) < 720:
        return "low_resolution"
    if sharpness < 45:
        return "blur"
    if input_size_bytes and input_size_bytes / max(w * h, 1) < 0.8:
        return "jpeg_artifact"
    if noise_score > 12:
        return "noise"
    return "mixed"


def choose_format(
    requested_format: str,
    output_profile: str,
    has_alpha: bool,
    has_real_alpha: bool,
    text_density: float,
) -> tuple[str, str, bool]:
    requested_format = normalize_output_format(requested_format)
    if has_real_alpha:
        return "png", "检测到真实透明通道，强制选择 PNG 以保留透明信息。", True
    if requested_format != "auto":
        return requested_format, f"用户显式选择 {requested_format}。", False
    if has_alpha and not has_real_alpha:
        alpha_note = "检测到 RGBA 但透明度全为不透明，按普通图片参与 JPG/WebP 自动选择。"
    else:
        alpha_note = ""
    if output_profile == "preview_light":
        return "webp", f"{alpha_note} 轻量优化版优先选择 WebP。".strip(), False
    if text_density >= 0.035:
        return "jpg", f"{alpha_note} 检测到文字/UI 密度较高，自动选择 JPG 95 并启用质量守门。".strip(), False
    return "jpg", f"{alpha_note} 照片/场景类图像自动选择 JPG 94。".strip(), False


def output_dirs(output_root: Path) -> dict[str, Path]:
    root = normalize_output_root(output_root)
    return {
        "root": root,
        "formal": root,
        "work": RUNTIME_ROOT / "work",
        "debug": RUNTIME_ROOT / "debug",
        "test": RUNTIME_ROOT / "test",
        "test_archive": RUNTIME_ROOT / "test" / "archived",
    }


def quarantine_formal_output_noise(
    formal_dir: Path,
    test_archive_dir: Path,
    work_dir: Path,
    protected_paths: set[Path] | None = None,
) -> list[dict[str, str]]:
    moved: list[dict[str, str]] = []
    if not formal_dir.exists():
        return moved
    protected = {path.resolve() for path in (protected_paths or set())}
    test_archive_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    for path in formal_dir.iterdir():
        lower = path.name.lower()
        if path.is_dir() and lower in {"images", "work", "debug", "test"}:
            for final_file in path.rglob("*_vmp_v036_final.*"):
                if final_file.is_file():
                    target_final = formal_dir / final_file.name
                    counter = 1
                    while target_final.exists():
                        target_final = formal_dir / f"{final_file.stem}_{counter}{final_file.suffix}"
                        counter += 1
                    shutil.move(str(final_file), str(target_final))
                    moved.append({"from": str(final_file), "to": str(target_final)})
            target = test_archive_dir / f"{path.name}_archived"
            counter = 1
            while target.exists():
                target = test_archive_dir / f"{path.name}_archived_{counter}"
                counter += 1
            shutil.move(str(path), str(target))
            moved.append({"from": str(path), "to": str(target)})
            continue
        if not path.is_file():
            continue
        try:
            if path.resolve() in protected:
                continue
        except OSError:
            pass
        if "_影界高清_1080p_" in lower:
            continue
        if any(marker in lower for marker in FORMAL_NOISE_MARKERS):
            target_dir = test_archive_dir if any(marker in lower for marker in ("async_test", "smoke_test", "demo_test", "vmp_async_test")) else work_dir
            target = target_dir / path.name
            counter = 1
            while target.exists():
                target = target_dir / f"{path.stem}_{counter}{path.suffix}"
                counter += 1
            shutil.move(str(path), str(target))
            moved.append({"from": str(path), "to": str(target)})
    return moved


def build_output_paths(
    source: Path,
    output_root: Path,
    selected_format: str,
    mode: str = "fidelity",
    timestamp: str | None = None,
) -> dict[str, Path]:
    dirs = output_dirs(output_root)
    stem = safe_filename_part(Path(source).stem)
    mode_part = safe_filename_part(mode or "fidelity", "fidelity")
    timestamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_stem = f"{stem}_影界高清_1080P_{mode_part}_{timestamp}"
    fmt = "jpg" if selected_format == "jpeg" else selected_format
    for key in ("formal", "work", "debug", "test", "test_archive"):
        dirs[key].mkdir(parents=True, exist_ok=True)
    final_path = unique_path(dirs["formal"] / f"{output_stem}.{fmt}")
    return {
        "main": dirs["work"] / f"{output_stem}_main.png",
        "optimized": dirs["work"] / f"{output_stem}_optimized.{fmt}",
        "final": final_path,
        "debug_dir": dirs["debug"],
        "work_dir": dirs["work"],
        "formal_dir": dirs["formal"],
        "test_archive_dir": dirs["test_archive"],
    }


def build_output_plan(
    input_path: Path,
    output_root: Path,
    output_profile: str,
    output_format: str,
    debug_keep_intermediate: bool | str = False,
    mode: str = "fidelity",
    timestamp: str | None = None,
) -> dict[str, Any]:
    image, _, has_alpha, has_real_alpha = load_image_with_alpha(input_path)
    height, width = image.shape[:2]
    profile = normalize_output_profile(output_profile)
    text_density = estimate_text_density(image)
    image_type, type_features = classify_image_type(image, text_density)
    selected_format, format_note, alpha_used = choose_format(output_format, profile, has_alpha, has_real_alpha, text_density)
    target_width, target_height, preset, scale_policy, resolution_gate_pass, resize_policy, was_upscaled, was_downscaled = target_size(width, height, profile)
    ratio, _ = aspect_label(width, height)
    paths = build_output_paths(input_path, output_root, selected_format, mode=mode, timestamp=timestamp)
    return {
        "output_profile": output_profile or "delivery_1080p",
        "output_format": output_format or "auto",
        "selected_output_profile": profile,
        "selected_output_format": selected_format,
        "format_note": format_note,
        "selected_format_reason": format_note,
        "input_width": width,
        "input_height": height,
        "target_width": target_width,
        "target_height": target_height,
        "output_width": target_width,
        "output_height": target_height,
        "aspect_ratio": ratio,
        "aspect_preset": preset,
        "scale_policy": scale_policy,
        "resize_policy": resize_policy,
        "was_upscaled": was_upscaled,
        "was_downscaled": was_downscaled,
        "resolution_gate_pass": resolution_gate_pass,
        "has_alpha": has_alpha,
        "has_real_alpha": has_real_alpha,
        "alpha_used": alpha_used,
        "text_density": round(text_density, 6),
        "image_type": image_type,
        "image_type_features": type_features,
        "debug_keep_intermediate": parse_bool(debug_keep_intermediate),
        "paths": paths,
    }


def resize_keep_ratio(image: np.ndarray, target_width: int, target_height: int) -> np.ndarray:
    height, width = image.shape[:2]
    interpolation = cv2.INTER_LANCZOS4 if target_width >= width or target_height >= height else cv2.INTER_AREA
    return cv2.resize(image, (target_width, target_height), interpolation=interpolation)


def resize_alpha(alpha: np.ndarray | None, target_width: int, target_height: int) -> np.ndarray | None:
    if alpha is None:
        return None
    return cv2.resize(alpha, (target_width, target_height), interpolation=cv2.INTER_NEAREST)


def mid_frequency_detail(image: np.ndarray, strength: float) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype("float32")
    luma = lab[:, :, 0]
    base = cv2.GaussianBlur(luma, (0, 0), 1.12)
    detail = luma - base
    detail = np.sign(detail) * np.minimum(np.maximum(np.abs(detail) - 0.9, 0.0), 9.0)
    lab[:, :, 0] = np.clip(luma + detail * strength, 0, 255)
    return cv2.cvtColor(lab.astype("uint8"), cv2.COLOR_LAB2BGR)


def phase2_mid_frequency_strength(profile: str, mode: str, image_type: str, has_alpha: bool = False) -> float:
    if profile == "preview_light" or mode == "text_safe" or image_type in {"text_poster", "ppt_page"}:
        return 0.0
    base_strength = {
        "product_kv": 0.13,
        "architecture": 0.14,
        "landscape": 0.13,
        "mixed": 0.12,
        "portrait": 0.08,
        "unknown": 0.10,
        "general": 0.10,
    }.get(image_type, 0.10)
    if mode == "texture":
        base_strength += 0.03
    if has_alpha:
        base_strength *= 0.45
    return float(np.clip(base_strength, 0.0, 0.18))


def phase2_material_policy(
    profile: str,
    mode: str,
    image_type: str,
    has_alpha: bool = False,
    type_features: dict[str, Any] | None = None,
    text_density: float = 0.0,
) -> dict[str, Any]:
    features = type_features or {}
    texture_density = float(features.get("texture_density") or 0.0)
    edge_density = float(features.get("edge_density") or 0.0)
    dark_ratio = float(features.get("dark_ratio") or 0.0)
    low_saturation_ratio = float(features.get("low_saturation_ratio") or 0.0)
    base_strength = phase2_mid_frequency_strength(profile, mode, image_type, has_alpha=False)
    skip_reason = ""
    eligible = True

    if profile == "preview_light":
        eligible = False
        skip_reason = "preview_light_profile"
    elif mode == "text_safe" or image_type in {"text_poster", "ppt_page"}:
        eligible = False
        skip_reason = "text_safe_or_text_poster"
    elif text_density >= 0.18 and texture_density < 0.035:
        eligible = False
        skip_reason = "high_text_or_gradient_risk"
    elif edge_density >= 0.10 and low_saturation_ratio > 0.65:
        eligible = False
        skip_reason = "fine_line_table_risk"
    elif image_type == "unknown" and dark_ratio > 0.12 and edge_density > 0.025 and texture_density > 0.05:
        eligible = False
        skip_reason = "small_text_or_technical_graphic_risk"
    elif edge_density >= 0.075 and texture_density < 0.035:
        eligible = False
        skip_reason = "fine_line_structure_risk"
    elif texture_density < 0.003 and edge_density < 0.003:
        eligible = False
        skip_reason = "synthetic_gradient_risk"
    elif texture_density < 0.006:
        base_strength = min(base_strength, 0.025)
        skip_reason = "very_low_texture_conservative"
    elif texture_density < 0.018 and image_type not in {"architecture", "landscape"}:
        base_strength = min(base_strength, 0.055)
        skip_reason = "low_texture_conservative"
    elif low_saturation_ratio > 0.92 and texture_density < 0.028:
        base_strength = min(base_strength, 0.06)
        skip_reason = "flat_low_saturation_conservative"
    else:
        skip_reason = "eligible"

    if has_alpha and eligible:
        base_strength *= 0.45
        skip_reason = "alpha_safe_reduced" if skip_reason == "eligible" else f"{skip_reason}+alpha_safe_reduced"

    strength = float(np.clip(base_strength if eligible else 0.0, 0.0, 0.18))
    if strength <= 0:
        eligible = False
    return {
        "phase2_material_eligible": bool(eligible),
        "phase2_material_strength": round(strength, 4),
        "phase2_skip_reason": skip_reason,
        "phase2_texture_density": round(texture_density, 6),
        "phase2_edge_density": round(edge_density, 6),
        "phase2_dark_ratio": round(dark_ratio, 6),
        "phase2_text_density": round(float(text_density), 6),
    }


def phase2_mid_frequency_material(
    image: np.ndarray,
    strength: float,
    image_type: str,
) -> np.ndarray:
    """Restore restrained material layers while suppressing text, flat areas, and halos."""
    strength = float(np.clip(strength, 0.0, 0.18))
    if strength <= 0:
        return image

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype("float32")
    luma = lab[:, :, 0]

    small = cv2.GaussianBlur(luma, (0, 0), 0.95)
    mid = cv2.GaussianBlur(luma, (0, 0), 2.4)
    broad = cv2.GaussianBlur(luma, (0, 0), 5.2)
    band = (small - mid) * 0.72 + (mid - broad) * 0.58
    band = np.sign(band) * np.minimum(np.maximum(np.abs(band) - 0.55, 0.0), 7.5)

    mean = cv2.GaussianBlur(luma, (0, 0), 2.0)
    mean_sq = cv2.GaussianBlur(luma * luma, (0, 0), 2.0)
    local_std = np.sqrt(np.maximum(mean_sq - mean * mean, 0.0))
    texture_mask = np.clip((local_std - 1.3) / 12.0, 0.0, 1.0)
    texture_coverage = float(np.mean(texture_mask > 0.22))
    if texture_coverage < 0.015:
        strength *= 0.25
    elif texture_coverage < 0.04:
        strength *= 0.65

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hard_edges = cv2.Canny(gray, 80, 180)
    hard_edges = cv2.dilate(hard_edges, np.ones((3, 3), dtype=np.uint8), iterations=1).astype("float32") / 255.0
    edge_guard = 1.0 - np.clip(hard_edges * 0.62, 0.0, 0.82)

    text_guard = 1.0
    try:
        text_mask = detect_text_like_regions(image)
        if float(np.mean(text_mask > 0.12)) > 0.0005:
            text_mask = cv2.dilate((text_mask > 0.08).astype("uint8"), np.ones((5, 5), dtype=np.uint8), iterations=1)
            text_guard = 1.0 - np.clip(text_mask.astype("float32") * 0.92, 0.0, 0.92)
    except Exception:
        text_guard = 1.0

    highlight_guard = np.clip((242.0 - luma) / 22.0, 0.0, 1.0)
    shadow_guard = np.clip((luma - 8.0) / 22.0, 0.0, 1.0)
    tonal_guard = highlight_guard * shadow_guard

    type_gain = 1.0
    if image_type == "portrait":
        type_gain = 0.72
    elif image_type in {"architecture", "landscape"}:
        type_gain = 1.08

    blend = np.clip(texture_mask * edge_guard * text_guard * tonal_guard * type_gain, 0.0, 1.0)
    enhanced_luma = np.clip(luma + band * strength * blend, 0, 255)
    lab[:, :, 0] = enhanced_luma
    return cv2.cvtColor(lab.astype("uint8"), cv2.COLOR_LAB2BGR)


def light_clean(image: np.ndarray, profile: str, image_type: str, mode: str = "fidelity") -> np.ndarray:
    if profile == "preview_light":
        return cv2.bilateralFilter(image, 3, 5, 5)
    if mode == "text_safe":
        return cv2.bilateralFilter(image, 3, 3, 3)
    if image_type in {"portrait", "mixed"}:
        cleaned = cv2.bilateralFilter(image, 3, 4, 4)
        return cv2.fastNlMeansDenoisingColored(cleaned, None, 0.45, 0.45, 7, 15)
    cleaned = cv2.bilateralFilter(image, 3, 6, 6)
    return cv2.fastNlMeansDenoisingColored(cleaned, None, 0.75, 0.75, 7, 15)


def enhance_fidelity(
    image: np.ndarray,
    target_width: int,
    target_height: int,
    profile: str,
    mode: str,
    image_type: str = "general",
    has_alpha: bool = False,
    phase2_strength: float | None = None,
    phase3_policy: dict[str, Any] | None = None,
    phase4_policy: dict[str, Any] | None = None,
) -> np.ndarray:
    reference = resize_keep_ratio(image, target_width, target_height)
    result = compress_clipped_highlights(reference, amount=0.04)
    result = light_clean(result, profile, image_type, mode)

    mid_strength = 0.11 if profile == "preview_light" else 0.18
    edge_strength = 0.13 if profile == "preview_light" else 0.22
    text_strength = 0.18 if profile == "preview_light" else 0.30
    text_intensive = mode == "text_safe"
    if image_type == "portrait":
        mid_strength += 0.02
        edge_strength -= 0.02
        text_strength -= 0.03
    elif image_type in {"text_poster", "ppt_page"}:
        mid_strength += 0.03
        edge_strength += 0.04
        text_strength += 0.08
    elif image_type == "mixed":
        mid_strength += 0.04
        edge_strength += 0.01
        text_strength -= 0.04
    if mode == "sharp_4k":
        mid_strength += 0.03
        edge_strength += 0.02
    if mode == "text_safe":
        mid_strength += 0.02
        edge_strength += 0.01
        text_strength += 0.06
    if mode == "texture":
        mid_strength += 0.05
        edge_strength += 0.01
        text_strength -= 0.03

    if text_intensive:
        result = enhance_text_regions(result, strength=min(text_strength * 0.72, 0.38))
    result = mid_frequency_detail(result, strength=mid_strength)
    if phase2_strength is None:
        phase2_strength = phase2_mid_frequency_strength(profile, mode, image_type, has_alpha=has_alpha)
    result = phase2_mid_frequency_material(result, strength=phase2_strength, image_type=image_type)
    result = phase4_low_quality_restore(reference, result, phase4_policy)
    phase3_reference = result.copy()
    result = enhance_true_edges(result, strength=max(0.08, min(edge_strength, 0.28 if text_intensive else 0.30)))
    result = enhance_text_regions(result, strength=min(text_strength, 0.52 if text_intensive else 0.42))
    result = phase3_edge_halo_control(phase3_reference, result, phase3_policy)
    result = protect_highlights(reference, result, strength=0.92)
    return lock_color_to_reference(reference, result, chroma_strength=0.985, luma_strength=0.045)


def add_alpha_channel(image: np.ndarray, alpha: np.ndarray | None) -> np.ndarray:
    if alpha is None:
        return image
    return cv2.cvtColor(np.dstack([image, alpha]), cv2.COLOR_BGRA2BGRA)


def encode_image(
    image: np.ndarray,
    output_format: str,
    role: str,
    profile: str,
    alpha: np.ndarray | None = None,
) -> tuple[np.ndarray, str]:
    fmt = normalize_output_format(output_format)
    if fmt == "auto":
        fmt = "jpg"
    if role == "main":
        fmt = "png"
    if alpha is not None:
        fmt = "png"
        image_to_encode = np.dstack([image, alpha])
    else:
        image_to_encode = image

    if fmt == "png":
        params = [cv2.IMWRITE_PNG_COMPRESSION, 6 if role == "main" else 8]
        ext = ".png"
    elif fmt == "webp":
        quality = 88 if profile == "preview_light" else 94
        params = [cv2.IMWRITE_WEBP_QUALITY, quality]
        ext = ".webp"
    else:
        quality = 92 if profile == "preview_light" else 95
        params = [cv2.IMWRITE_JPEG_QUALITY, quality, cv2.IMWRITE_JPEG_OPTIMIZE, 1]
        ext = ".jpg"
    ok, encoded = cv2.imencode(ext, image_to_encode, params)
    if not ok:
        raise RuntimeError(f"{role} 输出编码失败。")
    return encoded, fmt.lstrip(".")


def write_encoded(path: Path, encoded: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(str(path))


def safe_copy_final(source: Path, final_path: Path) -> Path:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = final_path.with_name(f"{final_path.stem}_tmp{final_path.suffix}")
    counter = 1
    while temp_path.exists():
        temp_path = final_path.with_name(f"{final_path.stem}_tmp_{counter}{final_path.suffix}")
        counter += 1
    shutil.copyfile(str(source), str(temp_path))
    try:
        temp_path.replace(final_path)
    except OSError:
        if final_path.exists():
            final_path.unlink()
        temp_path.replace(final_path)
    return final_path


def decode_encoded(encoded: np.ndarray) -> np.ndarray:
    decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if decoded is None:
        raise RuntimeError("候选输出解码失败。")
    return decoded


def laplacian_score(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_32F).var())


def edge_score(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    return float(np.mean(cv2.magnitude(gx, gy)))


def text_score(image: np.ndarray) -> float:
    try:
        mask = detect_text_like_regions(image)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 60, 160)
        grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        magnitude = cv2.magnitude(grad_x, grad_y)
        lap = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
        local = cv2.blur(gray.astype("float32"), (7, 7))
        local_contrast = np.abs(gray.astype("float32") - local)
        area = mask > 0.12
        if np.mean(area) < 0.0005:
            return laplacian_score(image)
        edge_signal = float(np.mean(edges[area])) * 1.35
        gradient_signal = float(np.mean(magnitude[area])) * 0.62
        lap_signal = float(np.mean(lap[area])) * 0.18
        contrast_signal = float(np.mean(local_contrast[area])) * 1.45
        score = max(edge_signal, gradient_signal + lap_signal + contrast_signal)
        if score <= 0.01:
            return laplacian_score(image)
        return score
    except Exception:
        return laplacian_score(image)


def score_0_100(value: float, scale: float) -> float:
    return round(float(max(0.0, min(100.0, math.log1p(max(value, 0.0)) * scale))), 4)


def high_frequency_score(image: np.ndarray, mask: np.ndarray | None = None) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    high = cv2.absdiff(gray, cv2.GaussianBlur(gray, (0, 0), 1.15))
    if mask is not None and np.mean(mask) > 0.001:
        value = float(np.mean(high[mask]))
    else:
        value = float(np.mean(high))
    return score_0_100(value, 16.0)


def skin_mask(image: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask_a = cv2.inRange(hsv, np.array([0, 20, 55], dtype=np.uint8), np.array([28, 190, 245], dtype=np.uint8))
    mask_b = cv2.inRange(hsv, np.array([160, 20, 55], dtype=np.uint8), np.array([179, 175, 245], dtype=np.uint8))
    return (mask_a | mask_b) > 0


def dark_edge_mask(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 45, 135) > 0
    return (gray < 95) & edges


def fabric_like_mask(image: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    saturation = hsv[:, :, 1]
    high = cv2.absdiff(gray, cv2.GaussianBlur(gray, (0, 0), 1.35))
    return (high > 7) & ((saturation > 35) | (gray < 115))


def dark_region_mask(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return gray < 88


def risk_from_gain(primary_gain: float, secondary_gain: float = 0.0) -> str:
    worst = min(primary_gain, secondary_gain)
    if worst < -1.2:
        return "high"
    if worst < -0.25:
        return "medium"
    return "low"


def mean_lab_delta(reference: np.ndarray, candidate: np.ndarray) -> float:
    if reference.shape[:2] != candidate.shape[:2]:
        reference = cv2.resize(reference, (candidate.shape[1], candidate.shape[0]), interpolation=cv2.INTER_CUBIC)
    ref_lab = cv2.cvtColor(reference, cv2.COLOR_BGR2LAB).astype("float32")
    cand_lab = cv2.cvtColor(candidate, cv2.COLOR_BGR2LAB).astype("float32")
    return float(np.mean(np.abs(ref_lab - cand_lab)))


def pixel_diff_score(input_image: np.ndarray, output_image: np.ndarray) -> float:
    if input_image.shape[:2] != output_image.shape[:2]:
        input_image = cv2.resize(input_image, (output_image.shape[1], output_image.shape[0]), interpolation=cv2.INTER_CUBIC)
    return float(np.mean(cv2.absdiff(input_image, output_image)))


def classify_risk(value: float, low_limit: float, high_limit: float) -> str:
    if value <= low_limit:
        return "low"
    if value <= high_limit:
        return "medium"
    return "high"


def quality_metrics(before_image: np.ndarray, after_image: np.ndarray, text_density: float) -> dict[str, Any]:
    before_resized = before_image
    if before_image.shape[:2] != after_image.shape[:2]:
        before_resized = cv2.resize(before_image, (after_image.shape[1], after_image.shape[0]), interpolation=cv2.INTER_CUBIC)

    before_text_mask = detect_text_like_regions(before_resized)
    after_text_mask = detect_text_like_regions(after_image)
    before_text_region_density = float(np.mean(before_text_mask > 0.12))
    after_text_region_density = float(np.mean(after_text_mask > 0.12))
    before_clarity_raw = laplacian_score(before_resized)
    after_clarity_raw = laplacian_score(after_image)
    before_text_raw = text_score(before_resized)
    after_text_raw = text_score(after_image)
    before_edge_raw = edge_score(before_resized)
    after_edge_raw = edge_score(after_image)
    color_delta = mean_lab_delta(before_resized, after_image)
    diff = pixel_diff_score(before_resized, after_image)

    clarity_score = score_0_100(after_clarity_raw, 11.0)
    before_clarity_score = score_0_100(before_clarity_raw, 11.0)
    text_clarity_score = score_0_100(after_text_raw, 10.5)
    before_text_score = score_0_100(before_text_raw, 10.5)
    edge_quality_score = score_0_100(after_edge_raw, 15.5)
    before_edge_score = score_0_100(before_edge_raw, 15.5)
    color_fidelity_score = round(max(0.0, min(100.0, 100.0 - color_delta * 3.2)), 4)
    detail_stability_score = round(max(0.0, min(100.0, 92.0 - abs(diff - 1.8) * 4.0)), 4)

    clarity_gain = round(clarity_score - before_clarity_score, 4)
    text_gain = round(text_clarity_score - before_text_score, 4)
    edge_gain = round(edge_quality_score - before_edge_score, 4)
    compression_damage_risk = classify_risk(color_delta, 1.15, 2.2)
    pseudo_hd_value = max(0.0, (0.2 - clarity_gain) + (0.1 - edge_gain))
    pseudo_hd_risk = "low" if pseudo_hd_value <= 0.4 and diff > 0.05 else "medium"
    artifact_risk = "high" if color_fidelity_score < 88 or compression_damage_risk == "high" else ("medium" if color_fidelity_score < 93 else "low")

    before_face = high_frequency_score(before_resized, skin_mask(before_resized))
    after_face = high_frequency_score(after_image, skin_mask(after_image))
    before_hair = high_frequency_score(before_resized, dark_edge_mask(before_resized))
    after_hair = high_frequency_score(after_image, dark_edge_mask(after_image))
    before_fabric = high_frequency_score(before_resized, fabric_like_mask(before_resized))
    after_fabric = high_frequency_score(after_image, fabric_like_mask(after_image))
    before_dark = high_frequency_score(before_resized, dark_region_mask(before_resized))
    after_dark = high_frequency_score(after_image, dark_region_mask(after_image))
    text_edge_clean_score = round(max(0.0, min(100.0, text_clarity_score - max(0.0, color_delta - 0.8) * 4.0)), 4)
    small_text_readability_score = round(
        max(0.0, min(100.0, text_clarity_score * 0.74 + edge_quality_score * 0.26 - max(0.0, color_delta - 1.0) * 2.0)),
        4,
    )
    face_gain = round(after_face - before_face, 4)
    hair_gain = round(after_hair - before_hair, 4)
    fabric_gain = round(after_fabric - before_fabric, 4)
    dark_gain = round(after_dark - before_dark, 4)
    over_smoothing_risk = risk_from_gain(clarity_gain, min(hair_gain, fabric_gain))
    texture_loss_risk = risk_from_gain(min(hair_gain, fabric_gain), detail_stability_score - 78.0)

    visual_score = round(
        clarity_score * 0.22
        + text_clarity_score * (0.22 if text_density >= 0.01 else 0.12)
        + edge_quality_score * 0.22
        + detail_stability_score * 0.16
        + color_fidelity_score * 0.18,
        4,
    )
    return {
        "clarity_score": clarity_score,
        "clarity_gain": clarity_gain,
        "text_clarity_score": text_clarity_score,
        "text_clarity_gain": text_gain,
        "edge_quality_score": edge_quality_score,
        "edge_quality_gain": edge_gain,
        "detail_stability_score": detail_stability_score,
        "color_fidelity_score": color_fidelity_score,
        "artifact_risk": artifact_risk,
        "pseudo_hd_risk": pseudo_hd_risk,
        "compression_damage_risk": compression_damage_risk,
        "face_detail_score": after_face,
        "face_detail_gain": face_gain,
        "hair_texture_score": after_hair,
        "hair_texture_gain": hair_gain,
        "fabric_texture_score": after_fabric,
        "fabric_texture_gain": fabric_gain,
        "text_edge_clean_score": text_edge_clean_score,
        "small_text_readability_score": small_text_readability_score,
        "before_text_region_density": round(before_text_region_density, 6),
        "after_text_region_density": round(after_text_region_density, 6),
        "text_region_density_delta": round(after_text_region_density - before_text_region_density, 6),
        "dark_detail_score": after_dark,
        "dark_detail_gain": dark_gain,
        "over_smoothing_risk": over_smoothing_risk,
        "texture_loss_risk": texture_loss_risk,
        "visual_score": visual_score,
        "pixel_diff_from_reference": round(diff, 6),
        "color_delta": round(color_delta, 6),
    }


def visual_gate(metrics: dict[str, Any], text_density: float) -> tuple[bool, str, str]:
    pass_gate = (
        metrics["color_fidelity_score"] >= 88
        and metrics["artifact_risk"] != "high"
        and metrics["pseudo_hd_risk"] != "high"
        and metrics["detail_stability_score"] >= 55
        and metrics["clarity_score"] >= 15
        and metrics["clarity_gain"] >= -0.5
        and metrics["edge_quality_gain"] >= -0.5
    )
    if text_density >= 0.015:
        pass_gate = pass_gate and metrics["text_clarity_score"] >= 24 and metrics["text_clarity_gain"] >= -0.8
    visual_score = metrics["visual_score"]
    if not pass_gate:
        level = "failed"
    elif visual_score >= 72 and metrics["color_fidelity_score"] >= 95:
        level = "excellent"
    elif visual_score >= 50:
        level = "standard"
    else:
        level = "acceptable"
    note = (
        f"清晰度 {metrics['clarity_score']}，文字 {metrics['text_clarity_score']}，"
        f"边缘 {metrics['edge_quality_score']}，色彩忠实 {metrics['color_fidelity_score']}，"
        f"伪高清风险 {metrics['pseudo_hd_risk']}。"
    )
    return bool(pass_gate), level, note


def visual_gate(metrics: dict[str, Any], text_density: float, image_type: str = "general") -> tuple[bool, str, str]:
    """V0.3.7 stricter 1080P delivery gate.

    Standard/excellent only appear when clarity, edge, texture, color fidelity,
    pseudo-HD risk, and over-smoothing risk are all stable.
    """
    pass_gate = (
        metrics["color_fidelity_score"] >= 91
        and metrics["artifact_risk"] != "high"
        and metrics["pseudo_hd_risk"] != "high"
        and metrics["over_smoothing_risk"] != "high"
        and metrics["texture_loss_risk"] != "high"
        and metrics["detail_stability_score"] >= 64
        and metrics["clarity_score"] >= 15
        and metrics["clarity_gain"] >= -0.25
        and metrics["edge_quality_gain"] >= -0.25
    )
    if text_density >= 0.015 or image_type in {"text_poster", "ppt_page"}:
        text_drop_floor = -2.0 if image_type in {"text_poster", "ppt_page"} else -1.2
        pass_gate = pass_gate and metrics["text_clarity_score"] >= 24 and metrics["text_clarity_gain"] >= text_drop_floor
    if image_type == "portrait":
        pass_gate = pass_gate and metrics["face_detail_gain"] >= -0.4 and metrics["hair_texture_gain"] >= -0.4
    if image_type == "mixed":
        pass_gate = pass_gate and metrics["fabric_texture_gain"] >= -0.35 and metrics["hair_texture_gain"] >= -0.35

    standard_gate = (
        pass_gate
        and metrics["color_fidelity_score"] >= 94
        and metrics["pseudo_hd_risk"] == "low"
        and metrics["over_smoothing_risk"] == "low"
        and metrics["texture_loss_risk"] == "low"
        and metrics["detail_stability_score"] >= 78
        and metrics["edge_quality_gain"] >= 0.0
        and metrics["clarity_gain"] >= 0.0
    )
    if text_density >= 0.015 or image_type in {"text_poster", "ppt_page"}:
        standard_gate = standard_gate and metrics["text_clarity_gain"] >= 0.0 and metrics["small_text_readability_score"] >= 26
    if image_type == "portrait":
        standard_gate = standard_gate and metrics["face_detail_gain"] >= 0.0 and metrics["hair_texture_gain"] >= 0.0
    if image_type == "mixed":
        standard_gate = standard_gate and metrics["fabric_texture_gain"] >= 0.0

    excellent_gate = (
        standard_gate
        and metrics["visual_score"] >= 74
        and metrics["text_clarity_gain"] >= 0.6
        and metrics["edge_quality_gain"] >= 0.6
        and metrics["detail_stability_score"] >= 86
        and metrics["color_fidelity_score"] >= 96
    )
    if not pass_gate:
        level = "failed"
    elif excellent_gate:
        level = "excellent"
    elif standard_gate:
        level = "standard"
    else:
        level = "acceptable"
    note = (
        f"1080P 质量判断：清晰度变化 {metrics['clarity_gain']}，文字清晰度变化 {metrics['text_clarity_gain']}，"
        f"边缘稳定性变化 {metrics['edge_quality_gain']}，细节稳定性 {metrics['detail_stability_score']}，"
        f"过度柔化风险 {metrics['over_smoothing_risk']}，纹理损失风险 {metrics['texture_loss_risk']}，"
        f"伪高清风险 {metrics['pseudo_hd_risk']}，最终等级 {level}。"
    )
    return bool(pass_gate), level, note


def compression_gate(main_image: np.ndarray, candidate_image: np.ndarray, profile: str, text_density: float) -> dict[str, Any]:
    diff = pixel_diff_score(main_image, candidate_image)
    color_delta = mean_lab_delta(main_image, candidate_image)
    main_edge = laplacian_score(main_image)
    candidate_edge = laplacian_score(candidate_image)
    edge_ratio = candidate_edge / max(main_edge, 1e-6)

    diff_limit = 2.2 if profile == "preview_light" else 1.45
    color_limit = 2.0 if profile == "preview_light" else 1.35
    edge_limit = 0.82 if profile == "preview_light" else 0.88
    if text_density >= 0.035:
        diff_limit -= 0.25
        edge_limit += 0.04

    quality_preserved = diff <= diff_limit and color_delta <= color_limit and edge_ratio >= edge_limit
    return {
        "quality_preserved": bool(quality_preserved),
        "candidate_pixel_diff_from_main": round(diff, 6),
        "candidate_color_delta": round(color_delta, 6),
        "candidate_edge_ratio": round(edge_ratio, 6),
        "compression_quality_drop": round(max(0.0, color_delta + max(0.0, 1.0 - edge_ratio) * 4.0), 6),
        "compression_allowed": bool(quality_preserved),
        "pseudo_hd_risk": "low" if quality_preserved else "medium",
    }


def compression_gate(
    main_image: np.ndarray,
    candidate_image: np.ndarray,
    profile: str,
    text_density: float,
    candidate_metrics: dict[str, Any] | None = None,
    image_type: str = "general",
) -> dict[str, Any]:
    """V0.3.7 quality-first compression gate.

    Smaller output is allowed only when the candidate keeps text, edges, detail,
    texture and color stable. Delivery mode is intentionally stricter than preview.
    """
    diff = pixel_diff_score(main_image, candidate_image)
    color_delta = mean_lab_delta(main_image, candidate_image)
    main_edge = laplacian_score(main_image)
    candidate_edge = laplacian_score(candidate_image)
    edge_ratio = candidate_edge / max(main_edge, 1e-6)

    diff_limit = 1.9 if profile == "preview_light" else 1.05
    color_limit = 1.65 if profile == "preview_light" else 1.0
    edge_limit = 0.9 if profile == "preview_light" else 0.965
    if text_density >= 0.035:
        diff_limit -= 0.18
        color_limit -= 0.12
        edge_limit += 0.025

    metric_gate = True
    metric_reasons: list[str] = []
    if candidate_metrics:
        checks = [
            ("text_clarity_gain", candidate_metrics.get("text_clarity_gain", 0.0), -0.05),
            ("edge_quality_gain", candidate_metrics.get("edge_quality_gain", 0.0), -0.05),
            ("face_detail_gain", candidate_metrics.get("face_detail_gain", 0.0), -0.15 if image_type == "portrait" else -0.35),
            ("hair_texture_gain", candidate_metrics.get("hair_texture_gain", 0.0), -0.12 if image_type in {"portrait", "mixed"} else -0.28),
            ("fabric_texture_gain", candidate_metrics.get("fabric_texture_gain", 0.0), -0.12 if image_type == "mixed" else -0.28),
            ("dark_detail_gain", candidate_metrics.get("dark_detail_gain", 0.0), -0.25),
        ]
        for name, value, floor in checks:
            if float(value) < floor:
                metric_gate = False
                metric_reasons.append(f"{name}={value} < {floor}")
        if candidate_metrics.get("over_smoothing_risk") != "low":
            metric_gate = False
            metric_reasons.append(f"over_smoothing_risk={candidate_metrics.get('over_smoothing_risk')}")
        if candidate_metrics.get("texture_loss_risk") != "low":
            metric_gate = False
            metric_reasons.append(f"texture_loss_risk={candidate_metrics.get('texture_loss_risk')}")
        if candidate_metrics.get("pseudo_hd_risk") != "low":
            metric_gate = False
            metric_reasons.append(f"pseudo_hd_risk={candidate_metrics.get('pseudo_hd_risk')}")

    primitive_gate = diff <= diff_limit and color_delta <= color_limit and edge_ratio >= edge_limit
    quality_preserved = bool(primitive_gate and metric_gate)
    if not primitive_gate:
        metric_reasons.append(
            f"primitive_gate_failed(diff={round(diff, 4)}, color_delta={round(color_delta, 4)}, edge_ratio={round(edge_ratio, 4)})"
        )
    return {
        "quality_preserved": bool(quality_preserved),
        "candidate_pixel_diff_from_main": round(diff, 6),
        "candidate_color_delta": round(color_delta, 6),
        "candidate_edge_ratio": round(edge_ratio, 6),
        "compression_quality_drop": round(max(0.0, color_delta + max(0.0, 1.0 - edge_ratio) * 4.0), 6),
        "compression_allowed": bool(quality_preserved),
        "pseudo_hd_risk": "low" if quality_preserved else "medium",
        "compression_damage_risk": "low" if quality_preserved else "medium",
        "strict_gate_reasons": metric_reasons,
    }


def debug_log(payload: dict[str, Any]) -> Path:
    log_path = logs_dir() / "v036_latest_output_debug.json"
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return log_path


def process_v036_output(
    input_path: Path,
    output_root: Path,
    mode: str = "fidelity",
    output_profile: str = "delivery_1080p",
    output_format: str = "auto",
    initial_timing: dict[str, float] | None = None,
    debug_keep_intermediate: bool | str = False,
) -> dict[str, Any]:
    total_start = time.perf_counter()
    timings = dict(initial_timing or {})
    timings.setdefault("receive_file_time", 0.0)
    timings.setdefault("save_input_time", 0.0)

    input_path = Path(input_path)
    output_root = Path(output_root)
    dirs = output_dirs(output_root)
    for folder in dirs.values():
        if isinstance(folder, Path):
            folder.mkdir(parents=True, exist_ok=True)
    moved_noise = quarantine_formal_output_noise(dirs["formal"], dirs["test_archive"], dirs["work"])

    input_size_bytes = input_path.stat().st_size
    input_hash = sha256_file(input_path)
    export_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    start = time.perf_counter()
    source_image, alpha, has_alpha, has_real_alpha = load_image_with_alpha(input_path)
    timings["decode_image_time"] = round(time.perf_counter() - start, 6)
    degradation_type = classify_degradation_type(source_image, input_size_bytes)

    plan = build_output_plan(
        input_path,
        output_root,
        output_profile,
        output_format,
        debug_keep_intermediate,
        mode=mode,
        timestamp=export_timestamp,
    )
    profile = plan["selected_output_profile"]
    selected_format = plan["selected_output_format"]
    image_type = plan["image_type"]
    paths = plan["paths"]
    target_alpha = resize_alpha(alpha, plan["output_width"], plan["output_height"]) if plan["alpha_used"] else None
    phase4_reference = resize_keep_ratio(source_image, plan["output_width"], plan["output_height"])
    phase4_before_probes = phase4_quality_probes(phase4_reference)
    phase2_policy = phase2_material_policy(
        profile,
        mode,
        image_type,
        has_alpha=plan["alpha_used"],
        type_features=plan["image_type_features"],
        text_density=plan["text_density"],
    )
    phase3_policy = phase3_edge_policy(
        profile,
        mode,
        image_type,
        has_alpha=plan["alpha_used"],
        type_features=plan["image_type_features"],
        text_density=plan["text_density"],
    )
    phase4_policy = phase4_low_quality_policy(
        profile,
        mode,
        image_type,
        has_alpha=plan["alpha_used"],
        type_features=plan["image_type_features"],
        text_density=plan["text_density"],
        input_width=plan["input_width"],
        input_height=plan["input_height"],
        input_size_bytes=input_size_bytes,
        input_suffix=input_path.suffix,
        before_probes=phase4_before_probes,
    )

    start = time.perf_counter()
    enhanced = enhance_fidelity(
        source_image,
        plan["output_width"],
        plan["output_height"],
        profile,
        mode,
        image_type,
        has_alpha=plan["alpha_used"],
        phase2_strength=phase2_policy["phase2_material_strength"],
        phase3_policy=phase3_policy,
        phase4_policy=phase4_policy,
    )
    timings["enhance_time"] = round(time.perf_counter() - start, 6)
    phase4_after_probes = phase4_quality_probes(enhanced)
    v046_text_engine_active = bool(mode == "text_safe" or image_type in {"text_poster", "ppt_page"} or plan["text_density"] >= 0.015)

    start = time.perf_counter()
    main_encoded, _ = encode_image(enhanced, "png", role="main", profile=profile, alpha=target_alpha)
    optimized_encoded, selected_format = encode_image(enhanced, selected_format, role="optimized", profile=profile, alpha=target_alpha)
    timings["encode_output_time"] = round(time.perf_counter() - start, 6)

    start = time.perf_counter()
    write_encoded(paths["main"], main_encoded)
    write_encoded(paths["optimized"], optimized_encoded)
    optimized_image = decode_encoded(optimized_encoded)
    timings["write_output_time"] = round(time.perf_counter() - start, 6)

    start = time.perf_counter()
    reference = resize_keep_ratio(source_image, plan["output_width"], plan["output_height"])
    main_metrics = quality_metrics(reference, enhanced, plan["text_density"])
    main_visual_pass, main_level, visual_note = visual_gate(main_metrics, plan["text_density"], image_type)
    candidate_metrics = quality_metrics(enhanced, optimized_image, plan["text_density"])
    compression = compression_gate(enhanced, optimized_image, profile, plan["text_density"], candidate_metrics, image_type)
    timings["quality_gate_time"] = round(time.perf_counter() - start, 6)

    main_size = paths["main"].stat().st_size
    optimized_size = paths["optimized"].stat().st_size
    optimized_smaller = optimized_size <= main_size
    resolution_gate_pass = bool(plan["resolution_gate_pass"] and enhanced.shape[1] == plan["output_width"] and enhanced.shape[0] == plan["output_height"])
    quality_1080p_pass = bool(resolution_gate_pass and main_visual_pass)
    use_optimized = bool(quality_1080p_pass and compression["compression_allowed"] and optimized_smaller)
    final_source = paths["optimized"] if use_optimized else paths["main"]
    final_quality_source = "optimized_output" if use_optimized else "main_output"
    final_path = paths["final"]
    if final_path.suffix.lower() != final_source.suffix.lower():
        final_path = final_path.with_suffix(final_source.suffix)
        paths["final"] = final_path
    final_path = safe_copy_final(final_source, final_path)
    paths["final"] = final_path
    quarantine_formal_output_noise(dirs["formal"], dirs["test_archive"], dirs["work"], protected_paths={final_path})
    delivery_package = write_delivery_metadata(final_path)

    final_size = final_path.stat().st_size
    final_hash = sha256_file(final_path)
    final_image = load_image_with_alpha(final_path)[0]
    final_diff = pixel_diff_score(source_image, final_image)
    hash_equal = input_hash == final_hash
    output_changed = (input_path.resolve() != final_path.resolve()) and (not hash_equal) and final_diff > 0
    file_size_ratio = round(final_size / max(input_size_bytes, 1), 4)
    compression_saved_ratio = round(max(main_size - final_size, 0) / max(main_size, 1), 4)
    final_output_type = final_quality_source

    if use_optimized:
        compression_note = "已完成无感体积优化，画质守门通过，文字、边缘和色彩保持稳定。"
    elif not optimized_smaller:
        compression_note = "优化候选未比高清主图更小，已保留高清主图。"
    else:
        compression_note = "压缩候选会造成画质下降，已保留高清主图，未强制压缩。"

    if use_optimized:
        compression_note = "已完成无感体积优化，画质守门通过，文字、边缘、发丝、织物细节和色彩保持稳定。"
        final_selection_reason = "optimized_output 体积更小且文字、边缘、发丝、织物、暗部细节未下降，选为 final。"
    elif not optimized_smaller:
        compression_note = "优化候选未比高清主图更小，已保留高清主图。"
        final_selection_reason = "optimized_output 未形成有效体积收益，回退 main_output 作为 final。"
    else:
        compression_note = "压缩候选会造成画质下降，已保留高清主图，未强制压缩。"
        final_selection_reason = "optimized_output 体积更小但细节稳定性、文字边缘或纹理风险未通过，回退 main_output 作为 final。"

    warnings: list[str] = []
    if moved_noise:
        warnings.append(f"已从正式输出目录隔离 {len(moved_noise)} 个测试/中间文件。")
    if not output_changed:
        warnings.append("输出图疑似原图复制：output_changed=false，请检查增强管线。")
    if file_size_ratio > 8.0:
        warnings.append(f"输出体积异常增大：ratio={file_size_ratio}，建议评估 JPG/WebP 或压缩参数。")
    if not quality_1080p_pass:
        warnings.append("1080P 质量守门未完全通过，final 已回退到当前质量最稳定图。")
    if final_path.name.lower().endswith(("_main.png", "_optimized.png")):
        warnings.append("final 输出命名异常，已保留在正式目录但需要检查路径策略。")
    if not delivery_package.get("written"):
        warnings.append("交付封装信息未写入，不影响成品图正常输出。")
    encoding_warning = ""
    if final_size < input_size_bytes * 0.35:
        encoding_warning = "输出体积明显小于原图，请复核是否存在过度压缩、降采样或细节损失。"
        warnings.append(encoding_warning)

    keep_intermediate = parse_bool(debug_keep_intermediate)
    removed_intermediate: list[str] = []
    if not keep_intermediate:
        for temp_path in (paths["main"], paths["optimized"]):
            try:
                if temp_path.exists() and temp_path.resolve() != final_path.resolve():
                    temp_path.unlink()
                    removed_intermediate.append(str(temp_path))
            except Exception as exc:
                warnings.append(f"中间文件清理失败：{temp_path}，原因：{exc}")

    quality_before_compression = round(main_metrics["visual_score"], 4)
    quality_after_compression = round(candidate_metrics["visual_score"], 4)
    compression_quality_drop = round(max(0.0, quality_before_compression - quality_after_compression), 4)
    timings["total_time"] = round(time.perf_counter() - total_start, 6)

    debug_quality = {
        "input_width": plan["input_width"],
        "input_height": plan["input_height"],
        "output_width": plan["output_width"],
        "output_height": plan["output_height"],
        "target_width": plan["target_width"],
        "target_height": plan["target_height"],
        "aspect_ratio": plan["aspect_ratio"],
        "aspect_preset": plan["aspect_preset"],
        "scale_policy": plan["scale_policy"],
        "resize_policy": plan["resize_policy"],
        "was_upscaled": plan["was_upscaled"],
        "was_downscaled": plan["was_downscaled"],
        "image_type": image_type,
        "degradation_type": degradation_type,
        "image_type_features": plan["image_type_features"],
        "resolution_gate_pass": resolution_gate_pass,
        "visual_quality_gate_pass": main_visual_pass,
        "quality_1080p_pass": quality_1080p_pass,
        "quality_1080p_level": main_level if quality_1080p_pass else "failed",
        "visual_quality_note": visual_note,
        "clarity_score": main_metrics["clarity_score"],
        "clarity_gain": main_metrics["clarity_gain"],
        "text_clarity_score": main_metrics["text_clarity_score"],
        "text_clarity_gain": main_metrics["text_clarity_gain"],
        "edge_quality_score": main_metrics["edge_quality_score"],
        "edge_quality_gain": main_metrics["edge_quality_gain"],
        "detail_stability_score": main_metrics["detail_stability_score"],
        "face_detail_score": main_metrics["face_detail_score"],
        "face_detail_gain": main_metrics["face_detail_gain"],
        "hair_texture_score": main_metrics["hair_texture_score"],
        "hair_texture_gain": main_metrics["hair_texture_gain"],
        "fabric_texture_score": main_metrics["fabric_texture_score"],
        "fabric_texture_gain": main_metrics["fabric_texture_gain"],
        "text_edge_clean_score": main_metrics["text_edge_clean_score"],
        "small_text_readability_score": main_metrics["small_text_readability_score"],
        "before_text_region_density": main_metrics["before_text_region_density"],
        "after_text_region_density": main_metrics["after_text_region_density"],
        "text_region_density_delta": main_metrics["text_region_density_delta"],
        "v046_text_engine_active": v046_text_engine_active,
        "v046_quality_profile": "1080P+ small text readability",
        "v046_phase2_mid_frequency_active": bool(phase2_policy["phase2_material_strength"] > 0),
        "v046_phase2_mid_frequency_strength": phase2_policy["phase2_material_strength"],
        "v046_phase2_profile": "mid-frequency material candidate round2",
        "phase2_material_eligible": phase2_policy["phase2_material_eligible"],
        "phase2_material_strength": phase2_policy["phase2_material_strength"],
        "phase2_skip_reason": phase2_policy["phase2_skip_reason"],
        "phase2_texture_density": phase2_policy["phase2_texture_density"],
        "phase2_edge_density": phase2_policy["phase2_edge_density"],
        "phase2_dark_ratio": phase2_policy["phase2_dark_ratio"],
        "phase2_text_density": phase2_policy["phase2_text_density"],
        "v046_phase3_profile": "edge and halo control candidate round1",
        "phase3_edge_strength": phase3_policy["phase3_edge_strength"],
        "phase3_edge_skip_reason": phase3_policy["phase3_edge_skip_reason"],
        "edge_contrast_risk": phase3_policy["edge_contrast_risk"],
        "halo_risk": phase3_policy["halo_risk"],
        "ringing_risk": phase3_policy["ringing_risk"],
        "alpha_edge_risk": phase3_policy["alpha_edge_risk"],
        "text_edge_risk": phase3_policy["text_edge_risk"],
        "v046_phase4_profile": "low-quality fidelity candidate round1",
        "phase4_low_quality_active": phase4_policy["phase4_low_quality_active"],
        "phase4_degradation_profile": phase4_policy["phase4_degradation_profile"],
        "phase4_restoration_strength": phase4_policy["phase4_restoration_strength"],
        "phase4_skip_reason": phase4_policy["phase4_skip_reason"],
        "compression_risk_before": phase4_policy["compression_risk_before"],
        "compression_risk_after": phase4_after_probes["compression_risk"],
        "shadow_dirt_risk_before": phase4_policy["shadow_dirt_risk_before"],
        "shadow_dirt_risk_after": phase4_after_probes["shadow_dirt_risk"],
        "local_contrast_before": phase4_policy["local_contrast_before"],
        "local_contrast_after": phase4_after_probes["local_contrast"],
        "dark_detail_score": main_metrics["dark_detail_score"],
        "dark_detail_gain": main_metrics["dark_detail_gain"],
        "over_smoothing_risk": main_metrics["over_smoothing_risk"],
        "texture_loss_risk": main_metrics["texture_loss_risk"],
        "color_fidelity_score": main_metrics["color_fidelity_score"],
        "artifact_risk": main_metrics["artifact_risk"],
        "pseudo_hd_risk": main_metrics["pseudo_hd_risk"],
        "compression_damage_risk": main_metrics["compression_damage_risk"],
        "quality_before_compression": quality_before_compression,
        "quality_after_compression": quality_after_compression,
        "compression_quality_drop": compression_quality_drop,
        "compression_allowed": bool(compression["compression_allowed"] and optimized_smaller),
        "final_selection_reason": final_selection_reason,
        "final_quality_source": final_quality_source,
        "has_alpha": plan["has_alpha"],
        "has_real_alpha": plan["has_real_alpha"],
        "alpha_used": plan["alpha_used"],
        "selected_format_reason": plan["selected_format_reason"],
        "quality_gate": compression,
        "warnings": warnings,
    }

    task_report = {
        "clarity_score": main_metrics["clarity_score"],
        "text_clarity_score": main_metrics["text_clarity_score"],
        "edge_quality_score": main_metrics["edge_quality_score"],
        "structure_score": main_metrics["detail_stability_score"],
        "color_fidelity_score": main_metrics["color_fidelity_score"],
        "texture_score": round(
            (
                main_metrics["hair_texture_score"]
                + main_metrics["fabric_texture_score"]
                + main_metrics["dark_detail_score"]
            )
            / 3.0,
            4,
        ),
        "pseudo_hd_risk": main_metrics["pseudo_hd_risk"],
        "artifact_risk": main_metrics["artifact_risk"],
        "small_text_readability_score": main_metrics["small_text_readability_score"],
        "text_edge_clean_score": main_metrics["text_edge_clean_score"],
        "v046_text_engine_active": v046_text_engine_active,
        "encoding_warning": encoding_warning,
        "delivery_score": main_metrics["visual_score"],
        "warnings": warnings,
    }
    task_result = {
        "input_width": plan["input_width"],
        "input_height": plan["input_height"],
        "output_path": str(final_path),
        "output_dir": str(final_path.parent),
        "output_filename": final_path.name,
        "output_format": final_path.suffix.lower().lstrip("."),
        "output_size": final_size,
        "output_width": plan["output_width"],
        "output_height": plan["output_height"],
        "target_resolution": "1080P",
        "resize_policy": plan["resize_policy"],
        "was_upscaled": plan["was_upscaled"],
        "was_downscaled": plan["was_downscaled"],
        "processing_profile": "v0.4_quality_stable",
        "mode": mode,
        "input_path": str(input_path),
        "input_dir": str(input_path.parent),
        "input_filename": input_path.name,
        "image_type": image_type,
        "degradation_type": degradation_type,
    }

    result = {
        "version": "V0.4",
        "task_backend": "1080P background stable delivery",
        "mode": mode,
        "target_resolution": "1080P",
        "output_profile": output_profile or "delivery_1080p",
        "output_format": output_format or "auto",
        "selected_output_profile": profile,
        "selected_output_format": final_path.suffix.lower().lstrip("."),
        "final_output_type": final_output_type,
        "input_width": plan["input_width"],
        "input_height": plan["input_height"],
        "output_width": plan["output_width"],
        "output_height": plan["output_height"],
        "target_width": plan["target_width"],
        "target_height": plan["target_height"],
        "width": plan["output_width"],
        "height": plan["output_height"],
        "aspect_ratio": plan["aspect_ratio"],
        "aspect_preset": plan["aspect_preset"],
        "scale_policy": plan["scale_policy"],
        "resize_policy": plan["resize_policy"],
        "was_upscaled": plan["was_upscaled"],
        "was_downscaled": plan["was_downscaled"],
        "resolution_gate_pass": resolution_gate_pass,
        "visual_quality_gate_pass": main_visual_pass,
        "quality_1080p_pass": quality_1080p_pass,
        "quality_1080p_level": main_level if quality_1080p_pass else "failed",
        "visual_quality_note": visual_note,
        "image_type": image_type,
        "degradation_type": degradation_type,
        "input_size_bytes": input_size_bytes,
        "main_size_bytes": main_size,
        "optimized_size_bytes": optimized_size,
        "final_size_bytes": final_size,
        "file_size_ratio": file_size_ratio,
        "compression_saved_ratio": compression_saved_ratio,
        "quality_preserved": bool(quality_1080p_pass),
        "compression_note": compression_note,
        "input_hash": input_hash,
        "output_hash": final_hash,
        "hash_equal": hash_equal,
        "pixel_diff_score": round(final_diff, 6),
        "output_changed": bool(output_changed),
        "has_alpha": plan["has_alpha"],
        "has_real_alpha": plan["has_real_alpha"],
        "alpha_used": plan["alpha_used"],
        "selected_format_reason": plan["selected_format_reason"],
        "text_density": plan["text_density"],
        "quality_gate": compression,
        "debug_quality": debug_quality,
        "delivery_package": delivery_package,
        "warnings": warnings,
        "moved_formal_noise": moved_noise,
        "debug_keep_intermediate": keep_intermediate,
        "removed_intermediate": removed_intermediate,
        "debug_timing": timings,
        "task_result": task_result,
        "task_report": task_report,
        "paths": {
            "main": str(paths["main"]) if keep_intermediate else None,
            "optimized": str(paths["optimized"]) if keep_intermediate else None,
            "final": str(final_path),
            "formal_dir": str(dirs["formal"]),
            "work_dir": str(dirs["work"]),
            "debug_dir": str(dirs["debug"]),
            "test_archive_dir": str(dirs["test_archive"]),
        },
    }
    result.update(
        {
            "version": "V0.4",
            "task_backend": "1080P background stable delivery + task API",
            "image_type": image_type,
            "degradation_type": degradation_type,
            "image_type_features": plan["image_type_features"],
            "face_detail_score": main_metrics["face_detail_score"],
            "face_detail_gain": main_metrics["face_detail_gain"],
            "hair_texture_score": main_metrics["hair_texture_score"],
            "hair_texture_gain": main_metrics["hair_texture_gain"],
            "fabric_texture_score": main_metrics["fabric_texture_score"],
            "fabric_texture_gain": main_metrics["fabric_texture_gain"],
            "text_edge_clean_score": main_metrics["text_edge_clean_score"],
            "small_text_readability_score": main_metrics["small_text_readability_score"],
            "v046_text_engine_active": v046_text_engine_active,
            "v046_quality_profile": "1080P+ small text readability",
            "dark_detail_score": main_metrics["dark_detail_score"],
            "dark_detail_gain": main_metrics["dark_detail_gain"],
            "over_smoothing_risk": main_metrics["over_smoothing_risk"],
            "texture_loss_risk": main_metrics["texture_loss_risk"],
            "final_selection_reason": final_selection_reason,
        }
    )
    log_path = debug_log(result)
    result["debug_log_path"] = str(log_path)
    result["output_path"] = final_path
    result["main_output_path"] = paths["main"] if keep_intermediate else None
    result["optimized_output_path"] = paths["optimized"] if keep_intermediate else None
    result["final_output_path"] = final_path
    console_payload = dict(result)
    for key in ("output_path", "main_output_path", "optimized_output_path", "final_output_path"):
        console_payload[key] = str(console_payload[key])
    print("[V0.3.6 OutputCore]", json.dumps(console_payload, ensure_ascii=False, indent=2, default=str))
    return result
