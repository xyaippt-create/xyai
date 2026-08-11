from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path

import cv2 as cv
import numpy as np
import onnxruntime as ort
from PIL import Image

from .contracts import LocalRetouchResult


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "local_retouch" / "inpainting_lama_2025jan.onnx"
EXPECTED_MODEL_SHA256 = "7df918ac3921d3daf0aae1d219776cf0dc4e4935f035af81841b40adcf74fdf2"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_image(path: Path, flags: int) -> np.ndarray | None:
    """Decode through bytes so Windows Unicode paths remain supported."""
    try:
        encoded = np.frombuffer(Path(path).read_bytes(), dtype=np.uint8)
    except OSError:
        return None
    return cv.imdecode(encoded, flags)


def _write_png(path: Path, image: np.ndarray) -> None:
    encoded, buffer = cv.imencode(".png", image)
    if not encoded:
        raise RuntimeError("修整结果编码失败。")
    Path(path).write_bytes(buffer.tobytes())


def _context_box(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.where(mask > 0)
    if xs.size == 0 or ys.size == 0:
        raise ValueError("修整选区为空。")
    x1, x2 = int(xs.min()), int(xs.max()) + 1
    y1, y2 = int(ys.min()), int(ys.max()) + 1
    height, width = mask.shape
    side = min(max(256, 6 * max(x2 - x1, y2 - y1)), width, height)
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    left = max(0, min(width - side, cx - side // 2))
    top = max(0, min(height - side, cy - side // 2))
    return left, top, left + side, top + side


class LamaOnnxAdapter:
    """LaMa-specific runtime hidden behind the product-level retouch contract."""

    engine_id = "lama_onnx_2025jan"

    def __init__(self, model_path: Path | None = None) -> None:
        self.model_path = Path(model_path or DEFAULT_MODEL_PATH).resolve()
        self._session: ort.InferenceSession | None = None
        self._session_lock = threading.Lock()
        self._model_sha256: str | None = None

    def availability(self) -> dict[str, object]:
        if not self.model_path.is_file():
            return {"available": False, "engine_id": self.engine_id, "reason": "本地修整模型尚未就绪。"}
        actual_sha = self._model_sha256 or _sha256(self.model_path)
        self._model_sha256 = actual_sha
        if actual_sha != EXPECTED_MODEL_SHA256:
            return {"available": False, "engine_id": self.engine_id, "reason": "本地修整模型完整性校验失败。"}
        return {
            "available": True,
            "engine_id": self.engine_id,
            "runtime": f"onnxruntime {ort.__version__}",
            "provider": "CPUExecutionProvider",
            "model_sha256": actual_sha,
        }

    def _require_session(self) -> ort.InferenceSession:
        available = self.availability()
        if not available["available"]:
            raise RuntimeError(str(available["reason"]))
        with self._session_lock:
            if self._session is None:
                options = ort.SessionOptions()
                options.log_severity_level = 3
                options.intra_op_num_threads = max(1, min(8, os.cpu_count() or 1))
                self._session = ort.InferenceSession(
                    str(self.model_path),
                    sess_options=options,
                    providers=["CPUExecutionProvider"],
                )
        return self._session

    def process(self, source_path: Path, mask_path: Path, output_path: Path) -> LocalRetouchResult:
        source_path = Path(source_path).resolve()
        mask_path = Path(mask_path).resolve()
        output_path = Path(output_path).resolve()
        source = _read_image(source_path, cv.IMREAD_UNCHANGED)
        mask = _read_image(mask_path, cv.IMREAD_GRAYSCALE)
        if source is None or mask is None:
            raise ValueError("无法读取当前工作图或修整选区。")
        if source.shape[:2] != mask.shape[:2]:
            raise ValueError("修整选区尺寸与当前工作图不一致。")
        mask = np.where(mask >= 128, 255, 0).astype(np.uint8)
        mask_pixels = int(np.count_nonzero(mask))
        if mask_pixels == 0:
            raise ValueError("请先在图片上标记需要修整的区域。")

        if source.ndim == 2:
            color = cv.cvtColor(source, cv.COLOR_GRAY2BGR)
            alpha_channel = None
        elif source.shape[2] == 4:
            color = source[:, :, :3].copy()
            alpha_channel = source[:, :, 3].copy()
        else:
            color = source[:, :, :3].copy()
            alpha_channel = None

        x1, y1, x2, y2 = _context_box(mask)
        patch = color[y1:y2, x1:x2]
        patch_mask = mask[y1:y2, x1:x2]
        resized = cv.resize(patch, (512, 512), interpolation=cv.INTER_AREA)
        resized_mask = cv.resize(patch_mask, (512, 512), interpolation=cv.INTER_NEAREST)
        image_blob = resized.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
        mask_blob = (resized_mask[None, None] > 0).astype(np.float32)

        session = self._require_session()
        started = time.perf_counter()
        raw = session.run(None, {"image": image_blob, "mask": mask_blob})[0]
        inference_seconds = time.perf_counter() - started
        candidate_patch = np.clip(raw[0].transpose(1, 2, 0), 0, 255).astype(np.uint8)
        candidate_patch = cv.resize(candidate_patch, (x2 - x1, y2 - y1), interpolation=cv.INTER_CUBIC)
        candidate = color.copy()
        candidate[y1:y2, x1:x2] = candidate_patch

        feather_radius = 5
        kernel_size = feather_radius * 2 + 1
        kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (kernel_size, kernel_size))
        influence = cv.dilate(mask, kernel)
        soft = cv.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), 2.5)
        alpha = np.where(mask > 0, 1.0, soft)
        alpha[influence == 0] = 0.0
        alpha = alpha[:, :, None]
        blended = np.rint(color.astype(np.float32) * (1.0 - alpha) + candidate.astype(np.float32) * alpha)
        blended = np.clip(blended, 0, 255).astype(np.uint8)
        blended[influence == 0] = color[influence == 0]

        final = cv.merge((*cv.split(blended), alpha_channel)) if alpha_channel is not None else blended
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_name(f".{output_path.stem}.writing{output_path.suffix}")
        if temporary.exists():
            temporary.unlink()
        _write_png(temporary, final)
        try:
            with Image.open(temporary) as opened:
                opened.load()
                if opened.size != (source.shape[1], source.shape[0]):
                    raise RuntimeError("修整结果尺寸验证失败。")
            os.replace(temporary, output_path)
        finally:
            temporary.unlink(missing_ok=True)

        return LocalRetouchResult(
            engine_id=self.engine_id,
            output_path=output_path,
            width=source.shape[1],
            height=source.shape[0],
            format="PNG",
            mask_pixels=mask_pixels,
            inference_seconds=round(inference_seconds, 4),
            source_sha256=_sha256(source_path),
        )
