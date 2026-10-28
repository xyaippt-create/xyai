from __future__ import annotations

import hashlib
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageCms, PngImagePlugin

from engine.output.filename_policy import (
    FEATURE_1080P,
    FEATURE_4K,
    FEATURE_COLOR,
    FEATURE_COMPRESSION,
    FEATURE_RETOUCH,
    FEATURE_WATERMARK,
    build_output_filename,
    build_output_path,
    resolve_collision_path,
)
from engine.output.metadata_writer import (
    HDDE_COMMENT,
    HDDE_KEYWORDS,
    HDDE_SOFTWARE,
    read_hdde_metadata,
    write_hdde_metadata,
)
import engine.output.publish_safety as publish_safety
import engine.output.metadata_writer as metadata_writer
from engine.output.publish_safety import (
    PRIVATE_OUTPUT_PREFIX,
    OutputMetadataStageError,
    publish_image_bytes_with_metadata,
)
from runtime import APP_VERSION


FIXED_MOMENT = datetime(2026, 9, 1, 10, 20, 30)


_WINDOWS_EXTERNAL_WRITE_ATTEMPT = r"""
import ctypes
import json
import sys
from ctypes import wintypes

GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
create_file = kernel32.CreateFileW
create_file.argtypes = (
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
)
create_file.restype = wintypes.HANDLE
write_file = kernel32.WriteFile
write_file.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p)
write_file.restype = wintypes.BOOL
close_handle = kernel32.CloseHandle
close_handle.argtypes = (wintypes.HANDLE,)
close_handle.restype = wintypes.BOOL

handle = create_file(
    sys.argv[1],
    GENERIC_WRITE,
    FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
    None,
    OPEN_EXISTING,
    0,
    None,
)
if handle == INVALID_HANDLE_VALUE:
    print(json.dumps({"opened": False, "written": False, "error": ctypes.get_last_error()}))
    raise SystemExit(0)

payload = bytes.fromhex(sys.argv[2])
written = wintypes.DWORD()
ok = bool(write_file(handle, payload, len(payload), ctypes.byref(written), None))
error = 0 if ok else ctypes.get_last_error()
close_handle(handle)
print(json.dumps({"opened": True, "written": ok, "bytes_written": written.value, "error": error}))
"""


def decoded_facts(path: Path) -> dict[str, object]:
    with Image.open(path) as image:
        image.load()
        rgba = image.convert("RGBA")
        return {
            "size": image.size,
            "mode": image.mode,
            "pixels": hashlib.sha256(image.tobytes()).hexdigest(),
            "alpha": hashlib.sha256(rgba.getchannel("A").tobytes()).hexdigest(),
            "icc": hashlib.sha256(image.info.get("icc_profile") or b"").hexdigest(),
        }


def _iptc_dataset(record: int, dataset: int, value: bytes | str) -> bytes:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return b"\x1c" + bytes((record, dataset)) + struct.pack(">H", len(payload)) + payload


def _photoshop_iptc_segment(datasets: list[bytes]) -> bytes:
    iptc = b"".join(datasets)
    resource = b"8BIM" + struct.pack(">H", 0x0404) + b"\x00\x00" + struct.pack(">I", len(iptc)) + iptc
    if len(iptc) % 2:
        resource += b"\x00"
    return metadata_writer._jpeg_segment(0xED, b"Photoshop 3.0\x00" + resource)


def _jpeg_with_segment(data: bytes, segment: bytes) -> bytes:
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("JPEG_SIGNATURE_INVALID")
    return data[:2] + segment + data[2:]


