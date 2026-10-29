"""Batch cards must survive paging, task clearing and application restarts."""
import hashlib
import io
import json
import time
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from tests.support.app_runtime import isolated_app_runtime
from engine.storage.shared_task_registry import SharedTaskRegistry


def source_bytes(index=0, fmt="PNG"):
    stream = io.BytesIO()
    Image.new("RGB", (180 + index, 120), (30 + index, 100, 170)).save(
        stream, format=fmt, **({"compress_level": 0} if fmt == "PNG" else {})
    )
    return stream.getvalue()


class BatchOutputContractTests(unittest.TestCase):
    def setUp(self):
        self.scope = isolated_app_runtime(self.id())
        self.runtime = self.scope.__enter__()
        self.client = TestClient(self.runtime.main.build_web_app())
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.scope.__exit__(None, None, None)

    def watermark(self, count=3):
        response = self.client.post(
            "/api/batch-watermark/batches",
            data={"spec_json": json.dumps({"kind": "text", "text": "S61"})},
            files=[("files", (f"source-{i}.png", source_bytes(i), "image/png")) for i in range(count)],
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def restart(self):
        self.client.__exit__(None, None, None)
        self.client = TestClient(self.runtime.main.build_web_app())
        self.client.__enter__()

    def card(self, batch_id):
        data = self.client.get("/api/output-center/items").json()["data"]
        return next(i for i in data["items"] if i.get("batch_id") == batch_id)

    def compression(self, files):
        batch_id = "compression_batch_" + uuid.uuid4().hex
        response = self.client.post("/api/image-compression/batches", files=files,
                                    data={"batch_id": batch_id, "workers": "1", "target_format": "PRESERVE_FORMAT"})
        self.assertEqual(response.status_code, 200, response.text)
        return batch_id

    def wait_batch(self, batch_id):
        for _ in range(150):
            response = self.client.get(f"/api/image-compression/batches/{batch_id}")
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()["data"]
            if not data["running"]:
                return data
            time.sleep(.05)
        self.fail("Batch did not finish")

    def test_three_watermarks_are_one_complete_batch_card(self):
        batch = self.watermark()
        page = self.client.get("/api/output-center/items?limit=1").json()["data"]
        self.assertEqual(page["total_count"], 1, "One batch must consume one page slot")
        card = page["items"][0]
        self.assertEqual(card["batch_id"], batch["batch_id"])
        self.assertEqual(len(card["items"]), 3)
        self.assertEqual(len({i["task_id"] for i in card["items"]}), 3)
        for item in card["items"]:
            for field in ("batch_id", "batch_item_id", "feature_type", "source_id", "task_id", "result_id", "status", "output_path", "output_sha256"):
                self.assertTrue(item[field], field)
            self.assertEqual(hashlib.sha256(Path(item["output_path"]).read_bytes()).hexdigest(), item["output_sha256"])
            self.assertEqual(self.client.get(item["thumbnail_url"]).status_code, 200)

    def test_ten_watermarks_survive_task_clear_restart_and_exact_continuation(self):
        batch = self.watermark(10)
        original = self.card(batch["batch_id"])
        hashes = {i["output_path"]: i["output_sha256"] for i in original["items"]}
        cleared = self.client.request("DELETE", "/api/v1/tasks", json={"task_ids": [batch["batch_id"], *[i["task_id"] for i in original["items"]]]})
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertEqual(cleared.json()["data"]["deleted_count"], 11)
        self.restart()
        restored = self.card(batch["batch_id"])
        self.assertEqual(len(restored["items"]), 10)
        self.assertEqual({i["result_id"] for i in restored["items"]}, {i["result_id"] for i in original["items"]})
        for item in restored["items"]:
            self.assertTrue(item["available"])
            asset = self.client.get("/api/result-assets/" + item["result_id"])
            self.assertEqual(asset.status_code, 200, asset.text)
        chosen = restored["items"][4]
        continued = self.client.post("/api/batch-watermark/batches", data={"result_ids_json": json.dumps([chosen["result_id"]]), "spec_json": '{"kind":"text","text":"next"}'})
        self.assertEqual(continued.status_code, 200, continued.text)
        child = continued.json()["data"]["items"][0]
        self.assertEqual(child["source_result_id"], chosen["result_id"])
        self.assertEqual(child["source_task_id"], chosen["task_id"])
        self.assertEqual(child["source_result_sha256"], chosen["output_sha256"])
        self.assertEqual(self.client.post(f"/api/output-center/items/{batch['batch_id']}/clear").status_code, 200)
        self.restart()
        self.assertNotIn(batch["batch_id"], [i.get("batch_id") for i in self.client.get("/api/output-center/items").json()["data"]["items"]])
        self.assertEqual(hashes, {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in hashes})

    def test_compression_mixed_three_preserves_keep_original_without_result(self):
        import numpy as np
        stream = io.BytesIO()
        Image.fromarray(np.random.default_rng(7).integers(0, 256, (240, 320, 3), dtype=np.uint8)).save(stream, "JPEG", quality=45, optimize=True)
        files = [("files", ("source.png", source_bytes(), "image/png")),
                 ("files", ("source.jpg", stream.getvalue(), "image/jpeg")),
                 ("files", ("source.webp", source_bytes(2, "WEBP"), "image/webp"))]
        batch_id = self.compression(files)
        data = self.wait_batch(batch_id)
        card = self.card(batch_id)
        self.assertEqual(len(card["items"]), 3)
        self.assertGreater(card["summary"]["completed"], 0)
        self.assertGreater(card["summary"]["keep_original"], 0)
        for item in card["items"]:
            self.assertTrue(item["source_id"])
            if item["status"] == "KEEP_ORIGINAL":
                self.assertEqual((item["result_id"], item["output_path"], item["output_sha256"]), ("", "", ""))
            else:
                self.assertTrue(item["available"])
                self.assertTrue(item["continue_eligible"])
                self.assertEqual(item["feature_key"], "image_compression")
                self.assertEqual(self.client.get("/api/result-assets/" + item["result_id"]).status_code, 200)
        self.restart()
        self.assertEqual([i["status"] for i in self.card(batch_id)["items"]], [i["status"] for i in data["items"]])

    def test_failed_and_canceled_items_remain_in_ten_item_card(self):
        files = [("files", (f"source-{i}.png", b"damaged" if i == 2 else source_bytes(i), "image/png")) for i in range(10)]
        batch_id = self.compression(files)
        cancel = self.client.post(f"/api/image-compression/batches/{batch_id}/control", json={"action": "cancel"})
        self.assertEqual(cancel.status_code, 200, cancel.text)
        self.wait_batch(batch_id)
        card = self.card(batch_id)
        self.assertEqual(len(card["items"]), 10)
        self.assertEqual(card["summary"]["failed"], 1)
        self.assertGreater(card["summary"]["canceled"], 0)
        registry = SharedTaskRegistry(self.runtime.formal_root)
        for item in card["items"]:
            self.assertIn(item["task_id"], registry)
            if item["status"] in {"CANCELED", "FAILED"}:
                self.assertFalse(item["result_id"] or item["output_path"] or item["output_sha256"])
        self.restart()
        self.assertEqual(card["summary"], self.card(batch_id)["summary"])

    def test_pagination_and_search_never_split_batch_or_guess_filename_membership(self):
        first, second = self.watermark(), self.watermark()
        page = self.client.get("/api/output-center/items?limit=1").json()["data"]
        next_page = self.client.get("/api/output-center/items?limit=1&offset=1").json()["data"]
        self.assertEqual(page["total_count"], 2)
        self.assertEqual(len(page["items"][0]["items"]), 3)
        self.assertNotEqual(page["items"][0]["batch_id"], next_page["items"][0]["batch_id"])
        search = self.client.get("/api/output-center/items?query=source-1").json()["data"]
        self.assertEqual(search["total_count"], 2)
        self.assertTrue(all(len(i["items"]) == 3 for i in search["items"]))
        # Unregistered historical files have no reliable batch relation.
        singleton = Path(first["items"][0]["output_path"]).with_name("source-1-unbound.png")
        singleton.write_bytes(source_bytes())
        page = self.client.get("/api/output-center/items").json()["data"]
        self.assertEqual(page["total_count"], 3)
        self.assertEqual(sum(i.get("card_type") == "batch" for i in page["items"]), 2)

    def test_registered_wrong_sha_disables_child_actions_without_touching_file(self):
        batch = self.watermark()
        output = Path(batch["items"][0]["output_path"])
        original_sha = hashlib.sha256(output.read_bytes()).hexdigest()
        self.client.__exit__(None, None, None)
        registry = SharedTaskRegistry(self.runtime.formal_root)
        for key in (batch["batch_id"], "output_batch:" + batch["batch_id"]):
            record = registry[key]
            record["items"][0]["output_sha256"] = "0" * 64
            registry[key] = record
        self.client = TestClient(self.runtime.main.build_web_app())
        self.client.__enter__()
        child = self.card(batch["batch_id"])["items"][0]
        self.assertFalse(child["available"])
        self.assertNotIn("thumbnail_url", child)
        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), original_sha)

    def test_compression_batch_results_can_be_delivered_by_result_id(self):
        files = [("files", (f"deliver-{i}.png", source_bytes(i), "image/png")) for i in range(2)]
        batch_id = self.compression(files)
        self.wait_batch(batch_id)
        children = [item for item in self.card(batch_id)["items"] if item["status"] == "COMPLETED"]
        self.assertEqual(len(children), 2)
        for child in children:
            preflight = self.client.post("/api/smart-delivery/preflight", json={"result_ids": [child["result_id"]], "rules": {}})
            self.assertEqual(preflight.status_code, 200, preflight.text)
            plan = preflight.json()["data"]
            self.assertTrue(plan["ready"], plan)
            execute = self.client.post("/api/smart-delivery/execute", json={
                "plan_id": plan["plan_id"], "confirmed": True,
                "idempotency_key": "delivery_request_" + uuid.uuid4().hex,
            })
            self.assertEqual(execute.status_code, 200, execute.text)
            result = execute.json()["data"]["results"][0]
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["source_result_id"], child["result_id"])
            self.assertEqual(result["delivery_sha256"], child["output_sha256"])
            delivered = self.runtime.formal_root / "输出" / "智能交付" / result["delivery_file_name"]
            self.assertEqual(hashlib.sha256(delivered.read_bytes()).hexdigest(), child["output_sha256"])

    def test_batch_child_with_wrong_registered_sha_is_not_deliverable(self):
        batch_id = self.compression([("files", ("tampered.png", source_bytes(5), "image/png"))])
        self.wait_batch(batch_id)
        result_id = self.card(batch_id)["items"][0]["result_id"]
        self.client.__exit__(None, None, None)
        registry = SharedTaskRegistry(self.runtime.formal_root)
        for key in (batch_id, "output_batch:" + batch_id):
            if key in registry:
                record = registry[key]
                record["items"][0]["output_sha256"] = "0" * 64
                registry[key] = record
        self.client = TestClient(self.runtime.main.build_web_app())
        self.client.__enter__()
        self.assertFalse(self.card(batch_id)["items"][0]["available"])
        preflight = self.client.post("/api/smart-delivery/preflight", json={"result_ids": [result_id], "rules": {}})
        self.assertEqual(preflight.status_code, 404, preflight.text)
        self.assertEqual(preflight.json()["detail"]["code"], "UNIFIED_RESULT_NOT_FOUND")
        self.assertFalse((self.runtime.formal_root / "输出" / "智能交付").exists())

    def test_batch_import_does_not_keep_a_second_intake_copy(self):
        single = self.client.post("/api/image-compression/intake", files={"file": ("single.png", source_bytes(9), "image/png")})
        self.assertEqual(single.status_code, 200, single.text)
        batch_id = self.compression([("files", (f"once-{i}.png", source_bytes(i), "image/png")) for i in range(2)])
        intake_roots = list(self.runtime.formal_root.rglob("image-compression-intake"))
        self.assertEqual(len(intake_roots), 1)
        leftovers = sorted(path.name for path in intake_roots[0].rglob("*.png"))
        self.assertEqual(leftovers, ["single.png"])  # Only the unrelated single-image intake remains.
        data = self.wait_batch(batch_id)
        self.assertEqual([item["status"] for item in data["items"]], ["COMPLETED", "COMPLETED"])


if __name__ == "__main__":
    unittest.main()
