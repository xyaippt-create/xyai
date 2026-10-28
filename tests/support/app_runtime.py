"""One isolation boundary for tests that initialize the real HDDE application.

The logging override intentionally controls only the runtime log. Settings and the
formal root use their existing, independent production resolvers and are patched
explicitly before ``build_web_app()`` is called.
"""

from __future__ import annotations

import atexit
import importlib
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Iterator
from unittest.mock import patch


RUNTIME_ROOT_OVERRIDE_ENV = "HDDE_RUNTIME_ROOT_OVERRIDE"
_PROCESS_LOG_ROOT: Path | None = None
_PROCESS_APP_RUNTIME: IsolatedAppRuntime | None = None


@dataclass(frozen=True)
class IsolatedAppRuntime:
    main: ModuleType
    root: Path
    formal_root: Path
    settings_path: Path
    runtime_log_path: Path
    test_id: str


def activate_test_runtime_logging(test_id: str) -> Path:
    """Activate one process-scoped temporary log root before importing the App."""

    global _PROCESS_LOG_ROOT
    configured = str(os.environ.get(RUNTIME_ROOT_OVERRIDE_ENV) or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    root = Path(tempfile.mkdtemp(prefix="hdde-app-test-log-"))
    os.environ[RUNTIME_ROOT_OVERRIDE_ENV] = str(root)
    _PROCESS_LOG_ROOT = root

    def cleanup() -> None:
        try:
            runtime_logging = importlib.import_module("engine.diagnostics.runtime_logging")
            runtime_logging.reset_runtime_logging_for_tests()
        finally:
            if os.environ.get(RUNTIME_ROOT_OVERRIDE_ENV) == str(root):
                os.environ.pop(RUNTIME_ROOT_OVERRIDE_ENV, None)
            shutil.rmtree(root, ignore_errors=True)

    atexit.register(cleanup)
    return root


@contextmanager
def isolated_runtime_logging(test_id: str) -> Iterator[Path]:
    """Scope only runtime logging for tests that intentionally control other paths."""

    with tempfile.TemporaryDirectory(prefix="hdde-app-test-log-") as directory:
        root = Path(directory).resolve()
        with patch.dict(os.environ, {RUNTIME_ROOT_OVERRIDE_ENV: str(root)}, clear=False):
            runtime_logging = importlib.import_module("engine.diagnostics.runtime_logging")
            runtime_logging.reset_runtime_logging_for_tests()
            try:
                yield root
            finally:
                runtime_logging.reset_runtime_logging_for_tests()


@contextmanager
def controlled_test_app_paths(settings_path: Path, formal_root: Path) -> Iterator[None]:
    """Guard production-path contract tests whose real log must follow a temp root."""

    temporary_root = Path(tempfile.gettempdir()).resolve()
    resolved_settings = Path(settings_path).resolve()
    resolved_formal = Path(formal_root).resolve()
    if temporary_root not in resolved_settings.parents or temporary_root not in resolved_formal.parents:
        raise AssertionError("CONTROLLED_APP_PATHS_MUST_BE_TEMPORARY")
    yield


def _isolated_settings(main: ModuleType, formal_root: Path) -> dict:
    settings = dict(main.default_settings())
    settings.update(
        {
            "app_data_root": str(formal_root),
            "last_app_data_root": str(formal_root),
            "default_output_dir": str(formal_root / main.DEFAULT_OUTPUT_DIR_NAME),
            "image_compression_default_output_root": str(
                formal_root / main.IMAGE_COMPRESSION_OUTPUT_DIR_NAME
            ),
            "last_output_dir": str(formal_root / main.DEFAULT_OUTPUT_DIR_NAME),
        }
    )
    return settings


def activate_test_app_runtime(test_id: str) -> IsolatedAppRuntime:
    """Activate process-scoped isolation for executable API validation scripts."""

    global _PROCESS_APP_RUNTIME
    if _PROCESS_APP_RUNTIME is not None:
        return _PROCESS_APP_RUNTIME
    root = activate_test_runtime_logging(test_id)
    main = importlib.import_module("main")
    runtime_logging = importlib.import_module("engine.diagnostics.runtime_logging")
    runtime_logging.reset_runtime_logging_for_tests()
    formal_root = root / "formal-root"
    settings_path = root / "settings" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(_isolated_settings(main, formal_root), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    original_settings_path = main.SETTINGS_PATH
    original_validation_root = main._VALIDATION_FORMAL_ROOT
    main.SETTINGS_PATH = settings_path
    main._VALIDATION_FORMAL_ROOT = formal_root
    _PROCESS_APP_RUNTIME = IsolatedAppRuntime(
        main=main,
        root=root,
        formal_root=formal_root,
        settings_path=settings_path,
        runtime_log_path=root / runtime_logging.LOG_RELATIVE_PATH,
        test_id=str(test_id),
    )

    def restore_main_paths() -> None:
        main.SETTINGS_PATH = original_settings_path
        main._VALIDATION_FORMAL_ROOT = original_validation_root

    atexit.register(restore_main_paths)
    return _PROCESS_APP_RUNTIME


@contextmanager
def isolated_app_runtime(test_id: str) -> Iterator[IsolatedAppRuntime]:
    """Establish log, Settings and formal-root isolation before real App init."""

    with tempfile.TemporaryDirectory(prefix="hdde-real-app-test-") as directory:
        root = Path(directory).resolve()
        formal_root = root / "formal-root"
        settings_path = root / "settings" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        env_patch = patch.dict(
            os.environ,
            {RUNTIME_ROOT_OVERRIDE_ENV: str(root)},
            clear=False,
        )
        env_patch.start()
        try:
            main = importlib.import_module("main")
            runtime_logging = importlib.import_module("engine.diagnostics.runtime_logging")
            runtime_logging.reset_runtime_logging_for_tests()
            settings_path.write_text(
                json.dumps(_isolated_settings(main, formal_root), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            with (
                patch.object(main, "SETTINGS_PATH", settings_path),
                patch.object(main, "_VALIDATION_FORMAL_ROOT", formal_root),
            ):
                yield IsolatedAppRuntime(
                    main=main,
                    root=root,
                    formal_root=formal_root,
                    settings_path=settings_path,
                    runtime_log_path=root / runtime_logging.LOG_RELATIVE_PATH,
                    test_id=str(test_id),
                )
        finally:
            try:
                runtime_logging = importlib.import_module("engine.diagnostics.runtime_logging")
                runtime_logging.reset_runtime_logging_for_tests()
            finally:
                env_patch.stop()


@contextmanager
def isolated_test_client(test_id: str, **client_options):
    """Build and run the real FastAPI app inside the shared isolation boundary."""

    from fastapi.testclient import TestClient

    with isolated_app_runtime(test_id) as runtime:
        with TestClient(runtime.main.build_web_app(), **client_options) as client:
            yield client, runtime
