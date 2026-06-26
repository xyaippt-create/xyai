from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class V046PathContext:
    workspace_root: Path
    input_dir: Path
    output_dir: Path
    diagnostics_dir: Path
    cache_dir: Path
    reports_dir: Path
    tests_results_dir: Path
    platform_name: str


def _default_external_root() -> Path:
    system = platform.system().lower()
    if system == "windows":
        return Path(os.environ.get("VMP_WORKSPACE_ROOT", r"D:\影界文件"))
    if system == "darwin":
        return Path(os.environ.get("VMP_WORKSPACE_ROOT", "~/Documents/影界文件")).expanduser()
    return Path(os.environ.get("VMP_WORKSPACE_ROOT", "~/Documents/影界文件")).expanduser()


def get_workspace_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for path in [current, *current.parents]:
        if (path / "package.json").exists() and (path / "main.py").exists():
            return path
    return current


def get_v046_path_context(start: Path | None = None) -> V046PathContext:
    workspace = get_workspace_root(start)
    external = _default_external_root()
    return V046PathContext(
        workspace_root=workspace,
        input_dir=Path(os.environ.get("VMP_INPUT_DIR", external / "输入图片")),
        output_dir=Path(os.environ.get("VMP_OUTPUT_DIR", external / "输出成品")),
        diagnostics_dir=Path(os.environ.get("VMP_DIAGNOSTICS_DIR", external / "诊断报告")),
        cache_dir=Path(os.environ.get("VMP_CACHE_DIR", workspace / "runtime" / "cache")),
        reports_dir=Path(os.environ.get("VMP_REPORTS_DIR", workspace / "docs" / "reports")),
        tests_results_dir=Path(os.environ.get("VMP_TEST_RESULTS_DIR", workspace / "tests" / "results")),
        platform_name=platform.system() or "Unknown",
    )


def file_meta(path: Path, logical_path: str, ctx: V046PathContext, final_output_url: str | None = None) -> dict:
    exists = path.exists()
    return {
        "logical_path": logical_path,
        "physical_path": str(path),
        "platform": ctx.platform_name,
        "workspace_root": str(ctx.workspace_root),
        "output_dir": str(ctx.output_dir),
        "file_exists": exists,
        "file_size": path.stat().st_size if exists else None,
        "final_output_url": final_output_url,
    }
