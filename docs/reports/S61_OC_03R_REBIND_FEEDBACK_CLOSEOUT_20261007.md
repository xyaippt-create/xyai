# S61-OC-03R｜同路径重建绑定与反馈合同收口

## S61-OC-03R1｜2026-10-15 当前冻结复核

STATUS=PASS_AND_FROZEN
ROOT_CAUSE=此前硬门禁错误要求批量压缩复用已占用的最终文件名，与冻结的持久路径预留/碰撞避让合同冲突；本轮按用户明确决策废止该门禁。OC-03R已有详情身份修复和顶层feature_key夹具修复保留。
CONTRACT_DECISION=相同来源与目录、新身份、新文件路径、旧文件不覆盖
FILES_MODIFIED=tests/output/test_same_path_rebind.py、本报告、docs/09_CODEX_CHANGELOG.md；独立证据目录output/playwright/s61-oc-03r1-20261015/。
PRODUCTION_CODE_CHANGED=NO。当前252份受保护源码/阶段文件登记；生产源码、前端、批次写入器、算法、Pillow策略、原dist及已有反馈修复均未改动。

BATCH_COMPRESSION_REBIND=真实照片派生PNG作为固定输入，在新隔离根首次批量压缩3张成功→整批移除输出中心记录→3个旧文件原位保留→重新上传相同来源文件、相同文件名并使用相同输出目录→3张成功新批次。新文件自动使用_02后缀，未释放或改写任何预留。随后刷新、3轮前后端重启及原生WebView完整退出重开全部通过。

OLD_FILE_PROTECTION=初次3个成品保留原路径，每个文件SHA从移除前到续编/所有重启后均不变；来源文件亦不变。只持久保存列表移除事实，不删除、移动、覆盖旧输出或清空移除表。

NEW_IDENTITY_BINDING=新Batch、Source、Task、Batch Item、Result和输出路径均独立。新批次始终只有一张卡、展开3个COMPLETED子项，九字段合同一致、无重复Result；首次scope=current，服务重启后scope=history。旧卡不回流，旧事实不清空新详情。缩略图实际解码、原生界面缩略图加载、具体子项详情选择、打开文件、打开目录及UI继续编辑都通过。

选中子项旧Task=`compression_923c713ba950484e`，旧Batch Item=`bbd1703a51064e34bfe5936fdc90d447`，旧Result=`compression_result_a2f6b67c7e7e4ef6`；新Task=`compression_8dd0114feaa84a3c`，新Batch Item=`0cfd1af65028495fb22ba47525ff56bd`，新Result=`compression_result_60898b38eb60475b`。输入源SHA=`2e7c4fb559a8e8a8573aa544b0eb2a8019b05610bb60d318e17b3dd81adcb460`，父输出SHA=`8eb033b92b12a83f9b6110b62516b370c3d3507643bc0fd4fec639fa48598ab4`。成功续编Task=`compression_8ea4903064234a0a`，Result=`compression_result_5579ccbd6f634cb6`，输入文件实际SHA等于父Result SHA，父链在后两轮重启后保留。完整三对子项、路径和SHA见runtime-cases.json。本轮8个实际Result均单独登记在隔离根，包含初/重建6个及后续处理2个，不进入正式基线。

TESTS=输出41/41；输出/批次/清理/水印等合同64/64；D61及反馈81/81；前端382/382，fail/cancelled/skipped/todo均0；production build ExitCode0，产物写入本轮独立目录。既有反馈feature_key正负校验未放宽。真实处理器测试仅对齐压缩分支：旧文件原位保留，断言新路径不同但目录相同、Task/Batch Item/Result不同、旧SHA不变；修正了“重启释放预留”的错误注释，未改水印与单图合同。

REAL_RUNTIME=当前共享源码真实接口及原生EdgeChromium/WebView2；初始刷新加3轮前后端重启/窗口完整重开，真实续编请求绑定选中Result/Task及SHA。正式D:\影界文件开发版另执行3轮启动、刷新、前进/后退/路由返回及正常退出。
PROCESS_CLEANUP=正式桌面3/3正常WM_CLOSE，ExitCode0、每轮residual=[]。按本轮Popen进程树PID/create_time确认归属，无按名称误杀。各隔离服务所属树也无残留。进入本轮时正式服务未运行，结束后保持关闭状态。

