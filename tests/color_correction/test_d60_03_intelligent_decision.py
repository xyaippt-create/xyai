from __future__ import annotations

import dataclasses
import runpy
import unittest
from pathlib import Path

import numpy as np
from PIL import Image
from engine.color_correction.color_management import load_color_managed_source

from engine.color_correction import (
    PARAMETER_SPECS,
    DiagnosisSeverity,
    DiagnosticFinding,
    ParameterDecisionOutcome,
    analyze_color_usability,
    audit_candidate,
    bind_parameter_decision,
    build_objective_diagnosis,
    decide_correction_parameters,
    generate_candidate,
    magnitude_for,
    validate_parameter_decision,
)


ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "output/evaluation/d01_color_decision_20260812/inputs"


def _pixels(name: str) -> np.ndarray:
    with Image.open(INPUTS / name) as image:
        image.load()
        return np.asarray(image.convert("RGB"), dtype=np.uint8).copy()


def _diagnosis(name: str, *, person_regions=None):
    decision = analyze_color_usability(_pixels(name), person_regions=person_regions)
    return decision, build_objective_diagnosis(decision)


def _finding(state: str, severity: DiagnosisSeverity, **evidence) -> DiagnosticFinding:
    return DiagnosticFinding(state, severity, 0.9, evidence)


def _controlled_base():
    _, base = _diagnosis("D01_01.jpg", person_regions=[])
    return dataclasses.replace(
        base,
        exposure=_finding(
            "ACCEPTABLE",
            DiagnosisSeverity.NONE,
            luminance_p05=0.15,
            luminance_p50=0.48,
            luminance_p95=0.82,
            mean_luminance=0.49,
            shadow_ratio=0.08,
        ),
        brightness_distribution=_finding(
            "BALANCED",
            DiagnosisSeverity.NONE,
            luminance_p05=0.15,
            luminance_p50=0.48,
            luminance_p95=0.82,
        ),
        contrast=_finding(
            "ACCEPTABLE",
            DiagnosisSeverity.NONE,
            luminance_p05=0.15,
            luminance_p95=0.82,
            dynamic_range_p95_p05=0.67,
        ),
        saturation=_finding(
            "ACCEPTABLE",
            DiagnosisSeverity.NONE,
            saturation_mean=0.30,
            saturation_p50=0.26,
            saturation_p90=0.62,
            strong_color_ratio=0.25,
        ),
        highlights=_finding(
            "ACCEPTABLE",
            DiagnosisSeverity.NONE,
            luminance_p95=0.82,
            luminance_p99=0.93,
            highlight_clip_ratio=0.0,
        ),
        shadows=_finding(
            "ACCEPTABLE",
            DiagnosisSeverity.NONE,
            luminance_p01=0.05,
            luminance_p05=0.15,
            shadow_clip_ratio=0.0,
        ),
        white_balance=_finding(
            "NEUTRAL",
            DiagnosisSeverity.NONE,
            neutral_lab_a=1.0,
            neutral_lab_b=2.0,
            neutral_chroma=2.24,
            neutral_evidence_state="SUFFICIENT",
            spatial_direction_consistency=0.9,
        ),
        neutral_color_evidence=_finding(
            "SUFFICIENT",
            DiagnosisSeverity.NONE,
            pixel_ratio=0.2,
            median_lab_a=1.0,
            median_lab_b=2.0,
            median_chroma=2.24,
            eligible_spatial_cells=9,
            spatial_field="UNIFORM",
            quantization_boundary_unstable=False,
        ),
        skin_risk=_finding(
            "LOW",
            DiagnosisSeverity.NONE,
            person_present=False,
            local_person_color_risk=False,
            local_person_exposure_risk=False,
            trusted_skin_pixel_ratio=0.0,
        ),
        scene_risk=_finding(
            "LOW",
            DiagnosisSeverity.NONE,
            scene_intent="GENERAL",
            dominant_color_risk="LOW",
            spatial_field="UNIFORM",
        ),
        clipping=_finding(
            "ACCEPTABLE",
            DiagnosisSeverity.NONE,
            shadow_clip_ratio=0.0,
            highlight_clip_ratio=0.0,
            combined_clip_ratio=0.0,
        ),
    )


