from __future__ import annotations

import csv
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


PROBLEM_CODES = {
    "PASS",
    "PASS_WITH_NOTES",
    "BLOCKED_INPUT_DIR_MISSING",
    "BLOCKED_INPUT_EMPTY",
    "BLOCKED_OUTPUT_PERMISSION",
    "BLOCKED_FEEDBACK_DIR_PERMISSION",
    "BLOCKED_REALESRGAN_MISSING",
    "BLOCKED_MODEL_MISSING",
    "BLOCKED_VULKAN_OR_GPU",
    "FAILED_IMAGE_READ",
    "FAILED_MODEL_RUN",
    "FAILED_CONTACT_SHEET",
    "FAILED_FEEDBACK_ZIP",
    "WARNING_LOW_GAIN",
    "WARNING_FACE_RISK",
    "WARNING_TEXT_DENSE",
    "WARNING_HIGHLIGHT_RISK",
    "WARNING_SYSTEM_ENV_UNKNOWN",
}

DEFAULT_FEEDBACK_DIR = (
    Path("D:/影界文件/影界测试反馈包") if os.name == "nt" else Path.home() / "影界文件" / "影界测试反馈包"
)
README_NAME = "README_请把整个ZIP发给开发者.txt"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _text_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def _run_version(command: list[str], cwd: Path) -> str:
    try:
        completed = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, timeout=5, check=False)
    except Exception:
        return "unavailable"
    return (completed.stdout or completed.stderr or "").strip().splitlines()[0] if (completed.stdout or completed.stderr) else "unavailable"


def _git_commit(project_root: Path) -> str:
    value = _run_version(["git", "rev-parse", "--short", "HEAD"], project_root)
    return value if value and value != "unavailable" else "unknown"


