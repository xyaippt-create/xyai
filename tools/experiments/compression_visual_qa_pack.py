#!/usr/bin/env python
"""Build a visual QA pack for output-size compression candidates.

This script is intentionally experimental. It reads probe CSV rows, original
samples, and candidate images, then writes review artifacts to an external QA
directory. It does not modify delivery outputs or connect to the app pipeline.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat


METHOD_ORDER = [
    "png_optimize",
    "jpg_q95",
    "jpg_q92",
    "jpg_q90",
    "webp_q94",
    "webp_q94_alpha",
    "webp_q90",
    "webp_q90_alpha",
]

METHOD_LABELS = {
    "png_optimize": "PNG optimize",
    "jpg_q95": "JPG95",
    "jpg_q92": "JPG92",
    "jpg_q90": "JPG90",
    "webp_q94": "WebP94",
    "webp_q94_alpha": "WebP94 alpha",
    "webp_q90": "WebP90",
    "webp_q90_alpha": "WebP90 alpha",
}

SUMMARY_FIELDS = [
    "file_name",
    "image_type_guess",
    "compression_method",
    "saved_ratio",
    "size_ratio_vs_original",
    "candidate_size_bytes",
    "mean_abs_diff",
    "psnr",
    "alpha_preserved",
    "alpha_mean_diff",
    "qa_verdict",
    "pipeline_scope",
    "visual_risk",
    "qa_notes",
    "contact_sheet_path",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate visual QA summaries and contact sheets for compression candidates."
    )
    parser.add_argument("--results-csv", required=True, help="compression_probe_results.csv")
    parser.add_argument("--candidates-dir", required=True, help="Candidate image directory")
    parser.add_argument("--samples-dir", required=True, help="Original sample directory")
    parser.add_argument("--output-dir", required=True, help="Visual QA output directory")
    return parser.parse_args()


def read_probe_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def float_value(value: str, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def has_alpha(image: Image.Image) -> bool:
    if "A" not in image.getbands():
        return False
    alpha = image.getchannel("A")
    stat = ImageStat.Stat(alpha)
    return stat.extrema[0][0] < 255


def to_display_rgb(image: Image.Image) -> Image.Image:
    if "A" not in image.getbands():
        return image.convert("RGB")
    rgba = image.convert("RGBA")
    checker = Image.new("RGB", rgba.size, (245, 245, 245))
    draw = ImageDraw.Draw(checker)
    step = 12
    for y in range(0, rgba.height, step):
        for x in range(0, rgba.width, step):
            if (x // step + y // step) % 2:
                draw.rectangle((x, y, x + step - 1, y + step - 1), fill=(220, 220, 220))
    checker.paste(rgba, mask=rgba.getchannel("A"))
    return checker


def resize_contain(image: Image.Image, size: Tuple[int, int]) -> Image.Image:
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    image = image.copy()
    image.thumbnail(size, resampling)
    canvas = Image.new("RGB", size, (250, 250, 250))
    x = (size[0] - image.width) // 2
    y = (size[1] - image.height) // 2
    canvas.paste(to_display_rgb(image), (x, y))
    return canvas


def safe_name(name: str) -> str:
    keep = []
    for char in name:
        if char.isalnum() or char in ("-", "_", "."):
            keep.append(char)
        else:
            keep.append("_")
    return "".join(keep)


def metric_diff(original: Image.Image, candidate: Image.Image) -> Dict[str, object]:
    original_rgba = original.convert("RGBA")
    candidate_rgba = candidate.convert("RGBA")
    if original_rgba.size != candidate_rgba.size:
        candidate_rgba = candidate_rgba.resize(original_rgba.size)

    original_rgb = original_rgba.convert("RGB")
    candidate_rgb = candidate_rgba.convert("RGB")
    diff = ImageChops.difference(original_rgb, candidate_rgb)
    stat = ImageStat.Stat(diff)
    mean_abs = sum(stat.mean) / len(stat.mean)
    rms = math.sqrt(sum(channel * channel for channel in stat.rms) / len(stat.rms))
    psnr = float("inf") if rms == 0 else 20 * math.log10(255.0 / rms)

    original_alpha = original_rgba.getchannel("A")
    candidate_alpha = candidate_rgba.getchannel("A")
    alpha_diff = ImageChops.difference(original_alpha, candidate_alpha)
    alpha_stat = ImageStat.Stat(alpha_diff)
    alpha_mean = alpha_stat.mean[0]
    alpha_max = alpha_stat.extrema[0][1]

    return {
        "mean_abs_diff": round(mean_abs, 4),
        "psnr": "inf" if math.isinf(psnr) else round(psnr, 4),
        "alpha_mean_diff": round(alpha_mean, 4),
        "alpha_max_diff": alpha_max,
        "alpha_preserved": alpha_max == 0,
    }


def focus_box(image: Image.Image, image_type: str) -> Tuple[int, int, int, int]:
    width, height = image.size
    if width <= 80 or height <= 80:
        return (0, 0, width, height)

    crop_w = max(80, min(width, int(width * 0.32)))
    crop_h = max(80, min(height, int(height * 0.32)))

    if image_type == "transparent_png" and "A" in image.getbands():
        alpha = image.convert("RGBA").getchannel("A")
        semi = alpha.point(lambda a: 255 if 0 < a < 255 else 0)
        bbox = semi.getbbox() or alpha.getbbox()
        if bbox:
            cx = (bbox[0] + bbox[2]) // 2
            cy = (bbox[1] + bbox[3]) // 2
            return clamp_box(cx - crop_w // 2, cy - crop_h // 2, crop_w, crop_h, width, height)

    gray = image.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    best_score = -1.0
    best_box = clamp_box((width - crop_w) // 2, (height - crop_h) // 2, crop_w, crop_h, width, height)
    steps_x = 5
    steps_y = 5
    for iy in range(steps_y):
        y = int((height - crop_h) * iy / max(1, steps_y - 1))
        for ix in range(steps_x):
            x = int((width - crop_w) * ix / max(1, steps_x - 1))
            box = (x, y, x + crop_w, y + crop_h)
            stat = ImageStat.Stat(edges.crop(box))
            score = stat.mean[0] + stat.stddev[0]
            if score > best_score:
                best_score = score
                best_box = box
    return best_box


def clamp_box(x: int, y: int, w: int, h: int, width: int, height: int) -> Tuple[int, int, int, int]:
    x = max(0, min(x, max(0, width - w)))
    y = max(0, min(y, max(0, height - h)))
    return (x, y, min(width, x + w), min(height, y + h))


def qa_decision(row: Dict[str, str], metrics: Dict[str, object], original_has_alpha: bool) -> Dict[str, str]:
    image_type = row["image_type_guess"]
    method = row["compression_method"]
    saved_ratio = float_value(row.get("saved_ratio", "0"))
    psnr_value = metrics["psnr"]
    psnr = 99.0 if psnr_value == "inf" else float(psnr_value)
    alpha_preserved = bool(metrics["alpha_preserved"])

    verdict = "manual_review"
    scope = "manual_qa"
    visual_risk = "medium"
    notes = "Needs visual review before formal use."

    if image_type == "contact_sheet_preview":
        if method in {"jpg_q90", "jpg_q92", "webp_q90", "webp_q94"}:
            return {
                "qa_verdict": "candidate",
                "pipeline_scope": "preview_only",
                "visual_risk": "low",
                "qa_notes": "Good candidate for contact sheet or preview lightening; not final output evidence.",
            }
        return {
            "qa_verdict": "manual_review",
            "pipeline_scope": "preview_only",
            "visual_risk": "medium",
            "qa_notes": "Preview-only fallback; lower priority than JPG/WebP preview candidates.",
        }

    if image_type == "transparent_png":
        if method == "png_optimize" and alpha_preserved:
            return {
                "qa_verdict": "candidate",
                "pipeline_scope": "transparent_png_lossless",
                "visual_risk": "low",
                "qa_notes": "Alpha is preserved; safest transparent PNG candidate.",
            }
        if method in {"webp_q90_alpha", "webp_q94_alpha"}:
            return {
                "qa_verdict": "experiment_only",
                "pipeline_scope": "webp_alpha_experiment",
                "visual_risk": "medium",
                "qa_notes": "Keeps alpha channel in this run but has alpha-edge and compatibility risk.",
            }
        return {
            "qa_verdict": "reject",
            "pipeline_scope": "do_not_use",
            "visual_risk": "high",
            "qa_notes": "Transparent PNG should not be converted to a non-alpha final format.",
        }

    if image_type == "text_ppt_logo":
        if method == "png_optimize" and psnr >= 48:
            return {
                "qa_verdict": "candidate",
                "pipeline_scope": "text_logo_conservative",
                "visual_risk": "low",
                "qa_notes": "Conservative candidate; still requires manual text/logo edge check.",
            }
        if method in {"jpg_q95", "webp_q94"}:
            return {
                "qa_verdict": "manual_review",
                "pipeline_scope": "text_logo_manual_only",
                "visual_risk": "medium",
                "qa_notes": "Only a manual QA candidate; risk to Chinese strokes, fine lines, and brand color.",
            }
        return {
            "qa_verdict": "reject",
            "pipeline_scope": "do_not_use",
            "visual_risk": "high",
            "qa_notes": "Too risky for Chinese small text, logo edges, or thin strokes.",
        }

    if image_type in {"product_ad", "commercial_png"}:
        if method == "jpg_q95" and saved_ratio > 0.15:
            verdict = "candidate"
            scope = "final_product_ad_candidate"
            visual_risk = "medium"
            notes = "Best final-output candidate class; requires packaging text, highlight, gradient, and texture QA."
        elif method in {"jpg_q92", "webp_q94"} and saved_ratio > 0.2:
            verdict = "manual_review"
            scope = "final_experiment_only"
            visual_risk = "medium"
            notes = "Useful experiment, but should not be a default final-output strategy."
        elif method == "png_optimize":
            verdict = "manual_review"
            scope = "lossless_png_fallback"
            visual_risk = "low"
            notes = "Safe fallback when lossy candidates fail visual QA."
        else:
            verdict = "reject"
            scope = "do_not_use"
            visual_risk = "high" if method in {"jpg_q90", "webp_q90"} else "medium"
            notes = "Too aggressive for default commercial final output."
        return {
            "qa_verdict": verdict,
            "pipeline_scope": scope,
            "visual_risk": visual_risk,
            "qa_notes": notes,
        }

    if image_type == "ordinary_non_alpha":
        if method in {"webp_q90", "webp_q94"} and saved_ratio > 0.2:
            return {
                "qa_verdict": "experiment_only",
                "pipeline_scope": "ordinary_webp_experiment",
                "visual_risk": "medium",
                "qa_notes": "Good size result, but WebP should remain opt-in until compatibility is decided.",
            }
        if saved_ratio <= 0:
            return {
                "qa_verdict": "reject",
                "pipeline_scope": "do_not_use",
                "visual_risk": "low",
                "qa_notes": "Candidate increases file size for this sample.",
            }

    return {
        "qa_verdict": verdict,
        "pipeline_scope": scope,
        "visual_risk": visual_risk,
        "qa_notes": notes,
    }


def sheet_methods_for_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    by_method = {row["compression_method"]: row for row in rows}
    selected = []
    for method in METHOD_ORDER:
        if method in by_method:
            selected.append(by_method[method])
    return selected


def create_contact_sheet(
    original_path: Path,
    rows: List[Dict[str, str]],
    output_path: Path,
) -> None:
    original = Image.open(original_path)
    image_type = rows[0]["image_type_guess"] if rows else "unknown"
    focus = focus_box(original, image_type)
    selected = sheet_methods_for_rows(rows)

    panels: List[Tuple[str, Image.Image]] = [("Original", original)]
    for row in selected:
        candidate_path = Path(row.get("candidate_path") or "")
        if candidate_path.exists():
            panels.append((METHOD_LABELS.get(row["compression_method"], row["compression_method"]), Image.open(candidate_path)))

    thumb_size = (220, 150)
    zoom_size = (220, 150)
    label_h = 34
    pad = 14
    title_h = 40
    columns = len(panels)
    width = pad + columns * (thumb_size[0] + pad)
    height = title_h + label_h + thumb_size[1] + label_h + zoom_size[1] + pad
    sheet = Image.new("RGB", (width, height), (246, 246, 246))
    draw = ImageDraw.Draw(sheet)
    draw.text((pad, 12), f"{original_path.name} | {image_type}", fill=(20, 20, 20))

    for index, (label, image) in enumerate(panels):
        x = pad + index * (thumb_size[0] + pad)
        draw.text((x, title_h), label[:32], fill=(20, 20, 20))
        full = resize_contain(image, thumb_size)
        sheet.paste(full, (x, title_h + label_h))

        crop = image.crop(focus if image.size == original.size else scale_box(focus, original.size, image.size))
        zoom = resize_contain(crop, zoom_size)
        y = title_h + label_h + thumb_size[1] + label_h
        draw.text((x, y - label_h + 8), "Focus crop", fill=(70, 70, 70))
        sheet.paste(zoom, (x, y))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, format="PNG", optimize=True)


def scale_box(
    box: Tuple[int, int, int, int],
    original_size: Tuple[int, int],
    target_size: Tuple[int, int],
) -> Tuple[int, int, int, int]:
    sx = target_size[0] / max(1, original_size[0])
    sy = target_size[1] / max(1, original_size[1])
    return (
        int(box[0] * sx),
        int(box[1] * sy),
        max(int(box[2] * sx), int(box[0] * sx) + 1),
        max(int(box[3] * sy), int(box[1] * sy) + 1),
    )


def format_pct(value: str) -> str:
    return f"{float_value(value) * 100:.2f}%"


def summarize_counts(rows: List[Dict[str, str]], field: str) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row[field]] += 1
    return dict(sorted(counts.items()))


def write_summary_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in SUMMARY_FIELDS})


def write_report(
    path: Path,
    args: argparse.Namespace,
    summary_rows: List[Dict[str, str]],
    sheet_paths: List[Path],
) -> None:
    counts_by_type = summarize_counts(summary_rows, "image_type_guess")
    counts_by_scope = summarize_counts(summary_rows, "pipeline_scope")
    counts_by_verdict = summarize_counts(summary_rows, "qa_verdict")

    lines = [
        "# Compression Candidate Visual QA Report",
        "",
        f"- Results CSV: `{args.results_csv}`",
        f"- Candidates: `{args.candidates_dir}`",
        f"- Samples: `{args.samples_dir}`",
        f"- Output: `{args.output_dir}`",
        f"- Candidate rows reviewed: {len(summary_rows)}",
        f"- Contact sheets: {len(sheet_paths)}",
        "",
        "## Candidate Counts By Type",
        "",
    ]
    for key, value in counts_by_type.items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## QA Verdict Counts", ""])
    for key, value in counts_by_verdict.items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Pipeline Scope Counts", ""])
    for key, value in counts_by_scope.items():
        lines.append(f"- {key}: {value}")

    lines.extend(
        [
            "",
            "## Visual QA Decisions",
            "",
            "| File | Method | Saved | PSNR | Alpha | Verdict | Scope | Risk | Notes |",
            "| --- | --- | ---: | ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for row in summary_rows:
        lines.append(
            "| {file} | {method} | {saved} | {psnr} | {alpha} | {verdict} | {scope} | {risk} | {notes} |".format(
                file=row["file_name"],
                method=row["compression_method"],
                saved=format_pct(row["saved_ratio"]),
                psnr=row["psnr"],
                alpha=row["alpha_preserved"],
                verdict=row["qa_verdict"],
                scope=row["pipeline_scope"],
                risk=row["visual_risk"],
                notes=row["qa_notes"].replace("|", "/"),
            )
        )

    lines.extend(
        [
            "",
            "## Guardrail Conclusions",
            "",
            "- Text / logo: only PNG optimize is a conservative Patch C candidate; JPG95 and WebP94 remain manual QA only.",
            "- Product / commercial: JPG95 can enter Patch C design as a non-transparent final-output candidate after manual visual QA.",
            "- Transparent PNG: keep alpha; PNG optimize is the only default candidate, WebP alpha remains an experiment.",
            "- Contact sheet / preview: JPG90/JPG92/WebP90/WebP94 are suitable preview-only candidates.",
            "- WebP should remain an experiment switch, not a default formal delivery format.",
            "- Human visual review is still required before any final-output compression enters the formal pipeline.",
        ]
    )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    results_csv = Path(args.results_csv)
    samples_dir = Path(args.samples_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    contact_sheet_dir = output_dir / "contact_sheets"
    contact_sheet_dir.mkdir(parents=True, exist_ok=True)

    rows = read_probe_rows(results_csv)
    grouped: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["file_name"]].append(row)

    sheet_paths: List[Path] = []
    summary_rows: List[Dict[str, str]] = []

    for file_name, file_rows in sorted(grouped.items()):
        original_path = samples_dir / file_name
        if not original_path.exists():
            continue

        sheet_path = contact_sheet_dir / f"{safe_name(Path(file_name).stem)}__visual_qa_sheet.png"
        create_contact_sheet(original_path, file_rows, sheet_path)
        sheet_paths.append(sheet_path)

        original = Image.open(original_path)
        original_has_alpha = has_alpha(original)
        for row in sorted(file_rows, key=lambda item: METHOD_ORDER.index(item["compression_method"]) if item["compression_method"] in METHOD_ORDER else 99):
            candidate_path = Path(row.get("candidate_path") or "")
            if not candidate_path.exists():
                continue
            candidate = Image.open(candidate_path)
            metrics = metric_diff(original, candidate)
            decision = qa_decision(row, metrics, original_has_alpha)
            summary = {
                **row,
                "mean_abs_diff": str(metrics["mean_abs_diff"]),
                "psnr": str(metrics["psnr"]),
                "alpha_preserved": str(metrics["alpha_preserved"]),
                "alpha_mean_diff": str(metrics["alpha_mean_diff"]),
                "contact_sheet_path": str(sheet_path),
                **decision,
            }
            summary_rows.append(summary)

    write_summary_csv(output_dir / "visual_qa_summary.csv", summary_rows)
    write_report(output_dir / "visual_qa_report.md", args, summary_rows, sheet_paths)
    print(f"Visual QA report: {output_dir / 'visual_qa_report.md'}")
    print(f"Visual QA summary: {output_dir / 'visual_qa_summary.csv'}")
    print(f"Contact sheets: {contact_sheet_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
