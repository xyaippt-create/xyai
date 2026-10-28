"""Native-resolution ROI hints for large JPEG search; never a delivery gate."""
from __future__ import annotations

import io
import time
from contextlib import ExitStack
from typing import Any

import cv2
import numpy as np
from PIL import Image

from .jpg_quality_gate import _metric_checks, measure_jpg_pixels, prepare_jpg_source_analysis

ROI_SIDE = 256
REPRESENTATIVE_GRID = 8
COARSE_QUALITIES = (96, 92, 88, 84, 80, 76, 72, 64, 56, 48, 40, 32, 24, 16, 8, 1)


def native_source_hf_mean(image: Image.Image) -> float:
    """Exact Source-only energy anchor; no JPEG encode and no resized pixels."""
    total = 0.0
    for y in range(0, image.height, 128):
        end = min(image.height, y + 128)
        top, bottom = max(0, y - 1), min(image.height, end + 1)
        rgb = np.asarray(image.crop((0, top, image.width, bottom)))
        luma = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
        core = cv2.Laplacian(luma, cv2.CV_32F)[y - top:end - top]
        total += float(np.sum(np.abs(core), dtype=np.float64))
    return total / (image.width * image.height)


def select_native_rois(image: Image.Image) -> list[dict[str, Any]]:
    """Scan native pixels, retaining high-risk and representative regions.

    Origins are MCU-aligned for both 4:4:4 and 4:2:0. No resize is used in
    selection or measurement; the role names are signal heuristics, not OCR.
    """
    rgb = image.convert("RGB")
    width, height = rgb.size
    tiles = []
    # Bounded scan count with native 256-pixel windows, including each border.
    xs = sorted({min(max(0, width - ROI_SIDE) // 16 * 16, x // 16 * 16)
                 for x in np.linspace(0, max(0, width - ROI_SIDE), min(12, max(1, width // ROI_SIDE)), dtype=int)})
    ys = sorted({min(max(0, height - ROI_SIDE) // 16 * 16, y // 16 * 16)
                 for y in np.linspace(0, max(0, height - ROI_SIDE), min(12, max(1, height // ROI_SIDE)), dtype=int)})
    for y in ys:
        for x in xs:
            box = (int(x), int(y), int(min(width, x + ROI_SIDE)), int(min(height, y + ROI_SIDE)))
            crop = rgb.crop(box)
            array = np.asarray(crop, dtype=np.uint8)
            gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY).astype(np.float32)
            gradient = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))
            smooth = float(np.mean(gradient <= 4))
            edge = float(np.mean(gradient >= 40))
            texture = float(np.mean(np.abs(cv2.Laplacian(gray, cv2.CV_32F))))
            spread = float(np.std(gray))
            chroma = array.astype(np.float32).max(axis=2) - array.astype(np.float32).min(axis=2)
            color_edge = float(np.mean(np.abs(np.diff(chroma, axis=1))))
            tiles.append({"box": box, "image": crop, "scores": {
                "text_fine_line": edge * (smooth + 0.1),
                "high_frequency": texture,
                "gradient": smooth * min(spread, 32.0),
                "photo": spread / (1.0 + abs(edge - 0.15) * 5),
                "color_edge": color_edge,
            }})
    selected = []
    used = set()
    for role in ("text_fine_line", "high_frequency", "gradient", "photo", "color_edge"):
        remaining = [tile for tile in tiles if tile["box"] not in used]
        if not remaining:
            break
        tile = max(remaining, key=lambda item: item["scores"][role])
        used.add(tile["box"])
        selected.append({"role": role, "box": tile["box"], "image": tile["image"]})
    return selected


def plan_large_jpg_search(image: Image.Image, subsampling_order: tuple[int, ...]):
    started = time.perf_counter()
    rois = select_native_rois(image)
    # Risk maxima alone over-represent strong contours and miss the widely
    # distributed low-amplitude grain in photos. Add a bounded uniform native
    # grid; these 128-pixel crops are never resized. Pool their Laplacian energy,
    # not the unweighted mean of per-crop retention ratios.
    rgb = image.convert("RGB")
    source_hf = native_source_hf_mean(rgb)
    side = min(128, rgb.width, rgb.height)
    for row in range(REPRESENTATIVE_GRID):
        for column in range(REPRESENTATIVE_GRID):
            x = max(0, min(rgb.width - side, int((column + 0.5) * rgb.width / REPRESENTATIVE_GRID - side / 2))) // 16 * 16
            y = max(0, min(rgb.height - side, int((row + 0.5) * rgb.height / REPRESENTATIVE_GRID - side / 2))) // 16 * 16
            crop = rgb.crop((x, y, x + side, y + side))
            luma = cv2.cvtColor(np.asarray(crop), cv2.COLOR_RGB2GRAY).astype(np.float32)
            rois.append({"role": "representative", "box": (x, y, x + side, y + side), "image": crop,
                         "source_hf_energy": float(np.mean(np.abs(cv2.Laplacian(luma, cv2.CV_32F))))})
    trials: list[dict[str, Any]] = []
    plans = []
    with ExitStack() as source_analyses:
        for roi in rois:
            if roi["role"] != "representative":
                roi["source_analysis"] = source_analyses.enter_context(
                    prepare_jpg_source_analysis(roi["image"]),
                )
        for mode in subsampling_order:
            cache: dict[int, dict[str, Any]] = {}

            def probe(quality: int):
                if quality in cache:
                    return cache[quality]
                began = time.perf_counter()
                measured = []
                added_energies = []
                encoded_size = 0
                for roi in rois:
                    # Huffman optimization changes bytes, not decoded pixels. It is
                    # unnecessary for ROI quality hints and can exhaust Pillow's
                    # optimize buffer on tiny high-entropy Q100 crops. Full-size
                    # candidates retain the original optimize=True encoder.
                    stream = io.BytesIO()
                    roi["image"].save(stream, format="JPEG", quality=quality, subsampling=mode,
                                      optimize=False, progressive=False)
                    encoded_size += stream.tell()
                    data = stream.getvalue()
                    with Image.open(io.BytesIO(data)) as decoded:
                        decoded.load()
                        candidate = decoded.convert("RGB")
                        if roi["role"] == "representative":
                            luma = cv2.cvtColor(np.asarray(candidate), cv2.COLOR_RGB2GRAY).astype(np.float32)
                            energy = float(np.mean(np.abs(cv2.Laplacian(luma, cv2.CV_32F))))
                            added_energies.append(energy - roi["source_hf_energy"])
                        else:
                            measured.append(measure_jpg_pixels(
                                roi["image"],
                                candidate,
                                _source_analysis=roi["source_analysis"],
                            ))
                # A prediction only: pooled native ROI metrics locate the likely
                # interval. Every persisted full-size candidate is independently gated.
                metrics = {key: float(np.mean([item[key] for item in measured])) for key in measured[0]}
                # Sampling can bias Source energy (especially smooth upscaled
                # photos). Estimate the JPEG-added energy per native pixel, anchored
                # to the exact whole-Source denominator used by the real gate.
                added_hf = float(np.mean(added_energies))
                metrics["high_frequency_retention"] = max(0.0, source_hf + added_hf) / max(source_hf, 1e-6)
                checks = _metric_checks(metrics)
                # A sampling-uncertainty guard for search only. Native crops are not
                # independent evidence of whole-image acceptance; leave two standard
                # errors of room before spending a full encode at a fragile boundary.
                uncertainty = 2.0 * float(np.std(added_energies, ddof=1)) / len(added_energies) ** 0.5
                hf_interval = [max(0.0, source_hf + added_hf + sign * uncertainty) / max(source_hf, 1e-6)
                               for sign in (-1, 1)]
                checks["high_frequency_detail"] = all(
                    _metric_checks({**metrics, "high_frequency_retention": bound})["high_frequency_detail"]
                    for bound in hf_interval
                )
                record = {"quality": quality, "subsampling": "4:4:4" if mode == 0 else "4:2:0",
                          "safe_hint": all(checks.values()), "failed_hints": [key for key, value in checks.items() if not value],
                          "hf_retention_hint": metrics["high_frequency_retention"],
                          "hf_retention_interval": hf_interval,
                          "roi_encoded_bytes": encoded_size, "elapsed_seconds": round(time.perf_counter() - began, 6)}
                trials.append(record)
                cache[quality] = record
                return record

            passing, failing = None, None
            for quality in COARSE_QUALITIES:
                result = probe(quality)
                if result["safe_hint"]:
                    passing = quality
                else:
                    failing = quality
                    if passing is None:
                        # The previous fixed search never reached Q99/Q100.
                        for high in (98, 100):
                            if probe(high)["safe_hint"]:
                                passing = high
                                break
                    break
            if passing is not None and failing is not None:
                low, high = failing + 1, passing - 1
                while low <= high:
                    quality = (low + high) // 2
                    if probe(quality)["safe_hint"]:
                        passing, high = quality, quality - 1
                    else:
                        failing, low = quality, quality + 1
            plans.append({"subsampling": mode, "quality": passing if passing is not None else 100,
                          "roi_last_pass": passing, "roi_first_fail": failing})
    return plans, {
        "native_resolution": True, "resized": False, "accepts_delivery": False,
        "representative_grid": [REPRESENTATIVE_GRID, REPRESENTATIVE_GRID],
        "hf_pooling": "SAMPLED_ADDED_ENERGY_WITH_EXACT_NATIVE_SOURCE_ANCHOR",
        "native_source_hf_mean": source_hf,
        "regions": [{"role": roi["role"], "box": list(roi["box"])} for roi in rois],
        "probe_count": len(trials), "roi_encode_count": len(trials) * len(rois), "trials": trials,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
    }
