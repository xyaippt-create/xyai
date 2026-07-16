from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

from .common import (
    CompressionRuntimeError,
    FaultInjector,
    apply_delivery_gate,
    atomic_write_bytes,
    compare_metadata,
    encode_image_bytes,
    no_processing_result,
    optimise_png_data,
    optimise_png_bytes,
    plan_output_path,
    populate_source,
    read_image_info,
    resize_from_source,
    runtime_failure_result,
    sha256_file,
)
from .contracts import ImageCompressionResult, ImageCompressionTask, base_result_for_task
from .statuses import TechnicalStatus, VisualReviewStatus


JPEG_QUALITIES = (95, 92, 90, 88, 85, 82, 80)
FIXED_SCALES = (0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50)
MIN_SAFE_SCALE = 0.50


def _within_limits(width: int, height: int, size_bytes: int, task: ImageCompressionTask) -> bool:
    return (
        (task.max_width is None or width <= task.max_width)
        and (task.max_height is None or height <= task.max_height)
        and (task.max_file_size_bytes is None or size_bytes <= task.max_file_size_bytes)
    )


def _candidate_dimensions(source: dict[str, Any], task: ImageCompressionTask) -> list[tuple[int, int]]:
    width, height = source["dimensions"]["width"], source["dimensions"]["height"]
    scale_limit = 1.0
    if task.max_width is not None:
        scale_limit = min(scale_limit, task.max_width / width)
    if task.max_height is not None:
        scale_limit = min(scale_limit, task.max_height / height)
    if scale_limit < MIN_SAFE_SCALE:
        return []
    scales = [scale_limit, *(scale for scale in FIXED_SCALES if scale <= scale_limit + 1e-9)]
    dimensions: list[tuple[int, int]] = []
    for scale in scales:
        if scale < MIN_SAFE_SCALE - 1e-9:
            continue
        candidate = (
            min(width, max(1, int(math.floor(width * scale + 0.5)))),
            min(height, max(1, int(math.floor(height * scale + 0.5)))),
        )
        if task.max_width is not None and candidate[0] > task.max_width:
            candidate = task.max_width, max(1, int(math.floor(height * task.max_width / width + 0.5)))
        if task.max_height is not None and candidate[1] > task.max_height:
            candidate = max(1, int(math.floor(width * task.max_height / height + 0.5))), task.max_height
        if candidate not in dimensions:
            dimensions.append(candidate)
    return dimensions


