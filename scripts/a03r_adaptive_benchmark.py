from __future__ import annotations

import hashlib
import json
import sys
import time
import tracemalloc
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.image_compression.delivery_options import (  # noqa: E402
    KEEP_ORIGINAL_SCHEME,
    PNG_LOSSLESS_SCHEME,
    generate_delivery_candidates,
)


TARGET_ROOT = ROOT / "output" / "a03r_adaptive_benchmark"
TARGET_REPORT = TARGET_ROOT / "benchmark.json"

SAMPLES = (
    ("中文商业图", "output/playwright/大疆创新信息图.png"),
    ("中文商业图", "output/g_line_final_benchmark_20260901/assets/normal_commercial_poster.png"),
    ("中文商业图", "output/g_line_final_benchmark_20260901/assets/normal_ppt_visual.png"),
    ("中文商业图", "output/g_line_final_benchmark_20260901/assets/normal_dark_kv.png"),
    ("中文商业图", "public/branding/hdde/splash-light.png"),
    ("中文商业图", "output/stage5_output_center_20260809_221329/output-center-light-final.png"),
    ("普通照片", "output/playwright/真实会议照片.jpg"),
    ("普通照片", "output/g_line_final_benchmark_20260901/assets/normal_photography.png"),
    ("普通照片", "output/g_line_final_benchmark_20260901/assets/problem_cool_cast.png"),
    ("普通照片", "output/g_line_final_benchmark_20260901/assets/problem_green_cast.png"),
    ("普通照片", "output/g_line_final_benchmark_20260901/assets/problem_warm_cast.png"),
    ("普通照片", "output/g_line_final_benchmark_20260901/assets/problem_underexposure.png"),
    ("大面积渐变", "public/branding/hdde/splash-dark.png"),
    ("大面积渐变", "output/playwright/ui-harmony-20260729-final/09-comparison-light.png"),
    ("大面积渐变", "output/g_line_final_benchmark_20260901/assets/problem_overexposure.png"),
    ("高频纹理", "output/g_line_final_benchmark_20260901/assets/problem_noise.png"),
    ("高频纹理", "output/g_line_final_benchmark_20260901/assets/problem_jpeg_compression.jpg"),
    ("高频纹理", "tests/fixtures/ocr_n2_02/samples/perspective_fragmented.png"),
    ("高频纹理", "output/playwright/c58_04_closure_20260901/benchmark/05_texture/candidate.png"),
    ("RGBA全Alpha255", "output/a02_lossless_benchmark/inputs/真实照片内容_RGBA全255_300DPI.png"),
    ("真实透明PNG", "output/g_line_final_benchmark_20260901/assets/special_transparent_png.png"),
    ("真实透明PNG", "output/g_line_final_benchmark_20260901/assets/special_semitransparent_png.png"),
    ("真实透明PNG", "public/branding/hdde/logo-light.png"),
    ("真实透明PNG", "public/branding/hdde/app-icon.png"),
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jpg_size_benefit(candidate: dict[str, Any], source_bytes: int, profile: dict[str, Any]) -> bool:
    saved_bytes = source_bytes - int(candidate["file_size"])
    saved_percent = saved_bytes / source_bytes * 100.0 if source_bytes else 0.0
    return bool(
        saved_bytes >= int(profile["min_jpg_saved_bytes"])
        and saved_percent >= float(profile["min_jpg_saved_percent"])
    )


def _expected_winner(candidates: list[dict[str, Any]], source_bytes: int, profile: dict[str, Any]) -> str:
    eligible: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.get("status") not in {"AVAILABLE", "INTERNAL_ONLY"}:
            continue
        if (candidate.get("quality_gate") or {}).get("status") != "PASS":
            continue
        if candidate.get("format") == "PNG":
            beneficial = int(candidate["file_size"]) < source_bytes
        else:
            beneficial = _jpg_size_benefit(candidate, source_bytes, profile)
        if beneficial:
            eligible.append(candidate)
    if not eligible:
        return KEEP_ORIGINAL_SCHEME
    return str(min(
        eligible,
        key=lambda item: (
            int(item["file_size"]),
            0 if item["format"] == "PNG" else 1,
            str(item["scheme_id"]),
        ),
    )["scheme_id"])


def main() -> None:
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_root = TARGET_ROOT / "runs" / run_stamp
    rows: list[dict[str, Any]] = []
    for index, (sample_class, relative_path) in enumerate(SAMPLES, start=1):
        source_path = (ROOT / relative_path).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Benchmark Source 不存在：{source_path}")
        output_root = run_root / f"{index:02d}"
        tracemalloc.start()
        started = time.perf_counter()
        generated = generate_delivery_candidates(
            source_path,
            output_root,
            source_filename=source_path.name,
            moment=datetime(2026, 9, 5, 18, 0, index),
        )
        total_seconds = time.perf_counter() - started
        _current_memory, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        candidates = list(generated["candidates"])
        source_bytes = int(generated["source_identity"]["size_bytes"])
        source_sha256 = str(generated["source_identity"]["sha256"])
        size_profile = dict(generated["size_search_profile"])
        content_profile = dict(generated["content_risk_profile"])
        jpg_search = dict(generated["jpg_search"])
        winner = dict(generated["winner"])
        winner_scheme = str(generated["winner_scheme_id"])
        winner_is_source = winner_scheme == KEEP_ORIGINAL_SCHEME
        winner_bytes = int(winner["file_size"])
        png = next(item for item in candidates if item["scheme_id"] == PNG_LOSSLESS_SCHEME)
        lossless_verification = dict(
            (png.get("metadata_details") or {}).get("lossless_verification") or {}
        )
        jpgs = [item for item in candidates if item["format"] == "JPG"]
        jpg_passing = [item for item in jpgs if (item.get("quality_gate") or {}).get("status") == "PASS"]
        formal_files = sorted(path for path in output_root.iterdir() if path.is_file())
        delivered_sha256 = _sha256_file(formal_files[0]) if len(formal_files) == 1 else None
        expected_winner = _expected_winner(candidates, source_bytes, size_profile)
        public_contract = (
            winner_is_source
            and generated["public_output_count"] == 0
            and len(formal_files) == 0
        ) or (
            not winner_is_source
            and generated["public_output_count"] == 1
            and len(formal_files) == 1
            and delivered_sha256 == winner.get("output_sha256")
        )
        checks = {
            "source_identity": _sha256_file(source_path) == source_sha256,
            "lossless_gate": (
                png.get("lossless_verified") is True
                and png.get("pixel_diff_count") == 0
                and png.get("max_channel_diff") == 0
                and (png.get("quality_gate") or {}).get("status") == "PASS"
            ),
            "jpg_search_bounded": int(jpg_search["encode_count"]) <= int(jpg_search["max_encodings"]),
            "jpg_gate_contract": all(
                (candidate.get("quality_gate") or {}).get("status") in {"PASS", "FAIL", "NOT_APPLICABLE"}
                for candidate in jpgs
            ),
            "direct_source_lineage": all(candidate.get("direct_source_lineage") is True for candidate in candidates),
            "winner_selection": winner_scheme == expected_winner,
            "winner_gate": (winner.get("quality_gate") or {}).get("status") == "PASS",
            "public_output_contract": public_contract,
            "public_output_at_most_one": generated["public_output_count"] <= 1 and len(formal_files) <= 1,
        }
        rows.append({
            "sample_class": sample_class,
            "source_path": str(source_path),
            "source_bytes": source_bytes,
            "source_sha256": source_sha256,
            "size_profile": size_profile["profile_id"],
            "content_risk_profile": content_profile["profile_id"],
            "content_risk_metrics": content_profile["metrics"],
            "lossless_best_bytes": int(png["file_size"]),
            "lossless_saved_percent": round((source_bytes - int(png["file_size"])) / source_bytes * 100.0, 4),
            "pixel_diff_count": png.get("pixel_diff_count"),
            "max_channel_diff": png.get("max_channel_diff"),
            "alpha_optimized": png.get("alpha_optimized"),
            "alpha_status": "PASS" if lossless_verification.get("alpha_preserved") is True else "FAIL",
            "icc_status": "PASS" if lossless_verification.get("icc_preserved") is True else "FAIL",
            "dpi_status": "PASS" if lossless_verification.get("dpi_preserved") is True else "FAIL",
            "metadata_status": "PASS" if lossless_verification.get("metadata_verified") is True else "FAIL",
            "metadata_verified": lossless_verification.get("metadata_verified"),
            "jpg_search_count": jpg_search["encode_count"],
            "jpg_lowest_safe_quality": jpg_search["lowest_safe_quality"],
            "jpg_lowest_safe_subsampling": jpg_search["lowest_safe_subsampling"],
            "jpg_best_passing_bytes": jpg_search["best_passing_bytes"],
            "jpg_pass_count": len(jpg_passing),
            "jpg_quality_gate_status": (
                "PASS"
                if jpg_passing
                else (
                    "NOT_APPLICABLE"
                    if jpgs and all(
                        (candidate.get("quality_gate") or {}).get("status") == "NOT_APPLICABLE"
                        for candidate in jpgs
                    )
                    else "FAIL"
                )
            ),
            "winner_scheme_id": winner_scheme,
            "winner_format": winner["format"],
            "winner_bytes": winner_bytes,
            "winner_sha256": winner.get("output_sha256"),
            "winner_quality_gate_status": (winner.get("quality_gate") or {}).get("status"),
            "winner_reason": winner.get("reason"),
            "winner_is_source": winner_is_source,
            "saved_bytes": source_bytes - winner_bytes,
            "saved_percent": round((source_bytes - winner_bytes) / source_bytes * 100.0, 4),
            "keep_reason": winner["reason"] if winner_is_source else None,
            "public_output_count": generated["public_output_count"],
            "formal_file_count": len(formal_files),
            "formal_file": str(formal_files[0]) if len(formal_files) == 1 else None,
            "delivered_sha256": delivered_sha256,
            "total_seconds": round(total_seconds, 6),
            "peak_python_memory_bytes": int(peak_memory),
            "checks": checks,
            "status": "PASS" if all(checks.values()) else "FAIL",
        })

    size_profiles = {row["size_profile"] for row in rows}
    required_classes = {"中文商业图", "普通照片", "大面积渐变", "高频纹理", "RGBA全Alpha255", "真实透明PNG"}
    aggregate_checks = {
        "sample_count_20_to_30": 20 <= len(rows) <= 30,
        "all_required_classes_present": {row["sample_class"] for row in rows} == required_classes,
        "all_size_profiles_present": size_profiles == {"SMALL", "MEDIUM", "LARGE", "VERY_LARGE"},
        "all_contracts_pass": all(row["status"] == "PASS" for row in rows),
        "all_lossless_pixel_exact": all(row["pixel_diff_count"] == 0 and row["max_channel_diff"] == 0 for row in rows),
        "public_output_at_most_one": all(row["formal_file_count"] <= 1 for row in rows),
    }
    status = "PASS" if all(aggregate_checks.values()) else "FAIL"
    report = {
        "status": status,
        "policy": "SINGLE_WINNER_QUALITY_V2",
        "benchmark_version": "A03_R_BENCHMARK_V2",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "run_root": str(run_root),
        "sample_count": len(rows),
        "aggregate_checks": aggregate_checks,
        "performance": {
            "total_seconds": round(sum(row["total_seconds"] for row in rows), 6),
            "max_sample_seconds": max(row["total_seconds"] for row in rows),
            "max_encode_count": max(row["jpg_search_count"] for row in rows),
            "max_peak_python_memory_bytes": max(row["peak_python_memory_bytes"] for row in rows),
        },
        "rows": rows,
    }
    run_root.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    run_report = run_root / "benchmark.json"
    run_report.write_text(encoded, encoding="utf-8")
    TARGET_ROOT.mkdir(parents=True, exist_ok=True)
    TARGET_REPORT.write_text(encoded, encoding="utf-8")
    print(json.dumps({
        "status": status,
        "report": str(TARGET_REPORT),
        "run_report": str(run_report),
        "sample_count": len(rows),
        "aggregate_checks": aggregate_checks,
        "performance": report["performance"],
    }, ensure_ascii=False))
    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
