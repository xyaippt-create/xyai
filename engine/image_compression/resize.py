from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .common import (
    CompressionRuntimeError,
    FaultInjector,
    apply_delivery_gate,
    atomic_write_bytes,
    compare_metadata,
    encode_image_bytes,
    plan_output_path,
    populate_source,
    read_image_info,
    resize_from_source,
    runtime_failure_result,
    sha256_file,
)
from .contracts import ImageCompressionResult, ImageCompressionTask, base_result_for_task
from .statuses import TechnicalStatus, VisualReviewStatus


def calculate_target_dimensions(task: ImageCompressionTask, source_dimensions: dict[str, int]) -> tuple[int, int]:
    width, height = source_dimensions["width"], source_dimensions["height"]
    if task.scale_ratio is not None:
        target = (
            max(1, int(math.floor(width * task.scale_ratio + 0.5))),
            max(1, int(math.floor(height * task.scale_ratio + 0.5))),
        )
    else:
        target = int(task.target_width or 0), int(task.target_height or 0)
    if target[0] <= 0 or target[1] <= 0 or target[0] > width or target[1] > height or target == (width, height):
        raise CompressionRuntimeError("TARGET_DIMENSION_INVALID", "Resize reduction requires smaller positive dimensions.", TechnicalStatus.CANNOT_MEET_SAFELY)
    expected_width = round(width * target[1] / height)
    if abs(expected_width - target[0]) > 1:
        raise CompressionRuntimeError("TARGET_DIMENSION_INVALID", "Target dimensions do not preserve aspect ratio within one pixel.", TechnicalStatus.CANNOT_MEET_SAFELY)
    return target


def _transparent_rgb_is_zero(path: Path) -> bool | None:
    with Image.open(path) as image:
        if "A" not in image.getbands():
            return None
        rgba = np.asarray(image.convert("RGBA"))
    transparent = rgba[..., 3] == 0
    return bool(not transparent.any() or np.all(rgba[..., :3][transparent] == 0))


def process_resize(
    task: ImageCompressionTask,
    *,
    visual_review_status: VisualReviewStatus | str | None = None,
    fault_injector: FaultInjector | None = None,
) -> ImageCompressionResult:
    started = time.perf_counter()
    source: dict[str, Any] | None = None
    try:
        source = read_image_info(task.source_path)
        if source.get("exif_orientation") not in (None, 1):
            raise CompressionRuntimeError(
                "EXIF_ORIENTATION_UNSUPPORTED",
                "Resizing an image with a non-normal EXIF orientation is outside the verified route.",
                TechnicalStatus.CANNOT_MEET_SAFELY,
            )
        target = calculate_target_dimensions(task, source["dimensions"])
        plan = plan_output_path(task, source["format"])
        resize_started = time.perf_counter()
        image, premultiplied = resize_from_source(task.source_path, target, task.resize_policy or "LANCZOS_HIGH_QUALITY")
        encoded = encode_image_bytes(image, source)
        resize_seconds = time.perf_counter() - resize_started
        output_path = atomic_write_bytes(
            encoded,
            plan,
            source_path=task.source_path,
            source_sha256=source["sha256"],
            expected_format=source["format"],
            expected_dimensions=target,
            fault_injector=fault_injector,
        )
        output = read_image_info(output_path)
        metadata_preserved, metadata_details = compare_metadata(source, output)
        result = base_result_for_task(task)
        populate_source(result, source)
        result.technical_status = TechnicalStatus.TARGET_MET_WITH_REENCODE if source["format"] == "JPEG" else TechnicalStatus.TARGET_MET
        result.visual_review_status = VisualReviewStatus(visual_review_status or VisualReviewStatus.PENDING)
        result.output_created = True
        result.output_path = str(output_path)
        result.output_sha256 = output["sha256"]
        result.output_format = source["format"]
        result.output_dimensions = dict(output["dimensions"])
        result.output_size_bytes = output["size_bytes"]
        result.size_reduction_bytes = source["size_bytes"] - output["size_bytes"]
        result.size_reduction_ratio = result.size_reduction_bytes / source["size_bytes"]
        result.dimension_scale_ratio = min(target[0] / source["dimensions"]["width"], target[1] / source["dimensions"]["height"])
        result.lossy = True
        result.reencoded = True
        result.resized = True
        result.metadata_preserved = metadata_preserved
        result.metadata_details = metadata_details
        result.alpha_preserved = source["alpha_present"] == output["alpha_present"]
        result.alpha_details.update(
            alpha_present=source["alpha_present"],
            alpha_channel_preserved=result.alpha_preserved,
            premultiplied_resize_used=premultiplied if source["alpha_present"] else None,
            fully_transparent_rgb_zero=_transparent_rgb_is_zero(output_path),
            semi_transparent_edges_reviewed=False if source["alpha_present"] else None,
            alpha_exact=False if source["alpha_present"] else None,
        )
        if not metadata_preserved:
            result.warnings.append("METADATA_NOT_FULLY_PRESERVED")
        result.processing_seconds = time.perf_counter() - started
        result.stage_seconds = {"resize_encode": resize_seconds, "verify_atomic_save": result.processing_seconds - resize_seconds}
        result.slowest_stage = max(result.stage_seconds, key=result.stage_seconds.get)
        result.validation_status = "PASS"
        if sha256_file(task.source_path) != source["sha256"]:
            try:
                output_path.unlink()
            except OSError:
                pass
            raise CompressionRuntimeError("SOURCE_SHA_CHANGED", "Source changed after resize output creation.")
        return apply_delivery_gate(result)
    except CompressionRuntimeError as exc:
        return runtime_failure_result(task, source, exc, started)


process = process_resize
