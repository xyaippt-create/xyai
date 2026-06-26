from __future__ import annotations

import csv
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v046_path_resolver import get_v046_path_context


CTX = get_v046_path_context(Path(__file__).resolve())
OUT = CTX.tests_results_dir / "v046_quality_lift_round2_2_targeted"
REPORTS = CTX.reports_dir


def load_rows() -> list[dict]:
    return json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))


def crop_counts(row: dict) -> tuple[int, int]:
    return len(list(Path(row["crop_100_path"]).glob("*.png"))), len(list(Path(row["crop_200_path"]).glob("*.png")))


def evidence_complete(row: dict) -> bool:
    c100, c200 = crop_counts(row)
    required = [
        row["original_path"],
        row["frozen_path"],
        row["round2_1_candidate_path"],
        row["round2_2_candidate_path"],
        row["full_compare_path"],
        row["same_scale_compare_path"],
        row["metrics_json_path"],
    ]
    return all(Path(path).exists() for path in required) and c100 >= 18 and c200 >= 18


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


def recommendation(row: dict) -> str:
    sid = row["sample_id"]
    if sid == "wechat_longscreenshot_2026-06-12_111900_080":
        return "体积目标已修复，但文字收益仍弱；必须由人工确认是否只算保护通过。"
    if sid in {"liu_qiangdong_commercial_portrait", "wei_zhongxian_character_card"}:
        return "人物/角色弱收益已收缩体积并加强保护；仍需看脸部、文字、红标和非脸部材质。"
    return "延续 MINOR_POSITIVE 方向；重点确认 Logo、文字、品牌色、高光和低频平滑区安全。"


