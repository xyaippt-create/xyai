from __future__ import annotations

import json
import unittest
from dataclasses import fields
from pathlib import Path

from engine.image_compression.contracts import (
    RESULT_FIELD_NAMES,
    TASK_FIELD_NAMES,
    VALIDATION_STAGES,
    ImageCompressionResult,
    ImageCompressionTask,
    canonical_json,
    validate_task,
)
from engine.image_compression.router import evaluate_fixture_case


FIXTURE = Path(__file__).parent / "fixtures" / "stage3_contract_cases_v1.json"


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_frozen_field_counts_and_order(self) -> None:
        self.assertEqual(tuple(item.name for item in fields(ImageCompressionTask)), TASK_FIELD_NAMES)
        self.assertEqual(tuple(item.name for item in fields(ImageCompressionResult)), RESULT_FIELD_NAMES)
        self.assertEqual(len(TASK_FIELD_NAMES), 28)
        self.assertEqual(len(RESULT_FIELD_NAMES), 50)

    def test_seven_validation_stages_are_stable(self) -> None:
        self.assertEqual(len(VALIDATION_STAGES), 7)
        self.assertEqual(
            VALIDATION_STAGES,
            (
                "STRUCTURE_AND_UNKNOWN_FIELDS",
                "VERSION_REQUIRED_AND_BASE_TYPES",
                "FIELD_APPLICABILITY",
                "ENUMS_AND_SINGLE_FIELD_RANGES",
                "CROSS_FIELD_CONFLICTS",
                "RESOURCE_AND_PATH_PREFLIGHT",
                "RUNTIME_PROCESSING_ERRORS",
            ),
        )

    def test_all_22_frozen_cases_execute(self) -> None:
        self.assertEqual(len(self.fixture["cases"]), 22)
        for case in self.fixture["cases"]:
            with self.subTest(case_id=case["case_id"]):
                result = evaluate_fixture_case(case)
                self.assertTrue(result["passed"], result)

    def test_case_22_collects_all_errors_with_stable_primary(self) -> None:
        case = self.fixture["cases"][-1]
        validation = validate_task(case["request"], check_resources=False)
        self.assertFalse(validation.valid)
        self.assertEqual(validation.primary_failure_code, "UNKNOWN_FIELD")
        codes = [item.failure_code for item in validation.validation_failures]
        self.assertIn("UNKNOWN_FIELD", codes)
        self.assertIn("FIELD_NOT_APPLICABLE", codes)
        self.assertIn("QUALITY_POLICY_INVALID", codes)
        self.assertLess(codes.index("UNKNOWN_FIELD"), codes.index("FIELD_NOT_APPLICABLE"))
        self.assertLess(codes.index("FIELD_NOT_APPLICABLE"), codes.index("QUALITY_POLICY_INVALID"))

    def test_unknown_fields_use_utf8_lexical_order(self) -> None:
        request = dict(self.fixture["cases"][0]["request"])
        request["未知字段"] = 1
        request["alpha_unknown"] = 2
        validation = validate_task(request, check_resources=False)
        unknown = [item.field for item in validation.validation_failures if item.failure_code == "UNKNOWN_FIELD"]
        self.assertEqual(unknown, sorted(unknown, key=lambda item: item.encode("utf-8")))
        self.assertEqual(validation.primary_failure_code, "UNKNOWN_FIELD")

    def test_test_setup_is_not_a_formal_request_field(self) -> None:
        request = dict(self.fixture["cases"][0]["request"])
        request["test_setup"] = {"fault_injection": True}
        validation = validate_task(request, check_resources=False)
        self.assertEqual(validation.primary_failure_code, "UNKNOWN_FIELD")

    def test_canonical_json_is_stable_and_typed(self) -> None:
        result = ImageCompressionResult(task_id="stable", operation_mode="LOSSLESS_COMPRESSION")
        first = result.canonical_json()
        second = canonical_json(result.to_dict())
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first)["delivery_eligible"], False)
        self.assertNotIn("not_applicable", first.lower())

    def test_result_rejects_not_applicable_string(self) -> None:
        with self.assertRaises(ValueError):
            ImageCompressionResult(task_id="invalid", warnings=["not_applicable"])

    def test_user_issue_context_requires_four_user_fields(self) -> None:
        request = dict(self.fixture["cases"][0]["request"])
        request.update(issue_report_id="issue-1", user_issue_context={})
        validation = validate_task(request, check_resources=False)
        self.assertFalse(validation.valid)
        self.assertEqual(validation.primary_failure_code, "USER_ISSUE_CONTEXT_INVALID")

    def test_diagnostic_session_and_registered_checks_are_strict(self) -> None:
        request = dict(self.fixture["cases"][0]["request"])
        request.update(diagnostic_session_id="not-a-uuid", required_checks=["bogus"])
        validation = validate_task(request, check_resources=False)
        self.assertFalse(validation.valid)
        codes = {item.failure_code for item in validation.validation_failures}
        self.assertIn("DIAGNOSTIC_SESSION_ID_INVALID", codes)
        self.assertIn("REQUIRED_CHECK_UNKNOWN", codes)


if __name__ == "__main__":
    unittest.main()
