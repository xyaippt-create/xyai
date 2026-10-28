from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


class ProgramResourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProgramResource:
    source_relative: str
    destination_relative: str


_STATIC_RESOURCES = (
    "product_version.json",
    "dist/index.html",
    "dist/favicon.svg",
    "dist/assets/contact/wechat-qr.png",
    "dist/branding/hdde/app-icon.png",
    "dist/branding/hdde/ASSET_MANIFEST.txt",
    "dist/branding/hdde/desktop-icon-master.png",
    "dist/branding/hdde/hdde.ico",
    "dist/branding/hdde/logo-dark.png",
    "dist/branding/hdde/logo-light.png",
    "dist/branding/hdde/splash-dark.png",
    "dist/branding/hdde/splash-light.png",
    "engine/batch_watermark/fonts/LICENSE-SourceHanSans.txt",
    "engine/batch_watermark/fonts/LICENSE-SourceHanSerif.txt",
    "engine/batch_watermark/fonts/SourceHanSansCN-Medium.otf",
    "engine/batch_watermark/fonts/SourceHanSansCN-Regular.otf",
    "engine/batch_watermark/fonts/SourceHanSerifCN-Heavy.otf",
    "engine/batch_watermark/fonts/THIRD_PARTY_NOTICES.md",
    "models/local_retouch/inpainting_lama_2025jan.onnx",
    "models/local_retouch/README.md",
    "modes/__init__.py",
    "modes/ai_commercial_kv.yaml",
    "modes/architecture.yaml",
    "modes/cinematic.yaml",
    "modes/cosmetics.yaml",
    "modes/food.yaml",
    "modes/luxury_product.yaml",
    "modes/mode_registry.py",
    "modes/portrait_commercial.yaml",
    "modes/ppt_business.yaml",
    "modes/README.md",
    "rules/global_visual_rules.yaml",
    "rules/pipeline_rules.yaml",
    "rules/README.md",
    "ai_noise_rules/ai_dirty_patterns.yaml",
    "ai_noise_rules/README.md",
    "material_rules/materials.yaml",
    "material_rules/README.md",
    "visual_style_rules/commercial_styles.yaml",
    "visual_style_rules/README.md",
    "external_tools/realesrgan-ncnn-vulkan/realesrgan-ncnn-vulkan.exe",
    "external_tools/realesrgan-ncnn-vulkan/vcomp140.dll",
    "external_tools/realesrgan-ncnn-vulkan/vcomp140d.dll",
    "external_tools/realesrgan-ncnn-vulkan/models/realesr-animevideov3-x2.bin",
    "external_tools/realesrgan-ncnn-vulkan/models/realesr-animevideov3-x2.param",
    "external_tools/realesrgan-ncnn-vulkan/models/realesr-animevideov3-x3.bin",
    "external_tools/realesrgan-ncnn-vulkan/models/realesr-animevideov3-x3.param",
    "external_tools/realesrgan-ncnn-vulkan/models/realesr-animevideov3-x4.bin",
    "external_tools/realesrgan-ncnn-vulkan/models/realesr-animevideov3-x4.param",
    "external_tools/realesrgan-ncnn-vulkan/models/realesrgan-x4plus-anime.bin",
    "external_tools/realesrgan-ncnn-vulkan/models/realesrgan-x4plus-anime.param",
    "external_tools/realesrgan-ncnn-vulkan/models/realesrgan-x4plus.bin",
    "external_tools/realesrgan-ncnn-vulkan/models/realesrgan-x4plus.param",
)

_MANAGED_ROOTS = (
    "dist",
    "engine/batch_watermark/fonts",
    "models/local_retouch",
    "modes",
    "rules",
    "ai_noise_rules",
    "material_rules",
    "visual_style_rules",
    "external_tools/realesrgan-ncnn-vulkan",
)

_KNOWN_SOURCE_EXCLUSIONS = {
    "modes/__pycache__/__init__.cpython-312.pyc",
    "modes/__pycache__/mode_registry.cpython-312.pyc",
    "external_tools/realesrgan-ncnn-vulkan/input.jpg",
    "external_tools/realesrgan-ncnn-vulkan/input2.jpg",
    "external_tools/realesrgan-ncnn-vulkan/onepiece_demo.mp4",
    "external_tools/realesrgan-ncnn-vulkan/README_windows.md",
    "external_tools/realesrgan-ncnn-vulkan/realesrgan-ncnn-vulkan-20220424-windows.zip",
}

_GENERATED_DIST_PATTERNS = (
    re.compile(r"dist/assets/index-[A-Za-z0-9_-]+\.(?:js|css)"),
    re.compile(r"dist/assets/SourceHan(?:Sans|Serif)CN-[A-Za-z]+-[A-Za-z0-9_-]+\.otf"),
)


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = getattr(path.stat(), "st_file_attributes", 0)
    except OSError as exc:
        raise ProgramResourceError(f"RESOURCE_STAT_FAILED: {path}: {exc}") from exc
    return bool(attributes & getattr(os.stat_result, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _validate_source_path(project_root: Path, path: Path) -> None:
    root = project_root.resolve()
    resolved = path.resolve()
    if root != resolved and root not in resolved.parents:
        raise ProgramResourceError(f"RESOURCE_PATH_ESCAPE: {path}")
    relative = path.relative_to(project_root)
    current = project_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or _is_reparse_point(current):
            raise ProgramResourceError(f"RESOURCE_REPARSE_POINT_FORBIDDEN: {current}")


def _matches_generated_dist(relative: str) -> bool:
    return any(pattern.fullmatch(relative) for pattern in _GENERATED_DIST_PATTERNS)


def discover_program_resources(project_root: str | Path) -> list[ProgramResource]:
    root = Path(project_root).resolve()
    allowed = set(_STATIC_RESOURCES)
    dist_root = root / "dist"
    if not dist_root.is_dir():
        raise ProgramResourceError(f"PRODUCTION_FRONTEND_MISSING: {dist_root}")
    for path in dist_root.rglob("*"):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            if _matches_generated_dist(relative):
                allowed.add(relative)

    missing = [relative for relative in sorted(allowed) if not (root / relative).is_file()]
    if missing:
        raise ProgramResourceError("PROGRAM_RESOURCE_MISSING: " + ", ".join(missing))

    observed: set[str] = set()
    for managed in _MANAGED_ROOTS:
        managed_root = root / managed
        if not managed_root.is_dir():
            raise ProgramResourceError(f"PROGRAM_RESOURCE_ROOT_MISSING: {managed}")
        observed.update(
            path.relative_to(root).as_posix()
            for path in managed_root.rglob("*")
            if path.is_file()
        )

    unexpected = sorted(observed - allowed - _KNOWN_SOURCE_EXCLUSIONS)
    if unexpected:
        raise ProgramResourceError("UNALLOWLISTED_PROGRAM_RESOURCE: " + ", ".join(unexpected))

    resources: list[ProgramResource] = []
    for relative in sorted(allowed):
        source = root / relative
        _validate_source_path(root, source)
        resources.append(ProgramResource(relative, relative))
    return resources


def build_pyinstaller_datas(project_root: str | Path) -> list[tuple[str, str]]:
    root = Path(project_root).resolve()
    return [
        (str(root / item.source_relative), str(Path(item.destination_relative).parent).replace("\\", "/"))
        for item in discover_program_resources(root)
    ]


def expected_app_tree_resources(project_root: str | Path) -> dict[str, str]:
    return {
        f"_internal/{item.destination_relative}": item.source_relative
        for item in discover_program_resources(project_root)
    }

