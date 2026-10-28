import base64
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2 as cv
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from backend.local_retouch_api import LOCAL_RETOUCH_FEATURE_KEY, register_local_retouch_routes
from engine.local_retouch.contracts import LocalRetouchResult
from engine.local_retouch.lama_adapter import (
    DEFAULT_MODEL_PATH,
    LamaOnnxAdapter,
    _context_box,
    _expanded_mask,
    _gradient_magnitude,
    _has_long_structure,
    _letterbox_for_model,
    _mask_expansion_radius,
    _region_plan,
)


def png_bytes(size=(96, 72), color=(45, 78, 120, 255), dpi=None):
    stream = io.BytesIO()
    options = {"dpi": dpi} if dpi is not None else {}
    Image.new("RGBA", size, color).save(stream, format="PNG", **options)
    return stream.getvalue()


def decoded_pixel_sha(value):
    data = Path(value).read_bytes() if isinstance(value, Path) else bytes(value)
    with Image.open(io.BytesIO(data)) as opened:
        rgba = opened.convert("RGBA")
        return hashlib.sha256(f"{rgba.width}x{rgba.height}:RGBA:".encode("ascii") + rgba.tobytes()).hexdigest()


def decoded_alpha_sha(value):
    data = Path(value).read_bytes() if isinstance(value, Path) else bytes(value)
    with Image.open(io.BytesIO(data)) as opened:
        opened.load()
        return hashlib.sha256(opened.convert("RGBA").getchannel("A").tobytes()).hexdigest()


def decoded_dpi(value):
    data = Path(value).read_bytes() if isinstance(value, Path) else bytes(value)
    with Image.open(io.BytesIO(data)) as opened:
        opened.load()
        dpi = opened.info.get("dpi")
        return tuple(round(float(item), 6) for item in dpi) if isinstance(dpi, tuple) else None


def mask_data_url(size=(96, 72), box=(30, 20, 50, 40)):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle(box, fill=255)
    stream = io.BytesIO()
    mask.save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def rgba_mask_data_url(alpha):
    alpha = np.asarray(alpha, dtype=np.uint8)
    rgba = np.zeros((*alpha.shape, 4), dtype=np.uint8)
    rgba[:, :, :3][alpha > 0] = 255
    rgba[:, :, 3] = alpha
    stream = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def gradient_background(size):
    width, height = size
    yy, xx = np.indices((height, width), dtype=np.float32)
    channels = (
        48.0 + xx * 0.16 + yy * 0.035,
        82.0 + xx * 0.055 + yy * 0.16,
        132.0 + xx * 0.095 + yy * 0.065,
    )
    return np.clip(np.stack(channels, axis=2), 0, 255).astype(np.uint8)


def overlay_mark(source, opacity, color):
    alpha = np.clip(opacity.astype(np.float32) / 255.0, 0.0, 1.0)[:, :, None]
    marked = source.astype(np.float32) * (1.0 - alpha) + np.asarray(color, dtype=np.float32) * alpha
    return np.clip(np.rint(marked), 0, 255).astype(np.uint8)


def save_bgr(path, image):
    Image.fromarray(cv.cvtColor(image, cv.COLOR_BGR2RGB)).save(path, format="PNG")


