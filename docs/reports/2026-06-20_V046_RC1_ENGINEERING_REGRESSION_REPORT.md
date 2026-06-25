# V0.4.6 RC1 工程回归报告

生成时间：2026-06-26  
任务：诊断说明补丁后的 RC1 工程回归  
结论：PASS

## 1. 回归范围

本轮回归验证：

1. 后端语法；
2. 前端生产 build；
3. JPG / PNG / 透明 PNG / 中文小字 API 上传；
4. 无 SSE 轮询完成；
5. SSE 成功、失败、重连、双订阅；
6. `final_output_url`；
7. 文件落盘；
8. 诊断 ZIP；
9. 路径索引；
10. PASS / PASS_WITH_LIMITATION / FAIL 前台状态映射。

## 2. 命令结果

| 项目 | 命令 / 验证 | 结果 |
|---|---|---|
| 后端语法 | `python -m py_compile main.py backend\v036_output_core.py engine\diagnostics\feedback_bundle.py engine\algorithms\delivery_guard.py` | PASS |
| 前端 build | `npm.cmd run build` | PASS |
| API / SSE 回归 | `tests\diagnostics\test_v0453_api_pipeline.py` | PASS |
| pipeline 正式入口 | `tests\diagnostics\test_v046_pipeline_entry.py` | PASS |
| 诊断 ZIP | TestClient 调用 `/api/v1/tasks/{task_id}/feedback-bundle` | PASS |
| 前台状态映射 | Node 直接验证 `resolveDeliveryStatus(...)` | PASS |

## 3. API 上传与任务链

| 样本 | 上传 | 轮询 | SSE | 重连 | 双订阅 | final_output_url | 文件存在 |
|---|---|---|---|---|---|---|---|
| JPG | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 普通 PNG | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 透明 PNG | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 中文小字图 | PASS | PASS | PASS | PASS | PASS | PASS | PASS |

失败任务 SSE：

```text
PASS
```

## 4. final_output_url

验证结果：

- `final_output_url` 使用网络挂载路径；
- 未暴露 `C:\` 或 `D:\` 本地盘符作为前台图片 URL；
- URL 请求返回 200；
- 对应物理文件真实存在。

结论：PASS。

## 5. 文件落盘与路径索引

验证结果：

- `output_dir` 按请求目录落盘；
- final 文件存在；
- API 任务结果包含物理输出路径和输出文件名；
- `pipeline_trace.json` 记录 `final_output_url`；
- `system_info.json` 记录平台信息；
- 文件存在性和文件大小可由任务结果与物理文件验证。

结论：PASS。

说明：当前路径索引仍分布在任务结果、`pipeline_trace.json`、`system_info.json` 和物理文件检查中，尚未形成单独 `path_index.json`。这不阻断 RC1，但建议 V0.4.7 统一为正式诊断索引字段。

## 6. 诊断 ZIP

生成并验证：

```text
D:\影界文件\诊断反馈\影界诊断_V046_task_20260626_074957_d2a98365_20260626_075001.zip
```

| 项目 | 结果 |
|---|---|
| 必要文件完整 | PASS |
| 不包含原图 | PASS |
| 不包含最终输出 | PASS |
| 脱敏字段 | PASS |
| README raw/resolved 说明 | PASS |
| task_summary raw/resolved 说明 | PASS |

## 7. 交付状态映射

验证样例：

| 输入 | 前台 resolved 状态 | 显示文案 | 角标 |
|---|---|---|---|
| `PASS` + 高分 | `PASS` | 可交付 | 1080P 高清成品 |
| `PASS_WITH_LIMITATION` | `PASS_WITH_LIMITATION` | 建议人工复核 | 1080P 本地预览 |
| raw `PASS` + `text_clarity_score < 60` | `PASS_WITH_LIMITATION` | 建议人工复核 | 1080P 本地预览 |
| raw `PASS` + `texture_score < 60` | `PASS_WITH_LIMITATION` | 建议人工复核 | 1080P 本地预览 |
| raw `PASS` + `edge_quality_score < 65` | `PASS_WITH_LIMITATION` | 建议人工复核 | 1080P 本地预览 |
| `FAIL` | `FAIL` | 不建议交付 | 不建议交付 |
| `REJECT` | `FAIL` | 不建议交付 | 不建议交付 |

页面覆盖：

- 质量报告页：PASS；
- 高清滑杆对比页：PASS；
- 任务详情页：PASS；
- Dashboard 队列表格：PASS；
- Dashboard 交付质检看板：PASS；
- Dashboard 计数器：PASS；
- Debug Runtime Monitor 技术说明：PASS。

## 8. 结论

RC1 工程回归通过。当前允许继续进入 RC1 提交范围筛选，但不建议冻结，也不建议接入新的正式生产链变更。
