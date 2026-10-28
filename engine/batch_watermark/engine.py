"""Local-only overlay engine for HDDE batch watermarking."""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageOps

from .font_registry import LoadedFont, load_watermark_font
from .spec import WatermarkSpec

SUPPORTED_SOURCE_FORMATS = frozenset({"PNG", "JPEG"})
MAX_IMAGE_PIXELS = 120_000_000


@dataclass(frozen=True, slots=True)
class WatermarkRenderResult:
    data: bytes
    source_format: str
    output_format: str
    width: int
    height: int
    overlay_bbox: tuple[int, int, int, int]
    source_has_alpha: bool
    alpha_outside_overlay_unchanged: bool
    icc_status: str
    exif_status: str
    relative_width_percent: float | None
    font_id: str | None
    font_asset: str | None
    font_family: str | None
    font_style: str | None

    def facts(self) -> dict[str, Any]:
        return {
            "source_format": self.source_format,
            "output_format": self.output_format,
            "width": self.width,
            "height": self.height,
            "overlay_bbox": list(self.overlay_bbox),
            "source_has_alpha": self.source_has_alpha,
            "alpha_outside_overlay_unchanged": self.alpha_outside_overlay_unchanged,
            "icc_status": self.icc_status,
            "exif_status": self.exif_status,
            "relative_width_percent": self.relative_width_percent,
            "font_id": self.font_id,
            "font_asset": self.font_asset,
            "font_family": self.font_family,
            "font_style": self.font_style,
        }


def _parse_color(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))  # type: ignore[return-value]


def _multiply_alpha(image: Image.Image, opacity: int) -> Image.Image:
    rgba = image.convert("RGBA")
    rgba.putalpha(rgba.getchannel("A").point(lambda value: round(value * opacity / 100)))
    return rgba


def _valid_dpi(value: object) -> tuple[float, float] | None:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return None
    try:
        dpi = (float(value[0]), float(value[1]))
    except (TypeError, ValueError):
        return None
    return dpi if all(math.isfinite(item) and item > 0 for item in dpi) else None


def _position_xy(canvas: tuple[int, int], patch: tuple[int, int], spec: WatermarkSpec) -> tuple[int, int]:
    width, height = canvas
    patch_w, patch_h = patch
    horizontal, vertical = {
        "top-left": ("left", "top"),
        "top-center": ("center", "top"),
        "top-right": ("right", "top"),
        "middle-left": ("left", "middle"),
        "center": ("center", "middle"),
        "middle-right": ("right", "middle"),
        "bottom-left": ("left", "bottom"),
        "bottom-center": ("center", "bottom"),
        "bottom-right": ("right", "bottom"),
    }[spec.position]
    x = spec.margin_x if horizontal == "left" else (width - patch_w) // 2
    y = spec.margin_y if vertical == "top" else (height - patch_h) // 2
    if horizontal == "right":
        x = width - patch_w - spec.margin_x
    if vertical == "bottom":
        y = height - patch_h - spec.margin_y
    return max(0, min(x, max(0, width - patch_w))), max(0, min(y, max(0, height - patch_h)))


