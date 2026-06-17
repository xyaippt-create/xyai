# V0.4.6 最小架构归位报告

日期：2026-06-18

## 目标

将 V0.4.6 API 正式交付链路归入 `engine.pipeline`，同时保持现有算法、参数、像素输出、诊断字段、API/SSE 行为和 `final_output_url` 不变。

## 归位后正式调用链

```text
main.py
→ /api/upload
→ ensure_task_started
→ run_task_background
→ run_image_pipeline
→ engine.pipeline.process_v046_delivery
→ rules/pipeline_rules.yaml: v046_1080p_delivery
→ engine.adapters.v046_delivery_adapter.run_v046_delivery
→ backend.v036_output_core.process_v036_output
→ safe_copy_final
→ returned final_output_path
→ final_output_url
```

## 修改范围

```text
main.py
engine/pipeline/orchestrator.py
engine/pipeline/__init__.py
engine/adapters/__init__.py
engine/adapters/v046_delivery_adapter.py
rules/pipeline_rules.yaml
tests/v046_architecture_rehome_regression.py
tests/diagnostics/test_v046_pipeline_entry.py
```

未修改 `backend/v036_output_core.py` 中的 Phase 1 / Phase 2 / Phase 3 图像算法。

## 零漂移结果

对归位前 direct 链路与归位后 pipeline 链路运行同一 19 张 ready 黄金样本：

```text
19/19 completed
19/19 file SHA256 match
19/19 decoded pixel SHA256 match
19/19 alpha match
19/19 dimensions / format / size match
19/19 quality gate match
19/19 key diagnostics match
19/19 entered engine.pipeline
```

证据文件：

```text
tests/results/v046_architecture_rehome/before_direct/summary.json
tests/results/v046_architecture_rehome/after_pipeline/summary.json
tests/results/v046_architecture_rehome/comparison_summary.json
```

## API/SSE 回归

`tests/diagnostics/test_v046_pipeline_entry.py` 验证：

```text
/api/upload completed
pipeline_call_count = 1
final_output_url reachable
SSE ended with [DONE]
```

`tests/diagnostics/test_v0453_api_pipeline.py` 验证：

```text
JPG upload PASS
PNG upload PASS
transparent PNG upload PASS
Chinese small text upload PASS
polling PASS
SSE PASS
SSE reconnect PASS
double subscribe PASS
failed SSE PASS
final_output_url PASS
final file exists PASS
```

## 结论

V0.4.6 API 交付链路已归入 `engine.pipeline`。`backend/v036_output_core.py` 当前保留为 V0.4.6 pipeline 内部交付实现，不再作为 API 独立旁路入口。
