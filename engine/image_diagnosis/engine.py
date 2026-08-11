from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .contracts import (
    DiagnosisImageAdapter,
    DiagnosisIssue,
    DiagnosisResult,
    RecommendedAction,
    SourceChangedDuringDiagnosisError,
)
from .pillow_opencv_adapter import PillowOpenCvDiagnosisAdapter


ISSUE_ORDER = (
    "resolution",
    "blur",
    "noise",
    "compression_artifacts",
    "exposure",
    "highlight_clipping",
    "shadow_blocking",
    "white_balance",
    "color_cast",
)
SEVERITY_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def _issue(
    status: str,
    severity: str,
    metrics: dict[str, Any],
    reason: str,
    *evidence: str,
) -> DiagnosisIssue:
    return DiagnosisIssue(
        status=status,
        severity=severity,
        metrics=metrics,
        evidence=[item for item in evidence if item],
        reason=reason,
    )


def _analysis_image(bgr: np.ndarray, max_dimension: int = 1600) -> tuple[np.ndarray, float]:
    height, width = bgr.shape[:2]
    scale = min(1.0, max_dimension / max(height, width))
    if scale == 1.0:
        return bgr, scale
    resized = cv2.resize(
        bgr,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )
    return resized, scale


def _diagnose_resolution(facts: dict[str, Any]) -> DiagnosisIssue:
    width = int(facts["width"])
    height = int(facts["height"])
    short_side = min(width, height)
    megapixels = float(facts["megapixels"])
    metrics = {"short_side_px": short_side, "megapixels": megapixels, "reference_short_side_px": 1080}
    if short_side < 480 or megapixels < 0.5:
        return _issue("detected", "high", metrics, "短边或总像素量明显低于高清处理参考范围。", f"短边为{short_side}px", f"总像素为{megapixels:.2f}MP")
    if short_side < 720 or megapixels < 1.0:
        return _issue("detected", "medium", metrics, "图片尺寸低于常规高清交付参考范围。", f"短边为{short_side}px", f"总像素为{megapixels:.2f}MP")
    if short_side < 1080 or megapixels < 2.0:
        return _issue("detected", "low", metrics, "图片尺寸接近但尚未达到1080P参考范围。", f"短边为{short_side}px", f"总像素为{megapixels:.2f}MP")
    return _issue("not_detected", "none", metrics, "图片尺寸未发现明显不足。", f"短边为{short_side}px", f"总像素为{megapixels:.2f}MP")


def _diagnose_blur(gray: np.ndarray, scale: float) -> DiagnosisIssue:
    laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(gx, gy)
    tenengrad_mean = float(np.mean(np.square(gradient)))
    gradient_p90 = float(np.percentile(gradient, 90))
    edge_density = float(np.mean(gradient >= 24.0))
    metrics = {
        "laplacian_variance": _round(laplacian_variance),
        "tenengrad_mean": _round(tenengrad_mean),
        "gradient_p90": _round(gradient_p90),
        "edge_density": _round(edge_density, 6),
        "analysis_scale": _round(scale, 6),
    }
    if gradient_p90 < 6.0 and laplacian_variance < 12.0:
        return _issue("indeterminate", "none", metrics, "画面本身缺少足够边缘与纹理，无法可靠区分平滑内容和失焦。", "有效纹理不足")
    if laplacian_variance < 35.0 or (laplacian_variance < 60.0 and edge_density < 0.04):
        return _issue("detected", "high", metrics, "归一化分析图的边缘响应明显偏低，存在显著模糊迹象。", f"拉普拉斯方差={laplacian_variance:.2f}", f"边缘占比={edge_density:.3f}")
    if laplacian_variance < 100.0:
        return _issue("detected", "medium", metrics, "清晰度指标低于D1保守阈值，存在可见模糊风险。", f"拉普拉斯方差={laplacian_variance:.2f}")
    return _issue("not_detected", "none", metrics, "清晰度指标未发现明显模糊。", f"拉普拉斯方差={laplacian_variance:.2f}")


