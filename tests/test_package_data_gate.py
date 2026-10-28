from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import marshal
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PACKAGING_ROOT = ROOT / "packaging" / "windows"
sys.path.insert(0, str(PACKAGING_ROOT))

import package_data_gate  # noqa: E402
import package_data_gate_core  # noqa: E402
import program_resources  # noqa: E402


class ProgramResourceAllowlistTests(unittest.TestCase):
    @staticmethod
    def _write_exe(tree: Path) -> dict[str, dict[str, str]]:
        executable = tree / package_data_gate.APP_EXE_NAME
        executable.write_bytes(b"MZ-HDDE")
        return {
            package_data_gate.APP_EXE_NAME: {
                "source_origin": str(executable),
                "source_type": "EXECUTABLE",
            }
        }

    @staticmethod
    def _zip_bytes(members: dict[str, bytes]) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, value in members.items():
                archive.writestr(name, value)
        return output.getvalue()

    @staticmethod
    def _pyc_bytes(source: str = "value = 1") -> bytes:
        header = importlib.util.MAGIC_NUMBER + (0).to_bytes(4, "little") + (b"\0" * 8)
        return header + marshal.dumps(compile(source, "expected_module.py", "exec"))

    @staticmethod
    def _pyc_inventory(
        archive: Path,
        member: str,
        source_origin: Path,
        provenance_source: Path,
        *,
        module_identity: str = "expected_module",
        archive_identity: str | None = None,
        recorded_member: str | None = None,
        expected_sha256: str | None = None,
    ) -> dict[str, dict[str, str]]:
        record = {
            "archive_identity": archive_identity or package_data_gate_core._archive_identity(archive),
            "member_path": recorded_member or member,
            "module_identity": module_identity,
            "source_origin": str(source_origin.resolve()),
            "source_identity": str(source_origin.resolve()),
            "provenance_source": str(provenance_source.resolve()),
            "expected_classification": "PYTHON_BYTECODE",
        }
        if expected_sha256 is not None:
            record["expected_sha256"] = expected_sha256
        return {member: record}

    def _production_collect_archive_fixture(
        self,
        root: Path,
        archive_name: str,
        archive_value: bytes,
    ) -> tuple[Path, Path, Path]:
        tree = root / "app"
        work = root / "pyinstaller-work"
        trusted = root / "trusted-runtime"
        tree.mkdir()
        work.mkdir()
        trusted.mkdir()
        source_exe = work / package_data_gate.APP_EXE_NAME
        source_exe.write_bytes(b"MZ-production-collect-fixture")
        (tree / package_data_gate.APP_EXE_NAME).write_bytes(source_exe.read_bytes())
        source = trusted / archive_name
        source.write_bytes(archive_value)
        target = tree / "_internal" / archive_name
        target.parent.mkdir()
        target.write_bytes(archive_value)
        analysis = [None] * 20
        analysis[15] = [(archive_name, str(source), "DATA")]
        analysis[18] = []
        analysis[19] = []
        (work / "Analysis-00.toc").write_text(repr(analysis), encoding="utf-8")
        collect = [
            (package_data_gate.APP_EXE_NAME, "ignored", "EXECUTABLE"),
            (archive_name, str(source), "DATA"),
        ]
        (work / "COLLECT-00.toc").write_text(repr(collect), encoding="utf-8")
        return tree, work, trusted

    def _production_archive_fixture(
        self,
        root: Path,
        archives: dict[str, bytes],
    ) -> tuple[Path, Path, Path, dict[str, dict[str, str]]]:
        tree = root / "app"
        work = root / "pyinstaller-work"
        trusted = root / "trusted-runtime"
        tree.mkdir()
        work.mkdir()
        trusted.mkdir()

        source_exe = work / package_data_gate.APP_EXE_NAME
        source_exe.write_bytes(b"MZ-production-archive-fixture")
        (tree / package_data_gate.APP_EXE_NAME).write_bytes(source_exe.read_bytes())
        provenance = {
            package_data_gate.APP_EXE_NAME: {
                "source_origin": str(source_exe),
                "source_type": "EXECUTABLE",
                "analysis_record": "PYINSTALLER_GENERATED",
            }
        }
        for relative, value in archives.items():
            source = trusted / Path(relative).name
            source.write_bytes(value)
            target = tree / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
            provenance[Path(relative).as_posix()] = {
                "source_origin": str(source),
                "source_type": "DATA",
                "analysis_record": "ANALYSIS_CONFIRMED",
            }
        return tree, work, trusted, provenance

    def test_current_program_resources_are_explicit_and_exclude_runtime_artifacts(self):
        resources = program_resources.discover_program_resources(ROOT)
        sources = {item.source_relative for item in resources}
        self.assertIn("dist/index.html", sources)
        self.assertIn("dist/assets/contact/wechat-qr.png", sources)
        self.assertIn("models/local_retouch/inpainting_lama_2025jan.onnx", sources)
        self.assertIn(
            "external_tools/realesrgan-ncnn-vulkan/realesrgan-ncnn-vulkan.exe",
            sources,
        )
        self.assertNotIn("external_tools/realesrgan-ncnn-vulkan/input.jpg", sources)
        self.assertNotIn("external_tools/realesrgan-ncnn-vulkan/input2.jpg", sources)
        self.assertNotIn("external_tools/realesrgan-ncnn-vulkan/onepiece_demo.mp4", sources)
        self.assertFalse(any("__pycache__" in item or item.endswith(".pyc") for item in sources))

    def test_minimal_app_tree_generates_reproducible_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / "app"
            tree.mkdir()
            provenance = self._write_exe(tree)
            manifest = root / "manifest.json"
            result = package_data_gate.scan_app_tree(
                tree,
                ROOT,
                manifest,
                expected_resources={},
                provenance_by_path=provenance,
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["file_count"], 1)
            self.assertTrue(manifest.is_file())
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["files"][0]["CLASSIFICATION"], "APP_EXECUTABLE")
            self.assertEqual(payload["files"][0]["ALLOW_RULE"], "EXPLICIT_TEST_PROVENANCE")
            self.assertIn("SOURCE_ORIGIN", payload["files"][0])
            self.assertIn("HASH", payload["files"][0])

    def test_manifest_schema_rejects_missing_null_and_unknown_archive_type(self):
        cases = {
            "missing": "MISSING",
            "null": None,
            "unknown-enum": "UNKNOWN_ARCHIVE_TYPE",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree, work, trusted, provenance = self._production_archive_fixture(
                root,
                {"_internal/safe.zip": self._zip_bytes({"safe.txt": b"program resource"})},
            )
            for label, archive_type in cases.items():
                with self.subTest(label=label):
                    member = {
                        "FINAL_PATH": "_internal/safe.zip!/safe.pyc",
                        "ARCHIVE_TYPE": archive_type,
                        "ARCHIVE_IDENTITY": "test-archive",
                        "MEMBER_PATH": "safe.pyc",
                        "CLASSIFICATION": "PYTHON_BYTECODE",
                        "SOURCE_ORIGIN": "test-source.py",
                        "EXPECTED_SHA256": "0" * 64,
                        "ACTUAL_SHA256": "0" * 64,
                        "HASH_MATCH": True,
                    }
                    if archive_type == "MISSING":
                        del member["ARCHIVE_TYPE"]
                    archive_result = {
                        "archive_type": "ZIP",
                        "path": "_internal/safe.zip",
                        "ARCHIVE_TYPE": "ZIP",
                        "CONTENT_BINDING_MODE": "MEMBER_INVENTORY",
                        "member_count": 1,
                        "members": [member],
                        "errors": [],
                    }
                    manifest = root / f"manifest-{label}.json"
                    with (
                        mock.patch.object(
                            package_data_gate_core,
                            "scan_zip_archive",
                            return_value=archive_result,
                        ),
                        mock.patch.object(
                            package_data_gate_core,
                            "scan_pyinstaller_archives",
                            return_value=[],
                        ),
                    ):
                        with self.assertRaisesRegex(
                            package_data_gate.PackageDataLeakError,
                            "MANIFEST_SCHEMA_ERROR",
                        ):
                            package_data_gate.scan_app_tree(
                                tree,
                                ROOT,
                                manifest,
                                expected_resources={},
                                pyinstaller_work=work,
                                provenance_by_path=provenance,
                                trusted_roots=[(trusted, "TEST_TRUSTED_RUNTIME")],
                            )
                    payload = json.loads(manifest.read_text(encoding="utf-8"))
                    self.assertEqual(payload["MANIFEST_SCHEMA"], "FAIL")
                    self.assertEqual(payload["status"], "FAIL")

    def test_manifest_schema_accepts_current_archive_type_enum(self):
        for archive_type in sorted(package_data_gate_core.ARCHIVE_TYPE_ENUM):
            with self.subTest(archive_type=archive_type):
                member = {
                    "FINAL_PATH": f"{archive_type}!/member",
                    "ARCHIVE_TYPE": archive_type,
                    "ARCHIVE_IDENTITY": "test-archive",
                    "MEMBER_PATH": "member",
                    "CLASSIFICATION": "PYTHON_MODULE",
                    "SOURCE_ORIGIN": "test-source.py",
                    "EXPECTED_SHA256": "0" * 64,
                    "ACTUAL_SHA256": "0" * 64,
                    "HASH_MATCH": True,
                }
                errors = package_data_gate_core._manifest_schema_errors(
                    [
                        {
                            "CONTENT_BINDING_MODE": "MEMBER_INVENTORY",
                            "members": [member],
                        }
                    ]
                )
                self.assertEqual(errors, [])

    def test_non_allowlist_image_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / "app"
            tree.mkdir()
            provenance = self._write_exe(tree)
            (tree / "customer-output.png").write_bytes(b"not-an-app-resource")
            with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "NON_ALLOWLIST_IMAGE"):
                package_data_gate.scan_app_tree(
                    tree,
                    ROOT,
                    root / "manifest.json",
                    expected_resources={},
                    provenance_by_path=provenance,
                )

    def test_formal_user_path_content_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / "app"
            tree.mkdir()
            provenance = self._write_exe(tree)
            (tree / "config.txt").write_text(r"D:\影界文件\输出", encoding="utf-8")
            with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "formal_user_root"):
                package_data_gate.scan_app_tree(
                    tree,
                    ROOT,
                    root / "manifest.json",
                    expected_resources={},
                    provenance_by_path=provenance,
                )

    def test_unused_renderer_runtime_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / "app"
            unused = tree / "_internal" / "webview" / "lib" / "pywebview-android.jar"
            unused.parent.mkdir(parents=True)
            provenance = self._write_exe(tree)
            unused.write_bytes(b"unused-renderer")
            with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "UNUSED_RENDERER_RUNTIME"):
                package_data_gate.scan_app_tree(
                    tree,
                    ROOT,
                    root / "manifest.json",
                    expected_resources={},
                    provenance_by_path=provenance,
                )

    def test_unknown_neutral_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / "app"
            tree.mkdir()
            provenance = self._write_exe(tree)
            (tree / "notes.txt").write_text("neutral", encoding="utf-8")
            with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "UNKNOWN_FINAL_FILE"):
                package_data_gate.scan_app_tree(
                    tree,
                    ROOT,
                    root / "manifest.json",
                    expected_resources={},
                    provenance_by_path=provenance,
                )

    def test_old_false_negative_business_files_fail_closed(self):
        cases = {
            "result.json": b"{}",
            "user.log": b"runtime log",
            "cache.dat": b"cache",
            "task_history.json": b"[]",
            "registry.json": b"{}",
            "tests/sample-output.txt": b"sample",
        }
        for relative, value in cases.items():
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                tree = root / "app"
                tree.mkdir()
                provenance = self._write_exe(tree)
                target = tree / Path(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(value)
                with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "BUSINESS_DATA_DENY"):
                    package_data_gate.scan_app_tree(
                        tree,
                        ROOT,
                        root / "manifest.json",
                        expected_resources={},
                        provenance_by_path=provenance,
                    )

    def test_feedback_zip_and_nested_business_data_fail_closed(self):
        cases = {
            "feedback.zip": self._zip_bytes({"result.json": b"{}"}),
            "payload.zip": self._zip_bytes(
                {"inner.zip": self._zip_bytes({"logs/user.log": b"private runtime log"})}
            ),
        }
        for relative, value in cases.items():
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                tree = root / "app"
                tree.mkdir()
                provenance = self._write_exe(tree)
                (tree / relative).write_bytes(value)
                with self.assertRaises(package_data_gate.PackageDataLeakError):
                    package_data_gate.scan_app_tree(
                        tree,
                        ROOT,
                        root / "manifest.json",
                        expected_resources={},
                        provenance_by_path=provenance,
                    )

    def test_invalid_zip_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / "app"
            tree.mkdir()
            provenance = self._write_exe(tree)
            (tree / "payload.zip").write_bytes(b"not-a-zip")
            with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "ZIP_INVALID"):
                package_data_gate.scan_app_tree(
                    tree,
                    ROOT,
                    root / "manifest.json",
                    expected_resources={},
                    provenance_by_path=provenance,
                )

    def test_production_branch_scans_extra_zip_and_rejects_business_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree, work, trusted, provenance = self._production_archive_fixture(
                root,
                {"payload.zip": self._zip_bytes({"logs/user.log": b"private runtime log"})},
            )
            with mock.patch.object(package_data_gate_core, "scan_pyinstaller_archives", return_value=[]):
                with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "BUSINESS_DATA_DENY"):
                    package_data_gate.scan_app_tree(
                        tree,
                        ROOT,
                        root / "manifest.json",
                        expected_resources={},
                        pyinstaller_work=work,
                        provenance_by_path=provenance,
                        trusted_roots=[(trusted, "TEST_TRUSTED_RUNTIME")],
                    )

    def test_production_branch_allows_explicit_safe_archive_member(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree, work, trusted, provenance = self._production_archive_fixture(
                root,
                {"safe.zip": self._zip_bytes({"safe/resource.dat": b"packaged program resource"})},
            )
            with mock.patch.object(package_data_gate_core, "scan_pyinstaller_archives", return_value=[]):
                result = package_data_gate.scan_app_tree(
                    tree,
                    ROOT,
                    root / "manifest.json",
                    expected_resources={},
                    pyinstaller_work=work,
                    provenance_by_path=provenance,
                    trusted_roots=[(trusted, "TEST_TRUSTED_RUNTIME")],
                    archive_member_allowlist={"safe.zip": {"safe/resource.dat"}},
                )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["archives_discovered"], 1)
            self.assertEqual(result["archives_scanned"], 1)
            member = result["archives"][0]["members"][0]
            self.assertEqual(member["CLASSIFICATION"], "APP_OWNED_ARCHIVE_RESOURCE")
            self.assertEqual(member["ALLOW_RULE"], "EXPLICIT_ARCHIVE_MEMBER_ALLOWLIST")

    def test_production_branch_rejects_nested_business_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = self._zip_bytes({"feedback/result.json": b"{}"})
            tree, work, trusted, provenance = self._production_archive_fixture(
                root,
                {"outer.zip": self._zip_bytes({"inner.zip": nested})},
            )
            with mock.patch.object(package_data_gate_core, "scan_pyinstaller_archives", return_value=[]):
                with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "BUSINESS_DATA_DENY"):
                    package_data_gate.scan_app_tree(
                        tree,
                        ROOT,
                        root / "manifest.json",
                        expected_resources={},
                        pyinstaller_work=work,
                        provenance_by_path=provenance,
                        trusted_roots=[(trusted, "TEST_TRUSTED_RUNTIME")],
                    )

    def test_production_branch_rejects_whl_business_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree, work, trusted, provenance = self._production_archive_fixture(
                root,
                {"payload.whl": self._zip_bytes({"registry/snapshot.json": b"{}"})},
            )
            with mock.patch.object(package_data_gate_core, "scan_pyinstaller_archives", return_value=[]):
                with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "BUSINESS_DATA_DENY"):
                    package_data_gate.scan_app_tree(
                        tree,
                        ROOT,
                        root / "manifest.json",
                        expected_resources={},
                        pyinstaller_work=work,
                        provenance_by_path=provenance,
                        trusted_roots=[(trusted, "TEST_TRUSTED_RUNTIME")],
                    )

    def test_base_library_is_scanned_once_across_ordinary_and_pyinstaller_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / "app"
            work = root / "pyinstaller-work"
            tree.mkdir()
            work.mkdir()
            source_exe = work / package_data_gate.APP_EXE_NAME
            source_exe.write_bytes(b"MZ-base-library-dedup")
            (tree / package_data_gate.APP_EXE_NAME).write_bytes(source_exe.read_bytes())
            base_source = work / "base_library.zip"
            base_source.write_bytes(self._zip_bytes({"safe.pyc": importlib.util.MAGIC_NUMBER + (b"\0" * 12)}))
            base_target = tree / "_internal" / "base_library.zip"
            base_target.parent.mkdir()
            base_target.write_bytes(base_source.read_bytes())
            provenance = {
                package_data_gate.APP_EXE_NAME: {
                    "source_origin": str(source_exe),
                    "source_type": "EXECUTABLE",
                    "analysis_record": "PYINSTALLER_GENERATED",
                },
                "_internal/base_library.zip": {
                    "source_origin": str(base_source),
                    "source_type": "DATA",
                    "analysis_record": "PYINSTALLER_GENERATED",
                },
            }
            base_result = {
                "archive_type": "BASE_LIBRARY_ZIP",
                "path": str(base_target.resolve()),
                "member_count": 1,
                "members": [],
                "errors": [],
            }
            fixed_results = [
                {
                    "archive_type": archive_type,
                    "path": str(work / path),
                    "member_count": 0,
                    "members": [],
                    "errors": [],
                }
                for archive_type, path in (
                    ("CARCHIVE_EXE", "app.exe"),
                    ("PKG", "app.pkg"),
                    ("PYZ_EMBEDDED", "embedded.pyz"),
                    ("PYZ_STANDALONE", "standalone.pyz"),
                )
            ]
            with (
                mock.patch.object(package_data_gate_core, "_scan_base_library_archive", return_value=base_result),
                mock.patch.object(
                    package_data_gate_core,
                    "scan_pyinstaller_archives",
                    return_value=fixed_results,
                ) as fixed_scan,
            ):
                result = package_data_gate.scan_app_tree(
                    tree,
                    ROOT,
                    root / "manifest.json",
                    expected_resources={},
                    pyinstaller_work=work,
                    provenance_by_path=provenance,
                    trusted_roots=[],
                )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["archives_discovered"], 6)
            self.assertEqual(result["archives_scanned"], 5)
            self.assertEqual(result["archives_deduped"], 1)
            self.assertEqual(sum(item["archive_type"] == "BASE_LIBRARY_ZIP" for item in result["archives"]), 1)
            self.assertFalse(fixed_scan.call_args.kwargs["include_base_library"])

            with (
                mock.patch.object(
                    package_data_gate_core,
                    "_scan_base_library_archive",
                    side_effect=package_data_gate.PackageDataLeakError("BASE_LIBRARY_TEST_FAILURE"),
                ),
                mock.patch.object(
                    package_data_gate_core,
                    "scan_pyinstaller_archives",
                    return_value=fixed_results,
                ) as fixed_scan_after_failure,
            ):
                with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "BASE_LIBRARY_TEST_FAILURE"):
                    package_data_gate.scan_app_tree(
                        tree,
                        ROOT,
                        root / "failure-manifest.json",
                        expected_resources={},
                        pyinstaller_work=work,
                        provenance_by_path=provenance,
                        trusted_roots=[],
                    )
            failure = json.loads((root / "failure-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(failure["archives_deduped"], 1)
            self.assertEqual(
                sum("BASE_LIBRARY_TEST_FAILURE" in item for item in failure["archive_scan_errors"]),
                1,
            )
            self.assertFalse(fixed_scan_after_failure.call_args.kwargs["include_base_library"])

    def test_header_only_pyc_fails_structure_and_provenance(self):
        fake_pyc = importlib.util.MAGIC_NUMBER + (b"\0" * 12)
        with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "PYC_INVALID"):
            package_data_gate.scan_zip_archive(
                self._zip_bytes({"customer.pyc": fake_pyc}),
                display_path="payload.zip",
            )

    def test_structurally_valid_pyc_without_inventory_fails_closed(self):
        with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "UNPROVEN_PYC_MEMBER"):
            package_data_gate.scan_zip_archive(
                self._zip_bytes({"customer.pyc": self._pyc_bytes()}),
                display_path="payload.zip",
            )

    def test_renamed_pyc_not_in_expected_inventory_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "payload.zip"
            source = root / "expected_module.py"
            provenance = root / "Analysis-00.toc"
            source.write_text("value = 1", encoding="utf-8")
            provenance.write_text("analysis", encoding="utf-8")
            pyc_value = self._pyc_bytes()
            archive.write_bytes(self._zip_bytes({"customer.pyc": pyc_value}))
            inventory = self._pyc_inventory(
                archive,
                "expected_module.pyc",
                source,
                provenance,
                expected_sha256=hashlib.sha256(pyc_value).hexdigest(),
            )
            with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "MEMBER_NOT_EXPECTED"):
                package_data_gate.scan_zip_archive(archive, expected_pyc_members=inventory)

    def test_structurally_valid_pyc_with_exact_member_provenance_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "payload.zip"
            source = root / "expected_module.py"
            provenance = root / "Analysis-00.toc"
            source.write_text("value = 1", encoding="utf-8")
            provenance.write_text("analysis", encoding="utf-8")
            pyc_value = self._pyc_bytes()
            archive.write_bytes(self._zip_bytes({"expected_module.pyc": pyc_value}))
            inventory = self._pyc_inventory(
                archive,
                "expected_module.pyc",
                source,
                provenance,
                expected_sha256=hashlib.sha256(pyc_value).hexdigest(),
            )
            result = package_data_gate.scan_zip_archive(archive, expected_pyc_members=inventory)
            member = result["members"][0]
            self.assertEqual(result["errors"], [])
            self.assertEqual(member["CLASSIFICATION"], "PYTHON_BYTECODE")
            self.assertEqual(member["ALLOW_RULE"], "EXPECTED_PYC_MEMBER_PROVENANCE")
            self.assertEqual(member["MODULE_IDENTITY"], "expected_module")
            self.assertEqual(member["MEMBER_PROVENANCE_RULE"], "EXPECTED_PYC_MEMBER_PROVENANCE")
            self.assertEqual(member["EXPECTED_SHA256"], hashlib.sha256(pyc_value).hexdigest())
            self.assertEqual(member["ACTUAL_SHA256"], hashlib.sha256(pyc_value).hexdigest())
            self.assertTrue(member["HASH_MATCH"])

    def test_structurally_valid_pyc_missing_expected_hash_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "payload.zip"
            source = root / "expected_module.py"
            provenance = root / "Analysis-00.toc"
            source.write_text("value = 1", encoding="utf-8")
            provenance.write_text("analysis", encoding="utf-8")
            archive.write_bytes(self._zip_bytes({"expected_module.pyc": self._pyc_bytes()}))
            inventory = self._pyc_inventory(archive, "expected_module.pyc", source, provenance)
            with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "EXPECTED_SHA256_MISSING"):
                package_data_gate.scan_zip_archive(archive, expected_pyc_members=inventory)

    def test_pyc_archive_identity_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "payload.zip"
            source = root / "expected_module.py"
            provenance = root / "Analysis-00.toc"
            source.write_text("value = 1", encoding="utf-8")
            provenance.write_text("analysis", encoding="utf-8")
            pyc_value = self._pyc_bytes()
            archive.write_bytes(self._zip_bytes({"expected_module.pyc": pyc_value}))
            inventory = self._pyc_inventory(
                archive,
                "expected_module.pyc",
                source,
                provenance,
                archive_identity=str(root / "different.zip"),
                expected_sha256=hashlib.sha256(pyc_value).hexdigest(),
            )
            with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "ARCHIVE_IDENTITY_MISMATCH"):
                package_data_gate.scan_zip_archive(archive, expected_pyc_members=inventory)

    def test_pyc_member_path_record_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "payload.zip"
            source = root / "expected_module.py"
            provenance = root / "Analysis-00.toc"
            source.write_text("value = 1", encoding="utf-8")
            provenance.write_text("analysis", encoding="utf-8")
            pyc_value = self._pyc_bytes()
            archive.write_bytes(self._zip_bytes({"expected_module.pyc": pyc_value}))
            inventory = self._pyc_inventory(
                archive,
                "expected_module.pyc",
                source,
                provenance,
                recorded_member="customer.pyc",
                expected_sha256=hashlib.sha256(pyc_value).hexdigest(),
            )
            with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "MEMBER_PATH_MISMATCH"):
                package_data_gate.scan_zip_archive(archive, expected_pyc_members=inventory)

    def test_ordinary_whl_unproven_pyc_fails_closed(self):
        with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "UNPROVEN_PYC_MEMBER"):
            package_data_gate.scan_zip_archive(
                self._zip_bytes({"customer.pyc": self._pyc_bytes()}),
                display_path="payload.whl",
                archive_type="WHL",
            )

    def test_nested_archive_fake_pyc_fails_closed(self):
        nested = self._zip_bytes({"customer.pyc": importlib.util.MAGIC_NUMBER + (b"\0" * 12)})
        outer = self._zip_bytes({"inner.zip": nested})
        with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "PYC_INVALID"):
            package_data_gate.scan_zip_archive(outer, display_path="outer.zip")

    def test_production_collect_branch_rejects_fake_and_unproven_pyc(self):
        cases = {
            "header-only": importlib.util.MAGIC_NUMBER + (b"\0" * 12),
            "real-codetype": self._pyc_bytes(),
        }
        for label, pyc in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                tree, work, trusted = self._production_collect_archive_fixture(
                    root,
                    "payload.zip",
                    self._zip_bytes({"customer.pyc": pyc}),
                )
                with mock.patch.object(package_data_gate_core, "scan_pyinstaller_archives", return_value=[]):
                    with self.assertRaisesRegex(
                        package_data_gate.PackageDataLeakError,
                        "PYC_INVALID|UNPROVEN_PYC_MEMBER",
                    ):
                        package_data_gate.scan_app_tree(
                            tree,
                            ROOT,
                            root / "manifest.json",
                            expected_resources={},
                            pyinstaller_work=work,
                            trusted_roots=[(trusted, "TEST_TRUSTED_RUNTIME")],
                        )

    def test_production_collect_base_library_member_substitution_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / "app"
            work = root / "pyinstaller-work"
            trusted = root / "trusted"
            tree.mkdir()
            work.mkdir()
            trusted.mkdir()
            (tree / "_internal").mkdir()
            source_exe = work / package_data_gate.APP_EXE_NAME
            source_exe.write_bytes(b"MZ-production-base-hash-fixture")
            (tree / package_data_gate.APP_EXE_NAME).write_bytes(source_exe.read_bytes())
            source_module = trusted / "expected_module.py"
            source_module.write_text("value = 1", encoding="utf-8")
            source_archive = work / "base_library.zip"
            source_archive.write_bytes(
                self._zip_bytes({"expected_module.pyc": self._pyc_bytes("value = 1")})
            )
            final_archive = tree / "_internal" / "base_library.zip"
            final_archive.write_bytes(
                self._zip_bytes(
                    {"expected_module.pyc": self._pyc_bytes("payload = 'private business data'")}
                )
            )
            analysis = [None] * 20
            analysis[15] = []
            analysis[18] = []
            analysis[19] = [("expected_module", str(source_module), "PYMODULE")]
            (work / "Analysis-00.toc").write_text(repr(analysis), encoding="utf-8")
            collect = [
                (package_data_gate.APP_EXE_NAME, "ignored", "EXECUTABLE"),
                ("base_library.zip", str(source_archive), "DATA"),
            ]
            (work / "COLLECT-00.toc").write_text(repr(collect), encoding="utf-8")
            with mock.patch.object(package_data_gate_core, "scan_pyinstaller_archives", return_value=[]):
                with self.assertRaisesRegex(
                    package_data_gate.PackageDataLeakError,
                    "SOURCE_ARCHIVE_HASH_MISMATCH",
                ):
                    package_data_gate.scan_app_tree(
                        tree,
                        ROOT,
                        root / "manifest.json",
                        expected_resources={},
                        pyinstaller_work=work,
                        trusted_roots=[(trusted, "TEST_TRUSTED_RUNTIME")],
                    )

    def test_base_library_expected_module_passes_and_unexpected_pyc_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "work"
            trusted = root / "trusted"
            work.mkdir()
            trusted.mkdir()
            source = trusted / "expected_module.py"
            source.write_text("value = 1", encoding="utf-8")
            analysis = [None] * 20
            analysis[19] = [("expected_module", str(source), "PYMODULE")]
            (work / "Analysis-00.toc").write_text(repr(analysis), encoding="utf-8")
            source_archive = work / "base_library.zip"
            source_member = self._pyc_bytes()
            source_archive.write_bytes(self._zip_bytes({"expected_module.pyc": source_member}))
            base_library = root / "base_library.zip"
            base_library.write_bytes(source_archive.read_bytes())
            result = package_data_gate_core._scan_base_library_archive(
                base_library,
                ROOT,
                work,
                {},
                [(trusted, "TEST_TRUSTED_RUNTIME")],
            )
            self.assertEqual(result["archive_type"], "BASE_LIBRARY_ZIP")
            self.assertTrue(result["SOURCE_ARCHIVE_HASH_MATCH"])
            self.assertEqual(result["SOURCE_ARCHIVE_SHA256"], result["FINAL_ARCHIVE_SHA256"])
            self.assertEqual(result["EXPECTED_MEMBER_COUNT"], 1)
            self.assertEqual(result["HASH_MATCHED_MEMBER_COUNT"], 1)
            self.assertEqual(result["HASH_MISMATCHED_MEMBER_COUNT"], 0)
            self.assertEqual(result["members"][0]["MODULE_IDENTITY"], "expected_module")
            self.assertEqual(result["members"][0]["ARCHIVE_TYPE"], "BASE_LIBRARY_ZIP")
            self.assertEqual(
                result["members"][0]["EXPECTED_SHA256"],
                hashlib.sha256(source_member).hexdigest(),
            )
            self.assertTrue(result["members"][0]["HASH_MATCH"])
            self.assertEqual(package_data_gate_core._manifest_schema_errors([result]), [])

            base_library.write_bytes(
                self._zip_bytes(
                    {
                        "expected_module.pyc": self._pyc_bytes(),
                        "unexpected/customer.pyc": self._pyc_bytes("secret = 'customer data'"),
                    }
                )
            )
            with self.assertRaisesRegex(
                package_data_gate.PackageDataLeakError,
                "SOURCE_ARCHIVE_HASH_MISMATCH.*MEMBER_NOT_EXPECTED",
            ):
                package_data_gate_core._scan_base_library_archive(
                    base_library,
                    ROOT,
                    work,
                    {},
                    [(trusted, "TEST_TRUSTED_RUNTIME")],
                )

    def test_base_library_same_member_valid_code_substitution_fails_hash_binding(self):
        cases = {
            "alternate-code": self._pyc_bytes("different_value = 2"),
            "business-data-constant": self._pyc_bytes("payload = 'private customer business data'"),
        }
        for label, replacement in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                work = root / "work"
                trusted = root / "trusted"
                work.mkdir()
                trusted.mkdir()
                source = trusted / "expected_module.py"
                source.write_text("value = 1", encoding="utf-8")
                analysis = [None] * 20
                analysis[19] = [("expected_module", str(source), "PYMODULE")]
                (work / "Analysis-00.toc").write_text(repr(analysis), encoding="utf-8")
                source_archive = work / "base_library.zip"
                source_archive.write_bytes(
                    self._zip_bytes({"expected_module.pyc": self._pyc_bytes()})
                )
                final_archive = root / "base_library.zip"
                final_archive.write_bytes(
                    self._zip_bytes({"expected_module.pyc": replacement})
                )
                with self.assertRaisesRegex(
                    package_data_gate.PackageDataLeakError,
                    "SOURCE_ARCHIVE_HASH_MISMATCH.*HASH_MISMATCH",
                ):
                    package_data_gate_core._scan_base_library_archive(
                        final_archive,
                        ROOT,
                        work,
                        {},
                        [(trusted, "TEST_TRUSTED_RUNTIME")],
                    )

    def test_base_library_missing_source_archive_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "work"
            trusted = root / "trusted"
            work.mkdir()
            trusted.mkdir()
            source = trusted / "expected_module.py"
            source.write_text("value = 1", encoding="utf-8")
            analysis = [None] * 20
            analysis[19] = [("expected_module", str(source), "PYMODULE")]
            (work / "Analysis-00.toc").write_text(repr(analysis), encoding="utf-8")
            final_archive = root / "base_library.zip"
            final_archive.write_bytes(
                self._zip_bytes({"expected_module.pyc": self._pyc_bytes()})
            )
            with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "BASE_LIBRARY_SOURCE_MISSING"):
                package_data_gate_core._scan_base_library_archive(
                    final_archive,
                    ROOT,
                    work,
                    {},
                    [(trusted, "TEST_TRUSTED_RUNTIME")],
                )

    def test_nested_archive_depth_limit_fails_closed(self):
        valid_pyc = importlib.util.MAGIC_NUMBER + (b"\0" * 12)
        value = self._zip_bytes({"safe.pyc": valid_pyc})
        for index in range(package_data_gate_core.MAX_ARCHIVE_DEPTH + 1):
            value = self._zip_bytes({f"level-{index}.zip": value})
        with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "ARCHIVE_MAX_DEPTH_EXCEEDED"):
            package_data_gate.scan_zip_archive(value, display_path="deep.zip")

    def test_archive_member_count_and_expanded_size_limits_fail_closed(self):
        valid_pyc = importlib.util.MAGIC_NUMBER + (b"\0" * 12)
        two_members = self._zip_bytes({"one.pyc": valid_pyc, "two.pyc": valid_pyc})
        with mock.patch.object(package_data_gate_core, "MAX_ARCHIVE_MEMBERS", 1):
            with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "ARCHIVE_MEMBER_LIMIT"):
                package_data_gate.scan_zip_archive(two_members, display_path="count.zip")
        with mock.patch.object(package_data_gate_core, "MAX_ARCHIVE_EXPANDED_SIZE", 1):
            with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "ARCHIVE_EXPANDED_SIZE_LIMIT"):
                package_data_gate.scan_zip_archive(two_members, display_path="size.zip")

    def test_archive_compression_bomb_ratio_limit_fails_closed(self):
        value = self._zip_bytes({"bomb.pyc": importlib.util.MAGIC_NUMBER + (b"\0" * 2_000_000)})
        with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "ARCHIVE_COMPRESSION_RATIO_LIMIT"):
            package_data_gate.scan_zip_archive(value, display_path="bomb.zip")

    def test_trusted_runtime_requires_exact_source_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / "app"
            trusted = root / "trusted"
            tree.mkdir()
            trusted.mkdir()
            provenance = self._write_exe(tree)
            source = trusted / "runtime.dll"
            source.write_bytes(b"runtime")
            target = tree / "_internal" / "runtime.dll"
            target.parent.mkdir()
            target.write_bytes(source.read_bytes())
            provenance["_internal/runtime.dll"] = {
                "source_origin": str(source),
                "source_type": "BINARY",
            }
            result = package_data_gate.scan_app_tree(
                tree,
                ROOT,
                root / "manifest.json",
                expected_resources={},
                provenance_by_path=provenance,
                trusted_roots=[(trusted, "TEST_TRUSTED_RUNTIME")],
            )
            runtime = next(item for item in result["files"] if item["FINAL_PATH"].endswith("runtime.dll"))
            self.assertEqual(runtime["CLASSIFICATION"], "THIRD_PARTY_RUNTIME")
            self.assertEqual(runtime["ALLOW_RULE"], "TEST_TRUSTED_RUNTIME")

    def test_trusted_runtime_source_drift_is_recorded_without_reclassifying_built_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / "app"
            trusted = root / "trusted"
            tree.mkdir()
            trusted.mkdir()
            provenance = self._write_exe(tree)
            source = trusted / "runtime.dll"
            source.write_bytes(b"current-runtime-version")
            target = tree / "_internal" / "runtime.dll"
            target.parent.mkdir()
            target.write_bytes(b"built-runtime-version")
            provenance["_internal/runtime.dll"] = {
                "source_origin": str(source),
                "source_type": "BINARY",
            }
            result = package_data_gate.scan_app_tree(
                tree,
                ROOT,
                root / "manifest.json",
                expected_resources={},
                provenance_by_path=provenance,
                trusted_roots=[(trusted, "TEST_TRUSTED_RUNTIME")],
            )
            runtime = next(item for item in result["files"] if item["FINAL_PATH"].endswith("runtime.dll"))
            self.assertFalse(runtime["SOURCE_HASH_MATCH"])

    def test_program_resource_requires_exact_source_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / "app"
            source_root = root / "source"
            tree.mkdir()
            source_root.mkdir()
            provenance = self._write_exe(tree)
            source = source_root / "index.html"
            source.write_text("<html>HDDE</html>", encoding="utf-8")
            target = tree / "_internal" / "dist" / "index.html"
            target.parent.mkdir(parents=True)
            target.write_bytes(source.read_bytes())
            final_path = "_internal/dist/index.html"
            provenance[final_path] = {"source_origin": str(source), "source_type": "DATA"}
            result = package_data_gate.scan_app_tree(
                tree,
                ROOT,
                root / "manifest.json",
                expected_resources={final_path: str(source)},
                provenance_by_path=provenance,
            )
            resource = next(item for item in result["files"] if item["FINAL_PATH"] == final_path)
            self.assertEqual(resource["CLASSIFICATION"], "APP_OWNED_RESOURCE")

            target.write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "APP_RESOURCE_HASH_MISMATCH"):
                package_data_gate.scan_app_tree(
                    tree,
                    ROOT,
                    root / "tampered-manifest.json",
                    expected_resources={final_path: str(source)},
                    provenance_by_path=provenance,
                )

    def test_loose_pyc_is_forbidden_even_with_trusted_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / "app"
            trusted = root / "trusted"
            tree.mkdir()
            trusted.mkdir()
            provenance = self._write_exe(tree)
            source = trusted / "module.pyc"
            source.write_bytes(importlib.util.MAGIC_NUMBER + (b"\0" * 12))
            target = tree / "_internal" / "module.pyc"
            target.parent.mkdir()
            target.write_bytes(source.read_bytes())
            provenance["_internal/module.pyc"] = {
                "source_origin": str(source),
                "source_type": "DATA",
            }
            with self.assertRaisesRegex(package_data_gate.PackageDataLeakError, "LOOSE_PYC_FORBIDDEN"):
                package_data_gate.scan_app_tree(
                    tree,
                    ROOT,
                    root / "manifest.json",
                    expected_resources={},
                    provenance_by_path=provenance,
                    trusted_roots=[(trusted, "TEST_TRUSTED_RUNTIME")],
                )


if __name__ == "__main__":
    unittest.main()
