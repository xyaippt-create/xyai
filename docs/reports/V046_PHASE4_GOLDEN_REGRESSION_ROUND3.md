# V0.4.6 Phase 4 Golden Regression Round 3

生成时间：2026-06-18

## 1. 结论

结论：PASS_WITH_KNOWN_ISSUES

Round 3 针对 Phase 4 的产品实拍误跳过、低频平滑区域暗块、细节负收益和饱和度漂移进行了最小修正。19 张黄金集全部完成，质量门通过数量保持 12/19，不存在新增严重负收益。

允许冻结 Phase 4。保留已知问题：历史文件体积扩张、部分高质量或复杂版式样本按安全策略跳过、低频平滑区域采取保守回退、华为颜色问题继续归入 Phase 5。

## 2. Git 基线

- Phase 4 Round 2 候选基线：6d1e1e8e75bb9bc3d2489ee22c4c3559e6831014
- Round 3 目标：产品与低频平滑区域定点修复、黄金集回归与冻结

## 3. Round 3 定点修复

| 问题 | 根因 | Round 3 处理 | 结果 |
|---|---|---|---|
| real_product_lowquality 被 synthetic_gradient_protected 跳过 | 实拍产品图低纹理、低边缘、低饱和区域占比高，被合成渐变风险规则覆盖 | 增加 product_photo_eligible，允许实拍产品以低强度进入，同时继续保护文字、Logo 和平滑背景 | 产品样本 active=true，strength=0.0172，skip_reason=product_photo_fidelity_safe |
| core_product_low_png 出现低频暗块 | Phase 4 在平滑区域执行亮度域恢复，缺少低频块状风险回退 | 增加 flat_region_mask、low_frequency_risk 与 fallback | fallback=true，输出与 Phase 3 保持一致，暗块消除 |
| core_product_low_png detail_delta=-6.1406 | 平滑背景被错误增强导致结构指标负向 | 触发低频风险回退 | detail_delta=0.0 |
| core_product_low_png saturation_delta=+0.037893 | 亮度和去污染混合后带来饱和度漂移 | 增加 color_drift_metrics 与色彩漂移回退 | saturation_delta=0.0 |

## 4. 定向样本结果

| sample_id | active | strength | fallback | skip_reason | clarity_delta | text_delta | edge_delta | detail_delta | saturation_delta | p95_delta_e |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| real_product_lowquality | True | 0.0172 | False | product_photo_fidelity_safe | 0.3795 | -0.0765 | 0.5051 | 0.1855 | 0.001207 | 1.414214 |
| core_product_low_png | False | 0.0 | True | eligible | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| synthetic_gradient_band | False | 0.0 | False | synthetic_gradient_protected | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| synthetic_brand_color_bars | False | 0.0 | False | clean_brand_kv_protected | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| real_architecture_lowquality | True | 0.0266 | False | local_text_protected | 0.1437 | 0.0564 | 0.0583 | -0.5583 | 0.001429 | 2.44949 |
| real_stage_activity_02 | False | 0.0 | True | portrait_fidelity_safe | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

定向结论：产品实拍进入保守处理；核心产品 PNG 的低频暗块、细节负收益和饱和度漂移均由回退机制归零；合成渐变和品牌色条保持保护。

## 5. 19 张黄金集统计

- 完成数量：19/19
- 失败数量：0
- Phase 4 主动启用数量：2
- Phase 4 回退数量：2
- 局部文字保护数量：10
- 跳过或保护数量：17
- 质量门通过数量：12 -> 12

主动启用样本：smoke_product_png_legacy, smoke_original_unprocessed_jpg

回退样本：core_product_low_png, core_unknown_opaque_rgba

## 6. 19 张黄金集明细

