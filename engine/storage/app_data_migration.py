from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


TARGET_PATHS = {
    "standard_output": Path("输出") / "1080P画质",
    "safe_output": Path("输出") / "1080P画质",
    "four_k_output": Path("输出") / "4K画质增强",
    "compression_output": Path("输出") / "图片压缩",
    "local_retouch_output": Path("输出") / "瑕疵修复",
    "standard_input_cache": Path("输出") / "1080P画质" / ".输入缓存",
    "safe_input_cache": Path("输出") / "1080P画质" / ".输入缓存",
    "compression_runtime_cache": Path("输出") / "图片压缩" / ".运行缓存",
    "log_dir": Path("诊断") / "日志",
    "feedback_dir": Path("诊断") / "反馈包",
    "safe_feedback_dir": Path("诊断") / "反馈包" / "1080P画质",
    "report_dir": Path("诊断") / "报告",
}

LEGACY_DIRECTORY_TARGETS = {
    "图片压缩输出": ("ACTIVE_MIGRATE", TARGET_PATHS["compression_output"]),
    "1080P安全增强输出": ("ACTIVE_MIGRATE", TARGET_PATHS["safe_output"]),
    "输出成品": ("ACTIVE_MIGRATE", TARGET_PATHS["standard_output"]),
    "输入": ("ACTIVE_MIGRATE", TARGET_PATHS["standard_input_cache"]),
    "输入图片": ("ACTIVE_MIGRATE", TARGET_PATHS["standard_input_cache"]),
    "beta_uploads": ("ACTIVE_MIGRATE", TARGET_PATHS["safe_input_cache"]),
    "1080P安全增强输入": ("ACTIVE_MIGRATE", TARGET_PATHS["safe_input_cache"]),
    "临时": ("ACTIVE_MIGRATE", TARGET_PATHS["compression_runtime_cache"]),
    "报告": ("DIAGNOSTIC_MIGRATE", TARGET_PATHS["report_dir"]),
    "反馈包": ("DIAGNOSTIC_MIGRATE", TARGET_PATHS["feedback_dir"]),
    "影界测试反馈包": ("DIAGNOSTIC_MIGRATE", TARGET_PATHS["safe_feedback_dir"]),
    "交付包": ("DIAGNOSTIC_MIGRATE", TARGET_PATHS["feedback_dir"]),
}

LEGACY_RELATIVE_DIRECTORY_TARGETS = {
    Path("诊断") / "反馈包" / "交付包": TARGET_PATHS["feedback_dir"],
    Path("诊断") / "反馈包" / "1080P安全增强": TARGET_PATHS["safe_feedback_dir"],
    Path("输出") / "4K尺寸适配": TARGET_PATHS["four_k_output"],
    Path("输出") / "4K适配": TARGET_PATHS["four_k_output"],
    Path("输出") / "4K增强": TARGET_PATHS["four_k_output"],
    Path("输出") / "4K画质": TARGET_PATHS["four_k_output"],
    Path("输出") / "4K画质适配": TARGET_PATHS["four_k_output"],
    Path("输出") / "4K高清增强": TARGET_PATHS["four_k_output"],
    Path("输出") / "1080P画质增强": TARGET_PATHS["standard_output"],
    Path("输出") / "1080P标准增强": TARGET_PATHS["standard_output"],
    Path("输出") / "1080P安全增强": TARGET_PATHS["standard_output"],
    Path("输出") / "1080P增强": TARGET_PATHS["standard_output"],
    Path("输出") / "1080P标准版": TARGET_PATHS["standard_output"],
    Path("输出") / "标记修整": TARGET_PATHS["local_retouch_output"],
    Path("输出") / "瑕疵修整": TARGET_PATHS["local_retouch_output"],
    Path("输出") / "局部修整": TARGET_PATHS["local_retouch_output"],
    Path("输出") / "局部修复": TARGET_PATHS["local_retouch_output"],
}

