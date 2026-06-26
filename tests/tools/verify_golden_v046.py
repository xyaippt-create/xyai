from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from typing import Any

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = PROJECT_ROOT / "tests" / "golden_v046"
MANIFEST_PATH = GOLDEN_ROOT / "manifest.json"

REQUIRED_FIELDS = [
    "sample_id",
    "display_name",
    "set_level",
    "relative_path",
    "storage_class",
    "source_path",
    "source_sha256",
    "golden_sha256",
    "format",
    "width",
    "height",
    "color_mode",
    "has_alpha",
    "file_size_bytes",
    "image_type_expected",
    "image_type_current",
    "source_kind",
    "is_ai_generated",
    "is_low_quality",
    "risk_tags",
    "main_risk",
    "expected_behavior",
    "forbidden_regression",
    "legacy_phase1_sample",
    "sensitive",
    "committable",
    "reference_group_id",
    "is_reference_image",
    "color_mismatch_type",
    "future_feature",
    "status",
    "notes",
]

VALID_STORAGE_CLASS = {"repo", "private", "synthetic", "external_reference"}
VALID_STATUS = {"ready", "missing", "excluded", "needs_user_approval"}


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_tracked_paths() -> set[str]:
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return {line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()}


def load_manifest() -> list[dict[str, Any]]:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    samples = data.get("samples")
    if not isinstance(samples, list):
        raise ValueError("manifest.json must contain a samples list")
    return samples


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    if not MANIFEST_PATH.exists():
        print("FAIL manifest.json missing")
        return 1

    try:
        samples = load_manifest()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL manifest.json unreadable: {exc}")
        return 1

    tracked = git_tracked_paths()
    seen_ids: set[str] = set()
    sha_to_samples: dict[str, list[str]] = defaultdict(list)
    ready_count = 0

    for index, sample in enumerate(samples, start=1):
        sid = str(sample.get("sample_id") or f"row_{index}")
        if sid in seen_ids:
            errors.append(f"duplicate sample_id: {sid}")
        seen_ids.add(sid)

        for field in REQUIRED_FIELDS:
            if field not in sample:
                errors.append(f"{sid}: missing field {field}")

        storage_class = sample.get("storage_class")
        status = sample.get("status")
        if storage_class not in VALID_STORAGE_CLASS:
            errors.append(f"{sid}: invalid storage_class {storage_class}")
        if status not in VALID_STATUS:
            errors.append(f"{sid}: invalid status {status}")

        rel = str(sample.get("relative_path") or "")
        if rel.startswith("/") or ":" in rel:
            errors.append(f"{sid}: relative_path must be repository relative")

        if status != "ready":
            continue

        ready_count += 1
        if not rel:
            errors.append(f"{sid}: ready sample has empty relative_path")
            continue
        path = GOLDEN_ROOT / rel
        if not path.exists():
            errors.append(f"{sid}: file missing: {rel}")
            continue

        actual_sha = file_sha256(path)
        expected_sha = sample.get("golden_sha256")
        if actual_sha != expected_sha:
            errors.append(f"{sid}: SHA-256 mismatch")
        sha_to_samples[actual_sha].append(sid)

        try:
            with Image.open(path) as image:
                actual_format = image.format or path.suffix.lstrip(".").upper()
                actual_mode = image.mode
                actual_has_alpha = actual_mode in {"RGBA", "LA"} or "transparency" in image.info
                if str(sample.get("format")) != str(actual_format):
                    errors.append(f"{sid}: format mismatch {actual_format} != {sample.get('format')}")
                if int(sample.get("width")) != image.width or int(sample.get("height")) != image.height:
                    errors.append(f"{sid}: dimensions mismatch")
                if str(sample.get("color_mode")) != actual_mode:
                    errors.append(f"{sid}: color_mode mismatch")
                if bool(sample.get("has_alpha")) != actual_has_alpha:
                    errors.append(f"{sid}: alpha flag mismatch")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{sid}: image unreadable: {exc}")

        if storage_class == "private":
            tracked_rel = f"tests/golden_v046/{rel}".replace("\\", "/")
            if tracked_rel in tracked:
                errors.append(f"{sid}: private file is tracked by Git")
        elif storage_class in {"repo", "synthetic"}:
            if not sample.get("source_path") or not sample.get("source_kind"):
                errors.append(f"{sid}: public sample lacks source metadata")

        if storage_class == "repo" and sample.get("sensitive"):
            errors.append(f"{sid}: sensitive repo sample is not allowed")

    for digest, ids in sorted(sha_to_samples.items()):
        if len(ids) > 1:
            warnings.append(f"duplicate file content {digest[:12]}: {', '.join(ids)}")

    private_root = GOLDEN_ROOT / "private"
    if private_root.exists():
        tracked_private = [
            item
            for item in tracked
            if item.startswith("tests/golden_v046/private/")
        ]
        if tracked_private:
            errors.append("private directory contains tracked files")

    missing_count = sum(1 for item in samples if item.get("status") == "missing")
    print(
        json.dumps(
            {
                "ready": ready_count,
                "missing": missing_count,
                "warnings": warnings,
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if errors:
        print("FAIL")
        return 1
    if warnings:
        print("WARNING")
        return 0
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
