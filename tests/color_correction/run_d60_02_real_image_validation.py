"""Real-image validation for the D60-02 deterministic basic color executor.

This is a retained verification entrypoint, not production diagnosis logic.  It
uses explicit parameters, independently replays every candidate through D3,
and exercises the existing managed-color encoder and atomic publisher.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageOps

from engine.color_correction import (
    CorrectionParameters,
    audit_basic_correction,
    execute_basic_correction,
    replay_basic_correction,
)
from engine.color_correction.color_management import (
    encode_color_managed_candidate,
    load_color_managed_source,
    verify_color_managed_output,
)
from engine.output.publish_safety import publish_image_bytes_with_metadata


REPO_ROOT = Path(__file__).resolve().parents[2]
D01_INPUTS = REPO_ROOT / "output/evaluation/d01_color_decision_20260812/inputs"
D01_ERRORS = (
    REPO_ROOT / "output/evaluation/color_quality_baseline_v1_metric_credit_fix_20260823/errors"
)
CHINESE_TEXT_SAMPLE = REPO_ROOT / "tests/fixtures/ocr_n2_01/samples/normal_chinese_title.png"
OUTPUT_DIR = REPO_ROOT / "output/evaluation/d60_02r_deterministic_base_20260904"


@dataclass(frozen=True)
class SampleCase:
    name: str
    source: str
    pixels: np.ndarray
    parameters: CorrectionParameters


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as opened:
        opened.load()
        return np.asarray(ImageOps.exif_transpose(opened).convert("RGB"), dtype=np.uint8).copy()


def _lab(pixels: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(pixels.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)


def _mean_chroma(pixels: np.ndarray) -> float:
    lab = _lab(pixels)
    return float(np.linalg.norm(lab[..., 1:3], axis=2).mean())


def _controlled_overexposure(pixels: np.ndarray) -> np.ndarray:
    return np.asarray(
        ImageEnhance.Brightness(Image.fromarray(pixels, mode="RGB")).enhance(1.55),
        dtype=np.uint8,
    ).copy()


def _controlled_saturation(pixels: np.ndarray, factor: float) -> np.ndarray:
    return np.asarray(
        ImageEnhance.Color(Image.fromarray(pixels, mode="RGB")).enhance(factor),
        dtype=np.uint8,
    ).copy()


def _controlled_magenta_cast(pixels: np.ndarray) -> np.ndarray:
    lab = _lab(pixels)
    lab[..., 1] = np.clip(lab[..., 1] + 14.0, -127.0, 127.0)
    rgb = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    return np.clip(np.rint(rgb * 255.0), 0.0, 255.0).astype(np.uint8)


def _direction_score(name: str, source: np.ndarray, candidate: np.ndarray) -> float:
    source_lab = _lab(source)
    candidate_lab = _lab(candidate)
    if name in {"exposure", "brightness"}:
        return float(candidate_lab[..., 0].mean() - source_lab[..., 0].mean())
    if name == "contrast":
        return float(candidate_lab[..., 0].std() - source_lab[..., 0].std())
    if name == "temperature":
        return float(np.median(candidate_lab[..., 2] - source_lab[..., 2]))
    if name == "tint":
        return float(np.median(candidate_lab[..., 1] - source_lab[..., 1]))
    if name in {"saturation", "vibrance"}:
        return _mean_chroma(candidate) - _mean_chroma(source)
    if name == "highlights":
        mask = source_lab[..., 0] >= np.quantile(source_lab[..., 0], 0.75)
        return float((candidate_lab[..., 0] - source_lab[..., 0])[mask].mean())
    if name == "shadows":
        mask = source_lab[..., 0] <= np.quantile(source_lab[..., 0], 0.25)
        return float((candidate_lab[..., 0] - source_lab[..., 0])[mask].mean())
    raise AssertionError(f"unknown parameter: {name}")


def _require_d3(
    source: np.ndarray,
    candidate: np.ndarray,
    parameters: CorrectionParameters,
) -> dict[str, object]:
    replay = replay_basic_correction(source, parameters.to_record())
    if not np.array_equal(replay, candidate):
        raise AssertionError("D3 replay differs from D2 candidate")
    audit = audit_basic_correction(source, candidate, parameters.to_record())
    if audit.status != "AUDIT_COMPLETE":
        raise AssertionError(f"D3 blocked safe candidate: {audit.to_record()}")
    if audit.pass_status["REPLAY_PASS"] != "YES":
        raise AssertionError("D3 replay identity did not pass")
    return audit.to_record()


def _fit_thumbnail(pixels: np.ndarray, width: int = 240, height: int = 180) -> Image.Image:
    image = Image.fromarray(pixels[..., :3], mode="RGB")
    image.thumbnail((width, height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), "#15191f")
    canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
    return canvas


def _contact_sheet(
    cells: list[tuple[str, np.ndarray]],
    *,
    columns: int,
    title: str,
) -> Image.Image:
    thumb_width, thumb_height, label_height = 240, 180, 34
    rows = (len(cells) + columns - 1) // columns
    sheet = Image.new(
        "RGB",
        (columns * thumb_width, 42 + rows * (thumb_height + label_height)),
        "#0c0f13",
    )
    draw = ImageDraw.Draw(sheet)
    draw.text((10, 12), title, fill="#f4f7fb")
    for index, (label, pixels) in enumerate(cells):
        row, column = divmod(index, columns)
        left = column * thumb_width
        top = 42 + row * (thumb_height + label_height)
        sheet.paste(_fit_thumbnail(pixels, thumb_width, thumb_height), (left, top))
        draw.rectangle(
            (left, top + thumb_height, left + thumb_width, top + thumb_height + label_height),
            fill="#15191f",
        )
        draw.text((left + 6, top + thumb_height + 9), label[:38], fill="#dbe8fa")
    return sheet


def _parameter_validation(source: np.ndarray) -> tuple[list[dict[str, object]], list[tuple[str, np.ndarray]]]:
    magnitudes = {
        "exposure": (0.22, 0.45),
        "brightness": (15.0, 30.0),
        "contrast": (18.0, 35.0),
        "temperature": (18.0, 35.0),
        "tint": (18.0, 35.0),
        "saturation": (18.0, 35.0),
        "vibrance": (18.0, 35.0),
        "highlights": (18.0, 35.0),
        "shadows": (18.0, 35.0),
    }
    records: list[dict[str, object]] = []
    cells: list[tuple[str, np.ndarray]] = []
    for name, (low_magnitude, high_magnitude) in magnitudes.items():
        candidates: dict[str, np.ndarray] = {}
        scores: dict[str, float] = {}
        audits: dict[str, dict[str, object]] = {}
        for label, value in (
            ("negative", -high_magnitude),
            ("low_positive", low_magnitude),
            ("positive", high_magnitude),
        ):
            parameters = CorrectionParameters(**{name: value})
            result = execute_basic_correction(source, parameters)
            candidates[label] = result.candidate_image
            scores[label] = _direction_score(name, source, result.candidate_image)
            audits[label] = _require_d3(source, result.candidate_image, parameters)
        if not scores["negative"] < 0.0 < scores["positive"]:
            raise AssertionError(f"{name} direction failed: {scores}")
        if not 0.0 < scores["low_positive"] < scores["positive"]:
            raise AssertionError(f"{name} amplitude is not monotonic: {scores}")
        records.append(
            {
                "parameter": name,
                "negative_value": -high_magnitude,
                "low_positive_value": low_magnitude,
                "positive_value": high_magnitude,
                "direction_scores": {key: round(value, 6) for key, value in scores.items()},
                "candidate_identities": {
                    key: audit["CANDIDATE_IDENTITY"] for key, audit in audits.items()
                },
                "result": "PASS",
            }
        )
        cells.extend(
            (
                (f"{name} -{high_magnitude:g}", candidates["negative"]),
                (f"{name} neutral", source),
                (f"{name} +{high_magnitude:g}", candidates["positive"]),
            )
        )
    saturation = execute_basic_correction(
        source, CorrectionParameters(saturation=35)
    ).candidate_image
    vibrance = execute_basic_correction(
        source, CorrectionParameters(vibrance=35)
    ).candidate_image
    if np.array_equal(saturation, vibrance):
        raise AssertionError("vibrance unexpectedly equals saturation")
    return records, cells


def _sample_cases() -> tuple[list[SampleCase], dict[Path, str]]:
    paths = {
        "normal": D01_INPUTS / "D01_01.jpg",
        "warm": D01_INPUTS / "D01_02.png",
        "cool": D01_INPUTS / "D01_03.png",
        "under": D01_INPUTS / "D01_04.png",
        "commercial": D01_INPUTS / "D01_10.png",
        "shadows": D01_INPUTS / "D01_11.png",
        "highlights": D01_INPUTS / "D01_12.png",
        "green": D01_ERRORS / "D01_01_OTHER_GLOBAL_CAST.png",
        "chinese": CHINESE_TEXT_SAMPLE,
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"real sample missing: {missing}")
    source_hashes = {path: _sha256(path) for path in set(paths.values())}
    normal = _load_rgb(paths["normal"])
    commercial = _load_rgb(paths["commercial"])
    cases = [
        SampleCase("normal_exposure_jpeg_portrait_skin", str(paths["normal"].relative_to(REPO_ROOT)), normal, CorrectionParameters(brightness=8)),
        SampleCase("underexposed_png", str(paths["under"].relative_to(REPO_ROOT)), _load_rgb(paths["under"]), CorrectionParameters(exposure=0.30, shadows=16)),
        SampleCase("overexposed_real_derived", "D01_01 brightness-derived x1.55", _controlled_overexposure(normal), CorrectionParameters(exposure=-0.30, highlights=-18)),
        SampleCase("warm_cast_png", str(paths["warm"].relative_to(REPO_ROOT)), _load_rgb(paths["warm"]), CorrectionParameters(temperature=-22)),
        SampleCase("cool_cast_png", str(paths["cool"].relative_to(REPO_ROOT)), _load_rgb(paths["cool"]), CorrectionParameters(temperature=22)),
        SampleCase("green_cast_png", str(paths["green"].relative_to(REPO_ROOT)), _load_rgb(paths["green"]), CorrectionParameters(tint=22)),
        SampleCase("magenta_cast_real_derived", "D01_01 Lab a +14", _controlled_magenta_cast(normal), CorrectionParameters(tint=-22)),
        SampleCase("low_saturation_real_derived", "D01_10 color x0.30", _controlled_saturation(commercial, 0.30), CorrectionParameters(vibrance=24, saturation=12)),
        SampleCase("high_saturation_real_derived", "D01_10 color x1.80", _controlled_saturation(commercial, 1.80), CorrectionParameters(saturation=-22)),
        SampleCase("highlight_detail_png", str(paths["highlights"].relative_to(REPO_ROOT)), _load_rgb(paths["highlights"]), CorrectionParameters(highlights=-20)),
        SampleCase("deep_shadows_png", str(paths["shadows"].relative_to(REPO_ROOT)), _load_rgb(paths["shadows"]), CorrectionParameters(shadows=20)),
        SampleCase("commercial_logo_png", str(paths["commercial"].relative_to(REPO_ROOT)), commercial, CorrectionParameters(contrast=8, vibrance=8)),
        SampleCase("chinese_text_logo_png", str(paths["chinese"].relative_to(REPO_ROOT)), _load_rgb(paths["chinese"]), CorrectionParameters(brightness=6, contrast=8)),
    ]
    return cases, source_hashes


def _validate_samples(cases: list[SampleCase]) -> tuple[list[dict[str, object]], list[tuple[str, np.ndarray]]]:
    records: list[dict[str, object]] = []
    cells: list[tuple[str, np.ndarray]] = []
    for case in cases:
        neutral = execute_basic_correction(case.pixels, CorrectionParameters())
        if not np.array_equal(neutral.candidate_image, case.pixels):
            raise AssertionError(f"neutral drift: {case.name}")
        neutral_audit = _require_d3(case.pixels, neutral.candidate_image, CorrectionParameters())
        result = execute_basic_correction(case.pixels, case.parameters)
        audit = _require_d3(case.pixels, result.candidate_image, case.parameters)
        second = execute_basic_correction(case.pixels.copy(), case.parameters)
        if not np.array_equal(second.candidate_image, result.candidate_image):
            raise AssertionError(f"non-deterministic sample: {case.name}")
        records.append(
            {
                "name": case.name,
                "source": case.source,
                "shape": list(case.pixels.shape),
                "source_pixel_sha256": hashlib.sha256(case.pixels.tobytes()).hexdigest(),
                "parameters": case.parameters.to_record(),
                "neutral_exact": True,
                "neutral_final_action": neutral_audit["FINAL_ACTION"],
                "candidate_identity": audit["CANDIDATE_IDENTITY"],
                "d3_replay": audit["PASS_STATUS"]["REPLAY_PASS"],
                "safety": audit["PASS_STATUS"]["OVERALL_EXECUTION_SAFETY_PASS"],
                "metrics": result.metrics,
                "result": "PASS",
            }
        )
        cells.append((f"{case.name} | source", case.pixels))
        cells.append((f"{case.name} | corrected", result.candidate_image))
    return records, cells


def _formal_publish_case(source_path: Path, output_path: Path) -> dict[str, object]:
    source_hash = _sha256(source_path)
    managed = load_color_managed_source(source_path)
    parameters = CorrectionParameters(
        exposure=0.16,
        brightness=5,
        contrast=7,
        temperature=4,
        tint=-3,
        saturation=5,
        vibrance=6,
        highlights=-5,
        shadows=7,
    )
    result = execute_basic_correction(
        managed.pixels,
        parameters,
        input_order=managed.input_order,
    )
    audit = audit_basic_correction(
        managed.pixels,
        result.candidate_image,
        result.parameter_record,
        input_order=managed.input_order,
    )
    if audit.status != "AUDIT_COMPLETE" or audit.pass_status["REPLAY_PASS"] != "YES":
        raise AssertionError(f"formal case D3 replay failed: {audit.to_record()}")
    encoded = encode_color_managed_candidate(result.candidate_image, managed)
    verify_color_managed_output(encoded, result.candidate_image, managed)

    def verify_private(payload: bytes) -> None:
        verify_color_managed_output(payload, result.candidate_image, managed)

    published, metadata, _validation = publish_image_bytes_with_metadata(
        encoded,
        output_path,
        source_data=source_path.read_bytes(),
        normalize_orientation=True,
        verify_private=verify_private,
    )
    verify_color_managed_output(published, result.candidate_image, managed)
    if _sha256(source_path) != source_hash:
        raise AssertionError("source file changed during formal publish")
    published_managed = load_color_managed_source(published)
    with Image.open(published) as opened:
        opened.load()
        decoder_dpi_hint = opened.info.get("dpi")
        observed_size = list(opened.size)
        observed_format = opened.format
    return {
        "source": str(source_path.relative_to(REPO_ROOT)),
        "source_sha256": source_hash,
        "source_format": managed.source_format,
        "source_dpi": list(managed.source_dpi) if managed.source_dpi is not None else None,
        "output": str(published.relative_to(REPO_ROOT)),
        "output_sha256": _sha256(published),
        "output_format": observed_format,
        "output_dimensions": observed_size,
        "output_dpi": (
            list(published_managed.source_dpi)
            if published_managed.source_dpi is not None
            else None
        ),
        "output_decoder_dpi_hint": (
            list(decoder_dpi_hint) if decoder_dpi_hint is not None else None
        ),
        "metadata_report": metadata,
        "d3_candidate_identity": audit.candidate_identity,
        "d3_replay": audit.pass_status["REPLAY_PASS"],
        "result": "PASS",
    }


def main() -> None:
    if OUTPUT_DIR.exists():
        raise FileExistsError(f"validation output already exists: {OUTPUT_DIR}")

    cases, source_hashes = _sample_cases()
    direction_source = _load_rgb(D01_INPUTS / "D01_01.jpg")
    parameter_records, parameter_cells = _parameter_validation(direction_source)
    sample_records, sample_cells = _validate_samples(cases)

    combination_parameters = CorrectionParameters(
        exposure=0.25,
        brightness=8,
        contrast=10,
        temperature=6,
        tint=-4,
        saturation=6,
        vibrance=8,
        highlights=-7,
        shadows=10,
    )
    combination_cells: list[tuple[str, np.ndarray]] = []
    combination_records: list[dict[str, object]] = []
    for case in (cases[0], cases[11], cases[12]):
        first = execute_basic_correction(case.pixels, combination_parameters)
        second = execute_basic_correction(case.pixels.copy(), combination_parameters)
        if not np.array_equal(first.candidate_image, second.candidate_image):
            raise AssertionError(f"combination is not deterministic: {case.name}")
        audit = _require_d3(case.pixels, first.candidate_image, combination_parameters)
        combination_records.append(
            {
                "sample": case.name,
                "parameters": combination_parameters.to_record(),
                "candidate_identity": audit["CANDIDATE_IDENTITY"],
                "exact_repeat": True,
                "d3_replay": audit["PASS_STATUS"]["REPLAY_PASS"],
                "metrics": first.metrics,
                "result": "PASS",
            }
        )
        combination_cells.extend(
            (
                (f"{case.name} | source", case.pixels),
                (f"{case.name} | 9-control combo", first.candidate_image),
            )
        )

    for path, original_hash in source_hashes.items():
        if _sha256(path) != original_hash:
            raise AssertionError(f"protected real source changed: {path}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=False)
    controlled_inputs = OUTPUT_DIR / "controlled_inputs"
    formal_outputs = OUTPUT_DIR / "formal_outputs"
    controlled_inputs.mkdir()
    formal_outputs.mkdir()

    _contact_sheet(
        parameter_cells,
        columns=3,
        title="D60-02 single-control directions: negative | neutral | positive",
    ).save(OUTPUT_DIR / "parameter_directions.jpg", quality=94, subsampling=0)
    _contact_sheet(
        sample_cells,
        columns=4,
        title="D60-02 real-image matrix: source and explicit correction",
    ).save(OUTPUT_DIR / "real_sample_matrix.jpg", quality=94, subsampling=0)
    _contact_sheet(
        combination_cells,
        columns=2,
        title="D60-02 deterministic nine-control combination",
    ).save(OUTPUT_DIR / "combination_review.jpg", quality=94, subsampling=0)

    Image.fromarray(cases[2].pixels, mode="RGB").save(controlled_inputs / "overexposed_D01_01.png")
    Image.fromarray(cases[6].pixels, mode="RGB").save(controlled_inputs / "magenta_cast_D01_01.png")
    Image.fromarray(cases[7].pixels, mode="RGB").save(controlled_inputs / "low_saturation_D01_10.png")
    Image.fromarray(cases[8].pixels, mode="RGB").save(controlled_inputs / "high_saturation_D01_10.png")

    dpi_source = controlled_inputs / "D01_01_dpi_180.jpg"
    Image.fromarray(direction_source, mode="RGB").save(
        dpi_source,
        quality=95,
        subsampling=0,
        dpi=(180, 180),
    )
    no_dpi_jpeg_source = controlled_inputs / "D01_01_no_dpi.jpg"
    Image.fromarray(direction_source, mode="RGB").save(
        no_dpi_jpeg_source,
        quality=95,
        subsampling=0,
    )
    formal_records = [
        _formal_publish_case(D01_INPUTS / "D01_01.jpg", formal_outputs / "real_jpeg_dpi_72.jpg"),
        _formal_publish_case(D01_INPUTS / "D01_10.png", formal_outputs / "real_png_no_dpi.png"),
        _formal_publish_case(no_dpi_jpeg_source, formal_outputs / "real_jpeg_no_dpi.jpg"),
        _formal_publish_case(dpi_source, formal_outputs / "real_jpeg_dpi_180.jpg"),
    ]
    if formal_records[0]["source_dpi"] is None or formal_records[0]["output_dpi"] is None:
        raise AssertionError("real 72 DPI JPEG lost its DPI value")
    if any(
        abs(float(actual) - float(expected)) > 0.02
        for actual, expected in zip(formal_records[0]["output_dpi"], formal_records[0]["source_dpi"])
    ):
        raise AssertionError("real 72 DPI JPEG changed its DPI value")
    if formal_records[1]["source_dpi"] is not None or formal_records[1]["output_dpi"] is not None:
        raise AssertionError("PNG without source DPI gained a DPI value")
    if formal_records[2]["source_dpi"] is not None or formal_records[2]["output_dpi"] is not None:
        raise AssertionError("JPEG without source DPI gained a DPI value")
    expected_dpi = formal_records[3]["source_dpi"]
    output_dpi = formal_records[3]["output_dpi"]
    if expected_dpi is None or output_dpi is None:
        raise AssertionError("180 DPI did not survive formal encoding")
    if any(abs(float(actual) - float(expected)) > 0.02 for actual, expected in zip(output_dpi, expected_dpi)):
        raise AssertionError(f"DPI mismatch: expected={expected_dpi}, output={output_dpi}")

    manifest = {
        "stage": "D60-02",
        "status": "PASS",
        "scope": "deterministic execution only; no automatic parameter decision",
        "parameter_directions": parameter_records,
        "real_samples": sample_records,
        "combinations": combination_records,
        "formal_encoding_and_atomic_publish": formal_records,
        "source_hashes_unchanged": {
            str(path.relative_to(REPO_ROOT)): digest for path, digest in sorted(source_hashes.items())
        },
        "controlled_real_derivatives": [
            "overexposed_D01_01.png",
            "magenta_cast_D01_01.png",
            "low_saturation_D01_10.png",
            "high_saturation_D01_10.png",
            "D01_01_dpi_180.jpg",
            "D01_01_no_dpi.jpg",
        ],
        "contact_sheets": [
            "parameter_directions.jpg",
            "real_sample_matrix.jpg",
            "combination_review.jpg",
        ],
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "output": str(OUTPUT_DIR), "counts": {
        "parameters": len(parameter_records),
        "real_samples": len(sample_records),
        "combinations": len(combination_records),
        "formal_outputs": len(formal_records),
    }}, ensure_ascii=False))


if __name__ == "__main__":
    main()
