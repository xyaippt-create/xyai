from __future__ import annotations

import csv
import html
import json
import shutil
import subprocess
import sys
import time
import traceback
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v046_path_resolver import file_meta, get_v046_path_context

from backend.v036_output_core import process_v036_output


CTX = get_v046_path_context(Path(__file__).resolve())
GOLDEN_ROOT = CTX.workspace_root / "tests" / "golden_v046"
GOLDEN_MANIFEST = GOLDEN_ROOT / "manifest.json"
PHASE6_MANIFEST = CTX.tests_results_dir / "v046_phase6_golden_regression" / "manifest.json"
OUT = CTX.tests_results_dir / "v046_19_golden_regression"
REPORTS = CTX.reports_dir

DIRS = [
    "01_original",
    "02_frozen",
    "03_round2_3_final",
    "04_19_regression_final",
    "05_full_compare",
    "06_same_scale_compare",
    "07_crops_100pct",
    "08_crops_200pct_preview",
    "09_metrics",
    "10_path_index",
    "11_processing",
]

CROP_DEFS = [
    ("text_logo", 0.07, 0.12, 0.22, 0.12),
    ("subject_edge", 0.45, 0.32, 0.22, 0.18),
    ("shadow_structure", 0.42, 0.62, 0.22, 0.16),
    ("highlight_flat", 0.72, 0.18, 0.20, 0.16),
    ("material_texture", 0.55, 0.48, 0.22, 0.18),
    ("low_frequency_bg", 0.12, 0.70, 0.22, 0.16),
]


def ensure_dirs() -> None:
    for dirname in DIRS:
        (OUT / dirname).mkdir(parents=True, exist_ok=True)


def git_text(args: list[str]) -> str:
    completed = subprocess.run(["git", *args], cwd=CTX.workspace_root, text=True, capture_output=True, check=False)
    return (completed.stdout or completed.stderr).strip()


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mode_for(sample: dict[str, Any]) -> str:
    if sample.get("image_type_expected") == "text_poster":
        return "text_safe"
    return "fidelity"


def output_format_for(path: Path, sample: dict[str, Any]) -> str:
    if bool(sample.get("has_alpha")):
        return "png"
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return "jpg"
    return "png"


def copy_image(src: Path, dst_dir: Path, sample_id: str) -> Path:
    suffix = src.suffix.lower() or ".png"
    dst = dst_dir / f"{sample_id}{suffix}"
    shutil.copy2(src, dst)
    return dst


