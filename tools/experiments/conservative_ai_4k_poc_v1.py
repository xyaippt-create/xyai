"""Offline conservative AI 4K Stage 2 PoC.

This module is intentionally isolated from the product pipeline. It only reads
the frozen Stage 1 manifest/candidates and writes a unique batch below
``artifacts/4k_stage2_ai_poc``. It never writes Settings, formal user output,
project tmp, or runtime_data.
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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.experiments import traditional_4k_baseline_v1 as stage1


STAGE1_ROOT = PROJECT_ROOT / "artifacts" / "4k_stage1_baseline"
STAGE2_ROOT = PROJECT_ROOT / "artifacts" / "4k_stage2_ai_poc"
DEFAULT_MANIFEST = STAGE1_ROOT / "golden_samples_manifest.json"
DEFAULT_STAGE1_RESULTS = STAGE1_ROOT / "results" / "4k_stage1_run_results.json"
DEFAULT_ROI_MANIFEST = STAGE1_ROOT / "comparisons" / "comparison_manifest.json"
DEFAULT_MODEL_ROOT = PROJECT_ROOT / "external_tools" / "realesrgan-ncnn-vulkan"
DEFAULT_MODEL_NAME = "realesrgan-x4plus"
FORMAL_4K_DIRECTORY = Path(r"D:\影界文件\输出\4K高清增强")
SETTINGS_PATH = PROJECT_ROOT / "settings" / "settings.json"
ORIGINAL_STAGE2_BATCH_ROOT = STAGE2_ROOT / "batch_20260722T170852_44bd772e"
AUDIT_REMEDIATION_BATCH_ROOT = STAGE2_ROOT / "batch_20260723T090034_audit_remediation_8b1edb4b"
BLOCKED_TRUTH_BATCH_ROOT = STAGE2_ROOT / "batch_20260723T120000_final_gate_truth_019f8c9d"
HDDE_SKILL_PATH = PROJECT_ROOT / ".agents" / "skills" / "hdde" / "SKILL.md"
HDDE_REPORT_TEMPLATE_PATH = (
    PROJECT_ROOT / ".agents" / "skills" / "hdde" / "assets" / "final-report-template.md"
)

ROUTE_A = "route_a_direct_ai"
ROUTE_B = "route_b_controlled_increment"
ROUTES = (ROUTE_A, ROUTE_B)
MODEL_VERSION = "Real-ESRGAN-ncnn-vulkan v0.2.5.0 portable 20220424"
MODEL_SOURCE = (
    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
    "realesrgan-ncnn-vulkan-20220424-windows.zip"
)
MODEL_LICENSE = "BSD-3-Clause"
MODEL_LICENSE_SOURCE = "https://github.com/xinntao/Real-ESRGAN/blob/master/LICENSE"
INFERENCE_PARAMETERS = {
    "model": DEFAULT_MODEL_NAME,
    "scale": 4,
    "tile_size": 128,
    "gpu_id": 0,
    "threads": "1:2:1",
    "tta": False,
    "output_format": "png",
    "face_enhancement": False,
    "beautification": False,
    "generative_texture_completion": False,
}
CONTROLLED_INCREMENT_PARAMETERS = {
    "detail_highpass_sigma": 1.2,
    "detail_clamp_per_channel": 12.0,
    "base_alpha": 0.35,
    "flat_region_alpha": 0.12,
    "high_contrast_edge_alpha": 0.12,
    "text_like_alpha": 0.04,
    "skin_alpha": 0.08,
    "high_saturation_alpha": 0.15,
    "alpha_edge_alpha": 0.0,
    "mask_feather_sigma": 1.2,
    "alpha_protection_expansion_pixels": 3,
}
MANDATORY_TECHNICAL_GATES = (
    "process_exit_validation",
    "source_validation",
    "decode_validation",
    "target_dimensions",
    "aspect_ratio",
    "format_validation",
    "alpha_validation",
    "geometry_validation",
    "orientation_validation",
    "tile_seam_validation",
)
FAILURE_PROBE_DEFAULT_RECORD = Path("failure.json")
RISK_LABELS = (
    "TEXT_STROKE_DRIFT",
    "TEXT_COUNTER_COLLAPSE",
    "TEXT_FAKE_DETAIL",
    "LOGO_EDGE_DRIFT",
    "FACE_IDENTITY_DRIFT",
    "FACE_FEATURE_RECONSTRUCTION",
    "SKIN_TEXTURE_FAKE",
    "HAIR_FAKE_DETAIL",
    "PRODUCT_STRUCTURE_DRIFT",
    "PACKAGING_TEXT_DRIFT",
    "MATERIAL_DRIFT",
    "COLOR_SHIFT",
    "LIGHTING_DRIFT",
    "BACKGROUND_BOKEH_DRIFT",
    "HALO",
    "RINGING",
    "OVER_SHARPEN",
    "FAKE_TEXTURE",
    "ALPHA_EDGE_CONTAMINATION",
    "TILE_SEAM",
)
FAILURE_STAGES = (
    "source_open",
    "source_validation",
    "model_inference",
    "model_decode",
    "normalize_4k",
    "safety_blend",
    "encode_save",
    "decode_validation",
    "metadata_hash",
)
REQUIRED_ROUTE_B_GEOMETRY_SEQUENCE = (
    ("source_open", "exif_transpose"),
    ("model_inference", "model_input"),
    ("model_decode", "model_super_resolution"),
    ("normalize_4k", "resize"),
    ("safety_blend", "pixel_blend"),
    ("encode_save", "encode"),
    ("decode_validation", "decode_measurement"),
)


class Stage2Error(RuntimeError):
    pass


class ModelProcessError(Stage2Error):
    def __init__(self, message: str, exit_code: int | None):
        self.exit_code = exit_code
        super().__init__(message)


class CandidateExecutionError(Stage2Error):
    def __init__(self, record: dict[str, Any]):
        self.record = record
        super().__init__(
            f"{record['sample_id']}:{record['candidate_route']}:{record['failure_stage']}:"
            f"{record['error_type']}:{record['error_message']}"
        )


def json_write(path: Path, payload: Any) -> None:
    stage1.atomic_write_json(path, payload)


def file_sha256(path: Path) -> str:
    return stage1.sha256_file(path)


def combined_model_sha256(param_path: Path, bin_path: Path) -> str:
    digest = hashlib.sha256()
    for path in (param_path, bin_path):
        digest.update(path.name.encode("utf-8"))
        digest.update(file_sha256(path).encode("ascii"))
    return digest.hexdigest()


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_batch_root(path: Path) -> Path:
    resolved = path.resolve()
    stage2 = STAGE2_ROOT.resolve()
    if not is_relative_to(resolved, stage2) or resolved == stage2:
        raise Stage2Error(f"STAGE2_BATCH_OUTSIDE_ALLOWED_ROOT:{resolved}")
    forbidden_exact = (
        PROJECT_ROOT.resolve(),
        (PROJECT_ROOT / "tmp").resolve(),
        (PROJECT_ROOT / "runtime_data").resolve(),
        FORMAL_4K_DIRECTORY.resolve(),
        STAGE1_ROOT.resolve(),
    )
    if resolved in forbidden_exact or is_relative_to(resolved, FORMAL_4K_DIRECTORY.resolve()):
        raise Stage2Error(f"STAGE2_BATCH_FORBIDDEN:{resolved}")
    return resolved


def validate_failure_probe_root(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    system_temp = Path(tempfile.gettempdir()).resolve()
    _reject_reparse_components(absolute, system_temp)
    resolved = absolute.resolve()
    if resolved == system_temp or not is_relative_to(resolved, system_temp):
        raise Stage2Error(f"FAILURE_PROBE_MUST_USE_ISOLATED_SYSTEM_TEMP:{resolved}")
    _reject_protected_probe_path(resolved)
    return resolved


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except FileNotFoundError:
        return False
    return bool(attributes & 0x400)


def _reject_reparse_components(path: Path, approved_root: Path) -> None:
    absolute = Path(os.path.abspath(path))
    lexical_root = Path(os.path.abspath(approved_root))
    if not is_relative_to(absolute, lexical_root):
        return
    current = lexical_root
    if current.exists() and _is_reparse_point(current):
        raise Stage2Error(f"FAILURE_PROBE_REPARSE_POINT_REJECTED:{current}")
    for part in absolute.relative_to(lexical_root).parts:
        current = current / part
        if current.exists() and _is_reparse_point(current):
            raise Stage2Error(f"FAILURE_PROBE_REPARSE_POINT_REJECTED:{current}")


def _protected_probe_paths() -> tuple[Path, ...]:
    return (
        SETTINGS_PATH.resolve(),
        FORMAL_4K_DIRECTORY.resolve(),
        PROJECT_ROOT.resolve(),
        STAGE1_ROOT.resolve(),
        ORIGINAL_STAGE2_BATCH_ROOT.resolve(),
        STAGE2_ROOT.resolve(),
    )


def _reject_protected_probe_path(path: Path) -> None:
    resolved = path.resolve()
    for protected in _protected_probe_paths():
        if resolved == protected or is_relative_to(resolved, protected):
            raise Stage2Error(f"FAILURE_PROBE_PROTECTED_PATH_REJECTED:{resolved}:{protected}")


def resolve_failure_probe_write_path(output_root: Path, requested_path: Path) -> Path:
    """Resolve one probe write target without creating files or directories."""

    root = validate_failure_probe_root(output_root)
    requested = Path(requested_path)
    if requested.is_absolute():
        raise Stage2Error(f"FAILURE_PROBE_RECORD_MUST_BE_RELATIVE:{requested}")
    if any(part == ".." for part in requested.parts):
        raise Stage2Error(f"FAILURE_PROBE_PATH_TRAVERSAL_REJECTED:{requested}")
    if not requested.parts or requested == Path("."):
        raise Stage2Error("FAILURE_PROBE_RECORD_PATH_EMPTY")
    lexical = Path(os.path.abspath(root / requested))
    _reject_reparse_components(lexical, root)
    resolved = lexical.resolve()
    if resolved == root or not is_relative_to(resolved, root):
        raise Stage2Error(f"FAILURE_PROBE_PATH_ESCAPE_REJECTED:{resolved}")
    _reject_protected_probe_path(resolved)
    return resolved


def capture_protected_state(manifest: dict[str, Any], stage1_results: dict[str, Any]) -> dict[str, Any]:
    return {
        "sources": {sample["sample_id"]: stage1.capture_file_state(Path(sample["source_path"])) for sample in manifest["samples"]},
        "snapshots": {
            sample["sample_id"]: stage1.capture_file_state(STAGE1_ROOT / "golden_samples" / sample["snapshot_file_name"])
            for sample in manifest["samples"]
        },
        "traditional_candidates": {
            f"{row['sample_id']}:{row['method']}": stage1.capture_file_state(Path(row["output_path"]))
            for row in stage1_results["candidates"]
        },
        "stage1_tree": stage1.directory_fingerprint(STAGE1_ROOT),
        "settings": stage1.capture_file_state(SETTINGS_PATH),
        "formal_4k_directory": stage1.directory_fingerprint(FORMAL_4K_DIRECTORY),
        "project_root_runtime_data": stage1.directory_fingerprint(PROJECT_ROOT / "runtime_data"),
        "agents": stage1.capture_file_state(PROJECT_ROOT / "AGENTS.md"),
        "hdde_skill": stage1.capture_file_state(HDDE_SKILL_PATH),
        "hdde_report_template": stage1.capture_file_state(HDDE_REPORT_TEMPLATE_PATH),
        "git_index": stage1.capture_file_state(PROJECT_ROOT / ".git" / "index"),
        "original_stage2_tree": stage1.directory_fingerprint(ORIGINAL_STAGE2_BATCH_ROOT),
        "audit_remediation_stage2_tree": stage1.directory_fingerprint(AUDIT_REMEDIATION_BATCH_ROOT),
        "blocked_truth_stage2_tree": stage1.directory_fingerprint(BLOCKED_TRUTH_BATCH_ROOT),
    }


def failure_record(
    sample_id: str,
    route: str,
    stage: str,
    exc: Exception,
    input_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    record = {
        "success": False,
        "technical_success": False,
        "technical_status": "FAIL",
        "sample_id": sample_id,
        "candidate_route": route,
        "model_name": DEFAULT_MODEL_NAME,
        "failure_stage": stage,
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "input_path": str(input_path.resolve()),
        "output_path": str(output_path.resolve()),
    }
    return apply_process_exit_contract(record, getattr(exc, "exit_code", None))


def candidate_stage(
    stage: str,
    action: Callable[[], Any],
    *,
    sample_id: str,
    route: str,
    input_path: Path,
    output_path: Path,
    fault_stage: str | None = None,
) -> Any:
    try:
        if fault_stage == stage:
            raise OSError(f"CONTROLLED_FAILURE:{stage}")
        return action()
    except CandidateExecutionError:
        raise
    except Exception as exc:
        raise CandidateExecutionError(failure_record(sample_id, route, stage, exc, input_path, output_path)) from exc


def model_metadata(model_root: Path) -> dict[str, Any]:
    exe = model_root / "realesrgan-ncnn-vulkan.exe"
    param = model_root / "models" / f"{DEFAULT_MODEL_NAME}.param"
    weights = model_root / "models" / f"{DEFAULT_MODEL_NAME}.bin"
    archive = model_root / "realesrgan-ncnn-vulkan-20220424-windows.zip"
    for path in (exe, param, weights, archive):
        if not path.is_file():
            raise Stage2Error(f"LOCAL_MODEL_COMPONENT_MISSING:{path}")
    return {
        "model_name": "RealESRGAN_x4plus",
        "model_version": MODEL_VERSION,
        "source": MODEL_SOURCE,
        "license": MODEL_LICENSE,
        "license_source": MODEL_LICENSE_SOURCE,
        "model_path": str(weights.resolve()),
        "model_param_path": str(param.resolve()),
        "model_size_bytes": weights.stat().st_size + param.stat().st_size,
        "model_sha256": file_sha256(weights),
        "model_param_sha256": file_sha256(param),
        "model_combined_sha256": combined_model_sha256(param, weights),
        "runtime_executable": str(exe.resolve()),
        "runtime_executable_sha256": file_sha256(exe),
        "release_archive_path": str(archive.resolve()),
        "release_archive_sha256": file_sha256(archive),
        "runtime_framework": "Real-ESRGAN ncnn Vulkan portable",
        "device": "detected_at_runtime",
        "precision": "ncnn Vulkan automatic; device capability recorded from verbose output",
        "inference_parameters": INFERENCE_PARAMETERS,
        "network_access": "NONE",
        "user_image_upload": False,
    }


def parse_device(output: str) -> dict[str, Any]:
    match = re.search(r"\[(\d+) ([^\]]+)\].*fp16-p/s/a=(\d+/\d+/\d+)", output.replace("\r", " ").replace("\n", " "))
    if not match:
        name = re.search(r"\[(\d+) ([^\]]+)\]", output)
        return {
            "gpu_id": int(name.group(1)) if name else None,
            "device_name": name.group(2) if name else "UNKNOWN_VULKAN_DEVICE",
            "fp16_capabilities": None,
        }
    return {"gpu_id": int(match.group(1)), "device_name": match.group(2), "fp16_capabilities": match.group(3)}


def run_model(model_root: Path, source: Path, raw_output: Path) -> dict[str, Any]:
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    exe = model_root / "realesrgan-ncnn-vulkan.exe"
    command = [
        str(exe.resolve()),
        "-i",
        str(source.resolve()),
        "-o",
        str(raw_output.resolve()),
        "-n",
        DEFAULT_MODEL_NAME,
        "-s",
        "4",
        "-t",
        "128",
        "-m",
        str((model_root / "models").resolve()),
        "-g",
        "0",
        "-j",
        "1:2:1",
        "-f",
        "png",
        "-v",
    ]
    started = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    elapsed = time.perf_counter() - started
    combined_output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    if completed.returncode != 0 or not raw_output.is_file():
        raise ModelProcessError(
            f"MODEL_PROCESS_FAILED:{completed.returncode}:{completed.stdout.strip()}:{completed.stderr.strip()}",
            completed.returncode,
        )
    return {
        "command": command,
        "exit_code": completed.returncode,
        "process_exit_status": process_exit_status(completed.returncode),
        "runtime_seconds": round(elapsed, 3),
        "device": parse_device(combined_output),
        "raw_output_path": str(raw_output.resolve()),
        "raw_output_size_bytes": raw_output.stat().st_size,
        "raw_output_sha256": file_sha256(raw_output),
        "runtime_output_tail": combined_output[-2000:],
    }


def open_normalized(path: Path) -> tuple[Image.Image, dict[str, Any]]:
    with Image.open(path) as opened:
        opened.load()
        info = dict(opened.info or {})
        encoded_dimensions = opened.size
        source_orientation = int(opened.getexif().get(274, 1) or 1)
        image = ImageOps.exif_transpose(opened).copy()
        image_format = str(opened.format or "UNKNOWN").upper()
    return image, {
        "format": "JPEG" if image_format == "JPG" else image_format,
        "icc_profile": info.get("icc_profile"),
        "source_orientation": source_orientation,
        "encoded_dimensions": list(encoded_dimensions),
        "normalized_dimensions": list(image.size),
    }


def attach_safe_alpha(rgb: Image.Image, base: Image.Image) -> Image.Image:
    if "A" not in base.getbands():
        return rgb.convert("RGB")
    r, g, b = rgb.convert("RGB").split()
    return Image.merge("RGBA", (r, g, b, base.getchannel("A")))


def save_candidate(image: Image.Image, destination: Path, icc_profile: bytes | None) -> None:
    if destination.exists():
        raise Stage2Error(f"STAGE2_CANDIDATE_ALREADY_EXISTS:{destination}")
    temp_path = stage1.save_png_temp(image, destination, icc_profile)
    os.replace(temp_path, destination)


def alpha_protection_mask(base: Image.Image) -> tuple[np.ndarray, dict[str, Any]]:
    height, width = base.height, base.width
    if "A" not in base.getbands():
        return np.zeros((height, width), dtype=bool), {
            "alpha_unique_value_count": 1,
            "semi_transparent_pixel_count": 0,
            "alpha_gradient_edge_pixel_count": 0,
            "alpha_boundary_pixel_count": 0,
            "alpha_protection_mask_pixel_count": 0,
            "alpha_protection_expansion_pixels": CONTROLLED_INCREMENT_PARAMETERS[
                "alpha_protection_expansion_pixels"
            ],
            "alpha_protection_mask_fraction": 0.0,
        }
    alpha = np.asarray(base.getchannel("A"), dtype=np.uint8)
    semi = (alpha > 0) & (alpha < 255)
    gradient = cv2.morphologyEx(alpha, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
    semi_u8 = semi.astype(np.uint8) * 255
    boundary = cv2.morphologyEx(semi_u8, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
    core = semi | gradient | boundary
    expansion = int(CONTROLLED_INCREMENT_PARAMETERS["alpha_protection_expansion_pixels"])
    if expansion > 0 and np.any(core):
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (expansion * 2 + 1, expansion * 2 + 1))
        protected = cv2.dilate(core.astype(np.uint8), kernel, iterations=1) > 0
    else:
        protected = core
    count = int(np.count_nonzero(protected))
    return protected, {
        "alpha_unique_value_count": int(np.unique(alpha).size),
        "semi_transparent_pixel_count": int(np.count_nonzero(semi)),
        "alpha_gradient_edge_pixel_count": int(np.count_nonzero(gradient)),
        "alpha_boundary_pixel_count": int(np.count_nonzero(boundary)),
        "alpha_protection_mask_pixel_count": count,
        "alpha_protection_expansion_pixels": expansion,
        "alpha_protection_mask_fraction": round(count / float(alpha.size), 8),
    }


def _composite_rgb(image: Image.Image, background: np.ndarray) -> np.ndarray:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint16)
    alpha = rgba[:, :, 3:4]
    return ((rgba[:, :, :3] * alpha + background.astype(np.uint16) * (255 - alpha) + 127) // 255).astype(
        np.uint8
    )


def alpha_safety_metrics(candidate: Image.Image, baseline: Image.Image) -> dict[str, Any]:
    protected, mask_metrics = alpha_protection_mask(baseline)
    baseline_has_alpha = "A" in baseline.getbands()
    candidate_has_alpha = "A" in candidate.getbands()
    metrics: dict[str, Any] = dict(mask_metrics)
    metrics["baseline_has_alpha"] = baseline_has_alpha
    metrics["candidate_has_alpha"] = candidate_has_alpha
    if not baseline_has_alpha:
        status = "PASS" if not candidate_has_alpha else "FAIL"
        metrics.update(
            {
                "alpha_channel_changed_pixels": 0,
                "alpha_edge_changed_pixels": 0,
                "alpha_edge_max_rgb_delta": 0,
                "non_protected_changed_pixels": int(
                    np.count_nonzero(np.any(np.asarray(candidate.convert("RGB")) != np.asarray(baseline.convert("RGB")), axis=2))
                ),
                "non_protected_max_rgb_delta": int(
                    np.max(
                        np.abs(
                            np.asarray(candidate.convert("RGB"), dtype=np.int16)
                            - np.asarray(baseline.convert("RGB"), dtype=np.int16)
                        )
                    )
                ),
                "black_composite_changed_pixels": 0,
                "white_composite_changed_pixels": 0,
                "checkerboard_composite_changed_pixels": 0,
                "black_edge_contamination": False,
                "white_edge_contamination": False,
                "color_edge_contamination": False,
                "status": status,
            }
        )
        return metrics
    if not candidate_has_alpha or candidate.size != baseline.size:
        metrics.update(
            {
                "alpha_channel_changed_pixels": baseline.width * baseline.height,
                "alpha_edge_changed_pixels": int(np.count_nonzero(protected)),
                "alpha_edge_max_rgb_delta": 255,
                "non_protected_changed_pixels": 0,
                "non_protected_max_rgb_delta": 0,
                "black_composite_changed_pixels": int(np.count_nonzero(protected)),
                "white_composite_changed_pixels": int(np.count_nonzero(protected)),
                "checkerboard_composite_changed_pixels": int(np.count_nonzero(protected)),
                "black_edge_contamination": True,
                "white_edge_contamination": True,
                "color_edge_contamination": True,
                "status": "FAIL",
            }
        )
        return metrics
    candidate_rgba = np.asarray(candidate.convert("RGBA"), dtype=np.uint8)
    baseline_rgba = np.asarray(baseline.convert("RGBA"), dtype=np.uint8)
    rgb_delta = np.abs(candidate_rgba[:, :, :3].astype(np.int16) - baseline_rgba[:, :, :3].astype(np.int16))
    rgb_changed = np.any(rgb_delta > 0, axis=2)
    alpha_changed = candidate_rgba[:, :, 3] != baseline_rgba[:, :, 3]
    outside = ~protected
    height, width = protected.shape
    checker = np.zeros((height, width, 3), dtype=np.uint8)
    yy, xx = np.indices((height, width))
    cells = ((xx // 16 + yy // 16) % 2) == 0
    checker[cells] = 224
    checker[~cells] = 176
    backgrounds = {
        "black": np.zeros((height, width, 3), dtype=np.uint8),
        "white": np.full((height, width, 3), 255, dtype=np.uint8),
        "checkerboard": checker,
    }
    composite_changes: dict[str, int] = {}
    for name, background in backgrounds.items():
        left = _composite_rgb(baseline, background)
        right = _composite_rgb(candidate, background)
        changed = np.any(left != right, axis=2) & protected
        composite_changes[name] = int(np.count_nonzero(changed))
    protected_count = int(np.count_nonzero(protected))
    gradient_count = int(mask_metrics["alpha_gradient_edge_pixel_count"])
    edge_changed = int(np.count_nonzero(rgb_changed & protected))
    edge_max = int(np.max(rgb_delta[protected])) if protected_count else 0
    status = "PASS"
    if gradient_count > 0 and protected_count == 0:
        status = "FAIL"
    if protected_count == protected.size and protected_count > 0:
        status = "FAIL"
    if int(np.count_nonzero(alpha_changed)) or edge_changed or edge_max:
        status = "FAIL"
    if any(composite_changes.values()):
        status = "FAIL"
    metrics.update(
        {
            "alpha_channel_changed_pixels": int(np.count_nonzero(alpha_changed)),
            "alpha_edge_changed_pixels": edge_changed,
            "alpha_edge_max_rgb_delta": edge_max,
            "non_protected_changed_pixels": int(np.count_nonzero(rgb_changed & outside)),
            "non_protected_max_rgb_delta": int(np.max(rgb_delta[outside])) if np.any(outside) else 0,
            "black_composite_changed_pixels": composite_changes["black"],
            "white_composite_changed_pixels": composite_changes["white"],
            "checkerboard_composite_changed_pixels": composite_changes["checkerboard"],
            "black_edge_contamination": composite_changes["black"] > 0,
            "white_edge_contamination": composite_changes["white"] > 0,
            "color_edge_contamination": composite_changes["checkerboard"] > 0,
            "status": status,
        }
    )
    return metrics


def controlled_increment(base: Image.Image, ai: Image.Image) -> tuple[Image.Image, dict[str, Any]]:
    base_rgb = np.asarray(base.convert("RGB"), dtype=np.float32)
    ai_rgb = np.asarray(ai.convert("RGB"), dtype=np.float32)
    if base_rgb.shape != ai_rgb.shape:
        raise Stage2Error(f"CONTROLLED_INCREMENT_SHAPE_MISMATCH:{base_rgb.shape}:{ai_rgb.shape}")
    delta = ai_rgb - base_rgb
    low = cv2.GaussianBlur(delta, (0, 0), CONTROLLED_INCREMENT_PARAMETERS["detail_highpass_sigma"])
    detail = np.clip(
        delta - low,
        -CONTROLLED_INCREMENT_PARAMETERS["detail_clamp_per_channel"],
        CONTROLLED_INCREMENT_PARAMETERS["detail_clamp_per_channel"],
    )

    base_u8 = base_rgb.astype(np.uint8)
    gray = cv2.cvtColor(base_u8, cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(base_u8, cv2.COLOR_RGB2HSV)
    ycrcb = cv2.cvtColor(base_u8, cv2.COLOR_RGB2YCrCb)
    edges = cv2.Canny(gray, 70, 170)
    adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 8
    )
    dark_strokes = ((gray < 130) & (edges > 0)).astype(np.uint8) * 255
    text_like = cv2.bitwise_or(dark_strokes, cv2.bitwise_and(adaptive, edges))
    text_like = cv2.dilate(text_like, np.ones((7, 7), np.uint8), iterations=1)
    skin = (
        (ycrcb[:, :, 1] > 132)
        & (ycrcb[:, :, 1] < 178)
        & (ycrcb[:, :, 2] > 84)
        & (ycrcb[:, :, 2] < 138)
        & (hsv[:, :, 1] > 20)
        & (hsv[:, :, 2] > 80)
    ).astype(np.uint8) * 255
    skin = cv2.dilate(skin, np.ones((15, 15), np.uint8), iterations=1)
    high_sat = ((hsv[:, :, 1] > 105) & (hsv[:, :, 2] > 80)).astype(np.uint8) * 255
    high_sat = cv2.dilate(high_sat, np.ones((5, 5), np.uint8), iterations=1)
    high_contrast = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)
    texture_strength = cv2.GaussianBlur(edges.astype(np.float32) / 255.0, (0, 0), 2.0)

    alpha = np.full(gray.shape, CONTROLLED_INCREMENT_PARAMETERS["base_alpha"], dtype=np.float32)
    alpha[texture_strength < 0.035] = CONTROLLED_INCREMENT_PARAMETERS["flat_region_alpha"]
    alpha[high_contrast > 0] = CONTROLLED_INCREMENT_PARAMETERS["high_contrast_edge_alpha"]
    alpha[high_sat > 0] = np.minimum(alpha[high_sat > 0], CONTROLLED_INCREMENT_PARAMETERS["high_saturation_alpha"])
    alpha[skin > 0] = CONTROLLED_INCREMENT_PARAMETERS["skin_alpha"]
    alpha[text_like > 0] = CONTROLLED_INCREMENT_PARAMETERS["text_like_alpha"]

    protected, protection_metrics = alpha_protection_mask(base)
    alpha = cv2.GaussianBlur(alpha, (0, 0), CONTROLLED_INCREMENT_PARAMETERS["mask_feather_sigma"])
    # The hard Alpha protection is deliberately re-applied after every operation
    # that can spread weights. This ordering is the safety boundary.
    alpha[protected] = CONTROLLED_INCREMENT_PARAMETERS["alpha_edge_alpha"]
    blended = np.clip(base_rgb + detail * alpha[:, :, None], 0, 255).astype(np.uint8)
    output = attach_safe_alpha(Image.fromarray(blended, mode="RGB"), base)
    safety = alpha_safety_metrics(output, base)
    return output, {
        "maximum_applied_channel_delta": round(float(np.max(np.abs(blended.astype(np.int16) - base_u8.astype(np.int16)))), 3),
        "mean_applied_channel_delta": round(float(np.mean(np.abs(blended.astype(np.int16) - base_u8.astype(np.int16)))), 6),
        "text_protected_pixels": int(np.count_nonzero(text_like)),
        "skin_protected_pixels": int(np.count_nonzero(skin)),
        "alpha_edge_protected_pixels": protection_metrics["alpha_protection_mask_pixel_count"],
        "alpha_protection": safety,
        "final_hard_protection_reapplied_after_feather": True,
        "parameters": CONTROLLED_INCREMENT_PARAMETERS,
    }


def alpha_status(image: Image.Image, baseline: Image.Image) -> str:
    return alpha_safety_metrics(image, baseline)["status"]


def color_metrics(candidate: Image.Image, baseline: Image.Image) -> dict[str, float]:
    candidate_bgr = cv2.cvtColor(np.asarray(candidate.convert("RGB")), cv2.COLOR_RGB2BGR)
    baseline_bgr = cv2.cvtColor(np.asarray(baseline.convert("RGB")), cv2.COLOR_RGB2BGR)
    candidate_lab = cv2.cvtColor(candidate_bgr, cv2.COLOR_BGR2LAB)
    baseline_lab = cv2.cvtColor(baseline_bgr, cv2.COLOR_BGR2LAB)
    delta = np.abs(candidate_lab.astype(np.float32) - baseline_lab.astype(np.float32))
    return {
        "mean_l_delta_vs_lanczos": round(float(np.mean(delta[:, :, 0])), 6),
        "mean_ab_delta_vs_lanczos": round(float(np.mean(delta[:, :, 1:])), 6),
        "maximum_lab_delta_vs_lanczos": round(float(np.max(delta)), 3),
    }


def seam_metric(candidate: Image.Image, raw_size: tuple[int, int], tile_output_size: int = 512) -> dict[str, Any]:
    gray = np.asarray(candidate.convert("L"), dtype=np.float32)
    height, width = gray.shape
    raw_width, raw_height = raw_size
    scores: list[float] = []
    for raw_boundary in range(tile_output_size, raw_width, tile_output_size):
        x = int(round(raw_boundary * width / raw_width))
        if 3 <= x < width - 3:
            boundary = float(np.mean(np.abs(gray[:, x] - gray[:, x - 1])))
            nearby = float(np.mean([np.mean(np.abs(gray[:, x + offset] - gray[:, x + offset - 1])) for offset in (-3, -2, 2, 3)]))
            scores.append(boundary / (nearby + 1.0))
    for raw_boundary in range(tile_output_size, raw_height, tile_output_size):
        y = int(round(raw_boundary * height / raw_height))
        if 3 <= y < height - 3:
            boundary = float(np.mean(np.abs(gray[y, :] - gray[y - 1, :])))
            nearby = float(np.mean([np.mean(np.abs(gray[y + offset, :] - gray[y + offset - 1, :])) for offset in (-3, -2, 2, 3)]))
            scores.append(boundary / (nearby + 1.0))
    maximum = max(scores, default=0.0)
    return {"boundary_count": len(scores), "maximum_boundary_gradient_ratio": round(maximum, 6), "status": "PASS" if maximum <= 2.5 else "REVIEW"}


def aggregate_mandatory_gates(gates: dict[str, str]) -> dict[str, Any]:
    missing = [name for name in MANDATORY_TECHNICAL_GATES if name not in gates]
    normalized = {name: str(gates.get(name, "UNKNOWN")).upper() for name in MANDATORY_TECHNICAL_GATES}
    blocking = [name for name, status in normalized.items() if status in {"FAIL", "BLOCKED", "UNKNOWN"}]
    reviews = [name for name, status in normalized.items() if status == "REVIEW"]
    invalid = [name for name, status in normalized.items() if status not in {"PASS", "REVIEW", "FAIL", "BLOCKED", "UNKNOWN"}]
    for name in missing + invalid:
        if name not in blocking:
            blocking.append(name)
        normalized[name] = "UNKNOWN"
    if any(normalized[name] == "FAIL" for name in blocking):
        technical_status = "FAIL"
    elif any(normalized[name] == "BLOCKED" for name in blocking):
        technical_status = "BLOCKED"
    elif blocking:
        technical_status = "UNKNOWN"
    elif reviews:
        technical_status = "REVIEW_REQUIRED"
    else:
        technical_status = "PASS"
    return {
        "success": technical_status == "PASS",
        "technical_status": technical_status,
        "blocking_gates": blocking,
        "review_required_gates": reviews,
        "mandatory_gates": normalized,
    }


def process_exit_status(exit_code: int | None) -> str:
    if exit_code is None:
        return "MISSING"
    return "SUCCESS" if exit_code == 0 else "FAILED"


def apply_process_exit_contract(record: dict[str, Any], exit_code: int | None) -> dict[str, Any]:
    record["exit_code"] = exit_code
    record["process_exit_status"] = process_exit_status(exit_code)
    if exit_code != 0:
        record["success"] = False
        record["technical_success"] = False
        record["technical_status"] = "FAIL"
    return record


def append_geometry_event(
    records: list[dict[str, Any]],
    *,
    sample_id: str,
    run_id: str,
    stage: str,
    operation: str,
    before_dimensions: tuple[int, int] | list[int],
    after_dimensions: tuple[int, int] | list[int],
    applied: bool,
    method: str,
    parameters: dict[str, Any] | None = None,
) -> None:
    records.append(
        {
            "sequence_index": len(records),
            "event_id": f"{run_id}:{stage}:{operation}",
            "sample_id": sample_id,
            "run_id": run_id,
            "stage": stage,
            "operation": operation,
            "applied": bool(applied),
            "before_dimensions": [int(value) for value in before_dimensions],
            "after_dimensions": [int(value) for value in after_dimensions],
            "method": method,
            "parameters": dict(parameters or {}),
        }
    )


def build_transform_trace(
    sample_id: str,
    run_id: str,
    source_dimensions: tuple[int, int],
    decoded_dimensions: tuple[int, int],
    expected_dimensions: tuple[int, int],
    actual_dimensions: tuple[int, int],
    *,
    source_orientation: int,
    operation_records: list[dict[str, Any]] | None,
    candidate_sha256: str | None,
) -> dict[str, Any]:
    ratio_status, ratio_error = stage1.aspect_status(decoded_dimensions, actual_dimensions)
    records = list(operation_records or [])
    required_fields = {
        "sequence_index", "event_id", "sample_id", "run_id", "stage", "operation", "applied",
        "before_dimensions", "after_dimensions", "method", "parameters",
    }
    event_fields_complete = bool(records) and all(required_fields.issubset(record) for record in records)
    observed_sequence = [(str(record.get("stage")), str(record.get("operation"))) for record in records]
    sequence_complete = observed_sequence == list(REQUIRED_ROUTE_B_GEOMETRY_SEQUENCE)
    sequence_indexes_valid = [record.get("sequence_index") for record in records] == list(range(len(records)))
    event_identity_valid = all(
        record.get("sample_id") == sample_id and record.get("run_id") == run_id for record in records
    )
    event_ids_unique = len({record.get("event_id") for record in records}) == len(records)

    dimension_values_valid = event_fields_complete
    if dimension_values_valid:
        try:
            before_dimensions = [tuple(int(value) for value in record["before_dimensions"]) for record in records]
            after_dimensions = [tuple(int(value) for value in record["after_dimensions"]) for record in records]
            dimension_values_valid = all(len(value) == 2 and min(value) > 0 for value in before_dimensions + after_dimensions)
        except (KeyError, TypeError, ValueError):
            dimension_values_valid = False
            before_dimensions = []
            after_dimensions = []
    else:
        before_dimensions = []
        after_dimensions = []
    dimension_chain_continuous = bool(records) and dimension_values_valid and all(
        after_dimensions[index] == before_dimensions[index + 1] for index in range(len(records) - 1)
    )
    source_chain_matches = bool(records) and dimension_values_valid and before_dimensions[0] == tuple(source_dimensions)
    decoded_chain_matches = bool(records) and dimension_values_valid and after_dimensions[0] == tuple(decoded_dimensions)
    final_chain_matches = bool(records) and dimension_values_valid and after_dimensions[-1] == tuple(actual_dimensions)
    decision, calculated_target = stage1.target_dimensions(*decoded_dimensions)
    target_rule_matches = decision == "PROCESS" and calculated_target == tuple(expected_dimensions)
    candidate_sha_valid = bool(candidate_sha256 and re.fullmatch(r"[0-9a-f]{64}", candidate_sha256))
    trace_valid = all(
        (
            event_fields_complete,
            sequence_complete,
            sequence_indexes_valid,
            event_identity_valid,
            event_ids_unique,
            dimension_values_valid,
            dimension_chain_continuous,
            source_chain_matches,
            decoded_chain_matches,
            final_chain_matches,
            target_rule_matches,
            candidate_sha_valid,
        )
    )
    trace_state = "VALID" if trace_valid else ("MISSING" if not records else "INVALID")

    def operation_state(name: str) -> dict[str, Any]:
        if not trace_valid:
            return {"applied": None, "status": "UNKNOWN", "parameters": None, "source": trace_state}
        matches = [record for record in records if record["operation"] == name and record["applied"]]
        return {
            "applied": bool(matches),
            "status": "PRESENT" if matches else "ABSENT",
            "parameters": [record["parameters"] for record in matches],
            "source": (
                [record["event_id"] for record in matches]
                if matches
                else "DERIVED_FROM_VALIDATED_ORDERED_EVENTS"
            ),
        }

    resize_record = next((record for record in records if record.get("operation") == "resize"), None)
    if trace_valid and resize_record is not None:
        resize_before = tuple(int(value) for value in resize_record["before_dimensions"])
        resize_after = tuple(int(value) for value in resize_record["after_dimensions"])
        resize_ratio_status, _ = stage1.aspect_status(resize_before, resize_after)
        resize_operation = {
            "applied": bool(resize_record["applied"]),
            "status": "PRESENT" if resize_record["applied"] else "ABSENT",
            "from_dimensions": list(resize_before),
            "to_dimensions": list(resize_after),
            "method": resize_record["method"],
            "parameters": resize_record["parameters"],
            "nonuniform_stretch": resize_ratio_status != "PASS",
            "source": resize_record["event_id"],
        }
    else:
        resize_operation = {
            "applied": None,
            "status": "UNKNOWN",
            "from_dimensions": None,
            "to_dimensions": None,
            "method": "UNKNOWN",
            "parameters": None,
            "nonuniform_stretch": None,
            "source": trace_state,
        }
    crop_operation = operation_state("crop")
    pad_operation = operation_state("pad")
    rotate_operation = operation_state("exif_transpose")
    model_input_record = next((record for record in records if record.get("operation") == "model_input"), None)
    model_output_record = next(
        (record for record in records if record.get("operation") == "model_super_resolution"), None
    )
    orientation_expected = source_orientation not in {0, 1}
    orientation_normalization_applied = rotate_operation["applied"]
    orientation_consistent = (
        None if orientation_normalization_applied is None else orientation_normalization_applied == orientation_expected
    )
    return {
        "sample_id": sample_id,
        "run_id": run_id,
        "source_dimensions": list(source_dimensions),
        "decoded_dimensions": list(decoded_dimensions),
        "source_orientation": int(source_orientation),
        "orientation_normalization_applied": orientation_normalization_applied,
        "orientation_consistent": orientation_consistent,
        "model_input_dimensions": (
            list(model_input_record["after_dimensions"]) if trace_valid and model_input_record else None
        ),
        "model_output_dimensions": (
            list(model_output_record["after_dimensions"]) if trace_valid and model_output_record else None
        ),
        "ordered_events": records,
        "expected_dimensions": list(expected_dimensions),
        "actual_dimensions": list(actual_dimensions),
        "aspect_ratio_error": round(float(ratio_error), 6),
        "candidate_sha256": candidate_sha256,
        "geometry_evidence_source": (
            "LIVE_PIPELINE_OPERATION_TRACE" if trace_valid else "MISSING_LIVE_OPERATION_TRACE"
        ),
        "trace_state": trace_state,
        "trace_complete": trace_valid,
        "required_sequence": [list(item) for item in REQUIRED_ROUTE_B_GEOMETRY_SEQUENCE],
        "observed_sequence": [list(item) for item in observed_sequence],
        "chain_validation": {
            "event_fields_complete": event_fields_complete,
            "sequence_complete": sequence_complete,
            "sequence_indexes_valid": sequence_indexes_valid,
            "event_identity_valid": event_identity_valid,
            "event_ids_unique": event_ids_unique,
            "dimension_values_valid": dimension_values_valid,
            "dimension_chain_continuous": dimension_chain_continuous,
            "source_chain_matches": source_chain_matches,
            "decoded_chain_matches": decoded_chain_matches,
            "final_chain_matches": final_chain_matches,
            "target_rule_matches": target_rule_matches,
            "candidate_sha_valid": candidate_sha_valid,
            "aspect_ratio_status": ratio_status,
        },
        "resize_operation": resize_operation,
        "crop_operation": crop_operation,
        "pad_operation": pad_operation,
        "rotate_operation": rotate_operation,
    }


def geometry_gate_from_trace(trace: dict[str, Any]) -> str:
    if trace.get("trace_state") == "MISSING":
        return "UNKNOWN"
    if trace.get("trace_state") != "VALID":
        return "FAIL"
    required_values = (
        trace["crop_operation"]["applied"],
        trace["pad_operation"]["applied"],
        trace["resize_operation"]["nonuniform_stretch"],
    )
    if any(value is None for value in required_values):
        return "UNKNOWN"
    failed = (
        bool(trace["crop_operation"]["applied"])
        or bool(trace["pad_operation"]["applied"])
        or bool(trace["resize_operation"]["nonuniform_stretch"])
        or list(trace["actual_dimensions"]) != list(trace["expected_dimensions"])
    )
    return "FAIL" if failed else "PASS"


def orientation_gate_from_trace(trace: dict[str, Any]) -> str:
    if trace.get("trace_state") == "MISSING":
        return "UNKNOWN"
    if trace.get("trace_state") != "VALID" or trace.get("orientation_consistent") is not True:
        return "FAIL"
    return "PASS"


def trace_status(value: bool | None, present: str, absent: str) -> str:
    if value is None:
        return "UNKNOWN"
    return present if value else absent


def image_identity(path: Path) -> dict[str, Any]:
    with Image.open(path) as opened:
        opened.load()
        image_format = str(opened.format or "UNKNOWN").upper()
        image = opened.copy()
    alpha_sha256 = None
    if "A" in image.getbands():
        alpha_sha256 = hashlib.sha256(image.getchannel("A").tobytes()).hexdigest()
    return {
        "path": str(path.resolve()),
        "file_sha256": file_sha256(path),
        "pixel_sha256": stage1.pixel_sha256(path),
        "dimensions": list(image.size),
        "format": "JPEG" if image_format == "JPG" else image_format,
        "mode": image.mode,
        "alpha_sha256": alpha_sha256,
    }


def build_route_b_structure_evidence(
    sample_id: str,
    candidate_path: Path,
    candidate: Image.Image,
    baseline: Image.Image,
    applicable_roi_records: list[dict[str, Any]],
    automatic_risk_precheck: str,
) -> dict[str, Any]:
    current_identity = image_identity(candidate_path)
    applicable_risks = [str(record["risk"]) for record in applicable_roi_records]
    alpha_metrics = alpha_safety_metrics(candidate, baseline)
    status = "PENDING_HUMAN_REVIEW" if automatic_risk_precheck == "PASS_NO_BLOCKING_SIGNAL" else "NOT_READY"
    return {
        "sample_id": sample_id,
        "route": ROUTE_B,
        "evidence_source": "HUMAN_VISUAL_REVIEW_REQUIRED",
        "validation_mode": "AUTOMATIC_TECHNICAL_RISK_PRECHECK_ONLY",
        "automatic_risk_precheck": automatic_risk_precheck,
        "applicable_risks": applicable_risks,
        "current_candidate": current_identity,
        "technical_observations": {
            "color_metrics_vs_lanczos": color_metrics(candidate, baseline),
            "alpha_safety_status": alpha_metrics["status"],
            "alpha_channel_changed_pixels": alpha_metrics["alpha_channel_changed_pixels"],
            "alpha_edge_changed_pixels": alpha_metrics["alpha_edge_changed_pixels"],
            "non_protected_changed_pixels": alpha_metrics["non_protected_changed_pixels"],
        },
        "human_review_checks": [
            {
                "risk": risk,
                "status": "PENDING_HUMAN_REVIEW",
                "basis": "AUTOMATIC_METRICS_CANNOT_PROVE_SEMANTIC_STRUCTURE_SAFETY",
            }
            for risk in applicable_risks
        ],
        "scalar_metrics_can_prove_structure_safety": False,
        "alpha_pass_can_prove_structure_safety": False,
        "technical_pass_can_prove_structure_safety": False,
        "historical_observations_can_prove_structure_safety": False,
        "status": status,
    }


def route_b_structure_status_for_blocked_run(
    structure_evidence_records: list[dict[str, Any]],
) -> str:
    # A technically blocked run is not ready for semantic structure review,
    # regardless of whether partial structure evidence was produced.
    _ = structure_evidence_records
    return "NOT_READY"


def candidate_record(
    sample: dict[str, Any],
    route: str,
    input_path: Path,
    output_path: Path,
    image: Image.Image,
    baseline: Image.Image,
    runtime_seconds: float,
    model_run: dict[str, Any],
    increment: dict[str, Any] | None,
    *,
    source_batch: str,
    revalidated_by_remediation: bool,
    lanczos_path: Path,
    structure_safety_status: str,
    structure_safety_evidence: dict[str, Any],
    route_decision: str,
    evidence_path: Path,
    run_id: str,
    run_started_at: str,
    run_ended_at: str,
    source_orientation: int = 1,
    transform_trace: dict[str, Any] | None = None,
    geometry_trace_path: Path | None = None,
) -> dict[str, Any]:
    decoded = stage1.verify_decode(output_path)
    decision, target = stage1.target_dimensions(sample["width"], sample["height"])
    if decision != "PROCESS" or target is None:
        raise Stage2Error(f"INVALID_STAGE2_SAMPLE_TARGET:{sample['sample_id']}:{decision}")
    ratio_status, ratio_error = stage1.aspect_status((sample["width"], sample["height"]), target)
    dimensions_status = "PASS" if image.size == target and (decoded["width"], decoded["height"]) == target else "FAIL"
    alpha_metrics = alpha_safety_metrics(image, baseline)
    alpha_result = alpha_metrics["status"]
    seam = seam_metric(image, tuple(model_run["raw_dimensions"]))
    trace = transform_trace or build_transform_trace(
        sample["sample_id"],
        run_id,
        (sample["width"], sample["height"]),
        (sample["width"], sample["height"]),
        target,
        (decoded["width"], decoded["height"]),
        source_orientation=source_orientation,
        operation_records=None,
        candidate_sha256=file_sha256(output_path) if output_path.is_file() else None,
    )
    geometry_status = geometry_gate_from_trace(trace)
    orientation_status = orientation_gate_from_trace(trace)
    source_state = stage1.capture_file_state(input_path)
    source_status = (
        "PASS"
        if all(source_state.get(key) == sample.get(key) for key in ("size_bytes", "mtime_ns", "sha256"))
        else "FAIL"
    )
    exit_code = model_run.get("exit_code")
    gates = {
        "process_exit_validation": "PASS" if exit_code == 0 else "FAIL",
        "source_validation": source_status,
        "decode_validation": decoded["decode_status"],
        "target_dimensions": dimensions_status,
        "aspect_ratio": ratio_status,
        "format_validation": "PASS" if decoded["format"] == "PNG" else "FAIL",
        "alpha_validation": alpha_result,
        "geometry_validation": geometry_status,
        "orientation_validation": orientation_status,
        "tile_seam_validation": seam["status"],
    }
    aggregate = aggregate_mandatory_gates(gates)
    automatic_risk_precheck = (
        "PASS_NO_BLOCKING_SIGNAL" if aggregate["success"] else "BLOCKED_BY_AUTOMATIC_SIGNAL"
    )
    candidate_sha256 = file_sha256(output_path)
    record = {
        "sample_id": sample["sample_id"],
        "run_id": run_id,
        "run_started_at": run_started_at,
        "run_ended_at": run_ended_at,
        "route": route,
        "candidate_route": route,
        "model_name": "RealESRGAN_x4plus",
        "source_batch": source_batch,
        "revalidated_by_remediation": revalidated_by_remediation,
        "source_path": str(input_path.resolve()),
        "lanczos_path": str(lanczos_path.resolve()),
        "candidate_path": str(output_path.resolve()),
        "input_path": str(input_path.resolve()),
        "output_path": str(output_path.resolve()),
        "source_dimensions": [sample["width"], sample["height"]],
        "expected_dimensions": list(target),
        "input_dimensions": [sample["width"], sample["height"]],
        "output_dimensions": [decoded["width"], decoded["height"]],
        "format": decoded["format"],
        "output_format": decoded["format"],
        "color_mode": decoded["mode"],
        "alpha_status": alpha_result,
        "runtime_seconds": round(runtime_seconds, 3),
        "output_size_bytes": output_path.stat().st_size,
        "output_sha256": candidate_sha256,
        "candidate_sha256": candidate_sha256,
        "geometry_trace_path": str(geometry_trace_path.resolve()) if geometry_trace_path else None,
        "output_pixel_sha256": stage1.pixel_sha256(output_path),
        "success": aggregate["success"],
        "technical_success": aggregate["success"],
        "technical_status": aggregate["technical_status"],
        "blocking_gates": aggregate["blocking_gates"],
        "review_required_gates": aggregate["review_required_gates"],
        "mandatory_gates": aggregate["mandatory_gates"],
        "failure_stage": None,
        "error_type": None,
        "error_message": None,
        "decode_status": decoded["decode_status"],
        "dimensions_status": dimensions_status,
        "aspect_ratio_status": ratio_status,
        "aspect_ratio_error_pixels": round(ratio_error, 6),
        "crop_status": trace_status(trace["crop_operation"]["applied"], "PRESENT", "ABSENT"),
        "stretch_status": trace_status(
            trace["resize_operation"]["nonuniform_stretch"], "PRESENT", "ABSENT"
        ),
        "padding_status": trace_status(trace["pad_operation"]["applied"], "PRESENT", "ABSENT"),
        "orientation_status": trace_status(
            trace["rotate_operation"]["applied"], "CHANGED", "PRESERVED"
        ),
        "transform_trace": trace,
        "geometry_gate": geometry_status,
        "orientation_gate": orientation_status,
        "tile_seam_precheck": seam,
        "tile_seam_gate": seam["status"],
        "alpha_gate": alpha_result,
        "alpha_metrics": alpha_metrics,
        "structure_safety_gate": structure_safety_status,
        "structure_status_source": structure_safety_evidence.get("evidence_source", "UNKNOWN"),
        "structure_safety_evidence": structure_safety_evidence,
        "automatic_risk_precheck": automatic_risk_precheck,
        "route_decision": route_decision,
        "evidence_path": str(evidence_path.resolve()),
        "color_metrics_vs_lanczos": color_metrics(image, baseline),
        "controlled_increment": increment,
        "inference_parameters": INFERENCE_PARAMETERS,
    }
    return apply_process_exit_contract(record, exit_code)


def display_panel(image: Image.Image, label: str, panel_size: int = 900) -> Image.Image:
    rgba = image.convert("RGBA")
    checker = Image.new("RGB", (panel_size, panel_size), (235, 235, 235))
    draw = ImageDraw.Draw(checker)
    cell = 32
    for y in range(0, panel_size, cell):
        for x in range(0, panel_size, cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=(210, 210, 210))
    rgba.thumbnail((panel_size, panel_size), Image.Resampling.LANCZOS)
    x = (panel_size - rgba.width) // 2
    y = (panel_size - rgba.height) // 2
    checker.paste(rgba.convert("RGB"), (x, y), rgba.getchannel("A"))
    canvas = Image.new("RGB", (panel_size, panel_size + 42), "white")
    canvas.paste(checker, (0, 42))
    ImageDraw.Draw(canvas).text((14, 14), label, fill=(20, 20, 20))
    return canvas


def save_contact(panels: list[tuple[str, Image.Image]], destination: Path, panel_size: int) -> None:
    rendered = [display_panel(image, label, panel_size) for label, image in panels]
    contact = Image.new("RGB", (sum(item.width for item in rendered), max(item.height for item in rendered)), "white")
    x = 0
    for item in rendered:
        contact.paste(item, (x, 0))
        x += item.width
    temp_path = stage1.save_png_temp(contact, destination, None)
    os.replace(temp_path, destination)


def build_review_package(
    batch_root: Path,
    manifest: dict[str, Any],
    roi_manifest: dict[str, Any],
    candidates: dict[tuple[str, str], Path],
    stage1_lanczos: dict[str, Path],
) -> dict[str, Any]:
    full_records: list[dict[str, Any]] = []
    roi_records: list[dict[str, Any]] = []
    sample_map = {sample["sample_id"]: sample for sample in manifest["samples"]}
    for sample in manifest["samples"]:
        source, _ = open_normalized(Path(sample["source_path"]))
        with Image.open(stage1_lanczos[sample["sample_id"]]) as opened:
            opened.load()
            lanczos = opened.copy()
        with Image.open(candidates[(sample["sample_id"], ROUTE_B)]) as opened:
            opened.load()
            route_b = opened.copy()
        destination = batch_root / "review_package" / "full_comparisons" / f"{sample['sample_id']}__full_comparison.png"
        save_contact(
            [("Original", source), ("Pillow LANCZOS", lanczos), ("修复后 Route B", route_b)],
            destination,
            900,
        )
        full_records.append({"sample_id": sample["sample_id"], "path": str(destination.resolve()), "sha256": file_sha256(destination)})

    for index, frozen in enumerate(roi_manifest["comparisons"], start=1):
        sample = sample_map[frozen["sample_id"]]
        source, _ = open_normalized(Path(sample["source_path"]))
        with Image.open(stage1_lanczos[sample["sample_id"]]) as opened:
            opened.load()
            lanczos = opened.copy()
        with Image.open(candidates[(sample["sample_id"], ROUTE_B)]) as opened:
            opened.load()
            route_b = opened.copy()
        source_box = tuple(frozen["source_pixel_box"][key] for key in ("x0", "y0", "x1", "y1"))
        normalized = frozen["normalized_box"]
        boxes = {
            "pillow_lanczos": stage1.map_normalized_box(normalized, *lanczos.size),
            ROUTE_B: stage1.map_normalized_box(normalized, *route_b.size),
        }
        crops = [
            ("Original", stage1.comparison_display(source.crop(source_box))),
            ("Pillow LANCZOS", stage1.comparison_display(lanczos.crop(boxes["pillow_lanczos"]))),
            ("修复后 Route B", stage1.comparison_display(route_b.crop(boxes[ROUTE_B]))),
        ]
        safe_risk = re.sub(r"[\\/:*?\"<>|]", "_", frozen["risk"])
        destination = (
            batch_root
            / "review_package"
            / "roi_comparisons"
            / f"{sample['sample_id']}__R{index:02d}__{safe_risk}.png"
        )
        save_contact(crops, destination, 512)

        native: dict[str, Any] = {}
        frozen_lanczos = frozen["candidate_native_100_percent"]["pillow_lanczos"]
        baseline_native_destination = (
            batch_root / "review_package" / "native_100_percent" / f"{sample['sample_id']}__R{index:02d}__pillow_lanczos.png"
        )
        baseline_native_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(frozen_lanczos["path"], baseline_native_destination)
        native["pillow_lanczos"] = {
            "pixel_box": frozen_lanczos["pixel_box"],
            "path": str(baseline_native_destination.resolve()),
            "sha256": file_sha256(baseline_native_destination),
            "scale": "100_PERCENT_NATIVE_PIXELS",
        }
        for route, image in ((ROUTE_B, route_b),):
            native_box = stage1.centered_box(image.width, image.height, next(
                region["center"] for region in sample["risk_regions"] if region["risk"] == frozen["risk"]
            ), 512)
            native_destination = (
                batch_root / "review_package" / "native_100_percent" / f"{sample['sample_id']}__R{index:02d}__{route}.png"
            )
            native_crop = image.crop(native_box)
            temp_path = stage1.save_png_temp(native_crop, native_destination, None)
            os.replace(temp_path, native_destination)
            native[route] = {
                "pixel_box": stage1.box_record(native_box),
                "path": str(native_destination.resolve()),
                "sha256": file_sha256(native_destination),
                "width": native_crop.width,
                "height": native_crop.height,
                "scale": "100_PERCENT_NATIVE_PIXELS",
            }

        errors = {
            name: stage1.reverse_mapping_errors(source_box, box, source.size, lanczos.size if name == "pillow_lanczos" else route_b.size)
            for name, box in boxes.items()
        }
        roi_records.append(
            {
                "sample_id": sample["sample_id"],
                "risk": frozen["risk"],
                "source_pixel_box": frozen["source_pixel_box"],
                "normalized_box": normalized,
                "candidate_pixel_boxes": {key: stage1.box_record(value) for key, value in boxes.items()},
                "reverse_mapping_error_source_pixels": errors,
                "maximum_reverse_mapping_error_source_pixels": max(item["maximum"] for item in errors.values()),
                "comparison_path": str(destination.resolve()),
                "comparison_sha256": file_sha256(destination),
                "native_100_percent": native,
            }
        )
    return {"full_comparisons": full_records, "roi_comparisons": roi_records}


def write_review_scaffolding(
    batch_root: Path,
    run_results: dict[str, Any],
    review: dict[str, Any],
    old_risks: dict[str, Any],
    structure_evidence_records: list[dict[str, Any]],
    geometry_trace_records: list[dict[str, Any]],
) -> None:
    evidence_by_sample = {record["sample_id"]: record for record in structure_evidence_records}
    observations = {
        "status": "READY_FOR_HUMAN_VISUAL_REVIEW",
        "human_visual_review_required": True,
        "candidate_ranking": [ROUTE_B],
        "ai_safe_gain_status": "PENDING_HUMAN_REVIEW",
        "route_disposition": {
            ROUTE_A: "REJECTED_UNSAFE_READ_ONLY_REVALIDATION",
            ROUTE_B: "PENDING_HUMAN_REVIEW",
        },
        "sample_observations": [
            {
                "sample_id": sample_id,
                "full_frame_gain_vs_lanczos": "PENDING_HUMAN_REVIEW",
                "structure_safety": {ROUTE_A: "FAIL", ROUTE_B: "PENDING_HUMAN_REVIEW"},
                "structure_evidence_source": "HUMAN_VISUAL_REVIEW_REQUIRED",
                "structure_validation_mode": evidence_by_sample[sample_id]["validation_mode"],
                "notes": "自动技术风险预检不判断中文、Logo、人物、产品或材质安全；结构与视觉增益等待人工复核。",
            }
            for sample_id in sorted(evidence_by_sample)
        ],
    }
    route_a_risk = dict(old_risks["routes"][ROUTE_A])
    route_a_risk["disposition"] = "REJECTED_UNSAFE_READ_ONLY_REVALIDATION"
    route_b_labels = {
        f"{record['sample_id']}:{check['risk']}": "PENDING_HUMAN_REVIEW"
        for record in structure_evidence_records
        for check in record["human_review_checks"]
    }
    risks = {
        "status": "AUTOMATIC_TECHNICAL_RISK_PRECHECK_COMPLETE",
        "human_visual_review_required": True,
        "safe_review_candidate": ROUTE_B,
        "routes": {
            ROUTE_A: route_a_risk,
            ROUTE_B: {
                "automatic_risk_precheck": "PASS_NO_BLOCKING_SIGNAL",
                "structure_safety_status": "PENDING_HUMAN_REVIEW",
                "structure_status_source": "HUMAN_VISUAL_REVIEW_REQUIRED",
                "disposition": "PENDING_HUMAN_REVIEW",
                "labels": route_b_labels,
                "sample_evidence": [
                    {
                        "sample_id": record["sample_id"],
                        "status": record["status"],
                        "validation_mode": record["validation_mode"],
                    }
                    for record in structure_evidence_records
                ],
            },
        },
    }
    json_write(batch_root / "review_package" / "observations.json", observations)
    json_write(batch_root / "review_package" / "risk_assessment.json", risks)
    json_write(
        batch_root / "review_package" / "geometry_trace_manifest.json",
        {"count": len(geometry_trace_records), "records": geometry_trace_records},
    )
    json_write(
        batch_root / "review_package" / "roi_manifest.json",
        {
            "version": "4K_STAGE_2_FROZEN_ROI_REUSE_V1",
            "roi_count": len(review["roi_comparisons"]),
            "native_100_percent_count": sum(len(row["native_100_percent"]) for row in review["roi_comparisons"]),
            "records": review["roi_comparisons"],
        },
    )
    json_write(batch_root / "review_package" / "full_comparison_manifest.json", review["full_comparisons"])
    readme = f"""# 影界 HDDE｜4K阶段2人工视觉复核包

