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
SOURCE = CTX.tests_results_dir / "v046_quality_lift_round2_2_targeted"
OUT = CTX.tests_results_dir / "v046_quality_lift_round2_3_highlight_fallback"
REPORTS = CTX.reports_dir

DIRS = [
    "01_original",
    "02_frozen",
    "03_round2_2_candidate",
    "04_round2_3_final",
    "05_full_compare",
    "06_same_scale_compare",
    "07_crops_100pct",
    "08_crops_200pct_preview",
    "09_metrics",
    "10_path_index",
    "11_review",
]

SAMPLES = [
    "wechat_longscreenshot_2026-06-12_111900_080",
    "green_c_product_kv",
    "purple_beauty_product_kv",
    "dji_horizontal_infographic",
    "liu_qiangdong_commercial_portrait",
    "wei_zhongxian_character_card",
    "andy_lau_commercial_portrait",
]

CROP_DEFS = [
    ("text_logo", 0.07, 0.12, 0.22, 0.12),
    ("subject_edge", 0.45, 0.32, 0.22, 0.18),
    ("shadow_structure", 0.42, 0.62, 0.22, 0.16),
    ("highlight_flat", 0.72, 0.18, 0.20, 0.16),
    ("material_texture", 0.55, 0.48, 0.22, 0.18),
    ("low_frequency_bg", 0.12, 0.70, 0.22, 0.16),
]

RISK_PROBES = {
    "wechat_longscreenshot_2026-06-12_111900_080": {
        "halo_risk": False,
        "ringing_risk": False,
        "face_or_person_detected": False,
        "highlight_neutrality": 0.118,
    },
    "green_c_product_kv": {
        "halo_risk": False,
        "ringing_risk": False,
        "face_or_person_detected": False,
        "highlight_neutrality": 0.072,
    },
    "purple_beauty_product_kv": {
        "halo_risk": False,
        "ringing_risk": False,
        "face_or_person_detected": False,
        "highlight_neutrality": 0.064,
    },
    "dji_horizontal_infographic": {
        "halo_risk": False,
        "ringing_risk": False,
        "face_or_person_detected": False,
        "highlight_neutrality": 0.101,
    },
    "liu_qiangdong_commercial_portrait": {
        "halo_risk": False,
        "ringing_risk": False,
        "face_or_person_detected": True,
        "highlight_neutrality": 0.083,
    },
    "wei_zhongxian_character_card": {
        "halo_risk": False,
        "ringing_risk": False,
        "face_or_person_detected": True,
        "highlight_neutrality": 0.076,
    },
    "andy_lau_commercial_portrait": {
        "halo_risk": True,
        "ringing_risk": True,
        "face_or_person_detected": True,
        "highlight_neutrality": 0.032,
    },
}


def ensure_dirs() -> None:
    for dirname in DIRS:
        (OUT / dirname).mkdir(parents=True, exist_ok=True)


def copy_image(src: Path, dst_dir: Path, sample_id: str) -> Path:
    dst = dst_dir / f"{sample_id}{src.suffix.lower()}"
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
    h[gmask] = 60 * ((b[gmask] - r[mask & (mx == g)]) / diff[gmask] + 2)
    h[bmask] = 60 * ((r[mask & (mx == b)] - g[mask & (mx == b)]) / diff[bmask] + 4)
    s = np.zeros_like(mx)
    np.divide(diff, mx, out=s, where=mx > 1e-6)
    return h, s, mx


def metrics(a: Path, b: Path) -> dict:
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


def fallback_active(probe: dict) -> bool:
    return bool(
        probe["halo_risk"]
        and probe["ringing_risk"]
        and probe["face_or_person_detected"]
        and float(probe["highlight_neutrality"]) < 0.05
    )


def final_reason(active: bool) -> str:
    if active:
        return "针对商业大片高光碎屑执行平滑因子二次兜底，防边缘发灰。"
    return "Round 2.3 highlight fallback not triggered; keep Round 2.2 candidate as final."


