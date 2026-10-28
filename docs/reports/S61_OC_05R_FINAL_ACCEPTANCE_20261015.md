# S61-OC-05R｜V0.6.1输出中心最终独立验收｜2026-10-15

STATUS=PASS_AND_FROZEN

## STAGE_LEDGER

真实版本0.6.1-dev / V0.6.1开发版 / DEVELOPMENT；branch=`codex/image-processing-routing-v1`；HEAD=`aa0dd93265d270eb5192ebbd44a1fe14488d454a`。当前无同仓库并行执行任务；staging开始/结束均为空。252份相关源码、测试和既有阶段资料纳入保护，当前dirty原样保留。本轮只验收，未修改生产代码、测试、settings、版本、算法、命名/预留、批次合同、性能方案、缩略图策略或原dist；未制作安装包。

| 阶段 | 当前依据 | 最终账本 |
| --- | --- | --- |
| S61-OC-00 批次合同 | 原冻结报告；本轮7组49子项/26Result、真实子项与水印父Task清理复核 | PASS_AND_FROZEN |
| S61-OC-01 性能 | OC-01R冻结；本轮新3冷/5暖/20页/展开/刷新全部过门禁 | PASS_AND_FROZEN |
| S61-OC-02 缩略图/超大图 | 不沿用早期含糊结论；本轮8格式、故障、100/180MP重启、全量测试、性能及资产全部过门禁 | PASS_AND_FROZEN |
| S61-OC-03/03R 清理/重建 | OC-03、03R1冻结；本轮真实界面清理、原真实重建根完整重开和scope/详情复核 | PASS_AND_FROZEN |
| S61-OC-04 谱系 | OC-04真实执行链及字节证据；本轮每条SHA边、失败恢复、双分支、祖先移除及原生重启复核 | PASS_AND_FROZEN |

OC-02原报告因并行/共享测试曾BLOCKED，后续OC-02P曾有冻结声明；OC-05又因身份/反馈门禁BLOCKED。这些历史报告保留，本轮依据当前全部门禁独立收口；旧冻结或失败声明均没有替代本轮运行。

OC_02_CLOSEOUT=S61-OC-02已冻结
S61-OC-02=PASS_AND_FROZEN

## FILES_MODIFIED

新增本报告 `docs/reports/S61_OC_05R_FINAL_ACCEPTANCE_20261015.md`、独立 `output/playwright/s61-oc-05r-20261015/` 证据；仅追加 `docs/09_CODEX_CHANGELOG.md`。生产源码和既有测试修改0，未为清零测试改断言/放宽/skip。

## TESTS

| 本轮实际执行 | 结果 | 原始证据 |
| --- | --- | --- |
| tests/output完整Python | 41/41，ExitCode0 | python-output.log |
| 输出/批次/水印/清理/记录删除/品牌合同 | 64/64，ExitCode0 | python-contracts.log |
| D61颜色/参考/稳定性及完整反馈邻接 | 81/81，ExitCode0 | d61.log |
| 当前前端全量 | 382/382，fail/cancelled/skipped/todo均0 | frontend.log |
| production build | ExitCode0，独立产物目录，原dist保持 | production-build.log |

全部命令和退出码在test-receipts.json。未改变任何既有测试文件。

## BATCH_COMPRESSION

继承未变的OC-03R1真实两轮3张压缩执行事实；本轮在其原运行根重新启动当前源码服务并原生完整重开，逐项复核新旧Source/Task/Batch Item/Result、文件、详情和scope。采用“相同来源与目录、新身份、新文件路径、旧文件不覆盖”：新文件既有_02后缀，旧3文件原路径/SHA保留，移除事实只隐藏旧身份。新批次一张卡、全部3个COMPLETED子项、统计和九字段一致，history scope符合重启语义；打开、打开目录和UI续编接入所选子项，已成功下游Result的父链保持。旧卡不回流，无重复或父Task冒充。原执行证据为s61-oc-03r1-20261015/runtime-cases.json；本轮独立结果为rebind-probe.json、native-oc05r-rebind-reopen.json。

## BATCH_WATERMARK

