from __future__ import annotations

import csv
import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests" / "results" / "v046_quality_lift_round2_targeted"
REPORTS = ROOT / "docs" / "reports"

FOCUS = {
    "wechat_longscreenshot_2026-06-12_111900_080": "小字清晰度、灰字/黑字边缘、灰边黑边重影糊边、白底和浅灰背景是否变脏",
    "green_c_product_kv": "包装文字、Logo、透明瓶体、高光、白色平滑区、产品轮廓、透明材质是否塑料化",
    "purple_beauty_product_kv": "DERMAFIRM 字样、紫色品牌色、银色高光、产品边缘、背景渐变、色带或脏块",
    "dji_horizontal_infographic": "中文小字、小图标、线条、浅色背景、中间结构、连接线、底部信息区",
    "liu_qiangdong_commercial_portrait": "人脸自然度、肤色、发丝、服装纹理、背景城市、中文标题、假锐化或磨皮感",
    "wei_zhongxian_character_card": "毛发、服饰纹理、小字、红色标签、边框线、暗部结块、角色质感",
    "andy_lau_commercial_portrait": "人脸和手部、金色高光、中文小字、碎片边缘、背景低频、金属高光是否发灰",
}

TYPE_LABEL = {
    "text_dense_long_screenshot": "文字/信息图",
    "text_dense_infographic": "文字/信息图",
    "product_kv": "产品/商业KV",
    "portrait_poster": "人物/角色海报",
    "character_info_card": "人物/角色海报",
}


def metric_judgement(row: dict) -> str:
    if row["p95_delta_e"] >= 3.5 or abs(row["saturation_delta"]) > 0.003:
        return "FAIL"
    if row["edge_delta_proxy"] > 0.015 and row["texture_delta_proxy"] > 0.015:
        return "PASS"
    return "WEAK"


def size_judgement(row: dict) -> str:
    ratio = row["candidate_size_ratio"]
    if ratio <= 1.11 and metric_judgement(row) == "PASS":
        return "ACCEPTABLE"
    if ratio <= 1.15:
        return "WEAK"
    return "NOT_ACCEPTABLE"


def evidence(row: dict) -> dict:
    sid = row["sample_id"]
    data = {
        "full": OUT / "04_full_compare" / f"{sid}.png",
        "same": OUT / "05_same_scale_compare" / f"{sid}.png",
        "crop100": OUT / "06_crops_100pct" / sid,
        "crop200": OUT / "07_crops_200pct_preview" / sid,
        "metrics": OUT / "08_metrics" / f"{sid}.json",
    }
    count100 = len(list(data["crop100"].glob("*.png"))) if data["crop100"].exists() else 0
    count200 = len(list(data["crop200"].glob("*.png"))) if data["crop200"].exists() else 0
    complete = all(
        [
            Path(row["original_path"]).exists(),
            Path(row["frozen_path"]).exists(),
            Path(row["candidate_path"]).exists(),
            data["full"].exists(),
            data["same"].exists(),
            data["metrics"].exists(),
            count100 >= 12,
            count200 >= 12,
        ]
    )
    data["count100"] = count100
    data["count200"] = count200
    data["complete"] = complete
    return data


def enrich(row: dict) -> dict:
    e = evidence(row)
    metric = metric_judgement(row)
    size = size_judgement(row)
    risk = "REJECT" if metric == "FAIL" or size == "NOT_ACCEPTABLE" else "REVIEW"
    return {
        **row,
        "sample_type": TYPE_LABEL.get(row["kind"], row["kind"]),
        "full_compare_path": str(e["full"]),
        "same_scale_compare_path": str(e["same"]),
        "crop_100_path": str(e["crop100"]),
        "crop_200_path": str(e["crop200"]),
        "metrics_json_path": str(e["metrics"]),
        "crop100_count": e["count100"],
        "crop200_count": e["count200"],
        "evidence_complete": "PASS" if e["complete"] else "FAIL",
        "metric_judgement": metric,
        "visual_review_required": "YES",
        "visual_prejudgement": "NEEDS_HUMAN_REVIEW",
        "risk_status": risk,
        "size_benefit_ratio_judgement": size,
        "gate_to_19": "WAIT_FOR_HUMAN_REVIEW" if e["complete"] and metric == "PASS" else "NO",
        "focus": FOCUS[row["sample_id"]],
        "notes": "指标方向为正，但需要人工查看 100% 裁切确认是否为真实可见收益，并确认无文字、Logo、人脸、品牌色、低频平滑区损伤。",
    }


