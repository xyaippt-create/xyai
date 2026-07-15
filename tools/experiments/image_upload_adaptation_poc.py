"""影界 HDDE 上传适配 PoC v1。

prepare/run 只允许在 ``tmp/image_upload_adaptation_poc_v1/<run_id>`` 中写入实验资产。
交付门禁回放只允许写入 ``tmp/image_upload_adaptation_delivery_gate_replay_v1/<run_id>``。
图片实验运行分为 prepare 和 run 两步：先冻结 manifest，再执行固定矩阵。
该脚本不接入 UI、API、SSE、任务合同或正式 pipeline。
"""

from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import math
import platform
import shutil
import statistics
import time
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageOps, PngImagePlugin, features

import image_compression_lossless_poc as png_lossless


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_RUN_ROOT = (PROJECT_ROOT / "tmp" / "image_upload_adaptation_poc_v1").resolve()
ALLOWED_DELIVERY_GATE_REPLAY_ROOT = (
    PROJECT_ROOT / "tmp" / "image_upload_adaptation_delivery_gate_replay_v1"
).resolve()
STAGE1_MANIFEST = (
    PROJECT_ROOT
    / "tmp"
    / "image_resize_poc_v1"
    / "20260713_150702"
    / "golden_samples_manifest.csv"
).resolve()

EXPECTED_SAMPLE_SHA256 = {
    "cn_title": "3a9a5f0588d591e77fe02c6f6794855bd7e2bcbe6bd62bd522604c6a8d65ca57",
    "cn_small": "66f3318e0bd81337d2747a08bdaaf9b795e901606cc04d8f11159b5e12c89167",
    "logo_product": "ed951ff181b36543373397661473ce9d3576bbacb8fbfaafd2bece81f336e2f5",
    "dark_material": "4c0f2d4873f9dae11c5248d5298a017ba6646c4352042af9d7e37f17560c80a3",
    "light_infographic": "b7ee559eb57e8dc42f29ae9cf2d383b32489f788ac309de921a4bfbdc37ac22d",
    "real_alpha": "7aa7a1a17f791145858b16b55a55fa863ea7f91e668b93a53f5193d1f6634508",
    "people_jpeg": "bbeb1523324fffc01fe5659c3c52fb2dbe4165735f46e2bcf510fee21cd8f3ef",
    "historical_jpeg": "e63b4d7e91e5bbea6c3a1e70402671381e977e86a4687b90fae5e72121096fb7",
}

SAMPLE_ORDER = tuple(EXPECTED_SAMPLE_SHA256)
JPEG_QUALITIES = (95, 92, 90, 88, 85, 82, 80)
FIXED_DIMENSION_SCALES = (0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50)
# PoC候选搜索下限，不是经过验证的视觉安全阈值，也不能证明结果可安全交付。
MIN_POC_SEARCH_SCALE = 0.50
SCENARIO_ORDER = ("A", "B", "C", "D", "E")
SCENARIO_DESCRIPTIONS = {
    "A": "原图已符合全部限制",
    "B": "仅超过像素尺寸限制",
    "C": "仅超过文件体积限制",
    "D": "同时超过尺寸和体积限制",
    "E": "限制要求低于PoC候选搜索下限",
}
RESULT_STATES = {
    "NO_PROCESSING_NEEDED",
    "TARGET_MET",
    "TARGET_MET_WITH_REENCODE",
    "REVIEW_REQUIRED",
    "CANNOT_MEET_SAFELY",
    "INPUT_INVALID",
    "PROCESSING_FAILED",
}

POLICY = {
    "definition": "同时满足最大宽度、最大高度和最大文件体积，并尽量保留最大像素尺寸和最高可接受画质",
    "dimension_scale_order": ["Smax", *FIXED_DIMENSION_SCALES],
    "minimum_poc_search_scale": MIN_POC_SEARCH_SCALE,
    "minimum_poc_search_scale_scope": "PoC candidate search lower bound only; does not establish visual safety",
    "dimension_rounding": "floor(original_dimension * scale + 0.5)",
    "jpeg_quality_order": list(JPEG_QUALITIES),
    "jpeg_quality_floor_scope": "quality 80 is PoC-only and is not a product quality floor",
    "jpeg_encoder": {
        "library": "Pillow",
        "optimize": True,
        "progressive": False,
        "subsampling": "preserve source sampling when available; otherwise 2",
        "metadata": ["ICC", "EXIF", "DPI", "XMP"],
        "lossy": True,
    },
    "png_encoder": {
        "library": "Pillow plus stage1 Python-zlib IDAT optimization",
        "compress_level": 6,
        "optimize": False,
        "lossy_quantization": False,
        "format_conversion": False,
        "metadata": ["ICC", "EXIF", "DPI", "XMP"],
    },
    "candidate_lineage": "every pixel/quality candidate is generated directly from immutable source pixels",
    "format_policy": {"PNG": "PNG", "JPEG": "JPEG"},
    "no_processing_policy": "return source path and do not create a final candidate copy",
    "visual_gate": "PENDING; automatic checks do not approve visual quality",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline upload-adaptation PoC with a frozen manifest.")
    parser.add_argument("phase", choices=("prepare", "run", "replay-delivery-gate"))
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--visual-review-fixture", type=Path)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(value: bytes | None) -> str:
    return hashlib.sha256(value).hexdigest() if value is not None else ""


def canonical_json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def assert_run_path(path: Path, run_dir: Path) -> Path:
    resolved = path.resolve()
    if resolved != run_dir and run_dir not in resolved.parents:
        raise RuntimeError(f"write_outside_run_dir:{resolved}")
    return resolved


def write_json(path: Path, payload: Any, run_dir: Path) -> None:
    resolved = assert_run_path(path, run_dir)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_bytes(canonical_json_bytes(payload))


def write_text(path: Path, content: str, run_dir: Path) -> None:
    resolved = assert_run_path(path, run_dir)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content.rstrip() + "\n", encoding="utf-8")


def write_csv(path: Path, fields: Iterable[str], rows: Iterable[dict[str, Any]], run_dir: Path) -> None:
    resolved = assert_run_path(path, run_dir)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize_dpi(value: Any) -> list[float] | None:
    if not value or not isinstance(value, (tuple, list)) or len(value) < 2:
        return None
    return [round(float(value[0]), 6), round(float(value[1]), 6)]


def xmp_bytes(info: dict[str, Any]) -> bytes:
    for key in ("xmp", "XML:com.adobe.xmp"):
        value = info.get(key)
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
    return b""


def magic_format(path: Path) -> str:
    header = path.read_bytes()[:16]
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if header.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    return "UNKNOWN"


def image_metadata(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        image.load()
        info = dict(image.info)
        exif = info.get("exif") if isinstance(info.get("exif"), bytes) else b""
        icc = info.get("icc_profile") if isinstance(info.get("icc_profile"), bytes) else b""
        xmp = xmp_bytes(info)
        orientation = image.getexif().get(274)
        sampling = None
        if image.format == "JPEG":
            from PIL import JpegImagePlugin

            sampling = JpegImagePlugin.get_sampling(image)
        # image.load() above is the complete-decode gate. Pillow's verify()
        # must be used before load() and on a separate image object.
        complete = True
        file_format = "JPEG" if image.format in {"JPEG", "JPG"} else image.format
        return {
            "absolute_path": str(path.resolve()),
            "file_name": path.name,
            "sha256": sha256_file(path),
            "file_format": file_format,
            "magic_format": magic_format(path),
            "width": image.width,
            "height": image.height,
            "aspect_ratio": image.width / image.height,
            "file_size_bytes": path.stat().st_size,
            "color_mode": image.mode,
            "alpha_present": "A" in image.getbands() or "transparency" in info,
            "icc_present": bool(icc),
            "icc_sha256": sha256_bytes(icc),
            "exif_present": bool(exif),
            "exif_sha256": sha256_bytes(exif),
            "exif_orientation": orientation,
            "dpi": normalize_dpi(info.get("dpi")),
            "xmp_present": bool(xmp),
            "xmp_sha256": sha256_bytes(xmp),
            "jpeg_sampling": sampling,
            "complete_decode": complete,
        }


def target_dimensions(width: int, height: int, scale: float) -> tuple[int, int]:
    return max(1, math.floor(width * scale + 0.5)), max(1, math.floor(height * scale + 0.5))


def build_dimension_candidates(width: int, height: int, smax: float) -> list[dict[str, Any]]:
    if smax < MIN_POC_SEARCH_SCALE:
        return []
    ordered = [min(1.0, smax)]
    ordered.extend(scale for scale in FIXED_DIMENSION_SCALES if MIN_POC_SEARCH_SCALE <= scale <= smax + 1e-12)
    candidates: list[dict[str, Any]] = []
    seen_dimensions: set[tuple[int, int]] = set()
    for scale in ordered:
        dimensions = target_dimensions(width, height, scale)
        if dimensions in seen_dimensions:
            continue
        seen_dimensions.add(dimensions)
        candidates.append({"scale": round(scale, 12), "width": dimensions[0], "height": dimensions[1]})
    return candidates


def scenario_limits(sample: dict[str, Any], scenario: str) -> dict[str, Any]:
    width = int(sample["width"])
    height = int(sample["height"])
    size = int(sample["file_size_bytes"])
    if scenario == "A":
        max_width, max_height, max_bytes = width, height, size
    elif scenario == "B":
        max_width, max_height = target_dimensions(width, height, 0.75)
        max_bytes = max(size * 4, 1_000_000)
    elif scenario == "C":
        max_width, max_height = width, height
        max_bytes = max(1024, math.floor(size * 0.55))
    elif scenario == "D":
        max_width, max_height = target_dimensions(width, height, 0.75)
        max_bytes = max(1024, math.floor(size * 0.30))
    elif scenario == "E":
        max_width, max_height = target_dimensions(width, height, 0.49)
        max_bytes = max(512, math.floor(size * 0.10))
    else:
        raise ValueError(f"unknown_scenario:{scenario}")
    smax = min(1.0, max_width / width, max_height / height)
    return {
        "max_width": max_width,
        "max_height": max_height,
        "max_file_size_bytes": max_bytes,
        "smax": round(smax, 12),
        "dimension_candidates": build_dimension_candidates(width, height, smax),
    }


def dependency_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "pillow": Image.__version__,
        "libjpeg": features.version("jpg") or "unknown",
        "zlib": zlib.ZLIB_VERSION,
        "numpy": np.__version__,
    }


