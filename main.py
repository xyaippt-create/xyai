import argparse
import sys
from pathlib import Path

from runtime import APP_VERSION
from runtime.crash_handler import handle_exception, install_global_exception_hook
from runtime.error_dialog import show_info_dialog
from runtime.startup_check import run_startup_check
from runtime.system_info import is_pyinstaller


AUTO_MODE = "fidelity"
SUPPORTED_MODES = [
    "fidelity",
    "text_safe",
    "ai_image_clean",
    "sharp_4k",
    "auto",
    "ai_commercial_kv",
    "architecture",
    "cinematic",
    "cosmetics",
    "food",
    "luxury_product",
    "portrait_commercial",
    "ppt_business",
]


def get_desktop_work_dirs():
    desktop = Path.home() / "Desktop"
    work_dir = desktop / "雪原Ai增强引擎"

    input_dir = work_dir / "输入图片"
    output_dir = work_dir / "输出成品"

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    return input_dir, output_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="VisualMasterPro",
        description="VisualMasterPro V0.3 商业级 AI 视觉增强系统。",
    )
    parser.add_argument("input_path", nargs="?", help="兼容旧命令的输入图片或文件夹。")
    parser.add_argument("output_dir", nargs="?", help="兼容旧命令的输出文件夹。")
    parser.add_argument("--input", dest="input_option", help="输入图片或图片文件夹。")
    parser.add_argument("--output", dest="output_option", help="输出文件夹。")
    parser.add_argument("--gui", action="store_true", help="启动 VisualMasterPro V0.3 图形化界面。")
    parser.add_argument(
        "--mode",
        default=AUTO_MODE,
        choices=SUPPORTED_MODES,
        help="增强模式。V0.3 默认使用 fidelity 原图忠实增强。",
    )
    parser.add_argument(
        "--report",
        default=None,
        choices=["both", "json", "md", "markdown", "none"],
        help="开发调试报告格式。默认关闭，只有 --debug 或 --developer 时启用。",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=2,
        choices=[2, 4],
        help="V0.3 批量增强放大倍率，支持 2 或 4，默认 2。",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        default="png",
        choices=["png", "jpg", "jpeg"],
        help="V0.3 批量增强输出格式，默认 png。",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="输出开发调试文件：JSON、Markdown 和对比图。",
    )
    parser.add_argument(
        "--developer",
        action="store_true",
        help="等同于 --debug，用于保留内部调试文件。",
    )
    parser.add_argument(
        "--pause",
        action="store_true",
        help="退出前暂停，适合调试 EXE 双击运行。",
    )
    return parser


def resolve_paths(args):
    input_value = args.input_option or args.input_path
    output_value = args.output_option or args.output_dir

    if input_value and output_value:
        return Path(input_value), Path(output_value)

    if not input_value and not output_value:
        return get_desktop_work_dirs()

    raise ValueError("input and output must be provided together.")


def run(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if is_pyinstaller() and not argv:
        from gui.app import run_gui

        return run_gui()

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.gui:
        from gui.app import run_gui

        return run_gui()

    try:
        input_path, output_dir = resolve_paths(args)
    except ValueError as exc:
        parser.error(str(exc))

    print(f"{APP_VERSION}（雪原Ai增强引擎）")
    print("-----------------------------------")
    developer_mode = args.debug or args.developer
    report_format = args.report or ("both" if developer_mode else "none")
    print(f"请求模式：{args.mode}")
    print(f"交付模式：{'开发调试' if developer_mode else '单图商业交付'}")
    print(f"报告格式：{report_format}")
    print(f"放大倍率：{args.scale}x")
    print(f"输出格式：{args.output_format}")
    print(f"输入位置：{input_path}")
    print(f"输出位置：{output_dir}")

    startup_status = run_startup_check(
        input_path=input_path,
        output_dir=output_dir,
        show_no_image_dialog=True,
    )
    if startup_status.input_path.is_dir() and not any(startup_status.input_path.iterdir()):
        print("未检测到待处理图片，已安全退出。")
        return 0

    if args.mode in {"fidelity", "text_safe", "ai_image_clean", "sharp_4k"}:
        from batch.batch_processor import process_batch

        results = process_batch(
            [input_path],
            output_dir,
            mode=args.mode,
            scale=args.scale,
            output_format=args.output_format,
            debug_output=developer_mode,
        )
        if not results:
            message = (
                "未检测到待处理图片。\n\n"
                "请将图片放入“输入图片”文件夹后重新运行。\n\n"
                f"输入图片目录：{input_path}\n"
                f"输出目录：{output_dir / 'images'}"
            )
            print(message)
            show_info_dialog("VisualMasterPro 提示", message)
            return 0
        for result in results:
            print(f"{'完成' if result.ok else '失败'}：{result.output or result.source}，{result.message}")
        return 0

    from engine.pipeline import process_path

    results = process_path(
        input_path=input_path,
        output_dir=output_dir,
        mode=args.mode,
        report=report_format,
        developer_mode=developer_mode,
    )

    if not results:
        message = (
            "未检测到待处理图片。\n\n"
            "请将图片放入“输入图片”文件夹后重新运行。\n\n"
            f"输入图片目录：{input_path}\n"
            f"输出目录：{output_dir / 'images'}"
        )
        print(message)
        show_info_dialog("VisualMasterPro 提示", message)
        return 0

    for result in results:
        if result.ok:
            print(f"完成：{result.output}")
            print(f"尺寸：{result.width}x{result.height}")
            print(f"使用模式：{result.mode}")
            if result.quality_report_json_path:
                print(f"JSON报告：{result.quality_report_json_path}")
            if result.quality_report_markdown_path:
                print(f"Markdown报告：{result.quality_report_markdown_path}")
        else:
            print(f"跳过：{result.source}，原因：{result.message}")

    print("全部处理完成。")
    if args.pause:
        input("按回车键退出...")
    return 0


if __name__ == "__main__":
    install_global_exception_hook()
    try:
        raise SystemExit(run(sys.argv[1:]))
    except Exception as exc:
        raise SystemExit(handle_exception(exc))
