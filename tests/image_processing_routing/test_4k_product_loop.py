from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
import json
from pathlib import Path

from PIL import Image

from engine.image_processing_routing.four_k_v1 import (
    FOUR_K_V1_OUTPUT_PROFILE,
    FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY,
    FOUR_K_V1_ROUTE,
    inspect_4k_v1_source,
    process_4k_v1_image,
)
from engine.diagnostics.feedback_bundle import generate_feedback_bundle
from engine.output.metadata_writer import HDDE_SOFTWARE, read_hdde_metadata


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FourKProductLoopTests(unittest.TestCase):
    def test_real_executor_writes_verified_png_under_formal_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            Image.new("RGB", (160, 90), (24, 86, 164)).save(source, format="PNG")
            source_hash = sha256(source)
            events: list[tuple[str, int, str]] = []

            result = process_4k_v1_image(
                source,
                root,
                stage_callback=lambda stage, progress, message: events.append((stage, progress, message)),
            )

            output = Path(result["final_output_path"])
            self.assertTrue(output.is_file())
            self.assertEqual(output.parent, root / "输出" / "4K画质增强")
            with Image.open(output) as image:
                image.load()
                self.assertEqual(image.size, (3840, 2160))
                self.assertEqual(image.format, "PNG")
            self.assertEqual(sha256(source), source_hash)
            self.assertEqual(read_hdde_metadata(output)["software"], HDDE_SOFTWARE)
            self.assertEqual(result["task_result"]["output_sha256"], sha256(output))
            self.assertTrue(result["task_result"]["output_metadata"]["written"])
            self.assertTrue(result["source_hash_unchanged"])
            self.assertEqual(result["route"], FOUR_K_V1_ROUTE)
            self.assertEqual(result["output_profile"], FOUR_K_V1_OUTPUT_PROFILE)
            self.assertEqual(result["quality_capability_boundary"], FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY)
            stages = [stage for stage, _, _ in events]
            self.assertEqual(stages[:2], ["contract_validation", "image_processing"])
            self.assertEqual(stages[-3:], ["output_file_write", "output_verify", "completed"])
            self.assertEqual(set(stages[1:-3]), {"image_processing"})
            progresses = [progress for _, progress, _ in events]
            self.assertEqual(progresses, sorted(progresses))
            self.assertEqual((progresses[0], progresses[-1]), (20, 100))
            self.assertEqual(result["quality_conclusion"], "DETAIL_ENHANCEMENT_COMPLETED")

            first_output_hash = sha256(output)
            repeated = process_4k_v1_image(source, root)
            repeated_output = Path(repeated["final_output_path"])
            self.assertEqual(repeated_output.name, f"{output.stem}_02.png")
            self.assertTrue(repeated_output.is_file())
            self.assertEqual(sha256(output), first_output_hash)

    def test_exif_orientation_is_applied_to_pixels_before_dimension_planning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "portrait-with-orientation.jpg"
            exif = Image.Exif()
            exif[274] = 6
            exif[282] = 200
            exif[283] = 200
            exif[296] = 2
            raw = Image.new("RGB", (120, 80))
            raw.paste((240, 20, 20), (0, 0, 60, 40))
            raw.paste((20, 240, 20), (60, 0, 120, 40))
            raw.paste((20, 20, 240), (0, 40, 60, 80))
            raw.paste((240, 240, 20), (60, 40, 120, 80))
            raw.save(source, format="JPEG", quality=100, subsampling=0, exif=exif, dpi=(200, 200))
            source_hash = sha256(source)

            source_meta = inspect_4k_v1_source(source)
            result = process_4k_v1_image(source, root)

            self.assertEqual((source_meta["input_width"], source_meta["input_height"]), (80, 120))
            self.assertEqual((source_meta["target_width"], source_meta["target_height"]), (2560, 3840))
            self.assertEqual((result["output_width"], result["output_height"]), (2560, 3840))
            with Image.open(result["final_output_path"]) as output:
                output.load()
                self.assertEqual(output.size, (2560, 3840))
                self.assertEqual(output.getexif().get(274), 1)
                self.assertAlmostEqual(output.info["dpi"][0], 200, places=2)
                self.assertAlmostEqual(output.info["dpi"][1], 200, places=2)
                self.assertEqual(float(output.getexif()[282]), 200)
                self.assertEqual(float(output.getexif()[283]), 200)
                self.assertEqual(output.getexif()[296], 2)
                expected_corners = {
                    "top_left": ((output.width // 8, output.height // 8), (20, 20, 240)),
                    "top_right": ((output.width * 7 // 8, output.height // 8), (240, 20, 20)),
                    "bottom_left": ((output.width // 8, output.height * 7 // 8), (240, 240, 20)),
                    "bottom_right": (
                        (output.width * 7 // 8, output.height * 7 // 8),
                        (20, 240, 20),
                    ),
                }
                for corner, (position, expected_rgb) in expected_corners.items():
                    actual_rgb = output.getpixel(position)
                    self.assertTrue(
                        all(abs(actual - expected) <= 20 for actual, expected in zip(actual_rgb, expected_rgb)),
                        f"{corner} proves the EXIF orientation is rotated clockwise without mirroring: "
                        f"expected {expected_rgb}, got {actual_rgb}",
                    )
                self.assertEqual(
                    output.width * source_meta["input_height"],
                    output.height * source_meta["input_width"],
                )
            self.assertEqual(sha256(source), source_hash)
            self.assertTrue(result["source_hash_unchanged"])
            self.assertTrue(result["task_result"]["output_metadata"]["decoded_pixel_content_unchanged"])
            self.assertTrue(result["task_result"]["output_metadata"]["dpi_unchanged"])

    def test_already_4k_source_is_not_written_as_a_false_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "already-4k.png"
            Image.new("RGB", (3840, 4), (12, 34, 56)).save(source, format="PNG")
            source_hash = sha256(source)

            result = process_4k_v1_image(source, root)

            self.assertEqual(result["quality_conclusion"], "NO_PROCESSING_NEEDED")
            self.assertFalse(result["final_output_exists"])
            self.assertEqual(result["final_output_path"], "")
            self.assertEqual(sha256(source), source_hash)
            self.assertFalse((root / "输出" / "4K画质增强").exists())

    def test_user_feedback_bundle_is_minimal_task_scoped_and_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "输入" / "sample.png"
            output = root / "输出" / "4K画质增强" / "sample_4k.png"
            source.parent.mkdir(parents=True)
            output.parent.mkdir(parents=True)
            Image.new("RGB", (32, 18), (10, 20, 30)).save(source, format="PNG")
            Image.new("RGB", (64, 36), (10, 20, 30)).save(output, format="PNG")
            bundle = generate_feedback_bundle(
                "task_feedback_contract",
                {
                    "task_id": "task_feedback_contract",
                    "task_status": "completed",
                    "mode": "4k_v1",
                    "formal_root": str(root),
                    "input_path": str(source),
                    "task_result": {
                        "output_path": str(output),
                        "input_width": 32,
                        "input_height": 18,
                        "output_width": 64,
                        "output_height": 36,
                        "output_format": "png",
                    },
                    "stage_events": [{"stage": "completed", "progress": 100, "message": "处理完成"}],
                },
                output_dir=root / "诊断" / "反馈包",
            )

            self.assertEqual(bundle["feedback_bundle_status"], "PASS")
            bundle_path = Path(bundle["feedback_bundle_path"])
            self.assertRegex(bundle_path.name, r"^影界HDDE_问题反馈_FB-\d{8}-[0-9A-F]{12}\.zip$")
            with zipfile.ZipFile(bundle_path) as archive:
                self.assertEqual(
                    archive.namelist(),
                    ["feedback.json", "related.log", "timeline.json", "manifest.json"],
                )
                payload = json.loads(archive.read("feedback.json").decode("utf-8"))
                archive_text = "\n".join(
                    archive.read(name).decode("utf-8") for name in archive.namelist()
                )
            self.assertEqual(payload["common_context"]["task_id"], "task_feedback_contract")
            self.assertTrue(payload["output_validation"]["decodable"])
            self.assertNotIn(str(root), archive_text)
            self.assertNotIn("settings.json", archive_text)
            self.assertFalse(any(name.lower().endswith((".png", ".jpg", ".jpeg")) for name in archive.namelist()))


if __name__ == "__main__":
    unittest.main()
