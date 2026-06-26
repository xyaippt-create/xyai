# V0.4.6 RC1 Final Smoke After Revert Report

日期：2026-06-26

## 结论

PASS

当前 HEAD：

```text
3c6eda5f26002639ceeef35834cd1ad952c4d393
```

本轮在 revert `62cb99b` 后重新执行 RC1 最终 smoke。未修改算法、API、SSE、`final_output_url`、后端 delivery guard 或前台功能范围。

## Smoke 结果

| 项目 | 结果 | 说明 |
|---|---:|---|
| 后端语法检查 | PASS | `main.py`、`backend/v036_output_core.py`、`engine/diagnostics/feedback_bundle.py`、`engine/algorithms/delivery_guard.py` 编译通过 |
| 前端生产 build | PASS | `npm.cmd run build` 成功 |
| API 上传 | PASS | JPG、普通 PNG、透明 PNG、中文小字样本通过既有 API smoke |
| 任务轮询 | PASS | 无 SSE 也能轮询到 completed |
| SSE 成功任务 | PASS | 成功任务发送 `[DONE]` |
| SSE 失败任务 | PASS | 失败任务发送 `[DONE]` |
| SSE 重连 | PASS | 重连不重复处理任务 |
| 双订阅 | PASS | 双 SSE 订阅不重复处理任务 |
| final_output_url | PASS | 返回 200，不暴露 `C:\` / `D:\`，指向真实最终文件 |
| 文件落盘 | PASS | `output_dir`、final 文件存在 |
| pipeline_call_count | PASS | 自定义 smoke 证实 `pipeline_call_count=1` |
| 诊断 ZIP | PASS | ZIP 生成成功，不含原图和最终输出，`redacted=true` |
| 诊断说明 | PASS | README 与 `task_summary.json` 均包含 raw status / resolved status 解释 |
| 前台三态映射 | PASS | PASS / PASS_WITH_LIMITATION / raw PASS 低分 / FAIL / REJECT 映射正确 |

## pipeline 入口说明

固定脚本 `tests/diagnostics/test_v046_pipeline_entry.py` 依赖已被 revert 的：

```text
tests/golden_v046/smoke/product_png_legacy.png
```

因此该脚本在 revert 后出现样本缺失。为避免重新引入被撤销的黄金集资产，本轮使用仓库中仍存在的旧诊断样本：

```text
runtime/v044_validation/inputs/test_1.png
```

执行同等 pipeline 入口 smoke，结果：

```text
pipeline_call_count=1
task_status=completed
final_output_url_ok=true
final_output_url_exposes_drive=false
SSE done=true
```

## 诊断 ZIP 核验

最新诊断 ZIP：

```text
D:\影界文件\诊断反馈\影界诊断_V046_task_20260626_083439_23d92bb8_20260626_083444.zip
```

核验结果：

```text
manifest.json=true
task_summary.json=true
diagnostics.json=true
quality_metrics.json=true
pipeline_trace.json=true
system_info.json=true
error_summary.txt=true
README.txt=true
contains_original_image=false
contains_final_output=false
redacted=true
README raw/resolved explanation=true
task_summary delivery_status_explanation=true
```

## 前台交付状态 Smoke

| 场景 | 显示结果 |
|---|---|
| PASS + 高分 | 可交付 / 1080P 高清成品 |
| PASS_WITH_LIMITATION | 建议人工复核 / 1080P 本地预览 |
| raw PASS + 低分 | 建议人工复核 / 1080P 本地预览 |
| FAIL | 不建议交付 |
| REJECT | 不建议交付 |

## 当前限制

本轮未重新运行 19 张黄金集。

本轮不冻结、不提交新代码、不接正式生产链。

