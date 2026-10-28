from __future__ import annotations

import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from tools.experiments.e1_01_real_information_baseline import (
    ASSESSMENT_FIELDS,
    CONTROLLED_CASES,
    OUTPUT_ROOT,
    create_degraded_input,
    degradation_extension,
    map_normalized_box,
    rerender_candidate_comparisons,
    sha256_file,
    validate_manifest,
)


class E101RealInformationBaselineTest(unittest.TestCase):
    def test_all_degradation_families_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            y, x = np.indices((96, 128))
            rgb = np.stack(((x * 3) % 256, (y * 5) % 256, ((x + y) * 7) % 256), axis=2).astype(np.uint8)
            source = root / "source.png"
            Image.fromarray(rgb, "RGB").save(source)
            seen: set[str] = set()
            for sample_id, (degradation_type, params) in CONTROLLED_CASES.items():
                with self.subTest(sample_id=sample_id, degradation_type=degradation_type):
                    extension = degradation_extension(degradation_type)
                    first = root / f"{sample_id}_first{extension}"
                    second = root / f"{sample_id}_second{extension}"
                    create_degraded_input(source, first, degradation_type, params)
                    create_degraded_input(source, second, degradation_type, params)
                    self.assertEqual(sha256_file(first), sha256_file(second))
                    seen.add(degradation_type)
            self.assertEqual(seen, {"RESIZE", "RESIZE_JPEG", "BLUR_JPEG", "MULTI_RESIZE", "SCREENSHOT_LIKE"})

    def test_roi_mapping_uses_normalized_xyxy(self) -> None:
        mapped = map_normalized_box({"x0": 0.25, "y0": 0.1, "x1": 0.75, "y1": 0.9}, (100, 80))
        self.assertEqual(mapped, {"x0": 25, "y0": 8, "x1": 75, "y1": 72})

    def test_fixed_manifest_and_outputs_validate(self) -> None:
        result = validate_manifest(OUTPUT_ROOT / "manifest.json")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["e1_01_baseline"], "FIXED")
        self.assertEqual(result["sample_count"], 8)
        self.assertEqual(result["case_count"], 16)
        self.assertEqual(result["ready_for_e1_02"], "YES")
        self.assertEqual(
            ASSESSMENT_FIELDS,
            (
                "VISIBLE_GAIN",
                "TEXT_FIDELITY",
                "FACE_IDENTITY",
                "LOGO_FIDELITY",
                "STRUCTURE_FIDELITY",
                "MATERIAL_FIDELITY",
                "HALO",
                "RINGING",
                "FALSE_TEXTURE",
            ),
        )

    def test_candidate_rerender_reuses_full_image_and_roi_contract_without_safe_base(self) -> None:
        manifest_path = OUTPUT_ROOT / "manifest.json"
        manifest_hash_before = sha256_file(manifest_path)
        manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
        for case_id in ("E1C002", "E1C006"):
            case = next(item for item in manifest["cases"] if item["case_id"] == case_id)
            safe_path = Path(__file__).resolve().parents[2] / case["safe_base"]["path"]
            with self.subTest(case_id=case_id), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                candidate = root / "candidate.png"
                shutil.copyfile(safe_path, candidate)
                with patch("tools.experiments.e1_01_real_information_baseline.process_4k_v1_image") as safe_executor:
                    result = rerender_candidate_comparisons(
                        manifest_path,
                        case_id,
                        candidate,
                        root / "comparison",
                    )
                safe_executor.assert_not_called()
                self.assertFalse(result["safe_base_rerun"])
                self.assertFalse(result["e1_01_baseline_modified"])
                full_comparison = Path(result["full_image_side_by_side"])
                self.assertTrue(full_comparison.is_file())
                with Image.open(full_comparison) as opened:
                    opened.load()
                self.assertEqual(len(result["roi"]), len(case["roi"]))
                for expected, actual in zip(case["roi"], result["roi"]):
                    self.assertEqual(actual["normalized_box"], expected["normalized_box"])
                    expected_candidate_box = map_normalized_box(
                        expected["normalized_box"],
                        (result["candidate"]["width"], result["candidate"]["height"]),
                    )
                    self.assertEqual(actual["pixel_boxes"]["candidate"], expected_candidate_box)
                    candidate_crop = Path(actual["crop_paths"]["candidate"])
                    roi_comparison = Path(actual["side_by_side"])
                    self.assertTrue(candidate_crop.is_file())
                    self.assertTrue(roi_comparison.is_file())
                    with Image.open(candidate_crop) as opened:
                        opened.load()
                        self.assertEqual(
                            opened.size,
                            (
                                expected_candidate_box["x1"] - expected_candidate_box["x0"],
                                expected_candidate_box["y1"] - expected_candidate_box["y0"],
                            ),
                        )
                    with Image.open(roi_comparison) as opened:
                        opened.load()
        self.assertEqual(sha256_file(manifest_path), manifest_hash_before)

    def test_candidate_rerender_fails_for_missing_or_wrong_dimensions(self) -> None:
        manifest_path = OUTPUT_ROOT / "manifest.json"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(RuntimeError, "CANDIDATE_MISSING"):
                rerender_candidate_comparisons(manifest_path, "E1C002", root / "missing.png", root / "missing-output")
            corrupt = root / "corrupt.png"
            corrupt.write_bytes(b"not-an-image")
            with self.assertRaisesRegex(RuntimeError, "CANDIDATE_DECODE_FAILED"):
                rerender_candidate_comparisons(manifest_path, "E1C002", corrupt, root / "corrupt-output")
            wrong = root / "wrong.png"
            Image.new("RGB", (32, 24), (20, 40, 60)).save(wrong)
            with self.assertRaisesRegex(RuntimeError, "CANDIDATE_DIMENSIONS_MISMATCH"):
                rerender_candidate_comparisons(manifest_path, "E1C002", wrong, root / "wrong-output")


if __name__ == "__main__":
    unittest.main()
