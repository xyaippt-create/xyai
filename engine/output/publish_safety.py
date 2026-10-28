"""Fail-closed, no-overwrite publication for prepared HDDE image outputs."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

from .filename_policy import resolve_collision_path
from .metadata_writer import write_hdde_metadata_bytes

if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes


PRIVATE_OUTPUT_PREFIX = ".hdde-output-"
PRIVATE_OUTPUT_SUFFIX = ".tmp"
SAFE_PUBLISH_UNSUPPORTED = "SAFE_PUBLISH_UNSUPPORTED"
_SAFE_PUBLISH_PLATFORM = os.name


class OutputMetadataStageError(RuntimeError):
    """Metadata preparation failed before any formal target was published."""


class OutputIdentityMismatchError(RuntimeError):
    """Copied bytes do not match the registered Result artifact identity."""


def _absolute_leaf(path: str | Path) -> Path:
    value = Path(path)
    return value.parent.resolve() / value.name


if os.name == "nt":
    _WIN_GENERIC_READ = 0x80000000
    _WIN_GENERIC_WRITE = 0x40000000
    _WIN_DELETE = 0x00010000
    _WIN_FILE_SHARE_READ = 0x00000001
    _WIN_FILE_SHARE_DELETE = 0x00000004
    _WIN_CREATE_NEW = 1
    _WIN_FILE_ATTRIBUTE_NORMAL = 0x00000080
    _WIN_FILE_RENAME_INFO = 3
    _WIN_FILE_DISPOSITION_INFO = 4
    _WIN_ERROR_FILE_EXISTS = 80
    _WIN_ERROR_ALREADY_EXISTS = 183
    _WIN_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class _WindowsFileDispositionInfo(ctypes.Structure):
        _fields_ = [("delete_file", wintypes.BOOLEAN)]

    class _WindowsFileRenameInfoHeader(ctypes.Structure):
        _fields_ = [
            ("replace_if_exists", wintypes.BOOLEAN),
            ("root_directory", wintypes.HANDLE),
            ("file_name_length", wintypes.DWORD),
        ]

    _windows_create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
    _windows_create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    _windows_create_file.restype = wintypes.HANDLE
    _windows_close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
    _windows_close_handle.argtypes = (wintypes.HANDLE,)
    _windows_close_handle.restype = wintypes.BOOL
    _windows_set_file_information = ctypes.WinDLL("kernel32", use_last_error=True).SetFileInformationByHandle
    _windows_set_file_information.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    _windows_set_file_information.restype = wintypes.BOOL


def _open_owned_private_temp(output_root: Path):
    if _SAFE_PUBLISH_PLATFORM != "nt":
        raise RuntimeError(SAFE_PUBLISH_UNSUPPORTED)
    output_root.mkdir(parents=True, exist_ok=True)
    while True:
        private_path = output_root / f"{PRIVATE_OUTPUT_PREFIX}{uuid.uuid4().hex}{PRIVATE_OUTPUT_SUFFIX}"
        raw_handle = _windows_create_file(
            str(private_path),
            _WIN_GENERIC_READ | _WIN_GENERIC_WRITE | _WIN_DELETE,
            # The creating handle remains open through validation and rename.  Never
            # grant a second handle write access to bytes that may become formal.
            _WIN_FILE_SHARE_READ | _WIN_FILE_SHARE_DELETE,
            None,
            _WIN_CREATE_NEW,
            _WIN_FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if raw_handle == _WIN_INVALID_HANDLE_VALUE:
            error_code = ctypes.get_last_error()
            if error_code in {_WIN_ERROR_FILE_EXISTS, _WIN_ERROR_ALREADY_EXISTS}:
                continue
            raise ctypes.WinError(error_code)
        try:
            file_descriptor = msvcrt.open_osfhandle(raw_handle, os.O_BINARY | os.O_RDWR)
        except Exception:
            _windows_close_handle(raw_handle)
            raise
        try:
            return private_path, os.fdopen(file_descriptor, "w+b")
        except Exception:
            os.close(file_descriptor)
            raise


def _same_open_file(open_file, path: Path) -> bool:
    try:
        opened = os.fstat(open_file.fileno())
        current = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return (opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino)


def _mark_owned_temp_for_delete(open_file, private_path: Path) -> None:
    if os.name == "nt":
        disposition = _WindowsFileDispositionInfo(True)
        raw_handle = msvcrt.get_osfhandle(open_file.fileno())
        if not _windows_set_file_information(
            raw_handle,
            _WIN_FILE_DISPOSITION_INFO,
            ctypes.byref(disposition),
            ctypes.sizeof(disposition),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return
    raise RuntimeError(SAFE_PUBLISH_UNSUPPORTED)


def _publish_open_file_no_replace(open_file, private_path: Path, candidate: Path) -> None:
    """Publish the open private file without any replace-existing semantics."""

    candidate = _absolute_leaf(candidate)
    if os.name == "nt":
        encoded_path = str(candidate).encode("utf-16-le")
        file_name_offset = _WindowsFileRenameInfoHeader.file_name_length.offset + ctypes.sizeof(wintypes.DWORD)
        rename_buffer = ctypes.create_string_buffer(file_name_offset + len(encoded_path) + ctypes.sizeof(wintypes.WCHAR))
        rename_header = _WindowsFileRenameInfoHeader.from_buffer(rename_buffer)
        rename_header.replace_if_exists = False
        rename_header.root_directory = None
        rename_header.file_name_length = len(encoded_path)
        ctypes.memmove(ctypes.addressof(rename_buffer) + file_name_offset, encoded_path, len(encoded_path))
        raw_handle = msvcrt.get_osfhandle(open_file.fileno())
        if not _windows_set_file_information(
            raw_handle,
            _WIN_FILE_RENAME_INFO,
            rename_buffer,
            len(rename_buffer),
        ):
            error_code = ctypes.get_last_error()
            if error_code in {_WIN_ERROR_FILE_EXISTS, _WIN_ERROR_ALREADY_EXISTS}:
                raise FileExistsError(error_code, ctypes.FormatError(error_code), str(candidate))
            raise ctypes.WinError(error_code)
        return
    raise RuntimeError(SAFE_PUBLISH_UNSUPPORTED)


def publish_image_bytes_with_metadata(
    output_data: bytes,
    final_target: str | Path,
    *,
    source_data: bytes | None = None,
    normalize_orientation: bool = False,
    collision_base_path: str | Path | None = None,
    verify_private: Callable[[bytes], Any] | None = None,
) -> tuple[Path, dict[str, Any], Any]:
    """Write metadata privately, validate, then publish exactly once without overwrite."""

    try:
        updated, metadata_report = write_hdde_metadata_bytes(
            output_data,
            source_data=source_data,
            normalize_orientation=normalize_orientation,
        )
    except Exception as exc:
        raise OutputMetadataStageError(str(exc) or exc.__class__.__name__) from exc
    requested_target = _absolute_leaf(final_target)
    collision_base = _absolute_leaf(collision_base_path) if collision_base_path is not None else None
    if collision_base is not None and requested_target.parent != collision_base.parent:
        raise ValueError("COLLISION_BASE_DIRECTORY_MISMATCH")

    def target_candidates():
        yield requested_target
        if collision_base is not None:
            while True:
                yield _absolute_leaf(resolve_collision_path(collision_base.parent, collision_base.name))

    publish_integrity: dict[str, Any] = {}
    published_path, validation = publish_prepared_bytes_no_overwrite(
        updated,
        target_candidates(),
        verify_private=verify_private,
        integrity_report=publish_integrity,
    )
    metadata_report = {**metadata_report, "publish_integrity": publish_integrity}
    return published_path, metadata_report, validation


def publish_prepared_bytes_no_overwrite(
    data: bytes,
    target_candidates: Iterable[str | Path],
    *,
    verify_private: Callable[[bytes], Any] | None = None,
    integrity_report: dict[str, Any] | None = None,
) -> tuple[Path, Any]:
    """Publish prepared bytes to the first available target without replacement."""

    candidates = iter(target_candidates)
    try:
        first_candidate = _absolute_leaf(next(candidates))
    except StopIteration as exc:
        raise ValueError("OUTPUT_TARGET_REQUIRED") from exc

    private_path, open_file = _open_owned_private_temp(first_candidate.parent)
    published = False
    try:
        written = open_file.write(data)
        if written != len(data):
            raise OSError("PRIVATE_OUTPUT_WRITE_INCOMPLETE")
        open_file.flush()
        os.fsync(open_file.fileno())
        open_file.seek(0)
        persisted = open_file.read()
        if persisted != data:
            raise OSError("PRIVATE_OUTPUT_PERSISTED_BYTES_MISMATCH")
        validated_sha256 = hashlib.sha256(persisted).hexdigest()
        validation = verify_private(persisted) if verify_private is not None else None

        candidate = first_candidate
        while True:
            try:
                _publish_open_file_no_replace(open_file, private_path, candidate)
                published = True
                break
            except FileExistsError as collision_error:
                try:
                    candidate = _absolute_leaf(next(candidates))
                except StopIteration:
                    raise collision_error
                if candidate.parent != first_candidate.parent:
                    raise ValueError("OUTPUT_TARGET_DIRECTORY_MISMATCH")

        # Verify the committed bytes through the same continuously-open handle.
        # No path-based rollback is allowed after the rename has committed.
        open_file.seek(0)
        committed_sha256 = hashlib.sha256(open_file.read()).hexdigest()
        if integrity_report is not None:
            integrity_report.update(
                {
                    "validated_sha256": validated_sha256,
                    "committed_sha256": committed_sha256,
                    "sha256_identity": committed_sha256 == validated_sha256,
                    "external_write_share": "DENIED_FROM_PRIVATE_CREATE_THROUGH_COMMIT",
                }
            )
        if committed_sha256 != validated_sha256:
            raise RuntimeError("PRIVATE_OUTPUT_COMMITTED_BYTES_MISMATCH")
        return candidate, validation
    except BaseException:
        if not published:
            _mark_owned_temp_for_delete(open_file, private_path)
        raise
    finally:
        open_file.close()


def publish_verified_file_copy_no_overwrite(
    source_path: str | Path,
    target_candidates: Iterable[str | Path],
    *,
    expected_sha256: str,
    chunk_size: int = 1024 * 1024,
) -> tuple[Path, dict[str, Any]]:
    """Stream one registered Result into a private file and publish only on SHA identity."""

    expected = str(expected_sha256 or "").strip().lower()
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise OutputIdentityMismatchError("RESULT_IDENTITY_MISMATCH")
    candidates = iter(target_candidates)
    try:
        first_candidate = _absolute_leaf(next(candidates))
    except StopIteration as exc:
        raise ValueError("OUTPUT_TARGET_REQUIRED") from exc

    private_path, open_file = _open_owned_private_temp(first_candidate.parent)
    published = False
    try:
        copied_digest = hashlib.sha256()
        copied_size = 0
        with Path(source_path).resolve().open("rb") as source_file:
            while True:
                chunk = source_file.read(max(1, int(chunk_size)))
                if not chunk:
                    break
                written = open_file.write(chunk)
                if written != len(chunk):
                    raise OSError("PRIVATE_OUTPUT_WRITE_INCOMPLETE")
                copied_digest.update(chunk)
                copied_size += len(chunk)
        open_file.flush()
        os.fsync(open_file.fileno())
        copied_sha256 = copied_digest.hexdigest()
        if copied_sha256 != expected:
            raise OutputIdentityMismatchError("RESULT_IDENTITY_MISMATCH")

        open_file.seek(0)
        persisted_digest = hashlib.sha256()
        for chunk in iter(lambda: open_file.read(max(1, int(chunk_size))), b""):
            persisted_digest.update(chunk)
        persisted_sha256 = persisted_digest.hexdigest()
        if persisted_sha256 != expected:
            raise OutputIdentityMismatchError("RESULT_IDENTITY_MISMATCH")

        candidate = first_candidate
        while True:
            try:
                _publish_open_file_no_replace(open_file, private_path, candidate)
                published = True
                break
            except FileExistsError as collision_error:
                try:
                    candidate = _absolute_leaf(next(candidates))
                except StopIteration:
                    raise collision_error
                if candidate.parent != first_candidate.parent:
                    raise ValueError("OUTPUT_TARGET_DIRECTORY_MISMATCH")

        open_file.seek(0)
        committed_digest = hashlib.sha256()
        for chunk in iter(lambda: open_file.read(max(1, int(chunk_size))), b""):
            committed_digest.update(chunk)
        committed_sha256 = committed_digest.hexdigest()
        if committed_sha256 != expected:
            _mark_owned_temp_for_delete(open_file, candidate)
            raise OutputIdentityMismatchError("RESULT_IDENTITY_MISMATCH")
        return candidate, {
            "registered_output_sha256": expected,
            "source_sha256": copied_sha256,
            "delivery_sha256": committed_sha256,
            "source_unchanged": True,
            "size_bytes": copied_size,
            "external_write_share": "DENIED_FROM_PRIVATE_CREATE_THROUGH_COMMIT",
        }
    except BaseException:
        if not published:
            _mark_owned_temp_for_delete(open_file, private_path)
        raise
    finally:
        open_file.close()


def publish_image_file_with_metadata(
    private_candidate: str | Path,
    final_target: str | Path,
    *,
    source_path: str | Path | None = None,
    normalize_orientation: bool = False,
    collision_base_path: str | Path | None = None,
    verify_private: Callable[[bytes], Any] | None = None,
) -> tuple[Path, dict[str, Any], Any]:
    """Publish an encoded candidate through the unified private metadata stage."""

    candidate_path = Path(private_candidate)
    return publish_image_bytes_with_metadata(
        candidate_path.read_bytes(),
        final_target,
        source_data=Path(source_path).read_bytes() if source_path is not None else None,
        normalize_orientation=normalize_orientation,
        collision_base_path=collision_base_path,
        verify_private=verify_private,
    )


__all__ = [
    "PRIVATE_OUTPUT_PREFIX",
    "PRIVATE_OUTPUT_SUFFIX",
    "SAFE_PUBLISH_UNSUPPORTED",
    "OutputIdentityMismatchError",
    "OutputMetadataStageError",
    "publish_image_bytes_with_metadata",
    "publish_image_file_with_metadata",
    "publish_prepared_bytes_no_overwrite",
    "publish_verified_file_copy_no_overwrite",
]
