# V0.4.6 RC1 冻结前最终 Smoke 报告

生成时间：2026-06-26  
任务：V0.4.6 RC1 冻结前最终 smoke  
结论：PASS

## 1. Git 基线

用户指令中记录的 HEAD：

```text
575653bd3bbba9286dce7dc656ba82e476d25e31
```

实际仓库 HEAD：

```text
62cb99b9e510d28a50eadac8b2f0a181aaeca550
```

实际最近提交：

```text
62cb99b Add V0.4.6 golden test set
575653b fix: clarify diagnostic delivery status explanation
1420f68 fix: align V0.4.6 RC1 delivery status presentation
d9945fa fix: guard highlight fragment fallback for V0.4.6 RC1
111393b docs: sync V0.4.6 frontend backend baseline
```

说明：本轮没有回退或重写历史。三段 RC1 拆分提交已包含在当前实际 HEAD 的父链中，本 smoke 基于实际 HEAD `62cb99b` 执行。

## 2. 验证结果总表

| 项目 | 结果 |
|---|---|
| 后端语法检查 | PASS |
| 前端 `npm.cmd run build` | PASS |
| 最小 API smoke | PASS |
| 任务轮询 smoke | PASS |
| SSE smoke | PASS |
| `final_output_url` smoke | PASS |
| 文件落盘 smoke | PASS |
| 诊断 ZIP smoke | PASS |
| 前台交付状态 smoke | PASS |
| 页面 smoke | PASS |
| 当前 HEAD 稳定性 | PASS |
| 是否新增应提交代码 | 否 |

## 3. 后端语法检查

命令：

```text
.venv\Scripts\python.exe -m py_compile main.py backend\v036_output_core.py engine\diagnostics\feedback_bundle.py engine\algorithms\delivery_guard.py
```

结果：

```text
PASS
```

## 4. 前端 Build

命令：

```text
npm.cmd run build
```

结果：

```text
PASS
```

Vite build 成功，产物生成到 `dist/`。

## 5. 最小 API / 任务 / SSE Smoke

脚本：

```text
tests\diagnostics\test_v0453_api_pipeline.py
```

覆盖样本：

```text
JPG
普通PNG
透明PNG
中文小字图
```

结果：

| 项目 | 结果 |
|---|---|
| JPG 上传 | PASS |
| 普通 PNG 上传 | PASS |
| 透明 PNG 上传 | PASS |
| 中文小字图上传 | PASS |
| 任务轮询 | PASS |
| 成功 SSE | PASS |
| 失败 SSE | PASS |
| SSE 重连 | PASS |
| SSE 双订阅 | PASS |
| `final_output_url` | PASS |

## 6. Pipeline 正式入口 Smoke

脚本：

```text
tests\diagnostics\test_v046_pipeline_entry.py
```

结果：

| 项目 | 结果 |
|---|---|
| API status | PASS |
| 任务完成 | PASS |
| `pipeline_call_count=1` | PASS |
| `final_output_url` 可访问 | PASS |
| SSE `[DONE]` | PASS |

## 7. final_output_url Smoke

验证结果：

- URL 返回 200：PASS；
- URL 未暴露 `C:\` 或 `D:\` 本地盘符：PASS；
- URL 指向真实最终文件：PASS；
- 物理 final 文件存在：PASS。

## 8. 文件落盘 Smoke

验证结果：

- `output_dir` 使用请求目录：PASS；
- final 文件存在：PASS；
- 任务结果包含输出文件路径、输出目录、输出文件名：PASS；
- 诊断 ZIP 文件存在：PASS。

## 9. 诊断 ZIP Smoke

生成并验证：

```text
D:\影界文件\诊断反馈\影界诊断_V046_task_20260626_080929_566ae7f5_20260626_080934.zip
```

结果：

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
| 不包含原图 | PASS |
| 不包含最终输出 | PASS |
| `redacted=true` | PASS |
| README 包含 raw status / resolved status 说明 | PASS |
| `task_summary.json` 包含 `delivery_status_explanation` | PASS |

## 10. 前台交付状态 Smoke

验证 `src/deliveryStatus.js`：

| 输入 | 输出 |
|---|---|
| `PASS` + 高分 | `PASS / 可交付 / 1080P 高清成品` |
| `PASS_WITH_LIMITATION` | `PASS_WITH_LIMITATION / 建议人工复核 / 1080P 本地预览` |
| raw `PASS` + 低分 | `PASS_WITH_LIMITATION / 建议人工复核 / 1080P 本地预览` |
| `FAIL` | `FAIL / 不建议交付 / 不建议交付` |
| `REJECT` | `FAIL / 不建议交付 / 不建议交付` |

结果：

```text
PASS
```

## 11. 页面 Smoke

页面覆盖方式：

- 前端生产 build 编译通过；
- 页面源码确认均接入或展示统一状态口径；
- Debug Runtime Monitor 已标注为技术详情。

页面结果：

| 页面 | 结果 |
|---|---|
| Dashboard | PASS |
| 任务详情页 | PASS |
| 高清滑杆对比页 | PASS |
| 质量报告页 | PASS |

## 12. Git 状态

最终 `git status --short`：

```text
 M tests/diagnostics/v0453_api_pipeline_results.json
 M tests/diagnostics/v046_pipeline_entry_results.json
?? docs/reports/2026-06-20_V046_RC1_FINAL_SMOKE_REPORT.md
```

说明：

- 两个 `tests/diagnostics/*results.json` 是本轮 smoke 更新的测试结果产物；
- `docs/reports/2026-06-20_V046_RC1_FINAL_SMOKE_REPORT.md` 是本轮输出报告；
- 本轮未新增生产代码脏文件；
- 未提交用户原图、`tests/results`、fixtures、历史 T02 或大量图片输出。

## 13. 结论

```text
RC1_FINAL_SMOKE_PASS
HEAD_STABLE_FOR_RC1_FREEZE_DECISION
ALLOW_RC1_FREEZE_DECISION
DO_NOT_SWITCH_PRODUCTION_CHAIN
NOT_FROZEN
NO_19_RERUN
```

当前允许进入 RC1 冻结判断；仍禁止接正式生产链，冻结动作需用户或 ChatGPT 明确确认。
