"""D1 color-correction usability decision layer.

This module observes JPEG/PNG pixels and decides whether a later correction
stage may run.  It never changes pixels and never emits correction parameters.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import weakref
from dataclasses import asdict, dataclass, field
from enum import Enum
from itertools import product
from pathlib import Path
from typing import Any, Iterable, Sequence

import cv2
import numpy as np
from PIL import Image, ImageOps


D1_SCHEMA_VERSION = "hdde.color-usability.schema.v2"
D1_ENGINE_VERSION = "hdde.d1-color-usability.v1.7"
D1_RULE_VERSION = "hdde.color-usability.rules.v1.7"
SOURCE_FINGERPRINT_VERSION = "hdde.source-fingerprint.v1"
_PERSON_REGION_CONTRACT_VERSION = "hdde.person-region-contract.v3"
_PERSON_REGION_BINDING_VERSION = "hdde.person-region-decision-binding.v2"
_PERSON_REGION_BINDING_KEY = secrets.token_bytes(32)
_PERSON_REGION_AUTO = "AUTO"
_PERSON_REGION_EXPLICIT_NONE = "EXPLICIT_NONE"
_PERSON_REGION_EXPLICIT_BOXES = "EXPLICIT_BOXES"
MAX_ANALYSIS_SIDE = 960
LAB_ENCODING_TOLERANCE = 0.5
RGB_8_16_EQUIVALENCE_RADIUS = (
    (0.5 / 255.0)
    + (0.5 / 65535.0)
    + (4.0 * float(np.finfo(np.float32).eps))
)


class ColorStatus(str, Enum):
    NORMAL = "NORMAL"
    YELLOW_CAST = "YELLOW_CAST"
    BLUE_CAST = "BLUE_CAST"
    OTHER_CAST = "OTHER_CAST"
    UNCERTAIN = "UNCERTAIN"


class ExposureStatus(str, Enum):
    PASS = "PASS"
    TOO_DARK = "TOO_DARK"
    TOO_BRIGHT = "TOO_BRIGHT"
    UNCERTAIN = "UNCERTAIN"


class ColorObservability(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class D1Action(str, Enum):
    AUTO_CORRECT = "AUTO_CORRECT"
    KEEP_ORIGINAL = "KEEP_ORIGINAL"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(frozen=True)
class Evidence:
    code: str
    target: str
    weight: float
    detail: str


@dataclass(frozen=True)
class _PersonRegionContract:
    version: str
    mode: str
    source_width: int
    source_height: int
    source_regions: tuple[tuple[int, int, int, int], ...]
    digest: str


@dataclass(frozen=True)
class _PersonRegionBinding:
    version: str
    digest: str
    owner: weakref.ReferenceType[ColorUsabilityDecision]


@dataclass(frozen=True)
class ColorUsabilityDecision:
    schema_version: str
    engine_version: str
    rule_version: str
    source_fingerprint: str
    image_facts: dict[str, Any]
    color_observability: ColorObservability
    global_color_facts: dict[str, Any]
    neutral_color_facts: dict[str, Any]
    skin_color_facts: dict[str, Any]
    low_chroma_color_facts: dict[str, Any]
    spatial_color_facts: dict[str, Any]
    illuminant_status: str
    dominant_color_risk: str
    scene_intent: str
    color_appearance_evidence: dict[str, Any]
    correction_justification: dict[str, Any]
    support_evidence: tuple[Evidence, ...]
    conflict_evidence: tuple[Evidence, ...]
    confidence: float
    risk: float
    color_status: ColorStatus
    exposure_status: ExposureStatus
    d1_action: D1Action
    # Runtime-only fields are deliberately excluded from ``__init__`` so the
    # previously public constructor keeps its original callable contract.
    # D1 attaches both values after constructing the immutable public record;
    # hand-built decisions therefore fail closed before D2 can touch pixels.
    _person_region_contract: _PersonRegionContract | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )
    _person_region_binding: _PersonRegionBinding | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        # Person/face coordinates and their binding digest are runtime-only.
        # They must not enter Shadow, Replay, API, or formal result records.
        value.pop("_person_region_contract", None)
        value.pop("_person_region_binding", None)
        value["color_observability"] = self.color_observability.value
        value["color_status"] = self.color_status.value
        value["exposure_status"] = self.exposure_status.value
        value["d1_action"] = self.d1_action.value
        return value


def _round(value: float) -> float:
    return round(float(value), 4)


def _fingerprint_source_array(
    image: Image.Image | np.ndarray,
    input_order: str,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Return a full-resolution canonical array used only for source binding."""

    if isinstance(image, Image.Image):
        oriented = ImageOps.exif_transpose(image)
        raw = np.asarray(oriented)
        if oriented.mode.startswith("I;16") or (
            oriented.mode == "I"
            and np.issubdtype(raw.dtype, np.integer)
            and raw.size > 0
            and int(raw.min()) >= 0
            and int(raw.max()) <= 65535
        ):
            array = raw.astype(np.uint16, copy=False)
        else:
            bands = oriented.getbands()
            alpha = np.asarray(oriented.getchannel("A"), dtype=np.uint8) if "A" in bands else None
            rgb = np.asarray(oriented.convert("RGB"), dtype=np.uint8)
            array = np.dstack((rgb, alpha)) if alpha is not None else rgb
        order = "RGB"
    else:
        array = np.asarray(image)
        order = input_order.upper()

    if array.ndim == 2:
        array = np.repeat(array[..., None], 3, axis=2)
    if array.ndim != 3 or array.shape[2] not in {3, 4}:
        raise ValueError("source fingerprint expects a gray, RGB/BGR, or RGBA/BGRA image")
    if order not in {"RGB", "BGR"}:
        raise ValueError("input_order must be RGB or BGR")

    color = array[..., :3]
    alpha = array[..., 3:4] if array.shape[2] == 4 else None
    if order == "BGR":
        color = color[..., ::-1]

    metadata: dict[str, Any] = {
        "version": SOURCE_FINGERPRINT_VERSION,
        "width": int(array.shape[1]),
        "height": int(array.shape[0]),
        "channels": int(array.shape[2]),
        "source_dtype": str(array.dtype),
        "source_bit_depth_per_channel": int(array.dtype.itemsize * 8),
        "channel_order": "RGBA" if alpha is not None else "RGB",
    }
    if np.issubdtype(array.dtype, np.integer):
        canonical = np.dstack((color, alpha)) if alpha is not None else color
        little_endian = canonical.dtype.newbyteorder("<")
        payload = np.ascontiguousarray(canonical.astype(little_endian, copy=False))
        metadata["numeric_representation"] = "native_integer"
    elif np.issubdtype(array.dtype, np.floating):
        finite = color[np.isfinite(color)]
        if finite.size == 0:
            raise ValueError("source fingerprint image contains no finite pixels")
        minimum, maximum = float(finite.min()), float(finite.max())
        if minimum < 0.0 or maximum > 255.0:
            raise ValueError("floating image range must be 0..1 or 0..255")
        color_scale = 1.0 if maximum <= 1.0 else 255.0
        canonical_color = np.clip(
            np.nan_to_num(color.astype(np.float32), nan=0.0, posinf=color_scale, neginf=0.0)
            / color_scale,
            0.0,
            1.0,
        )
        if alpha is not None:
            alpha_float = np.nan_to_num(alpha.astype(np.float32), nan=0.0, posinf=255.0, neginf=0.0)
            alpha_scale = 1.0 if float(alpha_float.max(initial=0.0)) <= 1.0 else 255.0
            canonical_alpha = np.clip(alpha_float / alpha_scale, 0.0, 1.0)
            canonical = np.dstack((canonical_color, canonical_alpha))
            metadata["alpha_scale"] = alpha_scale
        else:
            canonical = canonical_color
        payload = np.ascontiguousarray(canonical.astype("<f4", copy=False))
        metadata["numeric_representation"] = "normalized_float32"
        metadata["color_scale"] = color_scale
    else:
        raise ValueError(f"unsupported image dtype for source fingerprint: {array.dtype}")
    return payload, metadata


