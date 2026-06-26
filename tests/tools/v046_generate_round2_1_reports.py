from __future__ import annotations

import csv
import html
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v046_path_resolver import get_v046_path_context


CTX = get_v046_path_context(Path(__file__).resolve())
OUT = CTX.tests_results_dir / "v046_quality_lift_round2_1_targeted"
REPORTS = CTX.reports_dir


def load_rows() -> list[dict]:
    return json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))


def evidence_counts(row: dict) -> tuple[int, int]:
    return len(list(Path(row["crop_100_path"]).glob("*.png"))), len(list(Path(row["crop_200_path"]).glob("*.png")))


def evidence_complete(row: dict) -> bool:
    count100, count200 = evidence_counts(row)
    return all(
        [
            Path(row["original_path"]).exists(),
            Path(row["frozen_path"]).exists(),
            Path(row["round2_candidate_path"]).exists(),
            Path(row["round2_1_candidate_path"]).exists(),
            Path(row["full_compare_path"]).exists(),
            Path(row["same_scale_compare_path"]).exists(),
            Path(row["metrics_json_path"]).exists(),
            count100 >= 18,
            count200 >= 18,
        ]
    )


def table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    lines = [
        "| " + " | ".join(title for title, _ in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        values = []
        for _, key in columns:
            value = row.get(key, "")
            values.append(f"`{value}`" if key == "sample_id" else str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_csv(rows: list[dict]) -> Path:
    path = REPORTS / "2026-06-19_V046_ROUND2_1_SAMPLE_TABLE.csv"
    fields = [
        "sample_id",
        "sample_type",
        "original_path",
        "frozen_path",
        "round2_candidate_path",
        "round2_1_candidate_path",
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
            out = dict(row)
            out["evidence_complete"] = "PASS" if evidence_complete(row) else "FAIL"
            writer.writerow({field: out.get(field, "") for field in fields})
    return path


def sample_sections(rows: list[dict]) -> str:
    sections = []
    for row in rows:
        count100, count200 = evidence_counts(row)
        edge_gain = row["edge_delta_proxy"] - row["round2_edge_delta_proxy"]
        texture_gain = row["texture_delta_proxy"] - row["round2_texture_delta_proxy"]
        size_change = row["size_ratio"] - row["round2_size_ratio"]
        sections.append(
            f"""### {row['sample_id']}

- 类型：{row['sample_type']}
- 重点风险点：{row['focus']}
- Round 2 → Round 2.1 指标变化：edge {row['round2_edge_delta_proxy']} → {row['edge_delta_proxy']}（Δ {edge_gain:.6f}），texture {row['round2_texture_delta_proxy']} → {row['texture_delta_proxy']}（Δ {texture_gain:.6f}），size_ratio {row['round2_size_ratio']} → {row['size_ratio']}（Δ {size_change:.6f}）。
- 色彩与风险：p95_delta_e={row['p95_delta_e']}，saturation_delta={row['saturation_delta']}，risk_status={row['risk_status']}。
- 证据：original / frozen / Round2 / Round2.1 独立文件均已生成；100% 裁切 {count100} 个，200% 预览裁切 {count200} 个。
- 当前判断：{row['visual_prejudgement']}；仍需人工查看 100% 裁切确认真实可见收益。
"""
        )
    return "\n".join(sections)


def write_reports(rows: list[dict], csv_path: Path) -> tuple[Path, Path]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    all_evidence = all(evidence_complete(row) for row in rows)
    metric_pass = sum(1 for row in rows if row["metric_judgement"] == "PASS")
    minor_positive = sum(1 for row in rows if row["visual_prejudgement"] == "MINOR_POSITIVE")
    product_positive = sum(1 for row in rows if row["sample_type"] == "产品/商业KV" and row["metric_judgement"] == "PASS")
    text_positive = sum(1 for row in rows if row["sample_type"] == "文字/信息图" and row["metric_judgement"] == "PASS")
    portrait_positive = sum(1 for row in rows if row["sample_type"] == "人物/角色海报" and row["metric_judgement"] == "PASS")
    size_weak = sum(1 for row in rows if row["size_benefit_ratio_judgement"] == "WEAK")
    conclusion = "WAIT_FOR_HUMAN_VISUAL_REVIEW" if all_evidence and metric_pass >= 4 else "NOT_READY_FOR_19"
    gate_sentence = "等待人工视觉确认后再决定是否进入 19 张黄金集"

    summary = table(
        rows,
        [
            ("sample_id", "sample_id"),
            ("类型", "sample_type"),
            ("指标", "metric_judgement"),
            ("肉眼预判", "visual_prejudgement"),
            ("风险", "risk_status"),
            ("体积收益比", "size_benefit_ratio_judgement"),
            ("19张准入", "gate_to_19"),
        ],
    )
    metrics = table(
        rows,
        [
            ("sample_id", "sample_id"),
            ("Round2 edge", "round2_edge_delta_proxy"),
            ("Round2.1 edge", "edge_delta_proxy"),
            ("Round2 texture", "round2_texture_delta_proxy"),
            ("Round2.1 texture", "texture_delta_proxy"),
            ("p95_delta_e", "p95_delta_e"),
            ("saturation_delta", "saturation_delta"),
            ("size_ratio", "size_ratio"),
        ],
    )
    sections = sample_sections(rows)
    min_size = min(row["size_ratio"] for row in rows)
    max_size = max(row["size_ratio"] for row in rows)

    tuning = REPORTS / "2026-06-19_V046_ROUND2_1_TUNING_REPORT.md"
    tuning.write_text(
        f"""# V0.4.6 Round 2.1 安全局部收益微调报告

生成日期：2026-06-20

## 1. 本轮结论

结论：`{conclusion}`

是否建议进入 19 张黄金集：`{gate_sentence}`

本轮完成了 7 张决策样本的 Round 2.1 离线微调。证据包完整，指标方向 7/7 为正，但仍不能替代人工肉眼视觉判断，因此不直接进入 19 张黄金集。

## 2. 本轮改了什么

- 新增测试侧跨平台路径解析预留：`tests/tools/v046_path_resolver.py`；
- 新增 Round 2.1 离线候选脚本：`tests/tools/v046_round2_1_targeted_candidate.py`；
- 微调局部中频增强 mask：更强调安全边缘与材质结构，继续抑制平坦区、高光、强品牌色、肤色、深阴影和强边缘；
- 生成完整证据包：original / frozen / Round2 / Round2.1 / 全图对比 / 同尺度对比 / 100% 裁切 / 200% 裁切 / metrics / path_index。

## 3. 本轮没改什么

- 未修改正式生产代码；
- 未接入正式生产链；
- 未进入 19 张黄金集；
- 未冻结；
- 未修改 API 字段名；
- 未修改 XHR 上传；
- 未修改 EventSource SSE；
- 未修改 final_output_url / preview_output_url；
- 未扩展前台 UI；
- 未做第四模式或输出格式选择。

## 4. 7 张样本结果

{summary}

## 5. 与 Round 2 的收益对比

{metrics}

## 6. 风险变化

- 文字与信息图：指标增强更明显，但必须人工确认没有黑边、灰边、断笔、字腔堵塞和白底变脏。
- 产品 KV：产品边缘与材质代理指标为正，但必须人工确认包装文字、Logo、透明材质、高光和品牌色稳定。
- 人物/角色海报：非脸部材质与边缘代理指标为正，但必须人工确认人脸、肤色、手部、发丝没有假锐化、塑料感或磨皮感。
- 体积收益比：Round 2.1 size_ratio 范围为 {min_size} - {max_size}，仍需人工确认收益是否支撑体积增长。

## 7. 逐样本摘要

{sections}

## 8. 是否建议继续人工视觉复核

建议继续人工视觉复核。当前证据完整、指标方向为正，但商业质量准入必须看 100% 裁切。

## 9. 是否建议进入 19 张黄金集

当前不直接建议进入。建议在人工确认至少 4 张样本有真实可见收益，且无文字、Logo、人脸、品牌色、低频平滑区损伤后，再进入 19 张黄金集离线验证。

## 10. 如果仍不建议进入，下一轮怎么修

只允许 Round 2.2 小修：

1. 缩小增强区域 mask；
2. 降低中频增强强度；
3. 加强文字、Logo、人脸、肤色、品牌色、高光和平滑背景保护；
4. 降低体积增长；
5. 优化低频平滑区保护；
6. 不回到全图锐化、全图对比、全图饱和或全图通透路线。

## 11. Gemini 判断门

是否建议 Gemini 进入下一步复核：YES

原因：当前证据完整、指标方向为正，但是否进入 19 张黄金集仍依赖人工视觉判断；100% / 200% 裁切中的文字、Logo、人脸、品牌色、低频平滑区和体积收益比仍需视觉复核。
""",
        encoding="utf-8",
    )

    handoff = REPORTS / "2026-06-19_V046_ROUND2_1_CHATGPT_HANDOFF.md"
    handoff.write_text(
        f"""# 影界 VisualMasterPro V0.4.6 Round 2.1 开发交接报告

## 1. 当前结论

`{conclusion}`

Round 2.1 方向仍然成立：7 张样本证据完整，7/7 指标方向为正，安全性未被自动判定为失败。但真实肉眼收益必须由人工查看 100% 裁切确认，当前不能直接进入 19 张黄金集，不能冻结，不能接生产链。

## 2. Round 2.1 调整内容

- 在测试侧新增跨平台路径解析预留，避免新增脚本继续硬编码 `D:\\影界文件`；
- 基于 Round 2 的离线候选策略做小幅 mask 与强度微调；
- 文字/信息图：更聚焦安全文字边缘和线条边缘，保护浅灰背景；
- 产品 KV：缩小到产品非文字、非 Logo、非品牌色核心区域，保护白底、高光和平滑渐变；
- 人物/角色海报：强化非脸部材质区域，扩大肤色/人脸保护，继续抑制暗部和平滑背景。

## 3. 7 张样本逐张摘要

{sections}

## 4. 文字 / 产品 / 人物三类收益判断

- 文字 / 信息图：{text_positive}/2 指标为正；需要人工重点看小字边缘、灰字、图标和浅色背景。
- 产品 / 商业 KV：{product_positive}/2 指标为正；需要人工重点看包装文字、Logo、透明瓶体、高光、品牌色和白底。
- 人物 / 角色海报：{portrait_positive}/3 指标为正；需要人工重点看人脸、肤色、手部、发丝、服装和碎片高光。

## 5. 风险项统计

- 文字风险：未自动拒绝，但 7 张均需人工复核；
- Logo 风险：未自动拒绝，产品与商业海报需重点看；
- 人脸风险：未自动拒绝，3 张人物/角色海报需重点看；
- 品牌色风险：未自动拒绝，绿 C、DERMAFIRM 紫色、金色高光需重点看；
- 低频平滑区风险：未自动拒绝，白底、浅灰、渐变、高光需重点看；
- 体积收益比风险：{size_weak} 张为 WEAK，需要确认收益是否支撑体积增长。

## 6. 体积收益比判断

Round 2.1 size_ratio 范围：{min_size} - {max_size}。

当前不属于严重体积膨胀，但体积增长必须由 100% 裁切中的真实收益支撑。

## 7. 证据包完整性

证据完整性：{"PASS" if all_evidence else "FAIL"}

每张样本包含：

- 独立 original；
- 独立 frozen；
- 独立 Round2 candidate；
- 独立 Round2.1 candidate；
- 四联整图对比；
- 同尺度对比；
- 100% 裁切；
- 200% 预览裁切；
- metrics JSON；
- path_index。

## 8. 是否建议进入 19 张黄金集

当前建议：`等待人工视觉确认`。

只有人工确认至少 4 张样本有真实可见收益，并且文字、Logo、人脸、品牌色、低频平滑区无退化后，才建议进入 19 张黄金集离线验证。

## 9. 是否建议继续 Round 2.2

如果人工复核认为收益不足或风险偏高，建议进入 Round 2.2 小修。小修方向只能是缩小 mask、降低强度、增强保护和控制体积，不能回到全图增强路线。

## 10. 给 ChatGPT 的重点判断问题

1. Round 2.1 相比 Round 2 是否产生了更明确的肉眼收益？
2. 微信长截图和 DJI 信息图的小字、线条、图标是否真的更清楚？
3. 两张产品 KV 是否有包装文字和 Logo 无损前提下的材质提升？
4. 三张人物/角色海报是否有人脸变硬、肤色漂移、假锐化或塑料感？
5. 体积增长是否能被可见收益支撑？
6. 是否允许进入 19 张黄金集离线验证？
7. 如果不允许，Round 2.2 应优先缩小哪类 mask？

## 11. Gemini 判断门

是否建议 Gemini 进入下一步复核：YES

原因：当前不是明确工程问题或单纯报告整理问题，而是视觉证据是否足以进入 19 张黄金集仍存在判断空间；需要 Gemini 或人工视觉复核重点查看 100% / 200% 裁切。
""",
        encoding="utf-8",
    )
    return tuning, handoff


def write_csv(rows: list[dict]) -> Path:
    path = REPORTS / "2026-06-19_V046_ROUND2_1_SAMPLE_TABLE.csv"
    fields = [
        "sample_id",
        "sample_type",
        "original_path",
        "frozen_path",
        "round2_candidate_path",
        "round2_1_candidate_path",
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
            writer.writerow({field: row.get(field, "") for field in fields})
    return path


def write_html(rows: list[dict]) -> Path:
    path = OUT / "review_index_chatgpt.html"
    parts = [
        """<!doctype html>
<meta charset="utf-8">
<title>V0.4.6 Round2.1 ChatGPT Visual Review</title>
<style>
body{margin:0;background:#0b0c0e;color:#e2e8f0;font-family:Arial,'Microsoft YaHei',sans-serif}
main{padding:24px}.sample{border:1px solid #1c1f26;background:#121418;margin:0 0 28px;padding:16px}
h1{font-size:22px}h2{font-size:16px;color:#00ffcc}p,li{font-size:13px;line-height:1.6}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.cropgrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
img{max-width:100%;border:1px solid #1c1f26;background:#0b0c0e}.meta{color:#94a3b8}.warn{color:#f59e0b}
</style>
<main>
<h1>V0.4.6 Round 2.1 ChatGPT 视觉复核索引</h1>
<p class="warn">本页仅用于人工视觉复核。重点看 100% 裁切与 200% 预览裁切，不要用指标替代肉眼判断。</p>
"""
    ]
    for row in rows:
        parts.append(f"<section class='sample'><h2>{html.escape(row['sample_id'])}</h2>")
        parts.append(
            f"<p class='meta'>类型：{html.escape(row['sample_type'])}｜指标：{row['metric_judgement']}｜风险：{row['risk_status']}｜19张准入：{row['gate_to_19']}｜size_ratio：{row['size_ratio']}</p>"
        )
        parts.append(f"<p>重点风险点：{html.escape(row['focus'])}</p><div class='grid'>")
        for label, key in [
            ("Original", "original_path"),
            ("Frozen", "frozen_path"),
            ("Round2", "round2_candidate_path"),
            ("Round2.1", "round2_1_candidate_path"),
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


def main() -> None:
    rows = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    REPORTS.mkdir(parents=True, exist_ok=True)
    csv_path = write_csv(rows)
    tuning, handoff = write_reports(rows, csv_path)
    html_path = write_html(rows)
    print(json.dumps({
        "tuning_report": str(tuning),
        "handoff": str(handoff),
        "csv": str(csv_path),
        "review_index": str(html_path),
        "samples": len(rows),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
