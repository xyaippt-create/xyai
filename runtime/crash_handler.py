from __future__ import annotations

import sys
import traceback

from .dependency_check import check_dependencies
from .error_dialog import show_error_dialog
from .logger import write_crash_log


def handle_exception(exc: BaseException, title: str = "VisualMasterPro 启动失败") -> int:
    traceback_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    dependency_results = check_dependencies()
    crash_path, latest_path = write_crash_log(
        title=title,
        traceback_text=traceback_text,
        dependency_results=dependency_results,
    )

    print(title, file=sys.stderr)
    print(traceback_text, file=sys.stderr)
    print(f"错误日志：{latest_path}", file=sys.stderr)

    show_error_dialog(
        title,
        "\n".join(
            [
                "VisualMasterPro 启动失败",
                "",
                "软件启动时遇到问题，已自动生成错误日志。",
                "请将日志文件发送给开发者排查。",
                "",
                "日志位置：",
                str(latest_path),
                "",
                "本次崩溃日志：",
                str(crash_path),
            ]
        ),
    )
    return 1


def install_global_exception_hook() -> None:
    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        handle_exception(exc)

    sys.excepthook = _hook
