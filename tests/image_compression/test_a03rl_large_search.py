from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import cv2
from PIL import Image, ImageDraw

from engine.image_compression import delivery_options
from engine.image_compression.jpg_full_resolution import FullResolutionSourceAnalysis, full_resolution_metrics
from engine.image_compression.jpg_large_search import native_source_hf_mean, plan_large_jpg_search, select_native_rois
from engine.image_compression.jpg_quality_gate import (
    _THRESHOLDS, _metric_checks, evaluate_jpg_quality, measure_jpg_pixels, prepare_jpg_source_analysis,
)
from tests.image_compression.test_a03_single_winner import _business_image, _metadata_report


def jpeg(image, quality=96, subsampling=0):
    with tempfile.TemporaryFile() as stream:
        image.save(stream, format="JPEG", quality=quality, subsampling=subsampling, optimize=False)
        stream.seek(0)
        return Image.open(stream).convert("RGB")


class NativeMetricsTests(unittest.TestCase):
    def test_request_local_source_analysis_preserves_every_metric(self):
        source = _business_image()
        candidates = (jpeg(source, 96, 0), jpeg(source, 60, 2))
        expected = [measure_jpg_pixels(source, candidate) for candidate in candidates]
        with prepare_jpg_source_analysis(source, full_resolution=True) as prepared:
            actual = [
                measure_jpg_pixels(source, candidate, _source_analysis=prepared)
                for candidate in candidates
            ]
        self.assertEqual(actual, expected)

        expected_full = [
            {key: round(value, 6) for key, value in full_resolution_metrics(source, candidate).items()}
            for candidate in candidates
        ]
        with FullResolutionSourceAnalysis(source) as prepared:
            actual_full = [
                {key: round(value, 6) for key, value in full_resolution_metrics(
                    source, candidate, source_analysis=prepared,
                ).items()}
                for candidate in candidates
            ]
        self.assertEqual(actual_full, expected_full)

    def test_striped_metrics_match_frozen_monolithic_metrics_across_seams(self):
        rng = np.random.default_rng(451)
        texture = Image.fromarray(rng.integers(0, 256, (391, 519, 3), dtype=np.uint8))
        gradient = np.zeros((391, 519, 3), dtype=np.uint8)
        gradient[:, :, 0] = np.arange(519, dtype=np.uint16)[None, :] * 255 // 518
        gradient[:, :, 1] = np.arange(391, dtype=np.uint16)[:, None] * 255 // 390
        gradient[:, :, 2] = 130
        for source in (_business_image(), texture, Image.fromarray(gradient)):
            for quality, mode in ((96, 0), (60, 2)):
                with self.subTest(size=source.size, quality=quality):
                    candidate = jpeg(source, quality, mode)
                    expected = measure_jpg_pixels(source, candidate)
                    # Multiple odd stripe heights expose reflected-border and
                    # global JPEG block phase mistakes.
                    for rows in (31, 128):
                        with patch("engine.image_compression.jpg_full_resolution.STRIPE_ROWS", rows):
                            actual = full_resolution_metrics(source, candidate)
                        self.assertEqual(_metric_checks(actual), _metric_checks(expected))
                        for name, value in expected.items():
                            self.assertAlmostEqual(actual[name], value, delta=0.0001, msg=name)

    def test_large_gate_checks_all_pixels_and_still_rejects_real_damage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = Image.new("RGB", (2160, 1921), (248, 248, 248))
            draw = ImageDraw.Draw(source)
            for y in range(16, source.height, 32):
                draw.line((12, y, source.width - 12, y), fill=(35, 35, 35), width=2)
            original = root / "source.png"
            good = root / "good.jpg"
            bad = root / "bad.jpg"
            source.save(original)
            source.save(good, quality=98, subsampling=0)
            damaged = source.copy()
            ImageDraw.Draw(damaged).rectangle((0, 1664, source.width, source.height), fill=(250, 0, 0))
            damaged.save(bad, quality=98, subsampling=0)
            args = dict(metadata_report=_metadata_report(), source_has_real_transparency=False, full_resolution=True)
            passed = evaluate_jpg_quality(original, good, **args)
            failed = evaluate_jpg_quality(original, bad, **args)
            self.assertEqual(passed["status"], "PASS")
            self.assertEqual(passed["metrics"]["analysis_pixel_count"], 2160 * 1921)
            self.assertEqual(failed["status"], "FAIL")
            self.assertIn("COLOR_DRIFT", failed["failure_reasons"])
            self.assertEqual(passed["thresholds"], _THRESHOLDS)
            # Metadata and transparency protection do not become ROI hints.
            args["metadata_report"] = {}
            self.assertEqual(evaluate_jpg_quality(original, good, **args)["status"], "FAIL")
            args["metadata_report"] = _metadata_report()
            args["source_has_real_transparency"] = True
            self.assertEqual(evaluate_jpg_quality(original, good, **args)["status"], "FAIL")


