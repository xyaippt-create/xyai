# S61-OC-05｜输出中心最终独立验收｜2026-10-07

STATUS=BLOCKED

## STAGE_LEDGER

本轮读取真实版本、代码、阶段报告及运行结果。V0.6.1-dev / DEVELOPMENT；branch=`codex/image-processing-routing-v1`；HEAD=`aa0dd93265d270eb5192ebbd44a1fe14488d454a`；staging开始及结束均为空。107个相关源码/测试/阶段资料纳入保护，既有dirty保留。当前无同仓库并行执行任务；性能窗口不存在其他测试/构建负载。

| 阶段 | 既有账本 | 本轮独立复核 |
| --- | --- | --- |
| OC-00 批次合同 | 原报告PASS_AND_FROZEN | 七组49子项26Result和17成功子项绑定通过；新真实压缩/水印各3项通过 |
| OC-01 基础性能 | OC-01R明确冻结 | 正式最新3冷/5暖/20页全部满足门禁 |
| OC-02 缩略图/超大图 | 原OC-02报告BLOCKED；OC-02P后续有冻结声明 | 按用户要求独立重验，不沿用旧结论；本轮全部共享门禁未满足，BLOCKED |
| OC-03 清理 | 原报告明确冻结，源码受保护 | 一般清理通过；同路径新单图Result重启后丢失绑定，BLOCKED |
| OC-04 多轮追踪 | 原报告明确冻结，源码受保护 | 真实既有三轮、子项、恢复、分支及祖先移除后重启通过 |
| D61 | 原D61-06报告明确冻结，源码受保护 | 当前邻接反馈测试1项失败；既有严格检查与旧夹具不一致 |

现有冻结报告保留，本轮不据其声明最终通过。

## OC_02_CLOSEOUT

S61-OC-02=BLOCKED。

缩略图、超大图片、完整重启、性能及资产保护均取得本轮独立通过证据；输出相关Python及前端全量通过。但最终共享源码的相邻反馈测试未全绿，且OC-03同路径重启绑定缺陷阻断输出中心正式合同，因此不能声称OC-02本轮全部共享门禁通过，也不能新增总冻结结论。

## FILES_MODIFIED

产品源码、已有测试、settings、dist修改均为0；新增本报告、独立 `output/playwright/s61-oc-05-20261007/` 证据及必要changelog追加。没有Git写操作。

## TESTS

| 验证 | 本轮结果 | 证据 |
| --- | --- | --- |
| tests/output 当前完整Python | 38/38，ExitCode0 | python-output.log |
| 输出列表/批次/水印/清理/记录删除/品牌 | 64/64，ExitCode0 | python-contracts.log |
| D61颜色/参考/稳定性及相邻反馈 | 执行73项，72通过、1失败 | d61.log、test-receipts.json |
| 反馈V3相邻补集 | 7/7，ExitCode0；两组共80项79通过1失败 | d61-feedback-v3.log |
| 当前前端全量 | 382/382，fail/cancelled/skipped/todo均0 | frontend.log |
| production build | ExitCode0，输出到独立目录；原dist不变 | production-build.log、test-receipts.json |

失败为 `tests.diagnostics.test_unified_feedback.UnifiedFeedbackContractTests.test_task_snapshot_does_not_drift_and_bundle_is_self_contained`，第198行期望200，实际409。请求确实来自颜色校正，但手工夹具仅有嵌套 `task_context.feature_key`，没有顶层Task.feature_key，触发 `main.py:4894` 既有D61检查。与OC-04修改前main字节对照，该检查完全相同；OC-04新增的Task-ID冲突检查未触发。准确归属为D61/诊断反馈测试夹具与当前严格合同不一致；本轮没有改断言、补字段、弱化生产检查或跳过。见 `feedback-failure-attribution.json`。

## BATCH_COMPRESSION / BATCH_WATERMARK

新隔离根使用真实照片输入，实际生成压缩3项、水印3项，两批分别一张父卡、展开3子项。各批1个所属文件被移动到隔离held位置模拟缺失，仍保留真实Result身份；其余成功子项真实打开文件/目录、intake续编，返回的Task/Result/SHA均对应具体子项，原批次统计和子项数据未变。

