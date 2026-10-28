"""Validated, transport-neutral watermark specification."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .font_registry import FONT_IDS


POSITIONS = frozenset(
    {
        "top-left",
        "top-center",
        "top-right",
        "middle-left",
        "center",
        "middle-right",
        "bottom-left",
        "bottom-center",
        "bottom-right",
    }
)


class WatermarkSpecError(ValueError):
    """A user-supplied watermark specification is invalid."""


LEGACY_DEFAULT_FONT_IDS = frozenset({"default", "system_default", "microsoft yahei", "微软雅黑"})


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise WatermarkSpecError(f"{field} 不是有效数字。")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise WatermarkSpecError(f"{field} 不是有效数字。") from exc
    if number != number or number in {float("inf"), float("-inf")}:
        raise WatermarkSpecError(f"{field} 不是有限数字。")
    return number


@dataclass(frozen=True, slots=True)
class WatermarkSpec:
    """One validated contract shared by preview and formal batch processing."""

    kind: str = "text"
    text: str = "仅供方案预览"
    color: str = "#FFFFFF"
    opacity: int = 45
    text_size: int = 36
    font_id: str = "source_han_sans_cn_medium"
    rotation: int = 0
    position: str = "bottom-right"
    margin_x: int = 32
    margin_y: int = 32
    tile: bool = False
    image_width_percent: float = 18.0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "WatermarkSpec":
        raw = dict(value or {})
        allowed = {
            "kind",
            "text",
            "color",
            "opacity",
            "text_size",
            "font_id",
            "rotation",
            "position",
            "margin_x",
            "margin_y",
            "tile",
            "image_width_percent",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise WatermarkSpecError(f"水印参数包含未知字段：{', '.join(unknown)}。")

        kind = str(raw.get("kind", "text") or "").strip().lower()
        if kind not in {"text", "image"}:
            raise WatermarkSpecError("水印类型必须是 text 或 image。")
        text = str(raw.get("text", "仅供方案预览"))
        if kind == "text" and not text.strip():
            raise WatermarkSpecError("文字水印内容不能为空。")
        if len(text) > 200:
            raise WatermarkSpecError("文字水印不能超过 200 个字符。")

        font_id = str(raw.get("font_id", "source_han_sans_cn_medium") or "").strip().lower()
        if font_id in LEGACY_DEFAULT_FONT_IDS:
            font_id = "source_han_sans_cn_medium"
        if font_id not in FONT_IDS:
            raise WatermarkSpecError("文字水印字体不是有效的内置字体。")

        color = str(raw.get("color", "#FFFFFF") or "").strip().upper()
        if len(color) != 7 or not color.startswith("#"):
            raise WatermarkSpecError("文字颜色必须使用 #RRGGBB 格式。")
        try:
            int(color[1:], 16)
        except ValueError as exc:
            raise WatermarkSpecError("文字颜色必须使用 #RRGGBB 格式。") from exc

        opacity = round(_number(raw.get("opacity", 45), "透明度"))
        text_size = round(_number(raw.get("text_size", 36), "文字大小"))
        rotation = round(_number(raw.get("rotation", 0), "旋转角度"))
        margin_x = round(_number(raw.get("margin_x", 32), "水平边距"))
        margin_y = round(_number(raw.get("margin_y", 32), "垂直边距"))
        image_width_percent = _number(raw.get("image_width_percent", 18), "图片水印大小比例")
        if not 1 <= opacity <= 100:
            raise WatermarkSpecError("透明度必须在 1 到 100 之间。")
        if not 10 <= text_size <= 512:
            raise WatermarkSpecError("文字大小必须在 10 到 512 之间。")
        if not -180 <= rotation <= 180:
            raise WatermarkSpecError("旋转角度必须在 -180 到 180 之间。")
        if not 0 <= margin_x <= 10000 or not 0 <= margin_y <= 10000:
            raise WatermarkSpecError("水印边距必须在 0 到 10000 之间。")
        if not 1 <= image_width_percent <= 80:
            raise WatermarkSpecError("图片水印宽度比例必须在 1% 到 80% 之间。")

        position = str(raw.get("position", "bottom-right") or "").strip().lower()
        if position not in POSITIONS:
            raise WatermarkSpecError("水印位置不是有效的九宫格位置。")
        tile = raw.get("tile", False)
        if not isinstance(tile, bool):
            raise WatermarkSpecError("平铺开关必须是布尔值。")
        if kind == "image" and tile:
            raise WatermarkSpecError("图片水印第一版不支持平铺模式。")

        return cls(
            kind=kind,
            text=text,
            color=color,
            opacity=opacity,
            text_size=text_size,
            font_id=font_id,
            rotation=rotation,
            position=position,
            margin_x=margin_x,
            margin_y=margin_y,
            tile=tile,
            image_width_percent=round(image_width_percent, 3),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
