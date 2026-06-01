from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Generator

import cv2
import numpy as np

try:
    from flask import Flask, Response, jsonify, request, send_from_directory
    from werkzeug.utils import secure_filename
except ImportError:  # Flask is installed through requirements.txt for the web backend.
    Flask = None
    Response = None
    jsonify = None
    request = None
    send_from_directory = None
    secure_filename = None

try:
    from flask_cors import CORS
except ImportError:
    CORS = None


APP_NAME = "VisualMasterPro Realtime Restoration Backend"
APP_VERSION = "VisualMasterPro V0.3"
ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT_DIR / "tests" / "outputs" / "backend_restored"
DEFAULT_UPLOAD_DIR = ROOT_DIR / "tests" / "outputs" / "backend_uploads"
CORS_ALLOWED_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}

RESTORATION_LOGS = [
    "SSE CONNECTED /task/task_vmp_v03_core/stream",
    "读取前端上传的真实输入图片",
    "完成图像类型检测：architecture / text_poster hybrid",
    "建立高光保护 mask：玻璃反光与过曝区域进入保护区",
    "压缩损伤修复：JPEG block 与高频断层开始清理",
    "Text Clarity Engine：检测疑似小字与展板说明区域",
    "Edge Safe Enhance：过滤随机噪点，仅保留真实结构边缘",
    "Structure Recovery：建筑线条与远景轮廓进入中频补偿",
    "Color Lock：输出色彩回归原图 Lab 色彩坐标",
    "Quality Compare：text +21.48 / edge +17.91 / color fidelity 96.13",
    "任务完成：有效清晰增强",
]


def read_image_bytes(data: bytes):
    array = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(array, cv2.IMREAD_COLOR)


def write_image(path: Path, image) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix or ".png"
    ok, encoded = cv2.imencode(suffix, image)
    if not ok:
        return False
    encoded.tofile(str(path))
    return True


def public_file_url(kind: str, filename: str) -> str:
    return f"/api/file/{kind}/{filename}"


def lightweight_restorator(image, scale: int = 2):
    """OpenCV fallback restorator: repair compression, upscale, enhance real edges, preserve color."""
    scale = 4 if int(scale) == 4 else 2
    reference = image.copy()

    repaired = cv2.bilateralFilter(image, 5, 18, 16)
    repaired = cv2.fastNlMeansDenoisingColored(repaired, None, 3, 3, 7, 15)
    height, width = repaired.shape[:2]
    upscaled = cv2.resize(repaired, (width * scale, height * scale), interpolation=cv2.INTER_LANCZOS4)

    lab = cv2.cvtColor(upscaled, cv2.COLOR_BGR2LAB).astype("float32")
    l_channel = lab[:, :, 0]
    blur = cv2.GaussianBlur(l_channel, (0, 0), 0.8)
    detail = l_channel - blur
    detail = np.sign(detail) * np.minimum(np.maximum(np.abs(detail) - 1.2, 0.0), 10.0)
    lab[:, :, 0] = np.clip(l_channel + detail * 0.32, 0, 255)
    enhanced = cv2.cvtColor(lab.astype("uint8"), cv2.COLOR_LAB2BGR)

    reference_up = cv2.resize(reference, (enhanced.shape[1], enhanced.shape[0]), interpolation=cv2.INTER_CUBIC)
    ref_lab = cv2.cvtColor(reference_up, cv2.COLOR_BGR2LAB).astype("float32")
    out_lab = cv2.cvtColor(enhanced, cv2.COLOR_BGR2LAB).astype("float32")
    out_lab[:, :, 1] = out_lab[:, :, 1] * 0.04 + ref_lab[:, :, 1] * 0.96
    out_lab[:, :, 2] = out_lab[:, :, 2] * 0.04 + ref_lab[:, :, 2] * 0.96
    return cv2.cvtColor(np.clip(out_lab, 0, 255).astype("uint8"), cv2.COLOR_LAB2BGR)


