"""D60-05 retained real-file core experiment, not a formal Result/Delivery run.

Usage: python -B tests/color_correction/run_d60_05_real_reference_validation.py
       --output <new external evidence directory>
       --baseline-package <fixed D60-05A human-review package>  # D60-05B
Controlled derivatives are labeled. They prepare test stimuli only; every
candidate uses the frozen executor once with the recorded matching decision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from engine.color_correction.color_management import (
    encode_color_managed_candidate, load_color_managed_source,
    srgb_profile_bytes, verify_color_managed_output,
)
from engine.color_correction.executors.basic_correction import execute_basic_correction
from engine.color_correction.objective_diagnosis import build_objective_diagnosis
from engine.color_correction.parameters import CorrectionParameters
from engine.color_correction.quality_evidence import evaluate_quality_evidence
from engine.color_correction.reference_matching import (
    POLICY, decide_reference_matching, load_target_color_profile, load_reference_color_target,
)
from engine.color_correction.usability_decision import analyze_color_usability

INPUTS = ROOT / "output/evaluation/d01_color_decision_20260812/inputs"
FIXTURES = ROOT / "tests/fixtures/color_correction/d60_03r"
POSTER = ROOT / "output/g_line_final_benchmark_20260901/assets/normal_commercial_poster.png"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


@dataclass(frozen=True)
class Pair:
    name: str
    category: str
    target: Path
    reference: Path
    protected: tuple[str, ...] = ()
    expected_insufficient: bool = False


def prepare_pairs(out):
    inputs = out / "inputs"
    inputs.mkdir()
    sources = {f"{n:02}": INPUTS / (f"D01_{n:02}.jpg" if n == 1 else f"D01_{n:02}.png")
               for n in range(1, 16)}
    sources.update(landscape=FIXTURES / "real_mountain_lake_landscape.jpg",
                   sunset=FIXTURES / "real_sunset_landscape.jpg", poster=POSTER)
    hashes = {str(p): sha(p) for p in sources.values()}
    provenance = {}
    # This legacy real photograph is mode L, which the frozen formal loader
    # rejects. Explicit RGB test-copy preparation is NOT a runtime fallback.
    landscape_path = inputs / "landscape_explicit_rgb_test_copy.png"
    with Image.open(sources["landscape"]) as im:
        ImageOps.exif_transpose(im).convert("RGB").save(landscape_path, icc_profile=srgb_profile_bytes())
    provenance[str(landscape_path)] = {"SOURCE": str(sources["landscape"]),
                                     "TRANSFORM": "explicit grayscale-to-RGB test copy; original unchanged"}
    sources["landscape_rgb"] = landscape_path

    def derivative(key, name, parameters):
        source = load_color_managed_source(sources[key])
        candidate = execute_basic_correction(source.pixels, CorrectionParameters(**parameters))
        path = inputs / (name + (".jpg" if source.source_format == "JPEG" else ".png"))
        encoded = encode_color_managed_candidate(candidate.candidate_image, source)
        verify_color_managed_output(encoded, candidate.candidate_image, source)
        path.write_bytes(encoded)
        provenance[str(path)] = {"SOURCE": str(sources[key]), "TRANSFORM": "CONTROLLED_TEST_STIMULUS",
                                 "PARAMETERS": candidate.parameter_record}
        return path

    landscape_warm = derivative("landscape_rgb", "landscape_warm", {"temperature": 28, "brightness": 12})
    night_lift = derivative("15", "night_lift", {"shadows": 30, "saturation": -22})
    strong_warm = derivative("02", "portrait_strong_warm", {"temperature": 55})
    strong_cool = derivative("03", "portrait_strong_cool", {"temperature": -55})
    low_sat = derivative("01", "portrait_low_sat", {"saturation": -45})
    high_sat = derivative("01", "portrait_high_sat", {"saturation": 45})
    low_contrast = derivative("12", "indoor_low_contrast", {"contrast": -65})
    green = derivative("01", "portrait_green", {"tint": -48})
    magenta = derivative("01", "portrait_magenta", {"tint": 48})
    mild_green = derivative("12", "indoor_mild_green", {"tint": -12})
    mild_magenta = derivative("12", "indoor_mild_magenta", {"tint": 12})
    tails = derivative("12", "indoor_tail_reference", {"highlights": -42, "shadows": 38})
    product_high_sat = derivative("09", "product_high_sat", {"saturation": 50})
    # Explicit destructive reference fixtures; never candidate/fallback code.
    source_rgb = load_color_managed_source(sources["01"]).pixels[..., :3]
    clipped = inputs / "severely_clipped_reference.png"
    Image.fromarray(np.clip(source_rgb.astype(np.int16) + 170, 0, 255).astype(np.uint8)).save(clipped)
    provenance[str(clipped)] = {"SOURCE": str(sources["01"]), "TRANSFORM": "controlled +170 channel clipping counterexample"}
    stage = inputs / "special_mixed_stage_lighting.png"
    stage_pixels = source_rgb.copy()
    midpoint = stage_pixels.shape[1] // 2
    stage_pixels[:, :midpoint, 1:] //= 4
    stage_pixels[:, midpoint:, :2] //= 4
    Image.fromarray(stage_pixels).save(stage)
    provenance[str(stage)] = {"SOURCE": str(sources["01"]), "TRANSFORM": "controlled red/blue split special-lighting counterexample"}
    monochrome = inputs / "extreme_monochrome.png"
    mono = source_rgb.copy()
    mono[..., 1:] //= 12
    Image.fromarray(mono).save(monochrome)
    provenance[str(monochrome)] = {"SOURCE": str(sources["01"]), "TRANSFORM": "controlled extreme monochrome counterexample"}
    pairs = [
        Pair("01_portrait", "portrait -> portrait", sources["01"], sources["02"], ("skin",)),
        Pair("02_product", "product -> product", sources["09"], sources["10"], ("product", "brand")),
        Pair("03_landscape", "landscape -> landscape", landscape_path, landscape_warm),
        Pair("04_indoor", "indoor -> indoor", sources["12"], sources["13"], ("neutral",)),
        Pair("05_night", "night -> night", sources["15"], night_lift, ("skin", "shadow")),
        Pair("06_cool_to_warm", "cool -> warm reference", sources["03"], sources["02"], ("skin",)),
        Pair("07_warm_to_cool", "warm -> cool reference", sources["02"], sources["03"], ("skin",)),
        Pair("08_low_to_high_saturation", "low -> high saturation", low_sat, high_sat, ("skin",)),
        Pair("09_high_to_restrained", "high -> restrained saturation", high_sat, low_sat, ("skin",)),
        Pair("10_contrast", "low -> high contrast", low_contrast, sources["12"], ("neutral",)),
        Pair("11_skin_strong_warm", "portrait + strong warm reference", sources["01"], strong_warm, ("skin",)),
        Pair("12_skin_strong_cool", "portrait + strong cool reference", sources["01"], strong_cool, ("skin",)),
        Pair("13_brand_strong_color", "brand + strong-color reference", sources["10"], sources["02"], ("brand", "product", "neutral")),
        Pair("14_chinese_poster", "Chinese poster + color reference", sources["poster"], sources["13"], ("brand", "text")),
        Pair("15_product_saturation", "product true color + high saturation", sources["09"], product_high_sat, ("brand", "product")),
        Pair("16_day_to_dark_night", "day product + extreme dark night", sources["09"], sources["15"], ("product", "brand")),
        Pair("17_special_lighting", "normal + extreme mixed lighting", sources["01"], stage, ("skin",), True),
        Pair("18_severe_clip", "normal + severely clipped reference", sources["01"], clipped, ("skin",), True),
        Pair("19_green_to_magenta", "green -> magenta reference", green, magenta, ("skin",)),
        Pair("20_magenta_to_green", "magenta -> green reference", magenta, green, ("skin",)),
        Pair("21_underexposed", "underexposed -> healthy portrait", sources["04"], sources["01"], ("skin",)),
        Pair("22_highlight_shadow", "highlights/shadows residual matching", sources["12"], tails, ("neutral",)),
        Pair("23_extreme_monochrome", "normal + extreme monochrome", sources["01"], monochrome, ("skin",), True),
        Pair("24_tint_positive", "moderate green -> magenta", mild_green, mild_magenta, ("neutral",)),
        Pair("25_tint_negative", "moderate magenta -> green", mild_magenta, mild_green, ("neutral",)),
    ]
    write_json(out / "input_provenance.json", {
        "ORIGINAL_SHA256": hashes, "DERIVATIVES": provenance,
        "SOURCE_NOTE": "D01 commercial visual files retained in repository; camera provenance unverified. Landscape is retained real photograph. No synthetic array-only evidence.",
    })
    return pairs, hashes


def panel(path, label, width=400, height=300):
    # Respect the same input ICC/orientation contract in the visual evidence.
    managed = load_color_managed_source(path)
    image = ImageOps.contain(Image.fromarray(managed.pixels).convert("RGB"), (width, height))
    cell = Image.new("RGB", (width, height + 26), "#242832")
    cell.paste(image, ((width-image.width)//2, 26+(height-image.height)//2))
    ImageDraw.Draw(cell).text((8, 5), label, fill="white")
    return cell


def prepare_fixed_pairs(package):
    """Use A's exact encoded assets, not newly regenerated stimulus images."""
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pairs, baselines, hashes = [], {}, {str(manifest_path): sha(manifest_path)}
    for entry in manifest["PAIRS"]:
        paths = {}
        for role in ("TARGET", "REFERENCE", "CANDIDATE", "ORIGINAL_EVIDENCE"):
            path = (package / entry[role]["PACKAGED_PATH"]).resolve(strict=True)
            if not path.is_relative_to(package) or sha(path) != entry[role]["SHA256"]:
                raise ValueError("FIXED_A_ASSET_INTEGRITY_FAILURE")
            hashes[str(path)] = entry[role]["SHA256"]
            paths[role] = path
        old = json.loads(paths["ORIGINAL_EVIDENCE"].read_text(encoding="utf-8"))
        name = entry["PAIR_ID"]
        if name != Path(name).name or name in baselines:
            raise ValueError("FIXED_A_PAIR_ID_INVALID")
        pairs.append(Pair(name, entry["CATEGORY"], paths["TARGET"], paths["REFERENCE"],
                          tuple(entry["PROTECTED_CONTENT"]), old["EXPECTED_INSUFFICIENT"]))
        baselines[name] = {"entry": entry, "evidence": old, "candidate": paths["CANDIDATE"]}
    return pairs, hashes, baselines


