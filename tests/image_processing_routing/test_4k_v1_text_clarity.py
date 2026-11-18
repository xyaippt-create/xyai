"""4K text clarity: detector gating, v4 identity outside text, guard and fallback (no SR engine)."""

import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from engine.image_processing_routing import four_k_v1 as fk

FONT = Path(r"C:\Windows\Fonts\msyh.ttc")


def _poster(width=640, height=360):
    image = Image.new("RGB", (width, height), (30, 30, 34))
    draw = ImageDraw.Draw(image)
    yy, xx = np.mgrid[:height, : width // 2]
    photo = np.dstack([(xx * 0.4 + 60) % 255, (yy * 0.5 + 40) % 255, np.full_like(xx, 120)]).astype(np.uint8)
    image.paste(Image.fromarray(photo), (0, 0))
    if FONT.is_file():
        draw.text((width // 2 + 10, 40), "影界高清交付", font=ImageFont.truetype(str(FONT), 22), fill=(240, 220, 170))
        draw.text((width // 2 + 10, 90), "2026年11月18日 全国上映", font=ImageFont.truetype(str(FONT), 14), fill=(240, 240, 240))
    return image


def _fake_sr(rgb: Image.Image) -> np.ndarray:
    native = rgb.resize((rgb.width * fk.FOUR_K_V1_SR_SCALE, rgb.height * fk.FOUR_K_V1_SR_SCALE), Image.Resampling.LANCZOS)
    sharp = cv2.addWeighted(np.asarray(native, np.float32), 1.8, cv2.GaussianBlur(np.asarray(native, np.float32), (0, 0), 2), -0.8, 0)
    return np.clip(sharp, 0, 255).astype(np.uint8)


class TextGateTests(unittest.TestCase):
    def test_detector_model_verified_and_finds_text_only_on_text_side(self):
        if fk._text_detector()[0] is None or not FONT.is_file():
            self.skipTest("text detection model or font not available")
        image = _poster()
        gate, info = fk._detect_text_gate(image, image.size)
        self.assertEqual(info["status"], "APPLIED")
        self.assertGreater(float(gate[30:120, 330:].max()), 0.9)
        self.assertEqual(float(gate[:, :300].max()), 0.0)

    def test_missing_or_mismatched_model_reports_unavailable(self):
        with mock.patch.object(fk, "_TEXT_DETECTOR", None), mock.patch.object(fk, "FOUR_K_V1_TEXT_MODEL_SHA256", "0" * 64):
            gate, info = fk._detect_text_gate(_poster(), (64, 36))
        self.assertIsNone(gate)
        self.assertEqual(info["status"], "DETECTOR_UNAVAILABLE")
        self.assertIn("校验不一致", info["reason"])


class FusionIdentityTests(unittest.TestCase):
    def setUp(self):
        self.rgb = _poster()
        plan = fk.plan_4k_v1_dimensions(*self.rgb.size)
        self.target = (plan["target_width"], plan["target_height"])
        self.sr = _fake_sr(self.rgb)
        self.maps = fk._structure_maps(self.rgb, self.target)
        self.v4 = fk._fuse_detail(self.sr, self.rgb, self.target, self.maps)

    def test_zero_gate_is_v4_pixel_for_pixel(self):
        out = fk._fuse_detail(self.sr, self.rgb, self.target, self.maps, np.zeros(self.target[::-1], np.float32))
        self.assertTrue(np.array_equal(out, self.v4))

    def test_changes_stay_inside_gate(self):
        gate = np.zeros(self.target[::-1], np.float32)
        gate[:, self.target[0] // 2 :] = 1.0
        out = fk._fuse_detail(self.sr, self.rgb, self.target, self.maps, gate)
        changed = np.abs(out.astype(int) - self.v4.astype(int)).max(axis=2) > 0
        self.assertFalse(changed[:, : self.target[0] // 2].any())
        self.assertTrue(changed[:, self.target[0] // 2 :].any())


class SharpenTextTests(unittest.TestCase):
    def test_result_stays_inside_local_base_range(self):
        base = np.zeros((80, 80), np.float32)
        base[:, 40:] = 1.0
        base = cv2.GaussianBlur(base, (0, 0), 4)
        sr = np.clip((base - 0.5) * 3 + 0.5, -0.5, 1.5).astype(np.float32)  # overshooting SR
        out = fk._sharpen_text(base.copy(), sr, base, np.ones_like(base), 1.0)
        self.assertGreaterEqual(float(out.min()), float(base.min()) - 1e-6)
        self.assertLessEqual(float(out.max()), float(base.max()) + 1e-6)
        self.assertGreater(float(np.abs(np.diff(out, axis=1)).max()), float(np.abs(np.diff(base, axis=1)).max()))

    def test_guard_rejects_thinned_strokes(self):
        base = np.ones((60, 120), np.float32)
        base[:, 50:70] = 0.0
        base = cv2.GaussianBlur(base, (0, 0), 3)
        thin = np.ones_like(base)
        thin[:, 58:62] = 0.0  # SR drew a much thinner stroke
        out = fk._sharpen_text(base.copy(), thin, base, np.ones_like(base), 1.0)
        self.assertLess(float(np.abs(out - base)[:, 50:70].mean()), 0.02)


if __name__ == "__main__":
    unittest.main()
