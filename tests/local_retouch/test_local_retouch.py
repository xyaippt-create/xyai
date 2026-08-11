import base64
import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from backend.local_retouch_api import LOCAL_RETOUCH_FEATURE_KEY, register_local_retouch_routes
from engine.local_retouch.contracts import LocalRetouchResult
from engine.local_retouch.lama_adapter import DEFAULT_MODEL_PATH, LamaOnnxAdapter


def png_bytes(size=(96, 72), color=(45, 78, 120, 255)):
    stream = io.BytesIO()
    Image.new("RGBA", size, color).save(stream, format="PNG")
    return stream.getvalue()


def mask_data_url(size=(96, 72), box=(30, 20, 50, 40)):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle(box, fill=255)
    stream = io.BytesIO()
    mask.save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


class RecordingAdapter:
    engine_id = "recording_lama_adapter"

    def __init__(self, registry=None):
        self.calls = []
        self.registry = registry
        self.registry_snapshots = []

    def capabilities(self):
        return {"available": True, "engine_id": self.engine_id}

    def process(self, source_path, mask_path, output_path):
        source_path = Path(source_path)
        mask_path = Path(mask_path)
        output_path = Path(output_path)
        if self.registry is not None:
            self.registry_snapshots.append([dict(record) for record in self.registry.values()])
        self.calls.append((source_path, mask_path, hashlib.sha256(source_path.read_bytes()).hexdigest()))
        with Image.open(source_path) as opened:
            source = opened.convert("RGBA")
        with Image.open(mask_path) as opened:
            mask = opened.convert("L")
        result = source.copy()
        fill = Image.new("RGBA", source.size, (180, 130, 70, 255))
        result.paste(fill, mask=mask)
        result.save(output_path, format="PNG")
        return LocalRetouchResult(
            engine_id=self.engine_id,
            output_path=output_path,
            width=source.width,
            height=source.height,
            format="PNG",
            mask_pixels=sum(1 for value in mask.getdata() if value >= 128),
            inference_seconds=0.01,
            source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
        )


class LocalRetouchApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.formal = self.root / "formal"
        self.tmp = self.formal / "临时文件"
        self.tmp.mkdir(parents=True)
        self.shared_registry = {}
        self.runtime_events = []
        self.engine = RecordingAdapter(self.shared_registry)
        app = FastAPI()
        register_local_retouch_routes(
            app,
            user_dirs_provider=lambda: {
                "directory_ready": True,
                "app_data_root": self.formal,
                "tmp_dir": self.tmp,
            },
            shared_task_registry=self.shared_registry,
            engine=self.engine,
            now_provider=lambda: 1_786_262_400.0,
            runtime_event_logger=lambda event, **fields: self.runtime_events.append({"event": event, **fields}),
        )
        self.client = TestClient(app)
        self.source = png_bytes()

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def intake(self):
        response = self.client.post("/api/local-retouch/intake", files={"file": ("授权素材.png", self.source, "image/png")})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def process(self, session_id, revision, box):
        return self.client.post(
            f"/api/local-retouch/sessions/{session_id}/process",
            json={"mask_png_base64": mask_data_url(box=box), "mask_revision": revision},
        )

    def test_retry_always_uses_working_source_then_confirm_saves_derived_result(self):
        intake = self.intake()
        session_id = intake["session_id"]
        first = self.process(session_id, 1, (15, 15, 28, 28))
        self.assertEqual(first.status_code, 200, first.text)
        first_payload = first.json()["data"]
        first_task_id = first_payload["task_id"]
        self.assertEqual(first_payload["feature_key"], LOCAL_RETOUCH_FEATURE_KEY)
        self.assertTrue(first_task_id.startswith("retouch_task_"))
        self.assertEqual(first_payload["result_id"], "")
        second = self.process(session_id, 2, (55, 34, 70, 50))
        self.assertEqual(second.status_code, 200, second.text)
        second_payload = second.json()["data"]
        second_task_id = second_payload["task_id"]
        self.assertNotEqual(first_task_id, second_task_id)
        self.assertEqual(second_payload["result_id"], "")
        self.assertEqual(len(self.engine.calls), 2)
        self.assertEqual(len(self.engine.registry_snapshots), 2)
        for task_id, snapshot in zip((first_task_id, second_task_id), self.engine.registry_snapshots, strict=True):
            task_before_engine = next(record for record in snapshot if record["task_id"] == task_id)
            self.assertEqual(task_before_engine["feature_key"], LOCAL_RETOUCH_FEATURE_KEY)
            self.assertEqual(task_before_engine["status"], "processing")
            self.assertFalse(task_before_engine["result_id"])
            self.assertIsNone(task_before_engine["result"])
        self.assertEqual(self.engine.calls[0][0], self.engine.calls[1][0])
        self.assertEqual(self.engine.calls[0][2], self.engine.calls[1][2])
        self.assertEqual(second.json()["data"]["retry_source"], "working_source")

        stale = self.client.post(f"/api/local-retouch/sessions/{session_id}/confirm", json={"mask_revision": 1})
        self.assertEqual(stale.status_code, 409)
        confirmed = self.client.post(f"/api/local-retouch/sessions/{session_id}/confirm", json={"mask_revision": 2})
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.json()["data"]["result_id"], "")
        self.assertEqual(self.shared_registry[second_task_id]["result_id"], "")
        self.assertIsNone(self.shared_registry[second_task_id]["result"])
        saved = self.client.post(f"/api/local-retouch/sessions/{session_id}/save", json={})
        self.assertEqual(saved.status_code, 200, saved.text)
        payload = saved.json()["data"]
        self.assertTrue(payload["saved"])
        self.assertTrue(payload["result_id"].startswith("retouch_result_"))
        self.assertEqual(payload["task_id"], second_task_id)
        self.assertEqual(payload["feature_key"], LOCAL_RETOUCH_FEATURE_KEY)
        self.assertNotEqual(payload["task_id"], payload["result_id"])
        output = self.formal / "输出" / "标记修整" / payload["output_file_name"]
        self.assertTrue(output.is_file())
        with Image.open(output) as opened:
            opened.load()
            self.assertEqual((opened.size, opened.format), ((96, 72), "PNG"))
        intake_copy = self.tmp / "local-retouch" / session_id / "授权素材.png"
        self.assertEqual(hashlib.sha256(intake_copy.read_bytes()).hexdigest(), hashlib.sha256(self.source).hexdigest())
        record = self.shared_registry[payload["task_id"]]
        self.assertEqual(record["task_id"], payload["task_id"])
        self.assertEqual(record["result_id"], payload["result_id"])
        self.assertNotEqual(record["task_id"], record["result_id"])
        self.assertEqual(record["feature_key"], LOCAL_RETOUCH_FEATURE_KEY)
        self.assertEqual(record["source"], str(intake_copy.resolve()))
        self.assertEqual(record["result_file"], str(output.resolve()))
        self.assertEqual(record["task_family"], "local_retouch")
        self.assertEqual(record["processing_type"], "local_retouch")
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["progress"], 100)
        self.assertEqual(Path(record["source_path"]), intake_copy.resolve())
        self.assertEqual(Path(record["output_path"]), output.resolve())
        self.assertEqual(record["result"]["source_sha256"], hashlib.sha256(self.source).hexdigest())
        self.assertEqual(record["result"]["output_path"], str(output.resolve()))
        self.assertEqual(record["result"]["task_id"], payload["task_id"])
        self.assertEqual(record["result"]["feature_key"], LOCAL_RETOUCH_FEATURE_KEY)
        self.assertEqual(record["result"]["source"], str(intake_copy.resolve()))
        self.assertEqual(record["result"]["result_file"], str(output.resolve()))
        self.assertEqual(self.shared_registry[first_task_id]["result_id"], "")
        self.assertEqual(self.shared_registry[first_task_id]["processing_stage"], "preview_superseded")
        self.assertIsNone(self.shared_registry[first_task_id]["preview_path"])

        repeated = self.client.post(f"/api/local-retouch/sessions/{session_id}/save", json={})
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["data"]["result_id"], payload["result_id"])
        self.assertEqual(len(self.shared_registry), 2)
        event_names = [event["event"] for event in self.runtime_events]
        for required in ("TASK_CREATED", "PROCESS_STARTED", "PROCESS_SUCCEEDED", "USER_CONFIRMED", "RESULT_REGISTERED"):
            self.assertIn(required, event_names)
        registered = next(event for event in self.runtime_events if event["event"] == "RESULT_REGISTERED")
        self.assertEqual(registered["feature_key"], LOCAL_RETOUCH_FEATURE_KEY)
        self.assertEqual(registered["task_id"], second_task_id)
        self.assertEqual(registered["result_id"], payload["result_id"])

    def test_save_before_confirmation_is_blocked_without_output(self):
        intake = self.intake()
        session_id = intake["session_id"]
        self.assertEqual(self.process(session_id, 1, (20, 20, 35, 35)).status_code, 200)
        response = self.client.post(f"/api/local-retouch/sessions/{session_id}/save", json={})
        self.assertEqual(response.status_code, 409)
        self.assertFalse((self.formal / "输出" / "标记修整").exists())
        self.assertEqual(len(self.shared_registry), 1)
        task = next(iter(self.shared_registry.values()))
        self.assertEqual(task["feature_key"], LOCAL_RETOUCH_FEATURE_KEY)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["result_id"], "")
        self.assertIsNone(task["result"])

    def test_registration_failure_removes_derived_file_and_never_reports_success(self):
        class RejectingRegistry(dict):
            writes = 0

            def __setitem__(self, key, value):
                self.writes += 1
                if self.writes > 1:
                    raise RuntimeError("registry unavailable")
                return super().__setitem__(key, value)

        app = FastAPI()
        registry = RejectingRegistry()
        adapter = RecordingAdapter(registry)
        register_local_retouch_routes(
            app,
            user_dirs_provider=lambda: {
                "directory_ready": True,
                "app_data_root": self.formal,
                "tmp_dir": self.tmp,
            },
            shared_task_registry=registry,
            engine=adapter,
            now_provider=lambda: 1_786_262_400.0,
        )
        with TestClient(app) as client:
            intake = client.post("/api/local-retouch/intake", files={"file": ("授权素材.png", self.source, "image/png")}).json()["data"]
            session_id = intake["session_id"]
            processed = client.post(
                f"/api/local-retouch/sessions/{session_id}/process",
                json={"mask_png_base64": mask_data_url(), "mask_revision": 1},
            )
            self.assertEqual(processed.status_code, 200, processed.text)
            self.assertEqual(client.post(f"/api/local-retouch/sessions/{session_id}/confirm", json={"mask_revision": 1}).status_code, 200)
            saved = client.post(f"/api/local-retouch/sessions/{session_id}/save", json={})
            self.assertEqual(saved.status_code, 500)
            self.assertEqual(saved.json()["detail"]["code"], "RETOUCH_RESULT_REGISTRATION_FAILED")
        output_root = self.formal / "输出" / "标记修整"
        self.assertFalse(output_root.exists() and any(output_root.iterdir()))
        self.assertEqual(len(registry), 1)
        task = next(iter(registry.values()))
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["result_id"], "")
        self.assertIsNone(task["result"])

    def test_task_registration_failure_stops_before_engine(self):
        class RejectingRegistry(dict):
            def __setitem__(self, key, value):
                raise RuntimeError("registry unavailable")

        registry = RejectingRegistry()
        adapter = RecordingAdapter(registry)
        app = FastAPI()
        register_local_retouch_routes(
            app,
            user_dirs_provider=lambda: {
                "directory_ready": True,
                "app_data_root": self.formal,
                "tmp_dir": self.tmp,
            },
            shared_task_registry=registry,
            engine=adapter,
            now_provider=lambda: 1_786_262_400.0,
        )
        with TestClient(app) as client:
            intake = client.post("/api/local-retouch/intake", files={"file": ("授权素材.png", self.source, "image/png")}).json()["data"]
            response = client.post(
                f"/api/local-retouch/sessions/{intake['session_id']}/process",
                json={"mask_png_base64": mask_data_url(), "mask_revision": 1},
            )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"]["code"], "RETOUCH_TASK_REGISTRATION_FAILED")
        self.assertEqual(adapter.calls, [])
        self.assertEqual(registry, {})


class RealLamaAdapterTests(unittest.TestCase):
    def test_real_lama_runtime_generates_decodable_same_size_png(self):
        self.assertTrue(DEFAULT_MODEL_PATH.is_file(), "formal LaMa model is required")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "中文临时目录"
            root.mkdir()
            source = root / "source.png"
            mask = root / "mask.png"
            output = root / "output.png"
            image = Image.new("RGBA", (96, 80), (80, 120, 160, 210))
            draw = ImageDraw.Draw(image)
            draw.rectangle((36, 28, 56, 48), fill=(230, 40, 30, 210))
            image.save(source)
            selected = Image.new("L", image.size, 0)
            ImageDraw.Draw(selected).rectangle((36, 28, 56, 48), fill=255)
            selected.save(mask)
            result = LamaOnnxAdapter().process(source, mask, output)
            self.assertEqual((result.engine_id, result.width, result.height, result.format), ("lama_onnx_2025jan", 96, 80, "PNG"))
            with Image.open(output) as opened:
                opened.load()
                self.assertEqual(opened.size, image.size)
                self.assertEqual(opened.getchannel("A").tobytes(), image.getchannel("A").tobytes())


if __name__ == "__main__":
    unittest.main()
