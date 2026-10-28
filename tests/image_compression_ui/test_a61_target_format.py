import hashlib
import io
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from engine.image_compression.common import read_image_info
from tests.image_compression_ui import test_a06_batch_stability as batch_tests
from tests.image_compression_ui import test_image_compression_api as api_tests


def image_bytes(fmt, *, alpha=False, optimized=False):
    y, x = np.indices((96, 144))
    rgb = np.stack(((x * 3 + y) % 256, (x + y * 2) % 256, (x * 2 + y * 3) % 256), axis=2).astype(np.uint8)
    if alpha:
        alpha_channel = np.where(x < 48, 0, np.where(x < 96, 128, 255)).astype(np.uint8)
        image = Image.fromarray(np.dstack((rgb, alpha_channel)), "RGBA")
    else:
        image = Image.fromarray(rgb, "RGB")
    stream = io.BytesIO()
    options = (
        {"quality": 40 if optimized else 92, "optimize": True}
        if fmt == "JPEG"
        else {"optimize": optimized, "compress_level": 9 if optimized else 0}
        if fmt == "PNG"
        else {"lossless": True, "method": 6 if optimized else 4, "exact": True}
    )
    image.save(stream, format=fmt, **options)
    return stream.getvalue()


class TargetFormatApiTests(unittest.TestCase):
    setUp = api_tests.ImageCompressionApiStage4Tests.setUp
    tearDown = api_tests.ImageCompressionApiStage4Tests.tearDown
    intake_bytes = api_tests.ImageCompressionApiStage4Tests.intake_bytes

    def run_route(self, source_format, target_format, *, alpha=False, optimized=False):
        suffix = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}[source_format]
        mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[source_format]
        source = image_bytes(source_format, alpha=alpha, optimized=optimized)
        intake = self.intake_bytes(source, f"source.{suffix}", mime)
        response = self.client.post("/api/image-compression/run", json={
            "source_token": intake["source_token"],
            "operation_mode": "DELIVERY_OPTIMIZATION",
            "params": {"target_format": target_format},
        })
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        result = data["result"]
        record = self.state["task_registry"][result["task_id"]]
        expected = (
            result["output_format"]
            if target_format == "SMART_COMPRESSION"
            else source_format
            if target_format == "PRESERVE_FORMAT"
            else target_format
        )
        expected_candidate = "JPG" if expected == "JPEG" else expected

        self.assertEqual(record["request"]["target_format"], target_format)
        self.assertEqual(record["target_format"], target_format)
        self.assertEqual(record["effective_target_format"], expected)
        self.assertEqual(result["source_format"], source_format)
        self.assertEqual(result["output_format"], expected)
        self.assertEqual(result["public_output_count"], int(result["output_created"]))
        self.assertEqual(len(result["candidates"]), result["public_output_count"])
        self.assertEqual(sum(bool(item.get("output_path")) for item in record["candidate_options"]), result["public_output_count"])
        if not (target_format == "SMART_COMPRESSION" and source_format == "PNG" and not alpha):
            self.assertTrue(all(item["format"] == expected_candidate for item in record["candidate_options"]))
        self.assertEqual(result["source_sha256"], hashlib.sha256(source).hexdigest())

        output = Path(result["output_path"])
        verified = read_image_info(output, allow_webp=True)
        self.assertEqual(verified["format"], expected)
        self.assertEqual(verified["dimensions"], {"width": 144, "height": 96})
        if result["output_created"]:
            self.assertEqual(output.suffix.lower(), {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[expected])
            self.assertEqual(verified["sha256"], result["output_sha256"])
            self.assertEqual(result["winner"]["quality_gate"]["status"], "PASS")
            self.assertEqual(result["metadata_details"]["target_format"], target_format)
            self.assertEqual(result["metadata_details"]["effective_target_format"], expected)
        else:
            self.assertEqual(result["winner_scheme_id"], "keep_original")
            self.assertFalse(data["task"]["result_id"])
        if target_format in {"JPEG", "PNG", "WEBP"} and target_format != source_format:
            self.assertTrue(result["output_created"])
            self.assertTrue(record["format_conversion"])
        return data

    def test_twelve_core_routes_use_real_target_encoding(self):
        for target_format in ("PRESERVE_FORMAT", "JPEG", "PNG", "WEBP"):
            for source_format in ("JPEG", "PNG", "WEBP"):
                with self.subTest(source=source_format, target=target_format):
                    self.run_route(source_format, target_format)

    def test_preserve_format_never_generates_cross_format_candidates(self):
        for source_format in ("JPEG", "PNG", "WEBP"):
            with self.subTest(source=source_format):
                data = self.run_route(source_format, "PRESERVE_FORMAT")
                record = self.state["task_registry"][data["result"]["task_id"]]
                expected = "JPG" if source_format == "JPEG" else source_format
                self.assertEqual({item["format"] for item in record["candidate_options"]}, {expected})
                self.assertEqual(record["format_policy"], "PRESERVE_SOURCE_FORMAT")

    def test_smart_mode_compares_only_opaque_png_across_formats(self):
        opaque = self.run_route("PNG", "SMART_COMPRESSION")
        opaque_record = self.state["task_registry"][opaque["result"]["task_id"]]
        self.assertEqual({item["format"] for item in opaque_record["candidate_options"]}, {"PNG", "JPG"})
        self.assertTrue(opaque_record["smart_compression_details"]["comparison_performed"])
        self.assertIn(opaque["result"]["output_format"], {"PNG", "JPEG"})
        if opaque["result"]["output_format"] == "JPEG":
            self.assertLess(
                opaque["result"]["output_size_bytes"],
                opaque_record["smart_compression_details"]["png_candidate_bytes"],
            )
            self.assertTrue(opaque_record["format_conversion"])

        transparent = self.run_route("PNG", "SMART_COMPRESSION", alpha=True)
        transparent_record = self.state["task_registry"][transparent["result"]["task_id"]]
        self.assertEqual({item["format"] for item in transparent_record["candidate_options"]}, {"PNG"})
        self.assertFalse(transparent_record["smart_compression_details"]["comparison_performed"])

        for source_format, expected_candidate in (("JPEG", "JPG"), ("WEBP", "WEBP")):
            with self.subTest(source=source_format):
                data = self.run_route(source_format, "SMART_COMPRESSION")
                record = self.state["task_registry"][data["result"]["task_id"]]
                self.assertEqual({item["format"] for item in record["candidate_options"]}, {expected_candidate})
                self.assertFalse(record["format_conversion"])

    def test_legacy_auto_values_are_not_current_target_modes(self):
        source = image_bytes("PNG")
        intake = self.intake_bytes(source, "source.png", "image/png")
        for legacy_value in ("AUTO", "SYSTEM_AUTO"):
            with self.subTest(target=legacy_value):
                response = self.client.post("/api/image-compression/run", json={
                    "source_token": intake["source_token"],
                    "operation_mode": "DELIVERY_OPTIMIZATION",
                    "params": {"target_format": legacy_value},
                })
                self.assertEqual(response.status_code, 400, response.text)

    def test_alpha_png_and_webp_to_jpg_use_deterministic_white_background(self):
        for source_format in ("PNG", "WEBP"):
            with self.subTest(source=source_format):
                data = self.run_route(source_format, "JPEG", alpha=True)
                result = data["result"]
                self.assertFalse(result["alpha_preserved"])
                self.assertEqual(result["alpha_details"]["conversion_action"], "FLATTEN_ON_WHITE")
                self.assertEqual(result["alpha_details"]["conversion_background_rgb"], [255, 255, 255])
                with Image.open(result["output_path"]) as output:
                    output.load()
                    self.assertTrue(all(value >= 245 for value in output.convert("RGB").getpixel((0, 0))))

    def test_optimized_same_format_sources_keep_original(self):
        for source_format in ("JPEG", "PNG", "WEBP"):
            with self.subTest(source=source_format):
                data = self.run_route(source_format, "PRESERVE_FORMAT", optimized=True)
                self.assertEqual(data["result"]["winner_scheme_id"], "keep_original")


class BatchTargetFormatTests(unittest.TestCase):
    setUp = batch_tests.BatchStabilityTests.setUp
    tearDown = batch_tests.BatchStabilityTests.tearDown
    open = batch_tests.BatchStabilityTests.open
    close = batch_tests.BatchStabilityTests.close
    create = batch_tests.BatchStabilityTests.create
    status = batch_tests.BatchStabilityTests.status
    until = batch_tests.BatchStabilityTests.until

    @staticmethod
    def upload(fmt):
        suffix = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}[fmt]
        mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[fmt]
        return (f"batch.{suffix}", image_bytes(fmt), mime)

    def test_batch_reuses_same_preserve_and_manual_target_contract(self):
        self.open()
        cases = (
            ("PRESERVE_FORMAT", "WEBP", "WEBP"),
            ("JPEG", "PNG", "JPEG"),
            ("PNG", "WEBP", "PNG"),
            ("WEBP", "JPEG", "WEBP"),
        )
        for target, source, expected in cases:
            with self.subTest(target=target, source=source):
                batch_id = self.create([self.upload(source)], target_format=target)
                data = self.until(batch_id)
                self.assertEqual(data["targetFormat"], target)
                item = data["items"][0]
                self.assertIn(item["status"], {"COMPLETED", "KEEP_ORIGINAL"})
                record = self.registry[item["taskId"]]
                result = record["result"].to_dict()
                self.assertEqual(record["request"]["target_format"], target)
                self.assertEqual(result["source_format"], source)
                self.assertEqual(result["output_format"], expected)
                if target in {"JPEG", "PNG", "WEBP"} and target != source:
                    self.assertEqual(item["status"], "COMPLETED")
                    self.assertTrue(item["formatConversion"])

    def test_batch_smart_opaque_png_uses_shared_cross_format_decision(self):
        self.open()
        batch_id = self.create([self.upload("PNG")], target_format="SMART_COMPRESSION")
        data = self.until(batch_id)
        item = data["items"][0]
        self.assertIn(item["status"], {"COMPLETED", "KEEP_ORIGINAL"})
        record = self.registry[item["taskId"]]
        self.assertEqual(record["request"]["target_format"], "SMART_COMPRESSION")
        self.assertTrue(record["smart_compression_details"]["comparison_performed"])
        self.assertEqual({candidate["format"] for candidate in record["candidate_options"]}, {"PNG", "JPG"})


if __name__ == "__main__":
    unittest.main()
