"""Retained real-image validation for D60-03 diagnosis and parameter decisions."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageEnhance

from backend.image_compression_api import register_image_compression_routes
from engine.color_correction import (
    ParameterDecisionOutcome,
    analyze_color_usability,
    audit_candidate,
    bind_parameter_decision,
    build_objective_diagnosis,
    decide_correction_parameters,
    execute_basic_correction,
    run_formal_color_runtime,
)


INPUTS = ROOT / "output/evaluation/d01_color_decision_20260812/inputs"
POSTER = ROOT / "output/g_line_final_benchmark_20260901/assets/normal_commercial_poster.png"
FIXTURES = ROOT / "tests/fixtures/color_correction/d60_03r"
OUTPUT = ROOT / "output/evaluation/d60_03_intelligent_decision_20260904_r7"
PRODUCT_VERSION = ROOT / "product_version.json"
CODE_FINGERPRINT_PATHS = (
    ROOT / "engine/color_correction/objective_diagnosis.py",
    ROOT / "engine/color_correction/parameter_decision.py",
    ROOT / "engine/color_correction/usability_decision.py",
    ROOT / "engine/color_correction/formal_runtime.py",
    ROOT / "tests/color_correction/test_d60_03_intelligent_decision.py",
    Path(__file__).resolve(),
)
FROZEN_D60_02_PATHS = (
    ROOT / "engine/color_correction/parameters.py",
    ROOT / "engine/color_correction/executors/basic_correction.py",
    ROOT / "engine/color_correction/color_management.py",
)
FROZEN_D3_PATHS = (ROOT / "engine/color_correction/result_audit.py",)

EXPECTED_RESULTS = {
    "01_obvious_under": ("CORRECTION_NEEDED", "exposure", 1, (0.16, 0.52)),
    "02_obvious_over": ("INSUFFICIENT_EVIDENCE", None, 0, None),
    "03_mild_under": ("CORRECTION_NEEDED", "brightness", 1, (4.0, 12.0)),
    "04_mild_over": ("CORRECTION_NEEDED", "brightness", -1, (4.0, 12.0)),
    "05_warm_cast": ("CORRECTION_NEEDED", "temperature", -1, (6.0, 20.0)),
    "06_cool_cast": ("CORRECTION_NEEDED", "temperature", 1, (6.0, 20.0)),
    "07_green_cast": ("CORRECTION_NEEDED", "tint", 1, (6.0, 20.0)),
    "08_magenta_cast": ("CORRECTION_NEEDED", "tint", -1, (6.0, 20.0)),
    "09_low_saturation": ("INSUFFICIENT_EVIDENCE", None, 0, None),
    "10_high_saturation": ("INSUFFICIENT_EVIDENCE", None, 0, None),
    "11_low_contrast": ("CORRECTION_NEEDED", "contrast", 1, (6.0, 20.0)),
    "12_high_contrast": ("INSUFFICIENT_EVIDENCE", None, 0, None),
    "13_highlight_problem": ("INSUFFICIENT_EVIDENCE", None, 0, None),
    "14_shadow_problem": ("INSUFFICIENT_EVIDENCE", None, 0, None),
    "28_true_underexposed_person": ("CORRECTION_NEEDED", "exposure", 1, (0.16, 0.52)),
    "29_true_overexposed_person": ("CORRECTION_NEEDED", "exposure", -1, (0.16, 0.52)),
    "31_severe_clipping_high_saturation": ("INSUFFICIENT_EVIDENCE", None, 0, None),
    "32_high_skin_risk_under": ("INSUFFICIENT_EVIDENCE", None, 0, None),
}


@dataclass(frozen=True)
class Case:
    name: str
    category: str
    source: str
    pixels: np.ndarray
    diagnosis_check: Callable[[object], bool]
    expected_parameter: str | None = None
    expected_sign: int = 0
    actual_problem: bool = False
    protected_scene: bool = False
    person_regions: tuple[tuple[int, int, int, int], ...] | None = None
    coverage_note: str | None = None
    source_type: str = "REPOSITORY_REAL_SAMPLE"
    source_attribution: dict[str, str] | None = None


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_hashes(paths: tuple[Path, ...]) -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)): _hash(path)
        for path in paths
    }


def _fingerprint(hashes: dict[str, str]) -> str:
    payload = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _git_value(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    ).strip()


def _load(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        image.load()
        return np.asarray(image.convert("RGB"), dtype=np.uint8).copy()


def _enhance(pixels: np.ndarray, kind: str, factor: float) -> np.ndarray:
    image = Image.fromarray(pixels, mode="RGB")
    enhancer = {
        "brightness": ImageEnhance.Brightness,
        "contrast": ImageEnhance.Contrast,
        "color": ImageEnhance.Color,
    }[kind]
    return np.asarray(enhancer(image).enhance(factor), dtype=np.uint8).copy()


def _offset(pixels: np.ndarray, value: int) -> np.ndarray:
    return np.clip(pixels.astype(np.int16) + value, 0, 255).astype(np.uint8)


def _gamma(pixels: np.ndarray, exponent: float) -> np.ndarray:
    normalized = pixels.astype(np.float32) / 255.0
    return np.clip(np.rint(np.power(normalized, exponent) * 255.0), 0, 255).astype(np.uint8)


def _controlled_high_midtones(pixels: np.ndarray) -> np.ndarray:
    """Lift midtones while retaining measurable shadow and highlight detail."""

    normalized = pixels.astype(np.float32) / 255.0
    source_points = np.asarray((0.0, 0.04, 0.08, 0.18, 0.35, 0.55, 0.75, 0.90, 1.0))
    target_points = np.asarray((0.11, 0.13, 0.18, 0.35, 0.82, 0.90, 0.94, 0.97, 1.0))
    transformed = np.interp(normalized, source_points, target_points)
    return np.clip(np.rint(transformed * 255.0), 0, 255).astype(np.uint8)


def _blend_white(pixels: np.ndarray, amount: float) -> np.ndarray:
    blended = pixels.astype(np.float32) * (1.0 - amount) + 255.0 * amount
    return np.clip(np.rint(blended), 0, 255).astype(np.uint8)


def _severe_channel_clip(pixels: np.ndarray) -> np.ndarray:
    saturated = _enhance(pixels, "color", 2.2)
    clipped = saturated.copy()
    clipped[clipped <= 60] = 0
    clipped[clipped >= 195] = 255
    return clipped


def _lab_cast(pixels: np.ndarray, *, a: float = 0.0, b: float = 0.0) -> np.ndarray:
    lab = cv2.cvtColor(pixels.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    lab[..., 1] = np.clip(lab[..., 1] + a, -127.0, 127.0)
    lab[..., 2] = np.clip(lab[..., 2] + b, -127.0, 127.0)
    return np.clip(np.rint(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB) * 255.0), 0, 255).astype(np.uint8)


def _uniform_lab_cast(pixels: np.ndarray, *, a: float, b: float) -> np.ndarray:
    lab = cv2.cvtColor(pixels.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    lab[..., 1] = a
    lab[..., 2] = b
    return np.clip(np.rint(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB) * 255.0), 0, 255).astype(np.uint8)


def _thumb(pixels: np.ndarray, size: tuple[int, int] = (220, 150)) -> Image.Image:
    image = Image.fromarray(pixels, mode="RGB")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, "#11161d")
    canvas.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return canvas


def _sheet(cells: list[tuple[str, np.ndarray]]) -> Image.Image:
    width, height, label = 220, 150, 34
    columns = 4
    rows = (len(cells) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * width, 44 + rows * (height + label)), "#090d12")
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 14), "D60-03 source | decision candidate (or protected source)", fill="#f2f6fc")
    for index, (name, pixels) in enumerate(cells):
        row, column = divmod(index, columns)
        x, y = column * width, 44 + row * (height + label)
        sheet.paste(_thumb(pixels), (x, y))
        draw.text((x + 5, y + height + 9), name[:34], fill="#d8e5f7")
    return sheet


def _cases() -> tuple[list[Case], dict[Path, str]]:
    paths = {name: INPUTS / f"D01_{name}.png" for name in [f"{index:02d}" for index in range(2, 16)]}
    paths["01"] = INPUTS / "D01_01.jpg"
    paths["poster"] = POSTER
    paths["sunset"] = FIXTURES / "real_sunset_landscape.jpg"
    paths["landscape"] = FIXTURES / "real_mountain_lake_landscape.jpg"
    paths["ai_generated"] = FIXTURES / "ai_generated_product_studio.png"
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"D60-03 real sample missing: {missing}")
    hashes = {path: _hash(path) for path in set(paths.values())}
    normal = _load(paths["01"])
    cases = [
        Case("01_obvious_under", "明显欠曝", str(paths["04"].relative_to(ROOT)), _load(paths["04"]), lambda d: d.exposure.state == "UNDEREXPOSED", "exposure", 1, True),
        Case("02_obvious_over", "明显过曝", "D01_01 controlled +150", _offset(normal, 150), lambda d: d.exposure.state == "OVEREXPOSED", actual_problem=True),
        Case("03_mild_under", "轻微欠曝", "D01_01 controlled brightness 0.85", _enhance(normal, "brightness", 0.85), lambda d: d.brightness_distribution.state == "LOW_MIDTONES", "brightness", 1, True),
        Case("04_mild_over", "轻微过曝", "D01_01 controlled high-midtone curve with retained endpoints", _controlled_high_midtones(normal), lambda d: d.brightness_distribution.state == "HIGH_MIDTONES" and d.contrast.state == "ACCEPTABLE", "brightness", -1, True),
        Case("05_warm_cast", "明显偏暖", str(paths["02"].relative_to(ROOT)), _load(paths["02"]), lambda d: d.white_balance.state == "WARM", "temperature", -1, True),
        Case("06_cool_cast", "明显偏冷", str(paths["03"].relative_to(ROOT)), _load(paths["03"]), lambda d: d.white_balance.state == "COOL", "temperature", 1, True),
        Case("07_green_cast", "偏绿", "D01_01 controlled uniform Lab a -8 b 0", _uniform_lab_cast(normal, a=-8, b=0), lambda d: d.white_balance.state == "GREEN", "tint", 1, True),
        Case("08_magenta_cast", "偏洋红", "D01_01 controlled Lab a +14", _lab_cast(normal, a=14), lambda d: d.white_balance.state == "MAGENTA", "tint", -1, True),
        Case("09_low_saturation", "低饱和", "D01_01 controlled color 0.25", _enhance(normal, "color", 0.25), lambda d: d.saturation.state in {"LOW", "LOW_AMBIGUOUS", "VERY_LOW_UNIFORM"}, actual_problem=True),
        Case("10_high_saturation", "高饱和", "D01_01 controlled color 1.80", _enhance(normal, "color", 1.80), lambda d: d.saturation.state == "HIGH", actual_problem=True),
        Case("11_low_contrast", "对比不足", str(paths["06"].relative_to(ROOT)), _load(paths["06"]), lambda d: d.contrast.state == "LOW", "contrast", 1, True, person_regions=()),
        Case("12_high_contrast", "对比过强", "D01_01 controlled contrast 2.20", _enhance(normal, "contrast", 2.20), lambda d: d.contrast.state == "HIGH", actual_problem=True),
        Case("13_highlight_problem", "高光问题", "D01_12 controlled +55", _offset(_load(paths["12"]), 55), lambda d: d.highlights.state in {"AT_RISK", "CLIPPED"}, actual_problem=True, person_regions=()),
        Case("14_shadow_problem", "阴影问题", "D01_11 controlled -45", _offset(_load(paths["11"]), -45), lambda d: d.shadows.state in {"AT_RISK", "CRUSHED"}, actual_problem=True, person_regions=()),
        Case("15_normal_photo", "正常照片", str(paths["01"].relative_to(ROOT)), normal, lambda d: d.exposure.state == "ACCEPTABLE" and d.white_balance.state == "NEUTRAL", protected_scene=True),
        Case("16_portrait_skin", "人像/肤色", str(paths["01"].relative_to(ROOT)), normal, lambda d: d.skin_risk.state in {"MEDIUM", "HIGH"}, protected_scene=True),
        Case("17_product", "产品本色", str(paths["09"].relative_to(ROOT)), _load(paths["09"]), lambda d: d.scene_risk.state in {"MEDIUM", "HIGH"}, protected_scene=True),
        Case(
            "18_landscape",
            "真实风景照片",
            str(paths["landscape"].relative_to(ROOT)),
            _load(paths["landscape"]),
            lambda d: d.scene_risk.evidence.get("scene_intent") == "LEGITIMATE_DARK",
            protected_scene=True,
            person_regions=(),
            source_type="REAL_PHOTOGRAPH",
            source_attribution={
                "source_page": "https://commons.wikimedia.org/wiki/File:Scenic_view_of_a_mountain_lake_in_glacier_national_park.jpg",
                "license": "PUBLIC_DOMAIN",
                "description": "Scenic view of a mountain lake in Glacier National Park",
            },
        ),
        Case("19_warm_indoor", "室内暖光", str(paths["13"].relative_to(ROOT)), _load(paths["13"]), lambda d: d.scene_risk.evidence.get("scene_intent") == "LEGITIMATE_WARM", protected_scene=True),
        Case("20_night", "夜景", str(paths["15"].relative_to(ROOT)), _load(paths["15"]), lambda d: d.scene_risk.evidence.get("scene_intent") == "LEGITIMATE_DARK", protected_scene=True),
        Case(
            "21_sunset",
            "真实日落照片",
            str(paths["sunset"].relative_to(ROOT)),
            _load(paths["sunset"]),
            lambda d: d.scene_risk.evidence.get("scene_intent") == "LEGITIMATE_DARK",
            protected_scene=True,
            person_regions=(),
            source_type="REAL_PHOTOGRAPH",
            source_attribution={
                "source_page": "https://commons.wikimedia.org/wiki/File:Sunset_Landscape.jpg",
                "author": "Rabsum",
                "license": "CC_BY_SA_4.0",
                "description": "Landscape while sunset, photographed 2017-05-14",
            },
        ),
        Case(
            "22_ai_generated",
            "明确来源AI生图/商业渲染",
            str(paths["ai_generated"].relative_to(ROOT)),
            _load(paths["ai_generated"]),
            lambda d: d.scene_risk.evidence.get("scene_intent") == "LEGITIMATE_HIGH_KEY",
            protected_scene=True,
            person_regions=(),
            source_type="AI_GENERATED",
            source_attribution={
                "generator": "OpenAI built-in image_gen",
                "generated_for": "D60-03R color-decision validation",
                "prompt_summary": "unbranded teal bottle and coral package in neutral high-key studio light",
            },
        ),
        Case("23_chinese_poster_logo", "中文商业海报/Logo", str(paths["poster"].relative_to(ROOT)), _load(paths["poster"]), lambda d: d.scene_risk.state in {"MEDIUM", "HIGH"} or d.saturation.state in {"HIGH", "ACCEPTABLE"}, protected_scene=True),
        Case("24_no_reliable_neutral", "无可靠中性色证据", str(paths["07"].relative_to(ROOT)), _load(paths["07"]), lambda d: d.neutral_color_evidence.state in {"MIXED_FIELD", "INSUFFICIENT", "UNSTABLE"}, protected_scene=True),
        Case(
            "25_high_key_portrait",
            "高调人像",
            "D01_01 controlled high-key tonal treatment",
            _blend_white(normal, 0.62),
            lambda d: d.scene_risk.evidence.get("scene_intent") == "LEGITIMATE_HIGH_KEY",
            protected_scene=True,
            source_type="CONTROLLED_FROM_REAL_PHOTOGRAPH",
        ),
        Case(
            "26_backlit_person",
            "逆光人物",
            str(paths["05"].relative_to(ROOT)),
            _load(paths["05"]),
            lambda d: d.skin_risk.evidence.get("person_present") is True
            and d.highlights.state == "CLIPPED",
            protected_scene=True,
            person_regions=((240, 190, 930, 920),),
        ),
        Case(
            "27_normal_low_light_portrait",
            "正常低照度人像",
            str(paths["15"].relative_to(ROOT)),
            _load(paths["15"]),
            lambda d: d.scene_risk.evidence.get("scene_intent") == "LEGITIMATE_DARK"
            and d.skin_risk.evidence.get("person_present") is True,
            protected_scene=True,
        ),
        Case(
            "28_true_underexposed_person",
            "真正欠曝人物",
            str(paths["04"].relative_to(ROOT)),
            _load(paths["04"]),
            lambda d: d.exposure.state == "UNDEREXPOSED"
            and d.skin_risk.evidence.get("person_present") is True,
            "exposure",
            1,
            True,
        ),
        Case(
            "29_true_overexposed_person",
            "真正过曝人物",
            "D01_01 controlled +140 with clipped highlights",
            _offset(normal, 140),
            lambda d: d.exposure.state == "OVEREXPOSED"
            and d.skin_risk.evidence.get("person_present") is True,
            "exposure",
            -1,
            True,
            source_type="CONTROLLED_FROM_REAL_PHOTOGRAPH",
        ),
        Case(
            "30_non_person_high_key",
            "非人物高调场景",
            "D01_12 controlled high-key tonal treatment",
            _blend_white(_load(paths["12"]), 0.35),
            lambda d: d.scene_risk.evidence.get("scene_intent") == "LEGITIMATE_HIGH_KEY"
            and d.skin_risk.evidence.get("person_present") is False,
            protected_scene=True,
            person_regions=(),
            source_type="CONTROLLED_FROM_REAL_PHOTOGRAPH",
        ),
        Case(
            "31_severe_clipping_high_saturation",
            "严重通道clipping与高饱和",
            "D01_01 controlled color 2.2 plus channel clipping",
            _severe_channel_clip(normal),
            lambda d: d.saturation.state == "HIGH" and d.clipping.state == "SEVERE",
            actual_problem=True,
            source_type="CONTROLLED_FROM_REAL_PHOTOGRAPH",
        ),
        Case(
            "32_high_skin_risk_under",
            "高肤色风险欠曝反例",
            "D01_08 controlled brightness 0.80",
            _enhance(_load(paths["08"]), "brightness", 0.80),
            lambda d: d.exposure.state == "UNDEREXPOSED"
            and d.skin_risk.state == "HIGH"
            and d.skin_risk.evidence.get("local_person_color_risk") is True,
            actual_problem=True,
            protected_scene=True,
            source_type="CONTROLLED_FROM_REAL_PHOTOGRAPH",
        ),
    ]
    return cases, hashes


def run_midtone_formal_validation(*, baseline_root: Path, output: Path, base_url: str) -> dict:
    """Regenerate only the two affected, hash-fixed inputs through real HTTP.

    The caller starts unchanged main.py with a fresh validation runtime root.
    No person context is supplied: the formal runtime owns automatic detection.
    Previous Benchmark assets and human verdicts are never overwritten.
    """
    import html
    import httpx

    baseline_root, output = baseline_root.resolve(), output.resolve()
    runtime_root = output.parent / "runtime"
    if output.exists() or output.is_relative_to(ROOT) or not runtime_root.is_dir():
        raise ValueError("require a new external review directory and isolated runtime")
    manifest = json.loads((baseline_root / "manifest/inputs.json").read_text(encoding="utf-8"))
    sources = [row for row in manifest["auto"] if row["id"] in {"03_mild_under", "04_mild_over"}]
    assert len(sources) == 2
    paths = tuple(sorted(set(
        CODE_FINGERPRINT_PATHS + (PRODUCT_VERSION, ROOT / "main.py", ROOT / "backend/image_compression_api.py")
        + tuple((ROOT / "engine/color_correction").rglob("*.py"))
    )))
    before = _file_hashes(paths)
    assert not _git_value("diff", "--cached", "--name-status")
    output.mkdir(parents=True, exist_ok=False)
    rows, panels = [], []
    with httpx.Client(base_url=base_url, timeout=180, trust_env=False) as client:
        status = client.get("/api/runtime/status")
        status.raise_for_status()
        root_fact = status.json()["data"]["formal_root"]
        assert Path(root_fact["path"]).resolve() == runtime_root
        assert root_fact["source"] == "validation_formal_root"
        for row in sources:
            source = Path(row["source"])
            assert _hash(source) == row["source_sha256"]
            previous_path = baseline_root / "benchmark/final/auto" / row["id"] / "receipt.json"
            previous = json.loads(previous_path.read_text(encoding="utf-8"))["api"]["data"]["result"]
            assert previous["source_sha256"] == _hash(source)
            intake = client.post("/api/image-compression/intake", files={"file": (source.name, source.read_bytes(), "image/png")})
            intake.raise_for_status()
            response = client.post("/api/color-correction/run", json={
                "source_token": intake.json()["data"]["source_token"],
                "current_task_output_root": str(runtime_root / "输出"),
            })
            response.raise_for_status()
            payload = response.json()
            result = payload["data"]["result"]
            assert result["task_id"] != previous["task_id"] and result["result_id"] != previous["result_id"]
            final = Path(result["result_file"])
            assert final.resolve().is_relative_to(runtime_root)
            assert result["source_sha256"] == _hash(source) and result["output_sha256"] == _hash(final)
            with Image.open(source) as si, Image.open(final) as oi:
                si.load()
                oi.load()
                assert si.size == oi.size and si.mode == oi.mode and si.format == oi.format
                src, dst = np.asarray(si).copy(), np.asarray(oi).copy()
                left, right = si.convert("RGB"), oi.convert("RGB")
            direction = 1 if row["id"] == "03_mild_under" else -1
            rgb_delta = dst.astype(np.int16) - src.astype(np.int16)
            l_before = cv2.cvtColor(src.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)[..., 0]
            l_after = cv2.cvtColor(dst.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)[..., 0]
            pixel_checks = {
                "mean_Lstar_delta": float(np.mean(l_after - l_before)),
                "changed_pixel_ratio": float(np.mean(np.any(rgb_delta != 0, axis=2))),
                "source_zero_channel_ratio": float(np.mean(src == 0)),
                "result_zero_channel_ratio": float(np.mean(dst == 0)),
                "source_max_channel_ratio": float(np.mean(src == 255)),
                "result_max_channel_ratio": float(np.mean(dst == 255)),
                "max_absolute_channel_delta": int(np.max(np.abs(rgb_delta))),
                "direction_pass": bool(direction * np.mean(l_after - l_before) > 0),
            }
            # Uniform display scaling only; never amplify the image difference.
            left.thumbnail((900, 900), Image.Resampling.LANCZOS)
            right.thumbnail((900, 900), Image.Resampling.LANCZOS)
            sheet = Image.new("RGB", (left.width + right.width, 44 + max(left.height, right.height)), "#161b22")
            sheet.paste(left, (0, 44))
            sheet.paste(right, (left.width, 44))
            draw = ImageDraw.Draw(sheet)
            draw.text((12, 12), row["id"] + " | SOURCE", fill="white")
            draw.text((left.width + 12, 12), "REGISTERED RESULT | " + result["d3_final_action"], fill="white")
            comparison = output / (row["id"] + "_source_result.png")
            sheet.save(comparison)
            record = {
                "id": row["id"], "source": str(source), "source_sha256": _hash(source),
                "result": str(final), "result_sha256": _hash(final), "api": payload,
                "previous_receipt": str(previous_path), "previous_receipt_sha256": _hash(previous_path),
                "previous_decision": previous["analysis"]["PARAMETER_DECISION"],
                "previous_task_id": previous["task_id"], "previous_result_id": previous["result_id"],
                "person_context": "FORMAL_RUNTIME_AUTOMATIC", "pixel_checks": pixel_checks,
                "comparison": str(comparison), "comparison_sha256": _hash(comparison), "human_verdict": None,
            }
            rows.append(record)
            panels.append(
                f'<section><h2>{html.escape(row["id"])}</h2>'
                f'<p>{html.escape(result["result_id"])} | {html.escape(result["d3_final_action"])}</p>'
                f'<img style="max-width:100%" src="{comparison.name}" alt="Source | registered result">'
                f'<p>LEFT: SOURCE <a href="{source.as_uri()}">original pixels</a> | SHA256 {_hash(source)}</p>'
                f'<p>RIGHT: RESULT <a href="{final.as_uri()}">registered pixels</a> | SHA256 {_hash(final)}</p>'
                '<p>Human aesthetic acceptance: PENDING. Other 48 pairs are unchanged.</p></section>'
            )
    after = _file_hashes(paths)
    assert before == after and not _git_value("diff", "--cached", "--name-status")
    report = {
        "branch": _git_value("branch", "--show-current"), "head": _git_value("rev-parse", "HEAD"),
        "product_version": json.loads(PRODUCT_VERSION.read_text(encoding="utf-8")),
        "source_hashes": before, "pre_fingerprint": _fingerprint(before), "post_fingerprint": _fingerprint(after),
        "runtime": status.json(), "records": rows, "human_verdict": None,
        "scope": "Two affected pairs only; original 50-pair denominator and remaining 48 assets unchanged",
    }
    (output / "evidence.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    (output / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>D60-FINAL midtone fix review supplement</title>'
        '<h1>03 / 04 — Source | Fixed Result</h1>' + "".join(panels), encoding="utf-8",
    )
    for row in rows:
        result = row["api"]["data"]["result"]
        assert result["analysis"]["OBJECTIVE_DIAGNOSIS"]["SKIN_RISK"]["evidence"]["person_present"] is True
        assert result["analysis"]["PARAMETER_DECISION_OUTCOME"] == "CORRECTION_NEEDED"
        assert result["d3_final_action"] == "ACCEPT_CORRECTED"
        assert row["source_sha256"] != row["result_sha256"] and row["pixel_checks"]["direction_pass"]
    return report


def _run_formal_api(api_root: Path) -> dict[str, object]:
    tmp_root = api_root / "tmp"
    formal_root = api_root / "formal"
    tmp_root.mkdir(parents=True)
    formal_root.mkdir(parents=True)

    def validate_output_root(value: str) -> dict[str, object]:
        target = Path(value).resolve()
        target.mkdir(parents=True, exist_ok=True)
        return {"valid": True, "writable": True, "normalized_path": str(target)}

    app = FastAPI()
    state = register_image_compression_routes(
        app,
        user_dirs_provider=lambda: {
            "normal_output_dir": formal_root / "输出",
            "tmp_dir": tmp_root,
        },
        output_settings_provider=lambda: {
            "built_in_default_root": str(formal_root),
            "saved_default_root": str(formal_root),
        },
        output_dir_validator=validate_output_root,
    )
    source = INPUTS / "D01_04.png"
    with TestClient(app) as client:
        intake_response = client.post(
            "/api/image-compression/intake",
            files={"file": (source.name, source.read_bytes(), "image/png")},
        )
        if intake_response.status_code != 200:
            raise AssertionError(intake_response.text)
        source_token = intake_response.json()["data"]["source_token"]
        run_response = client.post(
            "/api/color-correction/run",
            json={"source_token": source_token},
        )
        if run_response.status_code != 200:
            raise AssertionError(run_response.text)
        data = run_response.json()["data"]

    task = data["task"]
    result = data["result"]
    task_id = str(task["task_id"])
    result_id = str(result["result_id"])
    if not task_id or not result_id or task_id == result_id:
        raise AssertionError("formal API did not create distinct Task/Result identities")
    if task_id not in state["task_registry"]:
        raise AssertionError("formal API task was not registered")
    output_path = Path(result["output_path"])
    if not output_path.is_file():
        raise AssertionError("formal API Result output is missing")
    with Image.open(output_path) as image:
        image.load()

    return {
        "HTTP_STATUS": 200,
        "TASK_ID": task_id,
        "RESULT_ID": result_id,
        "SOURCE_TOKEN_PRESENT": bool(source_token),
        "LIFECYCLE": [item["status"] for item in task["lifecycle"]],
        "DIAGNOSIS": result["analysis"]["OBJECTIVE_DIAGNOSIS"],
        "DECISION": result["analysis"]["PARAMETER_DECISION_OUTCOME"],
        "CORRECTION_PARAMETERS": result["parameters"]["correction_parameters"],
        "D3_ACTION": result["d3_final_action"],
        "OUTPUT_PATH": str(output_path.relative_to(ROOT)),
        "OUTPUT_SHA256": _hash(output_path),
    }


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(f"validation output already exists: {OUTPUT}")
    branch = _git_value("branch", "--show-current")
    head = _git_value("rev-parse", "HEAD")
    product_version = json.loads(PRODUCT_VERSION.read_text(encoding="utf-8"))
    pre_run_hashes = _file_hashes(CODE_FINGERPRINT_PATHS)
    pre_run_fingerprint = _fingerprint(pre_run_hashes)
    d60_02_hashes_before = _file_hashes(FROZEN_D60_02_PATHS)
    d3_hashes_before = _file_hashes(FROZEN_D3_PATHS)
    cases, source_hashes = _cases()
    OUTPUT.mkdir(parents=True, exist_ok=False)
    result_dir = OUTPUT / "visual_results"
    formal_dir = OUTPUT / "formal_runtime"
    result_dir.mkdir()
    formal_dir.mkdir()
    records: list[dict[str, object]] = []
    cells: list[tuple[str, np.ndarray]] = []
    diagnosis_correct = 0
    problem_count = 0
    selection_correct = selection_count = 0
    parameter_correct = parameter_count = 0
    magnitude_correct = magnitude_count = 0
    insufficient_correct = insufficient_count = 0
    normal_count = normal_adjusted = 0
    protected_count = protected_adjusted = 0

    for case in cases:
        person_regions = case.person_regions
        d1 = analyze_color_usability(case.pixels, person_regions=person_regions)
        diagnosis = build_objective_diagnosis(d1)
        parameter_decision = decide_correction_parameters(diagnosis)
        bind_parameter_decision(d1, parameter_decision)
        d3 = audit_candidate(case.pixels, d1, person_regions=person_regions)
        diagnosis_pass = bool(case.diagnosis_check(diagnosis))
        if case.actual_problem:
            problem_count += 1
            diagnosis_correct += int(diagnosis_pass)
        expected = EXPECTED_RESULTS.get(case.name)
        if case.actual_problem and expected is None:
            raise AssertionError(f"actual problem has no EXPECTED_DECISION_CLASS: {case.name}")
        expected_decision_class = expected[0] if expected else None
        expected_parameter = expected[1] if expected else None
        expected_sign = expected[2] if expected else 0
        expected_magnitude_range = expected[3] if expected else None
        selection_pass = None
        direction_pass = None
        magnitude_pass = None
        if case.actual_problem:
            selection_count += 1
            selection_pass = bool(
                parameter_decision.outcome.value == expected_decision_class
                and (
                    parameter_decision.active_parameters == (expected_parameter,)
                    if expected_parameter
                    else not parameter_decision.active_parameters
                )
            )
            selection_correct += int(selection_pass)
        if expected_parameter:
            parameter_count += 1
            actual_value = getattr(parameter_decision.correction_parameters, expected_parameter)
            direction_pass = int(np.sign(actual_value)) == expected_sign
            parameter_correct += int(direction_pass)
            magnitude_count += 1
            magnitude_pass = bool(
                expected_magnitude_range[0]
                <= abs(float(actual_value))
                <= expected_magnitude_range[1]
            )
            magnitude_correct += int(magnitude_pass)
        if expected_decision_class == ParameterDecisionOutcome.INSUFFICIENT_EVIDENCE.value:
            insufficient_count += 1
            insufficient_correct += int(
                parameter_decision.outcome == ParameterDecisionOutcome.INSUFFICIENT_EVIDENCE
                and not parameter_decision.active_parameters
            )
        active = bool(parameter_decision.active_parameters)
        if case.name == "15_normal_photo":
            normal_count += 1
            normal_adjusted += int(active)
        if case.protected_scene:
            protected_count += 1
            protected_adjusted += int(active)
        if active:
            execution = execute_basic_correction(case.pixels, parameter_decision.correction_parameters)
            visual = execution.candidate_image
        else:
            visual = case.pixels.copy()
        Image.fromarray(visual, mode="RGB").save(result_dir / f"{case.name}.png")
        cells.extend(((f"{case.name} source", case.pixels), (f"{case.name} result", visual)))
        records.append({
            "CASE_ID": case.name,
            "SOURCE": case.source,
            "SOURCE_PIXEL_SHA256": hashlib.sha256(case.pixels.tobytes()).hexdigest(),
            "SOURCE_TYPE": case.source_type,
            "SOURCE_ATTRIBUTION": case.source_attribution,
            "CATEGORY": case.category,
            "DIAGNOSIS": diagnosis.to_dict(),
            "DECISION": parameter_decision.outcome.value,
            "CORRECTION_PARAMETERS": parameter_decision.correction_parameters.to_record(),
            "NO_CORRECTION_REASON": list(parameter_decision.no_correction_reasons),
            "INSUFFICIENT_EVIDENCE_REASON": list(parameter_decision.insufficient_evidence_reasons),
            "CONFIDENCE": parameter_decision.decision_confidence,
            "D3_ACTION": d3.final_action.value,
            "D3_STATUS": d3.status,
            "D3_REPLAY_PASS": (d3.audit_metrics.get("basic_correction_replay") or {}).get("PASS_STATUS", {}).get("REPLAY_PASS", "NOT_APPLICABLE"),
            "DIAGNOSIS_DIRECTION_CORRECT": diagnosis_pass,
            "EXPECTED_DECISION_CLASS": expected_decision_class,
            "EXPECTED_PARAMETER": expected_parameter,
            "PARAMETER_SELECTION_CORRECT": selection_pass,
            "PARAMETER_DIRECTION_CORRECT": direction_pass,
            "PARAMETER_MAGNITUDE_RANGE": expected_magnitude_range,
            "PARAMETER_MAGNITUDE_REASONABLE": magnitude_pass,
            "COVERAGE_NOTE": case.coverage_note,
        })

    _sheet(cells).save(OUTPUT / "visual_validation_contact_sheet.jpg", quality=94, subsampling=0)
    formal_records = []
    for sample, source in (
        ("normal", INPUTS / "D01_01.jpg"),
        ("warm", INPUTS / "D01_02.png"),
        ("under", INPUTS / "D01_04.png"),
        ("mixed", INPUTS / "D01_07.png"),
    ):
        suffix = ".jpg" if source.suffix.lower() in {".jpg", ".jpeg"} else ".png"
        runtime = run_formal_color_runtime(source, formal_dir / f"{sample}{suffix}")
        formal_records.append({
            "sample": sample,
            "source": str(source.relative_to(ROOT)),
            "parameter_decision_outcome": runtime.analysis["PARAMETER_DECISION_OUTCOME"],
            "d3_final_action": runtime.d3_final_action,
            "result_action": runtime.result_action,
            "output_selected": runtime.output_selected,
            "output_path": runtime.output_path,
            "source_sha256": runtime.source_sha256,
            "output_sha256": runtime.output_sha256,
        })

    formal_api = _run_formal_api(OUTPUT / "formal_api")

    for path, digest in source_hashes.items():
        if _hash(path) != digest:
            raise AssertionError(f"protected sample changed: {path}")
    if problem_count <= 0 or selection_count <= 0 or parameter_count <= 0:
        raise AssertionError("benchmark metric denominator is empty")
    if magnitude_count <= 0 or insufficient_count <= 0 or protected_count <= 0:
        raise AssertionError("benchmark safety metric denominator is empty")
    metrics = {
        "actual_problem_count": problem_count,
        "diagnosis_direction_count": problem_count,
        "diagnosis_direction_accuracy": round(diagnosis_correct / max(problem_count, 1), 4),
        "parameter_selection_count": selection_count,
        "parameter_selection_accuracy": round(selection_correct / selection_count, 4),
        "parameter_direction_count": parameter_count,
        "parameter_direction_accuracy": round(parameter_correct / parameter_count, 4),
        "parameter_magnitude_reasonable_count": magnitude_count,
        "parameter_magnitude_reasonable_rate": round(magnitude_correct / magnitude_count, 4),
        "normal_image_count": normal_count,
        "unnecessary_adjustment_rate": round(normal_adjusted / max(normal_count, 1), 4),
        "expected_insufficient_evidence_count": insufficient_count,
        "insufficient_evidence_correct_rate": round(insufficient_correct / insufficient_count, 4),
        "protected_scene_count": protected_count,
        "scene_false_correction_rate": round(protected_adjusted / protected_count, 4),
        "observed_insufficient_evidence_count": sum(record["DECISION"] == ParameterDecisionOutcome.INSUFFICIENT_EVIDENCE.value for record in records),
    }
    if diagnosis_correct != problem_count:
        raise AssertionError("diagnosis direction benchmark failed")
    if selection_correct != selection_count:
        raise AssertionError("parameter selection benchmark failed")
    if parameter_correct != parameter_count:
        raise AssertionError("parameter direction benchmark failed")
    if magnitude_correct != magnitude_count:
        raise AssertionError("parameter magnitude benchmark failed")
    if insufficient_correct != insufficient_count:
        raise AssertionError("insufficient-evidence benchmark failed")
    if normal_adjusted or protected_adjusted:
        raise AssertionError("normal/protected scene received an unnecessary correction")

    post_run_hashes = _file_hashes(CODE_FINGERPRINT_PATHS)
    post_run_fingerprint = _fingerprint(post_run_hashes)
    d60_02_hashes_after = _file_hashes(FROZEN_D60_02_PATHS)
    d3_hashes_after = _file_hashes(FROZEN_D3_PATHS)
    if pre_run_fingerprint != post_run_fingerprint:
        raise AssertionError("code changed during formal evidence run")
    if d60_02_hashes_before != d60_02_hashes_after:
        raise AssertionError("D60-02 frozen core changed during formal evidence run")
    if d3_hashes_before != d3_hashes_after:
        raise AssertionError("D3 frozen core changed during formal evidence run")
    if branch != _git_value("branch", "--show-current") or head != _git_value("rev-parse", "HEAD"):
        raise AssertionError("Git identity changed during formal evidence run")
    staging_empty = not bool(_git_value("diff", "--cached", "--name-only"))
    if not staging_empty:
        raise AssertionError("staging is not empty")

    manifest = {
        "stage": "D60-03R",
        "identity": {
            "BRANCH": branch,
            "HEAD": head,
            "PRODUCT_VERSION": product_version,
            "STAGING_EMPTY": staging_empty,
        },
        "code_binding": {
            "PRE_RUN_CODE_FINGERPRINT": pre_run_fingerprint,
            "POST_RUN_CODE_FINGERPRINT": post_run_fingerprint,
            "FINGERPRINT_MATCH": pre_run_fingerprint == post_run_fingerprint,
            "PRE_RUN_SHA256": pre_run_hashes,
            "POST_RUN_SHA256": post_run_hashes,
        },
        "frozen_integrity": {
            "D60_02_CORE_HASH_BEFORE": d60_02_hashes_before,
            "D60_02_CORE_HASH_AFTER": d60_02_hashes_after,
            "D60_02_FROZEN_INTEGRITY": d60_02_hashes_before == d60_02_hashes_after,
            "D3_CORE_HASH_BEFORE": d3_hashes_before,
            "D3_CORE_HASH_AFTER": d3_hashes_after,
            "D3_INTEGRITY": d3_hashes_before == d3_hashes_after,
        },
        "sample_count": len(records),
        "metrics": metrics,
        "expected_results": EXPECTED_RESULTS,
        "samples": records,
        "formal_runtime": formal_records,
        "formal_api": formal_api,
        "source_hashes_unchanged": {str(path.relative_to(ROOT)): digest for path, digest in sorted(source_hashes.items())},
        "real_sample_requirements": {
            "REAL_SUNSET": "tests/fixtures/color_correction/d60_03r/real_sunset_landscape.jpg",
            "REAL_LANDSCAPE": "tests/fixtures/color_correction/d60_03r/real_mountain_lake_landscape.jpg",
            "AI_GENERATED_SAMPLE": "tests/fixtures/color_correction/d60_03r/ai_generated_product_studio.png",
            "AI_GENERATED_SOURCE_TYPE": "AI_GENERATED",
        },
        "limitations": [],
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "COMPLETE", "output": str(OUTPUT), "metrics": metrics, "formal_api": formal_api}, ensure_ascii=False))


if __name__ == "__main__":
    main()
