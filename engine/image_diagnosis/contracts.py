from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np


DIAGNOSIS_CONTRACT_VERSION = "hdde.image-diagnosis.v1"
IMAGE_DIAGNOSIS_FEATURE_KEY = "image_diagnosis"


class ImageDiagnosisError(ValueError):
    """Base error for safe, read-only image diagnosis failures."""


class SourceChangedDuringDiagnosisError(ImageDiagnosisError):
    """Raised when the source changes while it is being diagnosed."""


@dataclass(frozen=True)
class DecodedDiagnosisImage:
    source_path: Path
    bgr: np.ndarray
    image_facts: dict[str, Any]
    source_sha256: str
    source_mtime_ns: int
    source_size_bytes: int


class DiagnosisImageAdapter(Protocol):
    adapter_id: str

    def decode(self, source_path: Path) -> DecodedDiagnosisImage: ...


@dataclass(frozen=True)
class DiagnosisIssue:
    status: str
    severity: str
    metrics: dict[str, Any]
    evidence: list[str]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecommendedAction:
    primary_action: str
    secondary_actions: list[str]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DiagnosisResult:
    engine_id: str
    adapter_id: str
    image_facts: dict[str, Any]
    quality_issues: dict[str, DiagnosisIssue]
    recommended_action: RecommendedAction
    source_integrity: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": DIAGNOSIS_CONTRACT_VERSION,
            "feature_key": IMAGE_DIAGNOSIS_FEATURE_KEY,
            "engine_id": self.engine_id,
            "adapter_id": self.adapter_id,
            "image_facts": dict(self.image_facts),
            "quality_issues": {key: issue.to_dict() for key, issue in self.quality_issues.items()},
            "recommended_action": self.recommended_action.to_dict(),
            "source_integrity": dict(self.source_integrity),
        }
