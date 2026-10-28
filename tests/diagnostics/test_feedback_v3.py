from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from engine.diagnostics import feedback_bundle
from engine.diagnostics.feedback_bundle import FEEDBACK_SCHEMA_VERSION, generate_feedback_bundle, validate_feedback_bundle
from engine.diagnostics.feedback_context import FEATURE_TRACE_CONTRACTS, build_feedback_context
from engine.storage.shared_task_registry import SharedTaskRegistry


EXPECTED_ENTRIES = ["feedback.json", "related.log", "timeline.json", "manifest.json"]
EXPECTED_FEEDBACK_FIELDS = {
    "feedback_identity", "application_runtime", "user_description", "common_context",
    "module_context", "safe_input_metadata", "output_validation", "package_completeness",
    "privacy_summary", "evaluation", "image_evidence",
}


def context_for(record: dict, feature: str) -> dict:
    return build_feedback_context(
        record,
        source_feature=feature,
        runtime={
            "product_version": "V0.5.5-dev",
            "build_id": "V0.5.5-dev+feedback-v3-test",
            "runtime_id": "RUN-FEEDBACK-V3",
            "runtime_log_available": True,
            "backend_health": "healthy",
            "settings_status": "loaded",
            "formal_root_status": "ready",
        },
        user_description=r"controlled failure at C:\Users\private\source.png; token=private-value",
        route="/processing",
    )


