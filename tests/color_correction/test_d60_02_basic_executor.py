from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from engine.color_correction import (
    CORRECTION_EXECUTION_ORDER,
    CORRECTION_PARAMETERS_SCHEMA_VERSION,
    PARAMETER_SPECS,
    CorrectionParameters,
    FinalAction,
    audit_basic_correction,
    execute_basic_correction,
    parameter_contract,
    replay_basic_correction,
)
from engine.color_correction.color_management import (
    encode_color_managed_candidate,
    load_color_managed_source,
    verify_color_managed_output,
)
from engine.output.publish_safety import publish_image_bytes_with_metadata


def _gradient_rgb(width: int = 256, height: int = 96) -> np.ndarray:
    horizontal = np.linspace(4, 251, width, dtype=np.float32)
    vertical = np.linspace(0.88, 1.12, height, dtype=np.float32)[:, None]
    gray = np.clip(horizontal[None, :] * vertical, 2, 253).astype(np.uint8)
    return np.dstack(
        (
            gray,
            np.clip(gray.astype(np.int16) + 5, 0, 255).astype(np.uint8),
            np.clip(gray.astype(np.int16) - 4, 0, 255).astype(np.uint8),
        )
    )


def _lab(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)


def _mean_lstar(image: np.ndarray) -> float:
    return float(_lab(image)[..., 0].mean())


def _mean_chroma(image: np.ndarray) -> float:
    lab = _lab(image)
    return float(np.linalg.norm(lab[..., 1:3], axis=2).mean())


class CorrectionParameterContractTests(unittest.TestCase):
    def test_contract_is_complete_serializable_and_clamped(self) -> None:
        expected = {
            "exposure",
            "brightness",
            "contrast",
            "temperature",
            "tint",
            "saturation",
            "vibrance",
            "highlights",
            "shadows",
        }
        self.assertEqual(set(PARAMETER_SPECS), expected)
        self.assertEqual(set(CORRECTION_EXECUTION_ORDER), expected)
        self.assertTrue(all(spec.neutral == 0.0 for spec in PARAMETER_SPECS.values()))
        clamped = CorrectionParameters(exposure=99, brightness=-999, tint=140)
        self.assertEqual(clamped.exposure, 2.0)
        self.assertEqual(clamped.brightness, -100.0)
        self.assertEqual(clamped.tint, 100.0)
        record = clamped.to_record()
        self.assertEqual(record["schema_version"], CORRECTION_PARAMETERS_SCHEMA_VERSION)
        self.assertEqual(record["contract"], parameter_contract())
        self.assertEqual(CorrectionParameters.from_record(json.loads(json.dumps(record))), clamped)

    def test_record_replay_is_strict_and_never_silently_repairs_tampering(self) -> None:
        record = CorrectionParameters(exposure=0.5).to_record()
        record["values"]["exposure"] = 9.0
        with self.assertRaisesRegex(ValueError, "out of range"):
            CorrectionParameters.from_record(record)
        with self.assertRaises(TypeError):
            CorrectionParameters(brightness=True)
        with self.assertRaises(ValueError):
            CorrectionParameters.from_mapping({"automatic_magic": 1})


class DeterministicBasicExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = _gradient_rgb()

    def _run(self, **values: float) -> np.ndarray:
        return execute_basic_correction(
            self.source,
            CorrectionParameters(**values),
        ).candidate_image

    def test_neutral_is_exact_pixel_identity(self) -> None:
        result = execute_basic_correction(self.source, CorrectionParameters())
        self.assertTrue(np.array_equal(result.candidate_image, self.source))
        self.assertFalse(result.modified)
        self.assertEqual(result.metrics["maximum_channel_delta"], 0.0)
        self.assertEqual(result.metrics["hidden_enhancements"], [])

    def test_exposure_and_brightness_have_correct_but_distinct_directions(self) -> None:
        exposure_up = self._run(exposure=0.5)
        exposure_down = self._run(exposure=-0.5)
        brightness_up = self._run(brightness=30)
        brightness_down = self._run(brightness=-30)
        source_l = _mean_lstar(self.source)
        self.assertGreater(_mean_lstar(exposure_up), source_l)
        self.assertLess(_mean_lstar(exposure_down), source_l)
        self.assertGreater(_mean_lstar(brightness_up), source_l)
        self.assertLess(_mean_lstar(brightness_down), source_l)
        self.assertFalse(np.array_equal(exposure_up, brightness_up))
        self.assertFalse(np.array_equal(exposure_down, brightness_down))

    def test_contrast_changes_lstar_spread_in_requested_direction(self) -> None:
        source_std = float(_lab(self.source)[..., 0].std())
        high = float(_lab(self._run(contrast=40))[..., 0].std())
        low = float(_lab(self._run(contrast=-40))[..., 0].std())
        self.assertGreater(high, source_std)
        self.assertLess(low, source_std)

    def test_temperature_and_tint_axes_are_stable(self) -> None:
        source_lab = _lab(self.source)
        warm = _lab(self._run(temperature=35))
        cool = _lab(self._run(temperature=-35))
        magenta = _lab(self._run(tint=35))
        green = _lab(self._run(tint=-35))
        self.assertGreater(float(np.median(warm[..., 2] - source_lab[..., 2])), 0.5)
        self.assertLess(float(np.median(cool[..., 2] - source_lab[..., 2])), -0.5)
        self.assertGreater(float(np.median(magenta[..., 1] - source_lab[..., 1])), 0.5)
        self.assertLess(float(np.median(green[..., 1] - source_lab[..., 1])), -0.5)

    def test_saturation_and_vibrance_are_real_and_not_equivalent(self) -> None:
        color = np.zeros((80, 160, 3), dtype=np.uint8)
        color[:, :80] = (145, 118, 118)
        color[:, 80:] = (205, 48, 48)
        saturation = execute_basic_correction(
            color,
            CorrectionParameters(saturation=45),
        ).candidate_image
        desaturation = execute_basic_correction(
            color,
            CorrectionParameters(saturation=-45),
        ).candidate_image
        vibrance = execute_basic_correction(
            color,
            CorrectionParameters(vibrance=45),
        ).candidate_image
        source_lab = _lab(color)
        vibrance_lab = _lab(vibrance)
        low_gain = float(
            np.linalg.norm(vibrance_lab[:, :80, 1:3], axis=2).mean()
            - np.linalg.norm(source_lab[:, :80, 1:3], axis=2).mean()
        )
        high_gain = float(
            np.linalg.norm(vibrance_lab[:, 80:, 1:3], axis=2).mean()
            - np.linalg.norm(source_lab[:, 80:, 1:3], axis=2).mean()
        )
        self.assertGreater(_mean_chroma(saturation), _mean_chroma(color))
        self.assertLess(_mean_chroma(desaturation), _mean_chroma(color))
        self.assertGreater(low_gain, 0.0)
        self.assertGreater(low_gain, high_gain)
        self.assertFalse(np.array_equal(saturation, vibrance))

    def test_highlights_and_shadows_are_tonally_localized(self) -> None:
        source_l = _lab(self.source)[..., 0]
        high_mask = source_l >= 65.0
        low_mask = source_l <= 35.0
        highlights_up = _lab(self._run(highlights=45))[..., 0] - source_l
        highlights_down = _lab(self._run(highlights=-45))[..., 0] - source_l
        shadows_up = _lab(self._run(shadows=45))[..., 0] - source_l
        shadows_down = _lab(self._run(shadows=-45))[..., 0] - source_l
        self.assertGreater(float(highlights_up[high_mask].mean()), 0.5)
        self.assertLess(float(highlights_down[high_mask].mean()), -0.5)
        self.assertGreater(
            abs(float(highlights_up[high_mask].mean())),
            abs(float(highlights_up[low_mask].mean())) * 3.0,
        )
        self.assertGreater(float(shadows_up[low_mask].mean()), 0.5)
        self.assertLess(float(shadows_down[low_mask].mean()), -0.5)
        self.assertGreater(
            abs(float(shadows_up[low_mask].mean())),
            abs(float(shadows_up[high_mask].mean())) * 3.0,
        )

    def test_multi_parameter_order_is_deterministic_and_bounded(self) -> None:
        parameters = CorrectionParameters(
            exposure=0.25,
            brightness=10,
            contrast=12,
            temperature=8,
            tint=-6,
            saturation=8,
            vibrance=10,
            highlights=-8,
            shadows=12,
        )
        first = execute_basic_correction(self.source, parameters)
        second = execute_basic_correction(self.source.copy(), parameters)
        self.assertTrue(np.array_equal(first.candidate_image, second.candidate_image))
        self.assertEqual(first.parameter_record, second.parameter_record)
        self.assertEqual(first.execution_order, CORRECTION_EXECUTION_ORDER)
        self.assertEqual(first.metrics["new_channel_low_clip_ratio"], 0.0)
        self.assertLessEqual(first.metrics["new_channel_high_clip_ratio"], 0.002)

    def test_rgba_alpha_and_fully_transparent_rgb_are_preserved(self) -> None:
        alpha = np.tile(np.arange(self.source.shape[1], dtype=np.uint8), (self.source.shape[0], 1))
        alpha[:, :8] = 0
        rgba = np.dstack((self.source, alpha))
        result = execute_basic_correction(
            rgba,
            CorrectionParameters(exposure=0.25, temperature=12, vibrance=12),
        )
        self.assertTrue(np.array_equal(result.candidate_image[..., 3], alpha))
        self.assertTrue(
            np.array_equal(
                result.candidate_image[..., :3][alpha == 0],
                rgba[..., :3][alpha == 0],
            )
        )
        self.assertEqual(result.candidate_image.shape, rgba.shape)
        self.assertEqual(result.candidate_image.dtype, rgba.dtype)


