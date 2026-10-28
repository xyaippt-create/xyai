from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections import deque
from ctypes import wintypes
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
VITE_ENTRY = PROJECT_ROOT / "node_modules" / "vite" / "bin" / "vite.js"
BACKEND_PORT = 8787
FRONTEND_PORT = 5173
STATE_PATH = PROJECT_ROOT / "logs" / ".hdde_formal_runtime.json"
SETTINGS_PATH = PROJECT_ROOT / "settings" / "settings.json"
LIFECYCLE_CURRENT_NAME = "formal_runtime_lifecycle.json"
LIFECYCLE_HISTORY_NAME = "formal_runtime_lifecycle.jsonl"
BACKEND_TAIL_LINE_LIMIT = 80
EVENT_NAME = "Local\\HDDE_VisualMasterPro_" + hashlib.sha256(
    str(PROJECT_ROOT).lower().encode("utf-8")
).hexdigest()[:16]


class FormalStartupError(RuntimeError):
    pass


class _BackendOutputCapture:
    def __init__(self, process: subprocess.Popen, combined_log) -> None:
        self.process = process
        self.combined_log = combined_log
        self.stdout_tail: deque[str] = deque(maxlen=BACKEND_TAIL_LINE_LIMIT)
        self.stderr_tail: deque[str] = deque(maxlen=BACKEND_TAIL_LINE_LIMIT)
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    def _pump(self, stream, tail: deque[str]) -> None:
        if stream is None:
            return
        try:
            for line in iter(stream.readline, ""):
                tail.append(line.rstrip("\r\n"))
                with self._lock:
                    self.combined_log.write(line)
                    self.combined_log.flush()
        finally:
            stream.close()

    def start(self) -> None:
        for name, stream, tail in (
            ("stdout", self.process.stdout, self.stdout_tail),
            ("stderr", self.process.stderr, self.stderr_tail),
        ):
            thread = threading.Thread(
                target=self._pump,
                args=(stream, tail),
                name=f"HDDE-Backend-{name}-Capture",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def join(self, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        for thread in self._threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _resolve_lifecycle_paths(settings_path: Path | None = None) -> tuple[Path, Path] | None:
    path = settings_path or SETTINGS_PATH
    try:
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    for key in ("app_data_root", "last_app_data_root"):
        value = str(settings.get(key) or "").strip()
        if not value:
            continue
        try:
            formal_root = Path(value).expanduser().resolve()
        except OSError:
            continue
        if not formal_root.is_dir():
            continue
        log_dir = formal_root / "诊断" / "日志"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        return log_dir / LIFECYCLE_CURRENT_NAME, log_dir / LIFECYCLE_HISTORY_NAME
    return None


def _sanitize_output_tail(lines: deque[str] | list[str]) -> list[str]:
    try:
        from engine.diagnostics.runtime_logging import sanitize_diagnostic_value
    except Exception:
        return ["DIAGNOSTIC_SANITIZATION_UNAVAILABLE"] if lines else []
    return [sanitize_diagnostic_value(line) for line in lines if str(line).strip()]


def _last_backend_context(stdout_tail: deque[str], stderr_tail: deque[str]) -> dict[str, str | None]:
    fields = {
        "last_operation_id": "operation_id",
        "last_trace_id": "trace_id",
        "last_task_id": "task_id",
        "last_route": "route",
        "last_stage": "stage",
    }
    context: dict[str, str | None] = {name: None for name in fields}
    lines = list(stdout_tail) + list(stderr_tail)
    for line in reversed(lines):
        for output_name, log_name in fields.items():
            if context[output_name] is not None:
                continue
            match = re.search(rf"(?:^|\s|\|){re.escape(log_name)}=([^|\r\n]+)", line)
            if match:
                value = match.group(1).strip()
                context[output_name] = value or None
        if all(value is not None for value in context.values()):
            break
    return context


def _write_lifecycle_snapshot(
    paths: tuple[Path, Path] | None,
    record: dict,
    *,
    append_history: bool,
) -> bool:
    if paths is None:
        return False
    current_path, history_path = paths
    payload = json.dumps(record, ensure_ascii=False, indent=2)
    temporary = current_path.with_name(f".{current_path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(current_path)
        if append_history:
            with history_path.open("a", encoding="utf-8") as history:
                history.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return True
    except OSError:
        temporary.unlink(missing_ok=True)
        return False


def _archive_unfinished_lifecycle(paths: tuple[Path, Path] | None) -> None:
    if paths is None:
        return
    current_path, _ = paths
    try:
        previous = json.loads(current_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if previous.get("status") not in {"STARTING", "RUNNING"}:
        return
    previous.update(
        {
            "status": "EXITED_WITHOUT_FINALIZATION",
            "exit_at": _now_iso(),
            "exit_code": None,
            "exit_reason": "LAUNCHER_TERMINATED_WITHOUT_FINALIZATION",
        }
    )
    _write_lifecycle_snapshot(paths, previous, append_history=True)


def _same_path(left: str | Path, right: str | Path) -> bool:
    try:
        return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))
    except OSError:
        return False


def require_project_python() -> Path:
    if not PROJECT_PYTHON.is_file():
        raise FormalStartupError(f"项目运行环境不存在：{PROJECT_PYTHON}")
    return PROJECT_PYTHON


def resolve_node() -> Path:
    node = shutil.which("node.exe") or shutil.which("node")
    if not node:
        raise FormalStartupError("未找到 Node.js，无法启动正式前端。")
    if not VITE_ENTRY.is_file():
        raise FormalStartupError(f"前端依赖不完整：{VITE_ENTRY}")
    return Path(node).resolve()


def backend_command() -> list[str]:
    return [
        str(require_project_python()),
        "-u",
        str(PROJECT_ROOT / "main.py"),
        "--server",
        "--host",
        "127.0.0.1",
        "--port",
        str(BACKEND_PORT),
    ]


def frontend_command() -> list[str]:
    return [
        str(resolve_node()),
        str(VITE_ENTRY),
        "--host",
        "127.0.0.1",
        "--port",
        str(FRONTEND_PORT),
        "--strictPort",
    ]


def verify_formal_dependencies() -> None:
    probe = (
        "import cv2, fastapi, numpy, onnxruntime, PIL, uvicorn; "
        "from backend.local_retouch_api import register_local_retouch_routes"
    )
    completed = subprocess.run(
        [str(require_project_python()), "-c", probe],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if completed.returncode:
        reason = (completed.stderr or completed.stdout or "未知依赖错误").strip()
        raise FormalStartupError(f"项目运行环境依赖检查失败：{reason}")


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _listener_info(port: int) -> dict | None:
    script = (
        f"$c=Get-NetTCPConnection -State Listen -LocalPort {port} -ErrorAction SilentlyContinue | "
        "Select-Object -First 1; if($c){$p=Get-CimInstance Win32_Process "
        "-Filter ('ProcessId=' + $c.OwningProcess) -ErrorAction SilentlyContinue; "
        "[pscustomobject]@{pid=$c.OwningProcess;name=$p.Name;parent=$p.ParentProcessId;"
        "command=$p.CommandLine;executable=$p.ExecutablePath}|ConvertTo-Json -Compress}"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        output = completed.stdout.strip()
        return json.loads(output) if completed.returncode == 0 and output else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None


def _load_state() -> dict:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if data.get("project_root") == str(PROJECT_ROOT) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _is_confirmed_hdde_listener(info: dict | None, port: int, state: dict) -> bool:
    if not info or not info.get("pid"):
        return False
    command = str(info.get("command") or "").replace("/", "\\").lower()
    root = str(PROJECT_ROOT).replace("/", "\\").lower()
    state_key = "backend_pid" if port == BACKEND_PORT else "frontend_pid"
    state_matches = int(state.get(state_key) or -1) == int(info["pid"])
    if port == BACKEND_PORT:
        signature_matches = root in command and "main.py" in command and "--server" in command
        executable_matches = _same_path(str(info.get("executable") or ""), PROJECT_PYTHON)
    else:
        signature_matches = root in command and "node_modules\\vite\\bin\\vite.js" in command
        try:
            executable_matches = _same_path(str(info.get("executable") or ""), resolve_node())
        except FormalStartupError:
            executable_matches = False
    return bool(signature_matches and (state_matches or executable_matches))


def _terminate_confirmed_tree(pid: int) -> None:
    completed = subprocess.run(
        ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    if completed.returncode and "not found" not in (completed.stderr or "").lower():
        raise FormalStartupError(f"无法清理已确认的 HDDE 历史进程 PID {pid}。")


def ensure_ports_available() -> list[int]:
    cleaned: list[int] = []
    state = _load_state()
    for port in (BACKEND_PORT, FRONTEND_PORT):
        if _port_is_free(port):
            continue
        info = _listener_info(port)
        if not _is_confirmed_hdde_listener(info, port, state):
            owner = f"PID {info.get('pid')} ({info.get('name')})" if info else "未知进程"
            raise FormalStartupError(f"端口 {port} 已被非确认 HDDE 进程占用：{owner}。未执行强制清理。")
        _terminate_confirmed_tree(int(info["pid"]))
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not _port_is_free(port):
            time.sleep(0.2)
        if not _port_is_free(port):
            raise FormalStartupError(f"已确认的 HDDE 历史进程结束后，端口 {port} 仍未释放。")
        cleaned.append(int(info["pid"]))
    if STATE_PATH.exists() and all(_port_is_free(port) for port in (BACKEND_PORT, FRONTEND_PORT)):
        STATE_PATH.unlink(missing_ok=True)
    return cleaned


class _WindowsEvent:
    ERROR_ALREADY_EXISTS = 183
    EVENT_MODIFY_STATE = 0x0002
    SYNCHRONIZE = 0x00100000
    WAIT_OBJECT_0 = 0

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
            if not handle:
                raise FormalStartupError("无法创建 HDDE 运行生命周期事件。")
            self.already_exists = ctypes.get_last_error() == self.ERROR_ALREADY_EXISTS
        else:
            handle = kernel32.OpenEventW(self.EVENT_MODIFY_STATE | self.SYNCHRONIZE, False, EVENT_NAME)
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
        return kernel32.WaitForSingleObject(self.handle, 0) == self.WAIT_OBJECT_0

    def close(self) -> None:
        if self.handle:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.CloseHandle(self.handle)
            self.handle = None


class _WindowsJob:
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

    def __init__(self) -> None:
        self.handle = None
        if os.name != "nt":
            return

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class BASIC_LIMITS(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED_LIMITS(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMITS),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise FormalStartupError("无法创建 HDDE 子进程作业对象。")
        limits = EXTENDED_LIMITS()
        limits.BasicLimitInformation.LimitFlags = self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle,
            self.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            kernel32.CloseHandle(handle)
            raise FormalStartupError("无法设置 HDDE 子进程清理策略。")
        self.handle = handle

    def assign(self, process: subprocess.Popen) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        if self.handle and not kernel32.AssignProcessToJobObject(self.handle, wintypes.HANDLE(process._handle)):
            raise FormalStartupError(f"无法接管 HDDE 子进程 PID {process.pid}。")

    def close(self) -> None:
        if self.handle:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.CloseHandle(self.handle)
            self.handle = None


def _write_state(
    backend: subprocess.Popen | None,
    frontend: subprocess.Popen | None,
    *,
    backend_listener_pid: int | None = None,
    frontend_listener_pid: int | None = None,
) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "project_root": str(PROJECT_ROOT),
        "launcher_pid": os.getpid(),
        "backend_pid": backend_listener_pid or (backend.pid if backend else None),
        "backend_process_pid": backend.pid if backend else None,
        "frontend_pid": frontend_listener_pid or (frontend.pid if frontend else None),
        "frontend_process_pid": frontend.pid if frontend else None,
        "project_python": str(PROJECT_PYTHON),
        "started_at": time.time(),
    }
    STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _wait_http(url: str, process: subprocess.Popen, timeout: float) -> dict | str:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise FormalStartupError(f"子进程在服务就绪前退出，退出码 {process.returncode}：{url}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                body = response.read().decode("utf-8", errors="replace")
                if response.status == 200:
                    try:
                        return json.loads(body)
                    except json.JSONDecodeError:
                        return body
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise FormalStartupError(f"服务未在 {timeout:.0f} 秒内就绪：{url}；最后错误：{last_error}")


def _stop_owned_process(process: subprocess.Popen | None) -> None:
    if not process or process.poll() is not None:
        return
    try:
        os.kill(process.pid, signal.CTRL_BREAK_EVENT)
        process.wait(timeout=5)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        _terminate_confirmed_tree(process.pid)


def request_shutdown() -> int:
    event = _WindowsEvent(create=False)
    try:
        if not event.handle:
            print("影界 HDDE 当前没有由正式启动器管理的运行实例。", flush=True)
            return 1
        if not event.signal():
            raise FormalStartupError("无法向影界 HDDE 运行实例发送正常退出信号。")
        print("已请求影界 HDDE 正常退出。", flush=True)
        return 0
    finally:
        event.close()


def run_formal_desktop(*, open_browser: bool = True, startup_timeout: float = 45.0) -> int:
    if os.name != "nt":
        raise FormalStartupError("当前正式启动入口仅支持 Windows。")
    require_project_python()
    resolve_node()
    verify_formal_dependencies()

    lifecycle_event = _WindowsEvent(create=True)
    if lifecycle_event.already_exists:
        lifecycle_event.close()
        raise FormalStartupError("影界 HDDE 已由正式启动器运行，请勿重复启动。")

    backend = None
    frontend = None
    job = None
    backend_log = None
    frontend_log = None
    backend_capture = None
    backend_listener_pid = None
    lifecycle_paths = _resolve_lifecycle_paths()
    lifecycle_started_at = _now_iso()
    runtime_id = None
    exit_reason = "STARTUP_FAILURE"
    launcher_error = None
    backend_exited_before_shutdown = False
    stop_signal = None
    stop_requested = threading.Event()

    def handle_stop(_signum, _frame):
        nonlocal stop_signal
        try:
            stop_signal = signal.Signals(_signum).name
        except ValueError:
            stop_signal = str(_signum)
        stop_requested.set()

    previous_handlers = {}
    for sig in (signal.SIGINT, getattr(signal, "SIGBREAK", signal.SIGTERM), signal.SIGTERM):
        previous_handlers[sig] = signal.signal(sig, handle_stop)

    try:
        _archive_unfinished_lifecycle(lifecycle_paths)
        cleaned = ensure_ports_available()
        if cleaned:
            print(f"已安全清理历史 HDDE 进程：{', '.join(map(str, cleaned))}", flush=True)

        log_dir = PROJECT_ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        backend_log = (log_dir / "formal_backend.log").open("a", encoding="utf-8")
        frontend_log = (log_dir / "formal_frontend.log").open("a", encoding="utf-8")
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        job = _WindowsJob()

        backend = subprocess.Popen(
            backend_command(),
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        backend_capture = _BackendOutputCapture(backend, backend_log)
        backend_capture.start()
        job.assign(backend)
        _write_state(backend, None)
        _write_lifecycle_snapshot(
            lifecycle_paths,
            {
                "status": "STARTING",
                "runtime_id": None,
                "launcher_pid": os.getpid(),
                "backend_pid": backend.pid,
                "backend_process_pid": backend.pid,
                "started_at": lifecycle_started_at,
                "exit_at": None,
                "exit_code": None,
                "exit_reason": None,
                "stdout_tail": [],
                "stderr_tail": [],
            },
            append_history=False,
        )
        health = _wait_http(f"http://127.0.0.1:{BACKEND_PORT}/api/health", backend, startup_timeout)
        runtime_status = _wait_http(
            f"http://127.0.0.1:{BACKEND_PORT}/api/runtime/status", backend, startup_timeout
        )
        backend_listener_pid = int(runtime_status["data"]["application"]["process_id"])
        runtime_id = str(runtime_status["data"]["application"].get("runtime_id") or "") or None
        _write_state(backend, None, backend_listener_pid=backend_listener_pid)
        _write_lifecycle_snapshot(
            lifecycle_paths,
            {
                "status": "RUNNING",
                "runtime_id": runtime_id,
                "launcher_pid": os.getpid(),
                "backend_pid": backend_listener_pid,
                "backend_process_pid": backend.pid,
                "started_at": lifecycle_started_at,
                "exit_at": None,
                "exit_code": None,
                "exit_reason": None,
                "stdout_tail": [],
                "stderr_tail": [],
            },
            append_history=False,
        )

        frontend = subprocess.Popen(
            frontend_command(),
            cwd=PROJECT_ROOT,
            env={**os.environ, "HDDE_API_TARGET": f"http://127.0.0.1:{BACKEND_PORT}"},
            stdin=subprocess.DEVNULL,
            stdout=frontend_log,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        job.assign(frontend)
        _write_state(
            backend,
            frontend,
            backend_listener_pid=backend_listener_pid,
            frontend_listener_pid=frontend.pid,
        )
        _wait_http(f"http://127.0.0.1:{FRONTEND_PORT}/", frontend, startup_timeout)
        proxy_health = _wait_http(f"http://127.0.0.1:{FRONTEND_PORT}/api/health", frontend, startup_timeout)
        print(
            "HDDE_READY "
            + json.dumps(
                {
                    "backend_pid": backend_listener_pid,
                    "frontend_pid": frontend.pid,
                    "python": str(PROJECT_PYTHON),
                    "backend_health": health.get("status") if isinstance(health, dict) else "ok",
                    "proxy_health": proxy_health.get("status") if isinstance(proxy_health, dict) else "ok",
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if open_browser:
            webbrowser.open(f"http://127.0.0.1:{FRONTEND_PORT}/processing")

        exit_reason = "UNKNOWN"
        while True:
            if stop_requested.is_set():
                exit_reason = f"LAUNCHER_SIGNAL_{stop_signal or 'UNKNOWN'}"
                break
            if lifecycle_event.is_signaled():
                exit_reason = "LIFECYCLE_STOP_REQUEST"
                break
            if backend.poll() is not None:
                exit_reason = "BACKEND_PROCESS_EXIT"
                backend_exited_before_shutdown = True
                raise FormalStartupError(f"正式后端意外退出，退出码 {backend.returncode}。")
            if frontend.poll() is not None:
                exit_reason = "FRONTEND_PROCESS_EXIT"
                raise FormalStartupError(f"正式前端意外退出，退出码 {frontend.returncode}。")
            time.sleep(0.25)
        return 0
    except BaseException as exc:
        if exit_reason in {"STARTUP_FAILURE", "UNKNOWN"}:
            exit_reason = f"LAUNCHER_EXCEPTION_{type(exc).__name__}"
        launcher_error = str(exc)
        raise
    finally:
        _stop_owned_process(frontend)
        _stop_owned_process(backend)
        if backend_capture:
            backend_capture.join()
        if backend:
            stdout_tail = backend_capture.stdout_tail if backend_capture else deque()
            stderr_tail = backend_capture.stderr_tail if backend_capture else deque()
            final_record = {
                "status": "EXITED",
                "runtime_id": runtime_id,
                "launcher_pid": os.getpid(),
                "backend_pid": backend_listener_pid or backend.pid,
                "backend_process_pid": backend.pid,
                "started_at": lifecycle_started_at,
                "exit_at": _now_iso(),
                "exit_code": backend.poll(),
                "exit_reason": exit_reason,
                "backend_exit_observed_before_launcher_shutdown": backend_exited_before_shutdown,
                "launcher_error": (
                    _sanitize_output_tail(deque([launcher_error]))[0]
                    if launcher_error
                    else None
                ),
                "stdout_tail": _sanitize_output_tail(stdout_tail),
                "stderr_tail": _sanitize_output_tail(stderr_tail),
                **_last_backend_context(stdout_tail, stderr_tail),
            }
            if not _write_lifecycle_snapshot(lifecycle_paths, final_record, append_history=True):
                print("影界 HDDE 未能写入正式运行生命周期证据。", file=sys.stderr, flush=True)
        if job:
            job.close()
        if frontend_log:
            frontend_log.close()
        if backend_log:
            backend_log.close()
        STATE_PATH.unlink(missing_ok=True)
        lifecycle_event.close()
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="影界HDDE", description="影界 HDDE 正式本地运行入口。")
    parser.add_argument("--no-browser", action="store_true", help="启动服务但不自动打开浏览器。")
    parser.add_argument("--stop", action="store_true", help="请求当前正式实例正常退出。")
    parser.add_argument("--startup-timeout", type=float, default=45.0, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.stop:
            return request_shutdown()
        return run_formal_desktop(open_browser=not args.no_browser, startup_timeout=args.startup_timeout)
    except FormalStartupError as exc:
        print(f"影界 HDDE 启动失败：{exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
