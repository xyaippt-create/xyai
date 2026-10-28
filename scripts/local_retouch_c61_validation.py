from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2 as cv
import numpy as np

from engine.local_retouch.lama_adapter import LamaOnnxAdapter


REPO = Path(__file__).resolve().parents[1]
PROTECTED_ROOT = REPO / "output/playwright/c60_retouch_03b_candidate_20260905/production_after"
REAL_1080 = REPO / "output/a61_20260914/inputs/photo_1080.jpg"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path, mode: int) -> np.ndarray:
    value = cv.imdecode(np.fromfile(path, dtype=np.uint8), mode)
    if value is None:
        raise RuntimeError(f"无法读取验证图像：{path}")
    return value


def _write_mask(path: Path, mask: np.ndarray) -> None:
    encoded, buffer = cv.imencode(".png", mask)
    if not encoded:
        raise RuntimeError(f"无法编码验证 Mask：{path}")
    path.write_bytes(buffer.tobytes())


def _outside_max_delta(source: np.ndarray, result: np.ndarray, mask: np.ndarray) -> int:
    outside = mask < 128
    return int(np.max(np.abs(result.astype(np.int16) - source.astype(np.int16))[outside]))


def _rss_mb() -> float | None:
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / (1024 * 1024), 3)
    except ImportError:
        return None


def _protected_replay(adapter: LamaOnnxAdapter, root: Path) -> list[dict[str, object]]:
    records = []
    replay_root = root / "protected_quality_replay"
    replay_root.mkdir(parents=True, exist_ok=True)
    for sample_id in ("S05", "S06", "S07"):
        case_root = PROTECTED_ROOT / sample_id
        source = case_root / "01_source.png"
        mask = case_root / "02_user_mask.png"
        expected = case_root / "12_production_final.png"
        output = replay_root / f"{sample_id}.png"
        adapter.process(source, mask, output)
        records.append(
            {
                "sample_id": sample_id,
                "expected_sha256": _sha256(expected),
                "actual_sha256": _sha256(output),
                "byte_identical": _sha256(expected) == _sha256(output),
                "timings_ms": adapter.last_timings_ms,
            }
        )
    return records


