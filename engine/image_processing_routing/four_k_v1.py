from __future__ import annotations

import copy
import hashlib
import math
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


FOUR_K_V1_CONTRACT_VERSION = "4k_v1_contract_1.0"
FOUR_K_V1_ROUTE = "PILLOW_LANCZOS_SAFE_RESIZE"
FOUR_K_V1_MODE = "4k_v1"
FOUR_K_V1_OUTPUT_PROFILE = "delivery_4k_v1"
FOUR_K_V1_TARGET_RESOLUTION = "4K"
FOUR_K_V1_TARGET_LONG_EDGE = 3840
FOUR_K_V1_OUTPUT_FORMAT = "PNG"
FOUR_K_V1_OUTPUT_DIRECTORY = "输出/4K高清增强"
FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY = "HIGH_QUALITY_SIZE_ADAPTATION_ONLY"


_FOUR_K_V1_CONTRACT: dict[str, Any] = {
    "contract_version": FOUR_K_V1_CONTRACT_VERSION,
    "freeze_status": "FROZEN",
    "route": FOUR_K_V1_ROUTE,
    "mode": FOUR_K_V1_MODE,
    "output_profile": FOUR_K_V1_OUTPUT_PROFILE,
    "target_resolution": FOUR_K_V1_TARGET_RESOLUTION,
    "quality_capability_boundary": FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY,
    "request": {
        "endpoint": "/api/upload",
        "content_type": "multipart/form-data",
        "required_fields": ["file", "mode", "output_profile", "output_format"],
        "fixed_parameters": {
            "mode": FOUR_K_V1_MODE,
            "output_profile": FOUR_K_V1_OUTPUT_PROFILE,
            "output_format": "png",
        },
        "forbidden_overrides": [
            "scale",
            "target_width",
            "target_height",
            "target_long_edge",
            "resize_method",
            "ai_model",
            "enhancement_strength",
        ],
    },
    "dimensions": {
        "target_long_edge": FOUR_K_V1_TARGET_LONG_EDGE,
        "aspect_ratio_policy": "PRESERVE",
        "rounding_policy": "ROUND_HALF_UP",
        "maximum_aspect_ratio_error_pixels": 1,
        "source_long_edge_lt_3840": "UPSCALE_LONG_EDGE_TO_3840",
        "source_long_edge_ge_3840": "NO_PROCESSING_NEEDED",
        "crop_policy": "FORBIDDEN",
        "stretch_policy": "FORBIDDEN",
        "padding_policy": "FORBIDDEN",
    },
    "source": {
        "policy": "DIRECT_FROM_ORIGINAL",
        "original_write_policy": "READ_ONLY",
        "forbidden_sources": [
            "1080P_STANDARD_OUTPUT",
            "1080P_SAFE_OUTPUT",
            "OTHER_RESIZED_OR_ENHANCED_INTERMEDIATE",
        ],
        "required_integrity_fields": [
            "input_hash",
            "input_width",
            "input_height",
            "input_format",
            "has_alpha",
        ],
    },
    "output": {
        "directory_relative_to_formal_root": FOUR_K_V1_OUTPUT_DIRECTORY,
        "directory_failure_policy": "BLOCK_NO_FALLBACK",
        "file_name_pattern": "{source_stem}_影界4K适配_{yyyyMMdd_HHmmss}_{short_id}.png",
        "collision_policy": "CREATE_UNIQUE_NO_OVERWRITE",
        "format": FOUR_K_V1_OUTPUT_FORMAT,
        "extension": ".png",
        "lossless_encoding": True,
        "resample": "Pillow.Image.Resampling.LANCZOS",
        "preserve_icc_profile_when_present": True,
        "preserve_alpha_with_premultiplied_resize": True,
        "success_gates": [
            "OUTPUT_EXISTS",
            "OUTPUT_DECODES",
            "OUTPUT_DIMENSIONS_MATCH_PLAN",
            "SOURCE_HASH_UNCHANGED",
        ],
    },
    "state_semantics": {
        "preflight_statuses": ["READY", "NO_PROCESSING_NEEDED", "BLOCKED"],
        "task_statuses": ["pending", "processing", "completed", "failed", "blocked"],
        "progress_range": [0, 100],
        "completed_requires": [
            "OUTPUT_EXISTS",
            "OUTPUT_DECODES",
            "OUTPUT_DIMENSIONS_MATCH_PLAN",
        ],
        "blocked_before_execution": [
            "FORMAL_DIRECTORY_NOT_READY",
            "SOURCE_NOT_ORIGINAL",
            "SOURCE_UNAVAILABLE",
            "UNSUPPORTED_OR_UNDECODABLE_IMAGE",
            "INVALID_4K_REQUEST",
        ],
        "failed_after_execution_started": [
            "SOURCE_READ_FAILED",
            "RESIZE_FAILED",
            "OUTPUT_WRITE_FAILED",
            "OUTPUT_VERIFY_FAILED",
        ],
        "forbidden_success_fallbacks": [
            "PROJECT_TMP",
            "RUNTIME_DATA",
            "SOURCE_AS_RESULT",
            "STALE_OUTPUT",
        ],
    },
    "quality_semantics": {
        "allowed_conclusions": [
            "NOT_ASSESSED",
            "SIZE_ADAPTATION_COMPLETED",
            "NO_PROCESSING_NEEDED",
            "BLOCKED",
            "FAILED",
        ],
        "completed_conclusion": "SIZE_ADAPTATION_COMPLETED",
        "already_4k_conclusion": "NO_PROCESSING_NEEDED",
        "prohibited_claims": [
            "DETAIL_RECONSTRUCTION_PROVEN",
            "SUPER_RESOLUTION_PROVEN",
            "QUALITY_GAIN_PROVEN",
            "AI_ENHANCEMENT_PROVEN",
        ],
    },
    "single_image_loop_fields": {
        "upload_response": [
            "task_id",
            "task_status",
            "task_progress",
            "streamEndpoint",
            "originalUrl",
        ],
        "task": [
            "task_id",
            "task_status",
            "task_progress",
            "processing_stage",
            "processing_disposition",
            "mode",
            "route",
            "target_resolution",
            "original_filename",
            "input_hash",
            "input_width",
            "input_height",
            "target_width",
            "target_height",
            "output_width",
            "output_height",
            "output_format",
            "final_output_url",
            "final_output_exists",
            "quality_conclusion",
            "error_code",
            "error_message",
        ],
        "sse": [
            "task_id",
            "task_status",
            "task_progress",
            "processing_stage",
            "message",
            "error_code",
        ],
        "comparison": [
            "originalUrl",
            "final_output_url",
            "input_width",
            "input_height",
            "output_width",
            "output_height",
        ],
        "report": [
            "mode",
            "route",
            "quality_capability_boundary",
            "quality_conclusion",
            "input_width",
            "input_height",
            "output_width",
            "output_height",
            "output_format",
            "source_hash_unchanged",
            "warnings",
        ],
        "open_result": [
            "final_output_url",
            "final_output_exists",
            "output_directory_token",
        ],
        "backend_only": [
            "input_path",
            "expected_output_path",
            "output_path",
            "output_dir",
        ],
    },
    "frozen_evidence": {
        "stage1_standard": "artifacts/4k_stage1_baseline/4k_standard_v1.json",
        "stage1_baseline_selection": "artifacts/4k_stage1_baseline/results/baseline_selection.json",
        "stage2_negative_closure": "artifacts/4k_stage2_ai_poc/4K_STAGE_2_POC_VALUE_NOT_PROVEN_CLOSURE_REPORT.md",
        "route_b_product_adoption": "NO",
    },
}


