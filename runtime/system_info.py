from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path


def is_pyinstaller() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    if is_pyinstaller():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass).resolve()
    return app_root()


def runtime_settings_path() -> Path:
    """Return the writable settings file used by the active runtime."""
    if not is_pyinstaller():
        return resource_root() / "settings" / "settings.json"
    local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
    settings_root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return settings_root / "YingjieHDDE" / "settings.json"


PRODUCT_VERSION_PATH = resource_root() / "product_version.json"
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
RELEASE_CHANNEL_LABELS = {
    "DEVELOPMENT": "开发版",
    "INTERNAL_BETA": "测试版",
}


def expected_display_version(version: str, release_channel: str) -> str:
    match = SEMVER_PATTERN.fullmatch(version)
    label = RELEASE_CHANNEL_LABELS.get(release_channel)
    if not match or not label:
        raise RuntimeError("product_version.json contains an unsupported version contract")
    base_version = ".".join(match.group(index) for index in range(1, 4))
    return f"V{base_version} {label}"


def load_product_version() -> dict[str, str]:
    payload = json.loads(PRODUCT_VERSION_PATH.read_text(encoding="utf-8"))
    version = str(payload.get("version") or "").strip()
    display_version = str(payload.get("display_version") or "").strip()
    release_name = str(payload.get("release_name") or "").strip()
    release_channel = str(payload.get("release_channel") or "").strip().upper()
    if (
        display_version != expected_display_version(version, release_channel)
        or release_name != RELEASE_CHANNEL_LABELS[release_channel]
    ):
        raise RuntimeError("product_version.json is invalid or internally inconsistent")
    return {
        "version": version,
        "display_version": display_version,
        "release_name": release_name,
        "release_channel": release_channel,
    }


PRODUCT_VERSION_INFO = load_product_version()
PRODUCT_VERSION = PRODUCT_VERSION_INFO["version"]
APP_VERSION = PRODUCT_VERSION_INFO["display_version"]
RELEASE_CHANNEL = PRODUCT_VERSION_INFO["release_channel"]


def executable_path() -> Path:
    if is_pyinstaller():
        return Path(sys.executable).resolve()
    return Path(__file__).resolve()


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
