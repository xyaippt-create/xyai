from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging" / "windows"))

from installer_data_gate import scan_installer_content  # noqa: E402


def _write_provenance(path: Path, *, status: str = "PASS") -> None:
    payload = {
        "status": status,
        "MANIFEST_SCHEMA": "PASS",
        "MISSING_REQUIRED_MEMBER_FIELDS": 0,
        "unknown_count": 0,
        "archive_scan_errors": [],
        "archive_member_count": 3,
        "archives": [
            {
                "HASH_MISMATCHED_MEMBER_COUNT": 0,
                "MISSING_EXPECTED_HASH_COUNT": 0,
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class InstallerDataGateTests(unittest.TestCase):
    def _fixture(self, root: Path):
        installer = root / "setup.exe"
        installer.write_bytes(b"setup")
        source = root / "source"
        (source / "_internal").mkdir(parents=True)
        (source / "影界 HDDE.exe").write_bytes(b"exe")
        (source / "_internal" / "runtime.dll").write_bytes(b"dll")
        extracted = root / "extracted"
        (extracted / "app" / "_internal").mkdir(parents=True)
        (extracted / "tmp").mkdir()
        (extracted / "app" / "影界 HDDE.exe").write_bytes(b"exe")
        (extracted / "app" / "_internal" / "runtime.dll").write_bytes(b"dll")
        bootstrapper = root / "MicrosoftEdgeWebView2Setup.exe"
        bootstrapper.write_bytes(b"microsoft")
        (extracted / "tmp" / bootstrapper.name).write_bytes(b"microsoft")
        source_provenance = root / "source-provenance.json"
        extracted_provenance = root / "extracted-provenance.json"
        _write_provenance(source_provenance)
        _write_provenance(extracted_provenance)
        return installer, source, extracted, bootstrapper, source_provenance, extracted_provenance

    def test_exact_extracted_setup_content_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self._fixture(Path(directory))
            result = scan_installer_content(
                installer=args[0], extracted_root=args[2], source_app_tree=args[1],
                webview2_bootstrapper=args[3], app_provenance=args[4],
                extracted_app_provenance=args[5],
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["unknown_count"], 0)
            self.assertEqual(result["hash_mismatch_count"], 0)

    def test_unknown_content_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self._fixture(Path(directory))
            (args[2] / "app" / "Result").mkdir()
            (args[2] / "app" / "Result" / "history.jpg").write_bytes(b"user")
            result = scan_installer_content(
                installer=args[0], extracted_root=args[2], source_app_tree=args[1],
                webview2_bootstrapper=args[3], app_provenance=args[4],
                extracted_app_provenance=args[5],
            )
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["unknown_count"], 1)

    def test_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self._fixture(Path(directory))
            (args[2] / "app" / "影界 HDDE.exe").write_bytes(b"changed")
            result = scan_installer_content(
                installer=args[0], extracted_root=args[2], source_app_tree=args[1],
                webview2_bootstrapper=args[3], app_provenance=args[4],
                extracted_app_provenance=args[5],
            )
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["hash_mismatch_count"], 1)


if __name__ == "__main__":
    unittest.main()
