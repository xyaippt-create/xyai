from dataclasses import dataclass, field
from pathlib import Path

from .processing_strategy import ProcessingStrategy


@dataclass(frozen=True)
class EnhancementProfile:
    name: str
    description: str
    target_width: int = 3840
    output_suffix: str = "_VisualMasterPro"
    output_format: str = ".png"
    cleanup_strength: float = 0.35
    micro_contrast: float = 0.35
    sharpness: float = 0.18
    high_frequency_guard: float = 0.5
    material_weights: dict[str, float] = field(default_factory=dict)
    style_tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ProcessingResult:
    source: Path
    output: Path
    width: int
    height: int
    ok: bool
    mode: str = ""
    requested_mode: str = ""
    message: str = ""
    analysis: dict | None = None
    quality_report: dict | None = None
    quality_report_json_path: Path | None = None
    quality_report_markdown_path: Path | None = None

    @property
    def quality_report_path(self) -> Path | None:
        return self.quality_report_json_path


__all__ = [
    "EnhancementProfile",
    "ProcessingResult",
    "ProcessingStrategy",
]
