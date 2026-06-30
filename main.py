import argparse
import asyncio
import json
import os
import queue
import re
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
from datetime import datetime
from pathlib import Path

from runtime import APP_VERSION
from runtime.crash_handler import handle_exception, install_global_exception_hook
from runtime.error_dialog import show_info_dialog
from runtime.startup_check import run_startup_check
from runtime.system_info import is_pyinstaller


AUTO_MODE = "fidelity"
SERVER_HOST = "localhost"
SERVER_PORT = 8787
SERVER_CORS_ORIGINS = ["*"]
DEFAULT_TASK_ID = "task_vmp_v04_core"
SUPPORTED_MODES = [
    "fidelity",
    "texture",
    "text_safe",
    "ai_image_clean",
    "sharp_4k",
    "auto",
    "ai_commercial_kv",
    "architecture",
    "cinematic",
    "cosmetics",
    "food",
    "luxury_product",
    "portrait_commercial",
    "ppt_business",
]

PROJECT_ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = PROJECT_ROOT / "settings" / "settings.json"
DEFAULT_WORK_DIR_NAME = "影界文件"
DEFAULT_INPUT_DIR_NAME = "\u8f93\u5165\u56fe\u7247"
DEFAULT_OUTPUT_DIR_NAME = "\u8f93\u51fa\u6210\u54c1"
BETA_LOG_QUEUE: queue.Queue[str] = queue.Queue(maxsize=256)


def _beta_log_worker() -> None:
    while True:
        line = BETA_LOG_QUEUE.get()
        try:
            sys.stderr.write(line + "\n")
            sys.stderr.flush()
        except Exception:
            pass


threading.Thread(target=_beta_log_worker, name="safe-1080p-beta-log", daemon=True).start()


def enqueue_beta_log(line: str) -> None:
    try:
        BETA_LOG_QUEUE.put_nowait(line)
    except queue.Full:
        pass


def default_output_dir() -> Path:
    if os.name == "nt":
        return Path("D:/影界文件/输出成品")
    return Path.home() / DEFAULT_WORK_DIR_NAME / DEFAULT_OUTPUT_DIR_NAME


def default_settings() -> dict:
    return {
        "default_output_dir": str(default_output_dir()),
        "input_cache_policy": "keep",
        "cleanup_input_cache_days": 0,
        "cleanup_input_cache_max_files": 0,
        "last_output_dir": "",
        "allow_custom_output_dir": True,
        "create_output_dir_if_missing": True,
        "default_output_format": "png",
        "target_resolution": "1080P",
    }


def load_settings() -> dict:
    settings = default_settings()
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SETTINGS_PATH.exists():
        try:
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings.update({key: value for key, value in loaded.items() if value is not None})
        except Exception:
            pass
    if any(marker in str(settings.get("default_output_dir", "")) for marker in ("闆", "杈", "澧", "雪原Ai增强引擎")):
        settings["default_output_dir"] = str(default_output_dir())
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    return settings


def get_desktop_work_dirs() -> tuple[Path, Path]:
    desktop = Path.home() / "Desktop"
    work_dir = desktop / "雪原Ai增强引擎"
    input_dir = work_dir / "输入图片"
    output_dir = work_dir / "输出成品"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    return input_dir, output_dir


def get_desktop_work_dirs() -> tuple[Path, Path]:
    work_dir = Path("D:/影界文件") if os.name == "nt" else Path.home() / DEFAULT_WORK_DIR_NAME
    input_dir = work_dir / DEFAULT_INPUT_DIR_NAME
    output_dir = work_dir / DEFAULT_OUTPUT_DIR_NAME
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    return input_dir, output_dir


def normalize_user_output_root(output_root: Path) -> Path:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_upload_name(filename: str | None) -> str:
    original = Path(filename or "image.png").name
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", original).strip(" .")
    return cleaned or "image.png"


def public_file_url(kind: str, filename: str) -> str:
    return f"/api/file/{kind}/{filename}"


def parse_scale_value(value) -> int:
    text = str(value or "2").lower().replace("x", "").strip()
    try:
        parsed = int(text)
    except ValueError:
        return 2
    return 4 if parsed == 4 else 2


def parse_output_format(value) -> str:
    output_format = str(value or "png").lower().lstrip(".").strip()
    if output_format == "auto":
        return "png"
    if output_format == "jpeg":
        output_format = "jpg"
    return output_format if output_format in {"png", "jpg", "webp"} else "png"


def make_task_id() -> str:
    return f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def cleanup_input_cache(input_dir: Path, max_age_days: int = 0, max_files: int = 0) -> dict:
    """Reserved V0.4 cache cleanup hook.

    V0.4 keeps uploaded originals for traceability. Automatic deletion is not
    enabled until the user explicitly defines retention limits.
    """
    _ = Path(input_dir), max_age_days, max_files
    return {"enabled": False, "removed": 0, "reason": "V0.4 keeps input cache by default."}


def parse_bool_value(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "debug"}


