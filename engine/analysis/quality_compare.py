from __future__ import annotations

import cv2
import numpy as np

from engine.algorithms.text_clarity import detect_text_like_regions
from engine.analysis.edge_classifier import true_edge_mask
from engine.analysis.quality_metrics import compute_quality_metrics


def _resize_like(image: np.ndarray, target: np.ndarray) -> np.ndarray:
    if image.shape[:2] == target.shape[:2]:
        return image
    return cv2.resize(image, (target.shape[1], target.shape[0]), interpolation=cv2.INTER_CUBIC)


def _masked_laplacian_score(image: np.ndarray, mask: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    lap = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
    mask_f = mask.astype("float32")
    if mask_f.max() > 1:
        mask_f /= 255.0
    weight = float(mask_f.sum())
    if weight < 8:
        return float(lap.mean())
    return float((lap * mask_f).sum() / weight)


def _color_fidelity(reference: np.ndarray, enhanced: np.ndarray) -> float:
    ref = _resize_like(reference, enhanced)
    ref_lab = cv2.cvtColor(ref, cv2.COLOR_BGR2LAB).astype("float32")
    out_lab = cv2.cvtColor(enhanced, cv2.COLOR_BGR2LAB).astype("float32")
    chroma_delta = np.sqrt((ref_lab[:, :, 1] - out_lab[:, :, 1]) ** 2 + (ref_lab[:, :, 2] - out_lab[:, :, 2]) ** 2)
    score = 100.0 - float(np.clip(chroma_delta.mean() * 3.2, 0, 100))
    return round(score, 2)


def compare_quality(original: np.ndarray, enhanced: np.ndarray) -> dict[str, float | str | bool]:
    ref = _resize_like(original, enhanced)
    before = compute_quality_metrics(ref)
    after = compute_quality_metrics(enhanced)

    text_mask = detect_text_like_regions(ref)
    edge_mask = true_edge_mask(ref)
    before_text = _masked_laplacian_score(ref, text_mask)
    after_text = _masked_laplacian_score(enhanced, text_mask)
    before_edge = _masked_laplacian_score(ref, edge_mask)
    after_edge = _masked_laplacian_score(enhanced, edge_mask)

    clarity_gain = after["clarity_score"] - before["clarity_score"]
    text_gain = float(np.clip((after_text - before_text) / max(before_text, 1.0) * 100.0, -100.0, 100.0))
    edge_gain = float(np.clip((after_edge - before_edge) / max(before_edge, 1.0) * 100.0, -100.0, 100.0))
    structure_gain = after["structure_score"] - before["structure_score"]
    noise_delta = after["noise_score"] - before["noise_score"]
    color_score = _color_fidelity(original, enhanced)

    valid_gain = clarity_gain > 2.0 or text_gain > 3.0 or edge_gain > 3.0 or structure_gain > 2.0
    noise_not_worse = noise_delta <= 8.0
    color_ok = color_score >= 82.0
    pseudo_hd = not (valid_gain and noise_not_worse and color_ok)

    fidelity_score = float(np.clip(0.35 * color_score + 0.22 * max(0.0, 100.0 - max(noise_delta, 0.0)) + 0.23 * max(0.0, min(100.0, 50.0 + edge_gain)) + 0.20 * max(0.0, min(100.0, 50.0 + text_gain)), 0.0, 100.0))

    return {
        "clarity_score": round(after["clarity_score"], 2),
        "text_clarity_score": round(float(np.clip(50.0 + text_gain, 0.0, 100.0)), 2),
        "edge_quality_score": round(float(np.clip(50.0 + edge_gain, 0.0, 100.0)), 2),
        "structure_score": round(after["structure_score"], 2),
        "texture_score": round(after["texture_score"], 2),
        "noise_score": round(after["noise_score"], 2),
        "color_fidelity_score": color_score,
        "fidelity_score": round(fidelity_score, 2),
        "clarity_gain": round(float(clarity_gain), 2),
        "text_clarity_gain": round(text_gain, 2),
        "edge_quality_gain": round(edge_gain, 2),
        "structure_gain": round(float(structure_gain), 2),
        "noise_delta": round(float(noise_delta), 2),
        "is_pseudo_hd": bool(pseudo_hd),
        "quality_flag": "伪高清 / 无效增强" if pseudo_hd else "有效清晰增强",
    }