状态：修复后的唯一正式人工视觉复核入口。此包不代表阶段2通过、冻结或可以进入阶段3。

原入口 `{ORIGINAL_STAGE2_BATCH_ROOT}` 已因技术门禁聚合、故障探针路径安全、Alpha硬保护和执行矩阵合同缺陷失效；原批次保持字节级不变。失效关系见 `supersession.json`。

## 固定对照顺序

1. 原图
2. Pillow LANCZOS（阶段1冻结基线）
3. 修复后Route B：LANCZOS安全底图＋受控AI高频细节增量

Route A只读重评后仍为 `REJECTED_UNSAFE`，仅保留在批次根目录的淘汰证据和16行执行矩阵中，不进入主评图包。

自动技术真实性已经通过；自动预检不代表语义结构安全。中文、Logo、人物、产品、材质以及Route B是否肉眼优于LANCZOS，均等待人工视觉判断。

## 建议优先查看

- S01、S02：中文笔画、小字内部空间、Logo式边缘
- S03：眼睛、皮肤、头发和人物身份
- S05：Logo、包装文字、产品结构
- S06：玻璃、金属和透明材质
- S08：Alpha透明边缘

## 固定模型与参数

- 模型：RealESRGAN_x4plus
- 版本：{MODEL_VERSION}
- 来源：{MODEL_SOURCE}
- 许可证：{MODEL_LICENSE}
- 人脸增强、美颜、HDR、自动改色、文字/Logo重绘：全部关闭
- Route B参数见 `parameters.json`，8张样本完全统一，无单图调参。

