from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import cv2

from engine.color_correction import (
    D1Action,
    analyze_color_usability,
    analyze_color_usability_file,
    build_shadow_record,
)
from tests.color_correction.d1_replay_support import build_replay_image


def _analyze_png_round_trip(scene: np.ndarray, bits: int):
    maximum, dtype = (255, np.uint8) if bits == 8 else (65535, np.uint16)
    pixels = np.rint(scene * maximum).astype(dtype)
    ok, encoded = cv2.imencode(".png", pixels[..., ::-1])
    if not ok:
        raise AssertionError(f"failed to encode {bits}-bit PNG")
    decoded = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    if decoded is None or decoded.dtype != dtype:
        raise AssertionError(f"failed to preserve {bits}-bit PNG dtype")
    return analyze_color_usability(decoded, input_order="BGR", person_regions=[])


def _load_authoritative_d01_dataset(root: Path) -> dict[str, tuple[Path, dict[str, object]]]:
    evaluation = root / "output" / "evaluation" / "d01_color_decision_20260812"
    authority = evaluation / "candidate_v6_summary.json"
    if not authority.is_file():
        raise AssertionError(f"authoritative D1 labels are missing: {authority}")
    try:
        rows = json.loads(authority.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AssertionError(f"authoritative D1 labels are unreadable: {authority}") from exc
    expected = {f"D01_{index:02d}" for index in range(1, 16)}
    samples = [str(item.get("sample") or "") for item in rows]
    if len(samples) != len(expected) or set(samples) != expected:
        raise AssertionError("authoritative D1 labels must contain D01_01 through D01_15 exactly once")
    for row in rows:
        if not str(row.get("decision") or "") or not str(row.get("source_sha256") or ""):
            raise AssertionError(f"authoritative D1 label is incomplete: {row.get('sample')}")

    dataset: dict[str, tuple[Path, dict[str, object]]] = {}
    inputs = evaluation / "inputs"
    for row in rows:
        sample = str(row["sample"])
        sources = [path for extension in (".jpg", ".jpeg", ".png") if (path := inputs / f"{sample}{extension}").is_file()]
        if len(sources) != 1:
            raise AssertionError(f"authoritative D1 image must exist exactly once: {sample}")
        source = sources[0]
        try:
            payload = source.read_bytes()
            decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        except OSError as exc:
            raise AssertionError(f"authoritative D1 image is unreadable: {source}") from exc
        if decoded is None:
            raise AssertionError(f"authoritative D1 image is unreadable: {source}")
        if hashlib.sha256(payload).hexdigest() != row["source_sha256"]:
            raise AssertionError(f"authoritative D1 image hash does not match its label: {sample}")
        dataset[sample] = (source, row)
    return dataset


def _load_authoritative_d01_case(root: Path, sample: str) -> tuple[Path, dict[str, object]]:
    dataset = _load_authoritative_d01_dataset(root)
    if sample not in dataset:
        raise AssertionError(f"authoritative D1 label is missing: {sample}")
    source, row = dataset[sample]
    if "person" not in row or "local_light_contamination" not in row["person"]:
        raise AssertionError(f"authoritative D1 person label is incomplete: {sample}")
    return source, row


class ColorUsabilityDecisionTests(unittest.TestCase):
    def test_rgb_bgr_and_float_ranges_are_equivalent(self) -> None:
        rgb, _ = build_replay_image("yellow_cast")
        uint8 = np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8)
        by_rgb = analyze_color_usability(uint8, input_order="RGB")
        by_bgr = analyze_color_usability(uint8[..., ::-1], input_order="BGR")
        by_float = analyze_color_usability(uint8.astype(np.float32), input_order="RGB")
        self.assertEqual(by_rgb.color_status, by_bgr.color_status)
        self.assertEqual(by_rgb.color_status, by_float.color_status)
        self.assertEqual(by_rgb.d1_action, by_bgr.d1_action)
        self.assertEqual(by_rgb.d1_action, by_float.d1_action)

    def test_skin_is_never_neutral_evidence(self) -> None:
        image, regions = build_replay_image("person_skin")
        result = analyze_color_usability(image, person_regions=regions)
        self.assertFalse(result.skin_color_facts["used_as_neutral"])
        self.assertGreaterEqual(result.low_chroma_color_facts["skin_overlap_removed_ratio"], 0.0)

    def test_mixed_or_low_observability_never_auto_corrects(self) -> None:
        mixed, _ = build_replay_image("mixed_light")
        self.assertEqual(analyze_color_usability(mixed).d1_action, D1Action.REVIEW_REQUIRED)
        solid = np.full((64, 64, 3), (0.05, 0.2, 0.95), dtype=np.float32)
        self.assertNotEqual(analyze_color_usability(solid).d1_action, D1Action.AUTO_CORRECT)

    def test_high_chroma_spatial_mix_is_reviewed_without_neutral_pixels(self) -> None:
        image = np.empty((180, 240, 3), dtype=np.float32)
        image[:, :120] = (0.80, 0.12, 0.08)
        image[:, 120:] = (0.06, 0.18, 0.82)
        result = analyze_color_usability(image)
        self.assertEqual(result.spatial_color_facts["field_status"], "MIXED")
        self.assertEqual(result.d1_action, D1Action.REVIEW_REQUIRED)
        self.assertFalse(result.spatial_color_facts["local_correction_allowed"])

    def test_authoritative_d01_08_routes_local_person_color_risk_to_review(self) -> None:
        root = Path(__file__).resolve().parents[2]
        source, row = _load_authoritative_d01_case(root, "D01_08")
        self.assertEqual(row["decision"], "LOCAL_REQUIRED")
        self.assertTrue(row["person"]["local_light_contamination"])
        result = analyze_color_usability_file(source)
        self.assertEqual(result.color_status.value, "UNCERTAIN")
        self.assertEqual(result.scene_intent, "LOCAL_PERSON_COLOR_RISK")
        self.assertEqual(result.d1_action, D1Action.REVIEW_REQUIRED)
        self.assertIn("LOCAL_PERSON_COLOR_RISK", {item.code for item in result.conflict_evidence})

    def test_authoritative_yellow_and_blue_ground_truth_require_review_without_independent_evidence(self) -> None:
        root = Path(__file__).resolve().parents[2]
        dataset = _load_authoritative_d01_dataset(root)
        expectations = {"D01_02": "warm", "D01_03": "cool"}
        for sample, cast in expectations.items():
            with self.subTest(sample=sample):
                source, row = dataset[sample]
                self.assertEqual(row["decision"], "NORMAL")
                self.assertEqual(row["candidate_cast"], cast)
                self.assertEqual(row["cast"], cast)
                self.assertEqual(row["interpretation"], "global_error_cast")
                self.assertTrue(row["wb"])
                self.assertTrue(row["person"]["present"])
                self.assertFalse(row["person"]["local_light_contamination"])
                self.assertFalse(row["person"]["skin_color_risk"])

                result = analyze_color_usability_file(source)
                self.assertEqual(result.color_status.value, "UNCERTAIN")
                self.assertEqual(result.d1_action, D1Action.REVIEW_REQUIRED)
                self.assertFalse(result.correction_justification["auto_authorized"])
                self.assertEqual(
                    result.correction_justification["reason"],
                    "POST_ISP_APPEARANCE_CANNOT_SEPARATE_AMBIENT_LIGHT_FROM_ERROR_CAST",
                )

    def test_authoritative_normal_warm_person_scene_remains_protected(self) -> None:
        root = Path(__file__).resolve().parents[2]
        source, row = _load_authoritative_d01_case(root, "D01_13")
        self.assertEqual(row["decision"], "ORIGINAL")
        self.assertEqual(row["interpretation"], "legitimate_warm")
        self.assertEqual(row["scene_intent"], "legitimate_warm")
        self.assertFalse(row["wb"])

        result = analyze_color_usability_file(source)
        self.assertEqual(result.scene_intent, "LEGITIMATE_WARM")
        self.assertEqual(result.d1_action, D1Action.KEEP_ORIGINAL)
        self.assertFalse(result.correction_justification["auto_authorized"])

    def test_unanchored_post_isp_casts_do_not_gain_fake_reference_independence(self) -> None:
        for recipe in ("yellow_cast", "blue_cast"):
            with self.subTest(recipe=recipe):
                image, _ = build_replay_image(recipe)
                result = analyze_color_usability(image, person_regions=[])
                self.assertEqual(result.color_status.value, "UNCERTAIN")
                self.assertEqual(result.d1_action, D1Action.REVIEW_REQUIRED)
                self.assertFalse(result.correction_justification["auto_authorized"])
                self.assertEqual(result.correction_justification["independent_evidence_sources"], [])

    def test_authoritative_color_review_is_equivalent_after_real_8_and_16_bit_png_encoding(self) -> None:
        root = Path(__file__).resolve().parents[2]
        dataset = _load_authoritative_d01_dataset(root)
        for sample in ("D01_02", "D01_03"):
            with self.subTest(sample=sample):
                source, _ = dataset[sample]
                original = cv2.imdecode(np.frombuffer(source.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
                self.assertIsNotNone(original)
                rgb = original[..., ::-1].astype(np.float32) / 255.0
                results = []
                for bits, maximum, dtype in ((8, 255, np.uint8), (16, 65535, np.uint16)):
                    pixels = np.rint(rgb * maximum).astype(dtype)
                    ok, encoded = cv2.imencode(".png", pixels[..., ::-1])
                    self.assertTrue(ok)
                    decoded = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
                    self.assertEqual(decoded.dtype, dtype)
                    results.append(analyze_color_usability(decoded, input_order="BGR"))
                eight, sixteen = results
                self.assertEqual(eight.color_status, sixteen.color_status)
                self.assertEqual(eight.exposure_status, sixteen.exposure_status)
                self.assertEqual(eight.d1_action, sixteen.d1_action)
                self.assertEqual(eight.d1_action, D1Action.REVIEW_REQUIRED)

    def test_authoritative_d01_matrix_has_no_color_auto_action(self) -> None:
        root = Path(__file__).resolve().parents[2]
        dataset = _load_authoritative_d01_dataset(root)
        color_auto = {
            sample
            for sample, (source, _) in dataset.items()
            if (
                (decision := analyze_color_usability_file(source)).d1_action == D1Action.AUTO_CORRECT
                and decision.exposure_status.value == "PASS"
            )
        }
        self.assertEqual(color_auto, set())

    def test_authoritative_d01_missing_or_incomplete_resources_are_hard_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(AssertionError, "labels are missing"):
                _load_authoritative_d01_dataset(root)

            evaluation = root / "output" / "evaluation" / "d01_color_decision_20260812"
            inputs = evaluation / "inputs"
            inputs.mkdir(parents=True)
            rows = [
                {"sample": f"D01_{index:02d}", "decision": "KEEP", "source_sha256": "missing"}
                for index in range(1, 16)
            ]
            del rows[7]["decision"]
            (evaluation / "candidate_v6_summary.json").write_text(json.dumps(rows), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "label is incomplete: D01_08"):
                _load_authoritative_d01_dataset(root)

            rows[7]["decision"] = "LOCAL_REQUIRED"
            (evaluation / "candidate_v6_summary.json").write_text(json.dumps(rows), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "image must exist exactly once: D01_01"):
                _load_authoritative_d01_dataset(root)

            for index in range(1, 16):
                (inputs / f"D01_{index:02d}.png").write_bytes(b"not-an-image")
            with self.assertRaisesRegex(AssertionError, "image is unreadable"):
                _load_authoritative_d01_dataset(root)

    def test_equivalent_8_and_16_bit_png_keep_status_and_real_bit_depth(self) -> None:
        rgb, _ = build_replay_image("neutral_scene")
        equivalent_8 = np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8)
        equivalent_16 = equivalent_8.astype(np.uint16) * 257
        with tempfile.TemporaryDirectory() as temp_dir:
            eight_path = Path(temp_dir) / "equivalent_8.png"
            sixteen_path = Path(temp_dir) / "equivalent_16.png"
            ok8, encoded8 = cv2.imencode(".png", equivalent_8[..., ::-1])
            ok16, encoded16 = cv2.imencode(".png", equivalent_16[..., ::-1])
            self.assertTrue(ok8 and ok16)
            eight_path.write_bytes(encoded8.tobytes())
            sixteen_path.write_bytes(encoded16.tobytes())
            eight = analyze_color_usability_file(eight_path)
            sixteen = analyze_color_usability_file(sixteen_path)
        self.assertEqual(eight.image_facts["source_bit_depth_per_channel"], 8)
        self.assertEqual(sixteen.image_facts["source_bit_depth_per_channel"], 16)
        self.assertEqual(eight.color_status, sixteen.color_status)
        self.assertEqual(eight.exposure_status, sixteen.exposure_status)
        self.assertEqual(eight.d1_action, sixteen.d1_action)
        self.assertAlmostEqual(
            eight.image_facts["luminance_p50"],
            sixteen.image_facts["luminance_p50"],
            delta=0.01,
        )

    def test_real_8_and_16_bit_png_encodings_keep_decisions_equivalent(self) -> None:
        base, _ = build_replay_image("neutral_scene")
        scenes = {
            "warm_boundary": np.clip(base * np.asarray((1.04, 1.012, 0.928), dtype=np.float32), 0.0, 1.0),
            "cool_boundary": np.clip(base * np.asarray((0.928, 0.98, 1.04), dtype=np.float32), 0.0, 1.0),
            "neutral": base,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            for name, scene in scenes.items():
                with self.subTest(scene=name):
                    eight_pixels = np.rint(scene * 255.0).astype(np.uint8)
                    sixteen_pixels = np.rint(scene * 65535.0).astype(np.uint16)
                    eight_path = Path(temp_dir) / f"{name}_8.png"
                    sixteen_path = Path(temp_dir) / f"{name}_16.png"
                    ok8, encoded8 = cv2.imencode(".png", eight_pixels[..., ::-1])
                    ok16, encoded16 = cv2.imencode(".png", sixteen_pixels[..., ::-1])
                    self.assertTrue(ok8 and ok16)
                    eight_path.write_bytes(encoded8.tobytes())
                    sixteen_path.write_bytes(encoded16.tobytes())
                    eight = analyze_color_usability_file(eight_path)
                    sixteen = analyze_color_usability_file(sixteen_path)
                    self.assertEqual(eight.color_status, sixteen.color_status)
                    self.assertEqual(eight.exposure_status, sixteen.exposure_status)
                    self.assertEqual(eight.d1_action, sixteen.d1_action)

    def test_real_8_and_16_bit_png_continuous_warm_cool_sweeps_are_equivalent(self) -> None:
        base, _ = build_replay_image("neutral_scene")
        base = np.ascontiguousarray(base[::3, ::3])
        paths = {
            "warm": lambda t: (1.0 + 0.10 * t, 1.0 + 0.03 * t, 1.0 - 0.18 * t),
            "cool": lambda t: (1.0 - 0.18 * t, 1.0 - 0.05 * t, 1.0 + 0.10 * t),
        }
        for direction, gains_for in paths.items():
            actions: set[D1Action] = set()
            boundary_points = 0
            sweep = np.arange(0.10, 1.401, 0.01)
            for t in sweep:
                with self.subTest(direction=direction, t=round(float(t), 2)):
                    scene = np.clip(base * np.asarray(gains_for(float(t)), dtype=np.float32), 0.0, 1.0)
                    eight = _analyze_png_round_trip(scene, 8)
                    sixteen = _analyze_png_round_trip(scene, 16)
                    self.assertEqual(eight.color_status, sixteen.color_status)
                    self.assertEqual(eight.exposure_status, sixteen.exposure_status)
                    self.assertEqual(eight.d1_action, sixteen.d1_action)
                    actions.add(eight.d1_action)
                    boundary_points += int(bool(eight.color_appearance_evidence["boundary_unstable"]))
            self.assertIn(D1Action.KEEP_ORIGINAL, actions)
            self.assertIn(D1Action.REVIEW_REQUIRED, actions)
            self.assertNotIn(D1Action.AUTO_CORRECT, actions)
            self.assertGreater(boundary_points, 0)
            self.assertLess(boundary_points, len(sweep) * 0.25)

    def test_quantization_boundary_is_explicit_and_degrades_both_depths(self) -> None:
        base, _ = build_replay_image("neutral_scene")
        cases = {
            "warm": (0.255, lambda t: (1.0 + 0.10 * t, 1.0 + 0.03 * t, 1.0 - 0.18 * t)),
            "cool": (0.19, lambda t: (1.0 - 0.18 * t, 1.0 - 0.05 * t, 1.0 + 0.10 * t)),
        }
        for direction, (t, gains_for) in cases.items():
            scene = np.clip(base * np.asarray(gains_for(t), dtype=np.float32), 0.0, 1.0)
            for bits in (8, 16):
                with self.subTest(direction=direction, bits=bits):
                    result = _analyze_png_round_trip(scene, bits)
                    self.assertTrue(result.color_appearance_evidence["boundary_unstable"])
                    self.assertEqual(result.color_status.value, "UNCERTAIN")
                    self.assertEqual(result.d1_action, D1Action.REVIEW_REQUIRED)
                    self.assertIn(
                        "QUANTIZATION_BOUNDARY_UNSTABLE",
                        {item.code for item in result.conflict_evidence},
                    )

    def test_stable_normal_controls_remain_bounded(self) -> None:
        expectations = {
            "neutral_scene": ("NORMAL", D1Action.KEEP_ORIGINAL),
            "normal_warm": ("UNCERTAIN", D1Action.REVIEW_REQUIRED),
            "normal_cool": ("UNCERTAIN", D1Action.REVIEW_REQUIRED),
        }
        for recipe, (color_status, action) in expectations.items():
            scene, _ = build_replay_image(recipe)
            for bits in (8, 16):
                with self.subTest(recipe=recipe, bits=bits):
                    result = _analyze_png_round_trip(scene, bits)
                    self.assertFalse(result.color_appearance_evidence["boundary_unstable"])
                    self.assertEqual(result.color_status.value, color_status)
                    self.assertEqual(result.d1_action, action)

    def test_continuous_normal_warm_and_cool_sweeps_never_auto_correct(self) -> None:
        base, _ = build_replay_image("neutral_scene")
        paths = {
            "warm": lambda t: (1.0 + 0.10 * t, 1.0 + 0.03 * t, 1.0 - 0.18 * t),
            "cool": lambda t: (1.0 - 0.18 * t, 1.0 - 0.05 * t, 1.0 + 0.10 * t),
        }
        for direction, gains_for in paths.items():
            for t in np.arange(0.20, 1.41, 0.05):
                with self.subTest(direction=direction, t=round(float(t), 2)):
                    image = np.clip(base * np.asarray(gains_for(float(t)), dtype=np.float32), 0.0, 1.0)
                    result = analyze_color_usability(image)
                    self.assertNotEqual(result.d1_action, D1Action.AUTO_CORRECT)

    def test_post_isp_color_appearance_is_not_correction_justification(self) -> None:
        for recipe in ("yellow_cast", "blue_cast"):
            with self.subTest(recipe=recipe):
                image, _ = build_replay_image(recipe)
                result = analyze_color_usability(image).to_dict()
                self.assertNotEqual(result["color_appearance_evidence"]["direction"], "NEUTRAL")
                self.assertFalse(result["correction_justification"]["auto_authorized"])
                self.assertEqual(result["correction_justification"]["status"], "INSUFFICIENT")
                self.assertEqual(result["color_status"], "UNCERTAIN")
                self.assertEqual(result["d1_action"], "REVIEW_REQUIRED")
                self.assertIn(
                    "CORRECTION_JUSTIFICATION_MISSING",
                    {item["code"] for item in result["conflict_evidence"]},
                )

    def test_d2_contract_is_structured_and_contains_no_parameters(self) -> None:
        image, _ = build_replay_image("yellow_cast")
        result = analyze_color_usability(image).to_dict()
        required = {
            "color_observability", "spatial_color_facts", "illuminant_status",
            "dominant_color_risk", "support_evidence", "conflict_evidence",
            "confidence", "risk", "color_status", "exposure_status", "d1_action",
            "engine_version", "rule_version", "color_appearance_evidence",
            "correction_justification",
        }
        self.assertTrue(required.issubset(result))
        self.assertEqual(result["schema_version"], "hdde.color-usability.schema.v2")
        self.assertNotIn("correction_parameters", result)
        self.assertNotIn("local_color_field", result)
        self.assertNotIn("trusted_color_reference", result)
        self.assertNotIn("color_auto_authorization", result)

    def test_shadow_record_excludes_paths_images_and_identity(self) -> None:
        image, _ = build_replay_image("neutral_scene")
        record = build_shadow_record(analyze_color_usability(image), source_token="replay-neutral")
        encoded = json.dumps(record, ensure_ascii=False).lower()
        self.assertNotIn("source_path", encoded)
        self.assertEqual(record["privacy"], {
            "original_image_saved": False,
            "filesystem_path_saved": False,
            "person_identity_saved": False,
        })
        self.assertIn("correction_justification", record["d1_evidence"])
        self.assertNotIn("trusted_color_reference", record["d1_evidence"])
        self.assertNotIn("color_auto_authorization", record["d1_evidence"])


if __name__ == "__main__":
    unittest.main()