在既有真实图片执行事实的本轮独立副本实际DELETE水印父Task，确认deleted_count=1。保留3个嵌套正式Result及output_batch事实；所有九字段、顺序、summary与清理前一致，随后服务/原生重开仍正确。一份刻意缺失输出保留其真实Result和明确MISSING状态，其余子项实际打开/目录/intake的Task/Result/SHA准确。复制品不冒充本轮新执行Result。见watermark-parent-before/clear/restart.json、native-images-parent-restart.json。

七组既有矩阵另只读复核压缩3/10/混合JPG-PNG-WebP、水印3/10、失败/取消/KEEP_ORIGINAL；49子项、26唯一成功Result，九字段、顺序、统计与原证据一致。非成功项Result/path/SHA为空；17个成功子项界面详情/续编资格不串绑，pageerror和写请求均0。见bindings-recheck.json、selection-recheck.json。

## THUMBNAILS / LARGE_IMAGES / MISSING_FILES

本轮从受保护真实文件建立独立副本，以当前源码抽检JPG、PNG、透明PNG、WebP、4K、24MP、10000×10000(100MP)、18000×10000(180MP)。文件与原证据逐字节SHA一致，既有完整PNG流有效性/DecompressionBombWarning/Error证据允许继承。六种预算内缩略图真实解码、边长≤768，透明PNG Alpha=(80,80)。100MP/180MP超过缩略图安全预算，返回422但卡片available=true，原生界面显示“预览不可用”，打开/合法后续操作不因预览隐藏或中断；未伪造Result。

本轮实际损坏所属缩略图缓存后自动MISS重建并完整解码；以所属缓存目录故障哨兵制造422，正常正式Result卡片仍保留、打开及续编按钮可用。哨兵精确恢复，缓存/输出字节保持。故障原生窗口、两轮服务重启/完整原生重开及水印父Task清理后的额外重开都再次验证超大卡片和正常/失败/缺失状态；刷新卡数始终一致。见cache-fault.json、native-images-fault/restart-1/restart-2/parent-restart.json、images-restart-1/2.json。

13次真实列表读取记录完整像素解码次数0、目录状态1次/请求；进程内Pillow全局MAX_IMAGE_PIXELS始终89,478,485。图头读取保持32字节PNG/WebP和1MiB上限JPEG，缩略图预算仍40MP/最大边768；没有无边界解码或关闭全局限制。单图和批次缺失项明确MISSING/“正式文件缺失”、thumbnail为空/续编按文件状态禁用，卡片真实保留。见oc02-decoding-proof.json、images-*-requests.jsonl。

## LIST_CLEANUP

新的隔离清理副本保留8个既有真实输出，仅另生成1个真实当前压缩Result，用于与历史单图/批次分域。刻意缺失只将本轮副本的一个批次子项移到所属held位置，原48份隔离文件和正式文件不动。真实浏览器依次验证历史清除缺失、单卡移除、两个子项逐个移除/空批次消失、清空当前且历史保留、清空历史；每个响应files_deleted=false，详情取消选择、数量/空状态更新，刷新及服务/完整原生重开仍为空。9文件全部原字节保留，输入未变；祖先单卡移除后下游谱系仍可查询。原OC-03及OC-05部分/全部缺失、压缩/水印、当前/历史的未变覆盖继承，并由本轮64项合同回归保护。见cleanup-ui.json、cleanup-after-refresh/after-restart.json、native-cleanup-final-reopen.json。

## MULTI_ROUND_LINEAGE

将OC-04已有真实10输出及合法持久事实复制到新独立根，明确标记为既有执行证据复核；只定位复制品合法路径，不新造身份、猜测按时间/文件名归组或冒充新执行。当前API与原生桌面复核压缩→水印→压缩三轮、具体批次子项续编、真实failed/null中间轮从上一成功Result恢复、双分支；每条实际source_path文件SHA等于父Result SHA，Task/Result/路径独立。祖先列表移除后，三轮顺序、下游显示/打开/继续编辑和10文件SHA在服务/原生重启后保持。见lineage-durable.json、lineage-ancestor-removal.json、native-oc05r-ancestor-restart.json、branch-pages-after-restart.json。

本轮重新生成两分支真实反馈快照和ZIP，CRC校验及feedback.json读回证明只含各自Task，没有另一分支Task；显式跨Task、将水印Task用于颜色反馈、跨Result三个请求均409。生产严格校验保持，见feedback-branches.json、feedback-*.zip。