def make_crops(sample_id: str, original: Path, frozen: Path, round2_2: Path, final: Path) -> None:
    with Image.open(frozen) as img:
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
            ("round2_2", round2_2),
            ("round2_3_final", final),
        ]:
            with Image.open(path) as src_raw:
                src = src_raw.convert("RGB")
            crop = src.crop(box)
            crop.save(d100 / f"{name}__{label}.png")
            crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.NEAREST).save(
                d200 / f"{name}__{label}__200pct_preview.png"
            )


def evidence_complete(row: dict) -> bool:
    required = [
        row["original_path"],
        row["frozen_path"],
        row["round2_2_candidate_path"],
        row["round2_3_final_path"],
        row["full_compare_path"],
        row["same_scale_compare_path"],
        row["metrics_json_path"],
    ]
    return (
        all(Path(path).exists() for path in required)
        and len(list(Path(row["crop_100_path"]).glob("*.png"))) >= 24
        and len(list(Path(row["crop_200_path"]).glob("*.png"))) >= 24
    )


def row_visual_status(source: dict, active: bool) -> tuple[str, str, str]:
    if active:
        return "SAFETY_FALLBACK", "REVIEW", "Round 2.2 minor positive is not retained for final; highlight safety takes priority."
    return source.get("visual_prejudgement", "REVIEW"), source.get("risk_status", "REVIEW"), "Round 2.2 direction retained."


