from __future__ import annotations

import cv2
import numpy as np

from engine.analysis.edge_classifier import highlight_mask


def detect_text_like_regions(image):
    """Detect dense stroke-like regions without using OCR."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(grad_x, grad_y)
    mag_u8 = cv2.normalize(magnitude, None, 0, 255, cv2.NORM_MINMAX).astype("uint8")

    adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 17, 8)
    _, edge_binary = cv2.threshold(mag_u8, max(28, int(np.percentile(mag_u8, 72))), 255, cv2.THRESH_BINARY)
    micro_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, micro_kernel)
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, micro_kernel)
    micro_contrast = cv2.max(blackhat, tophat)
    _, micro_binary = cv2.threshold(
        micro_contrast,
        max(5, int(np.percentile(micro_contrast, 84))),
        255,
        cv2.THRESH_BINARY,
    )
    stroke = cv2.bitwise_or(cv2.bitwise_or(adaptive, edge_binary), micro_binary)

    horizontal = cv2.morphologyEx(stroke, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 2)), iterations=1)
    vertical = cv2.morphologyEx(stroke, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 7)), iterations=1)
    connected = cv2.bitwise_or(horizontal, vertical)
    density = cv2.blur(connected, (11, 5))
    _, dense = cv2.threshold(density, 34, 255, cv2.THRESH_BINARY)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(dense, 8)
    filtered = np.zeros_like(dense)
    image_area = gray.shape[0] * gray.shape[1]
    for label in range(1, num_labels):
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        width = int(stats[label, cv2.CC_STAT_WIDTH])
        height = int(stats[label, cv2.CC_STAT_HEIGHT])
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < 10 or area > image_area * 0.22:
            continue
        aspect = width / max(height, 1)
        fill = area / max(width * height, 1)
        looks_like_line = 0.12 <= fill <= 0.82 and (aspect >= 1.4 or height <= 42 or width <= 42)
        if looks_like_line:
            filtered[y : y + height, x : x + width] = 255

    fallback = cv2.morphologyEx(stroke, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 2)), iterations=1)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(fallback, 8)
    for label in range(1, num_labels):
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        width = int(stats[label, cv2.CC_STAT_WIDTH])
        height = int(stats[label, cv2.CC_STAT_HEIGHT])
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < 3 or area > image_area * 0.08:
            continue
        fill = area / max(width * height, 1)
        small_stroke = (
            2 <= height <= max(72, gray.shape[0] // 3)
            and 2 <= width <= max(180, gray.shape[1] // 2)
            and 0.04 <= fill <= 0.86
        )
        if small_stroke:
            filtered[y : y + height, x : x + width] = 255

    protected = cv2.bitwise_not(highlight_mask(image, value_threshold=218))
    filtered = cv2.bitwise_and(filtered, protected)
    filtered = cv2.morphologyEx(filtered, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)))
    if float(np.mean(filtered > 0)) > 0.42:
        filtered = cv2.bitwise_and(filtered, edge_binary)
    return cv2.GaussianBlur(filtered, (0, 0), 0.75).astype("float32") / 255.0


def enhance_text_regions(image, strength: float = 0.42):
    """Improve small-text legibility locally while preserving text color."""
    strength = float(np.clip(strength, 0.0, 0.82))
    mask = detect_text_like_regions(image)[:, :, None]
    if float(mask.max()) <= 0:
        return image

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype("float32")
    l = lab[:, :, 0]
    blur = cv2.GaussianBlur(l, (0, 0), 0.62)
    detail = l - blur
    detail = np.sign(detail) * np.minimum(np.maximum(np.abs(detail) - 0.55, 0.0), 10.5)
    local_mean = cv2.blur(l, (9, 9))
    contrast = (l - local_mean) * 0.12
    polarity = np.sign(l - local_mean) * np.minimum(np.abs(l - local_mean) * 0.045, 2.0)
    enhanced_l = l + detail * strength + contrast * strength + polarity * strength
    blend = mask[:, :, 0] * 0.68
    lab[:, :, 0] = l * (1.0 - blend) + enhanced_l * blend
    return cv2.cvtColor(np.clip(lab, 0, 255).astype("uint8"), cv2.COLOR_LAB2BGR)