PERFORMANCE=正式原生桌面、无测试/构建负载窗口：冷3次 943.0 / 935.0 / 935.0ms；暖5次 361.6 / 373.2 / 367.2 / 347.0 / 356.9ms；分页20次nearest-rank P95=98.9ms、max=99.0ms；展开24.2ms；刷新926.0ms。全部满足1000/800/150/200/100/1000门禁。其余两个桌面刷新原始值也保留在formal-2/3-gate.json。首屏12卡完整、身份唯一，每轮首屏列表请求1次、缩略图并发峰值4；当前正式列表39卡，按真实页数循环取得20个有效分页样本，不为测量增加正式记录。

早期脚本假设错误均保留：沙箱执行限制、续编按钮key/查询参数/返回等待、Task输入SHA字段位置，以及从旧157卡沿用5页遍历导致超时。修正仅涉及本轮验证脚本，未改生产代码。首次页数探针的冷940.0ms、暖380.5/348.7/191.0/389.6/407.6ms、分页104.7ms原始记录未删除；其窗口正常关闭且无残留。最终完整样本不是选择性丢弃超标值，前期已测得时间同样在门禁内。

REGRESSION=七组49子项、26个唯一成功Result的九字段和批次统计全部不变；17个既有成功子项界面详情/续编资格只读复核通过，页面错误及写请求均0。失败、取消、KEEP_ORIGINAL不产生虚假Result的合同测试保持通过。
ASSET_INTEGRITY=原34/当前49输出、51输入、settings、48份既有隔离文件SHA全不变；额外保护此前OC-03R的16个Result文件。settings SHA=`7d904536f0c34b9ae8636b378556f733d32c5d23c5e8f1384a5e09f34271f7d5`。受保护dirty保留，branch=`codex/image-processing-routing-v1`，HEAD=`aa0dd93265d270eb5192ebbd44a1fe14488d454a`，staging为空，无Git写操作；无正式目录测试垃圾。
REMAINING_RISK=本阶段无未完成门禁。当前仅冻结OC-03R；S61-OC-05须基于当前共享状态独立重跑，其他阶段门禁不能由本报告代替。
FREEZE_STATUS=S61-OC-03R已冻结
NEXT=独立重跑S61-OC-05最终验收
REPORT_PATH=docs/reports/S61_OC_03R_REBIND_FEEDBACK_CLOSEOUT_20261007.md

证据目录：output/playwright/s61-oc-03r1-20261015/。关键文件：baseline.json、test-contract.diff、test-receipts.json、runtime-cases.json、after-refresh/after-restart-1..3-snapshot.json、native-after-restart-1..3.json、continued-success.json、bindings-recheck.json、selection-recheck.json、formal-1..3-gate/close.json、performance-summary.json、integrity-final.json、final-closeout.json。

Skill迭代判断：暂不需要更新。

---

## 2026-10-07 历史执行记录（保留；旧同名输出门禁已被上方OC-03R1决策替代）


STATUS=BLOCKED

## ROOT_CAUSE

本轮真实基线仍为V0.6.1-dev / DEVELOPMENT，branch=`codex/image-processing-routing-v1`，HEAD=`aa0dd93265d270eb5192ebbd44a1fe14488d454a`，staging为空、已有dirty受保护，无同仓库并行修改。

修改前新隔离运行实际生成父Result、旧单图、移除记录、同路径新Task/Result；新Task、输出SHA、source_path及source_result_id/source_task_id始终持久存在。刷新后的接口和原生完整重开实测卡片Task/Result为空，而水印新子项仍正确。解绑发生在后端详情映射，不是Registry事实丢失、前端选择或缩略图缓存。`output_center_hidden`仍带旧路径，排序重载后被`output_center_active_records`当作真实Task/Result覆盖路径详情；同一事实还会覆盖当前/历史scope。

