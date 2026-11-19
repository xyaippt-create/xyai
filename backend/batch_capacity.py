"""Capacity checks for a batch's actual cache and output volumes."""

import shutil
from pathlib import Path

from fastapi import HTTPException


def batch_size_field(payload, name: str) -> int:
    size = payload.get(name)
    if type(size) is not int or not 0 <= size <= 2**53 - 1:
        raise HTTPException(400, detail={
            "code": "BATCH_SIZE_INVALID", "message": "批次文件体积无效，请重新选择图片。",
        })
    return size


def require_batch_capacity(*requirements: tuple[Path, int, str]) -> None:
    """Count cache and estimated output space together when they share a volume."""
    volumes: dict[int, tuple[Path, int, str]] = {}
    try:
        for target, amount, label in requirements:
            path = target.resolve()
            while not path.exists() and path != path.parent:
                path = path.parent
            if not path.is_dir():
                raise OSError("destination is not a directory")
            device = path.stat().st_dev
            previous = volumes.get(device)
            volumes[device] = (path, amount, label) if previous is None else (
                path, previous[1] + amount, f"{previous[2]}和{label}",
            )
        for path, required, label in volumes.values():
            free = shutil.disk_usage(path).free
            if free < max(1, required):
                raise HTTPException(422, detail={
                    "code": "BATCH_DISK_SPACE_INSUFFICIENT",
                    "message": (
                        f"{label}所在磁盘空间不足。本批按输入体积估算需预留 "
                        f"{max(1, required) / 2**20:.2f} MiB，当前可用 {free / 2**20:.2f} MiB。"
                        "请释放空间或减少本批图片后重试。"
                    ),
                })
    except (OSError, RuntimeError) as exc:
        raise HTTPException(422, detail={
            "code": "BATCH_DISK_SPACE_UNAVAILABLE",
            "message": "无法检查批次缓存或输出磁盘空间，请检查目录后重试。",
        }) from exc
