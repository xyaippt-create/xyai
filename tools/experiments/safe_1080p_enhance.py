"""Offline 1080P safe enhance candidate module.

This entry stays outside the production pipeline. It runs Real-ESRGAN x4plus
and applies a conservative 35% protected blend for non-portrait Chinese
commercial visuals.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
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
PORTRAIT_GROUP_SAFE_ROUTE = "portrait_group_conservative_safe_enhance"
PORTRAIT_COMMERCIAL_ROUTE = "portrait_commercial_layout_safe_enhance"
PORTRAIT_COMMERCIAL_POSTER_ROUTE = "portrait_commercial_poster_safe_enhance"
PORTRAIT_PHOTO_ROUTE = "portrait_photo_conservative_safe_enhance"
KNOWLEDGE_ROUTES = {"knowledge_poster_mode", "dense_chinese_poster_mode", "text_dense_visual_mode"}
IMAGE_QUALITY_PROFILES = {
    "commercial_product",
    "commercial_brand_visual",
    "portrait_photo",
    "portrait_commercial_layout",
    "portrait_group",
    "knowledge_poster",
    "general_visual",
}
CONTENT_TYPES = {
    "commercial_brand_visual",
    "commercial_product",
    "commercial_ppt_layout",
    "portrait_photo",
    "portrait_commercial_poster",
    "portrait_commercial_layout",
    "portrait_group",
    "unknown",
}
SMALL_TEXT_CONTENT_TYPES = {
    "commercial_brand_visual",
    "commercial_product",
    "commercial_ppt_layout",
    "portrait_commercial_poster",
    "portrait_commercial_layout",
}
CONTENT_TYPE_TO_PROFILE = {
    "commercial_brand_visual": "commercial_brand_visual",
    "commercial_product": "commercial_product",
    "commercial_ppt_layout": "knowledge_poster",
    "portrait_photo": "portrait_photo",
    "portrait_commercial_poster": "portrait_commercial_layout",
    "portrait_commercial_layout": "portrait_commercial_layout",
    "portrait_group": "portrait_group",
    "unknown": "general_visual",
}
TEXT_REQUIRED_PROFILES = {
    "commercial_product",
    "commercial_brand_visual",
    "portrait_commercial_layout",
    "knowledge_poster",
}
_FACE_CASCADE: cv2.CascadeClassifier | None = None
_FACE_REGION_CACHE: dict[tuple[int, int, int], tuple[list[tuple[int, int, int, int]], float]] = {}
TIMED_ENHANCE_STAGE_KEYS = (
    "resize_seconds",
    "prefilter_seconds",
    "roi_detect_seconds",
    "mask_build_seconds",
    "balanced_quality_seconds",
    "commercial_text_detail_seconds",
    "halo_suppress_seconds",
    "realesrgan_subprocess_seconds",
    "sr_io_seconds",
    "protected_blend_seconds",
    "local_detail_seconds",
    "text_line_enhance_seconds",
    "texture_suppress_seconds",
    "png_write_seconds",
    "contact_sheet_seconds",
    "roi_evidence_seconds",
    "quality_score_seconds",
    "small_text_roi_seconds",
)


NON_APPLICABLE_METRIC_VALUES = {"", "not_applicable", "not_available", "unavailable", "missing"}


def metric_number(value: object) -> float | None:
    """Return a real numeric metric without inventing a fallback value."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, str) and value.strip().lower() in NON_APPLICABLE_METRIC_VALUES:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


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
    if short_edge >= TRUE_1080P_SHORT_EDGE:
        return width, height, "preserve_native_resolution"
    scale = TRUE_1080P_SHORT_EDGE / max(short_edge, 1)
    target_width = max(1, int(round(width * scale)))
    target_height = max(1, int(round(height * scale)))
    return target_width, target_height, "upscale_to_1080"


def near_1080p_target_size(image: np.ndarray) -> tuple[int | None, int | None, float | None, str]:
    height, width = image.shape[:2]
    if width <= 0 or height <= 0:
        return None, None, None, "invalid_dimensions"
    aspect_ratio = width / max(height, 1)
    if aspect_ratio < TRUE_1080P_MIN_ASPECT_RATIO or aspect_ratio > TRUE_1080P_MAX_ASPECT_RATIO:
        return None, None, None, "aspect_ratio_not_supported"
    short_edge = min(width, height)
    scale = 1.0 if short_edge >= TRUE_1080P_SHORT_EDGE else TRUE_1080P_SHORT_EDGE / max(short_edge, 1)
    target_width = max(1, int(round(width * scale)))
    target_height = max(1, int(round(height * scale)))
    profile = "preserve_native_resolution" if short_edge >= TRUE_1080P_SHORT_EDGE else "upscale_to_1080"
    return target_width, target_height, round(scale, 4), profile


def resolution_policy_fields(original: np.ndarray, output: np.ndarray, route_decision: dict[str, object]) -> dict[str, object]:
    input_dims = image_dimensions(original)
    output_dims = image_dimensions(output)
    route = str(route_decision.get("target_profile") or "not_available")
    scale_factor = float(route_decision.get("input_to_output_scale_ratio") or 1.0)
    unexpected_downscale = bool(
        route == "preserve_native_resolution"
        and (output_dims.get("width") != input_dims.get("width") or output_dims.get("height") != input_dims.get("height"))
    )
    return {
        "resolution_route": route,
        "scale_factor": round(scale_factor, 4),
        "unexpected_downscale": unexpected_downscale,
        "input_width": input_dims.get("width"),
        "input_height": input_dims.get("height"),
        "output_width": output_dims.get("width"),
        "output_height": output_dims.get("height"),
    }


def default_enhance_timing_fields(route: str = "safe_beta_general") -> dict[str, object]:
    portrait_route = route in {
        PORTRAIT_PHOTO_ROUTE,
        PORTRAIT_COMMERCIAL_POSTER_ROUTE,
        PORTRAIT_COMMERCIAL_ROUTE,
        PORTRAIT_GROUP_SAFE_ROUTE,
    }
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
        "realesrgan_subprocess_seconds": "not_applicable" if portrait_route else 0,
        "sr_io_seconds": 0,
        "protected_blend_seconds": 0,
        "local_detail_seconds": 0,
        "text_line_enhance_seconds": 0,
        "texture_suppress_seconds": 0,
        "png_write_seconds": 0,
        "contact_sheet_seconds": 0,
        "roi_evidence_seconds": 0,
        "model_init_seconds": "not_applicable",
        "realesrgan_inference_seconds": "not_applicable",
        "fast_quality_level": "",
        "quality_score_seconds": 0,
        "halo_suppress_seconds": 0,
    }


