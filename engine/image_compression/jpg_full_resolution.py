"""The existing JPEG metrics over every native pixel, with bounded float workspaces.

One-row halos preserve Sobel/Laplacian and JPEG block coordinates at stripe seams.
Exact global quantiles use a private, automatically removed float scratch file;
neither thumbnails nor ROI measurements can approve a full-size candidate.
"""
from __future__ import annotations

import math
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

STRIPE_ROWS = 128


def _percentile_hist(histogram: np.ndarray, percentile: float) -> float:
    count = int(histogram.sum())
    if not count:
        return 0.0
    position = (count - 1) * percentile / 100.0
    lower, upper = math.floor(position), math.ceil(position)
    cumulative = histogram.cumsum()
    a = int(np.searchsorted(cumulative, lower + 1))
    b = int(np.searchsorted(cumulative, upper + 1))
    return a + (b - a) * (position - lower)


def _luma(image: Image.Image, top: int, bottom: int) -> np.ndarray:
    rgb = np.asarray(image.crop((0, top, image.width, bottom)), dtype=np.uint8)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)


def _gradient(luma: np.ndarray) -> np.ndarray:
    return cv2.magnitude(
        cv2.Sobel(luma, cv2.CV_32F, 1, 0, ksize=3),
        cv2.Sobel(luma, cv2.CV_32F, 0, 1, ksize=3),
    )


