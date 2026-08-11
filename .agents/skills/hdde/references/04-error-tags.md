# HDDE｜执行错误标签

## BASELINE_MISS

未正确读取或核对项目目录、分支、HEAD、版本、Git 状态和当前差异。

纠正：
停止修改，重新执行只读预检。

## STAGING_NOT_EMPTY

开始或结束时 staging 非空。

纠正：
不得自行 unstage、reset 或 restore；报告实际状态并等待修正后的任务卡。

## PROTECTED_RESULT_DAMAGE

已有受保护成果被覆盖、删除、回滚、遗漏或重新实现。

纠正：
立即停止；禁止报告通过；如实说明影响。

## SCOPE_EXPANSION

修改进入当前阶段范围外的功能、模块或版本。

纠正：
停止范围外开发；保留问题证据并延后处理。

## ROOT_CAUSE_GUESS

没有代码路径、运行或数据证据就宣布根因。

纠正：
补充最低必要诊断；无法确认时不得大范围修改。

## REIMPLEMENT_EXISTING_RESULT

没有基于当前实现做增量修改，而是重新建立已经完成的功能。

纠正：
读取现有差异和实现，恢复到最小增量路径。

## MULTI_COMMAND_CHAIN

把同一阶段拆成调查、修复、审核、补测试、补证据或多版本指令。

纠正：
在当前一次执行中完成可预见的诊断、实现、验证和报告。

## OVER_VALIDATION

验证、审核和报告投入明显超过真实功能开发需要。

纠正：
删除与验收门禁无直接关系的工作。

## UNDER_VALIDATION

缺少证明结果所需的真实运行或直接相关测试。

纠正：
补充最低必要验证；验证完成前不得通过。

## FALSE_PASS

运行、测试或门禁失败，却报告成功。

纠正：
撤销通过结论，报告真实状态。

## REPORT_EVIDENCE_GAP

最终结论无法对应命令、diff、API、页面、日志、文件或处理结果。

纠正：
补充可复核证据，或降低结论。

## ARCHITECTURE_BLOCK_MISUSE

把普通 Bug、依赖问题、时间不足、调查不完整或测试失败写成架构阻断。

纠正：
继续完成范围内普通工程处理。

## TEMP_FALLBACK_VIOLATION

正式目录失败后静默回退到项目临时目录、测试目录或 runtime_data。

纠正：
移除错误回退，恢复明确失败阻断。

## USER_SETTING_REWRITE

正式目录失败时自动改写用户设置。

纠正：
保持用户设置不变，报告真实未就绪状态。

## MOCK_SUCCESS

使用假数据、假文件、假路径、默认成功状态或不存在能力制造完成假象。

纠正：
移除 Mock 正式结果，使用真实运行和真实文件验证。

## UNAUTHORIZED_GIT_ACTION

未经本阶段明确授权执行暂存、提交、推送、合并、Tag、发布、stash、reset、clean、restore 或切换分支。

纠正：
立即停止并报告实际操作和影响。

## BULK_STAGE_VIOLATION

使用 `git add .`、`git add -A` 或 `git add --all`。

纠正：
禁止继续暂存；只允许在明确授权后逐文件操作。

## DOCUMENT_NOISE

正式档案记录了调试流水、失败尝试、截图堆叠和无价值证据。

纠正：
仅保留最终实现、解决、验证、遗留和基线。
