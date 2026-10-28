"""Bounded image metadata for Output Center; never decodes source pixels."""

import struct
from pathlib import Path


def read_image_header(path: Path) -> dict[str, int | str]:
    with path.open("rb") as stream:
        header = stream.read(32)
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            if len(header) < 29 or header[8:16] != b"\x00\x00\x00\rIHDR":
                raise ValueError("invalid PNG header")
            width, height = struct.unpack(">II", header[16:24])
            image_format = "PNG"
        elif header[:2] == b"\xff\xd8":
            stream.seek(2)
            # Skip APP/EXIF segments without reading or decoding their payload.
            # A bounded header budget also rejects malformed marker streams.
            while stream.tell() < 1024 * 1024:
                if stream.read(1) != b"\xff":
                    raise ValueError("invalid JPEG marker")
                marker = stream.read(1)
                while marker == b"\xff" and stream.tell() < 1024 * 1024:
                    marker = stream.read(1)
                if not marker or marker[0] in (0xD9, 0xDA):
                    raise ValueError("JPEG dimensions unavailable")
                if marker[0] in (0x01, *range(0xD0, 0xD9)):
                    continue
                raw_length = stream.read(2)
                if len(raw_length) != 2:
                    raise ValueError("truncated JPEG header")
                length = int.from_bytes(raw_length, "big")
                if length < 2:
                    raise ValueError("invalid JPEG segment")
                if marker[0] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    frame = stream.read(5)
                    if length < 8 or len(frame) != 5:
                        raise ValueError("invalid JPEG frame")
                    height, width = struct.unpack(">HH", frame[1:5])
                    break
                stream.seek(length - 2, 1)
            else:
                raise ValueError("JPEG header exceeds metadata budget")
            image_format = "JPEG"
        elif header[:4] == b"RIFF" and header[8:12] == b"WEBP" and len(header) >= 30:
            if header[12:16] == b"VP8X":
                width = int.from_bytes(header[24:27], "little") + 1
                height = int.from_bytes(header[27:30], "little") + 1
            elif header[12:16] == b"VP8L" and header[20] == 0x2F:
                bits = int.from_bytes(header[21:25], "little")
                width, height = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            elif header[12:16] == b"VP8 " and header[23:26] == b"\x9d\x01\x2a":
                width, height = struct.unpack("<HH", header[26:30])
                width, height = width & 0x3FFF, height & 0x3FFF
            else:
                raise ValueError("invalid WebP header")
            image_format = "WEBP"
        else:
            raise ValueError("unsupported output image header")
    if width <= 0 or height <= 0:
        raise ValueError("invalid image dimensions")
    return {"width": width, "height": height, "format": image_format}