旧反馈夹具只在task_context保存feature_key；当前D61合同以顶层Task.feature_key为权威。修改前独立探针确认合法200、缺Task字段409、错误Task/目标功能409、未知/缺目标枚举400、Result冲突409，生产校验没有真实缺陷。首次探针把未知枚举image_processing误期待409，400拒绝本身正确，原探针记录保留。

## FILES_MODIFIED

- `backend/image_compression_api.py`：仅4行，两处排除output_center_hidden参与详情和scope映射。
- `tests/diagnostics/test_unified_feedback.py`：既有夹具仅补顶层feature_key及注释；新增一项含7个正负子场景的合同回归，原断言保留。
- `tests/output/test_same_path_rebind.py`：新增3项真实处理器/持久Registry回归，覆盖单图父链、历史移除、刷新/重载、水印子项、压缩路径预留控制、最后子项、不同路径和failed/null隔离。
- 本报告、changelog追加和 `output/playwright/s61-oc-03r-20261007/` 独立证据。原dist、图片算法、批次写入器、Registry schema、前端和Pillow策略均未修改。

## IDENTITY_CONTRACT

继续使用既有removed_result_id、batch_item:batch_id:batch_item_id以及批次ID作为移除身份；路径只用于已有文件索引/元数据连接，不新增永久身份体系。新Result身份与旧Result不同，旧移除事实继续留在Registry并作用于旧身份；没有清空移除表、恢复旧卡、绕过持久状态或路径特判。

移除事实属于列表可见性，不能注册Result、成为文件详情或指定scope。历史数据沿用既有读取/可见性合同，不迁移、不改schema；匿名旧标记继续保守保持隐藏，不猜测Result归属。新增回归验证历史标记仍隐藏旧记录，合法不同路径与失败不串绑。清理仍只改变列表事实，来源、父链和输出记录保留。

## SAME_PATH_REBIND

实际单图：旧Result=`compression_result_0dedf10ef3244ffd`；新Result=`compression_result_bce1d6af1430448a`，输出路径完全相同，Task/Source独立，父Result保留。

实际水印子项：旧Result=`watermark_result_92aac8c7074944d8`；新Result=`watermark_result_cbb82c9c4f1c416b`，输出路径完全相同，具体子项Task/Result绑定正确；其他旧子项文件保留。

这两类修复后刷新、前后端重启和三次新原生窗口完整退出重开均保持详情/状态/Source及续编；旧记录不回流。新单图Result实际继续压缩，产生第三轮Result=`compression_result_75c3475baa984aad`，source_result_id指向新单图，输入SHA等于父输出SHA。

**批量压缩“同路径新子项”硬门禁未满足。** 冻结写入器 `backend/batch_compression_api.py:174-179` 和 `reserved_outputs:269` 对旧prepared.target持续预留；文件缺失也生成_02新路径。尝试既有父Task清理API不能移除compression_batch事实或释放预留，未声称释放成功。实际新子项=`compression_result_d187c9360f3542b7`使用新路径，只是身份隔离控制，不冒充同路径通过。用户本轮明确确认“保持原门禁：该项无法完成则BLOCKED”；未修改写入规则、伪改Result路径、清空预留/移除表或改算法。

证据：`before-restart-snapshot.json`、`native-before-full-reopen.json`、`after-restart-1..3-snapshot.json`、`native-after-*.json`、`continued-success.json`、`compression-reservation-evidence.json`。早期脚本的字段/编码/预留假设错误独立保留，修正的是验证脚本，不作为产品PASS。

## FEEDBACK_CONTRACT

既有反馈测试保持期望200、快照不可漂移及ZIP隐私/完整性断言，仅补当前正式Task字段。7个新子场景覆盖合法、缺顶层字段、错误Task功能、合法但跨功能目标、未知/缺目标功能和Result冲突；仍由原生产逻辑返回200/409/400。`main.py`与所有D61生产代码SHA未变，没有放宽校验、删除测试或skip。

## TESTS

