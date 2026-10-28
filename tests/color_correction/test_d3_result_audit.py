from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image, ImageOps

import engine.color_correction as color_correction_api
import engine.color_correction.candidate_generation as candidate_generation_module
import engine.color_correction.result_audit as result_audit_module
from engine.color_correction import (
    AcceptanceAuthority,
    CorrectionParameters,
    D1Action,
    FinalAction,
    NetGain,
    analyze_color_usability,
    analyze_color_usability_file,
    audit_candidate,
    execute_basic_correction,
    generate_candidate,
)
from tests.color_correction.d1_replay_support import build_replay_image
from tests.color_correction.test_color_usability_decision import _load_authoritative_d01_dataset


ROOT = Path(__file__).resolve().parents[2]


def _load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(ImageOps.exif_transpose(image).convert("RGB"))


def _local_alpha_gradient(shape: tuple[int, int], transition_width: int = 4) -> np.ndarray:
    height, width = shape
    if width <= transition_width:
        raise ValueError("alpha-gradient fixture requires an opaque interior")
    alpha = np.full((height, width), 255, dtype=np.uint8)
    alpha[:, : transition_width + 1] = np.linspace(
        0,
        255,
        transition_width + 1,
        dtype=np.uint8,
    )[None, :]
    return alpha


class D3ResultAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = _load_authoritative_d01_dataset(ROOT)

    def _d01(self, sample: str):
        path, authority = self.dataset[sample]
        original = _load_rgb(path)
        decision = analyze_color_usability_file(path)
        d2_result = generate_candidate(original, decision)
        return original, decision, d2_result, authority

    def test_module_level_expected_api(self) -> None:
        module_level_expected_api = {
            "D3_SCHEMA_VERSION",
            "D3_AUDIT_VERSION",
            "D2_CANDIDATE_IDENTITY_VERSION",
            "D3_BASIC_REPLAY_SCHEMA_VERSION",
            "D3_BASIC_REPLAY_AUDIT_VERSION",
            "D3_BASIC_CANDIDATE_IDENTITY_VERSION",
            "AcceptanceAuthority",
            "FinalAction",
            "NetGain",
            "replay_basic_correction",
            "audit_basic_correction",
            "audit_candidate",
            "audit_reference_candidate",
        }
        self.assertEqual(set(result_audit_module.__all__), module_level_expected_api)
        public_functions = {
            name
            for name in result_audit_module.__all__
            if inspect.isfunction(getattr(result_audit_module, name, None))
        }
        self.assertEqual(
            public_functions,
            {
                "audit_candidate",
                "replay_basic_correction",
                "audit_basic_correction",
                "audit_reference_candidate",
            },
        )

    def test_package_level_public_api(self) -> None:
        package_level_public_api = {
            "CORRECTION_PARAMETERS_SCHEMA_VERSION",
            "CORRECTION_WORKING_COLOR_SPACE",
            "CORRECTION_EXECUTION_ORDER",
            "PARAMETER_SPECS",
            "ParameterSpec",
            "CorrectionParameters",
            "parameter_contract",
            "BASIC_CORRECTION_EXECUTOR_VERSION",
            "BasicCorrectionResult",
            "BasicCorrectionSafetyError",
            "execute_basic_correction",
            "FORMAL_COLOR_RUNTIME_VERSION",
            "run_formal_color_runtime",
            "QUALITY_EVIDENCE_SCHEMA_VERSION",
            "QUALITY_EVIDENCE_ENGINE_VERSION",
            "EvidenceVerdict",
            "QualityNetBenefit",
            "QualityMetricEvidence",
            "QualityEvidence",
            "evaluate_quality_evidence",
            "OBJECTIVE_DIAGNOSIS_SCHEMA_VERSION",
            "OBJECTIVE_DIAGNOSIS_ENGINE_VERSION",
            "DiagnosisSeverity",
            "DiagnosticFinding",
            "ObjectiveColorDiagnosis",
            "build_objective_diagnosis",
            "PARAMETER_DECISION_SCHEMA_VERSION",
            "PARAMETER_DECISION_ENGINE_VERSION",
            "SEVERITY_PARAMETER_MAGNITUDES",
            "ParameterDecisionOutcome",
            "ParameterDirection",
            "ParameterDecisionItem",
            "ParameterDecision",
            "magnitude_for",
            "decide_correction_parameters",
            "validate_parameter_decision",
            "bind_parameter_decision",
            "D2_ENGINE_VERSION",
            "D2_SCHEMA_VERSION",
            "D2_SUPPORTED_D1_SCHEMA_VERSION",
            "D2_SUPPORTED_D1_ENGINE_VERSION",
            "D2_SUPPORTED_D1_RULE_VERSION",
            "D2_SUPPORTED_SOURCE_FINGERPRINT_VERSION",
            "CandidateExecutor",
            "CandidateType",
            "CorrectionBudget",
            "CorrectionTarget",
            "generate_candidate",
            "D2_CANDIDATE_IDENTITY_VERSION",
            "D3_BASIC_REPLAY_SCHEMA_VERSION",
            "D3_BASIC_REPLAY_AUDIT_VERSION",
            "D3_BASIC_CANDIDATE_IDENTITY_VERSION",
            "D3_AUDIT_VERSION",
            "D3_SCHEMA_VERSION",
            "AcceptanceAuthority",
            "FinalAction",
            "NetGain",
            "replay_basic_correction",
            "audit_basic_correction",
            "audit_candidate",
            "D1_RULE_VERSION",
            "D1_SCHEMA_VERSION",
            "D1_ENGINE_VERSION",
            "SOURCE_FINGERPRINT_VERSION",
            "ColorObservability",
            "ColorStatus",
            "ColorUsabilityDecision",
            "D1Action",
            "ExposureStatus",
            "analyze_color_usability",
            "analyze_color_usability_file",
            "append_shadow_record",
            "build_shadow_record",
            "compute_source_fingerprint",
        }
        self.assertEqual(set(color_correction_api.__all__), package_level_public_api)
        self.assertNotIn("audit_reference_candidate", color_correction_api.__all__)
        self.assertFalse(hasattr(color_correction_api, "audit_reference_candidate"))

    def test_public_surface_has_no_concrete_result_constructor(self) -> None:
        self.assertFalse(hasattr(color_correction_api, "D3AuditResult"))
        self.assertFalse(hasattr(result_audit_module, "D3AuditResult"))
        self.assertFalse(hasattr(color_correction_api, "BasicCorrectionAuditResult"))
        self.assertFalse(hasattr(result_audit_module, "BasicCorrectionAuditResult"))
        self.assertNotIn("d2_result", inspect.signature(audit_candidate).parameters)

    def test_d1_public_constructor_stays_compatible_and_manual_records_fail_closed(self) -> None:
        image, _ = build_replay_image("too_dark")
        pixels = np.rint(image * 255.0).astype(np.uint8)
        decision = analyze_color_usability(pixels, person_regions=[])
        constructor = type(decision)
        parameters = inspect.signature(constructor).parameters

        self.assertNotIn("_person_region_contract", parameters)
        self.assertNotIn("_person_region_binding", parameters)
        rebuilt = constructor(**{
            name: getattr(decision, name)
            for name in parameters
        })
        result = generate_candidate(pixels, rebuilt, person_regions=[])
        audit = audit_candidate(pixels, rebuilt, person_regions=[])
        self.assertEqual(result.status, "PROTECTION_BLOCKED")
        self.assertEqual(result.blocker, "MISSING_PERSON_REGION_CONTRACT")
        self.assertEqual(audit.status, "PROTECTION_BLOCKED")
        self.assertEqual(audit.blocker, "MISSING_PERSON_REGION_CONTRACT")

    def test_external_d2_dto_has_no_public_authority_and_stale_d1_fails_closed(self) -> None:
        original, decision, result, _ = self._d01("D01_04")
        manual_copy = replace(result)
        self.assertIsNot(manual_copy, result)
        with self.assertRaises(TypeError):
            audit_candidate(original, decision, manual_copy)
        with self.assertRaises(TypeError):
            audit_candidate(original, decision, d2_result=manual_copy)

        for field, blocker in (
            ("schema_version", "UNSUPPORTED_D1_SCHEMA_VERSION"),
            ("engine_version", "UNSUPPORTED_D1_ENGINE_VERSION"),
            ("rule_version", "UNSUPPORTED_D1_RULE_VERSION"),
        ):
            with self.subTest(stale_d1=field):
                audit = audit_candidate(original, replace(decision, **{field: f"stale.{field}"}))
                self.assertEqual(audit.status, "PROTECTION_BLOCKED")
                self.assertEqual(audit.blocker, blocker)
        missing_fingerprint = audit_candidate(original, replace(decision, source_fingerprint=""))
        self.assertEqual(missing_fingerprint.status, "PROTECTION_BLOCKED")
        self.assertEqual(missing_fingerprint.blocker, "MISSING_SOURCE_FINGERPRINT")
        for field, blocker in (
            ("schema_version", "MISSING_D1_SCHEMA_VERSION"),
            ("engine_version", "MISSING_D1_ENGINE_VERSION"),
            ("rule_version", "MISSING_D1_RULE_VERSION"),
        ):
            with self.subTest(missing_d1=field):
                values = dict(decision.__dict__)
                values.pop(field)
                audit = audit_candidate(original, SimpleNamespace(**values))
                self.assertEqual(audit.status, "PROTECTION_BLOCKED")
                self.assertEqual(audit.blocker, blocker)

    def test_internal_d2_source_binding_fails_closed(self) -> None:
        blue_original, blue_decision, _, _ = self._d01("D01_03")
        other_original = _load_rgb(self.dataset["D01_15"][0])
        direct_binding_mismatch = audit_candidate(other_original, blue_decision)
        self.assertEqual(direct_binding_mismatch.status, "PROTECTION_BLOCKED")
        self.assertEqual(direct_binding_mismatch.blocker, "SOURCE_FINGERPRINT_MISMATCH")

        with patch.object(result_audit_module, "generate_candidate", wraps=generate_candidate) as internal_d2:
            audit = audit_candidate(blue_original, blue_decision)
        internal_d2.assert_called_once()
        self.assertEqual(audit.status, "AUDIT_COMPLETE")

    def test_missing_or_mismatched_trusted_executor_trace_fails_closed(self) -> None:
        original, decision, result, _ = self._d01("D01_04")
        for damaged_result, blocker in (
            (
                replace(result, attempts=()),
                "D2_TRUSTED_EXECUTOR_REFERENCE_INVALID",
            ),
            (
                replace(result, executor_parameters={"tampered": True}),
                "D2_TRUSTED_EXECUTOR_PARAMETERS_MISMATCH",
            ),
        ):
            with self.subTest(blocker=blocker), patch.object(
                result_audit_module,
                "generate_candidate",
                return_value=damaged_result,
            ):
                audit = audit_candidate(original, decision)
            self.assertEqual(audit.status, "PROTECTION_BLOCKED")
            self.assertEqual(audit.blocker, blocker)
            self.assertEqual(audit.acceptance_authority, AcceptanceAuthority.NONE)
            self.assertEqual(audit.final_action, FinalAction.REVIEW_REQUIRED)

    def test_coherent_executor_parameter_mutation_fails_source_contract(self) -> None:
        image, _ = build_replay_image("too_dark")
        original = np.rint(image * 255.0).astype(np.uint8)
        decision = analyze_color_usability(original, input_order="RGB")
        result = generate_candidate(original, decision, input_order="RGB")
        selected = next(
            attempt
            for attempt in result.attempts
            if attempt.executor == result.executor
            and attempt.budget == result.plan.correction_budget
            and attempt.safety_status == "PASS"
            and not attempt.violations
        )
        self.assertIs(selected.parameters, result.executor_parameters)
        result.executor_parameters["values"]["exposure"] = (
            float(result.executor_parameters["values"]["exposure"]) + 0.50
        )

        with patch.object(
            result_audit_module,
            "generate_candidate",
            return_value=result,
        ):
            audit = audit_candidate(original, decision, input_order="RGB")

        self.assertEqual(audit.status, "AUDIT_COMPLETE")
        self.assertFalse(audit.audit_metrics["trusted_executor_reference_match"])
        self.assertEqual(audit.pass_status["SIDE_EFFECT_PASS"], "NO")
        self.assertEqual(audit.acceptance_authority, AcceptanceAuthority.NONE)
        self.assertEqual(audit.final_action, FinalAction.ACCEPT_ORIGINAL)

    def test_coherent_parameter_and_candidate_change_is_bound_to_a_new_identity(self) -> None:
        original, decision, result, _ = self._d01("D01_03")
        baseline = audit_candidate(original, decision)
        self.assertEqual(result.executor.value, "DETERMINISTIC_BASIC_CORRECTION")
        selected = next(
            attempt
            for attempt in result.attempts
            if attempt.executor == result.executor
            and attempt.budget == result.plan.correction_budget
            and attempt.safety_status == "PASS"
            and not attempt.violations
        )
        self.assertIs(selected.parameters, result.executor_parameters)
        values = dict(result.executor_parameters["values"])
        values["temperature"] = float(values["temperature"]) + 1.0
        parameters = CorrectionParameters.from_mapping(values)
        changed = execute_basic_correction(
            original,
            parameters,
        )
        result.executor_parameters.clear()
        result.executor_parameters.update(changed.parameter_record)
        selected.candidate_rgb01[:] = changed.candidate_image.astype(np.float32) / 255.0
        changed_result = replace(result, candidate_image=changed.candidate_image)

        with patch.object(
            result_audit_module,
            "generate_candidate",
            return_value=changed_result,
        ):
            audit = audit_candidate(original, decision)

        self.assertEqual(audit.status, "AUDIT_COMPLETE")
        self.assertTrue(audit.audit_metrics["trusted_executor_reference_match"])
        self.assertNotEqual(audit.d2_candidate_identity, baseline.d2_candidate_identity)
        self.assertEqual(audit.final_action, FinalAction.REVIEW_REQUIRED)

    def test_deterministic_basic_color_pixel_fault_is_rejected_by_source_replay(self) -> None:
        original, decision, _, _ = self._d01("D01_03")
        real_candidate = candidate_generation_module._basic_color_candidate

        def damaged_candidate(rgb, d1, budget):
            candidate, parameters = real_candidate(rgb, d1, budget)
            damaged = candidate.copy()
            damaged[10:18, 10:18, 0] = np.clip(
                damaged[10:18, 10:18, 0] + (8.0 / 255.0),
                0.0,
                1.0,
            )
            return damaged, parameters

        with patch.object(
            candidate_generation_module,
            "_basic_color_candidate",
            side_effect=damaged_candidate,
        ):
            audit = audit_candidate(original, decision)

        self.assertEqual(audit.status, "AUDIT_COMPLETE")
        self.assertFalse(audit.audit_metrics["trusted_executor_reference_match"])
        self.assertEqual(audit.pass_status["SIDE_EFFECT_PASS"], "NO")
        self.assertEqual(audit.acceptance_authority, AcceptanceAuthority.NONE)
        self.assertEqual(audit.final_action, FinalAction.ACCEPT_ORIGINAL)

    def test_hidden_rgba_rgb_cannot_change_visible_exposure_result(self) -> None:
        image, _ = build_replay_image("too_dark")
        rgb = np.rint(image * 255.0).astype(np.uint8)
        height, width = rgb.shape[:2]
        alpha = np.full((height, width), 255, dtype=np.uint8)
        alpha[:, 3 * width // 4 :] = 2
        first = np.dstack((rgb.copy(), alpha))
        second = first.copy()
        hidden = alpha <= 2
        first[..., :3][hidden] = np.array([0, 255, 0], dtype=np.uint8)
        second[..., :3][hidden] = np.array([255, 0, 255], dtype=np.uint8)

        first_decision = analyze_color_usability(first)
        second_decision = analyze_color_usability(second)
        first_semantics = first_decision.to_dict()
        second_semantics = second_decision.to_dict()
        first_semantics.pop("source_fingerprint")
        second_semantics.pop("source_fingerprint")
        self.assertEqual(first_semantics, second_semantics)
        self.assertEqual(first_decision.d1_action, D1Action.AUTO_CORRECT)

        first_result = generate_candidate(first, first_decision)
        second_result = generate_candidate(second, second_decision)
        self.assertEqual(first_result.executor_parameters, second_result.executor_parameters)
        self.assertEqual(first_result.before_metrics, second_result.before_metrics)
        self.assertEqual(first_result.after_metrics, second_result.after_metrics)
        visible = alpha > 2
        self.assertTrue(
            np.array_equal(
                first_result.candidate_image[..., :3][visible],
                second_result.candidate_image[..., :3][visible],
            )
        )

        first_audit = audit_candidate(first, first_decision)
        second_audit = audit_candidate(second, second_decision)
        self.assertEqual(first_audit.final_action, second_audit.final_action)
        self.assertEqual(first_audit.pass_status, second_audit.pass_status)
        self.assertEqual(first_audit.acceptance_authority, second_audit.acceptance_authority)
        self.assertEqual(first_audit.final_action, FinalAction.ACCEPT_CORRECTED)
        self.assertTrue(first_audit.audit_metrics["analysis_mask_unchanged"])
        self.assertTrue(second_audit.audit_metrics["analysis_mask_unchanged"])

    def test_person_region_hidden_rgba_rgb_cannot_change_d1_d2_or_d3(self) -> None:
        image, _ = build_replay_image("too_dark")
        rgb = np.rint(image * 255.0).astype(np.uint8)
        height, width = rgb.shape[:2]
        alpha = np.full((height, width), 255, dtype=np.uint8)
        alpha[:, 3 * width // 4 :] = 2
        first = np.dstack((rgb.copy(), alpha))
        second = first.copy()
        hidden = alpha <= 2
        first[..., :3][hidden] = np.array([183, 122, 87], dtype=np.uint8)
        second[..., :3][hidden] = np.array([20, 20, 240], dtype=np.uint8)
        person_regions = [(3 * width // 4 - 20, 30, width // 4 + 10, 120)]

        first_decision = analyze_color_usability(
            first,
            person_regions=person_regions,
        )
        second_decision = analyze_color_usability(
            second,
            person_regions=person_regions,
        )
        first_semantics = first_decision.to_dict()
        second_semantics = second_decision.to_dict()
        first_semantics.pop("source_fingerprint")
        second_semantics.pop("source_fingerprint")
        self.assertEqual(first_semantics, second_semantics)
        self.assertEqual(first_decision.d1_action, D1Action.AUTO_CORRECT)

        first_result = generate_candidate(
            first,
            first_decision,
            person_regions=person_regions,
        )
        second_result = generate_candidate(
            second,
            second_decision,
            person_regions=person_regions,
        )
        self.assertEqual(first_result.executor_parameters, second_result.executor_parameters)
        self.assertEqual(first_result.before_metrics, second_result.before_metrics)
        self.assertEqual(first_result.after_metrics, second_result.after_metrics)
        visible = alpha > 2
        self.assertTrue(
            np.array_equal(
                first_result.candidate_image[..., :3][visible],
                second_result.candidate_image[..., :3][visible],
            )
        )

        first_audit = audit_candidate(
            first,
            first_decision,
            person_regions=person_regions,
        )
        second_audit = audit_candidate(
            second,
            second_decision,
            person_regions=person_regions,
        )
        self.assertEqual(first_audit.final_action, second_audit.final_action)
        self.assertEqual(first_audit.pass_status, second_audit.pass_status)
        self.assertEqual(first_audit.acceptance_authority, second_audit.acceptance_authority)
        self.assertEqual(first_audit.final_action, FinalAction.ACCEPT_CORRECTED)

    def test_large_source_person_regions_use_source_coordinates_across_d1_d2_d3(self) -> None:
        image, _ = build_replay_image("too_dark")
        rgb = cv2.resize(
            np.rint(image * 255.0).astype(np.uint8),
            (1200, 800),
            interpolation=cv2.INTER_NEAREST,
        )
        person_region = (900, 150, 250, 500)
        x, y, width, height = person_region
        rgb[y : y + height, x : x + width] = np.array([90, 65, 50], dtype=np.uint8)
        alpha = np.full(rgb.shape[:2], 255, dtype=np.uint8)
        alpha[y : y + height, x + width - 50 : x + width] = 2
        first = np.dstack((rgb.copy(), alpha))
        second = first.copy()
        hidden = alpha <= 2
        first[..., :3][hidden] = np.array([183, 122, 87], dtype=np.uint8)
        second[..., :3][hidden] = np.array([20, 20, 240], dtype=np.uint8)
        person_regions = [person_region]

        first_decision = analyze_color_usability(first, person_regions=person_regions)
        second_decision = analyze_color_usability(second, person_regions=person_regions)
        self.assertEqual(first_decision.image_facts["analysis_width"], 960)
        self.assertEqual(first_decision.image_facts["analysis_height"], 640)
        self.assertTrue(first_decision.skin_color_facts["person_present"])
        self.assertGreater(first_decision.skin_color_facts["trusted_skin_pixel_ratio"], 0.08)
        first_semantics = first_decision.to_dict()
        second_semantics = second_decision.to_dict()
        first_semantics.pop("source_fingerprint")
        second_semantics.pop("source_fingerprint")
        self.assertEqual(first_semantics, second_semantics)
        self.assertEqual(first_decision.d1_action, D1Action.AUTO_CORRECT)

        first_result = generate_candidate(
            first,
            first_decision,
            person_regions=person_regions,
        )
        second_result = generate_candidate(
            second,
            second_decision,
            person_regions=person_regions,
        )
        self.assertEqual(first_result.executor_parameters, second_result.executor_parameters)
        self.assertEqual(first_result.before_metrics, second_result.before_metrics)
        self.assertEqual(first_result.after_metrics, second_result.after_metrics)
        visible = alpha > 2
        self.assertTrue(
            np.array_equal(
                first_result.candidate_image[..., :3][visible],
                second_result.candidate_image[..., :3][visible],
            )
        )

        first_audit = audit_candidate(
            first,
            first_decision,
            person_regions=person_regions,
        )
        second_audit = audit_candidate(
            second,
            second_decision,
            person_regions=person_regions,
        )
        self.assertEqual(first_audit.final_action, second_audit.final_action)
        self.assertEqual(first_audit.pass_status, second_audit.pass_status)
        self.assertEqual(first_audit.acceptance_authority, second_audit.acceptance_authority)
        self.assertEqual(first_audit.final_action, FinalAction.ACCEPT_ORIGINAL)

        with patch(
            "engine.color_correction.usability_decision._detect_faces",
            return_value=[(720, 120, 200, 400)],
        ) as detector:
            detected_decision = analyze_color_usability(first)
            detected_result = generate_candidate(first, detected_decision)
            detected_audit = audit_candidate(first, detected_decision)
        detector.assert_called_once()
        self.assertTrue(detected_decision.skin_color_facts["person_present"])
        self.assertGreater(detected_decision.skin_color_facts["trusted_skin_pixel_ratio"], 0.08)
        self.assertEqual(detected_result.status, "CANDIDATE_READY")
        self.assertTrue(detected_result.attempts)
        self.assertTrue(
            all(
                attempt.person_regions == (person_region,)
                for attempt in detected_result.attempts
            )
        )
        self.assertEqual(detected_audit.status, "AUDIT_COMPLETE")

    def test_person_region_three_state_contract_is_reused_or_fails_closed(self) -> None:
        image, _ = build_replay_image("too_dark")
        pixels = np.rint(image * 255.0).astype(np.uint8)

        with patch(
            "engine.color_correction.usability_decision._detect_faces",
            side_effect=AssertionError("explicit none must not run face detection"),
        ):
            explicit_none = analyze_color_usability(pixels, person_regions=[])
            explicit_none_result = generate_candidate(
                pixels,
                explicit_none,
                person_regions=[],
            )
            explicit_none_audit = audit_candidate(
                pixels,
                explicit_none,
                person_regions=[],
            )
        self.assertEqual(explicit_none_result.status, "CANDIDATE_READY")
        self.assertTrue(
            all(not attempt.person_regions for attempt in explicit_none_result.attempts)
        )
        self.assertEqual(explicit_none_audit.status, "AUDIT_COMPLETE")

        explicit_as_auto = generate_candidate(pixels, explicit_none)
        self.assertEqual(explicit_as_auto.status, "PROTECTION_BLOCKED")
        self.assertEqual(explicit_as_auto.blocker, "PERSON_REGION_CONTRACT_MISMATCH")
        explicit_as_auto_audit = audit_candidate(pixels, explicit_none)
        self.assertEqual(explicit_as_auto_audit.status, "PROTECTION_BLOCKED")
        self.assertEqual(
            explicit_as_auto_audit.blocker,
            "PERSON_REGION_CONTRACT_MISMATCH",
        )

        with patch(
            "engine.color_correction.usability_decision._detect_faces",
            return_value=[],
        ) as detector:
            automatic = analyze_color_usability(pixels)
        detector.assert_called_once()
        auto_as_explicit_none = generate_candidate(
            pixels,
            automatic,
            person_regions=[],
        )
        self.assertEqual(auto_as_explicit_none.status, "PROTECTION_BLOCKED")
        self.assertEqual(
            auto_as_explicit_none.blocker,
            "PERSON_REGION_CONTRACT_MISMATCH",
        )

        explicit_box = [(10, 10, 40, 40)]
        boxed = analyze_color_usability(pixels, person_regions=explicit_box)
        wrong_box = [(11, 10, 40, 40)]
        wrong_result = generate_candidate(
            pixels,
            boxed,
            person_regions=wrong_box,
        )
        wrong_audit = audit_candidate(
            pixels,
            boxed,
            person_regions=wrong_box,
        )
        self.assertEqual(wrong_result.status, "PROTECTION_BLOCKED")
        self.assertEqual(wrong_result.blocker, "PERSON_REGION_CONTRACT_MISMATCH")
        self.assertEqual(wrong_audit.status, "PROTECTION_BLOCKED")
        self.assertEqual(wrong_audit.blocker, "PERSON_REGION_CONTRACT_MISMATCH")

    def test_person_region_contract_is_private_and_integrity_checked(self) -> None:
        image, _ = build_replay_image("too_dark")
        pixels = np.rint(image * 255.0).astype(np.uint8)
        decision = analyze_color_usability(pixels, person_regions=[])
        result = generate_candidate(pixels, decision, person_regions=[])
        audit = audit_candidate(pixels, decision, person_regions=[])

        public_records = json.dumps(
            {
                "d1": decision.to_dict(),
                "d2": result.to_record(),
                "d3": audit.to_record(),
            },
            sort_keys=True,
        )
        self.assertNotIn("_person_region_contract", public_records)
        self.assertNotIn("source_regions", public_records)
        self.assertNotIn("person_region_contract_digest", public_records)

        contract = decision.__dict__["_person_region_contract"]
        tampered = replace(decision)
        object.__setattr__(
            tampered,
            "_person_region_contract",
            replace(contract, digest="0" * 64),
        )
        object.__setattr__(
            tampered,
            "_person_region_binding",
            decision.__dict__["_person_region_binding"],
        )
        tampered_result = generate_candidate(pixels, tampered, person_regions=[])
        tampered_audit = audit_candidate(pixels, tampered, person_regions=[])
        self.assertEqual(tampered_result.status, "PROTECTION_BLOCKED")
        self.assertEqual(tampered_result.blocker, "INVALID_PERSON_REGION_CONTRACT")
        self.assertEqual(tampered_audit.status, "PROTECTION_BLOCKED")
        self.assertEqual(tampered_audit.blocker, "INVALID_PERSON_REGION_CONTRACT")

        malformed_binding = analyze_color_usability(pixels, person_regions=[])
        object.__setattr__(
            malformed_binding,
            "_person_region_binding",
            replace(
                malformed_binding.__dict__["_person_region_binding"],
                digest=None,
            ),
        )
        malformed_result = generate_candidate(
            pixels,
            malformed_binding,
            person_regions=[],
        )
        malformed_audit = audit_candidate(
            pixels,
            malformed_binding,
            person_regions=[],
        )
        self.assertEqual(malformed_result.status, "PROTECTION_BLOCKED")
        self.assertEqual(malformed_result.blocker, "INVALID_PERSON_REGION_CONTRACT")
        self.assertEqual(malformed_audit.status, "PROTECTION_BLOCKED")
        self.assertEqual(malformed_audit.blocker, "INVALID_PERSON_REGION_CONTRACT")

        missing_values = dict(decision.__dict__)
        missing_values.pop("_person_region_contract")
        missing_contract = SimpleNamespace(**missing_values)
        missing_result = generate_candidate(
            pixels,
            missing_contract,
            person_regions=[],
        )
        missing_audit = audit_candidate(
            pixels,
            missing_contract,
            person_regions=[],
        )
        self.assertEqual(missing_result.status, "PROTECTION_BLOCKED")
        self.assertEqual(missing_result.blocker, "MISSING_PERSON_REGION_CONTRACT")
        self.assertEqual(missing_audit.status, "PROTECTION_BLOCKED")
        self.assertEqual(missing_audit.blocker, "MISSING_PERSON_REGION_CONTRACT")

        first_regions = [(5, 5, 30, 30)]
        second_regions = [(45, 45, 30, 30)]
        first = analyze_color_usability(pixels, person_regions=first_regions)
        second = analyze_color_usability(pixels, person_regions=second_regions)
        grafted = replace(first)
        object.__setattr__(
            grafted,
            "_person_region_contract",
            second.__dict__["_person_region_contract"],
        )
        object.__setattr__(
            grafted,
            "_person_region_binding",
            first.__dict__["_person_region_binding"],
        )
        grafted_result = generate_candidate(
            pixels,
            grafted,
            person_regions=second_regions,
        )
        grafted_audit = audit_candidate(
            pixels,
            grafted,
            person_regions=second_regions,
        )
        self.assertEqual(grafted_result.status, "PROTECTION_BLOCKED")
        self.assertEqual(grafted_result.blocker, "INVALID_PERSON_REGION_CONTRACT")
        self.assertEqual(grafted_audit.status, "PROTECTION_BLOCKED")
        self.assertEqual(grafted_audit.blocker, "INVALID_PERSON_REGION_CONTRACT")

    def test_candidate_identity_binds_opaque_person_region_context(self) -> None:
        original, decision, result, _ = self._d01("D01_04")
        identity = result_audit_module._candidate_identity(
            decision.source_fingerprint,
            result,
        )
        replacement_regions = ((0, 0, 1, 1),)
        if all(attempt.person_regions == replacement_regions for attempt in result.attempts):
            replacement_regions = ((1, 1, 1, 1),)
        changed = replace(
            result,
            attempts=tuple(
                replace(attempt, person_regions=replacement_regions)
                for attempt in result.attempts
            ),
        )

        self.assertTrue(np.array_equal(result.candidate_image, changed.candidate_image))
        self.assertNotEqual(
            identity,
            result_audit_module._candidate_identity(
                decision.source_fingerprint,
                changed,
            ),
        )

    def test_whole_person_region_credential_cannot_transfer_between_equal_decisions(self) -> None:
        pixels = np.full((96, 96, 3), 96, dtype=np.uint8)
        first_regions = [(5, 5, 24, 24)]
        second_regions = [(55, 55, 24, 24)]
        first = analyze_color_usability(pixels, person_regions=first_regions)
        second = analyze_color_usability(pixels, person_regions=second_regions)

        self.assertEqual(first.to_dict(), second.to_dict())
        donor_result = generate_candidate(
            pixels,
            second,
            person_regions=second_regions,
        )
        self.assertNotEqual(donor_result.status, "PROTECTION_BLOCKED")

        grafted = replace(first)
        object.__setattr__(
            grafted,
            "_person_region_contract",
            second.__dict__["_person_region_contract"],
        )
        object.__setattr__(
            grafted,
            "_person_region_binding",
            second.__dict__["_person_region_binding"],
        )
        grafted_result = generate_candidate(
            pixels,
            grafted,
            person_regions=second_regions,
        )
        grafted_audit = audit_candidate(
            pixels,
            grafted,
            person_regions=second_regions,
        )

        self.assertEqual(grafted_result.status, "PROTECTION_BLOCKED")
        self.assertEqual(grafted_result.blocker, "INVALID_PERSON_REGION_CONTRACT")
        self.assertEqual(grafted_audit.status, "PROTECTION_BLOCKED")
        self.assertEqual(grafted_audit.blocker, "INVALID_PERSON_REGION_CONTRACT")

    def test_structural_decision_clone_cannot_reuse_instance_credential(self) -> None:
        image, _ = build_replay_image("too_dark")
        pixels = np.rint(image * 255.0).astype(np.uint8)
        decision = analyze_color_usability(pixels, person_regions=[])

        class StructuralDecisionClone:
            def __init__(self, original):
                self.__dict__.update(original.__dict__)
                self._public_record = original.to_dict()

            def to_dict(self):
                return dict(self._public_record)

        forged = StructuralDecisionClone(decision)
        forged_result = generate_candidate(pixels, forged, person_regions=[])
        forged_audit = audit_candidate(pixels, forged, person_regions=[])

        self.assertEqual(forged_result.status, "PROTECTION_BLOCKED")
        self.assertEqual(forged_result.blocker, "INVALID_D1_DECISION_TYPE")
        self.assertEqual(forged_audit.status, "PROTECTION_BLOCKED")
        self.assertEqual(forged_audit.blocker, "INVALID_D1_DECISION_TYPE")

    def test_d01_02_and_d01_03_are_technically_audited_but_review_only(self) -> None:
        for sample in ("D01_02", "D01_03"):
            with self.subTest(sample=sample):
                original, decision, _, authority = self._d01(sample)
                self.assertEqual(authority["interpretation"], "global_error_cast")
                audit = audit_candidate(original, decision)
                self.assertEqual(audit.status, "AUDIT_COMPLETE")
                self.assertEqual(audit.net_gain, NetGain.POSITIVE)
                self.assertEqual(audit.acceptance_authority, AcceptanceAuthority.REVIEW_ONLY)
                self.assertEqual(audit.final_action, FinalAction.REVIEW_REQUIRED)
                self.assertNotEqual(audit.final_action, FinalAction.ACCEPT_CORRECTED)
                self.assertEqual(audit.pass_status["OVERALL_USABILITY_PASS"], "YES")
                for required in (
                    "COLOR_PASS",
                    "EXPOSURE_PASS",
                    "SKIN_PASS",
                    "NEUTRAL_PASS",
                    "BRAND_COLOR_PASS",
                    "HIGHLIGHT_PASS",
                    "SHADOW_PASS",
                    "COLOR_CONSISTENCY_PASS",
                    "REVERSE_CAST_PASS",
                    "SCENE_INTENT_PASS",
                    "SIDE_EFFECT_PASS",
                    "NET_GAIN_PASS",
                ):
                    self.assertEqual(audit.pass_status[required], "YES")

    def test_qualified_and_residual_exposure_candidates_route_differently(self) -> None:
        original, decision, _, _ = self._d01("D01_04")
        protected = audit_candidate(original, decision)
        brand_delta_e = protected.audit_metrics["brand_delta_e"]
        brand_pass = (
            brand_delta_e["mean"] is None
            or (
                float(brand_delta_e["mean"]) <= 6.0
                and float(brand_delta_e["p95"]) <= 12.0
            )
        )
        self.assertEqual(
            protected.pass_status["BRAND_COLOR_PASS"],
            "YES" if brand_pass else "NO",
        )
        self.assertFalse(brand_pass)
        self.assertEqual(protected.net_gain, NetGain.NEGATIVE)
        self.assertEqual(protected.acceptance_authority, AcceptanceAuthority.NONE)
        self.assertEqual(protected.final_action, FinalAction.ACCEPT_ORIGINAL)
        self.assertEqual(protected.pass_status["EXPOSURE_PASS"], "YES")

        for recipe, expected in (
            ("too_dark", FinalAction.ACCEPT_CORRECTED),
            ("too_bright", FinalAction.ACCEPT_CORRECTED),
        ):
            with self.subTest(recipe=recipe):
                image, regions = build_replay_image(recipe)
                pixels = np.rint(image * 255.0).astype(np.uint8)
                d1 = analyze_color_usability(pixels, person_regions=regions)
                audit = audit_candidate(pixels, d1, person_regions=regions)
                self.assertEqual(audit.final_action, expected)
                if expected == FinalAction.ACCEPT_CORRECTED:
                    self.assertEqual(audit.acceptance_authority, AcceptanceAuthority.AUTO_PROVEN)
                else:
                    self.assertEqual(audit.acceptance_authority, AcceptanceAuthority.NONE)
                    self.assertEqual(audit.pass_status["EXPOSURE_PASS"], "NO")
                    self.assertEqual(audit.net_gain, NetGain.INSUFFICIENT)

    def test_keep_original_remains_original_without_candidate_audit(self) -> None:
        image, regions = build_replay_image("neutral_scene")
        pixels = np.rint(image * 255.0).astype(np.uint8)
        decision = analyze_color_usability(pixels, person_regions=regions)
        self.assertEqual(decision.d1_action, D1Action.KEEP_ORIGINAL)
        audit = audit_candidate(pixels, decision, person_regions=regions)
        self.assertEqual(audit.status, "AUDIT_NOT_APPLICABLE")
        self.assertEqual(audit.acceptance_authority, AcceptanceAuthority.NONE)
        self.assertEqual(audit.final_action, FinalAction.ACCEPT_ORIGINAL)

    def test_independent_side_effect_controls_force_original_fallback(self) -> None:
        original, decision, result, _ = self._d01("D01_02")
        damaged = result.candidate_image.copy()
        ycrcb = cv2.cvtColor(original, cv2.COLOR_RGB2YCrCb)
        skin = (
            (ycrcb[..., 1] >= 133)
            & (ycrcb[..., 1] <= 180)
            & (ycrcb[..., 2] >= 77)
            & (ycrcb[..., 2] <= 135)
        )
        self.assertGreater(float(skin.mean()), 0.05)
        damaged[skin] = np.array([20, 220, 230], dtype=np.uint8)
        damaged[: damaged.shape[0] // 8, : damaged.shape[1] // 2] = 255
        damaged[-damaged.shape[0] // 8 :, damaged.shape[1] // 2 :] = 0

        damaged_result = replace(result, candidate_image=damaged)
        with patch.object(result_audit_module, "generate_candidate", return_value=damaged_result) as internal_d2:
            audit = audit_candidate(original, decision)
        internal_d2.assert_called_once()
        self.assertEqual(audit.status, "AUDIT_COMPLETE")
        self.assertEqual(audit.pass_status["SKIN_PASS"], "NO")
        self.assertEqual(audit.pass_status["HIGHLIGHT_PASS"], "NO")
        self.assertEqual(audit.pass_status["SHADOW_PASS"], "NO")
        self.assertEqual(audit.pass_status["SIDE_EFFECT_PASS"], "NO")
        self.assertEqual(audit.net_gain, NetGain.NEGATIVE)
        self.assertEqual(audit.acceptance_authority, AcceptanceAuthority.NONE)
        self.assertEqual(audit.final_action, FinalAction.ACCEPT_ORIGINAL)

    def test_transparent_rgb_damage_cannot_receive_auto_acceptance(self) -> None:
        image, _ = build_replay_image("too_dark")
        rgb = np.rint(image * 255.0).astype(np.uint8)
        alpha = np.full(rgb.shape[:2], 255, dtype=np.uint8)
        alpha[:16, :] = 0
        rgba = np.dstack((rgb, alpha))
        decision = analyze_color_usability(rgba, input_order="RGB")
        result = generate_candidate(rgba, decision, input_order="RGB")
        self.assertIsNotNone(result.candidate_image)
        private_record = json.dumps(result.to_record(), sort_keys=True)
        self.assertNotIn("person_regions", private_record)
        self.assertNotIn("candidate_rgb01", private_record)

        damaged = result.candidate_image.copy()
        transparent = alpha == 0
        damaged[..., :3][transparent] ^= np.uint8(255)
        damaged_result = replace(result, candidate_image=damaged)
        with patch.object(result_audit_module, "generate_candidate", return_value=damaged_result):
            audit = audit_candidate(rgba, decision, input_order="RGB")

        self.assertGreater(audit.audit_metrics["transparent_rgb_changed_pixel_count"], 0)
        self.assertFalse(audit.audit_metrics["transparent_rgb_unchanged"])
        self.assertEqual(audit.pass_status["SIDE_EFFECT_PASS"], "NO")
        self.assertEqual(audit.net_gain, NetGain.NEGATIVE)
        self.assertEqual(audit.acceptance_authority, AcceptanceAuthority.NONE)
        self.assertEqual(audit.final_action, FinalAction.ACCEPT_ORIGINAL)

    def test_semi_transparent_fringe_damage_cannot_receive_auto_acceptance(self) -> None:
        image, _ = build_replay_image("too_dark")
        original_rgb = np.rint(image * 255.0).astype(np.uint8)
        rgb = np.repeat(
            np.median(original_rgb, axis=1).astype(np.uint8)[:, None, :],
            original_rgb.shape[1],
            axis=1,
        )
        alpha = _local_alpha_gradient(rgb.shape[:2])
        rgba = np.dstack((rgb, alpha))
        decision = analyze_color_usability(rgba, input_order="RGB")
        result = generate_candidate(rgba, decision, input_order="RGB")
        self.assertIsNotNone(result.candidate_image)

        safe_audit = audit_candidate(rgba, decision, input_order="RGB")
        self.assertTrue(safe_audit.audit_metrics["semi_transparent_edge_safe"])
        self.assertTrue(safe_audit.audit_metrics["opaque_reference_sufficient"])
        self.assertEqual(
            safe_audit.audit_metrics["local_opaque_reference_unsupported_pixel_count"],
            0,
        )
        self.assertTrue(
            safe_audit.audit_metrics["semi_transparent_rgb_vector_within_reference"]
        )
        self.assertTrue(safe_audit.audit_metrics["composite_background_delta_equivalent"])
        self.assertTrue(safe_audit.audit_metrics["composite_local_continuity_safe"])
        self.assertTrue(safe_audit.audit_metrics["black_composite_edge_safe"])
        self.assertTrue(safe_audit.audit_metrics["white_composite_edge_safe"])
        self.assertEqual(safe_audit.final_action, FinalAction.ACCEPT_CORRECTED)

        damaged = result.candidate_image.copy()
        semi_transparent = (alpha > 0) & (alpha < 255)
        damaged[..., :3][semi_transparent] = np.array([255, 0, 255], dtype=np.uint8)
        damaged_result = replace(result, candidate_image=damaged)
        with patch.object(result_audit_module, "generate_candidate", return_value=damaged_result):
            audit = audit_candidate(rgba, decision, input_order="RGB")

        self.assertGreater(audit.audit_metrics["semi_transparent_pixel_count"], 0)
        self.assertFalse(audit.audit_metrics["semi_transparent_edge_safe"])
        self.assertEqual(audit.pass_status["SIDE_EFFECT_PASS"], "NO")
        self.assertEqual(audit.acceptance_authority, AcceptanceAuthority.NONE)
        self.assertEqual(audit.final_action, FinalAction.ACCEPT_ORIGINAL)

    def test_sparse_transparent_fringe_cannot_be_compensated_by_opaque_outlier(self) -> None:
        image, _ = build_replay_image("too_dark")
        source_rgb = np.rint(image * 255.0).astype(np.uint8)
        rgb = np.repeat(
            np.median(source_rgb, axis=1).astype(np.uint8)[:, None, :],
            source_rgb.shape[1],
            axis=1,
        )
        alpha = _local_alpha_gradient(rgb.shape[:2])
        rgba = np.dstack((rgb, alpha))
        decision = analyze_color_usability(rgba, input_order="RGB")
        result = generate_candidate(rgba, decision, input_order="RGB")
        self.assertIsNotNone(result.candidate_image)

        for damage_case in ("large_magnitude", "equal_magnitude_wrong_direction"):
            with self.subTest(damage_case=damage_case):
                damaged = result.candidate_image.copy()
                column = 3
                if damage_case == "large_magnitude":
                    damaged[:, column, :3] = np.array([0, 0, 170], dtype=np.uint8)
                else:
                    expected_delta = (
                        result.candidate_image[:, column, :3].astype(np.int16)
                        - rgba[:, column, :3].astype(np.int16)
                    )
                    damaged[:, column, :3] = np.clip(
                        rgba[:, column, :3].astype(np.int16) - expected_delta,
                        0,
                        255,
                    ).astype(np.uint8)
                damaged[0, -1, :3] = np.array([0, 0, 255], dtype=np.uint8)
                damaged_result = replace(result, candidate_image=damaged)
                with patch.object(
                    result_audit_module,
                    "generate_candidate",
                    return_value=damaged_result,
                ):
                    audit = audit_candidate(rgba, decision, input_order="RGB")

                self.assertGreater(
                    audit.audit_metrics["opaque_rgb_max_abs_delta"],
                    audit.audit_metrics["semi_transparent_rgb_max_abs_delta"],
                )
                self.assertTrue(audit.audit_metrics["opaque_reference_sufficient"])
                if damage_case == "large_magnitude":
                    self.assertLess(
                        audit.audit_metrics["opaque_rgb_reference_p99"],
                        audit.audit_metrics["semi_transparent_rgb_max_abs_delta"],
                    )
                    self.assertFalse(
                        audit.audit_metrics["semi_transparent_rgb_magnitude_within_reference"]
                    )
                else:
                    self.assertLessEqual(
                        audit.audit_metrics["semi_transparent_rgb_max_abs_delta"],
                        audit.audit_metrics["opaque_rgb_reference_limit"],
                    )
                    self.assertTrue(
                        audit.audit_metrics["semi_transparent_rgb_magnitude_within_reference"]
                    )
                self.assertFalse(
                    audit.audit_metrics["semi_transparent_rgb_vector_within_reference"]
                )
                self.assertFalse(audit.audit_metrics["semi_transparent_rgb_within_reference"])
                self.assertFalse(audit.audit_metrics["black_composite_edge_safe"])
                self.assertFalse(audit.audit_metrics["white_composite_edge_safe"])
                self.assertFalse(audit.audit_metrics["semi_transparent_edge_safe"])
                self.assertEqual(audit.pass_status["SIDE_EFFECT_PASS"], "NO")
                self.assertEqual(audit.net_gain, NetGain.NEGATIVE)
                self.assertEqual(audit.acceptance_authority, AcceptanceAuthority.NONE)
                self.assertEqual(audit.final_action, FinalAction.ACCEPT_ORIGINAL)

    def test_joint_rgb_recombination_and_local_discontinuity_cannot_auto_accept(self) -> None:
        image, _ = build_replay_image("too_dark")
        source_rgb = np.rint(image * 255.0).astype(np.uint8)
        rgb = np.repeat(
            np.median(source_rgb, axis=1).astype(np.uint8)[:, None, :],
            source_rgb.shape[1],
            axis=1,
        )
        alpha = _local_alpha_gradient(rgb.shape[:2])
        rgba = np.dstack((rgb, alpha))
        decision = analyze_color_usability(rgba, input_order="RGB")
        result = generate_candidate(rgba, decision, input_order="RGB")
        self.assertIsNotNone(result.candidate_image)

        for damage_scope in ("single_pixel", "single_column"):
            with self.subTest(damage_scope=damage_scope):
                damaged = result.candidate_image.copy()
                opaque_column = rgb.shape[1] - 1
                half = rgb.shape[0] // 2
                opaque_deltas = np.empty((rgb.shape[0], 3), dtype=np.int16)
                opaque_deltas[:half] = np.array([10, 29, 10], dtype=np.int16)
                opaque_deltas[half:] = np.array([29, 10, 29], dtype=np.int16)
                damaged[:, opaque_column, :3] = np.clip(
                    rgba[:, opaque_column, :3].astype(np.int16) + opaque_deltas,
                    0,
                    255,
                ).astype(np.uint8)

                semi_column = 3
                if damage_scope == "single_pixel":
                    rows = slice(rgb.shape[0] // 2, rgb.shape[0] // 2 + 1)
                else:
                    rows = slice(None)
                expected_delta = (
                    result.candidate_image[rows, semi_column, :3].astype(np.int16)
                    - rgba[rows, semi_column, :3].astype(np.int16)
                )
                damaged[rows, semi_column, :3] = np.clip(
                    rgba[rows, semi_column, :3].astype(np.int16)
                    - expected_delta,
                    0,
                    255,
                ).astype(np.uint8)

                damaged_result = replace(result, candidate_image=damaged)
                with patch.object(
                    result_audit_module,
                    "generate_candidate",
                    return_value=damaged_result,
                ):
                    audit = audit_candidate(rgba, decision, input_order="RGB")

                self.assertTrue(
                    audit.audit_metrics["semi_transparent_rgb_magnitude_within_reference"]
                )
                self.assertEqual(
                    audit.audit_metrics["local_opaque_reference_unsupported_pixel_count"],
                    0,
                )
                self.assertFalse(
                    audit.audit_metrics["semi_transparent_rgb_vector_within_reference"]
                )
                self.assertFalse(audit.audit_metrics["composite_local_continuity_safe"])
                self.assertTrue(
                    audit.audit_metrics["composite_background_delta_equivalent"]
                )
                self.assertFalse(audit.audit_metrics["semi_transparent_edge_safe"])
                self.assertEqual(audit.pass_status["SIDE_EFFECT_PASS"], "NO")
                self.assertEqual(audit.net_gain, NetGain.NEGATIVE)
                self.assertEqual(audit.acceptance_authority, AcceptanceAuthority.NONE)
                self.assertEqual(audit.final_action, FinalAction.ACCEPT_ORIGINAL)

    def test_coherent_opaque_and_semi_damage_cannot_self_authorize(self) -> None:
        image, _ = build_replay_image("too_dark")
        source_rgb = np.rint(image * 255.0).astype(np.uint8)
        rgb = np.repeat(
            np.median(source_rgb, axis=1).astype(np.uint8)[:, None, :],
            source_rgb.shape[1],
            axis=1,
        )
        alpha = _local_alpha_gradient(rgb.shape[:2])
        rgba = np.dstack((rgb, alpha))
        decision = analyze_color_usability(rgba, input_order="RGB")
        result = generate_candidate(rgba, decision, input_order="RGB")
        self.assertIsNotNone(result.candidate_image)

        damaged = result.candidate_image.copy()
        rows = slice(0, 16)
        changed_columns = slice(1, 5)
        coherent_delta = np.array([24, -17, 11], dtype=np.int16)
        damaged[rows, changed_columns, :3] = np.clip(
            damaged[rows, changed_columns, :3].astype(np.int16) + coherent_delta,
            0,
            255,
        ).astype(np.uint8)

        damaged_result = replace(result, candidate_image=damaged)
        with patch.object(
            result_audit_module,
            "generate_candidate",
            return_value=damaged_result,
        ):
            audit = audit_candidate(rgba, decision, input_order="RGB")

        self.assertFalse(audit.audit_metrics["trusted_executor_reference_match"])
        self.assertGreater(
            audit.audit_metrics["trusted_executor_reference_max_abs_error"],
            0.0,
        )
        self.assertEqual(audit.pass_status["SIDE_EFFECT_PASS"], "NO")
        self.assertEqual(audit.acceptance_authority, AcceptanceAuthority.NONE)
        self.assertEqual(audit.final_action, FinalAction.ACCEPT_ORIGINAL)

    def test_candidate_and_attempt_pixels_cannot_share_reference_authority(self) -> None:
        image, _ = build_replay_image("too_dark")
        source_rgb = np.rint(image * 255.0).astype(np.uint8)
        rgb = np.repeat(
            np.median(source_rgb, axis=1).astype(np.uint8)[:, None, :],
            source_rgb.shape[1],
            axis=1,
        )
        alpha = _local_alpha_gradient(rgb.shape[:2])
        rgba = np.dstack((rgb, alpha))
        decision = analyze_color_usability(rgba, input_order="RGB")
        result = generate_candidate(rgba, decision, input_order="RGB")
        self.assertIsNotNone(result.candidate_image)

        damaged = result.candidate_image.copy()
        rows = slice(0, 16)
        columns = slice(1, 5)
        damaged[rows, columns, :3] = np.clip(
            damaged[rows, columns, :3].astype(np.int16) + 10,
            0,
            255,
        ).astype(np.uint8)
        selected = next(
            attempt
            for attempt in result.attempts
            if attempt.executor == result.executor
            and attempt.budget == result.plan.correction_budget
            and attempt.safety_status == "PASS"
            and not attempt.violations
        )
        selected.candidate_rgb01[rows, columns] = (
            damaged[rows, columns, :3].astype(np.float32) / 255.0
        )
        damaged_result = replace(
            result,
            candidate_image=damaged,
        )

        with patch.object(
            result_audit_module,
            "generate_candidate",
            return_value=damaged_result,
        ):
            audit = audit_candidate(rgba, decision, input_order="RGB")

        self.assertEqual(
            audit.audit_metrics["trusted_executor_reference_source"],
            "D3_SOURCE_PARAMETER_REPLAY",
        )
        self.assertFalse(audit.audit_metrics["trusted_executor_reference_match"])
        self.assertEqual(audit.pass_status["SIDE_EFFECT_PASS"], "NO")
        self.assertEqual(audit.net_gain, NetGain.NEGATIVE)
        self.assertEqual(audit.acceptance_authority, AcceptanceAuthority.NONE)
        self.assertEqual(audit.final_action, FinalAction.ACCEPT_ORIGINAL)

    def test_deterministic_d2_executor_pixel_fault_is_rejected_by_source_replay(self) -> None:
        image, _ = build_replay_image("too_dark")
        source_rgb = np.rint(image * 255.0).astype(np.uint8)
        rgb = np.repeat(
            np.median(source_rgb, axis=1).astype(np.uint8)[:, None, :],
            source_rgb.shape[1],
            axis=1,
        )
        alpha = _local_alpha_gradient(rgb.shape[:2])
        rgba = np.dstack((rgb, alpha))
        decision = analyze_color_usability(rgba, input_order="RGB")
        real_executor = candidate_generation_module._exposure_candidate

        def damaged_executor(rgb01, status, budget, analysis_mask=None):
            candidate, parameters = real_executor(
                rgb01,
                status,
                budget,
                analysis_mask,
            )
            damaged = candidate.copy()
            damaged[:16, 1:5] = np.clip(
                damaged[:16, 1:5] + (10.0 / 255.0),
                0.0,
                1.0,
            )
            return damaged, parameters

        with patch.object(
            candidate_generation_module,
            "_exposure_candidate",
            side_effect=damaged_executor,
        ):
            audit = audit_candidate(rgba, decision, input_order="RGB")

        self.assertEqual(audit.status, "AUDIT_COMPLETE")
        self.assertFalse(audit.audit_metrics["trusted_executor_reference_match"])
        self.assertEqual(audit.pass_status["SIDE_EFFECT_PASS"], "NO")
        self.assertEqual(audit.acceptance_authority, AcceptanceAuthority.NONE)
        self.assertEqual(audit.final_action, FinalAction.ACCEPT_ORIGINAL)

    def test_thin_alpha_bridge_cannot_authorize_far_reference(self) -> None:
        image, _ = build_replay_image("too_dark")
        source_rgb = np.rint(image * 255.0).astype(np.uint8)
        rgb = np.repeat(
            np.median(source_rgb, axis=1).astype(np.uint8)[:, None, :],
            source_rgb.shape[1],
            axis=1,
        )
        height, width = rgb.shape[:2]
        alpha = np.zeros((height, width), dtype=np.uint8)
        left1 = width // 3
        right0 = 2 * width // 3
        bridge_row = height // 2
        alpha[:, :left1] = 128
        alpha[bridge_row, left1:right0] = 128
        alpha[:, right0:] = 255
        rgba = np.dstack((rgb, alpha))
        decision = analyze_color_usability(rgba, input_order="RGB")
        result = generate_candidate(rgba, decision, input_order="RGB")
        self.assertIsNotNone(result.candidate_image)

        safe_audit = audit_candidate(rgba, decision, input_order="RGB")

        self.assertEqual(
            safe_audit.audit_metrics["semi_transparent_component_count"],
            1,
        )
        self.assertGreater(
            safe_audit.audit_metrics[
                "local_opaque_reference_unsupported_pixel_count"
            ],
            0,
        )
        self.assertEqual(
            safe_audit.audit_metrics[
                "unsupported_semi_transparent_component_count"
            ],
            1,
        )
        self.assertFalse(
            safe_audit.audit_metrics["local_opaque_reference_authority_used"]
        )
        self.assertTrue(
            safe_audit.audit_metrics["trusted_executor_reference_match"]
        )
        self.assertEqual(safe_audit.final_action, FinalAction.ACCEPT_CORRECTED)

        damaged = result.candidate_image.copy()
        damaged[:, :left1, :3] = np.array([255, 0, 255], dtype=np.uint8)
        damaged_result = replace(result, candidate_image=damaged)
        with patch.object(
            result_audit_module,
            "generate_candidate",
            return_value=damaged_result,
        ):
            audit = audit_candidate(rgba, decision, input_order="RGB")

        self.assertFalse(audit.audit_metrics["trusted_executor_reference_match"])
        self.assertFalse(audit.audit_metrics["semi_transparent_edge_safe"])
        self.assertEqual(audit.pass_status["SIDE_EFFECT_PASS"], "NO")
        self.assertEqual(audit.acceptance_authority, AcceptanceAuthority.NONE)
        self.assertEqual(audit.final_action, FinalAction.ACCEPT_ORIGINAL)

    def test_semi_transparent_component_cannot_borrow_opaque_reference(self) -> None:
        image, _ = build_replay_image("too_dark")
        rgb = np.rint(image * 255.0).astype(np.uint8)
        height, width = rgb.shape[:2]
        alpha = np.zeros((height, width), dtype=np.uint8)
        alpha[:, : width // 3] = 128
        alpha[:, 2 * width // 3 :] = 255
        rgba = np.dstack((rgb, alpha))
        decision = analyze_color_usability(rgba, input_order="RGB")
        result = generate_candidate(rgba, decision, input_order="RGB")
        self.assertIsNotNone(result.candidate_image)

        damaged = result.candidate_image.copy()
        damaged[:, : width // 3, :3] = np.array([255, 0, 255], dtype=np.uint8)
        damaged_result = replace(result, candidate_image=damaged)
        with patch.object(
            result_audit_module,
            "generate_candidate",
            return_value=damaged_result,
        ):
            audit = audit_candidate(rgba, decision, input_order="RGB")

        self.assertTrue(audit.audit_metrics["opaque_reference_sufficient"])
        self.assertEqual(audit.audit_metrics["semi_transparent_component_count"], 1)
        self.assertEqual(
            audit.audit_metrics["unsupported_semi_transparent_component_count"],
            1,
        )
        self.assertEqual(
            audit.audit_metrics["local_opaque_reference_supported_pixel_count"],
            0,
        )
        self.assertEqual(
            audit.audit_metrics["local_opaque_reference_unsupported_pixel_count"],
            audit.audit_metrics["semi_transparent_pixel_count"],
        )
        self.assertFalse(audit.audit_metrics["local_opaque_reference_authority_used"])
        self.assertFalse(audit.audit_metrics["trusted_executor_reference_match"])
        self.assertFalse(audit.audit_metrics["semi_transparent_edge_safe"])
        self.assertEqual(audit.pass_status["SIDE_EFFECT_PASS"], "NO")
        self.assertEqual(audit.net_gain, NetGain.NEGATIVE)
        self.assertEqual(audit.acceptance_authority, AcceptanceAuthority.NONE)
        self.assertEqual(audit.final_action, FinalAction.ACCEPT_ORIGINAL)

    def test_d4_record_is_minimal_and_privacy_safe(self) -> None:
        original, decision, _, _ = self._d01("D01_04")
        audit = audit_candidate(original, decision)
        record = audit.to_record()
        self.assertTrue(record["D2_CANDIDATE_IDENTITY"].startswith("hdde.d2-candidate-identity.v3:"))
        self.assertEqual(record["audit_version"], "hdde.d3-result-audit.v1.4")
        self.assertEqual(color_correction_api.D1_ENGINE_VERSION, "hdde.d1-color-usability.v1.7")
        self.assertEqual(color_correction_api.D1_RULE_VERSION, "hdde.color-usability.rules.v1.7")
        self.assertEqual(color_correction_api.D2_ENGINE_VERSION, "hdde.d2-safe-candidate.v1.3")
        self.assertIn("AUDIT_METRICS", record)
        self.assertIn("PASS_STATUS", record)
        self.assertIn("NET_GAIN", record)
        self.assertIn("ACCEPTANCE_AUTHORITY", record)
        self.assertIn("FINAL_ACTION", record)
        serialized = json.dumps(record)
        self.assertNotIn(str(self.dataset["D01_04"][0]), serialized)
        self.assertNotIn("source_fingerprint", serialized)
        self.assertFalse(record["PRIVACY"]["original_image_saved"])
        self.assertFalse(record["PRIVACY"]["candidate_image_saved"])


if __name__ == "__main__":
    unittest.main()
