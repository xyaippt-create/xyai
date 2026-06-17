# V0.4.6 Phase 2 Golden Regression

日期：2026-06-17

## 1. Git 基线

- 用户视觉测试结论：PASS
- Phase 2 Round 2 算法基线：`7e727e0c08106929d3715cf08701ed1156b3f2fc`
- 执行前 HEAD：`7e727e0c08106929d3715cf08701ed1156b3f2fc`
- 当前分支：`main`
- 本轮未修改算法、未进入 Phase 3、未修改 UI、未优化安装包体积。
- 本轮不纳入既有脏文件：`.gitignore`、`docs/09_CODEX_CHANGELOG.md`、`tests/diagnostics/v0453_api_pipeline_results.json`、`tests/golden_v046/` 与 T02 未跟踪文件。

## 2. 19 张执行结果

Round 2 输出目录：

`tests/results/v046_phase2_round2_golden_regression/`

| sample_id | image_type | strength | skip_reason | before | after | clarity_delta | text_delta | edge_delta | detail_delta | size_delta | time_ms |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| smoke_text_poster_cn_small_legacy | text_poster | 0.0 | text_safe_or_text_poster | false | false | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 | 2464.85 |
| smoke_product_png_legacy | product_kv | 0.13 | eligible | false | false | 0.3659 | 0.1160 | 0.1264 | 0.0863 | 2457 | 7760.38 |
| smoke_transparent_png_legacy | product_kv | 0.0585 | alpha_safe_reduced | true | true | 0.3620 | -0.3665 | 0.2176 | 0.0809 | 5813 | 9146.59 |
| smoke_portrait_ready | unknown | 0.1 | eligible | true | true | 0.1501 | 0.3740 | 0.1569 | -0.0605 | 117 | 6592.88 |
| smoke_architecture_low | unknown | 0.1 | eligible | true | true | -0.0424 | 0.0175 | 0.0334 | 0.0492 | -63 | 8546.86 |
| smoke_landscape_ultrawide | unknown | 0.1 | eligible | true | true | 0.0478 | -0.0081 | 0.0108 | 0.0137 | -1705 | 7887.68 |
| smoke_original_unprocessed_jpg | product_kv | 0.025 | very_low_texture_conservative | false | false | 0.7168 | -0.2391 | 0.4740 | 0.0663 | 3250 | 6081.99 |
| core_text_case_original_png | text_poster | 0.0 | text_safe_or_text_poster | true | true | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 | 4549.23 |
| core_text_synthetic_microcopy | unknown | 0.0 | text_safe_or_text_poster | false | false | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 | 5528.10 |
| core_product_low_png | product_kv | 0.13 | eligible | false | false | 0.3724 | 0.2453 | 0.1670 | 0.0936 | 787 | 7145.49 |
| core_architecture_wide_scene | text_poster | 0.0 | text_safe_or_text_poster | true | true | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 | 6674.27 |
| core_landscape_sixteen_scene | text_poster | 0.0 | text_safe_or_text_poster | true | true | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 | 7861.34 |
| core_unknown_origin_photo | text_poster | 0.0 | text_safe_or_text_poster | true | true | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 | 7999.92 |
| core_unknown_opaque_rgba | product_kv | 0.13 | eligible | true | true | 0.3640 | -0.3663 | 0.2195 | 0.0811 | 5192 | 9411.51 |
| synthetic_alpha_edges | text_poster | 0.0 | text_safe_or_text_poster | true | true | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 | 6509.17 |
| synthetic_gradient_band | product_kv | 0.0 | synthetic_gradient_risk | false | false | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 | 8098.80 |
| synthetic_fine_line_table | architecture | 0.0 | text_safe_or_text_poster | false | false | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 | 5239.54 |
| synthetic_highlight_clip | text_poster | 0.0 | text_safe_or_text_poster | true | true | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 | 6361.96 |
| synthetic_brand_color_bars | product_kv | 0.13 | eligible | true | true | 0.0446 | 0.0425 | 0.2094 | 0.0815 | 324 | 8101.16 |

汇总：

- 19/19 completed。
- Phase 1 质量门：12 true / 7 false。
- Phase 2 Round 2 质量门：12 true / 7 false。
- Phase 2 材质增强启用：9 张。
- Phase 2 材质增强跳过或保护：10 张。

## 3. 正收益样本

以下样本在材质增强启用后，清晰、边缘、细节三个方向均为正向：

- `smoke_product_png_legacy`
- `smoke_transparent_png_legacy`
- `smoke_landscape_ultrawide`
- `smoke_original_unprocessed_jpg`
- `core_product_low_png`
- `core_unknown_opaque_rgba`
- `synthetic_brand_color_bars`

另外：

