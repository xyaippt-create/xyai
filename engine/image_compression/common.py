from __future__ import annotations

import binascii
import hashlib
import io
import os
import struct
import tempfile
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageOps, JpegImagePlugin, PngImagePlugin

from .contracts import ImageCompressionResult, ImageCompressionTask, base_result_for_task
from .statuses import (
    CandidateDeliveryRole,
    TechnicalStatus,
    VisualReviewStatus,
    evaluate_delivery_gate,
)


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
FaultInjector = Callable[[str], None]


class CompressionRuntimeError(RuntimeError):
    def __init__(self, failure_code: str, reason: str, technical_status: TechnicalStatus = TechnicalStatus.PROCESSING_FAILED):
        super().__init__(reason)
        self.failure_code = failure_code
        self.reason = reason
        self.technical_status = technical_status


@dataclass(frozen=True)
class OutputPlan:
    final_path: Path
    output_directory: Path


def sha256_bytes(value: bytes | None) -> str | None:
    return hashlib.sha256(value).hexdigest() if value is not None else None


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_format(path: str | Path) -> str:
    with Path(path).open("rb") as handle:
        header = handle.read(16)
    if header.startswith(PNG_SIGNATURE):
        return "PNG"
    if header.startswith(JPEG_SIGNATURE):
        return "JPEG"
    return "UNKNOWN"


def _normalise_dpi(value: Any) -> list[float] | None:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return None
    try:
        return [round(float(value[0]), 4), round(float(value[1]), 4)]
    except (TypeError, ValueError):
        return None


def _xmp_bytes(info: dict[str, Any]) -> bytes:
    value = info.get("xmp") or info.get("XML:com.adobe.xmp") or b""
    if isinstance(value, str):
        return value.encode("utf-8")
    return value if isinstance(value, bytes) else b""