| sample_id | active | strength | fallback | skip_reason | quality_before | quality_after | clarity_delta | text_delta | edge_delta | detail_delta | saturation_delta | p95_delta_e |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| smoke_text_poster_cn_small_legacy | False | 0.0 | False | text_or_dense_layout_protected | False | False | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| smoke_product_png_legacy | True | 0.0314 | False | eligible | False | False | 0.0812 | 0.0732 | 0.0654 | 0.2176 | 0.000595 | 1.0 |
| smoke_transparent_png_legacy | False | 0.0 | False | alpha_protected | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| smoke_portrait_ready | False | 0.0 | False | low_contrast_only_conservative | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| smoke_architecture_low | False | 0.0 | False | low_contrast_only_conservative | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| smoke_landscape_ultrawide | False | 0.0 | False | low_contrast_only_conservative | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| smoke_original_unprocessed_jpg | True | 0.0292 | False | eligible | False | False | 0.86 | 1.3447 | 0.7829 | 0.8001 | 0.001402 | 1.0 |
| core_text_case_original_png | False | 0.0 | False | text_or_dense_layout_protected | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| core_text_synthetic_microcopy | False | 0.0 | False | text_or_dense_layout_protected | False | False | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| core_product_low_png | False | 0.0 | True | eligible | False | False | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| core_architecture_wide_scene | False | 0.0 | False | text_or_dense_layout_protected | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| core_landscape_sixteen_scene | False | 0.0 | False | text_or_dense_layout_protected | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| core_unknown_origin_photo | False | 0.0 | False | text_or_dense_layout_protected | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| core_unknown_opaque_rgba | False | 0.0 | True | eligible | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| synthetic_alpha_edges | False | 0.0 | False | text_heavy_non_photo_protected | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| synthetic_gradient_band | False | 0.0 | False | synthetic_gradient_protected | False | False | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| synthetic_fine_line_table | False | 0.0 | False | text_or_dense_layout_protected | False | False | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| synthetic_highlight_clip | False | 0.0 | False | text_or_dense_layout_protected | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| synthetic_brand_color_bars | False | 0.0 | False | clean_brand_kv_protected | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

## 7. 保护结果

- 中文、小字、Logo 和细线：保护样本保持 0 变化或近似不变，无新增文字描边、笔画变粗或细线双边证据。
- 透明 PNG 与 Alpha：透明样本继续 alpha_protected，质量门保持通过，无 Alpha 退化。
- 人物：人物与活动样本在色彩或低频风险超限时回退，未出现磨皮、五官变化、发丝描边或肤色漂移。
- 产品：实拍产品进入低强度保真处理；核心产品 PNG 在低频风险触发时回退，避免暗块、假纹理和饱和度漂移。
- 建筑与平滑区域：建筑覆盖样本保持低强度或保护路径；平滑区域通过 flat_region_mask 与 fallback 防止暗块、色带和水彩块。
- 颜色稳定：黄金集无 p95_delta_e > 3、无 saturation_delta 超限样本；华为历史色彩问题不在 Phase 4 修改，继续记录到 Phase 5。

## 8. API / SSE 回归

| 项目 | 结果 |
|---|---|
| JPG 上传 / 轮询 / SSE / 重连 / 双订阅 / final_output_url | PASS / PASS / PASS / PASS / PASS / PASS |
| 普通 PNG 上传 / 轮询 / SSE / 重连 / 双订阅 / final_output_url | PASS / PASS / PASS / PASS / PASS / PASS |
| 透明 PNG 上传 / 轮询 / SSE / 重连 / 双订阅 / final_output_url | PASS / PASS / PASS / PASS / PASS / PASS |
| 中文小字图上传 / 轮询 / SSE / 重连 / 双订阅 / final_output_url | PASS / PASS / PASS / PASS / PASS / PASS |
| 失败任务 SSE | PASS |
| pipeline_call_count | PASS，正式入口诊断为 1 |

## 9. 文件体积

Round 3 未处理文件体积优化。文件体积扩张属于历史已知问题，未作为 Phase 4 冻结阻断。

## 10. 冻结判断

- 产品与建筑覆盖测试：通过，产品图不再因合成渐变保护误跳过，建筑和产品无新增严重退化。
- 19/19 黄金集：完成。
- 中文、小字、Logo、细线：无退化证据。
- Alpha：无退化证据。
- 人物：无磨皮、描边或身份变化证据。
- 产品：无虚构材质；核心产品 PNG 低频暗块已被回退机制阻断。
- 建筑与低频平滑区域：无新增双边、白边、色带或低频污染证据。
- API/SSE：通过。

Phase 4 冻结结论：允许冻结。

下一阶段建议：可以进入 Phase 5 色彩稳定。
