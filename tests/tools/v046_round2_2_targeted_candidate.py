from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v046_path_resolver import file_meta, get_v046_path_context


CTX = get_v046_path_context(Path(__file__).resolve())
ROUND2_1 = CTX.tests_results_dir / "v046_quality_lift_round2_1_targeted"
OUT = CTX.tests_results_dir / "v046_quality_lift_round2_2_targeted"

DIRS = [
    "01_original",
    "02_frozen",
    "03_round2_1_candidate",
    "04_round2_2_candidate",
    "05_full_compare",
    "06_same_scale_compare",
    "07_crops_100pct",
    "08_crops_200pct_preview",
    "09_metrics",
    "10_path_index",
    "11_review",
]

SAMPLE_POLICY = {
    "wechat_longscreenshot_2026-06-12_111900_080": {
        "type_label": "文字密集长截图",
        "profile": "text_dense_shrink",
        "strength": 0.022,
        "target": "压低体积增长，保留极轻微文字边缘稳定，保护白底和浅灰底",
    },
    "green_c_product_kv": {
        "type_label": "产品KV",
        "profile": "product_kv_safe",
        "strength": 0.066,
        "target": "保留瓶身透明材质和产品轮廓轻微收益，锁定Logo、包装文字、白面和高光",
    },
    "purple_beauty_product_kv": {
        "type_label": "产品KV",
        "profile": "product_kv_safe",
        "strength": 0.063,
        "target": "保留产品边缘和银色材质轻微收益，锁定品牌紫、银色高光和背景渐变",
    },
    "dji_horizontal_infographic": {
        "type_label": "文字信息图",
        "profile": "infographic_safe",
        "strength": 0.071,
        "target": "保留大结构、图标和线条轻微收益，保护小字、浅底和细线",
    },
    "liu_qiangdong_commercial_portrait": {
        "type_label": "商业人物海报",
        "profile": "portrait_nonface",
        "strength": 0.066,
        "target": "扩大脸部和肤色保护，只允许服装、背景城市和非脸部结构轻微处理",
    },
    "wei_zhongxian_character_card": {
        "type_label": "角色信息卡",
        "profile": "character_card_nontext",
        "strength": 0.060,
        "target": "加强红色标签、小字、边框和暗部保护，只保留毛发服饰低强度收益",
    },
    "andy_lau_commercial_portrait": {
        "type_label": "商业人物海报",
        "profile": "portrait_nonface",
        "strength": 0.062,
        "target": "保留碎片、服装和金属/背景结构轻微收益，保护脸、手、肤色和高光",
    },
}

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


def spatial_mask(sample_id: str, profile: str, shape: tuple[int, int]) -> np.ndarray:
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    x = xx / max(1, w)
    y = yy / max(1, h)
    mask = np.ones((h, w), dtype=np.float32)

    if sample_id == "liu_qiangdong_commercial_portrait":
        face_zone = (x > 0.30) & (x < 0.62) & (y > 0.14) & (y < 0.58)
        text_zone = (x < 0.28) & (y < 0.68)
        signature_zone = (y > 0.80)
        mask[face_zone | text_zone | signature_zone] *= 0.05
        mask[(y > 0.60) | ((x > 0.33) & (x < 0.62) & (y > 0.50))] *= 1.15
    elif sample_id == "andy_lau_commercial_portrait":
        face_hand_zone = ((x > 0.36) & (x < 0.58) & (y > 0.16) & (y < 0.48)) | (
            (x > 0.30) & (x < 0.54) & (y > 0.34) & (y < 0.58)
        )
        big_text_zone = x < 0.23
        mask[face_hand_zone | big_text_zone] *= 0.05
        mask[((x > 0.52) & (y > 0.15)) | ((x > 0.20) & (x < 0.72) & (y > 0.45))] *= 1.12
    elif sample_id == "wei_zhongxian_character_card":
        right_text_panels = x > 0.50
        red_label_rows = (y > 0.10) & (y < 0.42) & (x > 0.43)
        border_zone = (x < 0.03) | (x > 0.97) | (y < 0.05) | (y > 0.95)
        face_zone = (x > 0.25) & (x < 0.46) & (y > 0.12) & (y < 0.42)
        mask[right_text_panels | red_label_rows | border_zone | face_zone] *= 0.04
        mask[(x > 0.05) & (x < 0.48) & (y > 0.18) & (y < 0.86)] *= 1.12
    elif profile == "text_dense_shrink":
        margin_text = (x < 0.04) | (x > 0.96)
        mask[margin_text] *= 0.0
    return mask