def load_stage1_samples() -> list[dict[str, Any]]:
    if not STAGE1_MANIFEST.is_file():
        raise RuntimeError(f"stage1_manifest_missing:{STAGE1_MANIFEST}")
    with STAGE1_MANIFEST.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_id = {row["sample_id"]: row for row in rows}
    if set(by_id) != set(SAMPLE_ORDER):
        raise RuntimeError(f"stage1_sample_ids_mismatch:{sorted(by_id)}")
    samples: list[dict[str, Any]] = []
    for sample_id in SAMPLE_ORDER:
        row = by_id[sample_id]
        source = Path(row["absolute_path"]).resolve()
        if not source.is_file():
            raise RuntimeError(f"sample_missing:{sample_id}:{source}")
        actual = image_metadata(source)
        expected_sha = EXPECTED_SAMPLE_SHA256[sample_id]
        if actual["sha256"] != expected_sha or row["sha256"] != expected_sha:
            raise RuntimeError(f"sample_sha_mismatch:{sample_id}")
        if actual["file_format"] != row["file_format"]:
            raise RuntimeError(f"sample_format_mismatch:{sample_id}")
        if actual["width"] != int(row["width"]) or actual["height"] != int(row["height"]):
            raise RuntimeError(f"sample_dimensions_mismatch:{sample_id}")
        if actual["file_size_bytes"] != int(row["file_size_bytes"]):
            raise RuntimeError(f"sample_size_mismatch:{sample_id}")
        samples.append(
            {
                "sample_id": sample_id,
                "sample_type": row["sample_type"],
                "selection_note": row.get("selection_note", ""),
                "roi_definitions": json.loads(row["roi_definitions"]),
                **actual,
            }
        )
    formats = {sample["file_format"] for sample in samples}
    if formats != {"PNG", "JPEG"}:
        raise RuntimeError(f"sample_format_coverage_missing:{formats}")
    required_ids = {"cn_title", "cn_small", "logo_product", "real_alpha", "people_jpeg"}
    if not required_ids.issubset({sample["sample_id"] for sample in samples}):
        raise RuntimeError("sample_semantic_coverage_missing")
    return samples


def build_frozen_manifest(run_dir: Path) -> dict[str, Any]:
    samples = load_stage1_samples()
    tasks: list[dict[str, Any]] = []
    for sample in samples:
        for scenario in SCENARIO_ORDER:
            tasks.append(
                {
                    "task_id": f"{sample['sample_id']}__{scenario}",
                    "sample_id": sample["sample_id"],
                    "scenario": scenario,
                    "scenario_description": SCENARIO_DESCRIPTIONS[scenario],
                    "limits": scenario_limits(sample, scenario),
                }
            )
    return {
        "schema": "hdde_image_upload_adaptation_poc_v1_frozen_manifest",
        "created_at": datetime.now().astimezone().isoformat(),
        "run_dir": str(run_dir),
        "stage1_manifest_path": str(STAGE1_MANIFEST),
        "stage1_manifest_sha256": sha256_file(STAGE1_MANIFEST),
        "sample_count": len(samples),
        "task_count": len(tasks),
        "samples": samples,
        "tasks": tasks,
        "policy": POLICY,
        "policy_sha256": hashlib.sha256(canonical_json_bytes(POLICY)).hexdigest(),
        "dependencies": dependency_versions(),
    }


