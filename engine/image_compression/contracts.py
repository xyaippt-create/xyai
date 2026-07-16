from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .statuses import (
    CandidateDeliveryRole,
    DeliveryGateStatus,
    OperationMode,
    TechnicalStatus,
    VisualReviewStatus,
)


TASK_CONTRACT_VERSION = "hdde.image-task.v1"
RESULT_CONTRACT_VERSION = "hdde.image-result.v1"
TASK_FIELD_NAMES = (
    "contract_version",
    "task_id",
    "operation_mode",
    "source_path",
    "source_sha256_expected",
    "output_directory",
    "preserve_format",
    "max_width",
    "max_height",
    "max_file_size_bytes",
    "target_width",
    "target_height",
    "scale_ratio",
    "resize_policy",
    "quality_policy",
    "metadata_policy",
    "overwrite_policy",
    "output_naming_policy",
    "visual_review_policy",
    "request_context",
    "client_context",
    "run_id",
    "test_case_id",
    "diagnostic_session_id",
    "issue_report_id",
    "expected_status",
    "required_checks",
    "user_issue_context",
)
RESULT_FIELD_NAMES = (
    "contract_version",
    "task_contract_version",
    "task_id",
    "operation_mode",
    "run_id",
    "test_case_id",
    "diagnostic_session_id",
    "issue_report_id",
    "technical_status",
    "visual_review_status",
    "delivery_gate_status",
    "delivery_eligible",
    "delivery_decision_reason",
    "source_path",
    "source_sha256",
    "source_format",
    "source_dimensions",
    "source_size_bytes",
    "output_created",
    "output_path",
    "output_sha256",
    "output_format",
    "output_dimensions",
    "output_size_bytes",
    "size_reduction_bytes",
    "size_reduction_ratio",
    "dimension_scale_ratio",
    "lossy",
    "reencoded",
    "resized",
    "metadata_preserved",
    "metadata_details",
    "alpha_preserved",
    "alpha_details",
    "processing_seconds",
    "stage_seconds",
    "slowest_stage",
    "warnings",
    "failure_code",
    "failure_reason",
    "risk_reasons",
    "candidate_delivery_role",
    "evidence_paths",
    "validation_status",
    "validation_failures",
    "asset_manifest_path",
    "asset_comparison_path",
    "execution_log_path",
    "test_feedback",
    "user_feedback",
)
VALIDATION_STAGES = (
    "STRUCTURE_AND_UNKNOWN_FIELDS",
    "VERSION_REQUIRED_AND_BASE_TYPES",
    "FIELD_APPLICABILITY",
    "ENUMS_AND_SINGLE_FIELD_RANGES",
    "CROSS_FIELD_CONFLICTS",
    "RESOURCE_AND_PATH_PREFLIGHT",
    "RUNTIME_PROCESSING_ERRORS",
)

