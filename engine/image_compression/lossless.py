from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .common import (
    CompressionRuntimeError,
    FaultInjector,
    apply_delivery_gate,
    atomic_write_bytes,
    no_processing_result,
    optimise_png_bytes,
    plan_output_path,
    png_non_idat_chunks,
    populate_source,
    read_image_info,
    runtime_failure_result,
    sha256_file,
)
from .contracts import ImageCompressionResult, ImageCompressionTask, base_result_for_task
from .statuses import TechnicalStatus, VisualReviewStatus


def process_lossless(task: ImageCompressionTask, *, fault_injector: FaultInjector | None = None) -> ImageCompressionResult:
    started = time.perf_counter()
    source: dict[str, Any] | None = None
    try:
        source = read_image_info(task.source_path)
        if source["format"] == "JPEG":
            raise CompressionRuntimeError(
                "JPEG_COEFFICIENT_LOSSLESS_NOT_IMPLEMENTED",
                "JPEG coefficient-level true lossless compression is not implemented.",
                TechnicalStatus.CANNOT_MEET_SAFELY,
            )
        if source["format"] != "PNG":
            raise CompressionRuntimeError("SOURCE_FORMAT_UNSUPPORTED", "The verified lossless route supports static PNG only.", TechnicalStatus.CANNOT_MEET_SAFELY)
        candidate_bytes, optimisation = optimise_png_bytes(task.source_path)
        if len(candidate_bytes) >= source["size_bytes"]:
            result = no_processing_result(task, source, started)
            result.warnings.append("NO_SIZE_GAIN")
            result.evidence_paths = {"lossless_optimisation": optimisation}
            return result

        plan = plan_output_path(task, "PNG")
        source_raw = Path(task.source_path).read_bytes()
        source_non_idat = png_non_idat_chunks(source_raw)

        def verify_lossless(candidate_path: Path) -> None:
            output = read_image_info(candidate_path)
            if output["pixel_sha256"] != source["pixel_sha256"]:
                raise CompressionRuntimeError("LOSSLESS_PIXEL_MISMATCH", "Decoded pixels changed during PNG lossless compression.")
            if output["alpha_sha256"] != source["alpha_sha256"]:
                raise CompressionRuntimeError("LOSSLESS_ALPHA_MISMATCH", "Alpha changed during PNG lossless compression.")
            if png_non_idat_chunks(candidate_path.read_bytes()) != source_non_idat:
                raise CompressionRuntimeError("PNG_NON_IDAT_CHANGED", "PNG non-IDAT chunks changed during lossless compression.")

        output_path = atomic_write_bytes(
            candidate_bytes,
            plan,
            source_path=task.source_path,
            source_sha256=source["sha256"],
            expected_format="PNG",
            expected_dimensions=(source["dimensions"]["width"], source["dimensions"]["height"]),
            fault_injector=fault_injector,
            extra_verifier=verify_lossless,
        )
        output = read_image_info(output_path)
        result = base_result_for_task(task)
        populate_source(result, source)
        result.technical_status = TechnicalStatus.TARGET_MET
        result.visual_review_status = VisualReviewStatus.NOT_REQUIRED
        result.output_created = True
        result.output_path = str(output_path)
        result.output_sha256 = output["sha256"]
        result.output_format = "PNG"
        result.output_dimensions = dict(output["dimensions"])
        result.output_size_bytes = output["size_bytes"]
        result.size_reduction_bytes = source["size_bytes"] - output["size_bytes"]
        result.size_reduction_ratio = result.size_reduction_bytes / source["size_bytes"]
        result.dimension_scale_ratio = 1.0
        result.lossy = False
        result.reencoded = True
        result.resized = False
        result.metadata_preserved = True
        result.metadata_details.update(
            icc_preserved=True,
            exif_preserved=True,
            dpi_preserved=True,
            xmp_preserved=True,
            orientation_semantics_correct=True,
            png_non_idat_preserved=True,
            png_plte_preserved=True,
            png_trns_preserved=True,
        )
        result.alpha_preserved = True
        result.alpha_details.update(
            alpha_present=source["alpha_present"],
            alpha_channel_preserved=True if source["alpha_present"] else None,
            alpha_exact=True if source["alpha_present"] else None,
        )
        result.processing_seconds = time.perf_counter() - started
        result.stage_seconds = {"idat_optimisation_and_verify": result.processing_seconds}
        result.slowest_stage = "idat_optimisation_and_verify"
        result.evidence_paths = {"lossless_optimisation": optimisation}
        result.validation_status = "PASS"
        if sha256_file(task.source_path) != source["sha256"]:
            try:
                output_path.unlink()
            except OSError:
                pass
            raise CompressionRuntimeError("SOURCE_SHA_CHANGED", "Source changed after lossless output creation.")
        return apply_delivery_gate(result, strict_lossless_evidence=True)
    except CompressionRuntimeError as exc:
        return runtime_failure_result(task, source, exc, started)


process = process_lossless
