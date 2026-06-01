from __future__ import annotations

import cv2
import numpy as np

from engine.algorithms.fidelity_enhancement import enhance_fidelity
from engine.algorithms.highlight_protection import protect_highlights
from engine.analysis.image_type_detector import detect_image_type
from engine.analysis.quality_compare import compare_quality


def main() -> int:
    poster = np.full((120, 260, 3), 242, dtype=np.uint8)
    cv2.putText(poster, "FU CULTURE", (12, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (30, 30, 30), 2, cv2.LINE_AA)
    cv2.putText(poster, "2026.05.26  Museum Hall", (12, 86), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (60, 60, 60), 1, cv2.LINE_AA)

    image_type = detect_image_type(poster)
    assert image_type.image_type in {"text_poster", "general", "architecture"}

    enhanced = enhance_fidelity(poster, mode="text_safe", scale=2)
    quality = compare_quality(poster, enhanced)
    assert enhanced.shape[:2] == (240, 520)
    assert quality["color_fidelity_score"] >= 82.0, quality
    assert "quality_flag" in quality

    highlight = poster.copy()
    cv2.circle(highlight, (210, 34), 18, (255, 255, 255), -1)
    overdone = cv2.addWeighted(highlight, 1.28, cv2.GaussianBlur(highlight, (0, 0), 1), -0.28, 0)
    protected = protect_highlights(highlight, overdone, strength=0.95)
    assert protected[34, 210].mean() <= overdone[34, 210].mean()

    print("画质核心测试通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
