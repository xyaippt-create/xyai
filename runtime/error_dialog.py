from __future__ import annotations

import ctypes
import os


def show_error_dialog(title: str, message: str) -> None:
    if os.environ.get("VISUALMASTERPRO_DISABLE_DIALOG") == "1":
        return
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showerror(title, message)
        root.destroy()
        return
    except Exception:
        pass

    try:
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        return


def show_info_dialog(title: str, message: str) -> None:
    if os.environ.get("VISUALMASTERPRO_DISABLE_DIALOG") == "1":
        return
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showinfo(title, message)
        root.destroy()
        return
    except Exception:
        pass

    try:
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x40)
    except Exception:
        return
