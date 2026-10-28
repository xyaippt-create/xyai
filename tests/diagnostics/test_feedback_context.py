from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from engine.diagnostics.feedback_bundle import generate_feedback_bundle
from engine.diagnostics.feedback_context import (
    FEATURE_TRACE_CONTRACTS,
    FEEDBACK_TRACE_CONTRACT_VERSION,
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
                "system_settings": PASS,
                "runtime_failure": PASS,
            },
        )
        self.assertEqual(set(FEATURE_TRACE_CONTRACTS), set(RECENT_FEATURE_COVERAGE))

    def test_all_discovered_modules_use_common_and_module_context_without_fabricated_links(self):
        required_common_fields = {
            "feature_key", "module_id", "operation_id", "trace_id",
            "task_id", "result_id", "delivery_id", "batch_id",
            "route", "stage", "status", "started_at", "completed_at",
            "error_id", "error_code", "error_fingerprint", "runtime_id", "build_id",
            "task_status", "result_status", "output_created", "second_edit_used",
            "context_binding",
        }
        for feature_key, contract in FEATURE_TRACE_CONTRACTS.items():
            with self.subTest(feature_key=feature_key):
                context = build_feedback_context(
                    {},
                    source_feature=feature_key,
                    route="/settings" if feature_key == "system_settings" else "/processing",
                    runtime={"runtime_id": "RUN-CONTRACT", "build_id": "BUILD-CONTRACT"},
                )
                trace_contract = context["feedback_trace_contract"]
                self.assertEqual(set(trace_contract["common_context"]), required_common_fields)
                self.assertEqual(trace_contract["common_context"]["module_id"], contract["module_id"])
                self.assertIsInstance(trace_contract["module_context"], dict)
                self.assertIsNone(trace_contract["common_context"]["operation_id"])
                self.assertIsNone(trace_contract["common_context"]["trace_id"])
                serialized = json.dumps(trace_contract, ensure_ascii=False)
                self.assertNotIn("UNKNOWN", serialized)
                self.assertNotIn("INFERRED", serialized)
                self.assertNotIn("FAKE", serialized)

    def test_context_uses_only_real_identifiers_and_safe_references(self):
        context = build_feedback_context(
            {
                "task_family": "color_correction",
                "task_id": "color_task_real_123",
                "module_id": "hdde.color.correction",
                "operation_id": "OP-20260813T120000-ABCDEF1234",
                "trace_id": "TRACE-0123456789AB",
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
        self.assertEqual(context["feedback_trace_contract"]["version"], FEEDBACK_TRACE_CONTRACT_VERSION)
        self.assertEqual(context["common_context"]["operation_id"], "OP-20260813T120000-ABCDEF1234")
        self.assertEqual(context["common_context"]["trace_id"], "TRACE-0123456789AB")
        self.assertEqual(context["feedback_trace_contract"]["fact_policy"], "existing_facts_only")
        self.assertEqual(context["feedback_trace_contract"]["links"]["task"], "LINKED")
        self.assertIsNone(context["result_id"])
        self.assertRegex(context["references"]["source"], r"^file_[0-9a-f]{12}\.jpg$")
        self.assertRegex(context["references"]["result"], r"^file_[0-9a-f]{12}\.jpg$")
        self.assertNotIn("source.jpg", json.dumps(context, ensure_ascii=False))
        self.assertNotIn("result.jpg", json.dumps(context, ensure_ascii=False))
        self.assertNotIn(r"D:\private", json.dumps(context, ensure_ascii=False))

    def test_explicit_user_feature_owns_module_identity_without_replacing_linked_operation(self):
        context = build_feedback_context(
            {
                "feature_key": "enhancement_1080p",
                "module_id": "hdde.enhancement.1080p",
                "operation_id": "OP-20260813T120000-ENTRY00001",
                "trace_id": "TRACE-ENTRY000001",
                "task_id": "task_real_entry_123",
            },
            source_feature="quality_confirm",
            route="/quality-report/task_real_entry_123",
        )

        common = context["common_context"]
        self.assertEqual(common["feature_key"], "quality_confirm")
        self.assertEqual(common["module_id"], "hdde.quality.confirm")
        self.assertEqual(common["operation_id"], "OP-20260813T120000-ENTRY00001")
        self.assertEqual(common["trace_id"], "TRACE-ENTRY000001")
        self.assertEqual(common["task_id"], "task_real_entry_123")

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
        self.assertIsNone(context["common_context"]["operation_id"])
        self.assertIsNone(context["common_context"]["trace_id"])
        self.assertEqual(context["feedback_trace_contract"]["links"]["task"], "NOT_APPLICABLE")
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
                payload = json.loads(archive.read("feedback.json").decode("utf-8"))
                names = archive.namelist()
            self.assertEqual(names, ["feedback.json", "related.log", "timeline.json", "manifest.json"])
            self.assertEqual(payload["feedback_identity"]["schema_version"], "HDDE-user-feedback-v3")
            self.assertEqual(payload["common_context"]["feature_key"], "processing_center")
            self.assertEqual(payload["common_context"]["stage"], "output_write")
            self.assertEqual(payload["common_context"]["task_id"], "task_real_contract")
            self.assertFalse(any(name.lower().endswith((".png", ".jpg", ".jpeg")) for name in names))


if __name__ == "__main__":
    unittest.main()
