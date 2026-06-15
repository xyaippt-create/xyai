from __future__ import annotations

from pathlib import Path


def run_ai_restore(
    input_path,
    output_path,
    mode: str = "fidelity",
    strength: float = 0.5,
    preserve_text: bool = True,
    preserve_color: bool = True,
):
    """Reserved V0.5 AI Restoration Engine integration point.

    Current V0.4 keeps the stable OpenCV pipeline. This function is intentionally
    lightweight and does not require Torch, ONNXRuntime, Real-ESRGAN, SwinIR or HAT.
    Future model adapters can replace this body while keeping the same contract.
    """
    _ = mode, strength, preserve_text, preserve_color
    return Path(input_path), Path(output_path)
