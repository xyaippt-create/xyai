from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from engine.image_compression.delivery_options import (
    CONTENT_RISK_PROFILE,
    JPG_BALANCED_SCHEME,
    JPG_HIGH_QUALITY_SCHEME,
    KEEP_ORIGINAL_SCHEME,
    PNG_LOSSLESS_SCHEME,
    SIZE_SEARCH_PROFILE,
    generate_delivery_candidates,
)
import engine.image_compression.delivery_options as delivery_options_module
from engine.image_compression.common import CompressionRuntimeError
from engine.image_compression.jpg_quality_gate import evaluate_jpg_quality
import engine.output.publish_safety as publish_safety_module


def _metadata_report() -> dict[str, object]:
    return {
        "written": True,
        "decoded_pixel_content_unchanged": True,
        "alpha_unchanged": True,
        "icc_unchanged": True,
        "dpi_unchanged": True,
        "orientation_preserved": True,
        "title_preserved": True,
        "author_preserved": True,
        "source_metadata_preserved": True,
        "iptc_controlled_conflicts": 0,
        "xmp_controlled_conflicts": 0,
    }


def _business_image() -> Image.Image:
    image = Image.new("RGB", (640, 360), (247, 249, 252))
    draw = ImageDraw.Draw(image)
    draw.rectangle((36, 34, 604, 326), outline=(45, 111, 232), width=3)
    draw.rectangle((72, 86, 568, 142), fill=(45, 111, 232))
    draw.text((92, 102), "HDDE 2026", fill="white")
    for index in range(7):
        y = 174 + index * 18
        draw.line((90, y, 520 - index * 15, y), fill=(60, 71, 89), width=2)
    return image


class JpgQualityGateTests(unittest.TestCase):
    def test_high_quality_passes_and_damaged_candidate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            source = root / "source.png"
            high = root / "high.jpg"
            damaged = root / "damaged.jpg"
            image = _business_image()
            image.save(source, format="PNG")
            image.save(high, format="JPEG", quality=95, subsampling=0, optimize=True)
            image.save(damaged, format="JPEG", quality=25, subsampling=2, optimize=True)

            passed = evaluate_jpg_quality(
                source,
                high,
                metadata_report=_metadata_report(),
                source_has_real_transparency=False,
            )
            failed = evaluate_jpg_quality(
                source,
                damaged,
                metadata_report=_metadata_report(),
                source_has_real_transparency=False,
            )

            self.assertEqual(passed["status"], "PASS")
            self.assertEqual(failed["status"], "FAIL")
            self.assertTrue(failed["failure_reasons"])
            self.assertIn("text_and_fine_lines", passed["checks"])
            self.assertIn("gradient_banding", passed["checks"])

    def test_real_transparency_is_not_accepted_as_jpg(self) -> None:
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            source = root / "transparent.png"
            candidate = root / "candidate.jpg"
            image = Image.new("RGBA", (64, 64), (45, 111, 232, 0))
            image.save(source, format="PNG")
            image.convert("RGB").save(candidate, format="JPEG", quality=95)
            result = evaluate_jpg_quality(
                source,
                candidate,
                metadata_report=_metadata_report(),
                source_has_real_transparency=True,
            )
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("SOURCE_HAS_REAL_TRANSPARENCY", result["failure_reasons"])


