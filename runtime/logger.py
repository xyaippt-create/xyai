from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .dependency_check import format_dependency_report
from .system_info import app_root, collect_system_info


def logs_dir() -> Path:
    candidates = [
        app_root() / "logs",
        Path.home() / "Documents" / "VisualMasterPro" / "logs",
    ]
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except Exception:
            continue
    fallback = Path.cwd() / "logs"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def latest_crash_path() -> Path:
    return logs_dir() / "latest_crash.txt"


def write_crash_log(
    title: str,
    traceback_text: str,
    dependency_results,
    extra_sections: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    crash_path = logs_dir() / f"crash_{timestamp}.txt"

    lines = [
        "VisualMasterPro 崩溃日志",
        "=" * 40,
        f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"错误标题：{title}",
        "",
        "系统信息",
        "-" * 40,
    ]
    for key, value in collect_system_info().items():
        lines.append(f"{key}：{value}")

    lines.extend(["", "依赖检查结果", "-" * 40, format_dependency_report(dependency_results)])

    if extra_sections:
        for section_title, section_body in extra_sections.items():
            lines.extend(["", section_title, "-" * 40, section_body])

    lines.extend(["", "完整错误堆栈", "-" * 40, traceback_text])
    content = "\n".join(lines) + "\n"

    crash_path.write_text(content, encoding="utf-8")
    latest_path = latest_crash_path()
    latest_path.write_text(content, encoding="utf-8")
    return crash_path, latest_path
