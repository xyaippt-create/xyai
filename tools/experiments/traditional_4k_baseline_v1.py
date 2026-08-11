from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from PIL import Image, ImageOps


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "4k_stage1_baseline"
DEFAULT_MANIFEST = ARTIFACT_ROOT / "golden_samples_manifest.json"
DEFAULT_STANDARD = ARTIFACT_ROOT / "4k_standard_v1.json"
SETTINGS_PATH = PROJECT_ROOT / "settings" / "settings.json"
FORMAL_4K_DIRECTORY = Path(r"D:\影界文件\输出\4K高清增强")
PROJECT_RUNTIME_DIRECTORIES = (
    PROJECT_ROOT / "runtime_data",
    PROJECT_ROOT / "tmp" / "runtime_data",
)
METHODS = ("pillow_bicubic", "pillow_lanczos", "opencv_cubic")
METHOD_LABELS = {
    "pillow_bicubic": "Pillow BICUBIC",
    "pillow_lanczos": "Pillow LANCZOS",
    "opencv_cubic": "OpenCV INTER_CUBIC",
}
FORBIDDEN_SOURCE_MARKERS = (
    "1080p标准版",
    "1080p安全增强",
    "_影界高清_1080p",
    "_1080p_beta",
    "safe_1080p",
    "4k_stage1_baseline/candidates",
)


class BaselineError(RuntimeError):
    pass


class CandidateExecutionError(BaselineError):
    def __init__(self, record: dict[str, Any]):
        self.record = record
        super().__init__(
            f"{record['sample_id']}:{record['method']}:{record['failure_stage']}:"
            f"{record['error_type']}:{record['error_message']}"
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pixel_sha256(path: Path) -> str:
    with Image.open(path) as image:
        image.load()
        normalized = ImageOps.exif_transpose(image)
        payload = normalized.tobytes() + normalized.mode.encode("ascii") + repr(normalized.size).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_output_root(output_root: Path) -> Path:
    resolved = output_root.resolve()
    if not is_relative_to(resolved, ARTIFACT_ROOT.resolve()):
        raise BaselineError(f"OUTPUT_ROOT_OUTSIDE_STAGE_ARTIFACTS:{resolved}")
    if resolved == PROJECT_ROOT.resolve() or resolved in {item.resolve() for item in PROJECT_RUNTIME_DIRECTORIES}:
        raise BaselineError(f"OUTPUT_ROOT_FORBIDDEN:{resolved}")
    return resolved


def target_dimensions(width: int, height: int, target_long_edge: int = 3840) -> tuple[str, tuple[int, int] | None]:
    if width <= 0 or height <= 0:
        raise ValueError("INVALID_SOURCE_DIMENSIONS")
    if max(width, height) >= target_long_edge:
        return "NO_PROCESSING_NEEDED", None
    scale = target_long_edge / max(width, height)
    target_width = max(1, int(math.floor(width * scale + 0.5)))
    target_height = max(1, int(math.floor(height * scale + 0.5)))
    return "PROCESS", (target_width, target_height)


def source_directness_status(source: Path, declared_role: str) -> str:
    normalized = source.resolve().as_posix().lower()
    if not declared_role.endswith("ORIGINAL_INPUT"):
        return "REJECTED_SOURCE_ROLE"
    if any(marker in normalized for marker in FORBIDDEN_SOURCE_MARKERS):
        return "REJECTED_INTERMEDIATE_SOURCE"
    return "PASS"


def capture_file_state(path: Path) -> dict[str, Any]:
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


def directory_fingerprint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path.resolve()), "exists": False}
    if not path.is_dir():
        return {"path": str(path.resolve()), "exists": True, "is_directory": False, "sha256": sha256_file(path)}
    digest = hashlib.sha256()
    count = 0
    for child in sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: item.as_posix().lower()):
        relative = child.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(str(child.stat().st_size).encode("ascii"))
        digest.update(sha256_file(child).encode("ascii"))
        count += 1
    return {
        "path": str(path.resolve()),
        "exists": True,
        "is_directory": True,
        "file_count": count,
        "tree_content_sha256": digest.hexdigest(),
    }


def capture_protected_state() -> dict[str, Any]:
    return {
        "settings": capture_file_state(SETTINGS_PATH),
        "formal_4k_directory": directory_fingerprint(FORMAL_4K_DIRECTORY),
        "project_runtime_directories": [directory_fingerprint(path) for path in PROJECT_RUNTIME_DIRECTORIES],
    }


def read_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    samples = payload.get("samples")
    if payload.get("sample_count") != 8 or not isinstance(samples, list) or len(samples) != 8:
        raise BaselineError("MANIFEST_SAMPLE_COUNT_MUST_BE_8")
    if len({sample.get("sample_id") for sample in samples}) != 8:
        raise BaselineError("MANIFEST_SAMPLE_IDS_NOT_UNIQUE")
    return payload


