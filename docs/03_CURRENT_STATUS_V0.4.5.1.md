# 当前状态

更新时间：2026-11-19

## 权威说明

本文件是当前动态项目状态的权威入口。文件名保留 `V0.4.5.1` 仅为兼容现有 `AGENTS.md` 读取优先级，不代表当前产品版本。

- 2026-11-19（V0.8.3 开发版）：源码版本递增至 `0.8.3-dev`，沿用开发渠道。此次迭代仅登记版本启用。

- 2026-11-19（V0.8.2 开发版）：源码版本递增至 `0.8.2-dev`，渠道为 `DEVELOPMENT`。本版喷绘改动包括分层选区控件排版、左栏统一、尺寸预检首屏布局及分层操作区对齐。

- 2026-11-18（V0.8.1 开发版）：当前源码版本为 `0.8.1-dev`，渠道为 `DEVELOPMENT`。本次补丁收录一键生成交付副本和新版交付回执。软件内更新日志按版本列出本轮文件交付改动和 V0.8.0 的喷绘、校色记录。

- 2026-11-18（喷绘界面统一）：新隔离试用版沿用颜色校正工作台布局。左侧选图和设置规格，底部提交或另存，右侧预览、编辑分层及核对成品。两张真实 8K 样图完成出图与保存。[首屏](../output/playwright/v080-print-reference-ui/desktop-empty.png) · [成品审图](../output/playwright/v080-print-reference-ui/desktop-layer-result.png)

- 2026-11-18（喷绘工作区 UI）：隔离试用版采用原图与喷绘规格双栏，分层工具按需展开。成品可定位到同位置的原图和成品局部，随后在页头另存。等比摄影展板和分层海报均已走通真实出图与交付，成品文件与改版前一致。[界面截图](../output/playwright/v080-print-workspace-ui/desktop-ready.png) · [成品核对](../output/playwright/v080-print-workspace-ui/files.json)

- 2026-11-18（喷绘提交与审图）：隔离开发版的喷绘页首屏已有「提交出图」，提交成功后可预览成品与原像素局部，另存并从交付回执继续下一单。用 NASA/Josh Valcarcel 的 5504 × 8256 px 摄影原片完成 80 × 120 cm、5120 × 7680 px 模拟展板。数字审图可进入局部实物打样；本单纸面效果待验证。产品 99 的主体细纹问题仍单独保留。[摄影展板成品](../output/print-review/nasa-portrait-80x120/航天摄影展板_80x120cm_8K.png) · [原像素审图](../output/print-review/nasa-portrait-80x120/展板_原像素审图.png)

- 2026-11-18（喷绘分层出图，`OWNER_SIGNOFF_PENDING`）：「交付 → 喷绘出图」支持在影界内提取和排布图文轮廓、重铺字内纹理、沿轮廓选取照片主体并进行本地增强。「产品 99」已在隔离开发版完成 80 × 120 cm、5120 × 7680 px 的出图、原像素预览与交付副本保存。标题抽测字边变清楚，菌盖与手指的细纹仍然偏软。本次按近看条件暂缓打印，待负责人审图。分层成品使用原图轮廓生成 PNG，方案可以载入同一原图继续编辑。[原像素对照](../output/print-review/order99-80x120/分层出图/产品99_原像素对照.png) · [验证记录](../output/print-review/order99-80x120/分层出图/验证记录.json)

- 2026-11-18（喷绘模拟观看）：原整图插值版在假设的 2 米观看距离下，主标题、宣传语和产品可辨识。负责人复核指出近看字边、压缩块和主体细纹未满足 8K 喷绘观感。此稿仅保留作对照。[观看距离模拟](../output/print-review/order99-80x120/产品99_模拟观看距离.png)

- 2026-11-18（V0.8.0 喷绘出图第三阶段）：负责人完成 [A4 灰度样张](../output/pdf/喷绘出图_第三阶段_A4原尺寸打样.pdf)实物打印，反馈“A4纸打印没有问题”。A4 样张打印通过，1∶1 尺寸偏差尚无实测记录。

- 2026-11-18（V0.8.0 喷绘出图第二阶段）：在「交付 → 喷绘出图」确认预检后，可生成目标尺寸和 PPI 的 PNG，预览正式成品并另存交付副本。隔离 Edge 已跑通横图 7680 × 3288 和 EXIF 竖图 429 × 1000 的出图与保存。4K 和颜色校正各以同一张真实输入跨基线复跑，成品像素一致。本次交付为源码及隔离构建，实物打样仍待线下验证。[喷绘文件核对](../output/playwright/v080-print-output-stage2/verified-files.json)

- 2026-11-18（进入 V0.8.0 开发版）：源码版本为 `0.8.0-dev`，渠道为 `DEVELOPMENT`。「交付 → 8K喷绘出图」第一阶段已完成喷绘尺寸预检及隔离验证，支持按宽高与目标 PPI 计算、按 7680 px 长边估算。按目标像素增强、文件导出与实物打样归入后续阶段。本次验证使用独立构建，最近一次正式本机部署记录仍为 V0.7.2。

- 2026-11-18（进入 V0.7.3 开发版）：源码权威版本升至 `0.7.3-dev`，渠道为 `DEVELOPMENT`，软件内更新日志新增 V0.7.3 条目。本机最近一次正式部署记录为 V0.7.2。

- 2026-11-18（V0.7.2 开发版正式本机部署）：正式启动器已加载整版构建 `V0.7.2-dev+1eb239868079.unknown.20261118T030934658Z`。5173 与 8787 指向同一就绪后端，正式数据目录为 `D:\影界文件`。固定构建对应日本时间 12:09 的工作区快照。[正式实例核验](../output/deploy_v072_full_1794971372703/after.json)

- 2026-11-18（进入 V0.7.2 开发版）：权威版本由 `0.7.1-dev` 升至 `0.7.2-dev`，渠道为 `DEVELOPMENT`。软件内更新日志新增 V0.7.2 条目，V0.7.1 的指南、压缩、修复、水印、输出中心和交付等说明保留在原版本下。本轮升版范围为源码和版本记录。

- 2026-11-14（V0.7.0 开发收口，进入 V0.7.1 开发版）：负责人确认 V0.7.0 开发收口。本版用户可见改进以软件内 V0.7.0 更新日志为准（4K 画质增强、颜色校正、输出中心等）；颜色校正 S69-A/D/E/F/G 已完成并提交，S69-B 去灰 v3 与 S71 除雾 PoC 为 BLOCKED，除雾由负责人暂停。用 tools/manage_version.py 将权威版本由 `0.7.0-dev` 升至 `0.7.1-dev`（试运行后写入），渠道保持 `DEVELOPMENT`；软件内新增 V0.7.1 条目并保留全部历史。收口不代表冻结或正式部署：正式运行构建和安装包未更新，各模块未决事项以各自记录为准，工作区内其他会话的未提交成果原样保留。

- 2026-11-13（进入 V0.7.0 开发版）：按负责人要求将权威版本升级为 `0.7.0-dev`，渠道保持 `DEVELOPMENT`，应用内日志新增 V0.7.0 条目并保留全部历史。本次仅升级源码版本与记录，不代表 V0.6.9 已冻结；原生取消退出、安装升级及构建环境问题仍以原验收记录为准。正式运行构建和安装包未在本轮更新。

- 2026-11-12（V0.6.9 补充验收）：R3 安装包内容门禁、解包 EXE 真实启动与 LaMa 候选重启恢复另存已验证；原生取消退出证据不完整且自动操作与结果不一致，仍待确认，总验收 `BLOCKED`、未冻结。本轮未替换正式运行构建。R2 启动失败，不得分发。详见 [补充验收报告](../output/acceptance_v069_20261112/REPORT.md)。

- 2026-11-12（V0.6.9 正式本地运行）：同位置批量排除提示、干净结果预览和「清空当前批次」已部署至 `RUN-20261112T072309-7F595DEE08`。正式端口和代理均已核对 V0.6.9 更新日志。原反馈批次和重启前候选可恢复，设置与受检文件哈希一致。安装包和冻结状态另行确认。 [部署记录](09_CODEX_CHANGELOG.md)

