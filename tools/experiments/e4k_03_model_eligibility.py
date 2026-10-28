"""Build the source/license-first eligibility evidence for E4K-03.

This command intentionally performs no download and no model inference.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
import torch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.hd_core.model_eligibility import (
    AUTHORIZED_DOWNLOAD,
    BLOCKED,
    PASS,
    ModelEligibilityRecord,
    evaluate_pre_download,
    finalize_eligibility,
)


DEFAULT_OUTPUT_ROOT = REPO_ROOT / "artifacts" / "e4k_03_model_eligibility"


def initial_candidates() -> list[ModelEligibilityRecord]:
    common_input = {
        "color": "RGB_FLOAT32_0_TO_1",
        "alpha": "SOURCE_ALPHA_BYPASS_AND_REATTACH_REQUIRED",
        "source_binding": "SAME_E1_01_SOURCE",
    }
    return [
        ModelEligibilityRecord(
            model_id="RealESRGAN_x4plus",
            model_version="official_release_v0.1.0",
            model_role="PRIMARY_REAL_WORLD_X4_SUPER_RESOLUTION",
            source_url_or_provider="https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.1.0",
            source_status="PASS",
            source_evidence="Official author repository and release asset",
            code_license_reference="https://github.com/xinntao/Real-ESRGAN/blob/master/LICENSE",
            code_license_status="PASS",
            weight_license_reference="https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.1.0",
            weight_license_status="UNKNOWN",
            commercial_use_boundary="UNCLEAR",
            redistribution_boundary="UNCLEAR",
            model_file="RealESRGAN_x4plus.pth",
            runtime_requirement="PyTorch/BasicSR or official NCNN Vulkan runtime",
            hardware_requirement="CPU, CUDA GPU, or Vulkan-capable GPU depending on backend",
            memory_requirement="TILE_DEPENDENT_NOT_PROVEN_ON_CURRENT_MACHINE",
            backend="UNSELECTED",
            precision="UNSELECTED",
            input_contract=common_input,
            output_contract={"scale": 4, "color": "RGB", "format": "LOSSLESS_PNG"},
            determinism_status="NOT_TESTED",
            onnx_feasibility="COMMUNITY_PATH_EXISTS_NOT_OFFICIAL_PRODUCTION_PROOF",
            openvino_feasibility="NOT_PROVEN",
            expected_processing_cost="UNKNOWN_UNTIL_SMOKE",
        ),
        ModelEligibilityRecord(
            model_id="SwinIR_realSR_x4_GAN",
            model_version="official_release_v0.0",
            model_role="PRIMARY_REAL_WORLD_X4_SUPER_RESOLUTION",
            source_url_or_provider="https://github.com/JingyunLiang/SwinIR/releases/tag/v0.0",
            source_status="PASS",
            source_evidence="Official author repository release with pretrained model assets",
            code_license_reference="https://github.com/JingyunLiang/SwinIR/blob/main/LICENSE",
            code_license_status="PASS",
            weight_license_reference="https://github.com/JingyunLiang/SwinIR/releases/tag/v0.0",
            weight_license_status="UNKNOWN",
            commercial_use_boundary="UNCLEAR",
            redistribution_boundary="UNCLEAR",
            model_file="003_realSR_BSRGAN_DFO_s64w8_SwinIR-M_x4_GAN.pth",
            runtime_requirement="PyTorch FP32 with tiled inference for large inputs",
            hardware_requirement="CPU or CUDA GPU; current machine has CPU-only PyTorch",
            memory_requirement="TILE_DEPENDENT_NOT_PROVEN_ON_CURRENT_MACHINE",
            backend="PYTORCH_RESEARCH_RUNTIME",
            precision="FP32",
            input_contract=common_input,
            output_contract={"scale": 4, "color": "RGB", "format": "LOSSLESS_PNG"},
            determinism_status="NOT_TESTED",
            onnx_feasibility="NOT_PROVEN_FOR_SELECTED_WEIGHT",
            openvino_feasibility="NOT_PROVEN_FOR_SELECTED_WEIGHT",
            expected_processing_cost="HIGH_ON_CPU",
        ),
        ModelEligibilityRecord(
            model_id="caidas/swin2SR-realworld-sr-x4-64-bsrgan-psnr",
            model_version="huggingface_main_revision_to_be_frozen_on_download",
            model_role="PRIMARY_REAL_WORLD_X4_SUPER_RESOLUTION",
            source_url_or_provider="https://huggingface.co/caidas/swin2SR-realworld-sr-x4-64-bsrgan-psnr",
            source_status="PASS",
            source_evidence="Official CAIDAS model provider and author-linked model card",
            code_license_reference="https://github.com/mv-lab/swin2sr/blob/main/LICENSE",
            code_license_status="PASS",
            weight_license_reference="https://huggingface.co/caidas/swin2SR-realworld-sr-x4-64-bsrgan-psnr/blob/main/README.md",
            weight_license_status="PASS",
            commercial_use_boundary="PERMITTED_BY_APACHE_2_0_WITH_NOTICE_AND_LICENSE_CONDITIONS",
            redistribution_boundary="PERMITTED_BY_APACHE_2_0_WITH_NOTICE_AND_LICENSE_CONDITIONS",
            model_file="pytorch_model.bin",
            runtime_requirement="Transformers Swin2SR PyTorch FP32 tiled CPU inference",
            hardware_requirement="CPU supported; CUDA optional; current PyTorch is CPU-only",
            memory_requirement="32_GIB_SYSTEM_RAM_WITH_TILED_SMOKE_REQUIRED",
            backend="PYTORCH_RESEARCH_RUNTIME",
            precision="FP32",
            input_contract=common_input,
            output_contract={
                "native_scale": 4,
                "final_geometry": "EXPLICIT_LANCZOS_TO_SAME_LANCZOS_BASELINE_DIMENSIONS",
                "color": "RGB",
                "format": "LOSSLESS_PNG",
            },
            determinism_status="REQUIRES_REPEAT_SMOKE",
            onnx_feasibility="TRANSFORMERS_EXPORT_POSSIBLE_NOT_PROVEN_FOR_FULL_CANDIDATE",
            openvino_feasibility="REQUIRES_ONNX_OR_DIRECT_CONVERSION_NOT_PROVEN",
            expected_processing_cost="HIGH_ON_CPU_REQUIRES_TILE_AND_MEASUREMENT",
        ),
        ModelEligibilityRecord(
            model_id="SCUNet_color_real_psnr",
            model_version="official_KAIR_release_v1.0",
            model_role="SPECIALIST_BLIND_DENOISING_NOT_FULL_SUPER_RESOLUTION",
            source_url_or_provider="https://github.com/cszn/SCUNet",
            source_status="PASS",
            source_evidence="Official author repository; weights linked from separate KAIR release",
            code_license_reference="https://github.com/cszn/SCUNet/blob/main/LICENSE",
            code_license_status="PASS",
            weight_license_reference="https://github.com/cszn/KAIR/releases/tag/v1.0",
            weight_license_status="UNKNOWN",
            commercial_use_boundary="UNCLEAR",
            redistribution_boundary="UNCLEAR",
            model_file="scunet_color_real_psnr.pth",
            runtime_requirement="PyTorch FP32 same-resolution tiled denoising",
            hardware_requirement="CPU or CUDA GPU",
            memory_requirement="TILE_DEPENDENT_NOT_PROVEN_ON_CURRENT_MACHINE",
            backend="PYTORCH_RESEARCH_RUNTIME",
            precision="FP32",
            input_contract={
                **common_input,
                "role_boundary": "DENOISING_ONLY",
                "candidate_input": "LANCZOS_BASELINE_AT_TARGET_GEOMETRY",
            },
            output_contract={"scale": 1, "color": "RGB", "format": "LOSSLESS_PNG"},
            determinism_status="NOT_TESTED",
            onnx_feasibility="NOT_PROVEN_FOR_SELECTED_WEIGHT",
            openvino_feasibility="NOT_PROVEN_FOR_SELECTED_WEIGHT",
            expected_processing_cost="HIGH_ON_4K_CPU",
        ),
    ]


def runtime_snapshot(gpu_name: str, npu_name: str) -> dict[str, Any]:
    memory = psutil.virtual_memory()
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": sys.version,
        "python_executable": sys.executable,
        "cpu_logical_count": os.cpu_count(),
        "gpu": gpu_name,
        "npu": npu_name,
        "available_memory_bytes": memory.available,
        "total_memory_bytes": memory.total,
        "torch_version": torch.__version__,
        "torch_cuda_available": torch.cuda.is_available(),
        "torch_cuda_version": torch.version.cuda,
        "torch_device_count": torch.cuda.device_count(),
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def build(output_root: Path, *, gpu_name: str, npu_name: str) -> dict[str, Any]:
    root = output_root.expanduser().resolve()
    if root.exists():
        raise RuntimeError(f"OUTPUT_ROOT_ALREADY_EXISTS:{root}")
    root.mkdir(parents=True)
    records = [evaluate_pre_download(record) for record in initial_candidates()]
    for record in records:
        safe_name = (
            record["model_id"].replace("/", "__").replace(" ", "_").replace("+", "plus")
        )
        write_json(root / "records" / f"{safe_name}.json", record)
    snapshot = runtime_snapshot(gpu_name, npu_name)
    write_json(root / "runtime_snapshot.json", snapshot)
    eligible = [r for r in records if r["model_eligibility"] == AUTHORIZED_DOWNLOAD]
    blocked = [r for r in records if r["model_eligibility"] == BLOCKED]
    summary = {
        "artifact_version": "E4K_03_MODEL_ELIGIBILITY_ARTIFACT_V1",
        "status": "PASS",
        "task_id": "E4K-03_FIRST_REAL_ENHANCEMENT_CANDIDATE",
        "phase": "PRE_DOWNLOAD_ELIGIBILITY",
        "candidate_count": len(records),
        "eligible_for_authorized_download_count": len(eligible),
        "blocked_count": len(blocked),
        "eligible_model_ids": [r["model_id"] for r in eligible],
        "blocked_model_ids": [r["model_id"] for r in blocked],
        "models_downloaded": 0,
        "models_inference_run": 0,
        "models_benchmarked": 0,
        "topaz_status": "REFERENCE_ONLY_NOT_USED",
        "fidesr_status": "DROPPED_NOT_REOPENED",
        "runtime_snapshot": "runtime_snapshot.json",
        "records": [
            f"records/{r['model_id'].replace('/', '__').replace(' ', '_').replace('+', 'plus')}.json"
            for r in records
        ],
    }
    write_json(root / "summary.json", summary)
    return summary


def finalize_swin2sr(
    output_root: Path,
    *,
    model_path: Path,
    expected_sha256: str,
    revision: str,
) -> dict[str, Any]:
    """Freeze downloaded identity and prove local model loading before smoke."""

    root = output_root.expanduser().resolve()
    summary_path = root / "summary.json"
    if not summary_path.is_file():
        raise RuntimeError(f"PRE_DOWNLOAD_ARTIFACT_MISSING:{summary_path}")
    model = model_path.expanduser().resolve()
    if not model.is_file():
        raise RuntimeError(f"MODEL_FILE_MISSING:{model}")

    from transformers import (
        Swin2SRForImageSuperResolution,
        Swin2SRImageProcessor,
        __version__ as transformers_version,
    )

    process = psutil.Process(os.getpid())
    rss_before = process.memory_info().rss
    started = time.perf_counter()
    model_root = model.parent
    Swin2SRImageProcessor.from_pretrained(model_root, local_files_only=True)
    loaded = Swin2SRForImageSuperResolution.from_pretrained(
        model_root, local_files_only=True
    ).eval()
    model_load_time = time.perf_counter() - started
    rss_after = process.memory_info().rss
    parameter = next(loaded.parameters())
    del loaded

    base = next(
        item
        for item in initial_candidates()
        if item.model_id
        == "caidas/swin2SR-realworld-sr-x4-64-bsrgan-psnr"
    )
    frozen = replace(base, model_version=f"huggingface_revision_{revision}")
    memory = psutil.virtual_memory()
    runtime_facts = {
        "backend_available": True,
        "memory_fits": memory.available >= 8 * 1024**3,
        "dependency_conflict": False,
        "model_load_status": PASS,
        "model_load_time_seconds": model_load_time,
        "rss_before_bytes": rss_before,
        "rss_after_bytes": rss_after,
        "rss_delta_bytes": rss_after - rss_before,
        "available_memory_bytes": memory.available,
        "torch_version": torch.__version__,
        "transformers_version": transformers_version,
        "device": str(parameter.device),
        "dtype": str(parameter.dtype),
    }
    result = finalize_eligibility(
        frozen,
        model_path=model,
        expected_sha256=expected_sha256,
        runtime_facts=runtime_facts,
    )
    result["model_file"] = _relative(model)
    result["source_revision"] = revision
    result["download_time_utc_from_file"] = datetime.fromtimestamp(
        model.stat().st_mtime, timezone.utc
    ).isoformat()
    record_name = "caidas__swin2SR-realworld-sr-x4-64-bsrgan-psnr.json"
    write_json(root / "records" / record_name, result)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.update(
        {
            "phase": "FINAL_ELIGIBILITY_BEFORE_SMOKE",
            "eligible_model_count": 1 if result["model_eligibility"] == PASS else 0,
            "eligible_model_ids": (
                [result["model_id"]]
                if result["model_eligibility"] == PASS
                else []
            ),
            "models_downloaded": 1,
            "downloaded_model_revision": revision,
            "downloaded_model_sha256": result["model_sha256"],
            "downloaded_model_size": result["model_size"],
            "model_load_status": runtime_facts["model_load_status"],
            "model_inference_run": 0,
            "models_benchmarked": 0,
        }
    )
    write_json(summary_path, summary)
    return {"summary": summary, "eligible_record": result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--gpu-name", required=True)
    parser.add_argument("--npu-name", required=True)
    parser.add_argument("--finalize-model-path", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--revision")
    args = parser.parse_args()
    if args.finalize_model_path:
        if not args.expected_sha256 or not args.revision:
            parser.error("--finalize-model-path requires --expected-sha256 and --revision")
        result = finalize_swin2sr(
            args.output_root,
            model_path=args.finalize_model_path,
            expected_sha256=args.expected_sha256,
            revision=args.revision,
        )
    else:
        result = build(
            args.output_root, gpu_name=args.gpu_name, npu_name=args.npu_name
        )
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
