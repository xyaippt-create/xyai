from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.experiments import traditional_4k_baseline_v1 as baseline


class Traditional4KBaselineV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = baseline.read_manifest(baseline.DEFAULT_MANIFEST)
        cls.standard = json.loads(baseline.DEFAULT_STANDARD.read_text(encoding="utf-8"))
        cls.results_path = baseline.ARTIFACT_ROOT / "results" / "4k_stage1_run_results.json"
        if not cls.results_path.is_file():
            raise AssertionError("Run the Stage 1 baseline once before this targeted suite.")
        cls.results = json.loads(cls.results_path.read_text(encoding="utf-8"))
        cls.comparison_manifest = json.loads(
            (baseline.ARTIFACT_ROOT / "comparisons" / "comparison_manifest.json").read_text(encoding="utf-8")
        )
        cls.determinism = json.loads(
            (baseline.ARTIFACT_ROOT / "results" / "determinism_independent.json").read_text(encoding="utf-8")
        )

    def test_01_frozen_standard(self) -> None:
        self.assertEqual(self.standard["standard_version"], "V1")
        self.assertEqual(self.standard["target_long_edge"], 3840)
        self.assertEqual(self.standard["aspect_ratio_policy"], "PRESERVE")
        self.assertEqual(self.standard["source_policy"], "DIRECT_FROM_ORIGINAL")
        self.assertEqual(self.standard["crop_policy"], "FORBIDDEN")
        self.assertEqual(self.standard["stretch_policy"], "FORBIDDEN")
        self.assertEqual(self.standard["padding_policy"], "FORBIDDEN")

    def test_02_target_dimensions_horizontal_vertical_square_and_non_16_9(self) -> None:
        self.assertEqual(baseline.target_dimensions(1600, 900), ("PROCESS", (3840, 2160)))
        self.assertEqual(baseline.target_dimensions(900, 1600), ("PROCESS", (2160, 3840)))
        self.assertEqual(baseline.target_dimensions(1000, 1000), ("PROCESS", (3840, 3840)))
        self.assertEqual(baseline.target_dimensions(1000, 700), ("PROCESS", (3840, 2688)))

    def test_03_already_4k_is_no_processing_needed(self) -> None:
        self.assertEqual(baseline.target_dimensions(3840, 2160), ("NO_PROCESSING_NEEDED", None))
        self.assertEqual(baseline.target_dimensions(2160, 4000), ("NO_PROCESSING_NEEDED", None))

    def test_04_direct_original_policy_rejects_1080p_intermediates(self) -> None:
        valid = Path(r"D:\inputs\01_original\source.png")
        invalid = Path(r"D:\影界文件\输出\1080P安全增强\source.png")
        self.assertEqual(baseline.source_directness_status(valid, "HISTORICAL_POC_ORIGINAL_INPUT"), "PASS")
        self.assertEqual(
            baseline.source_directness_status(invalid, "HISTORICAL_POC_ORIGINAL_INPUT"),
            "REJECTED_INTERMEDIATE_SOURCE",
        )
        self.assertEqual(baseline.source_directness_status(valid, "CANDIDATE"), "REJECTED_SOURCE_ROLE")

    def test_05_alpha_is_preserved_by_all_three_methods(self) -> None:
        rgba = Image.new("RGBA", (7, 5), (10, 20, 30, 0))
        rgba.putpixel((3, 2), (200, 150, 100, 128))
        for method in baseline.METHODS:
            resized = baseline.resize_image(rgba, (17, 13), method)
            self.assertEqual(resized.mode, "RGBA", method)
            self.assertLess(resized.getchannel("A").getextrema()[0], 255, method)

    def test_06_different_existing_candidate_is_never_silently_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            destination = root / "candidate.png"
            destination.write_bytes(b"existing-content")
            temp = root / "new.tmp"
            temp.write_bytes(b"different-content")
            before = destination.read_bytes()
            with self.assertRaisesRegex(baseline.BaselineError, "CANDIDATE_CONFLICT_DIFFERENT_CONTENT"):
                baseline.commit_candidate(temp, destination)
            self.assertEqual(destination.read_bytes(), before)

    def test_07_manifest_has_eight_unique_eligible_sources_and_verified_snapshots(self) -> None:
        samples = self.manifest["samples"]
        self.assertEqual(len(samples), 8)
        self.assertEqual(len({sample["sample_id"] for sample in samples}), 8)
        self.assertTrue(all(sample["eligible"] and sample["below_4k"] for sample in samples))
        snapshots = self.results["snapshots"]
        self.assertEqual(len(snapshots), 8)
        self.assertTrue(all(row["verified"] for row in snapshots))
        expected = {sample["sample_id"]: sample["sha256"] for sample in samples}
        self.assertEqual({row["sample_id"]: row["sha256"] for row in snapshots}, expected)

    def test_08_all_24_candidates_decode_and_obey_geometry_without_crop_stretch_or_padding(self) -> None:
        candidates = self.results["candidates"]
        self.assertEqual(len(candidates), 24)
        self.assertEqual({row["method"] for row in candidates}, set(baseline.METHODS))
        for row in candidates:
            self.assertTrue(Path(row["output_path"]).is_file(), row["output_path"])
            self.assertTrue(row["success"], (row["sample_id"], row["method"]))
            self.assertEqual(row["decode_status"], "PASS")
            self.assertEqual(row["dimension_status"], "PASS")
            self.assertEqual(row["aspect_ratio_status"], "PASS")
            self.assertLessEqual(row["aspect_ratio_error_pixels"], 1.0)
            self.assertEqual(row["crop_status"], "ABSENT")
            self.assertEqual(row["stretch_status"], "ABSENT")
            self.assertEqual(row["padding_status"], "ABSENT")
            self.assertEqual(max(row["target_width"], row["target_height"]), 3840)

    def test_09_format_mode_and_alpha_results(self) -> None:
        for row in self.results["candidates"]:
            self.assertEqual(row["format"], "PNG")
            self.assertGreater(row["output_size_bytes"], 0)
            self.assertEqual(row["alpha_status"], "PASS")
            if row["sample_id"] == "S08":
                self.assertTrue(row["has_alpha"])
                self.assertLess(row["alpha_extrema"][0], 255)
            else:
                self.assertFalse(row["has_alpha"])

    def test_10_sources_are_direct_and_byte_metadata_unchanged(self) -> None:
        self.assertTrue(self.results["source_files_unchanged"])
        self.assertEqual(self.results["source_states_before"], self.results["source_states_after"])
        for row in self.results["candidates"]:
            self.assertEqual(row["source_directness_status"], "PASS")
            self.assertNotIn("1080p", row["source_path"].lower())

    def test_11_selected_method_determinism_is_file_and_pixel_exact(self) -> None:
        determinism = self.determinism
        self.assertEqual(determinism["status"], "PASS")
        self.assertEqual({row["sample_id"] for row in determinism["records"]}, {"S01", "S03"})
        for row in determinism["records"]:
            self.assertTrue(row["distinct_processes"])
            self.assertTrue(row["distinct_output_directories"])
            self.assertTrue(all(row["comparisons"].values()))
            self.assertEqual({run["exit_code"] for run in row["runs"]}, {0})
            self.assertEqual(len({run["process_id"] for run in row["runs"]}), 2)
            self.assertEqual(len({run["isolated_output_directory"] for run in row["runs"]}), 2)

    def test_12_no_formal_directory_settings_or_runtime_fallback_side_effect(self) -> None:
        checks = self.results["protected_state_checks"]
        self.assertTrue(checks["settings_unchanged"])
        self.assertTrue(checks["formal_4k_directory_unchanged"])
        self.assertTrue(checks["project_runtime_directories_unchanged"])
        before = self.results["protected_state_before"]
        after = self.results["protected_state_after"]
        self.assertFalse(before["formal_4k_directory"]["exists"])
        self.assertFalse(after["formal_4k_directory"]["exists"])
        self.assertFalse(before["project_runtime_directories"][0]["exists"])
        self.assertFalse(after["project_runtime_directories"][0]["exists"])
        artifact_root = baseline.ARTIFACT_ROOT.resolve()
        self.assertTrue(all(baseline.is_relative_to(Path(row["output_path"]), artifact_root) for row in self.results["candidates"]))

    def test_13_roi_normalization_and_reverse_mapping_error(self) -> None:
        source_size = (1086, 1448)
        target_size = (2880, 3840)
        source_box = baseline.centered_box(*source_size, [0.53, 0.31], 512)
        normalized = baseline.normalize_box(source_box, *source_size)
        target_box = baseline.map_normalized_box(normalized, *target_size)
        errors = baseline.reverse_mapping_errors(source_box, target_box, source_size, target_size)
        self.assertLessEqual(errors["maximum"], 1.0)
        self.assertAlmostEqual((source_box[2] - source_box[0]) / source_size[0], normalized["x1"] - normalized["x0"])
        self.assertAlmostEqual((target_box[2] - target_box[0]) / target_size[0], normalized["x1"] - normalized["x0"], places=3)

    def test_14_all_14_comparisons_have_matched_roi_and_three_native_crops(self) -> None:
        manifest = self.comparison_manifest
        self.assertEqual(manifest["version"], "4K_STAGE_1_ROI_COMPARISON_V2")
        self.assertEqual(manifest["comparison_count"], 14)
        native_paths: set[str] = set()
        for row in manifest["comparisons"]:
            self.assertEqual(row["mapping_status"], "PASS")
            self.assertLessEqual(row["maximum_reverse_mapping_error_source_pixels"], 1.0)
            self.assertEqual(set(row["candidate_pixel_boxes"]), set(baseline.METHODS))
            self.assertEqual(set(row["candidate_native_100_percent"]), set(baseline.METHODS))
            self.assertTrue(Path(row["semantic_comparison_path"]).is_file())
            for method, native in row["candidate_native_100_percent"].items():
                self.assertEqual(native["scale"], "100_PERCENT_NATIVE_PIXELS", method)
                self.assertTrue(Path(native["path"]).is_file(), native["path"])
                native_paths.add(native["path"])
            for errors in row["reverse_mapping_error_source_pixels"].values():
                self.assertLessEqual(max(errors[edge] for edge in ("x0", "y0", "x1", "y1")), 1.0)
        self.assertEqual(len(native_paths), 42)

    def test_15_candidate_failure_record_has_full_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "probe.png"
            Image.new("RGB", (20, 16), (20, 40, 60)).save(source)
            sample = baseline.build_probe_sample(source, "FAULT_S15")
            with self.assertRaises(baseline.CandidateExecutionError) as raised:
                baseline.execute_candidate(sample, "pillow_lanczos", root / "output", fault_stage="resize")
            record = raised.exception.record
            self.assertFalse(record["success"])
            self.assertEqual(record["sample_id"], "FAULT_S15")
            self.assertEqual(record["method"], "pillow_lanczos")
            self.assertEqual(record["failure_stage"], "resize")
            self.assertEqual(record["error_type"], "OSError")
            self.assertIn("CONTROLLED_FAILURE:resize", record["error_message"])
            self.assertFalse(Path(record["output_path"]).exists())

    def test_16_cli_failure_is_nonzero_persisted_and_does_not_pollute_formal_results(self) -> None:
        formal_candidates_before = {
            row["output_path"]: baseline.sha256_file(Path(row["output_path"])) for row in self.results["candidates"]
        }
        formal_result_before = baseline.sha256_file(self.results_path)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "probe.png"
            source.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (24, 18), (80, 100, 120)).save(source)
            failure_record = root / "failure.json"
            command = [
                sys.executable,
                str(Path(baseline.__file__).resolve()),
                "--failure-probe-source",
                str(source),
                "--failure-probe-output-root",
                str(root / "isolated_output"),
                "--failure-probe-record",
                str(failure_record),
                "--failure-probe-sample-id",
                "CLI_FAULT_S16",
                "--failure-probe-method",
                "opencv_cubic",
                "--failure-probe-stage",
                "resize",
            ]
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertNotEqual(completed.returncode, 0)
            summary = json.loads(completed.stdout.strip().splitlines()[-1])
            persisted = json.loads(failure_record.read_text(encoding="utf-8"))
            self.assertEqual(summary["sample_id"], "CLI_FAULT_S16")
            self.assertEqual(summary["method"], "opencv_cubic")
            self.assertEqual(summary["failure_stage"], "resize")
            self.assertEqual(summary["error_type"], "OSError")
            self.assertEqual({key: summary[key] for key in persisted}, persisted)
            self.assertFalse(Path(persisted["output_path"]).exists())
        self.assertEqual(baseline.sha256_file(self.results_path), formal_result_before)
        self.assertEqual(
            {path: baseline.sha256_file(Path(path)) for path in formal_candidates_before},
            formal_candidates_before,
        )


if __name__ == "__main__":
    unittest.main()
