from __future__ import annotations

import copy
from dataclasses import replace
import gc
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image

from engine import color_correction
from engine.color_correction import color_management
from engine.color_correction.color_management import (
    MANAGED_COLOR_SOURCE_ATOMIC_SNAPSHOT_VERSION,
    MANAGED_COLOR_SOURCE_PROVENANCE_VERSION,
    ManagedColorSource,
    acquire_validated_managed_source_snapshot,
    load_color_managed_source,
    validate_managed_color_source_provenance,
)
from engine.color_correction import v3_white_balance_prototype as white_balance_prototype
from engine.color_correction.v3_white_balance_prototype import (
    EVIDENCE_IDENTITY_BINDING_VERSION,
    RGBA_ALPHA_MODE_CONTRACT_VERSION,
    V3_WHITE_BALANCE_PROTOTYPE_VERSION,
    run_v3_white_balance_prototype,
    validate_v3_evidence_record,
)


def _srgb_to_linear(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    return np.where(
        values <= 0.04045,
        values / 12.92,
        ((values + 0.055) / 1.055) ** 2.4,
    )


def _linear_to_srgb(values: np.ndarray) -> np.ndarray:
    values = np.clip(np.asarray(values, dtype=np.float32), 0.0, 1.0)
    return np.where(
        values <= 0.0031308,
        values * 12.92,
        1.055 * np.power(values, 1.0 / 2.4) - 0.055,
    )


def _controlled_scene(cast: tuple[float, float, float] | None) -> tuple[np.ndarray, np.ndarray]:
    height, width = 96, 128
    ramp = np.linspace(0.16, 0.82, width, dtype=np.float32)
    ground_truth = np.repeat(ramp[None, :, None], height, axis=0)
    ground_truth = np.repeat(ground_truth, 3, axis=2)
    ground_truth[12:36, 12:42] = np.array([0.72, 0.20, 0.10], dtype=np.float32)
    ground_truth[56:84, 18:48] = np.array([0.12, 0.36, 0.76], dtype=np.float32)
    ground_truth[20:56, 82:118] = np.array([0.62, 0.36, 0.24], dtype=np.float32)

    if cast is None:
        source = ground_truth
    else:
        source_linear = _srgb_to_linear(ground_truth)
        source = _linear_to_srgb(source_linear * np.asarray(cast, dtype=np.float32))
    source_u8 = np.rint(source * 255.0).astype(np.uint8)

    neutral = np.ones((height, width), dtype=bool)
    neutral[12:36, 12:42] = False
    neutral[56:84, 18:48] = False
    neutral[20:56, 82:118] = False
    return source_u8, neutral


def _neutral_channel_spread(image: np.ndarray, mask: np.ndarray) -> float:
    medians = np.median(image[..., :3][mask].astype(np.float32), axis=0)
    return float(medians.max() - medians.min())


def _validated_rgba_source(rgba: np.ndarray):
    """Round-trip through the existing decoder that establishes straight Alpha."""

    with TemporaryDirectory() as temporary:
        source_path = Path(temporary) / "validated-straight-alpha.png"
        Image.fromarray(np.asarray(rgba, dtype=np.uint8), mode="RGBA").save(source_path)
        return load_color_managed_source(source_path)


def _validated_controlled_rgba_source() -> tuple[ManagedColorSource, np.ndarray]:
    source, _ = _controlled_scene((1.18, 1.0, 0.82))
    alpha = np.full(source.shape[:2], 255, dtype=np.uint8)
    alpha[:, 12:20] = 254
    rgba = np.dstack((source, alpha))
    return _validated_rgba_source(rgba), rgba


def _unregistered_managed_source(
    source: ManagedColorSource,
    *,
    pixels: np.ndarray | None = None,
    **overrides,
) -> ManagedColorSource:
    values = {
        "pixels": source.pixels if pixels is None else pixels,
        "source_format": source.source_format,
        "source_mode": source.source_mode,
        "source_bit_depth": source.source_bit_depth,
        "input_order": source.input_order,
        "profile_status": source.profile_status,
        "source_profile_name": source.source_profile_name,
        "output_icc_profile": source.output_icc_profile,
        "frame_count": source.frame_count,
    }
    values.update(overrides)
    return ManagedColorSource(**values)


class V3WhiteBalancePrototypeTests(unittest.TestCase):
    def test_per_channel_highlight_headroom_limits_mix_without_global_darkening(self) -> None:
        channel_cases = (
            ("R", 0, (0.84, 1.0, 1.17)),
            ("G", 1, (1.15, 0.84, 1.15)),
            ("B", 2, (1.18, 1.0, 0.82)),
        )
        for label, corrected_channel, cast in channel_cases:
            with self.subTest(channel=label):
                source, _ = _controlled_scene(cast)
                near_highlight = np.zeros(source.shape[:2], dtype=bool)
                near_highlight[40:48, 60:68] = True
                source[near_highlight] = 253
                source_before = source.copy()

                result = run_v3_white_balance_prototype(source)

                self.assertEqual(result.status, "CANDIDATE_READY")
                self.assertIsNone(result.blocker)
                self.assertTrue(np.array_equal(source, source_before))
                self.assertEqual(result.candidate_image.shape, source.shape)
                self.assertEqual(result.candidate_image.dtype, source.dtype)
                self.assertLessEqual(
                    int(result.candidate_image[..., corrected_channel][near_highlight].max()),
                    253,
                )
                new_highlight = (
                    (result.candidate_image[..., :3] >= 254)
                    & (source[..., :3] < 254)
                )
                self.assertFalse(new_highlight.any())
                non_highlight = ~near_highlight
                self.assertGreater(
                    int(
                        np.any(
                            result.candidate_image[..., :3] != source[..., :3],
                            axis=2,
                        )[non_highlight].sum()
                    ),
                    0,
                )
                source_luma = np.tensordot(
                    _srgb_to_linear(source.astype(np.float32) / 255.0),
                    np.array([0.2126, 0.7152, 0.0722], dtype=np.float32),
                    axes=([2], [0]),
                )
                candidate_luma = np.tensordot(
                    _srgb_to_linear(
                        result.candidate_image[..., :3].astype(np.float32) / 255.0
                    ),
                    np.array([0.2126, 0.7152, 0.0722], dtype=np.float32),
                    axes=([2], [0]),
                )
                self.assertLessEqual(
                    abs(float(candidate_luma.mean() - source_luma.mean())),
                    result.diagnostics["final_luminance_mean_limit"],
                )
                self.assertGreater(
                    result.diagnostics["headroom_limited_pixel_count"],
                    0,
                )
                self.assertLess(
                    result.diagnostics["headroom_safe_mix_factor_min"],
                    1.0,
                )
                self.assertEqual(
                    result.diagnostics["independent_replay_max_rgb_byte_delta"],
                    0,
                )

    def test_bright_neutral_anchor_majority_overshoot_fails_closed(self) -> None:
        source = np.full((96, 128, 3), (130, 145, 160), dtype=np.uint8)
        for row in range(4):
            for column in range(4):
                row_start = row * 24 + 6
                column_start = column * 32 + 8
                source[
                    row_start : row_start + 12,
                    column_start : column_start + 16,
                ] = np.array((190, 198, 208), dtype=np.uint8)
        source_before = source.copy()

        result = run_v3_white_balance_prototype(source)

        self.assertEqual(result.status, "NOT_APPLICABLE")
        self.assertEqual(result.blocker, "BRIGHT_NEUTRAL_ANCHOR_OVERSHOOT")
        self.assertIsNone(result.candidate_image)
        self.assertTrue(np.array_equal(source, source_before))
        self.assertEqual(result.diagnostics["normal_image_protection_gate"], "FAIL")
        self.assertGreater(
            result.diagnostics["bright_neutral_anchor_opposite_shift_ratio"],
            0.5,
        )
        self.assertEqual(result.diagnostics["new_highlight_clipped_channel_count"], 0)
        self.assertEqual(result.diagnostics["independent_replay_max_rgb_byte_delta"], 0)

        clear_cast, _ = _controlled_scene((1.18, 1.0, 0.82))
        clear_result = run_v3_white_balance_prototype(clear_cast)
        self.assertEqual(clear_result.status, "CANDIDATE_READY")
        self.assertIsNone(clear_result.blocker)
        self.assertIn(
            clear_result.diagnostics["normal_image_protection_gate"],
            ("PASS", "NOT_EVALUABLE"),
        )
        self.assertEqual(clear_result.diagnostics["new_highlight_clipped_channel_count"], 0)
        self.assertEqual(clear_result.diagnostics["independent_replay_max_rgb_byte_delta"], 0)

    def test_warm_and_cool_casts_produce_bounded_review_only_candidates(self) -> None:
        for cast in ((1.18, 1.0, 0.82), (0.84, 1.0, 1.17)):
            with self.subTest(cast=cast):
                source, neutral = _controlled_scene(cast)
                result = run_v3_white_balance_prototype(source)

                self.assertEqual(result.status, "CANDIDATE_READY")
                self.assertEqual(result.disposition, "ISOLATED_REVIEW_ONLY")
                self.assertIsNone(result.blocker)
                self.assertIsNotNone(result.candidate_image)
                self.assertEqual(result.candidate_image.dtype, source.dtype)
                self.assertEqual(result.candidate_image.shape, source.shape)
                self.assertLess(
                    _neutral_channel_spread(result.candidate_image, neutral),
                    _neutral_channel_spread(source, neutral) * 0.72,
                )
                self.assertGreater(result.diagnostics["neutral_error_improvement_ratio"], 0.20)
                self.assertLessEqual(result.diagnostics["new_clipping_growth"], 0.002)
                self.assertEqual(result.diagnostics["candidate_safety_gate"], "PASS")
                self.assertLessEqual(
                    result.diagnostics["independent_replay_max_rgb_byte_delta"],
                    result.diagnostics["independent_replay_rgb_byte_limit"],
                )
                self.assertEqual(
                    result.diagnostics["candidate_reference_authority"],
                    "SOURCE_DRIVEN_INDEPENDENT_REPLAY_NOT_CANDIDATE_NEIGHBORS",
                )
                self.assertEqual(result.diagnostics["new_shadow_clipped_channel_count"], 0)
                self.assertEqual(result.diagnostics["new_highlight_clipped_channel_count"], 0)
                self.assertLessEqual(
                    result.diagnostics["final_luminance_p95_abs_delta"],
                    result.diagnostics["final_luminance_p95_limit"],
                )
                self.assertFalse(result.to_record()["candidate_available"] is False)

    def test_alpha_hidden_rgb_and_hard_protection_are_pixel_exact(self) -> None:
        source_rgb, _ = _controlled_scene((1.18, 1.0, 0.82))
        alpha = np.full(source_rgb.shape[:2], 255, dtype=np.uint8)
        alpha[:, :8] = 0
        alpha[:, 8:12] = 2
        alpha[:, 50:58] = np.array([16, 48, 80, 112, 144, 176, 208, 240], dtype=np.uint8)
        rgba = np.dstack((source_rgb, alpha))
        rgba[:, :12, :3] = np.array([7, 249, 31], dtype=np.uint8)
        protected = np.zeros(source_rgb.shape[:2], dtype=bool)
        protected[20:56, 82:118] = True

        managed = _validated_rgba_source(rgba)
        result = run_v3_white_balance_prototype(
            managed,
            hard_protection_mask=protected,
        )

        self.assertEqual(result.status, "CANDIDATE_READY")
        self.assertTrue(np.array_equal(result.candidate_image[..., 3], rgba[..., 3]))
        self.assertTrue(np.array_equal(result.candidate_image[alpha <= 2], rgba[alpha <= 2]))
        self.assertTrue(np.array_equal(result.candidate_image[protected], rgba[protected]))
        self.assertEqual(result.diagnostics["protected_pixel_count"], int(protected.sum()))
        self.assertEqual(result.diagnostics["hidden_pixel_count"], int((alpha <= 2).sum()))
        self.assertEqual(
            result.diagnostics["illuminant_evidence_policy"],
            "OPAQUE_UNPROTECTED_SOURCE_PIXELS_ONLY",
        )
        self.assertEqual(
            result.diagnostics["rgba_alpha_mode_contract"],
            RGBA_ALPHA_MODE_CONTRACT_VERSION,
        )
        self.assertEqual(result.diagnostics["alpha_mode"], "STRAIGHT_VALIDATED")
        self.assertEqual(
            result.diagnostics["alpha_mode_provenance"],
            "VALIDATED_COLOR_MANAGEMENT_DECODER_V1",
        )
        self.assertEqual(
            result.diagnostics["illuminant_evidence_pixel_count"],
            int(((alpha == 255) & ~protected).sum()),
        )
        self.assertEqual(result.diagnostics["partial_alpha_pixel_count"], int(((alpha > 2) & (alpha < 255)).sum()))
        self.assertLessEqual(
            result.diagnostics["partial_alpha_replay_max_rgb_byte_delta"],
            result.diagnostics["independent_replay_rgb_byte_limit"],
        )
        self.assertEqual(result.diagnostics["partial_alpha_source_unsupported_pixel_count"], 0)
        self.assertEqual(result.diagnostics["partial_alpha_outcome_unsupported_pixel_count"], 0)
        self.assertEqual(result.diagnostics["partial_alpha_outcome_gate"], "PASS")
        self.assertGreater(
            result.diagnostics["partial_alpha_source_to_replay_black_composite_max_delta"],
            0.0,
        )
        self.assertEqual(
            result.diagnostics["partial_alpha_outcome_reference_authority"],
            "SOURCE_ONLY_TRUSTED_OPAQUE_SEEDS_AND_REPLAY_FIELD",
        )
        self.assertFalse(result.diagnostics["partial_alpha_black_white_independent_authority"])

    def test_near_transparent_neutrals_cannot_authorize_global_white_balance(self) -> None:
        height, width = 96, 128
        source_rgb = np.empty((height, width, 3), dtype=np.uint8)
        source_rgb[:] = np.array([45, 110, 210], dtype=np.uint8)
        alpha = np.zeros((height, width), dtype=np.uint8)
        alpha[38:58, 54:74] = 255

        patch_starts = ((8, 8), (8, 104), (72, 8), (72, 104))
        near_transparent = np.zeros((height, width), dtype=bool)
        opaque_non_neutral_seeds = np.zeros((height, width), dtype=bool)
        for row, column in patch_starts:
            near_transparent[row : row + 8, column : column + 8] = True
            opaque_non_neutral_seeds[
                row + 3 : row + 5,
                column + 3 : column + 5,
            ] = True

        source_rgb[near_transparent] = np.array([200, 160, 156], dtype=np.uint8)
        alpha[near_transparent] = 3
        source_rgb[opaque_non_neutral_seeds] = np.array(
            [200, 160, 150],
            dtype=np.uint8,
        )
        alpha[opaque_non_neutral_seeds] = 255

        result = run_v3_white_balance_prototype(
            _validated_rgba_source(np.dstack((source_rgb, alpha)))
        )

        self.assertEqual(result.status, "NOT_EVALUABLE")
        self.assertEqual(result.blocker, "INSUFFICIENT_DISTRIBUTED_NEUTRAL_EVIDENCE")
        self.assertIsNone(result.candidate_image)
        self.assertEqual(
            result.diagnostics["illuminant_evidence_policy"],
            "OPAQUE_UNPROTECTED_SOURCE_PIXELS_ONLY",
        )
        self.assertEqual(result.diagnostics["neutral_pixel_count"], 0)
        self.assertEqual(
            result.diagnostics["partial_alpha_illuminant_evidence_excluded_pixel_count"],
            int((near_transparent & ~opaque_non_neutral_seeds).sum()),
        )

    def test_relocated_channel_clipping_cannot_be_hidden_by_equal_aggregate_ratio(self) -> None:
        evaluate = getattr(white_balance_prototype, "_evaluate_candidate_safety", None)
        self.assertIsNotNone(evaluate, "prototype must expose its internal non-compensatory safety gate")

        source = np.full((8, 8, 3), 128, dtype=np.uint8)
        candidate = source.copy()
        analysis = np.ones(source.shape[:2], dtype=bool)
        source[0, 0, 0] = 255
        candidate[0, 0, 0] = 253
        candidate[0, 1, 1] = 254

        diagnostics, blocker = evaluate(source, candidate, analysis, alpha=None)

        self.assertEqual(diagnostics["source_clipping_ratio"], diagnostics["candidate_clipping_ratio"])
        self.assertEqual(diagnostics["released_highlight_clipped_channel_count"], 1)
        self.assertEqual(diagnostics["new_highlight_clipped_channel_count"], 1)
        self.assertEqual(blocker, "NEW_HIGHLIGHT_CLIPPING")

    def test_final_luminance_gate_uses_absolute_post_quantization_error(self) -> None:
        evaluate = getattr(white_balance_prototype, "_evaluate_candidate_safety", None)
        self.assertIsNotNone(evaluate, "prototype must expose its internal final-output safety gate")

        source = np.full((8, 8, 3), 128, dtype=np.uint8)
        candidate = source.copy()
        candidate[:4] = 148
        candidate[4:] = 108
        analysis = np.ones(source.shape[:2], dtype=bool)

        diagnostics, blocker = evaluate(source, candidate, analysis, alpha=None)

        self.assertGreater(
            diagnostics["final_luminance_mean_abs_delta"],
            diagnostics["final_luminance_mean_limit"],
        )
        self.assertGreater(
            diagnostics["final_luminance_p95_abs_delta"],
            diagnostics["final_luminance_p95_limit"],
        )
        self.assertEqual(blocker, "FINAL_LUMINANCE_DRIFT")

    def test_partial_alpha_gradient_rejects_one_sparse_composite_fringe(self) -> None:
        evaluate = getattr(white_balance_prototype, "_evaluate_candidate_safety", None)
        self.assertIsNotNone(evaluate, "prototype must expose its internal Alpha-composite safety gate")

        source = np.full((8, 8, 3), 112, dtype=np.uint8)
        alpha_row = np.array([0, 16, 48, 96, 160, 224, 255, 255], dtype=np.uint8)
        alpha = np.repeat(alpha_row[None, :], source.shape[0], axis=0)
        analysis = alpha > 2
        safe_candidate = source.copy()

        safe_diagnostics, safe_blocker = evaluate(source, safe_candidate, analysis, alpha=alpha)

        self.assertIsNone(safe_blocker)
        self.assertLessEqual(
            safe_diagnostics["partial_alpha_replay_max_rgb_byte_delta"],
            safe_diagnostics["independent_replay_rgb_byte_limit"],
        )

        fringe_candidate = safe_candidate.copy()
        fringe_candidate[3, 4, 0] += 1
        fringe_diagnostics, fringe_blocker = evaluate(source, fringe_candidate, analysis, alpha=alpha)

        self.assertGreater(
            fringe_diagnostics["partial_alpha_replay_max_rgb_byte_delta"],
            fringe_diagnostics["independent_replay_rgb_byte_limit"],
        )
        self.assertEqual(fringe_blocker, "PARTIAL_ALPHA_INDEPENDENT_REPLAY_MISMATCH")

        isolated_source = np.full((5, 5, 3), 32, dtype=np.uint8)
        isolated_source[2, 2] = np.array([180, 90, 150], dtype=np.uint8)
        isolated_alpha = np.full((5, 5), 255, dtype=np.uint8)
        isolated_alpha[2, 2] = 128
        isolated_analysis = np.ones((5, 5), dtype=bool)
        isolated_diagnostics, isolated_blocker = evaluate(
            isolated_source,
            isolated_source.copy(),
            isolated_analysis,
            alpha=isolated_alpha,
        )

        self.assertEqual(isolated_diagnostics["partial_alpha_replay_max_rgb_byte_delta"], 0)
        self.assertEqual(isolated_diagnostics["partial_alpha_source_unsupported_pixel_count"], 1)
        self.assertEqual(isolated_blocker, "PARTIAL_ALPHA_SOURCE_SUPPORT_NOT_EVALUABLE")

    def test_synchronized_partial_component_cannot_self_authorize_against_source_replay(self) -> None:
        evaluate = getattr(white_balance_prototype, "_evaluate_candidate_safety", None)
        self.assertIsNotNone(evaluate, "prototype must expose its internal Alpha safety gate")

        source, _ = _controlled_scene((1.18, 1.0, 0.82))
        alpha = np.full(source.shape[:2], 255, dtype=np.uint8)
        alpha[:, 12:20] = np.array([16, 48, 80, 112, 144, 176, 208, 240], dtype=np.uint8)
        analysis = alpha > 2
        expected_result = run_v3_white_balance_prototype(
            _validated_rgba_source(np.dstack((source, alpha)))
        )
        self.assertEqual(expected_result.status, "CANDIDATE_READY")
        synchronized_corruption = expected_result.candidate_image[..., :3].copy()
        partial = analysis & (alpha < 255)
        synchronized_corruption[partial] = np.clip(
            synchronized_corruption[partial].astype(np.int16)
            + np.array([1, -1, 0], dtype=np.int16),
            0,
            255,
        ).astype(np.uint8)

        diagnostics, blocker = evaluate(
            source,
            synchronized_corruption,
            analysis,
            alpha=alpha,
        )

        self.assertGreater(
            diagnostics["partial_alpha_replay_max_rgb_byte_delta"],
            diagnostics["independent_replay_rgb_byte_limit"],
        )
        self.assertEqual(
            diagnostics["candidate_reference_authority"],
            "SOURCE_DRIVEN_INDEPENDENT_REPLAY_NOT_CANDIDATE_NEIGHBORS",
        )
        self.assertEqual(blocker, "PARTIAL_ALPHA_INDEPENDENT_REPLAY_MISMATCH")

    def test_eligible_cast_with_unsupported_partial_pixel_fails_closed(self) -> None:
        source, _ = _controlled_scene((1.18, 1.0, 0.82))
        source = source.copy()
        row, column = 44, 64
        source[row, column] = np.array([203, 73, 149], dtype=np.uint8)
        alpha = np.full(source.shape[:2], 255, dtype=np.uint8)
        alpha[row, column] = 128

        result = run_v3_white_balance_prototype(
            _validated_rgba_source(np.dstack((source, alpha)))
        )

        self.assertEqual(result.status, "PROTECTION_BLOCKED")
        self.assertEqual(result.blocker, "PARTIAL_ALPHA_SOURCE_SUPPORT_NOT_EVALUABLE")
        self.assertIsNone(result.candidate_image)
        self.assertEqual(result.diagnostics["partial_alpha_source_unsupported_pixel_count"], 1)
        self.assertGreater(
            result.diagnostics["partial_alpha_source_to_replay_black_composite_max_delta"],
            0.0,
        )

    def test_no_cast_and_missing_neutral_evidence_do_not_create_candidates(self) -> None:
        balanced, _ = _controlled_scene(None)
        balanced_result = run_v3_white_balance_prototype(balanced)
        self.assertEqual(balanced_result.status, "NOT_APPLICABLE")
        self.assertEqual(balanced_result.blocker, "NO_MEANINGFUL_GLOBAL_CAST")
        self.assertIsNone(balanced_result.candidate_image)

        saturated = np.zeros((80, 120, 3), dtype=np.uint8)
        saturated[:, :60] = np.array([255, 0, 0], dtype=np.uint8)
        saturated[:, 60:] = np.array([0, 0, 255], dtype=np.uint8)
        missing = run_v3_white_balance_prototype(saturated)
        self.assertEqual(missing.status, "NOT_EVALUABLE")
        self.assertEqual(missing.blocker, "INSUFFICIENT_DISTRIBUTED_NEUTRAL_EVIDENCE")
        self.assertIsNone(missing.candidate_image)

        local_only = saturated.copy()
        local_only[:20, :20] = np.array([128, 128, 128], dtype=np.uint8)
        local_result = run_v3_white_balance_prototype(local_only)
        self.assertGreaterEqual(
            local_result.diagnostics["neutral_pixel_count"],
            local_result.diagnostics["minimum_neutral_pixel_count"],
        )
        self.assertLess(local_result.diagnostics["neutral_occupied_cells_4x4"], 4)
        self.assertEqual(local_result.status, "NOT_EVALUABLE")
        self.assertEqual(local_result.blocker, "INSUFFICIENT_DISTRIBUTED_NEUTRAL_EVIDENCE")
        self.assertIsNone(local_result.candidate_image)

    def test_input_contract_is_fail_closed_and_bgr_is_equivalent(self) -> None:
        source, _ = _controlled_scene((1.18, 1.0, 0.82))
        rgb = run_v3_white_balance_prototype(source)
        bgr = run_v3_white_balance_prototype(source[..., ::-1], input_order="BGR")

        self.assertEqual(rgb.status, "CANDIDATE_READY")
        self.assertEqual(bgr.status, "CANDIDATE_READY")
        self.assertTrue(np.array_equal(rgb.candidate_image, bgr.candidate_image[..., ::-1]))
        repeat = run_v3_white_balance_prototype(source)
        self.assertTrue(np.array_equal(rgb.candidate_image, repeat.candidate_image))
        self.assertEqual(rgb.to_record(), repeat.to_record())

        unsupported = run_v3_white_balance_prototype(source.astype(np.uint16) * 257)
        self.assertEqual(unsupported.status, "PROTECTION_BLOCKED")
        self.assertEqual(unsupported.blocker, "UNSUPPORTED_PROTOTYPE_BIT_DEPTH")
        self.assertIsNone(unsupported.candidate_image)

        with self.assertRaises(ValueError):
            run_v3_white_balance_prototype(source, hard_protection_mask=np.zeros((2, 2), dtype=bool))

    def test_rgba_alpha_mode_requires_validated_decoder_provenance(self) -> None:
        source, _ = _controlled_scene((1.18, 1.0, 0.82))
        for alpha_value in (240, 248, 254):
            with self.subTest(alpha=alpha_value):
                alpha = np.full(source.shape[:2], 255, dtype=np.uint8)
                alpha[:, 12:20] = alpha_value
                rgba = np.dstack((source, alpha))
                rgba[..., :3] = np.rint(
                    rgba[..., :3].astype(np.float64)
                    * (alpha[..., None].astype(np.float64) / 255.0)
                ).astype(np.uint8)

                premultiplied = run_v3_white_balance_prototype(
                    rgba,
                    alpha_mode="PREMULTIPLIED",
                )
                self.assertEqual(premultiplied.status, "INPUT_INELIGIBLE")
                self.assertEqual(
                    premultiplied.blocker,
                    "PREMULTIPLIED_ALPHA_UNSUPPORTED",
                )
                self.assertFalse(
                    premultiplied.diagnostics["global_wb_authorized"]
                )

        alpha = np.full(source.shape[:2], 255, dtype=np.uint8)
        rgba = np.dstack((source, alpha))
        unknown = run_v3_white_balance_prototype(rgba)
        self.assertEqual(unknown.status, "INPUT_INELIGIBLE")
        self.assertEqual(unknown.blocker, "RGBA_ALPHA_MODE_PROVENANCE_REQUIRED")
        claimed_straight = run_v3_white_balance_prototype(
            rgba,
            alpha_mode="STRAIGHT_VALIDATED",
        )
        self.assertEqual(claimed_straight.status, "INPUT_INELIGIBLE")
        self.assertEqual(
            claimed_straight.blocker,
            "RGBA_ALPHA_MODE_PROVENANCE_REQUIRED",
        )
        explicit_unknown = run_v3_white_balance_prototype(
            _validated_rgba_source(rgba),
            alpha_mode="UNKNOWN",
        )
        self.assertEqual(explicit_unknown.status, "INPUT_INELIGIBLE")
        self.assertEqual(
            explicit_unknown.blocker,
            "UNKNOWN_ALPHA_MODE_UNSUPPORTED",
        )

    def test_validated_straight_rgba_keeps_opaque_only_authority(self) -> None:
        source, _ = _controlled_scene((1.18, 1.0, 0.82))
        alpha = np.full(source.shape[:2], 255, dtype=np.uint8)
        alpha[:, 12:20] = 254
        managed = _validated_rgba_source(np.dstack((source, alpha)))

        result = run_v3_white_balance_prototype(managed)

        self.assertEqual(result.status, "CANDIDATE_READY")
        self.assertEqual(result.diagnostics["alpha_mode"], "STRAIGHT_VALIDATED")
        self.assertEqual(
            result.diagnostics["illuminant_evidence_pixel_count"],
            int((alpha == 255).sum()),
        )
        self.assertEqual(
            result.diagnostics["partial_alpha_illuminant_evidence_excluded_pixel_count"],
            int((alpha < 255).sum()),
        )
        self.assertTrue(result.diagnostics["global_wb_authorized"])

    def test_decoder_provenance_accepts_only_the_registered_instance(self) -> None:
        source, _ = _controlled_scene((1.18, 1.0, 0.82))
        alpha = np.full(source.shape[:2], 255, dtype=np.uint8)
        alpha[:, 12:20] = 254
        managed = _validated_rgba_source(np.dstack((source, alpha)))

        validation = validate_managed_color_source_provenance(managed)
        self.assertTrue(validation.valid)
        self.assertEqual(
            validation.provenance_version,
            MANAGED_COLOR_SOURCE_PROVENANCE_VERSION,
        )
        self.assertEqual(validation.decoder_origin_binding, "PASS")
        self.assertEqual(validation.pixel_object_identity, "PASS")
        self.assertEqual(validation.pixel_content_identity, "PASS")
        control = run_v3_white_balance_prototype(managed)
        self.assertEqual(control.status, "CANDIDATE_READY")
        self.assertEqual(control.diagnostics["provenance_validation"], "PASS")

        same_pixels = _unregistered_managed_source(managed)
        forged_metadata = _unregistered_managed_source(
            managed,
            pixels=managed.pixels.copy(),
            profile_status="CMM_CONVERTED_TO_SRGB",
        )
        copies = {
            "direct_constructor": _unregistered_managed_source(
                managed,
                pixels=managed.pixels.copy(),
            ),
            "same_pixel_object": same_pixels,
            "copy": copy.copy(managed),
            "deepcopy": copy.deepcopy(managed),
            "dataclasses_replace": replace(managed),
            "forged_metadata": forged_metadata,
        }
        for label, unregistered in copies.items():
            with self.subTest(label=label):
                self.assertIsNot(unregistered, managed)
                result = run_v3_white_balance_prototype(unregistered)
                self.assertEqual(result.status, "INPUT_INELIGIBLE")
                self.assertEqual(
                    result.blocker,
                    "MANAGED_SOURCE_UNREGISTERED_INSTANCE",
                )
                self.assertIsNone(result.candidate_image)
                self.assertFalse(result.diagnostics["global_wb_authorized"])

    def test_registered_source_pixel_and_contract_tampering_is_rejected(self) -> None:
        source, _ = _controlled_scene((1.18, 1.0, 0.82))
        alpha = np.full(source.shape[:2], 255, dtype=np.uint8)
        alpha[:, 12:20] = 254
        rgba = np.dstack((source, alpha))

        rgb_mutated = _validated_rgba_source(rgba)
        rgb_mutated.pixels[0, 0, 0] ^= 1
        rgb_result = run_v3_white_balance_prototype(rgb_mutated)
        self.assertEqual(rgb_result.status, "INPUT_INELIGIBLE")
        self.assertEqual(
            rgb_result.blocker,
            "MANAGED_SOURCE_PIXEL_IDENTITY_MISMATCH",
        )

        alpha_mutated = _validated_rgba_source(rgba)
        alpha_mutated.pixels[0, 0, 3] ^= 1
        alpha_result = run_v3_white_balance_prototype(alpha_mutated)
        self.assertEqual(alpha_result.status, "INPUT_INELIGIBLE")
        self.assertEqual(
            alpha_result.blocker,
            "MANAGED_SOURCE_PIXEL_IDENTITY_MISMATCH",
        )

        pixels_replaced = _validated_rgba_source(rgba)
        object.__setattr__(pixels_replaced, "pixels", pixels_replaced.pixels.copy())
        replacement_result = run_v3_white_balance_prototype(pixels_replaced)
        self.assertEqual(replacement_result.status, "INPUT_INELIGIBLE")
        self.assertEqual(
            replacement_result.blocker,
            "MANAGED_SOURCE_PIXEL_OBJECT_REPLACED",
        )

        contract_mutated = _validated_rgba_source(rgba)
        object.__setattr__(contract_mutated, "profile_status", "FORGED")
        contract_result = run_v3_white_balance_prototype(contract_mutated)
        self.assertEqual(contract_result.status, "INPUT_INELIGIBLE")
        self.assertEqual(
            contract_result.blocker,
            "MANAGED_SOURCE_CONTRACT_MISMATCH",
        )

        invalid_metadata = _validated_rgba_source(rgba)
        object.__setattr__(invalid_metadata, "output_icc_profile", None)
        invalid_metadata_result = run_v3_white_balance_prototype(invalid_metadata)
        self.assertEqual(invalid_metadata_result.status, "INPUT_INELIGIBLE")
        self.assertEqual(
            invalid_metadata_result.blocker,
            "MANAGED_SOURCE_CONTRACT_MISMATCH",
        )

    def test_premultiplied_mutation_and_explicit_modes_fail_closed(self) -> None:
        source, _ = _controlled_scene((1.18, 1.0, 0.82))
        for alpha_value in (240, 248, 254):
            with self.subTest(alpha=alpha_value):
                alpha = np.full(source.shape[:2], 255, dtype=np.uint8)
                alpha[:, 12:20] = alpha_value
                rgba = np.dstack((source, alpha))
                managed = _validated_rgba_source(rgba)
                managed.pixels[..., :3] = np.rint(
                    managed.pixels[..., :3].astype(np.float64)
                    * (alpha[..., None].astype(np.float64) / 255.0)
                ).astype(np.uint8)
                result = run_v3_white_balance_prototype(managed)
                self.assertEqual(result.status, "INPUT_INELIGIBLE")
                self.assertEqual(
                    result.blocker,
                    "MANAGED_SOURCE_PIXEL_IDENTITY_MISMATCH",
                )
                self.assertIsNone(result.candidate_image)

        alpha = np.full(source.shape[:2], 255, dtype=np.uint8)
        valid = _validated_rgba_source(np.dstack((source, alpha)))
        premultiplied = run_v3_white_balance_prototype(
            valid,
            alpha_mode="PREMULTIPLIED",
        )
        unknown = run_v3_white_balance_prototype(valid, alpha_mode="UNKNOWN")
        self.assertEqual(premultiplied.status, "INPUT_INELIGIBLE")
        self.assertEqual(
            premultiplied.blocker,
            "PREMULTIPLIED_ALPHA_UNSUPPORTED",
        )
        self.assertEqual(unknown.status, "INPUT_INELIGIBLE")
        self.assertEqual(unknown.blocker, "UNKNOWN_ALPHA_MODE_UNSUPPORTED")

    def test_stale_registry_entry_is_removed_with_decoder_source(self) -> None:
        source, _ = _controlled_scene((1.18, 1.0, 0.82))
        alpha = np.full(source.shape[:2], 255, dtype=np.uint8)
        managed = _validated_rgba_source(np.dstack((source, alpha)))
        source_id = id(managed)
        source_ref = weakref.ref(managed)
        self.assertIn(
            source_id,
            color_management._MANAGED_SOURCE_PROVENANCE_REGISTRY,
        )

        del managed
        gc.collect()

        self.assertIsNone(source_ref())
        self.assertNotIn(
            source_id,
            color_management._MANAGED_SOURCE_PROVENANCE_REGISTRY,
        )

    def test_atomic_snapshot_is_private_contiguous_read_only_and_hash_bound(self) -> None:
        managed, _ = _validated_controlled_rgba_source()

        acquisition = acquire_validated_managed_source_snapshot(managed)

        self.assertTrue(acquisition.valid)
        self.assertIsNone(acquisition.blocker)
        self.assertEqual(
            acquisition.snapshot_version,
            MANAGED_COLOR_SOURCE_ATOMIC_SNAPSHOT_VERSION,
        )
        self.assertTrue(acquisition.snapshot_private_memory)
        self.assertTrue(acquisition.snapshot_contiguous)
        self.assertFalse(acquisition.snapshot_writeable)
        self.assertFalse(np.shares_memory(acquisition.pixels, managed.pixels))
        self.assertEqual(
            acquisition.processing_snapshot_sha256,
            acquisition.decode_time_pixel_sha256,
        )
        with self.assertRaises(ValueError):
            acquisition.pixels[0, 0, 0] ^= np.uint8(1)

    def test_mutation_during_snapshot_acquisition_fails_closed(self) -> None:
        original_copy = color_management._copy_managed_source_pixels
        expected_blockers = {
            "rgb": "MANAGED_SOURCE_PIXEL_IDENTITY_MISMATCH",
            "alpha": "MANAGED_SOURCE_PIXEL_IDENTITY_MISMATCH",
            "replacement": "MANAGED_SOURCE_PIXEL_OBJECT_REPLACED",
        }

        for mode, expected_blocker in expected_blockers.items():
            with self.subTest(mode=mode):
                managed, _ = _validated_controlled_rgba_source()
                copy_entered = threading.Event()
                mutation_complete = threading.Event()
                worker_errors: list[str] = []

                def gated_copy(pixels: np.ndarray) -> np.ndarray:
                    copy_entered.set()
                    if not mutation_complete.wait(timeout=2):
                        worker_errors.append("mutation timeout")
                    return original_copy(pixels)

                def mutate_live_source() -> None:
                    if not copy_entered.wait(timeout=2):
                        worker_errors.append("copy timeout")
                    elif mode == "rgb":
                        managed.pixels[0, 0, 0] ^= np.uint8(1)
                    elif mode == "alpha":
                        managed.pixels[0, 0, 3] ^= np.uint8(1)
                    else:
                        object.__setattr__(managed, "pixels", managed.pixels.copy())
                    mutation_complete.set()

                worker = threading.Thread(target=mutate_live_source)
                worker.start()
                with patch.object(
                    color_management,
                    "_copy_managed_source_pixels",
                    side_effect=gated_copy,
                ):
                    result = run_v3_white_balance_prototype(managed)
                worker.join(timeout=2)

                self.assertFalse(worker.is_alive())
                self.assertEqual(worker_errors, [])
                self.assertEqual(result.status, "INPUT_INELIGIBLE")
                self.assertEqual(result.blocker, expected_blocker)
                self.assertIsNone(result.candidate_image)
                self.assertFalse(result.diagnostics["global_wb_authorized"])

    def test_live_mutation_after_snapshot_cannot_change_processing(self) -> None:
        control_source, _ = _validated_controlled_rgba_source()
        control = run_v3_white_balance_prototype(control_source)
        self.assertEqual(control.status, "CANDIDATE_READY")

        expected_post_blockers = {
            "rgb": "MANAGED_SOURCE_PIXEL_IDENTITY_MISMATCH",
            "alpha": "MANAGED_SOURCE_PIXEL_IDENTITY_MISMATCH",
            "replacement": "MANAGED_SOURCE_PIXEL_OBJECT_REPLACED",
        }
        original_acquire = acquire_validated_managed_source_snapshot
        for mode, expected_post_blocker in expected_post_blockers.items():
            with self.subTest(mode=mode):
                managed, _ = _validated_controlled_rgba_source()

                def acquire_then_mutate(source: ManagedColorSource):
                    acquisition = original_acquire(source)
                    self.assertTrue(acquisition.valid)
                    if mode == "rgb":
                        source.pixels[0, 0, 0] ^= np.uint8(1)
                    elif mode == "alpha":
                        source.pixels[0, 0, 3] ^= np.uint8(1)
                    else:
                        object.__setattr__(source, "pixels", source.pixels.copy())
                    return acquisition

                with patch.object(
                    white_balance_prototype,
                    "acquire_validated_managed_source_snapshot",
                    side_effect=acquire_then_mutate,
                ):
                    result = run_v3_white_balance_prototype(managed)

                self.assertEqual(result.status, "CANDIDATE_READY")
                self.assertTrue(
                    np.array_equal(result.candidate_image, control.candidate_image)
                )
                self.assertEqual(result.to_record(), control.to_record())
                post_validation = validate_managed_color_source_provenance(managed)
                self.assertFalse(post_validation.valid)
                self.assertEqual(post_validation.blocker, expected_post_blocker)

    def test_evidence_requires_decoder_snapshot_source_hash_consistency(self) -> None:
        managed, _ = _validated_controlled_rgba_source()
        result = run_v3_white_balance_prototype(managed)
        record = result.to_record()
        identity = record["evidence_identity"]

        self.assertEqual(record["record_status"], "VALID")
        self.assertEqual(
            identity["decoder_pixel_sha256"],
            identity["processing_snapshot_sha256"],
        )
        self.assertEqual(
            identity["processing_snapshot_sha256"],
            identity["source_evidence_sha256"],
        )
        valid, blocker = validate_v3_evidence_record(
            record,
            source_image=managed.pixels,
            candidate_image=result.candidate_image,
            hard_protection_mask=None,
        )
        self.assertTrue(valid)
        self.assertIsNone(blocker)

        for key in (
            "decoder_pixel_sha256",
            "processing_snapshot_sha256",
            "source_evidence_sha256",
        ):
            with self.subTest(key=key):
                tampered = copy.deepcopy(record)
                current = tampered["evidence_identity"][key]
                replacement_prefix = "0" if current[0] != "0" else "1"
                tampered["evidence_identity"][key] = replacement_prefix + current[1:]
                tampered["record_identity_sha256"] = (
                    white_balance_prototype._record_identity_sha256(tampered)
                )
                valid, blocker = validate_v3_evidence_record(
                    tampered,
                    source_image=managed.pixels,
                    candidate_image=result.candidate_image,
                    hard_protection_mask=None,
                )
                self.assertFalse(valid)
                self.assertEqual(
                    blocker,
                    "EVIDENCE_PROVENANCE_HASH_CONSISTENCY_MISMATCH",
                )

        tampered_identity = copy.deepcopy(result.evidence_identity)
        current = tampered_identity["processing_snapshot_sha256"]
        tampered_identity["processing_snapshot_sha256"] = (
            ("0" if current[0] != "0" else "1") + current[1:]
        )
        invalid_record = replace(
            result,
            evidence_identity=tampered_identity,
        ).to_record()
        self.assertEqual(invalid_record["record_status"], "INVALID")
        self.assertEqual(
            invalid_record["record_blocker"],
            "EVIDENCE_PROVENANCE_HASH_CONSISTENCY_MISMATCH",
        )

    def test_hard_protection_mask_is_snapshotted_before_processing(self) -> None:
        source, _ = _controlled_scene((1.18, 1.0, 0.82))
        zero_mask = np.zeros(source.shape[:2], dtype=bool)
        control = run_v3_white_balance_prototype(
            source,
            hard_protection_mask=zero_mask.copy(),
        )
        original_spatial_coverage = white_balance_prototype._spatial_coverage

        def mutate_caller_mask(mask: np.ndarray):
            zero_mask[0, 0] = True
            return original_spatial_coverage(mask)

        with patch.object(
            white_balance_prototype,
            "_spatial_coverage",
            side_effect=mutate_caller_mask,
        ):
            result = run_v3_white_balance_prototype(
                source,
                hard_protection_mask=zero_mask,
            )

        self.assertTrue(zero_mask[0, 0])
        self.assertEqual(result.status, control.status)
        self.assertTrue(np.array_equal(result.candidate_image, control.candidate_image))
        self.assertEqual(result.to_record(), control.to_record())

    def test_evidence_identity_binds_source_candidate_alpha_and_mask(self) -> None:
        source_a, _ = _controlled_scene((1.18, 1.0, 0.82))
        source_b = source_a.copy()
        for row in range(4):
            for column in range(4):
                row_start, row_end = row * 24, (row + 1) * 24
                column_start, column_end = column * 32, (column + 1) * 32
                source_b[row_start:row_end, column_start:column_end] = source_b[
                    row_start:row_end,
                    column_start:column_end,
                ][::-1, ::-1]

        result_a = run_v3_white_balance_prototype(source_a)
        result_b = run_v3_white_balance_prototype(source_b)
        record_a = result_a.to_record()
        record_b = result_b.to_record()
        self.assertEqual(record_a["record_status"], "VALID")
        self.assertEqual(
            record_a["evidence_identity_binding_version"],
            EVIDENCE_IDENTITY_BINDING_VERSION,
        )
        self.assertNotEqual(
            record_a["evidence_identity"]["source_sha256"],
            record_b["evidence_identity"]["source_sha256"],
        )
        self.assertNotEqual(
            record_a["evidence_identity"]["candidate_sha256"],
            record_b["evidence_identity"]["candidate_sha256"],
        )
        self.assertNotEqual(
            record_a["record_identity_sha256"],
            record_b["record_identity_sha256"],
        )
        self.assertNotEqual(record_a, record_b)

        valid, blocker = validate_v3_evidence_record(
            record_a,
            source_image=source_a,
            candidate_image=result_a.candidate_image,
            hard_protection_mask=None,
        )
        self.assertTrue(valid)
        self.assertIsNone(blocker)

        source_tampered = source_a.copy()
        source_tampered[0, 0, 0] ^= 1
        valid, blocker = validate_v3_evidence_record(
            record_a,
            source_image=source_tampered,
            candidate_image=result_a.candidate_image,
            hard_protection_mask=None,
        )
        self.assertFalse(valid)
        self.assertEqual(blocker, "EVIDENCE_SOURCE_BINDING_MISMATCH")

        candidate_tampered = result_a.candidate_image.copy()
        candidate_tampered[0, 0, 0] ^= 1
        valid, blocker = validate_v3_evidence_record(
            record_a,
            source_image=source_a,
            candidate_image=candidate_tampered,
            hard_protection_mask=None,
        )
        self.assertFalse(valid)
        self.assertEqual(blocker, "EVIDENCE_CANDIDATE_BINDING_MISMATCH")

        alpha = np.full(source_a.shape[:2], 255, dtype=np.uint8)
        alpha[:, 12:20] = 254
        rgba = np.dstack((source_a, alpha))
        managed = _validated_rgba_source(rgba)
        rgba_result = run_v3_white_balance_prototype(managed)
        rgba_record = rgba_result.to_record()
        alpha_tampered = managed.pixels.copy()
        alpha_tampered[0, 0, 3] ^= 1
        alpha_tampered_result = run_v3_white_balance_prototype(
            _validated_rgba_source(alpha_tampered)
        )
        self.assertNotEqual(
            rgba_record["evidence_identity"]["alpha_sha256"],
            alpha_tampered_result.to_record()["evidence_identity"]["alpha_sha256"],
        )
        valid, blocker = validate_v3_evidence_record(
            rgba_record,
            source_image=alpha_tampered,
            candidate_image=rgba_result.candidate_image,
            hard_protection_mask=None,
        )
        self.assertFalse(valid)
        self.assertEqual(blocker, "EVIDENCE_SOURCE_BINDING_MISMATCH")

        zero_mask = np.zeros(source_a.shape[:2], dtype=bool)
        none_mask_record = result_a.to_record()
        zero_mask_result = run_v3_white_balance_prototype(
            source_a,
            hard_protection_mask=zero_mask,
        )
        zero_mask_record = zero_mask_result.to_record()
        self.assertEqual(
            none_mask_record["evidence_identity"]["protected_mask_state"],
            "NONE",
        )
        self.assertIsNone(
            none_mask_record["evidence_identity"]["protected_mask_sha256"]
        )
        self.assertEqual(
            zero_mask_record["evidence_identity"]["protected_mask_state"],
            "PRESENT",
        )
        self.assertIsNotNone(
            zero_mask_record["evidence_identity"]["protected_mask_sha256"]
        )
        self.assertNotEqual(
            none_mask_record["record_identity_sha256"],
            zero_mask_record["record_identity_sha256"],
        )
        mask_tampered = zero_mask.copy()
        mask_tampered[0, 0] = True
        mask_tampered_result = run_v3_white_balance_prototype(
            source_a,
            hard_protection_mask=mask_tampered,
        )
        self.assertNotEqual(
            zero_mask_record["evidence_identity"]["protected_mask_sha256"],
            mask_tampered_result.to_record()["evidence_identity"]["protected_mask_sha256"],
        )
        valid, blocker = validate_v3_evidence_record(
            zero_mask_record,
            source_image=source_a,
            candidate_image=zero_mask_result.candidate_image,
            hard_protection_mask=mask_tampered,
        )
        self.assertFalse(valid)
        self.assertEqual(blocker, "EVIDENCE_MASK_BINDING_MISMATCH")

    def test_evidence_record_missing_required_bindings_is_rejected(self) -> None:
        source, _ = _controlled_scene((1.18, 1.0, 0.82))
        result = run_v3_white_balance_prototype(source)
        record = result.to_record()

        missing_source = copy.deepcopy(record)
        missing_source["evidence_identity"]["source_sha256"] = None
        valid, blocker = validate_v3_evidence_record(
            missing_source,
            source_image=source,
            candidate_image=result.candidate_image,
            hard_protection_mask=None,
        )
        self.assertFalse(valid)
        self.assertEqual(blocker, "EVIDENCE_RECORD_MISSING_SOURCE_BINDING")

        missing_candidate = copy.deepcopy(record)
        missing_candidate["evidence_identity"]["candidate_sha256"] = None
        valid, blocker = validate_v3_evidence_record(
            missing_candidate,
            source_image=source,
            candidate_image=result.candidate_image,
            hard_protection_mask=None,
        )
        self.assertFalse(valid)
        self.assertEqual(blocker, "EVIDENCE_RECORD_MISSING_CANDIDATE_BINDING")

    def test_prototype_is_not_part_of_the_formal_color_surface(self) -> None:
        self.assertNotIn("run_v3_white_balance_prototype", color_correction.__all__)
        self.assertNotIn("V3_WHITE_BALANCE_PROTOTYPE_VERSION", color_correction.__all__)
        source, _ = _controlled_scene((1.18, 1.0, 0.82))
        record = run_v3_white_balance_prototype(source).to_record()
        self.assertEqual(record["engine_version"], V3_WHITE_BALANCE_PROTOTYPE_VERSION)
        self.assertNotIn("candidate_image", record)


if __name__ == "__main__":
    unittest.main()
