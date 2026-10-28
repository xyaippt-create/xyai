from __future__ import annotations

import ast
import hashlib
import json
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from tests.support.app_runtime import isolated_app_runtime


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = PROJECT_ROOT / "tests"
REPOSITORY_SETTINGS_PATH = PROJECT_ROOT / "settings" / "settings.json"
SAFE_INITIALIZERS = {
    "activate_test_app_runtime",
    "activate_test_runtime_logging",
    "controlled_test_app_paths",
    "isolated_app_runtime",
    "isolated_runtime_logging",
    "isolated_test_client",
}


def _file_state(path: Path):
    if not path.exists():
        return ("missing",)
    if path.is_file():
        payload = path.read_bytes()
        return ("file", len(payload), hashlib.sha256(payload).hexdigest(), path.stat().st_mtime_ns)
    return (
        "directory",
        tuple(
            sorted(
                (
                    item.relative_to(path).as_posix(),
                    item.stat().st_size,
                    item.stat().st_mtime_ns,
                    hashlib.sha256(item.read_bytes()).hexdigest(),
                )
                for item in path.rglob("*")
                if item.is_file()
            )
        ),
    )


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _real_app_calls(path: Path) -> list[int]:
    source = path.read_text(encoding="utf-8-sig")
    if "build_web_app" not in source:
        return []
    tree = ast.parse(source, filename=str(path))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _call_name(node) == "build_web_app"
    ]


def _activated_initializers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return {
        _call_name(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _call_name(node) in SAFE_INITIALIZERS
    }


def _unisolated_app_lines(path: Path) -> list[int]:
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(path))
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def ancestor(node: ast.AST, kind):
        current = parents.get(node)
        while current is not None:
            if isinstance(current, kind):
                return current
            current = parents.get(current)
        return None

    def has_helper(node: ast.AST, *, before_line: int | None = None) -> bool:
        return any(
            isinstance(item, ast.Call)
            and _call_name(item) in SAFE_INITIALIZERS
            and (before_line is None or item.lineno < before_line)
            for item in ast.walk(node)
        )

    unsafe: list[int] = []
    for call in (
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _call_name(node) == "build_web_app"
    ):
        function = ancestor(call, (ast.FunctionDef, ast.AsyncFunctionDef))
        class_node = ancestor(call, ast.ClassDef)
        current = parents.get(call)
        safe = False
        while current is not None and current is not function:
            if isinstance(current, (ast.With, ast.AsyncWith)) and has_helper(current):
                safe = True
                break
            current = parents.get(current)
        if not safe and function is not None and has_helper(function, before_line=call.lineno):
            safe = True
        if not safe and class_node is not None:
            safe = any(
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name in {"setUp", "setUpClass"}
                and has_helper(item)
                for item in class_node.body
            )
        if not safe:
            unsafe.append(call.lineno)
    return unsafe


def test_all_real_app_test_paths_activate_shared_isolation_before_build() -> None:
    callsites: list[tuple[Path, int]] = []
    unisolated: list[str] = []
    for path in TESTS_ROOT.rglob("*.py"):
        if "support" in path.relative_to(TESTS_ROOT).parts:
            continue
        lines = _real_app_calls(path)
        if not lines:
            continue
        callsites.extend((path, line) for line in lines)
        unsafe_lines = _unisolated_app_lines(path)
        unisolated.extend(f"{path.relative_to(PROJECT_ROOT)}:{line}" for line in unsafe_lines)

    assert callsites, "No real build_web_app test path was discovered"
    assert not unisolated, f"UNISOLATED_APP_TEST_PATHS={unisolated}"


def test_real_app_api_writes_test_facts_only_to_isolated_runtime() -> None:
    repository_settings_before = _file_state(REPOSITORY_SETTINGS_PATH)
    configured = json.loads(REPOSITORY_SETTINGS_PATH.read_text(encoding="utf-8"))
    formal_root = Path(configured.get("app_data_root") or configured.get("last_app_data_root"))
    protected = {
        "formal_log": formal_root / "\u8bca\u65ad" / "\u65e5\u5fd7" / "hdde.log",
        "formal_feedback": formal_root / "\u8bca\u65ad" / "\u53cd\u9988\u5305",
        "formal_output": formal_root / "\u8f93\u51fa",
        "formal_result_delivery": formal_root / "\u8bca\u65ad" / "\u4efb\u52a1\u8bb0\u5f55" / "\u5171\u4eab\u4efb\u52a1\u4e8b\u5b9e.json",
    }
    protected_before = {name: _file_state(path) for name, path in protected.items()}
    test_id = f"API-ISOLATION-{uuid.uuid4().hex.upper()}"

    with isolated_app_runtime(test_id) as runtime:
        with TestClient(runtime.main.build_web_app(runtime_host="127.0.0.1", runtime_port=8896)) as client:
            health = client.get("/api/health")
            assert health.status_code == 200, health.text
            runtime_id = client.app.state.runtime_id
        temp_log = runtime.runtime_log_path.read_text(encoding="utf-8")
        assert f"runtime_id={runtime_id}" in temp_log
        assert "run_kind=test" in temp_log
        assert runtime.settings_path.is_file()
        isolated_settings = json.loads(runtime.settings_path.read_text(encoding="utf-8"))
        assert Path(isolated_settings["app_data_root"]) == runtime.formal_root
        assert (runtime.formal_root / runtime.main.DEFAULT_FEEDBACK_DIR_NAME).is_dir()
        assert (runtime.formal_root / runtime.main.OUTPUT_ROOT_RELATIVE).is_dir()

    formal_log_after = (
        protected["formal_log"].read_text(encoding="utf-8", errors="replace")
        if protected["formal_log"].is_file()
        else ""
    )
    assert runtime_id not in formal_log_after
    assert test_id not in formal_log_after
    assert _file_state(REPOSITORY_SETTINGS_PATH) == repository_settings_before
    for name in ("formal_feedback", "formal_output", "formal_result_delivery"):
        assert _file_state(protected[name]) == protected_before[name]


class AppRuntimeIsolationTests(unittest.TestCase):
    def test_all_real_app_paths_use_shared_isolation(self) -> None:
        test_all_real_app_test_paths_activate_shared_isolation_before_build()

    def test_real_app_api_keeps_formal_runtime_clean(self) -> None:
        test_real_app_api_writes_test_facts_only_to_isolated_runtime()

    def test_color_output_settings_follow_the_resolved_runtime_root(self) -> None:
        with isolated_app_runtime(f"COLOR-OUTPUT-{uuid.uuid4().hex.upper()}") as runtime:
            with TestClient(runtime.main.build_web_app()) as client:
                response = client.get("/api/color-correction/output-settings")

            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()["data"]
            expected_root = runtime.formal_root / "输出"
            self.assertEqual(Path(data["saved_default_root"]), expected_root)
            self.assertEqual(Path(data["function_output_directory"]), expected_root / "颜色校正")


if __name__ == "__main__":
    unittest.main()
