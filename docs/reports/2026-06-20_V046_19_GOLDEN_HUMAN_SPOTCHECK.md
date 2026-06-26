# V0.4.6 19 张黄金集人工点检整理

生成时间：2026-06-20  
当前结论：`CONDITIONAL_READY_FOR_RC1_CLOSEOUT_PREP / NOT_FROZEN / EVIDENCE_COMPLETE`  
当前 HEAD：`111393be65107b0e7670dd70a62681424a9f09a7`

## 执行边界

- 本轮不改算法。
- 本轮不接正式生产链。
- 本轮不冻结。
- 本轮不提交。
- 本轮只基于现有 19 张黄金集 evidence、metrics、CSV、HTML 做人工点检整理。

## 总体统计

|项目|结果|
|---|---:|
|完成样本|19/19|
|POSITIVE|2|
|MINOR_POSITIVE|4|
|NEUTRAL|13|
|REJECT|0|
|EVIDENCE_INCOMPLETE|0|
|PASS|9|
|PASS_WITH_LIMITATION|10|
|Alpha 失败|0|
|高光兜底触发|0|
|高光兜底误触发|0|

## 是否发现需要升级为 REJECT 的样本

未发现需要从当前结果升级为 `REJECT` 的样本。

依据：

- `REJECT=0`。
- `EVIDENCE_INCOMPLETE=0`。
- Alpha 透明样本为 `PASS_ALPHA_PRESENT`。
- 全不透明 RGBA 样本记录为 `PASS_OPAQUE_ALPHA_DROPPED_TO_RGB`，不属于透明通道损伤。
- Round 2.3 高光兜底在 19 张中未触发，未发现误触发导致 final 切换。
- `PASS_WITH_LIMITATION` 样本均保留在人工复核层，不应降级为普通 `PASS`。

## 10 个 PASS_WITH_LIMITATION 点检

结论：10 个样本均可接受为 `PASS_WITH_LIMITATION`，不建议升级为 `REJECT`；但也不能降级为普通 `PASS`。它们的共同特征是体积收益比、质量门未满、保护策略或安全回退触发，需要在 RC1 前台继续明确显示为“建议人工复核”。

|sample_id|类型|判断|触发原因|size_ratio|点检结论|
|---|---|---|---|---:|---|
|smoke_text_poster_cn_small_legacy|text_poster|NEUTRAL|quality_1080p_gate_not_fully_passed|57.898434|文字质量门未满；可接受为人工复核，不可写成明显提升。|
|smoke_product_png_legacy|product_kv|NEUTRAL|quality_1080p_gate_not_fully_passed|60.583142|产品 PNG 体积高；需复核包装字、Logo 和材质收益。|
|smoke_original_unprocessed_jpg|unknown|NEUTRAL|quality_1080p_gate_not_fully_passed|25.016412|普通 JPG 质量门未满；保护通过但收益有限。|
|core_text_synthetic_microcopy|text_poster|NEUTRAL|quality_1080p_gate_not_fully_passed|12.437971|微小字样本仍需人工看笔画、灰边和字腔。|
|core_product_low_png|product_kv|NEUTRAL|quality_1080p_gate_not_fully_passed|53.300054|低质产品 PNG 体积高；需复核产品文字和边缘。|
|synthetic_alpha_edges|unknown|NEUTRAL|smooth_region_guard|38.085034|Alpha 保留，但透明边缘和平滑区需人工复核。|
|synthetic_gradient_band|unknown|NEUTRAL|quality_1080p_gate_not_fully_passed|274.06971|体积 ratio 极高；必须重点复核渐变、色带和低频脏块。|
|synthetic_fine_line_table|text_poster|NEUTRAL|quality_1080p_gate_not_fully_passed|9.327887|细线表格需检查双边、断线、线宽变粗。|
|synthetic_highlight_clip|product_kv|NEUTRAL|very_large_size_limited_benefit|18.809853|高光样本需检查发灰、脏边和振铃。|
|synthetic_brand_color_bars|unknown|NEUTRAL|very_large_size_limited_benefit|14.513893|品牌色条需复核色彩稳定，不能按分数判明显提升。|

## 文字 / 小字 / 数字 / 细线样本

结论：文字相关样本未发现需要升级 `REJECT` 的证据。多数仍处于保护优先或人工复核状态，不能宣传为明显提升。

重点点检口径：

- 中文小字和细线图只能按“保护通过 / 建议人工复核”表达，不能按尺寸变大直接判断为明显提升。
- `synthetic_fine_line_table` 保持 `PASS_WITH_LIMITATION`，应重点人工查看细线是否有双边、断线、线宽异常。
- `smoke_text_poster_cn_small_legacy` 与 `core_text_synthetic_microcopy` 仍属于文字质量门未完全通过，不可升级为普通 PASS。

## 产品 KV / Logo / 包装字 / 品牌色 / 高光