- 2026-11-11（进入 V0.6.9 开发版）：当前权威版本为 `0.6.9-dev`，开发渠道为 `DEVELOPMENT`。应用内日志新增 V0.6.9 条目。V0.6.8 的原生「取消退出」仍待实测，安装包、正式部署和冻结另行决定。

- 2026-11-11（V0.6.8 优化整体验收）：本轮隔离生产构建通过 383 项前端和 143 项 API 与桌面宿主回归，完成工作区恢复、批量预检、交付中断恢复、成品对比以及真实候选退出重开与另存验证。原生取消退出仍待实测。范围排除 4K 和颜色校正。当前为 `0.6.8-dev`，桌面安装包、正式部署和冻结另行决定。 [验收记录](09_CODEX_CHANGELOG.md)

- 2026-11-11（进入 V0.6.8 开发版）：当前权威版本为 `0.6.8-dev`，开发渠道为 `DEVELOPMENT`。软件内日志新增 V0.6.8 条目，汇总已纳入的输出中心展示与批量水印链路改进。桌面安装包、正式部署和冻结另行决定。

- 2026-11-10（进入 V0.6.7 开发版）：V0.6.6 已完成开发收口。权威版本源为 `0.6.7-dev`，软件内更新日志新增 V0.6.7 条目并保留历史。既有 5 项旧 Node 静态断言失败继续保留记录，整批稳定提速维持 `NOT_VERIFIED`。正式部署和冻结另行决定。

- 2026-11-10（V0.6.6 开发收口）：BUG-01～04、单张与批量压缩设置及软件内更新日志通过同一隔离构建的指定冒烟。合并验收发现的 BUG-05 已修复，专项隔离 Edge 复跑「智能压缩转 JPG → 输出中心 → 批量水印」，原失败样本与对照共 5 项成功。负责人已确认默认允许转 JPG，并签收本组 3840 × 2161 整图样本。5 项已分类的旧 Node 静态断言仍失败，整批稳定提速维持 `NOT_VERIFIED`。当前版本仍为 `0.6.6-dev`，正式部署和冻结另行决定。 [合并验收](D:/CodexHome/.codex/visualizations/2026/11/10/01a1c357-a246-76e3-a7ff-0b895fcb948c/v066-merge-acceptance/REPORT.md) · [BUG-05 复验证据](D:/CodexHome/.codex/visualizations/2026/11/10/01a1c374-1835-7d31-bae3-b4bfa650fefb/bug05/verified-files.json)

- 2026-11-10（V0.6.5 开发收口，进入 V0.6.6）：负责人确认结束 V0.6.5 开发。权威版本源已升至 `0.6.6-dev`，软件内更新日志已新增 V0.6.6 开发版条目。V0.6.5 合并验收以已归档构建为准，后续输出中心布局和批量压缩界面改动以各自隔离证据为准。可选转 JPG 的整图画质签收仍待负责人确认，整批稳定提速维持 `NOT_VERIFIED`。正式部署和冻结另行决定。 [V0.6.5 合并验收](../output/merge_candidate_v065/REPORT.md)

- 2026-11-10（A 线智能压缩允许转 JPG）：单张和批量新增默认关闭的「允许不透明 PNG 转 JPG」。批次锁定设置，恢复与重试沿用。隔离 Edge 验证单张及六张混合批次。历史反馈样本默认 PNG 减容 7.62%，开启后 JPG 减容 92.11%，三轮中位数分别 13.539 秒和 16.738 秒。透明 PNG 保留 Alpha，已压缩 JPG 保留原图。正式部署及冻结另行决定。 [验收报告](../output/smart_png_jpeg_v065/REPORT.md)

- 2026-11-10（V0.6.5 合并隔离候选）：批量压缩处理中勾选、F 线批量水印及输出中心紧凑分组在同一归档构建通过验收。原 24／50 张各仅交付所选两份，重复确认无新增副本。水印完成成品带入、混合本地图、预览、逐张进度、取消和仅重试失败项，输出中心分组、子项身份及原图对比通过。软件内三组更新说明已复核。压缩引擎使用开工实现，RGBA 实验保留独立候选。版本、正式部署及冻结另行决定。 [验收报告](../output/merge_candidate_v065/REPORT.md)

- 2026-11-10（A 线批量压缩处理耗时）：V0.6.5 隔离对照完成原 24 张、50 张各三组交错跑批。候选在严格无损校验中以完整 RGBA 字节相等直接确认零差异，逐图输出和画质门槛一致。PNG 校验累计中位数下降 4.7% 和 12.3%，整批处理中位数分别为 64.154 → 69.502 秒、117.642 → 115.866 秒。整批稳定提速 `NOT_VERIFIED`，仅留隔离候选与证据。 [验收报告](../output/batch_processing_a065/REPORT.md)

- 2026-11-10（V0.6.5 批量压缩隔离候选）：支持处理中勾选已通过交付校验的成品和保留原图，资格更新保留有效勾选，批次结束后重新核对并确认交付所选项。Edge 复跑原 24 张和 50 张，核对 74 份交付路径及 SHA256，暂停、取消、恢复、失败重试和重复确认通过。50 份首次交付 38.755 秒。20 份首次交付三组交错计时未复现持续变慢。正式部署与冻结待负责人另行决定。正式端口只读状态显示开发版且未报告构建标识，候选验收以隔离证据为准。详见 [V0.6.5 批量压缩验收](../output/batch_acceptance_v065/REPORT.md)。

- 2026-11-09（V0.6.5 开发版）：权威版本源已升至 `0.6.5-dev`，软件内更新日志已新增 V0.6.5 条目。正式实例仍沿用 V0.6.4 部署。V0.6.5 待办为批量压缩处理中勾选与首次交付性能复测。

- 2026-11-09（V0.6.4 收口）：负责人确认结束 V0.6.4 开发，收口版本为 `0.6.4-dev`。大批次主流程验收通过。处理中勾选（`FAIL`）及首次交付性能复测（持续回归 `NOT_VERIFIED`）转入 V0.6.5。详见 [大批次验收报告](../output/batch_acceptance_v064/REPORT.md)。

- 2026-11-09 19:00（东京时间）：批量交付、批量瑕疵修复候选编码及缩略图冷缓存优化正式部署至 `RUN-20261109T190009-69AE3E6D02`。软件内更新日志已同步，正式历史压缩批次缩略图和原图身份已核对。部署证据见 `output/batch_experience_deploy_v064/`。

- 2026-11-09 18:30（东京时间）：按当前工作区合并部署至正式实例 `RUN-20261109T183009-43C88ABA89`。三项图片压缩改动、大图与缩略图预览、批量瑕疵修复恢复及历史成品对比修复随实例加载。软件内更新日志已同步。正式历史压缩批次预览及运行验证见 `output/compression_deploy_v064/`。

- 2026-11-09（V0.6.4 批量瑕疵修复仅重试失败项）：支持按逐图原蒙版重试失败项，失效原图逐图提示，已另存成品保留。隔离 Edge 与 LaMa 验证了重启后的定向重试和人工确认另存。已随正式合并部署。

- 2026-11-09（V0.6.4 历史成品来源与交付）：修复已清除 Task 的历史校色成品对比入口。抽检两张校色、一张压缩和一张瑕疵修复成品。原图与成品读取、以成品继续编辑、交付副本哈希及幂等重放通过。原 3 项来源素材回归与 1 项交付静态断言已修正。隔离证据见 `output/historical_result_check_v064/`，已随正式合并部署。

- 2026-11-09（V0.6.4 批量瑕疵修复断点恢复）：支持恢复原批次、共用像素选区、候选与逐图状态。中断项由用户手动继续，失效原图单独跳过，共用蒙版缺失或损坏时提示重新标记。已另存成品路径及 SHA256 经隔离环境真实重启核对，重复恢复与确认未增加副本。证据见 `output/retouch_resume_v064/validation.json`。已随正式合并部署，画质签收后置。

- 2026-11-09：当前正式运行版本为 `0.6.4-dev`（`V0.6.4 开发版`）。版本源、前端构建、软件内更新日志和正式 API 已同步。原完成任务仍可查询，正式目录及设置哈希一致。

