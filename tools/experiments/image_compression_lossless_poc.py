"""静态 PNG 同格式、像素级真正无损压缩离线 PoC。

该脚本只在 ``tmp/image_compression_poc_v1/<run_id>`` 下生成实验资产，
不接入正式 pipeline、API、UI、SSE 或任务合同。
"""

from __future__ import annotations

import argparse
import binascii
import csv
import hashlib
import json
import os
import shutil
import statistics
import struct
import subprocess
import sys
import time
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageCms, JpegImagePlugin, PngImagePlugin


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"

BUSINESS_PNG_SAMPLES = (
    {
        "sample_id": "png_cn_title",
        "sample_type": "中文大标题商业图",
        "path": "tmp/v046_rc7_upper_inputs_20260708/chengdu_yanhuo.png",
    },
    {
        "sample_id": "png_cn_small_text",
        "sample_type": "极小中文PPT",
        "path": "tmp/v047_stage1_smoke_inputs_20260707_114207/02_cn_small_text_ppt.png",
    },
    {
        "sample_id": "png_fine_line_logo",
        "sample_type": "细线与Logo",
        "path": "tmp/v046_rc7_upper_inputs_20260708/lixiang_l9.png",
    },
    {
        "sample_id": "png_dark_material",
        "sample_type": "深色高光与复杂材质",
        "path": "tmp/v046_rc8a_true_hardcase_inputs_20260709/jewelry_yaoshi_zhiguang.png",
    },
    {
        "sample_id": "png_light_infographic",
        "sample_type": "浅色中文信息图",
        "path": "runtime/v04_inputs/task_20260627_140717_3f184dc8_original_01_办公室久坐舒缓指南.png",
    },
    {
        "sample_id": "png_real_alpha",
        "sample_type": "真实透明Alpha",
        "path": "tmp/v046_rc2_final1080_inputs_20260707_154538/03_product_transparent_alpha.png",
    },
)

TOOL_NAMES = ("oxipng", "optipng", "zopflipng", "pngcrush", "jpegtran")
TOOL_FILENAMES = tuple(f"{name}.exe" for name in TOOL_NAMES)

MANIFEST_FIELDS = (
    "sample_id",
    "sample_type",
    "original_path",
    "file_name",
    "sha256",
    "file_format",
    "magic_format",
    "width",
    "height",
    "color_mode",
    "channel_count",
    "bit_depth",
    "file_size_bytes",
    "icc_present",
    "icc_sha256",
    "exif_orientation",
    "dpi",
    "xmp_present",
    "xmp_sha256",
    "alpha_present",
    "modified_time",
)

RESULT_FIELDS = (
    "sample_id",
    "sample_type",
    "original_file_name",
    "original_path",
    "candidate_path",
    "original_format",
    "output_format",
    "original_dimensions",
    "output_dimensions",
    "original_size_bytes",
    "output_size_bytes",
    "saved_bytes",
    "saved_ratio",
    "elapsed_seconds",
    "pixel_exact",
    "alpha_exact",
    "icc_preserved",
    "exif_orientation_preserved",
    "dpi_preserved",
    "xmp_preserved",
    "color_mode_preserved",
    "channel_count_preserved",
    "bit_depth_preserved",
    "jpeg_quantization_preserved",
    "jpeg_sampling_preserved",
    "critical_metadata_preserved",
    "format_preserved",
    "magic_preserved",
    "dimensions_preserved",
    "complete_decode",
    "original_sha256_preserved",
    "original_sha256",
    "candidate_sha256",
    "tool_name",
    "tool_version",
    "candidate_kept",
    "failure_reason",
    "final_recommendation",
)

PNG_ROBUSTNESS_FIELDS = (
    "sample_id",
    "sample_group",
    "sample_type",
    "original_path",
    "candidate_path",
    "original_size_bytes",
    "candidate_size_bytes",
    "saved_bytes",
    "saved_ratio",
    "elapsed_seconds",
    "technical_correctness_pass",
    "output_smaller",
    "format_preserved",
    "magic_preserved",
    "dimensions_preserved",
    "color_type_preserved",
    "color_mode_preserved",
    "channel_count_preserved",
    "bit_depth_preserved",
    "interlace_preserved",
    "filtered_scanlines_exact",
    "pixel_exact",
    "alpha_exact",
    "icc_preserved",
    "exif_preserved",
    "dpi_phys_preserved",
    "xmp_preserved",
    "plte_preserved",
    "trns_preserved",
    "all_non_idat_preserved",
    "complete_decode",
    "original_sha256_preserved",
    "original_sha256",
    "candidate_sha256",
    "candidate_kept",
    "failure_reason",
    "final_recommendation",
)

BOUNDARY_MANIFEST_FIELDS = (
    "sample_id",
    "sample_type",
    "generated_path",
    "generation_method",
    "expected_properties",
    "target_validations",
    "chunk_types",
    "chunk_records",
    "original_sha256",
    "file_size_bytes",
    "width",
    "height",
    "color_type",
    "color_mode",
    "channel_count",
    "bit_depth",
    "interlace",
    "idat_count",
)

REJECTED_RESULT_FIELDS = (
    "sample_id",
    "sample_type",
    "original_path",
    "original_sha256",
    "original_size_bytes",
    "actual_chunk_types",
    "expected_outcome",
    "actual_outcome",
    "rejection_reason",
    "candidate_exists_after",
    "original_sha256_preserved",
    "technical_correctness_pass",
    "output_smaller",
    "candidate_size_bytes",
    "saved_bytes",
    "saved_ratio",
    "final_recommendation",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline same-format genuinely lossless compression PoC. Never touches formal outputs.",
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        help="Isolated run directory. Default: tmp/image_compression_poc_v1/<timestamp>.",
    )
    parser.add_argument(
        "--png-robustness",
        action="store_true",
        help="Compatibility flag. Static PNG robustness is the only executable mode.",
    )
    return parser.parse_args()


def sha256_bytes(value: bytes | None) -> str:
    return hashlib.sha256(value).hexdigest() if value is not None else ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"byte_length": len(value), "sha256": sha256_bytes(value)}
    if isinstance(value, tuple):
        return [normalize_json_value(item) for item in value]
    if isinstance(value, list):
        return [normalize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): normalize_json_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def normalized_dpi(value: Any) -> list[float] | None:
    if not value:
        return None
    try:
        return [round(float(value[0]), 6), round(float(value[1]), 6)]
    except (TypeError, ValueError, IndexError):
        return None


def magic_format(path: Path) -> str:
    header = path.read_bytes()[:16]
    if header.startswith(PNG_SIGNATURE):
        return "PNG"
    if header.startswith(JPEG_SIGNATURE):
        return "JPEG"
    return "UNKNOWN"