class D3BasicCorrectionReplayTests(unittest.TestCase):
    def test_d3_replays_every_recorded_parameter_and_binds_candidate_identity(self) -> None:
        source = _gradient_rgb(192, 72)
        parameters = CorrectionParameters(
            exposure=0.2,
            brightness=8,
            contrast=9,
            temperature=-7,
            tint=6,
            saturation=7,
            vibrance=8,
            highlights=-6,
            shadows=9,
        )
        generated = execute_basic_correction(source, parameters)
        replayed = replay_basic_correction(source, generated.parameter_record)
        self.assertTrue(np.array_equal(replayed, generated.candidate_image))
        first = audit_basic_correction(
            source,
            generated.candidate_image,
            generated.parameter_record,
        )
        second = audit_basic_correction(
            source.copy(),
            generated.candidate_image.copy(),
            json.loads(json.dumps(generated.parameter_record)),
        )
        self.assertEqual(first.status, "AUDIT_COMPLETE")
        self.assertEqual(first.final_action, FinalAction.REVIEW_REQUIRED)
        self.assertEqual(first.pass_status["REPLAY_PASS"], "YES")
        self.assertEqual(first.candidate_identity, second.candidate_identity)

    def test_d3_rejects_pixel_and_parameter_tampering(self) -> None:
        source = _gradient_rgb(128, 64)
        generated = execute_basic_correction(
            source,
            CorrectionParameters(temperature=20),
        )
        damaged = generated.candidate_image.copy()
        damaged[20, 20, 0] ^= np.uint8(1)
        audit = audit_basic_correction(source, damaged, generated.parameter_record)
        self.assertEqual(audit.status, "PROTECTION_BLOCKED")
        self.assertEqual(audit.pass_status["REPLAY_PASS"], "NO")
        self.assertEqual(audit.blocker, "BASIC_CORRECTION_CANDIDATE_REPLAY_MISMATCH")

        record = json.loads(json.dumps(generated.parameter_record))
        record["execution_order"].reverse()
        audit = audit_basic_correction(source, generated.candidate_image, record)
        self.assertEqual(audit.status, "PROTECTION_BLOCKED")
        self.assertEqual(audit.blocker, "CORRECTION_PARAMETER_CONTRACT_INVALID")

    def test_color_cast_gate_covers_single_pair_combined_and_normal_boundaries(self) -> None:
        source = _gradient_rgb(256, 96)
        safe_cases = {
            "neutral": {},
            "temperature_positive_max": {"temperature": 100},
            "temperature_negative_max": {"temperature": -100},
            "tint_positive_max": {"tint": 100},
            "tint_negative_max": {"tint": -100},
            "saturation_positive_max": {"saturation": 100},
            "saturation_negative_max": {"saturation": -100},
            "vibrance_positive_max": {"vibrance": 100},
            "vibrance_negative_max": {"vibrance": -100},
            "temperature_tint_pair": {"temperature": 100, "tint": 100},
            "saturation_vibrance_pair": {"saturation": 100, "vibrance": 100},
            "normal_positive": {
                "temperature": 35,
                "tint": 35,
                "saturation": 35,
                "vibrance": 35,
            },
            "normal_negative": {
                "temperature": -35,
                "tint": -35,
                "saturation": -35,
                "vibrance": -35,
            },
        }
        for name, values in safe_cases.items():
            with self.subTest(name=name):
                generated = execute_basic_correction(
                    source,
                    CorrectionParameters(**values),
                )
                audit = audit_basic_correction(
                    source,
                    generated.candidate_image,
                    generated.parameter_record,
                )
                self.assertEqual(audit.status, "AUDIT_COMPLETE")
                self.assertEqual(audit.pass_status["COLOR_CAST_PASS"], "YES")

        blocked_cases = {
            "all_same_direction_max": {
                "temperature": 100,
                "tint": 100,
                "saturation": 100,
                "vibrance": 100,
            },
            "conflicting_max": {
                "temperature": 100,
                "tint": -100,
                "saturation": 100,
                "vibrance": -100,
            },
        }
        for name, values in blocked_cases.items():
            with self.subTest(name=name):
                generated = execute_basic_correction(
                    source,
                    CorrectionParameters(**values),
                )
                audit = audit_basic_correction(
                    source,
                    generated.candidate_image,
                    generated.parameter_record,
                )
                self.assertEqual(audit.status, "PROTECTION_BLOCKED")
                self.assertEqual(audit.pass_status["COLOR_CAST_PASS"], "NO")
                self.assertEqual(
                    audit.pass_status["COMBINED_COLOR_BUDGET_PASS"],
                    "NO",
                )
                self.assertEqual(
                    audit.blocker,
                    "BASIC_CORRECTION_EXECUTION_SAFETY_FAILED",
                )


