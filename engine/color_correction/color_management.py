"""Fail-closed color I/O boundary for the formal HDDE color runtime.

V1 intentionally supports only single-frame, camera-rendered 8-bit RGB/RGBA
JPEG and PNG inputs. Untagged input is treated as sRGB; valid sRGB, Display P3,
and Adobe RGB (1998) matrix profiles are converted by LittleCMS into the same
sRGB working space. Unsupported precision, modes, profiles, and animation are
rejected before D1/D2/D3 can interpret or modify pixels.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from threading import RLock
from typing import Any
import weakref

import numpy as np
from PIL import ExifTags, Image, ImageCms, ImageOps


COLOR_MANAGEMENT_VERSION = "hdde.color-management.v1.4"
MANAGED_COLOR_SOURCE_PROVENANCE_VERSION = (
    "hdde.managed-color-source-provenance-seal.v1"
)
WORKING_COLOR_SPACE = "sRGB IEC61966-2.1"
SUPPORTED_FORMATS = frozenset({"JPEG", "PNG"})
SUPPORTED_MODES = frozenset({"RGB", "RGBA"})
_SRGB_PNG_GAMMA = 0.45455
_SRGB_PNG_CHROMATICITY = (0.3127, 0.3290, 0.6400, 0.3300, 0.3000, 0.6000, 0.1500, 0.0600)
_PNG_METADATA_TOLERANCE = 0.00005
_ICC_PNG_CHROMATICITY_TOLERANCE = 0.0002
_ICC_TRC_PARAMETER_TOLERANCE = 0.00005
_SRGB_EQUIVALENCE_MAX_CHANNEL_DELTA = 2
_WIDE_GAMUT_NEUTRAL_MAX_CHANNEL_SPAN = 3
_WIDE_GAMUT_BLACK_MAX_CHANNEL_VALUE = 3
_WIDE_GAMUT_WHITE_MIN_CHANNEL_VALUE = 252
_SUPPORTED_WIDE_GAMUT_LABELS = {
    "DISPLAY_P3": frozenset({
        "display p3",
        "display p3 d65",
        "srgb eotf with display p3 color gamut",
    }),
    "ADOBE_RGB_1998": frozenset({
        "adobe rgb (1998)",
        "adobe rgb 1998",
    }),
}
_SUPPORTED_WIDE_GAMUT_PRIMARY_BOUNDS = {
    "DISPLAY_P3": {
        "red": ((0.67, 0.70), (0.30, 0.34)),
        "green": ((0.26, 0.31), (0.64, 0.71)),
        "blue": ((0.14, 0.18), (0.04, 0.09)),
    },
    "ADOBE_RGB_1998": {
        "red": ((0.63, 0.67), (0.31, 0.35)),
        "green": ((0.19, 0.25), (0.67, 0.73)),
        "blue": ((0.14, 0.18), (0.04, 0.09)),
    },
}
_BRADFORD_MATRIX = np.array(
    (
        (0.8951, 0.2664, -0.1614),
        (-0.7502, 1.7135, 0.0367),
        (0.0389, -0.0685, 1.0296),
    ),
    dtype=np.float64,
)
_ICC_PCS_D50_XYZ = np.array((0.96422, 1.0, 0.82521), dtype=np.float64)
_SOURCE_D65_XYZ = np.array((0.95047, 1.0, 1.08883), dtype=np.float64)
_D50_TO_D65_BRADFORD = np.linalg.inv(
    np.linalg.inv(_BRADFORD_MATRIX)
    @ np.diag((_BRADFORD_MATRIX @ _ICC_PCS_D50_XYZ) / (_BRADFORD_MATRIX @ _SOURCE_D65_XYZ))
    @ _BRADFORD_MATRIX
)
_SRGB_PARAMETRIC_TRC = {
    3: (2.4, 1.0 / 1.055, 0.055 / 1.055, 1.0 / 12.92, 0.04045),
    4: (2.4, 1.0 / 1.055, 0.055 / 1.055, 1.0 / 12.92, 0.04045, 0.0, 0.0),
}


class ColorManagementError(ValueError):
    """A stable, fail-closed color input or output contract violation."""

    def __init__(self, code: str) -> None:
        self.code = str(code)
        super().__init__(self.code)


@dataclass(frozen=True)
class ManagedColorSource:
    pixels: np.ndarray
    source_format: str
    source_mode: str
    source_bit_depth: int
    input_order: str
    profile_status: str
    source_profile_name: str | None
    output_icc_profile: bytes
    frame_count: int
    source_dpi: tuple[float, float] | None = None
    source_resolution_exif: tuple[str | None, str | None, str | None] = (
        None,
        None,
        None,
    )
    output_resolution_exif: bytes | None = None

    @property
    def alpha_present(self) -> bool:
        return bool(self.pixels.ndim == 3 and self.pixels.shape[2] == 4)


@dataclass(frozen=True)
class ManagedColorSourceProvenanceValidation:
    valid: bool
    blocker: str | None
    provenance_version: str | None
    alpha_mode: str
    decoder_origin_binding: str
    pixel_object_identity: str
    pixel_content_identity: str
    contract_identity: str
    decode_time_pixel_sha256: str | None
    current_pixel_sha256: str | None


@dataclass(frozen=True)
class ManagedColorSourceSnapshotAcquisition:
    valid: bool
    blocker: str | None
    pixels: np.ndarray
    provenance_version: str | None
    snapshot_version: str
    alpha_mode: str
    input_order: str | None
    decoder_origin_binding: str
    pixel_object_identity: str
    pixel_content_identity: str
    contract_identity: str
    decode_time_pixel_sha256: str | None
    processing_snapshot_sha256: str
    snapshot_private_memory: bool
    snapshot_contiguous: bool
    snapshot_writeable: bool


@dataclass(frozen=True)
class _ManagedColorSourceProvenanceEntry:
    source_ref: weakref.ReferenceType[ManagedColorSource]
    pixels_ref: weakref.ReferenceType[np.ndarray]
    provenance_version: str
    alpha_mode: str
    pixel_sha256: str
    shape: tuple[int, ...]
    dtype: str
    channels: int
    contract: tuple[object, ...]


_MANAGED_SOURCE_PROVENANCE_REGISTRY: dict[
    int, _ManagedColorSourceProvenanceEntry
] = {}
_MANAGED_SOURCE_PROVENANCE_LOCK = RLock()
MANAGED_COLOR_SOURCE_ATOMIC_SNAPSHOT_VERSION = (
    "hdde.managed-color-source-atomic-snapshot.v1"
)


def _canonical_array_sha256(array: np.ndarray) -> str:
    """Return the shared D57 canonical shape/dtype/content identity."""

    contiguous = np.ascontiguousarray(np.asarray(array))
    descriptor = json.dumps(
        {
            "shape": list(contiguous.shape),
            "dtype": contiguous.dtype.str,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(b"HDDE_D57_CANONICAL_ARRAY_V1\0")
    digest.update(len(descriptor).to_bytes(8, "big"))
    digest.update(descriptor)
    digest.update(contiguous.tobytes(order="C"))
    return digest.hexdigest().upper()


def _managed_source_contract(source: ManagedColorSource) -> tuple[object, ...]:
    return (
        source.source_format,
        source.source_mode,
        source.source_bit_depth,
        source.input_order,
        source.profile_status,
        source.source_profile_name,
        hashlib.sha256(bytes(source.output_icc_profile)).hexdigest().upper(),
        source.frame_count,
        source.source_dpi,
        source.source_resolution_exif,
        (
            hashlib.sha256(source.output_resolution_exif).hexdigest().upper()
            if source.output_resolution_exif is not None
            else None
        ),
    )


def _register_managed_color_source_provenance(
    source: ManagedColorSource,
) -> ManagedColorSource:
    """Register only the exact object emitted by the trusted decoder."""

    pixels = np.asarray(source.pixels)
    source_id = id(source)

    def remove_stale_source(
        source_ref: weakref.ReferenceType[ManagedColorSource],
    ) -> None:
        with _MANAGED_SOURCE_PROVENANCE_LOCK:
            current = _MANAGED_SOURCE_PROVENANCE_REGISTRY.get(source_id)
            if current is not None and current.source_ref is source_ref:
                _MANAGED_SOURCE_PROVENANCE_REGISTRY.pop(source_id, None)

    entry = _ManagedColorSourceProvenanceEntry(
        source_ref=weakref.ref(source, remove_stale_source),
        pixels_ref=weakref.ref(pixels),
        provenance_version=MANAGED_COLOR_SOURCE_PROVENANCE_VERSION,
        alpha_mode=("STRAIGHT_VALIDATED" if source.alpha_present else "NOT_APPLICABLE"),
        pixel_sha256=_canonical_array_sha256(pixels),
        shape=tuple(int(value) for value in pixels.shape),
        dtype=pixels.dtype.str,
        channels=int(pixels.shape[2]) if pixels.ndim == 3 else 0,
        contract=_managed_source_contract(source),
    )
    with _MANAGED_SOURCE_PROVENANCE_LOCK:
        _MANAGED_SOURCE_PROVENANCE_REGISTRY[source_id] = entry
    return source


def validate_managed_color_source_provenance(
    source: ManagedColorSource,
) -> ManagedColorSourceProvenanceValidation:
    """Revalidate decoder origin and the exact current decoded pixel identity."""

    pixels = np.asarray(source.pixels)
    current_sha256 = _canonical_array_sha256(pixels)
    with _MANAGED_SOURCE_PROVENANCE_LOCK:
        entry = _MANAGED_SOURCE_PROVENANCE_REGISTRY.get(id(source))
        if entry is not None and entry.source_ref() is not source:
            _MANAGED_SOURCE_PROVENANCE_REGISTRY.pop(id(source), None)
            entry = None

    if entry is None:
        return ManagedColorSourceProvenanceValidation(
            valid=False,
            blocker="MANAGED_SOURCE_UNREGISTERED_INSTANCE",
            provenance_version=None,
            alpha_mode="UNKNOWN",
            decoder_origin_binding="FAIL",
            pixel_object_identity="NOT_EVALUABLE",
            pixel_content_identity="NOT_EVALUABLE",
            contract_identity="NOT_EVALUABLE",
            decode_time_pixel_sha256=None,
            current_pixel_sha256=current_sha256,
        )

    origin_valid = entry.source_ref() is source
    pixel_object_valid = entry.pixels_ref() is source.pixels
    shape = tuple(int(value) for value in pixels.shape)
    channels = int(pixels.shape[2]) if pixels.ndim == 3 else 0
    try:
        current_contract = _managed_source_contract(source)
        current_alpha_mode = (
            "STRAIGHT_VALIDATED" if source.alpha_present else "NOT_APPLICABLE"
        )
    except (AttributeError, TypeError, ValueError):
        current_contract = None
        current_alpha_mode = "UNKNOWN"
    contract_valid = (
        entry.provenance_version == MANAGED_COLOR_SOURCE_PROVENANCE_VERSION
        and entry.shape == shape
        and entry.dtype == pixels.dtype.str
        and entry.channels == channels
        and entry.contract == current_contract
        and entry.alpha_mode == current_alpha_mode
    )
    content_valid = current_sha256 == entry.pixel_sha256

    if not origin_valid:
        blocker = "MANAGED_SOURCE_DECODER_ORIGIN_MISMATCH"
    elif not pixel_object_valid:
        blocker = "MANAGED_SOURCE_PIXEL_OBJECT_REPLACED"
    elif not contract_valid:
        blocker = "MANAGED_SOURCE_CONTRACT_MISMATCH"
    elif not content_valid:
        blocker = "MANAGED_SOURCE_PIXEL_IDENTITY_MISMATCH"
    else:
        blocker = None

    return ManagedColorSourceProvenanceValidation(
        valid=blocker is None,
        blocker=blocker,
        provenance_version=entry.provenance_version,
        alpha_mode=entry.alpha_mode,
        decoder_origin_binding="PASS" if origin_valid else "FAIL",
        pixel_object_identity="PASS" if pixel_object_valid else "FAIL",
        pixel_content_identity="PASS" if content_valid else "FAIL",
        contract_identity="PASS" if contract_valid else "FAIL",
        decode_time_pixel_sha256=entry.pixel_sha256,
        current_pixel_sha256=current_sha256,
    )


def _copy_managed_source_pixels(pixels: np.ndarray) -> np.ndarray:
    """Create the private contiguous pixel snapshot consumed by D57 prototypes."""

    snapshot = np.ascontiguousarray(np.asarray(pixels)).copy(order="C")
    snapshot.setflags(write=False)
    return snapshot


def acquire_validated_managed_source_snapshot(
    source: ManagedColorSource,
) -> ManagedColorSourceSnapshotAcquisition:
    """Bind decoder provenance to one private immutable processing snapshot.

    The live ``source.pixels`` array is deliberately not locked for the duration
    of processing. Instead, this function copies the registered pixel object,
    validates the copy against the decoder-time hash, and returns only that
    private copy. Mutations after a successful return therefore cannot change
    the processing input or its evidence identity.
    """

    pixels_object = source.pixels
    with _MANAGED_SOURCE_PROVENANCE_LOCK:
        entry = _MANAGED_SOURCE_PROVENANCE_REGISTRY.get(id(source))
        if entry is not None and entry.source_ref() is not source:
            _MANAGED_SOURCE_PROVENANCE_REGISTRY.pop(id(source), None)
            entry = None

    snapshot = _copy_managed_source_pixels(pixels_object)
    snapshot_sha256 = _canonical_array_sha256(snapshot)
    snapshot_private_memory = not np.shares_memory(snapshot, pixels_object)
    snapshot_contiguous = bool(snapshot.flags.c_contiguous)
    snapshot_writeable = bool(snapshot.flags.writeable)

    if entry is None:
        return ManagedColorSourceSnapshotAcquisition(
            valid=False,
            blocker="MANAGED_SOURCE_UNREGISTERED_INSTANCE",
            pixels=snapshot,
            provenance_version=None,
            snapshot_version=MANAGED_COLOR_SOURCE_ATOMIC_SNAPSHOT_VERSION,
            alpha_mode="UNKNOWN",
            input_order=None,
            decoder_origin_binding="FAIL",
            pixel_object_identity="NOT_EVALUABLE",
            pixel_content_identity="NOT_EVALUABLE",
            contract_identity="NOT_EVALUABLE",
            decode_time_pixel_sha256=None,
            processing_snapshot_sha256=snapshot_sha256,
            snapshot_private_memory=snapshot_private_memory,
            snapshot_contiguous=snapshot_contiguous,
            snapshot_writeable=snapshot_writeable,
        )

    with _MANAGED_SOURCE_PROVENANCE_LOCK:
        current_entry = _MANAGED_SOURCE_PROVENANCE_REGISTRY.get(id(source))
    origin_valid = current_entry is entry and entry.source_ref() is source
    pixel_object_valid = (
        entry.pixels_ref() is pixels_object and source.pixels is pixels_object
    )
    try:
        current_contract = _managed_source_contract(source)
        current_alpha_mode = (
            "STRAIGHT_VALIDATED" if source.alpha_present else "NOT_APPLICABLE"
        )
    except (AttributeError, TypeError, ValueError):
        current_contract = None
        current_alpha_mode = "UNKNOWN"
    contract_valid = (
        entry.provenance_version == MANAGED_COLOR_SOURCE_PROVENANCE_VERSION
        and entry.shape == tuple(int(value) for value in snapshot.shape)
        and entry.dtype == snapshot.dtype.str
        and entry.channels == (
            int(snapshot.shape[2]) if snapshot.ndim == 3 else 0
        )
        and entry.contract == current_contract
        and entry.alpha_mode == current_alpha_mode
    )
    content_valid = snapshot_sha256 == entry.pixel_sha256

    if not origin_valid:
        blocker = "MANAGED_SOURCE_DECODER_ORIGIN_MISMATCH"
    elif not pixel_object_valid:
        blocker = "MANAGED_SOURCE_PIXEL_OBJECT_REPLACED"
    elif not contract_valid:
        blocker = "MANAGED_SOURCE_CONTRACT_MISMATCH"
    elif not snapshot_private_memory:
        blocker = "MANAGED_SOURCE_SNAPSHOT_MEMORY_ALIAS"
    elif not snapshot_contiguous:
        blocker = "MANAGED_SOURCE_SNAPSHOT_NOT_CONTIGUOUS"
    elif snapshot_writeable:
        blocker = "MANAGED_SOURCE_SNAPSHOT_WRITEABLE"
    elif not content_valid:
        blocker = "MANAGED_SOURCE_PIXEL_IDENTITY_MISMATCH"
    else:
        blocker = None

    return ManagedColorSourceSnapshotAcquisition(
        valid=blocker is None,
        blocker=blocker,
        pixels=snapshot,
        provenance_version=entry.provenance_version,
        snapshot_version=MANAGED_COLOR_SOURCE_ATOMIC_SNAPSHOT_VERSION,
        alpha_mode=entry.alpha_mode,
        input_order=(str(entry.contract[3]) if len(entry.contract) > 3 else None),
        decoder_origin_binding="PASS" if origin_valid else "FAIL",
        pixel_object_identity="PASS" if pixel_object_valid else "FAIL",
        pixel_content_identity="PASS" if content_valid else "FAIL",
        contract_identity="PASS" if contract_valid else "FAIL",
        decode_time_pixel_sha256=entry.pixel_sha256,
        processing_snapshot_sha256=snapshot_sha256,
        snapshot_private_memory=snapshot_private_memory,
        snapshot_contiguous=snapshot_contiguous,
        snapshot_writeable=snapshot_writeable,
    )


@lru_cache(maxsize=1)
def srgb_profile_bytes() -> bytes:
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    return profile.tobytes()


def _open_profile(payload: bytes) -> ImageCms.ImageCmsProfile:
    try:
        return ImageCms.getOpenProfile(BytesIO(payload))
    except Exception as exc:  # Pillow exposes multiple lcms exception types.
        raise ColorManagementError("FORMAL_COLOR_ICC_INVALID") from exc


def _profile_name(profile: ImageCms.ImageCmsProfile) -> str:
    labels: list[str] = []
    for getter in (ImageCms.getProfileDescription, ImageCms.getProfileName):
        try:
            label = str(getter(profile)).strip()
        except Exception:
            label = ""
        if label and label not in labels:
            labels.append(label)
    return " | ".join(labels) or "UNNAMED_PROFILE"


@lru_cache(maxsize=1)
def _srgb_equivalence_probe() -> np.ndarray:
    levels = np.linspace(0, 255, 17, dtype=np.uint8)
    return np.stack(np.meshgrid(levels, levels, levels, indexing="ij"), axis=-1).reshape(17, 289, 3)


def _is_supported_srgb(profile: ImageCms.ImageCmsProfile) -> bool:
    """Accept profiles by their CMM behaviour, never by a human-readable label."""

    color_space = str(getattr(profile.profile, "xcolor_space", "")).strip().upper()
    if color_space != "RGB":
        return False
    probe = _srgb_equivalence_probe()
    try:
        converted = ImageCms.profileToProfile(
            Image.fromarray(probe, mode="RGB"),
            profile,
            ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")),
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            outputMode="RGB",
        )
    except Exception:
        return False
    converted_pixels = np.asarray(converted, dtype=np.uint8)
    if converted_pixels.shape != probe.shape:
        return False
    channel_delta = np.abs(converted_pixels.astype(np.int16) - probe.astype(np.int16))
    return int(channel_delta.max(initial=0)) <= _SRGB_EQUIVALENCE_MAX_CHANNEL_DELTA


def _profile_labels(profile: ImageCms.ImageCmsProfile) -> frozenset[str]:
    labels: set[str] = set()
    for getter in (ImageCms.getProfileDescription, ImageCms.getProfileName):
        try:
            label = " ".join(str(getter(profile)).split()).casefold()
        except Exception:
            label = ""
        if label:
            labels.add(label)
    return frozenset(labels)


def _profile_primary_xy(
    profile: ImageCms.ImageCmsProfile,
    channel: str,
) -> tuple[float, float] | None:
    try:
        primary = getattr(profile.profile, f"{channel}_primary")
        xy_y = primary[1]
        x, y = float(xy_y[0]), float(xy_y[1])
    except (AttributeError, IndexError, TypeError, ValueError):
        return None
    if not np.isfinite((x, y)).all():
        return None
    return x, y


def _profile_has_expected_primaries(
    profile: ImageCms.ImageCmsProfile,
    family: str,
) -> bool:
    bounds = _SUPPORTED_WIDE_GAMUT_PRIMARY_BOUNDS[family]
    for channel in ("red", "green", "blue"):
        primary = _profile_primary_xy(profile, channel)
        if primary is None:
            return False
        x, y = primary
        x_bounds, y_bounds = bounds[channel]
        if not (x_bounds[0] <= x <= x_bounds[1] and y_bounds[0] <= y <= y_bounds[1]):
            return False
    return True


def _profile_has_safe_matrix_contract(profile: ImageCms.ImageCmsProfile) -> bool:
    profile_data = profile.profile
    device_class = str(getattr(profile_data, "device_class", "")).strip().casefold()
    color_space = str(getattr(profile_data, "xcolor_space", "")).strip().upper()
    connection_space = str(getattr(profile_data, "connection_space", "")).strip().upper()
    if device_class != "mntr" or color_space != "RGB" or connection_space != "XYZ":
        return False
    if not bool(getattr(profile_data, "is_matrix_shaper", False)):
        return False
    try:
        white_point = getattr(profile_data, "media_white_point")[1]
        white_x, white_y = float(white_point[0]), float(white_point[1])
    except (AttributeError, IndexError, TypeError, ValueError):
        return False
    return bool(
        np.isfinite((white_x, white_y)).all()
        and 0.30 <= white_x <= 0.36
        and 0.31 <= white_y <= 0.37
    )


def _cmm_wide_gamut_probe_is_safe(profile: ImageCms.ImageCmsProfile) -> bool:
    probe = _srgb_equivalence_probe()
    try:
        converted = ImageCms.profileToProfile(
            Image.fromarray(probe, mode="RGB"),
            profile,
            ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")),
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            outputMode="RGB",
        )
    except Exception:
        return False
    converted_pixels = np.asarray(converted, dtype=np.uint8)
    if converted_pixels.shape != probe.shape:
        return False
    flat_probe = probe.reshape(-1, 3)
    flat_converted = converted_pixels.reshape(-1, 3)
    neutral = np.all(flat_probe == flat_probe[:, :1], axis=1)
    neutral_output = flat_converted[neutral].astype(np.int16)
    if neutral_output.shape[0] != 17:
        return False
    if int(np.ptp(neutral_output, axis=1).max(initial=0)) > _WIDE_GAMUT_NEUTRAL_MAX_CHANNEL_SPAN:
        return False
    if np.any(np.diff(neutral_output, axis=0) < 0):
        return False
    if int(flat_converted[0].max(initial=0)) > _WIDE_GAMUT_BLACK_MAX_CHANNEL_VALUE:
        return False
    if int(flat_converted[-1].min(initial=255)) < _WIDE_GAMUT_WHITE_MIN_CHANNEL_VALUE:
        return False
    return True


def _supported_profile_family(profile: ImageCms.ImageCmsProfile) -> str | None:
    if _is_supported_srgb(profile):
        return "SRGB"
    if not _profile_has_safe_matrix_contract(profile):
        return None
    labels = _profile_labels(profile)
    for family, supported_labels in _SUPPORTED_WIDE_GAMUT_LABELS.items():
        if labels & supported_labels and _profile_has_expected_primaries(profile, family):
            return family if _cmm_wide_gamut_probe_is_safe(profile) else None
    return None


def _metadata_conflict() -> None:
    raise ColorManagementError("FORMAL_COLOR_METADATA_CONFLICT")


def _icc_png_chromaticity(
    profile: ImageCms.ImageCmsProfile,
) -> tuple[float, ...] | None:
    """Recover source-space D65 chromaticities from the actual ICC matrix."""

    source_colorants: list[np.ndarray] = []
    for channel in ("red", "green", "blue"):
        try:
            pcs_xyz = np.asarray(
                getattr(profile.profile, f"{channel}_colorant")[0],
                dtype=np.float64,
            )
        except (AttributeError, IndexError, TypeError, ValueError):
            return None
        if pcs_xyz.shape != (3,) or not np.isfinite(pcs_xyz).all():
            return None
        source_xyz = _D50_TO_D65_BRADFORD @ pcs_xyz
        if not np.isfinite(source_xyz).all() or float(source_xyz.sum()) <= 0.0:
            return None
        source_colorants.append(source_xyz)

    source_white = np.sum(source_colorants, axis=0)
    if not np.isfinite(source_white).all() or float(source_white.sum()) <= 0.0:
        return None

    def xy(xyz: np.ndarray) -> tuple[float, float]:
        total = float(xyz.sum())
        return float(xyz[0] / total), float(xyz[1] / total)

    return (*xy(source_white), *(coordinate for xyz in source_colorants for coordinate in xy(xyz)))


def _icc_tag_payload(profile_payload: bytes, signature: bytes) -> bytes | None:
    if len(profile_payload) < 132 or len(signature) != 4:
        return None
    try:
        tag_count = struct.unpack_from(">I", profile_payload, 128)[0]
    except struct.error:
        return None
    if tag_count > (len(profile_payload) - 132) // 12:
        return None
    for index in range(tag_count):
        entry = 132 + index * 12
        if profile_payload[entry : entry + 4] != signature:
            continue
        try:
            offset, size = struct.unpack_from(">II", profile_payload, entry + 4)
        except struct.error:
            return None
        if size <= 0 or offset > len(profile_payload) or size > len(profile_payload) - offset:
            return None
        return profile_payload[offset : offset + size]
    return None


def _s15_fixed16_values(payload: bytes, count: int, offset: int = 12) -> tuple[float, ...] | None:
    if count < 0 or len(payload) < offset + count * 4:
        return None
    try:
        raw = struct.unpack_from(f">{count}i", payload, offset)
    except struct.error:
        return None
    return tuple(value / 65536.0 for value in raw)


def _trc_matches_srgb_contract(payload: bytes) -> bool:
    if len(payload) < 12 or payload[:4] != b"para":
        return False
    try:
        function_type = struct.unpack_from(">H", payload, 8)[0]
    except struct.error:
        return False
    expected = _SRGB_PARAMETRIC_TRC.get(function_type)
    if expected is None:
        return False
    actual = _s15_fixed16_values(payload, len(expected))
    return bool(
        actual is not None
        and np.allclose(actual, expected, rtol=0.0, atol=_ICC_TRC_PARAMETER_TOLERANCE)
    )


def _trc_gamma(payload: bytes) -> float | None:
    if len(payload) < 14 or payload[:4] != b"curv":
        return None
    try:
        count = struct.unpack_from(">I", payload, 8)[0]
        encoded_gamma = struct.unpack_from(">H", payload, 12)[0]
    except struct.error:
        return None
    if count != 1:
        return None
    gamma = encoded_gamma / 256.0
    return gamma if np.isfinite(gamma) and gamma > 0.0 else None


def _icc_png_gamma(
    profile_payload: bytes,
    profile_family: str,
) -> float | None:
    trcs = tuple(
        _icc_tag_payload(profile_payload, signature)
        for signature in (b"rTRC", b"gTRC", b"bTRC")
    )
    if any(trc is None for trc in trcs):
        return None
    channel_trcs = tuple(trc for trc in trcs if trc is not None)
    if profile_family in {"SRGB", "DISPLAY_P3"}:
        if not all(_trc_matches_srgb_contract(trc) for trc in channel_trcs):
            return None
        return _SRGB_PNG_GAMMA
    if profile_family == "ADOBE_RGB_1998":
        gammas = tuple(_trc_gamma(trc) for trc in channel_trcs)
        if any(gamma is None for gamma in gammas):
            return None
        numeric_gammas = tuple(float(gamma) for gamma in gammas if gamma is not None)
        if not np.allclose(
            numeric_gammas,
            (2.19921875,) * 3,
            rtol=0.0,
            atol=_ICC_TRC_PARAMETER_TOLERANCE,
        ):
            return None
        return 1.0 / float(np.mean(numeric_gammas))
    return None


def _validate_png_color_metadata(
    info: dict[object, object],
    profile_family: str,
    source_profile: ImageCms.ImageCmsProfile | None,
    embedded_icc: bytes | None,
) -> None:
    if "srgb" in info:
        try:
            rendering_intent = int(info["srgb"])
        except (TypeError, ValueError):
            _metadata_conflict()
        if rendering_intent not in {0, 1, 2, 3} or profile_family != "SRGB":
            _metadata_conflict()

    gamma = info.get("gamma")
    if gamma is not None:
        try:
            gamma_value = float(gamma)
        except (TypeError, ValueError):
            _metadata_conflict()
        if not np.isfinite(gamma_value):
            _metadata_conflict()
        expected_gamma = (
            _SRGB_PNG_GAMMA
            if source_profile is None
            else _icc_png_gamma(embedded_icc or b"", profile_family)
        )
        if expected_gamma is None or not np.isclose(
            gamma_value,
            expected_gamma,
            rtol=0.0,
            atol=_PNG_METADATA_TOLERANCE,
        ):
            _metadata_conflict()

    chromaticity = info.get("chromaticity")
    if chromaticity is not None:
        try:
            values = tuple(float(value) for value in chromaticity)
        except (TypeError, ValueError):
            _metadata_conflict()
        if source_profile is None:
            if len(values) != len(_SRGB_PNG_CHROMATICITY) or not np.allclose(
                values,
                _SRGB_PNG_CHROMATICITY,
                rtol=0.0,
                atol=_PNG_METADATA_TOLERANCE,
            ):
                _metadata_conflict()
        else:
            expected_chromaticity = _icc_png_chromaticity(source_profile)
            if (
                expected_chromaticity is None
                or len(values) != len(expected_chromaticity)
                or not np.allclose(
                    values,
                    expected_chromaticity,
                    rtol=0.0,
                    atol=_ICC_PNG_CHROMATICITY_TOLERANCE,
                )
            ):
                _metadata_conflict()


def _validate_exif_color_metadata(opened: Image.Image, profile_family: str) -> None:
    try:
        exif = opened.getexif()
    except ColorManagementError:
        raise
    except Exception:
        _metadata_conflict()

    try:
        exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
    except KeyError:
        exif_ifd = {}
    except Exception:
        _metadata_conflict()

    for color_space in (exif.get(40961), exif_ifd.get(40961) if exif_ifd else None):
        if color_space is not None:
            try:
                expected_color_space = 1 if profile_family == "SRGB" else 65535
                if int(color_space) != expected_color_space:
                    _metadata_conflict()
            except (TypeError, ValueError):
                _metadata_conflict()

    try:
        interop = exif.get_ifd(ExifTags.IFD.Interop)
    except KeyError:
        interop = {}
    except Exception:
        _metadata_conflict()

    interop_index = interop.get(1) if interop else None
    if interop_index is None:
        return
    if isinstance(interop_index, bytes):
        label = interop_index.decode("ascii", errors="ignore").rstrip("\x00").strip()
    else:
        label = str(interop_index).rstrip("\x00").strip()
    expected_interop = "R98" if profile_family == "SRGB" else "R03"
    if label and label != expected_interop:
        _metadata_conflict()


def _validate_color_metadata(
    opened: Image.Image,
    source_format: str,
    profile_family: str,
    source_profile: ImageCms.ImageCmsProfile | None,
    embedded_icc: bytes | None,
) -> None:
    if source_format == "PNG":
        _validate_png_color_metadata(
            opened.info,
            profile_family,
            source_profile,
            embedded_icc,
        )
    _validate_exif_color_metadata(opened, profile_family)


def _native_png_depth(path: Path) -> int:
    header = path.read_bytes()[:29]
    if len(header) < 29 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ColorManagementError("FORMAL_COLOR_PNG_HEADER_INVALID")
    return int(header[24])


def _valid_dpi(value: object) -> tuple[float, float] | None:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return None
    try:
        dpi = (float(value[0]), float(value[1]))
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(np.isfinite(item) and 0.0 < item <= 1_000_000.0 for item in dpi):
        return None
    return dpi


def _source_resolution_contract(
    opened: Image.Image,
) -> tuple[
    tuple[float, float] | None,
    tuple[str | None, str | None, str | None],
    bytes | None,
]:
    source_exif = opened.getexif()
    signature = tuple(
        repr(source_exif.get(tag)) if tag in source_exif else None
        for tag in (282, 283, 296)
    )
    resolution_exif = Image.Exif()
    for tag in (282, 283, 296):
        if tag in source_exif:
            resolution_exif[tag] = source_exif.get(tag)
    payload = resolution_exif.tobytes() if len(resolution_exif) else None

    source_format = str(opened.format or "").upper()
    if source_format == "JPEG":
        jfif_unit = opened.info.get("jfif_unit")
        jfif_density = opened.info.get("jfif_density")
        dpi = _valid_dpi(jfif_density) if jfif_unit == 1 else None
        if jfif_unit == 2:
            density = _valid_dpi(jfif_density)
            dpi = (
                (density[0] * 2.54, density[1] * 2.54)
                if density is not None
                else None
            )
    else:
        dpi = _valid_dpi(opened.info.get("dpi"))
    if dpi is None and all(tag in source_exif for tag in (282, 283, 296)):
        try:
            x_resolution = float(source_exif.get(282))
            y_resolution = float(source_exif.get(283))
            unit = int(source_exif.get(296))
            if unit == 3:
                x_resolution *= 2.54
                y_resolution *= 2.54
            elif unit != 2:
                x_resolution = y_resolution = 0.0
            dpi = _valid_dpi((x_resolution, y_resolution))
        except (TypeError, ValueError, OverflowError):
            dpi = None
    return dpi, signature, payload


def load_color_managed_source(path: str | Path) -> ManagedColorSource:
    """Decode one supported source into the explicit sRGB/RGB working domain."""

    source = Path(path).resolve()
    if not source.is_file():
        raise FileNotFoundError("FORMAL_COLOR_SOURCE_NOT_FOUND")

    try:
        opened_context = Image.open(source)
    except Exception as exc:
        raise ColorManagementError("FORMAL_COLOR_SOURCE_DECODE_FAILED") from exc

    with opened_context as opened:
        source_format = str(opened.format or "").upper()
        if source_format not in SUPPORTED_FORMATS:
            raise ColorManagementError("FORMAL_COLOR_RUNTIME_SUPPORTS_JPEG_AND_PNG_ONLY")

        frame_count = int(getattr(opened, "n_frames", 1) or 1)
        if frame_count != 1 or bool(getattr(opened, "is_animated", False)):
            raise ColorManagementError("FORMAL_COLOR_MULTIFRAME_UNSUPPORTED")

        if source_format == "PNG":
            native_depth = _native_png_depth(source)
            if native_depth == 16:
                raise ColorManagementError("FORMAL_COLOR_16BIT_AUTO_SUPPORT_SAFE_BLOCKED")
            if native_depth != 8:
                raise ColorManagementError("FORMAL_COLOR_PNG_BIT_DEPTH_UNSUPPORTED")

        opened.load()
        source_dpi, source_resolution_exif, output_resolution_exif = (
            _source_resolution_contract(opened)
        )
        embedded_icc = opened.info.get("icc_profile")
        source_profile: ImageCms.ImageCmsProfile | None = None
        source_profile_name: str | None = None
        embedded_icc_payload: bytes | None = None
        if embedded_icc is None:
            profile_family = "SRGB"
        else:
            if not isinstance(embedded_icc, (bytes, bytearray)) or not embedded_icc:
                raise ColorManagementError("FORMAL_COLOR_ICC_INVALID")
            embedded_icc_payload = bytes(embedded_icc)
            source_profile = _open_profile(embedded_icc_payload)
            source_profile_name = _profile_name(source_profile)
            profile_family = _supported_profile_family(source_profile)
            if profile_family is None:
                raise ColorManagementError("FORMAL_COLOR_NON_SRGB_PROFILE_SAFE_BLOCKED")

        _validate_color_metadata(
            opened,
            source_format,
            profile_family,
            source_profile,
            embedded_icc_payload,
        )
        oriented = ImageOps.exif_transpose(opened)
        source_mode = str(oriented.mode or "").upper()
        if source_mode not in SUPPORTED_MODES:
            raise ColorManagementError("FORMAL_COLOR_MODE_UNSUPPORTED")

        alpha = (
            np.asarray(oriented.getchannel("A"), dtype=np.uint8).copy()
            if source_mode == "RGBA"
            else None
        )
        rgb_image = oriented.convert("RGB")

        if source_profile is None:
            converted = rgb_image.copy()
            profile_status = "ASSUMED_SRGB"
        else:
            try:
                converted = ImageCms.profileToProfile(
                    rgb_image,
                    source_profile,
                    ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")),
                    renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
                    outputMode="RGB",
                )
            except Exception as exc:
                raise ColorManagementError("FORMAL_COLOR_ICC_CONVERSION_FAILED") from exc
            profile_status = "CMM_CONVERTED_TO_SRGB"

        rgb = np.asarray(converted, dtype=np.uint8).copy()
        pixels = np.dstack((rgb, alpha)) if alpha is not None else rgb
        managed_source = ManagedColorSource(
            pixels=np.ascontiguousarray(pixels),
            source_format=source_format,
            source_mode=source_mode,
            source_bit_depth=8,
            input_order="RGB",
            profile_status=profile_status,
            source_profile_name=source_profile_name,
            output_icc_profile=srgb_profile_bytes(),
            frame_count=frame_count,
            source_dpi=source_dpi,
            source_resolution_exif=source_resolution_exif,
            output_resolution_exif=output_resolution_exif,
        )
        return _register_managed_color_source_provenance(managed_source)


def encode_color_managed_candidate(
    candidate: np.ndarray,
    source: ManagedColorSource,
) -> bytes:
    """Encode a D3-selected candidate with pixels and ICC kept in agreement."""

    array = np.asarray(candidate)
    if array.shape != source.pixels.shape:
        raise ColorManagementError("FORMAL_COLOR_CANDIDATE_SHAPE_INVALID")
    if array.dtype != np.uint8:
        raise ColorManagementError("FORMAL_COLOR_CANDIDATE_BIT_DEPTH_UNSUPPORTED")
    if array.ndim != 3 or array.shape[2] not in {3, 4}:
        raise ColorManagementError("FORMAL_COLOR_CANDIDATE_CHANNELS_INVALID")
    if source.source_format == "JPEG" and array.shape[2] != 3:
        raise ColorManagementError("FORMAL_JPEG_CANDIDATE_DOMAIN_INVALID")
    if source.alpha_present:
        if array.shape[2] != 4 or not np.array_equal(array[..., 3], source.pixels[..., 3]):
            raise ColorManagementError("FORMAL_COLOR_ALPHA_CHANGED")
        transparent = source.pixels[..., 3] == 0
        if transparent.any() and not np.array_equal(
            array[..., :3][transparent],
            source.pixels[..., :3][transparent],
        ):
            raise ColorManagementError("FORMAL_COLOR_TRANSPARENT_RGB_CHANGED")

    image = Image.fromarray(array, mode="RGBA" if array.shape[2] == 4 else "RGB")
    stream = BytesIO()
    resolution_options: dict[str, Any] = {}
    if source.source_dpi is not None:
        resolution_options["dpi"] = source.source_dpi
    if source.output_resolution_exif is not None:
        resolution_options["exif"] = source.output_resolution_exif
    if source.source_format == "JPEG":
        image.save(
            stream,
            format="JPEG",
            quality=95,
            subsampling=0,
            optimize=True,
            icc_profile=source.output_icc_profile,
            **resolution_options,
        )
    else:
        image.save(
            stream,
            format="PNG",
            optimize=True,
            compress_level=7,
            icc_profile=source.output_icc_profile,
            **resolution_options,
        )
    return stream.getvalue()


def verify_color_managed_output(
    path: str | Path | bytes,
    candidate: np.ndarray,
    source: ManagedColorSource,
) -> None:
    """Verify the observable profile, bit depth, channels, and alpha contract."""

    try:
        opened_context = Image.open(BytesIO(path) if isinstance(path, bytes) else Path(path))
    except Exception as exc:
        raise ColorManagementError("FORMAL_OUTPUT_DECODE_FAILED") from exc

    with opened_context as opened:
        opened.load()
        if str(opened.format or "").upper() != source.source_format:
            raise ColorManagementError("FORMAL_OUTPUT_FORMAT_MISMATCH")
        if opened.size != (int(candidate.shape[1]), int(candidate.shape[0])):
            raise ColorManagementError("FORMAL_OUTPUT_DIMENSION_MISMATCH")
        output_icc = opened.info.get("icc_profile")
        if not isinstance(output_icc, (bytes, bytearray)) or not output_icc:
            raise ColorManagementError("FORMAL_OUTPUT_ICC_MISSING")
        profile = _open_profile(bytes(output_icc))
        if not _is_supported_srgb(profile):
            raise ColorManagementError("FORMAL_OUTPUT_ICC_NOT_SRGB")
        output_dpi, _, _ = _source_resolution_contract(opened)
        if source.source_dpi is None:
            if output_dpi is not None:
                raise ColorManagementError("FORMAL_OUTPUT_DPI_FABRICATED")
        elif output_dpi is None or any(
            abs(actual - expected) > 0.02
            for actual, expected in zip(output_dpi, source.source_dpi)
        ):
            raise ColorManagementError("FORMAL_OUTPUT_DPI_MISMATCH")
        output_exif = opened.getexif()
        output_resolution_signature = tuple(
            repr(output_exif.get(tag)) if tag in output_exif else None
            for tag in (282, 283, 296)
        )
        if output_resolution_signature != source.source_resolution_exif:
            raise ColorManagementError("FORMAL_OUTPUT_EXIF_RESOLUTION_MISMATCH")

        if source.source_format == "PNG":
            decoded = np.asarray(opened)
            if decoded.dtype != np.uint8:
                raise ColorManagementError("FORMAL_OUTPUT_BIT_DEPTH_MISMATCH")
            if decoded.shape != candidate.shape or not np.array_equal(decoded, candidate):
                raise ColorManagementError("FORMAL_OUTPUT_PNG_PIXEL_MISMATCH")
        elif str(opened.mode).upper() != "RGB":
            raise ColorManagementError("FORMAL_OUTPUT_JPEG_MODE_MISMATCH")


__all__ = [
    "COLOR_MANAGEMENT_VERSION",
    "MANAGED_COLOR_SOURCE_ATOMIC_SNAPSHOT_VERSION",
    "MANAGED_COLOR_SOURCE_PROVENANCE_VERSION",
    "WORKING_COLOR_SPACE",
    "ColorManagementError",
    "ManagedColorSource",
    "ManagedColorSourceProvenanceValidation",
    "ManagedColorSourceSnapshotAcquisition",
    "acquire_validated_managed_source_snapshot",
    "encode_color_managed_candidate",
    "load_color_managed_source",
    "srgb_profile_bytes",
    "validate_managed_color_source_provenance",
    "verify_color_managed_output",
]
