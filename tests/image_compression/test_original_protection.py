from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from engine.image_compression import common
from engine.image_compression.common import sha256_file
from engine.image_compression.router import process_image_compression
from engine.image_compression.statuses import TechnicalStatus


class OriginalProtectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.png"
        Image.new("RGBA", (96, 64), (10, 20, 30, 255)).save(self.source, format="PNG", compress_level=0)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def lossless_request(self, task_id: str, output: str = "out") -> dict[str, object]:
        return {
            "contract_version": "hdde.image-task.v1",
            "task_id": task_id,
            "operation_mode": "LOSSLESS_COMPRESSION",
            "source_path": str(self.source.resolve()),
            "output_directory": str((self.root / output).resolve()),
            "preserve_format": True,
            "quality_policy": "LOSSLESS_ONLY",
            "metadata_policy": "PRESERVE_SUPPORTED_STRICT",
            "visual_review_policy": "STRICT_LOSSLESS_EVIDENCE",
        }

    def resize_request(self, task_id: str, output: str = "resize") -> dict[str, object]:
        return {
            "contract_version": "hdde.image-task.v1",
            "task_id": task_id,
            "operation_mode": "RESIZE_REDUCTION",
            "source_path": str(self.source.resolve()),
            "output_directory": str((self.root / output).resolve()),
            "preserve_format": True,
            "scale_ratio": 0.75,
            "resize_policy": "LANCZOS_HIGH_QUALITY",
            "quality_policy": "SAME_FORMAT_HIGH_QUALITY",
            "metadata_policy": "PRESERVE_SUPPORTED_STRICT",
            "visual_review_policy": "VALIDATION_STRICT",
        }

    def test_source_sha_never_changes_and_output_is_separate(self) -> None:
        before = sha256_file(self.source)
        result = process_image_compression(self.lossless_request("protect"))
        self.assertEqual(sha256_file(self.source), before)
        self.assertEqual(result.technical_status, TechnicalStatus.TARGET_MET)
        self.assertNotEqual(Path(result.output_path).resolve(), self.source.resolve())
        self.assertEqual(list((self.root / "out").glob(".*.tmp")), [])

    def test_existing_output_is_not_overwritten(self) -> None:
        request = self.lossless_request("conflict")
        first = process_image_compression(request)
        first_hash = sha256_file(first.output_path)
        second = process_image_compression(request)
        self.assertEqual(second.technical_status, TechnicalStatus.PROCESSING_FAILED)
        self.assertEqual(second.failure_code, "OUTPUT_EXISTS")
        self.assertEqual(sha256_file(first.output_path), first_hash)

    def test_permission_error_during_atomic_write_leaves_no_output(self) -> None:
        def inject(stage: str) -> None:
            if stage == "ATOMIC_WRITE":
                raise PermissionError("fixture permission denial")

        result = process_image_compression(self.resize_request("permission"), fault_injector=inject)
        self.assertEqual(result.technical_status, TechnicalStatus.PROCESSING_FAILED)
        self.assertEqual(result.failure_code, "OUTPUT_WRITE_PERMISSION_DENIED")
        self.assertFalse(result.output_created)
        self.assertEqual(list((self.root / "resize").glob("*")), [])

    def test_source_change_during_atomic_write_removes_candidate(self) -> None:
        original = self.source.read_bytes()

        def inject(stage: str) -> None:
            if stage == "ATOMIC_WRITE":
                self.source.write_bytes(original + b"changed")

        result = process_image_compression(self.resize_request("source-change", "source-change-out"), fault_injector=inject)
        self.assertEqual(result.technical_status, TechnicalStatus.PROCESSING_FAILED)
        self.assertEqual(result.failure_code, "SOURCE_SHA_CHANGED")
        self.assertFalse(result.output_created)
        self.assertEqual(list((self.root / "source-change-out").glob("*")), [])

    def test_no_gain_does_not_create_copy(self) -> None:
        first = process_image_compression(self.lossless_request("first", "first-out"))
        self.assertTrue(first.output_created)
        optimised = Path(first.output_path)
        self.source = optimised
        second = process_image_compression(self.lossless_request("second", "second-out"))
        self.assertEqual(second.technical_status, TechnicalStatus.NO_PROCESSING_NEEDED)
        self.assertFalse(second.output_created)
        self.assertEqual(second.output_path, str(optimised.resolve()))
        self.assertFalse((self.root / "second-out" / "source__first__second.png").exists())

    def test_competing_same_name_is_not_overwritten(self) -> None:
        request = self.resize_request("race", "race-out")
        original_link = common.os.link

        def competing_link(source: Path, destination: Path) -> None:
            Path(destination).write_bytes(b"COMPETITOR")
            original_link(source, destination)

        with patch.object(common.os, "link", side_effect=competing_link):
            result = process_image_compression(request)
        self.assertEqual(result.failure_code, "OUTPUT_EXISTS")
        final = self.root / "race-out" / "source__race.png"
        self.assertEqual(final.read_bytes(), b"COMPETITOR")
        self.assertEqual(list((self.root / "race-out").glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
