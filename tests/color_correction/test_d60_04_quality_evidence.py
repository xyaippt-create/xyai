from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np
from PIL import Image

from engine.color_correction import (
    CorrectionParameters,
    EvidenceVerdict,
    QualityNetBenefit,
    analyze_color_usability,
    audit_candidate,
    bind_parameter_decision,
    build_objective_diagnosis,
    decide_correction_parameters,
    evaluate_quality_evidence as _evaluate,
    execute_basic_correction,
)
from engine.color_correction.color_management import load_color_managed_source
from engine.color_correction.parameter_decision import (
    ParameterDecision, ParameterDecisionItem, ParameterDecisionOutcome,
    ParameterDirection, _decision_payload, _payload_digest,
)
from engine.color_correction.objective_diagnosis import DiagnosisSeverity
from engine.color_correction.parameters import PARAMETER_SPECS


def evaluate_quality_evidence(source, candidate, parameters, **kwargs):
    """Use actual PNG headers, not UNKNOWN-as-PASS, in pixel-level cases."""
    formats = []
    for pixels in (source, candidate):
        stream = BytesIO()
        Image.fromarray(pixels).save(stream, format="PNG")
        with Image.open(BytesIO(stream.getvalue())) as opened:
            opened.load()
            formats.append(opened.format)
    diagnosis = build_objective_diagnosis(analyze_color_usability(source, person_regions=()))
    return _evaluate(source, candidate, parameters, objective_diagnosis=diagnosis,
                     source_format=formats[0], expected_output_format="PNG", candidate_format=formats[1], **kwargs)


def explicit_parameter_audit(source, parameters, *, format_known=True):
    """Adversarial contract input, not the frozen automatic parameter policy.

    D3 still creates D2, independently replays all supplied parameters, rebuilds
    the real source diagnosis, and computes quality. No pixel/audit/net-benefit
    result is patched. Formal-policy/API coverage uses the real decider.
    """
    with tempfile.TemporaryDirectory(prefix="hdde-d6004r-") as directory:
        path = Path(directory) / "source.png"
        Image.fromarray(source).save(path)
        managed = load_color_managed_source(path)
        owner = analyze_color_usability(managed.pixels, person_regions=())
        diagnosis = build_objective_diagnosis(owner)
        active = tuple(name for name in PARAMETER_SPECS if getattr(parameters, name))
        items = {name: ParameterDecisionItem(
            getattr(parameters, name), ParameterDirection.NEUTRAL if name not in active else (
                ParameterDirection.INCREASE if getattr(parameters, name) > 0 else ParameterDirection.DECREASE
            ), "EXPLICIT_ADVERSARIAL_VALIDATION_INPUT", (diagnosis.source_fingerprint,), 1.0, None,
        ) for name in PARAMETER_SPECS}
        outcome = ParameterDecisionOutcome.CORRECTION_NEEDED
        payload = _decision_payload(diagnosis, outcome, parameters, items, (), (), 1.0, active, DiagnosisSeverity.MILD)
        decision = ParameterDecision(
            payload["schema_version"], payload["engine_version"], diagnosis.source_fingerprint,
            diagnosis.schema_version, outcome, parameters, items, (), (), 1.0, active,
            DiagnosisSeverity.MILD, _payload_digest(payload),
        )
        bind_parameter_decision(owner, decision)
        return audit_candidate(managed.pixels, owner, person_regions=(),
                               managed_source=managed if format_known else None,
                               expected_output_format="PNG" if format_known else None)


def _scene() -> np.ndarray:
    ramp = np.linspace(20, 235, 256, dtype=np.uint8)
    gray = np.tile(ramp, (256, 1))
    image = np.stack((gray, gray, gray), axis=2)
    image[24:104, 16:96] = (190, 135, 110)
    image[24:104, 160:240] = (205, 40, 48)
    image[152:232, 16:96] = (40, 95, 205)
    return image


