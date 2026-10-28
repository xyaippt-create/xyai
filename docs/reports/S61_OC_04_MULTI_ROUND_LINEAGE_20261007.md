# S61-OC-04｜多轮编辑与结果追踪｜2026-10-07

STATUS=PASS_AND_FROZEN

## ROOT_CAUSE

真实复现并保存于 `output/playwright/s61-oc-04-20261007/reproduction.json`：删除上游处理中心 Task 时，保留 Result 的顶层 `source_result_id` 丢失，`source_task_id` 被自身 Task 覆盖，虽然嵌套任务结果仍有真实父边。已有继续编辑能够创建独立输入和结果，但没有用户可读的持久编辑链查询。旧复用检查只检查 completed，未拒绝待确认的 REVIEW_REQUIRED。

两条真实并行分支还复现了反馈请求外层 Task A 与 feedback_target Task B 冲突时返回200并采用B；当前明确冲突返回409。没有修改反馈功能路由或图像算法。

基线：V0.6.1-dev / DEVELOPMENT；branch=`codex/image-processing-routing-v1`；HEAD=`aa0dd93265d270eb5192ebbd44a1fe14488d454a`；staging为空。开始/结束均真实读取；既有dirty视为受保护基线，未执行任何Git写操作。当前聊天独占本轮修改与桌面验收。

## FILES_MODIFIED

- `engine/storage/result_reuse.py`：复用已有唯一Result解析，按需投影编辑链，状态/相邻SHA/Task/循环校验。
- `engine/storage/shared_task_registry.py`：保留已有Result父边，防止移除Task后覆盖来源身份。
- `backend/image_compression_api.py`：按需编辑链查询；继续编辑资格与正式复用状态检查一致。
- `src/OutputCenterPage.jsx`：继续编辑入口、按需查看编辑链；选择序列校验防止迟到响应串绑。
- `main.py`：两行反馈显式Task冲突拒绝检查。
- 新增 `tests/output/test_result_lineage.py`、`tests/output/test_lineage_feedback.py`；修改 `tests/output/test_continue_processing.py` 的两个旧断言及 `tests/image_compression_ui/test_output_center_ui.mjs` 的一项新增契约测试。
- 本报告、`docs/09_CODEX_CHANGELOG.md`、当前production `dist`及本轮独立证据。旧dist全部文件原字节保存在 `output/playwright/s61-oc-04-20261007/dist-before/`。

## IMPLEMENTATION / LINEAGE_CONTRACT

继续沿用 `continue_result=<Result ID>` 和正式 intake-result 桥接，服务端核验唯一 Task、正式路径、SHA、状态及目标处理器资格。每次intake创建独立输入快照/令牌或水印Source缓存，新执行仍由原处理器生成新Task/Result和独立正式文件。

复用既有 `source_origin / source_result_id / source_task_id / source_feature_key / source_result_sha256`。首轮Source由该轮Task持久的source_path、source_metadata/source_sha定位；已有source_id原样保留，旧单图记录没有source_id时不补造另一套ID。轮次由父Result边计算，不另存重复轮次或归组字段。失败缺边、SHA/Task冲突或循环明确报错，不按文件名或时间补链。

GET `/api/output-center/results/{result_id}/lineage` 仅在用户点击查看时读取Registry元数据，不完整解码图片、不扫描祖先文件、不阻塞首屏。当前叶Result必须真正completed且已被接受；待确认/拒绝结果、KEEP_ORIGINAL及无输出决定不能伪装成功复用。失败/取消仍由冻结处理器保持无Result。本阶段不改变发布或算法决定。

OC-03移除只影响列表；上游Source/Task/Result事实和文件保留，下游可照常打开、查询与续编。列表清理、九字段批次、分页和缩略图安全语义未变。

## SINGLE_CHAIN

使用真实照片 `D:\定制业务\学校定制\照片s\Image_1781401250990_757.jpg` 的隔离960边长PNG输入；原照片SHA=`e39d47bbe5dcf9a9366056aaf3e05c99e2e0bc7213672875b5084221285e282c`。真实执行器及真实浏览器依次执行压缩→水印→压缩：