def prepare(run_dir: Path) -> int:
    if run_dir.exists():
        raise SystemExit(f"prepare_run_dir_already_exists:{run_dir}")
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = build_frozen_manifest(run_dir)
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_path = assert_run_path(run_dir / "frozen_manifest.json", run_dir)
    manifest_path.write_bytes(manifest_bytes)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    write_text(run_dir / "frozen_manifest.sha256", manifest_sha, run_dir)
    manifest_rows = []
    for task in manifest["tasks"]:
        sample = next(item for item in manifest["samples"] if item["sample_id"] == task["sample_id"])
        manifest_rows.append(
            {
                "task_id": task["task_id"],
                "sample_id": sample["sample_id"],
                "sample_type": sample["sample_type"],
                "absolute_path": sample["absolute_path"],
                "source_sha256": sample["sha256"],
                "format": sample["file_format"],
                "original_dimensions": f"{sample['width']}x{sample['height']}",
                "original_size_bytes": sample["file_size_bytes"],
                "alpha_present": sample["alpha_present"],
                "icc_present": sample["icc_present"],
                "exif_orientation": sample["exif_orientation"],
                "scenario": task["scenario"],
                "max_width": task["limits"]["max_width"],
                "max_height": task["limits"]["max_height"],
                "max_file_size_bytes": task["limits"]["max_file_size_bytes"],
                "smax": task["limits"]["smax"],
                "dimension_candidates": json.dumps(task["limits"]["dimension_candidates"], ensure_ascii=False),
                "jpeg_qualities": json.dumps(JPEG_QUALITIES),
            }
        )
    write_csv(run_dir / "frozen_manifest.csv", manifest_rows[0].keys(), manifest_rows, run_dir)
    print(
        json.dumps(
            {
                "phase": "prepare",
                "run_dir": str(run_dir),
                "manifest_sha256": manifest_sha,
                "samples": len(manifest["samples"]),
                "tasks": len(manifest["tasks"]),
                "status": "FROZEN",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def load_frozen_manifest(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "frozen_manifest.json"
    sha_path = run_dir / "frozen_manifest.sha256"
    if not manifest_path.is_file() or not sha_path.is_file():
        raise RuntimeError("frozen_manifest_missing")
    actual_sha = sha256_file(manifest_path)
    expected_sha = sha_path.read_text(encoding="utf-8").strip()
    if actual_sha != expected_sha:
        raise RuntimeError("frozen_manifest_sha_mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["policy"] != POLICY:
        raise RuntimeError("frozen_policy_differs_from_script")
    if manifest["policy_sha256"] != hashlib.sha256(canonical_json_bytes(POLICY)).hexdigest():
        raise RuntimeError("frozen_policy_sha_mismatch")
    if manifest["sample_count"] != 8 or manifest["task_count"] != 40:
        raise RuntimeError("frozen_matrix_count_mismatch")
    return manifest


def transferable_metadata(source: Path) -> tuple[Image.Image, dict[str, Any]]:
    with Image.open(source) as opened:
        opened.load()
        info = dict(opened.info)
        orientation = opened.getexif().get(274)
        image = ImageOps.exif_transpose(opened).copy()
        exif = opened.getexif()
        if orientation not in {None, 1}:
            exif[274] = 1
        exif_bytes = exif.tobytes() if len(exif) else b""
        metadata = {
            "icc_profile": info.get("icc_profile") if isinstance(info.get("icc_profile"), bytes) else b"",
            "exif": exif_bytes,
            "dpi": info.get("dpi"),
            "xmp": xmp_bytes(info),
            "normalized_orientation": 1 if orientation not in {None, 1} else orientation,
        }
    return image, metadata


def clear_fully_transparent_rgb(image: Image.Image) -> Image.Image:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    rgba[..., :3][rgba[..., 3] == 0] = 0
    return Image.fromarray(rgba, mode="RGBA")


def resize_direct(source_image: Image.Image, size: tuple[int, int]) -> Image.Image:
    if source_image.size == size:
        return source_image.copy()
    if "A" in source_image.getbands() or "transparency" in source_image.info:
        rgba = source_image.convert("RGBA")
        resized = rgba.convert("RGBa").resize(size, Image.Resampling.LANCZOS).convert("RGBA")
        return clear_fully_transparent_rgb(resized)
    if source_image.mode == "L":
        return source_image.resize(size, Image.Resampling.LANCZOS)
    return source_image.convert("RGB").resize(size, Image.Resampling.LANCZOS)


def save_png_candidate(image: Image.Image, path: Path, metadata: dict[str, Any], run_dir: Path) -> None:
    resolved = assert_run_path(path, run_dir)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {"compress_level": 6, "optimize": False}
    if metadata["icc_profile"]:
        kwargs["icc_profile"] = metadata["icc_profile"]
    if metadata["exif"]:
        kwargs["exif"] = metadata["exif"]
    if metadata["dpi"]:
        kwargs["dpi"] = metadata["dpi"]
    if metadata["xmp"]:
        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add_itxt("XML:com.adobe.xmp", metadata["xmp"].decode("utf-8", errors="replace"))
        kwargs["pnginfo"] = pnginfo
    image.save(resolved, format="PNG", **kwargs)


def save_jpeg_candidate(
    image: Image.Image,
    path: Path,
    quality: int,
    sampling: int,
    metadata: dict[str, Any],
    run_dir: Path,
) -> None:
    resolved = assert_run_path(path, run_dir)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {
        "quality": quality,
        "optimize": True,
        "progressive": False,
        "subsampling": sampling if sampling in {0, 1, 2} else 2,
    }
    if metadata["icc_profile"]:
        kwargs["icc_profile"] = metadata["icc_profile"]
    if metadata["exif"]:
        kwargs["exif"] = metadata["exif"]
    if metadata["dpi"]:
        kwargs["dpi"] = metadata["dpi"]
    if metadata["xmp"]:
        kwargs["xmp"] = metadata["xmp"]
    image.convert("RGB").save(resolved, format="JPEG", **kwargs)


def automatic_alpha_check(source: Path, candidate: Path, same_dimensions: bool) -> dict[str, Any]:
    with Image.open(source) as original_image, Image.open(candidate) as candidate_image:
        if "A" not in original_image.getbands() and "transparency" not in original_image.info:
            return {"applicable": False, "passed": True, "scope": "no_alpha"}
        original_rgba = np.asarray(original_image.convert("RGBA"), dtype=np.uint8)
        candidate_rgba = np.asarray(candidate_image.convert("RGBA"), dtype=np.uint8)
    if same_dimensions:
        passed = np.array_equal(original_rgba, candidate_rgba)
        return {"applicable": True, "passed": bool(passed), "scope": "same_size_rgba_exact"}
    transparent = candidate_rgba[..., 3] == 0
    maximum = int(candidate_rgba[..., :3][transparent].max()) if transparent.any() else 0
    return {
        "applicable": True,
        "passed": maximum == 0,
        "scope": "fully_transparent_rgb_zero_only;semi_transparent_visual_pending",
        "fully_transparent_rgb_max": maximum,
    }


def verify_candidate(
    source_record: dict[str, Any],
    candidate: Path,
    task: dict[str, Any],
    expected_lossy: bool,
) -> dict[str, Any]:
    output = image_metadata(candidate)
    limits = task["limits"]
    aspect_error = abs(output["width"] - output["height"] * source_record["aspect_ratio"])
    alpha_check = automatic_alpha_check(
        Path(source_record["absolute_path"]),
        candidate,
        output["width"] == source_record["width"] and output["height"] == source_record["height"],
    )
    checks = {
        "output_exists": candidate.is_file(),
        "complete_decode": output["complete_decode"],
        "width_within_limit": output["width"] <= limits["max_width"],
        "height_within_limit": output["height"] <= limits["max_height"],
        "bytes_within_limit": output["file_size_bytes"] <= limits["max_file_size_bytes"],
        "aspect_ratio_within_one_pixel": aspect_error <= 1.0,
        "not_enlarged": output["width"] <= source_record["width"] and output["height"] <= source_record["height"],
        "format_preserved": output["file_format"] == source_record["file_format"],
        "magic_preserved": output["magic_format"] == source_record["magic_format"],
        "source_sha256_unchanged": sha256_file(Path(source_record["absolute_path"])) == source_record["sha256"],
        "direct_source_lineage": True,
        "crop_pad_processing_path_used": False,
        "jpeg_lossy_marked": expected_lossy == (source_record["file_format"] == "JPEG"),
        "alpha_automatic_check": alpha_check,
    }
    checks["passed"] = all(
        value
        for key, value in checks.items()
        if key not in {"alpha_automatic_check", "crop_pad_processing_path_used"}
    ) and alpha_check["passed"] and not checks["crop_pad_processing_path_used"]
    return {"output": output, "checks": checks, "aspect_pixel_error": round(aspect_error, 6)}


def source_within_limits(sample: dict[str, Any], limits: dict[str, Any]) -> bool:
    return (
        sample["width"] <= limits["max_width"]
        and sample["height"] <= limits["max_height"]
        and sample["file_size_bytes"] <= limits["max_file_size_bytes"]
    )


def attempt_record(
    task_id: str,
    source: dict[str, Any],
    path: Path,
    scale_info: dict[str, Any],
    quality: int | None,
    kind: str,
    elapsed: float,
    max_bytes: int,
) -> dict[str, Any]:
    metadata = image_metadata(path)
    return {
        "task_id": task_id,
        "source_path": source["absolute_path"],
        "source_sha256": source["sha256"],
        "generation_parent": "immutable_source_pixels",
        "prior_candidate_used": False,
        "postprocess": "IDAT-only lossless optimization" if kind == "png_lossless_optimized" else "none",
        "attempt_kind": kind,
        "scale": scale_info["scale"],
        "dimensions": f"{metadata['width']}x{metadata['height']}",
        "jpeg_quality": quality,
        "path": str(path),
        "sha256": metadata["sha256"],
        "file_size_bytes": metadata["file_size_bytes"],
        "meets_file_size": metadata["file_size_bytes"] <= max_bytes,
        "elapsed_seconds": round(elapsed, 6),
    }


def process_task(
    task: dict[str, Any],
    source: dict[str, Any],
    run_dir: Path,
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    started = time.perf_counter()
    limits = task["limits"]
    base_result = {
        "task_id": task["task_id"],
        "sample_id": source["sample_id"],
        "sample_type": source["sample_type"],
        "scenario": task["scenario"],
        "scenario_description": task["scenario_description"],
        "source_path": source["absolute_path"],
        "source_sha256": source["sha256"],
        "source_format": source["file_format"],
        "source_dimensions": f"{source['width']}x{source['height']}",
        "source_size_bytes": source["file_size_bytes"],
        "max_width": limits["max_width"],
        "max_height": limits["max_height"],
        "max_file_size_bytes": limits["max_file_size_bytes"],
        "smax": limits["smax"],
        "candidate_count": 0,
        "final_path": "",
        "final_dimensions": "",
        "final_size_bytes": "",
        "final_jpeg_quality": "",
        "reencoded": False,
        "lossy": False,
        "technical_gate_passed": False,
        "visual_review": "PENDING",
        "review_status": "REVIEW_REQUIRED",
        "safety_stop": False,
        "failure_reason": "",
    }
    if source_within_limits(source, limits):
        return {
            **base_result,
            "status": "NO_PROCESSING_NEEDED",
            "final_path": source["absolute_path"],
            "final_dimensions": base_result["source_dimensions"],
            "final_size_bytes": source["file_size_bytes"],
            "technical_gate_passed": True,
            "visual_review": "NOT_REQUIRED_NO_CHANGE",
            "review_status": "NO_PROCESSING_NEEDED",
            "processing_seconds": round(time.perf_counter() - started, 6),
            "slowest_stage": "limit_check",
            "no_processing_copy_created": False,
        }
    if limits["smax"] < MIN_POC_SEARCH_SCALE or not limits["dimension_candidates"]:
        return {
            **base_result,
            "status": "CANNOT_MEET_SAFELY",
            "visual_review": "NOT_AVAILABLE",
            "review_status": "CANNOT_MEET_SAFELY",
            "safety_stop": True,
            "failure_reason": "limits_require_below_poc_search_scale",
            "processing_seconds": round(time.perf_counter() - started, 6),
            "slowest_stage": "poc_search_floor_check",
            "no_processing_copy_created": False,
        }

    source_path = Path(source["absolute_path"])
    source_image, transferable = transferable_metadata(source_path)
    selected: Path | None = None
    selected_quality: int | None = None
    stage_times: dict[str, float] = {"resize_encode_search": 0.0, "verify": 0.0}
    original_sampling = source.get("jpeg_sampling")
    for scale_info in limits["dimension_candidates"]:
        dimensions = (scale_info["width"], scale_info["height"])
        scale_label = f"s{float(scale_info['scale']):.6f}_{dimensions[0]}x{dimensions[1]}"
        attempt_dir = assert_run_path(run_dir / "attempts" / task["task_id"] / scale_label, run_dir)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        if source["file_format"] == "PNG":
            attempt_started = time.perf_counter()
            if dimensions == (source["width"], source["height"]):
                optimized_path = attempt_dir / "png_source_idat_optimized.png"
                png_lossless.optimize_png_structure(source_path, optimized_path)
                elapsed = time.perf_counter() - attempt_started
                record = attempt_record(
                    task["task_id"], source, optimized_path, scale_info, None, "png_lossless_optimized", elapsed, limits["max_file_size_bytes"]
                )
                attempts.append(record)
                base_result["candidate_count"] += 1
                stage_times["resize_encode_search"] += elapsed
                if record["meets_file_size"]:
                    selected = optimized_path
                    break
            else:
                direct_image = resize_direct(source_image, dimensions)
                base_path = attempt_dir / "png_direct_lanczos.png"
                save_png_candidate(direct_image, base_path, transferable, run_dir)
                base_elapsed = time.perf_counter() - attempt_started
                base_record = attempt_record(
                    task["task_id"], source, base_path, scale_info, None, "png_direct", base_elapsed, limits["max_file_size_bytes"]
                )
                attempts.append(base_record)
                base_result["candidate_count"] += 1
                optimized_path = attempt_dir / "png_direct_lanczos_idat_optimized.png"
                optimize_started = time.perf_counter()
                png_lossless.optimize_png_structure(base_path, optimized_path)
                optimize_elapsed = time.perf_counter() - optimize_started
                optimized_record = attempt_record(
                    task["task_id"], source, optimized_path, scale_info, None, "png_lossless_optimized", optimize_elapsed, limits["max_file_size_bytes"]
                )
                attempts.append(optimized_record)
                base_result["candidate_count"] += 1
                stage_times["resize_encode_search"] += base_elapsed + optimize_elapsed
                viable = [record for record in (base_record, optimized_record) if record["meets_file_size"]]
                if viable:
                    chosen = min(viable, key=lambda item: item["file_size_bytes"])
                    selected = Path(chosen["path"])
                    break
        else:
            for quality in JPEG_QUALITIES:
                attempt_started = time.perf_counter()
                direct_image = resize_direct(source_image, dimensions)
                candidate = attempt_dir / f"jpeg_q{quality}.jpg"
                save_jpeg_candidate(
                    direct_image,
                    candidate,
                    quality,
                    int(original_sampling) if original_sampling is not None else 2,
                    transferable,
                    run_dir,
                )
                elapsed = time.perf_counter() - attempt_started
                record = attempt_record(
                    task["task_id"], source, candidate, scale_info, quality, "jpeg_direct_lossy", elapsed, limits["max_file_size_bytes"]
                )
                attempts.append(record)
                base_result["candidate_count"] += 1
                stage_times["resize_encode_search"] += elapsed
                if record["meets_file_size"]:
                    selected = candidate
                    selected_quality = quality
                    break
            if selected:
                break

    if not selected:
        return {
            **base_result,
            "status": "CANNOT_MEET_SAFELY",
            "visual_review": "NOT_AVAILABLE",
            "review_status": "CANNOT_MEET_SAFELY",
            "safety_stop": True,
            "failure_reason": "no_candidate_met_limits_at_or_above_50pct_and_jpeg_quality_at_or_above_80",
            "processing_seconds": round(time.perf_counter() - started, 6),
            "slowest_stage": "resize_encode_search",
            "no_processing_copy_created": False,
        }

    final_dir = assert_run_path(run_dir / "final_candidates", run_dir)
    final_dir.mkdir(parents=True, exist_ok=True)
    extension = ".png" if source["file_format"] == "PNG" else ".jpg"
    final_path = final_dir / f"{task['task_id']}{extension}"
    shutil.copyfile(selected, final_path)
    verify_started = time.perf_counter()
    verification = verify_candidate(source, final_path, task, source["file_format"] == "JPEG")
    stage_times["verify"] += time.perf_counter() - verify_started
    output = verification["output"]
    passed = bool(verification["checks"]["passed"])
    slowest_stage = max(stage_times, key=stage_times.get)
    return {
        **base_result,
        "status": "TARGET_MET_WITH_REENCODE" if source["file_format"] == "JPEG" else "TARGET_MET",
        "final_path": str(final_path),
        "final_sha256": output["sha256"],
        "final_dimensions": f"{output['width']}x{output['height']}",
        "final_size_bytes": output["file_size_bytes"],
        "final_jpeg_quality": selected_quality if selected_quality is not None else "",
        "reencoded": source["file_format"] == "JPEG" or output["sha256"] != source["sha256"],
        "lossy": source["file_format"] == "JPEG",
        "technical_gate_passed": passed,
        "visual_review": "PENDING",
        "review_status": "REVIEW_REQUIRED",
        "failure_reason": "" if passed else "automatic_hard_gate_failed",
        "automatic_checks": verification["checks"],
        "metadata_comparison": {
            "icc": {"source": source["icc_sha256"], "output": output["icc_sha256"], "preserved": source["icc_sha256"] == output["icc_sha256"]},
            "exif": {"source": source["exif_sha256"], "output": output["exif_sha256"], "preserved": source["exif_sha256"] == output["exif_sha256"]},
            "orientation": {"source": source["exif_orientation"], "output": output["exif_orientation"], "semantics_correct": output["exif_orientation"] in {None, 1, source["exif_orientation"]}},
            "dpi": {"source": source["dpi"], "output": output["dpi"], "preserved": source["dpi"] == output["dpi"]},
            "xmp": {"source": source["xmp_sha256"], "output": output["xmp_sha256"], "preserved": source["xmp_sha256"] == output["xmp_sha256"]},
            "color_mode": {"source": source["color_mode"], "output": output["color_mode"]},
            "alpha_present": {"source": source["alpha_present"], "output": output["alpha_present"]},
        },
        "aspect_pixel_error": verification["aspect_pixel_error"],
        "processing_seconds": round(time.perf_counter() - started, 6),
        "stage_seconds": {key: round(value, 6) for key, value in stage_times.items()},
        "slowest_stage": slowest_stage,
        "no_processing_copy_created": False,
    }


def crop_box(size: tuple[int, int], normalized: list[float]) -> tuple[int, int, int, int]:
    width, height = size
    left = max(0, min(width - 1, math.floor(normalized[0] * width)))
    top = max(0, min(height - 1, math.floor(normalized[1] * height)))
    right = max(left + 1, min(width, math.ceil(normalized[2] * width)))
    bottom = max(top + 1, min(height, math.ceil(normalized[3] * height)))
    return left, top, right, bottom


def visual_panel(image: Image.Image, background: str = "white") -> Image.Image:
    rgba = image.convert("RGBA")
    base = Image.new("RGBA", rgba.size, background)
    base.alpha_composite(rgba)
    panel = base.convert("RGB")
    panel.thumbnail((900, 900), Image.Resampling.LANCZOS)
    return panel


def save_contact_sheet(
    source: Path,
    final: Path | None,
    output: Path,
    label: str,
    run_dir: Path,
    background: str = "white",
) -> None:
    with Image.open(source) as original_image:
        original_image.load()
        panels = [("ORIGINAL", visual_panel(original_image, background))]
    if final is not None:
        with Image.open(final) as final_image:
            final_image.load()
            panels.append((label, visual_panel(final_image, background)))
    label_height = 30
    width = sum(panel.width for _, panel in panels)
    height = max(panel.height for _, panel in panels) + label_height
    canvas = Image.new("RGB", (width, height), "#202124")
    draw = ImageDraw.Draw(canvas)
    x = 0
    for name, panel in panels:
        draw.text((x + 8, 8), name, fill="white")
        canvas.paste(panel, (x, label_height))
        x += panel.width
    resolved = assert_run_path(output, run_dir)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(resolved, format="PNG", compress_level=6)


def create_visual_evidence(
    result: dict[str, Any],
    sample: dict[str, Any],
    run_dir: Path,
) -> list[dict[str, Any]]:
    source = Path(sample["absolute_path"])
    final = Path(result["final_path"]) if result["status"] in {"TARGET_MET", "TARGET_MET_WITH_REENCODE"} else None
    contact_dir = run_dir / "contact_sheets"
    contact = contact_dir / f"{result['task_id']}__white.png"
    save_contact_sheet(source, final, contact, result["status"], run_dir, "white")
    contact_black = ""
    if sample["alpha_present"]:
        black_path = contact_dir / f"{result['task_id']}__black.png"
        save_contact_sheet(source, final, black_path, result["status"], run_dir, "black")
        contact_black = str(black_path)
    if final is None:
        return [
            {
                "task_id": result["task_id"],
                "roi": "overview_only_no_candidate",
                "source_crop": "",
                "candidate_crop": "",
                "contact_sheet_white": str(contact),
                "contact_sheet_black": contact_black,
                "visual_review": result["visual_review"],
            }
        ]
    rows: list[dict[str, Any]] = []
    with Image.open(source) as source_image, Image.open(final) as final_image:
        source_image.load()
        final_image.load()
        for roi_name, normalized in sample["roi_definitions"]:
            source_crop = source_image.crop(crop_box(source_image.size, normalized))
            final_crop = final_image.crop(crop_box(final_image.size, normalized))
            crop_dir = run_dir / "native_crops" / result["task_id"] / roi_name
            source_crop_path = crop_dir / "source.png"
            final_crop_path = crop_dir / "candidate.png"
            for crop, path in ((source_crop, source_crop_path), (final_crop, final_crop_path)):
                resolved = assert_run_path(path, run_dir)
                resolved.parent.mkdir(parents=True, exist_ok=True)
                crop.save(resolved, format="PNG", compress_level=6)
            rows.append(
                {
                    "task_id": result["task_id"],
                    "roi": roi_name,
                    "source_crop": str(source_crop_path),
                    "candidate_crop": str(final_crop_path),
                    "contact_sheet_white": str(contact),
                    "contact_sheet_black": contact_black,
                    "visual_review": "PENDING",
                }
            )
    return rows


def write_run_summary(run_dir: Path, results: list[dict[str, Any]], attempts: list[dict[str, Any]], technical: str) -> None:
    status_counts = {state: sum(result["status"] == state for result in results) for state in RESULT_STATES}
    elapsed = [float(result["processing_seconds"]) for result in results]
    lines = [
        "# Image Upload Adaptation PoC v1 - Technical Run Summary",
        "",
        f"- Run directory: `{run_dir}`",
        f"- Tasks: {len(results)}",
        f"- Attempts: {len(attempts)}",
        f"- Status counts: `{json.dumps(status_counts, ensure_ascii=False, sort_keys=True)}`",
        f"- Median task time: {statistics.median(elapsed):.6f}s",
        "- Candidate generation: direct from immutable source pixels",
        "- Automatic gate scope: file, decode, dimensions, bytes, aspect, format, source SHA, lineage, and lossy labeling",
        "- Automatic gate does not approve visual crop/stretch/padding appearance, semi-transparent edges, Chinese, Logo, people, or materials",
        "",
        f"TECHNICAL_AUDIT: {technical}",
        "VISUAL_REVIEW: PENDING",
        f"STAGE_2_GATE: {'READY_FOR_USER_REVIEW' if technical == 'PASS' else technical}",
        "",
        "COMMIT_NOT_EXECUTED",
        "PUSH_NOT_EXECUTED",
        "TAG_NOT_EXECUTED",
        "PR_NOT_EXECUTED",
    ]
    write_text(run_dir / "run_summary.md", "\n".join(lines), run_dir)


def run_experiment(run_dir: Path) -> int:
    if (run_dir / "task_results.json").exists():
        raise SystemExit("formal_run_already_completed;refusing_to_overwrite")
    manifest = load_frozen_manifest(run_dir)
    samples = {sample["sample_id"]: sample for sample in manifest["samples"]}
    source_hashes_before = {sample_id: sha256_file(Path(sample["absolute_path"])) for sample_id, sample in samples.items()}
    results: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for task in manifest["tasks"]:
        source = samples[task["sample_id"]]
        try:
            result = process_task(task, source, run_dir, attempts)
        except Exception as exc:
            result = {
                "task_id": task["task_id"],
                "sample_id": source["sample_id"],
                "sample_type": source["sample_type"],
                "scenario": task["scenario"],
                "status": "PROCESSING_FAILED",
                "source_path": source["absolute_path"],
                "source_sha256": source["sha256"],
                "candidate_count": 0,
                "technical_gate_passed": False,
                "visual_review": "NOT_AVAILABLE",
                "review_status": "PROCESSING_FAILED",
                "safety_stop": True,
                "failure_reason": f"{type(exc).__name__}:{exc}",
                "processing_seconds": 0.0,
                "slowest_stage": "exception",
            }
        results.append(result)
    source_hashes_after = {sample_id: sha256_file(Path(sample["absolute_path"])) for sample_id, sample in samples.items()}
    originals_unchanged = source_hashes_before == source_hashes_after == {
        sample_id: sample["sha256"] for sample_id, sample in samples.items()
    }
    visual_rows: list[dict[str, Any]] = []
    for result in results:
        visual_rows.extend(create_visual_evidence(result, samples[result["sample_id"]], run_dir))

    expected_a = all(result["status"] == "NO_PROCESSING_NEEDED" for result in results if result["scenario"] == "A")
    expected_e = all(result["status"] == "CANNOT_MEET_SAFELY" for result in results if result["scenario"] == "E")
    successful = [result for result in results if result["status"] in {"TARGET_MET", "TARGET_MET_WITH_REENCODE"}]
    successful_pass = bool(successful) and all(result["technical_gate_passed"] for result in successful)
    no_processing_clean = all(
        result.get("no_processing_copy_created") is False and result.get("reencoded") is False
        for result in results
        if result["status"] == "NO_PROCESSING_NEEDED"
    )
    failures = [result for result in results if result["status"] in {"INPUT_INVALID", "PROCESSING_FAILED"}]
    technical = "PASS" if originals_unchanged and expected_a and expected_e and successful_pass and no_processing_clean and not failures else "FAIL"

    write_json(run_dir / "task_results.json", results, run_dir)
    result_fields = sorted({key for result in results for key in result if not isinstance(result.get(key), (dict, list))})
    write_csv(run_dir / "task_results.csv", result_fields, results, run_dir)
    write_json(run_dir / "candidate_attempts.json", attempts, run_dir)
    attempt_fields = sorted({key for attempt in attempts for key in attempt})
    write_csv(run_dir / "candidate_attempts.csv", attempt_fields, attempts, run_dir)
    write_json(
        run_dir / "performance_summary.json",
        {
            "task_seconds": {result["task_id"]: result["processing_seconds"] for result in results},
            "slowest_task": max(results, key=lambda item: float(item["processing_seconds"]))["task_id"],
            "attempt_count": len(attempts),
        },
        run_dir,
    )
    write_csv(run_dir / "visual_review_manifest.csv", visual_rows[0].keys(), visual_rows, run_dir)
    sha_rows = [
        {"role": "source", "task_or_sample": sample_id, "path": sample["absolute_path"], "sha256": sample["sha256"]}
        for sample_id, sample in samples.items()
    ]
    sha_rows.extend(
        {
            "role": "final_candidate",
            "task_or_sample": result["task_id"],
            "path": result["final_path"],
            "sha256": result.get("final_sha256", ""),
        }
        for result in successful
    )
    write_csv(run_dir / "sha256_manifest.csv", ("role", "task_or_sample", "path", "sha256"), sha_rows, run_dir)
    audit = {
        "manifest_sha256_valid": sha256_file(run_dir / "frozen_manifest.json") == (run_dir / "frozen_manifest.sha256").read_text(encoding="utf-8").strip(),
        "fixed_sample_count": len(samples) == 8,
        "fixed_task_count": len(results) == 40,
        "fixed_jpeg_qualities": JPEG_QUALITIES == (95, 92, 90, 88, 85, 82, 80),
        "fixed_poc_search_floor": MIN_POC_SEARCH_SCALE == 0.50,
        "originals_unchanged": originals_unchanged,
        "no_processing_scenarios_correct": expected_a and no_processing_clean,
        "safe_stop_scenarios_correct": expected_e,
        "successful_candidates_pass_automatic_gates": successful_pass,
        "jpeg_lossy_status_accurate": all(result["lossy"] and result["reencoded"] for result in successful if result["source_format"] == "JPEG"),
        "png_lossy_quantization_used": False,
        "format_conversion_used": False,
        "visual_review": "PENDING",
        "technical_audit": technical,
        "stage_2_gate": "READY_FOR_USER_REVIEW" if technical == "PASS" else "FAIL",
    }
    write_json(run_dir / "automatic_audit.json", audit, run_dir)
    write_run_summary(run_dir, results, attempts, technical)
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if technical == "PASS" else 2


TECHNICAL_DELIVERY_STATUSES = {
    "NO_PROCESSING_NEEDED",
    "TARGET_MET",
    "TARGET_MET_WITH_REENCODE",
    "CANNOT_MEET_SAFELY",
    "UNKNOWN",
}
PROCESSED_TECHNICAL_STATUSES = {"TARGET_MET", "TARGET_MET_WITH_REENCODE"}
VISUAL_REVIEW_STATUSES = {"NOT_REQUIRED", "PENDING", "PASS", "PASS_WITH_NOTES", "FAIL"}
DELIVERY_GATE_STATUSES = {
    "DELIVERY_READY",
    "DELIVERY_READY_WITH_NOTES",
    "REVIEW_REQUIRED",
    "CANNOT_MEET_SAFELY",
}


def evaluate_delivery_gate(
    technical_status: str,
    visual_review_status: str,
    delivery_risk_reasons: Iterable[str],
    review_notes_availability: str | None = None,
    review_notes: Iterable[str] = (),
) -> dict[str, Any]:
    """纯函数式PoC交付决策；风险标签只随结果记录，不直接等同于失败。"""

    risk_reasons = sorted(set(delivery_risk_reasons))
    persisted_notes = list(review_notes)
    if technical_status == "CANNOT_MEET_SAFELY":
        status = "CANNOT_MEET_SAFELY"
        eligible = False
        reason = "Technical processing could not meet constraints safely."
    elif technical_status in PROCESSED_TECHNICAL_STATUSES and visual_review_status == "FAIL":
        status = "CANNOT_MEET_SAFELY"
        eligible = False
        reason = "Visual review failed; candidate is evidence only and is not delivery eligible."
    elif technical_status in PROCESSED_TECHNICAL_STATUSES and visual_review_status == "PASS":
        status = "DELIVERY_READY"
        eligible = True
        reason = "Visual review passed."
    elif technical_status in PROCESSED_TECHNICAL_STATUSES and visual_review_status == "PASS_WITH_NOTES":
        status = "DELIVERY_READY_WITH_NOTES"
        eligible = True
        if review_notes_availability == "PERSISTED" and persisted_notes:
            reason = "Visual review passed with notes; human review notes were persisted in the final review source."
        else:
            reason = "Visual review passed with notes; detailed notes were not persisted in the final review source."
    elif technical_status in PROCESSED_TECHNICAL_STATUSES and visual_review_status == "PENDING":
        status = "REVIEW_REQUIRED"
        eligible = False
        reason = "Technical result requires human visual review before delivery."
    elif technical_status == "NO_PROCESSING_NEEDED" and visual_review_status == "NOT_REQUIRED":
        status = "DELIVERY_READY"
        eligible = True
        reason = "Source already meets target constraints; no candidate was generated or substituted."
    else:
        status = "REVIEW_REQUIRED"
        eligible = False
        reason = "Unknown or conflicting delivery evidence; manual review is required."
    return {
        "delivery_gate_status": status,
        "delivery_eligible": eligible,
        "delivery_decision_reason": reason,
        "delivery_risk_reasons": risk_reasons,
    }


def read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build_read_only_file_manifest(root: Path) -> dict[str, Any]:
    files = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: str(item).lower()):
        stat = path.stat()
        files.append(
            {
                "relative_path": path.relative_to(root).as_posix(),
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha256_file(path),
            }
        )
    return {
        "schema": "hdde_formal_run_file_manifest_v1",
        "formal_run_path": str(root),
        "file_count": len(files),
        "files": files,
    }


def compare_file_manifests(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_rows = {row["relative_path"]: row for row in before["files"]}
    after_rows = {row["relative_path"]: row for row in after["files"]}
    added = sorted(set(after_rows) - set(before_rows))
    removed = sorted(set(before_rows) - set(after_rows))
    modified = sorted(path for path in set(before_rows) & set(after_rows) if before_rows[path] != after_rows[path])
    return {
        "before_file_count": before["file_count"],
        "after_file_count": after["file_count"],
        "added_files": added,
        "removed_files": removed,
        "modified_files": modified,
        "path_changes": len(added) + len(removed),
        "unchanged": before["file_count"] == after["file_count"] and not added and not removed and not modified,
    }


def map_replay_technical_status(result: dict[str, Any], no_processing_verified: bool) -> str:
    status = result.get("status")
    technical_passed = result.get("technical_gate_passed") is True
    safety_stop = result.get("safety_stop") is True
    failure_reason = str(result.get("failure_reason") or "")
    if status == "NO_PROCESSING_NEEDED":
        return status if technical_passed and not safety_stop and not failure_reason and no_processing_verified else "UNKNOWN"
    if status in PROCESSED_TECHNICAL_STATUSES:
        return status if technical_passed and not safety_stop and not failure_reason else "UNKNOWN"
    if status == "CANNOT_MEET_SAFELY":
        return status if safety_stop else "UNKNOWN"
    return "UNKNOWN"


def derive_visual_required_task_ids(task_results: Iterable[dict[str, Any]]) -> set[str]:
    return {
        str(result["task_id"])
        for result in task_results
        if result.get("review_status") == "REVIEW_REQUIRED"
        and result.get("technical_gate_passed") is True
        and bool(result.get("final_path"))
        and bool(result.get("final_sha256"))
    }


def validate_visual_review_records(
    reviews: Any,
    known_task_ids: set[str],
    required_task_ids: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(reviews, list):
        raise RuntimeError("visual_review_fixture_reviews_missing")
    required_fields = {
        "task_id",
        "visual_review_status",
        "review_notes",
        "review_notes_availability",
    }
    allowed_availability = {"NOT_PERSISTED", "PERSISTED", "PERSISTED_CROSS_EVIDENCE"}
    review_map: dict[str, Any] = {}
    for index, review in enumerate(reviews):
        if not isinstance(review, dict):
            raise RuntimeError(f"visual_review_fixture_record_not_object:{index}")
        missing = sorted(required_fields - set(review))
        if missing:
            raise RuntimeError(f"visual_review_fixture_fields_missing:{review.get('task_id')}:{','.join(missing)}")
        task_id = review["task_id"]
        if not isinstance(task_id, str) or not task_id.strip():
            raise RuntimeError(f"visual_review_fixture_task_id_empty:{index}")
        if task_id in review_map:
            raise RuntimeError(f"visual_review_fixture_duplicate:{task_id}")
        if task_id not in known_task_ids:
            raise RuntimeError(f"visual_review_fixture_unknown_task:{task_id}")
        if review["visual_review_status"] not in {"PASS", "PASS_WITH_NOTES", "FAIL"}:
            raise RuntimeError(f"visual_review_fixture_invalid_status:{task_id}")
        notes = review["review_notes"]
        if not isinstance(notes, list) or not all(isinstance(note, str) and note.strip() for note in notes):
            raise RuntimeError(f"visual_review_fixture_notes_not_list:{task_id}")
        availability = review["review_notes_availability"]
        if availability not in allowed_availability:
            raise RuntimeError(f"visual_review_fixture_notes_availability_invalid:{task_id}")
        if availability == "NOT_PERSISTED" and notes:
            raise RuntimeError(f"visual_review_fixture_unpersisted_notes_not_empty:{task_id}")
        if availability in {"PERSISTED", "PERSISTED_CROSS_EVIDENCE"} and not notes:
            raise RuntimeError(f"visual_review_fixture_persisted_notes_empty:{task_id}")
        source_path_value = review.get("review_source_path")
        source_sha_value = review.get("review_source_sha256")
        if bool(source_path_value) != bool(source_sha_value):
            raise RuntimeError(f"visual_review_fixture_source_pair_incomplete:{task_id}")
        if source_path_value:
            source_path = Path(source_path_value)
            if not source_path.is_file() or sha256_file(source_path) != source_sha_value:
                raise RuntimeError(f"visual_review_fixture_source_mismatch:{task_id}")
        note_path_value = review.get("review_note_source_path")
        note_sha_value = review.get("review_note_source_sha256")
        if bool(note_path_value) != bool(note_sha_value):
            raise RuntimeError(f"visual_review_fixture_note_source_pair_incomplete:{task_id}")
        if note_path_value:
            note_path = Path(review["review_note_source_path"])
            if not note_path.is_file() or sha256_file(note_path) != note_sha_value:
                raise RuntimeError(f"visual_review_fixture_note_source_mismatch:{task_id}")
        review_map[task_id] = review
    required_ids = set(required_task_ids) if required_task_ids is not None else None
    missing_required = sorted(required_ids - set(review_map)) if required_ids is not None else []
    unexpected_required = sorted(set(review_map) - required_ids) if required_ids is not None else []
    if missing_required or unexpected_required:
        raise RuntimeError(
            "visual_review_fixture_task_set_mismatch:"
            f"missing={','.join(missing_required)}:unexpected={','.join(unexpected_required)}"
        )
    counts = {state: sum(item["visual_review_status"] == state for item in reviews) for state in ("PASS", "PASS_WITH_NOTES", "FAIL")}
    fail_tasks = sorted(item["task_id"] for item in reviews if item["visual_review_status"] == "FAIL")
    audit = {
        "fixture_count": len(reviews),
        "review_count": len(reviews),
        "unique_task_count": len(review_map),
        "duplicate_task_count": len(reviews) - len(review_map),
        "status_counts": counts,
        "fail_tasks": fail_tasks,
        "all_tasks_exist_in_formal_results": set(review_map) <= known_task_ids,
        "visual_required_task_count": len(required_ids) if required_ids is not None else None,
        "missing_required_task_ids": missing_required,
        "unexpected_task_ids": unexpected_required,
        "task_set_complete": not missing_required and not unexpected_required if required_ids is not None else None,
        "passed": True,
    }
    return review_map, audit


def load_visual_review_fixture(
    fixture_path: Path,
    known_task_ids: set[str],
    required_task_ids: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = read_json_file(fixture_path)
    review_map, audit = validate_visual_review_records(fixture.get("reviews"), known_task_ids, required_task_ids)
    audit.update(
        {
            "fixture_path": str(fixture_path),
            "fixture_sha256": sha256_file(fixture_path),
            "authority": fixture.get("authority", {}),
        }
    )
    return review_map, audit


def validate_fixture_fail_closed_cases() -> list[dict[str, Any]]:
    base = {
        "task_id": "known_task",
        "visual_review_status": "PASS",
        "review_notes": ["verified"],
        "review_notes_availability": "PERSISTED",
    }
    cases = [
        ("missing_task_id", [{key: value for key, value in base.items() if key != "task_id"}], {"known_task"}),
        ("duplicate_task_id", [dict(base), dict(base)], {"known_task"}),
        ("unknown_visual_review_status", [{**base, "visual_review_status": "UNKNOWN"}], {"known_task"}),
        ("unknown_task", [{**base, "task_id": "unknown_task"}], {"known_task"}),
        ("missing_visual_conclusion", [dict(base)], {"known_task", "missing_task"}),
    ]
    results = []
    for name, records, required_ids in cases:
        failed_closed = False
        error = ""
        try:
            validate_visual_review_records(records, {"known_task", "missing_task"}, required_ids)
        except RuntimeError as exc:
            failed_closed = True
            error = str(exc)
        results.append({"case": name, "failed_closed": failed_closed, "error": error})
    if not all(item["failed_closed"] for item in results):
        raise RuntimeError("visual_review_fixture_fail_closed_test_failed")
    return results


def validate_delivery_rule_priority() -> list[dict[str, Any]]:
    cases = [
        ("CANNOT_MEET_SAFELY", "FAIL", ["scale_lte_55pct"], "CANNOT_MEET_SAFELY", False),
        ("TARGET_MET", "FAIL", [], "CANNOT_MEET_SAFELY", False),
        ("TARGET_MET", "PASS", [], "DELIVERY_READY", True),
        ("TARGET_MET_WITH_REENCODE", "PASS_WITH_NOTES", ["jpeg_quality_lte_85"], "DELIVERY_READY_WITH_NOTES", True),
        ("TARGET_MET", "PENDING", ["tiny_chinese"], "REVIEW_REQUIRED", False),
        ("NO_PROCESSING_NEEDED", "NOT_REQUIRED", [], "DELIVERY_READY", True),
        ("UNKNOWN", "PASS", [], "REVIEW_REQUIRED", False),
    ]
    outcomes = []
    for technical, visual, risks, expected_status, expected_eligible in cases:
        result = evaluate_delivery_gate(technical, visual, risks)
        passed = result["delivery_gate_status"] == expected_status and result["delivery_eligible"] is expected_eligible
        outcomes.append(
            {
                "technical_status": technical,
                "visual_review_status": visual,
                "delivery_risk_reasons": risks,
                "expected_gate_status": expected_status,
                "expected_eligible": expected_eligible,
                "passed": passed,
            }
        )
    if not all(item["passed"] for item in outcomes):
        raise RuntimeError("delivery_rule_priority_test_failed")
    return outcomes


def build_delivery_replay_rows(
    task_results: Iterable[dict[str, Any]],
    review_map: dict[str, Any],
    risk_map: dict[str, list[str]],
    source_sha_by_path: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    replay_rows = []
    candidate_integrity = []
    for original in task_results:
        task_id = original["task_id"]
        source_path = Path(original["source_path"])
        source_sha = source_sha_by_path.get(
            str(source_path.resolve()), sha256_file(source_path) if source_path.is_file() else ""
        )
        if source_sha != original["source_sha256"]:
            raise RuntimeError(f"task_source_sha_mismatch:{task_id}")
        original_status = original.get("status")
        candidate_path = str(original.get("final_path") or "")
        candidate_sha = ""
        if candidate_path:
            candidate_file = Path(candidate_path)
            if not candidate_file.is_file():
                raise RuntimeError(f"task_candidate_missing:{task_id}")
            candidate_sha = sha256_file(candidate_file)
        no_processing_verified = (
            original_status == "NO_PROCESSING_NEEDED"
            and bool(candidate_path)
            and Path(candidate_path).resolve() == source_path.resolve()
            and candidate_sha == source_sha
            and original.get("safety_stop") is False
            and not original.get("failure_reason")
        )
        technical_status = map_replay_technical_status(original, no_processing_verified)
        if original_status in PROCESSED_TECHNICAL_STATUSES:
            expected_candidate_sha = str(original.get("final_sha256") or "")
            candidate_integrity.append(
                {
                    "task_id": task_id,
                    "path": candidate_path,
                    "expected_sha256": expected_candidate_sha,
                    "actual_sha256": candidate_sha,
                    "matched": bool(expected_candidate_sha) and expected_candidate_sha == candidate_sha,
                }
            )
        review = review_map.get(task_id)
        if review is not None:
            visual_status = review["visual_review_status"]
            review_notes = review["review_notes"]
            notes_availability = review["review_notes_availability"]
        elif technical_status == "NO_PROCESSING_NEEDED" and no_processing_verified:
            visual_status = "NOT_REQUIRED"
            review_notes = []
            notes_availability = "NOT_APPLICABLE_NO_PROCESSING"
        else:
            visual_status = "PENDING"
            review_notes = []
            notes_availability = "NOT_REVIEWED"
        decision = evaluate_delivery_gate(
            technical_status,
            visual_status,
            risk_map.get(task_id, []),
            notes_availability,
            review_notes,
        )
        if visual_status == "FAIL":
            candidate_role = "EVIDENCE_ONLY"
        elif technical_status == "NO_PROCESSING_NEEDED":
            candidate_role = "SOURCE_NO_PROCESSING"
        elif decision["delivery_eligible"]:
            candidate_role = "DELIVERY_CANDIDATE"
        elif candidate_path:
            candidate_role = "REVIEW_EVIDENCE_ONLY"
        else:
            candidate_role = "NO_CANDIDATE"
        replay_rows.append(
            {
                "task_id": task_id,
                "technical_status": technical_status,
                "visual_review_status": visual_status,
                "delivery_risk_reasons": decision["delivery_risk_reasons"],
                "delivery_gate_status": decision["delivery_gate_status"],
                "delivery_eligible": decision["delivery_eligible"],
                "delivery_decision_reason": decision["delivery_decision_reason"],
                "source_path": str(source_path),
                "candidate_path": candidate_path,
                "source_sha256": source_sha,
                "candidate_sha256": candidate_sha,
                "review_notes": review_notes,
                "review_notes_availability": notes_availability,
                "candidate_delivery_role": candidate_role,
                "technical_status_source": original_status,
            }
        )
    return replay_rows, candidate_integrity


def replay_delivery_gate(formal_run_dir: Path, fixture_path: Path, output_dir: Path) -> int:
    formal_run_dir = formal_run_dir.resolve()
    fixture_path = fixture_path.resolve()
    output_dir = output_dir.resolve()
    if formal_run_dir == ALLOWED_RUN_ROOT or ALLOWED_RUN_ROOT not in formal_run_dir.parents:
        raise SystemExit(f"run_dir_must_be_child_of:{ALLOWED_RUN_ROOT}")
    if output_dir == ALLOWED_DELIVERY_GATE_REPLAY_ROOT or ALLOWED_DELIVERY_GATE_REPLAY_ROOT not in output_dir.parents:
        raise SystemExit(f"output_dir_must_be_child_of:{ALLOWED_DELIVERY_GATE_REPLAY_ROOT}")
    if output_dir == formal_run_dir or formal_run_dir in output_dir.parents or output_dir in formal_run_dir.parents:
        raise SystemExit("replay_output_must_be_separate_from_formal_run")
    if not formal_run_dir.is_dir() or not fixture_path.is_file() or not output_dir.is_dir():
        raise SystemExit("replay_input_or_output_missing")
    if (output_dir / "delivery_gate_replay.json").exists():
        raise SystemExit("delivery_gate_replay_already_exists;refusing_to_overwrite")

    required_inputs = {
        "frozen_manifest": formal_run_dir / "frozen_manifest.json",
        "frozen_manifest_sha": formal_run_dir / "frozen_manifest.sha256",
        "task_results": formal_run_dir / "task_results.json",
        "candidate_attempts": formal_run_dir / "candidate_attempts.json",
        "review_package": formal_run_dir / "visual_review_package" / "review_package_manifest.json",
        "formal_manifest_before": output_dir / "formal_run_manifest_before.json",
        "source_snapshot_manifest": output_dir / "source_snapshot_manifest.json",
    }
    missing_inputs = [name for name, path in required_inputs.items() if not path.is_file()]
    if missing_inputs:
        raise RuntimeError(f"replay_required_inputs_missing:{','.join(missing_inputs)}")

    source_snapshot_manifest = read_json_file(required_inputs["source_snapshot_manifest"])
    snapshot_path = Path(source_snapshot_manifest.get("snapshot_path", ""))
    source_path = Path(source_snapshot_manifest.get("source_path", ""))
    fixture_snapshot_path = Path(source_snapshot_manifest.get("fixture_snapshot_path", ""))
    if source_path.resolve() != Path(__file__).resolve():
        raise RuntimeError("source_snapshot_target_mismatch")
    if not snapshot_path.is_file() or not fixture_snapshot_path.is_file():
        raise RuntimeError("source_or_fixture_snapshot_missing")
    snapshot_sha = sha256_file(snapshot_path)
    if snapshot_sha != source_snapshot_manifest.get("snapshot_sha256") or snapshot_sha != source_snapshot_manifest.get("source_sha256"):
        raise RuntimeError("source_snapshot_sha_mismatch")
    if sha256_file(fixture_snapshot_path) != source_snapshot_manifest.get("fixture_snapshot_sha256"):
        raise RuntimeError("fixture_snapshot_sha_mismatch")
    before_lines = snapshot_path.read_text(encoding="utf-8").splitlines(keepends=True)
    after_lines = source_path.read_text(encoding="utf-8").splitlines(keepends=True)
    implementation_diff = "".join(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile="a/tools/experiments/image_upload_adaptation_poc.py",
            tofile="b/tools/experiments/image_upload_adaptation_poc.py",
        )
    )
    if not implementation_diff:
        raise RuntimeError("implementation_diff_empty")
    write_text(output_dir / "implementation_diff.patch", implementation_diff, output_dir)

    frozen_manifest = read_json_file(required_inputs["frozen_manifest"])
    declared_manifest_sha = required_inputs["frozen_manifest_sha"].read_text(encoding="utf-8").strip()
    if sha256_file(required_inputs["frozen_manifest"]) != declared_manifest_sha:
        raise RuntimeError("formal_frozen_manifest_sha_mismatch")
    task_results = read_json_file(required_inputs["task_results"])
    attempts = read_json_file(required_inputs["candidate_attempts"])
    review_package = read_json_file(required_inputs["review_package"])
    before_manifest = read_json_file(required_inputs["formal_manifest_before"])
    if len(task_results) != 40 or len({item["task_id"] for item in task_results}) != 40:
        raise RuntimeError("formal_task_result_count_or_uniqueness_mismatch")
    if len(attempts) != 311:
        raise RuntimeError("formal_candidate_attempt_count_mismatch")
    if frozen_manifest.get("sample_count") != 8 or frozen_manifest.get("task_count") != 40:
        raise RuntimeError("formal_frozen_counts_mismatch")

    known_task_ids = {item["task_id"] for item in task_results}
    visual_required_task_ids = derive_visual_required_task_ids(task_results)
    review_map, fixture_audit = load_visual_review_fixture(
        fixture_path, known_task_ids, visual_required_task_ids
    )
    old_review_map, old_fixture_audit = load_visual_review_fixture(
        fixture_snapshot_path, known_task_ids
    )

    risk_tasks = review_package.get("tasks")
    if not isinstance(risk_tasks, list):
        raise RuntimeError("review_package_tasks_missing")
    risk_map: dict[str, list[str]] = {}
    for item in risk_tasks:
        task_id = item.get("task_id")
        reasons = item.get("risk_reasons", [])
        if task_id in risk_map or not isinstance(reasons, list) or not all(isinstance(reason, str) and reason for reason in reasons):
            raise RuntimeError(f"invalid_structured_risk_record:{task_id}")
        risk_map[task_id] = sorted(set(reasons))

    source_records = {sample["sample_id"]: sample for sample in frozen_manifest["samples"]}
    source_integrity = []
    source_sha_by_path: dict[str, str] = {}
    for sample in source_records.values():
        formal_source_path = Path(sample["absolute_path"])
        actual_sha = sha256_file(formal_source_path) if formal_source_path.is_file() else ""
        source_sha_by_path[str(formal_source_path.resolve())] = actual_sha
        source_integrity.append(
            {
                "sample_id": sample["sample_id"],
                "path": str(formal_source_path),
                "expected_sha256": sample["sha256"],
                "actual_sha256": actual_sha,
                "matched": actual_sha == sample["sha256"],
            }
        )
    if len(source_integrity) != 8 or not all(item["matched"] for item in source_integrity):
        raise RuntimeError("formal_source_integrity_failed")

    replay_rows, candidate_integrity = build_delivery_replay_rows(
        task_results, review_map, risk_map, source_sha_by_path
    )
    old_replay_rows, _ = build_delivery_replay_rows(
        task_results, old_review_map, risk_map, source_sha_by_path
    )
    if len(candidate_integrity) != 23 or not all(item["matched"] for item in candidate_integrity):
        raise RuntimeError("formal_candidate_integrity_failed")

    required_fields = {
        "task_id",
        "technical_status",
        "visual_review_status",
        "delivery_risk_reasons",
        "delivery_gate_status",
        "delivery_eligible",
        "delivery_decision_reason",
        "source_path",
        "candidate_path",
        "source_sha256",
        "candidate_sha256",
    }
    if len(replay_rows) != 40 or len({row["task_id"] for row in replay_rows}) != 40:
        raise RuntimeError("delivery_replay_count_or_uniqueness_mismatch")
    if any(required_fields - set(row) for row in replay_rows):
        raise RuntimeError("delivery_replay_required_fields_missing")
    if any(row["technical_status"] not in TECHNICAL_DELIVERY_STATUSES for row in replay_rows):
        raise RuntimeError("delivery_replay_technical_enum_invalid")
    if any(row["visual_review_status"] not in VISUAL_REVIEW_STATUSES for row in replay_rows):
        raise RuntimeError("delivery_replay_visual_enum_invalid")
    if any(row["delivery_gate_status"] not in DELIVERY_GATE_STATUSES for row in replay_rows):
        raise RuntimeError("delivery_replay_gate_enum_invalid")
    if any(not isinstance(row["delivery_eligible"], bool) for row in replay_rows):
        raise RuntimeError("delivery_replay_eligibility_not_boolean")

    gate_counts = {
        state: sum(row["delivery_gate_status"] == state for row in replay_rows)
        for state in sorted(DELIVERY_GATE_STATUSES)
    }
    old_gate_counts = {
        state: sum(row["delivery_gate_status"] == state for row in old_replay_rows)
        for state in sorted(DELIVERY_GATE_STATUSES)
    }
    reviewed_pass_false_blocks = [
        row["task_id"]
        for row in replay_rows
        if row["task_id"] in review_map
        and review_map[row["task_id"]]["visual_review_status"] in {"PASS", "PASS_WITH_NOTES"}
        and not row["delivery_eligible"]
    ]
    pending_tasks = sorted(
        row["task_id"]
        for row in replay_rows
        if row["technical_status"] in PROCESSED_TECHNICAL_STATUSES and row["visual_review_status"] == "PENDING"
    )
    old_pending_tasks = sorted(
        row["task_id"]
        for row in old_replay_rows
        if row["technical_status"] in PROCESSED_TECHNICAL_STATUSES and row["visual_review_status"] == "PENDING"
    )
    no_processing_tasks = [row for row in replay_rows if row["technical_status"] == "NO_PROCESSING_NEEDED"]
    real_alpha = next(row for row in replay_rows if row["task_id"] == "real_alpha__D")
    technical_status_unchanged = all(row["technical_status"] == row["technical_status_source"] for row in replay_rows)
    rule_priority_tests = validate_delivery_rule_priority()
    fail_closed_tests = validate_fixture_fail_closed_cases()

    four_expected = {
        "cn_small__B": ("TARGET_MET", "PASS_WITH_NOTES", "DELIVERY_READY_WITH_NOTES", True),
        "dark_material__B": ("TARGET_MET", "PASS", "DELIVERY_READY", True),
        "light_infographic__C": ("TARGET_MET", "PASS", "DELIVERY_READY", True),
        "logo_product__C": ("TARGET_MET", "PASS_WITH_NOTES", "DELIVERY_READY_WITH_NOTES", True),
    }
    row_by_id = {row["task_id"]: row for row in replay_rows}
    four_task_assertions = {
        task_id: (
            row_by_id[task_id]["technical_status"],
            row_by_id[task_id]["visual_review_status"],
            row_by_id[task_id]["delivery_gate_status"],
            row_by_id[task_id]["delivery_eligible"],
        )
        == expected
        for task_id, expected in four_expected.items()
    }
    persisted_note_tasks = [row_by_id["cn_small__B"], row_by_id["logo_product__C"]]
    persisted_notes_semantics = all(
        row["review_notes_availability"] == "PERSISTED"
        and bool(row["review_notes"])
        and "not persisted" not in row["delivery_decision_reason"].lower()
        for row in persisted_note_tasks
    )
    old_unpersisted_example = next(
        row
        for row in replay_rows
        if row["visual_review_status"] == "PASS_WITH_NOTES"
        and row["review_notes_availability"] == "NOT_PERSISTED"
    )
    unpersisted_notes_semantics = (
        old_unpersisted_example["review_notes"] == []
        and "not persisted" in old_unpersisted_example["delivery_decision_reason"].lower()
    )

    assertions = {
        "fixture_audit_passed": fixture_audit["passed"],
        "fixture_task_set_complete": fixture_audit["task_set_complete"] is True,
        "technical_task_count_40": len(replay_rows) == 40,
        "technical_status_unchanged": technical_status_unchanged,
        "real_alpha_d_failure_intercepted": real_alpha["technical_status"] == "TARGET_MET"
        and real_alpha["visual_review_status"] == "FAIL"
        and real_alpha["delivery_gate_status"] == "CANNOT_MEET_SAFELY"
        and real_alpha["delivery_eligible"] is False
        and real_alpha["candidate_delivery_role"] == "EVIDENCE_ONLY",
        "reviewed_pass_false_blocks_zero": not reviewed_pass_false_blocks,
        "unreviewed_tasks_fail_closed": all(
            row["delivery_gate_status"] == "REVIEW_REQUIRED" and row["delivery_eligible"] is False
            for row in replay_rows
            if row["task_id"] in pending_tasks
        ),
        "no_processing_tasks_not_required": len(no_processing_tasks) == 8
        and all(
            row["visual_review_status"] == "NOT_REQUIRED"
            and row["delivery_gate_status"] == "DELIVERY_READY"
            and row["delivery_eligible"] is True
            for row in no_processing_tasks
        ),
        "source_assets_8_of_8": len(source_integrity) == 8 and all(item["matched"] for item in source_integrity),
        "final_candidates_23_of_23": len(candidate_integrity) == 23 and all(item["matched"] for item in candidate_integrity),
        "candidate_attempt_records_unchanged_311": len(attempts) == 311,
        "rule_priority_tests_passed": all(item["passed"] for item in rule_priority_tests),
        "fixture_fail_closed_tests_passed": all(item["failed_closed"] for item in fail_closed_tests),
    }
    if not all(assertions.values()):
        raise RuntimeError("delivery_gate_replay_general_assertion_failed")

    # 以下仅是当前唯一正式运行的收口断言，不参与通用夹具读取或单项交付映射。
    final_expected_fixture_counts = {"PASS": 3, "PASS_WITH_NOTES": 19, "FAIL": 1}
    final_expected_gate_counts = {
        "DELIVERY_READY": 11,
        "DELIVERY_READY_WITH_NOTES": 19,
        "CANNOT_MEET_SAFELY": 10,
        "REVIEW_REQUIRED": 0,
    }
    old_expected_gate_counts = {
        "DELIVERY_READY": 9,
        "DELIVERY_READY_WITH_NOTES": 17,
        "CANNOT_MEET_SAFELY": 10,
        "REVIEW_REQUIRED": 4,
    }
    formal_closure_assertions = {
        "visual_required_task_count_23": len(visual_required_task_ids) == 23,
        "fixture_count_23": fixture_audit["fixture_count"] == 23,
        "fixture_status_distribution_match": fixture_audit["status_counts"] == final_expected_fixture_counts,
        "unique_fail_real_alpha_d": fixture_audit["fail_tasks"] == ["real_alpha__D"],
        "final_gate_distribution_match": gate_counts == final_expected_gate_counts,
        "review_required_zero": not pending_tasks and gate_counts["REVIEW_REQUIRED"] == 0,
        "four_new_task_decisions_match": all(four_task_assertions.values()),
        "old_fixture_count_19": old_fixture_audit["fixture_count"] == 19,
        "old_state_distribution_match": old_gate_counts == old_expected_gate_counts,
        "old_state_pending_tasks_4": len(old_pending_tasks) == 4,
        "persisted_notes_semantics": persisted_notes_semantics,
        "unpersisted_notes_semantics": unpersisted_notes_semantics,
    }
    if not all(formal_closure_assertions.values()):
        raise RuntimeError("delivery_gate_formal_closure_assertion_failed")

    after_manifest = build_read_only_file_manifest(formal_run_dir)
    manifest_comparison = compare_file_manifests(before_manifest, after_manifest)
    if before_manifest.get("file_count") != 1002 or not manifest_comparison["unchanged"]:
        raise RuntimeError("formal_run_changed_during_delivery_replay")
    write_json(output_dir / "formal_run_manifest_after.json", after_manifest, output_dir)
    write_json(output_dir / "formal_run_manifest_comparison.json", manifest_comparison, output_dir)
    write_json(output_dir / "visual_review_fixture_audit.json", fixture_audit, output_dir)

    validation_results = {
        "schema": "hdde_delivery_gate_dynamic_fixture_validation_v1",
        "visual_required_task_count": len(visual_required_task_ids),
        "visual_required_task_ids": sorted(visual_required_task_ids),
        "fixture_count": fixture_audit["fixture_count"],
        "fixture_status_counts": fixture_audit["status_counts"],
        "old_state_compatibility": {
            "fixture_count": old_fixture_audit["fixture_count"],
            "status_counts": old_gate_counts,
            "review_required_task_ids": old_pending_tasks,
            "expected_status_counts": old_expected_gate_counts,
            "passed": old_gate_counts == old_expected_gate_counts and len(old_pending_tasks) == 4,
        },
        "final_state": {
            "status_counts": gate_counts,
            "review_required_count": len(pending_tasks),
            "review_required_task_ids": pending_tasks,
            "expected_status_counts": final_expected_gate_counts,
            "passed": gate_counts == final_expected_gate_counts and not pending_tasks,
        },
        "persisted_notes_tasks": persisted_note_tasks,
        "unpersisted_notes_example": old_unpersisted_example,
        "fixture_fail_closed_tests": fail_closed_tests,
        "rule_priority_tests": rule_priority_tests,
        "four_new_task_assertions": four_task_assertions,
        "general_assertions": assertions,
        "formal_closure_assertions": formal_closure_assertions,
        "passed": all(assertions.values()) and all(formal_closure_assertions.values()),
    }
    write_json(output_dir / "validation_results.json", validation_results, output_dir)

    replay_payload = {
        "schema": "hdde_image_upload_adaptation_delivery_gate_replay_v1",
        "formal_run_path": str(formal_run_dir),
        "formal_task_results_path": str(required_inputs["task_results"]),
        "formal_task_results_sha256": sha256_file(required_inputs["task_results"]),
        "visual_review_fixture_path": str(fixture_path),
        "visual_review_fixture_sha256": sha256_file(fixture_path),
        "visual_required_task_count": len(visual_required_task_ids),
        "fixture_count": fixture_audit["fixture_count"],
        "fixture_status_counts": fixture_audit["status_counts"],
        "structured_risk_source_path": str(required_inputs["review_package"]),
        "structured_risk_source_sha256": sha256_file(required_inputs["review_package"]),
        "status_counts": gate_counts,
        "review_required_count": len(pending_tasks),
        "review_required_task_ids": pending_tasks,
        "delivery_eligible_true": sum(row["delivery_eligible"] is True for row in replay_rows),
        "delivery_eligible_false": sum(row["delivery_eligible"] is False for row in replay_rows),
        "reviewed_pass_false_blocks": reviewed_pass_false_blocks,
        "assertions": assertions,
        "formal_closure_assertions": formal_closure_assertions,
        "results": replay_rows,
    }
    write_json(output_dir / "delivery_gate_replay.json", replay_payload, output_dir)
    csv_rows = []
    for row in replay_rows:
        flat = dict(row)
        flat["delivery_risk_reasons"] = json.dumps(row["delivery_risk_reasons"], ensure_ascii=False)
        flat["review_notes"] = json.dumps(row["review_notes"], ensure_ascii=False)
        csv_rows.append(flat)
    write_csv(output_dir / "delivery_gate_replay.csv", csv_rows[0].keys(), csv_rows, output_dir)
    summary_lines = [
        "# HDDE Upload Adaptation Delivery Gate Replay v1",
        "",
        f"- Formal run: `{formal_run_dir}`",
        f"- Tasks: {len(replay_rows)}",
        f"- Visual fixture: {fixture_audit['fixture_count']}",
        f"- Status counts: `{json.dumps(gate_counts, ensure_ascii=False, sort_keys=True)}`",
        f"- Delivery eligible true: {sum(row['delivery_eligible'] is True for row in replay_rows)}",
        f"- Delivery eligible false: {sum(row['delivery_eligible'] is False for row in replay_rows)}",
        f"- REVIEW_REQUIRED count: {len(pending_tasks)}",
        f"- REVIEW_REQUIRED tasks: `{json.dumps(pending_tasks, ensure_ascii=False)}`",
        f"- real_alpha__D: `{json.dumps(real_alpha, ensure_ascii=False, sort_keys=True)}`",
        "",
        "OLD_19_RECORD_COMPATIBILITY_TEST: PASS",
        "FINAL_23_RECORD_REPLAY_TEST: PASS",
        "DELIVERY_GATE_REPLAY: PASS",
        "IMAGE_POC_RERUN: NO",
        "CANDIDATE_SEARCH_RERUN: NO",
        "IMAGES_REGENERATED: 0",
    ]
    write_text(output_dir / "delivery_gate_replay_summary.md", "\n".join(summary_lines), output_dir)

    post_audit = {
        "schema": "hdde_image_upload_adaptation_delivery_gate_post_execution_audit_v1",
        "precondition_check": "PASS",
        "visual_fixture_build": "PASS",
        "fixture_count": fixture_audit["fixture_count"],
        "fixture_status_counts": fixture_audit["status_counts"],
        "visual_required_task_count": len(visual_required_task_ids),
        "technical_task_count": len(replay_rows),
        "pure_decision_replay": "PASS",
        "real_alpha_d_blocked": "PASS",
        "visual_pass_tasks_not_wrongly_blocked": len(reviewed_pass_false_blocks) == 0,
        "review_required_count": len(pending_tasks),
        "review_required_task_ids": pending_tasks,
        "no_processing_tasks_not_required": len(no_processing_tasks),
        "status_counts": gate_counts,
        "expected_status_distribution_match": gate_counts == final_expected_gate_counts,
        "old_state_compatibility": validation_results["old_state_compatibility"],
        "fixture_fail_closed_tests": fail_closed_tests,
        "persisted_notes_semantics": persisted_notes_semantics,
        "formal_asset_protection": "PASS" if manifest_comparison["unchanged"] else "FAIL",
        "formal_run_manifest_comparison": manifest_comparison,
        "source_integrity": source_integrity,
        "candidate_integrity": candidate_integrity,
        "candidate_attempt_record_count": len(attempts),
        "technical_status_unchanged": technical_status_unchanged,
        "output_file_sha256": {
            path.name: sha256_file(path)
            for path in sorted(output_dir.iterdir(), key=lambda item: item.name)
            if path.is_file()
        },
        "files_staged": False,
        "commit": False,
        "push": False,
        "tag": False,
        "pr": False,
        "next_stage_started": False,
        "passed": all(assertions.values())
        and all(formal_closure_assertions.values())
        and manifest_comparison["unchanged"],
    }
    write_json(output_dir / "post_execution_audit.json", post_audit, output_dir)
    post_lines = [
        "# HDDE Delivery Gate Post-Execution Audit",
        "",
        f"- Pure decision replay: {post_audit['pure_decision_replay']}",
        f"- Formal asset protection: {post_audit['formal_asset_protection']}",
        f"- Technical status unchanged: {technical_status_unchanged}",
        f"- Fixture count: {fixture_audit['fixture_count']}",
        f"- REVIEW_REQUIRED count: {len(pending_tasks)}",
        f"- Source SHA: {sum(item['matched'] for item in source_integrity)}/8",
        f"- Candidate SHA: {sum(item['matched'] for item in candidate_integrity)}/23",
        f"- Formal run files: {after_manifest['file_count']}",
        "",
        f"POST_EXECUTION_AUDIT: {'PASS' if post_audit['passed'] else 'FAIL'}",
    ]
    write_text(output_dir / "post_execution_audit.md", "\n".join(post_lines), output_dir)
    print(json.dumps(post_audit, ensure_ascii=False, indent=2))
    return 0 if post_audit["passed"] else 2


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    if args.phase == "replay-delivery-gate":
        if args.visual_review_fixture is None or args.output_dir is None:
            raise SystemExit("replay-delivery-gate requires --visual-review-fixture and --output-dir")
        return replay_delivery_gate(run_dir, args.visual_review_fixture, args.output_dir)
    if run_dir == ALLOWED_RUN_ROOT or ALLOWED_RUN_ROOT not in run_dir.parents:
        raise SystemExit(f"run_dir_must_be_child_of:{ALLOWED_RUN_ROOT}")
    if args.phase == "prepare":
        return prepare(run_dir)
    if not run_dir.is_dir():
        raise SystemExit(f"run_dir_missing:{run_dir}")
    return run_experiment(run_dir)


if __name__ == "__main__":
    raise SystemExit(main())