- 2026-11-09：正式启动器在处理任务结束后正常重启，修复 0.6.3 前端仍从旧 0.6.2 后端读取产品版本的问题。正式 API 8787 和前端代理 5173 都返回 `V0.6.3 开发版`，API 机器版本为 `0.6.3-dev`。

- 2026-11-09：版本脚本已将权威源 `product_version.json` 升至 `0.6.3-dev`。Windows 原生 WebView2 桌面从仓库 `packaged_main.py` 启动，系统设置实际显示 `V0.6.3 开发版`，运行 API 的机器版本与权威源一致。版本相关测试 20 项通过。桌面验收使用隔离数据根目录。

- 2026-11-09（V0.6.3 批量压缩与文件交付）：更新压缩结果与交付文案，接入已登记批次的恢复入口、可恢复失败项的定向重试、保留原图的确认交付。桌面验收中，18 张成功与 2 张临时禁写失败的批次重开后只补出 2 份成品。另一批 20 张得到 16 份压缩成品和 3 份原图副本，坏图原因随清单显示。19 份副本内容核验一致，新会话重复确认未新增副本，失效原图被拒绝。详见 `docs/09_CODEX_CHANGELOG.md`。

- 2026-11-04（大图压缩提速候选已授权部署，画质签收后置）：候选两个运行文件及测试SHA与清单一致；旧正式实例已退出，未终止任何既有进程，通过原正式入口启动当前工作区。新后端PID42980、前端PID39864、runtime RUN-20261104T152611-3ED3C67DBA，前后端和正式目录就绪。正式PNG冒烟处理20.178秒，成品6,093,631字节且与部署前候选SHA相同，RGBA差异0、原图不变。此单次验证不替代既有三组性能结论；正式dist162文件、设置、版本及范围外源码保持。负责人明确暂不冻结；阶段BLOCKED / NOT_READY，人工签收PENDING。部署证据：output/compression_speed_20261104/deployment_20261104/。

- 2026-11-04（V0.6.2 A线大图压缩保真提速候选，未部署）：以开工工作区建立三张真实图各三次基线，并以开工文件副本补做旧/新交错三组成对复测。长截图引擎中位54.56→37.38秒（下降31.50%）、大尺寸PNG34.66→25.31秒（下降26.97%）；相机JPG13.60→14.25秒（上浮4.75%，在10%以内）。所有对应输出SHA及字节数保持一致。仅优化静态PNG元数据读取：完整遍历包含IDAT后元数据的PNG块、保留CRC及原Pillow文本/ICC安全限制，避免元数据读取反复解码像素；编码、全图无损/JPG质量门和发布验证保持。42项Python、19项Node、隔离构建、8873真实界面上传—压缩—预览、混合批量、损坏输入、取消、Result继续压缩及52,910,682字节接收通过；透明WebP全RGBA一致。仅隔离运行，正式dist的162个文件及用户主程序PID14224保持。候选在 `output/compression_speed_20261104/deployable/`；人工画质签收前阶段仍BLOCKED / NOT_READY，不冻结或自动部署。见 `output/compression_speed_20261104/REPORT.md`。

- 2026-11-04（同位置批量瑕疵修复已按负责人要求部署）：取消50MB限制的批量/单图修复已更新正式dist并启动真实桌面主程序，版本仍0.6.2-dev，运行端口8787、PID25252，build V0.6.2-dev+b4fdde85dc03.dirty.20261104T015910829Z；实际静态资源SHA及批量API核对一致，目录与LaMa就绪。完整旧dist已备份，原隔离宿主保留。用户要求后续再测画质；负责人尚未签收，阶段BLOCKED / NOT_READY不变。本轮授权只解除此前“不部署”的限制，不构成冻结。证据：output/retouch_batch_20261104/deploy_20261104/。

- 2026-11-04（同位置批量：真实界面验收与取消50MB上限，覆盖下方同日开发阶段的UI缺口）：真实界面已完成三图导入、多区域/画笔/擦除、切图、逐图试修、旧预览失效、顺序执行、取消、逐张及勾选另存、输出中心和原单图两轮修复回归。三张界面正式结果范围外变化均0；单图两轮及并集之外均0。按负责人追加要求，单图/批量/已有成品继续修复均取消文件字节大小限制，54,020,156字节有效PNG通过API和两种界面入口，保留格式、解码及像素安全检查。另最小修复正式Task原图链接依赖临时修复会话的问题，重载后仍可完整读取。23项受影响API＋1项链接回归、26项Node和隔离构建通过；10项未失效的真实LaMa算法/Alpha证据复用。最终界面原图/成品完整加载，修复后接口与控制台无新增错误；早期隔离宿主两个漏挂读接口及原图链接404记录保留并已闭环。版本仍0.6.2-dev，未部署正式dist/主程序，8787/5173与压缩工作、设置、原图及其他未提交成果保持。`STAGE_RESULT=BLOCKED / FINAL_STATUS=BLOCKED / FREEZE_STATUS=NOT_READY / SELF_AUDIT=FAIL`，唯一剩余项为负责人对真实整图和100%局部签收。见 `docs/reports/V062_RETOUCH_BATCH_20261104.md` 及 `output/retouch_batch_20261104/ui/`。

- 2026-11-04（V0.6.2 瑕疵修复：同位置批量）：实现现有页面的多图入口、共用最终蒙版、逐图覆盖/试修、固定快照顺序执行、逐项状态、取消及明确确认另存。方向归一化后像素尺寸不同或损坏输入逐张排除；每图独立 Source/Task/Result，保留 batch/item 和蒙版版本/哈希。复用原 LaMa、正式命名、元数据与防覆盖发布，未修改压缩、输出中心合同或依赖。32 项直接相关 Python（含真实 LaMa 单图/Alpha/DPI 回归）、26 项 Node 和隔离前端构建通过；三张真实照片（3648×5472）正式结果完整解码、范围外变化像素均为0，路径/字节/SHA登记一致，输出中心 API 逐图匹配。真实取消为1张候选保留、2张取消、正式结果0。Computer Use 停止要求继续生效，未部署或替换当前主程序/正式 dist，真实界面导入—标记—切图—执行—保存—输出中心及负责人视觉签收仍未完成；`STAGE_RESULT=BLOCKED / FINAL_STATUS=BLOCKED / FREEZE_STATUS=NOT_READY / SELF_AUDIT=FAIL`。唯一剩余主任务为获准恢复界面工具后完成上述界面验收及负责人签收，不进入下一阶段。用户更新说明暂存本阶段报告，未写成软件已验收发布记录；压缩当前合同和既有 BLOCKED 状态保持。详见 `docs/reports/V062_RETOUCH_BATCH_20261104.md`、`output/retouch_batch_20261104/real/real-validation.json`。

- 2026-11-01（A线原有压缩能力同图回归定位）：以用户反馈的3840×2161 PNG（SHA256 `9839ace5…fabf940`，6,596,005字节）对照已保存旧源副本和当前引擎。旧智能模式自动转JPG为520,511字节、减容92.11%；旧保持PNG与当前默认PNG均为6,093,631字节、减容7.62%，两份PNG的SHA完全相同；当前显式JPG与旧智能JPG也逐字节相同。首个有效差异为删除不透明PNG自动进入JPG候选的路由，非同格式PNG编码退化，未发现全局逐像素门槛误挡JPG。主程序PID9200正式同图重测得到相同文件，默认PNG24.92秒、显式JPG6.02秒；旧与当前质量门槛及搜索/择优规则保持。依照本轮默认源格式与禁止自动跨格式合同，不恢复自动转JPG；本轮算法及配置零修改，只更新定位记录。未新增编码器或量化实验，既有A线整体BLOCKED/NOT_READY及UI UNKNOWN保留。证据：`output/compression_regression_20261101/REPORT.md`。

- 2026-11-01（A线导入解码提示修复）：指定相机目录的57张JPG带MPF高清缩略图，旧单帧判定误拒，并统一显示为“图片无法通过完整解码校验”。已限定识别主图与依附缩略图，二者仍完整解码；真正多画面、动画及损坏缩略图仍拒绝。正式处理还发现GPS IFD偏移被误当内容比较，现改为比较真实GPS字段。`IMG_1032.JPG`正式结果10,577,993→2,256,825字节（节省78.66%），引擎14.47秒、含导入HTTP合计19.20秒；显示尺寸3648×5472、72DPI及原图SHA保持。`IMG_1105.JPG`为6,343,748字节全零文件，准确拒绝。23项最终相关回归通过，正式后端PID9200已加载修复。压缩候选与质量阈值未调整；本次技术故障已关闭，既有A线整体STAGE_RESULT=BLOCKED、FREEZE_STATUS=NOT_READY仍保留，Computer Use未恢复，UI与最终人工视觉验收UNKNOWN。证据：`output/compression_decode_20261101/REPORT.md`。

