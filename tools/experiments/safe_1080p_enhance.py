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
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.analysis.quality_compare import compare_quality


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
DEFAULT_TOOL_DIR = Path("external_tools/realesrgan-ncnn-vulkan")
BETA_TIMEOUT_SECONDS = 300
CONTACT_SHEET_LIGHT_JPEG_QUALITY = 90
JPG95_CANDIDATE_QUALITY = 95
TRUE_1080P_SHORT_EDGE = 1080
TRUE_1080P_MIN_ASPECT_RATIO = 0.45
TRUE_1080P_MAX_ASPECT_RATIO = 2.40
JPG95_CANDIDATE_MIN_OUTPUT_BYTES = 3 * 1024 * 1024
JPG95_CANDIDATE_MIN_SIZE_RATIO = 4.0
JPG95_CANDIDATE_MIN_SAVED_RATIO = 0.30
JPG95_CANDIDATE_TEXT_RATIO_LIMIT = 0.035
NEAR_1080P_FAST_MIN_SHORT_EDGE = 1000
NEAR_1080P_FAST_MAX_SCALE_RATIO = 1.12
KNOWLEDGE_POSTER_SCORE_THRESHOLD = 3.0
BALANCED_FAST_ROUTE = "already_1080p_balanced_fast_enhance"
TIMED_ENHANCE_STAGE_KEYS = (
    "resize_seconds",
    "prefilter_seconds",
    "roi_detect_seconds",
    "mask_build_seconds",
    "balanced_quality_seconds",
    "realesrgan_subprocess_seconds",
    "sr_io_seconds",
    "protected_blend_seconds",
    "local_detail_seconds",
    "text_line_enhance_seconds",
    "texture_suppress_seconds",
    "png_write_seconds",
    "contact_sheet_seconds",
    "roi_evidence_seconds",
)


def _read_settings_file_safely() -> dict:
    settings_path = PROJECT_ROOT / "settings" / "settings.json"
    if not settings_path.exists():
        return {}
    try:
        loaded = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _documents_dir() -> Path:
    if os.name == "nt" and os.environ.get("USERPROFILE"):
        return Path(os.environ["USERPROFILE"]) / "Documents"
    return Path.home() / "Documents"


def _directory_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".hdde_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def resolve_default_app_data_root() -> dict[str, object]:
    settings = _read_settings_file_safely()
    candidates: list[tuple[str, Path]] = []
    configured = str(settings.get("app_data_root") or "").strip()
    saved = str(settings.get("last_app_data_root") or "").strip()
    project_tmp_root = PROJECT_ROOT / "tmp" / "runtime_data"
    if configured:
        candidates.append(("user_config", Path(configured).expanduser()))
    saved_path = Path(saved).expanduser() if saved and saved != configured else None
    saved_is_project_tmp = False
    if saved_path is not None:
        try:
            saved_is_project_tmp = project_tmp_root.resolve() in saved_path.resolve().parents or saved_path.resolve() == project_tmp_root.resolve()
        except Exception:
            saved_is_project_tmp = False
    if saved_path is not None and not saved_is_project_tmp:
        candidates.append(("saved_config", saved_path))
    if os.name == "nt":
        candidates.append(("d_drive", Path("D:/影界文件")))
    candidates.append(("documents", _documents_dir() / "影界HDDE"))
    if saved_path is not None and saved_is_project_tmp:
        candidates.append(("saved_config", saved_path))
    candidates.append(("project_tmp", PROJECT_ROOT / "tmp" / "runtime_data" / "影界HDDE"))

    for source, candidate in candidates:
        if _directory_writable(candidate):
            return {
                "path": candidate,
                "source": source,
                "exists": candidate.exists(),
                "writable": True,
            }
    fallback = PROJECT_ROOT / "tmp" / "runtime_data" / "影界HDDE"
    return {"path": fallback, "source": "project_tmp", "exists": fallback.exists(), "writable": False}


def default_safe_beta_output_dir() -> Path:
    return Path(resolve_default_app_data_root()["path"]) / "1080P安全增强输出"


def default_safe_beta_diagnostic_dir() -> Path:
    return Path(resolve_default_app_data_root()["path"]) / "影界测试反馈包"


DEFAULT_OUTPUT_DIR = default_safe_beta_output_dir()
DEFAULT_DIAGNOSTIC_DIR = default_safe_beta_diagnostic_dir()


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


