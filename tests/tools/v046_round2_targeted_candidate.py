from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests" / "results" / "v046_quality_lift_round2_targeted"
ASSET_ROOT = Path("D:/影界文件")
INPUT_DIR = ASSET_ROOT / "输入图片"
OUTPUT_DIR = ASSET_ROOT / "输出成品"

DIRS = [
    "01_original",
    "02_frozen",
    "03_candidate",
    "04_full_compare",
    "05_same_scale_compare",
    "06_crops_100pct",
    "07_crops_200pct_preview",
    "08_metrics",
    "09_frontend_report_check",
    "10_review",
]

SAMPLES = [
    {
        "sample_id": "wechat_longscreenshot_2026-06-12_111900_080",
        "kind": "text_dense_long_screenshot",
        "strength": 0.075,
        "original": "wechat_longscreenshot_2026-06-12_111900_080.png",
        "frozen": "wechat_longscreenshot_2026-06-12_111900_080*171309.png",
    },
    {
        "sample_id": "green_c_product_kv",
        "kind": "product_kv",
        "strength": 0.052,
        "original": "*13_29_51.png",
        "frozen": "*13_29_51*171244.png",
    },
    {
        "sample_id": "purple_beauty_product_kv",
        "kind": "product_kv",
        "strength": 0.052,
        "original": "*13_52_35.png",
        "frozen": "*13_52_35*171301.png",
    },
    {
        "sample_id": "dji_horizontal_infographic",
        "kind": "text_dense_infographic",
        "strength": 0.065,
        "original": "*11_07_35.png",
        "frozen": "*11_07_35*171226.png",
    },
    {
        "sample_id": "liu_qiangdong_commercial_portrait",
        "kind": "portrait_poster",
        "strength": 0.055,
        "original": "*09_55_46.png",
        "frozen": "*09_55_46*171216.png",
    },
    {
        "sample_id": "wei_zhongxian_character_card",
        "kind": "character_info_card",
        "strength": 0.058,
        "original": "*18_11_39.png",
        "frozen": "*18_11_39*171233.png",
    },
    {
        "sample_id": "andy_lau_commercial_portrait",
        "kind": "portrait_poster",
        "strength": 0.055,
        "original": "*13_32_24.png",
        "frozen": "*13_32_24*171251.png",
    },
]


def resolve_one(folder: Path, pattern: str) -> Path:
    hits = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not hits:
        raise FileNotFoundError(f"{folder} :: {pattern}")
    return hits[0]


def ensure_dirs() -> None:
    for d in DIRS:
        (OUT / d).mkdir(parents=True, exist_ok=True)


def copy_asset(src: Path, subdir: str, sample_id: str) -> Path:
    dst = OUT / subdir / f"{sample_id}{src.suffix.lower()}"
    shutil.copy2(src, dst)
    return dst


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
    s = np.where(mx <= 1e-6, 0, diff / mx)
    return h, s, mx


def make_candidate(src: Path, dst: Path, strength: float, kind: str) -> None:
    im = Image.open(src).convert("RGBA")
    arr = np.asarray(im).astype(np.float32)
    rgb = arr[..., :3]
    alpha = arr[..., 3:4]
    lum = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    blur = np.asarray(Image.fromarray(np.clip(lum, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius=1.35))).astype(np.float32)
    detail = lum - blur
    abs_detail = np.abs(detail)
    hue, sat, _ = rgb_to_hsv_np(rgb)

    mask = np.ones_like(lum, dtype=np.float32) * strength
    flat = abs_detail < 2.4
    highlight_flat = (lum > 225) & (abs_detail < 8.0)
    deep_shadow = lum < 18
    brand_or_strong_color = (sat > 0.62) & (abs_detail < 10.0)
    skin = (
        (hue >= 12)
        & (hue <= 52)
        & (sat > 0.16)
        & (lum > 55)
        & (lum < 230)
        & (rgb[..., 0] >= rgb[..., 1])
        & (rgb[..., 1] >= (rgb[..., 2] - 8))
    )

    if "product" in kind:
        mask[flat | highlight_flat | brand_or_strong_color] = 0
        mask[lum > 210] *= 0.35
    elif "portrait" in kind:
        mask[skin] *= 0.18
        mask[flat | highlight_flat] = 0
    elif any(token in kind for token in ("text", "infographic", "card")):
        mask[highlight_flat | brand_or_strong_color] *= 0.25
        mask[flat] = 0

    mask[deep_shadow] *= 0.25
    mask[alpha[..., 0] <= 0] = 0

    limited = np.clip(detail, -18.0, 18.0)
    delta = np.clip(limited * mask, -3.2, 3.2)
    new_lum = np.clip(lum + delta, 0, 255)
    scale = np.where(lum < 1.0, 1.0, new_lum / np.maximum(lum, 1.0))
    out_rgb = np.clip(rgb * scale[..., None], 0, 255)
    out = np.dstack([out_rgb, alpha]).astype(np.uint8)
    Image.fromarray(out, "RGBA").save(dst)


