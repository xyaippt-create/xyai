from __future__ import annotations

import asyncio
import json
import time
import urllib.request
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime import packaged_launcher, system_info
from runtime.production_frontend import ProductionFrontendError, register_production_frontend
from runtime.windows_dialog import select_directory


ROOT = Path(__file__).resolve().parents[1]


class ProductionFrontendTests(unittest.TestCase):
    def test_spa_and_assets_are_served_without_intercepting_unknown_api(self):
        with tempfile.TemporaryDirectory() as directory:
            dist = Path(directory)
            (dist / "assets").mkdir()
            (dist / "index.html").write_text("<html>HDDE SPA</html>", encoding="utf-8")
            (dist / "assets" / "app.js").write_text("window.HDDE=true", encoding="utf-8")
            app = FastAPI()

            @app.get("/api/health")
            async def health():
                return {"version": "test"}

            register_production_frontend(app, dist)
            with TestClient(app) as client:
                self.assertEqual(client.get("/").status_code, 200)
                self.assertIn("HDDE SPA", client.get("/processing").text)
                self.assertIn("window.HDDE", client.get("/assets/app.js").text)
                self.assertEqual(client.get("/api/health").json(), {"version": "test"})
                self.assertEqual(client.get("/api/missing").status_code, 404)

    def test_formal_health_reports_bound_runtime_address(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        current_app = source[source.index("def build_web_app(runtime_host:") :]
        health = current_app[current_app.index('    @app.get("/api/health")') : current_app.index('    @app.get("/api/runtime/status")')]
        self.assertIn('"host": runtime_host', health)
        self.assertIn('"port": runtime_port', health)

    def test_missing_frontend_assets_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ProductionFrontendError):
                register_production_frontend(FastAPI(), directory)


