"""Experimental E4K-04 source-domain restoration Candidate V2.

The operator uses JPEG luma quantization metadata to apply deterministic,
non-generative DCT coefficient shrinkage on Source pixels before any resize.
The restored Source is then aligned to the existing Pillow LANCZOS comparison
surface and passed through the frozen V1 bounded safety system.  Unsupported,
uncertain, non-finite, or uncalibrated inputs fail closed to the baseline.

This module is isolated from the formal 4K route, API, Task/Result, Delivery,
and UI.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np
from PIL import Image, ImageOps

from .bounded_restoration import (
    ACTIVE,
    NO_OP,
    SAFE_PROFILE,
    SUPPORTED_TARGET_DEGRADATION,
    apply_bounded_residual,
    attach_baseline_alpha,
    build_degradation_profile,
    build_protection_scale,
    build_threshold_provenance,
)
from .candidate_framework import PRODUCT, CandidateDefinition, CandidateExecutionRequest


ALGORITHM_ID = "HDDE_SOURCE_DOMAIN_RESTORATION"
ALGORITHM_VERSION = "V2"
PROFILE_ID = "SOURCE_DOMAIN_RESTORATION_SAFE_PROFILE_V2"
TARGET_DEGRADATION_FAMILY = "JPEG_QUANTIZATION_ARTIFACT"
OPERATOR_TYPE = "QUANTIZATION_AWARE_SOURCE_LUMA_DCT_SHRINKAGE"
DEGRADATION_PROFILE_VERSION = "SOURCE_DEGRADATION_PROFILE_V2"
RESTORATION_EVIDENCE_MASK_VERSION = "RESTORATION_EVIDENCE_MASK_V2"
THRESHOLD_PROVENANCE_VERSION = "THRESHOLD_PROVENANCE_V2"
CALIBRATION_AUTHORITY_BINDING_VERSION = "CALIBRATION_AUTHORITY_BINDING_V1"
QUALIFICATION_RULE_VERSION = "V2_ALL_ROWS_POSITIVE_AND_SAFE_THEN_WORST_CASE_V1"
RUNTIME_CALIBRATION_AUTHORIZATION_GATE_VERSION = (
    "RUNTIME_CALIBRATION_AUTHORIZATION_GATE_V1"
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pixel_sha256(array: np.ndarray) -> str:
    values = np.ascontiguousarray(array)
    payload = values.tobytes() + str(values.dtype).encode("ascii") + repr(values.shape).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _round(value: float, digits: int = 8) -> float:
    return round(float(value), digits)


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _json_finite(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_finite(item) for item in value]
    if isinstance(value, (float, np.floating)) and not math.isfinite(float(value)):
        return f"NONFINITE:{value!r}"
    return value


@dataclass(frozen=True)
class SourceDomainRestorationProfile:
    """The single profile frozen before V2 Holdout execution."""

    profile_id: str = PROFILE_ID
    target_degradation_family: str = TARGET_DEGRADATION_FAMILY
    dct_soft_threshold_ratio: float = 0.03
    source_luma_delta_budget: float = 1.0

    def canonical_parameters(
        self, *, calibration_authority: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        values = _json_finite(asdict(self))
        values["threshold_provenance"] = build_v2_threshold_provenance(
            self, calibration_authority=calibration_authority
        )
        values["bounded_safety_profile"] = SAFE_PROFILE.canonical_parameters()
        return values


SAFE_PROFILE_V2 = SourceDomainRestorationProfile()


_V2_THRESHOLD_SPECS = {
    "dct_soft_threshold_ratio": {
        "unit": "jpeg_quantization_step_ratio",
        "source_type": "CONTROL_CALIBRATION",
        "source_evidence": "V2_MILD_AND_MODERATE_KNOWN_JPEG_DEGRADATION_GT_DIRECTION",
        "calibration_dataset": "E4K04_V2_CONTROLLED_SYNTHETIC_JPEG_PROBES",
        "calibration_method": "PRE_HOLDOUT_GRID_THEN_SINGLE_PROFILE_FREEZE",
        "allowed_range": [0.03, 0.03],
    },
    "source_luma_delta_budget": {
        "unit": "source_uint8_luma_level",
        "source_type": "CONTROL_CALIBRATION",
        "source_evidence": "V2_CONTROLLED_SOURCE_DELTA_AND_SAFETY_RESULTS",
        "calibration_dataset": "E4K04_V2_CONTROLLED_SYNTHETIC_JPEG_PROBES",
        "calibration_method": "MINIMUM_INTEGER_EFFECTIVE_SOURCE_DELTA_BOUND",
        "allowed_range": [1.0, 1.0],
    },
}


def build_calibration_authority_binding(
    calibration_result: Mapping[str, Any],
    *,
    calibration_artifact_sha256: str,
) -> dict[str, Any]:
    """Bind execution authorization to one concrete calibration artifact.

    A failed calibration can have a valid, traceable binding while still granting
    no execution authority.  This distinction prevents a code default from being
    mistaken for a calibrated parameter.
    """

    binding_failures: list[str] = []
    authorization_failures: list[str] = []
    sha = str(calibration_artifact_sha256 or "").lower()
    if len(sha) != 64 or any(character not in "0123456789abcdef" for character in sha):
        binding_failures.append("CALIBRATION_ARTIFACT_SHA256_INVALID")

    calibration_status = calibration_result.get("status")
    if calibration_status not in {"PASS", "FAIL"}:
        binding_failures.append("CALIBRATION_STATUS_INVALID")

    raw_grid = calibration_result.get("parameter_grid")
    grid: list[float] = []
    if not isinstance(raw_grid, list) or not raw_grid:
        binding_failures.append("CALIBRATION_GRID_INVALID")
    else:
        try:
            grid = [float(value) for value in raw_grid]
        except (TypeError, ValueError):
            binding_failures.append("CALIBRATION_GRID_INVALID")
        if grid and (not all(math.isfinite(value) for value in grid) or len(set(grid)) != len(grid)):
            binding_failures.append("CALIBRATION_GRID_INVALID")

    ratio_summaries = calibration_result.get("ratio_summaries")
    summary_qualified_ratios: list[float] = []
    if not isinstance(ratio_summaries, list) or len(ratio_summaries) != len(grid):
        binding_failures.append("CALIBRATION_RATIO_SUMMARIES_INVALID")
    else:
        try:
            summary_qualified_ratios = sorted(
                float(item["ratio"])
                for item in ratio_summaries
                if item.get("all_post_bounding_positive") is True
                and item.get("all_final_safety_pass") is True
            )
            summary_ratios = sorted(float(item["ratio"]) for item in ratio_summaries)
            if summary_ratios != sorted(grid):
                binding_failures.append("CALIBRATION_RATIO_SUMMARY_GRID_MISMATCH")
        except (KeyError, TypeError, ValueError):
            binding_failures.append("CALIBRATION_RATIO_SUMMARIES_INVALID")

    grid_rows = calibration_result.get("all_grid_rows")
    row_qualified_ratios: list[float] = []
    ratio_qualifications: list[dict[str, Any]] = []
    if not isinstance(grid_rows, list) or not grid_rows:
        binding_failures.append("CALIBRATION_GRID_ROWS_INVALID")
    else:
        for ratio in grid:
            rows: list[Mapping[str, Any]] = []
            for row in grid_rows:
                if not isinstance(row, Mapping):
                    binding_failures.append("CALIBRATION_GRID_ROW_INVALID")
                    continue
                row_ratio = _finite_float(row.get("ratio"))
                if row_ratio == ratio:
                    rows.append(row)
            rows_positive = bool(rows) and all(
                row.get("post_bounding_recovery_direction")
                == "POSITIVE_RECOVERY_DIRECTION"
                for row in rows
            )
            rows_safe = bool(rows) and all(
                isinstance(row.get("final_safety"), Mapping)
                and row["final_safety"].get("status") == "PASS"
                for row in rows
            )
            summary_pass = ratio in summary_qualified_ratios
            qualification_pass = rows_positive and rows_safe and summary_pass
            if not rows:
                binding_failures.append(
                    f"CALIBRATION_GRID_RATIO_ROWS_MISSING:{ratio}"
                )
            if rows_positive and rows_safe:
                row_qualified_ratios.append(ratio)
            ratio_qualifications.append(
                {
                    "ratio": ratio,
                    "grid_row_count": len(rows),
                    "all_grid_rows_positive": rows_positive,
                    "all_grid_rows_safety_pass": rows_safe,
                    "ratio_summary_qualification_pass": summary_pass,
                    "qualification": "PASS" if qualification_pass else "FAIL",
                }
            )
    if sorted(summary_qualified_ratios) != sorted(row_qualified_ratios):
        binding_failures.append("CALIBRATION_ROW_SUMMARY_QUALIFICATION_MISMATCH")
    qualified_ratios = sorted(
        item["ratio"]
        for item in ratio_qualifications
        if item["qualification"] == "PASS"
    )

    selected_raw = calibration_result.get("selected_ratio")
    selected_ratio: float | None = None
    if selected_raw is not None:
        selected_ratio = _finite_float(selected_raw)
        if selected_ratio is None:
            authorization_failures.append("SELECTED_RATIO_NONFINITE_OR_INVALID")

    if calibration_status != "PASS":
        authorization_failures.append("CALIBRATION_STATUS_NOT_PASS")
    if selected_ratio is None:
        authorization_failures.append("SELECTED_RATIO_NULL")
    elif selected_ratio not in grid:
        authorization_failures.append("SELECTED_RATIO_NOT_IN_CALIBRATION_GRID")
    elif selected_ratio not in qualified_ratios:
        authorization_failures.append("SELECTED_RATIO_NOT_QUALIFIED")

    formal_ratio = calibration_result.get("formal_ratio")
    try:
        formal_ratio_value = float(formal_ratio)
    except (TypeError, ValueError):
        formal_ratio_value = None
        binding_failures.append("FORMAL_RATIO_INVALID")
    if (
        selected_ratio is not None
        and formal_ratio_value is not None
        and selected_ratio != formal_ratio_value
    ):
        authorization_failures.append("SELECTED_RATIO_NOT_FORMAL_RATIO")

    execution_authorized = not binding_failures and not authorization_failures
    if calibration_status == "FAIL" and execution_authorized:
        binding_failures.append("FAILED_CALIBRATION_CANNOT_AUTHORIZE_EXECUTION")
        execution_authorized = False
    return {
        "version": CALIBRATION_AUTHORITY_BINDING_VERSION,
        "binding_status": "PASS" if not binding_failures else "FAIL",
        "calibration_artifact_sha256": sha,
        "calibration_status": calibration_status,
        "selected_ratio": selected_ratio,
        "verified_calibration_grid": grid,
        "qualified_ratios": qualified_ratios,
        "ratio_qualifications": ratio_qualifications,
        "qualification_rule_version": QUALIFICATION_RULE_VERSION,
        "binding_failures": binding_failures,
        "authorization_failures": sorted(set(authorization_failures)),
        "candidate_execution_authorized": execution_authorized,
    }


def build_v2_threshold_provenance(
    profile: SourceDomainRestorationProfile = SAFE_PROFILE_V2,
    *,
    calibration_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    default = SourceDomainRestorationProfile()
    thresholds: list[dict[str, Any]] = []
    failures: list[str] = []
    authority = dict(calibration_authority or {})
    selected_ratio = _finite_float(authority.get("selected_ratio"))
    verified_grid = [
        value
        for item in (authority.get("verified_calibration_grid") or [])
        if (value := _finite_float(item)) is not None
    ]
    qualified_ratios = [
        value
        for item in (authority.get("qualified_ratios") or [])
        if (value := _finite_float(item)) is not None
    ]
    bound_sha = str(authority.get("calibration_artifact_sha256") or "").lower()
    authority_valid = (
        authority.get("version") == CALIBRATION_AUTHORITY_BINDING_VERSION
        and authority.get("binding_status") == "PASS"
        and authority.get("calibration_status") == "PASS"
        and authority.get("qualification_rule_version") == QUALIFICATION_RULE_VERSION
        and len(bound_sha) == 64
        and not any(character not in "0123456789abcdef" for character in bound_sha)
        and authority.get("binding_failures") == []
        and authority.get("authorization_failures") == []
        and selected_ratio is not None
        and selected_ratio in verified_grid
        and selected_ratio in qualified_ratios
        and any(
            _finite_float(item.get("ratio")) == selected_ratio
            and item.get("qualification") == "PASS"
            for item in (authority.get("ratio_qualifications") or [])
            if isinstance(item, Mapping)
        )
        and authority.get("candidate_execution_authorized") is True
    )
    for name, spec in _V2_THRESHOLD_SPECS.items():
        value = getattr(profile, name)
        finite = (
            isinstance(value, (int, float))
            and math.isfinite(float(value))
        )
        low, high = spec["allowed_range"]
        in_declared_range = finite and float(low) <= float(value) <= float(high)
        if name == "dct_soft_threshold_ratio":
            parameter_authorized = (
                selected_ratio is not None
                and isinstance(selected_ratio, (int, float))
                and math.isfinite(float(selected_ratio))
                and finite
                and float(value) == float(selected_ratio)
            )
        else:
            parameter_authorized = finite and float(value) == float(getattr(default, name))
        valid = authority_valid and in_declared_range and parameter_authorized
        if not authority_valid:
            source_evidence = "CALIBRATION_AUTHORITY_NOT_GRANTED"
        elif not parameter_authorized:
            source_evidence = "PARAMETER_NOT_AUTHORIZED_BY_SELECTED_CALIBRATION"
        else:
            source_evidence = spec["source_evidence"]
        item = {
            "threshold_name": name,
            "threshold_value": _json_finite(value),
            "unit": spec["unit"],
            "source_type": spec["source_type"],
            "source_evidence": source_evidence,
            "calibration_dataset": spec["calibration_dataset"],
            "calibration_method": spec["calibration_method"],
            "allowed_range": list(spec["allowed_range"]),
            "status": "VALID" if valid else "NEED_CALIBRATION",
        }
        thresholds.append(item)
        if not valid:
            failures.append(f"THRESHOLD_NEEDS_CALIBRATION:{name}")
        if item["source_type"] == "SOURCE_DERIVED_RUNTIME_STATISTIC":
            failures.append(f"FIXED_THRESHOLD_MISLABELED_SOURCE_DERIVED:{name}")
    bounded = build_threshold_provenance(SAFE_PROFILE)
    if bounded["status"] != "PASS":
        failures.append("BOUNDED_SAFETY_THRESHOLD_PROVENANCE_INVALID")
    return {
        "version": THRESHOLD_PROVENANCE_VERSION,
        "status": "PASS" if not failures else "NEED_CALIBRATION",
        "candidate_execution_authorized": not failures and authority_valid,
        "uncalibrated_threshold_count": sum(
            item["status"] != "VALID" for item in thresholds
        )
        + int(bounded["status"] != "PASS"),
        "failures": failures,
        "thresholds": thresholds,
        "calibration_authority_binding": _json_finite(authority),
        "bounded_safety_threshold_provenance": bounded,
    }


def source_domain_candidate_definition(
    *,
    profile: SourceDomainRestorationProfile = SAFE_PROFILE_V2,
    calibration_authority: Mapping[str, Any] | None = None,
) -> CandidateDefinition:
    return CandidateDefinition(
        algorithm_id=ALGORITHM_ID,
        algorithm_version=ALGORITHM_VERSION,
        parameters={
            "model_plan": "SELF_DEVELOPED_SOURCE_DOMAIN_RESTORATION",
            "external_enhancement_model": "NONE",
            "formal_baseline": "PILLOW_LANCZOS",
            "target_degradation_family": TARGET_DEGRADATION_FAMILY,
            "operator_type": OPERATOR_TYPE,
            "operator_parameters": profile.canonical_parameters(
                calibration_authority=calibration_authority
            ),
            "candidate_execution_authorized": build_v2_threshold_provenance(
                profile, calibration_authority=calibration_authority
            )["candidate_execution_authorized"],
            "degradation_profile": DEGRADATION_PROFILE_VERSION,
            "restoration_evidence_mask": RESTORATION_EVIDENCE_MASK_VERSION,
            "residual_contract": "BOUNDED_RESIDUAL_CONTRACT_V1",
            "high_frequency_budget": "HIGH_FREQUENCY_BUDGET_V1",
            "overshoot_policy": "ZERO_NEW_LOCAL_EXTREMA",
            "halo_policy": "E1_02_RAW_AND_FINAL_DETECTION_PLUS_BOUNDING",
            "protected_structure_policy": "PROTECTED_STRUCTURE_MASK_V1",
            "color_policy": "LUMA_RESIDUAL_ONLY_ZERO_CHROMA_DIFFERENCE_DRIFT",
            "alpha_policy": "SAFE_BASE_ALPHA_BYTE_IDENTITY",
            "backend": "NUMPY_OPENCV_PILLOW_CPU",
            "precision": "FLOAT32_ANALYSIS_UINT8_DETERMINISTIC_OUTPUT",
            "unsupported_or_uncertain": NO_OP,
        },
        backend_identity="NUMPY_OPENCV_PILLOW_CPU",
        precision_identity="FLOAT32_ANALYSIS_UINT8_DETERMINISTIC_OUTPUT",
        candidate_class=PRODUCT,
        model_id="NONE",
        model_version="NONE",
        model_sha256="NONE",
        normalization={
            "version": "SOURCE_DOMAIN_RESTORATION_NORMALIZATION_V2",
            "operations": [
                "SOURCE_EXIF_TRANSPOSE",
                "EXPLICIT_RGB_TO_YCBCR",
                "SOURCE_LUMA_DCT_RESTORATION",
                "EXPLICIT_YCBCR_TO_RGB",
                "PILLOW_LANCZOS_COMPARISON_ALIGNMENT",
            ],
            "implicit_resize": False,
            "implicit_crop_or_padding": False,
            "implicit_color_conversion": False,
        },
        color_profile_policy="PRESERVE_BASELINE_PROFILE",
        control_fixture_only=False,
    )


def validate_runtime_calibration_authorization(
    *,
    calibration_artifact_path: str | Path | None,
    calibration_authority: Mapping[str, Any] | None,
    threshold_provenance: Mapping[str, Any] | None,
    candidate_id: str | None,
    profile: SourceDomainRestorationProfile = SAFE_PROFILE_V2,
) -> dict[str, Any]:
    """Rebuild execution authority from the bound calibration artifact.

    Caller-declared PASS fields are evidence inputs, never authority.  The gate
    reads the actual JSON artifact, hashes it, rebuilds qualification and
    provenance, and requires exact agreement before the Source operator can run.
    """

    failures: list[str] = []
    actual_sha: str | None = None
    actual_calibration: Mapping[str, Any] | None = None
    artifact = Path(calibration_artifact_path) if calibration_artifact_path else None
    if artifact is None:
        failures.append("CALIBRATION_ARTIFACT_REQUIRED")
    elif not artifact.is_file():
        failures.append("CALIBRATION_ARTIFACT_NOT_FILE")
    else:
        try:
            loaded = json.loads(artifact.read_text(encoding="utf-8"))
            if not isinstance(loaded, Mapping):
                raise ValueError("CALIBRATION_ARTIFACT_ROOT_NOT_OBJECT")
            actual_calibration = loaded
            actual_sha = _sha256_file(artifact)
        except Exception as exc:
            failures.append(
                f"CALIBRATION_ARTIFACT_INVALID:{type(exc).__name__}:{exc}"
            )

    declared_authority = dict(calibration_authority or {})
    declared_provenance = dict(threshold_provenance or {})
    if calibration_authority is None:
        failures.append("CALIBRATION_AUTHORITY_REQUIRED")
    if threshold_provenance is None:
        failures.append("THRESHOLD_PROVENANCE_REQUIRED")

    try:
        if actual_calibration is None or actual_sha is None:
            expected_authority = build_calibration_authority_binding(
                {}, calibration_artifact_sha256=""
            )
        else:
            expected_authority = build_calibration_authority_binding(
                actual_calibration,
                calibration_artifact_sha256=actual_sha,
            )
    except Exception as exc:
        failures.append(
            f"CALIBRATION_AUTHORITY_REBUILD_FAILED:{type(exc).__name__}:{exc}"
        )
        expected_authority = build_calibration_authority_binding(
            {}, calibration_artifact_sha256=""
        )
    expected_provenance = build_v2_threshold_provenance(
        profile,
        calibration_authority=expected_authority,
    )
    expected_candidate_id = source_domain_candidate_definition(
        profile=profile,
        calibration_authority=expected_authority,
    ).candidate_id

    bound_sha = str(declared_authority.get("calibration_artifact_sha256") or "")
    if actual_sha is None or bound_sha != actual_sha:
        failures.append("CALIBRATION_SHA_MISMATCH")
    if declared_authority != expected_authority:
        failures.append("CALIBRATION_AUTHORITY_BINDING_MISMATCH")
    if declared_authority.get("qualification_rule_version") != QUALIFICATION_RULE_VERSION:
        failures.append("QUALIFICATION_RULE_VERSION_MISMATCH")
    if expected_authority.get("calibration_status") != "PASS":
        failures.append("CALIBRATION_STATUS_NOT_PASS")

    selected_ratio = _finite_float(expected_authority.get("selected_ratio"))
    if selected_ratio is None:
        failures.append("SELECTED_RATIO_NULL_OR_NONFINITE")
    else:
        if selected_ratio not in expected_authority.get("verified_calibration_grid", []):
            failures.append("SELECTED_RATIO_NOT_IN_GRID")
        if selected_ratio not in expected_authority.get("qualified_ratios", []):
            failures.append("SELECTED_RATIO_NOT_IN_QUALIFIED_RATIOS")
        if not any(
            _finite_float(item.get("ratio")) == selected_ratio
            and item.get("qualification") == "PASS"
            for item in expected_authority.get("ratio_qualifications", [])
            if isinstance(item, Mapping)
        ):
            failures.append("SELECTED_RATIO_QUALIFICATION_NOT_PASS")

    if expected_authority.get("candidate_execution_authorized") is not True:
        failures.append("CALIBRATION_EVIDENCE_DOES_NOT_AUTHORIZE_EXECUTION")
    if declared_authority.get("candidate_execution_authorized") is not True:
        failures.append("DECLARED_EXECUTION_AUTHORIZATION_NOT_TRUE")
    if declared_provenance != expected_provenance:
        failures.append("THRESHOLD_PROVENANCE_BINDING_MISMATCH")
    if (
        expected_provenance.get("status") != "PASS"
        or expected_provenance.get("candidate_execution_authorized") is not True
        or any(
            item.get("status") != "VALID"
            for item in expected_provenance.get("thresholds", [])
        )
    ):
        failures.append("THRESHOLD_PROVENANCE_NOT_VALID")
    if candidate_id != expected_candidate_id:
        failures.append("CANDIDATE_IDENTITY_BINDING_MISMATCH")

    unique_failures = sorted(set(failures))
    authorized = not unique_failures
    return {
        "version": RUNTIME_CALIBRATION_AUTHORIZATION_GATE_VERSION,
        "status": "PASS" if authorized else "FAIL",
        "failures": unique_failures,
        "calibration_artifact_path": str(artifact) if artifact else None,
        "actual_calibration_sha256": actual_sha,
        "bound_calibration_artifact_sha256": bound_sha or None,
        "calibration_status": expected_authority.get("calibration_status"),
        "selected_ratio": selected_ratio,
        "verified_calibration_grid": expected_authority.get(
            "verified_calibration_grid", []
        ),
        "qualified_ratios": expected_authority.get("qualified_ratios", []),
        "ratio_qualifications": expected_authority.get("ratio_qualifications", []),
        "qualification_rule_version": expected_authority.get(
            "qualification_rule_version"
        ),
        "threshold_provenance_status": expected_provenance.get("status"),
        "expected_candidate_id": expected_candidate_id,
        "bound_candidate_id": candidate_id,
        "candidate_execution_authorized": authorized,
        "expected_calibration_authority": expected_authority,
        "expected_threshold_provenance": expected_provenance,
    }


def _open_source(path: Path) -> tuple[Image.Image, list[float] | None, str | None]:
    with Image.open(path) as opened:
        opened.load()
        decoded_format = opened.format
        quantization = getattr(opened, "quantization", None) or {}
        table = quantization.get(0)
        luma_table = [float(value) for value in table] if table and len(table) == 64 else None
        image = ImageOps.exif_transpose(opened).convert("RGB")
    return image, luma_table, decoded_format


def build_source_degradation_profile(path: str | Path) -> dict[str, Any]:
    source_path = Path(path)
    source_image, luma_table, decoded_format = _open_source(source_path)
    inherited = build_degradation_profile(source_path)
    direct_jpeg = decoded_format == "JPEG" and luma_table is not None
    status = SUPPORTED_TARGET_DEGRADATION if direct_jpeg else inherited["status"]
    if not direct_jpeg:
        status = "UNSUPPORTED" if inherited["status"] == "UNSUPPORTED" else "NEED_PROOF"
    activation = ACTIVE if direct_jpeg else NO_OP
    return {
        "profile_version": DEGRADATION_PROFILE_VERSION,
        "target_degradation_family": TARGET_DEGRADATION_FAMILY,
        "status": status,
        "restoration_activation": activation,
        "reason": (
            "JPEG_DECODE_AND_LUMA_QUANTIZATION_TABLE_DIRECTLY_CONFIRMED"
            if direct_jpeg
            else "DIRECT_JPEG_QUANTIZATION_EVIDENCE_NOT_AVAILABLE"
        ),
        "input_color_order": "PIL_RGB",
        "working_color_space": "PIL_YCBCR_LUMA_DCT",
        "working_dtype": "FLOAT32",
        "working_range": "0_255_CENTERED_TO_MINUS128_PLUS127_FOR_DCT",
        "source_width": source_image.width,
        "source_height": source_image.height,
        "compression_evidence": {
            "decoded_format": decoded_format,
            "luma_quantization_table_valid": luma_table is not None,
            "luma_quantization_mean": (
                _round(float(np.mean(luma_table)), 8) if luma_table else None
            ),
            "luma_quantization_max": max(luma_table) if luma_table else None,
        },
        "structured_risk_evidence": {
            "text_like_roi_ratio": (
                (inherited.get("text_like_risk") or {}).get("text_mask_ratio")
            ),
            "strong_edge_ratio": (
                (inherited.get("edge_evidence") or {}).get("canny_edge_fraction")
            ),
            "protected_structure_ratio": "MEASURED_ON_COMPARISON_SURFACE_AT_RUNTIME",
            "color_risk": "LUMA_ONLY_FINAL_RESIDUAL",
            "alpha_risk": "ALPHA_BYPASSED",
        },
        "inherited_source_probes": inherited,
    }


def quantization_aware_luma_restore(
    source_luma: np.ndarray,
    luma_quantization_table: list[float] | np.ndarray,
    *,
    soft_threshold_ratio: float,
    source_luma_delta_budget: float,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Restore one Source luma plane using only decoded pixels and JPEG metadata."""

    luma = np.asarray(source_luma, dtype=np.float32)
    quant = np.asarray(luma_quantization_table, dtype=np.float32)
    if luma.ndim != 2 or quant.shape != (64,):
        raise ValueError("SOURCE_LUMA_OR_QUANTIZATION_TABLE_INVALID")
    if not np.isfinite(luma).all() or not np.isfinite(quant).all():
        raise ValueError("NONFINITE_SOURCE_OR_QUANTIZATION_TABLE")
    if not math.isfinite(float(soft_threshold_ratio)) or not math.isfinite(
        float(source_luma_delta_budget)
    ):
        raise ValueError("NONFINITE_OPERATOR_PARAMETER")
    if soft_threshold_ratio <= 0 or source_luma_delta_budget <= 0:
        raise ValueError("NONPOSITIVE_OPERATOR_PARAMETER")

    height, width = luma.shape
    padded_height = int(math.ceil(height / 8.0) * 8)
    padded_width = int(math.ceil(width / 8.0) * 8)
    padded = cv2.copyMakeBorder(
        luma,
        0,
        padded_height - height,
        0,
        padded_width - width,
        cv2.BORDER_REFLECT_101,
    )
    restored = np.empty_like(padded, dtype=np.float32)
    evidence = np.zeros_like(padded, dtype=np.float32)
    quant_matrix = quant.reshape(8, 8)
    yy, xx = np.indices((8, 8), dtype=np.float32)
    frequency_weight = 0.25 + 0.75 * ((xx + yy) / 14.0)
    threshold = quant_matrix * float(soft_threshold_ratio) * frequency_weight
    threshold[0, 0] = 0.0
    modified_coefficient_count = 0
    evidence_block_count = 0
    total_blocks = 0
    for y0 in range(0, padded_height, 8):
        for x0 in range(0, padded_width, 8):
            block = padded[y0 : y0 + 8, x0 : x0 + 8] - 128.0
            coefficients = cv2.dct(block)
            shrunk = np.sign(coefficients) * np.maximum(
                np.abs(coefficients) - threshold, 0.0
            )
            shrunk[0, 0] = coefficients[0, 0]
            changed = np.abs(shrunk - coefficients) > 1e-7
            modified_coefficient_count += int(np.count_nonzero(changed))
            reconstructed = cv2.idct(shrunk) + 128.0
            delta = np.clip(
                reconstructed - padded[y0 : y0 + 8, x0 : x0 + 8],
                -float(source_luma_delta_budget),
                float(source_luma_delta_budget),
            )
            restored[y0 : y0 + 8, x0 : x0 + 8] = (
                padded[y0 : y0 + 8, x0 : x0 + 8] + delta
            )
            block_evidence = changed.any() and bool(np.any(np.abs(delta) > 1e-7))
            if block_evidence:
                evidence[y0 : y0 + 8, x0 : x0 + 8] = 1.0
                evidence_block_count += 1
            total_blocks += 1
    restored = np.clip(restored[:height, :width], 0.0, 255.0)
    evidence = evidence[:height, :width]
    delta = restored - luma
    if not np.isfinite(restored).all() or not np.isfinite(delta).all():
        raise ValueError("NONFINITE_OPERATOR_OUTPUT")
    record = {
        "operator_type": OPERATOR_TYPE,
        "generative": False,
        "sharpening_operator": False,
        "source_direct": True,
        "jpeg_dct_block_size": 8,
        "soft_threshold_ratio": soft_threshold_ratio,
        "source_luma_delta_budget": source_luma_delta_budget,
        "source_luma_delta_min": _round(np.min(delta), 8),
        "source_luma_delta_max": _round(np.max(delta), 8),
        "source_luma_delta_mean_abs": _round(np.mean(np.abs(delta)), 10),
        "modified_coefficient_count": modified_coefficient_count,
        "total_block_count": total_blocks,
        "evidence_block_count": evidence_block_count,
        "evidence_block_fraction": _round(evidence_block_count / max(total_blocks, 1), 8),
    }
    return restored, evidence, record


