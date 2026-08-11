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
    process_4k_v1_image,
)
from engine.diagnostics.feedback_bundle import generate_feedback_bundle


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
            self.assertEqual(output.parent, root / "输出" / "4K高清增强")
            with Image.open(output) as image:
                image.load()
                self.assertEqual(image.size, (3840, 2160))
                self.assertEqual(image.format, "PNG")
            self.assertEqual(sha256(source), source_hash)
            self.assertTrue(result["source_hash_unchanged"])
            self.assertEqual(result["route"], FOUR_K_V1_ROUTE)
            self.assertEqual(result["output_profile"], FOUR_K_V1_OUTPUT_PROFILE)
            self.assertEqual(result["quality_capability_boundary"], FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY)
            self.assertEqual(
                [stage for stage, _, _ in events],
                ["contract_validation", "image_processing", "output_file_write", "output_verify", "completed"],
            )
            self.assertEqual([progress for _, progress, _ in events], [20, 45, 72, 90, 100])

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
            self.assertFalse((root / "输出" / "4K高清增强").exists())

    def test_user_feedback_bundle_is_minimal_task_scoped_and_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "输入" / "sample.png"
            output = root / "输出" / "4K高清增强" / "sample_4k.png"
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
            self.assertRegex(bundle_path.name, r"^影界HDDE_问题反馈_task_feedback_contract_\d{8}_\d{6}\.zip$")
            with zipfile.ZipFile(bundle_path) as archive:
                self.assertEqual(
                    sorted(archive.namelist()),
                    ["feedback_report.json", "feedback_report.txt", "task_log.txt"],
                )
                payload = json.loads(archive.read("feedback_report.json").decode("utf-8"))
                archive_text = "\n".join(
                    archive.read(name).decode("utf-8") for name in archive.namelist()
                )
            self.assertEqual(payload["task"]["task_id"], "task_feedback_contract")
            self.assertTrue(payload["output_validation"]["decodable"])
            self.assertNotIn(str(root), archive_text)
            self.assertNotIn("settings.json", archive_text)
            self.assertFalse(any(name.lower().endswith((".png", ".jpg", ".jpeg")) for name in archive.namelist()))


if __name__ == "__main__":
    unittest.main()
