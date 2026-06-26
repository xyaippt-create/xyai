# V0.4.6 RC1前 19 张黄金集离线回归

## 结论

结论：WAIT_FOR_HUMAN_VISUAL_REVIEW / NOT_FROZEN / EVIDENCE_COMPLETE

本轮已运行 19 张黄金集离线回归。未提交、未冻结、未接新链路、未扩 UI、未进入 2K/4K。

## Git 与运行边界

- HEAD：`111393be65107b0e7670dd70a62681424a9f09a7`
- 是否修改正式生产代码：本轮回归未继续修改算法；工作区仍包含此前 Round 2.3 待验证改动。
- 是否接入正式生产链：否，离线调用本地核心到测试目录。
- 是否运行 19 张：是。
- 是否冻结：否。
- 证据目录：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_19_golden_regression`
- HTML：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_19_golden_regression\review_index_chatgpt.html`
- CSV：`D:\Codex\04_Visual-Master-Pro\docs\reports\2026-06-20_V046_19_GOLDEN_SAMPLE_TABLE.csv`

## 总体统计

- 完成：19/19
- POSITIVE：2
- MINOR_POSITIVE：4
- NEUTRAL：13
- REJECT：0
- EVIDENCE_INCOMPLETE：0
- PASS_WITH_LIMITATION：10
- Alpha 失败：0
- 高光兜底触发：0
- 高光兜底误触发：0（按 `highlight_shard_smooth_guard` 计）

## 样本表

| sample_id | type | judge | delivery | fallback | size | evidence | alpha |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `smoke_text_poster_cn_small_legacy` | text_poster | NEUTRAL | PASS_WITH_LIMITATION | NO | 57.898434 | PASS | NOT_APPLICABLE |
| `smoke_product_png_legacy` | product_kv | NEUTRAL | PASS_WITH_LIMITATION | NO | 60.583142 | PASS | NOT_APPLICABLE |
| `smoke_transparent_png_legacy` | unknown | POSITIVE | PASS | NO | 17.902131 | PASS | PASS_ALPHA_PRESENT |
| `smoke_portrait_ready` | portrait | MINOR_POSITIVE | PASS | NO | 1.361948 | PASS | NOT_APPLICABLE |
| `smoke_architecture_low` | architecture | NEUTRAL | PASS | NO | 3.519949 | PASS | NOT_APPLICABLE |
| `smoke_landscape_ultrawide` | landscape | NEUTRAL | PASS | NO | 3.624008 | PASS | NOT_APPLICABLE |
| `smoke_original_unprocessed_jpg` | unknown | NEUTRAL | PASS_WITH_LIMITATION | NO | 25.016412 | PASS | NOT_APPLICABLE |
| `core_text_case_original_png` | text_poster | NEUTRAL | PASS | NO | 14.482376 | PASS | NOT_APPLICABLE |
| `core_text_synthetic_microcopy` | text_poster | NEUTRAL | PASS_WITH_LIMITATION | NO | 12.437971 | PASS | NOT_APPLICABLE |
| `core_product_low_png` | product_kv | NEUTRAL | PASS_WITH_LIMITATION | NO | 53.300054 | PASS | NOT_APPLICABLE |
| `core_architecture_wide_scene` | architecture | MINOR_POSITIVE | PASS | NO | 4.343081 | PASS | NOT_APPLICABLE |
| `core_landscape_sixteen_scene` | landscape | MINOR_POSITIVE | PASS | NO | 5.449293 | PASS | NOT_APPLICABLE |
| `core_unknown_origin_photo` | unknown | MINOR_POSITIVE | PASS | NO | 6.594818 | PASS | NOT_APPLICABLE |
| `core_unknown_opaque_rgba` | unknown | POSITIVE | PASS | NO | 16.710249 | PASS | PASS_OPAQUE_ALPHA_DROPPED_TO_RGB |
| `synthetic_alpha_edges` | unknown | NEUTRAL | PASS_WITH_LIMITATION | NO | 38.085034 | PASS | PASS_ALPHA_PRESENT |
| `synthetic_gradient_band` | unknown | NEUTRAL | PASS_WITH_LIMITATION | NO | 274.06971 | PASS | NOT_APPLICABLE |
| `synthetic_fine_line_table` | text_poster | NEUTRAL | PASS_WITH_LIMITATION | NO | 9.327887 | PASS | NOT_APPLICABLE |
| `synthetic_highlight_clip` | product_kv | NEUTRAL | PASS_WITH_LIMITATION | NO | 18.809853 | PASS | NOT_APPLICABLE |
| `synthetic_brand_color_bars` | unknown | NEUTRAL | PASS_WITH_LIMITATION | NO | 14.513893 | PASS | NOT_APPLICABLE |

## 高光兜底

无

## 风险结论

- 文字、小字、Logo、细线：未出现自动 REJECT；文字/信息图样本仍需人工复核。
- 人脸、手部、肤色：未出现自动 REJECT；人物类样本仍需人工复核裁切。
- 品牌色、白底、渐变、低频平滑区：未出现颜色阈值 REJECT；合成/高光样本以 NEUTRAL 或人工复核处理。
- 文件体积收益比：历史 PASS_WITH_LIMITATION 仍保留，不写成已解决。
- 是否建议进入 RC1 工程收口：可以进入 ChatGPT/人工复核；不建议直接冻结。
- 是否建议提交：暂不建议，先完成 ChatGPT 对本报告和 HTML 的视觉复核。

## 输出

- `D:\Codex\04_Visual-Master-Pro\docs\reports\2026-06-20_V046_19_GOLDEN_REGRESSION_REPORT.md`
- `D:\Codex\04_Visual-Master-Pro\docs\reports\2026-06-20_V046_19_GOLDEN_SAMPLE_TABLE.csv`
- `D:\Codex\04_Visual-Master-Pro\tests\results\v046_19_golden_regression\review_index_chatgpt.html`
- `D:\Codex\04_Visual-Master-Pro\tests\results\v046_19_golden_regression\manifest.json`

请把 `docs/reports/2026-06-20_V046_19_GOLDEN_CHATGPT_HANDOFF.md` 发给 ChatGPT 分析。
