import io
import tempfile
import unittest
from collections import Counter
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageFile

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
            "1080p": self.output_root / "1080P画质" / "standard.png",
            "4k": self.output_root / "4K画质增强" / "four-k.png",
            "compression": self.output_root / "图片压缩" / "PNG无损压缩" / "compressed.png",
            "color": self.output_root / "颜色校正" / "meeting_影界自动校正_20260809_120000.jpg",
            "retouch": self.output_root / "瑕疵修复" / "poster_影界瑕疵修复_20260810_120000.png",
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
        self.output_center_user_dirs_call_count = 0

        def output_center_user_dirs():
            self.output_center_user_dirs_call_count += 1
            return {
                "app_data_root": self.app_root,
                "normal_output_dir": self.output_root / "1080P画质",
                "safe_beta_output_dir": self.output_root / "1080P画质",
                "image_compression_output_dir": self.output_root / "图片压缩",
                "tmp_dir": self.tmp,
            }

        excluded = self.output_root / "4K画质增强" / "evidence" / "must-not-appear.png"
        excluded.parent.mkdir(parents=True)
        Image.new("RGB", (20, 20), (255, 0, 0)).save(excluded)
        explicit_test_output = self.output_root / "1080P画质" / "front_upload_test_影界高清.png"
        Image.new("RGB", (20, 20), (255, 0, 0)).save(explicit_test_output)
        explicit_sample_output = self.output_root / "颜色校正" / "sample_a_影界自动校正_20260809_120000.jpg"
        Image.new("RGB", (20, 20), (255, 0, 0)).save(explicit_sample_output)
        (self.output_root / "1080P画质" / "broken.png").write_bytes(b"not-an-image")

        app = FastAPI()
        register_image_compression_routes(
            app,
            user_dirs_provider=lambda: {
                "app_data_root": self.app_root,
                "normal_output_dir": self.output_root / "1080P画质",
                "safe_beta_output_dir": self.output_root / "1080P画质",
                "image_compression_output_dir": self.output_root / "图片压缩",
                "tmp_dir": self.tmp,
            },
            output_center_user_dirs_provider=output_center_user_dirs,
            folder_opener=self.opened.append,
            output_settings_provider=lambda: {
                "built_in_default_root": str(self.output_root / "图片压缩"),
                "saved_default_root": str(self.output_root / "图片压缩"),
            },
            shared_task_registry=self.shared_registry,
        )
        self.app = app
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def test_large_header_is_listed_without_disabling_pillow_safety(self):
        # Real existing image, lowered guard to exercise the same failure cheaply.
        with patch.object(Image, "MAX_IMAGE_PIXELS", 1000):
            page = self.client.get("/api/output-center/items").json()["data"]
            item = next((i for i in page["items"] if i["file_name"] == "standard.png"), None)
            self.assertIsNotNone(item)
            self.assertEqual((item["width"], item["height"]), (85, 60))
            response = self.client.get(item["thumbnail_url"])
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["detail"]["code"], "OUTPUT_THUMBNAIL_UNAVAILABLE")
            self.assertEqual(Image.MAX_IMAGE_PIXELS, 1000)

    def test_corrupt_cache_is_regenerated_and_source_is_unchanged(self):
        item = next(i for i in self.client.get("/api/output-center/items").json()["data"]["items"] if i["file_name"] == "standard.png")
        source_before = self.paths["1080p"].read_bytes()
        self.assertEqual(self.client.get(item["thumbnail_url"]).status_code, 200)
        cache = next((self.tmp / "output-center-thumbnails").glob("*.png"))
        cache.write_bytes(b"damaged non-empty cache")
        response = self.client.get(item["thumbnail_url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-hdde-thumbnail-cache"], "MISS")
        with Image.open(io.BytesIO(response.content)) as image:
            image.load()
            self.assertLessEqual(max(image.size), 768)
        self.assertEqual(self.paths["1080p"].read_bytes(), source_before)

    def test_thumbnail_descriptor_failure_does_not_remove_cards(self):
        original = __import__("backend.image_compression_api", fromlist=["hashlib"]).hashlib.sha256
        def cache_failure(value=b""):
            if b"|768|" in value:
                raise OSError("owned unavailable cache descriptor")
            return original(value)
        with patch("backend.image_compression_api.hashlib.sha256", cache_failure):
            response = self.client.get("/api/output-center/items")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["count"], 5)
        self.assertEqual(len(response.json()["data"]["items"]), 5)
        self.assertTrue(all(i["available"] for i in response.json()["data"]["items"]))

    def test_registered_missing_result_keeps_explicit_missing_card(self):
        record = self.shared_registry["retouch_task_001"]
        record["output_sha256"] = sha256(self.paths["retouch"].read_bytes()).hexdigest()
        before = next(i for i in self.client.get("/api/output-center/items").json()["data"]["items"] if i["result_id"] == "retouch_result_001")
        self.paths["retouch"].unlink()
        after = next((i for i in self.client.get("/api/output-center/items").json()["data"]["items"] if i["id"] == before["id"]), None)
        self.assertIsNotNone(after)
        self.assertFalse(after["available"])
        self.assertEqual(after["file_status"], "MISSING")
        self.assertEqual(after["result_id"], before["result_id"])
        self.assertFalse(after["thumbnail_url"])
        # Missing cards use persisted Result facts, not live-file migration probes.
        # A missing-only page must also avoid the resolver's empty-set full scan.
        with patch(
            "backend.image_compression_api.resolve_migrated_formal_output_path",
            side_effect=AssertionError("Missing cards must not probe live output details"),
        ):
            missing_page = self.client.get(
                "/api/output-center/items", params={"query": self.paths["retouch"].name, "limit": 12}
            ).json()["data"]
        self.assertEqual([item["id"] for item in missing_page["items"]], [before["id"]])
        self.assertEqual(missing_page["items"][0]["result_id"], before["result_id"])
        self.assertEqual(missing_page["items"][0]["file_status"], "MISSING")
        self.assertEqual(self.client.get(f"/api/output-center/items/{after['id']}/preview").status_code, 404)

    def test_resolved_cache_escape_is_rejected_without_hiding_result(self):
        original = Path.resolve
        outside = self.root / "outside-cache"
        def resolve_cache(path, *args, **kwargs):
            if path.name == "output-center-thumbnails":
                return outside
            return original(path, *args, **kwargs)
        with patch.object(Path, "resolve", resolve_cache):
            page = self.client.get("/api/output-center/items").json()["data"]
            self.assertEqual(len(page["items"]), 5)
            item = next(i for i in page["items"] if i["file_name"] == "standard.png")
            self.assertEqual(item["thumbnail_status"], "unavailable")
            self.assertTrue(item["available"])
            self.assertEqual(self.client.get(f"/api/output-center/items/{item['id']}/thumbnail").status_code, 422)
        self.assertFalse(outside.exists())

    def test_cache_presence_permission_failure_keeps_result_cards(self):
        original = Path.is_file
        def probe(path):
            if path.parent.name == "output-center-thumbnails":
                raise PermissionError("owned denied thumbnail cache probe")
            return original(path)
        with patch.object(Path, "is_file", probe):
            response = self.client.get("/api/output-center/items")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]["items"]), 5)
        self.assertTrue(all(i["available"] and i["thumbnail_status"] == "unavailable" for i in response.json()["data"]["items"]))

    def test_formal_sources_are_shallow_real_and_action_bound(self):
        pixel_loads = []
        original_load = ImageFile.ImageFile.load
        from backend import image_compression_api
        header_reads = Counter()
        original_header = image_compression_api.read_image_header
        cache_root_resolves = []
        original_resolve = Path.resolve

        def resolve_path(path, *args, **kwargs):
            if path.name == "output-center-thumbnails":
                cache_root_resolves.append(path)
            return original_resolve(path, *args, **kwargs)

        def read_header(path):
            header_reads[str(path)] += 1
            return original_header(path)

        def track_pixel_load(image, *args, **kwargs):
            pixel_loads.append(image.filename)
            return original_load(image, *args, **kwargs)

        with patch.object(ImageFile.ImageFile, "load", track_pixel_load), patch.object(
            image_compression_api, "read_image_header", read_header
        ), patch.object(Path, "resolve", resolve_path):
            response = self.client.get("/api/output-center/items")
        self.assertEqual(pixel_loads, [])
        self.assertTrue(header_reads)
        self.assertTrue(all(count == 1 for count in header_reads.values()))
        self.assertEqual(len(cache_root_resolves), 1)
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

        four_k = next(item for item in data["items"] if item["processing_type"] == "4k")
        self.assertEqual(four_k["thumbnail_status"], "not_cached")
        self.assertIn(f"/api/output-center/items/{four_k['id']}/thumbnail?v=", four_k["thumbnail_url"])
        source_sha = sha256(self.paths["4k"].read_bytes()).hexdigest()
        first_thumbnail = self.client.get(four_k["thumbnail_url"])
        self.assertEqual(first_thumbnail.status_code, 200, first_thumbnail.text)
        self.assertEqual(first_thumbnail.headers["x-hdde-thumbnail-cache"], "MISS")
        self.assertEqual(first_thumbnail.headers["x-hdde-thumbnail-max-edge"], "768")
        with Image.open(__import__("io").BytesIO(first_thumbnail.content)) as thumbnail:
            self.assertLessEqual(max(thumbnail.size), 768)
        second_thumbnail = self.client.get(four_k["thumbnail_url"])
        self.assertEqual(second_thumbnail.status_code, 200)
        self.assertEqual(second_thumbnail.headers["x-hdde-thumbnail-cache"], "HIT")
        self.assertEqual(sha256(self.paths["4k"].read_bytes()).hexdigest(), source_sha)

        self.paths["4k"].touch()
        refreshed = self.client.get("/api/output-center/items").json()["data"]
        refreshed_four_k = next(item for item in refreshed["items"] if item["processing_type"] == "4k")
        self.assertNotEqual(refreshed_four_k["thumbnail_url"], four_k["thumbnail_url"])
        self.assertEqual(refreshed_four_k["thumbnail_status"], "not_cached")

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
        self.assertEqual(retouch["processing_label"], "瑕疵修复")
        self.assertTrue(retouch["compare_available"])
        self.assertEqual(self.client.get(retouch["preview_url"]).status_code, 200)
        self.assertEqual(self.client.get(retouch["source_preview_url"]).status_code, 200)

        opened_file = self.client.post(f"/api/output-center/items/{color['id']}/open")
        opened_folder = self.client.post(f"/api/output-center/items/{color['id']}/open-folder")
        self.assertEqual((opened_file.status_code, opened_folder.status_code), (200, 200))
        self.assertEqual(self.opened, [str(self.paths["color"].resolve()), str(self.paths["color"].parent.resolve())])

    def test_webp_result_is_visible_with_webp_preview_and_thumbnail(self):
        result_path = self.output_root / "图片压缩" / "交付优化" / "compressed.webp"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (96, 72), (40, 90, 140, 180)).save(result_path, format="WEBP", lossless=True)
        source_path = self.tmp / "image-compression-intake" / "intake_webp" / "source.webp"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (96, 72), (35, 85, 135)).save(source_path, format="WEBP", lossless=True)
        result_id = "compression_result_webp_001"
        task_id = "compression_task_webp_001"
        result_sha256 = sha256(result_path.read_bytes()).hexdigest()
        self.shared_registry[task_id] = {
            "task_id": task_id,
            "result_id": result_id,
            "feature_key": "image_compression",
            "task_family": "image_compression",
            "status": "completed",
            "source_path": source_path,
            "source": str(source_path),
            "output_path": result_path,
            "result_file": str(result_path),
            "output_sha256": result_sha256,
            "delivery_eligible": True,
            "result": {
                "result_id": result_id,
                "task_id": task_id,
                "feature_key": "image_compression",
                "source_path": str(source_path),
                "source": str(source_path),
                "output_path": str(result_path),
                "result_file": str(result_path),
                "output_sha256": result_sha256,
                "delivery_eligible": True,
                "status": "completed",
            },
        }

        response = self.client.get("/api/output-center/items")
        self.assertEqual(response.status_code, 200, response.text)
        item = next(entry for entry in response.json()["data"]["items"] if entry["result_id"] == result_id)
        self.assertEqual(item["format"], "WEBP")
        self.assertTrue(item["delivery_eligible"])

        preview = self.client.get(item["preview_url"])
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.headers["content-type"], "image/webp")
        with Image.open(io.BytesIO(preview.content)) as opened:
            self.assertEqual(opened.format, "WEBP")

        thumbnail = self.client.get(item["thumbnail_url"])
        self.assertEqual(thumbnail.status_code, 200, thumbnail.text)
        self.assertEqual(thumbnail.headers["content-type"], "image/webp")
        with Image.open(io.BytesIO(thumbnail.content)) as opened:
            self.assertEqual(opened.format, "WEBP")
            self.assertLessEqual(max(opened.size), 768)

    def test_items_request_reuses_one_user_dirs_snapshot_for_many_results(self):
        bulk_root = self.output_root / "1080P画质"
        for index in range(24):
            Image.new("RGB", (32, 24), (index, 80, 140)).save(bulk_root / f"bulk-{index:02d}.png")

        self.output_center_user_dirs_call_count = 0
        first = self.client.get("/api/output-center/items")
        self.assertEqual(first.status_code, 200, first.text)
        first_count = first.json()["data"]["count"]
        self.assertGreaterEqual(first_count, 29)
        self.assertEqual(self.output_center_user_dirs_call_count, 1)

        for index in range(24, 48):
            Image.new("RGB", (32, 24), (index, 80, 140)).save(bulk_root / f"bulk-{index:02d}.png")

        self.output_center_user_dirs_call_count = 0
        second = self.client.get("/api/output-center/items")
        self.assertEqual(second.status_code, 200, second.text)
        self.assertGreater(second.json()["data"]["count"], first_count)
        self.assertEqual(self.output_center_user_dirs_call_count, 1)

    def test_items_pagination_preserves_global_search_and_sort(self):
        first_page = self.client.get("/api/output-center/items?limit=2&offset=0&sort=newest").json()["data"]
        self.assertEqual(first_page["count"], 5)
        self.assertEqual(first_page["total_count"], 5)
        self.assertEqual(first_page["returned_count"], 2)
        self.assertTrue(first_page["has_more"])
        self.assertEqual(first_page["next_offset"], 2)
        index = self.app.state.image_compression_api_state["output_center_index"]
        hydrated = [item for item in index.values() if "delivery_eligible_base" in item]
        self.assertEqual(len(index), 5)
        self.assertEqual(len(hydrated), 2)

        second_page = self.client.get("/api/output-center/items?limit=2&offset=2&sort=newest").json()["data"]
        self.assertEqual(second_page["returned_count"], 2)
        self.assertTrue(set(item["id"] for item in first_page["items"]).isdisjoint(item["id"] for item in second_page["items"]))

        oldest = self.client.get("/api/output-center/items?limit=1&sort=oldest").json()["data"]["items"][0]
        newest = first_page["items"][0]
        self.assertLessEqual(oldest["created_at"], newest["created_at"])

        searched = self.client.get("/api/output-center/items?limit=12&query=meeting").json()["data"]
        self.assertEqual(searched["total_count"], 1)
        self.assertEqual(searched["items"][0]["processing_type"], "color_correction")

        category = self.client.get("/api/output-center/items?limit=12&category=local_retouch").json()["data"]
        self.assertEqual(category["total_count"], 1)
        self.assertEqual(category["items"][0]["processing_type"], "local_retouch")

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