def load_bgr(path):
    with Image.open(path) as opened:
        opened.load()
        return cv.cvtColor(np.asarray(opened.convert("RGB")), cv.COLOR_RGB2BGR)


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
        self.state = register_local_retouch_routes(
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

    def create_formal_result(self, revision=1, box=(12, 12, 24, 24)):
        intake = self.intake()
        session_id = intake["session_id"]
        processed = self.process(session_id, revision, box).json()["data"]
        confirmed = self.client.post(
            f"/api/local-retouch/sessions/{session_id}/confirm",
            json={"mask_revision": processed["mask_revision"]},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        saved = self.client.post(f"/api/local-retouch/sessions/{session_id}/save", json={})
        self.assertEqual(saved.status_code, 200, saved.text)
        return session_id, processed, saved.json()["data"]

    def resume_authority(self, task_id, result_id, *, client=None):
        response = (client or self.client).get(
            "/api/local-retouch/resume-authority",
            params={"task_id": task_id, "result_id": result_id},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def run_real_api_retouch(self, source):
        registry = {}
        runtime_events = []
        app = FastAPI()
        state = register_local_retouch_routes(
            app,
            user_dirs_provider=lambda: {
                "directory_ready": True,
                "app_data_root": self.formal,
                "tmp_dir": self.tmp,
            },
            shared_task_registry=registry,
            now_provider=lambda: 1_786_262_400.0,
            runtime_event_logger=lambda event, **fields: runtime_events.append({"event": event, **fields}),
        )
        with TestClient(app) as client:
            intake_response = client.post(
                "/api/local-retouch/intake",
                files={"file": ("DPI证据.png", source, "image/png")},
            )
            self.assertEqual(intake_response.status_code, 200, intake_response.text)
            intake = intake_response.json()["data"]
            session_id = intake["session_id"]
            intake_working_path = Path(state["sessions"][session_id]["working_path"])
            intake_working_dpi = decoded_dpi(intake_working_path)
            process_response = client.post(
                f"/api/local-retouch/sessions/{session_id}/process",
                json={"mask_png_base64": mask_data_url(), "mask_revision": 1},
            )
            self.assertEqual(process_response.status_code, 200, process_response.text)
            processed = process_response.json()["data"]
            working_path = Path(state["sessions"][session_id]["working_path"])
            working_pixel_sha = decoded_pixel_sha(working_path)
            working_alpha_sha = decoded_alpha_sha(working_path)
            working_dpi = decoded_dpi(working_path)
            confirm_response = client.post(
                f"/api/local-retouch/sessions/{session_id}/confirm",
                json={"mask_revision": processed["mask_revision"]},
            )
            self.assertEqual(confirm_response.status_code, 200, confirm_response.text)
            save_response = client.post(f"/api/local-retouch/sessions/{session_id}/save", json={})
            self.assertEqual(save_response.status_code, 200, save_response.text)
            saved = save_response.json()["data"]
            output_response = client.get(saved["output_url"])
            self.assertEqual(output_response.status_code, 200, output_response.text)

        record = registry[saved["task_id"]]
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["result_id"], saved["result_id"])
        self.assertEqual(record["result"]["task_id"], saved["task_id"])
        self.assertEqual(hashlib.sha256(Path(state["sessions"][session_id]["upload_path"]).read_bytes()).hexdigest(), hashlib.sha256(source).hexdigest())
        self.assertEqual(decoded_pixel_sha(output_response.content), working_pixel_sha)
        self.assertEqual(decoded_alpha_sha(output_response.content), working_alpha_sha)
        metadata = record["output_metadata"]
        self.assertTrue(metadata["written"])
        self.assertTrue(metadata["decoded_pixel_content_unchanged"])
        self.assertTrue(metadata["alpha_unchanged"])
        self.assertTrue(metadata["dpi_unchanged"])
        return {
            "intake_working_dpi": intake_working_dpi,
            "working_dpi": working_dpi,
            "output_dpi": decoded_dpi(output_response.content),
        }

    def test_real_api_preserves_rgba_png_nondefault_dpi_through_formal_save(self):
        source = png_bytes(color=(45, 78, 120, 173), dpi=(143, 117))
        source_dpi = decoded_dpi(source)
        facts = self.run_real_api_retouch(source)
        self.assertEqual(facts["intake_working_dpi"], source_dpi)
        self.assertEqual(facts["working_dpi"], source_dpi)
        self.assertEqual(facts["output_dpi"], source_dpi)

    def test_real_api_rgba_png_without_dpi_does_not_invent_dpi(self):
        source = png_bytes(color=(45, 78, 120, 173))
        self.assertIsNone(decoded_dpi(source))
        facts = self.run_real_api_retouch(source)
        self.assertIsNone(facts["intake_working_dpi"])
        self.assertIsNone(facts["working_dpi"])
        self.assertIsNone(facts["output_dpi"])

    def test_rgba_mask_uses_alpha_for_antialias_erase_rectangle_and_mixed_regions(self):
        height, width = 72, 96

        hard_rectangle = np.zeros((height, width), dtype=np.uint8)
        hard_rectangle[10:31, 12:41] = 255

        antialiased_stroke = np.zeros((height, width), dtype=np.uint8)
        cv.line(antialiased_stroke, (16, 24), (72, 24), 255, 9, lineType=cv.LINE_AA)

        erased_stroke = antialiased_stroke.copy()
        erase_alpha = np.zeros_like(erased_stroke)
        cv.line(erase_alpha, (44, 14), (44, 34), 255, 7, lineType=cv.LINE_AA)
        erased_stroke = np.rint(
            erased_stroke.astype(np.float32) * (1.0 - erase_alpha.astype(np.float32) / 255.0)
        ).astype(np.uint8)

        mixed = np.maximum(hard_rectangle, antialiased_stroke)
        mixed = np.rint(
            mixed.astype(np.float32) * (1.0 - erase_alpha.astype(np.float32) / 255.0)
        ).astype(np.uint8)

        for name, alpha in (
            ("hard_rectangle", hard_rectangle),
            ("antialiased_stroke", antialiased_stroke),
            ("destination_out_erase", erased_stroke),
            ("rectangle_brush_erase", mixed),
        ):
            with self.subTest(name=name):
                intake = self.intake()
                response = self.client.post(
                    f"/api/local-retouch/sessions/{intake['session_id']}/process",
                    json={"mask_png_base64": rgba_mask_data_url(alpha), "mask_revision": 1},
                )
                self.assertEqual(response.status_code, 200, response.text)
                mask_path = self.engine.calls[-1][1]
                with Image.open(mask_path) as opened:
                    backend_mask = np.asarray(opened.convert("L")) >= 128
                frontend_mask = alpha >= 128
                self.assertEqual(int(np.count_nonzero(backend_mask ^ frontend_mask)), 0)
                self.assertEqual(int(np.count_nonzero(backend_mask)), int(np.count_nonzero(frontend_mask)))
                backend_y, backend_x = np.where(backend_mask)
                frontend_y, frontend_x = np.where(frontend_mask)
                self.assertEqual(
                    (int(backend_x.min()), int(backend_y.min()), int(backend_x.max()), int(backend_y.max())),
                    (int(frontend_x.min()), int(frontend_y.min()), int(frontend_x.max()), int(frontend_y.max())),
                )

    def test_three_passes_advance_lossless_working_result_then_save_only_latest(self):
        existing_record = {
            "task_id": "existing_formal_task",
            "feature_key": "color_correction",
            "result_id": "existing_formal_result",
            "result": {"result_id": "existing_formal_result"},
            "status": "completed",
        }
        existing_snapshot = {**existing_record, "result": dict(existing_record["result"])}
        self.shared_registry[existing_record["task_id"]] = existing_record
        intake = self.intake()
        session_id = intake["session_id"]
        self.assertEqual(intake["working_revision"], 0)
        self.assertIsNone(intake["previous_working_revision"])
        first = self.process(session_id, 1, (15, 15, 28, 28))
        self.assertEqual(first.status_code, 200, first.text)
        first_payload = first.json()["data"]
        first_task_id = first_payload["task_id"]
        self.assertEqual(first_payload["feature_key"], LOCAL_RETOUCH_FEATURE_KEY)
        self.assertTrue(first_task_id.startswith("retouch_task_"))
        self.assertEqual(first_payload["result_id"], "")
        self.assertEqual(first_payload["working_revision"], 1)
        self.assertEqual(first_payload["previous_working_revision"], 0)

        second = self.process(session_id, 2, (55, 34, 70, 50))
        self.assertEqual(second.status_code, 200, second.text)
        second_payload = second.json()["data"]
        second_task_id = second_payload["task_id"]
        self.assertNotEqual(first_task_id, second_task_id)
        self.assertEqual(second_payload["result_id"], "")
        self.assertEqual(second_payload["working_revision"], 2)
        self.assertEqual(second_payload["previous_working_revision"], 1)

        third = self.process(session_id, 3, (74, 8, 88, 20))
        self.assertEqual(third.status_code, 200, third.text)
        third_payload = third.json()["data"]
        third_task_id = third_payload["task_id"]
        self.assertEqual(third_payload["working_revision"], 3)
        self.assertEqual(third_payload["previous_working_revision"], 2)
        self.assertTrue(third_payload["previous_result_url"])
        self.assertEqual(third_payload["result_id"], "")
        self.assertEqual(len(self.engine.calls), 3)
        self.assertEqual(len(self.engine.registry_snapshots), 3)
        for task_id, snapshot in zip((first_task_id, second_task_id, third_task_id), self.engine.registry_snapshots, strict=True):
            task_before_engine = next(record for record in snapshot if record["task_id"] == task_id)
            self.assertEqual(task_before_engine["feature_key"], LOCAL_RETOUCH_FEATURE_KEY)
            self.assertEqual(task_before_engine["status"], "processing")
            self.assertFalse(task_before_engine["result_id"])
            self.assertIsNone(task_before_engine["result"])
        self.assertEqual([call[0].name for call in self.engine.calls], ["working_source.png", "working_v0001.png", "working_v0002.png"])
        self.assertEqual(self.engine.calls[1][2], first_payload["working_sha256"])
        self.assertEqual(self.engine.calls[2][2], second_payload["working_sha256"])
        self.assertNotEqual(self.engine.calls[0][2], self.engine.calls[1][2])
        self.assertNotEqual(self.engine.calls[1][2], self.engine.calls[2][2])
        self.assertEqual(third_payload["retry_source"], "working_source")

        original = self.client.get(third_payload["source_url"])
        current = self.client.get(third_payload["working_source_url"])
        previous = self.client.get(third_payload["previous_result_url"])
        self.assertEqual((original.status_code, current.status_code, previous.status_code), (200, 200, 200))
        self.assertEqual(original.content, self.source)
        self.assertEqual(hashlib.sha256(original.content).hexdigest(), hashlib.sha256(self.source).hexdigest())
        self.assertEqual(hashlib.sha256(current.content).hexdigest(), third_payload["working_sha256"])
        self.assertNotEqual(hashlib.sha256(original.content).hexdigest(), third_payload["working_sha256"])
        self.assertEqual(hashlib.sha256(previous.content).hexdigest(), second_payload["working_sha256"])
        with Image.open(io.BytesIO(current.content)) as opened:
            opened.load()
            self.assertEqual((opened.size, opened.format), ((96, 72), "PNG"))
            self.assertEqual(opened.getpixel((20, 20)), (180, 130, 70, 255))
            self.assertEqual(opened.getpixel((60, 40)), (180, 130, 70, 255))
            self.assertEqual(opened.getpixel((80, 14)), (180, 130, 70, 255))
            self.assertEqual(opened.getpixel((4, 4)), (45, 78, 120, 255))

        output_root = self.formal / "输出" / "瑕疵修复"
        self.assertFalse(output_root.exists())
        local_records = [record for record in self.shared_registry.values() if record.get("feature_key") == LOCAL_RETOUCH_FEATURE_KEY]
        self.assertEqual(len(local_records), 3)
        self.assertTrue(all(not record.get("result_id") for record in local_records))
        self.assertTrue(all(record.get("result") is None for record in local_records))
        self.assertEqual(self.shared_registry[existing_record["task_id"]], existing_snapshot)

        stale = self.client.post(f"/api/local-retouch/sessions/{session_id}/confirm", json={"mask_revision": 2})
        self.assertEqual(stale.status_code, 409)
        confirmed = self.client.post(f"/api/local-retouch/sessions/{session_id}/confirm", json={"mask_revision": 3})
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.json()["data"]["result_id"], "")
        self.assertEqual(self.shared_registry[third_task_id]["result_id"], "")
        self.assertIsNone(self.shared_registry[third_task_id]["result"])
        saved = self.client.post(f"/api/local-retouch/sessions/{session_id}/save", json={})
        self.assertEqual(saved.status_code, 200, saved.text)
        payload = saved.json()["data"]
        self.assertTrue(payload["saved"])
        self.assertTrue(payload["result_id"].startswith("retouch_result_"))
        self.assertEqual(payload["task_id"], third_task_id)
        self.assertEqual(payload["feature_key"], LOCAL_RETOUCH_FEATURE_KEY)
        self.assertNotEqual(payload["task_id"], payload["result_id"])
        output = self.formal / "输出" / "瑕疵修复" / payload["output_file_name"]
        self.assertIn("_影界修复_", payload["output_file_name"])
        self.assertTrue(output.is_file())
        working_path = Path(self.shared_registry[third_task_id]["preview_path"])
        self.assertEqual(decoded_pixel_sha(output), decoded_pixel_sha(working_path))
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
        self.assertEqual(record["result"]["source_preview_url"], payload["source_url"])
        original_preview = self.client.get(record["result"]["source_preview_url"])
        formal_result = self.client.get(payload["output_url"])
        self.assertEqual((original_preview.status_code, formal_result.status_code), (200, 200))
        self.assertEqual(hashlib.sha256(original_preview.content).hexdigest(), hashlib.sha256(self.source).hexdigest())
        self.assertEqual(decoded_pixel_sha(formal_result.content), decoded_pixel_sha(working_path))
        self.assertNotEqual(
            hashlib.sha256(original_preview.content).hexdigest(),
            hashlib.sha256(formal_result.content).hexdigest(),
        )
        self.assertEqual(self.shared_registry[first_task_id]["result_id"], "")
        self.assertEqual(self.shared_registry[first_task_id]["processing_stage"], "preview_superseded")
        self.assertIsNone(self.shared_registry[first_task_id]["preview_path"])
        self.assertEqual(self.shared_registry[second_task_id]["processing_stage"], "preview_superseded")
        self.assertIsNone(self.shared_registry[second_task_id]["preview_path"])

        repeated = self.client.post(f"/api/local-retouch/sessions/{session_id}/save", json={})
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["data"]["result_id"], payload["result_id"])
        output_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
        blocked_after_save = self.process(session_id, 4, (4, 52, 16, 66))
        self.assertEqual(blocked_after_save.status_code, 409)
        self.assertEqual(blocked_after_save.json()["detail"]["code"], "RETOUCH_FORMAL_RESULT_LOCKED")
        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), output_sha256)
        self.assertEqual(len(self.shared_registry), 4)
        self.assertEqual(self.shared_registry[existing_record["task_id"]], existing_snapshot)
        event_names = [event["event"] for event in self.runtime_events]
        for required in ("TASK_CREATED", "PROCESS_STARTED", "PROCESS_SUCCEEDED", "USER_CONFIRMED", "RESULT_REGISTERED"):
            self.assertIn(required, event_names)
        registered = next(event for event in self.runtime_events if event["event"] == "RESULT_REGISTERED")
        self.assertEqual(registered["feature_key"], LOCAL_RETOUCH_FEATURE_KEY)
        self.assertEqual(registered["task_id"], third_task_id)
        self.assertEqual(registered["result_id"], payload["result_id"])

    def test_formal_result_can_resume_same_workbench_and_register_next_result(self):
        intake = self.intake()
        session_id = intake["session_id"]
        source_hash = hashlib.sha256(self.source).hexdigest()

        first = self.process(session_id, 1, (12, 12, 24, 24)).json()["data"]
        second = self.process(session_id, 2, (34, 20, 48, 34)).json()["data"]
        third = self.process(session_id, 3, (58, 32, 72, 46)).json()["data"]
        self.assertEqual([first["result_id"], second["result_id"], third["result_id"]], ["", "", ""])

        self.assertEqual(
            self.client.post(
                f"/api/local-retouch/sessions/{session_id}/confirm",
                json={"mask_revision": third["mask_revision"]},
            ).status_code,
            200,
        )
        first_formal = self.client.post(f"/api/local-retouch/sessions/{session_id}/save", json={}).json()["data"]
        first_result_id = first_formal["result_id"]
        first_task_id = first_formal["task_id"]
        first_output = self.formal / "输出" / "瑕疵修复" / first_formal["output_file_name"]
        first_output_hash = hashlib.sha256(first_output.read_bytes()).hexdigest()
        first_original_preview = self.client.get(first_formal["source_url"])
        self.assertEqual(first_original_preview.status_code, 200)
        self.assertEqual(hashlib.sha256(first_original_preview.content).hexdigest(), source_hash)

        authority = self.resume_authority(first_task_id, first_result_id)
        self.assertTrue(authority["available"])
        self.assertEqual(authority["status"], "AVAILABLE")
        self.assertEqual(authority["session_id"], session_id)

        prepared_response = self.client.post(
            f"/api/local-retouch/sessions/{session_id}/resume-adjustment",
            json={"result_id": first_result_id},
        )
        self.assertEqual(prepared_response.status_code, 200, prepared_response.text)
        prepared = prepared_response.json()["data"]
        self.assertEqual(prepared["resume_phase"], "PREPARED")
        self.assertTrue(prepared["saved"])
        self.assertEqual(prepared["result_id"], first_result_id)
        working_asset = self.client.get(prepared["working_source_url"])
        self.assertEqual(working_asset.status_code, 200)
        self.assertEqual(hashlib.sha256(working_asset.content).hexdigest(), third["working_sha256"])

        resumed_response = self.client.post(
            f"/api/local-retouch/sessions/{session_id}/resume-adjustment/commit",
            json={"result_id": first_result_id},
        )
        self.assertEqual(resumed_response.status_code, 200, resumed_response.text)
        resumed = resumed_response.json()["data"]
        self.assertEqual(resumed["resume_phase"], "COMMITTED")
        self.assertFalse(resumed["saved"])
        self.assertEqual(resumed["result_id"], "")
        self.assertEqual(resumed["working_revision"], 3)
        self.assertEqual(resumed["working_sha256"], third["working_sha256"])
        self.assertEqual(self.shared_registry[first_task_id]["result_id"], first_result_id)
        self.assertEqual(hashlib.sha256(first_output.read_bytes()).hexdigest(), first_output_hash)
        duplicate_commit = self.client.post(
            f"/api/local-retouch/sessions/{session_id}/resume-adjustment/commit",
            json={"result_id": first_result_id},
        )
        self.assertEqual(duplicate_commit.status_code, 200, duplicate_commit.text)
        self.assertTrue(duplicate_commit.json()["data"]["resume_duplicate"])
        committed_authority = self.resume_authority(first_task_id, first_result_id)
        self.assertTrue(committed_authority["available"])
        retry_prepare = self.client.post(
            f"/api/local-retouch/sessions/{session_id}/resume-adjustment",
            json={"result_id": first_result_id},
        )
        self.assertEqual(retry_prepare.status_code, 200, retry_prepare.text)
        self.assertFalse(retry_prepare.json()["data"]["saved"])

        fourth_response = self.process(session_id, 4, (76, 8, 88, 20))
        self.assertEqual(fourth_response.status_code, 200, fourth_response.text)
        fourth = fourth_response.json()["data"]
        self.assertEqual(fourth["working_revision"], 4)
        self.assertEqual(fourth["previous_working_revision"], 3)
        self.assertEqual(fourth["result_id"], "")
        self.assertEqual(
            self.client.post(
                f"/api/local-retouch/sessions/{session_id}/confirm",
                json={"mask_revision": fourth["mask_revision"]},
            ).status_code,
            200,
        )
        second_formal = self.client.post(f"/api/local-retouch/sessions/{session_id}/save", json={}).json()["data"]
        self.assertNotEqual(second_formal["result_id"], first_result_id)
        self.assertNotEqual(second_formal["task_id"], first_task_id)
        second_original_preview = self.client.get(second_formal["source_url"])
        second_formal_result = self.client.get(second_formal["output_url"])
        self.assertEqual((second_original_preview.status_code, second_formal_result.status_code), (200, 200))
        self.assertEqual(hashlib.sha256(second_original_preview.content).hexdigest(), source_hash)
        second_working_path = Path(self.shared_registry[second_formal["task_id"]]["preview_path"])
        self.assertEqual(decoded_pixel_sha(second_formal_result.content), decoded_pixel_sha(second_working_path))
        self.assertNotEqual(
            hashlib.sha256(second_original_preview.content).hexdigest(),
            hashlib.sha256(second_formal_result.content).hexdigest(),
        )
        second_record = self.shared_registry[second_formal["task_id"]]
        self.assertEqual(second_record["result_id"], second_formal["result_id"])
        self.assertEqual(second_record["result"]["output_sha256"], hashlib.sha256(second_formal_result.content).hexdigest())
        self.assertEqual(second_record["result"]["source_sha256"], source_hash)
        formal_records = [
            record for record in self.shared_registry.values()
            if str(record.get("result_id") or "").startswith("retouch_result_")
        ]
        self.assertEqual(len(formal_records), 2)
        self.assertEqual(hashlib.sha256(first_output.read_bytes()).hexdigest(), first_output_hash)
        self.assertEqual(hashlib.sha256(self.source).hexdigest(), source_hash)
        self.assertEqual([event["event"] for event in self.runtime_events].count("RETOUCH_ADJUSTMENT_RESUMED"), 1)
        self.assertFalse(self.resume_authority(first_task_id, first_result_id)["available"])
        self.assertTrue(self.resume_authority(second_formal["task_id"], second_formal["result_id"])["available"])

    def test_resume_authority_fails_closed_for_missing_task_result_session_and_invalid_binding(self):
        session_id, _, saved = self.create_formal_result()
        task_id = saved["task_id"]
        result_id = saved["result_id"]

        self.assertEqual(self.resume_authority(task_id, "wrong_result")["status"], "INVALID_BINDING")

        record = self.shared_registry[task_id]
        record["result_id"] = ""
        self.assertEqual(self.resume_authority(task_id, result_id)["status"], "RESULT_MISSING")
        record["result_id"] = result_id

        self.state["sessions"].pop(session_id)
        self.assertEqual(self.resume_authority(task_id, result_id)["status"], "SESSION_MISSING")

        self.shared_registry.pop(task_id)
        self.assertEqual(self.resume_authority(task_id, result_id)["status"], "TASK_MISSING")

    def test_backend_restart_invalidates_stale_frontend_resume_context(self):
        _, _, saved = self.create_formal_result()
        restarted_app = FastAPI()
        register_local_retouch_routes(
            restarted_app,
            user_dirs_provider=lambda: {
                "directory_ready": True,
                "app_data_root": self.formal,
                "tmp_dir": self.tmp,
            },
            shared_task_registry=self.shared_registry,
            engine=RecordingAdapter(self.shared_registry),
            now_provider=lambda: 1_786_262_400.0,
        )
        with TestClient(restarted_app) as restarted_client:
            authority = self.resume_authority(saved["task_id"], saved["result_id"], client=restarted_client)
        self.assertFalse(authority["available"])
        self.assertEqual(authority["status"], "SESSION_MISSING")

    def test_failed_client_image_load_does_not_consume_resume_and_retry_is_safe(self):
        session_id, _, saved = self.create_formal_result()
        request = {"result_id": saved["result_id"]}
        first_prepare = self.client.post(
            f"/api/local-retouch/sessions/{session_id}/resume-adjustment",
            json=request,
        )
        self.assertEqual(first_prepare.status_code, 200, first_prepare.text)
        self.assertTrue(first_prepare.json()["data"]["saved"])
        self.assertTrue(self.resume_authority(saved["task_id"], saved["result_id"])["available"])

        retry_prepare = self.client.post(
            f"/api/local-retouch/sessions/{session_id}/resume-adjustment",
            json=request,
        )
        self.assertEqual(retry_prepare.status_code, 200, retry_prepare.text)
        self.assertTrue(retry_prepare.json()["data"]["saved"])
        self.assertNotIn("RETOUCH_ADJUSTMENT_RESUMED", [event["event"] for event in self.runtime_events])

    def test_missing_working_asset_expires_authority_without_consuming_formal_result(self):
        session_id, _, saved = self.create_formal_result()
        session = self.state["sessions"][session_id]
        Path(session["working_path"]).unlink()
        authority = self.resume_authority(saved["task_id"], saved["result_id"])
        self.assertFalse(authority["available"])
        self.assertEqual(authority["status"], "EXPIRED")
        self.assertIsNotNone(session["output"])
        self.assertEqual(self.shared_registry[saved["task_id"]]["result_id"], saved["result_id"])

    def test_task_deletion_and_invalid_session_binding_revoke_resume_authority(self):
        session_id, _, saved = self.create_formal_result()
        session = self.state["sessions"][session_id]
        session["task_id"] = "different_task"
        self.assertEqual(self.resume_authority(saved["task_id"], saved["result_id"])["status"], "INVALID_BINDING")
        session["task_id"] = saved["task_id"]
        self.shared_registry.pop(saved["task_id"])
        session["task_id"] = ""
        authority = self.resume_authority(saved["task_id"], saved["result_id"])
        self.assertFalse(authority["available"])
        self.assertEqual(authority["status"], "TASK_MISSING")

    def test_duplicate_commit_is_idempotent_while_realtime_authority_remains_valid(self):
        session_id, _, saved = self.create_formal_result()
        request = {"result_id": saved["result_id"]}
        prepared = self.client.post(
            f"/api/local-retouch/sessions/{session_id}/resume-adjustment",
            json=request,
        )
        self.assertEqual(prepared.status_code, 200, prepared.text)

        first_commit = self.client.post(
            f"/api/local-retouch/sessions/{session_id}/resume-adjustment/commit",
            json=request,
        )
        self.assertEqual(first_commit.status_code, 200, first_commit.text)
        self.assertFalse(first_commit.json()["data"]["resume_duplicate"])
        session = self.state["sessions"][session_id]
        committed_state = {
            "task_id": session["task_id"],
            "working_sha256": session["working_sha256"],
            "working_revision": session["working_revision"],
            "resume_committed_result_id": session["resume_committed_result_id"],
            "resume_committed_task_id": session["resume_committed_task_id"],
        }
        resumed_event_count = sum(event["event"] == "RETOUCH_ADJUSTMENT_RESUMED" for event in self.runtime_events)
        formal_result_count = sum(
            record.get("result_id") == saved["result_id"] for record in self.shared_registry.values()
        )
        self.assertEqual(self.resume_authority(saved["task_id"], saved["result_id"])["status"], "AVAILABLE")

        duplicate_commit = self.client.post(
            f"/api/local-retouch/sessions/{session_id}/resume-adjustment/commit",
            json=request,
        )
        self.assertEqual(duplicate_commit.status_code, 200, duplicate_commit.text)
        self.assertTrue(duplicate_commit.json()["data"]["resume_duplicate"])
        self.assertEqual(
            {
                "task_id": session["task_id"],
                "working_sha256": session["working_sha256"],
                "working_revision": session["working_revision"],
                "resume_committed_result_id": session["resume_committed_result_id"],
                "resume_committed_task_id": session["resume_committed_task_id"],
            },
            committed_state,
        )
        self.assertEqual(
            sum(event["event"] == "RETOUCH_ADJUSTMENT_RESUMED" for event in self.runtime_events),
            resumed_event_count,
        )
        self.assertEqual(
            sum(record.get("result_id") == saved["result_id"] for record in self.shared_registry.values()),
            formal_result_count,
        )

    def test_duplicate_commit_after_task_deletion_fails_closed(self):
        session_id, _, saved = self.create_formal_result()
        request = {"result_id": saved["result_id"]}
        session = self.state["sessions"][session_id]
        formal_output = Path(session["output"]["path"])
        formal_output_sha256 = hashlib.sha256(formal_output.read_bytes()).hexdigest()

        prepared = self.client.post(
            f"/api/local-retouch/sessions/{session_id}/resume-adjustment",
            json=request,
        )
        self.assertEqual(prepared.status_code, 200, prepared.text)
        first_commit = self.client.post(
            f"/api/local-retouch/sessions/{session_id}/resume-adjustment/commit",
            json=request,
        )
        self.assertEqual(first_commit.status_code, 200, first_commit.text)

        self.shared_registry.pop(saved["task_id"])
        session["task_id"] = ""
        authority = self.resume_authority(saved["task_id"], saved["result_id"])
        self.assertFalse(authority["available"])
        self.assertEqual(authority["status"], "TASK_MISSING")

        duplicate_commit = self.client.post(
            f"/api/local-retouch/sessions/{session_id}/resume-adjustment/commit",
            json=request,
        )
        self.assertEqual(duplicate_commit.status_code, 409, duplicate_commit.text)
        self.assertEqual(duplicate_commit.json()["detail"]["code"], "RETOUCH_RESUME_TASK_MISSING")
        self.assertIsNone(session["output"])
        self.assertEqual(session["resume_committed_result_id"], saved["result_id"])
        self.assertTrue(formal_output.is_file())
        self.assertEqual(hashlib.sha256(formal_output.read_bytes()).hexdigest(), formal_output_sha256)

    def test_v2_to_v1_then_v1_to_v0_and_new_v1_uses_source_revision(self):
        existing_record = {
            "task_id": "protected_existing_task",
            "feature_key": "color_correction",
            "result_id": "protected_existing_result",
            "result": {"result_id": "protected_existing_result"},
            "status": "completed",
        }
        existing_snapshot = {**existing_record, "result": dict(existing_record["result"])}
        self.shared_registry[existing_record["task_id"]] = existing_record
        intake = self.intake()
        session_id = intake["session_id"]
        first = self.process(session_id, 1, (15, 15, 28, 28)).json()["data"]
        self.assertTrue(first["can_back_to_previous"])
        second = self.process(session_id, 2, (55, 34, 70, 50)).json()["data"]
        third = self.process(session_id, 3, (74, 8, 88, 20)).json()["data"]
        self.assertTrue(third["can_back_to_previous"])

        session = self.state["sessions"][session_id]
        session["processing"] = True
        blocked_process = self.process(session_id, 4, (6, 52, 18, 64))
        blocked_back = self.client.post(f"/api/local-retouch/sessions/{session_id}/back-to-previous", json={})
        self.assertEqual(blocked_process.status_code, 409)
        self.assertEqual(blocked_process.json()["detail"]["code"], "RETOUCH_PROCESSING")
        self.assertEqual(blocked_back.status_code, 409)
        self.assertEqual(blocked_back.json()["detail"]["code"], "RETOUCH_PROCESSING")
        session["processing"] = False

        back_to_second = self.client.post(f"/api/local-retouch/sessions/{session_id}/back-to-previous", json={})
        self.assertEqual(back_to_second.status_code, 200, back_to_second.text)
        second_again = back_to_second.json()["data"]
        self.assertEqual(second_again["working_revision"], 2)
        self.assertEqual(second_again["previous_working_revision"], 1)
        self.assertEqual(second_again["working_sha256"], second["working_sha256"])
        self.assertEqual(second_again["task_id"], second["task_id"])
        self.assertTrue(second_again["can_back_to_previous"])
        self.assertFalse((Path(session["root"]) / "current_mask.png").exists())

        back_to_first = self.client.post(f"/api/local-retouch/sessions/{session_id}/back-to-previous", json={})
        self.assertEqual(back_to_first.status_code, 200, back_to_first.text)
        first_again = back_to_first.json()["data"]
        self.assertEqual(first_again["working_revision"], 1)
        self.assertEqual(first_again["previous_working_revision"], 0)
        self.assertEqual(first_again["working_sha256"], first["working_sha256"])
        self.assertEqual(first_again["task_id"], first["task_id"])
        self.assertTrue(first_again["can_back_to_previous"])

        task_count_before_v0 = len(self.shared_registry)
        back_to_v0 = self.client.post(f"/api/local-retouch/sessions/{session_id}/back-to-previous", json={})
        self.assertEqual(back_to_v0.status_code, 200, back_to_v0.text)
        v0 = back_to_v0.json()["data"]
        self.assertEqual(v0["working_revision"], 0)
        self.assertIsNone(v0["previous_working_revision"])
        self.assertEqual(v0["working_sha256"], intake["working_sha256"])
        self.assertEqual(v0["source_sha256"], intake["source_sha256"])
        self.assertEqual(v0["task_id"], "")
        self.assertEqual(v0["result_id"], "")
        self.assertEqual(v0["result_url"], "")
        self.assertEqual(v0["engine_id"], "")
        self.assertIsNone(v0["mask_revision"])
        self.assertFalse(v0["can_back_to_previous"])
        self.assertEqual(len(self.shared_registry), task_count_before_v0)
        source_response = self.client.get(v0["source_url"])
        self.assertEqual(source_response.status_code, 200)
        self.assertEqual(source_response.content, self.source)
        unavailable = self.client.post(f"/api/local-retouch/sessions/{session_id}/back-to-previous", json={})
        self.assertEqual(unavailable.status_code, 409)
        self.assertEqual(unavailable.json()["detail"]["code"], "RETOUCH_PREVIOUS_RESULT_UNAVAILABLE")

        continued_response = self.process(session_id, 4, (6, 52, 18, 64))
        self.assertEqual(continued_response.status_code, 200, continued_response.text)
        continued = continued_response.json()["data"]
        self.assertEqual(continued["working_revision"], 1)
        self.assertEqual(continued["previous_working_revision"], 0)
        self.assertEqual(continued["source_sha256"], intake["source_sha256"])
        self.assertEqual(self.engine.calls[-1][2], intake["working_sha256"])
        self.assertEqual(self.engine.calls[-1][0].name, "working_source.png")
        current = self.client.get(continued["working_source_url"])
        with Image.open(io.BytesIO(current.content)) as opened:
            opened.load()
            self.assertEqual((opened.size, opened.format), ((96, 72), "PNG"))
            self.assertEqual(opened.getpixel((20, 20)), (45, 78, 120, 255))
            self.assertEqual(opened.getpixel((60, 40)), (45, 78, 120, 255))
            self.assertEqual(opened.getpixel((80, 14)), (45, 78, 120, 255))
            self.assertEqual(opened.getpixel((10, 58)), (180, 130, 70, 255))

        output_root = self.formal / "输出" / "瑕疵修复"
        self.assertFalse(output_root.exists())
        local_records = [record for record in self.shared_registry.values() if record.get("feature_key") == LOCAL_RETOUCH_FEATURE_KEY]
        self.assertTrue(all(not record.get("result_id") for record in local_records))
        self.assertEqual(self.shared_registry[existing_record["task_id"]], existing_snapshot)

        confirmed = self.client.post(
            f"/api/local-retouch/sessions/{session_id}/confirm",
            json={"mask_revision": 4},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        saved = self.client.post(f"/api/local-retouch/sessions/{session_id}/save", json={})
        self.assertEqual(saved.status_code, 200, saved.text)
        saved_payload = saved.json()["data"]
        self.assertTrue(saved_payload["result_id"].startswith("retouch_result_"))
        final_path = output_root / saved_payload["output_file_name"]
        continued_working_path = Path(self.shared_registry[saved_payload["task_id"]]["preview_path"])
        self.assertEqual(decoded_pixel_sha(final_path), decoded_pixel_sha(continued_working_path))
        formal_local_records = [record for record in self.shared_registry.values() if record.get("result_id", "").startswith("retouch_result_")]
        self.assertEqual(len(formal_local_records), 1)
        locked_back = self.client.post(f"/api/local-retouch/sessions/{session_id}/back-to-previous", json={})
        self.assertEqual(locked_back.status_code, 409)
        self.assertEqual(locked_back.json()["detail"]["code"], "RETOUCH_FORMAL_RESULT_LOCKED")

    def test_failed_v1_to_v0_back_keeps_v1_stable_and_current(self):
        intake = self.intake()
        session_id = intake["session_id"]
        first = self.process(session_id, 1, (15, 15, 28, 28)).json()["data"]
        session = self.state["sessions"][session_id]
        stable_snapshot = {
            "working_path": session["working_path"],
            "working_sha256": session["working_sha256"],
            "working_revision": session["working_revision"],
            "previous_working_path": session["previous_working_path"],
            "previous_working_revision": session["previous_working_revision"],
            "task_id": session["task_id"],
            "result": dict(session["result"]),
            "history_length": len(session["working_history"]),
        }
        Path(session["working_history"][0]["path"]).unlink()

        failed = self.client.post(f"/api/local-retouch/sessions/{session_id}/back-to-previous", json={})
        self.assertEqual(failed.status_code, 409, failed.text)
        self.assertEqual(failed.json()["detail"]["code"], "RETOUCH_WORKING_RESULT_CHANGED")
        self.assertEqual(session["working_path"], stable_snapshot["working_path"])
        self.assertEqual(session["working_sha256"], stable_snapshot["working_sha256"])
        self.assertEqual(session["working_revision"], stable_snapshot["working_revision"])
        self.assertEqual(session["previous_working_path"], stable_snapshot["previous_working_path"])
        self.assertEqual(session["previous_working_revision"], stable_snapshot["previous_working_revision"])
        self.assertEqual(session["task_id"], stable_snapshot["task_id"])
        self.assertEqual(session["result"], stable_snapshot["result"])
        self.assertEqual(len(session["working_history"]), stable_snapshot["history_length"])
        current = self.client.get(first["working_source_url"])
        self.assertEqual(current.status_code, 200)
        self.assertEqual(hashlib.sha256(current.content).hexdigest(), first["working_sha256"])
        self.assertTrue((Path(session["root"]) / "current_mask.png").is_file())

    def test_save_before_confirmation_is_blocked_without_output(self):
        intake = self.intake()
        session_id = intake["session_id"]
        self.assertEqual(self.process(session_id, 1, (20, 20, 35, 35)).status_code, 200)
        response = self.client.post(f"/api/local-retouch/sessions/{session_id}/save", json={})
        self.assertEqual(response.status_code, 409)
        self.assertFalse((self.formal / "输出" / "瑕疵修复").exists())
        self.assertEqual(len(self.shared_registry), 1)
        task = next(iter(self.shared_registry.values()))
        self.assertEqual(task["feature_key"], LOCAL_RETOUCH_FEATURE_KEY)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["result_id"], "")
        self.assertIsNone(task["result"])

    def test_failed_third_pass_keeps_v2_current_and_preserves_failed_mask(self):
        class FailingThirdAdapter(RecordingAdapter):
            def process(self, source_path, mask_path, output_path):
                if len(self.calls) == 2:
                    source_path = Path(source_path)
                    self.calls.append((source_path, Path(mask_path), hashlib.sha256(source_path.read_bytes()).hexdigest()))
                    raise RuntimeError("intentional third-pass failure")
                return super().process(source_path, mask_path, output_path)

        registry = {}
        adapter = FailingThirdAdapter(registry)
        app = FastAPI()
        state = register_local_retouch_routes(
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
            intake = client.post(
                "/api/local-retouch/intake",
                files={"file": ("授权素材.png", self.source, "image/png")},
            ).json()["data"]
            session_id = intake["session_id"]
            first = client.post(
                f"/api/local-retouch/sessions/{session_id}/process",
                json={"mask_png_base64": mask_data_url(box=(15, 15, 28, 28)), "mask_revision": 1},
            ).json()["data"]
            second = client.post(
                f"/api/local-retouch/sessions/{session_id}/process",
                json={"mask_png_base64": mask_data_url(box=(55, 34, 70, 50)), "mask_revision": 2},
            ).json()["data"]
            failed = client.post(
                f"/api/local-retouch/sessions/{session_id}/process",
                json={"mask_png_base64": mask_data_url(box=(74, 8, 88, 20)), "mask_revision": 3},
            )
            self.assertEqual(failed.status_code, 500)
            self.assertEqual(failed.json()["detail"]["code"], "RETOUCH_ENGINE_FAILED")
            current = client.get(second["working_source_url"])
            previous = client.get(second["previous_result_url"])

        session = state["sessions"][session_id]
        self.assertEqual(session["working_revision"], 2)
        self.assertEqual(session["previous_working_revision"], 1)
        self.assertEqual(session["task_id"], second["task_id"])
        self.assertEqual(session["working_sha256"], second["working_sha256"])
        self.assertEqual(hashlib.sha256(current.content).hexdigest(), second["working_sha256"])
        self.assertEqual(hashlib.sha256(previous.content).hexdigest(), first["working_sha256"])
        self.assertTrue((Path(session["root"]) / "current_mask.png").is_file())
        self.assertFalse(any(Path(session["root"]).glob(".candidate_*.png")))
        self.assertEqual(len(session["working_history"]), 3)
        failed_tasks = [record for record in registry.values() if record["status"] == "failed"]
        self.assertEqual(len(failed_tasks), 1)
        self.assertTrue(all(not record.get("result_id") for record in registry.values()))
        self.assertFalse((self.formal / "输出" / "瑕疵修复").exists())

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
        output_root = self.formal / "输出" / "瑕疵修复"
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
    def test_region_plan_selects_local_multi_local_and_full_routes(self):
        local = np.zeros((800, 1200), dtype=np.uint8)
        cv.rectangle(local, (100, 120), (132, 150), 255, -1)
        local_route, local_boxes = _region_plan(local)

        multi = local.copy()
        cv.rectangle(multi, (1020, 660), (1052, 690), 255, -1)
        multi_route, multi_boxes = _region_plan(multi)

        full = np.full((300, 400), 255, dtype=np.uint8)
        full_route, full_boxes = _region_plan(full)

        self.assertEqual((local_route, len(local_boxes)), ("LOCAL", 1))
        self.assertEqual((multi_route, len(multi_boxes)), ("MULTI_LOCAL", 2))
        self.assertEqual((full_route, full_boxes), ("FULL", [(0, 0, 400, 300)]))

    def test_small_selection_uses_bounded_four_pixel_expansion(self):
        mask = np.zeros((821, 1915), dtype=np.uint8)
        cv.rectangle(mask, (348, 14), (396, 30), 255, -1)
        self.assertEqual(_mask_expansion_radius(mask), 4)

    def test_neural_candidate_keeps_user_mask_as_model_input(self):
        class RecordingSession:
            def __init__(self):
                self.mask_blob = None

            def run(self, _outputs, inputs):
                self.mask_blob = inputs["mask"].copy()
                return [inputs["image"] * 255.0]

        yy, xx = np.indices((180, 220), dtype=np.uint8)
        source_image = np.stack((70 + xx // 3, 95 + yy // 4, 120 + xx // 5), axis=2).astype(np.uint8)
        user_mask = np.zeros(source_image.shape[:2], dtype=np.uint8)
        cv.rectangle(user_mask, (98, 72), (117, 105), 255, -1)
        expanded_mask, _ = _expanded_mask(user_mask)
        x1, y1, x2, y2 = _context_box(expanded_mask)
        patch_image = source_image[y1:y2, x1:x2]
        _, expected_model_mask, _ = _letterbox_for_model(
            patch_image,
            user_mask[y1:y2, x1:x2],
        )
        _, expanded_model_mask, _ = _letterbox_for_model(
            patch_image,
            expanded_mask[y1:y2, x1:x2],
        )
        self.assertGreater(int(np.count_nonzero(expanded_model_mask)), int(np.count_nonzero(expected_model_mask)))

        recording_session = RecordingSession()
        adapter = LamaOnnxAdapter()
        adapter._session = recording_session
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "source.png"
            mask_path = root / "mask.png"
            output_path = root / "output.png"
            save_bgr(source_path, source_image)
            Image.fromarray(user_mask).save(mask_path, format="PNG")
            with (
                patch.object(adapter, "availability", return_value={"available": True}),
                patch(
                    "engine.local_retouch.lama_adapter._simple_background_surface",
                    return_value=(None, 0.0, None),
                ),
            ):
                adapter.process(source_path, mask_path, output_path)

        self.assertIsNotNone(recording_session.mask_blob)
        actual_model_mask = recording_session.mask_blob[0, 0] > 0
        self.assertTrue(np.array_equal(actual_model_mask, expected_model_mask > 0))
        self.assertFalse(np.array_equal(actual_model_mask, expanded_model_mask > 0))

    def test_real_lama_edge_rectangle_preserves_exact_rgb_and_alpha_outside_user_mask(self):
        self.assertTrue(DEFAULT_MODEL_PATH.is_file(), "formal LaMa model is required")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "中文临时目录"
            root.mkdir()
            source = root / "source.png"
            mask = root / "mask.png"
            output = root / "output.png"
            image = Image.new("RGBA", (96, 80), (80, 120, 160, 210))
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 4, 20, 28), fill=(230, 40, 30, 210))
            image.save(source)
            selected = Image.new("L", image.size, 0)
            ImageDraw.Draw(selected).rectangle((0, 4, 20, 28), fill=255)
            selected.save(mask)
            source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
            result = LamaOnnxAdapter().process(source, mask, output)
            self.assertEqual((result.engine_id, result.width, result.height, result.format), ("lama_onnx_2025jan", 96, 80, "PNG"))
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_sha256)
            with Image.open(output) as opened:
                opened.load()
                self.assertEqual(opened.size, image.size)
                self.assertEqual(opened.getchannel("A").tobytes(), image.getchannel("A").tobytes())
                source_rgba = np.asarray(image)
                output_rgba = np.asarray(opened.convert("RGBA"))
                outside = np.asarray(selected) < 128
                rgb_diff = np.abs(output_rgba[:, :, :3].astype(np.int16) - source_rgba[:, :, :3].astype(np.int16))
                alpha_diff = np.abs(output_rgba[:, :, 3].astype(np.int16) - source_rgba[:, :, 3].astype(np.int16))
                self.assertEqual(int(np.count_nonzero(np.any(rgb_diff > 0, axis=2) & outside)), 0)
                self.assertEqual(int(rgb_diff[outside].max()), 0)
                self.assertEqual(int(alpha_diff[outside].max()), 0)

    def test_three_real_lama_passes_preserve_pixels_outside_each_new_user_mask(self):
        adapter = LamaOnnxAdapter()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "continuous_retouch"
            root.mkdir()
            clean = gradient_background((192, 128))
            source_image = clean.copy()
            defects = ((28, 30), (92, 66), (154, 32))
            masks = []
            for x, y in defects:
                cv.circle(source_image, (x, y), 7, (238, 240, 244), -1, cv.LINE_AA)
                mask = np.zeros(source_image.shape[:2], dtype=np.uint8)
                cv.circle(mask, (x, y), 8, 255, -1, cv.LINE_AA)
                masks.append(mask)

            original = root / "original.png"
            save_bgr(original, source_image)
            original_sha256 = hashlib.sha256(original.read_bytes()).hexdigest()
            current = original
            outputs = []
            input_hashes = []
            for revision, mask in enumerate(masks, start=1):
                mask_path = root / f"mask_{revision}.png"
                output_path = root / f"working_v{revision:04d}.png"
                Image.fromarray(mask).save(mask_path, format="PNG")
                expected_input_sha256 = hashlib.sha256(current.read_bytes()).hexdigest()
                processed = adapter.process(current, mask_path, output_path)
                self.assertEqual(processed.source_sha256, expected_input_sha256)
                self.assertEqual((processed.width, processed.height, processed.format), (192, 128, "PNG"))
                input_hashes.append(processed.source_sha256)
                outputs.append(load_bgr(output_path))
                current = output_path

            self.assertEqual(input_hashes[1], hashlib.sha256((root / "working_v0001.png").read_bytes()).hexdigest())
            self.assertEqual(input_hashes[2], hashlib.sha256((root / "working_v0002.png").read_bytes()).hexdigest())
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), original_sha256)

            inputs = [source_image, outputs[0], outputs[1]]
            for source_revision, output_revision, user_mask in zip(inputs, outputs, masks, strict=True):
                outside = user_mask < 128
                diff = np.abs(output_revision.astype(np.int16) - source_revision.astype(np.int16))
                self.assertEqual(int(np.count_nonzero(np.any(diff > 0, axis=2) & outside)), 0)
                self.assertEqual(int(diff[outside].max()), 0)

            first_region = cv.dilate(masks[0], cv.getStructuringElement(cv.MORPH_ELLIPSE, (21, 21))) > 0
            self.assertTrue(np.array_equal(outputs[0][first_region], outputs[1][first_region]))
            self.assertTrue(np.array_equal(outputs[1][first_region], outputs[2][first_region]))

    def test_small_roi_crossing_line_repairs_target_and_preserves_structure(self):
        clean = np.full((256, 256, 3), 200, dtype=np.uint8)
        cv.line(clean, (20, 128), (236, 128), (35, 35, 35), 2, cv.LINE_8)
        source = clean.copy()
        cv.circle(source, (128, 128), 5, (245, 245, 245), -1, cv.LINE_8)
        mask = np.zeros(source.shape[:2], dtype=np.uint8)
        cv.rectangle(mask, (112, 120), (144, 136), 255, -1)

        model_mask, _ = _expanded_mask(mask)
        x1, y1, x2, y2 = _context_box(model_mask)
        patch = source[y1:y2, x1:x2]
        patch_mask = model_mask[y1:y2, x1:x2]
        self.assertTrue(_has_long_structure(patch, patch_mask))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "small_crossing_line.png"
            mask_path = root / "small_crossing_line_mask.png"
            output_path = root / "small_crossing_line_output.png"
            save_bgr(source_path, source)
            Image.fromarray(mask).save(mask_path, format="PNG")
            source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
            result = LamaOnnxAdapter().process(source_path, mask_path, output_path)
            output = load_bgr(output_path)
            source_sha256_after = hashlib.sha256(source_path.read_bytes()).hexdigest()

        self.assertGreater(result.inference_seconds, 0.0)
        self.assertEqual(source_sha256_after, source_sha256)
        outside = mask == 0
        difference = np.abs(output.astype(np.int16) - source.astype(np.int16))
        self.assertEqual(int(np.count_nonzero(np.any(difference > 0, axis=2) & outside)), 0)
        self.assertEqual(int(difference[outside].max()), 0)

        yy, xx = np.indices(mask.shape)
        line = (yy == 128) & (mask > 0)
        lost_line_pixels = int(np.count_nonzero(np.mean(output[line], axis=1) >= 140.0))
        self.assertEqual(lost_line_pixels, 0)
        self.assertLess(float(np.mean(output[line])), 100.0)

        target = ((xx - 128) ** 2 + (yy - 128) ** 2 <= 25) & (mask > 0) & (yy != 128)
        source_target_error = float(np.mean(np.abs(source.astype(np.float32) - clean)[target]))
        output_target_error = float(np.mean(np.abs(output.astype(np.float32) - clean)[target]))
        self.assertLess(output_target_error, source_target_error * 0.25)
        self.assertLess(output_target_error, 10.0)

    def test_normal_chinese_title_uses_native_surface_without_glyph_stroke_false_positive(self):
        fixture = Path("tests/fixtures/ocr_n2_01/samples/normal_chinese_title.png")
        source = load_bgr(fixture)
        mask = np.zeros(source.shape[:2], dtype=np.uint8)
        cv.line(mask, (883, 216), (950, 228), 255, 36, cv.LINE_AA)
        mask = np.where(mask >= 128, 255, 0).astype(np.uint8)
        model_mask, _ = _expanded_mask(mask)
        x1, y1, x2, y2 = _context_box(model_mask)
        patch = source[y1:y2, x1:x2]
        patch_mask = model_mask[y1:y2, x1:x2]
        self.assertFalse(_has_long_structure(patch, patch_mask))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "normal_chinese_title.png"
            mask_path = root / "mask.png"
            output_path = root / "output.png"
            save_bgr(source_path, source)
            Image.fromarray(mask).save(mask_path, format="PNG")
            source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
            result = LamaOnnxAdapter().process(source_path, mask_path, output_path)
            output = load_bgr(output_path)
            source_sha256_after = hashlib.sha256(source_path.read_bytes()).hexdigest()

        self.assertEqual(result.inference_seconds, 0.0)
        self.assertEqual(source_sha256_after, source_sha256)
        outside = mask == 0
        self.assertEqual(int(np.max(np.abs(output.astype(np.int16) - source.astype(np.int16))[outside])), 0)
        output_gradient = float(np.percentile(_gradient_magnitude(output)[mask > 0], 90))
        self.assertLess(output_gradient, 8.0, output_gradient)

    def test_large_smooth_roi_bypasses_low_resolution_model_input_at_native_resolution(self):
        clean = gradient_background((1600, 700))
        source = clean.copy()
        mask = np.zeros(clean.shape[:2], dtype=np.uint8)
        cv.rectangle(mask, (500, 250), (811, 356), 255, -1)
        cv.putText(source, "HDDE QUALITY", (520, 330), cv.FONT_HERSHEY_SIMPLEX, 1.8, (238, 240, 244), 5, cv.LINE_AA)
        model_mask, _ = _expanded_mask(mask)
        x1, y1, x2, y2 = _context_box(model_mask)
        context_width, context_height = x2 - x1, y2 - y1
        _, _, transform = _letterbox_for_model(
            source[y1:y2, x1:x2],
            model_mask[y1:y2, x1:x2],
        )
        self.assertEqual((context_width, context_height), (1344, 524))
        self.assertEqual((transform[2], transform[3]), (512, 200))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "large_source.png"
            mask_path = root / "large_mask.png"
            output_path = root / "large_output.png"
            save_bgr(source_path, source)
            Image.fromarray(mask).save(mask_path, format="PNG")
            source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
            result = LamaOnnxAdapter().process(source_path, mask_path, output_path)
            output = load_bgr(output_path)
            source_sha256_after = hashlib.sha256(source_path.read_bytes()).hexdigest()

        self.assertEqual(result.inference_seconds, 0.0)
        self.assertEqual(source_sha256_after, source_sha256)
        outside = mask == 0
        self.assertEqual(int(np.max(np.abs(output.astype(np.int16) - source.astype(np.int16))[outside])), 0)
        input_error = float(np.mean(np.abs(source.astype(np.float32) - clean)[mask > 0]))
        output_error = float(np.mean(np.abs(output.astype(np.float32) - clean)[mask > 0]))
        self.assertLess(output_error, input_error * 0.22, (input_error, output_error))
        self.assertLess(output_error, 8.0)

    def test_large_roi_contaminated_context_controls_surface_and_preserves_roi(self):
        yy, xx = np.indices((360, 900), dtype=np.float32)
        clean = np.clip(
            np.stack(
                (
                    205.0 + xx * 0.012 + yy * 0.025,
                    188.0 + xx * 0.008 + yy * 0.018,
                    166.0 + xx * 0.006 + yy * 0.014,
                ),
                axis=2,
            ),
            0,
            255,
        ).astype(np.uint8)
        source = clean.copy()
        text = np.zeros(clean.shape[:2], dtype=np.uint8)
        cv.putText(text, "HDDE DELIVERY", (138, 190), cv.FONT_HERSHEY_SIMPLEX, 2.0, 255, 6, cv.LINE_AA)
        source = overlay_mark(source, text, (238, 240, 244))
        mask = np.zeros(clean.shape[:2], dtype=np.uint8)
        cv.rectangle(mask, (70, 90), (830, 240), 255, -1)
        cv.ellipse(source, (450, 315), (82, 60), 0, 180, 360, (34, 38, 46), -1, cv.LINE_AA)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "large_contaminated_source.png"
            mask_path = root / "large_contaminated_mask.png"
            output_path = root / "large_contaminated_output.png"
            save_bgr(source_path, source)
            Image.fromarray(mask).save(mask_path, format="PNG")
            source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
            result = LamaOnnxAdapter().process(source_path, mask_path, output_path)
            output = load_bgr(output_path)
            source_sha256_after = hashlib.sha256(source_path.read_bytes()).hexdigest()

        self.assertEqual(result.inference_seconds, 0.0)
        self.assertEqual(source_sha256_after, source_sha256)
        difference = np.abs(output.astype(np.int16) - source.astype(np.int16))
        outside = mask == 0
        self.assertEqual(int(np.count_nonzero(np.any(difference > 0, axis=2) & outside)), 0)
        self.assertEqual(int(difference[outside].max()), 0)

        target = (text >= 32) & (mask > 0)
        target_error = float(np.mean(np.abs(output.astype(np.float32) - clean.astype(np.float32))[target]))
        self.assertLess(target_error, 8.0, target_error)
        repaired_error = np.abs(output.astype(np.float32) - clean.astype(np.float32))
        self.assertLess(float(np.percentile(repaired_error[mask > 0], 95)), 7.0)

        distance = cv.distanceTransform(mask, cv.DIST_L2, 5)
        background_edge = (mask > 0) & (distance <= 18.0) & (text < 32)
        edge_delta = repaired_error[background_edge]
        edge_luminance_delta = edge_delta @ np.array([0.114, 0.587, 0.299], dtype=np.float32)
        self.assertLess(float(np.percentile(np.linalg.norm(edge_delta, axis=1), 90)), 8.0)
        self.assertLess(float(np.percentile(edge_luminance_delta, 90)), 4.0)

        contaminated_side = (slice(220, 241), slice(370, 531))
        self.assertLess(float(np.mean(repaired_error[contaminated_side])), 5.0)

    def test_quality_closes_small_glow_text_large_text_gradient_and_non_target_gates(self):
        adapter = LamaOnnxAdapter()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "quality_fixtures"
            root.mkdir()

            small_clean = gradient_background((320, 220))
            small_core = np.zeros(small_clean.shape[:2], dtype=np.uint8)
            cv.putText(small_core, "HDDE", (87, 122), cv.FONT_HERSHEY_SIMPLEX, 0.82, 255, 2, cv.LINE_AA)
            small_glow = cv.GaussianBlur(small_core, (0, 0), 3.0)
            small_effect = np.maximum(small_core, np.rint(small_glow.astype(np.float32) * 0.72).astype(np.uint8))
            small_source = overlay_mark(small_clean, small_effect, (232, 235, 242))
            small_mask = np.where(small_core >= 72, 255, 0).astype(np.uint8)

            small_source_path = root / "small_source.png"
            small_mask_path = root / "small_mask.png"
            small_output_path = root / "small_output.png"
            save_bgr(small_source_path, small_source)
            Image.fromarray(small_mask).save(small_mask_path, format="PNG")
            source_sha_before = hashlib.sha256(small_source_path.read_bytes()).hexdigest()
            adapter.process(small_source_path, small_mask_path, small_output_path)
            small_output = load_bgr(small_output_path)
            self.assertEqual(hashlib.sha256(small_source_path.read_bytes()).hexdigest(), source_sha_before)

            small_target = small_mask > 0
            small_input_error = float(np.mean(np.abs(small_source.astype(np.float32) - small_clean)[small_target]))
            small_output_error = float(np.mean(np.abs(small_output.astype(np.float32) - small_clean)[small_target]))
            self.assertLess(small_output_error, small_input_error * 0.55, (small_input_error, small_output_error))
            self.assertLess(small_output_error, 9.0)
            self.assertEqual(
                int(np.max(np.abs(small_output.astype(np.int16) - small_source.astype(np.int16))[small_mask == 0])),
                0,
            )

            large_clean = gradient_background((420, 260))
            cv.rectangle(large_clean, (34, 54), (386, 210), (124, 151, 190), 2, cv.LINE_AA)
            cv.line(large_clean, (34, 133), (386, 133), (105, 135, 176), 2, cv.LINE_AA)
            large_text = np.zeros(large_clean.shape[:2], dtype=np.uint8)
            cv.putText(large_text, "SALE", (82, 166), cv.FONT_HERSHEY_SIMPLEX, 2.05, 255, 5, cv.LINE_AA)
            large_shadow = cv.GaussianBlur(large_text, (0, 0), 4.0)
            large_effect = np.maximum(large_text, np.rint(large_shadow.astype(np.float32) * 0.60).astype(np.uint8))
            large_source = overlay_mark(large_clean, large_effect, (238, 239, 242))
            large_mask = np.zeros(large_clean.shape[:2], dtype=np.uint8)
            cv.rectangle(large_mask, (74, 105), (322, 177), 255, -1)

            large_source_path = root / "large_source.png"
            large_mask_path = root / "large_mask.png"
            large_output_path = root / "large_output.png"
            save_bgr(large_source_path, large_source)
            Image.fromarray(large_mask).save(large_mask_path, format="PNG")
            adapter.process(large_source_path, large_mask_path, large_output_path)
            large_output = load_bgr(large_output_path)

            large_text_region = large_effect >= 32
            large_input_error = float(np.mean(np.abs(large_source.astype(np.float32) - large_clean)[large_text_region]))
            large_output_error = float(np.mean(np.abs(large_output.astype(np.float32) - large_clean)[large_text_region]))
            self.assertLess(large_output_error, large_input_error * 0.72, (large_input_error, large_output_error))
            repaired_area_error = float(
                np.mean(np.abs(large_output.astype(np.float32) - large_clean)[large_mask > 0])
            )
            self.assertLess(repaired_area_error, 18.0)

            line_region = np.zeros(large_mask.shape, dtype=bool)
            line_region[131:136, 92:305] = True
            line_region &= large_mask > 0
            line_error = float(np.mean(np.abs(large_output.astype(np.float32) - large_clean)[line_region]))
            self.assertLess(line_error, 34.0)

            protected = large_mask == 0
            self.assertEqual(int(np.max(np.abs(large_output.astype(np.int16) - large_source.astype(np.int16))[protected])), 0)
            with Image.open(large_output_path) as opened:
                opened.load()
                self.assertEqual((opened.size, opened.format), ((420, 260), "PNG"))


if __name__ == "__main__":
    unittest.main()