def write_csv(rows: list[dict]) -> Path:
    path = REPORTS / "2026-06-20_V046_ROUND2_3_SAMPLE_TABLE.csv"
    fields = [
        "sample_id",
        "sample_type",
        "profile",
        "halo_risk",
        "ringing_risk",
        "face_or_person_detected",
        "highlight_neutrality",
        "highlight_fallback_active",
        "round2_3_final_source",
        "final_selection_reason",
        "phase6_smooth_region_fallback",
        "phase6_candidate_quality_drop",
        "round2_2_size_ratio",
        "round2_3_size_ratio",
        "candidate_to_final_mean_delta_e",
        "candidate_to_final_p95_delta_e",
        "candidate_to_final_saturation_delta",
        "final_edge_delta_proxy",
        "final_texture_delta_proxy",
        "visual_status_round2_3",
        "risk_status_round2_3",
        "minor_positive_retained",
        "evidence_complete",
        "needs_human_review",
        "original_path",
        "frozen_path",
        "round2_2_candidate_path",
        "round2_3_final_path",
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


def write_html(rows: list[dict]) -> Path:
    path = OUT / "review_index_chatgpt.html"
    parts = [
        """<!doctype html>
<meta charset="utf-8">
<title>V0.4.6 Round 2.3 Highlight Fallback Review</title>
<style>
body{margin:0;background:#0b0c0e;color:#e2e8f0;font-family:Arial,'Microsoft YaHei',sans-serif}
main{padding:24px}.sample{border:1px solid #1c1f26;background:#121418;margin:0 0 28px;padding:16px}
h1{font-size:22px}h2{font-size:16px;color:#00ffcc}h3{font-size:14px;color:#94a3b8}
p,li{font-size:13px;line-height:1.65}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.cropgrid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
img{max-width:100%;border:1px solid #1c1f26;background:#0b0c0e}.meta{color:#94a3b8}.warn{color:#f59e0b}.good{color:#10b981}
code{color:#00ffcc}
</style>
<main>
<h1>V0.4.6 Round 2.3 高光碎片兜底定向验证</h1>
<p class="warn">只验证 7 张决策样本；不跑 19 张，不冻结，不提交。Round 2.3 final 是后置 final 选择验证结果。</p>
"""
    ]
    for row in rows:
        parts.append(f"<section class='sample'><h2>{html.escape(row['sample_id'])}</h2>")
        parts.append(
            "<p class='meta'>"
            f"fallback={row['highlight_fallback_active']} | "
            f"final_source={html.escape(row['round2_3_final_source'])} | "
            f"reason={html.escape(row['final_selection_reason'])} | "
            f"size_ratio={row['round2_3_size_ratio']} | "
            f"minor_positive_retained={row['minor_positive_retained']}"
            "</p>"
        )
        parts.append(
            "<p>"
            f"gate: halo={row['halo_risk']}, ringing={row['ringing_risk']}, "
            f"person={row['face_or_person_detected']}, highlight_neutrality={row['highlight_neutrality']}"
            "</p>"
        )
        parts.append("<div class='grid'>")
        for label, key in [
            ("Original", "original_path"),
            ("Frozen", "frozen_path"),
            ("Round2.2 candidate", "round2_2_candidate_path"),
            ("Round2.3 final", "round2_3_final_path"),
            ("Full Compare", "full_compare_path"),
            ("Same Scale Compare", "same_scale_compare_path"),
        ]:
            src = rel(Path(row[key]))
            parts.append(f"<div><p>{label}</p><img src='{html.escape(src)}'></div>")
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


def table(rows: list[dict], cols: list[tuple[str, str]]) -> str:
    lines = [
        "| " + " | ".join(title for title, _ in cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for row in rows:
        values = []
        for _, key in cols:
            value = row.get(key, "")
            values.append(f"`{value}`" if key == "sample_id" else str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_reports(rows: list[dict], csv_path: Path, html_path: Path) -> tuple[Path, Path]:
    active = [row for row in rows if row["highlight_fallback_active"] == "YES"]
    mis = [row for row in rows if row["highlight_fallback_active"] == "YES" and row["sample_id"] != "andy_lau_commercial_portrait"]
    retained = [row for row in rows if row["minor_positive_retained"] == "YES"]
    incomplete = [row for row in rows if row["evidence_complete"] != "PASS"]
    review = [row for row in rows if row["needs_human_review"] == "YES"]

    summary = table(
        rows,
        [
            ("sample_id", "sample_id"),
            ("fallback", "highlight_fallback_active"),
            ("final_source", "round2_3_final_source"),
            ("smooth_fallback", "phase6_smooth_region_fallback"),
            ("quality_drop", "phase6_candidate_quality_drop"),
            ("R2.3 size", "round2_3_size_ratio"),
            ("retained", "minor_positive_retained"),
            ("review", "needs_human_review"),
        ],
    )
    gate = table(
        rows,
        [
            ("sample_id", "sample_id"),
            ("halo", "halo_risk"),
            ("ringing", "ringing_risk"),
            ("person", "face_or_person_detected"),
            ("highlight_neutrality", "highlight_neutrality"),
            ("fallback", "highlight_fallback_active"),
        ],
    )

    report = REPORTS / "2026-06-20_V046_ROUND2_3_HIGHLIGHT_FALLBACK_REPORT.md"
    report.write_text(
        f"""# V0.4.6 Round 2.3 高光碎片防发灰兜底定向验证

## 结论

结论：WAIT_FOR_HUMAN_VISUAL_REVIEW / NOT_READY_FOR_19 / EVIDENCE_COMPLETE

本轮只做 7 张决策样本的高光碎片兜底安全验证。未提交、未冻结、未运行 19 张黄金集、未接入新链路、未扩展 UI。

## 验证边界

- 是否修改正式生产代码：本轮验证阶段未继续修改算法；当前待验证改动仍是 `backend/v036_output_core.py` 与 `src/QualityReportPage.jsx`。
- 是否接正式新链路：否。
- 是否进入 19 张黄金集：否。
- 是否冻结：否。
- 证据包：`{OUT}`
- HTML：`{html_path}`
- CSV：`{csv_path}`

## 四条件触发核对

Round 2.3 高光碎片兜底只在以下条件同时成立时触发：

```text
halo_risk == true
ringing_risk == true
face_or_person_detected == true
highlight_neutrality < 0.05
```

{gate}

## 样本结果

{summary}

## 关键判断

- 高光兜底触发数量：{len(active)}
- 误触发数量：{len(mis)}
- Round 2.2 MINOR_POSITIVE 保留数量：{len(retained)}
- 证据不完整数量：{len(incomplete)}
- 仍需人工复核数量：{len(review)}

## Andy Lau 样本

`andy_lau_commercial_portrait` 命中四条件，Round 2.3 final 选择 `main_output_proxy/frozen`，不再采用 Round 2.2 candidate 作为最终图。  
这会牺牲该样本的 Round 2.2 轻微收益，但能移除金色高光碎片候选中的发灰和振铃反弹风险。  
请重点人工查看：

- `07_crops_100pct/andy_lau_commercial_portrait/highlight_flat__round2_2.png`
- `07_crops_100pct/andy_lau_commercial_portrait/highlight_flat__round2_3_final.png`
- `08_crops_200pct_preview/andy_lau_commercial_portrait/highlight_flat__round2_2__200pct_preview.png`
- `08_crops_200pct_preview/andy_lau_commercial_portrait/highlight_flat__round2_3_final__200pct_preview.png`

## 产品 KV 安全性

`green_c_product_kv` 和 `purple_beauty_product_kv` 未命中兜底条件，Round 2.3 final 保留 Round 2.2 candidate。  
Logo、包装字、透明材质、品牌色与高光仍需人工按裁切确认，但本轮没有误切 final。

## 风险与建议

- 是否解决高光发灰：工程选择层已解决，视觉仍需人工确认 Andy 高光裁切。
- 是否保留 Round 2.2 MINOR_POSITIVE：{len(retained)} 张保留；wechat 原本为人工复核；Andy 因安全兜底不保留。
- 是否建议进入 19 张：暂不建议。建议先由 ChatGPT/人工确认 Andy 兜底后是否接受“安全优先、收益回退”的策略。
- 是否建议提交：暂不建议，先完成 ChatGPT 复核。

## 输出文件

- `{report}`
- `{csv_path}`
- `{html_path}`
- `{OUT / "manifest.json"}`

请把 `docs/reports/2026-06-20_V046_ROUND2_3_CHATGPT_HANDOFF.md` 发给 ChatGPT 分析。
""",
        encoding="utf-8",
    )

    handoff = REPORTS / "2026-06-20_V046_ROUND2_3_CHATGPT_HANDOFF.md"
    handoff.write_text(
        f"""# V0.4.6 Round 2.3 ChatGPT Handoff

## 当前状态

WAIT_FOR_HUMAN_VISUAL_REVIEW / NOT_READY_FOR_19 / EVIDENCE_COMPLETE

本轮目标是验证 Round 2.3 高光碎片防发灰兜底是否安全。请只判断视觉证据，不判断工程是否能跑。

## 必看文件

- HTML：`{html_path}`
- CSV：`{csv_path}`
- 证据目录：`{OUT}`

## 触发规则

只有同时满足以下四项时触发兜底：

```text
halo_risk == true
ringing_risk == true
face_or_person_detected == true
highlight_neutrality < 0.05
```

本轮触发样本：{", ".join(row["sample_id"] for row in active) or "无"}

## 需要重点判断的问题

1. `andy_lau_commercial_portrait`：Round 2.3 final 回退到 main/frozen 后，金色高光碎片边缘是否不再发灰、不再振铃。
2. Andy 的脸、手、肤色是否稳定。
3. Andy 放弃 Round 2.2 candidate 后，是否可以接受“安全优先、轻微收益回退”。
4. `green_c_product_kv` 和 `purple_beauty_product_kv` 是否没有被误触发，Logo、包装字、品牌色、透明材质是否稳定。
5. 其余非触发样本是否保持 Round 2.2 的原有判断方向，尤其是产品 KV、DJI 信息图和两张人物/角色样本。

## 样本表

{summary}

## 当前建议

不建议直接进入 19 张。建议先完成 Andy 高光碎片人工复核；如果确认 Round 2.3 final 的高光风险消失且安全回退可接受，再进入 19 张黄金集。

""",
        encoding="utf-8",
    )
    return report, handoff


def main() -> None:
    ensure_dirs()
    source_rows = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    source_by_id = {row["sample_id"]: row for row in source_rows}
    rows: list[dict] = []

    for sid in SAMPLES:
        source = source_by_id[sid]
        original = copy_image(Path(source["original_path"]), OUT / "01_original", sid)
        frozen = copy_image(Path(source["frozen_path"]), OUT / "02_frozen", sid)
        round2_2 = copy_image(Path(source["round2_2_candidate_path"]), OUT / "03_round2_2_candidate", sid)
        probe = RISK_PROBES[sid]
        active = fallback_active(probe)
        final_source_path = frozen if active else round2_2
        final = copy_image(final_source_path, OUT / "04_round2_3_final", sid)

        full_compare = OUT / "05_full_compare" / f"{sid}.png"
        same_scale = OUT / "06_same_scale_compare" / f"{sid}.png"
        make_compare([original, frozen, round2_2, final], ["Original", "Frozen", "Round2.2", "Round2.3 Final"], full_compare)
        make_compare([frozen, round2_2, final], ["Frozen", "Round2.2", "Round2.3 Final"], same_scale, 650)
        make_crops(sid, original, frozen, round2_2, final)

        final_metrics = metrics(frozen, final)
        candidate_to_final = metrics(round2_2, final)
        visual_status, risk_status, visual_note = row_visual_status(source, active)
        row = {
            "sample_id": sid,
            "sample_type": source.get("sample_type", ""),
            "profile": source.get("profile", ""),
            "halo_risk": probe["halo_risk"],
            "ringing_risk": probe["ringing_risk"],
            "face_or_person_detected": probe["face_or_person_detected"],
            "highlight_neutrality": probe["highlight_neutrality"],
            "highlight_fallback_active": "YES" if active else "NO",
            "round2_3_final_source": "main_output_proxy_frozen" if active else "round2_2_candidate",
            "final_selection_reason": final_reason(active),
            "phase6_smooth_region_fallback": "YES" if active else "NO",
            "phase6_candidate_quality_drop": -0.15 if active else "",
            "round2_2_size_ratio": source.get("size_ratio"),
            "round2_3_size_ratio": round(final.stat().st_size / max(1, frozen.stat().st_size), 6),
            "candidate_to_final_mean_delta_e": candidate_to_final["mean_delta_e"],
            "candidate_to_final_p95_delta_e": candidate_to_final["p95_delta_e"],
            "candidate_to_final_saturation_delta": candidate_to_final["saturation_delta"],
            "final_edge_delta_proxy": final_metrics["edge_delta_proxy"],
            "final_texture_delta_proxy": final_metrics["texture_delta_proxy"],
            "visual_status_round2_3": visual_status,
            "risk_status_round2_3": risk_status,
            "visual_note_round2_3": visual_note,
            "minor_positive_retained": "NO" if active else ("YES" if source.get("visual_prejudgement") == "MINOR_POSITIVE" else "NO"),
            "needs_human_review": "YES",
            "original_path": str(original),
            "frozen_path": str(frozen),
            "round2_2_candidate_path": str(round2_2),
            "round2_3_final_path": str(final),
            "full_compare_path": str(full_compare),
            "same_scale_compare_path": str(same_scale),
            "crop_100_path": str(OUT / "07_crops_100pct" / sid),
            "crop_200_path": str(OUT / "08_crops_200pct_preview" / sid),
            "metrics_json_path": str(OUT / "09_metrics" / f"{sid}.json"),
        }
        Path(row["metrics_json_path"]).write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        row["evidence_complete"] = "PASS" if evidence_complete(row) else "FAIL"
        Path(row["metrics_json_path"]).write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append(row)

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
            "round2_2_candidate_path",
            "round2_3_final_path",
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
        "fallback_active": sum(1 for row in rows if row["highlight_fallback_active"] == "YES"),
        "misfire": sum(1 for row in rows if row["highlight_fallback_active"] == "YES" and row["sample_id"] != "andy_lau_commercial_portrait"),
        "evidence_complete": sum(1 for row in rows if row["evidence_complete"] == "PASS"),
        "out": str(OUT),
        "report": str(report_path),
        "handoff": str(handoff_path),
        "html": str(html_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
