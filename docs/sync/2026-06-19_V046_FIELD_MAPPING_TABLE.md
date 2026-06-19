# V0.4.6 前后台字段映射表

生成日期：2026-06-19

说明：

- “后端是否产生”基于 `main.py`、`backend/v036_output_core.py`、`engine/algorithms/*`、`engine/diagnostics/feedback_bundle.py` 与冻结文档核对；
- “前端是否读取”基于当前工作区 `src/*.jsx` 核对；
- 普通用户可见指工作台、任务详情、图片对比、质量报告的显性展示；
- 技术详情可见指任务详情、诊断包、质量报告或后续高级诊断入口。

| 字段名 | 后端来源 | 后端是否产生 | 前端读取位置 | 前端显示位置 | 用户可见性 | 当前状态 | 缺口 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `output_directory` | `main.py` / `process_v036_output` | 是 | `DashboardPage.jsx` 间接读取 `task_result.output_dir` | 工作台队列/输出目录状态 | 普通用户可见 | 已接入 | 无 | 用于输出目录说明，不作为图片 `src` |
| `output_directory_source` | `main.py` / output dir meta | 是 | 未显式展示 | 暂无 | 技术详情可见 | 部分接入 | 前台未单独展示 | 可保留在诊断详情 |
| `final_output_path` | `process_v036_output` / `safe_copy_final` | 是 | `DashboardPage.jsx` 间接读取 `task_result.output_path`/`final_output_path` | 复制/定位类动作、诊断 | 技术详情可见 | 部分接入 | 普通视图不应显示盘符 | 不得进入 `<img src>` |
| `final_output_filename` | `process_v036_output` | 是 | `DashboardPage.jsx` | 队列表格“输出文件名” | 普通用户可见 | 已接入 | 无 | 用于文件对应 |
| `final_output_url` | `main.py` public file url | 是 | `DashboardPage.jsx`、`ImageSliderComparePage.jsx` | 工作台动作、图片对比、下载/打开 | 普通用户可见 | 已接入 | 无 | 前台预览和打开应优先使用 URL |
| `preview_output_url` | `main.py` public file url | 是 | `DashboardPage.jsx`、`ImageSliderComparePage.jsx` | 图片对比增强图 | 普通用户可见 | 已接入 | 无 | 图片预览优先字段 |
| `enhancedUrl` | `main.py` 兼容字段 | 是 | `DashboardPage.jsx` / 旧兼容路径 | 兼容旧前台 | 普通用户可见 | 已兼容 | 无 | 不应删除 |
| `downloadUrl` | API 合同保留字段 | 合同要求 | 当前前台未显式读取 | 暂无 | 普通用户可见 | 缺口 | 前端未使用 | 当前可由 `final_output_url` 覆盖下载/打开 |
| `final_delivery_status` | `engine.algorithms.delivery_guard` / `process_v036_output` | 是 | `DashboardPage.jsx`、`TaskDetailPage.jsx`、`ImageSliderComparePage.jsx`、`QualityReportPage.jsx` | 队列、详情、对比、报告 | 普通用户可见 | 已接入 | 无 | `PASS_WITH_LIMITATION` 显示为“建议人工复核” |
| `final_delivery_reason` | `delivery_guard_policy` | 是 | `DashboardPage.jsx`、`TaskDetailPage.jsx`、`ImageSliderComparePage.jsx`、`QualityReportPage.jsx` | 任务详情/质量报告 | 普通用户可见 | 已接入 | 无 | 建议前台继续中文转译原因 |
| `final_delivery_risk_level` | `delivery_guard_policy` | 是 | `DashboardPage.jsx`、`TaskDetailPage.jsx`、`QualityReportPage.jsx` | 任务详情/质量报告 | 技术详情可见 | 已接入 | 无 | 普通第一屏不宜过度突出 |
| `final_delivery_recommended_usage` | `delivery_guard_policy` | 是 | `DashboardPage.jsx`、`TaskDetailPage.jsx`、`QualityReportPage.jsx` | 任务详情/质量报告 | 普通用户可见 | 已接入 | 无 | 建议保持克制描述 |
| `phase5_color_stability_active` | `engine.algorithms.color_stability` | 是 | 当前前台未系统展示 | 暂无 | 技术详情可见 | 缺口 | 未独立展示 | 可放高级诊断，不应占普通第一屏 |
| `phase5_color_drift_detected` | `color_stability` | 是 | `TaskDetailPage.jsx` 当前工作区有提示逻辑 | 任务详情色彩提示 | 普通用户可见，技术字段隐藏 | 部分接入 | 未形成完整技术详情区 | 默认视图不应写“检测到偏色但未修复” |
| `phase5_color_fallback_triggered` | `color_stability` | 是 | `TaskDetailPage.jsx` 当前工作区有提示逻辑 | 任务详情色彩提示 | 技术详情可见 | 部分接入 | 未单独展示 | 可用于解释保护回退 |
| `phase5_color_correction_enabled` | `single_image_color_correction` | 是 | `TaskDetailPage.jsx` 当前工作区有提示逻辑 | 任务详情色彩提示 | 普通用户可见 | 部分接入 | 未统一到 Dashboard | 默认显示“主动色偏修复未开启” |
| `phase5_cast_direction` | `single_image_color_correction` | 是 | 前台未显式读取 | 暂无 | 技术详情可见 | 缺口 | 未展示 | 仅适合高级诊断 |
| `phase5_correction_strength` | `single_image_color_correction` | 是 | 前台未显式读取 | 暂无 | 技术详情可见 | 缺口 | 未展示 | 仅适合高级诊断 |
| `phase5_correction_skip_reason` | `single_image_color_correction` | 是 | `TaskDetailPage.jsx` 当前工作区有提示逻辑 | 任务详情色彩提示 | 技术详情可见 | 部分接入 | 未完整列出 | `disabled_by_user` 普通文案应为“主动色偏修复未开启” |
| `phase6_size_growth_ratio` | `delivery_guard_policy` | 是 | 前台未显式读取 | 证据包/质量报告间接体现 | 技术详情可见 | 部分接入 | 普通前台缺少体积收益比摘要 | 下一阶段建议补充为人工复核原因 |
| `phase6_visible_benefit_score` | `delivery_guard_policy` | 是 | 前台未显式读取 | 证据包/诊断 | 技术详情可见 | 部分接入 | 未在普通 UI 展示 | 不应直接替代人工判断 |
| `phase6_size_fallback_triggered` | `delivery_guard_policy` | 是 | 前台未显式读取 | 诊断/报告 | 技术详情可见 | 缺口 | 未展示 | 可转译为“体积收益比需复核” |
| `phase6_size_fallback_reason` | `delivery_guard_policy` | 是 | 前台未显式读取 | 诊断/报告 | 技术详情可见 | 缺口 | 未展示 | 避免英文原因直接暴露 |
| `phase6_gradient_risk` | `phase6_smooth_region_metrics` | 是 | 前台未显式读取 | 诊断/证据包 | 技术详情可见 | 缺口 | 未展示 | 渐变样本应人工复核 |
| `phase6_band_risk` | `phase6_smooth_region_metrics` | 是 | 前台未显式读取 | 诊断/证据包 | 技术详情可见 | 缺口 | 未展示 | 色带风险字段 |
| `phase6_highlight_pollution_risk` | `phase6_smooth_region_metrics` | 是 | 前台未显式读取 | 诊断/证据包 | 技术详情可见 | 缺口 | 未展示 | 高光污染风险字段 |
| `phase6_smooth_region_fallback` | `phase6_smooth_region_metrics` | 是 | 前台未显式读取 | 诊断/证据包 | 技术详情可见 | 缺口 | 未展示 | 可映射为“平滑区域需复核” |
| `phase6_smooth_region_fallback_reason` | `phase6_smooth_region_metrics` | 是 | 前台未显式读取 | 诊断/证据包 | 技术详情可见 | 缺口 | 未展示 | 不应在普通视图裸露英文 |
| `feedback_bundle_status` | `engine.diagnostics.feedback_bundle` | 是 | `DashboardPage.jsx` | 生成诊断包后的 notice/状态 | 普通用户可见 | 已接入 | 无 | `PASS` 表示诊断包生成成功 |
| `feedback_bundle_path` | `feedback_bundle.py` | 是 | `DashboardPage.jsx` 存入队列项 | 普通视图未直接显示 | 技术详情可见 | 部分接入 | 未提供可视定位 | 默认脱敏，不含图片 |
| `feedback_bundle_size` | `feedback_bundle.py` | 是 | `DashboardPage.jsx` 存入队列项 | 普通视图未直接显示 | 技术详情可见 | 部分接入 | 未展示 | 可用于售后反馈确认 |
| `feedback_bundle_redacted` | `feedback_bundle.py` | 是 | 前台未显式读取 | 暂无 | 技术详情可见 | 缺口 | 未展示 | 诊断包说明应强调默认脱敏 |
| `feedback_bundle_error` | `feedback_bundle.py` | 是 | 前台通过异常 notice 间接显示 | notice | 普通用户可见 | 部分接入 | 未显示具体字段 | 失败时可显示克制错误信息 |

## 交付状态口径核对

| 后端值 | 前台显示 | 是否符合 |
| --- | --- | --- |
| `PASS` | 可交付 | 是 |
| `PASS_WITH_LIMITATION` | 建议人工复核 | 是 |
| `FAIL` | 不建议交付 / 不可交付 | 是 |

## 当前字段缺口摘要

前台普通工作流已接入必要字段：

- 上传；
- 轮询/SSE；
- `preview_output_url` / `final_output_url`；
- 三类交付状态；
- 诊断包生成入口。

当前主要缺口集中在高级诊断层，不阻塞 RC1 基础接入：

- Phase 5 详细色彩字段尚未形成统一折叠区；
- Phase 6 体积收益比、渐变、高光和平滑区域字段尚未完整前台转译；
- `downloadUrl` 合同字段未被前台显式使用；
- 诊断包 `feedback_bundle_redacted`、`feedback_bundle_error` 未形成完整普通视图反馈。