def normalized_source_image(source: Path) -> tuple[Image.Image, dict[str, Any]]:
    with Image.open(source) as opened:
        opened.load()
        info = dict(opened.info or {})
        orientation = opened.getexif().get(274)
        image = ImageOps.exif_transpose(opened).copy()
        source_format = str(opened.format or "UNKNOWN").upper()
    if image.mode not in {"RGB", "RGBA", "L", "LA"}:
        image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in info else "RGB")
    return image, {
        "source_format": "JPEG" if source_format == "JPG" else source_format,
        "source_mode": image.mode,
        "source_orientation": orientation,
        "icc_profile": info.get("icc_profile") if isinstance(info.get("icc_profile"), bytes) else None,
    }


def clear_transparent_rgb(image: Image.Image) -> Image.Image:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    rgba[..., :3][rgba[..., 3] == 0] = 0
    return Image.fromarray(rgba, mode="RGBA")


def resize_pillow(image: Image.Image, size: tuple[int, int], resample: Image.Resampling) -> Image.Image:
    if "A" in image.getbands():
        resized = image.convert("RGBA").convert("RGBa").resize(size, resample=resample).convert("RGBA")
        return clear_transparent_rgb(resized)
    return image.resize(size, resample=resample)


def resize_opencv_cubic(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    if "A" in image.getbands():
        rgba = np.asarray(image.convert("RGBA"), dtype=np.float32) / 255.0
        alpha = rgba[..., 3:4]
        premultiplied = rgba[..., :3] * alpha
        resized_rgb = cv2.resize(premultiplied, size, interpolation=cv2.INTER_CUBIC)
        resized_alpha = cv2.resize(alpha[..., 0], size, interpolation=cv2.INTER_CUBIC)[..., None]
        resized_alpha = np.clip(resized_alpha, 0.0, 1.0)
        rgb = np.zeros_like(resized_rgb)
        np.divide(resized_rgb, resized_alpha, out=rgb, where=resized_alpha > 1e-7)
        output = np.concatenate((np.clip(rgb, 0.0, 1.0), resized_alpha), axis=2)
        return clear_transparent_rgb(Image.fromarray(np.rint(output * 255.0).astype(np.uint8), mode="RGBA"))
    source_array = np.asarray(image)
    resized = cv2.resize(source_array, size, interpolation=cv2.INTER_CUBIC)
    return Image.fromarray(resized, mode=image.mode)


def resize_image(image: Image.Image, size: tuple[int, int], method: str) -> Image.Image:
    if method == "pillow_bicubic":
        return resize_pillow(image, size, Image.Resampling.BICUBIC)
    if method == "pillow_lanczos":
        return resize_pillow(image, size, Image.Resampling.LANCZOS)
    if method == "opencv_cubic":
        return resize_opencv_cubic(image, size)
    raise ValueError(f"UNKNOWN_METHOD:{method}")


def save_png_temp(image: Image.Image, destination: Path, icc_profile: bytes | None) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.stem}.", suffix=".png.tmp", dir=destination.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    options: dict[str, Any] = {"format": "PNG", "compress_level": 6, "optimize": False}
    if icc_profile:
        options["icc_profile"] = icc_profile
    try:
        image.save(temp_path, **options)
        return temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def commit_candidate(temp_path: Path, destination: Path) -> str:
    new_hash = sha256_file(temp_path)
    if destination.exists():
        if not destination.is_file():
            temp_path.unlink(missing_ok=True)
            raise BaselineError(f"CANDIDATE_PATH_NOT_FILE:{destination}")
        if sha256_file(destination) != new_hash:
            temp_path.unlink(missing_ok=True)
            raise BaselineError(f"CANDIDATE_CONFLICT_DIFFERENT_CONTENT:{destination}")
        temp_path.unlink(missing_ok=True)
        return "REUSED_IDENTICAL"
    os.replace(temp_path, destination)
    return "CREATED"


