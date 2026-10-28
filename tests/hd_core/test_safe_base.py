from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from engine.hd_core.safe_base import (
    HDCoreSafeBaseError,
    apply_source_alpha_bypass,
    assess_baseline_risk,
    diagnose_degradation,
    finalize_with_baseline_fallback,
    _validate_workspace,
)


class HDCoreSafeBaseTest(unittest.TestCase):
    def test_diagnosis_is_measurement_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.jpg"
            Image.new("RGB", (24, 16), (35, 70, 105)).save(source, quality=90)

            diagnosis = diagnose_degradation(source)

            self.assertEqual(diagnosis["status"], "MEASUREMENTS_ONLY_NO_RESTORATION_TRIGGER")
            self.assertFalse(diagnosis["semantic_detection_performed"])
            self.assertFalse(diagnosis["restoration_brick_enabled"])
            self.assertFalse(diagnosis["srmd_enabled"])

    def test_source_alpha_bypass_is_pixel_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            baseline = root / "baseline.png"
            candidate = root / "candidate.png"
            rgba = np.zeros((9, 11, 4), dtype=np.uint8)
            rgba[..., :3] = (180, 70, 35)
            rgba[..., 3] = np.arange(11, dtype=np.uint8)[None, :] * 25
            Image.fromarray(rgba, "RGBA").save(source)
            Image.new("RGBA", (44, 36), (100, 120, 140, 255)).save(baseline)

            apply_source_alpha_bypass(source, baseline, candidate)
            risk = assess_baseline_risk(source, baseline, candidate)

            with Image.open(source) as opened:
                expected = np.asarray(
                    opened.convert("RGBA").getchannel("A").resize((44, 36), Image.Resampling.LANCZOS),
                    dtype=np.uint8,
                )
            with Image.open(candidate) as opened:
                actual = np.asarray(opened.getchannel("A"), dtype=np.uint8)
            self.assertTrue(np.array_equal(actual, expected))
            self.assertEqual(risk["alpha"]["candidate_matches_source_resized_alpha"], True)
            self.assertEqual(risk["maximum_rgb_delta"], 0)

    def test_rgb_change_is_rejected_and_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            baseline = root / "baseline.png"
            candidate = root / "candidate.png"
            final = root / "final.png"
            Image.new("RGB", (12, 8), (80, 90, 100)).save(source)
            Image.new("RGB", (24, 16), (80, 90, 100)).save(baseline)
            changed = np.full((16, 24, 3), (80, 90, 100), dtype=np.uint8)
            changed[8, 12] = (255, 255, 255)
            Image.fromarray(changed, "RGB").save(candidate)

            risk = assess_baseline_risk(source, baseline, candidate)
            selected = finalize_with_baseline_fallback(baseline, candidate, final, risk)

            self.assertEqual(risk["status"], "FAIL")
            self.assertIn("RGB_DIFFERS_FROM_SAFE_BASELINE", risk["reasons"])
            self.assertTrue(risk["new_halo_possible"])
            self.assertTrue(risk["new_double_edge_possible"])
            self.assertTrue(selected["fallback_applied"])
            with Image.open(baseline) as baseline_image, Image.open(final) as final_image:
                self.assertTrue(np.array_equal(np.asarray(baseline_image), np.asarray(final_image)))

    def test_formal_root_and_descendants_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.png"
            Image.new("RGB", (12, 8), (80, 90, 100)).save(source)
            forbidden = (
                Path(r"D:\影界文件"),
                Path(r"D:\影界文件\任意新子目录"),
                Path(r"D:\影界文件\输出\4K画质增强"),
                Path(r"D:\影界文件\临时\.."),
                Path("d:/影界文件/输出/../"),
            )
            for workspace in forbidden:
                with self.subTest(workspace=str(workspace)):
                    with self.assertRaises(HDCoreSafeBaseError) as caught:
                        _validate_workspace(source, workspace)
                    self.assertEqual(caught.exception.code, "FORMAL_OUTPUT_FORBIDDEN")

    def test_isolated_and_same_prefix_workspaces_are_allowed(self) -> None:
        source = Path(r"D:\source\sample.png")
        isolated = Path(r"D:\Codex\04_Visual-Master-Pro\artifacts\hdde_hd_core_safe_base_20260813")
        same_prefix = Path(r"D:\影界文件_隔离\hd-core")
        self.assertEqual(_validate_workspace(source, isolated), isolated.resolve(strict=False))
        self.assertEqual(_validate_workspace(source, same_prefix), same_prefix.resolve(strict=False))

    def test_resolvable_symlink_alias_to_formal_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            protected = root / "protected"
            protected.mkdir()
            alias = root / "alias"
            try:
                alias.symlink_to(protected, target_is_directory=True)
            except OSError:
                junction = subprocess.run(
                    ["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(protected)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if junction.returncode != 0:
                    self.skipTest(f"当前Windows无法创建可解析别名：{junction.stderr.strip()}")
            try:
                source = root / "source.png"
                Image.new("RGB", (2, 2)).save(source)
                with patch("engine.hd_core.safe_base.FORMAL_DATA_ROOT", protected):
                    with self.assertRaises(HDCoreSafeBaseError) as caught:
                        _validate_workspace(source, alias / "future-child")
                self.assertEqual(caught.exception.code, "FORMAL_OUTPUT_FORBIDDEN")
            finally:
                if alias.exists():
                    os.rmdir(alias)

    def test_missing_risk_evidence_fails_closed_to_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "baseline.png"
            candidate = root / "candidate.png"
            final = root / "final.png"
            Image.new("RGB", (4, 4), (10, 20, 30)).save(baseline)
            Image.new("RGB", (4, 4), (250, 240, 230)).save(candidate)
            selected = finalize_with_baseline_fallback(baseline, candidate, final, {})
            self.assertTrue(selected["fallback_applied"])
            with Image.open(final) as opened:
                self.assertEqual(opened.getpixel((0, 0)), (10, 20, 30))


if __name__ == "__main__":
    unittest.main()
