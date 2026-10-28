# 影界 HDDE V0.5.7 UI/UX 技术收口终审

任务：`V057_UI_P1_07_STRICT_FILE_IDENTITY_FINAL`  
日期：2026-09-01  
版本权威源：`product_version.json = 0.5.7-dev / V0.5.7-dev`

## STATUS

```text
STATUS=BLOCKED
STAGE_RESULT=BLOCKED
FREEZE_STATUS=NOT_READY

P1_07=CLOSED
FILE_IDENTITY_NAME_TRUTH=PASS
FILE_NAME_MUTATION=0
FILE_NAME_TRIM=0
FILE_NAME_QUERY_HASH_TRUNCATION=0
DISPLAY_FILENAME_SOURCE=REAL_FILE_NAME
FILE_NAME_SEARCH_SOURCE=REAL_FILE_NAME
HASH_FILENAME_DISPLAY=PASS
HASH_FILENAME_SEARCH=PASS
QUESTION_MARK_FILENAME_DISPLAY=PASS
LEADING_SPACE_FILENAME_PRESERVED=PASS
PRODUCT_DISPLAY_NAME=瑕疵修复

P0=0
P1=1
P2=0

4K_RESULT=PASS
UNKNOWN_ROUTE=PASS
OUTPUT_CENTER=PASS
HISTORY_DATA_HEALTH=PASS
SMART_DELIVERY=PASS
SYSTEM_SETTINGS=PASS

TESTS=FAIL_271_OF_273
BUILD=PASS
PLAYWRIGHT=FAIL_FULL_CLOSEOUT
CONSOLE_ERRORS=0

V0.5.7_UI_TECHNICAL_CLOSEOUT=NO
UI_DEVELOPMENT=NOT_COMPLETE
USER_FILE_LOSS=0
UNKNOWN_DELETION=0
GIT_WRITE_OPERATION=NO
NEXT=FIX_BATCH_WATERMARK_UI_INTEGRATION_ONLY
```

## P1-07 关闭证据

- `getFileIdentityName()` 对 API / Registry `file_name` 原值返回，不执行 `trim`、`?/#` 截断或名称替换。
- 文件系统路径与 URL 分别由 `getFileNameFromPath()`、`getFileNameFromUrl()` 提取 basename，不复用文件身份逻辑。
- Output Center 展示和文件名搜索均读取真实 `item.file_name`；产品类型仍独立映射为“瑕疵修复”。
- Node 定向反例覆盖 `客户#项目.png`、`客户?项目.png`、前导空格、旧名称、Windows 路径和 URL。
- 正式 Chrome 验证真实混合文件名逐字符显示；真实旧名称与产品类型分别可搜索。
- 隔离浏览器数据合同验证 `#`、`?`、前导空格显示与搜索全部通过；未写入 Registry 或正式文件。

## 最终收口阻断

当前唯一新 P1 是“批量水印 UI 接入未完成一致性收口”，有两个同源症状：`/batch-watermark` 已加入 enabled 路由与一级导航，但冻结的正式路由审计清单尚未同步；同时页面自身使用 `<main className="hdde-watermark-preview">`，外层 `AppShell` 已使用 `<main id="hdde-main-content">`。真实 Chrome 统计该路由存在 2 个 main landmark，违反单一主要内容地标合同。

对应证据：

- `src/AppShell.jsx`：Shell 主内容 `<main>`。
- `src/BatchWatermarkPage.jsx`：预览区再次使用 `<main>`。
- `tests/image_compression_ui/test_processing_center.mjs`：正式路由审计仍冻结为原 9 项，当前 enabled 清单新增 `batch-watermark` 后失败。
- `tests/image_compression_ui/test_v1_ui_unification.mjs`：单一 main landmark 合同失败，实际 `2 !== 1`。
- Playwright：`/batch-watermark` 可达、导航存在、`mainLandmarks=2`、Console 0。

该问题不属于 P1-07 授权范围，本任务没有修改批量水印页面、Shell 或 CSS。由于最终门禁要求 `P0=0 / P1=0 / P2=0` 且 `TESTS=PASS / PLAYWRIGHT=PASS`，当前不能冻结 UI 技术收口。

## 其余门禁证据

- Node：P1-07 文件身份与 Output Center 定向测试通过；全组 UI 271/273，两个失败均来自同一批量水印接入未收口问题。
- Python：Output Center 与 Smart Delivery 15/15 通过。
- Vite production build：通过，70 modules transformed；仅有现存 chunk size 警告。
- 正式启动链：前端 `127.0.0.1:5173`、代理 `/api/health` 200、版本 `V0.5.7-dev`、正式目录 `D:\影界文件` ready。
- 4K：正式结果图浏览器解码 `3840 × 3840`。
- 未知路由：显示恢复页与“返回处理中心”。
- Output Center：20 份可用成品，真实文件名展示/搜索通过，排除 2 条不可用 Result。
- 历史数据：`FILE_UNAVAILABLE_RESULTS=2`、`FILE_UNAVAILABLE_DELIVERIES=3`、两个已删除 Task 未恢复。
- 系统设置：统一正式输出根目录；旧 1080P 专用目录名称未出现。
- `git diff --check`：通过；只有换行转换警告。

## PROTECTION

- 暂存区为空。
- 未执行 Git 写操作。
- 未修改 Task / Result / Delivery 合同、Registry、正式目录、算法、CSS 或磁盘文件名。
- 未删除用户文件或未知文件；浏览器验证脚本运行后已移除。

`ui-ux-pro-max`：已用于判断文件身份、搜索真实性及单一 main landmark 的用户影响；未扩张视觉设计。  
Playwright：已覆盖正式 Output Center、P1-07 特殊字符反例、4K Result、未知路由、系统设置与新阻断路由。  
SELF_AUDIT=PASS_WITH_BLOCKER
