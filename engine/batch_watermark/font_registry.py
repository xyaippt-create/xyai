"""Controlled font identities for HDDE text watermark rendering."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont


FONT_ASSET_ROOT = Path(__file__).resolve().parent / "fonts"


class FontLoadError(ValueError):
    """The selected font identity cannot be loaded exactly as requested."""


@dataclass(frozen=True, slots=True)
class FontDefinition:
    font_id: str
    display_name: str
    asset_name: str | None
    face_or_weight: str
    version: str
    source: str
    license_name: str


@dataclass(frozen=True, slots=True)
class LoadedFont:
    font: ImageFont.FreeTypeFont
    definition: FontDefinition
    asset_name: str
    family: str
    style: str


FONT_DEFINITIONS = {
    "default": FontDefinition(
        font_id="default",
        display_name="当前默认字体",
        asset_name=None,
        face_or_weight="系统兼容默认字面",
        version="system",
        source="当前操作系统既有字体候选链",
        license_name="由操作系统提供",
    ),
    "source_han_sans": FontDefinition(
        font_id="source_han_sans",
        display_name="思源黑体 CN Regular（历史兼容）",
        asset_name="SourceHanSansCN-Regular.otf",
        face_or_weight="CN Regular",
        version="2.005R",
        source="https://github.com/adobe-fonts/source-han-sans/tree/2.005R",
        license_name="SIL Open Font License 1.1",
    ),
    "source_han_sans_cn_medium": FontDefinition(
        font_id="source_han_sans_cn_medium",
        display_name="思源黑体 CN Medium",
        asset_name="SourceHanSansCN-Medium.otf",
        face_or_weight="CN Medium / 500",
        version="2.005R",
        source="https://github.com/adobe-fonts/source-han-sans/tree/2.005R/SubsetOTF/CN",
        license_name="SIL Open Font License 1.1",
    ),
    "source_han_serif_cn_heavy": FontDefinition(
        font_id="source_han_serif_cn_heavy",
        display_name="思源宋体 CN Heavy",
        asset_name="SourceHanSerifCN-Heavy.otf",
        face_or_weight="CN Heavy",
        version="2.003R",
        source="https://github.com/adobe-fonts/source-han-serif/tree/2.003R",
        license_name="SIL Open Font License 1.1",
    ),
}
FONT_IDS = frozenset(FONT_DEFINITIONS)


def _legacy_default_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = []
    windows_root = str(os.environ.get("WINDIR") or "").strip()
    if windows_root:
        fonts = Path(windows_root) / "Fonts"
        candidates.extend(fonts / name for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"))
    candidates.extend(
        Path(path)
        for path in (
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        )
    )
    return tuple(candidates)


def _load_exact_path(path: Path, size: int, definition: FontDefinition) -> LoadedFont:
    try:
        font = ImageFont.truetype(str(path), size=size)
    except OSError as exc:
        raise FontLoadError(f"所选字体“{definition.display_name}”无法加载：{path.name}。") from exc
    family, style = font.getname()
    return LoadedFont(
        font=font,
        definition=definition,
        asset_name=path.name,
        family=str(family),
        style=str(style),
    )


def load_watermark_font(font_id: str, size: int) -> LoadedFont:
    """Load exactly the selected font identity; never substitute another identity."""

    definition = FONT_DEFINITIONS.get(font_id)
    if definition is None:
        raise FontLoadError(f"文字水印字体标识无效：{font_id}。")

    if definition.asset_name:
        path = FONT_ASSET_ROOT / definition.asset_name
        if not path.is_file():
            raise FontLoadError(f"所选字体“{definition.display_name}”缺少内置字体文件：{definition.asset_name}。")
        return _load_exact_path(path, size, definition)

    load_errors: list[OSError] = []
    for path in _legacy_default_candidates():
        if not path.is_file():
            continue
        try:
            font = ImageFont.truetype(str(path), size=size)
        except OSError as exc:
            load_errors.append(exc)
            continue
        family, style = font.getname()
        return LoadedFont(
            font=font,
            definition=definition,
            asset_name=path.name,
            family=str(family),
            style=str(style),
        )
    if load_errors:
        raise FontLoadError("当前默认字体存在但无法加载，已停止生成文字水印。") from load_errors[-1]
    raise FontLoadError("当前默认字体不可用，已停止生成文字水印。")
