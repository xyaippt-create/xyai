"""Isolated Swin2SR research adapter for E4K-03.

The adapter owns model I/O only.  It never decides safety, quality, review, or
delivery and is intentionally reachable only through ``run_4k_candidate``.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import psutil
import torch
from PIL import Image

from .candidate_framework import (
    PRODUCT,
    CandidateDefinition,
    CandidateExecutionRequest,
    sha256_file,
)


ADAPTER_VERSION = "E4K_03_SWIN2SR_CANDIDATE_ADAPTER_V1"
MODEL_ID = "caidas/swin2SR-realworld-sr-x4-64-bsrgan-psnr"
NATIVE_SCALE = 4
TileInference = Callable[[Image.Image], Image.Image]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


class Swin2SRCandidateAdapter:
    """Lazy-loaded, deterministic FP32 CPU adapter with explicit context tiles."""

    def __init__(
        self,
        model_root: str | Path,
        *,
        tile_core: int = 224,
        tile_context: int = 16,
        tile_inference: TileInference | None = None,
    ) -> None:
        self.model_root = Path(model_root).expanduser().resolve()
        self.model_path = self.model_root / "pytorch_model.bin"
        if not self.model_path.is_file():
            raise FileNotFoundError(f"SWIN2SR_MODEL_MISSING:{self.model_path}")
        if tile_core <= 0 or tile_core % 8:
            raise ValueError("TILE_CORE_MUST_BE_POSITIVE_MULTIPLE_OF_8")
        if tile_context < 0 or tile_context % 8:
            raise ValueError("TILE_CONTEXT_MUST_BE_NONNEGATIVE_MULTIPLE_OF_8")
        self.tile_core = tile_core
        self.tile_context = tile_context
        self._tile_inference_override = tile_inference
        self._processor: Any = None
        self._model: Any = None
        self._model_load_time_seconds = 0.0

    @property
    def model_sha256(self) -> str:
        return sha256_file(self.model_path)

    def _load(self) -> None:
        if self._tile_inference_override is not None or self._model is not None:
            return
        from transformers import (
            Swin2SRForImageSuperResolution,
            Swin2SRImageProcessor,
        )

        started = time.perf_counter()
        self._processor = Swin2SRImageProcessor.from_pretrained(
            self.model_root, local_files_only=True
        )
        self._model = Swin2SRForImageSuperResolution.from_pretrained(
            self.model_root, local_files_only=True
        ).eval()
        self._model.to(device="cpu", dtype=torch.float32)
        self._model_load_time_seconds = time.perf_counter() - started

    def _infer_tile(self, tile: Image.Image) -> Image.Image:
        if self._tile_inference_override is not None:
            output = self._tile_inference_override(tile)
            if output.mode != "RGB":
                raise RuntimeError("TEST_TILE_INFERENCE_OUTPUT_NOT_RGB")
            return output
        self._load()
        inputs = self._processor(images=tile, return_tensors="pt").pixel_values
        with torch.inference_mode():
            reconstructed = self._model(pixel_values=inputs).reconstruction
        reconstructed = reconstructed[0, :, : tile.height * 4, : tile.width * 4]
        array = (
            reconstructed.clamp(0.0, 1.0)
            .permute(1, 2, 0)
            .mul(255.0)
            .round()
            .to(torch.uint8)
            .cpu()
            .numpy()
        )
        return Image.fromarray(array, "RGB")

    def __call__(self, request: CandidateExecutionRequest) -> None:
        process = psutil.Process(os.getpid())
        started = time.perf_counter()
        observed_peak_rss = process.memory_info().rss
        with Image.open(request.source_path) as opened:
            opened.load()
            source_rgb = opened.convert("RGB")
        with Image.open(request.baseline_path) as opened:
            opened.load()
            if opened.mode not in {"RGB", "RGBA"}:
                raise RuntimeError(f"BASELINE_MODE_UNSUPPORTED:{opened.mode}")
            baseline_mode = opened.mode
            baseline_size = opened.size
            baseline_alpha = (
                opened.getchannel("A").copy() if opened.mode == "RGBA" else None
            )
            icc_profile = opened.info.get("icc_profile")
            exif = opened.info.get("exif")

        native = Image.new(
            "RGB", (source_rgb.width * NATIVE_SCALE, source_rgb.height * NATIVE_SCALE)
        )
        inference_seconds = 0.0
        tile_count = 0
        for y0 in range(0, source_rgb.height, self.tile_core):
            y1 = min(source_rgb.height, y0 + self.tile_core)
            for x0 in range(0, source_rgb.width, self.tile_core):
                x1 = min(source_rgb.width, x0 + self.tile_core)
                expanded_x0 = max(0, x0 - self.tile_context)
                expanded_y0 = max(0, y0 - self.tile_context)
                expanded_x1 = min(source_rgb.width, x1 + self.tile_context)
                expanded_y1 = min(source_rgb.height, y1 + self.tile_context)
                tile = source_rgb.crop(
                    (expanded_x0, expanded_y0, expanded_x1, expanded_y1)
                )
                inference_started = time.perf_counter()
                enhanced = self._infer_tile(tile)
                inference_seconds += time.perf_counter() - inference_started
                expected_size = (tile.width * NATIVE_SCALE, tile.height * NATIVE_SCALE)
                if enhanced.size != expected_size:
                    raise RuntimeError(
                        f"SWIN2SR_NATIVE_OUTPUT_SIZE_INVALID:{enhanced.size}:{expected_size}"
                    )
                core = enhanced.crop(
                    (
                        (x0 - expanded_x0) * NATIVE_SCALE,
                        (y0 - expanded_y0) * NATIVE_SCALE,
                        (x1 - expanded_x0) * NATIVE_SCALE,
                        (y1 - expanded_y0) * NATIVE_SCALE,
                    )
                )
                native.paste(core, (x0 * NATIVE_SCALE, y0 * NATIVE_SCALE))
                tile_count += 1
                observed_peak_rss = max(observed_peak_rss, process.memory_info().rss)

        final_rgb = native.resize(baseline_size, Image.Resampling.LANCZOS)
        if baseline_mode == "RGBA":
            assert baseline_alpha is not None
            output = Image.merge("RGBA", (*final_rgb.split(), baseline_alpha))
        else:
            output = final_rgb
        save_options: dict[str, Any] = {"format": "PNG"}
        if isinstance(icc_profile, bytes) and icc_profile:
            save_options["icc_profile"] = icc_profile
        if isinstance(exif, bytes) and exif:
            save_options["exif"] = exif
        output.save(request.output_path, **save_options)
        total_seconds = time.perf_counter() - started
        observed_peak_rss = max(observed_peak_rss, process.memory_info().rss)
        _write_json(
            request.run_directory / "candidate_runtime.json",
            {
                "runtime_version": "E4K_03_CANDIDATE_RUNTIME_V1",
                "adapter_version": ADAPTER_VERSION,
                "candidate_id": request.candidate_id,
                "run_id": request.run_id,
                "model_id": MODEL_ID,
                "model_sha256": self.model_sha256,
                "backend": "PYTORCH_RESEARCH_RUNTIME",
                "precision": "FP32",
                "device": "CPU",
                "model_load_time_seconds": self._model_load_time_seconds,
                "inference_time_seconds": inference_seconds,
                "total_processing_time_seconds": total_seconds,
                "observed_peak_rss_bytes": observed_peak_rss,
                "input_pixels": source_rgb.width * source_rgb.height,
                "native_output_pixels": native.width * native.height,
                "output_pixels": output.width * output.height,
                "tile_core": self.tile_core,
                "tile_context": self.tile_context,
                "tile_count": tile_count,
                "native_scale": NATIVE_SCALE,
                "preprocess": [
                    "PIL_DECODE",
                    "EXPLICIT_RGB_CONVERSION",
                    "FLOAT32_ZERO_TO_ONE_BY_OFFICIAL_PROCESSOR",
                    "SYMMETRIC_WINDOW_PADDING_BY_OFFICIAL_PROCESSOR",
                ],
                "postprocess": [
                    "CLAMP_ZERO_TO_ONE",
                    "UINT8_ROUND",
                    "CONTEXT_TILE_CORE_CROP",
                    "EXPLICIT_LANCZOS_TO_BASELINE_GEOMETRY",
                    "BASELINE_ALPHA_DERIVED_FROM_SOURCE_REATTACH",
                    "BASELINE_ICC_PRESERVE",
                    "LOSSLESS_PNG",
                ],
                "alpha_strategy": (
                    "BASELINE_ALPHA_DERIVED_FROM_SOURCE_REATTACHED"
                    if baseline_alpha is not None
                    else "NO_ALPHA_PRESENT"
                ),
                "color_profile_strategy": "PRESERVE_BASELINE_ICC",
            },
        )


def build_swin2sr_definition(
    model_path: str | Path,
    *,
    revision: str,
    tile_core: int = 224,
    tile_context: int = 16,
) -> CandidateDefinition:
    model = Path(model_path).expanduser().resolve()
    return CandidateDefinition(
        algorithm_id="SWIN2SR_REALWORLD_X4_BSRGAN_PSNR",
        algorithm_version=ADAPTER_VERSION,
        parameters={
            "native_scale": NATIVE_SCALE,
            "tile_core": tile_core,
            "tile_context": tile_context,
            "tile_policy": "CONTEXT_EXPAND_THEN_CORE_CROP_NO_BLEND",
            "input_color": "RGB",
            "input_range": "FLOAT32_ZERO_TO_ONE",
            "window_padding": "OFFICIAL_PROCESSOR_SYMMETRIC",
            "output_quantization": "CLAMP_ROUND_UINT8",
            "final_geometry": "EXPLICIT_PILLOW_LANCZOS_TO_BASELINE_DIMENSIONS",
            "alpha_policy": "REATTACH_BASELINE_ALPHA_DERIVED_FROM_SOURCE",
            "icc_policy": "PRESERVE_BASELINE_ICC",
            "face_enhancement": False,
            "tta": False,
        },
        backend_identity="PYTORCH_2_6_CPU_TRANSFORMERS_4_49_RESEARCH_RUNTIME",
        precision_identity="FP32",
        candidate_class=PRODUCT,
        model_id=MODEL_ID,
        model_version=f"huggingface_revision_{revision}",
        model_sha256=sha256_file(model),
        normalization={
            "version": "CANDIDATE_NORMALIZATION_DECLARATION_V1",
            "operations": [
                "RGB_CONVERSION",
                "ZERO_TO_ONE",
                "SYMMETRIC_WINDOW_PADDING",
                "X4_INFERENCE",
                "CONTEXT_CORE_CROP",
                "LANCZOS_TO_BASELINE_GEOMETRY",
                "ALPHA_REATTACH",
                "ICC_PRESERVE",
            ],
            "implicit_resize": False,
            "implicit_crop_or_padding": False,
            "implicit_color_conversion": False,
        },
        color_profile_policy="PRESERVE_BASELINE_PROFILE",
        control_fixture_only=False,
    )


__all__ = [
    "ADAPTER_VERSION",
    "MODEL_ID",
    "NATIVE_SCALE",
    "Swin2SRCandidateAdapter",
    "build_swin2sr_definition",
]
