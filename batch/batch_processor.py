from __future__ import annotations

import traceback
import time
import json
import shutil
from pathlib import Path
from typing import Callable, Iterable

from batch.batch_logger import BatchLogger
from batch.batch_report import write_batch_report
from batch.batch_task import BatchTask, BatchTaskResult
from engine.algorithms.fidelity_enhancement import enhance_fidelity
from engine.analysis.quality_compare import compare_quality
from engine.delivery.compare import build_compare_image
from engine.io import IMAGE_EXTS, read_image, write_image
from runtime.logger import logs_dir


ProgressCallback = Callable[[BatchTask, BatchTaskResult | None, str], None]
CancelCallback = Callable[[], bool]
PauseCallback = Callable[[], bool]


def collect_image_paths(input_paths: Iterable[str | Path]) -> list[Path]:
    images: list[Path] = []
    for item in input_paths:
        path = Path(item)
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            images.append(path)
        elif path.is_dir():
            images.extend(
                sorted(
                    child
                    for child in path.iterdir()
                    if child.is_file() and child.suffix.lower() in IMAGE_EXTS
                )
            )
    return sorted(dict.fromkeys(images))


def build_output_path(source: Path, output_dir: Path, output_format: str) -> Path:
    suffix = output_format.lower().lstrip(".")
    return output_dir / f"{source.stem}_vmp_v03_4k.{suffix}"


def _debug_quality_path(source: Path, output_dir: Path, total: int) -> Path:
    report_dir = output_dir / "reports_json"
    report_dir.mkdir(parents=True, exist_ok=True)
    if total == 1:
        return report_dir / "quality_report.json"
    return report_dir / f"{source.stem}_quality_report.json"


def _debug_compare_path(source: Path, output_dir: Path) -> Path:
    compare_dir = output_dir / "compare"
    compare_dir.mkdir(parents=True, exist_ok=True)
    return compare_dir / f"{source.stem}_compare.png"


def process_one(task: BatchTask, debug_output: bool = False, total_sources: int = 1) -> BatchTaskResult:
    image = read_image(task.source)
    if image is None:
        return BatchTaskResult(task.source, None, False, "图片读取失败")

    output_image = enhance_fidelity(image, mode=task.mode, scale=task.scale)
    quality_summary = compare_quality(image, output_image)
    output_path = build_output_path(task.source, task.output_dir, task.output_format)
    if not write_image(output_path, output_image):
        return BatchTaskResult(task.source, output_path, False, "图片写入失败")

    if debug_output:
        quality_path = _debug_quality_path(task.source, task.output_dir, total_sources)
        quality_path.write_text(json.dumps(quality_summary, ensure_ascii=False, indent=2), encoding="utf-8")
        write_image(_debug_compare_path(task.source, task.output_dir), build_compare_image(image, output_image))

    height, width = output_image.shape[:2]
    quality_flag = str(quality_summary.get("quality_flag", "处理完成"))
    return BatchTaskResult(task.source, output_path, True, quality_flag, width=width, height=height, quality_summary=quality_summary)


def process_batch(
    input_paths,
    output_dir,
    mode="fidelity",
    scale=2,
    output_format="png",
    debug_output: bool = False,
    progress_callback: ProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
    pause_callback: PauseCallback | None = None,
) -> list[BatchTaskResult]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = BatchLogger(logs_dir())
    logger.info(f"开始批量处理，模式={mode}，倍率={scale}x，格式={output_format}")

    sources = collect_image_paths(input_paths)
    results: list[BatchTaskResult] = []
    if not sources:
        logger.info("未发现可处理图片。")
        write_batch_report(logs_dir(), results, mode, scale, output_format)
        return results

    for source in sources:
        while pause_callback and pause_callback():
            logger.info("批量任务暂停中。")
            time.sleep(0.2)
        if cancel_callback and cancel_callback():
            logger.info("收到停止请求，批量任务提前结束。")
            break
        task = BatchTask(
            source=source,
            output_dir=output_dir,
            mode=mode,
            scale=int(scale),
            output_format=output_format,
        )
        if progress_callback:
            progress_callback(task, None, "start")
        try:
            result = process_one(task, debug_output=debug_output, total_sources=len(sources))
        except Exception as exc:
            logger.error(f"{source}：{exc}\n{traceback.format_exc()}")
            result = BatchTaskResult(source, None, False, str(exc))

        results.append(result)
        if result.ok:
            logger.success(f"{source.name} -> {result.output}")
        else:
            logger.error(f"{source.name}：{result.message}")
        if progress_callback:
            progress_callback(task, result, "done")

    report_path = write_batch_report(logs_dir(), results, mode, int(scale), output_format)
    logger.info(f"批量处理结束，报告：{report_path}")
    if debug_output:
        shutil.copy2(report_path, output_dir / "batch_report.json")
        latest_log = logs_dir() / "latest_batch.log"
        if latest_log.exists():
            shutil.copy2(latest_log, output_dir / "latest_batch.log")
    return results
