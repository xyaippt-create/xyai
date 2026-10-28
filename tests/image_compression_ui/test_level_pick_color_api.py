"""S64-A level-pick colour correction: preview, user selection and formal Result contract."""
import hashlib
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.image_compression_api import register_image_compression_routes
from engine.color_correction.color_management import srgb_profile_bytes
from engine.color_correction.level_pick import (
    LEVELS,
    analyze_level_pick,
    build_level_pick_preview,
    level_safety,
    render_level,
)
from engine.storage.shared_task_registry import SharedTaskRegistry
from main import DEFAULT_TMP_DIR_NAME


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cast_scene(cast=(10, 4, -14), *, size=(240, 180), alpha=False) -> np.ndarray:
    """Grey cards and a white wall under a yellow cast, plus a saturated red block."""

    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    # Full tonal range like a real render (deep shadows to bright wall), so no grey veil is measured.
    base = 8 + 180 * (xx / (w - 1)) + 40 * (yy / (h - 1))
    rgb = np.stack([np.clip(base + c, 0, 255) for c in cast], -1)
    rgb[20:60, 20:80] = (205, 30, 35)  # brand red, must not drive the estimate
    rgb[-40:, :50] = np.clip(np.array((6, 6, 6)) + np.array(cast) * 0.2, 0, 255)  # deep shadow
    rgb[-40:, -70:] = np.clip(np.array((240, 240, 240)) + np.array(cast), 0, 255)  # white wall
    rgb = rgb.astype(np.uint8)
    if alpha:
        a = np.full((h, w), 255, np.uint8)
        a[:, :30] = 0
        a[:, 30:40] = 128
        rgb = np.dstack((rgb, a))
        rgb[:, :30, :3] = (0, 255, 0)  # hidden RGB must survive untouched
    return rgb


class LevelPickAlgorithmTests(unittest.TestCase):
    def test_levels_are_monotonic_safe_and_reduce_the_cast(self):
        pixels = cast_scene()
        analysis = analyze_level_pick(pixels)
        self.assertIn("YELLOW", analysis.category)
        changes = []
        for name in LEVELS:
            candidate = render_level(pixels, analysis, name)
            safety = level_safety(pixels, candidate, analysis)
            self.assertTrue(safety["passed"], safety)
            changes.append(safety["delta_e00_mean"])
        self.assertLess(changes[0], changes[1])
        self.assertLess(changes[1], changes[2])

    def test_safety_gate_blocks_levels_that_crush_a_channel(self):
        # A pure gradient with no shadows reads as a heavy grey veil; the stretch would
        # push the brand-red block's green channel to 0, so those levels must not be offered.
        w, h = 240, 180
        yy, xx = np.mgrid[0:h, 0:w]
        base = 60 + 90 * (xx / (w - 1)) + 40 * (yy / (h - 1))
        pixels = np.stack([base + 10, base + 4, base - 14], -1).astype(np.uint8)
        pixels[20:60, 20:80] = (205, 30, 35)
        analysis = analyze_level_pick(pixels)
        safety = level_safety(pixels, render_level(pixels, analysis, "strong"), analysis)
        self.assertFalse(safety["passed"])
        self.assertIn("CLIPPING_GROWTH", safety["failures"])

    def test_render_is_deterministic(self):
        pixels = cast_scene()
        analysis = analyze_level_pick(pixels)
        self.assertTrue(np.array_equal(render_level(pixels, analysis, "medium"), render_level(pixels, analysis, "medium")))

    def test_neutral_image_changes_little(self):
        pixels = cast_scene(cast=(0, 0, 0))
        analysis = analyze_level_pick(pixels)
        self.assertEqual(analysis.category, "NO_CAST")
        self.assertEqual(analysis.recommended_level, "original")
        candidate = render_level(pixels, analysis, "strong")
        self.assertLess(level_safety(pixels, candidate, analysis)["delta_e00_mean"], 1.5)

    def test_alpha_and_hidden_rgb_are_preserved(self):
        pixels = cast_scene(alpha=True)
        analysis = analyze_level_pick(pixels)
        candidate = render_level(pixels, analysis, "strong")
        self.assertTrue(np.array_equal(candidate[..., 3], pixels[..., 3]))
        transparent = pixels[..., 3] == 0
        self.assertTrue(np.array_equal(candidate[transparent], pixels[transparent]))

    def test_unknown_level_is_rejected(self):
        pixels = cast_scene()
        with self.assertRaises(ValueError):
            render_level(pixels, analyze_level_pick(pixels), "extreme")


class LevelPickApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.formal = self.root / "formal"
        self.cache = self.formal / DEFAULT_TMP_DIR_NAME
        self.cache.mkdir(parents=True)
        self.output_root = self.formal / "输出"
        self.now = 1_800_000_000.0
        self.events = []
        self.registry = SharedTaskRegistry(self.formal)
        self.client, self.state = self.make_app()

    def make_app(self):
        app = FastAPI()

        def validate(value):
            return {"valid": True, "writable": True, "normalized_path": str(Path(value).resolve())}

        state = register_image_compression_routes(
            app, user_dirs_provider=lambda: {"normal_output_dir": self.output_root, "tmp_dir": self.cache},
            shared_task_registry=self.registry, now_provider=lambda: self.now,
            output_settings_provider=lambda: {"built_in_default_root": str(self.formal), "saved_default_root": str(self.formal)},
            output_dir_validator=validate, folder_opener=lambda value: None,
            runtime_event_logger=lambda event, **fields: self.events.append({"event": event, **fields}),
        )
        return TestClient(app), state

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def intake(self, pixels=None, *, name="cast.png"):
        pixels = cast_scene() if pixels is None else pixels
        stream = io.BytesIO()
        fmt = "JPEG" if name.endswith(".jpg") else "PNG"
        Image.fromarray(pixels).save(stream, format=fmt, icc_profile=srgb_profile_bytes(), **({"quality": 95} if fmt == "JPEG" else {}))
        response = self.client.post("/api/image-compression/intake", files={"file": (name, stream.getvalue(), "image/png" if fmt == "PNG" else "image/jpeg")})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def preview(self, source):
        response = self.client.post("/api/color-correction/level-preview", json={"source_token": source["source_token"]})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def run_level(self, preview, level, **extra):
        return self.client.post("/api/color-correction/level-run", json={
            "preview_id": preview["preview_id"], "level": level,
            "current_task_output_root": str(self.output_root), **extra,
        })

    def color_dir_files(self):
        directory = self.output_root / "颜色校正"
        return sorted(directory.iterdir()) if directory.is_dir() else []

    def test_capabilities_announce_level_pick(self):
        data = self.client.get("/api/color-correction/capabilities").json()["data"]
        self.assertTrue(data["level_pick_available"])
        self.assertEqual(data["level_pick_levels"], ["original", "light", "medium", "strong"])
        self.assertTrue(data["reference_available"])

    def test_preview_offers_four_levels_with_measurement(self):
        source = self.intake()
        data = self.preview(source)
        self.assertEqual([item["level"] for item in data["levels"]], ["original", "light", "medium", "strong"])
        self.assertTrue(all(item["selectable"] for item in data["levels"]))
        self.assertIn("偏黄", data["measurement"]["summary"])
        for item in data["levels"]:
            image = self.client.get(item["preview_url"])
            self.assertEqual(image.status_code, 200)
        session = self.state["color_level_preview_sessions"][data["preview_id"]]
        self.assertTrue(all(Path(item["path"]).resolve().is_relative_to(self.cache.resolve()) for item in session["levels"].values()))
        self.assertEqual(self.color_dir_files(), [])
        self.assertEqual(len(self.registry), 0)

    def test_selected_level_becomes_human_confirmed_result_matching_preview(self):
        source = self.intake()
        source_path = Path(self.state["token_registry"][source["source_token"]]["path"])
        source_sha = sha256(source_path)
        data = self.preview(source)
        session = self.state["color_level_preview_sessions"][data["preview_id"]]
        with Image.open(session["levels"]["medium"]["path"]) as opened:
            preview_pixels = np.asarray(opened.convert("RGB"))
        response = self.run_level(data, "medium")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()["data"]
        self.assertEqual(body["selected_level"], "medium")
        result = body["result"]
        self.assertEqual(result["result_action"], "REVIEW_REQUIRED")
        self.assertEqual(result["output_selected"], "REVIEW_CANDIDATE")
        self.assertEqual(result["delivery_acceptance_authority"], "HUMAN_CONFIRMED_REVIEW")
        self.assertEqual(result["result_review_status"], "confirmed")
        self.assertTrue(result["delivery_eligible"])
        self.assertEqual(body["review"]["status"], "confirmed")
        self.assertEqual(body["ui"]["level_pick"]["label"], "中")
        output = Path(body["ui"]["output_path"])
        self.assertEqual(self.color_dir_files(), [output])
        self.assertEqual(sha256(output), result["output_sha256"])
        with Image.open(output) as opened:
            self.assertEqual(opened.format, "PNG")
            self.assertTrue(opened.info.get("icc_profile"))
            self.assertTrue(np.array_equal(np.asarray(opened.convert("RGB")), preview_pixels))
        self.assertEqual(sha256(source_path), source_sha)
        record = self.registry[body["task"]["task_id"]]
        self.assertEqual(record["operation_mode"], "LEVEL_PICK_COLOR_CORRECTION")
        self.assertEqual(record["status"], "completed")

        items = self.client.get("/api/output-center/items").json()["data"]["items"]
        item = next(entry for entry in items if entry["task_id"] == body["task"]["task_id"])
        self.assertTrue(item["delivery_eligible"])
        preflight = self.client.post("/api/smart-delivery/preflight", json={"item_ids": [item["id"]], "rules": {}})
        self.assertEqual(preflight.status_code, 200, preflight.text)
        self.assertTrue(preflight.json()["data"]["ready"], preflight.json()["data"])
        events = [event["event"] for event in self.events]
        self.assertIn("RESULT_CONFIRMED", events)

    def test_preview_cannot_be_used_twice(self):
        data = self.preview(self.intake())
        self.assertEqual(self.run_level(data, "light").status_code, 200)
        again = self.run_level(data, "strong")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()["detail"]["code"], "LEVEL_PREVIEW_ALREADY_USED")
        self.assertEqual(len(self.color_dir_files()), 1)

    def test_original_selection_writes_nothing_and_is_logged(self):
        data = self.preview(self.intake())
        response = self.run_level(data, "original")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()["data"]
        self.assertEqual(body["selected_level"], "original")
        self.assertIsNone(body["task"])
        self.assertEqual(self.color_dir_files(), [])
        self.assertEqual(len(self.registry), 0)
        self.assertIn("COLOR_LEVEL_PICK_ORIGINAL_SELECTED", [event["event"] for event in self.events])

    def test_invalid_requests_are_rejected(self):
        data = self.preview(self.intake())
        cases = (
            ({"preview_id": data["preview_id"], "level": "extreme"}, 400, "LEVEL_PICK_UNKNOWN_LEVEL"),
            ({"preview_id": data["preview_id"], "level": "medium", "strength": 0.9}, 400, "LEVEL_RUN_REQUEST_INVALID"),
            ({"preview_id": "missing", "level": "medium"}, 404, "LEVEL_PREVIEW_NOT_FOUND"),
        )
        for payload, status, code in cases:
            response = self.client.post("/api/color-correction/level-run", json=payload)
            self.assertEqual(response.status_code, status, payload)
            self.assertEqual(response.json()["detail"]["code"], code)
        bad = self.client.post("/api/color-correction/level-preview", json={"source_token": "missing"})
        self.assertEqual(bad.status_code, 404)

    def test_used_previews_are_deleted_and_stale_leftovers_pruned(self):
        data = self.preview(self.intake())
        directory = Path(self.state["color_level_preview_sessions"][data["preview_id"]]["directory"])
        self.assertTrue(directory.is_dir())
        self.assertEqual(self.run_level(data, "medium").status_code, 200)
        self.assertFalse(directory.exists())
        self.assertEqual(self.client.get(data["levels"][2]["preview_url"]).status_code, 404)
        original = self.preview(self.intake())
        original_dir = Path(self.state["color_level_preview_sessions"][original["preview_id"]]["directory"])
        self.assertEqual(self.run_level(original, "original").status_code, 200)
        self.assertFalse(original_dir.exists())
        # A directory left by an earlier process is removed once it is older than a preview lifetime.
        leftover = self.cache / "color-level-preview" / "preview_leftover"
        leftover.mkdir(parents=True)
        (leftover / "light.png").write_bytes(b"x")
        fresh = self.cache / "color-level-preview" / "preview_fresh"
        fresh.mkdir()
        old_time = self.now - 2 * 60 * 60
        import os
        os.utime(leftover, (old_time, old_time))
        os.utime(fresh, (self.now, self.now))
        self.preview(self.intake())
        self.assertFalse(leftover.exists())
        self.assertTrue(fresh.exists())
        unrelated = self.cache / "image-compression-intake"
        self.assertTrue(unrelated.is_dir())

    def test_expired_preview_is_rejected(self):
        data = self.preview(self.intake())
        self.state["color_level_preview_sessions"][data["preview_id"]]["expires_at"] = self.now - 1
        response = self.run_level(data, "medium")
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["detail"]["code"], "LEVEL_PREVIEW_EXPIRED")

    def test_restart_invalidates_previews(self):
        data = self.preview(self.intake())
        self.client.close()
        self.client, self.state = self.make_app()
        response = self.run_level(data, "medium")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "LEVEL_PREVIEW_NOT_FOUND")
        self.assertEqual(self.color_dir_files(), [])

    def test_source_change_after_preview_is_rejected(self):
        source = self.intake()
        data = self.preview(source)
        Path(self.state["token_registry"][source["source_token"]]["path"]).write_bytes(b"changed")
        response = self.run_level(data, "medium")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "SOURCE_IDENTITY_CHANGED")

    def test_result_that_does_not_match_the_preview_is_blocked(self):
        data = self.preview(self.intake())
        session = self.state["color_level_preview_sessions"][data["preview_id"]]
        session["levels"]["medium"]["pixel_sha256"] = "0" * 64
        response = self.run_level(data, "medium")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["data"]["task"]["status"], "failed")
        self.assertIn("不一致", response.json()["message"])
        self.assertEqual(self.color_dir_files(), [])
        self.assertIsNone(session["used_by_task_id"])

    def test_rgba_and_jpeg_sources(self):
        rgba = self.preview(self.intake(cast_scene(alpha=True), name="alpha.png"))
        response = self.run_level(rgba, "strong")
        self.assertEqual(response.status_code, 200, response.text)
        with Image.open(response.json()["data"]["ui"]["output_path"]) as opened:
            self.assertEqual(opened.mode, "RGBA")
            out = np.asarray(opened)
        source = cast_scene(alpha=True)
        self.assertTrue(np.array_equal(out[..., 3], source[..., 3]))
        self.assertTrue(np.array_equal(out[source[..., 3] == 0], source[source[..., 3] == 0]))

        jpeg = self.preview(self.intake(name="cast.jpg"))
        response = self.run_level(jpeg, "medium")
        self.assertEqual(response.status_code, 200, response.text)
        output = Path(response.json()["data"]["ui"]["output_path"])
        self.assertEqual(output.suffix, ".jpg")
        with Image.open(output) as opened:
            self.assertEqual(opened.format, "JPEG")

    def test_auto_and_reference_modes_still_use_their_own_paths(self):
        source = self.intake()
        response = self.client.post("/api/color-correction/run", json={"source_token": source["source_token"], "current_task_output_root": str(self.output_root)})
        self.assertIn(response.status_code, {200, 422})
        task = response.json()["data"]["task"]
        self.assertEqual(task["operation_mode"], "AUTO_COLOR_CORRECTION")
        self.assertEqual(self.state["color_level_preview_sessions"], {})


if __name__ == "__main__":
    unittest.main()