def _diagnose_noise(gray: np.ndarray) -> DiagnosisIssue:
    gray32 = gray.astype(np.float32)
    residual = gray32 - cv2.GaussianBlur(gray32, (0, 0), 0.85)
    gx = cv2.Sobel(gray32, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray32, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(gx, gy)
    cutoff = min(18.0, float(np.percentile(gradient, 40)))
    flat_mask = gradient <= max(cutoff, 2.0)
    flat_ratio = float(np.mean(flat_mask))
    samples = residual[flat_mask] if np.count_nonzero(flat_mask) >= 128 else residual.reshape(-1)
    center = float(np.median(samples))
    noise_sigma = float(np.median(np.abs(samples - center)) * 1.4826)
    metrics = {"estimated_noise_sigma": _round(noise_sigma), "flat_region_ratio": _round(flat_ratio, 6)}
    if gray.size < 4096 or flat_ratio < 0.015:
        return _issue("indeterminate", "none", metrics, "有效平坦区域不足，无法可靠分离噪声和真实纹理。", f"平坦区域占比={flat_ratio:.3f}")
    if noise_sigma >= 9.0:
        return _issue("detected", "high", metrics, "平坦区域高频残差明显偏高，存在强噪声迹象。", f"估计噪声σ={noise_sigma:.2f}")
    if noise_sigma >= 5.0:
        return _issue("detected", "medium", metrics, "平坦区域高频残差超过保守阈值，存在噪声风险。", f"估计噪声σ={noise_sigma:.2f}")
    return _issue("not_detected", "none", metrics, "平坦区域未发现明显噪声。", f"估计噪声σ={noise_sigma:.2f}")


def _diagnose_compression(bgr: np.ndarray, facts: dict[str, Any]) -> DiagnosisIssue:
    if facts.get("format") != "JPEG":
        return _issue("not_applicable", "none", {"format": facts.get("format")}, "非JPEG输入，不执行JPEG块效应判断。", "该项仅适用于JPEG")
    sample = bgr[: min(2048, bgr.shape[0]), : min(2048, bgr.shape[1])]
    gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY).astype(np.float32)
    vertical = np.abs(np.diff(gray, axis=1))
    horizontal = np.abs(np.diff(gray, axis=0))
    boundary_v = np.arange(vertical.shape[1]) % 8 == 7
    boundary_h = np.arange(horizontal.shape[0]) % 8 == 7
    if not np.any(boundary_v) or not np.any(boundary_h):
        return _issue("indeterminate", "none", {"format": "JPEG"}, "图片尺寸过小，无法形成可靠的8像素块边界样本。", "块边界样本不足")
    boundary_mean = float((vertical[:, boundary_v].mean() + horizontal[boundary_h, :].mean()) / 2.0)
    interior_mean = float((vertical[:, ~boundary_v].mean() + horizontal[~boundary_h, :].mean()) / 2.0)
    ratio = boundary_mean / max(interior_mean, 0.25)
    excess = boundary_mean - interior_mean
    bytes_per_pixel = float(facts.get("bytes_per_pixel") or 0.0)
    metrics = {
        "block_boundary_ratio": _round(ratio),
        "block_boundary_excess": _round(excess),
        "bytes_per_pixel": _round(bytes_per_pixel),
    }
    if ratio >= 2.2 and excess >= 4.0:
        return _issue("detected", "high", metrics, "JPEG 8像素块边界差异显著高于块内差异，存在明显压缩损伤。", f"块边界比={ratio:.2f}", f"边界超额={excess:.2f}")
    if (ratio >= 1.55 and excess >= 2.0) or (bytes_per_pixel < 0.22 and ratio >= 1.25):
        return _issue("detected", "medium", metrics, "JPEG块边界或低码率指标超过保守阈值，存在压缩损伤风险。", f"块边界比={ratio:.2f}", f"每像素字节={bytes_per_pixel:.3f}")
    return _issue("not_detected", "none", metrics, "未发现明显JPEG块效应。", f"块边界比={ratio:.2f}")


