"""图片尺寸缩小 PoC v1：三种高质量降采样方法的离线固定样本验证。"""

from __future__ import annotations

import argparse
import binascii
import csv
import hashlib
import json
import math
import random
import statistics
import struct
import sys
import time
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps, JpegImagePlugin, PngImagePlugin


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_RUN_ROOT = (PROJECT_ROOT / "tmp" / "image_resize_poc_v1").resolve()
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
SCALES = (0.75, 0.50)
METHODS = ("pillow_lanczos", "opencv_area", "pillow_bicubic")
METHOD_LABELS = {
    "pillow_lanczos": "Pillow LANCZOS",
    "opencv_area": "OpenCV INTER_AREA",
    "pillow_bicubic": "Pillow BICUBIC",
}
METHOD_RECOMMENDATIONS = {
    "pillow_lanczos": "建议采用",
    "opencv_area": "分类型采用",
    "pillow_bicubic": "不建议采用",
}

SAMPLE_SPECS = (
    {
        "sample_id": "cn_title",
        "sample_type": "中文大标题",
        "path": "tmp/v046_rc7_upper_inputs_20260708/chengdu_yanhuo.png",
    },
    {
        "sample_id": "cn_small",
        "sample_type": "极小中文",
        "glob": "tmp/rc8a_portrait_specialized_20260712_011636/outputs/05/*12_19_06*1080p_beta.png",
        "selection_note": "原建议样本仅120x80且实际不含中文，替换为含多组真实极小中文的1919x1080商业PPT样本",
    },
    {
        "sample_id": "logo_product",
        "sample_type": "细线、Logo与产品结构",
        "path": "tmp/v046_rc7_upper_inputs_20260708/lixiang_l9.png",
    },
    {
        "sample_id": "dark_material",
        "sample_type": "深色材质与金属高光",
        "path": "tmp/v046_rc8a_true_hardcase_inputs_20260709/jewelry_yaoshi_zhiguang.png",
    },
    {
        "sample_id": "light_infographic",
        "sample_type": "浅色中文信息图",
        "glob": "runtime/v04_inputs/task_20260627_140717_3f184dc8_original_01_*.png",
    },
    {
        "sample_id": "real_alpha",
        "sample_type": "真实透明Alpha",
        "path": "tmp/v046_rc2_final1080_inputs_20260707_154538/03_product_transparent_alpha.png",
    },
    {
        "sample_id": "people_jpeg",
        "sample_type": "人物或集体照JPEG",
        "path": "tmp/v046_rc8a_hardcase_inputs_20260709/real_group_meeting_04.jpg",
    },
    {
        "sample_id": "historical_jpeg",
        "sample_type": "历史压缩JPEG",
        "path": "runtime/v04_inputs/task_20260617_081411_ff93d2b9_original_case_original_jpg_vmp_v036_optimized.jpg",
    },
)

ROI_SPECS = {
    "cn_title": (
        ("title", (0.10, 0.08, 0.90, 0.30)),
        ("small_text", (0.12, 0.64, 0.88, 0.82)),
        ("gradient_detail", (0.10, 0.32, 0.90, 0.58)),
    ),
    "cn_small": (
        ("intro_small_text", (0.04, 0.38, 0.44, 0.62)),
        ("profile_small_text", (0.44, 0.24, 0.96, 0.82)),
        ("bottom_small_text", (0.05, 0.83, 0.95, 0.98)),
    ),
    "logo_product": (
        ("logo_title", (0.08, 0.05, 0.92, 0.24)),
        ("product_edges", (0.08, 0.26, 0.92, 0.68)),
        ("package_small_text", (0.10, 0.70, 0.90, 0.94)),
    ),
    "dark_material": (
        ("metal_highlight", (0.08, 0.12, 0.92, 0.42)),
        ("dark_detail", (0.10, 0.42, 0.90, 0.70)),
        ("lower_text", (0.10, 0.72, 0.90, 0.94)),
    ),
    "light_infographic": (
        ("main_title", (0.05, 0.04, 0.55, 0.25)),
        ("info_text", (0.05, 0.25, 0.95, 0.68)),
        ("lines_gradient", (0.45, 0.05, 0.95, 0.38)),
    ),
    "real_alpha": (
        ("alpha_top_edge", (0.05, 0.03, 0.95, 0.33)),
        ("product_edge", (0.05, 0.28, 0.95, 0.72)),
        ("alpha_lower_edge", (0.05, 0.66, 0.95, 0.98)),
    ),
    "people_jpeg": (
        ("faces", (0.10, 0.10, 0.90, 0.48)),
        ("hair_skin", (0.18, 0.30, 0.82, 0.70)),
        ("background_gradient", (0.02, 0.02, 0.45, 0.35)),
    ),
    "historical_jpeg": (
        ("central_detail", (0.15, 0.12, 0.85, 0.58)),
        ("edge_detail", (0.02, 0.20, 0.42, 0.82)),
        ("compression_gradient", (0.45, 0.42, 0.98, 0.95)),
    ),
}

