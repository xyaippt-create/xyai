from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from engine.hd_core.bounded_restoration import SAFE_PROFILE, build_protection_scale
from engine.hd_core.candidate_framework import PRODUCT, run_4k_candidate
from engine.hd_core.source_domain_restoration import (
    ACTIVE,
    ALGORITHM_ID,
    ALGORITHM_VERSION,
    NO_OP,
    OPERATOR_TYPE,
    SAFE_PROFILE_V2,
    TARGET_DEGRADATION_FAMILY,
    build_calibration_authority_binding,
    build_raw_source_proposal,
    build_source_degradation_profile,
    build_v2_threshold_provenance,
    quantization_aware_luma_restore,
    restore_source_domain_candidate,
    source_domain_candidate_definition,
    source_domain_restoration_candidate,
    validate_runtime_calibration_authorization,
)
from tools.experiments.e4k_04_source_domain_restoration_v2 import (
    OUTPUT_ROOT,
    _mae,
    recompute_calibration_semantics,
    runtime_authorization_semantic_projection,
    validate_calibration_artifact_path_binding,
    validate_artifact,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _probe_rgb(width: int = 128, height: int = 96) -> np.ndarray:
    yy, xx = np.indices((height, width), dtype=np.float32)
    base = 70.0 + xx * 0.7 + 8.0 * np.sin((xx + yy) / 5.0)
    rgb = np.dstack(
        (
            np.clip(base + 25, 0, 255),
            np.clip(base + 10, 0, 255),
            np.clip(base - 8, 0, 255),
        )
    ).astype(np.uint8)
    image = Image.fromarray(rgb, "RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((18, 16, 108, 80), outline=(20, 20, 20), width=3)
    draw.line((18, 80, 108, 16), fill=(235, 235, 235), width=2)
    return np.asarray(image)


class SourceDomainRestorationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = json.loads((OUTPUT_ROOT / "summary.json").read_text(encoding="utf-8"))
        cls.calibration = json.loads(
            (OUTPUT_ROOT / "controlled_calibration" / "controlled_calibration.json").read_text(
                encoding="utf-8"
            )
        )
        cls.calibration_path = (
            OUTPUT_ROOT / "controlled_calibration" / "controlled_calibration.json"
        )
        cls.failed_authority = build_calibration_authority_binding(
            cls.calibration,
            calibration_artifact_sha256=_sha256(cls.calibration_path),
        )
        cls.failed_provenance = build_v2_threshold_provenance(
            calibration_authority=cls.failed_authority
        )
        cls.failed_candidate_id = source_domain_candidate_definition(
            calibration_authority=cls.failed_authority
        ).candidate_id
        cls.selection = json.loads(
            (
                OUTPUT_ROOT
                / "target_family_selection"
                / "target_family_selection_v2.json"
            ).read_text(encoding="utf-8")
        )

    def test_family_selection_structured_evidence(self) -> None:
        self.assertEqual(self.selection["status"], "PASS")
        selected = next(
            row
            for row in self.selection["families"]
            if row["family"] == TARGET_DEGRADATION_FAMILY
        )
        for field in (
            "valid_case_count",
            "real_holdout_count",
            "gt_available_count",
            "baseline_error_headroom",
            "source_degradation_strength",
            "recoverable_structure_evidence",
            "text_structure_risk",
            "color_risk",
            "alpha_risk",
            "operator_applicability",
        ):
            self.assertIn(field, selected)
        self.assertTrue(selected["selection_rule_pass"])

    def test_unsupported_selection_reason_not_used_as_numeric_fact(self) -> None:
        self.assertFalse(self.selection["unsupported_reason_strings_used_as_numeric_fact"])
        for row in self.selection["families"]:
            if row["recoverable_structure_evidence"]["status"] == "NEED_PROOF":
                self.assertFalse(row["selection_rule_pass"])

    def test_raw_proposal_source_bound(self) -> None:
        for row in self.calibration["formal_rows"]:
            source = Path(row["asset_directory"]) / "source.jpg"
            self.assertEqual(row["raw_record"]["proposal_source_binding"], _sha256(source))
            self.assertGreater(row["evidence_pixel_fraction"], 0.0)

    def test_operator_is_non_generative(self) -> None:
        for row in self.calibration["formal_rows"]:
            self.assertFalse(row["raw_record"]["generative"])
            self.assertFalse(row["raw_record"]["sharpening_operator"])
            self.assertEqual(row["raw_record"]["operator_type"], OPERATOR_TYPE)

    def test_operator_deterministic(self) -> None:
        evidence = json.loads(
            (OUTPUT_ROOT / "validation" / "controlled_determinism.json").read_text(
                encoding="utf-8"
            )
        )

    @classmethod
    def _real_artifact_validator_results(cls) -> tuple[dict, dict]:
        cached = getattr(cls, "_cached_path_validator_results", None)
        if cached is None:
            absolute_root = OUTPUT_ROOT.resolve()
            relative_root = Path(
                os.path.relpath(absolute_root, Path.cwd().resolve())
            )
            cached = (
                validate_artifact(absolute_root),
                validate_artifact(relative_root),
            )
            cls._cached_path_validator_results = cached
        return cached
        self.assertEqual(evidence["status"], "PASS")
        self.assertTrue(evidence["byte_identical"])
        self.assertTrue(evidence["pixel_sha256_identical"])

    def test_controlled_mild_degradation_recovery_gate(self) -> None:
        mild = [row for row in self.calibration["formal_rows"] if row["level"] == "MILD"]
        self.assertEqual(self.summary["controlled_mild_recovery_direction"], "NOT_POSITIVE")
        self.assertTrue(
            any(
                row["post_bounding_recovery_direction"] != "POSITIVE_RECOVERY_DIRECTION"
                for row in mild
            )
        )
        self.assertEqual(self.summary["e1_cases_replayed"], "0/16")

    def test_controlled_moderate_degradation_recovery(self) -> None:
        moderate = [
            row for row in self.calibration["formal_rows"] if row["level"] == "MODERATE"
        ]
        self.assertTrue(moderate)
        self.assertTrue(
            all(
                row["post_bounding_recovery_direction"] == "POSITIVE_RECOVERY_DIRECTION"
                for row in moderate
            )
        )
        self.assertEqual(self.summary["controlled_moderate_recovery_direction"], "POSITIVE")

    def test_no_sharpness_only_false_gain(self) -> None:
        for row in self.calibration["formal_rows"]:
            measured_positive = (
                row["candidate_to_gt_error"] < row["baseline_to_gt_error"]
            )
            declared_positive = (
                row["post_bounding_recovery_direction"]
                == "POSITIVE_RECOVERY_DIRECTION"
            )
            self.assertEqual(declared_positive, measured_positive)
        self.assertNotIn("sharpness", self.calibration["selection_rule"].lower())

    def test_raw_gain_vs_post_bounding_gain_recorded(self) -> None:
        for row in self.calibration["formal_rows"]:
            self.assertIn("raw_proposal_to_gt_error", row)
            self.assertIn("pre_bounding_to_gt_error", row)
            self.assertIn("candidate_to_gt_error", row)
        self.assertEqual(self.summary["gain_loss_stage"], "SOURCE_OPERATOR")

    def test_residual_budget_enforced(self) -> None:
        self.assertTrue(
            all(
                row["residual_max_abs_after"] <= SAFE_PROFILE.residual_absolute_budget
                for row in self.calibration["formal_rows"]
            )
        )

    def test_nonfinite_operator_input_fails_closed(self) -> None:
        luma = np.full((8, 8), 128.0, dtype=np.float32)
        luma[0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "NONFINITE"):
            quantization_aware_luma_restore(
                luma,
                np.ones(64, dtype=np.float32),
                soft_threshold_ratio=0.03,
                source_luma_delta_budget=1.0,
            )

    def test_hf_budget_enforced(self) -> None:
        for row in self.calibration["formal_rows"]:
            bounded = row["bounded_record"]
            self.assertLessEqual(bounded["candidate_hf_energy"], bounded["hf_budget"] + 1e-7)

    def test_overshoot_enforced(self) -> None:
        self.assertTrue(
            all(
                row["bounded_record"]["overshoot_budget"] == 0.0
                for row in self.calibration["formal_rows"]
            )
        )

    def test_halo_ringing_enforced(self) -> None:
        for row in self.calibration["formal_rows"]:
            raw = row["final_safety"]["raw_detection"]
            self.assertFalse(raw["halo_or_ringing"])
            self.assertFalse(raw["white_edge"])
            self.assertFalse(raw["black_edge"])

    def _protection_fixture(self) -> tuple[np.ndarray, np.ndarray]:
        rgb = np.full((96, 128, 3), 220, dtype=np.uint8)
        cv2.putText(
            rgb,
            "HDDE",
            (8, 54),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.1,
            (15, 15, 15),
            2,
            cv2.LINE_AA,
        )
        cv2.rectangle(rgb, (82, 12), (118, 70), (20, 20, 20), 2)
        protection, _record = build_protection_scale(rgb)
        return rgb, protection

    def test_text_protected(self) -> None:
        _rgb, protection = self._protection_fixture()
        self.assertEqual(float(np.min(protection[18:60, 6:78])), 0.0)

    def test_logo_like_structure_protected(self) -> None:
        _rgb, protection = self._protection_fixture()
        self.assertEqual(float(np.min(protection[10:74, 80:121])), 0.0)

    def test_hard_edge_protected(self) -> None:
        _rgb, protection = self._protection_fixture()
        self.assertTrue(np.any(protection == 0.0))

    def test_rgb_bgr_order_explicit(self) -> None:
        for row in self.calibration["formal_rows"]:
            raw = row["raw_record"]
            self.assertEqual(raw["input_color_order"], "RGB")
            self.assertEqual(raw["working_color_space"], "YCbCr_LUMA")

    def test_color_lock(self) -> None:
        self.assertTrue(
            all(row["rgb_channel_difference_identity"] for row in self.calibration["formal_rows"])
        )
        self.assertTrue(
            all(
                row["bounded_record"]["color_delta"][
                    "maximum_chroma_difference_drift"
                ]
                == 0.0
                for row in self.calibration["formal_rows"]
            )
        )

    def test_no_saturation_inflation(self) -> None:
        for row in self.calibration["formal_rows"]:
            delta = row["bounded_record"]["color_delta"]["saturation_mean_delta"]
            self.assertLessEqual(abs(delta), 0.01)

    def test_alpha_identity_and_semitransparent_edge_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.jpg"
            Image.fromarray(_probe_rgb(), "RGB").save(
                source, format="JPEG", quality=76, subsampling=2
            )
            with Image.open(source) as opened:
                source_rgb = opened.convert("RGB")
            resized = np.asarray(source_rgb.resize((256, 192), Image.Resampling.LANCZOS))
            alpha = np.tile(np.linspace(0, 255, 256, dtype=np.uint8), (192, 1))
            baseline_rgba = np.dstack((resized, alpha))
            baseline = root / "baseline.png"
            output = root / "candidate.png"
            Image.fromarray(baseline_rgba, "RGBA").save(baseline)
            record = restore_source_domain_candidate(source, baseline, output)
            with Image.open(output) as opened:
                result = np.asarray(opened.convert("RGBA"))
        self.assertTrue(np.array_equal(result[..., 3], alpha))
        self.assertEqual(record["alpha_lock_status"], "BASELINE_BYTE_IDENTITY")
        self.assertFalse(record["candidate_execution_authorized"])

    def test_non_target_no_op_byte_equals_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            baseline = root / "baseline.png"
            output = root / "candidate.png"
            Image.fromarray(_probe_rgb(), "RGB").save(source)
            Image.fromarray(_probe_rgb(256, 192), "RGB").save(baseline)
            record = restore_source_domain_candidate(source, baseline, output)
            self.assertEqual(record["restoration_activation"], NO_OP)
            self.assertEqual(_sha256(output), _sha256(baseline))

    def test_e4k_02_connected_without_parallel_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            baseline = root / "baseline.png"
            Image.fromarray(_probe_rgb(), "RGB").save(source)
            Image.fromarray(_probe_rgb(256, 192), "RGB").save(baseline)
            result = run_4k_candidate(
                source,
                root / "runs",
                definition=source_domain_candidate_definition(),
                executor=source_domain_restoration_candidate,
                baseline_path=baseline,
                execution_nonce="E4K04_V2_FRAMEWORK_UNIT",
            )
        self.assertEqual(result["candidate_class"], PRODUCT)
        self.assertEqual(result["framework_version"], "HDDE_4K_ENHANCEMENT_CANDIDATE_FRAMEWORK_V1")
        self.assertEqual(result["output_validation"]["status"], "PASS")
        self.assertFalse(result["model_download"])
        self.assertFalse(result["model_inference_run"])

    def test_e1_02_not_run_after_controlled_failure(self) -> None:
        self.assertEqual(self.summary["e1_02_connected"], "NOT_RUN_CONTROLLED_GATE_STOP")
        self.assertEqual(self.summary["e1_cases_replayed"], "0/16")
        self.assertFalse(any((OUTPUT_ROOT / "case_results").glob("E1C*.json")))

    def test_candidate_identity_binds_full_v2_contract(self) -> None:
        contract = source_domain_candidate_definition().identity_contract()
        self.assertEqual(contract["algorithm_id"], ALGORITHM_ID)
        self.assertEqual(contract["algorithm_version"], ALGORITHM_VERSION)
        self.assertEqual(contract["candidate_class"], PRODUCT)
        parameters = contract["canonical_parameters"]
        for field in (
            "target_degradation_family",
            "operator_type",
            "operator_parameters",
            "residual_contract",
            "high_frequency_budget",
            "overshoot_policy",
            "halo_policy",
            "protected_structure_policy",
            "color_policy",
            "alpha_policy",
            "backend",
            "precision",
            "candidate_execution_authorized",
        ):
            self.assertIn(field, parameters)
        self.assertFalse(parameters["candidate_execution_authorized"])

    def test_threshold_provenance_complete_and_uncalibrated_fails(self) -> None:
        provenance = build_v2_threshold_provenance()
        self.assertEqual(provenance["status"], "NEED_CALIBRATION")
        self.assertGreaterEqual(provenance["uncalibrated_threshold_count"], 1)
        failed = build_v2_threshold_provenance(
            calibration_authority=self.failed_authority
        )
        self.assertEqual(failed["status"], "NEED_CALIBRATION")
        self.assertFalse(failed["candidate_execution_authorized"])
        changed = build_v2_threshold_provenance(
            replace(SAFE_PROFILE_V2, dct_soft_threshold_ratio=0.04),
            calibration_authority=self.failed_authority,
        )
        self.assertEqual(changed["status"], "NEED_CALIBRATION")
        self.assertGreater(changed["uncalibrated_threshold_count"], 0)

    @staticmethod
    def _valid_calibration_result() -> dict:
        return {
            "status": "PASS",
            "parameter_grid": [0.03],
            "ratio_summaries": [
                {
                    "ratio": 0.03,
                    "all_post_bounding_positive": True,
                    "all_final_safety_pass": True,
                }
            ],
            "all_grid_rows": [
                {
                    "ratio": 0.03,
                    "post_bounding_recovery_direction": (
                        "POSITIVE_RECOVERY_DIRECTION"
                    ),
                    "final_safety": {"status": "PASS"},
                }
            ],
            "selected_ratio": 0.03,
            "formal_ratio": 0.03,
        }

    @staticmethod
    def _write_calibration_artifact(root: Path, calibration: dict) -> Path:
        path = root / "calibration.json"
        path.write_text(
            json.dumps(calibration, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    @classmethod
    def _valid_authorization_bundle(
        cls, root: Path
    ) -> tuple[Path, dict, dict, str]:
        path = cls._write_calibration_artifact(
            root, cls._valid_calibration_result()
        )
        authority = build_calibration_authority_binding(
            json.loads(path.read_text(encoding="utf-8")),
            calibration_artifact_sha256=_sha256(path),
        )
        provenance = build_v2_threshold_provenance(
            calibration_authority=authority
        )
        candidate_id = source_domain_candidate_definition(
            calibration_authority=authority
        ).candidate_id
        return path, authority, provenance, candidate_id

    @staticmethod
    def _forged_pass_provenance(authority: dict) -> dict:
        provenance = build_v2_threshold_provenance(
            calibration_authority=authority
        )
        provenance["status"] = "PASS"
        provenance["candidate_execution_authorized"] = True
        provenance["uncalibrated_threshold_count"] = 0
        provenance["failures"] = []
        for item in provenance["thresholds"]:
            item["status"] = "VALID"
        return provenance

    @staticmethod
    def _write_runtime_images(root: Path) -> tuple[Path, Path, Path]:
        source = root / "source.jpg"
        baseline = root / "baseline.png"
        output = root / "candidate.png"
        Image.fromarray(_probe_rgb(), "RGB").save(
            source, format="JPEG", quality=76, subsampling=2
        )
        with Image.open(source) as opened:
            opened.convert("RGB").resize(
                (256, 192), Image.Resampling.LANCZOS
            ).save(baseline)
        return source, baseline, output

    def test_calibration_fail_marks_threshold_need_calibration(self) -> None:
        self.assertEqual(self.failed_authority["binding_status"], "PASS")
        self.assertEqual(self.failed_authority["calibration_status"], "FAIL")
        self.assertFalse(self.failed_authority["candidate_execution_authorized"])
        provenance = build_v2_threshold_provenance(
            calibration_authority=self.failed_authority
        )
        self.assertEqual(provenance["status"], "NEED_CALIBRATION")

    def test_null_selected_ratio_blocks_execution(self) -> None:
        self.assertIsNone(self.failed_authority["selected_ratio"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.jpg"
            baseline = root / "baseline.png"
            output = root / "candidate.png"
            Image.fromarray(_probe_rgb(), "RGB").save(
                source, format="JPEG", quality=76, subsampling=2
            )
            Image.fromarray(_probe_rgb(256, 192), "RGB").save(baseline)
            record = restore_source_domain_candidate(
                source,
                baseline,
                output,
                calibration_authority=self.failed_authority,
                calibration_artifact_path=self.calibration_path,
                threshold_provenance=self.failed_provenance,
                candidate_id=self.failed_candidate_id,
            )
            byte_equal = _sha256(output) == _sha256(baseline)
        self.assertEqual(record["restoration_activation"], NO_OP)
        self.assertFalse(record["candidate_execution_authorized"])
        self.assertFalse(record["source_operator_executed"])
        self.assertEqual(
            record["runtime_calibration_authorization"]["status"], "FAIL"
        )
        self.assertTrue(byte_equal)

    def test_default_ratio_cannot_bypass_failed_calibration(self) -> None:
        provenance = build_v2_threshold_provenance(
            SAFE_PROFILE_V2,
            calibration_authority=self.failed_authority,
        )
        self.assertEqual(SAFE_PROFILE_V2.dct_soft_threshold_ratio, 0.03)
        self.assertEqual(provenance["status"], "NEED_CALIBRATION")
        self.assertFalse(provenance["candidate_execution_authorized"])

    def test_forged_derived_fields_cannot_mark_provenance_pass(self) -> None:
        authority = copy.deepcopy(self.failed_authority)
        authority["selected_ratio"] = 0.03
        authority["candidate_execution_authorized"] = True
        provenance = build_v2_threshold_provenance(
            SAFE_PROFILE_V2,
            calibration_authority=authority,
        )
        self.assertEqual(authority["calibration_status"], "FAIL")
        self.assertEqual(authority["qualified_ratios"], [])
        self.assertEqual(provenance["status"], "NEED_CALIBRATION")
        self.assertFalse(provenance["candidate_execution_authorized"])

    def test_invalid_provenance_forces_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.jpg"
            baseline = root / "baseline.png"
            output = root / "candidate.png"
            Image.fromarray(_probe_rgb(), "RGB").save(
                source, format="JPEG", quality=76, subsampling=2
            )
            with Image.open(source) as opened:
                opened.convert("RGB").resize(
                    (256, 192), Image.Resampling.LANCZOS
                ).save(baseline)
            record = restore_source_domain_candidate(source, baseline, output)
            byte_equal = _sha256(output) == _sha256(baseline)
        self.assertEqual(record["restoration_activation"], NO_OP)
        self.assertEqual(record["raw_proposal"], "NOT_ADMISSIBLE")
        self.assertTrue(byte_equal)

    def test_valid_calibration_allows_execution_control_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calibration_path, authority, provenance, candidate_id = (
                self._valid_authorization_bundle(root)
            )
            source, baseline, output = self._write_runtime_images(root)
            record = restore_source_domain_candidate(
                source,
                baseline,
                output,
                calibration_authority=authority,
                calibration_artifact_path=calibration_path,
                threshold_provenance=provenance,
                candidate_id=candidate_id,
            )
        self.assertTrue(authority["candidate_execution_authorized"])
        self.assertTrue(record["candidate_execution_authorized"])
        self.assertTrue(record["source_operator_executed"])
        self.assertEqual(
            record["runtime_calibration_authorization"]["status"], "PASS"
        )
        self.assertEqual(record["threshold_provenance"]["status"], "PASS")
        self.assertIsInstance(record["raw_proposal"], dict)

    def test_forged_authorization_bypass_blocked(self) -> None:
        authority = copy.deepcopy(self.failed_authority)
        authority["selected_ratio"] = 0.03
        authority["candidate_execution_authorized"] = True
        provenance = self._forged_pass_provenance(authority)
        candidate_id = source_domain_candidate_definition(
            calibration_authority=authority
        ).candidate_id
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, baseline, output = self._write_runtime_images(root)
            record = restore_source_domain_candidate(
                source,
                baseline,
                output,
                calibration_authority=authority,
                calibration_artifact_path=self.calibration_path,
                threshold_provenance=provenance,
                candidate_id=candidate_id,
            )
            byte_equal = _sha256(output) == _sha256(baseline)
        self.assertEqual(record["restoration_activation"], NO_OP)
        self.assertFalse(record["source_operator_executed"])
        self.assertFalse(record["candidate_execution_authorized"])
        self.assertTrue(byte_equal)
        self.assertIn(
            "CALIBRATION_AUTHORITY_BINDING_MISMATCH",
            record["runtime_calibration_authorization"]["failures"],
        )

    def test_calibration_sha_mismatch_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calibration_path = self._write_calibration_artifact(
                root, self._valid_calibration_result()
            )
            calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
            authority = build_calibration_authority_binding(
                calibration,
                calibration_artifact_sha256="b" * 64,
            )
            provenance = build_v2_threshold_provenance(
                calibration_authority=authority
            )
            candidate_id = source_domain_candidate_definition(
                calibration_authority=authority
            ).candidate_id
            gate = validate_runtime_calibration_authorization(
                calibration_artifact_path=calibration_path,
                calibration_authority=authority,
                threshold_provenance=provenance,
                candidate_id=candidate_id,
            )
        self.assertEqual(gate["status"], "FAIL")
        self.assertFalse(gate["candidate_execution_authorized"])
        self.assertIn("CALIBRATION_SHA_MISMATCH", gate["failures"])

    def test_calibration_target_sha_mismatch_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, authority, provenance, candidate_id = (
                self._valid_authorization_bundle(root)
            )
            original_path_string = str(path)
            changed = self._valid_calibration_result()
            changed["formal_ratio"] = 0.04
            path.write_text(
                json.dumps(changed, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            gate = validate_runtime_calibration_authorization(
                calibration_artifact_path=path,
                calibration_authority=authority,
                threshold_provenance=provenance,
                candidate_id=candidate_id,
            )
        self.assertEqual(str(path), original_path_string)
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("CALIBRATION_SHA_MISMATCH", gate["failures"])

    def test_selected_ratio_not_in_grid_blocked(self) -> None:
        calibration = self._valid_calibration_result()
        calibration["parameter_grid"] = [0.04]
        calibration["ratio_summaries"][0]["ratio"] = 0.04
        calibration["all_grid_rows"][0]["ratio"] = 0.04
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self._write_calibration_artifact(root, calibration)
            authority = build_calibration_authority_binding(
                calibration, calibration_artifact_sha256=_sha256(path)
            )
            authority["candidate_execution_authorized"] = True
            provenance = self._forged_pass_provenance(authority)
            candidate_id = source_domain_candidate_definition(
                calibration_authority=authority
            ).candidate_id
            gate = validate_runtime_calibration_authorization(
                calibration_artifact_path=path,
                calibration_authority=authority,
                threshold_provenance=provenance,
                candidate_id=candidate_id,
            )
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("SELECTED_RATIO_NOT_IN_GRID", gate["failures"])

    def test_unqualified_selected_ratio_blocked(self) -> None:
        calibration = self._valid_calibration_result()
        calibration["ratio_summaries"][0]["all_post_bounding_positive"] = False
        calibration["all_grid_rows"][0][
            "post_bounding_recovery_direction"
        ] = "NOT_POSITIVE"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self._write_calibration_artifact(root, calibration)
            authority = build_calibration_authority_binding(
                calibration, calibration_artifact_sha256=_sha256(path)
            )
            authority["candidate_execution_authorized"] = True
            provenance = self._forged_pass_provenance(authority)
            candidate_id = source_domain_candidate_definition(
                calibration_authority=authority
            ).candidate_id
            gate = validate_runtime_calibration_authorization(
                calibration_artifact_path=path,
                calibration_authority=authority,
                threshold_provenance=provenance,
                candidate_id=candidate_id,
            )
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("SELECTED_RATIO_QUALIFICATION_NOT_PASS", gate["failures"])

    def test_selected_ratio_not_in_qualified_ratios_blocked(self) -> None:
        calibration = self._valid_calibration_result()
        calibration["ratio_summaries"][0]["all_final_safety_pass"] = False
        calibration["all_grid_rows"][0]["final_safety"]["status"] = "FAIL"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self._write_calibration_artifact(root, calibration)
            authority = build_calibration_authority_binding(
                calibration, calibration_artifact_sha256=_sha256(path)
            )
            authority["candidate_execution_authorized"] = True
            provenance = self._forged_pass_provenance(authority)
            candidate_id = source_domain_candidate_definition(
                calibration_authority=authority
            ).candidate_id
            gate = validate_runtime_calibration_authorization(
                calibration_artifact_path=path,
                calibration_authority=authority,
                threshold_provenance=provenance,
                candidate_id=candidate_id,
            )
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("SELECTED_RATIO_NOT_IN_QUALIFIED_RATIOS", gate["failures"])

    def test_calibration_status_fail_with_forged_pass_provenance_blocked(self) -> None:
        authority = copy.deepcopy(self.failed_authority)
        authority["selected_ratio"] = 0.03
        authority["candidate_execution_authorized"] = True
        provenance = self._forged_pass_provenance(authority)
        gate = validate_runtime_calibration_authorization(
            calibration_artifact_path=self.calibration_path,
            calibration_authority=authority,
            threshold_provenance=provenance,
            candidate_id=source_domain_candidate_definition(
                calibration_authority=authority
            ).candidate_id,
        )
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("CALIBRATION_STATUS_NOT_PASS", gate["failures"])

    def _assert_semantic_tamper_rejected(
        self, mutate: object, expected_failure: str
    ) -> None:
        calibration = copy.deepcopy(self.calibration)
        mutate(calibration)  # type: ignore[operator]
        recomputed = recompute_calibration_semantics(OUTPUT_ROOT, calibration)
        self.assertEqual(recomputed["status"], "FAIL")
        self.assertTrue(
            any(expected_failure in failure for failure in recomputed["failures"]),
            recomputed["failures"],
        )

    def test_tamper_stored_baseline_mae_rejected(self) -> None:
        self._assert_semantic_tamper_rejected(
            lambda value: value["all_grid_rows"][0].__setitem__(
                "baseline_to_gt_error",
                value["all_grid_rows"][0]["baseline_to_gt_error"] + 1.0,
            ),
            "METRIC_MISMATCH:baseline_to_gt_error",
        )

    def test_tamper_stored_candidate_mae_rejected(self) -> None:
        self._assert_semantic_tamper_rejected(
            lambda value: value["all_grid_rows"][0].__setitem__(
                "candidate_to_gt_error",
                value["all_grid_rows"][0]["candidate_to_gt_error"] + 1.0,
            ),
            "METRIC_MISMATCH:candidate_to_gt_error",
        )

    def test_tamper_recovery_direction_rejected(self) -> None:
        self._assert_semantic_tamper_rejected(
            lambda value: value["all_grid_rows"][0].__setitem__(
                "post_bounding_recovery_direction", "POSITIVE_RECOVERY_DIRECTION"
            ),
            "DIRECTION_MISMATCH",
        )

    def test_tamper_ratio_qualification_rejected(self) -> None:
        self._assert_semantic_tamper_rejected(
            lambda value: value["ratio_summaries"][0].__setitem__(
                "all_post_bounding_positive", True
            ),
            "RATIO_QUALIFICATION",
        )

    def test_tamper_selected_ratio_rejected(self) -> None:
        self._assert_semantic_tamper_rejected(
            lambda value: value.__setitem__("selected_ratio", 0.03),
            "SELECTED_RATIO_MISMATCH",
        )

    def test_tamper_calibration_status_rejected(self) -> None:
        self._assert_semantic_tamper_rejected(
            lambda value: value.__setitem__("status", "PASS"),
            "CALIBRATION_STATUS_MISMATCH",
        )

    def test_step0_test_count_single_source(self) -> None:
        record = json.loads(
            (OUTPUT_ROOT / "validation" / "step0_test_execution.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(self.summary["step0_tests_total"], record["tests_total"])
        self.assertEqual(self.summary["step0_tests_passed"], record["tests_passed"])
        self.assertEqual(self.summary["step0_tests_failed"], record["tests_failed"])
        self.assertNotIn("PASS_34_TESTS", json.dumps(self.summary))

    def test_nonfinite_formal_threshold_fails_closed_with_json_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.jpg"
            baseline = root / "baseline.png"
            output = root / "candidate.png"
            record_path = root / "record.json"
            Image.fromarray(_probe_rgb(), "RGB").save(
                source, format="JPEG", quality=76, subsampling=2
            )
            with Image.open(source) as opened:
                opened.convert("RGB").resize(
                    (256, 192), Image.Resampling.LANCZOS
                ).save(baseline)
            record = restore_source_domain_candidate(
                source,
                baseline,
                output,
                record_path=record_path,
                profile=replace(
                    SAFE_PROFILE_V2, dct_soft_threshold_ratio=float("nan")
                ),
            )
            loaded = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(record["restoration_activation"], NO_OP)
        self.assertIn(
            "RUNTIME_CALIBRATION_AUTHORIZATION_FAILED", record["no_op_reason"]
        )
        self.assertEqual(loaded["threshold_provenance"]["status"], "NEED_CALIBRATION")

    def test_artifact_integrity_and_protected_scope(self) -> None:
        validation, _ = self._real_artifact_validator_results()
        self.assertEqual(validation["status"], "PASS")
        self.assertTrue(validation["controlled_stop"])
        self.assertEqual(self.summary["stop_v2_operator"], "YES")
        self.assertEqual(
            self.summary["runtime_calibration_authorization_gate"], "PASS"
        )
        self.assertFalse(self.summary["current_source_operator_executed"])
        for field in (
            "formal_4k_pipeline_changed",
            "api_4k_changed",
            "e1_01_changed",
            "e1_02_changed",
            "e4k_02_frozen_artifact_changed",
            "product_version_changed",
        ):
            self.assertFalse(self.summary[field], field)

    def test_absolute_artifact_root_validates(self) -> None:
        absolute, _ = self._real_artifact_validator_results()
        self.assertEqual(absolute["status"], "PASS", absolute["failures"])
        self.assertEqual(absolute["calibration_path_binding"]["status"], "PASS")

    def test_relative_artifact_root_validates(self) -> None:
        _, relative = self._real_artifact_validator_results()
        self.assertEqual(relative["status"], "PASS", relative["failures"])
        self.assertEqual(relative["calibration_path_binding"]["status"], "PASS")

    def test_absolute_and_relative_results_identical(self) -> None:
        absolute, relative = self._real_artifact_validator_results()
        self.assertEqual(absolute, relative)

    def test_dot_segment_path_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifact"
            target = root / "controlled_calibration" / "calibration.json"
            target.parent.mkdir(parents=True)
            target.write_text("{}\n", encoding="utf-8")
            binding = validate_calibration_artifact_path_binding(
                artifact_root=root,
                recorded_calibration_path=(
                    "controlled_calibration\\..\\controlled_calibration"
                    "\\.\\calibration.json"
                ),
                expected_calibration_path=target,
            )
        self.assertEqual(binding["status"], "PASS", binding["failures"])
        self.assertEqual(
            binding["resolved_calibration_artifact_path"], str(target.resolve())
        )

    def test_calibration_path_traversal_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "artifact"
            root.mkdir()
            target = root / "controlled_calibration" / "calibration.json"
            target.parent.mkdir()
            target.write_text("{}\n", encoding="utf-8")
            external = parent / "external.json"
            external.write_text("{}\n", encoding="utf-8")
            binding = validate_calibration_artifact_path_binding(
                artifact_root=root,
                recorded_calibration_path="..\\external.json",
                expected_calibration_path=target,
            )
        self.assertEqual(binding["status"], "FAIL")
        self.assertIn(
            "CALIBRATION_PATH_OUTSIDE_ARTIFACT_ROOT", binding["failures"]
        )

    def test_calibration_target_missing_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifact"
            root.mkdir()
            missing = root / "controlled_calibration" / "missing.json"
            binding = validate_calibration_artifact_path_binding(
                artifact_root=root,
                recorded_calibration_path="controlled_calibration\\missing.json",
                expected_calibration_path=missing,
            )
        self.assertEqual(binding["status"], "FAIL")
        self.assertIn("CALIBRATION_PATH_TARGET_MISSING", binding["failures"])

    def test_calibration_different_target_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifact"
            expected = root / "controlled_calibration" / "calibration.json"
            different = root / "validation" / "calibration.json"
            expected.parent.mkdir(parents=True)
            different.parent.mkdir(parents=True)
            expected.write_text("{}\n", encoding="utf-8")
            different.write_text("{}\n", encoding="utf-8")
            binding = validate_calibration_artifact_path_binding(
                artifact_root=root,
                recorded_calibration_path="validation\\calibration.json",
                expected_calibration_path=expected,
            )
        self.assertEqual(binding["status"], "FAIL")
        self.assertIn("CALIBRATION_PATH_TARGET_MISMATCH", binding["failures"])

    def test_path_string_difference_does_not_change_authorization_semantics(self) -> None:
        stored = json.loads(
            (
                OUTPUT_ROOT
                / "validation"
                / "runtime_calibration_authorization.json"
            ).read_text(encoding="utf-8")
        )
        equivalent = copy.deepcopy(stored)
        equivalent["calibration_artifact_path"] = (
            "controlled_calibration\\.\\controlled_calibration.json"
        )
        self.assertEqual(
            runtime_authorization_semantic_projection(stored),
            runtime_authorization_semantic_projection(equivalent),
        )


if __name__ == "__main__":
    unittest.main()
