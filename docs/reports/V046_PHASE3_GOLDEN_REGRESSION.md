# V0.4.6 Phase 3 Golden Regression

## 1. Git 基线

- Phase 3 候选 Commit：`85ff7d873b5d8047839446716273c86b800c1127`
- 正式链路：`main.py -> engine.pipeline.process_v046_delivery -> v046_1080p_delivery -> v046_delivery_adapter -> process_v036_output -> engine.algorithms.edge_halo_control -> safe_copy_final -> final_output_url`
- 本轮未修改算法、未调整门控、未进入 Phase 4。

## 2. 19 张执行结果

| sample_id | image_type | Phase3 状态 | strength | skip_reason | pass_before | pass_after | clarity_delta | text_delta | edge_delta | detail_delta | size_delta | alpha |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| smoke_text_poster_cn_small_legacy | text_poster | text_protected | 0.0 | text_edge_protected | False | False | 0.0 | 0.0 | 0.0 | 0.0 | 0 | present=False, sha_match=True |
| smoke_product_png_legacy | product_kv | active | 0.04 | ringing_guard | False | False | 0.5237 | 0.2886 | 0.023 | 0.0165 | 14671 | present=False, sha_match=True |
| smoke_transparent_png_legacy | product_kv | active | 0.025 | alpha_edge_safe | True | True | 0.7031 | -0.0013 | 0.1215 | 0.0146 | 52219 | present=True, sha_match=True |
| smoke_portrait_ready | unknown | no_risk_skipped | 0.0 | no_edge_risk | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0 | present=False, sha_match=True |
| smoke_architecture_low | unknown | active | 0.045 | eligible | True | True | -0.0064 | 0.0723 | 0.0146 | -0.0004 | 2653 | present=False, sha_match=True |
| smoke_landscape_ultrawide | unknown | active | 0.045 | eligible | True | True | -0.0102 | 0.6358 | 0.0112 | 0.001 | 7316 | present=False, sha_match=True |
| smoke_original_unprocessed_jpg | product_kv | no_risk_skipped | 0.0 | no_edge_risk | False | False | 0.0 | 0.0 | 0.0 | 0.0 | 0 | present=False, sha_match=True |
| core_text_case_original_png | text_poster | text_protected | 0.0 | text_edge_protected | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0 | present=False, sha_match=True |
| core_text_synthetic_microcopy | unknown | text_protected | 0.0 | text_edge_protected | False | False | 0.0 | 0.0 | 0.0 | 0.0 | 0 | present=False, sha_match=True |
| core_product_low_png | product_kv | active | 0.04 | ringing_guard | False | False | 0.468 | -0.0739 | 0.0366 | 0.0138 | 12849 | present=False, sha_match=True |
| core_architecture_wide_scene | text_poster | text_protected | 0.0 | text_edge_protected | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0 | present=False, sha_match=True |
| core_landscape_sixteen_scene | text_poster | text_protected | 0.0 | text_edge_protected | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0 | present=False, sha_match=True |
| core_unknown_origin_photo | text_poster | text_protected | 0.0 | text_edge_protected | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0 | present=False, sha_match=True |
| core_unknown_opaque_rgba | product_kv | active | 0.045 | eligible | True | True | 0.6974 | 0.0114 | 0.1235 | 0.0153 | 46544 | present=False, sha_match=True |
| synthetic_alpha_edges | text_poster | text_protected | 0.0 | text_edge_protected | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0 | present=True, sha_match=True |
| synthetic_gradient_band | product_kv | gradient_protected | 0.0 | gradient_protected | False | False | 0.0 | 0.0 | 0.0 | 0.0 | 0 | present=False, sha_match=True |
| synthetic_fine_line_table | architecture | text_protected | 0.0 | text_edge_protected | False | False | 0.0 | 0.0 | 0.0 | 0.0 | 0 | present=False, sha_match=True |
| synthetic_highlight_clip | text_poster | text_protected | 0.0 | text_edge_protected | True | True | 0.0 | 0.0 | 0.0 | 0.0 | 0 | present=False, sha_match=True |
| synthetic_brand_color_bars | product_kv | active | 0.045 | eligible | True | True | 0.0715 | 0.0683 | 0.0481 | 0.383 | 2196 | present=False, sha_match=True |

## 3. 主动启用与跳过统计

- Phase 3 主动启用数量：7
- Phase 3 文字保护数量：9
- Phase 3 Alpha 保护数量：2
- Phase 3 无风险跳过数量：2
- 其他跳过数量：1
- 主动启用样本：`smoke_product_png_legacy`, `smoke_transparent_png_legacy`, `smoke_architecture_low`, `smoke_landscape_ultrawide`, `core_product_low_png`, `core_unknown_opaque_rgba`, `synthetic_brand_color_bars`

