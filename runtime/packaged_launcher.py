from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import os
import signal
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from ctypes import wintypes
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from runtime.production_frontend import validate_production_frontend
from runtime.system_info import APP_VERSION, PRODUCT_VERSION_PATH, resource_root, runtime_settings_path


HOST = "127.0.0.1"
DEFAULT_PAGE = "/processing"
WINDOW_TITLE = "影界 HDDE"
EVENT_NAME = "Local\\YingjieHDDE_PackagedDesktop"
RUNTIME_ROOT_OVERRIDE_ENV = "HDDE_RUNTIME_ROOT_OVERRIDE"


class PackagedRuntimeError(RuntimeError):
    pass


def _runtime_state_root() -> Path:
    override = str(os.environ.get(RUNTIME_ROOT_OVERRIDE_ENV) or "").strip()
    return Path(override).expanduser().resolve() if override else runtime_settings_path().parent


def write_startup_error(exc: BaseException) -> None:
    try:
        path = _runtime_state_root() / "packaged_startup_error.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            encoding="utf-8",
        )
    except Exception:
        return


class _WindowsEvent:
    ERROR_ALREADY_EXISTS = 183
    EVENT_MODIFY_STATE = 0x0002

    def __init__(self, *, create: bool) -> None:
        self.handle = None
        self.already_exists = False
        if os.name != "nt":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateEventW.restype = wintypes.HANDLE
        kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.OpenEventW.restype = wintypes.HANDLE
        if create:
            ctypes.set_last_error(0)
            handle = kernel32.CreateEventW(None, True, False, EVENT_NAME)
            self.already_exists = ctypes.get_last_error() == self.ERROR_ALREADY_EXISTS
        else:
            handle = kernel32.OpenEventW(self.EVENT_MODIFY_STATE, False, EVENT_NAME)
        self.handle = handle or None

    def signal(self) -> bool:
        if not self.handle:
            return False
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.SetEvent.argtypes = [wintypes.HANDLE]
        kernel32.SetEvent.restype = wintypes.BOOL
        return bool(kernel32.SetEvent(self.handle))

    def is_signaled(self) -> bool:
        if not self.handle:
            return False
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        return kernel32.WaitForSingleObject(self.handle, 0) == 0

    def close(self) -> None:
        if self.handle:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self.handle)
            self.handle = None


def validate_packaged_resources() -> dict[str, str]:
    root = resource_root()
    validate_production_frontend(root / "dist")
    if not PRODUCT_VERSION_PATH.is_file():
        raise PackagedRuntimeError(f"产品版本事实源不存在：{PRODUCT_VERSION_PATH}")
    required = (
        root / "engine" / "batch_watermark" / "fonts",
        root / "models" / "local_retouch" / "inpainting_lama_2025jan.onnx",
        root / "rules",
        root / "modes",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise PackagedRuntimeError("运行资源不完整：" + "；".join(missing))
    return {
        "version": APP_VERSION,
        "resource_root": str(root),
        "frontend": str(root / "dist" / "index.html"),
    }


def reserve_loopback_socket(preferred_port: int = 0) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind((HOST, preferred_port))
        listener.set_inheritable(True)
        return listener
    except Exception:
        listener.close()
        raise


def _read_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=1) as response:
        if response.status != 200:
            raise PackagedRuntimeError(f"Backend 返回非预期状态：{response.status}")
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise PackagedRuntimeError("Backend 返回了无效 JSON。")
    return payload


def _health_contract_valid(payload: dict[str, Any], port: int) -> bool:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return bool(
        payload.get("code") == 200
        and payload.get("status") == "success"
        and payload.get("success") is True
        and data.get("healthy") is True
        and data.get("version") == APP_VERSION
        and data.get("host") == HOST
        and data.get("port") == port
    )


def _runtime_contract_valid(payload: dict[str, Any], port: int) -> bool:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    product = data.get("product") if isinstance(data.get("product"), dict) else {}
    application = data.get("application") if isinstance(data.get("application"), dict) else {}
    return bool(
        payload.get("code") == 200
        and payload.get("status") == "success"
        and payload.get("success") is True
        and data.get("status") == "ready"
        and product.get("version") == APP_VERSION
        and product.get("build_status") == "loaded"
        and application.get("status") == "running"
        and application.get("host") == HOST
        and application.get("port") == port
    )


