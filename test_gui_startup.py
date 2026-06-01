from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from gui.help_system import HELP_TOPICS, help_dir, read_help_topic
from runtime.user_settings import settings_dir

ROOT = Path(__file__).resolve().parent


def main() -> int:
    assert (help_dir() / "使用说明.txt").exists(), "缺少 help/使用说明.txt"
    assert (help_dir() / "FAQ.txt").exists(), "缺少 help/FAQ.txt"
    assert (help_dir() / "日志位置说明.txt").exists(), "缺少 help/日志位置说明.txt"
    assert settings_dir().exists(), "运行时设置目录创建失败"
    for key in HELP_TOPICS:
        title, content = read_help_topic(key)
        assert title
        assert len(content.strip()) > 20, f"帮助主题内容过短：{key}"
    completed = subprocess.run(
        [sys.executable, "-m", "gui.app", "--self-test"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    print("GUI 启动模块测试通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
