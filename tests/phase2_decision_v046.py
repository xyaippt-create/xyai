from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import traceback
from hashlib import sha256
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.v036_output_core import process_v036_output  # noqa: E402


GOLDEN_ROOT = PROJECT_ROOT / "tests" / "golden_v046"
MANIFEST_PATH = GOLDEN_ROOT / "manifest.json"
RESULT_ROOT = PROJECT_ROOT / "tests" / "results" / "v046_phase2_round1"

DECISION_SAMPLE_IDS = [
    "smoke_original_unprocessed_jpg",
    "smoke_product_png_legacy",
    "smoke_transparent_png_legacy",
    "smoke_text_poster_cn_small_legacy",
    "core_product_low_png",
    "smoke_architecture_low",
]


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mode_for(sample: dict[str, Any]) -> str:
    return "text_safe" if sample.get("image_type_expected") == "text_poster" else "fidelity"


def output_format_for(path: Path, sample: dict[str, Any]) -> str:
    if bool(sample.get("has_alpha")):
        return "png"
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return "jpg"
    return "png"


def summarize_payload(sample: dict[str, Any], input_path: Path, payload: dict[str, Any], elapsed: float) -> dict[str, Any]:
    final_path = Path(payload.get("final_output_path") or "")
    debug_quality = payload.get("debug_quality") or {}
    task_report = payload.get("task_report") or {}
    return {
        "sample_id": sample["sample_id"],
        "expected_type": sample.get("image_type_expected"),
        "image_type": payload.get("image_type"),
        "mode": mode_for(sample),
        "input_path": str(input_path),
        "input_sha256": file_sha256(input_path),
        "output_path": str(final_path),
        "output_exists": final_path.exists(),
        "output_sha256": file_sha256(final_path) if final_path.exists() else "",
        "input_size_bytes": input_path.stat().st_size,
        "output_size_bytes": final_path.stat().st_size if final_path.exists() else None,
        "file_size_ratio": payload.get("file_size_ratio"),
        "quality_1080p_pass": payload.get("quality_1080p_pass"),
        "quality_1080p_level": payload.get("quality_1080p_level"),
        "clarity_gain": debug_quality.get("clarity_gain"),
        "text_clarity_gain": debug_quality.get("text_clarity_gain"),
        "edge_quality_gain": debug_quality.get("edge_quality_gain"),
        "detail_stability_score": debug_quality.get("detail_stability_score"),
        "color_fidelity_score": debug_quality.get("color_fidelity_score"),
        "pseudo_hd_risk": debug_quality.get("pseudo_hd_risk"),
        "over_smoothing_risk": debug_quality.get("over_smoothing_risk"),
        "texture_loss_risk": debug_quality.get("texture_loss_risk"),
        "warnings": task_report.get("warnings") or payload.get("warnings") or [],
        "elapsed_seconds": round(elapsed, 6),
    }


def run_sample(label: str, sample: dict[str, Any]) -> dict[str, Any]:
    input_path = GOLDEN_ROOT / sample["relative_path"]
    sample_dir = RESULT_ROOT / label / sample["sample_id"]
    sample_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    try:
        payload = process_v036_output(
            input_path,
            sample_dir,
            mode=mode_for(sample),
            output_profile="delivery_1080p",
            output_format=output_format_for(input_path, sample),
            debug_keep_intermediate=True,
        )
        elapsed = time.perf_counter() - started
        record = summarize_payload(sample, input_path, payload, elapsed)
        record["status"] = "completed" if record["output_exists"] else "failed"
        record["error"] = ""
        (sample_dir / "diagnostic.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        record = {
            "sample_id": sample["sample_id"],
            "status": "failed",
            "error": traceback.format_exc(),
            "elapsed_seconds": round(time.perf_counter() - started, 6),
        }
    (sample_dir / "result.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return record


def write_summary(label: str, records: list[dict[str, Any]]) -> None:
    out_dir = RESULT_ROOT / label
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "task": "V0.4.6 Phase 2 round1 decision samples",
        "label": label,
        "total": len(records),
        "completed": sum(1 for item in records if item.get("status") == "completed"),
        "failed": sum(1 for item in records if item.get("status") != "completed"),
        "results": records,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = [
        "sample_id",
        "status",
        "expected_type",
        "image_type",
        "mode",
        "input_size_bytes",
        "output_size_bytes",
        "file_size_ratio",
        "quality_1080p_pass",
        "quality_1080p_level",
        "clarity_gain",
        "text_clarity_gain",
        "edge_quality_gain",
        "detail_stability_score",
        "color_fidelity_score",
        "pseudo_hd_risk",
        "over_smoothing_risk",
        "texture_loss_risk",
        "output_path",
        "error",
    ]
    with (out_dir / "summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in records:
            writer.writerow({field: item.get(field, "") for field in fields})
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, choices=["phase1_baseline", "phase2_candidate"])
    args = parser.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    samples_by_id = {item["sample_id"]: item for item in manifest["samples"]}
    records = [run_sample(args.label, samples_by_id[sample_id]) for sample_id in DECISION_SAMPLE_IDS]
    write_summary(args.label, records)
    return 0 if all(item.get("status") == "completed" for item in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