- 2026-11-01（A线恢复原策略，当前执行合同）：本轮恢复原JPG候选及质量门槛，覆盖此前“所有压缩统一逐像素一致”规则；默认保持源格式，跨格式仅显式选择。压缩只降低字节体积，像素宽高、比例和DPI不变。保留50MiB解除、去重复及异常修复，并修复PNG 96.012 DPI转JPG的精度保存。四张真实图默认PNG节省1.48%–13.86%，手动JPG节省65.64%–68.22%；15次正式处理尺寸/DPI全部保持，单图、批量、继续压缩和52,910,682字节文件已验证。29项Python、24项Node及构建通过，实际主程序PID19336已加载新构建。Computer Use仍停止，界面与最终人工视觉验收UNKNOWN；STAGE_RESULT=BLOCKED、FREEZE_STATUS=NOT_READY。下方旧阶段记录仅为历史，不再作为当前压缩合同。证据：output/compression_restore_20261101/REPORT.md。

- 2026-11-01（A线固定 Oxipng 对照）：独立实验完成，5 张去重输入及一个透明合同夹具均通过完整像素/元数据验证；四张真实 PNG 最终减容 6.04%–8.78%，编码器调用 4.22–18.51 秒、完整实验链 9.01–31.11 秒；52.9MB 压力夹具的结果比现有最佳大 2,928 字节。决策为暂不接入默认生产链，结束本轮参数尝试：减容已证实，同时提速未证实。正式代码、构建、进程、设置及原有 A线 BLOCKED / NOT_READY 状态不变，未进行 UI 验收或 Git 写操作。证据：`output/compression_20261101/oxipng-o2-experiment/REPORT.md`。


- 2026-11-01（A线单图定位）：2.png / 1649×4351 / 5,209,388字节的三个无损DEFLATE策略均正常，但最小候选为5,234,239字节，故保留原图；没有最低减容比例误拒。已修正“已接近最优”为“本次无损优化未减小文件，已保留原图”，构建和正式主程序接口已更新，同图正式复测耗时7.304秒，仍节省0%。Computer Use未重试，视觉验收未执行；减容目标未实现，STAGE_RESULT=BLOCKED、FREEZE_STATUS=NOT_READY。证据：output/compression_20261101/single-1649x4351/REPORT.md。

- 2026-11-01：按负责人本轮要求，仅回开图片压缩的 50 MiB 接收限制、处理耗时与压缩策略。该轮历史硬约束为“画质不能有任何变化”（已被上方恢复指令替代）：当时的候选代码仅发布全图像素、Alpha 与颜色信息均保持的无损结果；JPG 无已验证的系数级无损优化器时保留原图，不承诺固定 90% 减容。代码、独立构建与直接相关测试已完成；界面工具因无法可靠识别浏览器地址而中止，完整页面上传流程未验收，正式 8787 进程与 `dist` 未替换。本轮 `STAGE_RESULT=BLOCKED`、`FREEZE_STATUS=NOT_READY`，不改变其他冻结能力。证据见 `output/compression_20261101/REPORT.md`。

- 2026-10-29：负责人宣布 V0.6.1 收口，进入 V0.6.2（`product_version.json` 已经项目升版脚本改为 `0.6.2-dev` / `V0.6.2 开发版`；负责人所说的“开发者预览版”按现有版本合同落为“开发版”阶段）。V0.6.1 颜色范围见 `V0_6_1_COLOR_SCOPE`；S67、S68 顺延至 V0.6.2。
- 当前产品版本单一权威来源为 `product_version.json`；当前统一运行身份与开发阶段标识均为 `V0.5.8-dev`。
- 当前构建身份由 Vite 在构建时固定注入，组合产品版本、Git短SHA、工作区clean/dirty状态与UTC构建时间；正式页面运行时不依赖Git。
- 当前分支基线：`codex/image-processing-routing-v1`。
- 当前开发阶段：V0.5.8开发中；V0.5.7 Capability Scope Closure只能作为历史边界记录，状态为`BLOCKED_FOR_PRODUCT_NAMING_DECISION`，且因当前权威代码基线已推进至V0.5.8-dev，不能从本工作树直接冻结V0.5.7 Release Candidate。UI-05-FIX-AUDIT 已完成，人工视觉签收仍为 `PENDING`，版本发布冻结仍为 `NO`。
- UI-004 已关闭“结果资源不可读取但仍可确认交付”和“未知路由读取空元数据导致白屏”两个 P0；UI-05-FIX-AUDIT 进一步关闭了瑕疵修整结果页刷新或深链进入后错误宣称可恢复旧工作台的问题。同一存活会话显示“返回调整”，无匹配会话上下文时只显示“重新处理”并进入干净导入流程。
- 阶段1图片压缩正式版保持冻结，本轮只复用其任务与输出规则。
- V0.5.7商业颜色恢复的D57-COLOR-03技术基础已完成至R11。D57-COLOR-04已完成能力边界收口：当前只属于存在未关闭证据缺口的隔离研究原型，不进入正式运行链，不代表商业颜色恢复成立。D57-COLOR-02已有11条真实来源记录，但尚未达到合同要求的30组完整材料，Ground Truth和数据权利证据均未成立。
- 当前版本级真实性核验仍发现一项跨版本风险（原“4K仅为Lanczos尺寸适配却名为4K画质增强”的风险已于2026-10-29随4K v3冻结关闭）：D57冻结报告绑定V3 v0.9，但当前隔离源码与直接测试已漂移至v0.10且未建立对应冻结证据。批量水印已由权威版本`0.5.8-dev`承接，不再属于V0.5.7版本归属冲突。

## 4K最终冻结状态（2026-11-13，产品负责人认可 v4）

```text
4K_V4: PASS_AND_FROZEN
CONTRACT: 4k_v1_contract_2.1
ROUTE: REALESRGAN_X4PLUS_FIDELITY_FUSION（标识沿用以兼容已登记成品；实际模型见下）
SR_MODEL: realesr-animevideov3-x3（原 realesrgan-x4plus）
FUSION: v4（亮度分频融合，色度取原图放大）
QUALITY_CAPABILITY_BOUNDARY / COMPLETED_CONCLUSION: 不变
```

- 重开原因：负责人反馈 4K 成品尺寸达标但画质无可感提升。实测 v3 的 4 轮反投影把成品锁回原图，保留下来的细纹多为皮肤颗粒与织物假线，小字笔画变细断开。
- v4 做法：反投影只锁低频明暗；中频跟随超分并限幅提升，超分改动不得超过原图局部结构幅度的 0.25 倍；细纹取消纹理回补、肤色降权；极小字只用原图放大底图锐化，不用超分。
- 已验证：5 张样本（负责人样本 + S01/S03/S05/S07）屏幕观看尺寸清晰度为直接放大的 1.20–1.42 倍（v3 为 1.17–1.28 倍），小字完整无黑边，平坦区颗粒低于 v3，体积小 9–22%；3 张真实照片（2 风景 + 1 合影）与原模型融合结果相当。正式入口与原型逐像素一致；真实应用后端上传→任务→成品登记→取回文件通过，单张约 6–9 秒（v3 约 72–79 秒）。
- 2026-11-13 产品负责人查看正式代码产出的对比样张后认可画质并要求冻结。未做：Claude 未在桌面界面内做目视验收；真实人像特写未专项测试；运行中的后端需重启才生效。清晰度提升幅度有限，受“不重绘、不凭空生成细节”边界约束。
- 受保护：4K v4 的算法参数、模型、合同与验收门禁未经产品负责人明确要求不得改动；改动须先说明理由并重新做样本验收。
- 证据：`artifacts/e4k_v4_poc/REPORT.md`（本地，不入库）。
- 2026-11-18 失真自查（负责人要求，负责人看对照图后认可保留）：修正 16 位灰度过曝、CMYK 配置文件未转换、透明抠图边缘描边、高饱和色交界色边四类失真；亮度融合参数不变，合同升为 `4k_v1_contract_2.2`。证据 `artifacts/4k_distortion_check_20261118/REPORT.md`（本地）。
- 2026-11-18 文字清晰度正式接入（负责人决定并签收，PASS_AND_FROZEN；参数、模型、合同未经负责人要求不得改动）：PP-OCRv3 中文文字检测（Apache-2.0，SHA 校验）圈出文字区，区内亮度取超分并受原图邻域范围与笔画面积保护，区外与 v4 逐像素一致；模型不可用时退回 v4 并在报告注明。合同 `4k_v1_contract_2.3`。证据 `artifacts/4k_text_clarity_integration_20261118/`（本地）。
- 下文 4K v3 冻结记录（2026-10-29）已被 v4 取代，仅作历史记录；其中处理链描述、`CONTRACT 2.0` 与“约 1–3 分钟/张”对应 v3。