class ObjectiveDiagnosisTests(unittest.TestCase):
    def test_contract_is_structured_and_has_no_product_action(self):
        _, diagnosis = _diagnosis("D01_01.jpg")
        record = diagnosis.to_dict()
        self.assertEqual(
            {
                "EXPOSURE",
                "WHITE_BALANCE",
                "COLOR_CAST",
                "BRIGHTNESS_DISTRIBUTION",
                "CONTRAST",
                "SATURATION",
                "HIGHLIGHTS",
                "SHADOWS",
                "NEUTRAL_COLOR_EVIDENCE",
                "SKIN_RISK",
                "SCENE_RISK",
                "CLIPPING",
                "DYNAMIC_RANGE",
            },
            {key for key in record if key.isupper() and key != "DIAGNOSIS_CONFIDENCE"},
        )
        self.assertNotIn("D1_ACTION", record)
        self.assertNotIn("AUTO_CORRECT", str(record))
        self.assertNotIn("KEEP_ORIGINAL", str(record))

    def test_real_directional_and_exposure_examples(self):
        _, warm = _diagnosis("D01_02.png")
        _, cool = _diagnosis("D01_03.png")
        _, dark = _diagnosis("D01_04.png")
        self.assertEqual(warm.white_balance.state, "WARM")
        self.assertEqual(cool.white_balance.state, "COOL")
        self.assertEqual(dark.exposure.state, "UNDEREXPOSED")

    def test_color_channel_clipping_is_part_of_objective_clipping_evidence(self):
        clipped_red = np.zeros((96, 128, 3), dtype=np.uint8)
        clipped_red[..., 0] = 255
        diagnosis = build_objective_diagnosis(
            analyze_color_usability(clipped_red, person_regions=[])
        )
        self.assertEqual(diagnosis.clipping.state, "SEVERE")
        self.assertGreaterEqual(
            diagnosis.clipping.evidence["maximum_color_channel_clip_ratio"],
            0.99,
        )
        self.assertGreaterEqual(
            diagnosis.clipping.evidence["color_clipped_pixel_ratio"],
            0.99,
        )