def get_4k_v1_contract() -> dict[str, Any]:
    """Return an isolated copy of the frozen 4K V1 product contract."""

    return copy.deepcopy(_FOUR_K_V1_CONTRACT)


def plan_4k_v1_dimensions(width: int, height: int) -> dict[str, Any]:
    """Plan the frozen long-edge 4K size treatment without touching image data."""

    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
    ):
        raise ValueError("INVALID_SOURCE_DIMENSIONS")

    source_long_edge = max(width, height)
    if source_long_edge >= FOUR_K_V1_TARGET_LONG_EDGE:
        return {
            "preflight_status": "NO_PROCESSING_NEEDED",
            "processing_disposition": "NO_PROCESSING_NEEDED",
            "input_width": width,
            "input_height": height,
            "target_width": width,
            "target_height": height,
            "scale": 1.0,
            "quality_conclusion": "NO_PROCESSING_NEEDED",
        }

    scale = FOUR_K_V1_TARGET_LONG_EDGE / source_long_edge
    target_width = max(1, int(math.floor(width * scale + 0.5)))
    target_height = max(1, int(math.floor(height * scale + 0.5)))
    return {
        "preflight_status": "READY",
        "processing_disposition": "UPSCALE_LONG_EDGE_TO_3840",
        "input_width": width,
        "input_height": height,
        "target_width": target_width,
        "target_height": target_height,
        "scale": scale,
        "quality_conclusion": "NOT_ASSESSED",
    }