## 4K v3 冻结状态（2026-10-29，历史记录，已被 v4 取代）

```text
4K_V3: PASS_AND_FROZEN
CONTRACT: 4k_v1_contract_2.0
ROUTE: REALESRGAN_X4PLUS_FIDELITY_FUSION
QUALITY_CAPABILITY_BOUNDARY: SR_DETAIL_ENHANCEMENT_WITH_SOURCE_FIDELITY_GUARD
COMPLETED_CONCLUSION: DETAIL_ENHANCEMENT_COMPLETED
REAL_VISUAL_GAIN: PROVEN_ON_9_SAMPLES_AND_IN_APP
LANCZOS_FALLBACK: REMOVED（超分失败即任务失败，不静默回退）
FROZEN_COMMITS: 39c591f（v2）/ 1b50364（v3）/ 730d7eb（软件内验收记录）
```

上一版冻结结论（`PILLOW_LANCZOS_SAFE_RESIZE`、`REAL_VISUAL_GAIN: NOT_PROVEN`、`FORMAL_AI_INTEGRATION: NO`）已由产品负责人2026-10-28决定取代，仅作历史记录。

## 4K已确认事实

- 正式 `4k_v1` 处理链：Real-ESRGAN x4plus（ncnn-vulkan，项目内置）原生4倍超分 → 缩至长边3840；低频取原图 LANCZOS 放大（防色偏）、高频取超分并补回被抹平的原图纹理；按原图测量分区控制强度（平坦区/皮肤减弱、高反差轮廓/发丝柔性封顶、极小字单独平滑接续 + 有界锐化）；最后4轮反投影，使成品缩回原图尺寸时与原图一致。不裁切、不拉伸、不补边，原图只读。
- 9 张样本（8 张金样本 + 产品负责人反馈海报）：清晰度与高反差细节显著高于 LANCZOS；与原图一致性 PSNR 43.5–67.5 dB，全部高于 LANCZOS；色偏 ≤0.16/255；同参数结果逐像素稳定。
- 2026-10-29 软件界面内验收 3 张（海报、S07 极小字、S03 人像）：全部完成，成品与 v3 逐像素一致，原图哈希不变；目视确认小字笔画干净连贯、发丝无硬线、皮肤无超分网格颗粒。
- 证据：`artifacts/4k_v2_testset/4K_V2_GOLDEN_TEST_REPORT.md` 与 `evidence/`（本地，不入库）。

## 用户可见能力边界

- 可表达：保持原图比例与构图，长边提升至3840像素，超分重建细节并以原图保真融合，防止色偏、重绘与过锐光晕。
- 不可宣称：恢复原图中已无法辨认的文字或细节、去除压缩噪点、纠正原图中错误的字形。
- 原图长边 ≥3840 不处理；处理约 1–3 分钟/张，依赖 Vulkan，超分引擎不可用时任务明确失败。

## 受保护能力

- 4K v3 冻结：算法参数、路线、合同与验收门禁未经产品负责人明确要求不得改动；改动须先说明理由并重新做样本与软件内验收。
- 1080P既有冻结能力不因4K变更而重开。
- 原图、Settings、正式目录、4K历史PoC与阶段证据保持不变。
- 未覆盖、未确认：PPT截图、实拍风景照两类样本尚未专项测试。

## V0.5.7 D57商业颜色恢复阶段状态

```text
D57_COLOR_00: COMPLETE
D57_COLOR_01: COMPLETE
D57_COLOR_02: INCOMPLETE_INSUFFICIENT_CONTRACT_COMPLETE_REAL_EVIDENCE
D57_COLOR_03: TECHNICALLY_COMPLETE
D57_COLOR_03_R1: REVOKED_BY_AUTO_AUDIT
D57_COLOR_03_R2: REVOKED_BY_AUTO_AUDIT
D57_COLOR_03_R3: REVOKED_BY_AUTO_AUDIT
D57_COLOR_03_R4: REVOKED_BY_AUTO_AUDIT
D57_COLOR_03_R5: REVOKED_BY_AUTO_AUDIT
D57_COLOR_03_R6: REVOKED_BY_AUTO_AUDIT
D57_COLOR_03_R7: REVOKED_BY_AUTO_AUDIT
D57_COLOR_03_R8: REVOKED_BY_AUTO_AUDIT
D57_COLOR_03_R9: REVOKED_BY_AUTO_AUDIT
D57_COLOR_03_R10: REVOKED_BY_AUTO_AUDIT
D57_COLOR_03_R11: COMPLETE
WORKING_COLOR_SPACE: sRGB_IEC61966_2_1
SUPPORTED_AUTO_INPUT: SINGLE_FRAME_8BIT_RGB_RGBA_JPEG_PNG_SRGB
INPUT_METADATA_CONFLICT: SAFE_BLOCKED
SRGB_PROFILE_IDENTITY: CMM_SEMANTIC_EQUIVALENCE_VERIFIED
PNG_OUTPUT_ICC: VERIFIED_SRGB
JPEG_OUTPUT_ICC: VERIFIED_SRGB
ALPHA_PRESERVATION: PIXEL_EXACT_AND_TRANSPARENT_EDGE_VERIFIED
RGBA_ANALYSIS_DOMAIN: ALPHA_GT_1_PERCENT_VISIBLE_ONLY_INCLUDING_PERSON_REGIONS
PERSON_REGION_COORDINATE_CONTRACT: SOURCE_IMAGE_XYWH_MAPPED_ONCE_TO_D1_ANALYSIS
PERSON_REGION_RESOLUTION_CONTRACT: D1_BOUND_AUTO_EXPLICIT_NONE_OR_EXPLICIT_BOXES
PERSON_REGION_DECISION_BINDING: PRIVATE_PROCESS_LOCAL_D1_INSTANCE_OWNER_HMAC_SEAL
D2_CANDIDATE_IDENTITY: V2_WITH_OPAQUE_PERSON_REGION_CONTEXT
BRAND_COLOR_GATE: EXISTING_FULL_DELTA_E_FAIL_CLOSED_NOT_COMMERCIAL_FROZEN
TRANSPARENT_EDGE_REFERENCE: D3_SOURCE_PARAMETER_REPLAY_PER_PIXEL
TRANSPARENT_RGB_VECTOR_GATE: SOURCE_REPLAYED_PER_PIXEL_MAGNITUDE_AND_JOINT_RGB_VECTOR
TRANSPARENT_COMPOSITE_GATE: D3_SOURCE_PARAMETER_REPLAY_AND_ALPHA_COMPOSITE_CONTINUITY
D2_EXECUTOR_PIXEL_TRACE_AUTHORITY: NONE_DIAGNOSTIC_ONLY
D2_CROSS_AFFINE_FIT_AUTHORITY: NONE_CONSISTENCY_CHECK_ONLY
CROSS_AFFINE_D3_REFERENCE: INDEPENDENT_SOURCE_EVIDENCE_REFIT
LOCAL_OPAQUE_REFERENCE_AUTHORITY: DIAGNOSTIC_ONLY_NOT_AUTHORIZING
16BIT_AUTO_SUPPORT: SAFE_BLOCKED
NON_SRGB_WIDE_GAMUT: SAFE_BLOCKED_PENDING_VALIDATED_GAMUT_MAPPING
D57_COLOR_04: RESEARCH_PROTOTYPE_WITH_UNCLOSED_EVIDENCE_GAPS
D57_COLOR_04_GO_NO_GO: NO_GO_INSUFFICIENT_REAL_EVIDENCE
D57_COLOR_04_PRODUCTION_ROUTE: NONE
V3_WHITE_BALANCE_PROTOTYPE: VALID_ISOLATED_RESEARCH_IMPLEMENTATION_CONTROLLED_FIXTURES_ONLY
V3_WHITE_BALANCE_SAFETY_GATE: PASS_CONTROLLED_ENGINEERING_SCOPE
PROVENANCE_ATOMIC_SNAPSHOT_TECHNICAL_GATE: PASS
CALLER_SUPPLIED_MASK_PROTECTION: PROVEN_CONTROLLED_FIXTURES_ONLY
AUTO_PROTECTED_REGION_COVERAGE: NOT_PROVEN
ARTIFACT_VALIDATOR: NOT_ESTABLISHED
THRESHOLD_PROVENANCE: FIXED_ENGINEERING_CONSTANTS_NOT_COMMERCIALLY_CALIBRATED
THRESHOLD_USE_SCOPE: RESEARCH_ONLY
REAL_SOURCE_RECORDS: 11
REAL_GT_RECORDS: 0
DATA_RIGHTS_COMPLETE_RECORDS: 0
REAL_SOURCE_STATUS: PARTIAL_REAL_SOURCE_RECORDS_AVAILABLE
REAL_DATASET_STATUS: INSUFFICIENT_11_OF_30_AND_NOT_CONTRACT_COMPLETE
REAL_GT_STATUS: MISSING
DATA_RIGHTS_STATUS: NOT_PROVEN
COMMERCIAL_COLOR_RESTORATION_V1: NOT_PROVEN
D57_04_BLOCKS_V0_5_7_RELEASE: NO_RESEARCH_PROTOTYPE_ISOLATED
```

