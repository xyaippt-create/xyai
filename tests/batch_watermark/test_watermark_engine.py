from __future__ import annotations

import io
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from engine.batch_watermark import WatermarkEngine, WatermarkSpec, WatermarkSpecError
from engine.batch_watermark import font_registry


def image_bytes(mode="RGBA", size=(480, 320), color=(40, 80, 120, 180), image_format="PNG", **save_options):
    stream = io.BytesIO()
    Image.new(mode, size, color).save(stream, format=image_format, **save_options)
    return stream.getvalue()


def logo_bytes(size=(100, 50)):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(image).rounded_rectangle((5, 5, size[0] - 5, size[1] - 5), radius=8, fill=(245, 250, 255, 210))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


class WatermarkEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = WatermarkEngine()

    def test_chinese_text_position_opacity_and_png_outside_pixels_are_exact(self):
        source = image_bytes()
        spec = WatermarkSpec.from_mapping(
            {"kind": "text", "text": "影界版权", "opacity": 37, "text_size": 42, "position": "bottom-right", "margin_x": 21, "margin_y": 17}
        )
        result = self.engine.render(source, spec)
        original = np.asarray(Image.open(io.BytesIO(source)).convert("RGBA"))
        rendered = np.asarray(Image.open(io.BytesIO(result.data)).convert("RGBA"))
        left, top, right, bottom = result.overlay_bbox
        outside = np.ones(original.shape[:2], dtype=bool)
        outside[top:bottom, left:right] = False
        self.assertTrue(np.array_equal(original[outside], rendered[outside]))
        self.assertGreater(left, original.shape[1] // 2)
        self.assertGreater(top, original.shape[0] // 2)
        self.assertTrue(result.alpha_outside_overlay_unchanged)

    def test_tiled_rotated_text_changes_multiple_image_regions(self):
        source = image_bytes(size=(900, 600), color=(20, 40, 60, 255))
        result = self.engine.render(
            source,
            WatermarkSpec.from_mapping({"kind": "text", "text": "仅供方案预览", "font_id": "source_han_serif_cn_heavy", "tile": True, "rotation": -25, "opacity": 30, "text_size": 44}),
        )
        before = np.asarray(Image.open(io.BytesIO(source)).convert("RGBA"))
        after = np.asarray(Image.open(io.BytesIO(result.data)).convert("RGBA"))
        changed = np.any(before != after, axis=2)
        quadrants = [changed[:300, :450], changed[:300, 450:], changed[300:, :450], changed[300:, 450:]]
        self.assertTrue(all(np.count_nonzero(region) > 50 for region in quadrants))
        self.assertEqual(result.font_id, "source_han_serif_cn_heavy")
        self.assertEqual(result.font_family, "Source Han Serif CN")
        self.assertEqual(result.font_style, "Heavy")

    def test_bundled_fonts_render_chinese_english_digits_and_mixed_text(self):
        cases = {
            "source_han_sans": ("Source Han Sans CN", "Regular", "SourceHanSansCN-Regular.otf"),
            "source_han_sans_cn_medium": ("Source Han Sans CN", "Medium", "SourceHanSansCN-Medium.otf"),
            "source_han_serif_cn_heavy": ("Source Han Serif CN", "Heavy", "SourceHanSerifCN-Heavy.otf"),
        }
        for font_id, expected in cases.items():
            for text in ("仅供预览", "CONFIDENTIAL", "2026", "内部资料 HDDE 2026", "未经授权禁止使用"):
                with self.subTest(font_id=font_id, text=text):
                    result = self.engine.render(
                        image_bytes(size=(1600, 900), color=(20, 40, 60, 255)),
                        WatermarkSpec.from_mapping({"kind": "text", "text": text, "font_id": font_id, "text_size": 48, "position": "center"}),
                    )
                    self.assertEqual((result.font_family, result.font_style, result.font_asset), expected)
                    self.assertEqual(result.font_id, font_id)
                    left, top, right, bottom = result.overlay_bbox
                    self.assertGreater(right - left, 0)
                    self.assertGreater(bottom - top, 0)
                    self.assertGreaterEqual(left, 0)
                    self.assertGreaterEqual(top, 0)
                    self.assertLessEqual(right, result.width)
                    self.assertLessEqual(bottom, result.height)

    def test_medium_asset_has_exact_internal_identity_and_weight(self):
        path = font_registry.FONT_ASSET_ROOT / "SourceHanSansCN-Medium.otf"
        data = path.read_bytes()
        table_count = struct.unpack_from(">H", data, 4)[0]
        tables = {
            data[12 + index * 16 : 16 + index * 16].decode("ascii"): struct.unpack_from(">LLL", data, 16 + index * 16)
            for index in range(table_count)
        }
        os2_offset = tables["OS/2"][1]
        loaded = font_registry.load_watermark_font("source_han_sans_cn_medium", 42)
        self.assertEqual((loaded.family, loaded.style), ("Source Han Sans CN", "Medium"))
        self.assertEqual(struct.unpack_from(">H", data, os2_offset + 4)[0], 500)

    def test_font_contract_defaults_to_medium_and_preserves_legacy_regular_identity(self):
        self.assertEqual(WatermarkSpec.from_mapping({"kind": "text", "text": "新任务"}).font_id, "source_han_sans_cn_medium")
        for legacy_font_id in ("default", "system_default", "Microsoft YaHei", "微软雅黑"):
            with self.subTest(legacy_font_id=legacy_font_id):
                self.assertEqual(
                    WatermarkSpec.from_mapping({"kind": "text", "text": "兼容", "font_id": legacy_font_id}).font_id,
                    "source_han_sans_cn_medium",
                )
        self.assertEqual(
            WatermarkSpec.from_mapping({"kind": "text", "text": "历史记录", "font_id": "source_han_sans"}).font_id,
            "source_han_sans",
        )
        with self.assertRaisesRegex(WatermarkSpecError, "字体不是有效的内置字体"):
            WatermarkSpec.from_mapping({"kind": "text", "text": "拒绝", "font_id": "unknown"})

    def test_selected_bundled_font_missing_fails_without_fallback(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(font_registry, "FONT_ASSET_ROOT", Path(temporary)):
            with self.assertRaisesRegex(ValueError, "思源黑体 CN Medium.*缺少内置字体文件"):
                self.engine.render(
                    image_bytes(),
                    WatermarkSpec.from_mapping({"kind": "text", "text": "不得回退", "font_id": "source_han_sans_cn_medium"}),
                )

    def test_normal_margins_move_edge_placement_and_tile_ignores_them(self):
        source = image_bytes(size=(1200, 800), color=(20, 40, 60, 255))
        common = {"kind": "text", "text": "边距语义", "position": "top-left", "text_size": 42}
        near = self.engine.render(source, WatermarkSpec.from_mapping({**common, "margin_x": 32, "margin_y": 32}))
        far = self.engine.render(source, WatermarkSpec.from_mapping({**common, "margin_x": 94, "margin_y": 94}))
        self.assertEqual(far.overlay_bbox[0] - near.overlay_bbox[0], 62)
        self.assertEqual(far.overlay_bbox[1] - near.overlay_bbox[1], 62)

        tiled_32 = self.engine.render(source, WatermarkSpec.from_mapping({**common, "tile": True, "margin_x": 32, "margin_y": 32}))
        tiled_94 = self.engine.render(source, WatermarkSpec.from_mapping({**common, "tile": True, "margin_x": 94, "margin_y": 94}))
        self.assertEqual(tiled_32.data, tiled_94.data)

    def test_transparent_logo_preserves_alpha_and_relative_scale_across_resolutions(self):
        logo = logo_bytes()
        spec = WatermarkSpec.from_mapping({"kind": "image", "image_width_percent": 20, "opacity": 55, "position": "center"})
        small = self.engine.render(image_bytes(size=(400, 250)), spec, watermark_bytes=logo)
        large = self.engine.render(image_bytes(size=(800, 500)), spec, watermark_bytes=logo)
        self.assertAlmostEqual(small.relative_width_percent, 20.0, places=2)
        self.assertAlmostEqual(large.relative_width_percent, 20.0, places=2)
        self.assertLessEqual(abs((large.overlay_bbox[2] - large.overlay_bbox[0]) - 2 * (small.overlay_bbox[2] - small.overlay_bbox[0])), 1)
        small_image = Image.open(io.BytesIO(small.data)).convert("RGBA")
        self.assertLess(small_image.getchannel("A").getextrema()[0], 255)
        self.assertIsNone(small.font_id)
        self.assertIsNone(small.font_asset)

    def test_jpeg_has_only_controlled_reencoding_error_outside_overlay(self):
        source_image = Image.new("RGB", (640, 420), (80, 120, 160))
        stream = io.BytesIO()
        source_image.save(stream, format="JPEG", quality=92, subsampling=0)
        result = self.engine.render(
            stream.getvalue(),
            WatermarkSpec.from_mapping({"kind": "text", "text": "HDDE", "position": "top-left", "margin_x": 24, "margin_y": 24}),
        )
        original = np.asarray(Image.open(io.BytesIO(stream.getvalue())).convert("RGB"), dtype=np.int16)
        rendered = np.asarray(Image.open(io.BytesIO(result.data)).convert("RGB"), dtype=np.int16)
        left, top, right, bottom = result.overlay_bbox
        outside = np.ones(original.shape[:2], dtype=bool)
        outside[max(0, top - 16) : min(original.shape[0], bottom + 16), max(0, left - 16) : min(original.shape[1], right + 16)] = False
        mean_error = np.abs(original - rendered)[outside].mean()
        self.assertLess(mean_error, 3.0)
        self.assertEqual(result.output_format, "JPEG")

    def test_icc_and_exif_are_preserved_with_orientation_normalized(self):
        exif = Image.Exif()
        exif[274] = 1
        exif[315] = "HDDE"
        source = image_bytes(icc_profile=b"hdde-test-icc", exif=exif)
        result = self.engine.render(source, WatermarkSpec.from_mapping({"kind": "text", "text": "版权"}))
        with Image.open(io.BytesIO(result.data)) as opened:
            self.assertEqual(opened.info.get("icc_profile"), b"hdde-test-icc")
            self.assertEqual(opened.getexif().get(315), "HDDE")
            self.assertEqual(opened.getexif().get(274), 1)
        self.assertEqual(result.icc_status, "preserved")
        self.assertEqual(result.exif_status, "preserved_orientation_normalized")

    def test_invalid_or_opaque_logo_is_rejected(self):
        spec = WatermarkSpec.from_mapping({"kind": "image"})
        with self.assertRaisesRegex(ValueError, "有效的透明 PNG"):
            self.engine.render(image_bytes(), spec, watermark_bytes=b"not-png")
        opaque = image_bytes(mode="RGB", size=(30, 20), color=(255, 255, 255), image_format="PNG")
        with self.assertRaisesRegex(ValueError, "Alpha"):
            self.engine.render(image_bytes(), spec, watermark_bytes=opaque)


if __name__ == "__main__":
    unittest.main()
