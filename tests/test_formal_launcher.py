from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from runtime import formal_launcher


class FormalLauncherContractTests(unittest.TestCase):
    def test_backend_is_bound_to_project_venv_without_system_fallback(self):
        command = formal_launcher.backend_command()
        self.assertTrue(formal_launcher._same_path(command[0], formal_launcher.PROJECT_PYTHON))
        self.assertNotEqual(Path(command[0]).resolve(), Path(sys.base_prefix) / "python.exe")
        self.assertIn("--server", command)

    def test_frontend_is_direct_vite_child_with_strict_ports(self):
        command = formal_launcher.frontend_command()
        self.assertEqual(Path(command[1]).resolve(), formal_launcher.VITE_ENTRY.resolve())
        self.assertIn("--strictPort", command)
        self.assertIn(str(formal_launcher.FRONTEND_PORT), command)

    def test_only_exact_project_process_signatures_are_owned(self):
        state = {"backend_pid": 101, "frontend_pid": 202}
        backend = {
            "pid": 101,
            "executable": str(formal_launcher.PROJECT_PYTHON),
            "command": f'"{formal_launcher.PROJECT_PYTHON}" "{PROJECT_ROOT / "main.py"}" --server',
        }
        frontend = {
            "pid": 202,
            "executable": "node.exe",
            "command": f'node "{formal_launcher.VITE_ENTRY}" --strictPort',
        }
        foreign = {"pid": 303, "executable": "node.exe", "command": "node other-project/server.js"}
        self.assertTrue(formal_launcher._is_confirmed_hdde_listener(backend, 8787, state))
        self.assertTrue(formal_launcher._is_confirmed_hdde_listener(frontend, 5173, state))
        self.assertFalse(formal_launcher._is_confirmed_hdde_listener(foreign, 5173, state))

    def test_formal_dependencies_are_available_in_project_venv(self):
        formal_launcher.verify_formal_dependencies()

    def test_pre_logger_startup_failure_remains_visible_on_stderr(self):
        captured = io.StringIO()
        with (
            patch.object(
                formal_launcher,
                "run_formal_desktop",
                side_effect=formal_launcher.FormalStartupError("受控依赖加载失败"),
            ),
            redirect_stderr(captured),
        ):
            exit_code = formal_launcher.main([])

        self.assertEqual(exit_code, 1)
        self.assertIn("影界 HDDE 启动失败", captured.getvalue())
        self.assertIn("受控依赖加载失败", captured.getvalue())

    def test_lifecycle_paths_are_derived_from_the_configured_formal_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            formal_root = root / "影界文件"
            formal_root.mkdir()
            settings_path = root / "settings.json"
            settings_path.write_text(
                json.dumps({"app_data_root": str(formal_root)}, ensure_ascii=False),
                encoding="utf-8",
            )

            paths = formal_launcher._resolve_lifecycle_paths(settings_path)

            self.assertIsNotNone(paths)
            current_path, history_path = paths
            self.assertEqual(current_path, formal_root / "诊断" / "日志" / "formal_runtime_lifecycle.json")
            self.assertEqual(history_path, formal_root / "诊断" / "日志" / "formal_runtime_lifecycle.jsonl")

    def test_backend_output_capture_keeps_separate_tails_and_combined_log(self):
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "print('stdout-line', flush=True); "
                    "print('event=PROCESS_STARTED | operation_id=OP-1 | trace_id=TRACE-1 | "
                    "task_id=task-1 | route=ROUTE-1 | stage=engine_adapter', file=sys.stderr, flush=True)"
                ),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        combined = io.StringIO()
        capture = formal_launcher._BackendOutputCapture(process, combined)
        capture.start()
        self.assertEqual(process.wait(timeout=10), 0)
        capture.join()

        self.assertEqual(list(capture.stdout_tail), ["stdout-line"])
        self.assertIn("event=PROCESS_STARTED", capture.stderr_tail[-1])
        self.assertIn("stdout-line", combined.getvalue())
        self.assertIn("event=PROCESS_STARTED", combined.getvalue())
        self.assertEqual(
            formal_launcher._last_backend_context(capture.stdout_tail, capture.stderr_tail),
            {
                "last_operation_id": "OP-1",
                "last_trace_id": "TRACE-1",
                "last_task_id": "task-1",
                "last_route": "ROUTE-1",
                "last_stage": "engine_adapter",
            },
        )

    def test_lifecycle_snapshot_archives_an_unfinished_previous_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = root / "formal_runtime_lifecycle.json", root / "formal_runtime_lifecycle.jsonl"
            running = {
                "status": "RUNNING",
                "runtime_id": "RUN-OLD",
                "backend_pid": 123,
                "started_at": "2026-09-04T21:00:00+08:00",
            }
            self.assertTrue(formal_launcher._write_lifecycle_snapshot(paths, running, append_history=False))

            formal_launcher._archive_unfinished_lifecycle(paths)

            current = json.loads(paths[0].read_text(encoding="utf-8"))
            history = [json.loads(line) for line in paths[1].read_text(encoding="utf-8").splitlines()]
            self.assertEqual(current["status"], "EXITED_WITHOUT_FINALIZATION")
            self.assertEqual(current["exit_reason"], "LAUNCHER_TERMINATED_WITHOUT_FINALIZATION")
            self.assertIsNone(current["exit_code"])
            self.assertEqual(history[-1]["runtime_id"], "RUN-OLD")


if __name__ == "__main__":
    unittest.main()
