# V0.4.6 RC1 交付状态根因诊断

生成时间：2026-06-26  
任务：交付状态、质量门禁、诊断 ZIP、前台显示链路根因诊断  
结论：多层共同作用，主因在后端 delivery guard 与 RC1 用户显示口径不完全一致；前台降级策略正确。

## 1. 当前问题摘要

最新诊断 ZIP 样本显示：

```text
final_delivery_status = PASS
final_delivery_reason = delivery_guard_pass
clarity_score = 75.3563
text_clarity_score = 36.0579
edge_quality_score = 57.0191
texture_score = 37.0789
color_fidelity_score = 96.0955
delivery_score = 68.854
warning = 压缩优化候选未采用，已使用主输出文件作为最终成品
```

后端原始状态是 `PASS / delivery_guard_pass`，但按 RC1 前台规则，因 `text_clarity_score < 60`、`texture_score < 60`、`edge_quality_score < 65`，面向用户必须显示：

```text
建议人工复核 / 1080P 本地预览
```

不得显示：

```text
可交付 / 1080P 高清成品
```

## 2. 诊断 ZIP 样本复盘

从用户提供的字段看，该 ZIP 的隐私和任务链路是通过的：

- task completed。
- error_summary 为空。
- 原图未包含。
- 最终输出未包含。
- 诊断 ZIP 脱敏边界通过。
- 成品文件选择为 `main_output`，压缩优化候选未采用。

但诊断 ZIP 只呈现后端原始 `final_delivery_status=PASS`，没有同步呈现前台解释后的“建议人工复核”状态，容易造成用户误解。

备注：该精确 ZIP 文件 `影界诊断_V046_task_20260620_112521_93759524_20260620_112550.zip` 未在当前工作区内检索到；本报告基于用户提供的 ZIP 字段和当前代码链路判断。

## 3. 完整状态链路

当前链路应理解为两层状态：

1. 图像处理完成。
2. 生成 `main_output` 与 `optimized_output`。
3. 根据压缩安全、体积、质量稳定性选择 `final_output`。
4. 生成质量指标：clarity、text、edge、texture、color、delivery_score 等。
5. 后端 `phase6_delivery_guard_policy(...)` 生成原始 `final_delivery_status` 和 `final_delivery_reason`。
6. 后端生成 warnings，例如“压缩优化候选未采用”。
7. 诊断 ZIP 打包原始字段、warnings、路径索引和脱敏信息。
8. 前端读取后端字段。
9. 前端 `resolveDeliveryStatus(...)` 根据后端状态、限制原因和低分指标做二次解释。
10. 质量报告页、高清滑杆对比页、任务详情页、Dashboard 显示前台解释后的用户状态。

## 4. 后端原始状态与前台解释状态

|层级|当前样本状态|用途|
|---|---|---|
|后端原始状态|`PASS / delivery_guard_pass`|说明任务完成，后端 delivery guard 未命中当前限制条件。|
|前台解释状态|`PASS_WITH_LIMITATION / 建议人工复核`|RC1 面向用户的最终显示状态。|

存在合法场景：

```text
后端原始 PASS，但前台根据低分指标降级为 PASS_WITH_LIMITATION。
```

这是当前 RC1 的安全兜底策略，不是前台错误。

## 5. 根因分类

当前矛盾对应以下类别：

- A. 后端 delivery guard 阈值过松：成立。
- B. 后端 PASS / PASS_WITH_LIMITATION 定义不清：部分成立。
- C. delivery_score 权重掩盖文字、纹理、边缘低分：成立。
- D. 前台二次解释是正确兜底：成立。
- E. 诊断 ZIP 缺少“前台解释后状态”说明：成立。
- F. 质量指标命名或显示口径有问题：部分成立，主要是 raw score 与用户交付口径未拆开。
- G. 体积 ratio 或样本口径造成误判：不是主因。
- H. 其他：无新增证据。

## 6. 后端 delivery guard 现状

当前 `engine/algorithms/delivery_guard.py` 中 `PASS_WITH_LIMITATION` 主要由以下条件触发：

- `quality_1080p_pass == false` → `quality_1080p_gate_not_fully_passed`
- `phase6_smooth_region_fallback == true` → `smooth_region_guard`
- `size_growth_ratio` 高且 `visible_benefit` 低 → `large_size_low_visible_benefit` 或 `very_large_size_limited_benefit`

当前没有把以下绝对低分作为硬门槛：

- `text_clarity_score < 60`
- `texture_score < 60`
- `edge_quality_score < 65`

因此会出现后端仍给 `PASS`，但前台必须降级的样本。

## 7. delivery_score 风险

当前质量分中：

```text
visual_score =
clarity_score * 0.22
+ text_clarity_score * 0.12/0.22
+ edge_quality_score * 0.22
+ detail_stability_score * 0.16
+ color_fidelity_score * 0.18
```

问题：

- 色彩忠实和清晰度较高时，可能抬高总分。
- text / texture / edge 低分没有形成硬门槛。
- texture_score 本身不是 delivery guard 的硬条件。
- delivery_score 是 raw score，不等于商业可交付状态。

建议后续拆分：

- `raw_delivery_score`
- `risk_adjusted_delivery_score`
- `frontend_resolved_delivery_status`

## 8. 是否需要立即修改

当前不建议在本轮直接大改算法或评分体系。

建议：

|事项|判断|
|---|---|
|是否需要改后端算法|否。|
|是否需要改 API / SSE / final_output_url|否。|
|是否需要改前台状态解析|已完成，当前策略正确。|
|是否需要改诊断 ZIP|RC1 可先补解释文案；新增字段建议放到后续确认。|
|是否需要重跑 19 张|若只补报告文案，不需要；若改后端 delivery guard，需要重跑。|
|是否允许继续 RC1 工程回归|允许。|
|是否允许提交|暂不允许，需先完成工程回归和提交范围筛选。|
|是否允许冻结|不允许。|

## 9. 结论

问题不是前台误判，而是：

```text
后端 raw PASS 仍偏工程完成口径；
前台 resolved status 才是 RC1 面向用户的商业交付口径。
```

当前前台降级策略正确。后端 delivery guard 在 V0.4.7 应增加风险调整和硬门槛，但 V0.4.6 RC1 可以先以“前台解释状态 + 报告说明”兜底。