## 文件入口

- `full_comparisons/`：8组完整画面对照
- `roi_comparisons/`：14组阶段1冻结ROI对照
- `native_100_percent/`：LANCZOS、修复后Route B各14份，共28份原生100%局部
- `alpha_evidence/`：S08与合成透明样本的黑底、白底、棋盘格证据
- `geometry_traces/`、`geometry_trace_manifest.json`：8张Route B真实有序几何事件与候选SHA
- `structure_evidence/`：逐样本自动技术观察和人工语义复核职责边界，不产生结构PASS
- `execution_matrix.json`：8张样本×2条路线的16行完整矩阵
- `supersession.json`：旧批次失效原因与新旧对应关系
- `observations.json`：自动技术风险预检与逐样本人工复核等待状态
- `risk_assessment.json`：结构风险人工复核标签
- `../run_results.json`：运行时间、大小、技术门禁和错误字段
- `../sha256_manifest.json`：最终文件SHA256清单

最终是否具有真实可见增益，必须由用户人工评图决定。
"""
    readme_path = batch_root / "review_package" / "README_人工视觉复核.md"
    readme_path.parent.mkdir(parents=True, exist_ok=True)
    readme_path.write_text(readme, encoding="utf-8")
    shutil.copyfile(batch_root / "execution_matrix.json", batch_root / "review_package" / "execution_matrix.json")
    shutil.copyfile(batch_root / "supersession.json", batch_root / "review_package" / "supersession.json")
    json_write(
        batch_root / "review_package" / "model_and_parameters.json",
        {
            "model": json.loads((batch_root / "model_manifest.json").read_text(encoding="utf-8")),
            "parameters": json.loads((batch_root / "parameters.json").read_text(encoding="utf-8")),
        },
    )


def _checkerboard_background(size: tuple[int, int], cell: int = 16) -> Image.Image:
    width, height = size
    yy, xx = np.indices((height, width))
    light = ((xx // cell + yy // cell) % 2) == 0
    data = np.empty((height, width, 3), dtype=np.uint8)
    data[light] = 224
    data[~light] = 176
    return Image.fromarray(data, mode="RGB")


def _pillow_composite(image: Image.Image, background: Image.Image) -> Image.Image:
    background = background.convert("RGBA")
    background.alpha_composite(image.convert("RGBA"))
    return background.convert("RGB")


def write_alpha_evidence_pair(
    batch_root: Path,
    evidence_id: str,
    baseline: Image.Image,
    candidate: Image.Image,
) -> dict[str, Any]:
    destination_root = batch_root / "review_package" / "alpha_evidence"
    records: dict[str, Any] = {}
    backgrounds = {
        "black": Image.new("RGB", baseline.size, "black"),
        "white": Image.new("RGB", baseline.size, "white"),
        "checkerboard": _checkerboard_background(baseline.size),
    }
    for name, background in backgrounds.items():
        destination = destination_root / f"{evidence_id}__{name}.png"
        save_contact(
            [
                ("Pillow LANCZOS", _pillow_composite(baseline, background)),
                ("修复后 Route B", _pillow_composite(candidate, background)),
            ],
            destination,
            min(900, max(baseline.size)),
        )
        records[name] = {
            "path": str(destination.resolve()),
            "sha256": file_sha256(destination),
        }
    return {
        "evidence_id": evidence_id,
        "metrics": alpha_safety_metrics(candidate, baseline),
        "composites": records,
    }


def synthetic_alpha_pair() -> tuple[Image.Image, Image.Image, dict[str, Any]]:
    width, height = 192, 144
    yy, xx = np.indices((height, width))
    distance = np.maximum(np.abs(xx - width // 2) - 50, np.abs(yy - height // 2) - 34)
    alpha = np.clip(255 - (distance + 8) * 24, 0, 255).astype(np.uint8)
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    rgb[:, :, 0] = np.clip(40 + xx, 0, 255)
    rgb[:, :, 1] = np.clip(70 + yy, 0, 255)
    rgb[:, :, 2] = 150
    rgba = np.dstack((rgb, alpha))
    baseline = Image.fromarray(rgba, mode="RGBA")
    ai_rgb = rgb.astype(np.int16)
    texture = (((xx // 3 + yy // 3) % 2) * 18 - 9)[:, :, None]
    ai_rgb = np.clip(ai_rgb + texture, 0, 255).astype(np.uint8)
    candidate, increment = controlled_increment(baseline, Image.fromarray(ai_rgb, mode="RGB"))
    return baseline, candidate, increment


def write_alpha_evidence(batch_root: Path, s08_baseline: Image.Image, s08_candidate: Image.Image) -> dict[str, Any]:
    synthetic_baseline, synthetic_candidate, synthetic_increment = synthetic_alpha_pair()
    payload = {
        "status": "PASS",
        "records": [
            write_alpha_evidence_pair(batch_root, "S08", s08_baseline, s08_candidate),
            write_alpha_evidence_pair(
                batch_root,
                "SYNTHETIC_MULTI_LEVEL_ALPHA",
                synthetic_baseline,
                synthetic_candidate,
            ),
        ],
        "synthetic_increment": synthetic_increment,
    }
    if any(record["metrics"]["status"] != "PASS" for record in payload["records"]):
        payload["status"] = "FAIL"
    json_write(batch_root / "review_package" / "alpha_evidence" / "alpha_evidence_manifest.json", payload)
    return payload


def write_file_manifest(batch_root: Path) -> dict[str, Any]:
    manifest_path = batch_root / "review_package" / "file_manifest.json"
    files = [
        {
            "path": path.relative_to(batch_root).as_posix(),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(batch_root.rglob("*"), key=lambda item: item.as_posix().lower())
        if path.is_file() and path != manifest_path
    ]
    payload = {"batch_id": batch_root.name, "file_count": len(files), "files": files}
    json_write(manifest_path, payload)
    return payload


def write_execution_report(batch_root: Path, run_results: dict[str, Any]) -> None:
    route_a_statuses = sorted({row["technical_status"] for row in run_results["candidates"] if row["route"] == ROUTE_A})
    report = f"""# 影界 HDDE｜4K阶段2几何轨迹真实性与人工视觉职责边界修复报告

