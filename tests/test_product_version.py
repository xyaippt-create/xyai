from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime import APP_VERSION, PRODUCT_VERSION


ROOT = Path(__file__).resolve().parents[1]
VERSION_PATH = ROOT / "product_version.json"
TOOL_PATH = ROOT / "tools" / "manage_version.py"
SPEC = importlib.util.spec_from_file_location("manage_version", TOOL_PATH)
assert SPEC and SPEC.loader
MANAGE_VERSION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MANAGE_VERSION)


class ProductVersionTests(unittest.TestCase):
    def test_single_source_is_current_development_version(self):
        payload = json.loads(VERSION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], "0.5.4-dev")
        self.assertEqual(payload["display_version"], "V0.5.4-dev")

    def test_backend_runtime_reads_single_source(self):
        payload = json.loads(VERSION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(PRODUCT_VERSION, payload["version"])
        self.assertEqual(APP_VERSION, payload["display_version"])

    def test_frontend_adapter_reads_single_source(self):
        source = (ROOT / "src" / "productVersion.js").read_text(encoding="utf-8")
        build_info = (ROOT / "src" / "buildInfo.js").read_text(encoding="utf-8")
        settings = (ROOT / "src" / "SystemSettingsPage.jsx").read_text(encoding="utf-8")
        vite_config = (ROOT / "vite.config.js").read_text(encoding="utf-8")
        self.assertIn('../product_version.json', source)
        self.assertIn('label="产品版本" value={health.version}', settings)
        self.assertIn('label="产品版本" value={PRODUCT_VERSION_LABEL}', settings)
        self.assertIn('label="当前构建" value={CURRENT_BUILD_ID}', settings)
        self.assertIn("__HDDE_BUILD_ID__", build_info)
        self.assertIn('gitValue(["rev-parse", "--short=12", "HEAD"])', vite_config)
        self.assertIn('gitValue(["status", "--porcelain=v1", "--untracked-files=all"])', vite_config)
        self.assertNotIn("new Date", build_info)
        self.assertNotIn("git", build_info.lower())
        self.assertNotIn("V0.5.3", settings)

    def test_prerelease_version_is_supported(self):
        self.assertEqual(MANAGE_VERSION.parse_version("0.5.4-dev"), (0, 5, 4))

    def test_bump_patch(self):
        self.assertEqual(MANAGE_VERSION.bump_version("0.5.3", "patch"), "0.5.4")

    def test_bump_minor(self):
        self.assertEqual(MANAGE_VERSION.bump_version("0.5.2", "minor"), "0.6.0")

    def test_bump_major(self):
        self.assertEqual(MANAGE_VERSION.bump_version("0.5.2", "major"), "1.0.0")

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "product_version.json"
            path.write_text(
                json.dumps(
                    {"version": "0.5.3", "display_version": "V0.5.3", "release_name": "test"},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            before = path.read_bytes()
            result = MANAGE_VERSION.update_version_file(path, bump="patch", dry_run=True)
            self.assertEqual(result["target"], "0.5.4")
            self.assertEqual(path.read_bytes(), before)

    def test_set_current_version_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "product_version.json"
            path.write_bytes(VERSION_PATH.read_bytes())
            before = path.read_bytes()
            result = MANAGE_VERSION.update_version_file(path, set_version="0.5.4-dev", expect_current="0.5.4-dev")
            self.assertFalse(result["changed"])
            self.assertEqual(path.read_bytes(), before)

    def test_expect_current_mismatch_blocks(self):
        with self.assertRaisesRegex(ValueError, "expected current version"):
            MANAGE_VERSION.update_version_file(VERSION_PATH, set_version="0.5.4-dev", expect_current="0.5.3", dry_run=True)

    def test_cli_has_no_git_side_effects(self):
        source = TOOL_PATH.read_text(encoding="utf-8")
        self.assertNotIn("git commit", source)
        self.assertNotIn("git tag", source)
        completed = subprocess.run(
            [str(ROOT / ".venv" / "Scripts" / "python.exe"), str(TOOL_PATH), "--set", "0.5.4-dev", "--expect-current", "0.5.4-dev", "--dry-run"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

    def test_historical_rc8a_baseline_is_preserved(self):
        settings = (ROOT / "src" / "SystemSettingsPage.jsx").read_text(encoding="utf-8")
        self.assertIn("V0.4.6 RC8A", settings)

    def test_default_resolution_is_named_as_a_default_not_total_capability(self):
        settings = (ROOT / "src" / "SystemSettingsPage.jsx").read_text(encoding="utf-8")
        self.assertIn('label="默认交付分辨率" value={health.target_resolution}', settings)
        self.assertNotIn('label="目标分辨率"', settings)


if __name__ == "__main__":
    unittest.main()
