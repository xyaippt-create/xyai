"""Offline ONNX restoration PoC for VisualMasterPro V0.4.6 RC1.

This script intentionally stays outside the delivery pipeline. It does not
fallback to OpenCV-only enhancement when ONNXRuntime or a local model is absent.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from importlib.util import find_spec
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


@dataclass(frozen=True)
class CheckResult:
    onnxruntime_available: bool
    model_files: list[Path]
    input_dir: Path | None
    input_images: list[Path]
    missing: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an offline ONNX restoration PoC on two latest real business images."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        help="Latest real image directory. Required when ONNXRuntime and a model are available.",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("models/restoration"),
        help="Directory containing local .onnx restoration or super-resolution models.",
    )
    parser.add_argument(
        "--model",
        type=Path,
        help="Optional explicit .onnx model path. Defaults to the first .onnx in --model-dir.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runtime/experiments/ai_restoration_poc"),
        help="Directory for before/after/blend comparison outputs.",
    )
    parser.add_argument("--max-images", type=int, default=2)
    return parser.parse_args()


def collect_images(input_dir: Path | None, max_images: int) -> list[Path]:
    if input_dir is None or not input_dir.exists() or not input_dir.is_dir():
        return []
    images = [
        item
        for item in sorted(input_dir.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True)
        if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS
    ]
    return images[:max_images]


def collect_models(model_dir: Path, explicit_model: Path | None) -> list[Path]:
    if explicit_model is not None:
        return [explicit_model] if explicit_model.exists() and explicit_model.suffix.lower() == ".onnx" else []
    if not model_dir.exists() or not model_dir.is_dir():
        return []
    return sorted(model_dir.glob("*.onnx"))


def preflight(args: argparse.Namespace) -> CheckResult:
    onnxruntime_available = find_spec("onnxruntime") is not None
    models = collect_models(args.model_dir, args.model)
    requested_images = max(1, args.max_images)
    images = collect_images(args.input_dir, requested_images)

    missing: list[str] = []
    if not onnxruntime_available:
        missing.append("onnxruntime")
    if not models:
        missing.append("models/restoration/*.onnx")
    if args.input_dir is None:
        missing.append("latest_real_image_dir")
    elif not args.input_dir.exists() or not args.input_dir.is_dir():
        missing.append(f"input_dir_not_found:{args.input_dir}")
    elif not images:
        missing.append(f"no_supported_images:{args.input_dir}")
    elif len(images) < requested_images:
        missing.append(f"need_{requested_images}_images_found_{len(images)}:{args.input_dir}")

    return CheckResult(
        onnxruntime_available=onnxruntime_available,
        model_files=models,
        input_dir=args.input_dir,
        input_images=images,
        missing=missing,
    )


def read_image(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot decode image: {path}")
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(path.suffix, image)
    if not ok:
        raise ValueError(f"Cannot encode image: {path}")
    encoded.tofile(str(path))


def to_nchw_rgb_float(image_bgr: np.ndarray, target_size: tuple[int, int] | None = None) -> np.ndarray:
    if target_size is not None:
        image_bgr = cv2.resize(image_bgr, target_size, interpolation=cv2.INTER_CUBIC)
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    return np.transpose(image_rgb, (2, 0, 1))[None, :, :, :]


def from_model_output(output: np.ndarray) -> np.ndarray:
    array = output[0] if output.ndim == 4 else output
    if array.ndim == 3 and array.shape[0] in (1, 3):
        array = np.transpose(array, (1, 2, 0))
    if array.ndim == 2:
        array = np.repeat(array[:, :, None], 3, axis=2)
    if array.dtype != np.uint8:
        if float(np.nanmax(array)) <= 1.5:
            array = array * 255.0
        array = np.clip(array, 0, 255).astype(np.uint8)
    if array.shape[2] == 1:
        array = np.repeat(array, 3, axis=2)
    return cv2.cvtColor(array[:, :, :3], cv2.COLOR_RGB2BGR)


def build_protection_masks(image_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return text/logo protection mask and non-text subject blend mask."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]

    edges = cv2.Canny(gray, 60, 160)
    dark_text = ((gray < 120) & (value < 180)).astype(np.uint8) * 255
    adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        10,
    )
    text_like = cv2.bitwise_or(dark_text, cv2.bitwise_and(adaptive, edges))
    text_like = cv2.morphologyEx(text_like, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8), iterations=1)
    text_like = cv2.dilate(text_like, np.ones((5, 5), np.uint8), iterations=1)

    white_flat = ((saturation < 35) & (value > 205) & (edges < 20)).astype(np.uint8) * 255
    textured = ((edges > 0) | (saturation > 45) | (gray < 220)).astype(np.uint8) * 255
    subject = cv2.bitwise_and(textured, cv2.bitwise_not(text_like))
    subject = cv2.bitwise_and(subject, cv2.bitwise_not(white_flat))
    subject = cv2.morphologyEx(subject, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    subject = cv2.GaussianBlur(subject, (0, 0), 2.0)

    return text_like, subject


def run_onnx(model_path: Path, image_bgr: np.ndarray):
    import onnxruntime as ort

    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    input_meta = session.get_inputs()[0]
    output_name = session.get_outputs()[0].name
    target_size = None
    if len(input_meta.shape) == 4:
        _, _, input_h, input_w = input_meta.shape
        if isinstance(input_h, int) and isinstance(input_w, int):
            target_size = (input_w, input_h)
    result = session.run([output_name], {input_meta.name: to_nchw_rgb_float(image_bgr, target_size)})[0]
    return from_model_output(result)


def blend_non_text_subjects(original_bgr: np.ndarray, restored_bgr: np.ndarray) -> np.ndarray:
    if restored_bgr.shape[:2] != original_bgr.shape[:2]:
        original_base = cv2.resize(
            original_bgr,
            (restored_bgr.shape[1], restored_bgr.shape[0]),
            interpolation=cv2.INTER_CUBIC,
        )
    else:
        original_base = original_bgr

    text_mask, subject_mask = build_protection_masks(original_base)
    alpha = (subject_mask.astype(np.float32) / 255.0) * 0.72
    alpha[text_mask > 0] = 0.0
    alpha = alpha[:, :, None]
    blended = original_base.astype(np.float32) * (1.0 - alpha) + restored_bgr.astype(np.float32) * alpha
    return np.clip(blended, 0, 255).astype(np.uint8)


def make_compare(before: np.ndarray, after: np.ndarray, blend: np.ndarray) -> np.ndarray:
    height = max(before.shape[0], after.shape[0], blend.shape[0])
    width = max(before.shape[1], after.shape[1], blend.shape[1])

    def fit(image: np.ndarray) -> np.ndarray:
        canvas = np.full((height, width, 3), 245, dtype=np.uint8)
        resized = image
        if image.shape[0] > height or image.shape[1] > width:
            resized = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
        y = (height - resized.shape[0]) // 2
        x = (width - resized.shape[1]) // 2
        canvas[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
        return canvas

    return np.concatenate([fit(before), fit(after), fit(blend)], axis=1)


def summarize_metrics(before: np.ndarray, blend: np.ndarray) -> dict[str, float]:
    if before.shape[:2] != blend.shape[:2]:
        before = cv2.resize(before, (blend.shape[1], blend.shape[0]), interpolation=cv2.INTER_CUBIC)
    before_lab = cv2.cvtColor(before, cv2.COLOR_BGR2LAB)
    blend_lab = cv2.cvtColor(blend, cv2.COLOR_BGR2LAB)
    before_lap = cv2.Laplacian(before_lab[:, :, 0], cv2.CV_64F).var()
    blend_lap = cv2.Laplacian(blend_lab[:, :, 0], cv2.CV_64F).var()
    color_delta = np.mean(np.abs(before_lab[:, :, 1:].astype(np.float32) - blend_lab[:, :, 1:].astype(np.float32)))
    return {
        "luma_laplacian_before": round(float(before_lap), 4),
        "luma_laplacian_blend": round(float(blend_lap), 4),
        "luma_laplacian_delta": round(float(blend_lap - before_lap), 4),
        "mean_ab_color_delta": round(float(color_delta), 4),
    }


def process_images(args: argparse.Namespace, checks: CheckResult) -> dict:
    model_path = checks.model_files[0]
    run_dir = args.output_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
    results = []

    for image_path in checks.input_images[: args.max_images]:
        original = read_image(image_path)
        restored = run_onnx(model_path, original)
        blended = blend_non_text_subjects(original, restored)
        compare = make_compare(original, restored, blended)

        stem = image_path.stem
        after_path = run_dir / f"{stem}_after.png"
        blend_path = run_dir / f"{stem}_blend.png"
        compare_path = run_dir / f"{stem}_compare_before_after_blend.png"
        write_image(after_path, restored)
        write_image(blend_path, blended)
        write_image(compare_path, compare)

        results.append(
            {
                "input": str(image_path),
                "after": str(after_path),
                "blend": str(blend_path),
                "compare": str(compare_path),
                "metrics": summarize_metrics(original, blended),
                "visual_judgement": "manual_image_check_required",
            }
        )

    return {
        "status": "PASS_WITH_NOTES",
        "onnxruntime": True,
        "model": str(model_path),
        "input_images": [str(path) for path in checks.input_images[: args.max_images]],
        "output_dir": str(run_dir),
        "results": results,
        "notes": [
            "Model output is blended only into non-text subject/detail regions.",
            "Text/logo-like regions and flat white background are protected from model replacement.",
        ],
    }


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    args = parse_args()
    checks = preflight(args)

    if checks.missing:
        emit(
            {
                "status": "BLOCKED",
                "onnxruntime": checks.onnxruntime_available,
                "models": [str(path) for path in checks.model_files],
                "input_dir": str(checks.input_dir) if checks.input_dir else None,
                "input_images": [str(path) for path in checks.input_images],
                "missing": checks.missing,
                "message": "Missing ONNXRuntime, local .onnx model, or latest real image directory. No OpenCV fallback was run.",
            }
        )
        return 2

    emit(process_images(args, checks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