class FormalColorDpiPreservationTests(unittest.TestCase):
    def _run_case(self, extension: str, dpi: tuple[int, int] | None) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source_path = root / f"source{extension}"
            output_path = root / f"output{extension}"
            pixels = _gradient_rgb(96, 64)
            save_options: dict[str, object] = {}
            if dpi is not None:
                save_options["dpi"] = dpi
            if extension == ".jpg":
                save_options.update({"quality": 95, "subsampling": 0})
            Image.fromarray(pixels, mode="RGB").save(source_path, **save_options)
            source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
            managed = load_color_managed_source(source_path)
            candidate = execute_basic_correction(
                managed.pixels,
                CorrectionParameters(brightness=10, temperature=5),
                input_order=managed.input_order,
            ).candidate_image
            encoded = encode_color_managed_candidate(candidate, managed)
            verify_color_managed_output(encoded, candidate, managed)

            def verify_private(data: bytes) -> None:
                verify_color_managed_output(data, candidate, managed)

            published, report, _validation = publish_image_bytes_with_metadata(
                encoded,
                output_path,
                source_data=source_path.read_bytes(),
                normalize_orientation=True,
                verify_private=verify_private,
            )
            self.assertEqual(hashlib.sha256(source_path.read_bytes()).hexdigest(), source_sha)
            self.assertTrue(report["dpi_unchanged"])
            with Image.open(published) as output:
                output.load()
                observed = output.info.get("dpi")
                if dpi is None:
                    resolution_exif = output.getexif()
                    self.assertFalse(any(tag in resolution_exif for tag in (282, 283, 296)))
                    if extension == ".jpg":
                        self.assertEqual(output.info.get("jfif_unit"), 0)
                    else:
                        self.assertIsNone(observed)
                else:
                    self.assertIsNotNone(observed)
                    self.assertAlmostEqual(float(observed[0]), float(dpi[0]), delta=0.02)
                    self.assertAlmostEqual(float(observed[1]), float(dpi[1]), delta=0.02)

    def test_png_and_jpeg_preserve_real_dpi_and_do_not_fabricate_missing_dpi(self) -> None:
        for extension in (".png", ".jpg"):
            for dpi in ((180, 180), None):
                with self.subTest(extension=extension, dpi=dpi):
                    self._run_case(extension, dpi)


if __name__ == "__main__":
    unittest.main()
