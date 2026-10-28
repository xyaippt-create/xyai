"""Focused core tests; no API, output registry, or acceptance authority changes."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image

from engine.color_correction.color_management import (
    encode_color_managed_candidate, load_color_managed_source,
    srgb_profile_bytes, verify_color_managed_output,
)
from engine.color_correction.executors.basic_correction import execute_basic_correction
from engine.color_correction.objective_diagnosis import build_objective_diagnosis
from engine.color_correction.parameters import CorrectionParameters, PARAMETER_SPECS
from engine.color_correction.reference_matching import (
    CALIBRATION_LIMITS, ColorDifference, ColorSource, IDENTITY_CAPS, LIMITS, POLICY, SKIN_CAPS,
    STRONG_COLOR_CAPS, ReferenceColorTarget, TargetColorProfile,
    compare_profiles, decide_reference_matching,
    load_reference_color_target, load_target_color_profile,
)
from engine.color_correction.usability_decision import analyze_color_usability


def profile(role=TargetColorProfile, **changes):
    # Pure decision-unit fixture, not a special production image path.
    ramp = np.tile(np.linspace(30, 220, 96).astype("uint8"), (96, 1))
    facts = analyze_color_usability(np.stack((ramp, ramp, ramp), -1), person_regions=())
    d = build_objective_diagnosis(facts).to_dict()
    d["EXPOSURE"]["evidence"].update(
        mean_luminance=0.45, luminance_p05=0.12, luminance_p50=0.45, luminance_p95=0.78)
    d["EXPOSURE"]["state"] = "ACCEPTABLE"
    d["SCENE_RISK"]["evidence"]["scene_intent"] = "GENERAL"
    d["SKIN_RISK"]["state"] = "LOW"
    d["SKIN_RISK"]["evidence"]["person_present"] = False
    d["CLIPPING"]["state"] = "ACCEPTABLE"
    d["CLIPPING"]["evidence"].update(highlight_clip_ratio=0, shadow_clip_ratio=0)
    d["NEUTRAL_COLOR_EVIDENCE"]["state"] = "SUFFICIENT"
    d["WHITE_BALANCE"]["evidence"].update(neutral_lab_a=0, neutral_lab_b=0)
    d["SATURATION"]["evidence"].update(saturation_p50=0.25, saturation_p90=0.50)
    d["DYNAMIC_RANGE"]["evidence"]["p95_minus_p05"] = 0.66
    distribution = {"family_coverage": dict.fromkeys(("RED", "BLUE", "GREEN"), 0.0),
                    "strong_color_ratio": 0.0, "dominant_color_risk": "LOW",
                    "skin_like_pixel_ratio": 0.0}
    for path, value in changes.items():
        keys = path.split("__")
        destination = d
        for key in keys[:-1]:
            destination = destination[key]
        destination[keys[-1]] = value
    source = ColorSource("unit-profile-not-a-file", "0"*64, "1"*64,
                         d["source_fingerprint"], "ASSUMED_SRGB", "PNG", None)
    return role(source, json.dumps(d), json.dumps(distribution))


class ReferenceDecisionTests(unittest.TestCase):
    def test_profile_and_difference_contract(self):
        target, ref = profile(), profile(ReferenceColorTarget)
        record = ref.to_record()
        for suffix in ("SOURCE", "LUMINANCE_PROFILE", "WHITE_BALANCE", "TEMPERATURE_STATE",
                       "TINT_STATE", "CONTRAST_PROFILE", "SATURATION_PROFILE", "VIBRANCE_PROFILE",
                       "HIGHLIGHT_PROFILE", "SHADOW_PROFILE", "NEUTRAL_EVIDENCE",
                       "COLOR_CAST", "CONFIDENCE"):
            self.assertIn("REFERENCE_" + suffix, record)
        difference = ColorDifference.between(target, ref).to_record()
        self.assertEqual(set(difference), set(PARAMETER_SPECS))
        self.assertTrue(all(d["RAW_DELTA"] == 0 for d in difference.values()))
        with self.assertRaises(TypeError):
            ColorDifference.between(ref, target)
        # The returned diagnostics cannot mutate the stored observations.
        target.diagnosis["EXPOSURE"]["state"] = "CORRUPTED"
        self.assertEqual(target.diagnosis["EXPOSURE"]["state"], "ACCEPTABLE")

    def test_all_nine_directional_mappings_and_evidence(self):
        for sign in (1, -1):
            cases = {
                "temperature": {"WHITE_BALANCE__evidence__neutral_lab_b": sign * 4},
                "tint": {"WHITE_BALANCE__evidence__neutral_lab_a": sign * 4},
                "brightness": {"EXPOSURE__evidence__luminance_p50": .45 + sign * .08},
                "contrast": {"EXPOSURE__evidence__luminance_p95": .78 + sign * .08},
                "saturation": {"SATURATION__evidence__saturation_p90": .5 + sign * .10},
                "vibrance": {"SATURATION__evidence__saturation_p50": .25 + sign * .08},
                "highlights": {"EXPOSURE__evidence__luminance_p95": .78 + sign * .08},
                "shadows": {"EXPOSURE__evidence__luminance_p05": .12 + sign * .06},
                "exposure": {"EXPOSURE__evidence__mean_luminance": .45 + sign * .10},
            }
            for parameter, values in cases.items():
                with self.subTest(parameter=parameter, sign=sign):
                    target = profile(**({"EXPOSURE__state": "UNDEREXPOSED" if sign > 0 else "OVEREXPOSED"}
                                       if parameter == "exposure" else {}))
                    decision = decide_reference_matching(target, profile(ReferenceColorTarget, **values))
                    self.assertGreater(getattr(decision.parameters, parameter) * sign, 0)
                    item = decision.to_record()["DIMENSIONS"][parameter]
                    self.assertEqual(set(item), {"SOURCE_VALUE", "REFERENCE_VALUE", "RAW_DELTA",
                                                "ALLOWED_DELTA", "FINAL_PARAMETER", "CONFIDENCE",
                                                "UNIT", "LIMIT_REASON", "RISK_AWARE_MATCH_BUDGET",
                                                "LIMIT_CONTRIBUTION_TRACE"})
                    self.assertLessEqual(abs(item["ALLOWED_DELTA"]), abs(item["RAW_DELTA"]))

    def test_neutral_strength_serialization_and_determinism(self):
        target = profile()
        reference = profile(ReferenceColorTarget, WHITE_BALANCE__evidence__neutral_lab_b=5)
        self.assertTrue(decide_reference_matching(target, profile(ReferenceColorTarget)).parameters.is_neutral)
        self.assertTrue(decide_reference_matching(target, reference, match_strength=0).parameters.is_neutral)
        low = decide_reference_matching(target, reference, match_strength=.2)
        high = decide_reference_matching(target, reference, match_strength=.4)
        self.assertAlmostEqual(high.parameters.temperature, 2 * low.parameters.temperature)
        self.assertEqual(high.to_record(), decide_reference_matching(target, reference, match_strength=.4).to_record())
        record = json.loads(json.dumps(high.to_record(), allow_nan=False))
        self.assertEqual(high.parameters, CorrectionParameters.from_record(record["CORRECTION_PARAMETERS"]))
        self.assertEqual(decide_reference_matching(target, reference, match_strength=3).match_strength, LIMITS.maximum_strength)
        for bad in (True, "1", None, float("nan"), float("inf")):
            with self.assertRaises((ValueError, TypeError)):
                decide_reference_matching(target, reference, match_strength=bad)

    def test_three_separate_comparabilities_and_no_night_exposure_copy(self):
        target = profile()
        ref = profile(ReferenceColorTarget, EXPOSURE__evidence__luminance_p50=.03,
                      SCENE_RISK__evidence__scene_intent="LEGITIMATE_DARK",
                      WHITE_BALANCE__evidence__neutral_lab_b=4)
        decision = decide_reference_matching(target, ref)
        self.assertEqual(decision.comparability.luminance, "LOW")
        self.assertEqual(decision.comparability.color, "HIGH")
        self.assertEqual(decision.status, "COLOR_ONLY_MATCH")
        for name in ("exposure", "brightness", "contrast", "highlights", "shadows"):
            self.assertEqual(getattr(decision.parameters, name), 0)
        self.assertGreater(decision.parameters.temperature, 0)

    def test_no_duplicate_exposure_brightness_and_target_clipping(self):
        target = profile(EXPOSURE__state="UNDEREXPOSED")
        ref = profile(ReferenceColorTarget, EXPOSURE__evidence__mean_luminance=.55,
                      EXPOSURE__evidence__luminance_p50=.55)
        decision = decide_reference_matching(target, ref)
        self.assertGreater(decision.parameters.exposure, 0)
        self.assertEqual(decision.parameters.brightness, 0)
        clipped = profile(CLIPPING__evidence__highlight_clip_ratio=.1)
        self.assertEqual(decide_reference_matching(clipped, ref).parameters.brightness, 0)
        dark = profile(CLIPPING__evidence__shadow_clip_ratio=.1)
        ref_dark = profile(ReferenceColorTarget, EXPOSURE__evidence__luminance_p50=.35)
        self.assertEqual(decide_reference_matching(dark, ref_dark).parameters.brightness, 0)

    def test_skin_is_limited_not_blanket_rejected_and_strong_color_budget(self):
        ref = profile(ReferenceColorTarget, WHITE_BALANCE__evidence__neutral_lab_b=10,
                      WHITE_BALANCE__evidence__neutral_lab_a=-10,
                      SATURATION__evidence__saturation_p90=.90,
                      SATURATION__evidence__saturation_p50=.65)
        skin = profile(SKIN_RISK__state="HIGH", SKIN_RISK__evidence__person_present=True)
        decision = decide_reference_matching(skin, ref)
        self.assertNotEqual(decision.status, "INSUFFICIENT_EVIDENCE")
        self.assertGreater(decision.parameters.temperature, 0)
        self.assertLess(decision.parameters.tint, 0)
        for name, value in decision.parameters.values().items():
            self.assertLessEqual(abs(value), SKIN_CAPS[name] * decision.match_strength)
        brand = profile()
        dist = brand.distribution
        dist["strong_color_ratio"] = .6
        brand = replace(brand, distribution_json=json.dumps(dist))
        decision = decide_reference_matching(brand, ref)
        for name, cap in STRONG_COLOR_CAPS.items():
            self.assertLessEqual(abs(getattr(decision.parameters, name)), cap * decision.match_strength)
        # Even an unrecognized/low-chroma product has a bounded identity budget.
        plain = decide_reference_matching(profile(), ref)
        for name, cap in IDENTITY_CAPS.items():
            self.assertLessEqual(abs(getattr(plain.parameters, name)), cap * plain.match_strength)

    def test_bad_reference_and_bad_target_fail_closed(self):
        for changes in (
            {"CLIPPING__state": "SEVERE"},
            {"DYNAMIC_RANGE__evidence__p95_minus_p05": .01},
        ):
            for is_reference in (True, False):
                target = profile(**({} if is_reference else changes))
                ref = profile(ReferenceColorTarget, **(changes if is_reference else {}))
                decision = decide_reference_matching(target, ref)
                self.assertEqual(decision.status, "INSUFFICIENT_EVIDENCE")
                self.assertTrue(decision.parameters.is_neutral)
                self.assertIn("REFERENCE_INSUFFICIENT_EVIDENCE", decision.reasons)

    def test_low_color_evidence_disables_white_balance_only(self):
        ref = profile(ReferenceColorTarget, NEUTRAL_COLOR_EVIDENCE__state="INSUFFICIENT",
                      WHITE_BALANCE__evidence__neutral_lab_b=5,
                      SATURATION__evidence__saturation_p90=.65)
        decision = decide_reference_matching(profile(), ref)
        self.assertEqual(decision.parameters.temperature, 0)
        self.assertGreater(decision.parameters.saturation, 0)

    def test_mixed_neutral_does_not_erase_independent_saturation_evidence(self):
        ref = profile(ReferenceColorTarget, NEUTRAL_COLOR_EVIDENCE__state="MIXED_FIELD",
                      SATURATION__evidence__saturation_p90=.65)
        decision = decide_reference_matching(profile(), ref)
        self.assertEqual(decision.parameters.temperature, 0)
        self.assertGreater(decision.parameters.saturation, 0)
        self.assertEqual(decision.status, "LIMITED_MATCH")
        unstable = replace(ref, diagnosis_json=ref.diagnosis_json.replace('"MIXED_FIELD"', '"UNSTABLE"'))
        limited = decide_reference_matching(profile(), unstable)
        self.assertEqual(limited.parameters.temperature, 0)
        self.assertGreater(limited.parameters.saturation, 0)

    def test_sub_unit_controls_are_suppressed_not_amplified(self):
        ref = profile(ReferenceColorTarget, EXPOSURE__evidence__luminance_p95=.80)
        decision = decide_reference_matching(profile(), ref)
        self.assertEqual(decision.parameters.highlights, 0)
        self.assertIn("BELOW_RELIABLE_COMBINED_CONTROL_BUDGET",
                      decision.to_record()["DIMENSIONS"]["highlights"]["LIMIT_REASON"])

    def test_monochrome_is_relative_to_observed_strong_color_area(self):
        ref = profile(ReferenceColorTarget, NEUTRAL_COLOR_EVIDENCE__state="INSUFFICIENT",
                      NEUTRAL_COLOR_EVIDENCE__evidence__pixel_ratio=0)
        distribution = ref.distribution
        distribution["family_coverage"]["RED"] = .8
        distribution["strong_color_ratio"] = .8
        ref = replace(ref, distribution_json=json.dumps(distribution))
        decision = decide_reference_matching(profile(), ref)
        self.assertEqual(decision.status, "INSUFFICIENT_EVIDENCE")
        self.assertIn("REFERENCE_EXTREME_MONOCHROME", decision.reasons)

    def test_opposing_saturation_and_vibrance_do_not_cancel_each_other(self):
        ref = profile(ReferenceColorTarget, SATURATION__evidence__saturation_p90=.4,
                      SATURATION__evidence__saturation_p50=.3)
        decision = decide_reference_matching(profile(), ref)
        self.assertLess(decision.parameters.saturation, 0)
        self.assertEqual(decision.parameters.vibrance, 0)
        self.assertIn("NO_OPPOSING_UNIFORM_AND_SELECTIVE_CHROMA",
                      decision.to_record()["DIMENSIONS"]["vibrance"]["LIMIT_REASON"])

    def test_invalid_profile_statistics_and_source_identity_are_rejected(self):
        original = profile()
        with self.assertRaises(ValueError):
            replace(original, source=replace(original.source, source_fingerprint="wrong"))
        for bad in (float("nan"), float("inf")):
            d = original.diagnosis
            d["SATURATION"]["evidence"]["saturation_p90"] = bad
            with self.assertRaises(ValueError):
                replace(original, diagnosis_json=json.dumps(d))


def coherent_axis_profile(role, a, **changes):
    p = profile(role, DIAGNOSIS_CONFIDENCE=.9, NEUTRAL_COLOR_EVIDENCE__confidence=.9,
                NEUTRAL_COLOR_EVIDENCE__state="UNSTABLE",
                WHITE_BALANCE__evidence__neutral_lab_a=a, **changes)
    distribution = p.distribution
    distribution["neutral_axis_evidence"] = {
        "quantization": {"feature_ranges": {
            "neutral_ratio": [.3, .4], "neutral_a": [a-.5, a+.5], "neutral_b": [-.5, .5]}},
        "spatial": {"strong_color_mixed": False,
                    "cells": [{"a": a + i/10} for i in range(9)]},
    }
    return replace(p, distribution_json=json.dumps(distribution))


class RiskAwareBudgetTests(unittest.TestCase):
    def test_coherent_tint_axis_without_rewriting_unstable_diagnosis(self):
        for sign in (1, -1):
            target = coherent_axis_profile(TargetColorProfile, -sign * 2)
            reference = coherent_axis_profile(ReferenceColorTarget, sign * 4)
            before = (target.diagnosis_json, reference.diagnosis_json)
            decision = decide_reference_matching(target, reference)
            self.assertGreater(decision.parameters.tint * sign, 0)
            self.assertLessEqual(abs(decision.parameters.tint), IDENTITY_CAPS["tint"])
            self.assertEqual(decision.comparability.color, "LOW")
            self.assertEqual(decision.status, "LIMITED_MATCH")
            item = decision.to_record()["DIMENSIONS"]["tint"]
            self.assertEqual(item["RISK_AWARE_MATCH_BUDGET"]["mode"], "COHERENT_TINT_AXIS")
            self.assertEqual(before, (target.diagnosis_json, reference.diagnosis_json))
            self.assertGreater(item["CONFIDENCE"], 0)
            self.assertLess(item["CONFIDENCE"], .9)

    def test_tint_axis_rejects_unproven_and_mixed_evidence(self):
        target = coherent_axis_profile(TargetColorProfile, -2)
        reference = coherent_axis_profile(ReferenceColorTarget, 4)
        for fault in ("missing", "overlap", "cross_zero", "spatial_variation",
                      "strong_mixed", "few_cells", "few_neutrals"):
            with self.subTest(fault=fault):
                dist = reference.distribution
                f = dist["neutral_axis_evidence"]
                if fault == "missing":
                    del dist["neutral_axis_evidence"]
                elif fault in {"overlap", "cross_zero"}:
                    f["quantization"]["feature_ranges"]["neutral_a"] = [-3, 5]
                elif fault == "spatial_variation":
                    f["spatial"]["cells"][0]["a"] = -5
                elif fault == "strong_mixed":
                    f["spatial"]["strong_color_mixed"] = True
                elif fault == "few_cells":
                    f["spatial"]["cells"] = f["spatial"]["cells"][:2]
                else:
                    f["quantization"]["feature_ranges"]["neutral_ratio"] = [.01, .02]
                bad = replace(reference, distribution_json=json.dumps(dist))
                self.assertEqual(decide_reference_matching(target, bad).parameters.tint, 0)
        for changes in ({"CLIPPING__state": "ELEVATED"}, {"SKIN_RISK__state": "HIGH"},
                        {"SKIN_RISK__evidence__local_person_color_risk": True},
                        {"DIAGNOSIS_CONFIDENCE": .4}):
            d = reference.diagnosis
            for path, value in changes.items():
                keys, destination = path.split("__"), d
                for key in keys[:-1]:
                    destination = destination[key]
                destination[keys[-1]] = value
            self.assertEqual(decide_reference_matching(
                target, replace(reference, diagnosis_json=json.dumps(d))).parameters.tint, 0)

    def test_temperature_budget_is_conditional_and_still_skin_capped(self):
        args = {"DIAGNOSIS_CONFIDENCE": .9, "SKIN_RISK__state": "MEDIUM",
                "SKIN_RISK__evidence__person_present": True,
                "SCENE_RISK__evidence__scene_intent": "PERSON_SCENE"}
        target = profile(**args, WHITE_BALANCE__state="COOL",
                         WHITE_BALANCE__evidence__neutral_lab_b=-8)
        ref = profile(ReferenceColorTarget, **args, WHITE_BALANCE__state="WARM",
                      WHITE_BALANCE__evidence__neutral_lab_b=8)
        dist = target.distribution
        dist.update(strong_color_ratio=.3, dominant_color_risk="MEDIUM")
        target = replace(target, distribution_json=json.dumps(dist))
        decision = decide_reference_matching(target, ref)
        self.assertGreater(decision.parameters.temperature, STRONG_COLOR_CAPS["temperature"] * LIMITS.default_strength)
        self.assertLessEqual(decision.parameters.temperature, SKIN_CAPS["temperature"])
        d = target.diagnosis
        d["WHITE_BALANCE"]["state"] = "NEUTRAL"
        d["WHITE_BALANCE"]["evidence"]["neutral_lab_b"] = 0
        unchanged_budget = decide_reference_matching(replace(target, diagnosis_json=json.dumps(d)), ref)
        self.assertLessEqual(unchanged_budget.parameters.temperature,
                             STRONG_COLOR_CAPS["temperature"] * LIMITS.default_strength)
        for strength in (0, .1, .3, LIMITS.maximum_strength):
            result = decide_reference_matching(target, ref, match_strength=strength)
            self.assertLessEqual(abs(result.parameters.temperature), SKIN_CAPS["temperature"])
            if not strength:
                self.assertTrue(result.parameters.is_neutral)
        dist["dominant_color_risk"] = "HIGH"
        high_risk = decide_reference_matching(replace(target, distribution_json=json.dumps(dist)), ref)
        self.assertLessEqual(high_risk.parameters.temperature,
                             STRONG_COLOR_CAPS["temperature"] * LIMITS.default_strength)

    def test_low_saturation_prefers_vibrance_and_reduction_does_not_fight_it(self):
        low = profile(DIAGNOSIS_CONFIDENCE=.9, SATURATION__evidence__saturation_p50=.12,
                      SATURATION__evidence__saturation_p90=.4)
        high = profile(ReferenceColorTarget, DIAGNOSIS_CONFIDENCE=.9,
                       SATURATION__evidence__saturation_p50=.28,
                       SATURATION__evidence__saturation_p90=.8)
        positive = decide_reference_matching(low, high)
        self.assertGreater(positive.parameters.vibrance, positive.parameters.saturation)
        self.assertGreater(positive.parameters.saturation, 0)
        negative = decide_reference_matching(
            TargetColorProfile(high.source, high.diagnosis_json, high.distribution_json),
            ReferenceColorTarget(low.source, low.diagnosis_json, low.distribution_json))
        self.assertLess(negative.parameters.saturation, 0)
        self.assertLessEqual(negative.parameters.vibrance, 0)

    def test_contrast_response_and_objective_exposure_have_separate_budgets(self):
        target = profile(DIAGNOSIS_CONFIDENCE=.9)
        reference = profile(ReferenceColorTarget, DIAGNOSIS_CONFIDENCE=.9,
                            EXPOSURE__evidence__luminance_p50=.49,
                            EXPOSURE__evidence__luminance_p95=.84)
        decision = decide_reference_matching(target, reference)
        self.assertGreater(decision.parameters.brightness, 0)
        self.assertGreater(decision.parameters.contrast, .06 * POLICY["contrast"][0] * LIMITS.default_strength)
        self.assertLessEqual(decision.parameters.contrast, POLICY["contrast"][1])
        dark = profile(DIAGNOSIS_CONFIDENCE=.9, EXPOSURE__state="UNDEREXPOSED",
                       EXPOSURE__evidence__luminance_p95=.70)
        healthy = profile(ReferenceColorTarget, DIAGNOSIS_CONFIDENCE=.9,
                          EXPOSURE__evidence__luminance_p50=.70,
                          EXPOSURE__evidence__mean_luminance=.60)
        decision = decide_reference_matching(dark, healthy)
        self.assertEqual(decision.comparability.luminance, "MEDIUM")
        self.assertEqual(decision.parameters.brightness, 0)
        self.assertGreater(decision.parameters.exposure, .1)
        d = dark.diagnosis
        d["SCENE_RISK"]["evidence"]["scene_intent"] = "LEGITIMATE_DARK"
        self.assertEqual(decide_reference_matching(
            replace(dark, diagnosis_json=json.dumps(d)), healthy).parameters.exposure, 0)

    def test_every_limit_trace_is_continuous_serializable_and_ends_at_parameters(self):
        target = coherent_axis_profile(TargetColorProfile, -2)
        reference = coherent_axis_profile(ReferenceColorTarget, 4)
        decision = decide_reference_matching(target, reference)
        record = json.loads(json.dumps(decision.to_record(), allow_nan=False))
        self.assertEqual(record["MATCH_BUDGET_MODEL"], "hdde.reference-risk-budget.v2")
        for name, item in record["DIMENSIONS"].items():
            trace = item["LIMIT_CONTRIBUTION_TRACE"]
            self.assertEqual(trace[0]["STEP"], "RAW_DELTA")
            for before, after in zip(trace, trace[1:]):
                self.assertEqual(before["OUTPUT_PARAMETER"], after["INPUT_PARAMETER"])
            self.assertEqual(trace[-1]["STEP"], "FINAL_ALLOWED_DELTA")
            self.assertEqual(trace[-1]["OUTPUT_PARAMETER"], record["CORRECTION_PARAMETERS"]["values"][name])
            self.assertEqual(trace[-1]["OUTPUT_ALLOWED_DELTA"], item["ALLOWED_DELTA"])
            self.assertLessEqual(abs(item["ALLOWED_DELTA"]), abs(item["RAW_DELTA"]) + 1e-8)
        self.assertEqual(record, decide_reference_matching(target, reference).to_record())


def local_headroom(p, chroma_a=9.0, chroma_b=12.0, risk=False):
    dist = p.distribution
    dist["skin_headroom_facts"] = {
        "local_person_color_risk": risk, "local_person_exposure_risk": risk,
        "trusted_skin_pixel_ratio": .05, "skin_like_pixel_ratio": .1,
        "trusted_skin_median_lab_a": chroma_a, "trusted_skin_median_lab_b": chroma_b,
    }
    return replace(p, distribution_json=json.dumps(dist))


class FinalCalibrationTests(unittest.TestCase):
    def person(self, role=TargetColorProfile, **kwargs):
        return profile(role, DIAGNOSIS_CONFIDENCE=.9, SKIN_RISK__state="MEDIUM",
                       SKIN_RISK__evidence__person_present=True,
                       SCENE_RISK__evidence__scene_intent="PERSON_SCENE", **kwargs)

    def check_trace(self, decision):
        record = json.loads(json.dumps(decision.to_record(), allow_nan=False))
        self.assertEqual(record, decide_reference_matching(decision.target, decision.reference).to_record())
        for name, item in record["DIMENSIONS"].items():
            trace = item["LIMIT_CONTRIBUTION_TRACE"]
            self.assertTrue(all(a["OUTPUT_PARAMETER"] == b["INPUT_PARAMETER"] for a, b in zip(trace, trace[1:])))
            self.assertEqual(trace[-1]["OUTPUT_PARAMETER"], getattr(decision.parameters, name))
            self.assertAlmostEqual(trace[-1]["OUTPUT_ALLOWED_DELTA"], item["ALLOWED_DELTA"])
            self.assertLessEqual(abs(item["ALLOWED_DELTA"]), abs(item["RAW_DELTA"]) + 1e-8)
            e = item["RISK_AWARE_MATCH_BUDGET"]["final_calibration"]
            if e["AMPLIFIED"]:
                for field in ("SKIN_HEADROOM", "BRAND_HEADROOM", "CLIPPING_HEADROOM", "EXPOSURE_HEADROOM", "COLOR_CAST_HEADROOM"):
                    self.assertIsNotNone(e[field])
                self.assertEqual(e["C_ALLOWED_PARAMETER"], item["FINAL_PARAMETER"])
                self.assertGreater(abs(item["FINAL_PARAMETER"]), abs(e["B_FINAL_PARAMETER"]))

    def test_wb_budget_requires_real_local_facts_and_retains_other_axes(self):
        for sign in (-1, 1):
            t = self.person(WHITE_BALANCE__state="COOL" if sign > 0 else "WARM",
                            WHITE_BALANCE__evidence__neutral_lab_b=-6*sign)
            r = self.person(ReferenceColorTarget, WHITE_BALANCE__evidence__neutral_lab_b=8*sign)
            b = decide_reference_matching(t, r)
            c = decide_reference_matching(local_headroom(t), local_headroom(r))
            self.assertGreater(c.parameters.temperature*sign, b.parameters.temperature*sign)
            self.assertLessEqual(abs(c.parameters.temperature), POLICY["temperature"][1])
            for name in PARAMETER_SPECS:
                if name != "temperature":
                    self.assertEqual(getattr(c.parameters, name), getattr(b.parameters, name))
            self.assertEqual(c.to_record()["MATCH_TIER"], "ASSERTIVE_SAFE")
            self.check_trace(c)
            self.assertEqual(decide_reference_matching(local_headroom(t, risk=True), local_headroom(r)).parameters, b.parameters)
            self.assertTrue(decide_reference_matching(local_headroom(t), local_headroom(r), match_strength=0).parameters.is_neutral)

    def test_chroma_pool_prefers_selective_and_bounds_combined_skin_displacement(self):
        low = local_headroom(self.person(SATURATION__evidence__saturation_p50=.12,
                                        SATURATION__evidence__saturation_p90=.4))
        high = local_headroom(self.person(ReferenceColorTarget, SATURATION__evidence__saturation_p50=.28,
                                         SATURATION__evidence__saturation_p90=.8))
        c = decide_reference_matching(low, high)
        self.assertGreater(c.parameters.vibrance, c.parameters.saturation)
        self.assertGreater(c.parameters.saturation, 5)
        self.check_trace(c)
        for name in ("saturation", "vibrance"):
            e = c.to_record()["DIMENSIONS"][name]["RISK_AWARE_MATCH_BUDGET"]["final_calibration"]
            self.assertLessEqual(e["SKIN_HEADROOM"]["PREDICTED_UPPER_CHROMA_DISPLACEMENT"], CALIBRATION_LIMITS.skin_chroma_lab_budget + 1e-8)
        reverse = decide_reference_matching(
            TargetColorProfile(high.source, high.diagnosis_json, high.distribution_json),
            ReferenceColorTarget(low.source, low.diagnosis_json, low.distribution_json))
        self.assertLess(reverse.parameters.saturation, -14)
        self.assertLessEqual(reverse.parameters.vibrance, 0)
        self.check_trace(reverse)

    def test_coherent_tint_can_release_headroom_but_stable_tint_is_unchanged(self):
        for sign in (-1, 1):
            kwargs = dict(SKIN_RISK__state="MEDIUM", SKIN_RISK__evidence__person_present=True)
            t = local_headroom(coherent_axis_profile(TargetColorProfile, -2*sign, **kwargs))
            r = local_headroom(coherent_axis_profile(ReferenceColorTarget, 4*sign, **kwargs))
            c = decide_reference_matching(t, r)
            self.assertGreater(c.parameters.tint*sign, SKIN_CAPS["tint"])
            self.check_trace(c)
        t, r = self.person(), self.person(ReferenceColorTarget, WHITE_BALANCE__evidence__neutral_lab_a=3)
        self.assertEqual(decide_reference_matching(t, r).parameters,
                         decide_reference_matching(local_headroom(t), local_headroom(r)).parameters)

    def test_exposure_uses_ev_response_with_highlight_room_and_no_duplicate_brightness(self):
        t = self.person(EXPOSURE__state="UNDEREXPOSED", EXPOSURE__evidence__mean_luminance=.25,
                        EXPOSURE__evidence__luminance_p50=.23, EXPOSURE__evidence__luminance_p95=.56)
        r = self.person(ReferenceColorTarget, EXPOSURE__evidence__mean_luminance=.38,
                        EXPOSURE__evidence__luminance_p50=.35, EXPOSURE__evidence__luminance_p95=.81)
        dist = t.distribution
        dist.update(strong_color_ratio=.25, dominant_color_risk="MEDIUM")
        t = replace(t, distribution_json=json.dumps(dist))
        b, c = decide_reference_matching(t, r), decide_reference_matching(local_headroom(t), local_headroom(r))
        self.assertGreater(c.parameters.exposure, b.parameters.exposure)
        self.assertLessEqual(c.parameters.exposure, POLICY["exposure"][1])
        self.assertEqual(c.parameters.brightness, 0)
        self.check_trace(c)
        self.assertEqual(decide_reference_matching(local_headroom(t, risk=True), local_headroom(r)).parameters, b.parameters)

    def test_existing_selective_budget_cannot_be_spent_again_by_uniform_calibration(self):
        low = local_headroom(self.person(SATURATION__evidence__saturation_p50=.08,
                                        SATURATION__evidence__saturation_p90=.4),42,56)
        high = local_headroom(self.person(ReferenceColorTarget, SATURATION__evidence__saturation_p50=.30,
                                         SATURATION__evidence__saturation_p90=.5),42,56)
        c = decide_reference_matching(low,high)
        for name in ("saturation","vibrance"):
            e = c.to_record()["DIMENSIONS"][name]["RISK_AWARE_MATCH_BUDGET"]["final_calibration"]
            self.assertFalse(e["AMPLIFIED"])
            self.assertEqual(getattr(c.parameters,name),e["B_FINAL_PARAMETER"])
        self.check_trace(c)

    def test_contrast_tails_and_high_risk_sentinels_never_get_new_budgets(self):
        t = self.person()
        r = self.person(ReferenceColorTarget, EXPOSURE__evidence__luminance_p95=.86,
                        EXPOSURE__evidence__luminance_p50=.49)
        self.assertEqual(decide_reference_matching(t, r).parameters,
                         decide_reference_matching(local_headroom(t), local_headroom(r)).parameters)
        for risk in ("HIGH",):
            d = t.diagnosis
            d["SKIN_RISK"]["state"] = risk
            risky = replace(t, diagnosis_json=json.dumps(d))
            self.assertEqual(decide_reference_matching(risky, r).parameters,
                             decide_reference_matching(local_headroom(risky), local_headroom(r)).parameters)


class ManagedPairIntegrationTests(unittest.TestCase):
    def test_managed_inputs_replay_encoding_orientation_dpi_alpha_and_source_identity(self):
        original = Path(__file__).resolve().parents[2] / "output/evaluation/d01_color_decision_20260812/inputs/D01_01.jpg"
        with Image.open(original) as image:
            rgb = np.asarray(image.convert("RGB"))
        with tempfile.TemporaryDirectory(prefix="hdde-d60-05-") as tmp:
            root = Path(tmp)
            for suffix, dpi, alpha in ((".png", (300, 300), True), (".png", None, False),
                                       (".jpg", (240, 240), False)):
                with self.subTest(suffix=suffix, dpi=dpi, alpha=alpha):
                    pixels = np.dstack((rgb, np.full(rgb.shape[:2], 127, np.uint8))) if alpha else rgb
                    path, refpath = root / ("target"+suffix), root / "reference.png"
                    options = {"icc_profile": srgb_profile_bytes()}
                    if dpi:
                        options["dpi"] = dpi
                    if suffix == ".jpg":
                        exif = Image.Exif()
                        exif[274] = 6
                        options["exif"] = exif
                    Image.fromarray(pixels).save(path, **options)
                    managed = load_color_managed_source(path)
                    ref_pixels = execute_basic_correction(managed.pixels, CorrectionParameters(temperature=30)).candidate_image
                    Image.fromarray(ref_pixels).save(refpath, icc_profile=srgb_profile_bytes())
                    hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (path, refpath)]
                    target, reference = load_target_color_profile(path), load_reference_color_target(refpath)
                    decision = decide_reference_matching(target, reference)
                    result = execute_basic_correction(managed.pixels, decision.parameters)
                    recorded = json.loads(json.dumps(decision.parameters.to_record()))
                    replay_source = load_color_managed_source(path)
                    replay = execute_basic_correction(replay_source.pixels, CorrectionParameters.from_record(recorded))
                    np.testing.assert_array_equal(result.candidate_image, replay.candidate_image)
                    if alpha:
                        np.testing.assert_array_equal(result.candidate_image[..., 3], pixels[..., 3])
                    if suffix == ".jpg":
                        self.assertEqual(managed.pixels.shape[:2], rgb.shape[1::-1])
                    encoded = encode_color_managed_candidate(result.candidate_image, managed)
                    verify_color_managed_output(encoded, result.candidate_image, managed)
                    self.assertEqual(hashes, [hashlib.sha256(p.read_bytes()).hexdigest() for p in (path, refpath)])
                    neutral = execute_basic_correction(managed.pixels, CorrectionParameters())
                    np.testing.assert_array_equal(neutral.candidate_image, managed.pixels)
                    self.assertNotIn("candidate_image", decision.to_record())
                    self.assertNotIn("pixels", reference.to_record())


if __name__ == "__main__":
    unittest.main()