class FullResolutionSourceAnalysis:
    """Request-local, read-only Source preprocessing for native JPEG metrics."""

    def __init__(self, source: Image.Image):
        self.size = source.size
        self.width, self.height = source.size
        self.pixels = self.width * self.height
        self._temporary = tempfile.TemporaryDirectory(prefix="hdde-jpg-source-analysis-")
        self._maps: list[np.memmap] = []
        self._closed = False
        try:
            self._build(source)
        except Exception:
            self.close()
            raise

    def _map(self, name: str, dtype, shape) -> np.memmap:
        path = Path(self._temporary.name) / f"{name}.bin"
        mapped = np.memmap(path, mode="w+", dtype=dtype, shape=shape)
        self._maps.append(mapped)
        return mapped

    def _build(self, source: Image.Image) -> None:
        width, height, pixels = self.width, self.height, self.pixels
        self.source_rgb = self._map("rgb", np.uint8, (height, width, 3))
        self.source_luma = self._map("luma", np.float32, (height, width))
        self.source_gradient = self._map("gradient", np.float32, (height, width))
        self.source_lab = self._map("lab", np.float32, (height, width, 3))
        self.source_hf_sum = 0.0

        with tempfile.TemporaryFile(prefix="hdde-jpg-source-percentile-") as scratch:
            values = np.memmap(scratch, mode="w+", dtype=np.float32, shape=(pixels,))
            try:
                for y in range(0, height, STRIPE_ROWS):
                    end = min(height, y + STRIPE_ROWS)
                    top, bottom = max(0, y - 1), min(height, end + 1)
                    core = slice(y - top, end - top)
                    rgb_with_halo = np.asarray(source.crop((0, top, width, bottom)), dtype=np.uint8)
                    source_rgb = rgb_with_halo[core]
                    source_luma = cv2.cvtColor(rgb_with_halo, cv2.COLOR_RGB2GRAY).astype(np.float32)
                    source_gradient = _gradient(source_luma)[core]
                    self.source_rgb[y:end] = source_rgb
                    self.source_luma[y:end] = source_luma[core]
                    self.source_gradient[y:end] = source_gradient
                    self.source_lab[y:end] = cv2.cvtColor(
                        source_rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB,
                    )
                    self.source_hf_sum += float(
                        np.sum(np.abs(cv2.Laplacian(source_luma, cv2.CV_32F)[core]), dtype=np.float64)
                    )
                    values[y * width:end * width] = source_gradient.reshape(-1)
                self.edge_threshold = max(16.0, float(np.percentile(values, 85, overwrite_input=True)))
            finally:
                values._mmap.close()

        self.source_edge_sum = 0.0
        for y in range(0, height, STRIPE_ROWS):
            end = min(height, y + STRIPE_ROWS)
            gradient = self.source_gradient[y:end]
            edge = gradient >= self.edge_threshold
            self.source_edge_sum += float(np.sum(gradient[edge], dtype=np.float64))
        for mapped in self._maps:
            mapped.flush()
            mapped.flags.writeable = False

    def measure(self, candidate: Image.Image) -> dict[str, float]:
        if candidate.size != self.size:
            raise ValueError("Full-resolution metrics require identical dimensions")
        width, height, pixels = self.width, self.height, self.pixels
        rgb_hist = np.zeros(256, dtype=np.int64)
        edge_hist = np.zeros(256, dtype=np.int64)
        smooth_hist = np.zeros(256, dtype=np.int64)
        channel_sum = np.zeros(3, dtype=np.float64)
        squared_error = absolute_error = 0.0
        candidate_edge_sum = candidate_hf_sum = 0.0
        horizontal_sum = vertical_sum = boundary_sum = 0.0
        horizontal_count = vertical_count = boundary_count = 0
        delta_e_sum = 0.0

        with tempfile.TemporaryFile(prefix="hdde-jpg-metrics-") as scratch:
            values = np.memmap(scratch, mode="w+", dtype=np.float32, shape=(pixels,))
            try:
                for y in range(0, height, STRIPE_ROWS):
                    end = min(height, y + STRIPE_ROWS)
                    top, bottom = max(0, y - 1), min(height, end + 1)
                    core = slice(y - top, end - top)
                    candidate_rgb_with_halo = np.asarray(
                        candidate.crop((0, top, width, bottom)), dtype=np.uint8,
                    )
                    candidate_rgb = candidate_rgb_with_halo[core]
                    source_rgb = self.source_rgb[y:end]
                    signed = candidate_rgb.astype(np.float32) - source_rgb.astype(np.float32)
                    absolute = np.abs(signed)
                    squared_error += float(np.sum(signed * signed, dtype=np.float64))
                    absolute_error += float(np.sum(absolute, dtype=np.float64))
                    channel_sum += np.sum(signed, axis=(0, 1), dtype=np.float64)
                    rgb_hist += np.bincount(absolute.astype(np.uint8).ravel(), minlength=256)

                    source_luma = self.source_luma[top:bottom]
                    candidate_luma = cv2.cvtColor(
                        candidate_rgb_with_halo, cv2.COLOR_RGB2GRAY,
                    ).astype(np.float32)
                    source_gradient = self.source_gradient[y:end]
                    candidate_gradient = _gradient(candidate_luma)[core]
                    residual = candidate_luma - source_luma
                    error = np.abs(residual[core]).astype(np.uint8)
                    edge = source_gradient >= self.edge_threshold
                    smooth = source_gradient <= 4.0
                    edge_hist += np.bincount(error[edge], minlength=256)
                    smooth_hist += np.bincount(error[smooth], minlength=256)
                    candidate_edge_sum += float(np.sum(candidate_gradient[edge], dtype=np.float64))
                    candidate_hf_sum += float(
                        np.sum(np.abs(cv2.Laplacian(candidate_luma, cv2.CV_32F)[core]), dtype=np.float64)
                    )

                    horizontal = np.abs(np.diff(residual[core], axis=1))
                    vertical_rows = min(end, height - 1) - y
                    vertical = np.abs(
                        residual[y - top + 1:y - top + 1 + vertical_rows]
                        - residual[y - top:y - top + vertical_rows]
                    )
                    horizontal_sum += float(horizontal.sum(dtype=np.float64))
                    vertical_sum += float(vertical.sum(dtype=np.float64))
                    horizontal_count += horizontal.size
                    vertical_count += vertical.size
                    horizontal_boundary = horizontal[:, 7::8] if width - 1 >= 8 else horizontal[:, :0]
                    vertical_boundary = (
                        vertical[(np.arange(y, y + vertical_rows) % 8) == 7]
                        if height - 1 >= 8 else vertical[:0]
                    )
                    boundary_sum += float(
                        horizontal_boundary.sum(dtype=np.float64) + vertical_boundary.sum(dtype=np.float64)
                    )
                    boundary_count += horizontal_boundary.size + vertical_boundary.size

                    candidate_lab = cv2.cvtColor(
                        candidate_rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB,
                    )
                    delta_e = np.linalg.norm(candidate_lab - self.source_lab[y:end], axis=2)
                    delta_e_sum += float(delta_e.sum(dtype=np.float64))
                    values[y * width:end * width] = delta_e.reshape(-1)
                delta_e_p95 = float(np.percentile(values, 95, overwrite_input=True))
            finally:
                values._mmap.close()

        bins = np.arange(256, dtype=np.float64)
        edges, smooths = int(edge_hist.sum()), int(smooth_hist.sum())
        mse = squared_error / (pixels * 3)
        interior_mean = (
            horizontal_sum / max(horizontal_count, 1) + vertical_sum / max(vertical_count, 1)
        ) / 2.0
        return {
            "analysis_pixel_count": float(pixels),
            "psnr_db": 99.0 if mse == 0 else 10.0 * math.log10(255.0 ** 2 / mse),
            "rgb_mae": absolute_error / (pixels * 3),
            "rgb_p99_error": _percentile_hist(rgb_hist, 99),
            "channel_bias": float(np.max(np.abs(channel_sum / pixels))),
            "delta_e_mean": delta_e_sum / pixels,
            "delta_e_p95": delta_e_p95,
            "edge_mae": float(np.dot(edge_hist, bins) / edges) if edges else 0.0,
            "edge_p95_error": _percentile_hist(edge_hist, 95),
            "edge_retention": candidate_edge_sum / max(self.source_edge_sum, 1.0) if edges else 1.0,
            "high_frequency_retention": (
                (candidate_hf_sum / pixels) / max(self.source_hf_sum / pixels, 1e-6)
            ),
            "smooth_region_mae": float(np.dot(smooth_hist, bins) / smooths) if smooths else 0.0,
            "smooth_region_p99_error": _percentile_hist(smooth_hist, 99),
            "block_boundary_excess": (
                max(0.0, boundary_sum / boundary_count - interior_mean) if boundary_count else 0.0
            ),
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for mapped in self._maps:
            try:
                mapped._mmap.close()
            except Exception:
                pass
        self._maps.clear()
        self._temporary.cleanup()

    def __enter__(self) -> "FullResolutionSourceAnalysis":
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()


def full_resolution_metrics(
    source: Image.Image,
    candidate: Image.Image,
    *,
    source_analysis: FullResolutionSourceAnalysis | None = None,
) -> dict[str, float]:
    if source.size != candidate.size:
        raise ValueError("Full-resolution metrics require identical dimensions")
    if source_analysis is not None:
        if source_analysis.size != source.size:
            raise ValueError("Source analysis does not match the source dimensions")
        return source_analysis.measure(candidate)
    with FullResolutionSourceAnalysis(source) as prepared:
        return prepared.measure(candidate)
