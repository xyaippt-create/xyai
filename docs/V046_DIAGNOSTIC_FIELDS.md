# V0.4.6 诊断字段说明

生成日期：2026-06-18

## 1. Phase 6 体积与收益字段

```text
phase6_delivery_guard_active
phase6_visible_benefit_score
phase6_size_growth_ratio
phase6_benefit_size_ratio
phase6_encoding_profile
phase6_size_fallback_triggered
phase6_size_fallback_reason
phase6_safe_optimized_available
phase6_candidate_quality_drop
```

用途：

- 判断输出体积增长是否与可见收益匹配；
- 标记体积异常但仍可人工复核的样本；
- 不直接替代现有 `quality_1080p_pass`。

## 2. Phase 6 平滑区域字段

```text
phase6_gradient_risk
phase6_band_risk
phase6_highlight_pollution_risk
phase6_flat_region_uniformity
phase6_smooth_region_fallback
phase6_smooth_region_fallback_reason
```

用途：

- 检查渐变、天空、墙面、高光和平滑背景；
- 标记色带、高光污染和低频平滑风险；
- 风险触发时交付状态降级为 `PASS_WITH_LIMITATION`。

## 3. 最终交付字段

```text
final_delivery_status
final_delivery_reason
final_delivery_risk_level
final_delivery_recommended_usage
```

状态说明：

- `PASS`：可用于 1080P 屏幕、PPT 或 Web 交付；
- `PASS_WITH_LIMITATION`：存在历史质量门、体积、平滑区域或其他复核风险；
- `FAIL`：不得交付。

## 4. 输出路径字段

```text
output_directory
output_directory_source
final_output_path
final_output_filename
final_output_url
```

约束：

- 前端预览继续使用 URL；
- 不使用本地盘符作为前端图片预览地址；
- 本地路径只作为任务详情、诊断和后续定位使用。

## 5. 反馈 ZIP 字段

```text
feedback_bundle_status
feedback_bundle_path
feedback_bundle_size
feedback_bundle_redacted
feedback_bundle_error
```

ZIP V1 文件：

```text
manifest.json
task_summary.json
diagnostics.json
pipeline_trace.json
quality_metrics.json
system_info.json
error_summary.txt
README.txt
```

约束：

- 不写入用户原图；
- 不写入最终输出图；
- 默认脱敏本地路径和敏感字段。
