"""Conservative, content-preserving automatic color correction.

The engine changes only existing pixels.  It does not resize, crop, synthesize,
or replace image content.  A local luminance mask is used when a bright
background and a darker foreground/person region are detected.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from PIL import Image, ImageOps

from .color_core_v2 import (
    COLOR_CORE_V2_VERSION,
    GLOBAL_ROUTE_NAME,
    LOCAL_ROUTE_NAME,
    run_global_recovery,
    run_local_recovery,
)
from .executors import apply_safe_white_balance

COLOR_CORRECTION_ENGINE_VERSION = "hdde.auto-color-correction.v7-color-core-v2"
MAX_PIXELS = 80_000_000


@dataclass(frozen=True)
class ColorCorrectionResult:
    output_path: str
    source_sha256: str
    output_sha256: str
    source_format: str
    output_format: str
    width: int
    height: int
    source_size_bytes: int
    output_size_bytes: int
    processing_time_ms: int
    analysis: dict[str, Any]
    before_metrics: dict[str, float]
    after_metrics: dict[str, float]
    detected_issues: list[str]
    improvements: list[str]
    review_points: list[str]
    applied_actions: list[str]
    parameters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_version": COLOR_CORRECTION_ENGINE_VERSION,
            "output_path": self.output_path,
            "source_sha256": self.source_sha256,
            "output_sha256": self.output_sha256,
            "source_format": self.source_format,
            "output_format": self.output_format,
            "width": self.width,
            "height": self.height,
            "source_size_bytes": self.source_size_bytes,
            "output_size_bytes": self.output_size_bytes,
            "processing_time_ms": self.processing_time_ms,
            "analysis": dict(self.analysis),
            "before_metrics": dict(self.before_metrics),
            "after_metrics": dict(self.after_metrics),
            "detected_issues": list(self.detected_issues),
            "improvements": list(self.improvements),
            "review_points": list(self.review_points),
            "applied_actions": list(self.applied_actions),
            "parameters": dict(self.parameters),
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _masked_mean(values: np.ndarray, mask: np.ndarray | None) -> float:
    if mask is None or float(mask.sum()) <= 1.0:
        return float(values.mean())
    return float((values * mask).sum() / mask.sum())


def _metrics(
    rgb: np.ndarray,
    focus_mask: np.ndarray | None = None,
    background_mask: np.ndarray | None = None,
) -> dict[str, float]:
    array = rgb.astype(np.float32)
    luminance = 0.2126 * array[..., 0] + 0.7152 * array[..., 1] + 0.0722 * array[..., 2]
    maximum = array.max(axis=2)
    minimum = array.min(axis=2)
    saturation = np.divide(maximum - minimum, np.maximum(maximum, 1.0))
    percentiles = np.percentile(luminance, [1, 10, 50, 90, 99])
    local_base = cv2.GaussianBlur(luminance, (0, 0), sigmaX=3.0)
    local_contrast = float(np.mean(np.abs(luminance - local_base)))
    return {
        "mean_luminance": round(float(luminance.mean()), 2),
        "foreground_luminance": round(_masked_mean(luminance, focus_mask), 2),
        "background_luminance": round(_masked_mean(luminance, background_mask), 2),
        "shadow_ratio": round(float((luminance < 42).mean()), 4),
        "highlight_ratio": round(float((luminance > 242).mean()), 4),
        "mean_saturation": round(float(saturation.mean()), 4),
        "black_point": round(float(percentiles[0]), 2),
        "shadow_point": round(float(percentiles[1]), 2),
        "midtone_point": round(float(percentiles[2]), 2),
        "highlight_point": round(float(percentiles[3]), 2),
        "white_point": round(float(percentiles[4]), 2),
        "dynamic_range": round(float(percentiles[4] - percentiles[0]), 2),
        "local_contrast": round(local_contrast, 3),
        "red_mean": round(float(array[..., 0].mean()), 2),
        "green_mean": round(float(array[..., 1].mean()), 2),
        "blue_mean": round(float(array[..., 2].mean()), 2),
    }


def _soft_mask(binary: np.ndarray, radius: int) -> np.ndarray:
    mask = np.clip(binary.astype(np.float32), 0.0, 1.0)
    if radius <= 0:
        return mask
    kernel = max(3, radius * 2 + 1)
    if kernel % 2 == 0:
        kernel += 1
    return cv2.GaussianBlur(mask, (kernel, kernel), 0)


def _detect_faces(rgb: np.ndarray) -> list[tuple[int, int, int, int]]:
    height, width = rgb.shape[:2]
    scale = min(1.0, 960.0 / max(width, height))
    preview = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else rgb
    gray = cv2.cvtColor(preview, cv2.COLOR_RGB2GRAY)
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    if cascade.empty():
        return []
    detected = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(28, 28))
    return [
        (
            int(round(x / scale)),
            int(round(y / scale)),
            int(round(w / scale)),
            int(round(h / scale)),
        )
        for x, y, w, h in detected
    ]


def _box_iou(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    x1 = max(lx, rx)
    y1 = max(ly, ry)
    x2 = min(lx + lw, rx + rw)
    y2 = min(ly + lh, ry + rh)
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = lw * lh + rw * rh - intersection
    return float(intersection / max(union, 1))


def _detect_local_faces(
    rgb: np.ndarray,
    fallback_faces: list[tuple[int, int, int, int]],
) -> list[tuple[int, int, int, int]]:
    """Find reliable local-executor anchors without changing D-01 perception."""
    height, width = rgb.shape[:2]
    scale = min(1.0, 960.0 / max(width, height))
    preview = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else rgb
    gray = cv2.cvtColor(preview, cv2.COLOR_RGB2GRAY)
    enhanced = cv2.createCLAHE(clipLimit=2.8, tileGridSize=(8, 8)).apply(gray)

    def detect(cascade_name: str, include_mirror: bool = False) -> list[tuple[int, int, int, int]]:
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + cascade_name)
        if cascade.empty():
            return []
        found: list[tuple[int, int, int, int]] = []
        variants = [(enhanced, False)]
        if include_mirror:
            variants.append((cv2.flip(enhanced, 1), True))
        for variant, mirrored in variants:
            detected = cascade.detectMultiScale(
                variant,
                scaleFactor=1.06,
                minNeighbors=4,
                minSize=(36, 36),
            )
            for x, y, w, h in detected:
                if mirrored:
                    x = variant.shape[1] - x - w
                found.append(
                    (
                        int(round(x / scale)),
                        int(round(y / scale)),
                        int(round(w / scale)),
                        int(round(h / scale)),
                    )
                )
        return found

    frontal = detect("haarcascade_frontalface_alt2.xml")
    profiles = detect("haarcascade_profileface.xml", include_mirror=True)
    candidates = frontal + profiles + list(fallback_faces)
    minimum_area = float(height * width) * 0.007
    reliable: list[tuple[int, int, int, int]] = []
    for candidate in candidates:
        _, _, w, h = candidate
        if w * h < minimum_area:
            continue
        peer_groups = (frontal, profiles, fallback_faces)
        agreements = sum(
            1
            for group in peer_groups
            if any(peer != candidate and _box_iou(candidate, peer) >= 0.22 for peer in group)
        )
        if agreements >= 1:
            reliable.append(candidate)

    reliable.sort(key=lambda box: box[2] * box[3], reverse=True)
    selected: list[tuple[int, int, int, int]] = []
    for candidate in reliable:
        if any(_box_iou(candidate, existing) >= 0.35 for existing in selected):
            continue
        selected.append(candidate)
    return selected[:6]


def _local_person_masks(
    shape: tuple[int, int],
    faces: list[tuple[int, int, int, int]],
) -> tuple[np.ndarray, np.ndarray]:
    height, width = shape
    face_binary = np.zeros((height, width), dtype=np.float32)
    person_binary = np.zeros((height, width), dtype=np.float32)
    for x, y, w, h in faces:
        cv2.ellipse(
            face_binary,
            (int(x + w * 0.5), int(y + h * 0.53)),
            (max(1, int(w * 0.58)), max(1, int(h * 0.68))),
            0,
            0,
            360,
            1.0,
            -1,
        )
        cv2.ellipse(
            person_binary,
            (int(x + w * 0.5), int(min(height - 1, y + h * 1.58))),
            (max(1, int(w * 1.02)), max(1, int(h * 1.76))),
            0,
            0,
            360,
            1.0,
            -1,
        )
    radius = max(5, int(min(width, height) * 0.018))
    face = _soft_mask(face_binary, max(3, radius // 2))
    person = _soft_mask(np.maximum(person_binary, face_binary), radius)
    return np.clip(face, 0.0, 1.0), np.clip(person, 0.0, 1.0)


def _apply_local_person_correction(
    pre_local_rgb: np.ndarray,
    faces: list[tuple[int, int, int, int]],
    perception: dict[str, Any],
    strong_screen_mask: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any], dict[str, Any]]:
    """Apply the D-03 local layer, or return the pre-local pixels unchanged."""
    decision = str(perception.get("processing_decision") or "")
    if decision != "LOCAL_REQUIRED":
        return pre_local_rgb.astype(np.uint8).copy(), {
            "mode": "not_triggered",
            "strength": 0.0,
        }, {
            "local_executor_applied": False,
            "local_execution": "not_triggered",
            "local_output_policy": str(perception.get("output_policy") or decision),
            "local_rollback_applied": False,
            "local_face_count": 0,
        }
    if not faces:
        return pre_local_rgb.astype(np.uint8).copy(), {
            "mode": "insufficient_person_evidence",
            "strength": 0.0,
        }, {
            "local_executor_applied": False,
            "local_execution": "blocked_insufficient_person_evidence",
            "local_output_policy": str(perception.get("output_policy") or decision),
            "local_rollback_applied": True,
            "local_face_count": 0,
        }

    source = pre_local_rgb.astype(np.uint8)
    lab = cv2.cvtColor(source, cv2.COLOR_RGB2LAB).astype(np.float32)
    lightness = lab[..., 0]
    face_mask, person_mask = _local_person_masks(source.shape[:2], faces)
    face_core = face_mask >= 0.55
    if int(face_core.sum()) < 64:
        return source.copy(), {"mode": "insufficient_face_area", "strength": 0.0}, {
            "local_executor_applied": False,
            "local_execution": "blocked_insufficient_person_evidence",
            "local_output_policy": str(perception.get("output_policy") or decision),
            "local_rollback_applied": True,
            "local_face_count": len(faces),
        }

    local_contamination = bool((perception.get("person") or {}).get("local_light_contamination"))
    before_face_l = float(np.median(lightness[face_core]))
    source_float = source.astype(np.float32)

    if local_contamination:
        b_axis = lab[..., 2] - 128.0
        blue_excess = np.clip((-b_axis - 4.0) / 34.0, 0.0, 1.0)
        luminance_gate = np.clip((lightness - 18.0) / 42.0, 0.20, 1.0)
        screen_protection = np.clip(strong_screen_mask * (1.0 - face_mask), 0.0, 1.0)
        target_mask = person_mask * blue_excess * luminance_gate
        target_mask *= np.clip(1.0 - screen_protection * 0.995, 0.0, 1.0)
        target_mask = cv2.GaussianBlur(
            target_mask,
            (0, 0),
            sigmaX=max(1.5, min(source.shape[:2]) * 0.004),
        )
        target_mask = np.clip(target_mask * person_mask, 0.0, 1.0)
        target_core = target_mask >= 0.18
        if int(target_core.sum()) < 64:
            return source.copy(), {"mode": "led_local_contamination", "strength": 0.0}, {
                "local_executor_applied": False,
                "local_execution": "blocked_insufficient_contamination_evidence",
                "local_output_policy": str(perception.get("output_policy") or decision),
                "local_rollback_applied": True,
                "local_face_count": len(faces),
            }
        pollution_before = float(np.median(b_axis[target_core]))
        correction = np.clip((-8.0 - b_axis) * 0.86, 0.0, 24.0)
        corrected_lab = lab.copy()
        corrected_lab[..., 2] = np.clip(corrected_lab[..., 2] + correction, 0.0, 255.0)
        a_axis = lab[..., 1] - 128.0
        reference_skin = face_core & (b_axis >= 2.0) & (b_axis <= 24.0)
        if int(reference_skin.sum()) >= 64:
            reference_a = float(np.median(a_axis[reference_skin]))
            a_correction = np.clip((reference_a - a_axis) * 0.25, -5.0, 3.0) * face_mask
            corrected_lab[..., 1] = np.clip(corrected_lab[..., 1] + a_correction, 0.0, 255.0)
        else:
            reference_a = None
        converted = cv2.cvtColor(corrected_lab.astype(np.uint8), cv2.COLOR_LAB2RGB).astype(np.float32)
        candidate = np.clip(
            source_float * (1.0 - target_mask[..., None]) + converted * target_mask[..., None],
            0.0,
            255.0,
        ).astype(np.uint8)
        candidate_lab = cv2.cvtColor(candidate, cv2.COLOR_RGB2LAB).astype(np.float32)
        pollution_after = float(np.median(candidate_lab[..., 2][target_core] - 128.0))
        mode = "led_local_contamination"
        strength = float(np.clip(np.mean((correction * target_mask)[target_core]) / 22.0, 0.0, 1.0))
        target_gain = pollution_after - pollution_before
        safe_gain_ceiling = float(np.clip((-pollution_before - 8.0) * 0.90, 9.0, 24.0))
        local_quality_ok = bool(3.0 <= target_gain <= safe_gain_ceiling and pollution_after <= -2.0)
        target_before = pollution_before
        target_after = pollution_after
    else:
        face_need = float(np.clip((102.0 - before_face_l) / 32.0, 0.0, 1.0))
        exposure_gain = float(np.clip(10.0 + 13.0 * face_need, 10.0, 23.0))
        body_only = np.clip(person_mask - face_mask * 0.55, 0.0, 1.0)
        target_mask = np.clip(face_mask * 0.94 + body_only * 0.52, 0.0, 1.0)
        target_mask *= np.clip(1.0 - strong_screen_mask * 0.985, 0.0, 1.0)
        black_gate = np.clip((lightness - 13.0) / 42.0, 0.0, 1.0)
        highlight_gate = np.clip((218.0 - lightness) / 72.0, 0.0, 1.0)
        midtone_weight = np.clip((170.0 - lightness) / 105.0, 0.20, 1.0)
        lift = exposure_gain * black_gate * highlight_gate * midtone_weight
        corrected_lab = lab.copy()
        corrected_lab[..., 0] = np.clip(corrected_lab[..., 0] + lift, 0.0, 255.0)
        converted = cv2.cvtColor(corrected_lab.astype(np.uint8), cv2.COLOR_LAB2RGB).astype(np.float32)
        candidate = np.clip(
            source_float * (1.0 - target_mask[..., None]) + converted * target_mask[..., None],
            0.0,
            255.0,
        ).astype(np.uint8)
        candidate_lab = cv2.cvtColor(candidate, cv2.COLOR_RGB2LAB).astype(np.float32)
        after_face_l = float(np.median(candidate_lab[..., 0][face_core]))
        mode = "local_person_exposure"
        strength = float(np.clip(exposure_gain / 23.0, 0.0, 1.0))
        target_gain = after_face_l - before_face_l
        local_quality_ok = bool(6.0 <= target_gain <= 22.0)
        target_before = before_face_l
        target_after = after_face_l

    candidate[target_mask <= 0.01] = source[target_mask <= 0.01]
    delta = np.abs(candidate.astype(np.float32) - source_float).mean(axis=2)
    non_target = target_mask <= 0.01
    non_target_mae = float(delta[non_target].mean()) if non_target.any() else 0.0
    non_target_p99 = float(np.percentile(delta[non_target], 99)) if non_target.any() else 0.0
    transition = (person_mask > 0.02) & (person_mask < 0.35)
    transition_p99 = float(np.percentile(delta[transition], 99)) if transition.any() else 0.0
    delta_gradient = np.maximum(
        np.abs(cv2.Sobel(delta, cv2.CV_32F, 1, 0, ksize=3)) / 4.0,
        np.abs(cv2.Sobel(delta, cv2.CV_32F, 0, 1, ksize=3)) / 4.0,
    )
    transition_gradient_p99 = (
        float(np.percentile(delta_gradient[transition], 99)) if transition.any() else 0.0
    )
    screen_region = (strong_screen_mask >= 0.35) & (person_mask <= 0.08)
    screen_mae = float(delta[screen_region].mean()) if screen_region.any() else 0.0
    highlight_before = float((_luminance(source) > 242.0).mean())
    highlight_after = float((_luminance(candidate) > 242.0).mean())
    drift_ok = bool(
        non_target_mae <= 0.08
        and non_target_p99 <= 0.75
        and screen_mae <= 0.10
        and highlight_after <= highlight_before + 0.002
    )
    blend_ok = bool(transition_gradient_p99 <= 4.0)
    accepted = bool(local_quality_ok and drift_ok and blend_ok)
    final = candidate if accepted else source.copy()
    return final, {
        "mode": mode,
        "strength": round(strength, 4),
        "target_before": round(target_before, 3),
        "target_after": round(target_after, 3),
        "target_gain": round(target_gain, 3),
        "reference_skin_lab_a": round(reference_a, 3) if local_contamination and reference_a is not None else None,
        "non_target_mae": round(non_target_mae, 4),
        "non_target_p99": round(non_target_p99, 4),
        "transition_delta_p99": round(transition_p99, 4),
        "transition_gradient_p99": round(transition_gradient_p99, 4),
        "screen_mae": round(screen_mae, 4),
        "highlight_ratio_before": round(highlight_before, 5),
        "highlight_ratio_after": round(highlight_after, 5),
        "quality_gate": local_quality_ok,
        "non_target_drift_gate": drift_ok,
        "blend_gate": blend_ok,
    }, {
        "local_executor_applied": accepted,
        "local_execution": mode if accepted else f"blocked_{mode}",
        "local_output_policy": "LOCAL_CORRECTED" if accepted else str(perception.get("output_policy") or decision),
        "local_rollback_applied": not accepted,
        "local_face_count": len(faces),
        "local_target_quality_pass": local_quality_ok,
        "local_non_target_drift_pass": drift_ok,
        "local_blend_quality_pass": blend_ok,
    }


def _scene_masks(
    rgb: np.ndarray,
    faces: list[tuple[int, int, int, int]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    height, width = rgb.shape[:2]
    luminance = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    yy, xx = np.mgrid[0:height, 0:width]
    center_prior = np.exp(-(((xx - width * 0.5) / max(width * 0.42, 1)) ** 2 + ((yy - height * 0.57) / max(height * 0.52, 1)) ** 2))
    upper_scene = yy < height * 0.66
    bright_threshold = max(145.0, float(np.percentile(luminance[upper_scene], 72)))
    bright_seed = upper_scene & (luminance >= bright_threshold)

    face_mask = np.zeros((height, width), dtype=np.float32)
    person_mask = np.zeros((height, width), dtype=np.float32)
    for x, y, w, h in faces:
        cv2.ellipse(
            face_mask,
            (int(x + w * 0.5), int(y + h * 0.52)),
            (max(1, int(w * 0.58)), max(1, int(h * 0.66))),
            0,
            0,
            360,
            1.0,
            -1,
        )
        cv2.ellipse(
            person_mask,
            (int(x + w * 0.5), int(min(height - 1, y + h * 1.72))),
            (max(1, int(w * 1.18)), max(1, int(h * 2.08))),
            0,
            0,
            360,
            1.0,
            -1,
        )

    mask_radius = max(3, int(min(width, height) * 0.012))
    face_soft = _soft_mask(face_mask, max(3, int(mask_radius * 0.65)))
    person_soft = _soft_mask(person_mask, mask_radius)
    background_mask = _soft_mask(bright_seed.astype(np.float32), max(3, int(mask_radius * 1.3)))
    background_mask *= np.clip(1.0 - person_soft * 0.96, 0.0, 1.0)

    background_luminance = _masked_mean(luminance, background_mask)
    person_luminance = _masked_mean(luminance, person_soft) if faces else float(np.percentile(luminance, 42))
    contrast = background_luminance - person_luminance
    shadow_threshold = min(150.0, background_luminance - 15.0)
    pixel_mask = (luminance < shadow_threshold).astype(np.float32) * center_prior.astype(np.float32)
    pixel_mask *= (luminance < 220).astype(np.float32)

    bright_background_evidence = float(bright_seed.mean()) >= 0.16
    non_face_backlight_evidence = bool(bright_background_evidence and float(np.median(luminance)) >= 160.0)
    reliable_backlight = bool(
        contrast >= 18.0
        and background_luminance >= 145.0
        and bright_background_evidence
        and (faces or non_face_backlight_evidence)
    )
    if reliable_backlight:
        combined = np.maximum(pixel_mask * 0.48, person_soft)
        combined = _soft_mask(combined, mask_radius)
    else:
        combined = person_soft if faces and person_luminance < 112.0 else np.zeros((height, width), dtype=np.float32)
    combined *= np.clip((232.0 - luminance) / 75.0, 0.0, 1.0)
    combined *= np.clip(1.0 - background_mask * 0.92, 0.0, 1.0)
    return np.clip(combined, 0.0, 1.0), np.clip(background_mask, 0.0, 1.0), face_soft, {
        "face_count": len(faces),
        "background_luminance": round(background_luminance, 2),
        "foreground_luminance": round(person_luminance, 2),
        "backlight_contrast": round(contrast, 2),
        "meeting_backlight_detected": reliable_backlight,
        "local_foreground_coverage": round(float((combined > 0.1).mean()), 4),
        "highlight_background_coverage": round(float((background_mask > 0.1).mean()), 4),
    }


def _color_region_features(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    hsv = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
    saturation = hsv[..., 1] / 255.0
    value = hsv[..., 2] / 255.0
    strong_binary = (saturation >= 0.38) & (value >= 0.18) & (value <= 0.98)
    height, width = saturation.shape
    yy, xx = np.mgrid[0:height, 0:width]
    upper_scene = yy < height * 0.72
    center_scene = np.exp(
        -(
            ((xx - width * 0.5) / max(width * 0.48, 1)) ** 2
            + ((yy - height * 0.46) / max(height * 0.48, 1)) ** 2
        )
    )
    radius = max(3, int(min(width, height) * 0.008))
    strong_mask = _soft_mask(strong_binary.astype(np.float32), radius)
    screen_mask = _soft_mask(
        (strong_binary & upper_scene).astype(np.float32) * center_scene.astype(np.float32),
        max(3, int(radius * 1.4)),
    )
    strong_saturation = float(saturation[strong_binary].mean()) if strong_binary.any() else 0.0
    hue = hsv[..., 0]
    blue_binary = strong_binary & (hue >= 90.0) & (hue <= 135.0)
    warm_binary = strong_binary & ((hue <= 30.0) | (hue >= 170.0))
    red_binary = strong_binary & ((hue <= 12.0) | (hue >= 170.0))
    return np.clip(strong_mask, 0.0, 1.0), np.clip(screen_mask, 0.0, 1.0), {
        "strong_color_coverage": round(float(strong_binary.mean()), 4),
        "upper_strong_color_coverage": round(float((strong_binary & upper_scene).mean()), 4),
        "strong_color_saturation": round(strong_saturation, 4),
        "blue_color_coverage": round(float(blue_binary.mean()), 4),
        "upper_blue_color_coverage": round(float((blue_binary & upper_scene).mean()), 4),
        "warm_color_coverage": round(float(warm_binary.mean()), 4),
        "red_color_coverage": round(float(red_binary.mean()), 4),
    }


def _perceptual_decision(
    rgb: np.ndarray,
    faces: list[tuple[int, int, int, int]],
    face_mask: np.ndarray,
    before_metrics: dict[str, float],
    scene_analysis: dict[str, Any],
    color_features: dict[str, float],
    low_key_design: bool,
) -> dict[str, Any]:
    """Describe error, scope, protection, and treatment value before editing pixels.

    The decision is based on independent spatial evidence rather than a single
    whole-image channel average.  It intentionally stops at a compact set of
    facts needed by the existing correction strategies.
    """

    array = rgb.astype(np.uint8)
    hsv = cv2.cvtColor(array, cv2.COLOR_RGB2HSV).astype(np.float32)
    lab = cv2.cvtColor(array, cv2.COLOR_RGB2LAB).astype(np.float32)
    luminance = _luminance(array)
    saturation = hsv[..., 1] / 255.0
    value = hsv[..., 2] / 255.0
    neutral = (saturation < 0.18) & (luminance > 38.0) & (luminance < 238.0)
    neutral_ratio = float(neutral.mean())
    neutral_a = float(np.median(lab[..., 1][neutral]) - 128.0) if neutral.any() else 0.0
    neutral_b = float(np.median(lab[..., 2][neutral]) - 128.0) if neutral.any() else 0.0

    height, width = neutral.shape
    neutral_cells: list[dict[str, float]] = []
    for row in range(3):
        for column in range(3):
            y0, y1 = row * height // 3, (row + 1) * height // 3
            x0, x1 = column * width // 3, (column + 1) * width // 3
            cell_mask = neutral[y0:y1, x0:x1]
            if int(cell_mask.sum()) < max(20, int(cell_mask.size * 0.002)):
                continue
            cell_lab = lab[y0:y1, x0:x1]
            neutral_cells.append(
                {
                    "row": row,
                    "column": column,
                    "a": round(float(np.median(cell_lab[..., 1][cell_mask]) - 128.0), 3),
                    "b": round(float(np.median(cell_lab[..., 2][cell_mask]) - 128.0), 3),
                }
            )

    warm_cells = sum(float(cell["b"]) >= 3.0 for cell in neutral_cells)
    cool_cells = sum(float(cell["b"]) <= -2.5 for cell in neutral_cells)
    cell_b_values = [float(cell["b"]) for cell in neutral_cells]
    mixed_light = bool(
        len(neutral_cells) >= 5
        and warm_cells >= 2
        and cool_cells >= 2
        and max(cell_b_values) - min(cell_b_values) >= 6.0
    )

    strong_coverage = float(color_features["strong_color_coverage"])
    upper_strong = float(color_features["upper_strong_color_coverage"])
    blue_coverage = float(color_features["blue_color_coverage"])
    upper_blue = float(color_features["upper_blue_color_coverage"])
    warm_coverage = float(color_features["warm_color_coverage"])
    red_coverage = float(color_features["red_color_coverage"])
    mixed_light = bool(
        mixed_light
        or (
            strong_coverage >= 0.30
            and blue_coverage >= 0.08
            and warm_coverage >= 0.08
            and blue_coverage / max(strong_coverage, 0.001) >= 0.18
            and warm_coverage / max(strong_coverage, 0.001) >= 0.18
        )
    )
    strong_binary = (saturation >= 0.38) & (value >= 0.18) & (value <= 0.98)
    face_region = face_mask > 0.2
    face_coverage = float(face_region.mean())
    face_skin_fraction = 0.0
    face_strong_overlap = 0.0
    face_luminance = 0.0
    face_a = 0.0
    face_b = 0.0
    if face_region.any():
        lab_a = lab[..., 1] - 128.0
        lab_b = lab[..., 2] - 128.0
        skin_candidate = (
            (lab_a > 4.0)
            & (lab_a < 30.0)
            & (lab_b > 2.0)
            & (lab_b < 35.0)
            & (luminance > 18.0)
            & (luminance < 235.0)
        )
        face_skin_fraction = float(skin_candidate[face_region].mean())
        face_strong_overlap = float(strong_binary[face_region].mean())
        face_luminance = float(luminance[face_region].mean())
        face_a = float(np.median(lab_a[face_region]))
        face_b = float(np.median(lab_b[face_region]))
    person_present = bool(
        faces
        and face_coverage >= 0.0005
        and (face_skin_fraction >= 0.10 or (strong_coverage < 0.08 and face_strong_overlap < 0.08))
    )

    auditorium_depth = bool(
        not person_present
        and strong_coverage >= 0.14
        and upper_strong >= 0.08
        and float(before_metrics["shadow_ratio"]) >= 0.18
        and float(before_metrics["mean_luminance"]) < 100.0
    )
    probable_screen = bool(
        auditorium_depth
        or (person_present and blue_coverage >= 0.10 and upper_blue >= 0.08)
    )
    strong_local_light = bool(probable_screen and person_present and not mixed_light)
    dominant_product_color = max(red_coverage, blue_coverage) / max(strong_coverage, 0.001)
    probable_product = bool(
        not person_present
        and not auditorium_depth
        and 0.10 <= strong_coverage <= 0.38
        and dominant_product_color >= 0.65
    )
    legitimate_warm = bool(
        strong_coverage >= 0.50
        and warm_coverage / max(strong_coverage, 0.001) >= 0.72
        and neutral_b >= 4.0
        and not mixed_light
    )
    legitimate_dark = bool(
        float(before_metrics["mean_luminance"]) < 35.0
        and float(before_metrics["shadow_ratio"]) >= 0.75
        and float(before_metrics["highlight_ratio"]) < 0.015
        and float(before_metrics["white_point"]) < 115.0
    )
    dark_material = bool(
        not person_present
        and 90.0 <= float(before_metrics["mean_luminance"]) <= 145.0
        and float(before_metrics["shadow_ratio"]) >= 0.20
        and float(before_metrics["dynamic_range"]) >= 200.0
        and float(before_metrics["mean_saturation"]) < 0.12
    )
    if low_key_design:
        legitimate_dark = True

    highlight_ratio = float(before_metrics["highlight_ratio"])
    if highlight_ratio >= 0.08 or (
        float(before_metrics["mean_luminance"]) >= 190.0
        and float(before_metrics["white_point"]) >= 250.0
    ):
        highlight_risk = "high"
    elif highlight_ratio >= 0.04:
        highlight_risk = "medium"
    else:
        highlight_risk = "low"

    local_subject_under = bool(
        person_present
        and not legitimate_dark
        and float(before_metrics["mean_luminance"]) >= 90.0
        and face_luminance <= min(95.0, float(before_metrics["mean_luminance"]) - 18.0)
        and float(scene_analysis["background_luminance"]) - face_luminance >= 55.0
    )
    local_foreground_under = bool(
        not person_present
        and not probable_product
        and bool(scene_analysis["meeting_backlight_detected"])
        and float(before_metrics["mean_luminance"]) < 190.0
        and float(before_metrics["foreground_luminance"]) < 110.0
        and float(before_metrics["background_luminance"]) - float(before_metrics["foreground_luminance"]) >= 70.0
    )
    local_light_contamination = bool(strong_local_light and face_b <= 2.0)
    global_under = bool(
        not legitimate_dark
        and not strong_local_light
        and float(before_metrics["mean_luminance"]) < 78.0
        and float(before_metrics["midtone_point"]) < 88.0
        and float(before_metrics["shadow_ratio"]) >= 0.32
        and float(before_metrics["white_point"]) < 210.0
    )
    global_over = bool(
        float(before_metrics["mean_luminance"]) > 215.0
        and float(before_metrics["highlight_ratio"]) > 0.30
    )
    low_contrast = bool(
        float(before_metrics["dynamic_range"]) < 145.0
        and float(before_metrics["local_contrast"]) < 4.2
        and highlight_ratio < 0.03
    )
    floating_black = bool(
        low_contrast
        and float(before_metrics["black_point"]) >= 25.0
        and float(before_metrics["shadow_ratio"]) < 0.10
    )

    candidate_direction = "none"
    if neutral_ratio >= 0.025 and len(neutral_cells) >= 4:
        if neutral_b >= 4.5:
            candidate_direction = "warm"
        elif neutral_b <= -2.5:
            candidate_direction = "cool"
        elif abs(neutral_a) >= 5.0:
            candidate_direction = "other"
    if candidate_direction == "warm":
        consistency = warm_cells / max(len(neutral_cells), 1)
        severity = float(np.clip((neutral_b - 3.0) / 6.0, 0.0, 1.0))
    elif candidate_direction == "cool":
        consistency = cool_cells / max(len(neutral_cells), 1)
        severity = float(np.clip((-neutral_b - 1.8) / 4.5, 0.0, 1.0))
    elif candidate_direction == "other":
        aligned = sum(np.sign(float(cell["a"])) == np.sign(neutral_a) and abs(float(cell["a"])) >= 3.0 for cell in neutral_cells)
        consistency = aligned / max(len(neutral_cells), 1)
        severity = float(np.clip((abs(neutral_a) - 3.0) / 8.0, 0.0, 1.0))
    else:
        consistency = 0.0
        severity = 0.0
    candidate_confidence = float(
        np.clip(
            0.40 * min(1.0, neutral_ratio / 0.12)
            + 0.40 * consistency
            + 0.20 * severity,
            0.0,
            1.0,
        )
    ) if candidate_direction != "none" else 0.0

    environment_reason: str | None = None
    if mixed_light:
        environment_reason = "mixed_light"
    elif legitimate_warm:
        environment_reason = "legitimate_warm"
    elif strong_local_light or probable_screen:
        environment_reason = "strong_local_light"
    elif local_subject_under and highlight_risk == "high":
        environment_reason = "backlight_environment"
    elif highlight_risk == "high":
        environment_reason = "highlight_limited_evidence"
    elif candidate_confidence < 0.62:
        environment_reason = "insufficient_global_evidence"

    if environment_reason is None and candidate_direction != "none":
        global_cast_direction = candidate_direction
        global_cast_confidence = candidate_confidence
        cast_interpretation = "global_error_cast"
    else:
        global_cast_direction = "none"
        global_cast_confidence = 0.0
        cast_interpretation = environment_reason or "no_clear_cast"

    if legitimate_dark:
        scene_intent = "legitimate_dark"
    elif legitimate_warm:
        scene_intent = "legitimate_warm"
    else:
        scene_intent = "normal"

    if legitimate_dark or dark_material or probable_product:
        exposure_scope = "normal"
        decision = "ORIGINAL"
    elif local_subject_under or local_foreground_under or local_light_contamination:
        exposure_scope = "local_subject_under" if (local_subject_under or local_foreground_under) else "normal"
        decision = "LOCAL_REQUIRED"
    elif auditorium_depth:
        exposure_scope = "normal"
        decision = "NORMAL"
    elif mixed_light or highlight_risk == "high":
        exposure_scope = "normal"
        decision = "LOW"
    elif global_cast_direction != "none" or global_under or global_over or low_contrast:
        exposure_scope = "global_under" if global_under else ("global_over" if global_over else "normal")
        decision = "NORMAL"
    else:
        exposure_scope = "normal"
        decision = "ORIGINAL"

    if probable_screen:
        key_color_kind = "screen"
    elif probable_product:
        key_color_kind = "product"
    elif legitimate_warm and strong_coverage >= 0.08:
        key_color_kind = "environment"
    else:
        key_color_kind = "none"
    protect_strength = "high" if (
        probable_screen or probable_product or legitimate_warm or legitimate_dark or dark_material or highlight_risk == "high"
    ) else ("medium" if strong_coverage >= 0.08 else "low")
    protection_needs: list[str] = []
    if person_present:
        protection_needs.append("person_and_skin")
    if probable_screen:
        protection_needs.append("screen_color")
    if probable_product:
        protection_needs.append("product_key_color")
    if dark_material:
        protection_needs.append("dark_material_and_black_point")
    if highlight_risk in {"medium", "high"}:
        protection_needs.append("highlight_detail")
    if legitimate_warm:
        protection_needs.append("legitimate_warm_ambience")
    if legitimate_dark:
        protection_needs.append("legitimate_dark_intent")

    return {
        "decision_version": "hdde.color-perception.d01.v1",
        "global_cast_direction": global_cast_direction,
        "global_cast_confidence": round(global_cast_confidence, 4),
        "global_cast_candidate_direction": candidate_direction,
        "global_cast_candidate_confidence": round(candidate_confidence, 4),
        "cast_interpretation": cast_interpretation,
        "neutral_evidence_ratio": round(neutral_ratio, 4),
        "neutral_cast_a": round(neutral_a, 3),
        "neutral_cast_b": round(neutral_b, 3),
        "neutral_spatial_cells": neutral_cells,
        "lighting": "mixed" if mixed_light else ("strong_local_light" if strong_local_light else "uniform"),
        "mixed_light": mixed_light,
        "strong_local_light": strong_local_light,
        "exposure": exposure_scope,
        "global_underexposure": global_under,
        "global_overexposure": global_over,
        "local_subject_underexposure": bool(local_subject_under or local_foreground_under),
        "tonal_risk": {
            "highlight_risk": highlight_risk,
            "shadow_risk": "high" if float(before_metrics["shadow_ratio"]) >= 0.35 and not legitimate_dark else "low",
            "low_contrast": low_contrast,
            "floating_black": floating_black,
        },
        "person": {
            "present": person_present,
            "detector_count": len(faces),
            "detector_reliable": person_present,
            "exposure_risk": bool(local_subject_under or global_under),
            "skin_color_risk": local_light_contamination,
            "local_light_contamination": local_light_contamination,
            "face_luminance": round(face_luminance, 3) if person_present else None,
            "face_skin_fraction": round(face_skin_fraction, 4) if faces else 0.0,
        },
        "key_color": {
            "strong_local_color": strong_coverage >= 0.08,
            "probable_product_or_screen_color": key_color_kind,
            "protect_strength": protect_strength,
            "strong_color_coverage": round(strong_coverage, 4),
            "blue_color_coverage": round(blue_coverage, 4),
            "warm_color_coverage": round(warm_coverage, 4),
        },
        "scene_intent": scene_intent,
        "legitimate_warm": legitimate_warm,
        "legitimate_dark": legitimate_dark,
        "dark_material_protection": dark_material,
        "highlight_risk": highlight_risk,
        "low_contrast": low_contrast,
        "floating_black": floating_black,
        "protection_needs": protection_needs,
        "processing_decision": decision,
        "processing_scope": "local" if decision == "LOCAL_REQUIRED" else ("global" if decision == "NORMAL" else "protective"),
        "output_policy": "ORIGINAL_PROTECTED" if decision == "LOCAL_REQUIRED" and local_light_contamination else decision,
        "risk_exceeds_gain": decision in {"ORIGINAL", "LOW"} and (
            mixed_light or legitimate_warm or legitimate_dark or dark_material or highlight_risk == "high" or probable_product
        ),
        "auditorium_depth_recovery": auditorium_depth,
    }


def _select_strategy(
    before_metrics: dict[str, float],
    scene_analysis: dict[str, Any],
    white_balance: dict[str, Any],
    color_features: dict[str, float],
    low_key_design: bool,
    perception: dict[str, Any],
) -> dict[str, Any]:
    faces = int(scene_analysis["face_count"])
    strong_coverage = float(color_features["strong_color_coverage"])
    upper_strong = float(color_features["upper_strong_color_coverage"])
    decision = str(perception["processing_decision"])
    if low_key_design or decision == "ORIGINAL":
        strategy_id = "NORMAL_DESIGN_PROTECTION"
        label = "正常设计保护"
        primary = "处理风险高于潜在收益，保持原有设计、色彩与明暗意图"
        modules = ["设计意图保护", "黑白场保持", "原始色彩关系保持"]
    elif decision == "LOW":
        strategy_id = "RISK_LIMITED_PROTECTION"
        label = "高风险少处理保护"
        primary = "混合光或高光风险使全局处理收益低于保护需求"
        modules = ["环境光保护", "高光保护", "强色保护"]
    elif decision == "LOCAL_REQUIRED" and perception["person"]["local_light_contamination"]:
        strategy_id = "LOCAL_CORRECTION_REQUIRED"
        label = "人物局部颜色校正待处理"
        primary = "强色光源本身需要保护，人物局部颜色污染不能用全局白平衡解决"
        modules = ["强色光源保护", "人物局部颜色风险标记", "全局白平衡阻断"]
    elif bool(perception["auditorium_depth_recovery"]):
        strategy_id = "AUDITORIUM_STRONG_COLOR_DEPTH"
        label = "礼堂强色层次恢复"
        primary = "礼堂暗部层次不足，同时存在需要保留的强色大屏"
        modules = ["会场暗部局部恢复", "黑位锚定", "中间调层次", "强色大屏保护", "高光文字保护"]
    elif decision == "LOCAL_REQUIRED" and faces > 0 and scene_analysis["meeting_backlight_detected"]:
        strategy_id = "MEETING_MIXED_LIGHT_PEOPLE"
        label = "会议人物混合光平衡"
        primary = "人物与高亮背景反差明显，需要主体和背景分开处理"
        modules = ["可信中性色判断", "人物局部提亮", "肤色保护", "桌面强色保护", "窗户与高亮背景保护", "主体背景分离"]
    elif decision == "LOCAL_REQUIRED" and scene_analysis["meeting_backlight_detected"]:
        strategy_id = "BACKLIGHT_DEPTH_RECOVERY"
        label = "逆光层次恢复"
        primary = "高亮背景与暗部前景反差明显"
        modules = ["前景局部提亮", "高亮背景保护", "黑位锚定", "局部层次恢复"]
    elif decision == "ORIGINAL" or (
        before_metrics["dynamic_range"] >= 175.0
        and before_metrics["local_contrast"] >= 4.8
        and before_metrics["highlight_ratio"] <= 0.035
        and before_metrics["shadow_ratio"] <= 0.27
        and strong_coverage <= 0.12
    ):
        strategy_id = "NORMAL_DESIGN_PROTECTION"
        label = "正常图片保护"
        primary = "原图曝光、层次与色彩关系已基本成立"
        modules = ["正常图片保护", "黑白场保持", "品牌色与强色保持"]
    elif perception["global_cast_direction"] != "none" and white_balance["white_balance_applied"]:
        strategy_id = "COLOR_CAST_AND_TONE_BALANCE"
        label = "偏色与层次平衡"
        primary = "可信中性色显示存在偏色，同时需要克制的层次整理"
        modules = ["可信中性色白平衡", "中间调整理", "选择性色彩恢复", "高光保护"]
    else:
        strategy_id = "TONAL_DEPTH_RECOVERY"
        label = "明暗层次恢复"
        primary = "曝光或中间调层次需要调整"
        modules = ["自适应曝光", "黑白场重建", "中间调层次", "受控局部对比", "噪点保护"]
    secondary: list[str] = []
    if before_metrics["shadow_ratio"] >= 0.18:
        secondary.append("暗部占比较高")
    if before_metrics["local_contrast"] < 5.0:
        secondary.append("局部层次不足")
    if float(white_balance["color_cast_magnitude"]) >= 1.5:
        secondary.append(str(white_balance["color_cast"]))
    if strong_coverage >= 0.08:
        secondary.append("存在需要独立保护的强色区域")
    return {
        "strategy_id": strategy_id,
        "strategy_label": label,
        "primary_issue": primary,
        "secondary_issues": secondary,
        "enabled_modules": modules,
    }


def _visual_severity(
    before_metrics: dict[str, float],
    scene_analysis: dict[str, Any],
    strategy: dict[str, Any],
    white_balance: dict[str, Any],
) -> dict[str, Any]:
    """Map measured image problems to a continuous, content-driven gain level."""
    strategy_id = str(strategy["strategy_id"])
    if strategy_id in {"NORMAL_DESIGN_PROTECTION", "RISK_LIMITED_PROTECTION", "LOCAL_CORRECTION_REQUIRED"}:
        gain = 0.0 if strategy_id in {"NORMAL_DESIGN_PROTECTION", "LOCAL_CORRECTION_REQUIRED"} else 0.12
        return {
            "visual_severity": "NORMAL" if gain == 0.0 else "MILD",
            "visual_severity_score": gain,
            "visual_gain": gain,
            "visual_severity_components": {
                "shadow": 0.0,
                "midtone": 0.0,
                "local_depth": 0.0,
                "foreground": 0.0,
                "backlight": 0.0,
                "dynamic_range": 0.0,
                "color_cast": 0.0,
            },
        }

    shadow_need = float(np.clip((before_metrics["shadow_ratio"] - 0.08) / 0.30, 0.0, 1.0))
    midtone_need = float(np.clip((124.0 - before_metrics["midtone_point"]) / 68.0, 0.0, 1.0))
    local_depth_need = float(np.clip((7.2 - before_metrics["local_contrast"]) / 5.8, 0.0, 1.0))
    range_need = float(np.clip((155.0 - before_metrics["dynamic_range"]) / 105.0, 0.0, 1.0))
    foreground_need = float(np.clip((116.0 - before_metrics["foreground_luminance"]) / 78.0, 0.0, 1.0))
    backlight_need = float(np.clip((float(scene_analysis["backlight_contrast"]) - 12.0) / 82.0, 0.0, 1.0))
    cast_need = float(np.clip((float(white_balance["color_cast_magnitude"]) - 1.2) / 8.5, 0.0, 1.0))
    score = float(
        0.22 * shadow_need
        + 0.18 * midtone_need
        + 0.17 * local_depth_need
        + 0.12 * range_need
        + 0.15 * foreground_need
        + 0.12 * backlight_need
        + 0.04 * cast_need
    )

    # These floors are based on generic scene evidence already required by the
    # strategy selector, never on filenames or calibration-sample identities.
    if strategy_id == "AUDITORIUM_STRONG_COLOR_DEPTH":
        score = max(score, 0.72 + 0.16 * shadow_need + 0.08 * local_depth_need)
    elif strategy_id == "MEETING_MIXED_LIGHT_PEOPLE":
        score = max(score, 0.68 + 0.18 * backlight_need + 0.12 * foreground_need)
    elif strategy_id == "BACKLIGHT_DEPTH_RECOVERY":
        score = max(score, 0.54 + 0.24 * backlight_need + 0.12 * foreground_need)
    score = float(np.clip(score, 0.0, 1.0))

    if score >= 0.68:
        label = "STRONG"
        gain = float(np.clip(0.82 + (score - 0.68) * 0.5625, 0.82, 1.0))
    elif score >= 0.38:
        label = "MODERATE"
        gain = float(np.clip(0.52 + (score - 0.38), 0.52, 0.82))
    else:
        label = "MILD"
        gain = float(np.clip(0.24 + score * 0.72, 0.24, 0.52))
    return {
        "visual_severity": label,
        "visual_severity_score": round(score, 4),
        "visual_gain": round(gain, 4),
        "visual_severity_components": {
            "shadow": round(shadow_need, 4),
            "midtone": round(midtone_need, 4),
            "local_depth": round(local_depth_need, 4),
            "foreground": round(foreground_need, 4),
            "backlight": round(backlight_need, 4),
            "dynamic_range": round(range_need, 4),
            "color_cast": round(cast_need, 4),
        },
    }


def _apply_adaptive_correction(
    source_rgb: np.ndarray,
    balanced_rgb: np.ndarray,
    before_metrics: dict[str, float],
    focus_mask: np.ndarray,
    background_mask: np.ndarray,
    face_mask: np.ndarray,
    strong_color_mask: np.ndarray,
    strong_screen_mask: np.ndarray,
    scene_analysis: dict[str, Any],
    white_balance: dict[str, Any],
    strategy: dict[str, Any],
    strength_scales: dict[str, float] | None = None,
) -> tuple[np.ndarray, dict[str, Any], dict[str, Any]]:
    scales = {
        "tone": 1.0,
        "white_balance": 1.0,
        "shadow": 1.0,
        "person": 1.0,
        "skin": 1.0,
        "detail": 1.0,
        "color": 1.0,
    }
    if strength_scales:
        scales.update({key: float(np.clip(value, 0.0, 1.0)) for key, value in strength_scales.items() if key in scales})
    balanced_u8 = np.clip(balanced_rgb, 0, 255).astype(np.uint8)
    lab = cv2.cvtColor(balanced_u8, cv2.COLOR_RGB2LAB).astype(np.float32)
    lightness = lab[..., 0]
    p1, p10, p50, p90, p99 = np.percentile(lightness, [1, 10, 50, 90, 99])
    dynamic_range = float(p99 - p1)
    local_contrast_before = float(before_metrics["local_contrast"])
    low_key_design = bool(before_metrics.get("low_key_design_detected", False))
    strategy_id = str(strategy["strategy_id"])
    normal_image = strategy_id in {"NORMAL_DESIGN_PROTECTION", "RISK_LIMITED_PROTECTION", "LOCAL_CORRECTION_REQUIRED"}
    global_underexposure = bool(scene_analysis.get("exposure") == "global_under")
    transparency_layering = bool(
        scene_analysis.get("low_contrast")
        and scene_analysis.get("floating_black")
        and not global_underexposure
    )
    pure_global_cast = bool(
        strategy_id == "COLOR_CAST_AND_TONE_BALANCE"
        and scene_analysis.get("exposure") == "normal"
        and not scene_analysis.get("low_contrast")
    )
    visual_severity = str(strategy.get("visual_severity") or ("NORMAL" if normal_image else "MILD"))
    severity_score = float(np.clip(strategy.get("visual_severity_score", 0.0), 0.0, 1.0))
    visual_gain = float(np.clip(strategy.get("visual_gain", 0.0 if normal_image else 0.35), 0.0, 1.0))
    if normal_image:
        parameters = {
            "global_gamma": 1.0,
            "contrast_strength": 0.0,
            "local_contrast_strength": 0.0,
            "shadow_lift": 0.0,
            "highlight_compression": 0.0,
            "local_luminance_strength": 0.0,
            "selective_color_strength": 0.0,
            "saturation_adjustment_mode": "保持原有色彩强度",
            "clarity_strength": 0.0,
            "dark_noise_risk": 0.0,
            "convergence_scales": dict(scales),
            "visual_severity": visual_severity,
            "visual_severity_score": round(severity_score, 4),
            "visual_gain": round(visual_gain, 4),
            "midtone_lift": 0.0,
            "black_reconstruction": 0.0,
            "subject_target_gain": 0.0,
            "skin_local_convergence_scale": 1.0,
            "tonal_curve_mode": "identity",
            "tonal_curve_source_points": [],
            "tonal_curve_target_points": [],
            "tonal_curve_strength": 0.0,
            "spatial_layering_strength": 0.0,
        }
        analysis = {
            "exposure_state": "基本正常",
            "normal_image_detected": strategy_id == "NORMAL_DESIGN_PROTECTION",
            "strategy_id": strategy_id,
            "strategy_label": strategy["strategy_label"],
            "primary_issue": strategy["primary_issue"],
            "secondary_issues": list(strategy["secondary_issues"]),
            "enabled_modules": list(strategy["enabled_modules"]),
            "module_order": list(strategy["enabled_modules"]),
            "person_region_reliably_detected": bool(scene_analysis.get("person_present", scene_analysis["face_count"] > 0) and float(face_mask.sum()) > 1.0),
            "person_local_adjustment_enabled": False,
            "foreground_local_adjustment_enabled": False,
            "highlight_background_protection_enabled": False,
            "skin_tone_protection_enabled": bool(float(face_mask.sum()) > 1.0),
            "strong_color_protection_enabled": bool(float(strong_color_mask.sum()) > 1.0 and strategy_id != "NORMAL_DESIGN_PROTECTION"),
            "local_contrast_enabled": False,
            "color_balance_enabled": False,
            "clarity_enabled": False,
            "noise_protection_enabled": True,
            "skin_local_convergence_applied": False,
            "input_black_point": round(float(p1), 2),
            "input_shadow_point": round(float(p10), 2),
            "input_midtone_point": round(float(p50), 2),
            "input_highlight_point": round(float(p90), 2),
            "input_white_point": round(float(p99), 2),
            "visual_severity": visual_severity,
            "visual_severity_score": round(severity_score, 4),
            "visual_gain": round(visual_gain, 4),
            "visual_severity_components": dict(strategy.get("visual_severity_components") or {}),
        }
        return source_rgb.astype(np.uint8).copy(), parameters, analysis
    range_need = float(np.clip((160.0 - dynamic_range) / 100.0, 0.0, 1.0))
    haze_need = float(np.clip((6.5 - local_contrast_before) / 5.0, 0.0, 1.0))
    if p50 < 124.0:
        target_mid = min(132.0, p50 + 7.0 + 20.0 * visual_gain)
    elif p50 > 178.0:
        target_mid = max(166.0, p50 - 8.0)
    else:
        target_mid = p50
    raw_gamma = 1.0 if p50 <= 1.0 or p50 >= 254.0 else float(np.log(max(target_mid, 1.0) / 255.0) / np.log(p50 / 255.0))
    gamma_response = 0.24 + 0.34 * visual_gain
    gamma = float(np.clip(1.0 + (raw_gamma - 1.0) * gamma_response, 0.94, 1.035))
    shadow_lift = float((0.7 + 3.8 * visual_gain) * scales["shadow"])
    midtone_lift = float((1.0 + 6.0 * visual_gain) * scales["tone"])
    black_reconstruction = float((0.3 + 1.5 * visual_gain) * scales["tone"])
    subject_target_gain = 0.0
    if strategy_id == "AUDITORIUM_STRONG_COLOR_DEPTH":
        gamma = min(gamma, 0.992 - 0.037 * visual_gain)
        contrast_strength = 0.04 + 0.065 * visual_gain
        local_contrast_strength = 0.045 + 0.09 * visual_gain
        local_strength = 5.0 + 12.0 * visual_gain
    elif strategy_id == "MEETING_MIXED_LIGHT_PEOPLE":
        gamma = min(gamma, 0.993 - 0.040 * visual_gain)
        contrast_strength = 0.035 + 0.05 * visual_gain
        local_contrast_strength = 0.045 + 0.07 * visual_gain
        local_strength = float(np.clip(12.0 + scene_analysis["backlight_contrast"] * 0.24 + 10.0 * visual_gain, 20.0, 44.0))
        subject_target_gain = 6.0 + 9.0 * visual_gain
    elif strategy_id == "BACKLIGHT_DEPTH_RECOVERY":
        gamma = min(gamma, 0.995 - 0.035 * visual_gain)
        contrast_strength = 0.03 + 0.055 * visual_gain
        local_contrast_strength = 0.04 + 0.07 * visual_gain
        local_strength = float(np.clip(9.0 + scene_analysis["backlight_contrast"] * 0.22 + 8.0 * visual_gain, 16.0, 38.0))
        subject_target_gain = 6.0 + 8.0 * visual_gain
    elif strategy_id == "COLOR_CAST_AND_TONE_BALANCE":
        if pure_global_cast:
            gamma = 1.0
            contrast_strength = 0.0
            local_contrast_strength = 0.0
            local_strength = 0.0
            shadow_lift = 0.0
            midtone_lift = 0.0
            black_reconstruction = 0.0
        else:
            contrast_strength = float(np.clip(0.035 + 0.05 * max(range_need, haze_need), 0.035, 0.09))
            if before_metrics["mean_luminance"] < 70.0:
                gamma = min(gamma, 0.94)
                contrast_strength = min(contrast_strength, 0.04)
            local_contrast_strength = float(np.clip(0.04 + 0.06 * haze_need, 0.04, 0.10))
            local_strength = 9.0 if scene_analysis["face_count"] else 0.0
    elif normal_image:
        gamma = 1.0
        contrast_strength = 0.0
        local_contrast_strength = 0.0
        local_strength = 0.0
    else:
        if global_underexposure:
            gamma = 1.0
            contrast_strength = 0.0
            local_contrast_strength = 0.032
            local_strength = 0.0
            shadow_lift = 0.0
            midtone_lift = 0.0
            black_reconstruction = 0.0
        elif transparency_layering:
            gamma = 1.0
            contrast_strength = 0.0
            local_contrast_strength = float(np.clip(0.12 + 0.025 * haze_need, 0.12, 0.138))
            local_strength = 0.0
            shadow_lift = 0.0
            midtone_lift = 0.0
            black_reconstruction = 0.0
        else:
            contrast_strength = float(np.clip(0.055 + 0.08 * max(range_need, haze_need), 0.055, 0.135))
            local_contrast_strength = float(np.clip(0.055 + 0.08 * haze_need, 0.055, 0.135))
            local_strength = 10.0 if scene_analysis["face_count"] and before_metrics["foreground_luminance"] < 112.0 else 0.0

    gamma = 1.0 + (gamma - 1.0) * scales["tone"]
    contrast_strength *= scales["tone"]
    local_contrast_strength *= scales["detail"]
    local_strength *= scales["person"]

    tonal_curve_mode = "adaptive_gamma"
    tonal_curve_source_points: list[float] = []
    tonal_curve_target_points: list[float] = []
    tonal_curve_strength = 0.0
    spatial_layering_strength = 0.0
    if global_underexposure and dynamic_range >= 20.0:
        under_need = float(np.clip((100.0 - p50) / 50.0, 0.0, 1.0))
        headroom_need = float(np.clip((220.0 - p99) / 80.0, 0.0, 1.0))
        tonal_curve_strength = float(
            np.clip((0.86 + 0.12 * max(under_need, headroom_need)) * scales["tone"] * (0.65 + 0.35 * scales["shadow"]), 0.0, 0.96)
        )
        source_points = np.array([0.0, p1, p10, p50, p90, p99, 255.0], dtype=np.float32)
        for index in range(1, len(source_points)):
            if source_points[index] <= source_points[index - 1]:
                source_points[index] = min(255.0, source_points[index - 1] + 0.01)
        target_anchors = np.array(
            [p1, max(p10, 16.0), max(p50, 105.0), max(p90, 198.0), max(p99, 224.0)],
            dtype=np.float32,
        )
        target_points = np.array(
            [0.0, *(np.array([p1, p10, p50, p90, p99]) + (target_anchors - np.array([p1, p10, p50, p90, p99])) * tonal_curve_strength), 255.0],
            dtype=np.float32,
        )
        target_points = np.maximum.accumulate(np.clip(target_points, 0.0, 255.0))
        global_lightness = np.interp(lightness, source_points, target_points).astype(np.float32)
        tonal_curve_mode = "coordinated_global_underexposure"
        tonal_curve_source_points = [round(float(value), 3) for value in source_points]
        tonal_curve_target_points = [round(float(value), 3) for value in target_points]
    elif transparency_layering and dynamic_range >= 20.0:
        tonal_curve_strength = float(np.clip((0.92 + 0.04 * haze_need) * scales["tone"], 0.0, 0.95))
        source_points = np.array([0.0, p1, p10, p50, p90, p99, 255.0], dtype=np.float32)
        for index in range(1, len(source_points)):
            if source_points[index] <= source_points[index - 1]:
                source_points[index] = min(255.0, source_points[index - 1] + 0.01)
        target_anchors = np.array(
            [
                max(4.0, p1 - 22.0 - 3.0 * haze_need),
                max(12.0, p10 - 13.0 - 2.5 * haze_need),
                min(205.0, p50 + 7.0 + 2.0 * haze_need),
                min(238.0, p90 + 27.0 + 4.0 * haze_need),
                min(248.0, p99 + 38.0 + 4.0 * haze_need),
            ],
            dtype=np.float32,
        )
        target_points = np.array(
            [0.0, *(np.array([p1, p10, p50, p90, p99]) + (target_anchors - np.array([p1, p10, p50, p90, p99])) * tonal_curve_strength), 255.0],
            dtype=np.float32,
        )
        target_points = np.maximum.accumulate(np.clip(target_points, 0.0, 255.0))
        global_lightness = np.interp(lightness, source_points, target_points).astype(np.float32)
        tonal_curve_mode = "floating_black_transparency_layering"
        tonal_curve_source_points = [round(float(value), 3) for value in source_points]
        tonal_curve_target_points = [round(float(value), 3) for value in target_points]
    else:
        normalized = np.clip(lightness / 255.0, 0.0, 1.0)
        gamma_curve = np.power(normalized, gamma)
        centered = gamma_curve - 0.5
        s_curve = gamma_curve + contrast_strength * centered * np.clip(1.0 - 4.0 * centered * centered, 0.0, 1.0)
        global_lightness = 255.0 * np.clip(s_curve, 0.0, 1.0)
    if strategy_id == "TONAL_DEPTH_RECOVERY" and not (global_underexposure or transparency_layering):
        measured_shadow_lift = float(np.clip((before_metrics["shadow_ratio"] - 0.12) * 28.0, 0.0, 5.0))
        shadow_lift = max(shadow_lift, measured_shadow_lift * scales["shadow"])
    shadow_weight = np.square(np.clip((142.0 - lightness) / 122.0, 0.0, 1.0))
    midtone_weight = np.exp(-0.5 * np.square((lightness - 112.0) / 48.0))
    black_reconstruction_weight = np.exp(-0.5 * np.square((lightness - 46.0) / 24.0))
    global_lightness += shadow_weight * shadow_lift
    global_lightness += midtone_weight * midtone_lift
    global_lightness -= black_reconstruction_weight * black_reconstruction
    highlight_compression = float(np.clip((before_metrics["highlight_ratio"] - 0.01) * 55.0, 0.0, 6.0))
    highlight_compression *= scales["tone"]
    highlight_weight = np.square(np.clip((lightness - 205.0) / 50.0, 0.0, 1.0))
    global_lightness -= highlight_weight * highlight_compression

    local_focus = np.clip(focus_mask, 0.0, 1.0)
    if strategy_id == "AUDITORIUM_STRONG_COLOR_DEPTH":
        height, width = lightness.shape
        yy = np.arange(height, dtype=np.float32)[:, None]
        lower_prior = np.clip((yy / max(height - 1, 1) - 0.38) / 0.30, 0.0, 1.0)
        auditorium_shadow = (lightness < 155.0).astype(np.float32) * lower_prior
        auditorium_shadow *= np.clip(1.0 - strong_screen_mask * 0.98, 0.0, 1.0)
        local_focus = _soft_mask(auditorium_shadow, max(3, int(min(width, height) * 0.01)))
    elif strategy_id in {"MEETING_MIXED_LIGHT_PEOPLE", "BACKLIGHT_DEPTH_RECOVERY"}:
        local_focus = np.clip(np.power(local_focus, 1.2) * 0.78 + face_mask * 0.34, 0.0, 1.0)
    subject_shadow_weight = np.clip((182.0 - lightness) / 132.0, 0.0, 1.0)
    black_gate = np.clip((lightness - 11.0) / 38.0, 0.0, 1.0)
    subject_delta = local_focus * subject_shadow_weight * black_gate * local_strength

    global_delta = global_lightness - lightness
    if scene_analysis["meeting_backlight_detected"]:
        global_delta -= background_mask * np.maximum(global_delta, 0.0) * 0.92
        screen_hold = background_mask * np.clip((lightness - 175.0) / 70.0, 0.0, 1.0) * 2.0
    else:
        screen_hold = 0.0
    corrected_lightness = np.clip(lightness + global_delta + subject_delta - screen_hold, 0.0, 255.0)
    screen_hold_strength = 0.76 if strategy_id == "AUDITORIUM_STRONG_COLOR_DEPTH" else 0.42
    corrected_lightness = corrected_lightness * (1.0 - strong_screen_mask * screen_hold_strength) + lightness * strong_screen_mask * screen_hold_strength
    if strategy_id in {"MEETING_MIXED_LIGHT_PEOPLE", "BACKLIGHT_DEPTH_RECOVERY"} and float(focus_mask.sum()) > 1.0:
        base_target = subject_target_gain or (6.5 if scene_analysis["face_count"] > 0 else 10.0)
        target_foreground_lift = base_target * scales["person"]
        current_foreground_lift = _masked_mean(corrected_lightness - lightness, focus_mask)
        if current_foreground_lift < target_foreground_lift:
            safe_focus = np.clip(focus_mask, 0.0, 1.0) * np.clip((lightness - 10.0) / 25.0, 0.0, 1.0)
            response = float((safe_focus * focus_mask).sum() / max(float(focus_mask.sum()), 1.0))
            separation_boost = float(np.clip((target_foreground_lift - current_foreground_lift) / max(response, 0.15), 0.0, 30.0))
            corrected_lightness = np.clip(corrected_lightness + safe_focus * separation_boost, 0.0, 255.0)

    if transparency_layering:
        spatial_layering_strength = float(
            np.clip((0.095 + 0.075 * haze_need) * scales["detail"], 0.0, 0.15)
        )
        spatial_sigma = max(8.0, min(lightness.shape) * 0.025)
        spatial_base = cv2.GaussianBlur(corrected_lightness, (0, 0), sigmaX=spatial_sigma)
        spatial_detail = np.clip(corrected_lightness - spatial_base, -24.0, 24.0)
        spatial_endpoint_gate = np.clip((corrected_lightness - 28.0) / 38.0, 0.0, 1.0)
        spatial_endpoint_gate *= np.clip((232.0 - corrected_lightness) / 42.0, 0.0, 1.0)
        spatial_face_hold = np.clip(1.0 - face_mask * 0.62, 0.38, 1.0)
        corrected_lightness = np.clip(
            corrected_lightness
            + spatial_detail * spatial_layering_strength * spatial_endpoint_gate * spatial_face_hold,
            0.0,
            255.0,
        )

    broad_detail = lightness - cv2.GaussianBlur(lightness, (0, 0), sigmaX=5.0)
    detail = lightness - cv2.GaussianBlur(lightness, (0, 0), sigmaX=1.15)
    dark_pixels = lightness < 72.0
    dark_noise_risk = float(np.mean(np.abs(detail[dark_pixels]))) if dark_pixels.any() else 0.0
    clarity_strength = 0.0 if normal_image or pure_global_cast or transparency_layering else float(np.clip(0.025 + 0.04 * visual_gain + 0.02 * haze_need, 0.025, 0.085))
    clarity_strength *= scales["detail"]
    detail_weight = np.clip((corrected_lightness - 38.0) / 55.0, 0.0, 1.0)
    detail_weight *= np.clip((226.0 - corrected_lightness) / 65.0, 0.0, 1.0)
    detail_weight *= 1.0 - face_mask * 0.78
    if dark_noise_risk >= 4.0:
        detail_weight *= 0.58
    corrected_lightness = np.clip(
        corrected_lightness
        + np.clip(broad_detail, -18.0, 18.0) * local_contrast_strength * detail_weight
        + np.clip(detail, -6.0, 6.0) * clarity_strength * detail_weight,
        0.0,
        255.0,
    )
    black_hold = np.square(np.clip((42.0 - lightness) / 34.0, 0.0, 1.0)) * 0.88
    white_hold = np.square(np.clip((lightness - 220.0) / 32.0, 0.0, 1.0)) * 0.86
    endpoint_hold = np.maximum(black_hold, white_hold)
    corrected_lightness = corrected_lightness * (1.0 - endpoint_hold) + lightness * endpoint_hold
    lab[..., 0] = corrected_lightness
    toned_rgb = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB)

    hsv = cv2.cvtColor(toned_rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    saturation = hsv[..., 1] / 255.0
    low_color_need = float(np.clip((0.28 - before_metrics["mean_saturation"]) / 0.22, 0.0, 1.0))
    if normal_image or pure_global_cast or transparency_layering:
        color_strength = 0.0
    elif strategy_id == "AUDITORIUM_STRONG_COLOR_DEPTH":
        color_strength = (0.012 + 0.035 * visual_gain) * (0.45 + 0.55 * low_color_need)
    elif strategy_id == "MEETING_MIXED_LIGHT_PEOPLE":
        color_strength = (0.012 + 0.032 * visual_gain) * (0.62 + 0.38 * low_color_need)
    else:
        color_strength = 0.04 * low_color_need
    color_strength *= scales["color"]
    vibrance = np.power(np.clip(1.0 - saturation, 0.0, 1.0), 1.4)
    vibrance *= np.clip((corrected_lightness - 42.0) / 65.0, 0.0, 1.0)
    vibrance *= np.clip((235.0 - corrected_lightness) / 55.0, 0.0, 1.0)
    vibrance *= 1.0 - face_mask * 0.72
    hsv[..., 1] = np.clip(hsv[..., 1] * (1.0 + color_strength * vibrance), 0.0, 255.0)
    colored_rgb = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)

    if float(strong_color_mask.sum()) > 1.0:
        final_hsv = cv2.cvtColor(colored_rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
        source_hsv = cv2.cvtColor(source_rgb.astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
        protected_saturation = np.clip(
            final_hsv[..., 1],
            source_hsv[..., 1] * 0.985,
            np.minimum(255.0, source_hsv[..., 1] * 1.055 + 1.0),
        )
        strong_hold = np.clip(strong_color_mask * 0.92, 0.0, 0.92)
        final_hsv[..., 0] = final_hsv[..., 0] * (1.0 - strong_hold) + source_hsv[..., 0] * strong_hold
        final_hsv[..., 1] = final_hsv[..., 1] * (1.0 - strong_hold) + protected_saturation * strong_hold
        colored_rgb = cv2.cvtColor(final_hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)

    if float(face_mask.sum()) > 1.0:
        final_lab = cv2.cvtColor(colored_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
        protected_lab = cv2.cvtColor(balanced_u8, cv2.COLOR_RGB2LAB).astype(np.float32)
        chroma_hold = np.clip(face_mask * 0.72, 0.0, 0.72)
        for channel in (1, 2):
            final_lab[..., channel] = final_lab[..., channel] * (1.0 - chroma_hold) + protected_lab[..., channel] * chroma_hold
        colored_rgb = cv2.cvtColor(final_lab.astype(np.uint8), cv2.COLOR_LAB2RGB)

    skin_local_scale = float(scales["skin"])
    skin_local_convergence_applied = bool(float(face_mask.sum()) > 1.0 and skin_local_scale < 0.999)
    if skin_local_convergence_applied:
        final_lab = cv2.cvtColor(colored_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
        source_lab = cv2.cvtColor(source_rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
        local_hold = np.clip(face_mask * (1.0 - skin_local_scale), 0.0, 0.88)
        for channel in range(3):
            final_lab[..., channel] = final_lab[..., channel] * (1.0 - local_hold) + source_lab[..., channel] * local_hold
        colored_rgb = cv2.cvtColor(np.clip(final_lab, 0.0, 255.0).astype(np.uint8), cv2.COLOR_LAB2RGB)

    parameters = {
        "global_gamma": round(gamma, 4),
        "contrast_strength": round(contrast_strength, 4),
        "local_contrast_strength": round(local_contrast_strength, 4),
        "shadow_lift": round(shadow_lift, 3),
        "highlight_compression": round(highlight_compression, 3),
        "local_luminance_strength": round(local_strength, 3),
        "selective_color_strength": round(color_strength, 4),
        "saturation_adjustment_mode": "保护强色的自然饱和度" if color_strength > 0 else "保持原有色彩强度",
        "clarity_strength": round(clarity_strength, 4),
        "dark_noise_risk": round(dark_noise_risk, 3),
        "convergence_scales": dict(scales),
        "visual_severity": visual_severity,
        "visual_severity_score": round(severity_score, 4),
        "visual_gain": round(visual_gain, 4),
        "midtone_lift": round(midtone_lift, 3),
        "black_reconstruction": round(black_reconstruction, 3),
        "subject_target_gain": round(subject_target_gain, 3),
        "skin_local_convergence_scale": round(skin_local_scale, 4),
        "tonal_curve_mode": tonal_curve_mode,
        "tonal_curve_source_points": tonal_curve_source_points,
        "tonal_curve_target_points": tonal_curve_target_points,
        "tonal_curve_strength": round(tonal_curve_strength, 4),
        "spatial_layering_strength": round(spatial_layering_strength, 4),
    }
    analysis = {
        "exposure_state": "偏暗" if p50 < 108.0 else ("偏亮" if p50 > 174.0 else "基本正常"),
        "normal_image_detected": normal_image,
        "strategy_id": strategy_id,
        "strategy_label": strategy["strategy_label"],
        "primary_issue": strategy["primary_issue"],
        "secondary_issues": list(strategy["secondary_issues"]),
        "enabled_modules": list(strategy["enabled_modules"]),
        "module_order": list(strategy["enabled_modules"]),
        "person_region_reliably_detected": bool(scene_analysis.get("person_present", scene_analysis["face_count"] > 0) and float(face_mask.sum()) > 1.0),
        "person_local_adjustment_enabled": bool(scene_analysis["face_count"] > 0 and local_strength > 0.0 and float(local_focus.sum()) > 1.0),
        "foreground_local_adjustment_enabled": bool(local_strength > 0.0 and float(local_focus.sum()) > 1.0),
        "highlight_background_protection_enabled": bool(scene_analysis["meeting_backlight_detected"] and float(background_mask.sum()) > 1.0),
        "skin_tone_protection_enabled": bool(float(face_mask.sum()) > 1.0),
        "strong_color_protection_enabled": bool(float(strong_color_mask.sum()) > 1.0 and strategy_id != "NORMAL_DESIGN_PROTECTION"),
        "local_contrast_enabled": bool(local_contrast_strength >= 0.025),
        "color_balance_enabled": bool(color_strength >= 0.01 or white_balance["white_balance_applied"]),
        "clarity_enabled": bool(clarity_strength >= 0.025),
        "noise_protection_enabled": True,
        "skin_local_convergence_applied": skin_local_convergence_applied,
        "input_black_point": round(float(p1), 2),
        "input_shadow_point": round(float(p10), 2),
        "input_midtone_point": round(float(p50), 2),
        "input_highlight_point": round(float(p90), 2),
        "input_white_point": round(float(p99), 2),
        "visual_severity": visual_severity,
        "visual_severity_score": round(severity_score, 4),
        "visual_gain": round(visual_gain, 4),
        "visual_severity_components": dict(strategy.get("visual_severity_components") or {}),
        "tonal_curve_mode": tonal_curve_mode,
        "tonal_curve_source_points": list(tonal_curve_source_points),
        "tonal_curve_target_points": list(tonal_curve_target_points),
        "tonal_curve_strength": round(tonal_curve_strength, 4),
    }
    return colored_rgb, parameters, analysis


def _region_saturation(rgb: np.ndarray, mask: np.ndarray) -> float:
    hsv = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
    return _masked_mean(hsv[..., 1] / 255.0, mask)


def _luminance(rgb: np.ndarray) -> np.ndarray:
    array = rgb.astype(np.float32)
    return 0.2126 * array[..., 0] + 0.7152 * array[..., 1] + 0.0722 * array[..., 2]


def _review_white_balance(
    source_rgb: np.ndarray,
    candidate_rgb: np.ndarray,
    strong_color_mask: np.ndarray,
    analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if (
        analysis
        and analysis.get("strategy_id") == "NORMAL_DESIGN_PROTECTION"
        and not analysis.get("white_balance_applied")
    ):
        return {
            "status": "NOT_APPLICABLE",
            "soft_deviation": False,
            "confidence": 0.0,
            "evidence_pixels": 0,
            "reason": "保护性策略未执行白平衡修正，无需单独判断通道回退",
            "before": None,
            "after": None,
        }
    source = source_rgb.astype(np.float32)
    maximum = source.max(axis=2)
    minimum = source.min(axis=2)
    saturation = np.divide(maximum - minimum, np.maximum(maximum, 1.0))
    luminance = _luminance(source)
    trusted = (
        (saturation < 0.16)
        & (luminance > 40.0)
        & (luminance < 235.0)
        & (strong_color_mask < 0.18)
    )
    evidence_pixels = int(trusted.sum())
    required = max(64, int(trusted.size * 0.003))
    if evidence_pixels < required:
        return {
            "status": "LOW_CONFIDENCE",
            "soft_deviation": False,
            "confidence": round(float(evidence_pixels / max(required, 1)), 3),
            "evidence_pixels": evidence_pixels,
            "reason": "可信中性色像素不足，未单独判断白平衡安全性",
            "before": None,
            "after": None,
        }

    source_lab = cv2.cvtColor(source_rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    candidate_lab = cv2.cvtColor(candidate_rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    before_a = float(np.median(source_lab[..., 1][trusted]) - 128.0)
    before_b = float(np.median(source_lab[..., 2][trusted]) - 128.0)
    after_a = float(np.median(candidate_lab[..., 1][trusted]) - 128.0)
    after_b = float(np.median(candidate_lab[..., 2][trusted]) - 128.0)
    before_magnitude = float(np.hypot(before_a, before_b))
    after_magnitude = float(np.hypot(after_a, after_b))
    before_channels = np.array([source[..., channel][trusted].mean() for channel in range(3)])
    candidate = candidate_rgb.astype(np.float32)
    after_channels = np.array([candidate[..., channel][trusted].mean() for channel in range(3)])
    before_spread = float(np.ptp(before_channels))
    after_spread = float(np.ptp(after_channels))
    # A small axis crossing inside the near-neutral zone is expected when a
    # confirmed global cast is brought back toward neutral.  Treat it as a
    # reversal only when the candidate leaves that natural tolerance again.
    reverse_overcorrection = bool(
        before_magnitude >= 1.0
        and (before_a * after_a + before_b * after_b) < 0.0
        and after_magnitude > 2.5
    )
    soft_deviation = bool(
        after_magnitude > before_magnitude + 1.35
        or after_spread > before_spread + 3.5
    )
    risk = bool(
        after_magnitude > before_magnitude + 3.0
        or after_spread > before_spread + 6.0
        or reverse_overcorrection
    )
    return {
        "status": "RISK" if risk else "PASS",
        "soft_deviation": bool(soft_deviation and not risk),
        "confidence": round(float(np.clip(evidence_pixels / max(trusted.size * 0.08, 1.0), 0.0, 1.0)), 3),
        "evidence_pixels": evidence_pixels,
        "reason": "中性色发生染色或反向过校正" if risk else "可信中性色通道关系未恶化",
        "before": {
            "lab_a": round(before_a, 3),
            "lab_b": round(before_b, 3),
            "cast_magnitude": round(before_magnitude, 3),
            "rgb_channel_spread": round(before_spread, 3),
        },
        "after": {
            "lab_a": round(after_a, 3),
            "lab_b": round(after_b, 3),
            "cast_magnitude": round(after_magnitude, 3),
            "rgb_channel_spread": round(after_spread, 3),
        },
        "cast_improved": bool(after_magnitude <= before_magnitude + 0.2),
        "reverse_overcorrection": reverse_overcorrection,
    }


def _review_skin_tone(
    source_rgb: np.ndarray,
    candidate_rgb: np.ndarray,
    face_mask: np.ndarray,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    if not analysis.get("person_region_reliably_detected") or float(face_mask.sum()) <= 1.0:
        return {
            "status": "NOT_APPLICABLE",
            "soft_deviation": False,
            "confidence": 0.0,
            "evidence_pixels": 0,
            "reason": "未检测到可靠人物区域，不使用全图颜色替代肤色判断",
            "before": None,
            "after": None,
        }
    source_ycc = cv2.cvtColor(source_rgb.astype(np.uint8), cv2.COLOR_RGB2YCrCb)
    skin = (
        (face_mask >= 0.28)
        & (source_ycc[..., 0] > 32)
        & (source_ycc[..., 1] >= 128)
        & (source_ycc[..., 1] <= 180)
        & (source_ycc[..., 2] >= 75)
        & (source_ycc[..., 2] <= 138)
    )
    evidence_pixels = int(skin.sum())
    face_pixels = int((face_mask >= 0.28).sum())
    required = max(48, int(face_pixels * 0.08))
    if evidence_pixels < required:
        return {
            "status": "LOW_CONFIDENCE",
            "soft_deviation": False,
            "confidence": round(float(evidence_pixels / max(required, 1)), 3),
            "evidence_pixels": evidence_pixels,
            "reason": "人物区域存在，但可靠肤色像素不足",
            "before": None,
            "after": None,
        }
    source_lab = cv2.cvtColor(source_rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    after_lab = cv2.cvtColor(candidate_rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    source_hsv = cv2.cvtColor(source_rgb.astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
    after_hsv = cv2.cvtColor(candidate_rgb.astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
    before_values = np.array([source_lab[..., channel][skin].mean() for channel in range(3)])
    after_values = np.array([after_lab[..., channel][skin].mean() for channel in range(3)])
    delta = after_values - before_values
    before_saturation = float((source_hsv[..., 1][skin] / 255.0).mean())
    after_saturation = float((after_hsv[..., 1][skin] / 255.0).mean())
    saturation_delta = after_saturation - before_saturation
    chroma_shift = float(np.hypot(delta[1], delta[2]))
    soft_deviation = bool(
        abs(float(delta[0])) > 8.0
        or chroma_shift > 3.0
        or abs(saturation_delta) > 0.04
    )
    risk = bool(
        abs(float(delta[0])) > 20.0
        or chroma_shift > 7.0
        or abs(saturation_delta) > 0.12
        or delta[1] < -5.0
        or delta[1] > 7.0
        or delta[2] < -6.0
        or delta[2] > 8.0
    )
    return {
        "status": "RISK" if risk else "PASS",
        "soft_deviation": bool(soft_deviation and not risk),
        "confidence": round(float(np.clip(evidence_pixels / max(face_pixels * 0.35, 1.0), 0.0, 1.0)), 3),
        "evidence_pixels": evidence_pixels,
        "reason": "肤色亮度或色相发生灰、红、黄、青方向异常偏移" if risk else "可靠肤色区域未发生明显异常偏移",
        "before": {
            "lab_l": round(float(before_values[0]), 3),
            "lab_a": round(float(before_values[1] - 128.0), 3),
            "lab_b": round(float(before_values[2] - 128.0), 3),
            "saturation": round(before_saturation, 4),
        },
        "after": {
            "lab_l": round(float(after_values[0]), 3),
            "lab_a": round(float(after_values[1] - 128.0), 3),
            "lab_b": round(float(after_values[2] - 128.0), 3),
            "saturation": round(after_saturation, 4),
        },
        "delta": {
            "luminance": round(float(delta[0]), 3),
            "lab_a": round(float(delta[1]), 3),
            "lab_b": round(float(delta[2]), 3),
            "saturation": round(saturation_delta, 4),
        },
    }


def _noise_measurement(rgb: np.ndarray, mask: np.ndarray) -> dict[str, float]:
    lab = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    luma_residual = lab[..., 0] - cv2.GaussianBlur(lab[..., 0], (0, 0), sigmaX=1.1)
    a_residual = lab[..., 1] - cv2.GaussianBlur(lab[..., 1], (0, 0), sigmaX=1.1)
    b_residual = lab[..., 2] - cv2.GaussianBlur(lab[..., 2], (0, 0), sigmaX=1.1)
    return {
        "luma_noise": float(np.mean(np.abs(luma_residual[mask]))),
        "chroma_noise": float(np.mean(np.hypot(a_residual[mask], b_residual[mask]))),
    }


def _review_noise(source_rgb: np.ndarray, candidate_rgb: np.ndarray) -> dict[str, Any]:
    luminance = _luminance(source_rgb)
    gradient_x = cv2.Sobel(luminance, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(luminance, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(gradient_x, gradient_y)
    dark = luminance < 108.0
    flat_dark = dark & (gradient < 12.0)
    evidence_pixels = int(flat_dark.sum())
    required = max(64, int(flat_dark.size * 0.004))
    if int(dark.sum()) < required:
        return {
            "status": "NOT_APPLICABLE",
            "soft_deviation": False,
            "confidence": 0.0,
            "evidence_pixels": evidence_pixels,
            "reason": "画面缺少可复核的暗部区域",
            "before": None,
            "after": None,
        }
    if evidence_pixels < required:
        return {
            "status": "LOW_CONFIDENCE",
            "soft_deviation": False,
            "confidence": round(float(evidence_pixels / max(required, 1)), 3),
            "evidence_pixels": evidence_pixels,
            "reason": "暗部存在但平坦区域不足，未用文字、纹理或边缘代替噪声判断",
            "before": None,
            "after": None,
        }
    before = _noise_measurement(source_rgb, flat_dark)
    after = _noise_measurement(candidate_rgb, flat_dark)
    luma_risk = bool(
        after["luma_noise"] > 1.20
        and after["luma_noise"] > max(before["luma_noise"] * 1.80, before["luma_noise"] + 0.90)
    )
    chroma_risk = bool(
        after["chroma_noise"] > 1.10
        and after["chroma_noise"] > max(before["chroma_noise"] * 1.80, before["chroma_noise"] + 0.75)
    )
    risk = bool(luma_risk or chroma_risk)
    soft_deviation = bool(
        after["luma_noise"] > before["luma_noise"] + 0.25
        or after["chroma_noise"] > before["chroma_noise"] + 0.22
    )
    return {
        "status": "RISK" if risk else "PASS",
        "soft_deviation": bool(soft_deviation and not risk),
        "confidence": round(float(np.clip(evidence_pixels / max(flat_dark.size * 0.08, 1.0), 0.0, 1.0)), 3),
        "evidence_pixels": evidence_pixels,
        "reason": "暗部亮度或彩色噪点被放大" if risk else "暗部平坦区域噪点未明显增加",
        "before": {key: round(value, 4) for key, value in before.items()},
        "after": {key: round(value, 4) for key, value in after.items()},
    }


def _review_sharpening_and_halo(source_rgb: np.ndarray, candidate_rgb: np.ndarray) -> dict[str, Any]:
    source_luminance = _luminance(source_rgb)
    candidate_luminance = _luminance(candidate_rgb)
    gradient_x = cv2.Sobel(source_luminance, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(source_luminance, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(gradient_x, gradient_y)
    edge_threshold = max(18.0, float(np.percentile(gradient, 86)))
    edge_seed = gradient >= edge_threshold
    evidence_pixels = int(edge_seed.sum())
    required = max(48, int(edge_seed.size * 0.001))
    if evidence_pixels < required:
        return {
            "status": "NOT_APPLICABLE",
            "soft_deviation": False,
            "confidence": 0.0,
            "evidence_pixels": evidence_pixels,
            "reason": "画面缺少足够的高反差边缘",
            "before": None,
            "after": None,
        }
    edge_band = cv2.dilate(edge_seed.astype(np.uint8), np.ones((5, 5), dtype=np.uint8), iterations=1).astype(bool)
    source_min = cv2.erode(source_luminance, np.ones((3, 3), dtype=np.uint8))
    source_max = cv2.dilate(source_luminance, np.ones((3, 3), dtype=np.uint8))
    positive_overshoot = edge_band & (candidate_luminance > source_max + 4.0)
    negative_overshoot = edge_band & (candidate_luminance < source_min - 4.0)
    overshoot = positive_overshoot | negative_overshoot
    overshoot_ratio = float(overshoot.sum() / max(edge_band.sum(), 1))
    positive_overshoot_ratio = float(positive_overshoot.sum() / max(edge_band.sum(), 1))
    negative_overshoot_ratio = float(negative_overshoot.sum() / max(edge_band.sum(), 1))
    source_residual = source_luminance - cv2.GaussianBlur(source_luminance, (0, 0), sigmaX=1.25)
    candidate_residual = candidate_luminance - cv2.GaussianBlur(candidate_luminance, (0, 0), sigmaX=1.25)
    before_edge_detail = float(np.mean(np.abs(source_residual[edge_band])))
    after_edge_detail = float(np.mean(np.abs(candidate_residual[edge_band])))
    residual_delta = float(np.mean(np.abs(candidate_residual[edge_band] - source_residual[edge_band])))
    risk = bool(
        (
            positive_overshoot_ratio > 0.006
            and negative_overshoot_ratio > 0.006
            and overshoot_ratio > 0.02
            and residual_delta > 2.0
        )
        or (after_edge_detail > before_edge_detail * 1.65 + 0.8 and residual_delta > 2.2)
    )
    soft_deviation = bool(
        residual_delta > 0.9
        or after_edge_detail > before_edge_detail * 1.20 + 0.25
    )
    return {
        "status": "RISK" if risk else "PASS",
        "soft_deviation": bool(soft_deviation and not risk),
        "confidence": round(float(np.clip(evidence_pixels / max(edge_seed.size * 0.04, 1.0), 0.0, 1.0)), 3),
        "evidence_pixels": evidence_pixels,
        "reason": "高反差边缘出现过冲、黑白边或光晕带" if risk else "高反差边缘未出现明显异常过冲或光晕",
        "before": {"edge_detail": round(before_edge_detail, 4), "overshoot_ratio": 0.0},
        "after": {
            "edge_detail": round(after_edge_detail, 4),
            "overshoot_ratio": round(overshoot_ratio, 5),
            "positive_overshoot_ratio": round(positive_overshoot_ratio, 5),
            "negative_overshoot_ratio": round(negative_overshoot_ratio, 5),
            "residual_delta": round(residual_delta, 4),
        },
    }


def _post_process_review(
    source_rgb: np.ndarray,
    candidate_rgb: np.ndarray,
    before_metrics: dict[str, float],
    focus_mask: np.ndarray,
    background_mask: np.ndarray,
    strong_color_mask: np.ndarray,
    analysis: dict[str, Any],
    face_mask: np.ndarray | None = None,
    candidate_factory: Callable[[dict[str, float]], tuple[np.ndarray, dict[str, Any], dict[str, Any]]] | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    strategy_id = str(analysis["strategy_id"])
    normal_image = strategy_id in {"NORMAL_DESIGN_PROTECTION", "RISK_LIMITED_PROTECTION", "LOCAL_CORRECTION_REQUIRED"}
    strong_before = _region_saturation(source_rgb, strong_color_mask)
    attempts: list[dict[str, Any]] = []
    selected = candidate_rgb.astype(np.uint8)
    selected_parameters: dict[str, Any] = {}
    selected_analysis: dict[str, Any] = {}
    selected_violations: list[str] = []
    selected_checks: dict[str, Any] = {}
    detected_risks: list[str] = []
    soft_deviations: list[str] = []
    convergence_actions: list[str] = []
    quality_flags: list[str] = []
    reduction_reasons: dict[str, list[str]] = {}
    scales = {"tone": 1.0, "white_balance": 1.0, "shadow": 1.0, "person": 1.0, "skin": 1.0, "detail": 1.0, "color": 1.0}
    current = candidate_rgb.astype(np.uint8)
    final_candidate_level = "FULL"
    face_review_mask = face_mask if face_mask is not None else np.zeros(source_rgb.shape[:2], dtype=np.float32)

    for attempt_index in range(4):
        if attempt_index > 0:
            global_scales = [scales[key] for key in ("tone", "white_balance", "shadow", "person", "detail", "color")]
            final_candidate_level = (
                f"LOCAL_SKIN_{attempt_index}"
                if scales["skin"] < 0.999 and min(global_scales) >= 0.999
                else f"REDUCED_{attempt_index}"
            )
            if candidate_factory is not None:
                current, selected_parameters, selected_analysis = candidate_factory(scales)
            else:
                blend = min(scales.values())
                current = np.clip(
                    source_rgb.astype(np.float32) * (1.0 - blend) + candidate_rgb.astype(np.float32) * blend,
                    0,
                    255,
                ).astype(np.uint8)
        after = _metrics(current, focus_mask, background_mask)
        strong_after = _region_saturation(current, strong_color_mask)
        foreground_gain = after["foreground_luminance"] - before_metrics["foreground_luminance"]
        background_gain = after["background_luminance"] - before_metrics["background_luminance"]
        violations: list[str] = []
        attempt_soft_deviations: list[str] = []
        black_shift = after["black_point"] - before_metrics["black_point"]
        black_delta = abs(black_shift)
        highlight_delta = after["highlight_ratio"] - before_metrics["highlight_ratio"]
        dynamic_range_loss = before_metrics["dynamic_range"] - after["dynamic_range"]
        transparency_curve = analysis.get("tonal_curve_mode") == "floating_black_transparency_layering"
        if transparency_curve:
            if black_shift > 5.0:
                violations.append("通透层次整理反向抬高黑位")
            elif black_shift < -22.0 or (after["black_point"] < 8.0 and black_shift < -8.0):
                violations.append("通透层次整理造成黑位压死风险")
            elif black_shift < -18.0:
                attempt_soft_deviations.append("通透层次整理的黑位回落接近保护边界")
            elif black_shift < -8.0:
                attempt_soft_deviations.append("通透层次整理执行受控黑位回落")
        elif normal_image and black_delta > 2.0:
            violations.append("正常图片黑位偏移超出保护范围")
        elif black_delta > 10.0:
            violations.append("黑位发生明显堵塞或漂移")
        elif black_delta > 4.0:
            attempt_soft_deviations.append("黑位发生小幅统计变化")
        if highlight_delta > 0.02:
            violations.append("高光出现明显损失")
        elif highlight_delta > 0.004:
            attempt_soft_deviations.append("高光占比小幅变化")
        if not normal_image and after["local_contrast"] < before_metrics["local_contrast"] - 0.12:
            attempt_soft_deviations.append("局部层次小幅下降")
        saturation_tolerance = 0.06 if strategy_id == "COLOR_CAST_AND_TONE_BALANCE" and analysis.get("white_balance_applied") else 0.018
        saturation_loss = before_metrics["mean_saturation"] - after["mean_saturation"]
        if saturation_loss > 0.08:
            violations.append("全局色彩强度发生明显损失")
        elif saturation_loss > saturation_tolerance:
            attempt_soft_deviations.append("全局色彩强度小幅变化")
        if analysis["strong_color_protection_enabled"] and strong_before > 0.0:
            strong_color_loss = strong_before - strong_after
            if strong_color_loss > 0.04:
                violations.append("强色区域发生明显失真")
            elif strong_color_loss > 0.012:
                attempt_soft_deviations.append("强色区域色彩强度小幅变化")
        if dynamic_range_loss > 35.0:
            violations.append("动态范围发生明显收缩")
        elif dynamic_range_loss > 12.0:
            attempt_soft_deviations.append("动态范围小幅收缩")
        if analysis["person_local_adjustment_enabled"] and foreground_gain <= background_gain + 2.0:
            attempt_soft_deviations.append("主体与背景增益分离不足")
        if normal_image and abs(after["mean_luminance"] - before_metrics["mean_luminance"]) > 2.5:
            violations.append("正常图片亮度变化过大")

        checks = {
            "white_balance_review": _review_white_balance(source_rgb, current, strong_color_mask, analysis),
            "skin_tone_review": _review_skin_tone(source_rgb, current, face_review_mask, analysis),
            "noise_review": _review_noise(source_rgb, current),
            "sharpening_and_halo_review": _review_sharpening_and_halo(source_rgb, current),
        }
        risk_labels = {
            "white_balance_review": "白平衡偏差风险",
            "skin_tone_review": "肤色偏差风险",
            "noise_review": "暗部或彩色噪点放大风险",
            "sharpening_and_halo_review": "锐化过冲或光晕风险",
        }
        quality_flag_by_violation = {
            "通透层次整理反向抬高黑位": "BLACK_POINT_DRIFT",
            "通透层次整理造成黑位压死风险": "BLACK_CRUSH",
            "正常图片黑位偏移超出保护范围": "BLACK_POINT_DRIFT",
            "黑位发生明显堵塞或漂移": "BLACK_POINT_DRIFT",
            "高光出现明显损失": "HIGHLIGHT_LOSS",
            "全局色彩强度发生明显损失": "SATURATION_LOSS",
            "强色区域发生明显失真": "KEY_COLOR_DISTORTION",
            "动态范围发生明显收缩": "DYNAMIC_RANGE_LOSS",
            "正常图片亮度变化过大": "LUMINANCE_DRIFT",
            "白平衡偏差风险": "WHITE_BALANCE_SHIFT",
            "肤色偏差风险": "SKIN_TONE_SHIFT",
            "暗部或彩色噪点放大风险": "NOISE_AMPLIFICATION",
            "锐化过冲或光晕风险": "HALO_OR_OVERSHOOT",
        }
        risk_keys = [key for key, value in checks.items() if value["status"] == "RISK"]
        violations.extend(risk_labels[key] for key in risk_keys)
        for key, value in checks.items():
            if value.get("soft_deviation"):
                attempt_soft_deviations.append(f"{risk_labels[key]}的轻微统计偏差")
        for violation in violations:
            if violation not in detected_risks:
                detected_risks.append(violation)
            quality_flag = quality_flag_by_violation.get(violation)
            if quality_flag and quality_flag not in quality_flags:
                quality_flags.append(quality_flag)
        for deviation in attempt_soft_deviations:
            if deviation not in soft_deviations:
                soft_deviations.append(deviation)
        attempts.append(
            {
                "candidate_level": final_candidate_level,
                "strength_scales": {key: round(value, 4) for key, value in scales.items()},
                "violations": list(violations),
                "hard_risks": list(violations),
                "soft_deviations": list(attempt_soft_deviations),
                "check_statuses": {key: value["status"] for key, value in checks.items()},
                "reviews": checks,
            }
        )
        selected = current
        selected_violations = violations
        selected_checks = checks
        if not violations:
            break

        previous_scales = dict(scales)

        def reduce_responsible(parameter: str, multiplier: float, reason: str) -> None:
            scales[parameter] *= multiplier
            reasons = reduction_reasons.setdefault(parameter, [])
            if reason not in reasons:
                reasons.append(reason)

        if "white_balance_review" in risk_keys:
            reduce_responsible("white_balance", 0.55, "WHITE_BALANCE_SHIFT")
            reduce_responsible("color", 0.75, "WHITE_BALANCE_SHIFT")
            convergence_actions.append("降低白平衡与通道修正后重新生成候选")
        if "skin_tone_review" in risk_keys:
            reduce_responsible("skin", 0.45, "SKIN_TONE_SHIFT")
            convergence_actions.append("仅降低肤色区域处理强度后重新生成候选，保留全局明暗、层次与主体增益")
        if "noise_review" in risk_keys:
            reduce_responsible("shadow", 0.55, "NOISE_AMPLIFICATION")
            reduce_responsible("detail", 0.45, "NOISE_AMPLIFICATION")
            convergence_actions.append("降低阴影提亮、清晰度与局部对比强度后重新生成候选")
        if "sharpening_and_halo_review" in risk_keys:
            reduce_responsible("detail", 0.40, "HALO_OR_OVERSHOOT")
            reduce_responsible("tone", 0.72, "HALO_OR_OVERSHOOT")
            convergence_actions.append("降低清晰度、锐化与局部对比强度后重新生成候选")
        color_loss_responsibility = (
            (("white_balance", 0.72),)
            if analysis.get("white_balance_applied")
            else (("color", 0.70),)
        )
        key_color_responsibility = (
            (("white_balance", 0.72),)
            if analysis.get("white_balance_applied")
            else (("color", 0.60),)
        )
        direct_risk_actions = {
            "通透层次整理反向抬高黑位": (("tone", 0.72), ("shadow", 0.70)),
            "通透层次整理造成黑位压死风险": (("tone", 0.72), ("shadow", 0.70)),
            "正常图片黑位偏移超出保护范围": (("tone", 0.72), ("shadow", 0.70)),
            "黑位发生明显堵塞或漂移": (("tone", 0.72), ("shadow", 0.70)),
            "高光出现明显损失": (("tone", 0.68),),
            "全局色彩强度发生明显损失": color_loss_responsibility,
            "强色区域发生明显失真": key_color_responsibility,
            "动态范围发生明显收缩": (("tone", 0.72), ("shadow", 0.65)),
            "正常图片亮度变化过大": (("tone", 0.70),),
        }
        for violation in violations:
            responsible = direct_risk_actions.get(violation)
            if not responsible:
                continue
            flag = quality_flag_by_violation[violation]
            for parameter, multiplier in responsible:
                reduce_responsible(parameter, multiplier, flag)
            convergence_actions.append(f"仅降低{flag}责任参数后重新生成候选")
        if scales == previous_scales:
            break

    if candidate_factory is None and detected_risks:
        selected_violations = list(detected_risks)

    if selected_violations:
        final_candidate_level = "ORIGINAL"
        selected = source_rgb.astype(np.uint8).copy()
        selected_parameters = {
            "global_gamma": 1.0,
            "contrast_strength": 0.0,
            "local_contrast_strength": 0.0,
            "shadow_lift": 0.0,
            "highlight_compression": 0.0,
            "local_luminance_strength": 0.0,
            "selective_color_strength": 0.0,
            "clarity_strength": 0.0,
            "convergence_scales": {key: 0.0 for key in scales},
            "visual_severity": str(analysis.get("visual_severity") or "MILD"),
            "visual_severity_score": float(analysis.get("visual_severity_score") or 0.0),
            "visual_gain": 0.0,
            "midtone_lift": 0.0,
            "black_reconstruction": 0.0,
            "subject_target_gain": 0.0,
            "skin_local_convergence_scale": 0.0,
            "spatial_layering_strength": 0.0,
        }
        selected_analysis = {
            "person_local_adjustment_enabled": False,
            "foreground_local_adjustment_enabled": False,
            "local_contrast_enabled": False,
            "color_balance_enabled": False,
            "clarity_enabled": False,
            "skin_local_convergence_applied": False,
        }
        selected_checks = {
            "white_balance_review": _review_white_balance(source_rgb, selected, strong_color_mask, analysis),
            "skin_tone_review": _review_skin_tone(source_rgb, selected, face_review_mask, analysis),
            "noise_review": _review_noise(source_rgb, selected),
            "sharpening_and_halo_review": _review_sharpening_and_halo(source_rgb, selected),
        }
        selected_violations = [
            value["reason"] for value in selected_checks.values() if value["status"] == "RISK"
        ]
        attempts.append(
            {
                "candidate_level": "ORIGINAL",
                "strength_scales": {key: 0.0 for key in scales},
                "violations": list(selected_violations),
                "hard_risks": list(selected_violations),
                "soft_deviations": [],
                "check_statuses": {key: value["status"] for key, value in selected_checks.items()},
                "reviews": selected_checks,
            }
        )
        convergence_actions.append("候选未能安全收敛，采用接近原图的保护性结果")

    rollback_applied = final_candidate_level != "FULL"
    evaluated_scales = next(
        (
            attempt["strength_scales"]
            for attempt in reversed(attempts)
            if attempt["candidate_level"] != "ORIGINAL"
        ),
        {key: 1.0 for key in scales},
    )
    strength_reduction_items = {
        key: {
            "initial": 1.0,
            "final": round(float(evaluated_scales[key]), 4),
            "responsible_quality_flags": reduction_reasons.get(key, []),
        }
        for key in scales
        if float(evaluated_scales[key]) < 0.999
    }
    selected_candidate_scope = "SKIN_LOCAL" if final_candidate_level.startswith("LOCAL_SKIN_") else ("FULL_IMAGE" if rollback_applied else "NONE")
    limited_checks = [
        key for key, value in selected_checks.items() if value["status"] in {"LOW_CONFIDENCE", "NOT_APPLICABLE"}
    ]
    return selected, {
        "status": "PASS" if not selected_violations else "PROTECTIVE_FALLBACK",
        "post_review_complete": True,
        "rollback_applied": rollback_applied,
        "selected_candidate_blend": 1.0 if final_candidate_level == "FULL" else (0.0 if final_candidate_level == "ORIGINAL" else round(min(scales.values()), 2)),
        "selected_candidate_scope": selected_candidate_scope,
        "attempts": attempts,
        "remaining_violations": selected_violations,
        "detected_risks": detected_risks,
        "quality_flags": quality_flags,
        "hard_risks": detected_risks,
        "soft_deviations": soft_deviations,
        "convergence_actions": convergence_actions,
        "rollback_reason": "；".join(detected_risks) if rollback_applied else None,
        "final_candidate_level": final_candidate_level,
        "strength_reduced": bool(strength_reduction_items),
        "strength_reduction_items": strength_reduction_items,
        "limited_evidence_checks": limited_checks,
        **selected_checks,
        "_selected_parameters": selected_parameters,
        "_selected_analysis": selected_analysis,
        "strong_color_saturation_before": round(strong_before, 4),
        "strong_color_saturation_after": round(_region_saturation(selected, strong_color_mask), 4),
    }


def _encoding_parameters(source_format: str, source_size: int, width: int, height: int) -> dict[str, Any]:
    if source_format != "JPEG":
        return {"format": "PNG", "compress_level": 7, "optimize": True}
    bytes_per_pixel = source_size / max(width * height, 1)
    if bytes_per_pixel < 0.20:
        quality, subsampling = 89, 1
    elif bytes_per_pixel < 0.38:
        quality, subsampling = 91, 1
    else:
        quality, subsampling = 93, 0
    return {
        "format": "JPEG",
        "quality": quality,
        "subsampling": subsampling,
        "optimize": True,
        "source_bytes_per_pixel": round(bytes_per_pixel, 4),
    }


def _save_image(
    image: Image.Image,
    output_path: Path,
    source_format: str,
    icc_profile: bytes | None,
    exif: Image.Exif | None,
    encoding: dict[str, Any],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    options: dict[str, Any] = {}
    if icc_profile:
        options["icc_profile"] = icc_profile
    if exif and len(exif):
        options["exif"] = exif.tobytes()
    if source_format == "JPEG":
        options.update({
            "quality": int(encoding["quality"]),
            "subsampling": int(encoding["subsampling"]),
            "optimize": True,
        })
        image.convert("RGB").save(output_path, format="JPEG", **options)
    else:
        options.update({"optimize": True, "compress_level": 7})
        image.save(output_path, format="PNG", **options)


def process_single_image(source_path: str | Path, output_path: str | Path) -> ColorCorrectionResult:
    source = Path(source_path).resolve()
    target = Path(output_path).resolve()
    if not source.is_file():
        raise FileNotFoundError("输入图片不存在或不可读取。")
    started = time.perf_counter()
    source_sha256 = _sha256(source)
    source_size = source.stat().st_size

    with Image.open(source) as opened:
        opened.load()
        source_format = str(opened.format or "").upper()
        if source_format not in {"PNG", "JPEG"}:
            raise ValueError("颜色校正仅支持 PNG、JPG、JPEG 图片。")
        oriented = ImageOps.exif_transpose(opened)
        width, height = oriented.size
        if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
            raise ValueError("图片尺寸超出颜色校正的安全处理范围。")
        icc_profile = opened.info.get("icc_profile")
        exif = opened.getexif()
        if exif:
            exif[274] = 1
        alpha = np.array(oriented.getchannel("A"), dtype=np.uint8) if "A" in oriented.getbands() else None
        rgb = np.array(oriented.convert("RGB"), dtype=np.uint8)

    faces = _detect_faces(rgb)
    focus_mask, background_mask, face_mask, analysis = _scene_masks(rgb.astype(np.float32), faces)
    strong_color_mask, strong_screen_mask, color_features = _color_region_features(rgb)
    before = _metrics(rgb, focus_mask, background_mask)
    low_key_design = bool(
        before["mean_luminance"] < 70.0
        and before["dynamic_range"] >= 170.0
        and before["local_contrast"] >= 6.0
        and before["mean_saturation"] >= 0.20
        and before["highlight_ratio"] <= 0.04
    )
    before["low_key_design_detected"] = low_key_design
    perception = _perceptual_decision(
        rgb,
        faces,
        face_mask,
        before,
        analysis,
        color_features,
        low_key_design,
    )
    analysis.update(perception)
    analysis["person_present"] = bool(perception["person"]["present"])
    suppress_global_white_balance = bool(
        perception["global_cast_direction"] == "none"
        or perception["processing_decision"] in {"ORIGINAL", "LOW", "LOCAL_REQUIRED"}
    )
    if low_key_design or suppress_global_white_balance:
        balanced = rgb.astype(np.float32)
        gains = [1.0, 1.0, 1.0]
        reason = {
            "mixed_light": "冷暖混合光环境保护",
            "legitimate_warm": "合理暖光环境保护",
            "strong_local_light": "局部强色光源保护",
            "backlight_environment": "逆光环境局部处理，阻断全局白平衡",
            "highlight_limited_evidence": "高光风险保护，中性色证据不用于全局校正",
            "insufficient_global_evidence": "全局色偏证据不足",
        }.get(str(perception["cast_interpretation"]), "低调设计色彩意图保护" if low_key_design else "环境与保护对象优先")
        white_balance = {
            "white_balance_confidence": 0.0,
            "neutral_pixel_ratio": perception["neutral_evidence_ratio"],
            "color_cast": reason,
            "color_cast_magnitude": 0.0,
            "white_balance_applied": False,
            "lab_neutral_cast_a": perception["neutral_cast_a"],
            "lab_neutral_cast_b": perception["neutral_cast_b"],
        }
    else:
        balanced, gains, white_balance = apply_safe_white_balance(rgb, perception)
    strategy = _select_strategy(before, analysis, white_balance, color_features, low_key_design, perception)
    strategy.update(_visual_severity(before, analysis, strategy, white_balance))
    if strategy["strategy_id"] in {"NORMAL_DESIGN_PROTECTION", "RISK_LIMITED_PROTECTION", "LOCAL_CORRECTION_REQUIRED"}:
        balanced = rgb.astype(np.float32)
        gains = [1.0, 1.0, 1.0]
        white_balance = {
            **white_balance,
            "color_cast": (
                "低调设计色彩意图保护"
                if low_key_design
                else "正常图片色彩关系保护"
                if strategy["strategy_id"] == "NORMAL_DESIGN_PROTECTION"
                else str(white_balance["color_cast"])
            ),
            "white_balance_applied": False,
        }
    def build_candidate(strength_scales: dict[str, float]) -> tuple[np.ndarray, dict[str, Any], dict[str, Any]]:
        white_balance_scale = float(np.clip(strength_scales.get("white_balance", 1.0), 0.0, 1.0))
        scaled_balanced = (
            rgb.astype(np.float32)
            + (balanced.astype(np.float32) - rgb.astype(np.float32)) * white_balance_scale
        )
        return _apply_adaptive_correction(
            rgb,
            scaled_balanced,
            before,
            focus_mask,
            background_mask,
            face_mask,
            strong_color_mask,
            strong_screen_mask,
            analysis,
            white_balance,
            strategy,
            strength_scales,
        )

    full_scales = {"tone": 1.0, "white_balance": 1.0, "shadow": 1.0, "person": 1.0, "detail": 1.0, "color": 1.0}
    corrected, adaptive_parameters, adaptive_analysis = build_candidate(full_scales)
    analysis.update(white_balance)
    analysis.update(adaptive_analysis)
    analysis.update(color_features)
    corrected, post_review = _post_process_review(
        rgb,
        corrected,
        before,
        focus_mask,
        background_mask,
        strong_color_mask,
        analysis,
        face_mask,
        build_candidate,
    )
    selected_parameters = post_review.pop("_selected_parameters", {})
    selected_analysis = post_review.pop("_selected_analysis", {})
    if selected_parameters:
        adaptive_parameters = selected_parameters
    if selected_analysis:
        analysis.update(selected_analysis)
    analysis["post_process_review"] = post_review
    analysis["post_review_complete"] = post_review["post_review_complete"]
    analysis["detected_risks"] = list(post_review["detected_risks"])
    analysis["hard_risks"] = list(post_review["hard_risks"])
    analysis["soft_deviations"] = list(post_review["soft_deviations"])
    analysis["convergence_actions"] = list(post_review["convergence_actions"])
    analysis["rollback_reason"] = post_review["rollback_reason"]
    analysis["final_candidate_level"] = post_review["final_candidate_level"]
    analysis["quality_flags"] = list(post_review["quality_flags"])
    analysis["strength_reduced"] = bool(post_review["strength_reduced"])
    analysis["strength_reduction_items"] = dict(post_review["strength_reduction_items"])
    analysis["white_balance_review"] = dict(post_review["white_balance_review"])
    analysis["skin_tone_review"] = dict(post_review["skin_tone_review"])
    analysis["noise_review"] = dict(post_review["noise_review"])
    analysis["sharpening_and_halo_review"] = dict(post_review["sharpening_and_halo_review"])
    effective_white_balance_scale = float(
        adaptive_parameters.get("convergence_scales", {}).get("white_balance", 1.0)
    )
    effective_white_balance_gains = [
        round(1.0 + (float(gain) - 1.0) * effective_white_balance_scale, 4) for gain in gains
    ]
    analysis["white_balance_effective_scale"] = round(effective_white_balance_scale, 4)
    analysis["white_balance_applied"] = bool(
        analysis.get("white_balance_applied") and effective_white_balance_scale >= 0.08
    )
    analysis["strong_color_saturation_before"] = post_review["strong_color_saturation_before"]
    analysis["strong_color_saturation_after"] = post_review["strong_color_saturation_after"]
    analysis["parameter_rollback_applied"] = post_review["rollback_applied"]
    d04_corrected = corrected.astype(np.uint8).copy()
    v2_faces = _detect_local_faces(rgb, faces)
    corrected, v2_global_gate = run_global_recovery(
        rgb,
        d04_corrected,
        analysis,
        v2_faces,
        strong_color_mask,
        before,
        focus_mask,
        background_mask,
        person_masks=_local_person_masks,
        metrics_fn=_metrics,
        noise_fn=_review_noise,
        halo_fn=_review_sharpening_and_halo,
    )
    global_v2_applied = bool(
        v2_global_gate["status"] == "PASS" and not np.array_equal(d04_corrected, corrected)
    )
    if global_v2_applied:
        analysis["final_candidate_level"] = (
            "COLOR_CORE_V2_FULL"
            if v2_global_gate.get("selected_strength") == 1.0
            else "COLOR_CORE_V2_REDUCED"
        )
    pre_local_corrected = corrected.astype(np.uint8).copy()
    global_fallback = analysis["final_candidate_level"] == "ORIGINAL" and not global_v2_applied
    local_eligible = bool(
        analysis["processing_decision"] == "LOCAL_REQUIRED" and not global_fallback
    )
    if local_eligible:
        local_faces = v2_faces
        corrected, local_parameters, local_analysis = _apply_local_person_correction(
            pre_local_corrected,
            local_faces,
            analysis,
            strong_screen_mask,
        )
    elif analysis["processing_decision"] == "LOCAL_REQUIRED" and global_fallback:
        corrected = pre_local_corrected.copy()
        local_parameters = {"mode": "skipped_global_fallback", "strength": 0.0}
        local_analysis = {
            "local_executor_applied": False,
            "local_execution": "skipped_global_fallback",
            "local_output_policy": "ORIGINAL_FALLBACK",
            "local_rollback_applied": False,
            "local_face_count": 0,
        }
    else:
        corrected, local_parameters, local_analysis = _apply_local_person_correction(
            pre_local_corrected,
            [],
            analysis,
            strong_screen_mask,
        )
    analysis.update(local_analysis)
    d03_corrected = corrected.astype(np.uint8).copy()
    v2_local_faces = (
        _detect_local_faces(d03_corrected, _detect_faces(d03_corrected))
        if local_eligible
        else []
    )
    corrected, v2_local_gate = run_local_recovery(
        d03_corrected,
        analysis,
        v2_local_faces,
        person_masks=_local_person_masks,
        color_features=_color_region_features,
        noise_fn=_review_noise,
        halo_fn=_review_sharpening_and_halo,
    )
    local_v2_applied = bool(
        v2_local_gate["status"] == "PASS" and not np.array_equal(d03_corrected, corrected)
    )
    if local_v2_applied:
        local_parameters = {**local_parameters, "color_core_v2": v2_local_gate.get("execution", {})}
        analysis.update(
            {
                "local_executor_applied": True,
                "local_execution": LOCAL_ROUTE_NAME,
                "local_output_policy": "D03_BASELINE_PLUS_COLOR_CORE_V2",
                "local_rollback_applied": False,
            }
        )
    v2_strength_reduced = bool(
        v2_global_gate.get("strength_reduced") or v2_local_gate.get("strength_reduced")
    )
    if v2_strength_reduced:
        analysis["strength_reduced"] = True
        reduction_items = dict(analysis["strength_reduction_items"])
        if v2_global_gate.get("strength_reduced"):
            reduction_items["color_core_v2_global"] = float(v2_global_gate.get("selected_strength", 0.0))
        if v2_local_gate.get("strength_reduced"):
            reduction_items["color_core_v2_local"] = float(v2_local_gate.get("selected_strength", 0.0))
        analysis["strength_reduction_items"] = reduction_items
    analysis["color_core_v2"] = {
        "version": COLOR_CORE_V2_VERSION,
        "global_route": GLOBAL_ROUTE_NAME,
        "local_route": LOCAL_ROUTE_NAME,
        "global_applied": global_v2_applied,
        "local_applied": local_v2_applied,
        "runtime_ground_truth_used": False,
    }
    analysis["safety_gate_v2"] = {
        "version": COLOR_CORE_V2_VERSION,
        "position": "FORMAL_FINAL_COLOR_OUTPUT_CHAIN",
        "global": v2_global_gate,
        "local": v2_local_gate,
        "runtime_ground_truth_used": False,
    }
    analysis["runtime_ground_truth_used"] = False
    analysis["pre_local_pixel_changed"] = bool(not np.array_equal(rgb, pre_local_corrected))
    analysis["local_pixel_changed"] = bool(not np.array_equal(pre_local_corrected, corrected))
    protective_strategies = {"NORMAL_DESIGN_PROTECTION", "RISK_LIMITED_PROTECTION", "LOCAL_CORRECTION_REQUIRED"}
    global_algorithm_applied = bool(
        global_v2_applied
        or (
            analysis["strategy_id"] not in protective_strategies
            and analysis["final_candidate_level"] != "ORIGINAL"
        )
    )
    algorithm_applied = bool(global_algorithm_applied or analysis["local_executor_applied"])
    algorithm_pixel_changed = bool(not np.array_equal(rgb, corrected)) if algorithm_applied else False
    analysis["global_algorithm_applied"] = global_algorithm_applied
    analysis["algorithm_applied"] = algorithm_applied
    analysis["algorithm_pixel_changed"] = algorithm_pixel_changed
    if global_v2_applied:
        global_execution = GLOBAL_ROUTE_NAME
    elif not global_algorithm_applied:
        global_execution = "none"
    elif adaptive_parameters.get("tonal_curve_mode") == "coordinated_global_underexposure":
        global_execution = "coordinated_global_tonal_recovery"
    elif adaptive_parameters.get("tonal_curve_mode") == "floating_black_transparency_layering":
        global_execution = "transparency_and_layering"
    elif analysis["white_balance_applied"]:
        global_execution = "global_white_balance"
    else:
        global_execution = "adaptive_existing_executor"
    analysis["global_execution"] = global_execution
    local_quality_flags: list[str] = []
    if analysis.get("local_rollback_applied"):
        if analysis.get("local_execution") in {
            "blocked_insufficient_person_evidence",
            "blocked_insufficient_contamination_evidence",
        }:
            local_quality_flags.append("LOCAL_EVIDENCE_INSUFFICIENT")
        if analysis.get("local_target_quality_pass") is False:
            local_quality_flags.append("LOCAL_TARGET_NEGATIVE_GAIN")
        if analysis.get("local_non_target_drift_pass") is False:
            local_quality_flags.append("LOCAL_NON_TARGET_DRIFT")
        if analysis.get("local_blend_quality_pass") is False:
            local_quality_flags.append("LOCAL_BLEND_OR_HALO_RISK")
    analysis["quality_flags"].extend(
        flag for flag in local_quality_flags if flag not in analysis["quality_flags"]
    )
    if global_fallback:
        global_quality_gate = "FALLBACK_ORIGINAL"
    elif analysis["strength_reduced"]:
        global_quality_gate = "ACCEPTED_REDUCED"
    elif global_algorithm_applied:
        global_quality_gate = "ACCEPTED_FULL"
    else:
        global_quality_gate = "ACCEPTED_PROTECTED_ORIGINAL"
    if local_v2_applied:
        local_quality_gate = "ACCEPTED_SAFETY_GATE_V2"
    elif analysis["processing_decision"] != "LOCAL_REQUIRED":
        local_quality_gate = "NOT_REQUIRED"
    elif global_fallback:
        local_quality_gate = "SKIPPED_GLOBAL_FALLBACK"
    elif analysis["local_executor_applied"]:
        local_quality_gate = "ACCEPTED"
    else:
        local_quality_gate = "ROLLED_BACK_TO_GLOBAL"
    if global_fallback:
        rollback_level = "ORIGINAL_FALLBACK"
        final_decision = "ORIGINAL_FALLBACK"
    elif analysis.get("local_rollback_applied"):
        rollback_level = "GLOBAL_ACCEPTED"
        final_decision = "GLOBAL_ACCEPTED_AFTER_LOCAL_ROLLBACK"
    elif analysis["strength_reduced"]:
        rollback_level = "GLOBAL_STRENGTH_REDUCED"
        final_decision = "FINAL_ACCEPTED"
    elif analysis["processing_decision"] == "ORIGINAL" and not algorithm_applied:
        rollback_level = "NONE"
        final_decision = "ORIGINAL_PROTECTED"
    else:
        rollback_level = "NONE"
        final_decision = "FINAL_ACCEPTED"
    analysis.update(
        {
            "initial_decision": analysis["processing_decision"],
            "global_applied": global_algorithm_applied,
            "global_execution": global_execution,
            "global_quality_gate": global_quality_gate,
            "local_applied": bool(analysis["local_executor_applied"]),
            "local_execution": analysis["local_execution"],
            "local_quality_gate": local_quality_gate,
            "rollback_level": rollback_level,
            "final_decision": final_decision,
            "processing_stages": [
                {"stage": "ORIGINAL", "status": "AVAILABLE"},
                {"stage": "GLOBAL_CANDIDATE", "status": "GENERATED"},
                {"stage": "GLOBAL_ACCEPTED", "status": global_quality_gate},
                {
                    "stage": "LOCAL_CANDIDATE",
                    "status": (
                        "GENERATED_ACCEPTED"
                        if analysis["local_executor_applied"]
                        else "GENERATED_ROLLED_BACK"
                        if analysis.get("local_rollback_applied")
                        else "SKIPPED_GLOBAL_FALLBACK"
                        if global_fallback and analysis["processing_decision"] == "LOCAL_REQUIRED"
                        else "NOT_REQUIRED"
                    ),
                },
                {"stage": "FINAL", "status": final_decision},
            ],
        }
    )
    if local_v2_applied:
        analysis["algorithm_execution"] = LOCAL_ROUTE_NAME
        analysis["result_conclusion"] = "已完成D-03人物局部处理与Color Core V2多光源颜色场恢复，并通过Safety Gate 2.0"
    elif global_v2_applied:
        analysis["algorithm_execution"] = GLOBAL_ROUTE_NAME
        analysis["result_conclusion"] = "已完成Color Core V2跨通道全局颜色恢复，并通过Safety Gate 2.0"
    elif analysis["local_executor_applied"]:
        analysis["algorithm_execution"] = analysis["local_execution"]
        analysis["result_conclusion"] = (
            "已在D-02处理结果上完成受控人物局部校正，非目标区域通过漂移门禁"
        )
    elif not algorithm_applied and analysis["processing_decision"] == "LOCAL_REQUIRED":
        analysis["algorithm_execution"] = "blocked_pending_local_executor"
        analysis["result_conclusion"] = "局部证据或质量门禁不足，已回退到D-02处理结果"
    elif not algorithm_applied:
        analysis["algorithm_execution"] = "none"
        analysis["result_conclusion"] = "未执行颜色或明暗算法变换，按原有设计关系保护输出"
    elif adaptive_parameters.get("tonal_curve_mode") == "coordinated_global_underexposure":
        analysis["algorithm_execution"] = "coordinated_global_tonal_recovery"
        analysis["result_conclusion"] = "已完成全局欠曝的五级明暗协调恢复，建议结合原图复核"
    elif adaptive_parameters.get("tonal_curve_mode") == "floating_black_transparency_layering":
        analysis["algorithm_execution"] = "transparency_and_layering"
        analysis["result_conclusion"] = "已完成黑位、中间调与白场的通透层次整理，建议结合原图复核"
    elif analysis["white_balance_applied"]:
        analysis["algorithm_execution"] = "global_white_balance"
        analysis["result_conclusion"] = "已完成可信全局色偏恢复，建议结合原图复核"
    else:
        analysis["algorithm_execution"] = "adaptive_existing_executor"
        analysis["result_conclusion"] = "图片已完成逐图策略校正，建议结合原图进行最终视觉确认"
    if alpha is not None:
        output_array = np.dstack([corrected, alpha])
        output_image = Image.fromarray(output_array, mode="RGBA")
    else:
        output_image = Image.fromarray(corrected, mode="RGB")

    encoding = _encoding_parameters(source_format, source_size, width, height)
    _save_image(output_image, target, source_format, icc_profile, exif, encoding)
    encoding_retry = False
    if source_format == "JPEG" and target.stat().st_size > max(int(source_size * 1.85), source_size + 420_000):
        encoding = {
            **encoding,
            "quality": max(86, int(encoding["quality"]) - 3),
            "subsampling": 2,
        }
        _save_image(output_image, target, source_format, icc_profile, exif, encoding)
        encoding_retry = True
    with Image.open(target) as verified:
        verified.load()
        if verified.size != (width, height) or str(verified.format or "").upper() != source_format:
            target.unlink(missing_ok=True)
            raise RuntimeError("颜色校正输出验证失败：尺寸或格式不一致。")
        if alpha is not None and not np.array_equal(np.array(verified.getchannel("A")), alpha):
            target.unlink(missing_ok=True)
            raise RuntimeError("颜色校正输出验证失败：透明通道发生变化。")

    after = _metrics(corrected, focus_mask, background_mask)
    foreground_gain = round(after["foreground_luminance"] - before["foreground_luminance"], 2)
    background_gain = round(after["background_luminance"] - before["background_luminance"], 2)
    gain_advantage = round(foreground_gain - background_gain, 2)
    analysis.update(
        {
            "foreground_luminance_before": before["foreground_luminance"],
            "foreground_luminance_after": after["foreground_luminance"],
            "foreground_luminance_gain": foreground_gain,
            "background_luminance_before": before["background_luminance"],
            "background_luminance_after": after["background_luminance"],
            "background_luminance_gain": background_gain,
            "foreground_background_gain_advantage": gain_advantage,
            "output_encoding_retry_applied": encoding_retry,
        }
    )
    applied_actions: list[str] = []
    if analysis["white_balance_applied"]:
        applied_actions.append("基于可信中性色的白平衡校正")
    if abs(adaptive_parameters["global_gamma"] - 1.0) >= 0.003 or adaptive_parameters["shadow_lift"] >= 0.5:
        applied_actions.append("自适应曝光与明暗层次校正")
    if adaptive_parameters["contrast_strength"] >= 0.025:
        applied_actions.append("黑白场与中间调对比关系重建")
    if adaptive_parameters["local_contrast_strength"] >= 0.025:
        applied_actions.append("受控中间调与局部层次分离")
    if adaptive_parameters["selective_color_strength"] >= 0.01:
        applied_actions.append("选择性色彩力量平衡")
    if analysis["person_local_adjustment_enabled"]:
        applied_actions.append("人物与前景独立提亮")
    if analysis["highlight_background_protection_enabled"]:
        applied_actions.append("LED屏与高亮背景保护")
    if analysis["strong_color_protection_enabled"]:
        applied_actions.append("强色区域独立保护")
    if analysis["skin_tone_protection_enabled"]:
        applied_actions.append("人物肤色与身份特征保护")
    if analysis.get("skin_local_convergence_applied"):
        applied_actions.append("肤色风险已局部收敛，保留全局明暗与空间层次")
    if analysis.get("local_execution") == "local_person_exposure" and analysis.get("local_executor_applied"):
        applied_actions.append("人物脸部与上半身中间调局部恢复")
    if analysis.get("local_execution") == "led_local_contamination" and analysis.get("local_executor_applied"):
        applied_actions.append("人物局部LED蓝光污染受控降低")
    if global_v2_applied:
        applied_actions.append("Color Core V2跨通道综合色彩恢复")
    if local_v2_applied:
        applied_actions.append("Color Core V2多光源人物局部颜色场恢复")
    if analysis["clarity_enabled"]:
        applied_actions.append("受控清晰度与暗部噪声保护")
    detected_issues: list[str] = [analysis["primary_issue"]]
    detected_issues.extend(item for item in analysis["secondary_issues"] if item not in detected_issues)
    if analysis["meeting_backlight_detected"]:
        issue = "检测到高亮背景与较暗人物/前景的明显亮度差"
        if issue not in detected_issues:
            detected_issues.append(issue)
    if analysis["color_cast_magnitude"] >= 1.5:
        detected_issues.append(f"检测到{analysis['color_cast']}")
    if before["dynamic_range"] < 125 or before["local_contrast"] < 4.2:
        detected_issues.append("画面层次或局部对比分离不足")
    if before["shadow_ratio"] >= 0.12:
        detected_issues.append("暗部风险占比较高")
    if before["highlight_ratio"] >= 0.05:
        detected_issues.append("高光风险区域较多")
    if analysis["normal_image_detected"]:
        detected_issues = ["当前图片曝光、色彩与层次基本正常，无需明显校正"]
    elif not detected_issues:
        detected_issues.append("未检测到需要强校正的明显问题")
    improvements = ["保留原始尺寸、构图与透明通道"]
    if analysis["white_balance_applied"]:
        improvements.append("可信中性色偏差已受控校正")
    if after["local_contrast"] > before["local_contrast"] + 0.05:
        improvements.append("中间调层次与局部清晰度已增强")
    if foreground_gain > 1.0:
        improvements.append(f"人物或前景平均亮度提升 {foreground_gain:.1f}")
    if before["shadow_ratio"] > after["shadow_ratio"]:
        improvements.append("深色区域堵塞比例已降低")
    if analysis["meeting_backlight_detected"]:
        improvements.append(f"人物提亮相对背景多 {gain_advantage:.1f}，高亮背景受保护")
    if analysis.get("local_executor_applied"):
        improvements.append("局部执行器已通过非目标漂移与自然融合门禁")
    if analysis["normal_image_detected"]:
        improvements.append("正常图片采用低强度保护性处理，避免不必要改色")
    if analysis["strong_color_protection_enabled"]:
        improvements.append("红色大屏、桌面或品牌强色已独立保护，未使用全图降饱和")
    if analysis["post_process_review"]["rollback_applied"]:
        improvements.append("处理后复核已降低参数强度，避免画面变灰、变平或过度增强")
    review_points = ["请复核肤色、LED屏文字与品牌色是否自然"]
    if analysis["white_balance_confidence"] < 0.35:
        review_points.append("中性色证据有限，白平衡未作强制校正")
    if not analysis["meeting_backlight_detected"]:
        review_points.append("未识别到强逆光，未启用会议人物独立提亮")
    if abs(after["mean_saturation"] - before["mean_saturation"]) > 0.02:
        review_points.append("饱和度变化较明显，建议重点复核")
    if before["black_point"] <= 1.0 or before["white_point"] >= 254.0:
        review_points.append("原图纯黑或纯白区域不存在可恢复细节，不宣称恢复")
    parameters = {
        "white_balance_gains": effective_white_balance_gains,
        "white_balance_confidence": analysis["white_balance_confidence"],
        "lab_neutral_cast_a": analysis.get("lab_neutral_cast_a", 0.0),
        "lab_neutral_cast_b": analysis.get("lab_neutral_cast_b", 0.0),
        **adaptive_parameters,
        "strategy_id": analysis["strategy_id"],
        "enabled_modules": list(analysis["enabled_modules"]),
        "post_process_review": analysis["post_process_review"],
        "color_core_v2": analysis["color_core_v2"],
        "safety_gate_v2": analysis["safety_gate_v2"],
        "jpeg_quality": encoding.get("quality"),
        "jpeg_subsampling": encoding.get("subsampling"),
        "source_bytes_per_pixel": encoding.get("source_bytes_per_pixel"),
        "encoding_retry_applied": encoding_retry,
        "skin_tone_protection": analysis["skin_tone_protection_enabled"],
        "highlight_background_protection": analysis["highlight_background_protection_enabled"],
        "noise_protection": analysis["noise_protection_enabled"],
        "algorithm_applied": algorithm_applied,
        "algorithm_execution": analysis["algorithm_execution"],
        "quality_control": {
            "initial_decision": analysis["initial_decision"],
            "global_applied": analysis["global_applied"],
            "global_execution": analysis["global_execution"],
            "global_quality_gate": analysis["global_quality_gate"],
            "local_applied": analysis["local_applied"],
            "local_execution": analysis["local_execution"],
            "local_quality_gate": analysis["local_quality_gate"],
            "strength_reduced": analysis["strength_reduced"],
            "strength_reduction_items": analysis["strength_reduction_items"],
            "rollback_level": analysis["rollback_level"],
            "quality_flags": analysis["quality_flags"],
            "final_decision": analysis["final_decision"],
            "algorithm_applied": analysis["algorithm_applied"],
            "processing_stages": analysis["processing_stages"],
        },
        "local_executor": local_parameters,
    }

    return ColorCorrectionResult(
        output_path=str(target),
        source_sha256=source_sha256,
        output_sha256=_sha256(target),
        source_format=source_format,
        output_format=source_format,
        width=width,
        height=height,
        source_size_bytes=source_size,
        output_size_bytes=target.stat().st_size,
        processing_time_ms=max(1, int(round((time.perf_counter() - started) * 1000))),
        analysis=analysis,
        before_metrics=before,
        after_metrics=after,
        detected_issues=detected_issues,
        improvements=improvements,
        review_points=review_points,
        applied_actions=applied_actions,
        parameters=parameters,
    )