- `smoke_portrait_ready` 清晰、文字、边缘均提升，细节稳定性轻微下降 `-0.0605`，风险字段仍为 low。
- `smoke_architecture_low` 清晰轻微下降 `-0.0424`，边缘与细节为正向，体积下降 63 bytes，风险字段为 low。

## 4. 中性样本

以下保护样本保持完全不变或近似不变：

- `smoke_text_poster_cn_small_legacy`
- `core_text_case_original_png`
- `core_text_synthetic_microcopy`
- `core_architecture_wide_scene`
- `core_landscape_sixteen_scene`
- `core_unknown_origin_photo`
- `synthetic_alpha_edges`
- `synthetic_gradient_band`
- `synthetic_fine_line_table`
- `synthetic_highlight_clip`

## 5. 负收益或风险样本

未发现新增严重负收益。

观察项：

- `smoke_transparent_png_legacy` 与 `core_unknown_opaque_rgba` 的 `text_delta` 约为 `-0.366`，但这两张不是 text_safe 样本，质量门仍为 true，边缘和细节均为正向。
- `smoke_architecture_low` 的 `clarity_delta=-0.0424`，幅度小，边缘和细节为正向，质量门保持 true。
- `smoke_portrait_ready` 的 `detail_delta=-0.0605`，幅度小，清晰、文字、边缘为正向，风险字段保持 low。
- `core_text_synthetic_microcopy` 与 `synthetic_fine_line_table` 的 high 风险字段来自既有 Phase 1 输出，Round 2 对它们保持 0 变化，没有新增退化。

## 6. 文字与 Alpha 保护结果

文字、小字、Logo、细线类样本：

- 中文小字图 `smoke_text_poster_cn_small_legacy`：`phase2_material_strength=0`，输出指标完全不变。
- 中文微小字 `core_text_synthetic_microcopy`：`phase2_material_strength=0`，输出指标完全不变。
- 细线表格 `synthetic_fine_line_table`：`phase2_material_strength=0`，输出指标完全不变。
- 合成渐变 `synthetic_gradient_band`：`synthetic_gradient_risk`，输出指标完全不变。

透明通道：

- `smoke_transparent_png_legacy`：输出为 RGBA，Alpha 保留。
- `synthetic_alpha_edges`：输出为 RGBA，Alpha 保留。
- `core_unknown_opaque_rgba`：输入为 RGBA 但无真实透明，按普通不透明图处理，输出 RGB，符合当前 alpha 策略。

## 7. API/SSE 回归结果

`tests/diagnostics/test_v0453_api_pipeline.py`：PASS。

覆盖结果：

- JPG：upload / poll / SSE / reconnect / double subscribe / final_output_url 全部 PASS。
- 普通 PNG：upload / poll / SSE / reconnect / double subscribe / final_output_url 全部 PASS。
- 透明 PNG：upload / poll / SSE / reconnect / double subscribe / final_output_url 全部 PASS。
- 中文小字图：upload / poll / SSE / reconnect / double subscribe / final_output_url 全部 PASS。
- 失败任务 SSE：PASS。

## 8. 文件体积问题

文件体积扩张仍是已知问题，不属于本轮 Phase 2 材质门控新增问题。

本轮 19 张中，13 张仍报告文件体积扩张警告：

- `smoke_text_poster_cn_small_legacy`
- `smoke_product_png_legacy`
- `smoke_transparent_png_legacy`
- `smoke_original_unprocessed_jpg`
- `core_text_case_original_png`
- `core_text_synthetic_microcopy`
- `core_product_low_png`
- `core_unknown_opaque_rgba`
- `synthetic_alpha_edges`
- `synthetic_gradient_band`
- `synthetic_fine_line_table`
- `synthetic_highlight_clip`
- `synthetic_brand_color_bars`

质量门 false 仍为 7 张，与 Phase 1 基线数量一致，没有新增失败。

## 9. Phase 2 是否允许冻结

结论：`PASS_WITH_KNOWN_ISSUES`

冻结判断：

- 19/19 完成：通过。
- 核心链路全部 PASS：通过。
- 中文与透明 PNG 无退化：通过。
- 材质目标多数为正收益：通过。
- 保护样本保持不变或近似不变：通过。
- 没有新增严重负收益：通过。
- 仍存在历史文件体积扩张与 7 张质量门 false：保留为 known issues。

允许冻结：

`V0.4.6 Phase 2 mid-frequency enhancement frozen`

## 10. 下一阶段建议

- 可以将 Phase 2 标记为冻结。
- 下一步可进入 Phase 3 的任务定义与验收标准准备，但本轮不进入 Phase 3。
- 文件体积扩张和历史质量门 false 建议作为独立后续任务处理，不在 Phase 2 Round 2 中继续调参。
