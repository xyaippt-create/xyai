"""Lossless metadata augmentation for HDDE JPEG, PNG and WebP final images."""

from __future__ import annotations

import binascii
import hashlib
import io
import math
import os
import re
import struct
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from PIL import Image

from runtime import APP_VERSION


HDDE_CONTACT_EMAIL = "xueyaippt@outlook.com"
HDDE_SOFTWARE = f"影界 HDDE {APP_VERSION}"
HDDE_COMMENT = f"由影界 HDDE 处理｜联系邮箱：{HDDE_CONTACT_EMAIL}"
HDDE_KEYWORDS = "影界 HDDE"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
WEBP_RIFF = b"RIFF"
WEBP_FORM = b"WEBP"
EXIF_PREFIX = b"Exif\x00\x00"
XMP_PREFIX = b"http://ns.adobe.com/xap/1.0/\x00"
ICC_PREFIX = b"ICC_PROFILE\x00"
_PNG_TARGET_KEYS = {"Software", "Comment", "Comments", "Keywords"}
_PNG_SOURCE_IDENTITY_KEYS = {"Title", "Author"}
_PNG_XMP_KEY = "XML:com.adobe.xmp"
_XMP_NS = "adobe:ns:meta/"
_RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_XMP_BASIC_NS = "http://ns.adobe.com/xap/1.0/"
_DC_NS = "http://purl.org/dc/elements/1.1/"
_TIFF_NS = "http://ns.adobe.com/tiff/1.0/"
_PHOTOSHOP_APP13_HEADER = b"Photoshop 3.0\x00"
_IPTC_RESOURCE_ID = 0x0404
_HDDE_PRODUCT_VERSION_PATTERN = re.compile(
    r"(?:影界\s+HDDE|HDDE|VisualMasterPro)\s+V?\d+(?:\.\d+){1,3}"
    r"(?:[-+][0-9A-Za-z.-]+)?(?:\s+[\u4e00-\u9fff]+版)?",
    flags=re.IGNORECASE,
)
_IPTC_TEXT_DATASETS = {
    (2, 5),    # Object Name
    (2, 25),   # Keywords
    (2, 40),   # Special Instructions
    (2, 65),   # Originating Program
    (2, 70),   # Program Version
    (2, 80),   # By-line
    (2, 85),   # By-line Title
    (2, 92),   # Sublocation
    (2, 95),   # Province/State
    (2, 101),  # Country
    (2, 105),  # Headline
    (2, 110),  # Credit
    (2, 115),  # Source
    (2, 116),  # Copyright Notice
    (2, 118),  # Contact
    (2, 120),  # Caption/Abstract
    (2, 122),  # Writer/Editor
}
_SOURCE_EXIF_TAGS = {
    270: "ImageDescription",
    271: "Make",
    272: "Model",
    315: "Artist",
    33432: "Copyright",
    34853: "GPSInfo",
    36867: "DateTimeOriginal",
    37386: "FocalLength",
    40091: "XPTitle",
    40093: "XPAuthor",
    42036: "LensModel",
}
_TITLE_EXIF_TAGS = (270, 40091)
_AUTHOR_EXIF_TAGS = (315, 40093)


def _sha256(value: bytes | None) -> str | None:
    return hashlib.sha256(value).hexdigest() if value is not None else None


def _valid_dpi(value: object) -> tuple[float, float] | None:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return None
    try:
        dpi = (float(value[0]), float(value[1]))
    except (TypeError, ValueError):
        return None
    return dpi if all(math.isfinite(item) and item > 0 for item in dpi) else None


def _effective_dpi(image: Image.Image, exif: Image.Exif) -> tuple[float, float] | None:
    image_format = str(image.format or "").upper()
    if image_format == "JPEG":
        density = _valid_dpi(image.info.get("jfif_density"))
        unit = image.info.get("jfif_unit")
        if density is not None and unit == 1:
            return density
        if density is not None and unit == 2:
            return tuple(value * 2.54 for value in density)
    else:
        dpi = _valid_dpi(image.info.get("dpi"))
        if dpi is not None:
            return dpi
    exif_dpi = _valid_dpi((exif.get(282), exif.get(283)))
    if exif_dpi is None:
        return None
    unit = exif.get(296, 2)
    if unit == 2:
        return exif_dpi
    if unit == 3:
        return tuple(value * 2.54 for value in exif_dpi)
    return None


def _read_effective_dpi(data: bytes) -> tuple[float, float] | None:
    with Image.open(io.BytesIO(data)) as image:
        return _effective_dpi(image, image.getexif())


def _dpi_equal(expected: tuple[float, float] | None, actual: tuple[float, float] | None) -> bool:
    if expected is None or actual is None:
        return expected is actual
    return all(math.isclose(left, right, rel_tol=1e-5, abs_tol=0.01) for left, right in zip(expected, actual))


def _decoded_signature(data: bytes) -> dict[str, Any]:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        pixels = image.tobytes()
        alpha = image.convert("RGBA").getchannel("A").tobytes() if "A" in image.getbands() or "transparency" in image.info else None
        icc = image.info.get("icc_profile") if isinstance(image.info.get("icc_profile"), bytes) else None
        exif = image.getexif()
        dpi = image.info.get("dpi")
        normalized_dpi = tuple(round(float(value), 6) for value in dpi) if isinstance(dpi, tuple) else dpi
        exif_resolution = tuple(repr(exif.get(tag)) if tag in exif else None for tag in (282, 283, 296))
        resolution_metadata = (
            "jpeg",
            image.info.get("jfif_unit"),
            image.info.get("jfif_density"),
            exif_resolution,
        ) if image.format == "JPEG" else (
            str(image.format or "").upper(),
            normalized_dpi,
            exif_resolution,
        )
        return {
            "format": "JPEG" if image.format == "JPG" else str(image.format or "").upper(),
            "size": image.size,
            "mode": image.mode,
            "pixel_sha256": _sha256(pixels),
            "alpha_sha256": _sha256(alpha),
            "icc_sha256": _sha256(icc),
            "effective_dpi": _effective_dpi(image, exif),
            "resolution_metadata": resolution_metadata,
        }


