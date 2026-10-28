"""Isolated V3 white-balance restoration prototype.

This module is deliberately absent from :mod:`engine.color_correction`'s public
surface and from the formal D1/D2/D3 runtime.  It provides engineering evidence
only: controlled fixtures can verify deterministic colour adaptation, Alpha
preservation and hard protected-region invariants, but cannot prove commercial
image quality without the D57-COLOR-02 source/GT/rights set.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import numpy as np

from .color_management import (
    MANAGED_COLOR_SOURCE_ATOMIC_SNAPSHOT_VERSION,
    MANAGED_COLOR_SOURCE_PROVENANCE_VERSION,
    ManagedColorSource,
    _canonical_array_sha256,
    acquire_validated_managed_source_snapshot,
)


V3_WHITE_BALANCE_PROTOTYPE_VERSION = "hdde.d57.v3-white-balance.prototype.v0.10"
RGBA_ALPHA_MODE_CONTRACT_VERSION = "hdde.d57.rgba-alpha-mode-contract.v1"
EVIDENCE_IDENTITY_BINDING_VERSION = "hdde.d57.color-04-evidence-identity-binding.v2"
_ALPHA_MODE_NOT_APPLICABLE = "NOT_APPLICABLE"
_ALPHA_MODE_STRAIGHT_VALIDATED = "STRAIGHT_VALIDATED"
_ALPHA_MODE_PREMULTIPLIED = "PREMULTIPLIED"
_ALPHA_MODE_UNKNOWN = "UNKNOWN"
_ALPHA_MODE_VALUES = frozenset({
    _ALPHA_MODE_STRAIGHT_VALIDATED,
    _ALPHA_MODE_PREMULTIPLIED,
    _ALPHA_MODE_UNKNOWN,
})
_VALIDATED_ALPHA_PROVENANCE = "VALIDATED_COLOR_MANAGEMENT_DECODER_V1"

_LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
_MAX_GAIN = 1.22
_MIN_GAIN = 0.82
_MAX_STRENGTH = 0.68
_MIN_CAST_LOG2_SPAN = 0.06
_MAX_FINAL_LUMINANCE_MEAN_DELTA = 0.0015
_MAX_FINAL_LUMINANCE_P95_DELTA = 0.0035
_MAX_FINAL_LUMINANCE_MAX_DELTA = 0.005
_MAX_INDEPENDENT_REPLAY_RGB_BYTE_DELTA = 0
_HIGHLIGHT_CLIP_BYTE_THRESHOLD = 254
_HIGHEST_NEW_HIGHLIGHT_SAFE_BYTE = _HIGHLIGHT_CLIP_BYTE_THRESHOLD - 1
_BRIGHT_NEUTRAL_ANCHOR_SATURATION_MAX = 0.10
_BRIGHT_NEUTRAL_ANCHOR_DISPLAY_LUMINANCE_MIN = 0.65
_MAX_BRIGHT_NEUTRAL_ANCHOR_OPPOSITE_SHIFT_RATIO = 0.50
_PARTIAL_ALPHA_SOURCE_BYTE_DELTA = 16
_PARTIAL_ALPHA_MAX_SUPPORT_DISTANCE = 12
_PARTIAL_ALPHA_MIN_TRUSTED_OPAQUE_NEIGHBORS = 4
_PARTIAL_ALPHA_MAX_OUTCOME_COMPOSITE_RESIDUAL = 0.008


@dataclass(frozen=True)
class _V3WhiteBalancePrototypeResult:
    status: str
    candidate_image: np.ndarray | None
    disposition: str
    blocker: str | None
    diagnostics: dict[str, Any]
    evidence_identity: dict[str, Any] | None

    @property
    def modified(self) -> bool:
        return self.candidate_image is not None

    def to_record(self) -> dict[str, Any]:
        """Return a pixel-free record bound to its exact input and candidate."""

        identity = dict(self.evidence_identity or {})
        record_status = "VALID"
        record_blocker: str | None = None
        if not _valid_sha256(identity.get("source_sha256")):
            record_status = "INVALID"
            record_blocker = "EVIDENCE_RECORD_MISSING_SOURCE_BINDING"
        elif self.modified and not _valid_sha256(identity.get("candidate_sha256")):
            record_status = "INVALID"
            record_blocker = "EVIDENCE_RECORD_MISSING_CANDIDATE_BINDING"
        else:
            provenance_blocker = _provenance_hash_consistency_blocker(identity)
            if provenance_blocker is not None:
                record_status = "INVALID"
                record_blocker = provenance_blocker

        record = {
            "engine_version": V3_WHITE_BALANCE_PROTOTYPE_VERSION,
            "evidence_identity_binding_version": EVIDENCE_IDENTITY_BINDING_VERSION,
            "record_status": record_status,
            "record_blocker": record_blocker,
            "status": self.status,
            "candidate_available": self.modified,
            "disposition": self.disposition,
            "blocker": self.blocker,
            "evidence_authority": "CONTROLLED_FIXTURES_ONLY_NOT_COMMERCIAL_GT",
            "evidence_identity": identity,
            "diagnostics": dict(self.diagnostics),
        }
        record["record_identity_sha256"] = _record_identity_sha256(record)
        return record


def _valid_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _provenance_hash_consistency_blocker(
    identity: dict[str, Any],
) -> str | None:
    source_sha = identity.get("source_sha256")
    source_evidence_sha = identity.get("source_evidence_sha256")
    if source_evidence_sha != source_sha:
        return "EVIDENCE_PROVENANCE_HASH_CONSISTENCY_MISMATCH"

    provenance_state = identity.get("managed_source_provenance_validation")
    if provenance_state == "NOT_APPLICABLE":
        return None

    decoder_sha = identity.get("decoder_pixel_sha256")
    snapshot_sha = identity.get("processing_snapshot_sha256")
    if not all(
        _valid_sha256(value)
        for value in (decoder_sha, snapshot_sha, source_evidence_sha)
    ):
        return "EVIDENCE_PROVENANCE_HASH_CONSISTENCY_MISMATCH"
    if len({decoder_sha, snapshot_sha, source_evidence_sha}) != 1:
        return "EVIDENCE_PROVENANCE_HASH_CONSISTENCY_MISMATCH"
    return None


def _record_identity_sha256(record: dict[str, Any]) -> str:
    payload = dict(record)
    payload.pop("record_identity_sha256", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(b"HDDE_D57_EVIDENCE_RECORD_V1\0" + encoded).hexdigest().upper()


def _build_evidence_identity(
    source: np.ndarray,
    *,
    candidate: np.ndarray | None,
    alpha: np.ndarray | None,
    protected_mask: np.ndarray | None,
    mask_was_supplied: bool,
    color_space: str,
    alpha_mode: str,
    alpha_mode_provenance: str,
    managed_source_provenance_validation: str,
    managed_source_provenance_version: str | None,
    managed_source_snapshot_version: str | None,
    decoder_origin_binding: str,
    decoder_pixel_sha256: str | None,
    processing_snapshot_sha256: str | None,
) -> dict[str, Any]:
    source_array = np.asarray(source)
    source_sha256 = _canonical_array_sha256(source_array)
    mask_state = "PRESENT" if mask_was_supplied else "NONE"
    mask_sha = (
        _canonical_array_sha256(np.asarray(protected_mask, dtype=bool))
        if mask_was_supplied and protected_mask is not None
        else None
    )
    return {
        "source_sha256": source_sha256,
        "source_evidence_sha256": source_sha256,
        "candidate_sha256": (
            _canonical_array_sha256(np.asarray(candidate))
            if candidate is not None
            else None
        ),
        "alpha_sha256": (
            _canonical_array_sha256(np.asarray(alpha)) if alpha is not None else None
        ),
        "protected_mask_state": mask_state,
        "protected_mask_sha256": mask_sha,
        "width": int(source_array.shape[1]) if source_array.ndim >= 2 else None,
        "height": int(source_array.shape[0]) if source_array.ndim >= 1 else None,
        "channels": int(source_array.shape[2]) if source_array.ndim == 3 else None,
        "dtype": str(source_array.dtype),
        "color_space": color_space,
        "alpha_mode": alpha_mode,
        "alpha_mode_provenance": alpha_mode_provenance,
        "managed_source_provenance_validation": (
            managed_source_provenance_validation
        ),
        "managed_source_provenance_version": managed_source_provenance_version,
        "managed_source_snapshot_version": managed_source_snapshot_version,
        "decoder_origin_binding": decoder_origin_binding,
        "decoder_pixel_sha256": decoder_pixel_sha256,
        "processing_snapshot_sha256": processing_snapshot_sha256,
        "decode_time_pixel_sha256": decoder_pixel_sha256,
        "current_pixel_sha256": processing_snapshot_sha256,
    }


def validate_v3_evidence_record(
    record: dict[str, Any],
    *,
    source_image: np.ndarray,
    candidate_image: np.ndarray | None,
    hard_protection_mask: np.ndarray | None,
) -> tuple[bool, str | None]:
    """Validate the minimal V1 content bindings against supplied arrays."""

    if not isinstance(record, dict) or record.get("record_status") != "VALID":
        return False, "EVIDENCE_RECORD_INVALID"
    if record.get("evidence_identity_binding_version") != EVIDENCE_IDENTITY_BINDING_VERSION:
        return False, "EVIDENCE_BINDING_VERSION_MISMATCH"
    identity = record.get("evidence_identity")
    if not isinstance(identity, dict) or not _valid_sha256(identity.get("source_sha256")):
        return False, "EVIDENCE_RECORD_MISSING_SOURCE_BINDING"
    provenance_blocker = _provenance_hash_consistency_blocker(identity)
    if provenance_blocker is not None:
        return False, provenance_blocker
    if identity["source_sha256"] != _canonical_array_sha256(source_image):
        return False, "EVIDENCE_SOURCE_BINDING_MISMATCH"

    candidate_available = bool(record.get("candidate_available"))
    candidate_sha = identity.get("candidate_sha256")
    if candidate_available:
        if not _valid_sha256(candidate_sha):
            return False, "EVIDENCE_RECORD_MISSING_CANDIDATE_BINDING"
        if candidate_image is None:
            return False, "EVIDENCE_CANDIDATE_REQUIRED"
        if candidate_sha != _canonical_array_sha256(candidate_image):
            return False, "EVIDENCE_CANDIDATE_BINDING_MISMATCH"
    elif candidate_sha is not None:
        return False, "EVIDENCE_UNEXPECTED_CANDIDATE_BINDING"

    source_array = np.asarray(source_image)
    expected_alpha = (
        source_array[..., 3]
        if source_array.ndim == 3 and source_array.shape[2] == 4
        else None
    )
    expected_alpha_sha = (
        _canonical_array_sha256(expected_alpha) if expected_alpha is not None else None
    )
    if identity.get("alpha_sha256") != expected_alpha_sha:
        return False, "EVIDENCE_ALPHA_BINDING_MISMATCH"

    if hard_protection_mask is None:
        if identity.get("protected_mask_state") != "NONE":
            return False, "EVIDENCE_MASK_STATE_MISMATCH"
        if identity.get("protected_mask_sha256") is not None:
            return False, "EVIDENCE_UNEXPECTED_MASK_BINDING"
    else:
        if identity.get("protected_mask_state") != "PRESENT":
            return False, "EVIDENCE_MASK_STATE_MISMATCH"
        expected_mask_sha = _canonical_array_sha256(
            np.asarray(hard_protection_mask, dtype=bool)
        )
        if identity.get("protected_mask_sha256") != expected_mask_sha:
            return False, "EVIDENCE_MASK_BINDING_MISMATCH"

    if record.get("record_identity_sha256") != _record_identity_sha256(record):
        return False, "EVIDENCE_RECORD_IDENTITY_MISMATCH"
    return True, None


def _result(
    status: str,
    *,
    candidate: np.ndarray | None = None,
    blocker: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    evidence_identity: dict[str, Any] | None = None,
) -> _V3WhiteBalancePrototypeResult:
    return _V3WhiteBalancePrototypeResult(
        status=status,
        candidate_image=candidate,
        disposition="ISOLATED_REVIEW_ONLY" if candidate is not None else "KEEP_ORIGINAL",
        blocker=blocker,
        diagnostics=dict(diagnostics or {}),
        evidence_identity=dict(evidence_identity or {}),
    )


def _srgb_to_linear(values: np.ndarray) -> np.ndarray:
    values = np.clip(np.asarray(values, dtype=np.float32), 0.0, 1.0)
    return np.where(
        values <= 0.04045,
        values / 12.92,
        np.power((values + 0.055) / 1.055, 2.4),
    ).astype(np.float32)


def _linear_to_srgb(values: np.ndarray) -> np.ndarray:
    values = np.clip(np.asarray(values, dtype=np.float32), 0.0, 1.0)
    return np.where(
        values <= 0.0031308,
        values * 12.92,
        1.055 * np.power(values, 1.0 / 2.4) - 0.055,
    ).astype(np.float32)


def _srgb_to_linear_replay(values: np.ndarray) -> np.ndarray:
    """Decode sRGB in float64 for post-candidate safety measurements."""

    values = np.clip(np.asarray(values, dtype=np.float64), 0.0, 1.0)
    return np.where(
        values <= 0.04045,
        values / 12.92,
        np.power((values + 0.055) / 1.055, 2.4),
    )


def _linear_to_srgb_replay(values: np.ndarray) -> np.ndarray:
    """Encode sRGB in float64 for post-candidate safety measurements."""

    values = np.clip(np.asarray(values, dtype=np.float64), 0.0, 1.0)
    return np.where(
        values <= 0.0031308,
        values * 12.92,
        1.055 * np.power(values, 1.0 / 2.4) - 0.055,
    )


_SRGB_U8_TO_LINEAR_LUT = _srgb_to_linear(
    np.arange(256, dtype=np.float32) / 255.0
)


def _spatial_coverage(mask: np.ndarray) -> tuple[int, int, int]:
    """Count occupied 4x4 cells and represented row/column bands."""

    height, width = mask.shape
    occupied: list[tuple[int, int]] = []
    row_edges = np.linspace(0, height, 5, dtype=int)
    column_edges = np.linspace(0, width, 5, dtype=int)
    for row in range(4):
        for column in range(4):
            cell = mask[
                row_edges[row] : row_edges[row + 1],
                column_edges[column] : column_edges[column + 1],
            ]
            required = max(4, int(np.ceil(cell.size * 0.005)))
            if int(cell.sum()) >= required:
                occupied.append((row, column))
    return (
        len(occupied),
        len({row for row, _ in occupied}),
        len({column for _, column in occupied}),
    )


@dataclass(frozen=True)
class _CandidateSynthesis:
    candidate_rgb: np.ndarray
    neutral: np.ndarray
    neutral_medians: np.ndarray
    cast_log2_span: float
    occupied_cells: int
    occupied_rows: int
    occupied_columns: int
    neutral_ratio: float
    raw_gains: np.ndarray
    applied_gains: np.ndarray
    strength: float
    headroom_diagnostics: dict[str, Any]


def _mix_distribution(values: np.ndarray, prefix: str) -> dict[str, float]:
    if values.size == 0:
        return {
            f"{prefix}_min": 1.0,
            f"{prefix}_p05": 1.0,
            f"{prefix}_p50": 1.0,
            f"{prefix}_p95": 1.0,
        }
    return {
        f"{prefix}_min": round(float(values.min()), 8),
        f"{prefix}_p05": round(float(np.percentile(values, 5)), 8),
        f"{prefix}_p50": round(float(np.percentile(values, 50)), 8),
        f"{prefix}_p95": round(float(np.percentile(values, 95)), 8),
    }


def _synthesize_candidate_from_source(
    source_rgb: np.ndarray,
    analysis: np.ndarray,
    illuminant_evidence: np.ndarray,
    *,
    collect_diagnostics: bool = True,
) -> _CandidateSynthesis:
    """Build one deterministic source-authorized candidate in float32.

    Per-channel linear-sRGB headroom limits the actual per-pixel mix before
    quantization.  A channel below the existing 254-byte clipping gate may not
    be raised above 253; an already-highlight channel may not be raised above
    its source byte.  The smallest channel allowance scales the whole pixel's
    white-balance mix, preserving the original correction direction without a
    post-hoc channel clip or global exposure reduction.
    """

    source = np.asarray(source_rgb)
    region = np.asarray(analysis, dtype=bool)
    evidence = np.asarray(illuminant_evidence, dtype=bool)
    if source.ndim != 3 or source.shape[2] != 3 or source.dtype != np.uint8:
        raise ValueError("candidate synthesis requires a uint8 HxWx3 RGB array")
    if region.shape != source.shape[:2]:
        raise ValueError("analysis must match image height and width")
    if evidence.shape != source.shape[:2]:
        raise ValueError("illuminant_evidence must match image height and width")
    if np.any(evidence & ~region):
        raise ValueError("illuminant_evidence must be a subset of analysis")

    source_srgb = source.astype(np.float32) / 255.0
    maximum = source_srgb.max(axis=2)
    minimum = source_srgb.min(axis=2)
    saturation = np.divide(maximum - minimum, np.maximum(maximum, 1e-12))
    display_luminance = np.tensordot(source_srgb, _LUMA_WEIGHTS, axes=([2], [0]))
    neutral = (
        evidence
        & (saturation <= 0.22)
        & (display_luminance >= 0.08)
        & (display_luminance <= 0.92)
    )
    occupied_cells, occupied_rows, occupied_columns = _spatial_coverage(neutral)
    neutral_ratio = float(int(neutral.sum()) / max(int(evidence.sum()), 1))
    empty_headroom = {
        "highlight_headroom_policy": (
            "PER_PIXEL_MINIMUM_OF_PER_CHANNEL_LINEAR_SRGB_REMAINING_HEADROOM"
        ),
        "highlight_headroom_constraint_stage": "PRE_QUANTIZATION_ACTUAL_MIX",
        "highest_new_highlight_safe_byte": _HIGHEST_NEW_HIGHLIGHT_SAFE_BYTE,
        "headroom_limited_pixel_count": 0,
        "headroom_limited_channel_count": 0,
        "headroom_limited_pixel_ratio": 0.0,
    }
    if collect_diagnostics:
        empty_headroom.update(
            _mix_distribution(np.empty(0, dtype=np.float64), "headroom_safe_mix_factor")
        )
        empty_headroom.update(
            _mix_distribution(np.empty(0, dtype=np.float64), "base_mix_weight")
        )
        empty_headroom.update(
            _mix_distribution(np.empty(0, dtype=np.float64), "effective_mix_weight")
        )
    if not neutral.any():
        return _CandidateSynthesis(
            candidate_rgb=source.copy(),
            neutral=neutral,
            neutral_medians=np.zeros(3, dtype=np.float64),
            cast_log2_span=0.0,
            occupied_cells=occupied_cells,
            occupied_rows=occupied_rows,
            occupied_columns=occupied_columns,
            neutral_ratio=neutral_ratio,
            raw_gains=np.ones(3, dtype=np.float64),
            applied_gains=np.ones(3, dtype=np.float64),
            strength=0.0,
            headroom_diagnostics=empty_headroom,
        )

    source_linear = _SRGB_U8_TO_LINEAR_LUT[source]
    neutral_medians = np.median(source_linear[neutral], axis=0).astype(np.float64)
    if np.any(neutral_medians <= 1e-12):
        return _CandidateSynthesis(
            candidate_rgb=source.copy(),
            neutral=neutral,
            neutral_medians=neutral_medians,
            cast_log2_span=0.0,
            occupied_cells=occupied_cells,
            occupied_rows=occupied_rows,
            occupied_columns=occupied_columns,
            neutral_ratio=neutral_ratio,
            raw_gains=np.ones(3, dtype=np.float64),
            applied_gains=np.ones(3, dtype=np.float64),
            strength=0.0,
            headroom_diagnostics=empty_headroom,
        )
    cast_log2_span = float(np.ptp(np.log2(neutral_medians)))
    if cast_log2_span < _MIN_CAST_LOG2_SPAN:
        return _CandidateSynthesis(
            candidate_rgb=source.copy(),
            neutral=neutral,
            neutral_medians=neutral_medians,
            cast_log2_span=cast_log2_span,
            occupied_cells=occupied_cells,
            occupied_rows=occupied_rows,
            occupied_columns=occupied_columns,
            neutral_ratio=neutral_ratio,
            raw_gains=np.ones(3, dtype=np.float64),
            applied_gains=np.ones(3, dtype=np.float64),
            strength=0.0,
            headroom_diagnostics=empty_headroom,
        )

    neutral_target = float(np.exp(np.mean(np.log(neutral_medians))))
    raw_gains = neutral_target / neutral_medians
    evidence_confidence = float(np.clip(neutral_ratio / 0.18, 0.0, 1.0))
    coverage_confidence = float(np.clip(occupied_cells / 12.0, 0.0, 1.0))
    confidence = 0.55 * evidence_confidence + 0.45 * coverage_confidence
    strength = float(min(_MAX_STRENGTH, 0.46 + 0.22 * confidence))
    bounded_log_gains = np.clip(
        np.log(raw_gains),
        np.log(_MIN_GAIN),
        np.log(_MAX_GAIN),
    )
    applied_gains = np.exp(bounded_log_gains * strength).astype(np.float32)

    adapted_linear = source_linear * applied_gains[None, None, :]
    source_luminance = np.tensordot(source_linear, _LUMA_WEIGHTS, axes=([2], [0]))
    adapted_luminance = np.tensordot(adapted_linear, _LUMA_WEIGHTS, axes=([2], [0]))
    luminance_scale = np.divide(
        source_luminance,
        np.maximum(adapted_luminance, 1e-12),
        out=np.ones_like(source_luminance),
        where=adapted_luminance > 1e-12,
    )
    adapted_linear *= luminance_scale[..., None]

    chroma_weight = np.clip(1.0 - 0.55 * saturation, 0.45, 1.0)
    endpoint_weight = np.clip(
        np.minimum(display_luminance / 0.08, (1.0 - display_luminance) / 0.08),
        0.0,
        1.0,
    )
    base_mix_weight = chroma_weight * endpoint_weight
    base_mix_weight[~region] = 0.0

    target_delta = adapted_linear - source_linear
    safe_ceiling_byte = np.where(
        source < _HIGHLIGHT_CLIP_BYTE_THRESHOLD,
        _HIGHEST_NEW_HIGHLIGHT_SAFE_BYTE,
        source,
    )
    safe_ceiling_linear = _SRGB_U8_TO_LINEAR_LUT[safe_ceiling_byte]
    increasing = target_delta > np.float32(1e-8)
    per_channel_weight_limit = np.ones_like(target_delta)
    per_channel_weight_limit[increasing] = np.divide(
        (safe_ceiling_linear - source_linear)[increasing],
        target_delta[increasing],
    )
    per_channel_weight_limit = np.clip(per_channel_weight_limit, 0.0, 1.0)
    pixel_weight_limit = per_channel_weight_limit.min(axis=2)
    effective_mix_weight = np.minimum(base_mix_weight, pixel_weight_limit)
    effective_mix_weight[~region] = 0.0

    candidate_linear = source_linear + target_delta * effective_mix_weight[..., None]
    candidate_rgb = np.rint(_linear_to_srgb(candidate_linear) * 255.0).astype(np.uint8)
    candidate_rgb[~region] = source[~region]

    headroom_diagnostics: dict[str, Any] = {}
    if collect_diagnostics:
        eligible_mix = region & (base_mix_weight > np.float32(1e-8))
        safe_mix_factor = np.ones_like(base_mix_weight)
        safe_mix_factor[eligible_mix] = np.divide(
            effective_mix_weight[eligible_mix],
            base_mix_weight[eligible_mix],
        )
        limited_pixels = eligible_mix & (
            effective_mix_weight < base_mix_weight - np.float32(1e-7)
        )
        limited_channels = (
            increasing
            & region[..., None]
            & (
                per_channel_weight_limit
                < base_mix_weight[..., None] - np.float32(1e-7)
            )
        )
        mix_values = safe_mix_factor[eligible_mix]
        base_values = base_mix_weight[eligible_mix]
        effective_values = effective_mix_weight[eligible_mix]
        headroom_diagnostics = {
            "highlight_headroom_policy": (
                "PER_PIXEL_MINIMUM_OF_PER_CHANNEL_LINEAR_SRGB_REMAINING_HEADROOM"
            ),
            "highlight_headroom_constraint_stage": "PRE_QUANTIZATION_ACTUAL_MIX",
            "highest_new_highlight_safe_byte": _HIGHEST_NEW_HIGHLIGHT_SAFE_BYTE,
            "headroom_limited_pixel_count": int(limited_pixels.sum()),
            "headroom_limited_channel_count": int(limited_channels.sum()),
            "headroom_limited_pixel_ratio": round(
                float(int(limited_pixels.sum()) / max(int(eligible_mix.sum()), 1)),
                8,
            ),
        }
        headroom_diagnostics.update(
            _mix_distribution(mix_values, "headroom_safe_mix_factor")
        )
        headroom_diagnostics.update(
            _mix_distribution(base_values, "base_mix_weight")
        )
        headroom_diagnostics.update(
            _mix_distribution(effective_values, "effective_mix_weight")
        )
    return _CandidateSynthesis(
        candidate_rgb=candidate_rgb,
        neutral=neutral,
        neutral_medians=neutral_medians,
        cast_log2_span=cast_log2_span,
        occupied_cells=occupied_cells,
        occupied_rows=occupied_rows,
        occupied_columns=occupied_columns,
        neutral_ratio=neutral_ratio,
        raw_gains=raw_gains,
        applied_gains=applied_gains,
        strength=strength,
        headroom_diagnostics=headroom_diagnostics,
    )


def _replay_candidate_from_source(
    source_rgb: np.ndarray,
    analysis: np.ndarray,
    illuminant_evidence: np.ndarray,
) -> np.ndarray:
    """Recompute via the shared source-only deterministic synthesis contract."""

    return _synthesize_candidate_from_source(
        source_rgb,
        analysis,
        illuminant_evidence,
        collect_diagnostics=False,
    ).candidate_rgb


def _evaluate_bright_neutral_anchor_overshoot(
    source_rgb: np.ndarray,
    candidate_rgb: np.ndarray,
    neutral: np.ndarray,
) -> tuple[dict[str, Any], str | None]:
    """Reject a candidate that moves most trusted bright neutrals past neutral.

    The anchor authority is a strict, bright subset of the existing source-only
    neutral evidence.  Candidate pixels are measured only as an outcome and do
    not participate in illuminant estimation.
    """

    source = np.asarray(source_rgb)
    candidate = np.asarray(candidate_rgb)
    neutral_mask = np.asarray(neutral, dtype=bool)
    if source.shape != candidate.shape or source.ndim != 3 or source.shape[2] != 3:
        raise ValueError("normal-image protection requires matching HxWx3 arrays")
    if source.dtype != np.uint8 or candidate.dtype != np.uint8:
        raise ValueError("normal-image protection requires uint8 RGB arrays")
    if neutral_mask.shape != source.shape[:2]:
        raise ValueError("neutral must match image height and width")

    neutral_source = source[neutral_mask]
    neutral_candidate = candidate[neutral_mask]
    minimum_anchor_count = max(96, int(np.ceil(int(neutral_mask.sum()) * 0.004)))
    base_diagnostics: dict[str, Any] = {
        "normal_image_protection_policy": (
            "SOURCE_ONLY_BRIGHT_STRICT_NEUTRAL_MAJORITY_OPPOSITE_SHIFT_FAIL_CLOSED"
        ),
        "bright_neutral_anchor_reference_authority": (
            "OPAQUE_UNPROTECTED_SOURCE_NEUTRAL_PIXELS_ONLY"
        ),
        "bright_neutral_anchor_saturation_max": (
            _BRIGHT_NEUTRAL_ANCHOR_SATURATION_MAX
        ),
        "bright_neutral_anchor_display_luminance_min": (
            _BRIGHT_NEUTRAL_ANCHOR_DISPLAY_LUMINANCE_MIN
        ),
        "bright_neutral_anchor_minimum_count": minimum_anchor_count,
        "bright_neutral_anchor_count": 0,
        "bright_neutral_anchor_source_log2_span": 0.0,
        "bright_neutral_anchor_source_direction_aligned_count": 0,
        "bright_neutral_anchor_opposite_shift_count": 0,
        "bright_neutral_anchor_opposite_shift_ratio": 0.0,
        "bright_neutral_anchor_opposite_shift_ratio_limit": (
            _MAX_BRIGHT_NEUTRAL_ANCHOR_OPPOSITE_SHIFT_RATIO
        ),
        "normal_image_protection_gate": "NOT_EVALUABLE",
        "normal_image_protection_blocker": None,
    }
    if neutral_source.size == 0:
        return base_diagnostics, None

    neutral_source_srgb = neutral_source.astype(np.float32) / 255.0
    maximum = neutral_source_srgb.max(axis=1)
    minimum = neutral_source_srgb.min(axis=1)
    saturation = np.divide(maximum - minimum, np.maximum(maximum, 1e-12))
    display_luminance = neutral_source_srgb @ _LUMA_WEIGHTS
    anchor_selection = (
        (saturation <= _BRIGHT_NEUTRAL_ANCHOR_SATURATION_MAX)
        & (display_luminance >= _BRIGHT_NEUTRAL_ANCHOR_DISPLAY_LUMINANCE_MIN)
    )
    anchor_count = int(anchor_selection.sum())
    base_diagnostics["bright_neutral_anchor_count"] = anchor_count
    if anchor_count < minimum_anchor_count:
        return base_diagnostics, None

    source_linear = _SRGB_U8_TO_LINEAR_LUT[neutral_source[anchor_selection]].astype(
        np.float64
    )
    candidate_linear = _SRGB_U8_TO_LINEAR_LUT[
        neutral_candidate[anchor_selection]
    ].astype(np.float64)
    anchor_medians = np.median(source_linear, axis=0)
    anchor_log = np.log2(np.maximum(anchor_medians, 1e-12))
    anchor_direction = anchor_log - float(anchor_log.mean())
    direction_energy = float(np.dot(anchor_direction, anchor_direction))
    base_diagnostics["bright_neutral_anchor_source_log2_span"] = round(
        float(np.ptp(anchor_log)),
        8,
    )
    if direction_energy <= 1e-12:
        return base_diagnostics, None

    source_log = np.log2(np.maximum(source_linear, 1e-12))
    candidate_log = np.log2(np.maximum(candidate_linear, 1e-12))
    source_chroma = source_log - source_log.mean(axis=1, keepdims=True)
    candidate_chroma = candidate_log - candidate_log.mean(axis=1, keepdims=True)
    source_projection = source_chroma @ anchor_direction / direction_energy
    candidate_projection = candidate_chroma @ anchor_direction / direction_energy
    aligned = source_projection > 0.0
    aligned_count = int(aligned.sum())
    opposite_shift = aligned & (candidate_projection < 0.0)
    opposite_count = int(opposite_shift.sum())
    opposite_ratio = float(opposite_count / max(aligned_count, 1))
    base_diagnostics.update({
        "bright_neutral_anchor_source_direction_aligned_count": aligned_count,
        "bright_neutral_anchor_opposite_shift_count": opposite_count,
        "bright_neutral_anchor_opposite_shift_ratio": round(opposite_ratio, 8),
    })
    if aligned_count < minimum_anchor_count:
        return base_diagnostics, None
    if opposite_ratio > _MAX_BRIGHT_NEUTRAL_ANCHOR_OPPOSITE_SHIFT_RATIO:
        blocker = "BRIGHT_NEUTRAL_ANCHOR_OVERSHOOT"
        base_diagnostics["normal_image_protection_gate"] = "FAIL"
        base_diagnostics["normal_image_protection_blocker"] = blocker
        return base_diagnostics, blocker

    base_diagnostics["normal_image_protection_gate"] = "PASS"
    return base_diagnostics, None


def _paired_slices(
    height: int,
    width: int,
    row_offset: int,
    column_offset: int,
) -> tuple[tuple[slice, slice], tuple[slice, slice]]:
    """Return target and offset-neighbour slices without wraparound."""

    if row_offset >= 0:
        target_rows = slice(0, height - row_offset)
        neighbour_rows = slice(row_offset, height)
    else:
        target_rows = slice(-row_offset, height)
        neighbour_rows = slice(0, height + row_offset)
    if column_offset >= 0:
        target_columns = slice(0, width - column_offset)
        neighbour_columns = slice(column_offset, width)
    else:
        target_columns = slice(-column_offset, width)
        neighbour_columns = slice(0, width + column_offset)
    return (
        (target_rows, target_columns),
        (neighbour_rows, neighbour_columns),
    )


def _evaluate_partial_alpha_outcome(
    source_rgb: np.ndarray,
    replay_rgb: np.ndarray,
    analysis: np.ndarray,
    alpha: np.ndarray,
) -> tuple[dict[str, Any], str | None]:
    """Gate the replayed Alpha-edge outcome with source-only local authority.

    Candidate pixels never enter this gate.  Trusted support starts only from
    source-similar opaque clusters and may propagate through a bounded local
    path when the independently replayed correction field remains continuous.
    """

    source = np.asarray(source_rgb)
    replay = np.asarray(replay_rgb)
    region = np.asarray(analysis, dtype=bool)
    alpha_array = np.asarray(alpha)
    if source.shape != replay.shape or source.ndim != 3 or source.shape[2] != 3:
        raise ValueError("partial Alpha outcome requires matching HxWx3 arrays")
    if source.dtype != np.uint8 or replay.dtype != np.uint8:
        raise ValueError("partial Alpha outcome requires uint8 RGB arrays")
    if region.shape != source.shape[:2]:
        raise ValueError("analysis must match image height and width")
    if alpha_array.shape != source.shape[:2] or alpha_array.dtype != np.uint8:
        raise ValueError("alpha must be a matching uint8 plane")

    partial = region & (alpha_array < 255)
    opaque = region & (alpha_array == 255)
    partial_count = int(partial.sum())
    source_i16 = source.astype(np.int16)
    replay_i16 = replay.astype(np.int16)
    source_linear = _srgb_to_linear_replay(source.astype(np.float64) / 255.0)
    replay_linear = _srgb_to_linear_replay(replay.astype(np.float64) / 255.0)
    correction = replay_linear - source_linear
    alpha_unit = alpha_array.astype(np.float64) / 255.0

    source_to_replay_rgb_max = 0
    source_to_replay_black_max = 0.0
    source_to_replay_white_max = 0.0
    source_to_replay_background_gap = 0.0
    if partial_count:
        source_to_replay_rgb_max = int(
            np.max(np.abs(replay_i16[partial] - source_i16[partial]))
        )
        black_change = correction * alpha_unit[..., None]
        white_change = (
            replay_linear * alpha_unit[..., None] + (1.0 - alpha_unit[..., None])
        ) - (
            source_linear * alpha_unit[..., None] + (1.0 - alpha_unit[..., None])
        )
        source_to_replay_black_max = float(np.max(np.abs(black_change[partial])))
        source_to_replay_white_max = float(np.max(np.abs(white_change[partial])))
        source_to_replay_background_gap = float(
            np.max(np.abs(black_change[partial] - white_change[partial]))
        )

    height, width = region.shape
    all_neighbours = (
        (-1, -1),
        (-1, 0),
        (-1, 1),
        (0, -1),
        (0, 1),
        (1, -1),
        (1, 0),
        (1, 1),
    )
    trusted_neighbour_count = opaque.astype(np.int16)
    for row_offset, column_offset in all_neighbours:
        target, neighbour = _paired_slices(
            height,
            width,
            row_offset,
            column_offset,
        )
        source_distance = np.max(
            np.abs(source_i16[target] - source_i16[neighbour]),
            axis=2,
        )
        trusted_neighbour_count[target] += (
            opaque[target]
            & opaque[neighbour]
            & (source_distance <= _PARTIAL_ALPHA_SOURCE_BYTE_DELTA)
        ).astype(np.int16)
    trusted_opaque = opaque & (
        trusted_neighbour_count >= _PARTIAL_ALPHA_MIN_TRUSTED_OPAQUE_NEIGHBORS
    )

    source_reachable = trusted_opaque.copy()
    outcome_reachable = trusted_opaque.copy()
    source_distance_steps = np.full(region.shape, -1, dtype=np.int16)
    outcome_distance_steps = np.full(region.shape, -1, dtype=np.int16)
    source_distance_steps[trusted_opaque] = 0
    outcome_distance_steps[trusted_opaque] = 0
    outcome_path_residual = np.zeros(region.shape, dtype=np.float64)
    propagation_neighbours = ((-1, 0), (0, -1), (0, 1), (1, 0))

    for step in range(1, _PARTIAL_ALPHA_MAX_SUPPORT_DISTANCE + 1):
        source_new = np.zeros(region.shape, dtype=bool)
        outcome_new = np.zeros(region.shape, dtype=bool)
        step_best_residual = np.full(region.shape, np.inf, dtype=np.float64)
        for row_offset, column_offset in propagation_neighbours:
            target, neighbour = _paired_slices(
                height,
                width,
                row_offset,
                column_offset,
            )
            source_distance = np.max(
                np.abs(source_i16[target] - source_i16[neighbour]),
                axis=2,
            )
            source_similar = source_distance <= _PARTIAL_ALPHA_SOURCE_BYTE_DELTA
            source_pair = (
                partial[target]
                & ~source_reachable[target]
                & source_reachable[neighbour]
                & source_similar
            )
            source_new[target] |= source_pair

            correction_residual = np.max(
                np.abs(correction[target] - correction[neighbour]),
                axis=2,
            ) * alpha_unit[target]
            outcome_pair = (
                partial[target]
                & ~outcome_reachable[target]
                & outcome_reachable[neighbour]
                & source_similar
                & (
                    correction_residual
                    <= _PARTIAL_ALPHA_MAX_OUTCOME_COMPOSITE_RESIDUAL
                )
            )
            outcome_new[target] |= outcome_pair
            target_best = step_best_residual[target]
            np.minimum(
                target_best,
                np.where(outcome_pair, correction_residual, np.inf),
                out=target_best,
            )

        source_new &= ~source_reachable
        outcome_new &= ~outcome_reachable
        if source_new.any():
            source_distance_steps[source_new] = step
            source_reachable |= source_new
        if outcome_new.any():
            outcome_distance_steps[outcome_new] = step
            outcome_path_residual[outcome_new] = step_best_residual[outcome_new]
            outcome_reachable |= outcome_new
        if not source_new.any() and not outcome_new.any():
            break

    source_unsupported = partial & ~source_reachable
    outcome_unsupported = partial & ~outcome_reachable
    source_supported_partial = partial & source_reachable
    outcome_supported_partial = partial & outcome_reachable
    source_max_distance = (
        int(source_distance_steps[source_supported_partial].max())
        if source_supported_partial.any()
        else 0
    )
    outcome_max_distance = (
        int(outcome_distance_steps[outcome_supported_partial].max())
        if outcome_supported_partial.any()
        else 0
    )
    outcome_residual_max = (
        float(outcome_path_residual[outcome_supported_partial].max())
        if outcome_supported_partial.any()
        else 0.0
    )

    blocker: str | None = None
    if source_unsupported.any():
        blocker = "PARTIAL_ALPHA_SOURCE_SUPPORT_NOT_EVALUABLE"
    elif outcome_unsupported.any():
        blocker = "PARTIAL_ALPHA_OUTCOME_DISCONTINUITY"
    diagnostics: dict[str, Any] = {
        "partial_alpha_outcome_reference_authority": (
            "SOURCE_ONLY_TRUSTED_OPAQUE_SEEDS_AND_REPLAY_FIELD"
        ),
        "partial_alpha_source_support_policy": (
            "BOUNDED_4_NEIGHBOUR_PROPAGATION_FROM_SOURCE_SIMILAR_OPAQUE_CLUSTERS"
        ),
        "partial_alpha_source_similarity_byte_limit": _PARTIAL_ALPHA_SOURCE_BYTE_DELTA,
        "partial_alpha_min_trusted_opaque_neighbours": (
            _PARTIAL_ALPHA_MIN_TRUSTED_OPAQUE_NEIGHBORS
        ),
        "partial_alpha_max_support_distance": _PARTIAL_ALPHA_MAX_SUPPORT_DISTANCE,
        "partial_alpha_outcome_composite_residual_limit": (
            _PARTIAL_ALPHA_MAX_OUTCOME_COMPOSITE_RESIDUAL
        ),
        "partial_alpha_trusted_opaque_seed_count": int(trusted_opaque.sum()),
        "partial_alpha_source_supported_pixel_count": int(source_supported_partial.sum()),
        "partial_alpha_source_unsupported_pixel_count": int(source_unsupported.sum()),
        "partial_alpha_outcome_supported_pixel_count": int(outcome_supported_partial.sum()),
        "partial_alpha_outcome_unsupported_pixel_count": int(outcome_unsupported.sum()),
        "partial_alpha_source_support_max_distance": source_max_distance,
        "partial_alpha_outcome_support_max_distance": outcome_max_distance,
        "partial_alpha_outcome_composite_residual_max": round(outcome_residual_max, 8),
        "partial_alpha_source_to_replay_max_rgb_byte_delta": source_to_replay_rgb_max,
        "partial_alpha_source_to_replay_black_composite_max_delta": round(
            source_to_replay_black_max,
            8,
        ),
        "partial_alpha_source_to_replay_white_composite_max_delta": round(
            source_to_replay_white_max,
            8,
        ),
        "partial_alpha_source_to_replay_black_white_delta_gap_max": round(
            source_to_replay_background_gap,
            8,
        ),
        "partial_alpha_black_white_independent_authority": False,
        "partial_alpha_outcome_gate": "PASS" if blocker is None else "FAIL",
        "partial_alpha_outcome_blocker": blocker,
    }
    return diagnostics, blocker


def _log2_channel_span(linear_rgb: np.ndarray, mask: np.ndarray) -> float:
    medians = np.median(linear_rgb[mask], axis=0)
    medians = np.maximum(medians.astype(np.float64), 1e-6)
    return float(np.ptp(np.log2(medians)))


def _clipping_ratio(rgb_u8: np.ndarray, mask: np.ndarray) -> float:
    selected = rgb_u8[mask]
    if selected.size == 0:
        return 1.0
    clipped = np.any((selected <= 1) | (selected >= 254), axis=1)
    return float(clipped.mean())


def _evaluate_candidate_safety(
    source_rgb: np.ndarray,
    candidate_rgb: np.ndarray,
    analysis: np.ndarray,
    *,
    alpha: np.ndarray | None,
) -> tuple[dict[str, Any], str | None]:
    """Evaluate final uint8 pixels with non-compensatory safety gates.

    The limits are conservative engineering boundaries for this isolated
    prototype.  They are not D57-COLOR-02 commercial thresholds and do not
    grant delivery authority.
    """

    source = np.asarray(source_rgb)
    candidate = np.asarray(candidate_rgb)
    region = np.asarray(analysis, dtype=bool)
    if source.shape != candidate.shape or source.ndim != 3 or source.shape[2] != 3:
        raise ValueError("source_rgb and candidate_rgb must be matching HxWx3 arrays")
    if region.shape != source.shape[:2]:
        raise ValueError("analysis must match image height and width")
    if source.dtype != np.uint8 or candidate.dtype != np.uint8:
        raise ValueError("candidate safety evaluation requires uint8 RGB arrays")
    if not region.any():
        raise ValueError("candidate safety evaluation requires at least one analysis pixel")

    alpha_array: np.ndarray | None = None
    if alpha is None:
        illuminant_evidence = region
    else:
        alpha_array = np.asarray(alpha)
        if alpha_array.shape != source.shape[:2] or alpha_array.dtype != np.uint8:
            raise ValueError("alpha must be a matching uint8 plane")
        illuminant_evidence = region & (alpha_array == 255)

    expected = _replay_candidate_from_source(
        source,
        region,
        illuminant_evidence,
    )
    channel_region = region[..., None]
    source_shadow = (source <= 1) & channel_region
    source_highlight = (source >= _HIGHLIGHT_CLIP_BYTE_THRESHOLD) & channel_region
    candidate_shadow = (candidate <= 1) & channel_region
    candidate_highlight = (
        candidate >= _HIGHLIGHT_CLIP_BYTE_THRESHOLD
    ) & channel_region
    new_shadow = candidate_shadow & ~source_shadow
    new_highlight = candidate_highlight & ~source_highlight
    released_shadow = source_shadow & ~candidate_shadow
    released_highlight = source_highlight & ~candidate_highlight

    source_i16 = source.astype(np.int16)
    candidate_i16 = candidate.astype(np.int16)
    expected_i16 = expected.astype(np.int16)
    replay_delta = np.abs(candidate_i16 - expected_i16)
    replay_pixel_delta = np.max(replay_delta, axis=2)
    replay_max = int(replay_pixel_delta.max())
    replay_mismatched_pixels = int(
        (replay_pixel_delta > _MAX_INDEPENDENT_REPLAY_RGB_BYTE_DELTA).sum()
    )
    shadow_excursion = (
        int(np.max((source_i16 - candidate_i16)[new_shadow])) if new_shadow.any() else 0
    )
    highlight_excursion = (
        int(np.max((candidate_i16 - source_i16)[new_highlight])) if new_highlight.any() else 0
    )
    source_clip = _clipping_ratio(source, region)
    candidate_clip = _clipping_ratio(candidate, region)

    source_linear = _SRGB_U8_TO_LINEAR_LUT[source]
    candidate_linear = _SRGB_U8_TO_LINEAR_LUT[candidate]
    source_luminance = np.tensordot(source_linear, _LUMA_WEIGHTS, axes=([2], [0]))
    candidate_luminance = np.tensordot(candidate_linear, _LUMA_WEIGHTS, axes=([2], [0]))
    luminance_delta = np.abs(candidate_luminance - source_luminance)[region]
    luminance_mean = float(luminance_delta.mean())
    luminance_p95 = float(np.percentile(luminance_delta, 95))
    luminance_max = float(luminance_delta.max())

    partial_count = 0
    partial_replay_max = 0
    partial_replay_mismatched_pixels = 0
    partial_black_max = 0.0
    partial_white_max = 0.0
    partial_background_gap = 0.0
    outcome_diagnostics: dict[str, Any] = {}
    outcome_blocker: str | None = None
    if alpha_array is not None:
        partial = region & (alpha_array < 255)
        partial_count = int(partial.sum())
        if partial_count:
            expected_linear = _srgb_to_linear_replay(
                expected.astype(np.float64) / 255.0
            )
            partial_replay_max = int(replay_pixel_delta[partial].max())
            partial_replay_mismatched_pixels = int(
                (
                    replay_pixel_delta[partial]
                    > _MAX_INDEPENDENT_REPLAY_RGB_BYTE_DELTA
                ).sum()
            )
            alpha_unit = alpha_array.astype(np.float64) / 255.0
            candidate_linear64 = _srgb_to_linear_replay(
                candidate.astype(np.float64) / 255.0
            )
            black_candidate = candidate_linear64 * alpha_unit[..., None]
            black_expected = expected_linear * alpha_unit[..., None]
            white_candidate = black_candidate + (1.0 - alpha_unit[..., None])
            white_expected = black_expected + (1.0 - alpha_unit[..., None])
            black_change = black_candidate - black_expected
            white_change = white_candidate - white_expected
            partial_black_max = float(np.max(np.abs(black_change[partial])))
            partial_white_max = float(np.max(np.abs(white_change[partial])))
            partial_background_gap = float(
                np.max(np.abs(black_change[partial] - white_change[partial]))
            )
        outcome_diagnostics, outcome_blocker = _evaluate_partial_alpha_outcome(
            source,
            expected,
            region,
            alpha_array,
        )

    diagnostics: dict[str, Any] = {
        "safety_threshold_authority": "CONTROLLED_ENGINEERING_BOUNDARY_NOT_COMMERCIAL_FREEZE",
        "clipping_gate_policy": "PER_CHANNEL_NEW_CLIPPING_NON_COMPENSATORY",
        "source_clipping_ratio": round(source_clip, 8),
        "candidate_clipping_ratio": round(candidate_clip, 8),
        "new_clipping_growth": round(float(candidate_clip - source_clip), 8),
        "new_shadow_clipped_channel_count": int(new_shadow.sum()),
        "new_highlight_clipped_channel_count": int(new_highlight.sum()),
        "new_shadow_clipped_pixel_count": int(np.any(new_shadow, axis=2).sum()),
        "new_highlight_clipped_pixel_count": int(np.any(new_highlight, axis=2).sum()),
        "released_shadow_clipped_channel_count": int(released_shadow.sum()),
        "released_highlight_clipped_channel_count": int(released_highlight.sum()),
        "new_shadow_max_byte_excursion": shadow_excursion,
        "new_highlight_max_byte_excursion": highlight_excursion,
        "independent_replay_policy": "SOURCE_ONLY_SHARED_FLOAT32_SYNTHESIS_RECOMPUTE",
        "candidate_reference_authority": (
            "SOURCE_DRIVEN_INDEPENDENT_REPLAY_NOT_CANDIDATE_NEIGHBORS"
        ),
        "independent_replay_max_rgb_byte_delta": replay_max,
        "independent_replay_mismatched_pixel_count": replay_mismatched_pixels,
        "independent_replay_rgb_byte_limit": _MAX_INDEPENDENT_REPLAY_RGB_BYTE_DELTA,
        "final_luminance_policy": "FINAL_UINT8_LINEAR_SRGB_ABSOLUTE_ERROR",
        "final_luminance_mean_abs_delta": round(luminance_mean, 8),
        "final_luminance_p95_abs_delta": round(luminance_p95, 8),
        "final_luminance_max_abs_delta": round(luminance_max, 8),
        "final_luminance_mean_limit": _MAX_FINAL_LUMINANCE_MEAN_DELTA,
        "final_luminance_p95_limit": _MAX_FINAL_LUMINANCE_P95_DELTA,
        "final_luminance_max_limit": _MAX_FINAL_LUMINANCE_MAX_DELTA,
        "partial_alpha_policy": (
            "EXACT_CANDIDATE_REPLAY_INTEGRITY_PLUS_SOURCE_ONLY_OUTCOME_SAFETY"
        ),
        "partial_alpha_pixel_count": partial_count,
        "partial_alpha_replay_max_rgb_byte_delta": partial_replay_max,
        "partial_alpha_replay_mismatched_pixel_count": partial_replay_mismatched_pixels,
        "partial_alpha_candidate_replay_black_composite_max_delta": round(
            partial_black_max,
            8,
        ),
        "partial_alpha_candidate_replay_white_composite_max_delta": round(
            partial_white_max,
            8,
        ),
        "partial_alpha_candidate_replay_black_white_delta_gap_max": round(
            partial_background_gap,
            8,
        ),
    }
    diagnostics.update(outcome_diagnostics)

    blocker: str | None = None
    if new_shadow.any():
        blocker = "NEW_SHADOW_CLIPPING"
    elif new_highlight.any():
        blocker = "NEW_HIGHLIGHT_CLIPPING"
    elif partial_replay_max > _MAX_INDEPENDENT_REPLAY_RGB_BYTE_DELTA:
        blocker = "PARTIAL_ALPHA_INDEPENDENT_REPLAY_MISMATCH"
    elif (
        luminance_mean > _MAX_FINAL_LUMINANCE_MEAN_DELTA
        or luminance_p95 > _MAX_FINAL_LUMINANCE_P95_DELTA
        or luminance_max > _MAX_FINAL_LUMINANCE_MAX_DELTA
    ):
        blocker = "FINAL_LUMINANCE_DRIFT"
    elif replay_max > _MAX_INDEPENDENT_REPLAY_RGB_BYTE_DELTA:
        blocker = "CANDIDATE_INDEPENDENT_REPLAY_MISMATCH"
    elif outcome_blocker is not None:
        blocker = outcome_blocker
    diagnostics["candidate_safety_gate"] = "PASS" if blocker is None else "FAIL"
    diagnostics["candidate_safety_blocker"] = blocker
    return diagnostics, blocker


def run_v3_white_balance_prototype(
    image: np.ndarray | ManagedColorSource,
    *,
    input_order: str = "RGB",
    hard_protection_mask: np.ndarray | None = None,
    alpha_mode: str | None = None,
) -> _V3WhiteBalancePrototypeResult:
    """Build one bounded, review-only white-balance candidate.

    The prototype accepts only the D57-COLOR-03 proven 8-bit sRGB RGB/RGBA
    array domain.  It requires neutral-looking pixels distributed across the
    frame, estimates a robust global illuminant, applies bounded von-Kries-like
    gains in linear sRGB, preserves source luminance, and restores protected or
    Alpha-hidden pixels byte-for-byte.
    """

    managed_source = image if isinstance(image, ManagedColorSource) else None
    managed_snapshot = (
        acquire_validated_managed_source_snapshot(managed_source)
        if managed_source is not None
        else None
    )
    managed_provenance = managed_snapshot
    array = (
        managed_snapshot.pixels
        if managed_snapshot is not None
        else np.asarray(image)
    )
    order = str(input_order).upper()
    if order not in {"RGB", "BGR"}:
        raise ValueError("input_order must be RGB or BGR")
    if (
        managed_snapshot is not None
        and managed_snapshot.valid
        and order != managed_snapshot.input_order
    ):
        raise ValueError("input_order must match the validated managed source")

    alpha_mode_was_explicit = alpha_mode is not None
    requested_alpha_mode = (
        _ALPHA_MODE_UNKNOWN if alpha_mode is None else str(alpha_mode).upper()
    )
    if alpha_mode is not None and requested_alpha_mode not in _ALPHA_MODE_VALUES:
        raise ValueError("alpha_mode must be STRAIGHT_VALIDATED, PREMULTIPLIED, or UNKNOWN")
    has_rgba_shape = bool(array.ndim == 3 and array.shape[2] == 4)
    alpha_for_identity = array[..., 3].copy() if has_rgba_shape else None
    mask_was_supplied = hard_protection_mask is not None
    raw_mask_for_identity = (
        np.array(hard_protection_mask, dtype=bool, copy=True, order="C")
        if mask_was_supplied
        else None
    )
    if raw_mask_for_identity is not None:
        raw_mask_for_identity.setflags(write=False)
    if (
        has_rgba_shape
        and managed_source is not None
        and managed_provenance is not None
        and managed_provenance.valid
        and managed_provenance.alpha_mode == _ALPHA_MODE_STRAIGHT_VALIDATED
    ):
        effective_alpha_mode = _ALPHA_MODE_STRAIGHT_VALIDATED
        alpha_mode_provenance = _VALIDATED_ALPHA_PROVENANCE
    elif has_rgba_shape and managed_source is not None:
        effective_alpha_mode = _ALPHA_MODE_UNKNOWN
        alpha_mode_provenance = "INVALID"
    elif has_rgba_shape:
        effective_alpha_mode = requested_alpha_mode
        alpha_mode_provenance = "UNAVAILABLE_BARE_ARRAY"
    else:
        effective_alpha_mode = _ALPHA_MODE_NOT_APPLICABLE
        alpha_mode_provenance = _ALPHA_MODE_NOT_APPLICABLE
    identity_color_space = (
        "VALIDATED_SRGB_WORKING_DOMAIN"
        if managed_provenance is not None and managed_provenance.valid
        else "ASSUMED_8BIT_SRGB_ARRAY"
    )
    provenance_validation = (
        "PASS"
        if managed_provenance is not None and managed_provenance.valid
        else ("FAIL" if managed_provenance is not None else "NOT_APPLICABLE")
    )
    provenance_version = (
        managed_provenance.provenance_version
        if managed_provenance is not None
        else None
    )
    snapshot_version = (
        managed_provenance.snapshot_version
        if managed_provenance is not None
        else None
    )
    decoder_origin_binding = (
        managed_provenance.decoder_origin_binding
        if managed_provenance is not None
        else "NOT_APPLICABLE"
    )
    decoder_pixel_sha256 = (
        managed_provenance.decode_time_pixel_sha256
        if managed_provenance is not None
        else None
    )
    processing_snapshot_sha256 = (
        managed_provenance.processing_snapshot_sha256
        if managed_provenance is not None
        else None
    )

    def finish(
        status: str,
        *,
        candidate: np.ndarray | None = None,
        blocker: str | None = None,
        diagnostics: dict[str, Any] | None = None,
        protected_mask: np.ndarray | None = raw_mask_for_identity,
    ) -> _V3WhiteBalancePrototypeResult:
        identity = _build_evidence_identity(
            array,
            candidate=candidate,
            alpha=alpha_for_identity,
            protected_mask=protected_mask,
            mask_was_supplied=mask_was_supplied,
            color_space=identity_color_space,
            alpha_mode=effective_alpha_mode,
            alpha_mode_provenance=alpha_mode_provenance,
            managed_source_provenance_validation=provenance_validation,
            managed_source_provenance_version=provenance_version,
            managed_source_snapshot_version=snapshot_version,
            decoder_origin_binding=decoder_origin_binding,
            decoder_pixel_sha256=decoder_pixel_sha256,
            processing_snapshot_sha256=processing_snapshot_sha256,
        )
        return _result(
            status,
            candidate=candidate,
            blocker=blocker,
            diagnostics=diagnostics,
            evidence_identity=identity,
        )

    if array.ndim != 3 or array.shape[2] not in {3, 4}:
        return finish(
            "PROTECTION_BLOCKED",
            blocker="UNSUPPORTED_PROTOTYPE_IMAGE_SHAPE",
            diagnostics={"input_shape": list(array.shape)},
        )
    if array.dtype != np.uint8:
        return finish(
            "PROTECTION_BLOCKED",
            blocker="UNSUPPORTED_PROTOTYPE_BIT_DEPTH",
            diagnostics={"input_dtype": str(array.dtype), "supported_dtype": "uint8"},
        )

    height, width = array.shape[:2]
    if hard_protection_mask is None:
        protected = np.zeros((height, width), dtype=bool)
        protected.setflags(write=False)
    else:
        protected = raw_mask_for_identity
        if protected.shape != (height, width):
            raise ValueError("hard_protection_mask must match image height and width")

    if managed_provenance is not None and not managed_provenance.valid:
        return finish(
            "INPUT_INELIGIBLE",
            blocker=managed_provenance.blocker
            or "MANAGED_SOURCE_PROVENANCE_INVALID",
            diagnostics={
                "managed_color_source_provenance_seal": (
                    MANAGED_COLOR_SOURCE_PROVENANCE_VERSION
                ),
                "managed_color_source_atomic_snapshot": (
                    MANAGED_COLOR_SOURCE_ATOMIC_SNAPSHOT_VERSION
                ),
                "provenance_validation": "FAIL",
                "provenance_blocker": managed_provenance.blocker,
                "decoder_origin_binding": (
                    managed_provenance.decoder_origin_binding
                ),
                "pixel_object_identity": (
                    managed_provenance.pixel_object_identity
                ),
                "pixel_content_identity": (
                    managed_provenance.pixel_content_identity
                ),
                "contract_identity": managed_provenance.contract_identity,
                "decode_time_pixel_sha256": (
                    managed_provenance.decode_time_pixel_sha256
                ),
                "processing_snapshot_sha256": (
                    managed_provenance.processing_snapshot_sha256
                ),
                "snapshot_private_memory": (
                    managed_provenance.snapshot_private_memory
                ),
                "snapshot_contiguous": managed_provenance.snapshot_contiguous,
                "snapshot_writeable": managed_provenance.snapshot_writeable,
                "rgba_alpha_mode_contract": RGBA_ALPHA_MODE_CONTRACT_VERSION,
                "alpha_mode": effective_alpha_mode,
                "alpha_mode_provenance": alpha_mode_provenance,
                "rgba_alpha_mode_authorization_gate": "FAIL",
                "global_wb_authorized": False,
            },
            protected_mask=protected,
        )

    if has_rgba_shape and (
        effective_alpha_mode != _ALPHA_MODE_STRAIGHT_VALIDATED
        or alpha_mode_provenance != _VALIDATED_ALPHA_PROVENANCE
        or (
            alpha_mode_was_explicit
            and requested_alpha_mode != _ALPHA_MODE_STRAIGHT_VALIDATED
        )
    ):
        return finish(
            "INPUT_INELIGIBLE",
            blocker=(
                "PREMULTIPLIED_ALPHA_UNSUPPORTED"
                if requested_alpha_mode == _ALPHA_MODE_PREMULTIPLIED
                else (
                    "UNKNOWN_ALPHA_MODE_UNSUPPORTED"
                    if alpha_mode_was_explicit
                    and requested_alpha_mode == _ALPHA_MODE_UNKNOWN
                    else "RGBA_ALPHA_MODE_PROVENANCE_REQUIRED"
                )
            ),
            diagnostics={
                "rgba_alpha_mode_contract": RGBA_ALPHA_MODE_CONTRACT_VERSION,
                "alpha_mode": effective_alpha_mode,
                "alpha_mode_provenance": alpha_mode_provenance,
                "rgba_alpha_mode_authorization_gate": "FAIL",
                "global_wb_authorized": False,
            },
            protected_mask=protected,
        )

    source_color = array[..., :3]
    source_rgb = source_color[..., ::-1].copy() if order == "BGR" else source_color.copy()
    if array.shape[2] == 4:
        alpha = array[..., 3].copy()
        visible = alpha.astype(np.float32) > 255.0 * 0.01
    else:
        alpha = None
        visible = np.ones((height, width), dtype=bool)
    analysis = visible & ~protected
    if alpha is None:
        illuminant_evidence = analysis.copy()
        illuminant_evidence_policy = "ALL_UNPROTECTED_RGB_SOURCE_PIXELS"
        partial_alpha_evidence_excluded = 0
    else:
        illuminant_evidence = analysis & (alpha == 255)
        illuminant_evidence_policy = "OPAQUE_UNPROTECTED_SOURCE_PIXELS_ONLY"
        partial_alpha_evidence_excluded = int(
            (analysis & (alpha < 255)).sum()
        )
    base_diagnostics: dict[str, Any] = {
        "managed_color_source_provenance_seal": (
            MANAGED_COLOR_SOURCE_PROVENANCE_VERSION
            if managed_source is not None
            else "NOT_APPLICABLE"
        ),
        "managed_color_source_atomic_snapshot": (
            MANAGED_COLOR_SOURCE_ATOMIC_SNAPSHOT_VERSION
            if managed_source is not None
            else "NOT_APPLICABLE"
        ),
        "provenance_validation": provenance_validation,
        "provenance_blocker": (
            managed_provenance.blocker if managed_provenance is not None else None
        ),
        "decoder_origin_binding": decoder_origin_binding,
        "pixel_object_identity": (
            managed_provenance.pixel_object_identity
            if managed_provenance is not None
            else "NOT_APPLICABLE"
        ),
        "pixel_content_identity": (
            managed_provenance.pixel_content_identity
            if managed_provenance is not None
            else "NOT_APPLICABLE"
        ),
        "contract_identity": (
            managed_provenance.contract_identity
            if managed_provenance is not None
            else "NOT_APPLICABLE"
        ),
        "decoder_pixel_sha256": decoder_pixel_sha256,
        "processing_snapshot_sha256": processing_snapshot_sha256,
        "source_evidence_sha256": _canonical_array_sha256(array),
        "decode_time_pixel_sha256": decoder_pixel_sha256,
        "current_pixel_sha256": processing_snapshot_sha256,
        "snapshot_private_memory": (
            managed_provenance.snapshot_private_memory
            if managed_provenance is not None
            else "NOT_APPLICABLE"
        ),
        "snapshot_contiguous": (
            managed_provenance.snapshot_contiguous
            if managed_provenance is not None
            else "NOT_APPLICABLE"
        ),
        "snapshot_writeable": (
            managed_provenance.snapshot_writeable
            if managed_provenance is not None
            else "NOT_APPLICABLE"
        ),
        "rgba_alpha_mode_contract": RGBA_ALPHA_MODE_CONTRACT_VERSION,
        "alpha_mode": effective_alpha_mode,
        "alpha_mode_provenance": alpha_mode_provenance,
        "rgba_alpha_mode_authorization_gate": (
            "PASS" if alpha is not None else "NOT_APPLICABLE"
        ),
        "global_wb_authorized": False,
        "working_domain": "LINEAR_SRGB_FROM_8BIT_SRGB",
        "input_order": order,
        "width": width,
        "height": height,
        "alpha_present": alpha is not None,
        "visible_pixel_count": int(visible.sum()),
        "hidden_pixel_count": int((~visible).sum()),
        "protected_pixel_count": int(protected.sum()),
        "illuminant_evidence_policy": illuminant_evidence_policy,
        "illuminant_evidence_pixel_count": int(illuminant_evidence.sum()),
        "partial_alpha_illuminant_evidence_excluded_pixel_count": (
            partial_alpha_evidence_excluded
        ),
        "formal_runtime_integrated": False,
        "auto_delivery_authority": False,
    }
    if int(analysis.sum()) < 96:
        return finish(
            "NOT_EVALUABLE",
            blocker="INSUFFICIENT_UNPROTECTED_VISIBLE_PIXELS",
            diagnostics=base_diagnostics,
            protected_mask=protected,
        )

    synthesis = _synthesize_candidate_from_source(
        source_rgb,
        analysis,
        illuminant_evidence,
    )
    neutral = synthesis.neutral
    neutral_count = int(neutral.sum())
    minimum_neutral_count = max(
        96,
        int(np.ceil(int(illuminant_evidence.sum()) * 0.004)),
    )
    occupied_cells = synthesis.occupied_cells
    occupied_rows = synthesis.occupied_rows
    occupied_columns = synthesis.occupied_columns
    neutral_ratio = synthesis.neutral_ratio
    base_diagnostics.update({
        "neutral_pixel_count": neutral_count,
        "neutral_pixel_ratio": round(neutral_ratio, 6),
        "minimum_neutral_pixel_count": minimum_neutral_count,
        "neutral_occupied_cells_4x4": occupied_cells,
        "neutral_occupied_row_bands": occupied_rows,
        "neutral_occupied_column_bands": occupied_columns,
    })
    if (
        neutral_count < minimum_neutral_count
        or occupied_cells < 4
        or occupied_rows < 2
        or occupied_columns < 2
    ):
        return finish(
            "NOT_EVALUABLE",
            blocker="INSUFFICIENT_DISTRIBUTED_NEUTRAL_EVIDENCE",
            diagnostics=base_diagnostics,
            protected_mask=protected,
        )

    neutral_medians = synthesis.neutral_medians
    if np.any(neutral_medians <= 1e-6):
        return finish(
            "NOT_EVALUABLE",
            blocker="DEGENERATE_NEUTRAL_EVIDENCE",
            diagnostics=base_diagnostics,
            protected_mask=protected,
        )
    cast_log2_span = synthesis.cast_log2_span
    base_diagnostics.update({
        "neutral_linear_rgb_median": [round(float(value), 8) for value in neutral_medians],
        "source_neutral_log2_span": round(cast_log2_span, 8),
    })
    if cast_log2_span < _MIN_CAST_LOG2_SPAN:
        return finish(
            "NOT_APPLICABLE",
            blocker="NO_MEANINGFUL_GLOBAL_CAST",
            diagnostics=base_diagnostics,
            protected_mask=protected,
        )

    raw_gains = synthesis.raw_gains
    applied_gains = synthesis.applied_gains
    strength = synthesis.strength
    candidate_rgb = synthesis.candidate_rgb.copy()
    candidate_rgb[~visible] = source_rgb[~visible]
    candidate_rgb[protected] = source_rgb[protected]

    source_linear_measured = _SRGB_U8_TO_LINEAR_LUT[source_rgb]
    candidate_linear_measured = _SRGB_U8_TO_LINEAR_LUT[candidate_rgb]
    after_span = _log2_channel_span(candidate_linear_measured, neutral)
    improvement_ratio = float(1.0 - after_span / max(cast_log2_span, 1e-8))
    normal_image_diagnostics, normal_image_blocker = (
        _evaluate_bright_neutral_anchor_overshoot(
            source_rgb,
            candidate_rgb,
            neutral,
        )
    )
    safety_diagnostics, safety_blocker = _evaluate_candidate_safety(
        source_rgb,
        candidate_rgb,
        analysis,
        alpha=alpha,
    )
    changed = np.any(candidate_rgb != source_rgb, axis=2) & analysis
    absolute_delta = np.abs(
        candidate_rgb.astype(np.int16) - source_rgb.astype(np.int16)
    )
    mean_delta = float(absolute_delta[analysis].mean())
    p95_delta = float(np.percentile(absolute_delta[analysis], 95))
    source_highlight_pixel = np.any(
        source_rgb >= _HIGHLIGHT_CLIP_BYTE_THRESHOLD,
        axis=2,
    )
    non_highlight_changed = changed & ~source_highlight_pixel
    source_luminance_measured = np.tensordot(
        source_linear_measured,
        _LUMA_WEIGHTS,
        axes=([2], [0]),
    )
    candidate_luminance_measured = np.tensordot(
        candidate_linear_measured,
        _LUMA_WEIGHTS,
        axes=([2], [0]),
    )
    signed_luminance_mean_delta = float(
        (
            candidate_luminance_measured[analysis]
            - source_luminance_measured[analysis]
        ).mean()
    )
    candidate_neutral_medians = np.median(
        candidate_linear_measured[neutral],
        axis=0,
    )
    base_diagnostics.update({
        "illuminant_raw_gains": [round(float(value), 8) for value in raw_gains],
        "applied_linear_gains": [round(float(value), 8) for value in applied_gains],
        "correction_strength": round(strength, 8),
        "candidate_neutral_linear_rgb_median": [
            round(float(value), 8) for value in candidate_neutral_medians
        ],
        "candidate_neutral_log2_span": round(after_span, 8),
        "neutral_error_improvement_ratio": round(improvement_ratio, 8),
        "changed_visible_unprotected_pixels": int(changed.sum()),
        "non_highlight_changed_pixel_count": int(non_highlight_changed.sum()),
        "mean_rgb_byte_delta": round(mean_delta, 6),
        "p95_rgb_byte_delta": round(p95_delta, 6),
        "signed_linear_luminance_mean_delta": round(
            signed_luminance_mean_delta,
            8,
        ),
        "luminance_policy": "SOURCE_LINEAR_LUMINANCE_PRESERVED_AND_FINAL_UINT8_GATED",
        "hard_protection_policy": "PIXEL_EXACT",
        "hidden_rgb_policy": "ALPHA_LE_1_PERCENT_PIXEL_EXACT",
    })
    base_diagnostics.update(synthesis.headroom_diagnostics)
    base_diagnostics.update(normal_image_diagnostics)
    base_diagnostics["global_wb_authorized"] = True
    base_diagnostics.update(safety_diagnostics)
    if safety_blocker is not None:
        return finish(
            "PROTECTION_BLOCKED",
            blocker=safety_blocker,
            diagnostics=base_diagnostics,
            protected_mask=protected,
        )
    if normal_image_blocker is not None:
        return finish(
            "NOT_APPLICABLE",
            blocker=normal_image_blocker,
            diagnostics=base_diagnostics,
            protected_mask=protected,
        )
    if improvement_ratio < 0.10:
        return finish(
            "PROTECTION_BLOCKED",
            blocker="NEUTRAL_CAST_NOT_MEANINGFULLY_REDUCED",
            diagnostics=base_diagnostics,
            protected_mask=protected,
        )
    if not changed.any():
        return finish(
            "NOT_APPLICABLE",
            blocker="NO_PIXEL_LEVEL_CORRECTION",
            diagnostics=base_diagnostics,
            protected_mask=protected,
        )

    output_color = candidate_rgb[..., ::-1] if order == "BGR" else candidate_rgb
    if alpha is None:
        output = np.ascontiguousarray(output_color)
    else:
        output = np.ascontiguousarray(np.dstack((output_color, alpha)))
    return finish(
        "CANDIDATE_READY",
        candidate=output,
        diagnostics=base_diagnostics,
        protected_mask=protected,
    )


__all__ = [
    "EVIDENCE_IDENTITY_BINDING_VERSION",
    "RGBA_ALPHA_MODE_CONTRACT_VERSION",
    "V3_WHITE_BALANCE_PROTOTYPE_VERSION",
    "run_v3_white_balance_prototype",
    "validate_v3_evidence_record",
]
