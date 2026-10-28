# S61-OC-03｜缺失记录与列表清理

STATUS=PASS_AND_FROZEN

基线：V0.6.1 开发版 / 0.6.1-dev；branch `codex/image-processing-routing-v1`；HEAD `aa0dd93265d270eb5192ebbd44a1fe14488d454a`；staging为空，已有dirty保留。唯一执行任务为“V0.6.1｜S线｜输出中心”，无并行源码修改、无Git写操作。

证据目录：`output/playwright/s61-oc-03-20261007/`。

## ROOT_CAUSE

- 旧清理接口只定位顶层卡片。真实水印3项中移走1个文件后，缺失子项没有卡片操作ID，移除请求404，重启后仍显示3项。普通卡片清理后又自动选择其他成品。
- 输出中心没有当前/历史分域，也没有按域清除缺失与清空；已有当前/历史按钮属于处理中心任务列表。
- 清理后保留的旧批次路径仍参与占用/冲突检查，会干扰同路径新Task/Result。只排除已经明确移除的列表占用，以精确Task/Result取对应元数据，不改九字段身份合同。
- 新增卡片控件造成分页时重复渲染。相同环境只读对照：旧完整实现分页最大102ms，当前后端配旧前端112ms，初版完整前端205ms；普通卡片按稳定项目/选中状态复用后恢复。未回滚或覆盖共享源码。

## FILES_MODIFIED

- `backend/image_compression_api.py`：明确身份分域、子项清理ID、持久移除、按域批量清理、首响应数量/批次统计、已移除占用排除。
- `src/OutputCenterPage.jsx`：卡片及子项移除、分域按钮、清理后取消详情、即时计数与空状态、普通卡片渲染复用。
- `src/index.css`：普通卡片独立移除按钮所需的两条布局规则。
- `tests/image_compression_ui/test_output_center_cleanup.py`：新增7项清理/身份/文件保护回归。
- `tests/image_compression_ui/test_output_center_ui.mjs`：对齐选择动作及新增清理契约测试；未减少测试或跳过。
- `dist/`、本报告、`docs/09_CODEX_CHANGELOG.md`；验收脚本与证据仅在上述证据目录。原production文件已备份并保留SHA。

## IMPLEMENTATION

用户确认的分域：后端启动时已有的Task/批次身份为历史，之后新登记的为当前。原“全部记录”入口保留；域判定不依赖文件名、mtime或时间猜测，重启后尚未移除的既有任务自然属于历史。

每张普通卡片、批次卡片和子项提供“移除记录”；当前/历史各有“清除缺失”与“清空列表”。批量操作只接受current或history，拒绝跨域all清空及删除文件模式。运行批次保留。

清理作用于Registry中的输出列表可见索引，沿用持久移除标志；**不物理删除冻结的Source/Task/Result来源事实**。这些事实也是Result查询、继续处理与批次身份的依据。直接删除来源事实仍可能被正式目录重建成卡片，因此移除标志用于确保刷新/重启不回流。新标志使用明确的removed_result_id，避免把同路径的新合法Result误认为旧记录，也不伪装成Result事实。

缺失判定只接受明确的FileNotFound；权限/IO错误、预览失败、SHA不一致不按“缺失”批量清理。读取或启动不自动删除记录。清理接口不删除、移动或改写成品文件；未新增磁盘删除操作。

服务响应直接返回准确域数量、移除卡片与剩余批次统计；前端立即移除对应行，取消右侧选择、关闭悬浮预览和继续处理对话框、更新交付选择与分页。随后刷新当前首12卡进行正式状态同步，不等待此GET才更新清理状态。

## TESTS

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 输出中心/清理/批次/水印/记录删除/品牌Python | 64/64，ExitCode0 | `python-final-64.log` |
| D61及相邻颜色/反馈Python | 70/70，ExitCode0 | `d61-final-70.log` |
| 当前前端全量 | 381/381，无fail/cancelled/skipped/todo | `frontend-final-green.log` |
| production build | 通过 | `production-final-green.log` |
| 同路径单图/批次新Result与旧记录不回流 | 通过 | `cleanup-versioned-removal.log` |

