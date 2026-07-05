from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.delivery_naming import DEFAULT_TEMPLATES, NamingSettings, SourceFile, build_rename_plan, export_rename_map_csv


def run_smoke(keep_dir: bool = False) -> dict[str, object]:
    temp_context = tempfile.TemporaryDirectory(prefix="hdde_delivery_naming_")
    root = Path(temp_context.name)
    try:
        source_dir = root / "source"
        target_dir = root / "renamed"
        source_dir.mkdir(parents=True, exist_ok=True)
        files = [
            source_dir / "产品图A.png",
            source_dir / "产品图B.png",
            source_dir / "缺字段.png",
            source_dir / "非法字符.png",
        ]
        for path in files:
            path.write_bytes(b"smoke")

        sources = [
            SourceFile(files[0], {"industry": "美妆", "title": "新品海报", "mode": "safe1080p"}),
            SourceFile(files[1], {"industry": "美妆", "title": "新品海报", "mode": "safe1080p"}),
            SourceFile(files[2], {"industry": "食品", "mode": "safe1080p"}),
            SourceFile(files[3], {"industry": "家居/软装", "title": '主图:夏季?新品', "mode": "safe1080p"}),
        ]
        settings = NamingSettings(
            template=DEFAULT_TEMPLATES["commercial_project"],
            start_index=1,
            index_width=3,
            separator="_",
            output_dir=target_dir,
            mode="safe1080p",
            resolution="1080P",
        )
        rows = build_rename_plan(sources, settings, existing_names=["001_美妆_新品海报_safe1080p.png"])
        csv_text = export_rename_map_csv(rows)
        summary = {
            "temp_dir": str(root),
            "targets": [row.target_name for row in rows],
            "statuses": [row.status for row in rows],
            "missing_fields": {row.source_name: row.missing_fields for row in rows if row.missing_fields},
            "conflicts": {row.source_name: row.conflict_status for row in rows},
            "csv_has_required_columns": all(
                column in csv_text.splitlines()[0]
                for column in ["source_path", "target_name", "missing_fields", "conflict_status", "applied"]
            ),
        }
        if keep_dir:
            temp_context.cleanup = lambda: None  # type: ignore[method-assign]
        return summary
    finally:
        if not keep_dir:
            temp_context.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test for HDDE rule-based delivery naming.")
    parser.add_argument("--keep-dir", action="store_true", help="Keep the temporary smoke directory for inspection.")
    args = parser.parse_args()
    summary = run_smoke(keep_dir=args.keep_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["csv_has_required_columns"]:
        return 1
    if "needs_confirmation" not in summary["statuses"]:
        return 1
    if "renamed_duplicate" not in summary["conflicts"].values():
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
