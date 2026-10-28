# 影界 HDDE V0.5.7 UI/UX 阶段02剩余问题复核

任务：`V057_UIUX_STAGE02_REMAINING_ISSUE_REAUDIT`  
日期：2026-09-01  
性质：只读当前状态审计  
版本权威源：`product_version.json = 0.5.7-dev / V0.5.7-dev`

## STATUS

```text
STATUS=PASS
AUDIT_STAGE=PASS_AND_FROZEN
V0.5.7_UI_TECHNICAL_CLOSEOUT=NO

ORIGINAL_ISSUES=11
P0=2
P1=6
P2=3

CURRENT_ISSUES=1
P0=0
P1=1
P2=0

RESOLVED_FROM_STAGE01=11（9项已解决，2项因后续产品决策或重新评估失效）
NEW_ISSUES=1
```

本阶段审计已完成并冻结唯一当前问题池；这不表示 V0.5.7 UI 已完成技术收口。当前仍有 1 个真实 P1，需要完成下一批最小修复后才能重新判断 UI 收口。

## AUDIT_BASELINE

- 当前分支：`codex/image-processing-routing-v1`
- 当前 HEAD：`aa0dd93265d270eb5192ebbd44a1fe14488d454a`
- `STAGING_EMPTY=YES`
- 当前工作区已有 168 项未提交差异，其中 85 项 untracked；全部按受保护成果处理，本阶段未清理、回滚、暂存或改写。
- 正式服务：前端 `127.0.0.1:5173`、后端 `127.0.0.1:8787` 均返回 200。
- 正式目录：`D:\影界文件`，`directory_ready=true`。
- 正式输出目录仍为：`1080P画质`、`4K画质增强`、`图片压缩`、`瑕疵修复`、`颜色校正`、`智能交付`。
- 权威历史事实仍为：`FILE_UNAVAILABLE_RESULTS=2`、`FILE_UNAVAILABLE_DELIVERIES=3`、两个已删除 Task 均未恢复。

## ORIGINAL_ISSUE_REAUDIT

| ISSUE_ID | LEVEL | 原始 DESCRIPTION | 原始 EVIDENCE | 原始 CODE_LOCATION | CURRENT_STATUS | 当前依据 |
|---|---|---|---|---|---|---|
| P0-01 | P0 | 4K 已完成任务选择失效预览 URL，仍允许确认交付 | 阶段01真实任务预览 404，规范 Result URL 200，确认按钮仍可用 | `src/App.jsx:59-69`；`src/TaskDetailPage.jsx:218-247,275-278` | RESOLVED_BY_LATER_CHANGE | 当前 4K Task `task_20260901_085018_67c8fb08` 使用规范 `/api/v1/tasks/.../result-file`，浏览器返回 200、3840px 成品真实解码；隔离浏览器将该 GET 模拟为 404 后，页面显示资产失败与恢复提示，确认交付按钮禁用。 |
| P0-02 | P0 | 未知路由空值异常，恢复页无法渲染 | `/unknown-audit-route` 抛出 `route.key` 空值异常并出现空白主区 | `src/App.jsx:314-316,463-469` | RESOLVED_BY_LATER_CHANGE | `App.jsx` 在 route 为空时独立渲染 `UnknownRoutePage`；浏览器显示“页面不存在”、原路径和“返回处理中心”，点击后回到 `/processing`，Console 0 错误。 |
| P1-01 | P1 | 一级导航与阶段01目标六项结构不一致 | 代码与浏览器显示 9 个入口，目标表为 6 项 | `src/AppShell.jsx:15-20`；`src/appRoutes.js` | INVALIDATED | 后续产品决策已冻结当前 9 个真实可达入口；本阶段任务明确禁止无回归证据时重开或重排导航。当前入口名称与能力真实状态一致。 |
| P1-02 | P1 | 历史任务视图仍展示当前任务摘要 | 历史页签下仍显示当前任务、0% 与等待结果摘要 | `src/DashboardPage.jsx:3045-3059,3429-3477` | RESOLVED_BY_LATER_CHANGE | 当前 `showCurrentSummary` 只在 `taskView=current` 时成立；浏览器切换历史任务后摘要区数量为 0，未出现“当前任务”摘要。 |
| P1-03 | P1 | 图片压缩没有完整 Result → Confirm → Delivery 用户链 | 页面内独立结果和复核，确认后缺少明确交付状态 | `src/CompressionPage.jsx:656-756` | RESOLVED_BY_LATER_CHANGE | 当前压缩页具有真实候选、人工复核、确认后交付状态及输出目录门禁；无候选时明确显示“原图已满足要求/未生成新成品”，不开放候选交付入口。专用页面不再构成流程缺失。 |
| P1-04 | P1 | UI 重复定义并重判业务交付状态 | `resolveDeliveryStatus` 根据指标和原因覆盖后端状态 | `src/deliveryStatus.js:38-94` | RESOLVED_BY_LATER_CHANGE | 当前交付结论只读取后端 `final_delivery_status / delivery_status`；指标只生成复核提示，不再覆盖明确业务结论。 |
| P1-05 | P1 | 输入、处理中和错误状态重复实现 | 多页面各自实现上传、进度、错误和操作 | `src/HddeUI.jsx` 及各功能页 | INVALIDATED | 这是架构观察项，不是可复现用户缺陷。现有共享 Shell、页头、结果与技术详情已经形成一致可见骨架；任务禁止为抽象统一而建设新框架。 |
| P1-06 | P1 | 目录状态加载初期误显示不可用 | `workdirInfo=null` 时直接推导 `directoryReady=false` | `src/DashboardPage.jsx:1326-1359,1474-1476,3185-3195` | RESOLVED_BY_LATER_CHANGE | 当前存在 `workdirPending` 中性状态并显示“正在检测正式目录”；浏览器完成读取后显示“正式目录可用”，未观察到错误阻断。 |
| P2-01 | P2 | 成品已保存页固定 760px，未利用 Shell 主区域 | 结果页 1440px、交付完成页 760px | `src/TaskDetailPage.jsx:486-525`；`src/index.css:6863-6873` | RESOLVED_BY_LATER_CHANGE | 当前交付完成头部与内容统一为 `width:min(1120px,100%)`，长文件名使用 `overflow-wrap:anywhere`。 |
| P2-02 | P2 | 用户可见文本存在 46 处 11px | 阶段01静态扫描 `font-size:11px` 共 46 处 | `src/index.css` | RESOLVED_BY_LATER_CHANGE | 当前静态扫描 `font-size: 11px` 命中为 0，最小用户可见文本基线为 12px。 |
| P2-03 | P2 | 处理中心空态重复展示多组零值与等待信息 | 四步流程、空任务表、进度、结果和交付重复空状态 | `src/DashboardPage.jsx:3130-3479` | RESOLVED_BY_LATER_CHANGE | 当前无实际任务时不渲染进度/交付摘要；浏览器当前视图摘要数量为 0，历史视图同样为 0。 |