def execute_pair(pair, out, baseline=None):
    directory = out / pair.name
    directory.mkdir()
    before = {str(p): sha(p) for p in (pair.target, pair.reference)}
    target = load_target_color_profile(pair.target)
    reference = load_reference_color_target(pair.reference)
    decision = decide_reference_matching(target, reference)
    if pair.expected_insufficient and decision.status != "INSUFFICIENT_EVIDENCE":
        raise AssertionError("KNOWN_UNSAFE_REFERENCE_WAS_NOT_REJECTED")
    source = load_color_managed_source(pair.target)
    # Bind the execution source back to the independently analyzed target.
    observations = analyze_color_usability(source.pixels)
    if observations.source_fingerprint != target.source.source_fingerprint:
        raise ValueError("TARGET_CHANGED_BETWEEN_DIAGNOSIS_AND_EXECUTION")
    result = execute_basic_correction(source.pixels, decision.parameters)
    replay_source = load_color_managed_source(pair.target)
    replay_parameters = CorrectionParameters.from_record(json.loads(json.dumps(result.parameter_record)))
    replay = execute_basic_correction(replay_source.pixels, replay_parameters)
    if not np.array_equal(result.candidate_image, replay.candidate_image):
        raise AssertionError("INDEPENDENT_CORE_REPLAY_MISMATCH")
    output_file = directory / ("candidate.jpg" if source.source_format == "JPEG" else "candidate.png")
    encoded = encode_color_managed_candidate(result.candidate_image, source)
    verify_color_managed_output(encoded, result.candidate_image, source)
    output_file.write_bytes(encoded)
    # Exact pre-encoding candidate retained separately for diagnosing JPEG loss.
    Image.fromarray(result.candidate_image).save(directory / "candidate_pixels.png")
    qe = evaluate_quality_evidence(
        source.pixels, result.candidate_image, decision.parameters,
        objective_diagnosis=build_objective_diagnosis(observations),
        source_format=source.source_format, candidate_format=source.source_format,
        expected_output_format=source.source_format,
    ).to_record()
    after_profile = load_target_color_profile(output_file)
    actual_values = after_profile.values()
    encoded_pixels = load_color_managed_source(output_file).pixels
    encoded_qe = evaluate_quality_evidence(
        source.pixels, encoded_pixels, decision.parameters,
        objective_diagnosis=build_objective_diagnosis(observations),
        source_format=source.source_format, candidate_format=source.source_format,
        expected_output_format=source.source_format,
    ).to_record()
    directions = {}
    for item in decision.dimensions:
        if item.final_parameter == 0:
            continue
        actual_delta = actual_values[item.name] - item.source_value
        # Whole-combination encoded-output metric, not parameter-sign tautology.
        directions[item.name] = {
            "SOURCE": item.source_value, "REFERENCE": item.reference_value,
            "CANDIDATE": actual_values[item.name], "ACTUAL_DELTA": actual_delta,
            "TOWARD_REFERENCE": actual_delta * item.raw_delta > 0,
            "OVERSHOOT": abs(actual_delta) > abs(item.raw_delta) + POLICY[item.name][2],
        }
    if before != {str(p): sha(p) for p in (pair.target, pair.reference)}:
        raise AssertionError("INPUT_FILE_MUTATED")
    comparison = [(pair.target, pair.name+" TARGET"), (pair.reference, "REFERENCE")]
    ab = {}
    if baseline:
        old = baseline["evidence"]
        for name, current in (("TARGET_PROFILE", target), ("REFERENCE_PROFILE", reference)):
            # A's analysis must describe these same source bytes and frozen
            # diagnostic facts. A path relocation alone is not a source change.
            prefix = "TARGET" if name == "TARGET_PROFILE" else "REFERENCE"
            old_profile = old[name]
            if (old_profile[prefix+"_SOURCE"]["ENCODED_SHA256"] != current.source.encoded_sha256
                    or old_profile["OBJECTIVE_DIAGNOSIS"] != current.diagnosis):
                raise AssertionError("A_TO_B_INPUT_OR_DIAGNOSTIC_DRIFT")
        a_profile = load_target_color_profile(baseline["candidate"])
        a_values = a_profile.values()
        a_pixels = load_color_managed_source(baseline["candidate"]).pixels
        a_parameters = CorrectionParameters.from_record(old["CORRECTION_PARAMETERS"])
        a_encoded_qe = evaluate_quality_evidence(
            source.pixels, a_pixels, a_parameters,
            objective_diagnosis=build_objective_diagnosis(observations),
            source_format=source.source_format, candidate_format=source.source_format,
            expected_output_format=source.source_format,
        ).to_record()
        axes = {}
        for item in decision.dimensions:
            raw = item.raw_delta
            a_error = abs(item.reference_value - a_values[item.name])
            b_error = abs(item.reference_value - actual_values[item.name])
            axes[item.name] = {
                "SOURCE": item.source_value, "REFERENCE": item.reference_value,
                "A_ENCODED": a_values[item.name], "B_ENCODED": actual_values[item.name],
                "RAW_DELTA": raw, "A_ERROR": a_error, "B_ERROR": b_error,
                "A_PROGRESS": (a_values[item.name] - item.source_value) / raw if raw else None,
                "B_PROGRESS": (actual_values[item.name] - item.source_value) / raw if raw else None,
                "B_CLOSER_THAN_A": b_error < a_error,
            }
        ab = {
            "PAIR_ID": pair.name, "A_CANDIDATE": str(baseline["candidate"]),
            "A_CANDIDATE_SHA256": sha(baseline["candidate"]),
            "A_PARAMETERS": old["CORRECTION_PARAMETERS"],
            "B_PARAMETERS": decision.parameters.to_record(),
            "A_LIMIT_REASONS": baseline["entry"]["LIMIT_REASONS"],
            "B_LIMIT_REASONS": {"GLOBAL": list(decision.reasons),
                                "BY_PARAMETER": {i.name: list(i.limit_reasons) for i in decision.dimensions}},
            "A_MATCH_STATUS": old["REFERENCE_MATCH_STATUS"], "B_MATCH_STATUS": decision.status,
            "AXES": axes, "A_ENCODED_QUALITY_EVIDENCE": a_encoded_qe,
            "A_B_PARAMETERS_IDENTICAL": a_parameters == decision.parameters,
            "A_B_ENCODED_PIXELS_IDENTICAL": np.array_equal(a_pixels, encoded_pixels),
            "A_B_MEAN_ABSOLUTE_PIXEL_DELTA": float(np.abs(a_pixels.astype(float) - encoded_pixels).mean()),
            "INPUT_AND_DIAGNOSIS_IDENTICAL": True,
        }
        comparison.append((baseline["candidate"], "D60-05A ENCODED CANDIDATE"))
    comparison.append((output_file, "D60-05B ENCODED CANDIDATE" if baseline else "ENCODED CANDIDATE"))
    width, height = (600, 720) if baseline else (400, 300)
    preview = Image.new("RGB", (width*len(comparison), height+26), "#242832")
    for i, (path, label) in enumerate(comparison):
        preview.paste(panel(path, label, width, height), (i*width, 0))
    preview.save(directory / "comparison.png", icc_profile=srgb_profile_bytes())
    record = {
        "CATEGORY": pair.category, "TARGET_FILE": str(pair.target), "REFERENCE_FILE": str(pair.reference),
        **decision.to_record(), "CANDIDATE": str(output_file), "CANDIDATE_SHA256": sha(output_file),
        "EXECUTOR": result.to_record(), "INDEPENDENT_CORE_REPLAY": "EXACT",
        "FORMAL_ENCODING_CONTRACT": "VERIFIED_NOT_REGISTERED_AS_RESULT",
        "D60_04_QUALITY_EVIDENCE": qe,
        "ENCODED_QUALITY_EVIDENCE": encoded_qe, "A_B_COMPARISON": ab,
        "D60_04_SCOPE": "EXPERIMENTAL_UNCHANGED_AUTO_CORRECTION_GATE_NOT_REFERENCE_INTENT_AUTHORITY",
        "ENCODED_OUTPUT_DIRECTIONS": directions, "EXPECTED_INSUFFICIENT": pair.expected_insufficient,
        "PROTECTED_CONTENT": pair.protected, "SOURCE_HASHES_UNCHANGED": before,
        "VISUAL_RESULT": {"HUMAN_REVIEW": "PENDING", "ASSISTANT_IMAGE_INSPECTION": "PENDING"},
    }
    write_json(directory / "evidence.json", record)
    return record, preview


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-package", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.is_relative_to(ROOT):
        raise ValueError("Evidence output must be outside the protected repository")
    out.mkdir(parents=True, exist_ok=False)
    watched = sorted((ROOT / "engine/color_correction").rglob("*.py"))
    watched += [Path(__file__).resolve(), ROOT / "tests/color_correction/test_d60_05_reference_matching.py"]
    before = {str(p): sha(p) for p in watched}
    if args.baseline_package:
        pairs, source_hashes, baselines = prepare_fixed_pairs(args.baseline_package.resolve(strict=True))
        write_json(out / "input_provenance.json", {
            "FIXED_A_PACKAGE": str(args.baseline_package.resolve()),
            "FIXED_A_SHA256": source_hashes, "REGENERATED_INPUTS": False,
        })
    else:
        pairs, source_hashes = prepare_pairs(out)
        baselines = {}
    records, previews, failures = [], [], []
    for pair in pairs:
        try:
            record, preview = execute_pair(pair, out, baselines.get(pair.name))
            records.append(record)
            previews.append(preview)
            print(pair.name, record["REFERENCE_MATCH_STATUS"], record["CORRECTION_PARAMETERS"]["values"], flush=True)
        except Exception as error:
            failure = {"PAIR": pair.name, "ERROR": f"{type(error).__name__}: {error}"}
            failures.append(failure)
            write_json(out / pair.name / "failure.json", failure)
            print(failure, flush=True)
    for index in range(0, len(previews), 4):
        batch = previews[index:index+4]
        w, h = batch[0].size
        sheet = Image.new("RGB", (w, h*len(batch)), "#242832")
        for row, im in enumerate(batch):
            sheet.paste(im, (0, row*h))
        sheet.save(out / f"review_sheet_{index//4+1:02}.png", icc_profile=srgb_profile_bytes())
    after = {str(p): sha(p) for p in watched}
    source_unchanged = all(sha(path) == digest for path, digest in source_hashes.items())
    directions = [v for r in records for v in r["ENCODED_OUTPUT_DIRECTIONS"].values()]
    write_json(out / "summary.json", {
        "PAIR_COUNT": len(records), "REQUESTED_PAIR_COUNT": len(pairs), "FAILURES": failures,
        "ACTIVE_DIMENSIONS": len(directions),
        "ENCODED_DIRECTION_CORRECT": sum(d["TOWARD_REFERENCE"] for d in directions),
        "ENCODED_OVERSHOOT_COUNT": sum(d["OVERSHOOT"] for d in directions),
        "CORE_DEPENDENCIES_BEFORE": before, "CORE_DEPENDENCIES_AFTER": after,
        "CORE_DEPENDENCIES_UNCHANGED": before == after, "ORIGINAL_FILES_UNCHANGED": source_unchanged,
        "HUMAN_VISUAL_REVIEW": "PENDING", "ASSISTANT_IMAGE_INSPECTION": "PENDING",
        "FORMAL_INTEGRATION": "NOT_PERFORMED_CORE_ONLY", "FINAL_FREEZE": "NOT_GRANTED",
    })
    if failures or before != after or not source_unchanged:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