class SingleWinnerTests(unittest.TestCase):
    def test_manual_jpg_internal_candidates_publish_only_one_formal_winner(self) -> None:
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            source = root / "source.png"
            output = root / "formal"
            _business_image().save(source, format="PNG", compress_level=0, dpi=(300, 300))

            generated = generate_delivery_candidates(
                source,
                output,
                source_filename=source.name,
                moment=datetime(2026, 9, 5, 12, 0, 0),
                target_format="JPEG",
            )

            self.assertGreater(len(generated["candidates"]), 3)
            scheme_ids = {item["scheme_id"] for item in generated["candidates"]}
            self.assertTrue({
                JPG_HIGH_QUALITY_SCHEME,
                JPG_BALANCED_SCHEME,
            }.issubset(scheme_ids))
            self.assertNotIn(PNG_LOSSLESS_SCHEME, scheme_ids)
            self.assertEqual(generated["target_format"], "JPEG")
            self.assertEqual(generated["effective_target_format"], "JPEG")
            self.assertNotEqual(generated["winner_scheme_id"], KEEP_ORIGINAL_SCHEME)
            self.assertEqual(generated["public_output_count"], 1)
            self.assertEqual(len([path for path in output.iterdir() if path.is_file()]), 1)
            self.assertEqual(
                len([item for item in generated["candidates"] if item.get("output_path")]),
                1,
            )
            self.assertLessEqual(
                generated["jpg_search"]["encode_count"],
                generated["jpg_search"]["max_encodings"],
            )
            self.assertEqual(generated["selection_policy"], "SINGLE_WINNER_QUALITY_V2")

    def test_manual_jpg_adaptive_search_is_bounded_and_uses_both_subsampling_modes(self) -> None:
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            source = root / "source.png"
            output = root / "formal"
            _business_image().save(source, format="PNG", compress_level=0, dpi=(300, 300))

            generated = generate_delivery_candidates(
                source,
                output,
                source_filename=source.name,
                moment=datetime(2026, 9, 5, 12, 1, 0),
                target_format="JPEG",
            )

            jpgs = [item for item in generated["candidates"] if item["format"] == "JPG"]
            searched_modes = {
                item["search_details"]["subsampling"]
                for item in jpgs
            }
            self.assertEqual(searched_modes, {"4:4:4", "4:2:0"})
            self.assertTrue(all(item["direct_source_lineage"] for item in jpgs))
            self.assertLessEqual(len(jpgs), generated["jpg_search"]["max_encodings"])
            self.assertIsNotNone(generated["jpg_search"]["lowest_safe_quality"])

    def test_size_and_content_profiles_are_centralized_without_gate_thresholds(self) -> None:
        self.assertEqual(set(SIZE_SEARCH_PROFILE), {"SMALL", "MEDIUM", "LARGE", "VERY_LARGE"})
        self.assertEqual(set(CONTENT_RISK_PROFILE), {
            "TEXT_LINE_HIGH_RISK",
            "PHOTO_NORMAL",
            "LOW_FREQUENCY_FRIENDLY",
            "HIGH_FREQUENCY_COMPLEX",
            "REAL_TRANSPARENCY",
        })
        self.assertTrue(all("quality_threshold" not in profile for profile in SIZE_SEARCH_PROFILE.values()))
        self.assertTrue(all("quality_threshold" not in profile for profile in CONTENT_RISK_PROFILE.values()))

    def test_source_wins_when_candidates_have_no_positive_saving(self) -> None:
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            source = root / "source.jpg"
            output = root / "formal"
            noise = np.random.default_rng(7).integers(0, 256, (240, 320, 3), dtype=np.uint8)
            Image.fromarray(noise, mode="RGB").save(
                source, format="JPEG", quality=45, optimize=True, dpi=(300, 300)
            )

            generated = generate_delivery_candidates(
                source,
                output,
                source_filename=source.name,
                moment=datetime(2026, 9, 5, 12, 0, 0),
            )

            self.assertEqual(generated["winner_scheme_id"], KEEP_ORIGINAL_SCHEME)
            self.assertEqual(generated["public_output_count"], 0)
            self.assertEqual(list(output.iterdir()), [])

    def test_transparent_png_smart_mode_preserves_png_without_jpg_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            source = root / "transparent.png"
            output = root / "formal"
            image = Image.new("RGBA", (160, 100), (45, 111, 232, 0))
            ImageDraw.Draw(image).rectangle((20, 20, 140, 80), fill=(45, 111, 232, 180))
            image.save(source, format="PNG", compress_level=0, dpi=(300, 300))

            generated = generate_delivery_candidates(
                source,
                output,
                source_filename=source.name,
                moment=datetime(2026, 9, 5, 12, 0, 0),
            )
            by_id = {item["scheme_id"]: item for item in generated["candidates"]}
            self.assertEqual(set(by_id), {PNG_LOSSLESS_SCHEME})
            self.assertEqual(generated["target_format"], "SMART_COMPRESSION")
            self.assertEqual(generated["effective_target_format"], "PNG")
            self.assertEqual(generated["format_policy"], "SMART_SAFE_FORMAT_SELECTION")
            self.assertEqual(generated["alpha_handling"]["action"], "PRESERVE")
            self.assertTrue(all(item["format"] == "PNG" for item in generated["candidates"]))

    def test_preserve_format_keeps_opaque_png_on_png_route(self) -> None:
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            source = root / "opaque.png"
            output = root / "formal"
            _business_image().save(source, format="PNG", compress_level=0)

            generated = generate_delivery_candidates(
                source,
                output,
                source_filename=source.name,
                moment=datetime(2026, 9, 21, 12, 0, 0),
                target_format="PRESERVE_FORMAT",
            )

            self.assertEqual(generated["effective_target_format"], "PNG")
            self.assertEqual(generated["format_policy"], "PRESERVE_SOURCE_FORMAT")
            self.assertEqual({item["format"] for item in generated["candidates"]}, {"PNG"})
            self.assertFalse(generated["smart_compression_details"]["comparison_performed"])

    def test_smart_opaque_png_compares_png_and_jpg_then_publishes_one_winner(self) -> None:
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            source = root / "opaque.png"
            output = root / "formal"
            _business_image().save(source, format="PNG", compress_level=0)

            generated = generate_delivery_candidates(
                source,
                output,
                source_filename=source.name,
                moment=datetime(2026, 9, 21, 12, 0, 0),
                target_format="SMART_COMPRESSION",
            )

            self.assertEqual({item["format"] for item in generated["candidates"]}, {"PNG", "JPG"})
            self.assertTrue(generated["smart_compression_details"]["comparison_performed"])
            self.assertIn(generated["effective_target_format"], {"PNG", "JPEG"})
            self.assertEqual(generated["public_output_count"], 1)
            self.assertEqual(
                len([item for item in generated["candidates"] if item.get("output_path")]),
                1,
            )
            self.assertEqual(
                generated["format_conversion"],
                generated["effective_target_format"] == "JPEG",
            )

    def test_source_change_before_publish_leaves_no_formal_or_temp_residue(self) -> None:
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            source = root / "source.png"
            output = root / "formal"
            _business_image().save(source, format="PNG", compress_level=0, dpi=(300, 300))
            original_reader = delivery_options_module._read_source_identity
            read_count = 0

            def mutate_before_second_identity_read(path: Path):
                nonlocal read_count
                read_count += 1
                if read_count == 2:
                    Image.new("RGB", (640, 360), (220, 20, 40)).save(path, format="PNG")
                return original_reader(path)

            with patch(
                "engine.image_compression.delivery_options._read_source_identity",
                side_effect=mutate_before_second_identity_read,
            ):
                with self.assertRaises(CompressionRuntimeError) as raised:
                    generate_delivery_candidates(
                        source,
                        output,
                        source_filename=source.name,
                        moment=datetime(2026, 9, 5, 12, 0, 0),
                    )

            self.assertEqual(raised.exception.failure_code, "SOURCE_IDENTITY_MISMATCH")
            self.assertTrue(output.is_dir())
            self.assertEqual(list(output.iterdir()), [])

    def test_formal_atomic_publish_failure_leaves_no_formal_or_temp_residue(self) -> None:
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            source = root / "source.png"
            output = root / "formal"
            _business_image().save(source, format="PNG", compress_level=0, dpi=(300, 300))
            original_publish = publish_safety_module._publish_open_file_no_replace

            def fail_only_formal_publish(open_file, private_path: Path, candidate: Path) -> None:
                if candidate.parent.resolve() == output.resolve():
                    raise PermissionError("controlled formal publish failure")
                original_publish(open_file, private_path, candidate)

            with patch(
                "engine.output.publish_safety._publish_open_file_no_replace",
                side_effect=fail_only_formal_publish,
            ):
                with self.assertRaises(PermissionError):
                    generate_delivery_candidates(
                        source,
                        output,
                        source_filename=source.name,
                        moment=datetime(2026, 9, 5, 12, 0, 0),
                    )

            self.assertTrue(output.is_dir())
            self.assertEqual(list(output.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
