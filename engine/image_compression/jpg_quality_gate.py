from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np
from PIL import Image, ImageOps


JPG_QUALITY_GATE_VERSION = "JPG_DELIVERY_QUALITY_V1"
MAX_ANALYSIS_PIXELS = 4_000_000

_METADATA_GATES = (
    "written",
    "decoded_pixel_content_unchanged",
    "alpha_unchanged",
    "icc_unchanged",
    "dpi_unchanged",
    "orientation_preserved",
    "title_preserved",
    "author_preserved",
    "source_metadata_preserved",
)

_THRESHOLDS = {
    "psnr_min_db": 36.0,
    "rgb_mae_max": 3.0,
    "rgb_p99_error_max": 14.0,
    "channel_bias_max": 1.0,
    "delta_e_mean_max": 2.5,
    "delta_e_p95_max": 6.0,
    "edge_mae_max": 4.0,
    "edge_p95_error_max": 12.0,
    "edge_retention_min": 0.97,
    "edge_retention_max": 1.03,
    "high_frequency_retention_min": 0.88,
    "high_frequency_retention_max": 1.12,
    "smooth_region_mae_max": 2.0,
    "smooth_region_p99_error_max": 8.0,
    "block_boundary_excess_max": 1.0,
}


def _round(value: float) -> float:
    return round(float(value), 6)


def _metadata_passes(report: Mapping[str, Any]) -> bool:
    return bool(
        all(report.get(key) is True for key in _METADATA_GATES)
        and int(report.get("iptc_controlled_conflicts", -1)) == 0
        and int(report.get("xmp_controlled_conflicts", -1)) == 0
    )


def _block_boundary_excess(residual: np.ndarray) -> float:
    horizontal = np.abs(np.diff(residual, axis=1))
    vertical = np.abs(np.diff(residual, axis=0))
    boundary_parts: list[np.ndarray] = []
    if horizontal.shape[1] >= 8:
        boundary_parts.append(horizontal[:, 7::8].reshape(-1))
    if vertical.shape[0] >= 8:
        boundary_parts.append(vertical[7::8, :].reshape(-1))
    if not boundary_parts:
        return 0.0
    boundary_mean = float(np.mean(np.concatenate(boundary_parts)))
    interior_mean = float((np.mean(horizontal) + np.mean(vertical)) / 2.0)
    return max(0.0, boundary_mean - interior_mean)


def _metric_checks(metrics: Mapping[str, float]) -> dict[str, bool]:
    return {
        "global_fidelity": (
            metrics["psnr_db"] >= _THRESHOLDS["psnr_min_db"]
            and metrics["rgb_mae"] <= _THRESHOLDS["rgb_mae_max"]
            and metrics["rgb_p99_error"] <= _THRESHOLDS["rgb_p99_error_max"]
        ),
        "color_drift": (
            metrics["channel_bias"] <= _THRESHOLDS["channel_bias_max"]
            and metrics["delta_e_mean"] <= _THRESHOLDS["delta_e_mean_max"]
            and metrics["delta_e_p95"] <= _THRESHOLDS["delta_e_p95_max"]
        ),
        "compression_blocks": metrics["block_boundary_excess"] <= _THRESHOLDS["block_boundary_excess_max"],
        "edge_ringing": (
            metrics["edge_mae"] <= _THRESHOLDS["edge_mae_max"]
            and metrics["edge_p95_error"] <= _THRESHOLDS["edge_p95_error_max"]
        ),
        "high_frequency_detail": (
            _THRESHOLDS["edge_retention_min"] <= metrics["edge_retention"] <= _THRESHOLDS["edge_retention_max"]
            and _THRESHOLDS["high_frequency_retention_min"]
            <= metrics["high_frequency_retention"]
            <= _THRESHOLDS["high_frequency_retention_max"]
        ),
        "text_and_fine_lines": (
            metrics["edge_mae"] <= _THRESHOLDS["edge_mae_max"]
            and metrics["edge_p95_error"] <= _THRESHOLDS["edge_p95_error_max"]
            and metrics["edge_retention"] >= _THRESHOLDS["edge_retention_min"]
        ),
        "gradient_banding": (
            metrics["smooth_region_mae"] <= _THRESHOLDS["smooth_region_mae_max"]
            and metrics["smooth_region_p99_error"] <= _THRESHOLDS["smooth_region_p99_error_max"]
        ),
    }


