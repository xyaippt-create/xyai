from __future__ import annotations

import contextlib
import hashlib
import io
import json
import logging
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from tests.support.app_runtime import controlled_test_app_paths, isolated_runtime_logging

import main
from engine.diagnostics import runtime_logging
from engine.storage import app_data_migration
from main import build_web_app
from runtime import startup_check


REPOSITORY_SETTINGS_PATH = Path(main.PROJECT_ROOT) / "settings" / "settings.json"


def semantic_sha256(payload: bytes) -> str:
    canonical = json.dumps(
        json.loads(payload.decode("utf-8")),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@contextlib.contextmanager
def capture_runtime_log():
    logger = runtime_logging.initialize_console_logging()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        handler.close()


class RuntimeLogRecordHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextlib.contextmanager
def capture_runtime_records():
    logger = runtime_logging.initialize_console_logging()
    handler = RuntimeLogRecordHandler()
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        handler.close()


def parse_runtime_record(record: logging.LogRecord) -> dict[str, str]:
    fields = {"level": record.levelname}
    for part in record.getMessage().split(" | "):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key] = value
    return fields


class WorkdirResolutionTests(unittest.TestCase):
    def test_saved_project_tmp_is_rejected_without_fallback(self):
        saved_project_tmp = Path(main.PROJECT_ROOT) / "tmp" / "runtime_data" / main.APP_DATA_ROOT_NAME
        result = main.resolve_app_data_root({"app_data_root": "", "last_app_data_root": str(saved_project_tmp)})

        self.assertFalse(result["directory_ready"])
        self.assertEqual(result["error_code"], "FORMAL_DIRECTORY_PATH_FORBIDDEN")
        self.assertEqual(Path(result["path"]), saved_project_tmp)

    def test_unwritable_saved_formal_root_blocks_without_project_tmp(self):
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "HDDE-unwritable-test-root"
            formal_root.mkdir()
            with (
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
                patch.object(main, "_directory_writable", return_value=(False, "controlled permission denied")),
            ):
                result = main.resolve_app_data_root({"app_data_root": "", "last_app_data_root": str(formal_root)})

            self.assertFalse(result["directory_ready"])
            self.assertEqual(Path(result["path"]), formal_root)
            self.assertNotIn("runtime_data", str(result["path"]))
            self.assertEqual(result["error_code"], "FORMAL_DIRECTORY_NOT_WRITABLE")

    def test_first_initialization_uses_only_formal_default_root(self):
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / main.LEGACY_WORK_DIR_NAME
            with (
                patch.object(main, "_initial_formal_app_data_root", return_value=formal_root),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
            ):
                result = main.resolve_app_data_root({"app_data_root": "", "last_app_data_root": ""})

            self.assertTrue(result["directory_ready"])
            self.assertEqual(result["source"], "initial_default")
            self.assertEqual(Path(result["path"]), formal_root)

    def test_saved_root_disappearance_blocks_without_recreation_and_recovers_in_place(self):
        repository_before = REPOSITORY_SETTINGS_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal_root = root / "saved-formal-root"
            formal_root.mkdir()
            settings_path = root / "settings.json"
            settings = json.loads(repository_before)
            settings["app_data_root"] = str(formal_root)
            settings["last_app_data_root"] = str(formal_root)
            settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
            settings_before = settings_path.read_bytes()
            formal_root.rmdir()

            with (
                isolated_runtime_logging("real-app-saved-root-disappearance"),
                patch.object(main, "SETTINGS_PATH", settings_path),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
                TestClient(build_web_app()) as client,
            ):
                blocked = client.get("/api/app/workdir")
                upload = client.post("/api/upload", files={"file": ("blocked.png", b"not-decoded", "image/png")})
                self.assertFalse(formal_root.exists())

                blocked_data = blocked.json()["data"]
                self.assertFalse(blocked_data["directory_ready"])
                self.assertFalse(blocked_data["processing_allowed"])
                self.assertEqual(Path(blocked_data["app_data_root"]), formal_root)
                self.assertEqual(Path(blocked_data["failed_path"]), formal_root)
                self.assertIn("不存在", blocked_data["failure_reason"])
                self.assertEqual(upload.status_code, 503, upload.text)
                self.assertFalse(formal_root.exists())

                formal_root.mkdir()
                recovered = client.get("/api/app/workdir")

            recovered_data = recovered.json()["data"]
            self.assertTrue(recovered_data["directory_ready"])
            self.assertTrue(recovered_data["processing_allowed"])
            self.assertEqual(Path(recovered_data["app_data_root"]), formal_root)
            self.assertEqual(settings_path.read_bytes(), settings_before)
            self.assertEqual(REPOSITORY_SETTINGS_PATH.read_bytes(), repository_before)

    def test_select_formal_root_write_failure_preserves_memory_disk_and_active_root(self):
        repository_before = REPOSITORY_SETTINGS_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_root = root / "old-formal-root"
            candidate_root = root / "candidate-formal-root"
            old_root.mkdir()
            candidate_root.mkdir()
            settings_path = root / "settings.json"
            settings = json.loads(repository_before)
            settings["app_data_root"] = str(old_root)
            settings["last_app_data_root"] = str(old_root)
            settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
            settings_before = settings_path.read_bytes()

            with (
                isolated_runtime_logging("real-app-select-root-failure"),
                patch.object(main, "SETTINGS_PATH", settings_path),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
                patch.object(
                    main,
                    "initialize_file_logging",
                    return_value={"initialized": False, "degraded": False, "path": None, "reason": "test_controlled"},
                ),
                TestClient(build_web_app(), raise_server_exceptions=False) as client,
            ):
                before = client.get("/api/app/workdir").json()["data"]
                with (
                    patch("runtime.windows_dialog.select_directory", return_value=str(candidate_root)),
                    patch.object(
                        main,
                        "write_settings_if_changed",
                        side_effect=PermissionError("controlled formal-directory settings failure"),
                    ) as writer,
                ):
                    failed = client.post("/api/app/workdir/select-popup", json={})
                after = client.get("/api/app/workdir").json()["data"]

            self.assertEqual(failed.status_code, 500, failed.text)
            self.assertEqual(failed.json()["detail"]["code"], "SETTINGS_WRITE_FAILED")
            self.assertIn("controlled formal-directory settings failure", failed.json()["detail"]["message"])
            self.assertEqual(writer.call_count, 1)
            self.assertEqual(Path(before["app_data_root"]), old_root)
            self.assertEqual(Path(after["app_data_root"]), old_root)
            self.assertTrue(after["directory_ready"])
            self.assertTrue(after["processing_allowed"])
            self.assertNotEqual(Path(after["app_data_root"]), candidate_root)
            self.assertEqual(settings_path.read_bytes(), settings_before)
            self.assertEqual(REPOSITORY_SETTINGS_PATH.read_bytes(), repository_before)

    def test_reset_formal_root_uses_authoritative_default_persists_and_preserves_old_files(self):
        repository_before = REPOSITORY_SETTINGS_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            custom_root = root / "custom-formal-root"
            default_root = root / "default-formal-root"
            custom_root.mkdir()
            default_root.mkdir()
            sentinel = custom_root / "preserve-me.txt"
            sentinel.write_bytes(b"old-custom-file-must-survive")
            settings_path = root / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {"app_data_root": str(custom_root), "last_app_data_root": str(custom_root)},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            with (
                isolated_runtime_logging("real-app-reset-formal-root"),
                patch.object(main, "SETTINGS_PATH", settings_path),
                patch.object(main, "_initial_formal_app_data_root", return_value=default_root),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
                patch.object(
                    main,
                    "initialize_file_logging",
                    return_value={"initialized": False, "degraded": False, "path": None, "reason": "test_controlled"},
                ),
            ):
                with TestClient(build_web_app()) as client:
                    before = client.get("/api/app/workdir").json()["data"]
                    restored = client.post("/api/app/workdir/reset-default", json={})

                    self.assertEqual(Path(before["app_data_root"]), custom_root)
                    self.assertEqual(Path(before["default_app_data_root"]), default_root)
                    self.assertFalse(before["is_default_app_data_root"])
                    self.assertEqual(restored.status_code, 200, restored.text)
                    restored_data = restored.json()["data"]
                    self.assertEqual(Path(restored_data["app_data_root"]), default_root)
                    self.assertEqual(Path(restored_data["formal_output_root"]), default_root / main.OUTPUT_ROOT_RELATIVE)
                    self.assertTrue(restored_data["is_default_app_data_root"])
                    self.assertEqual(sentinel.read_bytes(), b"old-custom-file-must-survive")

                    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
                    self.assertEqual(Path(persisted["app_data_root"]), default_root)
                    self.assertEqual(Path(persisted["last_app_data_root"]), default_root)
                    self.assertEqual(Path(persisted["default_output_dir"]), default_root / main.DEFAULT_OUTPUT_DIR_NAME)
                    self.assertEqual(
                        Path(persisted["image_compression_default_output_root"]),
                        default_root / main.IMAGE_COMPRESSION_OUTPUT_DIR_NAME,
                    )

                    unchanged_before = settings_path.read_bytes()
                    unchanged_mtime = settings_path.stat().st_mtime_ns
                    unchanged = client.post("/api/app/workdir/reset-default", json={})
                    self.assertEqual(unchanged.status_code, 200, unchanged.text)
                    self.assertEqual(unchanged.json()["status"], "unchanged")
                    self.assertTrue(unchanged.json()["write_skipped"])
                    self.assertEqual(settings_path.read_bytes(), unchanged_before)
                    self.assertEqual(settings_path.stat().st_mtime_ns, unchanged_mtime)

                with TestClient(build_web_app()) as restarted_client:
                    after_restart = restarted_client.get("/api/app/workdir").json()["data"]
                    self.assertEqual(Path(after_restart["app_data_root"]), default_root)
                    self.assertEqual(Path(after_restart["formal_output_root"]), default_root / main.OUTPUT_ROOT_RELATIVE)
                    self.assertTrue(after_restart["directory_ready"])
                    self.assertTrue(after_restart["is_default_app_data_root"])

                    from PIL import Image

                    image_buffer = io.BytesIO()
                    Image.new("RGB", (8, 8), color=(45, 111, 232)).save(image_buffer, format="PNG")
                    uploaded = restarted_client.post(
                        "/api/upload",
                        files={"file": ("after-reset.png", image_buffer.getvalue(), "image/png")},
                        data={"mode": "fidelity"},
                    )
                    self.assertEqual(uploaded.status_code, 200, uploaded.text)
                    created_task = restarted_client.app.state.task_registry[uploaded.json()["task_id"]]
                    self.assertEqual(Path(created_task["input_dir"]), default_root / main.DEFAULT_INPUT_DIR_NAME)
                    self.assertEqual(Path(created_task["output_root"]), default_root / main.DEFAULT_OUTPUT_DIR_NAME)

            self.assertEqual(sentinel.read_bytes(), b"old-custom-file-must-survive")
            self.assertEqual(REPOSITORY_SETTINGS_PATH.read_bytes(), repository_before)


class StartupDirectoryAuthorityTests(unittest.TestCase):
    @staticmethod
    def resolved_dirs(formal_root: Path, *, ready: bool = True) -> dict:
        return {
            "app_data_root": formal_root,
            "normal_input_dir": formal_root / main.DEFAULT_INPUT_DIR_NAME,
            "normal_output_dir": formal_root / main.DEFAULT_OUTPUT_DIR_NAME,
            "directory_ready": ready,
            "directory_error_code": "" if ready else "FORMAL_DIRECTORY_NOT_WRITABLE",
            "directory_message": "正式目录已就绪。" if ready else "controlled formal directory failure",
            "failure_reason": "" if ready else "controlled formal directory failure",
        }

    def test_startup_default_dirs_reuse_formal_directory_authority_and_custom_root(self):
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "custom-formal-root"
            resolved = self.resolved_dirs(formal_root)
            settings = {"app_data_root": str(formal_root)}
            with patch.object(main, "resolve_hdde_user_dirs", return_value=resolved) as authority:
                input_path, output_dir = startup_check.default_project_dirs(settings)

            authority.assert_called_once_with(settings)
            self.assertEqual(input_path, formal_root / main.DEFAULT_INPUT_DIR_NAME)
            self.assertEqual(output_dir, formal_root / main.DEFAULT_OUTPUT_DIR_NAME)

    def test_startup_unavailable_formal_directory_returns_blocked_without_fallback(self):
        formal_root = Path("D:/controlled-unavailable-formal-root")
        resolved = self.resolved_dirs(formal_root, ready=False)
        with patch.object(main, "resolve_hdde_user_dirs", return_value=resolved):
            status = startup_check.resolve_default_project_dirs({"app_data_root": str(formal_root)})
            with self.assertRaisesRegex(startup_check.StartupError, "FORMAL_DIRECTORY_NOT_WRITABLE"):
                startup_check.default_project_dirs({"app_data_root": str(formal_root)})

        self.assertEqual(status["status"], "BLOCKED")
        self.assertEqual(status["formal_root"], formal_root)
        self.assertNotIn("runtime_data", str(status))

    def test_startup_module_contains_no_independent_formal_root_or_tmp_fallback(self):
        source = Path(startup_check.__file__).read_text(encoding="utf-8")
        self.assertNotIn("D:/影界文件", source)
        self.assertNotIn("tmp/runtime_data", source.replace("\\", "/"))
        self.assertIn("resolve_hdde_user_dirs", source)