class ParameterDecisionTests(unittest.TestCase):
    def test_every_parameter_has_a_complete_decision_record(self):
        decision = decide_correction_parameters(_controlled_base())
        self.assertEqual(set(decision.parameter_decisions), set(PARAMETER_SPECS))
        for item in decision.parameter_decisions.values():
            record = item.to_dict()
            self.assertEqual(
                set(record),
                {"VALUE", "DIRECTION", "REASON", "SOURCE_EVIDENCE", "CONFIDENCE", "LIMIT_REASON"},
            )
        validate_parameter_decision(decision, source_fingerprint=decision.source_fingerprint)

    def test_severity_magnitudes_are_monotonic_and_inside_frozen_bounds(self):
        for name, spec in PARAMETER_SPECS.items():
            mild = magnitude_for(name, DiagnosisSeverity.MILD)
            moderate = magnitude_for(name, DiagnosisSeverity.MODERATE)
            strong = magnitude_for(name, DiagnosisSeverity.STRONG)
            self.assertLess(0.0, mild)
            self.assertLess(mild, moderate)
            self.assertLess(moderate, strong)
            self.assertLess(strong, spec.maximum)

    def test_tone_control_directions_and_roles(self):
        base = _controlled_base()
        under = decide_correction_parameters(dataclasses.replace(
            base,
            exposure=_finding(
                "UNDEREXPOSED", DiagnosisSeverity.MODERATE,
                luminance_p05=0.03, luminance_p50=0.21, luminance_p95=0.58,
                mean_luminance=0.25, shadow_ratio=0.4,
            ),
        ))
        self.assertGreater(under.correction_parameters.exposure, 0.0)
        self.assertEqual(under.active_parameters, ("exposure",))

        over = decide_correction_parameters(dataclasses.replace(
            base,
            exposure=_finding(
                "OVEREXPOSED", DiagnosisSeverity.MILD,
                luminance_p05=0.62, luminance_p50=0.85, luminance_p95=0.98,
                mean_luminance=0.83, shadow_ratio=0.0,
            ),
        ))
        self.assertLess(over.correction_parameters.exposure, 0.0)

        darker_midtones = decide_correction_parameters(dataclasses.replace(
            base,
            brightness_distribution=_finding(
                "LOW_MIDTONES", DiagnosisSeverity.MILD,
                luminance_p05=0.1, luminance_p50=0.31, luminance_p95=0.75,
            ),
        ))
        self.assertGreater(darker_midtones.correction_parameters.brightness, 0.0)
        self.assertEqual(darker_midtones.correction_parameters.exposure, 0.0)

        low_contrast = decide_correction_parameters(dataclasses.replace(
            base,
            contrast=_finding(
                "LOW", DiagnosisSeverity.MODERATE,
                luminance_p05=0.28, luminance_p95=0.64, dynamic_range_p95_p05=0.36,
            ),
        ))
        self.assertGreater(low_contrast.correction_parameters.contrast, 0.0)

        high_contrast = decide_correction_parameters(dataclasses.replace(
            base,
            contrast=_finding(
                "HIGH", DiagnosisSeverity.MODERATE,
                luminance_p05=0.04, luminance_p95=0.93, dynamic_range_p95_p05=0.89,
            ),
        ))
        self.assertLess(high_contrast.correction_parameters.contrast, 0.0)

    def test_white_balance_and_chroma_directions(self):
        base = _controlled_base()
        cases = (
            ("WARM", "temperature", -1),
            ("COOL", "temperature", 1),
            ("GREEN", "tint", 1),
            ("MAGENTA", "tint", -1),
        )
        for state, parameter, sign in cases:
            with self.subTest(state=state):
                white_balance = _finding(
                    state,
                    DiagnosisSeverity.MODERATE,
                    neutral_lab_a=-9.0 if state == "GREEN" else 9.0 if state == "MAGENTA" else 1.0,
                    neutral_lab_b=10.0 if state == "WARM" else -10.0 if state == "COOL" else 2.0,
                    neutral_chroma=10.0,
                    neutral_evidence_state="SUFFICIENT",
                    spatial_direction_consistency=0.9,
                )
                decision = decide_correction_parameters(dataclasses.replace(base, white_balance=white_balance))
                self.assertEqual(np.sign(getattr(decision.correction_parameters, parameter)), sign)

        low = decide_correction_parameters(dataclasses.replace(
            base,
            saturation=_finding(
                "LOW", DiagnosisSeverity.MODERATE,
                saturation_mean=0.14, saturation_p50=0.12, saturation_p90=0.34,
                strong_color_ratio=0.12,
            ),
        ))
        self.assertGreater(low.correction_parameters.vibrance, 0.0)
        self.assertEqual(low.correction_parameters.saturation, 0.0)
        high = decide_correction_parameters(dataclasses.replace(
            base,
            saturation=_finding(
                "HIGH", DiagnosisSeverity.MODERATE,
                saturation_mean=0.55, saturation_p50=0.6, saturation_p90=0.9,
                strong_color_ratio=0.35,
            ),
        ))
        self.assertLess(high.correction_parameters.saturation, 0.0)
        self.assertEqual(high.correction_parameters.vibrance, 0.0)

    def test_highlight_shadow_directions_are_local_and_mutually_exclusive(self):
        base = _controlled_base()
        highlights = decide_correction_parameters(dataclasses.replace(
            base,
            highlights=_finding(
                "CLIPPED", DiagnosisSeverity.MODERATE,
                luminance_p95=0.95, luminance_p99=0.998, highlight_clip_ratio=0.08,
            ),
        ))
        self.assertLess(highlights.correction_parameters.highlights, 0.0)
        self.assertEqual(highlights.correction_parameters.shadows, 0.0)
        shadows = decide_correction_parameters(dataclasses.replace(
            base,
            shadows=_finding(
                "CRUSHED", DiagnosisSeverity.MODERATE,
                luminance_p01=0.0, luminance_p05=0.04, shadow_clip_ratio=0.14,
            ),
        ))
        self.assertGreater(shadows.correction_parameters.shadows, 0.0)
        self.assertEqual(shadows.correction_parameters.highlights, 0.0)

    def test_no_correction_and_insufficient_evidence_are_distinct(self):
        _, normal = _diagnosis("D01_01.jpg")
        normal_decision = decide_correction_parameters(normal)
        self.assertEqual(normal_decision.outcome, ParameterDecisionOutcome.NO_CORRECTION_REQUIRED)
        self.assertTrue(normal_decision.no_correction_reasons)
        self.assertFalse(normal_decision.insufficient_evidence_reasons)

        base = _controlled_base()
        insufficient = decide_correction_parameters(dataclasses.replace(
            base,
            white_balance=_finding(
                "UNKNOWN", DiagnosisSeverity.INDETERMINATE,
                neutral_lab_a=0.0, neutral_lab_b=0.0, neutral_chroma=0.0,
                neutral_evidence_state="INSUFFICIENT", spatial_direction_consistency=0.0,
            ),
            neutral_color_evidence=_finding(
                "INSUFFICIENT", DiagnosisSeverity.INDETERMINATE,
                pixel_ratio=0.0, median_lab_a=0.0, median_lab_b=0.0,
                median_chroma=0.0, eligible_spatial_cells=0,
                spatial_field="UNKNOWN", quantization_boundary_unstable=False,
            ),
        ))
        self.assertEqual(insufficient.outcome, ParameterDecisionOutcome.INSUFFICIENT_EVIDENCE)
        self.assertIn("NO_RELIABLE_NEUTRAL_EVIDENCE", insufficient.insufficient_evidence_reasons)

    def test_clipped_endpoint_that_cannot_be_safely_adjusted_is_insufficient(self):
        base = _controlled_base()
        blocked = decide_correction_parameters(dataclasses.replace(
            base,
            highlights=_finding(
                "CLIPPED", DiagnosisSeverity.MODERATE,
                luminance_p95=0.97, luminance_p99=1.0, highlight_clip_ratio=0.08,
            ),
            clipping=_finding(
                "ELEVATED", DiagnosisSeverity.MODERATE,
                shadow_clip_ratio=0.0, highlight_clip_ratio=0.08,
                combined_clip_ratio=0.08,
            ),
        ))
        self.assertEqual(blocked.outcome, ParameterDecisionOutcome.INSUFFICIENT_EVIDENCE)
        self.assertEqual(blocked.active_parameters, ())
        self.assertIn(
            "CLIPPING_LIMITS_ENDPOINT_TONE_DECISION",
            blocked.insufficient_evidence_reasons,
        )

    def test_severe_channel_clipping_blocks_high_saturation_parameters(self):
        base = _controlled_base()
        blocked = decide_correction_parameters(dataclasses.replace(
            base,
            saturation=_finding(
                "HIGH", DiagnosisSeverity.MODERATE,
                saturation_mean=0.58, saturation_p50=0.62, saturation_p90=0.94,
                strong_color_ratio=0.42,
            ),
            clipping=_finding(
                "SEVERE", DiagnosisSeverity.STRONG,
                shadow_clip_ratio=0.02, highlight_clip_ratio=0.04,
                combined_clip_ratio=0.06,
                maximum_color_channel_clip_ratio=0.46,
                color_clipped_pixel_ratio=0.39,
            ),
        ))
        self.assertEqual(blocked.outcome, ParameterDecisionOutcome.INSUFFICIENT_EVIDENCE)
        self.assertEqual(blocked.active_parameters, ())
        self.assertEqual(blocked.correction_parameters.saturation, 0.0)
        self.assertEqual(blocked.correction_parameters.vibrance, 0.0)
        self.assertEqual(
            blocked.parameter_decisions["saturation"].reason,
            "SATURATION_MEASUREMENT_UNRELIABLE_DUE_TO_CLIPPING",
        )
        self.assertIn(
            "CLIPPING_LIMITS_SATURATION_EVIDENCE",
            blocked.insufficient_evidence_reasons,
        )

    def test_exposure_risk_protection_distinguishes_intent_from_true_error(self):
        base = _controlled_base()

        high_key = decide_correction_parameters(dataclasses.replace(
            base,
            exposure=_finding(
                "OVEREXPOSED", DiagnosisSeverity.MILD,
                luminance_p05=0.62, luminance_p50=0.85, luminance_p95=0.99,
                mean_luminance=0.84, shadow_ratio=0.0,
            ),
            scene_risk=_finding(
                "HIGH", DiagnosisSeverity.STRONG,
                scene_intent="PROBABLE_HIGH_KEY_OR_BACKLIGHT",
                dominant_color_risk="LOW", spatial_field="UNIFORM",
            ),
            highlights=_finding(
                "AT_RISK", DiagnosisSeverity.MILD,
                luminance_p95=0.99, luminance_p99=1.0, highlight_clip_ratio=0.04,
            ),
            clipping=_finding(
                "MILD", DiagnosisSeverity.MILD,
                shadow_clip_ratio=0.0, highlight_clip_ratio=0.04,
                combined_clip_ratio=0.04,
            ),
        ))
        self.assertEqual(high_key.outcome, ParameterDecisionOutcome.INSUFFICIENT_EVIDENCE)
        self.assertEqual(high_key.correction_parameters.exposure, 0.0)

        backlit_person = decide_correction_parameters(dataclasses.replace(
            base,
            exposure=_finding(
                "UNDEREXPOSED", DiagnosisSeverity.MODERATE,
                luminance_p05=0.02, luminance_p50=0.23, luminance_p95=0.57,
                mean_luminance=0.25, shadow_ratio=0.38,
            ),
            shadows=_finding(
                "AT_RISK", DiagnosisSeverity.MILD,
                luminance_p01=0.0, luminance_p05=0.02, shadow_clip_ratio=0.04,
            ),
            skin_risk=_finding(
                "HIGH", DiagnosisSeverity.STRONG,
                person_present=True, local_person_color_risk=False,
                local_person_exposure_risk=True, trusted_skin_pixel_ratio=0.03,
            ),
            scene_risk=_finding(
                "HIGH", DiagnosisSeverity.STRONG,
                scene_intent="PROBABLE_HIGH_KEY_OR_BACKLIGHT",
                dominant_color_risk="LOW", spatial_field="UNIFORM",
            ),
            clipping=_finding(
                "MILD", DiagnosisSeverity.MILD,
                shadow_clip_ratio=0.04, highlight_clip_ratio=0.0,
                combined_clip_ratio=0.04,
            ),
        ))
        self.assertEqual(backlit_person.outcome, ParameterDecisionOutcome.INSUFFICIENT_EVIDENCE)
        self.assertEqual(backlit_person.correction_parameters.exposure, 0.0)

        low_light_intent = decide_correction_parameters(dataclasses.replace(
            base,
            exposure=_finding(
                "UNDEREXPOSED", DiagnosisSeverity.STRONG,
                luminance_p05=0.0, luminance_p50=0.12, luminance_p95=0.50,
                mean_luminance=0.14, shadow_ratio=0.62,
            ),
            shadows=_finding(
                "CRUSHED", DiagnosisSeverity.MODERATE,
                luminance_p01=0.0, luminance_p05=0.0, shadow_clip_ratio=0.14,
            ),
            scene_risk=_finding(
                "HIGH", DiagnosisSeverity.STRONG,
                scene_intent="LEGITIMATE_DARK",
                dominant_color_risk="LOW", spatial_field="UNIFORM",
            ),
            clipping=_finding(
                "ELEVATED", DiagnosisSeverity.MODERATE,
                shadow_clip_ratio=0.14, highlight_clip_ratio=0.0,
                combined_clip_ratio=0.14,
            ),
        ))
        self.assertNotEqual(low_light_intent.outcome, ParameterDecisionOutcome.CORRECTION_NEEDED)
        self.assertEqual(low_light_intent.correction_parameters.exposure, 0.0)

        true_under_person = decide_correction_parameters(dataclasses.replace(
            base,
            exposure=_finding(
                "UNDEREXPOSED", DiagnosisSeverity.STRONG,
                luminance_p05=0.0, luminance_p50=0.15, luminance_p95=0.52,
                mean_luminance=0.17, shadow_ratio=0.57,
            ),
            shadows=_finding(
                "CRUSHED", DiagnosisSeverity.MODERATE,
                luminance_p01=0.0, luminance_p05=0.0, shadow_clip_ratio=0.13,
            ),
            skin_risk=_finding(
                "HIGH", DiagnosisSeverity.STRONG,
                person_present=True, local_person_color_risk=False,
                local_person_exposure_risk=True, trusted_skin_pixel_ratio=0.03,
            ),
            scene_risk=_finding(
                "MEDIUM", DiagnosisSeverity.MODERATE,
                scene_intent="PERSON_SCENE",
                dominant_color_risk="LOW", spatial_field="UNIFORM",
            ),
            clipping=_finding(
                "ELEVATED", DiagnosisSeverity.MODERATE,
                shadow_clip_ratio=0.13, highlight_clip_ratio=0.0,
                combined_clip_ratio=0.13,
            ),
        ))
        self.assertEqual(true_under_person.outcome, ParameterDecisionOutcome.CORRECTION_NEEDED)
        self.assertEqual(true_under_person.correction_parameters.exposure, 0.16)

        true_over_person = decide_correction_parameters(dataclasses.replace(
            base,
            exposure=_finding(
                "OVEREXPOSED", DiagnosisSeverity.STRONG,
                luminance_p05=0.71, luminance_p50=0.92, luminance_p95=1.0,
                mean_luminance=0.89, shadow_ratio=0.0,
            ),
            highlights=_finding(
                "CLIPPED", DiagnosisSeverity.MODERATE,
                luminance_p95=1.0, luminance_p99=1.0, highlight_clip_ratio=0.15,
            ),
            skin_risk=_finding(
                "HIGH", DiagnosisSeverity.STRONG,
                person_present=True, local_person_color_risk=False,
                local_person_exposure_risk=True, trusted_skin_pixel_ratio=0.03,
            ),
            scene_risk=_finding(
                "HIGH", DiagnosisSeverity.STRONG,
                scene_intent="PROBABLE_HIGH_KEY_OR_BACKLIGHT",
                dominant_color_risk="LOW", spatial_field="UNIFORM",
            ),
            clipping=_finding(
                "ELEVATED", DiagnosisSeverity.MODERATE,
                shadow_clip_ratio=0.0, highlight_clip_ratio=0.15,
                combined_clip_ratio=0.15,
            ),
        ))
        self.assertEqual(true_over_person.outcome, ParameterDecisionOutcome.CORRECTION_NEEDED)
        self.assertEqual(true_over_person.correction_parameters.exposure, -0.16)

        non_person_high_key = decide_correction_parameters(dataclasses.replace(
            base,
            exposure=_finding(
                "OVEREXPOSED", DiagnosisSeverity.STRONG,
                luminance_p05=0.70, luminance_p50=0.91, luminance_p95=0.99,
                mean_luminance=0.88, shadow_ratio=0.0,
            ),
            scene_risk=_finding(
                "HIGH", DiagnosisSeverity.STRONG,
                scene_intent="LEGITIMATE_HIGH_KEY",
                dominant_color_risk="LOW", spatial_field="UNIFORM",
            ),
        ))
        self.assertEqual(non_person_high_key.outcome, ParameterDecisionOutcome.NO_CORRECTION_REQUIRED)
        self.assertEqual(non_person_high_key.correction_parameters.exposure, 0.0)

    def test_skin_scene_and_multi_parameter_protection(self):
        _, local_skin = _diagnosis("D01_08.png")
        skin_decision = decide_correction_parameters(local_skin)
        self.assertEqual(skin_decision.correction_parameters.temperature, 0.0)
        self.assertEqual(skin_decision.correction_parameters.tint, 0.0)

        _, warm_scene = _diagnosis("D01_13.png")
        scene_decision = decide_correction_parameters(warm_scene)
        self.assertEqual(scene_decision.outcome, ParameterDecisionOutcome.NO_CORRECTION_REQUIRED)
        self.assertEqual(scene_decision.correction_parameters.temperature, 0.0)

        base = _controlled_base()
        combined = decide_correction_parameters(dataclasses.replace(
            base,
            exposure=_finding(
                "UNDEREXPOSED", DiagnosisSeverity.MODERATE,
                luminance_p05=0.03, luminance_p50=0.21, luminance_p95=0.58,
                mean_luminance=0.25, shadow_ratio=0.4,
            ),
            white_balance=_finding(
                "WARM", DiagnosisSeverity.MODERATE,
                neutral_lab_a=1.0, neutral_lab_b=10.0, neutral_chroma=10.0,
                neutral_evidence_state="SUFFICIENT", spatial_direction_consistency=0.9,
            ),
            saturation=_finding(
                "HIGH", DiagnosisSeverity.MODERATE,
                saturation_mean=0.55, saturation_p50=0.6, saturation_p90=0.9,
                strong_color_ratio=0.35,
            ),
        ))
        self.assertEqual(combined.active_parameters, ("exposure",))

    def test_bound_parameters_reach_d2_and_d3_replays_from_source(self):
        managed_source = load_color_managed_source(INPUTS / "D01_04.png")
        pixels = managed_source.pixels
        d1 = analyze_color_usability(pixels)
        parameter_decision = decide_correction_parameters(build_objective_diagnosis(d1))
        bind_parameter_decision(d1, parameter_decision)
        d2 = generate_candidate(pixels, d1)
        self.assertEqual(d2.status, "CANDIDATE_READY")
        self.assertEqual(d2.executor_parameters, parameter_decision.correction_parameters.to_record())
        d3 = audit_candidate(pixels, d1, managed_source=managed_source, expected_output_format="PNG")
        self.assertEqual(d3.status, "AUDIT_COMPLETE")
        self.assertEqual(d3.final_action.value, "ACCEPT_CORRECTED")
        replay = d3.audit_metrics["basic_correction_replay"]
        self.assertEqual(replay["PASS_STATUS"]["REPLAY_PASS"], "YES")

    def test_multi_parameter_plan_keeps_contract_order(self):
        pixels = _pixels("D01_01.jpg")
        d1 = analyze_color_usability(pixels, person_regions=[])
        controlled = dataclasses.replace(
            build_objective_diagnosis(d1),
            brightness_distribution=_finding(
                "LOW_MIDTONES", DiagnosisSeverity.MILD,
                luminance_p05=0.1, luminance_p50=0.31, luminance_p95=0.75,
            ),
            white_balance=_finding(
                "WARM", DiagnosisSeverity.MILD,
                neutral_lab_a=1.0, neutral_lab_b=8.0, neutral_chroma=8.06,
                neutral_evidence_state="SUFFICIENT", spatial_direction_consistency=0.9,
            ),
            skin_risk=_finding(
                "LOW", DiagnosisSeverity.NONE,
                person_present=False, local_person_color_risk=False,
                local_person_exposure_risk=False, trusted_skin_pixel_ratio=0.0,
            ),
            scene_risk=_finding(
                "LOW", DiagnosisSeverity.NONE,
                scene_intent="GENERAL", dominant_color_risk="LOW", spatial_field="UNIFORM",
            ),
        )
        parameter_decision = decide_correction_parameters(controlled)
        self.assertEqual(parameter_decision.active_parameters, ("brightness", "temperature"))
        bind_parameter_decision(d1, parameter_decision)
        d2 = generate_candidate(pixels, d1, person_regions=[])
        self.assertEqual(
            d2.plan.protection_profile["active_parameters"],
            ["brightness", "temperature"],
        )


class PersonMidtoneDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        validation = runpy.run_path(str(
            ROOT / "tests/color_correction/run_d60_03_real_decision_validation.py"
        ))
        cases, _ = validation["_cases"]()
        cls.real_cases = {case.name: case for case in cases}

    def _person_midtones(self, state="LOW_MIDTONES"):
        base = _controlled_base()
        return dataclasses.replace(
            base,
            brightness_distribution=_finding(
                state, DiagnosisSeverity.MILD,
                luminance_p05=0.12,
                luminance_p50=0.30 if state == "LOW_MIDTONES" else 0.79,
                luminance_p95=0.85,
            ),
            skin_risk=_finding(
                "MEDIUM", DiagnosisSeverity.MODERATE,
                person_present=True,
                local_person_color_risk=False,
                local_person_exposure_risk=False,
            ),
            scene_risk=_finding(
                "MEDIUM", DiagnosisSeverity.MODERATE,
                scene_intent="PERSON_SCENE",
                dominant_color_risk="LOW", spatial_field="UNIFORM",
            ),
        )

    def test_safe_mild_person_midtones_use_only_the_mild_brightness_budget(self):
        for state, sign in (("LOW_MIDTONES", 1), ("HIGH_MIDTONES", -1)):
            with self.subTest(state=state):
                diagnosis = self._person_midtones(state)
                decision = decide_correction_parameters(diagnosis)
                self.assertEqual(decision.outcome, ParameterDecisionOutcome.CORRECTION_NEEDED)
                self.assertEqual(decision.active_parameters, ("brightness",))
                self.assertEqual(
                    decision.correction_parameters.brightness,
                    sign * magnitude_for("brightness", DiagnosisSeverity.MILD),
                )
                item = decision.parameter_decisions["brightness"]
                self.assertIn("PERSON", item.reason)
                self.assertIsNotNone(item.limit_reason)
                self.assertTrue(any("local_person_exposure_risk=False" in s for s in item.source_evidence))
                validate_parameter_decision(decision, source_fingerprint=diagnosis.source_fingerprint)

    def test_person_midtones_do_not_bypass_evidence_or_protection(self):
        for state in ("LOW_MIDTONES", "HIGH_MIDTONES"):
            base = self._person_midtones(state)
            risks = {
                "low_diagnosis_confidence": dataclasses.replace(base, diagnosis_confidence=0.40),
                "low_midtone_confidence": dataclasses.replace(
                    base, brightness_distribution=dataclasses.replace(base.brightness_distribution, confidence=0.40)
                ),
                "strong_midtones": dataclasses.replace(
                    base, brightness_distribution=dataclasses.replace(base.brightness_distribution, severity=DiagnosisSeverity.STRONG)
                ),
                "high_skin_risk": dataclasses.replace(
                    base, skin_risk=dataclasses.replace(base.skin_risk, state="HIGH")
                ),
                "local_person_exposure_risk": dataclasses.replace(
                    base, skin_risk=dataclasses.replace(
                        base.skin_risk, evidence={**base.skin_risk.evidence, "local_person_exposure_risk": True}
                    )
                ),
                "local_person_color_risk": dataclasses.replace(
                    base, skin_risk=dataclasses.replace(
                        base.skin_risk, evidence={**base.skin_risk.evidence, "local_person_color_risk": True}
                    )
                ),
                "missing_local_person_evidence": dataclasses.replace(
                    base, skin_risk=dataclasses.replace(base.skin_risk, evidence={"person_present": True})
                ),
                "elevated_clipping": dataclasses.replace(base, clipping=dataclasses.replace(base.clipping, state="ELEVATED")),
                "severe_clipping": dataclasses.replace(base, clipping=dataclasses.replace(base.clipping, state="SEVERE")),
            }
            for intent in ("LEGITIMATE_HIGH_KEY", "PROBABLE_HIGH_KEY_OR_BACKLIGHT", "LEGITIMATE_WARM", "LEGITIMATE_DARK", "MIXED_LIGHT"):
                risks[intent] = dataclasses.replace(
                    base, scene_risk=dataclasses.replace(
                        base.scene_risk, state="HIGH", evidence={**base.scene_risk.evidence, "scene_intent": intent}
                    )
                )
            if state == "LOW_MIDTONES":
                risks["no_highlight_headroom"] = dataclasses.replace(
                    base, highlights=dataclasses.replace(base.highlights, evidence={**base.highlights.evidence, "luminance_p99": 0.999})
                )
                risks["missing_highlight_headroom"] = dataclasses.replace(
                    base, highlights=dataclasses.replace(base.highlights, evidence={})
                )
                risks["invalid_highlight_headroom"] = dataclasses.replace(
                    base, highlights=dataclasses.replace(base.highlights, evidence={"luminance_p99": float("nan")})
                )
            else:
                risks["no_shadow_headroom"] = dataclasses.replace(
                    base, shadows=dataclasses.replace(base.shadows, evidence={**base.shadows.evidence, "luminance_p01": 0.0})
                )
                risks["missing_shadow_headroom"] = dataclasses.replace(
                    base, shadows=dataclasses.replace(base.shadows, evidence={})
                )
                risks["invalid_shadow_headroom"] = dataclasses.replace(
                    base, shadows=dataclasses.replace(base.shadows, evidence={"luminance_p01": float("nan")})
                )
            for name, diagnosis in risks.items():
                with self.subTest(state=state, risk=name):
                    decision = decide_correction_parameters(diagnosis)
                    self.assertEqual(decision.outcome, ParameterDecisionOutcome.INSUFFICIENT_EVIDENCE)
                    self.assertFalse(decision.active_parameters)
                    self.assertNotEqual(
                        decision.parameter_decisions["brightness"].reason,
                        "BRIGHTNESS_DISTRIBUTION_ALREADY_ACCEPTABLE",
                    )
                    self.assertTrue(decision.insufficient_evidence_reasons)

    def test_portrait_derived_real_cases_never_clear_person_context(self):
        for name in (
            "02_obvious_over", "03_mild_under", "04_mild_over", "07_green_cast",
            "08_magenta_cast", "09_low_saturation", "10_high_saturation",
            "12_high_contrast", "31_severe_clipping_high_saturation",
        ):
            with self.subTest(sample=name):
                self.assertIsNone(self.real_cases[name].person_regions)

    def test_real_midtone_samples_keep_formal_automatic_person_context(self):
        for name, state, sign in (("03_mild_under", "LOW_MIDTONES", 1), ("04_mild_over", "HIGH_MIDTONES", -1)):
            with self.subTest(sample=name):
                case = self.real_cases[name]
                self.assertIsNone(case.person_regions, "real-image validation must not suppress person detection")
                d1 = analyze_color_usability(case.pixels)
                diagnosis = build_objective_diagnosis(d1)
                self.assertTrue(diagnosis.skin_risk.evidence["person_present"])
                self.assertEqual(diagnosis.scene_risk.state, "MEDIUM")
                self.assertEqual(diagnosis.brightness_distribution.state, state)
                decision = decide_correction_parameters(diagnosis)
                self.assertEqual(decision.outcome, ParameterDecisionOutcome.CORRECTION_NEEDED)
                self.assertEqual(decision.active_parameters, ("brightness",))
                self.assertGreater(sign * decision.correction_parameters.brightness, 0.0)

    def test_real_protection_sentinels_keep_formal_person_detection(self):
        expected = {
            "15_normal_photo": None,
            "17_product": None,
            "18_landscape": None,
            "19_warm_indoor": None,
            "25_high_key_portrait": None,
            "26_backlit_person": None,
            "28_true_underexposed_person": 1,
            "29_true_overexposed_person": -1,
            "32_high_skin_risk_under": None,
        }
        for name, exposure_sign in expected.items():
            with self.subTest(sample=name):
                diagnosis = build_objective_diagnosis(analyze_color_usability(self.real_cases[name].pixels))
                decision = decide_correction_parameters(diagnosis)
                if exposure_sign is None:
                    self.assertFalse(decision.active_parameters)
                else:
                    self.assertEqual(decision.active_parameters, ("exposure",))
                    self.assertGreater(exposure_sign * decision.correction_parameters.exposure, 0.0)
                self.assertEqual(decision.correction_parameters.temperature, 0.0)
                self.assertEqual(decision.correction_parameters.tint, 0.0)
        for name in ("02_obvious_over", "09_low_saturation", "10_high_saturation", "12_high_contrast", "13_highlight_problem", "14_shadow_problem"):
            with self.subTest(insufficient=name):
                diagnosis = build_objective_diagnosis(analyze_color_usability(self.real_cases[name].pixels))
                decision = decide_correction_parameters(diagnosis)
                self.assertEqual(decision.outcome, ParameterDecisionOutcome.INSUFFICIENT_EVIDENCE)
                self.assertFalse(decision.active_parameters)


if __name__ == "__main__":
    unittest.main()