class NativeRoiTests(unittest.TestCase):
    def test_rois_are_exact_source_pixels_at_mcu_aligned_origins(self):
        source = Image.new("RGB", (3840, 2161), (249, 249, 249))
        draw = ImageDraw.Draw(source)
        draw.line((2500, 700, 3200, 701), fill=(0, 0, 150), width=1)
        for x in range(1400, 1700, 3):
            draw.line((x, 1800, x, 2090), fill=(230, 50, 40), width=1)
        rois = select_native_rois(source)
        self.assertEqual(len(rois), 5)
        self.assertEqual({r["role"] for r in rois}, {"text_fine_line", "high_frequency", "gradient", "photo", "color_edge"})
        for roi in rois:
            x, y, right, bottom = roi["box"]
            self.assertEqual((x % 16, y % 16), (0, 0))
            self.assertEqual(roi["image"].size, (right - x, bottom - y))
            self.assertEqual(roi["image"].tobytes(), source.crop(roi["box"]).tobytes())

    def test_search_probes_both_modes_and_cannot_approve_delivery(self):
        plans, evidence = plan_large_jpg_search(_business_image(), (0, 2))
        self.assertEqual({p["subsampling"] for p in plans}, {0, 2})
        self.assertTrue(evidence["native_resolution"])
        self.assertFalse(evidence["resized"])
        self.assertFalse(evidence["accepts_delivery"])
        self.assertEqual(evidence["representative_grid"], [8, 8])
        self.assertEqual(sum(r["role"] == "representative" for r in evidence["regions"]), 64)
        for region in evidence["regions"]:
            self.assertEqual(region["box"][0] % 16, 0)
            self.assertEqual(region["box"][1] % 16, 0)
        for trial in evidence["trials"]:
            lower, upper = trial["hf_retention_interval"]
            self.assertLessEqual(lower, trial["hf_retention_hint"])
            self.assertGreaterEqual(upper, trial["hf_retention_hint"])
        for plan in plans:
            if plan["roi_last_pass"] and plan["roi_first_fail"]:
                self.assertEqual(plan["roi_last_pass"] - plan["roi_first_fail"], 1)
        self.assertNotIn("quality_gate", evidence)
        json.dumps(evidence)

    def test_native_source_energy_anchor_is_exact_and_does_not_resize(self):
        source = _business_image()
        luma = cv2.cvtColor(np.asarray(source), cv2.COLOR_RGB2GRAY).astype(np.float32)
        expected = np.mean(np.abs(cv2.Laplacian(luma, cv2.CV_32F)), dtype=np.float64)
        with patch.object(Image.Image, "resize", side_effect=AssertionError("Native probe must not resize")):
            self.assertAlmostEqual(native_source_hf_mean(source), expected, places=10)
            plan_large_jpg_search(source, (0, 2))


