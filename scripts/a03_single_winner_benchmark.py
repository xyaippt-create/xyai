from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.image_compression.delivery_options import (  # noqa: E402
    JPG_BALANCED_SCHEME,
    JPG_HIGH_QUALITY_SCHEME,
    KEEP_ORIGINAL_SCHEME,
    PNG_LOSSLESS_SCHEME,
    generate_delivery_candidates,
)


SOURCE_REPORT = ROOT / "output" / "a02_lossless_benchmark" / "benchmark.json"
TARGET_ROOT = ROOT / "output" / "a03_single_winner_benchmark"
TARGET_REPORT = TARGET_ROOT / "benchmark.json"
SCHEME_RANK = {
    PNG_LOSSLESS_SCHEME: 0,
    JPG_HIGH_QUALITY_SCHEME: 1,
    JPG_BALANCED_SCHEME: 2,
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_evidence(candidate: dict[str, Any]) -> dict[str, Any]:
    gate = dict(candidate.get("quality_gate") or {})
    metadata = dict(candidate.get("metadata_details") or {})
    lossless = dict(metadata.get("lossless_verification") or {})
    identity = dict(candidate.get("artifact_identity") or {})
    return {
        "scheme_id": candidate["scheme_id"],
        "status": candidate["status"],
        "evaluation_bytes": candidate.get("file_size"),
        "quality_gate": gate,
        "pixel_diff_count": candidate.get("pixel_diff_count"),
        "max_channel_diff": candidate.get("max_channel_diff"),
        "lossless_verified": candidate.get("lossless_verified"),
        "alpha_verified": lossless.get("alpha_verified"),
        "metadata_verified": lossless.get("metadata_verified"),
        "icc_preserved": lossless.get("icc_preserved"),
        "dpi_preserved": lossless.get("dpi_preserved"),
        "exif_preserved": lossless.get("exif_preserved"),
        "xmp_preserved": lossless.get("xmp_preserved"),
        "evaluation_sha256": identity.get("evaluation_output_sha256") or identity.get("output_sha256"),
        "public_output_sha256": candidate.get("output_sha256"),
    }


def _expected_winner(candidates: list[dict[str, Any]], source_bytes: int) -> str:
    eligible = [
        candidate
        for candidate in candidates
        if candidate.get("status") in {"AVAILABLE", "INTERNAL_ONLY"}
        and (candidate.get("quality_gate") or {}).get("status") == "PASS"
        and int(candidate.get("file_size") or source_bytes) < source_bytes
    ]
    if not eligible:
        return KEEP_ORIGINAL_SCHEME
    return str(min(
        eligible,
        key=lambda item: (int(item["file_size"]), SCHEME_RANK[str(item["scheme_id"])]),
    )["scheme_id"])


def _jpg_gate_contract(candidate: dict[str, Any], *, transparent: bool) -> bool:
    status = str(candidate.get("status") or "")
    gate = dict(candidate.get("quality_gate") or {})
    gate_status = str(gate.get("status") or "")
    if transparent:
        return status == "NOT_APPLICABLE" and gate_status == "NOT_APPLICABLE"
    if status in {"AVAILABLE", "INTERNAL_ONLY"}:
        return gate_status == "PASS" and isinstance(gate.get("checks"), dict)
    if status == "QUALITY_REJECTED":
        return gate_status == "FAIL" and bool(gate.get("failure_reasons"))
    return False


def main() -> None:
    source_report = json.loads(SOURCE_REPORT.read_text(encoding="utf-8"))
    source_rows = list(source_report.get("rows") or [])
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_root = TARGET_ROOT / "runs" / run_stamp
    rows: list[dict[str, Any]] = []

    for index, source_row in enumerate(source_rows, start=1):
        source_path = Path(str(source_row["source_path"])).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Benchmark Source 不存在：{source_path}")
        output_root = run_root / f"{index:02d}"
        generated = generate_delivery_candidates(
            source_path,
            output_root,
            source_filename=source_path.name,
            moment=datetime(2026, 9, 5, 12, 0, index),
        )
        candidates = list(generated["candidates"])
        candidate_map = {str(item["scheme_id"]): item for item in candidates}
        winner = dict(generated["winner"])
        winner_scheme = str(generated["winner_scheme_id"])
        winner_is_source = winner_scheme == KEEP_ORIGINAL_SCHEME
        source_bytes = int(generated["source"]["size_bytes"])
        source_sha256 = str(generated["source_identity"]["sha256"])
        winner_bytes = int(winner["file_size"])
        formal_files = sorted(path for path in output_root.iterdir() if path.is_file())
        formal_file = formal_files[0] if len(formal_files) == 1 else None
        formal_sha256 = _sha256_file(formal_file) if formal_file else None
        expected_winner = _expected_winner(candidates, source_bytes)
        transparent = bool(generated["source_has_real_transparency"])
        png = candidate_map[PNG_LOSSLESS_SCHEME]
        jpg_high = candidate_map[JPG_HIGH_QUALITY_SCHEME]
        jpg_balanced = candidate_map[JPG_BALANCED_SCHEME]
        registered_winner_sha = str(winner.get("output_sha256") or "")
        public_contract = (
            generated["public_output_count"] == 0
            and len(formal_files) == 0
            and winner_is_source
        ) or (
            generated["public_output_count"] == 1
            and len(formal_files) == 1
            and not winner_is_source
            and formal_file is not None
            and Path(str(winner["output_path"])).resolve() == formal_file.resolve()
            and formal_sha256 == registered_winner_sha
        )
        png_lossless_contract = (
            png.get("quality_gate", {}).get("status") == "PASS"
            and png.get("lossless_verified") is True
            and png.get("pixel_diff_count") == 0
            and png.get("max_channel_diff") == 0
        )
        transparency_contract = (
            not transparent
            or (
                jpg_high.get("status") == "NOT_APPLICABLE"
                and jpg_balanced.get("status") == "NOT_APPLICABLE"
                and winner_scheme not in {JPG_HIGH_QUALITY_SCHEME, JPG_BALANCED_SCHEME}
            )
        )
        row_checks = {
            "source_identity_pass": (
                _sha256_file(source_path) == source_sha256
                and int(source_path.stat().st_size) == int(generated["source_identity"]["size_bytes"])
            ),
            "png_lossless_gate_pass": png_lossless_contract,
            "jpg_quality_gate_pass": (
                _jpg_gate_contract(jpg_high, transparent=transparent)
                and _jpg_gate_contract(jpg_balanced, transparent=transparent)
            ),
            "transparency_protection_pass": transparency_contract,
            "winner_selection_pass": winner_scheme == expected_winner,
            "positive_saving_policy_pass": winner_is_source or winner_bytes < source_bytes,
            "public_output_contract_pass": public_contract,
            "public_output_count_at_most_one": generated["public_output_count"] <= 1 and len(formal_files) <= 1,
        }
        rows.append({
            "sample_class": source_row["sample_class"],
            "source_path": str(source_path),
            "source_sha256": source_sha256,
            "source_bytes": source_bytes,
            "source_has_real_transparency": transparent,
            "png_lossless": _candidate_evidence(png),
            "jpg_high_quality": _candidate_evidence(jpg_high),
            "jpg_balanced": _candidate_evidence(jpg_balanced),
            "expected_winner_scheme_id": expected_winner,
            "winner_scheme_id": winner_scheme,
            "winner_is_source": winner_is_source,
            "winner_bytes": winner_bytes,
            "winner_sha256": registered_winner_sha,
            "saved_bytes": source_bytes - winner_bytes,
            "saved_percent": round((source_bytes - winner_bytes) / source_bytes * 100.0, 4),
            "selection_reason": generated["recommendation_reason"],
            "public_output_count": generated["public_output_count"],
            "formal_file_count": len(formal_files),
            "formal_file": str(formal_file) if formal_file else None,
            "formal_file_sha256": formal_sha256,
            "checks": row_checks,
            "status": "PASS" if all(row_checks.values()) else "FAIL",
        })

    required_classes = {
        "中文商业PPT/海报",
        "普通照片",
        "大面积渐变",
        "高频纹理",
        "RGBA全Alpha255",
        "真实透明PNG",
    }
    aggregate_checks = {
        "six_required_classes_present": len(rows) == 6 and {row["sample_class"] for row in rows} == required_classes,
        "all_case_contracts_pass": bool(rows) and all(row["status"] == "PASS" for row in rows),
        "persistent_formal_evidence_valid": all(
            row["winner_is_source"]
            or (
                row["formal_file"] is not None
                and Path(str(row["formal_file"])).is_file()
                and _sha256_file(Path(str(row["formal_file"]))) == row["formal_file_sha256"]
            )
            for row in rows
        ),
    }
    status = "PASS" if all(aggregate_checks.values()) else "FAIL"
    report = {
        "status": status,
        "policy": "SINGLE_WINNER_QUALITY_V1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_report": str(SOURCE_REPORT),
        "run_root": str(run_root),
        "sample_count": len(rows),
        "aggregate_checks": aggregate_checks,
        "rows": rows,
    }
    run_root.mkdir(parents=True, exist_ok=True)
    run_report = run_root / "benchmark.json"
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    run_report.write_text(encoded, encoding="utf-8")
    TARGET_ROOT.mkdir(parents=True, exist_ok=True)
    TARGET_REPORT.write_text(encoded, encoding="utf-8")
    print(json.dumps({
        "status": status,
        "report": str(TARGET_REPORT),
        "run_report": str(run_report),
        "sample_count": len(rows),
        "aggregate_checks": aggregate_checks,
    }, ensure_ascii=False))
    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
