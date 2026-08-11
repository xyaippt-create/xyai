from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class LocalRetouchResult:
    engine_id: str
    output_path: Path
    width: int
    height: int
    format: str
    mask_pixels: int
    inference_seconds: float
    source_sha256: str


class LocalRetouchAdapter(Protocol):
    engine_id: str

    def availability(self) -> dict[str, object]: ...

    def process(self, source_path: Path, mask_path: Path, output_path: Path) -> LocalRetouchResult: ...