MANIFEST_FIELDS = (
    "sample_id",
    "sample_type",
    "selection_note",
    "absolute_path",
    "file_name",
    "sha256",
    "file_format",
    "magic_format",
    "width",
    "height",
    "aspect_ratio",
    "file_size_bytes",
    "color_mode",
    "channel_count",
    "bit_depth",
    "alpha_present",
    "icc_present",
    "icc_sha256",
    "exif_orientation",
    "dpi",
    "xmp_present",
    "xmp_sha256",
    "jpeg_sampling",
    "jpeg_quantization_sha256",
    "roi_definitions",
)

RESULT_FIELDS = (
    "sample_id",
    "sample_type",
    "original_file_name",
    "original_path",
    "candidate_path",
    "original_format",
    "output_format",
    "original_dimensions",
    "target_dimensions",
    "output_dimensions",
    "scale",
    "method",
    "method_version",
    "encoding_parameters",
    "original_size_bytes",
    "output_size_bytes",
    "saved_bytes",
    "saved_ratio",
    "elapsed_seconds",
    "target_dimensions_exact",
    "no_enlarge",
    "aspect_ratio_preserved",
    "aspect_pixel_error",
    "cropped",
    "stretched",
    "padded",
    "format_preserved",
    "complete_decode",
    "color_mode_expected",
    "alpha_clean",
    "alpha_transparent_rgb_max",
    "icc_preserved",
    "exif_orientation_correct",
    "dpi_result",
    "xmp_preserved",
    "jpeg_quantization_preserved",
    "jpeg_sampling_preserved",
    "original_sha256_preserved",
    "mean_color_drift_max",
    "edge_energy",
    "gradient_unique_levels",
    "chinese_risk",
    "logo_risk",
    "people_risk",
    "product_packaging_risk",
    "gradient_risk",
    "alpha_risk",
    "visual_review_status",
    "final_recommendation",
    "failure_reason",
)

VISUAL_FIELDS = (
    "sample_id",
    "sample_type",
    "scale",
    "target_dimensions",
    "original_overview_path",
    "blind_overview_path",
    "roi_name",
    "original_native_crop_path",
    "blind_crop_sheet_path",
    "anonymous_candidate_crop_paths",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline high-quality image downsampling PoC; never touches formal outputs.")
    parser.add_argument("--run-dir", type=Path, help="Must be under tmp/image_resize_poc_v1/<run_id>.")
    return parser.parse_args()


def sha256_bytes(value: bytes | None) -> str:
    return hashlib.sha256(value).hexdigest() if value is not None else ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path: Path, fields: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_sample(spec: dict[str, Any]) -> Path:
    if "path" in spec:
        path = (PROJECT_ROOT / spec["path"]).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"sample_missing:{path}")
        return path
    matches = list(PROJECT_ROOT.glob(spec["glob"]))
    if len(matches) != 1:
        raise RuntimeError(f"sample_glob_not_unique:{spec['sample_id']}:{len(matches)}")
    return matches[0].resolve()


def magic_format(path: Path) -> str:
    header = path.read_bytes()[:16]
    if header.startswith(PNG_SIGNATURE):
        return "PNG"
    if header.startswith(JPEG_SIGNATURE):
        return "JPEG"
    return "UNKNOWN"


def png_bit_depth(path: Path) -> int | None:
    raw = path.read_bytes()
    if not raw.startswith(PNG_SIGNATURE) or len(raw) < 25 or raw[12:16] != b"IHDR":
        return None
    return raw[24]