def _xp_text(value: str) -> bytes:
    return (str(value) + "\x00").encode("utf-16le")


def _decode_xp_text(value: Any) -> str:
    if isinstance(value, tuple):
        value = bytes(value)
    if isinstance(value, bytes):
        return value.decode("utf-16le", errors="replace").rstrip("\x00")
    return str(value or "")


def _read_exif(data: bytes) -> Image.Exif:
    with Image.open(io.BytesIO(data)) as image:
        # Pillow reads JPEG APP markers before SOS in _open(). Metadata access
        # needs no pixel decode. PNG may carry metadata after IDAT; keep its load.
        if image.format != "JPEG":
            image.load()
        return image.getexif()


def _merged_exif_bytes(output_data: bytes, source_data: bytes | None, *, normalize_orientation: bool) -> bytes:
    output_exif = _read_exif(output_data)
    source_exif = _read_exif(source_data) if source_data else Image.Exif()
    identity_exif = source_exif if source_data is not None else output_exif
    base = source_exif if len(source_exif) else output_exif
    if base is source_exif:
        for tag, value in output_exif.items():
            if tag not in base:
                base[tag] = value
    elif len(source_exif):
        for tag, value in source_exif.items():
            if tag not in base:
                base[tag] = value
    for tag in (*_TITLE_EXIF_TAGS, *_AUTHOR_EXIF_TAGS):
        if tag in identity_exif:
            base[tag] = identity_exif.get(tag)
        else:
            base.pop(tag, None)
    if normalize_orientation and (274 in base or len(base)):
        base[274] = 1
    # EXIF Software is ASCII-only. Windows Explorer gives it precedence over
    # XMP CreatorTool, so an ASCII fallback would hide the required Unicode
    # product identity. Remove the conflicting tag and carry the exact value in
    # XMP, which Explorer exposes as Program Name without re-encoding pixels.
    base.pop(305, None)
    base[37510] = b"UNICODE\x00" + HDDE_COMMENT.encode("utf-16le")
    base[40092] = _xp_text(HDDE_COMMENT)
    base[40094] = _xp_text(HDDE_KEYWORDS)
    payload = base.tobytes()
    return payload if payload.startswith(EXIF_PREFIX) else EXIF_PREFIX + payload


def _extract_xmp(data: bytes | None) -> bytes:
    if not data:
        return b""
    if data.startswith(JPEG_SIGNATURE):
        try:
            segments, _ = _jpeg_segments(data)
        except ValueError:
            return b""
        for segment in segments:
            payload = _jpeg_payload(segment)
            if _jpeg_marker(segment) == 0xE1 and payload.startswith(XMP_PREFIX):
                return payload[len(XMP_PREFIX) :]
        return b""
    if data.startswith(WEBP_RIFF) and data[8:12] == WEBP_FORM:
        try:
            for chunk_type, payload in _webp_chunks(data):
                if chunk_type == b"XMP ":
                    return payload
        except ValueError:
            return b""
        return b""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            value = image.info.get(_PNG_XMP_KEY) or image.info.get("xmp") or b""
            return value.encode("utf-8") if isinstance(value, str) else value if isinstance(value, bytes) else b""
    except Exception:
        return b""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _is_hdde_product_text(value: str) -> bool:
    normalized = " ".join(str(value or "").split())
    folded = normalized.casefold()
    return folded in {"影界 hdde", "hdde", "visualmasterpro"} or bool(
        _HDDE_PRODUCT_VERSION_PATTERN.fullmatch(normalized)
    )


def _is_hdde_contact_email(value: str) -> bool:
    return str(value or "").strip().casefold() == HDDE_CONTACT_EMAIL.casefold()


def _is_hdde_legacy_contact(value: str) -> bool:
    text = str(value or "")
    folded = text.casefold()
    if "xuey_aippt" in folded:
        return True
    if "由影界 hdde 处理" in folded:
        return True
    if "微信" in text and _is_hdde_product_text(text):
        return True
    return HDDE_CONTACT_EMAIL in folded


def _remove_hdde_legacy_contact(value: str) -> str:
    text = str(value or "")
    if not _is_hdde_legacy_contact(text):
        return text
    kept = [
        line
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if not _is_hdde_legacy_contact(line) and "微信" not in line
    ]
    return "\n".join(line for line in kept if line.strip()).strip()


def _description_nodes(root: ET.Element) -> list[ET.Element]:
    return list(root.findall(f".//{{{_RDF_NS}}}Description"))


def _xmp_subject_values(root: ET.Element) -> list[str]:
    values = [
        str(item.text or "")
        for item in root.findall(f".//{{{_DC_NS}}}subject/{{{_RDF_NS}}}Bag/{{{_RDF_NS}}}li")
        if str(item.text or "")
    ]
    for description in _description_nodes(root):
        compact = str(description.get(f"{{{_DC_NS}}}subject", "") or "")
        if compact:
            values.append(compact)
    return values


def _clean_xmp_subject(description: ET.Element, subject: ET.Element) -> None:
    items = list(subject.findall(f".//{{{_RDF_NS}}}li"))
    if items:
        for container in subject.iter():
            for item in list(container):
                value = str(item.text or "")
                if item.tag == f"{{{_RDF_NS}}}li" and (
                    _is_hdde_product_text(value) or _is_hdde_contact_email(value)
                ):
                    container.remove(item)
        if not any(str(item.text or "") for item in subject.findall(f".//{{{_RDF_NS}}}li")):
            description.remove(subject)
        return
    value = str(subject.text or "")
    if _is_hdde_product_text(value) or _is_hdde_contact_email(value):
        description.remove(subject)


