from __future__ import annotations

from pathlib import Path


def format_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.2f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def output_naming_rule() -> str:
    return "输出命名：原文件名_vmp_v03_4k.png / jpg"


def default_output_dir() -> Path:
    return Path.home() / "Desktop" / "雪原Ai增强引擎" / "输出成品"
