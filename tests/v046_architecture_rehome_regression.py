from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import traceback
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

GOLDEN_ROOT = PROJECT_ROOT / "tests" / "golden_v046"
MANIFEST_PATH = GOLDEN_ROOT / "manifest.json"
RESULT_ROOT = PROJECT_ROOT / "tests" / "results" / "v046_architecture_rehome"

DIAGNOSTIC_FIELDS = [
    "image_type",
    "quality_1080p_pass",
    "quality_1080p_level",
    "final_output_type",
    "phase2_material_strength",
    "phase2_skip_reason",
    "phase3_edge_strength",
    "phase3_edge_skip_reason",
    "pseudo_hd_risk",
    "over_smoothing_risk",
    "texture_loss_risk",
    "color_fidelity_score",
    "file_size_ratio",
    "final_quality_source",
]


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_hashes(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
        if has_alpha:
            rgba = image.convert("RGBA")
            rgb_bytes = rgba.convert("RGB").tobytes()
            alpha_bytes = rgba.getchannel("A").tobytes()
            pixel_mode = "RGBA"
        else:
            rgb = image.convert("RGB")
            rgb_bytes = rgb.tobytes()
            alpha_bytes = b""
            pixel_mode = "RGB"
        return {
            "decoded_pixel_sha256": sha256(rgb_bytes).hexdigest(),
            "alpha_sha256": sha256(alpha_bytes).hexdigest() if has_alpha else "",
            "alpha_present": has_alpha,
            "decoded_mode": pixel_mode,
            "width": image.width,
            "height": image.height,
        }


def ready_samples() -> list[dict[str, Any]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return [
        item
        for item in manifest.get("samples", [])
        if item.get("status") == "ready"
        and item.get("relative_path")
        and item.get("storage_class") != "private"
    ]


def mode_for(sample: dict[str, Any]) -> str:
    return "text_safe" if sample.get("image_type_expected") == "text_poster" else "fidelity"


def output_format_for(path: Path, sample: dict[str, Any]) -> str:
    if bool(sample.get("has_alpha")):
        return "png"
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return "jpg"
    return "png"


def extract_diagnostics(payload: dict[str, Any]) -> dict[str, Any]:
    debug_quality = payload.get("debug_quality") or {}
    values: dict[str, Any] = {}
    for field in DIAGNOSTIC_FIELDS:
        if field in debug_quality:
            values[field] = debug_quality.get(field)
        else:
            values[field] = payload.get(field)
    return values


def run_direct(input_path: Path, output_dir: Path, sample: dict[str, Any]) -> dict[str, Any]:
    from backend.v036_output_core import process_v036_output

    return process_v036_output(
        input_path,
        output_dir,
        mode=mode_for(sample),
        output_profile="delivery_1080p",
        output_format=output_format_for(input_path, sample),
        debug_keep_intermediate=False,
    )


def run_pipeline(input_path: Path, output_dir: Path, sample: dict[str, Any]) -> dict[str, Any]:
    from engine.pipeline import process_v046_delivery

    return process_v046_delivery(
        {
            "input_path": input_path,
            "output_root": output_dir,
            "mode": mode_for(sample),
            "output_profile": "delivery_1080p",
            "output_format": output_format_for(input_path, sample),
            "debug_keep_intermediate": False,
        }
    )


def run_set(label: str, runner: Callable[[Path, Path, dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    run_root = RESULT_ROOT / label
    run_root.mkdir(parents=True, exist_ok=True)
    records = []
    for sample in ready_samples():
        sample_id = sample["sample_id"]
        input_path = GOLDEN_ROOT / sample["relative_path"]
        output_dir = run_root / sample_id
        output_dir.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        record: dict[str, Any] = {
            "sample_id": sample_id,
            "mode": mode_for(sample),
            "requested_output_format": output_format_for(input_path, sample),
            "input_path": str(input_path),
            "input_sha256": file_sha256(input_path),
            "status": "failed",
            "error": "",
        }
        try:
            payload = runner(input_path, output_dir, sample)
            final_path = Path(payload.get("final_output_path") or "")
            image_info = image_hashes(final_path) if final_path.exists() else {}
            record.update(
                {
                    "status": "completed" if final_path.exists() else "failed",
                    "output_path": str(final_path),
                    "output_sha256": file_sha256(final_path) if final_path.exists() else "",
                    "output_size_bytes": final_path.stat().st_size if final_path.exists() else None,
                    "output_format": final_path.suffix.lower().lstrip(".") if final_path.exists() else "",
                    "quality_1080p_pass": payload.get("quality_1080p_pass"),
                    "quality_1080p_level": payload.get("quality_1080p_level"),
                    "diagnostics": extract_diagnostics(payload),
                    "pipeline_trace": payload.get("pipeline_trace") or {},
                    "processing_time_ms": round((payload.get("debug_timing") or {}).get("total_time", 0.0) * 1000, 2),
                    **image_info,
                }
            )
            (output_dir / "diagnostic.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            record["error"] = traceback.format_exc()
        record["wall_time_ms"] = round((time.perf_counter() - started) * 1000, 2)
        (output_dir / "result.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        records.append(record)

    summary = {
        "label": label,
        "total": len(records),
        "completed": sum(1 for item in records if item.get("status") == "completed"),
        "failed": sum(1 for item in records if item.get("status") != "completed"),
        "results": records,
    }
    (run_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (run_root / "summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = [
            "sample_id",
            "status",
            "output_sha256",
            "decoded_pixel_sha256",
            "alpha_sha256",
            "alpha_present",
            "width",
            "height",
            "output_format",
            "output_size_bytes",
            "quality_1080p_pass",
            "quality_1080p_level",
            "processing_time_ms",
            "output_path",
            "error",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, "") for field in fields})
    return summary


def compare_summaries(before_path: Path, after_path: Path) -> dict[str, Any]:
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))
    before_by_id = {item["sample_id"]: item for item in before.get("results", [])}
    after_by_id = {item["sample_id"]: item for item in after.get("results", [])}
    sample_ids = sorted(before_by_id)
    rows = []
    for sample_id in sample_ids:
        left = before_by_id[sample_id]
        right = after_by_id.get(sample_id, {})
        diagnostics_match = left.get("diagnostics") == right.get("diagnostics")
        row = {
            "sample_id": sample_id,
            "file_sha256_match": left.get("output_sha256") == right.get("output_sha256"),
            "decoded_pixel_sha256_match": left.get("decoded_pixel_sha256") == right.get("decoded_pixel_sha256"),
            "alpha_sha256_match": left.get("alpha_sha256") == right.get("alpha_sha256"),
            "alpha_present_match": left.get("alpha_present") == right.get("alpha_present"),
            "dimensions_match": (left.get("width"), left.get("height")) == (right.get("width"), right.get("height")),
            "format_match": left.get("output_format") == right.get("output_format"),
            "size_match": left.get("output_size_bytes") == right.get("output_size_bytes"),
            "quality_gate_match": (
                left.get("quality_1080p_pass"),
                left.get("quality_1080p_level"),
            )
            == (
                right.get("quality_1080p_pass"),
                right.get("quality_1080p_level"),
            ),
            "diagnostics_match": diagnostics_match,
            "pipeline_entered": bool((right.get("pipeline_trace") or {}).get("entered_engine_pipeline")),
        }
        row["all_required_match"] = all(
            row[key]
            for key in [
                "decoded_pixel_sha256_match",
                "alpha_sha256_match",
                "alpha_present_match",
                "dimensions_match",
                "format_match",
                "size_match",
                "quality_gate_match",
                "diagnostics_match",
                "pipeline_entered",
            ]
        )
        rows.append(row)

    comparison = {
        "before": str(before_path),
        "after": str(after_path),
        "total": len(rows),
        "all_required_match_count": sum(1 for row in rows if row["all_required_match"]),
        "file_sha256_match_count": sum(1 for row in rows if row["file_sha256_match"]),
        "decoded_pixel_sha256_match_count": sum(1 for row in rows if row["decoded_pixel_sha256_match"]),
        "alpha_match_count": sum(1 for row in rows if row["alpha_sha256_match"] and row["alpha_present_match"]),
        "quality_gate_match_count": sum(1 for row in rows if row["quality_gate_match"]),
        "diagnostics_match_count": sum(1 for row in rows if row["diagnostics_match"]),
        "pipeline_entered_count": sum(1 for row in rows if row["pipeline_entered"]),
        "rows": rows,
    }
    target = RESULT_ROOT / "comparison_summary.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    with (RESULT_ROOT / "comparison_summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = list(rows[0].keys()) if rows else ["sample_id"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return comparison


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["baseline", "pipeline", "compare"])
    parser.add_argument("--before", type=Path)
    parser.add_argument("--after", type=Path)
    args = parser.parse_args()

    if args.command == "baseline":
        print(json.dumps(run_set("before_direct", run_direct), ensure_ascii=False, indent=2))
        return 0
    if args.command == "pipeline":
        print(json.dumps(run_set("after_pipeline", run_pipeline), ensure_ascii=False, indent=2))
        return 0
    before = args.before or RESULT_ROOT / "before_direct" / "summary.json"
    after = args.after or RESULT_ROOT / "after_pipeline" / "summary.json"
    comparison = compare_summaries(before, after)
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    return 0 if comparison["all_required_match_count"] == comparison["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