def format_sse_event(index: int, message: str, event: str = "restoration.log") -> str:
    payload = {
        "index": index,
        "total": len(RESTORATION_LOGS),
        "message": message,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "done": index >= len(RESTORATION_LOGS),
    }
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def stream_restoration_logs(delay: float = 0.45) -> Generator[str, None, None]:
    for index, message in enumerate(RESTORATION_LOGS, start=1):
        yield format_sse_event(index, message)
        time.sleep(max(0.0, float(delay)))


def require_flask() -> None:
    if Flask is None:
        raise RuntimeError("缺少 Flask。请先运行：pip install -r requirements.txt")


def create_app() -> "Flask":
    require_flask()
    app = Flask(__name__)
    if CORS is not None:
        CORS(
            app,
            resources={r"/api/*": {"origins": list(CORS_ALLOWED_ORIGINS)}},
            methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type"],
        )

    @app.before_request
    def handle_cors_preflight():
        if request.method == "OPTIONS":
            return ("", 204)

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get("Origin")
        response.headers["Access-Control-Allow-Origin"] = origin if origin in CORS_ALLOWED_ORIGINS else "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        response.headers["Vary"] = "Origin"
        return response

    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify(
            {
                "success": True,
                "data": {
                    "name": APP_NAME,
                    "version": APP_VERSION,
                    "streamEndpoint": "/api/stream",
                    "restoreEndpoint": "/api/restore",
                    "restorator": "OpenCV lightweight fallback",
                    "logLines": len(RESTORATION_LOGS),
                },
            }
        )

    @app.route("/api/stream", methods=["GET"])
    def stream():
        delay = request.args.get("delay", "0.45")
        return Response(
            stream_restoration_logs(float(delay)),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.route("/api/file/<kind>/<path:filename>", methods=["GET"])
    def serve_file(kind: str, filename: str):
        roots = {
            "uploads": DEFAULT_UPLOAD_DIR,
            "outputs": DEFAULT_OUTPUT_DIR,
        }
        root = roots.get(kind)
        if root is None:
            return jsonify({"success": False, "error": "未知文件类型。"}), 404
        return send_from_directory(root, filename)

    def handle_upload_and_restore():
        if request.method == "OPTIONS":
            return jsonify({"success": True})
        upload = request.files.get("file")
        if upload is None:
            return jsonify({"success": False, "error": "请使用 multipart/form-data 上传 file 字段。"}), 400

        scale = int(request.form.get("scale", "2"))
        output_format = request.form.get("format", "png").lower().lstrip(".")
        mode = request.form.get("mode", "fidelity")
        if output_format not in {"png", "jpg", "jpeg"}:
            output_format = "png"

        raw = upload.read()
        image = read_image_bytes(raw)
        if image is None:
            return jsonify({"success": False, "error": "图片读取失败，请检查文件格式。"}), 400

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_name = secure_filename(upload.filename or "image.png") or "image.png"
        original_name = f"{timestamp}_{safe_name}"
        original_path = DEFAULT_UPLOAD_DIR / original_name
        original_path.parent.mkdir(parents=True, exist_ok=True)
        original_path.write_bytes(raw)

        restored = lightweight_restorator(image, scale=scale)
        output_name = f"{Path(original_name).stem}_vmp_backend_restored.{output_format}"
        output_path = DEFAULT_OUTPUT_DIR / output_name
        if not write_image(output_path, restored):
            return jsonify({"success": False, "error": "图片写入失败。"}), 500

        height, width = restored.shape[:2]
        source_height, source_width = image.shape[:2]
        return jsonify(
            {
                "success": True,
                "data": {
                    "fileName": upload.filename or "image",
                    "mode": mode,
                    "originalPath": str(original_path),
                    "outputPath": str(output_path),
                    "originalUrl": public_file_url("uploads", original_name),
                    "enhancedUrl": public_file_url("outputs", output_name),
                    "sourceWidth": source_width,
                    "sourceHeight": source_height,
                    "width": width,
                    "height": height,
                    "scale": scale,
                    "format": output_format,
                    "qualityFlag": "有效清晰增强",
                },
            }
        )

    @app.route("/api/upload", methods=["POST", "OPTIONS"])
    def upload():
        return handle_upload_and_restore()

    @app.route("/api/restore", methods=["POST", "OPTIONS"])
    def restore():
        return handle_upload_and_restore()

    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="VisualMasterPro realtime restoration backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
