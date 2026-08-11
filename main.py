import argparse
import asyncio
import copy
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from datetime import datetime
from pathlib import Path

from runtime import APP_VERSION, PRODUCT_VERSION
from runtime.crash_handler import handle_exception, install_global_exception_hook
from runtime.error_dialog import show_info_dialog
from runtime.startup_check import run_startup_check
from runtime.system_info import is_pyinstaller
from engine.diagnostics.runtime_logging import (
    CONFIGURATION_ERROR,
    ENVIRONMENT_ERROR,
    PRODUCT_ERROR,
    USER_ACTION_REQUIRED,
    begin_runtime,
    build_exception_diagnostics,
    configure_runtime_identity,
    initialize_file_logging,
    log_runtime_event,
    related_runtime_events,
)
from engine.storage.app_data_migration import execute_migration_cycle, resolve_migrated_formal_output_path
from engine.image_processing_routing.four_k_v1 import (
    FOUR_K_V1_MODE,
    FOUR_K_V1_OUTPUT_DIRECTORY,
    FOUR_K_V1_OUTPUT_PROFILE,
    FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY,
    FOUR_K_V1_ROUTE,
    build_4k_v1_output_path,
    inspect_4k_v1_source,
    process_4k_v1_image,
)


AUTO_MODE = "fidelity"
SERVER_HOST = "localhost"
SERVER_PORT = 8787
SERVER_CORS_ORIGINS = ["*"]
DEFAULT_TASK_ID = "task_vmp_v04_core"
ENHANCEMENT_1080P_FEATURE_KEY = "enhancement_1080p"
ENHANCEMENT_4K_FEATURE_KEY = "enhancement_4k"
SUPPORTED_MODES = [
    "fidelity",
    "texture",
    "text_safe",
    "ai_image_clean",
    "sharp_4k",
    "auto",
    "ai_commercial_kv",
    "architecture",
    "cinematic",
    "cosmetics",
    "food",
    "luxury_product",
    "portrait_commercial",
    "ppt_business",
]

PROJECT_ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = PROJECT_ROOT / "settings" / "settings.json"
APP_DATA_ROOT_NAME = "\u5f71\u754cHDDE"
LEGACY_WORK_DIR_NAME = "\u5f71\u754c\u6587\u4ef6"
OUTPUT_ROOT_RELATIVE = Path("\u8f93\u51fa")
DIAGNOSTIC_ROOT_RELATIVE = Path("\u8bca\u65ad")
DEFAULT_OUTPUT_DIR_NAME = OUTPUT_ROOT_RELATIVE / "1080P\u6807\u51c6\u589e\u5f3a"
DEFAULT_INPUT_DIR_NAME = DEFAULT_OUTPUT_DIR_NAME / ".\u8f93\u5165\u7f13\u5b58"
DEFAULT_REPORT_DIR_NAME = DIAGNOSTIC_ROOT_RELATIVE / "\u62a5\u544a"
DEFAULT_FEEDBACK_DIR_NAME = DIAGNOSTIC_ROOT_RELATIVE / "\u53cd\u9988\u5305"
DEFAULT_TMP_DIR_NAME = OUTPUT_ROOT_RELATIVE / "\u56fe\u7247\u538b\u7f29" / ".\u8fd0\u884c\u7f13\u5b58"
DEFAULT_DELIVERY_PACKAGE_DIR_NAME = DEFAULT_FEEDBACK_DIR_NAME
DEFAULT_CONFIG_DIR_NAME = Path(".")
DEFAULT_IMAGE_COMPRESSION_OUTPUT_ROOT = Path("D:/\u5f71\u754c\u6587\u4ef6/\u8f93\u51fa/\u56fe\u7247\u538b\u7f29")
DEFAULT_BETA_UPLOAD_DIR_NAME = OUTPUT_ROOT_RELATIVE / "1080P\u5b89\u5168\u589e\u5f3a" / ".\u8f93\u5165\u7f13\u5b58"
LEGACY_SAFE_BETA_INPUT_DIR_NAME = DEFAULT_BETA_UPLOAD_DIR_NAME
LEGACY_SAFE_BETA_OUTPUT_DIR_NAME = OUTPUT_ROOT_RELATIVE / "1080P\u5b89\u5168\u589e\u5f3a"
LEGACY_SAFE_BETA_FEEDBACK_DIR_NAME = DEFAULT_FEEDBACK_DIR_NAME / "1080P\u5b89\u5168\u589e\u5f3a"
IMAGE_COMPRESSION_OUTPUT_DIR_NAME = OUTPUT_ROOT_RELATIVE / "\u56fe\u7247\u538b\u7f29"
RUNTIME_LOG_DIR_NAME = DIAGNOSTIC_ROOT_RELATIVE / "\u65e5\u5fd7"
REQUIRED_FORMAL_SUBDIRECTORIES = (
    ("output_root", OUTPUT_ROOT_RELATIVE),
    ("diagnostic_root", DIAGNOSTIC_ROOT_RELATIVE),
    ("normal_output_dir", DEFAULT_OUTPUT_DIR_NAME),
    ("normal_input_dir", DEFAULT_INPUT_DIR_NAME),
    ("image_compression_output_dir", IMAGE_COMPRESSION_OUTPUT_DIR_NAME),
    ("tmp_dir", DEFAULT_TMP_DIR_NAME),
    ("safe_beta_output_dir", LEGACY_SAFE_BETA_OUTPUT_DIR_NAME),
    ("beta_upload_dir", DEFAULT_BETA_UPLOAD_DIR_NAME),
    ("report_dir", DEFAULT_REPORT_DIR_NAME),
    ("feedback_dir", DEFAULT_FEEDBACK_DIR_NAME),
    ("safe_beta_feedback_dir", LEGACY_SAFE_BETA_FEEDBACK_DIR_NAME),
    ("runtime_log_dir", RUNTIME_LOG_DIR_NAME),
)
BETA_LOG_QUEUE: queue.Queue[str] = queue.Queue(maxsize=256)


def _beta_log_worker() -> None:
    while True:
        line = BETA_LOG_QUEUE.get()
        try:
            sys.stderr.write(line + "\n")
            sys.stderr.flush()
        except Exception:
            pass


threading.Thread(target=_beta_log_worker, name="safe-1080p-beta-log", daemon=True).start()


def enqueue_beta_log(line: str) -> None:
    try:
        BETA_LOG_QUEUE.put_nowait(line)
    except queue.Full:
        pass


def _read_settings_file_safely() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _documents_dir() -> Path:
    if os.name == "nt":
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            return Path(user_profile) / "Documents"
    return Path.home() / "Documents"


def _ensure_directory_with_ownership(path: Path, *, parents: bool) -> dict:
    try:
        path.mkdir(parents=parents, exist_ok=False)
    except FileExistsError:
        if path.is_dir():
            return {
                "valid": True,
                "created_by_this_attempt": False,
                "failed_stage": "",
                "failure_reason": "",
            }
        return {
            "valid": False,
            "created_by_this_attempt": False,
            "failed_stage": "type_validation",
            "failure_reason": "路径已被同名文件占用。",
        }
    except OSError as exc:
        return {
            "valid": False,
            "created_by_this_attempt": False,
            "failed_stage": "create",
            "failure_reason": str(exc),
        }
    except Exception as exc:
        return {
            "valid": False,
            "created_by_this_attempt": False,
            "failed_stage": "create",
            "failure_reason": str(exc),
        }

    if not path.is_dir():
        return {
            "valid": False,
            "created_by_this_attempt": True,
            "failed_stage": "type_validation",
            "failure_reason": "目录创建后状态无效。",
        }
    return {
        "valid": True,
        "created_by_this_attempt": True,
        "failed_stage": "",
        "failure_reason": "",
    }


def _directory_writable(path: Path) -> tuple[bool, str]:
    try:
        probe = path / f".hdde_write_test_{uuid.uuid4().hex}.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _cleanup_newly_created_directories(created_directories: list[Path]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for directory in reversed(created_directories):
        try:
            if not directory.exists():
                continue
            if not directory.is_dir():
                failures.append({"path": str(directory), "reason": "新建路径已不再是目录，未执行清理。"})
                continue
            if any(directory.iterdir()):
                failures.append({"path": str(directory), "reason": "新建目录当前非空，未执行清理。"})
                continue
            directory.rmdir()
        except Exception as exc:
            failures.append({"path": str(directory), "reason": str(exc)})
    return failures


def _validate_required_formal_directories(base_dir: Path, created_directories: list[Path] | None = None) -> dict:
    created = list(created_directories or [])
    base_resolved = base_dir.resolve()

    def blocked(path: Path, stage: str, reason: str) -> dict:
        cleanup_failures = _cleanup_newly_created_directories(created)
        return {
            "directory_ready": False,
            "error_code": "REQUIRED_DIRECTORY_UNAVAILABLE",
            "failed_path": str(path),
            "failed_stage": stage,
            "failure_reason": reason,
            "message": f"必需目录不可用：{path}。请检查路径占用、目录权限或磁盘状态。",
            "created_directories": [str(item) for item in created],
            "cleanup_failures": cleanup_failures,
        }

    for _key, directory_name in REQUIRED_FORMAL_SUBDIRECTORIES:
        directory = base_dir / directory_name
        try:
            resolved = directory.resolve()
        except Exception as exc:
            return blocked(directory, "path_validation", str(exc))
        if not directory.is_absolute() or resolved == base_resolved or not _path_is_within(resolved, base_resolved):
            return blocked(directory, "path_validation", "必需目录路径不在正式根目录内。")
        creation = _ensure_directory_with_ownership(directory, parents=False)
        if creation["created_by_this_attempt"]:
            created.append(directory)
        if not creation["valid"]:
            return blocked(directory, creation["failed_stage"], creation["failure_reason"])
        writable, error = _directory_writable(directory)
        if not writable:
            return blocked(directory, "writable_check", error or "必需目录不可写。")

    return {
        "directory_ready": True,
        "error_code": "",
        "failed_path": "",
        "failed_stage": "",
        "failure_reason": "",
        "message": "正式目录及全部必需子目录已就绪。",
        "created_directories": [str(item) for item in created],
        "cleanup_failures": [],
    }


def _initial_formal_app_data_root() -> Path:
    if os.name == "nt" and Path("D:/").exists():
        return Path("D:/") / LEGACY_WORK_DIR_NAME
    if os.name == "nt":
        return _documents_dir() / APP_DATA_ROOT_NAME
    return Path.home() / APP_DATA_ROOT_NAME


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        resolved_path = path.resolve()
        resolved_root = root.resolve()
    except Exception:
        return False
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def _formal_root_validation_error(path: Path) -> tuple[str, str]:
    if not path.is_absolute():
        return "FORMAL_DIRECTORY_PATH_INVALID", "正式目录必须使用绝对路径。"
    forbidden_roots = [PROJECT_ROOT, Path.cwd()]
    for name in ("TEMP", "TMP"):
        value = str(os.environ.get(name) or "").strip()
        if value:
            forbidden_roots.append(Path(value))
    if any(_path_is_within(path, root) for root in forbidden_roots):
        return "FORMAL_DIRECTORY_PATH_FORBIDDEN", "正式目录不能位于项目目录、当前工作目录或系统临时目录中。"
    return "", ""


def resolve_app_data_root(settings: dict | None = None) -> dict:
    settings = settings if isinstance(settings, dict) else _read_settings_file_safely()
    configured = str(settings.get("app_data_root") or "").strip()
    saved = str(settings.get("last_app_data_root") or "").strip()
    if configured:
        source = "user_config"
        candidate = Path(configured).expanduser()
        first_initialization = False
    elif saved:
        source = "saved_config"
        candidate = Path(saved).expanduser()
        first_initialization = False
    else:
        source = "initial_default"
        candidate = _initial_formal_app_data_root()
        first_initialization = True

    error_code, validation_error = _formal_root_validation_error(candidate)
    if error_code:
        return {
            "path": candidate,
            "source": source,
            "exists": candidate.exists(),
            "writable": False,
            "directory_ready": False,
            "error_code": error_code,
            "error": validation_error,
            "message": validation_error,
            "created": False,
            "first_initialization": first_initialization,
            "required_directories_validated": False,
            "failed_path": str(candidate),
            "failed_stage": "path_validation",
            "failure_reason": validation_error,
            "created_directories": [],
            "cleanup_failures": [],
        }

    if not first_initialization and not candidate.exists():
        failure_reason = "已保存的正式目录不存在。"
        message = f"{failure_reason}请恢复该目录，或前往系统设置选择新目录。"
        return {
            "path": candidate,
            "source": source,
            "exists": False,
            "writable": False,
            "directory_ready": False,
            "error_code": "FORMAL_DIRECTORY_NOT_FOUND",
            "error": message,
            "message": message,
            "created": False,
            "first_initialization": False,
            "required_directories_validated": False,
            "failed_path": str(candidate),
            "failed_stage": "root_exists_check",
            "failure_reason": failure_reason,
            "created_directories": [],
            "cleanup_failures": [],
        }

    creation = _ensure_directory_with_ownership(candidate, parents=True)
    root_created = bool(creation["created_by_this_attempt"])
    if not creation["valid"]:
        error = creation["failure_reason"]
        cleanup_failures = _cleanup_newly_created_directories([candidate] if root_created else [])
        error_code = "FORMAL_DIRECTORY_NOT_WRITABLE" if candidate.exists() else "FORMAL_DIRECTORY_CREATE_FAILED"
        message = "正式目录不可用，请前往系统设置重新选择目录。"
        return {
            "path": candidate,
            "source": source,
            "exists": candidate.exists(),
            "writable": False,
            "directory_ready": False,
            "error_code": error_code,
            "error": f"{message} {error}".strip(),
            "message": message,
            "created": False,
            "first_initialization": first_initialization,
            "required_directories_validated": False,
            "failed_path": str(candidate),
            "failed_stage": creation["failed_stage"],
            "failure_reason": error,
            "created_directories": [str(candidate)] if root_created else [],
            "cleanup_failures": cleanup_failures,
        }

    writable, error = _directory_writable(candidate)
    if writable:
        required = _validate_required_formal_directories(candidate, [candidate] if root_created else [])
        if not required["directory_ready"]:
            return {
                "path": candidate,
                "source": source,
                "exists": candidate.exists(),
                "writable": bool(candidate.exists() and candidate.is_dir()),
                "directory_ready": False,
                "error_code": required["error_code"],
                "error": required["failure_reason"],
                "message": required["message"],
                "created": False,
                "first_initialization": first_initialization,
                "required_directories_validated": True,
                "failed_path": required["failed_path"],
                "failed_stage": required["failed_stage"],
                "failure_reason": required["failure_reason"],
                "created_directories": required["created_directories"],
                "cleanup_failures": required["cleanup_failures"],
            }
        return {
            "path": candidate,
            "source": source,
            "exists": True,
            "writable": True,
            "directory_ready": True,
            "error_code": "",
            "error": "",
            "message": required["message"],
            "created": root_created,
            "first_initialization": first_initialization,
            "required_directories_validated": True,
            "failed_path": "",
            "failed_stage": "",
            "failure_reason": "",
            "created_directories": required["created_directories"],
            "cleanup_failures": [],
        }

    cleanup_failures = _cleanup_newly_created_directories([candidate] if root_created else [])
    error_code = "FORMAL_DIRECTORY_NOT_WRITABLE" if candidate.exists() else "FORMAL_DIRECTORY_CREATE_FAILED"
    message = "正式目录不可写，请前往系统设置重新选择目录。" if candidate.exists() else "正式目录不存在且无法创建，请前往系统设置重新选择目录。"
    return {
        "path": candidate,
        "source": source,
        "exists": candidate.exists(),
        "writable": False,
        "directory_ready": False,
        "error_code": error_code,
        "error": f"{message} {error}".strip(),
        "message": message,
        "created": False,
        "first_initialization": first_initialization,
        "required_directories_validated": False,
        "failed_path": str(candidate),
        "failed_stage": "root_writable_check" if candidate.exists() else "root_create",
        "failure_reason": error,
        "created_directories": [str(candidate)] if root_created else [],
        "cleanup_failures": cleanup_failures,
    }


def get_app_data_root() -> Path:
    root_info = resolve_app_data_root()
    if not root_info["directory_ready"]:
        raise RuntimeError(root_info["message"])
    return Path(root_info["path"])


def default_output_dir() -> Path:
    return get_app_data_root() / DEFAULT_OUTPUT_DIR_NAME


def default_settings() -> dict:
    initial_root = _initial_formal_app_data_root()
    return {
        "app_data_root": "",
        "last_app_data_root": "",
        "default_output_dir": str(initial_root / DEFAULT_OUTPUT_DIR_NAME),
        "image_compression_default_output_root": str(DEFAULT_IMAGE_COMPRESSION_OUTPUT_ROOT),
        "input_cache_policy": "keep",
        "cleanup_input_cache_days": 0,
        "cleanup_input_cache_max_files": 0,
        "last_output_dir": "",
        "allow_custom_output_dir": True,
        "create_output_dir_if_missing": True,
        "default_output_format": "png",
        "target_resolution": "1080P",
    }