def _clean_xmp_property(description: ET.Element, child: ET.Element) -> None:
    local_name = _local_name(child.tag)
    if child.tag == f"{{{_DC_NS}}}subject":
        _clean_xmp_subject(description, child)
        return
    if local_name in {"CreatorTool", "Software"}:
        values = [str(node.text or "") for node in child.iter()]
        if any(_is_hdde_product_text(value) for value in values):
            description.remove(child)
        return
    changed = False
    for node in child.iter():
        if not node.text:
            continue
        cleaned = _remove_hdde_legacy_contact(node.text)
        if cleaned != node.text:
            node.text = cleaned or None
            changed = True
    if changed and not any(str(node.text or "").strip() for node in child.iter()):
        description.remove(child)


def _merged_xmp(output_data: bytes, source_data: bytes | None) -> bytes:
    source_packet = _extract_xmp(source_data) if source_data is not None else b""
    existing = source_packet or _extract_xmp(output_data)
    root: ET.Element
    if existing:
        try:
            root = ET.fromstring(existing.decode("utf-8", errors="strict"))
        except (ET.ParseError, UnicodeDecodeError):
            root = ET.Element(f"{{{_XMP_NS}}}xmpmeta")
    else:
        root = ET.Element(f"{{{_XMP_NS}}}xmpmeta")
    rdf = root.find(f".//{{{_RDF_NS}}}RDF")
    if rdf is None:
        rdf = ET.SubElement(root, f"{{{_RDF_NS}}}RDF")
    descriptions = _description_nodes(root)
    if not descriptions:
        description = ET.SubElement(rdf, f"{{{_RDF_NS}}}Description")
        description.set(f"{{{_RDF_NS}}}about", "")
        descriptions = [description]
    canonical = descriptions[0]

    # When a separate source has no XMP, no identity property from an
    # intermediate candidate is authoritative.
    if source_data is not None and not source_packet:
        for description in descriptions:
            for property_name in ("title", "creator"):
                for child in list(description.findall(f"{{{_DC_NS}}}{property_name}")):
                    description.remove(child)

    for description in descriptions:
        for attribute, value in list(description.attrib.items()):
            local_name = _local_name(attribute)
            if attribute == f"{{{_DC_NS}}}subject" and _is_hdde_product_text(value):
                description.attrib.pop(attribute, None)
            elif local_name in {"CreatorTool", "Software"} and _is_hdde_product_text(value):
                description.attrib.pop(attribute, None)
            elif _is_hdde_legacy_contact(value):
                cleaned = _remove_hdde_legacy_contact(value)
                if cleaned:
                    description.set(attribute, cleaned)
                else:
                    description.attrib.pop(attribute, None)
        for child in list(description):
            _clean_xmp_property(description, child)

    canonical.set(f"{{{_XMP_BASIC_NS}}}CreatorTool", HDDE_SOFTWARE)
    subject = canonical.find(f"{{{_DC_NS}}}subject")
    bag = subject.find(f"{{{_RDF_NS}}}Bag") if subject is not None else None
    if bag is None:
        subject = ET.SubElement(canonical, f"{{{_DC_NS}}}subject")
        bag = ET.SubElement(subject, f"{{{_RDF_NS}}}Bag")
    keyword = ET.SubElement(bag, f"{{{_RDF_NS}}}li")
    keyword.text = HDDE_KEYWORDS

    ET.register_namespace("x", _XMP_NS)
    ET.register_namespace("rdf", _RDF_NS)
    ET.register_namespace("xmp", _XMP_BASIC_NS)
    ET.register_namespace("dc", _DC_NS)
    ET.register_namespace("tiff", _TIFF_NS)
    return ET.tostring(root, encoding="utf-8", xml_declaration=False)


def _read_xmp_fields(data: bytes) -> dict[str, str]:
    packet = _extract_xmp(data)
    if not packet:
        return {}
    try:
        root = ET.fromstring(packet.decode("utf-8", errors="strict"))
    except (ET.ParseError, UnicodeDecodeError):
        return {}
    descriptions = _description_nodes(root)
    software_values = [
        description.get(f"{{{_XMP_BASIC_NS}}}CreatorTool", "")
        for description in descriptions
        if description.get(f"{{{_XMP_BASIC_NS}}}CreatorTool", "")
    ]
    comment_values = [
        str(item.text or "")
        for item in root.findall(f".//{{{_DC_NS}}}description/{{{_RDF_NS}}}Alt/{{{_RDF_NS}}}li")
        if str(item.text or "") and not _is_hdde_legacy_contact(str(item.text or ""))
    ]
    title_values = [
        str(item.text or "")
        for item in root.findall(f".//{{{_DC_NS}}}title/{{{_RDF_NS}}}Alt/{{{_RDF_NS}}}li")
        if str(item.text or "") and not _is_hdde_legacy_contact(str(item.text or ""))
    ]
    author_values = [
        str(item.text or "")
        for item in root.findall(f".//{{{_DC_NS}}}creator/{{{_RDF_NS}}}Seq/{{{_RDF_NS}}}li")
        if str(item.text or "")
    ]
    keywords = _xmp_subject_values(root)
    return {
        "software": software_values[0] if software_values else "",
        "comment": comment_values[0] if comment_values else "",
        "title": title_values[0] if title_values else "",
        "author": author_values[0] if author_values else "",
        "keywords": HDDE_KEYWORDS if HDDE_KEYWORDS in keywords else "; ".join(keywords),
    }


