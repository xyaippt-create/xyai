from __future__ import annotations

import cv2
import numpy as np

from engine.algorithms.text_clarity import detect_text_like_regions, enhance_text_regions
from engine.analysis.quality_compare import _masked_laplacian_score


def main() -> int:
    image = np.full((80, 180, 3), 245, dtype=np.uint8)
    cv2.putText(image, "Visual 123", (8, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (30, 30, 30), 2, cv2.LINE_AA)
    mask = detect_text_like_regions(image)
    enhanced = enhance_text_regions(image)
    assert mask.shape[:2] == image.shape[:2]
    assert enhanced.shape == image.shape
    assert float(mask.max()) > 0
    assert _masked_laplacian_score(enhanced, mask) >= _masked_laplacian_score(image, mask)
    print("文字清晰度增强测试通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