def _tone_metrics(gray: np.ndarray) -> dict[str, float]:
    return {
        "mean_luminance": _round(float(np.mean(gray))),
        "median_luminance": _round(float(np.median(gray))),
        "p05_luminance": _round(float(np.percentile(gray, 5))),
        "p95_luminance": _round(float(np.percentile(gray, 95))),
        "highlight_ratio_245": _round(float(np.mean(gray >= 245)), 6),
        "clipped_highlight_ratio_250": _round(float(np.mean(gray >= 250)), 6),
        "shadow_ratio_12": _round(float(np.mean(gray <= 12)), 6),
        "blocked_shadow_ratio_5": _round(float(np.mean(gray <= 5)), 6),
    }


def _diagnose_exposure(metrics: dict[str, float]) -> DiagnosisIssue:
    mean = metrics["mean_luminance"]
    median = metrics["median_luminance"]
    shadows = metrics["shadow_ratio_12"]
    highlights = metrics["highlight_ratio_245"]
    if mean < 42 and median < 40 and shadows >= 0.35:
        return _issue("detected", "high", metrics, "整体亮度与中位亮度过低，且大面积进入深暗区。", f"平均亮度={mean:.1f}", f"深暗占比={shadows:.3f}")
    if mean < 62 and median < 58 and shadows >= 0.18:
        return _issue("detected", "medium", metrics, "整体亮度偏低并伴随较多深暗像素。", f"平均亮度={mean:.1f}")
    if mean > 218 and median > 220 and highlights >= 0.35:
        return _issue("detected", "high", metrics, "整体亮度与中位亮度过高，且大面积进入高光区。", f"平均亮度={mean:.1f}", f"高光占比={highlights:.3f}")
    if mean > 198 and median > 202 and highlights >= 0.18:
        return _issue("detected", "medium", metrics, "整体亮度偏高并伴随较多高光像素。", f"平均亮度={mean:.1f}")
    return _issue("not_detected", "none", metrics, "整体曝光未发现明显异常。", f"平均亮度={mean:.1f}", f"中位亮度={median:.1f}")


def _diagnose_highlights(metrics: dict[str, float]) -> DiagnosisIssue:
    clipped = metrics["clipped_highlight_ratio_250"]
    high = metrics["highlight_ratio_245"]
    if clipped >= 0.25:
        return _issue("detected", "high", metrics, "大量像素接近纯白，高光细节存在明显溢出风险。", f"近纯白占比={clipped:.3f}")
    if clipped >= 0.08 or high >= 0.18:
        return _issue("detected", "medium", metrics, "高光端聚集比例超过保守阈值。", f"近纯白占比={clipped:.3f}", f"高光占比={high:.3f}")
    return _issue("not_detected", "none", metrics, "未发现大面积高光溢出。", f"近纯白占比={clipped:.3f}")


def _diagnose_shadows(metrics: dict[str, float]) -> DiagnosisIssue:
    blocked = metrics["blocked_shadow_ratio_5"]
    dark = metrics["shadow_ratio_12"]
    if blocked >= 0.25:
        return _issue("detected", "high", metrics, "大量像素接近纯黑，暗部细节存在明显堵塞风险。", f"近纯黑占比={blocked:.3f}")
    if blocked >= 0.08 or dark >= 0.18:
        return _issue("detected", "medium", metrics, "暗部端聚集比例超过保守阈值。", f"近纯黑占比={blocked:.3f}", f"深暗占比={dark:.3f}")
    return _issue("not_detected", "none", metrics, "未发现大面积暗部堵塞。", f"近纯黑占比={blocked:.3f}")


