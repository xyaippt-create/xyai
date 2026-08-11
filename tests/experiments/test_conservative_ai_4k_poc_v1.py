from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from tools.experiments import conservative_ai_4k_poc_v1 as stage2
from tools.experiments import traditional_4k_baseline_v1 as stage1


def pass_gates() -> dict[str, str]:
    return {name: "PASS" for name in stage2.MANDATORY_TECHNICAL_GATES}


def alpha_fixture(size: tuple[int, int] = (96, 72)) -> tuple[Image.Image, Image.Image]:
    width, height = size
    yy, xx = np.indices((height, width))
    distance = np.maximum(np.abs(xx - width // 2) - 24, np.abs(yy - height // 2) - 18)
    alpha = np.clip(255 - (distance + 5) * 28, 0, 255).astype(np.uint8)
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    rgb[:, :, 0] = np.clip(40 + xx * 2, 0, 255)
    rgb[:, :, 1] = np.clip(60 + yy * 2, 0, 255)
    rgb[:, :, 2] = 145
    baseline = Image.fromarray(np.dstack((rgb, alpha)), mode="RGBA")
    texture = ((((xx // 2) + (yy // 2)) % 2) * 20 - 10)[:, :, None]
    ai = Image.fromarray(np.clip(rgb.astype(np.int16) + texture, 0, 255).astype(np.uint8), mode="RGB")
    return baseline, ai


def formal_4k_target_dimensions() -> tuple[int, int]:
    decision, target = stage1.target_dimensions(100, 50)
    if decision != "PROCESS" or target is None:
        raise AssertionError(f"UNEXPECTED_4K_TARGET_DECISION:{decision}")
    return target


def actual_geometry_events(extra: list[dict[str, object]] | None = None) -> list[dict[str, object]]:
    target_dimensions = formal_4k_target_dimensions()
    definitions = (
        ("source_open", "exif_transpose", False, [100, 50], [100, 50]),
        ("model_inference", "model_input", True, [100, 50], [100, 50]),
        ("model_decode", "model_super_resolution", True, [100, 50], [400, 200]),
        ("normalize_4k", "resize", True, [400, 200], list(target_dimensions)),
        ("safety_blend", "pixel_blend", True, list(target_dimensions), list(target_dimensions)),
        ("encode_save", "encode", True, list(target_dimensions), list(target_dimensions)),
        ("decode_validation", "decode_measurement", True, list(target_dimensions), list(target_dimensions)),
    )
    events: list[dict[str, object]] = []
    for stage, operation, applied, before, after in definitions:
        stage2.append_geometry_event(
            events,
            sample_id="S01",
            run_id="run-test",
            stage=stage,
            operation=operation,
            applied=applied,
            before_dimensions=before,
            after_dimensions=after,
            method="TEST",
            parameters={},
        )
    for event in extra or []:
        stage2.append_geometry_event(
            events,
            sample_id="S01",
            run_id="run-test",
            stage=str(event["stage"]),
            operation=str(event["operation"]),
            applied=bool(event["applied"]),
            before_dimensions=event.get("before_dimensions", list(target_dimensions)),
            after_dimensions=event.get("after_dimensions", list(target_dimensions)),
            method="TEST",
            parameters=dict(event.get("parameters", {})),
        )
    return events


def transform_trace(
    events: list[dict[str, object]] | None,
    *,
    actual_dimensions: tuple[int, int] | None = None,
    source_orientation: int = 1,
) -> dict[str, object]:
    target_dimensions = formal_4k_target_dimensions()
    return stage2.build_transform_trace(
        "S01",
        "run-test",
        (100, 50),
        (100, 50),
        target_dimensions,
        actual_dimensions or target_dimensions,
        source_orientation=source_orientation,
        operation_records=events,
        candidate_sha256="a" * 64,
    )


class TechnicalGateTests(unittest.TestCase):
    def test_01_tile_seam_review_makes_success_false(self) -> None:
        gates = pass_gates()
        gates["tile_seam_validation"] = "REVIEW"
        result = stage2.aggregate_mandatory_gates(gates)
        self.assertFalse(result["success"])
        self.assertEqual(result["technical_status"], "REVIEW_REQUIRED")
        self.assertEqual(result["review_required_gates"], ["tile_seam_validation"])

    def test_02_tile_seam_fail_makes_success_false(self) -> None:
        gates = pass_gates()
        gates["tile_seam_validation"] = "FAIL"
        result = stage2.aggregate_mandatory_gates(gates)
        self.assertFalse(result["success"])
        self.assertEqual(result["technical_status"], "FAIL")
        self.assertIn("tile_seam_validation", result["blocking_gates"])

    def test_03_every_mandatory_gate_failure_blocks_success(self) -> None:
        for gate in stage2.MANDATORY_TECHNICAL_GATES:
            with self.subTest(gate=gate):
                gates = pass_gates()
                gates[gate] = "FAIL"
                self.assertFalse(stage2.aggregate_mandatory_gates(gates)["success"])

    def test_04_unknown_gate_blocks_success(self) -> None:
        gates = pass_gates()
        gates["alpha_validation"] = "UNKNOWN"
        result = stage2.aggregate_mandatory_gates(gates)
        self.assertFalse(result["success"])
        self.assertIn("alpha_validation", result["blocking_gates"])

    def test_05_only_all_pass_can_succeed(self) -> None:
        result = stage2.aggregate_mandatory_gates(pass_gates())
        self.assertTrue(result["success"])
        self.assertEqual(result["technical_status"], "PASS")
        self.assertEqual(result["blocking_gates"], [])
        self.assertEqual(result["review_required_gates"], [])

    def test_05a_failed_technical_run_without_structure_evidence_is_not_ready(self) -> None:
        self.assertEqual(stage2.route_b_structure_status_for_blocked_run([]), "NOT_READY")

    def test_06_crop_in_trace_fails_geometry_gate(self) -> None:
        trace = transform_trace(
            actual_geometry_events([{"stage": "normalize_4k", "operation": "crop", "applied": True}])
        )
        self.assertEqual(stage2.geometry_gate_from_trace(trace), "FAIL")

    def test_07_pad_in_trace_fails_geometry_gate(self) -> None:
        trace = transform_trace(
            actual_geometry_events([{"stage": "normalize_4k", "operation": "pad", "applied": True}])
        )
        self.assertEqual(stage2.geometry_gate_from_trace(trace), "FAIL")

    def test_08_unexpected_rotate_fails_orientation_gate(self) -> None:
        events = actual_geometry_events()
        events[0]["applied"] = True
        trace = transform_trace(events)
        self.assertEqual(stage2.orientation_gate_from_trace(trace), "FAIL")

    def test_09_transform_trace_contains_real_operation_evidence(self) -> None:
        trace = transform_trace(actual_geometry_events())
        expected = {
            "sample_id",
            "run_id",
            "source_dimensions",
            "decoded_dimensions",
            "expected_dimensions",
            "actual_dimensions",
            "source_orientation",
            "orientation_normalization_applied",
            "orientation_consistent",
            "model_input_dimensions",
            "model_output_dimensions",
            "ordered_events",
            "candidate_sha256",
            "resize_operation",
            "crop_operation",
            "pad_operation",
            "rotate_operation",
            "aspect_ratio_error",
            "geometry_evidence_source",
            "trace_state",
            "trace_complete",
            "required_sequence",
            "observed_sequence",
            "chain_validation",
        }
        self.assertEqual(set(trace), expected)
        self.assertEqual(trace["geometry_evidence_source"], "LIVE_PIPELINE_OPERATION_TRACE")
        self.assertTrue(trace["trace_complete"])
        self.assertEqual(stage2.geometry_gate_from_trace(trace), "PASS")
        self.assertEqual(trace["expected_dimensions"], [3840, 1920])
        self.assertEqual(trace["actual_dimensions"], [3840, 1920])
        self.assertEqual(trace["resize_operation"]["method"], "TEST")

    def test_09a_missing_actual_operation_trace_is_unknown_and_blocks(self) -> None:
        trace = transform_trace(None)
        self.assertEqual(stage2.geometry_gate_from_trace(trace), "UNKNOWN")
        self.assertEqual(stage2.orientation_gate_from_trace(trace), "UNKNOWN")
        self.assertEqual(trace["geometry_evidence_source"], "MISSING_LIVE_OPERATION_TRACE")
        gates = pass_gates()
        gates["geometry_validation"] = stage2.geometry_gate_from_trace(trace)
        self.assertFalse(stage2.aggregate_mandatory_gates(gates)["success"])

    def test_09b_manual_false_crop_pad_rotate_records_cannot_create_pass(self) -> None:
        events = actual_geometry_events(
            [
                {"stage": "normalize_4k", "operation": "crop", "applied": False},
                {"stage": "normalize_4k", "operation": "pad", "applied": False},
            ]
        )
        self.assertEqual(stage2.geometry_gate_from_trace(transform_trace(events)), "FAIL")

    def test_09c_broken_dimension_chain_fails(self) -> None:
        events = actual_geometry_events()
        events[3]["before_dimensions"] = [399, 200]
        self.assertEqual(stage2.geometry_gate_from_trace(transform_trace(events)), "FAIL")

    def test_09d_final_trace_dimensions_must_match_decoded_candidate(self) -> None:
        self.assertEqual(
            stage2.geometry_gate_from_trace(
                transform_trace(actual_geometry_events(), actual_dimensions=(3841, 1920))
            ),
            "FAIL",
        )


class ExitStatusContractTests(unittest.TestCase):
    @staticmethod
    def forward_record(candidate_path: Path) -> dict[str, object]:
        return {
            "success": True,
            "technical_success": True,
            "technical_status": "PASS",
            "sample_id": "S01",
            "route": stage2.ROUTE_B,
            "run_id": "batch:S01:run-contract",
            "candidate_path": str(candidate_path),
            "candidate_sha256": "a" * 64,
            "geometry_trace_path": str(candidate_path.with_suffix(".geometry.json")),
        }

    def test_exit_01_zero_maps_to_success_and_technical_pass(self) -> None:
        record = stage2.apply_process_exit_contract(self.forward_record(Path("candidate.png")), 0)
        self.assertEqual(record["exit_code"], 0)
        self.assertEqual(record["process_exit_status"], "SUCCESS")
        self.assertTrue(record["technical_success"])
        self.assertEqual(record["technical_status"], "PASS")

    def test_exit_02_nonzero_maps_to_failed_and_technical_fail(self) -> None:
        record = stage2.apply_process_exit_contract(self.forward_record(Path("candidate.png")), 7)
        self.assertEqual(record["exit_code"], 7)
        self.assertEqual(record["process_exit_status"], "FAILED")
        self.assertFalse(record["technical_success"])
        self.assertEqual(record["technical_status"], "FAIL")

    def test_exit_03_missing_maps_to_missing_and_technical_fail(self) -> None:
        record = stage2.apply_process_exit_contract(self.forward_record(Path("candidate.png")), None)
        self.assertIsNone(record["exit_code"])
        self.assertEqual(record["process_exit_status"], "MISSING")
        self.assertFalse(record["technical_success"])
        self.assertEqual(record["technical_status"], "FAIL")

    def test_exit_04_existing_candidate_cannot_override_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            candidate = Path(temporary_directory) / "candidate.png"
            candidate.write_bytes(b"candidate")
            record = stage2.apply_process_exit_contract(self.forward_record(candidate), 7)
            self.assertTrue(candidate.is_file())
            self.assertFalse(record["technical_success"])
            self.assertEqual(record["technical_status"], "FAIL")

    def test_exit_05_existing_candidate_cannot_override_missing_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            candidate = Path(temporary_directory) / "candidate.png"
            candidate.write_bytes(b"candidate")
            record = stage2.apply_process_exit_contract(self.forward_record(candidate), None)
            self.assertTrue(candidate.is_file())
            self.assertFalse(record["technical_success"])
            self.assertEqual(record["technical_status"], "FAIL")

    def test_exit_06_failure_record_contains_exit_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            failed_record = stage2.failure_record(
                "S01",
                stage2.ROUTE_B,
                "model_inference",
                stage2.ModelProcessError("MODEL_PROCESS_FAILED:7", 7),
                root / "source.png",
                root / "candidate.png",
            )
            missing_record = stage2.failure_record(
                "S01",
                stage2.ROUTE_B,
                "model_inference",
                RuntimeError("EXIT_CODE_UNAVAILABLE"),
                root / "source.png",
                root / "candidate.png",
            )
        self.assertEqual(failed_record["exit_code"], 7)
        self.assertEqual(failed_record["process_exit_status"], "FAILED")
        self.assertFalse(failed_record["technical_success"])
        self.assertEqual(failed_record["technical_status"], "FAIL")
        self.assertIsNone(missing_record["exit_code"])
        self.assertEqual(missing_record["process_exit_status"], "MISSING")
        self.assertFalse(missing_record["technical_success"])
        self.assertEqual(missing_record["technical_status"], "FAIL")

    def test_exit_07_forward_execution_matrix_row_contains_exit_fields(self) -> None:
        row = stage2.apply_process_exit_contract(self.forward_record(Path("candidate.png")), 0)
        matrix = json.loads(json.dumps({"row_count": 1, "rows": [row]}))
        self.assertEqual(matrix["row_count"], 1)
        self.assertIn("exit_code", matrix["rows"][0])
        self.assertIn("process_exit_status", matrix["rows"][0])

    def test_exit_08_record_preserves_run_candidate_geometry_association(self) -> None:
        source = self.forward_record(Path("candidate.png"))
        expected = {
            key: source[key]
            for key in ("run_id", "candidate_path", "candidate_sha256", "geometry_trace_path")
        }
        record = stage2.apply_process_exit_contract(source, 0)
        self.assertEqual(
            {key: record[key] for key in expected},
            expected,
        )
        self.assertEqual(record["process_exit_status"], "SUCCESS")


class StructureSafetyTests(unittest.TestCase):
    def test_09e_exact_candidate_still_requires_human_structure_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            current = root / "current.png"
            image = Image.new("RGB", (32, 24), (80, 100, 120))
            image.save(current)
            evidence = stage2.build_route_b_structure_evidence(
                "S01",
                current,
                image,
                image,
                [{"risk": "中文大标题"}],
                "PASS_NO_BLOCKING_SIGNAL",
            )
            self.assertEqual(evidence["status"], "PENDING_HUMAN_REVIEW")
            self.assertFalse(evidence["technical_pass_can_prove_structure_safety"])

    def test_09f_small_scalar_delta_cannot_create_structure_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            current = root / "current.png"
            baseline = Image.new("RGB", (32, 24), (80, 100, 120))
            changed = np.asarray(baseline).copy()
            changed[0, 0, 0] += 1
            candidate = Image.fromarray(changed, mode="RGB")
            candidate.save(current)
            evidence = stage2.build_route_b_structure_evidence(
                "S01",
                current,
                candidate,
                baseline,
                [{"risk": "中文大标题"}],
                "PASS_NO_BLOCKING_SIGNAL",
            )
            self.assertEqual(evidence["status"], "PENDING_HUMAN_REVIEW")
            self.assertFalse(evidence["scalar_metrics_can_prove_structure_safety"])

    def test_09g_alpha_pass_cannot_create_structure_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            current = Path(temporary_directory) / "current.png"
            baseline, _ = alpha_fixture()
            baseline.save(current)
            evidence = stage2.build_route_b_structure_evidence(
                "S08", current, baseline, baseline, [{"risk": "透明区域边缘"}], "PASS_NO_BLOCKING_SIGNAL"
            )
            self.assertEqual(evidence["technical_observations"]["alpha_safety_status"], "PASS")
            self.assertEqual(evidence["status"], "PENDING_HUMAN_REVIEW")
            self.assertFalse(evidence["alpha_pass_can_prove_structure_safety"])

    def test_09h_blocking_automatic_signal_keeps_structure_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            current = Path(temporary_directory) / "current.png"
            image = Image.new("RGB", (32, 24), (80, 100, 120))
            image.save(current)
            evidence = stage2.build_route_b_structure_evidence(
                "S01", current, image, image, [{"risk": "中文大标题"}], "BLOCKED_BY_AUTOMATIC_SIGNAL"
            )
            self.assertEqual(evidence["status"], "NOT_READY")


class FailureProbePathSafetyTests(unittest.TestCase):
    def test_10_external_absolute_record_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "probe"
            with self.assertRaisesRegex(stage2.Stage2Error, "MUST_BE_RELATIVE"):
                stage2.resolve_failure_probe_write_path(root, Path(temporary_directory) / "outside.json")
            self.assertFalse(root.exists())

    def test_11_parent_traversal_is_rejected_without_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "probe"
            with self.assertRaisesRegex(stage2.Stage2Error, "PATH_TRAVERSAL"):
                stage2.resolve_failure_probe_write_path(root, Path("..") / "outside.json")
            self.assertFalse(root.exists())

    def test_12_settings_path_is_protected(self) -> None:
        with self.assertRaisesRegex(stage2.Stage2Error, "PROTECTED_PATH"):
            stage2._reject_protected_probe_path(stage2.SETTINGS_PATH)

    def test_13_formal_directory_is_protected(self) -> None:
        with self.assertRaisesRegex(stage2.Stage2Error, "PROTECTED_PATH"):
            stage2._reject_protected_probe_path(stage2.FORMAL_4K_DIRECTORY / "probe.json")

    def test_14_repository_path_is_protected(self) -> None:
        with self.assertRaisesRegex(stage2.Stage2Error, "PROTECTED_PATH"):
            stage2._reject_protected_probe_path(stage2.PROJECT_ROOT / "probe.json")

    def test_15_stage1_path_is_protected(self) -> None:
        with self.assertRaisesRegex(stage2.Stage2Error, "PROTECTED_PATH"):
            stage2._reject_protected_probe_path(stage2.STAGE1_ROOT / "probe.json")

    def test_16_original_stage2_batch_is_protected(self) -> None:
        with self.assertRaisesRegex(stage2.Stage2Error, "PROTECTED_PATH"):
            stage2._reject_protected_probe_path(stage2.ORIGINAL_STAGE2_BATCH_ROOT / "probe.json")

    def test_17_new_stage2_batch_is_protected(self) -> None:
        with self.assertRaisesRegex(stage2.Stage2Error, "PROTECTED_PATH"):
            stage2._reject_protected_probe_path(stage2.STAGE2_ROOT / "batch_new" / "probe.json")

    def test_18_reparse_point_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temp = Path(temporary_directory)
            root = temp / "probe"
            outside = temp / "outside"
            root.mkdir()
            outside.mkdir()
            link = root / "escape"
            created = False
            try:
                os.symlink(outside, link, target_is_directory=True)
                created = True
            except OSError:
                if os.name == "nt":
                    completed = subprocess.run(
                        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                        capture_output=True,
                        text=True,
                    )
                    created = completed.returncode == 0 and link.exists()
            self.assertTrue(created, "Current Windows environment must provide a real symlink or junction probe")
            try:
                with self.assertRaisesRegex(stage2.Stage2Error, "REPARSE_POINT"):
                    stage2.resolve_failure_probe_write_path(root, Path("escape") / "failure.json")
            finally:
                if link.exists() or link.is_symlink():
                    os.rmdir(link)


class AlphaProtectionTests(unittest.TestCase):
    def test_19_multilevel_alpha_gradient_is_detected_and_protected(self) -> None:
        baseline, _ = alpha_fixture()
        _, metrics = stage2.alpha_protection_mask(baseline)
        self.assertGreater(metrics["alpha_unique_value_count"], 2)
        self.assertGreater(metrics["alpha_gradient_edge_pixel_count"], 0)
        self.assertGreater(metrics["alpha_protection_mask_pixel_count"], 0)

    def test_20_semitransparent_soft_edge_is_protected(self) -> None:
        baseline, _ = alpha_fixture()
        mask, metrics = stage2.alpha_protection_mask(baseline)
        alpha = np.asarray(baseline.getchannel("A"))
        self.assertGreater(metrics["semi_transparent_pixel_count"], 0)
        self.assertTrue(np.all(mask[(alpha > 0) & (alpha < 255)]))

    def test_21_fully_transparent_edge_pixels_are_in_protection_band(self) -> None:
        baseline, _ = alpha_fixture()
        mask, _ = stage2.alpha_protection_mask(baseline)
        alpha = np.asarray(baseline.getchannel("A"))
        self.assertGreater(np.count_nonzero(mask & (alpha == 0)), 0)

    def test_22_fully_opaque_rgb_sample_processes_normally(self) -> None:
        base = Image.new("RGB", (64, 48), (80, 100, 120))
        data = np.asarray(base).copy()
        data[8:40:2, 8:56:2] = np.clip(data[8:40:2, 8:56:2].astype(np.int16) + 24, 0, 255)
        output, metrics = stage2.controlled_increment(base, Image.fromarray(data, mode="RGB"))
        self.assertEqual(output.mode, "RGB")
        self.assertEqual(metrics["alpha_protection"]["status"], "PASS")

    def test_23_hard_protection_is_reapplied_after_feather(self) -> None:
        baseline, ai = alpha_fixture()
        output, metrics = stage2.controlled_increment(baseline, ai)
        mask, _ = stage2.alpha_protection_mask(baseline)
        self.assertTrue(metrics["final_hard_protection_reapplied_after_feather"])
        self.assertTrue(
            np.array_equal(np.asarray(output.convert("RGB"))[mask], np.asarray(baseline.convert("RGB"))[mask])
        )

    def test_24_alpha_channel_bytes_are_preserved(self) -> None:
        baseline, ai = alpha_fixture()
        output, _ = stage2.controlled_increment(baseline, ai)
        self.assertEqual(output.getchannel("A").tobytes(), baseline.getchannel("A").tobytes())

    def test_25_black_composite_has_no_protected_edge_pollution(self) -> None:
        baseline, ai = alpha_fixture()
        output, _ = stage2.controlled_increment(baseline, ai)
        self.assertEqual(stage2.alpha_safety_metrics(output, baseline)["black_composite_changed_pixels"], 0)

    def test_26_white_composite_has_no_protected_edge_pollution(self) -> None:
        baseline, ai = alpha_fixture()
        output, _ = stage2.controlled_increment(baseline, ai)
        self.assertEqual(stage2.alpha_safety_metrics(output, baseline)["white_composite_changed_pixels"], 0)

    def test_27_checkerboard_composite_has_no_protected_edge_pollution(self) -> None:
        baseline, ai = alpha_fixture()
        output, _ = stage2.controlled_increment(baseline, ai)
        self.assertEqual(
            stage2.alpha_safety_metrics(output, baseline)["checkerboard_composite_changed_pixels"], 0
        )

    def test_28_protection_mask_does_not_lock_the_whole_image(self) -> None:
        baseline, _ = alpha_fixture()
        mask, _ = stage2.alpha_protection_mask(baseline)
        self.assertGreater(np.count_nonzero(mask), 0)
        self.assertLess(np.count_nonzero(mask), mask.size)

    def test_29_nonprotected_region_retains_controlled_ai_increment(self) -> None:
        baseline, ai = alpha_fixture()
        output, _ = stage2.controlled_increment(baseline, ai)
        metrics = stage2.alpha_safety_metrics(output, baseline)
        self.assertGreater(metrics["non_protected_changed_pixels"], 0)
        self.assertLessEqual(metrics["non_protected_max_rgb_delta"], 5)


@unittest.skipUnless(os.environ.get("HDDE_STAGE2_BATCH_ID"), "HDDE_STAGE2_BATCH_ID is required for artifact tests")
class RemediationBatchContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.batch_root = stage2.STAGE2_ROOT / os.environ["HDDE_STAGE2_BATCH_ID"]
        cls.results = json.loads((cls.batch_root / "run_results.json").read_text(encoding="utf-8"))
        cls.matrix = json.loads((cls.batch_root / "execution_matrix.json").read_text(encoding="utf-8"))
        cls.roi_manifest = json.loads(
            (cls.batch_root / "review_package" / "roi_manifest.json").read_text(encoding="utf-8")
        )

    def test_30_s08_real_protected_rgb_and_alpha_are_zero_change(self) -> None:
        row = next(row for row in self.results["candidates"] if row["sample_id"] == "S08" and row["route"] == stage2.ROUTE_B)
        self.assertGreater(row["alpha_metrics"]["alpha_protection_mask_pixel_count"], 0)
        self.assertEqual(row["alpha_metrics"]["alpha_edge_changed_pixels"], 0)
        self.assertEqual(row["alpha_metrics"]["alpha_edge_max_rgb_delta"], 0)
        self.assertEqual(row["alpha_metrics"]["alpha_channel_changed_pixels"], 0)

    def test_31_execution_matrix_has_eight_by_two_complete_rows(self) -> None:
        self.assertEqual(self.matrix["row_count"], 16)
        self.assertEqual(len(self.matrix["rows"]), 16)
        required = {
            "sample_id", "route", "source_batch", "revalidated_by_remediation", "source_path",
            "lanczos_path", "candidate_path", "source_dimensions", "expected_dimensions", "output_dimensions",
            "runtime_seconds", "output_size_bytes", "format", "color_mode", "alpha_status", "geometry_gate",
            "orientation_gate", "tile_seam_gate", "alpha_gate", "structure_safety_gate", "technical_success",
            "technical_status", "blocking_gates", "review_required_gates", "route_decision", "evidence_path",
            "run_id", "run_started_at", "run_ended_at", "automatic_risk_precheck",
        }
        for row in self.matrix["rows"]:
            self.assertTrue(required.issubset(row), row)

    def test_32_route_a_is_read_only_revalidated_and_rejected(self) -> None:
        rows = [row for row in self.matrix["rows"] if row["route"] == stage2.ROUTE_A]
        self.assertEqual(len(rows), 8)
        self.assertFalse((self.batch_root / "candidates" / stage2.ROUTE_A).exists())
        for row in rows:
            self.assertTrue(row["revalidated_by_remediation"])
            self.assertEqual(row["source_batch"], stage2.ORIGINAL_STAGE2_BATCH_ROOT.name)
            self.assertEqual(row["structure_safety_gate"], "FAIL")
            self.assertEqual(row["route_decision"], "REJECTED_UNSAFE")
            self.assertFalse(row["technical_success"])
            self.assertEqual(row["geometry_gate"], "UNKNOWN")
            self.assertEqual(row["route_a_geometry_evidence_status"], "UNKNOWN_HISTORICAL_TRACE_UNAVAILABLE")
            self.assertEqual(row["transform_trace"]["geometry_evidence_source"], "MISSING_LIVE_OPERATION_TRACE")
            self.assertTrue(stage2.is_relative_to(Path(row["candidate_path"]), stage2.ORIGINAL_STAGE2_BATCH_ROOT))

    def test_33_all_eight_route_b_candidates_pass_technical_gates_and_wait_for_human(self) -> None:
        rows = [row for row in self.matrix["rows"] if row["route"] == stage2.ROUTE_B]
        self.assertEqual(len(rows), 8)
        self.assertEqual(len({row["run_id"] for row in rows}), 8)
        for row in rows:
            self.assertTrue(row["technical_success"], row)
            self.assertEqual(set(row["mandatory_gates"].values()), {"PASS"})
            self.assertEqual(row["automatic_risk_precheck"], "PASS_NO_BLOCKING_SIGNAL")
            self.assertEqual(row["structure_safety_gate"], "PENDING_HUMAN_REVIEW")
            self.assertEqual(row["structure_status_source"], "HUMAN_VISUAL_REVIEW_REQUIRED")
            self.assertEqual(row["transform_trace"]["geometry_evidence_source"], "LIVE_PIPELINE_OPERATION_TRACE")
            self.assertTrue(row["transform_trace"]["trace_complete"])
            self.assertNotIn("DEFAULT", json.dumps(row["transform_trace"], ensure_ascii=False).upper())
            self.assertEqual(row["transform_trace"]["candidate_sha256"], row["output_sha256"])
            self.assertTrue(all(row["transform_trace"]["chain_validation"].values()))
            self.assertEqual(row["route_decision"], "PENDING_HUMAN_REVIEW")
            self.assertTrue(Path(row["candidate_path"]).is_file())

    def test_33a_route_b_structure_evidence_never_claims_automatic_pass(self) -> None:
        rows = [row for row in self.matrix["rows"] if row["route"] == stage2.ROUTE_B]
        self.assertEqual(len(rows), 8)
        for row in rows:
            evidence = row["structure_safety_evidence"]
            self.assertEqual(evidence["sample_id"], row["sample_id"])
            self.assertEqual(evidence["evidence_source"], "HUMAN_VISUAL_REVIEW_REQUIRED")
            self.assertEqual(evidence["status"], "PENDING_HUMAN_REVIEW")
            self.assertFalse(evidence["scalar_metrics_can_prove_structure_safety"])
            self.assertFalse(evidence["alpha_pass_can_prove_structure_safety"])
            self.assertFalse(evidence["technical_pass_can_prove_structure_safety"])
            self.assertTrue(Path(row["evidence_path"]).is_file())

    def test_33b_geometry_trace_manifest_has_eight_live_records(self) -> None:
        payload = json.loads(
            (self.batch_root / "review_package" / "geometry_trace_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["count"], 8)
        self.assertEqual(len(payload["records"]), 8)
        for record in payload["records"]:
            self.assertEqual(record["geometry_gate"], "PASS")
            trace = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
            self.assertEqual(trace["geometry_evidence_source"], "LIVE_PIPELINE_OPERATION_TRACE")
            self.assertEqual(trace["candidate_sha256"], record["candidate_sha256"])

    def test_34_review_package_has_eight_three_way_full_comparisons(self) -> None:
        records = json.loads(
            (self.batch_root / "review_package" / "full_comparison_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(records), 8)
        self.assertTrue(all(Path(record["path"]).is_file() for record in records))

    def test_35_review_package_has_fourteen_rois_and_twenty_eight_native_crops(self) -> None:
        self.assertEqual(self.roi_manifest["roi_count"], 14)
        self.assertEqual(self.roi_manifest["native_100_percent_count"], 28)
        for row in self.roi_manifest["records"]:
            self.assertEqual(set(row["native_100_percent"]), {"pillow_lanczos", stage2.ROUTE_B})

    def test_36_alpha_evidence_contains_s08_and_synthetic_three_backgrounds(self) -> None:
        payload = json.loads(
            (self.batch_root / "review_package" / "alpha_evidence" / "alpha_evidence_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual({record["evidence_id"] for record in payload["records"]}, {"S08", "SYNTHETIC_MULTI_LEVEL_ALPHA"})
        for record in payload["records"]:
            self.assertEqual(set(record["composites"]), {"black", "white", "checkerboard"})

    def test_37_supersession_declares_old_batch_unchanged_and_new_entry(self) -> None:
        payload = json.loads((self.batch_root / "supersession.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "SUPERSEDED_BY_MINIMAL_TRUTHFULNESS_REMEDIATION")
        self.assertFalse(payload["original_batch_modified"])
        self.assertFalse(payload["superseded_remediation_batch_modified"])
        self.assertFalse(payload["blocked_truth_batch_modified"])
        self.assertEqual(len(payload["mapping"]), 8)

    def test_38_review_package_contract_files_and_sha_manifest_exist(self) -> None:
        required = (
            "README_人工视觉复核.md", "observations.json", "risk_assessment.json", "execution_matrix.json",
            "supersession.json", "file_manifest.json", "sha256_manifest.json", "model_and_parameters.json",
            "geometry_trace_manifest.json",
        )
        for relative in required:
            self.assertTrue((self.batch_root / "review_package" / relative).is_file(), relative)
        sha_manifest = json.loads((self.batch_root / "sha256_manifest.json").read_text(encoding="utf-8"))
        for record in sha_manifest["files"]:
            path = self.batch_root / record["path"]
            self.assertEqual(stage2.file_sha256(path), record["sha256"])

    def test_39_failure_probe_cli_is_structured_nonzero_and_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "stage2_failure_probe"
            command = [
                sys.executable, str(Path(stage2.__file__).resolve()), "--failure-probe-output-root", str(root),
                "--failure-probe-record", "failure.json", "--failure-probe-sample-id", "STAGE2_CLI_FAULT",
                "--failure-probe-route", stage2.ROUTE_B, "--failure-probe-stage", "safety_blend",
            ]
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
            persisted = json.loads((root / "failure.json").read_text(encoding="utf-8"))
            self.assertFalse(persisted["success"])
            self.assertFalse(Path(persisted["output_path"]).exists())

    def test_40_protected_state_and_forbidden_directories_are_unchanged(self) -> None:
        self.assertTrue(self.results["protected_state_unchanged"])
        self.assertEqual(self.results["protected_state_before"], self.results["protected_state_after"])
        self.assertFalse(stage2.FORMAL_4K_DIRECTORY.exists())
        self.assertFalse((stage2.PROJECT_ROOT / "runtime_data").exists())

    def test_41_route_b_risk_labels_remain_pending_human_review(self) -> None:
        payload = json.loads(
            (self.batch_root / "review_package" / "risk_assessment.json").read_text(encoding="utf-8")
        )
        route_b = payload["routes"][stage2.ROUTE_B]
        self.assertEqual(route_b["automatic_risk_precheck"], "PASS_NO_BLOCKING_SIGNAL")
        self.assertEqual(route_b["structure_safety_status"], "PENDING_HUMAN_REVIEW")
        self.assertEqual(route_b["structure_status_source"], "HUMAN_VISUAL_REVIEW_REQUIRED")
        self.assertEqual(len(route_b["sample_evidence"]), 8)
        self.assertEqual(set(route_b["labels"].values()), {"PENDING_HUMAN_REVIEW"})


if __name__ == "__main__":
    unittest.main()
