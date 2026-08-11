from __future__ import annotations

import io
import sys
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


if __name__ == "__main__":
    unittest.main()
