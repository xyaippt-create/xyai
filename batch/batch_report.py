from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .batch_task import BatchTaskResult


def write_batch_report(
    report_root: str | Path,
    results: list[BatchTaskResult],
    mode: str,
    scale: int,
    output_format: str,
) -> Path:
    report_dir = Path(report_root) / "batch_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"batch_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    data = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "VisualMasterPro V0.3",
        "mode": mode,
        "scale": scale,
        "output_format": output_format,
        "total": len(results),
        "success": sum(1 for item in results if item.ok),
        "failed": sum(1 for item in results if not item.ok),
        "results": [
            {
                **asdict(item),
                "source": str(item.source),
                "output": str(item.output) if item.output else "",
            }
            for item in results
        ],
    }
    report_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path
