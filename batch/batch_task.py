from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BatchTask:
    source: Path
    output_dir: Path
    mode: str = "fidelity"
    scale: int = 2
    output_format: str = "png"


@dataclass(frozen=True)
class BatchTaskResult:
    source: Path
    output: Path | None
    ok: bool
    message: str
    width: int = 0
    height: int = 0
    quality_summary: dict | None = None
