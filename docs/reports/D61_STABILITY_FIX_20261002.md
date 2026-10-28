# V0.6.1 D61 颜色校正稳定性修复证据

STATUS=PARTIAL

D61_STABILITY_FIX=PARTIAL（不得冻结）

VERSION=0.6.1-dev / V0.6.1 开发版 / DEVELOPMENT

BRANCH=codex/image-processing-routing-v1

HEAD=aa0dd93265d270eb5192ebbd44a1fe14488d454a

STAGING=EMPTY；HEAD 未变化；未执行 Git 写操作。

DIRTY_BASELINE=PROTECTED。仓库开始即有大量受保护改动；本轮保留既有内容。当前版本文件与旧状态文档的 V0.5.8-dev 标题冲突，以实时 product_version.json 和运行接口为准，未改版本。

ROOT_CAUSE=

- D61-01：NOT_YET_CONFIRMED。用户明确入口为“上传参考图”按钮。真实文件选择、React 当前 hooks、预览、intake token/路径/SHA、请求、API、Task、processor Result 的五种操作均未复现漂移；没有修改上传状态来掩盖问题。
- D61-02：算法安全决定 ACCEPT_ORIGINAL 不生成新 Result，但 API 原来仍返回 HTTP 200 / success=true / completed / Result=null。另一个明确代码故障是 transition_task 在 Registry 持久化之前先把传入对象改成 completed，登记失败仍可能暴露完成状态。前者由真实运行复现；后者由旧源码重放与定向写入失败测试证实，不把故障注入称为真实磁盘故障复现。
- D61-03：上述 Result=null 进入完成 UI，仍读取 result.improvements 等字段，触发 React TypeError，页面空白、操作不可继续。真实浏览器曾收到 Cannot read properties of null (reading 'improvements')。其他偶发性能卡顿根因 UNKNOWN。
- D61-04：颜色页面没有发布当前 task context，也未被 App 列入反馈任务路由；UnifiedFeedback 直接选择全局最近 feedback target，覆盖当前颜色 feature，绑定了前一个 4K Task / Result。

D61_01=PASS_FOR_TESTED_IDENTITY_CONTRACT；REPORTED_OVERWRITE=NOT_REPRODUCED；ROOT_CAUSE=UNKNOWN。

D61_02=PASS_ISOLATED_REAL_RUNTIME；FORMAL_MAIN_RUNTIME=NOT_VERIFIED。

D61_03=PASS_ISOLATED_REAL_RUNTIME（已复现的空白页故障）；其他偶发卡顿 UNKNOWN。

D61_04=PASS_ISOLATED_REAL_RUNTIME；FORMAL_MAIN_RUNTIME=NOT_VERIFIED。

SOURCE_REFERENCE_ISOLATION=PASS_FOR_TESTED_CASES

OUTPUT_CHAIN=PASS_ISOLATED；FORMAL=UNKNOWN

RUNTIME_STABILITY=PASS_ISOLATED；FORMAL_DESKTOP=UNKNOWN

FEEDBACK_BINDING=PASS_ISOLATED；FORMAL=UNKNOWN

## FILES_MODIFIED

本轮产品修改仅六个文件：

- backend/image_compression_api.py：颜色任务成功与输出/登记合同、失败返回和清除无效 Result 身份。
- src/ColorCorrectionPage.jsx：Result 为空时的渲染边界；发布/清除当前颜色任务上下文。
- src/App.jsx：颜色路由反馈上下文及 feature 检查。
- src/UnifiedFeedback.jsx、src/feedbackTarget.js：颜色入口拒绝其他功能的全局 target。
- main.py：颜色 context snapshot 对异功能 Task / target 返回 409。

测试：tests/image_compression_ui/test_d61_color_stability.py、test_d61_feedback_target.mjs、test_color_correction_api.py、test_reference_color_api.py、test_reference_color_ui.mjs、test_unified_feedback.mjs。

文档：本报告、docs/09_CODEX_CHANGELOG.md。

