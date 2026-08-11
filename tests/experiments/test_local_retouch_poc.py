from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from tools.experiments import local_retouch_poc as poc


class FixtureContractTests(unittest.TestCase):
    def test_fixture_freezes_six_internal_synthetic_samples_and_small_masks(self) -> None:
        fixture = poc.load_fixture()
        samples = poc.validate_fixture(fixture)
        self.assertEqual(len(samples), 6)
        self.assertEqual(fixture["source_policy"], "INTERNAL_SYNTHETIC_TEST_ASSETS_ONLY")
        for sample in samples:
            with self.subTest(sample=sample["sample_id"]):
                ratio = np.count_nonzero(sample["mask_array"]) / sample["mask_array"].size
                self.assertGreater(ratio, 0)
                self.assertLessEqual(ratio, 0.02)
                self.assertEqual(poc.sha256_file(sample["source_path"]), sample["source_sha256"])

    def test_output_guard_accepts_only_unique_direct_poc_child(self) -> None:
        parent = poc.OUTPUT_PARENT
        accepted = parent / "local_retouch_poc_20990101_010101"
        self.assertEqual(poc.ensure_isolated_output(accepted), accepted.resolve())
        rejected = (
            poc.PROJECT_ROOT / "settings" / "local_retouch_poc_20990101_010101",
            parent / "nested" / "local_retouch_poc_20990101_010101",
            parent / "wrong_name",
        )
        for path in rejected:
            with self.subTest(path=path), self.assertRaises(ValueError):
                    poc.ensure_isolated_output(path)


class PathSafetyContractTests(unittest.TestCase):
    def test_current_fixture_ids_and_derived_targets_remain_valid(self) -> None:
        fixture = poc.load_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "local_retouch_poc_20990101_010101"
            root.mkdir()
            for sample in fixture["samples"]:
                with self.subTest(sample=sample["sample_id"]):
                    sample_id = poc.validate_sample_id(sample["sample_id"])
                    target = root / "review_package" / sample_id / "candidate_a_telea.png"
                    self.assertEqual(poc.ensure_poc_target(root, target), target.resolve())

    def test_sample_id_rejects_absolute_rooted_unc_and_drive_paths(self) -> None:
        invalid = (
            r"D:\影界文件",
            r"D:relative",
            r"\\server\share\sample",
            r"\settings",
            "/tmp/sample",
        )
        for sample_id in invalid:
            with self.subTest(sample_id=sample_id), self.assertRaises(ValueError):
                poc.validate_sample_id(sample_id)

    def test_sample_id_rejects_traversal_and_path_separators(self) -> None:
        invalid = ("..", "../settings", r"..\settings", "A/B", r"A\B", "A/../B")
        for sample_id in invalid:
            with self.subTest(sample_id=sample_id), self.assertRaises(ValueError):
                poc.validate_sample_id(sample_id)

    def test_fixture_validation_rejects_sample_id_path_semantics(self) -> None:
        fixture = poc.load_fixture()
        fixture["samples"][0] = {**fixture["samples"][0], "sample_id": r"..\settings"}
        with self.assertRaises(ValueError):
            poc.validate_fixture(fixture)

    def test_derived_target_cannot_escape_poc_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "local_retouch_poc_20990101_010101"
            root.mkdir()
            escaped = root / "review_package" / ".." / ".." / "settings" / "candidate.png"
            with self.assertRaises(ValueError):
                poc.ensure_poc_target(root, escaped)

    def test_derived_target_rejects_detected_reparse_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "local_retouch_poc_20990101_010101"
            root.mkdir()
            reparse_component = (root / "review_package").absolute()
            target = reparse_component / "S01" / "candidate.png"

            def detected(path: Path) -> bool:
                return path.absolute() == reparse_component

            with patch.object(poc, "_is_reparse_point", side_effect=detected), self.assertRaises(ValueError):
                poc.ensure_poc_target(root, target)


class CandidateContractTests(unittest.TestCase):
    def test_both_fixed_routes_preserve_outside_mask_and_alpha(self) -> None:
        height, width = 48, 64
        yy, xx = np.indices((height, width))
        bgr = np.dstack((xx * 3, yy * 4, np.full((height, width), 96))).astype(np.uint8)
        alpha = np.clip(xx * 4, 0, 255).astype(np.uint8)
        source = np.dstack((bgr, alpha))
        mask = np.zeros((height, width), dtype=np.uint8)
        mask[18:28, 26:38] = 255
        for route in poc.ROUTES:
            with self.subTest(route=route):
                candidate, metrics = poc.run_inpaint(source, mask, route=route, radius=3.0)
                self.assertEqual(metrics["outside_mask_changed_pixels"], 0)
                self.assertEqual(metrics["alpha_status"], "PASS_ALPHA_EXACT")
                self.assertTrue(np.array_equal(candidate[:, :, 3], alpha))
                outside = mask == 0
                self.assertTrue(np.array_equal(candidate[:, :, :3][outside], source[:, :, :3][outside]))

    def test_mask_contract_rejects_empty_large_and_out_of_bounds_selection(self) -> None:
        with self.assertRaises(ValueError):
            poc.rectangle_mask((100, 100), {"type": "rectangle", "x0": 1, "y0": 1, "x1": 1, "y1": 3})
        with self.assertRaises(ValueError):
            poc.rectangle_mask((100, 100), {"type": "rectangle", "x0": 0, "y0": 0, "x1": 50, "y1": 50})
        with self.assertRaises(ValueError):
            poc.rectangle_mask((100, 100), {"type": "rectangle", "x0": 95, "y0": 95, "x1": 105, "y1": 105})

    def test_png_roundtrip_is_decodable_and_keeps_dimensions(self) -> None:
        image = np.full((24, 32, 3), (20, 80, 160), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate.png"
            poc.write_png(path, image)
            decoded = poc.read_image(path)
            self.assertEqual(decoded.shape, image.shape)
            self.assertTrue(np.array_equal(decoded, image))


if __name__ == "__main__":
    unittest.main()
