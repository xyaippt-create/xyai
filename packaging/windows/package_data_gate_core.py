from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import io
import json
import marshal
import os
import re
import site
import sys
import types
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable

from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.loader.pyimod01_archive import ZlibArchiveReader

from program_resources import expected_app_tree_resources


APP_EXE_NAME = "影界 HDDE.exe"
IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
ZIP_SUFFIXES = {".zip", ".whl"}
APP_RESOURCE_PREFIXES = (
    "_internal/dist/",
    "_internal/engine/batch_watermark/fonts/",
    "_internal/models/local_retouch/",
    "_internal/modes/",
    "_internal/rules/",
    "_internal/ai_noise_rules/",
    "_internal/material_rules/",
    "_internal/visual_style_rules/",
    "_internal/external_tools/realesrgan-ncnn-vulkan/",
)
FORBIDDEN_RENDERER_RUNTIME = (
    "_internal/webview/lib/pywebview-android.jar",
    "_internal/webview/lib/WebBrowserInterop.x64.dll",
    "_internal/webview/lib/WebBrowserInterop.x86.dll",
)

# These are business/runtime artefacts, not generic substrings. Exact components
# avoid false positives such as unittest.result and importlib_metadata.
DENIED_COMPONENTS = {
    "benchmark",
    "benchmarks",
    "cache",
    "caches",
    "feedback",
    "feedbacks",
    "log",
    "logs",
    "registry",
    "registries",
    "result",
    "results",
    "task",
    "tasks",
    "task_history",
    "temp",
    "tests",
    "test_output",
    "tmp",
    "问题反馈",
    "反馈包",
    "日志",
    "缓存",
    "任务历史",
    "处理结果",
}
DENIED_FILE_STEMS = {
    "benchmark",
    "cache",
    "feedback",
    "registry",
    "result",
    "task",
    "task_history",
    "user_log",
    "问题反馈",
    "反馈包",
    "用户日志",
    "任务历史",
}
DENIED_SUFFIXES = {".log", ".tmp", ".temp", ".bak"}

MAX_ARCHIVE_DEPTH = 3
MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_MEMBER_SIZE = 128 * 1024 * 1024
MAX_ARCHIVE_EXPANDED_SIZE = 512 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1_000
ARCHIVE_TYPE_ENUM = frozenset(
    {
        "BASE_LIBRARY_ZIP",
        "CARCHIVE_EXE",
        "PKG",
        "PYZ_EMBEDDED",
        "PYZ_STANDALONE",
        "WHL",
        "ZIP",
    }
)
REQUIRED_PROVENANCE_MEMBER_FIELDS = (
    "ARCHIVE_TYPE",
    "ARCHIVE_IDENTITY",
    "MEMBER_PATH",
    "CLASSIFICATION",
    "SOURCE_ORIGIN",
    "EXPECTED_SHA256",
    "ACTUAL_SHA256",
    "HASH_MATCH",
)
HASH_BOUND_CONTENT_MODES = frozenset(
    {
        "MEMBER_INVENTORY",
        "RAW_CARCHIVE_WHOLE_AND_MEMBERS",
        "WHOLE_ARCHIVE_AND_MEMBERS",
    }
)


class PackageDataLeakError(RuntimeError):
    pass