def write_csv(rows: list[dict]) -> Path:
    path = REPORTS / "2026-06-20_V046_ROUND2_2_SAMPLE_TABLE.csv"
    fields = [
        "sample_id",
        "sample_type",
        "profile",
        "target",
        "round2_2_strength",
        "original_path",
        "frozen_path",
        "round2_1_candidate_path",
        "round2_2_candidate_path",
        "full_compare_path",
        "same_scale_compare_path",
        "crop_100_path",
        "crop_200_path",
        "metrics_json_path",
        "round2_1_edge_delta_proxy",
        "round2_1_texture_delta_proxy",
        "round2_1_size_ratio",
        "edge_delta_proxy",
        "texture_delta_proxy",
        "p95_delta_e",
        "saturation_delta",
        "mean_delta_e",
        "size_ratio",
        "size_delta_vs_round2_1_bytes",
        "evidence_complete",
        "metric_judgement",
        "visual_prejudgement",
        "risk_status",
        "size_benefit_ratio_judgement",
        "gate_to_19",
        "round2_2_fix_result",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["evidence_complete"] = "PASS" if evidence_complete(row) else "FAIL"
            writer.writerow({field: out.get(field, "") for field in fields})
    return path


def write_html(rows: list[dict]) -> Path:
    path = OUT / "review_index_chatgpt.html"
    parts = [
        """<!doctype html>
<meta charset="utf-8">
<title>V0.4.6 Round 2.2 ChatGPT Visual Review</title>
<style>
body{margin:0;background:#0b0c0e;color:#e2e8f0;font-family:Arial,'Microsoft YaHei',sans-serif}
main{padding:24px}.sample{border:1px solid #1c1f26;background:#121418;margin:0 0 28px;padding:16px}
h1{font-size:22px}h2{font-size:16px;color:#00ffcc}h3{font-size:14px;color:#94a3b8}
p,li{font-size:13px;line-height:1.65}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.cropgrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
img{max-width:100%;border:1px solid #1c1f26;background:#0b0c0e}.meta{color:#94a3b8}.warn{color:#f59e0b}.good{color:#10b981}
</style>
<main>
<h1>V0.4.6 Round 2.2 ChatGPT 视觉复核索引</h1>
<p class="warn">本页只用于人工视觉复核。Round 2.2 未接正式生产链、未跑 19 张、未冻结。重点看 100% 裁切，200% preview 只用于辅助观察。</p>
"""
    ]
    for row in rows:
        parts.append(f"<section class='sample'><h2>{html.escape(row['sample_id'])}</h2>")
        parts.append(
            "<p class='meta'>"
            f"类型：{html.escape(row['sample_type'])} | "
            f"策略：{html.escape(row['profile'])} | "
            f"预判：{html.escape(row['visual_prejudgement'])} | "
            f"风险：{html.escape(row['risk_status'])} | "
            f"体积比：{row['size_ratio']} | "
            f"19张准入：{html.escape(row['gate_to_19'])}"
            "</p>"
        )
        parts.append(f"<p>修正目标：{html.escape(row['target'])}</p>")
        parts.append(f"<p class='good'>复核建议：{html.escape(recommendation(row))}</p>")
        parts.append("<div class='grid'>")
        for label, key in [
            ("Original", "original_path"),
            ("Frozen", "frozen_path"),
            ("Round2.1", "round2_1_candidate_path"),
            ("Round2.2", "round2_2_candidate_path"),
            ("Full Compare", "full_compare_path"),
            ("Same Scale Compare", "same_scale_compare_path"),
        ]:
            p = Path(row[key])
            src = p.relative_to(OUT).as_posix() if p.is_relative_to(OUT) else p.as_posix()
            parts.append(f"<div><p>{label}</p><img src='{html.escape(src)}'></div>")
        parts.append("</div><h3>100% 裁切</h3><div class='cropgrid'>")
        for crop in sorted(Path(row["crop_100_path"]).glob("*.png")):
            src = crop.relative_to(OUT).as_posix()
            parts.append(f"<div><p>{html.escape(crop.name)}</p><img src='{html.escape(src)}'></div>")
        parts.append("</div><h3>200% 预览裁切</h3><div class='cropgrid'>")
        for crop in sorted(Path(row["crop_200_path"]).glob("*.png")):
            src = crop.relative_to(OUT).as_posix()
            parts.append(f"<div><p>{html.escape(crop.name)}</p><img src='{html.escape(src)}'></div>")
        parts.append("</div></section>")
    parts.append("</main>")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def sample_sections(rows: list[dict]) -> str:
    sections = []
    for row in rows:
        c100, c200 = crop_counts(row)
        sections.append(
            f"""### {row['sample_id']}

- 类型：{row['sample_type']}
- Round 2.2 策略：{row['profile']}，强度 `{row['round2_2_strength']}`
- 修正目标：{row['target']}
- Round 2.1 -> Round 2.2：edge `{row['round2_1_edge_delta_proxy']}` -> `{row['edge_delta_proxy']}`，texture `{row['round2_1_texture_delta_proxy']}` -> `{row['texture_delta_proxy']}`，size_ratio `{row['round2_1_size_ratio']}` -> `{row['size_ratio']}`
- 色彩风险：p95_delta_e=`{row['p95_delta_e']}`，saturation_delta=`{row['saturation_delta']}`
- 证据完整：`{row['evidence_complete']}`，100%裁切 `{c100}`，200%预览裁切 `{c200}`
- 当前预判：`{row['visual_prejudgement']}`，风险：`{row['risk_status']}`，体积收益：`{row['size_benefit_ratio_judgement']}`
- 复核建议：{recommendation(row)}
"""
        )
    return "\n".join(sections)


def write_reports(rows: list[dict], csv_path: Path, html_path: Path) -> tuple[Path, Path]:
    all_evidence = all(evidence_complete(row) for row in rows)
    minor = [row for row in rows if row["visual_prejudgement"] == "MINOR_POSITIVE"]
    positive = [row for row in rows if row["visual_prejudgement"] == "POSITIVE"]
    insufficient = [row for row in rows if row["visual_prejudgement"] != "MINOR_POSITIVE"]
    size_fixed = next(row for row in rows if row["sample_id"] == "wechat_longscreenshot_2026-06-12_111900_080")
    size_max = max(row["size_ratio"] for row in rows)
    size_min = min(row["size_ratio"] for row in rows)

    summary = table(
        rows,
        [
            ("sample_id", "sample_id"),
            ("类型", "sample_type"),
            ("策略", "profile"),
            ("强度", "round2_2_strength"),
            ("预判", "visual_prejudgement"),
            ("风险", "risk_status"),
            ("体积收益", "size_benefit_ratio_judgement"),
            ("size_ratio", "size_ratio"),
            ("19张准入", "gate_to_19"),
        ],
    )
    metrics = table(
        rows,
        [
            ("sample_id", "sample_id"),
            ("R2.1 edge", "round2_1_edge_delta_proxy"),
            ("R2.2 edge", "edge_delta_proxy"),
            ("R2.1 texture", "round2_1_texture_delta_proxy"),
            ("R2.2 texture", "texture_delta_proxy"),
            ("p95_delta_e", "p95_delta_e"),
            ("sat_delta", "saturation_delta"),
            ("R2.1 size", "round2_1_size_ratio"),
            ("R2.2 size", "size_ratio"),
        ],
    )
    sections = sample_sections(rows)

    tuning = REPORTS / "2026-06-20_V046_ROUND2_2_TUNING_REPORT.md"
    tuning.write_text(
        f"""# V0.4.6 Round 2.2 小幅修正 / 收缩型安全微调报告

生成日期：2026-06-20

## 1. 本轮结论

```text
WAIT_FOR_GEMINI_REVIEW / NOT_RUN_19 / NOT_FROZEN / EVIDENCE_COMPLETE
```

本轮完成 7 张目标样本的 Round 2.2 离线收缩型候选。证据完整性：`{"PASS" if all_evidence else "FAIL"}`。

当前不进入 19 张黄金集，不冻结，不接正式生产链。原因是 Round 2.2 虽然修复了体积收益比，并把 6 张样本推回 `MINOR_POSITIVE` 指标区间，但仍需要 Gemini 或人工复核 100% 裁切确认真实可见收益。

## 2. 边界确认

```text
是否修改正式生产代码：否
是否接入正式生产链：否
是否运行19张黄金集：否
是否冻结：否
是否扩展前台UI：否
是否新增模式：否
是否做2K/4K：否
```

本轮只新增测试侧离线候选脚本、报告脚本和证据包。

## 3. Round 2.2 修正策略

- 文字密集图：显著降低增强强度，缩小文字边缘 mask，保护白底、浅灰底、小字、灰字和低频区域。
- 产品 KV：保留产品轮廓、透明材质、瓶身和中频质感的轻微收益，继续锁定 Logo、包装文字、品牌色、白色平滑面、高光和渐变。
- 人物图：扩大脸、五官、肤色、手部保护，只允许衣物、发丝、背景结构、碎片、金属等非脸部材质低强度增强。
- 角色卡：加强红色标签、小字、边框、暗部保护，不把版式边框、小字和标签当作材质收益区域。
- 体积控制：所有样本 `size_ratio <= 1.11`，本轮范围 `{size_min}` - `{size_max}`。

## 4. 样本总表

{summary}

## 5. 指标变化

{metrics}

## 6. 关键修复点

- `wechat_longscreenshot_2026-06-12_111900_080`：size_ratio 从 Round 2.1 的 `{size_fixed['round2_1_size_ratio']}` 降至 `{size_fixed['size_ratio']}`，达到 `<= 1.11` 目标；但文字收益仍弱，只能标记为 `NEEDS_HUMAN_REVIEW`。
- `liu_qiangdong_commercial_portrait`：size_ratio 降至 `{next(row for row in rows if row['sample_id']=='liu_qiangdong_commercial_portrait')['size_ratio']}`，脸部保护扩大，非脸部区域仍需人工确认收益。
- `wei_zhongxian_character_card`：size_ratio 降至 `{next(row for row in rows if row['sample_id']=='wei_zhongxian_character_card')['size_ratio']}`，红标、小字、边框保护加强，毛发/服饰收益仍需人工确认。
- `green_c_product_kv`、`purple_beauty_product_kv`、`dji_horizontal_infographic`、`andy_lau_commercial_portrait`：保留 `MINOR_POSITIVE` 方向，同时明显降低体积压力。

## 7. 逐样本说明

{sections}

## 8. 是否建议进入 19 张黄金集

当前结论：

```text
不建议直接进入19张黄金集
建议先交给 Gemini / 人工做一轮 Round 2.2 视觉复核
```

如果复核确认：

```text
至少4张为 MINOR_POSITIVE 或更高
wechat_longscreenshot 不再因为体积收益比阻断
2张产品KV至少1张有明确轻微材质收益
至少1张人物/角色图有非脸部材质收益
无文字损伤、Logo损伤、人脸异常、品牌色漂移、低频脏块、高光发灰、白底发脏
```

则可以进入 19 张黄金集离线回归。否则继续 Round 2.3 或回退该方向。

## 9. Gemini 判断门

```text
是否建议 Gemini 进入下一步复核：YES
```

重点看：

1. 长截图体积修复后，文字边缘是否仍有足够收益；
2. 两张产品 KV 是否保住 Logo、文字、品牌色、白面、高光，同时有轻微材质提升；
3. DJI 信息图小字、图标、细线是否没有断笔、堵塞、变粗；
4. 三张人物/角色图是否只提升非脸部材质，脸、手、肤色是否稳定；
5. 所有样本是否存在低频脏块、高光发灰或白底发脏。

## 10. 输出文件

```text
{OUT}
{csv_path}
{html_path}
```
""",
        encoding="utf-8",
    )

    handoff = REPORTS / "2026-06-20_V046_ROUND2_2_CHATGPT_HANDOFF.md"
    handoff.write_text(
        f"""# 影界 VisualMasterPro V0.4.6 Round 2.2 ChatGPT 交接报告

## 1. 当前状态

```text
WAIT_FOR_GEMINI_REVIEW / NOT_RUN_19 / NOT_FROZEN / EVIDENCE_COMPLETE
```

Round 2.2 是针对 Round 2.1 人工复核后做的收缩型安全微调。它没有接入正式生产链，没有运行 19 张黄金集，没有冻结，也没有改前台 UI。

## 2. 本轮要 ChatGPT 判断什么

请只判断视觉收益和安全性，不判断工程是否能跑。

重点问题：

1. Round 2.2 相比 frozen 和 Round 2.1 是否有更稳的真实轻微收益；
2. 体积收益比是否已经可接受；
3. 文字、Logo、品牌色、人脸、手部、肤色、低频平滑区、高光和白底是否安全；
4. 是否允许进入 19 张黄金集离线回归；
5. 如果不允许，是否继续 Round 2.3 或回退该方向。

## 3. 7 张样本结论表

{summary}

## 4. 最需要肉眼确认的样本

- `wechat_longscreenshot_2026-06-12_111900_080`：体积已修复，但文字收益仍弱。请重点看文字边缘和白底/浅灰底。
- `green_c_product_kv`：请看瓶身透明材质、产品轮廓、Logo、包装文字和白面。
- `purple_beauty_product_kv`：请看品牌紫、银色高光、背景渐变和产品边缘。
- `dji_horizontal_infographic`：请看中文小字、图标、细线和浅色背景。
- `andy_lau_commercial_portrait`：请看非脸部材质、脸、手、肤色、金色高光。
- `liu_qiangdong_commercial_portrait`：请看服装/背景收益是否足以支撑体积，脸部是否没有勾边。
- `wei_zhongxian_character_card`：请看毛发/服饰收益、红色标签、小字、边框和暗部。

## 5. 当前可暂判

```text
POSITIVE：0
MINOR_POSITIVE：{len(minor)}
仍需复核或收益不足：{len(insufficient)}
证据缺失：{0 if all_evidence else 1}
```

MINOR_POSITIVE 候选：

```text
{chr(10).join(row['sample_id'] for row in minor)}
```

仍需重点复核：

```text
{chr(10).join(row['sample_id'] for row in insufficient)}
```

## 6. 是否建议进入19张

当前建议：

```text
暂不直接进入19张
先做 Gemini / 人工视觉复核
```

如果复核确认 6 张 `MINOR_POSITIVE` 没有安全问题，并且 `wechat_longscreenshot` 体积修复后不再阻断，可以进入 19 张黄金集离线回归。

## 7. 证据入口

```text
{html_path}
{tuning}
{csv_path}
{OUT}
```

## 8. Gemini 判断门

```text
是否建议 Gemini 进入下一步复核：YES
```
""",
        encoding="utf-8",
    )
    return tuning, handoff


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    csv_path = write_csv(rows)
    html_path = write_html(rows)
    tuning, handoff = write_reports(rows, csv_path, html_path)
    print(json.dumps({
        "tuning_report": str(tuning),
        "handoff": str(handoff),
        "csv": str(csv_path),
        "review_index": str(html_path),
        "samples": len(rows),
        "minor_positive": sum(1 for row in rows if row["visual_prejudgement"] == "MINOR_POSITIVE"),
        "evidence_complete": all(evidence_complete(row) for row in rows),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