LEGACY_FORMAL_OUTPUT_ALIASES = {
    Path("输出") / "4K尺寸适配": TARGET_PATHS["four_k_output"],
    Path("输出") / "4K适配": TARGET_PATHS["four_k_output"],
    Path("输出") / "4K增强": TARGET_PATHS["four_k_output"],
    Path("输出") / "4K画质": TARGET_PATHS["four_k_output"],
    Path("输出") / "4K画质适配": TARGET_PATHS["four_k_output"],
    Path("输出") / "4K高清增强": TARGET_PATHS["four_k_output"],
    Path("输出") / "1080P画质增强": TARGET_PATHS["standard_output"],
    Path("输出") / "1080P标准增强": TARGET_PATHS["standard_output"],
    Path("输出") / "1080P安全增强": TARGET_PATHS["standard_output"],
    Path("输出") / "1080P增强": TARGET_PATHS["standard_output"],
    Path("输出") / "1080P标准版": TARGET_PATHS["standard_output"],
    Path("输出") / "标记修整": TARGET_PATHS["local_retouch_output"],
    Path("输出") / "瑕疵修整": TARGET_PATHS["local_retouch_output"],
    Path("输出") / "局部修整": TARGET_PATHS["local_retouch_output"],
    Path("输出") / "局部修复": TARGET_PATHS["local_retouch_output"],
}

CLEANUP_ONLY_NAMES = {"配置"}
POTENTIAL_HISTORY_NAMES = {"黄金测试集", "真实业务测试_6张"}
TARGET_TOP_LEVEL_NAMES = {"输出", "诊断", "历史保留"}
STANDARD_OUTPUT_RESERVED_NAMES = {
    TARGET_PATHS["standard_output"].name,
    TARGET_PATHS["safe_output"].name,
    TARGET_PATHS["compression_output"].name,
    TARGET_PATHS["four_k_output"].name,
    TARGET_PATHS["local_retouch_output"].name,
    *(path.name for path in LEGACY_FORMAL_OUTPUT_ALIASES),
}


def resolve_migrated_formal_output_path(path: str | Path, formal_root: str | Path) -> Path:
    """Resolve a moved formal file without rewriting the historical record that named it."""

    candidate = Path(path).expanduser()
    root = Path(formal_root).expanduser().resolve()
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError):
        resolved = candidate.absolute()
    if resolved.exists():
        return resolved
    for legacy_relative, current_relative in LEGACY_FORMAL_OUTPUT_ALIASES.items():
        legacy_root = (root / legacy_relative).resolve()
        try:
            relative = resolved.relative_to(legacy_root)
        except ValueError:
            continue
        migrated = (root / current_relative / relative).resolve()
        if migrated.exists():
            return migrated
    return resolved