@dataclass
class ArchiveBudget:
    members: int = 0
    expanded_size: int = 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_toc(path: Path):
    try:
        return ast.literal_eval(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - exact parser errors vary
        raise PackageDataLeakError(f"PYINSTALLER_TOC_INVALID:{path}:{exc}") from exc


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _normal_final_path(value: str) -> str:
    return PureWindowsPath(value).as_posix().lstrip("/")


def _path_needles(project_root: Path) -> dict[str, tuple[bytes, bytes]]:
    values = {
        "formal_user_root": r"D:\影界文件",
        "repository_path": str(project_root.resolve()),
    }
    user_profile = str(os.environ.get("USERPROFILE") or "").strip()
    if user_profile:
        values["current_user_profile"] = user_profile
    return {
        name: (value.encode("utf-8").lower(), value.encode("utf-16-le").lower())
        for name, value in values.items()
    }


def _scan_bytes(value: bytes, needles: dict[str, tuple[bytes, bytes]]) -> set[str]:
    lowered = value.lower()
    return {
        name
        for name, variants in needles.items()
        if any(needle and needle in lowered for needle in variants)
    }


def _hash_and_scan(path: Path, needles: dict[str, tuple[bytes, bytes]]) -> tuple[str, set[str]]:
    digest = hashlib.sha256()
    hits: set[str] = set()
    max_needle = max(len(item) for pair in needles.values() for item in pair)
    overlap = b""
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            searchable = (overlap + chunk).lower()
            for name, pair in needles.items():
                if any(needle and needle in searchable for needle in pair):
                    hits.add(name)
            overlap = searchable[-max_needle:]
    return digest.hexdigest(), hits


def _business_data_violations(value: str) -> list[str]:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    components = [part.casefold() for part in path.parts if part not in {"", "."}]
    errors: list[str] = []
    denied = sorted(set(components) & DENIED_COMPONENTS)
    if denied:
        errors.append("DENIED_COMPONENT:" + ",".join(denied))
    name = path.name.casefold()
    stem = PurePosixPath(name).stem
    if stem in DENIED_FILE_STEMS or any(stem.startswith(item + "_") for item in DENIED_FILE_STEMS):
        errors.append("DENIED_FILENAME:" + name)
    if PurePosixPath(name).suffix in DENIED_SUFFIXES:
        errors.append("DENIED_SUFFIX:" + PurePosixPath(name).suffix)
    return errors


def _trusted_roots(project_root: Path) -> list[tuple[Path, str]]:
    roots: list[tuple[Path, str]] = []
    for value in site.getsitepackages():
        roots.append((Path(value).resolve(), "PYTHON_SITE_PACKAGES"))
    roots.append((Path(sys.base_prefix).resolve(), "PYTHON_BASE_RUNTIME"))
    # The bundled Windows Python places codec/native dependencies beside its
    # Python directory. This exact environment root is part of the active
    # build toolchain, not an arbitrary user-profile directory.
    dependency_root = Path(sys.base_prefix).resolve().parent
    if dependency_root.name.casefold() == "dependencies":
        roots.append((dependency_root, "PYTHON_BUNDLED_DEPENDENCIES"))
    windows = os.environ.get("WINDIR")
    if windows:
        roots.extend(
            [
                (Path(windows, "System32").resolve(), "WINDOWS_SYSTEM_RUNTIME"),
                (Path(windows, "SysWOW64").resolve(), "WINDOWS_SYSTEM_RUNTIME"),
            ]
        )
    # Deduplicate while retaining the most specific roots first.
    unique: dict[str, tuple[Path, str]] = {}
    for root, rule in roots:
        unique[str(root).casefold()] = (root, rule)
    return sorted(unique.values(), key=lambda item: len(str(item[0])), reverse=True)


def _source_rule(source: Path, roots: list[tuple[Path, str]]) -> str | None:
    for root, rule in roots:
        if _is_within(source, root):
            if rule == "WINDOWS_SYSTEM_RUNTIME" and source.suffix.casefold() not in {".dll", ".pyd"}:
                return None
            return rule
    return None


def _collect_provenance(work: Path) -> dict[str, dict[str, str]]:
    toc_path = work / "COLLECT-00.toc"
    payload = _load_toc(toc_path)
    rows = payload[0] if isinstance(payload, tuple) and len(payload) == 1 else payload
    if not isinstance(rows, list):
        raise PackageDataLeakError(f"COLLECT_TOC_SHAPE_INVALID:{toc_path}")
    analysis = _load_toc(work / "Analysis-00.toc")
    analysis_sources = {
        (str(Path(source).resolve()).casefold(), str(source_type))
        for index in (15, 18)
        for _destination, source, source_type in analysis[index]
    }
    result: dict[str, dict[str, str]] = {}
    work_executables = list(work.glob("*.exe"))
    for row in rows:
        if not isinstance(row, tuple) or len(row) != 3:
            raise PackageDataLeakError(f"COLLECT_TOC_ROW_INVALID:{row!r}")
        destination, source, source_type = row
        if source_type == "EXECUTABLE":
            final_path = APP_EXE_NAME
            if len(work_executables) != 1:
                raise PackageDataLeakError(f"WORK_EXECUTABLE_COUNT_INVALID:{len(work_executables)}")
            source_path = work_executables[0]
        else:
            final_path = "_internal/" + _normal_final_path(str(destination))
            source_path = Path(str(source))
        if final_path in result:
            raise PackageDataLeakError(f"COLLECT_DUPLICATE_FINAL_PATH:{final_path}")
        result[final_path] = {
            "source_origin": str(source_path.resolve()),
            "source_type": str(source_type),
            "analysis_record": (
                "PYINSTALLER_GENERATED"
                if source_type == "EXECUTABLE" or source_path.name.casefold() == "base_library.zip"
                else (
                    "ANALYSIS_CONFIRMED"
                    if (str(source_path.resolve()).casefold(), str(source_type)) in analysis_sources
                    else "ANALYSIS_MISSING"
                )
            ),
        }
    return result


def _classify_file(
    relative: str,
    path: Path,
    provenance: dict[str, str] | None,
    expected: dict[str, str],
    project_root: Path,
    work: Path | None,
    roots: list[tuple[Path, str]],
) -> tuple[str, str, str, list[str]]:
    errors: list[str] = []
    if provenance is None:
        return "FAIL_CLOSED_UNKNOWN", "", "NO_COLLECT_PROVENANCE", [f"UNKNOWN_FINAL_FILE:{relative}"]
    source = Path(provenance["source_origin"])
    source_type = provenance["source_type"]
    if not source.is_file():
        return "FAIL_CLOSED_UNKNOWN", str(source), "SOURCE_MISSING", [f"PROVENANCE_SOURCE_MISSING:{relative}:{source}"]
    if work is not None and provenance.get("analysis_record") == "ANALYSIS_MISSING":
        return (
            "FAIL_CLOSED_UNKNOWN",
            str(source),
            "NOT_IN_PYINSTALLER_ANALYSIS",
            [f"PROVENANCE_NOT_IN_ANALYSIS:{relative}:{source}"],
        )
    if relative == APP_EXE_NAME:
        if source_type != "EXECUTABLE":
            errors.append(f"APP_EXECUTABLE_PROVENANCE_INVALID:{relative}:{source}")
            return "FAIL_CLOSED_UNKNOWN", str(source), "INVALID_EXECUTABLE_PROVENANCE", errors
        if work is None and source.resolve() == path.resolve():
            return "APP_EXECUTABLE", str(source), "EXPLICIT_TEST_PROVENANCE", errors
        if work is None or not _is_within(source, work):
            errors.append(f"APP_EXECUTABLE_PROVENANCE_INVALID:{relative}:{source}")
            return "FAIL_CLOSED_UNKNOWN", str(source), "INVALID_EXECUTABLE_PROVENANCE", errors
        return "APP_EXECUTABLE", str(source), "PYINSTALLER_COLLECT_EXECUTABLE", errors

    if relative in expected:
        expected_source = Path(expected[relative]).resolve()
        if source.resolve() != expected_source:
            errors.append(f"APP_RESOURCE_SOURCE_MISMATCH:{relative}:{source}:{expected_source}")
        elif _sha256(path) != _sha256(expected_source):
            errors.append(f"APP_RESOURCE_HASH_MISMATCH:{relative}")
        return "APP_OWNED_RESOURCE", str(source), "EXPLICIT_PROGRAM_RESOURCE_ALLOWLIST", errors

    allowed_sources = {str(Path(item).resolve()).casefold() for item in expected.values()}
    if str(source.resolve()).casefold() in allowed_sources and source_type in {"BINARY", "EXTENSION"}:
        if _sha256(path) != _sha256(source):
            errors.append(f"APP_RESOURCE_DEPENDENCY_HASH_MISMATCH:{relative}")
        return (
            "APP_OWNED_RUNTIME_DEPENDENCY",
            str(source),
            "PYINSTALLER_DEPENDENCY_FROM_ALLOWLIST_SOURCE",
            errors,
        )

    if relative.startswith(APP_RESOURCE_PREFIXES):
        errors.append(f"UNALLOWLISTED_APP_RESOURCE:{relative}")
        return "FAIL_CLOSED_UNKNOWN", str(source), "APP_RESOURCE_NOT_ALLOWLISTED", errors

    rule = _source_rule(source, roots)
    if rule:
        return "THIRD_PARTY_RUNTIME", str(source), rule, errors

    if work is not None and _is_within(source, work):
        if relative == "_internal/base_library.zip" and source.name.casefold() == "base_library.zip":
            if _sha256(path) != _sha256(source):
                errors.append(f"SOURCE_ARCHIVE_HASH_MISMATCH:{relative}:{source}")
            return "PYINSTALLER_RUNTIME", str(source), "PYINSTALLER_ANALYSIS_BASE_LIBRARY", errors
        errors.append(f"UNRECOGNIZED_PYINSTALLER_WORK_OUTPUT:{relative}:{source}")
        return "FAIL_CLOSED_UNKNOWN", str(source), "UNRECOGNIZED_WORK_OUTPUT", errors

    if _is_within(source, project_root):
        errors.append(f"PROJECT_SOURCE_NOT_ALLOWLISTED:{relative}:{source}")
        return "FAIL_CLOSED_UNKNOWN", str(source), "PROJECT_SOURCE_NOT_ALLOWLISTED", errors

    errors.append(f"UNTRUSTED_SOURCE_ORIGIN:{relative}:{source}")
    return "FAIL_CLOSED_UNKNOWN", str(source), "UNTRUSTED_SOURCE_ORIGIN", errors


def _validate_archive_member_name(name: str) -> str | None:
    normalized = name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return "ARCHIVE_MEMBER_ABSOLUTE_PATH"
    if any(part in {"", ".", ".."} for part in pure.parts):
        return "ARCHIVE_MEMBER_UNSAFE_PATH"
    return None


def _valid_pyc(value: bytes) -> bool:
    """Validate PYC structure without executing or importing its code object."""
    if len(value) < 17 or value[:4] != importlib.util.MAGIC_NUMBER:
        return False
    flags = int.from_bytes(value[4:8], "little")
    if flags not in {0, 1, 3}:
        return False
    payload = io.BytesIO(value[16:])
    try:
        code = marshal.load(payload)
    except (EOFError, ImportError, TypeError, ValueError):
        return False
    return isinstance(code, types.CodeType) and payload.read(1) == b""


def _archive_identity(value: str | Path) -> str:
    text = str(value)
    if "!/" in text:
        container, member = text.split("!/", 1)
        return f"{Path(container).resolve().as_posix().casefold()}!/{PurePosixPath(member).as_posix().casefold()}"
    return Path(text).resolve().as_posix().casefold()


def _manifest_schema_errors(archives: list[dict]) -> list[str]:
    errors: list[str] = []
    for archive in archives:
        content_bound = archive.get("CONTENT_BINDING_MODE") in HASH_BOUND_CONTENT_MODES
        for index, member in enumerate(archive.get("members", [])):
            label = str(member.get("FINAL_PATH") or f"member[{index}]")
            archive_type = member.get("ARCHIVE_TYPE")
            if archive_type is None or archive_type == "":
                errors.append(f"REQUIRED_FIELD_MISSING:{label}:ARCHIVE_TYPE")
            elif not isinstance(archive_type, str) or archive_type not in ARCHIVE_TYPE_ENUM:
                errors.append(f"ARCHIVE_TYPE_INVALID:{label}:{archive_type!r}")

            if not content_bound:
                continue
            for field in REQUIRED_PROVENANCE_MEMBER_FIELDS[1:]:
                value = member.get(field)
                if field == "HASH_MATCH":
                    if not isinstance(value, bool):
                        errors.append(f"REQUIRED_FIELD_INVALID:{label}:{field}")
                    elif value is not True:
                        errors.append(f"MEMBER_HASH_MATCH_FALSE:{label}")
                elif value is None or value == "":
                    errors.append(f"REQUIRED_FIELD_MISSING:{label}:{field}")
                elif not isinstance(value, str):
                    errors.append(f"REQUIRED_FIELD_INVALID:{label}:{field}")
            for field in ("EXPECTED_SHA256", "ACTUAL_SHA256"):
                value = member.get(field)
                if isinstance(value, str) and not re.fullmatch(r"[0-9a-f]{64}", value):
                    errors.append(f"SHA256_INVALID:{label}:{field}")
    return errors


def scan_zip_archive(
    archive: str | Path | bytes,
    *,
    display_path: str | None = None,
    depth: int = 0,
    budget: ArchiveBudget | None = None,
    expected_pyc_members: dict[str, dict[str, str]] | None = None,
    allowed_data_members: set[str] | None = None,
    needles: dict[str, tuple[bytes, bytes]] | None = None,
    archive_type: str = "ZIP",
    source_archive: str | Path | None = None,
) -> dict:
    """Scan ZIP contents recursively. Invalid/unknown members are fail-closed."""
    if depth > MAX_ARCHIVE_DEPTH:
        raise PackageDataLeakError(f"ARCHIVE_MAX_DEPTH_EXCEEDED:{display_path or archive}")
    current_budget = budget or ArchiveBudget()
    label = display_path or str(archive)
    source = io.BytesIO(archive) if isinstance(archive, bytes) else Path(archive)
    archive_identity = _archive_identity(display_path or label) if isinstance(archive, bytes) else _archive_identity(archive)
    final_archive_sha256 = _sha256_bytes(archive) if isinstance(archive, bytes) else _sha256(Path(archive))
    source_archive_path = Path(source_archive).resolve() if source_archive is not None else None
    if source_archive_path is not None and not source_archive_path.is_file():
        raise PackageDataLeakError(f"SOURCE_ARCHIVE_UNREADABLE:{source_archive_path}")
    source_archive_sha256 = _sha256(source_archive_path) if source_archive_path is not None else ""
    source_archive_hash_match = (
        source_archive_sha256 == final_archive_sha256 if source_archive_path is not None else None
    )
    allowed = {item.replace("\\", "/").lstrip("/") for item in (allowed_data_members or set())}
    expected_inventory = (
        {
            item.replace("\\", "/").lstrip("/"): dict(record)
            for item, record in expected_pyc_members.items()
        }
        if expected_pyc_members is not None
        else None
    )
    errors: list[str] = []
    if source_archive_hash_match is False:
        errors.append(
            f"SOURCE_ARCHIVE_HASH_MISMATCH:{label}:{source_archive_sha256}:{final_archive_sha256}"
        )
    entries: list[dict] = []
    try:
        handle = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise PackageDataLeakError(f"ZIP_INVALID:{label}:{exc}") from exc
    with handle:
        for info in handle.infolist():
            if info.is_dir():
                continue
            current_budget.members += 1
            current_budget.expanded_size += info.file_size
            member_label = f"{label}!/{info.filename}"
            if current_budget.members > MAX_ARCHIVE_MEMBERS:
                errors.append(f"ARCHIVE_MEMBER_LIMIT:{member_label}")
                break
            if info.file_size > MAX_ARCHIVE_MEMBER_SIZE:
                errors.append(f"ARCHIVE_MEMBER_SIZE_LIMIT:{member_label}:{info.file_size}")
                continue
            if current_budget.expanded_size > MAX_ARCHIVE_EXPANDED_SIZE:
                errors.append(f"ARCHIVE_EXPANDED_SIZE_LIMIT:{label}:{current_budget.expanded_size}")
                break
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > MAX_COMPRESSION_RATIO:
                errors.append(f"ARCHIVE_COMPRESSION_RATIO_LIMIT:{member_label}:{ratio:.2f}")
                continue
            unsafe = _validate_archive_member_name(info.filename)
            if unsafe:
                errors.append(f"{unsafe}:{member_label}")
                continue
            if info.flag_bits & 0x1:
                errors.append(f"ARCHIVE_ENCRYPTED_MEMBER:{member_label}")
                continue
            try:
                value = handle.read(info)
            except Exception as exc:  # pragma: no cover - depends on corrupt zip details
                errors.append(f"ARCHIVE_MEMBER_READ_ERROR:{member_label}:{exc}")
                continue
            for issue in _business_data_violations(info.filename):
                errors.append(f"BUSINESS_DATA_DENY:{member_label}:{issue}")
            if needles:
                for hit in sorted(_scan_bytes(value, needles)):
                    errors.append(f"PERSONAL_OR_FORMAL_PATH:{member_label}:{hit}")
            suffix = PurePosixPath(info.filename).suffix.casefold()
            member_name = info.filename.replace("\\", "/").lstrip("/")
            classification = "FAIL_CLOSED_UNKNOWN"
            rule = "UNKNOWN_ARCHIVE_MEMBER"
            member_source = label
            actual_sha256 = _sha256_bytes(value)
            member_details: dict[str, str | bool] = {}
            if suffix == ".pyc":
                structurally_valid = _valid_pyc(value)
                if not structurally_valid:
                    errors.append(f"PYC_INVALID:{member_label}")
                record = expected_inventory.get(member_name) if expected_inventory is not None else None
                expected_sha256 = str(record.get("expected_sha256", "")) if record is not None else ""
                hash_match = bool(expected_sha256 and expected_sha256.casefold() == actual_sha256)
                member_details = {
                    "ARCHIVE_TYPE": archive_type,
                    "ARCHIVE_IDENTITY": archive_identity,
                    "MEMBER_PATH": member_name,
                    "EXPECTED_SHA256": expected_sha256,
                    "ACTUAL_SHA256": actual_sha256,
                    "HASH_MATCH": hash_match,
                }
                if expected_inventory is None:
                    errors.append(f"UNPROVEN_PYC_MEMBER:{member_label}:NO_EXPECTED_INVENTORY")
                elif record is None:
                    errors.append(f"UNPROVEN_PYC_MEMBER:{member_label}:MEMBER_NOT_EXPECTED")
                else:
                    record_archive = str(record.get("archive_identity", ""))
                    record_member = str(record.get("member_path", "")).replace("\\", "/").lstrip("/")
                    module_identity = str(record.get("module_identity", ""))
                    source_origin = str(record.get("source_origin", ""))
                    source_identity = str(record.get("source_identity", ""))
                    provenance_source = str(record.get("provenance_source", ""))
                    expected_classification = str(record.get("expected_classification", ""))
                    provenance_errors: list[str] = []
                    if not record_archive or _archive_identity(record_archive) != archive_identity:
                        provenance_errors.append("ARCHIVE_IDENTITY_MISMATCH")
                    if record_member != member_name:
                        provenance_errors.append("MEMBER_PATH_MISMATCH")
                    if not module_identity:
                        provenance_errors.append("MODULE_IDENTITY_MISSING")
                    if not source_origin or not Path(source_origin).is_file():
                        provenance_errors.append("SOURCE_ORIGIN_UNVERIFIED")
                    if source_identity != source_origin:
                        provenance_errors.append("SOURCE_IDENTITY_MISMATCH")
                    if not provenance_source or not Path(provenance_source).is_file():
                        provenance_errors.append("PROVENANCE_SOURCE_UNVERIFIED")
                    if expected_classification != "PYTHON_BYTECODE":
                        provenance_errors.append("CLASSIFICATION_MISMATCH")
                    if not expected_sha256:
                        provenance_errors.append("EXPECTED_SHA256_MISSING")
                    elif not hash_match:
                        provenance_errors.append("HASH_MISMATCH")
                    if provenance_errors:
                        errors.extend(
                            f"PYC_PROVENANCE_INVALID:{member_label}:{issue}" for issue in provenance_errors
                        )
                    elif structurally_valid:
                        classification = "PYTHON_BYTECODE"
                        rule = "EXPECTED_PYC_MEMBER_PROVENANCE"
                        member_source = source_origin
                        member_details = {
                            "MODULE_IDENTITY": module_identity,
                            "PROVENANCE_SOURCE": provenance_source,
                            "ARCHIVE_IDENTITY": archive_identity,
                            "EXPECTED_CLASSIFICATION": expected_classification,
                            "MEMBER_PROVENANCE_RULE": "EXPECTED_PYC_MEMBER_PROVENANCE",
                            "SOURCE_IDENTITY": source_identity,
                            "MEMBER_PATH": member_name,
                            "EXPECTED_SHA256": expected_sha256,
                            "ACTUAL_SHA256": actual_sha256,
                            "HASH_MATCH": hash_match,
                        }
            elif suffix in ZIP_SUFFIXES:
                nested_prefix = member_name + "!/"
                nested_allowed = {
                    item[len(nested_prefix) :]
                    for item in allowed
                    if item.startswith(nested_prefix)
                }
                try:
                    nested = scan_zip_archive(
                        value,
                        display_path=member_label,
                        depth=depth + 1,
                        budget=current_budget,
                        allowed_data_members=nested_allowed,
                        needles=needles,
                        archive_type="WHL" if suffix == ".whl" else "ZIP",
                    )
                    entries.extend(nested["members"])
                except PackageDataLeakError as exc:
                    errors.append(str(exc))
                classification = "NESTED_ARCHIVE"
                rule = "RECURSIVE_ZIP_SCAN"
            elif member_name in allowed:
                classification = "APP_OWNED_ARCHIVE_RESOURCE"
                rule = "EXPLICIT_ARCHIVE_MEMBER_ALLOWLIST"
            else:
                errors.append(f"UNKNOWN_ARCHIVE_MEMBER:{member_label}")
            entries.append(
                {
                    "FINAL_PATH": member_label,
                    "ARCHIVE_TYPE": archive_type,
                    "CLASSIFICATION": classification,
                    "SOURCE_ORIGIN": member_source,
                    "ALLOW_RULE": rule,
                    "HASH": actual_sha256,
                    "SIZE": len(value),
                    **member_details,
                }
            )
    if expected_inventory is not None:
        actual = {
            item["FINAL_PATH"].split("!/", 1)[1]
            for item in entries
            if "!/" in item["FINAL_PATH"] and item["FINAL_PATH"].count("!/") == 1
        }
        missing = sorted(set(expected_inventory) - actual)
        # PyInstaller may move some expected stdlib modules into extension/runtime
        # payloads. Extra members are forbidden; missing Analysis rows are recorded.
        expected_note = {"expected_members": len(expected_inventory), "missing_expected_members": missing}
    else:
        expected_note = {}
    result = {
        "archive_type": archive_type,
        "path": label,
        "ARCHIVE_TYPE": archive_type,
        "ARCHIVE_IDENTITY": archive_identity,
        "SOURCE_ARCHIVE": str(source_archive_path) if source_archive_path is not None else "",
        "SOURCE_ARCHIVE_SHA256": source_archive_sha256,
        "FINAL_ARCHIVE_SHA256": final_archive_sha256,
        "SOURCE_ARCHIVE_HASH_MATCH": source_archive_hash_match,
        "CONTENT_BINDING_MODE": (
            "WHOLE_ARCHIVE_AND_MEMBERS"
            if source_archive_path is not None
            else "MEMBER_INVENTORY" if expected_inventory is not None else "UNPROVEN"
        ),
        "member_count": len(entries),
        "EXPECTED_MEMBER_COUNT": sum(bool(item.get("EXPECTED_SHA256")) for item in entries),
        "HASH_MATCHED_MEMBER_COUNT": sum(item.get("HASH_MATCH") is True for item in entries),
        "HASH_MISMATCHED_MEMBER_COUNT": sum(
            bool(item.get("EXPECTED_SHA256")) and item.get("HASH_MATCH") is not True for item in entries
        ),
        "MISSING_EXPECTED_HASH_COUNT": sum(
            "EXPECTED_SHA256" in item and not item.get("EXPECTED_SHA256") for item in entries
        ),
        "members": entries,
        "errors": errors,
        **expected_note,
    }
    if errors:
        raise PackageDataLeakError("ZIP_SCAN_FAIL:" + " | ".join(errors[:20]))
    return result


def _base_library_expected(
    work: Path,
    base_library: Path,
    source_archive: Path,
) -> dict[str, dict[str, str]]:
    analysis = _load_toc(work / "Analysis-00.toc")
    rows = analysis[19]
    analysis_members: dict[str, tuple[str, str]] = {}
    provenance_source = str((work / "Analysis-00.toc").resolve())
    archive_identity = _archive_identity(base_library)
    for module, source, source_type in rows:
        if source_type != "PYMODULE":
            continue
        module_path = module.replace(".", "/")
        if Path(source).name == "__init__.py":
            member = module_path + "/__init__.pyc"
        else:
            member = module_path + ".pyc"
        analysis_members[member] = (module, str(Path(source).resolve()))

    try:
        handle = zipfile.ZipFile(source_archive)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise PackageDataLeakError(f"BASE_LIBRARY_SOURCE_UNREADABLE:{source_archive}:{exc}") from exc
    source_hashes: dict[str, str] = {}
    with handle:
        for info in handle.infolist():
            if info.is_dir():
                continue
            unsafe = _validate_archive_member_name(info.filename)
            if unsafe:
                raise PackageDataLeakError(f"{unsafe}:{source_archive}!/{info.filename}")
            member = info.filename.replace("\\", "/").lstrip("/")
            if member in source_hashes:
                raise PackageDataLeakError(f"BASE_LIBRARY_SOURCE_DUPLICATE_MEMBER:{member}")
            if member not in analysis_members:
                raise PackageDataLeakError(f"BASE_LIBRARY_SOURCE_MEMBER_NOT_IN_ANALYSIS:{member}")
            try:
                source_hashes[member] = _sha256_bytes(handle.read(info))
            except Exception as exc:
                raise PackageDataLeakError(
                    f"BASE_LIBRARY_SOURCE_MEMBER_UNREADABLE:{source_archive}!/{member}:{exc}"
                ) from exc

    expected: dict[str, dict[str, str]] = {}
    for member, expected_sha256 in source_hashes.items():
        module, source_origin = analysis_members[member]
        expected[member] = {
            "archive_identity": archive_identity,
            "member_path": member,
            "module_identity": module,
            "source_origin": source_origin,
            "source_identity": source_origin,
            "provenance_source": provenance_source,
            "expected_classification": "PYTHON_BYTECODE",
            "expected_sha256": expected_sha256,
        }
    return expected


def _archive_source_rule(source: str, project_root: Path, work: Path, roots: list[tuple[Path, str]]) -> str | None:
    if source == "-":
        return "PYTHON_NAMESPACE_PACKAGE"
    path = Path(source)
    rule = _source_rule(path, roots)
    if rule:
        return rule
    if _is_within(path, work):
        return "PYINSTALLER_GENERATED_ARCHIVE_MEMBER"
    if _is_within(path, project_root) and path.suffix.casefold() == ".py":
        return "PROJECT_PYTHON_SOURCE_FROM_ANALYSIS"
    return None


def _scan_carchive(
    archive_path: Path,
    *,
    archive_type: str,
    work: Path,
    project_root: Path,
    roots: list[tuple[Path, str]],
    needles: dict[str, tuple[bytes, bytes]],
    source_archive: Path,
    expected_member_hashes: dict[str, str],
) -> dict:
    if not source_archive.is_file():
        raise PackageDataLeakError(f"CARCHIVE_SOURCE_MISSING:{source_archive}")
    try:
        reader = CArchiveReader(str(archive_path))
    except Exception as exc:
        raise PackageDataLeakError(f"CARCHIVE_INVALID:{archive_path}:{exc}") from exc
    pkg = _load_toc(work / "PKG-00.toc")
    rows = [row for row in pkg[2] if row[2] != "OPTION"]
    expected: dict[str, tuple[str, str]] = {}
    for name, source, source_type in rows:
        actual_name = "PYZ.pyz" if source_type == "PYZ" else name
        expected[actual_name] = (source, source_type)
    actual_names = set(reader.toc)
    errors: list[str] = []
    source_archive_sha256 = _sha256(source_archive)
    final_archive_sha256 = _sha256_bytes(reader.raw_pkg_data())
    source_archive_hash_match = source_archive_sha256 == final_archive_sha256
    if not source_archive_hash_match:
        errors.append(
            f"CARCHIVE_SOURCE_HASH_MISMATCH:{archive_path}:{source_archive_sha256}:{final_archive_sha256}"
        )
    if actual_names != set(expected):
        errors.append(
            "CARCHIVE_TOC_MISMATCH:missing="
            + ",".join(sorted(set(expected) - actual_names))
            + ":extra="
            + ",".join(sorted(actual_names - set(expected)))
        )
    members: list[dict] = []
    for name in sorted(actual_names):
        try:
            value = reader.extract(name)
        except Exception as exc:
            errors.append(f"CARCHIVE_EXTRACT_ERROR:{name}:{exc}")
            continue
        source, source_type = expected.get(name, ("", "UNKNOWN"))
        actual_sha256 = _sha256_bytes(value)
        expected_sha256 = expected_member_hashes.get(name, "")
        hash_match = bool(expected_sha256 and expected_sha256 == actual_sha256)
        if not expected_sha256:
            errors.append(f"CARCHIVE_EXPECTED_HASH_MISSING:{archive_path}!/{name}")
        elif not hash_match:
            errors.append(f"CARCHIVE_MEMBER_HASH_MISMATCH:{archive_path}!/{name}")
        rule = _archive_source_rule(source, project_root, work, roots)
        if not rule:
            errors.append(f"CARCHIVE_UNTRUSTED_SOURCE:{name}:{source}")
            rule = "FAIL_CLOSED_UNKNOWN"
        for hit in sorted(_scan_bytes(value, needles)):
            errors.append(f"PERSONAL_OR_FORMAL_PATH:{archive_path}!/{name}:{hit}")
        members.append(
            {
                "FINAL_PATH": f"{archive_path}!/{name}",
                "ARCHIVE_TYPE": archive_type,
                "ARCHIVE_IDENTITY": _archive_identity(archive_path),
                "MEMBER_PATH": name,
                "CLASSIFICATION": "PYINSTALLER_ARCHIVE_MEMBER" if rule != "FAIL_CLOSED_UNKNOWN" else "FAIL_CLOSED_UNKNOWN",
                "SOURCE_ORIGIN": source,
                "SOURCE_TYPE": source_type,
                "ALLOW_RULE": rule,
                "HASH": actual_sha256,
                "EXPECTED_SHA256": expected_sha256,
                "ACTUAL_SHA256": actual_sha256,
                "HASH_MATCH": hash_match,
                "SIZE": len(value),
            }
        )
    result = {
        "archive_type": archive_type,
        "path": str(archive_path.resolve()),
        "ARCHIVE_TYPE": archive_type,
        "ARCHIVE_IDENTITY": _archive_identity(archive_path),
        "SOURCE_ARCHIVE": str(source_archive.resolve()),
        "SOURCE_ARCHIVE_SHA256": source_archive_sha256,
        "FINAL_ARCHIVE_SHA256": final_archive_sha256,
        "SOURCE_ARCHIVE_HASH_MATCH": source_archive_hash_match,
        "CONTENT_BINDING_MODE": "RAW_CARCHIVE_WHOLE_AND_MEMBERS",
        "member_count": len(members),
        "EXPECTED_MEMBER_COUNT": len(expected_member_hashes),
        "HASH_MATCHED_MEMBER_COUNT": sum(item["HASH_MATCH"] is True for item in members),
        "HASH_MISMATCHED_MEMBER_COUNT": sum(item["HASH_MATCH"] is not True for item in members),
        "MISSING_EXPECTED_HASH_COUNT": sum(not item["EXPECTED_SHA256"] for item in members),
        "members": members,
        "errors": errors,
    }
    if errors:
        raise PackageDataLeakError("CARCHIVE_SCAN_FAIL:" + " | ".join(errors[:20]))
    return result


def _scan_pyz(
    reader: ZlibArchiveReader,
    *,
    archive_type: str,
    archive_path: str,
    work: Path,
    project_root: Path,
    roots: list[tuple[Path, str]],
    source_archive: Path,
    final_archive_sha256: str,
    expected_member_hashes: dict[str, str],
) -> dict:
    if not source_archive.is_file():
        raise PackageDataLeakError(f"PYZ_SOURCE_MISSING:{source_archive}")
    toc = _load_toc(work / "PYZ-00.toc")
    expected = {name: (source, source_type) for name, source, source_type in toc[1]}
    actual_names = set(reader.toc)
    errors: list[str] = []
    source_archive_sha256 = _sha256(source_archive)
    source_archive_hash_match = source_archive_sha256 == final_archive_sha256
    if not source_archive_hash_match:
        errors.append(
            f"PYZ_SOURCE_HASH_MISMATCH:{archive_path}:{source_archive_sha256}:{final_archive_sha256}"
        )
    if actual_names != set(expected):
        errors.append(
            "PYZ_TOC_MISMATCH:missing="
            + ",".join(sorted(set(expected) - actual_names))
            + ":extra="
            + ",".join(sorted(actual_names - set(expected)))
        )
    members: list[dict] = []
    for name in sorted(actual_names):
        typecode = reader.toc[name][0]
        source, source_type = expected.get(name, ("", "UNKNOWN"))
        rule = _archive_source_rule(source, project_root, work, roots)
        if not rule:
            errors.append(f"PYZ_UNTRUSTED_SOURCE:{name}:{source}")
            rule = "FAIL_CLOSED_UNKNOWN"
        if typecode not in {0, 1, 2, 3}:
            errors.append(f"PYZ_TYPECODE_INVALID:{name}:{typecode}")
        if source == "-" and typecode != 3:
            errors.append(f"PYZ_NAMESPACE_TYPE_INVALID:{name}:{typecode}")
        value = b""
        if source != "-":
            try:
                value = reader.extract(name, raw=True)
            except Exception as exc:
                errors.append(f"PYZ_EXTRACT_ERROR:{name}:{exc}")
        actual_sha256 = _sha256_bytes(value)
        expected_sha256 = expected_member_hashes.get(name, "")
        hash_match = bool(expected_sha256 and expected_sha256 == actual_sha256)
        if not expected_sha256:
            errors.append(f"PYZ_EXPECTED_HASH_MISSING:{archive_path}!/{name}")
        elif not hash_match:
            errors.append(f"PYZ_MEMBER_HASH_MISMATCH:{archive_path}!/{name}")
        members.append(
            {
                "FINAL_PATH": f"{archive_path}!/{name}",
                "ARCHIVE_TYPE": archive_type,
                "ARCHIVE_IDENTITY": _archive_identity(archive_path),
                "MEMBER_PATH": name,
                "CLASSIFICATION": "PYTHON_MODULE" if rule != "FAIL_CLOSED_UNKNOWN" else "FAIL_CLOSED_UNKNOWN",
                "SOURCE_ORIGIN": source,
                "SOURCE_TYPE": source_type,
                "ALLOW_RULE": rule,
                "HASH": actual_sha256,
                "EXPECTED_SHA256": expected_sha256,
                "ACTUAL_SHA256": actual_sha256,
                "HASH_MATCH": hash_match,
                "SIZE": len(value),
            }
        )
    result = {
        "archive_type": archive_type,
        "path": archive_path,
        "ARCHIVE_TYPE": archive_type,
        "ARCHIVE_IDENTITY": _archive_identity(archive_path),
        "SOURCE_ARCHIVE": str(source_archive.resolve()),
        "SOURCE_ARCHIVE_SHA256": source_archive_sha256,
        "FINAL_ARCHIVE_SHA256": final_archive_sha256,
        "SOURCE_ARCHIVE_HASH_MATCH": source_archive_hash_match,
        "CONTENT_BINDING_MODE": "WHOLE_ARCHIVE_AND_MEMBERS",
        "member_count": len(members),
        "EXPECTED_MEMBER_COUNT": len(expected_member_hashes),
        "HASH_MATCHED_MEMBER_COUNT": sum(item["HASH_MATCH"] is True for item in members),
        "HASH_MISMATCHED_MEMBER_COUNT": sum(item["HASH_MATCH"] is not True for item in members),
        "MISSING_EXPECTED_HASH_COUNT": sum(not item["EXPECTED_SHA256"] for item in members),
        "members": members,
        "errors": errors,
    }
    if errors:
        raise PackageDataLeakError("PYZ_SCAN_FAIL:" + " | ".join(errors[:20]))
    return result


def _carchive_member_hashes(reader: CArchiveReader, archive_path: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in sorted(reader.toc):
        try:
            hashes[name] = _sha256_bytes(reader.extract(name))
        except Exception as exc:
            raise PackageDataLeakError(f"CARCHIVE_SOURCE_MEMBER_UNREADABLE:{archive_path}!/{name}:{exc}") from exc
    return hashes


def _pyz_member_hashes(reader: ZlibArchiveReader, archive_path: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in sorted(reader.toc):
        try:
            value = reader.extract(name, raw=True)
        except Exception as exc:
            raise PackageDataLeakError(f"PYZ_SOURCE_MEMBER_UNREADABLE:{archive_path}!/{name}:{exc}") from exc
        hashes[name] = _sha256_bytes(value or b"")
    return hashes


def scan_pyinstaller_archives(
    app_tree: Path,
    project_root: Path,
    work: Path,
    needles: dict[str, tuple[bytes, bytes]],
    roots: list[tuple[Path, str]],
    *,
    include_base_library: bool = True,
) -> list[dict]:
    exe = app_tree / APP_EXE_NAME
    packages = list(work.glob("*.pkg"))
    if len(packages) != 1:
        raise PackageDataLeakError(f"PYINSTALLER_PKG_COUNT_INVALID:{len(packages)}")
    pyz_path = work / "PYZ-00.pyz"
    base_library = app_tree / "_internal" / "base_library.zip"
    required = [exe, packages[0], pyz_path, base_library]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise PackageDataLeakError("PYINSTALLER_ARCHIVE_MISSING:" + ",".join(missing))

    try:
        package_reader = CArchiveReader(str(packages[0]))
        executable_reader = CArchiveReader(str(exe))
        standalone_pyz_reader = ZlibArchiveReader(str(pyz_path))
        embedded_pyz_reader = executable_reader.open_embedded_archive("PYZ.pyz")
        embedded_pyz_bytes = executable_reader.extract("PYZ.pyz")
    except Exception as exc:
        raise PackageDataLeakError(f"PYINSTALLER_SOURCE_ARCHIVE_UNREADABLE:{exc}") from exc
    carchive_expected_hashes = _carchive_member_hashes(package_reader, packages[0])
    pyz_expected_hashes = _pyz_member_hashes(standalone_pyz_reader, pyz_path)

    archives = [
        _scan_carchive(
            exe,
            archive_type="CARCHIVE_EXE",
            work=work,
            project_root=project_root,
            roots=roots,
            needles=needles,
            source_archive=packages[0],
            expected_member_hashes=carchive_expected_hashes,
        ),
        _scan_carchive(
            packages[0],
            archive_type="PKG",
            work=work,
            project_root=project_root,
            roots=roots,
            needles=needles,
            source_archive=packages[0],
            expected_member_hashes=carchive_expected_hashes,
        ),
    ]
    archives.append(
        _scan_pyz(
            embedded_pyz_reader,
            archive_type="PYZ_EMBEDDED",
            archive_path=f"{exe}!/PYZ.pyz",
            work=work,
            project_root=project_root,
            roots=roots,
            source_archive=pyz_path,
            final_archive_sha256=_sha256_bytes(embedded_pyz_bytes),
            expected_member_hashes=pyz_expected_hashes,
        )
    )
    archives.append(
        _scan_pyz(
            standalone_pyz_reader,
            archive_type="PYZ_STANDALONE",
            archive_path=str(pyz_path),
            work=work,
            project_root=project_root,
            roots=roots,
            source_archive=pyz_path,
            final_archive_sha256=_sha256(pyz_path),
            expected_member_hashes=pyz_expected_hashes,
        )
    )
    if include_base_library:
        archives.append(_scan_base_library_archive(base_library, project_root, work, needles, roots))
    return archives


def _scan_base_library_archive(
    base_library: Path,
    project_root: Path,
    work: Path,
    needles: dict[str, tuple[bytes, bytes]],
    roots: list[tuple[Path, str]],
) -> dict:
    source_archive = work / "base_library.zip"
    if not source_archive.is_file():
        raise PackageDataLeakError(f"BASE_LIBRARY_SOURCE_MISSING:{source_archive}")
    expected_base = _base_library_expected(work, base_library, source_archive)
    base = scan_zip_archive(
        base_library,
        display_path=str(base_library),
        expected_pyc_members=expected_base,
        needles=needles,
        archive_type="BASE_LIBRARY_ZIP",
        source_archive=source_archive,
    )
    for member in base["members"]:
        name = member["FINAL_PATH"].split("!/", 1)[1]
        record = expected_base.get(name, {})
        member["SOURCE_ORIGIN"] = record.get("source_origin", "")
        rule = _archive_source_rule(member["SOURCE_ORIGIN"], project_root, work, roots)
        if not rule:
            raise PackageDataLeakError(f"BASE_LIBRARY_UNTRUSTED_SOURCE:{name}:{member['SOURCE_ORIGIN']}")
        member["ALLOW_RULE"] = rule
    return base


def scan_app_tree(
    app_tree: str | Path,
    project_root: str | Path,
    manifest_path: str | Path,
    *,
    expected_resources: dict[str, str] | None = None,
    pyinstaller_work: str | Path | None = None,
    provenance_by_path: dict[str, dict[str, str]] | None = None,
    trusted_roots: list[tuple[Path, str]] | None = None,
    archive_member_allowlist: dict[str, set[str]] | None = None,
) -> dict:
    tree = Path(app_tree).resolve()
    root = Path(project_root).resolve()
    manifest = Path(manifest_path).resolve()
    work = Path(pyinstaller_work).resolve() if pyinstaller_work else None
    if not tree.is_dir():
        raise PackageDataLeakError(f"APP_TREE_MISSING:{tree}")
    if work is not None and not work.is_dir():
        raise PackageDataLeakError(f"PYINSTALLER_WORK_MISSING:{work}")
    expected = expected_resources if expected_resources is not None else expected_app_tree_resources(root)
    provenance = provenance_by_path if provenance_by_path is not None else (_collect_provenance(work) if work else {})
    roots = trusted_roots if trusted_roots is not None else _trusted_roots(root)
    files = sorted(path for path in tree.rglob("*") if path.is_file())
    observed = {path.relative_to(tree).as_posix(): path for path in files}
    errors: list[str] = []
    archive_errors: list[str] = []
    archive_allowlist = {
        key.replace("\\", "/").lstrip("/"): set(value)
        for key, value in (archive_member_allowlist or {}).items()
    }

    if APP_EXE_NAME not in observed:
        errors.append(f"APP_EXE_MISSING:{APP_EXE_NAME}")
    missing_resources = sorted(set(expected) - set(observed))
    if missing_resources:
        errors.append("APP_RESOURCE_MISSING:" + ",".join(missing_resources))
    if work is not None:
        missing_collect = sorted(set(provenance) - set(observed))
        extra_observed = sorted(set(observed) - set(provenance))
        if missing_collect:
            errors.append("COLLECT_OUTPUT_MISSING:" + ",".join(missing_collect))
        if extra_observed:
            errors.append("UNKNOWN_FINAL_FILES:" + ",".join(extra_observed))

    needles = _path_needles(root)
    entries: list[dict] = []
    total_size = 0
    for relative, path in observed.items():
        for issue in _business_data_violations(relative):
            errors.append(f"BUSINESS_DATA_DENY:{relative}:{issue}")
        if path.suffix.casefold() == ".pyc":
            errors.append(f"LOOSE_PYC_FORBIDDEN:{relative}")
        if path.suffix.casefold() in IMAGE_SUFFIXES and relative not in expected:
            errors.append(f"NON_ALLOWLIST_IMAGE:{relative}")
        if any(relative == forbidden or relative.startswith(forbidden) for forbidden in FORBIDDEN_RENDERER_RUNTIME):
            errors.append(f"UNUSED_RENDERER_RUNTIME:{relative}")

        classification, source, allow_rule, classification_errors = _classify_file(
            relative,
            path,
            provenance.get(relative),
            expected,
            root,
            work,
            roots,
        )
        errors.extend(classification_errors)
        size = path.stat().st_size
        sha256, hits = _hash_and_scan(path, needles)
        source_path = Path(source) if source else None
        source_hash = _sha256(source_path) if source_path and source_path.is_file() else ""
        total_size += size
        for hit in sorted(hits):
            errors.append(f"PERSONAL_OR_FORMAL_PATH:{relative}:{hit}")
        entries.append(
            {
                "FINAL_PATH": relative,
                "CLASSIFICATION": classification,
                "SOURCE_ORIGIN": source,
                "SOURCE_TYPE": (provenance.get(relative) or {}).get("source_type", ""),
                "ANALYSIS_RECORD": (provenance.get(relative) or {}).get("analysis_record", "EXPLICIT_INJECTION"),
                "ALLOW_RULE": allow_rule,
                "HASH": sha256,
                "SOURCE_HASH": source_hash,
                "SOURCE_HASH_MATCH": bool(source_hash and source_hash == sha256),
                "SIZE": size,
            }
        )

    archives: list[dict] = []
    scanned_archive_identities: set[str] = set()
    ordinary_archives = [
        (relative, path)
        for relative, path in observed.items()
        if path.suffix.casefold() in ZIP_SUFFIXES
    ]
    base_library_path = tree / "_internal" / "base_library.zip"
    base_library_scanned = False
    for relative, path in ordinary_archives:
        identity = _archive_identity(path)
        try:
            if work is not None and identity == _archive_identity(base_library_path):
                base_library_scanned = True
                archive_result = _scan_base_library_archive(path, root, work, needles, roots)
            else:
                archive_result = scan_zip_archive(
                    path,
                    display_path=relative,
                    allowed_data_members=archive_allowlist.get(relative, set()),
                    needles=needles,
                    archive_type="WHL" if path.suffix.casefold() == ".whl" else "ZIP",
                )
            archives.append(archive_result)
            scanned_archive_identities.add(identity)
        except PackageDataLeakError as exc:
            archive_errors.append(str(exc))

    archives_deduped = 0
    pyinstaller_archives: list[dict] = []
    if work is not None:
        try:
            pyinstaller_archives = scan_pyinstaller_archives(
                tree,
                root,
                work,
                needles,
                roots,
                include_base_library=not base_library_scanned,
            )
            if base_library_scanned:
                archives_deduped = 1
            for archive_result in pyinstaller_archives:
                identity = _archive_identity(archive_result["path"])
                if identity in scanned_archive_identities:
                    archives_deduped += 1
                    continue
                archives.append(archive_result)
                scanned_archive_identities.add(identity)
        except PackageDataLeakError as exc:
            archive_errors.append(str(exc))
    errors.extend(f"ARCHIVE_SCAN_ERROR:{item}" for item in archive_errors)

    archives_discovered = len(ordinary_archives) + len(pyinstaller_archives) + archives_deduped
    manifest_schema_errors = _manifest_schema_errors(archives)
    errors.extend(f"MANIFEST_SCHEMA_ERROR:{item}" for item in manifest_schema_errors)
    missing_required_member_fields = sum(
        item.startswith("REQUIRED_FIELD_MISSING:") for item in manifest_schema_errors
    )

    result = {
        "status": "PASS" if not errors else "FAIL",
        "gate_version": "W60-02-P0-fail-closed-v1",
        "app_tree": str(tree),
        "pyinstaller_work": str(work) if work else "",
        "file_count": len(entries),
        "total_size": total_size,
        "app_owned_resource_count": sum(item["CLASSIFICATION"] == "APP_OWNED_RESOURCE" for item in entries),
        "third_party_runtime_count": sum(item["CLASSIFICATION"] == "THIRD_PARTY_RUNTIME" for item in entries),
        "unknown_count": sum(item["CLASSIFICATION"] == "FAIL_CLOSED_UNKNOWN" for item in entries),
        "program_resource_allowlist": sorted(expected),
        "nested_archive_policy": {
            "max_depth": MAX_ARCHIVE_DEPTH,
            "max_members": MAX_ARCHIVE_MEMBERS,
            "max_member_size": MAX_ARCHIVE_MEMBER_SIZE,
            "max_expanded_size": MAX_ARCHIVE_EXPANDED_SIZE,
            "max_compression_ratio": MAX_COMPRESSION_RATIO,
            "invalid_archive": "FAIL",
            "unknown_member": "FAIL",
        },
        "archive_scan_errors": archive_errors,
        "archives": archives,
        "archives_discovered": archives_discovered,
        "archives_scanned": len(archives),
        "archives_deduped": archives_deduped,
        "archive_member_count": sum(item["member_count"] for item in archives),
        "MANIFEST_SCHEMA": "PASS" if not manifest_schema_errors else "FAIL",
        "REQUIRED_MEMBER_FIELDS": list(REQUIRED_PROVENANCE_MEMBER_FIELDS),
        "MISSING_REQUIRED_MEMBER_FIELDS": missing_required_member_fields,
        "MANIFEST_SCHEMA_ERRORS": manifest_schema_errors,
        "errors": errors,
        "files": entries,
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if errors:
        raise PackageDataLeakError("PACKAGE_DATA_LEAK_GATE_FAIL: " + " | ".join(errors[:20]))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fail-closed scan of an HDDE PyInstaller application tree.")
    parser.add_argument("--app-tree", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--pyinstaller-work", required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = scan_app_tree(
        args.app_tree,
        args.project_root,
        args.manifest,
        pyinstaller_work=args.pyinstaller_work,
    )
    manifest = Path(args.manifest).resolve()
    print("PACKAGE_DATA_LEAK_GATE=PASS")
    print(f"APP_TREE_FILES={result['file_count']}")
    print(f"APP_TREE_SIZE={result['total_size']}")
    print(f"APP_OWNED_RESOURCES={result['app_owned_resource_count']}")
    print(f"THIRD_PARTY_RUNTIME_FILES={result['third_party_runtime_count']}")
    print(f"UNKNOWN_FILES={result['unknown_count']}")
    print(f"ARCHIVE_MEMBERS={result['archive_member_count']}")
    print(f"ARCHIVES_DISCOVERED={result['archives_discovered']}")
    print(f"ARCHIVES_SCANNED={result['archives_scanned']}")
    print(f"ARCHIVES_DEDUPED={result['archives_deduped']}")
    print(f"MANIFEST_SCHEMA={result['MANIFEST_SCHEMA']}")
    print(f"MISSING_REQUIRED_MEMBER_FIELDS={result['MISSING_REQUIRED_MEMBER_FIELDS']}")
    print(f"PROVENANCE_MANIFEST={manifest}")
    print(f"PROVENANCE_MANIFEST_SHA256={_sha256(manifest)}")
    return 0
