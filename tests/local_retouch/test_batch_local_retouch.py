import base64
import hashlib
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from backend.local_retouch_api import register_local_retouch_routes
from backend.batch_local_retouch_api import batch_retouch_path
from tests.local_retouch.test_local_retouch import RecordingAdapter


def image_bytes(size=(96, 64), color=(80, 120, 160, 127), orientation=None):
    image = Image.new("RGBA", size, color)
    stream = io.BytesIO()
    exif = Image.Exif()
    if orientation:
        exif[274] = orientation
    image.save(stream, "PNG", dpi=(144, 144), exif=exif)
    return stream.getvalue()


def mask_payload(revision=1, offset=0):
    mask = Image.new("L", (96, 64))
    draw = ImageDraw.Draw(mask)
    draw.rectangle((8 + offset, 10, 19 + offset, 21), fill=255)
    draw.line((40, 30, 56, 45), fill=255, width=9)
    draw.ellipse((45, 32, 48, 35), fill=0)
    stream = io.BytesIO()
    mask.save(stream, "PNG")
    return {"mask_revision": revision, "mask_png_base64": base64.b64encode(stream.getvalue()).decode()}


class BatchRetouchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.formal = self.root / "formal"
        self.formal.mkdir()
        self.registry = {}
        self.engine = RecordingAdapter(self.registry)
        self.app = FastAPI()
        self.state = register_local_retouch_routes(
            self.app, user_dirs_provider=lambda: {"directory_ready": True, "app_data_root": self.formal},
            shared_task_registry=self.registry, engine=self.engine,
        )
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.batch = self.client.post("/api/local-retouch/batches").json()["data"]
        self.url = f"/api/local-retouch/batches/{self.batch['batch_id']}"

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def add(self, content=None, name="授权素材.png"):
        response = self.client.post(self.url + "/items", files={"file": (name, content or image_bytes(), "image/png")})
        self.assertEqual(response.status_code, 200, response.text)
        self.batch = response.json()["data"]
        return self.batch["items"][-1]

    def wait_done(self):
        for _ in range(300):
            self.batch = self.client.get(self.url).json()["data"]
            if not self.batch["busy"]:
                return self.batch
            time.sleep(.01)
        self.fail("batch did not finish")

    def start(self, payload=None):
        response = self.client.post(self.url + "/start", json=payload or mask_payload())
        self.assertEqual(response.status_code, 200, response.text)
        return self.wait_done()

    def selection(self, items=None):
        return [{"item_id": item["item_id"], "session_id": item["candidate"]["session_id"]} for item in (items or self.batch["items"]) if item.get("candidate")]

    def restart(self):
        self.client.__exit__(None, None, None)
        self.app = FastAPI()
        self.state = register_local_retouch_routes(
            self.app, user_dirs_provider=lambda: {"directory_ready": True, "app_data_root": self.formal},
            shared_task_registry=self.registry, engine=self.engine,
        )
        self.client = TestClient(self.app)
        self.client.__enter__()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.text)
        self.batch = response.json()["data"]

    def test_recovery_reconciles_saved_result_and_restores_unconfirmed_candidate(self):
        self.add(name="saved.png")
        self.add(name="candidate.png")
        self.start()
        saved_selection, remaining = self.selection()
        manifest = batch_retouch_path(self.formal, self.batch["batch_id"]) / "batch.json"
        pre_save = manifest.read_bytes()
        response = self.client.post(self.url + "/confirm-save", json=mask_payload() | {"items": [saved_selection]})
        self.assertEqual(response.status_code, 200, response.text)
        output = next(record["result"] for record in self.registry.values() if record.get("result_id"))
        path = Path(output["output_path"])
        # A crash after the shared registry commit can leave the batch checkpoint behind.
        manifest.write_bytes(pre_save)
        self.restart()
        self.assertEqual([item["status"] for item in self.batch["items"]], ["saved", "candidate"])
        candidate = self.batch["items"][1]["candidate"]
        self.assertEqual(candidate["session_id"], remaining["session_id"])
        self.assertFalse(candidate["confirmed"])
        self.assertEqual(self.client.get(candidate["result_url"]).status_code, 200)
        encoded = self.client.get(self.url + "/selection").json()["data"]["mask_png_base64"]
        with Image.open(io.BytesIO(base64.b64decode(encoded))) as restored_mask:
            with Image.open(io.BytesIO(base64.b64decode(mask_payload()["mask_png_base64"]))) as original_mask:
                self.assertEqual(restored_mask.getchannel("A").tobytes(), original_mask.tobytes())
        self.assertEqual(self.client.post(self.url + "/confirm-save", json=mask_payload() | {"items": [saved_selection]}).status_code, 200)
        self.assertEqual(list(path.parent.glob("*.png")), [path])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), output["output_sha256"])

    def test_retry_after_publication_before_registry_commit_uses_same_file(self):
        self.add(name="publication.png")
        self.start()
        request = mask_payload() | {"items": self.selection()}
        task_id = self.batch["items"][0]["candidate"]["task_id"]
        record = dict(self.registry[task_id])
        manifest = batch_retouch_path(self.formal, self.batch["batch_id"]) / "batch.json"
        pre_save = manifest.read_bytes()
        self.assertEqual(self.client.post(self.url + "/confirm-save", json=request).status_code, 200)
        final = self.registry[task_id]
        path = Path(final["result"]["output_path"])
        # Preserve the published file and the pre-publication intent, as on process exit at this boundary.
        self.registry[task_id] = record | {"batch_save_intent": final["batch_save_intent"]}
        manifest.write_bytes(pre_save)
        self.restart()
        self.assertEqual(self.batch["items"][0]["status"], "candidate")
        response = self.client.post(self.url + "/confirm-save", json=request)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["items"][0]["status"], "saved")
        self.assertEqual(list(path.parent.glob("*.png")), [path])
        self.assertEqual(self.registry[task_id]["result"]["output_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_recovery_keeps_failed_and_cancelled_and_skips_bad_source_after_remarking(self):
        for name in ("failed.png", "cancelled.png", "lost.png", "pending.png"):
            self.add(name=name)
        self.assertEqual(self.client.put(self.url + "/selection", json=mask_payload()).status_code, 200)
        folder = batch_retouch_path(self.formal, self.batch["batch_id"])
        manifest = folder / "batch.json"
        state = json.loads(manifest.read_text(encoding="utf-8"))
        state.update(status="processing", busy=True)
        for item, status in zip(state["items"], ("failed", "cancelled", "processing", "queued")):
            item["status"] = status
        manifest.write_text(json.dumps(state), encoding="utf-8")
        Path(state["sessions"][state["items"][2]["source_session_id"]]["upload_path"]).unlink()
        (folder / f"mask-{state['groups']['96x64']['draft']['mask_file_sha256']}.png").write_bytes(b"damaged")
        self.restart()
        self.assertEqual([item["status"] for item in self.batch["items"]], ["failed", "cancelled", "ready", "ready"])
        self.assertIn("原图", self.batch["items"][2]["source_error"])
        self.assertIn("选区", self.client.get(self.url + "/selection").json()["data"]["error"])
        self.assertFalse(self.engine.calls)
        response = self.client.post(self.url + "/resume", json=mask_payload(2))
        self.assertEqual(response.status_code, 200, response.text)
        self.wait_done()
        self.assertEqual([item["status"] for item in self.batch["items"]], ["failed", "cancelled", "ready", "candidate"])
        self.assertEqual(len(self.engine.calls), 1)

    def test_three_candidates_bind_independent_sources_mask_and_explicit_save(self):
        for index in range(3):
            self.add(image_bytes(color=(50 + index * 50, 120, 160, 255)), name=f"授权素材{index}.png")
        self.start()
        self.assertEqual([item["status"] for item in self.batch["items"]], ["candidate"] * 3)
        self.assertEqual(len({item["candidate"]["task_id"] for item in self.batch["items"]}), 3)
        self.assertTrue(all(not record.get("result_id") and record["result_review_status"] == "pending" for record in self.registry.values()))
        masks = [Path(call[1]).read_bytes() for call in self.engine.calls]
        self.assertEqual(len(set(masks)), 1)
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.formal.rglob("授权素材*.png")}
        selected = self.selection()
        tampered = self.client.post(self.url + "/confirm-save", json=mask_payload() | {"items": [selected[0] | {"session_id": selected[1]["session_id"]}]})
        self.assertEqual(tampered.status_code, 409)
        stale = self.client.post(self.url + "/confirm-save", json=mask_payload(offset=1) | {"items": selected})
        self.assertEqual(stale.status_code, 409)
        saved = self.client.post(self.url + "/confirm-save", json=mask_payload() | {"items": selected})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual([item["status"] for item in saved.json()["data"]["items"]], ["saved"] * 3)
        records = list(self.registry.values())
        self.assertEqual(len({record["source_id"] for record in records}), 3)
        for record in records:
            result = record["result"]
            path = Path(result["output_path"])
            with Image.open(path) as opened:
                opened.load()
                self.assertEqual(opened.size, (96, 64))
            self.assertEqual(path.stat().st_size, result["output_size_bytes"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), result["output_sha256"])
            self.assertEqual(result["mask_sha256"], self.batch["mask_sha256"])
        self.assertTrue(all(hashlib.sha256(path.read_bytes()).hexdigest() == sha for path, sha in before.items()))
        again = self.client.post(self.url + "/confirm-save", json=mask_payload() | {"items": selected})
        self.assertEqual(again.status_code, 200)
        self.assertEqual(len(list((self.formal / "输出").rglob("*.png"))), 3)

    def test_normalized_geometry_bad_input_and_single_failure_are_isolated(self):
        self.add()
        self.add(image_bytes((64, 96), orientation=6))
        self.add(image_bytes((95, 64)))
        self.add(b"damaged image")
        self.add(name="last.png")
        original_process = self.engine.process
        def failing_process(source, mask, output):
            if len(self.engine.calls) == 1:
                self.engine.calls.append((source, mask, "failed"))
                raise RuntimeError("isolated engine failure")
            return original_process(source, mask, output)
        self.engine.process = failing_process
        self.assertEqual([g["group_id"] for g in self.batch["groups"]], ["96x64", "95x64"])
        self.assertEqual(self.client.post(self.url + "/start", json=mask_payload()).status_code, 409)
        self.assertEqual(self.client.post(self.url + "/start?group_id=96x64", json=mask_payload()).status_code, 200)
        self.wait_done()
        self.assertEqual([item["status"] for item in self.batch["items"]], ["candidate", "failed", "ready", "excluded", "candidate"])
        self.assertEqual(self.batch["finished"], 3)
        self.assertFalse(any(record.get("result_id") for record in self.registry.values()))

    def test_group_selections_and_candidates_survive_restart_and_reject_cross_group_actions(self):
        first = self.add()
        other = self.add(image_bytes((64, 96)))
        a = "?group_id=96x64"
        b = "?group_id=64x96"
        mask_a = mask_payload()
        mask_b = dict(mask_a)
        with Image.open(io.BytesIO(base64.b64decode(mask_a["mask_png_base64"]))) as opened:
            rotated = io.BytesIO()
            opened.transpose(Image.Transpose.ROTATE_90).save(rotated, "PNG")
        mask_b["mask_png_base64"] = base64.b64encode(rotated.getvalue()).decode()
        self.assertEqual(self.client.post(self.url + "/preview" + b, json=mask_b | {"item_id": first["item_id"]}).status_code, 409)
        self.assertEqual(self.client.post(self.url + "/start" + b, json=mask_a).status_code, 422)
        for query, mask, item in ((a, mask_a, first), (b, mask_b, other)):
            response = self.client.post(self.url + "/preview" + query, json=mask | {"item_id": item["item_id"]})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(self.client.post(self.url + "/start" + query, json=mask).status_code, 200)
            self.wait_done()
        before = self.selection()
        selections = [self.client.get(self.url + "/selection" + query).json()["data"] for query in (a, b)]
        self.assertNotEqual(selections[0]["mask_png_base64"], selections[1]["mask_png_base64"])
        self.restart()
        self.assertEqual(self.selection(), before)
        self.assertEqual(selections, [self.client.get(self.url + "/selection" + query).json()["data"] for query in (a, b)])
        self.assertEqual(self.client.post(self.url + "/confirm-save" + a, json=mask_a | {"items": before}).status_code, 409)
        self.assertFalse(any(record.get("result_id") for record in self.registry.values()))
        self.assertEqual(self.client.post(self.url + "/confirm-save" + b, json=mask_b | {"items": before[1:]}).status_code, 200)
        self.restart()
        self.assertEqual([item["status"] for item in self.batch["items"]], ["candidate", "saved"])

    def test_intake_replay_keeps_one_item_after_restart_and_binds_content(self):
        client_id = "a" * 32
        original = image_bytes()
        changed = image_bytes(color=(10, 20, 30, 255))

        def submit(content, key):
            return self.client.post(self.url + "/items", data={"client_item_id": key},
                                    files={"file": ("same-name.png", content, "image/png")})

        first = submit(original, client_id)
        self.assertEqual(first.status_code, 200, first.text)
        item = first.json()["data"]["items"][0]
        self.assertEqual(item["client_item_id"], client_id)
        self.restart()
        replay = submit(original, client_id)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["data"]["items"], [item])
        self.assertEqual(submit(changed, client_id).status_code, 409)
        second = submit(changed, "b" * 32)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(len({row["item_id"] for row in second.json()["data"]["items"]}), 2)

    def test_retry_only_failed_with_original_mask_after_resume_changes_batch_mask(self):
        for name in ("saved.png", "candidate.png", "temporary.png", "lost.png", "interrupted.png"):
            self.add(name=name)
        folder = batch_retouch_path(self.formal, self.batch["batch_id"])
        manifest = folder / "batch.json"
        stored = json.loads(manifest.read_text(encoding="utf-8"))
        lost = Path(stored["sessions"][stored["items"][3]["source_session_id"]]["upload_path"])
        lost.unlink()
        original_process = self.engine.process
        failed_masks = []

        def fail_once(source, mask, output):
            if len(self.engine.calls) == 2 and not failed_masks:
                failed_masks.append(Path(mask).read_bytes())
                raise RuntimeError("temporary processing error")
            return original_process(source, mask, output)

        self.engine.process = fail_once
        self.start()
        self.assertEqual([item["status"] for item in self.batch["items"]],
                         ["candidate", "candidate", "failed", "failed", "candidate"])
        saved, untouched, _ = self.selection()
        response = self.client.post(self.url + "/confirm-save", json=mask_payload() | {"items": [saved]})
        self.assertEqual(response.status_code, 200, response.text)
        saved_record = next(record["result"] for record in self.registry.values() if record.get("result_id"))
        path = Path(saved_record["output_path"])
        stored = json.loads(manifest.read_text(encoding="utf-8"))
        stored.update(status="processing", busy=True)
        stored["items"][-1].update(status="queued", candidate=None)
        manifest.write_text(json.dumps(stored), encoding="utf-8")
        self.restart()

        response = self.client.post(self.url + "/resume", json=mask_payload(2, offset=4))
        self.assertEqual(response.status_code, 200, response.text)
        self.wait_done()
        self.assertEqual([item["status"] for item in self.batch["items"]],
                         ["saved", "candidate", "failed", "failed", "candidate"])
        before = self.batch["items"]
        call_count = len(self.engine.calls)
        response = self.client.post(self.url + "/retry-failed")
        self.assertEqual(response.status_code, 200, response.text)
        self.wait_done()
        items = self.batch["items"]
        self.assertEqual([item["status"] for item in items],
                         ["saved", "candidate", "candidate", "failed", "candidate"])
        self.assertEqual(len(self.engine.calls), call_count + 1)
        self.assertEqual(Path(self.engine.calls[-1][1]).read_bytes(), failed_masks[0])
        self.assertEqual(items[1]["candidate"]["session_id"], untouched["session_id"])
        for index in (0, 1, 4):
            self.assertEqual(items[index], before[index])
        self.assertIn("原图已缺失", items[3]["source_error"])
        self.assertEqual(self.batch["draft_revision"], 2)
        self.assertEqual(items[2]["candidate"]["mask_revision"], 1)
        self.assertEqual(list(path.parent.glob("*.png")), [path])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), saved_record["output_sha256"])

        self.restart()
        request = {"items": self.selection([self.batch["items"][2]])}
        for _ in range(2):
            response = self.client.post(self.url + "/confirm-save", json=request)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["data"]["items"][2]["status"], "saved")
        self.assertEqual(len(list(path.parent.glob("*.png"))), 2)

    def test_retry_recovers_legacy_mask_binding_but_skips_damaged_mask(self):
        self.add()

        def fail_processing(*args):
            raise RuntimeError("temporary processing error")

        self.engine.process = fail_processing
        self.start()
        folder = batch_retouch_path(self.formal, self.batch["batch_id"])
        manifest = folder / "batch.json"
        stored = json.loads(manifest.read_text(encoding="utf-8"))
        stored["items"][0].pop("attempt_mask")
        group = stored.pop("groups")["96x64"]
        stored.update(schema=1, **{key: group[key] for key in ("width", "height", "draft", "snapshot")})
        stored["items"][0].pop("group_id")
        manifest.write_text(json.dumps(stored), encoding="utf-8")
        (folder / f"mask-{stored['snapshot']['mask_file_sha256']}.png").write_bytes(b"damaged")
        self.restart()
        response = self.client.post(self.url + "/retry-failed")
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["data"]["items"][0]
        self.assertEqual(item["status"], "failed")
        self.assertIn("原先使用的选区已缺失或损坏", item["error"])
        self.assertFalse(response.json()["data"]["busy"])

    def test_preview_starts_from_original_and_cannot_be_saved_as_batch_result(self):
        item = self.add()
        for revision in (1, 2):
            response = self.client.post(self.url + "/preview", json=mask_payload(revision) | {"item_id": item["item_id"]})
            self.assertEqual(response.status_code, 200, response.text)
        inputs = [call[2] for call in self.engine.calls]
        self.assertEqual(len(set(inputs)), 1)
        preview = response.json()["data"]["items"][0]["preview"]
        self.assertEqual(self.client.post(f"/api/local-retouch/sessions/{preview['session_id']}/confirm", json={"mask_revision": 2}).status_code, 409)
        refused = self.client.post(self.url + "/confirm-save", json=mask_payload(2) | {"items": [{"item_id": item["item_id"], "session_id": preview["session_id"]}]})
        self.assertEqual(refused.status_code, 409)
        self.start(mask_payload(2))
        self.assertEqual(len(set(call[2] for call in self.engine.calls)), 1)

    def test_cancel_is_responsive_and_retains_finished_without_starting_next(self):
        for _ in range(3):
            self.add()
        started, release = threading.Event(), threading.Event()
        original_process = self.engine.process
        def held_process(*args):
            started.set()
            if not release.wait(5):
                raise RuntimeError("test release timeout")
            return original_process(*args)
        self.engine.process = held_process
        try:
            self.assertEqual(self.client.post(self.url + "/start", json=mask_payload()).status_code, 200)
            self.assertTrue(started.wait(2))
            self.assertEqual(self.client.post(self.url + "/start", json=mask_payload()).status_code, 409)
            self.assertEqual(self.client.post(self.url + "/cancel").status_code, 200)
        finally:
            release.set()
        self.wait_done()
        self.assertEqual([item["status"] for item in self.batch["items"]], ["candidate", "cancelled", "cancelled"])
        self.assertEqual(len(self.engine.calls), 1)
        self.assertFalse(any(record.get("result_id") for record in self.registry.values()))

    def test_single_and_batch_intake_accept_real_png_above_50_mib(self):
        import numpy as np
        pixels = np.random.default_rng(20261104).integers(0, 256, (3600, 5000, 3), dtype=np.uint8)
        stream = io.BytesIO()
        Image.fromarray(pixels).save(stream, "PNG", compress_level=0)
        content = stream.getvalue()
        self.assertGreater(len(content), 50 * 1024 * 1024)
        capabilities = self.client.get("/api/local-retouch/capabilities").json()["data"]
        self.assertIsNone(capabilities["max_upload_bytes"])
        single = self.client.post("/api/local-retouch/intake", files={"file": ("大于50MiB.png", content, "image/png")})
        self.assertEqual(single.status_code, 200, single.text)
        item = self.add(content, name="批量大于50MiB.png")
        self.assertEqual(item["status"], "ready")
        for data in (single.json()["data"], item["source"]):
            self.assertEqual((data["width"], data["height"]), (5000, 3600))
            self.assertEqual(data["source_sha256"], hashlib.sha256(content).hexdigest())
        self.assertFalse(self.registry)

    def test_formal_task_source_remains_readable_after_retouch_session_expires(self):
        import ast
        import urllib.parse
        from fastapi import HTTPException
        from fastapi.responses import FileResponse
        from engine.storage.app_data_migration import resolve_migrated_formal_output_path

        self.add()
        self.start()
        saved = self.client.post(self.url + "/confirm-save", json=mask_payload() | {"items": self.selection()})
        self.assertEqual(saved.status_code, 200)
        item = saved.json()["data"]["items"][0]
        task_id = item["candidate"]["task_id"]
        source = Path(__file__).resolve().parents[2] / "main.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        factory = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build_web_app"][-1]
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "public_file_url"]
        functions += [node for node in factory.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {"public_task", "task_status", "task_source_file"}]
        namespace = {"app": self.app, "Path": Path, "HTTPException": HTTPException,
                     "FileResponse": FileResponse, "task_registry": self.registry,
                     "current_user_dirs": lambda: {"app_data_root": self.formal},
                     "resolve_migrated_formal_output_path": resolve_migrated_formal_output_path,
                     "urllib": urllib, "DEFAULT_TASK_ID": "task_vmp_v04_core", "latest_task_id": {"value": ""}}
        for function in functions:
            exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        self.state["sessions"].clear()
        data = self.client.get(f"/api/v1/tasks/{task_id}").json()["data"]
        self.assertEqual(data["originalUrl"], f"/api/v1/tasks/{task_id}/source-file")
        response = self.client.get(data["originalUrl"])
        self.assertEqual(response.status_code, 200)
        with Image.open(io.BytesIO(response.content)) as opened:
            opened.load()
            self.assertEqual(opened.size, (96, 64))


if __name__ == "__main__":
    unittest.main()