def read_image_unchanged(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise RuntimeError(f"Cannot decode image: {path}")
    return image


def real_alpha_status(path: Path) -> tuple[bool | None, str]:
    try:
        image = read_image_unchanged(path)
    except Exception as exc:
        return None, f"alpha_detection_failed: {tail_text(exc, 160)}"
    if image.ndim == 3 and image.shape[2] >= 4:
        alpha = image[:, :, 3]
        if bool(np.any(alpha < 255)):
            return True, "alpha_detected"
    return False, "no_real_alpha"


def file_size_bytes(path: Path | None) -> int | None:
    if path is None:
        return None
    try:
        return path.stat().st_size if path.exists() and path.is_file() else None
    except OSError:
        return None


def file_format(path: Path | None) -> str | None:
    if path is None:
        return None
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "jpeg":
        return "jpg"
    return suffix or None


def image_dimensions(image: np.ndarray | None) -> dict[str, int | None]:
    if image is None:
        return {"width": None, "height": None, "long_edge": None, "short_edge": None}
    height, width = image.shape[:2]
    return {
        "width": int(width),
        "height": int(height),
        "long_edge": int(max(width, height)),
        "short_edge": int(min(width, height)),
    }


def true_1080p_target_size(image: np.ndarray) -> tuple[int | None, int | None, str]:
    height, width = image.shape[:2]
    if width <= 0 or height <= 0:
        return None, None, "invalid_dimensions"
    aspect_ratio = width / max(height, 1)
    if aspect_ratio < TRUE_1080P_MIN_ASPECT_RATIO or aspect_ratio > TRUE_1080P_MAX_ASPECT_RATIO:
        return None, None, "aspect_ratio_not_supported"
    short_edge = min(width, height)
    if short_edge <= TRUE_1080P_SHORT_EDGE:
        return width, height, "source_not_upscaled"
    scale = TRUE_1080P_SHORT_EDGE / short_edge
    target_width = max(1, int(round(width * scale)))
    target_height = max(1, int(round(height * scale)))
    return target_width, target_height, "short_edge_1080"


def near_1080p_target_size(image: np.ndarray) -> tuple[int | None, int | None, float | None, str]:
    height, width = image.shape[:2]
    if width <= 0 or height <= 0:
        return None, None, None, "invalid_dimensions"
    aspect_ratio = width / max(height, 1)
    if aspect_ratio < TRUE_1080P_MIN_ASPECT_RATIO or aspect_ratio > TRUE_1080P_MAX_ASPECT_RATIO:
        return None, None, None, "aspect_ratio_not_supported"
    short_edge = min(width, height)
    scale = TRUE_1080P_SHORT_EDGE / max(short_edge, 1)
    target_width = max(1, int(round(width * scale)))
    target_height = max(1, int(round(height * scale)))
    return target_width, target_height, round(scale, 4), "short_edge_1080"


def default_enhance_timing_fields(route: str = "safe_beta_general") -> dict[str, object]:
    return {
        "enhance_route": route,
        "route_decision_reason": "",
        "already_1080p_or_near_1080p": False,
        "input_to_output_scale_ratio": "not_applicable",
        "resize_seconds": 0,
        "prefilter_seconds": 0,
        "roi_detect_seconds": 0,
        "mask_build_seconds": 0,
        "balanced_quality_seconds": 0,
        "realesrgan_subprocess_seconds": 0,
        "sr_io_seconds": 0,
        "protected_blend_seconds": 0,
        "local_detail_seconds": 0,
        "text_line_enhance_seconds": 0,
        "texture_suppress_seconds": 0,
        "png_write_seconds": 0,
        "contact_sheet_seconds": 0,
        "roi_evidence_seconds": 0,
        "model_init_seconds": "not_applicable",
        "fast_quality_level": "",
    }


def detect_knowledge_poster(path: Path, original: np.ndarray, metrics: dict[str, float]) -> dict[str, object]:
    name = path.stem.lower()
    text_ratio = float(metrics.get("text_ratio") or 0.0)
    edge_ratio = float(metrics.get("edge_ratio") or 0.0)
    light_bg_ratio = float(metrics.get("light_bg_ratio") or 0.0)
    skin_ratio = float(metrics.get("skin_ratio") or 0.0)
    high_sat_ratio = float(metrics.get("high_sat_ratio") or 0.0)
    gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    horizontal = cv2.morphologyEx(cv2.Canny(gray, 60, 160), cv2.MORPH_OPEN, np.ones((1, 9), np.uint8), iterations=1)
    vertical = cv2.morphologyEx(cv2.Canny(gray, 60, 160), cv2.MORPH_OPEN, np.ones((9, 1), np.uint8), iterations=1)
    line_ratio = float(np.mean((horizontal > 0) | (vertical > 0)))

    score = 0.0
    features: list[str] = []
    if text_ratio >= 0.055:
        score += 1.4
        features.append("dense_text")
    if text_ratio >= 0.085:
        score += 0.8
        features.append("very_dense_text")
    if edge_ratio >= 0.040:
        score += 0.7
        features.append("dense_edges")
    if line_ratio >= 0.012:
        score += 0.8
        features.append("diagram_or_table_lines")
    if light_bg_ratio >= 0.28:
        score += 0.6
        features.append("light_paper_background")
    if 0.015 <= skin_ratio <= 0.35 and text_ratio >= 0.035:
        score += 0.5
        features.append("portrait_plus_text")
    name_hint = any(token in name for token in ("knowledge", "poster", "timeline", "map", "graph"))
    if name_hint:
        score += 0.7
        features.append("name_hint")

    dense_diagram_override = text_ratio >= 0.45 and edge_ratio >= 0.11 and line_ratio >= 0.035
    paper_like = light_bg_ratio >= 0.34 or (light_bg_ratio >= 0.26 and high_sat_ratio < 0.055) or dense_diagram_override or name_hint
    product_photo_like = high_sat_ratio >= 0.055 and light_bg_ratio < 0.32 and skin_ratio > 0.18 and not dense_diagram_override
    is_knowledge = score >= KNOWLEDGE_POSTER_SCORE_THRESHOLD and paper_like and not product_photo_like
    return {
        "is_knowledge_poster": bool(is_knowledge),
        "knowledge_poster_score": round(score, 3),
        "knowledge_text_ratio": round(text_ratio, 4),
        "knowledge_edge_ratio": round(edge_ratio, 4),
        "knowledge_line_ratio": round(line_ratio, 4),
        "knowledge_dense_diagram_override": bool(dense_diagram_override),
        "knowledge_paper_like": bool(paper_like),
        "knowledge_product_photo_like": bool(product_photo_like),
        "knowledge_features": features,
    }


def decide_enhance_route(
    image_path: Path,
    original: np.ndarray,
    image_type: str,
    metrics: dict[str, float],
    knowledge_fields: dict[str, object],
) -> dict[str, object]:
    dims = image_dimensions(original)
    target_width, target_height, scale_ratio, profile = near_1080p_target_size(original)
    short_edge = int(dims.get("short_edge") or 0)
    blur_score = float(cv2.Laplacian(cv2.cvtColor(original, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
    severe_low_clarity = blur_score < 8.0
    is_knowledge = bool(knowledge_fields.get("is_knowledge_poster"))
    near_1080p = (
        target_width is not None
        and target_height is not None
        and short_edge >= NEAR_1080P_FAST_MIN_SHORT_EDGE
        and scale_ratio is not None
        and scale_ratio <= NEAR_1080P_FAST_MAX_SCALE_RATIO
    )
    can_fast = (
        image_type == "commercial_non_portrait"
        and near_1080p
        and not severe_low_clarity
        and not is_knowledge
    )
    if can_fast:
        reason = (
            f"near_1080p_fast_safe: input_short_edge={short_edge}; "
            f"scale_ratio={scale_ratio}; blur_score={blur_score:.2f}; not_knowledge_poster"
        )
        route = BALANCED_FAST_ROUTE
    elif is_knowledge:
        reason = f"knowledge_poster_mode: score={knowledge_fields.get('knowledge_poster_score')}; features={','.join(knowledge_fields.get('knowledge_features') or [])}"
        route = "knowledge_poster_mode"
    else:
        reason = (
            f"safe_beta_realesrgan_protected: input_short_edge={short_edge}; "
            f"scale_ratio={scale_ratio}; blur_score={blur_score:.2f}; profile={profile}"
        )
        route = "safe_beta_realesrgan_protected"
    return {
        "enhance_route": route,
        "route_decision_reason": reason,
        "already_1080p_or_near_1080p": bool(near_1080p),
        "input_to_output_scale_ratio": scale_ratio if scale_ratio is not None else "not_applicable",
        "target_width": target_width,
        "target_height": target_height,
        "target_profile": profile,
        "blur_score": round(blur_score, 3),
        "use_fast_route": bool(can_fast),
    }


def constrain_png_final_to_true_1080p(image: np.ndarray) -> tuple[np.ndarray | None, dict[str, object]]:
    target_width, target_height, profile = true_1080p_target_size(image)
    if target_width is None or target_height is None:
        return None, {"output_resolution_profile": profile, **image_dimensions(image)}
    if target_width == image.shape[1] and target_height == image.shape[0]:
        return image, {"output_resolution_profile": profile, **image_dimensions(image)}
    resized = cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_AREA)
    return resized, {"output_resolution_profile": profile, **image_dimensions(resized)}


def resize_to_target_for_fidelity(image: np.ndarray, target_width: int, target_height: int) -> np.ndarray:
    if image.shape[1] == target_width and image.shape[0] == target_height:
        return image
    interpolation = cv2.INTER_AREA if image.shape[1] > target_width or image.shape[0] > target_height else cv2.INTER_LANCZOS4
    return cv2.resize(image, (target_width, target_height), interpolation=interpolation)


def build_target_edge_text_mask(original_target: np.ndarray) -> np.ndarray:
    masks = build_protection_masks(original_target)
    text_mask = cv2.dilate(masks["text_like"], np.ones((5, 5), np.uint8), iterations=1)
    edge_mask = cv2.dilate(masks["high_contrast_edge"], np.ones((3, 3), np.uint8), iterations=1)
    subject_edge = cv2.bitwise_and(edge_mask, cv2.bitwise_or(text_mask, masks["high_sat"]))
    mask = cv2.bitwise_or(text_mask, subject_edge)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
    return cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), 0.65)


def build_target_high_value_mask(original_target: np.ndarray) -> np.ndarray:
    masks = build_protection_masks(original_target)
    gray = cv2.cvtColor(original_target, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(original_target, cv2.COLOR_BGR2HSV)
    _, s, v = cv2.split(hsv)
    local_mean = cv2.GaussianBlur(gray, (0, 0), 1.8)
    local_detail = cv2.absdiff(gray, local_mean)
    fine_mean = cv2.GaussianBlur(gray, (0, 0), 0.9)
    fine_detail = cv2.absdiff(gray, fine_mean)

    text_mask = cv2.dilate(masks["text_like"], np.ones((7, 7), np.uint8), iterations=1)
    edge_mask = cv2.dilate(masks["high_contrast_edge"], np.ones((3, 3), np.uint8), iterations=1)
    material_mask = cv2.dilate(masks["high_sat"], np.ones((5, 5), np.uint8), iterations=1)
    bright_structure = ((edge_mask > 0) & (v > 82) & (local_detail > 4)).astype(np.uint8) * 255
    small_object = ((local_detail > 7) & (fine_detail > 3) & (s > 16) & (v > 42)).astype(np.uint8) * 255
    small_object = cv2.morphologyEx(small_object, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)

    mask = cv2.bitwise_or(text_mask, edge_mask)
    mask = cv2.bitwise_or(mask, material_mask)
    mask = cv2.bitwise_or(mask, bright_structure)
    mask = cv2.bitwise_or(mask, small_object)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
    return cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), 0.58)


def target_size_fidelity_blend(original: np.ndarray, model_output: np.ndarray) -> tuple[np.ndarray | None, dict[str, object]]:
    target_width, target_height, profile = true_1080p_target_size(model_output)
    if target_width is None or target_height is None:
        return None, {"output_resolution_profile": profile, **image_dimensions(model_output)}

    original_target = resize_to_target_for_fidelity(original, target_width, target_height)
    enhanced_target = resize_to_target_for_fidelity(model_output, target_width, target_height)
    masks = build_protection_masks(original_target)

    alpha = np.full(original_target.shape[:2], 0.52, dtype=np.float32)
    material_mask = cv2.dilate(masks["high_sat"], np.ones((5, 5), np.uint8), iterations=1)
    edge_mask = cv2.dilate(masks["high_contrast_edge"], np.ones((3, 3), np.uint8), iterations=1)
    text_mask = cv2.dilate(masks["text_like"], np.ones((7, 7), np.uint8), iterations=1)

    alpha[material_mask > 0] = 0.66
    alpha[edge_mask > 0] = 0.46
    alpha[text_mask > 0] = 0.26
    alpha = cv2.GaussianBlur(alpha, (0, 0), 0.9)[:, :, None]

    blended = original_target.astype(np.float32) * (1.0 - alpha) + enhanced_target.astype(np.float32) * alpha
    restored = apply_light_edge_restore(np.clip(blended, 0, 255).astype(np.uint8), original_target, enhanced_target)
    return restored, {"output_resolution_profile": profile, **image_dimensions(restored)}


def compute_safe_beta_quality_scores(original: np.ndarray, final_png: np.ndarray) -> dict[str, object]:
    try:
        scores = compare_quality(original, final_png)
    except Exception as exc:
        return {"quality_score_status": "failed", "quality_score_reason": tail_text(exc, 180)}
    return {"quality_score_status": "available", **scores}


def apply_light_edge_restore(image: np.ndarray, original_target: np.ndarray, enhanced_target: np.ndarray | None = None) -> np.ndarray:
    edge_mask = build_target_edge_text_mask(original_target)[:, :, None]
    high_value_mask = build_target_high_value_mask(original_target)[:, :, None]
    blurred = cv2.GaussianBlur(image, (0, 0), 0.72).astype(np.float32)
    original_blurred = cv2.GaussianBlur(original_target, (0, 0), 0.72).astype(np.float32)
    image_detail = image.astype(np.float32) - blurred
    original_detail = original_target.astype(np.float32) - original_blurred
    detail = image_detail * 0.32 + original_detail * 0.64
    if enhanced_target is not None:
        enhanced_blurred = cv2.GaussianBlur(enhanced_target, (0, 0), 0.72).astype(np.float32)
        enhanced_detail = enhanced_target.astype(np.float32) - enhanced_blurred
        fine_enhanced_blurred = cv2.GaussianBlur(enhanced_target, (0, 0), 0.42).astype(np.float32)
        fine_enhanced_detail = enhanced_target.astype(np.float32) - fine_enhanced_blurred
        detail += enhanced_detail * 0.22 + fine_enhanced_detail * 0.12
    restore_mask = np.clip(edge_mask * 1.0 + high_value_mask * 0.70, 0.0, 1.0)
    detail = np.clip(detail, -22.0, 22.0)
    restored = image.astype(np.float32) + detail * restore_mask
    restored = apply_high_value_micro_contrast(np.clip(restored, 0, 255).astype(np.uint8), original_target, enhanced_target, high_value_mask)
    restored = apply_low_value_background_smoothing(np.clip(restored, 0, 255).astype(np.uint8), original_target)
    return np.clip(restored, 0, 255).astype(np.uint8)


