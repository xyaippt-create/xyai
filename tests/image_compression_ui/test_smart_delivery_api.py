import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import backend.image_compression_api as image_compression_api_module
from backend.image_compression_api import (
    RESULT_IDENTITY_MISMATCH,
    register_image_compression_routes,
    smart_delivery_name_issues,
)
from engine.output.publish_safety import publish_verified_file_copy_no_overwrite


SMART_DELIVERY_NAME_STEM_LENGTH = 177


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for block in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class SmartDeliveryApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.app_root = self.root / "formal"
        self.output_root = self.app_root / "输出"
        self.tmp = self.output_root / "图片压缩" / ".运行缓存"
        self.opened = []
        self.runtime_events = []
        self.sources = [
            self.output_root / "1080P画质" / "alpha.png",
            self.output_root / "4K画质增强" / "bravo.png",
        ]
        self.originals = [
            self.root / "originals" / "alpha-source.png",
            self.root / "originals" / "bravo-source.png",
        ]
        self.shared_registry = {}
        self.result_ids = ["enhancement_result_alpha_001", "enhancement_result_bravo_002"]
        for index, (result_path, source_path, result_id) in enumerate(
            zip(self.sources, self.originals, self.result_ids)
        ):
            result_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (80 + index, 60), (40 + index, 80, 130)).save(result_path)
            Image.new("RGB", (80 + index, 60), (30 + index, 70, 120)).save(source_path)
            result_sha256 = sha256_file(result_path)
            task_id = f"enhancement_task_{index + 1:03d}"
            self.shared_registry[task_id] = {
                "task_id": task_id,
                "result_id": result_id,
                "feature_key": "enhancement_1080p" if index == 0 else "enhancement_4k",
                "task_family": "enhancement",
                "status": "completed",
                "source_path": source_path,
                "source": str(source_path),
                "output_path": result_path,
                "result_file": str(result_path),
                "output_sha256": result_sha256,
                "result": {
                    "result_id": result_id,
                    "task_id": task_id,
                    "feature_key": "enhancement_1080p" if index == 0 else "enhancement_4k",
                    "source": str(source_path),
                    "source_path": str(source_path),
                    "result_file": str(result_path),
                    "output_path": str(result_path),
                    "output_sha256": result_sha256,
                    "status": "completed",
                },
            }

        self.original = self.root / "originals" / "retouch-source.png"
        self.retouch_result = self.output_root / "瑕疵修复" / "retouch-result.png"
        self.original.parent.mkdir(parents=True, exist_ok=True)
        self.retouch_result.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (96, 64), (20, 45, 75)).save(self.original)
        Image.new("RGB", (96, 64), (25, 50, 80)).save(self.retouch_result)
        retouch_sha256 = sha256_file(self.retouch_result)
        self.retouch_result_id = "retouch_result_formal_001"
        self.retouch_task_id = "retouch_task_formal_001"
        self.shared_registry[self.retouch_task_id] = {
            "task_id": self.retouch_task_id,
            "result_id": self.retouch_result_id,
            "feature_key": "local_retouch",
            "task_family": "local_retouch",
            "processing_type": "local_retouch",
            "original_filename": self.original.name,
            "status": "completed",
            "source_path": self.original,
            "source": str(self.original),
            "output_path": self.retouch_result,
            "result_file": str(self.retouch_result),
            "output_sha256": retouch_sha256,
            "result": {
                "result_id": self.retouch_result_id,
                "task_id": self.retouch_task_id,
                "feature_key": "local_retouch",
                "source": str(self.original),
                "source_path": str(self.original),
                "result_file": str(self.retouch_result),
                "output_path": str(self.retouch_result),
                "output_sha256": retouch_sha256,
                "status": "completed",
            },
        }

        self.client = self.make_client()
        items = self.client.get("/api/output-center/items").json()["data"]["items"]
        self.items_by_result = {item["result_id"]: item for item in items if item.get("result_id")}

    def make_client(self):
        app = FastAPI()
        register_image_compression_routes(
            app,
            user_dirs_provider=lambda: {
                "app_data_root": self.app_root,
                "normal_output_dir": self.output_root / "1080P画质",
                "safe_beta_output_dir": self.output_root / "1080P画质",
                "image_compression_output_dir": self.output_root / "图片压缩",
                "tmp_dir": self.tmp,
            },
            folder_opener=self.opened.append,
            output_settings_provider=lambda: {
                "built_in_default_root": str(self.output_root / "图片压缩"),
                "saved_default_root": str(self.output_root / "图片压缩"),
            },
            shared_task_registry=self.shared_registry,
            now_provider=lambda: 1_786_262_400.0,
            runtime_event_logger=lambda event, **fields: self.runtime_events.append({"event": event, **fields}),
        )
        return TestClient(app)

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def preflight(self, *, item_ids=None, result_ids=None, rules=None):
        payload = {"rules": {} if rules is None else rules}
        if item_ids is not None:
            payload["item_ids"] = item_ids
        if result_ids is not None:
            payload["result_ids"] = result_ids
        return self.client.post("/api/smart-delivery/preflight", json=payload)

    def add_delivery_source(self, filename: str, *, result_id: str, task_id: str) -> Path:
        result_path = self.output_root / "1080P画质" / filename
        result_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (72, 54), (55, 95, 135)).save(result_path)
        result_sha256 = sha256_file(result_path)
        source_path = self.root / "originals" / f"{task_id}-source.png"
        Image.new("RGB", (72, 54), (45, 85, 125)).save(source_path)
        self.shared_registry[task_id] = {
            "task_id": task_id,
            "result_id": result_id,
            "feature_key": "enhancement_1080p",
            "task_family": "enhancement",
            "status": "completed",
            "source_path": source_path,
            "source": str(source_path),
            "output_path": result_path,
            "result_file": str(result_path),
            "output_sha256": result_sha256,
            "result": {
                "result_id": result_id,
                "task_id": task_id,
                "feature_key": "enhancement_1080p",
                "source": str(source_path),
                "source_path": str(source_path),
                "result_file": str(result_path),
                "output_path": str(result_path),
                "output_sha256": result_sha256,
                "status": "completed",
            },
        }
        return result_path

    def test_public_delivery_copies_real_files_and_preserves_result_mapping(self):
        source_hashes = {path: sha256_file(path) for path in self.sources}
        preflight_response = self.preflight(result_ids=self.result_ids)
        self.assertEqual(preflight_response.status_code, 200, preflight_response.text)
        preflight = preflight_response.json()["data"]
        self.assertTrue(preflight["ready"], preflight)
        self.assertEqual(
            [item["delivery_file_name"] for item in preflight["items"]],
            [path.name for path in self.sources],
        )

        unconfirmed = self.client.post(
            "/api/smart-delivery/execute",
            json={"plan_id": preflight["plan_id"], "confirmed": False},
        )
        self.assertEqual(unconfirmed.status_code, 400, unconfirmed.text)
        self.assertEqual(unconfirmed.json()["detail"]["code"], "SMART_DELIVERY_CONFIRMATION_REQUIRED")

        execution = self.client.post(
            "/api/smart-delivery/execute",
            json={"plan_id": preflight["plan_id"], "confirmed": True},
        )
        self.assertEqual(execution.status_code, 200, execution.text)
        delivery = execution.json()["data"]
        self.assertEqual((delivery["success_count"], delivery["failure_count"]), (2, 0))
        delivery_root = self.output_root / "智能交付"
        for source, result in zip(self.sources, delivery["results"]):
            delivered_path = delivery_root / result["delivery_file_name"]
            self.assertTrue(delivered_path.is_file())
            self.assertEqual(delivered_path.suffix, source.suffix)
            self.assertEqual(result["source_result_id"], self.result_ids[self.sources.index(source)])
            self.assertEqual(result["source_sha256"], result["delivery_sha256"])
            self.assertEqual(result["registered_output_sha256"], source_hashes[source])
            self.assertEqual(sha256_file(source), source_hashes[source])
            self.assertEqual(sha256_file(delivered_path), source_hashes[source])

        output_items = self.client.get("/api/output-center/items").json()["data"]["items"]
        self.assertTrue(all(any(item["result_id"] == result_id for item in output_items) for result_id in self.result_ids))
        delivery_fact = self.shared_registry[f"delivery:{delivery['delivery_id']}"]
        self.assertEqual(delivery_fact["delivery_id"], delivery["delivery_id"])
        self.assertEqual(delivery_fact["success_count"], 2)
        self.assertEqual(self.shared_registry["enhancement_task_001"]["delivery_id"], delivery["delivery_id"])

        open_folder = self.client.post(f"/api/smart-delivery/runs/{delivery['delivery_id']}/open-folder")
        open_file = self.client.post(
            f"/api/smart-delivery/runs/{delivery['delivery_id']}/items/{delivery['results'][0]['result_id']}/open"
        )
        self.assertEqual((open_folder.status_code, open_file.status_code), (200, 200))
        self.assertEqual(self.opened[0], str(delivery_root.resolve()))
        self.assertEqual(self.opened[1], str((delivery_root / self.sources[0].name).resolve()))

    def test_collision_is_auto_unique_and_never_overwrites_existing_file(self):
        delivery_root = self.output_root / "智能交付"
        delivery_root.mkdir(parents=True, exist_ok=True)
        occupied = delivery_root / self.sources[0].name
        occupied_bytes = b"existing-delivery-owner"
        occupied.write_bytes(occupied_bytes)

        preflight_response = self.preflight(result_ids=[self.result_ids[0]])
        self.assertEqual(preflight_response.status_code, 200, preflight_response.text)
        preflight = preflight_response.json()["data"]
        self.assertTrue(preflight["ready"], preflight)
        self.assertEqual(
            preflight["items"][0]["delivery_file_name"],
            f"{self.sources[0].stem}_02{self.sources[0].suffix}",
        )

        execution = self.client.post(
            "/api/smart-delivery/execute",
            json={"plan_id": preflight["plan_id"], "confirmed": True},
        )
        self.assertEqual(execution.status_code, 200, execution.text)
        self.assertEqual(occupied.read_bytes(), occupied_bytes)
        delivered = execution.json()["data"]["results"][0]
        second_copy = delivery_root / delivered["delivery_file_name"]
        self.assertTrue(second_copy.is_file())
        self.assertNotEqual(delivered["delivery_file_name"], occupied.name)

        next_preflight_response = self.preflight(result_ids=[self.result_ids[0]])
        self.assertEqual(next_preflight_response.status_code, 200, next_preflight_response.text)
        next_preflight = next_preflight_response.json()["data"]
        self.assertTrue(next_preflight["ready"], next_preflight)
        self.assertEqual(
            next_preflight["items"][0]["delivery_file_name"],
            f"{self.sources[0].stem}_03{self.sources[0].suffix}",
        )
        self.assertEqual(occupied.read_bytes(), occupied_bytes)
        self.assertTrue(second_copy.is_file())

    def test_same_result_and_idempotency_key_replays_one_delivery_identity(self):
        result_id = self.result_ids[0]
        idempotency_key = f"delivery_request_{'a' * 32}"
        first_plan = self.preflight(result_ids=[result_id]).json()["data"]
        first = self.client.post(
            "/api/smart-delivery/execute",
            json={
                "plan_id": first_plan["plan_id"],
                "confirmed": True,
                "idempotency_key": idempotency_key,
            },
        )
        self.assertEqual(first.status_code, 200, first.text)
        first_delivery = first.json()["data"]
        self.assertFalse(first_delivery["idempotent_replay"])

        status = self.client.get(
            f"/api/smart-delivery/requests/{idempotency_key}",
            params={"result_id": result_id},
        )
        self.assertEqual(status.status_code, 200, status.text)
        self.assertTrue(status.json()["data"]["idempotent_replay"])
        self.assertEqual(status.json()["data"]["delivery_id"], first_delivery["delivery_id"])

        replay_plan = self.preflight(result_ids=[result_id]).json()["data"]
        replay = self.client.post(
            "/api/smart-delivery/execute",
            json={
                "plan_id": replay_plan["plan_id"],
                "confirmed": True,
                "idempotency_key": idempotency_key,
            },
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        replay_delivery = replay.json()["data"]
        self.assertTrue(replay_delivery["idempotent_replay"])
        self.assertEqual(replay_delivery["delivery_id"], first_delivery["delivery_id"])
        self.assertEqual(replay_delivery["results"], first_delivery["results"])
        self.assertEqual(len(list((self.output_root / "智能交付").glob("*.png"))), 1)
        delivery_facts = [key for key in self.shared_registry if str(key).startswith("delivery:")]
        self.assertEqual(delivery_facts, [f"delivery:{first_delivery['delivery_id']}"])
        request_fact = self.shared_registry[f"delivery_request:{idempotency_key}"]
        self.assertEqual(request_fact["result_id"], result_id)
        self.assertEqual(request_fact["delivery_id"], first_delivery["delivery_id"])
        self.assertEqual(request_fact["status"], "COMPLETED")
        self.assertEqual(request_fact["delivery_sha256"], first_delivery["results"][0]["delivery_sha256"])
        completed_attempts = [
            item for item in self.shared_registry["enhancement_task_001"].get("deliveries", [])
            if item.get("status") == "completed"
        ]
        self.assertEqual(len(completed_attempts), 1)

    def test_idempotency_key_cannot_be_rebound_to_another_result(self):
        idempotency_key = f"delivery_request_{'b' * 32}"
        first_plan = self.preflight(result_ids=[self.result_ids[0]]).json()["data"]
        first = self.client.post(
            "/api/smart-delivery/execute",
            json={"plan_id": first_plan["plan_id"], "confirmed": True, "idempotency_key": idempotency_key},
        )
        self.assertEqual(first.status_code, 200, first.text)

        other_plan = self.preflight(result_ids=[self.result_ids[1]]).json()["data"]
        conflict = self.client.post(
            "/api/smart-delivery/execute",
            json={"plan_id": other_plan["plan_id"], "confirmed": True, "idempotency_key": idempotency_key},
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["detail"]["code"], "SMART_DELIVERY_IDEMPOTENCY_CONFLICT")
        self.assertEqual(len([key for key in self.shared_registry if str(key).startswith("delivery:")]), 1)

    def test_processing_idempotency_fact_returns_existing_identity_without_copy(self):
        result_id = self.result_ids[0]
        idempotency_key = f"delivery_request_{'c' * 32}"
        delivery_id = "delivery_existing_processing"
        self.shared_registry[f"delivery_request:{idempotency_key}"] = {
            "record_kind": "delivery_request",
            "idempotency_key": idempotency_key,
            "result_id": result_id,
            "delivery_id": delivery_id,
            "status": "PROCESSING",
        }
        plan = self.preflight(result_ids=[result_id]).json()["data"]
        replay = self.client.post(
            "/api/smart-delivery/execute",
            json={"plan_id": plan["plan_id"], "confirmed": True, "idempotency_key": idempotency_key},
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        data = replay.json()["data"]
        self.assertEqual(data["status"], "processing")
        self.assertTrue(data["idempotent_replay"])
        self.assertEqual(data["delivery_id"], delivery_id)
        self.assertFalse((self.output_root / "智能交付").exists())

    def test_jpeg_extension_is_preserved_exactly_through_preflight_and_delivery(self):
        result_id = "enhancement_result_jpeg_003"
        source = self.add_delivery_source("portrait.jpeg", result_id=result_id, task_id="enhancement_task_003")

        preflight_response = self.preflight(result_ids=[result_id])
        self.assertEqual(preflight_response.status_code, 200, preflight_response.text)
        preflight = preflight_response.json()["data"]
        self.assertTrue(preflight["ready"], preflight)
        self.assertEqual(preflight["items"][0]["delivery_file_name"], source.name)
        self.assertTrue(preflight["items"][0]["delivery_file_name"].endswith(".jpeg"))

        execution = self.client.post(
            "/api/smart-delivery/execute",
            json={"plan_id": preflight["plan_id"], "confirmed": True},
        )
        self.assertEqual(execution.status_code, 200, execution.text)
        delivered_name = execution.json()["data"]["results"][0]["delivery_file_name"]
        self.assertEqual(delivered_name, source.name)
        self.assertTrue((self.output_root / "智能交付" / delivered_name).is_file())

    def test_webp_result_preflight_and_delivery_preserve_real_format(self):
        result_id = "enhancement_result_webp_003"
        source = self.add_delivery_source("compressed.webp", result_id=result_id, task_id="enhancement_task_webp_003")

        output_items = self.client.get("/api/output-center/items").json()["data"]["items"]
        output_item = next(item for item in output_items if item["result_id"] == result_id)
        preview = self.client.get(output_item["preview_url"])
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.headers["content-type"], "image/webp")
        with Image.open(io.BytesIO(preview.content)) as opened:
            self.assertEqual(opened.format, "WEBP")

        preflight_response = self.preflight(result_ids=[result_id])
        self.assertEqual(preflight_response.status_code, 200, preflight_response.text)
        preflight = preflight_response.json()["data"]
        self.assertTrue(preflight["ready"], preflight)
        self.assertEqual(preflight["items"][0]["delivery_file_name"], source.name)

        execution = self.client.post(
            "/api/smart-delivery/execute",
            json={"plan_id": preflight["plan_id"], "confirmed": True},
        )
        self.assertEqual(execution.status_code, 200, execution.text)
        delivered = execution.json()["data"]["results"][0]
        delivered_path = self.output_root / "智能交付" / delivered["delivery_file_name"]
        self.assertTrue(delivered_path.is_file())
        self.assertEqual(delivered_path.suffix.lower(), ".webp")
        self.assertEqual(sha256_file(delivered_path), sha256_file(source))
        self.assertEqual(delivered["source_sha256"], delivered["delivery_sha256"])
        with Image.open(delivered_path) as opened:
            self.assertEqual(opened.format, "WEBP")

    def test_overlong_source_filename_is_blocked_before_collision_allocation(self):
        result_id = "enhancement_result_long_name_004"
        source_name = f"{'长' * SMART_DELIVERY_NAME_STEM_LENGTH}.png"
        self.add_delivery_source(source_name, result_id=result_id, task_id="enhancement_task_004")

        preflight_response = self.preflight(result_ids=[result_id])
        self.assertEqual(preflight_response.status_code, 200, preflight_response.text)
        preflight = preflight_response.json()["data"]
        self.assertFalse(preflight["ready"])
        self.assertIn("FILE_NAME_TOO_LONG", {issue["code"] for issue in preflight["issues"]})
        self.assertEqual(preflight["items"][0]["delivery_file_name"], source_name)
        self.assertFalse((self.output_root / "智能交付").exists())

    def test_invalid_source_filename_keeps_windows_invalid_character_error(self):
        issues = smart_delivery_name_issues("客户:交付", ".png")
        self.assertEqual({code for code, _message in issues}, {"WINDOWS_INVALID_CHARACTER"})

    def test_windows_reserved_source_filename_is_blocked(self):
        issues = smart_delivery_name_issues("CON", ".png")
        self.assertEqual({code for code, _message in issues}, {"WINDOWS_RESERVED_NAME"})

    def test_duplicate_selection_blocks_execution_without_writing(self):
        item_id = self.items_by_result[self.result_ids[0]]["id"]
        preflight_response = self.preflight(item_ids=[item_id, item_id])
        self.assertEqual(preflight_response.status_code, 200, preflight_response.text)
        preflight = preflight_response.json()["data"]
        self.assertFalse(preflight["ready"])
        self.assertIn("DUPLICATE_SELECTION", {issue["code"] for issue in preflight["issues"]})
        blocked = self.client.post(
            "/api/smart-delivery/execute",
            json={"plan_id": preflight["plan_id"], "confirmed": True},
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertFalse((self.output_root / "智能交付").exists())

    def test_retired_naming_rules_are_rejected_before_any_file_write(self):
        response = self.preflight(
            result_ids=[self.result_ids[0]],
            rules={"base_mode": "custom", "base_name": "../unsafe", "prefix": "客户"},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"]["code"], "DELIVERY_NAMING_RULES_RETIRED")
        self.assertFalse((self.output_root / "智能交付").exists())

    def test_local_retouch_result_keeps_formal_result_to_delivery_mapping(self):
        preflight_response = self.preflight(result_ids=[self.retouch_result_id])
        self.assertEqual(preflight_response.status_code, 200, preflight_response.text)
        preflight = preflight_response.json()["data"]
        self.assertTrue(preflight["ready"], preflight)
        execution = self.client.post(
            "/api/smart-delivery/execute",
            json={"plan_id": preflight["plan_id"], "confirmed": True},
        )
        self.assertEqual(execution.status_code, 200, execution.text)
        delivery = execution.json()["data"]
        delivered = delivery["results"][0]
        self.assertEqual(delivered["source_result_id"], self.retouch_result_id)
        self.assertEqual(delivered["task_id"], self.retouch_task_id)
        self.assertEqual(self.shared_registry[self.retouch_task_id]["delivery_id"], delivery["delivery_id"])

    def test_current_file_hash_mismatch_blocks_preflight(self):
        original_bytes = self.sources[0].read_bytes()
        registered_sha256 = sha256_file(self.sources[0])
        Image.new("RGB", (80, 60), (220, 20, 30)).save(self.sources[0])
        self.assertNotEqual(sha256_file(self.sources[0]), registered_sha256)

        response = self.preflight(result_ids=[self.result_ids[0]])
        self.assertEqual(response.status_code, 200, response.text)
        preflight = response.json()["data"]
        self.assertFalse(preflight["ready"])
        self.assertIn(RESULT_IDENTITY_MISMATCH, {issue["code"] for issue in preflight["issues"]})
        output_item = next(
            item
            for item in self.client.get("/api/output-center/items").json()["data"]["items"]
            if item.get("result_id") == self.result_ids[0]
        )
        self.assertFalse(output_item["delivery_eligible"])
        self.assertEqual(output_item["delivery_failure_code"], RESULT_IDENTITY_MISMATCH)
        eligibility_fact = self.shared_registry[f"delivery_eligibility:{self.result_ids[0]}"]
        self.assertFalse(eligibility_fact["delivery_eligible"])

        self.client.close()
        self.client = self.make_client()
        restarted_item = next(
            item
            for item in self.client.get("/api/output-center/items").json()["data"]["items"]
            if item.get("result_id") == self.result_ids[0]
        )
        self.assertFalse(restarted_item["delivery_eligible"])

        self.sources[0].write_bytes(original_bytes)
        restored = self.preflight(result_ids=[self.result_ids[0]])
        self.assertTrue(restored.json()["data"]["ready"], restored.text)
        restored_item = next(
            item
            for item in self.client.get("/api/output-center/items").json()["data"]["items"]
            if item.get("result_id") == self.result_ids[0]
        )
        self.assertTrue(restored_item["delivery_eligible"])
        self.assertEqual(restored_item["delivery_failure_code"], "")
        self.assertFalse((self.output_root / "智能交付").exists())

    def test_preflight_pass_then_source_replacement_blocks_execute_without_publish(self):
        result_id = "enhancement_result_toctou_005"
        source = self.add_delivery_source("toctou.png", result_id=result_id, task_id="enhancement_task_005")
        registered_sha256 = sha256_file(source)
        preflight_response = self.preflight(result_ids=[result_id])
        self.assertEqual(preflight_response.status_code, 200, preflight_response.text)
        preflight = preflight_response.json()["data"]
        self.assertTrue(preflight["ready"], preflight)
        destination = self.output_root / "智能交付" / preflight["items"][0]["delivery_file_name"]

        def replace_before_copy(*args, **kwargs):
            Image.new("RGB", (72, 54), (230, 25, 45)).save(source)
            return publish_verified_file_copy_no_overwrite(*args, **kwargs)

        idempotency_key = f"delivery_request_{'d' * 32}"
        with patch.object(
            image_compression_api_module,
            "publish_verified_file_copy_no_overwrite",
            side_effect=replace_before_copy,
        ):
            execution = self.client.post(
                "/api/smart-delivery/execute",
                json={"plan_id": preflight["plan_id"], "confirmed": True, "idempotency_key": idempotency_key},
            )

        self.assertEqual(execution.status_code, 409, execution.text)
        self.assertEqual(execution.json()["detail"]["code"], RESULT_IDENTITY_MISMATCH)
        self.assertNotEqual(sha256_file(source), registered_sha256)
        self.assertFalse(destination.exists())
        delivery_root = self.output_root / "智能交付"
        self.assertEqual(list(delivery_root.glob(".hdde-output-*.tmp")), [])
        delivery_facts = [
            record for key, record in self.shared_registry.items()
            if str(key).startswith("delivery:")
        ]
        self.assertEqual(len(delivery_facts), 1)
        self.assertEqual(delivery_facts[0]["status"], "failed")
        self.assertEqual(delivery_facts[0]["error_code"], RESULT_IDENTITY_MISMATCH)
        output_item = next(
            item
            for item in self.client.get("/api/output-center/items").json()["data"]["items"]
            if item.get("result_id") == result_id
        )
        self.assertFalse(output_item["delivery_eligible"])
        self.assertEqual(output_item["delivery_failure_code"], RESULT_IDENTITY_MISMATCH)
        replay = self.client.post(
            "/api/smart-delivery/execute",
            json={"plan_id": preflight["plan_id"], "confirmed": True, "idempotency_key": idempotency_key},
        )
        self.assertEqual(replay.status_code, 409, replay.text)
        self.assertTrue(replay.json()["detail"]["idempotent_replay"])
        self.assertEqual(replay.json()["detail"]["delivery_id"], execution.json()["detail"]["delivery_id"])
        self.assertEqual(len([key for key in self.shared_registry if str(key).startswith("delivery:")]), 1)
        self.assertFalse(any(
            item.get("status") == "completed"
            for item in self.shared_registry["enhancement_task_005"].get("deliveries", [])
        ))


if __name__ == "__main__":
    unittest.main()
