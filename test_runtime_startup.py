from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from runtime.dependency_check import check_dependencies
from runtime.logger import latest_crash_path, logs_dir, write_crash_log
from runtime.startup_check import run_startup_check


PROJECT_ROOT = Path(__file__).resolve().parent


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_logs_create() -> None:
    path = logs_dir()
    assert_true(path.exists(), "logs 目录未自动创建")


def test_latest_crash_create() -> None:
    _, latest = write_crash_log(
        title="测试崩溃日志",
        traceback_text="Traceback: test runtime startup",
        dependency_results=check_dependencies(),
        extra_sections={"测试说明": "用于验证 latest_crash.txt 是否可生成。"},
    )
    assert_true(latest.exists(), "latest_crash.txt 未生成")
    assert_true("测试崩溃日志" in latest.read_text(encoding="utf-8"), "latest_crash.txt 内容异常")


def test_missing_input_dir_create() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        input_dir = root / "输入 图片"
        output_dir = root / "输出 成品"
        run_startup_check(input_dir, output_dir, show_no_image_dialog=False)
        assert_true(input_dir.exists(), "缺少输入目录时未自动创建")
        assert_true((output_dir / "images").exists(), "输出成品/images 未自动创建")


def test_no_input_image_no_crash() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        input_dir = root / "输入图片"
        output_dir = root / "输出成品"
        status = run_startup_check(input_dir, output_dir, show_no_image_dialog=False)
        assert_true(status.input_path.exists(), "无图片启动时输入目录不存在")


def test_dependency_check_runs() -> None:
    results = check_dependencies()
    names = {item.name for item in results}
    assert_true("cv2" in names, "dependency_check 未检查 cv2")
    assert_true("numpy" in names, "dependency_check 未检查 numpy")


def test_main_safe_start() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        env = os.environ.copy()
        env["VISUALMASTERPRO_DISABLE_DIALOG"] = "1"
        completed = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "main.py"),
                "--input",
                str(root / "输入图片"),
                "--output",
                str(root / "输出成品"),
            ],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=60,
        )
        assert_true(completed.returncode == 0, completed.stderr or completed.stdout)
        assert_true((root / "输入图片").exists(), "main.py 未创建输入图片目录")
        assert_true((root / "输出成品" / "images").exists(), "main.py 未创建输出成品/images")


def main() -> int:
    tests = [
        test_logs_create,
        test_latest_crash_create,
        test_missing_input_dir_create,
        test_no_input_image_no_crash,
        test_dependency_check_runs,
        test_main_safe_start,
    ]
    for test in tests:
        test()
        print(f"通过：{test.__name__}")
    print(f"日志目录：{logs_dir()}")
    print(f"latest_crash：{latest_crash_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
