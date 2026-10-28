from __future__ import annotations

import os
import subprocess


class WindowsDialogError(RuntimeError):
    pass


def select_directory(title: str) -> str:
    if os.name != "nt":
        raise WindowsDialogError("目录选择器仅支持 Windows。")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$dialog=New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$dialog.Description=$env:HDDE_FOLDER_DIALOG_TITLE; "
        "$dialog.ShowNewFolderButton=$true; "
        "if($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK)"
        "{[Console]::OutputEncoding=[Text.Encoding]::UTF8; Write-Output $dialog.SelectedPath}"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-STA", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "HDDE_FOLDER_DIALOG_TITLE": str(title)},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=300,
        check=False,
    )
    if completed.returncode:
        reason = (completed.stderr or completed.stdout or "unknown error").strip()
        raise WindowsDialogError(f"打开目录选择器失败：{reason}")
    return completed.stdout.strip()
