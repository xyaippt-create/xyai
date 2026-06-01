from __future__ import annotations

import tempfile
from pathlib import Path

import cv2
import numpy as np

from batch.batch_processor import collect_image_paths, process_batch


def write_test_image(path: Path) -> None:
    image = np.full((32, 48, 3), 180, dtype=np.uint8)
    cv2.putText(image, "A1", (5, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 1, cv2.LINE_AA)
    ok, encoded = cv2.imencode(path.suffix, image)
    assert ok
    encoded.tofile(str(path))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="中文 路径 ") as temp:
        root = Path(temp)
        input_dir = root / "输入 图片"
        output_dir = root / "输出 成品"
        input_dir.mkdir()
        write_test_image(input_dir / "test01.jpg")
        (input_dir / "ignore.txt").write_text("not image", encoding="utf-8")

        images = collect_image_paths([input_dir])
        assert len(images) == 1, images

        results = process_batch([input_dir], output_dir, mode="fidelity", scale=2, output_format="png")
        assert len(results) == 1, results
        assert results[0].ok, results[0]
        assert results[0].quality_summary is not None, results[0]
        assert "quality_flag" in results[0].quality_summary
        assert (output_dir / "test01_vmp_v03_4k.png").exists()

        failed = process_batch([input_dir / "missing.jpg", input_dir], output_dir, mode="fidelity", scale=2)
        assert len(failed) >= 1

    print("批量处理测试通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
