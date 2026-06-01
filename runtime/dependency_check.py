from __future__ import annotations

import importlib.util
from dataclasses import dataclass


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    import_name: str
    required: bool
    available: bool
    note: str = ""


REQUIRED_DEPENDENCIES = (
    ("cv2", "cv2", True, "图像处理核心组件"),
    ("numpy", "numpy", True, "图像矩阵计算组件"),
    ("pathlib", "pathlib", True, "路径处理组件"),
    ("tkinter", "tkinter", False, "图形界面优先组件；缺失时使用 Windows 图形界面回退方案"),
)

OPTIONAL_DEPENDENCIES = (
    ("PIL / Pillow", "PIL", False, "后续图像格式扩展组件"),
    ("torch", "torch", False, "当前版本未启用，仅为后续 AI / GPU 能力预留"),
    ("onnxruntime", "onnxruntime", False, "当前版本未启用，仅为后续模型推理预留"),
)


def check_dependencies() -> list[DependencyStatus]:
    results: list[DependencyStatus] = []
    for name, import_name, required, note in (*REQUIRED_DEPENDENCIES, *OPTIONAL_DEPENDENCIES):
        available = importlib.util.find_spec(import_name) is not None
        results.append(
            DependencyStatus(
                name=name,
                import_name=import_name,
                required=required,
                available=available,
                note=note,
            )
        )
    return results


def missing_required_dependencies(results: list[DependencyStatus] | None = None) -> list[DependencyStatus]:
    results = results if results is not None else check_dependencies()
    return [item for item in results if item.required and not item.available]


def format_dependency_report(results: list[DependencyStatus]) -> str:
    lines = []
    for item in results:
        required = "必需" if item.required else "可选"
        state = "可用" if item.available else "缺失"
        lines.append(f"- {item.name}（{required}）：{state}。{item.note}")
    return "\n".join(lines)
