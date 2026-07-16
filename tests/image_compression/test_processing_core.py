from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from engine.image_compression.common import read_image_info, sha256_file
from engine.image_compression.router import process_image_compression
from engine.image_compression.statuses import DeliveryGateStatus, TechnicalStatus, VisualReviewStatus


class ProcessingCoreSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def base_request(self, source: Path, output: str, task_id: str, mode: str, quality: str, visual: str) -> dict[str, object]:
        return {
            "contract_version": "hdde.image-task.v1",
            "task_id": task_id,
            "operation_mode": mode,
            "source_path": str(source.resolve()),
            "output_directory": str((self.root / output).resolve()),
            "preserve_format": True,
            "quality_policy": quality,
            "metadata_policy": "PRESERVE_SUPPORTED_STRICT",
            "visual_review_policy": visual,
        }

    def test_png_lossless_smoke(self) -> None:
        source = self.root / "lossless.png"
        Image.new("RGBA", (128, 96), (20, 40, 60, 180)).save(source, format="PNG", compress_level=0)
        before = read_image_info(source)
        request = self.base_request(source, "lossless-out", "smoke-lossless", "LOSSLESS_COMPRESSION", "LOSSLESS_ONLY", "STRICT_LOSSLESS_EVIDENCE")
        result = process_image_compression(request)
        after = read_image_info(result.output_path)
        self.assertEqual(result.technical_status, TechnicalStatus.TARGET_MET)
        self.assertEqual(before["pixel_sha256"], after["pixel_sha256"])
        self.assertEqual(before["alpha_sha256"], after["alpha_sha256"])
        self.assertLess(after["size_bytes"], before["size_bytes"])
        self.assertEqual(result.delivery_gate_status, DeliveryGateStatus.DELIVERY_READY)
        self.assertEqual(sha256_file(source), before["sha256"])

    def test_png_alpha_resize_smoke(self) -> None:
        source = self.root / "alpha.png"
        array = np.zeros((80, 100, 4), dtype=np.uint8)
        array[..., 0] = 220
        array[..., 1] = 30
        array[..., 2] = 70
        array[10:70, 10:90, 3] = 180
        Image.fromarray(array, mode="RGBA").save(source, format="PNG")
        request = self.base_request(source, "alpha-out", "smoke-alpha", "RESIZE_REDUCTION", "SAME_FORMAT_HIGH_QUALITY", "VALIDATION_STRICT")
        request.update(scale_ratio=0.75, resize_policy="LANCZOS_HIGH_QUALITY")
        result = process_image_compression(request)
        self.assertEqual(result.technical_status, TechnicalStatus.TARGET_MET)
        self.assertEqual(result.output_dimensions, {"width": 75, "height": 60})
        self.assertTrue(result.lossy)
        self.assertTrue(result.alpha_details["premultiplied_resize_used"])
        self.assertTrue(result.alpha_details["fully_transparent_rgb_zero"])
        self.assertEqual(result.visual_review_status, VisualReviewStatus.PENDING)
        self.assertFalse(result.delivery_eligible)

    def test_jpeg_resize_smoke(self) -> None:
        source = self.root / "photo.jpg"
        Image.new("RGB", (120, 80), (90, 120, 160)).save(source, format="JPEG", quality=95, subsampling=0)
        request = self.base_request(source, "jpeg-out", "smoke-jpeg", "RESIZE_REDUCTION", "SAME_FORMAT_HIGH_QUALITY", "VALIDATION_STRICT")
        request.update(scale_ratio=0.5, resize_policy="LANCZOS_HIGH_QUALITY")
        result = process_image_compression(request)
        self.assertEqual(result.technical_status, TechnicalStatus.TARGET_MET_WITH_REENCODE)
        self.assertEqual(result.output_format, "JPEG")
        self.assertEqual(result.output_dimensions, {"width": 60, "height": 40})
        self.assertTrue(result.lossy)
        self.assertFalse(result.delivery_eligible)

    def test_upload_adaptation_smoke(self) -> None:
        source = self.root / "upload.jpg"
        gradient = np.tile(np.arange(200, dtype=np.uint8), (100, 1))
        rgb = np.stack((gradient, np.flipud(gradient), gradient), axis=2)
        Image.fromarray(rgb, mode="RGB").save(source, format="JPEG", quality=95, subsampling=0)
        request = self.base_request(source, "upload-out", "smoke-upload", "UPLOAD_ADAPTATION", "UPLOAD_ADAPTATION_V1", "VALIDATION_STRICT")
        request.update(max_width=100, max_height=50)
        result = process_image_compression(request)
        self.assertIn(result.technical_status, {TechnicalStatus.TARGET_MET, TechnicalStatus.TARGET_MET_WITH_REENCODE})
        self.assertLessEqual(result.output_dimensions["width"], 100)
        self.assertLessEqual(result.output_dimensions["height"], 50)
        self.assertEqual(result.visual_review_status, VisualReviewStatus.PENDING)
        self.assertEqual(result.delivery_gate_status, DeliveryGateStatus.REVIEW_REQUIRED)
        self.assertFalse(result.delivery_eligible)
        attempts = result.evidence_paths["candidate_attempts"]
        self.assertTrue(all(item["direct_source_lineage"] for item in attempts))

    def test_palette_transparency_uses_premultiplied_resize(self) -> None:
        source = self.root / "palette-transparent.png"
        image = Image.new("P", (40, 30), 0)
        image.putpalette([220, 30, 70, 0, 0, 0] + [0] * 762)
        image.info["transparency"] = 0
        image.save(source, format="PNG")
        request = self.base_request(source, "palette-out", "smoke-palette", "RESIZE_REDUCTION", "SAME_FORMAT_HIGH_QUALITY", "VALIDATION_STRICT")
        request.update(scale_ratio=0.5, resize_policy="LANCZOS_HIGH_QUALITY")
        result = process_image_compression(request)
        self.assertEqual(result.technical_status, TechnicalStatus.TARGET_MET)
        self.assertTrue(result.alpha_details["premultiplied_resize_used"])
        self.assertTrue(result.alpha_details["fully_transparent_rgb_zero"])

    def test_non_normal_exif_orientation_fails_closed(self) -> None:
        source = self.root / "oriented.jpg"
        exif = Image.Exif()
        exif[274] = 6
        Image.new("RGB", (40, 20), (90, 120, 160)).save(source, format="JPEG", exif=exif.tobytes())
        request = self.base_request(source, "oriented-out", "smoke-orientation", "RESIZE_REDUCTION", "SAME_FORMAT_HIGH_QUALITY", "VALIDATION_STRICT")
        request.update(scale_ratio=0.5, resize_policy="LANCZOS_HIGH_QUALITY")
        result = process_image_compression(request)
        self.assertEqual(result.technical_status, TechnicalStatus.CANNOT_MEET_SAFELY)
        self.assertEqual(result.failure_code, "EXIF_ORIENTATION_UNSUPPORTED")
        self.assertFalse(result.output_created)


if __name__ == "__main__":
    unittest.main()