| 轮次 | Task | Result |
| --- | --- | --- |
| 1 | compression_d671d360464641a2 | compression_result_420f0a5429b44c69 |
| 2 | watermark_f28074106b8c4f7a | watermark_result_11bba83e4f6d448b |
| 3 | compression_bb8913bdea1d4d7d | compression_result_2faacd8db5a54d71 |

三轮成功文件独立、真实解码有效。第2/3轮输入SHA等于前轮Result SHA。页面刷新后三轮顺序和初始Source保持；源码集成测试还真实删除中间Task，保留Result仍完整追踪。`cases.json`、`three-round-ui.json`、`integrity-final.json`保存完整SHA与路径，`lineage-final-page.png`保存实际界面。

## BATCH_CHILD_CHAIN

真实3项压缩批次选择第2个成功子项，进入水印得到 Task=`watermark_bfb641d496d24505`、Result=`watermark_result_8fb6c89adae346a8`。父身份核对具体子项Task/Result，未使用批次父Task。原批次全部九字段和summary在后续、刷新与每轮重启完全一致，其他子项未修改。单图三轮中的水印结果也是正式单子项批次，继续压缩绑定该具体Result。

## FAILURE_RECOVERY

从第2轮成功Result真实执行1字节上限的UPLOAD_ADAPTATION，Task=`compression_c10ad0a1fe234bc6`实际failed，Result ID为空、无正式Result事实及文件。再从同一成功Result继续水印，Task=`watermark_1f2513d023b9436c`、Result=`watermark_result_f1527ce2ff9d4493`成功。之前全部成功文件SHA不变。

## BRANCH_ISOLATION

第3轮Result同时发起压缩和水印：`compression_6282adf5a0af4d31 → compression_result_fbf6d2127ed848ef`；`watermark_b68e964a9cf3419c → watermark_result_852d2207574e4576`。输入快照、Task、Result及路径独立，两边均指向共同的正确父Result。两张真实浏览器页面刷新/重新intake仍绑定各自Result，source_token不同。

两份真实反馈ZIP已下载、CRC校验、读取feedback.json，各自包含本分支Task，不包含另一分支Task；显式外层/内部Task冲突返回409，修改前200证据保留。见 `complete-runtime-final.log`、`branch-pages-after-restart.json`、`feedback-*.zip`、`integrity-final.json`。

## TESTS

| 验证 | 当前结果 | 证据 |
| --- | --- | --- |
| tests/output 当前完整Python | 38/38，ExitCode0 | python-output-all-byte-final.log |
| 输出列表/清理/批次/水印/记录删除/品牌 | 64/64，ExitCode0 | python-contracts-final.log |
| D61及颜色/反馈相邻Python | 70/70，ExitCode0 | d61-final.log |
| 当前前端全量 | 382/382，fail/cancelled/skipped/todo均0 | frontend-byte-final.log |
| production build | 通过，最新dist实际加载 | production-final.log、production-newline-check.log、restored-formal-ready.json |

两个旧断言先用修改前API字节稳定复现：把批次父卡当单图Result；颜色保留原图决定强制期待200成功。仅对齐冻结OC-00批次结构和D61 failed/null合同，未修改算法或减少测试。旧失败见 `preexisting-assertion-evidence.log`。

最终范围审计恢复三个本轮文件原有行尾约定，未改变执行逻辑；随后完整38项/382项及production构建通过。实际正式JS SHA与dist完全一致，恢复行尾后的重建入口程序在仅规范生成的asset引用哈希和build时间戳后完全相同，已有运行/性能证据对应当前逻辑。见 `scoped-newline-audit-final.json`、`served-production-asset.json`、`output-ui-build-equivalence.json`。截图脚本的相对URL/页面淡入时机错误单独保留，修正的是验证脚本，不是产品代码。

## REAL_RUNTIME

独立验证根为 `C:\Users\xyppt\.codex\visualizations\2026\09\21\01a0c410-c6b2-7562-a3e5-2a0588993e30\s61-oc-04-runtime-20261007`，明确配置压缩输出根。10个新增验收输出逐文件登记、解码和SHA核验，不混入正式49输出。