批次：`{batch_root.name}`

## 修复结果

- 几何门禁：由Route B真实处理点产生的严格有序事件链派生；缺失轨迹为UNKNOWN，链断裂、顺序错误或最终尺寸不一致为FAIL。
- Route B语义结构：自动阶段不再输出PASS；中文、Logo、人物、产品和材质统一保持PENDING_HUMAN_REVIEW。
- technical success：仅聚合可自动证明的技术事实；任何 REVIEW/FAIL/BLOCKED/UNKNOWN 均不能成功。
- 故障探针与Alpha硬保护：保留既有安全门禁并执行最小回归。
- Route A：仅引用旧候选并只读重评；技术状态集合为 `{', '.join(route_a_statuses)}`，结构不安全，保持淘汰。
- 执行矩阵：`execution_matrix.json` 共 {len(run_results['candidates'])} 行。

## 批次替代关系

旧批次 `{ORIGINAL_STAGE2_BATCH_ROOT}`、上一修复批次 `{AUDIT_REMEDIATION_BATCH_ROOT}` 与被阻断批次 `{BLOCKED_TRUTH_BATCH_ROOT}` 均保持字节级不变。新批次是唯一正式人工复核入口。

## 当前终态

`AUTOMATIC_AUDIT_MINIMAL_TRUTHFULNESS_REMEDIATION: PASS`

