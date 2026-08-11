from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

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
        cls.log_root = root / "isolated-log-root"
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
        cls.env_patch = patch.dict(
            os.environ,
            {runtime_logging.RUNTIME_ROOT_OVERRIDE_ENV: str(cls.log_root)},
            clear=False,
        )
        cls.settings_patch.start()
        cls.root_patch.start()
        cls.env_patch.start()
        cls.addClassCleanup(cls.settings_patch.stop)
        cls.addClassCleanup(cls.root_patch.stop)
        cls.addClassCleanup(cls.env_patch.stop)
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
        self.assertEqual(data["context"]["runtime"]["runtime_id"], self.client.app.state.runtime_id)

        generated = self.client.post(
            "/api/v1/feedback/bundle",
            json={"snapshot_id": data["snapshot_id"], "description": "启动后后端状态异常。"},
        )
        self.assertEqual(generated.status_code, 200, generated.text)
        payload = generated.json()["data"]["bundle_payload"]
        self.assertIsNone(payload["task"]["task_id"])
        self.assertEqual(payload["feedback_schema_version"], "HDDE-user-feedback-v2")
        self.assertRegex(payload["feedback_bundle_id"], r"^FB-\d{8}-[0-9A-F]{12}$")

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
            "status": "failed",
            "processing_stage": "source_decode",
            "source_path": r"C:\Users\private-user\某集团并购终稿.png",
            "task_context": {
                "task_id": task_id,
                "feature_key": "color_correction",
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
            json={"task_id": task_id, "source_feature": "color_correction", "stage": "ignored_page_stage"},
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
        context = report["context"]
        self.assertEqual(context["stage"], "source_decode")
        self.assertEqual(context["error"]["error_id"], "ERR-20260810-ABCD1234")
        self.assertEqual(context["task_id"], task_id)
        self.assertEqual(context["safe_input_metadata"]["width"], 640)
        self.assertLessEqual(len(report["related_events"]), 7)
        self.assertTrue(report["privacy_manifest"]["attachments_require_user_action"])
        self.assertFalse(report["privacy_manifest"]["auto_upload"])
        self.assertFalse(report["attachment_manifest"][0]["included_in_bundle"])
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("private-user", serialized)
        self.assertNotIn("某集团并购终稿.png", serialized)
        self.assertNotIn("客户目录", serialized)
        self.assertNotIn("FORMAL_BASELINE", serialized)
        self.assertEqual(self.settings_path.read_bytes(), settings_before)
        self.assertEqual(REPOSITORY_SETTINGS_PATH.read_bytes(), self.repository_settings_before)

        bundle_path = Path(data["feedback_bundle_path"])
        self.assertTrue(bundle_path.is_relative_to(self.formal_root))
        with zipfile.ZipFile(bundle_path) as archive:
            offline_report = json.loads(archive.read("feedback_report.json").decode("utf-8"))
        self.assertEqual(offline_report["feedback_bundle_id"], report["feedback_bundle_id"])
        self.assertEqual(offline_report["context"]["error"]["code_location"], "backend/image_compression_api.py:100::execute_color_task")

    def test_snapshot_contract_rejects_unknown_task_instead_of_using_latest(self):
        response = self.client.post(
            "/api/v1/feedback/context-snapshot",
            json={"task_id": "missing-task", "source_feature": "processing_center"},
        )
        self.assertEqual(response.status_code, 404, response.text)


if __name__ == "__main__":
    unittest.main()
