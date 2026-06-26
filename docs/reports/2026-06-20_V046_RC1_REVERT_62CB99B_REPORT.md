# V0.4.6 RC1 Revert 62cb99b Report

日期：2026-06-26

## 结论

PASS

已按用户授权执行：

```text
git revert --no-edit 62cb99b9e510d28a50eadac8b2f0a181aaeca550
```

生成 revert commit：

```text
3c6eda5f26002639ceeef35834cd1ad952c4d393
Revert "Add V0.4.6 golden test set"
```

## Revert 原因

`62cb99b` 经复核不适合作为 V0.4.6 RC1 冻结 HEAD。

该提交包含：

- `.gitignore`
- `docs/09_CODEX_CHANGELOG.md`
- 多份历史 Round 2 / Phase / RC 报告
- `docs/sync/*QUALITY_LIFT*` 同步包与 ZIP
- `tests/diagnostics/*results.json`
- `tests/fixtures/` 中真实测试素材
- `tests/golden_v046/` 黄金集图片与 manifest
- `tests/tools/` 临时测试工具
- `tests/run_golden_v046.py`

这些内容不属于 RC1 三段拆分提交的最小冻结范围。

## Revert 后 Git 链

```text
3c6eda5 Revert "Add V0.4.6 golden test set"
62cb99b Add V0.4.6 golden test set
575653b fix: clarify diagnostic delivery status explanation
1420f68 fix: align V0.4.6 RC1 delivery status presentation
d9945fa fix: guard highlight fragment fallback for V0.4.6 RC1
111393b docs: sync V0.4.6 frontend backend baseline
1f10900 fix: harden RC1 dashboard overflow boundaries
010acac fix: stabilize RC1 dashboard flex layout
```

## 三段 RC1 提交是否保留

```text
d9945fa：保留
1420f68：保留
575653b：保留
```

## Smoke Results JSON 清理

执行 revert 前已恢复：

```text
tests/diagnostics/v0453_api_pipeline_results.json
tests/diagnostics/v046_pipeline_entry_results.json
```

执行最终 smoke 后再次恢复：

```text
tests/diagnostics/v0453_api_pipeline_results.json
```

`tests/diagnostics/v046_pipeline_entry_results.json` 已随 `62cb99b` revert 从当前 HEAD 移除。

## 当前工作区

生产代码无未提交修改。

当前仅保留报告类未跟踪文件：

```text
docs/reports/2026-06-20_V046_RC1_FINAL_SMOKE_REPORT.md
docs/reports/2026-06-20_V046_RC1_HEAD_62CB99B_AUDIT.md
docs/reports/2026-06-20_V046_RC1_REVERT_62CB99B_REPORT.md
docs/reports/2026-06-20_V046_RC1_FINAL_SMOKE_AFTER_REVERT_REPORT.md
docs/reports/2026-06-20_V046_RC1_FREEZE_DECISION_HANDOFF.md
```

## 禁止事项确认

```text
未冻结
未推送
未接正式生产链
未进入 V0.4.7
未重跑 19 张黄金集
未提交用户原图
未提交 tests/results
未提交 fixtures 真实素材
```

