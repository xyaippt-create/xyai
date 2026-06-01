from __future__ import annotations

import numpy as np

from engine.algorithms.fidelity_enhancement import enhance_fidelity


def main() -> int:
    image = np.full((24, 36, 3), 128, dtype=np.uint8)
    out_2x = enhance_fidelity(image, mode="fidelity", scale=2)
    out_4x = enhance_fidelity(image, mode="sharp_4k", scale=4)
    assert out_2x.shape[:2] == (48, 72), out_2x.shape
    assert out_4x.shape[:2] == (96, 144), out_4x.shape
    print("原图忠实增强测试通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
