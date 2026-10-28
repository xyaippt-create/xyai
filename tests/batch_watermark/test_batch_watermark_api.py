from __future__ import annotations

import hashlib
import io
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import backend.batch_watermark_api as batch_watermark_api
from backend.batch_watermark_api import _write_without_overwrite, register_batch_watermark_routes
from engine.batch_watermark import font_registry


def png_bytes(size=(240, 160), color=(30, 60, 90, 255), *, dpi=None, icc_profile=None):
    stream = io.BytesIO()
    save_options = {}
    if dpi is not None:
        save_options["dpi"] = dpi
    if icc_profile is not None:
        save_options["icc_profile"] = icc_profile
    Image.new("RGBA", size, color).save(stream, format="PNG", **save_options)
    return stream.getvalue()


def decoded_dpi(value):
    data = Path(value).read_bytes() if isinstance(value, Path) else bytes(value)
    with Image.open(io.BytesIO(data)) as opened:
        opened.load()
        dpi = opened.info.get("dpi")
        return tuple(round(float(item), 6) for item in dpi) if isinstance(dpi, tuple) else None


def jpeg_bytes(size=(320, 200), color=(70, 100, 140)):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format="JPEG", quality=92)
    return stream.getvalue()


def logo_bytes():
    image = Image.new("RGBA", (80, 40), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((5, 5, 75, 35), fill=(255, 255, 255, 190))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


class BatchWatermarkApiTests(unittest.TestCase):
    @staticmethod
    def abc_output_name(sequence=None):
        sequence_text = f"_{sequence:02d}" if sequence else ""
        return f"ABC_影界水印_{datetime.now():%y%m%d}{sequence_text}.jpg"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.formal_root = Path(self.temporary.name) / "formal"
        self.formal_root.mkdir()
        self.registry = {}
        self.opened = []
        self.events = []
        app = FastAPI()
        register_batch_watermark_routes(
            app,
            user_dirs_provider=lambda: {"directory_ready": True, "app_data_root": self.formal_root},
            shared_task_registry=self.registry,
            folder_opener=self.opened.append,
            runtime_event_logger=lambda event, **fields: self.events.append({"event": event, **fields}),
            now_provider=lambda: 1_788_192_000.0,
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def test_preview_is_backend_rendered_png(self):
        response = self.client.post(
            "/api/batch-watermark/preview",
            files={"file": ("预览.jpg", jpeg_bytes(), "image/jpeg")},
            data={"spec_json": '{"kind":"text","text":"中文预览","opacity":35}'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.headers["x-hdde-watermark-engine"], "hdde.batch-watermark.v1")
        with Image.open(io.BytesIO(response.content)) as opened:
            self.assertEqual(opened.size, (320, 200))

    def test_registered_result_can_be_previewed_and_processed_with_lineage(self):
        source = self.formal_root / "输出" / "1080P画质" / "existing.png"
        source.parent.mkdir(parents=True)
        source.write_bytes(png_bytes((320, 180)))
        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        self.registry["task-a"] = {
            "task_id": "task-a",
            "result_id": "result-a",
            "feature_key": "enhancement_1080p",
            "status": "completed",
            "task_status": "completed",
            "result_file": str(source),
            "output_path": str(source),
            "output_sha256": source_sha,
        }

        preview = self.client.post(
            "/api/batch-watermark/preview",
            data={"result_id": "result-a", "spec_json": '{"kind":"text","text":"继续处理"}'},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        created = self.client.post(
            "/api/batch-watermark/batches",
            data={"result_ids_json": '["result-a"]', "spec_json": '{"kind":"text","text":"继续处理"}'},
        )
        self.assertEqual(created.status_code, 200, created.text)
        item = created.json()["data"]["items"][0]
        self.assertNotEqual(item["result_id"], "result-a")
        self.assertEqual(item["source_result_id"], "result-a")
        self.assertEqual(item["source_task_id"], "task-a")
        self.assertEqual(item["source_result_sha256"], source_sha)
        self.assertEqual(hashlib.sha256(Path(item["output_path"]).read_bytes()).hexdigest(), item["output_sha256"])

    def test_medium_font_id_reaches_batch_record_and_exact_renderer(self):
        response = self.client.post(
            "/api/batch-watermark/batches",
            files=[
                ("files", ("横图.png", png_bytes((960, 540)), "image/png")),
                ("files", ("竖图.png", png_bytes((540, 960)), "image/png")),
            ],
            data={"spec_json": '{"kind":"text","text":"内部资料 CONFIDENTIAL 2026","font_id":"source_han_sans_cn_medium","text_size":42}'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["batch_status"], "FULL_SUCCESS")
        self.assertEqual(self.registry[data["batch_id"]]["spec"]["font_id"], "source_han_sans_cn_medium")
        for item in data["items"]:
            self.assertEqual(item["render_facts"]["font_id"], "source_han_sans_cn_medium")
            self.assertEqual(item["render_facts"]["font_family"], "Source Han Sans CN")
            self.assertEqual(item["render_facts"]["font_style"], "Medium")
            self.assertEqual(item["render_facts"]["font_asset"], "SourceHanSansCN-Medium.otf")

    def test_invalid_or_missing_selected_font_fails_explicitly(self):
        invalid = self.client.post(
            "/api/batch-watermark/preview",
            files={"file": ("预览.png", png_bytes(), "image/png")},
            data={"spec_json": '{"kind":"text","text":"拒绝","font_id":"unknown"}'},
        )
        self.assertEqual(invalid.status_code, 422, invalid.text)
        self.assertEqual(invalid.json()["detail"]["code"], "WATERMARK_SPEC_INVALID")

        with tempfile.TemporaryDirectory() as temporary, patch.object(font_registry, "FONT_ASSET_ROOT", Path(temporary)):
            missing = self.client.post(
                "/api/batch-watermark/preview",
                files={"file": ("预览.png", png_bytes(), "image/png")},
                data={"spec_json": '{"kind":"text","text":"不得回退","font_id":"source_han_sans_cn_medium"}'},
            )
        self.assertEqual(missing.status_code, 422, missing.text)
        self.assertEqual(missing.json()["detail"]["code"], "WATERMARK_PREVIEW_REJECTED")
        self.assertIn("缺少内置字体文件", missing.json()["detail"]["message"])

    def test_multi_file_partial_failure_is_honest_and_sources_are_unchanged(self):
        source_png = png_bytes()
        source_jpeg = jpeg_bytes()
        response = self.client.post(
            "/api/batch-watermark/batches",
            files=[
                ("files", ("海报.png", source_png, "image/png")),
                ("files", ("照片.jpg", source_jpeg, "image/jpeg")),
                ("files", ("损坏.png", b"not-an-image", "image/png")),
            ],
            data={"spec_json": '{"kind":"text","text":"影界版权","position":"bottom-right"}'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["batch_status"], "PARTIAL_SUCCESS")
        self.assertEqual((data["total"], data["completed"], data["failed"]), (3, 2, 1))
        self.assertTrue(data["items"][0]["source_unchanged"])
        self.assertEqual(data["items"][0]["source_sha_before"], hashlib.sha256(source_png).hexdigest())
        self.assertEqual(data["items"][0]["source_sha_before"], data["items"][0]["source_sha_after"])
        self.assertIn("无法读取源图片", data["items"][2]["failure_reason"])
        output_root = self.formal_root / "输出" / "批量水印"
        self.assertEqual(len(list(output_root.iterdir())), 2)
        self.assertEqual(self.registry[data["batch_id"]]["status"], "completed")

    def test_formal_batch_preserves_rgba_png_nondefault_dpi_and_metadata_integrity(self):
        source = png_bytes(color=(30, 60, 90, 173), dpi=(143, 117), icc_profile=b"hdde-test-icc")
        source_dpi = decoded_dpi(source)
        response = self.client.post(
            "/api/batch-watermark/batches",
            files={"files": ("带DPI透明图.png", source, "image/png")},
            data={"spec_json": '{"kind":"text","text":"DPI回归","position":"bottom-right"}'},
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["batch_status"], "FULL_SUCCESS")
        item = data["items"][0]
        self.assertEqual(item["status"], "completed")
        self.assertTrue(item["source_unchanged"])
        self.assertEqual(item["source_sha_before"], hashlib.sha256(source).hexdigest())
        self.assertEqual(item["source_sha_before"], item["source_sha_after"])
        output_path = Path(item["output_path"])
        self.assertTrue(output_path.is_file())
        self.assertEqual(decoded_dpi(output_path), source_dpi)

        metadata = item["output_metadata"]
        self.assertTrue(metadata["decoded_pixel_content_unchanged"])
        self.assertTrue(metadata["alpha_unchanged"])
        self.assertTrue(metadata["icc_unchanged"])
        self.assertTrue(metadata["dpi_unchanged"])
        self.assertTrue(metadata["source_metadata_preserved"])
        with Image.open(io.BytesIO(source)) as source_image, Image.open(output_path) as output_image:
            source_image.load()
            output_image.load()
            self.assertEqual(output_image.mode, "RGBA")
            self.assertEqual(output_image.info.get("icc_profile"), source_image.info.get("icc_profile"))
            source_alpha = source_image.getchannel("A")
            output_alpha = output_image.getchannel("A")
            left, top, right, bottom = item["render_facts"]["overlay_bbox"]
            for y in range(output_image.height):
                for x in range(output_image.width):
                    if not (left <= x < right and top <= y < bottom):
                        self.assertEqual(output_alpha.getpixel((x, y)), source_alpha.getpixel((x, y)))

    def test_formal_batch_png_without_dpi_does_not_invent_dpi(self):
        source = png_bytes(color=(30, 60, 90, 173))
        self.assertIsNone(decoded_dpi(source))
        response = self.client.post(
            "/api/batch-watermark/batches",
            files={"files": ("无DPI透明图.png", source, "image/png")},
            data={"spec_json": '{"kind":"text","text":"无DPI回归"}'},
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["batch_status"], "FULL_SUCCESS")
        item = data["items"][0]
        self.assertEqual(item["status"], "completed")
        self.assertIsNone(decoded_dpi(Path(item["output_path"])))
        self.assertTrue(item["output_metadata"]["dpi_unchanged"])

    def test_logo_batch_relative_size_and_open_folder(self):
        response = self.client.post(
            "/api/batch-watermark/batches",
            files=[
                ("files", ("small.png", png_bytes((300, 200)), "image/png")),
                ("files", ("large.png", png_bytes((900, 600)), "image/png")),
                ("watermark_file", ("logo.png", logo_bytes(), "image/png")),
            ],
            data={"spec_json": '{"kind":"image","image_width_percent":15,"opacity":60,"position":"center"}'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["batch_status"], "FULL_SUCCESS")
        self.assertEqual([item["render_facts"]["relative_width_percent"] for item in data["items"]], [15.0, 15.0])
        opened = self.client.post("/api/batch-watermark/open-output-folder", json={"batch_id": data["batch_id"]})
        self.assertEqual(opened.status_code, 200, opened.text)
        self.assertEqual(self.opened, [str(self.formal_root / "输出" / "批量水印")])

    def test_existing_batch_get_restores_full_partial_failed_and_rejects_unknown_id(self):
        cases = [
            ([
                ("files", ("完整.png", png_bytes(), "image/png")),
                ("files", ("照片.jpg", jpeg_bytes(), "image/jpeg")),
            ], "FULL_SUCCESS"),
            ([
                ("files", ("有效.png", png_bytes(), "image/png")),
                ("files", ("损坏.png", b"not-an-image", "image/png")),
            ], "PARTIAL_SUCCESS"),
            ([
                ("files", ("全部损坏.png", b"not-an-image", "image/png")),
            ], "FAILED"),
        ]
        for files, expected_status in cases:
            with self.subTest(expected_status=expected_status):
                created = self.client.post(
                    "/api/batch-watermark/batches",
                    files=files,
                    data={"spec_json": '{"kind":"text","text":"恢复测试"}'},
                )
                self.assertEqual(created.status_code, 200, created.text)
                expected = created.json()["data"]
                restored = self.client.get(f"/api/batch-watermark/batches/{expected['batch_id']}")
                self.assertEqual(restored.status_code, 200, restored.text)
                self.assertEqual(restored.json()["data"], expected)
                self.assertEqual(restored.json()["data"]["batch_status"], expected_status)

        missing = self.client.get("/api/batch-watermark/batches/watermark_batch_0000000000000000")
        self.assertEqual(missing.status_code, 404, missing.text)
        self.assertEqual(missing.json()["detail"]["code"], "WATERMARK_BATCH_NOT_FOUND")

    def test_same_name_and_path_like_name_never_overwrite(self):
        files = [
            ("files", ("../同名.png", png_bytes(color=(10, 20, 30, 255)), "image/png")),
            ("files", ("同名.png", png_bytes(color=(50, 60, 70, 255)), "image/png")),
        ]
        response = self.client.post(
            "/api/batch-watermark/batches",
            files=files,
            data={"spec_json": '{"kind":"text","text":"版权"}'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        names = [item["output_file_name"] for item in response.json()["data"]["items"]]
        self.assertEqual(len(set(names)), 2)
        self.assertTrue(all(".." not in name and "/" not in name for name in names))

    def test_atomic_occupancy_conflict_preserves_foreign_file_and_uses_second_name(self):
        output_root = self.formal_root / "输出" / "批量水印"
        output_root.mkdir(parents=True)
        occupied = output_root / self.abc_output_name()
        foreign_bytes = b"foreign-owner-content"
        occupied.write_bytes(foreign_bytes)
        foreign_sha = hashlib.sha256(foreign_bytes).hexdigest()

        created = _write_without_overwrite(output_root, "ABC.jpg", b"current-call-content")

        self.assertEqual(created.name, self.abc_output_name(2))
        self.assertEqual(occupied.read_bytes(), foreign_bytes)
        self.assertEqual(hashlib.sha256(occupied.read_bytes()).hexdigest(), foreign_sha)
        self.assertEqual(created.read_bytes(), b"current-call-content")

    def test_publish_race_never_deletes_replacement_at_formal_candidate(self):
        output_root = self.formal_root / "输出" / "批量水印"
        output_root.mkdir(parents=True)
        replacement = output_root / self.abc_output_name()
        replacement_bytes = b"third-party-replacement"
        replacement_sha = hashlib.sha256(replacement_bytes).hexdigest()
        real_publish = batch_watermark_api._atomic_publish_no_replace
        race_injected = False

        def publish_after_third_party_wins(open_file, candidate):
            nonlocal race_injected
            if not race_injected and candidate == replacement:
                replacement.write_bytes(replacement_bytes)
                race_injected = True
                raise FileExistsError("third party published first")
            return real_publish(open_file, candidate)

        with patch("backend.batch_watermark_api._atomic_publish_no_replace", side_effect=publish_after_third_party_wins):
            created = _write_without_overwrite(output_root, "ABC.jpg", b"current-call-content")

        self.assertTrue(race_injected)
        self.assertEqual(created.name, self.abc_output_name(2))
        self.assertEqual(replacement.read_bytes(), replacement_bytes)
        self.assertEqual(hashlib.sha256(replacement.read_bytes()).hexdigest(), replacement_sha)
        self.assertFalse(list(output_root.glob(f"{batch_watermark_api.PRIVATE_TEMP_PREFIX}*")))

    def test_successful_publish_never_unlinks_reused_old_private_path(self):
        output_root = self.formal_root / "输出" / "批量水印"
        output_root.mkdir(parents=True)
        foreign_bytes = b"foreign-after-successful-publish"
        foreign_sha = hashlib.sha256(foreign_bytes).hexdigest()
        real_publish = batch_watermark_api._atomic_publish_no_replace
        real_open = batch_watermark_api._open_owned_private_temp
        reused_private_path = None
        current_private_path = None

        def open_and_capture_private_path(root):
            nonlocal current_private_path
            current_private_path, open_file = real_open(root)
            return current_private_path, open_file

        def publish_then_reuse_old_private_path(open_file, candidate):
            nonlocal reused_private_path
            real_publish(open_file, candidate)
            current_private_path.write_bytes(foreign_bytes)
            reused_private_path = current_private_path

        with patch(
            "backend.batch_watermark_api._open_owned_private_temp",
            side_effect=open_and_capture_private_path,
        ), patch(
            "backend.batch_watermark_api._atomic_publish_no_replace",
            side_effect=publish_then_reuse_old_private_path,
        ), patch.object(Path, "unlink", side_effect=AssertionError("released private path must never be unlinked")):
            created = _write_without_overwrite(output_root, "valid.png", png_bytes())

        self.assertIsNotNone(reused_private_path)
        self.assertTrue(reused_private_path.exists())
        self.assertEqual(reused_private_path.read_bytes(), foreign_bytes)
        self.assertEqual(hashlib.sha256(reused_private_path.read_bytes()).hexdigest(), foreign_sha)
        with Image.open(created) as opened:
            opened.load()
            self.assertEqual(opened.format, "PNG")
            self.assertEqual(opened.size, (240, 160))

    def test_handle_publish_ignores_rebound_source_path_and_publishes_written_bytes(self):
        output_root = self.formal_root / "输出" / "批量水印"
        output_root.mkdir(parents=True)
        written_bytes = png_bytes(color=(12, 34, 56, 255))
        written_sha = hashlib.sha256(written_bytes).hexdigest()
        foreign_bytes = b"foreign-private-path-replacement"
        foreign_sha = hashlib.sha256(foreign_bytes).hexdigest()
        moved_owned_path = output_root / "attacker-moved-owned-a.tmp"
        real_open = batch_watermark_api._open_owned_private_temp
        real_publish = batch_watermark_api._atomic_publish_no_replace
        state = {}

        def open_and_capture(root):
            private_path, open_file = real_open(root)
            state["private_path"] = private_path
            return private_path, open_file

        def rebind_before_publish(open_file, candidate):
            if not state.get("rebound"):
                os.rename(state["private_path"], moved_owned_path)
                state["private_path"].write_bytes(foreign_bytes)
                state["rebound"] = True
            return real_publish(open_file, candidate)

        with patch("backend.batch_watermark_api._open_owned_private_temp", side_effect=open_and_capture), patch(
            "backend.batch_watermark_api._atomic_publish_no_replace",
            side_effect=rebind_before_publish,
        ):
            created = _write_without_overwrite(output_root, "source.png", written_bytes)

        self.assertTrue(state.get("rebound"))
        self.assertFalse(moved_owned_path.exists())
        self.assertEqual(hashlib.sha256(created.read_bytes()).hexdigest(), written_sha)
        self.assertEqual(state["private_path"].read_bytes(), foreign_bytes)
        self.assertEqual(hashlib.sha256(state["private_path"].read_bytes()).hexdigest(), foreign_sha)
        with Image.open(created) as opened:
            opened.load()
            self.assertEqual(opened.format, "PNG")

    def test_handle_publish_retries_collision_after_source_path_rebind(self):
        output_root = self.formal_root / "输出" / "批量水印"
        output_root.mkdir(parents=True)
        occupied = output_root / self.abc_output_name()
        occupied_bytes = b"existing-formal-owner"
        occupied.write_bytes(occupied_bytes)
        occupied_sha = hashlib.sha256(occupied_bytes).hexdigest()
        written_bytes = b"current-handle-content"
        written_sha = hashlib.sha256(written_bytes).hexdigest()
        foreign_bytes = b"foreign-private-path-replacement"
        foreign_sha = hashlib.sha256(foreign_bytes).hexdigest()
        moved_owned_path = output_root / "attacker-moved-owned-b.tmp"
        real_open = batch_watermark_api._open_owned_private_temp
        real_publish = batch_watermark_api._atomic_publish_no_replace
        state = {}

        def open_and_capture(root):
            private_path, open_file = real_open(root)
            state["private_path"] = private_path
            return private_path, open_file

        def rebind_before_publish(open_file, candidate):
            if not state.get("rebound"):
                os.rename(state["private_path"], moved_owned_path)
                state["private_path"].write_bytes(foreign_bytes)
                state["rebound"] = True
            return real_publish(open_file, candidate)

        with patch("backend.batch_watermark_api._open_owned_private_temp", side_effect=open_and_capture), patch(
            "backend.batch_watermark_api._atomic_publish_no_replace",
            side_effect=rebind_before_publish,
        ):
            created = _write_without_overwrite(output_root, "ABC.jpg", written_bytes)

        self.assertEqual(created.name, self.abc_output_name(2))
        self.assertFalse(moved_owned_path.exists())
        self.assertEqual(hashlib.sha256(created.read_bytes()).hexdigest(), written_sha)
        self.assertEqual(hashlib.sha256(occupied.read_bytes()).hexdigest(), occupied_sha)
        self.assertEqual(hashlib.sha256(state["private_path"].read_bytes()).hexdigest(), foreign_sha)

    def test_handle_publish_retries_continuous_collisions_after_source_path_rebind(self):
        output_root = self.formal_root / "输出" / "批量水印"
        output_root.mkdir(parents=True)
        occupied = {
            output_root / self.abc_output_name(): b"first-formal-owner",
            output_root / self.abc_output_name(2): b"second-formal-owner",
        }
        occupied_sha = {}
        for path, content in occupied.items():
            path.write_bytes(content)
            occupied_sha[path] = hashlib.sha256(content).hexdigest()
        written_bytes = b"current-handle-third-content"
        written_sha = hashlib.sha256(written_bytes).hexdigest()
        foreign_bytes = b"foreign-private-path-replacement"
        foreign_sha = hashlib.sha256(foreign_bytes).hexdigest()
        moved_owned_path = output_root / "attacker-moved-owned-c.tmp"
        real_open = batch_watermark_api._open_owned_private_temp
        real_publish = batch_watermark_api._atomic_publish_no_replace
        state = {}

        def open_and_capture(root):
            private_path, open_file = real_open(root)
            state["private_path"] = private_path
            return private_path, open_file

        def rebind_before_publish(open_file, candidate):
            if not state.get("rebound"):
                os.rename(state["private_path"], moved_owned_path)
                state["private_path"].write_bytes(foreign_bytes)
                state["rebound"] = True
            return real_publish(open_file, candidate)

        with patch("backend.batch_watermark_api._open_owned_private_temp", side_effect=open_and_capture), patch(
            "backend.batch_watermark_api._atomic_publish_no_replace",
            side_effect=rebind_before_publish,
        ):
            created = _write_without_overwrite(output_root, "ABC.jpg", written_bytes)

        self.assertEqual(created.name, self.abc_output_name(3))
        self.assertFalse(moved_owned_path.exists())
        self.assertEqual(hashlib.sha256(created.read_bytes()).hexdigest(), written_sha)
        for path, expected_sha in occupied_sha.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected_sha)
        self.assertEqual(hashlib.sha256(state["private_path"].read_bytes()).hexdigest(), foreign_sha)

    def test_two_concurrent_writers_atomically_receive_distinct_names(self):
        output_root = self.formal_root / "输出" / "批量水印"
        output_root.mkdir(parents=True)
        barrier = threading.Barrier(2)

        def write_as_one_actor(content):
            barrier.wait(timeout=5)
            return _write_without_overwrite(output_root, "ABC.jpg", content)

        contents = (b"writer-one-content", b"writer-two-content")
        with ThreadPoolExecutor(max_workers=2) as executor:
            paths = list(executor.map(write_as_one_actor, contents))

        self.assertEqual({path.name for path in paths}, {self.abc_output_name(), self.abc_output_name(2)})
        self.assertEqual({path.read_bytes() for path in paths}, set(contents))

    def test_consecutive_atomic_conflicts_preserve_both_and_use_third_name(self):
        output_root = self.formal_root / "输出" / "批量水印"
        output_root.mkdir(parents=True)
        occupied = {
            output_root / self.abc_output_name(): b"first-owner",
            output_root / self.abc_output_name(2): b"second-owner",
        }
        before = {}
        for path, content in occupied.items():
            path.write_bytes(content)
            before[path] = hashlib.sha256(content).hexdigest()

        created = _write_without_overwrite(output_root, "ABC.jpg", b"third-owner")

        self.assertEqual(created.name, self.abc_output_name(3))
        self.assertEqual(created.read_bytes(), b"third-owner")
        for path, expected_sha in before.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected_sha)

    def test_failed_write_deletes_owned_handle_before_old_path_is_reused(self):
        output_root = self.formal_root / "输出" / "批量水印"
        output_root.mkdir(parents=True)
        foreign = output_root / self.abc_output_name()
        foreign_bytes = b"foreign-owner-content"
        foreign.write_bytes(foreign_bytes)
        foreign_sha = hashlib.sha256(foreign_bytes).hexdigest()
        replacement_bytes = b"foreign-after-owned-handle-close"
        replacement_sha = hashlib.sha256(replacement_bytes).hexdigest()
        real_open = batch_watermark_api._open_owned_private_temp
        reused_private_path = None
        owned_removed_before_reuse = False

        class CloseThenReusePath:
            def __init__(self, wrapped, private_path):
                self.wrapped = wrapped
                self.private_path = private_path

            def __getattr__(self, name):
                return getattr(self.wrapped, name)

            def close(self):
                nonlocal reused_private_path, owned_removed_before_reuse
                self.wrapped.close()
                owned_removed_before_reuse = not self.private_path.exists()
                self.private_path.write_bytes(replacement_bytes)
                reused_private_path = self.private_path

        def open_with_close_reuse(root):
            private_path, open_file = real_open(root)
            return private_path, CloseThenReusePath(open_file, private_path)

        with patch("backend.batch_watermark_api._open_owned_private_temp", side_effect=open_with_close_reuse), patch(
            "backend.batch_watermark_api.os.fsync",
            side_effect=OSError("forced-own-write-failure"),
        ), patch.object(Path, "unlink", side_effect=AssertionError("released private path must never be unlinked")):
            with self.assertRaisesRegex(OSError, "forced-own-write-failure"):
                _write_without_overwrite(output_root, "ABC.jpg", b"incomplete-current-call")

        self.assertTrue(owned_removed_before_reuse)
        self.assertIsNotNone(reused_private_path)
        self.assertTrue(reused_private_path.exists())
        self.assertEqual(reused_private_path.read_bytes(), replacement_bytes)
        self.assertEqual(hashlib.sha256(reused_private_path.read_bytes()).hexdigest(), replacement_sha)
        self.assertEqual(hashlib.sha256(foreign.read_bytes()).hexdigest(), foreign_sha)
        self.assertFalse((output_root / self.abc_output_name(2)).exists())

    def test_successful_publish_is_decodable_and_leaves_no_private_temp(self):
        output_root = self.formal_root / "输出" / "批量水印"
        output_root.mkdir(parents=True)
        created = _write_without_overwrite(output_root, "valid.png", png_bytes())

        with Image.open(created) as opened:
            opened.load()
            self.assertEqual(opened.format, "PNG")
            self.assertEqual(opened.size, (240, 160))
        self.assertGreater(created.stat().st_size, 0)
        self.assertFalse(list(output_root.glob(f"{batch_watermark_api.PRIVATE_TEMP_PREFIX}*")))

    def test_concurrent_same_name_stress_keeps_all_outputs_unique_and_decodable(self):
        output_root = self.formal_root / "输出" / "批量水印"
        output_root.mkdir(parents=True)
        actor_count = 24
        barrier = threading.Barrier(actor_count)
        payloads = [png_bytes(color=(index, 60, 90, 255)) for index in range(actor_count)]

        def publish_as_one_actor(payload):
            barrier.wait(timeout=10)
            return _write_without_overwrite(output_root, "stress.png", payload)

        with ThreadPoolExecutor(max_workers=actor_count) as executor:
            paths = list(executor.map(publish_as_one_actor, payloads))

        self.assertEqual(len(paths), actor_count)
        self.assertEqual(len({path.name for path in paths}), actor_count)
        for path in paths:
            self.assertGreater(path.stat().st_size, 0)
            with Image.open(path) as opened:
                opened.load()
                self.assertEqual(opened.format, "PNG")
                self.assertEqual(opened.size, (240, 160))
        self.assertFalse(list(output_root.glob(f"{batch_watermark_api.PRIVATE_TEMP_PREFIX}*")))

    def test_invalid_logo_and_unready_formal_root_fail_closed(self):
        invalid_logo = self.client.post(
            "/api/batch-watermark/batches",
            files=[
                ("files", ("source.png", png_bytes(), "image/png")),
                ("watermark_file", ("logo.png", b"broken", "image/png")),
            ],
            data={"spec_json": '{"kind":"image"}'},
        )
        self.assertEqual(invalid_logo.status_code, 200, invalid_logo.text)
        self.assertEqual(invalid_logo.json()["data"]["batch_status"], "FAILED")
        self.assertEqual(invalid_logo.json()["data"]["failed"], 1)

        blocked_app = FastAPI()
        register_batch_watermark_routes(
            blocked_app,
            user_dirs_provider=lambda: {"directory_ready": False, "directory_message": "正式目录不可用"},
            shared_task_registry={},
        )
        with TestClient(blocked_app) as blocked_client:
            response = blocked_client.post(
                "/api/batch-watermark/preview",
                files={"file": ("source.png", png_bytes(), "image/png")},
                data={"spec_json": '{"kind":"text","text":"版权"}'},
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["code"], "FORMAL_DIRECTORY_NOT_READY")


if __name__ == "__main__":
    unittest.main()
