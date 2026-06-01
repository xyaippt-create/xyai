from pathlib import Path

from engine.algorithms import upscale_to_width
from engine.analysis import (
    analyze_visual_quality,
    build_quality_report,
    write_quality_report_json,
    write_quality_report_markdown,
)
from engine.config import ProcessingResult
from engine.delivery import apply_delivery_badge, build_compare_image
from engine.io import collect_images, read_image, write_image
from engine.rules import interpret_rules_to_strategy, load_visual_rules
from modes import get_profile
from pipelines import PipelineContext, run_mode_pipeline


AUTO_MODE = "auto"
DEFAULT_ANALYSIS_MODE = "ai_commercial_kv"


def choose_mode(requested_mode: str | None, analysis) -> str:
    if requested_mode and requested_mode != AUTO_MODE:
        return requested_mode
    return analysis.recommended_mode


OUTPUT_SUBDIRS = {
    "images": "images",
    "reports_json": "reports_json",
    "reports_md": "reports_md",
    "compare": "compare",
    "archive": "archive",
}


def prepare_output_dirs(output_dir: Path, developer_mode: bool = False) -> dict[str, Path]:
    active_keys = ["images"]
    if developer_mode:
        active_keys.extend(["reports_json", "reports_md", "compare"])
    paths = {key: output_dir / OUTPUT_SUBDIRS[key] for key in active_keys}
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def build_output_path(source: Path, output_dir: Path, mode: str, output_format: str) -> Path:
    output_name = (
        f"{source.stem}_{mode}_雪原Ai·PPT设计"
        f"{output_format}"
    )
    return output_dir / OUTPUT_SUBDIRS["images"] / output_name


def build_quality_report_paths(output_path: Path, output_dir: Path) -> tuple[Path, Path]:
    report_stem = f"{output_path.stem}_quality_report"
    return (
        output_dir / OUTPUT_SUBDIRS["reports_json"] / f"{report_stem}.json",
        output_dir / OUTPUT_SUBDIRS["reports_md"] / f"{report_stem}.md",
    )


def build_compare_path(output_path: Path, output_dir: Path) -> Path:
    return output_dir / OUTPUT_SUBDIRS["compare"] / f"{output_path.stem}_compare.png"


def process_image(image, requested_mode: str | None = AUTO_MODE):
    rule_set = load_visual_rules()
    analysis = analyze_visual_quality(image, rule_set.to_dict())
    selected_mode = choose_mode(requested_mode, analysis)
    profile = get_profile(selected_mode)
    strategy = interpret_rules_to_strategy(analysis, rule_set, selected_mode)

    rule_pack = rule_set.to_dict()
    output_image = upscale_to_width(image, profile.target_width)
    output_image = run_mode_pipeline(
        profile.name,
        output_image,
        PipelineContext(
            analysis=analysis,
            profile=profile,
            rule_pack=rule_pack,
            strategy=strategy,
        ),
    )
    after_analysis = analyze_visual_quality(output_image, rule_set.to_dict())

    return output_image, analysis, after_analysis, profile, rule_set, strategy


def _should_write_json(report_format: str) -> bool:
    return report_format in {"json", "both"}


def _should_write_markdown(report_format: str) -> bool:
    return report_format in {"md", "markdown", "both"}


def process_path(
    input_path: str | Path,
    output_dir: str | Path,
    mode: str | None = AUTO_MODE,
    report: str = "none",
    developer_mode: bool = False,
):
    output_dir = Path(output_dir)
    prepare_output_dirs(output_dir, developer_mode=developer_mode)

    results: list[ProcessingResult] = []
    image_sources = collect_images(input_path)
    if image_sources:
        image_sources = image_sources[:1]

    for source in image_sources:
        image = read_image(source)
        if image is None:
            results.append(
                ProcessingResult(
                    source=source,
                    output=output_dir,
                    width=0,
                    height=0,
                    ok=False,
                    mode="",
                    requested_mode=mode or AUTO_MODE,
                    message="read failed",
                )
            )
            continue

        output_image, analysis, after_analysis, profile, rule_set, strategy = process_image(image, mode)
        report_data = build_quality_report(
            output_image,
            profile,
            rule_set.to_dict(),
            analysis=analysis,
            after_analysis=after_analysis,
            strategy=strategy,
            rules=rule_set,
        )
        if developer_mode:
            output_image = apply_delivery_badge(output_image, profile.name, report_data)
        height, width = output_image.shape[:2]
        output_path = build_output_path(source, output_dir, profile.name, profile.output_format)
        ok = write_image(output_path, output_image)

        json_report_path = None
        markdown_report_path = None
        if ok and developer_mode and report != "none":
            json_report_path, markdown_report_path = build_quality_report_paths(output_path, output_dir)
            if _should_write_json(report):
                write_quality_report_json(json_report_path, report_data)
            else:
                json_report_path = None
            if _should_write_markdown(report):
                write_quality_report_markdown(markdown_report_path, report_data)
            else:
                markdown_report_path = None

            compare_path = build_compare_path(output_path, output_dir)
            write_image(compare_path, build_compare_image(image, output_image))

        results.append(
            ProcessingResult(
                source=source,
                output=output_path,
                width=width,
                height=height,
                ok=ok,
                mode=profile.name,
                requested_mode=mode or AUTO_MODE,
                message="ok" if ok else "write failed",
                analysis=analysis.to_dict(),
                quality_report=report_data,
                quality_report_json_path=json_report_path,
                quality_report_markdown_path=markdown_report_path,
            )
        )

    return results
