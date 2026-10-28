# D61-05 正式桌面收口验收

STATUS=BLOCKED

VERSION=0.6.1-dev / V0.6.1 开发版 / DEVELOPMENT
BRANCH=codex/image-processing-routing-v1
HEAD=aa0dd93265d270eb5192ebbd44a1fe14488d454a
STAGING=EMPTY；没有执行任何 Git 写操作。受保护 dirty 基线保留。

ROOT_CAUSE=本轮新阻断已真实定位：runtime/packaged_launcher.py 的 run_desktop_window.on_loaded 每次页面 loaded 都要求路径为 /processing；刷新颜色页面时，该启动检查调用 window.destroy()，随后进程抛 PackagedRuntimeError。参考上传覆盖原目标图的原始根因仍 UNKNOWN，现象 NOT_REPRODUCED。本轮没有猜测修改上传代码，也没有修改冻结启动器。

FORMAL_RUNTIME_PATCH_LOADED=YES

旧共享服务启动时间早于完整 D61 修复。先执行正式 production build，再由现有 formal_launcher 正常停止并重启共享服务。实际 EdgeChromium 原生桌面使用 runtime.packaged_launcher.run_desktop_window，打开正式 8787 生产前端，后端使用仓库 .venv 和当前源码，正式根目录为 D:\影界文件，未改 settings 或使用验证目录替代正式目录。

- 加载修复后的 Runtime：RUN-20261002T235755-D395C1C67F，后端 PID 12556，启动 2026-10-02 23:57:55 +08。
- 前后端完整重启后的 Runtime：RUN-20261003T003659-B4938924C9；新后端 PID 与原进程不同，新原生桌面进程再次加载正式 /processing。
- build_id=V0.6.1-dev+aa0dd93265d2.dirty.20261002T155644071Z。
- 正式入口 dist/assets/index-CQCWrOvA.js，SHA256=abecf247b140d00d232769d599ae2d96d6f2a1e56ce50474eae1fed7c7328f7e。
- 实际桌面加载的 7 个 JS 资源逐字节 SHA 与当前 dist 一致，重启后再核验相同；18 个关键源码、算法、版本及 settings 文件与验收前 SHA 一致。后端启动晚于最终修改时间，正式无输出失败与反馈拒绝行为也由当前实际代码执行。

证据：[patch-loaded.json](../../output/playwright/d61-05-20261002/patch-loaded.json)、[restart-proof.json](../../output/playwright/d61-05-20261002/restart-proof.json)、[final.json](../../output/playwright/d61-05-20261002/final.json)。本轮没有重建安装包或安装 EXE，已安装分发包的补丁加载结论 UNKNOWN。

D61_01=PASS：当前数据及正式桌面 UI 隔离合同通过。
D61_02=PASS：十个成功任务的正式输出链通过；真实 A/B 合法无输出分支明确 failed / Result=null。
D61_03=PARTIAL：Result=null 页面不再崩溃，十次处理无空白页/永久等待；另发现原生颜色页刷新退出，阻止正式桌面稳定性冻结。
D61_04=PASS：正式反馈 snapshot 与实际本地 ZIP 绑定当前颜色 task/result；无任务与失败任务不借用历史 Result，其他功能目标拒绝。

ORIGINAL_OVERWRITE=NOT_REPRODUCED
SOURCE_REFERENCE_ISOLATION=PASS

实际用户原图：

- A= D:\定制业务\学校定制\照片s\Image_1781401319675_392.jpg，2133×1600 RGB JPEG，398418 bytes，SHA256=4930ffa47f6d6d24b7551dbd6da1be8443d064826e7b2ea728bf3f4aa0e1b961。
- B= D:\临时文件\ChatGPT Image 2026年6月28日 14_48_41.png，1672×941 RGB PNG，1503460 bytes，SHA256=49fbe7b41865db05e6bf9c0ecbabe2cec5e36a3bd1faa201315794cf26f6b8b7。

在正式原生桌面通过“上传参考图”按钮执行 A→B、更换 B、删除 B、重传 B、普通模式五种场景，逐步记录生产 React hook、原文件属性、source_token、source_sha256、safe_preview_url、当前 img src/currentSrc、解码尺寸和容器位置。Source token / SHA / 预览地址保持 A；参考图独立为 B。当前两个预览均使用独立 API 安全预览地址，没有 Object URL 串用或参考容器绑定目标图。原生画面截图已实际查看，没有出现视觉覆盖。目标卡片下的棋盘区域是现有 dropzone 背景，真实目标预览位于文件行缩略图。