def _canonical_settings_json(settings: dict) -> str:
    return json.dumps(settings, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_settings_if_changed(next_settings: dict) -> dict:
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log_runtime_event(
            "SETTINGS_WRITE_FAILED",
            level=logging.ERROR,
            stage="settings_parent_directory",
            result="failed",
            error_category=ENVIRONMENT_ERROR,
            path=SETTINGS_PATH,
            reason=str(exc),
            impact="settings_not_persisted",
            action="check_settings_directory_permissions",
        )
        raise
    if SETTINGS_PATH.exists():
        try:
            current_settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            current_settings = None
        if isinstance(current_settings, dict) and _canonical_settings_json(current_settings) == _canonical_settings_json(next_settings):
            log_runtime_event(
                "SETTINGS_WRITE_SKIPPED",
                level=logging.WARNING,
                stage="settings_write",
                result="skipped",
                path=SETTINGS_PATH,
                reason="settings_unchanged",
                impact="settings_file_preserved",
                action="none",
            )
            return {
                "status": "SKIPPED_UNCHANGED",
                "write_skipped": True,
                "write_performed": False,
            }
    try:
        SETTINGS_PATH.write_text(json.dumps(next_settings, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        log_runtime_event(
            "SETTINGS_WRITE_FAILED",
            level=logging.ERROR,
            stage="settings_write",
            result="failed",
            error_category=ENVIRONMENT_ERROR,
            path=SETTINGS_PATH,
            reason=str(exc),
            impact="settings_not_persisted",
            action="check_settings_file_permissions",
        )
        raise
    log_runtime_event(
        "SETTINGS_WRITE_SUCCEEDED",
        stage="settings_write",
        result="success",
        path=SETTINGS_PATH,
        impact="settings_persisted",
        action="none",
    )
    return {
        "status": "WRITE_PERFORMED",
        "write_skipped": False,
        "write_performed": True,
    }


def load_settings(load_status: dict | None = None) -> dict:
    settings = default_settings()
    settings_exists = SETTINGS_PATH.exists()
    settings_read_valid = False
    settings_complete = False
    settings_read_reason = "settings_file_missing"
    if settings_exists:
        try:
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings_read_valid = True
                settings_complete = all(key in loaded for key in settings)
                settings.update({key: value for key, value in loaded.items() if value is not None})
                settings_read_reason = "settings_loaded" if settings_complete else "settings_fields_incomplete"
            else:
                settings_read_reason = "settings_root_is_not_an_object"
        except Exception as exc:
            settings_read_reason = f"{type(exc).__name__}: {exc}"
    if settings_read_valid:
        log_runtime_event(
            "SETTINGS_READ_SUCCEEDED",
            stage="settings_read",
            result="complete" if settings_complete else "incomplete",
            path=SETTINGS_PATH,
            reason=settings_read_reason,
            impact="settings_loaded",
            action="none" if settings_complete else "complete_settings_configuration",
        )
    else:
        log_runtime_event(
            "SETTINGS_READ_FAILED",
            level=logging.ERROR if settings_exists else logging.WARNING,
            stage="settings_read",
            result="failed" if settings_exists else "missing",
            error_category=CONFIGURATION_ERROR,
            path=SETTINGS_PATH,
            reason=settings_read_reason,
            impact="settings_defaults_used_without_overwrite",
            action="repair_settings_file" if settings_exists else "initialize_settings_after_directory_validation",
        )
    had_saved_formal_root = bool(str(settings.get("app_data_root") or "").strip() or str(settings.get("last_app_data_root") or "").strip())
    root_info = resolve_app_data_root(settings)
    first_initialization_can_persist = (
        not had_saved_formal_root
        and root_info["directory_ready"]
        and (not settings_exists or (settings_read_valid and settings_complete))
    )
    if first_initialization_can_persist:
        settings["last_app_data_root"] = str(root_info["path"])
        write_settings_if_changed(settings)
    else:
        if had_saved_formal_root:
            skip_reason = "formal_root_already_configured"
        elif not root_info["directory_ready"]:
            skip_reason = "formal_directory_not_ready"
        elif settings_exists and not settings_read_valid:
            skip_reason = "settings_read_failed"
        elif settings_exists and not settings_complete:
            skip_reason = "settings_fields_incomplete"
        else:
            skip_reason = "settings_persistence_not_required"
        log_runtime_event(
            "SETTINGS_WRITE_SKIPPED",
            level=logging.WARNING,
            stage="settings_write_decision",
            result="skipped",
            path=SETTINGS_PATH,
            reason=skip_reason,
            impact="settings_file_preserved",
            action="none" if had_saved_formal_root else "resolve_settings_or_directory_issue",
        )
    if load_status is not None:
        if settings_read_valid and settings_complete:
            status = "loaded"
        elif settings_read_valid:
            status = "incomplete"
        elif settings_exists:
            status = "invalid"
        else:
            status = "missing"
        load_status.clear()
        load_status.update(
            {
                "status": status,
                "file_path": str(SETTINGS_PATH),
                "file_exists": settings_exists,
                "loaded_from_file": settings_read_valid,
                "complete": settings_complete,
                "defaults_applied": not settings_complete,
                "reason": settings_read_reason,
                "persisted_on_first_initialization": first_initialization_can_persist,
            }
        )
    return settings


def read_frontend_build_identity(project_root: Path | None = None, display_version: str = APP_VERSION) -> dict:
    root = Path(project_root or PROJECT_ROOT)
    dist_root = root / "dist"
    index_path = dist_root / "index.html"
    result = {
        "status": "unavailable",
        "build_id": "",
        "source_path": "",
        "error_code": "",
        "reason": "",
    }
    if not index_path.is_file():
        return {
            **result,
            "error_code": "BUILD_ARTIFACT_INDEX_MISSING",
            "reason": "当前前端构建入口不存在。",
        }
    try:
        index_text = index_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return {
            **result,
            "source_path": str(index_path),
            "error_code": "BUILD_ARTIFACT_INDEX_UNREADABLE",
            "reason": str(exc),
        }
    script_match = re.search(r'<script[^>]+src=["\']([^"\']+\.js)["\']', index_text)
    if not script_match:
        return {
            **result,
            "source_path": str(index_path),
            "error_code": "BUILD_ARTIFACT_REFERENCE_MISSING",
            "reason": "当前前端构建入口未引用 JavaScript 产物。",
        }
    try:
        dist_resolved = dist_root.resolve()
        asset_path = (dist_root / script_match.group(1).lstrip("/")).resolve()
        asset_path.relative_to(dist_resolved)
    except (OSError, ValueError) as exc:
        return {
            **result,
            "source_path": str(index_path),
            "error_code": "BUILD_ARTIFACT_PATH_INVALID",
            "reason": str(exc),
        }
    if not asset_path.is_file():
        return {
            **result,
            "source_path": str(asset_path),
            "error_code": "BUILD_ARTIFACT_MISSING",
            "reason": "当前前端 JavaScript 构建产物不存在。",
        }
    try:
        asset_text = asset_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return {
            **result,
            "source_path": str(asset_path),
            "error_code": "BUILD_ARTIFACT_UNREADABLE",
            "reason": str(exc),
        }
    pattern = re.compile(
        rf"{re.escape(display_version)}\+(?:[0-9a-f]{{7,12}}|nogit)\.(?:clean|dirty|unknown)\.\d{{8}}T\d{{9}}Z"
    )
    build_ids = sorted(set(pattern.findall(asset_text)))
    if len(build_ids) != 1:
        return {
            **result,
            "source_path": str(asset_path),
            "error_code": "BUILD_ID_MISSING" if not build_ids else "BUILD_ID_AMBIGUOUS",
            "reason": "当前前端产物未包含唯一 Build ID。",
        }
    return {
        "status": "loaded",
        "build_id": build_ids[0],
        "source_path": str(asset_path),
        "error_code": "",
        "reason": "",
    }


def read_only_formal_root_status(user_dirs: dict) -> dict:
    root_text = str(user_dirs.get("app_data_root") or "").strip()
    root_path = Path(root_text) if root_text else None
    inspection_error = ""
    try:
        root_exists = bool(root_path and root_path.exists() and root_path.is_dir())
    except OSError as exc:
        root_exists = False
        inspection_error = f"{type(exc).__name__}: {exc}"
    missing_required_directories: list[str] = []
    if root_path and root_exists:
        for _, relative_path in REQUIRED_FORMAL_SUBDIRECTORIES:
            required_path = root_path / relative_path
            try:
                required_directory_present = required_path.exists() and required_path.is_dir()
            except OSError as exc:
                required_directory_present = False
                if not inspection_error:
                    inspection_error = f"{type(exc).__name__}: {exc}"
            if not required_directory_present:
                missing_required_directories.append(str(required_path))
    startup_ready = bool(user_dirs.get("directory_ready"))
    directory_ready = bool(startup_ready and root_exists and not missing_required_directories)
    if not startup_ready:
        error_code = str(user_dirs.get("directory_error_code") or "FORMAL_DIRECTORY_NOT_READY")
        failed_path = str(user_dirs.get("failed_path") or root_text)
        failed_stage = str(user_dirs.get("failed_stage") or "startup_validation")
        reason = str(user_dirs.get("failure_reason") or user_dirs.get("directory_message") or "正式目录未就绪。")
    elif inspection_error:
        error_code = "FORMAL_DIRECTORY_READ_FAILED"
        failed_path = root_text
        failed_stage = "read_only_presence_check"
        reason = inspection_error
    elif not root_exists:
        error_code = "FORMAL_DIRECTORY_STATE_CHANGED"
        failed_path = root_text
        failed_stage = "read_only_presence_check"
        reason = "启动后正式根目录已不存在或不再是目录。"
    elif missing_required_directories:
        error_code = "REQUIRED_DIRECTORY_STATE_CHANGED"
        failed_path = missing_required_directories[0]
        failed_stage = "read_only_presence_check"
        reason = "启动后必需正式子目录缺失或不再是目录。"
    else:
        error_code = ""
        failed_path = ""
        failed_stage = ""
        reason = ""
    return {
        "status": "ready" if directory_ready else "blocked",
        "path": root_text,
        "source": str(user_dirs.get("app_data_root_source") or ""),
        "directory_ready": directory_ready,
        "exists": root_exists,
        "writable_at_startup": bool(user_dirs.get("app_data_root_writable")),
        "startup_validation_ready": startup_ready,
        "required_directories_present": not missing_required_directories,
        "missing_required_directories": missing_required_directories,
        "error_code": error_code,
        "failed_path": failed_path,
        "failed_stage": failed_stage,
        "reason": reason,
        "validation_basis": "startup_validation_plus_read_only_presence_check",
    }


def get_desktop_work_dirs() -> tuple[Path, Path]:
    user_dirs = resolve_hdde_user_dirs()
    return user_dirs["normal_input_dir"], user_dirs["normal_output_dir"]


def normalize_user_output_root(output_root: Path) -> Path:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_hdde_user_dirs(settings: dict | None = None) -> dict:
    root_info = resolve_app_data_root(settings)
    base_dir = Path(root_info["path"])
    normal_input_dir = base_dir / DEFAULT_INPUT_DIR_NAME
    normal_output_dir = base_dir / DEFAULT_OUTPUT_DIR_NAME
    report_dir = base_dir / DEFAULT_REPORT_DIR_NAME
    feedback_dir = base_dir / DEFAULT_FEEDBACK_DIR_NAME
    tmp_dir = base_dir / DEFAULT_TMP_DIR_NAME
    beta_upload_dir = base_dir / DEFAULT_BETA_UPLOAD_DIR_NAME
    delivery_package_dir = base_dir / DEFAULT_DELIVERY_PACKAGE_DIR_NAME
    config_dir = base_dir / DEFAULT_CONFIG_DIR_NAME
    safe_beta_input_root = base_dir / LEGACY_SAFE_BETA_INPUT_DIR_NAME
    safe_beta_output_dir = base_dir / LEGACY_SAFE_BETA_OUTPUT_DIR_NAME
    safe_beta_feedback_dir = base_dir / LEGACY_SAFE_BETA_FEEDBACK_DIR_NAME
    image_compression_output_dir = base_dir / IMAGE_COMPRESSION_OUTPUT_DIR_NAME
    runtime_log_dir = base_dir / RUNTIME_LOG_DIR_NAME
    if root_info["directory_ready"] and not root_info.get("required_directories_validated"):
        required = _validate_required_formal_directories(base_dir)
        if not required["directory_ready"]:
            root_info = {
                **root_info,
                "directory_ready": False,
                "error_code": required["error_code"],
                "error": required["failure_reason"],
                "message": required["message"],
                "required_directories_validated": True,
                "failed_path": required["failed_path"],
                "failed_stage": required["failed_stage"],
                "failure_reason": required["failure_reason"],
                "created_directories": required["created_directories"],
                "cleanup_failures": required["cleanup_failures"],
            }
    return {
        "base_dir": base_dir,
        "output_root": base_dir / OUTPUT_ROOT_RELATIVE,
        "diagnostic_root": base_dir / DIAGNOSTIC_ROOT_RELATIVE,
        "app_data_root": base_dir,
        "app_data_root_source": root_info["source"],
        "app_data_root_exists": bool(root_info["exists"]),
        "app_data_root_writable": bool(root_info["writable"]),
        "directory_ready": bool(root_info["directory_ready"]),
        "directory_error_code": str(root_info["error_code"]),
        "directory_message": str(root_info["message"]),
        "failed_path": str(root_info.get("failed_path") or ""),
        "failed_stage": str(root_info.get("failed_stage") or ""),
        "failure_reason": str(root_info.get("failure_reason") or ""),
        "cleanup_failures": list(root_info.get("cleanup_failures") or []),
        "normal_input_dir": normal_input_dir,
        "normal_output_dir": normal_output_dir,
        "report_dir": report_dir,
        "feedback_dir": feedback_dir,
        "tmp_dir": tmp_dir,
        "beta_upload_dir": beta_upload_dir,
        "delivery_package_dir": delivery_package_dir,
        "config_dir": config_dir,
        "safe_beta_input_root": safe_beta_input_root,
        "safe_beta_output_dir": safe_beta_output_dir,
        "safe_beta_feedback_dir": safe_beta_feedback_dir,
        "image_compression_output_dir": image_compression_output_dir,
        "runtime_log_dir": runtime_log_dir,
    }


def safe_upload_name(filename: str | None) -> str:
    original = Path(filename or "image.png").name
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", original).strip(" .")
    return cleaned or "image.png"


def safe_beta_run_id(value: str | None) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("._-")
    return cleaned or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def prepare_safe_beta_user_input_dir(beta_run_id: str | None) -> Path:
    user_dirs = resolve_hdde_user_dirs()
    input_root = user_dirs["beta_upload_dir"]
    task_dir = input_root / safe_beta_run_id(beta_run_id)
    input_root_resolved = input_root.resolve()
    if task_dir.exists():
        task_dir_resolved = task_dir.resolve()
        if input_root_resolved != task_dir_resolved and input_root_resolved in task_dir_resolved.parents:
            shutil.rmtree(task_dir)
        else:
            raise RuntimeError(f"BETA_INPUT_DIR_UNSAFE_PATH: {task_dir}")
    task_dir.mkdir(parents=True, exist_ok=True)
    return task_dir


def unique_child_path(parent: Path, filename: str) -> Path:
    candidate = parent / safe_upload_name(filename)
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 2
    while True:
        next_candidate = parent / f"{stem}_{counter:02d}{suffix}"
        if not next_candidate.exists():
            return next_candidate
        counter += 1


def public_file_url(kind: str, filename: str) -> str:
    return f"/api/file/{kind}/{filename}"


def parse_scale_value(value) -> int:
    text = str(value or "2").lower().replace("x", "").strip()
    try:
        parsed = int(text)
    except ValueError:
        return 2
    return 4 if parsed == 4 else 2


def parse_output_format(value) -> str:
    output_format = str(value or "png").lower().lstrip(".").strip()
    if output_format == "auto":
        return "png"
    if output_format == "jpeg":
        output_format = "jpg"
    return output_format if output_format in {"png", "jpg", "webp"} else "png"


def make_task_id() -> str:
    return f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def cleanup_input_cache(input_dir: Path, max_age_days: int = 0, max_files: int = 0) -> dict:
    """Reserved V0.4 cache cleanup hook.

    V0.4 keeps uploaded originals for traceability. Automatic deletion is not
    enabled until the user explicitly defines retention limits.
    """
    _ = Path(input_dir), max_age_days, max_files
    return {"enabled": False, "removed": 0, "reason": "V0.4 keeps input cache by default."}


def parse_bool_value(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "debug"}


def format_sse_log(index: int, total: int, message: str, done: bool = False, extra: dict | None = None) -> str:
    payload = {
        "index": index,
        "total": total,
        "message": message,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "done": done,
    }
    if extra:
        payload.update(extra)
    return f"event: restoration.log\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def build_web_app():
    try:
        from fastapi import FastAPI, File, Form, HTTPException, UploadFile
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse, StreamingResponse
    except ImportError as exc:
        raise RuntimeError("缺少 FastAPI 服务依赖。请先运行：pip install -r requirements.txt") from exc

    from backend.restoration_server import RESTORATION_LOGS
    from backend.v036_output_core import build_output_plan, process_v036_output, sha256_file
    from engine.io import read_image

    input_dir, output_root = get_desktop_work_dirs()
    output_formal_dir = normalize_user_output_root(output_root)
    runtime_root = Path(__file__).resolve().parent / "runtime"
    output_work_dir = runtime_root / "work"
    output_debug_dir = runtime_root / "debug"
    output_test_dir = runtime_root / "test"
    for directory in (output_formal_dir, output_work_dir, output_debug_dir, output_test_dir):
        directory.mkdir(parents=True, exist_ok=True)
    task_registry: dict[str, dict] = {}

    app = FastAPI(title="VisualMasterPro V0.3 API", version=APP_VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=SERVER_CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def resolve_public_file(kind: str, filename: str) -> Path:
        roots = {
            "uploads": input_dir,
            "outputs": output_formal_dir,
            "work": output_work_dir,
            "debug": output_debug_dir,
            "test": output_test_dir,
        }
        root = roots.get(kind)
        if root is None:
            raise HTTPException(status_code=404, detail="未知文件类型。")
        target = (root / filename).resolve()
        root_resolved = root.resolve()
        if root_resolved not in target.parents and target != root_resolved:
            raise HTTPException(status_code=403, detail="非法文件路径。")
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="文件不存在。")
        return target

    def run_image_pipeline(task: dict) -> dict:
        task["status"] = "processing"
        result = process_v036_output(
            task["input_path"],
            task["output_root"],
            mode=task["mode"],
            output_profile=task["output_profile"],
            output_format=task["output_format"],
            initial_timing=task.get("debug_timing"),
            debug_keep_intermediate=task.get("debug_keep_intermediate", False),
        )
        final_path = result["final_output_path"]
        main_path = result["main_output_path"]
        optimized_path = result["optimized_output_path"]
        main_output_url = public_file_url("work", main_path.name) if main_path else None
        optimized_output_url = public_file_url("work", optimized_path.name) if optimized_path else None
        debug_quality = dict(result.get("debug_quality") or {})
        for key in (
            "input_size_bytes",
            "main_size_bytes",
            "optimized_size_bytes",
            "final_size_bytes",
            "file_size_ratio",
            "compression_saved_ratio",
            "quality_preserved",
            "compression_note",
            "input_hash",
            "output_hash",
            "hash_equal",
            "pixel_diff_score",
            "output_changed",
            "warnings",
        ):
            debug_quality.setdefault(key, result.get(key))
        task.update(
            {
                "status": "completed",
                "output_path": final_path,
                "enhancedUrl": public_file_url("outputs", final_path.name),
                "main_output_url": main_output_url,
                "optimized_output_url": optimized_output_url,
                "final_output_url": public_file_url("outputs", final_path.name),
                "final_output_exists": final_path.exists(),
                "sourceWidth": result["input_width"],
                "sourceHeight": result["input_height"],
                "width": result["width"],
                "height": result["height"],
                "qualityFlag": result["compression_note"],
                "debug_quality": debug_quality,
                "debug_timing": result["debug_timing"],
                "debug_log_path": result["debug_log_path"],
                **{key: result.get(key) for key in [
                    "output_profile",
                    "output_format",
                    "selected_output_profile",
                    "selected_output_format",
                    "final_output_type",
                    "input_width",
                    "input_height",
                    "output_width",
                    "output_height",
                    "target_width",
                    "target_height",
                    "aspect_ratio",
                    "aspect_preset",
                    "scale_policy",
                    "resolution_gate_pass",
                    "visual_quality_gate_pass",
                    "quality_1080p_pass",
                    "quality_1080p_level",
                    "visual_quality_note",
                    "image_type",
                    "image_type_features",
                    "face_detail_score",
                    "face_detail_gain",
                    "hair_texture_score",
                    "hair_texture_gain",
                    "fabric_texture_score",
                    "fabric_texture_gain",
                    "text_edge_clean_score",
                    "small_text_readability_score",
                    "dark_detail_score",
                    "dark_detail_gain",
                    "over_smoothing_risk",
                    "texture_loss_risk",
                    "final_selection_reason",
                    "input_size_bytes",
                    "main_size_bytes",
                    "optimized_size_bytes",
                    "final_size_bytes",
                    "file_size_ratio",
                    "compression_saved_ratio",
                    "quality_preserved",
                    "compression_note",
                    "output_changed",
                    "hash_equal",
                    "pixel_diff_score",
                    "has_alpha",
                    "has_real_alpha",
                    "alpha_used",
                    "selected_format_reason",
                    "debug_keep_intermediate",
                ]},
                "output_contract": {
                    "enhancedUrl": public_file_url("outputs", final_path.name),
                    "main_output_url": main_output_url,
                    "optimized_output_url": optimized_output_url,
                    "final_output_url": public_file_url("outputs", final_path.name),
                    "enhanced_equals_final": True,
                    "formal_output_dir": str(output_formal_dir),
                    "work_output_dir": str(output_work_dir),
                    "debug_output_dir": str(output_debug_dir),
                    "test_output_dir": str(output_test_dir),
                    "official_images_only_final": True,
                    "final_output_exists": final_path.exists(),
                },
                "completedAt": datetime.now().isoformat(timespec="seconds"),
            }
        )
        return task

    async def stream_task_events(task_id: str, delay: float = 0.38):
        task = task_registry.get(task_id) or task_registry.get(DEFAULT_TASK_ID)
        total = len(RESTORATION_LOGS)

        if not task:
            yield format_sse_log(1, total, "SSE CONNECTED /task/task_vmp_v03_core/stream")
            yield format_sse_log(2, total, "未发现待处理图片，请先在工作台上传图片。", done=True)
            yield "data: [DONE]\n\n"
            return

        worker = asyncio.create_task(asyncio.to_thread(run_image_pipeline, task))
        yield format_sse_log(1, total, RESTORATION_LOGS[0])

        for index, message in enumerate(RESTORATION_LOGS[1:-1], start=2):
            await asyncio.sleep(max(0.0, float(delay)))
            if index == total - 1:
                target_w = task.get("output_width") or task.get("target_width")
                target_h = task.get("output_height") or task.get("target_height")
                message = (
                    f"1080P 质量守门：尺寸目标 {target_w}×{target_h}，"
                    "正在检测文字清晰度、边缘质量、色彩忠实度与伪高清风险。"
                )
            yield format_sse_log(index, total, message)

        try:
            await worker
            debug_quality = task.get("debug_quality") or {}
            debug_timing = task.get("debug_timing") or {}
            warnings = debug_quality.get("warnings") or []
            final_message = (
                f"1080P 质量判断：image_type={task.get('image_type')}，"
                f"quality_1080p_pass={task.get('quality_1080p_pass')}，"
                f"quality_level={task.get('quality_1080p_level')}，"
                f"text_clarity_gain={debug_quality.get('text_clarity_gain')}，"
                f"edge_quality_gain={debug_quality.get('edge_quality_gain')}，"
                f"detail_stability={debug_quality.get('detail_stability_score')}，"
                f"over_smoothing_risk={debug_quality.get('over_smoothing_risk')}，"
                f"texture_loss_risk={debug_quality.get('texture_loss_risk')}，"
                f"color_fidelity={debug_quality.get('color_fidelity_score')}，"
                f"pseudo_hd_risk={debug_quality.get('pseudo_hd_risk')}，"
                f"final_selection={debug_quality.get('final_selection_reason')}，"
                f"final_output_url={task.get('final_output_url')} 已生成，"
                f"size_ratio={debug_quality.get('file_size_ratio')}，"
                f"output_changed={debug_quality.get('output_changed')}，"
                f"hash_equal={debug_quality.get('hash_equal')}，"
                f"pixel_diff_score={debug_quality.get('pixel_diff_score')}，"
                f"final_output_type={task.get('final_output_type')}，"
                f"total_time={debug_timing.get('total_time')}s"
            )
            if warnings:
                final_message = f"{final_message}; {'; '.join(warnings)}"
            yield format_sse_log(
                total,
                total,
                final_message,
                done=True,
                extra={
                    "debug_quality": debug_quality,
                    "debug_timing": debug_timing,
                    "outputUrl": task.get("enhancedUrl"),
                    "output_contract": {
                        "main_output_url": task.get("main_output_url"),
                        "optimized_output_url": task.get("optimized_output_url"),
                        "final_output_url": task.get("final_output_url") or task.get("enhancedUrl"),
                        "output_profile": task.get("output_profile"),
                        "output_format": task.get("output_format"),
                        "selected_output_profile": task.get("selected_output_profile"),
                        "selected_output_format": task.get("selected_output_format"),
                        "final_output_type": task.get("final_output_type"),
                        "quality_preserved": task.get("quality_preserved"),
                        "compression_note": task.get("compression_note"),
                        "quality_1080p_pass": task.get("quality_1080p_pass"),
                        "quality_1080p_level": task.get("quality_1080p_level"),
                        "resolution_gate_pass": task.get("resolution_gate_pass"),
                        "visual_quality_gate_pass": task.get("visual_quality_gate_pass"),
                        "enhanced_equals_final": task.get("enhancedUrl") == (task.get("final_output_url") or task.get("enhancedUrl")),
                    },
                },
            )
        except Exception as exc:
            task["status"] = "failed"
            task["error"] = str(exc)
            yield format_sse_log(total, total, f"任务失败：{exc}", done=True)

        yield "data: [DONE]\n\n"

    @app.get("/api/health")
    async def health():
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "message": "VisualMasterPro V0.3 API 已就绪。",
            "data": {
                "version": APP_VERSION,
                "host": SERVER_HOST,
                "port": SERVER_PORT,
                "inputDir": str(input_dir),
                "outputDir": str(output_formal_dir),
                "uploadEndpoint": "/api/upload",
                "streamEndpoint": f"/api/v1/tasks/{DEFAULT_TASK_ID}/stream",
                "logLines": len(RESTORATION_LOGS),
                "backendStage": "V0.3.6",
                "outputProfiles": [
                    {"key": "delivery_1080p", "name": "高清交付 1080P", "default": True},
                    {"key": "preview_light", "name": "轻量优化版", "default": False},
                    {"key": "fidelity_original", "name": "原尺寸忠实增强", "default": False},
                ],
                "outputFormats": [
                    {"key": "auto", "name": "自动", "default": True},
                    {"key": "png", "name": "PNG", "default": False},
                    {"key": "jpg", "name": "JPG", "default": False},
                    {"key": "webp", "name": "WebP", "default": False},
                ],
                "cors": "ONLINE",
                "topology": [
                    {"name": "Local Client", "port": 5173, "status": "ONLINE"},
                    {"name": "XHR Stream", "contract": "file/mode/scale/format", "status": "READY"},
                    {"name": "Python Runtime", "port": 8787, "status": "ONLINE"},
                    {"name": "CORS", "policy": "ALLOW_ALL", "status": "ONLINE"},
                ],
                "modes": [
                    {"key": "fidelity", "name": "原图忠实", "status": "READY"},
                    {"key": "text_safe", "name": "文本增强", "status": "READY"},
                    {"key": "sharp_4k", "name": "极限自然", "status": "READY"},
                    {"key": "ai_image_clean", "name": "极境夜景", "status": "READY"},
                ],
            },
        }

    @app.get("/api/stream")
    @app.get("/api/v1/tasks/task_vmp_v03_core/stream")
    @app.get("/api/v1/tasks/{task_id}/stream")
    async def stream(task_id: str = DEFAULT_TASK_ID, delay: float = 0.38):
        return StreamingResponse(
            stream_task_events(task_id, delay),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.get("/api/file/{kind}/{filename:path}")
    async def serve_file(kind: str, filename: str):
        return FileResponse(resolve_public_file(kind, filename))

    @app.get("/api/v1/tasks/{task_id}")
    async def task_status(task_id: str):
        task = task_registry.get(task_id) or task_registry.get(DEFAULT_TASK_ID)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在。")
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "data": {
                "taskId": task.get("taskId", task_id),
                "status": task.get("status"),
                "fileName": task.get("fileName"),
                "mode": task.get("mode"),
                "scale": task.get("scale"),
                "format": task.get("format"),
                "originalUrl": public_file_url("uploads", Path(task["input_path"]).name),
                "enhancedUrl": task.get("enhancedUrl") or public_file_url("outputs", Path(task["expected_output_path"]).name),
                "main_output_url": task.get("main_output_url"),
                "optimized_output_url": task.get("optimized_output_url"),
                "final_output_url": task.get("final_output_url") or task.get("enhancedUrl") or public_file_url("outputs", Path(task["expected_output_path"]).name),
                "final_output_exists": bool(task.get("final_output_exists")),
                "output_profile": task.get("output_profile"),
                "output_format": task.get("output_format"),
                "selected_output_profile": task.get("selected_output_profile"),
                "selected_output_format": task.get("selected_output_format"),
                "final_output_type": task.get("final_output_type"),
                "input_width": task.get("input_width") or task.get("sourceWidth"),
                "input_height": task.get("input_height") or task.get("sourceHeight"),
                "output_width": task.get("output_width") or task.get("width"),
                "output_height": task.get("output_height") or task.get("height"),
                "target_width": task.get("target_width"),
                "target_height": task.get("target_height"),
                "aspect_ratio": task.get("aspect_ratio"),
                "aspect_preset": task.get("aspect_preset"),
                "scale_policy": task.get("scale_policy"),
                "resolution_gate_pass": task.get("resolution_gate_pass"),
                "visual_quality_gate_pass": task.get("visual_quality_gate_pass"),
                "quality_1080p_pass": task.get("quality_1080p_pass"),
                "quality_1080p_level": task.get("quality_1080p_level"),
                "visual_quality_note": task.get("visual_quality_note"),
                "image_type": task.get("image_type"),
                "image_type_features": task.get("image_type_features"),
                "face_detail_score": task.get("face_detail_score"),
                "face_detail_gain": task.get("face_detail_gain"),
                "hair_texture_score": task.get("hair_texture_score"),
                "hair_texture_gain": task.get("hair_texture_gain"),
                "fabric_texture_score": task.get("fabric_texture_score"),
                "fabric_texture_gain": task.get("fabric_texture_gain"),
                "text_edge_clean_score": task.get("text_edge_clean_score"),
                "small_text_readability_score": task.get("small_text_readability_score"),
                "dark_detail_score": task.get("dark_detail_score"),
                "dark_detail_gain": task.get("dark_detail_gain"),
                "over_smoothing_risk": task.get("over_smoothing_risk"),
                "texture_loss_risk": task.get("texture_loss_risk"),
                "final_selection_reason": task.get("final_selection_reason"),
                "input_size_bytes": task.get("input_size_bytes"),
                "main_size_bytes": task.get("main_size_bytes"),
                "optimized_size_bytes": task.get("optimized_size_bytes"),
                "final_size_bytes": task.get("final_size_bytes"),
                "file_size_ratio": task.get("file_size_ratio"),
                "compression_saved_ratio": task.get("compression_saved_ratio"),
                "quality_preserved": task.get("quality_preserved"),
                "compression_note": task.get("compression_note"),
                "output_changed": task.get("output_changed"),
                "hash_equal": task.get("hash_equal"),
                "pixel_diff_score": task.get("pixel_diff_score"),
                "has_alpha": task.get("has_alpha"),
                "has_real_alpha": task.get("has_real_alpha"),
                "alpha_used": task.get("alpha_used"),
                "selected_format_reason": task.get("selected_format_reason"),
                "debug_keep_intermediate": task.get("debug_keep_intermediate"),
                "debug_quality": task.get("debug_quality"),
                "debug_timing": task.get("debug_timing"),
                "debug_log_path": task.get("debug_log_path"),
                "output_contract": task.get("output_contract"),
                "error": task.get("error"),
            },
        }

    @app.post("/api/upload")
    async def upload_file(
        file: UploadFile = File(...),
        mode: str = Form("fidelity"),
        scale: str = Form("2"),
        output_profile: str = Form("delivery_1080p"),
        output_format: str | None = Form(None),
        format: str | None = Form(None),
        debug_keep_intermediate: str | None = Form("false"),
        debug_mode: str | None = Form(None),
    ):
        upload_name = safe_upload_name(file.filename)
        requested_output_format = parse_output_format(output_format or format or "auto")
        scale_value = parse_scale_value(scale)

        receive_start = time.perf_counter()
        raw = await file.read()
        receive_file_time = round(time.perf_counter() - receive_start, 6)
        if not raw:
            raise HTTPException(status_code=400, detail="上传图片为空。")

        input_dir.mkdir(parents=True, exist_ok=True)
        for directory in (output_formal_dir, output_work_dir, output_debug_dir, output_test_dir):
            directory.mkdir(parents=True, exist_ok=True)
        saved_path = input_dir / upload_name
        save_start = time.perf_counter()
        saved_path.write_bytes(raw)
        save_input_time = round(time.perf_counter() - save_start, 6)

        source_image = read_image(saved_path)
        source_height, source_width = source_image.shape[:2] if source_image is not None else (0, 0)
        input_hash = sha256_file(saved_path)
        input_size_bytes = saved_path.stat().st_size
        keep_intermediate = parse_bool_value(debug_keep_intermediate) or parse_bool_value(debug_mode)
        output_plan = build_output_plan(saved_path, output_root, output_profile, requested_output_format, keep_intermediate)
        expected_output_path = output_plan["paths"]["final"]
        task = {
            "taskId": DEFAULT_TASK_ID,
            "status": "ready",
            "input_path": saved_path,
            "output_root": output_formal_dir,
            "output_dir": output_formal_dir,
            "expected_output_path": expected_output_path,
            "mode": mode or "fidelity",
            "scale": scale_value,
            "format": requested_output_format,
            "output_profile": output_profile or "delivery_1080p",
            "output_format": requested_output_format,
            "selected_output_profile": output_plan["selected_output_profile"],
            "selected_output_format": output_plan["selected_output_format"],
            "fileName": upload_name,
            "createdAt": datetime.now().isoformat(timespec="seconds"),
            "input_hash": input_hash,
            "input_size_bytes": input_size_bytes,
            "input_width": source_width,
            "input_height": source_height,
            "output_width": output_plan["output_width"],
            "output_height": output_plan["output_height"],
            "target_width": output_plan["target_width"],
            "target_height": output_plan["target_height"],
            "aspect_ratio": output_plan["aspect_ratio"],
            "aspect_preset": output_plan["aspect_preset"],
            "scale_policy": output_plan["scale_policy"],
            "image_type": output_plan["image_type"],
            "image_type_features": output_plan["image_type_features"],
            "resolution_gate_pass": output_plan["resolution_gate_pass"],
            "has_alpha": output_plan["has_alpha"],
            "has_real_alpha": output_plan["has_real_alpha"],
            "alpha_used": output_plan["alpha_used"],
            "selected_format_reason": output_plan["selected_format_reason"],
            "debug_keep_intermediate": keep_intermediate,
            "debug_timing": {
                "receive_file_time": receive_file_time,
                "save_input_time": save_input_time,
            },
        }
        task_registry[DEFAULT_TASK_ID] = task

        data = {
            "fileName": upload_name,
            "taskId": DEFAULT_TASK_ID,
            "mode": mode or "fidelity",
            "originalPath": str(saved_path),
            "outputPath": str(expected_output_path),
            "originalUrl": public_file_url("uploads", saved_path.name),
            "enhancedUrl": public_file_url("outputs", expected_output_path.name),
            "main_output_url": public_file_url("work", output_plan["paths"]["main"].name) if keep_intermediate else None,
            "optimized_output_url": public_file_url("work", output_plan["paths"]["optimized"].name) if keep_intermediate else None,
            "final_output_url": public_file_url("outputs", expected_output_path.name),
            "final_output_exists": expected_output_path.exists(),
            "output_profile": output_profile or "delivery_1080p",
            "output_format": requested_output_format,
            "selected_output_profile": output_plan["selected_output_profile"],
            "selected_output_format": output_plan["selected_output_format"],
            "final_output_type": None,
            "sourceWidth": source_width,
            "sourceHeight": source_height,
            "input_width": source_width,
            "input_height": source_height,
            "output_width": output_plan["output_width"],
            "output_height": output_plan["output_height"],
            "target_width": output_plan["target_width"],
            "target_height": output_plan["target_height"],
            "aspect_ratio": output_plan["aspect_ratio"],
            "aspect_preset": output_plan["aspect_preset"],
            "scale_policy": output_plan["scale_policy"],
            "image_type": output_plan["image_type"],
            "image_type_features": output_plan["image_type_features"],
            "resolution_gate_pass": output_plan["resolution_gate_pass"],
            "visual_quality_gate_pass": None,
            "quality_1080p_pass": None,
            "quality_1080p_level": None,
            "visual_quality_note": None,
            "input_size_bytes": input_size_bytes,
            "main_size_bytes": None,
            "optimized_size_bytes": None,
            "final_size_bytes": None,
            "file_size_ratio": None,
            "compression_saved_ratio": None,
            "quality_preserved": None,
            "compression_note": None,
            "input_hash": input_hash,
            "output_changed": None,
            "hash_equal": None,
            "pixel_diff_score": None,
            "has_alpha": output_plan["has_alpha"],
            "has_real_alpha": output_plan["has_real_alpha"],
            "alpha_used": output_plan["alpha_used"],
            "selected_format_reason": output_plan["selected_format_reason"],
            "debug_keep_intermediate": keep_intermediate,
            "debug_timing": task["debug_timing"],
            "width": output_plan["output_width"],
            "height": output_plan["output_height"],
            "scale": scale_value,
            "format": requested_output_format,
            "qualityFlag": "任务已登记，等待 SSE 管线执行。",
            "streamEndpoint": f"/api/v1/tasks/{DEFAULT_TASK_ID}/stream",
            "debug_quality": {
                "input_width": source_width,
                "input_height": source_height,
                "output_width": output_plan["output_width"],
                "output_height": output_plan["output_height"],
                "target_width": output_plan["target_width"],
                "target_height": output_plan["target_height"],
                "aspect_ratio": output_plan["aspect_ratio"],
                "aspect_preset": output_plan["aspect_preset"],
                "scale_policy": output_plan["scale_policy"],
                "image_type": output_plan["image_type"],
                "image_type_features": output_plan["image_type_features"],
                "resolution_gate_pass": output_plan["resolution_gate_pass"],
                "visual_quality_gate_pass": None,
                "quality_1080p_pass": None,
                "quality_1080p_level": None,
                "has_alpha": output_plan["has_alpha"],
                "has_real_alpha": output_plan["has_real_alpha"],
                "alpha_used": output_plan["alpha_used"],
                "selected_format_reason": output_plan["selected_format_reason"],
            },
            "output_contract": {
                "enhancedUrl": public_file_url("outputs", expected_output_path.name),
                "main_output_url": public_file_url("work", output_plan["paths"]["main"].name) if keep_intermediate else None,
                "optimized_output_url": public_file_url("work", output_plan["paths"]["optimized"].name) if keep_intermediate else None,
                "final_output_url": public_file_url("outputs", expected_output_path.name),
                "final_output_exists": expected_output_path.exists(),
                "enhanced_equals_final": True,
                "formal_output_dir": str(output_formal_dir),
                "work_output_dir": str(output_work_dir),
                "debug_output_dir": str(output_debug_dir),
                "test_output_dir": str(output_test_dir),
                "official_images_only_final": True,
            },
        }
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "message": "图片上传完成，已登记为异步修复任务。",
            "filename": upload_name,
            "url": data["originalUrl"],
            "data": data,
        }

    return app


def build_web_app(runtime_host: str = SERVER_HOST, runtime_port: int = SERVER_PORT):
    runtime_id = begin_runtime(product_version=APP_VERSION)
    build_identity = read_frontend_build_identity(PROJECT_ROOT, APP_VERSION)
    configure_runtime_identity(
        product_version=APP_VERSION,
        build_id=build_identity["build_id"] or "unavailable",
    )
    application_started_monotonic = time.monotonic()
    application_started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    log_runtime_event(
        "APPLICATION_STARTING",
        stage="application_startup",
        result="starting",
        product_version=APP_VERSION,
        build_id=build_identity["build_id"] or "unavailable",
        runtime_id=runtime_id,
        impact="backend_initializing",
        action="resolve_settings_and_formal_directory",
    )
    try:
        from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
    except ImportError as exc:
        raise RuntimeError("缺少 FastAPI 服务依赖，请先安装 requirements.txt。") from exc

    from backend.v036_output_core import build_output_plan, sha256_file
    from backend.image_compression_api import register_image_compression_routes
    from engine.diagnostics.feedback_bundle import generate_feedback_bundle
    from engine.diagnostics.feedback_context import (
        RECENT_FEATURE_COVERAGE,
        build_feedback_context,
        feedback_context_preview,
    )
    from engine.pipeline import process_v046_delivery

    migration_settings_snapshot = _read_settings_file_safely()
    migration_settings_valid = bool(
        SETTINGS_PATH.exists()
        and migration_settings_snapshot
        and all(key in migration_settings_snapshot for key in default_settings())
    )
    settings_load_status: dict = {}
    settings_data = load_settings(settings_load_status)
    initial_user_dirs = resolve_hdde_user_dirs(settings_data)
    migration_result: dict = {"status": "SKIPPED", "second_run": "NOT_RUN"}
    if migration_settings_valid and initial_user_dirs["directory_ready"]:
        try:
            saved_root = Path(str(migration_settings_snapshot.get("last_app_data_root") or "")).expanduser().resolve()
            active_root = Path(initial_user_dirs["app_data_root"]).resolve()
        except Exception:
            saved_root = None
            active_root = None
        if saved_root is not None and active_root is not None and saved_root == active_root:
            migration_result = execute_migration_cycle(
                active_root,
                settings_data,
                settings_path=SETTINGS_PATH,
                settings_writer=write_settings_if_changed,
                project_root=PROJECT_ROOT,
                write_report=True,
            )
            if migration_result["status"] == "BLOCKED":
                first_failure = ((migration_result.get("first") or {}).get("failures") or [{}])[0]
                initial_user_dirs = {
                    **initial_user_dirs,
                    "directory_ready": False,
                    "directory_error_code": "APP_DATA_MIGRATION_BLOCKED",
                    "directory_message": "正式目录迁移失败，依赖目录的功能已阻断。",
                    "failed_path": str(first_failure.get("path") or active_root),
                    "failed_stage": "app_data_migration",
                    "failure_reason": str(first_failure.get("reason") or "正式目录迁移未完成。"),
                }
            elif migration_result["status"] == "APPLIED":
                initial_user_dirs = resolve_hdde_user_dirs(settings_data)
    if initial_user_dirs["directory_ready"]:
        logging_initialization = initialize_file_logging(initial_user_dirs["app_data_root"])
        log_runtime_event(
            "DIRECTORY_VALIDATION_SUCCEEDED",
            stage="required_directory_validation",
            result="success",
            path=initial_user_dirs["app_data_root"],
            impact="directory_dependent_operations_available",
            action="none",
        )
    else:
        logging_initialization = {
            "initialized": False,
            "degraded": True,
            "path": None,
            "reason": "formal_directory_not_ready",
        }
        log_runtime_event(
            "DIRECTORY_VALIDATION_FAILED",
            level=logging.ERROR,
            stage=initial_user_dirs.get("failed_stage") or "required_directory_validation",
            result="failed",
            error_category=ENVIRONMENT_ERROR,
            path=initial_user_dirs.get("failed_path") or initial_user_dirs["app_data_root"],
            reason=initial_user_dirs.get("failure_reason") or initial_user_dirs.get("directory_message"),
            impact="image_processing_blocked",
            action="check_directory_permissions_or_select_formal_directory",
        )
    input_dir = initial_user_dirs["normal_input_dir"]
    default_output_root = initial_user_dirs["normal_output_dir"]
    output_formal_dir = default_output_root

    task_registry: dict[str, dict] = {}
    upload_file_index: dict[str, Path] = {}
    output_file_index: dict[str, Path] = {}
    background_tasks: dict[str, asyncio.Task] = {}
    task_start_times: dict[str, float] = {}
    task_terminal_events: set[str] = set()
    latest_task_id = {"value": None}
    feedback_context_snapshots: dict[str, dict] = {}

    app = FastAPI(title=f"VisualMasterPro / Yingjie {APP_VERSION} API", version=PRODUCT_VERSION)
    app.state.runtime_task_start_times = task_start_times
    app.state.runtime_task_terminal_events = task_terminal_events
    app.state.app_data_migration_result = migration_result
    app.state.settings_load_status = settings_load_status
    app.state.frontend_build_identity = build_identity
    app.state.runtime_id = runtime_id
    app.state.application_started_at = application_started_at
    app.state.feedback_context_snapshots = feedback_context_snapshots
    app.state.task_registry = task_registry
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _finish_image_task(
        task_id: str,
        *,
        event: str,
        started_at: float | None,
        stage: str,
        result: str,
        route: str,
        path: str | Path | None,
        reason: str,
        impact: str,
        action: str,
        error_category: str = "",
        phase_event: str = "",
        purpose: str = "1080P_DELIVERY",
        level: int = logging.INFO,
        exception: BaseException | None = None,
    ) -> float | None:
        if task_id in task_terminal_events:
            return None
        timing_anchor = started_at if started_at is not None else task_start_times.get(task_id, time.monotonic())
        duration_ms = round((time.monotonic() - timing_anchor) * 1000, 3)
        task_terminal_events.add(task_id)
        common_fields = {
            "stage": stage,
            "result": result,
            "error_category": error_category,
            "task_id": task_id,
            "purpose": purpose,
            "route": route,
            "duration_ms": duration_ms,
            "path": path or "",
            "reason": reason,
            "impact": impact,
            "action": action,
        }
        if exception is not None:
            diagnostics = build_exception_diagnostics(
                exception,
                error_category=error_category or PRODUCT_ERROR,
                error_stage=stage,
            )
            common_fields.update(diagnostics)
            task_record = task_registry.get(task_id)
            if isinstance(task_record, dict):
                task_record["error_context"] = dict(diagnostics)
        try:
            if phase_event:
                log_runtime_event(phase_event, level=level, **common_fields)
            log_runtime_event(event, level=level, **common_fields)
            task_record = task_registry.get(task_id) or {}
            log_runtime_event(
                "PROCESS_SUCCEEDED" if result == "success" else "PROCESS_FAILED",
                level=level,
                feature_key=task_record.get("feature_key") or "",
                result_id=task_record.get("result_id") or "",
                status="completed" if result == "success" else ("failed" if result == "failed" else result),
                **common_fields,
            )
        finally:
            task_start_times.pop(task_id, None)
        return duration_ms

    def finish_task_success(task_id: str, *, started_at: float | None, **fields) -> float | None:
        return _finish_image_task(
            task_id,
            event="IMAGE_TASK_SUCCEEDED",
            started_at=started_at,
            **fields,
        )

    def finish_task_failure(task_id: str, *, started_at: float | None, **fields) -> float | None:
        return _finish_image_task(
            task_id,
            event="IMAGE_TASK_FAILED",
            started_at=started_at,
            **fields,
        )

    def register_unified_image_result(task: dict, final_path: Path) -> str:
        result_id = str(task.get("result_id") or f"image_result_{uuid.uuid4().hex[:16]}")
        task_id = str(task.get("task_id") or "")
        feature_key = str(task.get("feature_key") or "")
        source_path = Path(task["input_path"]).resolve()
        resolved_result = final_path.resolve()
        task_result = task.get("task_result") if isinstance(task.get("task_result"), dict) else {}
        task_result.update(
            {
                "result_id": result_id,
                "task_id": task_id,
                "feature_key": feature_key,
                "source": str(source_path),
                "source_path": str(source_path),
                "result_file": str(resolved_result),
                "output_path": str(resolved_result),
                "status": "completed",
            }
        )
        task.update(
            {
                "result_id": result_id,
                "source": str(source_path),
                "source_path": source_path,
                "result_file": str(resolved_result),
                "task_result": task_result,
            }
        )
        log_runtime_event(
            "RESULT_REGISTERED",
            stage="result_registry",
            result="success",
            feature_key=feature_key,
            task_id=task_id,
            result_id=result_id,
            status="completed",
            impact="formal_result_available",
        )
        return result_id

    def save_settings(next_settings: dict) -> None:
        write_settings_if_changed(next_settings)

    def current_user_dirs() -> dict:
        return resolve_hdde_user_dirs(settings_data)

    def require_directory_ready() -> dict:
        user_dirs = current_user_dirs()
        if user_dirs["directory_ready"]:
            return user_dirs
        raise HTTPException(
            status_code=503,
            detail={
                "code": user_dirs["directory_error_code"] or "FORMAL_DIRECTORY_NOT_READY",
                "message": user_dirs["directory_message"] or "正式目录未就绪，请前往系统设置重新选择目录。",
                "directory_ready": False,
                "failed_path": user_dirs.get("failed_path") or "",
                "failed_stage": user_dirs.get("failed_stage") or "",
                "failure_reason": user_dirs.get("failure_reason") or "",
                "cleanup_failures": user_dirs.get("cleanup_failures") or [],
            },
        )

    def normalize_output_dir_text(value: str | None) -> str:
        return str(value or "").strip().strip('"').strip()

    def validate_output_dir_value(output_dir_value: str | None, allow_create: bool | None = None, source_hint: str | None = None) -> dict:
        raw = normalize_output_dir_text(output_dir_value)
        allow_create = bool(settings_data.get("create_output_dir_if_missing", True)) if allow_create is None else bool(allow_create)
        if not raw:
            return {
                "valid": False,
                "exists": False,
                "created": False,
                "writable": False,
                "normalized_path": "",
                "source": source_hint or "empty",
                "message": "输出目录为空。",
            }
        if "\x00" in raw:
            return {
                "valid": False,
                "exists": False,
                "created": False,
                "writable": False,
                "normalized_path": "",
                "source": source_hint or "invalid",
                "message": "输出路径非法：包含不可见控制字符。",
            }
        try:
            target = Path(raw).expanduser()
            if not target.is_absolute():
                target = (PROJECT_ROOT / target).resolve()
            else:
                target = target.resolve()
        except Exception as exc:
            return {
                "valid": False,
                "exists": False,
                "created": False,
                "writable": False,
                "normalized_path": "",
                "source": source_hint or "invalid",
                "message": f"输出路径非法：{exc}",
            }
        existed = target.exists()
        created = False
        if existed and not target.is_dir():
            return {
                "valid": False,
                "exists": True,
                "created": False,
                "writable": False,
                "normalized_path": str(target),
                "source": source_hint or "invalid",
                "message": "输出路径已存在，但不是目录。",
                "error_category": ENVIRONMENT_ERROR,
                "failed_stage": "output_directory_create",
                "phase_event": "OUTPUT_DIRECTORY_CREATE_FAILED",
                "action": "check_output_directory_permissions",
            }
        if not existed:
            if not allow_create:
                return {
                    "valid": False,
                    "exists": False,
                    "created": False,
                    "writable": False,
                    "normalized_path": str(target),
                    "source": source_hint or "invalid",
                    "message": "输出目录不存在，且当前配置不允许自动创建。",
                }
            try:
                target.mkdir(parents=True, exist_ok=True)
                created = True
            except Exception as exc:
                return {
                    "valid": False,
                    "exists": False,
                    "created": False,
                    "writable": False,
                    "normalized_path": str(target),
                    "source": source_hint or "invalid",
                    "message": f"输出目录不存在且无法创建：{exc}",
                    "error_category": ENVIRONMENT_ERROR,
                    "failed_stage": "output_directory_create",
                    "phase_event": "OUTPUT_DIRECTORY_CREATE_FAILED",
                    "action": "check_output_directory_permissions",
                }
        probe = target / f".vmp_write_test_{uuid.uuid4().hex}.tmp"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except Exception as exc:
            try:
                probe.unlink(missing_ok=True)
            except Exception:
                pass
            return {
                "valid": False,
                "exists": target.exists(),
                "created": created,
                "writable": False,
                "normalized_path": str(target),
                "source": source_hint or "invalid",
                "message": f"输出目录不可写：{exc}",
                "error_category": ENVIRONMENT_ERROR,
                "failed_stage": "output_directory_writable_check",
                "phase_event": "OUTPUT_DIRECTORY_CREATE_FAILED",
                "action": "check_output_directory_permissions",
            }
        return {
            "valid": True,
            "exists": target.exists(),
            "created": created,
            "writable": True,
            "normalized_path": str(target),
            "source": source_hint or "default",
            "message": "输出目录可用",
        }

    def resolve_output_dir(output_dir_value: str | None, *, persist_custom_selection: bool = False) -> tuple[Path, dict]:
        user_dirs = require_directory_ready()
        requested = normalize_output_dir_text(output_dir_value)
        allow_custom = bool(settings_data.get("allow_custom_output_dir", True))
        candidates: list[tuple[str, str]] = []
        if requested:
            if not allow_custom:
                raise HTTPException(status_code=400, detail="当前配置不允许使用自定义输出目录。")
            candidates.append(("request", requested))
        if not requested:
            candidates.append(("formal_default", str(user_dirs["normal_output_dir"])))
        errors: list[str] = []
        for source, value in candidates:
            checked = validate_output_dir_value(value, source_hint=source)
            if checked["valid"]:
                target = Path(checked["normalized_path"])
                meta = {
                    "output_dir_source": source,
                    "used_custom_output_dir": source == "request",
                    "output_dir_created": bool(checked.get("created")),
                    "output_dir_message": checked.get("message") or "",
                }
                if source == "request" and persist_custom_selection:
                    next_settings = {**settings_data, "last_output_dir": str(target)}
                    save_settings(next_settings)
                    settings_data.clear()
                    settings_data.update(next_settings)
                return target, meta
            errors.append(f"{source}: {checked['message']}")
            if source == "request":
                error = HTTPException(status_code=400, detail=checked["message"])
                error.hdde_error_category = checked.get("error_category") or USER_ACTION_REQUIRED
                error.hdde_failed_stage = checked.get("failed_stage") or "output_directory_validation"
                error.hdde_phase_event = checked.get("phase_event") or ""
                error.hdde_action = checked.get("action") or "select_valid_output_directory"
                error.hdde_failed_path = checked.get("normalized_path") or value
                raise error
        error = HTTPException(status_code=400, detail="输出目录不可用：" + "；".join(errors))
        error.hdde_error_category = checked.get("error_category") or USER_ACTION_REQUIRED
        error.hdde_failed_stage = checked.get("failed_stage") or "output_directory_validation"
        error.hdde_phase_event = checked.get("phase_event") or ""
        error.hdde_action = checked.get("action") or "select_valid_output_directory"
        error.hdde_failed_path = checked.get("normalized_path") or value
        raise error

    def resolve_output_dir_for_open(output_dir_value: str | None) -> dict:
        checked = validate_output_dir_value(output_dir_value, allow_create=False, source_hint="request")
        return checked

    def compression_output_settings_provider() -> dict[str, str]:
        return {
            "built_in_default_root": str(DEFAULT_IMAGE_COMPRESSION_OUTPUT_ROOT),
            "saved_default_root": str(settings_data.get("image_compression_default_output_root") or DEFAULT_IMAGE_COMPRESSION_OUTPUT_ROOT),
        }

    def save_compression_default_output_root(value: str) -> None:
        next_settings = {**settings_data, "image_compression_default_output_root": value}
        save_settings(next_settings)
        settings_data.clear()
        settings_data.update(next_settings)

    def feedback_runtime_provider() -> dict:
        formal_root = read_only_formal_root_status(initial_user_dirs)
        runtime_ready = bool(settings_load_status["status"] == "loaded" and formal_root["directory_ready"])
        log_path = Path(initial_user_dirs["runtime_log_dir"]) / "hdde.log"
        error_code = formal_root["error_code"] or ("SETTINGS_NOT_LOADED" if settings_load_status["status"] != "loaded" else "")
        return {
            "app_version": APP_VERSION,
            "product_version": APP_VERSION,
            "build_id": build_identity["build_id"] or "unavailable",
            "runtime_id": runtime_id,
            "runtime_status": "ready" if runtime_ready else "degraded",
            "backend_health": "healthy" if runtime_ready else "degraded",
            "backend_connection_status": "connected",
            "frontend_connection_status": "not_available",
            "settings_status": settings_load_status["status"],
            "formal_root_status": formal_root["status"],
            "host": runtime_host,
            "port": runtime_port,
            "runtime_log_reference": "诊断/日志/hdde.log" if log_path.is_file() else "",
            "runtime_log_available": log_path.is_file(),
            "error_type": "CONFIGURATION_ERROR" if error_code else "",
            "error_code": error_code,
            "error_stage": formal_root["failed_stage"],
            "error_summary": (formal_root["reason"] or settings_load_status["reason"]) if error_code else "",
        }

    register_image_compression_routes(
        app,
        user_dirs_provider=require_directory_ready,
        output_settings_provider=compression_output_settings_provider,
        color_output_settings_provider=lambda: {
            "built_in_default_root": str(Path(settings_data["app_data_root"]) / "输出"),
            "saved_default_root": str(Path(settings_data["app_data_root"]) / "输出"),
        },
        output_default_saver=save_compression_default_output_root,
        output_dir_validator=lambda value: validate_output_dir_value(value, source_hint="image_compression"),
        shared_task_registry=task_registry,
        output_center_user_dirs_provider=current_user_dirs,
        feedback_runtime_provider=feedback_runtime_provider,
        runtime_event_logger=log_runtime_event,
    )

    from backend.local_retouch_api import register_local_retouch_routes

    register_local_retouch_routes(
        app,
        user_dirs_provider=require_directory_ready,
        shared_task_registry=task_registry,
        runtime_event_logger=log_runtime_event,
    )

    from backend.image_diagnosis_api import register_image_diagnosis_routes

    register_image_diagnosis_routes(
        app,
        user_dirs_provider=require_directory_ready,
        shared_task_registry=task_registry,
        runtime_event_logger=log_runtime_event,
    )

    def update_task_result_output_meta(task_result: dict, task: dict, final_path: Path) -> dict:
        meta = task.get("output_dir_meta") or {}
        task_result.update(
            {
                "input_dir": str(Path(task["input_path"]).parent),
                "input_path": str(task["input_path"]),
                "input_filename": Path(task["input_path"]).name,
                "output_dir": str(final_path.parent),
                "output_directory": str(final_path.parent),
                "output_directory_source": meta.get("output_dir_source") or "default",
                "output_path": str(final_path),
                "output_filename": final_path.name,
                "final_output_path": str(final_path),
                "final_output_filename": final_path.name,
                "output_size": final_path.stat().st_size if final_path.exists() else task_result.get("output_size", 0),
                "final_output_url": public_file_url("outputs", final_path.name),
                "preview_output_url": public_file_url("outputs", final_path.name),
                "used_custom_output_dir": bool(meta.get("used_custom_output_dir")),
                "output_dir_source": meta.get("output_dir_source") or "default",
                "output_dir_created": bool(meta.get("output_dir_created")),
                "output_path_exists": final_path.exists(),
            }
        )
        return task_result

    def resolve_output_dir_legacy(output_dir_value: str | None) -> Path:
        target, _meta = resolve_output_dir(output_dir_value)
        return target

    def _legacy_unused() -> None:
        return None

    def _old_resolve_output_dir(output_dir_value: str | None) -> Path:
        raw = (output_dir_value or "").strip()
        target = Path(raw) if raw else output_formal_dir
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"输出目录无法创建：{target}；原因：{exc}") from exc
        return target

    def unique_input_path(name: str) -> Path:
        active_input_dir = require_directory_ready()["normal_input_dir"]
        path = active_input_dir / name
        if not path.exists():
            return path
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = active_input_dir / f"{path.stem}_{stamp}{path.suffix}"
        counter = 1
        while candidate.exists():
            candidate = active_input_dir / f"{path.stem}_{stamp}_{counter}{path.suffix}"
            counter += 1
        return candidate

    def safe_mode(value: str | None) -> str:
        mode_value = str(value or "fidelity").strip().lower()
        return mode_value if mode_value in {"fidelity", "texture", "text_safe", FOUR_K_V1_MODE} else "fidelity"

    def empty_task_report() -> dict:
        return {
            "clarity_score": 0,
            "text_clarity_score": 0,
            "edge_quality_score": 0,
            "structure_score": 0,
            "color_fidelity_score": 0,
            "texture_score": 0,
            "pseudo_hd_risk": "medium",
            "artifact_risk": "medium",
            "delivery_score": 0,
            "warnings": [],
        }

    def public_task(task: dict) -> dict:
        result = dict(task)
        result.pop("formal_root", None)
        formal_root = Path(current_user_dirs()["app_data_root"])
        for key in ("input_path", "source_path", "result_file", "output_root", "expected_output_path", "output_path"):
            if key in result and result[key] is not None:
                result[key] = str(resolve_migrated_formal_output_path(result[key], formal_root))
        result["taskId"] = result.get("task_id")
        result["status"] = result.get("task_status") or result.get("status")
        result["task_status"] = result["status"]
        result["task_progress"] = result.get("task_progress", result.get("progress", 0))
        result["streamEndpoint"] = f"/api/v1/tasks/{result.get('task_id')}/stream"
        result["originalUrl"] = result.get("source_preview_url") or public_file_url(
            "uploads",
            Path(result.get("input_path") or result.get("source_path") or "").name,
        )
        if result.get("task_result"):
            filename = result["task_result"].get("output_filename")
            if filename:
                result["enhancedUrl"] = public_file_url("outputs", filename)
                result["final_output_url"] = result["enhancedUrl"]
        else:
            expected = result.get("expected_output_path")
            if expected:
                result["enhancedUrl"] = public_file_url("outputs", Path(expected).name)
                result["final_output_url"] = result["enhancedUrl"]
        if result.get("result_id") and result.get("task_id") and result.get("result_file"):
            result["final_output_url"] = f"/api/v1/tasks/{urllib.parse.quote(str(result['task_id']), safe='')}/result-file"
        result.setdefault("main_output_url", None)
        result.setdefault("optimized_output_url", None)
        result.setdefault("final_output_exists", False)
        return result

    def resolve_public_file(kind: str, filename: str) -> Path:
        if kind == "uploads":
            indexed = upload_file_index.get(Path(filename).name)
            if indexed and indexed.exists():
                return indexed
            active_input_dir = current_user_dirs()["normal_input_dir"]
            root = active_input_dir.resolve()
            target = (active_input_dir / filename).resolve()
        elif kind == "outputs":
            indexed = output_file_index.get(Path(filename).name)
            if indexed and indexed.exists():
                return indexed
            candidate_roots = [current_user_dirs()["normal_output_dir"]]
            for candidate_root in candidate_roots:
                root = candidate_root.resolve()
                target = (candidate_root / filename).resolve()
                if root in target.parents or target == root:
                    if target.exists() and target.is_file():
                        output_file_index[Path(filename).name] = target
                        return target
            active_output_dir = current_user_dirs()["normal_output_dir"]
            root = active_output_dir.resolve()
            target = (active_output_dir / filename).resolve()
        elif kind == "safe-beta":
            user_dirs = current_user_dirs()
            candidate_roots = [
                user_dirs["safe_beta_output_dir"],
                user_dirs["safe_beta_input_root"],
                user_dirs["safe_beta_feedback_dir"],
                user_dirs["feedback_dir"],
                user_dirs["beta_upload_dir"],
            ]
            raw_filename = urllib.parse.unquote(filename)
            if re.match(r"^/[a-zA-Z]:[\\/]", raw_filename):
                raw_filename = raw_filename[1:]
            raw_target = Path(raw_filename).expanduser()
            target = raw_target.resolve() if raw_target.is_absolute() else (PROJECT_ROOT / raw_target).resolve()
            for candidate_root in candidate_roots:
                root = candidate_root.resolve()
                try:
                    common_path = os.path.commonpath([os.path.normcase(str(root)), os.path.normcase(str(target))])
                except ValueError:
                    common_path = ""
                if common_path == os.path.normcase(str(root)) and target.exists() and target.is_file():
                    return target
            root = candidate_roots[0].resolve()
        else:
            raise HTTPException(status_code=404, detail="未知文件类型。")
        if root not in target.parents and target != root:
            raise HTTPException(status_code=403, detail="非法文件路径。")
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="文件不存在。")
        return target

    async def run_task_background(task_id: str) -> None:
        task = task_registry.get(task_id)
        if not task:
            return
        if task.get("task_status") in {"processing", "completed", "failed"}:
            return
        await asyncio.to_thread(run_image_pipeline, task)

    def ensure_task_started(task: dict) -> None:
        task_id = task.get("task_id")
        if not task_id:
            return
        if task.get("task_status") in {"processing", "completed", "failed"}:
            return
        existing = background_tasks.get(task_id)
        if existing and not existing.done():
            return
        task["execution_started"] = True
        background_tasks[task_id] = asyncio.create_task(run_task_background(task_id))

    def run_4k_v1_pipeline(task: dict) -> dict:
        task_id = str(task.get("task_id") or "")
        task["execution_started"] = True
        task["execution_state"] = "processing"
        task["task_status"] = "processing"
        task["status"] = "processing"
        task["task_progress"] = max(int(task.get("task_progress") or 0), 5)
        log_runtime_event(
            "PROCESS_STARTED",
            stage="engine_adapter",
            result="started",
            feature_key=task.get("feature_key") or ENHANCEMENT_4K_FEATURE_KEY,
            task_id=task_id,
            status="processing",
            impact="image_processing_running",
        )

        def record_stage(stage: str, progress: int, message: str) -> None:
            task["processing_stage"] = stage
            task["task_progress"] = max(0, min(100, int(progress)))
            task.setdefault("stage_events", []).append(
                {
                    "processing_stage": stage,
                    "task_progress": task["task_progress"],
                    "message": message,
                }
            )

        try:
            result = process_4k_v1_image(
                task["input_path"],
                task["formal_root"],
                output_path=task.get("expected_output_path"),
                stage_callback=record_stage,
            )
            task_result = dict(result.get("task_result") or {})
            task_report = dict(result.get("task_report") or {})
            final_path_value = result.get("final_output_path") or ""
            final_path = Path(final_path_value) if final_path_value else None
            if final_path:
                output_file_index[final_path.name] = final_path
                final_url = public_file_url("outputs", final_path.name)
                task_result["final_output_url"] = final_url
                task_result["preview_output_url"] = final_url
            else:
                final_url = ""

            task.update(
                {
                    "task_status": "completed",
                    "status": "completed",
                    "execution_state": "completed",
                    "task_progress": 100,
                    "processing_stage": "completed",
                    "completed_at": datetime.now().isoformat(timespec="seconds"),
                    "output_path": final_path or "",
                    "enhancedUrl": final_url,
                    "final_output_url": final_url,
                    "preview_output_url": final_url,
                    "final_output_exists": bool(final_path and final_path.is_file()),
                    "task_result": task_result,
                    "task_report": task_report,
                    "quality_conclusion": result.get("quality_conclusion"),
                    "source_hash_unchanged": result.get("source_hash_unchanged"),
                    "error_code": "",
                    "error_message": "",
                    "output_directory": str(final_path.parent) if final_path else "",
                    "final_output_path": str(final_path) if final_path else "",
                    "final_output_filename": final_path.name if final_path else "",
                    "input_width": task_result.get("input_width"),
                    "input_height": task_result.get("input_height"),
                    "output_width": task_result.get("output_width"),
                    "output_height": task_result.get("output_height"),
                    "output_format": task_result.get("output_format") or "PNG",
                    "resize_policy": task_result.get("resize_policy"),
                }
            )
            if final_path and final_path.is_file():
                register_unified_image_result(task, final_path)
            finish_task_success(
                task_id,
                started_at=task.get("started_at_monotonic"),
                stage="output_verify",
                result="success",
                route=FOUR_K_V1_ROUTE,
                path=final_path or task.get("input_path"),
                reason=result.get("quality_conclusion") or "SIZE_ADAPTATION_COMPLETED",
                impact="output_available" if final_path else "no_processing_needed",
                action="none",
                purpose="4K_SIZE_ADAPTATION",
            )
        except Exception as exc:
            error_code = str(getattr(exc, "code", "4K_PROCESSING_FAILED"))
            failed_stage = str(getattr(exc, "stage", getattr(exc, "hdde_failed_stage", "image_processing")))
            record_stage(failed_stage, 100, f"4K高清画质增强未完成：{exc}")
            finish_task_failure(
                task_id,
                started_at=task.get("started_at_monotonic"),
                level=logging.ERROR,
                stage=failed_stage,
                result="failed",
                error_category=ENVIRONMENT_ERROR if isinstance(exc, OSError) else PRODUCT_ERROR,
                route=FOUR_K_V1_ROUTE,
                path=task.get("expected_output_path") or task.get("input_path"),
                reason=str(exc),
                impact="output_unavailable",
                action="check_formal_directory_and_retry",
                purpose="4K_SIZE_ADAPTATION",
                exception=exc,
            )
            task.update(
                {
                    "task_status": "failed",
                    "status": "failed",
                    "execution_state": "failed",
                    "task_progress": 100,
                    "processing_stage": failed_stage,
                    "error_code": error_code,
                    "error_message": str(exc),
                    "task_error": str(exc),
                    "quality_conclusion": "FAILED",
                    "task_report": {
                        "mode": FOUR_K_V1_MODE,
                        "route": FOUR_K_V1_ROUTE,
                        "quality_capability_boundary": FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY,
                        "quality_conclusion": "FAILED",
                        "warnings": [str(exc)],
                    },
                    "completed_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
        return task

    def run_image_pipeline(task: dict) -> dict:
        if task.get("execution_state") in {"processing", "completed", "failed"}:
            return task
        if task.get("mode") == FOUR_K_V1_MODE:
            return run_4k_v1_pipeline(task)
        task["execution_started"] = True
        task["execution_state"] = "processing"
        task["task_status"] = "processing"
        task["status"] = "processing"
        task["task_progress"] = max(int(task.get("task_progress") or 0), 10)
        task_id = str(task.get("task_id") or "")
        log_runtime_event(
            "PROCESS_STARTED",
            stage="engine_adapter",
            result="started",
            feature_key=task.get("feature_key") or ENHANCEMENT_1080P_FEATURE_KEY,
            task_id=task_id,
            status="processing",
            impact="image_processing_running",
        )
        current_stage = "image_processing"
        try:
            result = process_v046_delivery(
                {
                    "input_path": Path(task["input_path"]),
                    "output_root": Path(task["output_root"]),
                    "mode": task["mode"],
                    "output_profile": task.get("output_profile") or "delivery_1080p",
                    "output_format": task["output_format"],
                    "debug_timing": task.get("debug_timing"),
                    "debug_keep_intermediate": False,
                    "color_stability_enabled": task.get("color_stability_enabled", True),
                    "color_correction_enabled": task.get("color_correction_enabled", False),
                }
            )
            final_path = Path(result["final_output_path"])
            if not final_path.is_file():
                current_stage = "output_finalize"
                raise RuntimeError(f"处理管线未生成预期成品文件：{final_path}")
            current_stage = "output_finalize"
            output_file_index[final_path.name] = final_path
            task_result = update_task_result_output_meta(dict(result.get("task_result") or {}), task, final_path)
            task_report = dict(result.get("task_report") or empty_task_report())
            task.update(
                {
                    "task_status": "completed",
                    "status": "completed",
                    "execution_state": "completed",
                    "task_progress": 100,
                    "completed_at": datetime.now().isoformat(timespec="seconds"),
                    "output_path": final_path,
                    "enhancedUrl": public_file_url("outputs", final_path.name),
                    "final_output_url": public_file_url("outputs", final_path.name),
                    "main_output_url": None,
                    "optimized_output_url": None,
                    "final_output_exists": final_path.exists(),
                    "image_type": result.get("image_type") or task.get("image_type") or "unknown",
                    "degradation_type": result.get("degradation_type") or "unknown",
                    "task_result": task_result,
                    "task_report": task_report,
                    "error_message": "",
                    "output_directory": str(final_path.parent),
                    "output_directory_source": (task.get("output_dir_meta") or {}).get("output_dir_source") or "default",
                    "final_output_path": str(final_path),
                    "final_output_filename": final_path.name,
                    "final_delivery_status": result.get("final_delivery_status") or (result.get("debug_quality") or {}).get("final_delivery_status"),
                    "final_delivery_reason": result.get("final_delivery_reason") or (result.get("debug_quality") or {}).get("final_delivery_reason"),
                    "final_delivery_risk_level": result.get("final_delivery_risk_level") or (result.get("debug_quality") or {}).get("final_delivery_risk_level"),
                    "final_delivery_recommended_usage": result.get("final_delivery_recommended_usage") or (result.get("debug_quality") or {}).get("final_delivery_recommended_usage"),
                    "feedback_bundle_status": "",
                    "feedback_bundle_path": "",
                    "feedback_bundle_size": 0,
                    "feedback_bundle_redacted": True,
                    "feedback_bundle_error": "",
                    "input_width": result.get("input_width"),
                    "input_height": result.get("input_height"),
                    "output_width": result.get("output_width"),
                    "output_height": result.get("output_height"),
                    "resize_policy": task_result.get("resize_policy") or result.get("resize_policy"),
                    "was_upscaled": task_result.get("was_upscaled"),
                    "was_downscaled": task_result.get("was_downscaled"),
                    "input_size_bytes": result.get("input_size_bytes"),
                    "output_size": task_result.get("output_size"),
                    "output_format": task_result.get("output_format") or task.get("output_format"),
                    "output_changed": result.get("output_changed"),
                    "hash_equal": result.get("hash_equal"),
                    "pixel_diff_score": result.get("pixel_diff_score"),
                    "debug_timing": result.get("debug_timing"),
                    "debug_quality": result.get("debug_quality"),
                }
            )
            register_unified_image_result(task, final_path)
            finish_task_success(
                task_id,
                started_at=task.get("started_at_monotonic"),
                stage="image_processing",
                result="success",
                route=task.get("mode"),
                path=final_path,
                reason="processing_completed",
                impact="output_available",
                action="none",
            )
        except Exception as exc:
            failed_stage = getattr(exc, "hdde_failed_stage", current_stage)
            error_category = getattr(
                exc,
                "hdde_error_category",
                ENVIRONMENT_ERROR if isinstance(exc, OSError) else PRODUCT_ERROR,
            )
            phase_event = (
                getattr(exc, "hdde_phase_event", "")
                if failed_stage == "output_file_write"
                else ""
            )
            action = (
                "check_output_path_permissions_disk_space_or_file_occupancy"
                if failed_stage == "output_file_write"
                else ("check_runtime_log_and_retry" if error_category == PRODUCT_ERROR else "check_processing_environment")
            )
            finish_task_failure(
                task_id,
                started_at=task.get("started_at_monotonic"),
                phase_event=phase_event,
                level=logging.ERROR,
                stage=failed_stage,
                result="failed",
                error_category=error_category,
                route=task.get("mode"),
                path=task.get("expected_output_path") or task.get("output_root"),
                reason=str(exc),
                impact="output_unavailable",
                action=action,
                exception=exc,
            )
            task.update(
                {
                    "task_status": "failed",
                    "status": "failed",
                    "execution_state": "failed",
                    "task_progress": 100,
                    "error_message": str(exc),
                    "task_error": str(exc),
                    "task_report": task.get("task_report") or empty_task_report(),
                    "completed_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
        return task

    async def stream_task_events(task_id: str, delay: float = 0.25):
        real_task_id = latest_task_id["value"] if task_id == DEFAULT_TASK_ID else task_id
        task = task_registry.get(real_task_id or "")
        if not task:
            yield format_sse_log(1, 2, f"任务不存在：{task_id}")
            yield format_sse_log(2, 2, "请先上传图片，再打开任务日志。", done=True)
            yield "data: [DONE]\n\n"
            return

        if task.get("mode") == FOUR_K_V1_MODE:
            cursor = 0
            deadline = time.perf_counter() + 180.0
            while time.perf_counter() < deadline:
                events = list(task.get("stage_events") or [])
                while cursor < len(events):
                    event = events[cursor]
                    cursor += 1
                    yield format_sse_log(
                        cursor,
                        max(cursor, len(events), 6),
                        str(event.get("message") or "4K任务状态已更新"),
                        extra={
                            "task_status": task.get("task_status"),
                            "task_progress": event.get("task_progress"),
                            "processing_stage": event.get("processing_stage"),
                            "error_code": task.get("error_code") or "",
                        },
                    )
                if task.get("task_status") in {"completed", "failed"}:
                    break
                await asyncio.sleep(0.05)

            if task.get("task_status") not in {"completed", "failed"}:
                task.update(
                    {
                        "task_status": "failed",
                        "status": "failed",
                        "execution_state": "failed",
                        "task_progress": 100,
                        "processing_stage": "processing_timeout",
                        "error_code": "PROCESSING_TIMEOUT",
                        "error_message": "4K任务处理超时，请确认正式目录可用后重试。",
                        "quality_conclusion": "FAILED",
                    }
                )

            final_payload = public_task(task)
            final_message = (
                f"4K高清画质增强未完成：{task.get('error_message') or '请重试。'}"
                if task.get("task_status") == "failed"
                else (
                    "原图已达到4K门槛，无需重复放大。"
                    if task.get("quality_conclusion") == "NO_PROCESSING_NEEDED"
                    else "4K高清画质增强完成"
                )
            )
            yield format_sse_log(
                max(1, cursor),
                max(1, cursor),
                final_message,
                done=True,
                extra={
                    "task": final_payload,
                    "task_status": task.get("task_status"),
                    "task_progress": 100,
                    "processing_stage": task.get("processing_stage"),
                    "error_code": task.get("error_code") or "",
                },
            )
            yield "data: [DONE]\n\n"
            return

        stage_logs = [
            "SSE CONNECTED /api/v1/tasks/{task_id}/stream",
            "读取前端上传的真实输入图片",
            "正在确认输出目录",
            "输出目录来源：{output_dir_source}",
            "输出目录验证通过，高清成品将保存至：{output_dir}",
            "完成图像类型检测与 1080P 输出尺寸规划",
            "完成退化类型检测：blur / jpeg_artifact / noise / low_resolution / mixed",
            "建立高光保护 mask：玻璃反光与过曝区域进入保护区",
            "压缩损伤修复：JPEG block 与高频断层开始清理",
            "Text Clarity Engine：检测疑似小字与说明区域",
            "Edge Safe Enhance：过滤随机噪点，仅保留真实结构边缘",
            "Structure Recovery：建筑线条、纹理与远景轮廓进入中频补偿",
            "Color Lock：输出色彩回归原图 Lab 色彩坐标",
            "1080P 输出完成：task_result 与 task_report 已生成",
        ]
        total = len(stage_logs)
        for index, message in enumerate(stage_logs, start=1):
            if index > 1:
                await asyncio.sleep(max(0.0, float(delay)))
            if task.get("task_status") not in {"completed", "failed"}:
                task["task_progress"] = min(99, int(round((index / total) * 100)))
            extra = {
                "task_id": task.get("task_id"),
                "task_status": task.get("task_status"),
                "task_progress": task.get("task_progress"),
            }
            yield format_sse_log(
                index,
                total,
                message.format(
                    task_id=task.get("task_id"),
                    output_dir_source=(task.get("output_dir_meta") or {}).get("output_dir_source", "default"),
                    output_dir=task.get("output_dir", ""),
                ),
                extra=extra,
            )

        deadline = time.perf_counter() + 180.0
        while task.get("task_status") not in {"completed", "failed"} and time.perf_counter() < deadline:
            await asyncio.sleep(0.25)
        if task.get("task_status") not in {"completed", "failed"}:
            task.update(
                {
                    "task_status": "failed",
                    "status": "failed",
                    "execution_state": "failed",
                    "task_progress": 100,
                    "error_message": "任务处理超时，SSE 已安全结束。",
                    "task_error": "任务处理超时，SSE 已安全结束。",
                    "task_report": task.get("task_report") or empty_task_report(),
                    "completed_at": datetime.now().isoformat(timespec="seconds"),
                }
            )

        final_payload = public_task(task)
        if task.get("task_status") == "failed":
            yield format_sse_log(
                total,
                total,
                f"任务失败：{task.get('error_message')}",
                done=True,
                extra={"task": final_payload, "task_status": "failed"},
            )
        else:
            yield format_sse_log(
                total,
                total,
                "任务完成：final_output 已生成，质量报告已写入任务结果。",
                done=True,
                extra={
                    "task": final_payload,
                    "task_result": task.get("task_result"),
                    "task_report": task.get("task_report"),
                    "outputUrl": task.get("final_output_url") or task.get("enhancedUrl"),
                },
            )
        yield "data: [DONE]\n\n"

    def app_workdir_payload() -> dict:
        user_dirs = current_user_dirs()
        directory_ready = bool(user_dirs["directory_ready"])
        input_dir_path = user_dirs["normal_input_dir"]
        beta_upload_dir = user_dirs["beta_upload_dir"]
        input_image_count = 0
        if directory_ready and input_dir_path.exists() and input_dir_path.is_dir():
            input_image_count = sum(
                1
                for item in input_dir_path.iterdir()
                if item.is_file() and item.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
            )
        d_drive_available = os.name == "nt" and Path("D:/").exists()
        data = {
            "app_data_root": str(user_dirs["app_data_root"]),
            "app_data_root_source": str(user_dirs["app_data_root_source"]),
            "app_data_root_exists": bool(user_dirs["app_data_root_exists"]),
            "app_data_root_writable": bool(user_dirs["app_data_root_writable"]),
            "directory_ready": directory_ready,
            "processing_allowed": directory_ready,
            "directory_error_code": str(user_dirs["directory_error_code"]),
            "directory_message": str(user_dirs["directory_message"]),
            "failed_path": str(user_dirs.get("failed_path") or ""),
            "failed_stage": str(user_dirs.get("failed_stage") or ""),
            "failure_reason": str(user_dirs.get("failure_reason") or ""),
            "cleanup_failures": list(user_dirs.get("cleanup_failures") or []),
            "d_drive_available": bool(d_drive_available),
            "switched_from_d_drive": False,
            "input_dir": str(user_dirs["normal_input_dir"]) if directory_ready else "",
            "output_dir": str(user_dirs["normal_output_dir"]) if directory_ready else "",
            "four_k_output_dir": (
                str((Path(user_dirs["app_data_root"]) / Path(FOUR_K_V1_OUTPUT_DIRECTORY)).resolve())
                if directory_ready
                else ""
            ),
            "legacy_output_dir": str(user_dirs["safe_beta_output_dir"]) if directory_ready else "",
            "beta_output_dir": str(user_dirs["safe_beta_output_dir"]) if directory_ready else "",
            "report_dir": str(user_dirs["report_dir"]) if directory_ready else "",
            "feedback_dir": str(user_dirs["feedback_dir"]) if directory_ready else "",
            "tmp_dir": str(user_dirs["tmp_dir"]) if directory_ready else "",
            "beta_upload_dir": str(beta_upload_dir) if directory_ready else "",
            "delivery_package_dir": str(user_dirs["delivery_package_dir"]) if directory_ready else "",
            "config_dir": str(user_dirs["config_dir"]) if directory_ready else "",
            "safe_beta_input_root": str(user_dirs["safe_beta_input_root"]) if directory_ready else "",
            "safe_beta_output_dir": str(user_dirs["safe_beta_output_dir"]) if directory_ready else "",
            "safe_beta_feedback_dir": str(user_dirs["safe_beta_feedback_dir"]) if directory_ready else "",
            "image_compression_output_dir": str(user_dirs["image_compression_output_dir"]) if directory_ready else "",
            "runtime_log_dir": str(user_dirs["runtime_log_dir"]) if directory_ready else "",
            "input_dir_exists": bool(directory_ready and input_dir_path.exists() and input_dir_path.is_dir()),
            "input_image_count": input_image_count,
            "beta_upload_dir_exists": bool(directory_ready and beta_upload_dir.exists() and beta_upload_dir.is_dir()),
        }
        return data

    @app.get("/api/app/workdir")
    async def get_app_workdir():
        data = app_workdir_payload()
        return {
            "code": 200,
            "status": "success" if data["directory_ready"] else "blocked",
            "success": True,
            "message": data["directory_message"],
            "data": data,
            **data,
        }

    @app.post("/api/app/workdir/select-popup")
    async def select_formal_workdir(payload: dict = Body(default_factory=dict)):
        unknown_fields = sorted(str(key) for key in payload if key not in set())
        if unknown_fields:
            raise HTTPException(status_code=400, detail=f"正式目录选择请求包含未知字段：{', '.join(unknown_fields)}。")

        def ask_directory() -> str:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            try:
                root.attributes("-topmost", True)
            except Exception:
                pass
            try:
                selected = filedialog.askdirectory(title="选择影界正式目录")
            finally:
                root.destroy()
            return selected or ""

        try:
            selected_path = await asyncio.to_thread(ask_directory)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"打开正式目录选择器失败：{exc}") from exc
        if not selected_path:
            return {"code": 200, "status": "cancelled", "success": True, "message": "已取消选择正式目录。", "data": {}}

        checked = resolve_app_data_root({"app_data_root": selected_path, "last_app_data_root": settings_data.get("last_app_data_root", "")})
        if not checked["directory_ready"]:
            log_runtime_event(
                "DIRECTORY_VALIDATION_FAILED",
                level=logging.ERROR,
                stage=checked.get("failed_stage") or "formal_directory_selection",
                result="failed",
                error_category=ENVIRONMENT_ERROR,
                path=checked.get("failed_path") or selected_path,
                reason=checked.get("failure_reason") or checked.get("message"),
                impact="formal_directory_not_changed",
                action="select_valid_writable_directory",
            )
            raise HTTPException(status_code=400, detail={"code": checked["error_code"], "message": checked["message"]})
        next_settings = {
            **settings_data,
            "app_data_root": str(checked["path"]),
            "last_app_data_root": str(checked["path"]),
        }
        try:
            save_settings(next_settings)
        except Exception as exc:
            log_runtime_event(
                "SETTINGS_WRITE_FAILED",
                level=logging.ERROR,
                stage="formal_directory_selection",
                result="failed",
                error_category=ENVIRONMENT_ERROR,
                path=SETTINGS_PATH,
                reason=str(exc),
                impact="formal_directory_not_changed",
                action="check_settings_file_permissions",
            )
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "SETTINGS_WRITE_FAILED",
                    "message": f"保存正式目录失败：{exc}",
                },
            ) from exc
        settings_data.clear()
        settings_data.update(next_settings)
        initialize_file_logging(Path(checked["path"]))
        log_runtime_event(
            "DIRECTORY_VALIDATION_SUCCEEDED",
            stage="formal_directory_selection",
            result="success",
            path=checked["path"],
            impact="formal_directory_available",
            action="persist_user_selection",
        )
        data = app_workdir_payload()
        return {"code": 200, "status": "success", "success": True, "message": "正式目录已保存并通过校验。", "data": data, **data}

    @app.get("/api/health")
    async def health():
        formal_root = read_only_formal_root_status(initial_user_dirs)
        settings_ready = settings_load_status["status"] == "loaded"
        healthy = bool(settings_ready and formal_root["directory_ready"])
        directory_ready = bool(formal_root["directory_ready"])
        return {
            "code": 200,
            "status": "success" if healthy else "degraded",
            "success": True,
            "message": (
                f"VisualMasterPro / 影界 {APP_VERSION} API 已就绪。"
                if healthy
                else f"VisualMasterPro / 影界 {APP_VERSION} API 正在运行，但运行配置或正式目录未就绪。"
            ),
            "data": {
                "version": APP_VERSION,
                "host": SERVER_HOST,
                "port": SERVER_PORT,
                "healthy": healthy,
                "health_basis": "startup_validation_plus_read_only_presence_check",
                "settings_status": settings_load_status["status"],
                "directory_ready": directory_ready,
                "directory_error_code": formal_root["error_code"],
                "directory_writable_at_startup": formal_root["writable_at_startup"],
                "default_output_dir": str(initial_user_dirs["normal_output_dir"]) if directory_ready else "",
                "app_data_root": formal_root["path"],
                "app_data_root_source": formal_root["source"],
                "safe_beta_output_dir": str(initial_user_dirs["safe_beta_output_dir"]) if directory_ready else "",
                "beta_output_dir": str(initial_user_dirs["safe_beta_output_dir"]) if directory_ready else "",
                "target_resolution": "1080P",
                "uploadEndpoint": "/api/upload",
                "taskEndpoint": "/api/v1/tasks/{task_id}",
                "streamEndpoint": "/api/v1/tasks/{task_id}/stream",
                "modes": ["fidelity", "texture", "text_safe"],
                "outputFormats": ["png", "jpg"],
            },
        }

    @app.get("/api/runtime/status")
    async def runtime_status():
        formal_root = read_only_formal_root_status(initial_user_dirs)
        overall_status = (
            "ready"
            if build_identity["status"] == "loaded"
            and settings_load_status["status"] == "loaded"
            and formal_root["directory_ready"]
            else "degraded"
        )
        data = {
            "read_only": True,
            "status": overall_status,
            "product": {
                "version": APP_VERSION,
                "build_id": build_identity["build_id"],
                "build_status": build_identity["status"],
                "build_source_path": build_identity["source_path"],
                "build_error_code": build_identity["error_code"],
                "build_reason": build_identity["reason"],
            },
            "application": {
                "status": "running",
                "runtime_id": runtime_id,
                "started_at": application_started_at,
                "uptime_seconds": round(max(0.0, time.monotonic() - application_started_monotonic), 3),
                "process_id": os.getpid(),
                "host": runtime_host,
                "port": runtime_port,
                "python_version": sys.version.split()[0],
                "platform": sys.platform,
                "executable_path": sys.executable,
            },
            "settings": {
                **settings_load_status,
                "read_only": True,
            },
            "formal_root": formal_root,
        }
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "message": "运行环境与正式目录状态读取成功。",
            "data": data,
        }

    @app.post("/api/output/validate")
    async def validate_output(payload: dict = Body(default_factory=dict)):
        output_dir_value = payload.get("output_dir") if isinstance(payload, dict) else ""
        checked = validate_output_dir_value(output_dir_value, source_hint="request")
        return {
            "code": 200 if checked["valid"] else 400,
            "status": "success" if checked["valid"] else "error",
            "success": bool(checked["valid"]),
            "valid": bool(checked["valid"]),
            "exists": bool(checked["exists"]),
            "created": bool(checked["created"]),
            "writable": bool(checked["writable"]),
            "normalized_path": checked["normalized_path"],
            "message": checked["message"],
            "data": checked,
        }

    @app.post("/api/output/apply")
    async def apply_output(payload: dict = Body(default_factory=dict)):
        output_dir_value = payload.get("output_dir") if isinstance(payload, dict) else ""
        checked = validate_output_dir_value(output_dir_value, source_hint="request")
        if not checked["valid"]:
            return {
                "code": 400,
                "status": "error",
                "success": False,
                "valid": False,
                "message": checked["message"],
                "data": checked,
            }
        next_settings = {**settings_data, "last_output_dir": checked["normalized_path"]}
        save_settings(next_settings)
        settings_data.clear()
        settings_data.update(next_settings)
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "valid": True,
            "message": "输出目录已应用。",
            "data": checked,
        }

    @app.post("/api/output/select-popup")
    async def select_output_popup(payload: dict = Body(default_factory=dict)):
        unknown_fields = sorted(str(key) for key in payload if key not in {"persist_last_output_dir"})
        if unknown_fields:
            raise HTTPException(status_code=400, detail=f"文件夹选择请求包含未知字段：{', '.join(unknown_fields)}。")
        persist_last_output_dir = payload.get("persist_last_output_dir", True) is not False

        def ask_directory() -> str:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            try:
                root.attributes("-topmost", True)
            except Exception:
                pass
            try:
                selected = filedialog.askdirectory(title="选择影界输出文件夹")
            finally:
                root.destroy()
            return selected or ""

        try:
            selected_path = await asyncio.to_thread(ask_directory)
        except Exception as exc:
            return {
                "code": 400,
                "status": "error",
                "success": False,
                "message": f"打开本地文件夹选择器失败：{exc}",
                "output_dir": "",
                "data": {},
            }

        if not selected_path:
            return {
                "code": 200,
                "status": "cancelled",
                "success": True,
                "message": "已取消选择输出文件夹。",
                "output_dir": "",
                "data": {},
            }

        checked = validate_output_dir_value(selected_path, source_hint="request")
        if not checked["valid"]:
            return {
                "code": 400,
                "status": "error",
                "success": False,
                "message": checked["message"],
                "output_dir": "",
                "data": checked,
            }
        if persist_last_output_dir:
            next_settings = {**settings_data, "last_output_dir": checked["normalized_path"]}
            save_settings(next_settings)
            settings_data.clear()
            settings_data.update(next_settings)
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "message": "已选择输出文件夹。",
            "output_dir": checked["normalized_path"],
            "data": checked,
        }

    @app.post("/api/output/open")
    async def open_output(payload: dict = Body(default_factory=dict)):
        output_dir_value = payload.get("output_dir") if isinstance(payload, dict) else ""
        checked = resolve_output_dir_for_open(output_dir_value)
        if not checked["valid"]:
            return {
                "code": 400,
                "status": "error",
                "success": False,
                "message": checked["message"],
                "data": checked,
            }
        target = Path(checked["normalized_path"])
        if not target.exists() or not target.is_dir():
            return {
                "code": 400,
                "status": "error",
                "success": False,
                "message": "输出目录不存在或不是目录。",
                "data": checked,
            }
        if sys.platform != "win32":
            return {
                "code": 400,
                "status": "error",
                "success": False,
                "message": "当前系统不支持自动打开目录。",
                "data": checked,
            }
        try:
            os.startfile(str(target))  # noqa: S606 - Windows shell open for a validated directory only.
        except Exception as exc:
            return {
                "code": 400,
                "status": "error",
                "success": False,
                "message": f"打开输出目录失败：{exc}",
                "data": checked,
            }
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "message": "已打开输出目录。",
            "data": checked,
        }

    def beta_redact_text(value) -> str:
        text = "" if value is None else str(value)
        if not text:
            return ""
        home = str(Path.home())
        if home and text.lower().startswith(home.lower()):
            text = "%USERPROFILE%" + text[len(home) :]
        for sensitive, replacement in (
            (os.environ.get("USERNAME") or os.environ.get("USER") or "", "%USERNAME%"),
            (os.environ.get("COMPUTERNAME") or "", "%COMPUTERNAME%"),
        ):
            if sensitive:
                text = text.replace(sensitive, replacement)
        text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "%IPV4%", text)
        text = re.sub(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b", "%MAC%", text)
        return text

    def beta_redact_path(value) -> str:
        return beta_redact_text(value)

    def beta_tail_text(value, limit: int = 1200) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        return beta_redact_text(text[-limit:])

    def beta_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def beta_result_dict(value: object, output_dir_value: str | Path | None = None) -> dict:
        if isinstance(value, dict):
            return value
        return {
            "status": "failed",
            "verification_result": "FAILED",
            "stage": "BETA_RESULT_INVALID",
            "reason": "BETA_RESULT_INVALID",
            "error": "1080P安全增强 Beta 返回结果无效。",
            "error_message": f"invalid_result_type={type(value).__name__}",
            "processed_count": 0,
            "skipped_count": 0,
            "processed": [],
            "skipped": [],
            "output_dir": str(output_dir_value or resolve_hdde_user_dirs()["safe_beta_output_dir"]),
        }

    def beta_decode_selected_names(form) -> list[str]:
        encoded_names = ""
        try:
            encoded_names = str(form.get("selected_file_names_encoded") or "").strip()
        except Exception:
            encoded_names = ""
        if encoded_names:
            try:
                decoded_value = json.loads(urllib.parse.unquote(encoded_names))
                if isinstance(decoded_value, list):
                    names = [
                        safe_upload_name(str(value))
                        for value in decoded_value
                        if str(value or "").strip()
                    ]
                    if names:
                        return names
            except Exception as exc:
                beta_stage_log(
                    "BETA_SELECTED_NAME_DECODE_FAILED",
                    error_message=str(exc),
                )
        try:
            return [
                safe_upload_name(str(value))
                for value in form.getlist("selected_file_names")
                if str(value or "").strip()
            ]
        except Exception as exc:
            beta_stage_log(
                "BETA_SELECTED_NAME_DECODE_FAILED",
                error_message=str(exc),
            )
            return []

    def beta_stage_log(stage: str, **fields) -> None:
        event = {
            "stage": stage,
            "beta_run_id": fields.get("beta_run_id") or "",
            "input_path": beta_redact_path(fields.get("input_path")),
            "output_dir": beta_redact_path(fields.get("output_dir")),
            "current_file": fields.get("current_file") or "",
            "flat_output": bool(fields.get("flat_output")),
            "business_output": bool(fields.get("business_output")),
            "elapsed_seconds": fields.get("elapsed_seconds", ""),
            "returncode": fields.get("returncode", ""),
            "stderr_tail": beta_tail_text(fields.get("stderr_tail")),
            "error_message": beta_tail_text(fields.get("error_message")),
        }
        enqueue_beta_log("[SAFE_1080P_BETA] " + json.dumps(event, ensure_ascii=False))

    def beta_failure_response(
        result: dict | None,
        output_dir_value: str | Path | None = None,
        status_code: int = 200,
        code: int = 500,
    ) -> JSONResponse:
        result = beta_result_dict(result or {}, output_dir_value)
        skipped_items = result.get("skipped") if isinstance(result.get("skipped"), list) else []
        first_skip = skipped_items[0] if skipped_items and isinstance(skipped_items[0], dict) else {}
        skip_reason = first_skip.get("reason") or ""
        skip_file = first_skip.get("file") or result.get("failed_file") or ""
        stage = result.get("stage") or ("BETA_INPUT_SKIPPED" if skipped_items else "") or result.get("reason") or "BETA_FAILED"
        output_dir_text = str(result.get("output_dir") or output_dir_value or "")
        output_dir_path = Path(output_dir_text) if output_dir_text else Path()
        rows = []
        enhanced_files = []
        for item in result.get("processed") or []:
            if not isinstance(item, dict):
                continue
            input_name = item.get("input_name") or item.get("file") or ""
            raw_output = item.get("output_path") or item.get("enhanced") or ""
            output_path = Path(str(raw_output)) if raw_output else Path()
            if raw_output and not output_path.is_absolute() and output_dir_text:
                output_path = output_dir_path / output_path
            output_name = item.get("output_name") or (output_path.name if raw_output else "")
            output_path_text = str(output_path) if raw_output else ""
            if output_path_text:
                enhanced_files.append(output_path_text)
            rows.append({"input_name": input_name, "output_name": output_name, "output_path": output_path_text})
        error = (
            result.get("error")
            or result.get("error_message")
            or (f"{skip_file} 被 1080P安全增强 Beta 安全策略跳过：{skip_reason}" if skip_reason else "")
            or result.get("reason")
            or "1080P safe enhance Beta failed."
        )
        beta_run_id = str(result.get("beta_run_id") or "")
        body = {
            "ok": False,
            "success": False,
            "status": "FAILED",
            "code": code,
            "beta_run_id": beta_run_id,
            "verification_result": "FAILED",
            "stage": stage,
            "error": beta_tail_text(error),
            "message": beta_tail_text(error),
            "processed_count": beta_int(result.get("processed_count"), 0),
            "skipped_count": beta_int(result.get("skipped_count"), 0),
            "enhanced_files": enhanced_files,
            "results": rows,
            "skipped": skipped_items,
            "input_dir": str(result.get("input_dir") or ""),
            "input_files": result.get("input_files") if isinstance(result.get("input_files"), list) else [],
            "input_file_names": result.get("input_file_names") if isinstance(result.get("input_file_names"), list) else [],
            "input_file_count": beta_int(result.get("input_file_count"), 0),
            "output_dir": output_dir_text,
            "app_data_root": str(result.get("app_data_root") or ""),
            "app_data_root_source": str(result.get("app_data_root_source") or ""),
            "app_data_root_exists": bool(result.get("app_data_root_exists")),
            "app_data_root_writable": bool(result.get("app_data_root_writable")),
            "report_dir": str(result.get("report_dir") or ""),
            "feedback_dir": str(result.get("feedback_dir") or ""),
            "beta_upload_dir": str(result.get("beta_upload_dir") or ""),
            "timeout_source": result.get("timeout_source", ""),
            "persisted_input_files": result.get("persisted_input_files") if isinstance(result.get("persisted_input_files"), list) else [],
            "original_to_persisted_path": result.get("original_to_persisted_path") if isinstance(result.get("original_to_persisted_path"), list) else [],
            "data": result,
        }
        return JSONResponse(status_code=status_code, content=body)

    def beta_success_body(result: dict, verification_result: str) -> dict:
        result = beta_result_dict(result)
        beta_run_id = str(result.get("beta_run_id") or "")
        output_dir_value = result.get("output_dir") or ""
        output_dir_path = Path(str(output_dir_value)) if output_dir_value else Path()
        rows = []
        enhanced_files = []
        for item in result.get("processed") or []:
            if not isinstance(item, dict):
                continue
            input_name = item.get("input_name") or item.get("file") or ""
            raw_output = item.get("output_path") or item.get("enhanced") or ""
            output_path = Path(str(raw_output)) if raw_output else Path()
            if raw_output and not output_path.is_absolute() and output_dir_value:
                output_path = output_dir_path / output_path
            output_name = item.get("output_name") or (output_path.name if raw_output else "")
            output_path_text = str(output_path) if raw_output else ""
            if output_path_text:
                enhanced_files.append(output_path_text)
            rows.append(
                {
                    "input_name": input_name,
                    "output_name": output_name,
                    "output_path": output_path_text,
                }
            )
        result["results"] = rows
        result["enhanced_files"] = enhanced_files
        input_files = [str(item) for item in result.get("input_files") or [] if str(item or "").strip()]
        input_file_names = [Path(item).name for item in input_files]
        result["input_files"] = input_files
        result["input_file_names"] = input_file_names
        result["input_file_count"] = len(input_files)
        return {
            "ok": True,
            "success": True,
            "status": "SUCCESS",
            "code": 200,
            "beta_run_id": beta_run_id,
            "message": "1080P safe enhance Beta completed.",
            "verification_result": verification_result,
            "processed_count": beta_int(result.get("processed_count"), len(rows)),
            "skipped_count": beta_int(result.get("skipped_count"), 0),
            "enhanced_files": enhanced_files,
            "results": rows,
            "input_dir": str(result.get("input_dir") or ""),
            "input_dir_exists": bool(result.get("input_dir_exists")),
            "input_image_count": beta_int(result.get("input_image_count"), len(input_files)),
            "input_files": input_files,
            "input_file_names": input_file_names,
            "input_file_count": len(input_files),
            "output_dir": str(output_dir_value),
            "app_data_root": str(result.get("app_data_root") or ""),
            "app_data_root_source": str(result.get("app_data_root_source") or ""),
            "app_data_root_exists": bool(result.get("app_data_root_exists")),
            "app_data_root_writable": bool(result.get("app_data_root_writable")),
            "report_dir": str(result.get("report_dir") or ""),
            "feedback_dir": str(result.get("feedback_dir") or ""),
            "beta_upload_dir": str(result.get("beta_upload_dir") or ""),
            "total_elapsed_seconds": result.get("total_elapsed_seconds", result.get("elapsed_seconds", "")),
            "timeout_source": result.get("timeout_source", ""),
            "persisted_input_files": result.get("persisted_input_files") if isinstance(result.get("persisted_input_files"), list) else [],
            "original_to_persisted_path": result.get("original_to_persisted_path") if isinstance(result.get("original_to_persisted_path"), list) else [],
            "timings": result.get("timings") if isinstance(result.get("timings"), dict) else {},
            "data": result,
        }

    def run_safe_1080p_beta(payload: dict) -> dict:
        import importlib.util
        beta_started = time.perf_counter()
        beta_run_id = str((payload or {}).get("beta_run_id") or "")
        backend_timings = dict((payload or {}).get("timings") or {})
        workdir_context = app_workdir_payload()
        queue_prepare_started = time.perf_counter()

        def attach_workdir_context(result: dict) -> dict:
            for key in (
                "app_data_root",
                "app_data_root_source",
                "app_data_root_exists",
                "app_data_root_writable",
                "report_dir",
                "feedback_dir",
                "beta_upload_dir",
                "delivery_package_dir",
                "config_dir",
                "safe_beta_input_root",
                "safe_beta_output_dir",
                "safe_beta_feedback_dir",
            ):
                result[key] = workdir_context.get(key)
            return result

        input_file_values = [
            Path(str(item)).expanduser()
            for item in ((payload or {}).get("input_files") or [])
            if str(item or "").strip()
        ]
        input_file_names = [item.name for item in input_file_values]
        backend_timings["queue_prepare_seconds"] = round(time.perf_counter() - queue_prepare_started, 3)
        beta_stage_log(
            "BETA_REQUEST_RECEIVED",
            input_path=(payload or {}).get("input_dir"),
            output_dir=(payload or {}).get("output_dir"),
            current_file=", ".join(input_file_names),
            flat_output=bool((payload or {}).get("flat_output")),
            business_output=bool((payload or {}).get("business_output")),
            elapsed_seconds=0,
            beta_run_id=beta_run_id,
        )
        beta_stage_log(
            "BETA_REQUEST_INPUT_FILES",
            input_path=(payload or {}).get("input_dir"),
            output_dir=(payload or {}).get("output_dir"),
            current_file=", ".join(input_file_names),
            flat_output=bool((payload or {}).get("flat_output")),
            business_output=bool((payload or {}).get("business_output")),
            elapsed_seconds=round(time.perf_counter() - beta_started, 3),
            beta_run_id=beta_run_id,
        )
        if not input_file_values:
            beta_stage_log(
                "BETA_FAILED",
                input_path=(payload or {}).get("input_dir"),
                output_dir=(payload or {}).get("output_dir"),
                flat_output=bool((payload or {}).get("flat_output")),
                business_output=bool((payload or {}).get("business_output")),
                elapsed_seconds=round(time.perf_counter() - beta_started, 3),
                error_message="BETA_INPUT_MISSING",
                beta_run_id=beta_run_id,
            )
            return attach_workdir_context({
                "ok": False,
                "success": False,
                "beta_run_id": beta_run_id,
                "status": "failed",
                "verification_result": "FAILED",
                "stage": "BETA_INPUT_MISSING",
                "reason": "BETA_INPUT_MISSING",
                "error": "BETA_INPUT_MISSING / 请先添加图片",
                "error_message": "BETA_INPUT_MISSING / 请先添加图片",
                "processed_count": 0,
                "skipped_count": 0,
                "processed": [],
                "skipped": [],
                "output_dir": str((payload or {}).get("output_dir") or resolve_hdde_user_dirs()["safe_beta_output_dir"]),
            })

        module_path = PROJECT_ROOT / "tools" / "experiments" / "safe_1080p_enhance.py"
        if not module_path.exists():
            beta_stage_log(
                "BETA_FAILED",
                input_path=(payload or {}).get("input_dir"),
                output_dir=(payload or {}).get("output_dir"),
                flat_output=bool((payload or {}).get("flat_output")),
                business_output=bool((payload or {}).get("business_output")),
                elapsed_seconds=round(time.perf_counter() - beta_started, 3),
                error_message="missing_safe_1080p_module",
                beta_run_id=beta_run_id,
            )
            return {
                "beta_run_id": beta_run_id,
                "status": "blocked",
                "verification_result": "BLOCKED",
                "reason": "missing_safe_1080p_module",
            }

        spec = importlib.util.spec_from_file_location("safe_1080p_enhance", module_path)
        if spec is None or spec.loader is None:
            beta_stage_log(
                "BETA_FAILED",
                input_path=(payload or {}).get("input_dir"),
                output_dir=(payload or {}).get("output_dir"),
                flat_output=bool((payload or {}).get("flat_output")),
                business_output=bool((payload or {}).get("business_output")),
                elapsed_seconds=round(time.perf_counter() - beta_started, 3),
                error_message="cannot_load_safe_1080p_module",
                beta_run_id=beta_run_id,
            )
            return {
                "beta_run_id": beta_run_id,
                "status": "blocked",
                "verification_result": "BLOCKED",
                "reason": "cannot_load_safe_1080p_module",
            }
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        input_dir_value = payload.get("input_dir") or str(input_file_values[0].parent)
        user_dirs = resolve_hdde_user_dirs()
        workdir_context = app_workdir_payload()
        output_dir_value = payload.get("output_dir") or str(user_dirs["safe_beta_output_dir"])
        mode_value = payload.get("mode") or "safe_1080p"
        if mode_value != "safe_1080p":
            beta_stage_log(
                "BETA_FAILED",
                input_path=input_dir_value,
                output_dir=output_dir_value,
                flat_output=bool(payload.get("flat_output")),
                business_output=bool(payload.get("business_output")),
                elapsed_seconds=round(time.perf_counter() - beta_started, 3),
                error_message="unsupported_beta_mode",
                beta_run_id=beta_run_id,
            )
            return {
                "beta_run_id": beta_run_id,
                "status": "blocked",
                "verification_result": "BLOCKED",
                "reason": "unsupported_beta_mode",
            }

        input_path = Path(str(input_dir_value)).expanduser()
        output_path = Path(str(output_dir_value)).expanduser()
        if not input_path.is_absolute():
            input_path = (PROJECT_ROOT / input_path).resolve()
        if not output_path.is_absolute():
            output_path = (PROJECT_ROOT / output_path).resolve()
        beta_stage_log(
            "BETA_INPUT_RESOLVED",
            input_path=input_path,
            output_dir=output_path,
            current_file=", ".join(input_file_names),
            flat_output=bool(payload.get("flat_output")),
            business_output=bool(payload.get("business_output")),
            elapsed_seconds=round(time.perf_counter() - beta_started, 3),
            beta_run_id=beta_run_id,
        )
        beta_stage_log(
            "BETA_RESOLVED_INPUT_FILES",
            input_path="; ".join(str(item.resolve()) for item in input_file_values),
            output_dir=output_path,
            current_file=", ".join(input_file_names),
            flat_output=bool(payload.get("flat_output")),
            business_output=bool(payload.get("business_output")),
            elapsed_seconds=round(time.perf_counter() - beta_started, 3),
            beta_run_id=beta_run_id,
        )
        beta_stage_log(
            "BETA_OUTPUT_DIR_RESOLVED",
            input_path=input_path,
            output_dir=output_path,
            current_file=", ".join(input_file_names),
            flat_output=bool(payload.get("flat_output")),
            business_output=bool(payload.get("business_output")),
            elapsed_seconds=round(time.perf_counter() - beta_started, 3),
            beta_run_id=beta_run_id,
        )

        def beta_run_stage_log(stage: str, **fields) -> None:
            fields.setdefault("beta_run_id", beta_run_id)
            beta_stage_log(stage, **fields)

        args = argparse.Namespace(
            input_dir=input_path,
            output_dir=output_path,
            mode="safe_1080p",
            tool_dir=PROJECT_ROOT / "external_tools" / "realesrgan-ncnn-vulkan",
            model="realesrgan-x4plus",
            scale="4",
            flat_output=True,
            business_output=True,
            timeout_seconds=300,
            stage_logger=beta_run_stage_log,
            diagnostic_dir=user_dirs["safe_beta_feedback_dir"],
            input_files=[item.resolve() for item in input_file_values],
            persisted_input_files=payload.get("persisted_input_files") if isinstance(payload.get("persisted_input_files"), list) else [],
        )
        script_started = time.perf_counter()
        result = attach_workdir_context(beta_result_dict(module.process(args), output_path))
        backend_timings["script_start_seconds"] = round(script_started - beta_started, 3)
        backend_timings["backend_api_blocking_seconds"] = round(time.perf_counter() - script_started, 3)
        backend_timings["backend_total_seconds"] = round(time.perf_counter() - beta_started, 3)
        result["beta_run_id"] = beta_run_id
        result["timings"] = {**backend_timings, **(result.get("timings") if isinstance(result.get("timings"), dict) else {})}
        processed_count = beta_int(result.get("processed_count"), 0)
        skipped_count = beta_int(result.get("skipped_count"), 0)
        if result.get("status") != "ok" or processed_count <= 0:
            if not result.get("verification_result"):
                result["verification_result"] = "FAILED" if result.get("status") == "failed" else "BLOCKED"
            beta_stage_log(
                "BETA_RESPONSE_READY",
                input_path=input_path,
                output_dir=output_path,
                current_file=result.get("failed_file") or "",
                flat_output=True,
                business_output=True,
                elapsed_seconds=round(time.perf_counter() - beta_started, 3),
                returncode=result.get("returncode", ""),
                stderr_tail=result.get("stderr_tail", ""),
                error_message=result.get("error_message") or result.get("reason") or result.get("status"),
                beta_run_id=beta_run_id,
            )
            return result

        processed_rows = [item for item in (result.get("processed") or []) if isinstance(item, dict)]
        fast_rows = [
            item
            for item in processed_rows
            if str(item.get("enhance_route") or "") in {"already_1080p_fast_safe_enhance", "already_1080p_balanced_fast_enhance"}
        ]
        speed_risk_rows = [item for item in processed_rows if bool(item.get("speed_risk")) or bool(item.get("heavy_route_speed_risk"))]
        verification_blockers: list[str] = []
        for item in processed_rows:
            file_name = str(item.get("file") or item.get("input_name") or "unknown")
            route_name = str(item.get("enhance_route") or "")
            if not route_name:
                verification_blockers.append(f"{file_name}: missing enhance_route")
            if not item.get("route_decision_reason"):
                verification_blockers.append(f"{file_name}: missing route_decision_reason")
            if item.get("roi_evidence_status") != "available":
                verification_blockers.append(f"{file_name}: roi_evidence_status={item.get('roi_evidence_status') or 'missing'}")
            if route_name in {"already_1080p_fast_safe_enhance", "already_1080p_balanced_fast_enhance"}:
                if bool(item.get("uses_realesrgan")):
                    verification_blockers.append(f"{file_name}: fast route uses_realesrgan=true")
                if not bool(item.get("fast_route_skipped_realesrgan")):
                    verification_blockers.append(f"{file_name}: fast route skipped_realesrgan=false")
                try:
                    if float(item.get("speed_actual_seconds") or 0) > 30.0:
                        verification_blockers.append(f"{file_name}: fast route speed_actual_seconds>30")
                except (TypeError, ValueError):
                    verification_blockers.append(f"{file_name}: invalid speed_actual_seconds")
            if bool(item.get("unexpected_downscale")):
                verification_blockers.append(f"{file_name}: unexpected_downscale")
            if item.get("quality_status") == "blocked":
                verification_blockers.append(f"{file_name}: {item.get('quality_status_reason') or 'quality_status=blocked'}")
        if result.get("diagnostics_consistency") == "BLOCKED":
            verification_blockers.extend(str(item) for item in (result.get("diagnostics_consistency_blockers") or []) if item)
        verification_blockers = list(dict.fromkeys(verification_blockers))
        result["verification_blockers"] = verification_blockers
        result["diagnostics_consistency"] = "PASS" if not verification_blockers else "BLOCKED"
        result["diagnostics_consistency_blockers"] = verification_blockers
        if fast_rows:
            result["fast_route_speed_pass"] = all(bool(item.get("fast_route_speed_pass")) for item in fast_rows)
            result["fast_route_quality_pass"] = all(bool(item.get("fast_route_quality_pass")) for item in fast_rows)
            result["fast_route_final_pass"] = all(bool(item.get("fast_route_final_pass")) for item in fast_rows)
        if verification_blockers:
            result["verification_result"] = "BLOCKED"
            result["generation_status"] = "generated"
            result["quality_status"] = "blocked"
            result["delivery_status"] = "review_before_use"
            result["reason"] = "diagnostics_consistency_blocked"
            result["error_message"] = "; ".join(verification_blockers[:5])
        elif speed_risk_rows:
            result["verification_result"] = "PASS_WITH_NOTES"
        else:
            result["verification_result"] = "PASS_WITH_NOTES" if skipped_count else "PASS"
        if not verification_blockers:
            result["generation_status"] = "generated"
            row_statuses = [str(item.get("quality_status") or "") for item in processed_rows]
            result["quality_status"] = "insufficient_gain" if "insufficient_gain" in row_statuses else "pass_candidate"
            result["delivery_status"] = "review_before_use"
        result["beta_policy"] = {
            "mode": "safe_1080p",
            "strategy": "route-aware safe beta",
            "scope": "route-aware Chinese commercial, portrait, and knowledge visuals",
            "main_pipeline": False,
        }
        beta_stage_log(
            "BETA_RESPONSE_READY",
            input_path=input_path,
            output_dir=output_path,
            current_file=(result.get("processed") or [{}])[-1].get("file") if result.get("processed") else "",
            flat_output=True,
            business_output=True,
            elapsed_seconds=round(time.perf_counter() - beta_started, 3),
            beta_run_id=beta_run_id,
        )
        return result

    @app.post("/api/beta/safe-1080p/enhance")
    async def beta_safe_1080p_enhance(request: Request):
        user_dirs = require_directory_ready()
        payload: dict = {}
        output_dir_value = str(user_dirs["safe_beta_output_dir"])
        beta_run_id = ""
        try:
            content_type = request.headers.get("content-type", "").lower()
            if "multipart/form-data" in content_type:
                form = await request.form()
                beta_run_id = str(form.get("beta_run_id") or "")
                output_dir_value = str(form.get("output_dir") or output_dir_value)
                beta_stage_log(
                    "BETA_API_REQUEST_RECEIVED",
                    output_dir=output_dir_value,
                    flat_output=parse_bool_value(form.get("flat_output"), True),
                    business_output=parse_bool_value(form.get("business_output"), True),
                    beta_run_id=beta_run_id,
                )
                beta_stage_log(
                    "BETA_API_FORM_FIELDS",
                    output_dir=output_dir_value,
                    current_file=str(form.get("selected_file_names") or ""),
                    flat_output=parse_bool_value(form.get("flat_output"), True),
                    business_output=parse_bool_value(form.get("business_output"), True),
                    beta_run_id=beta_run_id,
                )
                temp_input_dir = prepare_safe_beta_user_input_dir(beta_run_id)
                temp_input_dir.mkdir(parents=True, exist_ok=True)
                input_files: list[str] = []
                selected_names: list[str] = []
                persisted_input_files: list[dict[str, str]] = []
                declared_names = beta_decode_selected_names(form)
                beta_stage_log(
                    "BETA_API_FILES_RECEIVED",
                    input_path=temp_input_dir,
                    output_dir=output_dir_value,
                    current_file=", ".join(declared_names),
                    flat_output=parse_bool_value(form.get("flat_output"), True),
                    business_output=parse_bool_value(form.get("business_output"), True),
                    beta_run_id=beta_run_id,
                )
                file_index = 0
                for key, value in form.multi_items():
                    if hasattr(value, "filename") and hasattr(value, "read"):
                        upload_name = declared_names[file_index] if file_index < len(declared_names) else safe_upload_name(getattr(value, "filename", None))
                        file_index += 1
                        try:
                            raw = await value.read()
                        except Exception as exc:
                            raise RuntimeError(f"BETA_MULTIPART_FILE_READ_FAILED: {upload_name}: {exc}") from exc
                        if raw:
                            saved_path = unique_child_path(temp_input_dir, upload_name)
                            selected_names.append(saved_path.name)
                            try:
                                saved_path.write_bytes(raw)
                            except Exception as exc:
                                raise RuntimeError(f"BETA_MULTIPART_FILE_SAVE_FAILED: {upload_name}: {exc}") from exc
                            if not saved_path.exists() or not saved_path.is_file():
                                raise RuntimeError(f"BETA_MULTIPART_TEMP_FILE_MISSING: {upload_name}")
                            input_files.append(str(saved_path))
                            persisted_input_files.append(
                                {
                                    "original_filename": upload_name,
                                    "persisted_path": str(saved_path),
                                }
                            )
                    else:
                        payload[key] = value
                output_dir_value = payload.get("output_dir") or output_dir_value
                beta_run_id = str(payload.get("beta_run_id") or beta_run_id)
                payload.update(
                    {
                        "beta_run_id": beta_run_id,
                        "input_dir": str(temp_input_dir),
                        "input_files": input_files,
                        "persisted_input_files": persisted_input_files,
                        "original_to_persisted_path": persisted_input_files,
                        "selected_file_names": selected_names,
                        "flat_output": parse_bool_value(payload.get("flat_output"), True),
                        "business_output": parse_bool_value(payload.get("business_output"), True),
                        "mode": payload.get("mode") or "safe_1080p",
                        "output_dir": output_dir_value,
                    }
                )
                if not input_files:
                    beta_stage_log(
                        "BETA_INPUT_MISSING",
                        input_path=temp_input_dir,
                        output_dir=output_dir_value,
                        current_file=", ".join(declared_names),
                        flat_output=payload["flat_output"],
                        business_output=payload["business_output"],
                        beta_run_id=beta_run_id,
                        error_message="BETA_INPUT_MISSING / 请先添加图片",
                    )
                beta_stage_log(
                    "BETA_API_INPUT_FILES_RESOLVED",
                    input_path="; ".join(input_files),
                    output_dir=output_dir_value,
                    current_file=", ".join(selected_names),
                    flat_output=payload["flat_output"],
                    business_output=payload["business_output"],
                    beta_run_id=beta_run_id,
                )
            else:
                try:
                    payload = await request.json()
                except Exception:
                    payload = {}
                payload = payload if isinstance(payload, dict) else {}
                output_dir_value = payload.get("output_dir") or output_dir_value
                beta_run_id = str(payload.get("beta_run_id") or "")
                beta_stage_log(
                    "BETA_API_REQUEST_RECEIVED",
                    input_path=payload.get("input_dir"),
                    output_dir=output_dir_value,
                    current_file=", ".join([Path(str(item)).name for item in payload.get("input_files") or []]),
                    flat_output=bool(payload.get("flat_output")),
                    business_output=bool(payload.get("business_output")),
                    beta_run_id=beta_run_id,
                )
                beta_stage_log(
                    "BETA_API_FORM_FIELDS",
                    input_path=payload.get("input_dir"),
                    output_dir=output_dir_value,
                    current_file=", ".join([Path(str(item)).name for item in payload.get("input_files") or []]),
                    flat_output=bool(payload.get("flat_output")),
                    business_output=bool(payload.get("business_output")),
                    beta_run_id=beta_run_id,
                )
                beta_stage_log(
                    "BETA_API_INPUT_FILES_RESOLVED",
                    input_path="; ".join([str(item) for item in payload.get("input_files") or []]),
                    output_dir=output_dir_value,
                    current_file=", ".join([Path(str(item)).name for item in payload.get("input_files") or []]),
                    flat_output=bool(payload.get("flat_output")),
                    business_output=bool(payload.get("business_output")),
                    beta_run_id=beta_run_id,
                )
            if not ((payload or {}).get("input_files") or []):
                result = {
                    "ok": False,
                    "success": False,
                    "beta_run_id": beta_run_id,
                    "status": "failed",
                    "verification_result": "FAILED",
                    "stage": "BETA_INPUT_MISSING",
                    "reason": "BETA_INPUT_MISSING",
                    "error": "BETA_INPUT_MISSING / 请先添加图片",
                    "error_message": "BETA_INPUT_MISSING / 请先添加图片",
                    "processed_count": 0,
                    "skipped_count": 0,
                    "input_dir": str((payload or {}).get("input_dir") or ""),
                    "input_files": [],
                    "input_file_names": [],
                    "input_file_count": 0,
                    "processed": [],
                    "skipped": [],
                    "output_dir": output_dir_value,
                }
                beta_stage_log(
                    "BETA_API_RESPONSE_READY",
                    input_path=(payload or {}).get("input_dir") if isinstance(payload, dict) else "",
                    output_dir=output_dir_value,
                    current_file="",
                    flat_output=bool((payload or {}).get("flat_output")) if isinstance(payload, dict) else False,
                    business_output=bool((payload or {}).get("business_output")) if isinstance(payload, dict) else False,
                    beta_run_id=beta_run_id,
                    error_message=result["error_message"],
                )
                return beta_failure_response(result, output_dir_value, 200, 400)
            beta_stage_log(
                "BETA_API_ENHANCE_START",
                input_path=(payload or {}).get("input_dir"),
                output_dir=(payload or {}).get("output_dir"),
                current_file=", ".join([Path(str(item)).name for item in (payload or {}).get("input_files") or []]),
                flat_output=bool((payload or {}).get("flat_output")),
                business_output=bool((payload or {}).get("business_output")),
                beta_run_id=beta_run_id,
            )
            result = await asyncio.to_thread(run_safe_1080p_beta, payload if isinstance(payload, dict) else {})
            if isinstance(result, dict) and isinstance(payload, dict):
                input_files = [str(item) for item in payload.get("input_files") or [] if str(item or "").strip()]
                result.setdefault("input_dir", str(payload.get("input_dir") or ""))
                result["input_files"] = input_files
                result["input_file_names"] = [Path(item).name for item in input_files]
                result["input_file_count"] = len(input_files)
                if isinstance(payload.get("persisted_input_files"), list):
                    result["persisted_input_files"] = payload.get("persisted_input_files")
                    result["original_to_persisted_path"] = payload.get("persisted_input_files")
            beta_stage_log(
                "BETA_API_ENHANCE_DONE",
                input_path=(payload or {}).get("input_dir"),
                output_dir=(payload or {}).get("output_dir"),
                current_file=", ".join([Path(str(item)).name for item in (payload or {}).get("input_files") or []]),
                flat_output=bool((payload or {}).get("flat_output")),
                business_output=bool((payload or {}).get("business_output")),
                beta_run_id=beta_run_id,
                error_message=(result or {}).get("error_message") or (result or {}).get("reason") or "",
            )
        except Exception as exc:
            beta_stage_log(
                "BETA_API_FAILED",
                input_path=(payload or {}).get("input_dir") if isinstance(payload, dict) else "",
                output_dir=(payload or {}).get("output_dir") if isinstance(payload, dict) else "",
                flat_output=bool((payload or {}).get("flat_output")) if isinstance(payload, dict) else False,
                business_output=bool((payload or {}).get("business_output")) if isinstance(payload, dict) else False,
                error_message=str(exc),
                beta_run_id=beta_run_id,
            )
            result = {
                "beta_run_id": beta_run_id,
                "status": "failed",
                "verification_result": "FAILED",
                "reason": "beta_api_exception",
                "error_message": beta_tail_text(str(exc)),
            }
        result = beta_result_dict(result, output_dir_value)
        result["beta_run_id"] = result.get("beta_run_id") or beta_run_id
        verification_result = result.get("verification_result") or "BLOCKED"
        success = verification_result in {"PASS", "PASS_WITH_NOTES"}
        if not success:
            beta_stage_log(
                "BETA_API_RESPONSE_READY",
                input_path=(payload or {}).get("input_dir") if isinstance(payload, dict) else "",
                output_dir=output_dir_value,
                current_file=", ".join([Path(str(item)).name for item in (payload or {}).get("input_files") or []]) if isinstance(payload, dict) else "",
                flat_output=bool((payload or {}).get("flat_output")) if isinstance(payload, dict) else False,
                business_output=bool((payload or {}).get("business_output")) if isinstance(payload, dict) else False,
                beta_run_id=beta_run_id,
                error_message=result.get("error_message") or result.get("reason") or result.get("stage") or "",
            )
            return beta_failure_response(result, output_dir_value, 200, 500)
        beta_stage_log(
            "BETA_API_RESPONSE_READY",
            input_path=(payload or {}).get("input_dir") if isinstance(payload, dict) else "",
            output_dir=output_dir_value,
            current_file=", ".join([Path(str(item)).name for item in (payload or {}).get("input_files") or []]) if isinstance(payload, dict) else "",
            flat_output=bool((payload or {}).get("flat_output")) if isinstance(payload, dict) else False,
            business_output=bool((payload or {}).get("business_output")) if isinstance(payload, dict) else False,
            beta_run_id=beta_run_id,
        )
        return beta_success_body(result, verification_result)

    @app.post("/api/beta/safe-1080p/output-status")
    async def beta_safe_1080p_output_status(payload: dict = Body(default_factory=dict)):
        user_dirs = require_directory_ready()
        payload = payload if isinstance(payload, dict) else {}
        beta_run_id = str(payload.get("beta_run_id") or "")
        output_dir_value = payload.get("output_dir") or str(user_dirs["safe_beta_output_dir"])
        output_dir = Path(str(output_dir_value)).expanduser()
        selected_names_raw = payload.get("selected_file_names") or payload.get("files") or []
        if isinstance(selected_names_raw, str):
            selected_names = [selected_names_raw]
        else:
            selected_names = [str(item) for item in selected_names_raw if str(item or "").strip()]
        results: list[dict[str, str]] = []
        if output_dir.exists() and output_dir.is_dir():
            for selected_name in selected_names:
                safe_name = safe_upload_name(selected_name)
                stem = Path(safe_name).stem
                candidates = sorted(output_dir.glob(f"{stem}_1080p_beta*.png"), key=lambda item: item.stat().st_mtime, reverse=True)
                if candidates:
                    output_path = candidates[0]
                    results.append(
                        {
                            "input_name": safe_name,
                            "output_name": output_path.name,
                            "output_path": str(output_path),
                        }
                    )
        found = bool(results)
        return {
            "ok": found,
            "success": True,
            "status": "SUCCESS" if found else "PENDING",
            "code": 200,
            "beta_run_id": beta_run_id,
            "found": found,
            "verification_result": "PASS" if found else "PENDING",
            "processed_count": len(results),
            "skipped_count": 0,
            "results": results,
            "enhanced_files": [row["output_path"] for row in results],
            "output_dir": str(output_dir),
        }

    @app.post("/api/beta/safe-1080p/feedback-package")
    async def beta_safe_1080p_feedback_package(payload: dict = Body(default_factory=dict)):
        require_directory_ready()
        from engine.diagnostics.safe_1080p_feedback_package import generate_safe_1080p_feedback_package

        payload = payload if isinstance(payload, dict) else {}
        try:
            run_result = payload.get("run_result") if isinstance(payload.get("run_result"), dict) else None
            if not run_result:
                run_result = await asyncio.to_thread(run_safe_1080p_beta, payload)
            feedback_dir_value = payload.get("feedback_dir") or None
            feedback_dir = Path(str(feedback_dir_value)).expanduser() if feedback_dir_value else None
            package = await asyncio.to_thread(
                generate_safe_1080p_feedback_package,
                run_result,
                PROJECT_ROOT,
                feedback_dir,
            )
        except Exception as exc:
            package = {
                "feedback_bundle_status": "BLOCKED",
                "feedback_zip_path": "",
                "feedback_bundle_error": str(exc),
                "problem_code": "FAILED_FEEDBACK_ZIP",
                "problem_stage": "反馈包生成",
                "entries": [],
            }
        success = package.get("feedback_bundle_status") in {"PASS", "PASS_WITH_NOTES"}
        return {
            "code": 200 if success else 400,
            "status": "success" if success else "blocked",
            "success": success,
            "message": "Diagnostic feedback package exported." if success else "Diagnostic feedback package blocked.",
            "data": package,
        }

    @app.post("/api/upload")
    async def upload_file(
        file: UploadFile = File(...),
        mode: str = Form("fidelity"),
        scale: str | None = Form(None),
        output_dir: str | None = Form(None),
        output_profile: str | None = Form(None),
        output_format: str | None = Form(None),
        format: str | None = Form(None),
        color_correction_enabled: bool = Form(False),
    ):
        user_dirs = require_directory_ready()
        task_id = make_task_id()
        task_started_at = time.monotonic()
        task_start_times[task_id] = task_started_at
        mode_value = safe_mode(mode)
        current_stage = "image_task_intake"
        current_path: str | Path = file.filename or ""
        current_impact = "image_task_not_created"
        current_action = "check_runtime_log_and_retry"

        def annotate_http_failure(
            error: HTTPException,
            *,
            stage: str,
            error_category: str,
            path: str | Path,
            impact: str,
            action: str,
            phase_event: str = "",
        ) -> HTTPException:
            error.hdde_failed_stage = getattr(error, "hdde_failed_stage", stage)
            error.hdde_error_category = getattr(error, "hdde_error_category", error_category)
            error.hdde_failed_path = getattr(error, "hdde_failed_path", path)
            error.hdde_impact = getattr(error, "hdde_impact", impact)
            error.hdde_action = getattr(error, "hdde_action", action)
            error.hdde_phase_event = getattr(error, "hdde_phase_event", phase_event)
            return error

        try:
            log_runtime_event(
                "IMAGE_TASK_STARTED",
                stage=current_stage,
                result="started",
                task_id=task_id,
                purpose="4K_SIZE_ADAPTATION" if mode_value == FOUR_K_V1_MODE else "1080P_DELIVERY",
                route=mode_value,
                path=current_path,
                impact="image_task_initializing",
                action="validate_input_and_output_plan",
            )

            current_stage = "output_format_validation"
            if mode_value == FOUR_K_V1_MODE:
                if output_dir or scale is not None:
                    raise annotate_http_failure(
                        HTTPException(status_code=400, detail="4K任务不接受自定义输出目录或缩放参数。"),
                        stage="contract_validation",
                        error_category=USER_ACTION_REQUIRED,
                        path=output_dir or "",
                        impact=current_impact,
                        action="use_frozen_4k_request_contract",
                    )
                if str(output_profile or "").strip().lower() != FOUR_K_V1_OUTPUT_PROFILE:
                    raise annotate_http_failure(
                        HTTPException(status_code=400, detail="4K任务必须使用 delivery_4k_v1 输出合同。"),
                        stage="contract_validation",
                        error_category=USER_ACTION_REQUIRED,
                        path="",
                        impact=current_impact,
                        action="use_frozen_4k_request_contract",
                    )
                if str(output_format or format or "").strip().lower().lstrip(".") != "png":
                    raise annotate_http_failure(
                        HTTPException(status_code=400, detail="4K V1仅支持PNG成品。"),
                        stage="contract_validation",
                        error_category=USER_ACTION_REQUIRED,
                        path="",
                        impact=current_impact,
                        action="use_frozen_4k_request_contract",
                    )
                requested_output_format = "png"
                output_root = (Path(user_dirs["app_data_root"]) / Path(FOUR_K_V1_OUTPUT_DIRECTORY)).resolve()
                output_dir_meta = {
                    "output_dir_source": "formal_4k_contract",
                    "used_custom_output_dir": False,
                    "output_dir_created": False,
                    "output_dir_message": "使用正式目录下的4K高清增强输出目录。",
                }
            else:
                requested_output_format = parse_output_format(output_format or format or settings_data.get("default_output_format"))
                current_stage = "output_directory_validation"
                current_path = output_dir or ""
                current_action = "select_valid_output_directory"
                try:
                    output_root, output_dir_meta = resolve_output_dir(output_dir, persist_custom_selection=False)
                except HTTPException as exc:
                    annotate_http_failure(
                        exc,
                        stage=current_stage,
                        error_category=USER_ACTION_REQUIRED,
                        path=current_path,
                        impact=current_impact,
                        action=current_action,
                    )
                    raise

            current_stage = "output_directory_ready"
            current_path = output_root
            current_impact = "image_task_not_created"
            current_action = "check_runtime_log_and_retry"
            print(
                "[VisualMasterPro output_dir] upload",
                {
                    "task_id": task_id,
                    "requested_output_dir": output_dir,
                    "resolved_output_dir": str(output_root),
                    "output_dir_source": output_dir_meta.get("output_dir_source"),
                    "used_custom_output_dir": output_dir_meta.get("used_custom_output_dir"),
                },
            )

            current_stage = "input_read"
            current_path = file.filename or ""
            current_impact = "image_processing_not_started"
            current_action = "check_input_file_access"
            receive_start = time.perf_counter()
            try:
                raw = await file.read()
            except Exception as exc:
                error_category = ENVIRONMENT_ERROR if isinstance(exc, OSError) else PRODUCT_ERROR
                error = HTTPException(status_code=500, detail=f"上传图片读取失败：{exc}")
                annotate_http_failure(
                    error,
                    stage=current_stage,
                    error_category=error_category,
                    path=current_path,
                    impact=current_impact,
                    action=current_action if error_category == ENVIRONMENT_ERROR else "check_runtime_log_and_retry",
                )
                raise error from exc
            receive_file_time = round(time.perf_counter() - receive_start, 6)
            if not raw:
                current_stage = "input_validation"
                current_impact = "image_task_not_created"
                current_action = "select_non_empty_supported_image"
                error = HTTPException(status_code=400, detail="上传图片为空。")
                annotate_http_failure(
                    error,
                    stage=current_stage,
                    error_category=USER_ACTION_REQUIRED,
                    path=current_path,
                    impact=current_impact,
                    action=current_action,
                )
                raise error

            current_stage = "input_path_planning"
            upload_name = safe_upload_name(file.filename)
            saved_path = unique_input_path(upload_name)
            current_path = saved_path

            current_stage = "input_file_write"
            current_action = "check_formal_input_directory_permissions"
            save_start = time.perf_counter()
            try:
                saved_path.write_bytes(raw)
            except Exception as exc:
                error_category = ENVIRONMENT_ERROR if isinstance(exc, OSError) else PRODUCT_ERROR
                error = HTTPException(status_code=500, detail=f"正式输入目录写入失败：{exc}")
                annotate_http_failure(
                    error,
                    stage=current_stage,
                    error_category=error_category,
                    path=current_path,
                    impact=current_impact,
                    action=current_action if error_category == ENVIRONMENT_ERROR else "check_runtime_log_and_retry",
                )
                raise error from exc
            save_input_time = round(time.perf_counter() - save_start, 6)

            current_stage = "route_planning"
            current_action = "select_supported_decodable_image"
            try:
                if mode_value == FOUR_K_V1_MODE:
                    output_plan = inspect_4k_v1_source(saved_path)
                    output_plan["paths"] = {
                        "final": build_4k_v1_output_path(saved_path, user_dirs["app_data_root"])
                    }
                    output_plan["image_type"] = "alpha" if output_plan.get("has_alpha") else "opaque"
                else:
                    output_plan = build_output_plan(
                        saved_path,
                        output_root,
                        "delivery_1080p",
                        requested_output_format,
                        False,
                        mode=mode_value,
                    )
            except HTTPException as exc:
                error_category = (
                    getattr(exc, "hdde_error_category", "")
                    or (USER_ACTION_REQUIRED if 400 <= exc.status_code < 500 else PRODUCT_ERROR)
                )
                annotate_http_failure(
                    exc,
                    stage=current_stage,
                    error_category=error_category,
                    path=current_path,
                    impact=current_impact,
                    action=current_action,
                )
                raise
            except Exception as exc:
                error_category = ENVIRONMENT_ERROR if isinstance(exc, OSError) else PRODUCT_ERROR
                error = HTTPException(status_code=400, detail=f"图片解码或输出规划失败：{exc}")
                annotate_http_failure(
                    error,
                    stage=current_stage,
                    error_category=error_category,
                    path=current_path,
                    impact=current_impact,
                    action="check_file_access_and_retry" if error_category == ENVIRONMENT_ERROR else "check_runtime_log_and_retry",
                )
                raise error from exc

            log_runtime_event(
                "IMAGE_ROUTE_SELECTED",
                stage="route_planning",
                result="selected",
                task_id=task_id,
                purpose="4K_SIZE_ADAPTATION" if mode_value == FOUR_K_V1_MODE else "1080P_DELIVERY",
                route=FOUR_K_V1_ROUTE if mode_value == FOUR_K_V1_MODE else mode_value,
                path=saved_path,
                impact="image_processing_route_fixed",
                action="execute_image_pipeline",
            )

            current_stage = "task_registration"
            current_action = "check_input_file_access"
            try:
                expected_output_path = output_plan["paths"]["final"]
                input_size_bytes = saved_path.stat().st_size
                input_hash = sha256_file(saved_path)
            except Exception as exc:
                error_category = ENVIRONMENT_ERROR if isinstance(exc, OSError) else PRODUCT_ERROR
                error = HTTPException(status_code=500, detail=f"图片任务登记失败：{exc}")
                annotate_http_failure(
                    error,
                    stage=current_stage,
                    error_category=error_category,
                    path=current_path,
                    impact=current_impact,
                    action=current_action if error_category == ENVIRONMENT_ERROR else "check_runtime_log_and_retry",
                )
                raise error from exc

            created_at = datetime.now().isoformat(timespec="seconds")
            task = {
                "task_id": task_id,
                "taskId": task_id,
                "feature_key": ENHANCEMENT_4K_FEATURE_KEY if mode_value == FOUR_K_V1_MODE else ENHANCEMENT_1080P_FEATURE_KEY,
                "result_id": "",
                "task_status": "pending",
                "status": "pending",
                "task_progress": 0,
                "mode": mode_value,
                "route": FOUR_K_V1_ROUTE if mode_value == FOUR_K_V1_MODE else mode_value,
                "target_resolution": "4K" if mode_value == FOUR_K_V1_MODE else "1080P",
                "output_profile": FOUR_K_V1_OUTPUT_PROFILE if mode_value == FOUR_K_V1_MODE else output_profile or "delivery_1080p",
                "quality_capability_boundary": FOUR_K_V1_QUALITY_CAPABILITY_BOUNDARY if mode_value == FOUR_K_V1_MODE else "",
                "processing_stage": "pending",
                "processing_disposition": output_plan.get("processing_disposition") if mode_value == FOUR_K_V1_MODE else "",
                "quality_conclusion": output_plan.get("quality_conclusion") if mode_value == FOUR_K_V1_MODE else "",
                "error_code": "",
                "stage_events": [],
                "image_type": output_plan.get("image_type") or "unknown",
                "degradation_type": "unknown",
                "task_result": None,
                "task_report": empty_task_report(),
                "error_message": "",
                "created_at": created_at,
                "completed_at": None,
                "fileName": saved_path.name,
                "input_dir": str(saved_path.parent),
                "input_filename": saved_path.name,
                "original_filename": upload_name,
                "input_path": saved_path,
                "source": str(saved_path),
                "source_path": saved_path,
                "result_file": "",
                "formal_root": user_dirs["app_data_root"] if mode_value == FOUR_K_V1_MODE else "",
                "output_root": output_root,
                "output_dir": str(output_root),
                "output_directory": str(output_root),
                "output_directory_source": output_dir_meta.get("output_dir_source") or "default",
                "output_dir_meta": output_dir_meta,
                "expected_output_path": expected_output_path,
                "output_format": requested_output_format,
                "color_stability_enabled": True,
                "color_correction_enabled": bool(color_correction_enabled),
                "input_size_bytes": input_size_bytes,
                "input_hash": input_hash,
                "input_width": output_plan.get("input_width"),
                "input_height": output_plan.get("input_height"),
                "output_width": output_plan.get("output_width"),
                "output_height": output_plan.get("output_height"),
                "resize_policy": output_plan.get("resize_policy"),
                "was_upscaled": output_plan.get("was_upscaled"),
                "was_downscaled": output_plan.get("was_downscaled"),
                "scale": None if mode_value == FOUR_K_V1_MODE else parse_scale_value(scale),
                "started_at_monotonic": task_started_at,
                "debug_timing": {
                    "receive_file_time": receive_file_time,
                    "save_input_time": save_input_time,
                },
            }
            task_registry[task_id] = task
            task_registry[DEFAULT_TASK_ID] = task
            latest_task_id["value"] = task_id
            upload_file_index[saved_path.name] = saved_path
            output_file_index[expected_output_path.name] = expected_output_path
            log_runtime_event(
                "TASK_CREATED",
                stage="task_registration",
                result="success",
                feature_key=task["feature_key"],
                task_id=task_id,
                status="pending",
                impact="unified_task_available",
            )
            ensure_task_started(task)

            data = public_task(task)
            return {
                "code": 200,
                "status": "success",
                "success": True,
                "message": (
                    "图片上传完成，已开始4K高清画质增强。"
                    if mode_value == FOUR_K_V1_MODE
                    else f"图片上传完成，已登记为 {APP_VERSION} 后台处理任务。"
                ),
                "filename": saved_path.name,
                "url": data["originalUrl"],
                "task_id": task_id,
                "taskId": task_id,
                "streamEndpoint": data["streamEndpoint"],
                "data": data,
            }
        except HTTPException as exc:
            if task_id not in task_terminal_events:
                error_category = getattr(
                    exc,
                    "hdde_error_category",
                    USER_ACTION_REQUIRED if 400 <= exc.status_code < 500 else PRODUCT_ERROR,
                )
                finish_task_failure(
                    task_id,
                    started_at=task_started_at,
                    phase_event=getattr(exc, "hdde_phase_event", ""),
                    level=logging.ERROR if error_category in {ENVIRONMENT_ERROR, PRODUCT_ERROR, CONFIGURATION_ERROR} else logging.WARNING,
                    stage=getattr(exc, "hdde_failed_stage", current_stage),
                    result="blocked" if 400 <= exc.status_code < 500 else "failed",
                    error_category=error_category,
                    route=mode_value,
                    path=getattr(exc, "hdde_failed_path", current_path),
                    reason=str(exc.detail),
                    impact=getattr(exc, "hdde_impact", current_impact),
                    action=getattr(exc, "hdde_action", current_action),
                    exception=exc
                    if error_category in {ENVIRONMENT_ERROR, PRODUCT_ERROR, CONFIGURATION_ERROR}
                    else None,
                )
            raise
        except BaseException as exc:
            if task_id not in task_terminal_events:
                error_category = ENVIRONMENT_ERROR if isinstance(exc, OSError) else PRODUCT_ERROR
                finish_task_failure(
                    task_id,
                    started_at=task_started_at,
                    level=logging.ERROR,
                    stage=current_stage,
                    result="failed",
                    error_category=error_category,
                    route=mode_value,
                    path=current_path,
                    reason=str(exc),
                    impact=current_impact,
                    action=current_action if error_category == ENVIRONMENT_ERROR else "check_runtime_log_and_retry",
                    exception=exc,
                )
            raise
        finally:
            task_start_times.pop(task_id, None)

    @app.get("/api/stream")
    async def stream_latest(delay: float = 0.25):
        return StreamingResponse(
            stream_task_events(latest_task_id["value"] or DEFAULT_TASK_ID, delay),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    @app.get("/api/v1/tasks/{task_id}/stream")
    async def stream(task_id: str, delay: float = 0.25):
        return StreamingResponse(
            stream_task_events(task_id, delay),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    @app.get("/api/file/{kind}/{filename:path}")
    async def serve_file(kind: str, filename: str):
        return FileResponse(resolve_public_file(kind, filename))

    def capture_feedback_snapshot(task_id: str, source_feature: str, stage_hint: str = "") -> dict:
        feature = str(source_feature or "runtime_failure").strip()
        if feature not in RECENT_FEATURE_COVERAGE:
            raise HTTPException(status_code=400, detail="问题反馈功能来源无效。")
        normalized_task_id = str(task_id or "").strip()
        task = task_registry.get(normalized_task_id) if normalized_task_id else None
        if normalized_task_id and not task:
            raise HTTPException(status_code=404, detail="任务不存在。")
        captured_at = datetime.now().isoformat(timespec="milliseconds")
        frozen_task = copy.deepcopy(task) if task else {}
        frozen_task["source_feature"] = feature
        if not task and stage_hint:
            frozen_task["processing_stage"] = str(stage_hint)[:120]
        runtime_context = feedback_runtime_provider()
        frozen_task["runtime_context"] = runtime_context
        if task:
            error_context = task.get("error_context") if isinstance(task.get("error_context"), dict) else {}
            frozen_task["related_events"] = related_runtime_events(
                task_id=normalized_task_id,
                batch_id=str(task.get("batch_id") or ""),
                error_id=str(error_context.get("error_id") or ""),
            )
        else:
            frozen_task["related_events"] = []
        context = build_feedback_context(
            frozen_task,
            source_feature=feature,
            runtime=runtime_context,
            captured_at=captured_at,
        )
        snapshot_id = f"FCS-{uuid.uuid4().hex}"
        if len(feedback_context_snapshots) >= 64:
            feedback_context_snapshots.pop(next(iter(feedback_context_snapshots)), None)
        snapshot = {
            "snapshot_id": snapshot_id,
            "captured_at": captured_at,
            "task_id": normalized_task_id or None,
            "source_feature": feature,
            "task": frozen_task,
            "context": context,
        }
        feedback_context_snapshots[snapshot_id] = snapshot
        return snapshot

    def safe_attachment_manifest(value) -> list[dict]:
        if value in (None, ""):
            return []
        if not isinstance(value, list) or len(value) > 10:
            raise HTTPException(status_code=400, detail="反馈附件清单无效。")
        manifest: list[dict] = []
        for item in value:
            if not isinstance(item, dict) or set(item) - {"extension", "size_bytes", "selected_by_user"}:
                raise HTTPException(status_code=400, detail="反馈附件清单包含不允许的字段。")
            extension = str(item.get("extension") or "").lower()[:16]
            if extension and not re.fullmatch(r"\.[a-z0-9]{1,10}", extension):
                raise HTTPException(status_code=400, detail="反馈附件扩展名无效。")
            try:
                size_bytes = max(0, int(item.get("size_bytes") or 0))
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="反馈附件体积无效。") from exc
            manifest.append({
                "extension": extension,
                "size_bytes": size_bytes,
                "selected_by_user": bool(item.get("selected_by_user")),
            })
        return manifest

    def generate_snapshot_feedback_bundle(snapshot: dict, description: str, attachments: list[dict]) -> dict:
        user_dirs = current_user_dirs()
        if not user_dirs["directory_ready"]:
            raise HTTPException(status_code=409, detail=user_dirs["directory_message"])
        frozen_task = copy.deepcopy(snapshot["task"])
        frozen_task.update({
            "formal_root": user_dirs["app_data_root"],
            "formal_directory_available": user_dirs["directory_ready"],
            "app_version": APP_VERSION,
            "user_description": description,
        })
        context = copy.deepcopy(snapshot["context"])
        context["user_description"] = description
        artifact_identity = str(snapshot.get("task_id") or f"runtime_{runtime_id}")
        bundle = generate_feedback_bundle(
            artifact_identity,
            frozen_task,
            output_dir=Path(user_dirs["feedback_dir"]),
            context_snapshot=context,
            attachment_manifest=attachments,
        )
        bundle_status = str(bundle.get("feedback_bundle_status") or "FAIL")
        log_runtime_event(
            "FEEDBACK_REPORT_GENERATED" if bundle_status == "PASS" else "FEEDBACK_REPORT_GENERATION_FAILED",
            level=logging.INFO if bundle_status == "PASS" else logging.ERROR,
            stage="feedback_bundle_generation",
            result="success" if bundle_status == "PASS" else "failed",
            error_category="" if bundle_status == "PASS" else ENVIRONMENT_ERROR,
            feature=snapshot["source_feature"],
            task_id=str(snapshot.get("task_id") or ""),
            status=str(frozen_task.get("task_status") or frozen_task.get("status") or ""),
            error_stage="" if bundle_status == "PASS" else "feedback_bundle_generation",
            path=Path(str(bundle.get("feedback_bundle_path") or "")).name,
            runtime_log_reference="诊断/日志/hdde.log",
            reason=str(bundle.get("feedback_bundle_error") or ""),
            impact="feedback_bundle_available" if bundle_status == "PASS" else "feedback_bundle_unavailable",
            action="user_review_and_decide_whether_to_send" if bundle_status == "PASS" else "check_runtime_log_and_feedback_directory",
        )
        return bundle

    @app.post("/api/v1/feedback/context-snapshot")
    async def unified_feedback_context_snapshot(payload: dict = Body(default_factory=dict)):
        allowed_fields = {"task_id", "source_feature", "stage"}
        unknown_fields = sorted(str(key) for key in payload if key not in allowed_fields)
        if unknown_fields:
            raise HTTPException(status_code=400, detail=f"问题反馈上下文包含未知字段：{', '.join(unknown_fields)}。")
        snapshot = capture_feedback_snapshot(
            str(payload.get("task_id") or ""),
            str(payload.get("source_feature") or "runtime_failure"),
            str(payload.get("stage") or ""),
        )
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "data": {
                "snapshot_id": snapshot["snapshot_id"],
                "context_captured_at": snapshot["captured_at"],
                "context": snapshot["context"],
                "context_preview": feedback_context_preview(snapshot["context"]),
            },
        }

    @app.post("/api/v1/feedback/bundle")
    async def unified_feedback_bundle(payload: dict = Body(default_factory=dict)):
        allowed_fields = {"snapshot_id", "description", "attachment_manifest"}
        unknown_fields = sorted(str(key) for key in payload if key not in allowed_fields)
        if unknown_fields:
            raise HTTPException(status_code=400, detail=f"问题反馈请求包含未知字段：{', '.join(unknown_fields)}。")
        snapshot_id = str(payload.get("snapshot_id") or "").strip()
        snapshot = feedback_context_snapshots.get(snapshot_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail="问题反馈上下文快照不存在或已失效，请重新打开反馈窗口。")
        description = str(payload.get("description") or "").strip()
        if not description:
            raise HTTPException(status_code=400, detail="请描述你做了什么、发生了什么以及预期结果。")
        if len(description) > 1000:
            raise HTTPException(status_code=400, detail="问题描述不得超过1000个字符。")
        bundle = generate_snapshot_feedback_bundle(
            snapshot,
            description,
            safe_attachment_manifest(payload.get("attachment_manifest")),
        )
        return {
            "code": 200 if bundle["feedback_bundle_status"] == "PASS" else 500,
            "status": "success" if bundle["feedback_bundle_status"] == "PASS" else "error",
            "success": bundle["feedback_bundle_status"] == "PASS",
            "data": bundle,
        }

    @app.post("/api/v1/tasks/{task_id}/feedback-bundle")
    async def feedback_bundle(task_id: str, payload: dict = Body(default_factory=dict)):
        allowed_fields = {"source_feature", "description"}
        unknown_fields = sorted(str(key) for key in payload if key not in allowed_fields)
        if unknown_fields:
            raise HTTPException(status_code=400, detail=f"问题反馈请求包含未知字段：{', '.join(unknown_fields)}。")
        real_task_id = latest_task_id["value"] if task_id == DEFAULT_TASK_ID else task_id
        snapshot = capture_feedback_snapshot(
            str(real_task_id or ""),
            str(payload.get("source_feature") or "processing_center"),
        )
        bundle = generate_snapshot_feedback_bundle(snapshot, str(payload.get("description") or "").strip(), [])
        task = task_registry.get(str(real_task_id or ""))
        if task:
            task.update(bundle)
        return {
            "code": 200 if bundle["feedback_bundle_status"] == "PASS" else 500,
            "status": "success" if bundle["feedback_bundle_status"] == "PASS" else "error",
            "success": bundle["feedback_bundle_status"] == "PASS",
            "data": bundle,
        }

    @app.get("/api/v1/tasks/{task_id}/feedback-bundle")
    async def feedback_bundle_get(task_id: str):
        return await feedback_bundle(task_id, {})

    @app.get("/api/v1/tasks")
    async def task_list():
        unique_tasks: dict[str, dict] = {}
        for task in task_registry.values():
            task_identifier = str(task.get("task_id") or "").strip()
            if task_identifier:
                unique_tasks[task_identifier] = task
        ordered_tasks = sorted(
            unique_tasks.values(),
            key=lambda item: str(item.get("created_at") or item.get("updated_at") or ""),
            reverse=True,
        )
        tasks = [public_task(task) for task in ordered_tasks]
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "data": {"tasks": tasks, "count": len(tasks)},
        }

    @app.get("/api/v1/tasks/{task_id}")
    async def task_status(task_id: str):
        real_task_id = latest_task_id["value"] if task_id == DEFAULT_TASK_ID else task_id
        task = task_registry.get(real_task_id or "")
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在。")
        return {"code": 200, "status": "success", "success": True, "data": public_task(task)}

    @app.get("/api/v1/tasks/{task_id}/result-file")
    async def task_result_file(task_id: str):
        task = task_registry.get(str(task_id or ""))
        raw_path = task.get("result_file") or task.get("output_path") if task else ""
        if not task or not task.get("result_id") or not raw_path:
            raise HTTPException(status_code=404, detail="当前任务没有可打开的正式结果。")
        result_path = resolve_migrated_formal_output_path(str(raw_path), current_user_dirs()["app_data_root"])
        formal_output_root = (Path(current_user_dirs()["app_data_root"]).resolve() / OUTPUT_ROOT_RELATIVE).resolve()
        if formal_output_root not in result_path.parents or not result_path.is_file():
            raise HTTPException(status_code=404, detail="正式结果文件不存在或不在正式输出目录中。")
        return FileResponse(result_path, headers={"Cache-Control": "private, no-store"})

    log_runtime_event(
        "APPLICATION_STARTUP_COMPLETED",
        stage="application_startup",
        result="success" if initial_user_dirs["directory_ready"] else "degraded",
        product_version=APP_VERSION,
        build_id=build_identity["build_id"] or "unavailable",
        runtime_id=runtime_id,
        backend_ready=True,
        directory_ready=initial_user_dirs["directory_ready"],
        file_logging=bool(logging_initialization.get("initialized")),
        logging_ready=bool(logging_initialization.get("initialized")),
        path=logging_initialization.get("path") or "",
        impact="backend_ready" if initial_user_dirs["directory_ready"] else "directory_dependent_operations_blocked",
        action="none" if initial_user_dirs["directory_ready"] else "select_valid_formal_directory",
    )
    return app


