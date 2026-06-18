from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from backend.v036_output_core import process_v036_output


def run_v046_delivery(context: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt the V0.4.6 delivery core into the engine pipeline without reprocessing."""

    result = process_v036_output(
        Path(context["input_path"]),
        Path(context["output_root"]),
        mode=str(context.get("mode") or "fidelity"),
        output_profile=str(context.get("output_profile") or "delivery_1080p"),
        output_format=str(context.get("output_format") or "auto"),
        initial_timing=context.get("debug_timing"),
        debug_keep_intermediate=context.get("debug_keep_intermediate", False),
        color_stability_enabled=context.get("color_stability_enabled", True),
        color_correction_enabled=context.get("color_correction_enabled", False),
    )
    return result
