from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from engine.diagnostics.feedback_bundle import generate_feedback_bundle
from engine.diagnostics.feedback_context import build_feedback_context
from engine.image_compression.contracts import ImageCompressionResult


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_image(path: Path, image_format: str, *, color=(42, 92, 168, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "RGBA" if image_format in {"PNG", "WEBP"} else "RGB"
    selected_color = color if mode == "RGBA" else color[:3]
    Image.new(mode, (48, 32), selected_color).save(path, format=image_format, quality=88)


def _compression_task(root: Path, source_format: str, output_format: str, *, keep_original: bool = False) -> dict:
    extensions = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
    source_path = root / "输入" / f"source{extensions[source_format]}"
    output_path = root / "输出" / f"result{extensions[output_format]}"
    _write_image(source_path, source_format)
    if not keep_original:
        _write_image(output_path, output_format, color=(41, 91, 167, 255))
    source_size = source_path.stat().st_size
    output_size = source_size if keep_original else output_path.stat().st_size
    source_sha = _sha256(source_path)
    output_sha = source_sha if keep_original else _sha256(output_path)
    task_id = f"compression_{source_format.lower()}_{output_format.lower()}"
    result_id = "" if keep_original else f"compression_result_{source_format.lower()}_{output_format.lower()}"
    result = ImageCompressionResult(
        task_id=task_id,
        operation_mode="DELIVERY_OPTIMIZATION",
        technical_status="TARGET_MET",
        visual_review_status="NOT_REQUIRED",
        delivery_gate_status="DELIVERY_READY" if not keep_original else "NO_OUTPUT_REQUIRED",
        delivery_eligible=not keep_original,
        source_path=str(source_path),
        source_sha256=source_sha,
        source_format=source_format,
        source_dimensions={"width": 48, "height": 32},
        source_size_bytes=source_size,
        output_created=not keep_original,
        output_path=None if keep_original else str(output_path),
        output_sha256=output_sha,
        output_format=output_format,
        output_dimensions={"width": 48, "height": 32},
        output_size_bytes=output_size,
        size_reduction_bytes=source_size - output_size,
        size_reduction_ratio=(source_size - output_size) / source_size,
        alpha_details={"alpha_present": source_format in {"PNG", "WEBP"}},
        validation_status="PASS",
    )
    task_result = None if keep_original else {
        "task_id": task_id,
        "result_id": result_id,
        "feature_key": "image_compression",
        "module_id": "hdde.image.compression",
        "operation_id": f"OP-{task_id}",
        "trace_id": f"TRACE-{task_id}",
        "source_path": str(source_path),
        "output_path": str(output_path),
        "source_sha256": source_sha,
        "output_sha256": output_sha,
    }
    return {
        "task_id": task_id,
        "feature_key": "image_compression",
        "task_family": "image_compression",
        "module_id": "hdde.image.compression",
        "operation_id": f"OP-{task_id}",
        "trace_id": f"TRACE-{task_id}",
        "status": "completed",
        "task_status": "completed",
        "operation_mode": "DELIVERY_OPTIMIZATION",
        "target_format": "PRESERVE_FORMAT" if source_format == output_format else output_format,
        "source_has_real_transparency": source_format in {"PNG", "WEBP"},
        "winner_scheme_id": "KEEP_ORIGINAL" if keep_original else f"{output_format}_WINNER",
        "winner_public": {"source_selected": keep_original},
        "result_id": result_id,
        "result_file": "" if keep_original else str(output_path),
        "source_path": source_path,
        "output_path": None if keep_original else output_path,
        "original_filename": source_path.name,
        "source_metadata": {
            "filename": source_path.name,
            "format": source_format,
            "width": 48,
            "height": 32,
            "size_bytes": source_size,
            "sha256": source_sha,
        },
        "result": result,
        "task_result": task_result,
        "lifecycle": [{
            "task_id": task_id,
            "status": "completed",
            "event": "PROCESS_SUCCEEDED",
            "recorded_at": "2026-09-14T10:00:00+08:00",
        }],
    }


def _bundle(root: Path, task: dict, *, source: bool = False, result: bool = False):
    context = build_feedback_context(task, source_feature="image_compression", route="/compression")
    generated = generate_feedback_bundle(
        task["task_id"],
        task,
        output_dir=root / "反馈包",
        context_snapshot=context,
        evidence_consent={"include_source_image": source, "include_result_image": result},
        evidence_root=root,
    )
    assert generated["feedback_bundle_status"] == "PASS", generated
    path = Path(generated["feedback_bundle_path"])
    with zipfile.ZipFile(path) as archive:
        feedback = json.loads(archive.read("feedback.json"))
        manifest = json.loads(archive.read("manifest.json"))
        names = archive.namelist()
    return feedback, manifest, names


class CompressionFeedbackEvidenceTests(unittest.TestCase):
    def test_compression_feedback_records_real_format_size_hash_and_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for source_format, output_format in (("JPEG", "JPEG"), ("PNG", "PNG"), ("PNG", "JPEG"), ("WEBP", "WEBP")):
                with self.subTest(source_format=source_format, output_format=output_format):
                    root = base / f"{source_format}-{output_format}"
                    task = _compression_task(root, source_format, output_format)
                    feedback, manifest, names = _bundle(root, task)

                    module = feedback["module_context"]
                    self.assertEqual(feedback["common_context"]["task_id"], task["task_id"])
                    self.assertEqual(feedback["common_context"]["result_id"], task["result_id"])
                    self.assertEqual(feedback["common_context"]["trace_id"], task["trace_id"])
                    self.assertEqual(module["source_format"], source_format)
                    self.assertEqual(module["target_format_mode"], task["target_format"])
                    self.assertEqual(module["output_format"], output_format)
                    self.assertEqual(module["source_width"], module["result_width"])
                    self.assertEqual(module["source_width"], 48)
                    self.assertEqual(module["source_height"], module["result_height"])
                    self.assertEqual(module["source_height"], 32)
                    self.assertEqual(module["source_bytes"], task["result"].source_size_bytes)
                    self.assertEqual(module["result_bytes"], task["result"].output_size_bytes)
                    self.assertEqual(module["real_compression_ratio"], task["result"].size_reduction_ratio)
                    self.assertEqual(module["source_sha256"], task["result"].source_sha256)
                    self.assertEqual(module["result_sha256"], task["result"].output_sha256)
                    self.assertIs(module["keep_original"], False)
                    self.assertEqual(names, ["feedback.json", "related.log", "timeline.json", "manifest.json"])
                    self.assertEqual(feedback["image_evidence"]["source_image"]["status"], "NOT_AUTHORIZED")
                    self.assertEqual(feedback["image_evidence"]["result_image"]["status"], "NOT_AUTHORIZED")
                    self.assertEqual(manifest["context_binding"]["task_id"], task["task_id"])
                    self.assertEqual(manifest["context_binding"]["result_id"], task["result_id"])
                    self.assertEqual(manifest["context_binding"]["module_context"], module)
                    self.assertEqual(manifest["image_evidence"]["source_image"]["registered_sha256"], task["result"].source_sha256)
                    self.assertEqual(manifest["image_evidence"]["result_image"]["registered_sha256"], task["result"].output_sha256)

    def test_authorized_source_and_result_are_included_independently_with_verified_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = _compression_task(root, "PNG", "JPEG")

            source_feedback, _, source_names = _bundle(root, task, source=True)
            self.assertIn("evidence/source.png", source_names)
            self.assertNotIn("evidence/result.jpg", source_names)
            self.assertEqual(source_feedback["image_evidence"]["source_image"]["sha256"], task["result"].source_sha256)

            result_feedback, _, result_names = _bundle(root, task, result=True)
            self.assertNotIn("evidence/source.png", result_names)
            self.assertIn("evidence/result.jpg", result_names)
            self.assertEqual(result_feedback["image_evidence"]["result_image"]["sha256"], task["result"].output_sha256)

            both_feedback, _, both_names = _bundle(root, task, source=True, result=True)
            self.assertTrue({"evidence/source.png", "evidence/result.jpg"}.issubset(both_names))
            self.assertEqual(both_feedback["image_evidence"]["status"], "PASS")

    def test_authorized_missing_and_changed_evidence_have_specific_failure_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing_root = root / "missing"
            missing_task = _compression_task(missing_root, "PNG", "PNG")
            Path(missing_task["source_path"]).unlink()
            missing_feedback, _, _ = _bundle(missing_root, missing_task, source=True)
            missing = missing_feedback["image_evidence"]["source_image"]
            self.assertEqual(missing["status"], "FILE_NOT_FOUND")
            self.assertEqual(missing["failure_code"], "SOURCE_NOT_FOUND")

            changed_root = root / "changed"
            changed_task = _compression_task(changed_root, "PNG", "JPEG")
            output_path = Path(changed_task["output_path"])
            _write_image(output_path, "JPEG", color=(220, 20, 20, 255))
            changed_feedback, _, changed_names = _bundle(changed_root, changed_task, result=True)
            changed = changed_feedback["image_evidence"]["result_image"]
            self.assertEqual(changed["status"], "FILE_CHANGED")
            self.assertEqual(changed["failure_code"], "FILE_CHANGED")
            self.assertNotIn("evidence/result.jpg", changed_names)

    def test_keep_original_preserves_compression_facts_and_explains_missing_result_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = _compression_task(root, "WEBP", "WEBP", keep_original=True)
            feedback, manifest, names = _bundle(root, task, source=True, result=True)
            module = feedback["module_context"]
            self.assertIs(module["keep_original"], True)
            self.assertEqual(module["target_format_mode"], "PRESERVE_FORMAT")
            self.assertEqual(module["real_compression_ratio"], 0.0)
            self.assertIsNone(module["result_sha256"])
            self.assertIsNone(feedback["common_context"]["result_id"])
            self.assertIn("evidence/source.webp", names)
            self.assertNotIn("evidence/result.webp", names)
            result_evidence = feedback["image_evidence"]["result_image"]
            self.assertEqual(result_evidence["status"], "CONTEXT_UNAVAILABLE")
            self.assertEqual(result_evidence["failure_code"], "RESULT_BINDING_MISSING")
            self.assertIsNone(manifest["context_binding"]["result_id"])


if __name__ == "__main__":
    unittest.main()