def run_server(host: str = SERVER_HOST, port: int = SERVER_PORT, debug: bool = False) -> int:
    import uvicorn

    print(f"{APP_VERSION} Web API 服务启动中...")
    print(f"监听地址：http://{host}:{port}")
    print("上传接口：POST /api/upload")
    print(f"SSE接口：GET /api/v1/tasks/{DEFAULT_TASK_ID}/stream")
    try:
        app = build_web_app(runtime_host=host, runtime_port=port)
        uvicorn.run(app, host=host, port=port, log_level="debug" if debug else "info")
    except Exception as exc:
        dependency_failure = isinstance(exc, ImportError) or isinstance(exc.__cause__, ImportError)
        log_runtime_event(
            "APPLICATION_STARTUP_FAILED",
            level=logging.ERROR,
            stage="dependency_import" if dependency_failure else "web_server_startup",
            result="failed",
            error_category=CONFIGURATION_ERROR if dependency_failure else PRODUCT_ERROR,
            reason=str(exc),
            impact="backend_not_available",
            action="install_required_dependencies" if dependency_failure else "check_runtime_log_and_server_configuration",
            product_version=APP_VERSION,
            exception=exc,
        )
        raise
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="VisualMasterPro",
        description=f"VisualMasterPro {APP_VERSION} 1080P 稳定交付系统。",
    )
    parser.add_argument("input_path", nargs="?", help="兼容旧命令的输入图片或文件夹。")
    parser.add_argument("output_dir", nargs="?", help="兼容旧命令的输出文件夹。")
    parser.add_argument("--input", dest="input_option", help="输入图片或图片文件夹。")
    parser.add_argument("--output", dest="output_option", help="输出文件夹。")
    parser.add_argument("--gui", action="store_true", help=f"启动 VisualMasterPro {APP_VERSION} 图形化界面。")
    parser.add_argument("--server", action="store_true", help="启动 Web API 服务，监听 http://localhost:8787。")
    parser.add_argument("--host", default=SERVER_HOST, help="Web API 监听主机，默认 localhost。")
    parser.add_argument("--port", type=int, default=SERVER_PORT, help="Web API 监听端口，默认 8787。")
    parser.add_argument("--mode", default=AUTO_MODE, choices=SUPPORTED_MODES, help="增强模式，默认 fidelity。")
    parser.add_argument("--report", default=None, choices=["both", "json", "md", "markdown", "none"], help="调试报告格式。")
    parser.add_argument("--scale", type=int, default=2, choices=[2, 4], help="放大倍率，默认 2。")
    parser.add_argument("--format", dest="output_format", default="png", choices=["png", "jpg", "jpeg"], help="输出格式，默认 png。")
    parser.add_argument("--debug", action="store_true", help="输出开发调试文件。")
    parser.add_argument("--developer", action="store_true", help="等同于 --debug。")
    parser.add_argument("--pause", action="store_true", help="退出前暂停，适合 EXE 双击调试。")
    return parser


