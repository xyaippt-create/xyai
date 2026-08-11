from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.image_compression_api import register_image_compression_routes
from engine.image_processing_routing import (
    PreflightContractError,
    build_image_profile,
    route_preflight,
    validate_preflight_request,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "stage5_preflight_cases_v1.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
CASES = {case["case_id"]: case for case in FIXTURE["cases"]}


def expected_business(case: dict) -> dict:
    return {
        "schema_version": FIXTURE["schema_version"],
        "decision_version": FIXTURE["decision_version"],
        "profile": case["profile"],
        "purpose": case["request"]["purpose"],
        "preflight_status": case["expected_preflight_status"],
        "recommended_action": case["expected_recommended_action"],
        "executable": case["expected_executable"],
        "reason_codes": case["expected_reason_codes"],
        "blocking_reasons": case["expected_blocking_reasons"],
        "warnings": case["expected_warning_codes"],
        "recommended_parameters": case["expected_recommended_parameters"],
        "estimated_output": case["expected_estimated_output"],
        "alternatives": case["expected_alternatives"],
    }


class ApiHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.dirs = {"normal_output_dir": self.root / "output", "tmp_dir": self.root / "tmp"}
        for path in self.dirs.values():
            path.mkdir()
        app = FastAPI()
        self.state = register_image_compression_routes(app, user_dirs_provider=lambda: self.dirs)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.temporary.cleanup()

    @staticmethod
    def exact_image_bytes(profile: dict) -> bytes:
        image_format = profile["format"]
        mode = "RGBA" if profile["has_alpha"] and image_format == "PNG" else "RGB"
        color = (24, 120, 220, 180) if mode == "RGBA" else (24, 120, 220)
        image = Image.new(mode, (profile["width"], profile["height"]), color)
        stream = io.BytesIO()
        image.save(stream, format=image_format)
        payload = stream.getvalue()
        target_size = profile["size_bytes"]
        if len(payload) > target_size:
            raise AssertionError(f"generated fixture image exceeds target size: {len(payload)} > {target_size}")
        return payload + (b"\0" * (target_size - len(payload)))

    def intake_case(self, case: dict) -> str:
        profile = case["profile"]
        payload = self.exact_image_bytes(profile)
        suffix = ".png" if profile["format"] == "PNG" else ".jpg"
        mime = "image/png" if suffix == ".png" else "image/jpeg"
        response = self.client.post(
            "/api/image-compression/intake",
            files={"file": (f"{case['case_id']}{suffix}", payload, mime)},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["source_token"]


class RoutingFixtureTests(unittest.TestCase):
    pass


class ProfileFixtureTests(unittest.TestCase):
    pass


class ApiIntegrationFixtureTests(ApiHarness):
    pass


class ContractErrorFixtureTests(ApiHarness):
    pass


def _business_test(case_id: str):
    def test(self):
        case = CASES[case_id]
        request = validate_preflight_request(deepcopy(case["request"]))
        actual = route_preflight(deepcopy(case["profile"]), request)
        self.assertEqual(actual, expected_business(case))

    return test


def _api_test(case_id: str):
    def test(self):
        case = CASES[case_id]
        token = self.intake_case(case)
        request = deepcopy(case["request"])
        request["file_token"] = token
        response = self.client.post("/api/image-processing/preflight", json=request)
        self.assertEqual(response.status_code, case["expected_http_status"], response.text)
        self.assertEqual(response.json(), expected_business(case))
        self.assertNotIn(str(self.root), response.text)

    return test


def _contract_error_test(case_id: str):
    def test(self):
        case = CASES[case_id]
        if case_id == "S5-E04-image-decode-failed":
            corrupt = self.root / "corrupt.png"
            corrupt.write_bytes(b"not-an-image")
            with self.assertRaises(PreflightContractError) as raised:
                build_image_profile(corrupt)
            self.assertEqual(raised.exception.status_code, case["expected_http_status"])
            self.assertEqual(raised.exception.code, case["expected_error_code"])
            return
        response = self.client.post("/api/image-processing/preflight", json=deepcopy(case["request"]))
        self.assertEqual(response.status_code, case["expected_http_status"], response.text)
        self.assertEqual(response.json()["detail"]["code"], case["expected_error_code"])

    return test


for fixture_case in FIXTURE["cases"]:
    case_id = fixture_case["case_id"]
    method_name = "test_" + case_id.lower().replace("-", "_")
    layer = fixture_case["test_layer"]
    if layer == "ROUTING_UNIT":
        setattr(RoutingFixtureTests, method_name, _business_test(case_id))
    elif layer == "PROFILE_UNIT":
        setattr(ProfileFixtureTests, method_name, _business_test(case_id))
    elif layer == "API_INTEGRATION":
        setattr(ApiIntegrationFixtureTests, method_name, _api_test(case_id))
    elif layer == "CONTRACT_ERROR":
        setattr(ContractErrorFixtureTests, method_name, _contract_error_test(case_id))


class PreflightDeterminismAndSideEffectTests(ApiHarness):
    def test_all_business_cases_are_deterministic(self):
        checked = 0
        for case in FIXTURE["cases"]:
            if case["test_layer"] not in {"ROUTING_UNIT", "PROFILE_UNIT"}:
                continue
            request = validate_preflight_request(deepcopy(case["request"]))
            first = route_preflight(deepcopy(case["profile"]), request)
            second = route_preflight(deepcopy(case["profile"]), deepcopy(request))
            self.assertEqual(first, second, case["case_id"])
            checked += 1
        self.assertEqual(checked, 28)

    def test_api_preflight_has_no_processing_side_effects(self):
        case = CASES["S5-A01-png-lossless-static"]
        token = self.intake_case(case)
        source = Path(self.state["token_registry"][token]["path"])
        before = {
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "tokens": sorted(self.state["token_registry"]),
            "tasks": deepcopy(self.state["task_registry"]),
            "feedback": sorted(self.state["expired_feedback_tokens"]),
            "output_files": sorted(str(path.relative_to(self.root)) for path in self.dirs["normal_output_dir"].rglob("*") if path.is_file()),
        }
        request = deepcopy(case["request"])
        request["file_token"] = token
        response = self.client.post("/api/image-processing/preflight", json=request)
        self.assertEqual(response.status_code, 200, response.text)
        after = {
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "tokens": sorted(self.state["token_registry"]),
            "tasks": deepcopy(self.state["task_registry"]),
            "feedback": sorted(self.state["expired_feedback_tokens"]),
            "output_files": sorted(str(path.relative_to(self.root)) for path in self.dirs["normal_output_dir"].rglob("*") if path.is_file()),
        }
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
