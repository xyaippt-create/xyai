# V0.4.6 RC1 优化计划

生成时间：2026-06-26  
结论：RC1 可继续工程回归；不建议本轮直接改算法、改 API、冻结或提交。

## 1. V0.4.6 RC1 必修项

### 1.1 前台显示层

状态：已完成。

- 保持 `resolveDeliveryStatus(...)` 为用户显示的唯一状态解释入口。
- 保证低分样本显示为“建议人工复核”。
- 保证 `PASS_WITH_LIMITATION` 不被合并成普通 `PASS`。
- 保证滑杆页角标不对低分样本显示“1080P 高清成品”。

### 1.2 诊断报告解释层

建议 RC1 必修，但不一定新增 API 字段。

最小方案：

```text
后端原始状态 PASS，前台根据低分指标显示为建议人工复核。
```

应出现在：

- 诊断 ZIP README 或 task_summary。
- 前台下载诊断包前的说明。
- RC1 工程报告。

### 1.3 工程回归

继续执行：

- 后端语法检查。
- 前端 build。
- API / SSE / 轮询回归。
- final_output_url 回归。
- 诊断 ZIP 脱敏回归。
- PASS / PASS_WITH_LIMITATION / FAIL 映射回归。

## 2. V0.4.6 RC1 可保留限制

以下问题可作为 RC1 已知限制保留：

- 后端原始 `final_delivery_status=PASS` 与前台解释后 `PASS_WITH_LIMITATION` 并存。
- 10 个 `PASS_WITH_LIMITATION` 样本仍需人工复核。
- `synthetic_gradient_band` 体积 ratio 极高。
- 部分文字、产品、Alpha、渐变、高光、品牌色样本属于保护优先或收益有限。
- Debug 技术区可能显示后端 raw 字段，但普通用户结论区必须显示 resolved status。

## 3. V0.4.7 后端评分优化建议

### 3.1 delivery guard 增加硬门槛

建议在 V0.4.7 评估：

- `text_clarity_score < 60` → 至少 `PASS_WITH_LIMITATION`
- `texture_score < 60` → 至少 `PASS_WITH_LIMITATION`
- `edge_quality_score < 65` → 至少 `PASS_WITH_LIMITATION`

但不建议在当前诊断任务中直接修改，因为一旦改后端 guard，必须重新跑 19 张黄金集和 API/SSE 回归。

### 3.2 拆分交付分

建议新增或内部拆分：

- `raw_delivery_score`
- `risk_adjusted_delivery_score`
- `frontend_resolved_delivery_status`

其中 `raw_delivery_score` 保留算法分值，`risk_adjusted_delivery_score` 用于交付门禁，`frontend_resolved_delivery_status` 用于用户解释。

### 3.3 降低 color_fidelity 对交付通过的掩盖

当前色彩忠实较高会抬升 `delivery_score`。V0.4.7 应避免文字、纹理、边缘低分被 color_fidelity 和 clarity_score 掩盖。

## 4. V0.4.7 / V0.5 画质增强建议

放到后续版本：

- 中文小字真实可读性提升。
- 产品 PNG 体积收益比优化。
- 渐变、白底、浅灰底低频洁净度优化。
- 高光区域细碎振铃与发灰进一步控制。
- 品牌色样本的色彩稳定与体积收益平衡。

## 5. 是否需要新增诊断字段

推荐优先级：

### RC1 推荐：方案 A

不新增字段，只在诊断报告或 README 中解释：

```text
后端原始状态 PASS，前台根据低分指标显示为建议人工复核。
```

优点：

- 不改 API / SSE / URL 字段。
- 兼容风险最低。
- 满足 RC1 口径澄清。

### V0.4.7 可考虑：方案 B

新增诊断字段：

- `resolved_delivery_status`
- `resolved_delivery_label`
- `resolved_delivery_reason`

注意：只建议进入诊断 ZIP 或报告字段，不建议直接改 API 合同，除非完成兼容性评估。

### 不推荐单独采用：方案 C

只在下载诊断包前显示解释不足以解决 ZIP 内部被转发后的误解。

## 6. 是否需要重新跑 19 张

当前判断：

- 如果只补诊断报告文案：不需要重新跑 19 张。
- 如果修改后端 delivery guard：必须重新跑 19 张。
- 如果修改前台 `resolveDeliveryStatus(...)`：需要前端三态验证和 build，不一定需要跑 19 张。

## 7. 是否允许继续 RC1 工程回归

允许继续 RC1 工程回归。

前提：

- 不冻结。
- 不提交。
- 不接正式生产链。
- 不把后端 raw PASS 写成用户可交付。

## 8. 是否允许提交

当前不允许提交。

原因：

- 工作区仍有多阶段脏文件。
- 需要完成 RC1 工程回归和提交范围筛选。
- 后端 raw PASS 与前台 resolved status 的诊断口径需先确认。

## 9. 是否允许冻结

不允许冻结。

冻结前必须：

- 完成 RC1 工程回归。
- 完成诊断 ZIP 口径说明。
- 明确是否接受后端 raw PASS 与前台降级并存。
- 完成提交范围筛选。

## 10. 需要修改的文件建议

RC1 最小建议：

- 文案/报告层：补充 raw status 与 resolved status 解释。
- 可能涉及：诊断 ZIP README / task_summary 生成逻辑，具体文件需在用户确认后再查。

暂不建议：

- 大改 `backend/v036_output_core.py`。
- 大改 `engine/algorithms/delivery_guard.py`。
- 新增 API / SSE 字段。
- 重写评分体系。

## 11. 最终建议

当前问题最优处理路径：

1. 保持前台降级策略。
2. 在 RC1 诊断说明中补充“后端原始状态”和“前台解释状态”的关系。
3. 继续 RC1 工程回归。
4. 将 delivery guard 硬门槛和 risk-adjusted score 放入 V0.4.7。
