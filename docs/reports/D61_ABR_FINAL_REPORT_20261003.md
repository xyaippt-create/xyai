# D61-ABR 正负链路补验

STATUS=BLOCKED
FREEZE_STATUS=D61 未冻结

VERSION=0.6.1-dev / V0.6.1 开发版 / DEVELOPMENT
BRANCH=codex/image-processing-routing-v1
HEAD=aa0dd93265d270eb5192ebbd44a1fe14488d454a
STAGING=EMPTY；无 Git 写操作，dirty 基线保留。

## FILES_MODIFIED

- tests/image_compression_ui/test_a61_05_compression_advice.mjs：仅修改一条反馈路由集合断言并新增一行说明。
- docs/09_CODEX_CHANGELOG.md、本报告：记录本轮结论。
- output/playwright/d61-abr-20261003/：本轮测试、独立 production build、保护 SHA、少量只读选样证据。

产品源码、颜色算法、输出中心、冻结启动器均未修改。本聊天负责测试契约及复核；按用户明确授权，现有“V0.6.1｜D线｜颜色校正”聊天独占正式桌面与服务生命周期验收。其新增运行证据位于 output/playwright/d61-05-20261002/；不能把其他聊天的历史产品修复或原有 dirty 成果计入本轮改动。

## ASSERTION_ATTRIBUTION

生产合同正确：src/App.jsx 的反馈路由包含 compression 和 color-correction；颜色路由还要求当前 taskConfig.feature_key=color_correction。ColorCorrectionPage 发布当前任务上下文，feedbackTarget 拒绝颜色入口绑定其他 feature。

原压缩建议测试精确要求路由集合只包含 compression，因此在合法新增颜色反馈路由后失效。依本轮用户明确授权，更新该测试集合断言和说明，没有修改生产路由、压缩建议行为或弱化失败任务的 Result 合同。assertion-only.patch 与 before 测试文件证明只有上述两行变化。

## TESTS

- 当前前端全量：380/380，失败 0、跳过 0，退出码 0。
- D61 稳定性、颜色 API、参考颜色 API、相邻反馈 context/v3：70/70，退出码 0。
- 输出中心、批次、批量水印、记录删除及品牌相关 Python：57/57，退出码 0。
- production build：退出码 0，产物位于本轮独立 production-build，未覆盖正式桌面的 dist。

日志：output/playwright/d61-abr-20261003/frontend-full.log、python-d61.log、python-oc.log、build.log。

## REAL_RUNTIME

既有真实用户 A/B 负路径沿用，未重新提交它们的普通/参考算法请求。reference Task=color_e7f6d3324075469e、ordinary Task=color_6bd8ce8d079d48b2 均 ACCEPT_ORIGINAL / failed / Result=null；Source 缓存文件 SHA 对应 A，reference_metadata 与 provenance SHA 对应 B。负路径 Registry 与反馈当前 Task 事实一致，未伪造输出。

正式原生 EdgeChromium 桌面另外完成普通 5 次、参考 5 次真实处理：十个有效 Result 与可解码正式文件、Registry、输出中心及继续输入一致；无处理空白页、永久 pending 或输出缺失。正式压缩/瑕疵修复各一次烟测通过。该十次输入是既有明确标注的验证样本，不能替代本轮另选未经改造真实照片的 ACCEPT_CORRECTED 门禁。

前后端运行链已重启，backend PID 12556→40068，runtime_id RUN-20261002T235755-D395C1C67F→RUN-20261003T003659-B4938924C9。新原生桌面进程已重开，十个成功 Result 重启后仍显示；真实打开成品响应及继续颜色输入绑定通过，前端资源 SHA 一致。证据：stability.json、formal-output-proof.json、restart-proof.json、desktop-shell-restart-1.json。

反馈无颜色任务、失败颜色任务、成功颜色任务三类已核对：feature/module/current Task 匹配；失败没有 Result，不借用 4K 或历史 Result。真实负路径的重启事实与身份在 negative-context-proof.json 保留。

## BLOCKERS

1. 正式颜色页刷新会关闭原生窗口。真实继续编辑页刷新产生 page_closed，native-color-refresh.json 明确记录 FAILED；desktop-shell.json 记录 page_path=/color-correction、window_closed=true。runtime/packaged_launcher.py:288 的 on_loaded 在每次加载时都检查 current_url.endswith(DEFAULT_PAGE) 和 pathname=/processing；颜色页刷新后在 :309 调用 window.destroy()。源码未修改。普通入口刷新探针先读到 body 时写入 PASS/closed=false，但稍后的 desktop-shell-restart-1.json 已记录 window_closed=true；原生进程 70742 随后退出码 1，PackagedRuntimeError 明确为 /color-correction。native-refresh-reconciliation.json 已将该即时采样纠正为 FAILED 并保留原记录，不能以短暂 body 可读支持刷新通过。
2. 未证明另选真实照片的 ACCEPT_CORRECTED 正路径。本聊天只读检查同一原始学校照片目录的 12 组配对，6 组 ACCEPT_ORIGINAL、6 组 REVIEW_REQUIRED。选样不调用正式 API、不落盘候选/Result、不改源图或算法。REVIEW_REQUIRED 不能冒充 ACCEPT_CORRECTED；上述有限样本结论也不表示所有真实照片均不能校正。当前严格正路径门禁为 NOT_VERIFIED。

冻结启动器处于受保护范围；本轮为补验和旧测试契约对齐，没有修改该生产模块或降低刷新门禁。自动测试全绿不能覆盖真实窗口退出或缺少严格正路径的阻断。

## PROTECTION

本轮 integrity.json 全部门禁通过：branch/HEAD 不变、staging 为空；原 34 个正式输出路径及 SHA 不变；原始 A/B 和选样照片 SHA 不变；产品源码、输出中心批次合同及四个颜色算法文件 SHA 不变；旧 dirty 项没有消失。

settings/settings.json SHA256=7d904536f0c34b9ae8636b378556f733d32c5d23c5e8f1384a5e09f34271f7d5，保持不变。

NEXT=先明确授权修复冻结启动器的刷新退出问题，并补足严格真实 ACCEPT_CORRECTED 样本链。D61 全部门禁通过并冻结后，立即执行 S61-OC-02R；当前不得提前进入。

协调任务最终报告：docs/reports/D61_05_FORMAL_DESKTOP_ACCEPTANCE_20261003.md，结论同为 BLOCKED。其 launcher-refresh-proposal.patch 仅为未应用的审核提案，不是当前产品修复，也没有据此宣布刷新通过。正式服务与新的 /processing 原生桌面已重开。

Skill迭代判断：暂不需要更新；本轮属于动态缺陷和阶段验收结论。