def apply_high_value_micro_contrast(
    image: np.ndarray,
    original_target: np.ndarray,
    enhanced_target: np.ndarray | None,
    high_value_mask: np.ndarray,
) -> np.ndarray:
    gray = cv2.cvtColor(original_target, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 55, 150)
    edge_mask = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1).astype(np.float32) / 255.0
    edge_mask = cv2.GaussianBlur(edge_mask, (0, 0), 0.48)[:, :, None]

    base = image.astype(np.float32)
    micro_blur = cv2.GaussianBlur(image, (0, 0), 0.48).astype(np.float32)
    micro_detail = base - micro_blur
    original_micro = original_target.astype(np.float32) - cv2.GaussianBlur(original_target, (0, 0), 0.48).astype(np.float32)
    micro_detail = micro_detail * 0.24 + original_micro * 0.42
    if enhanced_target is not None:
        enhanced_micro = enhanced_target.astype(np.float32) - cv2.GaussianBlur(enhanced_target, (0, 0), 0.48).astype(np.float32)
        micro_detail += enhanced_micro * 0.24

    micro_detail = np.clip(micro_detail, -14.0, 14.0)
    mask = np.clip(high_value_mask * 0.70 + edge_mask * 0.42, 0.0, 0.92)
    restored = np.clip(base + micro_detail * mask, 0, 255).astype(np.uint8)
    return apply_high_value_luma_clarity(restored, high_value_mask, edge_mask)


def apply_high_value_luma_clarity(image: np.ndarray, high_value_mask: np.ndarray, edge_mask: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.45, tileGridSize=(8, 8))
    l_clahe = clahe.apply(l_channel)
    bilateral = cv2.bilateralFilter(l_channel, 5, 18, 3)
    l_detail = np.clip(l_channel.astype(np.float32) - bilateral.astype(np.float32), -12.0, 12.0)
    l_target = l_clahe.astype(np.float32) * 0.42 + np.clip(l_channel.astype(np.float32) + l_detail * 0.62, 0, 255) * 0.58
    clarity_mask = np.clip(high_value_mask[:, :, 0] * 0.24 + edge_mask[:, :, 0] * 0.18, 0.0, 0.34)
    l_new = l_channel.astype(np.float32) * (1.0 - clarity_mask) + l_target * clarity_mask
    merged = cv2.merge((np.clip(l_new, 0, 255).astype(np.uint8), a_channel, b_channel))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def apply_low_value_background_smoothing(image: np.ndarray, original_target: np.ndarray) -> np.ndarray:
    masks = build_protection_masks(original_target)
    gray = cv2.cvtColor(original_target, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(original_target, cv2.COLOR_BGR2HSV)
    _, s, v = cv2.split(hsv)

    protected = cv2.bitwise_or(masks["text_like"], masks["high_contrast_edge"])
    protected = cv2.bitwise_or(protected, masks["high_sat"])
    protected = cv2.bitwise_or(protected, masks["skin"])
    low_information = (protected == 0) & (s < 82) & (v < 188) & (gray > 18)
    smooth_mask = cv2.morphologyEx(low_information.astype(np.uint8) * 255, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8), iterations=1)
    smooth_mask = cv2.GaussianBlur(smooth_mask.astype(np.float32) / 255.0, (0, 0), 1.45)[:, :, None]
    smooth_mask *= 0.26

    smoothed = cv2.GaussianBlur(image, (0, 0), 0.55).astype(np.float32)
    return np.clip(image.astype(np.float32) * (1.0 - smooth_mask) + smoothed * smooth_mask, 0, 255).astype(np.uint8)


