from __future__ import annotations

import cv2
import numpy as np

from backend.restoration_server import RESTORATION_LOGS, format_sse_event, lightweight_restorator


def main() -> int:
    assert len(RESTORATION_LOGS) == 11
    event = format_sse_event(1, RESTORATION_LOGS[0])
    assert event.startswith("event: restoration.log")
    assert "data:" in event
    assert "SSE CONNECTED" in event

    image = np.full((24, 36, 3), 148, dtype=np.uint8)
    cv2.putText(image, "A1", (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 20, 20), 1, cv2.LINE_AA)
    restored = lightweight_restorator(image, scale=2)
    assert restored.shape[:2] == (48, 72), restored.shape
    print("实时修复后端基础测试通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
