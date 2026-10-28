"""Minimal HD Core carrier for optional, dependency-injected candidates.

No enhancement is registered here.  The frozen safe base remains the only
production route until a separately proven candidate is supplied by a caller.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any, Callable

from .safe_base import (
    HDCoreSafeBaseError,
    assess_baseline_risk,
    finalize_with_baseline_fallback,
    process_hd_core_safe_base,
)


CandidateEnhancer = Callable[[Path, Path], None]


def _fallback_risk(reason: str) -> dict[str, Any]:
    """Express a candidate execution failure to the frozen fallback selector."""

    return {
        "status": "FAIL",
        "fallback_required": True,
        "reasons": [reason],
    }


def process_hd_core_pipeline(
    source_path: str | Path,
    workspace_root: str | Path,
    *,
    candidate: CandidateEnhancer | None = None,
    candidate_name: str | None = None,
) -> dict[str, Any]:
    """Run the frozen safe base and optionally evaluate one injected candidate.

    A candidate receives only an internal copy of the safe baseline and a fixed
    internal destination.  It is never registered as a production capability.
    The frozen risk assessment and fallback selector own every final decision.
    """

    started = time.perf_counter()
    source = Path(source_path)
    root = Path(workspace_root)
    candidate_enabled = candidate is not None
    recorded_name = (
        candidate_name or getattr(candidate, "__name__", "INJECTED_CANDIDATE")
        if candidate
        else "NONE"
    )

    safe_result = process_hd_core_safe_base(source, root)
    baseline_path_text = str(safe_result.get("final_output_path") or "")
    runtime_record: dict[str, Any] = {
        "baseline": baseline_path_text,
        "candidate_enabled": candidate_enabled,
        "candidate_name": recorded_name,
        "decision": "ACCEPT",
        "fallback_reason": "NONE",
        "elapsed_time": 0.0,
    }

    if safe_result.get("status") != "COMPLETED":
        runtime_record["elapsed_time"] = round(time.perf_counter() - started, 4)
        return {
            "status": safe_result.get("status", "NOT_COMPLETED"),
            "hd_core_pipeline": "SAFE_BASE_DISPOSITION_ONLY",
            "runtime_record": runtime_record,
            "baseline_result": safe_result,
            "final_output_path": baseline_path_text,
        }

    baseline_path = Path(baseline_path_text)
    if not candidate_enabled:
        runtime_record["elapsed_time"] = round(time.perf_counter() - started, 4)
        return {
            "status": "COMPLETED",
            "hd_core_pipeline": "RUN_GATES_PASSED",
            "selected_route": "SAFE_BASELINE",
            "runtime_record": runtime_record,
            "baseline_result": safe_result,
            "baseline_output_path": str(baseline_path.resolve()),
            "final_output_path": str(baseline_path.resolve()),
            "final_output_pixel_sha256": safe_result["final_output_pixel_sha256"],
            "candidate_risk": None,
            "final_risk": safe_result["final_risk"],
        }

    candidate_root = root / "candidate_runtime"
    candidate_input = candidate_root / "safe_baseline_input.png"
    candidate_output = candidate_root / "candidate_output.png"
    final_output = root / "delivery" / "hd_core.png"
    candidate_root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(baseline_path, candidate_input)

    try:
        candidate(candidate_input, candidate_output)
        if not candidate_output.is_file() or candidate_output.stat().st_size == 0:
            candidate_risk = _fallback_risk("CANDIDATE_RESULT_MISSING")
        else:
            candidate_risk = assess_baseline_risk(source, baseline_path, candidate_output)
    except Exception as exc:  # Candidate failures are required to fail closed.
        candidate_risk = _fallback_risk(f"CANDIDATE_EXCEPTION:{type(exc).__name__}")

    finalized = finalize_with_baseline_fallback(
        baseline_path,
        candidate_output,
        final_output,
        candidate_risk,
    )
    final_risk = assess_baseline_risk(source, baseline_path, final_output)
    if final_risk.get("status") != "PASS":
        final_output.unlink(missing_ok=True)
        raise HDCoreSafeBaseError(
            "FINAL_RISK_GATE_FAILED",
            "candidate_pipeline:output_verify",
            str(final_risk.get("reasons", [])),
        )

    fallback_applied = bool(finalized["fallback_applied"])
    reasons = candidate_risk.get("reasons") or []
    runtime_record.update(
        {
            "decision": "FALLBACK" if fallback_applied else "ACCEPT",
            "fallback_reason": ";".join(str(reason) for reason in reasons) if fallback_applied else "NONE",
            "elapsed_time": round(time.perf_counter() - started, 4),
        }
    )
    return {
        "status": "COMPLETED",
        "hd_core_pipeline": "RUN_GATES_PASSED",
        "selected_route": finalized["selected_route"],
        "runtime_record": runtime_record,
        "baseline_result": safe_result,
        "baseline_output_path": str(baseline_path.resolve()),
        "final_output_path": finalized["final_output_path"],
        "final_output_pixel_sha256": finalized["final_pixel_sha256"],
        "candidate_risk": candidate_risk,
        "final_risk": final_risk,
    }


__all__ = ["CandidateEnhancer", "process_hd_core_pipeline"]
