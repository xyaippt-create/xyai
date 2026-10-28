from __future__ import annotations

import json
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from tests.support.app_runtime import isolated_runtime_logging

import main
from engine.diagnostics import runtime_logging


REPOSITORY_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "settings" / "settings.json"


class UnifiedFeedbackContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        runtime_logging.reset_runtime_logging_for_tests()
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary_directory.cleanup)
        root = Path(cls.temporary_directory.name)
        cls.formal_root = root / "isolated-formal-root"
        cls.formal_root.mkdir()
        cls.settings_path = root / "settings.json"
        cls.settings_path.write_bytes(REPOSITORY_SETTINGS_PATH.read_bytes())
        cls.repository_settings_before = REPOSITORY_SETTINGS_PATH.read_bytes()
        cls.settings_patch = patch.object(main, "SETTINGS_PATH", cls.settings_path)
        cls.root_patch = patch.object(main, "resolve_app_data_root", return_value={
            "path": str(cls.formal_root),
            "source": "test_controlled",
            "exists": True,
            "writable": True,
            "directory_ready": True,
            "error_code": "",
            "error": "",
            "message": "隔离目录已就绪。",
            "created": False,
            "first_initialization": False,
        })
        cls.runtime_log_isolation = isolated_runtime_logging("unified-feedback-real-app")
        cls.settings_patch.start()
        cls.root_patch.start()
        cls.runtime_log_isolation.__enter__()
        cls.addClassCleanup(cls.settings_patch.stop)
        cls.addClassCleanup(cls.root_patch.stop)
        cls.addClassCleanup(cls.runtime_log_isolation.__exit__, None, None, None)
        cls.addClassCleanup(runtime_logging.reset_runtime_logging_for_tests)
        cls.client = TestClient(main.build_web_app())
        cls.addClassCleanup(cls.client.close)

    def test_global_feedback_uses_runtime_fallback_without_guessing_task(self):
        response = self.client.post(
            "/api/v1/feedback/context-snapshot",
            json={"source_feature": "runtime_failure", "stage": "application_runtime"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertIsNone(data["context"]["task_id"])
        self.assertIsNone(data["context"]["result_id"])
        self.assertEqual(data["context"]["feature_key"], "runtime_failure")
        self.assertEqual(
            data["context"]["feedback_trace_contract"]["version"],
            "HDDE-feedback-trace-contract-v1",
        )
        self.assertEqual(data["context"]["feedback_trace_contract"]["fact_policy"], "existing_facts_only")
        self.assertIsNone(data["context"]["common_context"]["trace_id"])
        self.assertEqual(data["context"]["runtime"]["runtime_id"], self.client.app.state.runtime_id)

        generated = self.client.post(
            "/api/v1/feedback/bundle",
            json={"snapshot_id": data["snapshot_id"], "description": "启动后后端状态异常。"},
        )
        self.assertEqual(generated.status_code, 200, generated.text)
        data = generated.json()["data"]
        payload = data["bundle_payload"]
        self.assertIsNone(payload["common_context"]["task_id"])
        self.assertEqual(payload["feedback_identity"]["schema_version"], "HDDE-user-feedback-v3")
        self.assertRegex(payload["feedback_identity"]["feedback_bundle_id"], r"^FB-\d{8}-[0-9A-F]{12}$")
        downloaded = self.client.get(data["download_url"])
        self.assertEqual(downloaded.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
            self.assertEqual(archive.namelist(), ["feedback.json", "related.log", "timeline.json", "manifest.json"])

    def test_normal_page_feedback_without_task_id_returns_context_instead_of_400(self):
        for feature_key, route in (
            ("enhancement_1080p", "/processing"),
            ("enhancement_4k", "/processing?mode=4k_v1"),
            ("color_correction", "/color-correction"),
            ("image_compression", "/compression"),
            ("output_center", "/outputs"),
            ("smart_delivery", "/smart-delivery"),
            ("system_settings", "/settings"),
        ):
            with self.subTest(feature_key=feature_key):
                response = self.client.post(
                    "/api/v1/feedback/context-snapshot",
                    json={
                        "source_feature": feature_key,
                        "stage": "user_feedback_entry",
                        "route": route,
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)
                context = response.json()["data"]["context"]
                self.assertIsNone(context["task_id"])
                self.assertEqual(context["feature_key"], feature_key)

    def test_empty_result_file_remains_empty_in_public_task_contract(self):
        task_id = "color_review_candidate_without_formal_result"
        self.client.app.state.task_registry[task_id] = {
            "task_id": task_id,
            "task_status": "completed",
            "status": "completed",
            "feature_key": "color_correction",
            "result_id": "color_result_pending_review",
            "result_file": "",
            "output_path": "",
            "source_path": "",
            "task_result": {"result_id": "color_result_pending_review"},
        }
        try:
            response = self.client.get(f"/api/v1/tasks/{task_id}")
            self.assertEqual(response.status_code, 200, response.text)
            task = response.json()["data"]
            self.assertEqual(task["result_file"], "")
            self.assertEqual(task["output_path"], "")
        finally:
            self.client.app.state.task_registry.pop(task_id, None)

    def test_task_snapshot_does_not_drift_and_bundle_is_self_contained(self):
        task_id = "b07_color_task_001"
        runtime_logging.log_runtime_event(
            "COLOR_CORRECTION_TASK_STARTED",
            feature="color_correction",
            task_id=task_id,
            stage="source_decode",
            result="started",
        )
        task = {
            "task_id": task_id,
            "task_family": "color_correction",
            "feature_key": "color_correction",  # D61's authoritative top-level Task feature.
            "module_id": "hdde.color.correction",
            "operation_id": "OP-20260810T120000-COLOR00001",
            "trace_id": "TRACE-0123456789AB",
            "status": "failed",
            "processing_stage": "source_decode",
            "source_path": r"C:\Users\private-user\某集团并购终稿.png",
            "task_context": {
                "task_id": task_id,
                "feature_key": "color_correction",
                "module_id": "hdde.color.correction",
                "operation_id": "OP-20260810T120000-COLOR00001",
                "trace_id": "TRACE-0123456789AB",
                "purpose": "COLOR_FIDELITY_CORRECTION",
                "route_family": "color_correction",
                "source_reference": "file_0123456789ab.png",
                "safe_input_metadata": {
                    "format": "PNG",
                    "width": 640,
                    "height": 360,
                    "color_mode": "RGBA",
                    "channels": 4,
                    "alpha": True,
                    "file_size_bucket": "<1MB",
                },
            },
            "error_context": {
                "error_id": "ERR-20260810-ABCD1234",
                "error_fingerprint": "EFP-0123456789ABCDEF",
                "exception_type": "RuntimeError",
                "error_stage": "source_decode",
                "code_location": "backend/image_compression_api.py:100::execute_color_task",
                "module": "backend.image_compression_api",
                "trace_id": "TRACE-0123456789AB",
                "trace_summary": "backend/image_compression_api.py:100::execute_color_task",
                "reason": "controlled decode failure",
            },
        }
        self.client.app.state.task_registry[task_id] = task
        settings_before = self.settings_path.read_bytes()
        capture = self.client.post(
            "/api/v1/feedback/context-snapshot",
            json={
                "task_id": task_id,
                "source_feature": "color_correction",
                "stage": "ignored_page_stage",
                "route": "/color-correction",
            },
        )
        self.assertEqual(capture.status_code, 200, capture.text)
        snapshot = capture.json()["data"]

        task["processing_stage"] = "different_later_stage"
        task["error_context"]["error_id"] = "ERR-CHANGED-LATER"
        generated = self.client.post(
            "/api/v1/feedback/bundle",
            json={
                "snapshot_id": snapshot["snapshot_id"],
                "description": r"打开 C:\Users\private-user\客户目录 后处理失败。",
                "attachment_manifest": [{"extension": ".png", "size_bytes": 1024, "selected_by_user": True}],
            },
        )
        self.assertEqual(generated.status_code, 200, generated.text)
        data = generated.json()["data"]
        report = data["bundle_payload"]
        context = report["common_context"]
        self.assertEqual(context["stage"], "source_decode")
        self.assertEqual(context["error_id"], "ERR-20260810-ABCD1234")
        self.assertEqual(context["task_id"], task_id)
        self.assertEqual(context["operation_id"], "OP-20260810T120000-COLOR00001")
        self.assertEqual(context["trace_id"], "TRACE-0123456789AB")
        self.assertEqual(context["route"], "/color-correction")
        self.assertEqual(report["safe_input_metadata"]["width"], 640)
        self.assertFalse(report["privacy_summary"]["auto_upload"])
        self.assertFalse(report["privacy_summary"]["selected_attachments"][0]["included_in_bundle"])
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("private-user", serialized)
        self.assertNotIn("某集团并购终稿.png", serialized)
        self.assertNotIn("客户目录", serialized)
        self.assertNotIn("FORMAL_BASELINE", serialized)
        self.assertEqual(self.settings_path.read_bytes(), settings_before)
        self.assertEqual(REPOSITORY_SETTINGS_PATH.read_bytes(), self.repository_settings_before)

        self.assertNotIn("feedback_bundle_path", data)
        downloaded = self.client.get(data["download_url"])
        self.assertEqual(downloaded.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
            offline_report = json.loads(archive.read("feedback.json").decode("utf-8"))
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        self.assertEqual(offline_report["feedback_identity"]["feedback_bundle_id"], report["feedback_identity"]["feedback_bundle_id"])
        self.assertEqual(manifest["package_validation_status"], "PASS")

    def test_snapshot_contract_rejects_unknown_task_instead_of_using_latest(self):
        response = self.client.post(
            "/api/v1/feedback/context-snapshot",
            json={"task_id": "missing-task", "source_feature": "processing_center"},
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_t59_structured_evaluation_binding_and_image_consent(self):
        task_id = "t59_feedback_task_001"
        source_path = self.formal_root / "输入" / "t59" / "source.png"
        result_path = self.formal_root / "输出" / "t59" / "result.png"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (16, 12), "navy").save(source_path)
        Image.new("RGB", (16, 12), "white").save(result_path)
        self.client.app.state.task_registry[task_id] = {
            "task_id": task_id,
            "task_status": "completed",
            "status": "completed",
            "feature_key": "local_retouch",
            "result_id": "t59_result_001",
            "result_status": "available",
            "delivery_id": "t59_delivery_001",
            "source_path": str(source_path),
            "result_file": str(result_path),
            "output_created": True,
            "second_edit_used": False,
            "task_result": {"result_id": "t59_result_001", "output_path": str(result_path)},
        }

        def capture_snapshot() -> str:
            response = self.client.post(
                "/api/v1/feedback/context-snapshot",
                json={"task_id": task_id, "source_feature": "local_retouch", "route": "/local-retouch"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            common = response.json()["data"]["context"]["common_context"]
            self.assertEqual(common["task_id"], task_id)
            self.assertEqual(common["result_id"], "t59_result_001")
            self.assertEqual(common["delivery_id"], "t59_delivery_001")
            self.assertEqual(common["task_status"], "completed")
            self.assertEqual(common["result_status"], "available")
            self.assertIs(common["output_created"], True)
            self.assertIs(common["second_edit_used"], False)
            return response.json()["data"]["snapshot_id"]

        def generate(decision, reasons, source=False, result=False):
            response = self.client.post(
                "/api/v1/feedback/bundle",
                json={
                    "snapshot_id": capture_snapshot(),
                    "description": "T59 内测反馈，自由文本继续保留。",
                    "evaluation": {"decision": decision, "reasons": reasons},
                    "evidence_consent": {
                        "include_source_image": source,
                        "include_result_image": result,
                    },
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()["data"]
            downloaded = self.client.get(data["download_url"])
            self.assertEqual(downloaded.status_code, 200, downloaded.text)
            archive = zipfile.ZipFile(io.BytesIO(downloaded.content))
            feedback = json.loads(archive.read("feedback.json").decode("utf-8"))
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            return archive, feedback, manifest

        try:
            for decision, reasons in (
                ("ACCEPTED", []),
                ("NEEDS_ADJUSTMENT", ["EDGE_ARTIFACT"]),
                ("UNUSABLE", ["TEXT_OR_LOGO_DAMAGE"]),
            ):
                archive, feedback, _ = generate(decision, reasons)
                self.assertEqual(feedback["evaluation"], {"decision": decision, "reasons": reasons})
                self.assertEqual(feedback["user_description"], "T59 内测反馈，自由文本继续保留。")
                self.assertEqual(archive.namelist(), ["feedback.json", "related.log", "timeline.json", "manifest.json"])
                self.assertEqual(feedback["image_evidence"]["source_image"]["status"], "NOT_AUTHORIZED")
                self.assertEqual(feedback["image_evidence"]["result_image"]["status"], "NOT_AUTHORIZED")
                archive.close()

            archive, feedback, manifest = generate("NEEDS_ADJUSTMENT", ["EDGE_ARTIFACT"], result=True)
            self.assertNotIn("evidence/source.png", archive.namelist())
            self.assertEqual(archive.read("evidence/result.png"), result_path.read_bytes())
            self.assertEqual(feedback["image_evidence"]["result_image"]["status"], "INCLUDED")
            self.assertIn("evidence/result.png", manifest["evidence_files"])
            archive.close()

            archive, feedback, manifest = generate("UNUSABLE", ["TEXT_OR_LOGO_DAMAGE"], source=True, result=True)
            self.assertEqual(archive.read("evidence/source.png"), source_path.read_bytes())
            self.assertEqual(archive.read("evidence/result.png"), result_path.read_bytes())
            self.assertTrue(feedback["privacy_summary"]["image_consent_enforced"])
            self.assertTrue(feedback["privacy_summary"]["contains_original_image"])
            self.assertTrue(feedback["privacy_summary"]["contains_output_image"])
            self.assertEqual(manifest["package_validation_status"], "PASS")
            self.assertEqual(feedback["application_runtime"]["product_version"], main.APP_VERSION)
            archive.close()

            source_path.unlink()
            archive, feedback, _ = generate("NEEDS_ADJUSTMENT", ["LOCAL_DAMAGE"], source=True)
            self.assertNotIn("evidence/source.png", archive.namelist())
            self.assertEqual(feedback["image_evidence"]["status"], "PARTIAL")
            self.assertEqual(feedback["image_evidence"]["failure_code"], "EVIDENCE_ATTACHMENT_FAILED")
            self.assertEqual(feedback["image_evidence"]["source_image"]["status"], "FILE_NOT_FOUND")
            archive.close()
        finally:
            self.client.app.state.task_registry.pop(task_id, None)

    def test_compatibility_feedback_rejects_default_task_identity_instead_of_using_latest(self):
        source = io.BytesIO()
        Image.new("RGB", (8, 8), "white").save(source, format="PNG")
        uploaded = self.client.post(
            "/api/upload",
            files={"file": ("feedback-latest-guard.png", source.getvalue(), "image/png")},
            data={"mode": "fidelity", "output_profile": "delivery_1080p", "output_format": "png"},
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)

        response = self.client.post(
            f"/api/v1/tasks/{main.DEFAULT_TASK_ID}/feedback-bundle",
            json={"source_feature": "enhancement_1080p", "description": "验证反馈不得猜测最近任务。"},
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "CONTEXT_NOT_RESOLVABLE")

    def test_real_task_compat_feedback_endpoint_uses_safe_v3_defaults(self):
        task_id = "t59r_compat_feedback_task_001"
        result_id = "t59r_compat_feedback_result_001"
        source_path = self.formal_root / "输入" / "t59r" / "source.png"
        result_path = self.formal_root / "输出" / "t59r" / "result.png"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (12, 10), "navy").save(source_path)
        Image.new("RGB", (12, 10), "white").save(result_path)
        self.client.app.state.task_registry[task_id] = {
            "task_id": task_id,
            "task_status": "completed",
            "status": "completed",
            "overall_result": "worse",
            "feature_key": "enhancement_1080p",
            "result_id": result_id,
            "result_status": "available",
            "source_path": str(source_path),
            "result_file": str(result_path),
            "output_created": True,
            "task_result": {"result_id": result_id, "output_path": str(result_path)},
        }

        try:
            response = self.client.post(
                f"/api/v1/tasks/{task_id}/feedback-bundle",
                json={
                    "source_feature": "enhancement_1080p",
                    "description": "兼容端点自由文本反馈。",
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["success"])
            data = response.json()["data"]
            self.assertEqual(data["feedback_bundle_status"], "PASS")

            downloaded = self.client.get(data["download_url"])
            self.assertEqual(downloaded.status_code, 200, downloaded.text)
            with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
                self.assertEqual(
                    archive.namelist(),
                    ["feedback.json", "related.log", "timeline.json", "manifest.json"],
                )
                feedback = json.loads(archive.read("feedback.json").decode("utf-8"))
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                timeline = json.loads(archive.read("timeline.json").decode("utf-8"))
                related_log = archive.read("related.log").decode("utf-8")

            self.assertEqual(feedback["common_context"]["task_id"], task_id)
            self.assertEqual(feedback["common_context"]["result_id"], result_id)
            self.assertEqual(feedback["common_context"]["task_status"], "completed")
            self.assertEqual(feedback["application_runtime"]["product_version"], main.APP_VERSION)
            self.assertEqual(feedback["user_description"], "兼容端点自由文本反馈。")
            self.assertEqual(feedback["evaluation"], {"decision": None, "reasons": []})
            self.assertEqual(feedback["image_evidence"]["status"], "NOT_REQUESTED")
            self.assertEqual(feedback["image_evidence"]["source_image"]["status"], "NOT_AUTHORIZED")
            self.assertEqual(feedback["image_evidence"]["result_image"]["status"], "NOT_AUTHORIZED")
            self.assertFalse(feedback["image_evidence"]["source_image"]["requested_by_user"])
            self.assertFalse(feedback["image_evidence"]["result_image"]["requested_by_user"])
            self.assertFalse(feedback["privacy_summary"]["contains_original_image"])
            self.assertFalse(feedback["privacy_summary"]["contains_output_image"])
            self.assertEqual(manifest["evidence_files"], {})
            self.assertEqual(manifest["package_validation_status"], "PASS")
            self.assertIsInstance(timeline, dict)
            self.assertTrue(related_log.startswith("RELATED_LOG_STATUS="))

            stored_task = self.client.app.state.task_registry[task_id]
            self.assertEqual(stored_task["task_status"], "completed")
            self.assertEqual(stored_task["overall_result"], "worse")
        finally:
            self.client.app.state.task_registry.pop(task_id, None)

    def test_t59_global_feedback_remains_available_without_task_context(self):
        capture = self.client.post(
            "/api/v1/feedback/context-snapshot",
            json={"source_feature": "runtime_failure", "stage": "application_runtime"},
        )
        self.assertEqual(capture.status_code, 200, capture.text)
        generated = self.client.post(
            "/api/v1/feedback/bundle",
            json={
                "snapshot_id": capture.json()["data"]["snapshot_id"],
                "description": "无任务上下文反馈。",
                "evaluation": {"decision": "ACCEPTED", "reasons": []},
                "evidence_consent": {"include_source_image": False, "include_result_image": False},
            },
        )
        self.assertEqual(generated.status_code, 200, generated.text)
        payload = generated.json()["data"]["bundle_payload"]
        self.assertIsNone(payload["common_context"]["task_id"])
        self.assertIsNone(payload["common_context"]["result_id"])
        self.assertEqual(payload["common_context"]["context_binding"], "UNAVAILABLE")

    def test_empty_upload_failure_binds_exact_feedback_target_without_runtime_error_override(self):
        upload = self.client.post(
            "/api/upload",
            files={"file": ("empty.png", b"", "image/png")},
            data={"mode": "fidelity", "output_profile": "delivery_1080p", "output_format": "png"},
        )
        self.assertEqual(upload.status_code, 400, upload.text)
        payload = upload.json()
        self.assertEqual(payload["detail"], "上传图片为空。")
        target = payload["feedback_target"]
        self.assertEqual(target["feature_key"], "enhancement_1080p")
        self.assertEqual(target["route"], "fidelity")
        self.assertEqual(target["stage"], "input_validation")
        self.assertRegex(target["operation_id"], r"^OP-")
        self.assertRegex(target["trace_id"], r"^TRACE-")
        self.assertRegex(target["task_id"], r"^task_")

        capture = self.client.post(
            "/api/v1/feedback/context-snapshot",
            json={
                "source_feature": "processing_center",
                "stage": "user_feedback_entry",
                "route": "/processing",
                "feedback_target": target,
            },
        )
        self.assertEqual(capture.status_code, 200, capture.text)
        context = capture.json()["data"]["context"]
        common = context["common_context"]
        self.assertEqual(common["feature_key"], "enhancement_1080p")
        self.assertEqual(common["operation_id"], target["operation_id"])
        self.assertEqual(common["trace_id"], target["trace_id"])
        self.assertEqual(common["task_id"], target["task_id"])
        self.assertEqual(common["route"], "fidelity")
        self.assertEqual(common["stage"], "input_validation")
        self.assertEqual(context["error"]["summary"], "上传图片为空。")
        self.assertNotEqual(context["error"]["code"], "SETTINGS_NOT_LOADED")
        self.assertTrue(context["related_events"])
        for event in context["related_events"]:
            self.assertEqual(event.get("trace_id"), target["trace_id"])
            self.assertEqual(event.get("feature_key"), "enhancement_1080p")


class FeedbackFeatureIdentityTests(unittest.TestCase):
    # Reuse isolation only, without inheriting and rerunning the existing contract methods.
    setUpClass = classmethod(UnifiedFeedbackContractTests.setUpClass.__func__)
    def test_feature_and_result_positive_negative_contract(self):
        cases = [
            ("legal", "color_correction", None, 200),
            ("missing_task_feature", None, None, 409),
            ("wrong_task_feature", "image_compression", None, 409),
            ("wrong_target_feature", "color_correction", {"feature_key": "image_compression"}, 409),
            ("unknown_target_feature", "color_correction", {"feature_key": "unknown"}, 400),
            ("missing_target_feature", "color_correction", {}, 400),
            ("result_conflict", "color_correction", {"feature_key": "color_correction", "result_id": "OTHER-RESULT"}, 409),
        ]
        for label, feature, target, expected in cases:
            with self.subTest(label=label):
                task_id = "feature-contract-" + label
                record = {"task_id": task_id, "task_family": "color_correction", "status": "completed", "result_id": "CONTRACT-RESULT"}
                if feature is not None:
                    record["feature_key"] = feature
                self.client.app.state.task_registry[task_id] = record
                try:
                    request = {"task_id": task_id, "source_feature": "color_correction", "route": "/color-correction"}
                    if target is not None:
                        request["feedback_target"] = {**target, "task_id": task_id}
                    response = self.client.post("/api/v1/feedback/context-snapshot", json=request)
                    self.assertEqual(response.status_code, expected, response.text)
                    if expected == 200:
                        self.assertEqual(response.json()["data"]["context"]["feature_key"], "color_correction")
                finally:
                    self.client.app.state.task_registry.pop(task_id, None)


if __name__ == "__main__":
    unittest.main()
