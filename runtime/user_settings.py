from __future__ import annotations

from pathlib import Path

from .system_info import app_root


def settings_dir() -> Path:
    """Return a writable directory for lightweight user-side runtime flags."""
    candidates = [
        app_root() / "settings",
        Path.home() / "Documents" / "VisualMasterPro" / "settings",
    ]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except Exception:
            continue
    fallback = Path.cwd() / "settings"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def quick_guide_flag_path() -> Path:
    return settings_dir() / "quick_guide_seen_v03.flag"


def has_seen_quick_guide() -> bool:
    return quick_guide_flag_path().exists()


def mark_quick_guide_seen() -> None:
    quick_guide_flag_path().write_text("seen", encoding="utf-8")
