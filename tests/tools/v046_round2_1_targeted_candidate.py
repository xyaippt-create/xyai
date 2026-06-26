from __future__ import annotations

import csv
import html
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v046_path_resolver import file_meta, get_v046_path_context


CTX = get_v046_path_context(Path(__file__).resolve())
ROUND2 = CTX.tests_results_dir / "v046_quality_lift_round2_targeted"
OUT = CTX.tests_results_dir / "v046_quality_lift_round2_1_targeted"

DIRS = [
    "01_original",
    "02_frozen",
    "03_round2_candidate",
    "04_round2_1_candidate",
    "05_full_compare",
    "06_same_scale_compare",
    "07_crops_100pct",
    "08_crops_200pct_preview",
    "09_metrics",
    "10_path_index",
    "11_review",
]

FOCUS = {
    "wechat_longscreenshot_2026-06-12_111900_080": "小字、灰字/黑字边缘、字腔、白底和浅灰背景",
    "green_c_product_kv": "包装文字、Logo、透明瓶体、高光、白底、产品轮廓",
    "purple_beauty_product_kv": "DERMAFIRM 字样、紫色品牌色、银色高光、产品边缘、背景渐变",
    "dji_horizontal_infographic": "中文小字、小图标、线条、浅色背景、中间结构和底部信息区",
    "liu_qiangdong_commercial_portrait": "人脸、肤色、发丝、服装纹理、背景城市、中文标题",
    "wei_zhongxian_character_card": "毛发、服饰纹理、小字、红色标签、边框线、暗部",
    "andy_lau_commercial_portrait": "人脸、手部、金色高光、中文小字、碎片边缘、背景低频",
}

TYPE_LABEL = {
    "text_dense_long_screenshot": "文字/信息图",
    "text_dense_infographic": "文字/信息图",
    "product_kv": "产品/商业KV",
    "portrait_poster": "人物/角色海报",
    "character_info_card": "人物/角色海报",
}

STRENGTH = {
    "text_dense_long_screenshot": 0.105,
    "text_dense_infographic": 0.092,
    "product_kv": 0.073,
    "portrait_poster": 0.071,
    "character_info_card": 0.074,
}


def ensure_dirs() -> None:
    for dirname in DIRS:
        (OUT / dirname).mkdir(parents=True, exist_ok=True)


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