| 当前验证 | 结果 | 证据 |
| --- | --- | --- |
| 输出中心tests/output全量 | 41/41，ExitCode0 | python-output.log |
| 输出列表/批次/清理/水印等合同 | 64/64，ExitCode0 | python-contracts.log |
| D61及完整反馈邻接 | 81/81，ExitCode0 | d61.log |
| 前端全量 | 382/382，fail/skip/cancelled/todo均0 | frontend.log |
| production build | ExitCode0，独立目录 | production-build.log |
| 两阻断直接回归 | 14/14；名称明确区分水印同路径和压缩预留控制后的3项再次通过 | targeted-final.log、rebind-name-final.log |

未用测试全绿替代未满足的压缩真实同路径门禁。

## REAL_RUNTIME / PROCESS_CLEANUP

新运行根 `C:\Users\xyppt\.codex\visualizations\2026\09\21\01a0c410-c6b2-7562-a3e5-2a0588993e30\s61-oc-03r-runtime-20261007-r2` 显式配置独立压缩输出根；真实照片输入形成父链和三类验收数据。旧字节仅在本轮临时验收根保留至owned-prior-bytes，不移动任何既有正式输入输出或OC-05的48份文件。

三轮独立前后端/原生重开复核单图、水印正确同路径绑定及压缩新路径控制；真实打开文件、打开目录及intake SHA均正确。16个本轮登记Result字节全部保留；首轮预留假设不成立的运行目录保留，不删除未知文件。

正式开发版production/WebView2另外正常关闭重开3/3，ExitCode0、所属进程residual=[]，仅依据当前Popen树PID/create_time处理；原共享正式启动器经正常退出事件停启，结束恢复8787/5173正式服务及原dist。没有按进程名误杀共享或其他实例。

## PERFORMANCE

测试/构建/隔离服务结束后，无并行测试负载测量当前修复后的正式后端和原production前端：

- 冷首屏928.6ms；另两次938.2/922.0ms，均≤1000。
- 暖重开374.6 / 371.6 / 372.6 / 371.7 / 359.4ms，均≤800。
- 20次分页nearest-rank P95=98.4ms，max104.0ms，满足150/200门禁。
- 展开16.9ms；刷新929.5ms，满足100/1000门禁。
- 首12卡完整无重复、初始列表请求1次、缩略图峰值4、完整遍历157卡无重复。

原始全部样本、正常退出和负载记录为`formal-1..3-gate.json`、`formal-1..3-close.json`、`performance-summary.json`。未优化性能方案或整个软件启动。

## REGRESSION / ASSET_INTEGRITY

七组49子项、26个既有成功且唯一Result，统计及九字段绑定不变；17个成功子项真实界面选择/续编核对通过，见`bindings-recheck.json`及`selection-recheck.json`。

原34基线输出、当前49输出、51输入、settings及OC-05的48份隔离文件SHA全部不变；settings=`7d904536f0c34b9ae8636b378556f733d32c5d23c5e8f1384a5e09f34271f7d5`。原dist保持；其余受保护源码/冻结报告保持，dirty保留、branch/HEAD不变、staging为空，无Git写操作。验收没有向正式D:\影界文件新增测试输出。见`baseline.json`、`integrity-final.json`、`scoped-production-and-fixture.diff`。

## REMAINING_RISK / FREEZE_STATUS / NEXT

代码层的同路径详情覆盖和反馈夹具冲突已修复且测试/相应真实链通过。剩余硬门禁是批量压缩的新子项无法在冻结预留规则下合法复用旧路径。本轮遵照用户明确决定维持BLOCKED；不把压缩新路径控制当作同路径成功，不扩大为修改批次写入器或数据合同。

FREEZE_STATUS=NOT_FROZEN

NEXT=明确批量压缩同路径重建门禁与冻结路径预留合同的处理方式；当前修复保留，门禁收口后另行重跑OC-03R及S61-OC-05。不得宣布V0.6.1输出中心最终冻结。

REPORT_PATH=docs/reports/S61_OC_03R_REBIND_FEEDBACK_CLOSEOUT_20261007.md

Skill迭代判断：暂不需要更新。