def png_chunks(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    if not raw.startswith(PNG_SIGNATURE):
        raise ValueError("invalid_png_signature")
    chunks: list[dict[str, Any]] = []
    offset = len(PNG_SIGNATURE)
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise ValueError("truncated_png_chunk")
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        end = offset + 12 + length
        if end > len(raw):
            raise ValueError("truncated_png_payload")
        chunk_type = raw[offset + 4 : offset + 8]
        data = raw[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", raw[offset + 8 + length : end])[0]
        actual_crc = binascii.crc32(chunk_type)
        actual_crc = binascii.crc32(data, actual_crc) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise ValueError(f"png_crc_mismatch:{chunk_type.decode('latin-1')}")
        chunks.append(
            {
                "type": chunk_type,
                "data": data,
                "raw": raw[offset:end],
            }
        )
        offset = end
        if chunk_type == b"IEND":
            break
    if offset != len(raw):
        raise ValueError("png_trailing_bytes")
    return chunks


def validate_png_structure(chunks: list[dict[str, Any]], *, allow_apng: bool = False) -> dict[str, Any]:
    if not chunks:
        raise ValueError("png_chunks_missing")
    chunk_types = [item["type"] for item in chunks]
    if chunk_types[0] != b"IHDR" or chunk_types.count(b"IHDR") != 1:
        raise ValueError("png_ihdr_invalid")
    if chunk_types[-1] != b"IEND" or chunk_types.count(b"IEND") != 1:
        raise ValueError("png_iend_invalid")
    if chunks[-1]["data"]:
        raise ValueError("png_iend_payload_invalid")
    apng_types = {b"acTL", b"fcTL", b"fdAT"}
    if not allow_apng and any(item in apng_types for item in chunk_types):
        raise ValueError("unsupported_apng")
    known_critical = {b"IHDR", b"PLTE", b"IDAT", b"IEND"}
    for chunk_type in chunk_types:
        if len(chunk_type) != 4 or not all(65 <= value <= 90 or 97 <= value <= 122 for value in chunk_type):
            raise ValueError("png_chunk_type_invalid")
        if chunk_type[2] & 0x20:
            raise ValueError(f"png_reserved_bit_invalid:{chunk_type.decode('latin-1')}")
        if not chunk_type[0] & 0x20 and chunk_type not in known_critical:
            raise ValueError(f"unknown_critical_chunk:{chunk_type.decode('latin-1')}")
    ihdr = chunks[0]["data"]
    if len(ihdr) != 13:
        raise ValueError("png_ihdr_length_invalid")
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(">IIBBBBB", ihdr)
    if width <= 0 or height <= 0:
        raise ValueError("png_dimensions_invalid")
    valid_depths = {
        0: {1, 2, 4, 8, 16},
        2: {8, 16},
        3: {1, 2, 4, 8},
        4: {8, 16},
        6: {8, 16},
    }
    if color_type not in valid_depths or bit_depth not in valid_depths[color_type]:
        raise ValueError("png_color_type_or_bit_depth_invalid")
    if compression != 0 or filter_method != 0 or interlace not in {0, 1}:
        raise ValueError("png_ihdr_method_invalid")
    idat_indices = [index for index, item in enumerate(chunk_types) if item == b"IDAT"]
    if not idat_indices:
        raise ValueError("png_idat_missing")
    if idat_indices != list(range(idat_indices[0], idat_indices[-1] + 1)):
        raise ValueError("png_idat_not_contiguous")
    plte_indices = [index for index, item in enumerate(chunk_types) if item == b"PLTE"]
    if len(plte_indices) > 1:
        raise ValueError("png_plte_duplicate")
    if plte_indices and plte_indices[0] > idat_indices[0]:
        raise ValueError("png_plte_after_idat")
    if color_type == 3 and not plte_indices:
        raise ValueError("png_palette_missing")
    if color_type in {0, 4} and plte_indices:
        raise ValueError("png_palette_forbidden")
    if plte_indices:
        palette_length = len(chunks[plte_indices[0]]["data"])
        if palette_length < 3 or palette_length > 768 or palette_length % 3:
            raise ValueError("png_palette_length_invalid")
    return {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "compression": compression,
        "filter_method": filter_method,
        "interlace": interlace,
        "idat_indices": idat_indices,
    }


def decompress_png_idat(chunks: list[dict[str, Any]]) -> bytes:
    compressed = b"".join(item["data"] for item in chunks if item["type"] == b"IDAT")
    decompressor = zlib.decompressobj()
    payload = decompressor.decompress(compressed) + decompressor.flush()
    if not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
        raise ValueError("png_idat_zlib_stream_invalid")
    return payload


def validate_filtered_scanlines(payload: bytes, structure: dict[str, Any]) -> None:
    channel_map = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    channels = channel_map[structure["color_type"]]
    passes = ((0, 0, 1, 1),) if structure["interlace"] == 0 else (
        (0, 0, 8, 8),
        (4, 0, 8, 8),
        (0, 4, 4, 8),
        (2, 0, 4, 4),
        (0, 2, 2, 4),
        (1, 0, 2, 2),
        (0, 1, 1, 2),
    )
    offset = 0
    for start_x, start_y, step_x, step_y in passes:
        pass_width = 0 if structure["width"] <= start_x else (structure["width"] - start_x + step_x - 1) // step_x
        pass_height = 0 if structure["height"] <= start_y else (structure["height"] - start_y + step_y - 1) // step_y
        if pass_width == 0 or pass_height == 0:
            continue
        row_bytes = (pass_width * channels * structure["bit_depth"] + 7) // 8
        for _ in range(pass_height):
            if offset >= len(payload) or payload[offset] > 4:
                raise ValueError("png_scanline_filter_invalid")
            offset += 1 + row_bytes
    if offset != len(payload):
        raise ValueError("png_scanline_length_invalid")


def png_layout(path: Path) -> dict[str, Any]:
    chunks = png_chunks(path)
    structure = validate_png_structure(chunks)
    width = structure["width"]
    height = structure["height"]
    bit_depth = structure["bit_depth"]
    color_type = structure["color_type"]
    compression = structure["compression"]
    filter_method = structure["filter_method"]
    interlace = structure["interlace"]
    filtered_scanlines = decompress_png_idat(chunks)
    validate_filtered_scanlines(filtered_scanlines, structure)
    channel_map = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    non_idat = [
        {
            "type": item["type"].decode("latin-1"),
            "sha256": sha256_bytes(item["raw"]),
        }
        for item in chunks
        if item["type"] != b"IDAT"
    ]
    xmp_payloads = [
        item["data"]
        for item in chunks
        if item["type"] in {b"iTXt", b"tEXt", b"zTXt"}
        and (b"XML:com.adobe.xmp" in item["data"] or b"xmp" in item["data"].lower())
    ]
    return {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "channel_count_from_header": channel_map.get(color_type),
        "compression_method": compression,
        "filter_method": filter_method,
        "interlace": interlace,
        "chunk_types": [item["type"].decode("latin-1") for item in chunks],
        "chunk_records": [
            {
                "index": index,
                "type": item["type"].decode("latin-1"),
                "length": len(item["data"]),
                "data_sha256": sha256_bytes(item["data"]),
                "raw_sha256": sha256_bytes(item["raw"]),
            }
            for index, item in enumerate(chunks)
        ],
        "non_idat_chunks": non_idat,
        "idat_count": sum(item["type"] == b"IDAT" for item in chunks),
        "filtered_scanline_bytes": len(filtered_scanlines),
        "filtered_scanline_sha256": sha256_bytes(filtered_scanlines),
        "iccp_chunks": [sha256_bytes(item["data"]) for item in chunks if item["type"] == b"iCCP"],
        "exif_chunks": [sha256_bytes(item["data"]) for item in chunks if item["type"] == b"eXIf"],
        "phys_chunks": [sha256_bytes(item["data"]) for item in chunks if item["type"] == b"pHYs"],
        "plte_chunks": [sha256_bytes(item["data"]) for item in chunks if item["type"] == b"PLTE"],
        "trns_chunks": [sha256_bytes(item["data"]) for item in chunks if item["type"] == b"tRNS"],
        "xmp_raw": b"".join(xmp_payloads),
        "apng": any(item["type"] in {b"acTL", b"fcTL", b"fdAT"} for item in chunks),
    }


def jpeg_segments(path: Path) -> list[tuple[int, bytes]]:
    raw = path.read_bytes()
    if not raw.startswith(b"\xff\xd8"):
        raise ValueError("invalid_jpeg_signature")
    segments: list[tuple[int, bytes]] = []
    offset = 2
    standalone = {0x01, *range(0xD0, 0xD9)}
    while offset < len(raw):
        if raw[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(raw) and raw[offset] == 0xFF:
            offset += 1
        if offset >= len(raw):
            break
        marker = raw[offset]
        offset += 1
        if marker in standalone:
            segments.append((marker, b""))
            if marker == 0xD9:
                break
            continue
        if offset + 2 > len(raw):
            raise ValueError("truncated_jpeg_segment")
        length = struct.unpack(">H", raw[offset : offset + 2])[0]
        if length < 2 or offset + length > len(raw):
            raise ValueError("invalid_jpeg_segment_length")
        payload = raw[offset + 2 : offset + length]
        segments.append((marker, payload))
        offset += length
        if marker == 0xDA:
            break
    return segments


def jpeg_layout(path: Path) -> dict[str, Any]:
    segments = jpeg_segments(path)
    sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    precision = None
    width = None
    height = None
    components = None
    for marker, payload in segments:
        if marker in sof_markers and len(payload) >= 6:
            precision = payload[0]
            height = struct.unpack(">H", payload[1:3])[0]
            width = struct.unpack(">H", payload[3:5])[0]
            components = payload[5]
            break
    metadata_segments = [
        {
            "marker": f"0x{marker:02X}",
            "sha256": sha256_bytes(payload),
            "length": len(payload),
        }
        for marker, payload in segments
        if 0xE0 <= marker <= 0xEF or marker == 0xFE
    ]
    xmp_payloads = [
        payload
        for marker, payload in segments
        if marker == 0xE1 and (b"http://ns.adobe.com/xap/1.0/" in payload or b"xmpmeta" in payload.lower())
    ]
    return {
        "width": width,
        "height": height,
        "bit_depth": precision,
        "channel_count_from_header": components,
        "metadata_segments": metadata_segments,
        "xmp_raw": b"".join(xmp_payloads),
    }


def image_attributes(path: Path) -> dict[str, Any]:
    detected_magic = magic_format(path)
    layout = png_layout(path) if detected_magic == "PNG" else jpeg_layout(path) if detected_magic == "JPEG" else {}
    with Image.open(path) as image:
        image.load()
        file_format = "JPEG" if image.format == "JPG" else str(image.format or "UNKNOWN").upper()
        bands = list(image.getbands())
        info = dict(image.info or {})
        icc = info.get("icc_profile")
        if not isinstance(icc, bytes):
            icc = None
        try:
            exif_data = image.getexif()
        except Exception:
            exif_data = None
        exif_raw = info.get("exif")
        if not isinstance(exif_raw, bytes):
            try:
                exif_raw = exif_data.tobytes() if exif_data is not None and len(exif_data) else b""
            except Exception:
                exif_raw = b""
        try:
            orientation = exif_data.get(274) if exif_data is not None else None
        except Exception:
            orientation = None
        xmp = layout.get("xmp_raw") or info.get("xmp") or info.get("XML:com.adobe.xmp") or b""
        if isinstance(xmp, str):
            xmp = xmp.encode("utf-8")
        if not isinstance(xmp, bytes):
            xmp = b""
        alpha_present = "A" in bands or "transparency" in info
        if "A" in bands:
            alpha_bytes = image.getchannel("A").tobytes()
        elif "transparency" in info:
            alpha_bytes = image.convert("RGBA").getchannel("A").tobytes()
        else:
            alpha_bytes = None
        quantization = normalize_json_value(getattr(image, "quantization", None)) if file_format == "JPEG" else None
        try:
            sampling = JpegImagePlugin.get_sampling(image) if file_format == "JPEG" else None
        except Exception:
            sampling = None
        frame_count = int(getattr(image, "n_frames", 1))
        attributes = {
            "path": str(path.resolve()),
            "file_name": path.name,
            "file_size_bytes": path.stat().st_size,
            "file_format": file_format,
            "magic_format": detected_magic,
            "width": image.width,
            "height": image.height,
            "color_mode": image.mode,
            "bands": bands,
            "channel_count": len(bands),
            "bit_depth": layout.get("bit_depth"),
            "frame_count": frame_count,
            "complete_decode": True,
            "decoded_pixel_sha256": sha256_bytes(image.tobytes()),
            "alpha_present": alpha_present,
            "alpha_sha256": sha256_bytes(alpha_bytes),
            "icc_present": icc is not None,
            "icc_sha256": sha256_bytes(icc),
            "exif_orientation": orientation,
            "exif_present": bool(exif_raw),
            "exif_sha256": sha256_bytes(exif_raw),
            "dpi": normalized_dpi(info.get("dpi")),
            "xmp_present": bool(xmp),
            "xmp_sha256": sha256_bytes(xmp),
            "info_keys": sorted(str(key) for key in info.keys()),
            "quantization": quantization,
            "jpeg_sampling": sampling,
            "modified_time": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(),
            "sha256": sha256_file(path),
            "layout": normalize_json_value(layout),
        }
    with Image.open(path) as verify_image:
        verify_image.verify()
    return attributes


def make_png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = binascii.crc32(chunk_type)
    crc = binascii.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def compress_zlib_stream(raw_scanlines: bytes, strategy: int) -> bytes:
    compressor = zlib.compressobj(
        level=9,
        method=zlib.DEFLATED,
        wbits=15,
        memLevel=9,
        strategy=strategy,
    )
    return compressor.compress(raw_scanlines) + compressor.flush()


def optimize_png_structure(source: Path, candidate: Path) -> dict[str, Any]:
    chunks = png_chunks(source)
    structure = validate_png_structure(chunks)
    idat_indices = structure["idat_indices"]
    original_idat = b"".join(chunks[index]["data"] for index in idat_indices)
    filtered_scanlines = decompress_png_idat(chunks)
    validate_filtered_scanlines(filtered_scanlines, structure)
    strategy_values = {
        "Z_DEFAULT_STRATEGY": zlib.Z_DEFAULT_STRATEGY,
        "Z_FILTERED": zlib.Z_FILTERED,
        "Z_RLE": zlib.Z_RLE,
    }
    compressed_options = {
        name: compress_zlib_stream(filtered_scanlines, strategy)
        for name, strategy in strategy_values.items()
    }
    selected_strategy, selected_idat = min(compressed_options.items(), key=lambda item: len(item[1]))
    rebuilt = bytearray(PNG_SIGNATURE)
    first_idat = idat_indices[0]
    for index, item in enumerate(chunks):
        if index == first_idat:
            rebuilt.extend(make_png_chunk(b"IDAT", selected_idat))
        elif item["type"] != b"IDAT":
            rebuilt.extend(item["raw"])
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(bytes(rebuilt))
    return {
        "strategy": selected_strategy,
        "original_idat_bytes": len(original_idat),
        "candidate_idat_bytes": len(selected_idat),
        "filtered_scanline_bytes": len(filtered_scanlines),
        "all_strategy_sizes": {name: len(value) for name, value in compressed_options.items()},
    }


def safe_remove(path: Path, run_dir: Path) -> None:
    resolved = path.resolve()
    root = run_dir.resolve()
    if root != resolved and root in resolved.parents and resolved.is_file():
        resolved.unlink()


def discover_tools() -> tuple[list[dict[str, Any]], list[str]]:
    search_roots = [
        PROJECT_ROOT,
        Path(os.environ.get("ProgramFiles", "C:/Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")),
        Path(os.environ.get("ProgramData", "C:/ProgramData")) / "chocolatey" / "bin",
        Path.home() / "scoop",
        Path.home() / "AppData" / "Local" / "Programs",
        Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages",
        Path("C:/tools"),
        Path("D:/tools"),
    ]
    found: dict[str, Path] = {}
    for name in TOOL_NAMES:
        located = shutil.which(name)
        if located:
            found[f"{name}:{Path(located).resolve()}"] = Path(located).resolve()
    for root in search_roots:
        if not root.exists() or not root.is_dir():
            continue
        for filename in TOOL_FILENAMES:
            try:
                for path in root.rglob(filename):
                    if any(part.lower() in {".git", "node_modules", ".venv"} for part in path.parts):
                        continue
                    found[f"{path.stem.lower()}:{path.resolve()}"] = path.resolve()
            except (OSError, PermissionError):
                continue
    rows: list[dict[str, Any]] = []
    for path in sorted(found.values(), key=lambda item: str(item).lower()):
        version_output = ""
        help_output = ""
        for flag in ("--version", "-version", "-v"):
            try:
                completed = subprocess.run(
                    [str(path), flag],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=10,
                    check=False,
                )
                combined = (completed.stdout + "\n" + completed.stderr).strip()
                if combined:
                    version_output = combined[:4000]
                    break
            except (OSError, subprocess.SubprocessError):
                continue
        for flag in ("--help", "-help", "-h"):
            try:
                completed = subprocess.run(
                    [str(path), flag],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=10,
                    check=False,
                )
                combined = (completed.stdout + "\n" + completed.stderr).strip()
                if combined:
                    help_output = combined[:12000]
                    break
            except (OSError, subprocess.SubprocessError):
                continue
        lower_help = help_output.lower()
        rows.append(
            {
                "name": path.stem.lower(),
                "path": str(path),
                "version_output": version_output,
                "help_output": help_output,
                "offline": True,
                "jpeg_lossless_flags_confirmed": all(token in lower_help for token in ("optimize", "copy", "outfile"))
                if path.stem.lower() == "jpegtran"
                else None,
            }
        )
    return rows, [str(root) for root in search_roots if root.exists()]


def find_usable_jpegtran(tools: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    for tool in tools:
        if tool["name"] == "jpegtran" and tool.get("jpeg_lossless_flags_confirmed"):
            return tool
    return None


def optimize_jpeg_coefficients(tool: dict[str, Any], source: Path, candidate: Path) -> dict[str, Any]:
    del tool, source, candidate
    raise RuntimeError("jpeg_coefficient_lossless_route_blocked_in_png_poc")


def compare_attributes(original: dict[str, Any], candidate: dict[str, Any], original_hash_after: str) -> dict[str, Any]:
    png_metadata_equal = True
    jpeg_metadata_equal = True
    if original["file_format"] == "PNG":
        png_metadata_equal = original["layout"].get("non_idat_chunks") == candidate["layout"].get("non_idat_chunks")
    if original["file_format"] == "JPEG":
        jpeg_metadata_equal = original["layout"].get("metadata_segments") == candidate["layout"].get("metadata_segments")
    checks = {
        "format_preserved": original["file_format"] == candidate["file_format"],
        "magic_preserved": original["magic_format"] == candidate["magic_format"],
        "dimensions_preserved": (original["width"], original["height"]) == (candidate["width"], candidate["height"]),
        "color_mode_preserved": original["color_mode"] == candidate["color_mode"],
        "channel_count_preserved": original["channel_count"] == candidate["channel_count"],
        "bit_depth_preserved": original["bit_depth"] == candidate["bit_depth"],
        "pixel_exact": original["decoded_pixel_sha256"] == candidate["decoded_pixel_sha256"],
        "alpha_exact": original["alpha_present"] == candidate["alpha_present"]
        and original["alpha_sha256"] == candidate["alpha_sha256"],
        "icc_preserved": original["icc_present"] == candidate["icc_present"]
        and original["icc_sha256"] == candidate["icc_sha256"],
        "exif_orientation_preserved": original["exif_orientation"] == candidate["exif_orientation"],
        "exif_payload_preserved": original["exif_present"] == candidate["exif_present"]
        and original["exif_sha256"] == candidate["exif_sha256"],
        "dpi_preserved": original["dpi"] == candidate["dpi"],
        "xmp_preserved": original["xmp_present"] == candidate["xmp_present"]
        and original["xmp_sha256"] == candidate["xmp_sha256"],
        "critical_metadata_preserved": png_metadata_equal and jpeg_metadata_equal,
        "jpeg_quantization_preserved": original["quantization"] == candidate["quantization"]
        if original["file_format"] == "JPEG"
        else True,
        "jpeg_sampling_preserved": original["jpeg_sampling"] == candidate["jpeg_sampling"]
        if original["file_format"] == "JPEG"
        else True,
        "complete_decode": bool(candidate["complete_decode"]),
        "original_sha256_preserved": original["sha256"] == original_hash_after,
        "output_smaller": candidate["file_size_bytes"] < original["file_size_bytes"],
    }
    checks["all_hard_gates_pass"] = all(checks.values())
    checks["failed_checks"] = [name for name, value in checks.items() if name != "all_hard_gates_pass" and not value]
    return checks


def compare_png_robustness(
    original: dict[str, Any],
    candidate: dict[str, Any],
    original_hash_after: str,
) -> dict[str, Any]:
    original_layout = original["layout"]
    candidate_layout = candidate["layout"]
    checks = {
        "format_preserved": original["file_format"] == candidate["file_format"] == "PNG",
        "magic_preserved": original["magic_format"] == candidate["magic_format"] == "PNG",
        "dimensions_preserved": (original["width"], original["height"])
        == (candidate["width"], candidate["height"]),
        "color_type_preserved": original_layout["color_type"] == candidate_layout["color_type"],
        "color_mode_preserved": original["color_mode"] == candidate["color_mode"],
        "channel_count_preserved": original["channel_count"] == candidate["channel_count"],
        "bit_depth_preserved": original["bit_depth"] == candidate["bit_depth"],
        "interlace_preserved": original_layout["interlace"] == candidate_layout["interlace"],
        "filtered_scanlines_exact": original_layout["filtered_scanline_sha256"]
        == candidate_layout["filtered_scanline_sha256"],
        "pixel_exact": original["decoded_pixel_sha256"] == candidate["decoded_pixel_sha256"],
        "alpha_exact": original["alpha_present"] == candidate["alpha_present"]
        and original["alpha_sha256"] == candidate["alpha_sha256"],
        "icc_preserved": original["icc_present"] == candidate["icc_present"]
        and original["icc_sha256"] == candidate["icc_sha256"]
        and original_layout["iccp_chunks"] == candidate_layout["iccp_chunks"],
        "exif_preserved": original["exif_present"] == candidate["exif_present"]
        and original["exif_sha256"] == candidate["exif_sha256"]
        and original["exif_orientation"] == candidate["exif_orientation"]
        and original_layout["exif_chunks"] == candidate_layout["exif_chunks"],
        "dpi_phys_preserved": original["dpi"] == candidate["dpi"]
        and original_layout["phys_chunks"] == candidate_layout["phys_chunks"],
        "xmp_preserved": original["xmp_present"] == candidate["xmp_present"]
        and original["xmp_sha256"] == candidate["xmp_sha256"],
        "plte_preserved": original_layout["plte_chunks"] == candidate_layout["plte_chunks"],
        "trns_preserved": original_layout["trns_chunks"] == candidate_layout["trns_chunks"],
        "all_non_idat_preserved": original_layout["non_idat_chunks"] == candidate_layout["non_idat_chunks"],
        "complete_decode": bool(candidate["complete_decode"]),
        "original_sha256_preserved": original["sha256"] == original_hash_after,
        "output_smaller": candidate["file_size_bytes"] < original["file_size_bytes"],
    }
    technical_keys = [name for name in checks if name != "output_smaller"]
    checks["technical_correctness_pass"] = all(checks[name] for name in technical_keys)
    checks["all_hard_gates_pass"] = checks["technical_correctness_pass"] and checks["output_smaller"]
    checks["failed_checks"] = [
        name for name, value in checks.items() if name not in {"technical_correctness_pass", "all_hard_gates_pass"} and not value
    ]
    return checks


def write_csv(path: Path, fields: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalize_json_value(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create_visual_compare(original_path: Path, candidate_path: Path, output_path: Path) -> None:
    with Image.open(original_path) as original_image, Image.open(candidate_path) as candidate_image:
        original = original_image.convert("RGBA")
        candidate = candidate_image.convert("RGBA")
        canvas = Image.new("RGBA", (original.width + candidate.width, max(original.height, candidate.height)), (0, 0, 0, 0))
        canvas.paste(original, (0, 0), original)
        canvas.paste(candidate, (original.width, 0), candidate)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, format="PNG", compress_level=6)


def manifest_row(spec: dict[str, str], attributes: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_id": spec["sample_id"],
        "sample_type": spec["sample_type"],
        "original_path": attributes["path"],
        "file_name": attributes["file_name"],
        "sha256": attributes["sha256"],
        "file_format": attributes["file_format"],
        "magic_format": attributes["magic_format"],
        "width": attributes["width"],
        "height": attributes["height"],
        "color_mode": attributes["color_mode"],
        "channel_count": attributes["channel_count"],
        "bit_depth": attributes["bit_depth"],
        "file_size_bytes": attributes["file_size_bytes"],
        "icc_present": attributes["icc_present"],
        "icc_sha256": attributes["icc_sha256"],
        "exif_orientation": attributes["exif_orientation"],
        "dpi": json.dumps(attributes["dpi"], ensure_ascii=False),
        "xmp_present": attributes["xmp_present"],
        "xmp_sha256": attributes["xmp_sha256"],
        "alpha_present": attributes["alpha_present"],
        "modified_time": attributes["modified_time"],
    }


def blocked_result(spec: dict[str, str], original: dict[str, Any], reason: str, tool_name: str) -> dict[str, Any]:
    return {
        "sample_id": spec["sample_id"],
        "sample_type": spec["sample_type"],
        "original_file_name": original["file_name"],
        "original_path": original["path"],
        "candidate_path": "",
        "original_format": original["file_format"],
        "output_format": original["file_format"],
        "original_dimensions": f"{original['width']}x{original['height']}",
        "output_dimensions": "not_run",
        "original_size_bytes": original["file_size_bytes"],
        "output_size_bytes": "not_run",
        "saved_bytes": 0,
        "saved_ratio": 0,
        "elapsed_seconds": 0,
        "pixel_exact": "not_run",
        "alpha_exact": "not_run",
        "icc_preserved": "not_run",
        "exif_orientation_preserved": "not_run",
        "dpi_preserved": "not_run",
        "xmp_preserved": "not_run",
        "color_mode_preserved": "not_run",
        "channel_count_preserved": "not_run",
        "bit_depth_preserved": "not_run",
        "jpeg_quantization_preserved": "not_run",
        "jpeg_sampling_preserved": "not_run",
        "critical_metadata_preserved": "not_run",
        "format_preserved": "not_run",
        "magic_preserved": "not_run",
        "dimensions_preserved": "not_run",
        "complete_decode": "not_run",
        "original_sha256_preserved": sha256_file(Path(original["path"])) == original["sha256"],
        "original_sha256": original["sha256"],
        "candidate_sha256": "",
        "tool_name": tool_name,
        "tool_version": "",
        "candidate_kept": False,
        "failure_reason": reason,
        "final_recommendation": "保持原图",
    }


def result_row(
    spec: dict[str, str],
    original: dict[str, Any],
    candidate: dict[str, Any],
    checks: dict[str, Any],
    elapsed: float,
    tool_name: str,
    tool_version: str,
    kept: bool,
    candidate_path: Path,
) -> dict[str, Any]:
    saved_bytes = original["file_size_bytes"] - candidate["file_size_bytes"]
    failure_reason = ";".join(checks["failed_checks"])
    return {
        "sample_id": spec["sample_id"],
        "sample_type": spec["sample_type"],
        "original_file_name": original["file_name"],
        "original_path": original["path"],
        "candidate_path": str(candidate_path.resolve()) if kept else "",
        "original_format": original["file_format"],
        "output_format": candidate["file_format"],
        "original_dimensions": f"{original['width']}x{original['height']}",
        "output_dimensions": f"{candidate['width']}x{candidate['height']}",
        "original_size_bytes": original["file_size_bytes"],
        "output_size_bytes": candidate["file_size_bytes"],
        "saved_bytes": saved_bytes,
        "saved_ratio": round(saved_bytes / max(original["file_size_bytes"], 1), 8),
        "elapsed_seconds": round(elapsed, 6),
        "pixel_exact": checks["pixel_exact"],
        "alpha_exact": checks["alpha_exact"],
        "icc_preserved": checks["icc_preserved"],
        "exif_orientation_preserved": checks["exif_orientation_preserved"],
        "dpi_preserved": checks["dpi_preserved"],
        "xmp_preserved": checks["xmp_preserved"],
        "color_mode_preserved": checks["color_mode_preserved"],
        "channel_count_preserved": checks["channel_count_preserved"],
        "bit_depth_preserved": checks["bit_depth_preserved"],
        "jpeg_quantization_preserved": checks["jpeg_quantization_preserved"],
        "jpeg_sampling_preserved": checks["jpeg_sampling_preserved"],
        "critical_metadata_preserved": checks["critical_metadata_preserved"],
        "format_preserved": checks["format_preserved"],
        "magic_preserved": checks["magic_preserved"],
        "dimensions_preserved": checks["dimensions_preserved"],
        "complete_decode": checks["complete_decode"],
        "original_sha256_preserved": checks["original_sha256_preserved"],
        "original_sha256": original["sha256"],
        "candidate_sha256": candidate["sha256"],
        "tool_name": tool_name,
        "tool_version": tool_version,
        "candidate_kept": kept,
        "failure_reason": failure_reason,
        "final_recommendation": "建议采用" if kept else "保持原图",
    }


def write_tool_report(
    path: Path,
    tools: list[dict[str, Any]],
    search_roots: list[str],
    jpegtran: dict[str, Any] | None,
) -> None:
    lines = [
        "# Local Genuinely Lossless Tool Capability",
        "",
        f"- Generated: {datetime.now().astimezone().isoformat()}",
        f"- Python: {sys.version.split()[0]}",
        f"- zlib compile/runtime: {zlib.ZLIB_VERSION} / {zlib.ZLIB_RUNTIME_VERSION}",
        f"- Pillow validation runtime: {Image.__version__ if hasattr(Image, '__version__') else 'unknown'}",
        "- Network required: no",
        "- Installed or upgraded by this PoC: no",
        "",
        "## Search Scope",
        "",
        "- PATH via shutil.which",
        *[f"- `{root}`" for root in search_roots],
        "",
        "## External Tools",
        "",
    ]
    if not tools:
        lines.append("- No oxipng, optipng, zopflipng, pngcrush, or jpegtran executable was found.")
    for tool in tools:
        lines.extend(
            [
                f"### {tool['name']}",
                "",
                f"- Path: `{tool['path']}`",
                f"- Offline: {tool['offline']}",
                f"- JPEG lossless flags confirmed: {tool.get('jpeg_lossless_flags_confirmed')}",
                "",
                "Version output:",
                "",
                "```text",
                tool.get("version_output") or "No version output.",
                "```",
                "",
                "Help output:",
                "",
                "```text",
                tool.get("help_output") or "No help output.",
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## PNG Route",
            "",
            "- Route: Python zlib structural recompression.",
            "- Parameters: level=9, wbits=15, memLevel=9; tries Z_DEFAULT_STRATEGY, Z_FILTERED, and Z_RLE.",
            "- Safety property: decompresses and recompresses the existing filtered IDAT stream only.",
            "- All non-IDAT PNG chunks are preserved byte-for-byte and verified after output.",
            "- It does not change filtering, palette, color type, bit depth, pixels, alpha, or metadata.",
            "- Offline: yes.",
            "",
            "## JPEG Route",
            "",
            f"- Status: {'available' if jpegtran else 'BLOCKED'}.",
            f"- Tool: `{jpegtran['path']}`" if jpegtran else "- Reason: no jpegtran with locally verified -copy, -optimize, and -outfile help parameters was found.",
            "- No Pillow/OpenCV JPEG save, quality parameter, or format conversion is used as fallback.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_report(path: Path, results: list[dict[str, Any]], run_dir: Path, jpeg_available: bool) -> None:
    png_rows = [row for row in results if row["original_format"] == "PNG"]
    jpeg_rows = [row for row in results if row["original_format"] == "JPEG"]
    png_adopted = sum(row["final_recommendation"] == "建议采用" for row in png_rows)
    jpeg_adopted = sum(row["final_recommendation"] == "建议采用" for row in jpeg_rows)
    hard_failures = [
        row
        for row in results
        if row["failure_reason"]
        and row["failure_reason"] not in {"output_smaller", "jpeg_coefficient_tool_unavailable"}
        and "jpeg_coefficient_tool_unavailable" not in row["failure_reason"]
    ]
    if hard_failures:
        overall = "FAIL"
    elif png_adopted > 0 and not jpeg_available:
        overall = "PARTIAL"
    elif png_adopted > 0 and jpeg_adopted > 0:
        overall = "PASS"
    else:
        overall = "BLOCKED"
    lines = [
        "# Same-format Genuinely Lossless Compression PoC",
        "",
        f"- Run directory: `{run_dir}`",
        f"- Generated: {datetime.now().astimezone().isoformat()}",
        "- Visual-lossy/JPG95/WebP candidates: not run",
        "- Formal pipeline integration: none",
        "",
        "## Results",
        "",
        "| Sample | Type | Format | Original bytes | Candidate bytes | Saved bytes | Saved ratio | Pixels | Alpha | Metadata | Recommendation | Failure |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |",
    ]
    for row in results:
        output_size = row["output_size_bytes"]
        ratio = row["saved_ratio"]
        ratio_text = f"{float(ratio) * 100:.4f}%" if isinstance(ratio, (int, float)) else str(ratio)
        lines.append(
            f"| {row['original_file_name']} | {row['sample_type']} | {row['original_format']} | "
            f"{row['original_size_bytes']} | {output_size} | {row['saved_bytes']} | {ratio_text} | "
            f"{row['pixel_exact']} | {row['alpha_exact']} | {row['critical_metadata_preserved']} | "
            f"{row['final_recommendation']} | {row['failure_reason'] or '-'} |"
        )
    lines.extend(
        [
            "",
            "## Route Summary",
            "",
            f"- PNG adopted: {png_adopted}/{len(png_rows)} ({png_adopted / max(len(png_rows), 1) * 100:.2f}%).",
            f"- JPEG adopted: {jpeg_adopted}/{len(jpeg_rows)} ({jpeg_adopted / max(len(jpeg_rows), 1) * 100:.2f}%).",
            f"- JPEG coefficient route available: {jpeg_available}.",
            f"- Hard-gate safety failures: {len(hard_failures)}.",
            "",
            "## Final Conclusion",
            "",
            f"**{overall}**",
            "",
            "A candidate is kept only when every hard gate passes and the file is smaller. Visual comparison files are audit aids only.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def deterministic_rgb_image(size: tuple[int, int] = (96, 64)) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size)
    image.putdata(
        [
            (
                (x * 17 + y * 3) % 256,
                (x * 5 + y * 19) % 256,
                ((x // 8) * 29 + (y // 8) * 43) % 256,
            )
            for y in range(height)
            for x in range(width)
        ]
    )
    return image


def deterministic_palette_image(size: tuple[int, int] = (96, 64)) -> Image.Image:
    width, height = size
    image = Image.new("P", size)
    palette: list[int] = []
    for index in range(256):
        palette.extend(((index * 37) % 256, (index * 73) % 256, (index * 109) % 256))
    image.putpalette(palette)
    image.putdata([((x // 6) + (y // 4) * 5) % 32 for y in range(height) for x in range(width)])
    return image


def write_raw_png(
    path: Path,
    *,
    width: int,
    height: int,
    bit_depth: int,
    color_type: int,
    interlace: int,
    filtered_scanlines: bytes,
    compression: str = "stored",
    idat_parts: int = 1,
    extra_chunks: Iterable[tuple[bytes, bytes]] = (),
) -> None:
    if compression == "stored":
        compressed = zlib.compress(filtered_scanlines, level=0)
    elif compression == "best":
        options = [
            compress_zlib_stream(filtered_scanlines, zlib.Z_DEFAULT_STRATEGY),
            compress_zlib_stream(filtered_scanlines, zlib.Z_FILTERED),
            compress_zlib_stream(filtered_scanlines, zlib.Z_RLE),
        ]
        compressed = min(options, key=len)
    else:
        raise ValueError(f"unsupported_controlled_compression:{compression}")
    idat_parts = max(1, min(idat_parts, len(compressed)))
    split_points = [round(len(compressed) * index / idat_parts) for index in range(idat_parts + 1)]
    payload = bytearray(PNG_SIGNATURE)
    payload.extend(
        make_png_chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, interlace),
        )
    )
    for chunk_type, data in extra_chunks:
        payload.extend(make_png_chunk(chunk_type, data))
    for index in range(idat_parts):
        payload.extend(make_png_chunk(b"IDAT", compressed[split_points[index] : split_points[index + 1]]))
    payload.extend(make_png_chunk(b"IEND", b""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(payload))


def generate_controlled_boundary_samples(sample_dir: Path) -> list[dict[str, Any]]:
    sample_dir.mkdir(parents=True, exist_ok=True)
    specs: list[dict[str, Any]] = []

    def add(
        sample_id: str,
        sample_type: str,
        path: Path,
        generation_method: str,
        expected: dict[str, Any],
        targets: list[str],
    ) -> None:
        specs.append(
            {
                "sample_id": sample_id,
                "sample_type": sample_type,
                "path": path,
                "generation_method": generation_method,
                "expected": expected,
                "target_validations": targets,
            }
        )

    rgb = deterministic_rgb_image()
    icc_path = sample_dir / "boundary_icc.png"
    icc_bytes = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    rgb.save(icc_path, format="PNG", compress_level=0, icc_profile=icc_bytes)
    add(
        "boundary_icc",
        "实际ICC配置",
        icc_path,
        "Pillow RGB deterministic pixels; embedded generated sRGB ICC; PNG compress_level=0",
        {"chunk_present": "iCCP", "icc_present": True},
        ["iCCP raw payload", "decoded ICC SHA-256"],
    )

    dpi_path = sample_dir / "boundary_dpi_phys.png"
    rgb.save(dpi_path, format="PNG", compress_level=0, dpi=(144.0, 144.0))
    add(
        "boundary_dpi_phys",
        "实际DPI/pHYs",
        dpi_path,
        "Pillow RGB deterministic pixels; dpi=(144,144); PNG compress_level=0",
        {"chunk_present": "pHYs", "dpi_present": True},
        ["pHYs raw payload", "decoded DPI"],
    )

    exif_path = sample_dir / "boundary_exif.png"
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "HDDE deterministic PoC"
    rgb.save(exif_path, format="PNG", compress_level=0, exif=exif)
    add(
        "boundary_exif",
        "实际EXIF/eXIf",
        exif_path,
        "Pillow RGB deterministic pixels; EXIF Orientation=6 and Artist; PNG compress_level=0",
        {"chunk_present": "eXIf", "exif_present": True, "exif_orientation": 6},
        ["eXIf raw payload", "decoded EXIF SHA-256", "Orientation"],
    )

    xmp_path = sample_dir / "boundary_xmp.png"
    xmp_payload = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description xmlns:hdde="https://example.invalid/hdde/" hdde:Case="PNG-Robustness"/>'
        "</rdf:RDF></x:xmpmeta>"
    )
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_itxt("XML:com.adobe.xmp", xmp_payload)
    rgb.save(xmp_path, format="PNG", compress_level=0, pnginfo=pnginfo)
    add(
        "boundary_xmp",
        "实际XMP文本块",
        xmp_path,
        "Pillow RGB deterministic pixels; fixed XMP iTXt payload; PNG compress_level=0",
        {"chunk_present": "iTXt", "xmp_present": True},
        ["XMP iTXt payload", "XMP SHA-256"],
    )

    palette_path = sample_dir / "boundary_palette_plte.png"
    palette = deterministic_palette_image()
    palette.save(palette_path, format="PNG", compress_level=0, bits=8)
    add(
        "boundary_palette_plte",
        "索引色PLTE",
        palette_path,
        "Pillow deterministic P-mode palette; 8-bit indices; PNG compress_level=0",
        {"chunk_present": "PLTE", "color_type": 3, "bit_depth": 8, "color_mode": "P"},
        ["PLTE payload", "palette indices", "color type"],
    )

    trns_path = sample_dir / "boundary_trns.png"
    transparent_palette = deterministic_palette_image()
    transparent_palette.save(
        trns_path,
        format="PNG",
        compress_level=0,
        bits=8,
        transparency=bytes([0, 64, 128, 255] + [255] * 28),
    )
    add(
        "boundary_trns",
        "tRNS透明块",
        trns_path,
        "Pillow deterministic P-mode palette; fixed 32-entry transparency bytes; PNG compress_level=0",
        {"chunk_present": "tRNS", "color_type": 3, "alpha_present": True},
        ["tRNS payload", "decoded alpha bytes", "PLTE payload"],
    )

    grayscale_path = sample_dir / "boundary_grayscale.png"
    grayscale = Image.new("L", (96, 64))
    grayscale.putdata([(x * 11 + y * 7) % 256 for y in range(64) for x in range(96)])
    grayscale.save(grayscale_path, format="PNG", compress_level=0)
    add(
        "boundary_grayscale",
        "灰度PNG",
        grayscale_path,
        "Pillow deterministic L-mode pixels; PNG compress_level=0",
        {"color_type": 0, "bit_depth": 8, "color_mode": "L"},
        ["grayscale color type", "decoded grayscale bytes"],
    )

    sixteen_path = sample_dir / "boundary_16bit.png"
    sixteen_rows = bytearray()
    for y in range(64):
        sixteen_rows.append(0)
        for x in range(96):
            sixteen_rows.extend(struct.pack(">H", (x * 977 + y * 1231) % 65536))
    write_raw_png(
        sixteen_path,
        width=96,
        height=64,
        bit_depth=16,
        color_type=0,
        interlace=0,
        filtered_scanlines=bytes(sixteen_rows),
    )
    add(
        "boundary_16bit",
        "16位灰度PNG",
        sixteen_path,
        "Manual deterministic 16-bit big-endian grayscale scanlines; filter=0; zlib stored blocks",
        {"color_type": 0, "bit_depth": 16},
        ["IHDR bit depth", "16-bit decoded samples"],
    )

    adam7_path = sample_dir / "boundary_adam7.png"
    adam7_rows = bytearray()
    adam7_passes = (
        (0, 0, 8, 8),
        (4, 0, 8, 8),
        (0, 4, 4, 8),
        (2, 0, 4, 4),
        (0, 2, 2, 4),
        (1, 0, 2, 2),
        (0, 1, 1, 2),
    )
    for start_x, start_y, step_x, step_y in adam7_passes:
        for y in range(start_y, 64, step_y):
            adam7_rows.append(0)
            adam7_rows.extend((x * 13 + y * 17) % 256 for x in range(start_x, 64, step_x))
    write_raw_png(
        adam7_path,
        width=64,
        height=64,
        bit_depth=8,
        color_type=0,
        interlace=1,
        filtered_scanlines=bytes(adam7_rows),
    )
    add(
        "boundary_adam7",
        "Adam7隔行PNG",
        adam7_path,
        "Manual deterministic Adam7 seven-pass grayscale scanlines; filter=0; zlib stored blocks",
        {"color_type": 0, "bit_depth": 8, "interlace": 1},
        ["IHDR interlace=1", "seven-pass filtered bytes", "decoded pixels"],
    )

    multi_idat_path = sample_dir / "boundary_multi_idat.png"
    multi_rows = bytearray()
    for y in range(64):
        multi_rows.append(0)
        for x in range(96):
            multi_rows.extend(((x * 17 + y) % 256, (x + y * 19) % 256, (x * 3 + y * 5) % 256))
    write_raw_png(
        multi_idat_path,
        width=96,
        height=64,
        bit_depth=8,
        color_type=2,
        interlace=0,
        filtered_scanlines=bytes(multi_rows),
        idat_parts=4,
    )
    add(
        "boundary_multi_idat",
        "多IDAT静态PNG",
        multi_idat_path,
        "Manual deterministic RGB scanlines; filter=0; zlib stored blocks split across four contiguous IDAT chunks",
        {"color_type": 2, "bit_depth": 8, "idat_min": 2},
        ["contiguous multi-IDAT input", "joined zlib stream", "decoded pixels"],
    )
    return specs


def assert_boundary_expectations(spec: dict[str, Any], attributes: dict[str, Any]) -> None:
    expected = spec["expected"]
    layout = attributes["layout"]
    chunk_types = layout["chunk_types"]
    checks = {
        "chunk_present": expected.get("chunk_present") is None or expected["chunk_present"] in chunk_types,
        "color_type": expected.get("color_type") is None or layout["color_type"] == expected["color_type"],
        "bit_depth": expected.get("bit_depth") is None or attributes["bit_depth"] == expected["bit_depth"],
        "interlace": expected.get("interlace") is None or layout["interlace"] == expected["interlace"],
        "idat_min": expected.get("idat_min") is None or layout["idat_count"] >= expected["idat_min"],
        "color_mode": expected.get("color_mode") is None or attributes["color_mode"] == expected["color_mode"],
        "icc_present": expected.get("icc_present") is None or attributes["icc_present"] == expected["icc_present"],
        "dpi_present": expected.get("dpi_present") is None or (attributes["dpi"] is not None) == expected["dpi_present"],
        "exif_present": expected.get("exif_present") is None or attributes["exif_present"] == expected["exif_present"],
        "exif_orientation": expected.get("exif_orientation") is None
        or attributes["exif_orientation"] == expected["exif_orientation"],
        "xmp_present": expected.get("xmp_present") is None or attributes["xmp_present"] == expected["xmp_present"],
        "alpha_present": expected.get("alpha_present") is None or attributes["alpha_present"] == expected["alpha_present"],
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"boundary_sample_expectation_failed:{spec['sample_id']}:{','.join(failed)}")


def generate_rejection_and_fallback_samples(sample_dir: Path) -> list[dict[str, Any]]:
    sample_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    apng_path = sample_dir / "reject_apng.png"
    frame_one = Image.new("RGBA", (32, 32), (255, 0, 0, 255))
    frame_two = Image.new("RGBA", (32, 32), (0, 0, 255, 128))
    frame_one.save(
        apng_path,
        format="PNG",
        save_all=True,
        append_images=[frame_two],
        duration=[100, 100],
        loop=0,
        compress_level=0,
    )
    rows.append(
        {
            "sample_id": "reject_apng",
            "sample_type": "APNG结构拒绝",
            "path": apng_path,
            "expected_outcome": "不支持处理",
            "expected_reason": "unsupported_apng",
        }
    )

    base_rows = b"".join(b"\x00" + bytes((x * 23 + y * 7) % 256 for x in range(32)) for y in range(32))
    unknown_path = sample_dir / "reject_unknown_critical.png"
    write_raw_png(
        unknown_path,
        width=32,
        height=32,
        bit_depth=8,
        color_type=0,
        interlace=0,
        filtered_scanlines=base_rows,
        extra_chunks=((b"ABCD", b"HDDE-unknown-critical"),),
    )
    rows.append(
        {
            "sample_id": "reject_unknown_critical",
            "sample_type": "未知关键块拒绝",
            "path": unknown_path,
            "expected_outcome": "不支持处理",
            "expected_reason": "unknown_critical_chunk:ABCD",
        }
    )

    crc_path = sample_dir / "reject_crc_error.png"
    write_raw_png(
        crc_path,
        width=32,
        height=32,
        bit_depth=8,
        color_type=0,
        interlace=0,
        filtered_scanlines=base_rows,
    )
    corrupted = bytearray(crc_path.read_bytes())
    idat_offset = corrupted.index(b"IDAT") - 4
    idat_length = struct.unpack(">I", corrupted[idat_offset : idat_offset + 4])[0]
    crc_last_byte = idat_offset + 8 + idat_length + 3
    corrupted[crc_last_byte] ^= 0x01
    crc_path.write_bytes(bytes(corrupted))
    rows.append(
        {
            "sample_id": "reject_crc_error",
            "sample_type": "CRC损坏拒绝",
            "path": crc_path,
            "expected_outcome": "不支持处理",
            "expected_reason": "png_crc_mismatch:IDAT",
        }
    )

    no_gain_path = sample_dir / "fallback_optimized_no_gain.png"
    write_raw_png(
        no_gain_path,
        width=1,
        height=1,
        bit_depth=8,
        color_type=0,
        interlace=0,
        filtered_scanlines=b"\x00\x80",
        compression="best",
    )
    rows.append(
        {
            "sample_id": "fallback_optimized_no_gain",
            "sample_type": "已高度优化无收益静态PNG",
            "path": no_gain_path,
            "expected_outcome": "保持原图",
            "expected_reason": "output_smaller",
        }
    )
    return rows


def lenient_png_chunk_types(path: Path) -> list[str]:
    raw = path.read_bytes()
    if not raw.startswith(PNG_SIGNATURE):
        return []
    types: list[str] = []
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(raw):
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        end = offset + 12 + length
        if end > len(raw):
            break
        chunk_type = raw[offset + 4 : offset + 8]
        types.append(chunk_type.decode("latin-1"))
        offset = end
        if chunk_type == b"IEND":
            break
    return types


def build_png_result_row(
    spec: dict[str, Any],
    group: str,
    original: dict[str, Any],
    candidate: dict[str, Any],
    checks: dict[str, Any],
    elapsed: float,
    kept: bool,
    candidate_path: Path,
) -> dict[str, Any]:
    saved_bytes = original["file_size_bytes"] - candidate["file_size_bytes"]
    row = {
        "sample_id": spec["sample_id"],
        "sample_group": group,
        "sample_type": spec["sample_type"],
        "original_path": original["path"],
        "candidate_path": str(candidate_path.resolve()) if kept else "",
        "original_size_bytes": original["file_size_bytes"],
        "candidate_size_bytes": candidate["file_size_bytes"],
        "saved_bytes": saved_bytes,
        "saved_ratio": round(saved_bytes / max(original["file_size_bytes"], 1), 8),
        "elapsed_seconds": round(elapsed, 6),
        **{field: checks[field] for field in PNG_ROBUSTNESS_FIELDS if field in checks},
        "original_sha256": original["sha256"],
        "candidate_sha256": candidate["sha256"],
        "candidate_kept": kept,
        "failure_reason": ";".join(checks["failed_checks"]),
        "final_recommendation": "建议采用" if kept else "保持原图",
    }
    return row


def process_png_samples(
    specs: Iterable[dict[str, Any]],
    group: str,
    candidate_dir: Path,
    run_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    evidence = {"chunks": [], "metadata": [], "pixels_alpha": []}
    sha_rows: list[dict[str, Any]] = []
    for spec in specs:
        source = Path(spec["path"]).resolve()
        original = image_attributes(source)
        original_hash = original["sha256"]
        candidate_path = candidate_dir / f"{spec['sample_id']}__lossless.png"
        started = time.perf_counter()
        operation = optimize_png_structure(source, candidate_path)
        candidate = image_attributes(candidate_path)
        checks = compare_png_robustness(original, candidate, sha256_file(source))
        elapsed = time.perf_counter() - started
        kept = bool(checks["all_hard_gates_pass"])
        row = build_png_result_row(spec, group, original, candidate, checks, elapsed, kept, candidate_path)
        evidence["chunks"].append(
            {
                "sample_id": spec["sample_id"],
                "original_chunk_records": original["layout"]["chunk_records"],
                "candidate_chunk_records": candidate["layout"]["chunk_records"],
                "original_non_idat": original["layout"]["non_idat_chunks"],
                "candidate_non_idat": candidate["layout"]["non_idat_chunks"],
                "filtered_scanlines_exact": checks["filtered_scanlines_exact"],
                "all_non_idat_preserved": checks["all_non_idat_preserved"],
                "operation": operation,
            }
        )
        evidence["metadata"].append(
            {
                "sample_id": spec["sample_id"],
                "icc": {"original": original["icc_sha256"], "candidate": candidate["icc_sha256"], "preserved": checks["icc_preserved"]},
                "exif": {"original": original["exif_sha256"], "candidate": candidate["exif_sha256"], "preserved": checks["exif_preserved"]},
                "orientation": {"original": original["exif_orientation"], "candidate": candidate["exif_orientation"]},
                "dpi": {"original": original["dpi"], "candidate": candidate["dpi"], "preserved": checks["dpi_phys_preserved"]},
                "xmp": {"original": original["xmp_sha256"], "candidate": candidate["xmp_sha256"], "preserved": checks["xmp_preserved"]},
                "plte_preserved": checks["plte_preserved"],
                "trns_preserved": checks["trns_preserved"],
            }
        )
        evidence["pixels_alpha"].append(
            {
                "sample_id": spec["sample_id"],
                "original_pixel_sha256": original["decoded_pixel_sha256"],
                "candidate_pixel_sha256": candidate["decoded_pixel_sha256"],
                "pixel_exact": checks["pixel_exact"],
                "original_alpha_sha256": original["alpha_sha256"],
                "candidate_alpha_sha256": candidate["alpha_sha256"],
                "alpha_exact": checks["alpha_exact"],
            }
        )
        sha_rows.extend(
            [
                {"sample_id": spec["sample_id"], "role": "original", "path": str(source), "sha256": original_hash},
                {"sample_id": spec["sample_id"], "role": "candidate_attempt", "path": str(candidate_path), "sha256": candidate["sha256"]},
            ]
        )
        if not kept:
            safe_remove(candidate_path, run_dir)
        if sha256_file(source) != original_hash:
            raise RuntimeError(f"original_sample_changed:{spec['sample_id']}")
        results.append(row)
    return results, evidence, sha_rows


def png_group_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ratios = [float(row["saved_ratio"]) for row in rows]
    kept = [row for row in rows if row["candidate_kept"]]
    return {
        "sample_count": len(rows),
        "technical_pass_count": sum(bool(row["technical_correctness_pass"]) for row in rows),
        "technical_pass_rate": round(sum(bool(row["technical_correctness_pass"]) for row in rows) / max(len(rows), 1), 6),
        "smaller_count": len(kept),
        "keep_original_count": len(rows) - len(kept),
        "keep_original_reasons": [row["failure_reason"] for row in rows if not row["candidate_kept"]],
        "average_saved_ratio": round(statistics.mean(ratios), 8) if ratios else 0,
        "median_saved_ratio": round(statistics.median(ratios), 8) if ratios else 0,
        "minimum_saved_ratio": round(min(ratios), 8) if ratios else 0,
        "maximum_saved_ratio": round(max(ratios), 8) if ratios else 0,
    }


def process_rejection_and_fallback_samples(
    specs: list[dict[str, Any]],
    candidate_dir: Path,
    run_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    result_rows: list[dict[str, Any]] = []
    fallback_evidence = {"chunks": [], "metadata": [], "pixels_alpha": []}
    sha_rows: list[dict[str, Any]] = []
    for spec in specs:
        source = Path(spec["path"]).resolve()
        original_sha = sha256_file(source)
        original_size = source.stat().st_size
        chunk_types = lenient_png_chunk_types(source)
        candidate_path = candidate_dir / f"{spec['sample_id']}__lossless.png"
        if spec["expected_outcome"] == "保持原图":
            fallback_rows, evidence, fallback_sha = process_png_samples(
                [spec],
                "no_gain_fallback",
                candidate_dir,
                run_dir,
            )
            fallback = fallback_rows[0]
            for key in fallback_evidence:
                fallback_evidence[key].extend(evidence[key])
            sha_rows.extend(fallback_sha)
            result_rows.append(
                {
                    "sample_id": spec["sample_id"],
                    "sample_type": spec["sample_type"],
                    "original_path": str(source),
                    "original_sha256": original_sha,
                    "original_size_bytes": original_size,
                    "actual_chunk_types": json.dumps(chunk_types, ensure_ascii=False),
                    "expected_outcome": spec["expected_outcome"],
                    "actual_outcome": fallback["final_recommendation"],
                    "rejection_reason": fallback["failure_reason"],
                    "candidate_exists_after": candidate_path.exists(),
                    "original_sha256_preserved": sha256_file(source) == original_sha,
                    "technical_correctness_pass": fallback["technical_correctness_pass"],
                    "output_smaller": fallback["output_smaller"],
                    "candidate_size_bytes": fallback["candidate_size_bytes"],
                    "saved_bytes": fallback["saved_bytes"],
                    "saved_ratio": fallback["saved_ratio"],
                    "final_recommendation": fallback["final_recommendation"],
                }
            )
            continue
        actual_outcome = "错误处理"
        rejection_reason = "candidate_was_created"
        try:
            optimize_png_structure(source, candidate_path)
        except Exception as exc:
            rejection_reason = str(exc)
            if spec["expected_reason"] in rejection_reason:
                actual_outcome = "不支持处理"
        finally:
            safe_remove(candidate_path, run_dir)
        sha_rows.append(
            {"sample_id": spec["sample_id"], "role": "rejected_original", "path": str(source), "sha256": original_sha}
        )
        result_rows.append(
            {
                "sample_id": spec["sample_id"],
                "sample_type": spec["sample_type"],
                "original_path": str(source),
                "original_sha256": original_sha,
                "original_size_bytes": original_size,
                "actual_chunk_types": json.dumps(chunk_types, ensure_ascii=False),
                "expected_outcome": spec["expected_outcome"],
                "actual_outcome": actual_outcome,
                "rejection_reason": rejection_reason,
                "candidate_exists_after": candidate_path.exists(),
                "original_sha256_preserved": sha256_file(source) == original_sha,
                "technical_correctness_pass": "not_applicable",
                "output_smaller": "not_applicable",
                "candidate_size_bytes": "not_applicable",
                "saved_bytes": 0,
                "saved_ratio": 0,
                "final_recommendation": actual_outcome,
            }
        )
    return result_rows, fallback_evidence, sha_rows


def independent_png_records(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    if raw[:8] != PNG_SIGNATURE:
        raise ValueError("secondary_invalid_signature")
    records: list[dict[str, Any]] = []
    offset = 8
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise ValueError("secondary_truncated_chunk")
        length = int.from_bytes(raw[offset : offset + 4], "big")
        end = offset + length + 12
        if end > len(raw):
            raise ValueError("secondary_truncated_payload")
        chunk_type = raw[offset + 4 : offset + 8]
        data = raw[offset + 8 : offset + 8 + length]
        expected_crc = int.from_bytes(raw[offset + 8 + length : end], "big")
        actual_crc = binascii.crc32(data, binascii.crc32(chunk_type)) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise ValueError(f"secondary_crc_mismatch:{chunk_type.decode('latin-1')}")
        records.append({"type": chunk_type, "data": data, "raw": raw[offset:end]})
        offset = end
        if chunk_type == b"IEND":
            break
    if offset != len(raw):
        raise ValueError("secondary_trailing_bytes")
    return records


def independent_alpha_bytes(image: Image.Image) -> bytes | None:
    if "A" in image.getbands():
        return image.getchannel("A").tobytes()
    if "transparency" in image.info:
        return image.convert("RGBA").getchannel("A").tobytes()
    return None


def run_independent_secondary_verification(
    run_dir: Path,
    static_rows: list[dict[str, Any]],
    rejected_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for row in static_rows:
        sample_checks: dict[str, Any] = {"sample_id": row["sample_id"]}
        try:
            if not row["candidate_kept"]:
                raise ValueError("secondary_candidate_not_kept")
            original_path = Path(row["original_path"])
            candidate_path = Path(row["candidate_path"])
            original_records = independent_png_records(original_path)
            candidate_records = independent_png_records(candidate_path)
            original_non_idat = [item["raw"] for item in original_records if item["type"] != b"IDAT"]
            candidate_non_idat = [item["raw"] for item in candidate_records if item["type"] != b"IDAT"]
            original_filtered = zlib.decompress(b"".join(item["data"] for item in original_records if item["type"] == b"IDAT"))
            candidate_filtered = zlib.decompress(b"".join(item["data"] for item in candidate_records if item["type"] == b"IDAT"))
            with Image.open(original_path) as original_image, Image.open(candidate_path) as candidate_image:
                original_image.load()
                candidate_image.load()
                sample_checks.update(
                    {
                        "format_exact": original_image.format == candidate_image.format == "PNG",
                        "dimensions_exact": original_image.size == candidate_image.size,
                        "mode_exact": original_image.mode == candidate_image.mode,
                        "pixels_exact": original_image.tobytes() == candidate_image.tobytes(),
                        "alpha_exact": independent_alpha_bytes(original_image) == independent_alpha_bytes(candidate_image),
                    }
                )
            sample_checks.update(
                {
                    "crc_and_structure_valid": True,
                    "filtered_scanlines_exact": original_filtered == candidate_filtered,
                    "all_non_idat_exact": original_non_idat == candidate_non_idat,
                    "metadata_chunks_exact": all(
                        [item["raw"] for item in original_records if item["type"] == chunk_type]
                        == [item["raw"] for item in candidate_records if item["type"] == chunk_type]
                        for chunk_type in (b"iCCP", b"eXIf", b"pHYs", b"iTXt", b"tEXt", b"zTXt", b"PLTE", b"tRNS")
                    ),
                    "candidate_smaller": candidate_path.stat().st_size < original_path.stat().st_size,
                    "original_sha256_preserved": sha256_file(original_path) == row["original_sha256"],
                }
            )
            sample_checks["passed"] = all(value for key, value in sample_checks.items() if key != "sample_id")
        except Exception as exc:
            sample_checks.update({"passed": False, "error": f"{type(exc).__name__}:{exc}"})
        checks.append(sample_checks)

    rejection_checks: list[dict[str, Any]] = []
    for row in rejected_rows:
        expected = row["expected_outcome"]
        passed = (
            row["actual_outcome"] == expected
            and not bool(row["candidate_exists_after"])
            and bool(row["original_sha256_preserved"])
        )
        if row["sample_id"] == "reject_apng":
            passed = passed and any(item in {"acTL", "fcTL", "fdAT"} for item in json.loads(row["actual_chunk_types"]))
        if row["sample_id"] == "reject_unknown_critical":
            passed = passed and "ABCD" in json.loads(row["actual_chunk_types"])
        if row["sample_id"] == "reject_crc_error":
            try:
                independent_png_records(Path(row["original_path"]))
                passed = False
            except ValueError as exc:
                passed = passed and "secondary_crc_mismatch:IDAT" in str(exc)
        if row["sample_id"] == "fallback_optimized_no_gain":
            passed = passed and row["technical_correctness_pass"] is True and row["output_smaller"] is False
        rejection_checks.append({"sample_id": row["sample_id"], "passed": passed, "actual_outcome": row["actual_outcome"]})

    passed = all(item.get("passed") for item in checks) and all(item["passed"] for item in rejection_checks)
    payload = {
        "verifier": "independent byte parser plus separate Pillow decode comparison",
        "static_samples": checks,
        "rejection_and_fallback_samples": rejection_checks,
        "passed": passed,
    }
    write_json(run_dir / "independent_secondary_verification.json", payload)
    lines = [
        "# Independent Secondary Verification",
        "",
        "- Parser: independent local PNG chunk/CRC parser, separate from the primary parser.",
        "- Decode check: fresh Pillow opens for original and candidate.",
        f"- Static samples passed: {sum(item.get('passed', False) for item in checks)}/{len(checks)}.",
        f"- Rejection/fallback samples passed: {sum(item['passed'] for item in rejection_checks)}/{len(rejection_checks)}.",
        f"- Overall: {'PASS' if passed else 'FAIL'}.",
        "",
    ]
    (run_dir / "independent_secondary_verification.md").write_text("\n".join(lines), encoding="utf-8")
    return payload


def write_png_robustness_report(
    path: Path,
    run_dir: Path,
    business_rows: list[dict[str, Any]],
    boundary_rows: list[dict[str, Any]],
    boundary_manifest: list[dict[str, Any]],
    rejected_rows: list[dict[str, Any]],
    business_stats: dict[str, Any],
    boundary_stats: dict[str, Any],
    independent_passed: bool,
    overall: str,
) -> None:
    lines = [
        "# PNG Format Boundary and Real-Metadata Robustness Closure",
        "",
        f"- Run directory: `{run_dir}`",
        f"- Generated: {datetime.now().astimezone().isoformat()}",
        "- Route: recompress PNG IDAT zlib stream only; preserve every non-IDAT chunk byte-for-byte.",
        "- JPEG/UI/API/formal pipeline work: none.",
        "",
        "## Real Business PNG Regression",
        "",
        "| Sample | Original | Candidate | Saved | Ratio | Technical | Recommendation |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in business_rows:
        lines.append(
            f"| {Path(row['original_path']).name} | {row['original_size_bytes']} | {row['candidate_size_bytes']} | "
            f"{row['saved_bytes']} | {float(row['saved_ratio']) * 100:.4f}% | {row['technical_correctness_pass']} | {row['final_recommendation']} |"
        )
    lines.extend(
        [
            "",
            f"- Technical pass: {business_stats['technical_pass_count']}/{business_stats['sample_count']}.",
            f"- Smaller: {business_stats['smaller_count']}/{business_stats['sample_count']}.",
            f"- Average/median/min/max saved ratio: {business_stats['average_saved_ratio'] * 100:.4f}% / "
            f"{business_stats['median_saved_ratio'] * 100:.4f}% / {business_stats['minimum_saved_ratio'] * 100:.4f}% / "
            f"{business_stats['maximum_saved_ratio'] * 100:.4f}%.",
            "",
            "## Controlled Boundary PNGs",
            "",
            "| Sample | Required structure | Actual chunks | Original | Candidate | Ratio | Technical |",
            "| --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    manifest_by_id = {row["sample_id"]: row for row in boundary_manifest}
    for row in boundary_rows:
        manifest = manifest_by_id[row["sample_id"]]
        lines.append(
            f"| {row['sample_type']} | {manifest['target_validations']} | {manifest['chunk_types']} | "
            f"{row['original_size_bytes']} | {row['candidate_size_bytes']} | {float(row['saved_ratio']) * 100:.4f}% | "
            f"{row['technical_correctness_pass']} |"
        )
    lines.extend(
        [
            "",
            f"- Technical pass: {boundary_stats['technical_pass_count']}/{boundary_stats['sample_count']}.",
            f"- Smaller: {boundary_stats['smaller_count']}/{boundary_stats['sample_count']}.",
            f"- Average/median/min/max saved ratio: {boundary_stats['average_saved_ratio'] * 100:.4f}% / "
            f"{boundary_stats['median_saved_ratio'] * 100:.4f}% / {boundary_stats['minimum_saved_ratio'] * 100:.4f}% / "
            f"{boundary_stats['maximum_saved_ratio'] * 100:.4f}%.",
            "",
            "## Rejection and No-Gain Fallback",
            "",
            "| Sample | Chunks | Expected | Actual | Reason | Candidate remains |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in rejected_rows:
        lines.append(
            f"| {row['sample_type']} | {row['actual_chunk_types']} | {row['expected_outcome']} | {row['actual_outcome']} | "
            f"{row['rejection_reason']} | {row['candidate_exists_after']} |"
        )
    lines.extend(
        [
            "",
            "## Gate Summary",
            "",
            "- ICC, EXIF/eXIf, DPI/pHYs, and XMP are positive-presence samples, not absence-only checks.",
            "- PLTE, tRNS, grayscale, 16-bit, Adam7, and contiguous multi-IDAT structures are covered.",
            "- APNG, CRC damage, and an unknown critical chunk are rejected before candidate adoption.",
            "- The already-optimized PNG falls back to the original when the candidate is not smaller.",
            f"- Independent secondary verification: {'PASS' if independent_passed else 'FAIL'}.",
            "",
            "## Final Conclusion",
            "",
            f"**{overall}**",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def run_png_robustness(args: argparse.Namespace) -> int:
    run_dir = (args.run_dir or (PROJECT_ROOT / "tmp" / "image_compression_poc_v1" / datetime.now().strftime("%Y%m%d_%H%M%S"))).resolve()
    allowed_root = (PROJECT_ROOT / "tmp" / "image_compression_poc_v1").resolve()
    if allowed_root != run_dir and allowed_root not in run_dir.parents:
        raise SystemExit(f"Run directory must stay under {allowed_root}")
    run_dir.mkdir(parents=True, exist_ok=False)
    generated_dir = run_dir / "generated_samples"
    candidate_dir = run_dir / "candidates"

    business_specs = [dict(spec) for spec in BUSINESS_PNG_SAMPLES]
    boundary_specs = generate_controlled_boundary_samples(generated_dir / "boundary")
    rejection_specs = generate_rejection_and_fallback_samples(generated_dir / "rejection_and_fallback")

    boundary_manifest: list[dict[str, Any]] = []
    for spec in boundary_specs:
        attributes = image_attributes(Path(spec["path"]))
        assert_boundary_expectations(spec, attributes)
        layout = attributes["layout"]
        boundary_manifest.append(
            {
                "sample_id": spec["sample_id"],
                "sample_type": spec["sample_type"],
                "generated_path": attributes["path"],
                "generation_method": spec["generation_method"],
                "expected_properties": json.dumps(spec["expected"], ensure_ascii=False, sort_keys=True),
                "target_validations": json.dumps(spec["target_validations"], ensure_ascii=False),
                "chunk_types": json.dumps(layout["chunk_types"], ensure_ascii=False),
                "chunk_records": json.dumps(layout["chunk_records"], ensure_ascii=False, sort_keys=True),
                "original_sha256": attributes["sha256"],
                "file_size_bytes": attributes["file_size_bytes"],
                "width": attributes["width"],
                "height": attributes["height"],
                "color_type": layout["color_type"],
                "color_mode": attributes["color_mode"],
                "channel_count": attributes["channel_count"],
                "bit_depth": attributes["bit_depth"],
                "interlace": layout["interlace"],
                "idat_count": layout["idat_count"],
            }
        )

    business_rows, business_evidence, business_sha = process_png_samples(
        business_specs, "real_business", candidate_dir, run_dir
    )
    boundary_rows, boundary_evidence, boundary_sha = process_png_samples(
        boundary_specs, "controlled_boundary", candidate_dir, run_dir
    )
    rejected_rows, fallback_evidence, rejected_sha = process_rejection_and_fallback_samples(
        rejection_specs, candidate_dir, run_dir
    )

    write_csv(run_dir / "business_samples_results.csv", PNG_ROBUSTNESS_FIELDS, business_rows)
    write_csv(run_dir / "boundary_samples_manifest.csv", BOUNDARY_MANIFEST_FIELDS, boundary_manifest)
    write_csv(run_dir / "boundary_samples_results.csv", PNG_ROBUSTNESS_FIELDS, boundary_rows)
    write_csv(run_dir / "rejected_samples_results.csv", REJECTED_RESULT_FIELDS, rejected_rows)
    write_json(
        run_dir / "png_chunk_comparison.json",
        business_evidence["chunks"] + boundary_evidence["chunks"] + fallback_evidence["chunks"],
    )
    write_json(
        run_dir / "png_metadata_comparison.json",
        business_evidence["metadata"] + boundary_evidence["metadata"] + fallback_evidence["metadata"],
    )
    write_json(
        run_dir / "png_pixel_alpha_verification.json",
        business_evidence["pixels_alpha"] + boundary_evidence["pixels_alpha"] + fallback_evidence["pixels_alpha"],
    )
    write_csv(
        run_dir / "png_sha256_manifest.csv",
        ("sample_id", "role", "path", "sha256"),
        business_sha + boundary_sha + rejected_sha,
    )

    business_stats = png_group_statistics(business_rows)
    boundary_stats = png_group_statistics(boundary_rows)
    independent = run_independent_secondary_verification(
        run_dir,
        business_rows + boundary_rows,
        rejected_rows,
    )
    required_boundary_ids = {spec["sample_id"] for spec in boundary_specs}
    rejection_pass = all(
        row["actual_outcome"] == row["expected_outcome"]
        and not row["candidate_exists_after"]
        and row["original_sha256_preserved"]
        for row in rejected_rows
    )
    business_complete = len(business_rows) == 6 and all(row["technical_correctness_pass"] for row in business_rows)
    boundary_complete = (
        {row["sample_id"] for row in boundary_rows} == required_boundary_ids
        and all(row["technical_correctness_pass"] for row in boundary_rows)
    )
    originals_preserved = all(row["original_sha256_preserved"] for row in business_rows + boundary_rows) and all(
        row["original_sha256_preserved"] for row in rejected_rows
    )
    safety_failure = any(not row["technical_correctness_pass"] for row in business_rows + boundary_rows)
    if safety_failure:
        overall = "FAIL"
    elif business_complete and boundary_complete and rejection_pass and originals_preserved and independent["passed"]:
        overall = "PASS"
    elif business_complete:
        overall = "PARTIAL"
    else:
        overall = "BLOCKED"
    write_json(
        run_dir / "png_robustness_summary.json",
        {
            "business_statistics": business_stats,
            "boundary_statistics": boundary_stats,
            "rejection_pass": rejection_pass,
            "originals_preserved": originals_preserved,
            "independent_secondary_pass": independent["passed"],
            "overall": overall,
        },
    )
    write_png_robustness_report(
        run_dir / "png_robustness_report.md",
        run_dir,
        business_rows,
        boundary_rows,
        boundary_manifest,
        rejected_rows,
        business_stats,
        boundary_stats,
        independent["passed"],
        overall,
    )
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "business_statistics": business_stats,
                "boundary_statistics": boundary_stats,
                "rejected_samples": rejected_rows,
                "independent_secondary_pass": independent["passed"],
                "overall": overall,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if overall == "PASS" else 2


def _legacy_png_regression_main() -> int:
    args = parse_args()
    if args.png_robustness:
        return run_png_robustness(args)
    run_dir = (args.run_dir or (PROJECT_ROOT / "tmp" / "image_compression_poc_v1" / datetime.now().strftime("%Y%m%d_%H%M%S"))).resolve()
    allowed_root = (PROJECT_ROOT / "tmp" / "image_compression_poc_v1").resolve()
    if allowed_root != run_dir and allowed_root not in run_dir.parents:
        raise SystemExit(f"Run directory must stay under {allowed_root}")
    run_dir.mkdir(parents=True, exist_ok=False)
    candidate_dir = run_dir / "candidates"
    compare_json_dir = run_dir / "attribute_comparisons"
    visual_dir = run_dir / "visual_compare_100pct"

    tools, search_roots = discover_tools()
    jpegtran = find_usable_jpegtran(tools)
    write_tool_report(run_dir / "tool_capability_report.md", tools, search_roots, jpegtran)

    manifest: list[dict[str, Any]] = []
    original_attributes: dict[str, dict[str, Any]] = {}
    original_hashes: dict[str, str] = {}
    for spec in BUSINESS_PNG_SAMPLES:
        source = (PROJECT_ROOT / spec["path"]).resolve()
        if not source.exists() or not source.is_file():
            raise SystemExit(f"Sample missing: {source}")
        attributes = image_attributes(source)
        expected = "PNG" if spec["sample_id"].startswith("png_") else "JPEG"
        if attributes["file_format"] != expected or attributes["magic_format"] != expected:
            raise SystemExit(f"Sample format mismatch: {source} expected={expected} actual={attributes['file_format']}/{attributes['magic_format']}")
        original_attributes[spec["sample_id"]] = attributes
        original_hashes[spec["sample_id"]] = attributes["sha256"]
        manifest.append(manifest_row(spec, attributes))
    write_csv(run_dir / "golden_samples_manifest.csv", MANIFEST_FIELDS, manifest)
    write_json(run_dir / "golden_samples_manifest.json", manifest)

    results: list[dict[str, Any]] = []
    pixel_rows: list[dict[str, Any]] = []
    alpha_rows: list[dict[str, Any]] = []
    metadata_rows: list[dict[str, Any]] = []
    sha_rows: list[dict[str, Any]] = []

    for spec in BUSINESS_PNG_SAMPLES:
        source = Path(original_attributes[spec["sample_id"]]["path"])
        original = original_attributes[spec["sample_id"]]
        suffix = ".png" if original["file_format"] == "PNG" else source.suffix.lower()
        candidate_path = candidate_dir / f"{spec['sample_id']}__lossless{suffix}"
        if original["file_format"] == "JPEG" and jpegtran is None:
            row = blocked_result(spec, original, "jpeg_coefficient_tool_unavailable", "none")
            results.append(row)
            write_json(
                compare_json_dir / f"{spec['sample_id']}.json",
                {"sample": spec, "original": original, "candidate": None, "checks": None, "status": "BLOCKED"},
            )
            pixel_rows.append({"sample_id": spec["sample_id"], "status": "not_run", "pixel_exact": "not_run", "reason": row["failure_reason"]})
            alpha_rows.append({"sample_id": spec["sample_id"], "status": "not_run", "alpha_exact": "not_run", "reason": row["failure_reason"]})
            metadata_rows.append({"sample_id": spec["sample_id"], "status": "not_run", "reason": row["failure_reason"]})
            sha_rows.append({"sample_id": spec["sample_id"], "role": "original", "path": str(source), "sha256": original["sha256"]})
            continue

        started = time.perf_counter()
        operation: dict[str, Any]
        tool_name: str
        tool_version: str
        try:
            if original["file_format"] == "PNG":
                operation = optimize_png_structure(source, candidate_path)
                tool_name = "python-zlib-idat-recompress"
                tool_version = f"python {sys.version.split()[0]}; zlib {zlib.ZLIB_RUNTIME_VERSION}"
            else:
                operation = optimize_jpeg_coefficients(jpegtran, source, candidate_path)
                tool_name = "jpegtran"
                tool_version = str(jpegtran.get("version_output") or "help-verified-local-binary")[:500]
            candidate = image_attributes(candidate_path)
            original_hash_after = sha256_file(source)
            checks = compare_attributes(original, candidate, original_hash_after)
            elapsed = time.perf_counter() - started
            kept = bool(checks["all_hard_gates_pass"])
            row = result_row(spec, original, candidate, checks, elapsed, tool_name, tool_version, kept, candidate_path)
            write_json(
                compare_json_dir / f"{spec['sample_id']}.json",
                {
                    "sample": spec,
                    "original": original,
                    "candidate": candidate,
                    "operation": operation,
                    "checks": checks,
                    "candidate_kept": kept,
                    "final_recommendation": row["final_recommendation"],
                },
            )
            sha_rows.extend(
                [
                    {"sample_id": spec["sample_id"], "role": "original", "path": str(source), "sha256": original["sha256"]},
                    {"sample_id": spec["sample_id"], "role": "candidate_attempt", "path": str(candidate_path), "sha256": candidate["sha256"]},
                ]
            )
            pixel_rows.append(
                {
                    "sample_id": spec["sample_id"],
                    "status": "pass" if checks["pixel_exact"] else "fail",
                    "pixel_exact": checks["pixel_exact"],
                    "original_pixel_sha256": original["decoded_pixel_sha256"],
                    "candidate_pixel_sha256": candidate["decoded_pixel_sha256"],
                }
            )
            alpha_rows.append(
                {
                    "sample_id": spec["sample_id"],
                    "status": "pass" if checks["alpha_exact"] else "fail",
                    "alpha_exact": checks["alpha_exact"],
                    "original_alpha_sha256": original["alpha_sha256"],
                    "candidate_alpha_sha256": candidate["alpha_sha256"],
                }
            )
            metadata_rows.append(
                {
                    "sample_id": spec["sample_id"],
                    "icc_preserved": checks["icc_preserved"],
                    "exif_orientation_preserved": checks["exif_orientation_preserved"],
                    "exif_payload_preserved": checks["exif_payload_preserved"],
                    "dpi_preserved": checks["dpi_preserved"],
                    "xmp_preserved": checks["xmp_preserved"],
                    "critical_metadata_preserved": checks["critical_metadata_preserved"],
                    "jpeg_quantization_preserved": checks["jpeg_quantization_preserved"],
                    "jpeg_sampling_preserved": checks["jpeg_sampling_preserved"],
                    "failed_checks": ";".join(checks["failed_checks"]),
                }
            )
            if kept:
                create_visual_compare(source, candidate_path, visual_dir / f"{spec['sample_id']}__100pct.png")
            else:
                safe_remove(candidate_path, run_dir)
            results.append(row)
        except Exception as exc:
            elapsed = time.perf_counter() - started
            safe_remove(candidate_path, run_dir)
            row = blocked_result(spec, original, f"processing_error:{type(exc).__name__}:{exc}", "png_zlib" if original["file_format"] == "PNG" else "jpegtran")
            row["elapsed_seconds"] = round(elapsed, 6)
            results.append(row)
            write_json(
                compare_json_dir / f"{spec['sample_id']}.json",
                {"sample": spec, "original": original, "candidate": None, "checks": None, "status": "FAILED", "error": str(exc)},
            )

    for spec in BUSINESS_PNG_SAMPLES:
        current_hash = sha256_file(Path(original_attributes[spec["sample_id"]]["path"]))
        if current_hash != original_hashes[spec["sample_id"]]:
            raise RuntimeError(f"Original sample changed: {spec['sample_id']}")

    write_csv(run_dir / "lossless_compression_results.csv", RESULT_FIELDS, results)
    write_csv(
        run_dir / "sha256_manifest.csv",
        ("sample_id", "role", "path", "sha256"),
        sha_rows,
    )
    pixel_fields = sorted({key for row in pixel_rows for key in row.keys()})
    alpha_fields = sorted({key for row in alpha_rows for key in row.keys()})
    metadata_fields = sorted({key for row in metadata_rows for key in row.keys()})
    write_csv(run_dir / "pixel_consistency_results.csv", pixel_fields, pixel_rows)
    write_csv(run_dir / "alpha_consistency_results.csv", alpha_fields, alpha_rows)
    write_csv(run_dir / "metadata_diff_results.csv", metadata_fields, metadata_rows)
    write_json(run_dir / "lossless_compression_results.json", results)
    write_report(run_dir / "lossless_compression_report.md", results, run_dir, jpegtran is not None)

    print(json.dumps({"run_dir": str(run_dir), "results": results}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    """Run the finalized static-PNG robustness PoC entrypoint."""
    return run_png_robustness(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
