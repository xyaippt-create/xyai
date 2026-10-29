"""A06 durable orchestration, using the real frozen optimizer and registry."""
import asyncio
import copy
import hashlib
import io
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.batch_compression_api import BatchJob
from backend.image_compression_api import register_image_compression_routes
from engine.image_compression.delivery_options import generate_delivery_candidates
from engine.storage.shared_task_registry import SharedTaskRegistry, SharedTaskRegistryError
from engine.output.publish_safety import publish_verified_file_copy_no_overwrite


class BatchStabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.dirs = {"app_data_root": self.root, "normal_output_dir": self.output,
                     "image_compression_output_dir": self.output, "tmp_dir": self.root / "tmp"}
        self.client = None

    def open(self):
        self.registry = SharedTaskRegistry(self.root)
        app = FastAPI()
        state = register_image_compression_routes(app, user_dirs_provider=lambda: self.dirs,
                                                 shared_task_registry=self.registry)
        self.service = state["batch_service"]
        self.client = TestClient(app)
        self.client.__enter__()
        return self.client

    def close(self):
        if self.client is not None:
            self.client.__exit__(None, None, None)
            self.client = None

    def tearDown(self):
        self.close()
        self.temp.cleanup()

    @staticmethod
    def image(keep=False, alpha=False):
        data = io.BytesIO()
        if keep:
            image = Image.fromarray(np.random.default_rng(7).integers(0, 256, (120, 160, 3), dtype=np.uint8))
            image.save(data, format="JPEG", quality=40, optimize=True)
        else:
            Image.new("RGBA" if alpha else "RGB", (160, 120), (24, 120, 220, 90) if alpha else (24, 120, 220)).save(data, format="PNG", compress_level=0)
        return ("same.jpg" if keep else "same.png", data.getvalue(), "image/jpeg" if keep else "image/png")

    def create(self, files, workers=1, target_format="PRESERVE_FORMAT"):
        batch_id = "compression_batch_" + uuid.uuid4().hex
        response = self.client.post("/api/image-compression/batches", data={"batch_id": batch_id, "workers": workers, "target_format": target_format},
                                    files=[("files", value) for value in files])
        self.assertEqual(response.status_code, 200, response.text)
        return batch_id

    def status(self, batch_id):
        response = self.client.get("/api/image-compression/batches/" + batch_id)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def until(self, batch_id, predicate=lambda data: not data["running"], timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self.status(batch_id)
            if predicate(data):
                return data
            time.sleep(.03)
        self.fail(str(data))

    def control(self, batch_id, action):
        response = self.client.post(f"/api/image-compression/batches/{batch_id}/control", json={"action": action})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def assert_outputs(self, data):
        winners = [item for item in data["items"] if item["status"] == "COMPLETED"]
        self.assertEqual(len({i["taskId"] for i in data["items"]}), len(data["items"]))
        self.assertEqual(len({i["resultId"] for i in winners}), len(winners))
        actual_files = [p for p in self.output.rglob("*") if p.is_file()]
        self.assertEqual(len(actual_files), len(winners))
        center = self.client.get("/api/output-center/items").json()["data"]["items"]
        batch_cards = [card for card in center if card.get("batch_id") == data["batchId"]]
        self.assertEqual(len(batch_cards), 1)
        self.assertEqual(len(batch_cards[0]["items"]), len(data["items"]))
        self.assertEqual({item["task_id"] for item in batch_cards[0]["items"]}, {item["taskId"] for item in data["items"]})
        self.assertEqual({item["result_id"] for item in batch_cards[0]["items"] if item["status"] == "COMPLETED"}, {item["resultId"] for item in winners})
        for item in data["items"]:
            if item["status"] != "COMPLETED":
                self.assertFalse(item["resultId"])
                continue
            record = self.registry.get(item["taskId"]) or self.registry[item["resultId"]]
            raw = record["result"]
            raw = raw.to_dict() if hasattr(raw, "to_dict") else raw
            self.assertEqual(hashlib.sha256(Path(raw["output_path"]).read_bytes()).hexdigest(), item["outputSha256"])
            self.assertEqual(raw["source_sha256"], item["sourceSha256"])

    def assert_items_stable_across_restart(self, before, after):
        """Preview URLs may be re-signed; all durable item identity must remain exact."""

        self.assertEqual(len(after), len(before))
        for old_item, new_item in zip(before, after, strict=True):
            old_stable = {key: value for key, value in old_item.items() if key != "sourcePreviewUrl"}
            new_stable = {key: value for key, value in new_item.items() if key != "sourcePreviewUrl"}
            self.assertEqual(new_stable, old_stable)
            if not new_item["sourceSha256"]:
                self.assertFalse(new_item["sourcePreviewUrl"])
                continue
            preview = self.client.get(new_item["sourcePreviewUrl"])
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(hashlib.sha256(preview.content).hexdigest(), new_item["sourceSha256"])

    def test_mixed_failure_alpha_and_exact_restart(self):
        self.open()
        batch_id = self.create([self.image(), self.image(keep=True), ("broken.png", b"broken", "image/png"), self.image(alpha=True)], workers=2)
        data = self.until(batch_id)
        self.assertEqual([i["status"] for i in data["items"]], ["COMPLETED", "KEEP_ORIGINAL", "FAILED", "COMPLETED"])
        self.assert_outputs(data)
        record = self.registry[data["items"][3]["taskId"]]
        png = next(c for c in record["candidate_options"] if c["status"] == "AVAILABLE")
        self.assertTrue(png["quality_gate"]["checks"]["alpha_verified"])
        self.assertTrue(png["metadata_details"]["lossless_verification"]["alpha_preserved"])
        frozen = copy.deepcopy(data["items"])
        self.close()
        self.open()
        self.assert_items_stable_across_restart(frozen, self.status(batch_id)["items"])
        self.assert_outputs(data)

    def test_pause_resume_drains_without_replay(self):
        self.open()
        started, release = threading.Event(), threading.Event()
        def blocked(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(10))
            return generate_delivery_candidates(*args, **kwargs)
        with patch("backend.image_compression_api.generate_delivery_candidates", side_effect=blocked) as encoder:
            batch_id = self.create([self.image(), self.image(keep=True), self.image(alpha=True)])
            self.assertTrue(started.wait(5))
            self.assertEqual(self.control(batch_id, "pause")["state"], "PAUSING")
            release.set()
            paused = self.until(batch_id, lambda d: d["state"] == "PAUSED")
            self.assertEqual([i["status"] for i in paused["items"]], ["COMPLETED", "QUEUED", "QUEUED"])
            first_id = paused["items"][0]["resultId"]
            self.control(batch_id, "resume")
            done = self.until(batch_id)
            self.assertEqual(done["items"][0]["resultId"], first_id)
            self.assertEqual(encoder.call_count, 3)
            self.assert_outputs(done)

    def test_source_preview_is_state_independent_and_survives_runtime_restore(self):
        self.open()
        started, release = threading.Event(), threading.Event()

        def blocked(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(10))
            return generate_delivery_candidates(*args, **kwargs)

        with patch("backend.image_compression_api.generate_delivery_candidates", side_effect=blocked):
            batch_id = self.create([self.image(), self.image(keep=True)], workers=1)
            self.assertTrue(started.wait(5))
            active = self.status(batch_id)
            self.assertEqual([item["status"] for item in active["items"]], ["PROCESSING", "QUEUED"])
            for item in active["items"]:
                preview = self.client.get(item["sourcePreviewUrl"])
                self.assertEqual(preview.status_code, 200, preview.text)
                self.assertEqual(hashlib.sha256(preview.content).hexdigest(), item["sourceSha256"])
            release.set()
            done = self.until(batch_id)

        self.assertEqual([item["status"] for item in done["items"]], ["COMPLETED", "KEEP_ORIGINAL"])
        for item in done["items"]:
            self.assertEqual(self.client.get(item["sourcePreviewUrl"]).status_code, 200)

        self.close()
        self.open()
        restored = self.status(batch_id)
        for item in restored["items"]:
            self.assertEqual(self.client.get(item["sourcePreviewUrl"]).status_code, 200)

    def test_cancel_drains_active_and_never_deletes_winner(self):
        self.open()
        started, release = threading.Event(), threading.Event()
        def blocked(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(10))
            return generate_delivery_candidates(*args, **kwargs)
        with patch("backend.image_compression_api.generate_delivery_candidates", side_effect=blocked):
            batch_id = self.create([self.image(), self.image(), self.image()])
            self.assertTrue(started.wait(5))
            self.control(batch_id, "cancel")
            release.set()
            done = self.until(batch_id)
            self.assertEqual([i["status"] for i in done["items"]], ["COMPLETED", "CANCELED", "CANCELED"])
            self.assert_outputs(done)
            self.assertEqual(self.client.post(f"/api/image-compression/batches/{batch_id}/control", json={"action": "resume"}).status_code, 409)

    def test_prepared_publication_restart_does_not_encode_or_publish_twice(self):
        self.open()
        started, release = threading.Event(), threading.Event()
        def blocked(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(10))
            return generate_delivery_candidates(*args, **kwargs)
        with patch("backend.image_compression_api.generate_delivery_candidates", side_effect=blocked):
            batch_id = self.create([self.image()])
            self.assertTrue(started.wait(5))
            self.control(batch_id, "pause")
            release.set()
            done = self.until(batch_id)
        # Simulate a crash between publishing the SHA-bound receipt and saving the
        # completed Result. Preserve the exact already-published bytes and receipt.
        self.close()
        registry = SharedTaskRegistry(self.root)
        batch = registry[batch_id]
        item = batch["items"][0]
        item.update(status="PROCESSING", result_id="")
        registry[batch_id] = batch
        record = registry[item["task_id"]]
        record.update(status="processing", result=None, result_id="", task_result=None)
        registry[item["task_id"]] = record
        with patch("backend.image_compression_api.generate_delivery_candidates", side_effect=AssertionError("completed encoding must not repeat")):
            self.open()
            recovered = self.until(batch_id)
        self.assertEqual(recovered["items"][0]["resultId"], done["items"][0]["resultId"])
        self.assert_outputs(recovered)

    def test_queued_source_replacement_fails_closed_and_next_source_runs(self):
        self.open()
        started, release = threading.Event(), threading.Event()
        def blocked(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(10))
            return generate_delivery_candidates(*args, **kwargs)
        with patch("backend.image_compression_api.generate_delivery_candidates", side_effect=blocked):
            batch_id = self.create([self.image(), self.image(), self.image()])
            self.assertTrue(started.wait(5))
            batch = self.service.batches[batch_id]
            Path(batch["items"][1]["source"]["path"]).write_bytes(b"replaced test source")
            release.set()
            done = self.until(batch_id)
        self.assertEqual([i["status"] for i in done["items"]], ["COMPLETED", "FAILED", "COMPLETED"])
        self.assertEqual(done["items"][1]["error"], "SOURCE_IDENTITY_MISMATCH")
        self.assert_outputs(done)

    def test_duplicate_batch_id_and_unknown_recovery_are_rejected(self):
        self.open()
        batch_id = self.create([self.image()])
        self.until(batch_id)
        response = self.client.post("/api/image-compression/batches", data={"batch_id": batch_id}, files=[("files", self.image())])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get("/api/image-compression/batches/unknown").status_code, 404)

    def test_default_workers_uses_measured_conservative_limit(self):
        self.open()
        batch_id = "compression_batch_" + uuid.uuid4().hex
        response = self.client.post("/api/image-compression/batches", data={"batch_id": batch_id}, files=[("files", self.image())])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["workers"], 2)
        self.assert_outputs(self.until(batch_id))

    def test_import_progress_is_a_read_only_view_of_saved_sources(self):
        self.open()
        unknown = self.client.get(
            "/api/image-compression/batches/compression_batch_" + "f" * 32 + "/import-progress"
        )
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(unknown.json()["data"], {
            "registered": False, "preparedCount": 0, "preparingName": "",
        })
        batch = {
            "batch_id": "compression_batch_" + "a" * 32,
            "control": "IMPORTING",
            "workers": 2,
            "revision": 3,
            "items": [
                {"id": "one", "name": "一.png", "status": "QUEUED", "original_bytes": 10,
                 "task_id": "task-one", "source": {"sha256": "a" * 64}},
                {"id": "two", "name": "二.png", "status": "QUEUED", "original_bytes": 20,
                 "task_id": "task-two"},
                {"id": "three", "name": "三.png", "status": "FAILED", "original_bytes": 30,
                 "task_id": "task-three", "error": "invalid"},
            ],
        }
        before = copy.deepcopy(batch)
        public = self.service.public(batch)
        self.assertEqual(public["state"], "IMPORTING")
        self.assertEqual(public["preparedCount"], 2)
        self.assertEqual(public["preparingName"], "二.png")
        self.assertEqual(batch, before)

    def test_source_replaced_during_publication_removes_only_new_batch_output(self):
        self.open()
        def replace_after_copy(source, targets, **kwargs):
            published, report = publish_verified_file_copy_no_overwrite(source, targets, **kwargs)
            for batch in self.service.batches.values():
                for item in batch["items"]:
                    if item.get("prepared", {}).get("target") == str(published):
                        Path(item["source"]["path"]).write_bytes(b"test-only concurrent source replacement")
            return published, report
        with patch("backend.batch_compression_api.publish_verified_file_copy_no_overwrite", side_effect=replace_after_copy):
            batch_id = self.create([self.image()])
            done = self.until(batch_id)
        self.assertEqual(done["items"][0]["status"], "FAILED")
        self.assertEqual(done["items"][0]["error"], "SOURCE_IDENTITY_MISMATCH")
        self.assert_outputs(done)

    def test_bounded_workers_and_same_name_results_are_independent(self):
        self.open()
        started, release = threading.Event(), threading.Event()
        lock, active, peak = threading.Lock(), 0, 0
        def blocked(*args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if active == 3:
                    started.set()
            try:
                self.assertTrue(release.wait(10))
                return generate_delivery_candidates(*args, **kwargs)
            finally:
                with lock: active -= 1
        with patch("backend.image_compression_api.generate_delivery_candidates", side_effect=blocked):
            batch_id = self.create([self.image()] * 5, workers=3)
            self.assertTrue(started.wait(5))
            self.assertEqual(peak, 3)
            release.set()
            done = self.until(batch_id)
        self.assertEqual(peak, 3)
        self.assertTrue(all(i["status"] == "COMPLETED" for i in done["items"]))
        self.assert_outputs(done)

    def test_post_publish_registration_interruption_retains_receipt_without_second_winner(self):
        self.open()
        original_execute = self.service.execute
        interrupted = False
        async def interrupted_execute(*args, **kwargs):
            nonlocal interrupted
            result = await original_execute(*args, **kwargs)
            if not interrupted:
                interrupted = True
                raise OSError("simulated registration response interruption")
            return result
        self.service.execute = interrupted_execute
        batch_id = self.create([self.image()])
        done = self.until(batch_id)
        self.assertEqual(done["items"][0]["status"], "COMPLETED")
        self.assertTrue(done["items"][0]["resultId"])
        self.assertEqual(done["control"], "PAUSED")
        self.assert_outputs(done)

    def test_failed_start_registration_does_not_leave_a_phantom_processing_item(self):
        self.open()
        original_persist = self.service.persist
        def fail_start(batch):
            if any(i["status"] == "PROCESSING" for i in batch["items"]):
                raise SharedTaskRegistryError("test-only write interruption")
            return original_persist(batch)
        self.service.persist = fail_start
        batch_id = self.create([self.image()])
        paused = self.until(batch_id, lambda d: d["state"] == "PAUSED")
        self.assertEqual(paused["items"][0]["status"], "QUEUED")
        self.assertFalse(list(self.output.rglob("*.png")))
        self.service.persist = original_persist
        self.control(batch_id, "resume")
        self.assert_outputs(self.until(batch_id))

    def fail_final_batch_save(self):
        original = self.service.persist
        fired = threading.Event()
        def fail_once(batch):
            if not fired.is_set() and any(i["status"] in {"COMPLETED", "KEEP_ORIGINAL"} for i in batch["items"]):
                fired.set()
                raise SharedTaskRegistryError("test-only final batch save failure")
            return original(batch)
        self.service.persist = fail_once
        return fired

    def test_registered_winner_save_failure_cancel_and_restart_keep_authoritative_result(self):
        self.open()
        fired = self.fail_final_batch_save()
        batch_id = self.create([self.image()])
        self.assertTrue(fired.wait(10))
        # No GET before cancel: the control path must reconcile independently.
        done = self.control(batch_id, "cancel")
        self.assertEqual(done["items"][0]["status"], "COMPLETED")
        self.assert_outputs(done)
        result_id = done["items"][0]["resultId"]
        self.close()
        with patch("backend.image_compression_api.generate_delivery_candidates", side_effect=AssertionError("must not re-encode")):
            self.open()
            recovered = self.status(batch_id)
        self.assertEqual(recovered["items"][0]["status"], "COMPLETED")
        self.assertEqual(recovered["items"][0]["resultId"], result_id)
        self.assert_outputs(recovered)

    def test_registered_winner_save_failure_get_and_restart_do_not_replay(self):
        self.open()
        fired = self.fail_final_batch_save()
        with patch("backend.image_compression_api.generate_delivery_candidates", wraps=generate_delivery_candidates) as encoder:
            batch_id = self.create([self.image()])
            self.assertTrue(fired.wait(10))
            done = self.status(batch_id)
            self.assertEqual(done["items"][0]["status"], "COMPLETED")
            self.assertEqual(encoder.call_count, 1)
        self.assert_outputs(done)
        self.close()
        with patch("backend.image_compression_api.generate_delivery_candidates", side_effect=AssertionError("must not replay")):
            self.open()
            recovered = self.status(batch_id)
        self.assert_items_stable_across_restart(done["items"], recovered["items"])
        self.assert_outputs(recovered)

    def test_keep_original_save_failure_cancel_preserves_no_output_terminal(self):
        self.open()
        fired = self.fail_final_batch_save()
        batch_id = self.create([self.image(keep=True)])
        self.assertTrue(fired.wait(10))
        done = self.control(batch_id, "cancel")
        self.assertEqual(done["items"][0]["status"], "KEEP_ORIGINAL")
        self.assert_outputs(done)

    def test_old_canceled_snapshot_recovers_registered_winner_without_replay(self):
        self.open()
        batch_id = self.create([self.image()])
        done = self.until(batch_id)
        self.close()
        registry = SharedTaskRegistry(self.root)
        batch = registry[batch_id]
        batch["control"] = "CANCELED"
        batch["items"][0].update(status="CANCELED", result_id="", final_bytes=None, output_sha256="")
        registry[batch_id] = batch
        with patch("backend.image_compression_api.generate_delivery_candidates", side_effect=AssertionError("must not replay")):
            self.open()
            recovered = self.status(batch_id)
        self.assertEqual(recovered["items"][0]["status"], "COMPLETED")
        self.assertEqual(recovered["items"][0]["resultId"], done["items"][0]["resultId"])
        self.assert_outputs(recovered)

    def test_reconciliation_rejects_replaced_formal_winner_before_cancel(self):
        self.open()
        batch_id = self.create([self.image()])
        done = self.until(batch_id)
        item = self.service.batches[batch_id]["items"][0]
        raw = self.registry[item["task_id"]]["result"]
        raw = raw.to_dict() if hasattr(raw, "to_dict") else raw
        Path(raw["output_path"]).write_bytes(b"replaced test-only winner")
        item.update(status="QUEUED", result_id="", final_bytes=None, output_sha256="")
        canceled = self.control(batch_id, "cancel")
        self.assertEqual(canceled["items"][0]["status"], "FAILED")
        self.assertEqual(canceled["items"][0]["error"], "RESULT_IDENTITY_MISMATCH")
        self.assertFalse(canceled["items"][0]["resultId"])

    def test_live_stale_queued_row_get_reconciles_without_encoding(self):
        self.open()
        batch_id = self.create([self.image()])
        done = self.until(batch_id)
        batch = self.service.batches[batch_id]
        batch["control"] = "PAUSED"
        batch["items"][0].update(status="QUEUED", result_id="", final_bytes=None, output_sha256="")
        self.service.persist(batch)
        with patch("backend.image_compression_api.generate_delivery_candidates", side_effect=AssertionError("must not replay")):
            recovered = self.status(batch_id)
        self.assertEqual(recovered["items"][0]["status"], "COMPLETED")
        self.assertEqual(recovered["items"][0]["resultId"], done["items"][0]["resultId"])
        self.assert_outputs(recovered)

    def test_cancel_drains_published_receipt_when_result_registration_was_interrupted(self):
        self.open()
        batch_id = self.create([self.image()])
        done = self.until(batch_id)
        batch = self.service.batches[batch_id]
        item = batch["items"][0]
        record = self.registry[item["task_id"]]
        record.update(status="processing", result=None, result_id="", task_result=None)
        self.registry[item["task_id"]] = record
        batch["control"] = "PAUSED"
        item.update(status="QUEUED", result_id="", final_bytes=None, output_sha256="")
        self.service.persist(batch)
        with patch("backend.image_compression_api.generate_delivery_candidates", side_effect=AssertionError("must reuse receipt")):
            self.control(batch_id, "cancel")
            recovered = self.until(batch_id, lambda d: d["items"][0]["status"] == "COMPLETED")
        self.assertEqual(recovered["items"][0]["resultId"], done["items"][0]["resultId"])
        self.assert_outputs(recovered)

    def retain_result_after_batch_save_failure(self):
        self.open()
        fired = self.fail_final_batch_save()
        batch_id = self.create([self.image()])
        self.assertTrue(fired.wait(10))
        self.close()
        registry = SharedTaskRegistry(self.root)
        item = registry[batch_id]["items"][0]
        self.assertEqual(item["status"], "PROCESSING")
        task_id, result_id = item["task_id"], item["reserved_result_id"]
        deleted = registry.delete_task_fact(task_id)
        self.assertTrue(deleted["result_preserved"])
        self.assertNotIn(task_id, registry)
        return batch_id, task_id, result_id, copy.deepcopy(registry[result_id])

    def test_retained_result_restart_does_not_recreate_task_or_operation(self):
        batch_id, task_id, result_id, retained = self.retain_result_after_batch_save_failure()
        # No private candidate is needed to recover an already-published Result.
        registry = SharedTaskRegistry(self.root)
        receipt = registry[batch_id]["items"][0]["prepared"]
        Path(receipt["generated"]["winner"]["output_path"]).unlink()
        with patch("backend.image_compression_api.generate_delivery_candidates", side_effect=AssertionError("must not encode")):
            self.open()
            recovered = self.until(batch_id)
        self.assertEqual(recovered["items"][0]["status"], "COMPLETED")
        self.assertEqual(recovered["items"][0]["resultId"], result_id)
        self.assertNotIn(task_id, self.registry, "deleted Task must not be recreated")
        self.assertEqual(self.registry[result_id], retained)
        self.assert_outputs(recovered)
        center = self.client.get("/api/output-center/items").json()["data"]["items"]
        self.assertEqual(center[0]["items"][0]["operation_id"], retained["operation_id"])
        self.assertEqual(center[0]["items"][0]["trace_id"], retained["trace_id"])
        self.close()
        self.open()
        self.assertNotIn(task_id, self.registry)
        self.assertEqual(self.status(batch_id)["items"][0]["resultId"], result_id)

    def test_retained_result_get_cancel_and_worker_never_execute_again(self):
        self.open()
        batch_id = self.create([self.image()])
        done = self.until(batch_id)
        task_id, result_id = done["items"][0]["taskId"], done["items"][0]["resultId"]
        self.assertTrue(self.registry.delete_task_fact(task_id)["result_preserved"])
        retained = copy.deepcopy(self.registry[result_id])
        batch = self.service.batches[batch_id]
        batch["control"] = "PAUSED"
        with patch.object(self.service, "execute", wraps=self.service.execute) as execute:
            for action in ("get", "cancel", "work"):
                with self.subTest(action=action):
                    batch["items"][0].update(status="QUEUED", result_id="", final_bytes=None, output_sha256="")
                    self.service.persist(batch)
                    if action == "get":
                        recovered = self.status(batch_id)
                    elif action == "cancel":
                        recovered = self.control(batch_id, "cancel")
                    else:
                        self.client.portal.call(self.service.work, batch, batch["items"][0])
                        recovered = self.service.public(batch)
                    self.assertEqual(recovered["items"][0]["status"], "COMPLETED")
                    self.assertEqual(recovered["items"][0]["resultId"], result_id)
                    execute.assert_not_called()
                    self.assertNotIn(task_id, self.registry)
                    self.assertEqual(self.registry[result_id], retained)
        self.assert_outputs(recovered)

    def test_retained_result_rejects_changed_output_without_recreating_task(self):
        batch_id, task_id, result_id, retained = self.retain_result_after_batch_save_failure()
        Path(retained["output_path"]).write_bytes(b"test-only replacement of retained Winner")
        with patch("backend.image_compression_api.generate_delivery_candidates", side_effect=AssertionError("must not encode")):
            self.open()
            rejected = self.until(batch_id)
        self.assertEqual(rejected["items"][0]["status"], "FAILED")
        self.assertEqual(rejected["items"][0]["error"], "RESULT_IDENTITY_MISMATCH")
        self.assertFalse(rejected["items"][0]["resultId"])
        self.assertNotIn(task_id, self.registry)
        self.assertEqual(self.registry[result_id], retained)

    def test_retained_result_rejects_foreign_identity_or_unbound_quality_receipt(self):
        batch_id, task_id, result_id, retained = self.retain_result_after_batch_save_failure()
        registry = SharedTaskRegistry(self.root)
        original_batch = copy.deepcopy(registry[batch_id])
        for fault in ("result_id", "task_id", "record_kind", "source_sha", "output_sha", "quality_gate", "target"):
            with self.subTest(fault=fault):
                registry = SharedTaskRegistry(self.root)
                if task_id in registry:
                    registry.delete_task_fact(task_id)
                batch = copy.deepcopy(original_batch)
                record = copy.deepcopy(retained)
                generated = batch["items"][0]["prepared"]["generated"]
                if fault in {"result_id", "task_id", "record_kind"}:
                    record[fault] = "foreign-identity"
                elif fault in {"source_sha", "output_sha"}:
                    record["task_result"][fault + "256"] = "0" * 64
                elif fault == "quality_gate":
                    for candidate in generated["candidates"]:
                        candidate["quality_gate"]["status"] = "FAIL"
                else:
                    batch["items"][0]["prepared"]["target"] = str(self.output / "wrong.png")
                registry[batch_id] = batch
                registry[result_id] = record
                with patch("backend.image_compression_api.generate_delivery_candidates", side_effect=AssertionError("must not replay")):
                    self.open()
                    rejected = self.until(batch_id)
                self.assertEqual(rejected["items"][0]["status"], "FAILED")
                self.assertFalse(rejected["items"][0]["resultId"])
                self.assertNotIn(task_id, self.registry)
                self.assertEqual(self.registry[result_id], record)
                self.close()


class BatchDispatcherFailureContainmentTests(unittest.TestCase):
    """A worker that fails outside its own recovery must not stop the batch queue."""

    def make_service(self, registry):
        from backend.batch_compression_api import CompressionBatchService

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        service = CompressionBatchService(
            registry=registry, roots=lambda: {"tmp_dir": temp.name}, output_directory=lambda: temp.name,
            intake=None, execute=None, source_preview_url=lambda *_: "",
        )
        service.loaded, service.loaded_root = True, str(service.cache_root())
        return service

    def test_worker_failure_pauses_batch_and_next_run_continues(self):
        persisted = []

        class Registry(dict):
            def persist_facts(self, facts):
                persisted.append(copy.deepcopy(facts))

        service = self.make_service(Registry())
        items = [{"id": f"item{index}", "task_id": f"compression_task{index}", "name": f"{index}.png",
                  "status": "QUEUED", "source_id": "", "original_bytes": 1,
                  "source": {"width": 10, "height": 10}} for index in range(2)]
        service.batches = {"b": {"batch_id": "b", "control": "RUNNING", "workers": 1, "created_at": 0, "items": items}}
        calls = []

        async def work(batch, item):
            calls.append(item["id"])
            if item["id"] == "item0":
                raise RuntimeError("batch snapshot writer failed outside SharedTaskRegistryError")
            item["status"] = "COMPLETED"

        service.work = work

        async def run():
            with self.assertLogs("backend.batch_compression_api", level="ERROR"):
                service.ensure_running()
                await service.pump
            self.assertTrue(service.pump.done() and service.pump.exception() is None)
            self.assertEqual(service.active, {})
            batch = service.batches["b"]
            self.assertEqual(batch["control"], "PAUSED")
            self.assertEqual(items[0]["status"], "QUEUED")
            self.assertIn("不会重复生成成品", items[0]["error"])
            self.assertEqual(items[1]["status"], "QUEUED")
            self.assertTrue(persisted and persisted[-1]["b"]["control"] == "PAUSED")

            calls.clear()
            batch["control"] = "RUNNING"

            async def recovered(batch, item):
                item["status"] = "COMPLETED"
                calls.append(item["id"])

            service.work = recovered
            service.ensure_running()
            await service.pump
            self.assertEqual(calls, ["item0", "item1"])
            self.assertEqual([item["status"] for item in items], ["COMPLETED", "COMPLETED"])

        asyncio.run(run())

    def test_item_interrupted_by_app_shutdown_is_kept_for_recovery(self):
        class Registry(dict):
            def persist_facts(self, facts):
                self.update(copy.deepcopy(facts))

        registry = Registry()
        service = self.make_service(registry)
        source = service.cache_root() / "b" / "item0" / "source.png"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"saved source bytes")
        item = {"id": "item0", "task_id": "compression_task0", "reserved_result_id": "compression_result0",
                "name": "big.png", "status": "PROCESSING", "source_id": "", "original_bytes": 1,
                "source": {"path": str(source), "sha256": hashlib.sha256(b"saved source bytes").hexdigest(),
                           "width": 10, "height": 10}}
        batch = {"batch_id": "b", "control": "RUNNING", "workers": 1, "created_at": 0, "items": [item],
                 "output_directory": str(Path(service.output_directory()).resolve())}
        service.batches = {"b": batch}

        async def execute(payload, *, batch_job):
            await batch_job.checked_source()
            service.closing = True  # The window closed while this encode was running.
            raise RuntimeError("cannot schedule new futures after shutdown")

        service.execute = execute
        with self.assertLogs("backend.batch_compression_api", level="WARNING"):
            asyncio.run(service.work(batch, item))
        self.assertEqual(item["status"], "QUEUED")
        self.assertTrue(item["recovery_active"])
        self.assertIn("下次启动", item["error"])
        self.assertEqual(registry["b"]["items"][0]["status"], "QUEUED")

        # Identity failures are never softened into recovery, even while closing.
        item.update(status="PROCESSING", recovery_active=False)
        source.write_bytes(b"replaced while closing")
        asyncio.run(service.work(batch, item))
        self.assertEqual(item["status"], "FAILED")
        self.assertEqual(item["error"], "SOURCE_IDENTITY_MISMATCH")