def resolve_paths(args):
    input_value = args.input_option or args.input_path
    output_value = args.output_option or args.output_dir
    if input_value and output_value:
        return Path(input_value), Path(output_value)
    if not input_value and not output_value:
        return get_desktop_work_dirs()
    raise ValueError("input and output must be provided together.")


def run(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv and not is_pyinstaller():
        from runtime.formal_launcher import PROJECT_PYTHON, main as run_formal_launcher

        if Path(sys.executable).resolve() == PROJECT_PYTHON.resolve():
            return run_formal_launcher([])
        if not PROJECT_PYTHON.is_file():
            raise RuntimeError(f"项目运行环境不存在：{PROJECT_PYTHON}")
        return subprocess.call(
            [str(PROJECT_PYTHON), "-m", "runtime.formal_launcher"],
            cwd=str(PROJECT_ROOT),
        )

    if is_pyinstaller() and not argv:
        from gui.app import run_gui

        return run_gui()

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.server:
        from runtime.formal_launcher import PROJECT_PYTHON

        if Path(sys.executable).resolve() != PROJECT_PYTHON.resolve():
            if not PROJECT_PYTHON.is_file():
                raise RuntimeError(f"项目运行环境不存在：{PROJECT_PYTHON}")
            return subprocess.call(
                [str(PROJECT_PYTHON), str(PROJECT_ROOT / "main.py"), *argv],
                cwd=str(PROJECT_ROOT),
            )

    if args.gui:
        from gui.app import run_gui

        return run_gui()

    if args.server:
        return run_server(host=args.host, port=args.port, debug=args.debug)

    try:
        input_path, output_dir = resolve_paths(args)
    except ValueError as exc:
        parser.error(str(exc))

    print(f"{APP_VERSION}（雪原Ai增强引擎）")
    print("-----------------------------------")
    developer_mode = args.debug or args.developer
    report_format = args.report or ("both" if developer_mode else "none")
    print(f"请求模式：{args.mode}")
    print(f"报告格式：{report_format}")
    print(f"放大倍率：{args.scale}x")
    print(f"输出格式：{args.output_format}")
    print(f"输入位置：{input_path}")
    print(f"输出位置：{output_dir}")

    startup_status = run_startup_check(
        input_path=input_path,
        output_dir=output_dir,
        show_no_image_dialog=True,
    )
    if startup_status.input_path.is_dir() and not any(startup_status.input_path.iterdir()):
        print("未检测到待处理图片，已安全退出。")
        return 0

    if args.mode in {"fidelity", "text_safe", "ai_image_clean", "sharp_4k"}:
        from batch.batch_processor import process_batch

        results = process_batch(
            [input_path],
            output_dir,
            mode=args.mode,
            scale=args.scale,
            output_format=args.output_format,
            debug_output=developer_mode,
        )
        if not results:
            message = (
                "未检测到待处理图片。\n\n"
                "请将图片放入“输入图片”文件夹后重新运行。\n\n"
                f"输入图片目录：{input_path}\n"
                f"输出目录：{output_dir / 'images'}"
            )
            print(message)
            show_info_dialog("VisualMasterPro 提示", message)
            return 0
        for result in results:
            print(f"{'完成' if result.ok else '失败'}：{result.output or result.source}，{result.message}")
        return 0

    from engine.pipeline import process_path

    results = process_path(
        input_path=input_path,
        output_dir=output_dir,
        mode=args.mode,
        report=report_format,
        developer_mode=developer_mode,
    )

    if not results:
        message = (
            "未检测到待处理图片。\n\n"
            "请将图片放入“输入图片”文件夹后重新运行。\n\n"
            f"输入图片目录：{input_path}\n"
            f"输出目录：{output_dir / 'images'}"
        )
        print(message)
        show_info_dialog("VisualMasterPro 提示", message)
        return 0

    for result in results:
        if result.ok:
            print(f"完成：{result.output}")
            print(f"尺寸：{result.width}x{result.height}")
            print(f"使用模式：{result.mode}")
        else:
            print(f"跳过：{result.source}，原因：{result.message}")

    print("全部处理完成。")
    if args.pause:
        input("按回车键退出...")
    return 0


if __name__ == "__main__":
    install_global_exception_hook()
    try:
        raise SystemExit(run(sys.argv[1:]))
    except Exception as exc:
        raise SystemExit(handle_exception(exc))
