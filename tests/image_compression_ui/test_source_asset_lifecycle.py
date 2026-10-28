"""Token expiry and registered image retention use separate authorities."""

import copy
import hashlib
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import test_reference_color_api as reference_fixture
from backend.image_compression_api import TOKEN_TTL_SECONDS, register_image_compression_routes
from engine.storage.shared_task_registry import SharedTaskRegistry


class SourceAssetLifecycleTests(unittest.TestCase):
    setUp = reference_fixture.ReferenceColorApiTests.setUp
    tearDown = reference_fixture.ReferenceColorApiTests.tearDown
    intake = reference_fixture.ReferenceColorApiTests.intake
    run_reference = reference_fixture.ReferenceColorApiTests.run_reference

    def source(self, intake):
        return self.state["token_registry"][intake["source_token"]]

    def prune(self):
        response = self.client.get("/api/image-compression/preview/no-valid-token")
        self.assertEqual(response.status_code, 404)

    def expire(self):
        self.now += TOKEN_TTL_SECONDS + 1
        self.prune()

    def reload(self):
        self.client.close()
        self.registry = SharedTaskRegistry(self.formal)
        app = FastAPI()
        self.state = register_image_compression_routes(
            app, user_dirs_provider=lambda: {"normal_output_dir": self.formal / "输出", "tmp_dir": self.cache},
            shared_task_registry=self.registry, now_provider=lambda: self.now,
        )
        self.client = TestClient(app)

    def assert_preview(self, data, field, expected_hash):
        response = self.client.get(data["ui"][field])
        self.assertEqual(response.status_code, 200, response.text[:100])
        self.assertEqual(hashlib.sha256(response.content).hexdigest(), expected_hash)

    def test_unregistered_expired_upload_is_revoked_and_deleted(self):
        intake = self.intake()
        path = Path(self.source(intake)["path"])
        self.expire()
        self.assertNotIn(intake["source_token"], self.state["token_registry"])
        self.assertFalse(path.exists())
        self.assertFalse(path.parent.exists())
        self.assertEqual(self.client.get(intake["safe_preview_url"]).status_code, 404)

    def test_registered_task_sources_and_reference_review_survive_expiry(self):
        for status in ("pending", "queued", "processing", "completed"):
            for field in ("source_path", "source_file", "reference_metadata"):
                with self.subTest(status=status, field=field):
                    intake = self.intake()
                    item = copy.deepcopy(self.source(intake))
                    path = Path(item["path"])
                    record_id = status + field
                    self.registry[record_id] = {
                        "task_id": record_id, "status": status,
                        "result_action": "REVIEW_REQUIRED" if field == "reference_metadata" else "",
                        field: item if field == "reference_metadata" else str(path),
                    }
                    self.expire()
                    self.assertNotIn(intake["source_token"], self.state["token_registry"])
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])

    def test_duplicate_live_source_or_preview_token_delays_unregistered_cleanup(self):
        for role in ("source", "source_preview"):
            with self.subTest(role=role):
                intake = self.intake()
                item = copy.deepcopy(self.source(intake))
                path = Path(item["path"])
                item.update(role=role, expires_at=self.now + 2 * TOKEN_TTL_SECONDS)
                self.state["token_registry"]["second-authorization"] = item
                self.expire()
                self.assertTrue(path.is_file())
                self.assertIn("second-authorization", self.state["token_registry"])
                self.expire()
                self.assertFalse(path.exists())

    def test_last_persistent_reference_controls_retention(self):
        intake = self.intake()
        item = copy.deepcopy(self.source(intake))
        path = Path(item["path"])
        for key in ("first", "second"):
            self.registry[key] = {"task_id": key, "status": "completed", "source_path": str(path)}
        del self.registry["first"]
        self.expire()
        self.assertTrue(path.is_file())
        self.reload()
        # Re-evaluate an expired authorization against facts loaded from disk,
        # not an in-memory pin left by the process that created the Task.
        self.state["token_registry"]["expired-again"] = item
        self.prune()
        self.assertTrue(path.is_file())
        del self.registry["second"]
        self.state["token_registry"]["expired-without-owner"] = item
        self.prune()
        self.assertFalse(path.exists())

    def test_original_result_and_reference_previews_survive_expiry_and_reload(self):
        target, reference = self.intake(), self.intake(name="reference.png")
        before = self.run_reference(target, reference).json()["data"]
        self.assertEqual(before["result"]["result_action"], "ACCEPT_ORIGINAL")
        result_file = Path(before["result"]["result_file"])
        task_id = before["task"]["task_id"]
        self.expire()
        self.assertEqual(self.run_reference(target, reference).status_code, 404)
        for restart in (False, True):
            if restart:
                self.reload()
            data = self.client.get("/api/color-correction/tasks/" + task_id).json()["data"]
            self.assertEqual(data["result"], before["result"])
            self.assert_preview(data, "source_preview_url", target["source_sha256"])
            self.assert_preview(data, "reference_preview_url", reference["source_sha256"])
            self.assertEqual(hashlib.sha256(result_file.read_bytes()).hexdigest(), target["source_sha256"])

    def test_auto_color_preview_also_recovers_without_reviving_source_authorization(self):
        target = self.intake(cast=(0, 0, 0))
        before = self.client.post("/api/color-correction/run", json={"source_token": target["source_token"]}).json()["data"]
        self.assertEqual(before["task"]["status"], "completed")
        self.expire()
        self.assertEqual(self.client.post("/api/color-correction/run", json={"source_token": target["source_token"]}).status_code, 404)
        self.reload()
        data = self.client.get("/api/color-correction/tasks/" + before["task"]["task_id"]).json()["data"]
        self.assertEqual(data["result"], before["result"])
        self.assert_preview(data, "source_preview_url", target["source_sha256"])

    def test_deleted_task_retains_result_source_but_releases_unused_reference(self):
        target, reference = self.intake(), self.intake(name="reference.png")
        source_path, reference_path = Path(self.source(target)["path"]), Path(self.source(reference)["path"])
        data = self.run_reference(target, reference).json()["data"]
        task_id = data["task"]["task_id"]
        outcome = self.registry.delete_task_fact(task_id)
        self.assertTrue(outcome["result_preserved"])
        self.state["remove_task_runtime_references"](task_id)
        self.expire()
        self.assertTrue(source_path.is_file())
        self.assertFalse(reference_path.exists())
        self.reload()
        self.assertEqual(self.registry[data["result"]["result_id"]]["result_file"], str(source_path))
        self.assertEqual(self.client.get("/api/color-correction/tasks/" + task_id).status_code, 404)

    def test_retained_result_fields_and_nested_batch_sources_are_protected(self):
        for field in ("source_file", "result_file", "source_result_path"):
            with self.subTest(field=field):
                intake = self.intake()
                path = Path(self.source(intake)["path"])
                self.registry[field] = {"record_kind": "result", "result_id": field,
                                        "result": {"items": [{field: str(path)}]}}
                self.expire()
                self.assertTrue(path.is_file())

    def test_outside_root_traversal_and_output_files_are_never_unlinked(self):
        for kind in ("outside", "traversal", "formal-output", "relative"):
            with self.subTest(kind=kind):
                intake = self.intake()
                item = copy.deepcopy(self.source(intake))
                path = Path(item["path"])
                if kind in {"outside", "formal-output"}:
                    path = (self.root if kind == "outside" else self.formal / "输出") / "protected.png"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(Path(item["path"]).read_bytes())
                    raw = path
                elif kind == "traversal":
                    raw = path.parent / ".." / path.parent.name / path.name
                else:
                    raw = Path("relative.png")
                self.state["token_registry"].clear()
                item.update(path=raw, expires_at=self.now - 1)
                self.state["token_registry"]["invalid-target"] = item
                self.prune()
                self.assertTrue(path.is_file())
                self.assertNotIn("invalid-target", self.state["token_registry"])

    def test_sibling_cache_cannot_be_a_deletion_root(self):
        self.cache = self.root / "sibling-cache"
        intake = self.intake()
        path = Path(self.source(intake)["path"])
        self.expire()
        self.assertTrue(path.is_file())
        self.assertNotIn(intake["source_token"], self.state["token_registry"])


if __name__ == "__main__":
    unittest.main()