class LargeSearchControllerTests(unittest.TestCase):
    def run_search(self, trial, lossless_bytes=8_000_000):
        # Only controller decisions are stubbed here; native metrics and the
        # persisted-image gate are independently exercised above and in runtime.
        plans = [{"subsampling": mode, "quality": 80, "roi_last_pass": 80, "roi_first_fail": 79}
                 for mode in (0, 2)]
        with patch("engine.image_compression.jpg_large_search.plan_large_jpg_search", return_value=(plans, {})), \
                patch.object(delivery_options, "_evaluate_jpg_trial", side_effect=trial):
            return delivery_options._large_jpg_candidates(
                displayed=None, source={"size_bytes": 10_000_000}, source_data=b"", source_snapshot=None,
                evaluation_root=None, width=3840, height=2160, size_profile_id="VERY_LARGE",
                size_profile=delivery_options.SIZE_SEARCH_PROFILE["VERY_LARGE"],
                content_risk_id="TEXT_LINE_HIGH_RISK", lossless_bytes=lossless_bytes,
            )

    @staticmethod
    def trial(quality, subsampling, **kwargs):
        return {"format": "JPG", "file_size": quality * 10_000 - subsampling * 1000,
                "quality_gate": {"status": "PASS" if quality >= 60 else "FAIL"},
                "search_details": {"quality": quality, "subsampling": "4:4:4" if subsampling == 0 else "4:2:0"}}

    def test_two_real_full_passes_compete_by_bytes_at_roi_boundary(self):
        candidates, summary = self.run_search(self.trial)
        self.assertEqual(summary["full_image_encode_count"], 2)
        winner = min(candidates, key=lambda item: item["file_size"])
        self.assertEqual(winner["search_details"]["subsampling"], "4:2:0")
        self.assertEqual(summary["stop_reason"], "SMALLER_FULL_RESOLUTION_PASS_AT_NATIVE_ROI_BOUNDARY")

    def test_low_gain_png_cannot_stop_search_when_roi_candidate_has_no_benefit(self):
        candidates, summary = self.run_search(self.trial, lossless_bytes=100_000)
        self.assertGreater(summary["full_image_encode_count"], 2)
        self.assertEqual(set(summary["boundaries"]), {"4:4:4", "4:2:0"})
        for boundary in summary["boundaries"].values():
            self.assertEqual((boundary["last_pass"], boundary["first_fail"]), (60, 59))
        self.assertTrue(any(item["quality_gate"]["status"] == "FAIL" for item in candidates))

    def test_roi_pass_cannot_override_full_resolution_rejection(self):
        def reject(**kwargs):
            candidate = self.trial(**kwargs)
            candidate["quality_gate"]["status"] = "FAIL"
            return candidate
        candidates, summary = self.run_search(reject)
        self.assertTrue(all(item["quality_gate"]["status"] == "FAIL" for item in candidates))
        self.assertIsNone(summary["lowest_safe_quality"])
        self.assertIsNone(summary["best_passing_bytes"])
        self.assertEqual(summary["stop_reason"], "FULL_RESOLUTION_REJECTED_BOTH_MODES")

    def test_small_medium_and_high_gain_paths_keep_the_legacy_search(self):
        for profile, source_bytes, lossless in (("SMALL", 400_000, 399_000), ("MEDIUM", 1_800_000, 1_790_000),
                                                 ("VERY_LARGE", 10_000_000, 1_000_000)):
            with self.subTest(profile=profile), \
                    patch.object(delivery_options, "_large_jpg_candidates", side_effect=AssertionError("Frozen path")), \
                    patch.object(delivery_options, "_evaluate_jpg_trial", side_effect=self.trial):
                _, summary = delivery_options._adaptive_jpg_candidates(
                    displayed=None, source={"size_bytes": source_bytes}, source_data=b"", source_snapshot=None,
                    evaluation_root=None, width=3840, height=2161, size_profile_id=profile,
                    size_profile=delivery_options.SIZE_SEARCH_PROFILE[profile],
                    content_risk_id="TEXT_LINE_HIGH_RISK", lossless_bytes=lossless,
                )
                self.assertEqual(summary["policy"], "BOUNDED_COARSE_TO_FINE_V1")

    def test_low_gain_large_search_is_not_limited_to_one_problem_resolution(self):
        with patch.object(delivery_options, "_large_jpg_candidates", return_value=([], {})) as large:
            delivery_options._adaptive_jpg_candidates(
                displayed=None, source={"size_bytes": 4_000_000}, source_data=b"", source_snapshot=None,
                evaluation_root=None, width=2000, height=1800, size_profile_id="LARGE",
                size_profile=delivery_options.SIZE_SEARCH_PROFILE["LARGE"],
                content_risk_id="PHOTO_NORMAL", lossless_bytes=3_900_000,
            )
            large.assert_called_once()


if __name__ == "__main__":
    unittest.main()
