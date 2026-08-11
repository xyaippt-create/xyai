"""Offline Real-ESRGAN ncnn Vulkan PoC for VisualMasterPro V0.4.6 RC1."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Real-ESRGAN external PoC on the latest real images.")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument(
        "--tool-dir",
        type=Path,
        default=Path("external_tools/realesrgan-ncnn-vulkan"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runtime/experiments/realesrgan_external_poc_v4"),
    )
    parser.add_argument(
        "--reuse-after-dir",
        type=Path,
        default=Path("runtime/experiments/realesrgan_external_poc_v2/20260627_070550/after"),
        help="Reuse previous x4plus after outputs when present.",
    )
    parser.add_argument("--model", default="realesrgan-x4plus")
    parser.add_argument("--scale", default="4")
    parser.add_argument("--limit", type=int, default=7)
    return parser.parse_args()


def selected_images(input_dir: Path, limit: int) -> list[Path]:
    if not input_dir.exists() or not input_dir.is_dir():
        return []
    images = [
        item
        for item in input_dir.iterdir()
        if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS
    ]
    return sorted(images, key=lambda item: item.stat().st_mtime, reverse=True)[:limit]


def read_image(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Cannot decode image: {path}")
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(path.suffix, image)
    if not ok:
        raise RuntimeError(f"Cannot encode image: {path}")
    encoded.tofile(str(path))


def fit_height(image: np.ndarray, height: int) -> np.ndarray:
    scale = height / image.shape[0]
    width = max(1, int(round(image.shape[1] * scale)))
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)


def labeled_panel(image: np.ndarray, label: str, height: int) -> np.ndarray:
    panel = fit_height(image, height)
    label_bar = np.full((42, panel.shape[1], 3), 245, dtype=np.uint8)
    cv2.putText(label_bar, label, (14, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (30, 30, 30), 2, cv2.LINE_AA)
    return np.vstack([label_bar, panel])


def make_contact_sheet(panels: list[tuple[str, np.ndarray]], output_path: Path) -> None:
    preview_height = 720
    rendered = [labeled_panel(image, label, preview_height) for label, image in panels]
    max_height = max(panel.shape[0] for panel in rendered)
    normalized = []
    for panel in rendered:
        if panel.shape[0] == max_height:
            normalized.append(panel)
            continue
        canvas = np.full((max_height, panel.shape[1], 3), 245, dtype=np.uint8)
        canvas[: panel.shape[0], : panel.shape[1]] = panel
        normalized.append(canvas)
    spacer = np.full((max_height, 12, 3), 235, dtype=np.uint8)
    sheet = normalized[0]
    for panel in normalized[1:]:
        sheet = np.hstack([sheet, spacer, panel])
    write_image(output_path, sheet)


def resize_to_match(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    if source.shape[:2] == target.shape[:2]:
        return source
    return cv2.resize(source, (target.shape[1], target.shape[0]), interpolation=cv2.INTER_CUBIC)


def linear_blend(original: np.ndarray, model_output: np.ndarray, amount: float) -> np.ndarray:
    original_up = resize_to_match(original, model_output)
    blended = original_up.astype(np.float32) * (1.0 - amount) + model_output.astype(np.float32) * amount
    return np.clip(blended, 0, 255).astype(np.uint8)


def build_protection_masks(original_up: np.ndarray) -> dict[str, np.ndarray]:
    gray = cv2.cvtColor(original_up, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(original_up, cv2.COLOR_BGR2HSV)
    ycrcb = cv2.cvtColor(original_up, cv2.COLOR_BGR2YCrCb)

    edges = cv2.Canny(gray, 70, 170)
    adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        8,
    )
    dark_strokes = ((gray < 130) & (edges > 0)).astype(np.uint8) * 255
    text_like = cv2.bitwise_or(dark_strokes, cv2.bitwise_and(adaptive, edges))
    text_like = cv2.dilate(text_like, np.ones((5, 5), np.uint8), iterations=1)

    h, s, v = cv2.split(hsv)
    skin = (
        (ycrcb[:, :, 1] > 132)
        & (ycrcb[:, :, 1] < 178)
        & (ycrcb[:, :, 2] > 84)
        & (ycrcb[:, :, 2] < 138)
        & (s > 20)
        & (v > 80)
    ).astype(np.uint8) * 255
    skin = cv2.morphologyEx(skin, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=1)
    skin = cv2.GaussianBlur(skin, (0, 0), 3.0)

    high_sat = ((s > 105) & (v > 80)).astype(np.uint8) * 255
    high_sat = cv2.dilate(high_sat, np.ones((5, 5), np.uint8), iterations=1)

    hair_like = ((s < 80) & (v > 120) & (edges > 0)).astype(np.uint8) * 255
    hair_like = cv2.dilate(hair_like, np.ones((7, 7), np.uint8), iterations=1)
    hair_like = cv2.GaussianBlur(hair_like, (0, 0), 2.0)

    high_contrast_edge = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    return {
        "text_like": text_like,
        "skin": skin,
        "high_sat": high_sat,
        "hair_like": hair_like,
        "high_contrast_edge": high_contrast_edge,
    }


def classify_image(original: np.ndarray) -> tuple[str, dict[str, float]]:
    masks = build_protection_masks(original)
    gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(original, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    edges = cv2.Canny(gray, 70, 170)

    skin_ratio = float(np.mean(masks["skin"] > 0))
    text_ratio = float(np.mean(masks["text_like"] > 0))
    edge_ratio = float(np.mean(edges > 0))
    high_sat_ratio = float(np.mean(masks["high_sat"] > 0))
    light_bg_ratio = float(np.mean((s < 65) & (v > 175)))

    metrics = {
        "skin_ratio": round(skin_ratio, 4),
        "text_ratio": round(text_ratio, 4),
        "edge_ratio": round(edge_ratio, 4),
        "high_sat_ratio": round(high_sat_ratio, 4),
        "light_bg_ratio": round(light_bg_ratio, 4),
    }

    if light_bg_ratio < 0.08 and high_sat_ratio > 0.10 and text_ratio > 0.05:
        return "产品", metrics
    if text_ratio > 0.018 and light_bg_ratio > 0.35:
        return "信息海报", metrics
    if edge_ratio > 0.08 and light_bg_ratio > 0.20:
        return "城市建筑", metrics
    if high_sat_ratio > 0.08 and edge_ratio > 0.045:
        return "产品", metrics
    if 0.035 < skin_ratio < 0.70 and edge_ratio < 0.075 and light_bg_ratio < 0.70:
        return "人像", metrics
    return "不确定", metrics


def local_subject_blend(original: np.ndarray, model_output: np.ndarray, variant: str) -> np.ndarray:
    original_up = resize_to_match(original, model_output)
    masks = build_protection_masks(original_up)
    skin_ratio = float(np.mean(masks["skin"] > 0))
    portrait_like = skin_ratio > 0.035

    if variant == "b":
        alpha = np.full(original_up.shape[:2], 0.32, dtype=np.float32)
        if portrait_like:
            skin_mask = cv2.dilate(masks["skin"], np.ones((27, 27), np.uint8), iterations=1)
            hair_mask = cv2.dilate(masks["hair_like"], np.ones((21, 21), np.uint8), iterations=1)
            alpha[hair_mask > 0] = 0.10
            alpha[skin_mask > 0] = 0.05
            alpha[masks["text_like"] > 0] = 0.04
        else:
            text_mask = cv2.dilate(masks["text_like"], np.ones((13, 13), np.uint8), iterations=1)
            edge_mask = cv2.dilate(masks["high_contrast_edge"], np.ones((5, 5), np.uint8), iterations=1)
            alpha[edge_mask > 0] = 0.16
            alpha[text_mask > 0] = 0.04
            alpha[masks["high_sat"] > 0] = 0.12
    else:
        alpha = np.full(original_up.shape[:2], 0.35, dtype=np.float32)
        alpha[masks["high_contrast_edge"] > 0] = 0.22
        alpha[masks["high_sat"] > 0] = 0.16
        alpha[masks["hair_like"] > 0] = 0.14
        alpha[masks["skin"] > 0] = 0.08
        alpha[masks["text_like"] > 0] = 0.04

    alpha = cv2.GaussianBlur(alpha, (0, 0), 1.2)[:, :, None]
    blended = original_up.astype(np.float32) * (1.0 - alpha) + model_output.astype(np.float32) * alpha
    return np.clip(blended, 0, 255).astype(np.uint8)


def strategy_recommended_blend(original: np.ndarray, model_output: np.ndarray, image_type: str) -> tuple[str, np.ndarray]:
    original_up = resize_to_match(original, model_output)
    masks = build_protection_masks(original_up)

    if image_type == "人像" or image_type == "不确定":
        alpha = np.full(original_up.shape[:2], 0.25, dtype=np.float32)
        skin_mask = cv2.dilate(masks["skin"], np.ones((27, 27), np.uint8), iterations=1)
        hair_mask = cv2.dilate(masks["hair_like"], np.ones((17, 17), np.uint8), iterations=1)
        alpha[hair_mask > 0] = 0.08
        alpha[skin_mask > 0] = 0.04
        alpha[masks["text_like"] > 0] = 0.04
        label = f"strategy {image_type}: 25% protected"
    else:
        alpha = np.full(original_up.shape[:2], 0.35, dtype=np.float32)
        text_mask = cv2.dilate(masks["text_like"], np.ones((11, 11), np.uint8), iterations=1)
        edge_mask = cv2.dilate(masks["high_contrast_edge"], np.ones((5, 5), np.uint8), iterations=1)
        alpha[edge_mask > 0] = 0.20
        alpha[text_mask > 0] = 0.05
        alpha[masks["high_sat"] > 0] = 0.14
        label = f"strategy {image_type}: 35% protected"

    alpha = cv2.GaussianBlur(alpha, (0, 0), 1.2)[:, :, None]
    blended = original_up.astype(np.float32) * (1.0 - alpha) + model_output.astype(np.float32) * alpha
    return label, np.clip(blended, 0, 255).astype(np.uint8)


def luma_laplacian(image: np.ndarray) -> float:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    return float(cv2.Laplacian(lab[:, :, 0], cv2.CV_64F).var())


def color_delta_resized(before: np.ndarray, after: np.ndarray) -> float:
    after_small = cv2.resize(after, (before.shape[1], before.shape[0]), interpolation=cv2.INTER_AREA)
    before_lab = cv2.cvtColor(before, cv2.COLOR_BGR2LAB)
    after_lab = cv2.cvtColor(after_small, cv2.COLOR_BGR2LAB)
    return float(np.mean(np.abs(before_lab[:, :, 1:].astype(np.float32) - after_lab[:, :, 1:].astype(np.float32))))


def run_realesrgan(exe: Path, source: Path, target: Path, model: str, scale: str) -> dict:
    command = [
        str(exe.resolve()),
        "-i",
        str(source.resolve()),
        "-o",
        str(target.resolve()),
        "-n",
        model,
        "-s",
        scale,
        "-f",
        "png",
    ]
    completed = subprocess.run(command, cwd=str(exe.parent.resolve()), text=True, capture_output=True, timeout=180)
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "command": command,
    }


def find_reusable_after(source: Path, reuse_after_dir: Path) -> Path | None:
    normalized_stem = re.sub(r"_20\d{6}_\d{6}$", "", source.stem)
    search_dirs = [
        reuse_after_dir,
        Path("runtime/experiments/realesrgan_external_poc_v3/20260627_071417/after"),
        Path("runtime/experiments/realesrgan_external_poc/20260626_231220/after"),
    ]
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        matches = sorted(search_dir.glob(f"*{source.stem}*_realesrgan_x4plus.png"))
        if not matches and normalized_stem != source.stem:
            matches = sorted(search_dir.glob(f"*{normalized_stem}*_realesrgan_x4plus.png"))
        if matches:
            return matches[0]
    return None


def main() -> int:
    args = parse_args()
    exe = args.tool_dir / "realesrgan-ncnn-vulkan.exe"
    images = selected_images(args.input_dir, args.limit)

    if not exe.exists():
        print(json.dumps({"status": "BLOCKED", "reason": "missing_realesrgan_exe"}, ensure_ascii=False, indent=2))
        return 2
    if len(images) < args.limit:
        print(json.dumps({"status": "BLOCKED", "reason": "missing_input_images", "images": [str(p) for p in images]}, ensure_ascii=False, indent=2))
        return 2

    run_dir = args.output_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
    after_dir = run_dir / "after"
    blend_dir = run_dir / "blend"
    sheet_dir = run_dir / "contact_sheet"
    after_dir.mkdir(parents=True, exist_ok=True)
    blend_dir.mkdir(parents=True, exist_ok=True)
    sheet_dir.mkdir(parents=True, exist_ok=True)

    results = []
    failed = False
    for index, source in enumerate(images, start=1):
        safe_stem = f"{index:02d}_{source.stem}"
        after_path = after_dir / f"{safe_stem}_realesrgan_x4plus.png"
        reusable_after = find_reusable_after(source, args.reuse_after_dir)
        run_info = {"reused_after": str(reusable_after) if reusable_after else None}
        if reusable_after:
            after = read_image(reusable_after)
            write_image(after_path, after)
        else:
            run_info = run_realesrgan(exe, source, after_path, args.model, args.scale)
            if run_info["returncode"] != 0 or not after_path.exists():
                failed = True
                results.append({"input": str(source), "after": str(after_path), "contact_sheet": None, "run": run_info})
                continue

        before = read_image(source)
        after = read_image(after_path)
        image_type, type_metrics = classify_image(before)
        blend_25 = linear_blend(before, after, 0.25)
        blend_35 = linear_blend(before, after, 0.35)
        strategy_label, strategy = strategy_recommended_blend(before, after, image_type)
        blend_25_path = blend_dir / f"{safe_stem}_blend_25.png"
        blend_35_path = blend_dir / f"{safe_stem}_blend_35.png"
        strategy_path = blend_dir / f"{safe_stem}_strategy_recommended.png"
        sheet_path = sheet_dir / f"{safe_stem}_contact_sheet.png"
        write_image(blend_25_path, blend_25)
        write_image(blend_35_path, blend_35)
        write_image(strategy_path, strategy)
        make_contact_sheet(
            [
                ("original", before),
                ("25% blend", blend_25),
                ("35% blend", blend_35),
                (strategy_label, strategy),
            ],
            sheet_path,
        )
        results.append(
            {
                "input": str(source),
                "after": str(after_path),
                "image_type": image_type,
                "type_metrics": type_metrics,
                "blend_25": str(blend_25_path),
                "blend_35": str(blend_35_path),
                "strategy_recommended": str(strategy_path),
                "contact_sheet": str(sheet_path),
                "before_size": [int(before.shape[1]), int(before.shape[0])],
                "after_size": [int(after.shape[1]), int(after.shape[0])],
                "metrics": {
                    "before_luma_laplacian": round(luma_laplacian(before), 4),
                    "after_luma_laplacian": round(luma_laplacian(after), 4),
                    "blend_25_luma_laplacian": round(luma_laplacian(blend_25), 4),
                    "blend_35_luma_laplacian": round(luma_laplacian(blend_35), 4),
                    "strategy_luma_laplacian": round(luma_laplacian(strategy), 4),
                    "mean_ab_color_delta_downsampled": round(color_delta_resized(before, after), 4),
                    "blend_25_ab_delta_downsampled": round(color_delta_resized(before, blend_25), 4),
                    "blend_35_ab_delta_downsampled": round(color_delta_resized(before, blend_35), 4),
                    "strategy_ab_delta_downsampled": round(color_delta_resized(before, strategy), 4),
                },
                "run": run_info,
            }
        )

    payload = {
        "status": "BLOCKED" if failed else "PASS_WITH_NOTES",
        "model": args.model,
        "input_images": [str(path) for path in images],
        "output_dir": str(run_dir),
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