def make_candidate(src: Path, dst: Path, sample_id: str) -> None:
    policy = SAMPLE_POLICY[sample_id]
    image = Image.open(src).convert("RGBA")
    arr = np.asarray(image).astype(np.float32)
    rgb = arr[..., :3]
    alpha = arr[..., 3:4]
    lum = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    blur = np.asarray(
        Image.fromarray(np.clip(lum, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius=1.10))
    ).astype(np.float32)
    detail = lum - blur
    abs_detail = np.abs(detail)
    hue, sat, _ = rgb_to_hsv_np(rgb)

    profile = policy["profile"]
    mask = np.ones_like(lum, dtype=np.float32) * float(policy["strength"])
    mask *= spatial_mask(sample_id, profile, lum.shape)

    flat = abs_detail < 2.4
    weak_edge = (abs_detail >= 2.4) & (abs_detail < 5.4)
    useful_mid = (abs_detail >= 5.4) & (abs_detail <= 38.0)
    strong_edge = abs_detail > 48.0
    highlight_flat = (lum > 222) & (abs_detail < 14.0)
    smooth_light = (lum > 204) & (sat < 0.16) & (abs_detail < 18.0)
    deep_shadow = lum < 20
    brand_color = (sat > 0.52) & (abs_detail < 14.0)
    gray_white_bg = (sat < 0.11) & (lum > 184) & (abs_detail < 22.0)
    skin = (
        (hue >= 8)
        & (hue <= 58)
        & (sat > 0.12)
        & (lum > 42)
        & (lum < 238)
        & (rgb[..., 0] >= rgb[..., 1] - 5)
        & (rgb[..., 1] >= rgb[..., 2] - 14)
    )
    red_label = ((hue < 18) | (hue > 342)) & (sat > 0.28) & (lum > 35) & (lum < 185)

    mask[~useful_mid] *= 0.20
    mask[weak_edge] *= 0.55
    mask[strong_edge | deep_shadow] *= 0.16
    mask[flat | highlight_flat | smooth_light] = 0
    mask[alpha[..., 0] <= 0] = 0

    if profile == "text_dense_shrink":
        mask[gray_white_bg | brand_color] = 0
        mask[strong_edge] *= 0.05
        max_delta = 1.15
    elif profile == "infographic_safe":
        mask[gray_white_bg | brand_color | red_label] *= 0.18
        max_delta = 1.85
    elif profile == "product_kv_safe":
        mask[brand_color | gray_white_bg | highlight_flat] *= 0.10
        mask[lum > 215] *= 0.24
        max_delta = 1.90
    elif profile == "portrait_nonface":
        mask[skin] *= 0.04
        mask[brand_color | highlight_flat] *= 0.18
        max_delta = 2.05
    elif profile == "character_card_nontext":
        mask[skin | red_label | brand_color | gray_white_bg] *= 0.05
        max_delta = 1.65
    else:
        max_delta = 1.75

    limited = np.clip(detail, -13.0, 13.0)
    delta = np.clip(limited * mask, -max_delta, max_delta)
    new_lum = np.clip(lum + delta, 0, 255)
    scale = np.ones_like(lum)
    np.divide(new_lum, np.maximum(lum, 1.0), out=scale, where=lum >= 1.0)
    out_rgb = np.clip(rgb * scale[..., None], 0, 255)
    out = np.dstack([out_rgb, alpha]).astype(np.uint8)
    Image.fromarray(out, "RGBA").save(dst, optimize=True)


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


def copy(src: Path, dst_dir: Path, sample_id: str) -> Path:
    dst = dst_dir / f"{sample_id}{src.suffix.lower()}"
    shutil.copy2(src, dst)
    return dst