- 正式Color Core V2保持`PASS_AND_FROZEN`；正式入口为`engine.color_correction.formal_runtime.run_formal_color_runtime()`，当前包导出、API和正式运行链均未引用D57-COLOR-04。
- D57-COLOR-02合同仍要求至少30组真实开发材料。当前Manifest有11条真实来源记录，但没有GT字段和权利字段，且绑定的是早于当前V3原子快照修复的v0.7源码；它只能作为历史真实来源执行记录，不能证明当前v0.10真实样本效果、商业泛化或商业GO。
- D57-COLOR-04当前已证明范围仅包括受控夹具中的确定性白平衡、来源/候选/Alpha/调用方硬Mask的证据绑定、私有连续只读处理快照和正式链隔离。自动文字、Logo、肤色、品牌色区域识别，商业阈值校准、独立正式Artifact Validator、真实GT效果和商业直接使用率均未证明。
- 缺少独立Artifact Validator在当前只允许开发/实验、禁止生产自动采用和商业证据晋级的边界下属于`KNOWN_RESEARCH_LIMITATION`，不授权新增开发或自动晋级。
- 商业颜色恢复研发只有在足量真实Source、合法可追踪来源、明确研究/商业权利、可靠GT/Reference、合同场景覆盖、自动保护区域能力、商业阈值合法校准、必要Artifact Validator和独立审核九项条件全部满足后才允许重新打开。
- D57-COLOR-02的程序生成色块、渐变、Alpha和异常Profile测试图不计入开发集或商业质量证据。
- 2026-08-31用户明确决定在D57-COLOR-02合同完整材料尚未成立时继续隔离研究；该授权只建立未接入正式运行链的V3白平衡原型，不改变30组完整材料、GT和权利证据等商业门禁。
- V3白平衡隔离原型在线性sRGB中使用分散中性色证据形成有界色适应候选，逐像素恢复硬保护区、Alpha小于等于1%的隐藏RGB及完整Alpha，并只生成`ISOLATED_REVIEW_ONLY`候选。
- V3白平衡上一版以相邻同源颜色和候选修正连续性判断半透明边缘，自动审核证明整片半透明区域同步偏色时，候选像素可以互相授权，原“安全门禁已关闭”结论因此撤销。
- V3白平衡v0.3虽然消除了候选像素互相授权，但自动审核证明其Alpha黑/白底指标只比较候选与同算法重算，能够证明实现一致却不能证明重算结果本身安全；一个没有不透明同源支持的孤立半透明像素被改动9字节后仍得到安全PASS。审核还证明受控暖、冷夹具的合法重算差均为0，而未证明必要的1字节容差可放行整片同步偏移，因此v0.3未通过自动审核。
- V3白平衡v0.4将门禁拆为候选重算完整性和Alpha结果安全两部分。实际候选必须与源图独立float64重算逐字节完全一致；Alpha结果只从至少4个相近不透明源像素形成可信种子，并在最长12像素内沿源色相近且独立重算修正连续的路径传播授权。无可信源支持的半透明像素或修正场不连续均安全阻断；同时分别记录源图到重算结果的RGB及Alpha加权黑/白底合成变化，黑白底不冒充两份独立证据。后续自动审核证明该版本仍未隔离全局光源证据域，因此不能关闭安全门禁。
- V3白平衡v0.4自动审核构造了零全不透明中性像素的RGBA反例：240个`Alpha=3/255`近透明中性像素只有约2.82个全不透明像素的可见贡献，却因数量、空间覆盖和中位数均按未加权像素计算而获得完整光源估计权；门禁返回`CANDIDATE_READY`并改变400个不透明产品像素。逐字节重算一致性只能证明执行符合算法，不能纠正光源证据本身无权授权的问题。
- 冻结记录中的V3白平衡v0.9将颜色应用域与光源证据域分离，并把合法颜色管理解码结果绑定到私有、连续、只读的处理快照；该记录当时的复验结论为V3 25/25、颜色回归116/116、正式颜色API 37/37，并发探针6/6通过、证据篡改探针3/3阻断。当前隔离源码已是v0.10，未与该v0.9冻结记录重新绑定，因此这些历史结果不能直接证明当前v0.10；它们也从未证明商业阈值、正式集成或真实图片效果。
- 正式颜色运行链现通过单一内部颜色管理边界读取源图；D1、D2和D3使用同一份显式sRGB/RGB工作域像素，避免重复解码造成工作域不一致。
- sRGB ICC身份由Pillow ImageCms/LittleCMS颜色变换语义验证，不依赖Profile名称；无ICC的8-bit RGB/RGBA仅在PNG sRGB/gAMA/cHRM及EXIF/Interop元数据不存在冲突时按明确sRGB假设处理；输出JPEG和PNG均写入与像素匹配的sRGB ICC。
- 损坏ICC、伪装为sRGB但色度语义已改变的ICC、输入元数据冲突、非sRGB宽色域、CMYK、多帧和未证明全链原生精度的16-bit PNG均安全阻断，不静默转换或降为8-bit。
- D2在完全透明像素恢复源RGB并保持Alpha逐像素一致；R1至R4分别因异常值补偿、RGB联合关系丢失、跨对象借色、候选与执行器轨迹同源等授权缺陷被撤销。R5虽然让曝光和Safe-WB走独立数学重放，但Cross-Affine仍直接采用D2记录的拟合矩阵，矩阵与候选同步损坏时可以自我授权；同时D2/D3的颜色、曝光和人脸分析未统一排除隐藏及近透明RGB，因此R5也被撤销。
- R6完成了D2/D3主要RGBA分析域统一与Cross-Affine独立源证据重算，但自动审核发现D1的两处人物框掩码未与有效Alpha域相交。人物框覆盖隐藏或近透明像素时，这些RGB仍可进入肤色中位数、人物覆盖与脸部曝光事实，因而R6完成声明被撤销；其Cross-Affine独立重算结论不受影响。
- R7将D1人物场景事实和主决策路径的人物掩码都限制为人物框与Alpha大于1%有效域的交集。在其未触发D1缩放的小图覆盖范围内，相同可见图像、相同Alpha和相同显式人物框下，仅改变低Alpha RGB时，D1除源指纹外的语义、D2参数与可见候选、D3门禁与最终动作保持一致。完全透明像素的原始隐藏RGB与全部Alpha仍逐像素保留；颜色候选仍只能进入人工复核，不能自动交付。
- R7自动审核随后发现显式人物框仍按原图坐标直接用于最长边960像素的D1分析图；真实大图会让D1分析错误人物区域，而D2/D3继续使用正确原图区域，因此R7完成声明被撤销。
- R8明确显式人物框为原图`(x, y, width, height)`坐标，仅在D1内部按实际分析宽高比例映射一次；D1自动检测本来产生分析图坐标，不再二次缩放。大于960像素的RGBA回归现同时约束正确可信肤色区域、隐藏RGB隔离、D2可见候选一致和D3最终裁决一致。
- R8自动审核随后发现人物区域的“存在性与来源”没有跨阶段绑定：D1区分`None`自动检测和`[]`明确无人，D2却把两者都当成自动检测，D3又把两者都折叠为空并在可信重放中独立检测；正式链因而可能让D1、D2和D3使用三组不同人物区域，R8完成声明被撤销。
- R9由D1形成了私有三态人物区域契约，但自动审核证明该摘要只验证契约自身，能够把同一源图另一份完整有效契约整体替换到当前D1决策；R9还把曝光品牌门禁改成未获D57-COLOR-02参考样本授权的新Lab a/b阈值，且公开审核记录没有对应`brand_delta_ab`，无法复算`BRAND_COLOR_PASS`。R9完成声明因此撤销。
- R10将人物区域契约与完整D1语义快照做私有封印，但自动审核用两份公开`to_dict()`完全相同、人物框坐标不同的D1决策证明：把第二份决策的区域合同和绑定值整组复制到第一份新实例后，R10仍接受该凭据。该绑定只认证可转移内容，没有认证签发对象；R10完成声明因此撤销。D2候选身份V2仍能绑定已经进入D2的区域上下文，但不能补救上游D1错误授权。
- R10撤销R9未授权的曝光品牌a/b阈值，颜色与曝光候选统一恢复使用既有完整Delta-E品牌保护门禁；`BRAND_COLOR_PASS`可由正式记录已有的`brand_delta_e`直接复算。现有D01_04曝光候选通过曝光目标门禁但未通过品牌保护，正式链安全选择原图，不生成候选输出、不进入输出中心或智能交付。该结果不冻结商业阈值，也不证明商业颜色恢复完成。
- R11将人物区域绑定升级为进程内随机密钥签发的实例级HMAC封印，封印输入同时覆盖决策对象身份、完整公开D1语义和私有区域合同，并以不延长对象生命周期的弱引用校验原签发实例所有权；完整复制合同与绑定值到任何不同D1实例都会在执行像素前安全阻断，即使原实例已释放也不能借对象ID复用转移凭据。解析器同时只接受精确`ColorUsabilityDecision`类型，结构仿冒对象即使复制全部字段和私有凭据也以`INVALID_D1_DECISION_TYPE`阻断。两个运行字段继续不参与公共构造器、对象相等性、Shadow、Replay、API或正式结果序列化。
- R6至R11只修改D1/D2/D3的RGBA分析域、人物坐标与绑定解释、D2颜色/曝光候选分析、D3独立审计重放及其直接测试，并对Color Core内部目标计算增加可见域输入；公共API结构、SSE、FinalAction枚举与语义、页面、Settings、正式目录和产品版本均未改变。R11为行为与证据可追溯性更新D1/D2/D3及正式运行内部版本值。

