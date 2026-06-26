from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path

from batch.batch_processor import collect_image_paths, process_batch
from engine.io import read_image
from gui.components import default_output_dir, format_size, output_naming_rule
from gui.gui_state import GuiState, ImageItem
from gui.help_system import read_help_topic
from gui.powershell_fallback import run_powershell_gui
from runtime.crash_handler import handle_exception, install_global_exception_hook
from runtime.logger import logs_dir
from runtime.user_settings import has_seen_quick_guide, mark_quick_guide_seen


MODE_LABELS = {
    "fidelity": "原图忠实增强",
    "text_safe": "文字保护增强",
    "ai_image_clean": "AI图像清洁增强",
    "sharp_4k": "4K清晰增强",
}


class VisualMasterProApp:
    def __init__(self, root: Tk):
        self.root = root
        self.state = GuiState(output_dir=default_output_dir())
        self.mode_var = StringVar(value="fidelity")
        self.scale_var = StringVar(value="2")
        self.format_var = StringVar(value="png")
        self.output_var = StringVar(value=str(self.state.output_dir))
        self.current_var = StringVar(value="等待开始")
        self.count_var = StringVar(value="已选择 0 张图片")
        self.progress_var = StringVar(value="成功 0 / 失败 0 / 等待 0")
        self.progress = None
        self.listbox = None
        self.logbox = None
        self._build()
        self.root.after(600, self.show_first_launch_guide)

    def _build(self) -> None:
        self.root.title("影界 HDDE V0.3")
        self.root.geometry("980x720")
        self._build_menu()

        header = Frame(self.root, padx=16, pady=12)
        header.pack(fill="x")
        Label(header, text="影界 HDDE V0.3", font=("Microsoft YaHei UI", 18, "bold")).pack(anchor=W)
        Label(header, text="HD Delivery Engine · 中文视觉高清交付引擎", font=("Microsoft YaHei UI", 10)).pack(anchor=W)

        input_frame = ttk.LabelFrame(self.root, text="输入图片", padding=10)
        input_frame.pack(fill="both", padx=16, pady=8)
        toolbar = Frame(input_frame)
        toolbar.pack(fill="x")
        Button(toolbar, text="添加图片", command=self.add_images).pack(side=LEFT, padx=4)
        Button(toolbar, text="选择文件夹", command=self.add_folder).pack(side=LEFT, padx=4)
        Button(toolbar, text="清空列表", command=self.clear_images).pack(side=LEFT, padx=4)
        Label(toolbar, textvariable=self.count_var).pack(side=LEFT, padx=12)
        self.listbox = Listbox(input_frame, height=10)
        self.listbox.pack(fill=BOTH, expand=True, pady=8)

        output_frame = ttk.LabelFrame(self.root, text="输出设置", padding=10)
        output_frame.pack(fill="x", padx=16, pady=8)
        Button(output_frame, text="选择输出文件夹", command=self.choose_output).pack(side=LEFT, padx=4)
        Label(output_frame, textvariable=self.output_var).pack(side=LEFT, padx=8)
        Label(output_frame, text=output_naming_rule()).pack(side=RIGHT, padx=8)

        setting_frame = ttk.LabelFrame(self.root, text="增强设置", padding=10)
        setting_frame.pack(fill="x", padx=16, pady=8)
        ttk.Label(setting_frame, text="模式").pack(side=LEFT, padx=4)
        ttk.Combobox(setting_frame, textvariable=self.mode_var, values=list(MODE_LABELS), state="readonly", width=18).pack(side=LEFT, padx=4)
        ttk.Label(setting_frame, text="放大倍率").pack(side=LEFT, padx=12)
        ttk.Combobox(setting_frame, textvariable=self.scale_var, values=["2", "4"], state="readonly", width=8).pack(side=LEFT, padx=4)
        ttk.Label(setting_frame, text="输出格式").pack(side=LEFT, padx=12)
        ttk.Combobox(setting_frame, textvariable=self.format_var, values=["png", "jpg"], state="readonly", width=8).pack(side=LEFT, padx=4)

        progress_frame = ttk.LabelFrame(self.root, text="处理进度", padding=10)
        progress_frame.pack(fill="x", padx=16, pady=8)
        Label(progress_frame, textvariable=self.current_var).pack(anchor=W)
        self.progress = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress.pack(fill="x", pady=6)
        Label(progress_frame, textvariable=self.progress_var).pack(anchor=W)

        log_frame = ttk.LabelFrame(self.root, text="任务日志", padding=10)
        log_frame.pack(fill=BOTH, expand=True, padx=16, pady=8)
        self.logbox = Listbox(log_frame, height=8)
        self.logbox.pack(fill=BOTH, expand=True)

        action = Frame(self.root, padx=16, pady=10)
        action.pack(fill="x")
        Button(action, text="开始处理", command=self.start).pack(side=LEFT, padx=4)
        Button(action, text="暂停/继续", command=self.toggle_pause).pack(side=LEFT, padx=4)
        Button(action, text="停止", command=self.stop).pack(side=LEFT, padx=4)
        Button(action, text="打开输出文件夹", command=self.open_output).pack(side=RIGHT, padx=4)
        Button(action, text="查看日志", command=self.open_logs).pack(side=RIGHT, padx=4)

    def _build_menu(self) -> None:
        menubar = Menu(self.root)
        help_menu = Menu(menubar, tearoff=0)
        help_menu.add_command(label="快速引导", command=lambda: self.show_help_topic("quick_start"))
        help_menu.add_separator()
        help_menu.add_command(label="使用说明", command=lambda: self.show_help_topic("user_guide"))
        help_menu.add_command(label="常见问题", command=lambda: self.show_help_topic("faq"))
        help_menu.add_command(label="日志位置说明", command=lambda: self.show_help_topic("logs"))
        help_menu.add_separator()
        help_menu.add_command(label="打开日志文件夹", command=self.open_logs)
        menubar.add_cascade(label="帮助", menu=help_menu)
        self.root.config(menu=menubar)

    def show_help_topic(self, key: str) -> None:
        title, content = read_help_topic(key)
        window = Toplevel(self.root)
        window.title(f"影界 HDDE V0.3 - {title}")
        window.geometry("720x560")
        frame = Frame(window, padx=12, pady=12)
        frame.pack(fill=BOTH, expand=True)
        text = Text(frame, wrap="word", font=("Microsoft YaHei UI", 10), padx=8, pady=8)
        scrollbar = Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=RIGHT, fill=Y)
        text.pack(side=LEFT, fill=BOTH, expand=True)
        text.insert(END, content)
        text.configure(state="disabled")

    def show_first_launch_guide(self) -> None:
        if os.environ.get("VISUALMASTERPRO_SKIP_GUIDE") == "1":
            return
        if has_seen_quick_guide():
            return
        title, content = read_help_topic("quick_start")
        try:
            messagebox.showinfo(f"影界 HDDE V0.3 - {title}", content)
        finally:
            mark_quick_guide_seen()

    def log(self, message: str) -> None:
        self.logbox.insert(END, message)
        self.logbox.see(END)

    def add_images(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择图片",
            filetypes=[("图片文件", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff")],
        )
        self._add_paths(paths)

    def add_folder(self) -> None:
        folder = filedialog.askdirectory(title="选择图片文件夹")
        if folder:
            self._add_paths([folder])

    def _add_paths(self, paths) -> None:
        existing = {item.path for item in self.state.images}
        for path in collect_image_paths(paths):
            if path in existing:
                continue
            image = read_image(path)
            width = height = 0
            if image is not None:
                height, width = image.shape[:2]
            self.state.images.append(
                ImageItem(
                    path=path,
                    width=width,
                    height=height,
                    size_text=format_size(path.stat().st_size),
                )
            )
        self.refresh_list()

    def refresh_list(self) -> None:
        self.listbox.delete(0, END)
        for item in self.state.images:
            self.listbox.insert(END, f"{item.path.name} | {item.width}x{item.height} | {item.size_text} | {item.status}")
        self.count_var.set(f"已选择 {len(self.state.images)} 张图片")
        waiting = sum(1 for item in self.state.images if item.status == "等待")
        self.progress_var.set(f"成功 {self.state.success_count} / 失败 {self.state.failed_count} / 等待 {waiting}")

    def clear_images(self) -> None:
        self.state.images.clear()
        self.state.success_count = 0
        self.state.failed_count = 0
        self.refresh_list()

    def choose_output(self) -> None:
        folder = filedialog.askdirectory(title="选择输出文件夹")
        if folder:
            self.state.output_dir = Path(folder)
            self.output_var.set(str(self.state.output_dir))

    def start(self) -> None:
        if self.state.running:
            return
        if not self.state.images:
            self.log("未选择图片，请先添加图片或选择文件夹。")
            return
        self.state.running = True
        self.state.paused = False
        self.state.stop_requested = False
        self.state.success_count = 0
        self.state.failed_count = 0
        self.progress["maximum"] = len(self.state.images)
        self.progress["value"] = 0
        thread = threading.Thread(target=self._run_batch, daemon=True)
        thread.start()

    def _run_batch(self) -> None:
        paths = [item.path for item in self.state.images]

        def callback(task, result, phase):
            def update_ui():
                self._handle_progress(task, result, phase)
            self.root.after(0, update_ui)

        process_batch(
            paths,
            self.state.output_dir,
            mode=self.mode_var.get(),
            scale=int(self.scale_var.get()),
            output_format=self.format_var.get(),
            progress_callback=callback,
            cancel_callback=lambda: self.state.stop_requested,
            pause_callback=lambda: self.state.paused,
        )
        self.root.after(0, self._finish_batch)

    def _handle_progress(self, task, result, phase):
            if phase == "start":
                self.current_var.set(f"正在处理：{task.source.name}")
                self.log(f"开始：{task.source.name}")
                return
            self.progress["value"] += 1
            for item in self.state.images:
                if item.path == task.source:
                    item.status = "成功" if result and result.ok else "失败"
                    break
            if result and result.ok:
                self.state.success_count += 1
                self.log(f"成功：{task.source.name}")
            else:
                self.state.failed_count += 1
                self.log(f"失败：{task.source.name} - {result.message if result else '未知错误'}")
            self.refresh_list()

    def _finish_batch(self):
        self.state.running = False
        self.current_var.set("处理完成")
        self.log("批量处理完成。")

    def stop(self) -> None:
        self.state.stop_requested = True
        self.log("已请求停止。当前版本会在当前批次结束后停止。")

    def toggle_pause(self) -> None:
        if not self.state.running:
            return
        self.state.paused = not self.state.paused
        self.log("已暂停。" if self.state.paused else "继续处理。")

    def open_output(self) -> None:
        path = Path(self.output_var.get())
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    def open_logs(self) -> None:
        path = logs_dir()
        os.startfile(path)


def run_tkinter_gui() -> int:
    from tkinter import BOTH, END, LEFT, RIGHT, W, Y, Button, Frame, Label, Listbox, Menu, Scrollbar, StringVar, Text, Tk, Toplevel, filedialog, messagebox, ttk

    globals().update(
        {
            "BOTH": BOTH,
            "END": END,
            "LEFT": LEFT,
            "RIGHT": RIGHT,
            "W": W,
            "Y": Y,
            "Button": Button,
            "Frame": Frame,
            "Label": Label,
            "Listbox": Listbox,
            "Menu": Menu,
            "Scrollbar": Scrollbar,
            "StringVar": StringVar,
            "Text": Text,
            "Toplevel": Toplevel,
            "filedialog": filedialog,
            "messagebox": messagebox,
            "ttk": ttk,
        }
    )
    root = Tk()
    VisualMasterProApp(root)
    root.mainloop()
    return 0


def run_gui() -> int:
    try:
        return run_tkinter_gui()
    except Exception:
        return run_powershell_gui()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="影界 HDDE V0.3 图形化界面")
    parser.add_argument("--self-test", action="store_true", help="仅测试 GUI 模块是否可导入。")
    args = parser.parse_args(argv)
    if args.self_test:
        return 0
    install_global_exception_hook()
    try:
        return run_gui()
    except Exception as exc:
        return handle_exception(exc, title="影界 HDDE 图形界面启动失败")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