验证脚本、真实 fixture、截图、JSON、日志保存在 output/playwright/d61-stability-20261002/；ReproSight 记录在 .reprosight/runs/20261002t145326z-d61-01-source-reference-isolation/。它们是测试证据，不是用户正式资产。

IMPLEMENTATION=继续使用既有 writer、SharedTaskRegistry、Result、Output Center；没有第二条输出路径或平行 Result 系统。只在实际文件验证及现有 Registry 提交完成后发布 completed。无输出或保存/登记失败返回 failed / success=false；颜色算法、参数和参考上传状态未改变。没有新增 timeout、debounce、retry、fallback、自动刷新或自动重启修复。验证脚本等待上限不属于产品改动。

## TESTS

- 最终一次后端运行 28/28 PASS：[backend-final.txt](D:/Codex/04_Visual-Master-Pro/output/playwright/d61-stability-20261002/backend-final.txt)。包含真实 processor、可解码文件、Registry、无输出失败、保存失败及登记失败合同。
- 颜色/反馈前端 26/26 PASS：[frontend-tests.txt](D:/Codex/04_Visual-Master-Pro/output/playwright/d61-stability-20261002/frontend-tests.txt)。
- 输出中心、继续处理、压缩 session、瑕疵修复 UI 相关回归 71/71 PASS：[regression-frontend.txt](D:/Codex/04_Visual-Master-Pro/output/playwright/d61-stability-20261002/regression-frontend.txt)。
- 既有反馈 context/v3 回归 13/13 PASS：[regression-feedback.txt](D:/Codex/04_Visual-Master-Pro/output/playwright/d61-stability-20261002/regression-feedback.txt)。
- npm run build PASS，78 modules。
- 新增两项合同测试对编辑前保存的后端重放，均因 success=true 真实失败；这是事后基线重放，非伪称修改前已运行：[contract-baseline.txt](D:/Codex/04_Visual-Master-Pro/output/playwright/d61-stability-20261002/contract-baseline.txt)。
- 三个旧缓存用例在编辑前源码也失败；旧断言要求删除真实卡片，与当前 S61-OC-02 合同冲突。调整为卡片保留、thumbnail_status=unavailable、无缩略图 URL、文件动作正常、越界缩略图请求明确 422、外部目录不存在。未修改输出中心代码来通过测试。

## REAL_RUNTIME

使用真正的本仓库 backend、Vite 和 Edge，现有 --validation-runtime-root 隔离机制；最终服务 8795/5185，运行目录为 C:\Users\xyppt\.codex\visualizations\2026\10\02\01a0fd19-309f-72a0-8160-f96c9c9c8bb7\d61-runtime-final。这不是正式 D:\影界文件验收，也不是 Mock。

正式共享 8787 在核验时 started_at=2026-10-02T23:06:37+08:00，而完整修复 main.py / backend 文件分别在 23:14:14 / 23:20:54 修改；未替换其加载代码。该服务由同仓库 S 线任务使用，本轮未停止或重启该服务，也未向其他任务发送消息。正式桌面/安装包当前修复验收 UNKNOWN。最终隔离服务加载时间为 23:28:12，晚于最后源码修改；本轮隔离服务在验证结束后停止，文件和反馈包保留。

REFERENCE_SOURCE_IDENTITY=

- A→B、重新更换 B、删除 B、重新上传 B、切换普通校色：Source 的前端 selectedItems、预览、文件名、token 与 SHA 保持 A；referenceInput 独立变化。还用同文件名 A/B 检查上传缓存目录独立性。
- 文件选择按钮调用 reference handler，源 handler 独立；reference-run payload 使用 target_source_token / reference_source_token；API 分别解析 source/ref，task source_path 保持 A，processor 使用 A target、B reference。
- 实际成功 Task=color_3449da9bce0d4d3a；Result=color_result_2a7e4119ffc34527。A SHA=ead07d50e3b3c7a6e9ffcb36a64a1f7994717b0228cf06a518cb11283e7986f7；B SHA=9625fb08ae3ba7766d164666fd7599943fdf6285e31111f954750cdd40d596d3。Result source/reference provenance、实际 cache 文件和持久 Registry 一致：[d61-01-identity.json](D:/Codex/04_Visual-Master-Pro/output/playwright/d61-stability-20261002/d61-01-identity.json)。
- 未复制状态、恢复 A 或引入兼容路径；原覆盖报告仍 UNKNOWN。