def format_sse_log(index: int, total: int, message: str, done: bool = False, extra: dict | None = None) -> str:
    payload = {
        "index": index,
        "total": total,
        "message": message,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "done": done,
    }
    if extra:
        payload.update(extra)
    return f"event: restoration.log\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def build_web_app():
    try:
        from fastapi import FastAPI, File, Form, HTTPException, UploadFile
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse, StreamingResponse
    except ImportError as exc:
        raise RuntimeError("缺少 FastAPI 服务依赖。请先运行：pip install -r requirements.txt") from exc

    from backend.restoration_server import RESTORATION_LOGS
    from backend.v036_output_core import build_output_plan, process_v036_output, sha256_file
    from engine.io import read_image

    input_dir, output_root = get_desktop_work_dirs()
    output_formal_dir = normalize_user_output_root(output_root)
    runtime_root = Path(__file__).resolve().parent / "runtime"
    output_work_dir = runtime_root / "work"
    output_debug_dir = runtime_root / "debug"
    output_test_dir = runtime_root / "test"
    for directory in (output_formal_dir, output_work_dir, output_debug_dir, output_test_dir):
        directory.mkdir(parents=True, exist_ok=True)
    task_registry: dict[str, dict] = {}

    app = FastAPI(title="VisualMasterPro V0.3 API", version=APP_VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=SERVER_CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def resolve_public_file(kind: str, filename: str) -> Path:
        roots = {
            "uploads": input_dir,
            "outputs": output_formal_dir,
            "work": output_work_dir,
            "debug": output_debug_dir,
            "test": output_test_dir,
        }
        root = roots.get(kind)
        if root is None:
            raise HTTPException(status_code=404, detail="未知文件类型。")
        target = (root / filename).resolve()
        root_resolved = root.resolve()
        if root_resolved not in target.parents and target != root_resolved:
            raise HTTPException(status_code=403, detail="非法文件路径。")
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="文件不存在。")
        return target

    def run_image_pipeline(task: dict) -> dict:
        task["status"] = "processing"
        result = process_v036_output(
            task["input_path"],
            task["output_root"],
            mode=task["mode"],
            output_profile=task["output_profile"],
            output_format=task["output_format"],
            initial_timing=task.get("debug_timing"),
            debug_keep_intermediate=task.get("debug_keep_intermediate", False),
        )
        final_path = result["final_output_path"]
        main_path = result["main_output_path"]
        optimized_path = result["optimized_output_path"]
        main_output_url = public_file_url("work", main_path.name) if main_path else None
        optimized_output_url = public_file_url("work", optimized_path.name) if optimized_path else None
        debug_quality = dict(result.get("debug_quality") or {})
        for key in (
            "input_size_bytes",
            "main_size_bytes",
            "optimized_size_bytes",
            "final_size_bytes",
            "file_size_ratio",
            "compression_saved_ratio",
            "quality_preserved",
            "compression_note",
            "input_hash",
            "output_hash",
            "hash_equal",
            "pixel_diff_score",
            "output_changed",
            "warnings",
        ):
            debug_quality.setdefault(key, result.get(key))
        task.update(
            {
                "status": "completed",
                "output_path": final_path,
                "enhancedUrl": public_file_url("outputs", final_path.name),
                "main_output_url": main_output_url,
                "optimized_output_url": optimized_output_url,
                "final_output_url": public_file_url("outputs", final_path.name),
                "final_output_exists": final_path.exists(),
                "sourceWidth": result["input_width"],
                "sourceHeight": result["input_height"],
                "width": result["width"],
                "height": result["height"],
                "qualityFlag": result["compression_note"],
                "debug_quality": debug_quality,
                "debug_timing": result["debug_timing"],
                "debug_log_path": result["debug_log_path"],
                **{key: result.get(key) for key in [
                    "output_profile",
                    "output_format",
                    "selected_output_profile",
                    "selected_output_format",
                    "final_output_type",
                    "input_width",
                    "input_height",
                    "output_width",
                    "output_height",
                    "target_width",
                    "target_height",
                    "aspect_ratio",
                    "aspect_preset",
                    "scale_policy",
                    "resolution_gate_pass",
                    "visual_quality_gate_pass",
                    "quality_1080p_pass",
                    "quality_1080p_level",
                    "visual_quality_note",
                    "image_type",
                    "image_type_features",
                    "face_detail_score",
                    "face_detail_gain",
                    "hair_texture_score",
                    "hair_texture_gain",
                    "fabric_texture_score",
                    "fabric_texture_gain",
                    "text_edge_clean_score",
                    "small_text_readability_score",
                    "dark_detail_score",
                    "dark_detail_gain",
                    "over_smoothing_risk",
                    "texture_loss_risk",
                    "final_selection_reason",
                    "input_size_bytes",
                    "main_size_bytes",
                    "optimized_size_bytes",
                    "final_size_bytes",
                    "file_size_ratio",
                    "compression_saved_ratio",
                    "quality_preserved",
                    "compression_note",
                    "output_changed",
                    "hash_equal",
                    "pixel_diff_score",
                    "has_alpha",
                    "has_real_alpha",
                    "alpha_used",
                    "selected_format_reason",
                    "debug_keep_intermediate",
                ]},
                "output_contract": {
                    "enhancedUrl": public_file_url("outputs", final_path.name),
                    "main_output_url": main_output_url,
                    "optimized_output_url": optimized_output_url,
                    "final_output_url": public_file_url("outputs", final_path.name),
                    "enhanced_equals_final": True,
                    "formal_output_dir": str(output_formal_dir),
                    "work_output_dir": str(output_work_dir),
                    "debug_output_dir": str(output_debug_dir),
                    "test_output_dir": str(output_test_dir),
                    "official_images_only_final": True,
                    "final_output_exists": final_path.exists(),
                },
                "completedAt": datetime.now().isoformat(timespec="seconds"),
            }
        )
        return task

    async def stream_task_events(task_id: str, delay: float = 0.38):
        task = task_registry.get(task_id) or task_registry.get(DEFAULT_TASK_ID)
        total = len(RESTORATION_LOGS)

        if not task:
            yield format_sse_log(1, total, "SSE CONNECTED /task/task_vmp_v03_core/stream")
            yield format_sse_log(2, total, "未发现待处理图片，请先在工作台上传图片。", done=True)
            yield "data: [DONE]\n\n"
            return

        worker = asyncio.create_task(asyncio.to_thread(run_image_pipeline, task))
        yield format_sse_log(1, total, RESTORATION_LOGS[0])

        for index, message in enumerate(RESTORATION_LOGS[1:-1], start=2):
            await asyncio.sleep(max(0.0, float(delay)))
            if index == total - 1:
                target_w = task.get("output_width") or task.get("target_width")
                target_h = task.get("output_height") or task.get("target_height")
                message = (
                    f"1080P 质量守门：尺寸目标 {target_w}×{target_h}，"
                    "正在检测文字清晰度、边缘质量、色彩忠实度与伪高清风险。"
                )
            yield format_sse_log(index, total, message)

        try:
            await worker
            debug_quality = task.get("debug_quality") or {}
            debug_timing = task.get("debug_timing") or {}
            warnings = debug_quality.get("warnings") or []
            final_message = (
                f"1080P 质量判断：image_type={task.get('image_type')}，"
                f"quality_1080p_pass={task.get('quality_1080p_pass')}，"
                f"quality_level={task.get('quality_1080p_level')}，"
                f"text_clarity_gain={debug_quality.get('text_clarity_gain')}，"
                f"edge_quality_gain={debug_quality.get('edge_quality_gain')}，"
                f"detail_stability={debug_quality.get('detail_stability_score')}，"
                f"over_smoothing_risk={debug_quality.get('over_smoothing_risk')}，"
                f"texture_loss_risk={debug_quality.get('texture_loss_risk')}，"
                f"color_fidelity={debug_quality.get('color_fidelity_score')}，"
                f"pseudo_hd_risk={debug_quality.get('pseudo_hd_risk')}，"
                f"final_selection={debug_quality.get('final_selection_reason')}，"
                f"final_output_url={task.get('final_output_url')} 已生成，"
                f"size_ratio={debug_quality.get('file_size_ratio')}，"
                f"output_changed={debug_quality.get('output_changed')}，"
                f"hash_equal={debug_quality.get('hash_equal')}，"
                f"pixel_diff_score={debug_quality.get('pixel_diff_score')}，"
                f"final_output_type={task.get('final_output_type')}，"
                f"total_time={debug_timing.get('total_time')}s"
            )
            if warnings:
                final_message = f"{final_message}; {'; '.join(warnings)}"
            yield format_sse_log(
                total,
                total,
                final_message,
                done=True,
                extra={
                    "debug_quality": debug_quality,
                    "debug_timing": debug_timing,
                    "outputUrl": task.get("enhancedUrl"),
                    "output_contract": {
                        "main_output_url": task.get("main_output_url"),
                        "optimized_output_url": task.get("optimized_output_url"),
                        "final_output_url": task.get("final_output_url") or task.get("enhancedUrl"),
                        "output_profile": task.get("output_profile"),
                        "output_format": task.get("output_format"),
                        "selected_output_profile": task.get("selected_output_profile"),
                        "selected_output_format": task.get("selected_output_format"),
                        "final_output_type": task.get("final_output_type"),
                        "quality_preserved": task.get("quality_preserved"),
                        "compression_note": task.get("compression_note"),
                        "quality_1080p_pass": task.get("quality_1080p_pass"),
                        "quality_1080p_level": task.get("quality_1080p_level"),
                        "resolution_gate_pass": task.get("resolution_gate_pass"),
                        "visual_quality_gate_pass": task.get("visual_quality_gate_pass"),
                        "enhanced_equals_final": task.get("enhancedUrl") == (task.get("final_output_url") or task.get("enhancedUrl")),
                    },
                },
            )
        except Exception as exc:
            task["status"] = "failed"
            task["error"] = str(exc)
            yield format_sse_log(total, total, f"任务失败：{exc}", done=True)

        yield "data: [DONE]\n\n"

    @app.get("/api/health")
    async def health():
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "message": "VisualMasterPro V0.3 API 已就绪。",
            "data": {
                "version": APP_VERSION,
                "host": SERVER_HOST,
                "port": SERVER_PORT,
                "inputDir": str(input_dir),
                "outputDir": str(output_formal_dir),
                "uploadEndpoint": "/api/upload",
                "streamEndpoint": f"/api/v1/tasks/{DEFAULT_TASK_ID}/stream",
                "logLines": len(RESTORATION_LOGS),
                "backendStage": "V0.3.6",
                "outputProfiles": [
                    {"key": "delivery_1080p", "name": "高清交付 1080P", "default": True},
                    {"key": "preview_light", "name": "轻量优化版", "default": False},
                    {"key": "fidelity_original", "name": "原尺寸忠实增强", "default": False},
                ],
                "outputFormats": [
                    {"key": "auto", "name": "自动", "default": True},
                    {"key": "png", "name": "PNG", "default": False},
                    {"key": "jpg", "name": "JPG", "default": False},
                    {"key": "webp", "name": "WebP", "default": False},
                ],
                "cors": "ONLINE",
                "topology": [
                    {"name": "Local Client", "port": 5173, "status": "ONLINE"},
                    {"name": "XHR Stream", "contract": "file/mode/scale/format", "status": "READY"},
                    {"name": "Python Runtime", "port": 8787, "status": "ONLINE"},
                    {"name": "CORS", "policy": "ALLOW_ALL", "status": "ONLINE"},
                ],
                "modes": [
                    {"key": "fidelity", "name": "原图忠实", "status": "READY"},
                    {"key": "text_safe", "name": "文本增强", "status": "READY"},
                    {"key": "sharp_4k", "name": "极限自然", "status": "READY"},
                    {"key": "ai_image_clean", "name": "极境夜景", "status": "READY"},
                ],
            },
        }

    @app.get("/api/stream")
    @app.get("/api/v1/tasks/task_vmp_v03_core/stream")
    @app.get("/api/v1/tasks/{task_id}/stream")
    async def stream(task_id: str = DEFAULT_TASK_ID, delay: float = 0.38):
        return StreamingResponse(
            stream_task_events(task_id, delay),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.get("/api/file/{kind}/{filename:path}")
    async def serve_file(kind: str, filename: str):
        return FileResponse(resolve_public_file(kind, filename))

    @app.get("/api/v1/tasks/{task_id}")
    async def task_status(task_id: str):
        task = task_registry.get(task_id) or task_registry.get(DEFAULT_TASK_ID)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在。")
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "data": {
                "taskId": task.get("taskId", task_id),
                "status": task.get("status"),
                "fileName": task.get("fileName"),
                "mode": task.get("mode"),
                "scale": task.get("scale"),
                "format": task.get("format"),
                "originalUrl": public_file_url("uploads", Path(task["input_path"]).name),
                "enhancedUrl": task.get("enhancedUrl") or public_file_url("outputs", Path(task["expected_output_path"]).name),
                "main_output_url": task.get("main_output_url"),
                "optimized_output_url": task.get("optimized_output_url"),
                "final_output_url": task.get("final_output_url") or task.get("enhancedUrl") or public_file_url("outputs", Path(task["expected_output_path"]).name),
                "final_output_exists": bool(task.get("final_output_exists")),
                "output_profile": task.get("output_profile"),
                "output_format": task.get("output_format"),
                "selected_output_profile": task.get("selected_output_profile"),
                "selected_output_format": task.get("selected_output_format"),
                "final_output_type": task.get("final_output_type"),
                "input_width": task.get("input_width") or task.get("sourceWidth"),
                "input_height": task.get("input_height") or task.get("sourceHeight"),
                "output_width": task.get("output_width") or task.get("width"),
                "output_height": task.get("output_height") or task.get("height"),
                "target_width": task.get("target_width"),
                "target_height": task.get("target_height"),
                "aspect_ratio": task.get("aspect_ratio"),
                "aspect_preset": task.get("aspect_preset"),
                "scale_policy": task.get("scale_policy"),
                "resolution_gate_pass": task.get("resolution_gate_pass"),
                "visual_quality_gate_pass": task.get("visual_quality_gate_pass"),
                "quality_1080p_pass": task.get("quality_1080p_pass"),
                "quality_1080p_level": task.get("quality_1080p_level"),
                "visual_quality_note": task.get("visual_quality_note"),
                "image_type": task.get("image_type"),
                "image_type_features": task.get("image_type_features"),
                "face_detail_score": task.get("face_detail_score"),
                "face_detail_gain": task.get("face_detail_gain"),
                "hair_texture_score": task.get("hair_texture_score"),
                "hair_texture_gain": task.get("hair_texture_gain"),
                "fabric_texture_score": task.get("fabric_texture_score"),
                "fabric_texture_gain": task.get("fabric_texture_gain"),
                "text_edge_clean_score": task.get("text_edge_clean_score"),
                "small_text_readability_score": task.get("small_text_readability_score"),
                "dark_detail_score": task.get("dark_detail_score"),
                "dark_detail_gain": task.get("dark_detail_gain"),
                "over_smoothing_risk": task.get("over_smoothing_risk"),
                "texture_loss_risk": task.get("texture_loss_risk"),
                "final_selection_reason": task.get("final_selection_reason"),
                "input_size_bytes": task.get("input_size_bytes"),
                "main_size_bytes": task.get("main_size_bytes"),
                "optimized_size_bytes": task.get("optimized_size_bytes"),
                "final_size_bytes": task.get("final_size_bytes"),
                "file_size_ratio": task.get("file_size_ratio"),
                "compression_saved_ratio": task.get("compression_saved_ratio"),
                "quality_preserved": task.get("quality_preserved"),
                "compression_note": task.get("compression_note"),
                "output_changed": task.get("output_changed"),
                "hash_equal": task.get("hash_equal"),
                "pixel_diff_score": task.get("pixel_diff_score"),
                "has_alpha": task.get("has_alpha"),
                "has_real_alpha": task.get("has_real_alpha"),
                "alpha_used": task.get("alpha_used"),
                "selected_format_reason": task.get("selected_format_reason"),
                "debug_keep_intermediate": task.get("debug_keep_intermediate"),
                "debug_quality": task.get("debug_quality"),
                "debug_timing": task.get("debug_timing"),
                "debug_log_path": task.get("debug_log_path"),
                "output_contract": task.get("output_contract"),
                "error": task.get("error"),
            },
        }

    @app.post("/api/upload")
    async def upload_file(
        file: UploadFile = File(...),
        mode: str = Form("fidelity"),
        scale: str = Form("2"),
        output_profile: str = Form("delivery_1080p"),
        output_format: str | None = Form(None),
        format: str | None = Form(None),
        debug_keep_intermediate: str | None = Form("false"),
        debug_mode: str | None = Form(None),
    ):
        upload_name = safe_upload_name(file.filename)
        requested_output_format = parse_output_format(output_format or format or "auto")
        scale_value = parse_scale_value(scale)

        receive_start = time.perf_counter()
        raw = await file.read()
        receive_file_time = round(time.perf_counter() - receive_start, 6)
        if not raw:
            raise HTTPException(status_code=400, detail="上传图片为空。")

        input_dir.mkdir(parents=True, exist_ok=True)
        for directory in (output_formal_dir, output_work_dir, output_debug_dir, output_test_dir):
            directory.mkdir(parents=True, exist_ok=True)
        saved_path = input_dir / upload_name
        save_start = time.perf_counter()
        saved_path.write_bytes(raw)
        save_input_time = round(time.perf_counter() - save_start, 6)

        source_image = read_image(saved_path)
        source_height, source_width = source_image.shape[:2] if source_image is not None else (0, 0)
        input_hash = sha256_file(saved_path)
        input_size_bytes = saved_path.stat().st_size
        keep_intermediate = parse_bool_value(debug_keep_intermediate) or parse_bool_value(debug_mode)
        output_plan = build_output_plan(saved_path, output_root, output_profile, requested_output_format, keep_intermediate)
        expected_output_path = output_plan["paths"]["final"]
        task = {
            "taskId": DEFAULT_TASK_ID,
            "status": "ready",
            "input_path": saved_path,
            "output_root": output_formal_dir,
            "output_dir": output_formal_dir,
            "expected_output_path": expected_output_path,
            "mode": mode or "fidelity",
            "scale": scale_value,
            "format": requested_output_format,
            "output_profile": output_profile or "delivery_1080p",
            "output_format": requested_output_format,
            "selected_output_profile": output_plan["selected_output_profile"],
            "selected_output_format": output_plan["selected_output_format"],
            "fileName": upload_name,
            "createdAt": datetime.now().isoformat(timespec="seconds"),
            "input_hash": input_hash,
            "input_size_bytes": input_size_bytes,
            "input_width": source_width,
            "input_height": source_height,
            "output_width": output_plan["output_width"],
            "output_height": output_plan["output_height"],
            "target_width": output_plan["target_width"],
            "target_height": output_plan["target_height"],
            "aspect_ratio": output_plan["aspect_ratio"],
            "aspect_preset": output_plan["aspect_preset"],
            "scale_policy": output_plan["scale_policy"],
            "image_type": output_plan["image_type"],
            "image_type_features": output_plan["image_type_features"],
            "resolution_gate_pass": output_plan["resolution_gate_pass"],
            "has_alpha": output_plan["has_alpha"],
            "has_real_alpha": output_plan["has_real_alpha"],
            "alpha_used": output_plan["alpha_used"],
            "selected_format_reason": output_plan["selected_format_reason"],
            "debug_keep_intermediate": keep_intermediate,
            "debug_timing": {
                "receive_file_time": receive_file_time,
                "save_input_time": save_input_time,
            },
        }
        task_registry[DEFAULT_TASK_ID] = task

        data = {
            "fileName": upload_name,
            "taskId": DEFAULT_TASK_ID,
            "mode": mode or "fidelity",
            "originalPath": str(saved_path),
            "outputPath": str(expected_output_path),
            "originalUrl": public_file_url("uploads", saved_path.name),
            "enhancedUrl": public_file_url("outputs", expected_output_path.name),
            "main_output_url": public_file_url("work", output_plan["paths"]["main"].name) if keep_intermediate else None,
            "optimized_output_url": public_file_url("work", output_plan["paths"]["optimized"].name) if keep_intermediate else None,
            "final_output_url": public_file_url("outputs", expected_output_path.name),
            "final_output_exists": expected_output_path.exists(),
            "output_profile": output_profile or "delivery_1080p",
            "output_format": requested_output_format,
            "selected_output_profile": output_plan["selected_output_profile"],
            "selected_output_format": output_plan["selected_output_format"],
            "final_output_type": None,
            "sourceWidth": source_width,
            "sourceHeight": source_height,
            "input_width": source_width,
            "input_height": source_height,
            "output_width": output_plan["output_width"],
            "output_height": output_plan["output_height"],
            "target_width": output_plan["target_width"],
            "target_height": output_plan["target_height"],
            "aspect_ratio": output_plan["aspect_ratio"],
            "aspect_preset": output_plan["aspect_preset"],
            "scale_policy": output_plan["scale_policy"],
            "image_type": output_plan["image_type"],
            "image_type_features": output_plan["image_type_features"],
            "resolution_gate_pass": output_plan["resolution_gate_pass"],
            "visual_quality_gate_pass": None,
            "quality_1080p_pass": None,
            "quality_1080p_level": None,
            "visual_quality_note": None,
            "input_size_bytes": input_size_bytes,
            "main_size_bytes": None,
            "optimized_size_bytes": None,
            "final_size_bytes": None,
            "file_size_ratio": None,
            "compression_saved_ratio": None,
            "quality_preserved": None,
            "compression_note": None,
            "input_hash": input_hash,
            "output_changed": None,
            "hash_equal": None,
            "pixel_diff_score": None,
            "has_alpha": output_plan["has_alpha"],
            "has_real_alpha": output_plan["has_real_alpha"],
            "alpha_used": output_plan["alpha_used"],
            "selected_format_reason": output_plan["selected_format_reason"],
            "debug_keep_intermediate": keep_intermediate,
            "debug_timing": task["debug_timing"],
            "width": output_plan["output_width"],
            "height": output_plan["output_height"],
            "scale": scale_value,
            "format": requested_output_format,
            "qualityFlag": "任务已登记，等待 SSE 管线执行。",
            "streamEndpoint": f"/api/v1/tasks/{DEFAULT_TASK_ID}/stream",
            "debug_quality": {
                "input_width": source_width,
                "input_height": source_height,
                "output_width": output_plan["output_width"],
                "output_height": output_plan["output_height"],
                "target_width": output_plan["target_width"],
                "target_height": output_plan["target_height"],
                "aspect_ratio": output_plan["aspect_ratio"],
                "aspect_preset": output_plan["aspect_preset"],
                "scale_policy": output_plan["scale_policy"],
                "image_type": output_plan["image_type"],
                "image_type_features": output_plan["image_type_features"],
                "resolution_gate_pass": output_plan["resolution_gate_pass"],
                "visual_quality_gate_pass": None,
                "quality_1080p_pass": None,
                "quality_1080p_level": None,
                "has_alpha": output_plan["has_alpha"],
                "has_real_alpha": output_plan["has_real_alpha"],
                "alpha_used": output_plan["alpha_used"],
                "selected_format_reason": output_plan["selected_format_reason"],
            },
            "output_contract": {
                "enhancedUrl": public_file_url("outputs", expected_output_path.name),
                "main_output_url": public_file_url("work", output_plan["paths"]["main"].name) if keep_intermediate else None,
                "optimized_output_url": public_file_url("work", output_plan["paths"]["optimized"].name) if keep_intermediate else None,
                "final_output_url": public_file_url("outputs", expected_output_path.name),
                "final_output_exists": expected_output_path.exists(),
                "enhanced_equals_final": True,
                "formal_output_dir": str(output_formal_dir),
                "work_output_dir": str(output_work_dir),
                "debug_output_dir": str(output_debug_dir),
                "test_output_dir": str(output_test_dir),
                "official_images_only_final": True,
            },
        }
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "message": "图片上传完成，已登记为异步修复任务。",
            "filename": upload_name,
            "url": data["originalUrl"],
            "data": data,
        }

    return app