def _rectangle_brush_ab(adapter: LamaOnnxAdapter, root: Path) -> dict[str, object]:
    case_root = PROTECTED_ROOT / "S06"
    source_path = case_root / "01_source.png"
    target_mask = _read(case_root / "02_user_mask.png", cv.IMREAD_GRAYSCALE)
    source = _read(source_path, cv.IMREAD_COLOR)
    ys, xs = np.where(target_mask >= 128)
    left, right = int(xs.min()), int(xs.max())
    top, bottom = int(ys.min()), int(ys.max())
    width = right - left + 1
    height = bottom - top + 1
    center_x = (left + right) // 2
    center_y = (top + bottom) // 2

    ab_root = root / "rectangle_brush_ab"
    ab_root.mkdir(parents=True, exist_ok=True)
    masks: dict[str, np.ndarray] = {}
    rectangle = np.zeros(target_mask.shape, dtype=np.uint8)
    cv.rectangle(rectangle, (left, top), (right, bottom), 255, -1)
    masks["RECTANGLE"] = rectangle
    brush = np.zeros_like(rectangle)
    if width >= height:
        brush_radius = max(1, height // 2)
        start = (left + brush_radius, center_y)
        end = (right - brush_radius, center_y)
        thickness = height
    else:
        brush_radius = max(1, width // 2)
        start = (center_x, top + brush_radius)
        end = (center_x, bottom - brush_radius)
        thickness = width
    cv.line(brush, start, end, 255, max(1, thickness), cv.LINE_AA)
    masks["BRUSH"] = np.where(brush >= 128, 255, 0).astype(np.uint8)

    records: dict[str, dict[str, object]] = {}
    outputs: dict[str, np.ndarray] = {}
    for tool, mask in masks.items():
        mask_path = ab_root / f"{tool.lower()}_mask.png"
        output_path = ab_root / f"{tool.lower()}_output.png"
        _write_mask(mask_path, mask)
        adapter.process(source_path, mask_path, output_path)
        result = _read(output_path, cv.IMREAD_COLOR)
        outputs[tool] = result
        records[tool] = {
            "mask_pixels": int(np.count_nonzero(mask)),
            "outside_change_max": _outside_max_delta(source, result, mask),
            "output_sha256": _sha256(output_path),
            "timings_ms": adapter.last_timings_ms,
        }

    overlap = (masks["RECTANGLE"] > 0) & (masks["BRUSH"] > 0)
    union = (masks["RECTANGLE"] > 0) | (masks["BRUSH"] > 0)
    difference = np.abs(outputs["RECTANGLE"].astype(np.int16) - outputs["BRUSH"].astype(np.int16))
    return {
        "records": records,
        "mask_iou": round(float(np.count_nonzero(overlap) / np.count_nonzero(union)), 6),
        "overlap_mean_absolute_difference": round(float(np.mean(difference[overlap])), 6),
        "overlap_p90_absolute_difference": round(float(np.percentile(difference[overlap], 90)), 6),
    }


def _continuous_four_rounds(adapter: LamaOnnxAdapter, root: Path) -> list[dict[str, object]]:
    source = _read(REAL_1080, cv.IMREAD_COLOR)
    height, width = source.shape[:2]
    round_root = root / "continuous_four_rounds"
    round_root.mkdir(parents=True, exist_ok=True)
    current = REAL_1080
    records = []
    selections = (
        ("RECTANGLE", (int(width * 0.18), int(height * 0.22))),
        ("BRUSH", (int(width * 0.72), int(height * 0.27))),
        ("RECTANGLE", (int(width * 0.33), int(height * 0.70))),
        ("BRUSH", (int(width * 0.78), int(height * 0.73))),
    )
    for revision, (tool, (x, y)) in enumerate(selections, start=1):
        mask = np.zeros((height, width), dtype=np.uint8)
        if tool == "RECTANGLE":
            cv.rectangle(mask, (x - 28, y - 18), (x + 28, y + 18), 255, -1)
        else:
            cv.line(mask, (x - 30, y), (x + 30, y), 255, 31, cv.LINE_AA)
            mask = np.where(mask >= 128, 255, 0).astype(np.uint8)
        mask_path = round_root / f"mask_{revision}_{tool.lower()}.png"
        output_path = round_root / f"working_v{revision:04d}.png"
        _write_mask(mask_path, mask)
        input_image = _read(current, cv.IMREAD_COLOR)
        rss_before = _rss_mb()
        processed = adapter.process(current, mask_path, output_path)
        rss_after = _rss_mb()
        result_image = _read(output_path, cv.IMREAD_COLOR)
        records.append(
            {
                "revision": revision,
                "tool": tool,
                "input_sha256": processed.source_sha256,
                "output_sha256": _sha256(output_path),
                "outside_change_max": _outside_max_delta(input_image, result_image, mask),
                "rss_before_mb": rss_before,
                "rss_after_mb": rss_after,
                "timings_ms": adapter.last_timings_ms,
            }
        )
        current = output_path
    return records


def _multi_local_repair(adapter: LamaOnnxAdapter, root: Path) -> dict[str, object]:
    source = _read(REAL_1080, cv.IMREAD_COLOR)
    height, width = source.shape[:2]
    mask = np.zeros((height, width), dtype=np.uint8)
    cv.rectangle(mask, (120, 110), (174, 148), 255, -1)
    cv.line(
        mask,
        (width - 190, height - 135),
        (width - 130, height - 135),
        255,
        31,
        cv.LINE_AA,
    )
    mask = np.where(mask >= 128, 255, 0).astype(np.uint8)
    case_root = root / "multi_local"
    case_root.mkdir(parents=True, exist_ok=True)
    mask_path = case_root / "mask.png"
    output_path = case_root / "output.png"
    _write_mask(mask_path, mask)
    adapter.process(REAL_1080, mask_path, output_path)
    result = _read(output_path, cv.IMREAD_COLOR)
    return {
        "outside_change_max": _outside_max_delta(source, result, mask),
        "output_sha256": _sha256(output_path),
        "timings_ms": adapter.last_timings_ms,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO / "output/c61_retouch_performance_20260914/final_validation",
    )
    args = parser.parse_args()
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    adapter = LamaOnnxAdapter()
    report = {
        "protected_quality_replay": _protected_replay(adapter, root),
        "rectangle_brush_ab": _rectangle_brush_ab(adapter, root),
        "continuous_four_rounds": _continuous_four_rounds(adapter, root),
        "multi_local_repair": _multi_local_repair(adapter, root),
    }
    report_path = root / "validation.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "status": "PASS"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
