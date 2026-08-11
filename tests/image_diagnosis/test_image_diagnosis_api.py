from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.image_diagnosis_api import register_image_diagnosis_routes
from engine.image_diagnosis import IMAGE_DIAGNOSIS_FEATURE_KEY, ImageDiagnosisEngine


def png_bytes(size=(160, 120), color=(90, 130, 170)):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return stream.getvalue()


class DictDiagnosisResult:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return self.payload


class RecordingDiagnosisEngine:
    engine_id = "recording-image-diagnosis-engine"
    adapter_id = "recording-readonly-adapter"

    def __init__(self, registry):
        self.registry = registry
        self.snapshots = []

    def diagnose(self, source_path):
        source_path = Path(source_path)
        self.snapshots.append([dict(record) for record in self.registry.values()])
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        mtime = source_path.stat().st_mtime_ns
        return DictDiagnosisResult(
            {
                "contract_version": "hdde.image-diagnosis.v1",
                "feature_key": IMAGE_DIAGNOSIS_FEATURE_KEY,
                "engine_id": self.engine_id,
                "adapter_id": self.adapter_id,
                "image_facts": {
                    "width": 160,
                    "height": 120,
                    "format": "PNG",
                    "file_size_bytes": source_path.stat().st_size,
                    "color_mode": "RGB",
                    "has_alpha": False,
                    "exif": {"present": False, "field_count": 0, "fields": {}},
                },
                "quality_issues": {
                    "resolution": {
                        "status": "detected",
                        "severity": "high",
                        "metrics": {"short_side": 120},
                        "evidence": ["短边=120px"],
                        "reason": "图片尺寸明显不足。",
                    }
                },
                "recommended_action": {
                    "primary_action": "4K高清增强",
                    "secondary_actions": [],
                    "reasons": ["分辨率明显不足且清晰度诊断同时检出模糊。"],
                },
                "source_integrity": {
                    "sha256_before": digest,
                    "sha256_after": digest,
                    "mtime_ns_before": mtime,
                    "mtime_ns_after": mtime,
                    "unchanged": True,
                },
            }
        )


class ImageDiagnosisApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.formal_root = Path(self.temporary.name) / "formal"
        self.tmp_root = self.formal_root / "临时文件"
        self.tmp_root.mkdir(parents=True)
        self.registry = {}
        self.events = []
        self.engine = RecordingDiagnosisEngine(self.registry)
        app = FastAPI()
        register_image_diagnosis_routes(
            app,
            user_dirs_provider=lambda: {
                "directory_ready": True,
                "app_data_root": self.formal_root,
                "tmp_dir": self.tmp_root,
            },
            shared_task_registry=self.registry,
            engine=self.engine,
            now_provider=lambda: 1_786_262_400.0,
            runtime_event_logger=lambda event, **fields: self.events.append({"event": event, **fields}),
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def test_task_exists_before_engine_and_structured_result_is_traceable(self):
        source = png_bytes()
        response = self.client.post(
            "/api/image-diagnosis/tasks",
            files={"file": ("诊断样本.png", source, "image/png")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        task_id = data["task_id"]
        result_id = data["result_id"]

        self.assertEqual(data["feature_key"], IMAGE_DIAGNOSIS_FEATURE_KEY)
        self.assertTrue(task_id.startswith("diagnosis_task_"))
        self.assertTrue(result_id.startswith("diagnosis_result_"))
        self.assertNotEqual(task_id, result_id)
        self.assertEqual(data["result"]["task_id"], task_id)
        self.assertEqual(data["result"]["feature_key"], IMAGE_DIAGNOSIS_FEATURE_KEY)
        self.assertNotIn("source", data["result"])
        self.assertEqual(data["result"]["recommended_action"]["primary_action"], "4K高清增强")

        before_engine = self.engine.snapshots[0][0]
        self.assertEqual(before_engine["task_id"], task_id)
        self.assertEqual(before_engine["feature_key"], IMAGE_DIAGNOSIS_FEATURE_KEY)
        self.assertEqual(before_engine["status"], "processing")
        self.assertEqual(before_engine["result_id"], "")
        self.assertIsNone(before_engine["result"])

        record = self.registry[task_id]
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["result_id"], result_id)
        self.assertNotIn("result_file", record)
        self.assertEqual(record["result"]["diagnosis_findings"]["resolution"]["status"], "detected")
        self.assertEqual(record["result"]["source"], record["source"])
        source_path = Path(record["source_path"])
        self.assertEqual(hashlib.sha256(source_path.read_bytes()).hexdigest(), hashlib.sha256(source).hexdigest())
        self.assertTrue(record["result"]["source_integrity"]["unchanged"])

        preview = self.client.get(data["source_preview_url"])
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(hashlib.sha256(preview.content).hexdigest(), hashlib.sha256(source).hexdigest())

        names = [event["event"] for event in self.events]
        for required in ("TASK_CREATED", "PROCESS_STARTED", "PROCESS_SUCCEEDED", "RESULT_REGISTERED"):
            self.assertIn(required, names)
        for event in self.events:
            self.assertEqual(event["feature_key"], IMAGE_DIAGNOSIS_FEATURE_KEY)
            self.assertEqual(event["task_id"], task_id)

    def test_real_frozen_engine_is_called_without_creating_output_copy(self):
        app = FastAPI()
        registry = {}
        register_image_diagnosis_routes(
            app,
            user_dirs_provider=lambda: {
                "directory_ready": True,
                "app_data_root": self.formal_root,
                "tmp_dir": self.tmp_root,
            },
            shared_task_registry=registry,
            engine=ImageDiagnosisEngine(),
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/image-diagnosis/tasks",
                files={"file": ("真实低分辨率样本.png", png_bytes((128, 96)), "image/png")},
            )
        self.assertEqual(response.status_code, 200, response.text)
        record = next(iter(registry.values()))
        self.assertEqual(record["result"]["engine_id"], ImageDiagnosisEngine.engine_id)
        self.assertEqual(record["result"]["feature_key"], IMAGE_DIAGNOSIS_FEATURE_KEY)
        self.assertTrue(record["result"]["diagnosis_findings"])
        self.assertTrue(record["result"]["recommended_action"]["primary_action"])
        self.assertFalse((self.formal_root / "输出").exists())


if __name__ == "__main__":
    unittest.main()
