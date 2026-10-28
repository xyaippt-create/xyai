from __future__ import annotations

import tempfile
import threading
import unittest
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from tests.support.app_runtime import isolated_runtime_logging

import main
from backend.image_compression_api import register_image_compression_routes
from engine.storage.shared_task_registry import SharedTaskRegistry


class TaskRecordDeletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="hdde-task-delete-")
        self.root = Path(self.temp_dir.name)
        self.runtime_log_isolation = isolated_runtime_logging("task-record-deletion")
        self.runtime_log_isolation.__enter__()
        self.registry = SharedTaskRegistry(self.root)

    def tearDown(self) -> None:
        logger = logging.getLogger("hdde.runtime")
        for handler in list(logger.handlers):
            if getattr(handler, "_hdde_runtime_handler", None) == "file":
                logger.removeHandler(handler)
                handler.close()
        self.runtime_log_isolation.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_pending_delete_removes_aliases_and_survives_restart(self) -> None:
        record = {"task_id": "task_pending", "status": "pending", "execution_started": False}
        self.registry["task_pending"] = record
        self.registry["task_vmp_v03_core"] = record

        outcome = self.registry.delete_task_fact("task_pending")

        self.assertTrue(outcome["deleted"])
        self.assertNotIn("task_pending", self.registry)
        self.assertNotIn("task_vmp_v03_core", self.registry)
        restarted = SharedTaskRegistry(self.root)
        self.assertNotIn("task_pending", restarted)
        self.assertNotIn("task_vmp_v03_core", restarted)

    def test_completed_delete_keeps_result_delivery_and_output(self) -> None:
        output = self.root / "output.png"
        output.write_bytes(b"formal-output")
        self.registry["task_completed"] = {
            "task_id": "task_completed",
            "feature_key": "enhancement_1080p",
            "module_id": "hdde.enhancement.1080p",
            "operation_id": "OP-20260813T120000-DELETE0001",
            "trace_id": "TRACE-DELETE000001",
            "status": "completed",
            "execution_started": True,
            "result_id": "result_completed",
            "delivery_id": "delivery_completed",
            "source_path": str(self.root / "source.png"),
            "result_file": str(output),
            "output_path": str(output),
            "task_result": {
                "task_id": "task_completed",
                "result_id": "result_completed",
                "delivery_id": "delivery_completed",
                "result_file": str(output),
            },
        }

        outcome = self.registry.delete_task_fact("task_completed")

        self.assertTrue(outcome["deleted"])
        self.assertTrue(outcome["result_preserved"])
        self.assertNotIn("task_completed", self.registry)
        self.assertTrue(output.is_file())
        restarted = SharedTaskRegistry(self.root)
        result = restarted["result_completed"]
        self.assertEqual(result["record_kind"], "result")
        self.assertEqual(result["source_task_id"], "task_completed")
        self.assertEqual(result["delivery_id"], "delivery_completed")
        self.assertEqual(result["operation_id"], "OP-20260813T120000-DELETE0001")
        self.assertEqual(result["trace_id"], "TRACE-DELETE000001")
        self.assertEqual(Path(result["result_file"]), output)
        self.assertEqual(restarted.result_reference_for_task("task_completed")["result_id"], "result_completed")

    def test_missing_retained_result_and_delivery_are_marked_unavailable_without_restoring_task(self) -> None:
        missing_result = self.root / "missing-result.png"
        missing_delivery = self.root / "missing-delivery.png"
        self.registry["result_missing"] = {
            "record_kind": "result",
            "result_id": "result_missing",
            "task_id": "task_deleted",
            "source_task_id": "task_deleted",
            "status": "completed",
            "result_file": str(missing_result),
            "output_path": str(missing_result),
            "task_result": {
                "result_id": "result_missing",
                "final_output_exists": True,
                "output_path_exists": True,
            },
            "deliveries": [
                {
                    "delivery_id": "delivery_missing",
                    "status": "completed",
                    "delivery_file": str(missing_delivery),
                    "delivery_path": str(missing_delivery),
                }
            ],
        }

        outcome = self.registry.reconcile_file_availability(Path)

        self.assertEqual(outcome["unavailable_result_ids"], ["result_missing"])
        self.assertEqual(outcome["unavailable_delivery_ids"], ["delivery_missing"])
        record = self.registry["result_missing"]
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["record_kind"], "result")
        self.assertFalse(record["result_available"])
        self.assertEqual(record["result_file_status"], "FILE_UNAVAILABLE")
        self.assertFalse(record["task_result"]["final_output_exists"])
        self.assertFalse(record["task_result"]["output_path_exists"])
        self.assertFalse(record["deliveries"][0]["file_available"])
        self.assertEqual(record["deliveries"][0]["file_status"], "FILE_UNAVAILABLE")
        self.assertNotIn("task_deleted", self.registry)
        restarted = SharedTaskRegistry(self.root)
        self.assertNotIn("task_deleted", restarted)
        self.assertFalse(restarted.result_reference_for_task("task_deleted")["result_available"])

    def test_non_file_structured_result_survives_task_delete(self) -> None:
        structured_result = {
            "task_id": "task_quality_review",
            "result_id": "result_quality_review",
            "result_type": "structured_quality_review",
            "status": "completed",
            "review_findings": {"status": "approved"},
        }
        self.registry["task_quality_review"] = {
            "task_id": "task_quality_review",
            "feature_key": "quality_confirm",
            "status": "completed",
            "result_id": "result_quality_review",
            "result": structured_result,
            "task_result": structured_result,
        }

        outcome = self.registry.delete_task_fact("task_quality_review")

        self.assertTrue(outcome["deleted"])
        self.assertTrue(outcome["result_preserved"])
        self.assertNotIn("task_quality_review", self.registry)
        restarted = SharedTaskRegistry(self.root)
        result = restarted["result_quality_review"]
        self.assertEqual(result["record_kind"], "result")
        self.assertEqual(result["source_task_id"], "task_quality_review")
        self.assertEqual(result["result_file"], "")
        self.assertEqual(result["result"]["result_type"], "structured_quality_review")
        self.assertEqual(result["result"]["review_findings"], structured_result["review_findings"])

    def test_running_and_already_started_pending_tasks_are_protected(self) -> None:
        for task_id, record, expected_reason in (
            ("task_running", {"task_id": "task_running", "status": "running"}, "task_running"),
            ("task_processing", {"task_id": "task_processing", "status": "processing"}, "task_running"),
            (
                "task_scheduled",
                {"task_id": "task_scheduled", "status": "pending", "execution_started": True},
                "task_already_started",
            ),
        ):
            with self.subTest(task_id=task_id):
                self.registry[task_id] = record
                outcome = self.registry.delete_task_fact(task_id)
                self.assertFalse(outcome["deleted"])
                self.assertEqual(outcome["reason"], expected_reason)
                self.assertIn(task_id, self.registry)

    def test_execution_claim_and_delete_are_atomic(self) -> None:
        self.registry["task_race"] = {"task_id": "task_race", "status": "pending", "execution_started": False}
        barrier = threading.Barrier(2)

        def claim() -> bool:
            barrier.wait()
            return self.registry.claim_task_execution("task_race")

        def delete() -> dict:
            barrier.wait()
            return self.registry.delete_task_fact("task_race")

        with ThreadPoolExecutor(max_workers=2) as pool:
            claim_result = pool.submit(claim)
            delete_result = pool.submit(delete)
            claimed = claim_result.result(timeout=5)
            deleted = delete_result.result(timeout=5)

        self.assertNotEqual(claimed, bool(deleted["deleted"]))
        if claimed:
            self.assertEqual(deleted["reason"], "task_already_started")
            self.assertIn("task_race", self.registry)
        else:
            self.assertTrue(deleted["deleted"])
            self.assertNotIn("task_race", self.registry)

    def test_mixed_status_delete_removes_only_safe_records(self) -> None:
        records = {
            "task_pending": {"task_id": "task_pending", "status": "pending", "execution_started": False},
            "task_completed": {"task_id": "task_completed", "status": "completed"},
            "task_failed": {"task_id": "task_failed", "status": "failed"},
            "task_cancelled": {"task_id": "task_cancelled", "status": "cancelled"},
            "task_processing": {"task_id": "task_processing", "status": "processing"},
            "task_blocked": {"task_id": "task_blocked", "status": "blocked"},
        }
        for task_id, record in records.items():
            self.registry[task_id] = record

        outcomes = {task_id: self.registry.delete_task_fact(task_id) for task_id in records}

        self.assertEqual(
            {task_id for task_id, outcome in outcomes.items() if outcome["deleted"]},
            {"task_pending", "task_completed", "task_failed", "task_cancelled"},
        )
        self.assertEqual(set(self.registry), {"task_processing", "task_blocked"})

    def test_pending_runtime_queue_and_task_indexes_are_revoked(self) -> None:
        formal_root = self.root / "formal"
        output_root = formal_root / "输出"
        compression_root = output_root / "图片压缩"
        state = register_image_compression_routes(
            FastAPI(),
            user_dirs_provider=lambda: {
                "app_data_root": formal_root,
                "normal_output_dir": output_root / "1080P画质",
                "safe_beta_output_dir": output_root / "1080P画质",
                "image_compression_output_dir": compression_root,
                "tmp_dir": compression_root / ".运行缓存",
            },
            output_settings_provider=lambda: {
                "built_in_default_root": str(compression_root),
                "saved_default_root": str(compression_root),
            },
            shared_task_registry=self.registry,
        )
        record = {
            "task_id": "task_pending_queue",
            "status": "pending",
            "source_preview_token": "token_source",
            "output_preview_token": "token_output",
        }
        state["task_registry"]["task_pending_queue"] = record
        state["token_registry"]["token_source"] = {"role": "source_preview"}
        state["token_registry"]["token_output"] = {"role": "output_preview"}
        state["color_batch_registry"]["batch_pending"] = {
            "batch_id": "batch_pending",
            "status": "pending",
            "progress": 0,
            "total_count": 1,
            "completed_count": 0,
            "failed_count": 0,
            "created_at": "2026-08-13T00:00:00Z",
            "completed_at": None,
            "current_task_id": None,
            "task_ids": ["task_pending_queue"],
        }
        state["output_center_index"]["cached-task-item"] = {"task_id": "task_pending_queue"}

        state["remove_task_runtime_references"]("task_pending_queue")

        self.assertNotIn("task_pending_queue", state["task_registry"])
        self.assertNotIn("token_source", state["token_registry"])
        self.assertNotIn("token_output", state["token_registry"])
        self.assertNotIn("cached-task-item", state["output_center_index"])
        batch = state["color_batch_registry"]["batch_pending"]
        self.assertEqual(batch["task_ids"], [])
        self.assertEqual(batch["total_count"], 0)
        self.assertEqual(batch["status"], "cancelled")

    def test_restart_marks_orphaned_started_enhancement_as_interrupted(self) -> None:
        formal_root = self.root / "restart-formal"
        formal_root.mkdir()
        settings_path = self.root / "restart-settings.json"
        settings = main.default_settings()
        settings["app_data_root"] = str(formal_root)
        settings["last_app_data_root"] = str(formal_root)
        settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

        with (
            patch.object(main, "SETTINGS_PATH", settings_path),
            patch.object(main, "_formal_root_validation_error", return_value=("", "")),
            TestClient(main.build_web_app()) as client,
        ):
            client.app.state.task_registry["task_orphaned_after_restart"] = {
                "task_id": "task_orphaned_after_restart",
                "feature_key": "enhancement_1080p",
                "task_status": "pending",
                "status": "pending",
                "execution_started": True,
                "execution_state": "scheduled",
                "task_progress": 99,
                "created_at": "2026-08-13T19:28:34+08:00",
                "task_result": None,
                "result_id": "",
            }
            client.app.state.task_registry["compression_orphaned_after_restart"] = {
                "task_id": "compression_orphaned_after_restart",
                "feature_key": "image_compression",
                "task_status": "pending",
                "status": "pending",
                "execution_started": True,
                "execution_state": "scheduled",
                "task_progress": 99,
                "progress": 0,
                "created_at": "2026-08-13T19:28:35+08:00",
                "task_result": None,
                "result_id": "",
            }
            client.app.state.task_registry["compression_waiting_not_started"] = {
                "task_id": "compression_waiting_not_started",
                "feature_key": "image_compression",
                "task_status": "pending",
                "status": "pending",
                "execution_started": False,
                "execution_state": "queued",
                "task_progress": 0,
                "progress": 0,
                "created_at": "2026-08-13T19:28:36+08:00",
                "task_result": None,
                "result_id": "",
            }

        with (
            patch.object(main, "SETTINGS_PATH", settings_path),
            patch.object(main, "_formal_root_validation_error", return_value=("", "")),
            TestClient(main.build_web_app()) as restarted,
        ):
            tasks = restarted.get("/api/v1/tasks").json()["data"]["tasks"]
            task = next(item for item in tasks if item["task_id"] == "task_orphaned_after_restart")
            self.assertEqual(task["status"], "failed")
            self.assertEqual(task["task_status"], "failed")
            self.assertEqual(task["execution_state"], "interrupted")
            self.assertEqual(task["error_code"], "TASK_INTERRUPTED_BY_RESTART")
            self.assertFalse(task.get("task_result"))
            self.assertFalse(task.get("result_id"))
            compression = next(item for item in tasks if item["task_id"] == "compression_orphaned_after_restart")
            self.assertEqual(compression["status"], "failed")
            self.assertEqual(compression["task_status"], "failed")
            self.assertEqual(compression["progress"], 99)
            self.assertEqual(compression["task_progress"], 99)
            self.assertEqual(compression["execution_state"], "interrupted")
            self.assertEqual(compression["error_code"], "TASK_INTERRUPTED_BY_RESTART")
            waiting = next(item for item in tasks if item["task_id"] == "compression_waiting_not_started")
            self.assertEqual(waiting["status"], "pending")
            self.assertEqual(waiting["task_progress"], 0)
            stream = restarted.get("/api/v1/tasks/compression_orphaned_after_restart/stream")
            self.assertEqual(stream.status_code, 409)
            self.assertEqual(stream.json()["detail"]["code"], "TASK_STREAM_UNSUPPORTED")

    def test_task_list_orders_newest_first_with_stable_task_id_tiebreak_across_pages(self) -> None:
        formal_root = self.root / "sort-formal"
        formal_root.mkdir()
        settings_path = self.root / "sort-settings.json"
        settings = main.default_settings()
        settings["app_data_root"] = str(formal_root)
        settings["last_app_data_root"] = str(formal_root)
        settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

        with (
            patch.object(main, "SETTINGS_PATH", settings_path),
            patch.object(main, "_formal_root_validation_error", return_value=("", "")),
            TestClient(main.build_web_app()) as client,
        ):
            registry = client.app.state.task_registry
            for task_id, created_at in (
                ("task_older", "2026-08-13T19:28:34+08:00"),
                ("task_newer_a", "2026-08-13T19:28:35+08:00"),
                ("task_newer_b", "2026-08-13T19:28:35+08:00"),
            ):
                registry[task_id] = {
                    "task_id": task_id,
                    "feature_key": "image_compression",
                    "status": "completed",
                    "task_status": "completed",
                    "progress": 100,
                    "task_progress": 100,
                    "execution_started": True,
                    "execution_state": "completed",
                    "created_at": created_at,
                }
            first_page = client.get("/api/v1/tasks?limit=2&offset=0").json()["data"]
            second_page = client.get("/api/v1/tasks?limit=2&offset=2").json()["data"]
            self.assertEqual(
                [item["task_id"] for item in first_page["tasks"]],
                ["task_newer_b", "task_newer_a"],
            )
            self.assertEqual([item["task_id"] for item in second_page["tasks"]], ["task_older"])

    def test_task_order_key_normalizes_mixed_datetime_and_iso_string_values(self) -> None:
        records = [
            {"task_id": "task_older", "created_at": "2026-09-09T17:36:42+08:00"},
            {"task_id": "task_newer", "created_at": datetime.fromisoformat("2026-09-09T17:44:53+08:00")},
        ]

        ordered = sorted(records, key=main.task_created_order_key, reverse=True)

        self.assertEqual([item["task_id"] for item in ordered], ["task_newer", "task_older"])

    def test_real_api_delete_persists_and_result_remains_open_after_restart(self) -> None:
        formal_root = self.root / "api-formal"
        formal_root.mkdir()
        settings_path = self.root / "settings.json"
        settings = main.default_settings()
        settings["app_data_root"] = str(formal_root)
        settings["last_app_data_root"] = str(formal_root)
        settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

        with (
            patch.object(main, "SETTINGS_PATH", settings_path),
            patch.object(main, "_formal_root_validation_error", return_value=("", "")),
            TestClient(main.build_web_app()) as client,
        ):
            workdir = client.get("/api/app/workdir").json()["data"]
            output = Path(workdir["output_dir"]) / "preserved.png"
            output.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (12, 8), (20, 80, 160)).save(output)
            source = Path(workdir["input_dir"]) / "source.png"
            source.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (12, 8), (10, 40, 80)).save(source)
            registry = client.app.state.task_registry
            registry["task_completed_api"] = {
                "task_id": "task_completed_api",
                "feature_key": "enhancement_1080p",
                "module_id": "hdde.enhancement.1080p",
                "operation_id": "OP-20260813T000000-DELETEAPI1",
                "trace_id": "TRACE-DELETEAPI001",
                "task_status": "completed",
                "status": "completed",
                "task_progress": 100,
                "created_at": "2026-08-13T00:00:00+08:00",
                "completed_at": "2026-08-13T00:00:01+08:00",
                "input_path": source,
                "source_path": source,
                "result_id": "result_completed_api",
                "delivery_id": "delivery_completed_api",
                "result_file": str(output),
                "output_path": output,
                "task_result": {
                    "task_id": "task_completed_api",
                    "result_id": "result_completed_api",
                    "delivery_id": "delivery_completed_api",
                    "module_id": "hdde.enhancement.1080p",
                    "operation_id": "OP-20260813T000000-DELETEAPI1",
                    "trace_id": "TRACE-DELETEAPI001",
                    "output_filename": output.name,
                    "result_file": str(output),
                },
            }
            registry["task_pending_api"] = {
                "task_id": "task_pending_api",
                "feature_key": "enhancement_1080p",
                "task_status": "pending",
                "status": "pending",
                "execution_started": False,
                "task_progress": 0,
                "created_at": "2026-08-13T00:00:02+08:00",
                "input_path": source,
                "source_path": source,
            }
            registry["task_running_api"] = {
                "task_id": "task_running_api",
                "feature_key": "enhancement_1080p",
                "task_status": "processing",
                "status": "processing",
                "execution_started": True,
                "task_progress": 40,
                "created_at": "2026-08-13T00:00:03+08:00",
                "input_path": source,
                "source_path": source,
            }

            first_page = client.get("/api/v1/tasks?limit=2&offset=0").json()["data"]
            second_page = client.get("/api/v1/tasks?limit=2&offset=2").json()["data"]
            self.assertEqual(first_page["total_count"], 3)
            self.assertEqual(first_page["returned_count"], 2)
            self.assertTrue(first_page["has_more"])
            self.assertEqual(first_page["next_offset"], 2)
            self.assertEqual(second_page["returned_count"], 1)
            self.assertFalse(second_page["has_more"])
            self.assertTrue(
                {item["task_id"] for item in first_page["tasks"]}.isdisjoint(
                    item["task_id"] for item in second_page["tasks"]
                )
            )

            deleted = client.request(
                "DELETE",
                "/api/v1/tasks",
                json={"task_ids": ["task_completed_api", "task_pending_api", "task_running_api"]},
            )
            self.assertEqual(deleted.status_code, 200, deleted.text)
            data = deleted.json()["data"]
            self.assertEqual(data["deleted_count"], 2)
            self.assertEqual(data["protected_count"], 1)
            self.assertEqual(data["deleted_task_ids"], ["task_completed_api", "task_pending_api"])
            self.assertEqual(data["protected_task_ids"], ["task_running_api"])
            self.assertEqual(data["protected_tasks"][0]["reason"], "task_running")
            visible_ids = {item["task_id"] for item in client.get("/api/v1/tasks").json()["data"]["tasks"]}
            self.assertEqual(visible_ids, {"task_running_api"})
            self.assertEqual(client.get("/api/v1/tasks/task_completed_api").status_code, 404)
            self.assertEqual(client.get("/api/v1/tasks/task_completed_api/result-file").content, output.read_bytes())
            feedback_context = client.post(
                "/api/v1/feedback/context-snapshot",
                json={
                    "task_id": "task_completed_api",
                    "source_feature": "output_center",
                    "route": "/output-center",
                },
            )
            self.assertEqual(feedback_context.status_code, 200, feedback_context.text)
            common = feedback_context.json()["data"]["context"]["common_context"]
            self.assertEqual(common["feature_key"], "output_center")
            self.assertEqual(common["module_id"], "hdde.output.center")
            self.assertEqual(common["operation_id"], "OP-20260813T000000-DELETEAPI1")
            self.assertEqual(common["trace_id"], "TRACE-DELETEAPI001")
            self.assertEqual(common["result_id"], "result_completed_api")
            self.assertEqual(common["delivery_id"], "delivery_completed_api")
            output_items = client.get("/api/output-center/items").json()["data"]["items"]
            preserved = next(item for item in output_items if item["result_id"] == "result_completed_api")
            self.assertEqual(preserved["task_id"], "task_completed_api")
            self.assertEqual(client.get(preserved["preview_url"]).status_code, 200)

        with (
            patch.object(main, "SETTINGS_PATH", settings_path),
            patch.object(main, "_formal_root_validation_error", return_value=("", "")),
            TestClient(main.build_web_app()) as restarted,
        ):
            visible_ids = {item["task_id"] for item in restarted.get("/api/v1/tasks").json()["data"]["tasks"]}
            self.assertEqual(visible_ids, {"task_running_api"})
            self.assertEqual(restarted.get("/api/v1/tasks/task_completed_api").status_code, 404)
            self.assertEqual(restarted.get("/api/v1/tasks/task_completed_api/result-file").status_code, 200)
            result_reference = restarted.app.state.task_registry.result_reference_for_task("task_completed_api")
            self.assertEqual(result_reference["delivery_id"], "delivery_completed_api")
            self.assertEqual(result_reference["operation_id"], "OP-20260813T000000-DELETEAPI1")
            self.assertEqual(result_reference["trace_id"], "TRACE-DELETEAPI001")
            self.assertTrue(output.is_file())

    def test_color_result_preview_urls_bind_exact_task_files_after_restart(self) -> None:
        formal_root = self.root / "color-preview-formal"
        formal_root.mkdir()
        settings_path = self.root / "color-preview-settings.json"
        settings = main.default_settings()
        settings["app_data_root"] = str(formal_root)
        settings["last_app_data_root"] = str(formal_root)
        settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

        source = formal_root / "输出" / "图片压缩" / ".运行缓存" / "intake_exact" / "source.png"
        result = formal_root / "输出" / "颜色校正" / "result.png"
        source.parent.mkdir(parents=True)
        result.parent.mkdir(parents=True)
        Image.new("RGB", (12, 8), (10, 40, 80)).save(source)
        Image.new("RGB", (12, 8), (20, 80, 160)).save(result)
        task_id = "color_preview_restart"

        with (
            patch.object(main, "SETTINGS_PATH", settings_path),
            patch.object(main, "_formal_root_validation_error", return_value=("", "")),
            TestClient(main.build_web_app()) as client,
        ):
            client.app.state.task_registry[task_id] = {
                "task_id": task_id,
                "feature_key": "color_correction",
                "task_family": "color_correction",
                "operation_mode": "AUTO_COLOR_CORRECTION",
                "task_status": "completed",
                "status": "completed",
                "task_progress": 100,
                "source_path": str(source),
                "result_id": "color_result_preview_restart",
                "result_file": str(result),
                "output_path": str(result),
                "task_result": {
                    "task_id": task_id,
                    "result_id": "color_result_preview_restart",
                    "result_file": str(result),
                    "output_path": str(result),
                    "output_filename": result.name,
                },
            }
            payload = client.get(f"/api/v1/tasks/{task_id}").json()["data"]
            self.assertEqual(payload["source_preview_url"], f"/api/v1/tasks/{task_id}/source-file")
            self.assertEqual(payload["originalUrl"], payload["source_preview_url"])
            self.assertTrue(payload["final_output_exists"])
            self.assertEqual(payload["final_output_url"], f"/api/v1/tasks/{task_id}/result-file")
            self.assertEqual(payload["preview_output_url"], payload["final_output_url"])
            self.assertEqual(payload["enhancedUrl"], payload["final_output_url"])
            self.assertEqual(payload["task_result"]["final_output_url"], payload["final_output_url"])
            self.assertEqual(payload["task_result"]["preview_output_url"], payload["final_output_url"])
            self.assertEqual(client.get(payload["source_preview_url"]).content, source.read_bytes())
            self.assertEqual(client.get(payload["final_output_url"]).content, result.read_bytes())

        with (
            patch.object(main, "SETTINGS_PATH", settings_path),
            patch.object(main, "_formal_root_validation_error", return_value=("", "")),
            TestClient(main.build_web_app()) as restarted,
        ):
            payload = restarted.get(f"/api/v1/tasks/{task_id}").json()["data"]
            self.assertEqual(payload["source_preview_url"], f"/api/v1/tasks/{task_id}/source-file")
            self.assertEqual(restarted.get(payload["source_preview_url"]).content, source.read_bytes())
            self.assertEqual(restarted.get(payload["final_output_url"]).content, result.read_bytes())

    def test_accept_original_keeps_decision_without_creating_a_result_fact(self) -> None:
        formal_root = self.root / "color-original-formal"
        formal_root.mkdir()
        settings_path = self.root / "color-original-settings.json"
        settings = main.default_settings()
        settings["app_data_root"] = str(formal_root)
        settings["last_app_data_root"] = str(formal_root)
        settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

        source = formal_root / "输出" / "图片压缩" / ".运行缓存" / "intake_original" / "source.png"
        source.parent.mkdir(parents=True)
        Image.new("RGB", (12, 8), (10, 40, 80)).save(source)
        task_id = "color_accept_original"

        with (
            patch.object(main, "SETTINGS_PATH", settings_path),
            patch.object(main, "_formal_root_validation_error", return_value=("", "")),
            TestClient(main.build_web_app()) as client,
        ):
            client.app.state.task_registry[task_id] = {
                "task_id": task_id,
                "feature_key": "color_correction",
                "task_family": "color_correction",
                "operation_mode": "AUTO_COLOR_CORRECTION",
                "task_status": "completed",
                "status": "completed",
                "task_progress": 100,
                "source_path": str(source),
                "result_id": "",
                "result_file": "",
                "output_path": None,
                "result_action": "ACCEPT_ORIGINAL",
                "output_selected": "ORIGINAL",
                "decision": {
                    "result_action": "ACCEPT_ORIGINAL",
                    "output_selected": "ORIGINAL",
                },
                "result": None,
                "task_result": None,
            }
            payload = client.get(f"/api/v1/tasks/{task_id}").json()["data"]
            self.assertEqual(payload["result_id"], "")
            self.assertIsNone(payload["result"])
            self.assertIsNone(payload["task_result"])
            self.assertFalse(payload["final_output_exists"])
            self.assertIsNone(payload["final_output_url"])
            self.assertIsNone(payload["preview_output_url"])
            self.assertEqual(client.get(payload["source_preview_url"]).content, source.read_bytes())


if __name__ == "__main__":
    unittest.main()
