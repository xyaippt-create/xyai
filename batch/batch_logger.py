from __future__ import annotations

from datetime import datetime
from pathlib import Path


class BatchLogger:
    def __init__(self, log_dir: str | Path):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self.latest_path = self.log_dir / "latest_batch.log"
        self.latest_path.write_text("", encoding="utf-8")

    def write(self, message: str) -> None:
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        for path in (self.path, self.latest_path):
            with path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")

    def info(self, message: str) -> None:
        self.write(f"信息：{message}")

    def success(self, message: str) -> None:
        self.write(f"成功：{message}")

    def error(self, message: str) -> None:
        self.write(f"失败：{message}")