def _xmp_contract_conflicts(data: bytes) -> list[str]:
    packet = _extract_xmp(data)
    if not packet:
        return ["XMP_PACKET_MISSING"]
    try:
        root = ET.fromstring(packet.decode("utf-8", errors="strict"))
    except (ET.ParseError, UnicodeDecodeError):
        return ["XMP_PACKET_INVALID"]
    descriptions = _description_nodes(root)
    if not descriptions:
        return ["XMP_DESCRIPTION_MISSING"]
    conflicts: list[str] = []
    subject_values = _xmp_subject_values(root)
    hdde_subjects = [value for value in subject_values if _is_hdde_product_text(value)]
    if hdde_subjects != [HDDE_KEYWORDS]:
        conflicts.append("XMP_KEYWORDS_CONFLICT")
    current_software = 0
    for description in descriptions:
        for attribute, value in description.attrib.items():
            local_name = _local_name(attribute)
            if _is_hdde_legacy_contact(value):
                conflicts.append(f"XMP_LEGACY_CONTACT_ATTRIBUTE_{local_name}")
            if local_name in {"CreatorTool", "Software"} and _is_hdde_product_text(value):
                if local_name == "CreatorTool" and value == HDDE_SOFTWARE:
                    current_software += 1
                else:
                    conflicts.append(f"XMP_SOFTWARE_CONFLICT_{local_name}")
        for child in description:
            local_name = _local_name(child.tag)
            values = [str(node.text or "") for node in child.iter() if str(node.text or "")]
            if any(_is_hdde_legacy_contact(value) for value in values):
                conflicts.append(f"XMP_LEGACY_CONTACT_PROPERTY_{local_name}")
            if local_name in {"CreatorTool", "Software"}:
                for value in values:
                    if _is_hdde_product_text(value):
                        conflicts.append(f"XMP_SOFTWARE_CONFLICT_{local_name}")
    if current_software != 1:
        conflicts.append("XMP_SOFTWARE_NOT_UNIQUE")
    return conflicts


def _source_metadata_facts(data: bytes | None) -> dict[str, str]:
    if not data:
        return {}
    try:
        exif = _read_exif(data)
    except Exception:
        return {}
    facts: dict[str, str] = {}
    for tag, label in _SOURCE_EXIF_TAGS.items():
        if tag not in exif:
            continue
        value = exif.get(tag)
        facts[label] = _decode_xp_text(value) if tag in {40091, 40092, 40093, 40094, 40095} else repr(value)
    return facts


def _jpeg_segments(data: bytes) -> tuple[list[bytes], bytes]:
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("JPEG_SIGNATURE_INVALID")
    segments: list[bytes] = []
    cursor = 2
    while cursor < len(data):
        start = cursor
        if data[cursor] != 0xFF:
            raise ValueError("JPEG_MARKER_INVALID")
        while cursor < len(data) and data[cursor] == 0xFF:
            cursor += 1
        if cursor >= len(data):
            raise ValueError("JPEG_MARKER_TRUNCATED")
        marker = data[cursor]
        cursor += 1
        if marker == 0xDA:
            if cursor + 2 > len(data):
                raise ValueError("JPEG_SOS_TRUNCATED")
            length = struct.unpack(">H", data[cursor : cursor + 2])[0]
            end = cursor + length
            if end > len(data):
                raise ValueError("JPEG_SOS_INVALID")
            return segments, data[start:]
        if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
            segments.append(data[start:cursor])
            continue
        if cursor + 2 > len(data):
            raise ValueError("JPEG_SEGMENT_TRUNCATED")
        length = struct.unpack(">H", data[cursor : cursor + 2])[0]
        end = cursor + length
        if length < 2 or end > len(data):
            raise ValueError("JPEG_SEGMENT_INVALID")
        segments.append(data[start:end])
        cursor = end
    raise ValueError("JPEG_SOS_MISSING")


def _jpeg_marker(segment: bytes) -> int:
    index = 0
    while index < len(segment) and segment[index] == 0xFF:
        index += 1
    return segment[index] if index < len(segment) else -1


def _jpeg_payload(segment: bytes) -> bytes:
    marker_index = 0
    while marker_index < len(segment) and segment[marker_index] == 0xFF:
        marker_index += 1
    return segment[marker_index + 3 :] if marker_index + 3 <= len(segment) else b""


def _jpeg_segment(marker: int, payload: bytes) -> bytes:
    length = len(payload) + 2
    if length > 0xFFFF:
        raise ValueError("JPEG_METADATA_SEGMENT_TOO_LARGE")
    return b"\xff" + bytes([marker]) + struct.pack(">H", length) + payload


def _photoshop_resources(payload: bytes) -> list[tuple[bytes, int, bytes, bytes]] | None:
    if not payload.startswith(_PHOTOSHOP_APP13_HEADER):
        return None
    resources: list[tuple[bytes, int, bytes, bytes]] = []
    cursor = len(_PHOTOSHOP_APP13_HEADER)
    while cursor < len(payload):
        if cursor + 7 > len(payload):
            raise ValueError("PHOTOSHOP_RESOURCE_TRUNCATED")
        signature = payload[cursor : cursor + 4]
        if signature not in {b"8BIM", b"MeSa"}:
            raise ValueError("PHOTOSHOP_RESOURCE_SIGNATURE_INVALID")
        resource_id = struct.unpack(">H", payload[cursor + 4 : cursor + 6])[0]
        name_length = payload[cursor + 6]
        name_end = cursor + 7 + name_length
        name_padded_end = name_end + ((1 + name_length) % 2)
        if name_padded_end + 4 > len(payload):
            raise ValueError("PHOTOSHOP_RESOURCE_NAME_INVALID")
        name_field = payload[cursor + 6 : name_padded_end]
        data_length = struct.unpack(">I", payload[name_padded_end : name_padded_end + 4])[0]
        data_start = name_padded_end + 4
        data_end = data_start + data_length
        padded_end = data_end + (data_length % 2)
        if padded_end > len(payload):
            raise ValueError("PHOTOSHOP_RESOURCE_DATA_INVALID")
        resources.append((signature, resource_id, name_field, payload[data_start:data_end]))
        cursor = padded_end
    return resources


