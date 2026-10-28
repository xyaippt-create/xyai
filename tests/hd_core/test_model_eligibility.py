from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from engine.hd_core.model_eligibility import (
    AUTHORIZED_DOWNLOAD,
    BLOCKED,
    PASS,
    ModelEligibilityRecord,
    evaluate_pre_download,
    finalize_eligibility,
    sha256_file,
)


class ModelEligibilityTest(unittest.TestCase):
    def record(self) -> ModelEligibilityRecord:
        return ModelEligibilityRecord(
            model_id="TEST_MODEL",
            model_version="V1",
            model_role="PRIMARY",
            source_url_or_provider="https://example.invalid/official",
            source_status=PASS,
            source_evidence="OFFICIAL",
            code_license_reference="https://example.invalid/code-license",
            code_license_status=PASS,
            weight_license_reference="https://example.invalid/weight-license",
            weight_license_status=PASS,
            commercial_use_boundary="PERMITTED_WITH_CONDITIONS",
            redistribution_boundary="PERMITTED_WITH_CONDITIONS",
            model_file="model.bin",
            runtime_requirement="TEST",
            hardware_requirement="CPU",
            memory_requirement="1_BYTE",
            backend="TEST_BACKEND",
            precision="FP32",
            input_contract={"color": "RGB"},
            output_contract={"scale": 4},
            determinism_status="TEST_REQUIRED",
            onnx_feasibility="UNKNOWN",
            openvino_feasibility="UNKNOWN",
            expected_processing_cost="TEST",
        )

    def test_unverified_source_blocked(self) -> None:
        result = evaluate_pre_download(
            replace(self.record(), source_status="UNKNOWN")
        )
        self.assertEqual(result["model_eligibility"], BLOCKED)
        self.assertIn("UNVERIFIED_SOURCE", result["block_reasons"])

    def test_license_unknown_blocked(self) -> None:
        result = evaluate_pre_download(
            replace(
                self.record(),
                weight_license_status="UNKNOWN",
                commercial_use_boundary="UNCLEAR",
            )
        )
        self.assertEqual(result["model_eligibility"], BLOCKED)
        self.assertIn("WEIGHT_LICENSE_NOT_CONFIRMED", result["block_reasons"])

    def test_source_license_pass_authorizes_only_download(self) -> None:
        result = evaluate_pre_download(self.record())
        self.assertEqual(result["model_eligibility"], AUTHORIZED_DOWNLOAD)
        self.assertFalse(result["model_inference_run"])

    def test_hash_missing_blocked(self) -> None:
        result = finalize_eligibility(
            self.record(),
            model_path=None,
            expected_sha256=None,
            runtime_facts={
                "backend_available": True,
                "memory_fits": True,
                "dependency_conflict": False,
                "model_load_status": PASS,
            },
        )
        self.assertEqual(result["model_eligibility"], BLOCKED)
        self.assertIn("HASH_MISSING", result["block_reasons"])

    def test_runtime_unavailable_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model = Path(temporary) / "model.bin"
            model.write_bytes(b"model")
            result = finalize_eligibility(
                self.record(),
                model_path=model,
                expected_sha256=sha256_file(model),
                runtime_facts={
                    "backend_available": False,
                    "memory_fits": True,
                    "dependency_conflict": False,
                    "model_load_status": PASS,
                },
            )
        self.assertEqual(result["model_eligibility"], BLOCKED)
        self.assertIn("RUNTIME_UNAVAILABLE", result["block_reasons"])

    def test_valid_model_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model = Path(temporary) / "model.bin"
            model.write_bytes(b"model")
            result = finalize_eligibility(
                self.record(),
                model_path=model,
                expected_sha256=sha256_file(model),
                runtime_facts={
                    "backend_available": True,
                    "memory_fits": True,
                    "dependency_conflict": False,
                    "model_load_status": PASS,
                },
            )
        self.assertEqual(result["model_eligibility"], PASS)
        self.assertEqual(result["model_integrity_status"], PASS)
        self.assertEqual(result["runtime_status"], PASS)

    def test_model_load_fail_blocks_eligibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model = Path(temporary) / "model.bin"
            model.write_bytes(b"model")
            result = finalize_eligibility(
                self.record(),
                model_path=model,
                expected_sha256=sha256_file(model),
                runtime_facts={
                    "backend_available": True,
                    "memory_fits": True,
                    "dependency_conflict": False,
                    "model_load_status": "FAIL",
                },
            )
        self.assertEqual(result["model_eligibility"], BLOCKED)
        self.assertEqual(result["runtime_status"], "FAIL")
        self.assertFalse(result["model_benchmark"])

    def test_model_load_success_can_continue_eligibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model = Path(temporary) / "model.bin"
            model.write_bytes(b"model")
            result = finalize_eligibility(
                self.record(),
                model_path=model,
                expected_sha256=sha256_file(model),
                runtime_facts={
                    "backend_available": True,
                    "memory_fits": True,
                    "dependency_conflict": False,
                    "model_load_status": PASS,
                },
            )
        self.assertEqual(result["model_eligibility"], PASS)
        self.assertEqual(result["runtime_status"], PASS)


if __name__ == "__main__":
    unittest.main()