def _lab_shift(image: np.ndarray, *, a: float = 0.0, b: float = 0.0) -> np.ndarray:
    lab = cv2.cvtColor(image.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    lab[..., 1] = np.clip(lab[..., 1] + a, -127.0, 127.0)
    lab[..., 2] = np.clip(lab[..., 2] + b, -127.0, 127.0)
    return np.clip(np.rint(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB) * 255.0), 0, 255).astype(np.uint8)


def _saturation(image: np.ndarray, value: float) -> np.ndarray:
    rgb = image.astype(np.float32) / 255.0
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hsv[..., 1] = np.clip(value, 0.0, 1.0)
    return np.clip(np.rint(cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB) * 255.0), 0, 255).astype(np.uint8)


class D6004QualityEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = _scene()

    def evaluate(self, candidate: np.ndarray, **values: float):
        parameters = CorrectionParameters(**values)
        return evaluate_quality_evidence(self.source, candidate, parameters)

    def test_contract_is_complete_serializable_and_fingerprinted(self):
        parameters = CorrectionParameters(exposure=0.32)
        candidate = execute_basic_correction(self.source, parameters).candidate_image
        evidence = evaluate_quality_evidence(self.source, candidate, parameters)
        record = evidence.to_record()

        json.dumps(record, sort_keys=True)
        self.assertEqual(record["schema_version"], "hdde.color-quality-evidence.schema.v1")
        self.assertTrue(record["EVIDENCE_FINGERPRINT"].startswith("hdde.quality-evidence.v1:"))
        for name in (
            "TARGETED_ISSUE_IMPROVEMENT",
            "EXPOSURE_QUALITY",
            "WHITE_BALANCE_QUALITY",
            "COLOR_CAST_QUALITY",
            "CONTRAST_QUALITY",
            "SATURATION_QUALITY",
            "HIGHLIGHT_QUALITY",
            "SHADOW_QUALITY",
            "SKIN_PROTECTION",
            "NEUTRAL_PROTECTION",
            "BRAND_COLOR_PROTECTION",
            "CLIPPING_DELTA",
            "DYNAMIC_RANGE_DELTA",
            "BANDING_RISK",
            "POSTERIZATION_RISK",
            "CHANNEL_SATURATION_RISK",
            "ALPHA_INTEGRITY",
            "DIMENSION_INTEGRITY",
            "FORMAT_INTEGRITY",
        ):
            self.assertEqual(set(record[name]), {"SOURCE_METRIC", "CANDIDATE_METRIC", "DELTA", "VERDICT", "REASON"})

    def test_neutral_parameters_are_neutral_and_pixel_exact(self):
        parameters = CorrectionParameters()
        candidate = execute_basic_correction(self.source, parameters).candidate_image
        evidence = evaluate_quality_evidence(self.source, candidate, parameters)
        self.assertTrue(np.array_equal(candidate, self.source))
        self.assertEqual(evidence.targeted_issue_improvement.verdict, EvidenceVerdict.NOT_APPLICABLE)
        self.assertEqual(evidence.net_benefit, QualityNetBenefit.NEUTRAL)
        self.assertFalse(evidence.targeted_gain)
        self.assertFalse(evidence.protected_damage)

    def test_opposite_parameters_cannot_both_improve_one_real_diagnosis(self):
        cases = ((self.source * 0.35, "exposure", .32),
                 (self.source * 0.35, "brightness", 8),
                 (self.source * .35 + 90, "contrast", 12),
                 (_lab_shift(self.source, b=8), "temperature", -8),
                 (_lab_shift(self.source, a=-8), "tint", 8))
        for pixels, name, value in cases:
            source = np.rint(pixels).astype(np.uint8)
            verdicts = []
            for direction in (value, -value):
                parameters = CorrectionParameters(**{name: direction})
                candidate = execute_basic_correction(source, parameters).candidate_image
                evidence = evaluate_quality_evidence(source, candidate, parameters)
                verdicts.append(evidence.targeted_issue_improvement.verdict)
            self.assertEqual(verdicts[0], EvidenceVerdict.PASS, (name, verdicts))
            self.assertNotEqual(verdicts[1], EvidenceVerdict.PASS, (name, verdicts))

    def test_supporting_parameter_does_not_require_another_diagnosed_issue(self):
        source = np.rint(self.source * .35).astype(np.uint8)
        parameters = CorrectionParameters(exposure=.16, brightness=4)
        candidate = execute_basic_correction(source, parameters).candidate_image
        evidence = evaluate_quality_evidence(source, candidate, parameters)
        self.assertEqual(evidence.targeted_issue_improvement.verdict, EvidenceVerdict.PASS)
        issue = evidence.targeted_issue_improvement.candidate_metric["ISSUES"][0]
        self.assertEqual(issue["PRIMARY_PARAMETER"], "exposure")
        self.assertEqual(issue["SUPPORTING_PARAMETER"], ["brightness"])

    def test_saturation_vibrance_highlights_shadows_follow_diagnosed_error(self):
        from tests.color_correction.run_d60_03_real_decision_validation import _cases
        cases, _ = _cases()
        for index, name, value in ((9, "saturation", -12), (9, "vibrance", -16), (12, "highlights", -6), (13, "shadows", 6)):
            source = cases[index].pixels
            for sign in (1, -1):
                parameters = CorrectionParameters(**{name: value * sign})
                candidate = execute_basic_correction(source, parameters).candidate_image
                evidence = evaluate_quality_evidence(source, candidate, parameters)
                if sign == 1:
                    self.assertEqual(evidence.net_benefit, QualityNetBenefit.POSITIVE, name)
                else:
                    self.assertNotEqual(evidence.targeted_issue_improvement.verdict, EvidenceVerdict.PASS, name)

    def test_unsupported_or_missing_diagnosis_is_not_positive(self):
        parameters = CorrectionParameters(exposure=.16)
        candidate = execute_basic_correction(self.source, parameters).candidate_image
        evidence = evaluate_quality_evidence(self.source, candidate, parameters)
        self.assertTrue(evidence.targeted_issue_improvement.delta["UNSUPPORTED_ADJUSTMENT"])
        self.assertEqual(evidence.net_benefit, QualityNetBenefit.INCONCLUSIVE)
        missing = _evaluate(self.source, candidate, parameters)
        self.assertEqual(missing.targeted_issue_improvement.verdict, EvidenceVerdict.INCONCLUSIVE)
        self.assertEqual(missing.format_integrity.verdict, EvidenceVerdict.INCONCLUSIVE)

    def test_fourteen_directionally_plausible_degradations_do_not_pass(self):
        source = self.source
        brighter_clip = source.copy()
        brighter_clip[brighter_clip >= 170] = 255
        darker_crush = source.copy()
        darker_crush[darker_crush <= 90] = 0
        contrast_clip = np.where(source < 110, 0, np.where(source > 150, 255, source)).astype(np.uint8)
        yellow_cast = _lab_shift(source, b=42.0)
        magenta_cast = _lab_shift(source, a=42.0)
        over_saturated = _saturation(source, 1.0)
        desaturated = _saturation(source, 0.0)
        vibrance_saturation = _saturation(_lab_shift(source, a=12.0, b=12.0), 1.0)
        highlight_conflict = np.clip(source.astype(np.int16) + 45, 0, 255).astype(np.uint8)
        highlight_conflict[highlight_conflict >= 220] = 255
        shadow_conflict = np.clip(source.astype(np.float32) * 0.42 + 105.0, 0, 255).astype(np.uint8)
        skin_damage = source.copy()
        skin_damage[24:104, 16:96] = _lab_shift(skin_damage[24:104, 16:96], a=35.0, b=-30.0)
        brand_drift = source.copy()
        brand_drift[24:104, 160:240] = (40, 205, 70)
        posterized = (np.rint(source.astype(np.float32) / 32.0) * 32.0).clip(0, 255).astype(np.uint8)
        no_gain = source.copy()
        no_gain[:, ::2] = np.clip(no_gain[:, ::2].astype(np.int16) + 1, 0, 255).astype(np.uint8)
        cases = (
            ("highlight_blowout", brighter_clip, {"exposure": 0.32}),
            ("shadow_crush", darker_crush, {"exposure": -0.32}),
            ("contrast_endpoint_clip", contrast_clip, {"contrast": 12.0}),
            ("temperature_overdrive", yellow_cast, {"temperature": 8.0}),
            ("tint_overdrive", magenta_cast, {"tint": 8.0}),
            ("saturation_too_high", over_saturated, {"saturation": 12.0}),
            ("saturation_too_low", desaturated, {"saturation": -12.0}),
            ("vibrance_saturation_stack", vibrance_saturation, {"vibrance": 16.0, "saturation": 12.0}),
            ("highlight_exposure_conflict", highlight_conflict, {"highlights": -12.0, "exposure": 0.32}),
            ("shadow_contrast_conflict", shadow_conflict, {"shadows": 12.0, "contrast": 12.0}),
            ("skin_damage", skin_damage, {"tint": 8.0}),
            ("brand_hue_drift", brand_drift, {"saturation": 12.0}),
            ("gradient_banding", posterized, {"contrast": 12.0}),
            ("pixel_change_without_gain", no_gain, {"brightness": 4.0}),
        )
        self.assertEqual(len(cases), 14)
        for name, candidate, values in cases:
            with self.subTest(case=name):
                evidence = self.evaluate(candidate, **values)
                expected = QualityNetBenefit.INCONCLUSIVE if name == "pixel_change_without_gain" else QualityNetBenefit.NEGATIVE
                self.assertEqual(evidence.net_benefit, expected, (name, evidence.to_record()))

    def test_specific_degradation_dimensions_are_explainable(self):
        clipped = self.source.copy()
        clipped[clipped >= 170] = 255
        clipping = self.evaluate(clipped, exposure=0.32)
        self.assertEqual(clipping.clipping_delta.verdict, EvidenceVerdict.FAIL)
        self.assertEqual(clipping.highlight_quality.verdict, EvidenceVerdict.FAIL)

        cast = self.evaluate(_lab_shift(self.source, a=-45.0), tint=-8.0)
        self.assertEqual(cast.color_cast_quality.verdict, EvidenceVerdict.FAIL)

        saturated = self.evaluate(_saturation(self.source, 1.0), saturation=12.0)
        self.assertTrue(
            saturated.saturation_quality.verdict == EvidenceVerdict.FAIL
            or saturated.channel_saturation_risk.verdict == EvidenceVerdict.FAIL
        )

        posterized = (np.rint(self.source.astype(np.float32) / 32.0) * 32.0).clip(0, 255).astype(np.uint8)
        banding = self.evaluate(posterized, contrast=12.0)
        self.assertEqual(banding.posterization_risk.verdict, EvidenceVerdict.FAIL)
        self.assertEqual(banding.banding_risk.verdict, EvidenceVerdict.FAIL)

    def test_quality_evidence_is_deterministic_and_does_not_mutate_pixels(self):
        parameters = CorrectionParameters(temperature=-8.0, saturation=8.0)
        candidate = execute_basic_correction(self.source, parameters).candidate_image
        source_before = self.source.copy()
        candidate_before = candidate.copy()
        first = evaluate_quality_evidence(self.source, candidate, parameters)
        second = evaluate_quality_evidence(self.source, candidate, parameters)
        self.assertEqual(first.to_record(), second.to_record())
        self.assertTrue(np.array_equal(source_before, self.source))
        self.assertTrue(np.array_equal(candidate_before, candidate))

    def test_d3_consumes_quality_evidence_after_independent_replay(self):
        underexposed = np.clip(np.rint(self.source.astype(np.float32) * 0.35), 0, 255).astype(np.uint8)
        decision = analyze_color_usability(underexposed, person_regions=())
        parameter_decision = decide_correction_parameters(build_objective_diagnosis(decision))
        bind_parameter_decision(decision, parameter_decision)
        audit = audit_candidate(underexposed, decision, person_regions=())
        self.assertEqual(audit.status, "AUDIT_COMPLETE")
        self.assertIn("QUALITY_EVIDENCE", audit.audit_metrics)
        self.assertEqual(audit.audit_metrics["QUALITY_EVIDENCE"]["PARAMETER_DECISION_DIGEST"], parameter_decision.decision_digest)
        self.assertEqual(audit.audit_metrics["basic_correction_replay"]["PASS_STATUS"]["REPLAY_PASS"], "YES")

    def test_four_real_quality_outcomes_flow_through_audit_candidate(self):
        source = np.rint(self.source * .35).astype(np.uint8)
        photo_path = Path(__file__).resolve().parents[2] / "output/evaluation/d01_color_decision_20260812/inputs/D01_04.png"
        with Image.open(photo_path) as image:
            photo = np.array(image.convert("RGB"))
        cases = (
            (photo, .32, True, "POSITIVE", "ACCEPT_CORRECTED"),
            (photo, .01, True, "NEUTRAL", "ACCEPT_ORIGINAL"),
            (source, 1.5, True, "NEGATIVE", "ACCEPT_ORIGINAL"),
            (photo, .32, False, "INCONCLUSIVE", "REVIEW_REQUIRED"),
        )
        for pixels, value, format_known, benefit, action in cases:
            with self.subTest(benefit=benefit):
                audit = explicit_parameter_audit(pixels, CorrectionParameters(exposure=value), format_known=format_known)
                self.assertEqual(audit.status, "AUDIT_COMPLETE", audit.to_record())
                self.assertEqual(audit.audit_metrics["QUALITY_EVIDENCE"]["NET_BENEFIT"], benefit)
                self.assertEqual(audit.final_action.value, action)
                self.assertEqual(audit.audit_metrics["basic_correction_replay"]["PASS_STATUS"]["REPLAY_PASS"], "YES")

    def test_positive_quality_does_not_override_existing_d3_protection(self):
        source = np.rint(self.source * .35).astype(np.uint8)
        audit = explicit_parameter_audit(source, CorrectionParameters(exposure=.32))
        self.assertEqual(audit.audit_metrics["QUALITY_EVIDENCE"]["NET_BENEFIT"], "POSITIVE")
        self.assertEqual(audit.pass_status["SKIN_PASS"], "NO")
        self.assertEqual(audit.final_action.value, "ACCEPT_ORIGINAL")

    def test_banding_can_fail_independently_of_global_posterization(self):
        for tint in ((0, 0, 0), (-30, 0, 25), (25, -10, -20)):
            source = np.clip(self.source.astype(np.int16) + tint, 0, 255).astype(np.uint8)
            candidate = source.copy()
            candidate[120:150] = (candidate[120:150] // 16) * 16
            evidence = evaluate_quality_evidence(source, candidate, CorrectionParameters(contrast=12))
            self.assertEqual(evidence.posterization_risk.verdict, EvidenceVerdict.PASS)
            self.assertEqual(evidence.banding_risk.verdict, EvidenceVerdict.FAIL)

    def test_native_flat_colors_text_and_logo_edges_are_not_banding(self):
        source = np.full((256, 256, 3), 220, dtype=np.uint8)
        source[24:90, 20:200] = (200, 20, 40)
        source[130:220:8, 30:240] = 10
        source[130:220, 30:240:16] = 10
        candidate = execute_basic_correction(source, CorrectionParameters(contrast=12)).candidate_image
        evidence = evaluate_quality_evidence(source, candidate, CorrectionParameters(contrast=12))
        self.assertEqual(evidence.banding_risk.verdict, EvidenceVerdict.NOT_APPLICABLE)

    def test_format_uses_expected_contract_not_source_equality(self):
        params = CorrectionParameters()
        for expected, actual, verdict in (("PNG", "PNG", EvidenceVerdict.PASS), ("PNG", "JPEG", EvidenceVerdict.FAIL), (None, None, EvidenceVerdict.INCONCLUSIVE)):
            evidence = _evaluate(self.source, self.source, params, source_format="JPEG", expected_output_format=expected, candidate_format=actual)
            self.assertEqual(evidence.format_integrity.verdict, verdict)


if __name__ == "__main__":
    unittest.main()
