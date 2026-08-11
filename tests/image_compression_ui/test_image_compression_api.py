import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import backend.image_compression_api as image_compression_api_module
from backend.image_compression_api import (
    FUNCTION_DIRECTORY_BY_MODE,
    TOKEN_TTL_SECONDS,
    build_long_image_validation,
    calculate_target_by_short_side,
    classify_long_image_width,
    dimensions_after_exif_orientation,
    estimate_product_dimensions,
    is_long_image,
    register_image_compression_routes,
)
from engine.image_compression.common import optimise_png_data
from engine.image_compression.contracts import RESULT_FIELD_NAMES


class ImageCompressionApiStage4Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.dirs = {
            "normal_output_dir": self.root / "output",
            "tmp_dir": self.root / "tmp",
        }
        self.dirs["normal_output_dir"].mkdir()
        self.dirs["tmp_dir"].mkdir()
        self.now = 1_800_000_000.0
        self.opened = []
        self.built_in_output_root = self.root / "built-in-output"
        self.saved_output_root = self.root / "saved-output"
        self.current_task_output_root = self.root / "current-task-output"
        self.output_settings = {"saved_default_root": str(self.saved_output_root)}
        self.runtime_events = []

        def output_settings_provider():
            return {
                "built_in_default_root": str(self.built_in_output_root),
                "saved_default_root": self.output_settings["saved_default_root"],
            }

        def save_default_output_root(value):
            self.output_settings["saved_default_root"] = value

        def validate_output_root(value):
            target = Path(value).resolve()
            if target.exists() and not target.is_dir():
                return {"valid": False, "writable": False, "normalized_path": str(target), "message": "目标不是目录"}
            target.mkdir(parents=True, exist_ok=True)
            return {"valid": True, "writable": True, "normalized_path": str(target), "message": "输出目录可用"}

        app = FastAPI()
        self.state = register_image_compression_routes(
            app,
            user_dirs_provider=lambda: self.dirs,
            now_provider=lambda: self.now,
            folder_opener=self.opened.append,
            output_settings_provider=output_settings_provider,
            output_default_saver=save_default_output_root,
            output_dir_validator=validate_output_root,
            runtime_event_logger=lambda event, **fields: self.runtime_events.append({"event": event, **fields}),
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    @staticmethod
    def image_bytes(fmt="PNG", size=(96, 72), *, alpha=False, compress_level=None):
        mode = "RGBA" if fmt == "PNG" and alpha else "RGB"
        color = (24, 120, 220, 180) if mode == "RGBA" else (24, 120, 220)
        image = Image.new(mode, size, color)
        stream = io.BytesIO()
        options = {"compress_level": compress_level} if fmt == "PNG" and compress_level is not None else {}
        image.save(stream, format=fmt, **options)
        return stream.getvalue()

    def intake_bytes(self, payload, filename="sample.png", mime="image/png"):
        response = self.client.post(
            "/api/image-compression/intake",
            files={"file": (filename, payload, mime)},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def intake(self, filename="sample.png", fmt="PNG", size=(96, 72), **kwargs):
        payload = self.image_bytes(fmt, size, **kwargs)
        mime = "image/png" if fmt == "PNG" else "image/jpeg"
        return self.intake_bytes(payload, filename, mime), payload

    def execute(self, intake, mode, params=None, **context):
        payload = {
            "source_token": intake["source_token"],
            "operation_mode": mode,
            "params": params or {},
            **context,
        }
        response = self.client.post("/api/image-compression/run", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(set(data), {"task", "result", "ui"})
        self.assertEqual(tuple(data["result"]), RESULT_FIELD_NAMES)
        self.assertEqual(len(data["result"]), 50)
        task = self.state["task_registry"][data["result"]["task_id"]]
        self.assertEqual(data["result"], task["result"].to_dict())
        self.assertEqual(data["task"]["task_id"], data["result"]["task_id"])
        return data

    def generate_feedback(self, result):
        response = self.client.post(
            "/api/image-compression/test-feedback-package",
            json={"task_id": result["task_id"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def assert_feedback_manifest_integrity(self, package):
        package_path = Path(package["display_path"])
        with zipfile.ZipFile(package_path) as archive:
            self.assertIsNone(archive.testzip())
            names = set(archive.namelist())
            checked_names = names - {"manifest.json", "manifest.sha256"}
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            self.assertEqual({item["path"] for item in manifest["files"]}, checked_names)
            manifest_sha256 = archive.read("manifest.sha256").decode("utf-8")
            sha_lines = {}
            for line in manifest_sha256.splitlines():
                digest, relative_path = line.split("  ", 1)
                sha_lines[relative_path] = digest
            self.assertEqual(set(sha_lines), checked_names)
            for item in manifest["files"]:
                content = archive.read(item["path"])
                self.assertEqual(item["sha256"], hashlib.sha256(content).hexdigest())
                self.assertEqual(item["size_bytes"], len(content))
                self.assertEqual(sha_lines[item["path"]], item["sha256"])
        return manifest

    def assert_standard_feedback_files(self, package, *, long_image=False):
        expected = {
            "summary.md",
            "task.json",
            "result.json",
            "review.json",
            "environment.json",
            "validation.json",
            "warnings.json",
            "manifest.json",
            "manifest.sha256",
            "evidence/README.md",
        }
        if long_image:
            expected.add("long_image_validation.json")
        with zipfile.ZipFile(package["display_path"]) as archive:
            self.assertEqual(set(archive.namelist()), expected)

    def test_01_capabilities_three_modes(self):
        response = self.client.get("/api/image-compression/capabilities")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual([item["value"] for item in data["modes"]], [
            "LOSSLESS_COMPRESSION",
            "RESIZE_REDUCTION",
            "UPLOAD_ADAPTATION",
        ])
        self.assertFalse(data["online_upload"])
        self.assertFalse(data["jpeg_lossless_supported"])
        self.assertEqual(data["server_session_id"], self.state["server_session_id"])
        self.assertEqual(data["output_settings_endpoint"], "/api/image-compression/output-settings")

    def test_02_png_intake_stable_contract(self):
        intake, raw = self.intake("alpha.png", alpha=True)
        self.assertEqual(set(intake), {
            "source_token",
            "display_name",
            "format",
            "width",
            "height",
            "size_bytes",
            "has_alpha",
            "source_sha256",
            "safe_preview_url",
            "expires_at",
        })
        self.assertEqual((intake["format"], intake["width"], intake["height"]), ("PNG", 96, 72))
        self.assertTrue(intake["has_alpha"])
        self.assertEqual(intake["source_sha256"], hashlib.sha256(raw).hexdigest())
        preview = self.client.get(intake["safe_preview_url"])
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(hashlib.sha256(preview.content).hexdigest(), intake["source_sha256"])

    def test_03_jpeg_intake_stable_contract(self):
        intake, raw = self.intake("photo.jpg", "JPEG")
        self.assertEqual(intake["format"], "JPEG")
        self.assertFalse(intake["has_alpha"])
        self.assertEqual(intake["source_sha256"], hashlib.sha256(raw).hexdigest())

    def test_04_non_image_rejected_without_residue(self):
        response = self.client.post(
            "/api/image-compression/intake",
            files={"file": ("broken.png", b"not-an-image", "image/png")},
        )
        self.assertEqual(response.status_code, 400)
        intake_root = self.dirs["tmp_dir"] / "image-compression-intake"
        self.assertFalse(intake_root.exists() and any(intake_root.iterdir()))

    def test_05_extension_magic_mismatch_rejected(self):
        jpeg = self.image_bytes("JPEG")
        response = self.client.post(
            "/api/image-compression/intake",
            files={"file": ("disguised.png", jpeg, "image/png")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "SOURCE_EXTENSION_MAGIC_MISMATCH")

    def test_06_fake_and_cross_scope_tokens_rejected(self):
        fake = self.client.post("/api/image-compression/run", json={
            "source_token": "fake-token",
            "operation_mode": "LOSSLESS_COMPRESSION",
            "params": {},
        })
        self.assertEqual(fake.status_code, 404)
        self.assertEqual(fake.json()["detail"]["code"], "TOKEN_NOT_FOUND_OR_EXPIRED")
        intake, _ = self.intake()
        preview_token = intake["safe_preview_url"].rsplit("/", 1)[-1]
        cross_scope = self.client.post("/api/image-compression/run", json={
            "source_token": preview_token,
            "operation_mode": "LOSSLESS_COMPRESSION",
            "params": {},
        })
        self.assertEqual(cross_scope.status_code, 404)
        self.assertEqual(cross_scope.json()["detail"]["code"], "TOKEN_NOT_FOUND_OR_EXPIRED")

    def test_07_expired_source_token_rejected(self):
        intake, _ = self.intake()
        self.now += TOKEN_TTL_SECONDS + 1
        response = self.client.post("/api/image-compression/run", json={
            "source_token": intake["source_token"],
            "operation_mode": "LOSSLESS_COMPRESSION",
            "params": {},
        })
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "TOKEN_NOT_FOUND_OR_EXPIRED")

    def test_08_filename_traversal_rejected(self):
        response = self.client.post(
            "/api/image-compression/intake",
            files={"file": ("../escape.png", self.image_bytes(), "image/png")},
        )
        self.assertEqual(response.status_code, 400)

    def test_09_lossless_route_preserves_frozen_result_and_wrapper(self):
        intake, _ = self.intake(compress_level=0)
        data = self.execute(intake, "LOSSLESS_COMPRESSION")
        result, ui = data["result"], data["ui"]
        self.assertEqual(result["operation_mode"], "LOSSLESS_COMPRESSION")
        self.assertNotIn("source_preview_url", result)
        self.assertIn("source_preview_url", ui)
        self.assertIn(result["technical_status"], {"TARGET_MET", "NO_PROCESSING_NEEDED"})

    def test_10_resize_route_executes(self):
        intake, _ = self.intake("resize.png", size=(120, 80), alpha=True)
        data = self.execute(intake, "RESIZE_REDUCTION", {"scale_ratio": 0.75})
        result = data["result"]
        self.assertEqual(result["technical_status"], "TARGET_MET")
        self.assertEqual(result["output_dimensions"], {"width": 90, "height": 60})
        self.assertTrue(result["alpha_preserved"])
        width_only = self.execute(intake, "RESIZE_REDUCTION", {"target_width": 60})
        height_only = self.execute(intake, "RESIZE_REDUCTION", {"target_height": 40})
        self.assertEqual(width_only["result"]["output_dimensions"], {"width": 60, "height": 40})
        self.assertEqual(height_only["result"]["output_dimensions"], {"width": 60, "height": 40})

    def test_11_upload_adaptation_route_executes(self):
        intake, _ = self.intake("upload.jpg", "JPEG", size=(120, 80))
        data = self.execute(intake, "UPLOAD_ADAPTATION", {"max_width": 90, "max_height": 60})
        self.assertEqual(data["result"]["technical_status"], "TARGET_MET_WITH_REENCODE")
        self.assertLessEqual(data["result"]["output_dimensions"]["width"], 90)

    def test_12_unknown_mode_fields_and_contract_errors_rejected(self):
        intake, _ = self.intake()
        cases = [
            {"source_token": intake["source_token"], "operation_mode": "UNKNOWN", "params": {}},
            {"source_token": intake["source_token"], "operation_mode": "LOSSLESS_COMPRESSION", "params": {"scale_ratio": 0.5}},
            {"source_token": intake["source_token"], "operation_mode": "LOSSLESS_COMPRESSION", "params": {}, "source_path": "C:/private.png"},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                response = self.client.post("/api/image-compression/run", json=payload)
                self.assertEqual(response.status_code, 400, response.text)

    def test_13_jpeg_true_lossless_rejected_before_task_creation(self):
        intake, _ = self.intake("photo.jpg", "JPEG")
        before_tasks = len(self.state["task_registry"])
        response = self.client.post("/api/image-compression/run", json={
            "source_token": intake["source_token"],
            "operation_mode": "LOSSLESS_COMPRESSION",
            "params": {},
        })
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "MODE_NOT_APPLICABLE")
        self.assertEqual(len(self.state["task_registry"]), before_tasks)

    def test_14_png_lossless_gain_creates_verified_output(self):
        intake, _ = self.intake("gain.png", size=(180, 120), compress_level=0)
        result = self.execute(intake, "LOSSLESS_COMPRESSION")["result"]
        self.assertEqual(result["technical_status"], "TARGET_MET")
        self.assertTrue(result["output_created"])
        self.assertGreater(result["size_reduction_bytes"], 0)
        self.assertNotEqual(result["source_sha256"], result["output_sha256"])

    def test_15_png_no_gain_creates_no_copy(self):
        raw = self.image_bytes("PNG", (80, 60))
        optimised, _ = optimise_png_data(raw)
        intake = self.intake_bytes(optimised, "already-optimal.png")
        data = self.execute(intake, "LOSSLESS_COMPRESSION")
        self.assertEqual(data["result"]["technical_status"], "NO_PROCESSING_NEEDED")
        self.assertFalse(data["result"]["output_created"])
        self.assertFalse(data["ui"]["can_open_folder"])

    def test_16_resize_changed_output_requires_review(self):
        intake, _ = self.intake("review.png")
        result = self.execute(intake, "RESIZE_REDUCTION", {"scale_ratio": 0.5})["result"]
        self.assertEqual(result["visual_review_status"], "PENDING")
        self.assertEqual(result["delivery_gate_status"], "REVIEW_REQUIRED")
        self.assertFalse(result["delivery_eligible"])

    def test_17_upload_changed_output_requires_review(self):
        intake, _ = self.intake("review.jpg", "JPEG")
        result = self.execute(intake, "UPLOAD_ADAPTATION", {"max_width": 72})["result"]
        self.assertEqual(result["visual_review_status"], "PENDING")
        self.assertEqual(result["delivery_gate_status"], "REVIEW_REQUIRED")

    def test_18_review_pass_preserves_technical_evidence_and_sha(self):
        intake, _ = self.intake("pass.png")
        before = self.execute(intake, "RESIZE_REDUCTION", {"scale_ratio": 0.75})["result"]
        response = self.client.post("/api/image-compression/review", json={"task_id": before["task_id"], "decision": "PASS"})
        self.assertEqual(response.status_code, 200, response.text)
        after = response.json()["data"]["result"]
        self.assertEqual(after["delivery_gate_status"], "DELIVERY_READY")
        for key in ("technical_status", "source_sha256", "output_sha256", "output_size_bytes", "output_dimensions"):
            self.assertEqual(after[key], before[key])
        review_events = [item for item in self.runtime_events if item["event"] == "QUALITY_REVIEW_UPDATED"]
        self.assertEqual(len(review_events), 1)
        self.assertEqual(review_events[0]["task_id"], before["task_id"])
        self.assertEqual(review_events[0]["status"], "PASS")
        self.assertNotIn("result_id", review_events[0])

    def test_19_review_pass_with_notes_requires_and_returns_note(self):
        intake, _ = self.intake("notes.jpg", "JPEG")
        result = self.execute(intake, "RESIZE_REDUCTION", {"scale_ratio": 0.5})["result"]
        missing = self.client.post("/api/image-compression/review", json={"task_id": result["task_id"], "decision": "PASS_WITH_NOTES"})
        self.assertEqual(missing.status_code, 400)
        accepted = self.client.post("/api/image-compression/review", json={
            "task_id": result["task_id"],
            "decision": "PASS_WITH_NOTES",
            "note": "轻微纹理变化，可交付。",
        })
        self.assertEqual(accepted.status_code, 200)
        data = accepted.json()["data"]
        self.assertEqual(data["result"]["delivery_gate_status"], "DELIVERY_READY_WITH_NOTES")
        self.assertEqual(data["ui"]["review_note"], "轻微纹理变化，可交付。")

    def test_20_review_fail_closes_delivery(self):
        intake, _ = self.intake("fail.png")
        result = self.execute(intake, "RESIZE_REDUCTION", {"scale_ratio": 0.5})["result"]
        response = self.client.post("/api/image-compression/review", json={"task_id": result["task_id"], "decision": "FAIL"})
        self.assertEqual(response.status_code, 200)
        reviewed = response.json()["data"]["result"]
        self.assertEqual(reviewed["delivery_gate_status"], "CANNOT_MEET_SAFELY")
        self.assertFalse(reviewed["delivery_eligible"])

    def test_21_technical_failure_cannot_be_force_reviewed(self):
        intake, _ = self.intake("blocked.jpg", "JPEG")
        result = self.execute(intake, "UPLOAD_ADAPTATION", {"max_file_size_bytes": 1})["result"]
        response = self.client.post("/api/image-compression/review", json={"task_id": result["task_id"], "decision": "PASS"})
        self.assertEqual(response.status_code, 409)

    def test_22_arbitrary_open_path_rejected(self):
        response = self.client.post("/api/image-compression/open-output-folder", json={
            "task_id": "anything",
            "path": "C:/Users/private",
        })
        self.assertEqual(response.status_code, 400)

    def test_23_registered_output_folder_can_be_opened(self):
        intake, _ = self.intake("open.png")
        data = self.execute(
            intake,
            "RESIZE_REDUCTION",
            {"scale_ratio": 0.5},
            current_task_output_root=str(self.current_task_output_root),
        )
        result, ui = data["result"], data["ui"]
        self.assertEqual(Path(ui["effective_output_root"]), self.current_task_output_root.resolve())
        expected_task_dir = Path(ui["output_directory"]).resolve()
        self.assertEqual(expected_task_dir.parent, self.current_task_output_root.resolve())
        self.assertEqual(expected_task_dir.name, "尺寸缩小")
        self.assertEqual(Path(ui["display_path"]), expected_task_dir)
        self.assertEqual(ui["output_root_source"], "current_task")

        lossless, _ = self.intake("same-root.png", size=(180, 120), compress_level=0)
        upload, _ = self.intake("same-root.jpg", "JPEG", size=(120, 80))
        for candidate, mode, params in (
            (lossless, "LOSSLESS_COMPRESSION", {}),
            (upload, "UPLOAD_ADAPTATION", {"max_width": 90, "max_height": 60}),
        ):
            with self.subTest(mode=mode):
                routed = self.execute(candidate, mode, params, current_task_output_root=str(self.current_task_output_root))
                self.assertEqual(Path(routed["ui"]["effective_output_root"]), self.current_task_output_root.resolve())

        response = self.client.post("/api/image-compression/open-output-folder", json={"task_id": result["task_id"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.opened), 1)
        self.assertEqual(Path(self.opened[0]), expected_task_dir)
        self.assertTrue(expected_task_dir.is_dir())

    def test_24_failures_leave_no_output_or_temporary_residue(self):
        settings = self.client.get("/api/image-compression/output-settings")
        self.assertEqual(settings.status_code, 200, settings.text)
        self.assertEqual(Path(settings.json()["data"]["effective_output_root"]), self.saved_output_root.resolve())
        changed = self.client.post("/api/image-compression/output-settings/default", json={"output_root": str(self.current_task_output_root)})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(Path(self.output_settings["saved_default_root"]), self.current_task_output_root.resolve())
        restored = self.client.post("/api/image-compression/output-settings/restore", json={})
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(Path(self.output_settings["saved_default_root"]), self.built_in_output_root.resolve())
        traversal = self.client.post("/api/image-compression/output-settings/default", json={"output_root": str(self.root / ".." / "escape")})
        self.assertEqual(traversal.status_code, 400)

        intake, _ = self.intake("no-output.jpg", "JPEG")
        before_tasks = len(self.state["task_registry"])
        response = self.client.post("/api/image-compression/run", json={
            "source_token": intake["source_token"],
            "operation_mode": "LOSSLESS_COMPRESSION",
            "params": {},
        })
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.state["task_registry"]), before_tasks)
        output_root = self.built_in_output_root
        self.assertEqual(
            sorted(path.name for path in output_root.iterdir()),
            sorted(FUNCTION_DIRECTORY_BY_MODE.values()),
        )
        self.assertFalse(any(path.is_file() for path in output_root.rglob("*")))
        self.assertFalse(any(self.root.rglob("*.tmp")))

    def test_25_production_module_has_no_experiment_dependency(self):
        project = Path(__file__).resolve().parents[2]
        production = [
            project / "backend" / "image_compression_api.py",
            *(project / "engine" / "image_compression").glob("*.py"),
        ]
        for path in production:
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("tools.experiments", source)
                self.assertNotIn("tools/experiments", source)

    def test_26_long_image_sample_detected(self):
        self.assertTrue(is_long_image(1266, 9088))

    def test_27_ordinary_four_by_five_not_misclassified(self):
        self.assertFalse(is_long_image(3200, 4000))

    def test_28_ordinary_nine_by_sixteen_not_misclassified(self):
        self.assertFalse(is_long_image(2250, 4000))

    def test_29_tall_high_resolution_image_detected(self):
        self.assertTrue(is_long_image(2000, 4001))
        self.assertFalse(is_long_image(5000, 1200))

    def test_30_jpeg_mode_preflight_creates_no_task(self):
        intake, _ = self.intake("long.jpg", "JPEG", size=(1266, 9088))
        response = self.client.post("/api/image-compression/run", json={"source_token": intake["source_token"], "operation_mode": "LOSSLESS_COMPRESSION", "params": {}})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.state["task_registry"], {})

    def test_31_jpeg_mode_preflight_creates_no_output_folder(self):
        intake, _ = self.intake("long.jpg", "JPEG", size=(1266, 9088))
        response = self.client.post("/api/image-compression/run", json={"source_token": intake["source_token"], "operation_mode": "LOSSLESS_COMPRESSION", "params": {}})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.saved_output_root.exists())

    def test_32_long_image_default_max_height_is_null(self):
        data = self.client.get("/api/image-compression/capabilities").json()["data"]
        self.assertEqual(data["defaults"]["long_image_upload_max_width"], 1080)
        self.assertIsNone(data["defaults"]["long_image_upload_max_height"])

    def test_33_long_image_75_percent_estimate(self):
        self.assertEqual(estimate_product_dimensions(1266, 9088, "RESIZE_REDUCTION", {"scale_ratio": 0.75})["width"], 950)
        self.assertEqual(estimate_product_dimensions(1266, 9088, "RESIZE_REDUCTION", {"scale_ratio": 0.75})["height"], 6816)

    def test_34_long_image_50_percent_estimate(self):
        self.assertEqual(estimate_product_dimensions(1266, 9088, "RESIZE_REDUCTION", {"scale_ratio": 0.5})["width"], 633)
        self.assertEqual(estimate_product_dimensions(1266, 9088, "RESIZE_REDUCTION", {"scale_ratio": 0.5})["height"], 4544)

    def test_35_long_image_1080_width_estimate(self):
        self.assertEqual(estimate_product_dimensions(1266, 9088, "RESIZE_REDUCTION", {"target_width": 1080}), {"width": 1080, "height": 7753, "scale": 1080 / 1266})

    def test_36_long_image_900_width_estimate(self):
        estimate = estimate_product_dimensions(1266, 9088, "RESIZE_REDUCTION", {"target_width": 900})
        self.assertEqual((estimate["width"], estimate["height"]), (900, 6461))

    def test_37_height_1080_estimates_about_150_width(self):
        estimate = estimate_product_dimensions(1266, 9088, "UPLOAD_ADAPTATION", {"max_height": 1080})
        self.assertEqual((estimate["width"], estimate["height"]), (150, 1080))

    def test_38_width_below_600_is_blocked(self):
        self.assertTrue(classify_long_image_width(599)["blocked"])

    def test_39_width_600_to_749_requires_confirmation(self):
        risk = classify_long_image_width(700)
        self.assertTrue(risk["confirmation_required"])
        self.assertFalse(risk["blocked"])

    def test_40_width_750_to_899_has_strong_warning(self):
        self.assertEqual(classify_long_image_width(800)["level"], "STRONG_WARNING")

    def test_41_width_900_to_1079_has_review_notice(self):
        self.assertEqual(classify_long_image_width(950)["level"], "REVIEW_NOTICE")

    def test_42_width_at_least_1080_still_records_review_risk(self):
        risk = classify_long_image_width(1080)
        self.assertEqual(risk["level"], "LOWER_RISK")
        self.assertFalse(risk["blocked"])

    def test_43_no_candidate_has_no_output_preview(self):
        raw = self.image_bytes("PNG", (80, 240))
        optimised, _ = optimise_png_data(raw)
        intake = self.intake_bytes(optimised, "long-optimal.png")
        data = self.execute(intake, "LOSSLESS_COMPRESSION")
        self.assertFalse(data["result"]["output_created"])
        self.assertIsNone(data["ui"]["output_preview_url"])
        self.assertFalse(data["ui"]["candidate_available"])

    def test_44_no_candidate_cannot_be_reviewed(self):
        raw = self.image_bytes("PNG", (80, 240))
        optimised, _ = optimise_png_data(raw)
        intake = self.intake_bytes(optimised, "long-optimal.png")
        result = self.execute(intake, "LOSSLESS_COMPRESSION")["result"]
        response = self.client.post("/api/image-compression/review", json={"task_id": result["task_id"], "decision": "PASS"})
        self.assertEqual(response.status_code, 409)

    def test_45_long_image_feedback_package_contains_risk_fields(self):
        intake, _ = self.intake("long-feedback.png", size=(1200, 3600), compress_level=0)
        result = self.execute(intake, "RESIZE_REDUCTION", {"target_width": 1080})["result"]
        response = self.client.post("/api/image-compression/test-feedback-package", json={"task_id": result["task_id"]})
        self.assertEqual(response.status_code, 200, response.text)
        package = response.json()["data"]
        package_path = Path(package["feedback_package_path"])
        self.assertEqual(package_path.parent.name, "尺寸缩小")
        self.assertTrue(package_path.name.endswith("_测试反馈包.zip"))
        with zipfile.ZipFile(package_path) as archive:
            validation = json.loads(archive.read("long_image_validation.json").decode("utf-8"))
        for field in (
            "is_long_image",
            "detection_basis",
            "source_aspect_ratio",
            "preview_default_mode",
            "estimated_output_dimensions",
            "actual_output_dimensions",
            "maximum_height_applied",
            "width_risk_level",
            "text_risk_warnings",
            "segment_review_status",
            "width_risk_policy_version",
        ):
            self.assertIn(field, validation)
        self.assertTrue(validation["is_long_image"])
        self.assertEqual(validation["segment_review_status"], {
            "top": "PENDING",
            "middle": "PENDING",
            "bottom": "PENDING",
        })
        self.assert_standard_feedback_files(package, long_image=True)

    def test_46_feedback_package_redacts_private_paths_and_images(self):
        intake, _ = self.intake("private-long.png", size=(1200, 3600), compress_level=0)
        result = self.execute(intake, "RESIZE_REDUCTION", {"target_width": 1080})["result"]
        package = self.client.post("/api/image-compression/test-feedback-package", json={"task_id": result["task_id"]}).json()["data"]
        package_path = Path(package["feedback_package_path"])
        with zipfile.ZipFile(package_path) as archive:
            package_text = "\n".join(
                archive.read(name).decode("utf-8")
                for name in archive.namelist()
                if name.endswith((".json", ".md", ".sha256"))
            )
        self.assertNotIn(str(self.root), package_text)
        self.assertNotIn(intake["source_token"], package_text)
        self.assertNotIn("feedback-package/", package_text)
        self.assertFalse(package["source_image_included"])
        self.assertFalse(package["output_image_included"])

    def test_47_readable_output_names_replace_uuid_first_layer(self):
        intake, _ = self.intake("中文商业长图.png", size=(1200, 3600), compress_level=0)
        data = self.execute(intake, "RESIZE_REDUCTION", {"target_short_side": 1080})
        directory = Path(data["ui"]["output_directory"])
        output = Path(data["result"]["output_path"])
        self.assertEqual(directory.name, "尺寸缩小")
        self.assertIn("_尺寸缩小_短边1080_", output.name)
        self.assertNotIn("compression_", output.name)

    def test_48_short_side_calculation_examples(self):
        cases = (
            ((1266, 9088, 1080), (1080, 7753)),
            ((1266, 9088, 900), (900, 6461)),
            ((1920, 1080, 900), (1600, 900)),
            ((1080, 1350, 900), (900, 1125)),
            ((1200, 1200, 1080), (1080, 1080)),
            ((6000, 1000, 900), (5400, 900)),
        )
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                calculated = calculate_target_by_short_side(*arguments)
                self.assertEqual((calculated["target_width"], calculated["target_height"]), expected)
                self.assertEqual(calculated["source_short_side"], min(arguments[:2]))

    def test_49_short_side_calculation_rejects_invalid_values(self):
        cases = (
            (0, 100, 50),
            (100, 0, 50),
            (100, 100, 0),
            (100, 100, None),
            (100, 100, -1),
            (100, 100, 50.5),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                calculate_target_by_short_side(*arguments)

    def test_50_short_side_api_translates_to_frozen_target_dimensions(self):
        intake, _ = self.intake("横图.png", size=(1920, 1080), compress_level=0)
        data = self.execute(intake, "RESIZE_REDUCTION", {"target_short_side": 900})
        result, ui = data["result"], data["ui"]
        self.assertEqual(result["output_dimensions"], {"width": 1600, "height": 900})
        self.assertEqual(ui["resize_strategy"], "SHORT_SIDE")
        self.assertEqual(ui["source_short_side"], 1080)
        self.assertEqual(ui["target_short_side"], 900)
        self.assertEqual((ui["estimated_target_width"], ui["estimated_target_height"]), (1600, 900))
        self.assertEqual((ui["actual_target_width"], ui["actual_target_height"]), (1600, 900))
        self.assertTrue(ui["aspect_ratio_preserved"])
        self.assertFalse(ui["crop_applied"])
        self.assertFalse(ui["padding_applied"])
        self.assertFalse(ui["upscale_applied"])
        task = self.state["task_registry"][result["task_id"]]
        self.assertNotIn("target_short_side", task["request"])
        self.assertEqual((task["request"]["target_width"], task["request"]["target_height"]), (1600, 900))

    def test_51_short_side_equal_and_upscale_are_blocked_before_task_and_root(self):
        intake, _ = self.intake("small.png", size=(1200, 900))
        for target, code in ((900, "NO_PROCESSING_NEEDED"), (1080, "TARGET_SHORT_SIDE_UPSCALE_BLOCKED")):
            with self.subTest(target=target):
                response = self.client.post("/api/image-compression/run", json={
                    "source_token": intake["source_token"],
                    "operation_mode": "RESIZE_REDUCTION",
                    "params": {"target_short_side": target},
                })
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(response.json()["detail"]["code"], code)
                self.assertEqual(self.state["task_registry"], {})
                self.assertFalse(self.saved_output_root.exists())

    def test_52_resize_parameter_modes_are_mutually_exclusive(self):
        intake, _ = self.intake("exclusive.png", size=(1200, 900))
        invalid_params = (
            {},
            {"target_short_side": 750, "scale_ratio": 0.5},
            {"target_short_side": 750, "target_width": 600},
            {"scale_ratio": 0.5, "target_height": 450},
            {"target_width": 600, "target_height": 450},
        )
        for params in invalid_params:
            with self.subTest(params=params):
                response = self.client.post("/api/image-compression/run", json={
                    "source_token": intake["source_token"],
                    "operation_mode": "RESIZE_REDUCTION",
                    "params": params,
                })
                self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.state["task_registry"], {})
        self.assertFalse(self.saved_output_root.exists())

    def test_53_fixed_directories_and_flat_results_for_all_modes(self):
        root = self.root / "flat-root"
        lossless, _ = self.intake("品牌海报.png", size=(180, 120), compress_level=0)
        resize, _ = self.intake("中文海报.png", size=(1200, 900), compress_level=0)
        upload, _ = self.intake("时装周海报.jpg", "JPEG", size=(1200, 900))
        cases = (
            (lossless, "LOSSLESS_COMPRESSION", {}, "PNG无损压缩"),
            (resize, "RESIZE_REDUCTION", {"target_short_side": 750}, "尺寸缩小"),
            (upload, "UPLOAD_ADAPTATION", {"max_width": 900, "max_file_size_bytes": 2 * 1024 * 1024}, "上传适配"),
        )
        for intake_data, mode, params, directory_name in cases:
            with self.subTest(mode=mode):
                data = self.execute(intake_data, mode, params, current_task_output_root=str(root))
                output = Path(data["result"]["output_path"])
                self.assertEqual(output.parent, root.resolve() / directory_name)
                self.assertTrue(output.is_file())
        self.assertEqual(sorted(path.name for path in root.iterdir()), sorted(FUNCTION_DIRECTORY_BY_MODE.values()))
        self.assertFalse(any(path.is_dir() for directory in root.iterdir() for path in directory.iterdir()))
        self.assertFalse(any(path.name[:4].isdigit() and path.is_dir() for path in root.rglob("*")))
        self.assertFalse(any(path.name.startswith("compression_") for path in root.rglob("*")))

    def test_54_feedback_zip_uses_same_output_stem_and_directory(self):
        intake, _ = self.intake("中文商业PPT长图.jpg", "JPEG", size=(1266, 9088))
        data = self.execute(intake, "RESIZE_REDUCTION", {"target_short_side": 1080})
        output = Path(data["result"]["output_path"])
        response = self.client.post("/api/image-compression/test-feedback-package", json={"task_id": data["result"]["task_id"]})
        self.assertEqual(response.status_code, 200, response.text)
        package = response.json()["data"]
        package_path = Path(package["feedback_package_path"])
        self.assertEqual(package_path.parent, output.parent)
        self.assertEqual(package_path.name, f"{output.stem}_测试反馈包.zip")
        self.assertEqual(package["output_stem"], output.stem)
        self.assertEqual(package["feedback_package_sha256"], hashlib.sha256(package_path.read_bytes()).hexdigest())
        self.assertEqual(package["package_name"], package_path.name)
        self.assertEqual(package["package_size_bytes"], package_path.stat().st_size)
        self.assertEqual(package["package_sha256"], hashlib.sha256(package_path.read_bytes()).hexdigest())
        self.assertEqual(package["display_path"], str(package_path))
        self.assertEqual(package["function_directory_path"], str(output.parent))
        self.assertTrue(package["can_open_folder"])
        self.assertTrue(package["created_at"])
        self.assertTrue(package["expires_at"])
        self.assertRegex(package["download_url"], r"^/api/image-compression/feedback-package/[A-Za-z0-9_-]+$")
        self.assertNotIn(str(package_path), package["download_url"])
        self.assertNotIn("file:", package["download_url"].lower())
        download = self.client.get(package["download_url"])
        self.assertEqual(download.status_code, 200, download.text)
        self.assertEqual(download.headers["content-type"], "application/zip")
        self.assertIn("attachment; filename*=UTF-8''", download.headers["content-disposition"])
        self.assertIn(quote(package_path.name, safe=""), download.headers["content-disposition"])
        self.assertEqual(hashlib.sha256(download.content).hexdigest(), package["package_sha256"])
        self.assertFalse(any(path.is_dir() for path in output.parent.iterdir()))
        with zipfile.ZipFile(package_path) as archive:
            validation = json.loads(archive.read("validation.json").decode("utf-8"))
        short_side = validation["fixed_short_side_validation"]
        self.assertTrue(short_side["applicable"])
        self.assertEqual(short_side["target_short_side"], 1080)
        self.assertEqual((short_side["actual_target_width"], short_side["actual_target_height"]), (1080, 7753))
        self.assertTrue(short_side["passed"])

    def test_55_no_candidate_can_generate_diagnostic_feedback_package(self):
        raw = self.image_bytes("PNG", (80, 60))
        optimised, _ = optimise_png_data(raw)
        intake = self.intake_bytes(optimised, "no-candidate.png")
        result = self.execute(intake, "LOSSLESS_COMPRESSION")["result"]
        response = self.client.post("/api/image-compression/test-feedback-package", json={"task_id": result["task_id"]})
        self.assertEqual(response.status_code, 200, response.text)
        package = response.json()["data"]
        package_path = Path(package["display_path"])
        self.assertEqual(package_path.parent, self.saved_output_root.resolve() / "PNG无损压缩")
        self.assertTrue(package_path.is_file())
        self.assertTrue(package_path.name.endswith("_测试反馈包.zip"))
        self.assertIn("_PNG无损压缩_", package_path.name)
        self.assertRegex(package_path.name, r"_\d{8}-\d{6}_[a-f0-9]{4}_测试反馈包\.zip$")
        self.assertEqual(hashlib.sha256(package_path.read_bytes()).hexdigest(), package["package_sha256"])
        self.assertEqual(self.client.get(package["download_url"]).status_code, 200)
        with zipfile.ZipFile(package_path) as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        self.assertEqual(manifest["output_stem"], package["output_stem"])

    def test_56_historical_directories_are_not_modified(self):
        root = self.root / "history-root"
        history = root / "compression_legacy"
        history.mkdir(parents=True)
        marker = history / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        intake, _ = self.intake("new.png", size=(1200, 900), compress_level=0)
        self.execute(intake, "RESIZE_REDUCTION", {"target_short_side": 750}, current_task_output_root=str(root))
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        self.assertTrue(history.is_dir())

    def test_57_open_function_folder_uses_current_mode_directory(self):
        response = self.client.post("/api/image-compression/open-function-folder", json={
            "operation_mode": "UPLOAD_ADAPTATION",
            "current_task_output_root": str(self.current_task_output_root),
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(Path(self.opened[-1]), self.current_task_output_root.resolve() / "上传适配")

    def test_58_exif_orientation_dimensions_are_evaluated_after_rotation(self):
        self.assertEqual(dimensions_after_exif_orientation(1200, 800, 6), (800, 1200))
        self.assertEqual(dimensions_after_exif_orientation(1200, 800, 1), (1200, 800))

    def test_59_repeated_same_name_tasks_never_overwrite(self):
        intake, _ = self.intake("同名海报.png", size=(1200, 900), compress_level=0)
        first = self.execute(intake, "RESIZE_REDUCTION", {"target_short_side": 750})
        second = self.execute(intake, "RESIZE_REDUCTION", {"target_short_side": 750})
        first_path = Path(first["result"]["output_path"])
        second_path = Path(second["result"]["output_path"])
        self.assertNotEqual(first_path, second_path)
        self.assertTrue(first_path.is_file())
        self.assertTrue(second_path.is_file())
        self.assertIn("_尺寸缩小_短边750_", first_path.name)
        self.assertIn("_尺寸缩小_短边750_", second_path.name)

    def test_60_forged_source_and_preview_tokens_cannot_download_feedback_packages(self):
        intake, _ = self.intake("token-scope.png", size=(1200, 900), compress_level=0)
        preview_token = intake["safe_preview_url"].rsplit("/", 1)[-1]
        cases = (
            "forged_feedback_package_token",
            intake["source_token"],
            preview_token,
        )
        for token in cases:
            with self.subTest(token=token):
                response = self.client.get(f"/api/image-compression/feedback-package/{token}")
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(response.json()["detail"]["code"], "FEEDBACK_PACKAGE_TOKEN_NOT_FOUND")

    def test_61_expired_feedback_token_is_rejected_and_can_be_renewed(self):
        intake, _ = self.intake("expired-link.png", size=(1200, 900), compress_level=0)
        result = self.execute(intake, "RESIZE_REDUCTION", {"target_short_side": 750})["result"]
        first = self.client.post("/api/image-compression/test-feedback-package", json={"task_id": result["task_id"]}).json()["data"]
        self.now += TOKEN_TTL_SECONDS + 1
        renewed = self.client.post("/api/image-compression/test-feedback-package", json={"task_id": result["task_id"]})
        self.assertEqual(renewed.status_code, 200, renewed.text)
        second = renewed.json()["data"]
        self.assertNotEqual(second["download_url"], first["download_url"])
        self.assertEqual(self.client.get(second["download_url"]).status_code, 200)
        expired = self.client.get(first["download_url"])
        self.assertEqual(expired.status_code, 410, expired.text)
        self.assertEqual(expired.json()["detail"]["code"], "FEEDBACK_PACKAGE_TOKEN_EXPIRED")

    def test_62_deleted_feedback_zip_returns_explicit_missing_error(self):
        intake, _ = self.intake("missing-package.png", size=(1200, 900), compress_level=0)
        result = self.execute(intake, "RESIZE_REDUCTION", {"target_short_side": 750})["result"]
        package = self.client.post("/api/image-compression/test-feedback-package", json={"task_id": result["task_id"]}).json()["data"]
        Path(package["display_path"]).unlink()
        response = self.client.get(package["download_url"])
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["detail"]["code"], "FEEDBACK_PACKAGE_FILE_MISSING")

    def test_63_cross_task_feedback_token_cannot_be_rebound_to_another_package(self):
        first_intake, _ = self.intake("first-task.png", size=(1200, 900), compress_level=0)
        second_intake, _ = self.intake("second-task.png", size=(1200, 900), compress_level=0)
        first_result = self.execute(first_intake, "RESIZE_REDUCTION", {"target_short_side": 750})["result"]
        second_result = self.execute(second_intake, "RESIZE_REDUCTION", {"target_short_side": 750})["result"]
        first_package = self.client.post("/api/image-compression/test-feedback-package", json={"task_id": first_result["task_id"]}).json()["data"]
        second_package = self.client.post("/api/image-compression/test-feedback-package", json={"task_id": second_result["task_id"]}).json()["data"]
        first_token = first_package["download_url"].rsplit("/", 1)[-1]
        self.state["token_registry"][first_token]["path"] = Path(second_package["display_path"])
        response = self.client.get(first_package["download_url"])
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"]["code"], "FEEDBACK_PACKAGE_PATH_INVALID")

    def test_64_feedback_download_route_rejects_path_traversal(self):
        response = self.client.get("/api/image-compression/feedback-package/%2E%2E%2Fprivate.zip")
        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn(str(self.root), response.text)

    def test_65_feedback_download_rejects_sha_mismatch(self):
        intake, _ = self.intake("tampered-package.png", size=(1200, 900), compress_level=0)
        result = self.execute(intake, "RESIZE_REDUCTION", {"target_short_side": 750})["result"]
        package = self.client.post("/api/image-compression/test-feedback-package", json={"task_id": result["task_id"]}).json()["data"]
        with Path(package["display_path"]).open("ab") as handle:
            handle.write(b"tampered")
        response = self.client.get(package["download_url"])
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "FEEDBACK_PACKAGE_SHA_MISMATCH")

    def test_66_repeated_no_candidate_diagnostic_packages_never_collide(self):
        raw = self.image_bytes("PNG", (80, 60))
        optimised, _ = optimise_png_data(raw)
        intake = self.intake_bytes(optimised, "repeat-diagnostic.png")
        first_result = self.execute(intake, "LOSSLESS_COMPRESSION")["result"]
        second_result = self.execute(intake, "LOSSLESS_COMPRESSION")["result"]
        first = self.client.post("/api/image-compression/test-feedback-package", json={"task_id": first_result["task_id"]})
        second = self.client.post("/api/image-compression/test-feedback-package", json={"task_id": second_result["task_id"]})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        first_package = first.json()["data"]
        second_package = second.json()["data"]
        self.assertNotEqual(first_package["package_name"], second_package["package_name"])
        self.assertNotEqual(first_package["display_path"], second_package["display_path"])
        self.assertTrue(Path(first_package["display_path"]).is_file())
        self.assertTrue(Path(second_package["display_path"]).is_file())

    def test_67_existing_feedback_package_tamper_is_not_blessed_by_regeneration(self):
        intake, _ = self.intake("tampered-regeneration.png", size=(1200, 900), compress_level=0)
        result = self.execute(intake, "RESIZE_REDUCTION", {"target_short_side": 750})["result"]
        first = self.client.post("/api/image-compression/test-feedback-package", json={"task_id": result["task_id"]}).json()["data"]
        with Path(first["display_path"]).open("ab") as handle:
            handle.write(b"tampered-after-generation")
        response = self.client.post("/api/image-compression/test-feedback-package", json={"task_id": result["task_id"]})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "FEEDBACK_PACKAGE_SHA_MISMATCH")
        record = self.state["task_registry"][result["task_id"]]
        self.assertEqual(record["feedback_package"]["package_sha256"], first["package_sha256"])
        self.assertEqual(record["feedback_package"]["download_url"], first["download_url"])

    def test_68_expired_tampered_package_is_rejected_without_new_token(self):
        intake, _ = self.intake("expired-tampered.png", size=(1200, 900), compress_level=0)
        result = self.execute(intake, "RESIZE_REDUCTION", {"target_short_side": 750})["result"]
        first = self.client.post("/api/image-compression/test-feedback-package", json={"task_id": result["task_id"]}).json()["data"]
        self.now += TOKEN_TTL_SECONDS + 1
        with Path(first["display_path"]).open("ab") as handle:
            handle.write(b"tampered-before-renewal")
        response = self.client.post("/api/image-compression/test-feedback-package", json={"task_id": result["task_id"]})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "FEEDBACK_PACKAGE_SHA_MISMATCH")
        self.assertEqual(self.client.get(first["download_url"]).status_code, 410)
        record = self.state["task_registry"][result["task_id"]]
        self.assertEqual(record["feedback_package_token"], first["download_url"].rsplit("/", 1)[-1])

    def test_69_download_revalidates_the_exact_bytes_it_returns(self):
        intake, _ = self.intake("download-race.png", size=(1200, 900), compress_level=0)
        result = self.execute(intake, "RESIZE_REDUCTION", {"target_short_side": 750})["result"]
        package = self.client.post("/api/image-compression/test-feedback-package", json={"task_id": result["task_id"]}).json()["data"]
        package_path = Path(package["display_path"])
        original_sha256_file = image_compression_api_module._sha256_file
        mutation_applied = False

        def mutate_after_initial_hash(path):
            nonlocal mutation_applied
            digest = original_sha256_file(path)
            if not mutation_applied and Path(path).resolve() == package_path.resolve():
                with package_path.open("ab") as handle:
                    handle.write(b"changed-between-validation-and-response")
                mutation_applied = True
            return digest

        with patch("backend.image_compression_api._sha256_file", side_effect=mutate_after_initial_hash):
            response = self.client.get(package["download_url"])
        self.assertTrue(mutation_applied)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "FEEDBACK_PACKAGE_SHA_MISMATCH")

    def test_70_lossless_feedback_package_has_complete_standard_structure(self):
        intake, _ = self.intake("严格无损海报.png", size=(180, 120), compress_level=0)
        result = self.execute(intake, "LOSSLESS_COMPRESSION")["result"]
        self.assertEqual(result["technical_status"], "TARGET_MET")
        self.assertEqual(result["visual_review_status"], "NOT_REQUIRED")
        self.assertEqual(result["delivery_gate_status"], "DELIVERY_READY")
        package = self.generate_feedback(result)
        standard_files = {
            "summary.md",
            "task.json",
            "result.json",
            "review.json",
            "environment.json",
            "validation.json",
            "warnings.json",
            "manifest.json",
            "manifest.sha256",
            "evidence/README.md",
        }
        with zipfile.ZipFile(package["display_path"]) as archive:
            names = set(archive.namelist())
            self.assertEqual(names, standard_files)
            summary = archive.read("summary.md").decode("utf-8")
            task = json.loads(archive.read("task.json").decode("utf-8"))
            packaged_result = json.loads(archive.read("result.json").decode("utf-8"))
            review = json.loads(archive.read("review.json").decode("utf-8"))
            warnings = json.loads(archive.read("warnings.json").decode("utf-8"))
            validation = json.loads(archive.read("validation.json").decode("utf-8"))
        self.assertIn("无需人工视觉复核，可以交付", summary)
        self.assertNotIn("仍需人工复核", summary)
        self.assertEqual(task["parameters"], {})
        self.assertEqual(task["source"]["display_name"], "严格无损海报.png")
        self.assertEqual(task["function_directory_name"], "PNG无损压缩")
        self.assertEqual(tuple(packaged_result), RESULT_FIELD_NAMES)
        self.assertEqual(len(packaged_result), 50)
        self.assertEqual(review, {
            "review_required": False,
            "visual_review_status": "NOT_REQUIRED",
            "review_result": "NOT_REQUIRED",
            "review_note": None,
            "reviewed_at": None,
            "output_sha256": result["output_sha256"],
            "reason": result["delivery_decision_reason"],
        })
        self.assertEqual(warnings, {
            "warnings": result["warnings"],
            "risk_reasons": result["risk_reasons"],
            "failure_code": result["failure_code"],
            "failure_reason": result["failure_reason"],
        })
        self.assertEqual(warnings["warnings"], [])
        self.assertIsNone(warnings["failure_code"])
        self.assertIsNone(warnings["failure_reason"])
        self.assertEqual(validation["result_contract_validation"]["field_count"], 50)
        self.assertEqual(validation["result_contract_validation"]["status"], "PASS")
        self.assertTrue(validation["source_sha256_protected"])
        self.assertTrue(validation["output_full_decode"])
        self.assertNotIn("long_image_validation.json", names)
        self.assert_standard_feedback_files(package)
        self.assert_feedback_manifest_integrity(package)

    def test_71_resize_pending_feedback_matches_real_request_and_summary(self):
        intake, _ = self.intake("短边任务.png", size=(1200, 900), compress_level=0)
        result = self.execute(intake, "RESIZE_REDUCTION", {"target_short_side": 750})["result"]
        package = self.generate_feedback(result)
        with zipfile.ZipFile(package["display_path"]) as archive:
            task = json.loads(archive.read("task.json").decode("utf-8"))
            review = json.loads(archive.read("review.json").decode("utf-8"))
            summary = archive.read("summary.md").decode("utf-8")
            validation = json.loads(archive.read("validation.json").decode("utf-8"))
        self.assertEqual(task["parameters"], {"target_short_side": 750})
        self.assertEqual(review["review_required"], True)
        self.assertEqual(review["review_result"], "PENDING")
        self.assertIsNone(review["reviewed_at"])
        self.assertIn("需要完成实际视觉复核后才能确认交付", summary)
        self.assertIn("- 视觉状态：`PENDING`", summary)
        self.assertIn("- 交付状态：`REVIEW_REQUIRED`", summary)
        self.assertTrue(validation["fixed_short_side_validation"]["passed"])
        self.assertFalse(validation["is_long_image"])
        self.assert_feedback_manifest_integrity(package)

    def test_72_upload_feedback_contains_limits_and_standard_files(self):
        intake, _ = self.intake("上传适配.jpg", "JPEG", size=(1200, 900))
        result = self.execute(
            intake,
            "UPLOAD_ADAPTATION",
            {"max_width": 900, "max_file_size_bytes": 2 * 1024 * 1024},
        )["result"]
        package = self.generate_feedback(result)
        with zipfile.ZipFile(package["display_path"]) as archive:
            task = json.loads(archive.read("task.json").decode("utf-8"))
            validation = json.loads(archive.read("validation.json").decode("utf-8"))
            names = set(archive.namelist())
        self.assertEqual(task["parameters"], {"max_width": 900, "max_file_size_bytes": 2 * 1024 * 1024})
        self.assertEqual(task["function_directory_name"], "上传适配")
        self.assertTrue(validation["upload_limit_validation"]["width_within_limit"])
        self.assertTrue(validation["upload_limit_validation"]["size_within_limit"])
        self.assertNotIn("long_image_validation.json", names)
        self.assert_standard_feedback_files(package)
        self.assert_feedback_manifest_integrity(package)

    def test_73_review_pass_with_notes_is_preserved_without_reencoding(self):
        intake, _ = self.intake("人工备注.png", size=(1200, 900), compress_level=0)
        before = self.execute(intake, "RESIZE_REDUCTION", {"target_short_side": 750})["result"]
        response = self.client.post("/api/image-compression/review", json={
            "task_id": before["task_id"],
            "decision": "PASS_WITH_NOTES",
            "note": "底部小字可读，边缘轻微变软。",
        })
        self.assertEqual(response.status_code, 200, response.text)
        after = response.json()["data"]["result"]
        self.assertEqual(after["output_sha256"], before["output_sha256"])
        package = self.generate_feedback(after)
        with zipfile.ZipFile(package["display_path"]) as archive:
            review = json.loads(archive.read("review.json").decode("utf-8"))
            summary = archive.read("summary.md").decode("utf-8")
        self.assertEqual(review["review_result"], "PASS_WITH_NOTES")
        self.assertEqual(review["review_note"], "底部小字可读，边缘轻微变软。")
        self.assertTrue(review["reviewed_at"])
        self.assertEqual(review["output_sha256_before"], before["output_sha256"])
        self.assertEqual(review["output_sha256_after"], before["output_sha256"])
        self.assertIn("结果可用，但包含人工复核备注", summary)
        self.assert_standard_feedback_files(package)

    def test_74_unsafe_task_feedback_is_diagnostic_and_never_claims_delivery(self):
        intake, _ = self.intake("无法满足.jpg", "JPEG", size=(96, 72))
        result = self.execute(intake, "UPLOAD_ADAPTATION", {"max_file_size_bytes": 1})["result"]
        self.assertIn(result["technical_status"], {"CANNOT_MEET_SAFELY", "PROCESSING_FAILED"})
        package = self.generate_feedback(result)
        with zipfile.ZipFile(package["display_path"]) as archive:
            review = json.loads(archive.read("review.json").decode("utf-8"))
            summary = archive.read("summary.md").decode("utf-8")
            warnings = json.loads(archive.read("warnings.json").decode("utf-8"))
        self.assertFalse(review["review_required"])
        self.assertEqual(review["review_result"], "NOT_AVAILABLE")
        self.assertNotIn("可以交付。", summary)
        self.assertTrue(
            "未形成可安全交付的结果" in summary
            or "仅用于诊断" in summary
        )
        self.assertEqual(warnings["failure_code"], result["failure_code"])
        self.assertEqual(warnings["failure_reason"], result["failure_reason"])
        self.assert_standard_feedback_files(package)
        self.assert_feedback_manifest_integrity(package)

    def test_75_environment_and_evidence_files_are_privacy_safe(self):
        intake, _ = self.intake("隐私审计.png", size=(1200, 900), compress_level=0)
        result = self.execute(intake, "RESIZE_REDUCTION", {"target_short_side": 750})["result"]
        package = self.generate_feedback(result)
        with zipfile.ZipFile(package["display_path"]) as archive:
            environment = json.loads(archive.read("environment.json").decode("utf-8"))
            evidence = archive.read("evidence/README.md").decode("utf-8")
            all_text = "\n".join(
                archive.read(name).decode("utf-8")
                for name in archive.namelist()
                if name.endswith((".json", ".md", ".sha256"))
            )
        self.assertEqual(set(environment), {
            "application_name",
            "application_version",
            "api_version",
            "frontend_build_version",
            "python_version",
            "node_version",
            "operating_system",
            "generated_at",
        })
        self.assertNotIn(str(self.root), all_text)
        self.assertNotIn(intake["source_token"], all_text)
        self.assertNotIn("Cookie", all_text)
        self.assertIn("默认不包含用户原图", evidence)
        self.assertIn("默认不包含输出图片", evidence)
        self.assertIn("未执行任何在线上传", evidence)
        with zipfile.ZipFile(package["display_path"]) as archive:
            self.assertFalse(any(name.lower().endswith((".png", ".jpg", ".jpeg")) for name in archive.namelist()))

    def test_76_task_lifecycle_success_uses_one_real_task_and_verified_output(self):
        intake, source_bytes = self.intake("lifecycle-success.png", size=(120, 80), alpha=True)
        cached_source = Path(self.state["token_registry"][intake["source_token"]]["path"])
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()

        data = self.execute(intake, "RESIZE_REDUCTION", {"scale_ratio": 0.5})
        task = data["task"]
        output_path = Path(task["output_path"])

        self.assertEqual(task["operation_mode"], "RESIZE_REDUCTION")
        self.assertEqual(task["feature_key"], "image_compression")
        self.assertTrue(task["result_id"].startswith("compression_result_"))
        self.assertNotEqual(task["task_id"], task["result_id"])
        self.assertEqual(task["result_file"], task["output_path"])
        self.assertEqual(task["source_path"], str(cached_source))
        self.assertEqual(task["source_path"], data["result"]["source_path"])
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["progress"], 100)
        self.assertIsNone(task["failure_reason"])
        self.assertTrue(task["created_at"])
        self.assertTrue(task["completed_at"])
        self.assertGreaterEqual(datetime.fromisoformat(task["completed_at"]), datetime.fromisoformat(task["created_at"]))
        self.assertEqual(
            [(item["task_id"], item["status"], item["progress"]) for item in task["lifecycle"]],
            [
                (task["task_id"], "pending", 0),
                (task["task_id"], "processing", 10),
                (task["task_id"], "completed", 100),
            ],
        )
        self.assertTrue(output_path.is_file())
        self.assertEqual(task["output_path"], data["result"]["output_path"])
        self.assertGreater(output_path.stat().st_size, 0)
        with Image.open(output_path) as output:
            output.load()
            self.assertEqual(output.format, "PNG")
            self.assertEqual(output.size, (60, 40))
        self.assertEqual(hashlib.sha256(cached_source.read_bytes()).hexdigest(), source_sha256)

    def test_77_task_lifecycle_failure_preserves_original_and_has_no_fake_output(self):
        source_bytes = self.image_bytes("PNG", (120, 80), alpha=True)
        original_path = self.root / "lifecycle-failure-original.png"
        original_path.write_bytes(source_bytes)
        original_sha256 = hashlib.sha256(source_bytes).hexdigest()
        intake = self.intake_bytes(source_bytes, "lifecycle-failure.png")
        cached_source = Path(self.state["token_registry"][intake["source_token"]]["path"])
        cached_source.write_bytes(b"not-a-decodable-image")

        data = self.execute(intake, "RESIZE_REDUCTION", {"scale_ratio": 0.5})
        task = data["task"]

        self.assertEqual(task["status"], "failed")
        self.assertNotEqual(task["progress"], 100)
        self.assertIsNone(task["output_path"])
        self.assertTrue(task["failure_reason"])
        self.assertEqual(task["failure_reason"], data["result"]["failure_reason"])
        self.assertEqual(data["result"]["failure_code"], "SOURCE_SHA_MISMATCH")
        self.assertTrue(task["completed_at"])
        self.assertGreaterEqual(datetime.fromisoformat(task["completed_at"]), datetime.fromisoformat(task["created_at"]))
        self.assertEqual(
            [(item["task_id"], item["status"], item["progress"]) for item in task["lifecycle"]],
            [
                (task["task_id"], "pending", 0),
                (task["task_id"], "processing", 10),
                (task["task_id"], "failed", 10),
            ],
        )
        self.assertFalse(data["result"]["output_created"])
        self.assertIsNone(data["result"]["output_path"])
        self.assertEqual(hashlib.sha256(original_path.read_bytes()).hexdigest(), original_sha256)
        self.assertFalse(any(self.root.rglob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
