"""Internal HDDE high-definition core building blocks."""

from .safe_base import (
    HDCoreSafeBaseError,
    assess_baseline_risk,
    diagnose_degradation,
    finalize_with_baseline_fallback,
    process_hd_core_safe_base,
)
from .pipeline import CandidateEnhancer, process_hd_core_pipeline
from .candidate_framework import (
    CandidateDefinition,
    CandidateExecutionRequest,
    CandidateFrameworkError,
    E102EvaluationContext,
    build_candidate_identity,
    build_comparison_surface,
    build_run_identity,
    run_4k_candidate,
)

__all__ = [
    "HDCoreSafeBaseError",
    "assess_baseline_risk",
    "diagnose_degradation",
    "finalize_with_baseline_fallback",
    "process_hd_core_safe_base",
    "CandidateEnhancer",
    "process_hd_core_pipeline",
    "CandidateDefinition",
    "CandidateExecutionRequest",
    "CandidateFrameworkError",
    "E102EvaluationContext",
    "build_candidate_identity",
    "build_comparison_surface",
    "build_run_identity",
    "run_4k_candidate",
]
