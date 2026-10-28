# S61-OC-02R 共享状态复核（2026-10-03）

STATUS=BLOCKED

ATTRIBUTION=已确认并最小修复 OC-02 缺失文件卡片的冗余详情探测。剩余暖重开超标及分页波动尚未完成根因归属，不能冻结。没有直接证据认定 D61 故障，未修改 D61 源码、算法或生命周期。

VERSION=0.6.1-dev / V0.6.1 开发版 / DEVELOPMENT

BRANCH=codex/image-processing-routing-v1

HEAD=aa0dd93265d270eb5192ebbd44a1fe14488d454a

STAGING=EMPTY。全程无 Git 写操作；已有 staged/unstaged/untracked、删除标记均保留。开始共享源码 SHA 快照 baseline-current.json 包含55文件；本轮允许变更后端一处调用及一个现有测试，其余54份快照 SHA 保持。D61 已冻结结论保留。

FILES_MODIFIED=

- backend/image_compression_api.py：仅在分页后，排除已携带持久事实的 missing_items 路径再读取活文件详情；全部为缺失卡片时直接使用空详情，避免旧详情解析器把空集合解释为全量读取。selected_paths、卡片排序/身份、批次合同、有效文件校验与图片算法不变。
- tests/image_compression_ui/test_output_center_api.py：加强已有缺失 Result 测试，验证缺失专页不进行路径迁移探测，同时保留真实 ID、Result ID、MISSING 和预览404断言；测试数量仍为57组合。
- docs/09_CODEX_CHANGELOG.md、本报告。
- output/playwright/s61-oc-02r-20261003/：观察脚本、独立构建、实测日志、SHA及差异证据。未替换正式 dist。

IMPLEMENTATION=缺失卡片由本轮 OC-02 投影引入，其路径进入冻结 OC-01 的活文件详情解析器，导致不必要的 resolve/migration/file probes。缺失卡片最终使用持久 Result 事实，不消费这些详情，排除它们不改变合同。真实回归测试修复前失败于 resolve_migrated_formal_output_path，修复后通过。见 missing-probe-before-authorized.log、missing-probe-after.log、image_compression_api-stage-only.patch、test_output_center_api-stage-only.patch。初次测试受到默认沙箱临时目录清理权限限制，授权重跑后取得上述真实失败/通过，未以环境失败代替产品复现。

TESTS=当前修改后 Python57/57；前端380/380，fail0/cancelled0/skipped0；production build通过，输出到 production-build-fixed；追加 D61及相邻反馈 Python70/70通过。旧反馈路由断言已由前阶段合法对齐 compression + color-correction，本轮只读复核生产路由与说明，未修改无关断言。证据：python57-fixed.log、frontend380-fixed.log、build-fixed.log、d61-70-fixed.log。

REAL_RUNTIME=实际正式配置及正式 dist 的原生 EdgeChromium 桌面完整启动、路由、测量及正常关闭已执行。两次普通最终测量和一次只读剖析进程均 exit0、所属进程树无残留；这证明退出正常，不代表性能门禁通过。隔离当前源码/真实图片根目录先后完整重启前后端并关闭重开原生桌面，两次11张真实卡片 ID一致，普通缩略图和压缩批次3子项缩略图加载、100MP/180MP卡片及明确缺失状态保持。见 oc02r-final-native-close.json、oc02r-final-quiet-confirmation-close.json、oc02r-attribution-only-close.json、runtime-final-shared-first.json、runtime-final-shared-reopened.json、native-final-shared-first.json、native-final-shared-reopened.json。

PERFORMANCE=

| 实测 | 冷首屏 ms | 暖重开三次 ms | 刷新 ms | 判定 |
| --- | ---: | --- | ---: | --- |
| 当前修复前正式桌面、停止隔离服务后 | 929.6 | 633.2 / 472.8 / 531.7 | 925.0 | 冷暖数值达标，分页待定位 |
| 修复后首次测量 | 941.6 | 636.8 / 742.8 / **1632.7** | 926.2 | 暖超标，保留失败 |
| 修复后响应式观察脚本、完整原生重开 | 929.8 | 478.4 / 469.1 / 765.3 | 929.0 | 此轮达标，不能代替复核失败 |
| 测试/隔离服务结束后的安静复核 | 942.8 | **940.6** / 765.7 / **927.6** | 928.9 | 暖超标，最终性能门禁未通过 |
| 带 cProfile 的只读归属剖析 | 944.1 | 546.4 / 603.4 / 645.3 | 928.9 | 仅用于归属，不用于覆盖普通实测失败 |

首批12卡片完整，DOM/API身份一致；每轮真实正式总数159，分页遍历无重复、身份保持。159包含114张显式持久 Result 的缺失文件卡片；旧 OC-01 报告只有30卡片、后页18项，而当前后页32项，不直接把旧值当本轮结果。没有沿用旧3887ms。

同一159数据、同一32项分页的 request-to-paint：修复前偏移12/44/76/108/140为253.6/299.1/373.5/332.0/282.6ms；修复后完整原生测量为233.2/135.0/117.0/136.1/133.3ms。但最终安静复核又升至462.2/216.7/200.2/217.5/286.6ms，不能声称稳定无回退。正式批次1子项展开原始观察计时69.4–83.6ms。七组副本的10子项展开进一步检查：自动化调用至DOM35.3/41.1/40.4ms；真实点击至两帧绘制27.5/27.6/27.6ms，17成功子项详情/继续资格全部正确。保留先前48.5/52.8/83.8ms原始自动化计时，未以它冒充纯产品展开耗时。

