from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from tools.experiments import e1_02_quality_delivery_gate as gate
from tools.experiments.e1_02_quality_delivery_gate import (
    CONTROL_NEGATIVE,
    CONTROL_ORACLE,
    CONTROL_ZERO,
    E1_01_MANIFEST,
    NO_PROCESSING_NEEDED_BASELINE_ARTIFACT,
    NO_PROCESSING_NEEDED_CANDIDATE_POLICY,
    NO_PROCESSING_NEEDED_FALLBACK,
    PRODUCT,
    QUALITY_GAIN_NOT_PROVEN,
    QUALITY_GAIN_PROVEN,
    QUALITY_GAIN_REJECTED,
    _candidate_spec,
    _analysis_bgr,
    _geometry_measurement,
    _gt_improvement,
    _eligibility,
    _save_control_candidate,
    _text_structure_facts,
    array_review_context,
    build_human_review_evidence,
    evaluate_arrays,
    evaluate_case,
)
from tools.experiments.e1_01_real_information_baseline import sha256_file


def _fixture_rgba(width: int = 192, height: int = 128) -> np.ndarray:
    canvas = np.full((height, width, 3), 118, dtype=np.uint8)
    cv2.rectangle(canvas, (12, 14), (178, 112), (28, 220, 238), 3)
    cv2.line(canvas, (18, 102), (174, 24), (245, 35, 35), 2)
    cv2.putText(canvas, "HDDE 4K", (25, 67), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
    for x in range(20, 176, 12):
        cv2.line(canvas, (x, 82), (x, 94), (30, 30, 30), 1)
    return np.dstack((cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB), np.full((height, width), 255, dtype=np.uint8)))


def _transformed(base: np.ndarray, control: str) -> np.ndarray:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "source.png"
        output = root / "output.png"
        Image.fromarray(base, "RGBA").save(source)
        _save_control_candidate(source, output, control)
        with Image.open(output) as opened:
            opened.load()
            return np.asarray(opened.convert("RGBA"), dtype=np.uint8)


def _gt_positive_fixture() -> tuple[np.ndarray, np.ndarray]:
    gt = _fixture_rgba(384, 256)
    baseline_rgb = cv2.GaussianBlur(gt[..., :3], (0, 0), 2.6)
    return np.dstack((baseline_rgb, gt[..., 3])), gt


def _severe_gt_positive_fixture() -> tuple[np.ndarray, np.ndarray]:
    gt = _fixture_rgba(384, 256)
    small = cv2.resize(gt[..., :3], (24, 16), interpolation=cv2.INTER_AREA)
    baseline_rgb = cv2.resize(small, (384, 256), interpolation=cv2.INTER_LINEAR)
    return np.dstack((baseline_rgb, gt[..., 3])), gt


def _text_fixture_bgr(width: int = 320, height: int = 128) -> np.ndarray:
    image = np.full((height, width, 3), 245, dtype=np.uint8)
    cv2.putText(image, "HDDE 4K", (18, 78), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (20, 20, 20), 4, cv2.LINE_8)
    cv2.rectangle(image, (15, 15), (304, 108), (25, 25, 25), 2)
    return image


def _geometry_fixture() -> np.ndarray:
    image = _fixture_rgba(384, 256)
    rng = np.random.default_rng(20260821)
    texture = rng.integers(-12, 13, image[..., :3].shape, dtype=np.int16)
    image[..., :3] = np.clip(image[..., :3].astype(np.int16) + texture, 0, 255).astype(np.uint8)
    return image


def _all_pass_mandatory_aggregation() -> dict[str, object]:
    return gate.aggregate_mandatory_gates({name: "PASS" for name in gate.MANDATORY_GATE_NAMES})


def _authorized_product_pass_record(case_id: str = "PRODUCT_PASS_CONTRACT") -> dict[str, object]:
    aggregation = _all_pass_mandatory_aggregation()
    authority = gate.authorize_product_delivery(
        quality_gain_status=QUALITY_GAIN_PROVEN,
        hard_safety_status="PASS",
        mandatory_gate_aggregation=aggregation,
        human_review_required=False,
        review_product_admissible=False,
        test_vector_only=False,
    )
    return {
        "case_id": case_id,
        "candidate_class": PRODUCT,
        "delivery_status": authority["delivery_status"],
        "quality_gain_status": QUALITY_GAIN_PROVEN,
        "hard_safety_gate": {"status": "PASS"},
        "mandatory_gate_complete": True,
        "human_review_control_fixture_only": False,
        "human_review_required": False,
        "human_review_product_admissible": False,
        "test_vector_only": False,
        "delivery_authority": authority,
    }


