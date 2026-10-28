"""Formal batch-watermark contracts for HDDE."""

from .engine import WatermarkEngine, WatermarkRenderResult
from .spec import WatermarkSpec, WatermarkSpecError

__all__ = [
    "WatermarkEngine",
    "WatermarkRenderResult",
    "WatermarkSpec",
    "WatermarkSpecError",
]
