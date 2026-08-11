import hashlib
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.image_compression_api import register_image_compression_routes


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
            self.output_root / "1080P标准增强" / "alpha.png",
            self.output_root / "4K高清增强" / "bravo.png",
        ]
        for index, path in enumerate(self.sources):
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (80 + index, 60), (40 + index, 80, 130)).save(path)
        self.source_hashes = {path: sha256_file(path) for path in self.sources}
        self.original = self.root / "originals" / "retouch-source.png"
        self.retouch_result = self.output_root / "标记修整" / "retouch-result.png"
        self.original.parent.mkdir(parents=True, exist_ok=True)
        self.retouch_result.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (96, 64), (20, 45, 75)).save(self.original)
        Image.new("RGB", (96, 64), (25, 50, 80)).save(self.retouch_result)
        self.retouch_result_id = "retouch_result_formal_001"
        self.retouch_task_id = "retouch_task_formal_001"
        self.shared_registry = {
            self.retouch_task_id: {
                "task_id": self.retouch_task_id,
                "result_id": self.retouch_result_id,
                "feature_key": "local_retouch",
                "task_family": "local_retouch",
                "processing_type": "local_retouch",
                "status": "completed",
                "source_path": self.original,
                "source": str(self.original),
                "output_path": self.retouch_result,
                "result_file": str(self.retouch_result),
                "result": {
                    "result_id": self.retouch_result_id,
                    "task_id": self.retouch_task_id,
                    "feature_key": "local_retouch",
                    "source": str(self.original),
                    "source_path": str(self.original),
                    "result_file": str(self.retouch_result),
                    "output_path": str(self.retouch_result),
                    "status": "completed",
                },
            },
        }

        app = FastAPI()
        register_image_compression_routes(
            app,
            user_dirs_provider=lambda: {
                "app_data_root": self.app_root,
                "normal_output_dir": self.output_root / "1080P标准增强",
                "safe_beta_output_dir": self.output_root / "1080P安全增强",
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
        self.client = TestClient(app)
        items = self.client.get("/api/output-center/items").json()["data"]["items"]
        self.retouch_item = next(item for item in items if item["processing_type"] == "local_retouch")
        self.item_ids = [
            item["id"]
            for item in sorted(items, key=lambda item: item["processing_type"])
            if item["processing_type"] != "local_retouch"
        ]

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def preflight(self, rules):
        response = self.client.post(
            "/api/smart-delivery/preflight",
            json={"item_ids": self.item_ids, "rules": rules},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def test_duplicate_preflight_blocks_every_write_then_safe_copy_preserves_sources(self):
        duplicate = self.preflight({
            "base_mode": "custom",
            "base_name": "客户交付",
            "sequence_enabled": False,
            "date_enabled": False,
            "template": "{base}",
        })
        self.assertFalse(duplicate["ready"])
        self.assertIn("DUPLICATE_FINAL_NAME", {issue["code"] for issue in duplicate["issues"]})
        delivery_root = self.output_root / "智能交付"
        self.assertFalse(delivery_root.exists())

        blocked = self.client.post(
            "/api/smart-delivery/execute",
            json={"plan_id": duplicate["plan_id"], "confirmed": True},
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertFalse(delivery_root.exists())

        safe = self.preflight({
            "base_mode": "custom",
            "base_name": "客户交付",
            "sequence_enabled": True,
            "sequence_start": 1,
            "sequence_padding": 2,
            "date_enabled": False,
            "template": "{base}_{seq}",
        })
        self.assertTrue(safe["ready"], safe)
        preview_names = [item["delivery_file_name"] for item in safe["items"]]
        self.assertEqual(preview_names, ["客户交付_01.png", "客户交付_02.png"])

        execution = self.client.post(
            "/api/smart-delivery/execute",
            json={"plan_id": safe["plan_id"], "confirmed": True},
        )
        self.assertEqual(execution.status_code, 200, execution.text)
        data = execution.json()["data"]
        self.assertEqual((data["success_count"], data["failure_count"]), (2, 0))
        self.assertEqual([item["delivery_file_name"] for item in data["results"]], preview_names)
        self.assertEqual({path.name for path in delivery_root.iterdir()}, set(preview_names))
        for source in self.sources:
            self.assertEqual(sha256_file(source), self.source_hashes[source])
        for result in data["results"]:
            self.assertTrue(result["source_unchanged"])
            self.assertEqual(result["source_sha256"], result["delivery_sha256"])
            self.assertEqual(
                sha256_file(delivery_root / result["delivery_file_name"]),
                result["delivery_sha256"],
            )

        self.assertEqual(self.client.get("/api/output-center/items").json()["data"]["count"], 3)
        open_folder = self.client.post(f"/api/smart-delivery/runs/{data['delivery_id']}/open-folder")
        open_file = self.client.post(
            f"/api/smart-delivery/runs/{data['delivery_id']}/items/{data['results'][0]['result_id']}/open"
        )
        self.assertEqual((open_folder.status_code, open_file.status_code), (200, 200))
        self.assertEqual(self.opened[0], str(delivery_root.resolve()))
        self.assertEqual(self.opened[1], str((delivery_root / preview_names[0]).resolve()))

        existing = self.preflight({
            "base_mode": "custom",
            "base_name": "客户交付",
            "sequence_enabled": True,
            "sequence_start": 1,
            "sequence_padding": 2,
            "date_enabled": False,
            "template": "{base}_{seq}",
        })
        self.assertFalse(existing["ready"])
        self.assertEqual(
            {issue["code"] for issue in existing["issues"]},
            {"TARGET_ALREADY_EXISTS"},
        )

    def test_invalid_windows_name_is_reported_before_confirmation(self):
        plan = self.preflight({
            "base_mode": "custom",
            "base_name": "客户:交付",
            "sequence_enabled": True,
            "date_enabled": False,
            "template": "{base}_{seq}",
        })
        self.assertFalse(plan["ready"])
        self.assertIn("WINDOWS_INVALID_CHARACTER", {issue["code"] for issue in plan["issues"]})
        self.assertFalse((self.output_root / "智能交付").exists())

    def test_local_retouch_formal_result_keeps_result_to_delivery_mapping_and_protections(self):
        result_hash_before = sha256_file(self.retouch_result)
        result_mtime_before = self.retouch_result.stat().st_mtime_ns
        original_hash_before = sha256_file(self.original)
        original_mtime_before = self.original.stat().st_mtime_ns
        delivery_root = self.output_root / "智能交付"
        delivery_root.mkdir(parents=True)
        conflict = delivery_root / "retouch-delivery.png"
        Image.new("RGB", (8, 8), (255, 0, 0)).save(conflict)

        rules = {
            "base_mode": "custom",
            "base_name": "retouch-delivery",
            "sequence_enabled": False,
            "date_enabled": False,
            "template": "{base}",
        }
        blocked = self.client.post(
            "/api/smart-delivery/preflight",
            json={"result_ids": [self.retouch_result_id], "rules": rules},
        ).json()["data"]
        self.assertFalse(blocked["ready"])
        self.assertEqual({issue["code"] for issue in blocked["issues"]}, {"TARGET_ALREADY_EXISTS"})
        self.assertEqual({path.name for path in delivery_root.iterdir()}, {conflict.name})

        conflict.unlink()
        safe = self.client.post(
            "/api/smart-delivery/preflight",
            json={"result_ids": [self.retouch_result_id], "rules": rules},
        ).json()["data"]
        self.assertTrue(safe["ready"], safe)
        self.assertEqual(safe["items"][0]["source_result_id"], self.retouch_result_id)
        self.assertEqual(safe["items"][0]["result_id"], self.retouch_result_id)
        self.assertEqual(safe["items"][0]["task_id"], self.retouch_task_id)
        self.assertEqual(safe["items"][0]["feature_key"], "local_retouch")
        self.assertEqual(safe["items"][0]["source_processing_type"], "local_retouch")
        self.assertEqual(safe["items"][0]["delivery_file_name"], "retouch-delivery.png")

        response = self.client.post(
            "/api/smart-delivery/execute",
            json={"plan_id": safe["plan_id"], "confirmed": True},
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        delivered = data["results"][0]
        delivery_copy = delivery_root / delivered["delivery_file_name"]
        self.assertEqual(delivered["source_result_id"], self.retouch_result_id)
        self.assertEqual(delivered["result_id"], self.retouch_result_id)
        self.assertEqual(delivered["task_id"], self.retouch_task_id)
        self.assertEqual(delivered["feature_key"], "local_retouch")
        self.assertTrue(delivered["delivery_item_id"])
        self.assertEqual(delivered["source_processing_type"], "local_retouch")
        self.assertEqual(delivered["delivery_id"], data["delivery_id"])
        self.assertNotEqual(delivery_copy.resolve(), self.retouch_result.resolve())
        with Image.open(delivery_copy) as opened:
            opened.load()
            self.assertEqual(opened.size, (96, 64))
        self.assertEqual(sha256_file(delivery_copy), result_hash_before)
        self.assertEqual(sha256_file(self.retouch_result), result_hash_before)
        self.assertEqual(self.retouch_result.stat().st_mtime_ns, result_mtime_before)
        self.assertEqual(sha256_file(self.original), original_hash_before)
        self.assertEqual(self.original.stat().st_mtime_ns, original_mtime_before)
        self.assertEqual(self.shared_registry[self.retouch_task_id]["delivery_id"], data["delivery_id"])
        self.assertEqual(self.shared_registry[self.retouch_task_id]["deliveries"][-1]["result_id"], self.retouch_result_id)
        delivery_events = [event for event in self.runtime_events if event["event"].startswith("DELIVERY_")]
        self.assertEqual([event["event"] for event in delivery_events], ["DELIVERY_STARTED", "DELIVERY_SUCCEEDED"])
        self.assertEqual(delivery_events[-1]["task_id"], self.retouch_task_id)
        self.assertEqual(delivery_events[-1]["result_id"], self.retouch_result_id)
        self.assertEqual(delivery_events[-1]["delivery_id"], data["delivery_id"])

        current = self.client.get("/api/output-center/items").json()["data"]["items"]
        retouch = next(item for item in current if item["id"] == self.retouch_item["id"])
        self.assertEqual(retouch["result_id"], self.retouch_result_id)
        self.assertEqual(retouch["task_id"], self.retouch_task_id)
        self.assertEqual(retouch["feature_key"], "local_retouch")
        self.assertTrue(retouch["unified_result"])
        self.assertEqual(retouch["mapping_source"], "task_registry")
        self.assertTrue(retouch["compare_available"])

    def test_local_retouch_without_formal_result_reference_is_blocked(self):
        self.shared_registry.clear()
        plan = self.client.post(
            "/api/smart-delivery/preflight",
            json={
                "item_ids": [self.retouch_item["id"]],
                "rules": {
                    "base_mode": "original",
                    "sequence_enabled": True,
                    "date_enabled": False,
                    "template": "{base}_{seq}",
                },
            },
        ).json()["data"]
        self.assertFalse(plan["ready"])
        self.assertIn("UNIFIED_RESULT_REQUIRED", {issue["code"] for issue in plan["issues"]})

    def test_legacy_local_retouch_item_reference_remains_delivery_compatible(self):
        record = self.shared_registry[self.retouch_task_id]
        record.pop("feature_key")
        record["result"].pop("feature_key")
        current = self.client.get("/api/output-center/items").json()["data"]["items"]
        retouch = next(item for item in current if item["processing_type"] == "local_retouch")
        self.assertFalse(retouch["unified_result"])
        self.assertTrue(retouch["delivery_eligible"])
        plan = self.client.post(
            "/api/smart-delivery/preflight",
            json={
                "item_ids": [retouch["id"]],
                "rules": {
                    "base_mode": "custom",
                    "base_name": "legacy-compatible",
                    "sequence_enabled": False,
                    "date_enabled": False,
                    "template": "{base}",
                },
            },
        ).json()["data"]
        self.assertTrue(plan["ready"], plan)
        self.assertEqual(plan["items"][0]["source_result_id"], self.retouch_result_id)


if __name__ == "__main__":
    unittest.main()
