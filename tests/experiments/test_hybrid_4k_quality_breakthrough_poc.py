from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from tools.experiments import hybrid_4k_quality_breakthrough_poc as poc


class ContractTests(unittest.TestCase):
    def test_target_dimensions_use_3840_long_edge_and_half_up(self) -> None:
        self.assertEqual(poc.target_dimensions(1122, 1402), (3073, 3840))
        self.assertEqual(poc.target_dimensions(1915, 821), (3840, 1646))
        self.assertEqual(poc.target_dimensions(320, 180), (3840, 2160))

    def test_output_guard_only_accepts_unique_direct_output_child(self) -> None:
        accepted = poc.OUTPUT_ROOT / "4k_quality_breakthrough_20990101_010101"
        self.assertEqual(poc.ensure_isolated_output(accepted), accepted.resolve())
        for rejected in (
            poc.REPO_ROOT / "settings" / "4k_quality_breakthrough_bad",
            poc.OUTPUT_ROOT / "nested" / "4k_quality_breakthrough_bad",
            poc.OUTPUT_ROOT / "wrong_name",
        ):
            with self.subTest(path=rejected), self.assertRaises(ValueError):
                poc.ensure_isolated_output(rejected)

    def test_routes_are_fixed_to_two_no_denoise_x2_models(self) -> None:
        self.assertEqual(tuple(poc.ROUTES), ("PHOTO_BALANCED", "CUNET_DEPTH"))
        self.assertEqual(poc.ROUTES["PHOTO_BALANCED"].model_dir, "models-upconv_7_photo")
        self.assertEqual(poc.ROUTES["CUNET_DEPTH"].model_dir, "models-cunet")
        command = poc.waifu_command(Path("input.png"), Path("output.png"), poc.ROUTES["PHOTO_BALANCED"])
        self.assertEqual(command[command.index("-n") + 1], "-1")
        self.assertEqual(command[command.index("-s") + 1], "2")
        self.assertEqual(command[command.index("-t") + 1], "128")


class ProtectionTests(unittest.TestCase):
    @staticmethod
    def masks(shape: tuple[int, int] = (24, 32)) -> dict[str, np.ndarray]:
        result = {
            name: np.zeros(shape, dtype=np.uint8)
            for name in (
                "text_logo",
                "high_contrast",
                "face",
                "skin",
                "brand",
                "smooth_gradient",
                "texture",
                "alpha_edge",
                "hard_protect",
            )
        }
        result["hard_protect"][2:6, 2:6] = 255
        result["skin"][8:12, 2:6] = 255
        result["brand"][8:12, 8:12] = 255
        result["smooth_gradient"][8:12, 14:18] = 255
        result["texture"][14:20, 20:28] = 255
        return result

    def test_hard_protection_is_zero_and_soft_protection_is_capped(self) -> None:
        for config in poc.ROUTES.values():
            weights = poc.blend_weights(self.masks(), config)
            self.assertTrue(np.all(weights[2:6, 2:6] == 0.0))
            self.assertLessEqual(float(weights[9, 3]), config.protected_cap + 1e-6)
            self.assertLessEqual(float(weights[9, 9]), config.protected_cap + 1e-6)
            self.assertLessEqual(float(weights[9, 15]), config.protected_cap + 1e-6)
            self.assertLessEqual(float(weights.max()), config.texture_weight + 1e-6)

    def test_luminance_fusion_keeps_chroma_bounded_and_alpha_exact(self) -> None:
        height, width = 96, 128
        yy, xx = np.indices((height, width))
        rgb = np.dstack(
            (
                np.clip(40 + xx, 0, 255),
                np.clip(60 + yy, 0, 255),
                np.full((height, width), 130),
            )
        ).astype(np.uint8)
        alpha = np.clip(xx * 3, 0, 255).astype(np.uint8)
        baseline = Image.fromarray(np.dstack((rgb, alpha)), "RGBA")
        model = Image.fromarray(np.clip(rgb.astype(np.int16) + 24, 0, 255).astype(np.uint8), "RGB")
        result, metrics, masks = poc.fuse_luminance(baseline, model, poc.ROUTES["PHOTO_BALANCED"])
        result_array = np.asarray(result)
        self.assertTrue(np.array_equal(result_array[:, :, 3], alpha))
        self.assertLessEqual(metrics["actual_max_abs_luma_delta"], 8)
        self.assertLessEqual(metrics["actual_max_abs_chroma_delta"], 1)
        self.assertEqual(metrics["hard_protected_changed_pixels"], 0)
        alpha_gate = poc.alpha_metrics(baseline, result, masks["hard_protect"])
        self.assertEqual(alpha_gate["status"], "PASS")


class TruthfulnessTests(unittest.TestCase):
    def test_aggregate_never_converts_pending_visual_review_to_pass(self) -> None:
        records = [
            {
                "TECHNICAL_STATUS": "PASS",
                "STRUCTURE_SAFETY_STATUS": poc.VISUAL_PENDING,
                "VISUAL_GAIN_STATUS": poc.VISUAL_PENDING,
            }
        ]
        result = poc.aggregate_status(records, True)
        self.assertEqual(result["TECHNICAL_STATUS"], "PASS")
        self.assertEqual(result["STRUCTURE_SAFETY_STATUS"], poc.VISUAL_PENDING)
        self.assertEqual(result["VISUAL_GAIN_STATUS"], poc.VISUAL_PENDING)
        self.assertEqual(result["ROUTE_DECISION_STATUS"], "PENDING_HUMAN_REVIEW")
        self.assertEqual(result["value_claim"], "NOT_MADE")

    def test_any_technical_failure_blocks_technical_status(self) -> None:
        result = poc.aggregate_status([{"TECHNICAL_STATUS": "FAIL"}], True)
        self.assertEqual(result["TECHNICAL_STATUS"], "BLOCKED")

    def test_blind_order_has_baseline_and_both_routes_once(self) -> None:
        first = poc.blind_order("batch", "S01")
        second = poc.blind_order("batch", "S01")
        self.assertEqual(first, second)
        self.assertCountEqual(first, ["LANCZOS", "PHOTO_BALANCED", "CUNET_DEPTH"])

    def test_icc_gate_is_derived_from_real_file_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "baseline.png"
            matching = root / "matching.png"
            missing = root / "missing.png"
            profile = b"test-icc-profile"
            image = Image.new("RGB", (8, 8), (20, 40, 60))
            image.save(baseline, format="PNG", icc_profile=profile)
            image.save(matching, format="PNG", icc_profile=profile)
            image.save(missing, format="PNG")
            self.assertEqual(poc.file_record(baseline)["icc_sha256"], poc.file_record(matching)["icc_sha256"])
            self.assertNotEqual(poc.file_record(baseline)["icc_sha256"], poc.file_record(missing)["icc_sha256"])

    def test_native_roi_panel_preserves_candidate_pixels_one_to_one(self) -> None:
        yy, xx = np.indices((512, 512))
        pixels = np.dstack((xx % 256, yy % 256, (xx + yy) % 256)).astype(np.uint8)
        panel = poc.native_512_panel(Image.fromarray(pixels, "RGB"), "OPTION A")
        self.assertEqual(panel.size, (512, 548))
        self.assertTrue(np.array_equal(np.asarray(panel)[36:548, :, :], pixels))


if __name__ == "__main__":
    unittest.main()
