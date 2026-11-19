"""Run every backend unittest file under tests/ with one command.

Each test_*.py runs in its own process from the project root, with the file's own
folder on PYTHONPATH (several suites import sibling fixtures by bare name).
Usage:
    .venv\\Scripts\\python.exe scripts\\run_backend_tests.py            # all files
    .venv\\Scripts\\python.exe scripts\\run_backend_tests.py output print # path filters
Exit code is 0 only when every selected file passes.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
SKIP_PARTS = {"__pycache__", "experiments", "fixtures", "outputs", "results"}
# Historical evidence checks that fail by design once the code moves on. They are
# still run and listed, but do not decide the exit code. Remove an entry once the
# file is repaired or retired.
KNOWN_LEGACY = {
    "tests/diagnostics/test_v0453_core_pipeline.py": "V0.4.5.3 诊断脚本，源码中文已乱码，无法解析",
    "tests/hd_core/test_candidate_framework.py": "核对 main.py 等文件与 V0.4.x 开发前冻结哈希一致，代码演进后必然不符",
    "tests/hd_core/test_e1_01_real_information_baseline.py": "E1-01 历史实验产物复核，依赖当时的路由与产物",
    "tests/hd_core/test_source_recovery_v3.py": "源图恢复 V3 可行性历史产物复核，产物状态为 BLOCKED",
}


def discover(filters: list[str]) -> list[Path]:
    files = []
    for path in sorted(TESTS.rglob("test_*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if SKIP_PARTS.intersection(path.relative_to(TESTS).parts[:-1]):
            continue
        if filters and not any(item in relative for item in filters):
            continue
        files.append(path)
    return files


def run_file(path: Path, timeout: int) -> tuple[str, float, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(path.parent), str(ROOT), env.get("PYTHONPATH", "")]))
    env.setdefault("PYTHONIOENCODING", "utf-8")
    started = time.monotonic()
    try:
        done = subprocess.run(
            [sys.executable, "-m", "unittest", str(path.relative_to(ROOT))],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "TIMEOUT", time.monotonic() - started, f"超过 {timeout} 秒未结束"
    output = (done.stdout + done.stderr).strip()
    ran = re.findall(r"^Ran (\d+) tests?", output, re.MULTILINE)
    if done.returncode == 5 and "NO TESTS RAN" in output:
        return "EMPTY", time.monotonic() - started, "文件内没有测试用例（诊断脚本）"
    status = "PASS" if done.returncode == 0 else "FAIL"
    detail = f"{ran[-1] if ran else '?'} 项"
    if status == "FAIL":
        detail += "\n" + "\n".join(output.splitlines()[-25:])
    return status, time.monotonic() - started, detail


def main() -> int:
    # Redirected output defaults to the GBK code page on Chinese Windows.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="一键运行影界 HDDE 后端测试")
    parser.add_argument("filters", nargs="*", help="只运行路径中包含这些文字的测试文件")
    parser.add_argument("--timeout", type=int, default=900, help="单个测试文件的超时秒数（默认 900）")
    args = parser.parse_args()
    files = discover(args.filters)
    if not files:
        print("没有找到匹配的测试文件。")
        return 1
    failed, legacy, empty = [], [], []
    for index, path in enumerate(files, 1):
        status, seconds, detail = run_file(path, args.timeout)
        relative = path.relative_to(ROOT).as_posix()
        if status not in ("PASS", "EMPTY") and relative in KNOWN_LEGACY:
            status, detail = "LEGACY", f"已知历史问题：{KNOWN_LEGACY[relative]}"
        print(f"[{index}/{len(files)}] {status:<7} {seconds:6.1f}s  {relative}  {detail.splitlines()[0]}", flush=True)
        if status == "EMPTY":
            empty.append(relative)
        elif status == "LEGACY":
            legacy.append(relative)
        elif status != "PASS":
            failed.append((relative, detail))
    passed = len(files) - len(failed) - len(legacy) - len(empty)
    print(f"\n共 {len(files)} 个文件：通过 {passed}，未通过 {len(failed)}，"
          f"已知历史问题 {len(legacy)}，无用例 {len(empty)}。")
    for relative, detail in failed:
        print(f"\n=== {relative} ===\n{detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