def _box_iou(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
    lx1, ly1, lw, lh = left; rx1, ry1, rw, rh = right
    lx2, ly2 = lx1 + lw, ly1 + lh; rx2, ry2 = rx1 + rw, ry1 + rh
    intersection = max(0, min(lx2, rx2) - max(lx1, rx1)) * max(0, min(ly2, ry2) - max(ly1, ry1))
    union = lw * lh + rw * rh - intersection
    return float(intersection / max(union, 1))


def _box_containment_ratio(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
    lx1, ly1, lw, lh = left; rx1, ry1, rw, rh = right
    lx2, ly2 = lx1 + lw, ly1 + lh; rx2, ry2 = rx1 + rw, ry1 + rh
    intersection = max(0, min(lx2, rx2) - max(lx1, rx1)) * max(0, min(ly2, ry2) - max(ly1, ry1))
    return float(intersection / max(min(lw * lh, rw * rh), 1))


def detect_group_faces(original: np.ndarray, raw_detections: list[dict[str, object]] | None = None) -> dict[str, object]:
    gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    ycrcb = cv2.cvtColor(original, cv2.COLOR_BGR2YCrCb)
    hsv = cv2.cvtColor(original, cv2.COLOR_BGR2HSV)
    skin_like = (
        (ycrcb[:, :, 1] > 130) & (ycrcb[:, :, 1] < 180)
        & (ycrcb[:, :, 2] > 82) & (ycrcb[:, :, 2] < 142)
        & (hsv[:, :, 1] > 16) & (hsv[:, :, 2] > 62)
    )
    detector_name = "opencv_haar_frontalface_default"
    if raw_detections is None:
        preview_width = min(1200, gray.shape[1])
        scale = preview_width / gray.shape[1]
        preview = cv2.resize(gray, (preview_width, max(1, int(round(gray.shape[0] * scale)))), interpolation=cv2.INTER_AREA)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        try:
            detections, _, level_weights = cascade.detectMultiScale3(
                preview,
                scaleFactor=1.08,
                minNeighbors=4,
                minSize=(14, 14),
                outputRejectLevels=True,
            )
            weights = [float(value) for value in np.asarray(level_weights).reshape(-1)]
        except (AttributeError, cv2.error):
            detections = cascade.detectMultiScale(preview, scaleFactor=1.08, minNeighbors=4, minSize=(14, 14))
            weights = [0.0] * len(detections)
        raw_detections = [
            {
                "box": (int(round(x / scale)), int(round(y / scale)), int(round(w / scale)), int(round(h / scale))),
                "detector_weight": weights[index] if index < len(weights) else 0.0,
            }
            for index, (x, y, w, h) in enumerate(detections)
        ]
    else:
        detector_name = "synthetic_or_injected_face_candidates"
    image_area = float(original.shape[0] * original.shape[1])
    raw_count = len(raw_detections)
    face_candidates: list[dict[str, object]] = []
    prelim: list[tuple[tuple[int, int, int, int], float, int]] = []
    for index, raw in enumerate(raw_detections, start=1):
        raw_box = raw.get("box") or raw.get("bbox")
        try:
            x, y, width, height = (int(round(float(value))) for value in raw_box)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        x = max(0, min(gray.shape[1] - 1, x)); y = max(0, min(gray.shape[0] - 1, y))
        width = max(1, min(gray.shape[1] - x, width)); height = max(1, min(gray.shape[0] - y, height))
        box = (x, y, width, height)
        area_ratio = width * height / max(image_area, 1.0)
        roi = gray[y:y + height, x:x + width]
        skin_roi = skin_like[y:y + height, x:x + width]
        skin_coverage = float(raw.get("skin_coverage")) if raw.get("skin_coverage") is not None else (float(np.mean(skin_roi)) if skin_roi.size else 0.0)
        sharpness = float(raw.get("sharpness")) if raw.get("sharpness") is not None else (float(cv2.Laplacian(roi, cv2.CV_64F).var()) if roi.size else 0.0)
        edge_density = float(np.mean(cv2.Canny(roi, 45, 135) > 0)) if roi.size else 0.0
        detector_weight = float(raw.get("detector_weight") or 0.0)
        detector_confidence = raw.get("confidence")
        if detector_confidence is None:
            detector_confidence = float(np.clip(
                0.28
                + min(area_ratio / 0.018, 1.0) * 0.22
                + min(sharpness / 150.0, 1.0) * 0.20
                + min(skin_coverage / 0.24, 1.0) * 0.22
                + np.clip(detector_weight / 20.0, -0.08, 0.08),
                0.0,
                1.0,
            ))
        confidence = float(detector_confidence)
        aspect = width / max(height, 1)
        injected_screen_risk = raw.get("screen_or_icon_risk")
        screen_or_icon_risk = bool(
            injected_screen_risk
            if injected_screen_risk is not None
            else (skin_coverage < 0.012 and area_ratio < 0.006 and edge_density > 0.19)
        )
        small_status = "not_small"
        small_reason = "area_ratio_above_small_face_threshold"
        accepted = True
        filter_reason = "candidate_passed_basic_filters"
        if area_ratio < 0.00008:
            accepted = False; small_status = "filtered"; small_reason = "area_ratio_below_0.00008"; filter_reason = small_reason
        elif area_ratio < 0.00040:
            small_status = "retained" if raw_count >= 8 and confidence >= 0.45 else "filtered"
            small_reason = "small_face_retained_by_group_context" if small_status == "retained" else "small_face_without_group_confidence"
            if small_status == "filtered": accepted = False; filter_reason = small_reason
        if area_ratio > 0.20:
            accepted = False; filter_reason = "area_ratio_above_0.20"
        elif not 0.62 <= aspect <= 1.62:
            accepted = False; filter_reason = "face_aspect_ratio_out_of_range"
        elif confidence < 0.45:
            accepted = False; filter_reason = "confidence_below_0.45"
        elif screen_or_icon_risk:
            accepted = False; filter_reason = "screen_or_icon_risk"
        elif sharpness < 4.0 and raw_count < 8:
            accepted = False; filter_reason = "insufficient_local_structure"
        elif skin_coverage < 0.012 and raw_count < 8:
            accepted = False; filter_reason = "insufficient_skin_evidence"
        normalized = [round(x / gray.shape[1], 6), round(y / gray.shape[0], 6), round((x + width) / gray.shape[1], 6), round((y + height) / gray.shape[0], 6)]
        candidate = {
            "face_id": f"face_raw_{index:03d}",
            "bbox_normalized": normalized,
            "bbox_pixels": [x, y, width, height],
            "confidence": round(confidence, 4),
            "detector_weight": round(detector_weight, 4),
            "area_ratio": round(area_ratio, 6),
            "skin_coverage": round(skin_coverage, 4),
            "local_sharpness": round(sharpness, 3),
            "small_face_filter_status": small_status,
            "small_face_filter_reason": small_reason,
            "overlap_dedup_status": "pending" if accepted else "not_applicable",
            "overlap_dedup_reason": "pending" if accepted else filter_reason,
            "screen_or_icon_risk": screen_or_icon_risk,
            "accepted_as_face": False,
            "filter_reason": filter_reason,
        }
        face_candidates.append(candidate)
        if accepted:
            prelim.append((box, confidence, len(face_candidates) - 1))
    # Haar occasionally promotes lamps, labels, hands, or clothing folds as a
    # second face in a single-person commercial composition.  Apply a relative
    # evidence pass before overlap deduplication; this is deliberately limited
    # to small candidate sets so genuine small faces in group photos survive.
    if 1 < len(prelim) < 8:
        anchor_box, _, anchor_index = max(
            prelim,
            key=lambda item: (
                float(face_candidates[item[2]].get("skin_coverage") or 0.0),
                float(face_candidates[item[2]].get("confidence") or 0.0),
                item[0][2] * item[0][3],
            ),
        )
        anchor = face_candidates[anchor_index]
        anchor_area = float(anchor.get("area_ratio") or 0.0)
        anchor_skin = float(anchor.get("skin_coverage") or 0.0)
        anchor_cx = (anchor_box[0] + anchor_box[2] / 2) / gray.shape[1]
        anchor_cy = (anchor_box[1] + anchor_box[3] / 2) / gray.shape[0]
        retained_prelim: list[tuple[tuple[int, int, int, int], float, int]] = []
        for box, confidence, candidate_index in prelim:
            candidate = face_candidates[candidate_index]
            if candidate_index == anchor_index or anchor_skin < 0.25 or anchor_area < 0.004:
                retained_prelim.append((box, confidence, candidate_index))
                continue
            area = float(candidate.get("area_ratio") or 0.0)
            skin = float(candidate.get("skin_coverage") or 0.0)
            weight = float(candidate.get("detector_weight") or 0.0)
            cx = (box[0] + box[2] / 2) / gray.shape[1]
            cy = (box[1] + box[3] / 2) / gray.shape[0]
            near_top_border_artifact = box[1] / gray.shape[0] < 0.035 and skin < 0.20 and weight < 2.5
            same_column_body_feature = (
                area < anchor_area * 0.60
                and skin < 0.20
                and confidence < 0.80
                and abs(cx - anchor_cx) < 0.10
                and abs(cy - anchor_cy) > 0.16
            )
            if near_top_border_artifact or same_column_body_feature:
                candidate["screen_or_icon_risk"] = True
                candidate["overlap_dedup_status"] = "not_applicable"
                candidate["overlap_dedup_reason"] = "relative_anchor_artifact_filter"
                candidate["filter_reason"] = (
                    "top_border_decorative_artifact_risk"
                    if near_top_border_artifact
                    else "same_column_body_feature_risk"
                )
                continue
            retained_prelim.append((box, confidence, candidate_index))
        prelim = retained_prelim
    prelim.sort(key=lambda item: (item[1], item[0][2] * item[0][3]), reverse=True)
    kept: list[tuple[tuple[int, int, int, int], float, int]] = []
    for box, confidence, candidate_index in prelim:
        duplicate_of = None
        for existing, _, existing_index in kept:
            iou = _box_iou(box, existing)
            containment = _box_containment_ratio(box, existing)
            if iou >= 0.30 or containment >= 0.78:
                duplicate_of = (face_candidates[existing_index]["face_id"], iou, containment)
                break
        if duplicate_of is not None:
            candidate = face_candidates[candidate_index]
            candidate["overlap_dedup_status"] = "filtered_duplicate"
            candidate["overlap_dedup_reason"] = f"duplicate_of={duplicate_of[0]};iou={duplicate_of[1]:.4f};containment={duplicate_of[2]:.4f}"
            candidate["filter_reason"] = "overlap_duplicate"
            continue
        kept.append((box, confidence, candidate_index))
        face_candidates[candidate_index]["overlap_dedup_status"] = "kept"
        face_candidates[candidate_index]["overlap_dedup_reason"] = "iou<0.30_and_containment<0.78"
        face_candidates[candidate_index]["accepted_as_face"] = True
        face_candidates[candidate_index]["filter_reason"] = "accepted"
    boxes = [box for box, _, _ in kept]
    confidences = [confidence for _, confidence, _ in kept]
    accepted_area_ratios = [width * height / max(image_area, 1.0) for _, _, width, height in boxes]
    area_ratio = sum(accepted_area_ratios)
    centers_x = [(x + width / 2) / gray.shape[1] for x, _, width, _ in boxes]
    centers_y = [(y + height / 2) / gray.shape[0] for _, y, _, height in boxes]
    return {
        "face_detector": detector_name,
        "face_candidate_count_raw": len(face_candidates),
        "face_candidate_count_filtered": len(boxes),
        "group_face_count": len(boxes),
        "group_face_detection_confidence": round(float(np.mean(confidences)) if confidences else 0.0, 4),
        "group_face_area_ratio": round(float(area_ratio), 4),
        "group_face_confidences": [round(value, 4) for value in confidences],
        "group_face_boxes": boxes,
        "face_candidates": face_candidates,
        "face_iou_dedup_threshold": 0.30,
        "face_containment_dedup_threshold": 0.78,
        "face_small_area_ratio_threshold": 0.00040,
        "face_max_area_ratio": round(max(accepted_area_ratios), 6) if accepted_area_ratios else 0.0,
        "face_median_area_ratio": round(float(np.median(accepted_area_ratios)), 6) if accepted_area_ratios else 0.0,
        "face_center_spread_x": round(max(centers_x) - min(centers_x), 4) if len(centers_x) >= 2 else 0.0,
        "face_center_spread_y": round(max(centers_y) - min(centers_y), 4) if len(centers_y) >= 2 else 0.0,
    }


def detect_knowledge_topology(original: np.ndarray) -> dict[str, object]:
    gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    area = float(height * width)
    edges = cv2.Canny(gray, 45, 135)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    nodes: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, node_width, node_height = cv2.boundingRect(contour)
        ratio = node_width * node_height / max(area, 1.0)
        aspect = node_width / max(node_height, 1)
        if 0.00035 <= ratio <= 0.035 and 0.45 <= aspect <= 2.4 and node_width >= 14 and node_height >= 12:
            nodes.append((x, y, node_width, node_height))
    nodes.sort(key=lambda box: box[2] * box[3], reverse=True)
    deduped: list[tuple[int, int, int, int]] = []
    for node in nodes:
        if all(_box_iou(node, existing) < 0.55 for existing in deduped):
            deduped.append(node)
        if len(deduped) >= 80:
            break
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=28, minLineLength=max(18, min(width, height) // 35), maxLineGap=8)
    relation_links = 0
    connected_nodes: set[int] = set()
    for raw_line in ([] if lines is None else lines[:, 0, :]):
        x1, y1, x2, y2 = (int(value) for value in raw_line)
        matched: set[int] = set()
        for index, (x, y, node_width, node_height) in enumerate(deduped):
            margin = max(8, min(node_width, node_height) // 3)
            for px, py in ((x1, y1), (x2, y2)):
                if x - margin <= px <= x + node_width + margin and y - margin <= py <= y + node_height + margin:
                    matched.add(index)
        if len(matched) >= 2:
            relation_links += 1
            connected_nodes.update(matched)
    core_ratio = 0.0
    if connected_nodes:
        selected = [deduped[index] for index in connected_nodes]
        x1 = min(box[0] for box in selected); y1 = min(box[1] for box in selected)
        x2 = max(box[0] + box[2] for box in selected); y2 = max(box[1] + box[3] for box in selected)
        core_ratio = (x2 - x1) * (y2 - y1) / max(area, 1.0)
    topology = len(connected_nodes) >= 3 and relation_links >= 2 and core_ratio >= 0.025
    return {
        "knowledge_node_candidate_count": len(deduped),
        "knowledge_connected_node_count": len(connected_nodes),
        "knowledge_relation_link_count": relation_links,
        "knowledge_topology_core_ratio": round(float(core_ratio), 4),
        "knowledge_topology_evidence": bool(topology),
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
    topology_fields = detect_knowledge_topology(original)
    is_knowledge = bool(topology_fields["knowledge_topology_evidence"] and text_ratio >= 0.32 and score >= KNOWLEDGE_POSTER_SCORE_THRESHOLD and paper_like and not product_photo_like)
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
        **topology_fields,
    }


def decide_enhance_route(
    image_path: Path,
    original: np.ndarray,
    image_type: str,
    metrics: dict[str, float],
    knowledge_fields: dict[str, object],
    face_analysis: dict[str, object] | None = None,
) -> dict[str, object]:
    dims = image_dimensions(original)
    target_width, target_height, scale_ratio, profile = near_1080p_target_size(original)
    short_edge = int(dims.get("short_edge") or 0)
    blur_score = float(cv2.Laplacian(cv2.cvtColor(original, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
    severe_low_clarity = blur_score < 8.0
    is_knowledge = bool(knowledge_fields.get("is_knowledge_poster"))
    group_fields = face_analysis or detect_group_faces(original)
    face_count = int(group_fields.get("group_face_count") or 0)
    face_area_ratio = float(group_fields.get("group_face_area_ratio") or 0.0)
    max_face_area_ratio = float(group_fields.get("face_max_area_ratio") or 0.0)
    median_face_area_ratio = float(group_fields.get("face_median_area_ratio") or 0.0)
    face_spread_x = float(group_fields.get("face_center_spread_x") or 0.0)
    face_spread_y = float(group_fields.get("face_center_spread_y") or 0.0)
    accepted_faces = [
        item for item in (group_fields.get("face_candidates") or [])
        if isinstance(item, dict) and item.get("accepted_as_face") is True
    ]
    accepted_confidences = [float(item.get("confidence") or 0.0) for item in accepted_faces]
    high_confidence_face_ratio = (
        sum(value >= 0.65 for value in accepted_confidences) / len(accepted_confidences)
        if accepted_confidences else 0.0
    )
    face_rows: list[float] = []
    for item in sorted(accepted_faces, key=lambda value: float((value.get("bbox_normalized") or [0, 0, 0, 0])[1])):
        box = _validated_normalized_box(item.get("bbox_normalized"))
        if box is None:
            continue
        center_y = (box[1] + box[3]) / 2.0
        height = box[3] - box[1]
        if not face_rows or all(abs(center_y - row_y) > max(0.055, height * 0.85) for row_y in face_rows):
            face_rows.append(center_y)
    primary_face = max(accepted_faces, key=lambda item: float(item.get("area_ratio") or 0.0), default=None)
    primary_box = _validated_normalized_box(primary_face.get("bbox_normalized")) if primary_face else None
    primary_face_confidence = float(primary_face.get("confidence") or 0.0) if primary_face else 0.0
    primary_face_center_x = (primary_box[0] + primary_box[2]) / 2.0 if primary_box else 0.0
    primary_face_center_y = (primary_box[1] + primary_box[3]) / 2.0 if primary_box else 0.0
    text_ratio = float(metrics.get("text_ratio") or 0.0)
    dark_ratio = float(metrics.get("dark_ratio") or 0.0)
    light_bg_ratio = float(metrics.get("light_bg_ratio") or 0.0)
    edge_ratio = float(metrics.get("edge_ratio") or 0.0)
    high_sat_ratio = float(metrics.get("high_sat_ratio") or 0.0)
    layout_structure_score = (
        (1.0 if text_ratio >= 0.045 else 0.0)
        + (0.7 if edge_ratio >= 0.040 else 0.0)
        + (0.5 if light_bg_ratio >= 0.24 else 0.0)
        + (0.4 if high_sat_ratio >= 0.035 else 0.0)
    )
    compact_group_context = bool(
        face_count >= 5
        and median_face_area_ratio <= 0.015
        and (face_spread_x >= 0.30 or face_spread_y >= 0.18)
        and text_ratio < 0.16
    )
    large_group_context = bool(
        face_count >= 12
        and median_face_area_ratio <= 0.006
        and face_spread_x >= 0.45
        and len(face_rows) >= 2
        and high_confidence_face_ratio >= 0.70
    )
    group_photo = bool(compact_group_context or large_group_context)
    portrait_commercial_layout = bool(
        2 <= face_count <= 8
        and face_area_ratio >= 0.012
        and layout_structure_score >= 1.7
        and not group_photo
    )
    portrait_commercial_poster = bool(
        1 <= face_count <= 2
        and max_face_area_ratio >= 0.0045
        and text_ratio >= 0.045
        and layout_structure_score >= 1.4
        and (dark_ratio >= 0.12 or high_sat_ratio >= 0.035 or edge_ratio >= 0.045)
    )
    strong_single_portrait_context = bool(
        face_count == 1
        and max_face_area_ratio >= 0.040
        and primary_face_confidence >= 0.75
        and 0.15 <= primary_face_center_x <= 0.85
        and 0.10 <= primary_face_center_y <= 0.72
        and text_ratio < 0.22
        and layout_structure_score < 1.7
    )
    portrait_photo = bool(
        strong_single_portrait_context or (
        1 <= face_count <= 2
        and max_face_area_ratio >= 0.006
        and text_ratio < 0.055
        and not is_knowledge
        and not portrait_commercial_poster
        )
    )
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
    route_evidence = {
        "image_type": image_type,
        "face_count_filtered": face_count,
        "face_total_area_ratio": round(face_area_ratio, 6),
        "face_max_area_ratio": round(max_face_area_ratio, 6),
        "face_median_area_ratio": round(median_face_area_ratio, 6),
        "face_center_spread_x": round(face_spread_x, 4),
        "face_center_spread_y": round(face_spread_y, 4),
        "face_row_count": len(face_rows),
        "high_confidence_face_ratio": round(high_confidence_face_ratio, 4),
        "primary_face_confidence": round(primary_face_confidence, 4),
        "primary_face_center_x": round(primary_face_center_x, 4),
        "primary_face_center_y": round(primary_face_center_y, 4),
        "text_ratio": round(text_ratio, 4),
        "layout_structure_score": round(layout_structure_score, 3),
        "dark_ratio": round(dark_ratio, 4),
        "edge_ratio": round(edge_ratio, 4),
        "high_sat_ratio": round(high_sat_ratio, 4),
        "knowledge_topology": is_knowledge,
    }
    if is_knowledge:
        reason = (
            f"knowledge_poster_mode: score={knowledge_fields.get('knowledge_poster_score')}; "
            f"nodes={knowledge_fields.get('knowledge_connected_node_count')}; links={knowledge_fields.get('knowledge_relation_link_count')}; "
            f"features={','.join(knowledge_fields.get('knowledge_features') or [])}"
        )
        route = "knowledge_poster_mode"
    elif group_photo and isinstance(target_width, int) and isinstance(target_height, int):
        reason = (
            f"portrait_group_conservative_safe: faces={group_fields.get('group_face_count')}; rows={len(face_rows)}; "
            f"median_face_area_ratio={median_face_area_ratio:.6f}; high_confidence_ratio={high_confidence_face_ratio:.3f}; "
            f"input_short_edge={short_edge}; scale_ratio={scale_ratio}; skip_realesrgan"
        )
        route = PORTRAIT_GROUP_SAFE_ROUTE
    elif portrait_commercial_layout and isinstance(target_width, int) and isinstance(target_height, int):
        reason = (
            f"portrait_commercial_layout_safe: faces={face_count}; face_area_ratio={face_area_ratio:.4f}; "
            f"text_ratio={text_ratio:.4f}; preserve_people_and_enhance_layout_text"
        )
        route = PORTRAIT_COMMERCIAL_ROUTE
    elif portrait_commercial_poster and isinstance(target_width, int) and isinstance(target_height, int):
        reason = (
            f"portrait_commercial_poster_safe: faces={face_count}; max_face_area_ratio={max_face_area_ratio:.4f}; "
            f"text_ratio={text_ratio:.4f}; layout_score={layout_structure_score:.2f}; preserve_identity_before_text"
        )
        route = PORTRAIT_COMMERCIAL_POSTER_ROUTE
    elif portrait_photo and isinstance(target_width, int) and isinstance(target_height, int):
        reason = (
            f"portrait_photo_conservative_safe: faces={face_count}; face_area_ratio={face_area_ratio:.4f}; "
            f"text_not_required; skip_realesrgan"
        )
        route = PORTRAIT_PHOTO_ROUTE
    elif can_fast:
        reason = (
            f"near_1080p_fast_safe: input_short_edge={short_edge}; "
            f"scale_ratio={scale_ratio}; blur_score={blur_score:.2f}; not_knowledge_poster"
        )
        route = BALANCED_FAST_ROUTE
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
        "use_fast_route": bool(route == BALANCED_FAST_ROUTE),
        "portrait_commercial_layout_evidence": bool(portrait_commercial_layout),
        "portrait_commercial_poster_evidence": bool(portrait_commercial_poster),
        "portrait_photo_evidence": bool(portrait_photo),
        "portrait_group_evidence": bool(group_photo),
        "portrait_subject_context": bool(strong_single_portrait_context or portrait_photo or portrait_commercial_poster),
        "portrait_group_context": bool(group_photo),
        "portrait_large_group_context": bool(large_group_context),
        "portrait_compact_group_context": bool(compact_group_context),
        "route_evidence": route_evidence,
        **group_fields,
    }


def apply_realesrgan_execution_guard(route_decision: dict[str, object]) -> dict[str, object]:
    """Resolve model eligibility independently from upstream route selection."""
    resolved = dict(route_decision)
    requested_route = str(resolved.get("enhance_route") or "")
    portrait_routes = {
        PORTRAIT_PHOTO_ROUTE,
        PORTRAIT_COMMERCIAL_POSTER_ROUTE,
        PORTRAIT_COMMERCIAL_ROUTE,
        PORTRAIT_GROUP_SAFE_ROUTE,
    }
    group_context = bool(resolved.get("portrait_group_context"))
    subject_context = bool(resolved.get("portrait_subject_context"))
    if group_context:
        block_reason = "portrait_group_guard"
        if requested_route != PORTRAIT_GROUP_SAFE_ROUTE:
            resolved["upstream_route_before_realesrgan_guard"] = requested_route
            resolved["enhance_route"] = PORTRAIT_GROUP_SAFE_ROUTE
            resolved["route_decision_reason"] = (
                f"{resolved.get('route_decision_reason')}; execution_guard_reroute=portrait_group_conservative_safe"
            )
            resolved["use_fast_route"] = False
    elif subject_context:
        block_reason = "portrait_subject_guard"
        if requested_route not in portrait_routes:
            resolved["upstream_route_before_realesrgan_guard"] = requested_route
            resolved["enhance_route"] = PORTRAIT_PHOTO_ROUTE
            resolved["route_decision_reason"] = (
                f"{resolved.get('route_decision_reason')}; execution_guard_reroute=portrait_photo_conservative_safe"
            )
            resolved["use_fast_route"] = False
    elif requested_route in portrait_routes:
        block_reason = "portrait_route_guard"
    else:
        block_reason = "not_applicable"
    model_route_requested = requested_route not in portrait_routes and requested_route not in {BALANCED_FAST_ROUTE}
    resolved.update({
        "realesrgan_requested": bool(model_route_requested),
        "realesrgan_execution_allowed": bool(block_reason == "not_applicable"),
        "realesrgan_request_blocked": bool(model_route_requested and block_reason != "not_applicable"),
        "realesrgan_block_reason": block_reason,
        "portrait_context_established": bool(group_context or subject_context or requested_route in portrait_routes),
    })
    return resolved


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
    target_width, target_height, scale_factor, profile = near_1080p_target_size(original)
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
    route_decision = {"target_profile": profile, "input_to_output_scale_ratio": scale_factor}
    return restored, {"output_resolution_profile": profile, **image_dimensions(restored), **resolution_policy_fields(original, restored, route_decision)}


def _masked_laplacian_score(image: np.ndarray, mask: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    laplacian = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
    weight = mask.astype(np.float32)
    if weight.max(initial=0) > 1:
        weight /= 255.0
    weight_sum = float(weight.sum())
    return float(laplacian.mean()) if weight_sum < 8 else float((laplacian * weight).sum() / weight_sum)


def build_primary_delivery_text_mask(original_target: np.ndarray) -> tuple[np.ndarray, dict[str, object]]:
    text_mask = build_protection_masks(original_target)["text_like"] > 0
    gray = cv2.cvtColor(original_target, cv2.COLOR_BGR2GRAY)
    detail_energy = cv2.GaussianBlur(np.abs(cv2.Laplacian(gray, cv2.CV_32F)), (0, 0), 1.2)
    text_values = detail_energy[text_mask]
    if text_values.size < 32:
        empty = np.zeros(gray.shape, dtype=np.uint8)
        return empty, {
            "primary_text_roi_confidence": 0.0,
            "primary_text_roi_area_ratio": 0.0,
            "defocus_text_excluded_ratio": 0.0,
            "defocus_text_excluded_reason": "insufficient_text_pixels",
        }
    threshold = float(np.percentile(text_values, 28.0))
    primary = text_mask & (detail_energy >= threshold)
    primary_u8 = cv2.morphologyEx(primary.astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8), iterations=1)
    primary_ratio = float(np.mean(primary_u8 > 0))
    excluded_ratio = float(np.sum(text_mask & (primary_u8 == 0)) / max(int(np.sum(text_mask)), 1))
    confidence = float(np.clip(primary_ratio / 0.025, 0.0, 1.0))
    return primary_u8, {
        "primary_text_roi_confidence": round(confidence, 4),
        "primary_text_roi_area_ratio": round(primary_ratio, 4),
        "defocus_text_excluded_ratio": round(excluded_ratio, 4),
        "defocus_text_excluded_reason": "low_local_laplacian_energy_excluded",
    }


def apply_commercial_text_detail_boost(image: np.ndarray, original_target: np.ndarray, exclude_mask: np.ndarray | None = None) -> np.ndarray:
    primary_mask, _ = build_primary_delivery_text_mask(original_target)
    text_mask = build_protection_masks(original_target)["text_like"]
    boost_mask = np.clip(
        primary_mask.astype(np.float32) / 255.0 + (text_mask.astype(np.float32) / 255.0) * 0.38,
        0.0,
        1.0,
    )
    boost_mask = cv2.GaussianBlur(boost_mask, (0, 0), 0.38)[:, :, None]
    if exclude_mask is not None:
        protected = cv2.GaussianBlur((exclude_mask > 0).astype(np.float32), (0, 0), 1.2)[:, :, None]
        boost_mask *= 1.0 - np.clip(protected, 0.0, 1.0)
    detail = np.clip(image.astype(np.float32) - cv2.GaussianBlur(image, (0, 0), 0.42).astype(np.float32), -14.0, 14.0)
    return np.clip(image.astype(np.float32) + detail * boost_mask * 1.25, 0, 255).astype(np.uint8)


def suppress_high_contrast_overshoot(image: np.ndarray, original_target: np.ndarray) -> tuple[np.ndarray, dict[str, object]]:
    before = cv2.cvtColor(original_target, cv2.COLOR_BGR2GRAY)
    after = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    before_grad = cv2.magnitude(cv2.Sobel(before, cv2.CV_32F, 1, 0), cv2.Sobel(before, cv2.CV_32F, 0, 1))
    after_grad = cv2.magnitude(cv2.Sobel(after, cv2.CV_32F, 1, 0), cv2.Sobel(after, cv2.CV_32F, 0, 1))
    overshoot = (after_grad > before_grad * 1.52 + 12.0) & (before_grad > 18.0)
    mask = cv2.dilate(overshoot.astype(np.uint8) * 255, np.ones((3, 3), np.uint8), iterations=1)
    mask = cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), 0.72)[:, :, None] * 0.62
    restored = np.clip(image.astype(np.float32) * (1.0 - mask) + original_target.astype(np.float32) * mask, 0, 255).astype(np.uint8)
    return restored, {
        "overshoot_suppression_applied": bool(np.any(overshoot)),
        "overshoot_suppression_ratio": round(float(np.mean(overshoot)), 4),
    }


def semantic_texture_quality(original: np.ndarray, final_png: np.ndarray) -> dict[str, object]:
    original_target = resize_to_match(original, final_png)
    before_gray = cv2.cvtColor(original_target, cv2.COLOR_BGR2GRAY)
    after_gray = cv2.cvtColor(final_png, cv2.COLOR_BGR2GRAY)
    masks = build_protection_masks(original_target)
    before_detail = cv2.absdiff(before_gray, cv2.GaussianBlur(before_gray, (0, 0), 0.85)).astype(np.float32)
    after_detail = cv2.absdiff(after_gray, cv2.GaussianBlur(after_gray, (0, 0), 0.85)).astype(np.float32)
    threshold = max(3.0, float(np.percentile(before_detail, 58.0)))
    texture_mask = (before_detail >= threshold) & (masks["skin"] == 0)
    smooth_mask = (before_detail < max(2.5, threshold * 0.45)) & (masks["text_like"] == 0) & (masks["high_contrast_edge"] == 0)
    before_energy = float(before_detail[texture_mask].mean()) if np.any(texture_mask) else float(before_detail.mean())
    after_energy = float(after_detail[texture_mask].mean()) if np.any(texture_mask) else float(after_detail.mean())
    gain = (after_energy - before_energy) / max(before_energy, 1.0) * 100.0
    smooth_before = float(before_detail[smooth_mask].mean()) if np.any(smooth_mask) else 0.0
    smooth_after = float(after_detail[smooth_mask].mean()) if np.any(smooth_mask) else 0.0
    noise_growth = max(0.0, smooth_after - smooth_before) / max(smooth_before, 1.0) * 100.0
    overshoot = float(np.mean(after_detail[texture_mask] > before_detail[texture_mask] * 2.2 + 5.0)) if np.any(texture_mask) else 0.0
    score = float(np.clip(55.0 + np.clip(gain, -35.0, 35.0) * 0.45 - min(noise_growth, 60.0) * 0.28 - overshoot * 35.0, 0.0, 100.0))
    return {
        "texture_score": round(score, 2),
        "texture_gain": round(float(gain), 2),
        "texture_region_ratio": round(float(np.mean(texture_mask)), 4),
        "smooth_protection_region_ratio": round(float(np.mean(smooth_mask)), 4),
        "texture_noise_growth": round(float(noise_growth), 2),
        "texture_overshoot_ratio": round(overshoot, 4),
        "texture_metric_profile": "semantic_texture_excluding_skin_glass_blur_and_flat_regions",
    }


def edge_artifact_quality(original: np.ndarray, final_png: np.ndarray, base_score: object) -> dict[str, object]:
    original_target = resize_to_match(original, final_png)
    before = cv2.cvtColor(original_target, cv2.COLOR_BGR2GRAY)
    after = cv2.cvtColor(final_png, cv2.COLOR_BGR2GRAY)
    before_grad = cv2.magnitude(cv2.Sobel(before, cv2.CV_32F, 1, 0), cv2.Sobel(before, cv2.CV_32F, 0, 1))
    after_grad = cv2.magnitude(cv2.Sobel(after, cv2.CV_32F, 1, 0), cv2.Sobel(after, cv2.CV_32F, 0, 1))
    threshold = max(18.0, float(np.percentile(before_grad, 78.0)))
    edge_mask = before_grad >= threshold
    ratio = float(np.median(after_grad[edge_mask] / np.maximum(before_grad[edge_mask], 1.0))) if np.any(edge_mask) else 1.0
    overshoot = float(np.mean(after_grad[edge_mask] > before_grad[edge_mask] * 1.7 + 12.0)) if np.any(edge_mask) else 0.0
    halo_penalty = max(0.0, ratio - 1.32) * 35.0 + overshoot * 65.0
    raw_score = metric_number(base_score)
    score: float | str
    if raw_score is None:
        score = "not_available"
    else:
        score = float(np.clip(raw_score - halo_penalty, 0.0, 100.0))
        if overshoot > 0.035 or ratio > 1.45:
            score = min(score, 89.0)
    return {
        "edge_quality_score_raw": round(raw_score, 2) if raw_score is not None else "not_available",
        "edge_quality_score": round(score, 2) if isinstance(score, float) else score,
        "edge_strength_ratio": round(ratio, 4),
        "edge_overshoot_ratio": round(overshoot, 4),
        "halo_ringing_penalty": round(float(halo_penalty), 2),
        "halo_ringing_pass": bool(overshoot <= 0.055 and ratio <= 1.55),
    }


def infer_image_quality_profile(route: str) -> str:
    if route == PORTRAIT_PHOTO_ROUTE:
        return "portrait_photo"
    if route in {PORTRAIT_COMMERCIAL_ROUTE, PORTRAIT_COMMERCIAL_POSTER_ROUTE}:
        return "portrait_commercial_layout"
    if route == PORTRAIT_GROUP_SAFE_ROUTE:
        return "portrait_group"
    if route in KNOWLEDGE_ROUTES:
        return "knowledge_poster"
    if route in {"already_1080p_fast_safe_enhance", BALANCED_FAST_ROUTE}:
        return "general_visual"
    return "general_visual"


def infer_content_type(
    image_type: str,
    route: str,
    metrics: dict[str, object] | None = None,
    knowledge_fields: dict[str, object] | None = None,
) -> tuple[str, str]:
    """Infer content semantics from existing analysis evidence, never a filename."""
    metrics = metrics or {}
    knowledge_fields = knowledge_fields or {}
    text_ratio = metric_number(metrics.get("text_ratio")) or 0.0
    high_sat_ratio = metric_number(metrics.get("high_sat_ratio")) or 0.0
    light_bg_ratio = metric_number(metrics.get("light_bg_ratio")) or 0.0
    if route == PORTRAIT_PHOTO_ROUTE:
        return "portrait_photo", "route_and_face_metrics"
    if route == PORTRAIT_GROUP_SAFE_ROUTE:
        return "portrait_group", "route_and_face_metrics"
    if route == PORTRAIT_COMMERCIAL_ROUTE:
        face_count = int(metric_number(metrics.get("face_candidate_count_filtered")) or 0)
        content_type = "portrait_commercial_poster" if face_count <= 1 else "portrait_commercial_layout"
        return content_type, "route_face_and_text_metrics"
    if route == PORTRAIT_COMMERCIAL_POSTER_ROUTE:
        return "portrait_commercial_poster", "route_face_and_text_metrics"
    if bool(knowledge_fields.get("is_knowledge_poster")) or route in KNOWLEDGE_ROUTES:
        return "commercial_ppt_layout", "knowledge_topology_and_text_metrics"
    if text_ratio >= 0.12 and (high_sat_ratio >= 0.035 or light_bg_ratio < 0.55):
        return "commercial_brand_visual", "dense_text_color_layout_metrics"
    if high_sat_ratio >= 0.06:
        return "commercial_product", "product_color_and_edge_metrics"
    if text_ratio >= 0.055 and light_bg_ratio >= 0.30:
        return "commercial_ppt_layout", "text_dense_light_layout_metrics"
    return "unknown", "insufficient_content_type_evidence"


def content_type_fields(content_type: str | None, fallback_profile: str | None = None) -> dict[str, object]:
    resolved = content_type if content_type in CONTENT_TYPES else "unknown"
    profile = CONTENT_TYPE_TO_PROFILE.get(resolved, fallback_profile or "general_visual")
    return {
        "content_type": resolved,
        "content_type_review": "manual_review" if resolved == "unknown" else "classified",
        "image_quality_profile": profile,
    }


def _normalized_roi_crop(image: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
    x1, y1, x2, y2 = _normalized_box_pixel_bounds(image, box)
    return image[y1:y2, x1:x2]


def _normalized_box_pixel_bounds(image: np.ndarray, box: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    height, width = image.shape[:2]
    x1 = max(0, min(width - 1, int(round(width * box[0]))))
    y1 = max(0, min(height - 1, int(round(height * box[1]))))
    x2 = max(x1 + 1, min(width, int(round(width * box[2]))))
    y2 = max(y1 + 1, min(height, int(round(height * box[3]))))
    return x1, y1, x2, y2


def _stroke_structure_consistency(before: np.ndarray, after: np.ndarray, mask: np.ndarray) -> float:
    before_gray = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    after_gray = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
    before_edges = cv2.Canny(before_gray, 45, 135) > 0
    after_edges = cv2.Canny(after_gray, 45, 135) > 0
    region = cv2.dilate((mask > 0).astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
    before_edges &= region
    after_edges &= region
    if not np.any(before_edges) or not np.any(after_edges):
        return 0.0
    before_dilated = cv2.dilate(before_edges.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
    after_dilated = cv2.dilate(after_edges.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
    recall = float(np.mean(after_dilated[before_edges]))
    precision = float(np.mean(before_dilated[after_edges]))
    return float(100.0 * (2.0 * precision * recall / max(precision + recall, 1e-9)))


def _validated_normalized_box(box: object) -> tuple[float, float, float, float] | None:
    try:
        values = tuple(float(value) for value in box)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if len(values) != 4 or not all(np.isfinite(value) for value in values):
        return None
    x1, y1, x2, y2 = values
    if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
        return None
    return x1, y1, x2, y2


def _same_coordinate_roi_pair(
    original: np.ndarray,
    enhanced: np.ndarray,
    box: object,
) -> tuple[np.ndarray | None, np.ndarray | None, tuple[int, int] | None, str]:
    normalized = _validated_normalized_box(box)
    if normalized is None:
        return None, None, None, "invalid_normalized_roi_box"
    before = _normalized_roi_crop(original, normalized)
    after = _normalized_roi_crop(enhanced, normalized)
    if min(before.shape[:2], default=0) < 4 or min(after.shape[:2], default=0) < 4:
        return None, None, None, "roi_too_small_for_measurement"
    evaluation_width = max(24, min(640, max(before.shape[1], after.shape[1])))
    evaluation_height = max(16, min(384, max(before.shape[0], after.shape[0])))
    evaluation_size = (evaluation_width, evaluation_height)
    before_eval = cv2.resize(before, evaluation_size, interpolation=cv2.INTER_AREA if before.shape[1] > evaluation_width else cv2.INTER_CUBIC)
    after_eval = cv2.resize(after, evaluation_size, interpolation=cv2.INTER_AREA if after.shape[1] > evaluation_width else cv2.INTER_CUBIC)
    return before_eval, after_eval, evaluation_size, "available"


def _text_roi_absolute_measurement(image: np.ndarray, mask: np.ndarray) -> dict[str, object]:
    region = mask > 0
    if int(np.sum(region)) < 32:
        return {"score": "not_applicable", "detail_energy": "not_applicable", "local_contrast": "not_applicable", "edge_density": "not_applicable"}
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    detail_energy = _masked_laplacian_score(image, mask)
    local_contrast = float(np.std(gray[region]))
    edges = cv2.Canny(gray, 45, 135) > 0
    edge_density = float(np.mean(edges[region]))
    score = float(np.clip(18.0 + 13.5 * np.log1p(max(detail_energy, 0.0)) + 0.22 * local_contrast + 18.0 * edge_density, 0.0, 100.0))
    return {
        "score": round(score, 2),
        "detail_energy": round(detail_energy, 4),
        "local_contrast": round(local_contrast, 4),
        "edge_density": round(edge_density, 4),
    }


def text_roi_quality_evidence(
    original: np.ndarray,
    final_png: np.ndarray,
    image_quality_profile: str,
    roi_boxes: dict[str, tuple[float, float, float, float]] | None = None,
    glyph_integrity_review: str | None = None,
    glyph_review_evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    explicit_rois = bool(roi_boxes)
    if image_quality_profile in {"portrait_photo", "portrait_group"} and not explicit_rois:
        return {
            "text_metric_applicable": False,
            "text_metric_status": "not_applicable",
            "text_metric_reason": f"{image_quality_profile}_without_required_core_text",
            "text_clarity_score": "not_applicable",
            "text_clarity_gain": "not_applicable",
            "primary_text_roi_score": "not_applicable",
            "primary_text_roi_gain": "not_applicable",
            "commercial_text_quality_pass": "not_applicable",
            "valid_text_roi_count": 0,
            "text_roi_details": [],
            "text_score_100_eligible": False,
            "text_glyph_integrity_review": "not_applicable",
            "roi_source": "automatic_none",
        }

    regions = roi_boxes or {"detected_primary_text": (0.0, 0.0, 1.0, 1.0)}
    roi_source = "manual_coordinates" if explicit_rois else "automatic_detected"
    details: list[dict[str, object]] = []
    for name, box in regions.items():
        before_roi, after_roi, evaluation_size, pair_status = _same_coordinate_roi_pair(original, final_png, box)
        normalized_box = _validated_normalized_box(box)
        if pair_status != "available" or before_roi is None or after_roi is None or evaluation_size is None:
            details.append({
                "roi_name": name,
                "normalized_box": list(normalized_box) if normalized_box else list(box) if isinstance(box, (list, tuple)) else box,
                "roi_box_normalized": list(normalized_box) if normalized_box else "not_applicable",
                "status": "not_applicable",
                "applicability_reason": pair_status,
                "original_score": "not_applicable",
                "enhanced_score": "not_applicable",
                "beta_score": "not_applicable",
                "score_gain": "not_applicable",
                "roi_source": roi_source,
            })
            continue
        text_mask, mask_fields = build_primary_delivery_text_mask(before_roi)
        if not np.any(text_mask) or float(mask_fields["primary_text_roi_confidence"]) < 0.25:
            details.append({
                "roi_name": name,
                "normalized_box": list(normalized_box or ()),
                "roi_box_normalized": list(normalized_box or ()),
                "status": "missing_reliable_text_mask",
                "applicability_reason": "no_reliable_text_mask",
                "original_score": "not_applicable",
                "enhanced_score": "not_applicable",
                "beta_score": "not_applicable",
                "score_gain": "not_applicable",
                "evaluation_size": list(evaluation_size),
                "scoring_method": "same_mask_absolute_text_roi_measurement",
                "scoring_version": "rc8a_v2",
                "roi_source": roi_source,
                **mask_fields,
            })
            continue
        original_measurement = _text_roi_absolute_measurement(before_roi, text_mask)
        enhanced_measurement = _text_roi_absolute_measurement(after_roi, text_mask)
        original_score = metric_number(original_measurement.get("score"))
        enhanced_score = metric_number(enhanced_measurement.get("score"))
        if original_score is None or enhanced_score is None:
            details.append({
                "roi_name": name,
                "normalized_box": list(normalized_box or ()),
                "roi_box_normalized": list(normalized_box or ()),
                "status": "not_applicable",
                "applicability_reason": "absolute_score_not_applicable",
                "original_score": "not_applicable",
                "enhanced_score": "not_applicable",
                "beta_score": "not_applicable",
                "score_gain": "not_applicable",
                "evaluation_size": list(evaluation_size),
                "scoring_method": "same_mask_absolute_text_roi_measurement",
                "scoring_version": "rc8a_v2",
                "roi_source": roi_source,
                **mask_fields,
            })
            continue
        score_gain = enhanced_score - original_score
        before_detail = float(original_measurement["detail_energy"])
        after_detail = float(enhanced_measurement["detail_energy"])
        raw_gain = float((after_detail - before_detail) / max(before_detail, 1.0) * 100.0)
        edge_fields = edge_artifact_quality(before_roi, after_roi, 100.0)
        structure_score = _stroke_structure_consistency(before_roi, after_roi, text_mask)
        details.append({
            "roi_name": name,
            "normalized_box": list(normalized_box or ()),
            "roi_box_normalized": list(normalized_box or ()),
            "status": "available",
            "applicability_reason": "same_coordinate_roi_measured",
            "original_score": round(original_score, 2),
            "enhanced_score": round(enhanced_score, 2),
            "beta_score": round(enhanced_score, 2),
            "score_gain": round(score_gain, 2),
            "original_detail_energy": round(before_detail, 4),
            "beta_detail_energy": round(after_detail, 4),
            "raw_detail_gain_percent": round(raw_gain, 2),
            "original_local_contrast": original_measurement["local_contrast"],
            "enhanced_local_contrast": enhanced_measurement["local_contrast"],
            "original_edge_density": original_measurement["edge_density"],
            "enhanced_edge_density": enhanced_measurement["edge_density"],
            "stroke_structure_consistency_score": round(structure_score, 2),
            "halo_ringing_pass": edge_fields["halo_ringing_pass"],
            "edge_overshoot_ratio": edge_fields["edge_overshoot_ratio"],
            "halo_ringing_penalty": edge_fields["halo_ringing_penalty"],
            "evaluation_size": list(evaluation_size),
            "scoring_method": "same_mask_absolute_text_roi_measurement",
            "scoring_version": "rc8a_v2",
            "roi_source": roi_source,
            **mask_fields,
        })

    valid = [item for item in details if item.get("status") == "available"]
    required = image_quality_profile in TEXT_REQUIRED_PROFILES
    if not valid:
        status = "missing_required_roi" if required and explicit_rois else "not_applicable"
        return {
            "text_metric_applicable": False,
            "text_metric_status": status,
            "text_metric_reason": "required_text_roi_missing" if status == "missing_required_roi" else "no_reliable_text_roi",
            "text_clarity_score": "not_applicable",
            "text_clarity_gain": "not_applicable",
            "primary_text_roi_score": "not_applicable",
            "primary_text_roi_gain": "not_applicable",
            "commercial_text_quality_pass": False if required else "not_applicable",
            "valid_text_roi_count": 0,
            "text_roi_details": details,
            "text_score_100_eligible": False,
            "text_glyph_integrity_review": "not_applicable",
            "roi_source": roi_source if explicit_rois else "automatic_none",
        }

    aggregate_original_score = float(np.mean([float(item["original_score"]) for item in valid]))
    aggregate_raw_score = float(np.mean([float(item["enhanced_score"]) for item in valid]))
    no_negative_gain = all(float(item["score_gain"]) >= 0.0 for item in valid)
    artifact_free = all(bool(item["halo_ringing_pass"]) for item in valid)
    automated_safety_evidence = bool(
        len(valid) >= 2
        and no_negative_gain
        and artifact_free
        and all(float(item["stroke_structure_consistency_score"]) >= 98.0 for item in valid)
    )
    glyph_review_evidence = glyph_review_evidence or {}
    traceable_human_confirmation = bool(
        glyph_integrity_review == "human_confirmed"
        and glyph_review_evidence.get("status") == "human_confirmed"
        and str(glyph_review_evidence.get("reviewer") or "").strip()
        and str(glyph_review_evidence.get("reviewed_at") or "").strip()
    )
    resolved_glyph_review = "human_confirmed" if traceable_human_confirmation else "requires_human_review"
    eligible = bool(resolved_glyph_review == "human_confirmed" and automated_safety_evidence)
    aggregate_score = min(aggregate_raw_score, 99.0) if resolved_glyph_review != "human_confirmed" else aggregate_raw_score
    aggregate_gain = aggregate_raw_score - aggregate_original_score
    quality_pass = bool(aggregate_gain >= 0.0 and no_negative_gain and artifact_free)
    return {
        "text_metric_applicable": True,
        "text_metric_status": "available",
        "text_metric_reason": "same_coordinate_text_roi_evidence",
        "text_clarity_score": round(aggregate_score, 2),
        "text_clarity_score_raw": round(aggregate_raw_score, 2),
        "text_clarity_gain": round(aggregate_gain, 2),
        "primary_text_roi_score": round(aggregate_score, 2),
        "primary_text_roi_gain": round(aggregate_gain, 2),
        "commercial_text_quality_pass": quality_pass,
        "valid_text_roi_count": len(valid),
        "text_roi_details": details,
        "text_score_100_eligible": eligible,
        "text_score_cap_reason": "none" if resolved_glyph_review == "human_confirmed" or aggregate_raw_score < 100.0 else "glyph_integrity_unverified",
        "text_roi_artifact_free": artifact_free,
        "text_roi_no_negative_gain": no_negative_gain,
        "text_glyph_integrity_review": resolved_glyph_review,
        "text_glyph_review_evidence": glyph_review_evidence if traceable_human_confirmation else "not_available",
        "roi_source": roi_source,
        "original_text_roi_score": round(aggregate_original_score, 2),
    }


def _small_text_candidate_fields(
    image: np.ndarray,
    box: tuple[float, float, float, float],
    roi_id: str,
    text_role: str,
    detector_confidence: float,
    roi_source: str,
    estimated_character_height_px: int | None = None,
) -> dict[str, object]:
    roi = _normalized_roi_crop(image, box)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    height = int(estimated_character_height_px or max(1, min(roi.shape[0], round(roi.shape[0] * 0.62))))
    local_contrast = float(np.std(gray))
    laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    blur_severity = float(1.0 / (1.0 + laplacian_variance / 42.0))
    background_complexity = float(np.mean(cv2.Canny(gray, 45, 135) > 0))
    if text_role in {"decorative_microtext", "decorative_line", "icon_candidate", "icon", "unknown_text"} and detector_confidence < 0.45:
        recoverability = "not_applicable"
        reason = "low_confidence_non_semantic_text_candidate"
    elif height < 5 or local_contrast < 5.0 or blur_severity >= 0.94:
        recoverability = "unrecoverable"
        reason = "insufficient_original_stroke_information"
    elif height < 8 or local_contrast < 12.0 or blur_severity >= 0.78 or background_complexity > 0.48:
        recoverability = "limited_recoverable"
        reason = "visible_strokes_with_blur_or_background_limits"
    else:
        recoverability = "recoverable"
        reason = "stroke_structure_and_local_separation_available"
    return {
        "roi_id": roi_id,
        "roi_box_normalized": [round(value, 6) for value in box],
        "text_role": text_role,
        "detector_confidence": round(detector_confidence, 4),
        "estimated_character_height_px": int(height),
        "local_contrast": round(local_contrast, 3),
        "blur_severity": round(blur_severity, 4),
        "background_complexity": round(background_complexity, 4),
        "recoverability_status": recoverability,
        "recoverability_reason": reason,
        "roi_source": roi_source,
    }


def _small_text_line_geometry(
    image: np.ndarray,
    candidate_pixels: np.ndarray,
    edges: np.ndarray,
    pixels: list[int],
) -> dict[str, object]:
    x1, y1, x2, y2 = pixels
    binary = (candidate_pixels[y1:y2, x1:x2] > 0).astype(np.uint8)
    edge_roi = edges[y1:y2, x1:x2]
    hsv_roi = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    components = [stats[index] for index in range(1, count) if stats[index, cv2.CC_STAT_AREA] >= 2 and stats[index, cv2.CC_STAT_HEIGHT] >= 2]
    widths = np.array([item[cv2.CC_STAT_WIDTH] for item in components], dtype=np.float32)
    heights = np.array([item[cv2.CC_STAT_HEIGHT] for item in components], dtype=np.float32)
    baselines = np.array([item[cv2.CC_STAT_TOP] + item[cv2.CC_STAT_HEIGHT] for item in components], dtype=np.float32)
    order = sorted(components, key=lambda item: item[cv2.CC_STAT_LEFT])
    gaps = np.array([
        max(0, order[index + 1][cv2.CC_STAT_LEFT] - (order[index][cv2.CC_STAT_LEFT] + order[index][cv2.CC_STAT_WIDTH]))
        for index in range(len(order) - 1)
    ], dtype=np.float32)
    median_height = float(np.median(heights)) if heights.size else 0.0
    height_cv = float(np.std(heights) / max(np.mean(heights), 1.0)) if heights.size else 99.0
    baseline_deviation = float(np.std(baselines) / max(median_height, 1.0)) if baselines.size else 99.0
    gap_cv = float(np.std(gaps) / max(np.mean(gaps), 1.0)) if gaps.size >= 2 else 0.0
    region_height, region_width = binary.shape
    aspect = region_width / max(region_height, 1)
    stroke_density = float(np.mean(binary > 0)) if binary.size else 0.0
    edge_count = max(int(np.count_nonzero(edge_roi)), 1)
    horizontal = cv2.morphologyEx(edge_roi, cv2.MORPH_OPEN, np.ones((1, max(9, region_width // 3)), np.uint8), iterations=1)
    vertical = cv2.morphologyEx(edge_roi, cv2.MORPH_OPEN, np.ones((max(9, region_height // 2), 1), np.uint8), iterations=1)
    straight_edge_ratio = float((np.count_nonzero(horizontal) + np.count_nonzero(vertical)) / edge_count)
    highlight_ratio = float(np.mean((hsv_roi[:, :, 1] < 38) & (hsv_roi[:, :, 2] > 220))) if hsv_roi.size else 0.0
    component_count = len(components)
    regular_height = component_count >= 2 and height_cv <= 0.62
    regular_baseline = component_count >= 2 and baseline_deviation <= 0.72
    regular_spacing = component_count < 4 or gap_cv <= 1.35
    text_line_score = sum((
        1.0 if component_count >= 2 else 0.0,
        1.0 if aspect >= 1.8 else 0.0,
        1.0 if regular_height else 0.0,
        1.0 if regular_baseline else 0.0,
        0.6 if regular_spacing else 0.0,
        0.6 if 0.025 <= stroke_density <= 0.62 else 0.0,
    ))
    container_edge_risk = straight_edge_ratio > 0.48 and component_count <= 3
    highlight_or_icon_risk = bool(highlight_ratio > 0.32 and component_count <= 3 and aspect < 2.2)
    repeated_texture_risk = bool(component_count >= 5 and (height_cv > 0.72 or baseline_deviation > 0.90) and gap_cv > 1.10)
    accepted = bool(text_line_score >= 4.0 and not container_edge_risk and not highlight_or_icon_risk and not repeated_texture_risk)
    reason = (
        "validated_visual_text_line" if accepted
        else "container_edge_structure" if container_edge_risk
        else "highlight_or_icon_structure" if highlight_or_icon_risk
        else "repeated_texture_irregularity" if repeated_texture_risk
        else "insufficient_line_geometry"
    )
    return {
        "connected_component_count": component_count,
        "median_character_height": round(median_height, 3),
        "character_height_cv": round(height_cv, 4),
        "baseline_deviation_ratio": round(baseline_deviation, 4),
        "character_gap_cv": round(gap_cv, 4),
        "stroke_density": round(stroke_density, 4),
        "candidate_line_aspect": round(aspect, 3),
        "straight_edge_ratio": round(straight_edge_ratio, 4),
        "highlight_ratio": round(highlight_ratio, 4),
        "text_line_score": round(float(text_line_score), 2),
        "background_texture_risk": repeated_texture_risk,
        "highlight_or_icon_risk": highlight_or_icon_risk,
        "container_edge_risk": container_edge_risk,
        "visual_text_line_validated": accepted,
        "visual_text_line_reason": reason,
    }


def detect_small_text_rois(
    image: np.ndarray,
    content_type: str,
    manual_rois: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    if content_type not in SMALL_TEXT_CONTENT_TYPES:
        return []
    if manual_rois:
        candidates: list[dict[str, object]] = []
        for roi_id, specification in manual_rois.items():
            if isinstance(specification, dict):
                box = _validated_normalized_box(specification.get("box"))
                role = str(specification.get("text_role") or "small_text")
            else:
                box = _validated_normalized_box(specification)
                role = "small_text"
            if box is None:
                candidates.append({
                    "roi_id": str(roi_id),
                    "roi_box_normalized": "not_applicable",
                    "text_role": role,
                    "detector_confidence": 1.0,
                    "estimated_character_height_px": "not_applicable",
                    "local_contrast": "not_applicable",
                    "blur_severity": "not_applicable",
                    "background_complexity": "not_applicable",
                    "recoverability_status": "not_applicable",
                    "recoverability_reason": "invalid_manual_roi_box",
                    "roi_source": "manual_coordinates",
                })
                continue
            candidates.append(_small_text_candidate_fields(image, box, str(roi_id), role, 1.0, "manual_coordinates"))
        return candidates

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 21, 7)
    edges = cv2.Canny(gray, 42, 128)
    edge_supported = cv2.bitwise_and(adaptive, cv2.dilate(edges, np.ones((2, 2), np.uint8), iterations=1))
    low_contrast_strokes = cv2.morphologyEx(adaptive, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    candidate_pixels = cv2.bitwise_or(edge_supported, low_contrast_strokes)
    candidate_pixels = cv2.morphologyEx(candidate_pixels, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8), iterations=1)
    grouped = cv2.dilate(candidate_pixels, np.ones((3, 7), np.uint8), iterations=1)
    contours, _ = cv2.findContours(grouped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    height, width = gray.shape
    candidate_regions: list[dict[str, object]] = []
    for index, contour in enumerate(sorted(contours, key=lambda item: cv2.boundingRect(item)[1:3])):
        x, y, region_width, region_height = cv2.boundingRect(contour)
        if region_width < 8 or region_height < 4 or region_height > max(42, int(height * 0.10)):
            continue
        if region_width * region_height > width * height * 0.08:
            continue
        pad = max(2, int(round(region_height * 0.30)))
        x1, y1 = max(0, x - pad), max(0, y - pad)
        x2, y2 = min(width, x + region_width + pad), min(height, y + region_height + pad)
        pixel_region = candidate_pixels[y1:y2, x1:x2] > 0
        stroke_density = float(np.mean(pixel_region)) if pixel_region.size else 0.0
        local_contrast = float(np.std(gray[y1:y2, x1:x2]))
        confidence = float(np.clip(stroke_density * 3.2 + min(local_contrast / 80.0, 0.45), 0.0, 1.0))
        if confidence < 0.28:
            continue
        candidate_regions.append({"pixels": [x1, y1, x2, y2], "character_height": region_height, "confidence": confidence})
    merged_regions: list[dict[str, object]] = []
    for region in sorted(candidate_regions, key=lambda value: (int(value["pixels"][1]), int(value["pixels"][0]))):
        x1, y1, x2, y2 = (int(value) for value in region["pixels"])  # type: ignore[index]
        merged = False
        for existing in merged_regions:
            ex1, ey1, ex2, ey2 = (int(value) for value in existing["pixels"])  # type: ignore[index]
            horizontal_overlap = min(x2, ex2) - max(x1, ex1)
            vertical_overlap = min(y2, ey2) - max(y1, ey1)
            region_height = y2 - y1; existing_height = ey2 - ey1
            center_delta = abs((y1 + y2) / 2.0 - (ey1 + ey2) / 2.0)
            horizontal_gap = max(0, max(x1, ex1) - min(x2, ex2))
            same_visual_line = bool(
                center_delta <= max(region_height, existing_height) * 0.62
                and horizontal_gap <= max(14, max(region_height, existing_height) * 3.2)
                and max(region_height, existing_height) / max(min(region_height, existing_height), 1) <= 2.2
            )
            if (horizontal_overlap > 0 and vertical_overlap > 0) or same_visual_line:
                existing["pixels"] = [min(x1, ex1), min(y1, ey1), max(x2, ex2), max(y2, ey2)]
                existing["character_height"] = max(int(existing["character_height"]), int(region["character_height"]))
                existing["confidence"] = max(float(existing["confidence"]), float(region["confidence"]))
                merged = True
                break
        if not merged:
            merged_regions.append(dict(region))
    candidates: list[dict[str, object]] = []
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    for region in merged_regions:
        x1, y1, x2, y2 = (int(value) for value in region["pixels"])  # type: ignore[index]
        character_height = int(region["character_height"])
        confidence = float(region["confidence"])
        geometry = _small_text_line_geometry(image, candidate_pixels, edges, [x1, y1, x2, y2])
        box = (x1 / width, y1 / height, x2 / width, y2 / height)
        region_width_ratio = (x2 - x1) / max(width, 1)
        region_aspect = (x2 - x1) / max(y2 - y1, 1)
        saturation = float(np.mean(hsv[y1:y2, x1:x2, 1])) if y2 > y1 and x2 > x1 else 0.0
        if geometry["visual_text_line_validated"] is not True:
            role = (
                "container_edge" if geometry["container_edge_risk"]
                else "icon_candidate" if geometry["highlight_or_icon_risk"]
                else "background_texture" if geometry["background_texture_risk"]
                else "decorative_microtext"
            )
        elif character_height >= max(24, int(height * 0.035)) or region_width_ratio >= 0.34:
            role = "primary_text"
        elif region_aspect >= 12.0 and character_height <= 6:
            role = "decorative_line"
        elif region_aspect <= 1.45 and confidence < 0.52 and saturation >= 70.0:
            role = "icon_candidate"
        elif character_height <= 7 and confidence < 0.55:
            role = "decorative_microtext"
        elif region_width_ratio <= 0.10:
            role = "label_text"
        elif region_width_ratio <= 0.22 and y1 / max(height, 1) < 0.76:
            role = "name_text"
        elif x1 / max(width, 1) >= 0.64:
            role = "parameter_text"
        elif character_height <= 20:
            role = "description_text"
        else:
            role = "secondary_text"
        candidate = _small_text_candidate_fields(
            image,
            box,
            f"auto_{len(candidates) + 1:02d}",
            role,
            confidence,
            "automatic_connected_text_structure",
            estimated_character_height_px=character_height,
        )
        candidate.update({
            "candidate_region_aspect": round(region_aspect, 3),
            "candidate_region_width_ratio": round(region_width_ratio, 4),
            "text_non_text_filter_status": "text_candidate" if geometry["visual_text_line_validated"] else "filtered_non_text",
            "text_non_text_filter_reason": geometry["visual_text_line_reason"],
            "candidate_truth_status": "validated_text_line" if geometry["visual_text_line_validated"] else "not_applicable_non_text",
            **geometry,
        })
        if geometry["visual_text_line_validated"] is not True:
            candidate["recoverability_status"] = "not_applicable"
            candidate["recoverability_reason"] = str(geometry["visual_text_line_reason"])
        candidates.append(candidate)
    return candidates


def _small_text_image_signature(image: np.ndarray) -> str:
    digest = hashlib.sha256()
    contiguous = np.ascontiguousarray(image)
    digest.update(str(contiguous.shape).encode("ascii"))
    digest.update(contiguous.tobytes())
    return digest.hexdigest()


def _small_text_code_signature() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return "unavailable"


def _small_text_mask_evidence(mask: np.ndarray, prefix: str) -> dict[str, object]:
    contiguous = np.ascontiguousarray(mask.astype(np.uint8))
    return {
        f"{prefix}_shape": [int(contiguous.shape[1]), int(contiguous.shape[0])],
        f"{prefix}_coverage": round(float(np.mean(contiguous > 0)), 6),
        f"{prefix}_signature": hashlib.sha256(contiguous.tobytes()).hexdigest(),
    }


def _normalized_bbox_to_pixels(
    box: tuple[float, float, float, float],
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    x1 = max(0, min(width, int(math.floor(box[0] * width))))
    y1 = max(0, min(height, int(math.floor(box[1] * height))))
    x2 = max(0, min(width, int(math.ceil(box[2] * width))))
    y2 = max(0, min(height, int(math.ceil(box[3] * height))))
    if x2 - x1 < 1 or y2 - y1 < 1:
        return None
    return x1, y1, x2, y2


def prepare_automatic_small_text_candidates(
    image: np.ndarray,
    content_type: str,
    source_image_id: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Build the exact automatic candidate objects consumed by the enhancer."""
    global_text_mask, global_text_fields = build_primary_delivery_text_mask(image)
    reliable_text = bool(
        np.any(global_text_mask)
        and float(global_text_fields.get("primary_text_roi_confidence") or 0.0) >= 0.25
    )
    input_signature = _small_text_image_signature(image)
    code_signature = _small_text_code_signature()
    source_height, source_width = image.shape[:2]
    raw_candidates = detect_small_text_rois(image, content_type)
    prepared: list[dict[str, object]] = []
    supported_roles = {"small_text", "secondary_text", "name_text", "label_text", "description_text", "parameter_text"}
    for index, raw in enumerate(raw_candidates, start=1):
        box = _validated_normalized_box(raw.get("roi_box_normalized"))
        if box is None:
            continue
        bbox_source = _normalized_bbox_to_pixels(box, source_width, source_height)
        if bbox_source is None:
            continue
        sx1, sy1, sx2, sy2 = bbox_source
        roi = image[sy1:sy2, sx1:sx2]
        base_mask, _ = build_primary_delivery_text_mask(roi)
        text_mask, structure_mask_fields = _small_text_structure_mask(roi, base_mask)
        container_mask = _container_edge_exclusion_mask(roi)
        background_mask = cv2.bitwise_not(cv2.bitwise_or(text_mask, container_mask))
        detection_id = f"{source_image_id}:det:{index:04d}"
        automatic_role = str(raw.get("text_role") or "unknown_text")
        detector_confidence = float(raw.get("detector_confidence") or 0.0)
        role_confidence = float(np.clip(
            detector_confidence * (1.0 if raw.get("visual_text_line_validated") is True else 0.45),
            0.0,
            1.0,
        ))
        enhancement_eligible = bool(
            reliable_text
            and raw.get("visual_text_line_validated") is True
            and automatic_role in supported_roles
            and raw.get("recoverability_status") in {"recoverable", "limited_recoverable"}
            and structure_mask_fields.get("small_text_structure_mask_status") == "available"
        )
        candidate = dict(raw)
        candidate.update({
            "detection_id": detection_id,
            "source_image_id": source_image_id,
            "bbox_source_normalized": [round(value, 6) for value in box],
            "source_width": source_width,
            "source_height": source_height,
            "stage_width": "not_mapped",
            "stage_height": "not_mapped",
            "source_coordinate_space": "source_original",
            "stage_coordinate_space": "not_mapped",
            "scale_x": "not_mapped",
            "scale_y": "not_mapped",
            "bbox_source": list(bbox_source),
            "bbox_stage": "not_mapped",
            "detection_confidence": round(detector_confidence, 4),
            "merged_line_id": f"{source_image_id}:line:{index:04d}",
            "automatic_text_role": automatic_role,
            "role_confidence": round(role_confidence, 4),
            "reliable_text_status": "reliable" if reliable_text else "evidence_missing",
            "enhancement_eligible": enhancement_eligible,
            "execution_input_source": "automatic_detection",
            "code_signature": code_signature,
            "input_signature": input_signature,
            "text_mask": text_mask,
            "background_exclusion_mask": background_mask,
            "container_edge_exclusion_mask": container_mask,
            "mask_source_shape": [int(text_mask.shape[0]), int(text_mask.shape[1])],
            "mask_stage_shape": "not_mapped",
            "coordinate_contract_pass": "pending_stage_mapping",
            "mask_contract_pass": "pending_stage_mapping",
            **structure_mask_fields,
            **_small_text_mask_evidence(text_mask, "text_mask"),
            **_small_text_mask_evidence(background_mask, "background_exclusion_mask"),
            **_small_text_mask_evidence(container_mask, "container_edge_exclusion_mask"),
        })
        prepared.append(candidate)
    return prepared, {
        "source_image_id": source_image_id,
        "source_width": source_width,
        "source_height": source_height,
        "source_coordinate_space": "source_original",
        "input_signature": input_signature,
        "code_signature": code_signature,
        "reliable_text_status": "reliable" if reliable_text else "evidence_missing",
        "automatic_candidate_count": len(prepared),
        "automatic_enhancement_eligible_count": sum(item.get("enhancement_eligible") is True for item in prepared),
    }


def map_automatic_small_text_candidate_to_stage(
    candidate: dict[str, object],
    source_image: np.ndarray,
    stage_input: np.ndarray,
    source_image_id: str,
    code_signature: str,
) -> tuple[dict[str, object], dict[str, np.ndarray] | None]:
    source_height, source_width = source_image.shape[:2]
    stage_height, stage_width = stage_input.shape[:2]
    scale_x = stage_width / max(source_width, 1)
    scale_y = stage_height / max(source_height, 1)
    evidence: dict[str, object] = {
        "source_width": source_width,
        "source_height": source_height,
        "stage_width": stage_width,
        "stage_height": stage_height,
        "source_coordinate_space": "source_original",
        "stage_coordinate_space": "stage_input",
        "beta_coordinate_space": "beta_output",
        "scale_x": round(scale_x, 8),
        "scale_y": round(scale_y, 8),
        "bbox_source": candidate.get("bbox_source", "not_available"),
        "bbox_stage": "not_mapped",
        "mask_source_shape": candidate.get("mask_source_shape", "not_available"),
        "mask_stage_shape": "not_mapped",
        "coordinate_contract_pass": False,
        "mask_contract_pass": False,
        "contract_failure_reason": "pending_validation",
        "scoring_called": False,
        "enhancement_called": False,
    }
    failures: list[str] = []
    if candidate.get("execution_input_source") != "automatic_detection":
        failures.append("execution_input_source_invalid")
    if candidate.get("source_image_id") != source_image_id:
        failures.append("source_image_id_mismatch")
    if candidate.get("source_width") != source_width or candidate.get("source_height") != source_height:
        failures.append("source_dimensions_mismatch")
    if candidate.get("input_signature") != _small_text_image_signature(source_image):
        failures.append("source_input_signature_mismatch")
    if candidate.get("code_signature") != code_signature:
        failures.append("code_signature_mismatch")
    raw_bbox = candidate.get("bbox_source")
    try:
        sx1, sy1, sx2, sy2 = (int(value) for value in raw_bbox)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        failures.append("bbox_source_invalid")
        sx1 = sy1 = sx2 = sy2 = 0
    source_bbox_valid = bool(
        0 <= sx1 < sx2 <= source_width
        and 0 <= sy1 < sy2 <= source_height
        and sx2 - sx1 >= 1
        and sy2 - sy1 >= 1
    )
    if not source_bbox_valid:
        failures.append("bbox_source_out_of_bounds_or_empty")
    stage_bbox = (
        max(0, min(stage_width, int(math.floor(sx1 * scale_x)))),
        max(0, min(stage_height, int(math.floor(sy1 * scale_y)))),
        max(0, min(stage_width, int(math.ceil(sx2 * scale_x)))),
        max(0, min(stage_height, int(math.ceil(sy2 * scale_y)))),
    )
    tx1, ty1, tx2, ty2 = stage_bbox
    stage_bbox_valid = bool(tx2 - tx1 >= 2 and ty2 - ty1 >= 2)
    if not stage_bbox_valid:
        failures.append("bbox_stage_below_minimum_2px_or_empty")
    evidence["bbox_stage"] = list(stage_bbox)
    evidence["mapped_stage_roi_shape"] = [max(0, ty2 - ty1), max(0, tx2 - tx1)]
    evidence["coordinate_contract_pass"] = bool(source_bbox_valid and stage_bbox_valid and not any(
        reason in failures for reason in (
            "source_dimensions_mismatch", "source_input_signature_mismatch", "bbox_source_invalid", "bbox_source_out_of_bounds_or_empty"
        )
    ))
    source_roi_shape = (max(0, sy2 - sy1), max(0, sx2 - sx1))
    source_masks = {
        "text_mask": candidate.get("text_mask"),
        "background_exclusion_mask": candidate.get("background_exclusion_mask"),
        "container_edge_exclusion_mask": candidate.get("container_edge_exclusion_mask"),
    }
    source_masks_valid = True
    for name, mask in source_masks.items():
        if not isinstance(mask, np.ndarray):
            failures.append(f"{name}_missing_or_not_array")
            source_masks_valid = False
            continue
        if mask.dtype != np.uint8:
            failures.append(f"{name}_dtype_not_uint8")
            source_masks_valid = False
        if mask.shape != source_roi_shape:
            failures.append(f"{name}_source_shape_mismatch")
            source_masks_valid = False
    if isinstance(source_masks["text_mask"], np.ndarray) and np.count_nonzero(source_masks["text_mask"]) < 1:
        failures.append("text_mask_has_no_valid_pixels")
        source_masks_valid = False
    mapped_masks: dict[str, np.ndarray] | None = None
    if evidence["coordinate_contract_pass"] is True and source_masks_valid:
        target_width = tx2 - tx1; target_height = ty2 - ty1
        mapped_masks = {}
        for name, mask in source_masks.items():
            resized = cv2.resize(mask, (target_width, target_height), interpolation=cv2.INTER_NEAREST)  # type: ignore[arg-type]
            mapped_masks[name] = np.where(resized >= 128, 255, 0).astype(np.uint8)
        shapes_match = all(mask.shape == (target_height, target_width) for mask in mapped_masks.values())
        binary_masks = all(np.all(np.isin(np.unique(mask), (0, 255))) for mask in mapped_masks.values())
        evidence["mask_contract_pass"] = bool(shapes_match and binary_masks and np.count_nonzero(mapped_masks["text_mask"]) > 0)
        evidence["mask_stage_shape"] = [target_height, target_width]
        evidence.update(_small_text_mask_evidence(mapped_masks["text_mask"], "stage_text_mask"))
        evidence.update(_small_text_mask_evidence(mapped_masks["background_exclusion_mask"], "stage_background_exclusion_mask"))
        evidence.update(_small_text_mask_evidence(mapped_masks["container_edge_exclusion_mask"], "stage_container_edge_exclusion_mask"))
        if evidence["mask_contract_pass"] is not True:
            failures.append("mapped_mask_contract_failed")
    if evidence["coordinate_contract_pass"] is True and evidence["mask_contract_pass"] is True and not failures:
        evidence["contract_failure_reason"] = "none"
    else:
        evidence["contract_failure_reason"] = ";".join(dict.fromkeys(failures)) or "coordinate_or_mask_contract_failed"
        mapped_masks = None
    evidence["bbox_stage_normalized"] = [
        round(tx1 / max(stage_width, 1), 8),
        round(ty1 / max(stage_height, 1), 8),
        round(tx2 / max(stage_width, 1), 8),
        round(ty2 / max(stage_height, 1), 8),
    ]
    return evidence, mapped_masks


def _small_text_luma_candidate(roi: np.ndarray) -> np.ndarray:
    scale = 2.0 if min(roi.shape[:2]) < 72 else 1.5
    work = cv2.resize(roi, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)
    lab = cv2.cvtColor(work, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    denoised = cv2.bilateralFilter(l_channel, 5, 14, 3)
    local_mean = cv2.GaussianBlur(denoised, (0, 0), 0.72)
    mid_mean = cv2.GaussianBlur(denoised, (0, 0), 1.28)
    fine = np.clip(denoised.astype(np.float32) - local_mean.astype(np.float32), -8.0, 8.0)
    mid = np.clip(denoised.astype(np.float32) - mid_mean.astype(np.float32), -10.0, 10.0)
    restored_luma = np.clip(denoised.astype(np.float32) + fine * 1.02 + mid * 0.28, 0, 255).astype(np.uint8)
    restored = cv2.cvtColor(cv2.merge([restored_luma, a_channel, b_channel]), cv2.COLOR_LAB2BGR)
    return cv2.resize(restored, (roi.shape[1], roi.shape[0]), interpolation=cv2.INTER_AREA)


def _small_text_stroke_width(image: np.ndarray, reference_mask: np.ndarray) -> float | None:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if gray.size < 32:
        return None
    _, dark = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    _, light = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    support = cv2.dilate((reference_mask > 0).astype(np.uint8) * 255, np.ones((3, 3), np.uint8), iterations=1)
    dark = cv2.bitwise_and(dark, support); light = cv2.bitwise_and(light, support)
    foreground = dark if np.count_nonzero(dark) <= np.count_nonzero(light) else light
    if np.count_nonzero(foreground) < 24:
        return None
    distance = cv2.distanceTransform(foreground, cv2.DIST_L2, 3)
    values = distance[distance > 0]
    return float(np.median(values) * 2.0) if values.size else None


def _container_edge_exclusion_mask(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 55, 145)
    height, width = gray.shape
    horizontal = cv2.morphologyEx(
        edges, cv2.MORPH_OPEN, np.ones((1, max(11, width // 5)), np.uint8), iterations=1
    )
    vertical = cv2.morphologyEx(
        edges, cv2.MORPH_OPEN, np.ones((max(11, height // 4), 1), np.uint8), iterations=1
    )
    return cv2.dilate(cv2.bitwise_or(horizontal, vertical), np.ones((3, 3), np.uint8), iterations=1)


def _small_text_structure_mask(image: np.ndarray, base_mask: np.ndarray) -> tuple[np.ndarray, dict[str, object]]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 42, 128)
    stroke_support = cv2.dilate(edges, np.ones((2, 2), np.uint8), iterations=1)
    structure = cv2.bitwise_and(base_mask, stroke_support)
    structure = cv2.morphologyEx(structure, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8), iterations=1)
    container_edges = _container_edge_exclusion_mask(image)
    structure = cv2.bitwise_and(structure, cv2.bitwise_not(container_edges))
    coverage = float(np.mean(structure > 0))
    return structure, {
        "small_text_structure_mask_coverage": round(coverage, 4),
        "small_text_container_edge_excluded_ratio": round(float(np.mean(container_edges > 0)), 4),
        "small_text_structure_mask_status": "available" if np.count_nonzero(structure) >= 24 else "insufficient",
    }


def _small_text_binary_structure(image: np.ndarray, text_mask: np.ndarray) -> tuple[np.ndarray, int, int]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 42, 128)
    binary = ((edges > 0) & (text_mask > 0)).astype(np.uint8)
    component_count, _, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    components = sum(stats[index, cv2.CC_STAT_AREA] >= 2 for index in range(1, component_count))
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    counters = 0
    if hierarchy is not None:
        counters = sum(int(item[3]) >= 0 for item in hierarchy[0])
    return binary, int(components), int(counters)


def _small_text_structure_metrics(
    stage_input_roi: np.ndarray,
    candidate_roi: np.ndarray,
    text_mask: np.ndarray,
) -> dict[str, object]:
    structure = _stroke_structure_consistency(stage_input_roi, candidate_roi, text_mask)
    stage_width = _small_text_stroke_width(stage_input_roi, text_mask)
    candidate_width = _small_text_stroke_width(candidate_roi, text_mask)
    stroke_delta = (
        (candidate_width - stage_width) / max(stage_width, 0.5)
        if stage_width is not None and candidate_width is not None else None
    )
    stage_binary, stage_components, stage_counters = _small_text_binary_structure(stage_input_roi, text_mask)
    candidate_binary, candidate_components, candidate_counters = _small_text_binary_structure(candidate_roi, text_mask)
    component_delta = candidate_components - stage_components
    connectivity_delta = abs(component_delta) / max(stage_components, 1)
    counter_preservation = 1.0 - abs(candidate_counters - stage_counters) / max(stage_counters, 1)
    dilated_stage = cv2.dilate(stage_binary, np.ones((3, 3), np.uint8), iterations=1)
    dilated_candidate = cv2.dilate(candidate_binary, np.ones((3, 3), np.uint8), iterations=1)
    candidate_pixels = max(int(np.count_nonzero(candidate_binary)), 1)
    stage_pixels = max(int(np.count_nonzero(stage_binary)), 1)
    new_stroke_risk = float(np.count_nonzero((candidate_binary > 0) & (dilated_stage == 0)) / candidate_pixels)
    missing_stroke_risk = float(np.count_nonzero((stage_binary > 0) & (dilated_candidate == 0)) / stage_pixels)
    edge_alignment = float(np.clip(structure / 100.0, 0.0, 1.0))
    abs_diff = cv2.absdiff(stage_input_roi, candidate_roi)
    masked_values = abs_diff[text_mask > 0]
    mean_diff = float(np.mean(masked_values)) if masked_values.size else 255.0
    structure_similarity = float(np.clip(1.0 - mean_diff / 255.0, 0.0, 1.0))
    artifact = edge_artifact_quality(stage_input_roi, candidate_roi, 100.0)
    intrusion = _small_text_background_intrusion(stage_input_roi, candidate_roi, text_mask)
    sufficient_evidence = bool(np.count_nonzero(text_mask) >= 24 and stage_width is not None and candidate_width is not None and stage_components >= 1)
    auto_fail = bool(
        sufficient_evidence
        and (
            abs(stroke_delta or 0.0) > 0.28
            or connectivity_delta > 0.35
            or counter_preservation < 0.70
            or edge_alignment < 0.90
            or new_stroke_risk > 0.08
            or missing_stroke_risk > 0.08
            or artifact.get("halo_ringing_pass") is not True
            or intrusion > 0.035
        )
    )
    auto_pass = bool(
        sufficient_evidence
        and not auto_fail
        and abs(stroke_delta or 0.0) <= 0.18
        and connectivity_delta <= 0.12
        and counter_preservation >= 0.90
        and edge_alignment >= 0.96
        and structure_similarity >= 0.95
        and new_stroke_risk <= 0.04
        and missing_stroke_risk <= 0.04
    )
    structure_status = "auto_confirmed_fail" if auto_fail else "auto_confirmed_pass" if auto_pass else "requires_human_review"
    protection_pass: bool | str = False if auto_fail else True if auto_pass else "requires_human_review"
    return {
        "structure_status": structure_status,
        "small_text_character_structure_protection_pass": protection_pass,
        "small_text_character_structure_evidence": "automatic_metric_contract_v1" if sufficient_evidence else "requires_human_review",
        "character_component_count_stage_input": stage_components,
        "character_component_count_candidate": candidate_components,
        "character_component_count_delta": component_delta,
        "small_text_stroke_width_original": round(stage_width, 4) if stage_width is not None else "not_applicable",
        "small_text_stroke_width_candidate": round(candidate_width, 4) if candidate_width is not None else "not_applicable",
        "small_text_stroke_width_delta": round(stroke_delta, 4) if stroke_delta is not None else "not_applicable",
        "stroke_connectivity_delta": round(connectivity_delta, 6),
        "internal_counter_preservation": round(float(np.clip(counter_preservation, 0.0, 1.0)), 6),
        "edge_alignment_similarity": round(edge_alignment, 6),
        "structure_similarity_to_stage_input": round(structure_similarity, 6),
        "new_stroke_risk": round(new_stroke_risk, 6),
        "missing_stroke_risk": round(missing_stroke_risk, 6),
        "small_text_stroke_structure_consistency": round(structure, 2),
        "small_text_edge_overshoot": artifact.get("edge_overshoot_ratio", "not_applicable"),
        "small_text_halo_ringing_pass": artifact.get("halo_ringing_pass", "not_applicable"),
        "small_text_background_intrusion_ratio": round(intrusion, 4),
        "small_text_background_intrusion_pass": bool(intrusion <= 0.035),
        "small_text_observed_structure_distortion": auto_fail,
    }


def _blend_normalized_roi(
    target: np.ndarray,
    candidate_roi: np.ndarray,
    box: tuple[float, float, float, float],
    structure_mask: np.ndarray | None = None,
) -> None:
    x1, y1, x2, y2 = _normalized_box_pixel_bounds(target, box)
    height = y2 - y1; width = x2 - x1
    if candidate_roi.shape[:2] != (height, width):
        candidate_roi = cv2.resize(candidate_roi, (width, height), interpolation=cv2.INTER_AREA)
    existing = target[y1:y2, x1:x2].astype(np.float32)
    inset = max(2, min(6, min(height, width) // 10))
    mask = np.zeros((height, width), dtype=np.uint8)
    if height > inset * 2 and width > inset * 2:
        mask[inset:height - inset, inset:width - inset] = 255
    else:
        mask[:, :] = 255
    alpha = cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), max(0.8, inset * 0.55))
    if structure_mask is not None:
        if structure_mask.shape != (height, width):
            structure_mask = cv2.resize(structure_mask, (width, height), interpolation=cv2.INTER_NEAREST)
        structure_alpha = cv2.GaussianBlur((structure_mask > 0).astype(np.float32), (0, 0), 0.72)
        alpha *= np.clip(structure_alpha, 0.0, 1.0)
    alpha = alpha[:, :, None]
    target[y1:y2, x1:x2] = np.clip(existing * (1.0 - alpha) + candidate_roi.astype(np.float32) * alpha, 0, 255).astype(np.uint8)


def _safe_rollback_text_structure(
    target: np.ndarray,
    original_roi: np.ndarray,
    reference_roi: np.ndarray,
    box: tuple[float, float, float, float],
    structure_mask: np.ndarray,
) -> dict[str, object]:
    """Restore original text strokes without accepting an unverified rectangle seam."""
    x1, y1, x2, y2 = _normalized_box_pixel_bounds(target, box)
    height = y2 - y1; width = x2 - x1
    if reference_roi.shape[:2] != (height, width):
        reference_roi = cv2.resize(reference_roi, (width, height), interpolation=cv2.INTER_AREA)
    target[y1:y2, x1:x2] = reference_roi
    _blend_normalized_roi(target, original_roi, box, structure_mask)
    rolled_back = target[y1:y2, x1:x2].copy()
    boundary_delta = _small_text_roi_boundary_delta(reference_roi, rolled_back)
    boundary_pass = bool(boundary_delta <= 1.5)
    if not boundary_pass:
        target[y1:y2, x1:x2] = reference_roi
    return {
        "small_text_rollback_applied": bool(boundary_pass and not np.array_equal(rolled_back, reference_roi)),
        "small_text_rollback_boundary_delta": round(boundary_delta, 4),
        "small_text_rollback_boundary_pass": boundary_pass,
        "small_text_rollback_mode": "masked_original_strokes_feathered" if boundary_pass else "retain_pre_stage_beta",
    }


def _small_text_roi_boundary_delta(before_roi: np.ndarray, after_roi: np.ndarray) -> float:
    height, width = before_roi.shape[:2]
    band = max(1, min(3, min(height, width) // 8))
    boundary = np.zeros((height, width), dtype=bool)
    boundary[:band, :] = True; boundary[-band:, :] = True; boundary[:, :band] = True; boundary[:, -band:] = True
    return float(np.mean(np.abs(after_roi.astype(np.float32) - before_roi.astype(np.float32))[boundary]))


def _small_text_boundary_audit(stage_input_roi: np.ndarray, output_roi: np.ndarray) -> dict[str, object]:
    if stage_input_roi.size == 0 or output_roi.size == 0:
        return {
            "boundary_measurement_performed": False,
            "boundary_ring_delta": "not_evaluated",
            "boundary_gradient_jump": "not_evaluated",
            "boundary_color_delta": "not_evaluated",
            "boundary_noise_delta": "not_evaluated",
            "boundary_seam_pass": "not_evaluated",
        }
    if output_roi.shape != stage_input_roi.shape:
        output_roi = cv2.resize(output_roi, (stage_input_roi.shape[1], stage_input_roi.shape[0]), interpolation=cv2.INTER_AREA)
    height, width = stage_input_roi.shape[:2]
    band = max(1, min(3, min(height, width) // 8))
    ring = np.zeros((height, width), dtype=bool)
    ring[:band, :] = True; ring[-band:, :] = True; ring[:, :band] = True; ring[:, -band:] = True
    before_float = stage_input_roi.astype(np.float32)
    after_float = output_roi.astype(np.float32)
    absolute = np.abs(after_float - before_float)
    ring_delta = float(np.mean(absolute[ring]))
    color_delta = float(np.mean(np.abs(np.mean(after_float[ring], axis=0) - np.mean(before_float[ring], axis=0))))
    before_gray = cv2.cvtColor(stage_input_roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
    after_gray = cv2.cvtColor(output_roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
    before_gradient = cv2.magnitude(cv2.Sobel(before_gray, cv2.CV_32F, 1, 0), cv2.Sobel(before_gray, cv2.CV_32F, 0, 1))
    after_gradient = cv2.magnitude(cv2.Sobel(after_gray, cv2.CV_32F, 1, 0), cv2.Sobel(after_gray, cv2.CV_32F, 0, 1))
    gradient_jump = float(abs(np.mean(after_gradient[ring]) - np.mean(before_gradient[ring])))
    before_noise = before_gray - cv2.GaussianBlur(before_gray, (0, 0), 1.0)
    after_noise = after_gray - cv2.GaussianBlur(after_gray, (0, 0), 1.0)
    noise_delta = float(abs(np.std(after_noise[ring]) - np.std(before_noise[ring])))
    seam_pass = bool(ring_delta <= 1.5 and color_delta <= 1.5 and gradient_jump <= 4.0 and noise_delta <= 3.0)
    return {
        "boundary_measurement_performed": True,
        "boundary_ring_delta": round(ring_delta, 6),
        "boundary_gradient_jump": round(gradient_jump, 6),
        "boundary_color_delta": round(color_delta, 6),
        "boundary_noise_delta": round(noise_delta, 6),
        "boundary_seam_pass": seam_pass,
    }


def _small_text_cross_boundary_audit(
    stage_input_canvas: np.ndarray,
    output_canvas: np.ndarray,
    bbox_stage: tuple[int, int, int, int] | list[int],
    inner_width: int = 3,
    outer_width: int = 3,
) -> dict[str, object]:
    if stage_input_canvas.shape != output_canvas.shape or stage_input_canvas.size == 0:
        return {
            "boundary_measurement_performed": False,
            "boundary_measurable_side_count": 0,
            "boundary_inner_delta": "not_evaluated",
            "boundary_outer_delta": "not_evaluated",
            "cross_boundary_gradient_before": "not_evaluated",
            "cross_boundary_gradient_after": "not_evaluated",
            "cross_boundary_gradient_jump": "not_evaluated",
            "cross_boundary_color_delta": "not_evaluated",
            "cross_boundary_luminance_delta": "not_evaluated",
            "cross_boundary_noise_delta": "not_evaluated",
            "boundary_seam_pass": "not_evaluated",
            "boundary_sides": {},
        }
    height, width = stage_input_canvas.shape[:2]
    try:
        x1, y1, x2, y2 = (int(value) for value in bbox_stage)
    except (TypeError, ValueError):
        return _small_text_cross_boundary_audit(np.empty((0, 0, 3), np.uint8), np.empty((0, 0, 3), np.uint8), [0, 0, 0, 0])
    x1 = max(0, min(width, x1)); x2 = max(0, min(width, x2))
    y1 = max(0, min(height, y1)); y2 = max(0, min(height, y2))
    inner_width = max(1, int(inner_width)); outer_width = max(1, int(outer_width))
    definitions = {
        "left": ((x1, y1, min(x2, x1 + inner_width), y2), (max(0, x1 - outer_width), y1, x1, y2), x1 > 0),
        "right": ((max(x1, x2 - inner_width), y1, x2, y2), (x2, y1, min(width, x2 + outer_width), y2), x2 < width),
        "top": ((x1, y1, x2, min(y2, y1 + inner_width)), (x1, max(0, y1 - outer_width), x2, y1), y1 > 0),
        "bottom": ((x1, max(y1, y2 - inner_width), x2, y2), (x1, y2, x2, min(height, y2 + outer_width)), y2 < height),
    }
    before_gray = cv2.cvtColor(stage_input_canvas, cv2.COLOR_BGR2GRAY).astype(np.float32)
    after_gray = cv2.cvtColor(output_canvas, cv2.COLOR_BGR2GRAY).astype(np.float32)
    side_results: dict[str, dict[str, object]] = {}
    measured_rows: list[dict[str, float]] = []
    for side, (inner_box, outer_box, geometrically_measurable) in definitions.items():
        ix1, iy1, ix2, iy2 = inner_box; ox1, oy1, ox2, oy2 = outer_box
        measurable = bool(
            geometrically_measurable
            and ix2 > ix1 and iy2 > iy1
            and ox2 > ox1 and oy2 > oy1
        )
        if not measurable:
            side_results[side] = {"measured": False, "reason": "canvas_edge_or_empty_ring"}
            continue
        before_inner = stage_input_canvas[iy1:iy2, ix1:ix2].astype(np.float32)
        before_outer = stage_input_canvas[oy1:oy2, ox1:ox2].astype(np.float32)
        after_inner = output_canvas[iy1:iy2, ix1:ix2].astype(np.float32)
        after_outer = output_canvas[oy1:oy2, ox1:ox2].astype(np.float32)
        before_inner_gray = before_gray[iy1:iy2, ix1:ix2]
        before_outer_gray = before_gray[oy1:oy2, ox1:ox2]
        after_inner_gray = after_gray[iy1:iy2, ix1:ix2]
        after_outer_gray = after_gray[oy1:oy2, ox1:ox2]
        inner_delta = float(np.mean(np.abs(after_inner - before_inner)))
        outer_delta = float(np.mean(np.abs(after_outer - before_outer)))
        gradient_before = float(abs(np.mean(before_inner_gray) - np.mean(before_outer_gray)))
        gradient_after = float(abs(np.mean(after_inner_gray) - np.mean(after_outer_gray)))
        gradient_jump = float(abs(gradient_after - gradient_before))
        color_before = np.mean(before_inner, axis=(0, 1)) - np.mean(before_outer, axis=(0, 1))
        color_after = np.mean(after_inner, axis=(0, 1)) - np.mean(after_outer, axis=(0, 1))
        color_delta = float(np.mean(np.abs(color_after - color_before)))
        luminance_delta = gradient_jump
        before_inner_noise = before_inner_gray - cv2.GaussianBlur(before_inner_gray, (0, 0), 1.0)
        before_outer_noise = before_outer_gray - cv2.GaussianBlur(before_outer_gray, (0, 0), 1.0)
        after_inner_noise = after_inner_gray - cv2.GaussianBlur(after_inner_gray, (0, 0), 1.0)
        after_outer_noise = after_outer_gray - cv2.GaussianBlur(after_outer_gray, (0, 0), 1.0)
        noise_before = float(abs(np.std(before_inner_noise) - np.std(before_outer_noise)))
        noise_after = float(abs(np.std(after_inner_noise) - np.std(after_outer_noise)))
        noise_delta = float(abs(noise_after - noise_before))
        row = {
            "boundary_inner_delta": inner_delta,
            "boundary_outer_delta": outer_delta,
            "cross_boundary_gradient_before": gradient_before,
            "cross_boundary_gradient_after": gradient_after,
            "cross_boundary_gradient_jump": gradient_jump,
            "cross_boundary_color_delta": color_delta,
            "cross_boundary_luminance_delta": luminance_delta,
            "cross_boundary_noise_delta": noise_delta,
        }
        measured_rows.append(row)
        side_results[side] = {"measured": True, **{key: round(value, 6) for key, value in row.items()}}
    measured_count = len(measured_rows)
    if not measured_rows:
        return {
            "boundary_measurement_performed": False,
            "boundary_measurable_side_count": 0,
            "boundary_inner_delta": "not_evaluated",
            "boundary_outer_delta": "not_evaluated",
            "cross_boundary_gradient_before": "not_evaluated",
            "cross_boundary_gradient_after": "not_evaluated",
            "cross_boundary_gradient_jump": "not_evaluated",
            "cross_boundary_color_delta": "not_evaluated",
            "cross_boundary_luminance_delta": "not_evaluated",
            "cross_boundary_noise_delta": "not_evaluated",
            "boundary_seam_pass": "not_evaluated",
            "boundary_sides": side_results,
        }
    aggregate = {key: max(row[key] for row in measured_rows) for key in measured_rows[0]}
    seam_safe = bool(
        aggregate["boundary_inner_delta"] <= 1.5
        and aggregate["boundary_outer_delta"] <= 1.5
        and aggregate["cross_boundary_gradient_jump"] <= 4.0
        and aggregate["cross_boundary_color_delta"] <= 1.5
        and aggregate["cross_boundary_luminance_delta"] <= 4.0
        and aggregate["cross_boundary_noise_delta"] <= 3.0
    )
    seam_status: bool | str = seam_safe if measured_count >= 2 else "requires_review"
    return {
        "boundary_measurement_performed": True,
        "boundary_measurable_side_count": measured_count,
        **{key: round(value, 6) for key, value in aggregate.items()},
        "boundary_seam_pass": seam_status,
        "boundary_sides": side_results,
    }


def resolve_small_text_structure_review(
    automatic_fields: dict[str, object],
    candidate: dict[str, object],
    review: dict[str, object] | None,
) -> dict[str, object]:
    if not review:
        return {
            **automatic_fields,
            "human_review_validation_status": "not_provided",
            "human_review_validation_reason": "automatic_structure_result_used",
        }
    required = {"review_id", "source_image_id", "detection_id", "bbox", "reviewer_type", "reviewed_at", "decision", "evidence_path", "notes", "code_signature", "input_signature"}
    missing = sorted(key for key in required if review.get(key) in (None, ""))
    expected_bbox_raw = candidate.get("bbox_stage")
    if not isinstance(expected_bbox_raw, (list, tuple)) or len(expected_bbox_raw) != 4:
        expected_bbox_raw = candidate.get("bbox_source")
    if not isinstance(expected_bbox_raw, (list, tuple)) or len(expected_bbox_raw) != 4:
        expected_bbox_raw = candidate.get("roi_box_normalized") or []
    expected_bbox = [round(float(value), 6) for value in expected_bbox_raw]
    try:
        review_bbox = [round(float(value), 6) for value in review.get("bbox") or []]
    except (TypeError, ValueError):
        review_bbox = []
    try:
        reviewed_at = datetime.fromisoformat(str(review.get("reviewed_at") or "").replace("Z", "+00:00"))
        now = datetime.now(reviewed_at.tzinfo) if reviewed_at.tzinfo else datetime.now()
        review_age_seconds = (now - reviewed_at).total_seconds()
        review_timestamp_valid = -300.0 <= review_age_seconds <= 30.0 * 24.0 * 3600.0
    except (TypeError, ValueError):
        review_timestamp_valid = False
    checks = {
        "required_fields_complete": not missing,
        "decision_valid": review.get("decision") in {"pass", "fail"},
        "reviewer_type_valid": review.get("reviewer_type") == "human",
        "source_image_id_match": review.get("source_image_id") == candidate.get("source_image_id"),
        "detection_id_match": review.get("detection_id") == candidate.get("detection_id"),
        "bbox_match": review_bbox == expected_bbox,
        "input_signature_match": review.get("input_signature") == candidate.get("input_signature"),
        "code_signature_match": review.get("code_signature") == candidate.get("code_signature"),
        "evidence_path_exists": Path(str(review.get("evidence_path") or "")).is_file(),
        "review_timestamp_valid": review_timestamp_valid,
    }
    valid = all(checks.values())
    if valid:
        decision = str(review["decision"])
        status = "human_confirmed_pass" if decision == "pass" else "human_confirmed_fail"
        protection_pass: bool | str = decision == "pass"
        reason = "traceable_review_contract_valid"
    else:
        status = str(automatic_fields.get("structure_status") or "requires_human_review")
        protection_pass = automatic_fields.get("small_text_character_structure_protection_pass", "requires_human_review")
        reason = "invalid_review_contract:" + ",".join(key for key, value in checks.items() if not value)
        if missing:
            reason += ";missing=" + ",".join(missing)
    return {
        **automatic_fields,
        "structure_status": status,
        "small_text_character_structure_protection_pass": protection_pass,
        "human_review_validation_status": "accepted" if valid else "rejected",
        "human_review_validation_reason": reason,
        "human_review_id": review.get("review_id") if valid else "not_applicable",
        "human_review_decision": review.get("decision") if valid else "not_applicable",
        "human_review_checks": checks,
    }


def _small_text_background_intrusion(original_roi: np.ndarray, candidate_roi: np.ndarray, text_mask: np.ndarray) -> float:
    region = cv2.dilate((text_mask > 0).astype(np.uint8), np.ones((5, 5), np.uint8), iterations=1) == 0
    if int(np.sum(region)) < 32:
        return 0.0
    before_edges = cv2.Canny(cv2.cvtColor(original_roi, cv2.COLOR_BGR2GRAY), 45, 135) > 0
    after_edges = cv2.Canny(cv2.cvtColor(candidate_roi, cv2.COLOR_BGR2GRAY), 45, 135) > 0
    return float(max(0.0, np.mean(after_edges[region]) - np.mean(before_edges[region])))


def _small_text_visuals(
    original: np.ndarray,
    before_beta: np.ndarray,
    final_image: np.ndarray,
    details: list[dict[str, object]],
) -> tuple[np.ndarray | None, np.ndarray | None]:
    if not details:
        return None, None
    overview = before_beta.copy()
    comparison_rows: list[np.ndarray] = []
    for item in details:
        box = _validated_normalized_box(item.get("roi_box_normalized"))
        if box is None:
            continue
        x1 = int(round(box[0] * overview.shape[1])); y1 = int(round(box[1] * overview.shape[0]))
        x2 = int(round(box[2] * overview.shape[1])); y2 = int(round(box[3] * overview.shape[0]))
        color = (20, 180, 20) if item.get("recoverability_status") == "recoverable" else (0, 150, 240)
        cv2.rectangle(overview, (x1, y1), (x2, y2), color, 2)
        cv2.putText(overview, f"{item.get('roi_id')} {item.get('text_role')} {item.get('recoverability_status')}", (x1, max(14, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)
        crops = [_normalized_roi_crop(source, box) for source in (original, before_beta, final_image)]
        display_scale = min(4.0, 480.0 / max(crops[0].shape[1], 1), 320.0 / max(crops[0].shape[0], 1))
        display_width = max(1, int(round(crops[0].shape[1] * display_scale)))
        display_height = max(1, int(round(crops[0].shape[0] * display_scale)))
        item["visualization_scale"] = round(display_scale, 4)
        panels = []
        labels = (
            f"original ROI {display_scale:.2f}x",
            f"before beta ROI {display_scale:.2f}x",
            f"after beta ROI {display_scale:.2f}x",
        )
        for crop, label in zip(crops, labels):
            resized = cv2.resize(crop, (display_width, display_height), interpolation=cv2.INTER_NEAREST)
            panels.append(labeled_panel(resized, label, display_height))
        comparison_rows.append(np.hstack(panels))
    if not comparison_rows:
        return overview, None
    row_width = max(row.shape[1] for row in comparison_rows)
    padded = [cv2.copyMakeBorder(row, 0, 0, 0, row_width - row.shape[1], cv2.BORDER_CONSTANT, value=(245, 245, 245)) for row in comparison_rows]
    return overview, np.vstack(padded)


def _replace_normalized_roi(target: np.ndarray, source: np.ndarray, box: tuple[float, float, float, float]) -> None:
    x1, y1, x2, y2 = _normalized_box_pixel_bounds(target, box)
    sx1, sy1, sx2, sy2 = _normalized_box_pixel_bounds(source, box)
    source_roi = source[sy1:sy2, sx1:sx2]
    target_height = y2 - y1; target_width = x2 - x1
    if source_roi.shape[:2] != (target_height, target_width):
        source_roi = cv2.resize(source_roi, (target_width, target_height), interpolation=cv2.INTER_AREA)
    target[y1:y2, x1:x2] = source_roi


def _legacy_small_text_roi_safe_enhance_unused(
    original: np.ndarray,
    beta_image: np.ndarray,
    content_type: str,
    manual_rois: dict[str, object] | None = None,
    face_analysis: dict[str, object] | None = None,
) -> tuple[np.ndarray, dict[str, object], tuple[np.ndarray | None, np.ndarray | None]]:
    original_target = resize_to_match(original, beta_image)
    before_beta = beta_image.copy()
    output = beta_image.copy()
    reliable_text_mask, reliable_text_fields = build_primary_delivery_text_mask(original_target)
    reliable_text = bool(np.any(reliable_text_mask) and float(reliable_text_fields.get("primary_text_roi_confidence") or 0.0) >= 0.25)
    person_mask = _portrait_region_masks(original_target, face_analysis or {})["person"] if face_analysis else np.zeros(original_target.shape[:2], dtype=np.uint8)
    if content_type not in SMALL_TEXT_CONTENT_TYPES:
        return output, {
            "small_text_stage": "not_applicable",
            "small_text_stage_status": "not_applicable",
            "small_text_stage_reason": "content_type_not_applicable",
            "small_text_detected_count": 0,
            "small_text_valid_count": 0,
            "small_text_recoverable_count": 0,
            "small_text_limited_count": 0,
            "small_text_unrecoverable_count": 0,
            "small_text_enhanced_count": 0,
            "small_text_reverted_count": 0,
            "small_text_manual_review_count": 0,
            "small_text_roi_score": "not_applicable",
            "small_text_roi_gain": "not_applicable",
            "small_text_roi_applicable": False,
            "small_text_character_structure_protection_pass": "not_applicable",
            "small_text_stroke_width_delta": "not_applicable",
            "small_text_edge_overshoot": "not_applicable",
            "small_text_halo_ringing_pass": "not_applicable",
            "small_text_background_intrusion_pass": "not_applicable",
            "small_text_glyph_review": "not_applicable",
            "small_text_enhancement_applied": False,
            "small_text_quality_status": "not_applicable",
            "small_text_delivery_status": "review_before_use",
            "small_text_roi_details": [],
            "small_text_uses_generative_fill": False,
            "small_text_ocr_redraw_used": False,
        }, (None, None)
    candidates = detect_small_text_rois(original_target, content_type, manual_rois)
    automatic_detection = manual_rois is None
    if not reliable_text:
        for candidate in candidates:
            if candidate.get("recoverability_status") != "not_applicable":
                candidate["recoverability_status"] = "limited_recoverable"
                candidate["recoverability_reason"] = "global_text_roi_not_reliable_enhancement_disabled"
    details: list[dict[str, object]] = []
    for candidate in candidates:
        item = dict(candidate)
        box = _validated_normalized_box(item.get("roi_box_normalized"))
        recoverability = str(item.get("recoverability_status") or "not_applicable")
        if box is None:
            item.update({
                "original_score": "not_applicable", "enhanced_score": "not_applicable", "score_gain": "not_applicable",
                "small_text_enhancement_applied": False, "legacy_reverted_to_original_unused": False,
                "revert_reason": "invalid_roi", "small_text_glyph_review": "not_applicable",
            })
            details.append(item)
            continue
        original_roi = _normalized_roi_crop(original_target, box)
        before_roi = _normalized_roi_crop(before_beta, box)
        person_roi = _normalized_roi_crop(person_mask, box)
        person_overlap_ratio = float(np.mean(person_roi > 0)) if person_roi.size else 0.0
        base_text_mask, mask_fields = build_primary_delivery_text_mask(original_roi)
        text_mask, structure_mask_fields = _small_text_structure_mask(original_roi, base_text_mask)
        container_edge_mask = _container_edge_exclusion_mask(original_roi)
        original_measurement = _text_roi_absolute_measurement(original_roi, text_mask)
        before_measurement = _text_roi_absolute_measurement(before_roi, text_mask)
        original_score = metric_number(original_measurement.get("score"))
        before_score = metric_number(before_measurement.get("score"))
        item.update({
            "original_score": round(original_score, 2) if original_score is not None else "not_applicable",
            "before_beta_score": round(before_score, 2) if before_score is not None else "not_applicable",
            "scoring_method": "same_mask_absolute_text_roi_measurement",
            "scoring_version": "rc8a_v2",
            "evaluation_size": [original_roi.shape[1], original_roi.shape[0]],
            "person_overlap_ratio": round(person_overlap_ratio, 4),
            **mask_fields,
            **structure_mask_fields,
        })
        role = str(item.get("text_role") or "unknown_text")
        supported_text_roles = {"small_text", "secondary_text", "name_text", "label_text", "description_text", "parameter_text"}
        non_text_roles = {"decorative_line", "decorative_microtext", "icon_candidate", "icon", "background_texture", "highlight_or_particle", "container_edge"}
        can_attempt = (
            reliable_text
            and
            recoverability in {"recoverable", "limited_recoverable"}
            and role in supported_text_roles
            and original_score is not None and before_score is not None
            and person_overlap_ratio <= 0.05
            and structure_mask_fields["small_text_structure_mask_status"] == "available"
        )
        if not can_attempt:
            rollback_fields = {
                "small_text_rollback_applied": False,
                "small_text_rollback_boundary_delta": "not_applicable",
                "small_text_rollback_boundary_pass": "not_applicable",
                "small_text_rollback_mode": "not_applicable",
            }
            if person_overlap_ratio > 0.05:
                reverted = False
                reason = "person_roi_excluded_from_small_text_stage"
            elif role in non_text_roles:
                reverted = False
                reason = "non_text_structure_filtered"
            elif role == "logo_text":
                rollback_fields = _safe_rollback_text_structure(output, original_roi, before_roi, box, text_mask)
                reverted = rollback_fields["small_text_rollback_boundary_pass"] is True
                reason = "logo_strict_protection"
            elif role in {"primary_text", "unknown_text"}:
                reverted = False
                reason = "primary_text_uses_primary_text_stage" if role == "primary_text" else "unknown_text_role_protected"
            elif recoverability in {"unrecoverable", "limited_recoverable"}:
                rollback_fields = _safe_rollback_text_structure(output, original_roi, before_roi, box, text_mask)
                reverted = rollback_fields["small_text_rollback_boundary_pass"] is True
                reason = (
                    "unrecoverable_original_strokes" if recoverability == "unrecoverable"
                    else "global_text_roi_not_reliable_enhancement_disabled" if not reliable_text
                    else "limited_roi_metric_not_reliable_for_safe_enhance"
                )
            else:
                reverted = False
                reason = "metric_not_applicable"
            item.update({
                "enhanced_score": "not_applicable" if recoverability == "unrecoverable" else round(original_score, 2) if reverted and original_score is not None else "not_applicable",
                "score_gain": "not_applicable" if recoverability == "unrecoverable" else 0.0 if reverted and original_score is not None else "not_applicable",
                "small_text_roi_score_original": "not_applicable" if recoverability == "unrecoverable" else round(original_score, 2) if original_score is not None else "not_applicable",
                "small_text_roi_score_enhanced": "not_applicable" if recoverability == "unrecoverable" else round(original_score, 2) if reverted and original_score is not None else "not_applicable",
                "small_text_roi_gain": "not_applicable" if recoverability == "unrecoverable" else 0.0 if reverted and original_score is not None else "not_applicable",
                "small_text_glyph_review": "requires_human_review" if recoverability != "not_applicable" else "not_applicable",
                "small_text_roi_applicable": bool(role in supported_text_roles and person_overlap_ratio <= 0.05 and recoverability != "not_applicable"),
                "small_text_character_structure_protection_pass": "not_applicable" if role in non_text_roles or person_overlap_ratio > 0.05 else "requires_human_review",
                "small_text_stroke_width_delta": "not_applicable",
                "small_text_edge_overshoot": "not_applicable",
                "small_text_halo_ringing_pass": "not_applicable",
                "small_text_background_intrusion_pass": "not_applicable",
                "small_text_enhancement_applied": False,
                "legacy_reverted_to_original_unused": reverted,
                "small_text_roi_outcome": "not_applicable" if role in non_text_roles or person_overlap_ratio > 0.05 or recoverability == "not_applicable" else "safe_rollback",
                "revert_reason": reason,
                "small_text_halo_risk": "not_applicable",
                "small_text_background_intrusion_risk": "not_applicable",
                "small_text_roi_boundary_delta": rollback_fields["small_text_rollback_boundary_delta"],
                "small_text_roi_boundary_pass": rollback_fields["small_text_rollback_boundary_pass"],
                **rollback_fields,
            })
            details.append(item)
            continue
        pre_attempt_roi = _normalized_roi_crop(output, box).copy()
        enhanced_roi = _small_text_luma_candidate(before_roi)
        enhanced_measurement = _text_roi_absolute_measurement(enhanced_roi, text_mask)
        enhanced_score = metric_number(enhanced_measurement.get("score"))
        candidate_structure = _small_text_structure_metrics(original_roi, enhanced_roi, text_mask)
        stage_gain = None if enhanced_score is None else enhanced_score - before_score
        before_detail = metric_number(before_measurement.get("detail_energy"))
        candidate_detail = metric_number(enhanced_measurement.get("detail_energy"))
        candidate_detail_gain = (
            (candidate_detail - before_detail) / max(before_detail, 1.0) * 100.0
            if before_detail is not None and candidate_detail is not None else None
        )
        unsafe_reasons = []
        if candidate_structure["small_text_observed_structure_distortion"]:
            unsafe_reasons.append("candidate_structure_distortion")
        candidate_positive_gain = bool(
            (stage_gain is not None and stage_gain >= 0.20)
            or (candidate_detail_gain is not None and candidate_detail_gain >= 2.0)
        )
        if not candidate_positive_gain: unsafe_reasons.append("no_real_stage_gain")
        applied = not unsafe_reasons
        final_structure = candidate_structure
        boundary_delta: float | str = "not_applicable"
        container_delta: float | None = None
        if applied:
            _blend_normalized_roi(output, enhanced_roi, box, text_mask)
            blended_roi = _normalized_roi_crop(output, box)
            boundary_delta = _small_text_roi_boundary_delta(before_roi, blended_roi)
            final_structure = _small_text_structure_metrics(original_roi, blended_roi, text_mask)
            final_measurement = _text_roi_absolute_measurement(blended_roi, text_mask)
            final_score = metric_number(final_measurement.get("score"))
            final_stage_gain = None if final_score is None else final_score - before_score
            final_original_gain = None if final_score is None else final_score - original_score
            final_detail = metric_number(final_measurement.get("detail_energy"))
            final_detail_gain = (
                (final_detail - before_detail) / max(before_detail, 1.0) * 100.0
                if before_detail is not None and final_detail is not None else None
            )
            if boundary_delta > 1.5:
                unsafe_reasons.append(f"roi_boundary_delta={boundary_delta:.3f}>1.5")
            if final_structure["small_text_observed_structure_distortion"]:
                unsafe_reasons.append("final_structure_distortion")
            final_positive_gain = bool(
                (final_stage_gain is not None and final_stage_gain >= 0.10)
                or (final_detail_gain is not None and final_detail_gain >= 1.0)
            )
            if not final_positive_gain:
                unsafe_reasons.append("blended_gain_not_visible")
            if final_original_gain is None or final_original_gain < -0.05:
                unsafe_reasons.append("final_below_original_score")
            if np.count_nonzero(container_edge_mask) >= 12:
                container_before = before_roi[container_edge_mask > 0]
                container_after = blended_roi[container_edge_mask > 0]
                container_delta = float(np.mean(np.abs(container_after.astype(np.float32) - container_before.astype(np.float32))))
                if container_delta > 1.2:
                    unsafe_reasons.append(f"container_edge_delta={container_delta:.3f}>1.2")
            else:
                container_delta = 0.0
            applied = not unsafe_reasons
        if not applied:
            rollback_fields = _safe_rollback_text_structure(output, original_roi, pre_attempt_roi, box, text_mask)
            boundary_delta = rollback_fields["small_text_rollback_boundary_delta"]
            if rollback_fields["small_text_rollback_boundary_pass"] is not True:
                unsafe_reasons.append("rollback_boundary_unverified")
            final_roi = _normalized_roi_crop(output, box)
            final_measurement = _text_roi_absolute_measurement(final_roi, text_mask)
            final_score = metric_number(final_measurement.get("score"))
            final_gain = final_score - original_score if final_score is not None else 0.0
            final_structure = _small_text_structure_metrics(original_roi, final_roi, text_mask)
        else:
            rollback_fields = {
                "small_text_rollback_applied": False,
                "small_text_rollback_boundary_delta": "not_applicable",
                "small_text_rollback_boundary_pass": "not_applicable",
                "small_text_rollback_mode": "not_applicable",
            }
            final_gain = final_score - original_score if final_score is not None else 0.0
        item.update({
            "enhanced_score": round(final_score, 2),
            "score_gain": round(final_gain, 2),
            "small_text_roi_score_original": round(original_score, 2),
            "small_text_roi_score_enhanced": round(final_score, 2),
            "small_text_roi_gain": round(final_gain, 2),
            "small_text_candidate_score": round(enhanced_score, 2) if enhanced_score is not None else "not_applicable",
            "small_text_stage_gain": round(stage_gain, 2) if stage_gain is not None else "not_applicable",
            "small_text_candidate_detail_gain_percent": round(candidate_detail_gain, 2) if candidate_detail_gain is not None else "not_applicable",
            "small_text_final_detail_gain_percent": round(final_detail_gain, 2) if applied and final_detail_gain is not None else 0.0,
            "small_text_visible_gain_evidence": "score_or_unclipped_detail_gain" if applied else "safe_rollback",
            "small_text_edge_integrity": final_structure["small_text_stroke_structure_consistency"],
            "small_text_stroke_consistency": final_structure["small_text_stroke_structure_consistency"],
            "small_text_local_contrast_gain": round(float(enhanced_measurement["local_contrast"]) - float(before_measurement["local_contrast"]), 3),
            "small_text_halo_risk": final_structure["small_text_halo_ringing_pass"] is not True,
            "small_text_background_intrusion_risk": final_structure["small_text_background_intrusion_pass"] is False,
            "small_text_roi_boundary_delta": round(boundary_delta, 4) if isinstance(boundary_delta, float) else boundary_delta,
            "small_text_roi_boundary_pass": bool(isinstance(boundary_delta, (float, int)) and boundary_delta <= 1.5),
            "small_text_container_edge_delta": round(container_delta, 4) if container_delta is not None else "not_applicable",
            "small_text_container_edge_protection_pass": bool(container_delta <= 1.2) if container_delta is not None else "not_applicable",
            "small_text_roi_applicable": True,
            "small_text_glyph_review": "requires_human_review",
            "small_text_enhancement_applied": applied,
            "legacy_reverted_to_original_unused": bool(not applied and rollback_fields["small_text_rollback_boundary_pass"] is True),
            "small_text_roi_outcome": "enhanced" if applied else "safe_rollback",
            "revert_reason": "none" if applied else ";".join(unsafe_reasons),
            "halo_ringing_pass": final_structure["small_text_halo_ringing_pass"],
            **rollback_fields,
            **final_structure,
        })
        details.append(item)
    for item in details:
        box = _validated_normalized_box(item.get("roi_box_normalized"))
        if box is None or item.get("recoverability_status") in {"unrecoverable", "not_applicable"}:
            continue
        original_roi = _normalized_roi_crop(original_target, box)
        final_roi = _normalized_roi_crop(output, box)
        base_text_mask, _ = build_primary_delivery_text_mask(original_roi)
        text_mask, _ = _small_text_structure_mask(original_roi, base_text_mask)
        original_measurement = _text_roi_absolute_measurement(original_roi, text_mask)
        final_measurement = _text_roi_absolute_measurement(final_roi, text_mask)
        original_value = metric_number(original_measurement.get("score"))
        final_value = metric_number(final_measurement.get("score"))
        item["enhanced_score"] = round(final_value, 2) if final_value is not None else "not_applicable"
        item["score_gain"] = round(final_value - original_value, 2) if final_value is not None and original_value is not None else "not_applicable"
        item["small_text_roi_score_enhanced"] = item["enhanced_score"]
        item["small_text_roi_gain"] = item["score_gain"]
        item["final_output_remeasured"] = True
    valid = [item for item in details if item.get("recoverability_status") != "not_applicable"]
    for item in details:
        item.setdefault("halo_ringing_pass", item.get("small_text_halo_ringing_pass", "not_applicable"))
        item.setdefault("small_text_stroke_consistency", item.get("small_text_stroke_structure_consistency", "not_applicable"))
        intrusion_pass = item.get("small_text_background_intrusion_pass")
        item.setdefault("small_text_background_intrusion_risk", False if intrusion_pass is True else True if intrusion_pass is False else "not_applicable")
    applicable = [item for item in details if item.get("small_text_roi_applicable") is True]
    applied_items = [item for item in applicable if item.get("small_text_enhancement_applied") is True]
    enhanced_count = sum(item.get("small_text_enhancement_applied") is True for item in details)
    reverted_count = sum(item.get("legacy_reverted_to_original_unused") is True for item in details)
    measured_scores = [metric_number(item.get("small_text_roi_score_enhanced")) for item in applicable]
    measured_gains = [metric_number(item.get("small_text_roi_gain")) for item in applicable]
    measured_scores = [value for value in measured_scores if value is not None]
    measured_gains = [value for value in measured_gains if value is not None]
    enhanced_roles = {str(item.get("text_role") or "") for item in applied_items}
    if content_type in {"portrait_commercial_layout", "commercial_ppt_layout"}:
        required_role_pool = {"name_text", "description_text", "label_text"}
        minimum_role_coverage = 2
    elif content_type == "portrait_commercial_poster":
        required_role_pool = {"description_text", "parameter_text", "label_text"}
        minimum_role_coverage = 1
    else:
        required_role_pool = {"small_text", "secondary_text", "name_text", "description_text", "label_text", "parameter_text"}
        minimum_role_coverage = 1
    covered_roles = enhanced_roles & required_role_pool
    role_coverage_pass = len(covered_roles) >= minimum_role_coverage
    structure_confirmation_pass = bool(
        applied_items
        and all(item.get("small_text_character_structure_protection_pass") is True for item in applied_items)
    )
    boundary_evidence = [
        item.get("small_text_roi_boundary_pass")
        for item in applicable
        if item.get("small_text_roi_outcome") in {"enhanced", "safe_rollback"}
    ]
    boundary_verified = bool(boundary_evidence and all(value is True for value in boundary_evidence))
    automatic_supported_candidates = [
        item for item in details
        if item.get("visual_text_line_validated") is True
        and str(item.get("text_role") or "") in required_role_pool
    ]
    observed_output_distortion = any(
        item.get("small_text_enhancement_applied") is True
        and item.get("small_text_character_structure_protection_pass") is False
        for item in applicable
    )
    person_region = person_mask > 0
    person_roi_unchanged = bool(
        not np.any(person_region)
        or np.array_equal(output[person_region], before_beta[person_region])
    )
    aggregate_gain = float(np.mean(measured_gains)) if measured_gains else None
    if not reliable_text:
        small_text_quality_status = "evidence_missing"
    elif automatic_detection and not automatic_supported_candidates:
        small_text_quality_status = "automatic_detection_failed"
    elif observed_output_distortion or not person_roi_unchanged:
        small_text_quality_status = "blocked"
    elif not boundary_verified and applicable:
        small_text_quality_status = "boundary_unverified"
    elif enhanced_count <= 0 or not role_coverage_pass:
        small_text_quality_status = "insufficient_gain"
    elif not structure_confirmation_pass:
        small_text_quality_status = "evidence_missing"
    elif aggregate_gain is not None and aggregate_gain >= 0.20:
        small_text_quality_status = "pass_candidate"
    else:
        small_text_quality_status = "insufficient_gain"
    applicable_halo = [item.get("small_text_halo_ringing_pass") for item in applied_items if isinstance(item.get("small_text_halo_ringing_pass"), bool)]
    applicable_intrusion = [item.get("small_text_background_intrusion_pass") for item in applied_items if isinstance(item.get("small_text_background_intrusion_pass"), bool)]
    stroke_deltas = [metric_number(item.get("small_text_stroke_width_delta")) for item in applied_items]
    stroke_deltas = [value for value in stroke_deltas if value is not None]
    overshoots = [metric_number(item.get("small_text_edge_overshoot")) for item in applied_items]
    overshoots = [value for value in overshoots if value is not None]
    stage_fields = {
        "small_text_stage": "small_text_roi_safe_enhance" if reliable_text and candidates else "not_applicable",
        "small_text_stage_status": "available" if reliable_text and candidates else "not_applicable",
        "small_text_stage_reason": "reliable_text_roi" if reliable_text and candidates else "no_reliable_text_roi" if candidates else "no_small_text_candidate",
        "small_text_detected_count": len(candidates),
        "small_text_valid_count": len(valid),
        "small_text_applicable_count": len(applicable),
        "small_text_recoverable_count": sum(item.get("recoverability_status") == "recoverable" for item in details),
        "small_text_limited_count": sum(item.get("recoverability_status") == "limited_recoverable" for item in details),
        "small_text_unrecoverable_count": sum(item.get("recoverability_status") == "unrecoverable" for item in details),
        "small_text_enhanced_count": enhanced_count,
        "small_text_reverted_count": reverted_count,
        "small_text_safe_rollback_count": sum(item.get("small_text_roi_outcome") == "safe_rollback" for item in details),
        "small_text_not_applicable_count": sum(item.get("small_text_roi_outcome") == "not_applicable" for item in details),
        "small_text_manual_review_count": sum(item.get("small_text_glyph_review") == "requires_human_review" for item in details),
        "small_text_automatic_detection_status": (
            "not_applicable_manual_roi"
            if not automatic_detection else
            "available" if automatic_supported_candidates else "automatic_detection_failed"
        ),
        "small_text_automatic_supported_candidate_count": len(automatic_supported_candidates),
        "small_text_enhanced_roles": sorted(enhanced_roles),
        "small_text_required_role_pool": sorted(required_role_pool),
        "small_text_minimum_role_coverage": minimum_role_coverage,
        "small_text_covered_roles": sorted(covered_roles),
        "small_text_role_coverage_pass": role_coverage_pass,
        "small_text_structure_confirmation_pass": structure_confirmation_pass if applied_items else "not_applicable",
        "small_text_boundary_verified": boundary_verified if applicable else "not_applicable",
        "small_text_roi_score": round(float(np.mean(measured_scores)), 2) if measured_scores else "not_applicable",
        "small_text_roi_gain": round(aggregate_gain, 2) if aggregate_gain is not None else "not_applicable",
        "small_text_roi_applicable": bool(applicable),
        "small_text_character_structure_protection_pass": False if observed_output_distortion else ("requires_human_review" if applicable else "not_applicable"),
        "small_text_stroke_width_delta": round(float(np.mean(stroke_deltas)), 4) if stroke_deltas else "not_applicable",
        "small_text_edge_overshoot": round(float(max(overshoots)), 4) if overshoots else "not_applicable",
        "small_text_halo_ringing_pass": all(applicable_halo) if applicable_halo else "not_applicable",
        "small_text_background_intrusion_pass": all(applicable_intrusion) if applicable_intrusion else "not_applicable",
        "small_text_person_roi_unchanged": person_roi_unchanged,
        "small_text_roi_blend_mode": "feathered_same_coordinate_local_luma_detail",
        "small_text_glyph_review": "requires_human_review" if any(item.get("small_text_glyph_review") == "requires_human_review" for item in details) else "not_applicable",
        "small_text_enhancement_applied": bool(enhanced_count > 0),
        "small_text_quality_status": small_text_quality_status,
        "small_text_delivery_status": "review_before_use",
        "small_text_roi_details": details,
        "small_text_uses_generative_fill": False,
        "small_text_ocr_redraw_used": False,
    }
    visuals = _small_text_visuals(original_target, before_beta, output, details)
    return output, stage_fields, visuals


def small_text_roi_safe_enhance(
    original: np.ndarray,
    beta_image: np.ndarray,
    content_type: str,
    manual_rois: dict[str, object] | None = None,
    face_analysis: dict[str, object] | None = None,
    automatic_candidates: list[dict[str, object]] | None = None,
    source_image_id: str | None = None,
    structure_reviews: dict[str, dict[str, object]] | None = None,
    expected_small_text: bool | None = None,
) -> tuple[np.ndarray, dict[str, object], tuple[np.ndarray | None, np.ndarray | None]]:
    if manual_rois is not None and automatic_candidates is not None:
        raise ValueError("manual_rois_and_automatic_candidates_are_mutually_exclusive")
    original_target = resize_to_match(original, beta_image)
    before_beta = beta_image.copy()
    output = beta_image.copy()
    manual_debug = manual_rois is not None
    automatic_execution = not manual_debug
    source_image_id = source_image_id or f"memory:{_small_text_image_signature(original_target)[:16]}"
    input_signature = _small_text_image_signature(original)
    stage_input_signature = _small_text_image_signature(before_beta)
    code_signature = _small_text_code_signature()
    global_text_mask, global_text_fields = build_primary_delivery_text_mask(original_target)
    reliable_text = bool(np.any(global_text_mask) and float(global_text_fields.get("primary_text_roi_confidence") or 0.0) >= 0.25)
    empty_gate_fields = {
        "manual_roi_debug_only": manual_debug,
        "release_gate_eligible": False,
        "end_to_end_gate_eligible": False,
        "allow_full_image_run": False,
    }
    if content_type not in SMALL_TEXT_CONTENT_TYPES:
        return output, {
            "small_text_stage": "not_applicable",
            "small_text_stage_status": "not_applicable",
            "small_text_stage_reason": "content_type_not_applicable",
            "small_text_detected_count": 0,
            "small_text_valid_count": 0,
            "small_text_applicable_count": 0,
            "small_text_enhanced_count": 0,
            "small_text_reverted_count": 0,
            "small_text_candidate_not_applied_count": 0,
            "small_text_applied_then_reverted_count": 0,
            "small_text_roi_score": "not_applicable",
            "small_text_roi_gain": "not_applicable",
            "small_text_roi_applicable": False,
            "small_text_quality_status": "not_applicable",
            "small_text_delivery_status": "review_before_use",
            "small_text_roi_details": [],
            "small_text_uses_generative_fill": False,
            "small_text_ocr_redraw_used": False,
            **empty_gate_fields,
        }, (None, None)

    preparation_fields: dict[str, object]
    if manual_debug:
        candidates = detect_small_text_rois(original_target, content_type, manual_rois)
        preparation_fields = {
            "source_image_id": source_image_id,
            "source_width": int(original.shape[1]),
            "source_height": int(original.shape[0]),
            "stage_width": int(before_beta.shape[1]),
            "stage_height": int(before_beta.shape[0]),
            "source_coordinate_space": "source_original",
            "stage_coordinate_space": "stage_input",
            "input_signature": input_signature,
            "stage_input_signature": stage_input_signature,
            "code_signature": code_signature,
            "reliable_text_status": "reliable" if reliable_text else "evidence_missing",
            "automatic_candidate_count": 0,
            "automatic_enhancement_eligible_count": 0,
        }
        for index, candidate in enumerate(candidates, start=1):
            candidate.update({
                "detection_id": f"manual-debug:{index:04d}",
                "source_image_id": source_image_id,
                "bbox": candidate.get("roi_box_normalized"),
                "detection_confidence": candidate.get("detector_confidence", 1.0),
                "merged_line_id": f"manual-debug-line:{index:04d}",
                "automatic_text_role": "not_applicable",
                "role_confidence": "not_applicable",
                "reliable_text_status": "reliable" if reliable_text else "evidence_missing",
                "enhancement_eligible": bool(reliable_text and candidate.get("recoverability_status") in {"recoverable", "limited_recoverable"}),
                "execution_input_source": "manual_roi_debug",
                "code_signature": code_signature,
                "input_signature": input_signature,
            })
    else:
        if automatic_candidates is None:
            candidates, preparation_fields = prepare_automatic_small_text_candidates(
                original, content_type, source_image_id
            )
        else:
            candidates = automatic_candidates
            preparation_fields = {
                "source_image_id": source_image_id,
                "source_width": int(original.shape[1]),
                "source_height": int(original.shape[0]),
                "stage_width": int(before_beta.shape[1]),
                "stage_height": int(before_beta.shape[0]),
                "source_coordinate_space": "source_original",
                "stage_coordinate_space": "stage_input",
                "input_signature": input_signature,
                "stage_input_signature": stage_input_signature,
                "code_signature": code_signature,
                "reliable_text_status": "reliable" if reliable_text else "evidence_missing",
                "automatic_candidate_count": len(candidates),
                "automatic_enhancement_eligible_count": sum(item.get("enhancement_eligible") is True for item in candidates),
            }

    if automatic_execution and not candidates:
        text_expected = reliable_text if expected_small_text is None else bool(expected_small_text)
        no_applicable_text = not text_expected
        return output, {
            "small_text_stage": "small_text_automatic_end_to_end",
            "small_text_stage_status": "not_applicable" if no_applicable_text else "blocked",
            "small_text_stage_reason": "no_applicable_text" if no_applicable_text else "expected_text_but_zero_automatic_candidates",
            "source_image_id": source_image_id,
            "input_signature": input_signature,
            "stage_input_signature": stage_input_signature,
            "small_text_detected_count": 0,
            "small_text_valid_count": 0,
            "small_text_applicable_count": 0,
            "small_text_enhanced_count": 0,
            "small_text_real_gain_count": 0,
            "small_text_automatic_detection_status": "not_applicable" if no_applicable_text else "automatic_detection_failed",
            "small_text_reverted_count": 0,
            "small_text_candidate_not_applied_count": 0,
            "small_text_applied_then_reverted_count": 0,
            "small_text_quality_status": "not_applicable" if no_applicable_text else "evidence_missing",
            "small_text_overall_status": "NOT_APPLICABLE" if no_applicable_text else "BLOCKED",
            "automatic_candidate_contract_pass": bool(no_applicable_text),
            "release_gate_eligible": bool(no_applicable_text),
            "end_to_end_gate_eligible": False,
            "allow_full_image_run": False,
            "zero_candidate_semantics": "no_applicable_text" if no_applicable_text else "evidence_missing",
            "manual_roi_debug_only": False,
            "small_text_roi_details": [],
            "small_text_uses_generative_fill": False,
            "small_text_ocr_redraw_used": False,
            **preparation_fields,
        }, (None, None)

    person_mask = _portrait_region_masks(original_target, face_analysis or {})["person"] if face_analysis else np.zeros(original_target.shape[:2], dtype=np.uint8)
    supported_roles = {"small_text", "secondary_text", "name_text", "label_text", "description_text", "parameter_text"}
    non_text_roles = {"decorative_line", "decorative_microtext", "icon_candidate", "icon", "background_texture", "highlight_or_particle", "container_edge", "primary_text", "unknown_text"}
    details: list[dict[str, object]] = []
    automatic_contract_pass = True
    structure_reviews = structure_reviews or {}

    for raw_candidate in candidates:
        item = {key: value for key, value in raw_candidate.items() if not isinstance(value, np.ndarray)}
        if automatic_execution:
            mapping_fields, mapped_masks = map_automatic_small_text_candidate_to_stage(
                raw_candidate, original, before_beta, source_image_id, code_signature
            )
            item.update(mapping_fields)
            required_contract = {
                "detection_id", "source_image_id", "bbox_source", "source_width", "source_height",
                "detection_confidence", "merged_line_id", "automatic_text_role", "role_confidence",
                "reliable_text_status", "enhancement_eligible",
            }
            candidate_contract_pass = bool(
                mapping_fields.get("coordinate_contract_pass") is True
                and mapping_fields.get("mask_contract_pass") is True
                and mapped_masks is not None
                and all(key in raw_candidate for key in required_contract)
            )
            automatic_contract_pass = automatic_contract_pass and candidate_contract_pass
            if not candidate_contract_pass or mapped_masks is None:
                contract_output_equals_original: bool | str = "not_evaluated"
                raw_stage_bbox = mapping_fields.get("bbox_stage")
                if isinstance(raw_stage_bbox, list) and len(raw_stage_bbox) == 4:
                    cx1, cy1, cx2, cy2 = (int(value) for value in raw_stage_bbox)
                    if cx2 > cx1 and cy2 > cy1:
                        contract_output_equals_original = bool(np.array_equal(
                            output[cy1:cy2, cx1:cx2],
                            original_target[cy1:cy2, cx1:cx2],
                        ))
                item.update({
                    "enhancement_eligible": False,
                    "candidate_state": "not_applied",
                    "candidate_processing_state": "candidate_not_applied",
                    "rollback_requested": False,
                    "rollback_target": "none",
                    "rollback_applied": False,
                    "rollback_changed_pixels": 0,
                    "rollback_reason": "none",
                    "output_equals_stage_input": True,
                    "output_equals_original": contract_output_equals_original,
                    "applied_changed_pixels": 0,
                    "small_text_enhancement_applied": False,
                    "small_text_roi_applicable": False,
                    "small_text_roi_outcome": "candidate_not_applied",
                    "candidate_not_applied_reason": "coordinate_or_mask_contract_failed",
                    "small_text_quality_status": "automatic_detection_failed",
                    "small_text_overall_status": "BLOCKED",
                    "release_gate_eligible": False,
                    "end_to_end_gate_eligible": False,
                    "automatic_candidate_contract_pass": False,
                    **_small_text_cross_boundary_audit(np.empty((0, 0, 3), np.uint8), np.empty((0, 0, 3), np.uint8), [0, 0, 0, 0]),
                })
                details.append(item)
                continue
            box = _validated_normalized_box(mapping_fields.get("bbox_stage_normalized"))
            text_mask = mapped_masks["text_mask"]
            background_mask = mapped_masks["background_exclusion_mask"]
            container_mask = mapped_masks["container_edge_exclusion_mask"]
            mask_contract_pass = True
        else:
            box = _validated_normalized_box(item.get("bbox") or item.get("roi_box_normalized"))
            candidate_contract_pass = False
        if box is None:
            item.update({
                "candidate_state": "not_applied",
                "candidate_processing_state": "candidate_not_applied",
                "rollback_requested": False,
                "rollback_target": "none",
                "rollback_applied": False,
                "rollback_changed_pixels": 0,
                "rollback_reason": "invalid_bbox",
                "output_equals_stage_input": True,
                "output_equals_original": False,
                "applied_changed_pixels": 0,
                "small_text_enhancement_applied": False,
                "small_text_roi_applicable": False,
                "small_text_roi_outcome": "candidate_not_applied",
                "coordinate_contract_pass": False,
                "mask_contract_pass": False,
                "contract_failure_reason": "bbox_stage_invalid_after_mapping" if automatic_execution else "invalid_manual_bbox",
                "scoring_called": False,
                "enhancement_called": False,
                **_small_text_cross_boundary_audit(np.empty((0, 0, 3), np.uint8), np.empty((0, 0, 3), np.uint8), [0, 0, 0, 0]),
            })
            details.append(item)
            automatic_contract_pass = False if automatic_execution else automatic_contract_pass
            continue
        stage_bbox_pixels = (
            tuple(int(value) for value in item["bbox_stage"])
            if automatic_execution else _normalized_box_pixel_bounds(before_beta, box)
        )
        original_roi = _normalized_roi_crop(original_target, box)
        stage_input_roi = _normalized_roi_crop(before_beta, box)
        person_roi = _normalized_roi_crop(person_mask, box)
        person_overlap_ratio = float(np.mean(person_roi > 0)) if person_roi.size else 0.0
        if not automatic_execution:
            base_mask, _ = build_primary_delivery_text_mask(original_roi)
            text_mask, _ = _small_text_structure_mask(original_roi, base_mask)
            container_mask = _container_edge_exclusion_mask(original_roi)
            background_mask = cv2.bitwise_not(cv2.bitwise_or(text_mask, container_mask))
            mask_contract_pass = True
            candidate_contract_pass = False
        role = str(item.get("automatic_text_role") if automatic_execution else item.get("text_role") or "unknown_text")
        detection_id = str(item.get("detection_id") or "not_available")
        item["scoring_called"] = True
        original_measurement = _text_roi_absolute_measurement(original_roi, text_mask)
        stage_measurement = _text_roi_absolute_measurement(stage_input_roi, text_mask)
        original_score = metric_number(original_measurement.get("score"))
        stage_score = metric_number(stage_measurement.get("score"))
        pre_attempt_roi = _normalized_roi_crop(output, box).copy()
        enhancement_eligible = bool(
            item.get("enhancement_eligible") is True
            and reliable_text
            and role in supported_roles
            and mask_contract_pass
            and np.count_nonzero(text_mask) >= 24
            and original_score is not None
            and stage_score is not None
            and person_overlap_ratio <= 0.05
        )
        item.update({
            "roi_box_normalized": [round(value, 6) for value in box],
            "text_role": role,
            "automatic_candidate_contract_pass": candidate_contract_pass if automatic_execution else "not_applicable",
            "automatic_bbox_consumed": bool(automatic_execution),
            "automatic_role_consumed": bool(automatic_execution),
            "automatic_text_mask_consumed": bool(automatic_execution and mask_contract_pass),
            "automatic_background_exclusion_mask_consumed": bool(automatic_execution and mask_contract_pass),
            "automatic_container_edge_exclusion_mask_consumed": bool(automatic_execution and mask_contract_pass),
            "enhancement_called": False,
            "person_overlap_ratio": round(person_overlap_ratio, 6),
            "original_score": round(original_score, 2) if original_score is not None else "not_applicable",
            "before_beta_score": round(stage_score, 2) if stage_score is not None else "not_applicable",
            **_small_text_mask_evidence(text_mask, "consumed_text_mask"),
            **_small_text_mask_evidence(background_mask, "consumed_background_exclusion_mask"),
            **_small_text_mask_evidence(container_mask, "consumed_container_edge_exclusion_mask"),
        })

        if not enhancement_eligible:
            final_roi = _normalized_roi_crop(output, box)
            boundary_fields = _small_text_cross_boundary_audit(before_beta, output, stage_bbox_pixels)
            structure_fields = _small_text_structure_metrics(stage_input_roi, final_roi, text_mask)
            item.update({
                **resolve_small_text_structure_review(structure_fields, item, structure_reviews.get(detection_id)),
                "candidate_processing_state": "candidate_not_applied",
                "rollback_requested": False,
                "rollback_target": "none",
                "rollback_applied": False,
                "rollback_changed_pixels": 0,
                "rollback_reason": "none",
                "candidate_not_applied_reason": (
                    "manual_roi_debug_not_release_eligible" if manual_debug
                    else "reliable_text_evidence_missing" if not reliable_text
                    else "person_roi_excluded" if person_overlap_ratio > 0.05
                    else "automatic_candidate_not_eligible" if item.get("enhancement_eligible") is not True
                    else "candidate_contract_or_metric_missing"
                ),
                "output_equals_stage_input": bool(np.array_equal(final_roi, pre_attempt_roi)),
                "output_equals_original": bool(np.array_equal(final_roi, original_roi)),
                "applied_changed_pixels": 0,
                "small_text_enhancement_applied": False,
                "small_text_roi_applicable": bool(role in supported_roles and person_overlap_ratio <= 0.05),
                "small_text_roi_outcome": "candidate_not_applied",
                "small_text_roi_score_enhanced": round(stage_score, 2) if stage_score is not None else "not_applicable",
                "small_text_roi_gain": round(stage_score - original_score, 2) if stage_score is not None and original_score is not None else "not_applicable",
                **boundary_fields,
            })
            details.append(item)
            continue

        item["enhancement_called"] = True
        candidate_roi = _small_text_luma_candidate(stage_input_roi)
        candidate_measurement = _text_roi_absolute_measurement(candidate_roi, text_mask)
        candidate_score = metric_number(candidate_measurement.get("score"))
        stage_detail = metric_number(stage_measurement.get("detail_energy"))
        candidate_detail = metric_number(candidate_measurement.get("detail_energy"))
        stage_gain = candidate_score - stage_score if candidate_score is not None and stage_score is not None else None
        detail_gain = (
            (candidate_detail - stage_detail) / max(stage_detail, 1.0) * 100.0
            if candidate_detail is not None and stage_detail is not None else None
        )
        candidate_structure_auto = _small_text_structure_metrics(stage_input_roi, candidate_roi, text_mask)
        candidate_structure = resolve_small_text_structure_review(
            candidate_structure_auto, item, structure_reviews.get(detection_id)
        )
        positive_gain = bool((stage_gain is not None and stage_gain >= 0.20) or (detail_gain is not None and detail_gain >= 2.0))
        pre_apply_fail = bool(candidate_structure.get("structure_status") == "auto_confirmed_fail" or not positive_gain)
        if pre_apply_fail:
            final_roi = _normalized_roi_crop(output, box)
            item.update({
                **candidate_structure,
                "candidate_processing_state": "candidate_not_applied",
                "rollback_requested": False,
                "rollback_target": "none",
                "rollback_applied": False,
                "rollback_changed_pixels": 0,
                "rollback_reason": "none",
                "candidate_not_applied_reason": "auto_structure_failed" if candidate_structure.get("structure_status") == "auto_confirmed_fail" else "no_real_stage_gain",
                "output_equals_stage_input": bool(np.array_equal(final_roi, pre_attempt_roi)),
                "output_equals_original": bool(np.array_equal(final_roi, original_roi)),
                "applied_changed_pixels": 0,
                "small_text_enhancement_applied": False,
                "small_text_roi_applicable": True,
                "small_text_roi_outcome": "candidate_not_applied",
                "small_text_candidate_score": round(candidate_score, 2) if candidate_score is not None else "not_applicable",
                "small_text_stage_gain": round(stage_gain, 2) if stage_gain is not None else "not_applicable",
                "small_text_candidate_detail_gain_percent": round(detail_gain, 2) if detail_gain is not None else "not_applicable",
                "small_text_roi_score_enhanced": round(stage_score, 2) if stage_score is not None else "not_applicable",
                "small_text_roi_gain": round(stage_score - original_score, 2) if stage_score is not None and original_score is not None else "not_applicable",
                **_small_text_cross_boundary_audit(before_beta, output, stage_bbox_pixels),
            })
            details.append(item)
            continue

        _blend_normalized_roi(output, candidate_roi, box, text_mask)
        applied_roi = _normalized_roi_crop(output, box).copy()
        applied_changed_pixels = int(np.count_nonzero(np.any(applied_roi != pre_attempt_roi, axis=2)))
        if applied_changed_pixels <= 0:
            item.update({
                **candidate_structure,
                "candidate_processing_state": "candidate_not_applied",
                "rollback_requested": False,
                "rollback_target": "none",
                "rollback_applied": False,
                "rollback_changed_pixels": 0,
                "rollback_reason": "none",
                "candidate_not_applied_reason": "candidate_produced_zero_changed_pixels",
                "output_equals_stage_input": True,
                "output_equals_original": bool(np.array_equal(applied_roi, original_roi)),
                "applied_changed_pixels": 0,
                "small_text_enhancement_applied": False,
                "small_text_roi_applicable": True,
                "small_text_roi_outcome": "candidate_not_applied",
                "small_text_roi_score_enhanced": round(stage_score, 2) if stage_score is not None else "not_applicable",
                "small_text_roi_gain": round(stage_score - original_score, 2) if stage_score is not None and original_score is not None else "not_applicable",
                **_small_text_cross_boundary_audit(before_beta, output, stage_bbox_pixels),
            })
            details.append(item)
            continue

        final_measurement = _text_roi_absolute_measurement(applied_roi, text_mask)
        final_score = metric_number(final_measurement.get("score"))
        final_structure_auto = _small_text_structure_metrics(stage_input_roi, applied_roi, text_mask)
        final_structure = resolve_small_text_structure_review(final_structure_auto, item, structure_reviews.get(detection_id))
        candidate_boundary = _small_text_cross_boundary_audit(before_beta, output, stage_bbox_pixels)
        container_delta = 0.0
        if np.count_nonzero(container_mask) >= 12:
            container_delta = float(np.mean(np.abs(applied_roi[container_mask > 0].astype(np.float32) - pre_attempt_roi[container_mask > 0].astype(np.float32))))
        final_original_gain = final_score - original_score if final_score is not None and original_score is not None else None
        final_stage_gain = final_score - stage_score if final_score is not None and stage_score is not None else None
        final_fail_reasons: list[str] = []
        if final_structure.get("small_text_character_structure_protection_pass") is not True:
            final_fail_reasons.append(f"structure_status={final_structure.get('structure_status')}")
        if final_stage_gain is None or final_stage_gain < 0.10:
            final_fail_reasons.append("final_gain_not_visible")
        if final_original_gain is None or final_original_gain < -0.05:
            final_fail_reasons.append("final_below_original_score")
        if candidate_boundary.get("boundary_seam_pass") is not True:
            final_fail_reasons.append("candidate_boundary_seam_failed")
        if container_delta > 1.2:
            final_fail_reasons.append(f"container_edge_delta={container_delta:.3f}>1.2")

        if final_fail_reasons:
            x1, y1, x2, y2 = _normalized_box_pixel_bounds(output, box)
            output[y1:y2, x1:x2] = pre_attempt_roi
            restored_roi = _normalized_roi_crop(output, box)
            rollback_changed_pixels = int(np.count_nonzero(np.any(restored_roi != applied_roi, axis=2)))
            rollback_applied = bool(rollback_changed_pixels > 0 and np.array_equal(restored_roi, pre_attempt_roi))
            boundary_fields = _small_text_cross_boundary_audit(before_beta, output, stage_bbox_pixels)
            item.update({
                **final_structure,
                "candidate_processing_state": "candidate_applied_then_reverted",
                "rollback_requested": True,
                "rollback_target": "stage_input",
                "rollback_applied": rollback_applied,
                "rollback_changed_pixels": rollback_changed_pixels,
                "rollback_reason": ";".join(final_fail_reasons),
                "candidate_not_applied_reason": "not_applicable",
                "output_equals_stage_input": bool(np.array_equal(restored_roi, pre_attempt_roi)),
                "output_equals_original": bool(np.array_equal(restored_roi, original_roi)),
                "applied_changed_pixels": applied_changed_pixels,
                "small_text_enhancement_applied": False,
                "small_text_roi_applicable": True,
                "small_text_roi_outcome": "candidate_applied_then_reverted",
                "small_text_candidate_score": round(candidate_score, 2) if candidate_score is not None else "not_applicable",
                "small_text_stage_gain": round(stage_gain, 2) if stage_gain is not None else "not_applicable",
                "small_text_candidate_detail_gain_percent": round(detail_gain, 2) if detail_gain is not None else "not_applicable",
                "small_text_roi_score_enhanced": round(stage_score, 2) if stage_score is not None else "not_applicable",
                "small_text_roi_gain": round(stage_score - original_score, 2) if stage_score is not None and original_score is not None else "not_applicable",
                "candidate_boundary_seam_pass": candidate_boundary.get("boundary_seam_pass"),
                "small_text_container_edge_delta": round(container_delta, 6),
                **boundary_fields,
            })
        else:
            boundary_fields = _small_text_cross_boundary_audit(before_beta, output, stage_bbox_pixels)
            item.update({
                **final_structure,
                "candidate_processing_state": "enhanced",
                "rollback_requested": False,
                "rollback_target": "none",
                "rollback_applied": False,
                "rollback_changed_pixels": 0,
                "rollback_reason": "none",
                "candidate_not_applied_reason": "not_applicable",
                "output_equals_stage_input": False,
                "output_equals_original": bool(np.array_equal(applied_roi, original_roi)),
                "applied_changed_pixels": applied_changed_pixels,
                "small_text_enhancement_applied": True,
                "small_text_roi_applicable": True,
                "small_text_roi_outcome": "enhanced",
                "small_text_candidate_score": round(candidate_score, 2) if candidate_score is not None else "not_applicable",
                "small_text_stage_gain": round(stage_gain, 2) if stage_gain is not None else "not_applicable",
                "small_text_candidate_detail_gain_percent": round(detail_gain, 2) if detail_gain is not None else "not_applicable",
                "small_text_roi_score_enhanced": round(final_score, 2) if final_score is not None else "not_applicable",
                "small_text_roi_gain": round(final_original_gain, 2) if final_original_gain is not None else "not_applicable",
                "small_text_container_edge_delta": round(container_delta, 6),
                **boundary_fields,
            })
        details.append(item)

    for item in details:
        item.setdefault("halo_ringing_pass", item.get("small_text_halo_ringing_pass", "not_applicable"))
        item.setdefault("small_text_stroke_consistency", item.get("small_text_stroke_structure_consistency", "not_applicable"))
        intrusion_pass = item.get("small_text_background_intrusion_pass")
        item.setdefault("small_text_background_intrusion_risk", False if intrusion_pass is True else True if intrusion_pass is False else "not_applicable")
    applicable = [item for item in details if item.get("small_text_roi_applicable") is True]
    enhanced_items = [item for item in applicable if item.get("candidate_processing_state") == "enhanced"]
    reverted_items = [
        item for item in applicable
        if item.get("candidate_processing_state") == "candidate_applied_then_reverted"
        and item.get("rollback_applied") is True
        and int(item.get("rollback_changed_pixels") or 0) > 0
    ]
    not_applied_items = [item for item in details if item.get("candidate_processing_state") == "candidate_not_applied"]
    enhanced_roles = {str(item.get("text_role") or "") for item in enhanced_items}
    if content_type in {"portrait_commercial_layout", "commercial_ppt_layout"}:
        required_role_pool = {"name_text", "description_text", "label_text"}; minimum_role_coverage = 2
    elif content_type == "portrait_commercial_poster":
        required_role_pool = {"description_text", "parameter_text", "label_text"}; minimum_role_coverage = 1
    else:
        required_role_pool = supported_roles; minimum_role_coverage = 1
    covered_roles = enhanced_roles & required_role_pool
    role_coverage_pass = len(covered_roles) >= minimum_role_coverage
    structure_confirmation_pass = bool(
        enhanced_items
        and all(item.get("structure_status") in {"auto_confirmed_pass", "human_confirmed_pass"} for item in enhanced_items)
    )
    boundary_verified = bool(
        applicable
        and all(item.get("boundary_measurement_performed") is True and item.get("boundary_seam_pass") is True for item in applicable)
    )
    person_region = person_mask > 0
    person_unchanged = bool(not np.any(person_region) or np.array_equal(output[person_region], before_beta[person_region]))
    automatic_eligible = [item for item in details if item.get("execution_input_source") == "automatic_detection" and item.get("enhancement_eligible") is True]
    gains = [metric_number(item.get("small_text_roi_gain")) for item in enhanced_items]
    gains = [value for value in gains if value is not None]
    aggregate_gain = float(np.mean(gains)) if gains else None
    if manual_debug:
        quality_status = "evidence_missing"
    elif not automatic_contract_pass or not automatic_eligible:
        quality_status = "automatic_detection_failed"
    elif not reliable_text:
        quality_status = "evidence_missing"
    elif not person_unchanged:
        quality_status = "blocked"
    elif not boundary_verified:
        quality_status = "boundary_unverified"
    elif not enhanced_items or not role_coverage_pass:
        quality_status = "insufficient_gain"
    elif not structure_confirmation_pass:
        quality_status = "evidence_missing"
    elif aggregate_gain is not None and aggregate_gain >= 0.20:
        quality_status = "pass_candidate"
    else:
        quality_status = "insufficient_gain"
    release_gate_eligible = bool(automatic_execution and automatic_contract_pass and candidates and automatic_eligible)
    end_to_end_gate_eligible = bool(release_gate_eligible)
    scores = [metric_number(item.get("small_text_roi_score_enhanced")) for item in applicable]
    scores = [value for value in scores if value is not None]
    stage_fields = {
        "small_text_stage": "small_text_automatic_end_to_end" if automatic_execution else "small_text_manual_roi_debug",
        "small_text_stage_status": "available" if candidates else "not_applicable",
        "small_text_stage_reason": "automatic_candidates_consumed" if automatic_execution else "manual_roi_debug_only",
        "source_image_id": source_image_id,
        "input_signature": input_signature,
        "code_signature": code_signature,
        "small_text_detected_count": len(candidates),
        "small_text_automatic_detection_status": (
            "not_applicable_manual_roi" if manual_debug else
            "available" if automatic_eligible else "automatic_detection_failed"
        ),
        "small_text_automatic_supported_candidate_count": len(automatic_eligible),
        "small_text_valid_count": len(applicable),
        "small_text_applicable_count": len(applicable),
        "small_text_enhanced_count": len(enhanced_items),
        "small_text_real_gain_count": len(enhanced_items),
        "small_text_recoverable_count": sum(item.get("recoverability_status") == "recoverable" for item in details),
        "small_text_limited_count": sum(item.get("recoverability_status") == "limited_recoverable" for item in details),
        "small_text_unrecoverable_count": sum(item.get("recoverability_status") == "unrecoverable" for item in details),
        "small_text_reverted_count": len(reverted_items),
        "small_text_candidate_not_applied_count": len(not_applied_items),
        "small_text_applied_then_reverted_count": len(reverted_items),
        "small_text_safe_rollback_count": len(reverted_items),
        "small_text_not_applicable_count": sum(item.get("small_text_roi_applicable") is not True for item in details),
        "small_text_roi_score": round(float(np.mean(scores)), 2) if scores else "not_applicable",
        "small_text_roi_gain": round(aggregate_gain, 2) if aggregate_gain is not None else "not_applicable",
        "small_text_roi_applicable": bool(applicable),
        "small_text_character_structure_protection_pass": (
            True if structure_confirmation_pass else
            False if any(item.get("structure_status") in {"auto_confirmed_fail", "human_confirmed_fail"} for item in applicable)
            else "requires_human_review" if applicable else "not_applicable"
        ),
        "small_text_structure_confirmation_pass": structure_confirmation_pass if enhanced_items else "not_applicable",
        "small_text_enhanced_roles": sorted(enhanced_roles),
        "small_text_required_role_pool": sorted(required_role_pool),
        "small_text_minimum_role_coverage": minimum_role_coverage,
        "small_text_covered_roles": sorted(covered_roles),
        "small_text_role_coverage_pass": role_coverage_pass,
        "small_text_boundary_verified": boundary_verified if applicable else "not_applicable",
        "small_text_person_roi_unchanged": person_unchanged,
        "small_text_enhancement_applied": bool(enhanced_items),
        "small_text_quality_status": quality_status,
        "small_text_overall_status": "BLOCKED" if quality_status in {"insufficient_gain", "blocked", "evidence_missing", "automatic_detection_failed", "boundary_unverified"} else "NOT_APPLICABLE" if quality_status == "not_applicable" else "REVIEW_REQUIRED",
        "small_text_delivery_status": "review_before_use",
        "small_text_roi_details": details,
        "small_text_uses_generative_fill": False,
        "small_text_ocr_redraw_used": False,
        "manual_roi_debug_only": manual_debug,
        "release_gate_eligible": release_gate_eligible,
        "end_to_end_gate_eligible": end_to_end_gate_eligible,
        "allow_full_image_run": False,
        "automatic_bbox_consumed_count": sum(item.get("automatic_bbox_consumed") is True for item in details),
        "automatic_role_consumed_count": sum(item.get("automatic_role_consumed") is True for item in details),
        "automatic_text_mask_consumed_count": sum(item.get("automatic_text_mask_consumed") is True for item in details),
        "automatic_candidate_contract_pass": automatic_contract_pass if automatic_execution else "not_applicable",
        **preparation_fields,
    }
    visuals = _small_text_visuals(original_target, before_beta, output, details)
    return output, stage_fields, visuals


def small_text_end_to_end_in_memory(
    original: np.ndarray,
    beta_image: np.ndarray,
    content_type: str,
    source_image_id: str,
    face_analysis: dict[str, object] | None = None,
    structure_reviews: dict[str, dict[str, object]] | None = None,
    expected_small_text: bool | None = None,
) -> tuple[np.ndarray, dict[str, object], tuple[np.ndarray | None, np.ndarray | None]]:
    candidates, _ = prepare_automatic_small_text_candidates(original, content_type, source_image_id)
    return small_text_roi_safe_enhance(
        original,
        beta_image,
        content_type,
        face_analysis=face_analysis,
        automatic_candidates=candidates,
        source_image_id=source_image_id,
        structure_reviews=structure_reviews,
        expected_small_text=expected_small_text,
    )


def _portrait_region_masks(image: np.ndarray, face_analysis: dict[str, object]) -> dict[str, np.ndarray]:
    height, width = image.shape[:2]
    face = np.zeros((height, width), dtype=np.uint8)
    hair = np.zeros_like(face)
    clothing = np.zeros_like(face)
    person = np.zeros_like(face)
    for candidate in face_analysis.get("face_candidates") or []:
        if not isinstance(candidate, dict) or candidate.get("accepted_as_face") is not True:
            continue
        box = _validated_normalized_box(candidate.get("bbox_normalized"))
        if box is None:
            continue
        x1, y1, x2, y2 = _normalized_box_pixel_bounds(image, box)
        face[y1:y2, x1:x2] = 255
        fw = x2 - x1; fh = y2 - y1
        hair[max(0, y1 - fh // 2):min(height, y1 + fh // 3), max(0, x1 - fw // 3):min(width, x2 + fw // 3)] = 255
        clothing[max(0, y2):min(height, y2 + fh * 4), max(0, x1 - fw):min(width, x2 + fw)] = 255
        person[max(0, y1 - fh // 2):min(height, y2 + fh * 6), max(0, x1 - fw):min(width, x2 + fw)] = 255
    return {
        "face": face,
        "hair": cv2.morphologyEx(hair, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1),
        "clothing": cv2.morphologyEx(clothing, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), iterations=1),
        "person": cv2.morphologyEx(person, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=1),
    }


def _masked_detail_change(original: np.ndarray, enhanced: np.ndarray, mask: np.ndarray) -> tuple[float | None, float | None, float | None]:
    region = mask > 0
    if int(np.sum(region)) < 64:
        return None, None, None
    before_gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    after_gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
    before_detail = np.abs(cv2.Laplacian(before_gray, cv2.CV_32F))
    after_detail = np.abs(cv2.Laplacian(after_gray, cv2.CV_32F))
    before_value = float(np.mean(before_detail[region]))
    after_value = float(np.mean(after_detail[region]))
    gain = (after_value - before_value) / max(before_value, 1.0) * 100.0
    return before_value, after_value, gain


def portrait_quality_evidence(
    original: np.ndarray,
    final_png: np.ndarray,
    face_analysis: dict[str, object] | None,
    content_type: str,
    route: str,
) -> dict[str, object]:
    portrait_applicable = content_type.startswith("portrait_") or route in {
        PORTRAIT_PHOTO_ROUTE,
        PORTRAIT_COMMERCIAL_POSTER_ROUTE,
        PORTRAIT_COMMERCIAL_ROUTE,
        PORTRAIT_GROUP_SAFE_ROUTE,
    }
    if not portrait_applicable:
        return {"portrait_metric_status": "not_applicable"}
    face_analysis = face_analysis or {}
    original_target = resize_to_match(original, final_png)
    masks = _portrait_region_masks(original_target, face_analysis)
    face_details: list[dict[str, object]] = []
    for candidate in face_analysis.get("face_candidates") or []:
        if not isinstance(candidate, dict) or candidate.get("accepted_as_face") is not True:
            continue
        box = _validated_normalized_box(candidate.get("bbox_normalized"))
        if box is None:
            continue
        before_roi = _normalized_roi_crop(original_target, box)
        after_roi = _normalized_roi_crop(final_png, box)
        evaluation_width = max(before_roi.shape[1], after_roi.shape[1])
        evaluation_height = max(before_roi.shape[0], after_roi.shape[0])
        before_roi = cv2.resize(before_roi, (evaluation_width, evaluation_height), interpolation=cv2.INTER_CUBIC)
        after_roi = cv2.resize(after_roi, (evaluation_width, evaluation_height), interpolation=cv2.INTER_CUBIC)
        full_mask = np.full(before_roi.shape[:2], 255, dtype=np.uint8)
        structure = _stroke_structure_consistency(before_roi, after_roi, full_mask)
        halo = edge_artifact_quality(before_roi, after_roi, 100.0)
        color_delta = float(np.mean(np.abs(cv2.cvtColor(before_roi, cv2.COLOR_BGR2LAB).astype(np.float32) - cv2.cvtColor(after_roi, cv2.COLOR_BGR2LAB).astype(np.float32))))
        face_details.append({
            "face_id": candidate.get("face_id"),
            "bbox_normalized": list(box),
            "face_structure_score": round(structure, 2),
            "face_color_delta": round(color_delta, 3),
            "face_halo_ringing_pass": halo.get("halo_ringing_pass"),
            "face_edge_overshoot_ratio": halo.get("edge_overshoot_ratio"),
            "identity_review": "requires_human_review",
        })
    global_halo = edge_artifact_quality(original_target, final_png, 100.0)
    face_structure_pass: object = (
        bool(face_details and all(float(item["face_structure_score"]) >= 90.0 and item["face_halo_ringing_pass"] is True for item in face_details))
        if face_details else False
    )
    face_halo_pass: object = bool(face_details and all(item["face_halo_ringing_pass"] is True for item in face_details)) if face_details else False
    skin_mask = cv2.bitwise_and(build_protection_masks(original_target)["skin_raw"], masks["person"])
    _, _, skin_change = _masked_detail_change(original_target, final_png, skin_mask)
    _, _, hair_change = _masked_detail_change(original_target, final_png, masks["hair"])
    _, _, clothing_gain = _masked_detail_change(original_target, final_png, masks["clothing"])
    before_gray = cv2.cvtColor(original_target, cv2.COLOR_BGR2GRAY)
    background_base = cv2.bitwise_not(cv2.dilate(masks["person"], np.ones((13, 13), np.uint8), iterations=1))
    background_low_detail = (cv2.GaussianBlur(np.abs(cv2.Laplacian(before_gray, cv2.CV_32F)), (0, 0), 1.0) < 8.0).astype(np.uint8) * 255
    background_mask = cv2.bitwise_and(background_base, background_low_detail)
    _, _, background_change = _masked_detail_change(original_target, final_png, background_mask)
    hair_edge_consistency = "not_available" if hair_change is None else round(float(np.clip(100.0 - abs(hair_change) * 0.55, 0.0, 100.0)), 2)
    skin_pass: object = "not_available" if skin_change is None else bool(-35.0 <= skin_change <= 28.0)
    hair_pass: object = "not_available" if hair_change is None else bool(abs(hair_change) <= 32.0 and (metric_number(hair_edge_consistency) or 0.0) >= 82.0)
    clothing_risk: object = "not_available" if clothing_gain is None else bool(clothing_gain > 38.0)
    background_pass: object = "not_available" if background_change is None else bool(abs(background_change) <= 26.0)
    material_mask = ((cv2.cvtColor(original_target, cv2.COLOR_BGR2HSV)[:, :, 1] < 52) & (cv2.cvtColor(original_target, cv2.COLOR_BGR2HSV)[:, :, 2] > 135) & (masks["person"] == 0)).astype(np.uint8) * 255
    _, _, transparent_change = _masked_detail_change(original_target, final_png, material_mask)
    transparent_pass: object = "not_available" if transparent_change is None else bool(abs(transparent_change) <= 28.0)
    container_mask = cv2.bitwise_and(_container_edge_exclusion_mask(original_target), cv2.bitwise_not(masks["person"]))
    _, _, container_change = _masked_detail_change(original_target, final_png, container_mask)
    container_pass: object = "not_available" if container_change is None else bool(abs(container_change) <= 18.0)
    commercial_layout_pass: object = (
        bool(global_halo.get("halo_ringing_pass") is True and transparent_pass is not False and container_pass is not False)
        if content_type in {"portrait_commercial_poster", "portrait_commercial_layout"}
        else "not_applicable"
    )
    return {
        "portrait_metric_status": "available",
        "identity_protection_pass": "requires_human_review",
        "identity_protection_status": "requires_human_review",
        "identity_protection_reason": "no_face_embedding_or_traceable_human_identity_confirmation",
        "face_structure_protection_pass": face_structure_pass,
        "face_structure_details": face_details,
        "skin_protection_pass": skin_pass,
        "skin_texture_change": round(skin_change, 2) if skin_change is not None else "not_available",
        "hair_protection_pass": hair_pass,
        "hair_edge_consistency": hair_edge_consistency,
        "clothing_texture_gain": round(clothing_gain, 2) if clothing_gain is not None else "not_available",
        "clothing_hallucination_risk": clothing_risk,
        "background_blur_protection_pass": background_pass,
        "background_blur_change": round(background_change, 2) if background_change is not None else "not_available",
        "global_halo_ringing_pass": global_halo.get("halo_ringing_pass"),
        "face_halo_ringing_pass": face_halo_pass,
        "primary_text_halo_ringing_pass": "not_applicable" if content_type == "portrait_photo" else global_halo.get("halo_ringing_pass"),
        "small_text_halo_ringing_pass": "not_applicable",
        "commercial_layout_protection_pass": commercial_layout_pass,
        "transparent_material_protection_pass": transparent_pass,
        "container_edge_protection_pass": container_pass,
        "container_edge_detail_change": round(container_change, 2) if container_change is not None else "not_available",
        "container_edge_mask_source": "long_horizontal_vertical_edges_excluding_people",
        "face_count_raw": int(face_analysis.get("face_candidate_count_raw") or 0),
        "face_count_filtered": int(face_analysis.get("face_candidate_count_filtered") or 0),
        "face_candidates": face_analysis.get("face_candidates") or [],
        "face_detector": face_analysis.get("face_detector") or "not_available",
        "face_iou_dedup_threshold": face_analysis.get("face_iou_dedup_threshold", "not_available"),
    }


def route_quality_diagnostics(original: np.ndarray, final_png: np.ndarray, route: str, scores: dict[str, object]) -> dict[str, object]:
    original_target = resize_to_match(original, final_png)
    if route in {"already_1080p_fast_safe_enhance", BALANCED_FAST_ROUTE, PORTRAIT_COMMERCIAL_ROUTE, PORTRAIT_COMMERCIAL_POSTER_ROUTE}:
        primary_mask, mask_fields = build_primary_delivery_text_mask(original_target)
        reliable_roi = float(mask_fields["primary_text_roi_confidence"]) >= 0.45
        if not reliable_roi:
            return {
                "commercial_product_text_roi_mode": True,
                "primary_delivery_text_mask": "not_available",
                "primary_text_roi_score": "not_applicable",
                "primary_text_roi_gain": "not_applicable",
                "commercial_text_quality_pass": "not_applicable",
                "commercial_text_quality_reason": "no_reliable_text_roi",
                **mask_fields,
            }
        original_measurement = _text_roi_absolute_measurement(original_target, primary_mask)
        enhanced_measurement = _text_roi_absolute_measurement(final_png, primary_mask)
        original_score = metric_number(original_measurement.get("score"))
        enhanced_score = metric_number(enhanced_measurement.get("score"))
        gain = None if original_score is None or enhanced_score is None else enhanced_score - original_score
        global_score = metric_number(scores.get("text_clarity_score"))
        quality_pass = bool(global_score is not None and global_score >= 45.0 and gain is not None and gain >= 0.0)
        return {
            "commercial_product_text_roi_mode": True,
            "commercial_text_detail_boost": "local_laplacian_primary_text" if route not in {PORTRAIT_COMMERCIAL_ROUTE, PORTRAIT_COMMERCIAL_POSTER_ROUTE} else "person_excluded_local_laplacian_primary_text",
            "primary_delivery_text_mask": "available",
            "text_clarity_score_global": round(global_score, 2) if global_score is not None else "not_applicable",
            "primary_text_roi_score_original": round(original_score, 2) if original_score is not None else "not_applicable",
            "primary_text_roi_score": round(enhanced_score, 2) if enhanced_score is not None else "not_applicable",
            "primary_text_roi_gain": round(gain, 2) if gain is not None else "not_applicable",
            **mask_fields,
            "commercial_text_quality_pass": bool(quality_pass),
            "commercial_text_quality_reason": "global_floor_and_primary_roi_passed" if quality_pass else "applicable_text_metric_floor_not_met",
        }
    if route in KNOWLEDGE_ROUTES:
        gray = cv2.cvtColor(original_target, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 42, 128)
        adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 7)
        high_value = cv2.bitwise_and(adaptive, cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1))
        high_value = cv2.dilate(high_value, np.ones((3, 3), np.uint8), iterations=1)
        original_measurement = _text_roi_absolute_measurement(original_target, high_value)
        enhanced_measurement = _text_roi_absolute_measurement(final_png, high_value)
        original_score = metric_number(original_measurement.get("score"))
        enhanced_score = metric_number(enhanced_measurement.get("score"))
        gain = None if original_score is None or enhanced_score is None else enhanced_score - original_score
        pseudo = bool(scores.get("is_pseudo_hd"))
        return {
            "text_line_high_value_mask": "available",
            "background_low_value_mask": "available",
            "knowledge_text_line_roi_score_original": round(original_score, 2) if original_score is not None else "not_applicable",
            "knowledge_text_line_roi_gain": round(gain, 2) if gain is not None else "not_applicable",
            "knowledge_text_line_roi_score": round(enhanced_score, 2) if enhanced_score is not None else "not_applicable",
            "knowledge_pseudo_hd_trigger_reason": "none" if not pseudo else (
                f"valid_gain_not_met: clarity_gain={scores.get('clarity_gain')}; text_gain={scores.get('text_clarity_gain')}; edge_gain={scores.get('edge_quality_gain')}"
            ),
            "knowledge_quality_pass": bool(not pseudo and gain is not None and gain > 0.0),
        }
    if route == PORTRAIT_PHOTO_ROUTE:
        return {
            "text_clarity_score": "not_applicable",
            "text_clarity_gain": "not_applicable",
            "text_metric_applicable": False,
            "text_metric_reason": "portrait_photo_without_core_text",
        }
    return {"text_metric_applicable": False if route == PORTRAIT_GROUP_SAFE_ROUTE else True}


def compute_safe_beta_quality_scores(
    original: np.ndarray,
    final_png: np.ndarray,
    route: str = "",
    image_quality_profile: str | None = None,
    text_roi_boxes: dict[str, tuple[float, float, float, float]] | None = None,
    content_type: str | None = None,
    roi_source: str | None = None,
    background_roi_box: tuple[float, float, float, float] | None = None,
    glyph_integrity_review: str | None = None,
    glyph_review_evidence: dict[str, object] | None = None,
    face_analysis: dict[str, object] | None = None,
) -> dict[str, object]:
    try:
        scores = compare_quality(original, final_png)
    except Exception as exc:
        return {"quality_score_status": "failed", "quality_score_reason": tail_text(exc, 180)}
    texture_fields = semantic_texture_quality(original, final_png)
    edge_fields = edge_artifact_quality(original, final_png, scores.get("edge_quality_score"))
    type_fields = content_type_fields(content_type, infer_image_quality_profile(route))
    profile = image_quality_profile if image_quality_profile in IMAGE_QUALITY_PROFILES else str(type_fields["image_quality_profile"])
    merged = {
        "quality_score_status": "available",
        "image_quality_profile": profile,
        **type_fields,
        "image_quality_profile": profile,
        **scores,
        **texture_fields,
        **edge_fields,
    }
    route_fields = route_quality_diagnostics(original, final_png, route, merged)
    merged.update(route_fields)
    merged.update(text_roi_quality_evidence(original, final_png, profile, text_roi_boxes, glyph_integrity_review, glyph_review_evidence))
    if roi_source:
        merged["roi_source"] = roi_source
    if background_roi_box is not None and _validated_normalized_box(background_roi_box) is not None:
        background_before, background_after, _, background_status = _same_coordinate_roi_pair(original, final_png, background_roi_box)
        if background_status == "available" and background_before is not None and background_after is not None:
            background_fields = edge_artifact_quality(background_before, background_after, 100.0)
            background_noise = semantic_texture_quality(background_before, background_after)
            background_pass: object = bool(
                (metric_number(background_noise.get("texture_noise_growth")) or 0.0) <= 35.0
                and background_fields.get("halo_ringing_pass") is True
            )
            background_source = "explicit_background_roi"
        else:
            background_pass = "not_available"
            background_source = "invalid_background_roi"
    else:
        background_pass = "not_available"
        background_source = "no_background_roi"
    color_score = metric_number(merged.get("color_fidelity_score"))
    merged.update({
        "texture_roi_score": merged.get("texture_score"),
        "texture_roi_gain": merged.get("texture_gain"),
        "background_blur_protection_pass": background_pass,
        "background_roi_source": background_source,
        "color_fidelity_status": (
            "not_available" if color_score is None
            else "meets_target" if color_score >= 96.0
            else "manual_review" if color_score >= 94.0
            else "high_risk"
        ),
    })
    merged.update(portrait_quality_evidence(original, final_png, face_analysis, str(type_fields["content_type"]), route))
    merged["quality_flag"] = "pending_quality_gate"
    return merged


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
    detail_started = time.perf_counter()
    enhanced = apply_commercial_text_detail_boost(enhanced, original_target)
    timing["commercial_text_detail_seconds"] = round(time.perf_counter() - detail_started, 3)
    halo_started = time.perf_counter()
    enhanced, halo_fields = suppress_high_contrast_overshoot(enhanced, original_target)
    timing["halo_suppress_seconds"] = round(time.perf_counter() - halo_started, 3)

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
        "commercial_product_text_roi_mode": True,
        **halo_fields,
        **resolution_policy_fields(original, enhanced, route_decision),
    }
    return enhanced, fields, timing


def portrait_group_conservative_enhance(
    original: np.ndarray,
    route_decision: dict[str, object],
    route_name: str = PORTRAIT_GROUP_SAFE_ROUTE,
    enhance_layout_text: bool = False,
) -> tuple[np.ndarray | None, dict[str, object], dict[str, object]]:
    timing = default_enhance_timing_fields(route_name)
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
        return None, {"output_resolution_profile": route_decision.get("target_profile") or "invalid_portrait_group_target", **image_dimensions(original)}, timing

    started = time.perf_counter()
    original_target = cv2.resize(original, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)
    timing["resize_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    scale_x = target_width / original.shape[1]
    scale_y = target_height / original.shape[0]
    face_mask = np.zeros((target_height, target_width), dtype=np.uint8)
    person_mask = np.zeros_like(face_mask)
    hair_mask = np.zeros_like(face_mask)
    for raw_box in route_decision.get("group_face_boxes") or []:
        x, y, width, height = (int(value) for value in raw_box)
        x = int(round(x * scale_x)); y = int(round(y * scale_y))
        width = max(1, int(round(width * scale_x))); height = max(1, int(round(height * scale_y)))
        fx1 = max(0, x - width // 2); fx2 = min(target_width, x + width + width // 2)
        fy1 = max(0, y - height // 2); fy2 = min(target_height, y + height + height // 2)
        face_mask[fy1:fy2, fx1:fx2] = 255
        px1 = max(0, x - width * 2); px2 = min(target_width, x + width * 3)
        py1 = max(0, y - height); py2 = min(target_height, y + height * 10)
        person_mask[py1:py2, px1:px2] = 255
        hx1 = max(0, x - width); hx2 = min(target_width, x + width * 2)
        hy1 = max(0, y - height); hy2 = min(target_height, y + max(1, height // 2))
        hair_mask[hy1:hy2, hx1:hx2] = 255
    person_mask = cv2.morphologyEx(person_mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=1)
    timing["roi_detect_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    gray = cv2.cvtColor(original_target, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 65, 165)
    adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 8)
    strict_text = cv2.bitwise_and(adaptive, cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1))
    strict_text = cv2.morphologyEx(strict_text, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8), iterations=1)
    local_detail = cv2.absdiff(gray, cv2.GaussianBlur(gray, (0, 0), 1.1))
    low_information = ((local_detail < 4) & (edges == 0)).astype(np.uint8) * 255
    protected = cv2.bitwise_or(person_mask, face_mask)
    protected = cv2.bitwise_or(protected, hair_mask)
    safe_structure = cv2.bitwise_or(strict_text, cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1))
    safe_structure[protected > 0] = 0
    safe_structure[low_information > 0] = 0
    safe_mask = cv2.GaussianBlur(safe_structure.astype(np.float32) / 255.0, (0, 0), 0.48)[:, :, None]
    timing["mask_build_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    detail = np.clip(
        original_target.astype(np.float32) - cv2.GaussianBlur(original_target, (0, 0), 0.52).astype(np.float32),
        -10.0,
        10.0,
    )
    person_texture = cv2.bitwise_and(cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1), person_mask)
    person_texture[face_mask > 0] = 0
    person_texture_mask = cv2.GaussianBlur(person_texture.astype(np.float32) / 255.0, (0, 0), 0.62)[:, :, None]
    enhanced = np.clip(
        original_target.astype(np.float32)
        + detail * safe_mask * 0.32
        + np.clip(detail, -6.0, 6.0) * person_texture_mask * 0.12,
        0,
        255,
    ).astype(np.uint8)
    timing["local_detail_seconds"] = round(time.perf_counter() - started, 3)
    if enhance_layout_text:
        started = time.perf_counter()
        enhanced = apply_commercial_text_detail_boost(enhanced, original_target, person_mask)
        timing["commercial_text_detail_seconds"] = round(time.perf_counter() - started, 3)
    started = time.perf_counter()
    enhanced, halo_fields = suppress_high_contrast_overshoot(enhanced, original_target)
    timing["halo_suppress_seconds"] = round(time.perf_counter() - started, 3)

    fields = {
        "output_resolution_profile": route_decision.get("target_profile") or "short_edge_1080",
        **image_dimensions(enhanced),
        "enhance_route": route_name,
        "route_decision_reason": route_decision.get("route_decision_reason") or "",
        "already_1080p_or_near_1080p": route_decision.get("already_1080p_or_near_1080p", False),
        "input_to_output_scale_ratio": route_decision.get("input_to_output_scale_ratio", "not_applicable"),
        "realesrgan_used": False,
        "uses_realesrgan": False,
        "fast_route_skipped_realesrgan": True,
        "fast_route_skipped_protected_heavy_chain": True,
        "portrait_group_face_count": int(route_decision.get("group_face_count") or 0),
        "face_protection_applied": bool(np.any(face_mask)),
        "skin_protection_applied": bool(np.any(person_mask)),
        "hair_protection_applied": bool(np.any(hair_mask)),
        "clothing_protection_applied": bool(np.any(person_mask)),
        "background_defocus_protection_applied": bool(np.any(low_information)),
        "portrait_detail_policy": "preserve_person_pixels_and_low_information_background",
        "commercial_product_text_roi_mode": bool(enhance_layout_text),
        "face_candidate_count_raw": route_decision.get("face_candidate_count_raw"),
        "face_candidate_count_filtered": route_decision.get("face_candidate_count_filtered"),
        "face_detection_confidence": route_decision.get("group_face_detection_confidence"),
        "face_area_ratio": route_decision.get("group_face_area_ratio"),
        "face_candidates": route_decision.get("face_candidates") or [],
        "route_evidence": route_decision.get("route_evidence") or {},
        **halo_fields,
        **resolution_policy_fields(original, enhanced, route_decision),
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
    high_value_detail = np.clip(enhanced.astype(np.float32) - cv2.GaussianBlur(enhanced, (0, 0), 0.42).astype(np.float32), -14.0, 14.0)
    enhanced = np.clip(enhanced.astype(np.float32) + high_value_detail * np.clip(text_line_mask * 0.75, 0, 0.75), 0, 255).astype(np.uint8)
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
        "fast_route_skipped_protected_heavy_chain": True,
        "text_line_high_value_mask": "available",
        "background_low_value_mask": "available",
        **resolution_policy_fields(original, enhanced, route_decision),
    }
    return enhanced, fields, timing


def slowest_stage(timing: dict[str, object]) -> tuple[str, float | str]:
    values: list[tuple[str, float]] = []
    for key in TIMED_ENHANCE_STAGE_KEYS:
        try:
            raw_value = timing.get(key)
            value = float(raw_value) if raw_value not in (None, "", "not_applicable", "unavailable") else 0.0
        except (TypeError, ValueError):
            value = 0.0
        if value > 0.0:
            values.append((key, value))
    return max(values, key=lambda item: item[1]) if values else ("stage_timing_unavailable", "unavailable")


def speed_fields_for_route(route: str, actual_seconds: float, timing: dict[str, object]) -> dict[str, object]:
    if route in {"already_1080p_fast_safe_enhance", BALANCED_FAST_ROUTE}:
        speed_class = "near_1080p_fast_commercial"
        target = "8-15"
        risk = actual_seconds > 25
    elif route in {"knowledge_poster_mode", "dense_chinese_poster_mode", "text_dense_visual_mode"}:
        speed_class = "knowledge_dense_poster"
        target = "20-40"
        risk = actual_seconds > 60
    elif route in {PORTRAIT_GROUP_SAFE_ROUTE, PORTRAIT_COMMERCIAL_ROUTE, PORTRAIT_COMMERCIAL_POSTER_ROUTE, PORTRAIT_PHOTO_ROUTE}:
        speed_class = {
            PORTRAIT_GROUP_SAFE_ROUTE: "portrait_group_conservative_safe",
            PORTRAIT_COMMERCIAL_ROUTE: "portrait_commercial_layout_safe",
            PORTRAIT_COMMERCIAL_POSTER_ROUTE: "portrait_commercial_poster_safe",
            PORTRAIT_PHOTO_ROUTE: "portrait_photo_conservative_safe",
        }[route]
        target = "30-60"
        risk = actual_seconds > 90
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
        "slowest_stage_seconds": round(stage_seconds, 3) if isinstance(stage_seconds, (int, float)) else "unavailable",
        "heavy_route_speed_risk": bool(speed_class == "heavy_low_clarity_or_general" and actual_seconds > 90),
    }


def route_diagnostics_consistency(rows: list[dict[str, object]]) -> dict[str, object]:
    blockers: list[str] = []
    for row in rows:
        file_name = str(row.get("file") or row.get("input_name") or "unknown")
        route = str(row.get("enhance_route") or "")
        portrait_context = bool(row.get("portrait_context_established"))
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
            try:
                if float(row.get("speed_actual_seconds") or 0) > 30.0:
                    blockers.append(f"{file_name}: fast route speed_actual_seconds>30")
            except (TypeError, ValueError):
                blockers.append(f"{file_name}: invalid speed_actual_seconds")
        if route in {PORTRAIT_PHOTO_ROUTE, PORTRAIT_COMMERCIAL_POSTER_ROUTE, PORTRAIT_COMMERCIAL_ROUTE, PORTRAIT_GROUP_SAFE_ROUTE}:
            if row.get("face_count_filtered") in (None, ""):
                blockers.append(f"{file_name}: missing face_count_filtered")
            if not isinstance(row.get("face_candidates"), list):
                blockers.append(f"{file_name}: missing face_candidates")
            if row.get("identity_protection_status") not in {"requires_human_review", "human_confirmed"}:
                blockers.append(f"{file_name}: invalid identity_protection_status")
            if route == PORTRAIT_GROUP_SAFE_ROUTE and bool(row.get("uses_realesrgan")):
                blockers.append(f"{file_name}: portrait_group uses_realesrgan=true")
        if portrait_context:
            if row.get("portrait_metric_status") != "available":
                blockers.append(f"{file_name}: portrait_metrics_missing:evidence_missing")
            if row.get("identity_protection_status") not in {"requires_human_review", "human_confirmed"}:
                blockers.append(f"{file_name}: portrait_identity_evidence_missing")
        if bool(row.get("portrait_group_context")):
            if bool(row.get("uses_realesrgan")):
                blockers.append(f"{file_name}: portrait_group_guard_failed")
            if row.get("realesrgan_block_reason") != "portrait_group_guard":
                blockers.append(f"{file_name}: missing_portrait_group_guard_reason")
        if bool(row.get("unexpected_downscale")):
            blockers.append(f"{file_name}: unexpected_downscale")
        if row.get("quality_status") in (None, ""):
            blockers.append(f"{file_name}: missing quality_status")
    return {
        "diagnostics_consistency": "PASS" if not blockers else "BLOCKED",
        "diagnostics_consistency_blockers": blockers,
    }


def resolve_sync_summary_status(
    rows: list[dict[str, object]],
    diagnostics_consistency: str,
) -> dict[str, object]:
    blocking_small_text_statuses = {
        "insufficient_gain",
        "blocked",
        "evidence_missing",
        "automatic_detection_failed",
        "boundary_unverified",
    }
    row_quality_statuses = [str(item.get("quality_status") or "") for item in rows]
    row_small_text_statuses = [str(item.get("small_text_quality_status") or "") for item in rows]
    blocking_statuses = sorted(status for status in set(row_small_text_statuses) if status in blocking_small_text_statuses)
    small_text_sync_blocked = bool(blocking_statuses)
    aggregate_quality_status = (
        "blocked" if "blocked" in row_quality_statuses or small_text_sync_blocked
        else "insufficient_gain" if "insufficient_gain" in row_quality_statuses
        else "pass_candidate" if rows else "blocked"
    )
    verification_result = (
        "BLOCKED"
        if diagnostics_consistency == "BLOCKED" or aggregate_quality_status == "blocked"
        else "PASS_WITH_NOTES"
    )
    return {
        "quality_status": aggregate_quality_status,
        "verification_result": verification_result,
        "small_text_sync_blocked": small_text_sync_blocked,
        "small_text_blocking_statuses": blocking_statuses,
    }


def fast_route_pass_fields(route: str, speed_fields: dict[str, object], quality_fields: dict[str, object], output_fields: dict[str, object]) -> dict[str, object]:
    if route not in {"already_1080p_fast_safe_enhance", BALANCED_FAST_ROUTE}:
        return {}
    text_score = metric_number(quality_fields.get("text_clarity_score"))
    edge_score = metric_number(quality_fields.get("edge_quality_score"))
    texture_score = metric_number(quality_fields.get("texture_score"))
    color_score = metric_number(quality_fields.get("color_fidelity_score"))
    fidelity_score = metric_number(quality_fields.get("fidelity_score"))
    speed_seconds = metric_number(speed_fields.get("speed_actual_seconds"))
    if speed_seconds is None:
        speed_seconds = 9999.0
    uses_realesrgan = bool(output_fields.get("uses_realesrgan"))
    skipped_realesrgan = bool(output_fields.get("fast_route_skipped_realesrgan"))
    skipped_heavy = bool(output_fields.get("fast_route_skipped_protected_heavy_chain"))
    speed_pass = speed_seconds <= 20.0 and not bool(speed_fields.get("speed_risk"))
    quality_reasons: list[str] = []
    applicable_metrics: list[str] = []
    if text_score is not None:
        applicable_metrics.append("text")
    if text_score is not None and text_score < 45.0:
        quality_reasons.append(f"text_clarity_score={text_score:.2f}<45")
    if edge_score is not None:
        applicable_metrics.append("edge")
    if edge_score is None or edge_score < 45.0:
        rendered = "not_available" if edge_score is None else f"{edge_score:.2f}"
        quality_reasons.append(f"edge_quality_score={rendered}<45")
    if texture_score is not None:
        applicable_metrics.append("texture")
    if texture_score is None or texture_score < 2.0:
        rendered = "not_available" if texture_score is None else f"{texture_score:.2f}"
        quality_reasons.append(f"texture_score={rendered}<2")
    if color_score is not None:
        applicable_metrics.append("color")
    if color_score is None or color_score < 90.0:
        rendered = "not_available" if color_score is None else f"{color_score:.2f}"
        quality_reasons.append(f"color_fidelity_score={rendered}<90")
    if fidelity_score is not None:
        applicable_metrics.append("fidelity")
    if fidelity_score is None or fidelity_score < 54.0:
        rendered = "not_available" if fidelity_score is None else f"{fidelity_score:.2f}"
        quality_reasons.append(f"fidelity_score={rendered}<54")
    if bool(quality_fields.get("is_pseudo_hd")) and (text_score is None or text_score < 50.0) and (edge_score is None or edge_score < 50.0):
        quality_reasons.append("pseudo_hd_without_text_or_edge_gain")
    if not applicable_metrics:
        quality_reasons.append("no_applicable_quality_metrics")
    quality_pass = not quality_reasons
    final_pass = speed_pass and quality_pass and skipped_realesrgan and skipped_heavy and not uses_realesrgan
    return {
        "fast_route_speed_pass": bool(speed_pass),
        "fast_route_quality_pass": bool(quality_pass),
        "fast_route_final_pass": bool(final_pass),
        "fast_route_quality_grade": "B+" if final_pass else "BELOW_B_PLUS",
        "fast_route_quality_reason": "balanced_fast_quality_floor_passed" if quality_pass else "; ".join(quality_reasons),
        "fast_route_applicable_quality_metrics": applicable_metrics,
        "fast_route_speed_reason": "within_20s_fast_route_limit" if speed_pass else f"speed_actual_seconds={speed_seconds:.3f}>20",
        "fast_route_uses_realesrgan_blocker": bool(uses_realesrgan or not skipped_realesrgan),
        "fast_route_heavy_chain_skipped": bool(skipped_heavy),
    }


def classified_quality_status_fields(
    route: str,
    quality_fields: dict[str, object],
    output_fields: dict[str, object],
) -> dict[str, object]:
    unexpected_downscale = bool(output_fields.get("unexpected_downscale"))
    pseudo = bool(quality_fields.get("is_pseudo_hd"))
    halo_pass = bool(quality_fields.get("halo_ringing_pass"))
    color_score = metric_number(quality_fields.get("color_fidelity_score"))
    texture_gain = metric_number(quality_fields.get("texture_gain"))
    texture_overshoot = metric_number(quality_fields.get("texture_overshoot_ratio"))
    profile = str(quality_fields.get("image_quality_profile") or infer_image_quality_profile(route))
    portrait_route = profile in {"portrait_photo", "portrait_commercial_layout", "portrait_group"}
    portrait_context = bool(output_fields.get("portrait_context_established") or portrait_route)
    face_structure_value = quality_fields.get("face_structure_protection_pass")
    face_protection_pass = bool(face_structure_value) if isinstance(face_structure_value, bool) else bool(not portrait_route)
    product_protection_value = quality_fields.get("product_material_protection_pass")
    product_material_protection_pass = (
        bool(product_protection_value)
        if isinstance(product_protection_value, bool)
        else bool(color_score is not None and color_score >= 96.0 and halo_pass and (texture_overshoot is None or texture_overshoot <= 0.08))
    )
    background_value = quality_fields.get("background_blur_protection_pass")
    background_blur_protection_pass: bool | None = background_value if isinstance(background_value, bool) else None
    text_metric_applicable = quality_fields.get("text_metric_applicable") is True
    if profile in {"commercial_product", "commercial_brand_visual", "portrait_commercial_layout"}:
        text_gain = metric_number(quality_fields.get("primary_text_roi_gain"))
        if text_metric_applicable and text_gain is not None:
            key_gain = text_gain
            applicable_pass = quality_fields.get("commercial_text_quality_pass") is True
        else:
            key_gain = texture_gain
            edge_score = metric_number(quality_fields.get("edge_quality_score"))
            applicable_pass = bool(edge_score is not None and edge_score >= 45.0 and color_score is not None and color_score >= 90.0)
    elif profile == "knowledge_poster":
        key_gain = metric_number(quality_fields.get("knowledge_text_line_roi_gain"))
        applicable_pass = quality_fields.get("knowledge_quality_pass") is True
    else:
        key_gain = metric_number(quality_fields.get("texture_roi_gain"))
        if key_gain is None:
            key_gain = texture_gain
        applicable_pass = face_protection_pass and background_blur_protection_pass is not False
    negative_gain = bool((key_gain is not None and key_gain < -2.0) or (texture_gain is not None and texture_gain < -12.0))
    blocked_reasons: list[str] = []
    if unexpected_downscale:
        blocked_reasons.append("unexpected_downscale")
    if not route:
        blocked_reasons.append("missing_route")
    if portrait_route and not face_protection_pass:
        blocked_reasons.append("face_protection_missing")
    if portrait_route and int(quality_fields.get("face_count_filtered") or 0) <= 0:
        blocked_reasons.append("no_filtered_face_evidence")
    evidence_missing = bool(portrait_context and quality_fields.get("portrait_metric_status") != "available")
    if evidence_missing:
        blocked_reasons.append("portrait_metrics_missing")
    for protection_field, reason_code in (
        ("face_structure_protection_pass", "face_structure_protection_failed"),
        ("skin_protection_pass", "skin_protection_failed"),
        ("hair_protection_pass", "hair_protection_failed"),
        ("background_blur_protection_pass", "background_blur_protection_failed"),
        ("global_halo_ringing_pass", "global_halo_ringing_failed"),
        ("face_halo_ringing_pass", "face_halo_ringing_failed"),
        ("transparent_material_protection_pass", "transparent_material_protection_failed"),
        ("container_edge_protection_pass", "container_edge_protection_failed"),
    ):
        if portrait_route and quality_fields.get(protection_field) is False:
            blocked_reasons.append(reason_code)
    if portrait_route and quality_fields.get("clothing_hallucination_risk") is True:
        blocked_reasons.append("clothing_hallucination_risk")
    if profile in TEXT_REQUIRED_PROFILES and quality_fields.get("text_metric_status") == "missing_required_roi":
        blocked_reasons.append("critical_text_roi_missing")
    if pseudo:
        blocked_reasons.append("pseudo_hd")
    if key_gain is not None and key_gain < -2.0:
        blocked_reasons.append(f"critical_roi_negative_gain={key_gain:.2f}")
    small_text_truth_status = str(quality_fields.get("small_text_quality_status") or "not_applicable")
    blocking_small_text_truth_statuses = {
        "insufficient_gain",
        "blocked",
        "evidence_missing",
        "automatic_detection_failed",
        "boundary_unverified",
    }
    if small_text_truth_status in blocking_small_text_truth_statuses:
        blocked_reasons.append(f"small_text_{small_text_truth_status}")
    if portrait_route and quality_fields.get("small_text_roi_applicable") is True:
        if quality_fields.get("small_text_character_structure_protection_pass") is False:
            blocked_reasons.append("small_text_character_structure_failed")
        if quality_fields.get("small_text_person_roi_unchanged") is False:
            blocked_reasons.append("small_text_person_roi_intrusion")
    if bool(output_fields.get("structure_distortion_detected")):
        blocked_reasons.append("structure_or_identity_distortion")
    if blocked_reasons:
        quality_status = "blocked"
        delivery_status = "review_before_use"
        reason = ";".join(blocked_reasons)
    else:
        pass_candidate = bool(
            key_gain is not None
            and key_gain > 0.0
            and not negative_gain
            and applicable_pass
            and not pseudo
            and halo_pass
            and color_score is not None
            and color_score >= 96.0
            and background_blur_protection_pass is not False
            and small_text_truth_status not in blocking_small_text_truth_statuses
            and (product_material_protection_pass or portrait_route or profile == "knowledge_poster")
        )
        quality_status = "pass_candidate" if pass_candidate else "insufficient_gain"
        delivery_status = "review_before_use"
        reasons = []
        if key_gain is None: reasons.append("key_roi_gain=not_applicable")
        elif key_gain <= 0.0: reasons.append(f"key_roi_gain={key_gain:.2f}<=0")
        if negative_gain: reasons.append("negative_roi_or_texture_gain")
        if not applicable_pass: reasons.append("applicable_metric_floor_failed")
        if pseudo: reasons.append("pseudo_hd")
        if not halo_pass: reasons.append("halo_or_ringing_risk")
        if color_score is None: reasons.append("color_fidelity_score=not_available")
        elif color_score < 96.0: reasons.append(f"color_fidelity_score={color_score:.2f}<96")
        if background_blur_protection_pass is False: reasons.append("background_blur_protection_failed")
        if quality_fields.get("small_text_quality_status") == "insufficient_gain": reasons.append("small_text_insufficient_gain")
        if profile in {"commercial_product", "commercial_brand_visual"} and not product_material_protection_pass:
            reasons.append("product_material_protection_failed")
        reason = "quality_gate_pass_candidate" if pass_candidate else ";".join(reasons or ["insufficient_visible_gain"])
    return {
        "quality_status": quality_status,
        "delivery_status": delivery_status,
        "delivery_reason": reason,
        "quality_status_reason": reason,
        "quality_blocker_class": "evidence_missing" if evidence_missing else ("observed_risk" if blocked_reasons else "none"),
        "key_roi_positive_gain": bool(key_gain is not None and key_gain > 0.0),
        "key_roi_gain": round(key_gain, 2) if key_gain is not None else "not_applicable",
        "face_protection_pass": face_protection_pass,
        "identity_protection_pass": quality_fields.get("identity_protection_pass", "not_available"),
        "identity_protection_status": quality_fields.get("identity_protection_status", "not_applicable"),
        "product_material_protection_pass": product_material_protection_pass,
        "background_blur_protection_pass": background_blur_protection_pass if background_blur_protection_pass is not None else "not_available",
        "image_quality_profile": profile,
        "text_metric_applicable": quality_fields.get("text_metric_applicable", profile not in {"portrait_photo", "portrait_group"}),
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


def contact_sheet_labels(route: str) -> tuple[str, str, str]:
    if route == BALANCED_FAST_ROUTE:
        return "original", "balanced fast base", "balanced fast final"
    if route in KNOWLEDGE_ROUTES:
        return "original", "knowledge base", "knowledge poster final"
    if route == PORTRAIT_GROUP_SAFE_ROUTE:
        return "original", "person-preserved base", "portrait group safe final"
    if route in {PORTRAIT_PHOTO_ROUTE, PORTRAIT_COMMERCIAL_POSTER_ROUTE, PORTRAIT_COMMERCIAL_ROUTE}:
        return "original", "identity-preserved base", "portrait protected final"
    return "original", "protected SR blend", "protected SR final"


def build_contact_sheet(original: np.ndarray, blend35: np.ndarray, protected35: np.ndarray, route: str = "") -> np.ndarray:
    labels = contact_sheet_labels(route)
    rendered = [
        labeled_panel(original, labels[0], 720),
        labeled_panel(blend35, labels[1], 720),
        labeled_panel(protected35, labels[2], 720),
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


def make_contact_sheet(original: np.ndarray, blend35: np.ndarray, protected35: np.ndarray, path: Path, route: str = "") -> None:
    sheet = build_contact_sheet(original, blend35, protected35, route)
    write_image(path, sheet)


def make_contact_sheet_light(original: np.ndarray, blend35: np.ndarray, protected35: np.ndarray, path: Path, route: str = "") -> None:
    sheet = build_contact_sheet(original, blend35, protected35, route)
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
    if route == PORTRAIT_GROUP_SAFE_ROUTE:
        return [
            ("front_face", (0.42, 0.43, 0.52, 0.60)),
            ("side_face", (0.08, 0.34, 0.20, 0.52)),
            ("skin_and_hair", (0.58, 0.43, 0.70, 0.61)),
            ("clothing_texture", (0.38, 0.56, 0.58, 0.88)),
            ("background_defocus", (0.70, 0.04, 0.97, 0.30)),
            ("text_and_logo", (0.33, 0.16, 0.62, 0.34)),
        ]
    if route in {PORTRAIT_PHOTO_ROUTE, PORTRAIT_COMMERCIAL_POSTER_ROUTE, PORTRAIT_COMMERCIAL_ROUTE}:
        return [
            ("face_roi", (0.34, 0.18, 0.66, 0.52)),
            ("skin_roi", (0.38, 0.24, 0.62, 0.48)),
            ("hair_roi", (0.30, 0.08, 0.70, 0.30)),
            ("clothing_roi", (0.26, 0.48, 0.74, 0.88)),
            ("background_blur_roi", (0.72, 0.06, 0.97, 0.30)),
            ("primary_text_roi", (0.04, 0.06, 0.52, 0.30)),
            ("small_text_roi", (0.04, 0.68, 0.62, 0.92)),
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


def _confirmed_skin_mask(original_up: np.ndarray, raw_skin: np.ndarray) -> tuple[np.ndarray, dict[str, object]]:
    global _FACE_CASCADE
    gray = cv2.cvtColor(original_up, cv2.COLOR_BGR2GRAY)
    preview_width = min(640, gray.shape[1])
    scale = preview_width / gray.shape[1]
    preview = cv2.resize(gray, (preview_width, max(1, int(round(gray.shape[0] * scale)))), interpolation=cv2.INTER_AREA)
    signature = zlib.adler32(cv2.resize(preview, (64, 64), interpolation=cv2.INTER_AREA).tobytes())
    cache_key = (gray.shape[1], gray.shape[0], signature)
    cached = _FACE_REGION_CACHE.get(cache_key)
    if cached is None:
        if _FACE_CASCADE is None:
            _FACE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        detections = _FACE_CASCADE.detectMultiScale(preview, scaleFactor=1.1, minNeighbors=4, minSize=(18, 18))
        regions = [tuple(int(value) for value in item) for item in detections]
        confidence = float(np.clip(len(regions) / 3.0, 0.0, 1.0))
        cached = (regions, confidence)
        _FACE_REGION_CACHE[cache_key] = cached
    regions, face_confidence = cached
    person_region = np.zeros(gray.shape, dtype=np.uint8)
    for x, y, width, height in regions:
        x = int(round(x / scale)); y = int(round(y / scale))
        width = int(round(width / scale)); height = int(round(height / scale))
        x1 = max(0, x - width); x2 = min(gray.shape[1], x + width * 2)
        y1 = max(0, y - height); y2 = min(gray.shape[0], y + height * 4)
        person_region[y1:y2, x1:x2] = 255
    confirmed = cv2.bitwise_and(raw_skin, person_region)
    raw_ratio = float(np.mean(raw_skin > 0))
    confirmed_ratio = float(np.mean(confirmed > 0))
    overlap = confirmed_ratio / max(raw_ratio, 1e-6)
    applied = bool(confirmed_ratio >= 0.0005 and face_confidence > 0.0)
    return confirmed, {
        "skin_mask_raw_ratio": round(raw_ratio, 4),
        "skin_mask_confirmed_ratio": round(confirmed_ratio, 4),
        "skin_person_overlap_ratio": round(float(np.clip(overlap, 0.0, 1.0)), 4),
        "face_detection_confidence": round(face_confidence, 4),
        "person_detection_confidence": round(face_confidence, 4),
        "skin_protection_applied": applied,
        "skin_protection_reason": "face_region_overlap_confirmed" if applied else "warm_color_without_face_overlap_rejected",
    }


def build_protection_masks(original_up: np.ndarray) -> dict[str, np.ndarray | object]:
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

    raw_skin = (
        (ycrcb[:, :, 1] > 132)
        & (ycrcb[:, :, 1] < 178)
        & (ycrcb[:, :, 2] > 84)
        & (ycrcb[:, :, 2] < 138)
        & (s > 20)
        & (v > 80)
    ).astype(np.uint8) * 255
    raw_skin = cv2.morphologyEx(raw_skin, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8), iterations=1)
    skin, skin_fields = _confirmed_skin_mask(original_up, raw_skin)

    high_contrast_edge = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    return {
        "text_like": text_like,
        "high_sat": high_sat,
        "skin": skin,
        "skin_raw": raw_skin,
        "skin_fields": skin_fields,
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
    dark_ratio = float(np.mean(v < 58))

    metrics = {
        "skin_ratio": round(skin_ratio, 4),
        **masks["skin_fields"],
        "text_ratio": round(text_ratio, 4),
        "edge_ratio": round(edge_ratio, 4),
        "high_sat_ratio": round(high_sat_ratio, 4),
        "light_bg_ratio": round(light_bg_ratio, 4),
        "dark_ratio": round(dark_ratio, 4),
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


def analyze_beta_route(
    image_path: Path,
    original: np.ndarray,
    *,
    injected_classification: tuple[str, str, dict[str, float]] | None = None,
    injected_knowledge_fields: dict[str, object] | None = None,
    injected_face_analysis: dict[str, object] | None = None,
) -> dict[str, object]:
    """Production Beta analysis-to-route chain with injectable in-memory evidence."""
    image_type, classification_reason, metrics = injected_classification or classify_image(image_path, original)
    metrics = dict(metrics)
    knowledge_fields = dict(injected_knowledge_fields or detect_knowledge_poster(image_path, original, metrics))
    metrics.update({
        "knowledge_poster_score": knowledge_fields.get("knowledge_poster_score"),
        "knowledge_text_ratio": knowledge_fields.get("knowledge_text_ratio"),
        "knowledge_edge_ratio": knowledge_fields.get("knowledge_edge_ratio"),
        "knowledge_line_ratio": knowledge_fields.get("knowledge_line_ratio"),
    })
    if knowledge_fields.get("is_knowledge_poster") and image_type != "commercial_non_portrait":
        image_type = "commercial_non_portrait"
        classification_reason = "knowledge_poster_metrics"
    face_analysis = injected_face_analysis or detect_group_faces(original)
    route_decision = apply_realesrgan_execution_guard(
        decide_enhance_route(
            image_path,
            original,
            image_type,
            metrics,
            knowledge_fields,
            face_analysis=face_analysis,
        )
    )
    content_type, content_type_reason = infer_content_type(
        image_type,
        str(route_decision.get("enhance_route") or ""),
        {**metrics, **route_decision},
        knowledge_fields,
    )
    content_fields = content_type_fields(content_type)
    content_fields["content_type_reason"] = content_type_reason
    return {
        "image_type": image_type,
        "classification_reason": classification_reason,
        "metrics": metrics,
        "knowledge_fields": knowledge_fields,
        "face_analysis": face_analysis,
        "route_decision": route_decision,
        "content_type": content_type,
        "content_fields": content_fields,
    }


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
    subprocess_started_at = datetime.now().isoformat(timespec="milliseconds")
    subprocess_clock = time.perf_counter()
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
    command_signature = f"realesrgan-ncnn-vulkan -i <input> -o <output> -n {model} -s {scale} -f png"
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
    subprocess_finished_at = datetime.now().isoformat(timespec="milliseconds")
    subprocess_seconds = round(time.perf_counter() - subprocess_clock, 3)
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
    return {
        "returncode": completed.returncode,
        "stderr_tail": stderr_tail,
        "model_name": model,
        "subprocess_started_at": subprocess_started_at,
        "subprocess_finished_at": subprocess_finished_at,
        "subprocess_seconds": subprocess_seconds,
        "subprocess_exit_code": completed.returncode,
        "command_signature": command_signature,
    }


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
            read_started = time.perf_counter()
            original = read_image(image_path)
            per_file_timing["file_read_decode_seconds"] = round(time.perf_counter() - read_started, 3)
            analysis_started = time.perf_counter()
            analysis = analyze_beta_route(image_path, original)
            image_type = str(analysis["image_type"])
            reason = str(analysis["classification_reason"])
            metrics = analysis["metrics"]
            knowledge_fields = analysis["knowledge_fields"]
            route_decision = analysis["route_decision"]
            content_type = str(analysis["content_type"])
            content_fields = analysis["content_fields"]
            per_file_timing["route_preanalysis_seconds"] = round(time.perf_counter() - analysis_started, 3)
            base = image_path.stem
            safe_non_model_routes = {PORTRAIT_GROUP_SAFE_ROUTE, PORTRAIT_COMMERCIAL_ROUTE, PORTRAIT_COMMERCIAL_POSTER_ROUTE, PORTRAIT_PHOTO_ROUTE}
            if image_type != "commercial_non_portrait" and route_decision.get("enhance_route") not in safe_non_model_routes:
                skipped_candidate_fields = skipped_jpg95_candidate_fields(image_path, image_type, reason, metrics)
                skipped.append(
                    {
                        "file": image_path.name,
                        "input_name": image_path.name,
                        "type": image_type,
                        "reason": reason,
                        "metrics": metrics,
                        **content_fields,
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
                small_text_overview_path = unique_business_path(roi_dir / f"{base}_small_text_overview.png", run_token)
                small_text_comparison_path = unique_business_path(roi_dir / f"{base}_small_text_triptych.png", run_token)
                jpg95_candidate_path = unique_business_path(jpg95_candidate_dir / f"{base}_final_candidate_jpg95.jpg", run_token)
                light_delivery_path = unique_business_path(light_delivery_dir / f"{base}_delivery_light_jpg95.jpg", run_token)
            else:
                enhanced_path = enhanced_dir / f"{base}_safe_1080p_35protected.png"
                contact_path = contact_dir / f"{base}_contact_sheet.png"
                contact_light_path = contact_dir / f"{base}_contact_sheet_preview_q{CONTACT_SHEET_LIGHT_JPEG_QUALITY}.jpg"
                roi_evidence_path = roi_dir / f"{base}_roi_evidence.jpg"
                small_text_overview_path = roi_dir / f"{base}_small_text_overview.png"
                small_text_comparison_path = roi_dir / f"{base}_small_text_triptych.png"
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
            elif route_decision.get("enhance_route") == PORTRAIT_GROUP_SAFE_ROUTE:
                final_png, output_resolution_fields, portrait_timing = portrait_group_conservative_enhance(original, route_decision)
                per_file_timing.update(portrait_timing)
                blend35 = resize_to_match(original, final_png) if final_png is not None else original
            elif route_decision.get("enhance_route") == PORTRAIT_COMMERCIAL_ROUTE:
                final_png, output_resolution_fields, portrait_timing = portrait_group_conservative_enhance(
                    original, route_decision, route_name=PORTRAIT_COMMERCIAL_ROUTE, enhance_layout_text=True
                )
                per_file_timing.update(portrait_timing)
                blend35 = resize_to_match(original, final_png) if final_png is not None else original
            elif route_decision.get("enhance_route") == PORTRAIT_COMMERCIAL_POSTER_ROUTE:
                final_png, output_resolution_fields, portrait_timing = portrait_group_conservative_enhance(
                    original, route_decision, route_name=PORTRAIT_COMMERCIAL_POSTER_ROUTE, enhance_layout_text=True
                )
                per_file_timing.update(portrait_timing)
                blend35 = resize_to_match(original, final_png) if final_png is not None else original
            elif route_decision.get("enhance_route") == PORTRAIT_PHOTO_ROUTE:
                final_png, output_resolution_fields, portrait_timing = portrait_group_conservative_enhance(
                    original, route_decision, route_name=PORTRAIT_PHOTO_ROUTE, enhance_layout_text=False
                )
                per_file_timing.update(portrait_timing)
                blend35 = resize_to_match(original, final_png) if final_png is not None else original
            else:
                if route_decision.get("realesrgan_execution_allowed") is False:
                    raise RealEsrganProcessError(
                        f"realesrgan_blocked:{route_decision.get('realesrgan_block_reason')}",
                        "realesrgan_execution_guard",
                    )
                if exe is None:
                    raise RealEsrganProcessError("missing_realesrgan_exe", "missing_realesrgan_exe")
                if not has_model_files(tool_dir):
                    raise RealEsrganProcessError("missing_realesrgan_model_files", "missing_realesrgan_model_files")
                sr_start = time.perf_counter()
                subprocess_evidence = run_realesrgan(
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
                        "model_name": subprocess_evidence.get("model_name"),
                        "subprocess_started_at": subprocess_evidence.get("subprocess_started_at"),
                        "subprocess_finished_at": subprocess_evidence.get("subprocess_finished_at"),
                        "subprocess_seconds": subprocess_evidence.get("subprocess_seconds"),
                        "subprocess_exit_code": subprocess_evidence.get("subprocess_exit_code"),
                        "command_signature": subprocess_evidence.get("command_signature"),
                    }
                )
            per_file_timing["enhance_seconds"] = round(time.perf_counter() - enhance_start, 3)
            per_file_timing["final_stage_seconds"] = per_file_timing.get("local_detail_seconds", 0)
            output_resolution_fields.update(knowledge_fields)
            output_resolution_fields.update({
                "realesrgan_requested": route_decision.get("realesrgan_requested", False),
                "realesrgan_execution_allowed": route_decision.get("realesrgan_execution_allowed", True),
                "realesrgan_request_blocked": route_decision.get("realesrgan_request_blocked", False),
                "realesrgan_block_reason": route_decision.get("realesrgan_block_reason", "not_applicable"),
                "portrait_context_established": route_decision.get("portrait_context_established", False),
                "portrait_group_context": route_decision.get("portrait_group_context", False),
                "portrait_subject_context": route_decision.get("portrait_subject_context", False),
            })
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
                        **content_fields,
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

            small_text_started = time.perf_counter()
            final_png, small_text_fields, small_text_visuals = small_text_end_to_end_in_memory(
                original,
                final_png,
                content_type,
                source_image_id=str(image_path),
                face_analysis=route_decision,
            )
            per_file_timing["small_text_roi_seconds"] = round(time.perf_counter() - small_text_started, 3)
            small_text_overview, small_text_comparison = small_text_visuals
            small_text_fields.update({
                "small_text_overview_path": "",
                "small_text_comparison_path": "",
                "small_text_visualization_scale": "4x_same_coordinate_same_interpolation",
            })
            try:
                if small_text_overview is not None:
                    write_image(small_text_overview_path, small_text_overview)
                    small_text_fields["small_text_overview_path"] = str(small_text_overview_path)
                if small_text_comparison is not None:
                    write_image(small_text_comparison_path, small_text_comparison)
                    small_text_fields["small_text_comparison_path"] = str(small_text_comparison_path)
            except Exception as exc:
                small_text_fields["small_text_visualization_status"] = "failed"
                small_text_fields["small_text_visualization_reason"] = tail_text(exc, 180)
            else:
                small_text_fields["small_text_visualization_status"] = "available" if small_text_overview is not None else "not_applicable"

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
            route_name = str(output_resolution_fields.get("enhance_route") or route_decision.get("enhance_route") or "safe_beta_general")
            quality_score_fields = compute_safe_beta_quality_scores(
                original,
                final_png,
                route_name,
                image_quality_profile=str(content_fields["image_quality_profile"]),
                content_type=content_type,
                roi_source="automatic_detected",
                face_analysis=route_decision,
            )
            quality_score_fields.update(small_text_fields)
            quality_score_fields["primary_text_glyph_review"] = quality_score_fields.get("text_glyph_integrity_review", "not_applicable")
            small_text_detail_rows = small_text_fields.get("small_text_roi_details") or []
            applicable_small_halo = [item.get("halo_ringing_pass") for item in small_text_detail_rows if isinstance(item, dict) and isinstance(item.get("halo_ringing_pass"), bool)]
            if applicable_small_halo:
                quality_score_fields["small_text_halo_ringing_pass"] = all(applicable_small_halo)
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
                make_contact_sheet(original, blend35, final_png, contact_path, route_name)
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
                    make_contact_sheet_light(original, blend35, final_png, contact_light_path, route_name)
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
            speed_fields = speed_fields_for_route(route_name, float(per_file_timing["per_file_elapsed_seconds"]), per_file_timing)
            fast_pass_fields = fast_route_pass_fields(route_name, speed_fields, quality_score_fields, output_resolution_fields)
            status_fields = {
                "generation_status": "generated",
                **classified_quality_status_fields(route_name, quality_score_fields, output_resolution_fields),
            }
            quality_score_fields["quality_flag"] = status_fields["quality_status"]
            text_ratio = float(metrics.get("text_ratio") or 0.0)
            text_logo_applicable = route_name != PORTRAIT_PHOTO_ROUTE
            text_logo_risk = bool(text_logo_applicable and text_ratio >= JPG95_CANDIDATE_TEXT_RATIO_LIMIT)
            text_logo_fields = {
                "text_logo_risk_status": "not_applicable" if not text_logo_applicable else ("risk" if text_logo_risk else "safe"),
                "text_logo_risk_reason": (
                    "portrait_photo_without_core_text"
                    if not text_logo_applicable else
                    f"text_logo_risk: text_ratio={text_ratio:.4f} >= {JPG95_CANDIDATE_TEXT_RATIO_LIMIT:.3f}"
                    if text_logo_risk else f"text_ratio={text_ratio:.4f} < {JPG95_CANDIDATE_TEXT_RATIO_LIMIT:.3f}"
                ),
                "text_ratio": round(text_ratio, 4),
                "text_logo_risk_threshold": JPG95_CANDIDATE_TEXT_RATIO_LIMIT,
            }
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
                    **content_fields,
                    "skin_mask_raw_ratio": metrics.get("skin_mask_raw_ratio"),
                    "skin_mask_confirmed_ratio": metrics.get("skin_mask_confirmed_ratio"),
                    "skin_person_overlap_ratio": metrics.get("skin_person_overlap_ratio"),
                    "face_detection_confidence": metrics.get("face_detection_confidence"),
                    "person_detection_confidence": metrics.get("person_detection_confidence"),
                    "skin_protection_applied": metrics.get("skin_protection_applied"),
                    "skin_protection_reason": metrics.get("skin_protection_reason"),
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
                    "resolution_route": output_resolution_fields.get("resolution_route", route_decision.get("target_profile")),
                    "scale_factor": output_resolution_fields.get("scale_factor", route_decision.get("input_to_output_scale_ratio")),
                    "unexpected_downscale": output_resolution_fields.get("unexpected_downscale", False),
                    "enhance_route": output_resolution_fields.get("enhance_route", "safe_beta_general"),
                    "route_decision_reason": output_resolution_fields.get("route_decision_reason", route_decision.get("route_decision_reason")),
                    "already_1080p_or_near_1080p": output_resolution_fields.get("already_1080p_or_near_1080p", route_decision.get("already_1080p_or_near_1080p")),
                    "input_to_output_scale_ratio": output_resolution_fields.get("input_to_output_scale_ratio", route_decision.get("input_to_output_scale_ratio")),
                    "realesrgan_used": output_resolution_fields.get("realesrgan_used"),
                    "uses_realesrgan": output_resolution_fields.get("uses_realesrgan", output_resolution_fields.get("realesrgan_used")),
                    "model_name": output_resolution_fields.get("model_name", "not_applicable"),
                    "subprocess_started_at": output_resolution_fields.get("subprocess_started_at", "not_applicable"),
                    "subprocess_finished_at": output_resolution_fields.get("subprocess_finished_at", "not_applicable"),
                    "subprocess_seconds": output_resolution_fields.get("subprocess_seconds", "not_applicable"),
                    "subprocess_exit_code": output_resolution_fields.get("subprocess_exit_code", "not_applicable"),
                    "command_signature": output_resolution_fields.get("command_signature", "not_applicable"),
                    "realesrgan_requested": output_resolution_fields.get("realesrgan_requested", False),
                    "realesrgan_execution_allowed": output_resolution_fields.get("realesrgan_execution_allowed", True),
                    "realesrgan_request_blocked": output_resolution_fields.get("realesrgan_request_blocked", False),
                    "realesrgan_block_reason": output_resolution_fields.get("realesrgan_block_reason", "not_applicable"),
                    "portrait_context_established": output_resolution_fields.get("portrait_context_established", False),
                    "portrait_group_context": output_resolution_fields.get("portrait_group_context", False),
                    "portrait_subject_context": output_resolution_fields.get("portrait_subject_context", False),
                    "fast_route_skipped_realesrgan": output_resolution_fields.get("fast_route_skipped_realesrgan"),
                    "fast_route_skipped_protected_heavy_chain": output_resolution_fields.get("fast_route_skipped_protected_heavy_chain"),
                    "fast_quality_level": output_resolution_fields.get("fast_quality_level", per_file_timing.get("fast_quality_level")),
                    "portrait_group_face_count": output_resolution_fields.get("portrait_group_face_count"),
                    "face_protection_applied": output_resolution_fields.get("face_protection_applied"),
                    "skin_protection_applied": output_resolution_fields.get("skin_protection_applied", metrics.get("skin_protection_applied")),
                    "hair_protection_applied": output_resolution_fields.get("hair_protection_applied"),
                    "clothing_protection_applied": output_resolution_fields.get("clothing_protection_applied"),
                    "background_defocus_protection_applied": output_resolution_fields.get("background_defocus_protection_applied"),
                    "portrait_detail_policy": output_resolution_fields.get("portrait_detail_policy"),
                    "face_candidate_count_raw": output_resolution_fields.get("face_candidate_count_raw", route_decision.get("face_candidate_count_raw")),
                    "face_candidate_count_filtered": output_resolution_fields.get("face_candidate_count_filtered", route_decision.get("face_candidate_count_filtered")),
                    "face_area_ratio": output_resolution_fields.get("face_area_ratio", route_decision.get("group_face_area_ratio")),
                    "face_count_raw": route_decision.get("face_candidate_count_raw"),
                    "face_count_filtered": route_decision.get("face_candidate_count_filtered"),
                    "face_candidates": route_decision.get("face_candidates") or [],
                    "route_evidence": route_decision.get("route_evidence") or {},
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
                    **text_logo_fields,
                    **status_fields,
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
    sync_status_fields = resolve_sync_summary_status(processed, str(consistency_fields["diagnostics_consistency"]))
    resolved_content_types = list(dict.fromkeys(str(item.get("content_type") or "unknown") for item in processed))
    summary = {
        "status": "ok" if processed else "blocked",
        "generation_status": "generated" if processed else "failed",
        "quality_status": sync_status_fields["quality_status"],
        "delivery_status": "review_before_use" if processed else "blocked",
        "verification_result": sync_status_fields["verification_result"],
        "small_text_sync_blocked": sync_status_fields["small_text_sync_blocked"],
        "small_text_blocking_statuses": sync_status_fields["small_text_blocking_statuses"],
        "content_type": resolved_content_types[0] if len(resolved_content_types) == 1 else "mixed" if resolved_content_types else "unknown",
        "content_types": resolved_content_types,
        "small_text_stage": "small_text_roi_safe_enhance",
        "small_text_detected_count": sum(int(item.get("small_text_detected_count") or 0) for item in processed),
        "small_text_enhanced_count": sum(int(item.get("small_text_enhanced_count") or 0) for item in processed),
        "small_text_reverted_count": sum(int(item.get("small_text_reverted_count") or 0) for item in processed),
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