def verify_decode(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        image.load()
        width, height = image.size
        mode = image.mode
        file_format = str(image.format or "UNKNOWN").upper()
        has_alpha = "A" in image.getbands()
        alpha_extrema = image.getchannel("A").getextrema() if has_alpha else None
    with Image.open(path) as image:
        image.verify()
    return {
        "width": width,
        "height": height,
        "mode": mode,
        "format": file_format,
        "has_alpha": has_alpha,
        "alpha_extrema": list(alpha_extrema) if alpha_extrema else None,
        "decode_status": "PASS",
    }


def verify_manifest_sample(sample: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    source = Path(sample["source_path"])
    if not source.is_file():
        raise BaselineError(f"SOURCE_MISSING:{sample['sample_id']}:{source}")
    directness = source_directness_status(source, sample["source_role"])
    if directness != "PASS":
        raise BaselineError(f"SOURCE_DIRECTNESS_FAILED:{sample['sample_id']}:{directness}")
    state = capture_file_state(source)
    for field in ("size_bytes", "mtime_ns", "sha256"):
        if state[field] != sample[field]:
            raise BaselineError(f"SOURCE_MANIFEST_MISMATCH:{sample['sample_id']}:{field}")
    image, meta = normalized_source_image(source)
    if image.size != (sample["width"], sample["height"]):
        raise BaselineError(f"SOURCE_DIMENSION_MISMATCH:{sample['sample_id']}")
    if meta["source_format"] != sample["format"] or image.mode != sample["mode"]:
        raise BaselineError(f"SOURCE_FORMAT_OR_MODE_MISMATCH:{sample['sample_id']}")
    if ("A" in image.getbands()) != sample["has_alpha"]:
        raise BaselineError(f"SOURCE_ALPHA_MISMATCH:{sample['sample_id']}")
    return source, {"image": image, **meta, "directness": directness}


def snapshot_source(sample: dict[str, Any], source: Path, output_root: Path) -> dict[str, Any]:
    destination = output_root / "golden_samples" / sample["snapshot_file_name"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_file() or sha256_file(destination) != sample["sha256"]:
            raise BaselineError(f"SNAPSHOT_CONFLICT_DIFFERENT_CONTENT:{destination}")
        status = "REUSED_IDENTICAL"
    else:
        fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            shutil.copyfile(source, temp_path)
            if sha256_file(temp_path) != sample["sha256"] or temp_path.stat().st_size != sample["size_bytes"]:
                raise BaselineError(f"SNAPSHOT_COPY_VERIFICATION_FAILED:{sample['sample_id']}")
            os.replace(temp_path, destination)
        finally:
            temp_path.unlink(missing_ok=True)
        status = "CREATED"
    return {
        "sample_id": sample["sample_id"],
        "source_path": str(source.resolve()),
        "snapshot_path": str(destination.resolve()),
        "sha256": sha256_file(destination),
        "size_bytes": destination.stat().st_size,
        "status": status,
        "verified": sha256_file(destination) == sample["sha256"],
    }


def aspect_status(source_size: tuple[int, int], target_size: tuple[int, int]) -> tuple[str, float]:
    source_width, source_height = source_size
    target_width, target_height = target_size
    if source_width >= source_height:
        error_pixels = abs(target_height - source_height * target_width / source_width)
    else:
        error_pixels = abs(target_width - source_width * target_height / source_height)
    return ("PASS" if error_pixels <= 1.0 else "FAIL", error_pixels)


def candidate_failure_record(
    sample: dict[str, Any], method: str, stage: str, exc: Exception, source: Path, destination: Path
) -> dict[str, Any]:
    return {
        "success": False,
        "sample_id": str(sample.get("sample_id") or "UNKNOWN"),
        "method": method,
        "failure_stage": stage,
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "source_path": str(source.resolve()),
        "output_path": str(destination.resolve()),
    }


def _candidate_stage(
    stage: str,
    action: Callable[[], Any],
    sample: dict[str, Any],
    method: str,
    source: Path,
    destination: Path,
    fault_stage: str | None,
) -> Any:
    try:
        if fault_stage == stage:
            raise OSError(f"CONTROLLED_FAILURE:{stage}")
        return action()
    except CandidateExecutionError:
        raise
    except Exception as exc:
        raise CandidateExecutionError(candidate_failure_record(sample, method, stage, exc, source, destination)) from exc


def execute_candidate(
    sample: dict[str, Any], method: str, output_root: Path, *, fault_stage: str | None = None
) -> dict[str, Any]:
    source = Path(sample["source_path"])
    destination = output_root / "candidates" / method / f"{sample['sample_id']}__{method}.png"
    normalized_image, meta = _candidate_stage(
        "source_open",
        lambda: normalized_source_image(source),
        sample,
        method,
        source,
        destination,
        fault_stage,
    )

    def validate_source() -> tuple[tuple[int, int], str]:
        directness = source_directness_status(source, sample["source_role"])
        if directness != "PASS":
            raise BaselineError(f"SOURCE_DIRECTNESS_FAILED:{directness}")
        state = capture_file_state(source)
        for field in ("size_bytes", "mtime_ns", "sha256"):
            if state.get(field) != sample[field]:
                raise BaselineError(f"SOURCE_MANIFEST_MISMATCH:{field}")
        if normalized_image.size != (sample["width"], sample["height"]):
            raise BaselineError("SOURCE_DIMENSION_MISMATCH")
        if meta["source_format"] != sample["format"] or normalized_image.mode != sample["mode"]:
            raise BaselineError("SOURCE_FORMAT_OR_MODE_MISMATCH")
        if ("A" in normalized_image.getbands()) != sample["has_alpha"]:
            raise BaselineError("SOURCE_ALPHA_MISMATCH")
        decision, target_size = target_dimensions(sample["width"], sample["height"])
        if decision != "PROCESS" or target_size is None:
            raise BaselineError(f"SAMPLE_NOT_ELIGIBLE:{decision}")
        return target_size, directness

    target, directness = _candidate_stage(
        "source_validation",
        validate_source,
        sample,
        method,
        source,
        destination,
        fault_stage,
    )
    started = time.perf_counter_ns()
    resized = _candidate_stage(
        "resize",
        lambda: resize_image(normalized_image, target, method),
        sample,
        method,
        source,
        destination,
        fault_stage,
    )

    def encode_save() -> str:
        temp_path = save_png_temp(resized, destination, meta["icc_profile"])
        return commit_candidate(temp_path, destination)

    write_status = _candidate_stage(
        "encode_save", encode_save, sample, method, source, destination, fault_stage
    )
    duration_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    decoded = _candidate_stage(
        "decode_validation",
        lambda: verify_decode(destination),
        sample,
        method,
        source,
        destination,
        fault_stage,
    )
    ratio_status, ratio_error = aspect_status((sample["width"], sample["height"]), target)
    alpha_status = "PASS"
    if sample["has_alpha"]:
        if not decoded["has_alpha"] or not decoded["alpha_extrema"] or decoded["alpha_extrema"][0] >= 255:
            alpha_status = "FAIL"
    elif decoded["has_alpha"]:
        alpha_status = "FAIL"
    dimension_status = "PASS" if (decoded["width"], decoded["height"]) == target else "FAIL"
    output_metadata = _candidate_stage(
        "metadata_hash",
        lambda: {
            "output_sha256": sha256_file(destination),
            "output_pixel_sha256": pixel_sha256(destination),
            "output_size_bytes": destination.stat().st_size,
        },
        sample,
        method,
        source,
        destination,
        fault_stage,
    )
    return {
        "sample_id": sample["sample_id"],
        "method": method,
        "method_label": METHOD_LABELS[method],
        "success": all(value == "PASS" for value in (decoded["decode_status"], dimension_status, ratio_status, alpha_status)),
        "failure_stage": None,
        "error_type": None,
        "error_message": None,
        "source_path": str(source.resolve()),
        "source_sha256": sample["sha256"],
        "source_width": sample["width"],
        "source_height": sample["height"],
        "target_width": target[0],
        "target_height": target[1],
        "output_path": str(destination.resolve()),
        **output_metadata,
        "duration_ms": round(duration_ms, 3),
        "format": decoded["format"],
        "mode": decoded["mode"],
        "has_alpha": decoded["has_alpha"],
        "alpha_extrema": decoded["alpha_extrema"],
        "alpha_status": alpha_status,
        "decode_status": decoded["decode_status"],
        "dimension_status": dimension_status,
        "aspect_ratio_status": ratio_status,
        "aspect_ratio_error_pixels": round(ratio_error, 6),
        "crop_status": "ABSENT",
        "stretch_status": "ABSENT",
        "padding_status": "ABSENT",
        "source_directness_status": directness,
        "write_status": write_status,
    }


def round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def centered_box(width: int, height: int, center: list[float], size: int) -> tuple[int, int, int, int]:
    crop_width = min(size, width)
    crop_height = min(size, height)
    cx = round_half_up(width * float(center[0]))
    cy = round_half_up(height * float(center[1]))
    left = min(max(0, cx - crop_width // 2), max(0, width - crop_width))
    top = min(max(0, cy - crop_height // 2), max(0, height - crop_height))
    return left, top, left + crop_width, top + crop_height


def normalize_box(box: tuple[int, int, int, int], width: int, height: int) -> dict[str, float]:
    x0, y0, x1, y1 = box
    return {"x0": x0 / width, "y0": y0 / height, "x1": x1 / width, "y1": y1 / height}


def map_normalized_box(normalized_box: dict[str, float], width: int, height: int) -> tuple[int, int, int, int]:
    x0 = min(max(0, round_half_up(normalized_box["x0"] * width)), width - 1)
    y0 = min(max(0, round_half_up(normalized_box["y0"] * height)), height - 1)
    x1 = min(max(x0 + 1, round_half_up(normalized_box["x1"] * width)), width)
    y1 = min(max(y0 + 1, round_half_up(normalized_box["y1"] * height)), height)
    return x0, y0, x1, y1


def reverse_mapping_errors(
    source_box: tuple[int, int, int, int],
    candidate_box: tuple[int, int, int, int],
    source_size: tuple[int, int],
    candidate_size: tuple[int, int],
) -> dict[str, float]:
    source_width, source_height = source_size
    candidate_width, candidate_height = candidate_size
    source_edges = dict(zip(("x0", "y0", "x1", "y1"), source_box))
    candidate_edges = dict(zip(("x0", "y0", "x1", "y1"), candidate_box))
    errors = {
        "x0": abs(candidate_edges["x0"] * source_width / candidate_width - source_edges["x0"]),
        "y0": abs(candidate_edges["y0"] * source_height / candidate_height - source_edges["y0"]),
        "x1": abs(candidate_edges["x1"] * source_width / candidate_width - source_edges["x1"]),
        "y1": abs(candidate_edges["y1"] * source_height / candidate_height - source_edges["y1"]),
    }
    rounded = {edge: round(value, 6) for edge, value in errors.items()}
    rounded["maximum"] = round(max(errors.values()), 6)
    return rounded


def box_record(box: tuple[int, int, int, int]) -> dict[str, int]:
    return dict(zip(("x0", "y0", "x1", "y1"), box))


def comparison_display(image: Image.Image, size: tuple[int, int] = (512, 512)) -> Image.Image:
    if image.size == size:
        return image.copy()
    return resize_pillow(image, size, Image.Resampling.LANCZOS)


def replace_comparison(image: Image.Image, destination: Path) -> None:
    comparisons_root = (ARTIFACT_ROOT / "comparisons").resolve()
    if not is_relative_to(destination.resolve(), comparisons_root):
        raise BaselineError(f"COMPARISON_OUTPUT_OUTSIDE_ALLOWED_ROOT:{destination}")
    temp_path = save_png_temp(image, destination, None)
    os.replace(temp_path, destination)


def create_comparisons(
    manifest: dict[str, Any], candidate_rows: list[dict[str, Any]], output_root: Path
) -> list[dict[str, Any]]:
    candidate_map = {(row["sample_id"], row["method"]): Path(row["output_path"]) for row in candidate_rows}
    candidate_hashes = {(row["sample_id"], row["method"]): row["output_sha256"] for row in candidate_rows}
    rows: list[dict[str, Any]] = []
    for sample in manifest["samples"]:
        _, normalized = verify_manifest_sample(sample)
        source_image = normalized["image"]
        source_crop_size = min(512, source_image.width, source_image.height)
        for index, region in enumerate(sample["risk_regions"], start=1):
            source_box = centered_box(source_image.width, source_image.height, region["center"], source_crop_size)
            normalized_box = normalize_box(source_box, source_image.width, source_image.height)
            semantic_crops = [comparison_display(source_image.crop(source_box))]
            source_names = ["original"]
            candidate_boxes: dict[str, dict[str, int]] = {}
            native_records: dict[str, dict[str, Any]] = {}
            mapping_errors: dict[str, dict[str, float]] = {}
            for method in METHODS:
                candidate_path = candidate_map[(sample["sample_id"], method)]
                if sha256_file(candidate_path) != candidate_hashes[(sample["sample_id"], method)]:
                    raise BaselineError(f"PROTECTED_CANDIDATE_SHA256_MISMATCH:{sample['sample_id']}:{method}")
                with Image.open(candidate_path) as opened:
                    opened.load()
                    candidate = opened.copy()
                mapped_box = map_normalized_box(normalized_box, candidate.width, candidate.height)
                errors = reverse_mapping_errors(
                    source_box,
                    mapped_box,
                    source_image.size,
                    candidate.size,
                )
                if errors["maximum"] > 1.0:
                    raise BaselineError(
                        f"ROI_REVERSE_MAPPING_ERROR:{sample['sample_id']}:{method}:{errors['maximum']}"
                    )
                semantic_crops.append(comparison_display(candidate.crop(mapped_box)))
                source_names.append(method)
                candidate_boxes[method] = box_record(mapped_box)
                mapping_errors[method] = errors

                native_box = centered_box(candidate.width, candidate.height, region["center"], 512)
                native_crop = candidate.crop(native_box)
                native_destination = (
                    output_root
                    / "comparisons"
                    / "native_100_percent"
                    / f"{sample['sample_id']}__R{index:02d}__{method}.png"
                )
                replace_comparison(native_crop, native_destination)
                native_records[method] = {
                    "pixel_box": box_record(native_box),
                    "path": str(native_destination.resolve()),
                    "sha256": sha256_file(native_destination),
                    "width": native_crop.width,
                    "height": native_crop.height,
                    "scale": "100_PERCENT_NATIVE_PIXELS",
                }

            mode = "RGBA" if any("A" in crop.getbands() for crop in semantic_crops) else "RGB"
            contact = Image.new(mode, (512 * len(semantic_crops), 512))
            for panel_index, crop in enumerate(semantic_crops):
                contact.paste(crop.convert(mode), (panel_index * 512, 0))
            file_name = f"{sample['sample_id']}__R{index:02d}__{region['risk']}.png"
            destination = output_root / "comparisons" / file_name
            replace_comparison(contact, destination)
            rows.append(
                {
                    "sample_id": sample["sample_id"],
                    "risk": region["risk"],
                    "semantic_view_type": "MATCHED_NORMALIZED_SOURCE_REGION",
                    "panel_order": source_names,
                    "display_size_per_panel": [512, 512],
                    "display_resample": "Pillow LANCZOS presentation only",
                    "source_pixel_box": box_record(source_box),
                    "normalized_box": normalized_box,
                    "candidate_pixel_boxes": candidate_boxes,
                    "reverse_mapping_error_source_pixels": mapping_errors,
                    "maximum_reverse_mapping_error_source_pixels": max(
                        item["maximum"] for item in mapping_errors.values()
                    ),
                    "semantic_comparison_path": str(destination.resolve()),
                    "semantic_comparison_sha256": sha256_file(destination),
                    "candidate_native_100_percent": native_records,
                    "mapping_status": "PASS",
                }
            )
    atomic_write_json(
        output_root / "comparisons" / "comparison_manifest.json",
        {
            "version": "4K_STAGE_1_ROI_COMPARISON_V2",
            "comparison_count": len(rows),
            "semantic_range_policy": "SAME_NORMALIZED_BOX_FOR_SOURCE_AND_ALL_CANDIDATES",
            "native_candidate_policy": "THREE_SEPARATE_100_PERCENT_PIXEL_CROPS_PER_RISK_REGION",
            "maximum_allowed_reverse_mapping_error_source_pixels": 1.0,
            "comparisons": rows,
        },
    )
    return rows


def determinism_worker(request_path: Path) -> dict[str, Any]:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    source = Path(request["source_path"])
    output_path = Path(request["output_path"])
    actual_source_sha256 = sha256_file(source)
    if actual_source_sha256 != request["expected_source_sha256"]:
        raise BaselineError(
            f"DETERMINISM_SOURCE_SHA256_MISMATCH:{request['sample_id']}:{actual_source_sha256}"
        )
    image, meta = normalized_source_image(source)
    if image.size != tuple(request["source_size"]):
        raise BaselineError(f"DETERMINISM_SOURCE_SIZE_MISMATCH:{request['sample_id']}:{image.size}")
    decision, target = target_dimensions(image.width, image.height)
    if decision != "PROCESS" or target is None:
        raise BaselineError(f"DETERMINISM_SAMPLE_NOT_ELIGIBLE:{request['sample_id']}:{decision}")
    resized = resize_image(image, target, request["method"])
    temp_path = save_png_temp(resized, output_path, meta["icc_profile"])
    os.replace(temp_path, output_path)
    decoded = verify_decode(output_path)
    result = {
        "run_id": request["run_id"],
        "sample_id": request["sample_id"],
        "method": request["method"],
        "process_id": os.getpid(),
        "source_path": str(source.resolve()),
        "source_sha256": actual_source_sha256,
        "target_size": [decoded["width"], decoded["height"]],
        "mode": decoded["mode"],
        "format": decoded["format"],
        "encoding_parameters": {
            "format": "PNG",
            "compress_level": 6,
            "optimize": False,
            "icc_profile_preserved": bool(meta["icc_profile"]),
        },
        "output_path": str(output_path.resolve()),
        "output_sha256": sha256_file(output_path),
        "output_pixel_sha256": pixel_sha256(output_path),
        "output_size_bytes": output_path.stat().st_size,
        "worker_argv": sys.argv,
    }
    atomic_write_json(Path(request["run_result_path"]), result)
    return result


def run_independent_determinism(
    manifest: dict[str, Any], method: str, output_root: Path, sample_ids: tuple[str, str] = ("S01", "S03")
) -> dict[str, Any]:
    samples = {sample["sample_id"]: sample for sample in manifest["samples"]}
    batch_id = f"batch_{time.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    batch_root = output_root / "results" / "determinism_independent" / batch_id
    records: list[dict[str, Any]] = []
    for sample_id in sample_ids:
        sample = samples[sample_id]
        sample_runs: list[dict[str, Any]] = []
        for run_number in (1, 2):
            run_id = f"{sample_id}_{method}_run{run_number}_{uuid.uuid4().hex[:8]}"
            run_dir = batch_root / sample_id / run_id
            run_dir.mkdir(parents=True, exist_ok=False)
            request_path = run_dir / "worker_request.json"
            result_path = run_dir / "worker_result.json"
            output_path = run_dir / f"{sample_id}__{method}.png"
            request = {
                "run_id": run_id,
                "sample_id": sample_id,
                "method": method,
                "source_path": sample["source_path"],
                "expected_source_sha256": sample["sha256"],
                "source_size": [sample["width"], sample["height"]],
                "output_path": str(output_path.resolve()),
                "run_result_path": str(result_path.resolve()),
            }
            atomic_write_json(request_path, request)
            command = [sys.executable, str(Path(__file__).resolve()), "--determinism-worker", str(request_path.resolve())]
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if completed.returncode != 0:
                raise BaselineError(
                    f"DETERMINISM_WORKER_FAILED:{sample_id}:{run_id}:{completed.returncode}:"
                    f"{completed.stdout.strip()}:{completed.stderr.strip()}"
                )
            worker_result = json.loads(completed.stdout.strip().splitlines()[-1])
            persisted = json.loads(result_path.read_text(encoding="utf-8"))
            if worker_result != persisted:
                raise BaselineError(f"DETERMINISM_WORKER_RESULT_MISMATCH:{sample_id}:{run_id}")
            worker_result["exit_code"] = completed.returncode
            worker_result["command"] = command
            worker_result["isolated_output_directory"] = str(run_dir.resolve())
            sample_runs.append(worker_result)
        comparable_fields = (
            "source_sha256",
            "target_size",
            "mode",
            "format",
            "encoding_parameters",
            "output_sha256",
            "output_pixel_sha256",
            "output_size_bytes",
        )
        comparisons = {field: sample_runs[0][field] == sample_runs[1][field] for field in comparable_fields}
        distinct_processes = sample_runs[0]["process_id"] != sample_runs[1]["process_id"]
        distinct_directories = (
            sample_runs[0]["isolated_output_directory"] != sample_runs[1]["isolated_output_directory"]
        )
        records.append(
            {
                "sample_id": sample_id,
                "method": method,
                "runs": sample_runs,
                "comparisons": comparisons,
                "distinct_processes": distinct_processes,
                "distinct_output_directories": distinct_directories,
                "status": "PASS"
                if all(comparisons.values()) and distinct_processes and distinct_directories
                else "FAIL",
            }
        )
    result = {
        "version": "4K_STAGE_1_INDEPENDENT_DETERMINISM_V2",
        "supersedes": "in_process_determinism field in 4k_stage1_run_results.json",
        "batch_id": batch_id,
        "method": method,
        "sample_ids": list(sample_ids),
        "process_policy": "TWO_SEPARATE_PYTHON_INTERPRETER_PROCESSES_PER_SAMPLE",
        "records": records,
        "status": "PASS" if all(record["status"] == "PASS" for record in records) else "FAIL",
    }
    atomic_write_json(output_root / "results" / "determinism_independent.json", result)
    return result


def summarize_methods(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    categories = {"chinese": {"S01", "S02"}, "portrait": {"S03", "S04"}, "product": {"S05", "S06"}, "alpha": {"S08"}}
    for method in METHODS:
        selected = [row for row in rows if row["method"] == method]
        durations = [row["duration_ms"] for row in selected]
        sizes = [row["output_size_bytes"] for row in selected]
        summary: dict[str, Any] = {
            "method": method,
            "method_label": METHOD_LABELS[method],
            "success_count": sum(1 for row in selected if row["success"]),
            "failure_count": sum(1 for row in selected if not row["success"]),
            "average_duration_ms": round(statistics.fmean(durations), 3),
            "median_duration_ms": round(statistics.median(durations), 3),
            "slowest_duration_ms": round(max(durations), 3),
            "average_output_size_bytes": round(statistics.fmean(sizes)),
        }
        for category, sample_ids in categories.items():
            summary[f"{category}_samples_status"] = "PASS" if all(row["success"] for row in selected if row["sample_id"] in sample_ids) else "FAIL"
        summaries.append(summary)
    return summaries


def protected_state_equal(before: dict[str, Any], after: dict[str, Any]) -> dict[str, bool]:
    return {
        "settings_unchanged": before["settings"] == after["settings"],
        "formal_4k_directory_unchanged": before["formal_4k_directory"] == after["formal_4k_directory"],
        "project_runtime_directories_unchanged": before["project_runtime_directories"] == after["project_runtime_directories"],
    }


def existing_candidate_rows(output_root: Path) -> list[dict[str, Any]]:
    results_path = output_root / "results" / "4k_stage1_run_results.json"
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    rows = payload.get("candidates")
    if not isinstance(rows, list) or len(rows) != 24:
        raise BaselineError("EXISTING_CANDIDATE_RESULT_COUNT_MUST_BE_24")
    for row in rows:
        path = Path(row["output_path"])
        if not path.is_file() or sha256_file(path) != row["output_sha256"]:
            raise BaselineError(f"PROTECTED_CANDIDATE_SHA256_MISMATCH:{row['sample_id']}:{row['method']}")
    return rows


def build_probe_sample(source: Path, sample_id: str) -> dict[str, Any]:
    image, meta = normalized_source_image(source)
    stat = source.stat()
    return {
        "sample_id": sample_id,
        "source_path": str(source.resolve()),
        "source_role": "CONTROLLED_TEST_ORIGINAL_INPUT",
        "width": image.width,
        "height": image.height,
        "format": meta["source_format"],
        "mode": image.mode,
        "has_alpha": "A" in image.getbands(),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(source),
    }


def run_failure_probe(
    source: Path,
    output_root: Path,
    failure_record_path: Path,
    sample_id: str,
    method: str,
    failure_stage: str,
) -> int:
    sample = build_probe_sample(source, sample_id)
    try:
        success = execute_candidate(sample, method, output_root, fault_stage=failure_stage)
    except CandidateExecutionError as exc:
        atomic_write_json(failure_record_path, exc.record)
        print(json.dumps({"status": "FAIL", **exc.record}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "UNEXPECTED_SUCCESS", "candidate": success}, ensure_ascii=False))
    return 1


def run(manifest_path: Path, standard_path: Path, output_root: Path, determinism_method: str) -> dict[str, Any]:
    output_root = validate_output_root(output_root)
    standard = json.loads(standard_path.read_text(encoding="utf-8"))
    if standard.get("standard_version") != "V1" or standard.get("target_long_edge") != 3840:
        raise BaselineError("4K_STANDARD_INVALID")
    if determinism_method not in METHODS:
        raise BaselineError(f"DETERMINISM_METHOD_INVALID:{determinism_method}")
    manifest = read_manifest(manifest_path)
    protected_before = capture_protected_state()
    source_before = {sample["sample_id"]: capture_file_state(Path(sample["source_path"])) for sample in manifest["samples"]}
    snapshots: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for sample in manifest["samples"]:
        source, _ = verify_manifest_sample(sample)
        snapshots.append(snapshot_source(sample, source, output_root))
        for method in METHODS:
            candidates.append(execute_candidate(sample, method, output_root))
    comparisons = create_comparisons(manifest, candidates, output_root)
    determinism = run_independent_determinism(manifest, determinism_method, output_root)
    source_after = {sample["sample_id"]: capture_file_state(Path(sample["source_path"])) for sample in manifest["samples"]}
    protected_after = capture_protected_state()
    protection = protected_state_equal(protected_before, protected_after)
    result = {
        "stage": "4K_STAGE_1_TRADITIONAL_BASELINE",
        "standard": standard,
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "snapshot_count": len(snapshots),
        "snapshots": snapshots,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "method_summaries": summarize_methods(candidates),
        "comparison_count": len(comparisons),
        "comparisons": comparisons,
        "determinism": determinism,
        "source_states_before": source_before,
        "source_states_after": source_after,
        "source_files_unchanged": source_before == source_after,
        "protected_state_before": protected_before,
        "protected_state_after": protected_after,
        "protected_state_checks": protection,
        "all_candidate_checks_pass": all(row["success"] for row in candidates),
    }
    atomic_write_json(output_root / "results" / "4k_stage1_run_results.json", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline Stage 1 traditional 4K baseline; never touches formal product outputs.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--standard", type=Path, default=DEFAULT_STANDARD)
    parser.add_argument("--output-root", type=Path, default=ARTIFACT_ROOT)
    parser.add_argument("--determinism-method", choices=METHODS, default="pillow_lanczos")
    parser.add_argument("--rebuild-comparisons-only", action="store_true")
    parser.add_argument("--determinism-only", action="store_true")
    parser.add_argument("--determinism-worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--failure-probe-source", type=Path)
    parser.add_argument("--failure-probe-output-root", type=Path)
    parser.add_argument("--failure-probe-record", type=Path)
    parser.add_argument("--failure-probe-sample-id", default="FAULT_PROBE")
    parser.add_argument("--failure-probe-method", choices=METHODS, default="pillow_lanczos")
    parser.add_argument(
        "--failure-probe-stage",
        choices=("source_open", "source_validation", "resize", "encode_save", "decode_validation", "metadata_hash"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.determinism_worker:
            worker_result = determinism_worker(args.determinism_worker)
            print(json.dumps(worker_result, ensure_ascii=False))
            return 0
        if args.failure_probe_stage:
            required = (args.failure_probe_source, args.failure_probe_output_root, args.failure_probe_record)
            if any(value is None for value in required):
                raise BaselineError("FAILURE_PROBE_REQUIRES_SOURCE_OUTPUT_ROOT_AND_RECORD")
            return run_failure_probe(
                args.failure_probe_source,
                args.failure_probe_output_root,
                args.failure_probe_record,
                args.failure_probe_sample_id,
                args.failure_probe_method,
                args.failure_probe_stage,
            )
        if args.rebuild_comparisons_only:
            output_root = validate_output_root(args.output_root)
            manifest = read_manifest(args.manifest)
            rows = create_comparisons(manifest, existing_candidate_rows(output_root), output_root)
            print(json.dumps({"status": "PASS", "comparison_count": len(rows)}, ensure_ascii=False))
            return 0
        if args.determinism_only:
            output_root = validate_output_root(args.output_root)
            manifest = read_manifest(args.manifest)
            result = run_independent_determinism(manifest, args.determinism_method, output_root)
            print(json.dumps({"status": result["status"], "batch_id": result["batch_id"]}, ensure_ascii=False))
            return 0 if result["status"] == "PASS" else 1
        result = run(args.manifest, args.standard, args.output_root, args.determinism_method)
    except CandidateExecutionError as exc:
        print(json.dumps({"status": "FAIL", **exc.record}, ensure_ascii=False))
        return 1
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error_type": type(exc).__name__, "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "status": "PASS" if result["all_candidate_checks_pass"] else "FAIL",
                "candidate_count": result["candidate_count"],
                "comparison_count": result["comparison_count"],
                "source_files_unchanged": result["source_files_unchanged"],
                "protected_state_checks": result["protected_state_checks"],
                "determinism": result["determinism"]["status"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["all_candidate_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
