from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from engine.image_processing_routing import PreflightContractError, build_image_profile
from engine.image_processing_routing.profile import resolution_bucket


class ImageProfileImplementationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def save(self, name: str, *, size=(120, 80), image_format="PNG", mode="RGB") -> Path:
        path = self.root / name
        color = (20, 80, 140, 180) if mode == "RGBA" else (20, 80, 140)
        Image.new(mode, size, color).save(path, format=image_format)
        return path

    def test_landscape_profile(self):
        profile = build_image_profile(self.save("landscape.png", size=(120, 80)))
        self.assertEqual((profile["orientation"], profile["short_side"], profile["long_side"]), ("LANDSCAPE", 80, 120))

    def test_portrait_profile(self):
        profile = build_image_profile(self.save("portrait.jpg", size=(80, 120), image_format="JPEG"))
        self.assertEqual((profile["format"], profile["mime_type"], profile["orientation"]), ("JPEG", "image/jpeg", "PORTRAIT"))

    def test_square_profile(self):
        profile = build_image_profile(self.save("square.png", size=(90, 90)))
        self.assertEqual(profile["orientation"], "SQUARE")
        self.assertEqual(profile["aspect_ratio"], 1)

    def test_png_alpha_profile(self):
        profile = build_image_profile(self.save("alpha.png", mode="RGBA"))
        self.assertTrue(profile["has_alpha"])
        self.assertEqual(profile["processing_eligibility"], "ELIGIBLE_WITH_WARNING")
        self.assertIn("ALPHA_CHANNEL_PRESENT", profile["warnings"])

    def test_long_image_by_ratio(self):
        profile = build_image_profile(self.save("long.png", size=(100, 300)))
        self.assertTrue(profile["is_long_image"])
        self.assertIn("LONG_IMAGE_DETECTED", profile["warnings"])

    def test_height_4000_is_long_below_ratio_three(self):
        profile = build_image_profile(self.save("height-4000.jpg", size=(1600, 4000), image_format="JPEG"))
        self.assertTrue(profile["is_long_image"])
        self.assertAlmostEqual(profile["aspect_ratio"], 0.4)

    def test_ultra_wide_profile(self):
        profile = build_image_profile(self.save("ultra.png", size=(300, 100)))
        self.assertTrue(profile["is_ultra_wide"])
        self.assertIn("ULTRA_WIDE_IMAGE_DETECTED", profile["warnings"])

    def test_animated_png_reads_real_frame_count(self):
        path = self.root / "animated.png"
        first = Image.new("RGBA", (32, 24), (255, 0, 0, 128))
        second = Image.new("RGBA", (32, 24), (0, 255, 0, 128))
        first.save(path, format="PNG", save_all=True, append_images=[second], duration=100, loop=0)
        profile = build_image_profile(path)
        self.assertTrue(profile["is_animated"])
        self.assertEqual(profile["frame_count"], 2)
        self.assertEqual(profile["processing_eligibility"], "UNSUPPORTED")

    def test_multi_frame_tiff_reads_real_frame_count(self):
        path = self.root / "multi.tiff"
        first = Image.new("RGB", (32, 24), (255, 0, 0))
        second = Image.new("RGB", (32, 24), (0, 255, 0))
        first.save(path, format="TIFF", save_all=True, append_images=[second])
        profile = build_image_profile(path)
        self.assertEqual(profile["frame_count"], 2)
        self.assertIn("MULTI_FRAME_IMAGE_NOT_SUPPORTED", profile["warnings"])
        self.assertIn("FORMAT_NOT_SUPPORTED", profile["warnings"])

    def test_webp_is_objectively_profiled_but_unsupported(self):
        profile = build_image_profile(self.save("sample.webp", image_format="WEBP"))
        self.assertEqual(profile["mime_type"], "image/webp")
        self.assertEqual(profile["processing_eligibility"], "UNSUPPORTED")

    def test_corrupt_image_fails_complete_decode(self):
        path = self.root / "corrupt.png"
        path.write_bytes(b"not an image")
        with self.assertRaises(PreflightContractError) as raised:
            build_image_profile(path)
        self.assertEqual((raised.exception.status_code, raised.exception.code), (422, "IMAGE_DECODE_FAILED"))

    def test_resolution_bucket_boundaries(self):
        samples = {
            599: "SHORT_SIDE_LT_600",
            600: "SHORT_SIDE_600_1079",
            1079: "SHORT_SIDE_600_1079",
            1080: "SHORT_SIDE_1080_1439",
            1439: "SHORT_SIDE_1080_1439",
            1440: "SHORT_SIDE_1440_2159",
            2159: "SHORT_SIDE_1440_2159",
            2160: "SHORT_SIDE_2160_4319",
            4319: "SHORT_SIDE_2160_4319",
            4320: "SHORT_SIDE_GE_4320",
        }
        for value, expected in samples.items():
            with self.subTest(value=value):
                self.assertEqual(resolution_bucket(value), expected)

    def test_file_size_conversions_follow_binary_units(self):
        path = self.save("size.png")
        original = path.read_bytes()
        target_size = 1024 * 1024
        path.write_bytes(original + b"\0" * (target_size - len(original)))
        profile = build_image_profile(path)
        self.assertEqual((profile["size_bytes"], profile["size_kb"], profile["size_mb"]), (target_size, 1024, 1))


if __name__ == "__main__":
    unittest.main()
