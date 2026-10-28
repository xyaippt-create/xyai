from __future__ import annotations

import base64
import hashlib
import struct
import tempfile
import unittest
import zlib
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import ExifTags, Image, ImageCms, PngImagePlugin

from engine.color_correction import run_formal_color_runtime
from engine.color_correction.color_management import (
    ColorManagementError,
    encode_color_managed_candidate,
    load_color_managed_source,
    srgb_profile_bytes,
    verify_color_managed_output,
)
from engine.output.metadata_writer import HDDE_SOFTWARE, read_hdde_metadata
from tests.color_correction.d1_replay_support import build_replay_image


_DISPLAY_P3_PROFILE = base64.b64decode(
    "AAACMAAAAAACEAAAbW50clJHQiBYWVogAAAAAAAAAAAAAAAAYWNzcAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEAAPbWAAEAAAAA0y0AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJZGVzYwAAAPAAAAB0clhZWgAAAWQAAAAUZ1hZWgAAAXgAAAAUYlhZWgAAAYwAAAAUclRSQwAAAaAAAAAoZ1RSQwAAAaAAAAAoYlRSQwAAAaAAAAAod3RwdAAAAcgAAAAUY3BydAAAAdwAAABUbWx1YwAAAAAAAAABAAAADGVuVVMAAABYAAAAHABzAFIARwBCACAARQBPAFQARgAgAHcAaQB0AGgAIABEAGkAcwBwAGwAYQB5ACAAUAAzACAAQwBvAGwAbwByACAARwBhAG0AdQB0AAAAAAAAAAAAAAAAAABYWVogAAAAAAAAg98AAD2/////u1hZWiAAAAAAAABKvwAAsTcAAAq5WFlaIAAAAAAAACg4AAARCwAAyLlwYXJhAAAAAAAEAAAAAmZmAADypwAADVkAABPQAAAKWwAAAAAAAAAAWFlaIAAAAAAAAPbWAAEAAAAA0y1tbHVjAAAAAAAAAAEAAAAMZW5VUwAAADgAAAAcAEcAbwBvAGcAbABlACAASQBuAGMALgAgADIAMAAxADYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)
_ADOBE_RGB_1998_PROFILE = base64.b64decode(
    "AAACMEFEQkUCEAAAbW50clJHQiBYWVogB88ABgADAAAAAAAAYWNzcEFQUEwAAAAAbm9uZQAAAAAAAAAAAAAAAAAAAAAAAPbWAAEAAAAA0y1BREJFAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAKY3BydAAAAPwAAAAyZGVzYwAAATAAAABrd3RwdAAAAZwAAAAUYmtwdAAAAbAAAAAUclRSQwAAAcQAAAAOZ1RSQwAAAdQAAAAOYlRSQwAAAeQAAAAOclhZWgAAAfQAAAAUZ1hZWgAAAggAAAAUYlhZWgAAAhwAAAAUdGV4dAAAAABDb3B5cmlnaHQgMTk5OSBBZG9iZSBTeXN0ZW1zIEluY29ycG9yYXRlZAAAAGRlc2MAAAAAAAAAEUFkb2JlIFJHQiAoMTk5OCkAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAFhZWiAAAAAAAADzUQABAAAAARbMWFlaIAAAAAAAAAAAAAAAAAAAAABjdXJ2AAAAAAAAAAECMwAAY3VydgAAAAAAAAABAjMAAGN1cnYAAAAAAAAAAQIzAABYWVogAAAAAAAAnBgAAE+lAAAE/FhZWiAAAAAAAAA0jQAAoCwAAA+VWFlaIAAAAAAAACYxAAAQLwAAvpw="
)
_DISPLAY_P3_CHROMATICITY = (0.3127, 0.3290, 0.6800, 0.3200, 0.2650, 0.6900, 0.1500, 0.0600)
_ADOBE_RGB_1998_CHROMATICITY = (0.3127, 0.3290, 0.6400, 0.3300, 0.2100, 0.7100, 0.1500, 0.0600)
_SRGB_CHROMATICITY = (0.3127, 0.3290, 0.6400, 0.3300, 0.3000, 0.6000, 0.1500, 0.0600)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _as_uint8(recipe: str) -> np.ndarray:
    image, _ = build_replay_image(recipe)
    return np.rint(image * 255.0).astype(np.uint8)


def _profile_label(payload: bytes) -> str:
    profile = ImageCms.getOpenProfile(BytesIO(payload))
    return f"{ImageCms.getProfileDescription(profile)} {ImageCms.getProfileName(profile)}".casefold()


def _wide_gamut_test_image() -> np.ndarray:
    yy, xx = np.indices((72, 96))
    return np.stack(
        (
            (xx * 7 + yy * 3 + 29) % 256,
            (xx * 2 + yy * 9 + 71) % 256,
            (xx * 11 + yy * 5 + 113) % 256,
        ),
        axis=2,
    ).astype(np.uint8)


def _exif_color_contract(
    color_space: int,
    interoperability_index: str,
) -> Image.Exif:
    exif = Image.Exif()
    exif[ExifTags.IFD.Exif] = {
        40961: color_space,
        ExifTags.IFD.Interop: {1: interoperability_index},
    }
    return exif


def _png_color_contract(
    gamma: float,
    chromaticity: tuple[float, ...],
) -> PngImagePlugin.PngInfo:
    info = PngImagePlugin.PngInfo()
    info.add(b"gAMA", struct.pack(">I", round(gamma * 100000)))
    info.add(b"cHRM", struct.pack(">8I", *(round(value * 100000) for value in chromaticity)))
    return info


def _inject_png_chunk(path: Path, chunk_type: bytes, payload: bytes) -> None:
    encoded = path.read_bytes()
    if encoded[:8] != b"\x89PNG\r\n\x1a\n" or encoded[12:16] != b"IHDR":
        raise AssertionError("test fixture is not a PNG")
    ihdr_end = 8 + 12 + struct.unpack_from(">I", encoded, 8)[0]
    checksum = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    chunk = struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", checksum)
    path.write_bytes(encoded[:ihdr_end] + chunk + encoded[ihdr_end:])


def _profile_with_mutated_colorimetry(profile_payload: bytes) -> bytes:
    payload = bytearray(profile_payload)
    tag_count = struct.unpack_from(">I", payload, 128)[0]
    offsets = {
        bytes(payload[132 + index * 12 : 136 + index * 12]).decode("ascii"): struct.unpack_from(
            ">I", payload, 136 + index * 12
        )[0]
        for index in range(tag_count)
    }
    red_xyz_offset = offsets["rXYZ"]
    original_x = struct.unpack_from(">i", payload, red_xyz_offset + 8)[0]
    struct.pack_into(">i", payload, red_xyz_offset + 8, int(original_x * 0.75))
    return bytes(payload)


def _profile_with_mutated_parametric_trc_gamma(
    profile_payload: bytes,
    gamma: float,
) -> bytes:
    payload = bytearray(profile_payload)
    tag_count = struct.unpack_from(">I", payload, 128)[0]
    offsets = {
        bytes(payload[132 + index * 12 : 136 + index * 12]).decode("ascii"): struct.unpack_from(
            ">I", payload, 136 + index * 12
        )[0]
        for index in range(tag_count)
    }
    trc_offset = offsets["rTRC"]
    if bytes(payload[trc_offset : trc_offset + 4]) != b"para":
        raise AssertionError("test profile does not use a parametric TRC")
    struct.pack_into(">i", payload, trc_offset + 12, round(gamma * 65536))
    return bytes(payload)


def _srgb_label_with_mutated_colorimetry() -> bytes:
    return _profile_with_mutated_colorimetry(srgb_profile_bytes())


class ColorManagementFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_no_icc_rgb_is_assumed_srgb_without_channel_swap(self) -> None:
        source = self.root / "asymmetric.png"
        rgb = np.zeros((64, 96, 3), dtype=np.uint8)
        rgb[:, :32] = (241, 17, 39)
        rgb[:, 32:64] = (29, 223, 61)
        rgb[:, 64:] = (13, 47, 229)
        Image.fromarray(rgb, mode="RGB").save(source)
        source_sha = _sha256(source)

        managed = load_color_managed_source(source)

        self.assertEqual(managed.profile_status, "ASSUMED_SRGB")
        self.assertEqual(managed.input_order, "RGB")
        self.assertEqual(managed.source_bit_depth, 8)
        self.assertTrue(np.array_equal(managed.pixels, rgb))
        output = self.root / "asymmetric_output.png"
        output.write_bytes(encode_color_managed_candidate(managed.pixels, managed))
        verify_color_managed_output(output, managed.pixels, managed)
        with Image.open(output) as opened:
            self.assertIn("srgb", _profile_label(opened.info["icc_profile"]))
            self.assertTrue(np.array_equal(np.asarray(opened), rgb))
        self.assertEqual(_sha256(source), source_sha)

    def test_valid_srgb_profile_uses_cmm_and_png_stays_lossless(self) -> None:
        source = self.root / "tagged.png"
        rgb = _as_uint8("neutral_scene")
        Image.fromarray(rgb, mode="RGB").save(source, icc_profile=srgb_profile_bytes())

        managed = load_color_managed_source(source)

        self.assertEqual(managed.profile_status, "CMM_CONVERTED_TO_SRGB")
        self.assertIsNotNone(managed.source_profile_name)
        self.assertIn("srgb", str(managed.source_profile_name).casefold())
        self.assertLessEqual(int(np.abs(managed.pixels.astype(np.int16) - rgb.astype(np.int16)).max()), 1)
        output = self.root / "tagged_output.png"
        output.write_bytes(encode_color_managed_candidate(managed.pixels, managed))
        verify_color_managed_output(output, managed.pixels, managed)

    def test_supported_display_p3_and_adobe_rgb_profiles_use_cmm_to_srgb(self) -> None:
        rgb = _wide_gamut_test_image()
        srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
        for family, payload in (
            ("display_p3", _DISPLAY_P3_PROFILE),
            ("adobe_rgb_1998", _ADOBE_RGB_1998_PROFILE),
        ):
            with self.subTest(profile=family):
                source = self.root / f"{family}.png"
                Image.fromarray(rgb, mode="RGB").save(source, icc_profile=payload)
                source_sha = _sha256(source)

                managed = load_color_managed_source(source)

                expected = ImageCms.profileToProfile(
                    Image.fromarray(rgb, mode="RGB"),
                    ImageCms.getOpenProfile(BytesIO(payload)),
                    srgb,
                    renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
                    outputMode="RGB",
                )
                self.assertEqual(managed.profile_status, "CMM_CONVERTED_TO_SRGB")
                self.assertEqual(managed.pixels.shape, rgb.shape)
                self.assertTrue(np.array_equal(managed.pixels, np.asarray(expected)))
                self.assertFalse(np.array_equal(managed.pixels, rgb))
                self.assertEqual(_sha256(source), source_sha)

                output = self.root / f"{family}_output.png"
                output.write_bytes(encode_color_managed_candidate(managed.pixels, managed))
                verify_color_managed_output(output, managed.pixels, managed)
                with Image.open(output) as opened:
                    self.assertIn("srgb", _profile_label(opened.info["icc_profile"]))

    def test_supported_wide_gamut_rgba_preserves_alpha_and_formal_runtime_contract(self) -> None:
        rgb = _wide_gamut_test_image()
        alpha = np.tile(np.arange(rgb.shape[1], dtype=np.uint8), (rgb.shape[0], 1))
        rgba = np.dstack((rgb, alpha))
        for family, payload in (
            ("display_p3", _DISPLAY_P3_PROFILE),
            ("adobe_rgb_1998", _ADOBE_RGB_1998_PROFILE),
        ):
            with self.subTest(profile=family):
                source = self.root / f"{family}_rgba.png"
                output = self.root / f"{family}_rgba_output.png"
                Image.fromarray(rgba, mode="RGBA").save(source, icc_profile=payload)
                source_sha = _sha256(source)

                managed = load_color_managed_source(source)
                self.assertEqual(managed.pixels.shape, rgba.shape)
                self.assertTrue(np.array_equal(managed.pixels[..., 3], alpha))

                result = run_formal_color_runtime(source, output)

                self.assertEqual(result.source_sha256, source_sha)
                self.assertIn(result.result_action, {"ACCEPT_ORIGINAL", "ACCEPT_CORRECTED", "REVIEW_REQUIRED"})
                self.assertEqual(_sha256(source), source_sha)
                if result.output_path:
                    with Image.open(result.output_path) as opened:
                        self.assertEqual(opened.size, (rgb.shape[1], rgb.shape[0]))
                        self.assertTrue(np.array_equal(np.asarray(opened)[..., 3], alpha))

    def test_jpeg_icc_and_exif_metadata_are_profile_aware(self) -> None:
        rgb = _wide_gamut_test_image()
        cases = (
            ("srgb", srgb_profile_bytes(), 1, "R98"),
            ("display_p3", _DISPLAY_P3_PROFILE, 65535, "R03"),
            ("adobe_rgb_1998", _ADOBE_RGB_1998_PROFILE, 65535, "R03"),
        )
        for family, profile, color_space, interoperability_index in cases:
            with self.subTest(profile=family):
                source = self.root / f"{family}_exif.jpg"
                Image.fromarray(rgb, mode="RGB").save(
                    source,
                    icc_profile=profile,
                    exif=_exif_color_contract(color_space, interoperability_index),
                )
                source_sha = _sha256(source)
                with Image.open(source) as opened:
                    exif = opened.getexif()
                    self.assertEqual(exif.get_ifd(ExifTags.IFD.Exif).get(40961), color_space)
                    self.assertEqual(
                        exif.get_ifd(ExifTags.IFD.Interop).get(1),
                        interoperability_index,
                    )

                managed = load_color_managed_source(source)

                self.assertEqual(managed.profile_status, "CMM_CONVERTED_TO_SRGB")
                self.assertEqual(managed.pixels.shape, rgb.shape)
                self.assertEqual(_sha256(source), source_sha)

    def test_wide_gamut_jpeg_conflicting_exif_is_blocked(self) -> None:
        rgb = _wide_gamut_test_image()
        for family, profile in (
            ("display_p3", _DISPLAY_P3_PROFILE),
            ("adobe_rgb_1998", _ADOBE_RGB_1998_PROFILE),
        ):
            with self.subTest(profile=family):
                source = self.root / f"{family}_srgb_exif_conflict.jpg"
                Image.fromarray(rgb, mode="RGB").save(
                    source,
                    icc_profile=profile,
                    exif=_exif_color_contract(1, "R98"),
                )
                with self.assertRaisesRegex(ColorManagementError, "FORMAL_COLOR_METADATA_CONFLICT"):
                    load_color_managed_source(source)

    def test_unknown_and_malformed_icc_with_uncalibrated_exif_remain_blocked(self) -> None:
        rgb = _wide_gamut_test_image()
        cases = (
            (
                "unknown",
                ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes(),
                "FORMAL_COLOR_NON_SRGB_PROFILE_SAFE_BLOCKED",
            ),
            ("malformed", b"not-an-icc-profile", "FORMAL_COLOR_ICC_INVALID"),
        )
        for name, profile, expected_error in cases:
            with self.subTest(profile=name):
                source = self.root / f"{name}_uncalibrated.jpg"
                Image.fromarray(rgb, mode="RGB").save(
                    source,
                    icc_profile=profile,
                    exif=_exif_color_contract(65535, "R03"),
                )
                with self.assertRaisesRegex(ColorManagementError, expected_error):
                    load_color_managed_source(source)

    def test_supported_wide_gamut_png_metadata_matches_icc_and_preserves_alpha(self) -> None:
        rgb = _wide_gamut_test_image()
        alpha = np.tile(np.arange(rgb.shape[1], dtype=np.uint8), (rgb.shape[0], 1))
        rgba = np.dstack((rgb, alpha))
        cases = (
            ("display_p3", _DISPLAY_P3_PROFILE, 0.45455, _DISPLAY_P3_CHROMATICITY),
            (
                "adobe_rgb_1998",
                _ADOBE_RGB_1998_PROFILE,
                1.0 / 2.19921875,
                _ADOBE_RGB_1998_CHROMATICITY,
            ),
        )
        for family, profile, gamma, chromaticity in cases:
            with self.subTest(profile=family):
                source = self.root / f"{family}_metadata.png"
                Image.fromarray(rgba, mode="RGBA").save(
                    source,
                    icc_profile=profile,
                    pnginfo=_png_color_contract(gamma, chromaticity),
                )
                source_sha = _sha256(source)
                with Image.open(source) as opened:
                    self.assertIn("icc_profile", opened.info)
                    self.assertAlmostEqual(opened.info["gamma"], gamma, places=4)
                    self.assertTrue(
                        np.allclose(opened.info["chromaticity"], chromaticity, atol=0.00001)
                    )

                managed = load_color_managed_source(source)

                self.assertEqual(managed.profile_status, "CMM_CONVERTED_TO_SRGB")
                self.assertEqual(managed.pixels.shape, rgba.shape)
                self.assertTrue(np.array_equal(managed.pixels[..., 3], alpha))
                self.assertEqual(_sha256(source), source_sha)

    def test_wide_gamut_png_conflicts_and_unknown_icc_remain_blocked(self) -> None:
        rgb = _wide_gamut_test_image()
        srgb_chunk_conflict = self.root / "display_p3_srgb_chunk.png"
        Image.fromarray(rgb, mode="RGB").save(
            srgb_chunk_conflict,
            icc_profile=_DISPLAY_P3_PROFILE,
            pnginfo=_png_color_contract(0.45455, _DISPLAY_P3_CHROMATICITY),
        )
        _inject_png_chunk(srgb_chunk_conflict, b"sRGB", b"\x00")
        with Image.open(srgb_chunk_conflict) as opened:
            self.assertEqual(opened.info.get("srgb"), 0)
            self.assertIn("icc_profile", opened.info)
        with self.assertRaisesRegex(ColorManagementError, "FORMAL_COLOR_METADATA_CONFLICT"):
            load_color_managed_source(srgb_chunk_conflict)

        cases = (
            (
                "adobe_rgb_srgb_chromaticity",
                _ADOBE_RGB_1998_PROFILE,
                _png_color_contract(
                    1.0 / 2.19921875,
                    (0.3127, 0.3290, 0.6400, 0.3300, 0.3000, 0.6000, 0.1500, 0.0600),
                ),
                "FORMAL_COLOR_METADATA_CONFLICT",
            ),
            (
                "display_p3_bad_gamma",
                _DISPLAY_P3_PROFILE,
                _png_color_contract(1.0, _DISPLAY_P3_CHROMATICITY),
                "FORMAL_COLOR_METADATA_CONFLICT",
            ),
            (
                "unknown_profile",
                ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes(),
                _png_color_contract(0.45455, _DISPLAY_P3_CHROMATICITY),
                "FORMAL_COLOR_NON_SRGB_PROFILE_SAFE_BLOCKED",
            ),
            (
                "malformed_profile",
                b"not-an-icc-profile",
                _png_color_contract(0.45455, _DISPLAY_P3_CHROMATICITY),
                "FORMAL_COLOR_ICC_INVALID",
            ),
        )
        for name, profile, metadata, expected_error in cases:
            with self.subTest(case=name):
                source = self.root / f"{name}.png"
                Image.fromarray(rgb, mode="RGB").save(
                    source,
                    icc_profile=profile,
                    pnginfo=metadata,
                )
                with self.assertRaisesRegex(ColorManagementError, expected_error):
                    load_color_managed_source(source)

    def test_wide_gamut_png_in_family_metadata_conflicts_are_blocked(self) -> None:
        rgb = _wide_gamut_test_image()
        cases = (
            (
                "display_p3_in_family_chromaticity",
                _DISPLAY_P3_PROFILE,
                0.45455,
                (0.3127, 0.3290, 0.6800, 0.3200, 0.2660, 0.6900, 0.1500, 0.0600),
            ),
            (
                "adobe_rgb_in_family_chromaticity",
                _ADOBE_RGB_1998_PROFILE,
                1.0 / 2.19921875,
                (0.3127, 0.3290, 0.6400, 0.3300, 0.2110, 0.7100, 0.1500, 0.0600),
            ),
            (
                "display_p3_nearby_gamma",
                _DISPLAY_P3_PROFILE,
                0.45480,
                _DISPLAY_P3_CHROMATICITY,
            ),
            (
                "adobe_rgb_nearby_gamma",
                _ADOBE_RGB_1998_PROFILE,
                (1.0 / 2.19921875) + 0.00025,
                _ADOBE_RGB_1998_CHROMATICITY,
            ),
            (
                "display_p3_profile_trc_conflict",
                _profile_with_mutated_parametric_trc_gamma(_DISPLAY_P3_PROFILE, 2.2),
                0.45455,
                _DISPLAY_P3_CHROMATICITY,
            ),
        )
        for name, profile, gamma, chromaticity in cases:
            with self.subTest(case=name):
                source = self.root / f"{name}.png"
                Image.fromarray(rgb, mode="RGB").save(
                    source,
                    icc_profile=profile,
                    pnginfo=_png_color_contract(gamma, chromaticity),
                )
                with self.assertRaisesRegex(ColorManagementError, "FORMAL_COLOR_METADATA_CONFLICT"):
                    load_color_managed_source(source)

    def test_srgb_metadata_is_accepted_but_conflicting_png_and_exif_are_blocked(self) -> None:
        rgb = _as_uint8("neutral_scene")
        declared = self.root / "declared_srgb.png"
        declared_info = PngImagePlugin.PngInfo()
        declared_info.add(b"sRGB", b"\x00")
        Image.fromarray(rgb, mode="RGB").save(declared, pnginfo=declared_info)
        self.assertEqual(load_color_managed_source(declared).profile_status, "ASSUMED_SRGB")

        tagged_declared = self.root / "tagged_declared_srgb.png"
        Image.fromarray(rgb, mode="RGB").save(
            tagged_declared,
            icc_profile=srgb_profile_bytes(),
            pnginfo=_png_color_contract(0.45455, _SRGB_CHROMATICITY),
        )
        self.assertEqual(
            load_color_managed_source(tagged_declared).profile_status,
            "CMM_CONVERTED_TO_SRGB",
        )

        conflict_specs = (
            ("gamma", b"gAMA", struct.pack(">I", 100000), None),
            ("profile_gamma", b"gAMA", struct.pack(">I", 100000), srgb_profile_bytes()),
            (
                "chromaticity",
                b"cHRM",
                struct.pack(">8I", 40000, 32900, 64000, 33000, 30000, 60000, 15000, 6000),
                None,
            ),
        )
        for name, chunk, payload, icc_profile in conflict_specs:
            with self.subTest(metadata=name):
                source = self.root / f"{name}_conflict.png"
                output = self.root / f"{name}_conflict_output.png"
                info = PngImagePlugin.PngInfo()
                info.add(chunk, payload)
                Image.fromarray(rgb, mode="RGB").save(
                    source,
                    pnginfo=info,
                    icc_profile=icc_profile,
                )
                source_sha = _sha256(source)
                with self.assertRaisesRegex(ColorManagementError, "FORMAL_COLOR_METADATA_CONFLICT"):
                    load_color_managed_source(source)
                with self.assertRaisesRegex(ColorManagementError, "FORMAL_COLOR_METADATA_CONFLICT"):
                    run_formal_color_runtime(source, output)
                self.assertEqual(_sha256(source), source_sha)
                self.assertFalse(output.exists())

        exif_conflict = self.root / "exif_conflict.jpg"
        exif = Image.Exif()
        exif[ExifTags.IFD.Exif] = {40961: 65535}
        Image.fromarray(rgb, mode="RGB").save(exif_conflict, exif=exif)
        with self.assertRaisesRegex(ColorManagementError, "FORMAL_COLOR_METADATA_CONFLICT"):
            load_color_managed_source(exif_conflict)

        interop_conflict = self.root / "interop_conflict.jpg"
        exif = Image.Exif()
        exif[ExifTags.IFD.Exif] = {
            40961: 1,
            ExifTags.IFD.Interop: {1: "R03"},
        }
        Image.fromarray(rgb, mode="RGB").save(interop_conflict, exif=exif)
        with self.assertRaisesRegex(ColorManagementError, "FORMAL_COLOR_METADATA_CONFLICT"):
            load_color_managed_source(interop_conflict)

    def test_formal_runtime_preserves_rgba_alpha_and_writes_png_icc(self) -> None:
        source = self.root / "too_dark_rgba.png"
        output = self.root / "too_dark_rgba_output.png"
        rgb = _as_uint8("too_dark")
        rgb = np.repeat(np.median(rgb, axis=1).astype(np.uint8)[:, None, :], rgb.shape[1], axis=1)
        alpha = np.tile(np.linspace(0, 255, rgb.shape[1], dtype=np.uint8), (rgb.shape[0], 1))
        rgba = np.dstack((rgb, alpha))
        Image.fromarray(rgba, mode="RGBA").save(source)
        source_sha = _sha256(source)

        result = run_formal_color_runtime(source, output)

        self.assertEqual(result.result_action, "ACCEPT_CORRECTED")
        self.assertEqual(result.output_selected, "CORRECTED_CANDIDATE")
        self.assertTrue(result.output_metadata and result.output_metadata["written"])
        self.assertEqual(read_hdde_metadata(output)["software"], HDDE_SOFTWARE)
        self.assertTrue(output.is_file())
        with Image.open(output) as opened:
            self.assertEqual(opened.mode, "RGBA")
            self.assertIn("srgb", _profile_label(opened.info["icc_profile"]))
            decoded = np.asarray(opened)
            self.assertTrue(np.array_equal(decoded[..., 3], alpha))
            transparent = alpha == 0
            self.assertTrue(np.array_equal(decoded[..., :3][transparent], rgba[..., :3][transparent]))
            alpha01 = alpha.astype(np.float32)[..., None] / 255.0
            black_composite = decoded[..., :3].astype(np.float32) * alpha01
            white_composite = black_composite + 255.0 * (1.0 - alpha01)
            self.assertTrue(np.all(np.diff(black_composite, axis=1) >= -1e-5))
            self.assertTrue(np.all(np.diff(white_composite, axis=1) <= 1e-5))
        self.assertEqual(_sha256(source), source_sha)

    def test_formal_runtime_never_overwrites_a_racing_destination(self) -> None:
        source = self.root / "too_dark_collision.png"
        output = self.root / "protected_owner.png"
        rgb = _as_uint8("too_dark")
        rgb = np.repeat(np.median(rgb, axis=1).astype(np.uint8)[:, None, :], rgb.shape[1], axis=1)
        Image.fromarray(rgb, mode="RGB").save(source)
        protected = b"existing-owner"
        output.write_bytes(protected)

        with self.assertRaises(FileExistsError):
            run_formal_color_runtime(source, output)

        self.assertEqual(output.read_bytes(), protected)

    def test_jpeg_encoder_writes_matching_srgb_profile(self) -> None:
        source = self.root / "tagged.jpg"
        output = self.root / "tagged_output.jpg"
        rgb = _as_uint8("too_dark")
        Image.fromarray(rgb, mode="RGB").save(
            source,
            format="JPEG",
            quality=100,
            subsampling=0,
            icc_profile=srgb_profile_bytes(),
        )
        managed = load_color_managed_source(source)

        output.write_bytes(encode_color_managed_candidate(managed.pixels, managed))
        verify_color_managed_output(output, managed.pixels, managed)

        with Image.open(output) as opened:
            self.assertEqual(opened.mode, "RGB")
            self.assertIn("srgb", _profile_label(opened.info["icc_profile"]))

    def test_alpha_change_is_rejected_before_encoding(self) -> None:
        source = self.root / "alpha.png"
        rgb = _as_uint8("neutral_scene")
        alpha = np.tile(np.arange(rgb.shape[1], dtype=np.uint8), (rgb.shape[0], 1))
        rgba = np.dstack((rgb, alpha))
        Image.fromarray(rgba, mode="RGBA").save(source)
        managed = load_color_managed_source(source)
        changed = managed.pixels.copy()
        changed[0, 0, 3] ^= np.uint8(255)

        with self.assertRaisesRegex(ColorManagementError, "FORMAL_COLOR_ALPHA_CHANGED"):
            encode_color_managed_candidate(changed, managed)

        hidden_rgb_changed = managed.pixels.copy()
        transparent = managed.pixels[..., 3] == 0
        hidden_rgb_changed[..., 0][transparent] ^= np.uint8(255)
        with self.assertRaisesRegex(ColorManagementError, "FORMAL_COLOR_TRANSPARENT_RGB_CHANGED"):
            encode_color_managed_candidate(hidden_rgb_changed, managed)

    def test_exif_orientation_is_normalized_once_without_geometry_loss(self) -> None:
        source = self.root / "oriented.png"
        output = self.root / "oriented_output.png"
        rgb = np.zeros((40, 70, 3), dtype=np.uint8)
        rgb[:20, :35] = (230, 21, 47)
        rgb[:20, 35:] = (31, 210, 63)
        rgb[20:, :] = (17, 53, 225)
        exif = Image.Exif()
        exif[274] = 6
        Image.fromarray(rgb, mode="RGB").save(source, exif=exif)

        managed = load_color_managed_source(source)

        self.assertEqual(managed.pixels.shape, (70, 40, 3))
        output.write_bytes(encode_color_managed_candidate(managed.pixels, managed))
        verify_color_managed_output(output, managed.pixels, managed)
        with Image.open(output) as opened:
            self.assertEqual(opened.size, (40, 70))
            self.assertNotIn(274, opened.getexif())
            self.assertTrue(np.array_equal(np.asarray(opened), managed.pixels))

    def test_corrupt_and_non_srgb_profiles_fail_closed(self) -> None:
        rgb = _as_uint8("neutral_scene")
        corrupt = self.root / "corrupt_icc.png"
        Image.fromarray(rgb, mode="RGB").save(corrupt, icc_profile=b"not-an-icc-profile")
        with self.assertRaisesRegex(ColorManagementError, "FORMAL_COLOR_ICC_INVALID"):
            load_color_managed_source(corrupt)

        non_srgb = self.root / "non_srgb.png"
        lab_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
        Image.fromarray(rgb, mode="RGB").save(non_srgb, icc_profile=lab_profile)
        with self.assertRaisesRegex(
            ColorManagementError,
            "FORMAL_COLOR_NON_SRGB_PROFILE_SAFE_BLOCKED",
        ):
            load_color_managed_source(non_srgb)

        mislabeled = self.root / "mislabeled_srgb.png"
        Image.fromarray(rgb, mode="RGB").save(
            mislabeled,
            icc_profile=_srgb_label_with_mutated_colorimetry(),
        )
        with Image.open(mislabeled) as opened:
            self.assertIn("srgb", _profile_label(opened.info["icc_profile"]))
        with self.assertRaisesRegex(
            ColorManagementError,
            "FORMAL_COLOR_NON_SRGB_PROFILE_SAFE_BLOCKED",
        ):
            load_color_managed_source(mislabeled)

        malformed_display_p3 = self.root / "malformed_display_p3.png"
        Image.fromarray(rgb, mode="RGB").save(
            malformed_display_p3,
            icc_profile=_profile_with_mutated_colorimetry(_DISPLAY_P3_PROFILE),
        )
        with Image.open(malformed_display_p3) as opened:
            self.assertIn("display p3", _profile_label(opened.info["icc_profile"]))
        with self.assertRaisesRegex(
            ColorManagementError,
            "FORMAL_COLOR_NON_SRGB_PROFILE_SAFE_BLOCKED",
        ):
            load_color_managed_source(malformed_display_p3)

    def test_16bit_png_is_blocked_without_downconversion(self) -> None:
        source = self.root / "sixteen_bit.png"
        output = self.root / "sixteen_bit_output.png"
        yy, xx = np.indices((72, 96))
        rgb16 = np.stack(
            (
                (xx * 613 + 1024) % 65536,
                (yy * 877 + 2048) % 65536,
                ((xx + yy) * 431 + 4096) % 65536,
            ),
            axis=2,
        ).astype(np.uint16)
        ok, encoded = cv2.imencode(".png", rgb16[..., ::-1])
        self.assertTrue(ok)
        source.write_bytes(encoded.tobytes())
        source_sha = _sha256(source)

        with self.assertRaisesRegex(
            ColorManagementError,
            "FORMAL_COLOR_16BIT_AUTO_SUPPORT_SAFE_BLOCKED",
        ):
            load_color_managed_source(source)
        with self.assertRaisesRegex(
            ColorManagementError,
            "FORMAL_COLOR_16BIT_AUTO_SUPPORT_SAFE_BLOCKED",
        ):
            run_formal_color_runtime(source, output)

        decoded = cv2.imdecode(np.frombuffer(source.read_bytes(), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        self.assertEqual(decoded.dtype, np.uint16)
        self.assertEqual(_sha256(source), source_sha)
        self.assertFalse(output.exists())

    def test_cmyk_and_multiframe_inputs_fail_closed(self) -> None:
        cmyk = self.root / "cmyk.jpg"
        Image.new("CMYK", (64, 64), (10, 20, 30, 4)).save(cmyk)
        with self.assertRaisesRegex(ColorManagementError, "FORMAL_COLOR_MODE_UNSUPPORTED"):
            load_color_managed_source(cmyk)

        animated = self.root / "animated.png"
        first = Image.new("RGB", (64, 64), (20, 30, 40))
        second = Image.new("RGB", (64, 64), (50, 60, 70))
        first.save(animated, save_all=True, append_images=[second], duration=100, loop=0)
        with self.assertRaisesRegex(ColorManagementError, "FORMAL_COLOR_MULTIFRAME_UNSUPPORTED"):
            load_color_managed_source(animated)


if __name__ == "__main__":
    unittest.main()