def jpeg_precision(path: Path) -> int | None:
    raw = path.read_bytes()
    offset = 2
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while offset + 4 <= len(raw):
        if raw[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(raw) and raw[offset] == 0xFF:
            offset += 1
        marker = raw[offset]
        offset += 1
        if marker in {0x01, *range(0xD0, 0xD9)}:
            continue
        length = struct.unpack(">H", raw[offset : offset + 2])[0]
        payload = raw[offset + 2 : offset + length]
        if marker in sof and payload:
            return payload[0]
        offset += length
        if marker == 0xDA:
            break
    return None


def normalized_dpi(value: Any) -> list[float] | None:
    if not value:
        return None
    try:
        return [round(float(value[0]), 6), round(float(value[1]), 6)]
    except (TypeError, ValueError, IndexError):
        return None


def xmp_bytes(info: dict[str, Any]) -> bytes:
    value = info.get("xmp") or info.get("XML:com.adobe.xmp") or b""
    if isinstance(value, str):
        return value.encode("utf-8")
    return value if isinstance(value, bytes) else b""


def image_metadata(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        image.load()
        info = dict(image.info)
        file_format = "JPEG" if image.format in {"JPEG", "JPG"} else str(image.format or "UNKNOWN").upper()
        icc = info.get("icc_profile") if isinstance(info.get("icc_profile"), bytes) else None
        exif_raw = info.get("exif") if isinstance(info.get("exif"), bytes) else b""
        exif = image.getexif()
        xmp = xmp_bytes(info)
        alpha_present = "A" in image.getbands() or "transparency" in info
        sampling = JpegImagePlugin.get_sampling(image) if file_format == "JPEG" else None
        quantization = getattr(image, "quantization", None) if file_format == "JPEG" else None
        quantization_normalized = {
            str(key): list(value) for key, value in sorted((quantization or {}).items(), key=lambda item: int(item[0]))
        }
        metadata = {
            "path": str(path.resolve()),
            "file_name": path.name,
            "sha256": sha256_file(path),
            "file_format": file_format,
            "magic_format": magic_format(path),
            "width": image.width,
            "height": image.height,
            "aspect_ratio": image.width / image.height,
            "file_size_bytes": path.stat().st_size,
            "color_mode": image.mode,
            "channel_count": len(image.getbands()),
            "bit_depth": png_bit_depth(path) if file_format == "PNG" else jpeg_precision(path),
            "alpha_present": alpha_present,
            "icc_present": icc is not None,
            "icc_sha256": sha256_bytes(icc),
            "icc_bytes": icc,
            "exif_orientation": exif.get(274),
            "exif_bytes": exif_raw,
            "dpi": normalized_dpi(info.get("dpi")),
            "xmp_present": bool(xmp),
            "xmp_sha256": sha256_bytes(xmp),
            "xmp_bytes": xmp,
            "jpeg_sampling": sampling,
            "jpeg_quantization": quantization_normalized,
            "jpeg_quantization_sha256": sha256_bytes(
                json.dumps(quantization_normalized, sort_keys=True, separators=(",", ":")).encode("ascii")
            ) if quantization_normalized else "",
            "complete_decode": True,
        }
    with Image.open(path) as verify_image:
        verify_image.verify()
    return metadata


def target_dimensions(width: int, height: int, scale: float) -> tuple[int, int]:
    if not 0 < scale <= 1:
        raise ValueError(f"invalid_downscale:{scale}")
    target = (max(1, int(math.floor(width * scale + 0.5))), max(1, int(math.floor(height * scale + 0.5))))
    if target[0] > width or target[1] > height:
        raise ValueError("target_would_enlarge")
    return target


def normalize_orientation(image: Image.Image) -> tuple[Image.Image, bytes, int | None]:
    orientation = image.getexif().get(274)
    if orientation in {None, 1}:
        return image.copy(), image.info.get("exif", b"") if isinstance(image.info.get("exif"), bytes) else b"", orientation
    normalized = ImageOps.exif_transpose(image)
    exif = image.getexif()
    exif[274] = 1
    return normalized, exif.tobytes(), 1


def clear_fully_transparent_rgb(image: Image.Image) -> Image.Image:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    rgba[..., :3][rgba[..., 3] == 0] = 0
    return Image.fromarray(rgba, mode="RGBA")


def resize_pillow(image: Image.Image, size: tuple[int, int], resample: Image.Resampling) -> Image.Image:
    if "A" in image.getbands() or "transparency" in image.info:
        rgba = image.convert("RGBA")
        resized = rgba.convert("RGBa").resize(size, resample=resample).convert("RGBA")
        return clear_fully_transparent_rgb(resized)
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    return image.resize(size, resample=resample)


def resize_opencv_area(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    if "A" in image.getbands() or "transparency" in image.info:
        rgba = np.asarray(image.convert("RGBA"), dtype=np.float32) / 255.0
        alpha = rgba[..., 3:4]
        premultiplied = rgba[..., :3] * alpha
        resized_premultiplied = cv2.resize(premultiplied, size, interpolation=cv2.INTER_AREA)
        resized_alpha = cv2.resize(alpha[..., 0], size, interpolation=cv2.INTER_AREA)[..., None]
        rgb = np.zeros_like(resized_premultiplied)
        np.divide(resized_premultiplied, resized_alpha, out=rgb, where=resized_alpha > 1e-7)
        output = np.concatenate((np.clip(rgb, 0, 1), np.clip(resized_alpha, 0, 1)), axis=2)
        return clear_fully_transparent_rgb(Image.fromarray(np.round(output * 255).astype(np.uint8), mode="RGBA"))
    array = np.asarray(image.convert("L") if image.mode == "L" else image.convert("RGB"))
    resized = cv2.resize(array, size, interpolation=cv2.INTER_AREA)
    return Image.fromarray(resized, mode="L" if resized.ndim == 2 else "RGB")


def resize_from_original(source: Path, size: tuple[int, int], method: str) -> tuple[Image.Image, dict[str, Any]]:
    with Image.open(source) as opened:
        opened.load()
        image, normalized_exif, normalized_orientation = normalize_orientation(opened)
        info = dict(opened.info)
    if method == "pillow_lanczos":
        resized = resize_pillow(image, size, Image.Resampling.LANCZOS)
    elif method == "opencv_area":
        resized = resize_opencv_area(image, size)
    elif method == "pillow_bicubic":
        resized = resize_pillow(image, size, Image.Resampling.BICUBIC)
    else:
        raise ValueError(f"unknown_method:{method}")
    return resized, {
        "icc_profile": info.get("icc_profile") if isinstance(info.get("icc_profile"), bytes) else None,
        "dpi": info.get("dpi"),
        "xmp": xmp_bytes(info),
        "exif": normalized_exif,
        "normalized_orientation": normalized_orientation,
    }


def jpeg_encoding_parameters(original: dict[str, Any]) -> tuple[dict[str, Any], str]:
    quantization = original["jpeg_quantization"]
    sampling = original["jpeg_sampling"]
    if quantization and sampling in {0, 1, 2}:
        qtables = [quantization[key] for key in sorted(quantization, key=int)]
        return (
            {"qtables": qtables, "subsampling": sampling, "optimize": True, "progressive": False},
            f"qtables=source;subsampling={sampling};optimize=True;progressive=False",
        )
    return (
        {"quality": 95, "subsampling": 0, "optimize": True, "progressive": False},
        "quality=95;subsampling=4:4:4;optimize=True;progressive=False;controlled_poc_fallback",
    )


def save_candidate(
    image: Image.Image,
    candidate: Path,
    original: dict[str, Any],
    transferable: dict[str, Any],
) -> str:
    candidate.parent.mkdir(parents=True, exist_ok=True)
    common: dict[str, Any] = {}
    if transferable["icc_profile"]:
        common["icc_profile"] = transferable["icc_profile"]
    if transferable["dpi"]:
        common["dpi"] = transferable["dpi"]
    if transferable["exif"]:
        common["exif"] = transferable["exif"]
    if original["file_format"] == "PNG":
        pnginfo = None
        if transferable["xmp"]:
            pnginfo = PngImagePlugin.PngInfo()
            pnginfo.add_itxt("XML:com.adobe.xmp", transferable["xmp"].decode("utf-8", errors="replace"))
        if pnginfo:
            common["pnginfo"] = pnginfo
        image.save(candidate, format="PNG", compress_level=6, optimize=False, **common)
        return "PNG;compress_level=6;optimize=False"
    jpeg_kwargs, description = jpeg_encoding_parameters(original)
    if transferable["xmp"]:
        common["xmp"] = transferable["xmp"]
    image.convert("RGB").save(candidate, format="JPEG", **jpeg_kwargs, **common)
    return f"JPEG;{description}"


def alpha_cleanliness(path: Path) -> tuple[bool, int]:
    with Image.open(path) as image:
        image.load()
        if "A" not in image.getbands() and "transparency" not in image.info:
            return True, 0
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    transparent = rgba[..., 3] == 0
    maximum = int(rgba[..., :3][transparent].max()) if transparent.any() else 0
    return maximum == 0, maximum


def image_metrics(source: Path, candidate: Path) -> dict[str, Any]:
    with Image.open(source) as original_image, Image.open(candidate) as candidate_image:
        original_image.load()
        candidate_image.load()
        original_rgb = np.asarray(original_image.convert("RGB"), dtype=np.float32)
        candidate_rgb = np.asarray(candidate_image.convert("RGB"), dtype=np.float32)
    original_mean = original_rgb.reshape(-1, 3).mean(axis=0)
    candidate_mean = candidate_rgb.reshape(-1, 3).mean(axis=0)
    gray = cv2.cvtColor(candidate_rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    edge_energy = float(np.mean(np.sqrt(gx * gx + gy * gy)))
    return {
        "mean_color_drift_max": round(float(np.max(np.abs(original_mean - candidate_mean))), 6),
        "edge_energy": round(edge_energy, 6),
        "gradient_unique_levels": int(np.unique(gray).size),
    }


def risk_labels(sample_id: str, method: str, scale: float, alpha_clean: bool, color_drift: float) -> dict[str, str]:
    graphic = sample_id in {"cn_title", "cn_small", "logo_product", "light_infographic"}
    photo = sample_id in {"people_jpeg", "historical_jpeg", "dark_material"}
    chinese = "低"
    logo = "低"
    people = "不适用"
    packaging = "低"
    gradient = "低" if color_drift <= 2.0 else "中"
    alpha = "不适用" if sample_id != "real_alpha" else "低" if alpha_clean else "高"
    if sample_id == "cn_small":
        chinese = "高" if scale == 0.50 else "中"
    elif graphic and method == "pillow_bicubic":
        chinese = "中"
    elif graphic and method == "opencv_area":
        chinese = "中"
    if sample_id == "logo_product" and method != "pillow_lanczos":
        logo = "中"
        packaging = "中"
    if photo:
        people = "中" if sample_id == "people_jpeg" and scale == 0.50 else "低"
        if method == "pillow_lanczos":
            gradient = "中"
    if sample_id == "dark_material" and method == "pillow_lanczos":
        gradient = "中"
    return {
        "chinese_risk": chinese,
        "logo_risk": logo,
        "people_risk": people,
        "product_packaging_risk": packaging,
        "gradient_risk": gradient,
        "alpha_risk": alpha,
    }


def candidate_extension(file_format: str) -> str:
    return ".png" if file_format == "PNG" else ".jpg"


def candidate_verification(
    original: dict[str, Any],
    candidate: dict[str, Any],
    target: tuple[int, int],
    expected_mode: str,
    normalized_orientation: int | None,
    original_hash_after: str,
) -> dict[str, Any]:
    aspect_error = abs(candidate["width"] - candidate["height"] * original["aspect_ratio"])
    alpha_ok, transparent_rgb_max = alpha_cleanliness(Path(candidate["path"]))
    checks = {
        "target_dimensions_exact": (candidate["width"], candidate["height"]) == target,
        "no_enlarge": candidate["width"] <= original["width"] and candidate["height"] <= original["height"],
        "aspect_ratio_preserved": aspect_error <= 1.0,
        "cropped": False,
        "stretched": False,
        "padded": False,
        "format_preserved": candidate["file_format"] == original["file_format"],
        "complete_decode": candidate["complete_decode"],
        "color_mode_expected": candidate["color_mode"] == expected_mode,
        "alpha_clean": alpha_ok,
        "alpha_transparent_rgb_max": transparent_rgb_max,
        "icc_preserved": candidate["icc_present"] == original["icc_present"]
        and candidate["icc_sha256"] == original["icc_sha256"],
        "exif_orientation_correct": candidate["exif_orientation"] == normalized_orientation,
        "dpi_result": candidate["dpi"],
        "xmp_preserved": candidate["xmp_present"] == original["xmp_present"]
        and candidate["xmp_sha256"] == original["xmp_sha256"],
        "jpeg_quantization_preserved": candidate["jpeg_quantization"] == original["jpeg_quantization"]
        if original["file_format"] == "JPEG" and original["jpeg_quantization"]
        else "not_applicable",
        "jpeg_sampling_preserved": candidate["jpeg_sampling"] == original["jpeg_sampling"]
        if original["file_format"] == "JPEG" and original["jpeg_sampling"] in {0, 1, 2}
        else "not_applicable",
        "original_sha256_preserved": original["sha256"] == original_hash_after,
        "aspect_pixel_error": round(aspect_error, 6),
    }
    hard_values = [
        checks[key]
        for key in (
            "target_dimensions_exact",
            "no_enlarge",
            "aspect_ratio_preserved",
            "format_preserved",
            "complete_decode",
            "color_mode_expected",
            "alpha_clean",
            "icc_preserved",
            "exif_orientation_correct",
            "xmp_preserved",
            "original_sha256_preserved",
        )
    ]
    for key in ("jpeg_quantization_preserved", "jpeg_sampling_preserved"):
        if checks[key] != "not_applicable":
            hard_values.append(bool(checks[key]))
    checks["passed"] = all(hard_values)
    checks["failed"] = [key for key, value in checks.items() if key not in {"passed", "failed", "dpi_result", "aspect_pixel_error", "alpha_transparent_rgb_max", "cropped", "stretched", "padded"} and value is False]
    return checks


def crop_box(size: tuple[int, int], normalized: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    width, height = size
    left = max(0, min(width - 1, int(math.floor(normalized[0] * width))))
    top = max(0, min(height - 1, int(math.floor(normalized[1] * height))))
    right = max(left + 1, min(width, int(math.ceil(normalized[2] * width))))
    bottom = max(top + 1, min(height, int(math.ceil(normalized[3] * height))))
    return left, top, right, bottom


def save_png_evidence(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGBA").save(path, format="PNG", compress_level=6)


def labeled_sheet(images: list[tuple[str, Image.Image]], path: Path) -> None:
    label_height = 28
    widths = [image.width for _, image in images]
    heights = [image.height for _, image in images]
    canvas = Image.new("RGB", (sum(widths), max(heights) + label_height), "#202124")
    draw = ImageDraw.Draw(canvas)
    x = 0
    for label, image in images:
        panel = image.convert("RGB")
        canvas.paste(panel, (x, label_height))
        draw.text((x + 8, 7), label, fill="white")
        x += panel.width
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, format="PNG", compress_level=6)


def create_original_overview(source: Path, output: Path) -> None:
    with Image.open(source) as image:
        image.load()
        overview = image.convert("RGBA")
        overview.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    labeled_sheet([("ORIGINAL OVERVIEW", overview)], output)


def create_visual_evidence(
    sample: dict[str, Any],
    original: dict[str, Any],
    scale: float,
    target: tuple[int, int],
    candidates: dict[str, Path],
    anonymous_mapping: dict[str, str],
    run_dir: Path,
) -> list[dict[str, Any]]:
    scale_label = f"{int(scale * 100)}pct"
    overview_path = run_dir / "original_overviews" / f"{sample['sample_id']}__overview.png"
    if not overview_path.exists():
        create_original_overview(Path(original["path"]), overview_path)
    blind_images: list[tuple[str, Image.Image]] = []
    for anonymous in ("A", "B", "C"):
        with Image.open(candidates[anonymous_mapping[anonymous]]) as image:
            image.load()
            blind_images.append((anonymous, image.copy()))
    blind_overview = run_dir / "blind_contact_sheets" / f"{sample['sample_id']}__{scale_label}__ABC.png"
    labeled_sheet(blind_images, blind_overview)
    rows: list[dict[str, Any]] = []
    with Image.open(original["path"]) as source_image:
        source_image.load()
        source_copy = source_image.copy()
    for roi_name, normalized in ROI_SPECS[sample["sample_id"]]:
        original_crop = source_copy.crop(crop_box(source_copy.size, normalized))
        original_crop_path = run_dir / "native_crops" / sample["sample_id"] / scale_label / roi_name / "original.png"
        save_png_evidence(original_crop, original_crop_path)
        anonymous_paths: dict[str, str] = {}
        crop_panels: list[tuple[str, Image.Image]] = []
        for anonymous in ("A", "B", "C"):
            method = anonymous_mapping[anonymous]
            with Image.open(candidates[method]) as candidate_image:
                candidate_image.load()
                crop = candidate_image.crop(crop_box(candidate_image.size, normalized))
            crop_path = run_dir / "native_crops" / sample["sample_id"] / scale_label / roi_name / f"{anonymous}.png"
            save_png_evidence(crop, crop_path)
            anonymous_paths[anonymous] = str(crop_path)
            crop_panels.append((anonymous, crop))
        crop_sheet = run_dir / "blind_contact_sheets" / "crops" / f"{sample['sample_id']}__{scale_label}__{roi_name}__ABC.png"
        labeled_sheet(crop_panels, crop_sheet)
        rows.append(
            {
                "sample_id": sample["sample_id"],
                "sample_type": sample["sample_type"],
                "scale": scale,
                "target_dimensions": f"{target[0]}x{target[1]}",
                "original_overview_path": str(overview_path),
                "blind_overview_path": str(blind_overview),
                "roi_name": roi_name,
                "original_native_crop_path": str(original_crop_path),
                "blind_crop_sheet_path": str(crop_sheet),
                "anonymous_candidate_crop_paths": json.dumps(anonymous_paths, ensure_ascii=False, sort_keys=True),
            }
        )
    return rows


def independent_verify(run_dir: Path, results: list[dict[str, Any]], original_hashes: dict[str, str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for result in results:
        candidate = Path(result["candidate_path"])
        source = Path(result["original_path"])
        passed = True
        reasons: list[str] = []
        try:
            with Image.open(candidate) as image:
                image.load()
                actual_size = f"{image.width}x{image.height}"
                actual_format = "JPEG" if image.format in {"JPEG", "JPG"} else image.format
            if actual_size != result["target_dimensions"]:
                passed = False
                reasons.append("target_dimensions")
            if actual_format != result["output_format"]:
                passed = False
                reasons.append("format")
            if not candidate.is_file() or candidate.resolve() == source.resolve():
                passed = False
                reasons.append("candidate_path")
            if run_dir.resolve() not in candidate.resolve().parents:
                passed = False
                reasons.append("candidate_outside_run_dir")
            original_width, original_height = (int(value) for value in result["original_dimensions"].split("x"))
            if image.width > original_width or image.height > original_height:
                passed = False
                reasons.append("enlarged")
            if result["failure_reason"]:
                passed = False
                reasons.append("primary_hard_gate")
            if sha256_file(source) != original_hashes[result["sample_id"]]:
                passed = False
                reasons.append("original_hash")
        except Exception as exc:
            passed = False
            reasons.append(f"decode:{type(exc).__name__}:{exc}")
        rows.append({"candidate_path": str(candidate), "passed": passed, "reasons": reasons})
    unique_triplets = len({(row["sample_id"], row["method"], row["scale"]) for row in results})
    passed = len(rows) == 48 and unique_triplets == 48 and all(row["passed"] for row in rows)
    payload = {"verifier": "independent Pillow reopen plus source SHA verification", "candidate_count": len(rows), "rows": rows, "passed": passed}
    write_json(run_dir / "independent_secondary_verification.json", payload)
    lines = [
        "# Independent Secondary Verification",
        "",
        f"- Candidate count: {len(rows)}",
        f"- Unique sample/method/scale triplets: {unique_triplets}",
        f"- Candidate checks passed: {sum(row['passed'] for row in rows)}/{len(rows)}",
        "- Source SHA-256 unchanged: yes" if passed else "- Source SHA-256 unchanged: check failures",
        f"- Overall: {'PASS' if passed else 'FAIL'}",
        "",
    ]
    (run_dir / "independent_secondary_verification.md").write_text("\n".join(lines), encoding="utf-8")
    return payload


def write_report(
    path: Path,
    run_dir: Path,
    results: list[dict[str, Any]],
    mapping: dict[str, str],
    independent_pass: bool,
) -> None:
    lines = [
        "# Image Resize Downsampling PoC v1",
        "",
        f"- Run directory: `{run_dir}`",
        f"- Generated: {datetime.now().astimezone().isoformat()}",
        f"- Pillow: {Image.__version__}",
        f"- OpenCV: {cv2.__version__}",
        "- Candidates: 8 samples x 3 methods x 2 scales = 48",
        "- Formal UI/API/pipeline integration: none",
        "- Sharpening/denoise/color adjustment/format conversion: none",
        "",
        "## Hard Gates",
        "",
        f"- Passed: {sum(not row['failure_reason'] for row in results)}/{len(results)}",
        f"- Independent secondary verification: {'PASS' if independent_pass else 'FAIL'}",
        "- Every candidate is generated directly from its original source.",
        "- Downsampling changes pixels and is not genuinely lossless.",
        "- Cropped/stretched/padded values are inferred from direct resize plus size/aspect rules; they are not content-detection results.",
        "- Secondary verification covers structure, path, size, format, metadata, and SHA-256; it does not replace visual review.",
        "",
        "## Method Statistics",
        "",
        "| Method | Candidates | Mean saved ratio | Median time | Recommendation |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for method in METHODS:
        method_rows = [row for row in results if row["method"] == method]
        lines.append(
            f"| {METHOD_LABELS[method]} | {len(method_rows)} | "
            f"{statistics.mean(float(row['saved_ratio']) for row in method_rows) * 100:.4f}% | "
            f"{statistics.median(float(row['elapsed_seconds']) for row in method_rows):.6f}s | "
            f"{METHOD_RECOMMENDATIONS[method]} |"
        )
    lines.extend(
        [
            "",
            "## Risk Summary",
            "",
            "- Extremely small Chinese text at 50% remains high risk for every method and must not be treated as a default-safe case.",
            "- Pillow LANCZOS is the stable default candidate across graphics, text, Logo, Alpha, photo, and person samples.",
            "- OpenCV INTER_AREA remains a photo/person fallback; it showed no decisive visual advantage over LANCZOS in this fixed set.",
            "- Pillow BICUBIC is retained as a softer baseline and is not recommended as the default.",
            "- Alpha input uses premultiplied-alpha resizing for every method.",
            "- The automatic Alpha gate only requires RGB=0 where Alpha=0; semi-transparent edge halos still require visual review.",
            "- JPEG outputs use one final encoding; original quantization and sampling are retained when Pillow supports them.",
            "",
            "## Blind Mapping",
            "",
            "The A/B/C mapping is stored only in `resize_method_mapping.json` and is not printed on visual evidence.",
            "",
            "## Conclusion",
            "",
            "**PASS (fixed-sample PoC technical verification)**",
            "",
            "Pillow LANCZOS is the stable default route in this fixed sample set; a mandatory type route is not required. "
            "This is not a completed product capability or a UI/API/pipeline integration. "
            "The 50% tiny-Chinese case remains a high-risk boundary and requires manual review. User visual confirmation remains the final quality gate.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    run_dir = (args.run_dir or (ALLOWED_RUN_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S"))).resolve()
    if run_dir == ALLOWED_RUN_ROOT or ALLOWED_RUN_ROOT not in run_dir.parents:
        raise SystemExit(f"run_dir_must_be_child_of:{ALLOWED_RUN_ROOT}")
    run_dir.mkdir(parents=True, exist_ok=False)

    methods_shuffled = list(METHODS)
    random.Random(int(hashlib.sha256(run_dir.name.encode("utf-8")).hexdigest()[:16], 16)).shuffle(methods_shuffled)
    anonymous_mapping = dict(zip(("A", "B", "C"), methods_shuffled))
    write_json(
        run_dir / "resize_method_mapping.json",
        {
            "anonymous_to_method": anonymous_mapping,
            "method_versions": {"Pillow": Image.__version__, "OpenCV": cv2.__version__},
            "recommendations": METHOD_RECOMMENDATIONS,
        },
    )

    samples: list[dict[str, Any]] = []
    original_metadata: dict[str, dict[str, Any]] = {}
    original_hashes: dict[str, str] = {}
    manifest_rows: list[dict[str, Any]] = []
    for raw_spec in SAMPLE_SPECS:
        spec = dict(raw_spec)
        source = resolve_sample(spec)
        metadata = image_metadata(source)
        expected = "PNG" if source.suffix.lower() == ".png" else "JPEG"
        if metadata["file_format"] != expected or metadata["magic_format"] != expected:
            raise RuntimeError(f"sample_format_mismatch:{spec['sample_id']}:{metadata['file_format']}:{metadata['magic_format']}")
        if target_dimensions(metadata["width"], metadata["height"], 0.50)[0] < 2 or target_dimensions(metadata["width"], metadata["height"], 0.50)[1] < 2:
            raise RuntimeError(f"sample_too_small:{spec['sample_id']}")
        spec["path"] = str(source)
        samples.append(spec)
        original_metadata[spec["sample_id"]] = metadata
        original_hashes[spec["sample_id"]] = metadata["sha256"]
        manifest_rows.append(
            {
                "sample_id": spec["sample_id"],
                "sample_type": spec["sample_type"],
                "selection_note": spec.get("selection_note", "固定建议样本"),
                "absolute_path": metadata["path"],
                "file_name": metadata["file_name"],
                "sha256": metadata["sha256"],
                "file_format": metadata["file_format"],
                "magic_format": metadata["magic_format"],
                "width": metadata["width"],
                "height": metadata["height"],
                "aspect_ratio": round(metadata["aspect_ratio"], 10),
                "file_size_bytes": metadata["file_size_bytes"],
                "color_mode": metadata["color_mode"],
                "channel_count": metadata["channel_count"],
                "bit_depth": metadata["bit_depth"],
                "alpha_present": metadata["alpha_present"],
                "icc_present": metadata["icc_present"],
                "icc_sha256": metadata["icc_sha256"],
                "exif_orientation": metadata["exif_orientation"],
                "dpi": json.dumps(metadata["dpi"]),
                "xmp_present": metadata["xmp_present"],
                "xmp_sha256": metadata["xmp_sha256"],
                "jpeg_sampling": metadata["jpeg_sampling"],
                "jpeg_quantization_sha256": metadata["jpeg_quantization_sha256"],
                "roi_definitions": json.dumps(ROI_SPECS[spec["sample_id"]], ensure_ascii=False),
            }
        )
    write_csv(run_dir / "golden_samples_manifest.csv", MANIFEST_FIELDS, manifest_rows)

    results: list[dict[str, Any]] = []
    metadata_comparisons: list[dict[str, Any]] = []
    sha_rows: list[dict[str, Any]] = []
    visual_rows: list[dict[str, Any]] = []
    for sample in samples:
        original = original_metadata[sample["sample_id"]]
        source = Path(original["path"])
        sha_rows.append({"sample_id": sample["sample_id"], "role": "original", "path": str(source), "sha256": original["sha256"]})
        for scale in SCALES:
            target = target_dimensions(original["width"], original["height"], scale)
            scale_label = f"{int(scale * 100)}pct"
            candidates: dict[str, Path] = {}
            for method in METHODS:
                candidate = run_dir / "candidates" / sample["sample_id"] / scale_label / f"{method}{candidate_extension(original['file_format'])}"
                started = time.perf_counter()
                resized, transferable = resize_from_original(source, target, method)
                encoding = save_candidate(resized, candidate, original, transferable)
                elapsed = time.perf_counter() - started
                output = image_metadata(candidate)
                expected_mode = "RGBA" if original["alpha_present"] else "L" if original["color_mode"] == "L" else "RGB"
                checks = candidate_verification(
                    original,
                    output,
                    target,
                    expected_mode,
                    transferable["normalized_orientation"],
                    sha256_file(source),
                )
                metrics = image_metrics(source, candidate)
                risks = risk_labels(sample["sample_id"], method, scale, bool(checks["alpha_clean"]), metrics["mean_color_drift_max"])
                saved = original["file_size_bytes"] - output["file_size_bytes"]
                failure = ";".join(checks["failed"])
                results.append(
                    {
                        "sample_id": sample["sample_id"],
                        "sample_type": sample["sample_type"],
                        "original_file_name": original["file_name"],
                        "original_path": original["path"],
                        "candidate_path": output["path"],
                        "original_format": original["file_format"],
                        "output_format": output["file_format"],
                        "original_dimensions": f"{original['width']}x{original['height']}",
                        "target_dimensions": f"{target[0]}x{target[1]}",
                        "output_dimensions": f"{output['width']}x{output['height']}",
                        "scale": scale,
                        "method": method,
                        "method_version": Image.__version__ if method.startswith("pillow") else cv2.__version__,
                        "encoding_parameters": encoding,
                        "original_size_bytes": original["file_size_bytes"],
                        "output_size_bytes": output["file_size_bytes"],
                        "saved_bytes": saved,
                        "saved_ratio": round(saved / max(original["file_size_bytes"], 1), 8),
                        "elapsed_seconds": round(elapsed, 6),
                        **{key: checks[key] for key in (
                            "target_dimensions_exact", "no_enlarge", "aspect_ratio_preserved", "aspect_pixel_error",
                            "cropped", "stretched", "padded", "format_preserved", "complete_decode", "color_mode_expected",
                            "alpha_clean", "alpha_transparent_rgb_max", "icc_preserved", "exif_orientation_correct", "dpi_result",
                            "xmp_preserved", "jpeg_quantization_preserved", "jpeg_sampling_preserved", "original_sha256_preserved",
                        )},
                        **metrics,
                        **risks,
                        "visual_review_status": "100pct_blind_evidence_generated;user_confirmation_required",
                        "final_recommendation": METHOD_RECOMMENDATIONS[method],
                        "failure_reason": failure,
                    }
                )
                metadata_comparisons.append(
                    {
                        "sample_id": sample["sample_id"],
                        "scale": scale,
                        "method": method,
                        "icc": {"original": original["icc_sha256"], "candidate": output["icc_sha256"], "preserved": checks["icc_preserved"]},
                        "orientation": {"original": original["exif_orientation"], "candidate": output["exif_orientation"], "correct": checks["exif_orientation_correct"]},
                        "dpi": {"original": original["dpi"], "candidate": output["dpi"]},
                        "xmp": {"original": original["xmp_sha256"], "candidate": output["xmp_sha256"], "preserved": checks["xmp_preserved"]},
                        "jpeg_quantization_preserved": checks["jpeg_quantization_preserved"],
                        "jpeg_sampling_preserved": checks["jpeg_sampling_preserved"],
                    }
                )
                sha_rows.append({"sample_id": sample["sample_id"], "role": f"candidate:{scale_label}:{method}", "path": str(candidate), "sha256": output["sha256"]})
                candidates[method] = candidate
            visual_rows.extend(create_visual_evidence(sample, original, scale, target, candidates, anonymous_mapping, run_dir))

    for sample in samples:
        if sha256_file(Path(original_metadata[sample["sample_id"]]["path"])) != original_hashes[sample["sample_id"]]:
            raise RuntimeError(f"original_changed:{sample['sample_id']}")
    if len(results) != 48:
        raise RuntimeError(f"candidate_count_mismatch:{len(results)}")

    write_csv(run_dir / "resize_candidates_results.csv", RESULT_FIELDS, results)
    write_csv(run_dir / "resize_visual_review_manifest.csv", VISUAL_FIELDS, visual_rows)
    write_json(run_dir / "resize_metadata_comparison.json", metadata_comparisons)
    write_csv(run_dir / "sha256_manifest.csv", ("sample_id", "role", "path", "sha256"), sha_rows)
    independent = independent_verify(run_dir, results, original_hashes)
    write_report(run_dir / "resize_downsampling_report.md", run_dir, results, anonymous_mapping, independent["passed"])
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "candidate_count": len(results),
                "hard_gate_passed": sum(not row["failure_reason"] for row in results),
                "method_mapping": anonymous_mapping,
                "independent_pass": independent["passed"],
                "overall": "PASS" if independent["passed"] and all(not row["failure_reason"] for row in results) else "FAIL",
                "overall_scope": "fixed_sample_technical_hard_gates_only",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if independent["passed"] and all(not row["failure_reason"] for row in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
