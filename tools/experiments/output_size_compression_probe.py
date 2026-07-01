from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Iterable

from PIL import Image


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_OUTPUT_DIR = Path("D:/影界文件/影界测试反馈包/compression_trials")


@dataclass(frozen=True)
class Candidate:
    method: str
    fmt: str
    quality: str
    suffix: str


NON_ALPHA_CANDIDATES = [
    Candidate("png_optimize", "png", "optimize_level_9", ".png"),
    Candidate("jpg_q95", "jpg", "95", ".jpg"),
    Candidate("jpg_q92", "jpg", "92", ".jpg"),
    Candidate("jpg_q90", "jpg", "90", ".jpg"),
    Candidate("webp_q94", "webp", "94", ".webp"),
    Candidate("webp_q90", "webp", "90", ".webp"),
]

ALPHA_CANDIDATES = [
    Candidate("png_optimize", "png", "optimize_level_9", ".png"),
    Candidate("webp_q94_alpha", "webp", "94", ".webp"),
    Candidate("webp_q90_alpha", "webp", "90", ".webp"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe file-size compression candidates outside the formal delivery pipeline.",
    )
    parser.add_argument("input_dir", type=Path, help="Directory containing image samples.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="External directory for trial images and reports.",
    )
    parser.add_argument("--recursive", action="store_true", help="Scan input directory recursively.")
    parser.add_argument(
        "--role",
        choices=["auto", "final", "preview", "contact_sheet"],
        default="auto",
        help="Override sample role. auto uses filename/path hints.",
    )
    return parser.parse_args()


def iter_images(input_dir: Path, recursive: bool) -> Iterable[Path]:
    pattern = "**/*" if recursive else "*"
    for path in sorted(input_dir.glob(pattern)):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            yield path


def safe_stem(path: Path) -> str:
    stem = re.sub(r"[^0-9A-Za-z._-]+", "_", path.stem).strip("._-")
    return stem or "image"


def image_has_alpha(image: Image.Image) -> bool:
    if image.mode in {"RGBA", "LA"}:
        alpha = image.getchannel("A")
        low, high = alpha.getextrema()
        return low < 255 or high < 255
    return "transparency" in image.info


def guess_role(path: Path, override: str) -> str:
    if override != "auto":
        return override
    text = str(path).lower()
    if any(token in text for token in ("contact", "contact_sheet", "compare", "comparison")):
        return "contact_sheet"
    if any(token in text for token in ("preview", "thumb", "thumbnail", "report")):
        return "preview"
    return "final"


def guess_image_type(path: Path, image: Image.Image, has_alpha: bool, role: str) -> str:
    text = str(path).lower()
    if role in {"contact_sheet", "preview"}:
        return "contact_sheet_preview"
    if has_alpha:
        return "transparent_png"
    if any(token in text for token in ("ppt", "slide", "text", "logo", "brand", "ui", "poster", "cn", "chinese", "map")):
        return "text_ppt_logo"
    if any(token in text for token in ("product", "kv", "ad", "poster", "pack", "banner", "commerce")):
        return "product_ad"
    width, height = image.size
    if path.suffix.lower() == ".png" and width * height <= 3_000_000:
        return "commercial_png"
    return "ordinary_non_alpha"


def candidate_list(has_alpha: bool) -> list[Candidate]:
    return ALPHA_CANDIDATES if has_alpha else NON_ALPHA_CANDIDATES


def save_candidate(image: Image.Image, candidate: Candidate, target: Path, has_alpha: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if candidate.fmt == "png":
        png_image = image.convert("RGBA") if has_alpha else image.convert("RGB")
        png_image.save(target, format="PNG", optimize=True, compress_level=9)
        return
    if candidate.fmt == "jpg":
        rgb = image.convert("RGB")
        rgb.save(target, format="JPEG", quality=int(candidate.quality), optimize=True, subsampling=0)
        return
    if candidate.fmt == "webp":
        webp_image = image.convert("RGBA") if has_alpha else image.convert("RGB")
        webp_image.save(target, format="WEBP", quality=int(candidate.quality), method=6)
        return
    raise ValueError(f"Unsupported candidate format: {candidate.fmt}")


def risk_for_candidate(image_type: str, role: str, has_alpha: bool, candidate: Candidate) -> tuple[str, str, str]:
    if role in {"contact_sheet", "preview"}:
        return (
            "low" if candidate.fmt in {"jpg", "webp"} else "medium",
            "Preview/contact sheet only; does not represent final output quality.",
            "preview_only",
        )
    if has_alpha:
        if candidate.fmt == "png":
            return ("low", "Lossless PNG candidate keeps alpha; inspect transparent edges.", "cautious")
        return (
            "medium",
            "WebP can preserve alpha but has compatibility and transparent-edge review risk.",
            "cautious",
        )
    if image_type == "text_ppt_logo":
        if candidate.method == "png_optimize":
            return ("low", "Lossless-style PNG candidate; still inspect text and logo edges.", "cautious")
        if candidate.method in {"jpg_q95", "webp_q94"}:
            return ("medium", "May affect Chinese small text, logo edges, fine lines, and brand colors.", "cautious")
        return ("high", "Likely risk for small text, fine lines, logo edges, and flat brand colors.", "not_recommended")
    if image_type in {"product_ad", "commercial_png"}:
        if candidate.method in {"jpg_q90", "webp_q90"}:
            return ("medium", "Check highlights, gradients, package text, product edges, and material detail.", "cautious")
        return ("medium", "Potentially useful; manually inspect highlights, gradients, and product edges.", "cautious")
    if candidate.fmt == "webp":
        return ("medium", "Good size candidate, but WebP compatibility must be confirmed.", "candidate")
    if candidate.fmt == "jpg":
        return ("low", "Good non-alpha candidate if text/logo risk is low.", "candidate")
    return ("low", "Lossless-style PNG candidate.", "candidate")


def probe_image(path: Path, candidates_dir: Path, role_override: str) -> list[dict[str, object]]:
    original_size = path.stat().st_size
    original_format = path.suffix.lower().lstrip(".").replace("jpeg", "jpg")
    rows: list[dict[str, object]] = []
    with Image.open(path) as image:
        image.load()
        has_alpha = image_has_alpha(image)
        role = guess_role(path, role_override)
        image_type = guess_image_type(path, image, has_alpha, role)
        width, height = image.size
        for candidate in candidate_list(has_alpha):
            target = candidates_dir / f"{safe_stem(path)}__{candidate.method}{candidate.suffix}"
            save_candidate(image, candidate, target, has_alpha)
            candidate_size = target.stat().st_size
            saved_bytes = original_size - candidate_size
            saved_ratio = saved_bytes / max(original_size, 1)
            size_ratio = candidate_size / max(original_size, 1)
            risk_level, risk_notes, recommended_use = risk_for_candidate(image_type, role, has_alpha, candidate)
            rows.append(
                {
                    "file_name": path.name,
                    "image_type_guess": image_type,
                    "has_alpha": has_alpha,
                    "width": width,
                    "height": height,
                    "original_format": original_format,
                    "original_size_bytes": original_size,
                    "candidate_format": candidate.fmt,
                    "candidate_quality": candidate.quality,
                    "candidate_size_bytes": candidate_size,
                    "saved_bytes": saved_bytes,
                    "saved_ratio": round(saved_ratio, 6),
                    "size_ratio_vs_original": round(size_ratio, 6),
                    "compression_method": candidate.method,
                    "risk_level": risk_level,
                    "risk_notes": risk_notes,
                    "recommended_use": recommended_use,
                    "candidate_path": str(target),
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "file_name",
        "image_type_guess",
        "has_alpha",
        "width",
        "height",
        "original_format",
        "original_size_bytes",
        "candidate_format",
        "candidate_quality",
        "candidate_size_bytes",
        "saved_bytes",
        "saved_ratio",
        "size_ratio_vs_original",
        "compression_method",
        "risk_level",
        "risk_notes",
        "recommended_use",
        "candidate_path",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def average_saved(rows: list[dict[str, object]], method: str) -> str:
    values = [float(row["saved_ratio"]) for row in rows if row["compression_method"] == method]
    if not values:
        return "n/a"
    return f"{mean(values) * 100:.2f}%"


def group_average_table(rows: list[dict[str, object]]) -> list[str]:
    methods = sorted({str(row["compression_method"]) for row in rows})
    lines = ["| Method | Candidates | Average saved ratio |", "| --- | ---: | ---: |"]
    for method in methods:
        subset = [row for row in rows if row["compression_method"] == method]
        lines.append(f"| {method} | {len(subset)} | {average_saved(rows, method)} |")
    return lines


def write_markdown(path: Path, rows: list[dict[str, object]], input_dir: Path, output_dir: Path) -> None:
    sample_names = sorted({str(row["file_name"]) for row in rows})
    transparent_rows = [row for row in rows if row["image_type_guess"] == "transparent_png"]
    preview_rows = [row for row in rows if row["recommended_use"] == "preview_only"]
    high_risk_types = sorted({str(row["image_type_guess"]) for row in rows if row["risk_level"] == "high"})
    c_candidates = [
        row
        for row in rows
        if row["recommended_use"] in {"candidate", "cautious"}
        and row["risk_level"] != "high"
        and float(row["saved_ratio"]) > 0.15
    ]

    lines = [
        "# Output Size Compression Probe Report",
        "",
        f"- Input directory: `{input_dir}`",
        f"- Output directory: `{output_dir}`",
        f"- Sample count: {len(sample_names)}",
        f"- Candidate count: {len(rows)}",
        "",
        "## Average Saved Ratio By Method",
        "",
        *group_average_table(rows),
        "",
        "## Method Notes",
        "",
        f"- PNG optimize: {average_saved(rows, 'png_optimize')}",
        f"- JPG 95: {average_saved(rows, 'jpg_q95')}",
        f"- JPG 92: {average_saved(rows, 'jpg_q92')}",
        f"- JPG 90: {average_saved(rows, 'jpg_q90')}",
        f"- WebP 94: {average_saved(rows, 'webp_q94')}",
        f"- WebP 90: {average_saved(rows, 'webp_q90')}",
        "",
        "## Transparent PNG Conclusion",
        "",
        f"- Transparent PNG candidate rows: {len(transparent_rows)}",
        "- Do not recommend JPG for transparent PNG. PNG optimize keeps alpha; WebP alpha remains an experiment with compatibility risk.",
        "",
        "## Contact Sheet / Preview Conclusion",
        "",
        f"- Preview-only rows: {len(preview_rows)}",
        "- JPG/WebP can be more aggressive for preview/contact sheets, but these results must not represent final output quality.",
        "",
        "## Types Not Recommended For Aggressive Compression",
        "",
        f"- {', '.join(high_risk_types) if high_risk_types else 'None detected by heuristic.'}",
        "",
        "## Patch C Candidate Strategies",
        "",
    ]
    if c_candidates:
        lines.extend(
            [
                "| File | Method | Saved ratio | Risk | Recommended use |",
                "| --- | --- | ---: | --- | --- |",
            ]
        )
        for row in c_candidates[:30]:
            lines.append(
                f"| {row['file_name']} | {row['compression_method']} | {float(row['saved_ratio']) * 100:.2f}% | {row['risk_level']} | {row['recommended_use']} |"
            )
    else:
        lines.append("- No low/medium risk candidate with saved_ratio > 15% was found.")

    lines.extend(
        [
            "",
            "## Formal Pipeline Recommendation",
            "",
            "- Do not connect this probe directly to the formal delivery pipeline.",
            "- Patch C should only consider candidates after visual QA for text, logo, gradients, highlights, alpha edges, and product texture.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    input_dir = args.input_dir.expanduser().resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist: {input_dir}")

    run_dir = args.output_dir.expanduser() / datetime.now().strftime("%Y%m%d_%H%M%S")
    candidates_dir = run_dir / "candidates"
    rows: list[dict[str, object]] = []
    for image_path in iter_images(input_dir, args.recursive):
        rows.extend(probe_image(image_path, candidates_dir, args.role))

    if not rows:
        raise SystemExit(f"No supported images found in: {input_dir}")

    csv_path = run_dir / "compression_probe_results.csv"
    md_path = run_dir / "compression_probe_report.md"
    write_csv(csv_path, rows)
    write_markdown(md_path, rows, input_dir, run_dir)
    print(f"CSV: {csv_path}")
    print(f"Markdown: {md_path}")
    print(f"Candidates: {candidates_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
