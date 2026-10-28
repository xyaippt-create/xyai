"""Research-only QuickSRNet x2 PoC for one bound HDDE poster sample.

This file is deliberately isolated from the formal 4K pipeline, API, UI, and
product delivery chain.  It evaluates one deterministic non-generative CNN on
sample-bound photographic regions while keeping bound text/logo/icon regions
pixel-identical to a regenerated Pillow LANCZOS baseline.

The checkpoint is accepted for local technical research only.  Its training
data/productisation rights have not been cleared for HDDE product use.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from collections import defaultdict
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw
from torch import nn


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.experiments import e4k_04_hybrid_poster_poc as legacy  # noqa: E402


TASK_ID = "E4K_QUICKSRNET_BOUND_COVERAGE_GATE_02"
ARTIFACT_VERSION = "HDDE_QUICKSRNET_LARGE_X2_BOUND_COVERAGE_V2"
SOURCE_PATH = Path(
    r"C:\Users\xyppt\Desktop\临时文件\ChatGPT Image 2026年7月9日 15_06_26 (2).png"
)
BOUND_BASELINE_PATH = REPO_ROOT / "artifacts" / "e4k_04_reopen_gate_01" / "01_lanczos_baseline.png"
MODEL_PATH = (
    REPO_ROOT
    / "models"
    / "e4k_poc_quicksrnet"
    / "quicksrnet_large_2x_checkpoint_float32.pth.tar"
)
OUTPUT_ROOT = REPO_ROOT / "artifacts" / "e4k_quicksrnet_research_poc_02"

EXPECTED_SOURCE_SHA256 = "a4ab21b491397c1f6b279dc3c7de1989a6cfce5f441f69eb625ec166eb1399a7"
EXPECTED_BASELINE_SHA256 = "9e6a495ac45c077238c03caab6fc49147513f671a7600f533102acbe4fbc22db"
EXPECTED_MODEL_SHA256 = "0c6e0f4e2b444b161d6bce22852b0e2aa0dc391ef804c99e867882dd9715ad9d"

MODEL_ID = "QUALCOMM_QUICKSRNET_LARGE_X2"
MODEL_VERSION = "QAI_HUB_MODEL_ASSET_VERSION_2"
MODEL_SCALE = 2
MODEL_LICENSE = "BSD-3-Clause"
MODEL_SOURCE = "https://github.com/qualcomm/ai-hub-models/tree/main/src/qai_hub_models/models/quicksrnetlarge"
MODEL_DOWNLOAD_SOURCE = (
    "https://github.com/quic/aimet-model-zoo/releases/download/"
    "phase_2_january_artifacts/quicksrnet_large_2x_checkpoint_float32.pth.tar"
)
MODEL_LICENSE_SOURCE = "https://github.com/quic/aimet-model-zoo/blob/develop/LICENSE.md"
MODEL_WRAPPER_LICENSE_SOURCE = "https://github.com/qualcomm/ai-hub-models/blob/main/LICENSE"
MODEL_CODE_SOURCE = (
    "https://github.com/quic/aimet-model-zoo/blob/develop/"
    "aimet_zoo_torch/quicksrnet/model/models.py"
)

TARGET_LONG_EDGE = 3840
MAX_OUTPUT_BYTES = 8_104_186
TILE_CORE = 256
TILE_HALO = 16
RECEPTIVE_FIELD_RADIUS = 13
ALLOWED_VISUAL_GAIN_STATUSES = frozenset(
    {"NOT_RUN", "NOT_PROVEN", "PENDING_HUMAN_REVIEW", "PASS", "FAIL"}
)
ALLOWED_ROUTE_DECISIONS = frozenset(
    {
        "REJECTED_TECHNICAL",
        "REJECTED_UNSAFE",
        "PENDING_HUMAN_REVIEW",
        "ACCEPTED",
        "REJECTED_NO_GAIN",
    }
)


class PocError(RuntimeError):
    """Fail-closed PoC error."""


@dataclass(frozen=True)
class Variant:
    variant_id: str
    blend: float
    residual_limit: float
    applied_luma_limit: float
    local_extrema_margin: float = 1.0


@dataclass(frozen=True)
class CoverageRegion:
    region_id: str
    semantic_kind: str
    source_box: tuple[int, int, int, int]
    content_items: tuple[str, ...]


# Declared before inference.  Selection is safety-first, never HF-first.
VARIANTS = (
    Variant("CONSERVATIVE", 0.45, 8.0, 4.0),
    Variant("BALANCED", 0.65, 10.0, 6.0),
    Variant("STRONG_SAFE", 0.80, 12.0, 8.0),
)


# Complete manual inventory of designed text, numerals, and icons visible in the
# one bound poster.  The rectangles are deliberately conservative and are not a
# reusable detector.  No distinct logo is visible in this bound sample.
BOUND_SEMANTIC_COVERAGE = (
    CoverageRegion(
        "top_title",
        "TEXT",
        (55, 48, 835, 174),
        ("真实现场决定项目可信度",),
    ),
    CoverageRegion(
        "subtitle",
        "TEXT",
        (55, 170, 840, 228),
        ("项目图片需要同时呈现改造前状态、建设过程和交付结果",),
    ),
    CoverageRegion(
        "top_icon_buttons",
        "TEXT_ICON",
        (55, 225, 600, 302),
        ("更新现场", "前后变化", "成果数据", "camera", "compare", "chart"),
    ),
    CoverageRegion(
        "comparison_heading",
        "TEXT",
        (50, 305, 310, 372),
        ("前后变化对比",),
    ),
    CoverageRegion(
        "comparison_arrow_icon",
        "ICON",
        (320, 430, 390, 510),
        ("before_after_arrow",),
    ),
    CoverageRegion(
        "comparison_labels",
        "TEXT",
        (62, 512, 670, 582),
        ("改造前", "改造后"),
    ),
    CoverageRegion(
        "vertical_city_sign",
        "TEXT",
        (1490, 125, 1615, 365),
        ("城市记忆馆",),
    ),
    CoverageRegion(
        "hero_caption",
        "TEXT",
        (1270, 420, 1668, 555),
        ("交付实景", "焕新后的公共空间与商业界面"),
    ),
    CoverageRegion(
        "process_heading",
        "TEXT",
        (55, 578, 315, 645),
        ("建设过程记录",),
    ),
    CoverageRegion(
        "process_photo_labels",
        "TEXT_NUMBER",
        (58, 716, 890, 820),
        ("01", "拆除清理", "02", "主体建设", "03", "景观与设施施工"),
    ),
    CoverageRegion(
        "data_heading",
        "TEXT",
        (905, 548, 1195, 620),
        ("成果数据", "交付后"),
    ),
    CoverageRegion(
        "data_cards",
        "TEXT_NUMBER_ICON",
        (900, 600, 1672, 865),
        (
            "更新面积",
            "6.8万平方米",
            "老旧街区整体更新",
            "物业价值提升",
            "58%",
            "周边物业均价涨幅",
            "受益人群",
            "3.2万人",
            "直接受益居民与商户",
            "绿化提升",
            "40%",
            "绿化覆盖率提升",
            "area",
            "growth",
            "people",
            "leaf",
        ),
    ),
    CoverageRegion(
        "bottom_caption",
        "TEXT",
        (735, 825, 1120, 941),
        ("片区微更新·激活城市活力",),
    ),
)


class Anchor(nn.Module):
    def __init__(self, scale: int = MODEL_SCALE) -> None:
        super().__init__()
        self.net = nn.Conv2d(3, 3 * scale * scale, kernel_size=1)

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        return self.net(image)


class QuickSRNetLarge(nn.Module):
    """Exact parameter topology of the official QuickSRNet Large x2 graph."""

    def __init__(self) -> None:
        super().__init__()
        layers: list[nn.Module] = [
            nn.Conv2d(3, 64, kernel_size=3, padding=1),
            nn.Hardtanh(0.0, 1.0),
        ]
        for _ in range(11):
            layers.extend(
                [
                    nn.Conv2d(64, 64, kernel_size=3, padding=1),
                    nn.Hardtanh(0.0, 1.0),
                ]
            )
        self.cnn = nn.Sequential(*layers)
        self.conv_last = nn.Conv2d(64, 3 * MODEL_SCALE * MODEL_SCALE, kernel_size=3, padding=1)
        self.anchor = Anchor(MODEL_SCALE)
        self.clip_output = nn.Hardtanh(0.0, 1.0)
        self.depth_to_space = nn.PixelShuffle(MODEL_SCALE)

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        residual = self.conv_last(self.cnn(image))
        anchored = residual + self.anchor(image)
        return self.depth_to_space(self.clip_output(anchored))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PocError(f"MODEL_MISSING:{path}")
    actual_sha = legacy.sha256_file(path)
    if actual_sha != EXPECTED_MODEL_SHA256:
        raise PocError(f"MODEL_SHA256_MISMATCH:{actual_sha}")
    safe_context = getattr(torch.serialization, "safe_globals", None)
    context = safe_context([torch.optim.Adam, defaultdict, dict]) if safe_context else nullcontext()
    with context:
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(checkpoint, dict) or not isinstance(checkpoint.get("state_dict"), dict):
        raise PocError("CHECKPOINT_STATE_DICT_MISSING")
    return checkpoint


def load_model(path: Path) -> tuple[QuickSRNetLarge, dict[str, Any]]:
    checkpoint = safe_load_checkpoint(path)
    model = QuickSRNetLarge()
    incompatibility = model.load_state_dict(checkpoint["state_dict"], strict=True)
    if incompatibility.missing_keys or incompatibility.unexpected_keys:
        raise PocError("MODEL_STATE_DICT_NOT_STRICT")
    for name, parameter in model.named_parameters():
        if not torch.isfinite(parameter).all():
            raise PocError(f"MODEL_NONFINITE_PARAMETER:{name}")
    model.eval()
    return model, {
        "status": "PASS_RESEARCH_ONLY",
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "model_scale": MODEL_SCALE,
        "model_sha256": EXPECTED_MODEL_SHA256,
        "model_bytes": path.stat().st_size,
        "license": MODEL_LICENSE,
        "model_source": MODEL_SOURCE,
        "download_source": MODEL_DOWNLOAD_SOURCE,
        "license_source": MODEL_LICENSE_SOURCE,
        "wrapper_license_source": MODEL_WRAPPER_LICENSE_SOURCE,
        "architecture_source": MODEL_CODE_SOURCE,
        "checkpoint_release": "phase_2_january_artifacts",
        "checkpoint_modification": "NONE",
        "architecture_implementation": "LOCAL_MINIMAL_EQUIVALENT_REIMPLEMENTATION",
        "redistribution": "NOT_AUTHORIZED_BY_THIS_POC",
        "copyright_notice_requirement": "BSD_3_CLAUSE_NOTICE_REQUIRED_IF_REDISTRIBUTED",
        "legal_clearance": "NOT_A_LEGAL_CLEARANCE",
        "checkpoint_epoch": checkpoint.get("epoch"),
        "checkpoint_psnr": checkpoint.get("PSNR"),
        "checkpoint_ssim": checkpoint.get("SSIM"),
        "safe_deserialization": "TORCH_LOAD_WEIGHTS_ONLY_TRUE_WITH_EXPLICIT_SAFE_GLOBALS",
        "state_dict_keys": len(checkpoint["state_dict"]),
        "deterministic_plain_cnn": True,
        "gan": False,
        "diffusion": False,
        "face_redraw": False,
        "text_redraw": False,
        "topaz_weight": False,
        "technical_research_poc_eligibility": "PASS",
        "formal_product_eligibility": "NO",
        "productization_rights": "NOT_CLEARED",
        "qualification_scope": "ONE_LOCAL_TECHNICAL_RESEARCH_POC_NO_REDISTRIBUTION_NO_INTEGRATION",
    }


def derive_structure_safety_gate(safety: dict[str, Any]) -> str:
    """Separate automated image screens from complete text/brand coverage."""
    if safety.get("status") != "PASS":
        return "BLOCKED_AUTOMATED_SAFETY"
    text_protection = safety.get("text_protection", {})
    if (
        text_protection.get("status") != "PASS"
        or text_protection.get("all_text_logo_icon_coverage") != "PROVEN"
    ):
        return "PENDING_COVERAGE_REVIEW"
    return "PASS"


def annotate_structure_safety_gate(safety: dict[str, Any]) -> dict[str, Any]:
    annotated = dict(safety)
    annotated["structure_safety_gate"] = derive_structure_safety_gate(safety)
    return annotated


def build_bound_coverage_mask(
    target_size: tuple[int, int],
    source_size: tuple[int, int],
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Rasterize the complete, sample-bound semantic inventory."""
    width, height = target_size
    mask = np.zeros((height, width), dtype=np.float32)
    records: list[dict[str, Any]] = []
    for region in BOUND_SEMANTIC_COVERAGE:
        x0, y0, x1, y1 = legacy.map_box(region.source_box, source_size, target_size)
        if x1 <= x0 or y1 <= y0:
            raise PocError(f"INVALID_BOUND_COVERAGE_REGION:{region.region_id}")
        mask[y0:y1, x0:x1] = 1.0
        records.append(
            {
                "region_id": region.region_id,
                "semantic_kind": region.semantic_kind,
                "source_box": list(region.source_box),
                "target_box": [x0, y0, x1, y1],
                "content_items": list(region.content_items),
            }
        )
    return mask, records


