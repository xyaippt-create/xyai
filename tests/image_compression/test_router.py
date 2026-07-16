from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from engine.image_compression.contracts import ImageCompressionResult
from engine.image_compression.router import process_image_compression
from engine.image_compression.statuses import OperationMode, TechnicalStatus


class RouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.png"
        Image.new("RGB", (32, 24), "navy").save(self.source, format="PNG")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def request(self, mode: str) -> dict[str, object]:
        quality = {
            "LOSSLESS_COMPRESSION": "LOSSLESS_ONLY",
            "RESIZE_REDUCTION": "SAME_FORMAT_HIGH_QUALITY",
            "UPLOAD_ADAPTATION": "UPLOAD_ADAPTATION_V1",
        }[mode]
        request: dict[str, object] = {
            "contract_version": "hdde.image-task.v1",
            "task_id": f"route-{mode.lower()}",
            "operation_mode": mode,
            "source_path": str(self.source.resolve()),
            "output_directory": str((self.root / mode.lower()).resolve()),
            "preserve_format": True,
            "quality_policy": quality,
            "metadata_policy": "PRESERVE_SUPPORTED_STRICT",
            "visual_review_policy": "STRICT_LOSSLESS_EVIDENCE" if mode == "LOSSLESS_COMPRESSION" else "VALIDATION_STRICT",
        }
        if mode == "RESIZE_REDUCTION":
            request.update(scale_ratio=0.75, resize_policy="LANCZOS_HIGH_QUALITY")
        if mode == "UPLOAD_ADAPTATION":
            request.update(max_width=24, max_height=18)
        return request

    def test_each_mode_routes_only_to_its_processor(self) -> None:
        modules = {
            OperationMode.LOSSLESS_COMPRESSION: "lossless.process_lossless",
            OperationMode.RESIZE_REDUCTION: "resize.process_resize",
            OperationMode.UPLOAD_ADAPTATION: "upload_adaptation.process_upload_adaptation",
        }
        for mode, target in modules.items():
            with self.subTest(mode=mode):
                sentinel = ImageCompressionResult(task_id="sentinel", operation_mode=mode)
                with patch(f"engine.image_compression.router.{target}", return_value=sentinel) as processor:
                    result = process_image_compression(self.request(mode.value))
                    self.assertIs(result, sentinel)
                    processor.assert_called_once()

    def test_unknown_field_fails_before_processing(self) -> None:
        request = self.request("LOSSLESS_COMPRESSION")
        request["unknown"] = True
        result = process_image_compression(request)
        self.assertEqual(result.technical_status, TechnicalStatus.INVALID_REQUEST)
        self.assertEqual(result.failure_code, "UNKNOWN_FIELD")
        self.assertFalse(result.output_created)

    def test_test_setup_inside_request_is_unknown(self) -> None:
        request = self.request("RESIZE_REDUCTION")
        request["test_setup"] = {"stage": "ATOMIC_WRITE"}
        result = process_image_compression(request)
        self.assertEqual(result.failure_code, "UNKNOWN_FIELD")

    def test_output_directory_preflight_is_distinct_from_runtime_permission_failure(self) -> None:
        request = self.request("RESIZE_REDUCTION")
        request["output_directory"] = "relative-output-directory"
        result = process_image_compression(request)
        self.assertEqual(result.technical_status, TechnicalStatus.INVALID_REQUEST)
        self.assertEqual(result.failure_code, "OUTPUT_DIRECTORY_INVALID")
        self.assertFalse(result.output_created)

    def test_jpeg_lossless_does_not_switch_modes(self) -> None:
        jpeg = self.root / "source.jpg"
        Image.new("RGB", (32, 24), "orange").save(jpeg, format="JPEG", quality=95)
        request = self.request("LOSSLESS_COMPRESSION")
        request["source_path"] = str(jpeg.resolve())
        result = process_image_compression(request)
        self.assertEqual(result.operation_mode, OperationMode.LOSSLESS_COMPRESSION)
        self.assertEqual(result.technical_status, TechnicalStatus.CANNOT_MEET_SAFELY)
        self.assertEqual(result.failure_code, "JPEG_COEFFICIENT_LOSSLESS_NOT_IMPLEMENTED")


if __name__ == "__main__":
    unittest.main()