## S64 AI图挑档校色（2026-10-28）

```text
S63_AICOLOR_POC: POC_VALUE_NOT_PROVEN（自动判定不成立；真偏色图修正有效且安全）
S64_PRODUCT_DECISION: APPROVED（用户说修才修、修多少由用户挑）
S64_A_BACKEND_API: PASS_AND_FROZEN（4K 预览耗时：负责人接受空闲达标、负载下变慢）
S64_B_PAGE: PASS_AND_FROZEN（负责人 2026-10-28 签收）
S64_AI_COLOR_LEVEL_PICK: COMPLETE
S65_REFCOLOR_POC: REVIEW_PACKAGE_READY（R3 价值成立，代判）
S66_REFERENCE_LEVEL_PICK_DECISION: APPROVED（方案 A：升级“参考图校色”页签）
S66_A_BACKEND_API: PASS_AND_FROZEN（预览耗时：负责人接受空闲达标、降频或负载下变慢）
S66_B_PAGE: PASS_AND_FROZEN（参考图页签已改为四档挑选；真实桌面 4 组通过；负责人 2026-10-28 签收）
S66_C_REFERENCE_ADVICE: PASS_AND_FROZEN（提示改为说明结果方向；目标已正常且参考偏色时建议原图；像素 99/99 不变；负责人 2026-10-29 签收，纳入 V0.6.1）
S67_AUTOCOLOR_POC: POC_VALUE_NOT_PROVEN（负责人 2026-11-14 裁定；新规则安全但很少触发：26 张已知偏色修正 4 张、15 张真实图 0 张；路线停止，不集成，自动校色保持现状）
S68_REFTONE_POC: BLOCKED，DEFERRED_TO_NEXT_VERSION（第二轮技术门禁全部通过，G 组强档 ΔE 降幅中位 78.5%，耗时 ≤0.83 s；缺 S 组同系列样本；负责人 2026-10-29 裁定顺延，不纳入 V0.6.1）
V0_6_1_COLOR_SCOPE: CLOSED（纳入：S64 挑档校色、S66-A/B 参考图挑档、S66-C 提示方向与建议档位，均为 PASS_AND_FROZEN；顺延：S67、S68）
S69_COLOR_FULL_SCAN: COMPLETE（2026-11-13，只读；报告 artifacts/s69_color_full_scan/REPORT.md）
S69_A_LEVEL_PICK_MEASUREMENT: PASS_AND_FROZEN（2026-11-14 负责人签字；门禁 1、2 只考核 ΔE≥4 样本；建议档位封顶为“轻”；13 张对照图复验通过；未做正式部署）
S69_D_COLOR_INPUT_FORMAT: PASS_AND_FROZEN（2026-11-14；调色板、灰度、灰度加透明、1/2/4 位 PNG 与灰度 JPEG 无损展开后可校色；CMYK、16 位等保持拒绝并给出具体原因；未做正式部署、未在桌面软件内实测）
S69_E_COLOR_LEVEL_PICK_SPEED: PASS_AND_FROZEN（2026-11-14；4K 参考图预览 8.2→4.7 s，选档出成品挑档 8.9→5.3 s、参考图 8.1→3.8 s；像素不变，PNG 成品体积约 +10%；未做正式部署、未在桌面软件内实测）
S69_F_COLOR_KEEP_ORIGINAL_DISPLAY: PASS（2026-11-14；仅前端：自动校色保留原图显示“已保留原图”与说明，不显示进度和红色错误；后端 D61-02 合同不变；桌面实测 2 张通过；未部署）
S69_G_LEVEL_PICK_NOTICE: PASS（2026-11-14；挑档“可能是有意的设计色调”提醒只在测到偏色（偏黄、偏蓝、偏绿或品红）时显示；黑白、暗调图不再误显示；只改后端 public_level_measurement 一处，接口字段不变；桌面实测 2 张通过；未部署）
S69_B_COLOR_LEVEL_PICK_DEHAZE: BLOCKED（2026-11-14；v3 候选：暗通道判断灰雾、自动色阶式还原。灰雾 A 识别 8/11、去灰中位数 83%；灰雾 B 识别 10/11、中位数 40.6%，但 S01 花卉变差且强档被安全门禁拦下。门禁 1、2、5 未过；正常图零误判、偏色不退化、参考图 99/99 一致、耗时不增。候选归档于 artifacts/s69b_dehaze_candidate/，正式代码仍为 v2）
S71_DEHAZE_POC: BLOCKED，PAUSED_BY_OWNER（负责人 2026-11-14 裁定暂停除雾；2026-11-14；隔离 PoC，暗通道先验加导向滤波，合成雾样本。验证集识别 14/14，但强档去雾中位数 41.5%（要求 ≥50%）、2 例变差；对照图误判 12/24（设计图 9/13）；4K 单档 3.58 s（要求 ≤3 s）；光晕、安全、Alpha、确定性通过；复核图见强档明显偏色（雾色估错）。证据 artifacts/s71_dehaze_poc/；未接入软件）
S74_COLOR_EYEDROPPER: PASS_AND_FROZEN（2026-11-18 负责人签字；挑档校色“点选白点”：用户点一处白或灰，四档按该点校正；签收时改为有白点建议“中”，“强”可手选。门禁 2 负责人裁定排除 S03（原图无白区），48 例强档中位数 82.2%、0 例变差；门禁 1 无点回归 101 张逐字节一致；门禁 3–7 通过。未做正式部署、未提交。证据 artifacts/s74_neutral_point/）
S75_COLOR_BATCH_LEVEL_PICK: BLOCKED，WAITING_REAL_GROUP_SAMPLES（2026-11-18；挑档校色可选 2–20 张，代表图选档（可点白点）后整组按同一校正量处理，代表图人工确认、其余处理中心待复核。门禁 1–5 通过：合成组 42 张“中”中位数 61.8%、“强”77.8%，0 张变差；单张失败不连累；4K 每张 +0.14 s。门禁 6 缺真实同批图（RefSeries 为空）。代码在工作区，未部署、未提交。证据 artifacts/s75_batch_level_pick/）
S76_COLOR_BLACK_POINT: BLOCKED，DEHAZE_LINE_STOPPED_BY_OWNER（负责人 2026-11-18 裁定停下去灰线，不再开展去灰、除雾或黑点新变体；2026-11-18；用户点黑点压暗发灰暗部。合成发灰 8 张“中”档去灰中位数 25.6%（要求 ≥50%）、2 张变差，“强”21.9%；S07 剪切增长、亮部 ΔE 2.27。原因：部分图无真黑；灰雾同时压暗亮部，只校黑点还原不了。未调参，候选归档 artifacts/s76_black_point/，正式代码已撤回至 18d5ac6。去灰线连续第三次 BLOCKED（S69-B、S71、S76））
S77_COLOR_DEFAULT_MODE: PASS_AND_FROZEN（2026-11-18 负责人签字；颜色校正默认进入挑档校色，按钮顺序改为挑档｜参考图｜自动，自动校色模式提示多数图会保留原图，副标题改为不只描述自动校色；三种模式处理逻辑不变。前端测试 406 项通过，隔离浏览器实测通过。未部署、未提交）
S78_COLOR_MULTI_LEVEL_RESULTS: PASS_AND_FROZEN（2026-11-18 负责人签字；单张挑档可勾选 2–3 档，一组预览一次生成多张成品，每档与预览逐像素一致并已确认，结果进处理中心；只选一档不变，整组仍一组一档，文件名规则不改。接口 93、前端 407 项测试通过，4K 两档 13.64 s 对两次单档 14.26 s，隔离浏览器实测通过。未部署、未提交）
LEVEL_PICK_VERSION: hdde.color-level-pick.v2（S69-A 冻结）
LEVEL_PICK_CONTRACT: docs/contracts/HDDE_COLOR_LEVEL_PICK_SUPPLEMENT_V1.md
```