def _path_key(path: Path) -> str:
    try:
        value = path.resolve()
    except Exception:
        value = path.absolute()
    return os.path.normcase(str(value))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_count(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return 1
    return sum(1 for item in path.rglob("*") if item.is_file())


def _directory_empty(path: Path) -> bool:
    return path.is_dir() and not any(path.iterdir())


def _unique_conflict_path(path: Path) -> Path:
    index = 1
    while True:
        candidate = path.with_name(f"{path.stem}_迁移_{index:03d}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _copy_verified_then_remove(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.hdde-migrate-{uuid.uuid4().hex}.tmp"
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        if source.stat().st_size != temporary.stat().st_size:
            raise OSError("迁移临时文件大小校验失败。")
        try:
            source_sha256 = _sha256(source)
        except Exception as exc:
            raise _MigrationOperationError("hash", source, exc) from exc
        try:
            temporary_sha256 = _sha256(temporary)
        except Exception as exc:
            raise _MigrationOperationError("hash", temporary, exc) from exc
        if source_sha256 != temporary_sha256:
            raise _MigrationOperationError(
                "hash",
                temporary,
                OSError("迁移临时文件SHA256校验失败。"),
            )
        os.replace(temporary, destination)
        source.unlink()
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except Exception:
            pass
        raise


class _MigrationOperationError(RuntimeError):
    def __init__(self, stage: str, path: Path, original: Exception):
        super().__init__(str(original))
        self.stage = stage
        self.path = Path(path)
        self.original = original


def _ensure_directory(path: Path, created_directories: list[Path]) -> None:
    missing: list[Path] = []
    cursor = path
    try:
        while not cursor.exists() and cursor != cursor.parent:
            missing.append(cursor)
            cursor = cursor.parent
        path.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise _MigrationOperationError("mkdir", path, exc) from exc
    for directory in reversed(missing):
        if directory.is_dir() and directory not in created_directories:
            created_directories.append(directory)


def _rollback_moved_items(
    moved_items: list[tuple[Path, Path]],
    created_directories: list[Path],
    result: dict[str, Any],
) -> None:
    failure: tuple[Path, Exception] | None = None
    for source, target in reversed(moved_items):
        if not target.exists():
            continue
        try:
            source.parent.mkdir(parents=True, exist_ok=True)
            if source.exists():
                raise FileExistsError(f"rollback source already exists: {source}")
            target.replace(source)
        except Exception as exc:
            if failure is None:
                failure = (target, exc)
    for directory in reversed(created_directories):
        try:
            if directory.is_dir() and _directory_empty(directory):
                directory.rmdir()
        except Exception as exc:
            if failure is None:
                failure = (directory, exc)
    if failure is None:
        result["rollback_status"] = "SUCCESS"
        result["action_taken"] = "ROLLED_BACK"
        result["migrated_files"] = 0
        result["migrated_directories"] = 0
        return
    failure_path, exc = failure
    result["rollback_status"] = "FAILED"
    result["rollback_failure_path"] = str(failure_path)
    result["rollback_exception_type"] = type(exc).__name__
    result["rollback_reason"] = str(exc)
    result["action_taken"] = "ROLLBACK_FAILED"


def _block_result(
    result: dict[str, Any],
    *,
    stage: str,
    path: Path,
    exc: Exception,
    moved_items: list[tuple[Path, Path]],
    created_directories: list[Path],
) -> dict[str, Any]:
    original = exc.original if isinstance(exc, _MigrationOperationError) else exc
    result.update(
        {
            "status": "BLOCKED",
            "stage": stage,
            "path": str(path),
            "exception_type": type(original).__name__,
            "reason": str(original),
            "action_taken": "STOPPED",
        }
    )
    result["failures"].append(
        {
            "stage": stage,
            "path": str(path),
            "exception_type": type(original).__name__,
            "reason": str(original),
        }
    )
    if moved_items:
        _rollback_moved_items(moved_items, created_directories, result)
    else:
        result["rollback_status"] = "NOT_REQUIRED"
        result["action_taken"] = "KEPT_IN_PLACE"
        for directory in reversed(created_directories):
            try:
                if directory.is_dir() and _directory_empty(directory):
                    directory.rmdir()
            except Exception:
                pass
    return result


def _move_file(
    source: Path,
    destination: Path,
    result: dict[str, Any],
    moved_items: list[tuple[Path, Path]],
    created_directories: list[Path],
) -> Path:
    _ensure_directory(destination.parent, created_directories)
    target = destination
    if target.exists():
        if not target.is_file():
            raise _MigrationOperationError(
                "collision",
                target,
                FileExistsError(f"NAME_COLLISION: target is not a file: {target}"),
            )
        else:
            try:
                source_sha256 = _sha256(source)
                target_sha256 = _sha256(target)
            except Exception as exc:
                raise _MigrationOperationError("hash", source, exc) from exc
            if source_sha256 == target_sha256:
                backup = target.parent / f".{source.name}.hdde-dedup-{uuid.uuid4().hex}.tmp"
                try:
                    source.replace(backup)
                except Exception as exc:
                    raise _MigrationOperationError("move", source, exc) from exc
                moved_items.append((source, backup))
                result["moved_items"].append({"source": str(source), "target": str(backup)})
                result["_deduplication_backups"].append(str(backup))
                result["deduplicated_files"] += 1
                result["migrated_files"] += 1
                return target
            else:
                raise _MigrationOperationError(
                    "collision",
                    target,
                    FileExistsError(f"NAME_COLLISION: different content already exists: {target}"),
                )

    try:
        if source.drive.lower() == target.drive.lower() and not target.exists():
            try:
                source.replace(target)
            except OSError:
                _copy_verified_then_remove(source, target)
        else:
            _copy_verified_then_remove(source, target)
    except _MigrationOperationError:
        raise
    except Exception as exc:
        raise _MigrationOperationError("move", source, exc) from exc
    moved_items.append((source, target))
    result["moved_items"].append({"source": str(source), "target": str(target)})
    result["migrated_files"] += 1
    return target


def _merge_directory(
    source: Path,
    destination: Path,
    result: dict[str, Any],
    moved_items: list[tuple[Path, Path]],
    created_directories: list[Path],
) -> None:
    try:
        if not source.exists():
            return
        if not source.is_dir():
            raise NotADirectoryError(str(source))
        items = sorted(source.rglob("*"), key=lambda value: (len(value.parts), str(value)))
    except Exception as exc:
        raise _MigrationOperationError("enumerate", source, exc) from exc

    _ensure_directory(destination, created_directories)
    for item in items:
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            _ensure_directory(target, created_directories)
        elif item.is_file():
            _move_file(item, target, result, moved_items, created_directories)

    try:
        directories = sorted(
            (item for item in source.rglob("*") if item.is_dir()),
            key=lambda value: len(value.parts),
            reverse=True,
        )
        for directory in directories:
            if _directory_empty(directory):
                directory.rmdir()
        if _directory_empty(source):
            source.rmdir()
            result["deleted_empty_directories"].append(str(source))
            result["migrated_directories"] += 1
        else:
            raise OSError("legacy source remains non-empty after migration")
    except Exception as exc:
        raise _MigrationOperationError("move", source, exc) from exc


def _classify_inventory(root: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), key=lambda value: value.name):
        if path.is_file():
            inventory.append({"path": str(path), "name": path.name, "type": "ROOT_FILE", "classification": "KEEP_IN_PLACE", "files": 1})
            continue
        if not path.is_dir():
            inventory.append({"path": str(path), "name": path.name, "type": "OTHER", "classification": "KEEP_IN_PLACE", "files": 0})
            continue
        files = _file_count(path)
        if path.name == "输出":
            classification = "ACTIVE_MIGRATE"
        elif path.name == "诊断":
            classification = "DIAGNOSTIC_MIGRATE"
        elif path.name in LEGACY_DIRECTORY_TARGETS:
            classification = LEGACY_DIRECTORY_TARGETS[path.name][0]
        elif path.name in CLEANUP_ONLY_NAMES and files == 0 and _directory_empty(path):
            classification = "DELETE_EMPTY"
        elif path.name in POTENTIAL_HISTORY_NAMES:
            classification = "DELETE_EMPTY" if files == 0 and _directory_empty(path) else "KEEP_IN_PLACE"
        elif files == 0 and _directory_empty(path):
            classification = "KEEP_IN_PLACE"
        else:
            classification = "KEEP_IN_PLACE"
        inventory.append({"path": str(path), "name": path.name, "type": "DIRECTORY", "classification": classification, "files": files})
    return inventory


def _known_settings_updates(settings: dict[str, Any], root: Path, project_root: Path | None) -> dict[str, str]:
    standard = root / TARGET_PATHS["standard_output"]
    safe = root / TARGET_PATHS["safe_output"]
    compression = root / TARGET_PATHS["compression_output"]
    feedback = root / TARGET_PATHS["feedback_dir"]
    reports = root / TARGET_PATHS["report_dir"]
    mappings: dict[str, dict[str, Path]] = {
        "default_output_dir": {
            _path_key(root / "输出"): standard,
            _path_key(root / "输出成品"): standard,
            **{
                _path_key(root / legacy): standard
                for legacy in LEGACY_FORMAL_OUTPUT_ALIASES
                if legacy.parts[1].startswith("1080P")
            },
            _path_key(root / "输出" / "1080P标准版"): standard,
        },
        "last_output_dir": {
            _path_key(root / "输出"): standard,
            _path_key(root / "输出成品"): standard,
            **{
                _path_key(root / legacy): standard
                for legacy in LEGACY_FORMAL_OUTPUT_ALIASES
                if legacy.parts[1].startswith("1080P")
            },
            _path_key(root / "输出" / "1080P标准版"): standard,
            _path_key(root / "1080P安全增强输出"): safe,
            _path_key(root / "图片压缩输出"): compression,
        },
        "image_compression_default_output_root": {
            _path_key(root / "图片压缩输出"): compression,
        },
        "safe_beta_output_dir": {
            _path_key(root / "1080P安全增强输出"): safe,
            _path_key(root / "输出" / "1080P安全增强"): safe,
            _path_key(root / "输出" / "1080P标准增强"): safe,
        },
        "feedback_dir": {
            _path_key(root / "反馈包"): feedback,
            _path_key(root / "影界测试反馈包"): root / TARGET_PATHS["safe_feedback_dir"],
        },
        "report_dir": {
            _path_key(root / "报告"): reports,
        },
    }
    if project_root is not None:
        legacy_tmp_output = project_root / "tmp" / "runtime_data" / "影界HDDE" / "输出"
        mappings["default_output_dir"][_path_key(legacy_tmp_output)] = standard

    updates: dict[str, str] = {}
    for field, field_mappings in mappings.items():
        raw_value = settings.get(field)
        if not isinstance(raw_value, str) or not raw_value.strip():
            continue
        try:
            mapped = field_mappings.get(_path_key(Path(raw_value).expanduser()))
        except Exception:
            mapped = None
        if mapped is not None and _path_key(Path(raw_value).expanduser()) != _path_key(mapped):
            updates[field] = str(mapped)
    return updates


def _write_settings(settings_path: Path, payload: dict[str, Any]) -> None:
    temporary = settings_path.with_name(f".{settings_path.name}.hdde-migrate-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, settings_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _verify_writable(path: Path) -> tuple[bool, str]:
    probe = path / f".hdde_migration_probe_{uuid.uuid4().hex}.tmp"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"ok")
        probe.unlink()
        return True, ""
    except Exception as exc:
        try:
            probe.unlink(missing_ok=True)
        except Exception:
            pass
        return False, str(exc)


def _persist_settings(
    settings_path: Path | None,
    settings_writer: Callable[[dict[str, Any]], Any] | None,
    payload: dict[str, Any],
) -> None:
    if settings_writer is not None:
        settings_writer(payload)
    elif settings_path is not None:
        _write_settings(settings_path, payload)
    else:
        raise RuntimeError("Settings迁移缺少安全写入器。")


def _commit_migration(
    result: dict[str, Any],
    settings: dict[str, Any],
    settings_snapshot: dict[str, Any],
    settings_path: Path | None,
    settings_writer: Callable[[dict[str, Any]], Any] | None,
) -> None:
    updates = result.get("_pending_settings_changes") or {}
    updated_settings = copy.deepcopy(settings_snapshot)
    updated_settings.update(updates)
    if updates:
        try:
            _persist_settings(settings_path, settings_writer, updated_settings)
        except Exception as exc:
            raise _MigrationOperationError("move", settings_path or Path("settings"), exc) from exc
    try:
        for backup_value in result.get("_deduplication_backups") or []:
            Path(backup_value).unlink(missing_ok=True)
    except Exception as exc:
        raise _MigrationOperationError("move", Path(backup_value), exc) from exc
    if updates:
        settings.clear()
        settings.update(updated_settings)
        result["settings_changes"] = dict(updates)


def run_app_data_migration(
    root: Path,
    settings: dict[str, Any],
    *,
    settings_path: Path | None = None,
    settings_writer: Callable[[dict[str, Any]], Any] | None = None,
    project_root: Path | None = None,
    _defer_commit: bool = False,
) -> dict[str, Any]:
    root = Path(root)
    settings_path = Path(settings_path) if settings_path is not None else None
    settings_snapshot = copy.deepcopy(settings)
    moved_items: list[tuple[Path, Path]] = []
    created_directories: list[Path] = []
    commit_started = False
    result: dict[str, Any] = {
        "status": "NO_OP",
        "root": str(root),
        "inventory": [],
        "migrated_files": 0,
        "migrated_directories": 0,
        "deduplicated_files": 0,
        "renamed_conflicts": [],
        "deleted_empty_directories": [],
        "archived": [],
        "kept_in_place": [],
        "failures": [],
        "settings_changes": {},
        "migration_records": [],
        "moved_items": [],
        "stage": "",
        "path": "",
        "exception_type": "",
        "reason": "",
        "action_taken": "NONE",
        "rollback_status": "NOT_REQUIRED",
        "rollback_failure_path": "",
        "rollback_exception_type": "",
        "rollback_reason": "",
        "_moved_items": moved_items,
        "_created_directories": created_directories,
        "_deduplication_backups": [],
        "_pending_settings_changes": {},
    }
    try:
        if not root.exists() or not root.is_dir():
            raise _MigrationOperationError("enumerate", root, FileNotFoundError("正式根目录不存在或不是目录。"))

        settings_updates = _known_settings_updates(settings, root, project_root)
        legacy_paths = [root / name for name in LEGACY_DIRECTORY_TARGETS]
        legacy_paths.extend(root / relative for relative in LEGACY_RELATIVE_DIRECTORY_TARGETS)
        cleanup_paths = [root / name for name in CLEANUP_ONLY_NAMES | POTENTIAL_HISTORY_NAMES]
        output_root = root / "输出"
        direct_unknown_output_items: list[Path] = []
        if output_root.is_dir():
            direct_unknown_output_items = [
                item for item in output_root.iterdir() if item.name not in STANDARD_OUTPUT_RESERVED_NAMES
            ]
        missing_targets = [root / relative for relative in TARGET_PATHS.values() if not (root / relative).is_dir()]
        cleanup_needed = any(path.exists() and _directory_empty(path) for path in cleanup_paths)
        legacy_existing = [path for path in legacy_paths if path.exists()]
        result["inventory"] = _classify_inventory(root)
    except _MigrationOperationError as exc:
        return _block_result(
            result,
            stage=exc.stage,
            path=exc.path,
            exc=exc,
            moved_items=moved_items,
            created_directories=created_directories,
        )
    except Exception as exc:
        return _block_result(
            result,
            stage="enumerate",
            path=root,
            exc=exc,
            moved_items=moved_items,
            created_directories=created_directories,
        )

    for item in result["inventory"]:
        if item["classification"] == "KEEP_IN_PLACE":
            result["kept_in_place"].append(
                {
                    "source_path": item["path"],
                    "classification": "UNKNOWN",
                    "result": "KEEP_IN_PLACE",
                    "reason": "UNRECOGNIZED_LEGACY_CONTENT",
                }
            )
    for item in direct_unknown_output_items:
        record = {
            "source_path": str(item),
            "classification": "UNKNOWN",
            "result": "KEEP_IN_PLACE",
            "reason": "UNRECOGNIZED_LEGACY_CONTENT",
        }
        result["kept_in_place"].append(record)
        result["migration_records"].append(record)

    pending = bool(legacy_existing) or cleanup_needed or bool(settings_updates) or bool(missing_targets)
    if not pending:
        return result

    result["status"] = "APPLIED"
    result["action_taken"] = "MIGRATED"
    result["_pending_settings_changes"] = dict(settings_updates)
    try:
        _ensure_directory(root / "输出", created_directories)
        _ensure_directory(root / "诊断", created_directories)

        for legacy_name, (classification, target_relative) in LEGACY_DIRECTORY_TARGETS.items():
            source = root / legacy_name
            if source.exists():
                _merge_directory(source, root / target_relative, result, moved_items, created_directories)
                result["migration_records"].append(
                    {
                        "source_path": str(source),
                        "classification": classification,
                        "result": "MIGRATED",
                        "target_path": str(root / target_relative),
                    }
                )

        for source_relative, target_relative in LEGACY_RELATIVE_DIRECTORY_TARGETS.items():
            source = root / source_relative
            if source.exists():
                _merge_directory(source, root / target_relative, result, moved_items, created_directories)
                result["migration_records"].append(
                    {
                        "source_path": str(source),
                        "classification": "DIAGNOSTIC_MIGRATE",
                        "result": "MIGRATED",
                        "target_path": str(root / target_relative),
                    }
                )

        for name in sorted(CLEANUP_ONLY_NAMES | POTENTIAL_HISTORY_NAMES):
            path = root / name
            if not path.exists():
                continue
            if _directory_empty(path):
                path.rmdir()
                result["deleted_empty_directories"].append(str(path))
            elif not any(item.get("source_path") == str(path) for item in result["kept_in_place"]):
                result["kept_in_place"].append(
                    {
                        "source_path": str(path),
                        "classification": "UNKNOWN",
                        "result": "KEEP_IN_PLACE",
                        "reason": "UNRECOGNIZED_LEGACY_CONTENT",
                    }
                )

        for relative in TARGET_PATHS.values():
            target = root / relative
            _ensure_directory(target, created_directories)
            writable, reason = _verify_writable(target)
            if not writable:
                raise _MigrationOperationError("mkdir", target, OSError(reason))

        if not _defer_commit:
            commit_started = True
            _commit_migration(result, settings, settings_snapshot, settings_path, settings_writer)
        return result
    except _MigrationOperationError as exc:
        settings.clear()
        settings.update(settings_snapshot)
        blocked = _block_result(
            result,
            stage=exc.stage,
            path=exc.path,
            exc=exc,
            moved_items=moved_items,
            created_directories=created_directories,
        )
        if commit_started and result.get("_pending_settings_changes"):
            try:
                _persist_settings(settings_path, settings_writer, settings_snapshot)
            except Exception as restore_exc:
                blocked["rollback_status"] = "FAILED"
                blocked["rollback_failure_path"] = str(settings_path or "settings")
                blocked["rollback_exception_type"] = type(restore_exc).__name__
                blocked["rollback_reason"] = str(restore_exc)
                blocked["action_taken"] = "ROLLBACK_FAILED"
        return blocked
    except Exception as exc:
        settings.clear()
        settings.update(settings_snapshot)
        return _block_result(
            result,
            stage="move",
            path=root,
            exc=exc,
            moved_items=moved_items,
            created_directories=created_directories,
        )


def _migration_report_text(first: dict[str, Any], second_status: str) -> str:
    lines = [
        "# V0.5.3 正式目录迁移结果",
        "",
        f"执行时间：{datetime.now().isoformat(timespec='seconds')}",
        f"首次结果：{first.get('status')}",
        f"第二次运行结果：{second_status}",
        "",
        "## 迁移前目录分类",
        "",
    ]
    for item in first.get("inventory") or []:
        lines.append(f"- {item.get('name')}: {item.get('classification')}，文件数 {item.get('files', 0)}")
    lines.extend(
        [
            "",
            "## 执行统计",
            "",
            f"- 已迁移文件：{first.get('migrated_files', 0)}",
            f"- 已迁移目录：{first.get('migrated_directories', 0)}",
            f"- 相同内容去重：{first.get('deduplicated_files', 0)}",
            f"- 同名冲突安全改名：{len(first.get('renamed_conflicts') or [])}",
            f"- 删除空目录：{len(first.get('deleted_empty_directories') or [])}",
            f"- 历史归档：{len(first.get('archived') or [])}",
            f"- 原地保留：{len(first.get('kept_in_place') or [])}",
            f"- 失败：{len(first.get('failures') or [])}",
            "",
            "## Settings变化字段",
            "",
        ]
    )
    if first.get("settings_changes"):
        for field, value in first["settings_changes"].items():
            lines.append(f"- {field}: {value}")
    else:
        lines.append("- 无")
    lines.extend(["", "## 原地保留与失败", ""])
    for item in first.get("kept_in_place") or []:
        lines.append(f"- 保留：{item.get('source_path') or item.get('path')}；{item.get('reason')}")
    for item in first.get("failures") or []:
        lines.append(f"- 失败：{item.get('path')}；{item.get('reason')}")
    if not (first.get("kept_in_place") or first.get("failures")):
        lines.append("- 无")
    return "\n".join(lines) + "\n"


def _write_migration_report(report_path: Path, first: dict[str, Any], second_status: str) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if report_path.is_file():
        existing = report_path.read_text(encoding="utf-8").rstrip()
    if existing:
        lines = [
            existing,
            "",
            "## 后续安全收口",
            "",
            f"执行时间：{datetime.now().isoformat(timespec='seconds')}",
            f"首次结果：{first.get('status')}",
            f"第二次运行结果：{second_status}",
            f"已迁移文件：{first.get('migrated_files', 0)}",
            f"删除空目录：{len(first.get('deleted_empty_directories') or [])}",
            f"失败：{len(first.get('failures') or [])}",
        ]
        for path in first.get("deleted_empty_directories") or []:
            lines.append(f"- 已删除确认安全的空目录：{path}")
        for item in first.get("failures") or []:
            lines.append(f"- 失败：{item.get('path')}；{item.get('reason')}")
        report_text = "\n".join(lines) + "\n"
    else:
        report_text = _migration_report_text(first, second_status)
    temporary = report_path.with_name(f".{report_path.name}.tmp")
    try:
        temporary.write_text(report_text, encoding="utf-8")
        os.replace(temporary, report_path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _migration_cycle_response(status: str, first: dict[str, Any], second_run: str) -> dict[str, Any]:
    for key in [name for name in first if name.startswith("_")]:
        first.pop(key, None)
    return {"status": status, "first": first, "second_run": second_run}


def execute_migration_cycle(
    root: Path,
    settings: dict[str, Any],
    *,
    settings_path: Path | None = None,
    settings_writer: Callable[[dict[str, Any]], Any] | None = None,
    project_root: Path | None = None,
    write_report: bool = True,
) -> dict[str, Any]:
    report_path = Path(root) / TARGET_PATHS["report_dir"] / "V0.5.3_正式目录迁移结果.md"
    settings_snapshot = copy.deepcopy(settings)
    first = run_app_data_migration(
        root,
        settings,
        settings_path=settings_path,
        settings_writer=settings_writer,
        project_root=project_root,
        _defer_commit=True,
    )
    if first["status"] == "NO_OP":
        return _migration_cycle_response("NO_OP", first, "NO_OP")
    if first["status"] == "BLOCKED":
        return _migration_cycle_response("BLOCKED", first, "NOT_RUN")

    verification_settings = copy.deepcopy(settings_snapshot)
    verification_settings.update(first.get("_pending_settings_changes") or {})
    second = run_app_data_migration(
        root,
        verification_settings,
        settings_path=settings_path,
        settings_writer=settings_writer,
        project_root=project_root,
    )
    if second["status"] != "NO_OP":
        failure = RuntimeError(f"second migration verification returned {second['status']}")
        _block_result(
            first,
            stage=second.get("stage") or "enumerate",
            path=Path(second.get("path") or root),
            exc=failure,
            moved_items=first["_moved_items"],
            created_directories=first["_created_directories"],
        )
        return _migration_cycle_response("BLOCKED", first, second["status"])

    if write_report:
        try:
            _write_migration_report(report_path, first, second["status"])
        except Exception as exc:
            _block_result(
                first,
                stage="report_write",
                path=report_path,
                exc=exc,
                moved_items=first["_moved_items"],
                created_directories=first["_created_directories"],
            )
            settings.clear()
            settings.update(settings_snapshot)
            return _migration_cycle_response("BLOCKED", first, second["status"])

    try:
        _commit_migration(first, settings, settings_snapshot, settings_path, settings_writer)
    except _MigrationOperationError as exc:
        _block_result(
            first,
            stage=exc.stage,
            path=exc.path,
            exc=exc,
            moved_items=first["_moved_items"],
            created_directories=first["_created_directories"],
        )
        if first.get("_pending_settings_changes"):
            try:
                _persist_settings(settings_path, settings_writer, settings_snapshot)
            except Exception as restore_exc:
                first["rollback_status"] = "FAILED"
                first["rollback_failure_path"] = str(settings_path or "settings")
                first["rollback_exception_type"] = type(restore_exc).__name__
                first["rollback_reason"] = str(restore_exc)
                first["action_taken"] = "ROLLBACK_FAILED"
        settings.clear()
        settings.update(settings_snapshot)
        return _migration_cycle_response("BLOCKED", first, "NOT_RUN")
    return _migration_cycle_response("APPLIED", first, second["status"])


def main() -> int:
    parser = argparse.ArgumentParser(description="影界 V0.5.3 正式目录安全迁移")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    settings = json.loads(args.settings.read_text(encoding="utf-8"))
    result = execute_migration_cycle(
        args.root,
        settings,
        settings_path=args.settings,
        project_root=args.project_root,
        write_report=True,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"APPLIED", "NO_OP"} and result["second_run"] == "NO_OP" else 1


if __name__ == "__main__":
    raise SystemExit(main())
