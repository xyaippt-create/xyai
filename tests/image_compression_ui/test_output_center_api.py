import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.image_compression_api import register_image_compression_routes


class OutputCenterApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.app_root = self.root / "formal"
        self.output_root = self.app_root / "输出"
        self.tmp = self.output_root / "图片压缩" / ".运行缓存"
        self.opened = []
        self.paths = {
            "1080p": self.output_root / "1080P标准增强" / "standard.png",
            "4k": self.output_root / "4K高清增强" / "four-k.png",
            "compression": self.output_root / "图片压缩" / "PNG无损压缩" / "compressed.png",
            "color": self.output_root / "颜色校正" / "meeting_影界自动校正_20260809_120000.jpg",
            "retouch": self.output_root / "标记修整" / "poster_影界局部修整_20260810_120000.png",
        }
        colors = {
            "1080p": (30, 72, 140),
            "4k": (42, 88, 166),
            "compression": (80, 115, 150),
            "color": (135, 92, 70),
            "retouch": (92, 126, 78),
        }
        for key, path in self.paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (80 + len(key), 60), colors[key]).save(path)

        intake = self.tmp / "image-compression-intake" / "intake_exact"
        intake.mkdir(parents=True)
        self.source = intake / "meeting.jpg"
        Image.new("RGB", (85, 60), (100, 80, 70)).save(self.source)
        self.shared_registry = {
            "retouch_task_001": {
                "task_id": "retouch_task_001",
                "result_id": "retouch_result_001",
                "feature_key": "local_retouch",
                "task_family": "local_retouch",
                "processing_type": "local_retouch",
                "status": "completed",
                "source_path": self.source,
                "source": str(self.source),
                "output_path": self.paths["retouch"],
                "result_file": str(self.paths["retouch"]),
                "result": {
                    "result_id": "retouch_result_001",
                    "task_id": "retouch_task_001",
                    "feature_key": "local_retouch",
                    "source": str(self.source),
                    "result_file": str(self.paths["retouch"]),
                    "source_path": str(self.source),
                    "output_path": str(self.paths["retouch"]),
                    "status": "completed",
                },
            },
        }

        excluded = self.output_root / "4K高清增强" / "evidence" / "must-not-appear.png"
        excluded.parent.mkdir(parents=True)
        Image.new("RGB", (20, 20), (255, 0, 0)).save(excluded)
        explicit_test_output = self.output_root / "1080P标准增强" / "front_upload_test_影界高清.png"
        Image.new("RGB", (20, 20), (255, 0, 0)).save(explicit_test_output)
        explicit_sample_output = self.output_root / "颜色校正" / "sample_a_影界自动校正_20260809_120000.jpg"
        Image.new("RGB", (20, 20), (255, 0, 0)).save(explicit_sample_output)
        (self.output_root / "1080P标准增强" / "broken.png").write_bytes(b"not-an-image")

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
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def test_formal_sources_are_shallow_real_and_action_bound(self):
        response = self.client.get("/api/output-center/items")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertFalse(data["recursive_scan"])
        self.assertEqual(data["scan_scope"], "formal_contract_directories_only")
        self.assertEqual(data["count"], 5)
        self.assertEqual({item["processing_type"] for item in data["items"]}, {"1080p", "4k", "compression", "color_correction", "local_retouch"})
        serialized = response.text
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("must-not-appear", serialized)
        self.assertNotIn("front_upload_test", serialized)
        self.assertNotIn("sample_a", serialized)
        self.assertGreaterEqual(data["skipped_unavailable_count"], 1)

        color = next(item for item in data["items"] if item["processing_type"] == "color_correction")
        self.assertTrue(color["compare_available"])
        self.assertEqual(color["mapping_source"], "unique_managed_intake_match")
        self.assertTrue(color["compare_url"].startswith("/outputs/compare?item="))
        self.assertEqual(self.client.get(color["preview_url"]).status_code, 200)
        self.assertEqual(self.client.get(color["source_preview_url"]).status_code, 200)

        retouch = next(item for item in data["items"] if item["processing_type"] == "local_retouch")
        self.assertEqual(retouch["result_id"], "retouch_result_001")
        self.assertEqual(retouch["task_id"], "retouch_task_001")
        self.assertEqual(retouch["feature_key"], "local_retouch")
        self.assertTrue(retouch["unified_result"])
        self.assertTrue(retouch["delivery_eligible"])
        self.assertEqual(retouch["status"], "completed")
        self.assertEqual(retouch["mapping_source"], "task_registry")
        self.assertTrue(retouch["compare_available"])
        self.assertEqual(self.client.get(retouch["preview_url"]).status_code, 200)
        self.assertEqual(self.client.get(retouch["source_preview_url"]).status_code, 200)

        opened_file = self.client.post(f"/api/output-center/items/{color['id']}/open")
        opened_folder = self.client.post(f"/api/output-center/items/{color['id']}/open-folder")
        self.assertEqual((opened_file.status_code, opened_folder.status_code), (200, 200))
        self.assertEqual(self.opened, [str(self.paths["color"].resolve()), str(self.paths["color"].parent.resolve())])

    def test_missing_file_is_not_kept_as_a_normal_output(self):
        data = self.client.get("/api/output-center/items").json()["data"]
        item = next(candidate for candidate in data["items"] if candidate["processing_type"] == "1080p")
        self.paths["1080p"].unlink()
        response = self.client.post(f"/api/output-center/items/{item['id']}/open")
        self.assertEqual(response.status_code, 404)
        current = self.client.get("/api/output-center/items").json()["data"]
        self.assertNotIn(item["id"], {candidate["id"] for candidate in current["items"]})


if __name__ == "__main__":
    unittest.main()
