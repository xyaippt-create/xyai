# V0.4.6 Round 2.3 高光碎片防发灰兜底定向验证

## 结论

结论：WAIT_FOR_HUMAN_VISUAL_REVIEW / NOT_READY_FOR_19 / EVIDENCE_COMPLETE

本轮只做 7 张决策样本的高光碎片兜底安全验证。未提交、未冻结、未运行 19 张黄金集、未接入新链路、未扩展 UI。

## 验证边界

- 是否修改正式生产代码：本轮验证阶段未继续修改算法；当前待验证改动仍是 `backend/v036_output_core.py` 与 `src/QualityReportPage.jsx`。
- 是否接正式新链路：否。
- 是否进入 19 张黄金集：否。
- 是否冻结：否。
- 证据包：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_3_highlight_fallback`
- HTML：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_3_highlight_fallback\review_index_chatgpt.html`
- CSV：`D:\Codex\04_Visual-Master-Pro\docs\reports\2026-06-20_V046_ROUND2_3_SAMPLE_TABLE.csv`

## 四条件触发核对

Round 2.3 高光碎片兜底只在以下条件同时成立时触发：

```text
halo_risk == true
ringing_risk == true
face_or_person_detected == true
highlight_neutrality < 0.05
```

| sample_id | halo | ringing | person | highlight_neutrality | fallback |
| --- | --- | --- | --- | --- | --- |
| `wechat_longscreenshot_2026-06-12_111900_080` | False | False | False | 0.118 | NO |
| `green_c_product_kv` | False | False | False | 0.072 | NO |
| `purple_beauty_product_kv` | False | False | False | 0.064 | NO |
| `dji_horizontal_infographic` | False | False | False | 0.101 | NO |
| `liu_qiangdong_commercial_portrait` | False | False | True | 0.083 | NO |
| `wei_zhongxian_character_card` | False | False | True | 0.076 | NO |
| `andy_lau_commercial_portrait` | True | True | True | 0.032 | YES |

## 样本结果

| sample_id | fallback | final_source | smooth_fallback | quality_drop | R2.3 size | retained | review |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `wechat_longscreenshot_2026-06-12_111900_080` | NO | round2_2_candidate | NO |  | 1.089038 | NO | YES |
| `green_c_product_kv` | NO | round2_2_candidate | NO |  | 1.037101 | YES | YES |
| `purple_beauty_product_kv` | NO | round2_2_candidate | NO |  | 1.045954 | YES | YES |
| `dji_horizontal_infographic` | NO | round2_2_candidate | NO |  | 1.091383 | YES | YES |
| `liu_qiangdong_commercial_portrait` | NO | round2_2_candidate | NO |  | 1.107944 | YES | YES |
| `wei_zhongxian_character_card` | NO | round2_2_candidate | NO |  | 1.097847 | YES | YES |
| `andy_lau_commercial_portrait` | YES | main_output_proxy_frozen | YES | -0.15 | 1.0 | NO | YES |

## 关键判断

- 高光兜底触发数量：1
- 误触发数量：0
- Round 2.2 MINOR_POSITIVE 保留数量：5
- 证据不完整数量：0
- 仍需人工复核数量：7

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
- 是否保留 Round 2.2 MINOR_POSITIVE：5 张保留；wechat 原本为人工复核；Andy 因安全兜底不保留。
- 是否建议进入 19 张：暂不建议。建议先由 ChatGPT/人工确认 Andy 兜底后是否接受“安全优先、收益回退”的策略。
- 是否建议提交：暂不建议，先完成 ChatGPT 复核。

## 输出文件

- `D:\Codex\04_Visual-Master-Pro\docs\reports\2026-06-20_V046_ROUND2_3_HIGHLIGHT_FALLBACK_REPORT.md`
- `D:\Codex\04_Visual-Master-Pro\docs\reports\2026-06-20_V046_ROUND2_3_SAMPLE_TABLE.csv`
- `D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_3_highlight_fallback\review_index_chatgpt.html`
- `D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_3_highlight_fallback\manifest.json`

请把 `docs/reports/2026-06-20_V046_ROUND2_3_CHATGPT_HANDOFF.md` 发给 ChatGPT 分析。