class RequiredDirectoryReadinessTests(unittest.TestCase):
    @staticmethod
    def settings_payload(formal_root: Path) -> dict:
        payload = json.loads(REPOSITORY_SETTINGS_PATH.read_bytes())
        payload["app_data_root"] = ""
        payload["last_app_data_root"] = str(formal_root)
        payload["default_output_dir"] = str(formal_root / main.DEFAULT_OUTPUT_DIR_NAME)
        payload["image_compression_default_output_root"] = str(formal_root / main.IMAGE_COMPRESSION_OUTPUT_DIR_NAME)
        payload["last_output_dir"] = str(formal_root / main.DEFAULT_OUTPUT_DIR_NAME)
        return payload

    def test_normal_required_directories_are_ready_without_settings_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal_root = root / "formal-root"
            formal_root.mkdir()
            settings_path = root / "settings.json"
            settings_path.write_text(json.dumps(self.settings_payload(formal_root), ensure_ascii=False, indent=2), encoding="utf-8")
            before_bytes = settings_path.read_bytes()
            before_mtime = settings_path.stat().st_mtime_ns

            with (
                isolated_runtime_logging("real-app-required-directory-ready"),
                patch.object(main, "SETTINGS_PATH", settings_path),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
            ):
                loaded = main.load_settings()
                user_dirs = main.resolve_hdde_user_dirs(loaded)

            self.assertTrue(user_dirs["directory_ready"])
            self.assertEqual(user_dirs["normal_output_dir"], formal_root / main.DEFAULT_OUTPUT_DIR_NAME)
            self.assertEqual(user_dirs["safe_beta_output_dir"], formal_root / main.LEGACY_SAFE_BETA_OUTPUT_DIR_NAME)
            for key, _directory_name in main.REQUIRED_FORMAL_SUBDIRECTORIES:
                self.assertTrue(Path(user_dirs[key]).is_dir(), key)
            self.assertEqual(user_dirs["delivery_package_dir"], user_dirs["feedback_dir"])
            self.assertEqual(user_dirs["config_dir"], formal_root)
            self.assertFalse((formal_root / "交付包").exists())
            self.assertFalse((formal_root / "配置").exists())
            self.assertEqual(settings_path.read_bytes(), before_bytes)
            self.assertEqual(settings_path.stat().st_mtime_ns, before_mtime)

    def test_output_file_conflict_blocks_processing_without_deleting_user_data_or_writing_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal_root = root / "formal-root"
            conflict_path = formal_root / main.DEFAULT_OUTPUT_DIR_NAME
            conflict_path.parent.mkdir(parents=True, exist_ok=True)
            conflict_bytes = b"user-owned-output-name"
            conflict_path.write_bytes(conflict_bytes)
            user_dir = formal_root / "user-existing"
            user_dir.mkdir()
            user_file = user_dir / "keep.txt"
            user_file.write_text("keep", encoding="utf-8")
            settings_path = root / "settings.json"
            settings_path.write_text(json.dumps(self.settings_payload(formal_root), ensure_ascii=False, indent=2), encoding="utf-8")
            settings_before = settings_path.read_bytes()
            settings_mtime_before = settings_path.stat().st_mtime_ns

            with (
                isolated_runtime_logging("real-app-required-directory-failure"),
                patch.object(main, "SETTINGS_PATH", settings_path),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
                TestClient(build_web_app()) as client,
            ):
                response = client.get("/api/app/workdir")
                upload = client.post("/api/upload", files={"file": ("blocked.png", b"not-decoded", "image/png")})

            data = response.json()["data"]
            self.assertFalse(data["directory_ready"])
            self.assertEqual(data["directory_error_code"], "REQUIRED_DIRECTORY_UNAVAILABLE")
            self.assertEqual(Path(data["failed_path"]), conflict_path)
            self.assertEqual(data["failed_stage"], "type_validation")
            self.assertEqual(Path(data["app_data_root"]), formal_root)
            self.assertFalse(data["processing_allowed"])
            self.assertEqual(upload.status_code, 503, upload.text)
            self.assertEqual(upload.json()["detail"]["code"], "REQUIRED_DIRECTORY_UNAVAILABLE")
            self.assertEqual(conflict_path.read_bytes(), conflict_bytes)
            self.assertEqual(user_file.read_text(encoding="utf-8"), "keep")
            self.assertFalse((formal_root / main.DEFAULT_INPUT_DIR_NAME).exists())
            self.assertEqual(data["cleanup_failures"], [])
            self.assertEqual(settings_path.read_bytes(), settings_before)
            self.assertEqual(settings_path.stat().st_mtime_ns, settings_mtime_before)

    def test_required_directory_create_failure_cleans_only_new_empty_directories_and_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal_root = root / "formal-root"
            formal_root.mkdir()
            existing_user_dir = formal_root / "user-existing"
            existing_user_dir.mkdir()
            existing_file = existing_user_dir / "keep.txt"
            existing_file.write_text("keep", encoding="utf-8")
            failed_path = formal_root / main.DEFAULT_FEEDBACK_DIR_NAME
            settings_path = root / "settings.json"
            settings_path.write_text(json.dumps(self.settings_payload(formal_root), ensure_ascii=False, indent=2), encoding="utf-8")
            settings_before = settings_path.read_bytes()
            settings_mtime_before = settings_path.stat().st_mtime_ns
            original_mkdir = Path.mkdir

            def controlled_mkdir(path: Path, *args, **kwargs):
                if Path(path) == failed_path:
                    raise PermissionError("controlled required-directory create failure")
                return original_mkdir(path, *args, **kwargs)

            with (
                isolated_runtime_logging("real-app-directory-blocking"),
                patch.object(main, "SETTINGS_PATH", settings_path),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
                patch.object(Path, "mkdir", new=controlled_mkdir),
                TestClient(build_web_app()) as client,
            ):
                response = client.get("/api/app/workdir")
                upload = client.post("/api/upload", files={"file": ("blocked.png", b"not-decoded", "image/png")})

            data = response.json()["data"]
            self.assertFalse(data["directory_ready"])
            self.assertEqual(data["directory_error_code"], "REQUIRED_DIRECTORY_UNAVAILABLE")
            self.assertEqual(Path(data["failed_path"]), failed_path)
            self.assertEqual(data["failed_stage"], "create")
            self.assertIn("controlled required-directory create failure", data["failure_reason"])
            self.assertEqual(upload.status_code, 503, upload.text)
            self.assertTrue(existing_user_dir.is_dir())
            self.assertEqual(existing_file.read_text(encoding="utf-8"), "keep")
            self.assertFalse((formal_root / main.DEFAULT_OUTPUT_DIR_NAME).exists())
            self.assertFalse((formal_root / main.DEFAULT_REPORT_DIR_NAME).exists())
            self.assertFalse(failed_path.exists())
            self.assertEqual(data["cleanup_failures"], [])
            self.assertEqual(settings_path.read_bytes(), settings_before)
            self.assertEqual(settings_path.stat().st_mtime_ns, settings_mtime_before)


    def test_concurrently_created_subdirectory_is_not_owned_or_cleaned_when_later_creation_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal_root = root / "formal-root"
            formal_root.mkdir()
            concurrent_path = formal_root / main.IMAGE_COMPRESSION_OUTPUT_DIR_NAME
            concurrent_file = concurrent_path / "keep.txt"
            failed_path = formal_root / main.DEFAULT_FEEDBACK_DIR_NAME
            settings_path = root / "settings.json"
            settings_payload = self.settings_payload(formal_root)
            settings_path.write_text(json.dumps(settings_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            settings_before = settings_path.read_bytes()
            settings_mtime_before = settings_path.stat().st_mtime_ns
            original_mkdir = Path.mkdir
            race_created = False

            def controlled_mkdir(path: Path, *args, **kwargs):
                nonlocal race_created
                if Path(path) == concurrent_path and not race_created:
                    race_created = True
                    original_mkdir(path, *args, **kwargs)
                    concurrent_file.write_text("concurrent-user-data", encoding="utf-8")
                    raise FileExistsError("controlled concurrent subdirectory creation")
                if Path(path) == failed_path:
                    raise PermissionError("controlled later required-directory failure")
                return original_mkdir(path, *args, **kwargs)

            with (
                patch.object(main, "SETTINGS_PATH", settings_path),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
                patch.object(Path, "mkdir", new=controlled_mkdir),
            ):
                result = main.resolve_app_data_root(settings_payload)

            self.assertFalse(result["directory_ready"])
            self.assertEqual(result["error_code"], "REQUIRED_DIRECTORY_UNAVAILABLE")
            self.assertEqual(Path(result["failed_path"]), failed_path)
            self.assertNotIn(str(concurrent_path), result["created_directories"])
            self.assertTrue(concurrent_path.is_dir())
            self.assertEqual(concurrent_file.read_text(encoding="utf-8"), "concurrent-user-data")
            self.assertFalse((formal_root / main.DEFAULT_OUTPUT_DIR_NAME).exists())
            self.assertFalse((formal_root / main.DEFAULT_REPORT_DIR_NAME).exists())
            self.assertEqual(
                {Path(item["path"]) for item in result["cleanup_failures"]},
                {formal_root / main.OUTPUT_ROOT_RELATIVE},
            )
            self.assertEqual(settings_path.read_bytes(), settings_before)
            self.assertEqual(settings_path.stat().st_mtime_ns, settings_mtime_before)

    def test_concurrently_created_root_is_not_owned_or_cleaned_when_child_creation_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal_root = root / "formal-root"
            failed_path = formal_root / main.DEFAULT_FEEDBACK_DIR_NAME
            settings_path = root / "settings.json"
            settings_payload = self.settings_payload(formal_root)
            settings_payload["app_data_root"] = ""
            settings_payload["last_app_data_root"] = ""
            settings_path.write_text(json.dumps(settings_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            settings_before = settings_path.read_bytes()
            settings_mtime_before = settings_path.stat().st_mtime_ns
            original_mkdir = Path.mkdir
            race_created = False

            def controlled_mkdir(path: Path, *args, **kwargs):
                nonlocal race_created
                if Path(path) == formal_root and not race_created:
                    race_created = True
                    original_mkdir(path, *args, **kwargs)
                    raise FileExistsError("controlled concurrent root creation")
                if Path(path) == failed_path:
                    raise PermissionError("controlled later required-directory failure")
                return original_mkdir(path, *args, **kwargs)

            with (
                patch.object(main, "SETTINGS_PATH", settings_path),
                patch.object(main, "_initial_formal_app_data_root", return_value=formal_root),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
                patch.object(Path, "mkdir", new=controlled_mkdir),
            ):
                result = main.resolve_app_data_root(settings_payload)

            self.assertFalse(result["directory_ready"])
            self.assertEqual(result["error_code"], "REQUIRED_DIRECTORY_UNAVAILABLE")
            self.assertEqual(Path(result["failed_path"]), failed_path)
            self.assertNotIn(str(formal_root), result["created_directories"])
            self.assertTrue(formal_root.is_dir())
            self.assertFalse((formal_root / main.DEFAULT_INPUT_DIR_NAME).exists())
            self.assertFalse((formal_root / main.DEFAULT_OUTPUT_DIR_NAME).exists())
            self.assertFalse((formal_root / main.DEFAULT_REPORT_DIR_NAME).exists())
            self.assertEqual(result["cleanup_failures"], [])
            self.assertEqual(settings_path.read_bytes(), settings_before)
            self.assertEqual(settings_path.stat().st_mtime_ns, settings_mtime_before)


class SettingsWriteIdempotencyTests(unittest.TestCase):
    @staticmethod
    def controlled_root_info(path: Path) -> dict:
        return {
            "path": str(path),
            "source": "test_controlled",
            "exists": True,
            "writable": True,
            "directory_ready": True,
            "error_code": "",
            "error": "",
            "message": "正式目录已就绪。",
            "created": False,
            "first_initialization": False,
        }

    def test_unchanged_settings_skip_write_and_preserve_file_metadata(self):
        payload = {"target_resolution": "1080P", "default_output_format": "png"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")
            before_bytes = path.read_bytes()
            before_sha = hashlib.sha256(before_bytes).hexdigest()
            before_size = path.stat().st_size
            before_mtime = path.stat().st_mtime_ns

            with patch.object(main, "SETTINGS_PATH", path):
                result = main.write_settings_if_changed(dict(payload))

            self.assertEqual(result["status"], "SKIPPED_UNCHANGED")
            self.assertTrue(result["write_skipped"])
            self.assertFalse(result["write_performed"])
            self.assertEqual(path.read_bytes(), before_bytes)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before_sha)
            self.assertEqual(path.stat().st_size, before_size)
            self.assertEqual(path.stat().st_mtime_ns, before_mtime)

    def test_changed_settings_are_written(self):
        current = {"target_resolution": "1080P", "default_output_format": "png"}
        changed = {**current, "default_output_format": "jpg"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")

            with patch.object(main, "SETTINGS_PATH", path):
                result = main.write_settings_if_changed(changed)

            self.assertEqual(result["status"], "WRITE_PERFORMED")
            self.assertFalse(result["write_skipped"])
            self.assertTrue(result["write_performed"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), changed)

    def test_invalid_existing_settings_keep_safe_rewrite_behavior(self):
        replacement = {"target_resolution": "1080P", "default_output_format": "png"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text("{invalid-json", encoding="utf-8")

            with patch.object(main, "SETTINGS_PATH", path):
                result = main.write_settings_if_changed(replacement)

            self.assertEqual(result["status"], "WRITE_PERFORMED")
            self.assertTrue(result["write_performed"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), replacement)

    def test_stable_load_settings_skips_write(self):
        repository_before = REPOSITORY_SETTINGS_PATH.read_bytes()
        payload = json.loads(repository_before)
        controlled_root = Path(payload["last_app_data_root"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_bytes(repository_before)
            before_bytes = path.read_bytes()
            before_mtime = path.stat().st_mtime_ns
            before_byte_sha = hashlib.sha256(before_bytes).hexdigest()
            before_semantic_sha = semantic_sha256(before_bytes)
            before_size = len(before_bytes)
            write_results = []
            original_writer = main.write_settings_if_changed

            def capture_write_result(next_settings: dict) -> dict:
                result = original_writer(next_settings)
                write_results.append(result)
                return result

            with (
                patch.object(main, "SETTINGS_PATH", path),
                patch.object(main, "resolve_app_data_root", return_value=self.controlled_root_info(controlled_root)),
                patch.object(main, "write_settings_if_changed", side_effect=capture_write_result),
            ):
                loaded = main.load_settings()

            self.assertEqual(loaded, payload)
            self.assertEqual(write_results, [])
            self.assertEqual(path.read_bytes(), before_bytes)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before_byte_sha)
            self.assertEqual(semantic_sha256(path.read_bytes()), before_semantic_sha)
            self.assertEqual(path.stat().st_size, before_size)
            self.assertEqual(path.stat().st_mtime_ns, before_mtime)
            self.assertEqual(REPOSITORY_SETTINGS_PATH.read_bytes(), repository_before)

    def test_first_initialization_writes_formal_root_to_temporary_settings_only(self):
        repository_before = REPOSITORY_SETTINGS_PATH.read_bytes()
        repository_mtime = REPOSITORY_SETTINGS_PATH.stat().st_mtime_ns
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "settings.json"
            controlled_root = root / "controlled-app-data"
            controlled_root.mkdir()
            first_initialization_payload = json.loads(repository_before)
            first_initialization_payload["app_data_root"] = ""
            first_initialization_payload["last_app_data_root"] = ""
            path.write_text(json.dumps(first_initialization_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            write_results = []
            original_writer = main.write_settings_if_changed

            def capture_write_result(next_settings: dict) -> dict:
                result = original_writer(next_settings)
                write_results.append(result)
                return result

            with (
                patch.object(main, "SETTINGS_PATH", path),
                patch.object(main, "resolve_app_data_root", return_value=self.controlled_root_info(controlled_root)),
                patch.object(main, "write_settings_if_changed", side_effect=capture_write_result),
            ):
                loaded = main.load_settings()

            self.assertEqual(write_results[-1]["status"], "WRITE_PERFORMED")
            self.assertEqual(loaded["last_app_data_root"], str(controlled_root))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), loaded)
            self.assertEqual(REPOSITORY_SETTINGS_PATH.read_bytes(), repository_before)
            self.assertEqual(REPOSITORY_SETTINGS_PATH.stat().st_mtime_ns, repository_mtime)

    def test_directory_failure_never_creates_or_rewrites_missing_incomplete_or_invalid_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal_root = root / "unavailable-formal-root"
            failure_info = {
                "path": str(formal_root),
                "source": "initial_default",
                "exists": False,
                "writable": False,
                "directory_ready": False,
                "error_code": "FORMAL_DIRECTORY_CREATE_FAILED",
                "error": "controlled create failure",
                "message": "正式目录不存在且无法创建，请前往系统设置重新选择目录。",
                "created": False,
                "first_initialization": True,
            }
            cases = {
                "missing": None,
                "incomplete": json.dumps({"last_app_data_root": str(formal_root)}, ensure_ascii=False).encode("utf-8"),
                "invalid": b"{invalid-json",
            }

            for name, initial_bytes in cases.items():
                with self.subTest(name=name):
                    settings_path = root / name / "settings.json"
                    if initial_bytes is not None:
                        settings_path.parent.mkdir(parents=True, exist_ok=True)
                        settings_path.write_bytes(initial_bytes)
                        before_bytes = settings_path.read_bytes()
                        before_mtime = settings_path.stat().st_mtime_ns
                    with (
                        patch.object(main, "SETTINGS_PATH", settings_path),
                        patch.object(main, "resolve_app_data_root", return_value=failure_info),
                    ):
                        loaded = main.load_settings()

                    self.assertEqual(loaded["last_app_data_root"], str(formal_root) if name == "incomplete" else "")
                    if initial_bytes is None:
                        self.assertFalse(settings_path.exists())
                    else:
                        self.assertEqual(settings_path.read_bytes(), before_bytes)
                        self.assertEqual(settings_path.stat().st_mtime_ns, before_mtime)


class DirectoryFailureBlockingTests(unittest.TestCase):
    def test_unavailable_formal_directory_reports_blocked_and_prevents_upload_without_settings_mutation(self):
        repository_before = REPOSITORY_SETTINGS_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings_path = root / "settings.json"
            settings_path.write_bytes(repository_before)
            settings_before = settings_path.read_bytes()
            settings_mtime_before = settings_path.stat().st_mtime_ns
            isolated_project_root = root / "isolated-project"
            isolated_project_root.mkdir()
            formal_root = root / "unavailable-formal-root"
            failure_info = {
                "path": str(formal_root),
                "source": "saved_config",
                "exists": True,
                "writable": False,
                "directory_ready": False,
                "error_code": "FORMAL_DIRECTORY_NOT_WRITABLE",
                "error": "controlled permission denied",
                "message": "正式目录不可写，请前往系统设置重新选择目录。",
                "created": False,
                "first_initialization": False,
            }

            with (
                isolated_runtime_logging("real-app-unavailable-formal-directory"),
                patch.object(main, "SETTINGS_PATH", settings_path),
                patch.object(main, "PROJECT_ROOT", isolated_project_root),
                patch.object(main, "resolve_app_data_root", return_value=failure_info),
                TestClient(build_web_app()) as client,
            ):
                response = client.get("/api/app/workdir")
                upload = client.post("/api/upload", files={"file": ("blocked.png", b"not-decoded", "image/png")})
                compression_intake = client.post("/api/image-compression/intake", files={"file": ("blocked.png", b"not-decoded", "image/png")})
                compression_preflight = client.post("/api/image-processing/preflight", json={})
                compression_run = client.post("/api/image-compression/run", json={})
                compression_output = client.get("/api/image-compression/output-settings")

            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()["data"]
            self.assertFalse(data["directory_ready"])
            self.assertEqual(data["directory_error_code"], "FORMAL_DIRECTORY_NOT_WRITABLE")
            self.assertEqual(Path(data["app_data_root"]), formal_root)
            self.assertFalse(data["processing_allowed"])
            self.assertEqual(data["output_dir"], "")
            self.assertEqual(data["beta_output_dir"], "")
            self.assertNotIn("runtime_data", json.dumps(response.json(), ensure_ascii=False))
            self.assertEqual(upload.status_code, 503, upload.text)
            self.assertEqual(upload.json()["detail"]["code"], "FORMAL_DIRECTORY_NOT_WRITABLE")
            for blocked_response in (compression_intake, compression_preflight, compression_run, compression_output):
                self.assertEqual(blocked_response.status_code, 503, blocked_response.text)
                self.assertEqual(blocked_response.json()["detail"]["code"], "FORMAL_DIRECTORY_NOT_WRITABLE")
            self.assertFalse((isolated_project_root / "tmp").exists())
            self.assertFalse((isolated_project_root / "runtime").exists())
            self.assertEqual(settings_path.read_bytes(), settings_before)
            self.assertEqual(settings_path.stat().st_mtime_ns, settings_mtime_before)
            self.assertEqual(REPOSITORY_SETTINGS_PATH.read_bytes(), repository_before)


class RuntimeStatusHelperTests(unittest.TestCase):
    def test_build_identity_reads_existing_artifact_without_git_or_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset_dir = root / "dist" / "assets"
            asset_dir.mkdir(parents=True)
            build_id = "V0.5.4-dev+4ed3864f6d41.dirty.20260809T104354843Z"
            index_path = root / "dist" / "index.html"
            asset_path = asset_dir / "index-controlled.js"
            index_path.write_text('<script type="module" src="/assets/index-controlled.js"></script>', encoding="utf-8")
            asset_path.write_text(f'const buildId = "{build_id}";', encoding="utf-8")
            before = {
                path.relative_to(root): (path.is_dir(), path.stat().st_size, path.stat().st_mtime_ns)
                for path in root.rglob("*")
            }

            result = main.read_frontend_build_identity(root, "V0.5.4-dev")

            after = {
                path.relative_to(root): (path.is_dir(), path.stat().st_size, path.stat().st_mtime_ns)
                for path in root.rglob("*")
            }
            self.assertEqual(result["status"], "loaded")
            self.assertEqual(result["build_id"], build_id)
            self.assertEqual(Path(result["source_path"]), asset_path)
            self.assertEqual(after, before)

    def test_formal_root_presence_check_does_not_create_missing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            missing_root = Path(directory) / "missing-formal-root"
            result = main.read_only_formal_root_status(
                {
                    "app_data_root": missing_root,
                    "app_data_root_source": "user_config",
                    "app_data_root_writable": True,
                    "directory_ready": True,
                }
            )
            self.assertFalse(result["directory_ready"])
            self.assertEqual(result["error_code"], "FORMAL_DIRECTORY_STATE_CHANGED")
            self.assertFalse(missing_root.exists())

    def test_formal_root_access_error_returns_blocked_status(self):
        with patch.object(Path, "exists", side_effect=PermissionError("access denied")):
            result = main.read_only_formal_root_status(
                {
                    "app_data_root": Path("D:/formal-root"),
                    "app_data_root_source": "user_config",
                    "app_data_root_writable": True,
                    "directory_ready": True,
                }
            )

        self.assertFalse(result["directory_ready"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["error_code"], "FORMAL_DIRECTORY_READ_FAILED")
        self.assertIn("access denied", result["reason"])


class RealApplicationPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository_settings_before = REPOSITORY_SETTINGS_PATH.read_bytes()
        cls.repository_settings_mtime_before = REPOSITORY_SETTINGS_PATH.stat().st_mtime_ns
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary_directory.cleanup)
        temporary_root = Path(cls.temporary_directory.name)
        cls.test_settings_path = temporary_root / "settings.json"
        cls.test_settings_path.write_bytes(cls.repository_settings_before)
        cls.controlled_app_data_root = temporary_root / "controlled-app-data"
        cls.controlled_app_data_root.mkdir()
        cls.settings_path_patch = patch.object(main, "SETTINGS_PATH", cls.test_settings_path)
        cls.settings_path_patch.start()
        cls.addClassCleanup(cls.settings_path_patch.stop)
        cls.app_data_root_patch = patch.object(
            main,
            "resolve_app_data_root",
            return_value=SettingsWriteIdempotencyTests.controlled_root_info(cls.controlled_app_data_root),
        )
        cls.app_data_root_patch.start()
        cls.addClassCleanup(cls.app_data_root_patch.stop)
        cls.runtime_log_isolation = isolated_runtime_logging("real-app-preflight-class")
        cls.runtime_log_isolation.__enter__()
        cls.addClassCleanup(cls.runtime_log_isolation.__exit__, None, None, None)
        cls.addClassCleanup(runtime_logging.reset_runtime_logging_for_tests)
        cls.client = TestClient(build_web_app())
        cls.addClassCleanup(cls.client.close)

    def test_real_app_uses_temporary_settings_without_repository_mutation(self):
        self.assertEqual(main.SETTINGS_PATH, self.test_settings_path)
        self.assertEqual(REPOSITORY_SETTINGS_PATH.read_bytes(), self.repository_settings_before)
        self.assertEqual(REPOSITORY_SETTINGS_PATH.stat().st_mtime_ns, self.repository_settings_mtime_before)

    def test_real_app_exposes_current_product_version(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["version"], main.APP_VERSION)

    def test_health_is_read_only_for_settings_and_formal_root(self):
        settings_before = self.test_settings_path.read_bytes()
        settings_mtime_before = self.test_settings_path.stat().st_mtime_ns

        def tree_state(root: Path) -> dict:
            paths = [root, *root.rglob("*")]
            return {
                path.relative_to(root): (path.is_dir(), path.stat().st_size, path.stat().st_mtime_ns)
                for path in paths
            }

        formal_root_before = tree_state(self.controlled_app_data_root)
        with (
            patch.object(main, "resolve_app_data_root", side_effect=AssertionError("health must not resolve or probe")),
            patch.object(main, "write_settings_if_changed", side_effect=AssertionError("health must not write settings")),
        ):
            responses = [self.client.get("/api/health") for _ in range(2)]
        formal_root_after = tree_state(self.controlled_app_data_root)

        for response in responses:
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertTrue(payload["success"])
            self.assertEqual(payload["status"], "success")
            self.assertTrue(payload["data"]["healthy"])
            self.assertTrue(payload["data"]["directory_ready"])
            self.assertEqual(payload["data"]["settings_status"], "loaded")
            self.assertEqual(
                payload["data"]["health_basis"],
                "startup_validation_plus_read_only_presence_check",
            )
        self.assertEqual(self.test_settings_path.read_bytes(), settings_before)
        self.assertEqual(self.test_settings_path.stat().st_mtime_ns, settings_mtime_before)
        self.assertEqual(formal_root_after, formal_root_before)
        self.assertEqual(REPOSITORY_SETTINGS_PATH.read_bytes(), self.repository_settings_before)

    def test_health_reports_degraded_read_only_directory_state(self):
        blocked_status = {
            "status": "blocked",
            "path": str(self.controlled_app_data_root),
            "source": "test_controlled",
            "directory_ready": False,
            "exists": False,
            "writable_at_startup": True,
            "startup_validation_ready": True,
            "required_directories_present": False,
            "missing_required_directories": [str(self.controlled_app_data_root / "missing")],
            "error_code": "FORMAL_DIRECTORY_STATE_CHANGED",
            "failed_path": str(self.controlled_app_data_root),
            "failed_stage": "read_only_presence_check",
            "reason": "missing",
            "validation_basis": "startup_validation_plus_read_only_presence_check",
        }
        with patch.object(main, "read_only_formal_root_status", return_value=blocked_status):
            response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["status"], "degraded")
        self.assertFalse(payload["data"]["healthy"])
        self.assertFalse(payload["data"]["directory_ready"])
        self.assertEqual(payload["data"]["directory_error_code"], "FORMAL_DIRECTORY_STATE_CHANGED")

    def test_runtime_status_unifies_read_only_runtime_and_formal_directory_state(self):
        settings_before = self.test_settings_path.read_bytes()
        settings_mtime_before = self.test_settings_path.stat().st_mtime_ns

        def tree_state(root: Path) -> dict:
            return {
                path.relative_to(root): (path.is_dir(), path.stat().st_size, path.stat().st_mtime_ns)
                for path in root.rglob("*")
            }

        formal_root_before = tree_state(self.controlled_app_data_root)
        response = self.client.get("/api/runtime/status")
        formal_root_after = tree_state(self.controlled_app_data_root)

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["success"])
        data = payload["data"]
        self.assertTrue(data["read_only"])
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["product"]["version"], main.APP_VERSION)
        self.assertRegex(
            data["product"]["build_id"],
            rf"^V{re.escape(main.PRODUCT_VERSION)}\+(?:[0-9a-f]{{7,12}}|nogit)\.(?:clean|dirty|unknown)\.\d{{8}}T\d{{9}}Z$",
        )
        self.assertEqual(data["product"]["build_status"], "loaded")
        self.assertEqual(data["application"]["status"], "running")
        self.assertRegex(data["application"]["runtime_id"], r"^RUN-\d{8}T\d{6}-[0-9A-F]{10}$")
        self.assertEqual(data["application"]["runtime_id"], self.client.app.state.runtime_id)
        self.assertGreaterEqual(data["application"]["uptime_seconds"], 0)
        self.assertEqual(data["application"]["host"], main.SERVER_HOST)
        self.assertEqual(data["application"]["port"], main.SERVER_PORT)
        self.assertEqual(data["settings"]["status"], "loaded")
        self.assertEqual(Path(data["settings"]["file_path"]), self.test_settings_path)
        self.assertTrue(data["formal_root"]["directory_ready"])
        self.assertEqual(Path(data["formal_root"]["path"]), self.controlled_app_data_root)
        self.assertEqual(self.test_settings_path.read_bytes(), settings_before)
        self.assertEqual(self.test_settings_path.stat().st_mtime_ns, settings_mtime_before)
        self.assertEqual(formal_root_after, formal_root_before)
        self.assertEqual(REPOSITORY_SETTINGS_PATH.read_bytes(), self.repository_settings_before)

    def test_real_app_registers_preflight_route(self):
        routes = {route.path for route in self.client.app.routes}
        self.assertIn("/api/image-processing/preflight", routes)
        self.assertFalse(any(route.startswith("/api/image-diagnosis") for route in routes))

    def test_real_app_preserves_stage4_missing_token_semantics(self):
        response = self.client.post(
            "/api/image-processing/preflight",
            json={
                "file_token": "missing-real-service-token",
                "purpose": "REDUCE_FILE_SIZE",
                "targets": {},
                "requested_action": None,
            },
        )
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["detail"]["code"], "TOKEN_NOT_FOUND_OR_EXPIRED")

    def test_app_workdir_exposes_formal_standard_and_beta_output_directories(self):
        formal_root = Path("D:/") / main.LEGACY_WORK_DIR_NAME
        unavailable_input = Path(self.temporary_directory.name) / "unavailable-input"
        unavailable_beta_upload = Path(self.temporary_directory.name) / "unavailable-beta-upload"
        user_dirs = {
            "app_data_root": formal_root,
            "app_data_root_source": "d_drive",
            "app_data_root_exists": True,
            "app_data_root_writable": True,
            "directory_ready": True,
            "directory_error_code": "",
            "directory_message": "正式目录已就绪。",
            "normal_input_dir": unavailable_input,
            "normal_output_dir": formal_root / main.DEFAULT_OUTPUT_DIR_NAME,
            "image_compression_output_dir": formal_root / main.IMAGE_COMPRESSION_OUTPUT_DIR_NAME,
            "report_dir": formal_root / main.DEFAULT_REPORT_DIR_NAME,
            "feedback_dir": formal_root / main.DEFAULT_FEEDBACK_DIR_NAME,
            "tmp_dir": formal_root / main.DEFAULT_TMP_DIR_NAME,
            "beta_upload_dir": unavailable_beta_upload,
            "delivery_package_dir": formal_root / main.DEFAULT_DELIVERY_PACKAGE_DIR_NAME,
            "config_dir": formal_root / main.DEFAULT_CONFIG_DIR_NAME,
            "safe_beta_input_root": formal_root / main.LEGACY_SAFE_BETA_INPUT_DIR_NAME,
            "safe_beta_output_dir": formal_root / main.LEGACY_SAFE_BETA_OUTPUT_DIR_NAME,
            "safe_beta_feedback_dir": formal_root / main.LEGACY_SAFE_BETA_FEEDBACK_DIR_NAME,
            "runtime_log_dir": formal_root / main.RUNTIME_LOG_DIR_NAME,
        }

        with patch.object(main, "resolve_hdde_user_dirs", return_value=user_dirs):
            response = self.client.get("/api/app/workdir")

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(Path(data["output_dir"]), formal_root / main.DEFAULT_OUTPUT_DIR_NAME)
        self.assertEqual(Path(data["beta_output_dir"]), formal_root / main.LEGACY_SAFE_BETA_OUTPUT_DIR_NAME)
        self.assertEqual(data["app_data_root_source"], "d_drive")
        self.assertTrue(data["directory_ready"])


class RuntimeLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        runtime_logging.reset_runtime_logging_for_tests()

    def tearDown(self) -> None:
        runtime_logging.reset_runtime_logging_for_tests()

    @staticmethod
    def settings_payload(formal_root: Path) -> dict:
        payload = json.loads(REPOSITORY_SETTINGS_PATH.read_bytes())
        payload["app_data_root"] = ""
        payload["last_app_data_root"] = str(formal_root)
        payload["default_output_dir"] = str(formal_root / main.DEFAULT_OUTPUT_DIR_NAME)
        payload["image_compression_default_output_root"] = str(formal_root / main.IMAGE_COMPRESSION_OUTPUT_DIR_NAME)
        payload["last_output_dir"] = str(formal_root / main.DEFAULT_OUTPUT_DIR_NAME)
        return payload

    def test_file_logging_uses_formal_root_rotation_and_idempotent_handler(self):
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "formal-root"
            formal_root.mkdir()

            first = runtime_logging.initialize_file_logging(formal_root)
            second = runtime_logging.initialize_file_logging(formal_root)
            runtime_logging.log_runtime_event("TEST_SINGLE_EVENT", stage="test", result="success")
            state = runtime_logging.runtime_logging_state()

            expected_path = formal_root / "诊断" / "日志" / "hdde.log"
            self.assertTrue(first["initialized"])
            self.assertTrue(second["initialized"])
            self.assertEqual(Path(first["path"]), expected_path)
            self.assertEqual(Path(state["path"]), expected_path)
            self.assertEqual(state["file_handler_count"], 1)
            logger = logging.getLogger(runtime_logging.LOGGER_NAME)
            file_handlers = [handler for handler in logger.handlers if getattr(handler, "_hdde_runtime_handler", None) == "file"]
            self.assertEqual(len(file_handlers), 1)
            self.assertEqual(file_handlers[0].maxBytes, 5 * 1024 * 1024)
            self.assertEqual(file_handlers[0].backupCount, 3)
            content = expected_path.read_text(encoding="utf-8")
            self.assertEqual(content.count("event=RUNTIME_LOGGING_INITIALIZED"), 1)
            self.assertEqual(content.count("event=TEST_SINGLE_EVENT"), 1)
            self.assertIn(main.RUNTIME_LOG_DIR_NAME, {name for _key, name in main.REQUIRED_FORMAL_SUBDIRECTORIES})
            runtime_logging.reset_runtime_logging_for_tests()

    def test_runtime_events_redact_absolute_paths_and_secrets(self):
        with capture_runtime_log() as captured:
            runtime_logging.log_runtime_event(
                "PRIVACY_BOUNDARY_TEST",
                stage="controlled_test",
                result="failed",
                path=r"C:\Users\private-user\business\source.png",
                runtime_log_reference="诊断/日志/hdde.log",
                reason=r"read failed at C:\Users\private-user\business\source.png; token=private-token",
            )

        output = captured.getvalue()
        self.assertIn("event=PRIVACY_BOUNDARY_TEST", output)
        self.assertRegex(output, r"path=file_[0-9a-f]{12}\.png")
        self.assertNotIn("source.png", output)
        self.assertIn("runtime_log_reference=诊断/日志/hdde.log", output)
        self.assertIn("reason=read failed at <redacted_path>", output)
        self.assertIn("token=<redacted>", output)
        self.assertNotIn(r"C:\Users\private-user", output)
        self.assertNotIn("private-token", output)

    def test_file_logging_failure_degrades_to_console_without_temp_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "formal-root"
            formal_root.mkdir()
            blocked_parent = formal_root / "诊断" / "日志"
            original_mkdir = Path.mkdir

            def controlled_mkdir(path: Path, *args, **kwargs):
                if Path(path) == blocked_parent:
                    raise PermissionError("controlled runtime log directory failure")
                return original_mkdir(path, *args, **kwargs)

            with capture_runtime_log() as captured, patch.object(Path, "mkdir", new=controlled_mkdir):
                result = runtime_logging.initialize_file_logging(formal_root)
                runtime_logging.log_runtime_event("CONSOLE_STILL_AVAILABLE", result="success")

            output = captured.getvalue()
            self.assertFalse(result["initialized"])
            self.assertTrue(result["degraded"])
            self.assertIn("event=RUNTIME_LOGGING_DEGRADED", output)
            self.assertIn("error_category=ENVIRONMENT_ERROR", output)
            self.assertIn("event=CONSOLE_STILL_AVAILABLE", output)
            self.assertFalse((blocked_parent / "hdde.log").exists())
            self.assertNotIn("project_tmp", output)
            self.assertNotIn("runtime_data", output)
            self.assertEqual(runtime_logging.runtime_logging_state()["file_handler_count"], 0)

    def test_application_settings_and_directory_events_are_real_and_non_mutating(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal_root = root / "formal-root"
            formal_root.mkdir()
            settings_path = root / "settings.json"
            settings_payload = self.settings_payload(formal_root)
            settings_path.write_text(json.dumps(settings_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            settings_before = settings_path.read_bytes()
            settings_mtime_before = settings_path.stat().st_mtime_ns

            with (
                controlled_test_app_paths(settings_path, formal_root),
                capture_runtime_log() as captured,
                patch.object(main, "SETTINGS_PATH", settings_path),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
            ):
                build_web_app()

            output = captured.getvalue()
            log_path = formal_root / "诊断" / "日志" / "hdde.log"
            file_content = log_path.read_text(encoding="utf-8")
            self.assertIn("event=APPLICATION_STARTING", output)
            self.assertIn("event=SETTINGS_READ_SUCCEEDED", output)
            self.assertIn("event=SETTINGS_WRITE_SKIPPED", output)
            self.assertIn("event=DIRECTORY_VALIDATION_SUCCEEDED", output)
            self.assertIn("event=APPLICATION_STARTUP_COMPLETED", output)
            self.assertIn("event=RUNTIME_LOGGING_INITIALIZED", file_content)
            self.assertIn("event=DIRECTORY_VALIDATION_SUCCEEDED", file_content)
            self.assertIn("event=APPLICATION_STARTUP_COMPLETED", file_content)
            self.assertNotIn("event=APPLICATION_STARTING", file_content)
            self.assertEqual(settings_path.read_bytes(), settings_before)
            self.assertEqual(settings_path.stat().st_mtime_ns, settings_mtime_before)
            runtime_logging.reset_runtime_logging_for_tests()

    def test_configuration_and_directory_failures_have_real_error_categories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid_settings_path = root / "invalid-settings.json"
            invalid_settings_path.write_bytes(b"{invalid-json")
            invalid_before = invalid_settings_path.read_bytes()
            default_root = root / "default-formal-root"
            with (
                controlled_test_app_paths(invalid_settings_path, default_root),
                capture_runtime_log() as configuration_events,
                patch.object(main, "SETTINGS_PATH", invalid_settings_path),
                patch.object(main, "_initial_formal_app_data_root", return_value=default_root),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
            ):
                build_web_app()

            self.assertIn("event=SETTINGS_READ_FAILED", configuration_events.getvalue())
            self.assertIn("error_category=CONFIGURATION_ERROR", configuration_events.getvalue())
            self.assertEqual(invalid_settings_path.read_bytes(), invalid_before)

            runtime_logging.reset_runtime_logging_for_tests()
            blocked_root = root / "blocked-formal-root"
            blocked_root.write_bytes(b"user-owned-file")
            blocked_settings_path = root / "blocked-settings.json"
            blocked_settings_path.write_text(
                json.dumps(self.settings_payload(blocked_root), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            blocked_before = blocked_settings_path.read_bytes()
            with (
                controlled_test_app_paths(blocked_settings_path, blocked_root),
                capture_runtime_log() as directory_events,
                patch.object(main, "SETTINGS_PATH", blocked_settings_path),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
            ):
                build_web_app()

            output = directory_events.getvalue()
            self.assertIn("event=DIRECTORY_VALIDATION_FAILED", output)
            self.assertIn("error_category=ENVIRONMENT_ERROR", output)
            self.assertIn("impact=image_processing_blocked", output)
            self.assertFalse((blocked_root.parent / "诊断").exists())
            self.assertEqual(blocked_root.read_bytes(), b"user-owned-file")
            self.assertEqual(blocked_settings_path.read_bytes(), blocked_before)

    def test_real_image_task_logs_route_success_failures_output_error_and_duration(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            formal_root = root / "formal-root"
            formal_root.mkdir()
            settings_path = root / "settings.json"
            settings_path.write_text(
                json.dumps(self.settings_payload(formal_root), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            settings_before = settings_path.read_bytes()
            settings_mtime_before = settings_path.stat().st_mtime_ns

            def fake_output_plan(input_path, output_root, *_args, **_kwargs):
                source = Path(input_path)
                final_path = Path(output_root) / f"{source.stem}_final.png"
                return {
                    "paths": {"final": final_path},
                    "image_type": "test_fixture",
                    "input_width": 1,
                    "input_height": 1,
                    "output_width": 1,
                    "output_height": 1,
                    "resize_policy": "none",
                    "was_upscaled": False,
                    "was_downscaled": False,
                }

            def fake_process(payload):
                source = Path(payload["input_path"])
                if source.name.startswith("product-error"):
                    raise RuntimeError("controlled product failure")
                if source.name.startswith("non-output-io-error"):
                    raise OSError("controlled image processing I/O failure")
                final_path = Path(payload["output_root"]) / f"{source.stem}_final.png"
                final_path.write_bytes(b"processed")
                return {
                    "final_output_path": final_path,
                    "task_result": {
                        "output_format": "png",
                        "output_size": final_path.stat().st_size if final_path.exists() else 0,
                        "resize_policy": "none",
                        "was_upscaled": False,
                        "was_downscaled": False,
                    },
                    "task_report": {},
                    "image_type": "test_fixture",
                    "degradation_type": "none",
                    "input_width": 1,
                    "input_height": 1,
                    "output_width": 1,
                    "output_height": 1,
                    "input_size_bytes": source.stat().st_size,
                    "output_changed": True,
                    "hash_equal": False,
                    "pixel_diff_score": 1.0,
                    "debug_timing": {},
                    "debug_quality": {},
                }

            def wait_for_status(client: TestClient, task_id: str, expected: str) -> None:
                for _attempt in range(50):
                    response = client.get(f"/api/v1/tasks/{task_id}")
                    if response.json()["data"]["task_status"] == expected:
                        return
                    time.sleep(0.01)
                self.fail(f"task {task_id} did not reach {expected}")

            def events_for_task(events: list[dict[str, str]], task_id: str, event: str | None = None) -> list[dict[str, str]]:
                matches = [item for item in events if item.get("task_id") == task_id]
                return [item for item in matches if item.get("event") == event] if event else matches

            from starlette.datastructures import UploadFile as StarletteUploadFile

            original_upload_read = StarletteUploadFile.read

            async def controlled_upload_read(upload, size: int = -1):
                if upload.filename == "input-read-error.png":
                    raise OSError("controlled input read failure")
                return await original_upload_read(upload, size)

            with (
                controlled_test_app_paths(settings_path, formal_root),
                capture_runtime_records() as captured_records,
                patch.object(main, "SETTINGS_PATH", settings_path),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
                patch("backend.v036_output_core.build_output_plan", side_effect=fake_output_plan),
                patch("backend.v036_output_core.sha256_file", return_value="fixture-sha256"),
                patch("engine.pipeline.process_v046_delivery", side_effect=fake_process),
                TestClient(build_web_app()) as client,
            ):
                with patch.object(StarletteUploadFile, "read", new=controlled_upload_read):
                    input_read_error = client.post(
                        "/api/upload",
                        files={"file": ("input-read-error.png", b"fixture", "image/png")},
                        data={"mode": "texture"},
                    )
                self.assertEqual(input_read_error.status_code, 500, input_read_error.text)

                empty = client.post("/api/upload", files={"file": ("empty.png", b"", "image/png")}, data={"mode": "texture"})
                self.assertEqual(empty.status_code, 400, empty.text)

                blocked_output = root / "blocked-output"
                original_mkdir = Path.mkdir

                def controlled_output_mkdir(path: Path, *args, **kwargs):
                    if Path(path) == blocked_output:
                        raise PermissionError("controlled output directory create failure")
                    return original_mkdir(path, *args, **kwargs)

                with patch.object(Path, "mkdir", new=controlled_output_mkdir):
                    output_directory_error = client.post(
                        "/api/upload",
                        files={"file": ("output-directory-error.png", b"fixture", "image/png")},
                        data={"mode": "texture", "output_dir": str(blocked_output)},
                    )
                self.assertEqual(output_directory_error.status_code, 400, output_directory_error.text)

                success = client.post("/api/upload", files={"file": ("success.png", b"fixture", "image/png")}, data={"mode": "texture"})
                self.assertEqual(success.status_code, 200, success.text)
                wait_for_status(client, success.json()["task_id"], "completed")

                product_error = client.post("/api/upload", files={"file": ("product-error.png", b"fixture", "image/png")}, data={"mode": "texture"})
                self.assertEqual(product_error.status_code, 200, product_error.text)
                wait_for_status(client, product_error.json()["task_id"], "failed")

                non_output_io_error = client.post(
                    "/api/upload",
                    files={"file": ("non-output-io-error.png", b"fixture", "image/png")},
                    data={"mode": "texture"},
                )
                self.assertEqual(non_output_io_error.status_code, 200, non_output_io_error.text)
                wait_for_status(client, non_output_io_error.json()["task_id"], "failed")

                terminal_task_ids = {
                    success.json()["task_id"],
                    product_error.json()["task_id"],
                    non_output_io_error.json()["task_id"],
                }
                for _attempt in range(50):
                    current_events = [parse_runtime_record(record) for record in captured_records]
                    terminal_seen = {
                        item.get("task_id")
                        for item in current_events
                        if item.get("event") in {"IMAGE_TASK_SUCCEEDED", "IMAGE_TASK_FAILED"}
                    }
                    if terminal_task_ids <= terminal_seen:
                        break
                    time.sleep(0.01)

                parsed_events = [parse_runtime_record(record) for record in captured_records]
                started_task_ids = [
                    item["task_id"] for item in parsed_events if item.get("event") == "IMAGE_TASK_STARTED"
                ]
                self.assertEqual(len(started_task_ids), 6, started_task_ids)
                (
                    input_read_task_id,
                    empty_task_id,
                    output_directory_task_id,
                    success_started_id,
                    product_started_id,
                    non_output_started_id,
                ) = started_task_ids
                self.assertEqual(success_started_id, success.json()["task_id"])
                self.assertEqual(product_started_id, product_error.json()["task_id"])
                self.assertEqual(non_output_started_id, non_output_io_error.json()["task_id"])
                input_read_events = events_for_task(parsed_events, input_read_task_id)
                self.assertEqual(len(events_for_task(parsed_events, input_read_task_id, "IMAGE_TASK_STARTED")), 1)
                self.assertEqual(len(events_for_task(parsed_events, input_read_task_id, "IMAGE_TASK_FAILED")), 1)
                self.assertEqual(len(events_for_task(parsed_events, input_read_task_id, "IMAGE_TASK_SUCCEEDED")), 0)
                self.assertEqual(len(events_for_task(parsed_events, input_read_task_id, "OUTPUT_FILE_WRITE_FAILED")), 0)
                input_read_terminal = events_for_task(parsed_events, input_read_task_id, "IMAGE_TASK_FAILED")[0]
                self.assertEqual(input_read_terminal["stage"], "input_read")
                self.assertEqual(input_read_terminal["error_category"], runtime_logging.ENVIRONMENT_ERROR)
                self.assertIn("duration_ms", input_read_terminal)

                non_output_task_id = non_output_io_error.json()["task_id"]
                non_output_events = events_for_task(parsed_events, non_output_task_id)
                self.assertEqual(len(events_for_task(parsed_events, non_output_task_id, "IMAGE_TASK_STARTED")), 1)
                self.assertEqual(len(events_for_task(parsed_events, non_output_task_id, "IMAGE_ROUTE_SELECTED")), 1)
                self.assertEqual(len(events_for_task(parsed_events, non_output_task_id, "IMAGE_TASK_FAILED")), 1)
                self.assertEqual(len(events_for_task(parsed_events, non_output_task_id, "OUTPUT_FILE_WRITE_FAILED")), 0)
                self.assertEqual(events_for_task(parsed_events, non_output_task_id, "IMAGE_TASK_FAILED")[0]["stage"], "image_processing")
                self.assertEqual(
                    events_for_task(parsed_events, non_output_task_id, "IMAGE_TASK_FAILED")[0]["error_category"],
                    runtime_logging.ENVIRONMENT_ERROR,
                )

                output_directory_phase = events_for_task(parsed_events, output_directory_task_id, "OUTPUT_DIRECTORY_CREATE_FAILED")
                output_directory_terminal = events_for_task(parsed_events, output_directory_task_id, "IMAGE_TASK_FAILED")
                self.assertEqual(len(output_directory_phase), 1)
                self.assertEqual(len(output_directory_terminal), 1)
                self.assertEqual(output_directory_phase[0]["stage"], output_directory_terminal[0]["stage"])
                self.assertEqual(output_directory_phase[0]["error_category"], runtime_logging.ENVIRONMENT_ERROR)
                self.assertEqual(output_directory_phase[0]["error_category"], output_directory_terminal[0]["error_category"])
                self.assertEqual(output_directory_phase[0]["task_id"], output_directory_terminal[0]["task_id"])
                self.assertTrue(output_directory_terminal[0].get("action"))
                self.assertNotIn(
                    runtime_logging.USER_ACTION_REQUIRED,
                    {item.get("error_category") for item in events_for_task(parsed_events, output_directory_task_id)},
                )

                success_task_id = success.json()["task_id"]
                self.assertEqual(len(events_for_task(parsed_events, success_task_id, "IMAGE_TASK_STARTED")), 1)
                self.assertEqual(len(events_for_task(parsed_events, success_task_id, "IMAGE_ROUTE_SELECTED")), 1)
                self.assertEqual(len(events_for_task(parsed_events, success_task_id, "IMAGE_TASK_SUCCEEDED")), 1)
                self.assertEqual(len(events_for_task(parsed_events, success_task_id, "IMAGE_TASK_FAILED")), 0)
                self.assertIn("duration_ms", events_for_task(parsed_events, success_task_id, "IMAGE_TASK_SUCCEEDED")[0])

                failed_task_ids = {
                    input_read_task_id,
                    empty_task_id,
                    output_directory_task_id,
                    product_error.json()["task_id"],
                    non_output_task_id,
                }
                for failed_task_id in failed_task_ids:
                    task_events = events_for_task(parsed_events, failed_task_id)
                    terminal_events = [
                        item for item in task_events if item.get("event") in {"IMAGE_TASK_SUCCEEDED", "IMAGE_TASK_FAILED"}
                    ]
                    self.assertEqual(len(terminal_events), 1, task_events)
                    error_categories = {
                        item["error_category"]
                        for item in task_events
                        if item.get("error_category")
                    }
                    self.assertEqual(len(error_categories), 1, task_events)

                self.assertEqual(client.app.state.runtime_task_start_times, {})

            log_path = formal_root / "诊断" / "日志" / "hdde.log"
            self.assertTrue(log_path.is_file())
            self.assertEqual(settings_path.read_bytes(), settings_before)
            self.assertEqual(settings_path.stat().st_mtime_ns, settings_mtime_before)
            runtime_logging.reset_runtime_logging_for_tests()

    def test_global_terminal_guard_settings_write_and_route_classification(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            formal_root = root / "formal-root"
            formal_root.mkdir()
            settings_path = root / "settings.json"
            settings_path.write_text(
                json.dumps(self.settings_payload(formal_root), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            settings_before = settings_path.read_bytes()
            settings_mtime_before = settings_path.stat().st_mtime_ns

            def fake_output_plan(input_path, output_root, *_args, **_kwargs):
                source = Path(input_path)
                final_path = Path(output_root) / f"{source.stem}_final.png"
                return {
                    "paths": {"final": final_path},
                    "image_type": "test_fixture",
                    "input_width": 1,
                    "input_height": 1,
                    "output_width": 1,
                    "output_height": 1,
                    "resize_policy": "none",
                    "was_upscaled": False,
                    "was_downscaled": False,
                }

            def assert_failed_task(
                events: list[dict[str, str]],
                task_id: str,
                *,
                stage: str,
                error_category: str,
            ) -> None:
                task_events = [item for item in events if item.get("task_id") == task_id]
                self.assertEqual(len([item for item in task_events if item.get("event") == "IMAGE_TASK_STARTED"]), 1)
                failures = [item for item in task_events if item.get("event") == "IMAGE_TASK_FAILED"]
                self.assertEqual(len(failures), 1, task_events)
                self.assertEqual(len([item for item in task_events if item.get("event") == "IMAGE_TASK_SUCCEEDED"]), 0)
                self.assertEqual(failures[0]["stage"], stage)
                self.assertEqual(failures[0]["error_category"], error_category)
                self.assertIn("duration_ms", failures[0])
                categories = {item["error_category"] for item in task_events if item.get("error_category")}
                self.assertEqual(categories, {error_category})

            with (
                controlled_test_app_paths(settings_path, formal_root),
                capture_runtime_records() as captured_records,
                patch.object(main, "SETTINGS_PATH", settings_path),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
                patch("backend.v036_output_core.build_output_plan", side_effect=fake_output_plan) as output_plan_mock,
                TestClient(build_web_app(), raise_server_exceptions=False) as client,
            ):
                custom_output = root / "custom-output"
                with patch.object(main, "write_settings_if_changed", side_effect=OSError("controlled settings write failure")):
                    task_scoped_output = client.post(
                        "/api/upload",
                        files={"file": ("task-scoped-output.png", b"fixture", "image/png")},
                        data={"mode": "texture", "output_dir": str(custom_output)},
                    )
                self.assertEqual(task_scoped_output.status_code, 200, task_scoped_output.text)
                self.assertEqual(settings_path.read_bytes(), settings_before)
                self.assertEqual(settings_path.stat().st_mtime_ns, settings_mtime_before)

                with patch.object(main, "parse_output_format", side_effect=RuntimeError("controlled unexpected failure")):
                    unexpected_failure = client.post(
                        "/api/upload",
                        files={"file": ("unexpected-error.png", b"fixture", "image/png")},
                        data={"mode": "texture"},
                    )
                self.assertEqual(unexpected_failure.status_code, 500, unexpected_failure.text)

                route_cases = (
                    ("route-io-error.png", OSError("controlled route I/O failure"), runtime_logging.ENVIRONMENT_ERROR),
                    (
                        "route-user-error.png",
                        HTTPException(status_code=400, detail={"code": "INVALID_IMAGE_INPUT"}),
                        runtime_logging.USER_ACTION_REQUIRED,
                    ),
                    ("route-product-error.png", RuntimeError("controlled route product failure"), runtime_logging.PRODUCT_ERROR),
                )
                route_results: list[str] = []
                for filename, route_error, expected_category in route_cases:
                    output_plan_mock.side_effect = route_error
                    response = client.post(
                        "/api/upload",
                        files={"file": (filename, b"fixture", "image/png")},
                        data={"mode": "texture"},
                    )
                    self.assertEqual(response.status_code, 400, response.text)
                    route_results.append(expected_category)
                output_plan_mock.side_effect = fake_output_plan

                parsed_events = [parse_runtime_record(record) for record in captured_records]
                started_task_ids = [
                    item["task_id"] for item in parsed_events if item.get("event") == "IMAGE_TASK_STARTED"
                ]
                self.assertEqual(len(started_task_ids), 5, started_task_ids)
                task_scoped_id, unexpected_task_id, *route_task_ids = started_task_ids
                self.assertEqual(task_scoped_id, task_scoped_output.json()["task_id"])
                task_scoped_events = [item for item in parsed_events if item.get("task_id") == task_scoped_id]
                self.assertNotIn("settings_write", {item.get("stage") for item in task_scoped_events})
                assert_failed_task(
                    parsed_events,
                    unexpected_task_id,
                    stage="output_format_validation",
                    error_category=runtime_logging.PRODUCT_ERROR,
                )
                for route_task_id, expected_category in zip(route_task_ids, route_results, strict=True):
                    assert_failed_task(
                        parsed_events,
                        route_task_id,
                        stage="route_planning",
                        error_category=expected_category,
                    )

                self.assertEqual(client.app.state.runtime_task_start_times, {})

            self.assertEqual(settings_path.read_bytes(), settings_before)
            self.assertEqual(settings_path.stat().st_mtime_ns, settings_mtime_before)
            runtime_logging.reset_runtime_logging_for_tests()

    def test_settings_write_failure_preserves_file_and_in_memory_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal_root = root / "formal-root"
            formal_root.mkdir()
            settings_path = root / "settings.json"
            settings_payload = self.settings_payload(formal_root)
            settings_path.write_text(
                json.dumps(settings_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            settings_before = settings_path.read_bytes()
            settings_mtime_before = settings_path.stat().st_mtime_ns
            attempted_root = root / "attempted-compression-default"

            with (
                isolated_runtime_logging("real-app-settings-write-failure"),
                patch.object(main, "SETTINGS_PATH", settings_path),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
                TestClient(build_web_app(), raise_server_exceptions=False) as client,
            ):
                original_settings = client.get("/api/image-compression/output-settings")
                self.assertEqual(original_settings.status_code, 200, original_settings.text)
                original_saved_root = original_settings.json()["data"]["saved_default_root"]

                with patch.object(
                    main,
                    "write_settings_if_changed",
                    side_effect=OSError("controlled settings write failure"),
                ):
                    failed_save = client.post(
                        "/api/image-compression/output-settings/default",
                        json={"output_root": str(attempted_root)},
                    )

                self.assertEqual(failed_save.status_code, 500, failed_save.text)
                after_failure = client.get("/api/image-compression/output-settings")
                self.assertEqual(after_failure.status_code, 200, after_failure.text)
                self.assertEqual(
                    after_failure.json()["data"]["saved_default_root"],
                    original_saved_root,
                )

            self.assertEqual(settings_path.read_bytes(), settings_before)
            self.assertEqual(settings_path.stat().st_mtime_ns, settings_mtime_before)
            runtime_logging.reset_runtime_logging_for_tests()

    def test_real_output_write_failure_comes_from_production_persistence_boundary(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal_root = root / "formal-root"
            formal_root.mkdir()
            settings_path = root / "settings.json"
            settings_path.write_text(
                json.dumps(self.settings_payload(formal_root), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            settings_before = settings_path.read_bytes()
            settings_mtime_before = settings_path.stat().st_mtime_ns
            image_buffer = io.BytesIO()
            Image.new("RGB", (24, 24), (96, 128, 160)).save(image_buffer, format="PNG")

            def wait_for_failure(client: TestClient, task_id: str) -> None:
                for _attempt in range(100):
                    response = client.get(f"/api/v1/tasks/{task_id}")
                    if response.json()["data"]["task_status"] == "failed":
                        return
                    time.sleep(0.01)
                self.fail(f"task {task_id} did not reach failed")

            with (
                isolated_runtime_logging("real-app-output-write-failure"),
                capture_runtime_records() as captured_records,
                patch.object(main, "SETTINGS_PATH", settings_path),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
                TestClient(build_web_app()) as client,
            ):
                with patch(
                    "backend.v036_output_core.safe_copy_final",
                    side_effect=OSError("controlled production final replace failure"),
                ):
                    response = client.post(
                        "/api/upload",
                        files={"file": ("real-output-write-error.png", image_buffer.getvalue(), "image/png")},
                        data={"mode": "text_safe", "output_profile": "fidelity_original"},
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    task_id = response.json()["task_id"]
                    wait_for_failure(client, task_id)

                parsed_events = [parse_runtime_record(record) for record in captured_records]
                task_events = [item for item in parsed_events if item.get("task_id") == task_id]
                phase_events = [item for item in task_events if item.get("event") == "OUTPUT_FILE_WRITE_FAILED"]
                terminal_events = [item for item in task_events if item.get("event") == "IMAGE_TASK_FAILED"]
                self.assertEqual(len([item for item in task_events if item.get("event") == "IMAGE_TASK_STARTED"]), 1)
                self.assertEqual(len(phase_events), 1, task_events)
                self.assertEqual(len(terminal_events), 1, task_events)
                self.assertEqual(phase_events[0]["task_id"], terminal_events[0]["task_id"])
                self.assertEqual(phase_events[0]["stage"], "output_file_write")
                self.assertEqual(phase_events[0]["stage"], terminal_events[0]["stage"])
                self.assertEqual(phase_events[0]["error_category"], runtime_logging.ENVIRONMENT_ERROR)
                self.assertEqual(phase_events[0]["error_category"], terminal_events[0]["error_category"])
                self.assertIn("controlled production final replace failure", terminal_events[0]["reason"])
                self.assertIn("duration_ms", terminal_events[0])
                self.assertEqual(client.app.state.runtime_task_start_times, {})

            self.assertEqual(settings_path.read_bytes(), settings_before)
            self.assertEqual(settings_path.stat().st_mtime_ns, settings_mtime_before)
            runtime_logging.reset_runtime_logging_for_tests()


class AppDataMigrationTests(unittest.TestCase):
    @staticmethod
    def legacy_settings(formal_root: Path) -> dict:
        return {
            "last_app_data_root": str(formal_root),
            "default_output_dir": str(Path(main.PROJECT_ROOT) / "tmp" / "runtime_data" / "影界HDDE" / "输出"),
            "last_output_dir": str(formal_root / "1080P安全增强输出"),
            "image_compression_default_output_root": str(formal_root / "图片压缩输出"),
            "unrelated_user_preference": {"keep": True},
        }

    def test_active_and_diagnostic_migration_is_complete_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "formal-root"
            formal_root.mkdir()
            fixtures = {
                formal_root / "图片压缩输出" / "compression.txt": b"compression",
                formal_root / "1080P安全增强输出" / "safe.txt": b"safe",
                formal_root / "输出成品" / "standard.txt": b"standard",
                formal_root / "报告" / "report.txt": b"report",
                formal_root / "反馈包" / "feedback.txt": b"feedback",
                formal_root / "影界测试反馈包" / "safe-feedback.txt": b"safe-feedback",
            }
            for path, payload in fixtures.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            (formal_root / "交付包").mkdir()
            settings_path = Path(directory) / "settings.json"
            settings = self.legacy_settings(formal_root)
            settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

            result = app_data_migration.execute_migration_cycle(
                formal_root,
                settings,
                settings_path=settings_path,
                project_root=Path(main.PROJECT_ROOT),
                write_report=False,
            )

            self.assertEqual(result["status"], "APPLIED")
            self.assertEqual(result["second_run"], "NO_OP")
            targets = {
                formal_root / app_data_migration.TARGET_PATHS["compression_output"] / "compression.txt": b"compression",
                formal_root / app_data_migration.TARGET_PATHS["safe_output"] / "safe.txt": b"safe",
                formal_root / app_data_migration.TARGET_PATHS["standard_output"] / "standard.txt": b"standard",
                formal_root / app_data_migration.TARGET_PATHS["report_dir"] / "report.txt": b"report",
                formal_root / app_data_migration.TARGET_PATHS["feedback_dir"] / "feedback.txt": b"feedback",
                formal_root / app_data_migration.TARGET_PATHS["safe_feedback_dir"] / "safe-feedback.txt": b"safe-feedback",
            }
            self.assertEqual(len(targets), len(fixtures))
            for path, payload in targets.items():
                self.assertEqual(path.read_bytes(), payload)
            for legacy in ("图片压缩输出", "1080P安全增强输出", "报告", "反馈包", "影界测试反馈包", "交付包"):
                self.assertFalse((formal_root / legacy).exists())
            self.assertFalse((formal_root / app_data_migration.TARGET_PATHS["feedback_dir"] / "交付包").exists())
            self.assertEqual(
                app_data_migration.run_app_data_migration(
                    formal_root,
                    settings,
                    settings_path=settings_path,
                    project_root=Path(main.PROJECT_ROOT),
                )["status"],
                "NO_OP",
            )

    def test_formal_output_name_migration_preserves_bytes_settings_and_historical_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "formal-root"
            old_standard = formal_root / "输出" / "1080P标准版" / "standard.png"
            old_four_k = formal_root / "输出" / "4K增强" / "four-k.png"
            old_standard.parent.mkdir(parents=True)
            old_four_k.parent.mkdir(parents=True)
            old_standard.write_bytes(b"standard-result")
            old_four_k.write_bytes(b"four-k-result")
            settings = {
                "app_data_root": str(formal_root),
                "default_output_dir": str(old_standard.parent),
                "last_output_dir": str(old_standard.parent),
            }
            settings_path = Path(directory) / "settings.json"
            settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

            result = app_data_migration.execute_migration_cycle(
                formal_root,
                settings,
                settings_path=settings_path,
                write_report=False,
            )

            new_standard = formal_root / app_data_migration.TARGET_PATHS["standard_output"] / old_standard.name
            new_four_k = formal_root / app_data_migration.TARGET_PATHS["four_k_output"] / old_four_k.name
            self.assertEqual(result["status"], "APPLIED")
            self.assertEqual(new_standard.read_bytes(), b"standard-result")
            self.assertEqual(new_four_k.read_bytes(), b"four-k-result")
            self.assertFalse(old_standard.parent.exists())
            self.assertFalse(old_four_k.parent.exists())
            self.assertEqual(settings["default_output_dir"], str(new_standard.parent))
            self.assertEqual(settings["last_output_dir"], str(new_standard.parent))
            self.assertEqual(
                app_data_migration.resolve_migrated_formal_output_path(old_standard, formal_root),
                new_standard.resolve(),
            )
            self.assertEqual(
                app_data_migration.resolve_migrated_formal_output_path(old_four_k, formal_root),
                new_four_k.resolve(),
            )

    def test_all_retired_output_folders_migrate_to_the_two_official_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "formal-root"
            retired = {
                "4K尺寸适配": "four-k-size.bin",
                "4K适配": "four-k-adapt.bin",
                "4K增强": "four-k-enhance.bin",
                "4K画质": "four-k-quality.bin",
                "4K画质适配": "four-k-quality-adapt.bin",
                "4K高清增强": "four-k-hd.bin",
                "1080P画质增强": "1080-quality-enhance.bin",
                "1080P标准增强": "1080-standard.bin",
                "1080P安全增强": "1080-safe.bin",
                "1080P增强": "1080-enhance.bin",
                "1080P标准版": "1080-standard-edition.bin",
            }
            originals = {}
            for index, (folder, filename) in enumerate(retired.items(), start=1):
                source = formal_root / "输出" / folder / filename
                source.parent.mkdir(parents=True, exist_ok=True)
                payload = f"payload-{index}".encode("ascii")
                source.write_bytes(payload)
                originals[source] = payload

            result = app_data_migration.execute_migration_cycle(
                formal_root,
                {"app_data_root": str(formal_root)},
                write_report=False,
            )

            self.assertEqual(result["status"], "APPLIED")
            self.assertEqual(app_data_migration.TARGET_PATHS["standard_output"], Path("输出") / "1080P画质")
            self.assertEqual(app_data_migration.TARGET_PATHS["four_k_output"], Path("输出") / "4K画质增强")
            for source, payload in originals.items():
                target_root = (
                    formal_root / app_data_migration.TARGET_PATHS["four_k_output"]
                    if source.parent.name.startswith("4K")
                    else formal_root / app_data_migration.TARGET_PATHS["standard_output"]
                )
                target = target_root / source.name
                self.assertFalse(source.parent.exists())
                self.assertEqual(target.read_bytes(), payload)
                self.assertEqual(
                    app_data_migration.resolve_migrated_formal_output_path(source, formal_root),
                    target.resolve(),
                )

    def test_retired_local_retouch_folders_migrate_to_defect_repair_without_changing_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "formal-root"
            originals = {}
            for index, folder in enumerate(("标记修整", "瑕疵修整", "局部修整", "局部修复"), start=1):
                source = formal_root / "输出" / folder / f"retouch-{index}.png"
                source.parent.mkdir(parents=True, exist_ok=True)
                payload = f"retouch-payload-{index}".encode("ascii")
                source.write_bytes(payload)
                originals[source] = payload

            result = app_data_migration.execute_migration_cycle(
                formal_root,
                {"app_data_root": str(formal_root)},
                write_report=False,
            )

            target_root = formal_root / app_data_migration.TARGET_PATHS["local_retouch_output"]
            self.assertEqual(result["status"], "APPLIED")
            self.assertEqual(app_data_migration.TARGET_PATHS["local_retouch_output"], Path("输出") / "瑕疵修复")
            for source, payload in originals.items():
                target = target_root / source.name
                self.assertFalse(source.parent.exists())
                self.assertEqual(target.read_bytes(), payload)
                self.assertEqual(
                    app_data_migration.resolve_migrated_formal_output_path(source, formal_root),
                    target.resolve(),
                )

    def test_conflicts_and_move_failures_preserve_sources_and_unknown_content(self):
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "formal-root"
            legacy = formal_root / "图片压缩输出"
            target = formal_root / app_data_migration.TARGET_PATHS["compression_output"]
            legacy.mkdir(parents=True)
            target.mkdir(parents=True)
            (legacy / "same.txt").write_bytes(b"same")
            (target / "same.txt").write_bytes(b"same")
            (legacy / "conflict.txt").write_bytes(b"source-content")
            (target / "conflict.txt").write_bytes(b"target-content")
            failed_source = legacy / "z-move-failure.txt"
            failed_source.write_bytes(b"must-survive")
            unknown_dir = formal_root / "用途未知"
            unknown_dir.mkdir()
            unknown_file = unknown_dir / "keep.bin"
            unknown_file.write_bytes(b"user-owned")
            root_file = formal_root / "Logo.png"
            root_file.write_bytes(b"root-file")
            settings = self.legacy_settings(formal_root)
            settings_before = json.loads(json.dumps(settings, ensure_ascii=False))
            original_replace = Path.replace
            original_copy = app_data_migration._copy_verified_then_remove

            def controlled_replace(path: Path, target_path: Path):
                if Path(path) == failed_source:
                    raise OSError("controlled atomic move failure")
                return original_replace(path, target_path)

            def controlled_copy(source: Path, destination: Path):
                if Path(source) == failed_source:
                    raise OSError("controlled verified copy failure")
                return original_copy(source, destination)

            with (
                patch.object(Path, "replace", new=controlled_replace),
                patch.object(app_data_migration, "_copy_verified_then_remove", new=controlled_copy),
            ):
                result = app_data_migration.execute_migration_cycle(
                    formal_root,
                    settings,
                    settings_writer=lambda _payload: self.fail("Settings must not be written after a migration failure"),
                    project_root=Path(main.PROJECT_ROOT),
                    write_report=False,
                )

            first = result["first"]
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["second_run"], "NOT_RUN")
            self.assertEqual(first["deduplicated_files"], 0)
            self.assertEqual(first["stage"], "collision")
            self.assertEqual(first["rollback_status"], "NOT_REQUIRED")
            self.assertEqual(first["action_taken"], "KEPT_IN_PLACE")
            self.assertEqual((legacy / "same.txt").read_bytes(), b"same")
            self.assertEqual((legacy / "conflict.txt").read_bytes(), b"source-content")
            self.assertEqual((target / "same.txt").read_bytes(), b"same")
            self.assertEqual((target / "conflict.txt").read_bytes(), b"target-content")
            self.assertFalse((target / "conflict_迁移_001.txt").exists())
            self.assertEqual(failed_source.read_bytes(), b"must-survive")
            self.assertTrue(legacy.is_dir())
            self.assertEqual(unknown_file.read_bytes(), b"user-owned")
            self.assertEqual(root_file.read_bytes(), b"root-file")
            self.assertIn(str(unknown_dir), {item["source_path"] for item in first["kept_in_place"]})
            self.assertEqual(settings, settings_before)

    def test_settings_updates_are_exact_single_write_and_failure_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "formal-root"
            formal_root.mkdir()
            settings = self.legacy_settings(formal_root)
            original_last_root = settings["last_app_data_root"]
            original_unrelated = json.loads(json.dumps(settings["unrelated_user_preference"]))
            writes: list[dict] = []

            def writer(payload: dict) -> None:
                writes.append(json.loads(json.dumps(payload, ensure_ascii=False)))

            result = app_data_migration.execute_migration_cycle(
                formal_root,
                settings,
                settings_writer=writer,
                project_root=Path(main.PROJECT_ROOT),
                write_report=False,
            )

            self.assertEqual(result["status"], "APPLIED")
            self.assertEqual(result["second_run"], "NO_OP")
            self.assertEqual(len(writes), 1)
            self.assertEqual(settings["last_app_data_root"], original_last_root)
            self.assertEqual(settings["unrelated_user_preference"], original_unrelated)
            self.assertEqual(settings["default_output_dir"], str(formal_root / app_data_migration.TARGET_PATHS["standard_output"]))
            self.assertEqual(settings["last_output_dir"], str(formal_root / app_data_migration.TARGET_PATHS["safe_output"]))
            self.assertEqual(
                settings["image_compression_default_output_root"],
                str(formal_root / app_data_migration.TARGET_PATHS["compression_output"]),
            )

        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "formal-root"
            formal_root.mkdir()
            failed_settings = self.legacy_settings(formal_root)
            failed_before = json.loads(json.dumps(failed_settings, ensure_ascii=False))
            result = app_data_migration.execute_migration_cycle(
                formal_root,
                failed_settings,
                settings_writer=lambda _payload: (_ for _ in ()).throw(OSError("controlled Settings write failure")),
                project_root=Path(main.PROJECT_ROOT),
                write_report=False,
            )
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["second_run"], "NOT_RUN")
            self.assertEqual(failed_settings, failed_before)

    def test_filesystem_exceptions_return_auditable_blocked_contract(self):
        required_fields = {
            "status",
            "stage",
            "path",
            "exception_type",
            "reason",
            "action_taken",
        }

        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "enumerate-root"
            formal_root.mkdir()
            with patch.object(
                app_data_migration,
                "_classify_inventory",
                side_effect=PermissionError("controlled enumerate failure"),
            ):
                result = app_data_migration.run_app_data_migration(formal_root, {})
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["stage"], "enumerate")
            self.assertTrue(required_fields.issubset(result))

        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "mkdir-root"
            formal_root.mkdir()
            failed_path = formal_root / "输出"
            original_mkdir = Path.mkdir

            def controlled_mkdir(path: Path, *args, **kwargs):
                if Path(path) == failed_path:
                    raise OSError("controlled mkdir failure")
                return original_mkdir(path, *args, **kwargs)

            with patch.object(Path, "mkdir", new=controlled_mkdir):
                result = app_data_migration.run_app_data_migration(formal_root, {})
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["stage"], "mkdir")
            self.assertEqual(Path(result["path"]), failed_path)
            self.assertEqual(result["exception_type"], "OSError")
            self.assertTrue(required_fields.issubset(result))

        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "hash-root"
            source = formal_root / "输出成品" / "same.txt"
            target = formal_root / app_data_migration.TARGET_PATHS["standard_output"] / "same.txt"
            source.parent.mkdir(parents=True)
            target.parent.mkdir(parents=True)
            source.write_bytes(b"same")
            target.write_bytes(b"same")
            with patch.object(app_data_migration, "_sha256", side_effect=PermissionError("controlled hash failure")):
                result = app_data_migration.run_app_data_migration(formal_root, {})
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["stage"], "hash")
            self.assertEqual(Path(result["path"]), source)
            self.assertEqual(source.read_bytes(), b"same")
            self.assertEqual(target.read_bytes(), b"same")
            self.assertTrue(required_fields.issubset(result))

    def test_copy_fallback_hash_verification_failure_preserves_hash_stage_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "formal-root"
            source = formal_root / "输出成品" / "candidate.bin"
            target = formal_root / app_data_migration.TARGET_PATHS["standard_output"] / source.name
            source.parent.mkdir(parents=True)
            source.write_bytes(b"candidate")
            settings = self.legacy_settings(formal_root)
            settings_before = json.loads(json.dumps(settings, ensure_ascii=False))
            original_replace = Path.replace
            original_sha256 = app_data_migration._sha256

            def controlled_replace(path: Path, target_path: Path):
                if Path(path) == source:
                    raise OSError("controlled atomic move fallback")
                return original_replace(path, target_path)

            def controlled_sha256(path: Path):
                if ".hdde-migrate-" in Path(path).name:
                    raise PermissionError("controlled copy-verification hash failure")
                return original_sha256(path)

            with (
                patch.object(Path, "replace", new=controlled_replace),
                patch.object(app_data_migration, "_sha256", new=controlled_sha256),
            ):
                result = app_data_migration.run_app_data_migration(
                    formal_root,
                    settings,
                    project_root=Path(main.PROJECT_ROOT),
                )

            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["stage"], "hash")
            self.assertNotEqual(result["stage"], "move")
            self.assertEqual(result["exception_type"], "PermissionError")
            self.assertIn("controlled copy-verification hash failure", result["reason"])
            self.assertIn(".hdde-migrate-", Path(result["path"]).name)
            self.assertEqual(result["action_taken"], "KEPT_IN_PLACE")
            self.assertEqual(source.read_bytes(), b"candidate")
            self.assertFalse(target.exists())
            self.assertEqual(result["migrated_files"], 0)
            self.assertEqual(settings, settings_before)
            self.assertEqual(list(target.parent.glob("*.hdde-migrate-*.tmp")), [])

    def test_dedup_backup_move_failure_preserves_move_stage_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "formal-root"
            source = formal_root / "输出成品" / "same.bin"
            target = formal_root / app_data_migration.TARGET_PATHS["standard_output"] / source.name
            source.parent.mkdir(parents=True)
            target.parent.mkdir(parents=True)
            source.write_bytes(b"same")
            target.write_bytes(b"same")
            settings: dict = {}
            settings_before = dict(settings)
            original_replace = Path.replace

            def controlled_replace(path: Path, target_path: Path):
                if Path(path) == source and ".hdde-dedup-" in Path(target_path).name:
                    raise PermissionError("controlled dedup backup move failure")
                return original_replace(path, target_path)

            with patch.object(Path, "replace", new=controlled_replace):
                result = app_data_migration.run_app_data_migration(formal_root, settings)

            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["stage"], "move")
            self.assertNotEqual(result["stage"], "hash")
            self.assertEqual(result["exception_type"], "PermissionError")
            self.assertIn("controlled dedup backup move failure", result["reason"])
            self.assertEqual(result["action_taken"], "KEPT_IN_PLACE")
            self.assertEqual(source.read_bytes(), b"same")
            self.assertEqual(target.read_bytes(), b"same")
            self.assertEqual(settings, settings_before)
            self.assertEqual(list(target.parent.glob("*.hdde-dedup-*.tmp")), [])

    def test_report_write_failure_rolls_back_all_moves_and_preserves_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal_root = root / "formal-root"
            source = formal_root / "输出成品" / "result.txt"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"must-return")
            target = formal_root / app_data_migration.TARGET_PATHS["standard_output"] / source.name
            settings = self.legacy_settings(formal_root)
            settings_before = json.loads(json.dumps(settings, ensure_ascii=False))
            project_tmp = root / "project" / "tmp"

            with patch.object(
                app_data_migration,
                "_write_migration_report",
                side_effect=PermissionError("controlled report write failure"),
            ):
                result = app_data_migration.execute_migration_cycle(
                    formal_root,
                    settings,
                    settings_writer=lambda _payload: self.fail("Settings must remain unchanged before report commit"),
                    project_root=root / "project",
                    write_report=True,
                )

            first = result["first"]
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(first["stage"], "report_write")
            self.assertEqual(first["rollback_status"], "SUCCESS")
            self.assertEqual(first["action_taken"], "ROLLED_BACK")
            self.assertEqual(source.read_bytes(), b"must-return")
            self.assertFalse(target.exists())
            self.assertEqual(settings, settings_before)
            self.assertFalse(project_tmp.exists())

    def test_rollback_failure_is_reported_without_masking_original_move_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "formal-root"
            legacy = formal_root / "输出成品"
            source_a = legacy / "a.txt"
            source_b = legacy / "b.txt"
            source_a.parent.mkdir(parents=True)
            source_a.write_bytes(b"a")
            source_b.write_bytes(b"b")
            target_a = formal_root / app_data_migration.TARGET_PATHS["standard_output"] / source_a.name
            original_replace = Path.replace
            original_copy = app_data_migration._copy_verified_then_remove

            def controlled_replace(path: Path, target_path: Path):
                if Path(path) == source_b:
                    raise OSError("controlled second move failure")
                if Path(path) == target_a and Path(target_path) == source_a:
                    raise PermissionError("controlled rollback failure")
                return original_replace(path, target_path)

            def controlled_copy(source: Path, destination: Path):
                if Path(source) == source_b:
                    raise OSError("controlled verified copy failure")
                return original_copy(source, destination)

            with (
                patch.object(Path, "replace", new=controlled_replace),
                patch.object(app_data_migration, "_copy_verified_then_remove", new=controlled_copy),
            ):
                result = app_data_migration.run_app_data_migration(formal_root, {})

            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["stage"], "move")
            self.assertEqual(result["rollback_status"], "FAILED")
            self.assertEqual(Path(result["rollback_failure_path"]), target_a)
            self.assertEqual(result["rollback_exception_type"], "PermissionError")
            self.assertIn("controlled rollback failure", result["rollback_reason"])
            self.assertEqual(result["action_taken"], "ROLLBACK_FAILED")
            self.assertEqual(source_b.read_bytes(), b"b")
            self.assertEqual(target_a.read_bytes(), b"a")

    def test_unknown_output_content_is_kept_while_known_legacy_content_migrates(self):
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "formal-root"
            unknown_file = formal_root / "输出" / "custom.bin"
            unknown_nested = formal_root / "输出" / "客户自定义目录" / "keep.txt"
            known_source = formal_root / "输出成品" / "known.txt"
            unknown_file.parent.mkdir(parents=True)
            unknown_nested.parent.mkdir(parents=True)
            known_source.parent.mkdir(parents=True)
            unknown_file.write_bytes(b"unknown-file")
            unknown_nested.write_bytes(b"unknown-directory")
            known_source.write_bytes(b"known")

            result = app_data_migration.run_app_data_migration(formal_root, {})

            self.assertEqual(result["status"], "APPLIED")
            self.assertEqual(unknown_file.read_bytes(), b"unknown-file")
            self.assertEqual(unknown_nested.read_bytes(), b"unknown-directory")
            standard_output = formal_root / app_data_migration.TARGET_PATHS["standard_output"]
            self.assertFalse((standard_output / unknown_file.name).exists())
            self.assertFalse((standard_output / unknown_nested.parent.name).exists())
            kept_records = {
                item["source_path"]: item
                for item in result["migration_records"]
                if item["result"] == "KEEP_IN_PLACE"
            }
            for path in (unknown_file, unknown_nested.parent):
                self.assertEqual(kept_records[str(path)]["classification"], "UNKNOWN")
                self.assertEqual(kept_records[str(path)]["reason"], "UNRECOGNIZED_LEGACY_CONTENT")
            known_target = formal_root / app_data_migration.TARGET_PATHS["standard_output"] / known_source.name
            self.assertFalse(known_source.exists())
            self.assertEqual(known_target.read_bytes(), b"known")
            self.assertEqual(
                hashlib.sha256(known_target.read_bytes()).hexdigest(),
                hashlib.sha256(b"known").hexdigest(),
            )
            self.assertIn(
                "MIGRATED",
                {
                    item["result"]
                    for item in result["migration_records"]
                    if item["source_path"] == str(known_source.parent)
                },
            )

    def test_normal_processing_uses_new_paths_without_recreating_legacy_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "formal-root"
            formal_root.mkdir()
            settings_path = Path(directory) / "settings.json"
            settings = json.loads(REPOSITORY_SETTINGS_PATH.read_bytes())
            settings["app_data_root"] = str(formal_root)
            settings["last_app_data_root"] = str(formal_root)
            settings["default_output_dir"] = str(formal_root / app_data_migration.TARGET_PATHS["standard_output"])
            settings["last_output_dir"] = str(formal_root / app_data_migration.TARGET_PATHS["standard_output"])
            settings["image_compression_default_output_root"] = str(
                formal_root / app_data_migration.TARGET_PATHS["compression_output"]
            )
            settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

            def fake_output_plan(input_path, output_root, *_args, **_kwargs):
                source = Path(input_path)
                return {
                    "paths": {"final": Path(output_root) / f"{source.stem}_final.png"},
                    "image_type": "test_fixture",
                    "input_width": 1,
                    "input_height": 1,
                    "output_width": 1,
                    "output_height": 1,
                    "resize_policy": "none",
                    "was_upscaled": False,
                    "was_downscaled": False,
                }

            def fake_process(payload):
                source = Path(payload["input_path"])
                final_path = Path(payload["output_root"]) / f"{source.stem}_final.png"
                final_path.write_bytes(b"processed")
                return {
                    "final_output_path": final_path,
                    "task_result": {"output_format": "png", "output_size": 9},
                    "task_report": {},
                    "image_type": "test_fixture",
                    "degradation_type": "none",
                    "input_width": 1,
                    "input_height": 1,
                    "output_width": 1,
                    "output_height": 1,
                    "input_size_bytes": source.stat().st_size,
                    "output_changed": True,
                    "hash_equal": False,
                    "pixel_diff_score": 1.0,
                    "debug_timing": {},
                    "debug_quality": {},
                }

            with (
                isolated_runtime_logging("real-app-normal-processing"),
                patch.object(main, "SETTINGS_PATH", settings_path),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
                patch("backend.v036_output_core.build_output_plan", side_effect=fake_output_plan),
                patch("backend.v036_output_core.sha256_file", return_value="fixture-sha256"),
                patch("engine.pipeline.process_v046_delivery", side_effect=fake_process),
                TestClient(build_web_app()) as client,
            ):
                response = client.post(
                    "/api/upload",
                    files={"file": ("normal.png", b"fixture", "image/png")},
                    data={"mode": "texture"},
                )
                self.assertEqual(response.status_code, 200, response.text)
                task_id = response.json()["task_id"]
                for _attempt in range(50):
                    task = client.get(f"/api/v1/tasks/{task_id}").json()["data"]
                    if task["task_status"] == "completed":
                        break
                    time.sleep(0.01)
                else:
                    self.fail("normal processing did not complete")
                self.assertEqual(client.app.state.app_data_migration_result["status"], "APPLIED")

            self.assertEqual(
                (formal_root / app_data_migration.TARGET_PATHS["standard_output"] / "normal_final.png").read_bytes(),
                b"processed",
            )
            for key in ("standard_output", "safe_output", "four_k_output", "compression_output", "log_dir", "feedback_dir", "report_dir"):
                self.assertTrue((formal_root / app_data_migration.TARGET_PATHS[key]).is_dir(), key)
            self.assertFalse((formal_root / "输出" / "1080P标准版").exists())
            self.assertFalse((formal_root / "输出" / "4K增强").exists())
            for legacy in (
                "图片压缩输出",
                "1080P安全增强输出",
                "输出成品",
                "输入",
                "输入图片",
                "beta_uploads",
                "1080P安全增强输入",
                "临时",
                "报告",
                "反馈包",
                "影界测试反馈包",
                "交付包",
                "配置",
            ):
                self.assertFalse((formal_root / legacy).exists(), legacy)
            runtime_logging.reset_runtime_logging_for_tests()

    def test_completed_task_stream_does_not_replay_false_completion_or_delay_result_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory) / "formal-root"
            formal_root.mkdir()
            settings_path = Path(directory) / "settings.json"
            settings = json.loads(REPOSITORY_SETTINGS_PATH.read_bytes())
            settings["app_data_root"] = str(formal_root)
            settings["last_app_data_root"] = str(formal_root)
            settings["default_output_dir"] = str(formal_root / app_data_migration.TARGET_PATHS["standard_output"])
            settings["last_output_dir"] = str(formal_root / app_data_migration.TARGET_PATHS["standard_output"])
            settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

            def fake_output_plan(input_path, output_root, *_args, **_kwargs):
                source = Path(input_path)
                return {
                    "paths": {"final": Path(output_root) / f"{source.stem}_final.png"},
                    "image_type": "test_fixture",
                    "input_width": 1,
                    "input_height": 1,
                    "output_width": 1,
                    "output_height": 1,
                    "resize_policy": "none",
                    "was_upscaled": False,
                    "was_downscaled": False,
                }

            def fake_process(payload):
                source = Path(payload["input_path"])
                final_path = Path(payload["output_root"]) / f"{source.stem}_final.png"
                final_path.write_bytes(b"processed")
                return {
                    "final_output_path": final_path,
                    "task_result": {"output_format": "png", "output_size": 9},
                    "task_report": {},
                    "image_type": "test_fixture",
                    "degradation_type": "none",
                    "input_width": 1,
                    "input_height": 1,
                    "output_width": 1,
                    "output_height": 1,
                    "input_size_bytes": source.stat().st_size,
                    "output_changed": True,
                    "hash_equal": False,
                    "pixel_diff_score": 1.0,
                    "debug_timing": {},
                    "debug_quality": {},
                }

            with (
                isolated_runtime_logging("real-app-result-ready-stream"),
                patch.object(main, "SETTINGS_PATH", settings_path),
                patch.object(main, "_formal_root_validation_error", return_value=("", "")),
                patch("backend.v036_output_core.build_output_plan", side_effect=fake_output_plan),
                patch("backend.v036_output_core.sha256_file", return_value="fixture-sha256"),
                patch("engine.pipeline.process_v046_delivery", side_effect=fake_process),
                TestClient(build_web_app()) as client,
            ):
                response = client.post(
                    "/api/upload",
                    files={"file": ("stream-ready.png", b"fixture", "image/png")},
                    data={"mode": "texture"},
                )
                self.assertEqual(response.status_code, 200, response.text)
                task_id = response.json()["task_id"]
                for _attempt in range(100):
                    task = client.get(f"/api/v1/tasks/{task_id}").json()["data"]
                    if task["task_status"] == "completed":
                        break
                    time.sleep(0.01)
                else:
                    self.fail("stream-ready task did not complete")

                started = time.perf_counter()
                stream_response = client.get(f"/api/v1/tasks/{task_id}/stream")
                stream_elapsed = time.perf_counter() - started
                payloads = [
                    json.loads(line.removeprefix("data: "))
                    for line in stream_response.text.splitlines()
                    if line.startswith("data: {")
                ]

            premature_completion = [
                payload
                for payload in payloads
                if payload.get("done") is not True and "输出完成" in str(payload.get("message") or "")
            ]
            self.assertEqual(premature_completion, [])
            self.assertLess(stream_elapsed, 0.75)
            self.assertTrue(payloads[-1]["done"])
            self.assertEqual(payloads[-1]["task"]["task_status"], "completed")
            runtime_logging.reset_runtime_logging_for_tests()


if __name__ == "__main__":
    unittest.main()
