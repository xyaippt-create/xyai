"""Minimum real-run validation for the internal HDDE safe HD base.

This runner writes only beneath artifacts/hdde_hd_core_safe_base_20260813.  It
does not touch Settings, the formal delivery tree, or any product integration.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.hd_core.safe_base import (
    assess_baseline_risk,
    finalize_with_baseline_fallback,
    process_hd_core_safe_base,
)


ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "hdde_hd_core_safe_base_20260813"
SETTINGS_PATH = PROJECT_ROOT / "settings" / "settings.json"
FORMAL_ROOT = Path(r"D:\影界文件")
FORMAL_4K_DIRECTORY = FORMAL_ROOT / "输出" / "4K高清增强"
CROP_ROOT = (
    PROJECT_ROOT
    / "artifacts"
    / "4k_controlled_perceptual_poc_round1_20260813"
    / "batch_20260813T084132_controlled_realesrgan_x2_crop_stage_a"
    / "results"
    / "ORIGINAL"
)
REAL_ROOT = PROJECT_ROOT / "artifacts" / "4k_stage1_baseline" / "golden_samples"

SAMPLES = (
    ("crop_chinese", CROP_ROOT / "S02_chinese.png", "中文/规则结构"),
    ("crop_face", CROP_ROOT / "S03_face.png", "人物五官/头发"),
    ("crop_material", CROP_ROOT / "S06_material.png", "产品材质"),
    ("real_portrait", REAL_ROOT / "S03__andy_lau_commercial_portrait.png", "真实商务人物"),
    ("real_logo_graphic", REAL_ROOT / "S05__dji_horizontal_infographic.png", "中文/Logo/图形"),
    ("real_alpha", REAL_ROOT / "S08__smoke_transparent_png_legacy.png", "半透明Alpha"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def tree_state(path: Path, *, content_hash: bool) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "file_count": 0, "fingerprint": ""}
    digest = hashlib.sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file())
    total_bytes = 0
    for item in files:
        stat = item.stat()
        total_bytes += stat.st_size
        relative = item.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        if content_hash:
            digest.update(sha256_file(item).encode("ascii"))
    return {
        "exists": True,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "fingerprint": digest.hexdigest(),
        "content_hash_included": content_hash,
    }


def protection_state() -> dict[str, Any]:
    return {
        "settings": file_state(SETTINGS_PATH),
        "formal_root_metadata": tree_state(FORMAL_ROOT, content_hash=False),
        "formal_4k_content": tree_state(FORMAL_4K_DIRECTORY, content_hash=True),
    }


def decode_state(path: Path) -> dict[str, Any]:
    with Image.open(path) as opened:
        opened.load()
        return {
            "format": str(opened.format or "UNKNOWN").upper(),
            "mode": opened.mode,
            "size": list(opened.size),
        }


def save_alpha_composites(path: Path, destination: Path) -> list[str]:
    with Image.open(path) as opened:
        opened.load()
        rgba = opened.convert("RGBA")
    alpha = rgba.getchannel("A")
    outputs: list[str] = []
    for name, color in (("black", (0, 0, 0, 255)), ("white", (255, 255, 255, 255))):
        background = Image.new("RGBA", rgba.size, color)
        composite = Image.composite(rgba, background, alpha).convert("RGB")
        output = destination / f"alpha_on_{name}.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        composite.save(output, format="PNG", compress_level=6)
        outputs.append(str(output.resolve()))
    return outputs


def run_fallback_probe(root: Path) -> dict[str, Any]:
    probe = root / "fallback_probe"
    probe.mkdir(parents=True, exist_ok=False)
    source = probe / "source.png"
    baseline = probe / "baseline.png"
    candidate = probe / "candidate_with_new_edge.png"
    final = probe / "final.png"
    Image.new("RGB", (32, 24), (92, 96, 104)).save(source)
    baseline_array = np.full((48, 64, 3), (92, 96, 104), dtype=np.uint8)
    Image.fromarray(baseline_array, "RGB").save(baseline)
    changed = baseline_array.copy()
    changed[20:28, 31:33] = 245
    Image.fromarray(changed, "RGB").save(candidate)
    risk = assess_baseline_risk(source, baseline, candidate)
    selection = finalize_with_baseline_fallback(baseline, candidate, final, risk)
    with Image.open(baseline) as base_image, Image.open(final) as final_image:
        exact = bool(np.array_equal(np.asarray(base_image), np.asarray(final_image)))
    return {
        "status": "PASS"
        if risk["status"] == "FAIL" and selection["fallback_applied"] and exact
        else "FAIL",
        "risk": risk,
        "fallback": selection,
        "final_matches_baseline_pixels": exact,
    }


def run() -> Path:
    missing = [str(path) for _, path, _ in SAMPLES if not path.is_file()]
    if missing:
        raise RuntimeError(f"缺少代表样本：{missing}")
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    batch = ARTIFACT_ROOT / f"batch_{timestamp}"
    batch.mkdir(exist_ok=False)
    protection_before = protection_state()
    sample_hashes_before = {name: sha256_file(path) for name, path, _ in SAMPLES}
    results: list[dict[str, Any]] = []
    for name, source, coverage in SAMPLES:
        workspace = batch / "samples" / name
        result = process_hd_core_safe_base(source, workspace)
        final = Path(result["final_output_path"])
        baseline = Path(result["baseline_output_path"])
        decode = decode_state(final)
        expected_size = [result["diagnosis"]["target_width"], result["diagnosis"]["target_height"]]
        alpha = result["final_risk"]["alpha"]
        gates = {
            "decode": final.is_file(),
            "format_png": decode["format"] == "PNG",
            "dimensions": decode["size"] == expected_size,
            "source_unchanged": result["source_hash_unchanged"],
            "baseline_pixels_preserved": result["baseline_output_pixel_sha256"]
            == result["final_output_pixel_sha256"],
            "risk_pass": result["risk"]["status"] == "PASS" and result["final_risk"]["status"] == "PASS",
            "no_new_rgb_frequency_or_edges": result["final_risk"]["maximum_rgb_delta"] == 0
            and not result["final_risk"]["new_halo_possible"]
            and not result["final_risk"]["new_double_edge_possible"],
            "alpha": alpha["status"] in {"PASS", "NOT_APPLICABLE"},
        }
        entry: dict[str, Any] = {
            "sample": name,
            "coverage": coverage,
            "source": str(source.resolve()),
            "source_sha256": result["source_sha256"],
            "baseline": str(baseline.resolve()),
            "final": str(final.resolve()),
            "decode": decode,
            "elapsed_seconds": result["elapsed_seconds"],
            "gates": gates,
            "alpha_audit": alpha,
            "fallback": result["fallback"],
            "diagnosis": result["diagnosis"],
            "status": "PASS" if all(gates.values()) else "FAIL",
        }
        if name == "real_alpha":
            entry["alpha_composites"] = save_alpha_composites(final, workspace / "visual_checks")
        results.append(entry)

    fallback_probe = run_fallback_probe(batch)
    sample_hashes_after = {name: sha256_file(path) for name, path, _ in SAMPLES}
    protection_after = protection_state()
    protection = {
        "settings_unchanged": protection_before["settings"] == protection_after["settings"],
        "formal_root_unchanged": protection_before["formal_root_metadata"]
        == protection_after["formal_root_metadata"],
        "formal_4k_unchanged": protection_before["formal_4k_content"]
        == protection_after["formal_4k_content"],
        "sources_unchanged": sample_hashes_before == sample_hashes_after,
        "before": protection_before,
        "after": protection_after,
    }
    all_pass = (
        all(result["status"] == "PASS" for result in results)
        and fallback_probe["status"] == "PASS"
        and all(protection[key] for key in ("settings_unchanged", "formal_root_unchanged", "formal_4k_unchanged", "sources_unchanged"))
    )
    manifest = {
        "status": "PASS" if all_pass else "FAIL",
        "hd_core_safe_base": "PROVEN" if all_pass else "NOT_PROVEN",
        "scope": "INTERNAL_SAFE_BASE_ONLY_NOT_HD_CORE_V1",
        "pipeline": [
            "INPUT",
            "MEASUREMENTS_ONLY_DEGRADATION_DIAGNOSIS",
            "EXISTING_4K_SAFE_RECONSTRUCTION",
            "SOURCE_ALPHA_CHANNEL_BYPASS",
            "STRICT_BASELINE_PIXEL_RISK_GATE",
            "BASELINE_FALLBACK",
            "LOSSLESS_PNG_DELIVERY_ENCODING",
        ],
        "baseline_executor": "engine.image_processing_routing.four_k_v1.process_4k_v1_image",
        "baseline_route": "PILLOW_LANCZOS_SAFE_RESIZE",
        "srmd_enabled": False,
        "new_model_enabled": False,
        "semantic_detection_enabled": False,
        "device_scope": "CPU/Pillow path on current Intel machine; elapsed time is observed runtime, not a formal benchmark.",
        "samples": results,
        "fallback_probe": fallback_probe,
        "protection": protection,
    }
    manifest_path = batch / "validation.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


if __name__ == "__main__":
    print(run())