OUTPUT_FILE_CHAIN=PASS_ISOLATED。输出修复阶段普通/参考各连续 3 次通过；最终源码另完成普通 5 次/参考 5 次。最终 10 个文件均存在、非零、完整 PIL decode、526×789、SHA 匹配 Registry，输出中心可发现，intake-result 继续处理仍引用原 Result：[final-runtime-proof.json](D:/Codex/04_Visual-Master-Pro/output/playwright/d61-stability-20261002/final-runtime-proof.json)。中间验证的两种无输出样本明确 failed：[output-chain.json](D:/Codex/04_Visual-Master-Pro/output/playwright/d61-stability-20261002/output-chain.json)。

HANG_REPRODUCTION=真实复现“backend 已 completed 且 Result=null → React 抛错 → 页面空白”；不是长时间 processor pending。上传、preview、请求、processor、保存、登记和 UI 返回由 fetch/请求时间戳、响应、React hooks、任务生命周期及文件事实追踪。最终普通/参考交替 10 次，每次更换参考图、重新处理、查看结果、返回颜色页；errors=0、处理请求恰为 10、按钮与页面均恢复：[stability.json](D:/Codex/04_Visual-Master-Pro/output/playwright/d61-stability-20261002/stability.json)。永不结束 promise、重复更新循环、同步大文件阻塞等其他故障本轮未复现，UNKNOWN。

FEEDBACK_CONTEXT_BINDING=

- 修复前真实 4K Task=task_20261002_231238_ae5f4d1c；颜色失败 Task=color_bdc066abc9664118。颜色入口却发送 enhancement_4k / hdde.enhancement.4k 并绑定 4K Task：[feedback-before.json](D:/Codex/04_Visual-Master-Pro/output/playwright/d61-stability-20261002/feedback-before.json)。
- 修复后尚无颜色任务：color_correction / hdde.color.correction、Task/Result 均空；失败颜色 Task=color_6103d96744894d4c，Result=null；成功颜色 Task 和 Result 一一匹配。实际本地 ZIP feedback.json common_context 均验证；没有发送或上传反馈：[final-audit.json](D:/Codex/04_Visual-Master-Pro/output/playwright/d61-stability-20261002/final-audit.json)。
- 显式向颜色 snapshot 提交 4K Task 或 4K feedback target，均 409，fail closed：[feedback-zip-proof.json](D:/Codex/04_Visual-Master-Pro/output/playwright/d61-stability-20261002/feedback-zip-proof.json)。

REGRESSION=上述相关自动测试通过；隔离真实 4K 输入产生完成结果并作为反馈错绑前置条件，4K 算法未修改。压缩、瑕疵修复本轮完整真实运行 UNKNOWN，不能用 UI 测试替代其实际算法验收。

FROZEN_MODULES_TOUCHED=NONE_BY_D61。开始/结束 8 个保护文件 SHA 全相同：4 个颜色算法文件、4K 算法、local_retouch API、CompressionPage、OutputCenterPage。共享 backend 文件中另有 S 线并发的 thumbnail_status 差异，不属于本轮 D 修改；保留它们。当前开始到结束的 diff 含并发 S 修改及已有 changelog 新条目，不能把全部 diff 归为本轮成果。

COLOR_ALGORITHM_FILES_MODIFIED=NONE

REMAINING_RISK=用户实际 A/B 覆盖案例仍未复现；正式共享/桌面服务未加载完整补丁；其他偶发卡顿、大图性能 UNKNOWN；登记失败后已写出的未登记文件保留，不冒充成功 Result，也未擅自删除。未做完整安装包或所有冻结功能实际运行验收。

NEXT=在不干扰 S 线的维护窗口加载完整补丁，使用用户实际 A/B 样本从“上传参考图”入口复现；完成正式目录、桌面连续运行与反馈包复核后，才可重判 D61_STABILITY_FIX。当前不得提前冻结。