def _wait_until_ready(base_url: str, port: int, server, timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        if not server_thread_alive(server):
            raise PackagedRuntimeError("正式 Backend 在就绪前退出。")
        try:
            health = _read_json(f"{base_url}/api/health")
            runtime = _read_json(f"{base_url}/api/runtime/status")
            if _health_contract_valid(health, port) and _runtime_contract_valid(runtime, port):
                return {"health": health, "runtime": runtime}
            last_error = "Backend 已响应，但健康、版本或正式运行状态合同未成立。"
        except (OSError, ValueError, urllib.error.URLError, PackagedRuntimeError) as exc:
            last_error = str(exc)
        time.sleep(0.2)
    raise PackagedRuntimeError(f"正式 Backend 未在 {timeout:g} 秒内就绪：{last_error}")


def server_thread_alive(server) -> bool:
    thread = getattr(server, "_hdde_thread", None)
    return bool(thread and thread.is_alive())


def request_shutdown() -> int:
    event = _WindowsEvent(create=False)
    try:
        if not event.handle:
            return 1
        return 0 if event.signal() else 1
    finally:
        event.close()


def _validate_isolated_runtime_root(value: str | Path) -> Path:
    root = Path(value).expanduser()
    if not root.is_absolute():
        raise PackagedRuntimeError("自动验证运行目录必须使用绝对路径。")
    root = root.resolve()
    protected = (resource_root().resolve(), Path("D:/影界文件").resolve())
    for candidate in protected:
        if root == candidate or candidate in root.parents or root in candidate.parents:
            raise PackagedRuntimeError(f"自动验证运行目录与受保护目录重叠：{root}")
    return root


def configure_validation_runtime(main_module: ModuleType, value: str | Path) -> tuple[Path, Path]:
    runtime_root = _validate_isolated_runtime_root(value)
    formal_root = runtime_root / "formal-root"
    formal_root.mkdir(parents=True, exist_ok=True)
    settings_path = runtime_root / ".hdde-validation-settings.json"
    settings = dict(main_module.default_settings())
    settings.update(
        {
            "app_data_root": str(formal_root),
            "last_app_data_root": str(formal_root),
            "default_output_dir": str(formal_root / main_module.DEFAULT_OUTPUT_DIR_NAME),
            "image_compression_default_output_root": str(
                formal_root / main_module.IMAGE_COMPRESSION_OUTPUT_DIR_NAME
            ),
            "last_output_dir": str(formal_root / main_module.DEFAULT_OUTPUT_DIR_NAME),
        }
    )
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    os.environ[RUNTIME_ROOT_OVERRIDE_ENV] = str(runtime_root)
    main_module.SETTINGS_PATH = settings_path
    main_module._VALIDATION_FORMAL_ROOT = formal_root
    return runtime_root, formal_root


def _write_validation_evidence(path: Path | None, **fields: Any) -> None:
    if path is None:
        return
    payload: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload.update(loaded)
        except Exception:
            pass
    payload.update(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_desktop_window(
    url: str,
    stop_requested: threading.Event,
    should_close: Callable[[], bool],
    *,
    storage_root: Path,
    evidence_path: Path | None = None,
    webview_module=None,
) -> None:
    if webview_module is None:
        import webview as webview_module

    errors: list[str] = []
    window = webview_module.create_window(
        WINDOW_TITLE,
        url,
        width=1440,
        height=900,
        min_size=(1024, 720),
        resizable=True,
        background_color="#F5F7FA",
        text_select=True,
    )
    if window is None:
        raise PackagedRuntimeError("无法创建影界 HDDE 桌面窗口。")

    def on_shown(window=None):
        renderer = str(getattr(webview_module, "renderer", "") or "")
        _write_validation_evidence(evidence_path, window_shown=True, renderer=renderer, window_title=WINDOW_TITLE)
        if renderer != "edgechromium":
            errors.append(f"桌面窗口未使用 EdgeChromium：{renderer or 'unknown'}")
            if window is not None:
                window.destroy()

    initial_load_checked = False

    def on_loaded(window=None):
        nonlocal initial_load_checked
        # Startup readiness is checked once; later loads belong to user navigation.
        if initial_load_checked:
            return
        initial_load_checked = True
        current_url = window.get_current_url() if window is not None else ""
        page = {}
        if window is not None:
            try:
                page = window.evaluate_js(
                    "({path: window.location.pathname, title: document.title, readyState: document.readyState})"
                ) or {}
            except Exception as exc:
                errors.append(f"无法读取桌面页面状态：{exc}")
        _write_validation_evidence(
            evidence_path,
            window_loaded=True,
            current_url=current_url,
            page_path=str(page.get("path") or "") if isinstance(page, dict) else "",
            document_title=str(page.get("title") or "") if isinstance(page, dict) else "",
            document_ready_state=str(page.get("readyState") or "") if isinstance(page, dict) else "",
        )
        if not current_url.endswith(DEFAULT_PAGE) or not isinstance(page, dict) or page.get("path") != DEFAULT_PAGE:
            errors.append(f"桌面窗口未加载 {DEFAULT_PAGE}：{current_url}")
            if window is not None:
                window.destroy()

    def on_closed():
        stop_requested.set()
        _write_validation_evidence(evidence_path, window_closed=True)

    def watch_owned_runtime():
        while not stop_requested.wait(0.2):
            if should_close():
                stop_requested.set()
                try:
                    window.destroy()
                except Exception:
                    pass
                return

    window.events.shown += on_shown
    window.events.loaded += on_loaded
    window.events.closed += on_closed
    storage_root.mkdir(parents=True, exist_ok=True)
    webview_module.start(
        func=watch_owned_runtime,
        gui="edgechromium",
        debug=False,
        private_mode=True,
        storage_path=str(storage_root),
    )
    stop_requested.set()
    if errors:
        raise PackagedRuntimeError("；".join(errors))


def packaged_backend_loop_factory() -> asyncio.AbstractEventLoop:
    # This in-process Windows backend uses socket I/O, not asyncio subprocesses.
    # Proactor connection_lost can skip server detach after WinError 10054,
    # leaving Server.wait_closed pending even when Uvicorn has no live tasks.
    return asyncio.SelectorEventLoop()


def run_packaged_runtime(
    *,
    preferred_port: int = 0,
    validation_runtime_root: str | Path | None = None,
) -> int:
    if os.name != "nt":
        raise PackagedRuntimeError("正式安装版当前仅支持 Windows。")
    validate_packaged_resources()
    lifecycle = _WindowsEvent(create=True)
    if lifecycle.already_exists:
        lifecycle.close()
        return 0
    if not lifecycle.handle:
        raise PackagedRuntimeError("无法创建正式运行生命周期事件。")

    listener: socket.socket | None = None
    server = None
    thread = None
    stop_requested = threading.Event()
    evidence_path: Path | None = None
    previous_handlers: dict[int, Any] = {}

    def handle_stop(_signum, _frame):
        stop_requested.set()

    try:
        listener = reserve_loopback_socket(preferred_port)
        port = int(listener.getsockname()[1])

        import uvicorn
        import main as main_module

        runtime_root = None
        if validation_runtime_root is not None:
            runtime_root, _formal_root = configure_validation_runtime(main_module, validation_runtime_root)
            evidence_path = runtime_root / "w60_02_desktop_runtime.json"

        app = main_module.build_web_app(runtime_host=HOST, runtime_port=port)
        config = uvicorn.Config(
            app,
            host=HOST,
            port=port,
            log_level="info",
            log_config=None,
            access_log=False,
            loop="runtime.packaged_launcher:packaged_backend_loop_factory",
            timeout_graceful_shutdown=5,
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(
            target=server.run,
            kwargs={"sockets": [listener]},
            name="HDDE-Packaged-Backend",
            daemon=False,
        )
        server._hdde_thread = thread

        for sig in (signal.SIGINT, getattr(signal, "SIGBREAK", signal.SIGTERM), signal.SIGTERM):
            try:
                previous_handlers[sig] = signal.signal(sig, handle_stop)
            except (OSError, ValueError):
                continue

        thread.start()
        base_url = f"http://{HOST}:{port}"
        ready = _wait_until_ready(base_url, port, server)
        _write_validation_evidence(
            evidence_path,
            process_id=os.getpid(),
            host=HOST,
            port=port,
            backend_ready=True,
            health_version=ready["health"]["data"]["version"],
            runtime_status=ready["runtime"]["data"]["status"],
        )
        run_desktop_window(
            f"{base_url}{DEFAULT_PAGE}",
            stop_requested,
            lambda: lifecycle.is_signaled() or not server_thread_alive(server),
            storage_root=(runtime_root / "webview") if runtime_root is not None else runtime_settings_path().parent / "webview",
            evidence_path=evidence_path,
        )
        server.should_exit = True
        thread.join(timeout=15)
        if thread.is_alive():
            raise PackagedRuntimeError("正式 Backend 未能正常退出。")
        _write_validation_evidence(evidence_path, backend_stopped=True, shutdown_complete=True)
        return 0
    finally:
        stop_requested.set()
        if server is not None:
            server.should_exit = True
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        if listener is not None:
            listener.close()
        lifecycle.close()
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"影界 HDDE {APP_VERSION} 正式桌面入口")
    parser.add_argument("--shutdown", action="store_true", help="正常退出正在运行的影界 HDDE。")
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--validation-runtime-root", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.shutdown:
        return request_shutdown()
    if args.self_test:
        resources = validate_packaged_resources()
        print(f"HDDE_PACKAGED_SELF_TEST=PASS VERSION={resources['version']}")
        return 0
    return run_packaged_runtime(preferred_port=args.port, validation_runtime_root=args.validation_runtime_root)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        from runtime.error_dialog import show_error_dialog

        show_error_dialog("影界 HDDE 启动失败", str(exc))
        raise