至少三轮独立前后端服务停止/重启和三个新EdgeChromium原生桌面完整退出/重开，均复核三轮顺序、批次子项、失败恢复、分支、文件SHA、真实打开文件/目录和继续编辑；压缩页刷新仍可从选定Resultintake。移除初始Result列表记录后，下游保持显示/打开/续编，编辑链保持原样。所有所属验收服务回收无残留；不以Mock或HTTP200替代实际文件证明。

正式根仅用于只读界面/性能和正常启动退出。原正式启动器经正常退出事件关闭，验收使用真实production/WebView2后正常WM_CLOSE，最终恢复正式8787/5173服务，根仍为 `D:\影界文件`，新构建 `V0.6.1-dev+aa0dd93265d2.dirty.20261007T023302122Z` 已加载，首12卡无重复。

## PERFORMANCE

所有无埋点测量保留于 `oc04-final-gate.json`、`oc04-confirm-gate.json`，合并统计为 `performance-all-unwrapped.json`。首轮十页P95/max=163.8ms，单轮失败如实保留，不用正常退出PASS替代性能门禁。

为确认归属，独立诊断脚本分段计时并从已保存的修改前API/production字节进行只读对照，没有回滚共享源码。当前新增状态检查每页约0.01–0.02ms；慢页集中在目录状态及路径解析/探测，Registry只在启动读盘、列表无pixel_decode、目录状态每请求一次；修改前对照十页P95=113.2ms。该次波动的更深环境归因仍NOT_YET_CONFIRMED，未借此豁免门禁或改冻结性能代码。

固定执行最后一轮当前源码无埋点复测：

| 门禁 | 最后完整测量 |
| --- | --- |
| 冷首屏≤1000ms | 926.4ms（首轮933.1ms） |
| 暖重开≤800ms | 381.6 / 379.8 / 381.8 / 377.0 / 379.3ms |
| 分页P95≤150ms | 最后10次P95/max=129.4ms；全部20次nearest-rank P95=129.4ms，最大163.8ms，包含早期失败样本 |
| 批次展开≤100ms | 17.6ms |
| 首屏/翻页完整性 | 首12卡完整；两轮各遍历157卡，无重复，初始列表请求各1次，无提前后页请求 |
| 刷新及预览加载 | 刷新921.3ms；缩略图并发峰值4；无页面异常 |

埋点/修改前回放仅用来诊断，不混入正式无埋点性能样本；冷首屏为清浏览器缓存后的输出页首卡绘制，不声称整个软件启动耗时。

## REGRESSION

七组49子项、26个成功且唯一Result的九字段及统计不变；真实浏览器17个成功子项选择/继续处理复核只发GET、无串绑。证据 `bindings-recheck.json`、`selection-recheck.json`。

原34输出、当前49正式输出、51原图/真实A-B及settings逐文件SHA全部不变；settings仍为 `7d904536f0c34b9ae8636b378556f733d32c5d23c5e8f1384a5e09f34271f7d5`。新10输出、10个不同Source输入路径及6条实际继续编辑边全部解码/SHA核验。算法、批次持久合同、清理语义、Pillow安全限额、缩略图队列和D61启动器等其余54个受保护相关文件SHA保持。保护dirty、branch、HEAD、空staging不变。

## REMAINING_RISK

较早存在一次163.8ms分页波动，完整样本及最后固定复测满足当前P95门禁，但其更深环境来源未确认，应在OC-05继续观察。历史缺失来源摘要/冲突/循环不会猜测补链；超64轮拒绝继续追踪并明确报错。旧单图没有source_id时使用已有Task所属Source事实定位，未迁移旧身份或创建重复体系。

没有开发新图片能力、调整算法/阈值、优化整个软件启动、制作安装包或Git写操作。Skill迭代判断：暂不需要更新。

FREEZE_STATUS=S61-OC-04已冻结

NEXT=进入S61-OC-05最终验收。
