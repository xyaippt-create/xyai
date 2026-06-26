# V0.4.6 RC1 Git Scope Check

生成时间：2026-06-20  
当前 HEAD：`111393be65107b0e7670dd70a62681424a9f09a7`

## 当前结论

当前 git diff 不干净，但范围可拆分；不建议直接整仓提交。必须先区分：

1. Round 2.3 / 19 张回归相关文件；
2. RC1 前台 UI 改动；
3. 既有 T02 / 诊断 / fixture / tests 输出；
4. 不应提交的用户原图和测试结果图片。

## Tracked diff

- `M .gitignore`
- `M backend/v036_output_core.py`
- `M docs/09_CODEX_CHANGELOG.md`
- `M src/DashboardPage.jsx`
- `M src/QualityReportPage.jsx`
- `M src/TaskDetailPage.jsx`
- `M src/index.css`
- `M tests/diagnostics/v0453_api_pipeline_results.json`

## 本轮 19 张回归新增关键文件

- `docs/reports/2026-06-20_V046_19_GOLDEN_REGRESSION_REPORT.md`
- `docs/reports/2026-06-20_V046_19_GOLDEN_CHATGPT_HANDOFF.md`
- `docs/reports/2026-06-20_V046_19_GOLDEN_SAMPLE_TABLE.csv`
- `docs/reports/2026-06-20_V046_19_GOLDEN_HUMAN_SPOTCHECK.md`
- `docs/reports/2026-06-20_V046_RC1_CLOSEOUT_PREP.md`
- `docs/reports/2026-06-20_V046_RC1_GIT_SCOPE_CHECK.md`
- `tests/results/v046_19_golden_regression/`
- `tests/tools/v046_round2_3_19_golden_regression.py`

## 其他未跟踪文件

工作区中还存在较多历史未跟踪文件，包括 Round 2.x 报告、T02 文件、fixtures、tests/results、sync 包等。不能无筛选提交。

## 本轮应保留但暂不提交的文件

- `docs/reports/2026-06-20_V046_19_GOLDEN_HUMAN_SPOTCHECK.md`
- `docs/reports/2026-06-20_V046_RC1_CLOSEOUT_PREP.md`
- `docs/reports/2026-06-20_V046_RC1_GIT_SCOPE_CHECK.md`
- `docs/reports/2026-06-20_V046_19_GOLDEN_REGRESSION_REPORT.md`
- `docs/reports/2026-06-20_V046_19_GOLDEN_CHATGPT_HANDOFF.md`
- `docs/reports/2026-06-20_V046_19_GOLDEN_SAMPLE_TABLE.csv`
- `tests/results/v046_19_golden_regression/`
- `tests/tools/v046_round2_3_19_golden_regression.py`

## RC1 后续可能提交的候选范围

需要用户确认后，才可从以下类别中筛选：

- Round 2.3 高光兜底相关生产代码。
- 前台 RC1 显示和布局改动。
- 必要的离线验证脚本。
- 必要的最终报告。

## 明确不应提交的内容

- 用户原图。
- `tests/results/` 下的大量输出图片，除非用户明确要求归档。
- 历史诊断产物。
- 与本轮无关的 T02 未跟踪文件。
- 未经确认的 `.gitignore`、旧 changelog、旧诊断 JSON 改动。
- 任意包含真实用户素材的 fixture。

## 提交前检查清单

- [ ] `git diff -- backend/v036_output_core.py` 只包含 Round 2.3 高光兜底意图。
- [ ] `git diff -- src` 只包含 RC1 前台显示/布局意图。
- [ ] 不提交 `tests/results` 图片输出。
- [ ] 不提交 `tests/fixtures` 用户素材。
- [ ] 不提交历史 T02 脏文件。
- [ ] 不提交无关 `.gitignore` 和旧诊断变更，除非单独确认。
- [ ] 所有提交前验证通过后再建立独立 commit。

## 当前判断

当前 git diff：不干净，但可控；不能直接提交，必须先做范围筛选。
