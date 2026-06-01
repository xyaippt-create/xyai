from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ImageItem:
    path: Path
    width: int = 0
    height: int = 0
    size_text: str = ""
    status: str = "等待"


@dataclass
class GuiState:
    images: list[ImageItem] = field(default_factory=list)
    output_dir: Path | None = None
    mode: str = "fidelity"
    scale: int = 2
    output_format: str = "png"
    running: bool = False
    paused: bool = False
    stop_requested: bool = False
    success_count: int = 0
    failed_count: int = 0