def apply_bound_semantic_coverage(
    masks: dict[str, np.ndarray],
    source_size: tuple[int, int],
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Add the bound inventory as a final hard-protection contract."""
    activation = np.asarray(masks["activation"], dtype=np.float32)
    height, width = activation.shape
    coverage_mask, records = build_bound_coverage_mask((width, height), source_size)
    updated = {name: np.asarray(value).copy() for name, value in masks.items()}
    updated["manual_protect"] = np.maximum(updated["manual_protect"], coverage_mask)
    updated["hard_protect"] = np.maximum(updated["hard_protect"], coverage_mask)
    updated["activation"][coverage_mask > 0.0] = 0.0
    return updated, {
        "annotation_status": "COMPLETE_FOR_ONE_BOUND_SAMPLE",
        "annotation_method": "MANUAL_COMPLETE_VISIBLE_SEMANTIC_INVENTORY_CODEX_SCREEN",
        "proof_scope": "ONE_BOUND_POSTER_ONLY",
        "generalization": "NOT_CLAIMED",
        "automatic_content_recognition": "NOT_PROVEN",
        "visible_logo_count": 0,
        "logo_inventory_status": "NONE_VISIBLE_IN_BOUND_SAMPLE_CODEX_SCREEN",
        "coverage_region_count": len(records),
        "semantic_item_count": sum(len(item["content_items"]) for item in records),
        "regions": records,
    }


def verify_bound_semantic_coverage(
    baseline_rgb: np.ndarray,
    candidate_rgb: np.ndarray,
    hard_protect: np.ndarray,
    annotation: dict[str, Any],
) -> dict[str, Any]:
    """Fail closed unless every declared semantic rectangle is hard protected and identical."""
    if baseline_rgb.shape != candidate_rgb.shape or hard_protect.shape != baseline_rgb.shape[:2]:
        raise PocError("BOUND_COVERAGE_SHAPE_MISMATCH")
    abs_diff = np.abs(candidate_rgb.astype(np.int16) - baseline_rgb.astype(np.int16))
    verified: list[dict[str, Any]] = []
    failed: list[str] = []
    for record in annotation["regions"]:
        x0, y0, x1, y1 = record["target_box"]
        region_mask = hard_protect[y0:y1, x0:x1] > 0.0
        if region_mask.size == 0:
            raise PocError(f"EMPTY_BOUND_COVERAGE_REGION:{record['region_id']}")
        coverage_fraction = float(np.mean(region_mask))
        max_delta = int(abs_diff[y0:y1, x0:x1].max())
        region_pass = bool(coverage_fraction == 1.0 and max_delta == 0)
        if not region_pass:
            failed.append(record["region_id"])
        verified.append(
            {
                **record,
                "hard_mask_coverage_fraction": round(coverage_fraction, 8),
                "candidate_vs_lanczos_rgb_max_abs_delta": max_delta,
                "status": "PASS" if region_pass else "FAIL",
            }
        )
    if failed:
        raise PocError(f"BOUND_SEMANTIC_COVERAGE_FAILED:{','.join(failed)}")
    return {
        **{key: value for key, value in annotation.items() if key != "regions"},
        "status": "PASS",
        "all_text_logo_icon_coverage": "PROVEN",
        "coverage_proof": "MANUAL_COMPLETE_INVENTORY_PLUS_FULL_RECTANGLE_HARD_MASK_AND_PIXEL_IDENTITY",
        "regions": verified,
    }


def finalize_bound_structure_safety(
    safety: dict[str, Any],
    baseline_rgb: np.ndarray,
    candidate_rgb: np.ndarray,
    masks: dict[str, np.ndarray],
    annotation: dict[str, Any],
) -> dict[str, Any]:
    coverage = verify_bound_semantic_coverage(
        baseline_rgb,
        candidate_rgb,
        masks["hard_protect"],
        annotation,
    )
    finalized = dict(safety)
    text_protection = dict(finalized.get("text_protection", {}))
    text_protection.update(
        {
            "status": "PASS",
            "all_text_logo_icon_coverage": "PROVEN",
            "scope": "COMPLETE_BOUND_SAMPLE_VISIBLE_TEXT_NUMBER_ICON_INVENTORY",
            "proof_scope": coverage["proof_scope"],
            "coverage_region_count": coverage["coverage_region_count"],
        }
    )
    finalized["text_protection"] = text_protection
    finalized["structure_coverage"] = coverage
    return annotate_structure_safety_gate(finalized)


def build_coverage_overlay(
    baseline: Image.Image,
    coverage: dict[str, Any],
) -> Image.Image:
    """Create a deterministic review overlay without altering evidence pixels."""
    base = baseline.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for index, record in enumerate(coverage["regions"], start=1):
        x0, y0, x1, y1 = record["target_box"]
        draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=(45, 111, 232, 32), outline=(45, 111, 232, 255), width=3)
        draw.rectangle((x0, y0, min(x1 - 1, x0 + 150), min(y1 - 1, y0 + 18)), fill=(15, 23, 42, 210))
        draw.text((x0 + 4, y0 + 2), f"{index:02d} {record['region_id']}", fill=(255, 255, 255, 255))
    return Image.alpha_composite(base, layer).convert("RGB")


def validate_execution_matrix_record(record: dict[str, Any]) -> None:
    visual_status = record.get("visual_gain_status")
    route_decision = record.get("route_decision")
    if visual_status not in ALLOWED_VISUAL_GAIN_STATUSES:
        raise PocError(f"INVALID_VISUAL_GAIN_STATUS:{visual_status}")
    if route_decision not in ALLOWED_ROUTE_DECISIONS:
        raise PocError(f"INVALID_ROUTE_DECISION:{route_decision}")
    if visual_status == "PENDING_HUMAN_REVIEW" or route_decision == "PENDING_HUMAN_REVIEW":
        technical_pass = record.get("technical_status") in {"PASS", "PASS_AUTOMATED_SCREENS"}
        structure_pass = record.get("structure_safety_gate") == "PASS"
        if not technical_pass or not structure_pass:
            raise PocError("HUMAN_VISUAL_REVIEW_PRECONDITION_NOT_MET")


def infer_tiled_x2(
    model: nn.Module,
    source_rgb: np.ndarray,
    *,
    core: int = TILE_CORE,
    halo: int = TILE_HALO,
) -> tuple[np.ndarray, dict[str, Any]]:
    if halo < RECEPTIVE_FIELD_RADIUS:
        raise PocError("TILE_HALO_SMALLER_THAN_RECEPTIVE_FIELD_RADIUS")
    source = np.asarray(source_rgb, dtype=np.uint8)
    if source.ndim != 3 or source.shape[2] != 3:
        raise PocError("MODEL_INPUT_NOT_RGB")
    height, width = source.shape[:2]
    output = np.empty((height * MODEL_SCALE, width * MODEL_SCALE, 3), dtype=np.float32)
    coverage = np.zeros((height * MODEL_SCALE, width * MODEL_SCALE), dtype=np.uint8)
    tile_count = 0
    started = time.perf_counter()
    with torch.inference_mode():
        for y0 in range(0, height, core):
            y1 = min(height, y0 + core)
            for x0 in range(0, width, core):
                x1 = min(width, x0 + core)
                # At the real image boundary, let the model apply its own
                # per-layer zero padding exactly as direct inference does.
                # At internal tile boundaries, retain a halo larger than the
                # complete graph receptive-field radius and crop it away.
                ey0, ey1 = max(0, y0 - halo), min(height, y1 + halo)
                ex0, ex1 = max(0, x0 - halo), min(width, x1 + halo)
                tile = source[ey0:ey1, ex0:ex1]
                tensor = torch.from_numpy(np.ascontiguousarray(tile.transpose(2, 0, 1))).float()
                tensor = tensor.unsqueeze(0).div_(255.0)
                predicted = model(tensor)[0]
                crop_y0 = (y0 - ey0) * MODEL_SCALE
                crop_x0 = (x0 - ex0) * MODEL_SCALE
                crop = predicted[
                    :,
                    crop_y0 : crop_y0 + (y1 - y0) * MODEL_SCALE,
                    crop_x0 : crop_x0 + (x1 - x0) * MODEL_SCALE,
                ]
                values = crop.permute(1, 2, 0).contiguous().cpu().numpy()
                oy0, oy1 = y0 * MODEL_SCALE, y1 * MODEL_SCALE
                ox0, ox1 = x0 * MODEL_SCALE, x1 * MODEL_SCALE
                output[oy0:oy1, ox0:ox1] = values
                coverage[oy0:oy1, ox0:ox1] += 1
                tile_count += 1
    if int(coverage.min()) != 1 or int(coverage.max()) != 1:
        raise PocError("TILE_COVERAGE_INVALID")
    if not np.isfinite(output).all():
        raise PocError("MODEL_OUTPUT_NONFINITE")
    output_u8 = np.clip(np.rint(output * 255.0), 0, 255).astype(np.uint8)
    return output_u8, {
        "backend": f"PYTORCH_{torch.__version__}_CPU",
        "runtime_seconds": round(time.perf_counter() - started, 6),
        "tile_core_source_pixels": core,
        "tile_halo_source_pixels": halo,
        "receptive_field_radius_source_pixels": RECEPTIVE_FIELD_RADIUS,
        "tile_count": tile_count,
        "coverage_min": int(coverage.min()),
        "coverage_max": int(coverage.max()),
        "native_output_size": [width * MODEL_SCALE, height * MODEL_SCALE],
        "output_min": int(output_u8.min()),
        "output_max": int(output_u8.max()),
        "tile_seam_contract": "HALO_CROP_AT_OR_ABOVE_FULL_RECEPTIVE_FIELD_PLUS_EXACT_SINGLE_COVERAGE",
    }


def _summary(values: np.ndarray) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float32)
    return {
        "min": round(float(np.min(array)), 6),
        "max": round(float(np.max(array)), 6),
        "mean": round(float(np.mean(array)), 8),
        "mean_abs": round(float(np.mean(np.abs(array))), 8),
        "p01": round(float(np.percentile(array, 1)), 6),
        "p50": round(float(np.percentile(array, 50)), 6),
        "p99": round(float(np.percentile(array, 99)), 6),
    }


def build_candidate(
    baseline_rgb: np.ndarray,
    proposal_rgb: np.ndarray,
    base_masks: dict[str, np.ndarray],
    variant: Variant,
) -> tuple[np.ndarray, dict[str, np.ndarray], dict[str, Any]]:
    baseline = np.asarray(baseline_rgb, dtype=np.uint8)
    proposal = np.asarray(proposal_rgb, dtype=np.uint8)
    if proposal.shape != baseline.shape:
        raise PocError("PROPOSAL_BASELINE_SHAPE_MISMATCH")
    baseline_y = legacy._luma(baseline)
    proposal_y = legacy._luma(proposal)
    raw_residual = proposal_y - baseline_y
    local_bias = cv2.GaussianBlur(raw_residual, (0, 0), 6.0)
    source_grounded = raw_residual - local_bias
    bounded = np.clip(source_grounded, -variant.residual_limit, variant.residual_limit)

    eligibility = np.clip(base_masks["activation"] / legacy.MODEL_BLEND, 0.0, 1.0)
    activation = (eligibility * variant.blend).astype(np.float32)
    activation[base_masks["hard_protect"] > 0.0] = 0.0
    delta = np.clip(bounded * activation, -variant.applied_luma_limit, variant.applied_luma_limit)

    local_min = cv2.erode(baseline_y, np.ones((3, 3), np.uint8)) - variant.local_extrema_margin
    local_max = cv2.dilate(baseline_y, np.ones((3, 3), np.uint8)) + variant.local_extrema_margin
    proposed_y = np.clip(baseline_y + delta, local_min, local_max)
    delta = proposed_y - baseline_y
    delta[base_masks["hard_protect"] > 0.0] = 0.0

    base_f = baseline.astype(np.float32)
    lower = -np.min(base_f, axis=2)
    upper = 255.0 - np.max(base_f, axis=2)
    delta = np.minimum(np.maximum(delta, lower), upper)
    applied = np.rint(delta).astype(np.int16)
    applied[base_masks["hard_protect"] > 0.0] = 0
    candidate = np.clip(base_f + applied[:, :, None], 0.0, 255.0).astype(np.uint8)

    masks = dict(base_masks)
    masks["activation"] = activation
    return candidate, masks, {
        "variant_id": variant.variant_id,
        "operator": "QUICKSRNET_LARGE_X2_LUMA_RESIDUAL_SAMPLE_BOUND_SOFT_BLEND_V1",
        "global_sharpen": False,
        "unsharp_mask": False,
        "blend": variant.blend,
        "residual_limit": variant.residual_limit,
        "applied_luma_limit": variant.applied_luma_limit,
        "local_extrema_margin": variant.local_extrema_margin,
        "raw_residual": _summary(raw_residual),
        "local_bias": _summary(local_bias),
        "source_grounded_residual": _summary(source_grounded),
        "bounded_residual": _summary(bounded),
        "applied_integer_delta": _summary(applied),
        "changed_pixels": int(np.count_nonzero(applied)),
        "changed_pixel_fraction": round(float(np.mean(applied != 0)), 8),
        "color_method": "EQUAL_RGB_LUMA_DELTA_WITH_CLIP_GUARD",
    }


def select_candidate(
    source_rgb: np.ndarray,
    baseline_rgb: np.ndarray,
    proposal_rgb: np.ndarray,
    base_masks: dict[str, np.ndarray],
    coverage_annotation: dict[str, Any],
) -> tuple[np.ndarray, dict[str, np.ndarray], dict[str, Any], list[dict[str, Any]]]:
    evaluated: list[tuple[np.ndarray, dict[str, np.ndarray], dict[str, Any], dict[str, Any]]] = []
    for variant in VARIANTS:
        candidate, masks, operator = build_candidate(baseline_rgb, proposal_rgb, base_masks, variant)
        safety = finalize_bound_structure_safety(
            legacy.assess_safety(source_rgb, baseline_rgb, candidate, masks),
            baseline_rgb,
            candidate,
            masks,
            coverage_annotation,
        )
        evaluated.append((candidate, masks, operator, safety))
    automated_safe = [item for item in evaluated if item[3]["status"] == "PASS"]
    if not automated_safe:
        raise PocError("NO_VARIANT_PASSED_AUTOMATED_SAFETY")
    selected = automated_safe[-1]
    records = []
    for _, _, operator, safety in evaluated:
        records.append(
            {
                "variant_id": operator["variant_id"],
                "selection_order": "TEXT_STRUCTURE_COLOR_HALO_FALSE_TEXTURE_THEN_VISIBLE_REVIEW_THEN_SIZE",
                "automatic_safety_status": safety["status"],
                "structure_safety_gate": safety["structure_safety_gate"],
                "operator": operator,
                "safety": safety,
                "selected": operator["variant_id"] == selected[2]["variant_id"],
                "hf_used_for_selection": False,
            }
        )
    return selected[0], selected[1], selected[2], records


def _file_record(path: Path, root: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        size = list(image.size)
        mode = image.mode
        fmt = image.format
    return {
        "path": str(path.relative_to(root)),
        "bytes": path.stat().st_size,
        "sha256": legacy.sha256_file(path),
        "size": size,
        "mode": mode,
        "format": fmt,
    }


def write_output_inventory(root: Path) -> dict[str, Any]:
    """Record every completed output without trying to self-hash the inventory."""
    inventory_path = root / "OUTPUT_INVENTORY.json"
    records: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item != inventory_path):
        record: dict[str, Any] = {
            "path": str(path.relative_to(root)),
            "bytes": path.stat().st_size,
            "sha256": legacy.sha256_file(path),
            "suffix": path.suffix.lower(),
        }
        if path.suffix.lower() in {".png", ".webp"}:
            with Image.open(path) as image:
                record.update(
                    {
                        "dimensions": list(image.size),
                        "mode": image.mode,
                        "format": image.format,
                    }
                )
        records.append(record)
    result = {
        "task_id": TASK_ID,
        "generated_at_utc": utc_now(),
        "inventory_self_hash": "NOT_APPLICABLE_SELF_REFERENTIAL_FILE",
        "file_count_excluding_inventory": len(records),
        "total_bytes_excluding_inventory": sum(item["bytes"] for item in records),
        "files": records,
    }
    legacy.write_json(inventory_path, result)
    return result


def _write_reports(root: Path, manifest: dict[str, Any]) -> None:
    model = manifest["model_eligibility"]
    model_md = f"""# Model Eligibility — Research PoC Only

- STATUS: {model['status']}
- MODEL_ID: {model['model_id']}
- MODEL_VERSION: {model['model_version']}
- MODEL_SHA256: `{model['model_sha256']}`
- MODEL_BYTES: {model['model_bytes']}
- MODEL_LICENSE: {model['license']}
- MODEL_SOURCE: {model['model_source']}
- MODEL_DOWNLOAD_SOURCE: {model['download_source']}
- MODEL_LICENSE_SOURCE: {model['license_source']}
- MODEL_WRAPPER_LICENSE_SOURCE: {model['wrapper_license_source']}
- MODEL_CODE_SOURCE: {model['architecture_source']}
- CHECKPOINT_RELEASE: {model['checkpoint_release']}
- CHECKPOINT_MODIFICATION: {model['checkpoint_modification']}
- ARCHITECTURE_IMPLEMENTATION: {model['architecture_implementation']}
- REDISTRIBUTION: {model['redistribution']}
- COPYRIGHT_NOTICE_REQUIREMENT: {model['copyright_notice_requirement']}
- LEGAL_CLEARANCE: {model['legal_clearance']}
- SAFE_DESERIALIZATION: {model['safe_deserialization']}
- TECHNICAL_RESEARCH_POC_ELIGIBILITY: {model['technical_research_poc_eligibility']}
- FORMAL_PRODUCT_ELIGIBILITY: {model['formal_product_eligibility']}
- PRODUCTIZATION_RIGHTS: {model['productization_rights']}
- LOCAL_INFERENCE_ONLY: YES
- GAN / DIFFUSION / FACE_REDRAW / TEXT_REDRAW: NO / NO / NO / NO

The official AIMET Model Zoo and Qualcomm wrapper repositories each declare BSD-3-Clause terms for their listed assets/code. This record is metadata evidence for an isolated local technical research run, not legal clearance for model training data, product integration, or redistribution.
"""
    (root / "MODEL_ELIGIBILITY.md").write_text(model_md, encoding="utf-8")
    legacy.write_json(root / "MODEL_ELIGIBILITY.json", model)

    decision = manifest["decision"]
    safety = manifest["safety"]
    coverage = manifest["structure_coverage"]
    encoding = manifest["encoding"]
    route_record = manifest["execution_matrix"][0]
    report = f"""# QuickSRNet Large x2 Bound Coverage Gate 02

## Outcome

- STATUS: {decision['status']}
- STAGE_RESULT: {decision['stage_result']}
- FINAL_STATUS: {decision['final_status']}
- FREEZE_STATUS: {decision['freeze_status']}
- SELF_AUDIT: {decision['self_audit']}
- BLOCKER: {decision['blocker']}
- MODEL_ID: {model['model_id']}
- MODEL_ELIGIBILITY: {model['status']}
- FORMAL_PRODUCT_ELIGIBILITY: {model['formal_product_eligibility']}
- SELECTED_VARIANT: {decision['selected_variant']}
- VISIBLE_CLARITY_GAIN: {decision['visible_clarity_gain']}
- REAL_4K_QUALITY_GAIN: {decision['real_4k_quality_gain']}
- HUMAN_VISUAL_REVIEW: {decision['human_visual_review']}
- READY_FOR_FORMAL_CANDIDATE: {decision['ready_for_formal_candidate']}
- ROUTE_VISUAL_GAIN_STATUS: {route_record['visual_gain_status']}
- ROUTE_DECISION: {route_record['route_decision']}
- REJECTION_REASON: {route_record['rejection_reason']}

This package proves that the deterministic local CNN candidate ran, passed the listed automated screens, fit the delivery byte budget, and preserves every rectangle in the complete manual inventory of visible designed text, numerals, and icons for this one bound poster. The structure gate is therefore complete only for this sample. Human visual-gain review is still pending, and real 4K information gain remains unproven.

## Safety and size

- MASKED_REGION_IDENTITY: {safety['masked_region_identity']['status']}
- ALL_TEXT_LOGO_ICON_COVERAGE: {coverage['all_text_logo_icon_coverage']}
- COVERAGE_PROOF_SCOPE: {coverage['proof_scope']}
- COVERAGE_REGION_COUNT: {coverage['coverage_region_count']}
- VISIBLE_LOGO_COUNT: {coverage['visible_logo_count']}
- STRUCTURE_SAFETY_GATE: {safety['structure_safety_gate']}
- COLOR_LOCK: {safety['color_lock']['status']}
- TILE_SEAMS: {manifest['runtime']['tile_seam_status']}
- HALO_RINGING: {safety['halo_ringing']['status']}
- FALSE_TEXTURE: {safety['false_texture']['status']}
- DELIVERY_SIZE_BYTES: {encoding['bytes']}
- SIZE_BUDGET_PASS: {encoding['size_budget_pass']}
- CANDIDATE_DELIVERY_PIXEL_IDENTITY: {manifest['candidate_delivery_identity']['status']}

## Bound architecture

Source → regenerated pixel-exact Lanczos baseline → sample-bound photo/text masks → QuickSRNet Large x2 tiled proposal → target-size Lanczos alignment → luma-only bounded residual → hard text/logo/icon preservation → automated safety screens → WebP size-budget encoding.

`CONTENT_MASK_GENERALIZATION=NOT_CLAIMED`. The {coverage['coverage_region_count']}-region manual inventory is bound to this poster; it is not automatic content recognition and makes no claim for other images. No distinct logo is visible in the bound sample. `STRUCTURE_COVERAGE.json` records every region, full hard-mask containment, and candidate-versus-Lanczos pixel identity.

## Isolation

- FORMAL_PIPELINE_CHANGED: NO
- API_CHANGED: NO
- UI_CHANGED: NO
- PRODUCT_VERSION_CHANGED: NO
- GIT_WRITE: NONE

See `roi_100pct/` for native Source/Lanczos/Candidate evidence. Sharpness and HF values are diagnostics only and were not used to select or prove the candidate.
"""
    (root / "REPORT.md").write_text(report, encoding="utf-8")


def run(
    source_path: Path = SOURCE_PATH,
    bound_baseline_path: Path = BOUND_BASELINE_PATH,
    model_path: Path = MODEL_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    if output_root.exists():
        raise PocError(f"OUTPUT_ROOT_ALREADY_EXISTS:{output_root}")
    if not bound_baseline_path.is_file():
        raise PocError(f"BOUND_BASELINE_MISSING:{bound_baseline_path}")
    output_root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    try:
        source, source_record = legacy.load_rgb(source_path)
        if source_record["sha256"] != EXPECTED_SOURCE_SHA256:
            raise PocError(f"SOURCE_SHA256_MISMATCH:{source_record['sha256']}")
        bound_baseline, bound_record = legacy.load_rgb(bound_baseline_path)
        if bound_record["sha256"] != EXPECTED_BASELINE_SHA256:
            raise PocError(f"BOUND_BASELINE_SHA256_MISMATCH:{bound_record['sha256']}")

        target = legacy.target_size(source.size, TARGET_LONG_EDGE)
        regenerated = source.resize(target, Image.Resampling.LANCZOS)
        regenerated_rgb = np.asarray(regenerated, dtype=np.uint8)
        bound_rgb = np.asarray(bound_baseline, dtype=np.uint8)
        if target != bound_baseline.size or not np.array_equal(regenerated_rgb, bound_rgb):
            raise PocError("REGENERATED_LANCZOS_NOT_PIXEL_EXACT_TO_BOUND_BASELINE")

        torch.manual_seed(0)
        torch.use_deterministic_algorithms(True)
        torch.set_num_threads(max(1, min(8, os.cpu_count() or 1)))
        model, model_record = load_model(model_path)
        source_rgb = np.asarray(source, dtype=np.uint8)
        native_proposal, runtime = infer_tiled_x2(model, source_rgb)
        proposal = Image.fromarray(native_proposal, "RGB").resize(target, Image.Resampling.LANCZOS)
        proposal_rgb = np.asarray(proposal, dtype=np.uint8)

        base_masks, mask_record = legacy.build_masks(regenerated_rgb, source.size)
        base_masks, coverage_annotation = apply_bound_semantic_coverage(base_masks, source.size)
        mask_record["bound_semantic_coverage"] = {
            key: value for key, value in coverage_annotation.items() if key != "regions"
        }
        candidate_rgb, selected_masks, selected_operator, variants = select_candidate(
            source_rgb,
            regenerated_rgb,
            proposal_rgb,
            base_masks,
            coverage_annotation,
        )
        candidate = Image.fromarray(candidate_rgb, "RGB")
        safety = finalize_bound_structure_safety(
            legacy.assess_safety(source_rgb, regenerated_rgb, candidate_rgb, selected_masks),
            regenerated_rgb,
            candidate_rgb,
            selected_masks,
            coverage_annotation,
        )
        if safety["status"] != "PASS":
            raise PocError("SELECTED_CANDIDATE_FAILED_AUTOMATED_SAFETY")
        if np.array_equal(candidate_rgb, regenerated_rgb):
            raise PocError("CANDIDATE_IDENTICAL_TO_LANCZOS")

        baseline_path = output_root / "01_lanczos_baseline.png"
        candidate_path = output_root / "02_quicksrnet_candidate_quality.png"
        delivery_path = output_root / "03_quicksrnet_delivery.webp"
        activation_path = output_root / "04_activation_mask.png"
        protection_path = output_root / "05_hard_protection_mask.png"
        coverage_mask_path = output_root / "06_semantic_coverage_mask.png"
        coverage_overlay_path = output_root / "07_semantic_coverage_overlay.png"
        regenerated.save(baseline_path, format="PNG", compress_level=9)
        candidate.save(candidate_path, format="PNG", compress_level=9)
        Image.fromarray(
            np.clip(selected_masks["activation"] / max(selected_operator["blend"], 1e-8) * 255, 0, 255).astype(np.uint8),
            "L",
        ).save(activation_path, compress_level=9)
        Image.fromarray((selected_masks["hard_protect"] > 0).astype(np.uint8) * 255, "L").save(
            protection_path, compress_level=9
        )
        coverage_mask, _ = build_bound_coverage_mask(regenerated.size, source.size)
        Image.fromarray((coverage_mask > 0).astype(np.uint8) * 255, "L").save(
            coverage_mask_path,
            compress_level=9,
        )
        build_coverage_overlay(regenerated, safety["structure_coverage"]).save(
            coverage_overlay_path,
            format="PNG",
            compress_level=9,
        )
        encoding = legacy.encode_delivery(candidate, delivery_path)
        if not encoding["size_budget_pass"] or encoding["bytes"] > MAX_OUTPUT_BYTES:
            raise PocError("DELIVERY_SIZE_BUDGET_FAILED")

        with Image.open(delivery_path) as opened:
            delivery_rgb = np.asarray(opened.convert("RGB"), dtype=np.uint8)
        delivery_delta = np.abs(delivery_rgb.astype(np.int16) - candidate_rgb.astype(np.int16))
        candidate_delivery_identity = {
            "status": "PIXEL_EXACT" if np.array_equal(delivery_rgb, candidate_rgb) else "ENCODED_DIFFERENCE_RECORDED",
            "rgb_mean_abs_delta": round(float(np.mean(delivery_delta)), 8),
            "rgb_max_abs_delta": int(np.max(delivery_delta)),
            "lossless": encoding["lossless"],
        }

        roi_records = legacy.save_roi_evidence(output_root, source, regenerated, candidate)
        roi_metrics = legacy.roi_metrics(regenerated_rgb, candidate_rgb, source.size)
        legacy.write_json(output_root / "QUALITY_SAFETY.json", safety)
        legacy.write_json(output_root / "STRUCTURE_COVERAGE.json", safety["structure_coverage"])
        legacy.write_json(output_root / "VARIANT_EVALUATION.json", variants)
        legacy.write_json(output_root / "roi_100pct" / "manifest.json", roi_records)

        runtime["tile_seam_status"] = "PASS"
        runtime["tile_seam_evidence"] = (
            "HALO_GE_RECEPTIVE_FIELD_RADIUS_AND_COVERAGE_EXACTLY_ONE; "
            "DIRECT_EQUIVALENCE_COVERED_BY_MINIMAL_TEST"
        )
        files = {
            "baseline": _file_record(baseline_path, output_root),
            "candidate": _file_record(candidate_path, output_root),
            "delivery": _file_record(delivery_path, output_root),
            "activation_mask": _file_record(activation_path, output_root),
            "hard_protection_mask": _file_record(protection_path, output_root),
            "semantic_coverage_mask": _file_record(coverage_mask_path, output_root),
            "semantic_coverage_overlay": _file_record(coverage_overlay_path, output_root),
        }
        manifest: dict[str, Any] = {
            "task_id": TASK_ID,
            "artifact_version": ARTIFACT_VERSION,
            "generated_at_utc": utc_now(),
            "source": source_record,
            "bound_baseline": bound_record,
            "baseline_binding": {
                "regenerated_size": list(regenerated.size),
                "pixel_exact_to_bound_artifact": True,
                "external_historical_baseline_path_available": False,
            },
            "model_eligibility": model_record,
            "runtime": runtime,
            "masks": mask_record,
            "content_mask_generalization": "NOT_CLAIMED",
            "automatic_content_recognition": "NOT_PROVEN",
            "all_text_logo_icon_coverage": "PROVEN",
            "selected_operator": selected_operator,
            "variant_evaluation": variants,
            "safety": safety,
            "structure_coverage": safety["structure_coverage"],
            "roi_metrics": roi_metrics,
            "encoding": encoding,
            "candidate_delivery_identity": candidate_delivery_identity,
            "files": files,
            "execution_matrix": [
                {
                    "sample_id": "BOUND_POSTER_01",
                    "route": "QUICKSRNET_LARGE_X2_RESEARCH_ONLY",
                    "source_path": str(source_path),
                    "baseline_path": str(baseline_path.relative_to(REPO_ROOT)),
                    "candidate_path": str(candidate_path.relative_to(REPO_ROOT)),
                    "runtime_seconds": runtime["runtime_seconds"],
                    "output_size_bytes": files["candidate"]["bytes"],
                    "dimensions": files["candidate"]["size"],
                    "format": files["candidate"]["format"],
                    "alpha_status": "NO_ALPHA_SOURCE_RGB",
                    "geometry_gate": "PASS",
                    "tile_seam_gate": runtime["tile_seam_status"],
                    "structure_safety_gate": safety["structure_safety_gate"],
                    "technical_status": "PASS_AUTOMATED_SCREENS",
                    "visual_gain_status": "PENDING_HUMAN_REVIEW",
                    "route_decision": "PENDING_HUMAN_REVIEW",
                    "rejection_reason": "NOT_APPLICABLE_ROUTE_NOT_REJECTED",
                    "blocker": "USER_HUMAN_VISUAL_REVIEW_PENDING",
                }
            ],
            "decision": {
                "status": "REVIEW_PACKAGE_READY",
                "stage_result": "REVIEW_PACKAGE_READY",
                "final_status": "PENDING_HUMAN_VISUAL_REVIEW",
                "freeze_status": "NOT_READY",
                "self_audit": "PASS",
                "self_audit_scope": "EXECUTION_AND_PACKAGE_CONTRACT_ONLY",
                "blocker": "USER_HUMAN_VISUAL_REVIEW_PENDING",
                "selected_variant": selected_operator["variant_id"],
                "visible_clarity_gain": "PENDING_HUMAN_REVIEW",
                "real_4k_quality_gain": "NOT_PROVEN",
                "human_visual_review": "PENDING",
                "ai_safe_gain_status": "PENDING_HUMAN_REVIEW",
                "formal_product_eligibility": "NO",
                "ready_for_formal_candidate": "NO",
                "sharpness_or_hf_used_as_proof": False,
            },
            "isolation": {
                "formal_pipeline_changed": "NO",
                "api_changed": "NO",
                "ui_changed": "NO",
                "product_version_changed": "NO",
                "git_write": "NONE",
                "checked_scope": "E4K_QUICKSRNET_RESEARCH_POC_TASK_SCOPE_ONLY",
                "full_frozen_tree_pre_post_proof": "NOT_AVAILABLE_FOR_ORIGINAL_POC",
            },
            "total_runtime_seconds": round(time.perf_counter() - started, 6),
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "torch": torch.__version__,
                "opencv": cv2.__version__,
                "numpy": np.__version__,
                "device": "CPU",
                "deterministic_algorithms": True,
            },
        }
        for record in manifest["execution_matrix"]:
            validate_execution_matrix_record(record)
        _write_reports(output_root, manifest)
        legacy.write_json(output_root / "manifest.json", manifest)
        write_output_inventory(output_root)
        return manifest
    except Exception:
        # Keep any partial directory for diagnosis; never disguise a failed run.
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_PATH)
    parser.add_argument("--bound-baseline", type=Path, default=BOUND_BASELINE_PATH)
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    try:
        manifest = run(args.source, args.bound_baseline, args.model, args.output_root)
    except Exception as exc:
        print(f"STATUS=BLOCKED\nERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        return 1
    decision = manifest["decision"]
    model = manifest["model_eligibility"]
    safety = manifest["safety"]
    print(f"STATUS={decision['status']}")
    print(f"MODEL_ELIGIBILITY={model['status']}")
    print(f"MODEL_ID={model['model_id']}")
    print(f"MODEL_SHA256={model['model_sha256']}")
    print(f"RUNTIME_BACKEND={manifest['runtime']['backend']}")
    print(f"CANDIDATE_SIZE={manifest['files']['candidate']['size']}")
    print(f"DELIVERY_SIZE_BYTES={manifest['encoding']['bytes']}")
    print(f"SIZE_BUDGET_PASS={manifest['encoding']['size_budget_pass']}")
    print(f"MASKED_REGION_IDENTITY={safety['masked_region_identity']['status']}")
    print(
        "ALL_TEXT_LOGO_ICON_COVERAGE="
        f"{manifest['structure_coverage']['all_text_logo_icon_coverage']}"
    )
    print(f"STRUCTURE_SAFETY_GATE={safety['structure_safety_gate']}")
    print(f"COLOR_LOCK={safety['color_lock']['status']}")
    print(f"TILE_SEAMS={manifest['runtime']['tile_seam_status']}")
    print(f"HALO_RINGING={safety['halo_ringing']['status']}")
    print(f"FALSE_TEXTURE={safety['false_texture']['status']}")
    print(f"VISIBLE_CLARITY_GAIN={decision['visible_clarity_gain']}")
    print(f"REAL_4K_QUALITY_GAIN={decision['real_4k_quality_gain']}")
    print(f"HUMAN_VISUAL_REVIEW={decision['human_visual_review']}")
    print("FORMAL_PIPELINE_CHANGED=NO")
    print("API_CHANGED=NO")
    print("UI_CHANGED=NO")
    print("PRODUCT_VERSION_CHANGED=NO")
    print("GIT_WRITE=NONE")
    print("READY_FOR_FORMAL_CANDIDATE=NO")
    return 0 if decision["status"] != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
