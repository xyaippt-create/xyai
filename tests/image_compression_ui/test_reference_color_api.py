"""D60-05F product contract tests, isolated from formal user data."""
import hashlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.image_compression_api import register_image_compression_routes
from engine.color_correction.color_management import load_color_managed_source, srgb_profile_bytes
from engine.color_correction.executors.basic_correction import execute_basic_correction
from engine.color_correction.formal_runtime import _write_verified_candidate
from engine.color_correction.reference_matching import decide_reference_matching, load_target_color_profile, load_reference_color_target
from engine.color_correction.reference_integration import reference_decision_record, validate_reference_binding
from engine.color_correction.result_audit import FinalAction, audit_basic_correction, audit_reference_candidate
from engine.color_correction.usability_decision import analyze_color_usability
from engine.storage.shared_task_registry import SharedTaskRegistry
from main import DEFAULT_TMP_DIR_NAME


class ReferenceColorApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.formal = self.root / "formal"
        self.cache = self.formal / DEFAULT_TMP_DIR_NAME
        self.cache.mkdir(parents=True)
        self.now = 1_800_000_000.0
        self.events = []
        self.registry = SharedTaskRegistry(self.formal)
        self.valid_output = True
        app = FastAPI()
        def validate(value):
            return {"valid": self.valid_output, "writable": self.valid_output, "normalized_path": str(Path(value).resolve())}
        self.state = register_image_compression_routes(
            app, user_dirs_provider=lambda: {"normal_output_dir": self.formal / "输出", "tmp_dir": self.cache},
            shared_task_registry=self.registry, now_provider=lambda: self.now,
            output_settings_provider=lambda: {"built_in_default_root": str(self.formal), "saved_default_root": str(self.formal)},
            output_dir_validator=validate, folder_opener=lambda value: None,
            runtime_event_logger=lambda event, **fields: self.events.append({"event": event, **fields}),
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def intake(self, *, cast=(-5, 0, 12), name="target.png", flat=None, alpha=False, dpi=None, author="Target author"):
        ramp = np.tile(np.linspace(35, 215, 160).astype(np.int16), (120, 1))
        rgb = np.stack([np.clip(ramp + x, 0, 255) for x in cast], -1).astype(np.uint8)
        if flat is not None:
            rgb[:] = flat
        if alpha:
            rgb = np.dstack((rgb, np.tile(np.linspace(0, 255, 160).astype(np.uint8), (120, 1))))
        image = Image.fromarray(rgb)
        exif = Image.Exif()
        exif[315] = author
        exif[270] = "Target title" if author == "Target author" else "Reference title"
        stream = io.BytesIO()
        options = {"exif": exif, "icc_profile": srgb_profile_bytes()}
        if dpi:
            options["dpi"] = dpi
        fmt = "JPEG" if name.endswith("jpg") else "PNG"
        image.save(stream, format=fmt, **options)
        response = self.client.post("/api/image-compression/intake", files={"file": (name, stream.getvalue(), "image/jpeg" if fmt == "JPEG" else "image/png")})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def run_reference(self, target, reference, **extra):
        return self.client.post("/api/color-correction/reference-run", json={
            "target_source_token": target["source_token"], "reference_source_token": reference["source_token"], **extra})

    def test_distinct_contract_and_invalid_tokens(self):
        target, reference = self.intake(), self.intake(name="reference.png")
        for field, code in (("target_source_token", "TARGET_TOKEN_INVALID"), ("reference_source_token", "REFERENCE_TOKEN_INVALID")):
            payload = {"target_source_token": target["source_token"], "reference_source_token": reference["source_token"], field: "missing"}
            response = self.client.post("/api/color-correction/reference-run", json=payload)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"]["code"], code)
        self.assertEqual(self.run_reference(target, reference, match_strength=.65).status_code, 400)
        old = self.client.post("/api/color-correction/run", json={"source_token": target["source_token"], "reference_source_token": reference["source_token"]})
        self.assertEqual(old.status_code, 400)
        self.assertEqual(len(self.registry), 0)

    def test_expiry_distinguishes_target_and_reference(self):
        for role in ("target", "reference"):
            target, reference = self.intake(), self.intake(name="reference.png")
            selected = target if role == "target" else reference
            self.state["token_registry"][selected["source_token"]]["expires_at"] = self.now - 1
            response = self.run_reference(target, reference)
            self.assertEqual(response.status_code, 410)
            self.assertEqual(response.json()["detail"]["code"], role.upper() + "_TOKEN_EXPIRED")

    def test_unsupported_reference_and_changed_identity_are_rejected(self):
        target, reference = self.intake(), self.intake(name="reference.png")
        item = self.state["token_registry"][reference["source_token"]]
        path = Path(item["path"])
        # A token remains valid structurally; its file has become unsupported.
        Image.new("RGB", (80, 80)).save(path, format="BMP")
        response = self.run_reference(target, reference)
        self.assertEqual(response.status_code, 409)
        item["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        response = self.run_reference(target, reference)
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.json()["detail"]["code"], "UNSUPPORTED_REFERENCE_FORMAT")

    def test_same_image_is_neutral_target_result_and_private_reference(self):
        target = self.intake()
        response = self.run_reference(target, target)
        self.assertEqual(response.status_code, 422, response.json().get("code"))
        data = response.json()["data"]
        self.assertFalse(response.json()["success"])
        self.assertEqual(data["task"]["status"], "failed")
        self.assertIsNone(data["result"])
        result = data["decision"]
        self.assertEqual(result["result_action"], "ACCEPT_ORIGINAL")
        self.assertEqual(result["source_sha256"], target["source_sha256"])
        self.assertEqual(result["result_file"], "")
        self.assertTrue(all(x == 0 for x in result["parameters"]["correction_parameters"]["values"].values()))
        matching = result["analysis"]["REFERENCE_MATCHING"]
        self.assertNotIn("PATH", matching["REFERENCE_PROFILE"]["REFERENCE_SOURCE"])
        self.assertNotIn("PATH", matching["TARGET_PROFILE"]["TARGET_SOURCE"])
        self.assertEqual(len(self.registry), 1)
        self.assertEqual(str(self.registry[data["task"]["task_id"]]["source_path"]), result["source_path"])
        self.assertFalse(data["ui"]["can_open_output"])

    def test_insufficient_reference_preserves_target(self):
        target, reference = self.intake(), self.intake(name="extreme.png", flat=255)
        response = self.run_reference(target, reference)
        self.assertEqual(response.status_code, 422, response.json().get("code"))
        data = response.json()["data"]
        self.assertIsNone(data["result"])
        self.assertEqual(data["task"]["status"], "failed")
        self.assertEqual(data["decision"]["result_action"], "ACCEPT_ORIGINAL")
        self.assertEqual(data["ui"]["reference_notice_code"], "REFERENCE_INSUFFICIENT_EVIDENCE")
        self.assertEqual(data["decision"]["output_path"], "")

    def test_reference_runtime_failure_does_not_leak_paths_or_fallback(self):
        target, reference = self.intake(), self.intake(name="private-reference.png")
        private = str(self.state["token_registry"][reference["source_token"]]["path"])
        with patch("engine.color_correction.formal_runtime.load_color_managed_source", side_effect=OSError(private)) as run:
            response = self.run_reference(target, reference)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["code"], "RUNTIME_FAILURE")
        self.assertNotIn(private, response.text)
        self.assertNotIn(private, json.dumps(self.events, default=str))
        self.assertIsNone(response.json()["data"]["result"])

    def test_invalid_output_directory_does_not_execute(self):
        target, reference = self.intake(), self.intake()
        self.valid_output = False
        with patch("engine.color_correction.formal_runtime.load_color_managed_source") as run:
            response = self.run_reference(target, reference, current_task_output_root=str(self.formal / "unavailable"))
        self.assertGreaterEqual(response.status_code, 400)
        run.assert_not_called()

    def test_independent_d3_replay_failure_never_registers_reference_result(self):
        target, reference = self.intake(), self.intake(cast=(8, 2, -4))
        def altered_candidate(original, candidate, parameters, **kwargs):
            changed = candidate.copy()
            changed[0, 0, 0] ^= 1
            return audit_basic_correction(original, changed, parameters, **kwargs)
        with patch("engine.color_correction.result_audit.audit_basic_correction", side_effect=altered_candidate):
            response = self.run_reference(target, reference)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["code"], "PROTECTION_BLOCKED")
        data = response.json()["data"]
        self.assertEqual(data["task"]["d3_status"], "PROTECTION_BLOCKED")
        self.assertNotIn("PROTECTION_BLOCKED", {action.value for action in FinalAction})
        self.assertEqual(data["task"]["d3_final_action"], "REVIEW_REQUIRED")
        self.assertEqual(data["task"]["status"], "failed")
        self.assertEqual(data["task"]["output_selected"], "NONE")
        self.assertIsNone(data["result"])
        self.assertFalse(data["task"]["result_id"])
        self.assertFalse(data["ui"]["can_open_output"])
        self.assertFalse(data["ui"]["can_open_folder"])
        persisted = self.registry[data["task"]["task_id"]]
        self.assertIsNone(persisted["result"])
        self.assertFalse(persisted["result_id"])
        # This is a fault-injected backend contract test, not a real input trigger.
        self.assertFalse(self.client.get("/api/output-center/items").json()["data"]["items"])
        preflight = self.client.post("/api/smart-delivery/preflight", json={
            "result_ids": [data["task"]["task_id"]], "rules": {}})
        self.assertEqual(preflight.status_code, 404)
        self.assertEqual(preflight.json()["detail"]["code"], "UNIFIED_RESULT_NOT_FOUND")
        execute = self.client.post("/api/smart-delivery/execute", json={
            "plan_id": data["task"]["task_id"], "confirmed": True})
        self.assertEqual(execute.status_code, 404)
        self.assertFalse(list((self.formal / "颜色校正").glob("*")))

    def test_reference_result_read_restores_existing_fact_after_restart(self):
        target, reference = self.intake(), self.intake(name="reference.png")
        before = self.run_reference(target, reference).json()["data"]
        task_id = before["task"]["task_id"]
        persisted_sha = hashlib.sha256(self.registry.path.read_bytes()).hexdigest()
        restarted_registry = SharedTaskRegistry(self.formal)
        restarted = FastAPI()
        register_image_compression_routes(
            restarted, user_dirs_provider=lambda: {"normal_output_dir": self.formal / "输出", "tmp_dir": self.cache},
            shared_task_registry=restarted_registry, now_provider=lambda: self.now,
        )
        with TestClient(restarted) as client:
            response = client.get("/api/color-correction/tasks/" + task_id)
            self.assertEqual(response.status_code, 200, response.text)
            restored = response.json()["data"]
            self.assertEqual(restored["result"], before["result"])
            self.assertEqual(restored["task"]["lifecycle"], before["task"]["lifecycle"])
            for field, expected_hash in (("source_preview_url", target["source_sha256"]), ("reference_preview_url", reference["source_sha256"])):
                preview = client.get(restored["ui"][field])
                self.assertEqual(preview.status_code, 200)
                self.assertEqual(hashlib.sha256(preview.content).hexdigest(), expected_hash)
            self.assertEqual(client.post("/api/color-correction/tasks/" + task_id + "/review", json={"status": "confirmed"}).status_code, 409)
            private = restarted_registry[task_id]["reference_metadata"]
            private["path"] = str(self.root / "outside-cache.png")
            response = client.get("/api/color-correction/tasks/" + task_id)
            self.assertIsNone(response.json()["data"]["ui"]["reference_preview_url"])
            self.assertNotIn(private["path"], response.text)
        self.assertEqual(hashlib.sha256(self.registry.path.read_bytes()).hexdigest(), persisted_sha)
        self.assertEqual(len(restarted_registry), len(self.registry))

    def test_executor_replay_and_target_metadata(self):
        for name, alpha, dpi in (("target.png", True, (300, 300)), ("target.jpg", False, (144, 144)), ("target.png", False, None)):
            with self.subTest(name=name, alpha=alpha, dpi=dpi):
                target = self.intake(name=name, alpha=alpha, dpi=dpi)
                reference = self.intake(cast=(8, 2, -4), name="reference.png", author="Reference author")
                source = Path(self.state["token_registry"][target["source_token"]]["path"])
                ref = Path(self.state["token_registry"][reference["source_token"]]["path"])
                decision = decide_reference_matching(load_target_color_profile(source), load_reference_color_target(ref))
                managed = load_color_managed_source(source)
                candidate = execute_basic_correction(managed.pixels, decision.parameters).candidate_image
                replay = audit_basic_correction(managed.pixels, candidate, decision.parameters.to_record())
                self.assertEqual(replay.status, "AUDIT_COMPLETE")
                bad = replace(decision, parameters=replace(decision.parameters, brightness=8))
                with self.assertRaises(ValueError):
                    validate_reference_binding(bad, managed.pixels, bad.parameters)
                audit = audit_reference_candidate(managed.pixels, analyze_color_usability(managed.pixels), decision, managed_source=managed)
                self.assertEqual(audit.status, "AUDIT_COMPLETE")
                response = self.run_reference(target, reference)
                self.assertEqual(response.status_code, 422, response.json().get("code"))
                data = response.json()["data"]
                # This smooth ramp's reference gain is below the unchanged
                # quality threshold. It must not become an accepted Result.
                self.assertIsNone(data["result"])
                self.assertEqual(data["task"]["status"], "failed")
                self.assertEqual(data["decision"]["result_action"], "ACCEPT_ORIGINAL")
                # Independently exercise the exact formal encoder/publisher;
                # this private fixture output is NOT registered or deliverable.
                output = self.root / (f"encoding-{alpha}-{dpi}" + source.suffix)
                _write_verified_candidate(candidate, output, source=managed, source_path=source)
                with Image.open(output) as image, Image.open(source) as original:
                    self.assertEqual(image.size, original.size)
                    self.assertEqual(image.format, original.format)
                    self.assertEqual(image.getexif().get(315), "Target author")
                    self.assertEqual(image.getexif().get(270), original.getexif().get(270))
                    self.assertNotEqual(image.getexif().get(270), "Reference title")
                    self.assertTrue(image.info.get("icc_profile"))
                    if dpi:
                        self.assertAlmostEqual(image.info["dpi"][0], dpi[0], delta=.02)
                    else:
                        self.assertNotIn("dpi", image.info)
                    if alpha:
                        np.testing.assert_array_equal(np.asarray(image)[..., 3], np.asarray(original)[..., 3])
                self.assertEqual(data["decision"]["source_sha256"], target["source_sha256"])
                self.assertNotIn(str(ref), json.dumps(data))
                self.assertIn("QUALITY_EVIDENCE", data["decision"]["analysis"])


if __name__ == "__main__":
    unittest.main()