另外独立只读复核七组历史真实矩阵：压缩3/10/混合JPG-PNG-WebP、水印3/10及错误/取消场景，总49子项、26个成功且唯一Result。failed、取消、KEEP_ORIGINAL保持无伪造Result/输出；总字节统计、全部九字段、顺序及重启后关系保持。真实Edge选择17个成功子项未串绑，未用父Task冒充子Result。见 `bindings-recheck.json`、`selection-recheck.json`、`batch-actions.json`、`images-*.json`。

## THUMBNAILS / LARGE_IMAGES / MISSING_FILES

在新隔离图片根重新验证8种真实文件：JPG、PNG、透明PNG、WebP、3840×2160、6000×4000、10000×10000（100MP）、18000×10000（180MP）。六种预算内缩略图实际解码，最大边≤768；透明PNG Alpha保持(80,80)。两种超预算文件thumbnail返回422，原文件存在、卡片保留、明确“预览不可用”，没有假Result。真实缺失单图及批次子项显示缺失状态，按钮按真实文件状态工作，无空白卡片或页面异常。

实际损坏本轮所属缓存后MISS重建，并解码确认有效；把本轮缓存目录暂存并替换为已知故障哨兵，实际返回422；真实原生桌面保留卡片，正常结果仍可打开、打开目录与继续编辑。故障哨兵已精确移除，原缓存恢复，输出SHA不变。缓存探针最初误读公开卡片路径字段，修正的是独立验证脚本，失败记录保留，未改产品。

刷新、两轮独立前后端停止重启、三个新EdgeChromium原生窗口均重验100MP/180MP及正常、失败、缺失状态。17次列表请求完整像素解码次数为0，目录状态每请求一次；运行进程记录的Pillow全局上限始终89,478,485，缩略图仍按需/限量/缓存。见 `oc02-decoding-proof.json`、`images-*-requests.jsonl`、`native-images-*.json`、`cache-fault.json`。没有完整解码超大源图或关闭全局限制来制造通过。

## LIST_CLEANUP

新隔离根中实际生成当前/历史两组单图、压缩、水印，共16真实Result。单卡、子项、部分/全部缺失、两个域分别清空、最后子项移除后空批次消失、详情取消选择、刷新/重启不回流均通过；四轮服务生命周期及四个原生窗口复核通过。故意缺失仅移动所属副本至held，全部原字节保留。

额外真实水印3项试验刻意暂缓后续列表GET，首个移除响应即更新子项/标题/详情，清空即空状态；`counts-ui.json`记录通过。

**同路径新Result门禁失败，真实产品缺陷归属OC-03。** 从已清理的历史单图取真实Source，在隔离根移动原输出保留字节，再运行原压缩API，真实获得新Task/Result且正式路径相同：

- 旧Task=`compression_35da95192543428a`；旧Result=`compression_result_36201817bf8c44ee`。
- 新Task=`compression_18751e61a16b48f3`；新Result=`compression_result_7c35b4f7c4da49ba`。
- 新Result当轮卡片绑定正确，available/unified_result均true。
- 完整后端重启后，同一张卡的task_id/result_id均变空，unified_result=false；真实文件、新Task事实及SHA仍有效。

`SharedTaskRegistry._commit`使用sort_keys（第75行），重载后同路径的 `output_center_hidden` 移除事实排在新Task后。`backend/image_compression_api.py:763` 的 `output_center_active_records` 未排除该事实；第866行把它作为路径详情覆盖了真实新Task。列表仍有文件卡片，错误在身份/续编绑定，不是文件丢失。原输出held副本和新文件SHA均为 `39297f44cf043254b5138fba0cd3854e9f815883e1053300754b69c456f5ace4`，都实际存在。证据：`same-path-create.json`、`same-path-restart.log`、`same-path-restart-defect.json`。本轮不修复生产代码。

## MULTI_ROUND_LINEAGE

复制OC-04真实10输出及合法Registry事实到新的所属隔离根，逐字节SHA一致，明确记录这是已有真实链的复核，未伪造新执行Result。当前源码实际重验压缩→水印→压缩三轮、批次具体子项分支、中间failed/null后恢复、并行两分支；每条续编输入SHA等于父Result SHA，路径/Task/Result独立，历史10文件不变。

