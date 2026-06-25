# V0.4.6 RC1 提交范围计划

生成时间：2026-06-26  
任务：RC1 工程回归后的提交范围筛选  
结论：提交范围可控，但当前仍不直接提交

## 1. 当前变更分类

| 文件 / 路径 | 分类 | 建议 |
|---|---|---|
| `backend/v036_output_core.py` | Round 2.3 高光兜底相关生产代码 | 候选提交，需最终 diff 复核 |
| `engine/diagnostics/feedback_bundle.py` | 诊断 ZIP 说明补丁 | 候选提交 |
| `src/deliveryStatus.js` | RC1 前台交付状态统一解析 | 候选提交 |
| `src/QualityReportPage.jsx` | RC1 质量报告页状态与布局修正 | 候选提交 |
| `src/ImageSliderComparePage.jsx` | 高清滑杆对比页状态角标修正 | 候选提交 |
| `src/TaskDetailPage.jsx` | 任务详情页状态映射修正 | 候选提交 |
| `src/DashboardPage.jsx` | Dashboard 状态映射、Debug 技术说明、RC1 UI 必要修正 | 候选提交 |
| `src/index.css` | RC1 前台布局与滚动槽稳定性 | 候选提交，需确认仅为前台样式 |
| `docs/reports/2026-06-20_V046_RC1_DIAGNOSTIC_EXPLANATION_PATCH.md` | 本轮报告 | 候选提交 |
| `docs/reports/2026-06-20_V046_RC1_ENGINEERING_REGRESSION_REPORT.md` | 本轮报告 | 候选提交 |
| `docs/reports/2026-06-20_V046_RC1_COMMIT_SCOPE_PLAN.md` | 本轮报告 | 候选提交 |
| `docs/reports/2026-06-20_V046_RC1_FINAL_CHATGPT_HANDOFF.md` | 本轮交接报告 | 候选提交 |

## 2. 本轮明确不提交

| 文件 / 路径 | 原因 |
|---|---|
| `.gitignore` | 既有无关脏文件，本轮不纳入 |
| `docs/09_CODEX_CHANGELOG.md` | 旧变更混杂，需单独确认后再纳入 |
| `tests/diagnostics/v0453_api_pipeline_results.json` | 回归输出产物，不纳入代码提交 |
| `tests/diagnostics/v046_pipeline_entry_results.json` | 回归输出产物，不纳入代码提交 |
| `tests/diagnostics/output/` | 测试输出图片与中间文件，不纳入 |
| `tests/results/` | 大量图片证据与输出，不纳入 |
| `tests/fixtures/` | 用户素材 / 测试输入原图，不纳入 |
| `tests/golden_v046/` | T02 黄金集资产与历史未跟踪内容，不纳入 |
| `tests/tools/` | 历史画质回归工具，除非另行确认，不纳入 |
| `docs/sync/*QUALITY_LIFT*` | 历史同步包与输出包，本轮不纳入 |
| 其他 Round 2 / Phase 报告 | 非本轮提交范围，除非单独收口 |

## 3. 提交前必须复核

提交前需要执行：

1. `git diff -- backend/v036_output_core.py`，确认仅包含 Round 2.3 高光兜底意图；
2. `git diff -- engine/diagnostics/feedback_bundle.py`，确认仅包含诊断说明；
3. `git diff -- src/deliveryStatus.js src/QualityReportPage.jsx src/ImageSliderComparePage.jsx src/TaskDetailPage.jsx src/DashboardPage.jsx src/index.css`，确认仅包含 RC1 前台必要修改；
4. 排除 `.gitignore`、测试输出、用户原图、fixtures、`tests/results`、旧诊断 JSON；
5. 再执行一次前端 build 和后端语法检查。

## 4. 建议提交拆分

建议拆为两个提交，而不是一个大提交：

```text
fix: align V0.4.6 RC1 delivery status presentation
```

包含：

- `src/deliveryStatus.js`
- `src/QualityReportPage.jsx`
- `src/ImageSliderComparePage.jsx`
- `src/TaskDetailPage.jsx`
- `src/DashboardPage.jsx`
- `src/index.css`

```text
fix: clarify diagnostic delivery status explanation
```

包含：

- `engine/diagnostics/feedback_bundle.py`
- 本轮 RC1 诊断与工程回归报告

Round 2.3 高光兜底如需提交，应单独提交：

```text
fix: guard highlight fragment fallback for V0.4.6 RC1
```

包含：

- `backend/v036_output_core.py`

## 5. 当前结论

当前允许继续进入提交前最终 diff 复核，但本轮不创建 commit，不冻结，不接正式生产链。