`GEOMETRY_TRACE_AUTHENTICITY: PASS`

`DEFAULT_GEOMETRY_BOOLEAN_USAGE: REMOVED`

`LIVE_PIPELINE_OPERATION_TRACE: PASS`

`ROUTE_A_GEOMETRY_EVIDENCE_STATUS: UNKNOWN_HISTORICAL_TRACE_UNAVAILABLE`

`ROUTE_A_TECHNICAL_STATUS: FAIL`

`ROUTE_A_STATUS: REJECTED_UNSAFE`

`ROUTE_B_TECHNICAL_STATUS: PASS`

`ROUTE_B_AUTOMATIC_RISK_PRECHECK: PASS_NO_BLOCKING_SIGNAL`

`ROUTE_B_STRUCTURE_SAFETY_STATUS: PENDING_HUMAN_REVIEW`

`ROUTE_B_VISUAL_GAIN_STATUS: PENDING_HUMAN_REVIEW`

`ROUTE_B_STATUS: PENDING_HUMAN_REVIEW`

`REVIEW_PACKAGE_CONTRACT: PASS`

`4K_STAGE_2_VISUAL_REVIEW_STATUS: READY`

`4K_STAGE_2_FINAL_STATUS: PENDING_HUMAN_VISUAL_REVIEW`

