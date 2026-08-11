from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from engine.diagnostics.feedback_bundle import generate_feedback_bundle
from engine.diagnostics.feedback_context import (
    PASS,
    RECENT_FEATURE_COVERAGE,
    build_feedback_context,
)


class FeedbackContextTests(unittest.TestCase):
    def test_feedback_context_covers_current_public_feature_facts(self):
        self.assertEqual(
            RECENT_FEATURE_COVERAGE,
            {
                "enhancement_1080p": PASS,
                "enhancement_4k": PASS,
                "image_compression": PASS,
                "color_correction": PASS,
                "batch_processing": PASS,
                "processing_center": PASS,
                "quality_confirm": PASS,
                "output_center": PASS,
                "smart_delivery": PASS,
                "local_retouch": PASS,
                "image_diagnosis": PASS,
                "runtime_failure": PASS,
            },
        )

    def test_context_uses_only_real_identifiers_and_safe_references(self):
        context = build_feedback_context(
            {
                "task_family": "color_correction",
                "task_id": "color_task_real_123",
                "operation_mode": "AUTO_COLOR_CORRECTION",
                "status": "completed",
                "source_path": r"D:\private\source.jpg",
                "output_path": r"D:\private\result.jpg",
                "result_review_status": "confirmed",
                "result": {},
            },
            runtime={"app_version": "V0.5.4-dev", "backend_health": "healthy"},
        )

        self.assertEqual(context["feature"]["key"], "color_correction")
        self.assertEqual(context["task_id"], "color_task_real_123")
        self.assertIsNone(context["result_id"])
        self.assertRegex(context["references"]["source"], r"^file_[0-9a-f]{12}\.jpg$")
        self.assertRegex(context["references"]["result"], r"^file_[0-9a-f]{12}\.jpg$")
        self.assertNotIn("source.jpg", json.dumps(context, ensure_ascii=False))
        self.assertNotIn("result.jpg", json.dumps(context, ensure_ascii=False))
        self.assertNotIn(r"D:\private", json.dumps(context, ensure_ascii=False))

    def test_runtime_failure_context_is_truthful_and_redacted(self):
        context = build_feedback_context(
            {},
            source_feature="runtime_failure",
            runtime={
                "app_version": "V0.5.4-dev",
                "build_id": "V0.5.4-dev+abc1234.dirty.20260810T000000000Z",
                "runtime_status": "degraded",
                "backend_health": "unavailable",
                "backend_connection_status": "failed",
                "frontend_connection_status": "proxy_failed",
                "error_type": "ImportError",
                "error_code": "ONNXRUNTIME_IMPORT_FAILED",
                "error_stage": "backend_startup",
                "error_summary": r"onnxruntime import failed at C:\Users\private\runtime; token=secret-value",
                "runtime_log_reference": "诊断/日志/hdde.log",
                "runtime_log_available": True,
            },
            user_description="后端无法启动",
        )

        self.assertEqual(context["feature"]["key"], "runtime_failure")
        self.assertIsNone(context["task_id"])
        self.assertIsNone(context["result_id"])
        self.assertEqual(context["runtime"]["error_code"], "ONNXRUNTIME_IMPORT_FAILED")
        serialized = json.dumps(context, ensure_ascii=False)
        self.assertNotIn("secret-value", serialized)
        self.assertNotIn(r"C:\Users\private", serialized)

    def test_existing_feedback_bundle_embeds_context_without_user_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = generate_feedback_bundle(
                "task_real_contract",
                {
                    "task_id": "task_real_contract",
                    "task_status": "failed",
                    "current_stage": "output_write",
                    "error_code": "OUTPUT_WRITE_FAILED",
                    "error_message": "输出失败",
                    "source_feature": "processing_center",
                    "runtime_context": {
                        "app_version": "V0.5.4-dev",
                        "backend_health": "healthy",
                        "runtime_log_reference": "诊断/日志/hdde.log",
                        "runtime_log_available": True,
                    },
                },
                output_dir=root,
            )

            self.assertEqual(result["feedback_bundle_status"], "PASS")
            with zipfile.ZipFile(result["feedback_bundle_path"]) as archive:
                payload = json.loads(archive.read("feedback_report.json").decode("utf-8"))
                names = archive.namelist()
            self.assertEqual(payload["context"]["feature"]["key"], "processing_center")
            self.assertEqual(payload["context"]["stage"], "output_write")
            self.assertEqual(payload["context"]["task_id"], "task_real_contract")
            self.assertFalse(any(name.lower().endswith((".png", ".jpg", ".jpeg")) for name in names))


if __name__ == "__main__":
    unittest.main()
