# D61-05 桌面刷新生命周期修复验收

STATUS=BLOCKED

VERSION=V0.6.1 开发版 / 0.6.1-dev
BRANCH=codex/image-processing-routing-v1
HEAD=aa0dd93265d270eb5192ebbd44a1fe14488d454a
STAGING=EMPTY
DIRTY_BASELINE=原有 dirty 条目保留；Git 写操作 NONE。

ROOT_CAUSE=原 run_desktop_window.on_loaded 在每次 WebView loaded 时重复要求 current_url 和 pathname 为 /processing，非首屏刷新触发 window.destroy。修复前新增回归确实报 A later page load closed the desktop。另有独立正常关闭验收失败：导航刷新后窗口 closed=true，后台 thread.join(15) 后仍存活并抛 PackagedRuntimeError。只读观察 connections=0/tasks=0，协程为 Server.serve/LifespanOn.main 等待，伴随 Windows Proactor ConnectionResetError 10054。后者的最终根因及是否修改前已存在均 NOT_YET_CONFIRMED；不据此断言 SSE 阻塞，不改 timeout、后端或事件循环。

FILES_MODIFIED=
- runtime/packaged_launcher.py：7 行首次加载标志及守卫，after SHA=886bd0cf1f79e26d84cb06f97971cdcb71181e9df4c09bf86d65ccee6884c742。
- tests/test_packaged_runtime.py：同一加载回归覆盖后续颜色/输出/处理页 loaded 不关闭，以及错误首次入口仍拒绝。
- 本报告、docs/09_CODEX_CHANGELOG.md。
- 验收文件 output/playwright/d61-05r-20261003/；真实照片只读选样新增 d61-abr-20261003/real-candidates-24.* 和 real-candidates-36.*，未改旧证据。
- 另一获授权 D61-06 聊天重建正式 dist 的归属单独记录；本聊天 production build 使用独立 outDir，没有覆盖它。

IMPLEMENTATION=只检查首次 loaded；后续加载在页面检查和启动 errors 累积之前返回。原 /processing 首屏检查、EdgeChromium 检查、窗口关闭 stop_requested、后端监视及退出控制均保持。未修改颜色/压缩/水印算法、输出中心、Task/Result/批次合同或用户设置。

TESTS=
- 前端 380/380，fail=0，skipped=0（frontend.log）。
- D61 Python 70/70（python-d61.log）。
- 输出中心 Python 57/57（python-oc.log）。
- 启动器 15/15（launcher-after.log）；修复前真实回归失败保留于 launcher-before.log。最初临时目录沙箱权限失败另有证据，纠正测试运行目录后才认定复现，不把环境错误作为产品失败。
- production build 通过（build.log），独立 production-build/。

REAL_RUNTIME=实际 Windows EdgeChromium 原生窗口，run_packaged_runtime 真实拥有 Uvicorn backend，使用当前源码、正式 D:\影界文件、生产 dist；不使用 validation root 或 Mock。三轮各 10 次颜色页刷新全部存活；输出 /outputs、处理 /processing、压缩 /compression 刷新以及 SPA 前进后退通过。refresh.json、refresh-diagnose.json、refresh-trace.json 保留完整路径和 health 证据。首次脚本误写 /output-center 已纠正为真实 /outputs，只结束验收脚本，没有改产品路由。

正常关闭五轮中：first、diagnose、trace 三轮失败，second 和 binding 成功。binding.json 实证 exit_code=0、8787 关闭、全部本轮 owned Python/WebView2 PID 归零；不能用此覆盖其他三轮失败。失败进程保留日志/线程栈后按精确 PID 清退，这不算正常关闭通过。完整重开后新 runtime/PID 和当前 dist 可用，结束时恢复 /processing 正式桌面（desktop-final.json）。整项正常退出/无残留门禁 FAILED。

POSITIVE_CHAIN=既有十条确为 completed、ACCEPT_CORRECTED，Source/Task/Result/正式路径/输出 SHA/参考 SHA 一致且完整解码；独立 D61-06 的 source-provenance-audit.json 保留逐条事实。本轮新完整重开后十卡片及十缩略图全部显示，真实打开成品 HTTP200，继续处理 source_result_id/source_sha256 一致，继续颜色页刷新仍存活（binding-restart.json）。但是 D01_02/D01_03 在 tests/color_correction/run_d01_evaluation.py 中明确标记为受控错误偏黄/偏蓝，不能冒充未经改造真实图片正路径。本轮追加五组原始学校照片只读评估：2 REVIEW_REQUIRED、3 ACCEPT_ORIGINAL，没有 ACCEPT_CORRECTED（real-pair-selection.json）。没有发布这些审核候选，没有创建新颜色 Result，严格真实照片正链仍 NOT_VERIFIED。

NEGATIVE_CHAIN=沿用两个既有真实任务 color_e7f6d3324075469e / color_6bd8ce8d079d48b2，正式重开后仍 failed、Result=null、result_id 为空；Source 缓存与原始 A SHA 一致，参考缓存与原始 B SHA 一致；无输出伪造。两种跨功能旧 Task 反馈请求均 HTTP409（negative-context-proof.json）。未重新处理既有负样本。

REGRESSION=本轮完整最终 SHA 复核：原34正式输出与 settings、原始 A/B及48选样原图均不变；17受保护关键文件不变，此前13文件保护门禁全成立；D61-06 当前52文件/48输出快照也逐文件无差异。颜色算法、4K、压缩、瑕疵修复、共享 Registry 和 Output Center 源码未改。settings SHA=7d904536f0c34b9ae8636b378556f733d32c5d23c5e8f1384a5e09f34271f7d5。未回滚并行成果。01:12 compression_b32febc58896477f 新任务来源 UNKNOWN，保留并排除出本轮验收，不能借 latest task 绑定颜色反馈。正常退出门禁仍有真实失败。

FREEZE_STATUS=NOT_FROZEN；D61 未冻结。

NEXT=保留首次加载修复；对 owned backend 正常关闭失败另行限定根因修复范围，并完成未经改造真实照片 ACCEPT_CORRECTED 正链。满足 D61 全部门禁后才进入 S61-OC-02R；当前未启动其共享冻结流程。

证据目录：D:\Codex\04_Visual-Master-Pro\output\playwright\d61-05r-20261003。
