"""Real JPEG streams: an MPF thumbnail is not a second independent photograph."""
import hashlib
import io
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageFile, ImageOps

from engine.output import metadata_writer
from tests.image_compression.test_a03_single_winner import _business_image
from tests.image_compression_ui import test_image_compression_api as api_tests


def camera_jpeg(*, thumbnail=True, thumbnail_size=(160, 90), orientation=1):
    primary = _business_image()
    preview = primary.resize(thumbnail_size)
    stream = io.BytesIO()
    exif = Image.Exif()
    exif[274], exif[282], exif[283], exif[296] = orientation, 72, 72, 2
    exif[34853] = {0: b"\x02\x03\x00\x00", 1: "N", 2: (31, 12, 0)}
    primary.save(stream, format="MPO", save_all=True, append_images=[preview], quality=100, exif=exif)
    payload = bytearray(stream.getvalue())
    if thumbnail:
        # Give the actual embedded JPEG the same MPF roles as the camera sample.
        base = payload.index(b"MPF\0") + 4
        assert payload[base:base+2] == b"II"
        directory = base + struct.unpack_from("<I", payload, base+4)[0]
        count = struct.unpack_from("<H", payload, directory)[0]
        entries = None
        for index in range(count):
            offset = directory+2+12*index
            if struct.unpack_from("<H", payload, offset)[0] == 0xB002:
                entries = base+struct.unpack_from("<I", payload, offset+8)[0]
                break
        assert entries is not None
        struct.pack_into("<I", payload, entries, 0x80030000)
        struct.pack_into("<H", payload, entries+12, 2)
        struct.pack_into("<I", payload, entries+16, 0x40010002)
    return bytes(payload)


class CameraJpegIntakeTests(unittest.TestCase):
    setUp = api_tests.ImageCompressionApiStage4Tests.setUp
    tearDown = api_tests.ImageCompressionApiStage4Tests.tearDown
    intake_bytes = api_tests.ImageCompressionApiStage4Tests.intake_bytes

    def post_intake(self, content):
        return self.client.post("/api/image-compression/intake", files={"file":("camera.jpg", content, "image/jpeg")})

    def test_static_camera_thumbnail_uses_primary_and_keeps_orientation_dpi_and_source(self):
        content = camera_jpeg(orientation=6)
        with Image.open(io.BytesIO(content)) as image:
            self.assertEqual(image.format, "MPO")
            self.assertEqual(image.n_frames, 2)
            primary = ImageOps.exif_transpose(image).copy()
        intake = self.intake_bytes(content, "camera.jpg", "image/jpeg")
        self.assertEqual(intake["format"], "JPEG")
        self.assertEqual((intake["width"], intake["height"]), primary.size)
        response = self.client.post("/api/image-compression/run", json={
            "source_token":intake["source_token"], "operation_mode":"DELIVERY_OPTIMIZATION", "params":{},
        })
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        result = data["result"]
        self.assertTrue(result["output_created"], result)
        self.assertEqual(result["source_sha256"], hashlib.sha256(content).hexdigest())
        self.assertFalse(result["resized"])
        self.assertEqual(result["output_dimensions"], result["source_dimensions"])
        self.assertEqual(result["winner"]["quality_gate"]["status"], "PASS")
        self.assertEqual(Path(data["task"]["source_path"]).read_bytes(), content)
        with Image.open(result["output_path"]) as output:
            output.load()
            self.assertEqual(output.format, "JPEG")
            self.assertEqual(output.size, primary.size)
            self.assertEqual(output.info["dpi"], (72,72))
            self.assertEqual(output.getexif().get_ifd(34853), {0: b"\x02\x03\x00\x00", 1: "N", 2: (31, 12, 0)})
        self.assertFalse(ImageFile.LOAD_TRUNCATED_IMAGES)

    def test_changed_gps_content_still_fails_metadata_validation(self):
        source = camera_jpeg()
        with Image.open(io.BytesIO(source)) as image:
            stream = io.BytesIO()
            image.save(stream, format="JPEG")
        encoded = stream.getvalue()
        updated, report = metadata_writer.write_hdde_metadata_bytes(encoded, source_data=source)
        self.assertTrue(report["source_metadata_preserved"])
        exif = metadata_writer._read_exif(updated)
        self.assertNotEqual(exif.get(34853), metadata_writer._read_exif(source).get(34853))
        exif.get_ifd(34853)[1] = "S"
        segments, tail = metadata_writer._jpeg_segments(updated)
        changed = b"\xff\xd8" + b"".join(
            metadata_writer._jpeg_segment(0xE1, exif.tobytes())
            if metadata_writer._jpeg_category(segment) == "exif" else segment
            for segment in segments
        ) + tail
        with patch.object(metadata_writer, "_write_jpeg_metadata", return_value=changed):
            with self.assertRaisesRegex(ValueError, "SOURCE_METADATA_NOT_PRESERVED"):
                metadata_writer.write_hdde_metadata_bytes(encoded, source_data=source)

    def test_independent_mpo_is_rejected_with_specific_message(self):
        with self.assertLogs("backend.image_compression_api", level="ERROR") as logs:
            response = self.post_intake(camera_jpeg(thumbnail=False))
        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "MULTI_FRAME_SOURCE_UNSUPPORTED")
        self.assertIn("多个独立画面", detail["message"])
        self.assertTrue(any("source_validation" in line and "Traceback" in line for line in logs.output))
        self.assertEqual(len(self.state["task_registry"]), 0)

    def test_same_size_second_image_is_not_accepted_as_thumbnail(self):
        with self.assertLogs("backend.image_compression_api", level="ERROR"):
            response = self.post_intake(camera_jpeg(thumbnail_size=(640,360)))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "MULTI_FRAME_SOURCE_UNSUPPORTED")

    def test_truncated_thumbnail_fails_even_when_primary_fully_decodes(self):
        content = camera_jpeg()[:-100]
        with Image.open(io.BytesIO(content)) as primary:
            primary.load()
        with self.assertLogs("backend.image_compression_api", level="ERROR"):
            response = self.post_intake(content)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "SOURCE_DECODE_FAILED")
        self.assertFalse(ImageFile.LOAD_TRUNCATED_IMAGES)
        self.assertEqual(len(self.state["task_registry"]), 0)

    def test_zero_filled_file_has_explicit_format_error(self):
        with self.assertLogs("backend.image_compression_api", level="ERROR"):
            response = self.post_intake(bytes(1024))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "SOURCE_FORMAT_UNSUPPORTED")
        self.assertIn("文件内容不是", response.json()["detail"]["message"])

    def test_intake_write_failure_is_not_reported_as_bad_image(self):
        write = Path.write_bytes
        def fail_copy(path, content):
            if "image-compression-intake" in path.parts:
                raise PermissionError("controlled intake-copy write failure")
            return write(path, content)
        with patch.object(Path, "write_bytes", fail_copy), self.assertLogs("backend.image_compression_api", level="ERROR") as logs:
            response = self.post_intake(camera_jpeg())
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"]["code"], "SOURCE_INTAKE_WRITE_FAILED")
        self.assertTrue(any("intake_write" in line and "PermissionError" in line for line in logs.output))
        self.assertEqual(len(self.state["task_registry"]), 0)
