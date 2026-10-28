from __future__ import annotations

from pathlib import Path

import webview
from PyInstaller.utils.hooks import collect_data_files


WEBVIEW_ROOT = Path(webview.__file__).resolve().parent
datas = collect_data_files("webview", subdir="js")
for relative, destination in (
    ("lib/Microsoft.Web.WebView2.Core.dll", "webview/lib"),
    ("lib/Microsoft.Web.WebView2.WinForms.dll", "webview/lib"),
    ("lib/runtimes/win-arm64/native/WebView2Loader.dll", "webview/lib/runtimes/win-arm64/native"),
    ("lib/runtimes/win-x64/native/WebView2Loader.dll", "webview/lib/runtimes/win-x64/native"),
    ("lib/runtimes/win-x86/native/WebView2Loader.dll", "webview/lib/runtimes/win-x86/native"),
):
    source = WEBVIEW_ROOT / relative
    if not source.is_file():
        raise RuntimeError(f"Required EdgeChromium runtime file is missing: {source}")
    datas.append((str(source), destination))

binaries = []