def process_upload_adaptation(
    task: ImageCompressionTask,
    *,
    visual_review_status: VisualReviewStatus | str | None = None,
    fault_injector: FaultInjector | None = None,
) -> ImageCompressionResult:
    started = time.perf_counter()
    source: dict[str, Any] | None = None
    try:
        source = read_image_info(task.source_path)
        width, height = source["dimensions"]["width"], source["dimensions"]["height"]
        if _within_limits(width, height, source["size_bytes"], task):
            return no_processing_result(task, source, started)
        if source.get("exif_orientation") not in (None, 1):
            raise CompressionRuntimeError(
                "EXIF_ORIENTATION_UNSUPPORTED",
                "Upload adaptation of a non-normal EXIF orientation is outside the verified route.",
                TechnicalStatus.CANNOT_MEET_SAFELY,
            )
        dimensions = _candidate_dimensions(source, task)
        if not dimensions:
            raise CompressionRuntimeError(
                "UPLOAD_LIMITS_BELOW_SAFE_FLOOR",
                "Upload limits require dimensions below the verified 50% search floor.",
                TechnicalStatus.CANNOT_MEET_SAFELY,
            )

        selected: bytes | None = None
        selected_dimensions: tuple[int, int] | None = None
        selected_quality: int | None = None
        selected_resized = False
        attempts: list[dict[str, Any]] = []
        search_started = time.perf_counter()
        for candidate_dimensions in dimensions:
            same_dimensions = candidate_dimensions == (width, height)
            if source["format"] == "PNG":
                if same_dimensions:
                    candidate, optimisation = optimise_png_bytes(task.source_path)
                    options = [(candidate, "png_source_idat_optimised", optimisation)]
                else:
                    image, _ = resize_from_source(task.source_path, candidate_dimensions, "LANCZOS_HIGH_QUALITY")
                    encoded = encode_image_bytes(image, source)
                    optimised, optimisation = optimise_png_data(encoded)
                    options = sorted(
                        [(encoded, "png_direct_lanczos", {}), (optimised, "png_direct_lanczos_idat_optimised", optimisation)],
                        key=lambda item: len(item[0]),
                    )
                for candidate, kind, details in options:
                    meets = _within_limits(candidate_dimensions[0], candidate_dimensions[1], len(candidate), task)
                    attempts.append({"dimensions": list(candidate_dimensions), "quality": None, "kind": kind, "size_bytes": len(candidate), "meets_limits": meets, "direct_source_lineage": True, "details": details})
                    if meets:
                        selected = candidate
                        selected_dimensions = candidate_dimensions
                        selected_resized = not same_dimensions
                        break
            else:
                image, _ = resize_from_source(task.source_path, candidate_dimensions, "LANCZOS_HIGH_QUALITY") if not same_dimensions else (None, False)
                for quality in JPEG_QUALITIES:
                    if same_dimensions:
                        from PIL import Image

                        with Image.open(task.source_path) as opened:
                            opened.load()
                            direct = opened.copy()
                    else:
                        direct = image
                    candidate = encode_image_bytes(direct, source, jpeg_quality=quality)
                    meets = _within_limits(candidate_dimensions[0], candidate_dimensions[1], len(candidate), task)
                    attempts.append({"dimensions": list(candidate_dimensions), "quality": quality, "kind": "jpeg_direct_lossy", "size_bytes": len(candidate), "meets_limits": meets, "direct_source_lineage": True})
                    if meets:
                        selected = candidate
                        selected_dimensions = candidate_dimensions
                        selected_quality = quality
                        selected_resized = not same_dimensions
                        break
            if selected is not None:
                break
        search_seconds = time.perf_counter() - search_started
        if selected is None or selected_dimensions is None:
            raise CompressionRuntimeError(
                "UPLOAD_LIMITS_CANNOT_MEET_SAFELY",
                "No candidate met limits at or above 50% scale and JPEG quality 80.",
                TechnicalStatus.CANNOT_MEET_SAFELY,
            )

        plan = plan_output_path(task, source["format"])
        output_path = atomic_write_bytes(
            selected,
            plan,
            source_path=task.source_path,
            source_sha256=source["sha256"],
            expected_format=source["format"],
            expected_dimensions=selected_dimensions,
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
        result.dimension_scale_ratio = min(selected_dimensions[0] / width, selected_dimensions[1] / height)
        result.lossy = source["format"] == "JPEG" or selected_resized
        result.reencoded = True
        result.resized = selected_resized
        result.metadata_preserved = metadata_preserved
        result.metadata_details = metadata_details
        result.alpha_preserved = source["alpha_present"] == output["alpha_present"]
        result.alpha_details.update(
            alpha_present=source["alpha_present"],
            alpha_channel_preserved=result.alpha_preserved,
            premultiplied_resize_used=True if source["alpha_present"] and selected_resized else None,
            fully_transparent_rgb_zero=True if source["alpha_present"] and selected_resized else None,
            semi_transparent_edges_reviewed=False if source["alpha_present"] and selected_resized else None,
            alpha_exact=(not selected_resized) if source["alpha_present"] else None,
        )
        result.processing_seconds = time.perf_counter() - started
        result.stage_seconds = {"candidate_search": search_seconds, "verify_atomic_save": result.processing_seconds - search_seconds}
        result.slowest_stage = max(result.stage_seconds, key=result.stage_seconds.get)
        result.evidence_paths = {"candidate_attempts": attempts, "selected_jpeg_quality": selected_quality, "generation_parent": "immutable_source_pixels"}
        result.validation_status = "PASS"
        if not metadata_preserved:
            result.warnings.append("METADATA_NOT_FULLY_PRESERVED")
        if sha256_file(task.source_path) != source["sha256"]:
            try:
                output_path.unlink()
            except OSError:
                pass
            raise CompressionRuntimeError("SOURCE_SHA_CHANGED", "Source changed after upload adaptation output creation.")
        return apply_delivery_gate(result)
    except CompressionRuntimeError as exc:
        return runtime_failure_result(task, source, exc, started)


process = process_upload_adaptation