点检结论：未发现需要升级 `REJECT` 的样本；产品类高体积样本仍需人工复核。

重点样本：

- `smoke_product_png_legacy`：`PASS_WITH_LIMITATION`，体积 ratio 高，需复核包装字、边缘和材质收益是否支撑体积。
- `core_product_low_png`：`PASS_WITH_LIMITATION`，低质产品样本有保护性回退，需复核 Logo/包装字是否无损。
- `synthetic_highlight_clip`：`PASS_WITH_LIMITATION`，高光样本因体积收益比进入人工复核，需查看高光是否发灰或脏边。
- `synthetic_brand_color_bars`：`PASS_WITH_LIMITATION`，品牌色条必须人工复核色彩稳定，不能只按增强分数判明显提升。

## Alpha / 透明 PNG

结论：Alpha 失败为 0。

|sample_id|状态|说明|
|---|---|---|
|synthetic_alpha_edges|PASS_ALPHA_PRESENT|透明 Alpha 保留，但进入 `PASS_WITH_LIMITATION`，需人工看透明边缘是否有白边、黑边或脏边。|
|smoke_transparent_png_legacy|PASS_ALPHA_PRESENT|透明样本为 `POSITIVE`，Alpha 保留。|
|core_unknown_opaque_rgba|PASS_OPAQUE_ALPHA_DROPPED_TO_RGB|源图 RGBA 但 Alpha 全 255，不是真透明；输出为 RGB 不视为透明损伤。|

## 渐变、白底、浅灰底、低频平滑区域

重点样本：

- `synthetic_gradient_band`：体积 ratio 最高，`274.06971`，仍为 `PASS_WITH_LIMITATION`。当前不升级 `REJECT`，但必须作为 RC1 重点人工复核样本，判断是否存在色带、低频块、灰雾、体积收益不成立。
- `synthetic_highlight_clip`：高光区域需复核是否发灰、边缘脏、振铃。
- 白底/浅灰底文字图：应确认底色不变脏，不出现灰边、黑边、重影。

## 体积 ratio 高风险样本

|sample_id|交付状态|判断|size_ratio|visible_benefit|点检意见|
|---|---|---|---:|---:|---|
|synthetic_gradient_band|PASS_WITH_LIMITATION|NEUTRAL|274.06971|8.396162|极高体积比，必须人工复核收益是否成立。|
|smoke_product_png_legacy|PASS_WITH_LIMITATION|NEUTRAL|60.583142|3.262285|体积高，产品细节收益需人工确认。|
|smoke_text_poster_cn_small_legacy|PASS_WITH_LIMITATION|NEUTRAL|57.898434|3.379053|文字图不能因放大判明显提升。|
|core_product_low_png|PASS_WITH_LIMITATION|NEUTRAL|53.300054|3.951699|低质产品图需复核文字和边缘。|
|synthetic_alpha_edges|PASS_WITH_LIMITATION|NEUTRAL|38.085034|1.109685|透明边缘和平滑区需复核。|
|smoke_original_unprocessed_jpg|PASS_WITH_LIMITATION|NEUTRAL|25.016412|2.247222|普通 JPG 质量门未满，保留复核。|
|synthetic_highlight_clip|PASS_WITH_LIMITATION|NEUTRAL|18.809853|0.564397|高光收益弱，体积需复核。|
|smoke_transparent_png_legacy|PASS|POSITIVE|17.902131|3.056531|透明 PNG 当前为正向，但仍需看 Alpha 边缘。|

## 人工复核优先级

1. 第一优先级：`synthetic_gradient_band`、`smoke_product_png_legacy`、`smoke_text_poster_cn_small_legacy`、`core_product_low_png`。
2. 第二优先级：`synthetic_alpha_edges`、`smoke_original_unprocessed_jpg`、`synthetic_highlight_clip`、`synthetic_brand_color_bars`。
3. 第三优先级：其余 `NEUTRAL` 保护样本，确认无文字、Logo、颜色和低频副作用。

## 点检材料路径

- 回归 HTML：`tests/results/v046_19_golden_regression/review_index_chatgpt.html`
- 回归 manifest：`tests/results/v046_19_golden_regression/manifest.json`
- 样本 CSV：`docs/reports/2026-06-20_V046_19_GOLDEN_SAMPLE_TABLE.csv`

## 点检结论

- 是否发现需要升级为 REJECT 的样本：否。
- 10 个 PASS_WITH_LIMITATION 是否都能接受：可以接受为“建议人工复核”，不可降级为普通 PASS。
- 是否允许进入 RC1 工程收口准备：允许进入准备清单阶段。
- 是否允许提交：暂不允许，需先完成 RC1 工程回归与提交范围筛选。
- 是否允许冻结：不允许。
- 是否允许接正式生产链：不允许，本轮仍为离线验证与收口准备。
