from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path


APP_VERSION = "VisualMasterPro V0.3"


def is_pyinstaller() -> bool:
    return bool(getattr(sys, "frozen", False))


def executable_path() -> Path:
    if is_pyinstaller():
        return Path(sys.executable).resolve()
    return Path(__file__).resolve()


def app_root() -> Path:
    if is_pyinstaller():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass).resolve()
    return app_root()


def get_gpu_info() -> str:
    commands = [
        ["wmic", "path", "win32_VideoController", "get", "name"],
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
    ]
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=5,
            )
        except Exception:
            continue
        output = "\n".join(line.strip() for line in completed.stdout.splitlines() if line.strip())
        if output:
            return output
    return "未检测到 GPU 信息或当前系统不支持自动读取。"


def collect_system_info() -> dict[str, str]:
    return {
        "软件版本": APP_VERSION,
        "Python 版本": sys.version.replace("\n", " "),
        "Windows 版本": platform.platform(),
        "当前工作目录": str(Path.cwd()),
        "EXE 运行路径": str(executable_path()),
        "PyInstaller 打包环境": "是" if is_pyinstaller() else "否",
        "_MEIPASS 路径": str(getattr(sys, "_MEIPASS", "未启用")),
        "资源根目录": str(resource_root()),
        "GPU 信息": get_gpu_info(),
    }