def balanced_fast_quality_pass(
    original_target: np.ndarray,
    base: np.ndarray,
    text_mask: np.ndarray,
    edge_mask: np.ndarray,
    material_mask: np.ndarray,
    smooth_mask: np.ndarray,
    timing: dict[str, object],
) -> np.ndarray:
    started = time.perf_counter()
    scale = 1.35
    work_size = (max(1, int(round(base.shape[1] * scale))), max(1, int(round(base.shape[0] * scale))))
    work = cv2.resize(base, work_size, interpolation=cv2.INTER_LANCZOS4)
    ref_work = cv2.resize(original_target, work_size, interpolation=cv2.INTER_LANCZOS4)
    text_work = cv2.resize(text_mask, work_size, interpolation=cv2.INTER_AREA)
    edge_work = cv2.resize(edge_mask, work_size, interpolation=cv2.INTER_AREA)
    material_work = cv2.resize(material_mask, work_size, interpolation=cv2.INTER_AREA)
    smooth_work = cv2.resize(smooth_mask[:, :, 0], work_size, interpolation=cv2.INTER_AREA)
    timing["intermediate_resize_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    gray = cv2.cvtColor(ref_work, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(ref_work, cv2.COLOR_BGR2HSV)
    _, s, v = cv2.split(hsv)
    adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 23, 6)
    fine_edges = cv2.Canny(gray, 48, 138, L2gradient=True)
    line_h = cv2.morphologyEx(fine_edges, cv2.MORPH_OPEN, np.ones((1, 7), np.uint8), iterations=1)
    line_v = cv2.morphologyEx(fine_edges, cv2.MORPH_OPEN, np.ones((7, 1), np.uint8), iterations=1)
    text_line = cv2.bitwise_or(cv2.bitwise_or(adaptive, line_h), line_v)
    text_line = cv2.bitwise_and(text_line, cv2.dilate(fine_edges, np.ones((3, 3), np.uint8), iterations=1))
    text_line = cv2.bitwise_or(text_line, (text_work > 24).astype(np.uint8) * 255)
    text_line = cv2.morphologyEx(text_line, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8), iterations=1)

    local_mean = cv2.GaussianBlur(gray, (0, 0), 1.0)
    local_detail = cv2.absdiff(gray, local_mean)
    metal_like = ((material_work > 18) | ((s > 24) & (v > 48) & (local_detail > 4))).astype(np.uint8) * 255
    metal_like = cv2.dilate(metal_like, np.ones((3, 3), np.uint8), iterations=1)
    roi_mask = np.clip(
        (text_line.astype(np.float32) / 255.0) * 0.88
        + (edge_work.astype(np.float32) / 255.0) * 0.38
        + (metal_like.astype(np.float32) / 255.0) * 0.42,
        0.0,
        1.0,
    )
    roi_mask = cv2.GaussianBlur(roi_mask, (0, 0), 0.42)[:, :, None]
    background_mask = np.clip((smooth_work.astype(np.float32) / 255.0) * (1.0 - roi_mask[:, :, 0]), 0.0, 1.0)[:, :, None]
    timing["balanced_mask_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    lab = cv2.cvtColor(work, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.55, tileGridSize=(8, 8))
    l_clahe = clahe.apply(l_channel)
    l_small = cv2.GaussianBlur(l_channel, (0, 0), 0.36).astype(np.float32)
    l_mid = cv2.GaussianBlur(l_channel, (0, 0), 0.92).astype(np.float32)
    fine_detail = np.clip(l_channel.astype(np.float32) - l_small, -10.0, 10.0)
    mid_detail = np.clip(l_channel.astype(np.float32) - l_mid, -15.0, 15.0)
    l_target = (
        l_channel.astype(np.float32) * 0.58
        + l_clahe.astype(np.float32) * 0.22
        + np.clip(l_channel.astype(np.float32) + fine_detail * 1.05 + mid_detail * 0.34, 0, 255) * 0.20
    )
    l_new = l_channel.astype(np.float32) * (1.0 - roi_mask[:, :, 0] * 0.62) + l_target * (roi_mask[:, :, 0] * 0.62)
    work = cv2.cvtColor(cv2.merge((np.clip(l_new, 0, 255).astype(np.uint8), a_channel, b_channel)), cv2.COLOR_LAB2BGR)
    timing["text_line_enhance_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    small_blur = cv2.GaussianBlur(work, (0, 0), 0.34).astype(np.float32)
    medium_blur = cv2.GaussianBlur(work, (0, 0), 0.78).astype(np.float32)
    fine_rgb = np.clip(work.astype(np.float32) - small_blur, -12.0, 12.0)
    mid_rgb = np.clip(work.astype(np.float32) - medium_blur, -16.0, 16.0)
    detail_gain = np.clip(roi_mask * 0.72 + (metal_like.astype(np.float32) / 255.0)[:, :, None] * 0.20, 0.0, 0.82)
    work = np.clip(work.astype(np.float32) + fine_rgb * detail_gain + mid_rgb * np.clip(detail_gain * 0.28, 0.0, 0.24), 0, 255).astype(np.uint8)
    timing["local_detail_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    soft = cv2.GaussianBlur(work, (0, 0), 0.52).astype(np.float32)
    work = np.clip(work.astype(np.float32) * (1.0 - background_mask * 0.24) + soft * (background_mask * 0.24), 0, 255).astype(np.uint8)
    timing["texture_suppress_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    down = cv2.resize(work, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_AREA)
    final_mask = cv2.GaussianBlur(
        np.clip((text_mask.astype(np.float32) / 255.0) * 0.65 + (edge_mask.astype(np.float32) / 255.0) * 0.26 + (material_mask.astype(np.float32) / 255.0) * 0.28, 0.0, 1.0),
        (0, 0),
        0.52,
    )[:, :, None]
    refined = np.clip(base.astype(np.float32) * (1.0 - final_mask * 0.90) + down.astype(np.float32) * (final_mask * 0.90), 0, 255).astype(np.uint8)
    final_blur = cv2.GaussianBlur(refined, (0, 0), 0.60).astype(np.float32)
    original_blur = cv2.GaussianBlur(original_target, (0, 0), 0.60).astype(np.float32)
    refined_detail = np.clip(refined.astype(np.float32) - final_blur, -18.0, 18.0)
    original_detail = np.clip(original_target.astype(np.float32) - original_blur, -18.0, 18.0)
    final_detail = refined_detail * 0.35 + original_detail * 1.10
    final_boost_mask = cv2.GaussianBlur(
        np.clip((text_mask.astype(np.float32) / 255.0) * 0.78 + (edge_mask.astype(np.float32) / 255.0) * 0.52 + (material_mask.astype(np.float32) / 255.0) * 0.42, 0.0, 1.0),
        (0, 0),
        0.44,
    )[:, :, None]
    refined = np.clip(refined.astype(np.float32) + final_detail * np.clip(final_boost_mask * 1.15, 0.0, 1.15), 0, 255).astype(np.uint8)
    timing["balanced_quality_seconds"] = round(time.perf_counter() - started, 3)
    return refined


def fast_safe_enhance_near_1080p(original: np.ndarray, route_decision: dict[str, object]) -> tuple[np.ndarray | None, dict[str, object], dict[str, object]]:
    timing = default_enhance_timing_fields(BALANCED_FAST_ROUTE)
    timing.update(
        {
            "route_decision_reason": route_decision.get("route_decision_reason") or "",
            "already_1080p_or_near_1080p": True,
            "input_to_output_scale_ratio": route_decision.get("input_to_output_scale_ratio", "not_applicable"),
            "fast_quality_level": "balanced",
        }
    )
    target_width = route_decision.get("target_width")
    target_height = route_decision.get("target_height")
    if not isinstance(target_width, int) or not isinstance(target_height, int):
        return None, {"output_resolution_profile": route_decision.get("target_profile") or "invalid_fast_route_target", **image_dimensions(original)}, timing

    started = time.perf_counter()
    interpolation = cv2.INTER_AREA if min(original.shape[:2]) > TRUE_1080P_SHORT_EDGE else cv2.INTER_LANCZOS4
    original_target = cv2.resize(original, (target_width, target_height), interpolation=interpolation)
    timing["resize_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    base = cv2.bilateralFilter(original_target, 5, 18, 3)
    base = np.clip(original_target.astype(np.float32) * 0.95 + base.astype(np.float32) * 0.05, 0, 255).astype(np.uint8)
    timing["prefilter_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    gray = cv2.cvtColor(original_target, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(original_target, cv2.COLOR_BGR2HSV)
    _, s, v = cv2.split(hsv)
    edges = cv2.Canny(gray, 55, 145)
    local_mean = cv2.GaussianBlur(gray, (0, 0), 1.2)
    local_detail = cv2.absdiff(gray, local_mean)
    timing["roi_detect_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    masks = build_protection_masks(original_target)
    adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 7)
    text_mask = cv2.dilate(cv2.bitwise_or(masks["text_like"], cv2.bitwise_and(adaptive, cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1))), np.ones((5, 5), np.uint8), iterations=1)
    edge_mask = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    material_mask = ((s > 28) & (v > 44) & (local_detail > 4)).astype(np.uint8) * 255
    material_mask = cv2.dilate(material_mask, np.ones((3, 3), np.uint8), iterations=1)
    protected_mask = cv2.bitwise_or(text_mask, edge_mask)
    protected_mask = cv2.bitwise_or(protected_mask, material_mask)
    high_value = cv2.GaussianBlur(protected_mask.astype(np.float32) / 255.0, (0, 0), 0.55)[:, :, None]
    low_value = ((protected_mask == 0) & (s < 80) & (local_detail < 7)).astype(np.uint8) * 255
    low_value = cv2.morphologyEx(low_value, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8), iterations=1)
    smooth_mask = cv2.GaussianBlur(low_value.astype(np.float32) / 255.0, (0, 0), 1.25)[:, :, None]
    timing["mask_build_seconds"] = round(time.perf_counter() - started, 3)

    enhanced = balanced_fast_quality_pass(original_target, base, text_mask, edge_mask, material_mask, smooth_mask, timing)

    fields = {
        "output_resolution_profile": route_decision.get("target_profile") or "short_edge_1080",
        **image_dimensions(enhanced),
        "enhance_route": BALANCED_FAST_ROUTE,
        "route_decision_reason": route_decision.get("route_decision_reason") or "",
        "already_1080p_or_near_1080p": True,
        "input_to_output_scale_ratio": route_decision.get("input_to_output_scale_ratio", "not_applicable"),
        "realesrgan_used": False,
        "uses_realesrgan": False,
        "fast_route_skipped_realesrgan": True,
        "fast_route_skipped_protected_heavy_chain": True,
        "fast_quality_level": "balanced",
    }
    return enhanced, fields, timing


def knowledge_poster_local_enhance(original: np.ndarray, route_decision: dict[str, object]) -> tuple[np.ndarray | None, dict[str, object], dict[str, object]]:
    timing = default_enhance_timing_fields("knowledge_poster_mode")
    timing.update(
        {
            "route_decision_reason": route_decision.get("route_decision_reason") or "",
            "already_1080p_or_near_1080p": route_decision.get("already_1080p_or_near_1080p", False),
            "input_to_output_scale_ratio": route_decision.get("input_to_output_scale_ratio", "not_applicable"),
        }
    )
    target_width = route_decision.get("target_width")
    target_height = route_decision.get("target_height")
    if not isinstance(target_width, int) or not isinstance(target_height, int):
        return None, {"output_resolution_profile": route_decision.get("target_profile") or "invalid_knowledge_target", **image_dimensions(original)}, timing

    started = time.perf_counter()
    interpolation = cv2.INTER_AREA if min(original.shape[:2]) > TRUE_1080P_SHORT_EDGE else cv2.INTER_LANCZOS4
    original_target = cv2.resize(original, (target_width, target_height), interpolation=interpolation)
    timing["resize_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    base = cv2.bilateralFilter(original_target, 5, 22, 5)
    base = np.clip(original_target.astype(np.float32) * 0.82 + base.astype(np.float32) * 0.18, 0, 255).astype(np.uint8)
    timing["prefilter_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    gray = cv2.cvtColor(original_target, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(original_target, cv2.COLOR_BGR2HSV)
    _, s, v = cv2.split(hsv)
    edges = cv2.Canny(gray, 48, 135)
    adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 7)
    line_h = cv2.morphologyEx(edges, cv2.MORPH_OPEN, np.ones((1, 7), np.uint8), iterations=1)
    line_v = cv2.morphologyEx(edges, cv2.MORPH_OPEN, np.ones((7, 1), np.uint8), iterations=1)
    timing["roi_detect_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    text_line = cv2.bitwise_or(cv2.bitwise_and(adaptive, cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)), line_h)
    text_line = cv2.bitwise_or(text_line, line_v)
    text_line = cv2.dilate(text_line, np.ones((3, 3), np.uint8), iterations=1)
    text_line_mask = cv2.GaussianBlur(text_line.astype(np.float32) / 255.0, (0, 0), 0.48)[:, :, None]
    paper_mask = ((s < 75) & (v > 92) & (text_line == 0)).astype(np.uint8) * 255
    paper_mask = cv2.morphologyEx(paper_mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8), iterations=1)
    paper_smooth_mask = cv2.GaussianBlur(paper_mask.astype(np.float32) / 255.0, (0, 0), 1.35)[:, :, None]
    timing["mask_build_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    lab = cv2.cvtColor(base, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    small_blur = cv2.GaussianBlur(l_channel, (0, 0), 0.42).astype(np.float32)
    medium_blur = cv2.GaussianBlur(l_channel, (0, 0), 0.9).astype(np.float32)
    fine_detail = np.clip(l_channel.astype(np.float32) - small_blur, -10.0, 10.0)
    mid_detail = np.clip(l_channel.astype(np.float32) - medium_blur, -14.0, 14.0)
    line_gain = np.clip(text_line_mask[:, :, 0] * 0.58, 0.0, 0.58)
    l_new = np.clip(l_channel.astype(np.float32) + fine_detail * line_gain + mid_detail * np.clip(line_gain * 0.34, 0, 0.22), 0, 255)
    enhanced = cv2.cvtColor(cv2.merge((l_new.astype(np.uint8), a_channel, b_channel)), cv2.COLOR_LAB2BGR)
    timing["text_line_enhance_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    micro_blur = cv2.GaussianBlur(enhanced, (0, 0), 0.50).astype(np.float32)
    micro_detail = np.clip(enhanced.astype(np.float32) - micro_blur, -8.0, 8.0)
    enhanced = np.clip(enhanced.astype(np.float32) + micro_detail * np.clip(text_line_mask * 0.25, 0, 0.25), 0, 255).astype(np.uint8)
    timing["local_detail_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    paper_soft = cv2.GaussianBlur(enhanced, (0, 0), 0.52).astype(np.float32)
    suppress = np.clip(paper_smooth_mask * 0.20, 0.0, 0.20)
    enhanced = np.clip(enhanced.astype(np.float32) * (1.0 - suppress) + paper_soft * suppress, 0, 255).astype(np.uint8)
    timing["texture_suppress_seconds"] = round(time.perf_counter() - started, 3)

    fields = {
        "output_resolution_profile": route_decision.get("target_profile") or "short_edge_1080",
        **image_dimensions(enhanced),
        "enhance_route": "knowledge_poster_mode",
        "route_decision_reason": route_decision.get("route_decision_reason") or "",
        "already_1080p_or_near_1080p": route_decision.get("already_1080p_or_near_1080p", False),
        "input_to_output_scale_ratio": route_decision.get("input_to_output_scale_ratio", "not_applicable"),
        "realesrgan_used": False,
        "uses_realesrgan": False,
        "fast_route_skipped_realesrgan": True,
    }
    return enhanced, fields, timing


def slowest_stage(timing: dict[str, object]) -> tuple[str, float]:
    values: list[tuple[str, float]] = []
    for key in TIMED_ENHANCE_STAGE_KEYS:
        try:
            value = float(timing.get(key) or 0)
        except (TypeError, ValueError):
            value = 0.0
        values.append((key, value))
    return max(values, key=lambda item: item[1]) if values else ("not_applicable", 0.0)


def speed_fields_for_route(route: str, actual_seconds: float, timing: dict[str, object]) -> dict[str, object]:
    if route in {"already_1080p_fast_safe_enhance", BALANCED_FAST_ROUTE}:
        speed_class = "near_1080p_fast_commercial"
        target = "8-15"
        risk = actual_seconds > 25
    elif route in {"knowledge_poster_mode", "dense_chinese_poster_mode", "text_dense_visual_mode"}:
        speed_class = "knowledge_dense_poster"
        target = "20-40"
        risk = actual_seconds > 60
    else:
        speed_class = "heavy_low_clarity_or_general"
        target = "30-60"
        risk = actual_seconds > 90
    stage_name, stage_seconds = slowest_stage(timing)
    return {
        "speed_class": speed_class,
        "speed_target_seconds": target,
        "speed_actual_seconds": round(actual_seconds, 3),
        "speed_risk": bool(risk),
        "batch_estimated_10_images_seconds": round(actual_seconds * 10, 3),
        "batch_estimated_20_images_seconds": round(actual_seconds * 20, 3),
        "slowest_stage_name": stage_name,
        "slowest_stage_seconds": round(stage_seconds, 3),
        "heavy_route_speed_risk": bool(speed_class == "heavy_low_clarity_or_general" and actual_seconds > 90),
    }


def route_diagnostics_consistency(rows: list[dict[str, object]]) -> dict[str, object]:
    blockers: list[str] = []
    for row in rows:
        file_name = str(row.get("file") or row.get("input_name") or "unknown")
        route = str(row.get("enhance_route") or "")
        if not route:
            blockers.append(f"{file_name}: missing enhance_route")
        if not row.get("route_decision_reason"):
            blockers.append(f"{file_name}: missing route_decision_reason")
        if row.get("roi_evidence_status") != "available":
            blockers.append(f"{file_name}: roi_evidence_status={row.get('roi_evidence_status') or 'missing'}")
        if row.get("speed_actual_seconds") in ("", None):
            blockers.append(f"{file_name}: missing speed_actual_seconds")
        if route in {"already_1080p_fast_safe_enhance", BALANCED_FAST_ROUTE}:
            if bool(row.get("uses_realesrgan")):
                blockers.append(f"{file_name}: fast route uses_realesrgan=true")
            if not bool(row.get("fast_route_skipped_realesrgan")):
                blockers.append(f"{file_name}: fast route did not mark skipped_realesrgan")
            if row.get("fast_route_final_pass") is not True:
                blockers.append(f"{file_name}: fast_route_final_pass={row.get('fast_route_final_pass')}")
            try:
                if float(row.get("speed_actual_seconds") or 0) > 30.0:
                    blockers.append(f"{file_name}: fast route speed_actual_seconds>30")
            except (TypeError, ValueError):
                blockers.append(f"{file_name}: invalid speed_actual_seconds")
    return {
        "diagnostics_consistency": "PASS" if not blockers else "BLOCKED",
        "diagnostics_consistency_blockers": blockers,
    }


def fast_route_pass_fields(route: str, speed_fields: dict[str, object], quality_fields: dict[str, object], output_fields: dict[str, object]) -> dict[str, object]:
    if route not in {"already_1080p_fast_safe_enhance", BALANCED_FAST_ROUTE}:
        return {}
    text_score = float(quality_fields.get("text_clarity_score") or 0.0)
    edge_score = float(quality_fields.get("edge_quality_score") or 0.0)
    texture_score = float(quality_fields.get("texture_score") or 0.0)
    color_score = float(quality_fields.get("color_fidelity_score") or 0.0)
    fidelity_score = float(quality_fields.get("fidelity_score") or 0.0)
    speed_seconds = float(speed_fields.get("speed_actual_seconds") or 9999.0)
    uses_realesrgan = bool(output_fields.get("uses_realesrgan"))
    skipped_realesrgan = bool(output_fields.get("fast_route_skipped_realesrgan"))
    skipped_heavy = bool(output_fields.get("fast_route_skipped_protected_heavy_chain"))
    speed_pass = speed_seconds <= 20.0 and not bool(speed_fields.get("speed_risk"))
    quality_reasons: list[str] = []
    if text_score < 45.0:
        quality_reasons.append(f"text_clarity_score={text_score:.2f}<45")
    if edge_score < 45.0:
        quality_reasons.append(f"edge_quality_score={edge_score:.2f}<45")
    if texture_score < 2.0:
        quality_reasons.append(f"texture_score={texture_score:.2f}<2")
    if color_score < 90.0:
        quality_reasons.append(f"color_fidelity_score={color_score:.2f}<90")
    if fidelity_score < 54.0:
        quality_reasons.append(f"fidelity_score={fidelity_score:.2f}<54")
    if bool(quality_fields.get("is_pseudo_hd")) and text_score < 50.0 and edge_score < 50.0:
        quality_reasons.append("pseudo_hd_without_text_or_edge_gain")
    quality_pass = not quality_reasons
    final_pass = speed_pass and quality_pass and skipped_realesrgan and skipped_heavy and not uses_realesrgan
    return {
        "fast_route_speed_pass": bool(speed_pass),
        "fast_route_quality_pass": bool(quality_pass),
        "fast_route_final_pass": bool(final_pass),
        "fast_route_quality_grade": "B+" if final_pass else "BELOW_B_PLUS",
        "fast_route_quality_reason": "balanced_fast_quality_floor_passed" if quality_pass else "; ".join(quality_reasons),
        "fast_route_speed_reason": "within_20s_fast_route_limit" if speed_pass else f"speed_actual_seconds={speed_seconds:.3f}>20",
        "fast_route_uses_realesrgan_blocker": bool(uses_realesrgan or not skipped_realesrgan),
        "fast_route_heavy_chain_skipped": bool(skipped_heavy),
    }


def size_ratio(output_size: int | None, input_size: int | None) -> float | None:
    if not input_size or output_size is None:
        return None
    return round(output_size / input_size, 4)


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


def build_contact_sheet(original: np.ndarray, blend35: np.ndarray, protected35: np.ndarray) -> np.ndarray:
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
    return sheet


def make_contact_sheet(original: np.ndarray, blend35: np.ndarray, protected35: np.ndarray, path: Path) -> None:
    sheet = build_contact_sheet(original, blend35, protected35)
    write_image(path, sheet)


def make_contact_sheet_light(original: np.ndarray, blend35: np.ndarray, protected35: np.ndarray, path: Path) -> None:
    sheet = build_contact_sheet(original, blend35, protected35)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(
        ".jpg",
        sheet,
        [int(cv2.IMWRITE_JPEG_QUALITY), CONTACT_SHEET_LIGHT_JPEG_QUALITY],
    )
    if not ok:
        raise RuntimeError(f"Cannot encode contact sheet preview: {path}")
    encoded.tofile(str(path))


def roi_regions_for_route(route: str, width: int, height: int) -> list[tuple[str, tuple[float, float, float, float]]]:
    if route == "knowledge_poster_mode":
        return [
            ("top_left_text", (0.03, 0.04, 0.28, 0.24)),
            ("top_right_graph", (0.68, 0.04, 0.97, 0.30)),
            ("center_face", (0.34, 0.20, 0.66, 0.58)),
            ("middle_diagram", (0.04, 0.32, 0.32, 0.58)),
            ("bottom_timeline", (0.06, 0.70, 0.94, 0.95)),
        ]
    return [
        ("main_text", (0.34, 0.28, 0.66, 0.50)),
        ("product_numbers", (0.32, 0.38, 0.68, 0.70)),
        ("product_edge", (0.20, 0.18, 0.82, 0.82)),
        ("material_texture", (0.30, 0.04, 0.70, 0.22)),
        ("background_blur", (0.02, 0.05, 0.24, 0.24)),
    ]


def crop_fraction(image: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
    height, width = image.shape[:2]
    x1 = max(0, min(width - 1, int(round(width * box[0]))))
    y1 = max(0, min(height - 1, int(round(height * box[1]))))
    x2 = max(x1 + 1, min(width, int(round(width * box[2]))))
    y2 = max(y1 + 1, min(height, int(round(height * box[3]))))
    return image[y1:y2, x1:x2]


def make_roi_evidence_sheet(original: np.ndarray, final_png: np.ndarray, route: str, path: Path) -> None:
    original_target = resize_to_match(original, final_png)
    rows: list[np.ndarray] = []
    for label, box in roi_regions_for_route(route, final_png.shape[1], final_png.shape[0]):
        before = fit_height(crop_fraction(original_target, box), 220)
        after = fit_height(crop_fraction(final_png, box), 220)
        label_bar = np.full((32, before.shape[1] + after.shape[1] + 8, 3), 245, dtype=np.uint8)
        cv2.putText(label_bar, label, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (30, 30, 30), 1, cv2.LINE_AA)
        spacer = np.full((max(before.shape[0], after.shape[0]), 8, 3), 235, dtype=np.uint8)
        row_height = max(before.shape[0], after.shape[0])
        before_canvas = np.full((row_height, before.shape[1], 3), 245, dtype=np.uint8)
        after_canvas = np.full((row_height, after.shape[1], 3), 245, dtype=np.uint8)
        before_canvas[: before.shape[0], : before.shape[1]] = before
        after_canvas[: after.shape[0], : after.shape[1]] = after
        rows.append(np.vstack([label_bar, np.hstack([before_canvas, spacer, after_canvas])]))
    width = max(row.shape[1] for row in rows)
    normalized = []
    for row in rows:
        if row.shape[1] == width:
            normalized.append(row)
            continue
        canvas = np.full((row.shape[0], width, 3), 245, dtype=np.uint8)
        canvas[:, : row.shape[1]] = row
        normalized.append(canvas)
    sheet = np.vstack(normalized)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".jpg", sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise RuntimeError(f"Cannot encode ROI evidence: {path}")
    encoded.tofile(str(path))


def default_jpg95_candidate_fields(status: str, reason: str, enhanced_path: Path | None = None, output_size: int | None = None) -> dict[str, object]:
    return {
        "original_png_output_path": str(enhanced_path) if enhanced_path else "",
        "original_png_output_size_bytes": output_size,
        "jpg95_candidate_path": "",
        "jpg95_candidate_size_bytes": None,
        "jpg95_candidate_saved_ratio": None,
        "jpg95_candidate_format": "jpg",
        "jpg95_candidate_quality": JPG95_CANDIDATE_QUALITY,
        "jpg95_candidate_role": "final_candidate",
        "jpg95_candidate_status": status,
        "jpg95_candidate_reason": reason,
        "final_output_source": "png_main",
        "final_output_fallback_reason": "jpg95_candidate_requires_manual_review" if status == "candidate_for_review" else reason,
    }


def default_light_delivery_fields(status: str, reason: str) -> dict[str, object]:
    return {
        "light_delivery_path": "",
        "light_delivery_size_bytes": None,
        "light_delivery_format": "jpg",
        "light_delivery_quality": JPG95_CANDIDATE_QUALITY,
        "light_delivery_role": "delivery_light_copy",
        "light_delivery_source": "jpg95_candidate",
        "light_delivery_status": status,
        "light_delivery_reason": reason,
        "light_delivery_saved_ratio": None,
    }


def remove_file_quietly(path: Path) -> None:
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except OSError:
        pass


def make_jpg95_candidate(
    *,
    image_path: Path,
    enhanced_path: Path,
    candidate_path: Path,
    image_type: str,
    metrics: dict[str, float],
    input_size: int | None,
    output_size: int | None,
) -> dict[str, object]:
    base_fields = default_jpg95_candidate_fields("not_applicable", "candidate_not_evaluated", enhanced_path, output_size)
    if image_type != "commercial_non_portrait":
        return {**base_fields, "jpg95_candidate_reason": f"image_type_not_allowed: {image_type}", "final_output_fallback_reason": f"image_type_not_allowed: {image_type}"}

    has_alpha, alpha_reason = real_alpha_status(image_path)
    if has_alpha is None:
        return {**base_fields, "jpg95_candidate_reason": alpha_reason, "final_output_fallback_reason": alpha_reason}
    if has_alpha:
        return {**base_fields, "jpg95_candidate_reason": alpha_reason, "final_output_fallback_reason": alpha_reason}

    text_ratio = float(metrics.get("text_ratio") or 0.0)
    if text_ratio >= JPG95_CANDIDATE_TEXT_RATIO_LIMIT:
        reason = f"text_logo_risk: text_ratio={text_ratio:.4f} >= {JPG95_CANDIDATE_TEXT_RATIO_LIMIT:.3f}"
        return {**base_fields, "jpg95_candidate_reason": reason, "final_output_fallback_reason": reason}

    if output_size is None or output_size <= 0:
        reason = "final_output_size_missing"
        return {**base_fields, "jpg95_candidate_status": "not_generated", "jpg95_candidate_reason": reason, "final_output_fallback_reason": reason}
    current_size_ratio = size_ratio(output_size, input_size)
    if output_size < JPG95_CANDIDATE_MIN_OUTPUT_BYTES and (current_size_ratio is None or current_size_ratio < JPG95_CANDIDATE_MIN_SIZE_RATIO):
        reason = f"final_png_not_large_enough: output_size_bytes={output_size}; size_ratio={current_size_ratio}"
        return {**base_fields, "jpg95_candidate_reason": reason, "final_output_fallback_reason": reason}
    if not enhanced_path.exists():
        reason = "final_png_missing"
        return {**base_fields, "jpg95_candidate_status": "not_generated", "jpg95_candidate_reason": reason, "final_output_fallback_reason": reason}

    try:
        final_image = read_image(enhanced_path)
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        ok, encoded = cv2.imencode(
            ".jpg",
            final_image,
            [int(cv2.IMWRITE_JPEG_QUALITY), JPG95_CANDIDATE_QUALITY],
        )
        if not ok:
            raise RuntimeError("jpg95_encode_failed")
        encoded.tofile(str(candidate_path))
        candidate_image = read_image(candidate_path)
    except Exception as exc:
        remove_file_quietly(candidate_path)
        reason = f"jpg95_candidate_write_failed: {tail_text(exc, 180)}"
        return {**base_fields, "jpg95_candidate_status": "not_generated", "jpg95_candidate_reason": reason, "final_output_fallback_reason": reason}

    if candidate_image.shape[:2] != final_image.shape[:2]:
        remove_file_quietly(candidate_path)
        reason = f"jpg95_resolution_mismatch: final={final_image.shape[1]}x{final_image.shape[0]}; candidate={candidate_image.shape[1]}x{candidate_image.shape[0]}"
        return {**base_fields, "jpg95_candidate_status": "not_generated", "jpg95_candidate_reason": reason, "final_output_fallback_reason": reason}

    candidate_size = file_size_bytes(candidate_path)
    if candidate_size is None or candidate_size <= 0:
        remove_file_quietly(candidate_path)
        reason = "jpg95_candidate_size_missing"
        return {**base_fields, "jpg95_candidate_status": "not_generated", "jpg95_candidate_reason": reason, "final_output_fallback_reason": reason}
    if candidate_size >= output_size:
        remove_file_quietly(candidate_path)
        reason = f"jpg95_candidate_not_smaller: candidate_size_bytes={candidate_size}; output_size_bytes={output_size}"
        return {**base_fields, "jpg95_candidate_reason": reason, "final_output_fallback_reason": reason}

    saved_ratio = round((output_size - candidate_size) / max(output_size, 1), 4)
    if saved_ratio < JPG95_CANDIDATE_MIN_SAVED_RATIO:
        remove_file_quietly(candidate_path)
        reason = f"jpg95_saved_ratio_below_threshold: {saved_ratio} < {JPG95_CANDIDATE_MIN_SAVED_RATIO}"
        return {**base_fields, "jpg95_candidate_reason": reason, "final_output_fallback_reason": reason}

    return {
        **base_fields,
        "jpg95_candidate_path": str(candidate_path),
        "jpg95_candidate_size_bytes": candidate_size,
        "jpg95_candidate_saved_ratio": saved_ratio,
        "jpg95_candidate_status": "candidate_for_review",
        "jpg95_candidate_reason": f"commercial_non_portrait; {alpha_reason}; text_ratio={text_ratio:.4f}; saved_ratio={saved_ratio:.4f}",
        "final_output_fallback_reason": "jpg95_candidate_requires_manual_review",
    }


def make_light_delivery_copy(
    *,
    candidate_fields: dict[str, object],
    light_delivery_path: Path,
    output_size: int | None,
) -> dict[str, object]:
    if candidate_fields.get("jpg95_candidate_status") != "candidate_for_review":
        reason = str(candidate_fields.get("jpg95_candidate_reason") or "jpg95_candidate_not_available")
        return default_light_delivery_fields("not_applicable", reason)

    candidate_path_text = str(candidate_fields.get("jpg95_candidate_path") or "")
    candidate_path = Path(candidate_path_text) if candidate_path_text else Path()
    if not candidate_path.exists() or not candidate_path.is_file():
        return default_light_delivery_fields("not_generated", "jpg95_candidate_file_missing")

    try:
        light_delivery_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate_path, light_delivery_path)
    except Exception as exc:
        remove_file_quietly(light_delivery_path)
        return default_light_delivery_fields("not_generated", f"light_delivery_copy_failed: {tail_text(exc, 180)}")

    light_size = file_size_bytes(light_delivery_path)
    if light_size is None or light_size <= 0:
        remove_file_quietly(light_delivery_path)
        return default_light_delivery_fields("not_generated", "light_delivery_size_missing")

    return {
        "light_delivery_path": str(light_delivery_path),
        "light_delivery_size_bytes": light_size,
        "light_delivery_format": file_format(light_delivery_path),
        "light_delivery_quality": JPG95_CANDIDATE_QUALITY,
        "light_delivery_role": "delivery_light_copy",
        "light_delivery_source": "jpg95_candidate",
        "light_delivery_status": "available",
        "light_delivery_reason": "copied_from_jpg95_candidate",
        "light_delivery_saved_ratio": round((output_size - light_size) / max(output_size, 1), 4) if output_size else None,
    }


def skipped_jpg95_candidate_fields(image_path: Path, image_type: str, reason: str, metrics: dict[str, float]) -> dict[str, object]:
    has_alpha, alpha_reason = real_alpha_status(image_path)
    if has_alpha is None or has_alpha:
        candidate_reason = alpha_reason
    else:
        text_ratio = float(metrics.get("text_ratio") or 0.0)
        if text_ratio >= JPG95_CANDIDATE_TEXT_RATIO_LIMIT:
            candidate_reason = f"text_logo_risk: text_ratio={text_ratio:.4f} >= {JPG95_CANDIDATE_TEXT_RATIO_LIMIT:.3f}"
        else:
            candidate_reason = f"image_type_not_allowed: {image_type}; reason={reason}"
    return default_jpg95_candidate_fields("not_applicable", candidate_reason)


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


def app_workdir_diagnostics(diagnostic_dir: Path) -> dict[str, object]:
    root_info = resolve_default_app_data_root()
    root = Path(root_info["path"])
    return {
        "app_data_root": str(root),
        "app_data_root_source": str(root_info["source"]),
        "app_data_root_exists": bool(root_info["exists"]),
        "app_data_root_writable": bool(root_info["writable"]),
        "report_dir": str(root / "报告"),
        "feedback_dir": str(diagnostic_dir),
        "beta_upload_dir": str(root / "beta_uploads"),
    }


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
    persisted_input_files = [
        item
        for item in (getattr(args, "persisted_input_files", None) or [])
        if isinstance(item, dict)
    ]
    exe = find_exe(tool_dir)

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
        roi_dir = diagnostic_dir / "roi_evidence"
        summary_dir = diagnostic_dir / "summaries"
        jpg95_candidate_dir = run_dir / "jpg95_candidates"
        light_delivery_dir = run_dir / "delivery_light"
        temp_context = tempfile.TemporaryDirectory(prefix="safe_1080p_beta_")
        after_dir = Path(temp_context.name)
    else:
        run_dir = args.output_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
        after_dir = run_dir / "after_x4plus"
        enhanced_dir = run_dir / "enhanced"
        contact_dir = run_dir / "contact_sheet"
        roi_dir = run_dir / "roi_evidence"
        jpg95_candidate_dir = run_dir / "jpg95_candidates"
        light_delivery_dir = run_dir / "delivery_light"
        summary_dir = run_dir
        diagnostic_dir = run_dir
    workdir_diagnostics = app_workdir_diagnostics(diagnostic_dir)
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
    file_timings: list[dict[str, object]] = []
    failure: Exception | None = None
    failed_file = ""
    failed_input_size_bytes: int | None = None
    failed_output_size_bytes: int | None = None
    failed_contact_sheet_size_bytes: int | None = None

    try:
        for image_path in inputs:
            failed_file = image_path.name
            image_start = time.perf_counter()
            per_file_timing: dict[str, object] = {
                "file": image_path.name,
                "per_file_start": datetime.now().isoformat(timespec="seconds"),
            }
            input_size = file_size_bytes(image_path)
            failed_input_size_bytes = input_size
            failed_output_size_bytes = None
            failed_contact_sheet_size_bytes = None
            original = read_image(image_path)
            image_type, reason, metrics = classify_image(image_path, original)
            knowledge_fields = detect_knowledge_poster(image_path, original, metrics)
            metrics.update(
                {
                    "knowledge_poster_score": knowledge_fields.get("knowledge_poster_score"),
                    "knowledge_text_ratio": knowledge_fields.get("knowledge_text_ratio"),
                    "knowledge_edge_ratio": knowledge_fields.get("knowledge_edge_ratio"),
                    "knowledge_line_ratio": knowledge_fields.get("knowledge_line_ratio"),
                }
            )
            if knowledge_fields.get("is_knowledge_poster") and image_type != "commercial_non_portrait":
                image_type = "commercial_non_portrait"
                reason = "knowledge_poster_metrics"
            route_decision = decide_enhance_route(image_path, original, image_type, metrics, knowledge_fields)
            base = image_path.stem
            if image_type != "commercial_non_portrait":
                skipped_candidate_fields = skipped_jpg95_candidate_fields(image_path, image_type, reason, metrics)
                skipped.append(
                    {
                        "file": image_path.name,
                        "input_name": image_path.name,
                        "type": image_type,
                        "reason": reason,
                        "metrics": metrics,
                        "input_size_bytes": input_size,
                        "output_size_bytes": None,
                        "contact_sheet_size_bytes": None,
                        "contact_sheet_light": "",
                        "contact_sheet_light_size_bytes": None,
                        "contact_sheet_light_format": None,
                        "contact_sheet_light_role": "preview_only",
                        "enhance_route": route_decision.get("enhance_route"),
                        "route_decision_reason": route_decision.get("route_decision_reason"),
                        "already_1080p_or_near_1080p": route_decision.get("already_1080p_or_near_1080p"),
                        "input_to_output_scale_ratio": route_decision.get("input_to_output_scale_ratio"),
                        **knowledge_fields,
                        "size_ratio": None,
                        "output_format": None,
                        "contact_sheet_format": None,
                        **skipped_candidate_fields,
                        **default_light_delivery_fields("not_applicable", skipped_candidate_fields.get("jpg95_candidate_reason") or reason),
                    }
                )
                continue

            after_path = after_dir / f"{base}_x4plus.png"
            if flat_output:
                enhanced_path = unique_business_path(enhanced_dir / f"{base}_1080p_beta.png", run_token)
                contact_path = unique_business_path(contact_dir / f"{base}_contact_sheet.png", run_token)
                contact_light_path = unique_business_path(contact_dir / f"{base}_contact_sheet_preview_q{CONTACT_SHEET_LIGHT_JPEG_QUALITY}.jpg", run_token)
                roi_evidence_path = unique_business_path(roi_dir / f"{base}_roi_evidence.jpg", run_token)
                jpg95_candidate_path = unique_business_path(jpg95_candidate_dir / f"{base}_final_candidate_jpg95.jpg", run_token)
                light_delivery_path = unique_business_path(light_delivery_dir / f"{base}_delivery_light_jpg95.jpg", run_token)
            else:
                enhanced_path = enhanced_dir / f"{base}_safe_1080p_35protected.png"
                contact_path = contact_dir / f"{base}_contact_sheet.png"
                contact_light_path = contact_dir / f"{base}_contact_sheet_preview_q{CONTACT_SHEET_LIGHT_JPEG_QUALITY}.jpg"
                roi_evidence_path = roi_dir / f"{base}_roi_evidence.jpg"
                jpg95_candidate_path = unique_business_path(jpg95_candidate_dir / f"{base}_final_candidate_jpg95.jpg", run_token)
                light_delivery_path = unique_business_path(light_delivery_dir / f"{base}_delivery_light_jpg95.jpg", run_token)

            enhance_start = time.perf_counter()
            per_file_timing.update(default_enhance_timing_fields(str(route_decision.get("enhance_route") or "safe_beta_general")))
            per_file_timing.update(
                {
                    "route_decision_reason": route_decision.get("route_decision_reason") or "",
                    "already_1080p_or_near_1080p": route_decision.get("already_1080p_or_near_1080p", False),
                    "input_to_output_scale_ratio": route_decision.get("input_to_output_scale_ratio", "not_applicable"),
                }
            )
            if route_decision.get("use_fast_route"):
                final_png, output_resolution_fields, fast_timing = fast_safe_enhance_near_1080p(original, route_decision)
                per_file_timing.update(fast_timing)
                blend35 = resize_to_match(original, final_png) if final_png is not None else original
            elif route_decision.get("enhance_route") == "knowledge_poster_mode" and route_decision.get("already_1080p_or_near_1080p"):
                final_png, output_resolution_fields, knowledge_timing = knowledge_poster_local_enhance(original, route_decision)
                per_file_timing.update(knowledge_timing)
                blend35 = resize_to_match(original, final_png) if final_png is not None else original
            else:
                if exe is None:
                    raise RealEsrganProcessError("missing_realesrgan_exe", "missing_realesrgan_exe")
                if not has_model_files(tool_dir):
                    raise RealEsrganProcessError("missing_realesrgan_model_files", "missing_realesrgan_model_files")
                sr_start = time.perf_counter()
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
                per_file_timing["realesrgan_subprocess_seconds"] = round(time.perf_counter() - sr_start, 3)
                sr_io_start = time.perf_counter()
                model_output = read_image(after_path)
                per_file_timing["sr_io_seconds"] = round(time.perf_counter() - sr_io_start, 3)
                blend_start = time.perf_counter()
                blend35 = linear_blend(original, model_output, 0.35)
                per_file_timing["protected_blend_seconds"] = round(time.perf_counter() - blend_start, 3)
                final_stage_start = time.perf_counter()
                final_png, output_resolution_fields = target_size_fidelity_blend(original, model_output)
                per_file_timing["local_detail_seconds"] = round(time.perf_counter() - final_stage_start, 3)
                output_resolution_fields.update(
                    {
                        "enhance_route": route_decision.get("enhance_route"),
                        "route_decision_reason": route_decision.get("route_decision_reason"),
                        "already_1080p_or_near_1080p": route_decision.get("already_1080p_or_near_1080p"),
                        "input_to_output_scale_ratio": route_decision.get("input_to_output_scale_ratio"),
                        "realesrgan_used": True,
                        "uses_realesrgan": True,
                        "fast_route_skipped_realesrgan": False,
                    }
                )
            per_file_timing["enhance_seconds"] = round(time.perf_counter() - enhance_start, 3)
            per_file_timing["final_stage_seconds"] = per_file_timing.get("local_detail_seconds", 0)
            output_resolution_fields.update(knowledge_fields)
            if final_png is None:
                resize_reason = str(output_resolution_fields.get("output_resolution_profile") or "true_1080p_resize_skipped")
                skipped_candidate_fields = skipped_jpg95_candidate_fields(image_path, image_type, resize_reason, metrics)
                skipped.append(
                    {
                        "file": image_path.name,
                        "input_name": image_path.name,
                        "type": image_type,
                        "reason": resize_reason,
                        "metrics": metrics,
                        "input_size_bytes": input_size,
                        "output_size_bytes": None,
                        "output_width": None,
                        "output_height": None,
                        "output_long_edge": None,
                        "output_short_edge": None,
                        "output_resolution_profile": resize_reason,
                        "enhance_route": output_resolution_fields.get("enhance_route") or route_decision.get("enhance_route"),
                        "route_decision_reason": output_resolution_fields.get("route_decision_reason") or route_decision.get("route_decision_reason"),
                        "already_1080p_or_near_1080p": output_resolution_fields.get("already_1080p_or_near_1080p") or route_decision.get("already_1080p_or_near_1080p"),
                        "input_to_output_scale_ratio": output_resolution_fields.get("input_to_output_scale_ratio") or route_decision.get("input_to_output_scale_ratio"),
                        **knowledge_fields,
                        "contact_sheet_size_bytes": None,
                        "contact_sheet_light": "",
                        "contact_sheet_light_size_bytes": None,
                        "contact_sheet_light_format": None,
                        "contact_sheet_light_role": "preview_only",
                        "size_ratio": None,
                        "output_format": None,
                        "contact_sheet_format": None,
                        **skipped_candidate_fields,
                        **default_light_delivery_fields("not_applicable", resize_reason),
                    }
                )
                continue

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
            png_write_start = time.perf_counter()
            write_image(enhanced_path, final_png)
            per_file_timing["png_write_seconds"] = round(time.perf_counter() - png_write_start, 3)
            output_size = file_size_bytes(enhanced_path)
            failed_output_size_bytes = output_size
            score_start = time.perf_counter()
            quality_score_fields = compute_safe_beta_quality_scores(original, final_png)
            per_file_timing["quality_score_seconds"] = round(time.perf_counter() - score_start, 3)
            jpg_start = time.perf_counter()
            jpg95_candidate_fields = make_jpg95_candidate(
                image_path=image_path,
                enhanced_path=enhanced_path,
                candidate_path=jpg95_candidate_path,
                image_type=image_type,
                metrics=metrics,
                input_size=input_size,
                output_size=output_size,
            )
            per_file_timing["jpg95_candidate_seconds"] = round(time.perf_counter() - jpg_start, 3)
            light_start = time.perf_counter()
            light_delivery_fields = make_light_delivery_copy(
                candidate_fields=jpg95_candidate_fields,
                light_delivery_path=light_delivery_path,
                output_size=output_size,
            )
            per_file_timing["delivery_light_seconds"] = round(time.perf_counter() - light_start, 3)
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
            contact_sheet_light_value = ""
            roi_evidence_value = ""
            roi_evidence_status = "not_generated"
            roi_evidence_reason = ""
            contact_start = time.perf_counter()
            try:
                make_contact_sheet(original, blend35, final_png, contact_path)
                contact_sheet_value = relative_or_name(contact_path, run_dir)
                failed_contact_sheet_size_bytes = file_size_bytes(contact_path)
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
                try:
                    make_contact_sheet_light(original, blend35, final_png, contact_light_path)
                    contact_sheet_light_value = relative_or_name(contact_light_path, run_dir)
                except Exception as exc:
                    warning = f"contact_sheet_light_write_failed: {tail_text(exc)}"
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
                    contact_sheet_light=contact_sheet_light_value,
                )
            per_file_timing["contact_sheet_seconds"] = round(time.perf_counter() - contact_start, 3)
            roi_start = time.perf_counter()
            try:
                make_roi_evidence_sheet(original, final_png, str(output_resolution_fields.get("enhance_route") or route_decision.get("enhance_route") or ""), roi_evidence_path)
                roi_evidence_value = relative_or_name(roi_evidence_path, run_dir)
                roi_evidence_status = "available"
            except Exception as exc:
                roi_evidence_reason = f"roi_evidence_write_failed: {tail_text(exc)}"
                warnings.append(roi_evidence_reason)
            per_file_timing["roi_evidence_seconds"] = round(time.perf_counter() - roi_start, 3)
            per_file_timing["per_file_finish"] = datetime.now().isoformat(timespec="seconds")
            per_file_timing["per_file_elapsed_seconds"] = round(time.perf_counter() - image_start, 3)
            per_file_timing["main_output_seconds"] = round(
                float(per_file_timing.get("enhance_seconds") or 0)
                + float(per_file_timing.get("png_write_seconds") or 0),
                3,
            )
            per_file_timing["evidence_seconds"] = round(
                float(per_file_timing.get("contact_sheet_seconds") or 0)
                + float(per_file_timing.get("roi_evidence_seconds") or 0),
                3,
            )
            per_file_timing["postprocess_seconds"] = round(
                float(per_file_timing.get("quality_score_seconds") or 0)
                + float(per_file_timing.get("jpg95_candidate_seconds") or 0)
                + float(per_file_timing.get("delivery_light_seconds") or 0),
                3,
            )
            per_file_timing["total_elapsed_seconds"] = per_file_timing["per_file_elapsed_seconds"]
            route_name = str(output_resolution_fields.get("enhance_route") or route_decision.get("enhance_route") or "safe_beta_general")
            speed_fields = speed_fields_for_route(route_name, float(per_file_timing["per_file_elapsed_seconds"]), per_file_timing)
            fast_pass_fields = fast_route_pass_fields(route_name, speed_fields, quality_score_fields, output_resolution_fields)
            file_timings.append(per_file_timing)
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
                    "input_size_bytes": input_size,
                    "input_width": image_dimensions(original).get("width"),
                    "input_height": image_dimensions(original).get("height"),
                    "input_long_edge": image_dimensions(original).get("long_edge"),
                    "input_short_edge": image_dimensions(original).get("short_edge"),
                    "output_size_bytes": output_size,
                    "output_width": output_resolution_fields.get("width"),
                    "output_height": output_resolution_fields.get("height"),
                    "output_long_edge": output_resolution_fields.get("long_edge"),
                    "output_short_edge": output_resolution_fields.get("short_edge"),
                    "output_resolution_profile": output_resolution_fields.get("output_resolution_profile"),
                    "enhance_route": output_resolution_fields.get("enhance_route", "safe_beta_general"),
                    "route_decision_reason": output_resolution_fields.get("route_decision_reason", route_decision.get("route_decision_reason")),
                    "already_1080p_or_near_1080p": output_resolution_fields.get("already_1080p_or_near_1080p", route_decision.get("already_1080p_or_near_1080p")),
                    "input_to_output_scale_ratio": output_resolution_fields.get("input_to_output_scale_ratio", route_decision.get("input_to_output_scale_ratio")),
                    "realesrgan_used": output_resolution_fields.get("realesrgan_used"),
                    "uses_realesrgan": output_resolution_fields.get("uses_realesrgan", output_resolution_fields.get("realesrgan_used")),
                    "fast_route_skipped_realesrgan": output_resolution_fields.get("fast_route_skipped_realesrgan"),
                    "fast_route_skipped_protected_heavy_chain": output_resolution_fields.get("fast_route_skipped_protected_heavy_chain"),
                    "fast_quality_level": output_resolution_fields.get("fast_quality_level", per_file_timing.get("fast_quality_level")),
                    "is_knowledge_poster": output_resolution_fields.get("is_knowledge_poster", False),
                    "knowledge_poster_score": output_resolution_fields.get("knowledge_poster_score"),
                    "knowledge_text_ratio": output_resolution_fields.get("knowledge_text_ratio"),
                    "knowledge_edge_ratio": output_resolution_fields.get("knowledge_edge_ratio"),
                    "knowledge_line_ratio": output_resolution_fields.get("knowledge_line_ratio"),
                    "knowledge_dense_diagram_override": output_resolution_fields.get("knowledge_dense_diagram_override"),
                    "knowledge_paper_like": output_resolution_fields.get("knowledge_paper_like"),
                    "knowledge_product_photo_like": output_resolution_fields.get("knowledge_product_photo_like"),
                    "knowledge_features": output_resolution_fields.get("knowledge_features", []),
                    "contact_sheet_size_bytes": file_size_bytes(contact_path) if contact_sheet_value else None,
                    "contact_sheet_light": contact_sheet_light_value,
                    "contact_sheet_light_size_bytes": file_size_bytes(contact_light_path) if contact_sheet_light_value else None,
                    "contact_sheet_light_format": file_format(contact_light_path) if contact_sheet_light_value else None,
                    "contact_sheet_light_quality": CONTACT_SHEET_LIGHT_JPEG_QUALITY if contact_sheet_light_value else None,
                    "contact_sheet_light_role": "preview_only",
                    "roi_evidence_path": str(roi_evidence_path) if roi_evidence_value else "",
                    "roi_evidence": roi_evidence_value,
                    "roi_evidence_size_bytes": file_size_bytes(roi_evidence_path) if roi_evidence_value else None,
                    "roi_evidence_format": file_format(roi_evidence_path) if roi_evidence_value else None,
                    "roi_evidence_status": roi_evidence_status,
                    "roi_evidence_reason": roi_evidence_reason,
                    "size_ratio": size_ratio(output_size, input_size),
                    "output_format": file_format(enhanced_path),
                    "contact_sheet_format": file_format(contact_path) if contact_sheet_value else None,
                    **quality_score_fields,
                    **jpg95_candidate_fields,
                    **light_delivery_fields,
                    **per_file_timing,
                    **speed_fields,
                    **fast_pass_fields,
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
        report_start = time.perf_counter()
        summary = {
            "status": "failed",
            "verification_result": "FAILED",
            "reason": getattr(failure, "reason", "safe_1080p_failed"),
            "error_message": tail_text(str(failure)),
            "returncode": getattr(failure, "returncode", ""),
            "stderr_tail": tail_text(getattr(failure, "stderr_tail", "")),
            "failed_file": failed_file,
            "input_size_bytes": failed_input_size_bytes,
            "output_size_bytes": failed_output_size_bytes,
            "contact_sheet_size_bytes": failed_contact_sheet_size_bytes,
            "contact_sheet_light_size_bytes": None,
            "contact_sheet_light_format": None,
            "contact_sheet_light_role": "preview_only",
            "size_ratio": size_ratio(failed_output_size_bytes, failed_input_size_bytes),
            "output_format": None,
            "contact_sheet_format": None,
            **default_jpg95_candidate_fields("not_generated", "processing_failed", None, failed_output_size_bytes),
            **default_light_delivery_fields("not_generated", "processing_failed"),
            "mode": args.mode,
            "model": args.model,
            **workdir_diagnostics,
            "input_dir": str(input_dir),
            "input_dir_exists": bool(Path(input_dir).exists() and Path(input_dir).is_dir()),
            "input_image_count": len(inputs),
            "input_files": [str(item) for item in inputs],
            "input_file_names": [item.name for item in inputs],
            "output_dir": str(run_dir),
            "diagnostic_dir": str(summary_dir.parent if flat_output else run_dir),
            "flat_output": flat_output,
            "business_output": business_output,
            "timeout_seconds": timeout_seconds,
            "started_at": started_at,
            "finished_at": finished_at,
            "elapsed_seconds": round(time.perf_counter() - start_time, 3),
            "total_elapsed_seconds": round(time.perf_counter() - start_time, 3),
            "timeout_source": "subprocess" if getattr(failure, "reason", "") == "realesrgan_timeout" else "unknown",
            "file_timings": file_timings,
            "persisted_input_files": persisted_input_files,
            "original_to_persisted_path": persisted_input_files,
            "processed_count": len(processed),
            "skipped_count": len(skipped),
            "processed": processed,
            "skipped": skipped,
            "warnings": warnings,
        }
        summary_name = f"safe_1080p_beta_summary_{run_token}.json" if flat_output else "summary.json"
        summary_path = summary_dir / summary_name
        summary["summary_path"] = str(summary_path)
        summary["report_seconds"] = round(time.perf_counter() - report_start, 3)
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

    report_start = time.perf_counter()
    fast_rows = [item for item in processed if str(item.get("enhance_route") or "") in {"already_1080p_fast_safe_enhance", BALANCED_FAST_ROUTE}]
    fast_final_pass = all(bool(item.get("fast_route_final_pass")) for item in fast_rows) if fast_rows else None
    fast_speed_pass = all(bool(item.get("fast_route_speed_pass")) for item in fast_rows) if fast_rows else None
    fast_quality_pass = all(bool(item.get("fast_route_quality_pass")) for item in fast_rows) if fast_rows else None
    consistency_fields = route_diagnostics_consistency(processed)
    summary = {
        "status": "ok" if processed else "blocked",
        "mode": args.mode,
        "model": args.model,
        **workdir_diagnostics,
        "input_dir": str(input_dir),
        "input_dir_exists": bool(Path(input_dir).exists() and Path(input_dir).is_dir()),
        "input_image_count": len(inputs),
        "input_files": [str(item) for item in inputs],
        "input_file_names": [item.name for item in inputs],
        "output_dir": str(run_dir),
        "diagnostic_dir": str(summary_dir.parent if flat_output else run_dir),
        "flat_output": flat_output,
        "business_output": business_output,
        "timeout_seconds": timeout_seconds,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": round(time.perf_counter() - start_time, 3),
        "total_elapsed_seconds": round(time.perf_counter() - start_time, 3),
        "timeout_source": "",
        "file_timings": file_timings,
        "persisted_input_files": persisted_input_files,
        "original_to_persisted_path": persisted_input_files,
        "processed_count": len(processed),
        "skipped_count": len(skipped),
        "fast_route_speed_pass": fast_speed_pass,
        "fast_route_quality_pass": fast_quality_pass,
        "fast_route_final_pass": fast_final_pass,
        **consistency_fields,
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
    summary["report_seconds"] = round(time.perf_counter() - report_start, 3)
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
