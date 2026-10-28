from __future__ import annotations

import io
import json
import logging
import os
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import main
from engine.diagnostics import runtime_logging
from engine.diagnostics.feedback_bundle import generate_feedback_bundle
from engine.diagnostics.feedback_context import build_feedback_context, feedback_context_preview


@contextmanager
def captured_runtime_log():
    logger = runtime_logging.initialize_console_logging()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        handler.close()


def controlled_decode_failure() -> None:
    raise RuntimeError(
        r"decode failed for C:\Users\private-user\客户并购终稿.png; token=private-value"
    )


class RuntimeDiagnosticIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        runtime_logging.reset_runtime_logging_for_tests()

    def tearDown(self) -> None:
        runtime_logging.reset_runtime_logging_for_tests()

    def test_runtime_identity_precedes_logging_and_test_log_target_is_physical_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal_root = root / "formal-user-root"
            isolated_root = root / "isolated-test-root"
            formal_log = formal_root / runtime_logging.LOG_RELATIVE_PATH
            formal_log.parent.mkdir(parents=True)
            formal_log.write_text("FORMAL_BASELINE\n", encoding="utf-8")
            baseline = formal_log.read_bytes()

            runtime_id = runtime_logging.begin_runtime(product_version="V0.5.4-dev")
            runtime_logging.configure_runtime_identity(
                product_version="V0.5.4-dev",
                build_id="V0.5.4-dev+test123.clean.20260810T000000000Z",
            )
            with patch.dict(
                os.environ,
                {runtime_logging.RUNTIME_ROOT_OVERRIDE_ENV: str(isolated_root)},
                clear=False,
            ):
                state = runtime_logging.initialize_file_logging(formal_root)
                runtime_logging.log_runtime_event("APPLICATION_STARTUP_COMPLETED", result="success")
                runtime_logging.reset_runtime_logging_for_tests()

            isolated_log = isolated_root / runtime_logging.LOG_RELATIVE_PATH
            self.assertTrue(state["isolated"])
            self.assertEqual(state["run_kind"], "test")
            self.assertEqual(Path(state["path"]), isolated_log)
            self.assertEqual(formal_log.read_bytes(), baseline)
            content = isolated_log.read_text(encoding="utf-8")
            self.assertIn(f"runtime_id={runtime_id}", content)
            self.assertIn("run_kind=test", content)
            self.assertNotIn(str(formal_root), content)

            next_runtime_id = runtime_logging.begin_runtime(product_version="V0.5.4-dev")
            self.assertNotEqual(next_runtime_id, runtime_id)

    def test_feedback_context_uses_unified_task_result_delivery_facts(self):
        context = build_feedback_context(
            {
                "task_id": "retouch_task_001",
                "feature_key": "local_retouch",
                "result_id": "retouch_result_001",
                "delivery_id": "delivery_001",
                "status": "completed",
                "source_path": r"D:\private\source.png",
                "result_file": r"D:\private\result.png",
                "failure_reason": "",
            },
            runtime={
                "product_version": "V0.5.4-dev",
                "formal_root_status": "ready",
                "runtime_id": "RUN-F3",
                "build_id": "BUILD-F3",
            },
        )
        self.assertEqual(context["feature_key"], "local_retouch")
        self.assertEqual(context["task_id"], "retouch_task_001")
        self.assertEqual(context["result_id"], "retouch_result_001")
        self.assertEqual(context["delivery_id"], "delivery_001")
        self.assertEqual(context["task_status"], "completed")
        self.assertEqual(context["product_version"], "V0.5.4-dev")
        self.assertEqual(context["formal_root_status"], "ready")
        preview = feedback_context_preview(context)
        self.assertTrue(preview["delivery_reference_available"])

    def test_root_exception_reuses_error_id_and_has_stable_fingerprint(self):
        try:
            controlled_decode_failure()
        except RuntimeError as root_error:
            first = runtime_logging.build_exception_diagnostics(
                root_error,
                error_category=runtime_logging.PRODUCT_ERROR,
                error_stage="source_decode",
            )
            try:
                raise ValueError("wrapped service failure") from root_error
            except ValueError as wrapper:
                propagated = runtime_logging.build_exception_diagnostics(
                    wrapper,
                    error_category=runtime_logging.PRODUCT_ERROR,
                    error_stage="api_request",
                )

        try:
            controlled_decode_failure()
        except RuntimeError as repeated_error:
            repeated = runtime_logging.build_exception_diagnostics(
                repeated_error,
                error_category=runtime_logging.PRODUCT_ERROR,
                error_stage="source_decode",
            )

        self.assertEqual(first["error_id"], propagated["error_id"])
        self.assertEqual(first["trace_id"], propagated["trace_id"])
        self.assertNotEqual(first["error_id"], repeated["error_id"])
        self.assertEqual(first["error_fingerprint"], repeated["error_fingerprint"])
        self.assertRegex(first["error_id"], r"^ERR-\d{8}-[0-9A-F]{8}$")
        self.assertRegex(first["error_fingerprint"], r"^EFP-[0-9A-F]{16}$")
        self.assertIn("tests/diagnostics/test_runtime_diagnostics.py", first["code_location"])
        self.assertNotIn(str(Path.cwd()), first["code_location"])
        self.assertNotIn("private-user", first["reason"])
        self.assertNotIn("客户并购终稿.png", first["reason"])
        self.assertNotIn("private-value", first["reason"])

    def test_business_trace_is_reused_by_error_and_related_event_lookup(self):
        operation = runtime_logging.new_operation_identity(
            "image_compression",
            module_id="hdde.image.compression",
        )
        try:
            controlled_decode_failure()
        except RuntimeError as exc:
            diagnostics = runtime_logging.build_exception_diagnostics(
                exc,
                error_category=runtime_logging.PRODUCT_ERROR,
                error_stage="compression_engine",
                trace_id=operation["trace_id"],
            )
        runtime_logging.log_runtime_event(
            "PROCESS_FAILED",
            level=logging.ERROR,
            stage="compression_engine",
            result="failed",
            task_id="compression_task_trace_contract",
            **{**operation, **diagnostics},
        )
        related = runtime_logging.related_runtime_events(
            operation_id=operation["operation_id"],
            trace_id=operation["trace_id"],
        )
        self.assertEqual(diagnostics["trace_id"], operation["trace_id"])
        self.assertEqual(len(related), 1)
        self.assertEqual(related[0]["operation_id"], operation["operation_id"])
        self.assertEqual(related[0]["trace_id"], operation["trace_id"])

    def test_controlled_failure_feedback_contains_only_related_safe_diagnostics(self):
        runtime_id = runtime_logging.begin_runtime(product_version="V0.5.4-dev")
        build_id = "V0.5.4-dev+test123.clean.20260810T000000000Z"
        runtime_logging.configure_runtime_identity(product_version="V0.5.4-dev", build_id=build_id)
        task_id = "color_real_task_123"
        try:
            controlled_decode_failure()
        except RuntimeError as exc:
            diagnostics = runtime_logging.build_exception_diagnostics(
                exc,
                error_category=runtime_logging.PRODUCT_ERROR,
                error_stage="color_correction_execution",
            )
        runtime_logging.log_runtime_event(
            "COLOR_CORRECTION_TASK_FAILED",
            level=logging.ERROR,
            stage="color_correction_execution",
            result="failed",
            feature="color_correction",
            task_id=task_id,
            purpose="COLOR_FIDELITY_CORRECTION",
            route_family="color_correction",
            source_reference="file_0123456789ab",
            format="PNG",
            width=16384,
            height=4096,
            color_mode="RGBA",
            channels=4,
            alpha=True,
            file_size_bucket="20-50MB",
            impact="color_correction_output_unavailable",
            **diagnostics,
        )
        related = runtime_logging.related_runtime_events(
            task_id=task_id,
            error_id=diagnostics["error_id"],
        )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            bundle = generate_feedback_bundle(
                task_id,
                {
                    "task_id": task_id,
                    "task_family": "color_correction",
                    "operation_mode": "AUTO_COLOR_CORRECTION",
                    "status": "failed",
                    "source_path": r"C:\Users\private-user\客户并购终稿.png",
                    "failure_reason": diagnostics["reason"],
                    "error_context": diagnostics,
                    "task_context": {
                        "task_id": task_id,
                        "feature_key": "color_correction",
                        "purpose": "COLOR_FIDELITY_CORRECTION",
                        "batch_id": None,
                        "route_family": "color_correction",
                        "source_reference": "file_0123456789ab",
                        "safe_input_metadata": {
                            "format": "PNG",
                            "width": 16384,
                            "height": 4096,
                            "color_mode": "RGBA",
                            "channels": 4,
                            "alpha": True,
                            "orientation": 1,
                            "file_size_bucket": "20-50MB",
                        },
                    },
                    "related_events": related,
                    "runtime_context": {
                        "app_version": "V0.5.4-dev",
                        "product_version": "V0.5.4-dev",
                        "build_id": build_id,
                        "runtime_id": runtime_id,
                        "runtime_log_reference": "诊断/日志/hdde.log",
                        "runtime_log_available": True,
                    },
                },
                output_dir=output,
            )
            self.assertEqual(bundle["feedback_bundle_status"], "PASS")
            with zipfile.ZipFile(bundle["feedback_bundle_path"]) as archive:
                report = json.loads(archive.read("feedback.json").decode("utf-8"))
                timeline = json.loads(archive.read("timeline.json").decode("utf-8"))

        context = report["common_context"]
        self.assertEqual(report["application_runtime"]["build_id"], build_id)
        self.assertEqual(report["application_runtime"]["runtime_id"], runtime_id)
        self.assertEqual(context["task_id"], task_id)
        self.assertIsNone(context["result_id"])
        self.assertEqual(context["error_id"], diagnostics["error_id"])
        self.assertEqual(context["error_fingerprint"], diagnostics["error_fingerprint"])
        self.assertEqual(report["safe_input_metadata"]["file_size_bucket"], "20-50MB")
        self.assertTrue(any(event["error_id"] == diagnostics["error_id"] for event in timeline["events"]))
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("private-user", serialized)
        self.assertNotIn("客户并购终稿.png", serialized)
        self.assertNotIn("private-value", serialized)
        self.assertNotIn(str(Path.cwd()), serialized)

    def test_startup_dependency_exception_contract_is_visible_without_starting_server(self):
        dependency = ImportError("controlled dependency unavailable")
        startup = RuntimeError("backend dependency startup failed")
        startup.__cause__ = dependency
        with captured_runtime_log() as captured, patch.object(main, "build_web_app", side_effect=startup):
            with self.assertRaises(RuntimeError):
                main.run_server(host="127.0.0.1", port=8791)
        output = captured.getvalue()
        self.assertIn("event=APPLICATION_STARTUP_FAILED", output)
        self.assertIn("stage=dependency_import", output)
        self.assertRegex(output, r"error_id=ERR-\d{8}-[0-9A-F]{8}")
        self.assertIn("exception_type=ImportError", output)
        self.assertIn("code_location=main.py", output)


if __name__ == "__main__":
    unittest.main()