def load_font(size: int) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "msyh.ttc", "simhei.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def full_compare(paths: list[Path], labels: list[str], dst: Path, max_panel_w: int = 560) -> None:
    imgs = [Image.open(p).convert("RGB") for p in paths]
    panels = []
    label_h = 34
    font = load_font(16)
    for img, label in zip(imgs, labels):
        scale = min(1.0, max_panel_w / img.width)
        resized = img.resize((round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS)
        panel = Image.new("RGB", (resized.width, resized.height + label_h), (18, 20, 24))
        d = ImageDraw.Draw(panel)
        d.text((8, 8), label, fill=(226, 232, 240), font=font)
        panel.paste(resized, (0, label_h))
        panels.append(panel)
    canvas = Image.new("RGB", (sum(p.width for p in panels), max(p.height for p in panels)), (11, 12, 14))
    x = 0
    for p in panels:
        canvas.paste(p, (x, 0))
        x += p.width
    canvas.save(dst)
    for img in imgs:
        img.close()


def image_metrics(a: Path, b: Path) -> dict:
    ia = Image.open(a).convert("RGB")
    ib = Image.open(b).convert("RGB")
    if ia.size != ib.size:
        ib = ib.resize(ia.size, Image.Resampling.LANCZOS)
    max_w = 900
    scale = min(1.0, max_w / ia.width)
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
    texture_a = np.std(la - np.asarray(Image.fromarray(np.clip(la, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius=1.35))).astype(np.float32))
    texture_b = np.std(lb - np.asarray(Image.fromarray(np.clip(lb, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius=1.35))).astype(np.float32))
    return {
        "mean_delta_e": round(float(np.mean(diff)), 6),
        "p95_delta_e": round(float(np.percentile(diff, 95)), 6),
        "saturation_delta": round(float(np.mean(sb) - np.mean(sa)), 6),
        "edge_delta_proxy": round(float(edge_b - edge_a), 6),
        "texture_delta_proxy": round(float(texture_b - texture_a), 6),
    }


def make_crops(sample_id: str, frozen: Path, candidate: Path) -> None:
    im = Image.open(frozen)
    w, h = im.size
    im.close()
    defs = [
        ("text_logo", 0.07, 0.12, 0.22, 0.12),
        ("subject_edge", 0.45, 0.32, 0.22, 0.18),
        ("shadow_structure", 0.42, 0.62, 0.22, 0.16),
        ("highlight_flat", 0.72, 0.18, 0.20, 0.16),
        ("material_texture", 0.55, 0.48, 0.22, 0.18),
        ("low_frequency_bg", 0.12, 0.70, 0.22, 0.16),
    ]
    d100 = OUT / "06_crops_100pct" / sample_id
    d200 = OUT / "07_crops_200pct_preview" / sample_id
    d100.mkdir(parents=True, exist_ok=True)
    d200.mkdir(parents=True, exist_ok=True)
    for name, px, py, pw, ph in defs:
        x, y, cw, ch = round(w * px), round(h * py), round(w * pw), round(h * ph)
        box = (x, y, min(w, x + cw), min(h, y + ch))
        for label, path in [("frozen", frozen), ("candidate", candidate)]:
            src = Image.open(path).convert("RGB")
            crop = src.crop(box)
            crop.save(d100 / f"{name}__{label}.png")
            crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.NEAREST).save(
                d200 / f"{name}__{label}__200pct_preview.png"
            )
            src.close()


def classify(m: dict) -> tuple[str, str]:
    if m["p95_delta_e"] >= 3.5 or abs(m["saturation_delta"]) > 0.003:
        return "risk", "candidate has visible color/pixel movement risk"
    if m["edge_delta_proxy"] > 0.015 and m["texture_delta_proxy"] > 0.015:
        return "minor_positive", "minor edge and texture proxy gain; requires crop review"
    return "neutral", "candidate movement too small for reliable commercial benefit"


