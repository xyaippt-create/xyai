from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .dependency_check import check_dependencies, missing_required_dependencies
from .error_dialog import show_info_dialog
from .system_info import app_root, resource_root


IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


class StartupError(RuntimeError):
    pass


@dataclass(frozen=True)
class StartupStatus:
    input_path: Path
    output_dir: Path
    output_images_dir: Path
    dependency_report: list
    resource_root: Path


def ensure_default_dirs(input_path: Path, output_dir: Path) -> None:
    if input_path.suffix:
        input_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        input_path.mkdir(parents=True, exist_ok=True)
    (output_dir / "images").mkdir(parents=True, exist_ok=True)


def image_count(input_path: Path) -> int:
    if input_path.is_file():
        return 1 if input_path.suffix.lower() in IMAGE_EXTS else 0
    if not input_path.exists():
        return 0
    return sum(1 for path in input_path.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTS)


def check_resources() -> list[str]:
    root = resource_root()
    required_dirs = [
        "engine",
        "pipelines",
        "modes",
        "rules",
        "ai_noise_rules",
        "material_rules",
        "visual_style_rules",
        "runtime",
    ]
    missing = [name for name in required_dirs if not (root / name).exists()]
    return missing


def run_startup_check(input_path: Path, output_dir: Path, show_no_image_dialog: bool = True) -> StartupStatus:
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    ensure_default_dirs(input_path, output_dir)

    dependency_report = check_dependencies()
    missing_required = missing_required_dependencies(dependency_report)
    if missing_required:
        missing_names = "\n".join(f"- {item.name}" for item in missing_required)
        raise StartupError(f"缺少必要组件：\n{missing_names}")

    missing_resources = check_resources()
    if missing_resources:
        missing_names = "\n".join(f"- {name}" for name in missing_resources)
        raise StartupError(
            "程序资源不完整，可能是 EXE 打包时缺少必要目录：\n"
            f"{missing_names}\n\n"
            f"资源根目录：{resource_root()}"
        )

    if image_count(input_path) == 0 and show_no_image_dialog:
        message = "\n".join(
            [
                "未检测到待处理图片。",
                "",
                "请将图片放入“输入图片”文件夹后重新运行。",
                "",
                f"输入图片目录：{input_path}",
                f"输出目录：{output_dir / 'images'}",
            ]
        )
        print(message)
        show_info_dialog("VisualMasterPro 提示", message)

    return StartupStatus(
        input_path=input_path,
        output_dir=output_dir,
        output_images_dir=output_dir / "images",
        dependency_report=dependency_report,
        resource_root=resource_root(),
    )


def default_project_dirs() -> tuple[Path, Path]:
    root = app_root()
    return root / "输入图片", root / "输出成品"