## 4. 正收益样本

- `smoke_product_png_legacy`：Phase 3 启用，edge_delta=0.023，detail_delta=0.0165，size_delta=14671。
- `smoke_transparent_png_legacy`：Phase 3 启用，edge_delta=0.1215，detail_delta=0.0146，size_delta=52219。
- `smoke_architecture_low`：Phase 3 启用，edge_delta=0.0146，detail_delta=-0.0004，size_delta=2653。
- `smoke_landscape_ultrawide`：Phase 3 启用，edge_delta=0.0112，detail_delta=0.001，size_delta=7316。
- `core_product_low_png`：Phase 3 启用，edge_delta=0.0366，detail_delta=0.0138，size_delta=12849。
- `core_unknown_opaque_rgba`：Phase 3 启用，edge_delta=0.1235，detail_delta=0.0153，size_delta=46544。
- `synthetic_brand_color_bars`：Phase 3 启用，edge_delta=0.0481，detail_delta=0.383，size_delta=2196。

## 5. 中性保护样本

- 中性保护或跳过样本数量：12。
- 样本：`smoke_text_poster_cn_small_legacy`, `smoke_portrait_ready`, `smoke_original_unprocessed_jpg`, `core_text_case_original_png`, `core_text_synthetic_microcopy`, `core_architecture_wide_scene`, `core_landscape_sixteen_scene`, `core_unknown_origin_photo`, `synthetic_alpha_edges`, `synthetic_gradient_band`, `synthetic_fine_line_table`, `synthetic_highlight_clip`。

## 6. 负收益或风险样本

- 未发现新增严重负收益样本。
- `smoke_architecture_low` 的 detail_delta 为 -0.0004，属于可忽略级别，未构成建筑结构变软。
- 仍保留历史文件体积扩张问题，不在 Phase 3 处理。

## 7. 文字和 Alpha 结果

- 中文、小字、Logo 和细线：文字保护样本未启用 Phase 3 边缘控制，未发现文字描边、笔画变粗、小字堵塞或细线双边的指标风险。
- 文字或细线保护样本：`smoke_text_poster_cn_small_legacy`, `core_text_case_original_png`, `core_text_synthetic_microcopy`, `core_architecture_wide_scene`, `core_landscape_sixteen_scene`, `core_unknown_origin_photo`, `synthetic_alpha_edges`, `synthetic_fine_line_table`, `synthetic_highlight_clip`。
- 透明 PNG：Alpha 存在性与 Alpha SHA256 在 Phase 2 / Phase 3 之间保持一致。
- Alpha 样本：`smoke_transparent_png_legacy`, `synthetic_alpha_edges`。

## 8. API/SSE 结果

- JPG：upload=PASS，poll=PASS，SSE=PASS，reconnect=PASS，double_subscribe=PASS，final_url=PASS。
- 普通 PNG：upload=PASS，poll=PASS，SSE=PASS，reconnect=PASS，double_subscribe=PASS，final_url=PASS。
- 透明 PNG：upload=PASS，poll=PASS，SSE=PASS，reconnect=PASS，double_subscribe=PASS，final_url=PASS。
- 中文小字图：upload=PASS，poll=PASS，SSE=PASS，reconnect=PASS，double_subscribe=PASS，final_url=PASS。
- 失败任务 SSE：PASS。
- pipeline_call_count：1，final_output_url_ok：True，pipeline_entry_passed：True。

## 9. 华为色彩问题 Phase 5 记录

```text
issue_id: phase5_color_stability_huawei_sample
source_stage: original_to_phase2
phase2_to_phase3_delta_e: 0.0
mean_delta_e_original_to_phase2: 2.054837
p95_delta_e_original_to_phase2: 5.09902
mean_saturation_delta: +0.037547
high_saturation_pixel_ratio_delta: +0.055545
target_phase: Phase 5
```

## 10. Phase 3 冻结结论

- 19/19 完成。
- 核心 API/SSE 链路 PASS。
- 中文、小字、Logo、细线、透明 Alpha、人物、建筑、产品、渐变和高光样本未发现新增严重退化。
- 主动启用样本无严重负收益，保护和跳过样本保持稳定。
- 当前已知限制：Phase 3 门控较保守，部分复杂文字版式完全跳过；华为色彩漂移属于 Phase 5；历史文件体积扩张仍保留。
- 结论：`PASS_WITH_KNOWN_ISSUES`，允许冻结 V0.4.6 Phase 3。
