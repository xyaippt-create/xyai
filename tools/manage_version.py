from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


DEFAULT_VERSION_FILE = Path(__file__).resolve().parents[1] / "product_version.json"
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
RELEASE_CHANNEL_LABELS = {
    "DEVELOPMENT": "开发版",
    "INTERNAL_BETA": "测试版",
}
RELEASE_CHANNEL_SUFFIXES = {
    "DEVELOPMENT": "-dev",
    "INTERNAL_BETA": "-beta",
}


def parse_version(value: str) -> tuple[int, int, int]:
    match = SEMVER_PATTERN.fullmatch(str(value).strip())
    if not match:
        raise ValueError(f"invalid semantic version: {value!r}")
    return tuple(int(match.group(index)) for index in range(1, 4))


def display_version_for(version: str, release_channel: str) -> str:
    major, minor, patch = parse_version(version)
    normalized_channel = str(release_channel or "").strip().upper()
    label = RELEASE_CHANNEL_LABELS.get(normalized_channel)
    if not label:
        raise ValueError(f"unsupported release channel: {release_channel!r}")
    return f"V{major}.{minor}.{patch} {label}"


def release_channel_for_label(label: str) -> str:
    normalized_label = str(label or "").strip()
    for release_channel, expected_label in RELEASE_CHANNEL_LABELS.items():
        if normalized_label == expected_label:
            return release_channel
    raise ValueError(f"unsupported release label: {label!r}")


def machine_version_for(version: str, release_channel: str) -> str:
    major, minor, patch = parse_version(version)
    normalized_channel = str(release_channel or "").strip().upper()
    suffix = RELEASE_CHANNEL_SUFFIXES.get(normalized_channel)
    if not suffix:
        raise ValueError(f"unsupported release channel: {release_channel!r}")
    return f"{major}.{minor}.{patch}{suffix}"


def bump_version(current: str, level: str) -> str:
    major, minor, patch = parse_version(current)
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    if level == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"unsupported bump level: {level}")


def read_version_file(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    current = str(payload.get("version") or "").strip()
    parse_version(current)
    release_channel = str(payload.get("release_channel") or "").strip().upper()
    if payload.get("display_version") != display_version_for(current, release_channel):
        raise ValueError("display_version does not match version and release_channel")
    if not str(payload.get("release_name") or "").strip():
        raise ValueError("release_name is required")
    return payload


def update_version_file(
    path: Path,
    *,
    set_version: str | None = None,
    bump: str | None = None,
    set_release_channel: str | None = None,
    expect_current: str | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    payload = read_version_file(path)
    current = str(payload["version"])
    if expect_current is not None and current != expect_current:
        raise ValueError(f"expected current version {expect_current}, found {current}")
    target = set_version if set_version is not None else bump_version(current, str(bump))
    parse_version(target)
    target_channel = str(set_release_channel or payload["release_channel"]).strip().upper()
    target_label = RELEASE_CHANNEL_LABELS.get(target_channel)
    if not target_label:
        raise ValueError(f"unsupported release channel: {target_channel!r}")
    next_payload = {
        **payload,
        "version": target,
        "display_version": display_version_for(target, target_channel),
        "release_name": target_label if set_release_channel is not None else payload["release_name"],
        "release_channel": target_channel,
    }
    changed = next_payload != payload
    if changed and not dry_run:
        rendered = json.dumps(next_payload, ensure_ascii=False, indent=2) + "\n"
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8", newline="\n")
        temporary.replace(path)
    return {"current": current, "target": target, "changed": changed, "dry_run": dry_run, "path": str(path)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safely update the VisualMasterPro product version source.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--set", dest="set_version", metavar="VERSION")
    action.add_argument("--bump", choices=("patch", "minor", "major"))
    parser.add_argument("--expect-current")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--file", type=Path, default=DEFAULT_VERSION_FILE, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = update_version_file(
            args.file.resolve(),
            set_version=args.set_version,
            bump=args.bump,
            expect_current=args.expect_current,
            dry_run=args.dry_run,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"VERSION_UPDATE_BLOCKED: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