def _build_photoshop_resources(resources: list[tuple[bytes, int, bytes, bytes]]) -> bytes:
    output = bytearray(_PHOTOSHOP_APP13_HEADER)
    for signature, resource_id, name_field, data in resources:
        output.extend(signature)
        output.extend(struct.pack(">H", resource_id))
        output.extend(name_field)
        output.extend(struct.pack(">I", len(data)))
        output.extend(data)
        if len(data) % 2:
            output.append(0)
    return bytes(output)


def _parse_iptc_datasets(data: bytes) -> list[tuple[int, int, bytes, bytes]]:
    datasets: list[tuple[int, int, bytes, bytes]] = []
    cursor = 0
    while cursor < len(data):
        start = cursor
        if cursor + 5 > len(data) or data[cursor] != 0x1C:
            raise ValueError("IPTC_DATASET_INVALID")
        record = data[cursor + 1]
        dataset = data[cursor + 2]
        length_word = struct.unpack(">H", data[cursor + 3 : cursor + 5])[0]
        cursor += 5
        if length_word & 0x8000:
            length_bytes = length_word & 0x7FFF
            if length_bytes < 1 or length_bytes > 4 or cursor + length_bytes > len(data):
                raise ValueError("IPTC_EXTENDED_LENGTH_INVALID")
            length = int.from_bytes(data[cursor : cursor + length_bytes], "big")
            cursor += length_bytes
        else:
            length = length_word
        end = cursor + length
        if end > len(data):
            raise ValueError("IPTC_DATASET_TRUNCATED")
        datasets.append((record, dataset, data[cursor:end], data[start:end]))
        cursor = end
    return datasets


def _build_iptc_dataset(record: int, dataset: int, value: bytes) -> bytes:
    if len(value) <= 0x7FFF:
        length = struct.pack(">H", len(value))
    else:
        encoded_length = len(value).to_bytes(4, "big")
        length = struct.pack(">H", 0x8000 | len(encoded_length)) + encoded_length
    return b"\x1c" + bytes((record, dataset)) + length + value


def _decode_iptc_text(value: bytes) -> str:
    try:
        return value.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return value.decode("latin-1", errors="replace")


def _govern_iptc_data(data: bytes) -> bytes:
    datasets = _parse_iptc_datasets(data)
    has_hdde_program = any(
        (record, dataset) == (2, 65) and _is_hdde_product_text(_decode_iptc_text(value))
        for record, dataset, value, _raw in datasets
    )
    seen_keyword = False
    seen_program = False
    seen_version = False
    output: list[bytes] = []
    for record, dataset, value, raw in datasets:
        key = (record, dataset)
        text = _decode_iptc_text(value) if key in _IPTC_TEXT_DATASETS else ""
        cleaned = _remove_hdde_legacy_contact(text) if text else text
        if text and cleaned != text:
            if not cleaned:
                continue
            value = cleaned.encode("utf-8")
            text = cleaned
            raw = _build_iptc_dataset(record, dataset, value)
        if key == (2, 25) and _is_hdde_product_text(text):
            if seen_keyword:
                continue
            value = HDDE_KEYWORDS.encode("utf-8")
            raw = _build_iptc_dataset(record, dataset, value)
            seen_keyword = True
        elif key == (2, 65) and _is_hdde_product_text(text):
            if seen_program:
                continue
            value = HDDE_SOFTWARE.encode("utf-8")
            raw = _build_iptc_dataset(record, dataset, value)
            seen_program = True
        elif key == (2, 70) and (has_hdde_program or _is_hdde_product_text(text)):
            if seen_version:
                continue
            value = APP_VERSION.encode("utf-8")
            raw = _build_iptc_dataset(record, dataset, value)
            seen_version = True
        output.append(raw)
    return b"".join(output)


def _govern_iptc_segment(segment: bytes) -> bytes:
    payload = _jpeg_payload(segment)
    resources = _photoshop_resources(payload)
    if resources is None:
        return segment
    governed: list[tuple[bytes, int, bytes, bytes]] = []
    changed = False
    for signature, resource_id, name_field, data in resources:
        updated = _govern_iptc_data(data) if resource_id == _IPTC_RESOURCE_ID else data
        changed = changed or updated != data
        governed.append((signature, resource_id, name_field, updated))
    return _jpeg_segment(0xED, _build_photoshop_resources(governed)) if changed else segment


def _read_iptc_datasets(data: bytes) -> list[tuple[int, int, bytes]]:
    if not data.startswith(JPEG_SIGNATURE):
        return []
    datasets: list[tuple[int, int, bytes]] = []
    for segment in _jpeg_segments(data)[0]:
        if _jpeg_marker(segment) != 0xED:
            continue
        resources = _photoshop_resources(_jpeg_payload(segment))
        if resources is None:
            continue
        for _signature, resource_id, _name_field, resource_data in resources:
            if resource_id == _IPTC_RESOURCE_ID:
                datasets.extend((record, dataset, value) for record, dataset, value, _raw in _parse_iptc_datasets(resource_data))
    return datasets


