from __future__ import annotations

import ast
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from engine.hd_core import pipeline as pipeline_module
from engine.hd_core.pipeline import process_hd_core_pipeline
from engine.hd_core.safe_base import (
    HDCoreSafeBaseError,
    assess_baseline_risk,
    finalize_with_baseline_fallback,
    process_hd_core_safe_base,
)


class HDCorePipelineTest(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, dict[str, object]]:
        source = root / "source.png"
        baseline = root / "prepared_safe_base.png"
        source_rgba = np.zeros((6, 8, 4), dtype=np.uint8)
        source_rgba[..., :3] = (45, 90, 135)
        source_rgba[..., 3] = np.arange(8, dtype=np.uint8)[None, :] * 30
        Image.fromarray(source_rgba, "RGBA").save(source)
        with Image.open(source) as opened:
            baseline_image = opened.convert("RGBA").resize((16, 12), Image.Resampling.LANCZOS)
            baseline_image.save(baseline, format="PNG")
        safe_result: dict[str, object] = {
            "status": "COMPLETED",
            "final_output_path": str(baseline),
            "final_output_pixel_sha256": "prepared-pixel-sha",
            "final_risk": assess_baseline_risk(source, baseline, baseline),
        }
        return source, baseline, safe_result

    def test_no_candidate_is_exact_current_safe_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input" / "source.png"
            source.parent.mkdir()
            Image.new("RGB", (32, 18), (45, 90, 135)).save(source)
            current = process_hd_core_safe_base(source, root / "current_safe_base")
            carried = process_hd_core_pipeline(source, root / "candidate_carrier")

            self.assertEqual(current["status"], "COMPLETED")
            self.assertEqual(carried["status"], "COMPLETED")
            self.assertEqual(
                carried["final_output_pixel_sha256"],
                current["final_output_pixel_sha256"],
            )
            self.assertFalse(carried["runtime_record"]["candidate_enabled"])
            self.assertEqual(carried["runtime_record"]["candidate_name"], "NONE")
            self.assertEqual(carried["runtime_record"]["decision"], "ACCEPT")

    def test_injected_identity_candidate_passes_frozen_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, baseline, safe_result = self._fixture(root)

            def identity_candidate(candidate_input: Path, candidate_output: Path) -> None:
                shutil.copyfile(candidate_input, candidate_output)

            with (
                patch.object(
                    pipeline_module,
                    "process_hd_core_safe_base",
                    return_value=safe_result,
                ),
                patch.object(
                    pipeline_module,
                    "assess_baseline_risk",
                    wraps=assess_baseline_risk,
                ) as risk_gate,
                patch.object(
                    pipeline_module,
                    "finalize_with_baseline_fallback",
                    wraps=finalize_with_baseline_fallback,
                ) as fallback_gate,
            ):
                result = process_hd_core_pipeline(
                    source,
                    root / "work",
                    candidate=identity_candidate,
                    candidate_name="TEST_IDENTITY_ONLY",
                )

            self.assertGreaterEqual(risk_gate.call_count, 2)
            self.assertEqual(fallback_gate.call_count, 1)
            self.assertEqual(result["runtime_record"]["decision"], "ACCEPT")
            self.assertFalse(result["candidate_risk"]["fallback_required"])
            with Image.open(baseline) as expected, Image.open(result["final_output_path"]) as actual:
                self.assertTrue(np.array_equal(np.asarray(expected), np.asarray(actual)))

    def test_candidate_exception_falls_back_pixel_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, baseline, safe_result = self._fixture(root)

            def failing_candidate(_candidate_input: Path, _candidate_output: Path) -> None:
                raise RuntimeError("test-only candidate failure")

            with patch.object(
                pipeline_module,
                "process_hd_core_safe_base",
                return_value=safe_result,
            ):
                result = process_hd_core_pipeline(
                    source,
                    root / "work",
                    candidate=failing_candidate,
                    candidate_name="TEST_EXCEPTION_ONLY",
                )

            self.assertEqual(result["runtime_record"]["decision"], "FALLBACK")
            self.assertEqual(
                result["runtime_record"]["fallback_reason"],
                "CANDIDATE_EXCEPTION:RuntimeError",
            )
            with Image.open(baseline) as expected, Image.open(result["final_output_path"]) as actual:
                self.assertTrue(np.array_equal(np.asarray(expected), np.asarray(actual)))

    def test_missing_candidate_result_falls_back_pixel_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, baseline, safe_result = self._fixture(root)

            def missing_result_candidate(_candidate_input: Path, _candidate_output: Path) -> None:
                return None

            with patch.object(
                pipeline_module,
                "process_hd_core_safe_base",
                return_value=safe_result,
            ):
                result = process_hd_core_pipeline(
                    source,
                    root / "work",
                    candidate=missing_result_candidate,
                    candidate_name="TEST_MISSING_RESULT_ONLY",
                )

            self.assertEqual(result["runtime_record"]["decision"], "FALLBACK")
            self.assertEqual(
                result["runtime_record"]["fallback_reason"],
                "CANDIDATE_RESULT_MISSING",
            )
            with Image.open(baseline) as expected, Image.open(result["final_output_path"]) as actual:
                self.assertTrue(np.array_equal(np.asarray(expected), np.asarray(actual)))

    def test_candidate_rgb_risk_falls_back_and_preserves_alpha(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, baseline, safe_result = self._fixture(root)

            def risky_candidate(candidate_input: Path, candidate_output: Path) -> None:
                with Image.open(candidate_input) as opened:
                    changed = np.asarray(opened.convert("RGBA"), dtype=np.uint8).copy()
                changed[4, 5, :3] = (255, 255, 255)
                Image.fromarray(changed, "RGBA").save(candidate_output, format="PNG")

            with patch.object(
                pipeline_module,
                "process_hd_core_safe_base",
                return_value=safe_result,
            ):
                result = process_hd_core_pipeline(
                    source,
                    root / "work",
                    candidate=risky_candidate,
                    candidate_name="TEST_RISK_ONLY",
                )

            self.assertEqual(result["runtime_record"]["decision"], "FALLBACK")
            self.assertIn(
                "RGB_DIFFERS_FROM_SAFE_BASELINE",
                result["runtime_record"]["fallback_reason"],
            )
            self.assertEqual(result["final_risk"]["alpha"]["status"], "PASS")
            with Image.open(baseline) as expected, Image.open(result["final_output_path"]) as actual:
                self.assertTrue(np.array_equal(np.asarray(expected), np.asarray(actual)))

    def test_formal_root_and_descendant_still_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            protected = root / "formal-root"
            Image.new("RGB", (8, 6), (10, 20, 30)).save(source)
            with patch("engine.hd_core.safe_base.FORMAL_DATA_ROOT", protected):
                for workspace in (protected, protected / "future" / "candidate"):
                    with self.subTest(workspace=workspace):
                        with self.assertRaises(HDCoreSafeBaseError) as caught:
                            process_hd_core_pipeline(source, workspace)
                        self.assertEqual(caught.exception.code, "FORMAL_OUTPUT_FORBIDDEN")
                        self.assertFalse(workspace.exists())

    def test_production_runtime_does_not_import_sc_ibp(self) -> None:
        hd_core_root = Path(pipeline_module.__file__).resolve().parent
        for module_path in (hd_core_root / "pipeline.py", hd_core_root / "__init__.py"):
            tree = ast.parse(module_path.read_text(encoding="utf-8"))
            imported = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported.append(node.module or "")
            self.assertFalse(any("sc_ibp" in name.lower() for name in imported), module_path)


if __name__ == "__main__":
    unittest.main()