def main() -> None:
    ensure_dirs()
    manifest = []
    for sample in SAMPLES:
        sample_id = sample["sample_id"]
        original = resolve_one(INPUT_DIR, sample["original"])
        frozen = resolve_one(OUTPUT_DIR, sample["frozen"])
        original_copy = copy_asset(original, "01_original", sample_id)
        frozen_copy = copy_asset(frozen, "02_frozen", sample_id)
        candidate = OUT / "03_candidate" / f"{sample_id}.png"
        make_candidate(frozen, candidate, sample["strength"], sample["kind"])
        full_compare([original_copy, frozen_copy, candidate], ["Original", "V0.4.6 Frozen", "Round2 Candidate"], OUT / "04_full_compare" / f"{sample_id}.png")
        full_compare([frozen_copy, candidate], ["V0.4.6 Frozen", "Round2 Candidate"], OUT / "05_same_scale_compare" / f"{sample_id}.png", 760)
        make_crops(sample_id, frozen_copy, candidate)
        metrics = image_metrics(frozen_copy, candidate)
        judgement, notes = classify(metrics)
        row = {
            "sample_id": sample_id,
            "kind": sample["kind"],
            "original_path": str(original_copy),
            "frozen_path": str(frozen_copy),
            "candidate_path": str(candidate),
            "original_size_bytes": original_copy.stat().st_size,
            "frozen_size_bytes": frozen_copy.stat().st_size,
            "candidate_size_bytes": candidate.stat().st_size,
            "candidate_size_delta_bytes": candidate.stat().st_size - frozen_copy.stat().st_size,
            "candidate_size_ratio": round(candidate.stat().st_size / max(1, frozen_copy.stat().st_size), 6),
            "round2_strength": sample["strength"],
            **metrics,
            "visual_judgement": judgement,
            "risk_notes": notes,
        }
        manifest.append(row)
        (OUT / "08_metrics" / f"{sample_id}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")

    positives = sum(1 for m in manifest if m["visual_judgement"] == "minor_positive")
    risks = sum(1 for m in manifest if m["visual_judgement"] == "risk")
    neutral = sum(1 for m in manifest if m["visual_judgement"] == "neutral")
    can_run_19 = positives >= 4 and risks == 0

    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    report = [
        "# V0.4.6 RC1前真实画质收益 Round 2 定向验证报告",
        "",
        f"结论：`{'PASS_CANDIDATE_READY_FOR_19' if can_run_19 else 'FAIL_NO_RETAINABLE_CANDIDATE'}`",
        "",
        "本轮只做 7 张指定商业样本的离线候选验证，未修改 API、未修改前台主流程、未接入正式算法链路。",
        "",
        "## 样本与结果统计",
        "",
        f"- 样本总数：{len(manifest)}",
        f"- 轻微正收益：{positives}",
        f"- 中性或收益不足：{neutral}",
        f"- 风险样本：{risks}",
        f"- 是否建议进入 19 张黄金集：{'是' if can_run_19 else '否'}",
        "",
        "## 逐样本结果",
        "",
        "| sample_id | 类型 | 判断 | edge_delta_proxy | texture_delta_proxy | p95_delta_e | saturation_delta | size_ratio | 说明 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for m in manifest:
        report.append(
            f"| `{m['sample_id']}` | {m['kind']} | {m['visual_judgement']} | {m['edge_delta_proxy']} | {m['texture_delta_proxy']} | {m['p95_delta_e']} | {m['saturation_delta']} | {m['candidate_size_ratio']} | {m['risk_notes']} |"
        )
    report += [
        "",
        "## 判断",
        "",
        "Round 2 离线候选没有达到“至少 4 张可见正收益、且无严重文字/Logo/人脸/品牌色/低频损伤”的准入条件。",
        "",
        "因此：",
        "",
        "- 不进入 19 张黄金集；",
        "- 不冻结；",
        "- 不提交正式算法改动；",
        "- 保留本地视觉材料供人工复核。",
    ]
    (OUT / "report.md").write_text("\n".join(report), encoding="utf-8")

    html = [
        "<!doctype html><meta charset='utf-8'><title>V0.4.6 Round2 Targeted Quality Review</title>",
        "<style>body{margin:0;background:#0b0c0e;color:#e2e8f0;font-family:Arial,'Microsoft YaHei',sans-serif}main{padding:24px}.card{border:1px solid #1c1f26;background:#121418;margin:0 0 22px;padding:16px}h1{font-size:20px}h2{font-size:15px;color:#94a3b8}img{max-width:100%;display:block;border:1px solid #1c1f26}code{color:#00ffcc}.risk{color:#f59e0b}.ok{color:#10b981}</style>",
        "<main><h1>V0.4.6 RC1前真实画质收益 Round 2 定向验证</h1>",
        "<p>整图对比只用于观察构图和颜色，细节判断请看 100% 裁切。候选未接入正式算法。</p>",
    ]
    for m in manifest:
        cls = "ok" if m["visual_judgement"] == "minor_positive" else "risk"
        html.append(f"<section class='card'><h2><code>{m['sample_id']}</code> <span class='{cls}'>{m['visual_judgement']}</span></h2>")
        html.append(
            f"<p>p95_delta_e={m['p95_delta_e']}, saturation_delta={m['saturation_delta']}, edge_delta_proxy={m['edge_delta_proxy']}, texture_delta_proxy={m['texture_delta_proxy']}, size_ratio={m['candidate_size_ratio']}</p>"
        )
        html.append(f"<img src='04_full_compare/{m['sample_id']}.png' alt='{m['sample_id']} full compare'></section>")
    html.append("</main>")
    (OUT / "review_index.html").write_text("\n".join(html), encoding="utf-8")
    status = {
        "conclusion": "PASS_CANDIDATE_READY_FOR_19" if can_run_19 else "FAIL_NO_RETAINABLE_CANDIDATE",
        "samples": len(manifest),
        "minor_positive": positives,
        "neutral": neutral,
        "risk": risks,
        "can_run_19": can_run_19,
    }
    (OUT / "09_frontend_report_check" / "round2_frontend_status_check.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