def _iptc_contract_conflicts(data: bytes) -> list[str]:
    try:
        datasets = _read_iptc_datasets(data)
    except ValueError as exc:
        return [str(exc)]
    conflicts: list[str] = []
    has_hdde_program = any(
        (record, dataset) == (2, 65) and _is_hdde_product_text(_decode_iptc_text(value))
        for record, dataset, value in datasets
    )
    current_keywords = 0
    current_programs = 0
    current_versions = 0
    for record, dataset, value in datasets:
        key = (record, dataset)
        text = _decode_iptc_text(value) if key in _IPTC_TEXT_DATASETS else ""
        if text and _is_hdde_legacy_contact(text):
            conflicts.append(f"IPTC_LEGACY_CONTACT_{record}_{dataset}")
        if key == (2, 25) and _is_hdde_product_text(text):
            if text != HDDE_KEYWORDS:
                conflicts.append("IPTC_KEYWORDS_CONFLICT")
            else:
                current_keywords += 1
        elif key == (2, 65) and _is_hdde_product_text(text):
            if text != HDDE_SOFTWARE:
                conflicts.append("IPTC_SOFTWARE_CONFLICT")
            else:
                current_programs += 1
        elif key == (2, 70) and has_hdde_program:
            if text != APP_VERSION:
                conflicts.append("IPTC_VERSION_CONFLICT")
            else:
                current_versions += 1
    if current_keywords > 1:
        conflicts.append("IPTC_KEYWORDS_DUPLICATE")
    if current_programs > 1:
        conflicts.append("IPTC_SOFTWARE_DUPLICATE")
    if current_versions > 1:
        conflicts.append("IPTC_VERSION_DUPLICATE")
    return conflicts


def _jpeg_category(segment: bytes) -> str:
    marker = _jpeg_marker(segment)
    payload = _jpeg_payload(segment)
    if marker == 0xE1 and payload.startswith(EXIF_PREFIX):
        return "exif"
    if marker == 0xE1 and payload.startswith(XMP_PREFIX):
        return "xmp"
    if marker == 0xE2 and payload.startswith(ICC_PREFIX):
        return "icc"
    if marker == 0xED:
        return "iptc"
    if marker == 0xFE:
        return "comment"
    return ""


def _write_jpeg_metadata(output_data: bytes, source_data: bytes | None, *, normalize_orientation: bool) -> bytes:
    segments, tail = _jpeg_segments(output_data)
    exif_payload = _merged_exif_bytes(output_data, source_data, normalize_orientation=normalize_orientation)
    xmp_payload = _merged_xmp(output_data, source_data)
    kept = [
        _govern_iptc_segment(segment) if _jpeg_category(segment) == "iptc" else segment
        for segment in segments
        if _jpeg_category(segment) not in {"exif", "xmp"}
    ]
    existing_categories = {_jpeg_category(segment) for segment in kept}
    inherited: list[bytes] = []
    if source_data and source_data.startswith(JPEG_SIGNATURE):
        source_segments, _ = _jpeg_segments(source_data)
        for segment in source_segments:
            category = _jpeg_category(segment)
            if category in {"icc", "iptc", "comment"} and category not in existing_categories:
                inherited.append(_govern_iptc_segment(segment) if category == "iptc" else segment)
                existing_categories.add(category)
    insertion = 0
    while insertion < len(kept) and _jpeg_marker(kept[insertion]) in {0xE0, 0xEE}:
        insertion += 1
    metadata = [_jpeg_segment(0xE1, exif_payload), _jpeg_segment(0xE1, XMP_PREFIX + xmp_payload), *inherited]
    return b"\xff\xd8" + b"".join([*kept[:insertion], *metadata, *kept[insertion:]]) + tail


def _png_chunks(data: bytes) -> list[tuple[bytes, bytes, bytes]]:
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("PNG_SIGNATURE_INVALID")
    chunks: list[tuple[bytes, bytes, bytes]] = []
    cursor = len(PNG_SIGNATURE)
    while cursor + 12 <= len(data):
        length = struct.unpack(">I", data[cursor : cursor + 4])[0]
        end = cursor + 12 + length
        if end > len(data):
            raise ValueError("PNG_CHUNK_TRUNCATED")
        chunk_type = data[cursor + 4 : cursor + 8]
        payload = data[cursor + 8 : cursor + 8 + length]
        raw = data[cursor:end]
        chunks.append((chunk_type, payload, raw))
        cursor = end
        if chunk_type == b"IEND":
            if cursor != len(data):
                raise ValueError("PNG_TRAILING_DATA")
            return chunks
    raise ValueError("PNG_IEND_MISSING")


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = binascii.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", checksum)


def _png_text_key(chunk_type: bytes, payload: bytes) -> str:
    if chunk_type not in {b"tEXt", b"zTXt", b"iTXt"} or b"\x00" not in payload:
        return ""
    return payload.split(b"\x00", 1)[0].decode("latin-1", errors="replace")


def _png_itxt(key: str, value: str) -> bytes:
    payload = key.encode("latin-1") + b"\x00\x00\x00\x00\x00" + value.encode("utf-8")
    return _png_chunk(b"iTXt", payload)


def _webp_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    if len(data) < 12 or not data.startswith(WEBP_RIFF) or data[8:12] != WEBP_FORM:
        raise ValueError("WEBP_SIGNATURE_INVALID")
    declared = struct.unpack("<I", data[4:8])[0]
    if declared + 8 != len(data):
        raise ValueError("WEBP_RIFF_SIZE_INVALID")
    chunks: list[tuple[bytes, bytes]] = []
    cursor = 12
    while cursor + 8 <= len(data):
        chunk_type = data[cursor : cursor + 4]
        length = struct.unpack("<I", data[cursor + 4 : cursor + 8])[0]
        start = cursor + 8
        end = start + length
        padded_end = end + (length % 2)
        if padded_end > len(data):
            raise ValueError("WEBP_CHUNK_TRUNCATED")
        chunks.append((chunk_type, data[start:end]))
        cursor = padded_end
    if cursor != len(data):
        raise ValueError("WEBP_CHUNK_ALIGNMENT_INVALID")
    return chunks


