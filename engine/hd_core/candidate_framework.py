"""Experimental-only 4K Candidate carrier for E4K-02.

This module owns execution isolation, deterministic Candidate identity, per-run
identity, mechanical output validation, comparison-surface eligibility, and
state normalization.  It deliberately delegates replay binding, safety,
quality-gain, mandatory-gate, human-review, and delivery decisions to E1-02.

It is not connected to the formal 4K route, API, Task, Result, Delivery, or UI.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from PIL import Image, __version__ as PILLOW_VERSION

from engine.image_processing_routing.four_k_v1 import inspect_4k_v1_source

from .safe_base import FORMAL_DATA_ROOT, process_hd_core_safe_base


FRAMEWORK_VERSION = "HDDE_4K_ENHANCEMENT_CANDIDATE_FRAMEWORK_V1"
CANDIDATE_IDENTITY_VERSION = "CANDIDATE_IDENTITY_V1"
RUN_IDENTITY_VERSION = "RUN_IDENTITY_V1"
CANDIDATE_RESULT_VERSION = "CANDIDATE_RESULT_V1"
COMPARISON_SURFACE_VERSION = "E1_02_COMPARISON_SURFACE_V1"
STATE_MACHINE_VERSION = "CANDIDATE_STATE_V1"
REPLAY_BINDING_AUTHORITY = "E1_02_REPLAY_BINDING_V1"
ACTUAL_RUN_BINDING_VERSION = "ACTUAL_RUN_TO_E1_CASE_BINDING_V1"

CONTROL_FRAMEWORK = "CONTROL_FRAMEWORK"
PRODUCT = "PRODUCT"
ALLOWED_CANDIDATE_CLASSES = frozenset({CONTROL_FRAMEWORK, PRODUCT})

EXECUTION_FAILED = "EXECUTION_FAILED"
OUTPUT_INVALID = "OUTPUT_INVALID"
EVALUATION_INELIGIBLE = "EVALUATION_INELIGIBLE"
SAFETY_REJECTED = "SAFETY_REJECTED"
QUALITY_REJECTED = "QUALITY_REJECTED"
REVIEW = "REVIEW"
ACCEPTED = "ACCEPTED"
NOT_APPLICABLE = "NOT_APPLICABLE"


class CandidateFrameworkError(RuntimeError):
    """Structured framework contract or isolation failure."""


def _canonical_json_object(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CandidateFrameworkError(f"{field_name}_NOT_OBJECT")
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise CandidateFrameworkError(f"{field_name}_NOT_CANONICAL_JSON") from exc
    if not isinstance(decoded, dict):
        raise CandidateFrameworkError(f"{field_name}_NOT_OBJECT")
    return decoded


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_text(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise CandidateFrameworkError(f"{field_name}_MISSING")
    return normalized


@dataclass(frozen=True)
class CandidateDefinition:
    """Immutable algorithm/configuration identity; never a run identity."""

    algorithm_id: str
    algorithm_version: str
    parameters: Mapping[str, Any]
    backend_identity: str
    precision_identity: str
    candidate_class: str = CONTROL_FRAMEWORK
    model_id: str = "NONE"
    model_version: str = "NONE"
    model_sha256: str = "NONE"
    normalization: Mapping[str, Any] = field(
        default_factory=lambda: {
            "version": "CANDIDATE_NORMALIZATION_DECLARATION_V1",
            "operations": [],
            "implicit_resize": False,
            "implicit_crop_or_padding": False,
            "implicit_color_conversion": False,
        }
    )
    color_profile_policy: str = "PRESERVE_BASELINE_PROFILE"
    control_fixture_only: bool = True

    def identity_contract(self) -> dict[str, Any]:
        algorithm_id = _required_text(self.algorithm_id, "ALGORITHM_ID")
        algorithm_version = _required_text(self.algorithm_version, "ALGORITHM_VERSION")
        backend = _required_text(self.backend_identity, "BACKEND_IDENTITY")
        precision = _required_text(self.precision_identity, "PRECISION_IDENTITY")
        if self.candidate_class not in ALLOWED_CANDIDATE_CLASSES:
            raise CandidateFrameworkError(
                f"CANDIDATE_CLASS_NOT_ALLOWED_IN_E4K_02:{self.candidate_class}"
            )
        if (
            self.candidate_class == CONTROL_FRAMEWORK
            and self.control_fixture_only is not True
        ):
            raise CandidateFrameworkError(
                "CONTROL_FRAMEWORK_MUST_BE_CONTROL_FIXTURE_ONLY"
            )
        if self.candidate_class == PRODUCT and self.control_fixture_only is not False:
            raise CandidateFrameworkError("PRODUCT_CANDIDATE_CANNOT_BE_CONTROL_FIXTURE")
        parameters = _canonical_json_object(self.parameters, field_name="PARAMETERS")
        normalization = _canonical_json_object(
            self.normalization, field_name="NORMALIZATION"
        )
        if not isinstance(normalization.get("operations"), list):
            raise CandidateFrameworkError("NORMALIZATION_OPERATIONS_NOT_LIST")
        model_id = _required_text(self.model_id, "MODEL_ID")
        model_version = _required_text(self.model_version, "MODEL_VERSION")
        model_sha256 = _required_text(self.model_sha256, "MODEL_SHA256")
        if self.candidate_class == PRODUCT:
            model_identity_is_none = (
                model_id == "NONE"
                and model_version == "NONE"
                and model_sha256 == "NONE"
            )
            if not model_identity_is_none:
                if model_id == "NONE" or model_version == "NONE":
                    raise CandidateFrameworkError("PRODUCT_MODEL_IDENTITY_MISSING")
                if not re.fullmatch(r"[0-9a-fA-F]{64}", model_sha256):
                    raise CandidateFrameworkError("PRODUCT_MODEL_SHA256_INVALID")
        is_control = self.candidate_class == CONTROL_FRAMEWORK
        return {
            "identity_version": CANDIDATE_IDENTITY_VERSION,
            "candidate_class": self.candidate_class,
            "algorithm_id": algorithm_id,
            "algorithm_version": algorithm_version,
            "canonical_parameters": parameters,
            "backend_identity": backend,
            "precision_identity": precision,
            "model_id": model_id,
            "model_version": model_version,
            "model_sha256": model_sha256,
            "normalization": normalization,
            "color_profile_policy": _required_text(
                self.color_profile_policy, "COLOR_PROFILE_POLICY"
            ),
            "control_fixture_only": is_control,
            "not_product_candidate": is_control,
            "not_enhancement_algorithm": is_control,
            "experimental_only": True,
        }

    @property
    def candidate_id(self) -> str:
        return f"candidate_{_canonical_sha256(self.identity_contract())}"


@dataclass(frozen=True)
class CandidateExecutionRequest:
    """Only isolated snapshots are exposed to a Candidate executor."""

    source_path: Path
    baseline_path: Path
    output_path: Path
    run_directory: Path
    candidate_id: str
    run_id: str


CandidateExecutor = Callable[[CandidateExecutionRequest], None]


@dataclass(frozen=True)
class E102EvaluationContext:
    manifest_path: Path
    case_id: str


def evaluate_actual_run_binding(
    context: E102EvaluationContext | None,
    *,
    actual_source_sha256: str,
    actual_baseline_sha256: str,
) -> dict[str, Any]:
    """Qualify actual run facts against one E1 Case before invoking E1-02.

    This is an eligibility precondition, not a replay identity algorithm.  E1-02
    remains the sole authority that creates replay_identity.
    """

    base = {
        "binding_version": ACTUAL_RUN_BINDING_VERSION,
        "actual_source_sha256": actual_source_sha256,
        "actual_baseline_sha256": actual_baseline_sha256,
    }
    if context is None:
        return {
            **base,
            "e1_01_case_id": None,
            "expected_source_binding_sha256": None,
            "expected_baseline_binding_sha256": None,
            "source_binding_match": None,
            "baseline_binding_match": None,
            "actual_run_binding_status": "NOT_APPLICABLE",
            "actual_run_binding_reason": "E1_02_CONTEXT_NOT_PROVIDED",
        }
    try:
        manifest = json.loads(context.manifest_path.read_text(encoding="utf-8"))
        matches = [
            item
            for item in manifest.get("cases", [])
            if item.get("case_id") == context.case_id
        ]
        if len(matches) != 1:
            raise CandidateFrameworkError(
                f"E1_02_CASE_ID_NOT_UNIQUE_OR_MISSING:{context.case_id}"
            )
        case = matches[0]
        expected_source = str(case["input"]["sha256"])
        expected_baseline = str(case["safe_base"]["sha256"])
    except Exception as exc:
        return {
            **base,
            "e1_01_case_id": context.case_id,
            "expected_source_binding_sha256": None,
            "expected_baseline_binding_sha256": None,
            "source_binding_match": False,
            "baseline_binding_match": False,
            "actual_run_binding_status": "FAIL",
            "actual_run_binding_reason": (
                f"E1_CASE_CONTRACT_UNAVAILABLE:{type(exc).__name__}:{exc}"
            ),
        }
    source_match = actual_source_sha256 == expected_source
    baseline_match = actual_baseline_sha256 == expected_baseline
    reasons: list[str] = []
    if not source_match:
        reasons.append("SOURCE_BINDING_MISMATCH")
    if not baseline_match:
        reasons.append("BASELINE_BINDING_MISMATCH")
    return {
        **base,
        "e1_01_case_id": context.case_id,
        "expected_source_binding_sha256": expected_source,
        "expected_baseline_binding_sha256": expected_baseline,
        "source_binding_match": source_match,
        "baseline_binding_match": baseline_match,
        "actual_run_binding_status": "PASS" if not reasons else "FAIL",
        "actual_run_binding_reason": (
            "SOURCE_AND_BASELINE_MATCH_E1_CASE" if not reasons else ";".join(reasons)
        ),
    }


def build_candidate_identity(definition: CandidateDefinition) -> tuple[str, dict[str, Any]]:
    contract = definition.identity_contract()
    return definition.candidate_id, contract


def build_run_identity(
    *,
    candidate_id: str,
    source_sha256: str,
    baseline_sha256: str,
    runtime_context: Mapping[str, Any],
    execution_nonce: str,
) -> tuple[str, dict[str, Any]]:
    contract = {
        "identity_version": RUN_IDENTITY_VERSION,
        "candidate_id": _required_text(candidate_id, "CANDIDATE_ID"),
        "source_sha256": _required_text(source_sha256, "SOURCE_SHA256"),
        "baseline_sha256": _required_text(baseline_sha256, "BASELINE_SHA256"),
        "runtime_context": _canonical_json_object(
            runtime_context, field_name="RUNTIME_CONTEXT"
        ),
        "execution_nonce": _required_text(execution_nonce, "EXECUTION_NONCE"),
    }
    return f"run_{_canonical_sha256(contract)}", contract


def default_runtime_context(executor_identity: str) -> dict[str, Any]:
    return {
        "framework_version": FRAMEWORK_VERSION,
        "executor_identity": _required_text(executor_identity, "EXECUTOR_IDENTITY"),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "pillow_version": PILLOW_VERSION,
    }


def _portable_reference(path: Path | None) -> str | None:
    if path is None:
        return None
    resolved = path.resolve()
    repo_root = Path(__file__).resolve().parents[2]
    try:
        return resolved.relative_to(repo_root).as_posix()
    except ValueError:
        return str(resolved)


def _is_same_or_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(root))) == str(root)
    except ValueError:
        return False


def _validate_workspace(source: Path, workspace_root: Path) -> Path:
    root = workspace_root.expanduser().resolve(strict=False)
    formal = FORMAL_DATA_ROOT.expanduser().resolve(strict=False)
    if _is_same_or_within(root, formal) or _is_same_or_within(formal, root):
        raise CandidateFrameworkError("FORMAL_OUTPUT_FORBIDDEN")
    if root == source.resolve().parent:
        raise CandidateFrameworkError("SOURCE_DIRECTORY_OUTPUT_FORBIDDEN")
    return root


def _image_facts(path: Path) -> dict[str, Any]:
    with Image.open(path) as opened:
        opened.load()
        exif = opened.getexif()
        icc = opened.info.get("icc_profile")
        bands = list(opened.getbands())
        alpha = opened.getchannel("A").tobytes() if "A" in bands else None
        return {
            "width": opened.width,
            "height": opened.height,
            "mode": opened.mode,
            "bands": bands,
            "format": str(opened.format or "UNKNOWN").upper(),
            "orientation": int(exif.get(274, 1)),
            "has_alpha": alpha is not None,
            "alpha_sha256_or_none": (
                "NONE" if alpha is None else hashlib.sha256(alpha).hexdigest()
            ),
            "icc_profile_sha256_or_none": (
                "NONE"
                if not isinstance(icc, bytes) or not icc
                else hashlib.sha256(icc).hexdigest()
            ),
        }


def _mechanical_output_validation(
    *,
    source: Path,
    baseline: Path,
    output: Path,
    source_sha256_before: str,
    baseline_sha256_before: str,
) -> dict[str, Any]:
    checks: dict[str, bool] = {
        "output_exists": output.is_file(),
        "output_nonempty": output.is_file() and output.stat().st_size > 0,
        "decode_success": False,
        "source_unchanged": source.is_file()
        and sha256_file(source) == source_sha256_before,
        "baseline_unchanged": baseline.is_file()
        and sha256_file(baseline) == baseline_sha256_before,
    }
    output_facts: dict[str, Any] | None = None
    decode_error: str | None = None
    candidate_sha256: str | None = None
    if checks["output_exists"] and checks["output_nonempty"]:
        try:
            output_facts = _image_facts(output)
            checks["decode_success"] = True
            candidate_sha256 = sha256_file(output)
        except Exception as exc:
            decode_error = f"{type(exc).__name__}:{exc}"
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "validation_version": "CANDIDATE_OUTPUT_VALIDATION_V1",
        "status": status,
        "checks": checks,
        "decode_error": decode_error,
        "candidate_sha256": candidate_sha256,
        "output_facts": output_facts,
    }


def build_comparison_surface(
    baseline_path: str | Path,
    candidate_path: str | Path,
    definition: CandidateDefinition,
) -> dict[str, Any]:
    baseline = Path(baseline_path)
    candidate = Path(candidate_path)
    baseline_facts = _image_facts(baseline)
    candidate_facts = _image_facts(candidate)
    contract = definition.identity_contract()
    normalization = contract["normalization"]
    checks = {
        "same_target_dimensions": (
            baseline_facts["width"], baseline_facts["height"]
        )
        == (candidate_facts["width"], candidate_facts["height"]),
        "same_orientation": baseline_facts["orientation"]
        == candidate_facts["orientation"],
        "same_crop_padding_geometry_contract": not bool(
            normalization.get("implicit_crop_or_padding")
        ),
        "compatible_channel_contract": baseline_facts["bands"]
        == candidate_facts["bands"],
        "compatible_alpha_contract": (
            baseline_facts["has_alpha"] == candidate_facts["has_alpha"]
            and baseline_facts["alpha_sha256_or_none"]
            == candidate_facts["alpha_sha256_or_none"]
        ),
        "known_color_profile_handling": (
            contract["color_profile_policy"] == "PRESERVE_BASELINE_PROFILE"
            and baseline_facts["icc_profile_sha256_or_none"]
            == candidate_facts["icc_profile_sha256_or_none"]
        ),
        "decode_success": True,
        "no_implicit_resize": not bool(normalization.get("implicit_resize")),
        "no_implicit_color_conversion": not bool(
            normalization.get("implicit_color_conversion")
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "surface_version": COMPARISON_SURFACE_VERSION,
        "status": "ELIGIBLE" if not failures else "INELIGIBLE",
        "checks": checks,
        "failures": failures,
        "baseline_facts": baseline_facts,
        "candidate_facts": candidate_facts,
        "normalization_declaration": normalization,
        "normalization_applied_by_framework": False,
        "implicit_repair_performed": False,
    }


def resolve_candidate_state(
    *,
    execution_status: str,
    output_validation_status: str,
    comparison_surface_status: str,
    e1_02_result: Mapping[str, Any] | None,
) -> str:
    if execution_status != "COMPLETED":
        return EXECUTION_FAILED
    if output_validation_status != "PASS":
        return OUTPUT_INVALID
    if comparison_surface_status != "ELIGIBLE" or not e1_02_result:
        return EVALUATION_INELIGIBLE
    if e1_02_result.get("evaluation_status") != "COMPLETE":
        return EVALUATION_INELIGIBLE
    safety = (e1_02_result.get("safety_results") or {}).get("status")
    quality = e1_02_result.get("quality_gain_status")
    delivery = e1_02_result.get("delivery_status")
    if safety == "FAIL":
        return SAFETY_REJECTED
    if quality == "QUALITY_GAIN_REJECTED":
        return QUALITY_REJECTED
    if (
        safety == "PASS"
        and quality == "QUALITY_GAIN_PROVEN"
        and e1_02_result.get("mandatory_gate_complete") is True
        and delivery == "PASS"
    ):
        return ACCEPTED
    return REVIEW


def _safe_resolution(state: str) -> dict[str, Any]:
    if state == ACCEPTED:
        return {
            "safe_reference_selected": "CANDIDATE",
            "fallback_kind": "NOT_APPLICABLE",
            "fallback_reason": "EXPERIMENTAL_E1_02_ACCEPTED_NOT_FORMAL_PRODUCT",
            "candidate_accepted": True,
            "candidate_rejected": False,
        }
    if state == REVIEW:
        return {
            "safe_reference_selected": "BASELINE",
            "fallback_kind": "REVIEW_SAFE_REFERENCE",
            "fallback_reason": "CANDIDATE_NOT_ACCEPTED_PENDING_OR_INSUFFICIENT_PROOF",
            "candidate_accepted": False,
            "candidate_rejected": False,
        }
    mapping = {
        EXECUTION_FAILED: ("EXECUTION_FALLBACK", "CANDIDATE_EXECUTION_FAILED"),
        OUTPUT_INVALID: ("EXECUTION_FALLBACK", "CANDIDATE_OUTPUT_INVALID"),
        EVALUATION_INELIGIBLE: (
            "EVALUATION_INELIGIBLE",
            "COMPARISON_OR_E1_02_ELIGIBILITY_FAILED",
        ),
        SAFETY_REJECTED: ("SAFETY_REJECTION", "E1_02_HARD_SAFETY_REJECTED"),
        QUALITY_REJECTED: ("QUALITY_REJECTION", "E1_02_QUALITY_REJECTED"),
    }
    kind, reason = mapping[state]
    return {
        "safe_reference_selected": "BASELINE",
        "fallback_kind": kind,
        "fallback_reason": reason,
        "candidate_accepted": False,
        "candidate_rejected": state != EVALUATION_INELIGIBLE,
    }


def _e1_02_spec_and_result(
    *,
    context: E102EvaluationContext,
    definition: CandidateDefinition,
    candidate_id: str,
    run_id: str,
    candidate_path: Path,
    output_root: Path,
    actual_run_binding: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    # Importing the E1-02 module, including its replay helper, is the explicit
    # authority boundary.  No replay hash implementation exists in Framework.
    from tools.experiments import e1_02_quality_delivery_gate as e1_02

    if actual_run_binding.get("actual_run_binding_status") != "PASS":
        raise CandidateFrameworkError("ACTUAL_RUN_BINDING_NOT_PASS")
    manifest = json.loads(context.manifest_path.read_text(encoding="utf-8"))
    matches = [
        item
        for item in manifest.get("cases", [])
        if item.get("case_id") == context.case_id
    ]
    if len(matches) != 1:
        raise CandidateFrameworkError(
            f"E1_02_CASE_ID_NOT_UNIQUE_OR_MISSING:{context.case_id}"
        )
    case = matches[0]
    candidate_sha = sha256_file(candidate_path)
    identity_contract = definition.identity_contract()
    if definition.candidate_class == CONTROL_FRAMEWORK:
        e1_candidate_class = e1_02.CONTROL_ZERO
        adapter_reason = "CONTROL_FRAMEWORK_TO_EXISTING_ZERO_GAIN_CONTROL_SEMANTICS"
        product_authorization_forbidden = True
    elif definition.candidate_class == PRODUCT:
        e1_candidate_class = e1_02.PRODUCT
        adapter_reason = "PRODUCT_CANDIDATE_TO_EXISTING_E1_02_PRODUCT_SEMANTICS"
        product_authorization_forbidden = False
    else:  # identity_contract already fails closed; retain a local guard.
        raise CandidateFrameworkError("CANDIDATE_CLASS_NOT_MAPPABLE_TO_E1_02")
    parameters = {
        "framework_version": FRAMEWORK_VERSION,
        "candidate_id": candidate_id,
        "candidate_identity_contract": identity_contract,
        "e1_02_candidate_class_adapter": {
            "framework_candidate_class": definition.candidate_class,
            "e1_02_candidate_class": e1_candidate_class,
            "reason": adapter_reason,
            "product_authorization_forbidden": product_authorization_forbidden,
        },
    }
    replay_identity, replay_contract = e1_02.compute_replay_identity(
        case, candidate_sha, candidate_id, parameters
    )
    spec = {
        "candidate_id": run_id,
        "candidate_class": e1_candidate_class,
        "candidate_identity": candidate_sha,
        "algorithm_identity": candidate_id,
        "parameters": parameters,
        "canonical_parameters": parameters,
        "source_binding_sha256": actual_run_binding[
            "expected_source_binding_sha256"
        ],
        "baseline_binding_sha256": actual_run_binding[
            "expected_baseline_binding_sha256"
        ],
        "gt_binding_sha256_or_none": (
            "NONE" if case["gt"] is None else case["gt"]["sha256"]
        ),
        "roi_set_sha256": replay_contract["roi_manifest_hash"],
        "replay_identity": replay_identity,
        "replay_contract": replay_contract,
        "evaluation_schema_version": e1_02.EVALUATION_SCHEMA_VERSION,
        "human_review_evidence": None,
    }
    result = e1_02.evaluate_case(
        context.manifest_path,
        context.case_id,
        candidate_path,
        spec,
        output_root,
    )
    return spec, result


def run_4k_candidate(
    source_path: str | Path,
    workspace_root: str | Path,
    *,
    definition: CandidateDefinition,
    executor: CandidateExecutor,
    baseline_path: str | Path | None = None,
    e1_02_context: E102EvaluationContext | None = None,
    runtime_context: Mapping[str, Any] | None = None,
    execution_nonce: str | None = None,
) -> dict[str, Any]:
    """Run one isolated Candidate and delegate all quality authority to E1-02."""

    if not callable(executor):
        raise CandidateFrameworkError("CANDIDATE_EXECUTOR_NOT_CALLABLE")
    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise CandidateFrameworkError(f"SOURCE_MISSING:{source}")
    root = _validate_workspace(source, Path(workspace_root))
    candidate_id, candidate_contract = build_candidate_identity(definition)
    executor_identity = getattr(executor, "__name__", type(executor).__name__)
    runtime = _canonical_json_object(
        runtime_context or default_runtime_context(executor_identity),
        field_name="RUNTIME_CONTEXT",
    )
    nonce = execution_nonce or str(uuid.uuid4())
    source_sha = sha256_file(source)
    source_meta = inspect_4k_v1_source(source)

    if source_meta["processing_disposition"] == "NO_PROCESSING_NEEDED":
        run_id, run_contract = build_run_identity(
            candidate_id=candidate_id,
            source_sha256=source_sha,
            baseline_sha256="NONE",
            runtime_context=runtime,
            execution_nonce=nonce,
        )
        return {
            "result_version": CANDIDATE_RESULT_VERSION,
            "framework_version": FRAMEWORK_VERSION,
            "state_machine_version": STATE_MACHINE_VERSION,
            "run_id": run_id,
            "run_identity_contract": run_contract,
            "candidate_id": candidate_id,
            "candidate_identity_contract": candidate_contract,
            "candidate_class": definition.candidate_class,
            "candidate_state": NOT_APPLICABLE,
            "processing_disposition": "NO_PROCESSING_NEEDED",
            "execution_status": "NOT_APPLICABLE",
            "execution_error": None,
            "source_reference": _portable_reference(source),
            "baseline_reference": None,
            "candidate_reference": None,
            "source_sha256": source_sha,
            "baseline_sha256": "NONE",
            "actual_source_sha256": source_sha,
            "actual_baseline_sha256": "NONE",
            "expected_source_binding_sha256": None,
            "expected_baseline_binding_sha256": None,
            "source_binding_match": None,
            "baseline_binding_match": None,
            "actual_run_binding_status": "NOT_APPLICABLE",
            "actual_run_binding_reason": "NO_PROCESSING_NEEDED_BYPASS",
            "actual_run_binding": {
                "binding_version": ACTUAL_RUN_BINDING_VERSION,
                "actual_source_sha256": source_sha,
                "actual_baseline_sha256": "NONE",
                "expected_source_binding_sha256": None,
                "expected_baseline_binding_sha256": None,
                "source_binding_match": None,
                "baseline_binding_match": None,
                "actual_run_binding_status": "NOT_APPLICABLE",
                "actual_run_binding_reason": "NO_PROCESSING_NEEDED_BYPASS",
            },
            "candidate_sha256": None,
            "e1_02_replay_identity": None,
            "replay_binding_authority": REPLAY_BINDING_AUTHORITY,
            "safety_status": "NOT_APPLICABLE",
            "mandatory_gate_complete": False,
            "quality_gain_status": "NOT_APPLICABLE",
            "delivery_status": "NOT_APPLICABLE",
            "safe_reference_selected": "SOURCE",
            "fallback_kind": "NOT_APPLICABLE",
            "fallback_reason": "SOURCE_LONG_EDGE_GE_3840_BYPASS",
            "candidate_accepted": False,
            "candidate_rejected": False,
            "control_fixture_only": definition.control_fixture_only,
            "formal_production": False,
            "evidence_refs": {},
            "candidate_execution": "NOT_APPLICABLE",
            "baseline_artifact": "NONE",
            "candidate_fallback": "NOT_APPLICABLE",
        }

    baseline_resolution: dict[str, Any]
    if baseline_path is None:
        resolution_root = root / "_baseline_resolution" / nonce
        safe = process_hd_core_safe_base(source, resolution_root)
        if safe.get("status") != "COMPLETED":
            raise CandidateFrameworkError(
                f"SAFE_BASELINE_NOT_COMPLETED:{safe.get('status')}"
            )
        baseline = Path(str(safe["final_output_path"])).resolve()
        baseline_resolution = {
            "mode": "FROZEN_SAFE_BASE_EXECUTED_ONCE",
            "safe_base_result": safe,
        }
    else:
        baseline = Path(baseline_path).expanduser().resolve()
        baseline_resolution = {"mode": "EXISTING_VALID_BASELINE_REUSED"}
    if not baseline.is_file():
        raise CandidateFrameworkError(f"BASELINE_MISSING:{baseline}")
    baseline_sha = sha256_file(baseline)
    actual_run_binding = evaluate_actual_run_binding(
        e1_02_context,
        actual_source_sha256=source_sha,
        actual_baseline_sha256=baseline_sha,
    )
    run_id, run_contract = build_run_identity(
        candidate_id=candidate_id,
        source_sha256=source_sha,
        baseline_sha256=baseline_sha,
        runtime_context=runtime,
        execution_nonce=nonce,
    )
    if candidate_id == run_id:
        raise CandidateFrameworkError("CANDIDATE_RUN_ID_COLLISION")
    run_dir = root / run_id
    if run_dir.exists():
        raise CandidateFrameworkError(f"RUN_DIRECTORY_ALREADY_EXISTS:{run_dir}")
    input_dir = run_dir / "isolated_inputs"
    candidate_dir = run_dir / "candidate_artifact"
    input_dir.mkdir(parents=True)
    candidate_dir.mkdir()
    source_snapshot = input_dir / f"source{source.suffix.lower()}"
    baseline_snapshot = input_dir / "baseline.png"
    candidate_output = candidate_dir / "candidate.png"
    shutil.copyfile(source, source_snapshot)
    shutil.copyfile(baseline, baseline_snapshot)
    if sha256_file(source_snapshot) != source_sha:
        raise CandidateFrameworkError("SOURCE_SNAPSHOT_HASH_MISMATCH")
    if sha256_file(baseline_snapshot) != baseline_sha:
        raise CandidateFrameworkError("BASELINE_SNAPSHOT_HASH_MISMATCH")

    request = CandidateExecutionRequest(
        source_path=source_snapshot,
        baseline_path=baseline_snapshot,
        output_path=candidate_output,
        run_directory=run_dir,
        candidate_id=candidate_id,
        run_id=run_id,
    )
    execution_status = "COMPLETED"
    execution_error: str | None = None
    try:
        executor(request)
    except Exception as exc:
        execution_status = "FAILED"
        execution_error = f"{type(exc).__name__}:{exc}"

    validation = _mechanical_output_validation(
        source=source,
        baseline=baseline,
        output=candidate_output,
        source_sha256_before=source_sha,
        baseline_sha256_before=baseline_sha,
    )
    validation["comparison_contract_status"] = "NOT_EVALUATED"
    validation["comparison_contract_checks"] = {
        "target_dimensions_valid": "NOT_EVALUATED",
        "orientation_valid": "NOT_EVALUATED",
        "channel_contract_valid": "NOT_EVALUATED",
        "alpha_contract_valid": "NOT_EVALUATED",
        "color_profile_handling_known": "NOT_EVALUATED",
    }
    comparison_surface: dict[str, Any] | None = None
    e1_spec: dict[str, Any] | None = None
    e1_result: dict[str, Any] | None = None
    e1_error: str | None = None
    if execution_status == "COMPLETED" and validation["status"] == "PASS":
        comparison_surface = build_comparison_surface(
            baseline_snapshot, candidate_output, definition
        )
        surface_checks = comparison_surface["checks"]
        validation["comparison_contract_status"] = comparison_surface["status"]
        validation["comparison_contract_checks"] = {
            "target_dimensions_valid": surface_checks["same_target_dimensions"],
            "orientation_valid": surface_checks["same_orientation"],
            "channel_contract_valid": surface_checks[
                "compatible_channel_contract"
            ],
            "alpha_contract_valid": surface_checks["compatible_alpha_contract"],
            "color_profile_handling_known": surface_checks[
                "known_color_profile_handling"
            ],
        }
        if (
            comparison_surface["status"] == "ELIGIBLE"
            and e1_02_context
            and actual_run_binding["actual_run_binding_status"] == "PASS"
        ):
            try:
                e1_spec, e1_result = _e1_02_spec_and_result(
                    context=e1_02_context,
                    definition=definition,
                    candidate_id=candidate_id,
                    run_id=run_id,
                    candidate_path=candidate_output,
                    output_root=run_dir / "e1_02_evidence" / "comparisons",
                    actual_run_binding=actual_run_binding,
                )
                if "roi_results" in e1_result:
                    roi_path = run_dir / "roi_results" / f"{run_id}.json"
                    roi_path.parent.mkdir(parents=True, exist_ok=True)
                    roi_path.write_text(
                        json.dumps(
                            {
                                "case_id": run_id,
                                "roi_results": e1_result["roi_results"],
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
            except Exception as exc:
                e1_error = f"{type(exc).__name__}:{exc}"
        elif (
            comparison_surface["status"] == "ELIGIBLE"
            and e1_02_context
            and actual_run_binding["actual_run_binding_status"] == "FAIL"
        ):
            e1_error = (
                "ACTUAL_RUN_BINDING_FAILED:"
                + str(actual_run_binding["actual_run_binding_reason"])
            )

    state = resolve_candidate_state(
        execution_status=execution_status,
        output_validation_status=validation["status"],
        comparison_surface_status=(
            "INELIGIBLE" if comparison_surface is None else comparison_surface["status"]
        ),
        e1_02_result=e1_result,
    )
    safe = _safe_resolution(state)
    if actual_run_binding["actual_run_binding_status"] == "FAIL":
        safe["fallback_reason"] = str(
            actual_run_binding["actual_run_binding_reason"]
        )
    safety = None if e1_result is None else e1_result.get("safety_results")
    evidence_refs: dict[str, Any] = {
        "run_directory": _portable_reference(run_dir),
        "isolated_source_snapshot": _portable_reference(source_snapshot),
        "isolated_baseline_snapshot": _portable_reference(baseline_snapshot),
        "comparison_surface_version": COMPARISON_SURFACE_VERSION,
        "actual_run_binding_version": ACTUAL_RUN_BINDING_VERSION,
    }
    if e1_result:
        evidence_refs["e1_02"] = e1_result.get("evidence_refs", {})
    external_model_used = candidate_contract["model_id"] != "NONE"
    result = {
        "result_version": CANDIDATE_RESULT_VERSION,
        "framework_version": FRAMEWORK_VERSION,
        "state_machine_version": STATE_MACHINE_VERSION,
        "run_id": run_id,
        "run_identity_contract": run_contract,
        "candidate_id": candidate_id,
        "candidate_identity_contract": candidate_contract,
        "candidate_class": definition.candidate_class,
        "candidate_state": state,
        "processing_disposition": source_meta["processing_disposition"],
        "execution_status": execution_status,
        "execution_error": execution_error,
        "source_reference": _portable_reference(source),
        "baseline_reference": _portable_reference(baseline),
        "candidate_reference": (
            _portable_reference(candidate_output)
            if candidate_output.is_file()
            else None
        ),
        "source_sha256": source_sha,
        "baseline_sha256": baseline_sha,
        "actual_source_sha256": actual_run_binding["actual_source_sha256"],
        "actual_baseline_sha256": actual_run_binding["actual_baseline_sha256"],
        "expected_source_binding_sha256": actual_run_binding[
            "expected_source_binding_sha256"
        ],
        "expected_baseline_binding_sha256": actual_run_binding[
            "expected_baseline_binding_sha256"
        ],
        "source_binding_match": actual_run_binding["source_binding_match"],
        "baseline_binding_match": actual_run_binding["baseline_binding_match"],
        "actual_run_binding_status": actual_run_binding[
            "actual_run_binding_status"
        ],
        "actual_run_binding_reason": actual_run_binding[
            "actual_run_binding_reason"
        ],
        "actual_run_binding": actual_run_binding,
        "candidate_sha256": validation["candidate_sha256"],
        "e1_02_replay_identity": (
            None if e1_result is None else e1_result.get("replay_identity")
        ),
        "replay_binding_authority": REPLAY_BINDING_AUTHORITY,
        "parallel_replay_binding_created": False,
        "safety_status": None if safety is None else safety.get("status"),
        "mandatory_gate_complete": (
            False
            if e1_result is None
            else bool(e1_result.get("mandatory_gate_complete"))
        ),
        "quality_gain_status": (
            "NOT_EVALUATED"
            if e1_result is None
            else e1_result.get("quality_gain_status")
        ),
        "delivery_status": (
            "NOT_EVALUATED"
            if e1_result is None
            else e1_result.get("delivery_status")
        ),
        **safe,
        "control_fixture_only": definition.control_fixture_only,
        "formal_production": False,
        "model_download": external_model_used,
        "model_inference_run": (
            external_model_used
            and execution_status == "COMPLETED"
            and validation["status"] == "PASS"
        ),
        "model_benchmark": (
            external_model_used and e1_result is not None
        ),
        "model_adopted": False,
        "source_isolation": "READ_ONLY_ORIGINAL_PLUS_ISOLATED_SNAPSHOT",
        "baseline_isolation": "READ_ONLY_ORIGINAL_PLUS_ISOLATED_SNAPSHOT",
        "candidate_isolation": "RUN_SCOPED_DIRECTORY",
        "baseline_resolution": baseline_resolution,
        "output_validation": validation,
        "comparison_surface": comparison_surface,
        "e1_02_candidate_class": (
            None if e1_spec is None else e1_spec["candidate_class"]
        ),
        "e1_02_spec": e1_spec,
        "e1_02_result": e1_result,
        "e1_02_error": e1_error,
        "evidence_refs": evidence_refs,
    }
    return result


def identity_test_candidate(request: CandidateExecutionRequest) -> None:
    """Zero-gain control: byte-exact baseline copy, never an enhancement."""

    shutil.copyfile(request.baseline_path, request.output_path)


def failure_test_candidate(_request: CandidateExecutionRequest) -> None:
    raise RuntimeError("CONTROLLED_FAILURE_TEST_CANDIDATE")


def invalid_output_test_candidate(request: CandidateExecutionRequest) -> None:
    request.output_path.write_bytes(b"INVALID_OUTPUT_TEST_CANDIDATE")


__all__ = [
    "ACCEPTED",
    "ACTUAL_RUN_BINDING_VERSION",
    "CANDIDATE_IDENTITY_VERSION",
    "CANDIDATE_RESULT_VERSION",
    "COMPARISON_SURFACE_VERSION",
    "CONTROL_FRAMEWORK",
    "CandidateDefinition",
    "CandidateExecutionRequest",
    "CandidateExecutor",
    "CandidateFrameworkError",
    "E102EvaluationContext",
    "EVALUATION_INELIGIBLE",
    "EXECUTION_FAILED",
    "FRAMEWORK_VERSION",
    "NOT_APPLICABLE",
    "OUTPUT_INVALID",
    "PRODUCT",
    "QUALITY_REJECTED",
    "REPLAY_BINDING_AUTHORITY",
    "REVIEW",
    "RUN_IDENTITY_VERSION",
    "SAFETY_REJECTED",
    "STATE_MACHINE_VERSION",
    "build_candidate_identity",
    "build_comparison_surface",
    "build_run_identity",
    "evaluate_actual_run_binding",
    "failure_test_candidate",
    "identity_test_candidate",
    "invalid_output_test_candidate",
    "resolve_candidate_state",
    "run_4k_candidate",
    "sha256_file",
]
