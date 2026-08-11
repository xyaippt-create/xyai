from __future__ import annotations

from pathlib import Path

from .contracts import LocalRetouchAdapter, LocalRetouchResult
from .lama_adapter import LamaOnnxAdapter


class LocalRetouchEngine:
    """Stable product boundary for local retouch engines and future adapters."""

    def __init__(self, adapter: LocalRetouchAdapter | None = None) -> None:
        self._adapter = adapter or LamaOnnxAdapter()

    @property
    def engine_id(self) -> str:
        return self._adapter.engine_id

    def capabilities(self) -> dict[str, object]:
        return dict(self._adapter.availability())

    def process(self, source_path: Path, mask_path: Path, output_path: Path) -> LocalRetouchResult:
        return self._adapter.process(source_path, mask_path, output_path)
