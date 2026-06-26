from __future__ import annotations

import csv
import json
import subprocess
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
RESULT_ROOT = PROJECT_ROOT / "tests" / "results" / "golden_v046_phase1"


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_text(args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return (completed.stdout or completed.stderr).strip()


def mode_for(sample: dict[str, Any]) -> str:
    if sample.get("image_type_expected") == "text_poster":
        return "text_safe"
    return "fidelity"


def output_format_for(path: Path, sample: dict[str, Any]) -> str:
    if bool(sample.get("has_alpha")):
        return "png"
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return "jpg"
    return "png"


def run_sample(sample: dict[str, Any]) -> dict[str, Any]:
    sample_id = sample["sample_id"]
    input_path = GOLDEN_ROOT / sample["relative_path"]
    sample_dir = RESULT_ROOT / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    record: dict[str, Any] = {
        "sample_id": sample_id,
        "input_path": str(input_path),
        "input_sha256": file_sha256(input_path),
        "status": "failed",
        "error": "",
    }
    try:
        payload = process_v036_output(
            input_path,
            sample_dir,
            mode=mode_for(sample),
            output_profile="delivery_1080p",
            output_format=output_format_for(input_path, sample),
            debug_keep_intermediate=False,
        )
        final_path = Path(payload.get("final_output_path") or "")
        task_report = payload.get("task_report") or {}
        record.update(
            {
                "status": "completed" if final_path.exists() else "failed",
                "output_path": str(final_path),
                "output_sha256": file_sha256(final_path) if final_path.exists() else "",
                "image_type": payload.get("image_type"),
                "quality_1080p_pass": payload.get("quality_1080p_pass"),
                "quality_1080p_level": payload.get("quality_1080p_level"),
                "pseudo_hd_risk": task_report.get("pseudo_hd_risk"),
                "artifact_risk": task_report.get("artifact_risk"),
                "processing_time": payload.get("debug_timing", {}).get("total_time"),
                "output_size_bytes": final_path.stat().st_size if final_path.exists() else None,
                "warnings": task_report.get("warnings") or [],
            }
        )
        (sample_dir / "diagnostic.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        record["error"] = traceback.format_exc()
    record["wall_time"] = round(time.perf_counter() - started, 6)
    (sample_dir / "result.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return record


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    samples = [
        item
        for item in manifest.get("samples", [])
        if item.get("status") == "ready" and item.get("storage_class") != "private"
    ]
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    results = [run_sample(sample) for sample in samples]
    summary = {
        "task": "V0.4.6 golden set Phase 1 baseline run",
        "baseline_commit": git_text(["rev-parse", "v0.4.6-phase1-baseline"]),
        "baseline_tag": "v0.4.6-phase1-baseline",
        "head": git_text(["rev-parse", "HEAD"]),
        "total": len(results),
        "completed": sum(1 for item in results if item.get("status") == "completed"),
        "failed": sum(1 for item in results if item.get("status") != "completed"),
        "quality_1080p_false": sum(1 for item in results if item.get("quality_1080p_pass") is False),
        "file_size_warning_count": sum(
            1
            for item in results
            if any("体积" in str(warning) for warning in item.get("warnings", []))
        ),
        "results": results,
    }
    (RESULT_ROOT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    with (RESULT_ROOT / "summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = [
            "sample_id",
            "status",
            "input_sha256",
            "output_sha256",
            "image_type",
            "quality_1080p_pass",
            "quality_1080p_level",
            "pseudo_hd_risk",
            "artifact_risk",
            "processing_time",
            "output_size_bytes",
            "wall_time",
            "error",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in results:
            writer.writerow({field: item.get(field, "") for field in fields})
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
