# D61 真实 A/B 样本验收与冻结复核

STATUS=BLOCKED

VERSION=0.6.1-dev / V0.6.1 开发版 / DEVELOPMENT
BRANCH=codex/image-processing-routing-v1
HEAD=aa0dd93265d270eb5192ebbd44a1fe14488d454a
STAGING=EMPTY；未执行 Git 写操作。现有 dirty 基线保留。

ATTRIBUTION=跨线测试契约冲突及真实 A/B 成功输出门禁未证明。D61 已在 src/App.jsx 的 FEEDBACK_TASK_ROUTES 中加入 color-correction；tests/image_compression_ui/test_a61_05_compression_advice.mjs:81 仍精确要求只有 TASK_ROUTES 加 compression。当前全量测试真实失败于该断言。按本轮禁止清零无关断言的要求，没有修改测试或生产代码。

FILES_MODIFIED=本报告、docs/09_CODEX_CHANGELOG.md；新增本轮隔离证据脚本、日志、哈希快照和 production build 产物。产品源码、测试、settings、输出中心代码均未修改。

TESTS=
- 当前前端全量：380 项，379 通过，1 失败，0 跳过；命令退出码 1。
- D61 颜色稳定性、颜色 API、参考颜色 API及相邻反馈 context/v3 组合：70/70，退出码 0。
- 输出中心、批次、批量水印、记录删除及品牌相关 Python 回归：57/57，退出码 0。
- production build：退出码 0；产物写入本轮独立目录，没有覆盖 dist。

REAL_RUNTIME=真实 A/B 已提供并完成正式 8787 实例的独立 Edge 浏览器验证，scope=REAL_AB_FORMAL_RUNTIME_INDEPENDENT_BROWSER。运行时 RUN-20261002T235755-D395C1C67F 使用 D:\影界文件。未操作并行任务桌面窗口或停止/重启共享服务；独立浏览器已关闭。用户明确授权发送 A/B 与验收要求给“V0.6.1｜D线｜颜色校正”，该聊天已接收并继续负责正式桌面及重启验收；其最终证据尚待完成。

A=D:\定制业务\学校定制\照片s\Image_1781401319675_392.jpg；2133×1600 RGB JPEG，398418 bytes，SHA256=4930ffa47f6d6d24b7551dbd6da1be8443d064826e7b2ea728bf3f4aa0e1b961。
B=D:\临时文件\ChatGPT Image 2026年6月28日 14_48_41.png；1672×941 RGB PNG，1503460 bytes，SHA256=49fbe7b41865db05e6bf9c0ecbabe2cec5e36a3bd1faa201315794cf26f6b8b7。
两张均完整解码；验收后原文件 SHA 保持不变。

SOURCE_TASK_RESULT_BINDING=真实 Source→Task 失败分支已核验。A→B、参考图更换、删除、重上传及自动模式切换六个检查点，A 预览 URL 不变；截图中 A 缩略图与 B 参考缩略图分别绑定原图片，未复现参考图覆盖 A。生产构建的组件名已压缩，直接 React hooks state 没有读取到，不将其伪称为状态级验证。两个实际任务 Source 缓存文件 SHA 与 A 相同；reference Task 的 reference_metadata 实际文件及 reference_provenance fingerprint 与 B 相同，reference_match_status=INSUFFICIENT_EVIDENCE。
EMPTY_RESULT_FAILURE=真实 reference Task=color_e7f6d3324075469e，automatic Task=color_6bd8ce8d079d48b2。两者均 HTTP422 / success=false / failed / Result=null，原因保留原图未生成新文件；落盘 Registry 均为 ACCEPT_ORIGINAL / output_selected=ORIGINAL，result_id 与 output_path 为空。页面按钮恢复，无 pageerror，未伪造成功记录。
RETRY=NOT_VERIFIED_THIS_RUN
REFRESH_BACKEND_FRONTEND_RESTART_DESKTOP_REOPEN=NOT_VERIFIED_THIS_RUN
FEEDBACK_BINDING=两次真实反馈 context snapshot 的 request 与返回 common_context 均为 color_correction / hdde.color.correction / 当前对应颜色 task_id；result_id 为空，无其他功能或历史 Result 串绑。未生成/发送外部反馈；桌面与重启后的复核尚待 D 线完成。

REGRESSION=原 S61-OC-02 基线中的 34 个正式输出路径及 SHA 完全一致；settings/settings.json SHA=7d904536f0c34b9ae8636b378556f733d32c5d23c5e8f1384a5e09f34271f7d5，与基线一致。输出中心、预览 helper、批次合同、压缩/水印 API、Result reuse 及 D61 本轮保护源码/断言前后 SHA 无变化。HEAD、branch、staging 未变化；原 dirty status 项没有消失。

REMAINING_RISK=这对真实 A/B 均安全保留原图，无法用它们证明成功 Result→正式文件输出链。没有调整算法来强制输出。重试、刷新、前后端重启及桌面完整重开最终验收尚待并行 D 线完成；前端全量失败，不能用相关测试通过或 build 成功替代冻结门禁。当前全量失败是精确源码形状断言与 D61 新路由合同冲突，不据此回滚正确反馈路由。

FREEZE_STATUS=D61 未冻结
NEXT=等待已授权协调的 D 线完成桌面及重启验收，并由对应合同维护方处理跨线断言冲突；所有门禁满足后才可返回 S61-OC-02R。

证据目录：output/playwright/d61-ab-acceptance-20261002/。frontend-full.log、python-d61-feedback.log、python-oc-regression.log、build.log、before.json、after.json、real-ab-inputs.json、real-ab-browser.json、real-ab-binding-proof.json、real-ab-*.png 可复核本轮结论。

Skill迭代判断：暂不需要更新；本轮没有形成新的长期规则。