# IDs are also used in Windows output names; keep the grammar portable across
# Windows, macOS and Linux (notably, ':' is not a valid Windows filename char).
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DIAGNOSTIC_ID = re.compile(r"^(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}|[0-9A-HJKMNP-TV-Z]{26})$")
_REGISTERED_CHECKS = {
    "SOURCE_SHA_PROTECTION",
    "NO_OVERWRITE",
    "ATOMIC_WRITE",
    "FAIL_CLOSED",
    "DECODE_VERIFY",
    "FORMAT_VERIFY",
    "DIMENSION_VERIFY",
    "ALPHA_VERIFY",
    "METADATA_VERIFY",
    "VISUAL_REVIEW",
}
_USER_ISSUE_FIELDS = {
    "issue_category",
    "user_description",
    "reproduction_steps",
    "expected_result",
    "actual_result",
    "attachment_paths",
    "include_source_image",
    "include_output_image",
    "include_diagnostic_logs",
    "privacy_confirmation",
}
_SENSITIVE_CONTEXT_KEYS = {"account", "accountid", "token", "accesstoken", "authtoken", "secret", "password", "apikey", "serialnumber"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KNOWN_EXPECTED_STATUSES = {
    *(item.value for item in TechnicalStatus),
    *(item.value for item in VisualReviewStatus),
    *(item.value for item in DeliveryGateStatus),
}


def _metadata_details_default() -> dict[str, Any]:
    return {
        "icc_preserved": None,
        "exif_preserved": None,
        "dpi_preserved": None,
        "xmp_preserved": None,
        "orientation_semantics_correct": None,
        "png_non_idat_preserved": None,
        "png_plte_preserved": None,
        "png_trns_preserved": None,
        "jpeg_quantization_preserved": None,
        "jpeg_sampling_preserved": None,
        "unsupported_or_unchecked_items": [],
    }


def _alpha_details_default() -> dict[str, Any]:
    return {
        "alpha_present": None,
        "alpha_channel_preserved": None,
        "premultiplied_resize_used": None,
        "fully_transparent_rgb_zero": None,
        "semi_transparent_edges_reviewed": None,
        "alpha_exact": None,
    }


def _json_ready(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def canonical_json(payload: Any) -> str:
    if hasattr(payload, "to_dict"):
        payload = payload.to_dict()
    return json.dumps(_json_ready(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass
class ValidationFailure:
    stage: int
    field: str | None
    failure_code: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ImageCompressionTask:
    contract_version: str = TASK_CONTRACT_VERSION
    task_id: str = ""
    operation_mode: OperationMode | str = ""
    source_path: str = ""
    source_sha256_expected: str | None = None
    output_directory: str = ""
    preserve_format: bool = True
    max_width: int | None = None
    max_height: int | None = None
    max_file_size_bytes: int | None = None
    target_width: int | None = None
    target_height: int | None = None
    scale_ratio: float | None = None
    resize_policy: str | None = None
    quality_policy: str = ""
    metadata_policy: str = "PRESERVE_SUPPORTED_STRICT"
    overwrite_policy: str = "FAIL_IF_EXISTS"
    output_naming_policy: str = "TASK_ID_SUFFIX"
    visual_review_policy: str = ""
    request_context: dict[str, Any] = field(default_factory=dict)
    client_context: dict[str, Any] | None = None
    run_id: str | None = None
    test_case_id: str | None = None
    diagnostic_session_id: str | None = None
    issue_report_id: str | None = None
    expected_status: str | None = None
    required_checks: list[str] = field(default_factory=list)
    user_issue_context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))

    def canonical_json(self) -> str:
        return canonical_json(self)


@dataclass
class ImageCompressionResult:
    contract_version: str = RESULT_CONTRACT_VERSION
    task_contract_version: str = TASK_CONTRACT_VERSION
    task_id: str = ""
    operation_mode: OperationMode | str = ""
    run_id: str | None = None
    test_case_id: str | None = None
    diagnostic_session_id: str | None = None
    issue_report_id: str | None = None
    technical_status: TechnicalStatus | str = TechnicalStatus.PROCESSING_FAILED
    visual_review_status: VisualReviewStatus | str = VisualReviewStatus.NOT_AVAILABLE
    delivery_gate_status: DeliveryGateStatus | str = DeliveryGateStatus.CANNOT_MEET_SAFELY
    delivery_eligible: bool = False
    delivery_decision_reason: str = ""
    source_path: str | None = None
    source_sha256: str | None = None
    source_format: str | None = None
    source_dimensions: dict[str, int] | None = None
    source_size_bytes: int | None = None
    output_created: bool = False
    output_path: str | None = None
    output_sha256: str | None = None
    output_format: str | None = None
    output_dimensions: dict[str, int] | None = None
    output_size_bytes: int | None = None
    size_reduction_bytes: int | None = None
    size_reduction_ratio: float | None = None
    dimension_scale_ratio: float | None = None
    lossy: bool | None = None
    reencoded: bool | None = None
    resized: bool | None = None
    metadata_preserved: bool | None = None
    metadata_details: dict[str, Any] = field(default_factory=_metadata_details_default)
    alpha_preserved: bool | None = None
    alpha_details: dict[str, Any] = field(default_factory=_alpha_details_default)
    processing_seconds: float = 0.0
    stage_seconds: dict[str, float] = field(default_factory=dict)
    slowest_stage: str | None = None
    warnings: list[str] = field(default_factory=list)
    failure_code: str | None = None
    failure_reason: str | None = None
    risk_reasons: list[str] = field(default_factory=list)
    candidate_delivery_role: CandidateDeliveryRole | str = CandidateDeliveryRole.NONE
    evidence_paths: dict[str, Any] = field(default_factory=dict)
    validation_status: str = "NOT_RUN"
    validation_failures: list[dict[str, Any]] = field(default_factory=list)
    asset_manifest_path: str | None = None
    asset_comparison_path: str | None = None
    execution_log_path: str | None = None
    test_feedback: dict[str, Any] | None = None
    user_feedback: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if _contains_not_applicable(asdict(self)):
            raise ValueError("String not_applicable is forbidden in the unified result contract")

    def to_dict(self) -> dict[str, Any]:
        result = _json_ready(asdict(self))
        if tuple(result) != RESULT_FIELD_NAMES:
            raise ValueError("Unified result field order or count drifted from the frozen contract")
        return result

    def canonical_json(self) -> str:
        return canonical_json(self)


@dataclass
class TaskValidationResult:
    valid: bool
    task: ImageCompressionTask | None
    primary_failure_code: str | None
    validation_failures: list[ValidationFailure]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "task": self.task.to_dict() if self.task else None,
            "primary_failure_code": self.primary_failure_code,
            "validation_failures": [item.to_dict() for item in self.validation_failures],
        }


def _contains_not_applicable(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() == "not_applicable"
    if isinstance(value, Mapping):
        return any(_contains_not_applicable(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_not_applicable(item) for item in value)
    return False


def _contains_restricted_not_applicable(raw: Mapping[str, Any]) -> bool:
    """Reject the legacy sentinel only where booleans/numbers are expected.

    User-provided text (for example a description containing the literal word)
    is not a type pollution and must remain representable in the contract.
    """
    restricted = (
        "preserve_format",
        "max_width",
        "max_height",
        "max_file_size_bytes",
        "target_width",
        "target_height",
        "scale_ratio",
    )
    if any(_contains_not_applicable(raw.get(name)) for name in restricted):
        return True
    issue = raw.get("user_issue_context")
    if isinstance(issue, Mapping):
        return any(_contains_not_applicable(issue.get(name)) for name in ("include_source_image", "include_output_image", "include_diagnostic_logs", "privacy_confirmation"))
    return False


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        if any(re.sub(r"[^a-z]", "", str(key).strip().lower()) in _SENSITIVE_CONTEXT_KEYS for key in value):
            return True
        return any(_contains_sensitive_key(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_task(payload: Mapping[str, Any] | Any, *, check_resources: bool = True) -> TaskValidationResult:
    failures: list[ValidationFailure] = []

    def add(stage: int, field_name: str | None, code: str, reason: str) -> None:
        key = (stage, field_name, code)
        if not any((item.stage, item.field, item.failure_code) == key for item in failures):
            failures.append(ValidationFailure(stage, field_name, code, reason))

    if not isinstance(payload, Mapping):
        add(1, None, "REQUEST_OBJECT_INVALID", "The request must be a JSON object.")
        return TaskValidationResult(False, None, "REQUEST_OBJECT_INVALID", failures)

    raw = dict(payload)
    unknown = sorted((str(key) for key in raw if key not in TASK_FIELD_NAMES), key=lambda item: item.encode("utf-8"))
    for name in unknown:
        add(1, name, "UNKNOWN_FIELD", f"Unknown task field: {name}")

    required = (
        "contract_version",
        "task_id",
        "operation_mode",
        "source_path",
        "output_directory",
        "quality_policy",
        "metadata_policy",
        "visual_review_policy",
    )
    for name in required:
        if name not in raw:
            add(2, name, f"{name.upper()}_REQUIRED", f"Required field is missing: {name}")

    string_fields = (
        "contract_version",
        "task_id",
        "operation_mode",
        "source_path",
        "output_directory",
        "quality_policy",
        "metadata_policy",
        "overwrite_policy",
        "output_naming_policy",
        "visual_review_policy",
    )
    for name in string_fields:
        if name in raw and not isinstance(raw[name], str):
            add(2, name, "FIELD_TYPE_INVALID", f"{name} must be a string.")
    for name in ("source_sha256_expected", "resize_policy", "run_id", "test_case_id", "diagnostic_session_id", "issue_report_id", "expected_status"):
        if name in raw and raw[name] is not None and not isinstance(raw[name], str):
            add(2, name, "FIELD_TYPE_INVALID", f"{name} must be a string or null.")
    if "preserve_format" in raw and not isinstance(raw["preserve_format"], bool):
        add(2, "preserve_format", "FIELD_TYPE_INVALID", "preserve_format must be boolean.")
    for name in ("max_width", "max_height", "max_file_size_bytes", "target_width", "target_height"):
        if name in raw and raw[name] is not None and not _is_int(raw[name]):
            add(2, name, "FIELD_TYPE_INVALID", f"{name} must be an integer or null.")
    if "scale_ratio" in raw and raw["scale_ratio"] is not None and not _is_number(raw["scale_ratio"]):
        add(2, "scale_ratio", "FIELD_TYPE_INVALID", "scale_ratio must be a number or null.")
    for name in ("request_context",):
        if name in raw and not isinstance(raw[name], dict):
            add(2, name, "FIELD_TYPE_INVALID", f"{name} must be an object.")
    for name in ("client_context", "user_issue_context"):
        if name in raw and raw[name] is not None and not isinstance(raw[name], dict):
            add(2, name, "FIELD_TYPE_INVALID", f"{name} must be an object or null.")
    if "required_checks" in raw and not isinstance(raw["required_checks"], list):
        add(2, "required_checks", "FIELD_TYPE_INVALID", "required_checks must be an array.")
    if isinstance(raw.get("contract_version"), str) and raw["contract_version"] != TASK_CONTRACT_VERSION:
        add(2, "contract_version", "CONTRACT_VERSION_UNSUPPORTED", "Unsupported task contract version.")

    operation: OperationMode | None = None
    try:
        if isinstance(raw.get("operation_mode"), str):
            operation = OperationMode(raw["operation_mode"])
    except ValueError:
        operation = None

    if operation is not None:
        applicability = {
            OperationMode.LOSSLESS_COMPRESSION: ("max_width", "max_height", "max_file_size_bytes", "target_width", "target_height", "scale_ratio", "resize_policy"),
            OperationMode.RESIZE_REDUCTION: ("max_width", "max_height", "max_file_size_bytes"),
            OperationMode.UPLOAD_ADAPTATION: ("target_width", "target_height", "scale_ratio", "resize_policy"),
        }
        for name in applicability[operation]:
            if name in raw and raw[name] is not None:
                add(3, name, "FIELD_NOT_APPLICABLE", f"{name} is not applicable to {operation.value}.")
        if raw.get("visual_review_policy") == "STRICT_LOSSLESS_EVIDENCE" and operation is not OperationMode.LOSSLESS_COMPRESSION:
            add(3, "visual_review_policy", "FIELD_NOT_APPLICABLE", "STRICT_LOSSLESS_EVIDENCE is only applicable to LOSSLESS_COMPRESSION.")
    if raw.get("issue_report_id") is not None and raw.get("user_issue_context") is None:
        add(3, "issue_report_id", "FIELD_NOT_APPLICABLE", "issue_report_id requires user_issue_context.")

    issue = raw.get("user_issue_context")
    if isinstance(issue, dict):
        unknown_issue = sorted((str(key) for key in issue if key not in _USER_ISSUE_FIELDS), key=lambda item: item.encode("utf-8"))
        for name in unknown_issue:
            add(1, f"user_issue_context.{name}", "USER_ISSUE_CONTEXT_INVALID", f"Unknown user issue field: {name}.")
        if not issue:
            add(3, "user_issue_context", "USER_ISSUE_CONTEXT_INVALID", "user_issue_context must contain a user issue.")
        for name in ("issue_category", "user_description", "expected_result", "actual_result"):
            if not isinstance(issue.get(name), str) or not issue.get(name, "").strip():
                add(2, f"user_issue_context.{name}", "USER_ISSUE_CONTEXT_INVALID", f"{name} must be a non-empty string.")
        for name in ("reproduction_steps", "attachment_paths"):
            value = issue.get(name, [])
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                add(2, f"user_issue_context.{name}", "USER_ISSUE_CONTEXT_INVALID", f"{name} must be an array of strings.")
        for name in ("include_source_image", "include_output_image", "include_diagnostic_logs", "privacy_confirmation"):
            if name in issue and not isinstance(issue[name], bool):
                add(2, f"user_issue_context.{name}", "USER_ISSUE_CONTEXT_INVALID", f"{name} must be boolean.")

    if isinstance(raw.get("task_id"), str) and not _SAFE_ID.fullmatch(raw["task_id"]):
        add(4, "task_id", "TASK_ID_INVALID", "task_id must use safe characters and be 1-128 characters.")
    if isinstance(raw.get("operation_mode"), str) and operation is None:
        add(4, "operation_mode", "OPERATION_MODE_INVALID", "Unknown operation_mode.")
    source_sha = raw.get("source_sha256_expected")
    if isinstance(source_sha, str) and not _SHA256.fullmatch(source_sha):
        add(4, "source_sha256_expected", "SOURCE_SHA256_EXPECTED_INVALID", "Expected source SHA256 must be 64 lowercase hexadecimal characters.")
    if raw.get("preserve_format", True) is not True:
        add(4, "preserve_format", "PRESERVE_FORMAT_REQUIRED", "Stage 3 requires preserve_format=true.")
    for name in ("max_width", "max_height", "max_file_size_bytes"):
        value = raw.get(name)
        if _is_int(value) and value <= 0:
            add(4, name, "LIMIT_INVALID", f"{name} must be positive.")
    for name in ("target_width", "target_height"):
        value = raw.get(name)
        if _is_int(value) and value <= 0:
            add(4, name, "TARGET_DIMENSION_INVALID", f"{name} must be positive.")
    scale = raw.get("scale_ratio")
    if _is_number(scale) and not 0 < float(scale) < 1:
        add(4, "scale_ratio", "SCALE_RATIO_INVALID", "scale_ratio must be greater than zero and less than one.")
    if raw.get("resize_policy") is not None and raw.get("resize_policy") not in {"LANCZOS_HIGH_QUALITY", "INTER_AREA_PHOTO_ONLY"}:
        add(4, "resize_policy", "RESIZE_POLICY_INVALID", "Unsupported resize policy.")
    quality_by_mode = {
        OperationMode.LOSSLESS_COMPRESSION: "LOSSLESS_ONLY",
        OperationMode.RESIZE_REDUCTION: "SAME_FORMAT_HIGH_QUALITY",
        OperationMode.UPLOAD_ADAPTATION: "UPLOAD_ADAPTATION_V1",
    }
    if operation is not None and isinstance(raw.get("quality_policy"), str) and raw["quality_policy"] != quality_by_mode[operation]:
        add(4, "quality_policy", "QUALITY_POLICY_INVALID", "quality_policy does not match operation_mode.")
    if isinstance(raw.get("metadata_policy"), str) and raw["metadata_policy"] != "PRESERVE_SUPPORTED_STRICT":
        add(4, "metadata_policy", "METADATA_POLICY_INVALID", "Unsupported metadata policy.")
    if raw.get("overwrite_policy", "FAIL_IF_EXISTS") not in {"FAIL_IF_EXISTS", "UNIQUE_SUFFIX"}:
        add(4, "overwrite_policy", "OVERWRITE_POLICY_INVALID", "Unsupported overwrite policy.")
    if raw.get("output_naming_policy", "TASK_ID_SUFFIX") != "TASK_ID_SUFFIX":
        add(4, "output_naming_policy", "OUTPUT_NAMING_POLICY_INVALID", "Unsupported output naming policy.")
    if isinstance(raw.get("visual_review_policy"), str) and raw["visual_review_policy"] not in {"VALIDATION_STRICT", "PRODUCT_RISK_GATED", "STRICT_LOSSLESS_EVIDENCE"}:
        add(4, "visual_review_policy", "VISUAL_REVIEW_POLICY_INVALID", "Unsupported visual review policy.")
    for name in ("run_id", "test_case_id", "diagnostic_session_id", "issue_report_id"):
        value = raw.get(name)
        if isinstance(value, str) and not _SAFE_ID.fullmatch(value):
            add(4, name, f"{name.upper()}_INVALID", f"{name} has an invalid identifier format.")
    diagnostic_id = raw.get("diagnostic_session_id")
    if isinstance(diagnostic_id, str) and not _DIAGNOSTIC_ID.fullmatch(diagnostic_id):
        add(4, "diagnostic_session_id", "DIAGNOSTIC_SESSION_ID_INVALID", "diagnostic_session_id must be UUID or ULID shaped.")
    if isinstance(raw.get("expected_status"), str) and raw["expected_status"] not in _KNOWN_EXPECTED_STATUSES:
        add(4, "expected_status", "EXPECTED_STATUS_INVALID", "Unknown expected status.")
    checks = raw.get("required_checks", [])
    if isinstance(checks, list) and (any(not isinstance(item, str) or not item for item in checks) or len(checks) != len(set(checks)) or any(item not in _REGISTERED_CHECKS for item in checks)):
        add(4, "required_checks", "REQUIRED_CHECK_UNKNOWN", "required_checks must contain unique non-empty registered names.")
    if _contains_restricted_not_applicable(raw):
        add(4, None, "FIELD_TYPE_INVALID", "String not_applicable is forbidden in task boolean and numeric data.")

    if _contains_sensitive_key(raw.get("request_context")):
        add(3, "request_context", "REQUEST_CONTEXT_INVALID", "request_context must not contain account or secret material.")
    if _contains_sensitive_key(raw.get("client_context")):
        add(3, "client_context", "CLIENT_CONTEXT_INVALID", "client_context must not contain account or secret material.")

    internal_test_scope = bool(raw.get("run_id") or raw.get("test_case_id"))
    if (raw.get("expected_status") is not None or checks) and not internal_test_scope:
        if raw.get("expected_status") is not None:
            add(3, "expected_status", "FIELD_NOT_APPLICABLE", "expected_status is reserved for internal test tasks.")
        if checks:
            add(3, "required_checks", "FIELD_NOT_APPLICABLE", "required_checks is reserved for internal test tasks.")
    if internal_test_scope:
        if not raw.get("run_id"):
            add(5, "run_id", "RUN_ID_REQUIRED", "run_id is required for internal test tasks.")
        if not raw.get("test_case_id"):
            add(5, "test_case_id", "TEST_CASE_ID_REQUIRED", "test_case_id is required for internal test tasks.")

    if operation is OperationMode.RESIZE_REDUCTION:
        scale_present = raw.get("scale_ratio") is not None
        width_present = raw.get("target_width") is not None
        height_present = raw.get("target_height") is not None
        if scale_present and (width_present or height_present):
            add(5, "scale_ratio", "RESIZE_ARGUMENT_CONFLICT", "Use scale_ratio or target dimensions, never both.")
        elif not scale_present and width_present != height_present:
            add(5, "target_width" if width_present else "target_height", "TARGET_DIMENSION_INVALID", "Both target dimensions are required together.")
        elif not scale_present and not (width_present and height_present):
            add(5, "scale_ratio", "RESIZE_ARGUMENT_CONFLICT", "A scale ratio or both target dimensions are required.")
    if operation is OperationMode.UPLOAD_ADAPTATION and all(raw.get(name) is None for name in ("max_width", "max_height", "max_file_size_bytes")):
        add(5, "max_width", "LIMITS_MISSING", "Upload adaptation requires at least one limit.")
    issue = raw.get("user_issue_context")
    if isinstance(issue, dict):
        if not raw.get("issue_report_id"):
            add(5, "issue_report_id", "ISSUE_REPORT_ID_REQUIRED", "issue_report_id is required with user_issue_context.")
        includes_private = any(bool(issue.get(name)) for name in ("attachment_paths", "include_source_image", "include_output_image", "include_diagnostic_logs"))
        if includes_private and issue.get("privacy_confirmation") is not True:
            add(5, "user_issue_context", "PRIVACY_CONFIRMATION_REQUIRED", "Privacy confirmation is required before including attachments or logs.")

    if check_resources and isinstance(raw.get("source_path"), str) and isinstance(raw.get("output_directory"), str):
        source = Path(raw["source_path"])
        output_dir = Path(raw["output_directory"])
        if not source.is_absolute():
            add(6, "source_path", "SOURCE_PATH_INVALID", "source_path must be absolute.")
        elif not source.is_file():
            add(6, "source_path", "SOURCE_NOT_FOUND", "source_path does not exist or is not a file.")
        elif not os.access(source, os.R_OK):
            add(6, "source_path", "SOURCE_PATH_INVALID", "source_path is not readable.")
        if not output_dir.is_absolute() or (output_dir.exists() and not output_dir.is_dir()):
            add(6, "output_directory", "OUTPUT_DIRECTORY_INVALID", "output_directory must be an absolute directory path.")
        elif source.resolve() == output_dir.resolve():
            add(6, "output_directory", "OUTPUT_DIRECTORY_INVALID", "output_directory cannot be the source file.")
        else:
            # Validation must remain side-effect free.  A missing output
            # directory is accepted only when its existing parent is a
            # writable directory; the processor creates it after validation.
            probe = output_dir
            while not probe.exists() and probe != probe.parent:
                probe = probe.parent
            if not probe.exists() or not probe.is_dir() or not os.access(probe, os.W_OK):
                add(6, "output_directory", "OUTPUT_DIRECTORY_INVALID", "Output directory or its writable parent is unavailable.")
        if source.is_file() and isinstance(source_sha, str) and _SHA256.fullmatch(source_sha) and _hash_file(source) != source_sha:
            add(6, "source_sha256_expected", "SOURCE_SHA_MISMATCH", "Source SHA256 does not match the request.")
        if source.is_file() and operation is OperationMode.RESIZE_REDUCTION and raw.get("target_width") and raw.get("target_height"):
            try:
                from PIL import Image

                with Image.open(source) as image:
                    source_width, source_height = image.size
                target_width, target_height = int(raw["target_width"]), int(raw["target_height"])
                if target_width > source_width or target_height > source_height:
                    add(6, "target_width", "TARGET_DIMENSION_INVALID", "Resize reduction cannot enlarge the source.")
                expected_width = round(source_width * target_height / source_height)
                if abs(expected_width - target_width) > 1:
                    add(6, "target_width", "TARGET_DIMENSION_INVALID", "Target dimensions do not preserve the source aspect ratio within one pixel.")
            except OSError as exc:
                add(6, "source_path", "SOURCE_PATH_INVALID", f"Source image cannot be decoded: {exc}")

    field_index = {name: index for index, name in enumerate(TASK_FIELD_NAMES)}

    def failure_sort_key(item: ValidationFailure) -> tuple[Any, ...]:
        if item.stage == 1 and item.field:
            return item.stage, item.field.encode("utf-8"), item.failure_code
        return item.stage, field_index.get(item.field or "", len(field_index)), item.failure_code

    failures.sort(key=failure_sort_key)
    if failures:
        return TaskValidationResult(False, None, failures[0].failure_code, failures)

    normalized = {name: raw.get(name) for name in TASK_FIELD_NAMES}
    normalized.update(
        contract_version=raw.get("contract_version", TASK_CONTRACT_VERSION),
        preserve_format=raw.get("preserve_format", True),
        metadata_policy=raw.get("metadata_policy", "PRESERVE_SUPPORTED_STRICT"),
        overwrite_policy=raw.get("overwrite_policy", "FAIL_IF_EXISTS"),
        output_naming_policy=raw.get("output_naming_policy", "TASK_ID_SUFFIX"),
        request_context=dict(raw.get("request_context") or {}),
        required_checks=list(raw.get("required_checks") or []),
    )
    if operation is OperationMode.RESIZE_REDUCTION and normalized["resize_policy"] is None:
        normalized["resize_policy"] = "LANCZOS_HIGH_QUALITY"
    normalized["operation_mode"] = operation
    if normalized["scale_ratio"] is not None:
        normalized["scale_ratio"] = float(normalized["scale_ratio"])
    task = ImageCompressionTask(**normalized)
    if tuple(item.name for item in fields(task)) != TASK_FIELD_NAMES:
        raise RuntimeError("Unified task field order or count drifted from the frozen contract")
    return TaskValidationResult(True, task, None, [])


def base_result_for_task(task: ImageCompressionTask) -> ImageCompressionResult:
    return ImageCompressionResult(
        task_id=task.task_id,
        operation_mode=task.operation_mode,
        run_id=task.run_id,
        test_case_id=task.test_case_id,
        diagnostic_session_id=task.diagnostic_session_id,
        issue_report_id=task.issue_report_id,
        source_path=task.source_path,
    )
