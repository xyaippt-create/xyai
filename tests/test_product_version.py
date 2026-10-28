from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime import APP_VERSION, PRODUCT_VERSION, RELEASE_CHANNEL


ROOT = Path(__file__).resolve().parents[1]
VERSION_PATH = ROOT / "product_version.json"
TOOL_PATH = ROOT / "tools" / "manage_version.py"
ENTRY_PATH = ROOT / "scripts" / "bump_version.py"
SPEC = importlib.util.spec_from_file_location("manage_version", TOOL_PATH)
assert SPEC and SPEC.loader
MANAGE_VERSION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MANAGE_VERSION)
BUMP_SPEC = importlib.util.spec_from_file_location("bump_version", ENTRY_PATH)
assert BUMP_SPEC and BUMP_SPEC.loader
BUMP_VERSION = importlib.util.module_from_spec(BUMP_SPEC)
BUMP_SPEC.loader.exec_module(BUMP_VERSION)


class ProductVersionTests(unittest.TestCase):
    def test_single_source_is_internally_consistent(self):
        payload = json.loads(VERSION_PATH.read_text(encoding="utf-8"))
        MANAGE_VERSION.parse_version(payload["version"])
        self.assertEqual(
            payload["display_version"],
            MANAGE_VERSION.display_version_for(payload["version"], payload["release_channel"]),
        )
        self.assertEqual(
            payload["release_name"],
            MANAGE_VERSION.RELEASE_CHANNEL_LABELS[payload["release_channel"]],
        )

    def test_backend_runtime_reads_single_source(self):
        payload = json.loads(VERSION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(PRODUCT_VERSION, payload["version"])
        self.assertEqual(APP_VERSION, payload["display_version"])
        self.assertEqual(RELEASE_CHANNEL, payload["release_channel"])

    def test_frontend_adapter_reads_single_source(self):
        source = (ROOT / "src" / "productVersion.js").read_text(encoding="utf-8")
        build_info = (ROOT / "src" / "buildInfo.js").read_text(encoding="utf-8")
        settings = (ROOT / "src" / "SystemSettingsPage.jsx").read_text(encoding="utf-8")
        vite_config = (ROOT / "vite.config.js").read_text(encoding="utf-8")
        self.assertIn('../product_version.json', source)
        self.assertIn('PRODUCT_RELEASE_CHANNEL = productVersion.release_channel', source)
        self.assertIn('label="产品版本"', settings)
        self.assertIn('value={health.version || PRODUCT_VERSION_LABEL}', settings)
        self.assertNotIn('>测试版</HddeStatusPill>', settings)
        self.assertNotIn('label="当前构建"', settings)
        self.assertIn("__HDDE_BUILD_ID__", build_info)
        self.assertIn('gitValue(["rev-parse", "--short=12", "HEAD"])', vite_config)
        self.assertIn('gitValue(["status", "--porcelain=v1", "--untracked-files=all"])', vite_config)
        self.assertNotIn("new Date", build_info)
        self.assertNotIn("git", build_info.lower())
        self.assertNotIn("V0.5.3", settings)

    def test_prerelease_version_is_supported(self):
        self.assertEqual(MANAGE_VERSION.parse_version("1.2.3-dev"), (1, 2, 3))
        self.assertEqual(MANAGE_VERSION.parse_version("1.2.3-beta"), (1, 2, 3))
        self.assertEqual(MANAGE_VERSION.display_version_for("1.2.3-beta", "INTERNAL_BETA"), "V1.2.3 测试版")
        self.assertEqual(MANAGE_VERSION.display_version_for("1.2.3-dev", "DEVELOPMENT"), "V1.2.3 开发版")
        self.assertEqual(MANAGE_VERSION.machine_version_for("1.2.3", "DEVELOPMENT"), "1.2.3-dev")
        self.assertEqual(MANAGE_VERSION.machine_version_for("1.2.3", "INTERNAL_BETA"), "1.2.3-beta")

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
                    {
                        "version": "0.5.3-beta",
                        "display_version": "V0.5.3 测试版",
                        "release_name": "test",
                        "release_channel": "INTERNAL_BETA",
                    },
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
            current = json.loads(before.decode("utf-8"))["version"]
            result = MANAGE_VERSION.update_version_file(path, set_version=current, expect_current=current)
            self.assertFalse(result["changed"])
            self.assertEqual(path.read_bytes(), before)

    def test_expect_current_mismatch_blocks(self):
        with self.assertRaisesRegex(ValueError, "expected current version"):
            MANAGE_VERSION.update_version_file(VERSION_PATH, set_version="0.5.4-dev", expect_current="0.5.3", dry_run=True)

    def test_cli_has_no_git_side_effects(self):
        source = TOOL_PATH.read_text(encoding="utf-8")
        entry_source = ENTRY_PATH.read_text(encoding="utf-8")
        self.assertNotIn("git commit", source)
        self.assertNotIn("git tag", source)
        self.assertNotIn("git commit", entry_source)
        self.assertNotIn("git tag", entry_source)
        payload = json.loads(VERSION_PATH.read_text(encoding="utf-8"))
        completed = subprocess.run(
            [
                str(ROOT / ".venv" / "Scripts" / "python.exe"),
                str(ENTRY_PATH),
                payload["display_version"],
                "--expect-current",
                payload["version"],
                "--dry-run",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

    def test_one_sentence_entry_updates_an_isolated_version_source(self):
        payload = json.loads(VERSION_PATH.read_text(encoding="utf-8"))
        target_semantic = MANAGE_VERSION.bump_version(payload["version"], "patch")
        target_label = MANAGE_VERSION.RELEASE_CHANNEL_LABELS[payload["release_channel"]]
        target_display = f"V{target_semantic} {target_label}"
        target_machine = MANAGE_VERSION.machine_version_for(target_semantic, payload["release_channel"])

        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            version_path = project_root / "product_version.json"
            version_path.write_bytes(VERSION_PATH.read_bytes())
            completed = subprocess.run(
                [
                    str(ROOT / ".venv" / "Scripts" / "python.exe"),
                    str(ENTRY_PATH),
                    f"版本升级｜{target_display}",
                    "--expect-current",
                    payload["version"],
                    "--file",
                    str(version_path),
                    "--project-root",
                    str(project_root),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            result = json.loads(completed.stdout)
            updated = json.loads(version_path.read_text(encoding="utf-8"))

        self.assertEqual(result["new"]["semantic_version"], target_semantic)
        self.assertEqual(result["new"]["machine_version"], target_machine)
        self.assertEqual(result["new"]["display_version"], target_display)
        self.assertEqual(result["installer_version_source"], "packaging/windows/build_release.ps1")
        self.assertEqual(result["old_version_residuals"], 0)
        self.assertEqual(updated["version"], target_machine)
        self.assertEqual(updated["display_version"], target_display)
        self.assertEqual(updated["release_channel"], payload["release_channel"])
        self.assertEqual(updated["release_name"], payload["release_name"])

    def test_one_sentence_entry_switches_release_stage_for_the_same_semantic_version(self):
        payload = json.loads(VERSION_PATH.read_text(encoding="utf-8"))
        current_semantic = ".".join(str(part) for part in MANAGE_VERSION.parse_version(payload["version"]))
        target_channel = "DEVELOPMENT" if payload["release_channel"] != "DEVELOPMENT" else "INTERNAL_BETA"
        target_label = MANAGE_VERSION.RELEASE_CHANNEL_LABELS[target_channel]

        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            version_path = project_root / "product_version.json"
            version_path.write_bytes(VERSION_PATH.read_bytes())
            result = BUMP_VERSION.upgrade_product_version(
                f"版本升级｜V{current_semantic} {target_label}",
                version_path=version_path,
                project_root=project_root,
            )
            updated = json.loads(version_path.read_text(encoding="utf-8"))

        self.assertEqual(result["new"]["semantic_version"], current_semantic)
        self.assertEqual(
            result["new"]["machine_version"],
            MANAGE_VERSION.machine_version_for(current_semantic, target_channel),
        )
        self.assertEqual(result["new"]["display_version"], f"V{current_semantic} {target_label}")
        self.assertEqual(updated["release_channel"], target_channel)
        self.assertEqual(updated["release_name"], target_label)

    def test_one_sentence_entry_rejects_an_unsupported_display_label(self):
        payload = json.loads(VERSION_PATH.read_text(encoding="utf-8"))
        target_semantic = MANAGE_VERSION.bump_version(payload["version"], "patch")
        with self.assertRaisesRegex(ValueError, "unsupported release label"):
            BUMP_VERSION.upgrade_product_version(
                f"V{target_semantic} 正式版",
                version_path=VERSION_PATH,
                project_root=ROOT,
                dry_run=True,
            )

    def test_one_sentence_entry_blocks_downgrades(self):
        with self.assertRaisesRegex(ValueError, "version downgrade is not allowed"):
            BUMP_VERSION.upgrade_product_version(
                "V0.1.0 测试版",
                version_path=VERSION_PATH,
                project_root=ROOT,
                dry_run=True,
            )

    def test_one_sentence_entry_blocks_old_version_in_active_source_before_write(self):
        payload = json.loads(VERSION_PATH.read_text(encoding="utf-8"))
        target_semantic = MANAGE_VERSION.bump_version(payload["version"], "patch")
        target_label = MANAGE_VERSION.RELEASE_CHANNEL_LABELS[payload["release_channel"]]
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            version_path = project_root / "product_version.json"
            source_root = project_root / "src"
            source_root.mkdir()
            version_path.write_bytes(VERSION_PATH.read_bytes())
            source_path = source_root / "hardcoded.js"
            source_path.write_text(f'export const oldVersion = "{payload["display_version"]}";\n', encoding="utf-8")
            before = version_path.read_bytes()
            with self.assertRaisesRegex(ValueError, "old version remains in active production source"):
                BUMP_VERSION.upgrade_product_version(
                    f"V{target_semantic} {target_label}",
                    version_path=version_path,
                    project_root=project_root,
                )
            self.assertEqual(version_path.read_bytes(), before)

    def test_installer_version_remains_derived_from_the_authoritative_source(self):
        build_script = (ROOT / "packaging" / "windows" / "build_release.ps1").read_text(encoding="utf-8")
        self.assertIn('$VersionPath = Join-Path $ProjectRoot "product_version.json"', build_script)
        self.assertIn('$Version = Get-Content -Raw -Encoding UTF8 -LiteralPath $VersionPath | ConvertFrom-Json', build_script)
        self.assertIn('$VersionMatch = [regex]::Match([string]$Version.version', build_script)
        self.assertIn('$InstallerVersion = "$($VersionMatch.Groups[1].Value).$($VersionMatch.Groups[2].Value).$($VersionMatch.Groups[3].Value).0"', build_script)

    def test_historical_rc8a_baseline_is_preserved(self):
        changelog = (ROOT / "docs" / "09_CODEX_CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("V0.4.6 RC8A", changelog)

    def test_system_settings_does_not_present_a_global_default_resolution(self):
        settings = (ROOT / "src" / "SystemSettingsPage.jsx").read_text(encoding="utf-8")
        self.assertNotIn('label="默认交付分辨率"', settings)
        self.assertNotIn('label="目标分辨率"', settings)


if __name__ == "__main__":
    unittest.main()
