"""Offline 1080P safe enhance candidate module.

This entry stays outside the production pipeline. It runs Real-ESRGAN x4plus
and applies a conservative 35% protected blend for non-portrait Chinese
commercial visuals.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
DEFAULT_TOOL_DIR = Path("external_tools/realesrgan-ncnn-vulkan")
BETA_TIMEOUT_SECONDS = 300
DEFAULT_OUTPUT_DIR = Path("D:/影界文件/1080P安全增强输出")
DEFAULT_DIAGNOSTIC_DIR = Path("D:/影界文件/影界测试反馈包")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run offline 1080P safe enhancement candidates.")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mode", choices=["safe_1080p"], default="safe_1080p")
    parser.add_argument("--tool-dir", type=Path, default=DEFAULT_TOOL_DIR)
    parser.add_argument("--model", default="realesrgan-x4plus")
    parser.add_argument("--scale", default="4")
    parser.add_argument("--flat-output", action="store_true")
    parser.add_argument("--business-output", action="store_true")
    parser.add_argument("--diagnostic-dir", type=Path, default=DEFAULT_DIAGNOSTIC_DIR)
    parser.add_argument("--timeout-seconds", type=int, default=BETA_TIMEOUT_SECONDS)
    return parser.parse_args()


class RealEsrganProcessError(RuntimeError):
    def __init__(self, reason: str, message: str, returncode: int | str | None = None, stderr_tail: str = "") -> None:
        super().__init__(message)
        self.reason = reason
        self.returncode = returncode
        self.stderr_tail = stderr_tail


def redact_text(value: object) -> str:
    text = "" if value is None else str(value)
    if not text:
        return ""
    home = str(Path.home())
    if home and text.lower().startswith(home.lower()):
        text = "%USERPROFILE%" + text[len(home) :]
    for sensitive, replacement in (
        (os.environ.get("USERNAME") or os.environ.get("USER") or "", "%USERNAME%"),
        (os.environ.get("COMPUTERNAME") or "", "%COMPUTERNAME%"),
    ):
        if sensitive:
            text = text.replace(sensitive, replacement)
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "%IPV4%", text)
    text = re.sub(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b", "%MAC%", text)
    return text


def redact_path(value: object) -> str:
    return redact_text(value)


def tail_text(value: object, limit: int = 1200) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = str(value).strip()
    return redact_text(text[-limit:])


def emit_stage(stage_logger: object, stage: str, started: float, **fields: object) -> None:
    payload = {
        "stage": stage,
        "input_path": redact_path(fields.get("input_path")),
        "output_dir": redact_path(fields.get("output_dir")),
        "current_file": fields.get("current_file") or "",
        "flat_output": bool(fields.get("flat_output")),
        "business_output": bool(fields.get("business_output")),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "returncode": fields.get("returncode", ""),
        "stderr_tail": tail_text(fields.get("stderr_tail")),
        "error_message": tail_text(fields.get("error_message")),
    }
    if callable(stage_logger):
        forwarded = dict(payload)
        forwarded.pop("stage", None)
        stage_logger(stage, **forwarded)
        return
    print("[SAFE_1080P_BETA] " + json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)


def write_optional_json(path: Path, payload: dict[str, object]) -> str:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return ""
    except Exception as exc:
        return tail_text(exc)


def image_files(input_dir: Path) -> list[Path]:
    if not input_dir.exists() or not input_dir.is_dir():
        return []
    return sorted(
        [
            item
            for item in input_dir.iterdir()
            if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS
        ],
        key=lambda item: item.name,
    )


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
    cv2.putText(
        label_bar,
        label,
        (14, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        (30, 30, 30),
        2,
        cv2.LINE_AA,
    )
    return np.vstack([label_bar, panel])


def make_contact_sheet(original: np.ndarray, blend35: np.ndarray, protected35: np.ndarray, path: Path) -> None:
    rendered = [
        labeled_panel(original, "original", 720),
        labeled_panel(blend35, "35% blend", 720),
        labeled_panel(protected35, "35% protected", 720),
    ]
    max_height = max(panel.shape[0] for panel in rendered)
    normalized: list[np.ndarray] = []
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
    write_image(path, sheet)


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
    dark_strokes = ((gray < 135) & (edges > 0)).astype(np.uint8) * 255
    text_like = cv2.bitwise_or(dark_strokes, cv2.bitwise_and(adaptive, edges))
    text_like = cv2.dilate(text_like, np.ones((7, 7), np.uint8), iterations=1)

    h, s, v = cv2.split(hsv)
    high_sat = ((s > 105) & (v > 80)).astype(np.uint8) * 255
    high_sat = cv2.dilate(high_sat, np.ones((5, 5), np.uint8), iterations=1)

    skin = (
        (ycrcb[:, :, 1] > 132)
        & (ycrcb[:, :, 1] < 178)
        & (ycrcb[:, :, 2] > 84)
        & (ycrcb[:, :, 2] < 138)
        & (s > 20)
        & (v > 80)
    ).astype(np.uint8) * 255
    skin = cv2.morphologyEx(skin, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8), iterations=1)

    high_contrast_edge = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    return {
        "text_like": text_like,
        "high_sat": high_sat,
        "skin": skin,
        "high_contrast_edge": high_contrast_edge,
    }


def classify_image(path: Path, original: np.ndarray) -> tuple[str, str, dict[str, float]]:
    name = path.stem
    gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(original, cv2.COLOR_BGR2HSV)
    _, s, v = cv2.split(hsv)
    masks = build_protection_masks(original)
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

    commercial_name_tokens = ("指南", "清单", "服务", "护肤", "地图", "广告", "产品", "包装", "海报")
    portrait_name_tokens = ("人像", "头像", "面部", "写真", "证件照")
    if any(token in name for token in portrait_name_tokens):
        return "portrait", "skip_portrait_name", metrics
    if any(token in name for token in commercial_name_tokens):
        return "commercial_non_portrait", "commercial_name", metrics

    if text_ratio > 0.08 and edge_ratio > 0.035:
        return "commercial_non_portrait", "strong_text_commercial_metrics", metrics
    if text_ratio > 0.018 and light_bg_ratio > 0.35:
        return "commercial_non_portrait", "info_poster_metrics", metrics
    if edge_ratio > 0.08 and light_bg_ratio > 0.20:
        return "commercial_non_portrait", "city_or_map_metrics", metrics
    if high_sat_ratio > 0.08 and edge_ratio > 0.045:
        return "commercial_non_portrait", "product_metrics", metrics
    if 0.035 < skin_ratio < 0.70 and edge_ratio < 0.075 and light_bg_ratio < 0.70:
        return "portrait", "skip_portrait_metrics", metrics
    return "uncertain", "skip_uncertain", metrics


def protected_35_blend(original: np.ndarray, model_output: np.ndarray) -> np.ndarray:
    original_up = resize_to_match(original, model_output)
    masks = build_protection_masks(original_up)

    alpha = np.full(original_up.shape[:2], 0.35, dtype=np.float32)
    text_mask = cv2.dilate(masks["text_like"], np.ones((11, 11), np.uint8), iterations=1)
    edge_mask = cv2.dilate(masks["high_contrast_edge"], np.ones((5, 5), np.uint8), iterations=1)
    alpha[edge_mask > 0] = 0.20
    alpha[masks["high_sat"] > 0] = 0.14
    alpha[text_mask > 0] = 0.05

    alpha = cv2.GaussianBlur(alpha, (0, 0), 1.2)[:, :, None]
    blended = original_up.astype(np.float32) * (1.0 - alpha) + model_output.astype(np.float32) * alpha
    return np.clip(blended, 0, 255).astype(np.uint8)


def find_exe(tool_dir: Path) -> Path | None:
    exe = tool_dir / "realesrgan-ncnn-vulkan.exe"
    return exe if exe.exists() else None


def has_model_files(tool_dir: Path) -> bool:
    model_dir = tool_dir / "models"
    if not model_dir.exists():
        return False
    return any(item.suffix.lower() in {".param", ".bin"} for item in model_dir.rglob("*") if item.is_file())


def run_realesrgan(
    exe: Path,
    tool_dir: Path,
    source: Path,
    output: Path,
    model: str,
    scale: str,
    timeout_seconds: int = BETA_TIMEOUT_SECONDS,
    stage_logger: object = None,
    started: float | None = None,
    output_dir: Path | None = None,
    flat_output: bool = False,
    business_output: bool = False,
) -> dict[str, object]:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(exe),
        "-i",
        str(source.resolve()),
        "-o",
        str(output.resolve()),
        "-n",
        model,
        "-s",
        scale,
        "-f",
        "png",
    ]
    stage_started = started if started is not None else time.perf_counter()
    emit_stage(
        stage_logger,
        "BETA_REALESRGAN_SUBPROCESS_START",
        stage_started,
        input_path=source,
        output_dir=output_dir,
        current_file=source.name,
        flat_output=flat_output,
        business_output=business_output,
    )
    try:
        completed = subprocess.run(
            command,
            cwd=str(tool_dir.resolve()),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stderr_tail = tail_text(exc.stderr or exc.output)
        emit_stage(
            stage_logger,
            "BETA_FAILED",
            stage_started,
            input_path=source,
            output_dir=output_dir,
            current_file=source.name,
            flat_output=flat_output,
            business_output=business_output,
            returncode="timeout",
            stderr_tail=stderr_tail,
            error_message=f"Real-ESRGAN timed out after {timeout_seconds}s",
        )
        raise RealEsrganProcessError(
            "realesrgan_timeout",
            f"Real-ESRGAN timed out after {timeout_seconds}s for {source.name}",
            "timeout",
            stderr_tail,
        ) from exc
    stderr_tail = tail_text(completed.stderr or completed.stdout)
    emit_stage(
        stage_logger,
        "BETA_REALESRGAN_SUBPROCESS_DONE",
        stage_started,
        input_path=source,
        output_dir=output_dir,
        current_file=source.name,
        flat_output=flat_output,
        business_output=business_output,
        returncode=completed.returncode,
        stderr_tail=stderr_tail,
    )
    if completed.returncode != 0:
        raise RealEsrganProcessError(
            "realesrgan_failed",
            f"Real-ESRGAN failed for {source.name}: {stderr_tail}",
            completed.returncode,
            stderr_tail,
        )
    return {"returncode": completed.returncode, "stderr_tail": stderr_tail}


def relative_or_name(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def unique_business_path(path: Path, token: str) -> Path:
    if not path.exists():
        return path
    candidate = path.with_name(f"{path.stem}_{token}{path.suffix}")
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{token}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def process(args: argparse.Namespace) -> dict[str, object]:
    started_at = datetime.now().isoformat(timespec="seconds")
    start_time = time.perf_counter()
    input_dir = args.input_dir
    tool_dir = args.tool_dir
    stage_logger = getattr(args, "stage_logger", None)
    business_output = bool(getattr(args, "business_output", False))
    flat_output = bool(getattr(args, "flat_output", False) or business_output)
    timeout_seconds = int(getattr(args, "timeout_seconds", BETA_TIMEOUT_SECONDS) or BETA_TIMEOUT_SECONDS)
    explicit_input_files = [
        Path(item)
        for item in (getattr(args, "input_files", None) or [])
        if str(item or "").strip()
    ]
    exe = find_exe(tool_dir)
    if exe is None:
        emit_stage(
            stage_logger,
            "BETA_FAILED",
            start_time,
            input_path=input_dir,
            output_dir=args.output_dir,
            flat_output=flat_output,
            business_output=business_output,
            error_message="missing_realesrgan_exe",
        )
        return {"status": "blocked", "reason": "missing_realesrgan_exe"}
    if not has_model_files(tool_dir):
        emit_stage(
            stage_logger,
            "BETA_FAILED",
            start_time,
            input_path=input_dir,
            output_dir=args.output_dir,
            flat_output=flat_output,
            business_output=business_output,
            error_message="missing_realesrgan_model_files",
        )
        return {"status": "blocked", "reason": "missing_realesrgan_model_files"}

    if flat_output or business_output:
        inputs = [item for item in explicit_input_files if item.exists() and item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS]
    else:
        inputs = image_files(input_dir)
    if not inputs:
        reason = "missing_explicit_input_files" if flat_output or business_output else "missing_input_images"
        emit_stage(
            stage_logger,
            "BETA_FAILED",
            start_time,
            input_path=input_dir,
            output_dir=args.output_dir,
            flat_output=flat_output,
            business_output=business_output,
            error_message=reason,
        )
        return {"status": "failed", "verification_result": "FAILED", "reason": reason, "processed_count": 0, "skipped_count": 0}

    run_token = datetime.now().strftime("%H%M%S")
    if flat_output:
        run_dir = args.output_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        enhanced_dir = run_dir
        diagnostic_dir = Path(getattr(args, "diagnostic_dir", DEFAULT_DIAGNOSTIC_DIR))
        contact_dir = diagnostic_dir / "contact_sheets"
        summary_dir = diagnostic_dir / "summaries"
        temp_context = tempfile.TemporaryDirectory(prefix="safe_1080p_beta_")
        after_dir = Path(temp_context.name)
    else:
        run_dir = args.output_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
        after_dir = run_dir / "after_x4plus"
        enhanced_dir = run_dir / "enhanced"
        contact_dir = run_dir / "contact_sheet"
        summary_dir = run_dir
    emit_stage(
        stage_logger,
        "BETA_ENHANCE_START",
        start_time,
        input_path=input_dir,
        output_dir=run_dir,
        current_file=inputs[0].name,
        flat_output=flat_output,
        business_output=business_output,
    )
    skipped: list[dict[str, object]] = []
    processed: list[dict[str, object]] = []
    warnings: list[str] = []
    failure: Exception | None = None
    failed_file = ""

    try:
        for image_path in inputs:
            failed_file = image_path.name
            image_start = time.perf_counter()
            original = read_image(image_path)
            image_type, reason, metrics = classify_image(image_path, original)
            base = image_path.stem
            if image_type != "commercial_non_portrait":
                skipped.append({"file": image_path.name, "type": image_type, "reason": reason, "metrics": metrics})
                continue

            after_path = after_dir / f"{base}_x4plus.png"
            if flat_output:
                enhanced_path = unique_business_path(enhanced_dir / f"{base}_1080p_beta.png", run_token)
                contact_path = unique_business_path(contact_dir / f"{base}_contact_sheet.png", run_token)
            else:
                enhanced_path = enhanced_dir / f"{base}_safe_1080p_35protected.png"
                contact_path = contact_dir / f"{base}_contact_sheet.png"

            run_realesrgan(
                exe,
                tool_dir,
                image_path,
                after_path,
                args.model,
                args.scale,
                timeout_seconds=timeout_seconds,
                stage_logger=stage_logger,
                started=start_time,
                output_dir=run_dir,
                flat_output=flat_output,
                business_output=business_output,
            )
            model_output = read_image(after_path)
            blend35 = linear_blend(original, model_output, 0.35)
            protected35 = protected_35_blend(original, model_output)

            emit_stage(
                stage_logger,
                "BETA_FLAT_OUTPUT_WRITE_START",
                start_time,
                input_path=image_path,
                output_dir=run_dir,
                current_file=image_path.name,
                flat_output=flat_output,
                business_output=business_output,
            )
            write_image(enhanced_path, protected35)
            emit_stage(
                stage_logger,
                "BETA_FLAT_OUTPUT_WRITE_DONE",
                start_time,
                input_path=image_path,
                output_dir=run_dir,
                current_file=image_path.name,
                flat_output=flat_output,
                business_output=business_output,
            )
            emit_stage(
                stage_logger,
                "BETA_CONTACT_SHEET_START",
                start_time,
                input_path=image_path,
                output_dir=run_dir,
                current_file=image_path.name,
                flat_output=flat_output,
                business_output=business_output,
            )
            contact_sheet_value = ""
            try:
                make_contact_sheet(original, blend35, protected35, contact_path)
                contact_sheet_value = relative_or_name(contact_path, run_dir)
            except Exception as exc:
                warning = f"contact_sheet_write_failed: {tail_text(exc)}"
                warnings.append(warning)
                emit_stage(
                    stage_logger,
                    "BETA_CONTACT_SHEET_DONE",
                    start_time,
                    input_path=image_path,
                    output_dir=run_dir,
                    current_file=image_path.name,
                    flat_output=flat_output,
                    business_output=business_output,
                    error_message=warning,
                )
            else:
                emit_stage(
                    stage_logger,
                    "BETA_CONTACT_SHEET_DONE",
                    start_time,
                    input_path=image_path,
                    output_dir=run_dir,
                    current_file=image_path.name,
                    flat_output=flat_output,
                    business_output=business_output,
                )
            processed.append(
                {
                    "file": image_path.name,
                    "input_name": image_path.name,
                    "output_name": enhanced_path.name,
                    "output_path": str(enhanced_path),
                    "type": image_type,
                    "reason": reason,
                    "metrics": metrics,
                    "after": "" if flat_output else relative_or_name(after_path, run_dir),
                    "enhanced": relative_or_name(enhanced_path, run_dir),
                    "contact_sheet": contact_sheet_value,
                    "elapsed_seconds": round(time.perf_counter() - image_start, 3),
                }
            )
    except Exception as exc:
        failure = exc
        emit_stage(
            stage_logger,
            "BETA_FAILED",
            start_time,
            input_path=input_dir,
            output_dir=run_dir,
            current_file=failed_file,
            flat_output=flat_output,
            business_output=business_output,
            returncode=getattr(exc, "returncode", ""),
            stderr_tail=getattr(exc, "stderr_tail", ""),
            error_message=str(exc),
        )
    finally:
        if flat_output:
            temp_context.cleanup()

    finished_at = datetime.now().isoformat(timespec="seconds")
    if failure is not None:
        summary = {
            "status": "failed",
            "verification_result": "FAILED",
            "reason": getattr(failure, "reason", "safe_1080p_failed"),
            "error_message": tail_text(str(failure)),
            "returncode": getattr(failure, "returncode", ""),
            "stderr_tail": tail_text(getattr(failure, "stderr_tail", "")),
            "failed_file": failed_file,
            "mode": args.mode,
            "model": args.model,
            "input_dir": str(input_dir),
            "output_dir": str(run_dir),
            "diagnostic_dir": str(summary_dir.parent if flat_output else run_dir),
            "flat_output": flat_output,
            "business_output": business_output,
            "timeout_seconds": timeout_seconds,
            "started_at": started_at,
            "finished_at": finished_at,
            "elapsed_seconds": round(time.perf_counter() - start_time, 3),
            "processed_count": len(processed),
            "skipped_count": len(skipped),
            "processed": processed,
            "skipped": skipped,
            "warnings": warnings,
        }
        summary_name = f"safe_1080p_beta_summary_{run_token}.json" if flat_output else "summary.json"
        summary_path = summary_dir / summary_name
        summary["summary_path"] = str(summary_path)
        summary_error = write_optional_json(summary_path, summary)
        if summary_error:
            summary["summary_path"] = ""
            summary["summary_write_error"] = summary_error
            warnings.append(f"summary_write_failed: {summary_error}")
        emit_stage(
            stage_logger,
            "BETA_RESPONSE_READY",
            start_time,
            input_path=input_dir,
            output_dir=run_dir,
            current_file=failed_file,
            flat_output=flat_output,
            business_output=business_output,
            returncode=summary.get("returncode", ""),
            stderr_tail=summary.get("stderr_tail", ""),
            error_message=summary.get("error_message", ""),
        )
        return summary

    summary = {
        "status": "ok" if processed else "blocked",
        "mode": args.mode,
        "model": args.model,
        "input_dir": str(input_dir),
        "output_dir": str(run_dir),
        "diagnostic_dir": str(summary_dir.parent if flat_output else run_dir),
        "flat_output": flat_output,
        "business_output": business_output,
        "timeout_seconds": timeout_seconds,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": round(time.perf_counter() - start_time, 3),
        "processed_count": len(processed),
        "skipped_count": len(skipped),
        "processed": processed,
        "skipped": skipped,
        "warnings": warnings,
    }
    if not processed and skipped:
        first_skip = skipped[0]
        skip_file = str(first_skip.get("file") or failed_file or inputs[0].name)
        skip_reason = str(first_skip.get("reason") or "input_skipped_by_beta_policy")
        summary["stage"] = "BETA_INPUT_SKIPPED"
        summary["reason"] = skip_reason
        summary["error_message"] = f"{skip_file} 被 1080P安全增强 Beta 安全策略跳过：{skip_reason}"
        summary["failed_file"] = skip_file
    summary_name = f"safe_1080p_beta_summary_{run_token}.json" if flat_output else "summary.json"
    summary_path = summary_dir / summary_name
    summary["summary_path"] = str(summary_path)
    summary_error = write_optional_json(summary_path, summary)
    if summary_error:
        summary["summary_path"] = ""
        summary["summary_write_error"] = summary_error
        warnings.append(f"summary_write_failed: {summary_error}")
    emit_stage(
        stage_logger,
        "BETA_RESPONSE_READY",
        start_time,
        input_path=input_dir,
        output_dir=run_dir,
        current_file=processed[-1]["file"] if processed else "",
        flat_output=flat_output,
        business_output=business_output,
        error_message="" if processed else summary.get("status"),
    )
    return summary


def main() -> int:
    args = parse_args()
    result = process(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
