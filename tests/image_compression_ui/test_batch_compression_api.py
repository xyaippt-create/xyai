"""The A05 sequence uses the actual existing intake/run/Result APIs unchanged."""
import hashlib
import io
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from tests.image_compression_ui import test_image_compression_api as api_tests


class BatchCompressionContractTests(unittest.TestCase):
    def setUp(self):
        self.api = api_tests.ImageCompressionApiStage4Tests(methodName="runTest")
        self.api.setUp()
        self.api.dirs["image_compression_output_dir"] = self.api.saved_output_root

    def tearDown(self):
        self.api.tearDown()

    def run_mixed(self, count, damaged_index=None):
        result_ids, tokens, tasks, kept, failed = [], set(), set(), 0, 0
        for index in range(count):
            stream = io.BytesIO()
            if index == 1:
                pixels = np.random.default_rng(7).integers(0, 256, (240, 320, 3), dtype=np.uint8)
                Image.fromarray(pixels).save(stream, format="JPEG", quality=45, optimize=True)
                filename, mime = "same-name.jpg", "image/jpeg"
            else:
                Image.new("RGB", (160 + index, 100), (index * 17, 111, 232)).save(stream, format="PNG", compress_level=0)
                filename, mime = "same-name.png", "image/png"
            payload = b"damaged image" if index == damaged_index else stream.getvalue()
            intake_response = self.api.client.post("/api/image-compression/intake", files={"file": (filename, payload, mime)})
            if index == damaged_index:
                self.assertGreaterEqual(intake_response.status_code, 400)
                failed += 1
                continue
            self.assertEqual(intake_response.status_code, 200, intake_response.text)
            intake = intake_response.json()["data"]
            self.assertNotIn(intake["source_token"], tokens)
            tokens.add(intake["source_token"])
            data = self.api.execute_delivery_optimization(intake)
            result, task = data["result"], data["task"]
            self.assertEqual(result["source_sha256"], hashlib.sha256(payload).hexdigest())
            self.assertNotIn(task["task_id"], tasks)
            tasks.add(task["task_id"])
            self.assertLessEqual(result["public_output_count"], 1)
            if result["winner_scheme_id"] == "keep_original":
                kept += 1
                self.assertFalse(task["result_id"])
                self.assertFalse(result["output_created"])
                self.assertEqual(result["public_output_count"], 0)
            else:
                self.assertTrue(task["result_id"])
                result_ids.append(task["result_id"])
                self.assertEqual(result["public_output_count"], 1)
                self.assertEqual(len(result["candidates"]), 1)
                self.assertEqual(result["winner"]["quality_gate"]["status"], "PASS")
                output = Path(result["output_path"])
                self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), result["output_sha256"])
                with Image.open(output) as image:
                    image.load()
                    self.assertEqual(image.size, (160 + index, 100))
        self.assertEqual(len(result_ids) + kept + failed, count)
        self.assertGreater(kept, 0)
        self.assertGreater(len(result_ids), 0)
        self.assertEqual(len(set(result_ids)), len(result_ids))
        center = self.api.client.get("/api/output-center/items").json()["data"]["items"]
        self.assertEqual({item["result_id"] for item in center}, set(result_ids))
        self.assertEqual(len(center), len(result_ids))
        formal_files = list(self.api.saved_output_root.rglob("*.png")) + list(self.api.saved_output_root.rglob("*.jpg"))
        self.assertEqual(len(formal_files), len(result_ids))

    def test_three_mixed_sources(self):
        self.run_mixed(3)

    def test_ten_mixed_sources(self):
        self.run_mixed(10)

    def test_damaged_source_does_not_prevent_later_result(self):
        self.run_mixed(4, damaged_index=2)