## TARGETED_UI_REVIEW

```text
P0_4K_PREVIEW_STATUS=RESOLVED_BY_LATER_CHANGE
P0_UNKNOWN_ROUTE_STATUS=RESOLVED_BY_LATER_CHANGE
UI002_SAVED_PAGE_WIDTH=RESOLVED_BY_LATER_CHANGE
UI003_RESULT_INFORMATION_HIERARCHY=NOT_REPRODUCED
UI004_RESULT_ACTION_HIERARCHY=NOT_REPRODUCED
```

当前 4K Result 在 1440×1000 浏览器中呈现三个明确步骤：前后对比、复核重点、成品摘要；技术信息折叠处理。可见决策动作是“返回调整 / 重新处理”和唯一主动作“确认结果并交付”，没有复现多个同等级主动作或无法判断下一步的问题。

## CURRENT_ISSUE_POOL

### CURRENT_P0

```text
COUNT=0
```

### CURRENT_P1

```text
ISSUE_ID=P1-07
LEVEL=P1
STATUS=CONFIRMED
NEW_ISSUE=YES
LOCATION=src/fileDisplayName.js；OutputCenterPage、TaskDetailPage、DashboardPage、BatchImageNamingPanel等调用点
CURRENT_BEHAVIOR=共享显示函数对完整文件名执行旧HDDE后缀replaceAll，无法区分用户原名与系统后缀。实际文件“客户_影界瑕疵修整_项目_影界瑕疵修复_20260901_110235.png”在输出中心和处理结果页被显示为“客户_影界瑕疵修复_项目_影界瑕疵修复_20260901_110235.png”。输出中心按真实原名搜索得到0项，按被错误改写的名称搜索得到1项。
EXPECTED_BEHAVIOR=用户原始文件名部分逐字符保留；用户按磁盘真实文件名可以查找到成品；只有后端已经证明的HDDE系统后缀可以规范化。
USER_IMPACT=用户看到的名称与磁盘真实文件不一致，无法按真实文件名查找成品，并可能在核对或交付沟通时误认文件身份。文件操作仍绑定真实item/path，未发现错误文件写入或数据损坏，因此等级为P1而非P0。
EVIDENCE=正式注册表 original_filename 为“客户_影界瑕疵修整_项目.png”；正式输出文件真实存在；Chrome/Playwright复现显示名被改写且真实名搜索0项；src/fileDisplayName.js对整名使用replaceAll。
ROOT_CAUSE_STATUS=CONFIRMED
RECOMMENDED_SCOPE=只修复用户可见文件名展示与搜索的来源边界；保留剪贴板GUID友好显示；复用后端已确认的delivery_file_name/original_filename边界，不改后端命名、Task/Result/Delivery合同、历史实体文件或正式目录。
```

该问题不重新打开已冻结的 Smart Delivery 后端来源边界。`SmartDeliveryPage` 当前仍直接展示后端 `delivery_file_name`；问题存在于其他仍复用旧宽泛显示函数的页面。

### CURRENT_P2

```text
COUNT=0
```