def make_candidate(src: Path, dst: Path, kind: str) -> None:
    image = Image.open(src).convert("RGBA")
    arr = np.asarray(image).astype(np.float32)
    rgb = arr[..., :3]
    alpha = arr[..., 3:4]
    lum = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    blur = np.asarray(
        Image.fromarray(np.clip(lum, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius=1.15))
    ).astype(np.float32)
    detail = lum - blur
    abs_detail = np.abs(detail)
    hue, sat, _ = rgb_to_hsv_np(rgb)

    strength = STRENGTH[kind]
    mask = np.ones_like(lum, dtype=np.float32) * strength
    flat = abs_detail < 2.2
    weak_edge = (abs_detail >= 2.2) & (abs_detail < 5.2)
    strong_edge = abs_detail > 54
    highlight_flat = (lum > 224) & (abs_detail < 12.0)
    deep_shadow = lum < 18
    brand_color = (sat > 0.58) & (abs_detail < 13.0)
    smooth_light = (lum > 210) & (sat < 0.13) & (abs_detail < 18.0)
    skin = (
        (hue >= 10)
        & (hue <= 55)
        & (sat > 0.13)
        & (lum > 45)
        & (lum < 235)
        & (rgb[..., 0] >= rgb[..., 1] - 4)
        & (rgb[..., 1] >= rgb[..., 2] - 12)
    )

    if "text" in kind or "infographic" in kind or "card" in kind:
        text_safe_edge = (abs_detail >= 5.2) & (abs_detail <= 42.0) & (lum < 235)
        mask[~text_safe_edge] *= 0.15
        mask[flat | highlight_flat | smooth_light] = 0
        mask[brand_color] *= 0.35
    elif "product" in kind:
        material_edge = (abs_detail >= 4.5) & (abs_detail <= 40.0)
        mask[~material_edge] *= 0.18
        mask[brand_color | highlight_flat | smooth_light | flat] = 0
        mask[lum > 218] *= 0.25
    elif "portrait" in kind:
        material_edge = (abs_detail >= 4.0) & (abs_detail <= 46.0)
        mask[~material_edge] *= 0.18
        mask[skin] *= 0.05
        mask[highlight_flat | smooth_light | flat] = 0

    mask[deep_shadow | strong_edge] *= 0.2
    mask[weak_edge] *= 0.65
    mask[alpha[..., 0] <= 0] = 0

    limited = np.clip(detail, -16.0, 16.0)
    delta = np.clip(limited * mask, -3.4, 3.4)
    new_lum = np.clip(lum + delta, 0, 255)
    scale = np.ones_like(lum)
    np.divide(new_lum, np.maximum(lum, 1.0), out=scale, where=lum >= 1.0)
    out_rgb = np.clip(rgb * scale[..., None], 0, 255)
    out = np.dstack([out_rgb, alpha]).astype(np.uint8)
    Image.fromarray(out, "RGBA").save(dst)


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
        img = Image.open(path).convert("RGB")
        scale = min(1.0, max_panel_w / img.width)
        panel_img = img.resize((round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS)
        panel = Image.new("RGB", (panel_img.width, panel_img.height + 34), (18, 20, 24))
        draw = ImageDraw.Draw(panel)
        draw.text((8, 8), label, fill=(226, 232, 240), font=font)
        panel.paste(panel_img, (0, 34))
        panels.append(panel)
        img.close()
    canvas = Image.new("RGB", (sum(p.width for p in panels), max(p.height for p in panels)), (11, 12, 14))
    x = 0
    for panel in panels:
        canvas.paste(panel, (x, 0))
        x += panel.width
    canvas.save(dst)


def metrics(a: Path, b: Path) -> dict:
    ia = Image.open(a).convert("RGB")
    ib = Image.open(b).convert("RGB")
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
    blur_a = np.asarray(Image.fromarray(np.clip(la, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius=1.15))).astype(np.float32)
    blur_b = np.asarray(Image.fromarray(np.clip(lb, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius=1.15))).astype(np.float32)
    tex_a = np.std(la - blur_a)
    tex_b = np.std(lb - blur_b)
    return {
        "mean_delta_e": round(float(np.mean(diff)), 6),
        "p95_delta_e": round(float(np.percentile(diff, 95)), 6),
        "saturation_delta": round(float(np.mean(sb) - np.mean(sa)), 6),
        "edge_delta_proxy": round(float(edge_b - edge_a), 6),
        "texture_delta_proxy": round(float(tex_b - tex_a), 6),
    }


def make_crops(sample_id: str, frozen: Path, round2: Path, candidate: Path) -> None:
    img = Image.open(frozen)
    w, h = img.size
    img.close()
    defs = [
        ("text_logo", 0.07, 0.12, 0.22, 0.12),
        ("subject_edge", 0.45, 0.32, 0.22, 0.18),
        ("shadow_structure", 0.42, 0.62, 0.22, 0.16),
        ("highlight_flat", 0.72, 0.18, 0.20, 0.16),
        ("material_texture", 0.55, 0.48, 0.22, 0.18),
        ("low_frequency_bg", 0.12, 0.70, 0.22, 0.16),
    ]
    d100 = OUT / "07_crops_100pct" / sample_id
    d200 = OUT / "08_crops_200pct_preview" / sample_id
    d100.mkdir(parents=True, exist_ok=True)
    d200.mkdir(parents=True, exist_ok=True)
    for name, px, py, pw, ph in defs:
        box = (round(w * px), round(h * py), min(w, round(w * (px + pw))), min(h, round(h * (py + ph))))
        for label, path in [("frozen", frozen), ("round2", round2), ("round2_1", candidate)]:
            src = Image.open(path).convert("RGB")
            crop = src.crop(box)
            crop.save(d100 / f"{name}__{label}.png")
            crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.NEAREST).save(
                d200 / f"{name}__{label}__200pct_preview.png"
            )
            src.close()


def classify(row: dict) -> tuple[str, str, str, str]:
    metric = "PASS"
    if row["p95_delta_e"] >= 3.5 or abs(row["saturation_delta"]) > 0.003:
        metric = "FAIL"
    elif row["edge_delta_proxy"] < 0.015 or row["texture_delta_proxy"] < 0.015:
        metric = "WEAK"
    size = "ACCEPTABLE" if row["size_ratio"] <= 1.11 and metric == "PASS" else ("WEAK" if row["size_ratio"] <= 1.15 else "NOT_ACCEPTABLE")
    if metric == "FAIL" or size == "NOT_ACCEPTABLE":
        risk = "REJECT"
        gate = "NO"
    else:
        risk = "REVIEW"
        gate = "WAIT_FOR_HUMAN_REVIEW"
    visual = "MINOR_POSITIVE" if metric == "PASS" and risk == "REVIEW" else "NEEDS_HUMAN_REVIEW"
    return metric, visual, risk, size if gate else size


