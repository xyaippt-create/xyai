from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from engine.algorithms.color_fidelity import lock_color_to_reference
from engine.algorithms.edge_safe_enhance import enhance_true_edges
from engine.algorithms.highlight_protection import compress_clipped_highlights, protect_highlights
from engine.algorithms.text_clarity import enhance_text_regions
from engine.io import read_image
from runtime.logger import logs_dir


TARGET_LONG_EDGE = 1920
TARGET_16_9 = (1920, 1080)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_v035_output_path(source: Path, output_dir: Path, output_format: str) -> Path:
    suffix = output_format.lower().lstrip(".")
    return output_dir / f"{source.stem}_vmp_v035_1080p.{suffix}"


def target_1080p_size(width: int, height: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        return TARGET_16_9
    aspect = width / max(height, 1)
    if abs(aspect - (16 / 9)) <= 0.025:
        return TARGET_16_9
    scale = TARGET_LONG_EDGE / max(width, height)
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def _resize_to_1080p(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    target_width, target_height = target_1080p_size(width, height)
    interpolation = cv2.INTER_LANCZOS4 if target_width >= width or target_height >= height else cv2.INTER_AREA
    return cv2.resize(image, (target_width, target_height), interpolation=interpolation)


def _mid_frequency_detail(image: np.ndarray, strength: float = 0.16) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype("float32")
    luma = lab[:, :, 0]
    base = cv2.GaussianBlur(luma, (0, 0), 1.15)
    detail = luma - base
    detail = np.sign(detail) * np.minimum(np.maximum(np.abs(detail) - 0.9, 0.0), 9.0)
    lab[:, :, 0] = np.clip(luma + detail * strength, 0, 255)
    return cv2.cvtColor(lab.astype("uint8"), cv2.COLOR_LAB2BGR)


def _light_clean(image: np.ndarray) -> np.ndarray:
    cleaned = cv2.bilateralFilter(image, 3, 10, 10)
    return cv2.fastNlMeansDenoisingColored(cleaned, None, 1.8, 1.8, 7, 15)


def enhance_1080p_fidelity(image: np.ndarray, mode: str = "fidelity") -> np.ndarray:
    reference = _resize_to_1080p(image)
    result = compress_clipped_highlights(reference, amount=0.045)
    result = _light_clean(result)
    result = _mid_frequency_detail(result, strength=0.18 if mode == "sharp_4k" else 0.14)
    result = enhance_true_edges(result, strength=0.18 if mode != "ai_image_clean" else 0.12)
    text_strength = 0.28 if mode in {"text_safe", "sharp_4k"} else 0.18
    result = enhance_text_regions(result, strength=text_strength)
    result = protect_highlights(reference, result, strength=0.92)
    return lock_color_to_reference(reference, result, chroma_strength=0.985, luma_strength=0.045)


def encode_image(image: np.ndarray, output_format: str) -> tuple[bool, np.ndarray | None, str]:
    fmt = output_format.lower().lstrip(".")
    if fmt == "jpeg":
        fmt = "jpg"
    if fmt not in {"png", "jpg", "webp"}:
        fmt = "png"

    if fmt == "png":
        params = [cv2.IMWRITE_PNG_COMPRESSION, 6]
        ext = ".png"
    elif fmt == "webp":
        params = [cv2.IMWRITE_WEBP_QUALITY, 92]
        ext = ".webp"
    else:
        params = [cv2.IMWRITE_JPEG_QUALITY, 94, cv2.IMWRITE_JPEG_OPTIMIZE, 1]
        ext = ".jpg"
    ok, encoded = cv2.imencode(ext, image, params)
    return ok, encoded, fmt


def pixel_diff_score(input_image: np.ndarray, output_image: np.ndarray) -> float:
    if input_image.shape[:2] != output_image.shape[:2]:
        input_image = cv2.resize(input_image, (output_image.shape[1], output_image.shape[0]), interpolation=cv2.INTER_CUBIC)
    diff = cv2.absdiff(input_image, output_image)
    return float(np.mean(diff))


def write_debug_log(payload: dict[str, Any]) -> Path:
    log_path = logs_dir() / "v035_latest_quality_debug.json"
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return log_path


def process_v035_1080p(
    input_path: Path,
    output_dir: Path,
    mode: str = "fidelity",
    output_format: str = "png",
    initial_timing: dict[str, float] | None = None,
) -> dict[str, Any]:
    total_start = time.perf_counter()
    timings: dict[str, float] = dict(initial_timing or {})
    timings.setdefault("receive_file_time", 0.0)
    timings.setdefault("save_input_time", 0.0)
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    input_size_bytes = input_path.stat().st_size
    input_hash = sha256_file(input_path)

    start = time.perf_counter()
    image = read_image(input_path)
    timings["decode_image_time"] = round(time.perf_counter() - start, 6)
    if image is None:
        raise RuntimeError("图片读取失败，无法进入 V0.3.5 忠实高清清洁管线。")

    input_height, input_width = image.shape[:2]

    start = time.perf_counter()
    output_image = enhance_1080p_fidelity(image, mode=mode)
    timings["enhance_time"] = round(time.perf_counter() - start, 6)
    output_height, output_width = output_image.shape[:2]

    start = time.perf_counter()
    ok, encoded, normalized_format = encode_image(output_image, output_format)
    timings["encode_output_time"] = round(time.perf_counter() - start, 6)
    if not ok or encoded is None:
        raise RuntimeError("图片重新编码失败。")

    output_path = build_v035_output_path(input_path, output_dir, normalized_format)
    start = time.perf_counter()
    encoded.tofile(str(output_path))
    timings["write_output_time"] = round(time.perf_counter() - start, 6)

    output_size_bytes = output_path.stat().st_size
    output_hash = sha256_file(output_path)
    diff_score = pixel_diff_score(image, output_image)
    hash_equal = input_hash == output_hash
    output_changed = (input_path.resolve() != output_path.resolve()) and (not hash_equal) and diff_score > 0
    size_ratio = round(output_size_bytes / max(input_size_bytes, 1), 4)
    timings["total_time"] = round(time.perf_counter() - total_start, 6)

    warnings: list[str] = []
    if not output_changed:
        warnings.append("输出图疑似原图复制：output_changed=false，请检查增强管线。")
    if size_ratio > 8.0:
        warnings.append(f"输出体积异常增大：ratio={size_ratio}，建议评估 JPG/WebP 或压缩参数。")

    diagnostics = {
        "input_size_bytes": input_size_bytes,
        "output_size_bytes": output_size_bytes,
        "file_size_ratio": size_ratio,
        "input_width": input_width,
        "input_height": input_height,
        "output_width": output_width,
        "output_height": output_height,
        "input_hash": input_hash,
        "output_hash": output_hash,
        "hash_equal": hash_equal,
        "pixel_diff_score": round(diff_score, 6),
        "output_changed": output_changed,
        "input_path": str(input_path),
        "output_path": str(output_path),
        "warnings": warnings,
    }
    payload = {
        "version": "V0.3.5",
        "mode": mode,
        "format": normalized_format,
        "debug_timing": timings,
        "debug_quality": diagnostics,
    }
    debug_log_path = write_debug_log(payload)
    payload["debug_log_path"] = str(debug_log_path)
    print("[V0.3.5 QualityCore]", json.dumps(payload, ensure_ascii=False, indent=2))
    return {
        "output_path": output_path,
        "width": output_width,
        "height": output_height,
        "format": normalized_format,
        "qualityFlag": "V0.3.5 1080P 忠实高清清洁完成" if output_changed else "输出疑似未发生有效变化",
        **payload,
    }