证据：[user-actual-upload-identity.json](../../output/playwright/d61-05-20261002/user-actual-upload-identity.json)、[实际 A/B 原生桌面](../../output/playwright/d61-05-20261002/user-actual-A-B.png)。

按照用户最新 D61-ABR 要求，沿用已完成的真实 A/B 负路径，没有再次执行该组算法：参考任务 color_e7f6d3324075469e、普通任务 color_6bd8ce8d079d48b2 均 HTTP422、success=false、failed、Result=null，决策 ACCEPT_ORIGINAL。重启后再次核对 Registry 仍无 Result，实际 Source 文件 SHA 为 A，参考文件 SHA 为 B，没有伪造输出。失败任务 RESULT_SOURCE / RESULT_REFERENCE 不适用；成功 Result 的双身份另由十次正式链验证。

证据：[原始实际 A/B 请求与响应](../../output/playwright/d61-ab-acceptance-20261002/real-ab-browser.json)、[重启后负路径和拒绝外国功能绑定](../../output/playwright/d61-05-20261002/negative-context-proof.json)。

OUTPUT_CHAIN=PASS（正式十个成功任务）；REAL_PHOTO_ACCEPT_CORRECTED=NOT_VERIFIED。

连续十次通过正式原生桌面的选择、处理按钮、Result 页面、输出中心卡片、继续处理入口执行。普通 5 次、参考 5 次；参考场景包含更换、删除和重传。每次成功任务均具备真实文件 >0 bytes、全图 PIL 解码、526×789 原尺寸、文件 SHA 与 Result output_sha256 一致、正式 Registry completed 及 Task/Result 一一对应、输出中心实际卡片、继续输入 source_result_id / source_sha256 与当前 Result 一致。前两次及重启后最后一次实际调用“打开成品”，现有 OS 打开入口返回成功；真实文件也独立完整解码。

十次输入是既有 D01 校色验证样本，属于正式 UI / API / processor / writer 的真实执行，没有 Mock。它们不冒充用户新增要求的未经改造真实照片正路径。新增选择了同一用户照片目录的两张校园原始 JPG：Image_1781400707642_360.jpg 与 Image_1781400714691_318.jpg；两张实图已查看、完整解码并记录 SHA。该组合仍为 ACCEPT_ORIGINAL，不曾强制生成 Result；进一步有限只读选样也没有证明真实照片 ACCEPT_CORRECTED。该新增正路径门禁仍未满足。

证据：[stability.json](../../output/playwright/d61-05-20261002/stability.json)、[formal-output-proof.json](../../output/playwright/d61-05-20261002/formal-output-proof.json)、run-1.json 至 run-10.json、[额外校园组合](../../output/playwright/d61-05-20261002/real-campus-positive-identity.json)。

RUNTIME_STABILITY=BLOCKED

连续处理序列：SUCCESS_COUNT=10，FAIL_COUNT=0，UI_CRASH=0，BLANK_PAGE=0，HANG=0，OUTPUT_MISSING=0，IDENTITY_DRIFT=0；执行 POST 数量恰好 10。这里不把合法算法保留原图的负路径计作成功，也不把验收采样错误计为产品故障。

新的刷新阻断实际发生两次：

1. 十次结束后，在 /color-correction?continue_result=color_result_e117cb9c20a849fd 刷新，页面关闭、原生进程退出码 1，异常路径 runtime/packaged_launcher.py:338。
2. 服务与桌面完整重启后，在普通 /color-correction 入口刷新，同样窗口关闭、原生进程退出码 1。即时浏览器 reload 采样先返回了页面 DOM；原生 on_loaded 回调随后销毁窗口，已在最终证据中明确纠正该即时观察，不以早到的 DOM 当作刷新 PASS。

仅 /processing 入口刷新通过，不能代替颜色页刷新门禁。后端仍健康，持久 Result 与文件均保留，根因属于桌面启动器的重复首屏路径校验，而非算法、文件保存或颜色 React 循环。

证据：[native-refresh-reconciliation.json](../../output/playwright/d61-05-20261002/native-refresh-reconciliation.json)、[首次刷新原始记录](../../output/playwright/d61-05-20261002/native-color-refresh.json)、[重开后普通入口原始记录](../../output/playwright/d61-05-20261002/native-color-refresh-ordinary-entry.json)、desktop-shell.json、desktop-shell-restart-1.json。仅准备了[待审核最小修复提案](../../output/playwright/d61-05-20261002/launcher-refresh-proposal.patch)，没有应用到生产源码，也没有以候选代码冒充正式加载。

