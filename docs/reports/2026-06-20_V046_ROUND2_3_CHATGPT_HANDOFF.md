# V0.4.6 Round 2.3 ChatGPT Handoff

## 当前状态

WAIT_FOR_HUMAN_VISUAL_REVIEW / NOT_READY_FOR_19 / EVIDENCE_COMPLETE

本轮目标是验证 Round 2.3 高光碎片防发灰兜底是否安全。请只判断视觉证据，不判断工程是否能跑。

## 必看文件

- HTML：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_3_highlight_fallback\review_index_chatgpt.html`
- CSV：`D:\Codex\04_Visual-Master-Pro\docs\reports\2026-06-20_V046_ROUND2_3_SAMPLE_TABLE.csv`
- 证据目录：`D:\Codex\04_Visual-Master-Pro\tests\results\v046_quality_lift_round2_3_highlight_fallback`

## 触发规则

只有同时满足以下四项时触发兜底：

```text
halo_risk == true
ringing_risk == true
face_or_person_detected == true
highlight_neutrality < 0.05
```

本轮触发样本：andy_lau_commercial_portrait

## 需要重点判断的问题

1. `andy_lau_commercial_portrait`：Round 2.3 final 回退到 main/frozen 后，金色高光碎片边缘是否不再发灰、不再振铃。
2. Andy 的脸、手、肤色是否稳定。
3. Andy 放弃 Round 2.2 candidate 后，是否可以接受“安全优先、轻微收益回退”。
4. `green_c_product_kv` 和 `purple_beauty_product_kv` 是否没有被误触发，Logo、包装字、品牌色、透明材质是否稳定。
5. 其余非触发样本是否保持 Round 2.2 的原有判断方向，尤其是产品 KV、DJI 信息图和两张人物/角色样本。

## 样本表

| sample_id | fallback | final_source | smooth_fallback | quality_drop | R2.3 size | retained | review |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `wechat_longscreenshot_2026-06-12_111900_080` | NO | round2_2_candidate | NO |  | 1.089038 | NO | YES |
| `green_c_product_kv` | NO | round2_2_candidate | NO |  | 1.037101 | YES | YES |
| `purple_beauty_product_kv` | NO | round2_2_candidate | NO |  | 1.045954 | YES | YES |
| `dji_horizontal_infographic` | NO | round2_2_candidate | NO |  | 1.091383 | YES | YES |
| `liu_qiangdong_commercial_portrait` | NO | round2_2_candidate | NO |  | 1.107944 | YES | YES |
| `wei_zhongxian_character_card` | NO | round2_2_candidate | NO |  | 1.097847 | YES | YES |
| `andy_lau_commercial_portrait` | YES | main_output_proxy_frozen | YES | -0.15 | 1.0 | NO | YES |

## 当前建议

不建议直接进入 19 张。建议先完成 Andy 高光碎片人工复核；如果确认 Round 2.3 final 的高光风险消失且安全回退可接受，再进入 19 张黄金集。