## OUTPUT_CENTER_REVIEW

```text
OUTPUT_CENTER_STATUS=P1_CONFIRMED
AVAILABLE_ITEMS=19
FILE_UNAVAILABLE_RESULTS=2
FILE_UNAVAILABLE_NOTICE=“已排除 2 个不存在或无法读取的文件记录”
SEARCH=AVAILABLE_BUT_AFFECTED_BY_P1-07
TYPE_LABELS=PASS
FORMAL_NAMES=PASS
ENGINEERING_FIELDS_EXPOSED=NO
```

输出中心当前只列出仍存在且可解码的正式成品；两个 `FILE_UNAVAILABLE` Result 被排除并以聚合提示表达。三个不可用 Delivery 属于交付记录，不被错误计入可用成品数量。除 P1-07 的显示名与搜索问题外，未发现新的文件状态、类型、操作入口或工程字段问题。

## PROCESSING_CENTER_REVIEW

```text
PROCESSING_CENTER_STATUS=PASS
CURRENT_TASK_HISTORY_ISOLATION=PASS
COMPLETED=PASS
FAILED=NOT_REPRODUCED
FILE_UNAVAILABLE=权威事实保持，未恢复删除Task
DELETED_TASK_REAPPEAR=NO
CURRENT_SUMMARY_IN_HISTORY=NO
```

本轮复用 16 个现有 Task，只读查看当前/历史页签；没有新建任务。历史视图显示 16 条已有任务且不混入当前摘要。两个已删除 Task 仍不存在，`FILE_UNAVAILABLE_RESULTS=2`、`FILE_UNAVAILABLE_DELIVERIES=3` 未变化。

## FROZEN_CAPABILITY_CHECK

```text
FROZEN_CAPABILITY_REGRESSION=NO
SETTINGS_UNIFIED_OUTPUT=PASS
4K_NAME_AND_OUTPUT=PASS
1080P_NAME_AND_OUTPUT=PASS
RETOUCH_NAME_AND_OUTPUT=PASS
SMART_DELIVERY_PROVENANCE_BOUNDARY=PASS
HISTORY_DATA_HEALTH=PASS
```

P1-07 是冻结链之外的相邻展示层问题：没有改变真实文件、后端交付名、注册表、正式目录或 Smart Delivery 新交付链。

## NEXT_BATCH_PRIORITY

```text
NEXT_BATCH=1
RECOMMENDED_FIRST_TASK=V0.5.7｜UI/UX｜P1-07｜跨页面文件名展示来源边界收口
```

下一批只处理 P1-07。不得顺带调整 CSS、导航、状态模型、后端命名算法或历史文件。验收重点应是：用户原名逐字符不变、真实文件名搜索可命中、已证明系统后缀仍按后端事实展示、Smart Delivery 已冻结链无回归。

## VALIDATION

- 静态扫描：`src` 44 个文件、相关后端与正式注册表；核对阶段01原始报告全部11项。
- 真实 Chrome + Playwright，视口 1440×1000：
  - 未知路由恢复页与返回处理中心：通过，Console 0。
  - 现有 4K Result：规范 Result URL 200，3840×3840 成品真实解码，Console 0。
  - 隔离模拟 4K Result GET 404：确认交付按钮禁用，显示失败原因和重新检测入口。
  - Result 信息/动作层级：三个步骤、一个主动作，未复现 UI-003/UI-004。
  - 输出中心：19 个可用成品、2 个不可用 Result 聚合提示；P1-07 真实复现。
  - 处理中心当前/历史隔离：通过，历史视图当前摘要数量 0，Console 0。
  - 系统设置：统一输出根目录 `D:\影界文件\输出`，旧 1080P 目录名称 0，版本 `V0.5.7-dev`，Console 0。
- 未新建业务任务、未确认交付、未打开本地文件或目录、未写入正式注册表。

```text
FILES_SCANNED=49（src 44 + backend/main/version/阶段01报告/正式注册表 5）
PLAYWRIGHT=PASS
CONSOLE=0_ERRORS
```

## PROTECTION

```text
MODIFIED_FILES=NONE
REPORT_CREATED=HDDE_V0.5.7_UIUX_REMAINING_ISSUES_STAGE02.md
GIT_WRITE_OPERATION=NO
STAGING_EMPTY=YES
FORMAL_DATA_MODIFIED=NO
USER_FILES_MODIFIED=NO
SELF_AUDIT=PASS
NEXT=EXECUTE_NEXT_BATCH_1_ONLY
```

`MODIFIED_FILES=NONE` 指生产代码、CSS、配置、正式数据、用户文件与历史任务均未修改；本报告是任务明确允许新增的唯一文件。

`ui-ux-pro-max` 只用于可用性、信息层级、动作层级与问题等级判断，没有输出新视觉方案。Playwright 只覆盖任务卡指定关键路径，没有扩张为全量 E2E。

Skill迭代判断：暂不需要更新。当前结论属于 V0.5.7 一次性问题池与具体显示缺陷，不是新的跨版本稳定规则。