class _BoundedSourceAnalysis:
    """Read-only Source terms shared by candidates within one request."""

    def __init__(self, source_image: Image.Image):
        self.size = source_image.size
        self.source_rgb = np.asarray(source_image, dtype=np.uint8)
        self.source_luma = cv2.cvtColor(self.source_rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
        self.source_gradient = cv2.magnitude(
            cv2.Sobel(self.source_luma, cv2.CV_32F, 1, 0, ksize=3),
            cv2.Sobel(self.source_luma, cv2.CV_32F, 0, 1, ksize=3),
        )
        self.edge_threshold = max(16.0, float(np.percentile(self.source_gradient, 85)))
        self.edge_mask = self.source_gradient >= self.edge_threshold
        self.smooth_mask = self.source_gradient <= 4.0
        self.source_laplacian = cv2.Laplacian(self.source_luma, cv2.CV_32F)
        self.source_lab = cv2.cvtColor(
            self.source_rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB,
        )
        for value in (
            self.source_rgb, self.source_luma, self.source_gradient, self.edge_mask,
            self.smooth_mask, self.source_laplacian, self.source_lab,
        ):
            value.flags.writeable = False

    def measure(self, candidate_image: Image.Image) -> dict[str, float]:
        if candidate_image.size != self.size:
            raise ValueError("JPEG metrics require identical dimensions")
        candidate_rgb = np.asarray(candidate_image, dtype=np.uint8)
        signed_delta = candidate_rgb.astype(np.float32) - self.source_rgb.astype(np.float32)
        absolute_delta = np.abs(signed_delta)
        mse = float(np.mean(signed_delta * signed_delta))
        rgb_mae = float(np.mean(absolute_delta))
        rgb_p99_error = float(np.percentile(absolute_delta, 99))
        channel_bias = float(np.max(np.abs(np.mean(signed_delta, axis=(0, 1)))))
        del signed_delta, absolute_delta

        candidate_luma = cv2.cvtColor(candidate_rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
        luma_error = np.abs(candidate_luma - self.source_luma)
        candidate_gradient = cv2.magnitude(
            cv2.Sobel(candidate_luma, cv2.CV_32F, 1, 0, ksize=3),
            cv2.Sobel(candidate_luma, cv2.CV_32F, 0, 1, ksize=3),
        )
        candidate_laplacian = cv2.Laplacian(candidate_luma, cv2.CV_32F)
        edge_mae = float(np.mean(luma_error[self.edge_mask])) if np.any(self.edge_mask) else 0.0
        edge_p95_error = (
            float(np.percentile(luma_error[self.edge_mask], 95)) if np.any(self.edge_mask) else 0.0
        )
        edge_retention = (
            float(
                np.sum(candidate_gradient[self.edge_mask])
                / max(float(np.sum(self.source_gradient[self.edge_mask])), 1.0)
            )
            if np.any(self.edge_mask) else 1.0
        )
        high_frequency_retention = float(
            np.mean(np.abs(candidate_laplacian))
            / max(float(np.mean(np.abs(self.source_laplacian))), 1e-6)
        )
        smooth_region_mae = (
            float(np.mean(luma_error[self.smooth_mask])) if np.any(self.smooth_mask) else 0.0
        )
        smooth_region_p99_error = (
            float(np.percentile(luma_error[self.smooth_mask], 99)) if np.any(self.smooth_mask) else 0.0
        )
        block_boundary_excess = _block_boundary_excess(candidate_luma - self.source_luma)

        candidate_lab = cv2.cvtColor(
            candidate_rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB,
        )
        delta_e = np.linalg.norm(candidate_lab - self.source_lab, axis=2)
        return {
            "analysis_pixel_count": float(self.size[0] * self.size[1]),
            "psnr_db": 99.0 if mse == 0 else 10.0 * math.log10((255.0 * 255.0) / mse),
            "rgb_mae": rgb_mae,
            "rgb_p99_error": rgb_p99_error,
            "channel_bias": channel_bias,
            "delta_e_mean": float(np.mean(delta_e)),
            "delta_e_p95": float(np.percentile(delta_e, 95)),
            "edge_mae": edge_mae,
            "edge_p95_error": edge_p95_error,
            "edge_retention": edge_retention,
            "high_frequency_retention": high_frequency_retention,
            "smooth_region_mae": smooth_region_mae,
            "smooth_region_p99_error": smooth_region_p99_error,
            "block_boundary_excess": block_boundary_excess,
        }

    def close(self) -> None:
        return None

    def __enter__(self) -> "_BoundedSourceAnalysis":
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()


def prepare_jpg_source_analysis(
    source_image: Image.Image, *, full_resolution: bool = False,
):
    pixel_count = source_image.width * source_image.height
    if pixel_count > MAX_ANALYSIS_PIXELS:
        if not full_resolution:
            raise ValueError("ANALYSIS_PIXEL_LIMIT_EXCEEDED")
        from .jpg_full_resolution import FullResolutionSourceAnalysis

        return FullResolutionSourceAnalysis(source_image)
    return _BoundedSourceAnalysis(source_image)


def evaluate_jpg_quality(
    source_path: str | Path,
    candidate_path: str | Path,
    *,
    metadata_report: Mapping[str, Any],
    source_has_real_transparency: bool,
    full_resolution: bool = False,
    _decoded_source: Image.Image | None = None,
    _source_analysis: Any | None = None,
) -> dict[str, Any]:
    """Evaluate a persisted JPEG with multiple explainable, fail-closed checks."""

    source_file = Path(source_path).resolve()
    candidate_file = Path(candidate_path).resolve()
    checks: dict[str, bool] = {
        "alpha_applicable": not source_has_real_transparency,
        "decodable": False,
        "format": False,
        "resolution": False,
        "metadata_contract": _metadata_passes(metadata_report),
        "analysis_bound": False,
    }
    metrics: dict[str, float] = {}
    failures: list[str] = []

    if source_has_real_transparency:
        failures.append("SOURCE_HAS_REAL_TRANSPARENCY")
    try:
        if _decoded_source is None:
            with Image.open(source_file) as source_opened:
                source_opened.load()
                source_image = ImageOps.exif_transpose(source_opened).convert("RGB")
        else:
            # Internal search reuses the RGB image decoded from its immutable
            # Source snapshot. Formal publication still reopens both files.
            source_image = _decoded_source
        with Image.open(candidate_file) as candidate_opened:
            candidate_opened.load()
            checks["decodable"] = True
            checks["format"] = str(candidate_opened.format or "").upper() in {"JPEG", "JPG"}
            checks["resolution"] = candidate_opened.size == source_image.size
            candidate_image = candidate_opened.convert("RGB")
    except Exception as exc:
        failures.append(f"DECODE_FAILED:{exc.__class__.__name__}")
        return {
            "version": JPG_QUALITY_GATE_VERSION,
            "status": "FAIL",
            "checks": checks,
            "metrics": metrics,
            "thresholds": dict(_THRESHOLDS),
            "failure_reasons": failures,
        }

    pixel_count = int(source_image.width * source_image.height)
    checks["analysis_bound"] = pixel_count <= MAX_ANALYSIS_PIXELS or full_resolution
    if not checks["analysis_bound"]:
        failures.append("ANALYSIS_PIXEL_LIMIT_EXCEEDED")
    if not checks["format"]:
        failures.append("OUTPUT_FORMAT_INVALID")
    if not checks["resolution"]:
        failures.append("RESOLUTION_CHANGED")
    if not checks["metadata_contract"]:
        failures.append("METADATA_CONTRACT_FAILED")
    if failures:
        return {
            "version": JPG_QUALITY_GATE_VERSION,
            "status": "FAIL",
            "checks": checks,
            "metrics": metrics,
            "thresholds": dict(_THRESHOLDS),
            "failure_reasons": failures,
        }

    metrics = measure_jpg_pixels(
        source_image,
        candidate_image,
        full_resolution=full_resolution,
        _source_analysis=_source_analysis,
    )
    checks.update(_metric_checks(metrics))
    failures.extend(key.upper() for key, passed in checks.items() if not passed)
    return {
        "version": JPG_QUALITY_GATE_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "metrics": metrics,
        "thresholds": dict(_THRESHOLDS),
        "failure_reasons": failures,
    }


def measure_jpg_pixels(
    source_image: Image.Image,
    candidate_image: Image.Image,
    *,
    full_resolution: bool = False,
    _source_analysis: Any | None = None,
) -> dict[str, float]:
    """Pixel metrics only; ROI callers cannot claim metadata or artifact acceptance."""
    pixel_count = source_image.width * source_image.height
    if source_image.size != candidate_image.size:
        raise ValueError("JPEG metrics require identical dimensions")
    if _source_analysis is not None:
        if getattr(_source_analysis, "size", None) != source_image.size:
            raise ValueError("Source analysis does not match the source dimensions")
        metrics = _source_analysis.measure(candidate_image)
    else:
        with prepare_jpg_source_analysis(source_image, full_resolution=full_resolution) as prepared:
            metrics = prepared.measure(candidate_image)
    return {key: _round(value) for key, value in metrics.items()}


__all__ = [
    "JPG_QUALITY_GATE_VERSION",
    "MAX_ANALYSIS_PIXELS",
    "evaluate_jpg_quality",
    "prepare_jpg_source_analysis",
]