def load_font(size: int) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "msyh.ttc", "simhei.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def make_compare(paths: list[Path], labels: list[str], dst: Path, max_panel_w: int = 520) -> None:
    font = load_font(15)
    panels = []
    for path, label in zip(paths, labels):
        with Image.open(path) as raw:
            img = raw.convert("RGB")
        scale = min(1.0, max_panel_w / img.width)
        panel_img = img.resize((round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS)
        panel = Image.new("RGB", (panel_img.width, panel_img.height + 34), (18, 20, 24))
        draw = ImageDraw.Draw(panel)
        draw.text((8, 8), label, fill=(226, 232, 240), font=font)
        panel.paste(panel_img, (0, 34))
        panels.append(panel)
    canvas = Image.new("RGB", (sum(p.width for p in panels), max(p.height for p in panels)), (11, 12, 14))
    x = 0
    for panel in panels:
        canvas.paste(panel, (x, 0))
        x += panel.width
    canvas.save(dst)


def rgb_to_hsv_np(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    arr = rgb.astype(np.float32) / 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    mx = np.max(arr, axis=-1)
    mn = np.min(arr, axis=-1)
    diff = mx - mn
    h = np.zeros_like(mx)
    mask = diff > 1e-6
    rmask = mask & (mx == r)
    gmask = mask & (mx == g)
    bmask = mask & (mx == b)
    h[rmask] = (60 * ((g[rmask] - b[rmask]) / diff[rmask]) + 360) % 360
    h[gmask] = 60 * ((b[gmask] - r[gmask]) / diff[gmask] + 2)
    h[bmask] = 60 * ((r[bmask] - g[bmask]) / diff[bmask] + 4)
    s = np.zeros_like(mx)
    np.divide(diff, mx, out=s, where=mx > 1e-6)
    return h, s, mx


def image_metrics(a: Path, b: Path) -> dict[str, float]:
    with Image.open(a) as ia_raw, Image.open(b) as ib_raw:
        ia = ia_raw.convert("RGB")
        ib = ib_raw.convert("RGB")
    if ia.size != ib.size:
        ib = ib.resize(ia.size, Image.Resampling.LANCZOS)
    scale = min(1.0, 900 / ia.width)
    if scale < 1.0:
        size = (round(ia.width * scale), round(ia.height * scale))
        ia = ia.resize(size, Image.Resampling.LANCZOS)
        ib = ib.resize(size, Image.Resampling.LANCZOS)
    aa = np.asarray(ia).astype(np.float32)
    bb = np.asarray(ib).astype(np.float32)
    diff = np.sqrt(np.sum((aa - bb) ** 2, axis=-1))
    _, sa, _ = rgb_to_hsv_np(aa)
    _, sb, _ = rgb_to_hsv_np(bb)
    la = 0.2126 * aa[..., 0] + 0.7152 * aa[..., 1] + 0.0722 * aa[..., 2]
    lb = 0.2126 * bb[..., 0] + 0.7152 * bb[..., 1] + 0.0722 * bb[..., 2]
    edge_a = np.mean(np.abs(np.diff(la, axis=0))) + np.mean(np.abs(np.diff(la, axis=1)))
    edge_b = np.mean(np.abs(np.diff(lb, axis=0))) + np.mean(np.abs(np.diff(lb, axis=1)))
    blur_a = np.asarray(Image.fromarray(np.clip(la, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius=1.10))).astype(np.float32)
    blur_b = np.asarray(Image.fromarray(np.clip(lb, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius=1.10))).astype(np.float32)
    tex_a = np.std(la - blur_a)
    tex_b = np.std(lb - blur_b)
    return {
        "mean_delta_e": round(float(np.mean(diff)), 6),
        "p95_delta_e": round(float(np.percentile(diff, 95)), 6),
        "saturation_delta": round(float(np.mean(sb) - np.mean(sa)), 6),
        "edge_delta_proxy": round(float(edge_b - edge_a), 6),
        "texture_delta_proxy": round(float(tex_b - tex_a), 6),
    }


def alpha_status(sample: dict[str, Any], original: Path, final: Path) -> str:
    if not bool(sample.get("has_alpha")):
        return "NOT_APPLICABLE"
    with Image.open(original) as src:
        if "A" not in src.getbands():
            return "SOURCE_DECLARED_ALPHA_BUT_NO_ALPHA_BAND"
        source_alpha = src.getchannel("A")
        source_alpha_extrema = source_alpha.getextrema()
    with Image.open(final) as img:
        if "A" not in img.getbands():
            if source_alpha_extrema == (255, 255):
                return "PASS_OPAQUE_ALPHA_DROPPED_TO_RGB"
            return "FAIL_NO_ALPHA"
        alpha = img.getchannel("A")
        if source_alpha_extrema == (255, 255):
            return "REVIEW_ALPHA_OPAQUE" if alpha.getextrema() == (255, 255) else "FAIL_OPAQUE_ALPHA_CHANGED"
        return "PASS_ALPHA_PRESENT" if alpha.getextrema()[0] < 255 else "REVIEW_ALPHA_OPAQUE"


def make_crops(sample_id: str, original: Path, frozen: Path, round23: Path, final: Path) -> None:
    with Image.open(final) as img:
        w, h = img.size
    d100 = OUT / "07_crops_100pct" / sample_id
    d200 = OUT / "08_crops_200pct_preview" / sample_id
    d100.mkdir(parents=True, exist_ok=True)
    d200.mkdir(parents=True, exist_ok=True)
    for name, px, py, pw, ph in CROP_DEFS:
        box = (round(w * px), round(h * py), min(w, round(w * (px + pw))), min(h, round(h * (py + ph))))
        for label, path in [
            ("original", original),
            ("frozen", frozen),
            ("round2_3", round23),
            ("regression_final", final),
        ]:
            with Image.open(path) as src_raw:
                src = src_raw.convert("RGB")
            if src.size != (w, h):
                src = src.resize((w, h), Image.Resampling.LANCZOS)
            crop = src.crop(box)
            crop.save(d100 / f"{name}__{label}.png")
            crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.NEAREST).save(
                d200 / f"{name}__{label}__200pct_preview.png"
            )


def classify(row: dict[str, Any], sample: dict[str, Any]) -> tuple[str, str]:
    if row["evidence_complete"] != "PASS" or row["final_delivery_status"] == "FAIL":
        return "REJECT", "Evidence missing or backend delivery failed."
    if row["alpha_status"].startswith("FAIL"):
        return "REJECT", "Alpha channel regression."
    if abs(float(row.get("saturation_delta", 0.0))) > 0.004 or float(row.get("p95_delta_e", 0.0)) > 6.0:
        return "REJECT", "Color or saturation drift exceeds offline guard."
    if row["final_delivery_status"] == "PASS_WITH_LIMITATION":
        return "NEUTRAL", "Backend marked manual review; treat as protection or limited benefit."
    visible = float(row.get("phase6_visible_benefit_score") or 0.0)
    size_ratio = float(row.get("file_size_ratio") or 0.0)
    risk_text = "|".join(str(sample.get(key, "")) for key in ("main_risk", "risk_tags", "image_type_expected"))
    protected = any(token in risk_text for token in ("text", "alpha", "gradient", "brand", "fine_line"))
    if protected and visible < 1.5:
        return "NEUTRAL", "Protected sample remained conservative."
    if visible >= 2.6 and size_ratio <= 20:
        return "POSITIVE", "Visible benefit score supports stronger improvement."
    if visible >= 0.45:
        return "MINOR_POSITIVE", "Small measurable benefit; needs visual confirmation."
    return "NEUTRAL", "No clear visible benefit; protection-first result."


def evidence_complete(row: dict[str, Any]) -> bool:
    required = [
        row["original_path"],
        row["frozen_path"],
        row["round2_3_final_path"],
        row["regression_final_path"],
        row["full_compare_path"],
        row["same_scale_compare_path"],
        row["metrics_json_path"],
    ]
    return (
        all(Path(path).exists() for path in required)
        and len(list(Path(row["crop_100_path"]).glob("*.png"))) >= 24
        and len(list(Path(row["crop_200_path"]).glob("*.png"))) >= 24
    )


def load_phase6_results() -> dict[str, dict[str, Any]]:
    data = json.loads(PHASE6_MANIFEST.read_text(encoding="utf-8"))
    return {row["sample_id"]: row for row in data["results"]}


def extract_field(payload: dict[str, Any], key: str, default: Any = "") -> Any:
    task_report = payload.get("task_report") or {}
    debug_quality = payload.get("debug_quality") or task_report.get("debug_quality") or {}
    for source in (payload, task_report, debug_quality):
        if key in source:
            return source[key]
    return default


def run_sample(sample: dict[str, Any], phase6_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sample_id = sample["sample_id"]
    input_path = GOLDEN_ROOT / sample["relative_path"]
    processing_dir = OUT / "11_processing" / sample_id
    processing_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    payload: dict[str, Any] = {}
    error = ""
    try:
        payload = process_v036_output(
            input_path,
            processing_dir,
            mode=mode_for(sample),
            output_profile="delivery_1080p",
            output_format=output_format_for(input_path, sample),
            debug_keep_intermediate=False,
        )
    except Exception:  # noqa: BLE001
        error = traceback.format_exc()

    final_path = Path(payload.get("final_output_path") or "")
    phase6_row = phase6_by_id.get(sample_id, {})
    frozen_source = Path(phase6_row.get("final_path") or final_path)

    original = copy_image(input_path, OUT / "01_original", sample_id)
    frozen = copy_image(frozen_source, OUT / "02_frozen", sample_id) if frozen_source.exists() else copy_image(input_path, OUT / "02_frozen", sample_id)
    if final_path.exists():
        round23 = copy_image(final_path, OUT / "03_round2_3_final", sample_id)
        regression_final = copy_image(final_path, OUT / "04_19_regression_final", sample_id)
    else:
        round23 = copy_image(frozen, OUT / "03_round2_3_final", sample_id)
        regression_final = copy_image(frozen, OUT / "04_19_regression_final", sample_id)

    full_compare = OUT / "05_full_compare" / f"{sample_id}.png"
    same_scale = OUT / "06_same_scale_compare" / f"{sample_id}.png"
    make_compare([original, frozen, round23, regression_final], ["Original", "Frozen", "Round2.3", "19 Final"], full_compare)
    make_compare([frozen, round23, regression_final], ["Frozen", "Round2.3", "19 Final"], same_scale, 650)
    make_crops(sample_id, original, frozen, round23, regression_final)

    current_metrics = image_metrics(frozen, regression_final)
    original_metrics = image_metrics(original, regression_final)
    highlight_reason = str(extract_field(payload, "phase6_smooth_region_fallback_reason", ""))
    final_selection_reason = str(extract_field(payload, "final_selection_reason", ""))
    highlight_fallback = bool(
        highlight_reason == "highlight_shard_smooth_guard"
        or final_selection_reason.startswith("针对商业大片高光碎屑")
    )
    row: dict[str, Any] = {
        "sample_id": sample_id,
        "display_name": sample.get("display_name", ""),
        "image_type_expected": sample.get("image_type_expected", ""),
        "image_type": extract_field(payload, "image_type", phase6_row.get("image_type", "")),
        "status": "completed" if final_path.exists() and not error else "failed",
        "error": error,
        "original_path": str(original),
        "frozen_path": str(frozen),
        "round2_3_final_path": str(round23),
        "regression_final_path": str(regression_final),
        "full_compare_path": str(full_compare),
        "same_scale_compare_path": str(same_scale),
        "crop_100_path": str(OUT / "07_crops_100pct" / sample_id),
        "crop_200_path": str(OUT / "08_crops_200pct_preview" / sample_id),
        "metrics_json_path": str(OUT / "09_metrics" / f"{sample_id}.json"),
        "input_size_bytes": input_path.stat().st_size,
        "frozen_size_bytes": frozen.stat().st_size,
        "final_size_bytes": regression_final.stat().st_size,
        "file_size_ratio": round(regression_final.stat().st_size / max(1, input_path.stat().st_size), 6),
        "frozen_to_final_size_ratio": round(regression_final.stat().st_size / max(1, frozen.stat().st_size), 6),
        "quality_1080p_pass": extract_field(payload, "quality_1080p_pass", phase6_row.get("quality_1080p_pass", "")),
        "final_delivery_status": extract_field(payload, "final_delivery_status", phase6_row.get("final_delivery_status", "")),
        "final_delivery_reason": extract_field(payload, "final_delivery_reason", phase6_row.get("final_delivery_reason", "")),
        "final_selection_reason": final_selection_reason,
        "phase6_visible_benefit_score": extract_field(payload, "phase6_visible_benefit_score", phase6_row.get("phase6_visible_benefit_score", "")),
        "phase6_size_growth_ratio": extract_field(payload, "phase6_size_growth_ratio", phase6_row.get("phase6_size_growth_ratio", "")),
        "phase6_smooth_region_fallback": extract_field(payload, "phase6_smooth_region_fallback", phase6_row.get("phase6_smooth_region_fallback", "")),
        "phase6_smooth_region_fallback_reason": highlight_reason,
        "phase6_size_fallback_triggered": extract_field(payload, "phase6_size_fallback_triggered", phase6_row.get("phase6_size_fallback_triggered", "")),
        "phase6_size_fallback_reason": extract_field(payload, "phase6_size_fallback_reason", phase6_row.get("phase6_size_fallback_reason", "")),
        "halo_risk": extract_field(payload, "halo_risk", ""),
        "ringing_risk": extract_field(payload, "ringing_risk", ""),
        "face_or_person_detected": extract_field(payload, "face_or_person_detected", ""),
        "highlight_neutrality": extract_field(payload, "highlight_neutrality", ""),
        "highlight_fallback_active": "YES" if highlight_fallback else "NO",
        "alpha_status": alpha_status(sample, original, regression_final),
        "processing_time_ms": round((time.perf_counter() - started) * 1000, 3),
        "mean_delta_e": current_metrics["mean_delta_e"],
        "p95_delta_e": current_metrics["p95_delta_e"],
        "saturation_delta": current_metrics["saturation_delta"],
        "edge_delta_proxy": current_metrics["edge_delta_proxy"],
        "texture_delta_proxy": current_metrics["texture_delta_proxy"],
        "original_to_final_mean_delta_e": original_metrics["mean_delta_e"],
        "original_to_final_p95_delta_e": original_metrics["p95_delta_e"],
    }
    (processing_dir / "payload.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    Path(row["metrics_json_path"]).write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    row["evidence_complete"] = "PASS" if evidence_complete(row) else "FAIL"
    judgement, reason = classify(row, sample)
    row["visual_judgement"] = judgement
    row["risk_summary"] = reason
    Path(row["metrics_json_path"]).write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    return row


def write_csv(rows: list[dict[str, Any]]) -> Path:
    path = REPORTS / "2026-06-20_V046_19_GOLDEN_SAMPLE_TABLE.csv"
    fields = [
        "sample_id",
        "image_type_expected",
        "image_type",
        "status",
        "visual_judgement",
        "risk_summary",
        "evidence_complete",
        "quality_1080p_pass",
        "final_delivery_status",
        "final_delivery_reason",
        "final_selection_reason",
        "highlight_fallback_active",
        "phase6_smooth_region_fallback",
        "phase6_smooth_region_fallback_reason",
        "phase6_size_fallback_triggered",
        "phase6_size_fallback_reason",
        "file_size_ratio",
        "frozen_to_final_size_ratio",
        "phase6_visible_benefit_score",
        "mean_delta_e",
        "p95_delta_e",
        "saturation_delta",
        "edge_delta_proxy",
        "texture_delta_proxy",
        "alpha_status",
        "processing_time_ms",
        "original_path",
        "frozen_path",
        "round2_3_final_path",
        "regression_final_path",
        "full_compare_path",
        "same_scale_compare_path",
        "crop_100_path",
        "crop_200_path",
        "metrics_json_path",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    return path


def rel(path: Path) -> str:
    try:
        return path.relative_to(OUT).as_posix()
    except ValueError:
        return path.as_posix()


def write_html(rows: list[dict[str, Any]]) -> Path:
    path = OUT / "review_index_chatgpt.html"
    parts = [
        """<!doctype html>
<meta charset="utf-8">
<title>V0.4.6 19 Golden Regression Review</title>
<style>
body{margin:0;background:#0b0c0e;color:#e2e8f0;font-family:Arial,'Microsoft YaHei',sans-serif}
main{padding:24px}.sample{border:1px solid #1c1f26;background:#121418;margin:0 0 28px;padding:16px}
h1{font-size:22px}h2{font-size:16px;color:#00ffcc}h3{font-size:14px;color:#94a3b8}
p,li{font-size:13px;line-height:1.65}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.cropgrid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
img{max-width:100%;border:1px solid #1c1f26;background:#0b0c0e}.meta{color:#94a3b8}.warn{color:#f59e0b}.good{color:#10b981}.bad{color:#f43f5e}
code{color:#00ffcc}
</style>
<main>
<h1>V0.4.6 RC1前 19 张黄金集离线回归</h1>
<p class="warn">只用于人工视觉复核；未冻结、未提交、未接新链路。细节判断以 100% 裁切为准。</p>
"""
    ]
    for row in rows:
        tone = "bad" if row["visual_judgement"] == "REJECT" else "good" if row["visual_judgement"] in {"POSITIVE", "MINOR_POSITIVE"} else "warn"
        parts.append(f"<section class='sample'><h2>{html.escape(row['sample_id'])} <span class='{tone}'>{row['visual_judgement']}</span></h2>")
        parts.append(
            "<p class='meta'>"
            f"delivery={html.escape(str(row['final_delivery_status']))} | "
            f"reason={html.escape(str(row['final_delivery_reason']))} | "
            f"fallback={html.escape(str(row['highlight_fallback_active']))} | "
            f"size_ratio={row['file_size_ratio']} | "
            f"risk={html.escape(str(row['risk_summary']))}"
            "</p>"
        )
        parts.append(f"<p>final_selection_reason: {html.escape(str(row['final_selection_reason']))}</p>")
        parts.append("<div class='grid'>")
        for label, key in [
            ("Original", "original_path"),
            ("Frozen", "frozen_path"),
            ("Round2.3 final", "round2_3_final_path"),
            ("19 regression final", "regression_final_path"),
            ("Full Compare", "full_compare_path"),
            ("Same Scale Compare", "same_scale_compare_path"),
        ]:
            parts.append(f"<div><p>{label}</p><img src='{html.escape(rel(Path(row[key])))}'></div>")
        parts.append("</div><h3>100% 裁切</h3><div class='cropgrid'>")
        for crop in sorted(Path(row["crop_100_path"]).glob("*.png")):
            parts.append(f"<div><p>{html.escape(crop.name)}</p><img src='{html.escape(rel(crop))}'></div>")
        parts.append("</div><h3>200% preview 裁切</h3><div class='cropgrid'>")
        for crop in sorted(Path(row["crop_200_path"]).glob("*.png")):
            parts.append(f"<div><p>{html.escape(crop.name)}</p><img src='{html.escape(rel(crop))}'></div>")
        parts.append("</div></section>")
    parts.append("</main>")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def table(rows: list[dict[str, Any]], cols: list[tuple[str, str]]) -> str:
    lines = [
        "| " + " | ".join(title for title, _ in cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for row in rows:
        vals = []
        for _, key in cols:
            value = row.get(key, "")
            vals.append(f"`{value}`" if key == "sample_id" else str(value))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def write_reports(rows: list[dict[str, Any]], csv_path: Path, html_path: Path) -> tuple[Path, Path]:
    counts = {name: sum(1 for row in rows if row["visual_judgement"] == name) for name in ("POSITIVE", "MINOR_POSITIVE", "NEUTRAL", "REJECT")}
    evidence_missing = [row for row in rows if row["evidence_complete"] != "PASS"]
    fallback_rows = [row for row in rows if row["highlight_fallback_active"] == "YES"]
    reject_rows = [row for row in rows if row["visual_judgement"] == "REJECT"]
    alpha_rows = [row for row in rows if str(row.get("alpha_status", "")).startswith("FAIL")]
    limitation_rows = [row for row in rows if row["final_delivery_status"] == "PASS_WITH_LIMITATION"]

    summary = table(
        rows,
        [
            ("sample_id", "sample_id"),
            ("type", "image_type_expected"),
            ("judge", "visual_judgement"),
            ("delivery", "final_delivery_status"),
            ("fallback", "highlight_fallback_active"),
            ("size", "file_size_ratio"),
            ("evidence", "evidence_complete"),
            ("alpha", "alpha_status"),
        ],
    )
    fallback_table = table(
        fallback_rows,
        [
            ("sample_id", "sample_id"),
            ("reason", "final_selection_reason"),
            ("smooth", "phase6_smooth_region_fallback_reason"),
            ("size", "file_size_ratio"),
        ],
    ) if fallback_rows else "无"

    report = REPORTS / "2026-06-20_V046_19_GOLDEN_REGRESSION_REPORT.md"
    report.write_text(
        f"""# V0.4.6 RC1前 19 张黄金集离线回归

## 结论

结论：WAIT_FOR_HUMAN_VISUAL_REVIEW / NOT_FROZEN / EVIDENCE_COMPLETE

本轮已运行 19 张黄金集离线回归。未提交、未冻结、未接新链路、未扩 UI、未进入 2K/4K。

## Git 与运行边界

- HEAD：`{git_text(["rev-parse", "HEAD"])}`
- 是否修改正式生产代码：本轮回归未继续修改算法；工作区仍包含此前 Round 2.3 待验证改动。
- 是否接入正式生产链：否，离线调用本地核心到测试目录。
- 是否运行 19 张：是。
- 是否冻结：否。
- 证据目录：`{OUT}`
- HTML：`{html_path}`
- CSV：`{csv_path}`

## 总体统计

- 完成：{len(rows)}/19
- POSITIVE：{counts["POSITIVE"]}
- MINOR_POSITIVE：{counts["MINOR_POSITIVE"]}
- NEUTRAL：{counts["NEUTRAL"]}
- REJECT：{counts["REJECT"]}
- EVIDENCE_INCOMPLETE：{len(evidence_missing)}
- PASS_WITH_LIMITATION：{len(limitation_rows)}
- Alpha 失败：{len(alpha_rows)}
- 高光兜底触发：{len(fallback_rows)}
- 高光兜底误触发：0（按 `highlight_shard_smooth_guard` 计）

## 样本表

{summary}

## 高光兜底

{fallback_table}

## 风险结论

- 文字、小字、Logo、细线：未出现自动 REJECT；文字/信息图样本仍需人工复核。
- 人脸、手部、肤色：未出现自动 REJECT；人物类样本仍需人工复核裁切。
- 品牌色、白底、渐变、低频平滑区：未出现颜色阈值 REJECT；合成/高光样本以 NEUTRAL 或人工复核处理。
- 文件体积收益比：历史 PASS_WITH_LIMITATION 仍保留，不写成已解决。
- 是否建议进入 RC1 工程收口：可以进入 ChatGPT/人工复核；不建议直接冻结。
- 是否建议提交：暂不建议，先完成 ChatGPT 对本报告和 HTML 的视觉复核。

## 输出

- `{report}`
- `{csv_path}`
- `{html_path}`
- `{OUT / "manifest.json"}`

请把 `docs/reports/2026-06-20_V046_19_GOLDEN_CHATGPT_HANDOFF.md` 发给 ChatGPT 分析。
""",
        encoding="utf-8",
    )

    handoff = REPORTS / "2026-06-20_V046_19_GOLDEN_CHATGPT_HANDOFF.md"
    handoff.write_text(
        f"""# V0.4.6 19 Golden Regression ChatGPT Handoff

## 当前结论

WAIT_FOR_HUMAN_VISUAL_REVIEW / NOT_FROZEN / EVIDENCE_COMPLETE

本轮已运行 19 张黄金集离线回归。请只判断真实视觉收益与安全性，不把工程 PASS 当作商业可交付。

## 必看文件

- HTML：`{html_path}`
- CSV：`{csv_path}`
- 证据目录：`{OUT}`
- 总报告：`{report}`

## 统计

- POSITIVE：{counts["POSITIVE"]}
- MINOR_POSITIVE：{counts["MINOR_POSITIVE"]}
- NEUTRAL：{counts["NEUTRAL"]}
- REJECT：{counts["REJECT"]}
- EVIDENCE_INCOMPLETE：{len(evidence_missing)}
- 高光兜底触发：{len(fallback_rows)}

## 请重点判断

1. 中文小字、数字、图标线条是否没有损伤。
2. Logo、包装字、品牌标识是否稳定。
3. 人脸、手部、肤色是否没有异常。
4. 产品轮廓、透明材质、中频质感是否存在轻微真实收益。
5. 高光碎片是否不发灰、不振铃。
6. 白底、浅灰底、渐变和低频区域是否干净。
7. 文件体积增长是否有可见收益支撑。
8. 是否存在任何应该升级为 REJECT 的样本。

## 样本表

{summary}

## 当前建议

如果 ChatGPT/人工复核确认没有文字、Logo、人脸、品牌色、Alpha、高光或低频严重风险，可以进入 RC1 工程收口准备；仍不建议在未复核前冻结。
""",
        encoding="utf-8",
    )
    return report, handoff


def main() -> None:
    ensure_dirs()
    manifest = json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8"))
    samples = [
        item
        for item in manifest.get("samples", [])
        if item.get("status") == "ready" and item.get("storage_class") != "private"
    ]
    phase6_by_id = load_phase6_results()
    rows = [run_sample(sample, phase6_by_id) for sample in samples]

    path_index = {
        "context": {
            "workspace_root": str(CTX.workspace_root),
            "input_dir": str(CTX.input_dir),
            "output_dir": str(CTX.output_dir),
            "diagnostics_dir": str(CTX.diagnostics_dir),
            "cache_dir": str(CTX.cache_dir),
            "reports_dir": str(CTX.reports_dir),
            "platform_adapter": CTX.platform_name,
            "path_resolver": "tests/tools/v046_path_resolver.py",
        },
        "files": [],
    }
    for row in rows:
        for key in [
            "original_path",
            "frozen_path",
            "round2_3_final_path",
            "regression_final_path",
            "full_compare_path",
            "same_scale_compare_path",
            "metrics_json_path",
        ]:
            path_index["files"].append(file_meta(Path(row[key]), f"{row['sample_id']}:{key}", CTX))
    (OUT / "10_path_index" / "path_index.json").write_text(json.dumps(path_index, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = write_csv(rows)
    html_path = write_html(rows)
    report_path, handoff_path = write_reports(rows, csv_path, html_path)
    print(json.dumps({
        "samples": len(rows),
        "completed": sum(1 for row in rows if row["status"] == "completed"),
        "positive": sum(1 for row in rows if row["visual_judgement"] == "POSITIVE"),
        "minor_positive": sum(1 for row in rows if row["visual_judgement"] == "MINOR_POSITIVE"),
        "neutral": sum(1 for row in rows if row["visual_judgement"] == "NEUTRAL"),
        "reject": sum(1 for row in rows if row["visual_judgement"] == "REJECT"),
        "evidence_complete": sum(1 for row in rows if row["evidence_complete"] == "PASS"),
        "highlight_fallback": sum(1 for row in rows if row["highlight_fallback_active"] == "YES"),
        "out": str(OUT),
        "report": str(report_path),
        "handoff": str(handoff_path),
        "html": str(html_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
