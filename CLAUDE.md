# 影界 HDDE｜Claude 项目指令

本仓库的长期工程规则以 `AGENTS.md` 为准，Claude 必须完整遵守：

@AGENTS.md

## Claude 适配说明

1. 本项目开发执行者已由 Codex 改为 Claude。`AGENTS.md` 与 HDDE Skill 中凡写“Codex”的执行者职责、限制与报告义务，均由 Claude 承担，规则本身不变。
2. HDDE 单阶段开发 Skill 位于 `.claude/skills/hdde/`（复制自 `.agents/skills/hdde/`，内容一致）。`AGENTS.md` 中“显式调用 `$hdde`”在 Claude 中对应调用 `hdde` Skill（`/hdde`）。两处副本如有修改，需同步。
3. 产品路线、任务拆解与验收标准可在 Claude 对话中完成；用户仍是产品负责人和最终画质裁判。
4. 当前版本、分支、HEAD、阶段状态和下一任务一律从真实仓库与 `docs/` 当前报告读取，不得根据本文件、根目录旧文档（README、项目说明、项目路线图，均停留在 V0.3）或聊天记录推断。
5. 每次修改后照常追加 `docs/09_CODEX_CHANGELOG.md`（沿用原文件名）。