class FeedbackV3Tests(unittest.TestCase):
    def test_delivery_timeline_correlates_child_traces_retry_and_excludes_other_tasks(self):
        record = {
            "task_id": "TASK-COLOR",
            "feature_key": "color_correction",
            "task_family": "color_correction",
            "operation_id": "OP-COLOR",
            "trace_id": "TRACE-COLOR",
            "result_id": "RESULT-COLOR",
            "delivery_id": "DELIVERY-RETRY",
            "status": "completed",
            "processing_stage": "completed",
        }
        lines = (
            "2026-09-02T01:00:00+00:00 | INFO | event=PROCESS_STARTED | stage=engine_adapter | result=started | runtime_id=RUN-FEEDBACK-V3 | feature_key=color_correction | operation_id=OP-COLOR | task_id=TASK-COLOR | trace_id=TRACE-COLOR",
            "2026-09-02T01:00:01+00:00 | INFO | event=PROCESS_SUCCEEDED | stage=output_verification | result=review_required | runtime_id=RUN-FEEDBACK-V3 | feature_key=color_correction | operation_id=OP-COLOR | task_id=TASK-COLOR | result_id=RESULT-COLOR | trace_id=TRACE-COLOR",
            "2026-09-02T01:00:02+00:00 | INFO | event=RESULT_REGISTERED | stage=result_registry | result=review_required | runtime_id=RUN-FEEDBACK-V3 | feature_key=color_correction | operation_id=OP-COLOR | task_id=TASK-COLOR | result_id=RESULT-COLOR | trace_id=TRACE-COLOR",
            "2026-09-02T01:00:03+00:00 | INFO | event=DELIVERY_CREATED | stage=delivery_registry | result=created | runtime_id=RUN-FEEDBACK-V3 | feature_key=smart_delivery | source_feature_key=color_correction | operation_id=OP-DELIVERY-1 | parent_operation_id=OP-COLOR | task_id=TASK-COLOR | result_id=RESULT-COLOR | delivery_id=DELIVERY-FAILED | trace_id=TRACE-DELIVERY-1 | parent_trace_id=TRACE-COLOR",
            "2026-09-02T01:00:04+00:00 | INFO | event=DELIVERY_STARTED | stage=delivery_copy | result=started | runtime_id=RUN-FEEDBACK-V3 | feature_key=smart_delivery | source_feature_key=color_correction | operation_id=OP-DELIVERY-1 | parent_operation_id=OP-COLOR | task_id=TASK-COLOR | result_id=RESULT-COLOR | delivery_id=DELIVERY-FAILED | trace_id=TRACE-DELIVERY-1 | parent_trace_id=TRACE-COLOR",
            "2026-09-02T01:00:05+00:00 | ERROR | event=DELIVERY_FAILED | stage=delivery_copy | result=failed | runtime_id=RUN-FEEDBACK-V3 | feature_key=smart_delivery | source_feature_key=color_correction | operation_id=OP-DELIVERY-1 | parent_operation_id=OP-COLOR | task_id=TASK-COLOR | result_id=RESULT-COLOR | delivery_id=DELIVERY-FAILED | trace_id=TRACE-DELIVERY-1 | parent_trace_id=TRACE-COLOR",
            "2026-09-02T01:00:06+00:00 | INFO | event=DELIVERY_CREATED | stage=delivery_registry | result=created | runtime_id=RUN-FEEDBACK-V3 | feature_key=smart_delivery | source_feature_key=color_correction | operation_id=OP-DELIVERY-2 | parent_operation_id=OP-COLOR | task_id=TASK-COLOR | result_id=RESULT-COLOR | delivery_id=DELIVERY-RETRY | trace_id=TRACE-DELIVERY-2 | parent_trace_id=TRACE-COLOR | retry_of_delivery_id=DELIVERY-FAILED",
            "2026-09-02T01:00:07+00:00 | INFO | event=DELIVERY_RETRY_STARTED | stage=delivery_copy | result=started | runtime_id=RUN-FEEDBACK-V3 | feature_key=smart_delivery | source_feature_key=color_correction | operation_id=OP-DELIVERY-2 | parent_operation_id=OP-COLOR | task_id=TASK-COLOR | result_id=RESULT-COLOR | delivery_id=DELIVERY-RETRY | trace_id=TRACE-DELIVERY-2 | parent_trace_id=TRACE-COLOR | retry_of_delivery_id=DELIVERY-FAILED",
            "2026-09-02T01:00:08+00:00 | INFO | event=DELIVERY_STARTED | stage=delivery_copy | result=started | runtime_id=RUN-FEEDBACK-V3 | feature_key=smart_delivery | source_feature_key=color_correction | operation_id=OP-DELIVERY-2 | parent_operation_id=OP-COLOR | task_id=TASK-COLOR | result_id=RESULT-COLOR | delivery_id=DELIVERY-RETRY | trace_id=TRACE-DELIVERY-2 | parent_trace_id=TRACE-COLOR | retry_of_delivery_id=DELIVERY-FAILED",
            "2026-09-02T01:00:09+00:00 | INFO | event=DELIVERY_SUCCEEDED | stage=delivery_copy | result=success | runtime_id=RUN-FEEDBACK-V3 | feature_key=smart_delivery | source_feature_key=color_correction | operation_id=OP-DELIVERY-2 | parent_operation_id=OP-COLOR | task_id=TASK-COLOR | result_id=RESULT-COLOR | delivery_id=DELIVERY-RETRY | trace_id=TRACE-DELIVERY-2 | parent_trace_id=TRACE-COLOR | retry_of_delivery_id=DELIVERY-FAILED",
            "2026-09-02T01:00:10+00:00 | INFO | event=RESULT_REGISTERED | stage=result_registry | result=success | runtime_id=RUN-FEEDBACK-V3 | feature_key=enhancement_4k | operation_id=OP-4K | task_id=TASK-4K | result_id=RESULT-4K | trace_id=TRACE-4K",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_log = root / "hdde.log"
            runtime_log.write_text("\n".join(lines), encoding="utf-8")
            result = generate_feedback_bundle(
                record["task_id"],
                record,
                root / "out",
                context_snapshot=context_for(record, "color_correction"),
                runtime_log_path=runtime_log,
            )
            with zipfile.ZipFile(result["feedback_bundle_path"]) as archive:
                timeline = json.loads(archive.read("timeline.json").decode("utf-8"))
                related = archive.read("related.log").decode("utf-8")

        event_names = [event["event_type"] for event in timeline["events"]]
        self.assertEqual(timeline["timeline_status"], "PASS", timeline)
        self.assertTrue(timeline["timeline_present"])
        self.assertTrue(timeline["timeline_complete"])
        for event_name in (
            "PROCESS_STARTED",
            "PROCESS_SUCCEEDED",
            "RESULT_REGISTERED",
            "DELIVERY_CREATED",
            "DELIVERY_STARTED",
            "DELIVERY_FAILED",
            "DELIVERY_RETRY_STARTED",
            "DELIVERY_SUCCEEDED",
        ):
            self.assertIn(event_name, event_names)
        self.assertIn("DELIVERY-FAILED", related)
        self.assertIn("DELIVERY-RETRY", related)
        self.assertNotIn("TASK-4K", related)

    def test_delivery_timeline_is_partial_when_required_stage_is_missing(self):
        record = {
            "task_id": "TASK-INCOMPLETE",
            "feature_key": "color_correction",
            "operation_id": "OP-INCOMPLETE",
            "trace_id": "TRACE-INCOMPLETE",
            "result_id": "RESULT-INCOMPLETE",
            "delivery_id": "DELIVERY-INCOMPLETE",
            "status": "completed",
            "related_events": [{
                "timestamp": "2026-09-02T02:00:00+00:00",
                "event": "RESULT_REGISTERED",
                "feature_key": "color_correction",
                "operation_id": "OP-INCOMPLETE",
                "trace_id": "TRACE-INCOMPLETE",
                "task_id": "TASK-INCOMPLETE",
                "result_id": "RESULT-INCOMPLETE",
                "runtime_id": "RUN-FEEDBACK-V3",
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = generate_feedback_bundle(
                record["task_id"], record, Path(directory), context_snapshot=context_for(record, "color_correction")
            )
            with zipfile.ZipFile(result["feedback_bundle_path"]) as archive:
                timeline = json.loads(archive.read("timeline.json").decode("utf-8"))

        self.assertEqual(timeline["timeline_status"], "PARTIAL")
        self.assertTrue(timeline["timeline_present"])
        self.assertFalse(timeline["timeline_complete"])
        self.assertIn("DELIVERY_SUCCEEDED", timeline["missing_required_events"])

    def test_exact_package_schema_manifest_hashes_and_privacy(self):
        record = {
            "task_id": "TASK-V3",
            "feature_key": "color_correction",
            "task_family": "color_correction",
            "operation_id": "OP-V3",
            "trace_id": "TRACE-V3",
            "result_id": "RESULT-V3",
            "delivery_id": "DELIVERY-V3",
            "status": "completed",
            "processing_stage": "completed",
        }
        with tempfile.TemporaryDirectory() as directory:
            result = generate_feedback_bundle(
                record["task_id"], record, Path(directory), context_snapshot=context_for(record, "color_correction")
            )
            self.assertEqual(result["feedback_bundle_status"], "PASS", result)
            with zipfile.ZipFile(result["feedback_bundle_path"]) as archive:
                self.assertEqual(archive.namelist(), EXPECTED_ENTRIES)
                feedback = json.loads(archive.read("feedback.json").decode("utf-8"))
                timeline = json.loads(archive.read("timeline.json").decode("utf-8"))
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                related_log = archive.read("related.log").decode("utf-8")
                for name, entry in manifest["payload_files"].items():
                    payload = archive.read(name)
                    self.assertEqual(entry["size_bytes"], len(payload))
                    self.assertEqual(entry["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(set(feedback), EXPECTED_FEEDBACK_FIELDS)
            self.assertEqual(feedback["feedback_identity"]["schema_version"], FEEDBACK_SCHEMA_VERSION)
            self.assertEqual(manifest["package_schema_version"], FEEDBACK_SCHEMA_VERSION)
            self.assertNotIn("manifest.json", manifest["payload_files"])
            self.assertTrue(related_log.startswith("RELATED_LOG_STATUS=NOT_FOUND"))
            self.assertIsInstance(timeline["events"], list)
            serialized = json.dumps(feedback, ensure_ascii=False)
            self.assertNotIn("private-value", serialized)
            self.assertNotIn(r"C:\Users\private", serialized)
            self.assertEqual(feedback["privacy_summary"]["review_status"], "PASS")
            self.assertFalse(feedback["privacy_summary"]["contains_original_image"])
            self.assertFalse(feedback["privacy_summary"]["contains_output_image"])
            promoted = Path(result["feedback_bundle_path"])
            self.assertEqual(validate_feedback_bundle(promoted)["zip_validation"], "PASS")
            promoted.write_bytes(b"controlled-corrupt-package")
            with self.assertRaises(zipfile.BadZipFile):
                validate_feedback_bundle(promoted)

    def test_interleaved_trace_logs_are_strictly_isolated(self):
        record = {
            "task_id": "TASK-A", "feature_key": "color_correction", "task_family": "color_correction",
            "operation_id": "OP-A", "trace_id": "TRACE-A", "status": "failed", "processing_stage": "execute",
            "related_events": [{
                "timestamp": "2026-08-13T01:00:01+00:00", "event": "COLOR_CORRECTION_TASK_FAILED",
                "feature_key": "color_correction", "operation_id": "OP-A", "trace_id": "TRACE-A",
                "task_id": "TASK-A", "runtime_id": "RUN-FEEDBACK-V3", "stage": "execute", "result": "failed",
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_log = root / "hdde.log"
            runtime_log.write_text("\n".join((
                "2026-08-13T01:00:01+00:00 | ERROR | event=COLOR_CORRECTION_TASK_FAILED | stage=execute | runtime_id=RUN-FEEDBACK-V3 | feature_key=color_correction | operation_id=OP-A | task_id=TASK-A | trace_id=TRACE-A",
                "2026-08-13T01:00:01+00:00 | ERROR | event=COLOR_CORRECTION_TASK_FAILED | stage=execute | runtime_id=RUN-FEEDBACK-V3 | feature_key=color_correction | operation_id=OP-B | task_id=TASK-B | trace_id=TRACE-B",
            )), encoding="utf-8")
            result = generate_feedback_bundle(
                "TASK-A", record, root / "out", context_snapshot=context_for(record, "color_correction"), runtime_log_path=runtime_log
            )
            with zipfile.ZipFile(result["feedback_bundle_path"]) as archive:
                related = archive.read("related.log").decode("utf-8")
            self.assertIn("TRACE-A", related)
            self.assertNotIn("TRACE-B", related)
            self.assertIn("TIME_WINDOW_USED=NO", related)
            self.assertEqual(result["log_isolation"]["p1_match_count"], 1)

    def test_validation_failure_leaves_no_final_or_temporary_package(self):
        record = {"feature_key": "runtime_failure", "status": "failed"}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(feedback_bundle, "_validate_zip_payload", side_effect=ValueError("CONTROLLED_INVALID_ZIP")):
                result = generate_feedback_bundle(
                    "runtime", record, output, context_snapshot=context_for(record, "runtime_failure"),
                    feedback_bundle_id="FB-ATOMIC",
                )
            self.assertEqual(result["feedback_bundle_status"], "FAIL")
            self.assertEqual(list(output.iterdir()), [])

    def test_all_modules_and_representative_link_shapes_use_one_generator(self):
        representatives = {
            "enhancement_1080p": {"task_id": "TASK-PROCESS", "operation_id": "OP-PROCESS", "trace_id": "TRACE-PROCESS"},
            "smart_delivery": {"task_id": "TASK-DELIVERY", "result_id": "RESULT-DELIVERY", "delivery_id": "DELIVERY-1", "operation_id": "OP-DELIVERY", "trace_id": "TRACE-DELIVERY"},
            "local_retouch": {"task_id": "TASK-RETOUCH", "result_id": "RESULT-RETOUCH", "operation_id": "OP-RETOUCH", "trace_id": "TRACE-RETOUCH"},
            "runtime_failure": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for feature in FEATURE_TRACE_CONTRACTS:
                record = {"feature_key": feature, "status": "failed", **representatives.get(feature, {})}
                context = context_for(record, feature)
                result = generate_feedback_bundle(
                    str(record.get("task_id") or "runtime"), record, root, context_snapshot=context
                )
                self.assertEqual(result["feedback_bundle_status"], "PASS", feature)
                with zipfile.ZipFile(result["feedback_bundle_path"]) as archive:
                    payload = json.loads(archive.read("feedback.json").decode("utf-8"))
                self.assertEqual(payload["common_context"]["feature_key"], feature)
                self.assertNotIn("UNKNOWN", json.dumps(payload, ensure_ascii=False))

    def test_persisted_trace_facts_survive_registry_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = SharedTaskRegistry(root)
            registry["TASK-PERSISTED"] = {
                "task_id": "TASK-PERSISTED", "feature_key": "smart_delivery", "status": "completed",
                "operation_id": "OP-PERSISTED", "trace_id": "TRACE-PERSISTED",
                "result_id": "RESULT-PERSISTED", "delivery_id": "DELIVERY-PERSISTED",
            }
            reloaded = SharedTaskRegistry(root)
            persisted = reloaded["TASK-PERSISTED"]
            context = context_for(persisted, "smart_delivery")
            result = generate_feedback_bundle(
                persisted["task_id"], persisted, root / "feedback", context_snapshot=context
            )
            with zipfile.ZipFile(result["feedback_bundle_path"]) as archive:
                common = json.loads(archive.read("feedback.json"))["common_context"]
            self.assertEqual(common["trace_id"], "TRACE-PERSISTED")
            self.assertEqual(common["result_id"], "RESULT-PERSISTED")
            self.assertEqual(common["delivery_id"], "DELIVERY-PERSISTED")


if __name__ == "__main__":
    unittest.main()
