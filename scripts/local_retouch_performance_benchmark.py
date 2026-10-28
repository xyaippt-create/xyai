from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path

import cv2 as cv
import numpy as np

from engine.local_retouch.lama_adapter import LamaOnnxAdapter, _write_png


REPO = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLES = (
    ("1080p", REPO / "output/a61_20260914/inputs/photo_1080.jpg"),
    (
        "3k_4k",
        REPO
        / "artifacts/e4k_03_candidates/candidate_a7e8332b2a88abb11d6c0bd0aa06e3ca2332775853b9c43bef2722b45b8f3d05"
        / "benchmark_runs/run_16536247e5eb99c9f85d0a7ec46c3c4e57fc73701757e89df577327fd9de60f2"
        / "isolated_inputs/baseline.png",
    ),
    (
        "12mp",
        REPO
        / "artifacts/e4k_04_bounded_restoration_core_v1/candidate_runs"
        / "run_def378b689d373a9ac8c9b46d81cd0e5761467953d26758aa5b1f1ff221ead86"
        / "isolated_inputs/baseline.png",
    ),
    ("24mp", REPO / "output/a61_20260914/inputs/photo_24mp.jpg"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_dimensions(path: Path) -> tuple[int, int]:
    encoded = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    image = cv.imdecode(encoded, cv.IMREAD_UNCHANGED)
    if image is None:
        raise RuntimeError(f"Cannot decode benchmark source: {path}")
    return int(image.shape[1]), int(image.shape[0])


def make_mask(width: int, height: int, scale: str) -> np.ndarray:
    mask = np.zeros((height, width), dtype=np.uint8)
    if scale == "SMALL_MASK":
        mask_width = min(72, max(24, width // 80))
        mask_height = min(72, max(24, height // 80))
    elif scale == "MEDIUM_MASK":
        mask_width = max(96, round(width * 0.12))
        mask_height = max(96, round(height * 0.12))
    elif scale == "LARGE_MASK":
        mask_width = max(256, round(width * 0.42))
        mask_height = max(256, round(height * 0.36))
    else:
        raise ValueError(scale)
    left = max(0, (width - mask_width) // 2)
    top = max(0, (height - mask_height) // 2)
    cv.rectangle(mask, (left, top), (left + mask_width - 1, top + mask_height - 1), 255, -1)
    return mask


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--sample-id", action="append", dest="sample_ids")
    parser.add_argument("--mask-scale", action="append", dest="mask_scales")
    args = parser.parse_args()

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    records: list[dict[str, object]] = []
    for sample_id, source_path in DEFAULT_SAMPLES:
        if args.sample_ids and sample_id not in args.sample_ids:
            continue
        source_path = source_path.resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        width, height = read_dimensions(source_path)
        source_hash = sha256(source_path)
        requested_scales = args.mask_scales or ("SMALL_MASK", "MEDIUM_MASK", "LARGE_MASK")
        for mask_scale in requested_scales:
            case_root = output_root / sample_id / mask_scale.lower()
            case_root.mkdir(parents=True, exist_ok=False)
            mask_path = case_root / "mask.png"
            _write_png(mask_path, make_mask(width, height, mask_scale))
            adapter = LamaOnnxAdapter()
            for run_index, temperature in enumerate(("COLD", "WARM_1", "WARM_2")):
                output_path = case_root / f"{temperature.lower()}.png"
                wall_started = time.perf_counter()
                result = adapter.process(source_path, mask_path, output_path)
                wall_ms = (time.perf_counter() - wall_started) * 1000.0
                if sha256(source_path) != source_hash:
                    raise RuntimeError(f"Benchmark source changed: {source_path}")
                timings = adapter.last_timings_ms
                record = {
                    "label": args.label,
                    "sample_id": sample_id,
                    "source_path": str(source_path),
                    "source_sha256": source_hash,
                    "dimensions": [width, height],
                    "megapixels": round(width * height / 1_000_000.0, 3),
                    "mask_scale": mask_scale,
                    "mask_pixels": result.mask_pixels,
                    "temperature": temperature,
                    "run_index": run_index,
                    "wall_ms": round(wall_ms, 3),
                    "output_path": str(output_path),
                    "output_sha256": sha256(output_path),
                    "timings_ms": timings,
                }
                records.append(record)
                print(json.dumps(record, ensure_ascii=False), flush=True)

    summaries: dict[str, dict[str, float]] = {}
    for mask_scale in sorted({str(record["mask_scale"]) for record in records}):
        values = [
            float(record["timings_ms"]["TOTAL_MS"])
            for record in records
            if record["mask_scale"] == mask_scale
        ]
        summaries[mask_scale] = {
            "P50_TOTAL_MS": round(statistics.median(values), 3),
            "P90_TOTAL_MS": round(percentile(values, 0.9), 3),
        }
    payload = {"label": args.label, "records": records, "summaries": summaries}
    report_path = output_root / "benchmark.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report_path": str(report_path), "summaries": summaries}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
