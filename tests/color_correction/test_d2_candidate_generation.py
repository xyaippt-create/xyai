from __future__ import annotations

from dataclasses import is_dataclass, replace
import inspect
import json
from types import SimpleNamespace
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

import engine.color_correction as color_correction_public_api
import engine.color_correction.candidate_generation as candidate_generation_module
from engine.color_correction import (
    CandidateExecutor,
    CandidateType,
    CorrectionBudget,
    D1Action,
    analyze_color_usability,
    analyze_color_usability_file,
    build_shadow_record,
    compute_source_fingerprint,
    generate_candidate,
)
from tests.color_correction.d1_replay_support import build_replay_image
from tests.color_correction.test_color_usability_decision import _load_authoritative_d01_dataset


ROOT = Path(__file__).resolve().parents[2]


def _load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(ImageOps.exif_transpose(image).convert("RGB"))


def _lab_distance(left: np.ndarray, right: np.ndarray) -> float:
    if left.shape != right.shape:
        raise AssertionError(f"ground-truth dimensions differ: {left.shape} vs {right.shape}")
    left_lab = cv2.cvtColor(left.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    right_lab = cv2.cvtColor(right.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    return float(np.linalg.norm(left_lab - right_lab, axis=2).mean())


class D2CandidateGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # This loader hard-fails on a missing/unreadable fixture, incomplete label,
        # or hash drift.  D2 executor claims may not silently lose their authority.
        cls.dataset = _load_authoritative_d01_dataset(ROOT)
        cls.reference = _load_rgb(cls.dataset["D01_01"][0])

    def _authoritative_candidate(self, sample: str, budget: CorrectionBudget):
        source_path, authority = self.dataset[sample]
        self.assertEqual(authority["interpretation"], "global_error_cast")
        source = _load_rgb(source_path)
        decision = analyze_color_usability_file(source_path)
        self.assertEqual(decision.d1_action, D1Action.REVIEW_REQUIRED)
        result = generate_candidate(source, decision, budget_cap=budget)
        self.assertEqual(result.status, "CANDIDATE_READY")
        self.assertEqual(result.plan.candidate_type, CandidateType.COLOR_REVIEW_CANDIDATE)
        self.assertEqual(result.disposition, "D3_REVIEW_REQUIRED")
        self.assertIsNotNone(result.candidate_image)
        return source, result

    def _assert_contract_blocked(self, source: np.ndarray, decision, blocker: str) -> None:
        before = source.copy()
        result = generate_candidate(source, decision)
        self.assertEqual(result.status, "PROTECTION_BLOCKED")
        self.assertEqual(result.blocker, blocker)
        self.assertFalse(result.modified)
        self.assertIsNone(result.candidate_image)
        self.assertEqual(result.executor, CandidateExecutor.NONE)
        self.assertTrue(np.array_equal(source, before))

    def test_public_d2_execution_surface_has_only_the_gated_entrypoint(self) -> None:
        supported_public_api = {
            "D2_SCHEMA_VERSION",
            "D2_ENGINE_VERSION",
            "D2_SUPPORTED_D1_SCHEMA_VERSION",
            "D2_SUPPORTED_D1_ENGINE_VERSION",
            "D2_SUPPORTED_D1_RULE_VERSION",
            "D2_SUPPORTED_SOURCE_FINGERPRINT_VERSION",
            "CandidateType",
            "CorrectionBudget",
            "CorrectionTarget",
            "CandidateExecutor",
            "generate_candidate",
        }
        self.assertEqual(set(candidate_generation_module.__all__), supported_public_api)
        self.assertTrue(supported_public_api.issubset(set(color_correction_public_api.__all__)))

        private_concrete_constructors = {
            "build_correction_plan",
            "CorrectionPlan",
            "ExecutorAttempt",
            "D2CandidateResult",
        }
        for name in private_concrete_constructors:
            with self.subTest(private=name):
                self.assertFalse(hasattr(color_correction_public_api, name))
                self.assertFalse(hasattr(candidate_generation_module, name))
                self.assertNotIn(name, color_correction_public_api.__all__)
                self.assertNotIn(name, candidate_generation_module.__all__)

        public_callables = {
            name
            for name in candidate_generation_module.__all__
            if callable(getattr(candidate_generation_module, name, None))
        }
        self.assertEqual(
            public_callables,
            {
                "CandidateType",
                "CorrectionBudget",
                "CorrectionTarget",
                "CandidateExecutor",
                "generate_candidate",
            },
        )
        self.assertTrue(inspect.isfunction(candidate_generation_module.generate_candidate))
        self.assertEqual(
            set(CandidateExecutor),
            {
                CandidateExecutor.NONE,
                CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION,
            },
        )
        self.assertFalse(hasattr(candidate_generation_module, "_safe_wb_candidate"))
        self.assertFalse(hasattr(candidate_generation_module, "_cross_affine_candidate"))
        for name in public_callables - {"generate_candidate"}:
            self.assertFalse(is_dataclass(getattr(candidate_generation_module, name)))

        source = np.zeros((2, 2, 3), dtype=np.uint8)
        with self.assertRaises(TypeError):
            candidate_generation_module.generate_candidate(source)

    def test_source_fingerprint_is_private_stable_and_channel_order_canonical(self) -> None:
        source_path, _ = self.dataset["D01_04"]
        rgb = _load_rgb(source_path)
        decision = analyze_color_usability_file(source_path)
        self.assertEqual(decision.source_fingerprint, compute_source_fingerprint(rgb))
        self.assertEqual(
            decision.source_fingerprint,
            compute_source_fingerprint(rgb[..., ::-1], input_order="BGR"),
        )
        self.assertNotIn(str(source_path), decision.source_fingerprint)
        self.assertNotIn("source_fingerprint", json.dumps(build_shadow_record(decision)))
        changed = rgb.copy()
        changed[0, 0, 0] ^= np.uint8(1)
        self.assertNotEqual(decision.source_fingerprint, compute_source_fingerprint(changed))

    def test_mismatched_d1_decision_fails_closed_before_pixel_processing(self) -> None:
        exposure_decision = analyze_color_usability_file(self.dataset["D01_04"][0])
        for sample in ("D01_01", "D01_15"):
            with self.subTest(sample=sample):
                source_path, _ = self.dataset[sample]
                source = _load_rgb(source_path)
                actual = analyze_color_usability_file(source_path)
                self.assertEqual(actual.d1_action, D1Action.KEEP_ORIGINAL)
                self._assert_contract_blocked(source, exposure_decision, "SOURCE_FINGERPRINT_MISMATCH")

    def test_d1_version_gate_rejects_stale_and_missing_contract_fields(self) -> None:
        source_path, _ = self.dataset["D01_04"]
        source = _load_rgb(source_path)
        decision = analyze_color_usability_file(source_path)
        stale_cases = {
            "schema_version": "UNSUPPORTED_D1_SCHEMA_VERSION",
            "engine_version": "UNSUPPORTED_D1_ENGINE_VERSION",
            "rule_version": "UNSUPPORTED_D1_RULE_VERSION",
        }
        for field, blocker in stale_cases.items():
            with self.subTest(stale=field):
                self._assert_contract_blocked(source, replace(decision, **{field: f"stale.{field}"}), blocker)

        self._assert_contract_blocked(
            source,
            replace(decision, schema_version="hdde.color-usability.schema.v1"),
            "UNSUPPORTED_D1_SCHEMA_VERSION",
        )

        self._assert_contract_blocked(
            source,
            replace(decision, source_fingerprint=""),
            "MISSING_SOURCE_FINGERPRINT",
        )
        for field in stale_cases:
            with self.subTest(missing=field):
                values = dict(decision.__dict__)
                values.pop(field)
                self._assert_contract_blocked(
                    source,
                    SimpleNamespace(**values),
                    f"MISSING_D1_{field.removesuffix('_version').upper()}_VERSION",
                )

    def test_d01_04_correct_pair_still_generates_exposure_candidate(self) -> None:
        source_path, _ = self.dataset["D01_04"]
        source = _load_rgb(source_path)
        decision = analyze_color_usability_file(source_path)
        self.assertEqual(decision.d1_action, D1Action.AUTO_CORRECT)
        result = generate_candidate(source, decision)
        self.assertEqual(result.status, "CANDIDATE_READY")
        self.assertEqual(result.plan.candidate_type, CandidateType.AUTO_EXPOSURE_CANDIDATE)
        self.assertEqual(result.executor, CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION)
        self.assertTrue(result.modified)

    def test_keep_original_is_pixel_immutable_and_review_never_auto_accepts(self) -> None:
        for recipe in ("neutral_scene", "normal_dark", "dominant_brand_red"):
            with self.subTest(recipe=recipe):
                image, regions = build_replay_image(recipe)
                decision = analyze_color_usability(image, person_regions=regions)
                self.assertEqual(decision.d1_action, D1Action.KEEP_ORIGINAL)
                result = generate_candidate(image, decision, person_regions=regions)
                self.assertEqual(result.status, "NOT_APPLICABLE")
                self.assertFalse(result.modified)
                self.assertEqual(result.plan.candidate_type, CandidateType.NONE)

        for recipe in ("normal_warm", "normal_cool"):
            with self.subTest(recipe=recipe):
                image, regions = build_replay_image(recipe)
                decision = analyze_color_usability(image, person_regions=regions)
                self.assertEqual(decision.d1_action, D1Action.REVIEW_REQUIRED)
                result = generate_candidate(image, decision, person_regions=regions)
                self.assertEqual(result.plan.candidate_type, CandidateType.COLOR_REVIEW_CANDIDATE)
                self.assertNotIn("ACCEPT", result.disposition)
                self.assertEqual(result.disposition, "D3_REVIEW_REQUIRED")

    def test_local_person_mixed_and_legitimate_warm_protections_block_global_color(self) -> None:
        image, regions = build_replay_image("local_person_led_blue")
        local = generate_candidate(
            image,
            analyze_color_usability(image, person_regions=regions),
            person_regions=regions,
        )
        self.assertEqual(local.status, "PROTECTION_BLOCKED")
        self.assertFalse(local.modified)
        self.assertIn("LOCAL_PERSON_COLOR_RISK", local.plan.protection_profile["blockers"])

        image, regions = build_replay_image("mixed_light")
        mixed = generate_candidate(
            image,
            analyze_color_usability(image, person_regions=regions),
            person_regions=regions,
        )
        self.assertEqual(mixed.status, "PROTECTION_BLOCKED")
        self.assertFalse(mixed.modified)
        self.assertIn("MIXED_COLOR_FIELD", mixed.plan.protection_profile["blockers"])

        warm_path, authority = self.dataset["D01_13"]
        self.assertEqual(authority["interpretation"], "legitimate_warm")
        with Image.open(warm_path) as image:
            warm_source = np.asarray(ImageOps.exif_transpose(image))
        warm = generate_candidate(warm_source, analyze_color_usability_file(warm_path))
        self.assertEqual(warm.status, "NOT_APPLICABLE")
        self.assertFalse(warm.modified)

    def test_d01_02_and_d01_03_have_bounded_real_improvement(self) -> None:
        for sample in ("D01_02", "D01_03"):
            with self.subTest(sample=sample):
                source, mild = self._authoritative_candidate(sample, CorrectionBudget.MILD)
                _, moderate = self._authoritative_candidate(sample, CorrectionBudget.MODERATE)
                source_distance = _lab_distance(self.reference, source)
                mild_distance = _lab_distance(self.reference, mild.candidate_image)
                moderate_distance = _lab_distance(self.reference, moderate.candidate_image)

                self.assertLess(mild_distance, source_distance)
                self.assertLess(moderate_distance, mild_distance)
                self.assertGreater(
                    moderate.after_metrics["mean_rgb_delta"],
                    mild.after_metrics["mean_rgb_delta"],
                )
                self.assertEqual(
                    moderate.executor,
                    CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION,
                )
                self.assertGreater(moderate.after_metrics["neutral_improvement"], 0.2)
                self.assertFalse(moderate.after_metrics["neutral_target_crossed"])
                self.assertLessEqual(moderate.after_metrics["skin_delta_e_mean"], 3.5)
                self.assertLessEqual(moderate.after_metrics["skin_delta_e_p95"], 9.0)
                self.assertLessEqual(moderate.after_metrics["brand_delta_e_mean"], 6.5)
                self.assertLessEqual(moderate.after_metrics["brand_delta_e_p95"], 13.0)
                self.assertLessEqual(moderate.after_metrics["luminance_mae"], 0.75)
                self.assertLessEqual(moderate.after_metrics["shadow_clip_growth"], 0.003)
                self.assertLessEqual(moderate.after_metrics["highlight_clip_growth"], 0.003)

                # Both D1 color directions must reach the same single pixel
                # primitive; no second white-balance implementation is active.
                attempts = {attempt.executor: attempt for attempt in moderate.attempts}
                self.assertEqual(
                    set(attempts),
                    {CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION},
                )
                for attempt in attempts.values():
                    self.assertLess(_lab_distance(self.reference, np.rint(attempt.candidate_rgb01 * 255).astype(np.uint8)), source_distance)

    def test_hidden_rgba_rgb_cannot_change_basic_parameters_or_visible_pixels(self) -> None:
        source_path, _ = self.dataset["D01_03"]
        rgb = _load_rgb(source_path)
        height, width = rgb.shape[:2]
        alpha = np.full((height, width), 255, dtype=np.uint8)
        hidden_columns = max(4, width // 20)
        alpha[:, width - hidden_columns :] = 2
        first = np.dstack((rgb.copy(), alpha))
        second = first.copy()
        hidden = alpha <= 2
        first[..., :3][hidden] = np.array([0, 255, 0], dtype=np.uint8)
        second[..., :3][hidden] = np.array([255, 0, 255], dtype=np.uint8)

        first_decision = analyze_color_usability(first)
        second_decision = analyze_color_usability(second)
        self.assertEqual(first_decision.d1_action, D1Action.REVIEW_REQUIRED)
        self.assertEqual(second_decision.d1_action, D1Action.REVIEW_REQUIRED)
        first_result = generate_candidate(first, first_decision)
        second_result = generate_candidate(second, second_decision)
        self.assertEqual(first_result.executor, second_result.executor)
        first_basic = next(
            attempt
            for attempt in first_result.attempts
            if attempt.executor == CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION
        )
        second_basic = next(
            attempt
            for attempt in second_result.attempts
            if attempt.executor == CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION
        )
        self.assertEqual(first_basic.safety_status, second_basic.safety_status)
        self.assertEqual(first_basic.parameters, second_basic.parameters)
        self.assertEqual(first_basic.before_metrics, second_basic.before_metrics)
        self.assertEqual(first_basic.after_metrics, second_basic.after_metrics)
        visible = alpha > 2
        self.assertTrue(
            np.array_equal(
                first_basic.candidate_rgb01[visible],
                second_basic.candidate_rgb01[visible],
            )
        )
        self.assertTrue(
            np.array_equal(
                first_result.candidate_image[..., :3][visible],
                second_result.candidate_image[..., :3][visible],
            )
        )

    def test_exposure_auto_is_independent_bounded_and_preserves_color(self) -> None:
        for recipe, direction in (("too_dark", 1), ("too_bright", -1)):
            with self.subTest(recipe=recipe):
                image, regions = build_replay_image(recipe)
                pixels = np.rint(image * 255).astype(np.uint8)
                decision = analyze_color_usability(pixels, person_regions=regions)
                self.assertEqual(decision.d1_action, D1Action.AUTO_CORRECT)
                mild = generate_candidate(pixels, decision, person_regions=regions, budget_cap=CorrectionBudget.MILD)
                moderate = generate_candidate(pixels, decision, person_regions=regions)
                for result in (mild, moderate):
                    self.assertEqual(result.status, "CANDIDATE_READY")
                    self.assertEqual(result.plan.candidate_type, CandidateType.AUTO_EXPOSURE_CANDIDATE)
                    self.assertEqual(
                        result.executor,
                        CandidateExecutor.DETERMINISTIC_BASIC_CORRECTION,
                    )
                    self.assertEqual(result.disposition, "D3_AUDIT_REQUIRED")
                    self.assertLessEqual(result.after_metrics["lab_ab_delta_mean"], 1.50)
                    self.assertLessEqual(result.after_metrics["lab_ab_delta_p95"], 4.00)
                    self.assertLessEqual(result.after_metrics["shadow_clip_growth"], 0.002)
                    self.assertLessEqual(result.after_metrics["highlight_clip_growth"], 0.002)
                    delta = result.after_metrics["luminance_p50"] - result.before_metrics["luminance_p50"]
                    minimum = 0.012 if result.plan.correction_budget == CorrectionBudget.MILD else 0.02
                    self.assertGreater(direction * delta, minimum)
                    values = result.executor_parameters["values"]
                    self.assertEqual(set(values), {
                        "exposure", "brightness", "contrast", "temperature", "tint",
                        "saturation", "vibrance", "highlights", "shadows",
                    })
                    self.assertNotEqual(values["exposure"], 0.0)
                    self.assertTrue(all(
                        value == 0.0
                        for name, value in values.items()
                        if name != "exposure"
                    ))
                self.assertGreater(
                    moderate.after_metrics["mean_rgb_delta"],
                    mild.after_metrics["mean_rgb_delta"],
                )

    def test_dtype_order_and_record_contract_are_explicit(self) -> None:
        image, regions = build_replay_image("too_dark")
        rgb8 = np.rint(image * 255).astype(np.uint8)
        decision = analyze_color_usability(rgb8, person_regions=regions)
        bgr = rgb8[..., ::-1]
        result = generate_candidate(bgr, decision, input_order="BGR", person_regions=regions)
        self.assertEqual(result.candidate_image.dtype, bgr.dtype)
        self.assertEqual(result.candidate_image.shape, bgr.shape)
        record = result.to_record()
        required = {
            "D1_ACTION", "CANDIDATE_TYPE", "CORRECTION_TARGET", "CORRECTION_BUDGET",
            "EXECUTOR", "EXECUTOR_PARAMETERS", "BEFORE_METRICS", "AFTER_METRICS",
        }
        self.assertTrue(required.issubset(record))
        self.assertNotIn("image", " ".join(record).lower())
        self.assertEqual(record["DISPOSITION"], "D3_AUDIT_REQUIRED")

        source_path, _ = self.dataset["D01_02"]
        source8 = _load_rgb(source_path)
        source16 = source8.astype(np.uint16) * 257
        unsupported = generate_candidate(source16, analyze_color_usability(source16))
        self.assertEqual(unsupported.status, "PROTECTION_BLOCKED")
        self.assertFalse(unsupported.modified)
        self.assertEqual(unsupported.blocker, "UNSUPPORTED_COLOR_EXECUTOR_BIT_DEPTH")


if __name__ == "__main__":
    unittest.main()
