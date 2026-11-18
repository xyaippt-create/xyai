"""Exercise the print endpoint with encoded image inputs and a disk registry."""

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import hashlib
import json
import tempfile
import unittest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image, ImageCms, ImageDraw

from backend.print_output_api import register_print_output_routes
from engine.storage.result_reuse import result_lineage
from engine.storage.shared_task_registry import SharedTaskRegistry


def client_for(root, *, ready=True):
    def directories():
        if not ready:
            raise HTTPException(503, "正式目录未就绪")
        return {"app_data_root": root, "normal_input_dir": root / "输入", "output_root": root / "输出"}

    app = FastAPI()
    registry = SharedTaskRegistry(root)
    register_print_output_routes(app, user_dirs_provider=directories, registry=registry)
    return TestClient(app), registry


def encoded(image, fmt="PNG", **options):
    stream = BytesIO()
    image.save(stream, format=fmt, **options)
    return stream.getvalue()


def submit(client, data, key=None, **fields):
    form = {"width": 8, "height": 4, "ppi": 150, "request_id": str(key or uuid4()), **fields}
    return client.post("/api/print-output/render", data=form, files={"file": ("测试原图.png", data)})


class PrintOutputTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_transparent_profiled_png_and_restart_replay(self):
        tmp_path = self.root
        client, registry = client_for(tmp_path)
        source = Image.new("RGBA", (4, 2), (32, 128, 72, 255))
        source.putpixel((0, 0), (20, 24, 17, 0))
        icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        data = encoded(source, icc_profile=icc, dpi=(72, 72))
        key = uuid4()
        response = submit(client, data, key)
        assert response.status_code == 200, response.text
        result = response.json()
        task = registry[result["task_id"]]
        path = Path(task["result_file"])
        assert path.parent == tmp_path / "输出" / "喷绘出图"
        assert Path(task["source_path"]).read_bytes() == data
        with Image.open(path) as output:
            assert output.info["icc_profile"] == icc
            assert all(abs(d - 150) < 0.01271 for d in output.info["dpi"])
            # A 2x colour enlargement goes through the 4K reconstruction; alpha is never generated.
            assert result["upscale"]["method"] == "SR_FUSION"
            assert output.getchannel("A").tobytes() == source.getchannel("A").resize((8, 4), Image.Resampling.LANCZOS).tobytes()
            assert max(abs(a - b) for a, b in zip(output.convert("RGB").getpixel((7, 3)), (32, 128, 72))) <= 3
        restarted, _ = client_for(tmp_path)
        assert submit(restarted, data, key).json() == result
        assert submit(restarted, data, key, ppi=100).status_code == 409
        assert len(list(path.parent.glob("*.png"))) == 1
        another = submit(restarted, data).json()
        assert another["filename"].endswith("_02.png")
        assert another["result_id"] != result["result_id"]


    def test_existing_result_is_bound_to_preview_render_and_retry(self):
        client, registry = client_for(self.root)
        source = Image.new("RGB", (100, 80), "white")
        ImageDraw.Draw(source).rectangle((12, 12, 26, 30), fill="black")
        parent = submit(client, encoded(source), width=100, height=80).json()
        parent_path = Path(registry[parent["task_id"]]["result_file"])
        original = parent_path.read_bytes()
        recipe = json.dumps({"version": 1, "paper": "#ffffff", "subject": [],
                             "regions": [{"kind": "ink", "rect": [.08, .10, .32, .45], "ink": "#000000"}]})
        form = {"result_id": parent["result_id"], "layers": recipe}
        preview = client.post("/api/print-output/layers/preview", data=form)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["source_sha256"], hashlib.sha256(original).hexdigest())
        form.update(width=200, height=160, ppi=150, request_id=str(uuid4()))
        response = client.post("/api/print-output/render", data=form)
        self.assertEqual(response.status_code, 200, response.text)
        child = response.json()
        self.assertNotEqual(child["result_id"], parent["result_id"])
        restarted, durable = client_for(self.root)
        self.assertEqual(restarted.post("/api/print-output/render", data=form).json(), child)
        chain = result_lineage(durable, child["result_id"])["items"]
        self.assertEqual([r["result_id"] for r in chain], [parent["result_id"], child["result_id"]])
        path = Path(durable[child["task_id"]]["result_file"])
        self.assertNotEqual(path, parent_path)
        with Image.open(path) as printed:
            printed.load()
            self.assertEqual(printed.size, (200, 160))
        self.assertEqual(parent_path.read_bytes(), original)
        self.assertEqual(client.post("/api/print-output/render", data=form,
                                     files={"file": ("duplicate.png", original)}).status_code, 422)
        parent_path.write_bytes(encoded(Image.new("RGB", (100, 80), "blue")))
        form.update(request_id=str(uuid4()))
        for endpoint in ("layers/preview", "render"):
            denied = restarted.post("/api/print-output/" + endpoint, data=form)
            self.assertEqual(denied.status_code, 409)
            self.assertEqual(denied.json()["detail"]["code"], "RESULT_REUSE_INTEGRITY_MISMATCH")
        self.assertEqual(len(list(path.parent.glob("*.png"))), 2)

    def test_interrupted_publication_recovers_original_file(self):
        tmp_path = self.root
        client, registry = client_for(tmp_path)
        key = uuid4()
        data = encoded(Image.new("RGB", (4, 2), "orange"))
        completed = submit(client, data, key).json()
        task_id = completed["task_id"]
        # Recreate the durable state between publishing the file and committing the Result.
        intent = dict(registry[task_id], status="pending", record_kind="print_publication")
        for field in ("result_id", "result_file", "output_path", "print_response", "task_status", "delivery_eligible"):
            intent.pop(field)
        registry[task_id] = intent
        restarted, durable = client_for(tmp_path)
        assert submit(restarted, data, key).json() == completed
        assert durable[task_id]["record_kind"] == "task"
        assert len(list((tmp_path / "输出" / "喷绘出图").glob("*.png"))) == 1


    def test_invalid_plan_has_no_output(self):
        tmp_path = self.root
        client, registry = client_for(tmp_path)
        for fields in ({"width": 4, "height": 12}, {"width": 32769}, {"width": 10000, "height": 10000}, {"ppi": 0}):
            response = submit(client, encoded(Image.new("RGB", (4, 2))), **fields)
            assert response.status_code == 422
            assert not registry and not (tmp_path / "输出").exists()

    def test_interrupted_request_keeps_its_filename(self):
        client, registry = client_for(self.root)
        first_key = uuid4()
        data = encoded(Image.new("RGB", (4, 2), "red"))
        first = submit(client, data, first_key).json()
        intent = registry[first["task_id"]].copy()
        pending_target = Path(intent["print_target"])
        pending_target.unlink()  # Only this test's own file in its isolated directory.
        registry[first["task_id"]] = {**intent, "record_kind": "print_publication", "status": "pending"}
        second = submit(client, data).json()
        assert second["filename"].endswith("_02.png")
        assert not pending_target.exists()
        assert submit(client, data, first_key).json() == first
        assert pending_target.exists()


    def test_bad_image_and_unready_directory(self):
        tmp_path = self.root
        client, registry = client_for(tmp_path)
        assert submit(client, b"invalid").status_code == 422
        assert submit(client, encoded(Image.new("I;16", (4, 2)))).status_code == 422
        assert not registry and not (tmp_path / "输出").exists()
        blocked, _ = client_for(tmp_path / "other", ready=False)
        assert submit(blocked, encoded(Image.new("RGB", (4, 2)))).status_code == 503
        assert not (tmp_path / "other" / "输入").exists()

    def test_layer_preview_and_replay_keep_the_counter_and_transform_the_outline(self):
        client, registry = client_for(self.root)
        source = Image.new("RGB", (100, 80), "white")
        draw = ImageDraw.Draw(source)
        draw.rectangle((12, 12, 26, 30), fill="black")
        draw.rectangle((16, 16, 22, 26), fill="white")
        data = encoded(source)
        region = dict(kind="ink", rect=[.08, .10, .32, .45], ink="#000000", dx=.40, scale=1.25)
        plan = dict(version=1, paper="#ffffff", subject=[], regions=[region])
        layers = json.dumps(plan)
        preview = client.post("/api/print-output/layers/preview", data={"layers": layers},
                              files={"file": ("poster.png", data)})
        assert preview.status_code == 200, preview.text
        assert preview.json()["source_sha256"] == hashlib.sha256(data).hexdigest()
        assert preview.json()["contours"] == 2 and not registry
        key = uuid4()
        result = submit(client, data, key, width=400, height=400, layers=layers)
        assert result.status_code == 200, result.text
        assert result.json()["layers"]["base_upscale"]["method"] == "SR_FUSION"
        assert preview.json()["base_upscale"]["method"] == "LANCZOS"
        with Image.open(registry[result.json()["task_id"]]["result_file"]) as out:
            assert out.info["srgb"] == 0 and abs(out.info["dpi"][0] - 150) < .013
            assert out.getpixel((50, 100)) == (255, 255, 255)  # erased former location
            assert out.getpixel((215, 130)) == (0, 0, 0)
            assert out.getpixel((247, 137)) == (255, 255, 255)  # counter
            assert out.getpixel((215, 10)) == (255, 255, 255)  # centered letterbox
        assert submit(client, data, key, width=400, height=400, layers=layers).json() == result.json()
        region["dx"] = .10
        assert submit(client, data, key, width=400, height=400, layers=json.dumps(plan)).status_code == 409

    def test_texture_and_subject_mask_are_clipped_to_the_requested_regions(self):
        import numpy as np
        from engine.print_layers import Recipe, compose, subject_mask

        rgb = np.full((60, 60, 3), 255, dtype=np.uint8)
        rgb[6:26, 6:26] = [174, 23, 30]
        rgb[13:19, 13:19] = 255
        region = dict(kind="texture", rect=[0, 0, .5, .5], ink="#ae171e")
        plan = dict(version=1, paper="#ffffff", regions=[region], subject=[])
        recipe = Recipe.read(json.dumps(plan))
        a, _ = compose(rgb, recipe, (240, 240))
        b, _ = compose(rgb, recipe, (240, 240))
        assert a.tobytes() == b.tobytes()
        assert a.getpixel((200, 40)) == a.getpixel((62, 62)) == (255, 255, 255)
        assert len(set(a.crop((30, 30, 45, 45)).getdata())) > 1
        plan.update(subject=[[.1, .1], [.9, .1], [.9, .9], [.1, .9]], snap=False,
                    cutouts=[[[.4, .4], [.6, .4], [.6, .6], [.4, .6]]])
        mask = subject_mask(rgb, Recipe.read(json.dumps(plan)))
        assert mask[10, 12] == 255 and mask[30, 30] == mask[2, 2] == 0

    def test_invalid_layers_are_rejected_without_creating_a_result(self):
        client, registry = client_for(self.root)
        data = encoded(Image.new("RGB", (40, 40), "white"))
        plan = dict(version=1, paper="#ffffff", regions=[], subject=[])
        region = dict(kind="ink", rect=[0, 0, 1, 1], ink="#ff3300")
        for changes in ({}, {"subject": [[0, 0]]}, {"regions": [{**region, "scale": -1}]},
                        {"regions": [region]}, {"cutouts": [[[0, 0], [.5, 0], [0, .5]]]}):
            assert submit(client, data, layers=json.dumps({**plan, **changes})).status_code == 422
        assert not registry and not (self.root / "输出").exists()


    def test_keyed_transparency_and_webp(self):
        tmp_path = self.root
        client, registry = client_for(tmp_path)
        gray = Image.new("L", (4, 2), 100)
        gray.putpixel((0, 0), 0)
        result = submit(client, encoded(gray, transparency=0), width=4, height=2).json()
        with Image.open(registry[result["task_id"]]["result_file"]) as output:
            assert output.mode == "LA" and output.getchannel("A").getextrema() == (0, 255)
        webp = encoded(Image.new("RGBA", (4, 2), (12, 20, 40, 128)), "WEBP", lossless=True)
        result = submit(client, webp, width=4, height=2).json()
        with Image.open(registry[result["task_id"]]["result_file"]) as output:
            assert output.mode == "RGBA" and output.getpixel((0, 0)) == (12, 20, 40, 128)


class PrintUpscalePlanTests(unittest.TestCase):
    def test_reconstruction_is_chosen_by_scale_source_size_and_colour(self):
        from engine.print_upscale import plan_print_upscale

        eight_k = plan_print_upscale(1672, 941, 7680, 4322)
        assert eight_k["method"] == "SR_FUSION" and eight_k["residual_scale"] == 1 and eight_k["detail_scale"] == 3
        banner = plan_print_upscale(1672, 941, 11812, 6648)
        assert banner["method"] == "SR_FUSION" and 1.35 < banner["residual_scale"] < 1.45
        assert plan_print_upscale(1672, 941, 1900, 1069)["reason"] == "SMALL_SCALE"
        assert plan_print_upscale(3000, 2000, 7680, 5120)["reason"] == "SOURCE_TOO_LARGE"
        assert plan_print_upscale(1672, 941, 7680, 4322, color=False)["reason"] == "GRAYSCALE"