class E102QualityDeliveryGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = _fixture_rgba()

    def test_no_processing_needed_policy_is_explicit_bypass(self) -> None:
        self.assertEqual(NO_PROCESSING_NEEDED_CANDIDATE_POLICY, "BYPASS")
        self.assertEqual(NO_PROCESSING_NEEDED_BASELINE_ARTIFACT, "NONE")
        self.assertEqual(NO_PROCESSING_NEEDED_FALLBACK, "NOT_APPLICABLE")

    def test_zero_gain_control_never_proves_gain(self) -> None:
        result = evaluate_arrays(self.baseline, self.baseline.copy(), candidate_class=CONTROL_ZERO)
        self.assertEqual(result["hard_safety_gate"]["status"], "PASS")
        self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_NOT_PROVEN)
        self.assertEqual(result["delivery_status"], "REVIEW")

    def test_blur_negative_is_rejected(self) -> None:
        candidate = _transformed(self.baseline, "NEGATIVE_BLUR")
        result = evaluate_arrays(
            self.baseline,
            candidate,
            candidate_class=CONTROL_NEGATIVE,
            roi_types=("CHINESE_TEXT",),
        )
        self.assertTrue(result["hard_safety_gate"]["raw_detection"]["blur"])
        self.assertEqual(result["text_fidelity"], "TEXT_DEGRADED")
        self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_REJECTED)
        self.assertEqual(result["delivery_status"], "FAIL")

    def test_oversharpen_negative_is_rejected(self) -> None:
        candidate = _transformed(self.baseline, "NEGATIVE_OVERSHARPEN")
        result = evaluate_arrays(self.baseline, candidate, candidate_class=CONTROL_NEGATIVE)
        self.assertTrue(result["hard_safety_gate"]["raw_detection"]["oversharpen"])
        self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_REJECTED)

    def test_halo_or_ringing_negative_is_rejected(self) -> None:
        candidate = _transformed(self.baseline, "NEGATIVE_HALO_OR_RINGING")
        result = evaluate_arrays(self.baseline, candidate, candidate_class=CONTROL_NEGATIVE)
        self.assertTrue(result["hard_safety_gate"]["raw_detection"]["halo_or_ringing"])
        self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_REJECTED)

    def test_color_shift_negative_is_rejected(self) -> None:
        candidate = _transformed(self.baseline, "NEGATIVE_COLOR_SHIFT")
        result = evaluate_arrays(self.baseline, candidate, candidate_class=CONTROL_NEGATIVE)
        self.assertTrue(result["hard_safety_gate"]["raw_detection"]["color_shift"])
        self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_REJECTED)

    def test_oracle_positive_is_detected_but_remains_control(self) -> None:
        gt = self.baseline
        blurred = cv2.GaussianBlur(gt[..., :3], (0, 0), 2.6)
        baseline = np.dstack((blurred, gt[..., 3]))
        result = evaluate_arrays(
            baseline,
            gt.copy(),
            gt_rgba=gt,
            candidate_class=CONTROL_ORACLE,
        )
        self.assertTrue(result["gt_evidence"]["positive_direction_supported"])
        self.assertEqual(result["hard_safety_gate"]["status"], "PASS")
        self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_PROVEN)
        self.assertEqual(result["delivery_status"], "PASS")

    def test_product_positive_requires_gt_safety_and_completed_human_review(self) -> None:
        gt = self.baseline
        blurred = cv2.GaussianBlur(gt[..., :3], (0, 0), 2.6)
        baseline = np.dstack((blurred, gt[..., 3]))
        without_review = evaluate_arrays(baseline, gt.copy(), gt_rgba=gt, candidate_class=PRODUCT)
        context = array_review_context("PRODUCT_POSITIVE", gt, baseline, gt.copy(), gt)
        evidence = build_human_review_evidence(context, "BETTER")
        with_review = evaluate_arrays(
            baseline,
            gt.copy(),
            gt_rgba=gt,
            candidate_class=PRODUCT,
            human_review_context=context,
            human_review_evidence=evidence,
        )
        self.assertEqual(without_review["quality_gain_status"], QUALITY_GAIN_NOT_PROVEN)
        self.assertEqual(without_review["delivery_status"], "REVIEW")
        self.assertEqual(with_review["hard_safety_gate"]["status"], "PASS")
        self.assertTrue(with_review["human_review_binding_valid"])
        self.assertTrue(with_review["human_review_control_fixture_only"])
        self.assertFalse(with_review["human_review_product_admissible"])
        self.assertEqual(with_review["quality_gain_status"], QUALITY_GAIN_NOT_PROVEN)
        self.assertEqual(with_review["delivery_status"], "REVIEW")
        self.assertTrue(with_review["human_review_required"])
        self.assertTrue(with_review["human_review_completed"])

    def test_control_fixture_product_is_bound_but_not_admissible(self) -> None:
        baseline, gt = _gt_positive_fixture()
        context = array_review_context("CONTROL_FIXTURE_PRODUCT", gt, baseline, gt.copy(), gt)
        evidence = build_human_review_evidence(context, "BETTER")
        result = evaluate_arrays(
            baseline,
            gt.copy(),
            gt_rgba=gt,
            candidate_class=PRODUCT,
            human_review_context=context,
            human_review_evidence=evidence,
        )
        self.assertTrue(result["human_review_binding_valid"])
        self.assertTrue(result["human_review_control_fixture_only"])
        self.assertFalse(result["human_review_product_admissible"])
        self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_NOT_PROVEN)
        self.assertNotEqual(result["delivery_status"], "PASS")

    def test_mandatory_text_fail_blocks_product_delivery(self) -> None:
        statuses = {name: "PASS" for name in gate.MANDATORY_GATE_NAMES}
        statuses["TEXT_FIDELITY_GATE"] = "FAIL"
        aggregation = gate.aggregate_mandatory_gates(statuses)
        decision = gate.authorize_product_delivery(
            quality_gain_status=QUALITY_GAIN_PROVEN,
            hard_safety_status="PASS",
            mandatory_gate_aggregation=aggregation,
            human_review_required=False,
            review_product_admissible=False,
            test_vector_only=False,
        )
        self.assertFalse(aggregation["mandatory_gate_complete"])
        self.assertEqual(decision["delivery_status"], "FAIL")

    def test_mandatory_geometry_need_proof_blocks_product_delivery(self) -> None:
        statuses = {name: "PASS" for name in gate.MANDATORY_GATE_NAMES}
        statuses["GEOMETRY_SAFETY_GATE"] = "NEED_PROOF"
        aggregation = gate.aggregate_mandatory_gates(statuses)
        decision = gate.authorize_product_delivery(
            quality_gain_status=QUALITY_GAIN_PROVEN,
            hard_safety_status="PASS",
            mandatory_gate_aggregation=aggregation,
            human_review_required=False,
            review_product_admissible=False,
            test_vector_only=False,
        )
        self.assertFalse(aggregation["mandatory_gate_complete"])
        self.assertEqual(decision["delivery_status"], "REVIEW")

    def test_control_fixture_cannot_prove_gain_or_pass_delivery(self) -> None:
        baseline, gt = _gt_positive_fixture()
        context = array_review_context("CONTROL_CANNOT_AUTHORIZE", gt, baseline, gt.copy(), gt)
        result = evaluate_arrays(
            baseline,
            gt.copy(),
            gt_rgba=gt,
            candidate_class=PRODUCT,
            human_review_context=context,
            human_review_evidence=build_human_review_evidence(context, "BETTER"),
            mandatory_gate_aggregation=_all_pass_mandatory_aggregation(),
        )
        self.assertTrue(result["human_review_binding_valid"])
        self.assertTrue(result["human_review_control_fixture_only"])
        self.assertFalse(result["human_review_product_admissible"])
        self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_NOT_PROVEN)
        self.assertEqual(result["delivery_status"], "REVIEW")
        self.assertEqual(gate.control_fixture_product_authorization_count([result]), 0)

    def test_mandatory_edge_fail_blocks_product_delivery(self) -> None:
        statuses = {name: "PASS" for name in gate.MANDATORY_GATE_NAMES}
        statuses["EDGE_ARTIFACT_GATE"] = "FAIL"
        decision = gate.authorize_product_delivery(
            quality_gain_status=QUALITY_GAIN_PROVEN,
            hard_safety_status="PASS",
            mandatory_gate_aggregation=gate.aggregate_mandatory_gates(statuses),
            human_review_required=False,
            review_product_admissible=False,
            test_vector_only=False,
        )
        self.assertEqual(decision["delivery_status"], "FAIL")
        self.assertFalse(decision["production_authorized"])

    def test_mandatory_color_fail_blocks_product_delivery(self) -> None:
        statuses = {name: "PASS" for name in gate.MANDATORY_GATE_NAMES}
        statuses["COLOR_SAFETY_GATE"] = "FAIL"
        decision = gate.authorize_product_delivery(
            quality_gain_status=QUALITY_GAIN_PROVEN,
            hard_safety_status="PASS",
            mandatory_gate_aggregation=gate.aggregate_mandatory_gates(statuses),
            human_review_required=False,
            review_product_admissible=False,
            test_vector_only=False,
        )
        self.assertEqual(decision["delivery_status"], "FAIL")

    def test_mandatory_gate_all_pass_allows_single_authority_pass(self) -> None:
        decision = gate.authorize_product_delivery(
            quality_gain_status=QUALITY_GAIN_PROVEN,
            hard_safety_status="PASS",
            mandatory_gate_aggregation=_all_pass_mandatory_aggregation(),
            human_review_required=False,
            review_product_admissible=False,
            test_vector_only=False,
        )
        self.assertEqual(decision["authority_version"], gate.PRODUCT_DELIVERY_AUTHORITY_VERSION)
        self.assertTrue(decision["mandatory_gate_complete"])
        self.assertEqual(decision["delivery_status"], "PASS")
        self.assertTrue(decision["production_authorized"])

    def test_mandatory_gate_missing_unknown_and_not_applicable_never_complete(self) -> None:
        missing = gate.aggregate_mandatory_gates({})
        unknown = gate.aggregate_mandatory_gates({
            **{name: "PASS" for name in gate.MANDATORY_GATE_NAMES},
            "TEXT_FIDELITY_GATE": "UNKNOWN",
        })
        not_applicable = gate.aggregate_mandatory_gates({
            **{name: "PASS" for name in gate.MANDATORY_GATE_NAMES},
            "TEXT_FIDELITY_GATE": "NOT_APPLICABLE",
        })
        self.assertFalse(missing["mandatory_gate_complete"])
        self.assertFalse(unknown["mandatory_gate_complete"])
        self.assertFalse(not_applicable["mandatory_gate_complete"])
        self.assertEqual(unknown["sub_gate_statuses"]["TEXT_FIDELITY_GATE"], "NEED_PROOF")
        self.assertEqual(not_applicable["blocking_gates"][0]["reason"], "NOT_APPLICABLE_NOT_ALLOWLISTED")

    def test_contract_test_only_production_review_vector_uses_same_authority_without_authorizing(self) -> None:
        baseline, gt = _gt_positive_fixture()
        context = array_review_context("CONTRACT_TEST_ONLY_PRODUCTION_REVIEW_VECTOR", gt, baseline, gt.copy(), gt)
        evidence = build_human_review_evidence(
            context,
            "BETTER",
            control_fixture_only=False,
            test_vector_only=True,
        )
        review = gate.validate_human_review_evidence(context, evidence)
        self.assertTrue(review["binding_valid"])
        self.assertFalse(review["product_admissible"])
        self.assertTrue(review["contract_test_product_admissible"])
        decision = gate.authorize_product_delivery(
            quality_gain_status=QUALITY_GAIN_PROVEN,
            hard_safety_status="PASS",
            mandatory_gate_aggregation=_all_pass_mandatory_aggregation(),
            human_review_required=True,
            review_product_admissible=review["contract_test_product_admissible"],
            test_vector_only=True,
        )
        self.assertEqual(decision["contract_test_expected_delivery"], "PASS")
        self.assertEqual(decision["delivery_status"], "REVIEW")
        self.assertFalse(decision["production_authorized"])
        normal_path = evaluate_arrays(
            baseline,
            gt.copy(),
            gt_rgba=gt,
            candidate_class=PRODUCT,
            human_review_context=context,
            human_review_evidence=evidence,
            mandatory_gate_aggregation=_all_pass_mandatory_aggregation(),
        )
        self.assertFalse(normal_path["human_review_product_admissible"])
        self.assertEqual(normal_path["quality_gain_status"], QUALITY_GAIN_NOT_PROVEN)
        self.assertEqual(normal_path["delivery_status"], "REVIEW")

    def test_human_review_cannot_override_hard_safety(self) -> None:
        decision = gate.authorize_product_delivery(
            quality_gain_status=QUALITY_GAIN_PROVEN,
            hard_safety_status="FAIL",
            mandatory_gate_aggregation=_all_pass_mandatory_aggregation(),
            human_review_required=True,
            review_product_admissible=True,
            test_vector_only=False,
        )
        self.assertEqual(decision["delivery_status"], "FAIL")

    def test_human_review_cannot_override_mandatory_fail_or_need_proof(self) -> None:
        for blocked_status, expected in (("FAIL", "FAIL"), ("NEED_PROOF", "REVIEW")):
            with self.subTest(blocked_status=blocked_status):
                statuses = {name: "PASS" for name in gate.MANDATORY_GATE_NAMES}
                statuses["TEXT_FIDELITY_GATE"] = blocked_status
                decision = gate.authorize_product_delivery(
                    quality_gain_status=QUALITY_GAIN_PROVEN,
                    hard_safety_status="PASS",
                    mandatory_gate_aggregation=gate.aggregate_mandatory_gates(statuses),
                    human_review_required=True,
                    review_product_admissible=True,
                    test_vector_only=False,
                )
                self.assertEqual(decision["delivery_status"], expected)

    def test_alpha_change_is_a_hard_safety_failure(self) -> None:
        candidate = self.baseline.copy()
        candidate[30:50, 40:70, 3] = 96
        result = evaluate_arrays(self.baseline, candidate, candidate_class=PRODUCT)
        self.assertEqual(result["hard_safety_gate"]["status"], "FAIL")
        self.assertIn("ALPHA_IDENTITY_FAILED", result["hard_safety_gate"]["failures"])
        self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_REJECTED)

    def test_material_without_gt_remains_need_proof(self) -> None:
        result = evaluate_arrays(
            self.baseline,
            self.baseline.copy(),
            candidate_class=PRODUCT,
            roi_types=("MATERIAL",),
        )
        self.assertEqual(result["material_texture"], "NEED_PROOF")
        self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_NOT_PROVEN)

    def test_missing_eligibility_binding_forbids_evaluation(self) -> None:
        case = {
            "input": {"sha256": "a" * 64},
            "safe_base": {"sha256": "b" * 64, "width": 192, "height": 128},
            "gt": None,
            "roi": [],
        }
        result = _eligibility(case, Path("missing.png"), {})
        self.assertEqual(result["status"], "INELIGIBLE")
        self.assertIn("CANDIDATE_OUTPUT_MISSING", result["failures"])
        self.assertGreater(len(result["missing_fields"]), 0)

    def test_incomplete_case_explicitly_forbids_quality_gain(self) -> None:
        manifest = json.loads(E1_01_MANIFEST.read_text(encoding="utf-8"))
        case = next(item for item in manifest["cases"] if item["case_id"] == "E1C002")
        baseline = Path(__file__).resolve().parents[2] / case["safe_base"]["path"]
        result = evaluate_case(E1_01_MANIFEST, "E1C002", baseline, {}, Path("unused"))
        self.assertEqual(result["evaluation_status"], "INELIGIBLE")
        self.assertEqual(result["quality_gain_proven"], "FORBIDDEN")
        self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_NOT_PROVEN)
        self.assertEqual(result["delivery_status"], "FAIL")
        self.assertFalse(result["mandatory_gate_complete"])

    def test_gt_positive_with_local_color_damage_hits_color_gate(self) -> None:
        baseline, gt = _severe_gt_positive_fixture()
        candidate = gt.copy()
        width = int(round(candidate.shape[1] * 0.04))
        candidate[:, :width, :3] = np.array([255, 0, 255], dtype=np.uint8)
        precondition = _gt_improvement(_analysis_bgr(baseline), _analysis_bgr(candidate), _analysis_bgr(gt))
        result = evaluate_arrays(baseline, candidate, gt_rgba=gt, candidate_class=PRODUCT)
        self.assertTrue(precondition["positive_direction_supported"])
        self.assertTrue(result["hard_safety_gate"]["raw_detection"]["local_color_shift"])
        self.assertIn("LOCAL_COLOR_SHIFT_DETECTED", result["hard_safety_gate"]["failures"])
        self.assertFalse(result["net_quality_gain_evaluated"])
        self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_REJECTED)
        self.assertEqual(result["delivery_status"], "FAIL")

    def test_gt_positive_with_high_frequency_damage_hits_high_frequency_gate(self) -> None:
        baseline, gt = _severe_gt_positive_fixture()
        candidate = gt.copy().astype(np.int16)
        checker = ((np.indices((256, 16)).sum(axis=0) % 2) * 2 - 1) * 44
        candidate[:, 150:166, :3] = np.clip(candidate[:, 150:166, :3] + checker[..., None], 0, 255)
        candidate = candidate.astype(np.uint8)
        precondition = _gt_improvement(_analysis_bgr(baseline), _analysis_bgr(candidate), _analysis_bgr(gt))
        result = evaluate_arrays(baseline, candidate, gt_rgba=gt, candidate_class=PRODUCT)
        self.assertTrue(precondition["positive_direction_supported"])
        self.assertTrue(result["hard_safety_gate"]["raw_detection"]["high_frequency_anomaly"])
        self.assertIn("HIGH_FREQUENCY_ARTIFACT_DETECTED", result["hard_safety_gate"]["failures"])
        self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_REJECTED)

    def test_geometry_shift_3px_has_exact_contract_result(self) -> None:
        baseline = _geometry_fixture()
        matrix = np.float32([[1.0, 0.0, 3.0], [0.0, 1.0, 0.0]])
        candidate = cv2.warpAffine(
            baseline,
            matrix,
            (baseline.shape[1], baseline.shape[0]),
            borderMode=cv2.BORDER_REFLECT,
        )
        geometry = _geometry_measurement(baseline, candidate)
        self.assertEqual(geometry["status"], "FAIL")
        self.assertEqual(geometry["decision"], "TRANSLATION_OR_GEOMETRIC_DRIFT_DETECTED")
        self.assertEqual(geometry["decision_reason"], geometry["decision"])
        self.assertEqual(geometry["estimated_transform"]["translation_method"], "PHASE_CORRELATION")
        self.assertAlmostEqual(geometry["estimated_transform"]["translation_magnitude_px"], 3.0, delta=1.0)
        self.assertGreaterEqual(geometry["confidence"], 0.85)
        self.assertIsInstance(geometry["residual_or_error"], float)

    def test_geometry_shift_8px_has_exact_contract_result(self) -> None:
        baseline = _geometry_fixture()
        matrix = np.float32([[1.0, 0.0, 8.0], [0.0, 1.0, 0.0]])
        candidate = cv2.warpAffine(
            baseline,
            matrix,
            (baseline.shape[1], baseline.shape[0]),
            borderMode=cv2.BORDER_REFLECT,
        )
        geometry = _geometry_measurement(baseline, candidate)
        self.assertEqual(geometry["status"], "FAIL")
        self.assertEqual(geometry["decision"], "TRANSLATION_OR_GEOMETRIC_DRIFT_DETECTED")
        self.assertEqual(geometry["decision_reason"], geometry["decision"])
        self.assertEqual(geometry["estimated_transform"]["translation_method"], "PHASE_CORRELATION")
        self.assertAlmostEqual(geometry["estimated_transform"]["translation_magnitude_px"], 8.0, delta=1.0)
        self.assertGreaterEqual(geometry["confidence"], 0.85)
        self.assertIsInstance(geometry["residual_or_error"], float)

    def test_geometry_crop_is_detected(self) -> None:
        baseline = _geometry_fixture()
        cropped = baseline[12:-12, 18:-18]
        candidate = cv2.resize(cropped, (baseline.shape[1], baseline.shape[0]), interpolation=cv2.INTER_LINEAR)
        geometry = _geometry_measurement(baseline, candidate)
        self.assertEqual(geometry["status"], "FAIL")
        self.assertEqual(geometry["decision"], "CROP_PADDING_OR_STRETCH_DETECTED")
        self.assertEqual(geometry["decision_reason"], geometry["decision"])
        self.assertIsNotNone(geometry["estimated_transform"])
        self.assertIsInstance(geometry["confidence"], float)
        self.assertIsInstance(geometry["residual_or_error"], float)

    def test_geometry_padding_is_detected(self) -> None:
        baseline = _geometry_fixture()
        inner = cv2.resize(baseline, (344, 224), interpolation=cv2.INTER_AREA)
        candidate = cv2.copyMakeBorder(inner, 16, 16, 20, 20, cv2.BORDER_CONSTANT, value=(127, 127, 127, 255))
        geometry = _geometry_measurement(baseline, candidate)
        self.assertEqual(geometry["status"], "FAIL")
        self.assertEqual(geometry["decision"], "CROP_PADDING_OR_STRETCH_DETECTED")
        self.assertEqual(geometry["decision_reason"], geometry["decision"])
        self.assertIsNotNone(geometry["estimated_transform"])
        self.assertIsInstance(geometry["confidence"], float)
        self.assertIsInstance(geometry["residual_or_error"], float)

    def test_geometry_stretch_is_detected(self) -> None:
        baseline = _geometry_fixture()
        matrix = np.float32([[0.75, 0.0, 48.0], [0.0, 1.0, 0.0]])
        candidate = cv2.warpAffine(baseline, matrix, (baseline.shape[1], baseline.shape[0]), borderMode=cv2.BORDER_REFLECT)
        geometry = _geometry_measurement(baseline, candidate)
        self.assertEqual(geometry["status"], "FAIL")
        self.assertEqual(geometry["decision"], "CROP_PADDING_OR_STRETCH_DETECTED")
        self.assertEqual(geometry["decision_reason"], geometry["decision"])
        self.assertIsNotNone(geometry["estimated_transform"])
        self.assertIsInstance(geometry["confidence"], float)
        self.assertIsInstance(geometry["residual_or_error"], float)

    def test_geometry_low_texture_is_never_default_pass(self) -> None:
        baseline = np.full((128, 192, 4), 128, dtype=np.uint8)
        candidate = baseline.copy()
        candidate[:, 3:] = candidate[:, :-3]
        candidate[0, 0, 0] = 129
        geometry = _geometry_measurement(baseline, candidate)
        self.assertEqual(geometry["status"], "REVIEW")
        self.assertEqual(geometry["decision"], "LOW_TEXTURE_GEOMETRY_NEED_PROOF")

    def test_replay_binding_rejects_invalid_replay_id(self) -> None:
        manifest = json.loads(E1_01_MANIFEST.read_text(encoding="utf-8"))
        case = next(item for item in manifest["cases"] if item["case_id"] == "E1C002")
        candidate = Path(__file__).resolve().parents[2] / case["safe_base"]["path"]
        spec = _candidate_spec(case, candidate, "REPLAY_INVALID", CONTROL_ZERO, "BASELINE_IDENTITY_CONTROL")
        spec["replay_identity"] = "0" * 64
        result = _eligibility(case, candidate, spec)
        self.assertEqual(result["status"], "INELIGIBLE")
        self.assertIn("INVALID_REPLAY_ID", result["failures"])

    def test_replay_binding_rejects_parameters_none(self) -> None:
        manifest = json.loads(E1_01_MANIFEST.read_text(encoding="utf-8"))
        case = next(item for item in manifest["cases"] if item["case_id"] == "E1C002")
        candidate = Path(__file__).resolve().parents[2] / case["safe_base"]["path"]
        spec = _candidate_spec(case, candidate, "PARAM_NONE", CONTROL_ZERO, "BASELINE_IDENTITY_CONTROL")
        spec["parameters"] = None
        result = _eligibility(case, candidate, spec)
        self.assertIn("PARAMETERS_NONE", result["failures"])
        self.assertEqual(result["replay_binding_gate"], "FAIL")

    def test_replay_binding_rejects_parameters_changed(self) -> None:
        manifest = json.loads(E1_01_MANIFEST.read_text(encoding="utf-8"))
        case = next(item for item in manifest["cases"] if item["case_id"] == "E1C002")
        candidate = Path(__file__).resolve().parents[2] / case["safe_base"]["path"]
        spec = _candidate_spec(case, candidate, "PARAM_CHANGED", CONTROL_ZERO, "BASELINE_IDENTITY_CONTROL")
        spec["parameters"] = {"gate_fixture": "CHANGED", "version": "V1"}
        result = _eligibility(case, candidate, spec)
        self.assertIn("PARAMETERS_CHANGED", result["failures"])
        self.assertIn("INVALID_REPLAY_ID", result["failures"])

    def test_replay_binding_rejects_candidate_sha_changed(self) -> None:
        manifest = json.loads(E1_01_MANIFEST.read_text(encoding="utf-8"))
        case = next(item for item in manifest["cases"] if item["case_id"] == "E1C002")
        baseline = Path(__file__).resolve().parents[2] / case["safe_base"]["path"]
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "candidate.png"
            with Image.open(baseline) as opened:
                opened.save(candidate)
            spec = _candidate_spec(case, candidate, "SHA_CHANGED", CONTROL_ZERO, "BASELINE_IDENTITY_CONTROL")
            with Image.open(candidate) as opened:
                changed = np.asarray(opened.convert("RGBA"), dtype=np.uint8).copy()
            changed[0, 0, 0] ^= 1
            Image.fromarray(changed, "RGBA").save(candidate)
            result = _eligibility(case, candidate, spec)
        self.assertIn("CANDIDATE_SHA_CHANGED", result["failures"])
        self.assertIn("INVALID_REPLAY_ID", result["failures"])

    def test_replay_binding_rejects_roi_binding_changed(self) -> None:
        manifest = json.loads(E1_01_MANIFEST.read_text(encoding="utf-8"))
        case = next(item for item in manifest["cases"] if item["case_id"] == "E1C002")
        candidate = Path(__file__).resolve().parents[2] / case["safe_base"]["path"]
        spec = _candidate_spec(case, candidate, "ROI_CHANGED", CONTROL_ZERO, "BASELINE_IDENTITY_CONTROL")
        spec["roi_set_sha256"] = "f" * 64
        result = _eligibility(case, candidate, spec)
        self.assertIn("ROI_BINDING_CHANGED", result["failures"])

    def test_unbound_better_cannot_authorize_product_gain(self) -> None:
        baseline, gt = _gt_positive_fixture()
        result = evaluate_arrays(
            baseline,
            gt.copy(),
            gt_rgba=gt,
            candidate_class=PRODUCT,
            human_review_context=array_review_context("UNBOUND", gt, baseline, gt.copy(), gt),
            human_review_evidence={"review_verdict": "BETTER"},
        )
        self.assertEqual(result["human_review_status"], "UNBOUND")
        self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_NOT_PROVEN)
        self.assertEqual(result["delivery_status"], "REVIEW")

    def test_valid_bound_better_is_consistent(self) -> None:
        baseline, gt = _gt_positive_fixture()
        context = array_review_context("BOUND_BETTER", gt, baseline, gt.copy(), gt)
        evidence = build_human_review_evidence(context, "BETTER")
        result = evaluate_arrays(baseline, gt.copy(), gt_rgba=gt, candidate_class=PRODUCT, human_review_context=context, human_review_evidence=evidence)
        self.assertEqual(result["human_review_status"], "BOUND")
        self.assertTrue(result["human_review_completed"])
        self.assertTrue(result["human_review_required"])
        self.assertTrue(result["human_review_control_fixture_only"])
        self.assertFalse(result["human_review_product_admissible"])
        self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_NOT_PROVEN)
        self.assertEqual(result["delivery_status"], "REVIEW")

    def test_valid_bound_worse_rejects_delivery(self) -> None:
        baseline, gt = _gt_positive_fixture()
        context = array_review_context("BOUND_WORSE", gt, baseline, gt.copy(), gt)
        evidence = build_human_review_evidence(context, "WORSE")
        result = evaluate_arrays(baseline, gt.copy(), gt_rgba=gt, candidate_class=PRODUCT, human_review_context=context, human_review_evidence=evidence)
        self.assertEqual(result["human_review_status"], "BOUND")
        self.assertTrue(result["human_review_control_fixture_only"])
        self.assertFalse(result["human_review_product_admissible"])
        self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_NOT_PROVEN)
        self.assertEqual(result["delivery_status"], "REVIEW")

    def test_review_asset_hash_mismatch_is_unbound(self) -> None:
        baseline, gt = _gt_positive_fixture()
        context = array_review_context("ASSET_MISMATCH", gt, baseline, gt.copy(), gt)
        evidence = build_human_review_evidence(context, "BETTER")
        changed_context = {**context, "comparison_asset_set": {"fixture": "0" * 64}}
        result = evaluate_arrays(baseline, gt.copy(), gt_rgba=gt, candidate_class=PRODUCT, human_review_context=changed_context, human_review_evidence=evidence)
        self.assertEqual(result["human_review_status"], "UNBOUND")
        self.assertIn("REVIEW_COMPARISON_ASSET_SET_MISMATCH", result["human_review_failures"])

    def test_review_case_mismatch_is_unbound(self) -> None:
        baseline, gt = _gt_positive_fixture()
        context = array_review_context("CASE_A", gt, baseline, gt.copy(), gt)
        evidence = build_human_review_evidence(context, "BETTER")
        changed_context = {**context, "case_id": "CASE_B"}
        result = evaluate_arrays(baseline, gt.copy(), gt_rgba=gt, candidate_class=PRODUCT, human_review_context=changed_context, human_review_evidence=evidence)
        self.assertEqual(result["human_review_status"], "UNBOUND")
        self.assertIn("REVIEW_CASE_ID_MISMATCH", result["human_review_failures"])

    def test_text_broken_stroke_is_detected(self) -> None:
        baseline = _text_fixture_bgr()
        candidate = baseline.copy()
        candidate[:, 80:86] = 245
        candidate[:, 150:156] = 245
        facts = _text_structure_facts(baseline, candidate)
        self.assertTrue(facts["raw_detection"]["broken_stroke"])
        self.assertEqual(facts["status"], "TEXT_DEGRADED")

    def test_text_sticking_is_detected(self) -> None:
        baseline = _text_fixture_bgr()
        dark = np.all(baseline < 100, axis=2).astype(np.uint8)
        stuck = cv2.dilate(dark, np.ones((9, 9), np.uint8), iterations=1)
        candidate = np.repeat(np.where(stuck[..., None] > 0, 20, 245), 3, axis=2).astype(np.uint8)
        facts = _text_structure_facts(baseline, candidate)
        self.assertTrue(facts["raw_detection"]["sticking"])

    def test_text_double_edge_is_detected(self) -> None:
        baseline = _text_fixture_bgr()
        candidate = baseline.copy()
        edges = cv2.Canny(cv2.cvtColor(baseline, cv2.COLOR_BGR2GRAY), 50, 150)
        shifted = np.roll(edges, 3, axis=1) > 0
        candidate[shifted] = (15, 15, 15)
        facts = _text_structure_facts(baseline, candidate)
        self.assertTrue(facts["raw_detection"]["double_edge"])

    def test_black_edge_is_detected(self) -> None:
        baseline = _text_fixture_bgr()
        candidate = baseline.copy()
        edges = cv2.Canny(cv2.cvtColor(baseline, cv2.COLOR_BGR2GRAY), 50, 150)
        ring = (cv2.dilate(edges, np.ones((5, 5), np.uint8)) > 0) & (edges == 0)
        candidate[ring] = 0
        result = evaluate_arrays(np.dstack((baseline[..., ::-1], np.full(baseline.shape[:2], 255, np.uint8))), np.dstack((candidate[..., ::-1], np.full(candidate.shape[:2], 255, np.uint8))), candidate_class=CONTROL_NEGATIVE)
        self.assertTrue(result["hard_safety_gate"]["raw_detection"]["black_edge"])
        self.assertIn("BLACK_EDGE_DETECTED", result["hard_safety_gate"]["failures"])

    def test_white_edge_is_detected(self) -> None:
        baseline = _text_fixture_bgr()
        candidate = baseline.copy()
        edges = cv2.Canny(cv2.cvtColor(baseline, cv2.COLOR_BGR2GRAY), 50, 150)
        ring = (cv2.dilate(edges, np.ones((5, 5), np.uint8)) > 0) & (edges == 0)
        candidate[ring] = 255
        result = evaluate_arrays(np.dstack((baseline[..., ::-1], np.full(baseline.shape[:2], 255, np.uint8))), np.dstack((candidate[..., ::-1], np.full(candidate.shape[:2], 255, np.uint8))), candidate_class=CONTROL_NEGATIVE)
        self.assertTrue(result["hard_safety_gate"]["raw_detection"]["white_edge"])
        self.assertIn("WHITE_EDGE_DETECTED", result["hard_safety_gate"]["failures"])

    def test_local_color_shift_is_detected(self) -> None:
        baseline = _fixture_rgba(384, 256)
        candidate = baseline.copy()
        candidate[:, :16, :3] = np.array([255, 0, 255], dtype=np.uint8)
        result = evaluate_arrays(baseline, candidate, candidate_class=CONTROL_NEGATIVE)
        self.assertTrue(result["hard_safety_gate"]["raw_detection"]["local_color_shift"])
        self.assertIn("LOCAL_COLOR_SHIFT_DETECTED", result["hard_safety_gate"]["failures"])

    def test_product_pass_global_invariant_accepts_only_complete_authorized_pass(self) -> None:
        result = gate.validate_product_pass_global_invariant([_authorized_product_pass_record()])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["product_pass_count"], 1)
        self.assertEqual(result["violation_count"], 0)

    def test_validation_rejects_control_fixture_product_pass(self) -> None:
        record = _authorized_product_pass_record("CONTROL_FIXTURE_BYPASS")
        record["human_review_control_fixture_only"] = True
        result = gate.validate_product_pass_global_invariant([record])
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("CONTROL_FIXTURE_AUTHORIZATION", result["violations"][0]["violations"])
        self.assertEqual(gate.control_fixture_product_authorization_count([record]), 1)

    def test_validation_rejects_incomplete_mandatory_product_pass(self) -> None:
        record = _authorized_product_pass_record("MANDATORY_INCOMPLETE_BYPASS")
        record["mandatory_gate_complete"] = False
        result = gate.validate_product_pass_global_invariant([record])
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("MANDATORY_GATE_INCOMPLETE", result["violations"][0]["violations"])

    def test_global_invariant_checks_every_product_pass(self) -> None:
        valid = _authorized_product_pass_record("VALID_PASS")
        invalid = _authorized_product_pass_record("INVALID_TEST_VECTOR_PASS")
        invalid["test_vector_only"] = True
        result = gate.validate_product_pass_global_invariant([valid, invalid, {"candidate_class": CONTROL_ORACLE, "delivery_status": "PASS"}])
        self.assertEqual(result["product_pass_count"], 2)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["violations"][0]["case_id"], "INVALID_TEST_VECTOR_PASS")
        self.assertIn("TEST_VECTOR_AUTHORIZATION", result["violations"][0]["violations"])

    def test_real_e1_case_reuses_existing_rerender_contract(self) -> None:
        manifest_hash_before = sha256_file(E1_01_MANIFEST)
        manifest = json.loads(E1_01_MANIFEST.read_text(encoding="utf-8"))
        case = next(item for item in manifest["cases"] if item["case_id"] == "E1C002")
        baseline = Path(__file__).resolve().parents[2] / case["safe_base"]["path"]
        spec = _candidate_spec(case, baseline, "TEST_ZERO_E1C002", CONTROL_ZERO, "BASELINE_IDENTITY_CONTROL")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "comparison"
            result = evaluate_case(E1_01_MANIFEST, "E1C002", baseline, spec, output)
            self.assertEqual(result["evaluation_status"], "COMPLETE")
            self.assertEqual(result["quality_gain_status"], QUALITY_GAIN_NOT_PROVEN)
            self.assertTrue((output / "comparison_manifest.json").is_file())
            self.assertTrue((output / "full_image_side_by_side.png").is_file())
            self.assertEqual(len(result["roi_results"]), len(case["roi"]))
        self.assertEqual(sha256_file(E1_01_MANIFEST), manifest_hash_before)


if __name__ == "__main__":
    unittest.main()