def build_web_app():
    try:
        from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
    except ImportError as exc:
        raise RuntimeError("缺少 FastAPI 服务依赖，请先安装 requirements.txt。") from exc

    from backend.v036_output_core import build_output_plan, sha256_file
    from engine.diagnostics.feedback_bundle import generate_feedback_bundle
    from engine.pipeline import process_v046_delivery

    settings_data = load_settings()
    try:
        input_dir, default_output_root = get_desktop_work_dirs()
    except Exception:
        input_dir = PROJECT_ROOT / "runtime" / "v04_inputs"
        default_output_root = PROJECT_ROOT / "runtime" / "v04_outputs"
        input_dir.mkdir(parents=True, exist_ok=True)
        default_output_root.mkdir(parents=True, exist_ok=True)
    configured_output = Path(settings_data.get("default_output_dir") or default_output_root)
    try:
        output_formal_dir = normalize_user_output_root(configured_output)
    except Exception:
        output_formal_dir = normalize_user_output_root(default_output_root)

    task_registry: dict[str, dict] = {}
    upload_file_index: dict[str, Path] = {}
    output_file_index: dict[str, Path] = {}
    background_tasks: dict[str, asyncio.Task] = {}
    latest_task_id = {"value": None}

    app = FastAPI(title="VisualMasterPro / Yingjie V0.4 API", version="V0.4")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def save_settings(next_settings: dict) -> None:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(next_settings, ensure_ascii=False, indent=2), encoding="utf-8")

    def normalize_output_dir_text(value: str | None) -> str:
        return str(value or "").strip().strip('"').strip()

    def validate_output_dir_value(output_dir_value: str | None, allow_create: bool | None = None, source_hint: str | None = None) -> dict:
        raw = normalize_output_dir_text(output_dir_value)
        allow_create = bool(settings_data.get("create_output_dir_if_missing", True)) if allow_create is None else bool(allow_create)
        if not raw:
            return {
                "valid": False,
                "exists": False,
                "created": False,
                "writable": False,
                "normalized_path": "",
                "source": source_hint or "empty",
                "message": "输出目录为空。",
            }
        if "\x00" in raw:
            return {
                "valid": False,
                "exists": False,
                "created": False,
                "writable": False,
                "normalized_path": "",
                "source": source_hint or "invalid",
                "message": "输出路径非法：包含不可见控制字符。",
            }
        try:
            target = Path(raw).expanduser()
            if not target.is_absolute():
                target = (PROJECT_ROOT / target).resolve()
            else:
                target = target.resolve()
        except Exception as exc:
            return {
                "valid": False,
                "exists": False,
                "created": False,
                "writable": False,
                "normalized_path": "",
                "source": source_hint or "invalid",
                "message": f"输出路径非法：{exc}",
            }
        existed = target.exists()
        created = False
        if existed and not target.is_dir():
            return {
                "valid": False,
                "exists": True,
                "created": False,
                "writable": False,
                "normalized_path": str(target),
                "source": source_hint or "invalid",
                "message": "输出路径已存在，但不是目录。",
            }
        if not existed:
            if not allow_create:
                return {
                    "valid": False,
                    "exists": False,
                    "created": False,
                    "writable": False,
                    "normalized_path": str(target),
                    "source": source_hint or "invalid",
                    "message": "输出目录不存在，且当前配置不允许自动创建。",
                }
            try:
                target.mkdir(parents=True, exist_ok=True)
                created = True
            except Exception as exc:
                return {
                    "valid": False,
                    "exists": False,
                    "created": False,
                    "writable": False,
                    "normalized_path": str(target),
                    "source": source_hint or "invalid",
                    "message": f"输出目录不存在且无法创建：{exc}",
                }
        probe = target / f".vmp_write_test_{uuid.uuid4().hex}.tmp"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except Exception as exc:
            try:
                probe.unlink(missing_ok=True)
            except Exception:
                pass
            return {
                "valid": False,
                "exists": target.exists(),
                "created": created,
                "writable": False,
                "normalized_path": str(target),
                "source": source_hint or "invalid",
                "message": f"输出目录不可写：{exc}",
            }
        return {
            "valid": True,
            "exists": target.exists(),
            "created": created,
            "writable": True,
            "normalized_path": str(target),
            "source": source_hint or "default",
            "message": "输出目录可用",
        }

    def resolve_output_dir(output_dir_value: str | None) -> tuple[Path, dict]:
        requested = normalize_output_dir_text(output_dir_value)
        allow_custom = bool(settings_data.get("allow_custom_output_dir", True))
        candidates: list[tuple[str, str]] = []
        if requested:
            if not allow_custom:
                raise HTTPException(status_code=400, detail="当前配置不允许使用自定义输出目录。")
            candidates.append(("request", requested))
        last_used = normalize_output_dir_text(settings_data.get("last_output_dir"))
        if not requested and last_used:
            candidates.append(("last_used", last_used))
        default_value = normalize_output_dir_text(settings_data.get("default_output_dir"))
        if default_value:
            candidates.append(("default", default_value))
        candidates.append(("runtime_fallback", str(default_output_root)))
        errors: list[str] = []
        for source, value in candidates:
            checked = validate_output_dir_value(value, source_hint=source)
            if checked["valid"]:
                target = Path(checked["normalized_path"])
                meta = {
                    "output_dir_source": source,
                    "used_custom_output_dir": source == "request",
                    "output_dir_created": bool(checked.get("created")),
                    "output_dir_message": checked.get("message") or "",
                }
                if source == "request":
                    settings_data["last_output_dir"] = str(target)
                    save_settings(settings_data)
                return target, meta
            errors.append(f"{source}: {checked['message']}")
            if source == "request":
                raise HTTPException(status_code=400, detail=checked["message"])
        raise HTTPException(status_code=400, detail="输出目录不可用：" + "；".join(errors))

    def resolve_output_dir_for_open(output_dir_value: str | None) -> dict:
        checked = validate_output_dir_value(output_dir_value, allow_create=False, source_hint="request")
        return checked

    def update_task_result_output_meta(task_result: dict, task: dict, final_path: Path) -> dict:
        meta = task.get("output_dir_meta") or {}
        task_result.update(
            {
                "input_dir": str(Path(task["input_path"]).parent),
                "input_path": str(task["input_path"]),
                "input_filename": Path(task["input_path"]).name,
                "output_dir": str(final_path.parent),
                "output_directory": str(final_path.parent),
                "output_directory_source": meta.get("output_dir_source") or "default",
                "output_path": str(final_path),
                "output_filename": final_path.name,
                "final_output_path": str(final_path),
                "final_output_filename": final_path.name,
                "output_size": final_path.stat().st_size if final_path.exists() else task_result.get("output_size", 0),
                "final_output_url": public_file_url("outputs", final_path.name),
                "preview_output_url": public_file_url("outputs", final_path.name),
                "used_custom_output_dir": bool(meta.get("used_custom_output_dir")),
                "output_dir_source": meta.get("output_dir_source") or "default",
                "output_dir_created": bool(meta.get("output_dir_created")),
                "output_path_exists": final_path.exists(),
            }
        )
        return task_result

    def resolve_output_dir_legacy(output_dir_value: str | None) -> Path:
        target, _meta = resolve_output_dir(output_dir_value)
        return target

    def _legacy_unused() -> None:
        return None

    def _old_resolve_output_dir(output_dir_value: str | None) -> Path:
        raw = (output_dir_value or "").strip()
        target = Path(raw) if raw else output_formal_dir
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"输出目录无法创建：{target}；原因：{exc}") from exc
        return target

    def unique_input_path(name: str) -> Path:
        path = input_dir / name
        if not path.exists():
            return path
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = input_dir / f"{path.stem}_{stamp}{path.suffix}"
        counter = 1
        while candidate.exists():
            candidate = input_dir / f"{path.stem}_{stamp}_{counter}{path.suffix}"
            counter += 1
        return candidate

    def safe_mode(value: str | None) -> str:
        mode_value = str(value or "fidelity").strip().lower()
        return mode_value if mode_value in {"fidelity", "texture", "text_safe"} else "fidelity"

    def empty_task_report() -> dict:
        return {
            "clarity_score": 0,
            "text_clarity_score": 0,
            "edge_quality_score": 0,
            "structure_score": 0,
            "color_fidelity_score": 0,
            "texture_score": 0,
            "pseudo_hd_risk": "medium",
            "artifact_risk": "medium",
            "delivery_score": 0,
            "warnings": [],
        }

    def public_task(task: dict) -> dict:
        result = dict(task)
        for key in ("input_path", "output_root", "expected_output_path", "output_path"):
            if key in result and result[key] is not None:
                result[key] = str(result[key])
        result["taskId"] = result.get("task_id")
        result["status"] = result.get("task_status")
        result["streamEndpoint"] = f"/api/v1/tasks/{result.get('task_id')}/stream"
        result["originalUrl"] = public_file_url("uploads", Path(result.get("input_path", "")).name)
        if result.get("task_result"):
            filename = result["task_result"].get("output_filename")
            if filename:
                result["enhancedUrl"] = public_file_url("outputs", filename)
                result["final_output_url"] = result["enhancedUrl"]
        else:
            expected = result.get("expected_output_path")
            if expected:
                result["enhancedUrl"] = public_file_url("outputs", Path(expected).name)
                result["final_output_url"] = result["enhancedUrl"]
        result.setdefault("main_output_url", None)
        result.setdefault("optimized_output_url", None)
        result.setdefault("final_output_exists", False)
        return result

    def resolve_public_file(kind: str, filename: str) -> Path:
        if kind == "uploads":
            indexed = upload_file_index.get(Path(filename).name)
            if indexed and indexed.exists():
                return indexed
            root = input_dir.resolve()
            target = (input_dir / filename).resolve()
        elif kind == "outputs":
            indexed = output_file_index.get(Path(filename).name)
            if indexed and indexed.exists():
                return indexed
            candidate_roots = [output_formal_dir]
            for value in (
                settings_data.get("last_output_dir"),
                settings_data.get("default_output_dir"),
            ):
                if value:
                    candidate = Path(value).expanduser()
                    if candidate not in candidate_roots:
                        candidate_roots.append(candidate)
            for candidate_root in candidate_roots:
                root = candidate_root.resolve()
                target = (candidate_root / filename).resolve()
                if root in target.parents or target == root:
                    if target.exists() and target.is_file():
                        output_file_index[Path(filename).name] = target
                        return target
            root = output_formal_dir.resolve()
            target = (output_formal_dir / filename).resolve()
        else:
            raise HTTPException(status_code=404, detail="未知文件类型。")
        if root not in target.parents and target != root:
            raise HTTPException(status_code=403, detail="非法文件路径。")
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="文件不存在。")
        return target

    async def run_task_background(task_id: str) -> None:
        task = task_registry.get(task_id)
        if not task:
            return
        if task.get("task_status") in {"processing", "completed", "failed"}:
            return
        await asyncio.to_thread(run_image_pipeline, task)

    def ensure_task_started(task: dict) -> None:
        task_id = task.get("task_id")
        if not task_id:
            return
        if task.get("task_status") in {"processing", "completed", "failed"}:
            return
        existing = background_tasks.get(task_id)
        if existing and not existing.done():
            return
        task["execution_started"] = True
        background_tasks[task_id] = asyncio.create_task(run_task_background(task_id))

    def run_image_pipeline(task: dict) -> dict:
        if task.get("execution_state") in {"processing", "completed", "failed"}:
            return task
        task["execution_started"] = True
        task["execution_state"] = "processing"
        task["task_status"] = "processing"
        task["status"] = "processing"
        task["task_progress"] = max(int(task.get("task_progress") or 0), 10)
        try:
            result = process_v046_delivery(
                {
                    "input_path": Path(task["input_path"]),
                    "output_root": Path(task["output_root"]),
                    "mode": task["mode"],
                    "output_profile": task.get("output_profile") or "delivery_1080p",
                    "output_format": task["output_format"],
                    "debug_timing": task.get("debug_timing"),
                    "debug_keep_intermediate": False,
                    "color_stability_enabled": task.get("color_stability_enabled", True),
                    "color_correction_enabled": task.get("color_correction_enabled", False),
                }
            )
            final_path = Path(result["final_output_path"])
            output_file_index[final_path.name] = final_path
            task_result = update_task_result_output_meta(dict(result.get("task_result") or {}), task, final_path)
            task_report = dict(result.get("task_report") or empty_task_report())
            task.update(
                {
                    "task_status": "completed",
                    "status": "completed",
                    "execution_state": "completed",
                    "task_progress": 100,
                    "completed_at": datetime.now().isoformat(timespec="seconds"),
                    "output_path": final_path,
                    "enhancedUrl": public_file_url("outputs", final_path.name),
                    "final_output_url": public_file_url("outputs", final_path.name),
                    "main_output_url": None,
                    "optimized_output_url": None,
                    "final_output_exists": final_path.exists(),
                    "image_type": result.get("image_type") or task.get("image_type") or "unknown",
                    "degradation_type": result.get("degradation_type") or "unknown",
                    "task_result": task_result,
                    "task_report": task_report,
                    "error_message": "",
                    "output_directory": str(final_path.parent),
                    "output_directory_source": (task.get("output_dir_meta") or {}).get("output_dir_source") or "default",
                    "final_output_path": str(final_path),
                    "final_output_filename": final_path.name,
                    "final_delivery_status": result.get("final_delivery_status") or (result.get("debug_quality") or {}).get("final_delivery_status"),
                    "final_delivery_reason": result.get("final_delivery_reason") or (result.get("debug_quality") or {}).get("final_delivery_reason"),
                    "final_delivery_risk_level": result.get("final_delivery_risk_level") or (result.get("debug_quality") or {}).get("final_delivery_risk_level"),
                    "final_delivery_recommended_usage": result.get("final_delivery_recommended_usage") or (result.get("debug_quality") or {}).get("final_delivery_recommended_usage"),
                    "feedback_bundle_status": "",
                    "feedback_bundle_path": "",
                    "feedback_bundle_size": 0,
                    "feedback_bundle_redacted": True,
                    "feedback_bundle_error": "",
                    "input_width": result.get("input_width"),
                    "input_height": result.get("input_height"),
                    "output_width": result.get("output_width"),
                    "output_height": result.get("output_height"),
                    "resize_policy": task_result.get("resize_policy") or result.get("resize_policy"),
                    "was_upscaled": task_result.get("was_upscaled"),
                    "was_downscaled": task_result.get("was_downscaled"),
                    "input_size_bytes": result.get("input_size_bytes"),
                    "output_size": task_result.get("output_size"),
                    "output_format": task_result.get("output_format") or task.get("output_format"),
                    "output_changed": result.get("output_changed"),
                    "hash_equal": result.get("hash_equal"),
                    "pixel_diff_score": result.get("pixel_diff_score"),
                    "debug_timing": result.get("debug_timing"),
                    "debug_quality": result.get("debug_quality"),
                }
            )
        except Exception as exc:
            task.update(
                {
                    "task_status": "failed",
                    "status": "failed",
                    "execution_state": "failed",
                    "task_progress": 100,
                    "error_message": str(exc),
                    "task_error": str(exc),
                    "task_report": task.get("task_report") or empty_task_report(),
                    "completed_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
        return task

    async def stream_task_events(task_id: str, delay: float = 0.25):
        real_task_id = latest_task_id["value"] if task_id == DEFAULT_TASK_ID else task_id
        task = task_registry.get(real_task_id or "")
        if not task:
            yield format_sse_log(1, 2, f"任务不存在：{task_id}")
            yield format_sse_log(2, 2, "请先上传图片，再打开任务日志。", done=True)
            yield "data: [DONE]\n\n"
            return

        stage_logs = [
            "SSE CONNECTED /api/v1/tasks/{task_id}/stream",
            "读取前端上传的真实输入图片",
            "正在确认输出目录",
            "输出目录来源：{output_dir_source}",
            "输出目录验证通过，高清成品将保存至：{output_dir}",
            "完成图像类型检测与 1080P 输出尺寸规划",
            "完成退化类型检测：blur / jpeg_artifact / noise / low_resolution / mixed",
            "建立高光保护 mask：玻璃反光与过曝区域进入保护区",
            "压缩损伤修复：JPEG block 与高频断层开始清理",
            "Text Clarity Engine：检测疑似小字与说明区域",
            "Edge Safe Enhance：过滤随机噪点，仅保留真实结构边缘",
            "Structure Recovery：建筑线条、纹理与远景轮廓进入中频补偿",
            "Color Lock：输出色彩回归原图 Lab 色彩坐标",
            "1080P 输出完成：task_result 与 task_report 已生成",
        ]
        total = len(stage_logs)
        for index, message in enumerate(stage_logs, start=1):
            if index > 1:
                await asyncio.sleep(max(0.0, float(delay)))
            if task.get("task_status") not in {"completed", "failed"}:
                task["task_progress"] = min(99, int(round((index / total) * 100)))
            extra = {
                "task_id": task.get("task_id"),
                "task_status": task.get("task_status"),
                "task_progress": task.get("task_progress"),
            }
            yield format_sse_log(
                index,
                total,
                message.format(
                    task_id=task.get("task_id"),
                    output_dir_source=(task.get("output_dir_meta") or {}).get("output_dir_source", "default"),
                    output_dir=task.get("output_dir", ""),
                ),
                extra=extra,
            )

        deadline = time.perf_counter() + 180.0
        while task.get("task_status") not in {"completed", "failed"} and time.perf_counter() < deadline:
            await asyncio.sleep(0.25)
        if task.get("task_status") not in {"completed", "failed"}:
            task.update(
                {
                    "task_status": "failed",
                    "status": "failed",
                    "execution_state": "failed",
                    "task_progress": 100,
                    "error_message": "任务处理超时，SSE 已安全结束。",
                    "task_error": "任务处理超时，SSE 已安全结束。",
                    "task_report": task.get("task_report") or empty_task_report(),
                    "completed_at": datetime.now().isoformat(timespec="seconds"),
                }
            )

        final_payload = public_task(task)
        if task.get("task_status") == "failed":
            yield format_sse_log(
                total,
                total,
                f"任务失败：{task.get('error_message')}",
                done=True,
                extra={"task": final_payload, "task_status": "failed"},
            )
        else:
            yield format_sse_log(
                total,
                total,
                "任务完成：final_output 已生成，质量报告已写入任务结果。",
                done=True,
                extra={
                    "task": final_payload,
                    "task_result": task.get("task_result"),
                    "task_report": task.get("task_report"),
                    "outputUrl": task.get("final_output_url") or task.get("enhancedUrl"),
                },
            )
        yield "data: [DONE]\n\n"

    @app.get("/api/health")
    async def health():
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "message": "VisualMasterPro / 影界 V0.4 API 已就绪。",
            "data": {
                "version": "V0.4",
                "host": SERVER_HOST,
                "port": SERVER_PORT,
                "default_output_dir": str(output_formal_dir),
                "target_resolution": "1080P",
                "uploadEndpoint": "/api/upload",
                "taskEndpoint": "/api/v1/tasks/{task_id}",
                "streamEndpoint": "/api/v1/tasks/{task_id}/stream",
                "modes": ["fidelity", "texture", "text_safe"],
                "outputFormats": ["png", "jpg"],
            },
        }

    @app.post("/api/output/validate")
    async def validate_output(payload: dict = Body(default_factory=dict)):
        output_dir_value = payload.get("output_dir") if isinstance(payload, dict) else ""
        checked = validate_output_dir_value(output_dir_value, source_hint="request")
        return {
            "code": 200 if checked["valid"] else 400,
            "status": "success" if checked["valid"] else "error",
            "success": bool(checked["valid"]),
            "valid": bool(checked["valid"]),
            "exists": bool(checked["exists"]),
            "created": bool(checked["created"]),
            "writable": bool(checked["writable"]),
            "normalized_path": checked["normalized_path"],
            "message": checked["message"],
            "data": checked,
        }

    @app.post("/api/output/apply")
    async def apply_output(payload: dict = Body(default_factory=dict)):
        output_dir_value = payload.get("output_dir") if isinstance(payload, dict) else ""
        checked = validate_output_dir_value(output_dir_value, source_hint="request")
        if not checked["valid"]:
            return {
                "code": 400,
                "status": "error",
                "success": False,
                "valid": False,
                "message": checked["message"],
                "data": checked,
            }
        settings_data["last_output_dir"] = checked["normalized_path"]
        save_settings(settings_data)
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "valid": True,
            "message": "输出目录已应用。",
            "data": checked,
        }

    @app.post("/api/output/select-popup")
    async def select_output_popup():
        def ask_directory() -> str:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            try:
                root.attributes("-topmost", True)
            except Exception:
                pass
            try:
                selected = filedialog.askdirectory(title="选择雪原增强引擎高清成品输出文件夹")
            finally:
                root.destroy()
            return selected or ""

        try:
            selected_path = await asyncio.to_thread(ask_directory)
        except Exception as exc:
            return {
                "code": 400,
                "status": "error",
                "success": False,
                "message": f"打开本地文件夹选择器失败：{exc}",
                "output_dir": "",
                "data": {},
            }

        if not selected_path:
            return {
                "code": 200,
                "status": "cancelled",
                "success": True,
                "message": "已取消选择输出文件夹。",
                "output_dir": "",
                "data": {},
            }

        checked = validate_output_dir_value(selected_path, source_hint="request")
        if not checked["valid"]:
            return {
                "code": 400,
                "status": "error",
                "success": False,
                "message": checked["message"],
                "output_dir": "",
                "data": checked,
            }
        settings_data["last_output_dir"] = checked["normalized_path"]
        save_settings(settings_data)
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "message": "已选择输出文件夹。",
            "output_dir": checked["normalized_path"],
            "data": checked,
        }

    @app.post("/api/output/open")
    async def open_output(payload: dict = Body(default_factory=dict)):
        output_dir_value = payload.get("output_dir") if isinstance(payload, dict) else ""
        checked = resolve_output_dir_for_open(output_dir_value)
        if not checked["valid"]:
            return {
                "code": 400,
                "status": "error",
                "success": False,
                "message": checked["message"],
                "data": checked,
            }
        target = Path(checked["normalized_path"])
        if not target.exists() or not target.is_dir():
            return {
                "code": 400,
                "status": "error",
                "success": False,
                "message": "输出目录不存在或不是目录。",
                "data": checked,
            }
        if sys.platform != "win32":
            return {
                "code": 400,
                "status": "error",
                "success": False,
                "message": "当前系统不支持自动打开目录。",
                "data": checked,
            }
        try:
            os.startfile(str(target))  # noqa: S606 - Windows shell open for a validated directory only.
        except Exception as exc:
            return {
                "code": 400,
                "status": "error",
                "success": False,
                "message": f"打开输出目录失败：{exc}",
                "data": checked,
            }
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "message": "已打开输出目录。",
            "data": checked,
        }

    def beta_redact_text(value) -> str:
        text = "" if value is None else str(value)
        if not text:
            return ""
        home = str(Path.home())
        if home and text.lower().startswith(home.lower()):
            text = "%USERPROFILE%" + text[len(home) :]
        for sensitive, replacement in (
            (os.environ.get("USERNAME") or os.environ.get("USER") or "", "%USERNAME%"),
            (os.environ.get("COMPUTERNAME") or "", "%COMPUTERNAME%"),
        ):
            if sensitive:
                text = text.replace(sensitive, replacement)
        text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "%IPV4%", text)
        text = re.sub(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b", "%MAC%", text)
        return text

    def beta_redact_path(value) -> str:
        return beta_redact_text(value)

    def beta_tail_text(value, limit: int = 1200) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        return beta_redact_text(text[-limit:])

    def beta_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def beta_result_dict(value: object, output_dir_value: str | Path | None = None) -> dict:
        if isinstance(value, dict):
            return value
        return {
            "status": "failed",
            "verification_result": "FAILED",
            "stage": "BETA_RESULT_INVALID",
            "reason": "BETA_RESULT_INVALID",
            "error": "1080P安全增强 Beta 返回结果无效。",
            "error_message": f"invalid_result_type={type(value).__name__}",
            "processed_count": 0,
            "skipped_count": 0,
            "processed": [],
            "skipped": [],
            "output_dir": str(output_dir_value or "D:/影界文件/1080P安全增强输出"),
        }

    def beta_decode_selected_names(form) -> list[str]:
        encoded_names = ""
        try:
            encoded_names = str(form.get("selected_file_names_encoded") or "").strip()
        except Exception:
            encoded_names = ""
        if encoded_names:
            try:
                decoded_value = json.loads(urllib.parse.unquote(encoded_names))
                if isinstance(decoded_value, list):
                    names = [
                        safe_upload_name(str(value))
                        for value in decoded_value
                        if str(value or "").strip()
                    ]
                    if names:
                        return names
            except Exception as exc:
                beta_stage_log(
                    "BETA_SELECTED_NAME_DECODE_FAILED",
                    error_message=str(exc),
                )
        try:
            return [
                safe_upload_name(str(value))
                for value in form.getlist("selected_file_names")
                if str(value or "").strip()
            ]
        except Exception as exc:
            beta_stage_log(
                "BETA_SELECTED_NAME_DECODE_FAILED",
                error_message=str(exc),
            )
            return []

    def beta_stage_log(stage: str, **fields) -> None:
        event = {
            "stage": stage,
            "beta_run_id": fields.get("beta_run_id") or "",
            "input_path": beta_redact_path(fields.get("input_path")),
            "output_dir": beta_redact_path(fields.get("output_dir")),
            "current_file": fields.get("current_file") or "",
            "flat_output": bool(fields.get("flat_output")),
            "business_output": bool(fields.get("business_output")),
            "elapsed_seconds": fields.get("elapsed_seconds", ""),
            "returncode": fields.get("returncode", ""),
            "stderr_tail": beta_tail_text(fields.get("stderr_tail")),
            "error_message": beta_tail_text(fields.get("error_message")),
        }
        enqueue_beta_log("[SAFE_1080P_BETA] " + json.dumps(event, ensure_ascii=False))

    def beta_failure_response(
        result: dict | None,
        output_dir_value: str | Path | None = None,
        status_code: int = 200,
        code: int = 500,
    ) -> JSONResponse:
        result = beta_result_dict(result or {}, output_dir_value)
        skipped_items = result.get("skipped") if isinstance(result.get("skipped"), list) else []
        first_skip = skipped_items[0] if skipped_items and isinstance(skipped_items[0], dict) else {}
        skip_reason = first_skip.get("reason") or ""
        skip_file = first_skip.get("file") or result.get("failed_file") or ""
        stage = result.get("stage") or ("BETA_INPUT_SKIPPED" if skipped_items else "") or result.get("reason") or "BETA_FAILED"
        error = (
            result.get("error")
            or result.get("error_message")
            or (f"{skip_file} 被 1080P安全增强 Beta 安全策略跳过：{skip_reason}" if skip_reason else "")
            or result.get("reason")
            or "1080P safe enhance Beta failed."
        )
        beta_run_id = str(result.get("beta_run_id") or "")
        body = {
            "ok": False,
            "success": False,
            "status": "FAILED",
            "code": code,
            "beta_run_id": beta_run_id,
            "verification_result": "FAILED",
            "stage": stage,
            "error": beta_tail_text(error),
            "message": beta_tail_text(error),
            "processed_count": beta_int(result.get("processed_count"), 0),
            "skipped_count": beta_int(result.get("skipped_count"), 0),
            "enhanced_files": [],
            "results": [],
            "skipped": skipped_items,
            "output_dir": str(result.get("output_dir") or output_dir_value or ""),
            "data": result,
        }
        return JSONResponse(status_code=status_code, content=body)

    def beta_success_body(result: dict, verification_result: str) -> dict:
        result = beta_result_dict(result)
        beta_run_id = str(result.get("beta_run_id") or "")
        output_dir_value = result.get("output_dir") or ""
        output_dir_path = Path(str(output_dir_value)) if output_dir_value else Path()
        rows = []
        enhanced_files = []
        for item in result.get("processed") or []:
            if not isinstance(item, dict):
                continue
            input_name = item.get("input_name") or item.get("file") or ""
            raw_output = item.get("output_path") or item.get("enhanced") or ""
            output_path = Path(str(raw_output)) if raw_output else Path()
            if raw_output and not output_path.is_absolute() and output_dir_value:
                output_path = output_dir_path / output_path
            output_name = item.get("output_name") or (output_path.name if raw_output else "")
            output_path_text = str(output_path) if raw_output else ""
            if output_path_text:
                enhanced_files.append(output_path_text)
            rows.append(
                {
                    "input_name": input_name,
                    "output_name": output_name,
                    "output_path": output_path_text,
                }
            )
        result["results"] = rows
        result["enhanced_files"] = enhanced_files
        return {
            "ok": True,
            "success": True,
            "status": "SUCCESS",
            "code": 200,
            "beta_run_id": beta_run_id,
            "message": "1080P safe enhance Beta completed.",
            "verification_result": verification_result,
            "processed_count": beta_int(result.get("processed_count"), len(rows)),
            "skipped_count": beta_int(result.get("skipped_count"), 0),
            "enhanced_files": enhanced_files,
            "results": rows,
            "output_dir": str(output_dir_value),
            "data": result,
        }

    def run_safe_1080p_beta(payload: dict) -> dict:
        import importlib.util
        beta_started = time.perf_counter()
        beta_run_id = str((payload or {}).get("beta_run_id") or "")

        input_file_values = [
            Path(str(item)).expanduser()
            for item in ((payload or {}).get("input_files") or [])
            if str(item or "").strip()
        ]
        input_file_names = [item.name for item in input_file_values]
        beta_stage_log(
            "BETA_REQUEST_RECEIVED",
            input_path=(payload or {}).get("input_dir"),
            output_dir=(payload or {}).get("output_dir"),
            current_file=", ".join(input_file_names),
            flat_output=bool((payload or {}).get("flat_output")),
            business_output=bool((payload or {}).get("business_output")),
            elapsed_seconds=0,
            beta_run_id=beta_run_id,
        )
        beta_stage_log(
            "BETA_REQUEST_INPUT_FILES",
            input_path=(payload or {}).get("input_dir"),
            output_dir=(payload or {}).get("output_dir"),
            current_file=", ".join(input_file_names),
            flat_output=bool((payload or {}).get("flat_output")),
            business_output=bool((payload or {}).get("business_output")),
            elapsed_seconds=round(time.perf_counter() - beta_started, 3),
            beta_run_id=beta_run_id,
        )
        if not input_file_values:
            beta_stage_log(
                "BETA_FAILED",
                input_path=(payload or {}).get("input_dir"),
                output_dir=(payload or {}).get("output_dir"),
                flat_output=bool((payload or {}).get("flat_output")),
                business_output=bool((payload or {}).get("business_output")),
                elapsed_seconds=round(time.perf_counter() - beta_started, 3),
                error_message="BETA_INPUT_MISSING",
                beta_run_id=beta_run_id,
            )
            return {
                "ok": False,
                "success": False,
                "beta_run_id": beta_run_id,
                "status": "failed",
                "verification_result": "FAILED",
                "stage": "BETA_INPUT_MISSING",
                "reason": "BETA_INPUT_MISSING",
                "error": "未收到当前选择的输入文件，已拒绝使用默认测试样本",
                "error_message": "未收到当前选择的输入文件，已拒绝使用默认测试样本",
                "processed_count": 0,
                "skipped_count": 0,
                "processed": [],
                "skipped": [],
                "output_dir": str((payload or {}).get("output_dir") or "D:/影界文件/1080P安全增强输出"),
            }

        module_path = PROJECT_ROOT / "tools" / "experiments" / "safe_1080p_enhance.py"
        if not module_path.exists():
            beta_stage_log(
                "BETA_FAILED",
                input_path=(payload or {}).get("input_dir"),
                output_dir=(payload or {}).get("output_dir"),
                flat_output=bool((payload or {}).get("flat_output")),
                business_output=bool((payload or {}).get("business_output")),
                elapsed_seconds=round(time.perf_counter() - beta_started, 3),
                error_message="missing_safe_1080p_module",
                beta_run_id=beta_run_id,
            )
            return {
                "beta_run_id": beta_run_id,
                "status": "blocked",
                "verification_result": "BLOCKED",
                "reason": "missing_safe_1080p_module",
            }

        spec = importlib.util.spec_from_file_location("safe_1080p_enhance", module_path)
        if spec is None or spec.loader is None:
            beta_stage_log(
                "BETA_FAILED",
                input_path=(payload or {}).get("input_dir"),
                output_dir=(payload or {}).get("output_dir"),
                flat_output=bool((payload or {}).get("flat_output")),
                business_output=bool((payload or {}).get("business_output")),
                elapsed_seconds=round(time.perf_counter() - beta_started, 3),
                error_message="cannot_load_safe_1080p_module",
                beta_run_id=beta_run_id,
            )
            return {
                "beta_run_id": beta_run_id,
                "status": "blocked",
                "verification_result": "BLOCKED",
                "reason": "cannot_load_safe_1080p_module",
            }
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        input_dir_value = payload.get("input_dir") or str(input_file_values[0].parent)
        output_dir_value = payload.get("output_dir") or "D:/影界文件/1080P安全增强输出"
        mode_value = payload.get("mode") or "safe_1080p"
        if mode_value != "safe_1080p":
            beta_stage_log(
                "BETA_FAILED",
                input_path=input_dir_value,
                output_dir=output_dir_value,
                flat_output=bool(payload.get("flat_output")),
                business_output=bool(payload.get("business_output")),
                elapsed_seconds=round(time.perf_counter() - beta_started, 3),
                error_message="unsupported_beta_mode",
                beta_run_id=beta_run_id,
            )
            return {
                "beta_run_id": beta_run_id,
                "status": "blocked",
                "verification_result": "BLOCKED",
                "reason": "unsupported_beta_mode",
            }

        input_path = Path(str(input_dir_value)).expanduser()
        output_path = Path(str(output_dir_value)).expanduser()
        if not input_path.is_absolute():
            input_path = (PROJECT_ROOT / input_path).resolve()
        if not output_path.is_absolute():
            output_path = (PROJECT_ROOT / output_path).resolve()
        beta_stage_log(
            "BETA_INPUT_RESOLVED",
            input_path=input_path,
            output_dir=output_path,
            current_file=", ".join(input_file_names),
            flat_output=bool(payload.get("flat_output")),
            business_output=bool(payload.get("business_output")),
            elapsed_seconds=round(time.perf_counter() - beta_started, 3),
            beta_run_id=beta_run_id,
        )
        beta_stage_log(
            "BETA_RESOLVED_INPUT_FILES",
            input_path="; ".join(str(item.resolve()) for item in input_file_values),
            output_dir=output_path,
            current_file=", ".join(input_file_names),
            flat_output=bool(payload.get("flat_output")),
            business_output=bool(payload.get("business_output")),
            elapsed_seconds=round(time.perf_counter() - beta_started, 3),
            beta_run_id=beta_run_id,
        )
        beta_stage_log(
            "BETA_OUTPUT_DIR_RESOLVED",
            input_path=input_path,
            output_dir=output_path,
            current_file=", ".join(input_file_names),
            flat_output=bool(payload.get("flat_output")),
            business_output=bool(payload.get("business_output")),
            elapsed_seconds=round(time.perf_counter() - beta_started, 3),
            beta_run_id=beta_run_id,
        )

        def beta_run_stage_log(stage: str, **fields) -> None:
            fields.setdefault("beta_run_id", beta_run_id)
            beta_stage_log(stage, **fields)

        args = argparse.Namespace(
            input_dir=input_path,
            output_dir=output_path,
            mode="safe_1080p",
            tool_dir=PROJECT_ROOT / "external_tools" / "realesrgan-ncnn-vulkan",
            model="realesrgan-x4plus",
            scale="4",
            flat_output=True,
            business_output=True,
            timeout_seconds=300,
            stage_logger=beta_run_stage_log,
            diagnostic_dir=Path("D:/影界文件/影界测试反馈包"),
            input_files=[item.resolve() for item in input_file_values],
        )
        result = beta_result_dict(module.process(args), output_path)
        result["beta_run_id"] = beta_run_id
        processed_count = beta_int(result.get("processed_count"), 0)
        skipped_count = beta_int(result.get("skipped_count"), 0)
        if result.get("status") != "ok" or processed_count <= 0:
            if not result.get("verification_result"):
                result["verification_result"] = "FAILED" if result.get("status") == "failed" else "BLOCKED"
            beta_stage_log(
                "BETA_RESPONSE_READY",
                input_path=input_path,
                output_dir=output_path,
                current_file=result.get("failed_file") or "",
                flat_output=True,
                business_output=True,
                elapsed_seconds=round(time.perf_counter() - beta_started, 3),
                returncode=result.get("returncode", ""),
                stderr_tail=result.get("stderr_tail", ""),
                error_message=result.get("error_message") or result.get("reason") or result.get("status"),
                beta_run_id=beta_run_id,
            )
            return result

        result["verification_result"] = "PASS_WITH_NOTES" if skipped_count else "PASS"
        result["beta_policy"] = {
            "mode": "safe_1080p",
            "strategy": "35% protected",
            "scope": "Chinese commercial non-portrait visuals only",
            "main_pipeline": False,
        }
        beta_stage_log(
            "BETA_RESPONSE_READY",
            input_path=input_path,
            output_dir=output_path,
            current_file=(result.get("processed") or [{}])[-1].get("file") if result.get("processed") else "",
            flat_output=True,
            business_output=True,
            elapsed_seconds=round(time.perf_counter() - beta_started, 3),
            beta_run_id=beta_run_id,
        )
        return result

    @app.post("/api/beta/safe-1080p/enhance")
    async def beta_safe_1080p_enhance(request: Request):
        payload: dict = {}
        temp_context = None
        output_dir_value = "D:/影界文件/1080P安全增强输出"
        beta_run_id = ""
        try:
            content_type = request.headers.get("content-type", "").lower()
            if "multipart/form-data" in content_type:
                form = await request.form()
                beta_run_id = str(form.get("beta_run_id") or "")
                beta_stage_log(
                    "BETA_API_REQUEST_RECEIVED",
                    output_dir=str(form.get("output_dir") or output_dir_value),
                    flat_output=parse_bool_value(form.get("flat_output"), True),
                    business_output=parse_bool_value(form.get("business_output"), True),
                    beta_run_id=beta_run_id,
                )
                beta_stage_log(
                    "BETA_API_FORM_FIELDS",
                    output_dir=str(form.get("output_dir") or output_dir_value),
                    current_file=str(form.get("selected_file_names") or ""),
                    flat_output=parse_bool_value(form.get("flat_output"), True),
                    business_output=parse_bool_value(form.get("business_output"), True),
                    beta_run_id=beta_run_id,
                )
                temp_context = tempfile.TemporaryDirectory(prefix="safe_1080p_beta_selected_")
                temp_input_dir = Path(temp_context.name)
                temp_input_dir.mkdir(parents=True, exist_ok=True)
                input_files: list[str] = []
                selected_names: list[str] = []
                declared_names = beta_decode_selected_names(form)
                beta_stage_log(
                    "BETA_API_FILES_RECEIVED",
                    input_path=temp_input_dir,
                    output_dir=str(form.get("output_dir") or output_dir_value),
                    current_file=", ".join(declared_names),
                    flat_output=parse_bool_value(form.get("flat_output"), True),
                    business_output=parse_bool_value(form.get("business_output"), True),
                    beta_run_id=beta_run_id,
                )
                file_index = 0
                for key, value in form.multi_items():
                    if hasattr(value, "filename") and hasattr(value, "read"):
                        upload_name = declared_names[file_index] if file_index < len(declared_names) else safe_upload_name(getattr(value, "filename", None))
                        file_index += 1
                        selected_names.append(upload_name)
                        saved_path = temp_input_dir / upload_name
                        try:
                            raw = await value.read()
                        except Exception as exc:
                            raise RuntimeError(f"BETA_MULTIPART_FILE_READ_FAILED: {upload_name}: {exc}") from exc
                        if raw:
                            try:
                                saved_path.write_bytes(raw)
                            except Exception as exc:
                                raise RuntimeError(f"BETA_MULTIPART_FILE_SAVE_FAILED: {upload_name}: {exc}") from exc
                            if not saved_path.exists() or not saved_path.is_file():
                                raise RuntimeError(f"BETA_MULTIPART_TEMP_FILE_MISSING: {upload_name}")
                            input_files.append(str(saved_path))
                    else:
                        payload[key] = value
                output_dir_value = payload.get("output_dir") or output_dir_value
                beta_run_id = str(payload.get("beta_run_id") or beta_run_id)
                payload.update(
                    {
                        "beta_run_id": beta_run_id,
                        "input_dir": str(temp_input_dir),
                        "input_files": input_files,
                        "selected_file_names": selected_names,
                        "flat_output": parse_bool_value(payload.get("flat_output"), True),
                        "business_output": parse_bool_value(payload.get("business_output"), True),
                        "mode": payload.get("mode") or "safe_1080p",
                        "output_dir": output_dir_value,
                    }
                )
                beta_stage_log(
                    "BETA_API_INPUT_FILES_RESOLVED",
                    input_path="; ".join(input_files),
                    output_dir=output_dir_value,
                    current_file=", ".join(selected_names),
                    flat_output=payload["flat_output"],
                    business_output=payload["business_output"],
                    beta_run_id=beta_run_id,
                )
            else:
                try:
                    payload = await request.json()
                except Exception:
                    payload = {}
                payload = payload if isinstance(payload, dict) else {}
                output_dir_value = payload.get("output_dir") or output_dir_value
                beta_run_id = str(payload.get("beta_run_id") or "")
                beta_stage_log(
                    "BETA_API_REQUEST_RECEIVED",
                    input_path=payload.get("input_dir"),
                    output_dir=output_dir_value,
                    current_file=", ".join([Path(str(item)).name for item in payload.get("input_files") or []]),
                    flat_output=bool(payload.get("flat_output")),
                    business_output=bool(payload.get("business_output")),
                    beta_run_id=beta_run_id,
                )
                beta_stage_log(
                    "BETA_API_FORM_FIELDS",
                    input_path=payload.get("input_dir"),
                    output_dir=output_dir_value,
                    current_file=", ".join([Path(str(item)).name for item in payload.get("input_files") or []]),
                    flat_output=bool(payload.get("flat_output")),
                    business_output=bool(payload.get("business_output")),
                    beta_run_id=beta_run_id,
                )
                beta_stage_log(
                    "BETA_API_INPUT_FILES_RESOLVED",
                    input_path="; ".join([str(item) for item in payload.get("input_files") or []]),
                    output_dir=output_dir_value,
                    current_file=", ".join([Path(str(item)).name for item in payload.get("input_files") or []]),
                    flat_output=bool(payload.get("flat_output")),
                    business_output=bool(payload.get("business_output")),
                    beta_run_id=beta_run_id,
                )
            beta_stage_log(
                "BETA_API_ENHANCE_START",
                input_path=(payload or {}).get("input_dir"),
                output_dir=(payload or {}).get("output_dir"),
                current_file=", ".join([Path(str(item)).name for item in (payload or {}).get("input_files") or []]),
                flat_output=bool((payload or {}).get("flat_output")),
                business_output=bool((payload or {}).get("business_output")),
                beta_run_id=beta_run_id,
            )
            result = await asyncio.to_thread(run_safe_1080p_beta, payload if isinstance(payload, dict) else {})
            beta_stage_log(
                "BETA_API_ENHANCE_DONE",
                input_path=(payload or {}).get("input_dir"),
                output_dir=(payload or {}).get("output_dir"),
                current_file=", ".join([Path(str(item)).name for item in (payload or {}).get("input_files") or []]),
                flat_output=bool((payload or {}).get("flat_output")),
                business_output=bool((payload or {}).get("business_output")),
                beta_run_id=beta_run_id,
                error_message=(result or {}).get("error_message") or (result or {}).get("reason") or "",
            )
        except Exception as exc:
            beta_stage_log(
                "BETA_API_FAILED",
                input_path=(payload or {}).get("input_dir") if isinstance(payload, dict) else "",
                output_dir=(payload or {}).get("output_dir") if isinstance(payload, dict) else "",
                flat_output=bool((payload or {}).get("flat_output")) if isinstance(payload, dict) else False,
                business_output=bool((payload or {}).get("business_output")) if isinstance(payload, dict) else False,
                error_message=str(exc),
                beta_run_id=beta_run_id,
            )
            result = {
                "beta_run_id": beta_run_id,
                "status": "failed",
                "verification_result": "FAILED",
                "reason": "beta_api_exception",
                "error_message": beta_tail_text(str(exc)),
            }
        finally:
            if temp_context is not None:
                temp_context.cleanup()
        result = beta_result_dict(result, output_dir_value)
        result["beta_run_id"] = result.get("beta_run_id") or beta_run_id
        verification_result = result.get("verification_result") or "BLOCKED"
        success = verification_result in {"PASS", "PASS_WITH_NOTES"}
        if not success:
            beta_stage_log(
                "BETA_API_RESPONSE_READY",
                input_path=(payload or {}).get("input_dir") if isinstance(payload, dict) else "",
                output_dir=output_dir_value,
                current_file=", ".join([Path(str(item)).name for item in (payload or {}).get("input_files") or []]) if isinstance(payload, dict) else "",
                flat_output=bool((payload or {}).get("flat_output")) if isinstance(payload, dict) else False,
                business_output=bool((payload or {}).get("business_output")) if isinstance(payload, dict) else False,
                beta_run_id=beta_run_id,
                error_message=result.get("error_message") or result.get("reason") or result.get("stage") or "",
            )
            return beta_failure_response(result, output_dir_value, 200, 500)
        beta_stage_log(
            "BETA_API_RESPONSE_READY",
            input_path=(payload or {}).get("input_dir") if isinstance(payload, dict) else "",
            output_dir=output_dir_value,
            current_file=", ".join([Path(str(item)).name for item in (payload or {}).get("input_files") or []]) if isinstance(payload, dict) else "",
            flat_output=bool((payload or {}).get("flat_output")) if isinstance(payload, dict) else False,
            business_output=bool((payload or {}).get("business_output")) if isinstance(payload, dict) else False,
            beta_run_id=beta_run_id,
        )
        return beta_success_body(result, verification_result)

    @app.post("/api/beta/safe-1080p/output-status")
    async def beta_safe_1080p_output_status(payload: dict = Body(default_factory=dict)):
        payload = payload if isinstance(payload, dict) else {}
        beta_run_id = str(payload.get("beta_run_id") or "")
        output_dir_value = payload.get("output_dir") or "D:/影界文件/1080P安全增强输出"
        output_dir = Path(str(output_dir_value)).expanduser()
        selected_names_raw = payload.get("selected_file_names") or payload.get("files") or []
        if isinstance(selected_names_raw, str):
            selected_names = [selected_names_raw]
        else:
            selected_names = [str(item) for item in selected_names_raw if str(item or "").strip()]
        results: list[dict[str, str]] = []
        if output_dir.exists() and output_dir.is_dir():
            for selected_name in selected_names:
                safe_name = safe_upload_name(selected_name)
                stem = Path(safe_name).stem
                candidates = sorted(output_dir.glob(f"{stem}_1080p_beta*.png"), key=lambda item: item.stat().st_mtime, reverse=True)
                if candidates:
                    output_path = candidates[0]
                    results.append(
                        {
                            "input_name": safe_name,
                            "output_name": output_path.name,
                            "output_path": str(output_path),
                        }
                    )
        found = bool(results)
        return {
            "ok": found,
            "success": True,
            "status": "SUCCESS" if found else "PENDING",
            "code": 200,
            "beta_run_id": beta_run_id,
            "found": found,
            "verification_result": "PASS" if found else "PENDING",
            "processed_count": len(results),
            "skipped_count": 0,
            "results": results,
            "enhanced_files": [row["output_path"] for row in results],
            "output_dir": str(output_dir),
        }

    @app.post("/api/beta/safe-1080p/feedback-package")
    async def beta_safe_1080p_feedback_package(payload: dict = Body(default_factory=dict)):
        from engine.diagnostics.safe_1080p_feedback_package import generate_safe_1080p_feedback_package

        payload = payload if isinstance(payload, dict) else {}
        try:
            run_result = payload.get("run_result") if isinstance(payload.get("run_result"), dict) else None
            if not run_result:
                run_result = await asyncio.to_thread(run_safe_1080p_beta, payload)
            feedback_dir_value = payload.get("feedback_dir") or None
            feedback_dir = Path(str(feedback_dir_value)).expanduser() if feedback_dir_value else None
            package = await asyncio.to_thread(
                generate_safe_1080p_feedback_package,
                run_result,
                PROJECT_ROOT,
                feedback_dir,
            )
        except Exception as exc:
            package = {
                "feedback_bundle_status": "BLOCKED",
                "feedback_zip_path": "",
                "feedback_bundle_error": str(exc),
                "problem_code": "FAILED_FEEDBACK_ZIP",
                "problem_stage": "反馈包生成",
                "entries": [],
            }
        success = package.get("feedback_bundle_status") in {"PASS", "PASS_WITH_NOTES"}
        return {
            "code": 200 if success else 400,
            "status": "success" if success else "blocked",
            "success": success,
            "message": "Diagnostic feedback package exported." if success else "Diagnostic feedback package blocked.",
            "data": package,
        }

    @app.post("/api/upload")
    async def upload_file(
        file: UploadFile = File(...),
        mode: str = Form("fidelity"),
        scale: str = Form("2"),
        output_dir: str | None = Form(None),
        output_profile: str | None = Form(None),
        output_format: str | None = Form(None),
        format: str | None = Form(None),
        color_correction_enabled: bool = Form(False),
    ):
        task_id = make_task_id()
        mode_value = safe_mode(mode)
        requested_output_format = parse_output_format(output_format or format or settings_data.get("default_output_format"))
        output_root, output_dir_meta = resolve_output_dir(output_dir)
        print(
            "[VisualMasterPro output_dir] upload",
            {
                "task_id": task_id,
                "requested_output_dir": output_dir,
                "resolved_output_dir": str(output_root),
                "output_dir_source": output_dir_meta.get("output_dir_source"),
                "used_custom_output_dir": output_dir_meta.get("used_custom_output_dir"),
            },
        )

        receive_start = time.perf_counter()
        raw = await file.read()
        receive_file_time = round(time.perf_counter() - receive_start, 6)
        if not raw:
            raise HTTPException(status_code=400, detail="上传图片为空。")

        upload_name = safe_upload_name(file.filename)
        saved_path = unique_input_path(upload_name)
        save_start = time.perf_counter()
        try:
            saved_path.write_bytes(raw)
        except Exception as exc:
            fallback_input_dir = PROJECT_ROOT / "runtime" / "v04_inputs"
            fallback_input_dir.mkdir(parents=True, exist_ok=True)
            saved_path = fallback_input_dir / f"{task_id}_original_{upload_name}"
            try:
                saved_path.write_bytes(raw)
            except Exception as fallback_exc:
                raise HTTPException(status_code=500, detail=f"输入文件写入失败：{exc}；备用缓存也失败：{fallback_exc}") from fallback_exc
        save_input_time = round(time.perf_counter() - save_start, 6)

        try:
            output_plan = build_output_plan(
                saved_path,
                output_root,
                "delivery_1080p",
                requested_output_format,
                False,
                mode=mode_value,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"图片解码或输出规划失败：{exc}") from exc

        expected_output_path = output_plan["paths"]["final"]
        input_size_bytes = saved_path.stat().st_size
        input_hash = sha256_file(saved_path)
        created_at = datetime.now().isoformat(timespec="seconds")
        task = {
            "task_id": task_id,
            "taskId": task_id,
            "task_status": "pending",
            "status": "pending",
            "task_progress": 0,
            "mode": mode_value,
            "target_resolution": "1080P",
            "output_profile": output_profile or "delivery_1080p",
            "image_type": output_plan.get("image_type") or "unknown",
            "degradation_type": "unknown",
            "task_result": None,
            "task_report": empty_task_report(),
            "error_message": "",
            "created_at": created_at,
            "completed_at": None,
            "fileName": saved_path.name,
            "input_dir": str(saved_path.parent),
            "input_filename": saved_path.name,
            "original_filename": upload_name,
            "input_path": saved_path,
            "output_root": output_root,
            "output_dir": str(output_root),
            "output_directory": str(output_root),
            "output_directory_source": output_dir_meta.get("output_dir_source") or "default",
            "output_dir_meta": output_dir_meta,
            "expected_output_path": expected_output_path,
            "output_format": requested_output_format,
            "color_stability_enabled": True,
            "color_correction_enabled": bool(color_correction_enabled),
            "input_size_bytes": input_size_bytes,
            "input_hash": input_hash,
            "input_width": output_plan.get("input_width"),
            "input_height": output_plan.get("input_height"),
            "output_width": output_plan.get("output_width"),
            "output_height": output_plan.get("output_height"),
            "resize_policy": output_plan.get("resize_policy"),
            "was_upscaled": output_plan.get("was_upscaled"),
            "was_downscaled": output_plan.get("was_downscaled"),
            "scale": parse_scale_value(scale),
            "debug_timing": {
                "receive_file_time": receive_file_time,
                "save_input_time": save_input_time,
            },
        }
        task_registry[task_id] = task
        task_registry[DEFAULT_TASK_ID] = task
        latest_task_id["value"] = task_id
        upload_file_index[saved_path.name] = saved_path
        output_file_index[expected_output_path.name] = expected_output_path
        ensure_task_started(task)

        data = public_task(task)
        return {
            "code": 200,
            "status": "success",
            "success": True,
            "message": "图片上传完成，已登记为 V0.4 后台处理任务。",
            "filename": saved_path.name,
            "url": data["originalUrl"],
            "task_id": task_id,
            "taskId": task_id,
            "streamEndpoint": data["streamEndpoint"],
            "data": data,
        }

    @app.get("/api/stream")
    async def stream_latest(delay: float = 0.25):
        return StreamingResponse(
            stream_task_events(latest_task_id["value"] or DEFAULT_TASK_ID, delay),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    @app.get("/api/v1/tasks/{task_id}/stream")
    async def stream(task_id: str, delay: float = 0.25):
        return StreamingResponse(
            stream_task_events(task_id, delay),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    @app.get("/api/file/{kind}/{filename:path}")
    async def serve_file(kind: str, filename: str):
        return FileResponse(resolve_public_file(kind, filename))

    @app.post("/api/v1/tasks/{task_id}/feedback-bundle")
    async def feedback_bundle(task_id: str):
        real_task_id = latest_task_id["value"] if task_id == DEFAULT_TASK_ID else task_id
        task = task_registry.get(real_task_id or "")
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在。")
        bundle = generate_feedback_bundle(real_task_id or task_id, task)
        task.update(bundle)
        return {
            "code": 200 if bundle["feedback_bundle_status"] == "PASS" else 500,
            "status": "success" if bundle["feedback_bundle_status"] == "PASS" else "error",
            "success": bundle["feedback_bundle_status"] == "PASS",
            "data": bundle,
        }

    @app.get("/api/v1/tasks/{task_id}/feedback-bundle")
    async def feedback_bundle_get(task_id: str):
        return await feedback_bundle(task_id)

    @app.get("/api/v1/tasks/{task_id}")
    async def task_status(task_id: str):
        real_task_id = latest_task_id["value"] if task_id == DEFAULT_TASK_ID else task_id
        task = task_registry.get(real_task_id or "")
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在。")
        return {"code": 200, "status": "success", "success": True, "data": public_task(task)}

    return app


def run_server(host: str = SERVER_HOST, port: int = SERVER_PORT, debug: bool = False) -> int:
    import uvicorn

    print(f"{APP_VERSION} Web API 服务启动中...")
    print(f"监听地址：http://{host}:{port}")
    print("上传接口：POST /api/upload")
    print(f"SSE接口：GET /api/v1/tasks/{DEFAULT_TASK_ID}/stream")
    uvicorn.run(build_web_app(), host=host, port=port, log_level="debug" if debug else "info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="VisualMasterPro",
        description="VisualMasterPro V0.4 1080P 稳定交付系统。",
    )
    parser.add_argument("input_path", nargs="?", help="兼容旧命令的输入图片或文件夹。")
    parser.add_argument("output_dir", nargs="?", help="兼容旧命令的输出文件夹。")
    parser.add_argument("--input", dest="input_option", help="输入图片或图片文件夹。")
    parser.add_argument("--output", dest="output_option", help="输出文件夹。")
    parser.add_argument("--gui", action="store_true", help="启动 VisualMasterPro V0.4 图形化界面。")
    parser.add_argument("--server", action="store_true", help="启动 Web API 服务，监听 http://localhost:8787。")
    parser.add_argument("--host", default=SERVER_HOST, help="Web API 监听主机，默认 localhost。")
    parser.add_argument("--port", type=int, default=SERVER_PORT, help="Web API 监听端口，默认 8787。")
    parser.add_argument("--mode", default=AUTO_MODE, choices=SUPPORTED_MODES, help="增强模式，默认 fidelity。")
    parser.add_argument("--report", default=None, choices=["both", "json", "md", "markdown", "none"], help="调试报告格式。")
    parser.add_argument("--scale", type=int, default=2, choices=[2, 4], help="放大倍率，默认 2。")
    parser.add_argument("--format", dest="output_format", default="png", choices=["png", "jpg", "jpeg"], help="输出格式，默认 png。")
    parser.add_argument("--debug", action="store_true", help="输出开发调试文件。")
    parser.add_argument("--developer", action="store_true", help="等同于 --debug。")
    parser.add_argument("--pause", action="store_true", help="退出前暂停，适合 EXE 双击调试。")
    return parser


def resolve_paths(args):
    input_value = args.input_option or args.input_path
    output_value = args.output_option or args.output_dir
    if input_value and output_value:
        return Path(input_value), Path(output_value)
    if not input_value and not output_value:
        return get_desktop_work_dirs()
    raise ValueError("input and output must be provided together.")


def run(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv and not is_pyinstaller():
        return run_server()

    if is_pyinstaller() and not argv:
        from gui.app import run_gui

        return run_gui()

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.gui:
        from gui.app import run_gui

        return run_gui()

    if args.server:
        return run_server(host=args.host, port=args.port, debug=args.debug)

    try:
        input_path, output_dir = resolve_paths(args)
    except ValueError as exc:
        parser.error(str(exc))

    print(f"{APP_VERSION}（雪原Ai增强引擎）")
    print("-----------------------------------")
    developer_mode = args.debug or args.developer
    report_format = args.report or ("both" if developer_mode else "none")
    print(f"请求模式：{args.mode}")
    print(f"报告格式：{report_format}")
    print(f"放大倍率：{args.scale}x")
    print(f"输出格式：{args.output_format}")
    print(f"输入位置：{input_path}")
    print(f"输出位置：{output_dir}")

    startup_status = run_startup_check(
        input_path=input_path,
        output_dir=output_dir,
        show_no_image_dialog=True,
    )
    if startup_status.input_path.is_dir() and not any(startup_status.input_path.iterdir()):
        print("未检测到待处理图片，已安全退出。")
        return 0

    if args.mode in {"fidelity", "text_safe", "ai_image_clean", "sharp_4k"}:
        from batch.batch_processor import process_batch

        results = process_batch(
            [input_path],
            output_dir,
            mode=args.mode,
            scale=args.scale,
            output_format=args.output_format,
            debug_output=developer_mode,
        )
        if not results:
            message = (
                "未检测到待处理图片。\n\n"
                "请将图片放入“输入图片”文件夹后重新运行。\n\n"
                f"输入图片目录：{input_path}\n"
                f"输出目录：{output_dir / 'images'}"
            )
            print(message)
            show_info_dialog("VisualMasterPro 提示", message)
            return 0
        for result in results:
            print(f"{'完成' if result.ok else '失败'}：{result.output or result.source}，{result.message}")
        return 0

    from engine.pipeline import process_path

    results = process_path(
        input_path=input_path,
        output_dir=output_dir,
        mode=args.mode,
        report=report_format,
        developer_mode=developer_mode,
    )

    if not results:
        message = (
            "未检测到待处理图片。\n\n"
            "请将图片放入“输入图片”文件夹后重新运行。\n\n"
            f"输入图片目录：{input_path}\n"
            f"输出目录：{output_dir / 'images'}"
        )
        print(message)
        show_info_dialog("VisualMasterPro 提示", message)
        return 0

    for result in results:
        if result.ok:
            print(f"完成：{result.output}")
            print(f"尺寸：{result.width}x{result.height}")
            print(f"使用模式：{result.mode}")
        else:
            print(f"跳过：{result.source}，原因：{result.message}")

    print("全部处理完成。")
    if args.pause:
        input("按回车键退出...")
    return 0


if __name__ == "__main__":
    install_global_exception_hook()
    try:
        raise SystemExit(run(sys.argv[1:]))
    except Exception as exc:
        raise SystemExit(handle_exception(exc))
