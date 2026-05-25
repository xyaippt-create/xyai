import cv2
import numpy as np


BADGE_VERSION = "VisualMasterPro V3.5"


def _text_size(lines: list[str], font_scale: float, thickness: int) -> tuple[int, int, int]:
    widths = []
    heights = []
    baselines = []
    for line in lines:
        (width, height), baseline = cv2.getTextSize(
            line,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            thickness,
        )
        widths.append(width)
        heights.append(height)
        baselines.append(baseline)
    return max(widths), sum(heights), max(baselines)


def apply_delivery_badge(image, mode_name: str, report: dict | None = None):
    """Add a small commercial delivery badge without covering the main subject."""

    result = image.copy()
    height, width = result.shape[:2]
    report = report or {}

    commercial_score = int(report.get("premium_score", 0))
    structure_score = int(report.get("mid_frequency_score", 0))
    lines = [
        BADGE_VERSION,
        f"Mode: {mode_name}",
        f"Commercial Score: {commercial_score}",
        f"Structure Score: {structure_score}",
        "Material Reconstruction: ON",
    ]

    font_scale = max(0.42, min(width, height) / 2300)
    thickness = 1
    line_gap = max(7, int(font_scale * 12))
    padding_x = max(18, int(width * 0.008))
    padding_y = max(14, int(height * 0.007))
    text_width, text_total_height, baseline = _text_size(lines, font_scale, thickness)

    box_width = text_width + padding_x * 2
    box_height = text_total_height + line_gap * (len(lines) - 1) + padding_y * 2 + baseline
    margin = max(24, int(min(width, height) * 0.018))
    x1 = max(margin, width - box_width - margin)
    y1 = max(margin, height - box_height - margin)
    x2 = width - margin
    y2 = height - margin

    overlay = result.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), (18, 18, 18), -1)
    cv2.rectangle(overlay, (x1, y1), (x2, y2), (210, 210, 210), 1)
    result = cv2.addWeighted(overlay, 0.38, result, 0.62, 0)

    cursor_y = y1 + padding_y
    for index, line in enumerate(lines):
        (_, text_height), _ = cv2.getTextSize(
            line,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            thickness,
        )
        cursor_y += text_height
        color = (236, 236, 236) if index == 0 else (218, 218, 218)
        cv2.putText(
            result,
            line,
            (x1 + padding_x, cursor_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            color,
            thickness,
            cv2.LINE_AA,
        )
        cursor_y += line_gap

    return np.clip(result, 0, 255).astype("uint8")