class FourKV1ProcessingError(RuntimeError):
    """Structured failure raised by the frozen 4K V1 execution route."""

    def __init__(self, code: str, stage: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.hdde_failed_stage = stage


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _emit_stage(callback, stage: str, progress: int, message: str) -> None:
    if callback is not None:
        callback(stage, progress, message)


def _safe_source_stem(source_path: Path) -> str:
    stem = source_path.stem.strip() or "图片"
    sanitized = "".join(character if character not in '<>:"/\\|?*' else "_" for character in stem)
    return sanitized[:80].rstrip(" .") or "图片"


def build_4k_v1_output_path(
    source_path: str | Path,
    formal_root: str | Path,
    *,
    timestamp: datetime | None = None,
    short_id: str | None = None,
) -> Path:
    """Build a unique formal output path from the frozen output contract."""

    source = Path(source_path)
    root = Path(formal_root).expanduser().resolve()
    output_dir = (root / Path(FOUR_K_V1_OUTPUT_DIRECTORY)).resolve()
    if output_dir != root and root not in output_dir.parents:
        raise FourKV1ProcessingError("FORMAL_DIRECTORY_NOT_READY", "contract_validation", "4K输出目录超出正式目录。")

    moment = timestamp or datetime.now()
    token = (short_id or uuid.uuid4().hex[:8]).strip()[:12]
    base = f"{_safe_source_stem(source)}_影界4K适配_{moment:%Y%m%d_%H%M%S}_{token}"
    candidate = output_dir / f"{base}.png"
    counter = 2
    while candidate.exists():
        candidate = output_dir / f"{base}_{counter}.png"
        counter += 1
    return candidate


def inspect_4k_v1_source(source_path: str | Path) -> dict[str, Any]:
    """Read only the uploaded source and return contract facts."""

    source = Path(source_path)
    if not source.is_file():
        raise FourKV1ProcessingError("SOURCE_UNAVAILABLE", "contract_validation", "找不到待处理的原始图片。")
    try:
        source_hash = _sha256_file(source)
        with Image.open(source) as image:
            image.load()
            width, height = image.size
            source_format = str(image.format or source.suffix.lstrip(".") or "UNKNOWN").upper()
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            icc_profile = image.info.get("icc_profile")
    except FourKV1ProcessingError:
        raise
    except Exception as exc:
        raise FourKV1ProcessingError(
            "UNSUPPORTED_OR_UNDECODABLE_IMAGE",
            "contract_validation",
            f"图片无法解码：{exc}",
        ) from exc

    plan = plan_4k_v1_dimensions(width, height)
    return {
        **plan,
        "input_hash": source_hash,
        "input_format": source_format,
        "has_alpha": bool(has_alpha),
        "icc_profile_present": isinstance(icc_profile, bytes) and bool(icc_profile),
    }


def process_4k_v1_image(
    source_path: str | Path,
    formal_root: str | Path,
    *,
    output_path: str | Path | None = None,
    stage_callback=None,
) -> dict[str, Any]:
    """Execute the frozen Pillow LANCZOS 4K V1 route against one source image."""

    source = Path(source_path)
    root = Path(formal_root).expanduser().resolve()
    _emit_stage(stage_callback, "contract_validation", 20, "正在核对4K处理合同与原图信息")
    source_meta = inspect_4k_v1_source(source)
    destination = Path(output_path) if output_path else build_4k_v1_output_path(source, root)
    destination = destination.expanduser().resolve()
    expected_root = (root / Path(FOUR_K_V1_OUTPUT_DIRECTORY)).resolve()
    if destination.parent != expected_root:
        raise FourKV1ProcessingError("INVALID_4K_REQUEST", "contract_validation", "4K成品必须写入正式4K输出目录。")

    common = {
        "mode": FOUR_K_V1_MODE,
        "route": FOUR_K_V1_ROUTE,
        "output_profile": FOUR_K_V1_OUTPUT_PROFILE,
        "target_resolution": FOUR_K_V1_TARGET_RESOLUTION,
        "quality_capability_boundary": FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY,
        "input_hash": source_meta["input_hash"],
        "input_width": source_meta["input_width"],
        "input_height": source_meta["input_height"],
        "input_format": source_meta["input_format"],
        "has_alpha": source_meta["has_alpha"],
        "target_width": source_meta["target_width"],
        "target_height": source_meta["target_height"],
        "processing_disposition": source_meta["processing_disposition"],
        "resize_policy": source_meta["processing_disposition"],
        "output_format": FOUR_K_V1_OUTPUT_FORMAT,
    }

    if source_meta["processing_disposition"] == "NO_PROCESSING_NEEDED":
        _emit_stage(stage_callback, "output_verify", 100, "原图长边已达到4K门槛，无需重复放大")
        report = {
            **common,
            "quality_conclusion": "NO_PROCESSING_NEEDED",
            "source_hash_unchanged": _sha256_file(source) == source_meta["input_hash"],
            "warnings": ["原图长边已达到3840像素，未执行像素放大。"],
        }
        return {
            **common,
            "task_result": {
                **common,
                "output_width": source_meta["input_width"],
                "output_height": source_meta["input_height"],
                "final_output_exists": False,
                "final_output_url": "",
                "quality_conclusion": "NO_PROCESSING_NEEDED",
            },
            "task_report": report,
            "quality_conclusion": "NO_PROCESSING_NEEDED",
            "source_hash_unchanged": report["source_hash_unchanged"],
            "final_output_path": "",
            "final_output_exists": False,
        }

    temp_path: Path | None = None
    try:
        _emit_stage(stage_callback, "image_processing", 45, "正在进行4K高清画质增强")
        with Image.open(source) as opened:
            icc_profile = opened.info.get("icc_profile")
            image = ImageOps.exif_transpose(opened)
            image.load()
            target_size = (source_meta["target_width"], source_meta["target_height"])
            if source_meta["has_alpha"]:
                resized = image.convert("RGBA").convert("RGBa").resize(target_size, Image.Resampling.LANCZOS).convert("RGBA")
            else:
                resized = image.convert("RGB").resize(target_size, Image.Resampling.LANCZOS)

        _emit_stage(stage_callback, "output_file_write", 72, "正在写入正式4K成品")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = destination.with_name(f".{destination.stem}.{uuid.uuid4().hex}.tmp.png")
        save_options: dict[str, Any] = {"format": "PNG", "compress_level": 6}
        if isinstance(icc_profile, bytes) and icc_profile:
            save_options["icc_profile"] = icc_profile
        resized.save(temp_path, **save_options)
        temp_path.replace(destination)
    except FourKV1ProcessingError:
        raise
    except OSError as exc:
        raise FourKV1ProcessingError("OUTPUT_WRITE_FAILED", "output_file_write", f"4K成品写入失败：{exc}") from exc
    except Exception as exc:
        raise FourKV1ProcessingError("RESIZE_FAILED", "image_processing", f"4K尺寸适配失败：{exc}") from exc
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)

    _emit_stage(stage_callback, "output_verify", 90, "正在核对成品文件与像素尺寸")
    try:
        with Image.open(destination) as output_image:
            output_image.load()
            output_width, output_height = output_image.size
        if (output_width, output_height) != (source_meta["target_width"], source_meta["target_height"]):
            raise ValueError("OUTPUT_DIMENSIONS_MISMATCH")
        source_hash_unchanged = _sha256_file(source) == source_meta["input_hash"]
        if not source_hash_unchanged:
            raise ValueError("SOURCE_HASH_CHANGED")
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise FourKV1ProcessingError("OUTPUT_VERIFY_FAILED", "output_verify", f"4K成品验证失败：{exc}") from exc

    _emit_stage(stage_callback, "completed", 100, "4K高清画质增强完成")
    task_result = {
        **common,
        "output_filename": destination.name,
        "output_path": str(destination),
        "final_output_path": str(destination),
        "output_width": output_width,
        "output_height": output_height,
        "output_size": destination.stat().st_size,
        "final_output_exists": True,
        "quality_conclusion": "SIZE_ADAPTATION_COMPLETED",
        "source_hash_unchanged": source_hash_unchanged,
    }
    task_report = {
        **common,
        "output_width": output_width,
        "output_height": output_height,
        "quality_conclusion": "SIZE_ADAPTATION_COMPLETED",
        "source_hash_unchanged": source_hash_unchanged,
        "warnings": [
            "本结果仅代表高质量4K尺寸增强适配，不代表真实细节重建、AI超分辨率或已证明的画质增益。"
        ],
    }
    return {
        **common,
        "task_result": task_result,
        "task_report": task_report,
        "quality_conclusion": "SIZE_ADAPTATION_COMPLETED",
        "source_hash_unchanged": source_hash_unchanged,
        "final_output_path": str(destination),
        "final_output_exists": True,
        "output_width": output_width,
        "output_height": output_height,
        "output_format": FOUR_K_V1_OUTPUT_FORMAT,
    }


__all__ = [
    "FOUR_K_V1_CONTRACT_VERSION",
    "FOUR_K_V1_MODE",
    "FOUR_K_V1_OUTPUT_DIRECTORY",
    "FOUR_K_V1_OUTPUT_FORMAT",
    "FOUR_K_V1_OUTPUT_PROFILE",
    "FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY",
    "FOUR_K_V1_ROUTE",
    "FOUR_K_V1_TARGET_LONG_EDGE",
    "FOUR_K_V1_TARGET_RESOLUTION",
    "FourKV1ProcessingError",
    "build_4k_v1_output_path",
    "get_4k_v1_contract",
    "inspect_4k_v1_source",
    "plan_4k_v1_dimensions",
    "process_4k_v1_image",
]