两张真实浏览器页面刷新/重新intake绑定各自Result/Task，令牌不同；既有实际反馈ZIP分别只包含各自Task。完整服务和原生桌面重开保持三轮顺序。副本目录改变了路径派生列表ID，验证脚本从持久Result的真实路径精确定位祖先，再实际移除列表记录；下游仍显示、打开、继续编辑，重启后三轮及10文件SHA不变，没有按文件名或时间猜关系。见 `lineage-*.log`、`native-oc05-*.json`、`lineage-ancestor-removal.json`、`branch-pages-after-restart.json`。

## DESKTOP_RUNTIME / PROCESS_CLEANUP

正式开发版production + Edge Chromium WebView2连续5轮正常启动、页面刷新、切换处理中心及返回、前进/后退、完整WM_CLOSE退出重开均通过。每轮依据本次Popen树的PID/create_time识别所属启动器、后端和WebView前端，正常退出ExitCode0、residual=[]，没有按进程名误杀其他实例。原共享正式启动器经其正常退出事件关闭，最后恢复8787/5173正式服务，根仍为 `D:\影界文件`，实际加载原当前dist构建。没有后台服务留置冒充完整退出。

## PERFORMANCE

测试、构建、隔离运行均结束后才开始测量；其他验收端口空闲，无测试/构建进程，5轮开始时CPU约6–8%，负载记录和原始样本全部保留。未重新抽取失败样本或只选最好值。冷屏为清浏览器缓存后的输出页首12卡绘制，不外推整个软件启动时间。

- 连续3次冷首屏：931.8 / 922.7 / 931.8ms，全部≤1000；第4/5完整重开另记935.9 / 927.5ms。
- 连续5次暖重开：382.1 / 378.6 / 378.8 / 397.0 / 380.9ms，全部≤800。
- 连续20次分页：105.3 / 76.1 / 59.0 / 60.0 / 60.8 / 98.9 / 62.4 / 93.4 / 60.7 / 78.7 / 96.6 / 61.2 / 62.9 / 62.3 / 77.0 / 98.1 / 62.4 / 62.1 / 61.7 / 59.9ms。
- nearest-rank P95=98.9ms≤150；max=105.3ms≤200。
- 批次展开16.5ms≤100；5轮刷新916.6 / 919.4 / 926.1 / 926.3 / 932.4ms，全部≤1000。
- 每轮首12卡完整无重复、初始列表请求1次、缩略图峰值4；四次完整分页遍历各157卡无重复。

`performance-summary.json`、`formal-1..5-gate.json`、`formal-1..5-close.json`、`formal-window-load.json`为本轮原始证据。OC-04早期163.8ms样本留在原目录，不沿用旧3887ms，也未混入本轮独立连续20次样本。

## ASSET_INTEGRITY / REGRESSION

原34个基线输出、当前49个既有输出、51输入及settings逐文件SHA保持；settings=`7d904536f0c34b9ae8636b378556f733d32c5d23c5e8f1384a5e09f34271f7d5`。107个受保护相关文件及原dist全部保持（仅必要changelog追加另列）。Branch/HEAD/空staging及既有dirty保留，没有commit/push/reset/checkout等Git写操作。

新增及复制的48份验收图片独立登记、SHA核验，缺失模拟后的held副本全部保留：图片根16份、清理根22份、真实链副本10份。同路径旧文件在held处核验，未覆盖原字节。正式用户Root未用于清理、故障或新处理演练。见 `baseline.json`、`integrity-final.json`、`cleanup-file-protection.json`、`git-status-final.txt`。

## REMAINING_RISK / FREEZE_STATUS / NEXT

阻断1：OC-03同路径新单图Result在重启后被移除事实覆盖详情身份，真实复现，不能最终冻结。

阻断2：D61/诊断反馈旧夹具缺顶层feature_key导致相邻测试409；当前生产检查在OC-04前已经存在。需在独立最小修复阶段按正式合同处理测试兼容性，本阶段未为清零修改正确代码。

FREEZE_STATUS=V0.6.1输出中心未最终冻结；S61-OC-02本轮BLOCKED。其他既有冻结成果受保护，不以局部门禁通过替代最终通过。

NEXT=另开OC-03同路径重启身份绑定最小修复阶段；随后处理反馈测试契约并重新执行OC-05。当前验收阶段停止开发，不进入安装包或新功能。

Skill迭代判断：暂不需要更新。