同数据只读加载 OC-01 源码快照、修复前 OC-02 快照及当前源码，没有替换正式源码/服务；首12身份相同，目录 provider每个列表请求1次。控制轮32项中位154.9/247.9/195.0ms，后两份同159数据、同页身份。另一次修复前工具测量约470.7ms、修复后一次约142.3ms有波动，不作为稳定门禁值。见 same-data-before-after-controlled.json、same-data-source-comparison.json及对应日志。

真实服务器只读 cProfile 的当前首12快照179–218ms、路径resolve402次、底层 _getfinalpathname996次（66–80ms）；缩略图描述符12次约18–27ms，目录状态约18–20ms，活文件详情约24–26ms。同步路径解析/文件状态探针是实际热点；剖析期间未复现同一次940/1633ms暖超标，底层波动及其他请求/调度贡献 NOT_YET_CONFIRMED。冻结 OC-01 的详情资格流程与 Windows 文件系统调用也在热点内，不能把所有耗时归给新增缩略图、更不能凭此认定 D61 为根因。见 live-profile-01至10、oc02r-attribution-only.json。未继续优化冻结模块。

首个开发 Vite 冷载曾为9318.5ms，随后因该夹具只有11卡片，旧测量器等待不存在的分页而超时；performance-first.log保留。它是开发服务的真实观察失败，不拿正式生产测量替换这条历史记录，其首载模块/环境贡献尚未完整量化。本门禁采用正式配置+正式 dist 的实测。首次修复后原观察脚本还卡在原生截图；独立CDP确认DOM/服务响应，截图5秒超时，发送所属窗口正常WM_CLOSE后无残留。证据脚本把同步子进程改为异步等待、截图限时，产品代码未为此改动；formal-fixed-observer-close.json、cdp_screenshot.log保留，之后原生截图与正常退出均成立。

LARGE_IMAGE_RESULT=真实 JPG、PNG、透明PNG、WebP、4K、24MP、100MP(10000×10000)、180MP(18000×10000)共8类文件保持 SHA。100MP/180MP具备完整PNG块/CRC/文件尾证据，非伪造头部；刷新、前后端重启及原生完整重开后真实卡片保持。40MP预览预算以上返回422 OUTPUT_THUMBNAIL_UNAVAILABLE，界面显示“预览不可用”，不隐藏卡片；Pillow全局MAX_IMAGE_PIXELS=89478485未关闭。普通缩略图≤768，透明PNG alpha80保持。损坏自有 v2 PNG缓存触发MISS并重建；缓存目录故障返回422、保留真实卡片，实际打开文件/目录200、继续资格保持；故障注入已还原。真实缺失 Result保持MISSING、空预览、关闭继续按钮及文件动作缺失错误。见 huge-file-validity.json、runtime-final-shared-*.json、cache-fault.json、desktop-fault-fixed.log、native-final-shared-*.json。

REGRESSION=七组49子项、26个唯一成功Result逐项核对九字段、Task/Result/Source关系、实际图像完整解码、路径及SHA；成功Result资产/原始预览SHA一致。KEEP_ORIGINAL、FAILED、CANCELED不补造Result/path/SHA。当前UI17成功子项详情和继续输入资格绑定正确，无pageerror、无批次写请求。原有清除记录的两组卡片保持隐藏而正式文件仍在、SHA不变；不重复清除已清除历史。见 bindings-recheck.json、selection-click-paint.json、clear-records.json。单图既有卡片保持；缺失卡片使用显式持久关系而非时间/文件名猜测。

REGRESSION_SHA=原34正式输出、D61开始48正式输出、真实正链新增1正式输出、原图集合及正链A/B、隔离42图片/输出、settings、其余54共享源码 SHA全部一致。正式settings SHA=7d904536f0c34b9ae8636b378556f733d32c5d23c5e8f1384a5e09f34271f7d5。见 integrity-final.json。初始 isolated_settings_sha256 为空，未据此声称隔离设置已有开始SHA基线；正式settings有开始/最终真实基线，重启身份由实际health/runtime证明。

REMAINING_RISK=普通正式桌面暖重开两轮有真实超标；分页仍有波动。已确认的小缺陷修复与所有正确性测试不能替代性能门禁。剩余波动根因未完全确认，暂不能判断是否需要触及冻结 OC-01 或属于环境/调度。所有失败和观察器边界已保留，未做整个软件启动时间优化、安装包、算法修改或无关UI重构。

FREEZE_STATUS=D61保持已冻结；S61-OC-02未冻结。

NEXT=继续只读定位普通正式暖重开超标与分页波动的归属；确认属于OC-02后才允许最小修复。当前不进入OC-03/OC-04。清除记录已有OC-00覆盖证据，只有OC-02全部门禁真实满足后才可据此跳至OC-04。

证据根目录：output/playwright/s61-oc-02r-20261003/。本报告是当前共享状态的最终结论，不覆盖历史分阶段报告或已冻结D61报告。