class PackagedRuntimeContractTests(unittest.TestCase):
    def test_owned_backend_close_is_idempotent_and_preserves_another_server(self):
        import uvicorn

        policy = asyncio.get_event_loop_policy()
        servers = []
        threads = []
        listeners = []
        app = FastAPI()

        @app.get("/health")
        async def health():
            return {"ready": True}

        try:
            for _ in range(2):
                listener = packaged_launcher.reserve_loopback_socket()
                listeners.append(listener)
                config = uvicorn.Config(
                    app, log_config=None, access_log=False,
                    loop="runtime.packaged_launcher:packaged_backend_loop_factory",
                    timeout_graceful_shutdown=5,
                )
                server = uvicorn.Server(config)
                servers.append(server)
                thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]})
                threads.append(thread)
                thread.start()
                deadline = time.monotonic() + 5
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(server.started)
            urls = [f"http://127.0.0.1:{s.getsockname()[1]}/health" for s in listeners]
            for url in urls:
                with urllib.request.urlopen(url, timeout=2) as response:
                    self.assertEqual(response.status, 200)
            servers[0].should_exit = True
            servers[0].should_exit = True
            threads[0].join(timeout=5)
            self.assertFalse(threads[0].is_alive())
            self.assertTrue(threads[1].is_alive())
            with urllib.request.urlopen(urls[1], timeout=2) as response:
                self.assertEqual(response.status, 200)
            self.assertIs(asyncio.get_event_loop_policy(), policy)
        finally:
            for server in servers:
                server.should_exit = True
            for thread in threads:
                thread.join(timeout=5)
            for listener in listeners:
                listener.close()

    def test_dynamic_loopback_socket_remains_reserved_for_uvicorn_handoff(self):
        listener = packaged_launcher.reserve_loopback_socket()
        try:
            host, port = listener.getsockname()
            self.assertEqual(host, "127.0.0.1")
            self.assertNotIn(port, {5173, 8787})
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as contender:
                with self.assertRaises(OSError):
                    contender.bind((host, port))
        finally:
            listener.close()

    def test_readiness_requires_health_version_runtime_and_bound_port(self):
        port = 49152
        health = {
            "code": 200,
            "status": "success",
            "success": True,
            "data": {
                "healthy": True,
                "version": packaged_launcher.APP_VERSION,
                "host": "127.0.0.1",
                "port": port,
            },
        }
        runtime = {
            "code": 200,
            "status": "success",
            "success": True,
            "data": {
                "status": "ready",
                "product": {
                    "version": packaged_launcher.APP_VERSION,
                    "build_status": "loaded",
                },
                "application": {
                    "status": "running",
                    "host": "127.0.0.1",
                    "port": port,
                },
            },
        }
        self.assertTrue(packaged_launcher._health_contract_valid(health, port))
        self.assertTrue(packaged_launcher._runtime_contract_valid(runtime, port))
        health["data"]["healthy"] = False
        self.assertFalse(packaged_launcher._health_contract_valid(health, port))
        runtime["data"]["product"]["version"] = "wrong"
        self.assertFalse(packaged_launcher._runtime_contract_valid(runtime, port))

    def test_desktop_window_forces_edgechromium_and_closes_owned_runtime(self):
        class FakeEvent:
            def __init__(self):
                self.callbacks = []

            def __iadd__(self, callback):
                self.callbacks.append(callback)
                return self

            def fire(self, *args):
                for callback in self.callbacks:
                    callback(*args)

        class FakeWindow:
            def __init__(self, url):
                self.url = url
                self.destroyed = False
                self.events = type("Events", (), {})()
                self.events.shown = FakeEvent()
                self.events.loaded = FakeEvent()
                self.events.closed = FakeEvent()

            def get_current_url(self):
                return self.url

            def evaluate_js(self, _script):
                return {"path": self.url.split(":49152", 1)[1], "title": "影界 HDDE", "readyState": "complete"}

            def destroy(self):
                self.destroyed = True

        class FakeWebview:
            renderer = "edgechromium"

            def __init__(self):
                self.window = None
                self.create_kwargs = {}
                self.start_kwargs = {}

            def create_window(self, _title, url, **kwargs):
                self.window = FakeWindow(url)
                self.create_kwargs = kwargs
                return self.window

            def start(self, **kwargs):
                self.start_kwargs = kwargs
                self.window.events.shown.fire(self.window)
                self.window.events.loaded.fire(self.window)
                if self.window.url.endswith("/processing"):
                    for route in ("/color-correction", "/output-center", "/processing"):
                        self.window.url = "http://127.0.0.1:49152" + route
                        self.window.events.loaded.fire(self.window)
                        if self.window.destroyed:
                            raise AssertionError("A later page load closed the desktop")
                self.window.events.closed.fire()

        fake = FakeWebview()
        stopped = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            packaged_launcher.run_desktop_window(
                "http://127.0.0.1:49152/processing",
                stopped,
                lambda: False,
                storage_root=Path(directory) / "webview",
                webview_module=fake,
            )
        self.assertTrue(stopped.is_set())
        self.assertEqual(fake.start_kwargs["gui"], "edgechromium")
        self.assertTrue(fake.start_kwargs["private_mode"])
        self.assertEqual(fake.window.url, "http://127.0.0.1:49152/processing")
        self.assertFalse(fake.window.destroyed)
        with tempfile.TemporaryDirectory() as directory:
            invalid = FakeWebview()
            with self.assertRaises(packaged_launcher.PackagedRuntimeError):
                packaged_launcher.run_desktop_window(
                    "http://127.0.0.1:49152/color-correction",
                    threading.Event(), lambda: False,
                    storage_root=Path(directory), webview_module=invalid,
                )
            self.assertTrue(invalid.window.destroyed)

    def test_packaged_source_never_opens_a_system_browser(self):
        source = (ROOT / "runtime" / "packaged_launcher.py").read_text(encoding="utf-8")
        self.assertNotIn("import webbrowser", source)
        self.assertNotIn("webbrowser.open", source)
        self.assertIn('DEFAULT_PAGE = "/processing"', source)

    def test_windowed_packaged_runtime_disables_console_log_formatter(self):
        source = (ROOT / "runtime" / "packaged_launcher.py").read_text(encoding="utf-8")
        self.assertIn("log_config=None", source)

    def test_packaged_startup_failure_is_written_outside_install_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "YingjieHDDE" / "settings.json"
            try:
                raise RuntimeError("packaged-startup-probe")
            except RuntimeError as exc:
                with patch.object(packaged_launcher, "runtime_settings_path", return_value=settings):
                    packaged_launcher.write_startup_error(exc)
            error_log = settings.parent / "packaged_startup_error.log"
            self.assertTrue(error_log.is_file())
            self.assertIn("packaged-startup-probe", error_log.read_text(encoding="utf-8"))

    def test_windows_folder_dialog_uses_system_runtime_without_tkinter(self):
        completed = type("Completed", (), {"returncode": 0, "stdout": "D:\\影界文件\n", "stderr": ""})()
        with patch("runtime.windows_dialog.subprocess.run", return_value=completed) as run:
            self.assertEqual(select_directory("选择目录"), "D:\\影界文件")
        self.assertEqual(run.call_args.args[0][0], "powershell.exe")
        self.assertIn("HDDE_FOLDER_DIALOG_TITLE", run.call_args.kwargs["env"])

    def test_source_and_packaged_settings_are_separated(self):
        self.assertEqual(system_info.runtime_settings_path(), ROOT / "settings" / "settings.json")
        with (
            patch.object(system_info, "is_pyinstaller", return_value=True),
            patch.dict("os.environ", {"LOCALAPPDATA": r"C:\Users\tester\AppData\Local"}),
        ):
            self.assertEqual(
                system_info.runtime_settings_path(),
                Path(r"C:\Users\tester\AppData\Local") / "YingjieHDDE" / "settings.json",
            )

    def test_packaged_resource_contract_uses_product_version_and_current_dist(self):
        version = json.loads((ROOT / "product_version.json").read_text(encoding="utf-8"))
        with (
            patch.object(packaged_launcher, "resource_root", return_value=ROOT),
            patch.object(packaged_launcher, "PRODUCT_VERSION_PATH", ROOT / "product_version.json"),
        ):
            result = packaged_launcher.validate_packaged_resources()
        self.assertEqual(result["version"], version["display_version"])
        self.assertEqual(Path(result["frontend"]), ROOT / "dist" / "index.html")

    def test_formal_spec_targets_current_packaged_entry_and_resources(self):
        spec = (ROOT / "packaging" / "windows" / "HDDE.spec").read_text(encoding="utf-8")
        self.assertIn('packaged_main.py', spec)
        self.assertIn('program_resources.py', spec)
        self.assertIn('webview.platforms.edgechromium', spec)
        self.assertIn('name="影界 HDDE"', spec)
        self.assertNotIn("gui.app", spec)
        self.assertNotIn("VisualMasterPro.spec", spec)
        self.assertNotIn('collect_submodules("webview")', spec)
        self.assertIn('hookspath=[str(Path(SPECPATH) / "hooks")]', spec)
        hook = (ROOT / "packaging" / "windows" / "hooks" / "hook-webview.py").read_text(encoding="utf-8")
        self.assertIn("Microsoft.Web.WebView2.Core.dll", hook)
        self.assertIn("Microsoft.Web.WebView2.WinForms.dll", hook)
        self.assertIn("runtimes/win-arm64/native/WebView2Loader.dll", hook)
        self.assertIn("runtimes/win-x64/native/WebView2Loader.dll", hook)
        self.assertIn("runtimes/win-x86/native/WebView2Loader.dll", hook)
        self.assertNotIn("pywebview-android.jar", hook)
        self.assertNotIn("WebBrowserInterop", hook)

    def test_packaged_legacy_logs_use_local_app_data_instead_of_install_or_documents(self):
        from runtime import logger

        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "YingjieHDDE" / "settings.json"
            with (
                patch.object(logger, "is_pyinstaller", return_value=True),
                patch.object(logger, "runtime_settings_path", return_value=settings),
            ):
                self.assertEqual(logger.logs_dir(), settings.parent / "logs")

    def test_installer_does_not_manage_formal_user_data_root(self):
        script = (ROOT / "packaging" / "windows" / "HDDE.iss").read_text(encoding="utf-8")
        build_script = (ROOT / "packaging" / "windows" / "build_release.ps1").read_text(encoding="utf-8")
        self.assertNotIn(r"D:\影界文件", script)
        self.assertNotIn("[UninstallDelete]", script)
        self.assertNotIn("V0.5.9", script)
        self.assertIn("OutputBaseFilename={#PackageBaseName}", script)
        self.assertIn("影界 HDDE.exe", script)
        self.assertIn("--shutdown", script)
        self.assertIn("MicrosoftEdgeWebView2Setup.exe", script)
        self.assertIn("PrepareToInstall", script)
        self.assertIn("HasWebView2RuntimeFiles", script)
        self.assertIn("GetVersionNumbersString", script)
        self.assertIn("$Version.release_name", build_script)
        self.assertIn(r"packaging\windows\release\$PublicVersion\installer", build_script)
        self.assertIn("installer_data_gate.py", build_script)


if __name__ == "__main__":
    unittest.main()
