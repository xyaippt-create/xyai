# V0.4.6 RC1 诊断说明补丁报告

生成时间：2026-06-26  
任务：诊断 ZIP raw status 与前台 resolved status 解释层补丁  
结论：PASS

## 1. 补丁目标

本轮只补充诊断解释层，不修改图像算法、不修改后端评分体系、不修改 API / SSE / final_output_url。

补丁用于解释：

- `final_delivery_status` 是后端原始交付状态；
- 前台 `resolveDeliveryStatus(...)` 是 RC1 面向用户的最终交付显示口径；
- 允许存在“后端 raw PASS，但前台因低分或限制原因显示为建议人工复核”的合法场景。

## 2. 修改文件

| 文件 | 修改内容 |
|---|---|
| `engine/diagnostics/feedback_bundle.py` | 在诊断 ZIP `README.txt` 与 `task_summary.json` 内加入交付状态解释说明 |
| `src/DashboardPage.jsx` | 在 Debug Runtime Monitor 上方加入“后端原始字段 / 技术详情，不代表用户交付结论”的说明 |

## 3. 诊断 ZIP 解释内容

已加入说明：

```text
final_delivery_status 为后端原始交付状态，用于表示任务处理与后端门禁结果；前台会根据文字清晰度、纹理保持力、边缘质量、限制原因等指标进行二次解释。
若核心指标偏低，即使后端原始状态为 PASS，前台仍会显示为“建议人工复核 / 1080P 本地预览”。请以前台交付状态作为面向用户的最终交付口径。
```

覆盖映射：

| 后端原始状态 | 条件 | 前台显示 |
|---|---|---|
| `PASS` | `text_clarity_score >= 60`、`texture_score >= 60`、`edge_quality_score >= 65` 且无限制原因 | 可交付 / 1080P 高清成品 |
| `PASS_WITH_LIMITATION` | 任意限制原因 | 建议人工复核 / 1080P 本地预览 |
| `PASS` | `text_clarity_score < 60` 或 `texture_score < 60` 或 `edge_quality_score < 65` | 建议人工复核 / 1080P 本地预览 |
| `FAIL / REJECT` | 后端失败或拒绝 | 不建议交付 |

## 4. 验证结果

重新生成诊断 ZIP：

```text
D:\影界文件\诊断反馈\影界诊断_V046_task_20260626_074957_d2a98365_20260626_075001.zip
```

检查结果：

| 项目 | 结果 |
|---|---|
| `manifest.json` | PASS |
| `task_summary.json` | PASS |
| `diagnostics.json` | PASS |
| `quality_metrics.json` | PASS |
| `pipeline_trace.json` | PASS |
| `system_info.json` | PASS |
| `error_summary.txt` | PASS |
| `README.txt` | PASS |
| `contains_original_image=false` | PASS |
| `contains_final_output=false` | PASS |
| `redacted=true` | PASS |
| README 含 raw/resolved 说明 | PASS |
| `task_summary.json` 含 `delivery_status_explanation` | PASS |

## 5. 合同影响

| 项目 | 是否修改 |
|---|---|
| API 字段 | 否 |
| SSE 字段 | 否 |
| `final_output_url` | 否 |
| 图像算法 | 否 |
| delivery guard 判定逻辑 | 否 |
| 诊断 ZIP 内部说明 | 是 |

## 6. 结论

诊断解释层补丁已完成。普通用户页面继续以前台 `resolveDeliveryStatus(...)` 为最终显示口径；Debug Runtime Monitor 与诊断 ZIP 中的 raw 字段已明确标注为技术详情。
