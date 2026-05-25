import argparse
import sys
from pathlib import Path

from engine.pipeline import process_path
from modes import list_profiles


AUTO_MODE = "auto"


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
        description="VisualMasterPro V3 AI commercial visual quality engine.",
    )
    parser.add_argument("input_path", nargs="?", help="Backward-compatible input image file or folder.")
    parser.add_argument("output_dir", nargs="?", help="Backward-compatible output folder.")
    parser.add_argument("--input", dest="input_option", help="Input image file or image folder.")
    parser.add_argument("--output", dest="output_option", help="Output folder.")
    parser.add_argument(
        "--mode",
        default=AUTO_MODE,
        choices=[AUTO_MODE, *list_profiles()],
        help="Visual mode. Use auto to let the visual analyzer choose.",
    )
    parser.add_argument(
        "--report",
        default=None,
        choices=["both", "json", "md", "markdown", "none"],
        help="Developer/debug report format. Default is off unless --debug or --developer is enabled.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Write developer files: JSON report, Markdown report, and compare image.",
    )
    parser.add_argument(
        "--developer",
        action="store_true",
        help="Same as --debug. Keeps internal quality artifacts for development review.",
    )
    parser.add_argument(
        "--pause",
        action="store_true",
        help="Pause before exit, useful for packaged EXE double-click runs.",
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
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        input_path, output_dir = resolve_paths(args)
    except ValueError as exc:
        parser.error(str(exc))

    print("VisualMasterPro V3（雪原Ai增强引擎）")
    print("-----------------------------------")
    developer_mode = args.debug or args.developer
    report_format = args.report or ("both" if developer_mode else "none")
    print(f"请求模式：{args.mode}")
    print(f"交付模式：{'开发调试' if developer_mode else '单图商业交付'}")
    print(f"报告格式：{report_format}")
    print(f"输入位置：{input_path}")
    print(f"输出位置：{output_dir}")

    results = process_path(
        input_path=input_path,
        output_dir=output_dir,
        mode=args.mode,
        report=report_format,
        developer_mode=developer_mode,
    )

    if not results:
        print("没有找到可处理图片。")
        if args.pause:
            input("按回车键退出...")
        return 1

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
    raise SystemExit(run(sys.argv[1:]))
