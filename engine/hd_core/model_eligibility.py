"""Fail-closed model eligibility contracts for isolated E4K-03 research.

This module does not download or load model weights.  It only evaluates
provenance, licensing, file integrity, and declared runtime facts before a
candidate can reach model inference.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


MODEL_ELIGIBILITY_VERSION = "E4K_03_MODEL_ELIGIBILITY_V1"
PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
PENDING_MODEL = "PENDING_MODEL_INTEGRITY_AND_RUNTIME"
AUTHORIZED_DOWNLOAD = "ELIGIBLE_FOR_AUTHORIZED_DOWNLOAD"


class ModelEligibilityError(RuntimeError):
    """Invalid eligibility record or unsafe eligibility transition."""


@dataclass(frozen=True)
class ModelEligibilityRecord:
    model_id: str
    model_version: str
    model_role: str
    source_url_or_provider: str
    source_status: str
    source_evidence: str
    code_license_reference: str
    code_license_status: str
    weight_license_reference: str
    weight_license_status: str
    commercial_use_boundary: str
    redistribution_boundary: str
    model_file: str
    runtime_requirement: str
    hardware_requirement: str
    memory_requirement: str
    backend: str
    precision: str
    input_contract: Mapping[str, Any]
    output_contract: Mapping[str, Any]
    determinism_status: str
    onnx_feasibility: str
    openvino_feasibility: str
    expected_processing_cost: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def evaluate_pre_download(record: ModelEligibilityRecord) -> dict[str, Any]:
    """Evaluate source and licensing before any model file may be downloaded."""

    failures: list[str] = []
    if record.source_status != PASS or not record.source_url_or_provider.startswith(
        "https://"
    ):
        failures.append("UNVERIFIED_SOURCE")
    if record.code_license_status != PASS:
        failures.append("CODE_LICENSE_NOT_CONFIRMED")
    if record.weight_license_status != PASS:
        failures.append("WEIGHT_LICENSE_NOT_CONFIRMED")
    if _text(record.commercial_use_boundary).upper() in {
        "",
        "UNKNOWN",
        "UNCLEAR",
    }:
        failures.append("COMMERCIAL_USE_BOUNDARY_UNCLEAR")
    if _text(record.redistribution_boundary).upper() in {
        "",
        "UNKNOWN",
        "UNCLEAR",
    }:
        failures.append("REDISTRIBUTION_BOUNDARY_UNCLEAR")

    gate = PASS if not failures else BLOCKED
    return {
        "eligibility_version": MODEL_ELIGIBILITY_VERSION,
        **record.to_dict(),
        "pre_download_gate": gate,
        "model_sha256": None,
        "model_size": None,
        "model_integrity_status": "NOT_EVALUATED",
        "runtime_status": "NOT_EVALUATED",
        "model_eligibility": AUTHORIZED_DOWNLOAD if gate == PASS else BLOCKED,
        "block_reasons": failures,
        "model_inference_run": False,
        "model_benchmark": False,
    }


def finalize_eligibility(
    record: ModelEligibilityRecord,
    *,
    model_path: str | Path | None,
    expected_sha256: str | None,
    runtime_facts: Mapping[str, Any],
) -> dict[str, Any]:
    """Finalize a record after an authorized download and live runtime probe."""

    result = evaluate_pre_download(record)
    if result["pre_download_gate"] != PASS:
        return result

    failures: list[str] = []
    path = None if model_path is None else Path(model_path).expanduser().resolve()
    if path is None or not path.is_file():
        failures.append("HASH_MISSING")
        actual_sha = None
        size = None
    else:
        actual_sha = sha256_file(path)
        size = path.stat().st_size
        if not _text(expected_sha256):
            failures.append("EXPECTED_HASH_MISSING")
        elif actual_sha.lower() != str(expected_sha256).lower():
            failures.append("MODEL_HASH_MISMATCH")

    if runtime_facts.get("backend_available") is not True:
        failures.append("RUNTIME_UNAVAILABLE")
    if runtime_facts.get("memory_fits") is not True:
        failures.append("MEMORY_NOT_PROVEN")
    if runtime_facts.get("dependency_conflict") is True:
        failures.append("DEPENDENCY_CONFLICT")
    model_load_failed = runtime_facts.get("model_load_status") != PASS
    if model_load_failed:
        failures.append("MODEL_LOAD_NOT_PASS")

    result.update(
        {
            "model_file": None if path is None else str(path),
            "model_sha256": actual_sha,
            "model_size": size,
            "model_integrity_status": (
                PASS
                if actual_sha
                and expected_sha256
                and actual_sha.lower() == str(expected_sha256).lower()
                else BLOCKED
            ),
            "runtime_facts": dict(runtime_facts),
            "runtime_status": (
                FAIL
                if model_load_failed
                else PASS
                if runtime_facts.get("backend_available") is True
                and runtime_facts.get("memory_fits") is True
                and runtime_facts.get("dependency_conflict") is not True
                else BLOCKED
            ),
            "model_eligibility": PASS if not failures else BLOCKED,
            "block_reasons": failures,
        }
    )
    return result


__all__ = [
    "AUTHORIZED_DOWNLOAD",
    "BLOCKED",
    "FAIL",
    "MODEL_ELIGIBILITY_VERSION",
    "ModelEligibilityError",
    "ModelEligibilityRecord",
    "PASS",
    "PENDING_MODEL",
    "evaluate_pre_download",
    "finalize_eligibility",
    "sha256_file",
]