def _webp_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    padding = b"\x00" if len(payload) % 2 else b""
    return chunk_type + struct.pack("<I", len(payload)) + payload + padding


def _uint24_le(value: int) -> bytes:
    return int(value).to_bytes(3, "little", signed=False)


def _write_webp_metadata(output_data: bytes, source_data: bytes | None, *, normalize_orientation: bool) -> bytes:
    chunks = _webp_chunks(output_data)
    kept = [(chunk_type, payload) for chunk_type, payload in chunks if chunk_type not in {b"EXIF", b"XMP "}]
    chunk_types = {chunk_type for chunk_type, _ in kept}
    if b"ICCP" not in chunk_types and source_data and source_data.startswith(WEBP_RIFF):
        for chunk_type, payload in _webp_chunks(source_data):
            if chunk_type == b"ICCP":
                kept.insert(0, (chunk_type, payload))
                chunk_types.add(chunk_type)
                break
    exif_payload = _merged_exif_bytes(output_data, source_data, normalize_orientation=normalize_orientation)[len(EXIF_PREFIX) :]
    xmp_payload = _merged_xmp(output_data, source_data)
    with Image.open(io.BytesIO(output_data)) as image:
        image.load()
        width, height = image.size
        has_alpha = "A" in image.getbands() or "transparency" in image.info
    flags = 0x08 | 0x04
    if b"ICCP" in chunk_types:
        flags |= 0x20
    if has_alpha:
        flags |= 0x10
    if b"ANIM" in chunk_types:
        flags |= 0x02
    vp8x_payload = bytes([flags, 0, 0, 0]) + _uint24_le(width - 1) + _uint24_le(height - 1)
    without_vp8x = [(chunk_type, payload) for chunk_type, payload in kept if chunk_type != b"VP8X"]
    ordered = [(b"VP8X", vp8x_payload), *without_vp8x, (b"EXIF", exif_payload), (b"XMP ", xmp_payload)]
    body = WEBP_FORM + b"".join(_webp_chunk(chunk_type, payload) for chunk_type, payload in ordered)
    return WEBP_RIFF + struct.pack("<I", len(body)) + body


def _write_png_metadata(output_data: bytes, source_data: bytes | None, *, normalize_orientation: bool) -> bytes:
    chunks = _png_chunks(output_data)
    kept: list[tuple[bytes, bytes, bytes]] = []
    existing_text_keys: set[str] = set()
    for chunk_type, payload, raw in chunks:
        key = _png_text_key(chunk_type, payload)
        if key.casefold() in {value.casefold() for value in (*_PNG_TARGET_KEYS, *_PNG_SOURCE_IDENTITY_KEYS)} or key == _PNG_XMP_KEY:
            continue
        kept.append((chunk_type, payload, raw))
        if key:
            existing_text_keys.add(key)

    inherited: list[bytes] = []
    identity_source = source_data if source_data is not None else output_data
    if identity_source.startswith(PNG_SIGNATURE):
        output_types = {chunk_type for chunk_type, _, _ in kept}
        for chunk_type, payload, raw in _png_chunks(identity_source):
            key = _png_text_key(chunk_type, payload)
            if key.casefold() in {value.casefold() for value in _PNG_SOURCE_IDENTITY_KEYS}:
                if key.casefold() not in {value.casefold() for value in existing_text_keys}:
                    inherited.append(raw)
                    existing_text_keys.add(key)
            elif key and key not in _PNG_TARGET_KEYS and key != _PNG_XMP_KEY and key not in existing_text_keys:
                inherited.append(raw)
                existing_text_keys.add(key)
            elif chunk_type in {b"tIME", b"pHYs"} and chunk_type not in output_types:
                inherited.append(raw)
                output_types.add(chunk_type)

    exif_payload = _merged_exif_bytes(output_data, source_data, normalize_orientation=normalize_orientation)
    xmp_payload = _merged_xmp(output_data, source_data)
    exif_chunk = _png_chunk(b"eXIf", exif_payload[len(EXIF_PREFIX) :])
    kept = [item for item in kept if item[0] != b"eXIf"]
    additions = [
        *inherited,
        exif_chunk,
        _png_itxt(_PNG_XMP_KEY, xmp_payload.decode("utf-8")),
        _png_itxt("Software", HDDE_SOFTWARE),
        _png_itxt("Comment", HDDE_COMMENT),
        _png_itxt("Keywords", HDDE_KEYWORDS),
    ]
    output = bytearray(PNG_SIGNATURE)
    for chunk_type, _payload, raw in kept:
        if chunk_type == b"IEND":
            output.extend(b"".join(additions))
        output.extend(raw)
    return bytes(output)


def read_hdde_metadata(path_or_bytes: str | Path | bytes) -> dict[str, Any]:
    data = path_or_bytes if isinstance(path_or_bytes, bytes) else Path(path_or_bytes).read_bytes()
    xmp = _read_xmp_fields(data)
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "JPEG":
            image.load()
        info = dict(image.info or {})
        exif = image.getexif()
        software = str(info.get("Software") or xmp.get("software") or exif.get(305) or "")
        comment = str(info.get("Comment") or info.get("Comments") or _decode_xp_text(exif.get(40092)) or xmp.get("comment") or "")
        keywords = str(info.get("Keywords") or xmp.get("keywords") or _decode_xp_text(exif.get(40094)) or "")
        title = str(info.get("Title") or xmp.get("title") or _decode_xp_text(exif.get(40091)) or exif.get(270) or "")
        author = str(info.get("Author") or xmp.get("author") or _decode_xp_text(exif.get(40093)) or exif.get(315) or "")
        return {
            "format": "JPEG" if image.format == "JPG" else str(image.format or "").upper(),
            "software": software,
            "comment": comment,
            "keywords": keywords,
            "title": title,
            "author": author,
            "copyright": exif.get(33432),
        }


