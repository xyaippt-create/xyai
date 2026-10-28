import base64
import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from backend.image_compression_api import register_image_compression_routes
from backend.batch_watermark_api import register_batch_watermark_routes
from backend.local_retouch_api import register_local_retouch_routes
from engine.local_retouch.contracts import LocalRetouchResult
from engine.storage.shared_task_registry import SharedTaskRegistry


def image_bytes(size=(120, 80), color=(35, 105, 185, 255)):
    stream = io.BytesIO()
    Image.new("RGBA", size, color).save(stream, format="PNG")
    return stream.getvalue()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mask_data_url(size=(60, 40)):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle((18, 12, 31, 25), fill=255)
    stream = io.BytesIO()
    mask.save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


class RecordingRetouchEngine:
    engine_id = "continue_processing_test_adapter"

    def capabilities(self):
        return {"available": True, "engine_id": self.engine_id}

    def process(self, source_path, mask_path, output_path):
        source_path = Path(source_path)
        with Image.open(source_path) as opened:
            source = opened.convert("RGBA")
        with Image.open(mask_path) as opened:
            mask = opened.convert("L")
        result = source.copy()
        result.paste(Image.new("RGBA", source.size, (180, 125, 70, 255)), mask=mask)
        result.save(output_path, format="PNG")
        return LocalRetouchResult(
            engine_id=self.engine_id,
            output_path=Path(output_path),
            width=source.width,
            height=source.height,
            format="PNG",
            mask_pixels=sum(mask.histogram()[128:]),
            inference_seconds=0.01,
            source_sha256=sha256(source_path),
        )


class ContinueProcessingWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.formal = self.root / "formal"
        self.output_root = self.formal / "输出"
        self.tmp = self.formal / "临时文件"
        self.normal = self.output_root / "1080P画质"
        self.compression = self.output_root / "图片压缩"
        self.normal.mkdir(parents=True)
        self.compression.mkdir(parents=True)
        self.tmp.mkdir(parents=True)
        self.registry = SharedTaskRegistry(self.formal)
        self.source_a = self.normal / "existing-result-a.png"
        self.source_a.write_bytes(image_bytes())
        self.source_a_sha = sha256(self.source_a)
        self.registry["task-a"] = {
            "task_id": "task-a",
            "result_id": "result-a",
            "feature_key": "image_processing",
            "task_family": "image_processing",
            "processing_type": "1080p",
            "status": "completed",
            "task_status": "completed",
            "source_path": str(self.source_a),
            "output_path": str(self.source_a),
            "result_file": str(self.source_a),
            "output_sha256": self.source_a_sha,
            "task_result": {
                "result_id": "result-a",
                "task_id": "task-a",
                "feature_key": "image_processing",
                "status": "completed",
                "output_path": str(self.source_a),
                "result_file": str(self.source_a),
                "output_sha256": self.source_a_sha,
            },
        }
        self.app, self.compression_state, self.retouch_state = self.build_app(self.registry)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def user_dirs(self):
        return {
            "directory_ready": True,
            "app_data_root": self.formal,
            "normal_output_dir": self.normal,
            "safe_beta_output_dir": self.normal,
            "image_compression_output_dir": self.compression,
            "tmp_dir": self.tmp,
        }

    def build_app(self, registry):
        app = FastAPI()

        def validate_output_root(value):
            target = Path(value).resolve()
            target.mkdir(parents=True, exist_ok=True)
            return {"valid": True, "writable": True, "normalized_path": str(target), "message": "输出目录可用"}

        compression_state = register_image_compression_routes(
            app,
            user_dirs_provider=self.user_dirs,
            output_center_user_dirs_provider=self.user_dirs,
            output_settings_provider=lambda: {
                "built_in_default_root": str(self.compression),
                "saved_default_root": str(self.compression),
            },
            output_dir_validator=validate_output_root,
            shared_task_registry=registry,
            now_provider=lambda: 1_800_000_000.0,
        )
        retouch_state = register_local_retouch_routes(
            app,
            user_dirs_provider=self.user_dirs,
            shared_task_registry=registry,
            engine=RecordingRetouchEngine(),
            now_provider=lambda: 1_800_000_001.0,
        )
        register_batch_watermark_routes(
            app,
            user_dirs_provider=self.user_dirs,
            shared_task_registry=registry,
            now_provider=lambda: 1_800_000_002.0,
        )
        return app, compression_state, retouch_state

    def test_result_a_to_compression_b_to_retouch_c_survives_restart(self):
        items = self.client.get("/api/output-center/items").json()["data"]["items"]
        existing = next(item for item in items if item["result_id"] == "result-a")
        self.assertTrue(existing["continue_eligible"])
        self.assertEqual(
            existing["continue_processor_keys"],
            ["color_correction", "image_compression", "local_retouch", "batch_watermark"],
        )
        eligibility_response = self.client.get(
            f"/api/output-center/items/{existing['id']}/continue-eligibility"
        )
        self.assertEqual(eligibility_response.status_code, 200, eligibility_response.text)
        eligibility = eligibility_response.json()["data"]["processors"]
        self.assertEqual(
            [entry["label"] for entry in eligibility],
            ["画质增强", "颜色校正", "图片压缩", "瑕疵修复", "添加水印"],
        )
        self.assertEqual(
            [entry["status"] for entry in eligibility],
            ["UNAVAILABLE", "AVAILABLE", "AVAILABLE", "AVAILABLE", "AVAILABLE"],
        )
        self.assertEqual(
            [entry["history_status"] for entry in eligibility],
            ["PROCESSED", "NOT_PROCESSED", "NOT_PROCESSED", "NOT_PROCESSED", "NOT_PROCESSED"],
        )
        self.assertEqual([entry["repeatable"] for entry in eligibility], [False, True, True, True, True])
        self.assertEqual(eligibility[0]["reason"], "已完成画质增强。")

        intake_b_response = self.client.post("/api/image-compression/intake-result", json={"result_id": "result-a"})
        self.assertEqual(intake_b_response.status_code, 200, intake_b_response.text)
        intake_b = intake_b_response.json()["data"]
        self.assertEqual(intake_b["source_origin"], "EXISTING_RESULT")
        self.assertEqual(intake_b["source_result_id"], "result-a")
        self.assertNotEqual(Path(self.compression_state["token_registry"][intake_b["source_token"]]["path"]), self.source_a)

        run_b_response = self.client.post("/api/image-compression/run", json={
            "source_token": intake_b["source_token"],
            "operation_mode": "RESIZE_REDUCTION",
            "params": {"target_short_side": 40},
        })
        self.assertEqual(run_b_response.status_code, 200, run_b_response.text)
        run_b = run_b_response.json()["data"]
        task_b_id = run_b["task"]["task_id"]
        result_b_id = run_b["task"]["result_id"]
        record_b = self.registry[task_b_id]
        output_b = Path(record_b["result_file"])
        self.assertNotEqual(task_b_id, "task-a")
        self.assertNotEqual(result_b_id, "result-a")
        self.assertEqual(record_b["source_result_id"], "result-a")
        self.assertEqual(record_b["source_task_id"], "task-a")
        self.assertEqual(record_b["task_result"]["source_result_id"], "result-a")
        self.assertTrue(output_b.is_file())

        intake_c_response = self.client.post("/api/local-retouch/intake-result", json={"result_id": result_b_id})
        self.assertEqual(intake_c_response.status_code, 200, intake_c_response.text)
        intake_c = intake_c_response.json()["data"]
        self.assertEqual(intake_c["source_result_id"], result_b_id)
        session_id = intake_c["session_id"]
        process_c_response = self.client.post(
            f"/api/local-retouch/sessions/{session_id}/process",
            json={"mask_png_base64": mask_data_url(), "mask_revision": 1},
        )
        self.assertEqual(process_c_response.status_code, 200, process_c_response.text)
        processed_c = process_c_response.json()["data"]
        confirmed_c = self.client.post(
            f"/api/local-retouch/sessions/{session_id}/confirm",
            json={"mask_revision": processed_c["mask_revision"]},
        )
        self.assertEqual(confirmed_c.status_code, 200, confirmed_c.text)
        saved_c_response = self.client.post(f"/api/local-retouch/sessions/{session_id}/save", json={})
        self.assertEqual(saved_c_response.status_code, 200, saved_c_response.text)
        saved_c = saved_c_response.json()["data"]
        task_c_id = saved_c["task_id"]
        result_c_id = saved_c["result_id"]
        record_c = self.registry[task_c_id]
        output_c = Path(record_c["result_file"])
        self.assertEqual(record_c["source_result_id"], result_b_id)
        self.assertEqual(record_c["source_task_id"], task_b_id)
        self.assertEqual(record_c["task_result"]["source_result_id"], result_b_id)

        source_c_sha = sha256(output_c)
        watermark_d_response = self.client.post(
            "/api/batch-watermark/batches",
            data={
                "result_ids_json": f'["{result_c_id}"]',
                "spec_json": '{"kind":"text","text":"多轮处理"}',
            },
        )
        self.assertEqual(watermark_d_response.status_code, 200, watermark_d_response.text)
        watermark_d = watermark_d_response.json()["data"]
        result_d = watermark_d["items"][0]
        task_d_id = watermark_d["batch_id"]
        result_d_id = result_d["result_id"]
        output_d = Path(result_d["output_path"])
        self.assertEqual(result_d["source_result_id"], result_c_id)
        self.assertEqual(result_d["source_task_id"], task_c_id)
        self.assertEqual(result_d["source_result_sha256"], source_c_sha)
        self.assertEqual(sha256(output_c), source_c_sha)
        self.assertEqual(sha256(output_d), result_d["output_sha256"])

        self.assertEqual(len({"task-a", task_b_id, task_c_id, task_d_id}), 4)
        self.assertEqual(len({"result-a", result_b_id, result_c_id, result_d_id}), 4)
        self.assertEqual(sha256(self.source_a), self.source_a_sha)
        self.assertTrue(output_b.is_file())
        self.assertTrue(output_c.is_file())
        self.assertTrue(output_d.is_file())
        with Image.open(output_b) as opened:
            opened.load()
        with Image.open(output_c) as opened:
            opened.load()

        refreshed_items = self.client.get("/api/output-center/items").json()["data"]["items"]
        # OC-00 batches consume one top-level card; identities belong to their children.
        refreshed_items = [child for card in refreshed_items for child in card.get("items", [card])]
        refreshed_ids = {item["result_id"] for item in refreshed_items}
        self.assertTrue({"result-a", result_b_id, result_c_id, result_d_id}.issubset(refreshed_ids))
        item_d = next(item for item in refreshed_items if item["result_id"] == result_d_id)
        eligibility_d = self.client.get(
            f"/api/output-center/items/{item_d['id']}/continue-eligibility"
        ).json()["data"]["processors"]
        state_by_key = {entry["key"]: entry for entry in eligibility_d}
        self.assertEqual(state_by_key["image_enhancement"]["status"], "UNAVAILABLE")
        self.assertEqual(state_by_key["image_enhancement"]["history_status"], "PROCESSED")
        self.assertEqual(state_by_key["image_compression"]["status"], "AVAILABLE")
        self.assertEqual(state_by_key["image_compression"]["history_status"], "PROCESSED")
        self.assertEqual(state_by_key["local_retouch"]["status"], "AVAILABLE")
        self.assertEqual(state_by_key["local_retouch"]["history_status"], "PROCESSED")
        self.assertEqual(state_by_key["color_correction"]["status"], "AVAILABLE")
        self.assertEqual(state_by_key["batch_watermark"]["status"], "AVAILABLE")
        self.assertEqual(state_by_key["batch_watermark"]["history_status"], "PROCESSED")

        reloaded_registry = SharedTaskRegistry(self.formal)
        restarted_app, _, _ = self.build_app(reloaded_registry)
        with TestClient(restarted_app) as restarted_client:
            restarted_cards = restarted_client.get("/api/output-center/items").json()["data"]["items"]
            restarted_ids = {item["result_id"] for card in restarted_cards for item in card.get("items", [card])}
            self.assertTrue({"result-a", result_b_id, result_c_id, result_d_id}.issubset(restarted_ids))
            reusable_again = restarted_client.post("/api/image-compression/intake-result", json={"result_id": result_d_id})
            self.assertEqual(reusable_again.status_code, 200, reusable_again.text)
            self.assertEqual(reusable_again.json()["data"]["source_result_id"], result_d_id)

    def test_eligibility_endpoint_does_not_reopen_or_rescan_the_result_file(self):
        items = self.client.get("/api/output-center/items").json()["data"]["items"]
        existing = next(item for item in items if item["result_id"] == "result-a")
        original = self.source_a.read_bytes()
        self.source_a.unlink()
        try:
            response = self.client.get(
                f"/api/output-center/items/{existing['id']}/continue-eligibility"
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(response.json()["data"]["processors"]), 5)
        finally:
            self.source_a.write_bytes(original)

    def test_processed_color_history_remains_repeatable(self):
        color_dir = self.output_root / "颜色校正"
        color_dir.mkdir(parents=True)
        color_output = color_dir / "color-result-b.png"
        color_output.write_bytes(self.source_a.read_bytes())
        color_sha = sha256(color_output)
        result = {
            "result_id": "color-result-b",
            "task_id": "color-task-b",
            "feature_key": "color_correction",
            "status": "completed",
            "output_path": str(color_output),
            "result_file": str(color_output),
            "output_sha256": color_sha,
            "source_result_id": "result-a",
            "source_task_id": "task-a",
            "source_feature_key": "image_processing",
        }
        self.registry["color-task-b"] = {
            **result,
            "task_family": "color_correction",
            "processing_type": "color_correction",
            "task_status": "completed",
            "source_path": str(self.source_a),
            "task_result": result,
        }

        items = self.client.get("/api/output-center/items").json()["data"]["items"]
        item = next(entry for entry in items if entry["result_id"] == "color-result-b")
        processors = self.client.get(
            f"/api/output-center/items/{item['id']}/continue-eligibility"
        ).json()["data"]["processors"]
        color = next(entry for entry in processors if entry["key"] == "color_correction")
        self.assertEqual(color["history_status"], "PROCESSED")
        self.assertEqual(color["status"], "AVAILABLE")
        self.assertTrue(color["repeatable"])
        self.assertEqual(color["reason"], "已处理，可再次处理。")

    def test_color_result_intake_preserves_exact_result_lineage(self):
        response = self.client.post("/api/color-correction/intake-result", json={"result_id": "result-a"})

        self.assertEqual(response.status_code, 200, response.text)
        intake = response.json()["data"]
        self.assertEqual(intake["source_origin"], "EXISTING_RESULT")
        self.assertEqual(intake["source_result_id"], "result-a")
        self.assertEqual(intake["source_task_id"], "task-a")
        self.assertEqual(intake["source_feature_key"], "image_processing")
        self.assertEqual(intake["source_result_sha256"], self.source_a_sha)

        run = self.client.post("/api/color-correction/run", json={"source_token": intake["source_token"]})
        # Frozen D61: ACCEPT_ORIGINAL is failed/Result=null, preserving the input lineage.
        self.assertIn(run.status_code, {200, 422}, run.text)
        task = run.json()["data"]["task"]
        result = run.json()["data"]["result"]
        self.assertEqual(task["source_result_id"], "result-a")
        self.assertEqual(task["source_task_id"], "task-a")
        if run.status_code == 422:
            self.assertEqual(task["status"], "failed")
            self.assertFalse(task["result_id"])
            self.assertIsNone(result)
        if result is not None:
            self.assertEqual(result["source_result_id"], "result-a")
            self.assertEqual(result["source_task_id"], "task-a")
        self.assertEqual(sha256(self.source_a), self.source_a_sha)

    def test_missing_or_incomplete_result_fails_without_touching_existing_result(self):
        missing_path = self.normal / "missing.png"
        missing_path.write_bytes(image_bytes((64, 48)))
        missing_sha = sha256(missing_path)
        self.registry["task-missing"] = {
            "task_id": "task-missing",
            "result_id": "result-missing",
            "feature_key": "image_processing",
            "status": "completed",
            "output_path": str(missing_path),
            "output_sha256": missing_sha,
        }
        missing_path.unlink()
        keys_before = set(self.registry)
        response = self.client.post("/api/image-compression/intake-result", json={"result_id": "result-missing"})
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["detail"]["code"], "RESULT_REUSE_FILE_MISSING")
        self.assertEqual(set(self.registry), keys_before)
        self.assertEqual(sha256(self.source_a), self.source_a_sha)

        incomplete_path = self.normal / "incomplete.png"
        incomplete_path.write_bytes(image_bytes((64, 48)))
        self.registry["task-incomplete"] = {
            "task_id": "task-incomplete",
            "result_id": "result-incomplete",
            "feature_key": "image_processing",
            "status": "completed",
            "output_path": str(incomplete_path),
        }
        incomplete = self.client.post("/api/local-retouch/intake-result", json={"result_id": "result-incomplete"})
        self.assertEqual(incomplete.status_code, 409, incomplete.text)
        self.assertEqual(incomplete.json()["detail"]["code"], "RESULT_REUSE_INCOMPLETE")

        damaged_path = self.normal / "damaged.png"
        damaged_path.write_bytes(b"not-a-decodable-image")
        self.registry["task-damaged"] = {
            "task_id": "task-damaged",
            "result_id": "result-damaged",
            "feature_key": "image_processing",
            "status": "completed",
            "output_path": str(damaged_path),
            "output_sha256": sha256(damaged_path),
        }
        damaged = self.client.post("/api/local-retouch/intake-result", json={"result_id": "result-damaged"})
        self.assertEqual(damaged.status_code, 422, damaged.text)
        self.assertEqual(damaged.json()["detail"]["code"], "RETOUCH_IMAGE_INVALID")

        outside_path = self.root / "outside-formal.png"
        outside_path.write_bytes(image_bytes((64, 48)))
        self.registry["task-outside"] = {
            "task_id": "task-outside",
            "result_id": "result-outside",
            "feature_key": "image_processing",
            "status": "completed",
            "output_path": str(outside_path),
            "output_sha256": sha256(outside_path),
        }
        outside = self.client.post("/api/image-compression/intake-result", json={"result_id": "result-outside"})
        self.assertEqual(outside.status_code, 409, outside.text)
        self.assertEqual(outside.json()["detail"]["code"], "RESULT_REUSE_PATH_UNSAFE")
        self.assertEqual(sha256(self.source_a), self.source_a_sha)

    def test_exact_result_id_ignores_incomplete_batch_reference_and_selects_requested_history_item(self):
        history_a = self.normal / "history-a" / "same-name.png"
        history_b = self.normal / "history-b" / "same-name.png"
        history_a.parent.mkdir()
        history_b.parent.mkdir()
        history_a.write_bytes(image_bytes(color=(180, 35, 45, 255)))
        history_b.write_bytes(image_bytes(color=(35, 180, 75, 255)))
        for suffix, path in (("a", history_a), ("b", history_b)):
            self.registry[f"task-history-{suffix}"] = {
                "task_id": f"task-history-{suffix}",
                "result_id": f"result-history-{suffix}",
                "feature_key": "image_compression",
                "status": "completed",
                "output_path": str(path),
                "output_sha256": sha256(path),
            }
        self.registry["batch-history"] = {
            "record_kind": "compression_batch",
            "items": [
                {
                    "task_id": "task-history-b",
                    "result_id": "result-history-b",
                    "status": "COMPLETED",
                    "output_sha256": sha256(history_b),
                }
            ],
        }

        response = self.client.post(
            "/api/local-retouch/intake-result",
            json={"result_id": "result-history-b"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        session = response.json()["data"]
        self.assertEqual(session["source_result_id"], "result-history-b")
        self.assertEqual(session["source_task_id"], "task-history-b")
        self.assertEqual(session["source_result_sha256"], sha256(history_b))
        with Image.open(self.retouch_state["sessions"][session["session_id"]]["working_path"]) as opened:
            opened.load()
            self.assertEqual(opened.getpixel((0, 0)), (35, 180, 75, 255))

    def test_true_result_identity_conflict_and_unknown_id_fail_closed(self):
        conflicting = self.normal / "conflicting.png"
        conflicting.write_bytes(image_bytes(color=(90, 40, 160, 255)))
        self.registry["task-conflicting"] = {
            "task_id": "task-conflicting",
            "result_id": "result-a",
            "feature_key": "image_processing",
            "status": "completed",
            "output_path": str(conflicting),
            "output_sha256": sha256(conflicting),
        }
        keys_before = set(self.registry)

        conflict = self.client.post("/api/local-retouch/intake-result", json={"result_id": "result-a"})
        unknown = self.client.post("/api/local-retouch/intake-result", json={"result_id": "result-unknown"})

        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["detail"]["code"], "RESULT_REUSE_CONFLICT")
        self.assertEqual(unknown.status_code, 404, unknown.text)
        self.assertEqual(unknown.json()["detail"]["code"], "RESULT_REUSE_NOT_FOUND")
        self.assertEqual(set(self.registry), keys_before)
        self.assertEqual(sha256(self.source_a), self.source_a_sha)


if __name__ == "__main__":
    unittest.main()
