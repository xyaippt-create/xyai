"""Single-image automatic color-correction core for HDDE."""

from .core import COLOR_CORRECTION_ENGINE_VERSION, ColorCorrectionResult, process_single_image

__all__ = ["COLOR_CORRECTION_ENGINE_VERSION", "ColorCorrectionResult", "process_single_image"]
