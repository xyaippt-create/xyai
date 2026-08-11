from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from engine.image_diagnosis import ImageDiagnosisEngine


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sharp_pattern(width: int, height: int) -> np.ndarray:
    image = np.full((height, width, 3), 128, dtype=np.uint8)
    step = max(12, min(width, height) // 16)
    for y in range(0, height, step):
        color = 220 if (y // step) % 2 == 0 else 35
        cv2.line(image, (0, y), (width - 1, y), (color, color, color), 2)
    for x in range(0, width, step):
        color = 35 if (x // step) % 2 == 0 else 220
        cv2.line(image, (x, 0), (x, height - 1), (color, color, color), 2)
    cv2.putText(image, "HDDE D1", (width // 8, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (245, 245, 245), 3, cv2.LINE_AA)
    return image


def tonal_clipping_pattern(*, highlight: bool, shadow: bool) -> np.ndarray:
    image = sharp_pattern(1920, 1200)
    if highlight:
        image[:300, :, :] = 252
    if shadow:
        image[300:600, :, :] = 3
    return image


class ImageDiagnosisEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = ImageDiagnosisEngine()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_bgr(self, name: str, image: np.ndarray, *, jpeg_quality: int | None = None) -> Path:
        path = self.root / name
        params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality] if jpeg_quality is not None else []
        self.assertTrue(cv2.imwrite(str(path), image, params))
        return path

    def test_image_facts_exif_alpha_and_source_are_read_only(self) -> None:
        path = self.root / "facts.png"
        rgba = np.zeros((480, 640, 4), dtype=np.uint8)
        rgba[:, :, :3] = (30, 90, 160)
        rgba[:, :160, 3] = 0
        rgba[:, 160:, 3] = 255
        Image.fromarray(rgba, mode="RGBA").save(path, format="PNG")
        before_hash = sha256(path)
        before_mtime = path.stat().st_mtime_ns

        result = self.engine.diagnose(path).to_dict()
        facts = result["image_facts"]

        self.assertEqual(result["contract_version"], "hdde.image-diagnosis.v1")
        self.assertEqual(result["feature_key"], "image_diagnosis")
        self.assertEqual((facts["width"], facts["height"]), (640, 480))
        self.assertEqual(facts["aspect_ratio_label"], "4:3")
        self.assertEqual(facts["format"], "PNG")
        self.assertEqual(facts["color_mode"], "RGBA")
        self.assertTrue(facts["has_alpha"])
        self.assertAlmostEqual(facts["transparent_pixel_ratio"], 0.25, places=3)
        self.assertFalse(facts["exif"]["present"])
        self.assertEqual(sha256(path), before_hash)
        self.assertEqual(path.stat().st_mtime_ns, before_mtime)
        self.assertTrue(result["source_integrity"]["unchanged"])

        exif_path = self.root / "oriented.jpg"
        exif = Image.Exif()
        exif[271] = "HDDE Test Camera"
        exif[274] = 6
        Image.new("RGB", (40, 20), (120, 120, 120)).save(exif_path, format="JPEG", exif=exif)
        exif_result = self.engine.diagnose(exif_path).to_dict()["image_facts"]
        self.assertEqual((exif_result["stored_width"], exif_result["stored_height"]), (40, 20))
        self.assertEqual((exif_result["width"], exif_result["height"]), (20, 40))
        self.assertTrue(exif_result["exif"]["present"])
        self.assertEqual(exif_result["exif"]["fields"]["orientation"], 6)
        self.assertEqual(exif_result["exif"]["fields"]["make"], "HDDE Test Camera")

    def test_blur_metric_separates_obvious_blur_from_clear_pattern(self) -> None:
        sharp = sharp_pattern(1280, 960)
        blurred = cv2.GaussianBlur(sharp_pattern(320, 240), (0, 0), 8.0)
        sharp_result = self.engine.diagnose(self.write_bgr("sharp.png", sharp)).to_dict()
        blur_path = self.write_bgr("blurred.png", blurred)
        blur_hash = sha256(blur_path)
        blur_mtime = blur_path.stat().st_mtime_ns
        blurred_result = self.engine.diagnose(blur_path).to_dict()
        sharp_issue = sharp_result["quality_issues"]["blur"]
        blurred_issue = blurred_result["quality_issues"]["blur"]

        self.assertEqual(sharp_issue["status"], "not_detected")
        self.assertEqual(blurred_issue["status"], "detected")
        self.assertLess(blurred_issue["metrics"]["laplacian_variance"], sharp_issue["metrics"]["laplacian_variance"])
        self.assertEqual(blurred_result["recommended_action"]["primary_action"], "4K高清增强")
        self.assertEqual(sha256(blur_path), blur_hash)
        self.assertEqual(blur_path.stat().st_mtime_ns, blur_mtime)

    def test_exposure_highlight_shadow_and_color_cast_are_directional(self) -> None:
        bright = np.full((720, 1080, 3), 252, dtype=np.uint8)
        dark = np.full((720, 1080, 3), 3, dtype=np.uint8)
        tinted_rgb = np.full((1200, 1920, 3), (150, 126, 112), dtype=np.uint8)
        tinted = cv2.cvtColor(tinted_rgb, cv2.COLOR_RGB2BGR)

        bright_result = self.engine.diagnose(self.write_bgr("bright.png", bright)).to_dict()
        dark_result = self.engine.diagnose(self.write_bgr("dark.png", dark)).to_dict()
        tint_result = self.engine.diagnose(self.write_bgr("tint.png", tinted)).to_dict()

        self.assertEqual(bright_result["quality_issues"]["exposure"]["status"], "detected")
        self.assertEqual(bright_result["quality_issues"]["highlight_clipping"]["status"], "detected")
        self.assertEqual(bright_result["quality_issues"]["shadow_blocking"]["status"], "not_detected")
        self.assertEqual(dark_result["quality_issues"]["exposure"]["status"], "detected")
        self.assertEqual(dark_result["quality_issues"]["shadow_blocking"]["status"], "detected")
        self.assertEqual(dark_result["quality_issues"]["highlight_clipping"]["status"], "not_detected")
        self.assertEqual(tint_result["quality_issues"]["white_balance"]["status"], "detected")
        self.assertEqual(tint_result["quality_issues"]["color_cast"]["status"], "detected")
        self.assertEqual(tint_result["recommended_action"]["primary_action"], "颜色校正")

    def test_noise_and_jpeg_compression_metrics_are_explainable(self) -> None:
        rng = np.random.default_rng(54)
        noisy = np.clip(128 + rng.normal(0, 24, (720, 1080, 3)), 0, 255).astype(np.uint8)
        noisy_result = self.engine.diagnose(self.write_bgr("noise.png", noisy)).to_dict()
        self.assertEqual(noisy_result["quality_issues"]["noise"]["status"], "detected")
        self.assertGreater(noisy_result["quality_issues"]["noise"]["metrics"]["estimated_noise_sigma"], 5)

        gradient = np.tile(np.linspace(0, 255, 1024, dtype=np.uint8), (768, 1))
        patterned = np.dstack((gradient, np.roll(gradient, 3, axis=1), np.roll(gradient, 7, axis=1)))
        jpeg_result = self.engine.diagnose(self.write_bgr("compressed.jpg", patterned, jpeg_quality=4)).to_dict()
        compression = jpeg_result["quality_issues"]["compression_artifacts"]
        self.assertEqual(compression["status"], "detected")
        self.assertIn("block_boundary_ratio", compression["metrics"])
        self.assertTrue(compression["reason"])

    def test_normal_clear_sample_can_recommend_no_processing(self) -> None:
        result = self.engine.diagnose(self.write_bgr("normal.png", sharp_pattern(1920, 1200))).to_dict()
        self.assertEqual(result["quality_issues"]["resolution"]["status"], "not_detected")
        self.assertEqual(result["quality_issues"]["blur"]["status"], "not_detected")
        self.assertEqual(result["recommended_action"]["primary_action"], "无需处理")
        self.assertNotIn("score", result)

    def test_highlight_shadow_and_combined_clipping_map_to_color_correction(self) -> None:
        cases = (
            ("highlight", True, False),
            ("shadow", False, True),
            ("combined", True, True),
        )
        for name, highlight, shadow in cases:
            with self.subTest(name=name):
                result = self.engine.diagnose(
                    self.write_bgr(f"{name}.png", tonal_clipping_pattern(highlight=highlight, shadow=shadow))
                ).to_dict()
                issues = result["quality_issues"]
                self.assertEqual(issues["highlight_clipping"]["status"] == "detected", highlight)
                self.assertEqual(issues["shadow_blocking"]["status"] == "detected", shadow)
                recommendation = result["recommended_action"]
                self.assertEqual(recommendation["primary_action"], "颜色校正")
                reason = " ".join(recommendation["reasons"])
                self.assertIn("曝光/色调校正", reason)
                self.assertIn("可能无法完全恢复", reason)
                self.assertNotIn("无损恢复", reason)

    def test_existing_1080p_compression_and_color_recommendations_do_not_regress(self) -> None:
        standard = self.engine.diagnose(self.write_bgr("standard.png", sharp_pattern(800, 600))).to_dict()
        self.assertEqual(standard["recommended_action"]["primary_action"], "1080P标准增强")

        rng = np.random.default_rng(540)
        noisy = np.clip(sharp_pattern(800, 600) + rng.normal(0, 24, (600, 800, 3)), 0, 255).astype(np.uint8)
        safe = self.engine.diagnose(self.write_bgr("safe.png", noisy)).to_dict()
        self.assertEqual(safe["recommended_action"]["primary_action"], "1080P安全增强")

        large_bmp = self.write_bgr("large.bmp", sharp_pattern(2000, 1600))
        compression = self.engine.diagnose(large_bmp).to_dict()
        self.assertGreater(compression["image_facts"]["file_size_bytes"], 8 * 1024 * 1024)
        self.assertEqual(compression["recommended_action"]["primary_action"], "图片压缩")

        tinted_rgb = np.full((1200, 1920, 3), (150, 126, 112), dtype=np.uint8)
        tinted = cv2.cvtColor(tinted_rgb, cv2.COLOR_RGB2BGR)
        color = self.engine.diagnose(self.write_bgr("color.png", tinted)).to_dict()
        self.assertEqual(color["recommended_action"]["primary_action"], "颜色校正")


if __name__ == "__main__":
    unittest.main()
