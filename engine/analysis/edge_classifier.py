from __future__ import annotations

import cv2
import numpy as np


def _safe_uint8_mask(mask: np.ndarray) -> np.ndarray:
    return np.where(mask > 0, 255, 0).astype("uint8")


def highlight_mask(image: np.ndarray, value_threshold: int = 224) -> np.ndarray:
    """Detect bright reflection regions that should not be sharpened."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    value = hsv[:, :, 2]
    saturation = hsv[:, :, 1]
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(grad_x, grad_y)
    bright = (value >= value_threshold) & (saturation >= 36)
    clipped = value >= 248
    reflective = (value >= 244) & (saturation <= 48) & (gradient <= 3.5)
    mask = _safe_uint8_mask(bright | clipped | reflective)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    return cv2.dilate(mask, kernel, iterations=1)


def compression_block_mask(image: np.ndarray) -> np.ndarray:
    """Estimate JPEG/block artifacts using grid discontinuity and flat areas."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    gx = cv2.absdiff(gray[:, 1:], gray[:, :-1])
    gy = cv2.absdiff(gray[1:, :], gray[:-1, :])
    grid = np.zeros_like(gray, dtype="uint8")
    if width > 16:
        vertical = np.zeros_like(gray, dtype="uint8")
        vertical[:, 8::8] = 255
        jumps = np.zeros_like(gray, dtype="uint8")
        jumps[:, 1:] = gx
        grid = cv2.max(grid, cv2.bitwise_and(vertical, _safe_uint8_mask(jumps > 8)))
    if height > 16:
        horizontal = np.zeros_like(gray, dtype="uint8")
        horizontal[8::8, :] = 255
        jumps = np.zeros_like(gray, dtype="uint8")
        jumps[1:, :] = gy
        grid = cv2.max(grid, cv2.bitwise_and(horizontal, _safe_uint8_mask(jumps > 8)))
    flat = cv2.Laplacian(gray, cv2.CV_32F)
    flat_mask = _safe_uint8_mask(np.abs(flat) < 4.5)
    grid = cv2.dilate(grid, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)
    return cv2.bitwise_and(grid, flat_mask)


def true_edge_mask(image: np.ndarray, exclude_highlights: bool = True) -> np.ndarray:
    """Classify stable structural edges and reject noise, blocks and highlights."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (0, 0), 0.6)
    median = float(np.median(gray))
    lower = int(max(18, 0.58 * median))
    upper = int(min(210, max(lower + 24, 1.28 * median)))
    edges = cv2.Canny(gray, lower, upper, L2gradient=True)

    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(grad_x, grad_y)
    stable = _safe_uint8_mask(magnitude > max(10.0, float(np.percentile(magnitude, 72))))
    mask = cv2.bitwise_and(edges, stable)

    # Favor coherent lines and contours over isolated speckles.
    line_h = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 1)))
    line_v = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 5)))
    mask = cv2.max(mask, cv2.max(line_h, line_v))

    noise = _safe_uint8_mask(magnitude > np.percentile(magnitude, 98.8))
    block = compression_block_mask(image)
    reject = cv2.dilate(cv2.max(noise, block), cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)
    if exclude_highlights:
        reject = cv2.max(reject, highlight_mask(image))
    mask = cv2.bitwise_and(mask, cv2.bitwise_not(reject))

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    filtered = np.zeros_like(mask)
    for label in range(1, num_labels):
        area = int(stats[label, cv2.CC_STAT_AREA])
        width = int(stats[label, cv2.CC_STAT_WIDTH])
        height = int(stats[label, cv2.CC_STAT_HEIGHT])
        if area >= 8 and max(width, height) >= 5:
            filtered[labels == label] = 255
    return cv2.GaussianBlur(filtered, (0, 0), 0.55)


def normalized_mask(mask: np.ndarray) -> np.ndarray:
    if mask.ndim == 3:
        mask = mask[:, :, 0]
    return np.clip(mask.astype("float32") / 255.0, 0.0, 1.0)