`4K_STAGE_2_FREEZE_STATUS: NOT_READY`

`AI_SAFE_GAIN_STATUS: PENDING_HUMAN_REVIEW`

`STAGE_RESULT: REVIEW_PACKAGE_READY`

`SELF_AUDIT_SCOPE: TECHNICAL_TRUTHFULNESS_AND_PACKAGE_CONTRACT_ONLY`

本报告不证明视觉增益，不授权阶段冻结、自动路由、产品接入或进入阶段3。
"""
    destination = batch_root / "reports" / "4K_STAGE_2_MINIMAL_TRUTHFULNESS_REMEDIATION_REPORT.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(report, encoding="utf-8")


def refresh_sha_manifest(batch_root: Path) -> dict[str, Any]:
    review_root = batch_root / "review_package"
    review_manifest_path = review_root / "sha256_manifest.json"
    review_files = []
    if review_root.exists():
        for path in sorted(
            (item for item in review_root.rglob("*") if item.is_file() and item != review_manifest_path),
            key=lambda item: item.as_posix().lower(),
        ):
            review_files.append(
                {
                    "path": path.relative_to(review_root).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": file_sha256(path),
                }
            )
        json_write(
            review_manifest_path,
            {"batch_id": batch_root.name, "scope": "review_package", "file_count": len(review_files), "files": review_files},
        )
    manifest_path = batch_root / "sha256_manifest.json"
    files = []
    for path in sorted((item for item in batch_root.rglob("*") if item.is_file() and item != manifest_path), key=lambda item: item.as_posix().lower()):
        files.append(
            {
                "path": path.relative_to(batch_root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    payload = {"batch_id": batch_root.name, "file_count": len(files), "files": files}
    json_write(manifest_path, payload)
    return payload


def run_batch(batch_root: Path, model_root: Path) -> dict[str, Any]:
    batch_root = validate_batch_root(batch_root)
    if (batch_root / "run_results.json").exists() or (batch_root / "candidates").exists():
        raise Stage2Error(f"STAGE2_BATCH_ALREADY_EXECUTED:{batch_root}")
    if not ORIGINAL_STAGE2_BATCH_ROOT.is_dir():
        raise Stage2Error(f"ORIGINAL_STAGE2_BATCH_MISSING:{ORIGINAL_STAGE2_BATCH_ROOT}")
    manifest = stage1.read_manifest(DEFAULT_MANIFEST)
    stage1_results = json.loads(DEFAULT_STAGE1_RESULTS.read_text(encoding="utf-8"))
    roi_manifest = json.loads(DEFAULT_ROI_MANIFEST.read_text(encoding="utf-8"))
    old_results = json.loads((ORIGINAL_STAGE2_BATCH_ROOT / "run_results.json").read_text(encoding="utf-8"))
    old_risks = json.loads(
        (ORIGINAL_STAGE2_BATCH_ROOT / "review_package" / "risk_assessment.json").read_text(encoding="utf-8")
    )
    if roi_manifest.get("comparison_count") != 14:
        raise Stage2Error("FROZEN_ROI_COUNT_MUST_BE_14")
    if stage1_results.get("candidate_count") != 24:
        raise Stage2Error("FROZEN_TRADITIONAL_CANDIDATE_COUNT_MUST_BE_24")
    stage1_lanczos = {
        row["sample_id"]: Path(row["output_path"])
        for row in stage1_results["candidates"]
        if row["method"] == "pillow_lanczos"
    }
    if len(stage1_lanczos) != 8:
        raise Stage2Error("FROZEN_LANCZOS_COUNT_MUST_BE_8")
    old_route_a_rows = {
        row["sample_id"]: row for row in old_results["candidates"] if row["candidate_route"] == ROUTE_A
    }
    old_route_b_rows = {
        row["sample_id"]: row for row in old_results["candidates"] if row["candidate_route"] == ROUTE_B
    }
    roi_records_by_sample: dict[str, list[dict[str, Any]]] = {}
    for record in roi_manifest["comparisons"]:
        roi_records_by_sample.setdefault(record["sample_id"], []).append(record)
    if len(old_route_a_rows) != 8:
        raise Stage2Error("ORIGINAL_ROUTE_A_COUNT_MUST_BE_8")
    if len(old_route_b_rows) != 8:
        raise Stage2Error("ORIGINAL_ROUTE_B_COUNT_MUST_BE_8")
    metadata = model_metadata(model_root)
    protected_before = capture_protected_state(manifest, stage1_results)
    batch_root.mkdir(parents=True, exist_ok=True)
    json_write(batch_root / "model_manifest.json", metadata)
    json_write(
        batch_root / "parameters.json",
        {
            "route_a": {
                "status": "READ_ONLY_REVALIDATION_NO_REGENERATION",
                "source_batch": str(ORIGINAL_STAGE2_BATCH_ROOT.resolve()),
                "inference_parameters": INFERENCE_PARAMETERS,
            },
            "route_b": {
                "inference_parameters": INFERENCE_PARAMETERS,
                "controlled_increment_parameters": CONTROLLED_INCREMENT_PARAMETERS,
                "geometry_trace_contract": "STRICT_LIVE_ORDERED_OPERATION_TRACE_REQUIRED",
                "structure_safety_contract": "PENDING_HUMAN_VISUAL_REVIEW_REQUIRED",
                "superseded_remediation_batch": str(AUDIT_REMEDIATION_BATCH_ROOT.resolve()),
                "superseded_blocked_batch": str(BLOCKED_TRUTH_BATCH_ROOT.resolve()),
            },
        },
    )

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    candidates: dict[tuple[str, str], Path] = {}
    device_records: list[dict[str, Any]] = []
    route_a_revalidation: list[dict[str, Any]] = []
    route_b_structure_evidence: list[dict[str, Any]] = []
    route_b_geometry_traces: list[dict[str, Any]] = []
    for sample in manifest["samples"]:
        sample_id = sample["sample_id"]
        run_id = f"{batch_root.name}:{sample_id}:{uuid.uuid4().hex}"
        run_started_at = datetime.now(timezone.utc).isoformat()
        source_path = Path(sample["source_path"])
        raw_path = batch_root / "_work" / f"{sample_id}__model_raw_x4.png"
        route_b_path = batch_root / "candidates" / ROUTE_B / f"{sample_id}__{ROUTE_B}.png"
        old_route_a_path = Path(old_route_a_rows[sample_id]["output_path"])
        model_run: dict[str, Any] | None = None
        geometry_events: list[dict[str, Any]] = []
        try:
            source, source_meta = candidate_stage(
                "source_open",
                lambda: open_normalized(source_path),
                sample_id=sample_id,
                route=ROUTE_B,
                input_path=source_path,
                output_path=route_b_path,
            )
            append_geometry_event(
                geometry_events,
                sample_id=sample_id,
                run_id=run_id,
                stage="source_open",
                operation="exif_transpose",
                applied=source_meta["source_orientation"] not in {0, 1},
                before_dimensions=source_meta["encoded_dimensions"],
                after_dimensions=source_meta["normalized_dimensions"],
                method="PILLOW_IMAGEOPS_EXIF_TRANSPOSE",
                parameters={"source_orientation": source_meta["source_orientation"]},
            )

            def validate_source() -> None:
                state = stage1.capture_file_state(source_path)
                for field in ("size_bytes", "mtime_ns", "sha256"):
                    if state.get(field) != sample[field]:
                        raise Stage2Error(f"SOURCE_MANIFEST_MISMATCH:{sample_id}:{field}")
                if source.size != (sample["width"], sample["height"]):
                    raise Stage2Error(f"SOURCE_DIMENSION_MISMATCH:{sample_id}")

            candidate_stage(
                "source_validation",
                validate_source,
                sample_id=sample_id,
                route=ROUTE_B,
                input_path=source_path,
                output_path=route_b_path,
            )
            with Image.open(stage1_lanczos[sample_id]) as opened:
                opened.load()
                baseline = opened.copy()
            with Image.open(old_route_a_path) as opened:
                opened.load()
                old_route_a = opened.copy()
            route_a_evidence = batch_root / "revalidation" / "route_a" / f"{sample_id}.json"
            route_a_trace = build_transform_trace(
                sample_id,
                f"{ORIGINAL_STAGE2_BATCH_ROOT.name}:{sample_id}:HISTORICAL_TRACE_UNAVAILABLE",
                tuple(source_meta["encoded_dimensions"]),
                tuple(source_meta["normalized_dimensions"]),
                baseline.size,
                old_route_a.size,
                source_orientation=source_meta["source_orientation"],
                operation_records=None,
                candidate_sha256=file_sha256(old_route_a_path),
            )
            route_a_record = candidate_record(
                sample,
                ROUTE_A,
                source_path,
                old_route_a_path,
                old_route_a,
                baseline,
                float(old_route_a_rows[sample_id]["runtime_seconds"]),
                {"raw_dimensions": [sample["width"] * 4, sample["height"] * 4]},
                None,
                source_batch=ORIGINAL_STAGE2_BATCH_ROOT.name,
                revalidated_by_remediation=True,
                lanczos_path=stage1_lanczos[sample_id],
                structure_safety_status="FAIL",
                structure_safety_evidence={
                    "sample_id": sample_id,
                    "route": ROUTE_A,
                    "status": "FAIL",
                    "evidence_source": "READ_ONLY_CODEX_STRUCTURE_REVALIDATION",
                },
                route_decision="REJECTED_UNSAFE",
                evidence_path=route_a_evidence,
                run_id=f"{ORIGINAL_STAGE2_BATCH_ROOT.name}:{sample_id}:HISTORICAL_TRACE_UNAVAILABLE",
                run_started_at="HISTORICAL_NOT_RECORDED",
                run_ended_at="HISTORICAL_NOT_RECORDED",
                source_orientation=source_meta["source_orientation"],
                transform_trace=route_a_trace,
                geometry_trace_path=route_a_evidence,
            )
            route_a_record["route_a_geometry_evidence_status"] = "UNKNOWN_HISTORICAL_TRACE_UNAVAILABLE"
            json_write(route_a_evidence, route_a_record)
            rows.append(route_a_record)
            route_a_revalidation.append(route_a_record)

            def execute_model() -> dict[str, Any]:
                append_geometry_event(
                    geometry_events,
                    sample_id=sample_id,
                    run_id=run_id,
                    stage="model_inference",
                    operation="model_input",
                    applied=True,
                    before_dimensions=source.size,
                    after_dimensions=source_meta["encoded_dimensions"],
                    method="SOURCE_FILE_PASSED_TO_NCNN_VULKAN",
                    parameters={"source_sha256": sample["sha256"], "model": DEFAULT_MODEL_NAME},
                )
                return run_model(model_root, source_path, raw_path)

            model_run = candidate_stage(
                "model_inference",
                execute_model,
                sample_id=sample_id,
                route=ROUTE_B,
                input_path=source_path,
                output_path=route_b_path,
            )
            device_records.append(model_run["device"])
            raw, _ = candidate_stage(
                "model_decode",
                lambda: open_normalized(raw_path),
                sample_id=sample_id,
                route=ROUTE_B,
                input_path=source_path,
                output_path=route_b_path,
            )
            model_run["raw_dimensions"] = list(raw.size)
            append_geometry_event(
                geometry_events,
                sample_id=sample_id,
                run_id=run_id,
                stage="model_decode",
                operation="model_super_resolution",
                applied=raw.size != tuple(source_meta["encoded_dimensions"]),
                before_dimensions=source_meta["encoded_dimensions"],
                after_dimensions=raw.size,
                method="REALESRGAN_X4PLUS",
                parameters={"scale": INFERENCE_PARAMETERS["scale"]},
            )

            def normalize_route_b() -> Image.Image:
                before_dimensions = raw.size
                resized = raw.convert("RGB").resize(baseline.size, Image.Resampling.LANCZOS)
                append_geometry_event(
                    geometry_events,
                    sample_id=sample_id,
                    run_id=run_id,
                    stage="normalize_4k",
                    operation="resize",
                    applied=before_dimensions != resized.size,
                    before_dimensions=before_dimensions,
                    after_dimensions=resized.size,
                    method="PILLOW_LANCZOS",
                    parameters={"target_dimensions": list(baseline.size)},
                )
                return attach_safe_alpha(resized, baseline)

            ephemeral_ai = candidate_stage(
                "normalize_4k",
                normalize_route_b,
                sample_id=sample_id,
                route=ROUTE_B,
                input_path=source_path,
                output_path=route_b_path,
            )
            route_b, increment = candidate_stage(
                "safety_blend",
                lambda: controlled_increment(baseline, ephemeral_ai),
                sample_id=sample_id,
                route=ROUTE_B,
                input_path=source_path,
                output_path=route_b_path,
            )
            append_geometry_event(
                geometry_events,
                sample_id=sample_id,
                run_id=run_id,
                stage="safety_blend",
                operation="pixel_blend",
                applied=True,
                before_dimensions=ephemeral_ai.size,
                after_dimensions=route_b.size,
                method="CONTROLLED_HIGH_FREQUENCY_INCREMENT",
                parameters={"parameter_set": "CONTROLLED_INCREMENT_PARAMETERS"},
            )
            route_started = time.perf_counter()
            candidate_stage(
                "encode_save",
                lambda: save_candidate(route_b, route_b_path, source_meta["icc_profile"]),
                sample_id=sample_id,
                route=ROUTE_B,
                input_path=source_path,
                output_path=route_b_path,
            )
            append_geometry_event(
                geometry_events,
                sample_id=sample_id,
                run_id=run_id,
                stage="encode_save",
                operation="encode",
                applied=True,
                before_dimensions=route_b.size,
                after_dimensions=route_b.size,
                method="ATOMIC_PNG_SAVE",
                parameters={"format": "PNG"},
            )
            decoded_route_b = candidate_stage(
                "decode_validation",
                lambda: stage1.verify_decode(route_b_path),
                sample_id=sample_id,
                route=ROUTE_B,
                input_path=source_path,
                output_path=route_b_path,
            )
            append_geometry_event(
                geometry_events,
                sample_id=sample_id,
                run_id=run_id,
                stage="decode_validation",
                operation="decode_measurement",
                applied=True,
                before_dimensions=route_b.size,
                after_dimensions=(decoded_route_b["width"], decoded_route_b["height"]),
                method="INDEPENDENT_OUTPUT_DECODE",
                parameters={"format": decoded_route_b["format"]},
            )
            route_b_trace = build_transform_trace(
                sample_id,
                run_id,
                tuple(source_meta["encoded_dimensions"]),
                tuple(source_meta["normalized_dimensions"]),
                baseline.size,
                (decoded_route_b["width"], decoded_route_b["height"]),
                source_orientation=source_meta["source_orientation"],
                operation_records=geometry_events,
                candidate_sha256=file_sha256(route_b_path),
            )
            geometry_trace_path = batch_root / "review_package" / "geometry_traces" / f"{sample_id}.json"
            json_write(geometry_trace_path, route_b_trace)
            route_b_geometry_traces.append(
                {
                    "sample_id": sample_id,
                    "run_id": run_id,
                    "path": str(geometry_trace_path.resolve()),
                    "candidate_sha256": route_b_trace["candidate_sha256"],
                    "geometry_gate": geometry_gate_from_trace(route_b_trace),
                }
            )
            route_b_evidence = batch_root / "review_package" / "structure_evidence" / f"{sample_id}.json"
            run_ended_at = datetime.now(timezone.utc).isoformat()
            pending_structure_evidence = {
                "sample_id": sample_id,
                "route": ROUTE_B,
                "status": "PENDING_HUMAN_REVIEW",
                "evidence_source": "HUMAN_VISUAL_REVIEW_REQUIRED",
            }
            route_b_record = candidate_stage(
                "metadata_hash",
                lambda: candidate_record(
                    sample,
                    ROUTE_B,
                    source_path,
                    route_b_path,
                    route_b,
                    baseline,
                    model_run["runtime_seconds"] + (time.perf_counter() - route_started),
                    model_run,
                    increment,
                    source_batch=batch_root.name,
                    revalidated_by_remediation=False,
                    lanczos_path=stage1_lanczos[sample_id],
                    structure_safety_status="PENDING_HUMAN_REVIEW",
                    structure_safety_evidence=pending_structure_evidence,
                    route_decision="PENDING_HUMAN_REVIEW",
                    evidence_path=route_b_evidence,
                    run_id=run_id,
                    run_started_at=run_started_at,
                    run_ended_at=run_ended_at,
                    source_orientation=source_meta["source_orientation"],
                    transform_trace=route_b_trace,
                    geometry_trace_path=geometry_trace_path,
                ),
                sample_id=sample_id,
                route=ROUTE_B,
                input_path=source_path,
                output_path=route_b_path,
            )
            structure_evidence = build_route_b_structure_evidence(
                sample_id,
                route_b_path,
                route_b,
                baseline,
                roi_records_by_sample.get(sample_id, []),
                route_b_record["automatic_risk_precheck"],
            )
            json_write(route_b_evidence, structure_evidence)
            route_b_structure_evidence.append(structure_evidence)
            route_b_record["structure_safety_gate"] = structure_evidence["status"]
            route_b_record["structure_status_source"] = structure_evidence["evidence_source"]
            route_b_record["structure_safety_evidence"] = structure_evidence
            rows.append(route_b_record)
            candidates[(sample_id, ROUTE_B)] = route_b_path
        except CandidateExecutionError as exc:
            failures.append(exc.record)
        finally:
            if raw_path.is_file():
                raw_path.unlink()

    work_root = batch_root / "_work"
    if work_root.exists() and not any(work_root.rglob("*")):
        work_root.rmdir()
    route_a_rows = [row for row in rows if row["route"] == ROUTE_A]
    route_b_rows = [row for row in rows if row["route"] == ROUTE_B]
    route_a_summary = {"technical_status": "FAIL" if len(route_a_rows) == 8 else "BLOCKED"}
    original_tree_before = protected_before["original_stage2_tree"]
    remediation_tree_before = protected_before["audit_remediation_stage2_tree"]
    blocked_truth_tree_before = protected_before["blocked_truth_stage2_tree"]
    supersession = {
        "status": "SUPERSEDED_BY_MINIMAL_TRUTHFULNESS_REMEDIATION",
        "original_batch_path": str(ORIGINAL_STAGE2_BATCH_ROOT.resolve()),
        "original_batch_tree_hash_baseline": original_tree_before.get("tree_content_sha256"),
        "original_batch_file_count": original_tree_before.get("file_count"),
        "superseded_remediation_batch_path": str(AUDIT_REMEDIATION_BATCH_ROOT.resolve()),
        "superseded_remediation_tree_hash_baseline": remediation_tree_before.get("tree_content_sha256"),
        "superseded_remediation_file_count": remediation_tree_before.get("file_count"),
        "blocked_truth_batch_path": str(BLOCKED_TRUTH_BATCH_ROOT.resolve()),
        "blocked_truth_tree_hash_baseline": blocked_truth_tree_before.get("tree_content_sha256"),
        "blocked_truth_file_count": blocked_truth_tree_before.get("file_count"),
        "invalidation_reasons": [
            "GEOMETRY_FIELDS_WERE_DEFAULT_FALSE_INSTEAD_OF_ACTUAL_EXECUTION_TRACE",
            "ROUTE_B_STRUCTURE_PASS_USED_SCALAR_DELTA_WITHOUT_AUDITABLE_SAMPLE_EVIDENCE",
            "ROUTE_B_RISK_LABELS_WERE_BLINDLY_COPIED_FROM_OLD_BATCH",
        ],
        "new_batch_path": str(batch_root.resolve()),
        "original_batch_modified": False,
        "superseded_remediation_batch_modified": False,
        "blocked_truth_batch_modified": False,
        "mapping": [
            {
                "sample_id": sample["sample_id"],
                "route_a_source": str(Path(old_route_a_rows[sample["sample_id"]]["output_path"]).resolve()),
                "previous_route_b_candidate": str(
                    Path(old_route_b_rows[sample["sample_id"]]["output_path"]).resolve()
                ),
                "superseded_route_b_candidate": str(
                    (
                        AUDIT_REMEDIATION_BATCH_ROOT
                        / "candidates"
                        / ROUTE_B
                        / f"{sample['sample_id']}__{ROUTE_B}.png"
                    ).resolve()
                ),
                "route_b_replacement": str(
                    (batch_root / "candidates" / ROUTE_B / f"{sample['sample_id']}__{ROUTE_B}.png").resolve()
                ),
            }
            for sample in manifest["samples"]
        ],
    }
    json_write(batch_root / "supersession.json", supersession)
    json_write(batch_root / "route_a_revalidation.json", {"records": route_a_revalidation})
    json_write(batch_root / "execution_matrix.json", {"row_count": len(rows), "rows": rows})

    protected_after_processing = capture_protected_state(manifest, stage1_results)
    protected_unchanged = protected_before == protected_after_processing
    route_b_ready = len(route_b_rows) == 8 and not failures and all(row["success"] for row in route_b_rows)
    all_candidates_ready = len(rows) == 16 and len(route_a_rows) == 8 and route_b_ready
    if not all_candidates_ready or not protected_unchanged:
        result = {
            "batch_id": batch_root.name,
            "technical_status": "BLOCKED",
            "candidate_count": len(rows),
            "candidates": rows,
            "failures": failures,
            "route_a_technical_status": route_a_summary["technical_status"],
            "route_b_structure_safety_status": route_b_structure_status_for_blocked_run(
                route_b_structure_evidence
            ),
            "structure_status_source": "HUMAN_VISUAL_REVIEW_REQUIRED",
            "route_b_automatic_risk_precheck": "BLOCKED_BY_AUTOMATIC_SIGNAL",
            "visual_review_status": "NOT_READY",
            "protected_state_unchanged": protected_unchanged,
            "protected_state_before": protected_before,
            "protected_state_after": protected_after_processing,
        }
        json_write(batch_root / "run_results.json", result)
        refresh_sha_manifest(batch_root)
        return result

    unique_devices = {
        (record.get("gpu_id"), record.get("device_name"), record.get("fp16_capabilities"))
        for record in device_records
    }
    if len(unique_devices) == 1:
        gpu_id, device_name, fp16_capabilities = next(iter(unique_devices))
        metadata["device"] = f"{device_name} (Vulkan GPU {gpu_id})"
        metadata["precision"] = (
            "ncnn Vulkan automatic; "
            f"device reports fp16-p/s/a={fp16_capabilities or 'UNKNOWN'}"
        )
    else:
        metadata["device"] = "MIXED_OR_UNKNOWN_VULKAN_DEVICES"
        metadata["precision"] = "ncnn Vulkan automatic; see run_results.device_records"
    json_write(batch_root / "model_manifest.json", metadata)

    review = build_review_package(batch_root, manifest, roi_manifest, candidates, stage1_lanczos)
    with Image.open(stage1_lanczos["S08"]) as opened:
        opened.load()
        s08_baseline = opened.copy()
    with Image.open(candidates[("S08", ROUTE_B)]) as opened:
        opened.load()
        s08_candidate = opened.copy()
    alpha_evidence = write_alpha_evidence(batch_root, s08_baseline, s08_candidate)
    if alpha_evidence["status"] != "PASS":
        raise Stage2Error("ALPHA_EVIDENCE_GATE_FAILED")
    run_results = {
        "batch_id": batch_root.name,
        "stage": "4K_STAGE_2_CONSERVATIVE_AI_POC",
        "technical_status": "PASS",
        "structure_safety_status": "PENDING_HUMAN_REVIEW",
        "structure_status_source": "HUMAN_VISUAL_REVIEW_REQUIRED",
        "geometry_trace_source": "LIVE_PIPELINE_OPERATION_TRACE",
        "visual_review_status": "READY",
        "ai_safe_gain_status": "PENDING_HUMAN_REVIEW",
        "human_visual_review_required": True,
        "route_a_technical_status": route_a_summary["technical_status"],
        "route_a_structure_safety_status": "FAIL",
        "route_a_visual_gain_status": "NOT_PROVEN",
        "route_a_status": "REJECTED_UNSAFE",
        "route_a_geometry_evidence_status": "UNKNOWN_HISTORICAL_TRACE_UNAVAILABLE",
        "route_b_technical_status": "PASS",
        "route_b_automatic_risk_precheck": "PASS_NO_BLOCKING_SIGNAL",
        "route_b_structure_safety_status": "PENDING_HUMAN_REVIEW",
        "route_b_structure_evidence_count": len(route_b_structure_evidence),
        "route_b_visual_gain_status": "PENDING_HUMAN_REVIEW",
        "route_b_status": "PENDING_HUMAN_REVIEW",
        "model_manifest_path": str((batch_root / "model_manifest.json").resolve()),
        "device_records": device_records,
        "candidate_count": len(rows),
        "candidates": rows,
        "failures": failures,
        "full_comparison_count": len(review["full_comparisons"]),
        "roi_comparison_count": len(review["roi_comparisons"]),
        "native_100_percent_count": sum(len(row["native_100_percent"]) for row in review["roi_comparisons"]),
        "execution_matrix_row_count": len(rows),
        "geometry_trace_count": len(route_b_geometry_traces),
        "alpha_evidence_status": alpha_evidence["status"],
        "protected_state_unchanged": protected_unchanged,
        "protected_state_before": protected_before,
        "protected_state_after": protected_after_processing,
    }
    json_write(batch_root / "run_results.json", run_results)
    write_review_scaffolding(
        batch_root,
        run_results,
        review,
        old_risks,
        route_b_structure_evidence,
        route_b_geometry_traces,
    )
    write_execution_report(batch_root, run_results)
    write_file_manifest(batch_root)
    refresh_sha_manifest(batch_root)
    return run_results


def run_failure_probe(output_root: Path, record_path: Path, sample_id: str, route: str, stage: str) -> int:
    output_root = validate_failure_probe_root(output_root)
    record_path = resolve_failure_probe_write_path(output_root, record_path)
    output_path = resolve_failure_probe_write_path(output_root, Path("candidate.png"))
    source_path = resolve_failure_probe_write_path(output_root, Path("probe_source.png"))
    output_root.mkdir(parents=True, exist_ok=True)
    # Revalidate after creation to close a reparse-point race at the approved root.
    output_root = validate_failure_probe_root(output_root)
    record_path = resolve_failure_probe_write_path(output_root, record_path.relative_to(output_root))
    output_path = resolve_failure_probe_write_path(output_root, output_path.relative_to(output_root))
    source_path = resolve_failure_probe_write_path(output_root, source_path.relative_to(output_root))
    if not source_path.exists():
        Image.new("RGB", (32, 24), (30, 60, 90)).save(source_path)
    try:
        candidate_stage(
            stage,
            lambda: None,
            sample_id=sample_id,
            route=route,
            input_path=source_path,
            output_path=output_path,
            fault_stage=stage,
        )
    except CandidateExecutionError as exc:
        json_write(record_path, exc.record)
        print(json.dumps({"status": "FAIL", **exc.record}, ensure_ascii=False))
        return 2
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline conservative AI 4K Stage 2 PoC")
    parser.add_argument("--batch-id")
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--refresh-sha-manifest", action="store_true")
    parser.add_argument("--failure-probe-output-root", type=Path)
    parser.add_argument("--failure-probe-record", type=Path, default=FAILURE_PROBE_DEFAULT_RECORD)
    parser.add_argument("--failure-probe-sample-id", default="STAGE2_FAULT_PROBE")
    parser.add_argument("--failure-probe-route", choices=ROUTES, default=ROUTE_B)
    parser.add_argument("--failure-probe-stage", choices=FAILURE_STAGES)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.failure_probe_stage:
            if args.failure_probe_output_root is None:
                raise Stage2Error("FAILURE_PROBE_REQUIRES_OUTPUT_ROOT")
            return run_failure_probe(
                args.failure_probe_output_root,
                args.failure_probe_record,
                args.failure_probe_sample_id,
                args.failure_probe_route,
                args.failure_probe_stage,
            )
        if not args.batch_id:
            raise Stage2Error("BATCH_ID_REQUIRED")
        batch_root = validate_batch_root(STAGE2_ROOT / args.batch_id)
        if args.refresh_sha_manifest:
            payload = refresh_sha_manifest(batch_root)
            print(json.dumps({"status": "PASS", "batch_id": args.batch_id, "file_count": payload["file_count"]}, ensure_ascii=False))
            return 0
        result = run_batch(batch_root, args.model_root)
    except CandidateExecutionError as exc:
        print(json.dumps({"status": "FAIL", **exc.record}, ensure_ascii=False))
        return 1
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error_type": type(exc).__name__, "error_message": str(exc)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "status": result["technical_status"],
                "batch_id": result["batch_id"],
                "candidate_count": result["candidate_count"],
                "protected_state_unchanged": result["protected_state_unchanged"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["technical_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
