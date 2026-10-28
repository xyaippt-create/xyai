from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERSION_PATH = PROJECT_ROOT / "product_version.json"
MANAGE_VERSION_PATH = PROJECT_ROOT / "tools" / "manage_version.py"
TARGET_PATTERN = re.compile(r"^V(?P<semantic>\d+\.\d+\.\d+)\s+(?P<label>\S(?:.*\S)?)$")
COMMAND_PREFIXES = ("版本升级｜", "版本升级|")
TEXT_SUFFIXES = {".py", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".json", ".html", ".ps1", ".iss", ".spec"}
EXCLUDED_ROOT_DIRECTORIES = {
    ".agents",
    ".codex",
    ".git",
    ".reprosight",
    ".venv",
    "artifacts",
    "build",
    "dist",
    "docs",
    "logs",
    "node_modules",
    "output",
    "reports",
    "tests",
    "tmp",
}
EXCLUDED_DIRECTORY_NAMES = {"__pycache__", ".pytest_cache"}
EXCLUDED_FILE_NAMES = {"package-lock.json"}


def _load_manage_version():
    spec = importlib.util.spec_from_file_location("hdde_manage_version", MANAGE_VERSION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load version manager: {MANAGE_VERSION_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MANAGE_VERSION = _load_manage_version()


def _strip_command_prefix(value: str) -> str:
    normalized = str(value or "").strip()
    for prefix in COMMAND_PREFIXES:
        if normalized.startswith(prefix):
            return normalized[len(prefix) :].strip()
    return normalized


def parse_target_display(value: str) -> dict[str, str]:
    normalized = _strip_command_prefix(value)
    match = TARGET_PATTERN.fullmatch(normalized)
    if not match:
        raise ValueError("target must use the form 'V<major>.<minor>.<patch> <版本阶段>'")

    semantic_parts = MANAGE_VERSION.parse_version(match.group("semantic"))
    semantic_version = ".".join(str(part) for part in semantic_parts)
    label = match.group("label")
    release_channel = MANAGE_VERSION.release_channel_for_label(label)
    expected_display = MANAGE_VERSION.display_version_for(semantic_version, release_channel)
    target_display = f"V{semantic_version} {label}"
    if target_display != expected_display:
        raise ValueError(
            f"target display version {target_display!r} does not match release channel {release_channel!r}"
        )
    return {
        "semantic_version": semantic_version,
        "display_version": target_display,
        "label": label,
        "release_channel": release_channel,
    }


def _semantic_version(machine_version: str) -> str:
    return ".".join(str(part) for part in MANAGE_VERSION.parse_version(machine_version))


def _iter_active_source_files(project_root: Path):
    resolved_root = project_root.resolve()
    for current_root, directory_names, file_names in os.walk(resolved_root):
        current_path = Path(current_root)
        relative_parts = current_path.relative_to(resolved_root).parts
        directory_names[:] = [
            name
            for name in directory_names
            if name not in EXCLUDED_DIRECTORY_NAMES
            and not (not relative_parts and name in EXCLUDED_ROOT_DIRECTORIES)
            and not (relative_parts == ("tools",) and name == "experiments")
        ]
        for name in file_names:
            if name in EXCLUDED_FILE_NAMES:
                continue
            path = current_path / name
            if path.suffix.lower() in TEXT_SUFFIXES and not path.is_symlink():
                yield path


def find_old_version_residuals(
    project_root: Path,
    *,
    version_path: Path,
    old_machine_version: str,
    old_display_version: str,
    new_machine_version: str,
    new_display_version: str,
) -> list[dict[str, object]]:
    old_semantic = _semantic_version(old_machine_version)
    new_semantic = _semantic_version(new_machine_version)
    patterns = []
    if old_display_version != new_display_version:
        patterns.append(old_display_version)
    if old_machine_version != new_machine_version:
        patterns.append(old_machine_version)
    if old_semantic != new_semantic:
        patterns.extend((f"V{old_semantic}", old_semantic))
    patterns = tuple(dict.fromkeys(patterns))
    resolved_version_path = version_path.resolve()
    residuals: list[dict[str, object]] = []
    for path in _iter_active_source_files(project_root.resolve()):
        if path.resolve() == resolved_version_path:
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern in patterns:
                if pattern in line:
                    residuals.append(
                        {
                            "path": str(path.relative_to(project_root.resolve())),
                            "line": line_number,
                            "value": pattern,
                        }
                    )
    return residuals


def upgrade_product_version(
    target: str,
    *,
    version_path: Path = VERSION_PATH,
    project_root: Path = PROJECT_ROOT,
    expect_current: str | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    resolved_version_path = version_path.resolve()
    payload = MANAGE_VERSION.read_version_file(resolved_version_path)
    current_machine = str(payload["version"])
    current_display = str(payload["display_version"])
    current_release_channel = str(payload["release_channel"])
    target_info = parse_target_display(target)
    target_semantic = target_info["semantic_version"]
    target_release_channel = target_info["release_channel"]
    current_semantic = _semantic_version(current_machine)

    if MANAGE_VERSION.parse_version(target_semantic) < MANAGE_VERSION.parse_version(current_machine):
        raise ValueError(f"version downgrade is not allowed: {current_semantic} -> {target_semantic}")
    target_machine = MANAGE_VERSION.machine_version_for(target_semantic, target_release_channel)
    expected_display = MANAGE_VERSION.display_version_for(target_machine, target_release_channel)
    if expected_display != target_info["display_version"]:
        raise ValueError("target machine and display versions are inconsistent")

    residuals = find_old_version_residuals(
        project_root,
        version_path=resolved_version_path,
        old_machine_version=current_machine,
        old_display_version=current_display,
        new_machine_version=target_machine,
        new_display_version=expected_display,
    )
    if residuals:
        first = residuals[0]
        raise ValueError(
            "old version remains in active production source: "
            f"{first['path']}:{first['line']} ({first['value']})"
        )

    update_result = MANAGE_VERSION.update_version_file(
        resolved_version_path,
        set_version=target_machine,
        set_release_channel=target_release_channel,
        expect_current=expect_current or current_machine,
        dry_run=dry_run,
    )
    effective_payload = (
        {
            **payload,
            "version": target_machine,
            "display_version": expected_display,
            "release_name": target_info["label"],
            "release_channel": target_release_channel,
        }
        if dry_run
        else MANAGE_VERSION.read_version_file(resolved_version_path)
    )
    if (
        effective_payload["version"] != target_machine
        or effective_payload["display_version"] != expected_display
        or effective_payload["release_name"] != target_info["label"]
        or effective_payload["release_channel"] != target_release_channel
    ):
        raise RuntimeError("version source verification failed after update")

    post_update_residuals = find_old_version_residuals(
        project_root,
        version_path=resolved_version_path,
        old_machine_version=current_machine,
        old_display_version=current_display,
        new_machine_version=target_machine,
        new_display_version=expected_display,
    )
    if post_update_residuals:
        first = post_update_residuals[0]
        raise RuntimeError(
            "old version remains in active production source after update: "
            f"{first['path']}:{first['line']} ({first['value']})"
        )

    return {
        "status": "VERSION_UPGRADE_DRY_RUN" if dry_run else "VERSION_UPGRADE_OK",
        "source": str(resolved_version_path),
        "release_channel": target_release_channel,
        "old": {
            "semantic_version": current_semantic,
            "machine_version": current_machine,
            "display_version": current_display,
            "release_channel": current_release_channel,
        },
        "new": {
            "semantic_version": target_semantic,
            "machine_version": target_machine,
            "display_version": expected_display,
            "release_channel": target_release_channel,
        },
        "installer_version_source": "packaging/windows/build_release.ps1",
        "old_version_residuals": len(post_update_residuals),
        "changed": bool(update_result["changed"]),
        "dry_run": dry_run,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Upgrade the authoritative 影界 HDDE product version.")
    parser.add_argument("target", help="目标展示版本，例如：V<主版本>.<次版本>.<修订版本> <版本阶段>")
    parser.add_argument("--expect-current", help="可选的当前 machine version 并发保护")
    parser.add_argument("--dry-run", action="store_true", help="只校验并展示结果，不写入版本源")
    parser.add_argument("--file", type=Path, default=VERSION_PATH, help=argparse.SUPPRESS)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        result = upgrade_product_version(
            args.target,
            version_path=args.file,
            project_root=args.project_root,
            expect_current=args.expect_current,
            dry_run=args.dry_run,
        )
    except (OSError, UnicodeError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"VERSION_UPGRADE_BLOCKED: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