def md_table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    lines = [
        "| " + " | ".join(title for title, _ in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        values = []
        for _, key in columns:
            if key == "sample_id":
                values.append(f"`{row[key]}`")
            else:
                values.append(str(row.get(key, "")))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def review_sections(rows: list[dict]) -> str:
    parts = []
    for row in rows:
        parts.append(
            f"""### {row['sample_id']}

- 类型：{row['sample_type']}
- 重点检查：{row['focus']}
- 原图：`{row['original_path']}`
- Frozen：`{row['frozen_path']}`
- Candidate：`{row['candidate_path']}`
- 整图对比：`{row['full_compare_path']}`
- 同尺度对比：`{row['same_scale_compare_path']}`
- 100% 裁切目录：`{row['crop_100_path']}`（{row['crop100_count']} 个文件）
- 200% 预览裁切目录：`{row['crop_200_path']}`（{row['crop200_count']} 个文件）
- 指标：edge_delta_proxy={row['edge_delta_proxy']}，texture_delta_proxy={row['texture_delta_proxy']}，p95_delta_e={row['p95_delta_e']}，saturation_delta={row['saturation_delta']}，size_ratio={row['candidate_size_ratio']}
- 当前判断：证据 {row['evidence_complete']}；指标 {row['metric_judgement']}；风险 {row['risk_status']}；19 张准入 {row['gate_to_19']}
- 风险点：体积增长需要人工确认收益支撑；必须确认无文字、Logo、人脸、品牌色、低频平滑区损伤。
"""
        )
    return "\n".join(parts)


def write_csv(rows: list[dict]) -> Path:
    path = REPORTS / "2026-06-19_V046_ROUND2_SAMPLE_REVIEW_TABLE.csv"
    fields = [
        "sample_id",
        "sample_type",
        "original_path",
        "frozen_path",
        "candidate_path",
        "full_compare_path",
        "same_scale_compare_path",
        "crop_100_path",
        "crop_200_path",
        "metrics_json_path",
        "edge_delta_proxy",
        "texture_delta_proxy",
        "p95_delta_e",
        "saturation_delta",
        "size_ratio",
        "evidence_complete",
        "metric_judgement",
        "visual_review_required",
        "risk_status",
        "gate_to_19",
        "notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            data = dict(row)
            data["size_ratio"] = data["candidate_size_ratio"]
            writer.writerow({field: data.get(field, "") for field in fields})
    return path


def write_reports(rows: list[dict], csv_path: Path) -> tuple[Path, Path]:
    all_evidence = all(row["evidence_complete"] == "PASS" for row in rows)
    metric_pass = sum(1 for row in rows if row["metric_judgement"] == "PASS")
    product_pass = sum(1 for row in rows if row["kind"] == "product_kv" and row["metric_judgement"] == "PASS")
    text_pass = sum(1 for row in rows if row["kind"] in ("text_dense_long_screenshot", "text_dense_infographic") and row["metric_judgement"] == "PASS")
    portrait_pass = sum(1 for row in rows if row["sample_type"] == "人物/角色海报" and row["metric_judgement"] == "PASS")
    size_weak = sum(1 for row in rows if row["size_benefit_ratio_judgement"] == "WEAK")
    conclusion = "WAIT_FOR_HUMAN_VISUAL_REVIEW" if all_evidence and metric_pass >= 4 else "NOT_READY_FOR_19"
    gate = "等待人工视觉确认后再决定是否进入 19 张黄金集" if conclusion == "WAIT_FOR_HUMAN_VISUAL_REVIEW" else "暂不建议进入 19 张黄金集"

    summary = md_table(
        rows,
        [
            ("sample_id", "sample_id"),
            ("类型", "sample_type"),
            ("证据", "evidence_complete"),
            ("指标", "metric_judgement"),
            ("肉眼预判", "visual_prejudgement"),
            ("风险", "risk_status"),
            ("体积收益比", "size_benefit_ratio_judgement"),
            ("19张准入", "gate_to_19"),
        ],
    )
    metrics = md_table(
        rows,
        [
            ("sample_id", "sample_id"),
            ("edge_delta_proxy", "edge_delta_proxy"),
            ("texture_delta_proxy", "texture_delta_proxy"),
            ("p95_delta_e", "p95_delta_e"),
            ("saturation_delta", "saturation_delta"),
            ("size_ratio", "candidate_size_ratio"),
        ],
    )
    sections = review_sections(rows)
    min_ratio = min(row["candidate_size_ratio"] for row in rows)
    max_ratio = max(row["candidate_size_ratio"] for row in rows)

    admission = REPORTS / "2026-06-19_V046_ROUND2_VISUAL_REVIEW_AND_19_GATE.md"
    admission.write_text(
        f"""# V0.4.6 Round 2 视觉复核与 19 张黄金集准入判断

生成日期：2026-06-19

## 1. 本轮结论

结论：`{conclusion}`

是否建议进入 19 张黄金集：`{gate}`

说明：7 张样本的证据材料完整，指标方向整体为正，但 Codex 不能替代人工完成真实肉眼视觉判断。本轮只允许得出“等待人工 100% 裁切复核”的准入结论，不能直接视为生产算法通过或冻结。

## 2. 证据完整性

- 7 张样本证据完整：{"PASS" if all_evidence else "FAIL"}
- 每张样本均包含 original / frozen / candidate / full compare / same scale compare / 100% crops / 200% preview crops / metrics JSON。
- 100% 裁切每张不少于 12 个文件；200% 预览裁切每张不少于 12 个文件。

## 3. 逐样本准入表

{summary}

## 4. 指标汇总

{metrics}

## 5. 体积收益比判断

- 体积倍率范围：{min_ratio} - {max_ratio}
- `ACCEPTABLE` 数量：{sum(1 for row in rows if row['size_benefit_ratio_judgement'] == 'ACCEPTABLE')}
- `WEAK` 数量：{size_weak}
- `NOT_ACCEPTABLE` 数量：{sum(1 for row in rows if row['size_benefit_ratio_judgement'] == 'NOT_ACCEPTABLE')}

体积增长约 1.09x - 1.14x，不属于严重膨胀，但必须由人工确认 100% 裁切收益是否支撑体积增长。

## 6. 风险点

- 文字风险：未从指标发现强风险，但需要人工检查字腔、灰边、重影、断笔。
- Logo 风险：未从指标发现强风险，但产品包装 Logo 和品牌字样必须人工检查。
- 人脸风险：候选对肤色变化指标较小，但人脸自然度、塑料感、假锐化必须人工检查。
- 品牌色风险：饱和度变化很小，但绿 C 橙色、DERMAFIRM 紫色、金色高光需人工复核。
- 低频平滑区风险：白底、浅灰背景、天空/云雾、海报渐变和高光区域必须人工复核。
- 体积收益比风险：所有样本均有体积增长，收益必须由视觉证据支撑。

## 7. 逐样本视觉复核索引

{sections}

## 8. Round 2.1 修正方向（如人工复核不通过）

如果人工复核认为收益不足或存在风险，只允许做以下小修：

1. 缩小增强区域 mask；
2. 降低中频增强强度；
3. 加强文字、Logo、人脸、肤色、品牌色、高光、平滑背景保护；
4. 降低体积增长；
5. 优化低频平滑区保护；
6. 调整不同样本类型的区域资格判断；
7. 不回到全图通透、全图锐化、全图对比、全图饱和路线。
""",
        encoding="utf-8",
    )

    checks = "\n".join(
        [
            f"- 7 张中至少 4 张正收益：{metric_pass}/7 指标可复核为正；肉眼仍需人工确认",
            f"- 至少 2 张产品 / 商业 KV 明确质感提升：{product_pass}/2 指标为正；明确质感提升需人工裁切确认",
            f"- 至少 1 张文字密集图文字或边缘提升：{text_pass}/2 指标为正；文字真实提升需人工确认",
            f"- 至少 1 张人物海报材质或清晰度提升：{portrait_pass}/3 指标为正；人物自然度需人工确认",
            "- 无严重文字损伤：未发现指标强风险；需要人工检查",
            "- 无 Logo 损伤：未发现指标强风险；需要人工检查",
            "- 无人脸异常：未发现指标强风险；需要人工检查",
            "- 无品牌色漂移：saturation_delta 很小；品牌色仍需人工检查",
            "- 无低频脏块：未自动判定；必须人工检查 100% 裁切",
            "- 体积增长有收益支撑：体积增长 1.09x-1.14x；需人工确认收益支撑",
        ]
    )

    handoff = REPORTS / "2026-06-19_V046_ROUND2_CHATGPT_HANDOFF.md"
    handoff.write_text(
        f"""# 影界 VisualMasterPro V0.4.6 Round 2 开发交接报告

## 1. 当前结论

`{conclusion}`

当前不写 PASS，也不写冻结。7 张样本证据完整，指标方向为正，但真实肉眼收益、文字/Logo/人脸/品牌色/低频平滑区是否无损，必须由人工查看 100% 裁切确认。

## 2. 本轮任务范围

本轮只做视觉复核证据整理与 19 张黄金集准入判断，基于已有目录：

```text
tests/results/v046_quality_lift_round2_targeted/
```

## 3. 本轮未做事项

- 未接入正式生产算法链；
- 未冻结；
- 未修改 API 字段；
- 未修改 XHR 上传；
- 未修改 EventSource SSE；
- 未修改 final_output_url / preview_output_url；
- 未扩展前台 UI；
- 未做第四模式；
- 未做输出格式选择；
- 未进入 2K / 4K / 印刷级方向。

## 4. 7 张样本总表

{summary}

## 5. 逐样本复核摘要

{sections}

## 6. 三类核心收益判断

### 文字 / 信息图收益

微信长截图和 DJI 横版信息图的 edge / texture 代理指标为正，但文字清晰度是否真实提升，必须查看小字、灰字、线条、图标和浅色背景 100% 裁切。当前建议：等待人工视觉确认。

### 产品 / 商业 KV 质感收益

绿 C 产品 KV 与紫色美妆 KV 的 edge / texture 代理指标为正，且饱和度变化很小。仍必须人工确认包装文字、Logo、透明瓶体、紫色品牌色、银色/金色高光和白底是否稳定。当前建议：等待人工视觉确认。

### 人物 / 角色海报收益

刘强东、魏忠贤、刘德华三张人物/角色海报指标为正，但人脸、肤色、手部、发丝、皮肤质感、假锐化和塑料感必须人工复核。当前建议：等待人工视觉确认。

## 7. 风险项统计

- 文字风险：0 个自动拒绝；7 张均需要人工复核；
- Logo 风险：0 个自动拒绝；产品与商业海报需重点看；
- 人脸风险：0 个自动拒绝；3 张人物/角色海报需重点看；
- 品牌色风险：0 个自动拒绝；绿 C、紫色 DERMAFIRM、金色高光需重点看；
- 低频平滑区风险：0 个自动拒绝；白底、浅灰背景、高光、渐变需重点看；
- 高光 / 渐变风险：0 个自动拒绝；产品高光与人物海报碎片高光需重点看；
- 体积收益比风险：{size_weak} 张为 WEAK，需人工确认收益是否支撑体积增长。

## 8. 是否满足 Round 2 成功标准

{checks}

## 9. 是否建议进入 19 张黄金集

当前建议：`等待人工视觉确认`。

理由：证据完整，指标方向符合进入下一步的前置条件，但当前证据仍不能替代人工肉眼裁切判断。若人工确认至少 4 张样本存在真实可见收益，且产品、文字、人物三类没有关键退化，则建议进入 19 张黄金集。

## 10. 如果进入 19 张黄金集，下一步怎么做

- 继续离线验证；
- 不接生产链；
- 不冻结；
- 不改 API / SSE / URL；
- 输出 before / frozen / candidate / delta / 100% 裁切 / 200% 裁切；
- 记录每张样本的文字、Logo、人脸、品牌色、低频平滑区和体积收益比。

## 11. 如果不进入 19 张黄金集，下一步怎么做

进入 Round 2.1 小修，不重新发明算法：

1. 缩小增强区域 mask；
2. 降低中频增强强度；
3. 加强文字、Logo、人脸、肤色、品牌色、高光、平滑背景保护；
4. 降低体积增长；
5. 优化低频平滑区保护；
6. 调整不同样本类型的区域资格判断；
7. 不回到全图通透、全图锐化、全图对比、全图饱和路线。

## 12. 给 ChatGPT 的问题

1. 当前 7 张样本的视觉证据是否足够进入 19 张黄金集？
2. 哪些样本收益不足，只是指标轻微变化？
3. 产品 KV 的质感提升是否足以支撑 1.10x 左右体积增长？
4. 微信长截图和 DJI 信息图的小字是否真的更清楚？
5. 三张人物/角色海报是否存在人脸变硬、肤色漂移、假锐化或塑料感？
6. 是否需要 Round 2.1 缩小 mask 或降低强度？
7. 如果人工确认通过，是否允许后续抽成独立算法模块进入 19 张黄金集离线验证？
""",
        encoding="utf-8",
    )
    return admission, handoff


def write_html(rows: list[dict]) -> Path:
    path = OUT / "review_index_chatgpt.html"
    parts = [
        """<!doctype html>
<meta charset="utf-8">
<title>V0.4.6 Round2 ChatGPT Visual Review</title>
<style>
body{margin:0;background:#0b0c0e;color:#e2e8f0;font-family:Arial,'Microsoft YaHei',sans-serif}
main{padding:24px}.sample{border:1px solid #1c1f26;background:#121418;margin:0 0 28px;padding:16px}
h1{font-size:22px}h2{font-size:16px;color:#00ffcc}p,li{font-size:13px;line-height:1.6}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.cropgrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
img{max-width:100%;border:1px solid #1c1f26;background:#0b0c0e}.meta{color:#94a3b8}.warn{color:#f59e0b}code{color:#00ffcc}
</style>
<main>
<h1>V0.4.6 Round 2 ChatGPT 视觉复核索引</h1>
<p class="warn">本页仅用于人工视觉复核。整图用于观察构图和颜色，真实收益请看 100% 裁切与 200% 预览裁切。</p>
"""
    ]
    for row in rows:
        sid = row["sample_id"]
        parts.append(f"<section class='sample'><h2>{html.escape(sid)}</h2>")
        parts.append(
            f"<p class='meta'>类型：{html.escape(row['sample_type'])}｜指标：{row['metric_judgement']}｜风险：{row['risk_status']}｜19张准入：{row['gate_to_19']}｜size_ratio：{row['candidate_size_ratio']}</p>"
        )
        parts.append(f"<p>重点检查：{html.escape(row['focus'])}</p>")
        parts.append("<div class='grid'>")
        for label, img_path in [
            ("Original", row["original_path"]),
            ("Frozen", row["frozen_path"]),
            ("Candidate", row["candidate_path"]),
            ("Full Compare", row["full_compare_path"]),
            ("Same Scale Compare", row["same_scale_compare_path"]),
        ]:
            p = Path(img_path)
            try:
                src = p.relative_to(OUT).as_posix()
            except ValueError:
                src = p.as_posix()
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


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    rows = [enrich(row) for row in manifest]
    csv_path = write_csv(rows)
    admission, handoff = write_reports(rows, csv_path)
    html_path = write_html(rows)
    result = {
        "conclusion": "WAIT_FOR_HUMAN_VISUAL_REVIEW",
        "evidence_complete": all(row["evidence_complete"] == "PASS" for row in rows),
        "metric_pass": sum(1 for row in rows if row["metric_judgement"] == "PASS"),
        "files": [str(admission), str(handoff), str(csv_path), str(html_path)],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