def make_crops(sample_id: str, frozen: Path, round2_1: Path, candidate: Path) -> None:
    img = Image.open(frozen)
    w, h = img.size
    img.close()
    d100 = OUT / "07_crops_100pct" / sample_id
    d200 = OUT / "08_crops_200pct_preview" / sample_id
    d100.mkdir(parents=True, exist_ok=True)
    d200.mkdir(parents=True, exist_ok=True)
    for name, px, py, pw, ph in CROP_DEFS:
        box = (round(w * px), round(h * py), min(w, round(w * (px + pw))), min(h, round(h * (py + ph))))
        for label, path in [("frozen", frozen), ("round2_1", round2_1), ("round2_2", candidate)]:
            src = Image.open(path).convert("RGB")
            crop = src.crop(box)
            crop.save(d100 / f"{name}__{label}.png")
            crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.NEAREST).save(
                d200 / f"{name}__{label}__200pct_preview.png"
            )
            src.close()


def classify(row: dict) -> tuple[str, str, str, str, str]:
    if row["evidence_complete"] != "PASS":
        return "FAIL", "EVIDENCE_INCOMPLETE", "REJECT", "UNKNOWN", "NO"
    if row["p95_delta_e"] >= 3.5 or abs(row["saturation_delta"]) > 0.003:
        return "FAIL", "NEEDS_ROUND2_2_REPAIR", "REJECT", "COLOR_RISK", "NO"
    if row["size_ratio"] > 1.11:
        size = "WEAK" if row["size_ratio"] <= 1.15 else "NOT_ACCEPTABLE"
    else:
        size = "ACCEPTABLE"
    if row["edge_delta_proxy"] >= 0.04 and row["texture_delta_proxy"] >= 0.04:
        metric = "PASS"
    elif row["edge_delta_proxy"] >= 0.012 or row["texture_delta_proxy"] >= 0.012:
        metric = "WEAK_POSITIVE"
    else:
        metric = "WEAK"
    if size == "NOT_ACCEPTABLE":
        return metric, "NEEDS_ROUND2_3_OR_REJECT", "REJECT", size, "NO"
    if metric == "PASS" and size == "ACCEPTABLE":
        return metric, "MINOR_POSITIVE", "REVIEW", size, "WAIT_FOR_HUMAN_REVIEW"
    return metric, "NEEDS_HUMAN_REVIEW", "REVIEW", size, "WAIT_FOR_HUMAN_REVIEW"


def evidence_complete(row: dict) -> bool:
    paths = [
        row["original_path"],
        row["frozen_path"],
        row["round2_1_candidate_path"],
        row["round2_2_candidate_path"],
        row["full_compare_path"],
        row["same_scale_compare_path"],
    ]
    if not all(Path(path).exists() for path in paths):
        return False
    return (
        len(list(Path(row["crop_100_path"]).glob("*.png"))) >= 18
        and len(list(Path(row["crop_200_path"]).glob("*.png"))) >= 18
    )


