from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


class InstallerDataGateError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_files(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise InstallerDataGateError(f"REPARSE_OR_SYMLINK_FORBIDDEN: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path
    return result


def _provenance_summary(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    archives = payload.get("archives") or []
    mismatched = sum(int(item.get("HASH_MISMATCHED_MEMBER_COUNT", 0)) for item in archives)
    missing_hash = sum(int(item.get("MISSING_EXPECTED_HASH_COUNT", 0)) for item in archives)
    errors: list[str] = []
    if payload.get("status") != "PASS":
        errors.append("PROVENANCE_STATUS_NOT_PASS")
    if payload.get("MANIFEST_SCHEMA") != "PASS":
        errors.append("MANIFEST_SCHEMA_NOT_PASS")
    if int(payload.get("MISSING_REQUIRED_MEMBER_FIELDS", -1)) != 0:
        errors.append("MISSING_REQUIRED_MEMBER_FIELDS")
    if int(payload.get("unknown_count", -1)) != 0:
        errors.append("PROVENANCE_UNKNOWN_COUNT")
    if payload.get("archive_scan_errors"):
        errors.append("ARCHIVE_SCAN_ERRORS")
    if mismatched:
        errors.append("HASH_MISMATCHED_MEMBERS")
    if missing_hash:
        errors.append("MISSING_EXPECTED_HASH")
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "status": payload.get("status"),
        "manifest_schema": payload.get("MANIFEST_SCHEMA"),
        "missing_required_member_fields": payload.get("MISSING_REQUIRED_MEMBER_FIELDS"),
        "unknown_count": payload.get("unknown_count"),
        "archive_scan_errors": len(payload.get("archive_scan_errors") or []),
        "archive_member_count": payload.get("archive_member_count"),
        "hash_mismatched_member_count": mismatched,
        "missing_expected_hash": missing_hash,
        "errors": errors,
    }


def scan_installer_content(
    *,
    installer: Path,
    extracted_root: Path,
    source_app_tree: Path,
    webview2_bootstrapper: Path,
    app_provenance: Path,
    extracted_app_provenance: Path,
) -> dict[str, object]:
    errors: list[str] = []
    extracted_files = _tree_files(extracted_root)
    source_files = _tree_files(source_app_tree)
    expected = {f"app/{name}": path for name, path in source_files.items()}
    expected["tmp/MicrosoftEdgeWebView2Setup.exe"] = webview2_bootstrapper

    missing = sorted(set(expected) - set(extracted_files))
    unknown = sorted(set(extracted_files) - set(expected))
    if missing:
        errors.extend(f"MISSING_INSTALLER_CONTENT: {name}" for name in missing)
    if unknown:
        errors.extend(f"UNKNOWN_INSTALLER_CONTENT: {name}" for name in unknown)

    records: list[dict[str, object]] = []
    mismatched: list[str] = []
    for name in sorted(extracted_files):
        actual_path = extracted_files[name]
        actual_hash = _sha256(actual_path)
        expected_path = expected.get(name)
        expected_hash = _sha256(expected_path) if expected_path else None
        hash_match = expected_hash == actual_hash if expected_hash else False
        if expected_path and not hash_match:
            mismatched.append(name)
            errors.append(f"INSTALLER_CONTENT_HASH_MISMATCH: {name}")
        records.append(
            {
                "path": name,
                "size": actual_path.stat().st_size,
                "sha256": actual_hash,
                "classification": (
                    "THIRD_PARTY_WEBVIEW2_BOOTSTRAPPER"
                    if name == "tmp/MicrosoftEdgeWebView2Setup.exe"
                    else "APP_TREE"
                    if name.startswith("app/") and expected_path
                    else "UNKNOWN"
                ),
                "expected_sha256": expected_hash,
                "hash_match": hash_match,
            }
        )

    source_provenance = _provenance_summary(app_provenance)
    extracted_provenance = _provenance_summary(extracted_app_provenance)
    errors.extend(f"SOURCE_{item}" for item in source_provenance["errors"])
    errors.extend(f"EXTRACTED_{item}" for item in extracted_provenance["errors"])
    if source_provenance["archive_member_count"] != extracted_provenance["archive_member_count"]:
        errors.append("ARCHIVE_MEMBER_COUNT_MISMATCH")

    return {
        "status": "PASS" if not errors else "FAIL",
        "gate_version": "W60-03-installer-content-v1",
        "installer": str(installer.resolve()),
        "installer_sha256": _sha256(installer),
        "installer_size": installer.stat().st_size,
        "extracted_root": str(extracted_root.resolve()),
        "installer_content_files": len(records),
        "installer_content_size": sum(int(item["size"]) for item in records),
        "installer_content_scan_errors": errors,
        "unknown_count": len(unknown),
        "missing_count": len(missing),
        "hash_mismatch_count": len(mismatched),
        "source_app_file_count": len(source_files),
        "webview2_bootstrapper_sha256": _sha256(webview2_bootstrapper),
        "source_app_provenance": source_provenance,
        "extracted_app_provenance": extracted_provenance,
        "files": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--extracted-root", type=Path, required=True)
    parser.add_argument("--source-app-tree", type=Path, required=True)
    parser.add_argument("--webview2-bootstrapper", type=Path, required=True)
    parser.add_argument("--app-provenance", type=Path, required=True)
    parser.add_argument("--extracted-app-provenance", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    result = scan_installer_content(
        installer=args.installer,
        extracted_root=args.extracted_root,
        source_app_tree=args.source_app_tree,
        webview2_bootstrapper=args.webview2_bootstrapper,
        app_provenance=args.app_provenance,
        extracted_app_provenance=args.extracted_app_provenance,
    )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"INSTALLER_CONTENT_SCAN={result['status']}")
    print(f"INSTALLER_CONTENT_FILES={result['installer_content_files']}")
    print(f"INSTALLER_CONTENT_SIZE={result['installer_content_size']}")
    print(f"INSTALLER_CONTENT_SCAN_ERRORS={len(result['installer_content_scan_errors'])}")
    print(f"UNKNOWN_COUNT={result['unknown_count']}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