def build_raw_source_proposal(
    source_path: str | Path,
    baseline_rgb: np.ndarray,
    *,
    profile: SourceDomainRestorationProfile = SAFE_PROFILE_V2,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    source_file = Path(source_path)
    source_image, luma_table, decoded_format = _open_source(source_file)
    if decoded_format != "JPEG" or luma_table is None:
        raise ValueError("DIRECT_JPEG_QUANTIZATION_EVIDENCE_REQUIRED")
    source_rgb = np.asarray(source_image, dtype=np.uint8)
    ycbcr = source_image.convert("YCbCr")
    y_plane, _cb_plane, _cr_plane = ycbcr.split()
    source_luma = np.asarray(y_plane, dtype=np.float32)
    restored_luma, source_evidence, operator_record = quantization_aware_luma_restore(
        source_luma,
        luma_table,
        soft_threshold_ratio=profile.dct_soft_threshold_ratio,
        source_luma_delta_budget=profile.source_luma_delta_budget,
    )
    restored_luma_u8 = np.clip(np.rint(restored_luma), 0, 255).astype(np.uint8)
    source_luma_u8 = np.asarray(y_plane, dtype=np.uint8)
    source_luma_delta = (
        restored_luma_u8.astype(np.int16) - source_luma_u8.astype(np.int16)
    )
    restored_source_rgb = np.clip(
        source_rgb.astype(np.int16) + source_luma_delta[..., None], 0, 255
    ).astype(np.uint8)
    restored_source = Image.fromarray(restored_source_rgb, "RGB")
    height, width = np.asarray(baseline_rgb).shape[:2]
    proposal_rgb = np.asarray(
        restored_source.resize((width, height), Image.Resampling.LANCZOS),
        dtype=np.uint8,
    )
    baseline = np.asarray(baseline_rgb, dtype=np.uint8)
    proposal_luma = cv2.cvtColor(proposal_rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    baseline_luma = cv2.cvtColor(baseline, cv2.COLOR_RGB2GRAY).astype(np.float32)
    evidence_target = cv2.resize(
        source_evidence,
        (width, height),
        interpolation=cv2.INTER_NEAREST,
    )
    raw_residual = (proposal_luma - baseline_luma) * evidence_target
    if not np.isfinite(raw_residual).all() or not np.isfinite(evidence_target).all():
        raise ValueError("NONFINITE_RAW_PROPOSAL")
    operator_record.update(
        {
            "proposal_source_binding": _sha256_file(source_file),
            "operator_parameters": {
                "dct_soft_threshold_ratio": profile.dct_soft_threshold_ratio,
                "source_luma_delta_budget": profile.source_luma_delta_budget,
            },
            "proposal_sha256": _pixel_sha256(proposal_rgb),
            "alignment_surface": "PILLOW_LANCZOS_TARGET_SIZE",
            "target_width": width,
            "target_height": height,
            "raw_residual_min": _round(np.min(raw_residual), 8),
            "raw_residual_max": _round(np.max(raw_residual), 8),
            "raw_residual_mean_abs": _round(np.mean(np.abs(raw_residual)), 10),
            "restoration_evidence_mask": {
                "version": RESTORATION_EVIDENCE_MASK_VERSION,
                "evidence_types": [
                    "DIRECT_JPEG_LUMA_QUANTIZATION_TABLE",
                    "SOURCE_DCT_COEFFICIENT_RESPONSE",
                ],
                "evidence_pixel_fraction": _round(np.mean(evidence_target > 0), 8),
                "insufficient_evidence_strength": 0.0,
            },
            "input_color_order": "RGB",
            "working_color_space": "YCbCr_LUMA",
            "working_dtype": "FLOAT32",
            "working_range": "0_255",
        }
    )
    return proposal_rgb, raw_residual, evidence_target, operator_record


def restore_source_domain_candidate(
    source_path: str | Path,
    baseline_path: str | Path,
    output_path: str | Path,
    *,
    record_path: str | Path | None = None,
    profile: SourceDomainRestorationProfile = SAFE_PROFILE_V2,
    calibration_authority: Mapping[str, Any] | None = None,
    calibration_artifact_path: str | Path | None = None,
    threshold_provenance: Mapping[str, Any] | None = None,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    source_file = Path(source_path)
    baseline_file = Path(baseline_path)
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    source_before = _sha256_file(source_file)
    baseline_before = _sha256_file(baseline_file)
    provenance = dict(
        threshold_provenance
        or build_v2_threshold_provenance(
            profile, calibration_authority=calibration_authority
        )
    )
    runtime_authorization = validate_runtime_calibration_authorization(
        calibration_artifact_path=calibration_artifact_path,
        calibration_authority=calibration_authority,
        threshold_provenance=threshold_provenance,
        candidate_id=candidate_id,
        profile=profile,
    )
    degradation: dict[str, Any] | None = None
    raw_proposal_path: Path | None = None
    try:
        if (
            runtime_authorization["status"] != "PASS"
            or runtime_authorization["candidate_execution_authorized"] is not True
        ):
            raise ValueError(
                "RUNTIME_CALIBRATION_AUTHORIZATION_FAILED:"
                + ",".join(runtime_authorization["failures"])
            )
        degradation = build_source_degradation_profile(source_file)
        if degradation["status"] != SUPPORTED_TARGET_DEGRADATION:
            shutil.copyfile(baseline_file, output_file)
            record = {
                "algorithm_id": ALGORITHM_ID,
                "algorithm_version": ALGORITHM_VERSION,
                "profile": profile.canonical_parameters(
                    calibration_authority=calibration_authority
                ),
                "threshold_provenance": provenance,
                "runtime_calibration_authorization": runtime_authorization,
                "candidate_execution_authorized": False,
                "source_operator_executed": False,
                "degradation_profile": degradation,
                "restoration_activation": NO_OP,
                "no_op_reason": degradation["reason"],
                "raw_proposal": "NOT_EXECUTED",
                "bounded_residual": "ZERO",
                "alpha_lock_status": "BASELINE_BYTE_IDENTITY",
                "output_pixel_sha256": None,
            }
        else:
            with Image.open(baseline_file) as opened:
                opened.load()
                baseline_icc = opened.info.get("icc_profile")
                baseline = ImageOps.exif_transpose(opened).copy()
            if baseline.mode not in {"RGB", "RGBA"}:
                raise ValueError(f"BASELINE_MODE_UNSUPPORTED:{baseline.mode}")
            baseline_array = np.asarray(baseline, dtype=np.uint8)
            baseline_rgb = baseline_array[..., :3]
            proposal_rgb, raw_residual, _evidence, raw_record = build_raw_source_proposal(
                source_file, baseline_rgb, profile=profile
            )
            protection_scale, protection_record = build_protection_scale(
                baseline_rgb, profile=SAFE_PROFILE
            )
            candidate_rgb, bounded_record = apply_bounded_residual(
                baseline_rgb,
                raw_residual,
                protection_scale=protection_scale,
                protection_reliable=protection_record["status"] == "PASS",
                profile=SAFE_PROFILE,
            )
            if baseline.mode == "RGBA":
                output_array = attach_baseline_alpha(candidate_rgb, baseline_array)
                alpha_status = (
                    "PASS" if np.array_equal(output_array[..., 3], baseline_array[..., 3]) else "FAIL"
                )
                output_image = Image.fromarray(output_array, "RGBA")
            else:
                output_array = candidate_rgb
                alpha_status = "PASS_NOT_APPLICABLE_OPAQUE"
                output_image = Image.fromarray(output_array, "RGB")
            if np.array_equal(output_array, baseline_array):
                shutil.copyfile(baseline_file, output_file)
                output_encoding = "BASELINE_BYTE_IDENTITY"
            else:
                save_kwargs: dict[str, Any] = {
                    "format": "PNG",
                    "compress_level": 6,
                    "optimize": False,
                }
                if isinstance(baseline_icc, bytes) and baseline_icc:
                    save_kwargs["icc_profile"] = baseline_icc
                output_image.save(output_file, **save_kwargs)
                output_encoding = "DETERMINISTIC_PNG_COMPRESS_LEVEL_6"
            if record_path is not None:
                raw_proposal_path = Path(record_path).parent / "raw_proposal.png"
                Image.fromarray(proposal_rgb, "RGB").save(
                    raw_proposal_path, format="PNG", compress_level=6, optimize=False
                )
            record = {
                "algorithm_id": ALGORITHM_ID,
                "algorithm_version": ALGORITHM_VERSION,
                "profile": profile.canonical_parameters(
                    calibration_authority=calibration_authority
                ),
                "threshold_provenance": provenance,
                "runtime_calibration_authorization": runtime_authorization,
                "candidate_execution_authorized": True,
                "source_operator_executed": True,
                "degradation_profile": degradation,
                "restoration_activation": bounded_record["restoration_activation"],
                "no_op_reason": bounded_record.get("fail_closed_reason"),
                "raw_proposal": raw_record,
                "raw_proposal_path": str(raw_proposal_path) if raw_proposal_path else None,
                "protection_masks_metadata": protection_record,
                "bounded_residual": bounded_record,
                "alpha_lock_status": alpha_status,
                "alpha_policy": "SAFE_BASE_ALPHA_BYTE_IDENTITY_EQUIVALENT_TO_VERIFIED_SOURCE_ALPHA_RESAMPLE",
                "output_encoding": output_encoding,
                "output_pixel_sha256": _pixel_sha256(output_array),
            }
    except Exception as exc:
        shutil.copyfile(baseline_file, output_file)
        record = {
            "algorithm_id": ALGORITHM_ID,
            "algorithm_version": ALGORITHM_VERSION,
            "profile": profile.canonical_parameters(
                calibration_authority=calibration_authority
            ),
            "threshold_provenance": provenance,
            "runtime_calibration_authorization": runtime_authorization,
            "candidate_execution_authorized": False,
            "source_operator_executed": False,
            "degradation_profile": degradation,
            "restoration_activation": NO_OP,
            "no_op_reason": f"FAIL_CLOSED:{type(exc).__name__}:{exc}",
            "raw_proposal": "NOT_ADMISSIBLE",
            "bounded_residual": {
                "fail_closed": True,
                "fail_closed_reason": f"{type(exc).__name__}:{exc}",
            },
            "alpha_lock_status": "BASELINE_BYTE_IDENTITY",
            "output_pixel_sha256": None,
        }
    record.update(
        {
            "source_unchanged": _sha256_file(source_file) == source_before,
            "baseline_unchanged": _sha256_file(baseline_file) == baseline_before,
            "output_sha256": _sha256_file(output_file),
        }
    )
    if not record["source_unchanged"] or not record["baseline_unchanged"]:
        raise RuntimeError("READ_ONLY_INPUT_INTEGRITY_VIOLATION")
    if record_path is not None:
        target = Path(record_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    return record


def source_domain_restoration_candidate(
    request: CandidateExecutionRequest,
    *,
    calibration_authority: Mapping[str, Any] | None = None,
    calibration_artifact_path: str | Path | None = None,
    threshold_provenance: Mapping[str, Any] | None = None,
) -> None:
    restore_source_domain_candidate(
        request.source_path,
        request.baseline_path,
        request.output_path,
        record_path=request.run_directory
        / "budget_records"
        / "source_domain_restoration_record.json",
        calibration_authority=calibration_authority,
        calibration_artifact_path=calibration_artifact_path,
        threshold_provenance=threshold_provenance,
        candidate_id=request.candidate_id,
    )


__all__ = [
    "ALGORITHM_ID",
    "ALGORITHM_VERSION",
    "CALIBRATION_AUTHORITY_BINDING_VERSION",
    "DEGRADATION_PROFILE_VERSION",
    "OPERATOR_TYPE",
    "PROFILE_ID",
    "QUALIFICATION_RULE_VERSION",
    "RUNTIME_CALIBRATION_AUTHORIZATION_GATE_VERSION",
    "RESTORATION_EVIDENCE_MASK_VERSION",
    "SAFE_PROFILE_V2",
    "SourceDomainRestorationProfile",
    "TARGET_DEGRADATION_FAMILY",
    "THRESHOLD_PROVENANCE_VERSION",
    "build_raw_source_proposal",
    "build_calibration_authority_binding",
    "build_source_degradation_profile",
    "build_v2_threshold_provenance",
    "quantization_aware_luma_restore",
    "restore_source_domain_candidate",
    "source_domain_candidate_definition",
    "source_domain_restoration_candidate",
    "validate_runtime_calibration_authorization",
]
