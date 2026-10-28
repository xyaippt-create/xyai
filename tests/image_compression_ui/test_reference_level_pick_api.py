"""S66-A reference level pick: target + reference preview, user selection, formal Result."""
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
from engine.color_correction.level_pick import LEVELS, _adaptation_matrix, _gamut_pull, _to_linear, _to_srgb, delta_e2000
from engine.color_correction.reference_level_pick import plan_reference, render_reference_level
from engine.storage.shared_task_registry import SharedTaskRegistry
from main import DEFAULT_TMP_DIR_NAME


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clean_scene(size=(240, 180)) -> np.ndarray:
    """Grey wall and floor with shadows, a white panel and a brand-red block."""

    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    base = 8 + 180 * (xx / (w - 1)) + 40 * (yy / (h - 1))
    rgb = np.stack([base, base, base], -1)
    rgb[20:60, 20:80] = (205, 30, 35)
    rgb[-40:, :50] = 6
    rgb[-40:, -70:] = 238
    return np.clip(rgb, 0, 255).astype(np.uint8)


def with_cast(rgb: np.ndarray, ab=(0.0, 14.0)) -> np.ndarray:
    lin = _to_linear(rgb.astype(np.float32) / 255.0) @ _adaptation_matrix((0.0, 0.0), ab).T
    return (np.clip(_to_srgb(_gamut_pull(lin)), 0, 1) * 255 + 0.5).astype(np.uint8)


class ReferenceLevelPickAlgorithmTests(unittest.TestCase):
    def test_strong_level_removes_most_of_a_known_cast(self):
        clean = clean_scene()
        target = with_cast(clean)
        plan = plan_reference(target, clean)
        self.assertTrue(plan.usable)
        self.assertIn("偏黄", plan.description["summary"])
        before = float(delta_e2000(target, clean).mean())
        after = [float(delta_e2000(render_reference_level(target, plan, name), clean).mean()) for name in LEVELS]
        self.assertGreater(after[0], after[1])
        self.assertGreater(after[1], after[2])
        self.assertLess(after[2], before * 0.4)

    def test_reference_equal_to_target_changes_almost_nothing(self):
        clean = clean_scene()
        plan = plan_reference(clean, clean)
        out = render_reference_level(clean, plan, "strong")
        self.assertLess(float(delta_e2000(out, clean).mean()), 0.5)
        self.assertEqual(plan.to_record()["recommended_level"], "original")

    def test_reference_without_neutral_pixels_is_unusable(self):
        clean = clean_scene()
        red = np.zeros_like(clean)
        red[:] = (210, 20, 30)
        plan = plan_reference(with_cast(clean), red)
        self.assertFalse(plan.usable)
        target = with_cast(clean)
        self.assertTrue(np.array_equal(render_reference_level(target, plan, "strong"), target))

    def test_alpha_and_hidden_rgb_are_preserved(self):
        clean = clean_scene()
        target = np.dstack((with_cast(clean), np.full(clean.shape[:2], 255, np.uint8)))
        target[:, :20, 3] = 0
        target[:, :20, :3] = (0, 255, 0)
        out = render_reference_level(target, plan_reference(target, clean), "strong")
        self.assertTrue(np.array_equal(out[..., 3], target[..., 3]))
        self.assertTrue(np.array_equal(out[target[..., 3] == 0], target[target[..., 3] == 0]))


class ReferenceLevelPickApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.formal = Path(self.temporary.name) / "formal"
        self.cache = self.formal / DEFAULT_TMP_DIR_NAME
        self.cache.mkdir(parents=True)
        self.output_root = self.formal / "输出"
        self.now = 1_800_000_000.0
        self.events = []
        self.registry = SharedTaskRegistry(self.formal)
        app = FastAPI()
        self.state = register_image_compression_routes(
            app, user_dirs_provider=lambda: {"normal_output_dir": self.output_root, "tmp_dir": self.cache},
            shared_task_registry=self.registry, now_provider=lambda: self.now,
            output_settings_provider=lambda: {"built_in_default_root": str(self.formal), "saved_default_root": str(self.formal)},
            output_dir_validator=lambda v: {"valid": True, "writable": True, "normalized_path": str(Path(v).resolve())},
            folder_opener=lambda v: None,
            runtime_event_logger=lambda event, **fields: self.events.append({"event": event, **fields}),
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def intake(self, pixels, name):
        stream = io.BytesIO()
        Image.fromarray(pixels).save(stream, format="PNG", icc_profile=srgb_profile_bytes())
        response = self.client.post("/api/image-compression/intake", files={"file": (name, stream.getvalue(), "image/png")})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def preview(self, target, reference, expected=200):
        response = self.client.post("/api/color-correction/level-preview", json={
            "source_token": target["source_token"], "reference_source_token": reference["source_token"]})
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()["data"] if expected == 200 else response.json()

    def run_level(self, preview, level):
        return self.client.post("/api/color-correction/level-run", json={
            "preview_id": preview["preview_id"], "level": level, "current_task_output_root": str(self.output_root)})

    def color_files(self):
        directory = self.output_root / "颜色校正"
        return sorted(directory.iterdir()) if directory.is_dir() else []

    def test_capabilities_announce_reference_level_pick(self):
        data = self.client.get("/api/color-correction/capabilities").json()["data"]
        self.assertTrue(data["reference_level_pick_available"])
        self.assertTrue(data["level_pick_available"])
        self.assertEqual(data["reference_endpoint"], "/api/color-correction/reference-run")

    def test_reference_preview_measures_shift_and_offers_levels(self):
        clean = clean_scene()
        target, reference = self.intake(with_cast(clean), "target.png"), self.intake(clean, "reference.png")
        data = self.preview(target, reference)
        self.assertIn("偏黄", data["measurement"]["summary"])
        self.assertEqual(data["measurement"]["recommended_level"], "medium")
        self.assertIn("同一系列", data["measurement"]["notice"])
        self.assertTrue(all(item["selectable"] for item in data["levels"]))
        self.assertEqual(self.client.get(data["reference_preview_url"]).status_code, 200)
        self.assertEqual(self.color_files(), [])

    def test_selected_level_is_human_confirmed_and_records_the_reference(self):
        clean = clean_scene()
        target, reference = self.intake(with_cast(clean), "target.png"), self.intake(clean, "reference.png")
        reference_path = Path(self.state["token_registry"][reference["source_token"]]["path"])
        reference_sha = sha256(reference_path)
        data = self.preview(target, reference)
        session = self.state["color_level_preview_sessions"][data["preview_id"]]
        with Image.open(session["levels"]["strong"]["path"]) as opened:
            preview_pixels = np.asarray(opened.convert("RGB"))
        response = self.run_level(data, "strong")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()["data"]
        result = body["result"]
        self.assertEqual(body["task"]["operation_mode"], "REFERENCE_LEVEL_PICK_COLOR_CORRECTION")
        self.assertEqual(result["delivery_acceptance_authority"], "HUMAN_CONFIRMED_REVIEW")
        self.assertEqual(result["result_action"], "REVIEW_REQUIRED")
        self.assertEqual(result["parameters"]["reference_sha256"], reference_sha)
        self.assertEqual(result["analysis"]["REFERENCE_PROVENANCE"]["reference_source_fingerprint"], reference_sha)
        self.assertEqual(body["ui"]["level_pick"]["label"], "强")
        self.assertIn("偏黄", body["ui"]["level_pick"]["measurement"]["summary"])
        output = Path(body["ui"]["output_path"])
        self.assertEqual(self.color_files(), [output])
        with Image.open(output) as opened:
            produced = np.asarray(opened.convert("RGB"))
        self.assertTrue(np.array_equal(produced, preview_pixels))
        self.assertLess(float(delta_e2000(produced, clean).mean()), float(delta_e2000(with_cast(clean), clean).mean()) * 0.4)
        # the reference is read only: unchanged, never an output, never an output-centre item
        self.assertEqual(sha256(reference_path), reference_sha)
        items = self.client.get("/api/output-center/items").json()["data"]["items"]
        self.assertEqual([item["task_id"] for item in items], [body["task"]["task_id"]])
        self.assertTrue(items[0]["delivery_eligible"])
        preflight = self.client.post("/api/smart-delivery/preflight", json={"item_ids": [items[0]["id"]], "rules": {}})
        self.assertTrue(preflight.json()["data"]["ready"], preflight.text)
        self.assertFalse(Path(session["directory"]).exists())

    def test_unusable_reference_offers_only_the_original(self):
        clean = clean_scene()
        red = np.zeros_like(clean)
        red[:] = (210, 20, 30)
        target, reference = self.intake(with_cast(clean), "target.png"), self.intake(red, "red.png")
        data = self.preview(target, reference)
        self.assertEqual(data["measurement"]["category"], "REFERENCE_UNUSABLE")
        self.assertIn("不适合", data["measurement"]["notice"])
        self.assertEqual([item["selectable"] for item in data["levels"]], [True, False, False, False])
        refused = self.run_level(data, "medium")
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()["detail"]["code"], "LEVEL_NOT_SELECTABLE")
        self.assertEqual(self.run_level(data, "original").status_code, 200)
        self.assertEqual(self.color_files(), [])

    def test_reference_changed_after_preview_is_rejected(self):
        clean = clean_scene()
        target, reference = self.intake(with_cast(clean), "target.png"), self.intake(clean, "reference.png")
        data = self.preview(target, reference)
        Path(self.state["token_registry"][reference["source_token"]]["path"]).write_bytes(b"changed")
        response = self.run_level(data, "medium")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "REFERENCE_IDENTITY_CHANGED")
        self.assertEqual(self.color_files(), [])

    def test_invalid_reference_token_and_reuse_are_rejected(self):
        clean = clean_scene()
        target = self.intake(with_cast(clean), "target.png")
        bad = self.client.post("/api/color-correction/level-preview", json={"source_token": target["source_token"], "reference_source_token": "missing"})
        self.assertEqual(bad.status_code, 404)
        self.assertEqual(bad.json()["detail"]["code"], "REFERENCE_TOKEN_INVALID")
        data = self.preview(target, self.intake(clean, "reference.png"))
        self.assertEqual(self.run_level(data, "light").status_code, 200)
        again = self.run_level(data, "strong")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()["detail"]["code"], "LEVEL_PREVIEW_ALREADY_USED")

    def test_old_reference_run_endpoint_is_unchanged(self):
        clean = clean_scene()
        target, reference = self.intake(with_cast(clean), "target.png"), self.intake(clean, "reference.png")
        response = self.client.post("/api/color-correction/reference-run", json={
            "target_source_token": target["source_token"], "reference_source_token": reference["source_token"]})
        self.assertIn(response.status_code, {200, 422})
        self.assertEqual(response.json()["data"]["task"]["operation_mode"], "REFERENCE_COLOR_CORRECTION")
        self.assertEqual(self.state["color_level_preview_sessions"], {})


if __name__ == "__main__":
    unittest.main()