class UnifiedFilenamePolicyTests(unittest.TestCase):
    def test_all_formal_feature_short_names(self) -> None:
        cases = {
            FEATURE_4K: "test_影界4K_260901.png",
            FEATURE_1080P: "test_影界1080P_260901.png",
            FEATURE_COLOR: "test_影界校色_260901.png",
            FEATURE_RETOUCH: "test_影界修复_260901.png",
            FEATURE_COMPRESSION: "test_影界压缩_260901.jpg",
            FEATURE_WATERMARK: "test_影界水印_260901.png",
        }
        for feature, expected in cases.items():
            extension = ".jpg" if feature == FEATURE_COMPRESSION else ".png"
            self.assertEqual(build_output_filename("test.png", feature, extension, moment=FIXED_MOMENT), expected)

    def test_collision_sequence_starts_at_02_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = build_output_path(root, "客户照片01.png", FEATURE_4K, ".png", moment=FIXED_MOMENT)
            self.assertEqual(first.name, "客户照片01_影界4K_260901.png")
            first.write_bytes(b"protected-first")
            second = build_output_path(root, "客户照片01.png", FEATURE_4K, ".png", moment=FIXED_MOMENT)
            self.assertEqual(second.name, "客户照片01_影界4K_260901_02.png")
            second.write_bytes(b"protected-second")
            third = build_output_path(root, "客户照片01.png", FEATURE_4K, ".png", moment=FIXED_MOMENT)
            self.assertEqual(third.name, "客户照片01_影界4K_260901_03.png")
            self.assertEqual(first.read_bytes(), b"protected-first")
            self.assertEqual(second.read_bytes(), b"protected-second")

    def test_trusted_original_wins_but_untrusted_name_is_never_guessed_or_stripped(self) -> None:
        stacked = "客户_影界校色_260831_影界4K_260901.png"
        safe = build_output_filename(stacked, FEATURE_RETOUCH, ".png", moment=FIXED_MOMENT)
        trusted = build_output_filename(
            stacked,
            FEATURE_RETOUCH,
            ".png",
            trusted_original_filename="客户.png",
            moment=FIXED_MOMENT,
        )
        self.assertEqual(safe, "客户_影界校色_260831_影界4K_260901_影界修复_260901.png")
        self.assertEqual(trusted, "客户_影界修复_260901.png")

    def test_delivery_collision_preserves_source_name(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            protected = root / "客户_影界4K_260901.png"
            protected.write_bytes(b"protected")
            self.assertEqual(resolve_collision_path(root, protected.name).name, "客户_影界4K_260901_02.png")
            self.assertEqual(protected.read_bytes(), b"protected")


class UnifiedMetadataWriterTests(unittest.TestCase):
    @staticmethod
    def _srgb_profile() -> bytes:
        return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()

    def _source_exif(self) -> Image.Exif:
        exif = Image.Exif()
        exif[271] = "HDDE Test Camera"
        exif[272] = "Model One"
        exif[315] = "Original Photographer"
        exif[33432] = "Original Copyright"
        exif[36867] = "2026:08:31 10:20:30"
        exif[42036] = "Test Lens"
        return exif

    def test_jpeg_metadata_is_added_without_pixel_or_author_copyright_change(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "test.jpg"
            image = Image.new("RGB", (31, 19), (80, 120, 160))
            image.putpixel((3, 4), (17, 99, 201))
            image.save(path, format="JPEG", quality=93, subsampling=0, exif=self._source_exif())
            before = decoded_facts(path)
            before_file_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            report = write_hdde_metadata(path, source_path=path)
            after = decoded_facts(path)
            metadata = read_hdde_metadata(path)
            with Image.open(path) as opened:
                exif = opened.getexif()
                self.assertEqual(exif.get(271), "HDDE Test Camera")
                self.assertEqual(exif.get(272), "Model One")
                self.assertEqual(exif.get(315), "Original Photographer")
                self.assertEqual(exif.get(33432), "Original Copyright")
                self.assertEqual(exif.get(36867), "2026:08:31 10:20:30")
                self.assertEqual(exif.get(42036), "Test Lens")
            self.assertEqual(before, after)
            self.assertNotEqual(before_file_sha, hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(metadata["software"], f"影界 HDDE {APP_VERSION}")
            self.assertEqual(metadata["comment"], HDDE_COMMENT)
            self.assertEqual(metadata["keywords"], HDDE_KEYWORDS)
            self.assertEqual(metadata["author"], "Original Photographer")
            self.assertEqual(metadata["copyright"], "Original Copyright")
            self.assertTrue(report["decoded_pixel_content_unchanged"])
            self.assertTrue(report["source_metadata_preserved"])

    def test_png_metadata_is_added_without_pixel_alpha_icc_or_existing_text_change(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "test.png"
            pnginfo = PngImagePlugin.PngInfo()
            pnginfo.add_itxt("Author", "Original Illustrator")
            pnginfo.add_itxt("Copyright", "Original PNG Copyright")
            image = Image.new("RGBA", (23, 17), (20, 40, 60, 128))
            image.putpixel((2, 3), (200, 100, 50, 7))
            image.save(path, format="PNG", pnginfo=pnginfo, exif=self._source_exif())
            before = decoded_facts(path)
            report = write_hdde_metadata(path, source_path=path, normalize_orientation=True)
            after = decoded_facts(path)
            metadata = read_hdde_metadata(path)
            with Image.open(path) as opened:
                opened.load()
                self.assertEqual(opened.info.get("Author"), "Original Illustrator")
                self.assertEqual(opened.info.get("Copyright"), "Original PNG Copyright")
                exif = opened.getexif()
                self.assertEqual(exif.get(315), "Original Photographer")
                self.assertEqual(exif.get(33432), "Original Copyright")
            self.assertEqual(before, after)
            self.assertEqual(metadata["software"], HDDE_SOFTWARE)
            self.assertEqual(metadata["comment"], HDDE_COMMENT)
            self.assertEqual(metadata["keywords"], HDDE_KEYWORDS)
            self.assertTrue(report["alpha_unchanged"])
            self.assertTrue(report["icc_unchanged"])

    def test_jpeg_to_png_source_dpi_restore_is_not_reported_as_pixel_change(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source-200dpi.jpg"
            target = root / "formal-4k.png"
            exif = self._source_exif()
            exif[282] = 200
            exif[283] = 200
            exif[296] = 2
            Image.new("RGB", (37, 23), (41, 81, 121)).save(
                source,
                format="JPEG",
                quality=94,
                subsampling=0,
                exif=exif,
                dpi=(200, 200),
            )
            candidate = io.BytesIO()
            image = Image.new("RGB", (74, 46), (43, 83, 123))
            image.putpixel((7, 11), (221, 31, 71))
            image.save(candidate, format="PNG", compress_level=6, dpi=(200, 200))
            before_pixels = hashlib.sha256(image.tobytes()).hexdigest()

            published, report, _validation = publish_image_bytes_with_metadata(
                candidate.getvalue(),
                target,
                source_data=source.read_bytes(),
                normalize_orientation=True,
            )

            with Image.open(published) as output:
                output.load()
                self.assertEqual(hashlib.sha256(output.tobytes()).hexdigest(), before_pixels)
                self.assertAlmostEqual(output.info["dpi"][0], 200, places=2)
                self.assertAlmostEqual(output.info["dpi"][1], 200, places=2)
                self.assertEqual(float(output.getexif()[282]), 200)
                self.assertEqual(float(output.getexif()[283]), 200)
                self.assertEqual(output.getexif()[296], 2)
            self.assertTrue(report["decoded_pixel_content_unchanged"])
            self.assertTrue(report["dpi_unchanged"])

    def test_metadata_stage_still_fails_closed_on_real_pixel_change(self) -> None:
        candidate = io.BytesIO()
        Image.new("RGB", (19, 13), (23, 63, 103)).save(candidate, format="PNG")

        def change_pixel(data: bytes, _source_data: bytes | None, *, normalize_orientation: bool) -> bytes:
            del normalize_orientation
            with Image.open(io.BytesIO(data)) as opened:
                opened.load()
                changed = opened.copy()
            changed.putpixel((3, 5), (241, 17, 91))
            output = io.BytesIO()
            changed.save(output, format="PNG")
            return output.getvalue()

        with patch.object(metadata_writer, "_write_png_metadata", side_effect=change_pixel):
            with self.assertRaisesRegex(ValueError, "^DECODED_PIXEL_CONTENT_CHANGED$"):
                metadata_writer.write_hdde_metadata_bytes(candidate.getvalue())

    def test_webp_metadata_is_added_without_pixel_or_alpha_change(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "test.webp"
            image = Image.new("RGBA", (21, 15), (20, 90, 160, 127))
            image.putpixel((4, 5), (201, 30, 71, 9))
            image.save(path, format="WEBP", lossless=True, exif=self._source_exif())
            before = decoded_facts(path)
            report = write_hdde_metadata(path, source_path=path, normalize_orientation=True)
            after = decoded_facts(path)
            metadata = read_hdde_metadata(path)
            self.assertEqual(before, after)
            self.assertEqual(metadata["software"], HDDE_SOFTWARE)
            self.assertEqual(metadata["comment"], HDDE_COMMENT)
            self.assertEqual(metadata["keywords"], HDDE_KEYWORDS)
            self.assertTrue(report["decoded_pixel_content_unchanged"])

    def test_real_formal_file_case_a_keeps_missing_title_and_author_empty(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source-without-title-author.jpg"
            target = root / "formal-case-a.jpg"
            exif = Image.Exif()
            exif[271] = "HDDE Case A Camera"
            exif[274] = 6
            image = Image.new("RGB", (37, 23), (31, 91, 151))
            image.putpixel((5, 7), (221, 41, 73))
            image.save(
                source,
                format="JPEG",
                quality=94,
                subsampling=0,
                exif=exif,
                icc_profile=self._srgb_profile(),
                dpi=(144, 144),
            )
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            before = decoded_facts(source)

            published, report, _validation = publish_image_bytes_with_metadata(
                source.read_bytes(),
                target,
                source_data=source.read_bytes(),
                normalize_orientation=False,
            )

            metadata = read_hdde_metadata(published)
            self.assertEqual(metadata["title"], "")
            self.assertEqual(metadata["author"], "")
            self.assertEqual(metadata["keywords"], "影界 HDDE")
            self.assertEqual(metadata["comment"], "由影界 HDDE 处理｜联系邮箱：xueyaippt@outlook.com")
            self.assertEqual(metadata["software"], f"影界 HDDE {APP_VERSION}")
            self.assertNotIn(b"xueyaippt@outlook.com", metadata_writer._extract_xmp(published.read_bytes()))
            self.assertEqual(before, decoded_facts(published))
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_sha)
            self.assertTrue(report["icc_unchanged"])
            self.assertTrue(report["dpi_unchanged"])
            self.assertTrue(report["orientation_preserved"])

    def test_real_formal_file_case_b_preserves_source_title_author_and_technical_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source-with-title-author.png"
            target = root / "formal-case-b.png"
            title = "Original Delivery Title"
            author = "Original Photographer"
            legacy_contact = "\n".join(
                ("由影界 HDDE 处理", "\u5fae\u4fe1\uff1a" + "xuey" + "_aippt", "邮箱：xueyaippt@outlook.com")
            )
            source_xmp = f"""<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dc="http://purl.org/dc/elements/1.1/">
<rdf:RDF><rdf:Description rdf:about=""><dc:title><rdf:Alt><rdf:li xml:lang="x-default">{title}</rdf:li></rdf:Alt></dc:title><dc:creator><rdf:Seq><rdf:li>{author}</rdf:li></rdf:Seq></dc:creator><dc:description><rdf:Alt><rdf:li xml:lang="x-default">{legacy_contact}</rdf:li></rdf:Alt></dc:description></rdf:Description></rdf:RDF></x:xmpmeta>"""
            pnginfo = PngImagePlugin.PngInfo()
            pnginfo.add_itxt("Title", title)
            pnginfo.add_itxt("Author", author)
            pnginfo.add_itxt("XML:com.adobe.xmp", source_xmp)
            exif = Image.Exif()
            exif[270] = title
            exif[315] = author
            exif[274] = 6
            exif[36867] = "2026:09:02 09:30:00"
            image = Image.new("RGBA", (29, 31), (42, 82, 122, 173))
            image.putpixel((4, 8), (203, 33, 63, 19))
            image.save(
                source,
                format="PNG",
                pnginfo=pnginfo,
                exif=exif,
                icc_profile=self._srgb_profile(),
                dpi=(180, 180),
            )
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            before = decoded_facts(source)

            published, report, _validation = publish_image_bytes_with_metadata(
                source.read_bytes(),
                target,
                source_data=source.read_bytes(),
                normalize_orientation=False,
            )

            metadata = read_hdde_metadata(published)
            output_xmp = metadata_writer._extract_xmp(published.read_bytes())
            self.assertEqual(metadata["title"], title)
            self.assertEqual(metadata["author"], author)
            self.assertEqual(metadata["keywords"], "影界 HDDE")
            self.assertEqual(metadata["comment"], "由影界 HDDE 处理｜联系邮箱：xueyaippt@outlook.com")
            self.assertEqual(metadata["software"], f"影界 HDDE {APP_VERSION}")
            self.assertIn(title.encode("utf-8"), output_xmp)
            self.assertIn(author.encode("utf-8"), output_xmp)
            self.assertNotIn(b"xuey_aippt", output_xmp)
            self.assertNotIn(b"xueyaippt@outlook.com", output_xmp)
            self.assertEqual(before, decoded_facts(published))
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_sha)
            self.assertTrue(report["icc_unchanged"])
            self.assertTrue(report["dpi_unchanged"])
            self.assertTrue(report["orientation_preserved"])
            self.assertTrue(report["title_preserved"])
            self.assertTrue(report["author_preserved"])

    def test_case_c_jpeg_iptc_conflicts_are_governed_without_losing_user_iptc(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source-iptc-conflict.jpg"
            target = root / "formal-case-c.jpg"
            exif = self._source_exif()
            exif[274] = 6
            Image.new("RGB", (41, 27), (63, 103, 143)).save(
                source,
                format="JPEG",
                quality=94,
                subsampling=0,
                exif=exif,
                icc_profile=self._srgb_profile(),
                dpi=(150, 150),
            )
            source.write_bytes(
                _jpeg_with_segment(
                    source.read_bytes(),
                    _photoshop_iptc_segment(
                        [
                            _iptc_dataset(1, 90, b"\x1b%G"),
                            _iptc_dataset(2, 25, "客户标签"),
                            _iptc_dataset(2, 25, "影界 HDDE V0.5.7"),
                            _iptc_dataset(2, 65, "影界 HDDE V0.5.7"),
                            _iptc_dataset(2, 70, "V0.5.7"),
                            _iptc_dataset(2, 80, "Original Byline"),
                            _iptc_dataset(2, 92, "Original Location"),
                            _iptc_dataset(2, 116, "Original IPTC Copyright"),
                            _iptc_dataset(2, 120, "Original Customer Caption"),
                            _iptc_dataset(
                                2,
                                40,
                                "由影界 HDDE 处理\n微信：xuey_aippt\n邮箱：xueyaippt@outlook.com",
                            ),
                        ]
                    ),
                )
            )
            source_data = source.read_bytes()
            before = decoded_facts(source)

            published, report, _validation = publish_image_bytes_with_metadata(
                source_data,
                target,
                source_data=source_data,
                normalize_orientation=False,
            )

            published_data = published.read_bytes()
            self.assertNotIn("V0.5.7", published_data.decode("utf-8", errors="ignore"))
            self.assertNotIn("xuey_aippt", published_data.decode("utf-8", errors="ignore"))
            self.assertNotIn("微信", published_data.decode("utf-8", errors="ignore"))
            self.assertTrue(metadata_writer._iptc_contract_conflicts(source_data))
            datasets = metadata_writer._read_iptc_datasets(published_data)
            decoded = [(record, dataset, value.decode("utf-8", errors="replace")) for record, dataset, value in datasets]
            self.assertIn((2, 25, "客户标签"), decoded)
            self.assertIn((2, 80, "Original Byline"), decoded)
            self.assertIn((2, 92, "Original Location"), decoded)
            self.assertIn((2, 116, "Original IPTC Copyright"), decoded)
            self.assertIn((2, 120, "Original Customer Caption"), decoded)
            self.assertIn((2, 25, HDDE_KEYWORDS), decoded)
            self.assertIn((2, 65, HDDE_SOFTWARE), decoded)
            self.assertIn((2, 70, APP_VERSION), decoded)
            self.assertFalse(metadata_writer._iptc_contract_conflicts(published_data))
            self.assertEqual(read_hdde_metadata(published)["comment"], HDDE_COMMENT)
            self.assertEqual(before, decoded_facts(published))
            self.assertTrue(report["icc_unchanged"])
            self.assertTrue(report["dpi_unchanged"])
            self.assertTrue(report["orientation_preserved"])

    def test_case_d_all_xmp_descriptions_are_governed_without_flattening_user_data(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source-multi-description.png"
            target = root / "formal-case-d.png"
            source_xmp = """<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmlns:tiff="http://ns.adobe.com/tiff/1.0/" xmlns:customer="urn:hdde:test:customer">
<rdf:RDF>
  <rdf:Description rdf:about="" customer:Workflow="User preserved workflow">
    <dc:title><rdf:Alt><rdf:li xml:lang="x-default">Original Multi XMP Title</rdf:li></rdf:Alt></dc:title>
    <dc:creator><rdf:Seq><rdf:li>Original Multi XMP Author</rdf:li></rdf:Seq></dc:creator>
    <dc:subject><rdf:Bag><rdf:li>影界 HDDE</rdf:li></rdf:Bag></dc:subject>
  </rdf:Description>
  <rdf:Description rdf:about="urn:legacy" xmp:CreatorTool="影界 HDDE V0.5.7" tiff:Software="影界 HDDE V0.5.7">
    <dc:subject><rdf:Bag><rdf:li>影界 HDDE V0.5.7</rdf:li></rdf:Bag></dc:subject>
    <dc:description><rdf:Alt><rdf:li xml:lang="x-default">由影界 HDDE 处理\n微信：xuey_aippt\n邮箱：xueyaippt@outlook.com</rdf:li></rdf:Alt></dc:description>
    <customer:ReviewState>Approved by customer</customer:ReviewState>
  </rdf:Description>
</rdf:RDF></x:xmpmeta>"""
            pnginfo = PngImagePlugin.PngInfo()
            pnginfo.add_itxt("XML:com.adobe.xmp", source_xmp)
            exif = self._source_exif()
            exif[274] = 6
            Image.new("RGBA", (33, 25), (72, 112, 152, 191)).save(
                source,
                format="PNG",
                pnginfo=pnginfo,
                exif=exif,
                icc_profile=self._srgb_profile(),
                dpi=(180, 180),
            )
            source_data = source.read_bytes()
            before = decoded_facts(source)

            published, report, _validation = publish_image_bytes_with_metadata(
                source_data,
                target,
                source_data=source_data,
                normalize_orientation=False,
            )

            published_data = published.read_bytes()
            self.assertTrue(metadata_writer._xmp_contract_conflicts(source_data))
            packet = metadata_writer._extract_xmp(published_data)
            root_element = ET.fromstring(packet.decode("utf-8"))
            descriptions = root_element.findall(
                ".//{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description"
            )
            subjects = root_element.findall(
                ".//{http://purl.org/dc/elements/1.1/}subject/{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Bag/{http://www.w3.org/1999/02/22-rdf-syntax-ns#}li"
            )
            creator_tools = [
                value
                for description in descriptions
                for value in [description.get("{http://ns.adobe.com/xap/1.0/}CreatorTool")]
                if value
            ]
            self.assertEqual(len(descriptions), 2)
            self.assertEqual([item.text for item in subjects], [HDDE_KEYWORDS])
            self.assertEqual(creator_tools, [HDDE_SOFTWARE])
            self.assertEqual(
                descriptions[0].get("{urn:hdde:test:customer}Workflow"),
                "User preserved workflow",
            )
            self.assertEqual(
                descriptions[1].find("{urn:hdde:test:customer}ReviewState").text,
                "Approved by customer",
            )
            self.assertFalse(metadata_writer._xmp_contract_conflicts(published_data))
            self.assertNotIn(b"V0.5.7", packet)
            self.assertNotIn(b"xuey_aippt", packet)
            self.assertNotIn("微信".encode("utf-8"), packet)
            self.assertNotIn(b"xueyaippt@outlook.com", packet)
            metadata = read_hdde_metadata(published)
            self.assertEqual(metadata["title"], "Original Multi XMP Title")
            self.assertEqual(metadata["author"], "Original Multi XMP Author")
            self.assertEqual(metadata["keywords"], HDDE_KEYWORDS)
            self.assertEqual(metadata["software"], HDDE_SOFTWARE)
            self.assertEqual(metadata["comment"], HDDE_COMMENT)
            self.assertEqual(before, decoded_facts(published))
            self.assertTrue(report["icc_unchanged"])
            self.assertTrue(report["dpi_unchanged"])
            self.assertTrue(report["orientation_preserved"])

    def test_case_e_user_xmp_subjects_are_preserved_and_hdde_tag_is_unique(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source-user-subjects.png"
            target = root / "formal-case-e.png"
            source_xmp = """<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dc="http://purl.org/dc/elements/1.1/">
<rdf:RDF><rdf:Description rdf:about=""><dc:subject><rdf:Bag>
<rdf:li>商业摄影</rdf:li><rdf:li>客户A</rdf:li><rdf:li>年度报告</rdf:li><rdf:li>影界 HDDE V0.5.7</rdf:li>
</rdf:Bag></dc:subject></rdf:Description></rdf:RDF></x:xmpmeta>"""
            pnginfo = PngImagePlugin.PngInfo()
            pnginfo.add_itxt("XML:com.adobe.xmp", source_xmp)
            Image.new("RGB", (35, 23), (83, 123, 163)).save(source, format="PNG", pnginfo=pnginfo)
            source_data = source.read_bytes()

            published, _report, _validation = publish_image_bytes_with_metadata(
                source_data,
                target,
                source_data=source_data,
            )

            packet = metadata_writer._extract_xmp(published.read_bytes())
            root_element = ET.fromstring(packet.decode("utf-8"))
            subjects = [
                str(item.text or "")
                for item in root_element.findall(
                    ".//{http://purl.org/dc/elements/1.1/}subject/{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Bag/{http://www.w3.org/1999/02/22-rdf-syntax-ns#}li"
                )
            ]
            for user_subject in ("商业摄影", "客户A", "年度报告"):
                self.assertIn(user_subject, subjects)
            self.assertEqual(subjects.count(HDDE_KEYWORDS), 1)
            self.assertNotIn("影界 HDDE V0.5.7", subjects)
            self.assertFalse(metadata_writer._xmp_contract_conflicts(published.read_bytes()))
            self.assertEqual(read_hdde_metadata(published)["keywords"], HDDE_KEYWORDS)

    def test_case_f_bare_contact_email_is_removed_from_non_comment_xmp_and_iptc(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source-bare-email.jpg"
            target = root / "formal-case-f.jpg"
            Image.new("RGB", (39, 25), (93, 133, 173)).save(source, format="JPEG", quality=94, subsampling=0)
            source_xmp = b"""<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:customer="urn:hdde:test:customer">
<rdf:RDF><rdf:Description rdf:about=""/><rdf:Description rdf:about="urn:legacy"><customer:LegacyContact>xueyaippt@outlook.com</customer:LegacyContact><customer:Workflow>Customer workflow retained</customer:Workflow></rdf:Description></rdf:RDF></x:xmpmeta>"""
            with_xmp = _jpeg_with_segment(
                source.read_bytes(),
                metadata_writer._jpeg_segment(0xE1, metadata_writer.XMP_PREFIX + source_xmp),
            )
            source_data = _jpeg_with_segment(
                with_xmp,
                _photoshop_iptc_segment(
                    [
                        _iptc_dataset(1, 90, b"\x1b%G"),
                        _iptc_dataset(2, 118, "xueyaippt@outlook.com"),
                        _iptc_dataset(2, 120, "Customer caption retained"),
                    ]
                ),
            )
            source.write_bytes(source_data)

            self.assertIn(
                "XMP_LEGACY_CONTACT_PROPERTY_LegacyContact",
                metadata_writer._xmp_contract_conflicts(source_data),
            )
            self.assertIn(
                "IPTC_LEGACY_CONTACT_2_118",
                metadata_writer._iptc_contract_conflicts(source_data),
            )

            published, _report, _validation = publish_image_bytes_with_metadata(
                source_data,
                target,
                source_data=source_data,
            )

            published_data = published.read_bytes()
            packet = metadata_writer._extract_xmp(published_data)
            datasets = [
                (record, dataset, value.decode("utf-8", errors="replace"))
                for record, dataset, value in metadata_writer._read_iptc_datasets(published_data)
            ]
            self.assertNotIn(b"xueyaippt@outlook.com", packet)
            self.assertNotIn((2, 118, "xueyaippt@outlook.com"), datasets)
            self.assertIn((2, 120, "Customer caption retained"), datasets)
            self.assertIn(b"Customer workflow retained", packet)
            self.assertEqual(read_hdde_metadata(published)["comment"], HDDE_COMMENT)
            self.assertFalse(metadata_writer._xmp_contract_conflicts(published_data))
            self.assertFalse(metadata_writer._iptc_contract_conflicts(published_data))

    def test_case_f2_bare_contact_email_is_removed_from_xmp_subject(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source-subject-email.png"
            target = root / "formal-case-f2.png"
            source_xmp = """<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dc="http://purl.org/dc/elements/1.1/">
<rdf:RDF><rdf:Description rdf:about=""><dc:subject><rdf:Bag>
<rdf:li>商业摄影</rdf:li><rdf:li>xueyaippt@outlook.com</rdf:li><rdf:li>影界 HDDE</rdf:li>
</rdf:Bag></dc:subject></rdf:Description></rdf:RDF></x:xmpmeta>"""
            pnginfo = PngImagePlugin.PngInfo()
            pnginfo.add_itxt("XML:com.adobe.xmp", source_xmp)
            Image.new("RGB", (41, 27), (98, 138, 178)).save(source, format="PNG", pnginfo=pnginfo)
            source_data = source.read_bytes()

            published, _report, _validation = publish_image_bytes_with_metadata(
                source_data,
                target,
                source_data=source_data,
            )

            self.assertEqual(published, target)
            self.assertTrue(published.is_file())
            self.assertIn(b"xueyaippt@outlook.com", source.read_bytes())
            packet = metadata_writer._extract_xmp(published.read_bytes())
            root_element = ET.fromstring(packet.decode("utf-8"))
            subjects = [
                str(item.text or "")
                for item in root_element.findall(
                    ".//{http://purl.org/dc/elements/1.1/}subject/{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Bag/{http://www.w3.org/1999/02/22-rdf-syntax-ns#}li"
                )
            ]
            self.assertIn("商业摄影", subjects)
            self.assertNotIn("xueyaippt@outlook.com", subjects)
            self.assertEqual(subjects.count(HDDE_KEYWORDS), 1)
            self.assertEqual(read_hdde_metadata(published)["comment"], HDDE_COMMENT)
            self.assertFalse(metadata_writer._xmp_contract_conflicts(published.read_bytes()))

    def test_case_g_iptc_keyword_containing_product_name_is_not_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source-user-product-keyword.jpg"
            target = root / "formal-case-g.jpg"
            Image.new("RGB", (43, 29), (103, 143, 183)).save(source, format="JPEG", quality=94, subsampling=0)
            source_data = _jpeg_with_segment(
                source.read_bytes(),
                _photoshop_iptc_segment(
                    [
                        _iptc_dataset(1, 90, b"\x1b%G"),
                        _iptc_dataset(2, 25, "影界 HDDE 摄影项目"),
                        _iptc_dataset(2, 25, "影界 HDDE V0.5.7"),
                    ]
                ),
            )
            source.write_bytes(source_data)

            published, _report, _validation = publish_image_bytes_with_metadata(
                source_data,
                target,
                source_data=source_data,
            )

            datasets = [
                (record, dataset, value.decode("utf-8", errors="replace"))
                for record, dataset, value in metadata_writer._read_iptc_datasets(published.read_bytes())
            ]
            self.assertIn((2, 25, "影界 HDDE 摄影项目"), datasets)
            self.assertIn((2, 25, HDDE_KEYWORDS), datasets)
            self.assertEqual(sum(1 for item in datasets if item == (2, 25, HDDE_KEYWORDS)), 1)
            self.assertNotIn((2, 25, "影界 HDDE V0.5.7"), datasets)
            self.assertFalse(metadata_writer._iptc_contract_conflicts(published.read_bytes()))


class NoOverwritePublishSafetyTests(unittest.TestCase):
    @staticmethod
    def _png_bytes(color: tuple[int, int, int, int] = (20, 90, 160, 127)) -> bytes:
        stream = io.BytesIO()
        Image.new("RGBA", (17, 13), color).save(stream, format="PNG")
        return stream.getvalue()

    @staticmethod
    def _private_outputs(root: Path) -> list[Path]:
        return list(root.glob(f"{PRIVATE_OUTPUT_PREFIX}*"))

    @staticmethod
    def _attempt_external_write(path: Path, payload: bytes) -> dict[str, object]:
        completed = subprocess.run(
            [sys.executable, "-c", _WINDOWS_EXTERNAL_WRITE_ATTEMPT, str(path), payload.hex()],
            check=True,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return json.loads(completed.stdout)

    def test_case_01_private_metadata_stage_publishes_valid_image(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "normal.png"
            published, report, _validation = publish_image_bytes_with_metadata(self._png_bytes(), target)
            self.assertEqual(published, target.resolve())
            self.assertTrue(target.is_file())
            with Image.open(target) as opened:
                opened.load()
                self.assertEqual(opened.size, (17, 13))
            self.assertEqual(read_hdde_metadata(target)["software"], HDDE_SOFTWARE)
            self.assertTrue(report["decoded_pixel_content_unchanged"])
            self.assertEqual(self._private_outputs(root), [])

    def test_case_02_existing_target_is_unchanged_and_safe_collision_uses_02(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "客户_影界4K_260901.png"
            protected = b"protected-owner"
            target.write_bytes(protected)
            protected_sha = hashlib.sha256(protected).hexdigest()
            published, _report, _validation = publish_image_bytes_with_metadata(
                self._png_bytes(), target, collision_base_path=target
            )
            self.assertEqual(published.name, "客户_影界4K_260901_02.png")
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), protected_sha)
            self.assertEqual(self._private_outputs(root), [])

    def test_case_03_competitor_created_after_metadata_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = (root / "race.png").resolve()
            competitor = b"competitor-after-metadata"
            competitor_sha = hashlib.sha256(competitor).hexdigest()
            real_publish = publish_safety._publish_open_file_no_replace

            def occupy_then_publish(open_file, private_path, candidate):
                target.write_bytes(competitor)
                return real_publish(open_file, private_path, candidate)

            with patch.object(publish_safety, "_publish_open_file_no_replace", side_effect=occupy_then_publish):
                with self.assertRaises(FileExistsError):
                    publish_image_bytes_with_metadata(self._png_bytes(), target)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), competitor_sha)
            self.assertEqual(self._private_outputs(root), [])

    def test_case_04_double_publisher_allows_exactly_one_winner(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = (root / "double.png").resolve()
            barrier = threading.Barrier(2)
            real_publish = publish_safety._publish_open_file_no_replace

            def synchronized_publish(open_file, private_path, candidate):
                barrier.wait(timeout=5)
                return real_publish(open_file, private_path, candidate)

            def attempt(payload: bytes) -> str:
                try:
                    publish_image_bytes_with_metadata(payload, target)
                    return "success"
                except FileExistsError:
                    return "collision"

            with patch.object(publish_safety, "_publish_open_file_no_replace", side_effect=synchronized_publish):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    outcomes = list(pool.map(attempt, (self._png_bytes((10, 20, 30, 255)), self._png_bytes((70, 80, 90, 255)))))
            self.assertEqual(outcomes.count("success"), 1)
            self.assertEqual(outcomes.count("collision"), 1)
            with Image.open(target) as opened:
                opened.load()
                self.assertEqual(opened.size, (17, 13))
            self.assertEqual(self._private_outputs(root), [])

    def test_case_05_metadata_failure_creates_no_final_and_cleans_private_temp(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "metadata-failure.png"
            with patch.object(publish_safety, "write_hdde_metadata_bytes", side_effect=ValueError("controlled metadata failure")):
                with self.assertRaises(OutputMetadataStageError):
                    publish_image_bytes_with_metadata(self._png_bytes(), target)
            self.assertFalse(target.exists())
            self.assertEqual(self._private_outputs(root), [])

            def reject_private(_data: bytes) -> None:
                raise ValueError("controlled private validation failure")

            with self.assertRaisesRegex(ValueError, "controlled private validation failure"):
                publish_image_bytes_with_metadata(self._png_bytes(), target, verify_private=reject_private)
            self.assertFalse(target.exists())
            self.assertEqual(self._private_outputs(root), [])

    def test_case_06_publish_failure_preserves_existing_target_and_cleans_private_temp(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "publish-failure.png"
            protected = b"publish-failure-owner"
            target.write_bytes(protected)
            before_sha = hashlib.sha256(protected).hexdigest()
            with self.assertRaises(FileExistsError):
                publish_image_bytes_with_metadata(self._png_bytes(), target)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), before_sha)
            self.assertEqual(self._private_outputs(root), [])

    @unittest.skipUnless(os.name == "nt", "Windows handle-sharing contract")
    def test_case_07_post_validation_external_write_is_denied_and_sha_is_committed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = (root / "post-validation-tamper.png").resolve()
            observed: dict[str, object] = {}
            real_publish = publish_safety._publish_open_file_no_replace

            def verify_private(data: bytes) -> None:
                observed["validated_sha256"] = hashlib.sha256(data).hexdigest()

            def tamper_then_publish(open_file, private_path, candidate):
                observed["tamper"] = self._attempt_external_write(private_path, b"tamper-after-validation")
                return real_publish(open_file, private_path, candidate)

            with patch.object(publish_safety, "_publish_open_file_no_replace", side_effect=tamper_then_publish):
                published, report, _validation = publish_image_bytes_with_metadata(
                    self._png_bytes(), target, verify_private=verify_private
                )

            final_sha = hashlib.sha256(published.read_bytes()).hexdigest()
            self.assertFalse(observed["tamper"]["opened"])
            self.assertFalse(observed["tamper"]["written"])
            self.assertEqual(final_sha, observed["validated_sha256"])
            self.assertEqual(report["publish_integrity"]["validated_sha256"], final_sha)
            self.assertEqual(report["publish_integrity"]["committed_sha256"], final_sha)
            self.assertTrue(report["publish_integrity"]["sha256_identity"])
            with Image.open(published) as opened:
                opened.load()
                self.assertEqual(opened.size, (17, 13))
            self.assertEqual(self._private_outputs(root), [])

    @unittest.skipUnless(os.name == "nt", "Windows handle-sharing contract")
    def test_case_08_preoccupied_exact_private_candidate_fails_create_new_and_preserves_owner(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = (root / "preoccupied-private-target.png").resolve()
            sentinel = root / f"{PRIVATE_OUTPUT_PREFIX}{'a' * 32}{publish_safety.PRIVATE_OUTPUT_SUFFIX}"
            sentinel.write_bytes(b"third-party-owner")
            sentinel_sha = hashlib.sha256(sentinel.read_bytes()).hexdigest()

            raw_handle = publish_safety._windows_create_file(
                str(sentinel),
                publish_safety._WIN_GENERIC_READ | publish_safety._WIN_GENERIC_WRITE | publish_safety._WIN_DELETE,
                publish_safety._WIN_FILE_SHARE_READ | publish_safety._WIN_FILE_SHARE_DELETE,
                None,
                publish_safety._WIN_CREATE_NEW,
                publish_safety._WIN_FILE_ATTRIBUTE_NORMAL,
                None,
            )
            error_code = publish_safety.ctypes.get_last_error()

            self.assertEqual(raw_handle, publish_safety._WIN_INVALID_HANDLE_VALUE)
            self.assertIn(error_code, {publish_safety._WIN_ERROR_FILE_EXISTS, publish_safety._WIN_ERROR_ALREADY_EXISTS})
            self.assertTrue(sentinel.is_file())
            self.assertEqual(hashlib.sha256(sentinel.read_bytes()).hexdigest(), sentinel_sha)
            self.assertFalse(target.exists())
            self.assertEqual(self._private_outputs(root), [sentinel])

    def test_case_09_unsupported_platform_fails_closed_before_private_or_final_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = (root / "unsupported-platform.png").resolve()
            with patch.object(publish_safety, "_SAFE_PUBLISH_PLATFORM", "posix"):
                with self.assertRaisesRegex(RuntimeError, "SAFE_PUBLISH_UNSUPPORTED"):
                    publish_image_bytes_with_metadata(self._png_bytes(), target)
            self.assertFalse(target.exists())
            self.assertEqual(self._private_outputs(root), [])


if __name__ == "__main__":
    unittest.main()