采集限制：最小化窗口曾导致 CDP 截图失败，PrintWindow 得到的灰色图不作为产品空白页证据。恢复本轮窗口并使用实际 CDP surface 后采集成功。验收脚本早期有 intake 完成前采样、普通追加模式及缩略图队列等待错误，均按真实状态修正验证脚本，没有改产品状态或增加产品 retry/timeout/fallback。最终十次完整序列通过。额外校园输入出现两次执行任务，第二次发起端 UNKNOWN；该发生在最终十次之外，当前 React task 与反馈一致，记录见 extra-campus-task-observation.json，未推测根因或添加 debounce。

FEEDBACK_BINDING=PASS

正式桌面无颜色任务、失败颜色任务、成功颜色任务分别生成实际本地 ZIP，完整解包，feedback.json common_context 的 feature_key=color_correction、module_id=hdde.color.correction，task/result 与当前页面权威上下文一致；失败及无任务 Result 空。额外校园失败当前任务 color_3a13d9c3acf84f8f 不绑定此前已结束任务；成功当前 task/result 一一匹配。沿用实际 A/B 原始 snapshot 的正确绑定；重启后显式将既有 4K Task 或 foreign feedback target 传入颜色 snapshot，均 HTTP409。没有执行新的 4K 任务，没有发送/上传反馈。

REAL_RUNTIME=正式共享前后端及实际原生 EdgeChromium 桌面处理、文件、Registry、输出中心与继续输入通过；正常前后端重启及桌面完整退出重开后持久链通过；颜色页刷新 FAILED。最后已重开 /processing 可用桌面及正式服务。

TESTS=本轮相关后端 28/28、颜色反馈前端 26/26、正式 production build PASS。同一仓库协调任务依据用户 D61-ABR 明确授权，仅修正旧前端路由断言一行及注释一行，生产路由未变；实际共享代码全量前端 380/380、skip=0，D61/颜色/反馈 Python70/70，输出中心57/57，独立 production build PASS，均已读取当前日志核对。测试通过不能消除真实刷新退出或真实照片正路径缺失。

证据：本目录 backend-tests.txt、frontend-tests.txt；output/playwright/d61-abr-20261003/frontend-full.log、python-d61.log、python-oc.log、build.log、assertion-only.patch。

ADJACENT_SMOKE=PASS：正式原生压缩1次（compression_f1a5891a80bf44ea / compression_result_1dba71fb2c2c454d，263×395 PNG）及瑕疵修复1次（retouch_task_405f64f4054f4408 / retouch_result_c45fcd0e71294ac6，1915×821 PNG）；Task/Result completed，正式文件完整解码、SHA 一致，输出中心发现。没有运行 A/C 完整 Benchmark。

FILES_MODIFIED=本轮未修改产品源码、颜色算法、4K、settings 或冻结启动器。重建正式 dist；新增本目录报告、验收脚本/JSON/截图/日志/本地反馈 ZIP，更新 docs/09_CODEX_CHANGELOG.md。协调任务独立完成用户授权的 tests/image_compression_ui/test_a61_05_compression_advice.mjs 两行更新；保留其差异。本轮18关键源码指纹全部与初始值一致。

REGRESSION=正式压缩/瑕疵修复最小冒烟、正式输出与反馈通过；原34个正式输出逐文件路径、size、SHA 保持不变，settings SHA 不变，实际 A/B 原图 SHA 不变，四个颜色算法与 4K SHA 不变。STAGING=EMPTY，HEAD/branch 不变。新增正式输出没有覆盖原34个输出。

FROZEN_MODULES_TOUCHED=NONE（候选补丁未应用）。
REMAINING_RISK=颜色页刷新导致原生窗口退出；未经改造真实照片 ACCEPT_CORRECTED 成功链未证明；额外校园第二次请求发起端 UNKNOWN；安装 EXE 与打包分发环境 UNKNOWN。
FREEZE_STATUS=NOT_FROZEN；D61_STABILITY_FIX=BLOCKED。
NEXT=先取得回开冻结桌面启动器的明确授权，仅修首次加载检查错误；完成实际刷新回归，再补真实照片 ACCEPT_CORRECTED 正链后重新判定冻结。当前不能关闭 D61，也不能提前进入 S61-OC-02R。