## DESKTOP_RUNTIME / PROCESS_CLEANUP

当前正式开发版production + Edge Chromium WebView2正常关闭重开5/5，页面刷新、处理中心切换/返回、前进/后退均通过。每轮依据本次Popen进程树PID/create_time识别所属后端/启动器/WebView前端，正常WM_CLOSE、ExitCode0、residual=[]；没有按进程名误杀共享或其他实例。所属隔离服务树也已全部关闭。

最终正式服务已恢复ready，根仍D:\影界文件，8787/5173当前开发服务可用；实际载入原dist构建`V0.6.1-dev+aa0dd93265d2.dirty.20261007T023302122Z`。正式恢复实例是明确要求保留的服务，不计作已关闭测试实例残留。见formal-1..5-close.json、restored-formal-ready.json及最终健康读取。


交付复读一度发现恢复进程随验证工具命令生命周期结束而退出（启动日志仅有HDDE_READY，无产品异常，所属PID均消失）。随后以同一正式启动器、CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB恢复服务，后续两个独立命令健康复读持续ready；生产源码和资产SHA保持。首次验证脚本误断言“必须不属于任何Windows Job”，该断言与外层Job成员身份无关且不用于判定产品失败，错误及进程证据保留。最终恢复归属为PID26272/create_time1792027183.7024932的进程树，五轮已关闭测试实例残留仍0。当前动态结果以final-formal-ready-and-cleanup.json为准。

## PERFORMANCE

在全部测试/构建/隔离服务结束后新测量，开始前无其他测试/构建进程，负载和所有原始样本保留，未放宽门禁或选择最好成绩。测量范围为输出页导航/加载到首12卡绘制，整个软件启动速度不在本阶段。

- 冷首屏3次：920.5 / 943.7 / 932.9ms，均≤1000；第4/5完整重开另记933.5 / 934.9ms。
- 暖重开5次：369.2 / 376.4 / 369.4 / 355.6 / 374.0ms，均≤800。
- 分页连续20次：91.3 / 97.3 / 99.0 / 98.2 / 82.0 / 97.5 / 98.0 / 95.4 / 98.6 / 97.9 / 98.8 / 99.0 / 97.8 / 97.9 / 99.0 / 81.9 / 98.4 / 98.9 / 98.6 / 98.5ms；nearest-rank P95=99.0ms≤150，max=99.0ms≤200。
- 批次展开24.3ms≤100；5次刷新927.2 / 926.4 / 930.8 / 927.0 / 919.9ms，均≤1000。
- 每轮首12卡完整无重复、列表首请求1次、缩略图峰值4；按当前真实39卡页数循环采集20个有效分页样本，未增加正式记录。

原始证据：performance-summary.json、formal-1..5-gate.json、formal-window-load.json；早期3887/163.8ms及其他阶段样本未代替本轮测量。

## REGRESSION / ASSET_INTEGRITY

七组49子项、26个既有成功Result及统计保持，原34/当前49输出、51输入、settings、48份旧隔离文件SHA全部不变；额外保护OC-03R的16输出及03R1的8输出。settings SHA=`7d904536f0c34b9ae8636b378556f733d32c5d23c5e8f1384a5e09f34271f7d5`。35个本轮复制/新增文件独立登记，只有上述1个清理域当前Result为本轮新执行，不污染正式目录或旧基线。所有缺失/故障操作局限于本轮副本/缓存，Source及已有输出未删除/覆盖。source_checks保护252文件，生产/测试全部字节未变；原dist不变，dirty保留、branch/HEAD不变、staging为空，无Git写操作。见baseline.json、copied-runtimes.json、integrity-final.json、git-status-final.txt。

## REMAINING_RISK / FREEZE_STATUS / NEXT

REMAINING_RISK=本阶段无未完成门禁；冻结范围为当前V0.6.1输出中心，不外推其他机器负载、整个软件启动时间、算法新需求或安装包发布。
FREEZE_STATUS=V0.6.1输出中心已最终冻结
NEXT=输出中心阶段关闭，不继续修改；后续如有新需求另开版本阶段
REPORT_PATH=docs/reports/S61_OC_05R_FINAL_ACCEPTANCE_20261015.md

Skill迭代判断：暂不需要更新。
