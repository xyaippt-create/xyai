# V0.4.6 RC1 前台交付状态映射审计

生成时间：2026-06-26  
结论：普通用户可见页面已统一走 `resolveDeliveryStatus(...)`；Debug 技术区仍可能显示后端原始字段，应标记为技术详情。

## 1. 前台统一解析规则

文件：`src/deliveryStatus.js`

统一规则：

|输入|用户显示|角标|
|---|---|---|
|`PASS` 且无低分/限制原因|可交付|1080P 高清成品|
|`PASS_WITH_LIMITATION`|建议人工复核|1080P 本地预览|
|后端 `PASS` 但低分|建议人工复核|1080P 本地预览|
|`FAIL / REJECT`|不建议交付|不建议交付|

低分触发：

- `text_clarity_score < 60`
- `texture_score < 60`
- `edge_quality_score < 65`

限制原因触发：

- `PASS_WITH_LIMITATION`
- `manual_review`
- `quality_1080p_gate_not_fully_passed`
- `smooth_region_guard`
- `very_large_size_limited_benefit`
- `limited_benefit`
- `size_guard`
- `quality_gate_not_fully_passed`

## 2. 页面接入审计

|页面 / 组件|文件|是否使用 `resolveDeliveryStatus(...)`|审计结论|
|---|---|---|---|
|质量报告页|`src/QualityReportPage.jsx`|是|右侧“最终交付”使用解释后状态。|
|高清滑杆对比页|`src/ImageSliderComparePage.jsx`|是|右侧字段绑定和图上角标使用解释后状态。|
|任务详情页|`src/TaskDetailPage.jsx`|是|顶部状态胶囊使用解释后状态。|
|Dashboard 队列表格|`src/DashboardPage.jsx`|是|`DeliveryPill` 使用解释后状态。|
|Dashboard 交付质检看板|`src/DashboardPage.jsx`|是|活动样本状态使用解释后状态。|
|Dashboard 计数器|`src/DashboardPage.jsx`|是|建议复核/不建议交付数量按解释后状态统计。|
|Debug Runtime Monitor|`src/DashboardPage.jsx`|否，显示原始 JSON|这是技术详情区，不应作为用户交付结论；建议后续加注“原始后端字段”。|

## 3. 三态样本验证

使用 `resolveDeliveryStatus(...)` 构造验证：

|样本|输入|输出|
|---|---|---|
|PASS + 高分|`PASS`，text/texture/edge 均高|`PASS / 可交付 / 1080P 高清成品`|
|PASS_WITH_LIMITATION|后端直接返回 `PASS_WITH_LIMITATION`|`PASS_WITH_LIMITATION / 建议人工复核 / 1080P 本地预览`|
|后端 PASS 但低分|`PASS` + text=36.0579 + texture=37.0789 + edge=57.0191|`PASS_WITH_LIMITATION / 建议人工复核 / 1080P 本地预览`|
|FAIL|`FAIL`|`FAIL / 不建议交付 / 不建议交付`|
|REJECT|`REJECT`|`FAIL / 不建议交付 / 不建议交付`|

验证结论：PASS。

## 4. 诊断 ZIP 样本前台显示结果

用户提供的 ZIP 样本：

```text
final_delivery_status=PASS
final_delivery_reason=delivery_guard_pass
text_clarity_score=36.0579
texture_score=37.0789
edge_quality_score=57.0191
```

前台解释后结果：

```text
status = PASS_WITH_LIMITATION
label = 建议人工复核
badge = 1080P 本地预览
```

因此质量报告页、高清滑杆对比页、任务详情页、Dashboard 普通用户区域都不应显示为“可交付”。

## 5. 是否仍有页面绕过统一解析

普通用户可见的交付状态区域：未发现绕过。

需要注意：

- `Dashboard` 的 Debug Runtime Monitor 仍会显示 `final_delivery_status` 原始字段，这是技术 JSON 详情。
- 该区域建议后续增加 `resolved_delivery_status` 或文字说明，避免用户把 raw PASS 当作最终交付结论。

## 6. UI 口径一致性

当前一致：

- `PASS`：可交付。
- `PASS_WITH_LIMITATION`：建议人工复核。
- 低分降级：建议人工复核。
- `FAIL / REJECT`：不建议交付。

当前不一致风险：

- 诊断 ZIP 和 Debug JSON 仍偏后端 raw 字段。
- 报告和诊断包需要解释 raw status 与 resolved status 的关系。

## 7. 构建验证

最近一次验证：

```text
npm.cmd run build：PASS
```

## 8. 审计结论

前台 `resolveDeliveryStatus(...)` 已足够作为 V0.4.6 RC1 显示层兜底。当前不建议在前台继续扩展复杂状态体系；更大的状态一致性应放到诊断说明或后端 V0.4.7 评分体系优化中解决。