def read_image_info(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    magic = detect_format(source)
    if magic not in {"PNG", "JPEG"}:
        raise CompressionRuntimeError("SOURCE_FORMAT_UNSUPPORTED", "Only PNG and JPEG are supported.", TechnicalStatus.CANNOT_MEET_SAFELY)
    try:
        with Image.open(source) as opened:
            opened.load()
            file_format = "JPEG" if opened.format == "JPG" else str(opened.format or "UNKNOWN").upper()
            info = dict(opened.info or {})
            icc = info.get("icc_profile") if isinstance(info.get("icc_profile"), bytes) else None
            exif = info.get("exif") if isinstance(info.get("exif"), bytes) else b""
            if not exif:
                try:
                    exif_obj = opened.getexif()
                    exif = exif_obj.tobytes() if len(exif_obj) else b""
                except Exception:
                    exif = b""
            try:
                orientation = opened.getexif().get(274)
            except Exception:
                orientation = None
            xmp = _xmp_bytes(info)
            alpha_present = "A" in opened.getbands() or "transparency" in info
            alpha = opened.convert("RGBA").getchannel("A").tobytes() if alpha_present else None
            quantization = getattr(opened, "quantization", None) if file_format == "JPEG" else None
            try:
                sampling = JpegImagePlugin.get_sampling(opened) if file_format == "JPEG" else None
            except Exception:
                sampling = None
            result = {
                "path": str(source.resolve()),
                "sha256": sha256_file(source),
                "format": file_format,
                "magic_format": magic,
                "dimensions": {"width": opened.width, "height": opened.height},
                "size_bytes": source.stat().st_size,
                "mode": opened.mode,
                "pixel_sha256": sha256_bytes(opened.tobytes()),
                "alpha_present": alpha_present,
                "alpha_sha256": sha256_bytes(alpha),
                "icc_profile": icc,
                "icc_sha256": sha256_bytes(icc),
                "exif_bytes": exif,
                "exif_sha256": sha256_bytes(exif) if exif else None,
                "exif_orientation": orientation,
                "dpi": _normalise_dpi(info.get("dpi")),
                "xmp_bytes": xmp,
                "xmp_sha256": sha256_bytes(xmp) if xmp else None,
                "jpeg_quantization": quantization,
                "jpeg_sampling": sampling,
            }
        with Image.open(source) as verify_image:
            verify_image.verify()
        return result
    except CompressionRuntimeError:
        raise
    except Exception as exc:
        raise CompressionRuntimeError("SOURCE_DECODE_FAILED", f"Source image cannot be fully decoded: {exc}") from exc


def parse_png_chunks(value: bytes) -> list[dict[str, Any]]:
    if not value.startswith(PNG_SIGNATURE):
        raise CompressionRuntimeError("PNG_STRUCTURE_INVALID", "Invalid PNG signature.", TechnicalStatus.CANNOT_MEET_SAFELY)
    chunks: list[dict[str, Any]] = []
    offset = len(PNG_SIGNATURE)
    while offset < len(value):
        if offset + 12 > len(value):
            raise CompressionRuntimeError("PNG_STRUCTURE_INVALID", "Truncated PNG chunk.", TechnicalStatus.CANNOT_MEET_SAFELY)
        length = struct.unpack(">I", value[offset : offset + 4])[0]
        end = offset + 12 + length
        if end > len(value):
            raise CompressionRuntimeError("PNG_STRUCTURE_INVALID", "Truncated PNG payload.", TechnicalStatus.CANNOT_MEET_SAFELY)
        chunk_type = value[offset + 4 : offset + 8]
        data = value[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", value[offset + 8 + length : end])[0]
        actual_crc = binascii.crc32(data, binascii.crc32(chunk_type)) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise CompressionRuntimeError("PNG_STRUCTURE_INVALID", f"PNG CRC mismatch: {chunk_type!r}", TechnicalStatus.CANNOT_MEET_SAFELY)
        chunks.append({"type": chunk_type, "data": data, "raw": value[offset:end]})
        offset = end
        if chunk_type == b"IEND":
            break
    types = [item["type"] for item in chunks]
    if offset != len(value) or not types or types[0] != b"IHDR" or types[-1] != b"IEND" or b"IDAT" not in types:
        raise CompressionRuntimeError("PNG_STRUCTURE_INVALID", "PNG structure is incomplete.", TechnicalStatus.CANNOT_MEET_SAFELY)
    if any(item in {b"acTL", b"fcTL", b"fdAT"} for item in types):
        raise CompressionRuntimeError("APNG_NOT_SUPPORTED", "Animated PNG is outside the verified lossless route.", TechnicalStatus.CANNOT_MEET_SAFELY)
    idat_indices = [index for index, item in enumerate(types) if item == b"IDAT"]
    if idat_indices != list(range(idat_indices[0], idat_indices[-1] + 1)):
        raise CompressionRuntimeError("PNG_STRUCTURE_INVALID", "PNG IDAT chunks must be contiguous.", TechnicalStatus.CANNOT_MEET_SAFELY)
    return chunks


def _make_png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = binascii.crc32(data, binascii.crc32(chunk_type)) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _compress_scanlines(scanlines: bytes, strategy: int) -> bytes:
    compressor = zlib.compressobj(9, zlib.DEFLATED, 15, 9, strategy)
    return compressor.compress(scanlines) + compressor.flush()


def optimise_png_data(raw: bytes) -> tuple[bytes, dict[str, Any]]:
    chunks = parse_png_chunks(raw)
    compressed = b"".join(item["data"] for item in chunks if item["type"] == b"IDAT")
    try:
        decompressor = zlib.decompressobj()
        scanlines = decompressor.decompress(compressed) + decompressor.flush()
        if not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
            raise zlib.error("incomplete zlib stream")
    except zlib.error as exc:
        raise CompressionRuntimeError("PNG_IDAT_INVALID", f"PNG IDAT stream is invalid: {exc}", TechnicalStatus.CANNOT_MEET_SAFELY) from exc
    options = {
        "Z_DEFAULT_STRATEGY": _compress_scanlines(scanlines, zlib.Z_DEFAULT_STRATEGY),
        "Z_FILTERED": _compress_scanlines(scanlines, zlib.Z_FILTERED),
        "Z_RLE": _compress_scanlines(scanlines, zlib.Z_RLE),
    }
    strategy, selected = min(options.items(), key=lambda item: len(item[1]))
    rebuilt = bytearray(PNG_SIGNATURE)
    wrote_idat = False
    for item in chunks:
        if item["type"] == b"IDAT":
            if not wrote_idat:
                rebuilt.extend(_make_png_chunk(b"IDAT", selected))
                wrote_idat = True
        else:
            rebuilt.extend(item["raw"])
    return bytes(rebuilt), {
        "strategy": strategy,
        "original_idat_bytes": len(compressed),
        "candidate_idat_bytes": len(selected),
        "scanline_sha256": sha256_bytes(scanlines),
    }


def optimise_png_bytes(source: str | Path) -> tuple[bytes, dict[str, Any]]:
    return optimise_png_data(Path(source).read_bytes())


def png_non_idat_chunks(value: bytes) -> list[bytes]:
    return [item["raw"] for item in parse_png_chunks(value) if item["type"] != b"IDAT"]


def plan_output_path(task: ImageCompressionTask, source_format: str) -> OutputPlan:
    source = Path(task.source_path).resolve()
    output_directory = Path(task.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    suffix = ".png" if source_format == "PNG" else ".jpg"
    candidate = output_directory / f"{source.stem}__{task.task_id}{suffix}"
    if candidate.resolve() == source:
        raise CompressionRuntimeError("OUTPUT_PATH_CONFLICT", "Output path would overwrite the source.")
    if task.overwrite_policy == "FAIL_IF_EXISTS" and candidate.exists():
        raise CompressionRuntimeError("OUTPUT_EXISTS", "The deterministic output path already exists.")
    if task.overwrite_policy == "UNIQUE_SUFFIX" and candidate.exists():
        index = 1
        while True:
            alternative = candidate.with_name(f"{candidate.stem}__{index}{candidate.suffix}")
            if not alternative.exists():
                candidate = alternative
                break
            index += 1
    return OutputPlan(candidate, output_directory)


def verify_image_file(path: str | Path, expected_format: str, expected_dimensions: tuple[int, int]) -> None:
    candidate = Path(path)
    if detect_format(candidate) != expected_format:
        raise CompressionRuntimeError("OUTPUT_FORMAT_MISMATCH", "Candidate magic format does not match the source format.")
    try:
        with Image.open(candidate) as image:
            image.load()
            actual_format = "JPEG" if image.format == "JPG" else str(image.format or "UNKNOWN").upper()
            if actual_format != expected_format or image.size != expected_dimensions:
                raise CompressionRuntimeError("OUTPUT_VERIFICATION_FAILED", "Candidate format or dimensions are invalid.")
        with Image.open(candidate) as image:
            image.verify()
    except CompressionRuntimeError:
        raise
    except Exception as exc:
        raise CompressionRuntimeError("OUTPUT_DECODE_FAILED", f"Candidate cannot be fully decoded: {exc}") from exc


def atomic_write_bytes(
    data: bytes,
    plan: OutputPlan,
    *,
    source_path: str | Path,
    source_sha256: str,
    expected_format: str,
    expected_dimensions: tuple[int, int],
    fault_injector: FaultInjector | None = None,
    extra_verifier: Callable[[Path], None] | None = None,
) -> Path:
    final_path = plan.final_path
    if final_path.exists():
        raise CompressionRuntimeError("OUTPUT_EXISTS", "The final output already exists.")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{final_path.name}.", suffix=".tmp", dir=plan.output_directory)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        if fault_injector:
            fault_injector("TEMP_WRITE")
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        verify_image_file(temporary, expected_format, expected_dimensions)
        if extra_verifier:
            extra_verifier(temporary)
        if sha256_file(source_path) != source_sha256:
            raise CompressionRuntimeError("SOURCE_SHA_CHANGED", "Source SHA256 changed during processing.")
        if final_path.exists():
            raise CompressionRuntimeError("OUTPUT_EXISTS", "The final output appeared during processing.")
        if fault_injector:
            fault_injector("ATOMIC_WRITE")
        # Link the fully verified temporary file into place atomically.  Unlike
        # os.replace(), os.link() never overwrites an existing destination;
        # this closes the check-then-replace race for FAIL_IF_EXISTS.  The
        # temporary link is removed only after the final link succeeds.
        try:
            os.link(temporary, final_path)
            temporary.unlink()
        except FileExistsError as exc:
            raise CompressionRuntimeError("OUTPUT_EXISTS", "The final output appeared during processing.") from exc
        if sha256_file(source_path) != source_sha256:
            try:
                final_path.unlink()
            except OSError:
                pass
            raise CompressionRuntimeError("SOURCE_SHA_CHANGED", "Source SHA256 changed during atomic save.")
        return final_path
    except PermissionError as exc:
        raise CompressionRuntimeError("OUTPUT_WRITE_PERMISSION_DENIED", f"Output write permission was denied: {exc}") from exc
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def transferable_save_kwargs(source_info: dict[str, Any], *, png: bool) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if source_info.get("icc_profile"):
        kwargs["icc_profile"] = source_info["icc_profile"]
    if source_info.get("exif_bytes"):
        kwargs["exif"] = source_info["exif_bytes"]
    if source_info.get("dpi"):
        kwargs["dpi"] = tuple(source_info["dpi"])
    xmp = source_info.get("xmp_bytes") or b""
    if png and xmp:
        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add_itxt("XML:com.adobe.xmp", xmp.decode("utf-8", errors="replace"))
        kwargs["pnginfo"] = pnginfo
    elif not png and xmp:
        kwargs["xmp"] = xmp
    return kwargs


def encode_image_bytes(image: Image.Image, source_info: dict[str, Any], *, jpeg_quality: int | None = None) -> bytes:
    output = io.BytesIO()
    if source_info["format"] == "PNG":
        kwargs = transferable_save_kwargs(source_info, png=True)
        image.save(output, format="PNG", compress_level=6, optimize=False, **kwargs)
    else:
        kwargs = transferable_save_kwargs(source_info, png=False)
        quantization = source_info.get("jpeg_quantization")
        sampling = source_info.get("jpeg_sampling")
        if jpeg_quality is None and quantization and sampling in {0, 1, 2}:
            tables = [quantization[key] for key in sorted(quantization)]
            encoding = {"qtables": tables, "subsampling": sampling, "optimize": True, "progressive": False}
        else:
            encoding = {
                "quality": jpeg_quality or 95,
                "subsampling": sampling if sampling in {0, 1, 2} else 0,
                "optimize": True,
                "progressive": False,
            }
        image.convert("RGB").save(output, format="JPEG", **encoding, **kwargs)
    return output.getvalue()


def resize_from_source(source_path: str | Path, target: tuple[int, int], policy: str) -> tuple[Image.Image, bool]:
    with Image.open(source_path) as opened:
        opened.load()
        has_alpha = "A" in opened.getbands() or "transparency" in opened.info
        image = ImageOps.exif_transpose(opened).copy()
    # Palette and LA images can carry transparency without an ``RGBA`` mode.
    # Normalise every alpha-bearing source before premultiplied resampling so
    # transparent RGB values cannot bleed into the resized edge.
    if has_alpha and image.mode != "RGBA":
        image = image.convert("RGBA")
    if policy == "INTER_AREA_PHOTO_ONLY":
        import cv2

        array = np.asarray(image)
        if image.mode == "RGBA":
            rgba = array.astype(np.float32) / 255.0
            alpha = rgba[..., 3:4]
            premultiplied = rgba[..., :3] * alpha
            resized_premultiplied = cv2.resize(premultiplied, target, interpolation=cv2.INTER_AREA)
            resized_alpha = cv2.resize(alpha[..., 0], target, interpolation=cv2.INTER_AREA)[..., None]
            rgb = np.divide(resized_premultiplied, resized_alpha, out=np.zeros_like(resized_premultiplied), where=resized_alpha > 1e-8)
            output = np.concatenate((rgb, resized_alpha), axis=2)
            output[output[..., 3] <= 0, :3] = 0
            return Image.fromarray(np.round(np.clip(output, 0, 1) * 255).astype(np.uint8), mode="RGBA"), True
        resized = cv2.resize(array, target, interpolation=cv2.INTER_AREA)
        return Image.fromarray(resized, mode=image.mode), False
    if image.mode == "RGBA":
        rgba = np.asarray(image, dtype=np.float32) / 255.0
        alpha = rgba[..., 3]
        premultiplied = rgba[..., :3] * alpha[..., None]
        channels = [Image.fromarray(np.round(premultiplied[..., index] * 255).astype(np.uint8), mode="L").resize(target, Image.Resampling.LANCZOS) for index in range(3)]
        alpha_image = Image.fromarray(np.round(alpha * 255).astype(np.uint8), mode="L").resize(target, Image.Resampling.LANCZOS)
        resized_alpha = np.asarray(alpha_image, dtype=np.float32) / 255.0
        resized_premultiplied = np.stack([np.asarray(channel, dtype=np.float32) / 255.0 for channel in channels], axis=2)
        rgb = np.divide(resized_premultiplied, resized_alpha[..., None], out=np.zeros_like(resized_premultiplied), where=resized_alpha[..., None] > 1e-8)
        output = np.concatenate((rgb, resized_alpha[..., None]), axis=2)
        output[resized_alpha <= 0, :3] = 0
        return Image.fromarray(np.round(np.clip(output, 0, 1) * 255).astype(np.uint8), mode="RGBA"), True
    return image.resize(target, Image.Resampling.LANCZOS), False


def compare_metadata(source: dict[str, Any], output: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    png_non_idat_preserved: bool | None = None
    png_plte_preserved: bool | None = None
    png_trns_preserved: bool | None = None
    if source.get("format") == output.get("format") == "PNG":
        try:
            source_chunks = parse_png_chunks(Path(source["path"]).read_bytes())
            output_chunks = parse_png_chunks(Path(output["path"]).read_bytes())
            ignored = {b"IHDR", b"IDAT", b"IEND"}
            source_ancillary = [(item["type"], item["raw"]) for item in source_chunks if item["type"] not in ignored]
            output_ancillary = [(item["type"], item["raw"]) for item in output_chunks if item["type"] not in ignored]
            png_non_idat_preserved = source_ancillary == output_ancillary
            def chunk_bytes(chunks: list[dict[str, Any]], chunk_type: bytes) -> list[bytes]:
                return [item["raw"] for item in chunks if item["type"] == chunk_type]
            png_plte_preserved = chunk_bytes(source_chunks, b"PLTE") == chunk_bytes(output_chunks, b"PLTE")
            png_trns_preserved = chunk_bytes(source_chunks, b"tRNS") == chunk_bytes(output_chunks, b"tRNS")
        except (OSError, CompressionRuntimeError):
            png_non_idat_preserved = False
            png_plte_preserved = False
            png_trns_preserved = False
    source_orientation = source.get("exif_orientation") or 1
    output_orientation = output.get("exif_orientation") or 1
    orientation_correct = output_orientation == 1
    details = {
        "icc_preserved": source.get("icc_sha256") == output.get("icc_sha256"),
        # A transformed orientation is semantically preserved when it is
        # normalised to 1, even though the EXIF byte hash necessarily changes.
        "exif_preserved": source.get("exif_sha256") == output.get("exif_sha256") or (source_orientation not in {1} and orientation_correct),
        "dpi_preserved": source.get("dpi") == output.get("dpi"),
        "xmp_preserved": source.get("xmp_sha256") == output.get("xmp_sha256"),
        "orientation_semantics_correct": orientation_correct,
        "png_non_idat_preserved": png_non_idat_preserved,
        "png_plte_preserved": png_plte_preserved,
        "png_trns_preserved": png_trns_preserved,
        "jpeg_quantization_preserved": source.get("jpeg_quantization") == output.get("jpeg_quantization") if source["format"] == "JPEG" else None,
        "jpeg_sampling_preserved": source.get("jpeg_sampling") == output.get("jpeg_sampling") if source["format"] == "JPEG" else None,
        "unsupported_or_unchecked_items": [],
    }
    applicable = [value for key, value in details.items() if key != "unsupported_or_unchecked_items" and value is not None]
    return all(applicable), details


def populate_source(result: ImageCompressionResult, source: dict[str, Any]) -> None:
    result.source_path = source["path"]
    result.source_sha256 = source["sha256"]
    result.source_format = source["format"]
    result.source_dimensions = dict(source["dimensions"])
    result.source_size_bytes = source["size_bytes"]


def apply_delivery_gate(
    result: ImageCompressionResult,
    *,
    strict_lossless_evidence: bool = False,
    evidence_candidate: bool | None = None,
) -> ImageCompressionResult:
    if evidence_candidate is None:
        evidence_candidate = result.output_created
    decision = evaluate_delivery_gate(
        result.technical_status,
        result.visual_review_status,
        strict_lossless_evidence=strict_lossless_evidence,
        evidence_candidate=evidence_candidate,
        risk_reasons=result.risk_reasons,
    )
    result.delivery_gate_status = decision.status
    result.delivery_eligible = decision.eligible
    result.delivery_decision_reason = decision.reason
    result.candidate_delivery_role = decision.candidate_role
    return result


def no_processing_result(task: ImageCompressionTask, source: dict[str, Any], started: float) -> ImageCompressionResult:
    result = base_result_for_task(task)
    populate_source(result, source)
    result.technical_status = TechnicalStatus.NO_PROCESSING_NEEDED
    result.visual_review_status = VisualReviewStatus.NOT_REQUIRED
    result.output_created = False
    result.output_path = source["path"]
    result.output_sha256 = source["sha256"]
    result.output_format = source["format"]
    result.output_dimensions = dict(source["dimensions"])
    result.output_size_bytes = source["size_bytes"]
    result.size_reduction_bytes = 0
    result.size_reduction_ratio = 0.0
    result.dimension_scale_ratio = 1.0
    result.lossy = False
    result.reencoded = False
    result.resized = False
    result.metadata_preserved = True
    result.alpha_preserved = True
    result.alpha_details["alpha_present"] = source["alpha_present"]
    result.processing_seconds = max(0.0, time.perf_counter() - started)
    result.slowest_stage = "limit_check"
    result.validation_status = "PASS"
    return apply_delivery_gate(result)


def runtime_failure_result(
    task: ImageCompressionTask,
    source: dict[str, Any] | None,
    error: CompressionRuntimeError,
    started: float,
) -> ImageCompressionResult:
    result = base_result_for_task(task)
    if source:
        populate_source(result, source)
    result.technical_status = error.technical_status
    result.visual_review_status = VisualReviewStatus.NOT_AVAILABLE
    result.failure_code = error.failure_code
    result.failure_reason = error.reason
    result.output_created = False
    result.processing_seconds = max(0.0, time.perf_counter() - started)
    result.validation_status = "FAIL"
    result.validation_failures = [{"stage": 7, "field": None, "failure_code": error.failure_code, "reason": error.reason}]
    return apply_delivery_gate(result, evidence_candidate=False)