def _safe_stat(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _image_count(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    return sum(1 for item in path.iterdir() if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS)


def _check_writable(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        marker = path / f".hdde_write_check_{os.getpid()}_{int(time.time())}.tmp"
        marker.write_text("ok", encoding="utf-8")
        marker.unlink(missing_ok=True)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _path_checks(input_dir: Path, output_dir: Path, feedback_dir: Path) -> dict[str, Any]:
    input_exists = input_dir.exists() and input_dir.is_dir()
    input_readable = False
    input_error = ""
    if input_exists:
        try:
            list(input_dir.iterdir())
            input_readable = True
        except Exception as exc:
            input_error = str(exc)

    output_writable, output_error = _check_writable(output_dir)
    feedback_writable, feedback_error = _check_writable(feedback_dir)
    return {
        "input_dir_exists": input_exists,
        "input_image_count": _image_count(input_dir),
        "input_dir_readable": input_readable,
        "input_dir_error": input_error,
        "output_dir_exists": output_dir.exists() and output_dir.is_dir(),
        "output_dir_creatable": output_writable,
        "output_dir_writable": output_writable,
        "output_dir_error": output_error,
        "feedback_dir_exists": feedback_dir.exists() and feedback_dir.is_dir(),
        "feedback_dir_creatable": feedback_writable,
        "feedback_dir_writable": feedback_writable,
        "feedback_dir_error": feedback_error,
    }


def _tool_checks(project_root: Path) -> dict[str, Any]:
    tool_dir = project_root / "external_tools" / "realesrgan-ncnn-vulkan"
    exe = tool_dir / "realesrgan-ncnn-vulkan.exe"
    model_dir = tool_dir / "models"
    required_files = [
        model_dir / "realesrgan-x4plus.param",
        model_dir / "realesrgan-x4plus.bin",
    ]
    return {
        "realesrgan_tool_dir": str(tool_dir),
        "realesrgan_exe_exists": exe.exists(),
        "model_dir_exists": model_dir.exists(),
        "required_model_files_exist": all(item.exists() for item in required_files),
        "required_model_files": [str(item) for item in required_files],
        "vulkan_gpu_check": "not_checked",
        "tool_check_result": "PASS" if exe.exists() and model_dir.exists() and all(item.exists() for item in required_files) else "BLOCKED",
    }


def _environment(project_root: Path, input_dir: Path, output_dir: Path, feedback_dir: Path, mode: str) -> dict[str, Any]:
    uname = platform.uname()
    return {
        "software_name": "影界 HDDE",
        "software_version": "V0.4.6 RC1",
        "commit": _git_commit(project_root),
        "mode": mode,
        "os_name": uname.system,
        "os_version": platform.version(),
        "windows_build": platform.version() if os.name == "nt" else "",
        "system_arch": platform.machine(),
        "python_version": sys.version.split()[0],
        "node_version": _run_version(["node", "--version"], project_root),
        "npm_version": _run_version(["npm", "--version"], project_root),
        "working_dir": str(project_root),
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "feedback_dir": str(feedback_dir),
    }


def _problem_from_result(run_result: dict[str, Any], path_checks: dict[str, Any], tool_checks: dict[str, Any]) -> tuple[str, str, str]:
    reason = str(run_result.get("reason") or "")
    status = str(run_result.get("verification_result") or run_result.get("status") or "PASS_WITH_NOTES")
    if not path_checks["input_dir_exists"]:
        return "BLOCKED", "输入路径", "BLOCKED_INPUT_DIR_MISSING"
    if path_checks["input_image_count"] <= 0:
        return "BLOCKED", "输入路径", "BLOCKED_INPUT_EMPTY"
    if not path_checks["output_dir_writable"]:
        return "BLOCKED", "输出路径", "BLOCKED_OUTPUT_PERMISSION"
    if not path_checks["feedback_dir_writable"]:
        return "BLOCKED", "输出路径", "BLOCKED_FEEDBACK_DIR_PERMISSION"
    if not tool_checks["realesrgan_exe_exists"]:
        return "BLOCKED", "外部工具", "BLOCKED_REALESRGAN_MISSING"
    if not tool_checks["required_model_files_exist"]:
        return "BLOCKED", "模型文件", "BLOCKED_MODEL_MISSING"
    if reason == "missing_input_images":
        return "BLOCKED", "输入路径", "BLOCKED_INPUT_EMPTY"
    if reason == "missing_realesrgan_exe":
        return "BLOCKED", "外部工具", "BLOCKED_REALESRGAN_MISSING"
    if reason == "missing_realesrgan_model_files":
        return "BLOCKED", "模型文件", "BLOCKED_MODEL_MISSING"
    if status == "BLOCKED":
        return "BLOCKED", "模型执行", "FAILED_MODEL_RUN"
    if int(run_result.get("skipped_count") or 0) > 0:
        return "PASS_WITH_NOTES", "图片质量", "PASS_WITH_NOTES"
    return "PASS", "无", "PASS"


def _image_results_csv(run_result: dict[str, Any], run_dir: Path, input_dir: Path) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "file_name",
            "status",
            "problem_code",
            "input_size",
            "output_size",
            "mode",
            "strategy",
            "enhanced_generated",
            "contact_sheet_generated",
            "elapsed_seconds",
            "quality_note",
            "risk_tags",
            "error_message",
        ],
    )
    writer.writeheader()
    for item in run_result.get("processed") or []:
        enhanced = _resolve_run_file(run_dir, str(item.get("enhanced") or ""))
        contact = _resolve_run_file(run_dir, str(item.get("contact_sheet") or ""))
        metrics = item.get("metrics") or {}
        risk_tags = []
        if float(metrics.get("text_ratio") or 0) > 0.22:
            risk_tags.append("WARNING_TEXT_DENSE")
        writer.writerow(
            {
                "file_name": item.get("file", ""),
                "status": "PASS",
                "problem_code": "PASS" if not risk_tags else ";".join(risk_tags),
                "input_size": _safe_stat(input_dir / str(item.get("file") or "")),
                "output_size": _safe_stat(enhanced),
                "mode": run_result.get("mode") or "safe_1080p",
                "strategy": "35% protected",
                "enhanced_generated": enhanced.exists(),
                "contact_sheet_generated": contact.exists(),
                "elapsed_seconds": item.get("elapsed_seconds", ""),
                "quality_note": "35% protected candidate generated; inspect contact sheet before use.",
                "risk_tags": ";".join(risk_tags),
                "error_message": "",
            }
        )
    for item in run_result.get("skipped") or []:
        writer.writerow(
            {
                "file_name": item.get("file", ""),
                "status": "SKIPPED",
                "problem_code": "WARNING_FACE_RISK" if item.get("type") == "portrait" else "PASS_WITH_NOTES",
                "input_size": _safe_stat(input_dir / str(item.get("file") or "")),
                "output_size": 0,
                "mode": run_result.get("mode") or "safe_1080p",
                "strategy": "35% protected",
                "enhanced_generated": False,
                "contact_sheet_generated": False,
                "elapsed_seconds": "",
                "quality_note": f"Skipped: {item.get('reason', '')}",
                "risk_tags": "WARNING_FACE_RISK" if item.get("type") == "portrait" else "",
                "error_message": item.get("reason", ""),
            }
        )
    return output.getvalue()


def _markdown_summary(run_result: dict[str, Any], status: str, input_dir: Path, output_dir: Path, zip_path: Path) -> str:
    return "\n".join(
        [
            "# 影界 HDDE 测试反馈包",
            "",
            f"- 最终状态：{status}",
            f"- 处理模式：{run_result.get('mode') or 'safe_1080p'}",
            f"- 输入目录：{input_dir}",
            f"- 输出目录：{output_dir}",
            f"- 输入图片数量：{int(run_result.get('processed_count') or 0) + int(run_result.get('skipped_count') or 0)}",
            f"- 成功数量：{int(run_result.get('processed_count') or 0)}",
            f"- 跳过数量：{int(run_result.get('skipped_count') or 0)}",
            "- 失败数量：0",
            f"- 反馈包生成时间：{_now_iso()}",
            f"- 反馈包路径：{zip_path}",
            "",
            "请将整个 ZIP 文件发送给开发者。",
            "",
        ]
    )


def _developer_diagnosis(status: str, stage: str, code: str, notes: list[str]) -> str:
    main_issue = "未发现阻断问题。" if status == "PASS" else "存在需要进一步查看的测试条件或图像收益边界。"
    action = "查看 contact sheet 与 diagnostics.json。" if status != "PASS" else "可作为有效测试反馈包归档。"
    return "\n".join(
        [
            f"最终状态：{status}",
            f"问题阶段：{stage}",
            f"problem_code：{code}",
            f"主要问题：{main_issue}",
            f"建议动作：{action}",
            f"是否需要用户重新测试：{'否' if status != 'BLOCKED' else '是'}",
            f"是否需要开发修复：{'否' if status == 'PASS' else '视 contact sheet 与 diagnostics.json 决定'}",
            "",
            "Notes:",
            *[f"- {note}" for note in notes],
            "",
        ]
    )


def _tool_check_text(tool_checks: dict[str, Any]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in tool_checks.items()) + "\n"


def _path_check_text(path_checks: dict[str, Any]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in path_checks.items()) + "\n"


def _resolve_run_file(run_dir: Path, value: str) -> Path:
    path = Path(str(value or ""))
    if path.is_absolute():
        return path
    return run_dir / path

def _environment_text(env: dict[str, Any], tool_checks: dict[str, Any], path_checks: dict[str, Any]) -> str:
    merged = {**env, **tool_checks, **path_checks}
    return "\n".join(f"{key}: {value}" for key, value in merged.items()) + "\n"


def generate_safe_1080p_feedback_package(
    run_result: dict[str, Any],
    project_root: Path,
    feedback_dir: Path | None = None,
) -> dict[str, Any]:
    project_root = Path(project_root)
    input_dir = Path(str(run_result.get("input_dir") or ""))
    output_dir = Path(str(run_result.get("output_dir") or ""))
    if not output_dir.is_absolute():
        output_dir = (project_root / output_dir).resolve()
    feedback_dir = Path(feedback_dir) if feedback_dir else DEFAULT_FEEDBACK_DIR
    feedback_dir.mkdir(parents=True, exist_ok=True)

    path_checks = _path_checks(input_dir, output_dir, feedback_dir)
    tool_checks = _tool_checks(project_root)
    status, problem_stage, problem_code = _problem_from_result(run_result, path_checks, tool_checks)
    env = _environment(project_root, input_dir, output_dir, feedback_dir, run_result.get("mode") or "safe_1080p")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = feedback_dir / f"HDDE_V046_测试反馈包_{timestamp}.zip"

    diagnostics = {
        "version": "V0.4.6 RC1",
        "commit": env["commit"],
        "mode": run_result.get("mode") or "safe_1080p",
        "strategy": "35% protected",
        "status": status,
        "problem_stage": problem_stage,
        "problem_code": problem_code,
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "feedback_zip_path": str(zip_path),
        "processed_count": int(run_result.get("processed_count") or 0),
        "success_count": int(run_result.get("processed_count") or 0),
        "skipped_count": int(run_result.get("skipped_count") or 0),
        "failed_count": 0,
        "started_at": run_result.get("started_at") or "",
        "finished_at": run_result.get("finished_at") or _now_iso(),
        "elapsed_seconds": run_result.get("elapsed_seconds", ""),
        "notes": ["Original images and enhanced outputs are not included by default."],
        **env,
        **tool_checks,
        **path_checks,
    }
    run_config = {
        "mode": run_result.get("mode") or "safe_1080p",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "beta_default_output_dir": "runtime/experiments/safe_1080p_beta",
        "strategy": "35% protected",
        "blend_ratio": 0.35,
        "uses_realesrgan": True,
        "realesrgan_tool_path": tool_checks["realesrgan_tool_dir"],
        "generate_contact_sheet": True,
        "include_original_images": False,
        "include_enhanced_outputs": False,
    }
    batch_report = {
        "version": "HDDE_V046_safe_1080p_beta_batch_report",
        "created_at": _now_iso(),
        "status": status,
        "problem_code": problem_code,
        "run_result": run_result,
    }
    entries: list[str] = []
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            payloads: dict[str, bytes] = {
                "summary.md": _text_bytes(_markdown_summary(run_result, status, input_dir, output_dir, zip_path)),
                "developer_diagnosis.md": _text_bytes(
                    _developer_diagnosis(status, problem_stage, problem_code, diagnostics["notes"])
                ),
                "batch_report.json": _json_bytes(batch_report),
                "diagnostics.json": _json_bytes(diagnostics),
                "image_results.csv": _text_bytes(_image_results_csv(run_result, output_dir, input_dir)),
                "run_config.json": _json_bytes(run_config),
                "environment.txt": _text_bytes(_environment_text(env, tool_checks, path_checks)),
                "tool_check.txt": _text_bytes(_tool_check_text(tool_checks)),
                "path_check.txt": _text_bytes(_path_check_text(path_checks)),
                "run_log.txt": _text_bytes(
                    f"Generated safe_1080p feedback package at {_now_iso()}.\n"
                    f"Run output directory: {output_dir}\n"
                    f"Processed: {run_result.get('processed_count', 0)}\n"
                    f"Skipped: {run_result.get('skipped_count', 0)}\n"
                ),
                "error_log.txt": _text_bytes("No error captured.\n" if status != "BLOCKED" else f"{problem_code}\n"),
                README_NAME: _text_bytes(
                    "请将整个 ZIP 文件发送给开发者，用于判断本次测试结果、运行环境、输出效果和错误原因。\n\n"
                    "本反馈包仅用于软件测试诊断，包含本次运行环境、路径检测、工具检测、日志和 contact sheet。"
                    "反馈包不会自动上传，不包含账号密码、网络地址、设备序列号或无关个人文件。"
                    "请用户确认后手动发送给开发者。\n"
                ),
            }
            for name, content in payloads.items():
                archive.writestr(name, content)
                entries.append(name)

            for item in run_result.get("processed") or []:
                contact_rel = str(item.get("contact_sheet") or "")
                if not contact_rel:
                    continue
                contact_path = _resolve_run_file(output_dir, contact_rel)
                if contact_path.exists() and contact_path.is_file():
                    arcname = f"contact_sheets/{contact_path.name}"
                    archive.write(contact_path, arcname)
                    entries.append(arcname)
    except Exception as exc:
        return {
            "feedback_bundle_status": "BLOCKED",
            "feedback_zip_path": "",
            "feedback_bundle_error": str(exc),
            "problem_code": "FAILED_FEEDBACK_ZIP",
            "problem_stage": "反馈包生成",
            "entries": [],
        }

    return {
        "feedback_bundle_status": status,
        "feedback_zip_path": str(zip_path),
        "feedback_bundle_size": zip_path.stat().st_size,
        "problem_stage": problem_stage,
        "problem_code": problem_code,
        "entries": entries,
        "contains_original_images": False,
        "contains_enhanced_outputs": False,
        "contains_contact_sheets": any(item.startswith("contact_sheets/") for item in entries),
    }