def _text_patch(spec: WatermarkSpec) -> tuple[Image.Image, LoadedFont]:
    loaded_font = load_watermark_font(spec.font_id, spec.text_size)
    font = loaded_font.font
    draw = ImageDraw.Draw(Image.new("L", (1, 1)))
    bbox = draw.textbbox((0, 0), spec.text, font=font)
    width, height = max(1, bbox[2] - bbox[0]), max(1, bbox[3] - bbox[1])
    padding = max(4, spec.text_size // 8)
    patch = Image.new("RGBA", (width + padding * 2, height + padding * 2), (0, 0, 0, 0))
    color = (*_parse_color(spec.color), round(spec.opacity * 255 / 100))
    ImageDraw.Draw(patch).text((padding - bbox[0], padding - bbox[1]), spec.text, font=font, fill=color)
    if spec.rotation:
        patch = patch.rotate(spec.rotation, resample=Image.Resampling.BICUBIC, expand=True)
    return patch, loaded_font


def _logo_patch(watermark_bytes: bytes, canvas_width: int, spec: WatermarkSpec) -> Image.Image:
    if not watermark_bytes:
        raise ValueError("请选择透明 PNG 图片水印。")
    try:
        with Image.open(io.BytesIO(watermark_bytes)) as opened:
            opened.load()
            if str(opened.format or "").upper() != "PNG":
                raise ValueError("图片水印必须是 PNG 文件。")
            if "A" not in opened.getbands() and "transparency" not in opened.info:
                raise ValueError("图片水印必须包含 Alpha 透明通道。")
            rgba = opened.convert("RGBA")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("无法读取图片水印，请选择有效的透明 PNG。") from exc
    if rgba.getchannel("A").getextrema() == (255, 255):
        raise ValueError("图片水印必须包含实际透明像素。")
    target_width = max(1, round(canvas_width * spec.image_width_percent / 100))
    target_height = max(1, round(rgba.height * target_width / rgba.width))
    return _multiply_alpha(rgba.resize((target_width, target_height), Image.Resampling.LANCZOS), spec.opacity)


def _build_overlay(
    size: tuple[int, int],
    spec: WatermarkSpec,
    watermark_bytes: bytes | None,
) -> tuple[Image.Image, float | None, LoadedFont | None]:
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    if spec.kind == "image":
        patch = _logo_patch(watermark_bytes or b"", size[0], spec)
        overlay.alpha_composite(patch, dest=_position_xy(size, patch.size, spec))
        return overlay, patch.width * 100.0 / size[0], None
    patch, loaded_font = _text_patch(spec)
    if not spec.tile:
        overlay.alpha_composite(patch, dest=_position_xy(size, patch.size, spec))
        return overlay, None, loaded_font
    gap_x = max(round(patch.width * 0.65), round(size[0] * 0.06), 24)
    gap_y = max(round(patch.height * 0.85), round(size[1] * 0.06), 24)
    step_x, step_y = patch.width + gap_x, patch.height + gap_y
    row, y = 0, -patch.height // 2
    while y < size[1]:
        x = -patch.width // 2 - (step_x // 2 if row % 2 else 0)
        while x < size[0]:
            overlay.alpha_composite(patch, dest=(x, y))
            x += step_x
        y += step_y
        row += 1
    return overlay, None, loaded_font


class WatermarkEngine:
    """Apply an overlay without resizing or enhancing the source image."""

    engine_id = "hdde.batch-watermark.v1"

    def render(self, source_bytes: bytes, spec: WatermarkSpec, *, watermark_bytes: bytes | None = None, output_format: str | None = None) -> WatermarkRenderResult:
        if not source_bytes:
            raise ValueError("源图片为空。")
        try:
            with Image.open(io.BytesIO(source_bytes)) as opened:
                opened.load()
                source_format = str(opened.format or "").upper()
                if source_format not in SUPPORTED_SOURCE_FORMATS:
                    raise ValueError("仅支持 PNG、JPG、JPEG 源图片。")
                if opened.width * opened.height > MAX_IMAGE_PIXELS:
                    raise ValueError("图片像素数量过大，已停止处理。")
                icc_profile = opened.info.get("icc_profile")
                source_dpi = _valid_dpi(opened.info.get("dpi"))
                source_exif = opened.getexif()
                source_has_alpha = "A" in opened.getbands() or "transparency" in opened.info
                base = ImageOps.exif_transpose(opened).convert("RGBA")
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("无法读取源图片，请确认文件未损坏。") from exc

        overlay, relative_width, loaded_font = _build_overlay(base.size, spec, watermark_bytes)
        alpha_bbox = overlay.getchannel("A").getbbox()
        if alpha_bbox is None:
            raise ValueError("水印没有可见内容。")
        result = base.copy()
        result.alpha_composite(overlay)
        selected_format = str(output_format or source_format).upper().replace("JPG", "JPEG")
        if selected_format not in SUPPORTED_SOURCE_FORMATS:
            raise ValueError("输出格式必须与 PNG 或 JPEG 合同一致。")

        exif_status, save_exif = "not_present", None
        if source_exif:
            try:
                source_exif[274] = 1
                save_exif = source_exif.tobytes()
                exif_status = "preserved_orientation_normalized"
            except Exception:
                exif_status = "not_preserved"
        save_options: dict[str, Any] = {}
        if icc_profile:
            save_options["icc_profile"] = icc_profile
        if save_exif:
            save_options["exif"] = save_exif
        if source_dpi is not None:
            save_options["dpi"] = source_dpi
        stream = io.BytesIO()
        if selected_format == "PNG":
            result.save(stream, format="PNG", compress_level=6, **save_options)
        else:
            result.convert("RGB").save(stream, format="JPEG", quality=95, subsampling=0, optimize=False, **save_options)
        return WatermarkRenderResult(
            data=stream.getvalue(), source_format=source_format, output_format=selected_format,
            width=result.width, height=result.height, overlay_bbox=alpha_bbox,
            source_has_alpha=source_has_alpha, alpha_outside_overlay_unchanged=True,
            icc_status="preserved" if icc_profile else "not_present", exif_status=exif_status,
            relative_width_percent=round(relative_width, 3) if relative_width is not None else None,
            font_id=loaded_font.definition.font_id if loaded_font else None,
            font_asset=loaded_font.asset_name if loaded_font else None,
            font_family=loaded_font.family if loaded_font else None,
            font_style=loaded_font.style if loaded_font else None,
        )