def _diagnose_color(bgr: np.ndarray) -> tuple[DiagnosisIssue, DiagnosisIssue]:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32)
    maximum = np.max(rgb, axis=2)
    minimum = np.min(rgb, axis=2)
    luma = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    neutral_mask = (luma >= 32) & (luma <= 223) & ((maximum - minimum) <= 45)
    neutral_ratio = float(np.mean(neutral_mask))
    if np.count_nonzero(neutral_mask) < 256 or neutral_ratio < 0.01:
        metrics = {"neutral_candidate_ratio": _round(neutral_ratio, 6)}
        reason = "中性候选像素不足，无法可靠区分场景固有颜色与白平衡偏移。"
        issue = _issue("indeterminate", "none", metrics, reason, f"中性候选占比={neutral_ratio:.3f}")
        return issue, issue

    neutral_means = np.mean(rgb[neutral_mask], axis=0)
    spread = float(np.max(neutral_means) - np.min(neutral_means))
    dominant_index = int(np.argmax(neutral_means))
    dominant_channel = ("red", "green", "blue")[dominant_index]
    lab = cv2.cvtColor(np.clip(rgb, 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    mean_a = float(np.mean(lab[:, :, 1][neutral_mask]))
    mean_b = float(np.mean(lab[:, :, 2][neutral_mask]))
    cast_strength = float(np.hypot(mean_a - 128.0, mean_b - 128.0))
    metrics = {
        "neutral_candidate_ratio": _round(neutral_ratio, 6),
        "neutral_mean_rgb": [_round(value) for value in neutral_means],
        "neutral_channel_spread": _round(spread),
        "dominant_channel": dominant_channel,
        "lab_neutral_a": _round(mean_a),
        "lab_neutral_b": _round(mean_b),
        "cast_strength": _round(cast_strength),
    }
    if spread >= 24.0:
        white_balance = _issue("detected", "high", metrics, "中性候选区域通道差异明显，存在强白平衡偏移。", f"中性通道差={spread:.2f}", f"主导通道={dominant_channel}")
    elif spread >= 14.0:
        white_balance = _issue("detected", "medium", metrics, "中性候选区域通道差异超过保守阈值。", f"中性通道差={spread:.2f}", f"主导通道={dominant_channel}")
    else:
        white_balance = _issue("not_detected", "none", metrics, "中性候选区域未发现明显白平衡偏移。", f"中性通道差={spread:.2f}")

    if cast_strength >= 16.0:
        color_cast = _issue("detected", "high", metrics, "中性候选区域在Lab色度平面偏离中性点明显，存在强整体色偏。", f"色偏强度={cast_strength:.2f}")
    elif cast_strength >= 8.0:
        color_cast = _issue("detected", "medium", metrics, "中性候选区域在Lab色度平面偏离中性点，存在整体色偏风险。", f"色偏强度={cast_strength:.2f}")
    else:
        color_cast = _issue("not_detected", "none", metrics, "中性候选区域未发现明显整体色偏。", f"色偏强度={cast_strength:.2f}")
    return white_balance, color_cast


def _detected(issues: dict[str, DiagnosisIssue], key: str, minimum: str = "low") -> bool:
    issue = issues[key]
    return issue.status == "detected" and SEVERITY_RANK.get(issue.severity, 0) >= SEVERITY_RANK[minimum]


def _recommend(facts: dict[str, Any], issues: dict[str, DiagnosisIssue]) -> RecommendedAction:
    resolution = issues["resolution"]
    blur = issues["blur"]
    structure_risk = any(_detected(issues, key, "medium") for key in ("noise", "compression_artifacts"))
    highlight_problem = _detected(issues, "highlight_clipping", "medium")
    shadow_problem = _detected(issues, "shadow_blocking", "medium")
    tonal_clipping_problem = highlight_problem or shadow_problem
    color_problem = tonal_clipping_problem or any(
        _detected(issues, key, "medium") for key in ("white_balance", "color_cast", "exposure")
    )
    file_large = int(facts["file_size_bytes"]) >= 8 * 1024 * 1024 or (
        int(facts["file_size_bytes"]) >= 3 * 1024 * 1024 and float(facts["bytes_per_pixel"]) >= 3.5
    )
    actions: list[tuple[str, str]] = []
    clipping_labels = [
        label
        for detected, label in (
            (highlight_problem, "高光溢出"),
            (shadow_problem, "暗部堵塞"),
        )
        if detected
    ]
    clipping_reason = (
        f"检测到{'与'.join(clipping_labels)}；可建议曝光/色调校正，"
        "但已经发生像素剪切的区域可能无法完全恢复。"
        if clipping_labels
        else ""
    )
    if highlight_problem and shadow_problem:
        actions.append(("颜色校正", clipping_reason))
    if resolution.status == "detected" and resolution.severity == "high" and blur.status == "detected":
        actions.append(("4K高清增强", "分辨率明显不足且清晰度诊断同时检出模糊。"))
    elif resolution.status == "detected" and structure_risk:
        actions.append(("1080P安全增强", "尺寸不足且噪声或压缩损伤风险较高，应优先采用保守增强。"))
    elif resolution.status == "detected":
        actions.append(("1080P标准增强", "图片尺寸未达到1080P参考范围，且未检出需要转入安全增强的主要结构风险。"))
    elif blur.status == "detected" or structure_risk:
        actions.append(("1080P安全增强", "当前尺寸可用，但清晰度、噪声或压缩损伤需要保守处理。"))

    if color_problem:
        actions.append((
            "颜色校正",
            clipping_reason or "曝光、白平衡或整体色偏诊断存在明确异常。",
        ))
    if file_large:
        actions.append(("图片压缩", "文件体积或每像素字节量明显偏高，可在画质门禁下进行压缩。"))
    if not actions:
        return RecommendedAction("无需处理", [], ["D1主要诊断指标未发现需要进入正式处理链的明确问题。"])

    unique: list[tuple[str, str]] = []
    for action in actions:
        if action[0] not in {item[0] for item in unique}:
            unique.append(action)
    return RecommendedAction(
        primary_action=unique[0][0],
        secondary_actions=[item[0] for item in unique[1:]],
        reasons=[item[1] for item in unique],
    )


class ImageDiagnosisEngine:
    """D1 read-only diagnosis core. It never schedules or performs image processing."""

    engine_id = "hdde-image-diagnosis-engine-v1"

    def __init__(self, adapter: DiagnosisImageAdapter | None = None) -> None:
        self._adapter = adapter or PillowOpenCvDiagnosisAdapter()

    @property
    def adapter_id(self) -> str:
        return self._adapter.adapter_id

    def diagnose(self, source_path: Path) -> DiagnosisResult:
        decoded = self._adapter.decode(Path(source_path))
        analysis_bgr, scale = _analysis_image(decoded.bgr)
        gray = cv2.cvtColor(analysis_bgr, cv2.COLOR_BGR2GRAY)
        tone_metrics = _tone_metrics(gray)
        white_balance, color_cast = _diagnose_color(analysis_bgr)
        issues = {
            "resolution": _diagnose_resolution(decoded.image_facts),
            "blur": _diagnose_blur(gray, scale),
            "noise": _diagnose_noise(gray),
            "compression_artifacts": _diagnose_compression(decoded.bgr, decoded.image_facts),
            "exposure": _diagnose_exposure(tone_metrics),
            "highlight_clipping": _diagnose_highlights(tone_metrics),
            "shadow_blocking": _diagnose_shadows(tone_metrics),
            "white_balance": white_balance,
            "color_cast": color_cast,
        }
        if tuple(issues) != ISSUE_ORDER:
            raise RuntimeError("诊断项合同顺序异常。")

        stat_after = decoded.source_path.stat()
        sha_after = _sha256(decoded.source_path)
        unchanged = (
            stat_after.st_size == decoded.source_size_bytes
            and stat_after.st_mtime_ns == decoded.source_mtime_ns
            and sha_after == decoded.source_sha256
        )
        if not unchanged:
            raise SourceChangedDuringDiagnosisError("诊断期间源图片发生变化，结果已丢弃。")
        return DiagnosisResult(
            engine_id=self.engine_id,
            adapter_id=self.adapter_id,
            image_facts=decoded.image_facts,
            quality_issues=issues,
            recommended_action=_recommend(decoded.image_facts, issues),
            source_integrity={
                "sha256_before": decoded.source_sha256,
                "sha256_after": sha_after,
                "mtime_ns_before": decoded.source_mtime_ns,
                "mtime_ns_after": stat_after.st_mtime_ns,
                "size_bytes_before": decoded.source_size_bytes,
                "size_bytes_after": stat_after.st_size,
                "unchanged": True,
            },
        )