## REAL_RUNTIME

使用真实照片的隔离输入，真实生成单图、压缩3项、水印3项各两组。当前/历史、单条/批量缺失、部分/全部批次、有效文件和超预算预览均实测。原始照片SHA保持。

四轮独立前后端服务生命周期与四个EdgeChromium原生桌面窗口通过：部分清理后剩余4卡，刷新和完整服务/桌面重开保持相同ID；历史全部清空后0卡、无详情，再次完整重开仍0卡。18个主要测试文件（16个真实结果、100MP/180MP两张真实PNG）字节全部保留；故意制造缺失时只移动所属测试副本至隔离held目录。

补充验证刻意暂缓清理后的列表GET，首个移除响应已使子项数/批次标题正确、详情取消选择、清空立即进入空状态；渲染复用后按钮仍执行最新动作。见 `counts-ui.json`、`counts-final-complete.log`。最终后端还新开原生桌面复核空列表，见 `native-final-empty-restart.json`。

较早正式服务加载旧构建且无活动任务。通过已核验正式启动器的正常退出事件停止，最终恢复正式启动器（不另开浏览器），8787/5173加载最新构建，正式根与设置不变，清理路由存在、首12卡完整无重复。**正式用户Registry未用于清理演练**；正式根仅作读取/性能核验。

最终正式WebView2：冷首屏925.3ms；暖重开239.2/377.5/380.3/372.3/377.9ms；连续10页59.5–115.4ms，nearest-rank P95/max=115.4ms；展开30.1ms；刷新924.8ms；缩略图峰值4。首12卡及157卡完整遍历无重复。门禁未放宽，较早失败样本和测量器滚动后再次点击的竞争证据保留。

## BATCH_BEHAVIOR

部分缺失只移除相应列表子项，成功/KEEP_ORIGINAL/失败/取消及体积统计按剩余显示项更新；最后子项移除后空批次不显示。持久批次API仍保留原始9字段事实及Result来源，已移除的旧占用不会抢占新明确Task/Result。同路径新结果按身份关联，未按名称或时间归组。

冻结七组49子项、26个唯一成功Result复核一致；实际选择17个成功压缩/水印子项，详情和继续处理准确绑定。复核仅GET，无冻结数据改写。见 `bindings-recheck.json`、`selection-recheck.json`。

## FILE_PROTECTION

原34输出及开始时49个正式输出、51个原图/真实A-B输入、settings SHA全部不变；Settings SHA仍为 `7d904536f0c34b9ae8636b378556f733d32c5d23c5e8f1384a5e09f34271f7d5`。算法、批次持久合同、D61启动器、缩略图队列/像素安全策略均未改动。

验证异常单列：首个隔离配置沿用了保存的压缩输出根，5个新增测试产物误写到正式目录，未覆盖原文件。验收立即停止；逐项核对本轮隔离Task/Result、SHA和与原49输出无重叠后，将5个已确认所属测试产物独立移动到 `owned-misrouted-files/`，保留原字节，未删除文件或执行产品清理。所有路径、归属、SHA及恢复记录保存于 `owned-misrouted-test-files.json`、`owned-test-file-recovery.json`；后续验证显式配置隔离输出根。失败配置未冒充通过证据。

## REGRESSION / FREEZE_STATUS / NEXT

后端64、D61 70、前端381、production build、真实清理/重启/文件保护及OC-02性能门禁全部通过。其余受保护相关源码保持SHA；branch/HEAD/空staging及已有dirty保留。没有图片算法、批次Result合同、缩略图安全、整个软件启动、安装包或Git写操作。

此前OC-02P的“OC-03已覆盖”仅对应整卡显示记录清除，未覆盖本轮新定义的域隔离、缺失批量清理及逐子项清理；本轮报告以用户新合同为准，不改旧报告证据。

FREEZE_STATUS=S61-OC-03已冻结。

NEXT=进入S61-OC-04；本轮未开始OC-04开发。

Skill迭代判断：暂不需要更新。