- 新增接口 `/api/color-correction/level-preview` 与 `/api/color-correction/level-run`。用户选定档位即人工确认，复用现有的颜色人工确认交付，不新增 FinalAction。
- 颜色校正页已提供第三种模式"挑档校色"（S64-B），正式 dist 已重建（旧 dist 备份于 output/s64b_level_pick/dist_backup_20261007/）；负责人已签收，S64 已冻结。
- 自动校色、参考图校色、D57 合同与 Color Core V2 冻结记录保持不变。
- 证据：`artifacts/s64a_level_pick/REPORT.md`、`artifacts/s64a_level_pick/validation.json`。

## D线 Color Core V2 最终冻结状态

```text
HUMAN_FINAL_REVIEW: PASS
COLOR_CORE_V2: PROVEN_AND_FROZEN
D_LINE_COLOR_CORE: COMPLETE
GLOBAL_RUNTIME_ROUTE: cross_affine_balanced
LOCAL_RUNTIME_ROUTE: guided_rgb_lab_field_selective
SAFETY_GATE_V2: FROZEN
RUNTIME_GROUND_TRUTH_USED: NO
```

- `/color-correction`已从占位页替换为真实单图自动颜色校正页面。
- 自动处理核心从原始物理文件读取并输出同尺寸、同方向、同格式成品；正式链路保持D-01感知决策、D-02全局明暗、D-03人物局部、D-04回退框架，并接入冻结的`cross_affine_balanced`、`guided_rgb_lab_field_selective`与Safety Gate 2.0，同时不裁切、不拉伸、不补边、不覆盖原图。
- 会议LED屏/亮背景场景采用人脸或可靠前景识别、人物与背景独立亮度度量、局部提亮和高亮背景保护；普通照片不复用会议强校正，低调黑金等设计图启用色彩意图与暗部保护。
- 任务直接复用阶段1同一任务注册表和生命周期，完成态在文件存在、非空、可解码、尺寸/格式/扩展名/SHA256一致且真实像素发生变化后写入。
- 用户结果报告来自实际输入/输出像素；本地问题反馈报告默认不包含原图、结果图、二进制、完整路径或外部上传。
- 正式默认输出目录为`D:\影界文件\输出\颜色校正`；Settings保持不变，不回退项目临时目录。
- V2-G1/V2-G2 evaluation与PoC资产保留为验证证据，不进入正式runtime依赖；正式runtime不读取Ground Truth、样本编号或文件名特判。

## UI-05-FIX-AUDIT 收口

```text
UI_05_FIX_AUDIT: PASS
SAME_SESSION_RETURN_ADJUSTMENT: PASS
REFRESHED_OR_DEEP_LINK_RESULT_ACTION: TRUTHFUL_REPROCESS
FIRST_FORMAL_RESULT_IMMUTABLE: PASS
SECOND_FORMAL_RESULT_REGISTERED_SEPARATELY: PASS
LATEST_RESULT_DELIVERY_BINDING: PASS
BROWSER_CONSOLE_ERRORS: 0
HUMAN_VISUAL_SIGNOFF: PENDING
RELEASE_FREEZE: NO
```

- 审计以真实浏览器先复现缺陷：结果页刷新后，旧实现仍显示“返回调整 / 重新处理”，点击后进入空工作台并报“当前正式结果不属于本工作台上下文”。
- 修复只在前端绑定当前 Result 与仍存活的瑕疵修整会话；有匹配上下文时恢复同一工作台，无匹配上下文时诚实进入重新导入流程。LaMa、Mask、工作版本生成、后端 API、正式结果、Delivery、Color Core V2 和正式目录合同均未改变。
- 隔离真实链验证了首次 Result、返回调整、第二次 Result 与第二次 Result 的 copy-only Delivery；第一次结果文件保持不变，原图 SHA256 在两次结果中一致，交付文件 SHA256 与第二次结果一致且不同于第一次结果。

## V0.5.7版本级能力收口

唯一能力矩阵与Release Candidate候选合同见：

`docs/reports/HDDE_V0.5.7_CAPABILITY_SCOPE_CLOSURE.md`

当前状态：

```text
CAPABILITY_MATRIX_COMPLETE: YES
PRODUCT_CLAIMS_MATCH_IMPLEMENTATION: FAIL
USER_VISIBLE_CAPABILITY_OVERCLAIM_HITS: 36
FROZEN_CAPABILITY_DRIFT_COUNT: 2
RELEASE_BLOCKERS: 4
V0_5_7_CAPABILITY_SCOPE: BLOCKED_NO_CURRENT_V0_5_7_BASELINE
```

## 下一任务

当前权威版本已经进入`V0.5.8-dev`。不得在这个工作树上继续把`V0.5.7_FINAL_PRODUCT_SIGNOFF_AND_RELEASE_FREEZE`当作当前下一阶段；如需追溯V0.5.7签收，必须另行提供明确、只读、可核验的V0.5.7代码快照。当前更合理的下一任务是建立`V0.5.8_CAPABILITY_SCOPE_BASELINE`，并继续保持D57-COLOR-04隔离，不得进入正式Color Core、API、UI、Settings、正式目录或商业产品声明。
