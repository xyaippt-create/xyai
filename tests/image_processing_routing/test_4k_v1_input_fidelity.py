"""4K distortion guards: input normalisation, transparent fill and chroma follow (no SR engine needed)."""

import io
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms

from engine.image_processing_routing import four_k_v1 as fk

RSWOP = Path(r"C:\Windows\System32\spool\drivers\color\RSWOP.icm")


class WorkingRgbTests(unittest.TestCase):
    def test_16bit_gray_is_scaled_not_clipped_to_white(self):
        ramp = np.tile(np.linspace(0, 65535, 256).astype(np.uint16), (8, 1))
        rgb, icc = fk._working_rgb(Image.fromarray(ramp), None)
        values = np.asarray(rgb)[0, :, 0].astype(int)
        self.assertEqual(rgb.mode, "RGB")
        self.assertIsNone(icc)
        self.assertLessEqual(int(np.abs(values - np.arange(256)).max()), 1)

    def test_rgb_profile_is_kept(self):
        srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        _, icc = fk._working_rgb(Image.new("RGB", (4, 4), (10, 20, 30)), srgb)
        self.assertEqual(icc, srgb)

    @unittest.skipUnless(RSWOP.is_file(), "Windows CMYK profile not present")
    def test_cmyk_with_profile_becomes_srgb_tagged_srgb(self):
        cmyk = Image.new("CMYK", (4, 4), (0, 255, 255, 0))  # process red
        rgb, icc = fk._working_rgb(cmyk, RSWOP.read_bytes())
        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        self.assertEqual(str(profile.profile.xcolor_space).strip(), "RGB")
        r, g, b = np.asarray(rgb)[0, 0].astype(int)
        self.assertGreater(r, 180)
        self.assertLess(g, 90)

    def test_unusable_non_rgb_profile_is_dropped(self):
        lab = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
        rgb, icc = fk._working_rgb(Image.new("RGB", (4, 4)), lab)
        self.assertEqual(rgb.mode, "RGB")
        self.assertIsNone(icc)


class TransparentFillTests(unittest.TestCase):
    def test_hidden_black_is_replaced_and_visible_pixels_kept(self):
        rgb = np.zeros((64, 64, 3), np.uint8)
        alpha = np.zeros((64, 64), np.uint8)
        rgb[16:48, 16:48] = (200, 180, 40)
        alpha[16:48, 16:48] = 255
        alpha[15, 16:48] = 128
        rgb[15, 16:48] = (200, 180, 40)
        filled = np.asarray(fk._fill_transparent_rgb(Image.fromarray(rgb), Image.fromarray(alpha)))
        visible = alpha > 0
        self.assertTrue(np.array_equal(filled[visible], rgb[visible]))
        self.assertTrue(np.all(np.abs(filled[~visible].astype(int) - (200, 180, 40)) <= 2))

    def test_fully_opaque_image_is_untouched(self):
        rgb = Image.new("RGB", (8, 8), (1, 2, 3))
        self.assertIs(fk._fill_transparent_rgb(rgb, Image.new("L", (8, 8), 255)), rgb)


class ChromaFollowTests(unittest.TestCase):
    def _ycc(self, rgb):
        import cv2

        return cv2.cvtColor(np.asarray(rgb, np.float32) / 255.0, cv2.COLOR_RGB2YCrCb)

    def test_flat_chroma_and_luma_are_untouched(self):
        gray = np.tile(np.linspace(0, 255, 96).astype(np.uint8), (64, 1))
        base = self._ycc(np.dstack([gray] * 3))
        before = base.copy()
        sharpened = np.clip(base[..., 0] * 1.1 - 0.05, 0, 1)
        fk._chroma_follow(base, before[..., 0].copy(), sharpened, 4.0)
        self.assertTrue(np.allclose(base[..., 1:], before[..., 1:], atol=1e-6))

    def test_sharpened_colour_edge_moves_chroma_within_source_range(self):
        import cv2

        img = np.zeros((40, 160, 3), np.uint8)
        img[:, :80] = (255, 230, 0)
        img[:, 80:] = (10, 20, 200)
        soft = cv2.GaussianBlur(img, (0, 0), 6)
        base = self._ycc(soft)
        base_luma = base[..., 0].copy()
        hard_luma = self._ycc(img)[..., 0]
        chroma_before = base[..., 1:].copy()
        fk._chroma_follow(base, base_luma, hard_luma, 4.0)
        target = self._ycc(img)[..., 1:]
        err_before = np.abs(chroma_before - target)[:, 70:90].mean()
        err_after = np.abs(base[..., 1:] - target)[:, 70:90].mean()
        self.assertLess(err_after, err_before * 0.6)
        self.assertGreaterEqual(base[..., 1:].min(), chroma_before.min() - 1e-6)
        self.assertLessEqual(base[..., 1:].max(), chroma_before.max() + 1e-6)


if __name__ == "__main__":
    unittest.main()


class SuperResolutionWatchdogTests(unittest.TestCase):
    def test_a_silent_hung_engine_is_killed_at_the_deadline(self):
        import subprocess
        import sys
        import tempfile
        import time
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            tool = Path(tmp) / "tool"
            (tool / "models").mkdir(parents=True)
            for name in ("realesrgan-ncnn-vulkan.exe", f"models/{fk.FOUR_K_V1_SR_MODEL}.param", f"models/{fk.FOUR_K_V1_SR_MODEL}.bin"):
                (tool / name).write_bytes(b"")
            launched = []
            real_popen = subprocess.Popen

            def hang(command, **options):
                # Stands in for an engine that hangs with stdout open and prints nothing.
                process = real_popen([sys.executable, "-c", "import time; time.sleep(60)"], **{**options, "cwd": tmp})
                launched.append(process)
                return process

            with mock.patch.object(fk, "_sr_tool_dir", return_value=tool),                  mock.patch.object(fk, "FOUR_K_V1_SR_TIMEOUT_SECONDS", 1),                  mock.patch.object(fk.subprocess, "Popen", side_effect=hang):
                started = time.monotonic()
                with self.assertRaises(fk.FourKV1ProcessingError) as raised:
                    fk._run_super_resolution(Image.new("RGB", (8, 8)), Path(tmp))
            self.assertLess(time.monotonic() - started, 15)
            self.assertIn("超时", str(raised.exception))
            self.assertIsNotNone(launched[0].poll())  # the engine process is gone
            self.assertEqual(list(Path(tmp).glob(".sr_*")), [])
