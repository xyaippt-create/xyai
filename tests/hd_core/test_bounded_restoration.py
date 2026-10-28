from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from engine.hd_core.bounded_restoration import (
    ACTIVE,
    NEED_PROOF,
    NO_OP,
    SAFE_PROFILE,
    SUPPORTED_TARGET_DEGRADATION,
    UNSUPPORTED,
    apply_bounded_residual,
    attach_baseline_alpha,
    bounded_candidate_definition,
    bounded_restoration_candidate,
    build_degradation_profile,
    build_threshold_provenance,
    restore_bounded_candidate,
)
from engine.hd_core.candidate_framework import PRODUCT, run_4k_candidate
from tools.experiments.e1_02_quality_delivery_gate import (
    QUALITY_GAIN_NOT_PROVEN,
    QUALITY_GAIN_PROVEN,
    evaluate_arrays,
)
from tools.experiments.e4k_04_bounded_restoration_core import (
    OUTPUT_ROOT as E4K_04_OUTPUT_ROOT,
    derive_case_summary_evidence,
    validate_summary_raw_evidence,
    validate_artifact as validate_e4k_04_artifact,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gradient_rgb(height: int = 64, width: int = 64) -> np.ndarray:
    x = np.linspace(24, 184, width, dtype=np.uint8)[None, :]
    y = np.linspace(0, 24, height, dtype=np.uint8)[:, None]
    base = np.clip(x.astype(np.int16) + y.astype(np.int16), 0, 215).astype(np.uint8)
    return np.dstack((base, np.clip(base + 18, 0, 255), np.clip(base + 32, 0, 255)))


def _jpeg_probe(path: Path) -> np.ndarray:
    rgb = _gradient_rgb(96, 128)
    rgb[18:78, 40:44] = (20, 20, 20)
    rgb[18:22, 40:100] = (235, 235, 235)
    for x in range(8, 120, 16):
        rgb[80:88, x : x + 6] = (30, 30, 30)
    Image.fromarray(rgb, "RGB").save(path, format="JPEG", quality=42, subsampling=2)
    return rgb


class BoundedRestorationTest(unittest.TestCase):
    def test_target_degradation_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "probe.jpg"
            _jpeg_probe(source)
            result = build_degradation_profile(source)
        self.assertEqual(result["status"], SUPPORTED_TARGET_DEGRADATION)
        self.assertEqual(result["restoration_activation"], ACTIVE)
        self.assertTrue(result["compression_evidence"]["luma_quantization_table_valid"])

    def test_unsupported_degradation_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "probe.png"
            Image.fromarray(_gradient_rgb(), "RGB").save(source)
            result = build_degradation_profile(source)
        self.assertEqual(result["status"], UNSUPPORTED)
        self.assertEqual(result["restoration_activation"], NO_OP)

    def test_uncertain_degradation_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "conflicting.jpg"
            Image.fromarray(_gradient_rgb(), "RGB").save(source, format="PNG")
            result = build_degradation_profile(source)
        self.assertEqual(result["status"], NEED_PROOF)
        self.assertEqual(result["restoration_activation"], NO_OP)

    def test_residual_budget_enforced(self) -> None:
        baseline = _gradient_rgb()
        raw = np.full(baseline.shape[:2], 50.0, dtype=np.float32)
        candidate, record = apply_bounded_residual(baseline, raw)
        delta = np.abs(candidate.astype(np.int16) - baseline.astype(np.int16))
        self.assertLessEqual(int(delta.max()), int(SAFE_PROFILE.residual_absolute_budget))
        self.assertGreater(record["absolute_budget_clamped_count"], 0)

    def test_nonfinite_residual_fail_closed(self) -> None:
        baseline = _gradient_rgb()
        raw = np.zeros(baseline.shape[:2], dtype=np.float32)
        raw[3, 4] = np.nan
        candidate, record = apply_bounded_residual(baseline, raw)
        self.assertTrue(np.array_equal(candidate, baseline))
        self.assertTrue(record["fail_closed"])
        self.assertEqual(record["fail_closed_reason"], "NONFINITE_RESIDUAL")

    def test_zero_budget_returns_baseline(self) -> None:
        baseline = _gradient_rgb()
        profile = replace(SAFE_PROFILE, residual_absolute_budget=0.0)
        candidate, record = apply_bounded_residual(
            baseline,
            np.ones(baseline.shape[:2], dtype=np.float32),
            profile=profile,
        )
        self.assertTrue(np.array_equal(candidate, baseline))
        self.assertEqual(record["restoration_activation"], NO_OP)

    def test_hf_budget_clamps_oversharpen(self) -> None:
        baseline = np.full((64, 64, 3), 128, dtype=np.uint8)
        _yy, xx = np.indices((64, 64))
        raw = np.where((xx // 2) % 2 == 0, 12.0, -12.0).astype(np.float32)
        candidate, record = apply_bounded_residual(baseline, raw)
        self.assertTrue(record["hf_clamped"])
        self.assertLessEqual(record["candidate_hf_energy"], record["hf_budget"])
        self.assertTrue(np.array_equal(candidate, baseline))

    def test_hf_increase_does_not_auto_prove_gain(self) -> None:
        baseline = _gradient_rgb()
        raw = np.tile(np.array([-8.0, 8.0], dtype=np.float32), (64, 32))
        _candidate, record = apply_bounded_residual(baseline, raw)
        self.assertTrue(record["hf_clamped"])
        self.assertNotIn("quality_gain_status", record)

    def _edge_suppression_fixture(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        baseline = np.zeros((64, 64, 3), dtype=np.uint8)
        baseline[:, :32] = (24, 24, 24)
        baseline[:, 32:] = (232, 232, 232)
        raw = np.zeros((64, 64), dtype=np.float32)
        raw[:, 29:32] = 12.0
        raw[:, 32:35] = -12.0
        protection = np.ones((64, 64), dtype=np.float32)
        protection[:, 27:37] = 0.0
        return baseline, raw, protection

    def test_white_edge_suppressed(self) -> None:
        baseline, raw, protection = self._edge_suppression_fixture()
        candidate, _ = apply_bounded_residual(baseline, raw, protection_scale=protection)
        self.assertTrue(np.array_equal(candidate[:, 27:37], baseline[:, 27:37]))

    def test_black_edge_suppressed(self) -> None:
        baseline, raw, protection = self._edge_suppression_fixture()
        candidate, _ = apply_bounded_residual(baseline, -raw, protection_scale=protection)
        self.assertTrue(np.array_equal(candidate[:, 27:37], baseline[:, 27:37]))

    def test_halo_suppressed(self) -> None:
        baseline, raw, protection = self._edge_suppression_fixture()
        candidate, record = apply_bounded_residual(
            baseline, raw, protection_scale=protection
        )
        self.assertTrue(np.array_equal(candidate[:, 27:37], baseline[:, 27:37]))
        self.assertTrue(record["halo_ringing_suppression"]["edge_and_text_residual_lock"])

    def test_ringing_suppressed(self) -> None:
        baseline, raw, protection = self._edge_suppression_fixture()
        raw[:, 26:38] *= np.tile(np.array([-1.0, 1.0]), 6)[None, :]
        candidate, _ = apply_bounded_residual(baseline, raw, protection_scale=protection)
        self.assertTrue(np.array_equal(candidate[:, 27:37], baseline[:, 27:37]))

    def test_text_region_budget_reduced(self) -> None:
        baseline = _gradient_rgb()
        raw = np.ones((64, 64), dtype=np.float32)
        protection = np.ones((64, 64), dtype=np.float32)
        protection[20:40, 10:54] = 0.0
        candidate, _ = apply_bounded_residual(
            baseline, raw, protection_scale=protection
        )
        self.assertTrue(np.array_equal(candidate[20:40, 10:54], baseline[20:40, 10:54]))

    def test_text_uncertain_region_no_op(self) -> None:
        baseline = _gradient_rgb()
        candidate, record = apply_bounded_residual(
            baseline,
            np.ones((64, 64), dtype=np.float32),
            protection_reliable=False,
        )
        self.assertTrue(np.array_equal(candidate, baseline))
        self.assertEqual(record["fail_closed_reason"], "PROTECTION_EVIDENCE_UNCERTAIN")

    def test_structure_mask_protected(self) -> None:
        baseline, raw, protection = self._edge_suppression_fixture()
        candidate, _ = apply_bounded_residual(baseline, raw, protection_scale=protection)
        self.assertTrue(np.array_equal(candidate[:, 27:37], baseline[:, 27:37]))

    def test_color_lock(self) -> None:
        baseline = _gradient_rgb()
        raw = np.ones((64, 64), dtype=np.float32)
        candidate, record = apply_bounded_residual(baseline, raw)
        base = baseline.astype(np.int16)
        changed = candidate.astype(np.int16)
        self.assertTrue(np.array_equal(base[..., 0] - base[..., 1], changed[..., 0] - changed[..., 1]))
        self.assertTrue(np.array_equal(base[..., 2] - base[..., 1], changed[..., 2] - changed[..., 1]))
        self.assertEqual(record["color_lock_status"], "PASS")

    def test_saturation_not_artificially_increased(self) -> None:
        baseline = _gradient_rgb()
        candidate, record = apply_bounded_residual(
            baseline, np.ones((64, 64), dtype=np.float32)
        )
        base_ycc = cv2.cvtColor(baseline, cv2.COLOR_RGB2YCrCb)
        candidate_ycc = cv2.cvtColor(candidate, cv2.COLOR_RGB2YCrCb)
        chroma_delta = np.abs(
            candidate_ycc[..., 1:].astype(np.int16) - base_ycc[..., 1:].astype(np.int16)
        )
        self.assertLessEqual(int(chroma_delta.max()), 1)
        self.assertEqual(record["color_delta"]["maximum_chroma_difference_drift"], 0.0)

    def test_alpha_identity_preserved(self) -> None:
        baseline = np.dstack(
            (
                _gradient_rgb(),
                np.tile(np.arange(64, dtype=np.uint8), (64, 1)) * 4,
            )
        )
        merged = attach_baseline_alpha(baseline[..., :3].copy(), baseline)
        self.assertTrue(np.array_equal(merged[..., 3], baseline[..., 3]))

    def test_semitransparent_edge_preserved(self) -> None:
        baseline = np.dstack((_gradient_rgb(), np.full((64, 64), 127, dtype=np.uint8)))
        merged = attach_baseline_alpha(baseline[..., :3].copy(), baseline)
        self.assertTrue(np.all(merged[..., 3] == 127))

    def test_same_input_same_candidate_pixels_and_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.jpg"
            rgb = _jpeg_probe(source)
            baseline = root / "baseline.png"
            Image.fromarray(rgb, "RGB").resize((256, 192), Image.Resampling.LANCZOS).save(
                baseline, format="PNG", compress_level=6
            )
            first = root / "first.png"
            second = root / "second.png"
            first_record = restore_bounded_candidate(source, baseline, first)
            second_record = restore_bounded_candidate(source, baseline, second)
            self.assertEqual(_sha256(first), _sha256(second))
            self.assertEqual(first_record["output_pixel_sha256"], second_record["output_pixel_sha256"])

    def test_self_developed_product_identity_uses_no_model(self) -> None:
        definition = bounded_candidate_definition()
        contract = definition.identity_contract()
        self.assertEqual(contract["candidate_class"], PRODUCT)
        self.assertEqual(contract["model_id"], "NONE")
        self.assertIn("restoration_profile", contract["canonical_parameters"])

    def test_bounded_candidate_uses_e4k_02(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            baseline = root / "baseline.png"
            Image.fromarray(_gradient_rgb(24, 32), "RGB").save(source)
            Image.fromarray(_gradient_rgb(48, 64), "RGB").save(baseline)
            result = run_4k_candidate(
                source,
                root / "runs",
                definition=bounded_candidate_definition(),
                executor=bounded_restoration_candidate,
                baseline_path=baseline,
                execution_nonce="BOUNDED_FRAMEWORK_TEST",
            )
        self.assertEqual(result["candidate_class"], PRODUCT)
        self.assertFalse(result["model_download"])
        self.assertFalse(result["model_inference_run"])
        self.assertEqual(result["output_validation"]["status"], "PASS")

    def test_bounded_candidate_reaches_real_e1_02(self) -> None:
        validation = validate_e4k_04_artifact()
        summary = json.loads(
            (E4K_04_OUTPUT_ROOT / "summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(summary["e1_01_cases_replayed"], "16/16")
        self.assertTrue(summary["e1_02_connected"])

    def test_production_protection_artifact(self) -> None:
        summary = json.loads(
            (E4K_04_OUTPUT_ROOT / "summary.json").read_text(encoding="utf-8")
        )
        for field in (
            "formal_4k_pipeline_changed",
            "api_4k_changed",
            "e1_01_changed",
            "e1_02_changed",
            "e4k_02_frozen_artifact_changed",
            "product_version_changed",
        ):
            self.assertFalse(summary[field], field)

    def test_no_op_case_not_proven(self) -> None:
        baseline = np.dstack(
            (_gradient_rgb(), np.full((64, 64), 255, dtype=np.uint8))
        )
        result = evaluate_arrays(baseline, baseline.copy(), candidate_class=PRODUCT)
        self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_NOT_PROVEN)

    def test_no_op_false_positive_gain_count_zero(self) -> None:
        baseline = np.dstack(
            (_gradient_rgb(), np.full((64, 64), 255, dtype=np.uint8))
        )
        results = [
            evaluate_arrays(baseline, baseline.copy(), candidate_class=PRODUCT)
            for _ in range(2)
        ]
        self.assertEqual(
            sum(item["quality_gain_status"] == QUALITY_GAIN_PROVEN for item in results),
            0,
        )

    def test_threshold_provenance_complete(self) -> None:
        provenance = build_threshold_provenance()
        self.assertEqual(provenance["status"], "PASS")
        self.assertEqual(provenance["uncalibrated_threshold_count"], 0)
        required = {
            "threshold_name",
            "threshold_value",
            "unit",
            "source_type",
            "source_evidence",
            "calibration_dataset",
            "calibration_method",
            "allowed_range",
            "status",
        }
        self.assertTrue(provenance["thresholds"])
        self.assertTrue(all(required <= set(item) for item in provenance["thresholds"]))

    def test_fixed_threshold_not_mislabeled_source_derived(self) -> None:
        provenance = build_threshold_provenance()
        self.assertTrue(
            all(
                item["source_type"] != "SOURCE_DERIVED_RUNTIME_STATISTIC"
                for item in provenance["thresholds"]
            )
        )
        local_gradient = next(
            item
            for item in provenance["thresholds"]
            if item["threshold_name"] == "local_gradient_budget"
        )
        self.assertEqual(local_gradient["source_type"], "CONTROL_CALIBRATION")

    def test_uncalibrated_threshold_fails_closed(self) -> None:
        baseline = _gradient_rgb()
        profile = replace(SAFE_PROFILE, local_gradient_budget=3.0)
        candidate, record = apply_bounded_residual(
            baseline,
            np.ones(baseline.shape[:2], dtype=np.float32),
            profile=profile,
        )
        self.assertTrue(np.array_equal(candidate, baseline))
        self.assertEqual(record["threshold_status"], "NEED_CALIBRATION")
        self.assertEqual(
            record["fail_closed_reason"], "THRESHOLD_PROVENANCE_NEEDS_CALIBRATION"
        )

    def test_nonfinite_threshold_record_is_json_safe(self) -> None:
        baseline = _gradient_rgb()
        profile = replace(SAFE_PROFILE, local_gradient_budget=float("nan"))
        candidate, record = apply_bounded_residual(
            baseline,
            np.ones(baseline.shape[:2], dtype=np.float32),
            profile=profile,
        )
        self.assertTrue(np.array_equal(candidate, baseline))
        self.assertEqual(record["threshold_status"], "NEED_CALIBRATION")
        json.dumps(record, allow_nan=False)

    def _derived_summary_fixture(self) -> tuple[dict, dict, np.ndarray, np.ndarray]:
        baseline = _gradient_rgb(16, 16)
        candidate = baseline.copy()
        record = {
            "profile": {
                "residual_absolute_budget": 1.0,
                "overshoot_budget": 0.0,
            },
            "restoration_activation": ACTIVE,
            "bounded_residual": {
                "residual_absolute_budget": 1.0,
                "residual_max_abs_after": 0,
                "residual_nonzero_count": 0,
                "overshoot_budget": 0.0,
            },
        }
        e1 = {
            "safety_results": {
                "raw_detection": {
                    "halo_or_ringing": False,
                    "white_edge": False,
                    "black_edge": False,
                }
            }
        }
        return record, e1, baseline, candidate

    def test_summary_derived_from_raw_evidence(self) -> None:
        record, e1, baseline, candidate = self._derived_summary_fixture()
        derived = derive_case_summary_evidence(
            case_id="CONTROL",
            record=record,
            e1_result=e1,
            baseline_pixels=baseline,
            candidate_pixels=candidate,
        )
        self.assertEqual(derived["residual"]["status"], "PASS")
        self.assertEqual(derived["overshoot"]["status"], "PASS")
        self.assertEqual(derived["halo_ringing"]["status"], "PASS")

    def test_tampered_residual_record_rejected(self) -> None:
        record, e1, baseline, candidate = self._derived_summary_fixture()
        record["bounded_residual"]["residual_max_abs_after"] = 1
        derived = derive_case_summary_evidence(
            case_id="CONTROL",
            record=record,
            e1_result=e1,
            baseline_pixels=baseline,
            candidate_pixels=candidate,
        )
        self.assertEqual(derived["residual"]["status"], "FAIL")

    def test_tampered_overshoot_record_rejected(self) -> None:
        record, e1, baseline, candidate = self._derived_summary_fixture()
        record["bounded_residual"]["overshoot_budget"] = 1.0
        derived = derive_case_summary_evidence(
            case_id="CONTROL",
            record=record,
            e1_result=e1,
            baseline_pixels=baseline,
            candidate_pixels=candidate,
        )
        self.assertEqual(derived["overshoot"]["status"], "FAIL")

    def test_tampered_halo_record_rejected(self) -> None:
        record, e1, baseline, candidate = self._derived_summary_fixture()
        e1["safety_results"]["raw_detection"]["halo_or_ringing"] = True
        derived = derive_case_summary_evidence(
            case_id="CONTROL",
            record=record,
            e1_result=e1,
            baseline_pixels=baseline,
            candidate_pixels=candidate,
        )
        self.assertEqual(derived["halo_ringing"]["status"], "FAIL")

    def test_summary_raw_evidence_mismatch_fails(self) -> None:
        summary = {
            "residual_budget": "PASS",
            "overshoot_control": "PASS",
            "halo_ringing_suppression": "PASS",
            "halo_ringing_count": 0,
            "white_edge_count": 0,
            "black_edge_count": 0,
        }
        derived = dict(summary)
        derived.update({"status": "PASS", "residual_budget": "FAIL"})
        failures = validate_summary_raw_evidence(summary, derived)
        self.assertIn(
            "SUMMARY_RAW_EVIDENCE_MISMATCH:residual_budget", failures
        )


if __name__ == "__main__":
    unittest.main()
