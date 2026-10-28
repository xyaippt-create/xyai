from __future__ import annotations

import inspect
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from engine.hd_core import candidate_framework as framework
from engine.hd_core.candidate_framework import (
    ACCEPTED,
    CONTROL_FRAMEWORK,
    E102EvaluationContext,
    EVALUATION_INELIGIBLE,
    EXECUTION_FAILED,
    OUTPUT_INVALID,
    PRODUCT,
    QUALITY_REJECTED,
    REVIEW,
    SAFETY_REJECTED,
    CandidateDefinition,
    CandidateFrameworkError,
    build_candidate_identity,
    build_comparison_surface,
    build_run_identity,
    failure_test_candidate,
    identity_test_candidate,
    invalid_output_test_candidate,
    resolve_candidate_state,
    run_4k_candidate,
    sha256_file,
)
from tools.experiments.e4k_02_candidate_framework import (
    OUTPUT_ROOT as E4K_02_OUTPUT_ROOT,
    validate_artifact,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
E1_01_MANIFEST = REPO_ROOT / "artifacts" / "e1_01_real_information_baseline_v1" / "manifest.json"


class CandidateFrameworkTest(unittest.TestCase):
    def _definition(self, **changes: object) -> CandidateDefinition:
        values: dict[str, object] = {
            "algorithm_id": "IDENTITY_TEST_CANDIDATE",
            "algorithm_version": "V1",
            "parameters": {"operation": "BASELINE_BYTE_IDENTITY"},
            "backend_identity": "PYTHON_SHUTIL",
            "precision_identity": "BYTE_EXACT",
        }
        values.update(changes)
        return CandidateDefinition(**values)  # type: ignore[arg-type]

    def _product_definition(self, **changes: object) -> CandidateDefinition:
        values: dict[str, object] = {
            "algorithm_id": "TEST_REAL_MODEL_ADAPTER",
            "algorithm_version": "V1",
            "parameters": {"tile": 64, "overlap": 8},
            "backend_identity": "PYTORCH_RESEARCH_RUNTIME",
            "precision_identity": "FP32",
            "candidate_class": PRODUCT,
            "model_id": "TEST_REAL_MODEL",
            "model_version": "REVISION_1",
            "model_sha256": "1" * 64,
            "control_fixture_only": False,
        }
        values.update(changes)
        return CandidateDefinition(**values)  # type: ignore[arg-type]

    def _fixture(self, root: Path, *, alpha: bool = True) -> tuple[Path, Path]:
        source = root / "source.png"
        baseline = root / "baseline.png"
        if alpha:
            rgba = np.zeros((12, 16, 4), dtype=np.uint8)
            rgba[..., :3] = (30, 80, 140)
            rgba[..., 3] = np.arange(16, dtype=np.uint8)[None, :] * 16
            Image.fromarray(rgba, "RGBA").save(source)
            Image.fromarray(np.repeat(np.repeat(rgba, 2, axis=0), 2, axis=1), "RGBA").save(baseline)
        else:
            Image.new("RGB", (16, 12), (30, 80, 140)).save(source)
            Image.new("RGB", (32, 24), (30, 80, 140)).save(baseline)
        return source, baseline

    def _run(self, root: Path, executor=identity_test_candidate, **kwargs: object) -> dict[str, object]:
        source, baseline = self._fixture(root)
        return run_4k_candidate(
            source,
            root / "runs",
            definition=self._definition(),
            executor=executor,
            baseline_path=baseline,
            execution_nonce="TEST_RUN",
            **kwargs,
        )

    def test_candidate_interface_valid(self) -> None:
        candidate_id, contract = build_candidate_identity(self._definition())
        self.assertTrue(candidate_id.startswith("candidate_"))
        self.assertEqual(contract["candidate_class"], CONTROL_FRAMEWORK)
        self.assertTrue(contract["control_fixture_only"])
        self.assertTrue(contract["not_product_candidate"])

    def test_candidate_interface_missing_identity(self) -> None:
        with self.assertRaisesRegex(CandidateFrameworkError, "ALGORITHM_ID_MISSING"):
            build_candidate_identity(self._definition(algorithm_id=""))

    def test_candidate_interface_invalid_parameters(self) -> None:
        with self.assertRaisesRegex(CandidateFrameworkError, "PARAMETERS_NOT_CANONICAL_JSON"):
            build_candidate_identity(self._definition(parameters={"invalid": float("nan")}))

    def test_same_contract_same_id(self) -> None:
        self.assertEqual(self._definition().candidate_id, self._definition().candidate_id)

    def test_product_candidate_identity_is_explicit_and_stable(self) -> None:
        candidate_id, contract = build_candidate_identity(self._product_definition())
        self.assertEqual(candidate_id, self._product_definition().candidate_id)
        self.assertEqual(contract["candidate_class"], PRODUCT)
        self.assertFalse(contract["control_fixture_only"])
        self.assertFalse(contract["not_product_candidate"])
        self.assertFalse(contract["not_enhancement_algorithm"])

    def test_product_model_sha_change_creates_new_id(self) -> None:
        self.assertNotEqual(
            self._product_definition().candidate_id,
            self._product_definition(model_sha256="2" * 64).candidate_id,
        )

    def test_product_identity_requires_real_model_sha(self) -> None:
        with self.assertRaisesRegex(
            CandidateFrameworkError, "PRODUCT_MODEL_SHA256_INVALID"
        ):
            build_candidate_identity(self._product_definition(model_sha256="NONE"))

    def test_parameter_change_creates_new_id(self) -> None:
        self.assertNotEqual(
            self._definition().candidate_id,
            self._definition(parameters={"operation": "DIFFERENT"}).candidate_id,
        )

    def test_algorithm_version_change_creates_new_id(self) -> None:
        self.assertNotEqual(
            self._definition().candidate_id,
            self._definition(algorithm_version="V2").candidate_id,
        )

    def test_backend_change_creates_new_id(self) -> None:
        self.assertNotEqual(
            self._definition().candidate_id,
            self._definition(backend_identity="OTHER_BACKEND").candidate_id,
        )

    def test_precision_change_creates_new_id(self) -> None:
        self.assertNotEqual(
            self._definition().candidate_id,
            self._definition(precision_identity="FP32").candidate_id,
        )

    def test_candidate_id_is_separate_from_run_id(self) -> None:
        candidate_id = self._definition().candidate_id
        first, first_contract = build_run_identity(
            candidate_id=candidate_id,
            source_sha256="a" * 64,
            baseline_sha256="b" * 64,
            runtime_context={"executor": "test"},
            execution_nonce="FIRST",
        )
        second, _ = build_run_identity(
            candidate_id=candidate_id,
            source_sha256="a" * 64,
            baseline_sha256="b" * 64,
            runtime_context={"executor": "test"},
            execution_nonce="SECOND",
        )
        self.assertNotEqual(candidate_id, first)
        self.assertNotEqual(first, second)
        self.assertEqual(first_contract["candidate_id"], candidate_id)

    def test_identity_candidate_run_and_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, baseline = self._fixture(root)
            source_before = sha256_file(source)
            baseline_before = sha256_file(baseline)
            result = run_4k_candidate(
                source,
                root / "runs",
                definition=self._definition(),
                executor=identity_test_candidate,
                baseline_path=baseline,
                execution_nonce="IDENTITY",
            )
            self.assertEqual(result["execution_status"], "COMPLETED")
            self.assertEqual(result["candidate_state"], EVALUATION_INELIGIBLE)
            self.assertEqual(sha256_file(source), source_before)
            self.assertEqual(sha256_file(baseline), baseline_before)
            candidate = Path(str(result["candidate_reference"]))
            self.assertTrue(candidate.is_file())
            self.assertNotEqual(candidate.resolve(), baseline.resolve())
            self.assertEqual(result["candidate_sha256"], baseline_before)

    def test_executor_receives_only_isolated_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, baseline = self._fixture(root)
            source_before = sha256_file(source)
            baseline_before = sha256_file(baseline)

            def mutate_snapshots(request: framework.CandidateExecutionRequest) -> None:
                request.source_path.write_bytes(b"isolated-source-mutated")
                request.baseline_path.write_bytes(b"isolated-baseline-mutated")
                request.output_path.write_bytes(b"invalid")

            result = run_4k_candidate(
                source,
                root / "runs",
                definition=self._definition(),
                executor=mutate_snapshots,
                baseline_path=baseline,
                execution_nonce="MUTATE_SNAPSHOTS",
            )
            self.assertEqual(result["candidate_state"], OUTPUT_INVALID)
            self.assertEqual(sha256_file(source), source_before)
            self.assertEqual(sha256_file(baseline), baseline_before)

    def test_failure_candidate_exception_has_execution_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self._run(Path(temporary), failure_test_candidate)
            self.assertEqual(result["candidate_state"], EXECUTION_FAILED)
            self.assertEqual(result["fallback_kind"], "EXECUTION_FALLBACK")
            self.assertEqual(result["safe_reference_selected"], "BASELINE")
            self.assertIsNone(result["candidate_reference"])

    def test_invalid_output_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self._run(Path(temporary), invalid_output_test_candidate)
            self.assertEqual(result["candidate_state"], OUTPUT_INVALID)
            self.assertFalse(result["output_validation"]["checks"]["decode_success"])
            self.assertEqual(result["fallback_kind"], "EXECUTION_FALLBACK")

    def test_matching_geometry_is_comparison_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, baseline = self._fixture(root)
            candidate = root / "candidate.png"
            shutil.copyfile(baseline, candidate)
            surface = build_comparison_surface(baseline, candidate, self._definition())
            self.assertEqual(surface["status"], "ELIGIBLE")
            self.assertTrue(all(surface["checks"].values()))

    def test_wrong_dimension_is_evaluation_ineligible_without_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def wrong_dimension(request: framework.CandidateExecutionRequest) -> None:
                Image.new("RGBA", (7, 5), (1, 2, 3, 4)).save(request.output_path)

            result = self._run(root, wrong_dimension)
            self.assertEqual(result["candidate_state"], EVALUATION_INELIGIBLE)
            self.assertIn("same_target_dimensions", result["comparison_surface"]["failures"])
            self.assertFalse(result["comparison_surface"]["implicit_repair_performed"])

    def test_wrong_orientation_is_evaluation_ineligible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def wrong_orientation(request: framework.CandidateExecutionRequest) -> None:
                with Image.open(request.baseline_path) as opened:
                    opened.load()
                    image = opened.copy()
                exif = Image.Exif()
                exif[274] = 6
                image.save(request.output_path, format="PNG", exif=exif)

            result = self._run(root, wrong_orientation)
            self.assertEqual(result["candidate_state"], EVALUATION_INELIGIBLE)
            self.assertIn("same_orientation", result["comparison_surface"]["failures"])

    def test_invalid_alpha_contract_is_evaluation_ineligible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def wrong_alpha(request: framework.CandidateExecutionRequest) -> None:
                with Image.open(request.baseline_path) as opened:
                    pixels = np.asarray(opened.convert("RGBA"), dtype=np.uint8).copy()
                pixels[0, 0, 3] ^= 255
                Image.fromarray(pixels, "RGBA").save(request.output_path)

            result = self._run(root, wrong_alpha)
            self.assertEqual(result["candidate_state"], EVALUATION_INELIGIBLE)
            self.assertIn("compatible_alpha_contract", result["comparison_surface"]["failures"])

    def test_normalization_declaration_is_in_candidate_identity(self) -> None:
        declared = self._definition(
            normalization={
                "version": "CANDIDATE_NORMALIZATION_DECLARATION_V1",
                "operations": [{"name": "EXPLICIT_ALPHA_REATTACH", "version": "V1"}],
                "implicit_resize": False,
                "implicit_crop_or_padding": False,
                "implicit_color_conversion": False,
            }
        )
        _, contract = build_candidate_identity(declared)
        self.assertEqual(contract["normalization"]["operations"][0]["name"], "EXPLICIT_ALPHA_REATTACH")
        self.assertNotEqual(declared.candidate_id, self._definition().candidate_id)

    def test_no_processing_needed_bypasses_baseline_and_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "already_4k.png"
            Image.new("RGB", (3840, 1), (10, 20, 30)).save(source)
            calls: list[str] = []

            def should_not_run(_request: framework.CandidateExecutionRequest) -> None:
                calls.append("called")

            result = run_4k_candidate(
                source,
                root / "runs",
                definition=self._definition(),
                executor=should_not_run,
                execution_nonce="BYPASS",
            )
            self.assertEqual(calls, [])
            self.assertEqual(result["candidate_execution"], "NOT_APPLICABLE")
            self.assertEqual(result["baseline_artifact"], "NONE")
            self.assertEqual(result["candidate_fallback"], "NOT_APPLICABLE")

    def test_e1_02_is_only_replay_authority(self) -> None:
        source = inspect.getsource(framework._e1_02_spec_and_result)
        self.assertIn("e1_02.compute_replay_identity", source)
        self.assertNotIn("_replay_contract(", source)
        self.assertEqual(framework.REPLAY_BINDING_AUTHORITY, "E1_02_REPLAY_BINDING_V1")

    def test_actual_source_hash_mismatch_rejected(self) -> None:
        manifest = json.loads(E1_01_MANIFEST.read_text(encoding="utf-8"))
        case = next(item for item in manifest["cases"] if item["case_id"] == "E1C015")
        baseline = REPO_ROOT / case["safe_base"]["path"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrong_source = root / "wrong_source.png"
            Image.new("RGBA", (320, 180), (255, 0, 255, 255)).save(wrong_source)
            result = run_4k_candidate(
                wrong_source,
                root / "runs",
                definition=self._definition(),
                executor=identity_test_candidate,
                baseline_path=baseline,
                e1_02_context=E102EvaluationContext(E1_01_MANIFEST, "E1C015"),
                execution_nonce="ACTUAL_SOURCE_HASH_MISMATCH_REJECTED",
            )
        self.assertNotEqual(result["source_sha256"], case["input"]["sha256"])
        self.assertEqual(result["candidate_state"], EVALUATION_INELIGIBLE)
        self.assertEqual(result["actual_source_sha256"], result["source_sha256"])
        self.assertEqual(result["actual_run_binding_status"], "FAIL")
        self.assertFalse(result["source_binding_match"])
        self.assertTrue(result["baseline_binding_match"])
        self.assertIsNone(result["e1_02_result"])
        self.assertEqual(result["quality_gain_status"], "NOT_EVALUATED")
        self.assertEqual(result["delivery_status"], "NOT_EVALUATED")

    def test_actual_baseline_hash_mismatch_rejected(self) -> None:
        manifest = json.loads(E1_01_MANIFEST.read_text(encoding="utf-8"))
        case = next(item for item in manifest["cases"] if item["case_id"] == "E1C015")
        source = REPO_ROOT / case["input"]["path"]
        official_baseline = REPO_ROOT / case["safe_base"]["path"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with Image.open(official_baseline) as opened:
                pixels = np.asarray(opened.convert("RGBA"), dtype=np.uint8).copy()
            pixels[0, 0, 0] ^= 1
            wrong_baseline = root / "wrong_baseline.png"
            Image.fromarray(pixels, "RGBA").save(wrong_baseline)
            result = run_4k_candidate(
                source,
                root / "runs",
                definition=self._definition(),
                executor=identity_test_candidate,
                baseline_path=wrong_baseline,
                e1_02_context=E102EvaluationContext(E1_01_MANIFEST, "E1C015"),
                execution_nonce="ACTUAL_BASELINE_HASH_MISMATCH_REJECTED",
            )
        self.assertNotEqual(result["baseline_sha256"], case["safe_base"]["sha256"])
        self.assertEqual(result["candidate_state"], EVALUATION_INELIGIBLE)
        self.assertEqual(result["actual_baseline_sha256"], result["baseline_sha256"])
        self.assertEqual(result["actual_run_binding_status"], "FAIL")
        self.assertTrue(result["source_binding_match"])
        self.assertFalse(result["baseline_binding_match"])
        self.assertIsNone(result["e1_02_result"])
        self.assertEqual(result["quality_gain_status"], "NOT_EVALUATED")
        self.assertEqual(result["delivery_status"], "NOT_EVALUATED")

    def test_source_mismatch_does_not_call_quality_advancement(self) -> None:
        manifest = json.loads(E1_01_MANIFEST.read_text(encoding="utf-8"))
        case = next(item for item in manifest["cases"] if item["case_id"] == "E1C015")
        baseline = REPO_ROOT / case["safe_base"]["path"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrong_source = root / "wrong_source.png"
            Image.new("RGBA", (320, 180), (240, 10, 120, 255)).save(wrong_source)
            with patch.object(framework, "_e1_02_spec_and_result") as e1_02_call:
                result = run_4k_candidate(
                    wrong_source,
                    root / "runs",
                    definition=self._definition(),
                    executor=identity_test_candidate,
                    baseline_path=baseline,
                    e1_02_context=E102EvaluationContext(E1_01_MANIFEST, "E1C015"),
                    execution_nonce="SOURCE_MISMATCH_NO_QUALITY_ADVANCEMENT",
                )
        e1_02_call.assert_not_called()
        self.assertEqual(result["candidate_state"], EVALUATION_INELIGIBLE)
        self.assertEqual(result["fallback_kind"], "EVALUATION_INELIGIBLE")
        self.assertEqual(result["safe_reference_selected"], "BASELINE")
        self.assertFalse(result["candidate_accepted"])
        self.assertFalse(result["candidate_rejected"])

    def test_baseline_mismatch_does_not_call_quality_advancement(self) -> None:
        manifest = json.loads(E1_01_MANIFEST.read_text(encoding="utf-8"))
        case = next(item for item in manifest["cases"] if item["case_id"] == "E1C015")
        source = REPO_ROOT / case["input"]["path"]
        official_baseline = REPO_ROOT / case["safe_base"]["path"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with Image.open(official_baseline) as opened:
                pixels = np.asarray(opened.convert("RGBA"), dtype=np.uint8).copy()
            pixels[0, 0, 1] ^= 1
            wrong_baseline = root / "wrong_baseline.png"
            Image.fromarray(pixels, "RGBA").save(wrong_baseline)
            with patch.object(framework, "_e1_02_spec_and_result") as e1_02_call:
                result = run_4k_candidate(
                    source,
                    root / "runs",
                    definition=self._definition(),
                    executor=identity_test_candidate,
                    baseline_path=wrong_baseline,
                    e1_02_context=E102EvaluationContext(E1_01_MANIFEST, "E1C015"),
                    execution_nonce="BASELINE_MISMATCH_NO_QUALITY_ADVANCEMENT",
                )
        e1_02_call.assert_not_called()
        self.assertEqual(result["candidate_state"], EVALUATION_INELIGIBLE)
        self.assertEqual(result["fallback_kind"], "EVALUATION_INELIGIBLE")
        self.assertEqual(result["safe_reference_selected"], "BASELINE")
        self.assertFalse(result["candidate_accepted"])
        self.assertFalse(result["candidate_rejected"])

    def test_candidate_result_records_actual_binding_facts(self) -> None:
        manifest = json.loads(E1_01_MANIFEST.read_text(encoding="utf-8"))
        case = next(item for item in manifest["cases"] if item["case_id"] == "E1C015")
        source = REPO_ROOT / case["input"]["path"]
        baseline = REPO_ROOT / case["safe_base"]["path"]
        e1_spec = {
            "candidate_class": "CONTROL_ZERO",
            "replay_identity": "test-replay",
        }
        e1_result = {
            "evaluation_status": "COMPLETE",
            "replay_identity": "test-replay",
            "safety_results": {"status": "PASS"},
            "quality_gain_status": "QUALITY_GAIN_NOT_PROVEN",
            "delivery_status": "REVIEW",
            "mandatory_gate_complete": False,
            "evidence_refs": {},
        }
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            framework,
            "_e1_02_spec_and_result",
            return_value=(e1_spec, e1_result),
        ):
            result = run_4k_candidate(
                source,
                Path(temporary) / "runs",
                definition=self._definition(),
                executor=identity_test_candidate,
                baseline_path=baseline,
                e1_02_context=E102EvaluationContext(E1_01_MANIFEST, "E1C015"),
                execution_nonce="CANDIDATE_RESULT_BINDING_FACTS",
            )
        self.assertEqual(result["actual_source_sha256"], case["input"]["sha256"])
        self.assertEqual(
            result["actual_baseline_sha256"], case["safe_base"]["sha256"]
        )
        self.assertEqual(
            result["expected_source_binding_sha256"], case["input"]["sha256"]
        )
        self.assertEqual(
            result["expected_baseline_binding_sha256"],
            case["safe_base"]["sha256"],
        )
        self.assertTrue(result["source_binding_match"])
        self.assertTrue(result["baseline_binding_match"])
        self.assertEqual(result["actual_run_binding_status"], "PASS")
        self.assertEqual(
            result["actual_run_binding_reason"],
            "SOURCE_AND_BASELINE_MATCH_E1_CASE",
        )

    def test_real_e1_02_integration_for_control_framework(self) -> None:
        manifest = json.loads(E1_01_MANIFEST.read_text(encoding="utf-8"))
        case = next(item for item in manifest["cases"] if item["case_id"] == "E1C015")
        source = REPO_ROOT / case["input"]["path"]
        baseline = REPO_ROOT / case["safe_base"]["path"]
        with tempfile.TemporaryDirectory() as temporary:
            result = run_4k_candidate(
                source,
                Path(temporary) / "runs",
                definition=self._definition(),
                executor=identity_test_candidate,
                baseline_path=baseline,
                e1_02_context=E102EvaluationContext(E1_01_MANIFEST, "E1C015"),
                execution_nonce="REAL_E1_02_INTEGRATION",
            )
        self.assertEqual(result["candidate_state"], REVIEW)
        self.assertEqual(result["e1_02_candidate_class"], "CONTROL_ZERO")
        self.assertEqual(result["e1_02_result"]["evaluation_status"], "COMPLETE")
        self.assertEqual(result["e1_02_result"]["eligibility"]["status"], "ELIGIBLE")
        self.assertEqual(result["e1_02_result"]["eligibility"]["replay_binding_gate"], "PASS")
        self.assertEqual(result["safety_status"], "PASS")
        self.assertEqual(result["quality_gain_status"], "QUALITY_GAIN_NOT_PROVEN")
        self.assertEqual(result["delivery_status"], "REVIEW")
        self.assertEqual(result["actual_run_binding_status"], "PASS")
        self.assertTrue(result["source_binding_match"])
        self.assertTrue(result["baseline_binding_match"])
        self.assertEqual(
            result["actual_source_sha256"],
            result["e1_02_spec"]["source_binding_sha256"],
        )
        self.assertEqual(
            result["actual_baseline_sha256"],
            result["e1_02_spec"]["baseline_binding_sha256"],
        )
        self.assertEqual(
            result["e1_02_replay_identity"],
            result["e1_02_spec"]["replay_identity"],
        )
        self.assertFalse(result["candidate_accepted"])
        self.assertFalse(result["candidate_rejected"])

    def test_state_machine_all_required_states(self) -> None:
        base = {
            "execution_status": "COMPLETED",
            "output_validation_status": "PASS",
            "comparison_surface_status": "ELIGIBLE",
        }
        self.assertEqual(
            resolve_candidate_state(**{**base, "execution_status": "FAILED"}, e1_02_result=None),
            EXECUTION_FAILED,
        )
        self.assertEqual(
            resolve_candidate_state(**{**base, "output_validation_status": "FAIL"}, e1_02_result=None),
            OUTPUT_INVALID,
        )
        self.assertEqual(
            resolve_candidate_state(**{**base, "comparison_surface_status": "INELIGIBLE"}, e1_02_result=None),
            EVALUATION_INELIGIBLE,
        )
        self.assertEqual(
            resolve_candidate_state(**base, e1_02_result=self._e1_result(safety="FAIL")),
            SAFETY_REJECTED,
        )
        self.assertEqual(
            resolve_candidate_state(
                **base,
                e1_02_result=self._e1_result(quality="QUALITY_GAIN_REJECTED"),
            ),
            QUALITY_REJECTED,
        )
        self.assertEqual(
            resolve_candidate_state(**base, e1_02_result=self._e1_result()),
            REVIEW,
        )
        self.assertEqual(
            resolve_candidate_state(
                **base,
                e1_02_result=self._e1_result(
                    quality="QUALITY_GAIN_PROVEN", delivery="PASS", mandatory=True
                ),
            ),
            ACCEPTED,
        )

    def test_fallback_and_safe_reference_semantics_all_states(self) -> None:
        expected = {
            EXECUTION_FAILED: ("BASELINE", "EXECUTION_FALLBACK", False, True),
            OUTPUT_INVALID: ("BASELINE", "EXECUTION_FALLBACK", False, True),
            EVALUATION_INELIGIBLE: (
                "BASELINE",
                "EVALUATION_INELIGIBLE",
                False,
                False,
            ),
            SAFETY_REJECTED: ("BASELINE", "SAFETY_REJECTION", False, True),
            QUALITY_REJECTED: ("BASELINE", "QUALITY_REJECTION", False, True),
            REVIEW: ("BASELINE", "REVIEW_SAFE_REFERENCE", False, False),
            ACCEPTED: ("CANDIDATE", "NOT_APPLICABLE", True, False),
        }
        for state, values in expected.items():
            with self.subTest(state=state):
                resolved = framework._safe_resolution(state)
                self.assertEqual(
                    (
                        resolved["safe_reference_selected"],
                        resolved["fallback_kind"],
                        resolved["candidate_accepted"],
                        resolved["candidate_rejected"],
                    ),
                    values,
                )

    @staticmethod
    def _e1_result(
        *,
        safety: str = "PASS",
        quality: str = "QUALITY_GAIN_NOT_PROVEN",
        delivery: str = "REVIEW",
        mandatory: bool = False,
    ) -> dict[str, object]:
        return {
            "evaluation_status": "COMPLETE",
            "safety_results": {"status": safety},
            "quality_gain_status": quality,
            "delivery_status": delivery,
            "mandatory_gate_complete": mandatory,
        }

    def test_unrecognized_candidate_class_is_rejected(self) -> None:
        for candidate_class in ("CONTRACT_TEST_ONLY", "CONTROL_ORACLE"):
            with self.subTest(candidate_class=candidate_class), self.assertRaisesRegex(
                CandidateFrameworkError, "CANDIDATE_CLASS_NOT_ALLOWED"
            ):
                build_candidate_identity(self._definition(candidate_class=candidate_class))

    def test_formal_and_gate_sources_match_frozen_predevelopment_hashes(self) -> None:
        expected = {
            "engine/image_processing_routing/four_k_v1.py": "7741e65a0aef3a9e24caa58ba75bc391cb0040b139802802a4670f908e469e65",
            "main.py": "c1a36512f8a2b8b487a039ec306c240c242f1a0b1aa87430e657dab254ad6db8",
            "product_version.json": "0517884da7197275f505cb21acee3dfe239f88d9f810da9495ef747f5a94bb36",
            "tools/experiments/e1_01_real_information_baseline.py": "2741c5b7b10524167db436a39a331323f76bc20ec9ba167b79abd36b5c8754a6",
            "tools/experiments/e1_02_quality_delivery_gate.py": "222f840fce1eac0c13c02555b51e1f00c6d31b79d5844cb88e2e6920fa590027",
        }
        for relative, digest in expected.items():
            with self.subTest(path=relative):
                self.assertEqual(sha256_file(REPO_ROOT / relative), digest)

    def test_fixed_e4k_02_artifact_validates(self) -> None:
        result = validate_artifact(E4K_02_OUTPUT_ROOT)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["statistics"]["e1_01_cases_replayed"], 16)
        self.assertEqual(result["statistics"]["candidate_id_count"], 1)
        self.assertEqual(result["statistics"]["run_id_count"], 16)
        self.assertEqual(result["product_candidate_quality_gain_proven_count"], 0)
        self.assertEqual(result["real_4k_quality_gain"], "NOT_PROVEN")
        self.assertEqual(result["ACTUAL_RUN_BINDING_GATE"], "PASS")
        self.assertEqual(result["SOURCE_BINDING_MISMATCH_COUNT"], 0)
        self.assertEqual(result["BASELINE_BINDING_MISMATCH_COUNT"], 0)
        self.assertEqual(result["CORRECT_PAIR_REPLAY_COUNT"], 16)
        self.assertEqual(result["JSON_PARSE_FAILURES"], 0)
        self.assertEqual(result["REFERENCE_MISSING"], 0)
        self.assertEqual(result["STATISTICS_CONSISTENT"], "YES")

    def _copied_artifact_contract(self, root: Path) -> list[Path]:
        manifest = json.loads(
            (E4K_02_OUTPUT_ROOT / "framework_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        destination = root / "candidate_results"
        destination.mkdir(parents=True)
        copied: list[Path] = []
        for entry in manifest["case_results"]:
            source_path = REPO_ROOT / entry["candidate_result_path"]
            target = destination / source_path.name
            shutil.copyfile(source_path, target)
            entry["candidate_result_path"] = str(target.resolve())
            copied.append(target)
        (root / "framework_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return copied

    def test_artifact_validator_detects_source_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copied = self._copied_artifact_contract(root)
            result = json.loads(copied[0].read_text(encoding="utf-8"))
            result["actual_source_sha256"] = "0" * 64
            copied[0].write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            validation = validate_artifact(root)
        self.assertEqual(validation["status"], "BLOCKED")
        self.assertEqual(validation["ACTUAL_RUN_BINDING_GATE"], "FAIL")
        self.assertEqual(validation["SOURCE_BINDING_MISMATCH_COUNT"], 1)
        self.assertEqual(validation["BASELINE_BINDING_MISMATCH_COUNT"], 0)

    def test_artifact_validator_detects_baseline_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copied = self._copied_artifact_contract(root)
            result = json.loads(copied[0].read_text(encoding="utf-8"))
            result["actual_baseline_sha256"] = "0" * 64
            copied[0].write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            validation = validate_artifact(root)
        self.assertEqual(validation["status"], "BLOCKED")
        self.assertEqual(validation["ACTUAL_RUN_BINDING_GATE"], "FAIL")
        self.assertEqual(validation["SOURCE_BINDING_MISMATCH_COUNT"], 0)
        self.assertEqual(validation["BASELINE_BINDING_MISMATCH_COUNT"], 1)

    def test_fixed_artifact_declares_no_real_model_work(self) -> None:
        manifest = json.loads(
            (E4K_02_OUTPUT_ROOT / "framework_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["status"], "PASS")
        self.assertEqual(manifest["e1_01_cases_replayed"], 16)
        self.assertEqual(manifest["model_plan"]["experimental_model"], "NONE")
        self.assertFalse(manifest["model_plan"]["model_download"])
        self.assertFalse(manifest["model_plan"]["model_inference_run"])
        self.assertFalse(manifest["e1_02_candidate_class_adapter"]["e1_02_gate_semantics_changed"])


if __name__ == "__main__":
    unittest.main()