def copy(src: Path, dst_dir: Path, sample_id: str) -> Path:
    dst = dst_dir / f"{sample_id}{src.suffix.lower()}"
    shutil.copy2(src, dst)
    return dst


def main() -> None:
    ensure_dirs()
    manifest2 = json.loads((ROUND2 / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for item in manifest2:
        sid = item["sample_id"]
        kind = item["kind"]
        original_src = Path(item["original_path"])
        frozen_src = Path(item["frozen_path"])
        round2_src = Path(item["candidate_path"])
        original = copy(original_src, OUT / "01_original", sid)
        frozen = copy(frozen_src, OUT / "02_frozen", sid)
        round2 = copy(round2_src, OUT / "03_round2_candidate", sid)
        candidate = OUT / "04_round2_1_candidate" / f"{sid}.png"
        make_candidate(frozen, candidate, kind)
        make_compare([original, frozen, round2, candidate], ["Original", "Frozen", "Round2", "Round2.1"], OUT / "05_full_compare" / f"{sid}.png")
        make_compare([frozen, round2, candidate], ["Frozen", "Round2", "Round2.1"], OUT / "06_same_scale_compare" / f"{sid}.png", 650)
        make_crops(sid, frozen, round2, candidate)
        m = metrics(frozen, candidate)
        m2_delta = metrics(round2, candidate)
        row = {
            "sample_id": sid,
            "sample_type": TYPE_LABEL.get(kind, kind),
            "kind": kind,
            "original_path": str(original),
            "frozen_path": str(frozen),
            "round2_candidate_path": str(round2),
            "round2_1_candidate_path": str(candidate),
            "full_compare_path": str(OUT / "05_full_compare" / f"{sid}.png"),
            "same_scale_compare_path": str(OUT / "06_same_scale_compare" / f"{sid}.png"),
            "crop_100_path": str(OUT / "07_crops_100pct" / sid),
            "crop_200_path": str(OUT / "08_crops_200pct_preview" / sid),
            "metrics_json_path": str(OUT / "09_metrics" / f"{sid}.json"),
            "focus": FOCUS[sid],
            "round2_edge_delta_proxy": item["edge_delta_proxy"],
            "round2_texture_delta_proxy": item["texture_delta_proxy"],
            "round2_p95_delta_e": item["p95_delta_e"],
            "round2_saturation_delta": item["saturation_delta"],
            "round2_size_ratio": item["candidate_size_ratio"],
            "edge_delta_proxy": m["edge_delta_proxy"],
            "texture_delta_proxy": m["texture_delta_proxy"],
            "p95_delta_e": m["p95_delta_e"],
            "saturation_delta": m["saturation_delta"],
            "mean_delta_e": m["mean_delta_e"],
            "round2_to_round2_1_p95_delta_e": m2_delta["p95_delta_e"],
            "round2_to_round2_1_saturation_delta": m2_delta["saturation_delta"],
            "frozen_size_bytes": frozen.stat().st_size,
            "round2_size_bytes": round2.stat().st_size,
            "round2_1_size_bytes": candidate.stat().st_size,
            "size_ratio": round(candidate.stat().st_size / max(1, frozen.stat().st_size), 6),
            "size_delta_vs_round2_bytes": candidate.stat().st_size - round2.stat().st_size,
        }
        metric, visual, risk, size = classify(row)
        row["evidence_complete"] = "PASS"
        row["metric_judgement"] = metric
        row["visual_review_required"] = "YES"
        row["visual_prejudgement"] = visual
        row["risk_status"] = risk
        row["size_benefit_ratio_judgement"] = size
        row["gate_to_19"] = "WAIT_FOR_HUMAN_REVIEW" if risk == "REVIEW" else "NO"
        row["notes"] = "Round 2.1 为离线安全局部中频微调；需要人工查看裁切确认真实肉眼收益和风险。"
        rows.append(row)
        (OUT / "09_metrics" / f"{sid}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")

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
        for key in ["original_path", "frozen_path", "round2_candidate_path", "round2_1_candidate_path", "full_compare_path", "same_scale_compare_path", "metrics_json_path"]:
            path_index["files"].append(file_meta(Path(row[key]), f"{row['sample_id']}:{key}", CTX))
    (OUT / "10_path_index" / "path_index.json").write_text(json.dumps(path_index, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"samples": len(rows), "out": str(OUT), "metric_pass": sum(1 for r in rows if r["metric_judgement"] == "PASS")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