def main() -> None:
    ensure_dirs()
    source_rows = json.loads((ROUND2_1 / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for source in source_rows:
        sid = source["sample_id"]
        original = copy(Path(source["original_path"]), OUT / "01_original", sid)
        frozen = copy(Path(source["frozen_path"]), OUT / "02_frozen", sid)
        round2_1 = copy(Path(source["round2_1_candidate_path"]), OUT / "03_round2_1_candidate", sid)
        candidate = OUT / "04_round2_2_candidate" / f"{sid}.png"
        make_candidate(frozen, candidate, sid)

        make_compare(
            [original, frozen, round2_1, candidate],
            ["Original", "Frozen", "Round2.1", "Round2.2"],
            OUT / "05_full_compare" / f"{sid}.png",
        )
        make_compare(
            [frozen, round2_1, candidate],
            ["Frozen", "Round2.1", "Round2.2"],
            OUT / "06_same_scale_compare" / f"{sid}.png",
            650,
        )
        make_crops(sid, frozen, round2_1, candidate)

        m = metrics(frozen, candidate)
        m21 = metrics(round2_1, candidate)
        row = {
            "sample_id": sid,
            "sample_type": SAMPLE_POLICY[sid]["type_label"],
            "profile": SAMPLE_POLICY[sid]["profile"],
            "target": SAMPLE_POLICY[sid]["target"],
            "round2_2_strength": SAMPLE_POLICY[sid]["strength"],
            "original_path": str(original),
            "frozen_path": str(frozen),
            "round2_1_candidate_path": str(round2_1),
            "round2_2_candidate_path": str(candidate),
            "full_compare_path": str(OUT / "05_full_compare" / f"{sid}.png"),
            "same_scale_compare_path": str(OUT / "06_same_scale_compare" / f"{sid}.png"),
            "crop_100_path": str(OUT / "07_crops_100pct" / sid),
            "crop_200_path": str(OUT / "08_crops_200pct_preview" / sid),
            "metrics_json_path": str(OUT / "09_metrics" / f"{sid}.json"),
            "round2_1_edge_delta_proxy": source["edge_delta_proxy"],
            "round2_1_texture_delta_proxy": source["texture_delta_proxy"],
            "round2_1_p95_delta_e": source["p95_delta_e"],
            "round2_1_saturation_delta": source["saturation_delta"],
            "round2_1_size_ratio": source["size_ratio"],
            "edge_delta_proxy": m["edge_delta_proxy"],
            "texture_delta_proxy": m["texture_delta_proxy"],
            "p95_delta_e": m["p95_delta_e"],
            "saturation_delta": m["saturation_delta"],
            "mean_delta_e": m["mean_delta_e"],
            "round2_1_to_round2_2_p95_delta_e": m21["p95_delta_e"],
            "round2_1_to_round2_2_saturation_delta": m21["saturation_delta"],
            "frozen_size_bytes": frozen.stat().st_size,
            "round2_1_size_bytes": round2_1.stat().st_size,
            "round2_2_size_bytes": candidate.stat().st_size,
            "size_ratio": round(candidate.stat().st_size / max(1, frozen.stat().st_size), 6),
            "size_delta_vs_round2_1_bytes": candidate.stat().st_size - round2_1.stat().st_size,
        }
        row["evidence_complete"] = "PASS" if evidence_complete(row) else "FAIL"
        metric, visual, risk, size, gate = classify(row)
        row["metric_judgement"] = metric
        row["visual_prejudgement"] = visual
        row["risk_status"] = risk
        row["size_benefit_ratio_judgement"] = size
        row["gate_to_19"] = gate
        row["visual_review_required"] = "YES"
        if sid == "wechat_longscreenshot_2026-06-12_111900_080" and row["size_ratio"] <= 1.11:
            row["round2_2_fix_result"] = "SIZE_RATIO_FIXED_NEEDS_VISUAL_CHECK"
        elif sid in {"liu_qiangdong_commercial_portrait", "wei_zhongxian_character_card"}:
            row["round2_2_fix_result"] = "NONFACE_TARGETING_TIGHTENED_NEEDS_VISUAL_CHECK"
        else:
            row["round2_2_fix_result"] = "MINOR_POSITIVE_DIRECTION_PRESERVED_NEEDS_VISUAL_CHECK"
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
        for key in [
            "original_path",
            "frozen_path",
            "round2_1_candidate_path",
            "round2_2_candidate_path",
            "full_compare_path",
            "same_scale_compare_path",
            "metrics_json_path",
        ]:
            path_index["files"].append(file_meta(Path(row[key]), f"{row['sample_id']}:{key}", CTX))
    (OUT / "10_path_index" / "path_index.json").write_text(json.dumps(path_index, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "samples": len(rows),
        "out": str(OUT),
        "evidence_complete": sum(1 for row in rows if row["evidence_complete"] == "PASS"),
        "minor_positive": sum(1 for row in rows if row["visual_prejudgement"] == "MINOR_POSITIVE"),
        "size_fixed_wechat": next(row["size_ratio"] for row in rows if row["sample_id"] == "wechat_longscreenshot_2026-06-12_111900_080"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