def write_hdde_metadata_bytes(
    output_data: bytes,
    *,
    source_data: bytes | None = None,
    normalize_orientation: bool = False,
) -> tuple[bytes, dict[str, Any]]:
    """Add HDDE metadata without re-encoding decoded image content."""

    before = _decoded_signature(output_data)
    if output_data.startswith(PNG_SIGNATURE):
        updated = _write_png_metadata(output_data, source_data, normalize_orientation=normalize_orientation)
        method = "png_chunk_edit"
    elif output_data.startswith(JPEG_SIGNATURE):
        updated = _write_jpeg_metadata(output_data, source_data, normalize_orientation=normalize_orientation)
        method = "jpeg_segment_edit"
    elif output_data.startswith(WEBP_RIFF) and output_data[8:12] == WEBP_FORM:
        updated = _write_webp_metadata(output_data, source_data, normalize_orientation=normalize_orientation)
        method = "webp_chunk_edit"
    else:
        raise ValueError("METADATA_FORMAT_UNSUPPORTED")
    after = _decoded_signature(updated)
    pixel_unchanged = all(
        before[key] == after[key]
        for key in ("format", "size", "mode", "pixel_sha256", "alpha_sha256", "icc_sha256")
    )
    if not pixel_unchanged:
        raise ValueError("DECODED_PIXEL_CONTENT_CHANGED")
    identity_source = source_data if source_data is not None else output_data
    expected_dpi = _read_effective_dpi(identity_source)
    dpi_preserved = _dpi_equal(expected_dpi, after["effective_dpi"])
    if not dpi_preserved:
        raise ValueError("DPI_METADATA_NOT_PRESERVED")
    metadata = read_hdde_metadata(updated)
    if metadata["software"] != HDDE_SOFTWARE or metadata["comment"] != HDDE_COMMENT or metadata["keywords"] != HDDE_KEYWORDS:
        raise ValueError("HDDE_METADATA_VERIFY_FAILED")
    iptc_conflicts = _iptc_contract_conflicts(updated)
    if iptc_conflicts:
        raise ValueError("IPTC_METADATA_CONTRACT_FAILED:" + ",".join(iptc_conflicts))
    xmp_conflicts = _xmp_contract_conflicts(updated)
    if xmp_conflicts:
        raise ValueError("XMP_METADATA_CONTRACT_FAILED:" + ",".join(xmp_conflicts))
    source_identity = read_hdde_metadata(identity_source)
    if metadata["title"] != source_identity["title"] or metadata["author"] != source_identity["author"]:
        raise ValueError("SOURCE_IDENTITY_METADATA_NOT_PRESERVED")
    identity_exif = _read_exif(identity_source)
    candidate_exif = _read_exif(output_data)
    source_orientation = identity_exif.get(274)
    output_orientation = _read_exif(updated).get(274)
    expected_orientation = (
        1
        if normalize_orientation and (len(identity_exif) or len(candidate_exif))
        else source_orientation
    )
    if output_orientation != expected_orientation:
        raise ValueError("SOURCE_ORIENTATION_NOT_PRESERVED")
    source_facts = _source_metadata_facts(source_data)
    output_facts = _source_metadata_facts(updated)
    source_metadata_preserved = all(output_facts.get(key) == value for key, value in source_facts.items())
    if not source_metadata_preserved:
        raise ValueError("SOURCE_METADATA_NOT_PRESERVED")
    return updated, {
        "written": True,
        "format": after["format"],
        "method": method,
        "software": HDDE_SOFTWARE,
        "comment": HDDE_COMMENT,
        "keywords": HDDE_KEYWORDS,
        "product_version": APP_VERSION,
        "decoded_pixel_content_unchanged": True,
        "alpha_unchanged": before["alpha_sha256"] == after["alpha_sha256"],
        "icc_unchanged": before["icc_sha256"] == after["icc_sha256"],
        "dpi_unchanged": dpi_preserved,
        "orientation_preserved": output_orientation == expected_orientation,
        "title_preserved": metadata["title"] == source_identity["title"],
        "author_preserved": metadata["author"] == source_identity["author"],
        "source_metadata_preserved": source_metadata_preserved,
        "source_metadata_checked_fields": sorted(source_facts),
        "iptc_controlled_conflicts": len(iptc_conflicts),
        "xmp_controlled_conflicts": len(xmp_conflicts),
        "file_sha256_before": _sha256(output_data),
        "file_sha256_after": _sha256(updated),
    }


def write_hdde_metadata(
    output_path: str | Path,
    *,
    source_path: str | Path | None = None,
    normalize_orientation: bool = False,
) -> dict[str, Any]:
    """Augment a private image candidate and verify it before formal publication."""

    target = Path(output_path)
    with target.open("r+b") as handle:
        output_data = handle.read()
        if source_path is not None and Path(source_path).resolve() == target.resolve():
            source_data = output_data
        else:
            source_data = Path(source_path).read_bytes() if source_path else None
        updated, report = write_hdde_metadata_bytes(
            output_data,
            source_data=source_data,
            normalize_orientation=normalize_orientation,
        )
        handle.seek(0)
        written = handle.write(updated)
        if written != len(updated):
            raise OSError("PRIVATE_METADATA_WRITE_INCOMPLETE")
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())
    return report
