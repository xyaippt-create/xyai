"""Build the minimal reusable E1-01 real-information-gain baseline.

This stage creates no enhancement candidate.  It reuses the frozen Stage-1
golden snapshots, the frozen Pillow LANCZOS 4K executor, and normalized ROIs.
All writes stay below ``artifacts/e1_01_real_information_baseline_v1``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.image_processing_routing.four_k_v1 import FOUR_K_V1_ROUTE, process_4k_v1_image


STAGE1_ROOT = REPO_ROOT / "artifacts" / "4k_stage1_baseline"
SOURCE_MANIFEST = STAGE1_ROOT / "golden_samples_manifest.json"
SOURCE_ROI_MANIFEST = STAGE1_ROOT / "comparisons" / "comparison_manifest.json"
OUTPUT_ROOT = REPO_ROOT / "artifacts" / "e1_01_real_information_baseline_v1"
SETTINGS_PATH = REPO_ROOT / "settings" / "settings.json"
FORMAL_4K_DIRECTORY = Path(r"D:\影界文件\输出\4K高清增强")

REQUIRED_CASE_FIELDS = (
    "case_id",
    "source_class",
    "content_type",
    "degradation_type",
    "degradation_params",
    "input",
    "safe_base",
    "candidate",
    "gt",
    "roi",
    "hard_gate_notes",
)
ASSESSMENT_FIELDS = (
    "VISIBLE_GAIN",
    "TEXT_FIDELITY",
    "FACE_IDENTITY",
    "LOGO_FIDELITY",
    "STRUCTURE_FIDELITY",
    "MATERIAL_FIDELITY",
    "HALO",
    "RINGING",
    "FALSE_TEXTURE",
)
REQUIRED_DEGRADATIONS = {
    "RESIZE",
    "RESIZE_JPEG",
    "BLUR_JPEG",
    "MULTI_RESIZE",
    "SCREENSHOT_LIKE",
}
REQUIRED_CONTENT_COVERAGE = {
    "PHOTO_PORTRAIT",
    "CHINESE_TEXT_SCREEN",
    "LOGO_GRAPHICS",
    "PRODUCT_MATERIAL",
    "JPEG_WEB_COMPRESSION",
    "ALREADY_CLEAR_CONTROL",
}

SAMPLE_CONTRACT: dict[str, dict[str, Any]] = {
    "S01": {
        "source_class": "REAL_COMMERCIAL_IMAGE",
        "content_type": ["CHINESE_TEXT_SCREEN", "LOGO_GRAPHICS", "FINE_DETAIL"],
        "hard_gate_notes": ["中文笔画、品牌文字和高反差边缘不得被猜测或改写。"],
    },
    "S02": {
        "source_class": "REAL_COMMERCIAL_IMAGE",
        "content_type": ["CHINESE_TEXT_SCREEN", "LOGO_GRAPHICS", "ALREADY_CLEAR_CONTROL"],
        "hard_gate_notes": ["密集中文、小字、图标和规则细线必须保持真实形状。"],
    },
    "S03": {
        "source_class": "REAL_COMMERCIAL_IMAGE",
        "content_type": ["PHOTO_PORTRAIT", "FINE_DETAIL"],
        "hard_gate_notes": ["人物身份、眼睛、皮肤和头发事实不得重新生成。"],
    },
    "S04": {
        "source_class": "REAL_COMMERCIAL_IMAGE",
        "content_type": ["PHOTO_PORTRAIT", "JPEG_WEB_COMPRESSION"],
        "hard_gate_notes": ["多人身份、肢体、服装和背景虚化关系不得改变。"],
    },
    "S05": {
        "source_class": "REAL_COMMERCIAL_IMAGE",
        "content_type": ["LOGO_GRAPHICS", "PRODUCT_MATERIAL", "CHINESE_TEXT_SCREEN"],
        "hard_gate_notes": ["Logo、产品结构、包装文字和规则几何不得改写。"],
    },
    "S06": {
        "source_class": "REAL_COMMERCIAL_IMAGE",
        "content_type": ["PRODUCT_MATERIAL", "LOGO_GRAPHICS"],
        "hard_gate_notes": ["玻璃、金属、反射、Logo和产品边界不得重解释。"],
    },
    "S07": {
        "source_class": "REAL_COMMERCIAL_IMAGE",
        "content_type": ["PRODUCT_MATERIAL", "LOGO_GRAPHICS", "FINE_DETAIL"],
        "hard_gate_notes": ["建筑几何、复杂纹理、渐变和中文元素不得产生假细节。"],
    },
    "S08": {
        "source_class": "SYNTHETIC_CONTROL",
        "content_type": ["ALREADY_CLEAR_CONTROL", "LOGO_GRAPHICS"],
        "hard_gate_notes": ["SYNTHETIC_CONTROL；只用于清晰线条与平坦区域判断，不冒充真实商业图片。"],
    },
}

ROI_TYPE_BY_RISK = {
    "中文大标题": "CHINESE_TEXT",
    "高反差边缘": "FINE_DETAIL",
    "中文小字": "CHINESE_TEXT",
    "细线或图表": "FINE_DETAIL",
    "人物眼睛": "FACE",
    "人物头发": "FACE",
    "人物皮肤": "FACE",
    "背景虚化区域": "CONTROL_FLAT_REGION",
    "Logo边缘": "LOGO",
    "产品包装文字": "PRODUCT_STRUCTURE",
    "透明材质边缘": "MATERIAL",
    "渐变区域": "CONTROL_FLAT_REGION",
    "复杂纹理": "MATERIAL",
    "透明区域边缘": "FINE_DETAIL",
}

CONTROLLED_CASES = {
    "S01": ("RESIZE", {"scale": 0.55, "resample": "LANCZOS", "encoding": "PNG"}),
    "S02": ("SCREENSHOT_LIKE", {"scale": 0.72, "resample": "BILINEAR", "encoding": "PNG", "bit_depth": 8}),
    "S03": ("BLUR_JPEG", {"blur_radius": 1.1, "jpeg_quality": 82, "jpeg_subsampling": 2}),
    "S04": ("RESIZE_JPEG", {"scale": 0.62, "resample": "LANCZOS", "jpeg_quality": 80, "jpeg_subsampling": 2}),
    "S05": ("MULTI_RESIZE", {"scales": [0.82, 0.68], "resample": "LANCZOS", "encoding": "PNG"}),
    "S06": ("RESIZE", {"scale": 0.58, "resample": "LANCZOS", "encoding": "PNG"}),
    "S07": ("RESIZE_JPEG", {"scale": 0.64, "resample": "LANCZOS", "jpeg_quality": 76, "jpeg_subsampling": 2}),
    "S08": ("SCREENSHOT_LIKE", {"scale": 0.75, "resample": "BILINEAR", "encoding": "PNG", "bit_depth": 8}),
}


class E101Error(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def relative_path(path: Path | None) -> str | None:
    if path is None:
        return None
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def file_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path.resolve()), "exists": False}
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "exists": True,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def directory_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path.resolve()), "exists": False}
    digest = hashlib.sha256()
    count = 0
    for child in sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: item.as_posix().lower()):
        digest.update(child.relative_to(path).as_posix().encode("utf-8"))
        digest.update(str(child.stat().st_size).encode("ascii"))
        digest.update(sha256_file(child).encode("ascii"))
        count += 1
    return {
        "path": str(path.resolve()),
        "exists": True,
        "file_count": count,
        "tree_content_sha256": digest.hexdigest(),
    }


def protected_state() -> dict[str, Any]:
    return {
        "settings": file_state(SETTINGS_PATH),
        "formal_4k_directory": directory_state(FORMAL_4K_DIRECTORY),
    }


def _normalized_image(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        opened.load()
        return ImageOps.exif_transpose(opened).copy()


def _resize(image: Image.Image, size: tuple[int, int], resample: Image.Resampling) -> Image.Image:
    if "A" not in image.getbands():
        return image.convert("RGB").resize(size, resample)
    rgba = np.asarray(image.convert("RGBA"), dtype=np.float32) / 255.0
    alpha = rgba[..., 3:4]
    premultiplied = Image.fromarray(np.rint(np.concatenate((rgba[..., :3] * alpha, alpha), axis=2) * 255).astype(np.uint8), "RGBA")
    resized = np.asarray(premultiplied.resize(size, resample), dtype=np.float32) / 255.0
    out_alpha = resized[..., 3:4]
    out_rgb = np.zeros_like(resized[..., :3])
    np.divide(resized[..., :3], out_alpha, out=out_rgb, where=out_alpha > 1e-7)
    return Image.fromarray(np.rint(np.concatenate((np.clip(out_rgb, 0, 1), out_alpha), axis=2) * 255).astype(np.uint8), "RGBA")


def _scaled_size(size: tuple[int, int], scale: float) -> tuple[int, int]:
    return max(8, int(math.floor(size[0] * scale + 0.5))), max(8, int(math.floor(size[1] * scale + 0.5)))


def degradation_extension(degradation_type: str) -> str:
    return ".jpg" if degradation_type in {"RESIZE_JPEG", "BLUR_JPEG"} else ".png"


def create_degraded_input(source: Path, destination: Path, degradation_type: str, params: dict[str, Any]) -> None:
    image = _normalized_image(source)
    if degradation_type == "RESIZE":
        output = _resize(image, _scaled_size(image.size, float(params["scale"])), Image.Resampling.LANCZOS)
    elif degradation_type == "RESIZE_JPEG":
        output = _resize(image, _scaled_size(image.size, float(params["scale"])), Image.Resampling.LANCZOS).convert("RGB")
    elif degradation_type == "BLUR_JPEG":
        output = image.convert("RGB").filter(ImageFilter.GaussianBlur(radius=float(params["blur_radius"])))
    elif degradation_type == "MULTI_RESIZE":
        output = image
        for scale in params["scales"]:
            output = _resize(output, _scaled_size(output.size, float(scale)), Image.Resampling.LANCZOS)
    elif degradation_type == "SCREENSHOT_LIKE":
        output = _resize(image, _scaled_size(image.size, float(params["scale"])), Image.Resampling.BILINEAR)
    else:
        raise E101Error(f"UNSUPPORTED_DEGRADATION:{degradation_type}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix.lower() in {".jpg", ".jpeg"}:
        output.convert("RGB").save(
            destination,
            format="JPEG",
            quality=int(params["jpeg_quality"]),
            subsampling=int(params["jpeg_subsampling"]),
            optimize=False,
            progressive=False,
        )
    else:
        output.save(destination, format="PNG", compress_level=6, optimize=False)


def map_normalized_box(box: dict[str, float], size: tuple[int, int]) -> dict[str, int]:
    width, height = size
    x0 = max(0, min(width - 1, int(math.floor(box["x0"] * width))))
    y0 = max(0, min(height - 1, int(math.floor(box["y0"] * height))))
    x1 = max(x0 + 1, min(width, int(math.ceil(box["x1"] * width))))
    y1 = max(y0 + 1, min(height, int(math.ceil(box["y1"] * height))))
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}


def _checkerboard(size: tuple[int, int], cell: int = 16) -> Image.Image:
    canvas = Image.new("RGB", size, (238, 238, 238))
    draw = ImageDraw.Draw(canvas)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, min(x + cell - 1, size[0] - 1), min(y + cell - 1, size[1] - 1)), fill=(210, 210, 210))
    return canvas


def _display_rgb(image: Image.Image) -> Image.Image:
    if "A" not in image.getbands():
        return image.convert("RGB")
    rgba = image.convert("RGBA")
    background = _checkerboard(rgba.size).convert("RGBA")
    background.alpha_composite(rgba)
    return background.convert("RGB")


def _panel(image: Image.Image | None, label: str, size: tuple[int, int] = (420, 320)) -> Image.Image:
    panel = Image.new("RGB", (size[0], size[1] + 30), (245, 245, 245))
    draw = ImageDraw.Draw(panel)
    draw.text((10, 9), label, fill=(20, 20, 20))
    if image is None:
        draw.rectangle((0, 30, size[0] - 1, size[1] + 29), fill=(224, 224, 224), outline=(150, 150, 150))
        draw.line((25, 55, size[0] - 25, size[1] + 4), fill=(165, 165, 165), width=2)
        draw.line((size[0] - 25, 55, 25, size[1] + 4), fill=(165, 165, 165), width=2)
        draw.text((145, 170), "NOT PROVIDED", fill=(80, 80, 80))
        return panel
    shown = _display_rgb(image)
    shown.thumbnail(size, Image.Resampling.LANCZOS)
    x = (size[0] - shown.width) // 2
    y = 30 + (size[1] - shown.height) // 2
    panel.paste(shown, (x, y))
    return panel


def render_comparison(
    input_path: Path,
    safe_base_path: Path,
    candidate_path: Path | None,
    gt_path: Path | None,
    destination: Path,
) -> None:
    paths = (input_path, safe_base_path, candidate_path, gt_path)
    labels = ("INPUT", "SAFE_BASE", "CANDIDATE", "GT")
    images: list[Image.Image | None] = []
    for path in paths:
        images.append(None if path is None else _normalized_image(path))
    panels = [_panel(image, label) for image, label in zip(images, labels)]
    contact = Image.new("RGB", (sum(panel.width for panel in panels), panels[0].height), "white")
    offset = 0
    for panel in panels:
        contact.paste(panel, (offset, 0))
        offset += panel.width
    destination.parent.mkdir(parents=True, exist_ok=True)
    contact.save(destination, format="PNG", compress_level=6)


def _crop(path: Path, normalized_box: dict[str, float]) -> tuple[Image.Image, dict[str, int]]:
    image = _normalized_image(path)
    box = map_normalized_box(normalized_box, image.size)
    return image.crop((box["x0"], box["y0"], box["x1"], box["y1"])), box


def _image_record(path: Path) -> dict[str, Any]:
    with Image.open(path) as opened:
        opened.load()
        width, height = opened.size
        mode = opened.mode
        image_format = str(opened.format or "UNKNOWN").upper()
    return {
        "path": relative_path(path),
        "sha256": sha256_file(path),
        "width": width,
        "height": height,
        "mode": mode,
        "format": image_format,
        "size_bytes": path.stat().st_size,
    }


def _load_stage1() -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    samples = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    rois = json.loads(SOURCE_ROI_MANIFEST.read_text(encoding="utf-8"))
    if samples.get("status") != "FROZEN" or samples.get("sample_count") != 8:
        raise E101Error("STAGE1_GOLDEN_SAMPLE_CONTRACT_INVALID")
    roi_by_sample: dict[str, list[dict[str, Any]]] = {sample_id: [] for sample_id in SAMPLE_CONTRACT}
    for row in rois.get("comparisons", []):
        sample_id = row["sample_id"]
        roi_by_sample[sample_id].append(
            {
                "roi_id": f"R{len(roi_by_sample[sample_id]) + 1:02d}",
                "roi_type": ROI_TYPE_BY_RISK[row["risk"]],
                "label": row["risk"],
                "normalized_box": row["normalized_box"],
            }
        )
    if any(not (1 <= len(items) <= 3) for items in roi_by_sample.values()):
        raise E101Error("ROI_COUNT_OUTSIDE_MINIMAL_CONTRACT")
    return samples, roi_by_sample


def _case_specs(samples: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {sample["sample_id"]: sample for sample in samples["samples"]}
    specs: list[dict[str, Any]] = []
    index = 1
    for sample_id in sorted(by_id):
        contract = SAMPLE_CONTRACT[sample_id]
        specs.append(
            {
                "case_id": f"E1C{index:03d}",
                "sample_id": sample_id,
                "evidence_role": "SYNTHETIC_CONTROL" if sample_id == "S08" else "REAL_NO_GT_AUXILIARY",
                "degradation_type": "REAL_INPUT_AS_IS",
                "degradation_params": {"operation": "BYTE_EXACT_REUSE"},
                **contract,
            }
        )
        index += 1
        degradation_type, params = CONTROLLED_CASES[sample_id]
        specs.append(
            {
                "case_id": f"E1C{index:03d}",
                "sample_id": sample_id,
                "evidence_role": "CONTROLLED_GT_PRIMARY",
                "degradation_type": degradation_type,
                "degradation_params": params,
                **contract,
            }
        )
        index += 1
    return specs


def _build_roi_records(
    case_dir: Path,
    case_id: str,
    roi_specs: list[dict[str, Any]],
    input_path: Path,
    safe_path: Path,
    candidate_path: Path | None,
    gt_path: Path | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for spec in roi_specs:
        role_paths = {"input": input_path, "safe_base": safe_path, "candidate": candidate_path, "gt": gt_path}
        crop_paths: dict[str, str | None] = {}
        pixel_boxes: dict[str, dict[str, int] | None] = {}
        crop_images: list[Image.Image | None] = []
        for role, path in role_paths.items():
            if path is None:
                crop_paths[role] = None
                pixel_boxes[role] = None
                crop_images.append(None)
                continue
            crop, pixel_box = _crop(path, spec["normalized_box"])
            destination = case_dir / "roi_crops" / f"{spec['roi_id']}__{role}.png"
            destination.parent.mkdir(parents=True, exist_ok=True)
            crop.save(destination, format="PNG", compress_level=6)
            crop_paths[role] = relative_path(destination)
            pixel_boxes[role] = pixel_box
            crop_images.append(crop)
        panels = [_panel(image, label, size=(256, 256)) for image, label in zip(crop_images, ("INPUT", "SAFE_BASE", "CANDIDATE", "GT"))]
        comparison = Image.new("RGB", (sum(panel.width for panel in panels), panels[0].height), "white")
        offset = 0
        for panel in panels:
            comparison.paste(panel, (offset, 0))
            offset += panel.width
        comparison_path = case_dir / "roi_comparisons" / f"{spec['roi_id']}__side_by_side.png"
        comparison_path.parent.mkdir(parents=True, exist_ok=True)
        comparison.save(comparison_path, format="PNG", compress_level=6)
        records.append(
            {
                **spec,
                "coordinate_contract": "NORMALIZED_XYXY_0_TO_1",
                "pixel_boxes": pixel_boxes,
                "crop_paths": crop_paths,
                "side_by_side": relative_path(comparison_path),
            }
        )
    return records


def build() -> dict[str, Any]:
    resolved_output = OUTPUT_ROOT.resolve()
    expected_parent = (REPO_ROOT / "artifacts").resolve()
    if resolved_output.parent != expected_parent or not resolved_output.name.startswith("e1_01_"):
        raise E101Error("OUTPUT_ROOT_NOT_ISOLATED")
    if OUTPUT_ROOT.exists():
        raise E101Error(f"OUTPUT_ROOT_ALREADY_EXISTS:{OUTPUT_ROOT}")

    samples, roi_by_sample = _load_stage1()
    specs = _case_specs(samples)
    sample_by_id = {sample["sample_id"]: sample for sample in samples["samples"]}
    source_hashes_before = {
        sample_id: sha256_file(STAGE1_ROOT / "golden_samples" / sample["snapshot_file_name"])
        for sample_id, sample in sample_by_id.items()
    }
    protection_before = protected_state()
    case_records: list[dict[str, Any]] = []
    OUTPUT_ROOT.mkdir(parents=True)
    try:
        for spec in specs:
            sample = sample_by_id[spec["sample_id"]]
            source = STAGE1_ROOT / "golden_samples" / sample["snapshot_file_name"]
            case_dir = OUTPUT_ROOT / "cases" / spec["case_id"]
            case_dir.mkdir(parents=True)
            gt_path: Path | None = None
            if spec["degradation_type"] == "REAL_INPUT_AS_IS":
                input_path = case_dir / f"input{source.suffix.lower()}"
                shutil.copyfile(source, input_path)
                reproducibility = {"status": "BYTE_EXACT_REUSE", "repeat_sha256_match": True}
            else:
                gt_path = case_dir / f"gt{source.suffix.lower()}"
                shutil.copyfile(source, gt_path)
                extension = degradation_extension(spec["degradation_type"])
                input_path = case_dir / f"input{extension}"
                create_degraded_input(source, input_path, spec["degradation_type"], spec["degradation_params"])
                repeat_path = case_dir / f".determinism_repeat{extension}"
                create_degraded_input(source, repeat_path, spec["degradation_type"], spec["degradation_params"])
                repeat_matches = sha256_file(input_path) == sha256_file(repeat_path)
                repeat_path.unlink()
                if not repeat_matches:
                    raise E101Error(f"DEGRADATION_NOT_DETERMINISTIC:{spec['case_id']}")
                reproducibility = {"status": "PASS", "repeat_sha256_match": True, "sha256": sha256_file(input_path)}

            safe_workspace = case_dir / "safe_base_workspace"
            safe_path = safe_workspace / "输出" / "4K高清增强" / "safe_base.png"
            safe_result = process_4k_v1_image(input_path, safe_workspace, output_path=safe_path)
            if safe_result.get("final_output_exists") is not True or not safe_path.is_file():
                raise E101Error(f"SAFE_BASE_OUTPUT_MISSING:{spec['case_id']}")
            candidate_expected = case_dir / "candidate.png"
            side_by_side = case_dir / "side_by_side.png"
            render_comparison(input_path, safe_path, None, gt_path, side_by_side)
            roi_records = _build_roi_records(
                case_dir,
                spec["case_id"],
                roi_by_sample[spec["sample_id"]],
                input_path,
                safe_path,
                None,
                gt_path,
            )
            case_records.append(
                {
                    **spec,
                    "input": _image_record(input_path),
                    "safe_base": {**_image_record(safe_path), "route": safe_result["route"], "reused_existing_executor": True},
                    "candidate": {
                        "status": "EMPTY_BY_E1_01",
                        "path": None,
                        "expected_path": relative_path(candidate_expected),
                    },
                    "gt": None if gt_path is None else _image_record(gt_path),
                    "roi": roi_records,
                    "hard_gate_notes": spec["hard_gate_notes"],
                    "side_by_side": relative_path(side_by_side),
                    "degradation_reproducibility": reproducibility,
                    "assessment": {field: "NOT_ASSESSED_E1_01" for field in ASSESSMENT_FIELDS},
                    "real_information_gain": "NOT_ASSESSED_E1_01",
                }
            )

        source_hashes_after = {
            sample_id: sha256_file(STAGE1_ROOT / "golden_samples" / sample["snapshot_file_name"])
            for sample_id, sample in sample_by_id.items()
        }
        protection_after = protected_state()
        protection = {
            "settings_unchanged": protection_before["settings"] == protection_after["settings"],
            "formal_4k_directory_unchanged": protection_before["formal_4k_directory"] == protection_after["formal_4k_directory"],
            "source_snapshots_unchanged": source_hashes_before == source_hashes_after,
            "before": protection_before,
            "after": protection_after,
        }
        if not all(protection[key] for key in ("settings_unchanged", "formal_4k_directory_unchanged", "source_snapshots_unchanged")):
            raise E101Error("PROTECTED_STATE_CHANGED")

        real_cases = sum(record["evidence_role"] == "REAL_NO_GT_AUXILIARY" for record in case_records)
        gt_cases = sum(record["gt"] is not None for record in case_records)
        manifest = {
            "manifest_version": "HDDE_E1_01_REAL_INFORMATION_BASELINE_V1",
            "status": "FIXED",
            "stage": "E1-01",
            "scope": "MINIMAL_REAL_INFORMATION_GAIN_JUDGEMENT_BASELINE",
            "sample_count": len(samples["samples"]),
            "case_count": len(case_records),
            "gt_case_count": gt_cases,
            "real_no_gt_case_count": real_cases,
            "synthetic_control_sample_count": 1,
            "benchmark_scope": "MINIMAL",
            "source_manifest": relative_path(SOURCE_MANIFEST),
            "source_roi_manifest": relative_path(SOURCE_ROI_MANIFEST),
            "case_contract": {
                "required_fields": list(REQUIRED_CASE_FIELDS),
                "panel_order": ["INPUT", "SAFE_BASE", "CANDIDATE", "GT"],
                "candidate_policy": "EMPTY_ALLOWED_IN_E1_01; E1_02_AND_E1_03_WRITE_EXPECTED_PATH_AND_RE_RENDER",
                "roi_coordinate_contract": "NORMALIZED_XYXY_0_TO_1",
                "roi_count_per_case": "1_TO_3",
            },
            "real_information_gain_contract": {
                "assessment_fields": list(ASSESSMENT_FIELDS),
                "not_real_information_gain": [
                    "SHARPEN_ONLY",
                    "HIGH_FREQUENCY_INCREASE_ONLY",
                    "CONTRAST_INCREASE_ONLY",
                    "EDGE_HARDENING_ONLY",
                    "NOISE_AMPLIFICATION",
                    "JPEG_TEXTURE_AMPLIFICATION",
                    "TEXTURE_NOT_PRESENT_IN_GT",
                    "GUESSED_CHINESE_STROKE",
                    "REWRITTEN_LOGO_CONTOUR",
                    "REGENERATED_FACE_DETAIL",
                    "CHANGED_PRODUCT_STRUCTURE",
                ],
                "positive_evidence_requirements": [
                    "SAFE_BASE_RECOVERY_INSUFFICIENT",
                    "INPUT_OR_GT_CONTAINS_REAL_EVIDENCE",
                    "CANDIDATE_CHANGE_ALIGNS_WITH_EVIDENCE",
                    "KEY_ROI_VISIBLE_IMPROVEMENT",
                    "NO_HALO_RINGING_OR_FALSE_TEXTURE_EXCHANGE",
                    "TEXT_FACE_LOGO_STRUCTURE_MATERIAL_FIDELITY_PRESERVED",
                ],
                "gt_policy": "GT_IS_PRIMARY_TRUTH_REFERENCE_WHEN_PRESENT",
                "real_no_gt_policy": "AUXILIARY_ONLY; LOOKS_CLEARER_ALONE_CANNOT_PROVE_REAL_INFORMATION_GAIN",
                "metric_policy": "AUXILIARY_ONLY; METRIC_IMPROVED_NEVER_EQUALS_REAL_INFORMATION_GAIN",
            },
            "content_coverage": sorted({item for record in case_records for item in record["content_type"]}),
            "degradation_coverage": sorted({record["degradation_type"] for record in case_records if record["degradation_type"] != "REAL_INPUT_AS_IS"}),
            "samples": [
                {
                    "sample_id": sample["sample_id"],
                    "snapshot": relative_path(STAGE1_ROOT / "golden_samples" / sample["snapshot_file_name"]),
                    "snapshot_sha256": source_hashes_after[sample["sample_id"]],
                    "source_class": SAMPLE_CONTRACT[sample["sample_id"]]["source_class"],
                    "content_type": SAMPLE_CONTRACT[sample["sample_id"]]["content_type"],
                }
                for sample in samples["samples"]
            ],
            "cases": case_records,
            "protection": protection,
            "ready_for_e1_02": True,
        }
        atomic_write_json(OUTPUT_ROOT / "manifest.json", manifest)
        validation = validate_manifest(OUTPUT_ROOT / "manifest.json")
        atomic_write_json(OUTPUT_ROOT / "validation.json", validation)
        return validation
    except Exception:
        # Keep any partial evidence for diagnosis; never rewrite or clean protected paths.
        raise


def _manifest_asset(path_value: str) -> Path:
    path = Path(path_value)
    resolved = path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise E101Error(f"MANIFEST_ASSET_OUTSIDE_REPOSITORY:{resolved}") from exc
    if not resolved.is_file():
        raise E101Error(f"MANIFEST_ASSET_MISSING:{resolved}")
    return resolved


def _validate_candidate(candidate_path: Path, safe_path: Path) -> dict[str, Any]:
    candidate = candidate_path.expanduser().resolve()
    if not candidate.is_file():
        raise E101Error(f"CANDIDATE_MISSING:{candidate}")
    try:
        with Image.open(candidate) as opened:
            opened.load()
            candidate_size = opened.size
            candidate_mode = opened.mode
            candidate_format = str(opened.format or "UNKNOWN").upper()
        with Image.open(safe_path) as opened:
            opened.load()
            safe_size = opened.size
    except Exception as exc:
        raise E101Error(f"CANDIDATE_DECODE_FAILED:{candidate}") from exc
    if candidate_size != safe_size:
        raise E101Error(
            f"CANDIDATE_DIMENSIONS_MISMATCH:{candidate_size[0]}x{candidate_size[1]}:"
            f"EXPECTED:{safe_size[0]}x{safe_size[1]}"
        )
    return {
        "path": relative_path(candidate),
        "sha256": sha256_file(candidate),
        "width": candidate_size[0],
        "height": candidate_size[1],
        "mode": candidate_mode,
        "format": candidate_format,
        "size_bytes": candidate.stat().st_size,
    }


def _validate_rerender_root(output_root: Path) -> Path:
    resolved = output_root.expanduser().resolve()
    baseline = OUTPUT_ROOT.resolve()
    formal = FORMAL_4K_DIRECTORY.resolve()
    if resolved == baseline or baseline in resolved.parents:
        raise E101Error(f"RERENDER_OUTPUT_CANNOT_MODIFY_E1_01_BASELINE:{resolved}")
    if resolved == formal or formal in resolved.parents:
        raise E101Error(f"RERENDER_OUTPUT_CANNOT_USE_FORMAL_4K_DIRECTORY:{resolved}")
    if resolved.exists():
        raise E101Error(f"RERENDER_OUTPUT_ALREADY_EXISTS:{resolved}")
    return resolved


def rerender_candidate_comparisons(
    manifest_path: str | Path,
    case_id: str,
    candidate_path: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    """Render full-image and ROI comparisons without rebuilding any baseline asset."""

    manifest = Path(manifest_path).expanduser().resolve()
    if not manifest.is_file():
        raise E101Error(f"MANIFEST_MISSING:{manifest}")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if payload.get("manifest_version") != "HDDE_E1_01_REAL_INFORMATION_BASELINE_V1":
        raise E101Error("MANIFEST_VERSION_INVALID")
    matches = [case for case in payload.get("cases", []) if case.get("case_id") == case_id]
    if len(matches) != 1:
        raise E101Error(f"CASE_ID_NOT_UNIQUE_OR_MISSING:{case_id}")
    case = matches[0]
    input_path = _manifest_asset(case["input"]["path"])
    safe_path = _manifest_asset(case["safe_base"]["path"])
    gt_path = None if case["gt"] is None else _manifest_asset(case["gt"]["path"])
    candidate = Path(candidate_path).expanduser().resolve()
    candidate_record = _validate_candidate(candidate, safe_path)
    destination = _validate_rerender_root(Path(output_root))
    destination.mkdir(parents=True)

    full_comparison = destination / "full_image_side_by_side.png"
    render_comparison(input_path, safe_path, candidate, gt_path, full_comparison)
    roi_records = _build_roi_records(
        destination,
        case_id,
        case["roi"],
        input_path,
        safe_path,
        candidate,
        gt_path,
    )
    result = {
        "manifest_version": "HDDE_E1_01_CANDIDATE_RERENDER_V1",
        "status": "PASS",
        "source_manifest": relative_path(manifest),
        "case_id": case_id,
        "input": case["input"],
        "safe_base": case["safe_base"],
        "candidate": candidate_record,
        "gt": case["gt"],
        "full_image_side_by_side": relative_path(full_comparison),
        "roi": roi_records,
        "safe_base_rerun": False,
        "e1_01_baseline_modified": False,
    }
    atomic_write_json(destination / "comparison_manifest.json", result)
    return result


def validate_manifest(manifest_path: Path = OUTPUT_ROOT / "manifest.json") -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if payload.get("status") != "FIXED" or not isinstance(cases, list):
        raise E101Error("MANIFEST_NOT_FIXED")
    if not 8 <= payload.get("sample_count", 0) <= 12:
        raise E101Error("SAMPLE_COUNT_OUTSIDE_CONTRACT")
    if not 15 <= payload.get("case_count", 0) <= 20 or len(cases) != payload["case_count"]:
        raise E101Error("CASE_COUNT_OUTSIDE_CONTRACT")
    if not REQUIRED_CONTENT_COVERAGE.issubset(set(payload.get("content_coverage", []))):
        raise E101Error("CONTENT_COVERAGE_INCOMPLETE")
    if not REQUIRED_DEGRADATIONS.issubset(set(payload.get("degradation_coverage", []))):
        raise E101Error("DEGRADATION_COVERAGE_INCOMPLETE")
    for case in cases:
        missing = [field for field in REQUIRED_CASE_FIELDS if field not in case]
        if missing:
            raise E101Error(f"CASE_FIELDS_MISSING:{case.get('case_id')}:{','.join(missing)}")
        if not 1 <= len(case["roi"]) <= 3:
            raise E101Error(f"ROI_COUNT_INVALID:{case['case_id']}")
        if case["safe_base"].get("route") != FOUR_K_V1_ROUTE:
            raise E101Error(f"SAFE_BASE_ROUTE_INVALID:{case['case_id']}")
        required_paths = [case["input"]["path"], case["safe_base"]["path"], case["side_by_side"]]
        if case["gt"] is not None:
            required_paths.append(case["gt"]["path"])
        required_paths.extend(roi["side_by_side"] for roi in case["roi"])
        required_paths.extend(path for roi in case["roi"] for path in roi["crop_paths"].values() if path)
        for path_value in required_paths:
            path = (REPO_ROOT / path_value).resolve()
            try:
                path.relative_to(REPO_ROOT.resolve())
            except ValueError as exc:
                raise E101Error(f"OUTPUT_PATH_ESCAPE:{case['case_id']}:{path}") from exc
            if not path.is_file():
                raise E101Error(f"OUTPUT_PATH_MISSING:{case['case_id']}:{path}")
            try:
                with Image.open(path) as opened:
                    opened.load()
            except Exception as exc:
                raise E101Error(f"OUTPUT_NOT_DECODABLE:{case['case_id']}:{path}") from exc
        if case["candidate"].get("path") is not None or (REPO_ROOT / case["candidate"]["expected_path"]).exists():
            raise E101Error(f"E1_01_CANDIDATE_MUST_BE_EMPTY:{case['case_id']}")
        role_records = {"input": case["input"], "safe_base": case["safe_base"], "gt": case["gt"]}
        for roi in case["roi"]:
            for role, record in role_records.items():
                if record is None:
                    if roi["pixel_boxes"].get(role) is not None:
                        raise E101Error(f"ROI_ABSENT_ROLE_BOX_PRESENT:{case['case_id']}:{roi['roi_id']}:{role}")
                    continue
                expected_box = map_normalized_box(roi["normalized_box"], (record["width"], record["height"]))
                if roi["pixel_boxes"].get(role) != expected_box:
                    raise E101Error(f"ROI_MAPPING_MISMATCH:{case['case_id']}:{roi['roi_id']}:{role}")
                crop_path = REPO_ROOT / roi["crop_paths"][role]
                with Image.open(crop_path) as crop:
                    crop.load()
                    expected_size = (expected_box["x1"] - expected_box["x0"], expected_box["y1"] - expected_box["y0"])
                    if crop.size != expected_size:
                        raise E101Error(f"ROI_CROP_SIZE_MISMATCH:{case['case_id']}:{roi['roi_id']}:{role}")
            if roi["pixel_boxes"].get("candidate") is not None or roi["crop_paths"].get("candidate") is not None:
                raise E101Error(f"E1_01_CANDIDATE_ROI_MUST_BE_EMPTY:{case['case_id']}:{roi['roi_id']}")
        if case["degradation_type"] != "REAL_INPUT_AS_IS" and case["degradation_reproducibility"].get("status") != "PASS":
            raise E101Error(f"DEGRADATION_REPRODUCIBILITY_FAILED:{case['case_id']}")
        if tuple(case["assessment"].keys()) != ASSESSMENT_FIELDS:
            raise E101Error(f"ASSESSMENT_FIELDS_INVALID:{case['case_id']}")
    protection = payload.get("protection", {})
    if not all(protection.get(key) is True for key in ("settings_unchanged", "formal_4k_directory_unchanged", "source_snapshots_unchanged")):
        raise E101Error("PROTECTION_GATE_FAILED")
    return {
        "status": "PASS",
        "e1_01_baseline": "FIXED",
        "sample_count": payload["sample_count"],
        "case_count": payload["case_count"],
        "content_coverage": "PASS",
        "degradation_coverage": "PASS",
        "gt_cases": payload["gt_case_count"],
        "real_cases": payload["real_no_gt_case_count"],
        "roi_contract": "FIXED",
        "side_by_side_ready": "YES",
        "safe_base_reused": "YES",
        "gt_degradation_reproducible": "YES",
        "ready_for_e1_02": "YES",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or validate the HDDE E1-01 minimal real-information baseline")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    rerender_values = (args.manifest, args.case_id, args.candidate, args.output_root)
    if any(value is not None for value in rerender_values):
        if args.validate_only or not all(value is not None for value in rerender_values):
            parser.error("candidate rerender requires --manifest, --case-id, --candidate and --output-root")
        result = rerender_candidate_comparisons(args.manifest, args.case_id, args.candidate, args.output_root)
    else:
        result = validate_manifest() if args.validate_only else build()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