def compute_source_fingerprint(
    image: Image.Image | np.ndarray,
    *,
    input_order: str = "RGB",
) -> str:
    """Hash canonical decoded pixels without retaining paths, pixels, or identity."""

    payload, metadata = _fingerprint_source_array(image, input_order)
    digest = hashlib.sha256()
    digest.update(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    digest.update(b"\0")
    digest.update(payload.tobytes(order="C"))
    return f"{SOURCE_FINGERPRINT_VERSION}:{digest.hexdigest()}"


def _normalise_array(image: np.ndarray, input_order: str) -> tuple[np.ndarray, np.ndarray]:
    array = np.asarray(image)
    if array.ndim == 2:
        array = np.repeat(array[..., None], 3, axis=2)
    if array.ndim != 3 or array.shape[2] not in {3, 4}:
        raise ValueError("D1 expects a gray, RGB/BGR, or RGBA/BGRA image array")

    alpha = array[..., 3] if array.shape[2] == 4 else None
    color = array[..., :3]
    if input_order.upper() not in {"RGB", "BGR"}:
        raise ValueError("input_order must be RGB or BGR")
    if input_order.upper() == "BGR":
        color = color[..., ::-1]

    if np.issubdtype(color.dtype, np.integer):
        maximum = float(np.iinfo(color.dtype).max)
        rgb = color.astype(np.float32) / maximum
        valid = np.ones(color.shape[:2], dtype=bool) if alpha is None else alpha.astype(np.float32) > maximum * 0.01
    elif np.issubdtype(color.dtype, np.floating):
        finite = color[np.isfinite(color)]
        if finite.size == 0:
            raise ValueError("D1 image contains no finite pixels")
        minimum, maximum = float(finite.min()), float(finite.max())
        if minimum < 0.0 or maximum > 255.0:
            raise ValueError("floating image range must be 0..1 or 0..255")
        scale = 1.0 if maximum <= 1.0 else 255.0
        rgb = np.nan_to_num(color.astype(np.float32), nan=0.0, posinf=scale, neginf=0.0) / scale
        if alpha is None:
            valid = np.ones(color.shape[:2], dtype=bool)
        else:
            alpha_float = np.nan_to_num(alpha.astype(np.float32), nan=0.0)
            alpha_scale = 1.0 if float(alpha_float.max(initial=0.0)) <= 1.0 else 255.0
            valid = alpha_float > alpha_scale * 0.01
    else:
        raise ValueError(f"unsupported image dtype: {color.dtype}")
    return np.ascontiguousarray(np.clip(rgb, 0.0, 1.0), dtype=np.float32), valid


def _prepare_image(
    image: Image.Image | np.ndarray,
    input_order: str,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if isinstance(image, Image.Image):
        oriented = ImageOps.exif_transpose(image)
        raw = np.asarray(oriented)
        if oriented.mode.startswith("I;16") or (
            oriented.mode == "I"
            and np.issubdtype(raw.dtype, np.integer)
            and raw.size > 0
            and int(raw.min()) >= 0
            and int(raw.max()) <= 65535
        ):
            raw = raw.astype(np.uint16, copy=False)
            rgb, valid = _normalise_array(raw, "RGB")
            source_dtype = "uint16"
            source_bit_depth = 16
        else:
            bands = oriented.getbands()
            alpha = np.asarray(oriented.getchannel("A"), dtype=np.uint8) if "A" in bands else None
            rgb, valid = _normalise_array(
                np.dstack((np.asarray(oriented.convert("RGB"), dtype=np.uint8), alpha)) if alpha is not None
                else np.asarray(oriented.convert("RGB"), dtype=np.uint8),
                "RGB",
            )
            source_dtype = "uint8"
            source_bit_depth = 8
    else:
        raw = np.asarray(image)
        source_dtype = str(raw.dtype)
        source_bit_depth = int(raw.dtype.itemsize * 8)
        rgb, valid = _normalise_array(raw, input_order)

    source_height, source_width = rgb.shape[:2]
    scale = min(1.0, MAX_ANALYSIS_SIDE / max(source_width, source_height))
    if scale < 1.0:
        size = (max(1, int(round(source_width * scale))), max(1, int(round(source_height * scale))))
        # Straight-alpha RGB below the visibility threshold is undefined image
        # payload. Replace it before area resampling so hidden colors cannot
        # bleed into visible analysis pixels at transparency boundaries.
        resize_source = rgb.copy()
        resize_source[~valid] = 0.5
        rgb = cv2.resize(resize_source, size, interpolation=cv2.INTER_AREA)
        valid = cv2.resize(valid.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0
    facts = {
        "width": source_width,
        "height": source_height,
        "source_dtype": source_dtype,
        "source_bit_depth_per_channel": source_bit_depth,
        "source_numeric_range": (
            f"0..{np.iinfo(raw.dtype).max}"
            if np.issubdtype(raw.dtype, np.integer)
            else "0..1-or-0..255"
        ),
        "canonicalization": "native-range-to-normalized-domain",
        "analysis_dtype": str(rgb.dtype),
        "analysis_range": "0.0..1.0",
        "native_precision_preserved_before_analysis": True,
        "channel_order": "RGB",
        "analysis_width": int(rgb.shape[1]),
        "analysis_height": int(rgb.shape[0]),
        "valid_pixel_ratio": _round(valid.mean()),
    }
    return rgb, valid, facts


def _detect_faces(
    rgb: np.ndarray,
    valid: np.ndarray | None = None,
) -> list[tuple[int, int, int, int]]:
    detection_rgb = rgb
    if valid is not None:
        visible = np.asarray(valid, dtype=bool)
        if visible.shape != rgb.shape[:2]:
            raise ValueError("D1 face-detection mask shape does not match image")
        detection_rgb = rgb.copy()
        detection_rgb[~visible] = 0.5
    preview = np.clip(detection_rgb * 255.0, 0.0, 255.0).astype(np.uint8)
    gray = cv2.cvtColor(preview, cv2.COLOR_RGB2GRAY)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if cascade.empty():
        return []
    return [tuple(int(part) for part in box) for box in cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(28, 28)
    )]


def _box_mask(shape: tuple[int, int], boxes: Iterable[Sequence[int]]) -> np.ndarray:
    height, width = shape
    mask = np.zeros(shape, dtype=bool)
    for box in boxes:
        if len(box) != 4:
            raise ValueError("person/face regions must contain x, y, width, height")
        x, y, box_width, box_height = (int(value) for value in box)
        x0, y0 = min(width, max(0, x)), min(height, max(0, y))
        x1 = max(0, min(width, x + max(0, box_width)))
        y1 = max(0, min(height, y + max(0, box_height)))
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = True
    return mask


def _source_boxes_to_analysis(
    boxes: Iterable[Sequence[int]],
    *,
    source_shape: tuple[int, int],
    analysis_shape: tuple[int, int],
) -> list[tuple[int, int, int, int]]:
    """Map source-image ``(x, y, width, height)`` boxes to D1 analysis pixels."""

    source_height, source_width = source_shape
    analysis_height, analysis_width = analysis_shape
    scale_x = analysis_width / source_width
    scale_y = analysis_height / source_height
    mapped: list[tuple[int, int, int, int]] = []
    for box in boxes:
        if len(box) != 4:
            raise ValueError("person/face regions must contain x, y, width, height")
        x, y, box_width, box_height = (int(value) for value in box)
        x0 = int(np.floor(x * scale_x))
        y0 = int(np.floor(y * scale_y))
        x1 = int(np.ceil((x + max(0, box_width)) * scale_x))
        y1 = int(np.ceil((y + max(0, box_height)) * scale_y))
        mapped.append((x0, y0, max(0, x1 - x0), max(0, y1 - y0)))
    return mapped


def _analysis_boxes_to_source(
    boxes: Iterable[Sequence[int]],
    *,
    source_shape: tuple[int, int],
    analysis_shape: tuple[int, int],
) -> tuple[tuple[int, int, int, int], ...]:
    """Map detector boxes to the one authoritative source-image coordinate set."""

    source_height, source_width = source_shape
    analysis_height, analysis_width = analysis_shape
    scale_x = source_width / analysis_width
    scale_y = source_height / analysis_height
    mapped: list[tuple[int, int, int, int]] = []
    for box in boxes:
        if len(box) != 4:
            raise ValueError("person/face regions must contain x, y, width, height")
        x, y, box_width, box_height = (int(value) for value in box)
        x0 = int(np.floor(x * scale_x))
        y0 = int(np.floor(y * scale_y))
        x1 = int(np.ceil((x + max(0, box_width)) * scale_x))
        y1 = int(np.ceil((y + max(0, box_height)) * scale_y))
        mapped.append((x0, y0, max(0, x1 - x0), max(0, y1 - y0)))
    return tuple(mapped)


def _canonical_source_regions(
    regions: Iterable[Sequence[int]],
    *,
    source_shape: tuple[int, int],
) -> tuple[tuple[int, int, int, int], ...]:
    """Return a deterministic source-coordinate region set or fail closed."""

    source_height, source_width = source_shape
    canonical: set[tuple[int, int, int, int]] = set()
    try:
        iterator = iter(regions)
    except TypeError as exc:
        raise ValueError("person/face regions must be iterable") from exc
    for raw_box in iterator:
        if not isinstance(raw_box, (list, tuple, np.ndarray)) or len(raw_box) != 4:
            raise ValueError("person/face regions must contain x, y, width, height")
        try:
            x, y, box_width, box_height = (int(value) for value in raw_box)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("person/face regions must contain finite integer coordinates") from exc
        if (
            box_width <= 0
            or box_height <= 0
            or x >= source_width
            or y >= source_height
            or x + box_width <= 0
            or y + box_height <= 0
        ):
            raise ValueError("person/face region does not intersect the source image")
        canonical.add((x, y, box_width, box_height))
    return tuple(sorted(canonical))


def _person_region_digest(
    mode: str,
    source_shape: tuple[int, int],
    source_regions: tuple[tuple[int, int, int, int], ...],
) -> str:
    source_height, source_width = source_shape
    payload = {
        "version": _PERSON_REGION_CONTRACT_VERSION,
        "mode": mode,
        "source_width": source_width,
        "source_height": source_height,
        "source_regions": [list(box) for box in source_regions],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _build_person_region_contract(
    mode: str,
    source_shape: tuple[int, int],
    source_regions: tuple[tuple[int, int, int, int], ...],
) -> _PersonRegionContract:
    source_height, source_width = source_shape
    return _PersonRegionContract(
        version=_PERSON_REGION_CONTRACT_VERSION,
        mode=mode,
        source_width=source_width,
        source_height=source_height,
        source_regions=source_regions,
        digest=_person_region_digest(mode, source_shape, source_regions),
    )


def _person_region_binding_digest(
    decision: ColorUsabilityDecision,
    contract: _PersonRegionContract,
) -> str:
    """Issue a process-local seal for one exact D1 decision instance."""

    payload = {
        "version": _PERSON_REGION_BINDING_VERSION,
        "decision_instance_id": id(decision),
        "decision": decision.to_dict(),
        "person_region_contract": {
            "version": contract.version,
            "mode": contract.mode,
            "source_width": contract.source_width,
            "source_height": contract.source_height,
            "source_regions": [list(box) for box in contract.source_regions],
            "digest": contract.digest,
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(_PERSON_REGION_BINDING_KEY, encoded, hashlib.sha256).hexdigest()


def _resolve_bound_person_regions(
    decision: ColorUsabilityDecision,
    person_regions: Iterable[Sequence[int]] | None,
) -> tuple[tuple[int, int, int, int], ...]:
    """Resolve a D1-bound region contract without detecting or exposing faces."""

    contract = getattr(decision, "_person_region_contract", None)
    if not isinstance(contract, _PersonRegionContract):
        raise ValueError("MISSING_PERSON_REGION_CONTRACT")
    if type(decision) is not ColorUsabilityDecision:
        raise ValueError("INVALID_D1_DECISION_TYPE")
    if contract.version != _PERSON_REGION_CONTRACT_VERSION:
        raise ValueError("UNSUPPORTED_PERSON_REGION_CONTRACT_VERSION")
    source_shape = (contract.source_height, contract.source_width)
    try:
        image_facts = getattr(decision, "image_facts")
        facts_shape = (int(image_facts["height"]), int(image_facts["width"]))
        stored_regions = _canonical_source_regions(
            contract.source_regions,
            source_shape=source_shape,
        )
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("INVALID_PERSON_REGION_CONTRACT") from exc
    if facts_shape != source_shape or stored_regions != contract.source_regions:
        raise ValueError("INVALID_PERSON_REGION_CONTRACT")
    if contract.mode not in {
        _PERSON_REGION_AUTO,
        _PERSON_REGION_EXPLICIT_NONE,
        _PERSON_REGION_EXPLICIT_BOXES,
    }:
        raise ValueError("INVALID_PERSON_REGION_CONTRACT")
    if (
        contract.mode == _PERSON_REGION_EXPLICIT_NONE and stored_regions
    ) or (
        contract.mode == _PERSON_REGION_EXPLICIT_BOXES and not stored_regions
    ):
        raise ValueError("INVALID_PERSON_REGION_CONTRACT")
    expected_digest = _person_region_digest(contract.mode, source_shape, stored_regions)
    if (
        not isinstance(contract.digest, str)
        or len(contract.digest) != 64
        or any(character not in "0123456789abcdef" for character in contract.digest)
        or not hmac.compare_digest(
            contract.digest,
            expected_digest,
        )
    ):
        raise ValueError("INVALID_PERSON_REGION_CONTRACT")
    binding = getattr(decision, "_person_region_binding", None)
    if (
        not isinstance(binding, _PersonRegionBinding)
        or binding.version != _PERSON_REGION_BINDING_VERSION
        or not isinstance(binding.owner, weakref.ReferenceType)
        or binding.owner() is not decision
        or not isinstance(binding.digest, str)
        or len(binding.digest) != 64
        or any(character not in "0123456789abcdef" for character in binding.digest)
    ):
        raise ValueError("INVALID_PERSON_REGION_CONTRACT")
    expected_binding = _person_region_binding_digest(decision, contract)
    if not hmac.compare_digest(binding.digest, expected_binding):
        raise ValueError("INVALID_PERSON_REGION_CONTRACT")

    if person_regions is None:
        requested_mode = _PERSON_REGION_AUTO
        requested_regions = stored_regions
    else:
        try:
            requested_regions = _canonical_source_regions(
                person_regions,
                source_shape=source_shape,
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("INVALID_PERSON_REGION_REQUEST") from exc
        requested_mode = (
            _PERSON_REGION_EXPLICIT_BOXES
            if requested_regions
            else _PERSON_REGION_EXPLICIT_NONE
        )
    if requested_mode != contract.mode or requested_regions != stored_regions:
        raise ValueError("PERSON_REGION_CONTRACT_MISMATCH")
    return stored_regions


def _canonical_person_scene_facts(
    lab: np.ndarray,
    hue: np.ndarray,
    saturation: np.ndarray,
    value: np.ndarray,
    luminance: np.ndarray,
    valid: np.ndarray,
    boxes: Sequence[Sequence[int]],
) -> dict[str, Any]:
    """Port the frozen D-01 person/local-light facts to canonical normalized data.

    These facts are safety-only.  They can require review, but they never
    authorize a global color correction.
    """

    person_mask = _box_mask(valid.shape, boxes) & valid
    valid_count = max(int(valid.sum()), 1)
    face_coverage = float(person_mask.sum() / valid_count)
    strong = valid & (saturation >= 0.38) & (value >= 0.18) & (value <= 0.98)
    strong_coverage = float(strong.sum() / valid_count)
    face_strong_overlap = float(strong[person_mask].mean()) if person_mask.any() else 0.0
    skin_candidate = (
        person_mask
        & (lab[..., 1] > 4.0) & (lab[..., 1] < 30.0)
        & (lab[..., 2] > 2.0) & (lab[..., 2] < 35.0)
        & (luminance > (18.0 / 255.0)) & (luminance < (235.0 / 255.0))
    )
    face_skin_fraction = float(skin_candidate[person_mask].mean()) if person_mask.any() else 0.0
    trusted_skin_ratio = float(skin_candidate.sum() / valid_count)
    trusted_skin_a = float(np.median(lab[..., 1][skin_candidate])) if skin_candidate.any() else None
    trusted_skin_b = float(np.median(lab[..., 2][skin_candidate])) if skin_candidate.any() else None
    person_present = bool(
        boxes
        and face_coverage >= 0.0005
        and (face_skin_fraction >= 0.10 or (strong_coverage < 0.08 and face_strong_overlap < 0.08))
    )

    blue = strong & (hue >= 200.0) & (hue < 280.0)
    upper = np.zeros(valid.shape, dtype=bool)
    upper[: max(1, int(round(valid.shape[0] * 0.46)))] = True
    blue_coverage = float(blue.sum() / valid_count)
    upper_blue_coverage = float((blue & upper).sum() / valid_count)
    probable_screen = bool(person_present and blue_coverage >= 0.10 and upper_blue_coverage >= 0.08)
    # A mixed field does not neutralize a person-level contamination signal.
    # This fact can only force review, so retaining the local safety signal is
    # preferable to silently treating a blue-lit face as a normal mixed scene.
    strong_local_light = probable_screen
    face_b = float(np.median(lab[..., 2][person_mask])) if person_mask.any() else 0.0
    local_person_color_risk = bool(strong_local_light and face_b <= 2.0)

    valid_luminance = luminance[valid]
    mean_luminance = float(valid_luminance.mean())
    face_luminance = float(luminance[person_mask].mean()) if person_mask.any() else 0.0
    background_mask = valid & ~person_mask
    background_luminance = float(luminance[background_mask].mean()) if background_mask.any() else mean_luminance
    local_person_exposure_risk = bool(
        person_present
        and mean_luminance >= (90.0 / 255.0)
        and face_luminance <= min(95.0 / 255.0, mean_luminance - (18.0 / 255.0))
        and background_luminance - face_luminance >= (55.0 / 255.0)
    )
    return {
        "person_present": person_present,
        "local_person_color_risk": local_person_color_risk,
        "local_person_exposure_risk": local_person_exposure_risk,
        "trusted_skin_pixel_ratio": trusted_skin_ratio,
        "trusted_skin_median_lab_a": trusted_skin_a,
        "trusted_skin_median_lab_b": trusted_skin_b,
        "person_fact_source": "hdde.color-perception.d01.canonical-facts.v1",
        "numeric_domain": "canonical-float32-0..1",
        "global_correction_authority": False,
    }


def _family_facts(hue: np.ndarray, saturation: np.ndarray, value: np.ndarray, valid: np.ndarray) -> dict[str, float]:
    strong = valid & (saturation >= 0.36) & (value >= 0.12) & (value <= 0.99)
    families = {
        "RED": (hue < 22.0) | (hue >= 338.0),
        "WOOD_WARM": (hue >= 22.0) & (hue < 65.0),
        "GREEN": (hue >= 65.0) & (hue < 165.0),
        "CYAN": (hue >= 165.0) & (hue < 205.0),
        "BLUE": (hue >= 205.0) & (hue < 285.0),
        "MAGENTA": (hue >= 285.0) & (hue < 338.0),
    }
    denominator = max(int(valid.sum()), 1)
    return {name: _round((strong & family).sum() / denominator) for name, family in families.items()}


def _spatial_facts(
    lab: np.ndarray,
    neutral: np.ndarray,
    valid: np.ndarray,
    hue: np.ndarray,
    saturation: np.ndarray,
    value: np.ndarray,
) -> dict[str, Any]:
    height, width = neutral.shape
    cells: list[dict[str, Any]] = []
    for row in range(3):
        for column in range(3):
            y0, y1 = row * height // 3, (row + 1) * height // 3
            x0, x1 = column * width // 3, (column + 1) * width // 3
            local_neutral = neutral[y0:y1, x0:x1]
            local_valid = valid[y0:y1, x0:x1]
            required = max(24, int(local_valid.sum() * 0.012))
            if int(local_neutral.sum()) < required:
                continue
            local_lab = lab[y0:y1, x0:x1]
            local_hue = hue[y0:y1, x0:x1]
            local_saturation = saturation[y0:y1, x0:x1]
            local_value = value[y0:y1, x0:x1]
            local_strong = local_valid & (local_saturation >= 0.36) & (local_value >= 0.12) & (local_value <= 0.99)
            local_warm = local_strong & ((local_hue < 65.0) | (local_hue >= 338.0))
            local_cool = local_strong & (local_hue >= 165.0) & (local_hue < 285.0)
            local_denominator = max(int(local_valid.sum()), 1)
            warm_ratio = float(local_warm.sum() / local_denominator)
            cool_ratio = float(local_cool.sum() / local_denominator)
            if warm_ratio >= 0.16 and warm_ratio >= cool_ratio * 1.5:
                strong_direction = "WARM"
            elif cool_ratio >= 0.16 and cool_ratio >= warm_ratio * 1.5:
                strong_direction = "COOL"
            elif warm_ratio >= 0.10 and cool_ratio >= 0.10:
                strong_direction = "MIXED"
            else:
                strong_direction = "NONE"
            a = float(np.median(local_lab[..., 1][local_neutral]))
            b = float(np.median(local_lab[..., 2][local_neutral]))
            if b >= 4.5 and abs(b) >= abs(a) * 0.72:
                direction = "WARM"
            elif b <= -3.5 and abs(b) >= abs(a) * 0.72:
                direction = "COOL"
            elif abs(a) >= 4.5:
                direction = "OTHER"
            else:
                direction = "NEUTRAL"
            cells.append({
                "row": row,
                "column": column,
                "a": _round(a),
                "b": _round(b),
                "direction": direction,
                "strong_direction": strong_direction,
                "strong_warm_ratio": _round(warm_ratio),
                "strong_cool_ratio": _round(cool_ratio),
            })

    directions = [str(cell["direction"]) for cell in cells]
    non_neutral = [direction for direction in directions if direction != "NEUTRAL"]
    counts = {direction: directions.count(direction) for direction in {"WARM", "COOL", "OTHER", "NEUTRAL"}}
    vectors = np.asarray([[cell["a"], cell["b"]] for cell in cells], dtype=np.float32)
    vector_span = 0.0
    if len(vectors) >= 2:
        vector_span = float(np.linalg.norm(vectors[:, None, :] - vectors[None, :, :], axis=2).max())
    strong_cells: list[dict[str, Any]] = []
    for row in range(3):
        for column in range(3):
            y0, y1 = row * height // 3, (row + 1) * height // 3
            x0, x1 = column * width // 3, (column + 1) * width // 3
            local_valid = valid[y0:y1, x0:x1]
            local_hue = hue[y0:y1, x0:x1]
            local_saturation = saturation[y0:y1, x0:x1]
            local_value = value[y0:y1, x0:x1]
            local_strong = local_valid & (local_saturation >= 0.36) & (local_value >= 0.12) & (local_value <= 0.99)
            local_warm = local_strong & ((local_hue < 65.0) | (local_hue >= 338.0))
            local_cool = local_strong & (local_hue >= 165.0) & (local_hue < 285.0)
            local_denominator = max(int(local_valid.sum()), 1)
            warm_ratio = float(local_warm.sum() / local_denominator)
            cool_ratio = float(local_cool.sum() / local_denominator)
            if warm_ratio >= 0.16 and warm_ratio >= cool_ratio * 1.5:
                strong_direction = "WARM"
            elif cool_ratio >= 0.16 and cool_ratio >= warm_ratio * 1.5:
                strong_direction = "COOL"
            elif warm_ratio >= 0.10 and cool_ratio >= 0.10:
                strong_direction = "MIXED"
            else:
                strong_direction = "NONE"
            strong_cells.append({
                "row": row,
                "column": column,
                "direction": strong_direction,
                "warm_ratio": _round(warm_ratio),
                "cool_ratio": _round(cool_ratio),
            })
    strong_directions = [str(cell["direction"]) for cell in strong_cells]
    spatial_strong_coverage = float(np.mean([
        float(cell["warm_ratio"]) + float(cell["cool_ratio"])
        for cell in strong_cells
    ])) if strong_cells else 0.0
    spatial_strong_mixed = bool(
        spatial_strong_coverage >= 0.36
        and (
            (strong_directions.count("WARM") >= 2 and strong_directions.count("COOL") >= 2)
            or strong_directions.count("MIXED") >= 2
        )
    )
    mixed = bool(
        (
            len(cells) >= 4
            and (
                vector_span >= 8.0
                and len(set(non_neutral)) >= 2
                and min((non_neutral.count(item) for item in set(non_neutral)), default=0) >= 2
            )
        )
        or spatial_strong_mixed
    )
    dominant_direction = max(counts, key=counts.get) if cells else "UNKNOWN"
    consistency = counts.get(dominant_direction, 0) / max(len(cells), 1)
    if mixed:
        field_status = "MIXED"
    elif len(cells) >= 4 and consistency >= (2.0 / 3.0):
        field_status = "UNIFORM"
    else:
        field_status = "INSUFFICIENT"
    return {
        "field_status": field_status,
        "purpose": "UNIFORM_VS_MIXED_ONLY",
        "eligible_cell_count": len(cells),
        "dominant_direction": dominant_direction,
        "direction_consistency": _round(consistency),
        "vector_span": _round(vector_span),
        "strong_color_mixed": spatial_strong_mixed,
        "spatial_strong_color_coverage": _round(spatial_strong_coverage),
        "cells": cells,
        "strong_color_cells": strong_cells,
        "local_correction_allowed": False,
    }


def _classify_color_appearance(
    spatial: dict[str, Any],
    neutral_ratio: float,
    neutral_a: float,
    neutral_b: float,
    neutral_chroma: float,
) -> str:
    """Apply the frozen appearance thresholds; this never authorizes correction."""

    if spatial["field_status"] == "MIXED":
        return "MIXED"
    if neutral_ratio >= 0.025 and neutral_b >= 4.5 - LAB_ENCODING_TOLERANCE and neutral_chroma >= 4.5 - LAB_ENCODING_TOLERANCE:
        return "WARM"
    if neutral_ratio >= 0.025 and neutral_b <= -2.5 + LAB_ENCODING_TOLERANCE and neutral_chroma >= 2.5 - LAB_ENCODING_TOLERANCE:
        return "COOL"
    if neutral_ratio >= 0.025 and abs(neutral_a) >= 4.5 - LAB_ENCODING_TOLERANCE:
        return "OTHER"
    if neutral_chroma <= 4.0 - LAB_ENCODING_TOLERANCE:
        return "NEUTRAL"
    return "UNKNOWN"


def _appearance_signature_from_rgb(rgb: np.ndarray, valid: np.ndarray) -> dict[str, Any]:
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    lightness, a_axis, b_axis = lab[..., 0], lab[..., 1], lab[..., 2]
    hue, saturation, value = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    chroma = np.hypot(a_axis, b_axis)
    skin_like = (
        valid
        & (a_axis >= 4.0) & (a_axis <= 32.0)
        & (b_axis >= 3.0) & (b_axis <= 38.0)
        & (lightness >= 18.0) & (lightness <= 92.0)
        & (hue >= 5.0) & (hue <= 65.0)
    )
    low_chroma = valid & (chroma <= 30.0) & (saturation <= 0.36) & (lightness >= 12.0) & (lightness <= 96.0)
    neutral = low_chroma & ~skin_like
    neutral_count = int(neutral.sum())
    valid_count = max(int(valid.sum()), 1)
    neutral_ratio = neutral_count / valid_count
    neutral_a = float(np.median(a_axis[neutral])) if neutral_count else 0.0
    neutral_b = float(np.median(b_axis[neutral])) if neutral_count else 0.0
    neutral_chroma = float(np.hypot(neutral_a, neutral_b))
    spatial = _spatial_facts(lab, neutral, valid, hue, saturation, value)
    return {
        "direction": _classify_color_appearance(spatial, neutral_ratio, neutral_a, neutral_b, neutral_chroma),
        "neutral_ratio": neutral_ratio,
        "neutral_a": neutral_a,
        "neutral_b": neutral_b,
        "neutral_chroma": neutral_chroma,
        "spatial_field": str(spatial["field_status"]),
    }


def _quantization_stability_gate(
    rgb: np.ndarray,
    valid: np.ndarray,
    current_signature: dict[str, Any],
) -> dict[str, Any]:
    """Detect decision boundaries reachable within one 8/16-bit encoding envelope.

    The coarsest supported encoder is 8-bit.  Its half-LSB plus the 16-bit
    half-LSB and float32 roundoff define one shared RGB uncertainty radius.
    Re-running the complete RGB->Lab/HSV appearance path at all channel-wise
    envelope corners propagates that numeric uncertainty without changing any
    appearance threshold or replacing native precision with an 8-bit result.
    """

    reference = np.rint(np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.float32) / 255.0
    signatures = [current_signature, _appearance_signature_from_rgb(reference, valid)]
    for signs in product((-1.0, 1.0), repeat=3):
        delta = np.asarray(signs, dtype=np.float32) * RGB_8_16_EQUIVALENCE_RADIUS
        variant = np.ascontiguousarray(np.clip(reference + delta, 0.0, 1.0), dtype=np.float32)
        signatures.append(_appearance_signature_from_rgb(variant, valid))

    directions = sorted({str(item["direction"]) for item in signatures})
    ranges = {
        key: [_round(min(float(item[key]) for item in signatures)), _round(max(float(item[key]) for item in signatures))]
        for key in ("neutral_ratio", "neutral_a", "neutral_b", "neutral_chroma")
    }
    return {
        "boundary_unstable": len(directions) > 1,
        "stable_margin_rgb": _round(RGB_8_16_EQUIVALENCE_RADIUS),
        "margin_basis": "8bit-half-lsb + 16bit-half-lsb + float32-roundoff",
        "evaluated_variants": len(signatures),
        "appearance_directions": directions,
        "spatial_fields": sorted({str(item["spatial_field"]) for item in signatures}),
        "feature_ranges": ranges,
    }


def analyze_color_usability(
    image: Image.Image | np.ndarray,
    *,
    input_order: str = "RGB",
    person_regions: Iterable[Sequence[int]] | None = None,
) -> ColorUsabilityDecision:
    """Return D1 facts and a fail-safe action without modifying the image."""

    source_fingerprint = compute_source_fingerprint(image, input_order=input_order)
    rgb, valid, image_facts = _prepare_image(image, input_order)
    if int(valid.sum()) < 256:
        raise ValueError("D1 requires at least 256 visible pixels")

    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    lightness, a_axis, b_axis = lab[..., 0], lab[..., 1], lab[..., 2]
    hue, saturation, value = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    luminance = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    chroma = np.hypot(a_axis, b_axis)

    source_shape = (int(image_facts["height"]), int(image_facts["width"]))
    if person_regions is None:
        detected_analysis_regions = _detect_faces(rgb, valid)
        detected_source_regions = _analysis_boxes_to_source(
            detected_analysis_regions,
            source_shape=source_shape,
            analysis_shape=valid.shape,
        )
        source_regions = _canonical_source_regions(
            detected_source_regions,
            source_shape=source_shape,
        )
        person_region_mode = _PERSON_REGION_AUTO
    else:
        source_regions = _canonical_source_regions(
            person_regions,
            source_shape=source_shape,
        )
        person_region_mode = (
            _PERSON_REGION_EXPLICIT_BOXES
            if source_regions
            else _PERSON_REGION_EXPLICIT_NONE
        )
    person_region_contract = _build_person_region_contract(
        person_region_mode,
        source_shape,
        source_regions,
    )
    boxes = _source_boxes_to_analysis(
        source_regions,
        source_shape=source_shape,
        analysis_shape=valid.shape,
    )
    person_mask = _box_mask(valid.shape, boxes) & valid
    skin_like = (
        valid
        & (a_axis >= 4.0) & (a_axis <= 32.0)
        & (b_axis >= 3.0) & (b_axis <= 38.0)
        & (lightness >= 18.0) & (lightness <= 92.0)
        & (hue >= 5.0) & (hue <= 65.0)
    )
    trusted_skin = skin_like & person_mask

    # The wider low-chroma candidate remains useful under a real cast.  Skin is
    # removed before any neutral statistic, even when no face detector fires.
    low_chroma = valid & (chroma <= 30.0) & (saturation <= 0.36) & (lightness >= 12.0) & (lightness <= 96.0)
    neutral = low_chroma & ~skin_like
    neutral_count = int(neutral.sum())
    valid_count = max(int(valid.sum()), 1)
    neutral_ratio = neutral_count / valid_count
    low_chroma_ratio = float(low_chroma.sum() / valid_count)
    neutral_a = float(np.median(a_axis[neutral])) if neutral_count else 0.0
    neutral_b = float(np.median(b_axis[neutral])) if neutral_count else 0.0
    neutral_chroma = float(np.hypot(neutral_a, neutral_b))
    neutral_tonal_bands: list[dict[str, Any]] = []
    for name, lower, upper in (("SHADOW", 12.0, 40.0), ("MIDTONE", 40.0, 70.0), ("HIGHLIGHT", 70.0, 96.1)):
        band_mask = neutral & (lightness >= lower) & (lightness < upper)
        required = max(32, int(valid_count * 0.003))
        if int(band_mask.sum()) < required:
            continue
        band_a = float(np.median(a_axis[band_mask]))
        band_b = float(np.median(b_axis[band_mask]))
        if band_b >= 4.5 and abs(band_b) >= abs(band_a) * 0.72:
            band_direction = "WARM"
        elif band_b <= -3.5 and abs(band_b) >= abs(band_a) * 0.72:
            band_direction = "COOL"
        elif abs(band_a) >= 4.5:
            band_direction = "OTHER"
        else:
            band_direction = "NEUTRAL"
        neutral_tonal_bands.append({
            "band": name,
            "pixel_ratio": _round(band_mask.sum() / valid_count),
            "median_lab_a": _round(band_a),
            "median_lab_b": _round(band_b),
            "direction": band_direction,
        })

    spatial = _spatial_facts(lab, neutral, valid, hue, saturation, value)
    family = _family_facts(hue, saturation, value, valid)
    person_facts = _canonical_person_scene_facts(
        lab,
        hue,
        saturation,
        value,
        luminance,
        valid,
        boxes,
    )
    dominant_family = max(family, key=family.get)
    dominant_coverage = float(family[dominant_family])
    strong_color_ratio = float(sum(family.values()))
    if dominant_coverage >= 0.42 or (dominant_coverage >= 0.28 and neutral_ratio < 0.04):
        dominant_risk = "HIGH"
    elif dominant_coverage >= 0.20 or strong_color_ratio >= 0.45:
        dominant_risk = "MEDIUM"
    else:
        dominant_risk = "LOW"

    valid_luminance = luminance[valid]
    p01, p05, p50, p95, p99 = (float(item) for item in np.percentile(valid_luminance, [1, 5, 50, 95, 99]))
    mean_luminance = float(valid_luminance.mean())
    shadow_ratio = float((valid & (luminance <= 0.14)).sum() / valid_count)
    shadow_clip = float((valid & (luminance <= 0.01)).sum() / valid_count)
    highlight_clip = float((valid & (luminance >= 0.99)).sum() / valid_count)
    chroma_valid = valid & (saturation >= 0.20)
    channel_low_clip = tuple(
        float((chroma_valid & (rgb[..., channel] <= 0.01)).sum() / valid_count)
        for channel in range(3)
    )
    channel_high_clip = tuple(
        float((chroma_valid & (rgb[..., channel] >= 0.99)).sum() / valid_count)
        for channel in range(3)
    )
    channel_clip = tuple(
        channel_low_clip[channel] + channel_high_clip[channel]
        for channel in range(3)
    )
    color_clipped_pixels = chroma_valid & (
        (rgb <= 0.01).any(axis=2) | (rgb >= 0.99).any(axis=2)
    )
    color_clipped_pixel_ratio = float(color_clipped_pixels.sum() / valid_count)
    dynamic_range = p95 - p05
    image_facts.update({
        "luminance_p01": _round(p01),
        "luminance_p05": _round(p05),
        "luminance_p50": _round(p50),
        "luminance_p95": _round(p95),
        "luminance_p99": _round(p99),
        "mean_luminance": _round(mean_luminance),
        "luminance_dynamic_range_p95_p05": _round(dynamic_range),
        "shadow_ratio": _round(shadow_ratio),
        "shadow_clip_ratio": _round(shadow_clip),
        "highlight_clip_ratio": _round(highlight_clip),
        "color_channel_low_clip_ratios": [_round(value) for value in channel_low_clip],
        "color_channel_high_clip_ratios": [_round(value) for value in channel_high_clip],
        "maximum_color_channel_clip_ratio": _round(max(channel_clip)),
        "color_clipped_pixel_ratio": _round(color_clipped_pixel_ratio),
    })

    severe_clipping = shadow_clip + highlight_clip >= 0.35
    eligible_cells = int(spatial["eligible_cell_count"])
    if neutral_ratio >= 0.10 and eligible_cells >= 6 and not severe_clipping and image_facts["valid_pixel_ratio"] >= 0.8:
        observability = ColorObservability.HIGH
    elif neutral_ratio >= 0.025 and eligible_cells >= 3 and image_facts["valid_pixel_ratio"] >= 0.5:
        observability = ColorObservability.MEDIUM
    else:
        observability = ColorObservability.LOW

    direction = str(spatial["dominant_direction"])
    if spatial["field_status"] == "MIXED":
        illuminant_status = "MIXED"
    elif spatial["field_status"] == "UNIFORM" and direction in {"WARM", "COOL", "OTHER", "NEUTRAL"}:
        illuminant_status = direction
    else:
        illuminant_status = "UNKNOWN"

    warm_coverage = family["RED"] + family["WOOD_WARM"]
    cool_coverage = family["CYAN"] + family["BLUE"]
    low_key = bool(
        (p50 <= 0.20 and p95 >= 0.42 and dynamic_range >= 0.34 and highlight_clip < 0.08)
        or (mean_luminance < 0.14 and shadow_ratio >= 0.72 and highlight_clip < 0.015 and p99 < 0.46)
    )
    high_key = bool(
        p50 >= 0.74
        and p05 >= 0.25
        and mean_luminance >= 0.64
        and shadow_ratio < 0.03
        and highlight_clip < 0.10
    )
    if spatial["field_status"] == "MIXED":
        scene_intent = "MIXED_LIGHT"
    elif low_key:
        scene_intent = "LEGITIMATE_DARK"
    elif high_key:
        scene_intent = "LEGITIMATE_HIGH_KEY"
    elif illuminant_status == "WARM" and warm_coverage >= 0.34 and dominant_risk in {"MEDIUM", "HIGH"}:
        scene_intent = "LEGITIMATE_WARM"
    elif illuminant_status == "COOL" and cool_coverage >= 0.34 and dominant_risk in {"MEDIUM", "HIGH"}:
        scene_intent = "LEGITIMATE_COOL"
    elif dominant_risk == "HIGH":
        scene_intent = "DOMINANT_COLOR_DESIGN"
    elif boxes:
        scene_intent = "PERSON_SCENE"
    else:
        scene_intent = "GENERAL"
    local_person_color_risk = bool(person_facts["local_person_color_risk"])
    if local_person_color_risk:
        scene_intent = "LOCAL_PERSON_COLOR_RISK"

    # RGB, Lab, neutral pixels, tonal bands, spatial cells, and the frozen D-01
    # global-cast view are all transformations of the same post-ISP pixels.
    # They may establish appearance, but cannot independently establish that
    # the appearance is an error requiring automatic correction.
    appearance_direction = _classify_color_appearance(
        spatial,
        neutral_ratio,
        neutral_a,
        neutral_b,
        neutral_chroma,
    )
    quantization_stability = _quantization_stability_gate(
        rgb,
        valid,
        {
            "direction": appearance_direction,
            "neutral_ratio": neutral_ratio,
            "neutral_a": neutral_a,
            "neutral_b": neutral_b,
            "neutral_chroma": neutral_chroma,
            "spatial_field": str(spatial["field_status"]),
        },
    )
    boundary_unstable = bool(quantization_stability["boundary_unstable"])
    candidate_direction = appearance_direction.lower()

    matching_band_count = sum(
        str(item["direction"]).lower() == candidate_direction
        for item in neutral_tonal_bands
    )
    rgb_means = [float(rgb[..., channel][valid].mean()) for channel in range(3)]
    channel_imbalance = max(rgb_means) - min(rgb_means)
    appearance_is_directional = appearance_direction in {"WARM", "COOL", "OTHER"}
    appearance_evidence = {
        "direction": appearance_direction,
        "source_group": "POST_ISP_RGB_APPEARANCE",
        "components": [
            "GLOBAL_RGB_LAB",
            "SKIN_EXCLUDED_NEUTRAL_LAB",
            "TONAL_BANDS",
            "SPATIAL_CELLS",
        ],
        "components_are_independent_for_correction": False,
        "observable": observability.value,
        "uniform_vs_mixed": str(spatial["field_status"]),
        "matching_tonal_band_count": matching_band_count,
        "boundary_unstable": boundary_unstable,
        "quantization_stability": quantization_stability,
    }
    protected_color_intent = scene_intent in {"LEGITIMATE_WARM", "LEGITIMATE_COOL", "DOMINANT_COLOR_DESIGN"}
    # V0.5.6 has no independent capture-domain evidence that can authorize
    # automatic color correction. Directional Post-ISP appearance remains
    # review-only; exposure AUTO is evaluated independently below.
    correction_justification = {
        "status": (
            "INSUFFICIENT"
            if (appearance_is_directional and not protected_color_intent) or boundary_unstable
            else "NOT_REQUIRED"
        ),
        "auto_authorized": False,
        "independent_evidence_sources": [],
        "excluded_same_source_evidence": [
            "GLOBAL_RGB_LAB",
            "SKIN_EXCLUDED_NEUTRAL_LAB",
            "HIGHLIGHT_LOW_CHROMA_REFERENCE",
            "SPATIAL_MULTI_REGION_REFERENCE",
            "PERSON_SKIN_RELATION",
            "LEGACY_D01_GLOBAL_CAST",
        ],
        "reason": (
            "ENCODING_QUANTIZATION_CAN_CHANGE_COLOR_CLASSIFICATION"
            if boundary_unstable
            else "POST_ISP_APPEARANCE_CANNOT_SEPARATE_AMBIENT_LIGHT_FROM_ERROR_CAST"
            if appearance_is_directional and not protected_color_intent
            else "NO_AUTOMATIC_GLOBAL_COLOR_CORRECTION_REQUESTED"
        ),
    }

    support: list[Evidence] = []
    conflict: list[Evidence] = []
    if neutral_ratio >= 0.025:
        support.append(Evidence("NEUTRAL_REFERENCE_PRESENT", "COLOR", min(0.35, neutral_ratio * 1.8), "skin-excluded low-chroma references"))
    if spatial["field_status"] == "UNIFORM":
        support.append(Evidence("SPATIAL_FIELD_UNIFORM", "COLOR_APPEARANCE", 0.30, "cells agree on appearance only"))
    if neutral_chroma >= 4.5:
        support.append(Evidence("NEUTRAL_DIRECTIONAL_SHIFT", "COLOR", min(0.30, neutral_chroma / 30.0), f"median Lab a/b={neutral_a:.2f}/{neutral_b:.2f}"))
    if matching_band_count >= 2:
        support.append(Evidence("TONAL_BAND_DIRECTION_CONSENSUS", "COLOR", 0.20, f"{matching_band_count} lightness bands agree"))
    if appearance_is_directional:
        support.append(Evidence("POST_ISP_COLOR_APPEARANCE", "COLOR_APPEARANCE", 0.30, appearance_direction))
    if mean_luminance < 0.31 and p95 < 0.68 and p50 < 0.30 and shadow_ratio >= 0.30 and not low_key:
        support.append(Evidence("GLOBAL_TONAL_COMPRESSION_DARK", "EXPOSURE", 0.35, "upper luminance range is compressed"))
    if p05 > 0.58 and p50 > 0.82:
        support.append(Evidence("GLOBAL_TONAL_COMPRESSION_BRIGHT", "EXPOSURE", 0.35, "lower luminance range is compressed"))

    if spatial["field_status"] == "MIXED":
        conflict.append(Evidence("MIXED_COLOR_FIELD", "COLOR", 0.70, "spatial directions disagree"))
    if observability == ColorObservability.LOW:
        conflict.append(Evidence("LOW_COLOR_OBSERVABILITY", "COLOR", 0.65, "too few trustworthy independent color references"))
    if dominant_risk == "HIGH":
        conflict.append(Evidence("DOMINANT_COLOR_CAN_EXPLAIN_GLOBAL_MEAN", "COLOR", 0.60, dominant_family))
    if scene_intent in {"LEGITIMATE_WARM", "LEGITIMATE_COOL", "LEGITIMATE_DARK", "LEGITIMATE_HIGH_KEY"}:
        conflict.append(Evidence("SCENE_INTENT_PROTECTION", "BOTH", 0.60, scene_intent))
    if severe_clipping:
        conflict.append(Evidence("CLIPPING_LIMITS_OBSERVATION", "BOTH", 0.55, "too many clipped pixels"))
    elif highlight_clip >= 0.08 and not (p05 > 0.58 and p50 > 0.82):
        conflict.append(Evidence("HIGHLIGHT_LIMITED_COLOR_EVIDENCE", "COLOR", 0.55, "highlight clipping can bias neutral evidence"))
    if boxes and trusted_skin.sum() < max(16, int(person_mask.sum() * 0.01)):
        conflict.append(Evidence("PERSON_WITHOUT_TRUSTED_SKIN_REFERENCE", "COLOR", 0.30, "person protection has weak skin evidence"))
    if local_person_color_risk:
        conflict.append(Evidence("LOCAL_PERSON_COLOR_RISK", "COLOR", 0.90, "existing D01 person/skin facts identify local light contamination"))
    if boundary_unstable:
        conflict.append(Evidence("QUANTIZATION_BOUNDARY_UNSTABLE", "COLOR", 0.80, "8/16-bit encoding envelope crosses a color classification boundary"))
    appearance_requires_review = bool(
        boundary_unstable
        or (
            appearance_is_directional
            and not local_person_color_risk
            and not protected_color_intent
        )
    )
    if appearance_is_directional and not local_person_color_risk and not protected_color_intent:
        conflict.append(Evidence("CORRECTION_JUSTIFICATION_MISSING", "COLOR", 0.75, "all available color facts share the same post-ISP RGB source"))
        conflict.append(Evidence("AMBIENT_VS_CAST_UNRESOLVED", "COLOR", 0.70, "uniform warm/cool shift lacks independent evidence separating ambient intent from global error"))

    hard_color_conflict = any(item.code in {
        "MIXED_COLOR_FIELD", "LOW_COLOR_OBSERVABILITY", "DOMINANT_COLOR_CAN_EXPLAIN_GLOBAL_MEAN",
        "CLIPPING_LIMITS_OBSERVATION", "HIGHLIGHT_LIMITED_COLOR_EVIDENCE",
        "LOCAL_PERSON_COLOR_RISK", "AMBIENT_VS_CAST_UNRESOLVED", "CORRECTION_JUSTIFICATION_MISSING",
        "QUANTIZATION_BOUNDARY_UNSTABLE",
    } for item in conflict)
    if boundary_unstable:
        color_status = ColorStatus.UNCERTAIN
    elif local_person_color_risk:
        color_status = ColorStatus.UNCERTAIN
    elif protected_color_intent:
        color_status = ColorStatus.NORMAL
    elif appearance_requires_review or hard_color_conflict:
        color_status = ColorStatus.UNCERTAIN
    elif appearance_direction == "NEUTRAL":
        color_status = ColorStatus.NORMAL
    else:
        color_status = ColorStatus.UNCERTAIN

    if low_key or high_key:
        exposure_status = ExposureStatus.PASS
    elif severe_clipping and not (p05 > 0.58 or p95 < 0.42):
        exposure_status = ExposureStatus.UNCERTAIN
    elif mean_luminance < 0.31 and p95 < 0.68 and p50 < 0.30 and shadow_ratio >= 0.30:
        exposure_status = ExposureStatus.TOO_DARK
    elif p05 > 0.58 and p50 > 0.82:
        exposure_status = ExposureStatus.TOO_BRIGHT
    else:
        exposure_status = ExposureStatus.PASS

    color_score = min(1.0, 0.28 * min(1.0, neutral_ratio / 0.12) + 0.36 * float(spatial["direction_consistency"]) + 0.22 * min(1.0, neutral_chroma / 12.0) + 0.14 * (observability != ColorObservability.LOW))
    exposure_score = min(1.0, 0.45 + 0.35 * min(1.0, dynamic_range / 0.55) + 0.20 * (not severe_clipping))
    confidence = color_score if color_status not in {ColorStatus.NORMAL, ColorStatus.UNCERTAIN} else min(color_score, exposure_score)
    risk = min(1.0, sum(item.weight for item in conflict))

    correctable = exposure_status in {ExposureStatus.TOO_DARK, ExposureStatus.TOO_BRIGHT}
    protected_keep = bool(
        scene_intent in {"LEGITIMATE_WARM", "LEGITIMATE_COOL", "LEGITIMATE_DARK", "DOMINANT_COLOR_DESIGN"}
        and color_status in {ColorStatus.NORMAL, ColorStatus.UNCERTAIN}
        and spatial["field_status"] != "MIXED"
        and exposure_status == ExposureStatus.PASS
        and not boundary_unstable
    )
    requires_review = bool(
        boundary_unstable
        or spatial["field_status"] == "MIXED"
        or (observability == ColorObservability.LOW and not protected_keep)
        or (color_status == ColorStatus.UNCERTAIN and not protected_keep)
        or exposure_status == ExposureStatus.UNCERTAIN
        or (correctable and risk >= 0.55 and not protected_keep)
    )
    if requires_review:
        action = D1Action.REVIEW_REQUIRED
    elif correctable and risk < 0.55 and confidence >= 0.60:
        action = D1Action.AUTO_CORRECT
    else:
        action = D1Action.KEEP_ORIGINAL

    global_facts = {
        "rgb_mean": [_round(item) for item in rgb_means],
        "lab_mean": [_round(float(lab[..., channel][valid].mean())) for channel in range(3)],
        "saturation_mean": _round(float(saturation[valid].mean())),
        "saturation_p50": _round(float(np.percentile(saturation[valid], 50))),
        "saturation_p90": _round(float(np.percentile(saturation[valid], 90))),
        "strong_color_ratio": _round(strong_color_ratio),
        "family_coverage": family,
        "channel_imbalance": _round(channel_imbalance),
        "appearance_source_group": "POST_ISP_RGB_APPEARANCE",
        "multi_source_global_cast_supported": False,
        "note": "global statistics are context only and never trigger correction alone",
    }
    neutral_facts = {
        "pixel_ratio": _round(neutral_ratio),
        "median_lab_a": _round(neutral_a),
        "median_lab_b": _round(neutral_b),
        "median_chroma": _round(neutral_chroma),
        "tonal_bands": neutral_tonal_bands,
        "skin_excluded": True,
    }
    skin_facts = {
        "face_or_person_region_count": len(boxes),
        "skin_like_pixel_ratio": _round(skin_like.sum() / valid_count),
        "trusted_skin_pixel_ratio": _round(trusted_skin.sum() / valid_count),
        "person_present": bool(person_facts["person_present"]),
        "local_person_color_risk": local_person_color_risk,
        "local_person_exposure_risk": bool(person_facts["local_person_exposure_risk"]),
        "trusted_skin_median_lab_a": (
            _round(float(person_facts["trusted_skin_median_lab_a"]))
            if person_facts["trusted_skin_median_lab_a"] is not None else None
        ),
        "trusted_skin_median_lab_b": (
            _round(float(person_facts["trusted_skin_median_lab_b"]))
            if person_facts["trusted_skin_median_lab_b"] is not None else None
        ),
        "fact_source": person_facts["person_fact_source"],
        "numeric_domain": person_facts["numeric_domain"],
        "global_correction_authority": person_facts["global_correction_authority"],
        "used_as_neutral": False,
        "identity_recorded": False,
    }
    low_chroma_facts = {
        "pixel_ratio": _round(low_chroma_ratio),
        "skin_overlap_removed_ratio": _round((low_chroma & skin_like).sum() / valid_count),
    }
    decision = ColorUsabilityDecision(
        schema_version=D1_SCHEMA_VERSION,
        engine_version=D1_ENGINE_VERSION,
        rule_version=D1_RULE_VERSION,
        source_fingerprint=source_fingerprint,
        image_facts=image_facts,
        color_observability=observability,
        global_color_facts=global_facts,
        neutral_color_facts=neutral_facts,
        skin_color_facts=skin_facts,
        low_chroma_color_facts=low_chroma_facts,
        spatial_color_facts=spatial,
        illuminant_status=illuminant_status,
        dominant_color_risk=dominant_risk,
        scene_intent=scene_intent,
        color_appearance_evidence=appearance_evidence,
        correction_justification=correction_justification,
        support_evidence=tuple(support),
        conflict_evidence=tuple(conflict),
        confidence=_round(confidence),
        risk=_round(risk),
        color_status=color_status,
        exposure_status=exposure_status,
        d1_action=action,
    )
    object.__setattr__(decision, "_person_region_contract", person_region_contract)
    binding = _PersonRegionBinding(
        version=_PERSON_REGION_BINDING_VERSION,
        digest=_person_region_binding_digest(decision, person_region_contract),
        owner=weakref.ref(decision),
    )
    object.__setattr__(decision, "_person_region_binding", binding)
    return decision


def analyze_color_usability_file(path: str | Path) -> ColorUsabilityDecision:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError("D1 input image does not exist")
    with Image.open(source) as image:
        image.load()
        source_format = str(image.format or "").upper()
        if source_format not in {"JPEG", "PNG"}:
            raise ValueError("D1 supports JPEG and PNG only")
        if source_format == "PNG":
            encoded = np.frombuffer(source.read_bytes(), dtype=np.uint8)
            decoded = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
            if decoded is None:
                raise ValueError("D1 cannot decode the PNG input")
            if np.issubdtype(decoded.dtype, np.integer) and decoded.dtype.itemsize > 1:
                return analyze_color_usability(decoded, input_order="BGR")
        return analyze_color_usability(image)


def build_shadow_record(
    decision: ColorUsabilityDecision,
    *,
    source_token: str | None = None,
) -> dict[str, Any]:
    """Build a privacy-minimal replay record; no image or filesystem path is stored."""

    facts = decision.to_dict()
    token = source_token or hashlib.sha256(
        json.dumps({
            "image": facts["image_facts"],
            "global": facts["global_color_facts"],
            "neutral": facts["neutral_color_facts"],
            "spatial": facts["spatial_color_facts"],
        }, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "schema_version": D1_SCHEMA_VERSION,
        "source_token": token,
        "facts": {
            "image": facts["image_facts"],
            "global": facts["global_color_facts"],
            "neutral": facts["neutral_color_facts"],
            "skin": facts["skin_color_facts"],
            "low_chroma": facts["low_chroma_color_facts"],
            "spatial": facts["spatial_color_facts"],
        },
        "d1_evidence": {
            "support": facts["support_evidence"],
            "conflict": facts["conflict_evidence"],
            "color_observability": facts["color_observability"],
            "illuminant_status": facts["illuminant_status"],
            "dominant_color_risk": facts["dominant_color_risk"],
            "scene_intent": facts["scene_intent"],
            "color_appearance": facts["color_appearance_evidence"],
            "correction_justification": facts["correction_justification"],
        },
        "status": {
            "color": facts["color_status"],
            "exposure": facts["exposure_status"],
        },
        "confidence": facts["confidence"],
        "risk": facts["risk"],
        "d1_action": facts["d1_action"],
        "engine_version": facts["engine_version"],
        "rule_version": facts["rule_version"],
        "privacy": {
            "original_image_saved": False,
            "filesystem_path_saved": False,
            "person_identity_saved": False,
        },
    }


def append_shadow_record(path: str | Path, record: dict[str, Any]) -> None:
    """Explicit opt-in JSONL sink for replay; D1 never writes by default."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


__all__ = [
    "D1_SCHEMA_VERSION",
    "D1_ENGINE_VERSION",
    "D1_RULE_VERSION",
    "SOURCE_FINGERPRINT_VERSION",
    "compute_source_fingerprint",
    "ColorStatus",
    "ExposureStatus",
    "ColorObservability",
    "D1Action",
    "Evidence",
    "ColorUsabilityDecision",
    "analyze_color_usability",
    "analyze_color_usability_file",
    "build_shadow_record",
    "append_shadow_record",
]
