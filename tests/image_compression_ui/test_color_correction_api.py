import hashlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import cv2
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from backend.image_compression_api import register_image_compression_routes
from engine.color_correction import process_single_image
from engine.diagnostics.feedback_context import build_feedback_context
from engine.color_correction.core import (
    _metrics,
    _post_process_review,
    _review_noise,
    _review_sharpening_and_halo,
    _review_skin_tone,
    _review_white_balance,
    _visual_severity,
)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def meeting_image(size=(480, 320)):
    image = Image.new("RGB", size, (205, 215, 230))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size[0], 140), fill=(235, 238, 240))
    draw.rectangle((55, 42, size[0] - 55, 122), fill=(238, 246, 252))
    draw.ellipse((170, 105, 310, 245), fill=(70, 57, 51))
    draw.rectangle((130, 190, 350, size[1]), fill=(30, 42, 58))
    draw.rectangle((20, 250, size[0] - 20, size[1]), fill=(50, 58, 70))
    return image


def auditorium_image(size=(640, 420)):
    image = Image.new("RGB", size, (42, 48, 56))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size[0], 105), fill=(166, 165, 158))
    draw.rectangle((112, 78, 528, 245), fill=(198, 25, 38))
    draw.rectangle((155, 112, 485, 132), fill=(246, 240, 225))
    for y in range(270, size[1], 36):
        for x in range(18, size[0], 58):
            draw.rounded_rectangle((x, y, x + 44, min(y + 24, size[1] - 1)), radius=6, fill=(55, 31, 28))
    return image


class ColorCorrectionCoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_dark_image_changes_real_pixels_without_touching_source(self):
        source = self.root / "dark.png"
        output = self.root / "dark_corrected.png"
        array = np.zeros((180, 240, 3), dtype=np.uint8)
        array[..., 0] = np.linspace(18, 72, 240, dtype=np.uint8)
        array[..., 1] = np.linspace(22, 78, 240, dtype=np.uint8)
        array[..., 2] = np.linspace(30, 86, 240, dtype=np.uint8)
        Image.fromarray(array).save(source)
        source_hash = sha256(source)
        result = process_single_image(source, output)
        self.assertTrue(output.is_file())
        self.assertNotEqual(result.output_sha256, source_hash)
        self.assertEqual(sha256(source), source_hash)
        with Image.open(output) as image:
            image.load()
            self.assertEqual(image.size, (240, 180))
            self.assertEqual(image.format, "PNG")
        self.assertGreater(result.after_metrics["mean_luminance"], result.before_metrics["mean_luminance"])

    def test_meeting_backlight_uses_local_foreground_lift_and_protects_highlights(self):
        source = self.root / "meeting.jpg"
        output = self.root / "meeting_corrected.jpg"
        meeting_image().save(source, quality=95)
        result = process_single_image(source, output)
        self.assertTrue(result.analysis["meeting_backlight_detected"])
        self.assertIn("检测到高亮背景与较暗人物/前景的明显亮度差", result.detected_issues)
        self.assertGreater(result.after_metrics["foreground_luminance"], result.before_metrics["foreground_luminance"] + 3)
        self.assertLessEqual(result.after_metrics["highlight_ratio"], result.before_metrics["highlight_ratio"] + 0.01)
        with Image.open(source) as before_image, Image.open(output) as after_image:
            before = np.asarray(before_image.convert("RGB"), dtype=np.float32)
            after = np.asarray(after_image.convert("RGB"), dtype=np.float32)
        delta = after.mean(axis=2) - before.mean(axis=2)
        foreground_delta = float(delta[175:300, 135:345].mean())
        background_delta = float(delta[35:120, 65:415].mean())
        self.assertGreater(foreground_delta, background_delta + 2.0)
        self.assertGreater(result.analysis["foreground_luminance_gain"], result.analysis["background_luminance_gain"] + 2.0)
        self.assertTrue(result.analysis["highlight_background_protection_enabled"])
        self.assertIn("LED屏与高亮背景保护", result.applied_actions)

    def test_auditorium_strategy_restores_depth_without_weakening_strong_screen_color(self):
        source = self.root / "auditorium.jpg"
        output = self.root / "auditorium_corrected.jpg"
        auditorium_image().save(source, quality=94)
        result = process_single_image(source, output)
        self.assertEqual(result.analysis["strategy_id"], "AUDITORIUM_STRONG_COLOR_DEPTH")
        self.assertFalse(result.analysis["person_region_reliably_detected"])
        self.assertTrue(result.analysis["foreground_local_adjustment_enabled"])
        self.assertTrue(result.analysis["strong_color_protection_enabled"])
        self.assertGreater(result.after_metrics["local_contrast"], result.before_metrics["local_contrast"])
        self.assertGreaterEqual(
            result.analysis["strong_color_saturation_after"],
            result.analysis["strong_color_saturation_before"] - 0.015,
        )
        self.assertEqual(result.analysis["post_process_review"]["status"], "PASS")
        self.assertEqual(result.analysis["visual_severity"], "STRONG")
        self.assertGreaterEqual(result.parameters["visual_gain"], 0.82)

    def test_mixed_light_people_strategy_separates_subject_and_background(self):
        source = self.root / "meeting_people.jpg"
        output = self.root / "meeting_people_corrected.jpg"
        meeting_image().save(source, quality=95)
        with patch("engine.color_correction.core._detect_faces", return_value=[(185, 108, 76, 76)]):
            result = process_single_image(source, output)
        self.assertEqual(result.analysis["strategy_id"], "MEETING_MIXED_LIGHT_PEOPLE")
        self.assertTrue(result.analysis["person_region_reliably_detected"])
        self.assertTrue(result.analysis["person_local_adjustment_enabled"])
        self.assertTrue(result.analysis["skin_tone_protection_enabled"])
        self.assertTrue(result.analysis["highlight_background_protection_enabled"])
        self.assertGreater(
            result.analysis["foreground_luminance_gain"],
            result.analysis["background_luminance_gain"] + 2.0,
        )
        self.assertEqual(result.analysis["visual_severity"], "STRONG")
        self.assertGreater(result.parameters["subject_target_gain"], 12.0)
        self.assertGreater(result.analysis["foreground_luminance_gain"], 8.0)

    def test_visual_severity_uses_measured_problems_without_sample_identity(self):
        normal = _visual_severity(
            {
                "shadow_ratio": 0.08,
                "midtone_point": 132.0,
                "local_contrast": 7.4,
                "dynamic_range": 185.0,
                "foreground_luminance": 128.0,
            },
            {"backlight_contrast": 4.0},
            {"strategy_id": "NORMAL_DESIGN_PROTECTION"},
            {"color_cast_magnitude": 0.5},
        )
        strong = _visual_severity(
            {
                "shadow_ratio": 0.31,
                "midtone_point": 78.0,
                "local_contrast": 4.1,
                "dynamic_range": 138.0,
                "foreground_luminance": 70.0,
            },
            {"backlight_contrast": 78.0},
            {"strategy_id": "BACKLIGHT_DEPTH_RECOVERY"},
            {"color_cast_magnitude": 1.0},
        )
        self.assertEqual(normal["visual_severity"], "NORMAL")
        self.assertEqual(normal["visual_gain"], 0.0)
        self.assertEqual(strong["visual_severity"], "STRONG")
        self.assertGreaterEqual(strong["visual_gain"], 0.82)
        self.assertNotIn("filename", strong)

    def test_soft_deviation_is_recorded_without_reducing_candidate(self):
        source = np.full((96, 128, 3), 128, dtype=np.uint8)
        candidate = np.clip(source.astype(np.int16) + 5, 0, 255).astype(np.uint8)
        focus = np.ones(source.shape[:2], dtype=np.float32)
        background = np.zeros(source.shape[:2], dtype=np.float32)
        corrected, review = _post_process_review(
            source,
            candidate,
            _metrics(source, focus, background),
            focus,
            background,
            np.zeros(source.shape[:2], dtype=np.float32),
            {
                "strategy_id": "TONAL_DEPTH_RECOVERY",
                "person_local_adjustment_enabled": False,
                "person_region_reliably_detected": False,
                "strong_color_protection_enabled": False,
                "white_balance_applied": False,
            },
        )
        self.assertFalse(review["hard_risks"])
        self.assertTrue(review["soft_deviations"])
        self.assertFalse(review["convergence_actions"])
        self.assertEqual(review["final_candidate_level"], "FULL")
        self.assertTrue(np.array_equal(corrected, candidate))

    def test_post_process_review_falls_back_to_source_when_candidate_breaks_color_and_depth(self):
        source = np.asarray(auditorium_image((320, 220)), dtype=np.uint8)
        candidate = np.full_like(source, 128)
        focus = np.ones(source.shape[:2], dtype=np.float32)
        background = np.zeros(source.shape[:2], dtype=np.float32)
        strong_color = np.ones(source.shape[:2], dtype=np.float32)
        corrected, review = _post_process_review(
            source,
            candidate,
            _metrics(source, focus, background),
            focus,
            background,
            strong_color,
            {
                "strategy_id": "AUDITORIUM_STRONG_COLOR_DEPTH",
                "person_local_adjustment_enabled": False,
                "strong_color_protection_enabled": True,
            },
        )
        self.assertTrue(review["rollback_applied"])
        self.assertEqual(review["selected_candidate_blend"], 0.0)
        self.assertEqual(review["status"], "PASS")
        self.assertGreater(len(review["attempts"]), 1)
        self.assertFalse(review["_selected_analysis"]["skin_local_convergence_applied"])
        self.assertTrue(np.array_equal(corrected, source))

    def test_white_balance_review_detects_worsening_and_reports_low_confidence(self):
        source = np.full((96, 128, 3), 128, dtype=np.uint8)
        candidate = source.copy()
        candidate[..., 0] = 158
        candidate[..., 1] = 122
        candidate[..., 2] = 102
        strong_color = np.zeros(source.shape[:2], dtype=np.float32)
        review = _review_white_balance(source, candidate, strong_color)
        self.assertEqual(review["status"], "RISK")
        self.assertGreater(review["after"]["cast_magnitude"], review["before"]["cast_magnitude"])

        saturated = np.zeros_like(source)
        saturated[..., 2] = 220
        low_confidence = _review_white_balance(saturated, saturated, strong_color)
        self.assertEqual(low_confidence["status"], "LOW_CONFIDENCE")
        self.assertNotEqual(low_confidence["status"], "PASS")

    def test_skin_tone_review_detects_shift_and_never_uses_full_image_without_person(self):
        source = np.full((100, 120, 3), (178, 132, 108), dtype=np.uint8)
        candidate = np.full_like(source, (225, 104, 55))
        face_mask = np.ones(source.shape[:2], dtype=np.float32)
        review = _review_skin_tone(
            source,
            candidate,
            face_mask,
            {"person_region_reliably_detected": True},
        )
        self.assertEqual(review["status"], "RISK")
        self.assertGreater(abs(review["delta"]["lab_a"]) + abs(review["delta"]["lab_b"]), 7.0)

        not_applicable = _review_skin_tone(
            source,
            candidate,
            np.zeros_like(face_mask),
            {"person_region_reliably_detected": False},
        )
        self.assertEqual(not_applicable["status"], "NOT_APPLICABLE")
        self.assertEqual(not_applicable["evidence_pixels"], 0)

    def test_noise_review_detects_dark_luma_and_chroma_noise_increase(self):
        source = np.full((120, 160, 3), 62, dtype=np.uint8)
        yy, xx = np.mgrid[0:120, 0:160]
        pattern = np.where((xx + yy) % 2 == 0, 14, -14).astype(np.int16)
        candidate = source.astype(np.int16)
        candidate[..., 0] += pattern
        candidate[..., 1] -= pattern
        candidate[..., 2] += pattern
        review = _review_noise(source, np.clip(candidate, 0, 255).astype(np.uint8))
        self.assertEqual(review["status"], "RISK")
        self.assertGreater(review["after"]["chroma_noise"], review["before"]["chroma_noise"])

    def test_sharpening_review_detects_edge_overshoot_and_halo(self):
        source = np.full((120, 180, 3), 38, dtype=np.uint8)
        source[:, 90:] = 210
        candidate = source.copy()
        candidate[:, 87:90] = 0
        candidate[:, 90:93] = 255
        review = _review_sharpening_and_halo(source, candidate)
        self.assertEqual(review["status"], "RISK")
        self.assertGreater(review["after"]["overshoot_ratio"], 0.0)

    def test_detected_risk_reduces_parameters_regenerates_and_rechecks(self):
        source = np.full((100, 140, 3), 128, dtype=np.uint8)
        focus = np.ones(source.shape[:2], dtype=np.float32)
        background = np.zeros(source.shape[:2], dtype=np.float32)
        strong_color = np.zeros(source.shape[:2], dtype=np.float32)
        face_mask = np.zeros(source.shape[:2], dtype=np.float32)
        generated_scales = []

        def factory(scales):
            generated_scales.append(dict(scales))
            strength = float(scales["white_balance"])
            candidate = source.astype(np.float32)
            candidate[..., 0] += 28.0 * strength
            candidate[..., 1] -= 5.0 * strength
            candidate[..., 2] -= 22.0 * strength
            return np.clip(candidate, 0, 255).astype(np.uint8), {"convergence_scales": dict(scales)}, {}

        initial, _, _ = factory({
            "tone": 1.0,
            "white_balance": 1.0,
            "shadow": 1.0,
            "person": 1.0,
            "detail": 1.0,
            "color": 1.0,
        })
        corrected, review = _post_process_review(
            source,
            initial,
            _metrics(source, focus, background),
            focus,
            background,
            strong_color,
            {
                "strategy_id": "COLOR_CAST_AND_TONE_BALANCE",
                "person_local_adjustment_enabled": False,
                "person_region_reliably_detected": False,
                "strong_color_protection_enabled": False,
                "white_balance_applied": True,
            },
            face_mask,
            factory,
        )
        self.assertTrue(review["post_review_complete"])
        self.assertIn("白平衡偏差风险", review["detected_risks"])
        self.assertTrue(review["convergence_actions"])
        self.assertGreater(len(generated_scales), 1)
        self.assertLess(generated_scales[-1]["white_balance"], 1.0)
        self.assertFalse(review["remaining_violations"])
        self.assertNotEqual(review["final_candidate_level"], "FULL")
        self.assertFalse(np.array_equal(corrected, initial))

    def test_skin_tone_risk_converges_locally_without_global_downgrade(self):
        source = np.full((100, 120, 3), (178, 132, 108), dtype=np.uint8)
        focus = np.ones(source.shape[:2], dtype=np.float32)
        background = np.zeros(source.shape[:2], dtype=np.float32)
        strong_color = np.zeros(source.shape[:2], dtype=np.float32)
        face_mask = np.zeros(source.shape[:2], dtype=np.float32)
        face_mask[25:75, 40:80] = 1.0
        face_mask = cv2.GaussianBlur(face_mask, (0, 0), sigmaX=6.0)
        generated_scales = []

        def factory(scales):
            generated_scales.append(dict(scales))
            candidate = np.clip(source.astype(np.float32) + 7.0, 0.0, 255.0)
            unsafe = np.full_like(source, (220, 120, 100), dtype=np.float32)
            local_strength = float(scales["skin"])
            local_mask = face_mask[..., None]
            local_candidate = source.astype(np.float32) * (1.0 - local_strength) + unsafe * local_strength
            candidate = candidate * (1.0 - local_mask) + local_candidate * local_mask
            return candidate.astype(np.uint8), {"convergence_scales": dict(scales)}, {}

        full = {"tone": 1.0, "white_balance": 1.0, "shadow": 1.0, "person": 1.0, "skin": 1.0, "detail": 1.0, "color": 1.0}
        initial, _, _ = factory(full)
        corrected, review = _post_process_review(
            source,
            initial,
            _metrics(source, focus, background),
            focus,
            background,
            strong_color,
            {
                "strategy_id": "MEETING_MIXED_LIGHT_PEOPLE",
                "person_local_adjustment_enabled": False,
                "person_region_reliably_detected": True,
                "strong_color_protection_enabled": False,
                "white_balance_applied": True,
            },
            face_mask,
            factory,
        )
        self.assertIn("肤色偏差风险", review["detected_risks"])
        self.assertTrue(any("仅降低肤色区域" in action for action in review["convergence_actions"]))
        self.assertGreater(len(generated_scales), 1)
        self.assertLess(generated_scales[-1]["skin"], 1.0)
        for key in ("tone", "white_balance", "shadow", "person", "detail", "color"):
            self.assertEqual(generated_scales[-1][key], 1.0, msg=review["attempts"])
        self.assertFalse(review["remaining_violations"])
        self.assertEqual(review["selected_candidate_scope"], "SKIN_LOCAL")
        outside_delta = np.abs(corrected[:20, :20].astype(np.int16) - initial[:20, :20].astype(np.int16))
        self.assertLessEqual(int(outside_delta.max()), 1)

    def test_noise_risk_reduces_shadow_and_detail_before_recheck(self):
        source = np.full((120, 160, 3), 62, dtype=np.uint8)
        focus = np.ones(source.shape[:2], dtype=np.float32)
        background = np.zeros(source.shape[:2], dtype=np.float32)
        strong_color = np.zeros(source.shape[:2], dtype=np.float32)
        yy, xx = np.mgrid[0:120, 0:160]
        pattern = np.where((xx + yy) % 2 == 0, 15.0, -15.0)
        generated_scales = []

        def factory(scales):
            generated_scales.append(dict(scales))
            strength = min(float(scales["shadow"]), float(scales["detail"]))
            candidate = source.astype(np.float32)
            candidate[..., 0] += pattern * strength
            candidate[..., 1] -= pattern * strength
            candidate[..., 2] += pattern * strength
            return np.clip(candidate, 0, 255).astype(np.uint8), {"convergence_scales": dict(scales)}, {}

        full = {"tone": 1.0, "white_balance": 1.0, "shadow": 1.0, "person": 1.0, "detail": 1.0, "color": 1.0}
        initial, _, _ = factory(full)
        _, review = _post_process_review(
            source,
            initial,
            _metrics(source, focus, background),
            focus,
            background,
            strong_color,
            {
                "strategy_id": "TONAL_DEPTH_RECOVERY",
                "person_local_adjustment_enabled": False,
                "person_region_reliably_detected": False,
                "strong_color_protection_enabled": False,
                "white_balance_applied": False,
            },
            np.zeros_like(focus),
            factory,
        )
        self.assertIn("暗部或彩色噪点放大风险", review["detected_risks"])
        self.assertTrue(any("阴影提亮" in action for action in review["convergence_actions"]))
        self.assertLess(generated_scales[-1]["shadow"], 1.0)
        self.assertLess(generated_scales[-1]["detail"], 1.0)

    def test_halo_risk_reduces_tone_and_detail_before_recheck(self):
        source = np.full((120, 180, 3), 38, dtype=np.uint8)
        source[:, 90:] = 210
        focus = np.ones(source.shape[:2], dtype=np.float32)
        background = np.zeros(source.shape[:2], dtype=np.float32)
        strong_color = np.zeros(source.shape[:2], dtype=np.float32)
        generated_scales = []

        def factory(scales):
            generated_scales.append(dict(scales))
            strength = min(float(scales["tone"]), float(scales["detail"]))
            candidate = source.astype(np.float32)
            candidate[:, 87:90] -= 45.0 * strength
            candidate[:, 90:93] += 45.0 * strength
            return np.clip(candidate, 0, 255).astype(np.uint8), {"convergence_scales": dict(scales)}, {}

        full = {"tone": 1.0, "white_balance": 1.0, "shadow": 1.0, "person": 1.0, "detail": 1.0, "color": 1.0}
        initial, _, _ = factory(full)
        _, review = _post_process_review(
            source,
            initial,
            _metrics(source, focus, background),
            focus,
            background,
            strong_color,
            {
                "strategy_id": "TONAL_DEPTH_RECOVERY",
                "person_local_adjustment_enabled": False,
                "person_region_reliably_detected": False,
                "strong_color_protection_enabled": False,
                "white_balance_applied": False,
            },
            np.zeros_like(focus),
            factory,
        )
        self.assertIn("锐化过冲或光晕风险", review["detected_risks"])
        self.assertTrue(any("锐化" in action for action in review["convergence_actions"]))
        self.assertLess(generated_scales[-1]["tone"], 1.0)
        self.assertLess(generated_scales[-1]["detail"], 1.0)

    def test_trusted_neutral_pixels_drive_measured_white_balance_correction(self):
        source = self.root / "warm_cast.png"
        output = self.root / "warm_cast_corrected.png"
        base = np.linspace(85, 205, 260, dtype=np.float32)[None, :, None]
        warm = np.concatenate([base + 13, base + 2, base - 11], axis=2)
        warm = np.repeat(np.clip(warm, 0, 255).astype(np.uint8), 180, axis=0)
        Image.fromarray(warm).save(source)
        result = process_single_image(source, output)
        with Image.open(output) as image:
            corrected = np.asarray(image.convert("RGB"), dtype=np.float32)
        before_spread = float(warm.mean(axis=(0, 1)).max() - warm.mean(axis=(0, 1)).min())
        after_spread = float(corrected.mean(axis=(0, 1)).max() - corrected.mean(axis=(0, 1)).min())
        self.assertTrue(result.analysis["white_balance_applied"])
        self.assertGreaterEqual(result.analysis["white_balance_confidence"], 0.35)
        self.assertLess(after_spread, before_spread)
        self.assertIn("基于可信中性色的白平衡校正", result.applied_actions)

    def test_normal_image_is_conservative_and_alpha_is_exact(self):
        source = self.root / "normal.png"
        output = self.root / "normal_corrected.png"
        rgba = np.zeros((120, 160, 4), dtype=np.uint8)
        rgba[..., 0] = 130
        rgba[..., 1] = 122
        rgba[..., 2] = 116
        rgba[..., 3] = np.arange(160, dtype=np.uint8)[None, :]
        Image.fromarray(rgba, mode="RGBA").save(source)
        result = process_single_image(source, output)
        self.assertFalse(result.analysis["meeting_backlight_detected"])
        self.assertLess(abs(result.after_metrics["mean_luminance"] - result.before_metrics["mean_luminance"]), 8)
        review = result.analysis["post_process_review"]
        self.assertTrue(review["post_review_complete"])
        self.assertFalse(review["remaining_violations"])
        self.assertIn(review["white_balance_review"]["status"], {"PASS", "LOW_CONFIDENCE"})
        self.assertEqual(review["skin_tone_review"]["status"], "NOT_APPLICABLE")
        for field in ("detected_risks", "convergence_actions", "rollback_reason", "final_candidate_level"):
            self.assertIn(field, review)
        with Image.open(output) as image:
            self.assertTrue(np.array_equal(np.asarray(image.getchannel("A")), rgba[..., 3]))

    def test_well_exposed_textured_image_uses_protective_low_strength_processing(self):
        source = self.root / "normal_textured.png"
        output = self.root / "normal_textured_corrected.png"
        yy, xx = np.mgrid[0:180, 0:260]
        luminance = 34 + xx * (185 / 259) + ((xx // 8 + yy // 8) % 2) * 12
        rgb = np.stack([luminance, luminance, luminance], axis=2)
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        Image.fromarray(rgb).save(source)
        result = process_single_image(source, output)
        self.assertTrue(result.analysis["normal_image_detected"])
        self.assertEqual(result.analysis["strategy_id"], "NORMAL_DESIGN_PROTECTION")
        self.assertEqual(result.parameters["contrast_strength"], 0.0)
        self.assertEqual(result.parameters["local_contrast_strength"], 0.0)
        self.assertEqual(result.parameters["clarity_strength"], 0.0)
        self.assertEqual(result.analysis["visual_severity"], "NORMAL")
        self.assertEqual(result.parameters["visual_gain"], 0.0)
        self.assertIn("正常图片采用低强度保护性处理，避免不必要改色", result.improvements)
        self.assertEqual(result.after_metrics, {key: value for key, value in result.before_metrics.items() if key != "low_key_design_detected"})
        with Image.open(source) as before_image, Image.open(output) as after_image:
            self.assertTrue(np.array_equal(np.asarray(before_image), np.asarray(after_image)))

    def test_low_key_brand_design_preserves_black_point_and_color_intent(self):
        source = self.root / "low_key_brand.png"
        output = self.root / "low_key_brand_corrected.png"
        image = Image.new("RGB", (320, 220), (2, 3, 5))
        draw = ImageDraw.Draw(image)
        draw.rectangle((25, 32, 295, 52), fill=(224, 182, 92))
        draw.ellipse((85, 72, 235, 205), fill=(16, 28, 88), outline=(245, 222, 178), width=8)
        draw.line((25, 195, 295, 80), fill=(250, 245, 230), width=4)
        image.save(source)
        result = process_single_image(source, output)
        self.assertTrue(result.before_metrics["low_key_design_detected"])
        self.assertTrue(result.analysis["normal_image_detected"])
        self.assertFalse(result.analysis["white_balance_applied"])
        self.assertEqual(result.analysis["color_cast"], "低调设计色彩意图保护")
        self.assertLess(abs(result.after_metrics["mean_luminance"] - result.before_metrics["mean_luminance"]), 1.0)
        self.assertLessEqual(abs(result.after_metrics["black_point"] - result.before_metrics["black_point"]), 1.0)


class ColorCorrectionApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.tmp = self.root / "tmp"
        self.formal = self.root / "formal"
        self.tmp.mkdir()
        self.formal.mkdir()
        self.opened = []
        self.runtime_events = []
        self.now = 1_800_000_000.0
        self.feedback_runtime = {
            "app_version": "V0.5.4-dev",
            "build_id": "V0.5.4-dev+test123.clean.20260810T000000000Z",
            "runtime_id": "RUN-20260810T000000-TEST123456",
            "runtime_status": "ready",
            "backend_health": "healthy",
            "backend_connection_status": "connected",
            "frontend_connection_status": "not_available",
            "settings_status": "loaded",
            "formal_root_status": "ready",
            "runtime_log_reference": "诊断/日志/hdde.log",
            "runtime_log_available": True,
        }

        def capture_runtime_event(event, **fields):
            self.runtime_events.append({"event": event, **fields})

        self.capture_runtime_event = capture_runtime_event

        def validate_output_root(value):
            target = Path(value).resolve()
            target.mkdir(parents=True, exist_ok=True)
            return {"valid": True, "writable": True, "normalized_path": str(target)}

        app = FastAPI()
        self.state = register_image_compression_routes(
            app,
            user_dirs_provider=lambda: {"normal_output_dir": self.formal / "输出", "tmp_dir": self.tmp},
            now_provider=lambda: self.now,
            folder_opener=self.opened.append,
            output_settings_provider=lambda: {"built_in_default_root": str(self.formal), "saved_default_root": str(self.formal)},
            output_dir_validator=validate_output_root,
            feedback_runtime_provider=lambda: dict(self.feedback_runtime),
            runtime_event_logger=self.capture_runtime_event,
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def intake(self, image=None, filename="meeting.jpg"):
        stream = io.BytesIO()
        (image or meeting_image()).save(stream, format="JPEG", quality=95)
        response = self.client.post("/api/image-compression/intake", files={"file": (filename, stream.getvalue(), "image/jpeg")})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def test_real_success_lifecycle_output_actions_and_feedback(self):
        intake = self.intake()
        response = self.client.post("/api/color-correction/run", json={"source_token": intake["source_token"]})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        task = data["task"]
        self.assertEqual([item["status"] for item in task["lifecycle"]], ["pending", "processing", "completed"])
        self.assertEqual(task["progress"], 100)
        self.assertEqual(task["operation_mode"], "AUTO_COLOR_CORRECTION")
        self.assertIsNone(task["failure_reason"])
        self.assertIn("原图哈希保持不变，未覆盖或修改原图", data["result"]["improvements"])
        self.assertIn("输出已完成存在、解码、尺寸、格式与摘要验证", data["result"]["improvements"])
        output = Path(data["ui"]["output_path"])
        self.assertTrue(output.is_file())
        self.assertEqual(output.parent, (self.formal / "颜色校正").resolve())
        for compression_directory in ("PNG无损压缩", "尺寸缩小", "上传适配"):
            self.assertFalse((self.formal / compression_directory).exists())
        with Image.open(output) as image:
            image.load()
            self.assertEqual(image.size, (480, 320))
        self.assertIn(task["task_id"], self.state["task_registry"])
        self.assertNotIn("color_task_registry", self.state)

        task_events = [item for item in self.runtime_events if item.get("task_id") == task["task_id"]]
        self.assertEqual(
            [item["event"] for item in task_events],
            ["TASK_CREATED", "PROCESS_STARTED", "COLOR_CORRECTION_TASK_STARTED", "PROCESS_SUCCEEDED", "RESULT_REGISTERED", "COLOR_CORRECTION_TASK_SUCCEEDED"],
        )
        self.assertTrue(all(item["feature"] == "color_correction" for item in task_events))
        self.assertEqual(task["feature_key"], "color_correction")
        self.assertNotEqual(task["task_id"], task["result_id"])
        self.assertEqual(data["result"]["result_id"], task["result_id"])
        self.assertEqual(data["result"]["task_id"], task["task_id"])
        self.assertEqual(task_events[-2]["result_id"], task["result_id"])

        opened_output = self.client.post("/api/color-correction/open-output", json={"task_id": task["task_id"]})
        opened_folder = self.client.post("/api/color-correction/open-output-folder", json={"task_id": task["task_id"]})
        self.assertEqual((opened_output.status_code, opened_folder.status_code), (200, 200))
        self.assertEqual(self.opened, [str(output.resolve()), str(output.parent.resolve())])

        report_response = self.client.post("/api/color-correction/feedback-report", json={
            "task_id": task["task_id"],
            "category": "人物仍然偏暗",
            "description": "请复核人物暗部。",
        })
        self.assertEqual(report_response.status_code, 200, report_response.text)
        report = report_response.json()["data"]
        report_path = Path(report["report_path"])
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
        serialized = json.dumps(report_data, ensure_ascii=False)
        self.assertNotIn(str(self.root), serialized)
        self.assertFalse(report_data["privacy"]["source_image_included"])
        self.assertFalse(report_data["privacy"]["output_image_included"])
        self.assertFalse(report_data["privacy"]["external_upload_performed"])
        self.assertIn("background_luminance_gain", report_data["processing"]["analysis"])
        self.assertIn("white_balance_confidence", report_data["processing"]["analysis"])
        self.assertIn("local_contrast", report_data["processing"]["before_metrics"])
        self.assertIn("strategy_id", report_data["processing"]["analysis"])
        self.assertIn("post_process_review", report_data["processing"]["analysis"])
        self.assertIn("strong_color_saturation_before", report_data["processing"]["analysis"])
        self.assertEqual(report_data["task"]["lifecycle"][-1]["status"], "completed")
        self.assertEqual(report_data["context"]["feature"]["key"], "color_correction")
        self.assertEqual(report_data["context"]["task_id"], task["task_id"])
        self.assertEqual(report_data["context"]["result_id"], task["result_id"])
        self.assertEqual(report_data["context"]["stage"], "completed")
        self.assertEqual(report_data["context"]["status"], "completed")
        self.assertEqual(report_data["context"]["runtime"]["app_version"], "V0.5.4-dev")
        self.assertEqual(report_data["context"]["runtime"]["runtime_id"], "RUN-20260810T000000-TEST123456")
        self.assertEqual(report_data["context"]["runtime"]["backend_health"], "healthy")
        self.assertEqual(report_data["context"]["runtime"]["runtime_log_reference"], "诊断/日志/hdde.log")
        self.assertEqual(report["context_preview"]["feature_name"], "单图自动颜色校正")
        self.assertTrue(report["context_preview"]["task_reference_available"])
        self.assertTrue(report["context_preview"]["result_reference_available"])
        self.assertEqual(report_data["context"]["purpose"], "COLOR_FIDELITY_CORRECTION")
        self.assertEqual(report_data["context"]["route_family"], "color_correction")
        self.assertEqual(report_data["context"]["safe_input_metadata"]["format"], "JPEG")
        self.assertRegex(report_data["files"]["source_reference"], r"^file_[0-9a-f]{12}$")
        self.assertNotIn("meeting.jpg", serialized)
        report_events = [item for item in self.runtime_events if item["event"] == "FEEDBACK_REPORT_GENERATED"]
        self.assertEqual(len(report_events), 1)
        self.assertEqual(report_events[0]["task_id"], task["task_id"])
        self.assertEqual(report_events[0]["runtime_log_reference"], "诊断/日志/hdde.log")
        download = self.client.get(report["download_url"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(hashlib.sha256(download.content).hexdigest(), report["report_sha256"])

    def test_controlled_runtime_failure_context_enters_real_task_feedback_report(self):
        self.feedback_runtime.update({
            "runtime_status": "degraded",
            "backend_health": "unavailable",
            "backend_connection_status": "failed",
            "frontend_connection_status": "proxy_failed",
            "error_type": "ImportError",
            "error_code": "ONNXRUNTIME_IMPORT_FAILED",
            "error_stage": "backend_startup",
            "error_summary": r"onnxruntime import failed at C:\private\runtime; token=secret-value",
        })
        intake = self.intake(filename="runtime-context.jpg")
        task_data = self.client.post("/api/color-correction/run", json={"source_token": intake["source_token"]}).json()["data"]
        task_id = task_data["task"]["task_id"]

        response = self.client.post(
            "/api/color-correction/feedback-report",
            json={"task_id": task_id, "category": "启动或运行异常", "description": "后端连接异常"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        report_path = Path(response.json()["data"]["report_path"])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        runtime = report["context"]["runtime"]
        self.assertEqual(runtime["runtime_status"], "degraded")
        self.assertEqual(runtime["backend_health"], "unavailable")
        self.assertEqual(runtime["error_code"], "ONNXRUNTIME_IMPORT_FAILED")
        self.assertEqual(runtime["error_stage"], "backend_startup")
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("secret-value", serialized)
        self.assertNotIn(r"C:\private", serialized)

    def test_processing_failure_uses_same_task_and_leaves_no_output(self):
        self.client.close()
        app = FastAPI()

        def validator(value):
            target = Path(value).resolve()
            target.mkdir(parents=True, exist_ok=True)
            return {"valid": True, "writable": True, "normalized_path": str(target)}

        with patch("engine.color_correction.process_single_image", side_effect=RuntimeError("受控编码失败")):
            state = register_image_compression_routes(
                app,
                user_dirs_provider=lambda: {"normal_output_dir": self.formal / "输出", "tmp_dir": self.tmp},
                now_provider=lambda: self.now,
                output_settings_provider=lambda: {"built_in_default_root": str(self.formal), "saved_default_root": str(self.formal)},
                output_dir_validator=validator,
                runtime_event_logger=self.capture_runtime_event,
            )
        self.client = TestClient(app)
        intake = self.intake(filename="某集团并购终稿.jpg")
        response = self.client.post("/api/color-correction/run", json={"source_token": intake["source_token"]})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual([item["status"] for item in data["task"]["lifecycle"]], ["pending", "processing", "failed"])
        self.assertEqual(data["task"]["failure_reason"], "受控编码失败")
        self.assertLess(data["task"]["progress"], 100)
        self.assertIsNone(data["task"]["output_path"])
        self.assertIsNone(data["result"])
        self.assertEqual(list((self.formal / "颜色校正").glob("*")), [])
        self.assertIn(data["task"]["task_id"], state["task_registry"])
        failed_events = [item for item in self.runtime_events if item["event"] == "COLOR_CORRECTION_TASK_FAILED"]
        self.assertEqual(len(failed_events), 1)
        self.assertEqual(failed_events[0]["task_id"], data["task"]["task_id"])
        self.assertEqual(failed_events[0]["stage"], "color_correction_execution")
        self.assertEqual(failed_events[0]["reason"], "受控编码失败")
        self.assertRegex(failed_events[0]["error_id"], r"^ERR-\d{8}-[0-9A-F]{8}$")
        self.assertRegex(failed_events[0]["error_fingerprint"], r"^EFP-[0-9A-F]{16}$")
        self.assertEqual(failed_events[0]["exception_type"], "RuntimeError")
        self.assertIn("backend/image_compression_api.py", failed_events[0]["code_location"])
        failed_record = state["task_registry"][data["task"]["task_id"]]
        self.assertEqual(failed_record["error_context"]["error_id"], failed_events[0]["error_id"])
        self.assertEqual(failed_record["task_context"]["feature_key"], "color_correction")
        self.assertEqual(failed_record["task_context"]["purpose"], "COLOR_FIDELITY_CORRECTION")
        failed_record["related_events"] = [
            event for event in self.runtime_events if event.get("task_id") == data["task"]["task_id"]
        ]
        context = build_feedback_context(
            failed_record,
            runtime=self.feedback_runtime,
            user_description="处理失败，请定位。",
        )
        self.assertEqual(context["error"]["error_id"], failed_events[0]["error_id"])
        self.assertEqual(context["error"]["error_fingerprint"], failed_events[0]["error_fingerprint"])
        self.assertEqual(context["error"]["exception_type"], "RuntimeError")
        self.assertIn("backend/image_compression_api.py", context["error"]["code_location"])
        self.assertEqual(context["error"]["stage"], "color_correction_execution")
        self.assertEqual(context["safe_input_metadata"]["format"], "JPEG")
        self.assertEqual(len(context["related_events"]), 5)
        self.assertNotIn("某集团并购终稿.jpg", json.dumps(context, ensure_ascii=False))

    def test_batch_queue_isolates_one_failure_and_completes_remaining_images(self):
        self.client.close()
        app = FastAPI()

        def validator(value):
            target = Path(value).resolve()
            target.mkdir(parents=True, exist_ok=True)
            return {"valid": True, "writable": True, "normalized_path": str(target)}

        real_process = process_single_image
        call_count = {"value": 0}

        def isolated_processor(source_path, output_path):
            call_count["value"] += 1
            if call_count["value"] == 2:
                raise RuntimeError("受控单图失败")
            return real_process(source_path, output_path)

        with patch("engine.color_correction.process_single_image", side_effect=isolated_processor):
            state = register_image_compression_routes(
                app,
                user_dirs_provider=lambda: {"normal_output_dir": self.formal / "输出", "tmp_dir": self.tmp},
                now_provider=lambda: self.now,
                output_settings_provider=lambda: {"built_in_default_root": str(self.formal), "saved_default_root": str(self.formal)},
                output_dir_validator=validator,
                runtime_event_logger=self.capture_runtime_event,
            )
            self.client = TestClient(app)
            source_tokens = [
                self.intake(meeting_image(), filename="batch_meeting.jpg")["source_token"],
                self.intake(auditorium_image(), filename="batch_failure.jpg")["source_token"],
                self.intake(meeting_image((520, 340)), filename="batch_final.jpg")["source_token"],
            ]
            response = self.client.post("/api/color-correction/batches", json={"source_tokens": source_tokens})
            self.assertEqual(response.status_code, 202, response.text)
            batch_id = response.json()["data"]["batch_id"]

            deadline = time.monotonic() + 20
            batch = None
            while time.monotonic() < deadline:
                status_response = self.client.get(f"/api/color-correction/batches/{batch_id}")
                self.assertEqual(status_response.status_code, 200, status_response.text)
                batch = status_response.json()["data"]
                if batch["status"] in {"completed", "failed"}:
                    break
                time.sleep(0.05)

            self.assertIsNotNone(batch)
            self.assertEqual(batch["status"], "completed")
            self.assertEqual(batch["progress"], 100)
            self.assertEqual(batch["total_count"], 3)
            self.assertEqual(batch["completed_count"], 2)
            self.assertEqual(batch["failed_count"], 1)
            self.assertEqual(batch["confirmed_count"], 0)
            self.assertEqual(batch["pending_review_count"], 2)
            self.assertEqual([item["task"]["status"] for item in batch["items"]], ["completed", "failed", "completed"])
            self.assertEqual(batch["items"][1]["task"]["failure_reason"], "受控单图失败")
            self.assertIsNone(batch["items"][1]["ui"]["output_path"])
            completed_outputs = [Path(item["ui"]["output_path"]) for item in batch["items"] if item["task"]["status"] == "completed"]
            self.assertEqual(len(completed_outputs), 2)
            self.assertTrue(all(path.is_file() for path in completed_outputs))
            self.assertEqual(len({path.name for path in completed_outputs}), 2)
            self.assertEqual(call_count["value"], 3)
            self.assertIn(batch_id, state["color_batch_registry"])
            listed = self.client.get("/api/color-correction/batches").json()["data"]
            self.assertEqual(listed["count"], 1)
            self.assertEqual(listed["batches"][0]["batch_id"], batch_id)

            batch_events = [item for item in self.runtime_events if item.get("batch_id") == batch_id]
            batch_event_names = [item["event"] for item in batch_events]
            self.assertIn("COLOR_BATCH_QUEUED", batch_event_names)
            self.assertIn("COLOR_BATCH_STARTED", batch_event_names)
            self.assertIn("COLOR_BATCH_COMPLETED", batch_event_names)
            completed_event = next(item for item in batch_events if item["event"] == "COLOR_BATCH_COMPLETED")
            self.assertEqual(completed_event["completed_count"], 2)
            self.assertEqual(completed_event["failed_count"], 1)
            self.assertTrue(all(item.get("feature_key") == "color_correction" for item in batch_events))

            reviewed_item = batch["items"][0]
            reviewed_task_id = reviewed_item["task"]["task_id"]
            reviewed_output = Path(reviewed_item["ui"]["output_path"])
            output_sha_before = hashlib.sha256(reviewed_output.read_bytes()).hexdigest()
            output_mtime_before = reviewed_output.stat().st_mtime_ns
            other_task_id = batch["items"][2]["task"]["task_id"]

            review_response = self.client.post(
                f"/api/color-correction/tasks/{reviewed_task_id}/review",
                json={"status": "confirmed"},
            )
            self.assertEqual(review_response.status_code, 200, review_response.text)
            self.assertEqual(review_response.json()["data"]["review"]["status"], "confirmed")
            self.assertIsNotNone(review_response.json()["data"]["review"]["reviewed_at"])
            self.assertEqual(hashlib.sha256(reviewed_output.read_bytes()).hexdigest(), output_sha_before)
            self.assertEqual(reviewed_output.stat().st_mtime_ns, output_mtime_before)

            reviewed_batch = self.client.get(f"/api/color-correction/batches/{batch_id}").json()["data"]
            self.assertEqual(reviewed_batch["confirmed_count"], 1)
            self.assertEqual(reviewed_batch["pending_review_count"], 1)
            review_by_task = {item["task"]["task_id"]: item["review"]["status"] for item in reviewed_batch["items"]}
            self.assertEqual(review_by_task[reviewed_task_id], "confirmed")
            self.assertEqual(review_by_task[other_task_id], "pending")
            review_events = [item for item in self.runtime_events if item["event"] == "QUALITY_REVIEW_UPDATED"]
            self.assertEqual(len(review_events), 1)
            self.assertEqual(review_events[0]["task_id"], reviewed_task_id)
            self.assertEqual(review_events[0]["batch_id"], batch_id)
            self.assertEqual(review_events[0]["status"], "confirmed")
            for item in state["color_batch_registry"][batch_id]["task_ids"]:
                record = state["task_registry"][item]
                self.assertEqual(record["feature_key"], "color_correction")
                self.assertEqual(record["task_context"]["task_id"], item)
                self.assertEqual(record["task_context"]["feature_key"], "color_correction")
                self.assertEqual(record["task_context"]["purpose"], "COLOR_FIDELITY_CORRECTION")
                self.assertEqual(record["task_context"]["batch_id"], batch_id)
                if record.get("result"):
                    self.assertEqual(record["result"]["feature_key"], "color_correction")
                feedback_context = build_feedback_context(record, runtime=self.feedback_runtime)
                self.assertEqual(feedback_context["feature_key"], "color_correction")
                task_events = [event for event in self.runtime_events if event.get("task_id") == item]
                self.assertTrue(task_events)
                self.assertTrue(all(event["feature_key"] == "color_correction" for event in task_events))
                self.assertTrue(all(event["feature"] == "color_correction" for event in task_events))
                self.assertTrue(all(event["purpose"] == "COLOR_FIDELITY_CORRECTION" for event in task_events))
                self.assertTrue(all(event["batch_id"] == batch_id for event in task_events))


if __name__ == "__main__":
    unittest.main()
