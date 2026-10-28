# S61-OC-02P｜暖重开与分页性能收口

STATUS=PASS_AND_FROZEN

VERSION=0.6.1-dev / V0.6.1 开发版 / DEVELOPMENT

BRANCH=codex/image-processing-routing-v1

HEAD=aa0dd93265d270eb5192ebbd44a1fe14488d454a

STAGING=EMPTY；受保护 dirty 保留；未执行 Git 写操作。开始与结束无本轮所属服务残留，未发现相关并行源码写入。

证据根：`output/playwright/s61-oc-02p-20261004/`。以下计时均为本轮真实测量；旧 OC-02R 的失败报告及原始文件保持不变。

## ROOT_CAUSE

1. `select_output_center_page` 已完成轻量清单读取与分页，`build_output_center_snapshot` 随后再次枚举目录、解析路径、读取当前页文件 stat/header。首次12卡实际37个文件，却出现49次文件头读取；重复阶段增加 Windows 文件探测开销。
2. 同一请求的每个缩略图描述符反复解析、校验相同正式根和缓存目录；批次路径又在缺失判定、冲突检查、文件绑定三个循环中重复 resolve。Registry 的启动磁盘读取只有一次，并非逐卡磁盘重载。
3. 前端在首12卡之后通过1500ms/100ms定时器自动读取全部剩余页。未滚动也会补齐清单，影响暖重开和分页期间的请求节奏。
4. 测量器另有“滚动触发分页后再点击同一按钮”的竞争，导致旧探针超时；只修测量器，并保留 `final-03.log`、`diagnostic-04.log`。`diagnostic-05` 的157–161ms、`stable-03` 的225ms等失败样本均保留，未用来宣称通过。逐调用路径包装的开销也单列，未用于最终门禁。

## FILES_MODIFIED

| 文件 | 本阶段修改 |
| --- | --- |
| `backend/image_compression_api.py` | 请求内复用清单 stat/header、批次路径和一次校验的缓存目录 |
| `src/OutputCenterPage.jsx` | 首12卡后滚动或“加载更多成品”按需分页，锁住同一offset，卸载中止请求 |
| `tests/image_compression_ui/test_output_center_api.py` | 原测试增强为文件头单次读取、缓存根单次解析；保留安全/缺失/解码断言 |
| `tests/image_compression_ui/test_output_center_ui.mjs` | 对齐本轮明确要求的按需分页契约，未减少或跳过测试 |
| `dist/` | 当前 production build 生成物；原29个文件已逐字节备份至证据根 `dist-before/` |
| `docs/09_CODEX_CHANGELOG.md`、本报告 | 追加本轮证据与冻结结论 |

生产与测试的本阶段独立 diff 为证据根 `*-stage-only.patch`，不把仓库已有大幅 dirty diff 归为本轮修改。

## IMPLEMENTATION

当前请求的分页候选只携带已读取的 Path/stat/header，详情只消费选中页；不缓存跨请求的缺失状态。每次新读取仍检查当前真实文件，显式缺失 Result 保留 MISSING 卡片。批次路径只在本请求解析一次，不改变九字段合同、身份、迁移依据和 Result 正式性。

缩略图目录安全检查按请求复用；文件签名、文件级路径校验、缓存验证/损坏重建、768px、40MP预览预算和全局 Pillow 限制均保留。列表没有像素解码。前端请求有单次分页锁、offset去重和卸载 Abort；首屏不等待后页或缩略图。列表过短无法滚动时，已有按钮样式提供明确的加载操作。

## REQUEST_COUNTS

最终正式 WebView2 首屏完成17次请求：HTML1、JS1、CSS1、品牌资源5、列表1、可见/预取缩略图8；重复URL为0。首12卡静置1700ms仍只有一次列表请求。缩略图峰值4；缩略图异步，不作为卡片/翻页完成条件。

完整测量的列表请求18次，恰好对应首屏1、五次页面暖重开5、两轮各五次后页10、两次刷新2；每轮分页路径offset为0/12/44/76/108/140，157卡完整且ID无重复。批次展开无额外列表读取。

独立只读剖析：Registry 启动读盘105.97ms一次，列表读盘0；每次列表 `current_user_dirs`=1，缓存根校验=1，像素解码=0。当前37个真实浅层文件头每请求各读一次；不递归扫描。下表是操作调用数，`stat`包括`exists/is_file`内部调用，不能相加冒充独立磁盘IO。

| offset | stat | resolve | is_file | exists | header/唯一文件 | 缩略图描述符 | 带探针接口ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 544 | 248 | 74 | 151 | 37/37 | 12 | 57.03 |
| 12 | 689 | 335 | 99 | 175 | 37/37 | 21 | 76.34 |
| 44 | 372 | 160 | 38 | 115 | 37/37 | 0 | 43.00 |
| 76 | 352 | 140 | 38 | 115 | 37/37 | 0 | 35.90 |
| 108 | 352 | 140 | 38 | 115 | 37/37 | 0 | 34.95 |
| 140 | 352 | 140 | 38 | 115 | 37/37 | 0 | 33.76 |

后部页主要是已有显式缺失记录，不执行活文件详情探测。原始逐请求操作和耗时见 `final-profile-requests.jsonl`，汇总见 `acceptance-summary.json`。

## TESTS

- 输出中心/批次/水印/记录清除/品牌 Python **57/57**，进程ExitCode0：`python57-final.log`。
- D61颜色与相邻反馈 Python **70/70**，进程ExitCode0：`d61-70-final.log`。
- 前端全量 **380/380**，fail/cancelled/skipped/todo均0：`frontend380-final.log`。
- **production build通过**：`production-build-final.log`；最终原生桌面使用这一构建再完整复测。

## REAL_RUNTIME / PERFORMANCE

门禁直接在正式 `runtime.packaged_launcher` 的 EdgeChromium WebView2窗口、正式根 `D:\影界文件`、当前production资源测量。未将独立Edge替代为桌面证据。每个冷屏先清除此窗口浏览器缓存；每轮桌面正常关闭，ExitCode0、所属launcher/backend/WebView残留0。

冷屏起点为HTML导航开始；暖重开起点为原生窗口从处理中心返回输出中心；终点均为12张真实卡片数据完整、加载/启动遮罩退出后两帧。翻页测量从请求发起到追加页两帧；没有排除文件探测或等待缩略图。此前后端就绪到HTML之前的整个软件启动时间仍独立，不在本阶段优化范围。

| 门禁 | 最终真实值ms | 结果 |
| --- | --- | --- |
| 连续3次冷首屏≤1000 | 928.7 / 928.6 / 930.5 | PASS |
| 最新production构建额外冷复核≤1000 | 936.6 | PASS |
| 连续5次暖重开≤800 | 362.7 / 371.7 / 373.3 / 348.1 / 374.1 | PASS |
| 连续10次分页 | 90.7 / 72.0 / 60.5 / 62.0 / 60.4 / 98.9 / 61.7 / 62.5 / 60.3 / 61.8 | PASS |
| 分页P95≤150、最大≤200 | nearest-rank P95=98.9；max=98.9 | PASS |
| 批次展开≤100 | 17.5 | PASS |
| 刷新≤1000 | 933.5 | PASS |

最新构建冷屏分段：HTML响应完成4.7ms；JS从7.8ms加载至17.0ms，DOMContentLoaded结束23.2ms；列表57.5ms，API到DOM/两帧37.6ms。Registry启动读盘、每页文件操作与缩略图请求另见上述计数及 `native-final-04-gate.json`。首卡DOM较早已完成，既有启动遮罩使可见冷屏接近900ms；`reactPaintMs`字段包含遮罩等待，不能当作纯React计算耗时。分页各项请求/响应/绘制分段也保留在同一文件。

## LARGE_IMAGE_RESULT

复用已完整校验PNG数据流/CRC的真实100MP、180MP文件，重新比对SHA后实测；JPG、PNG、透明PNG、WebP、4K、24MP同轮通过。正常预览真实解码≤768px，透明PNG alpha80保持。100MP/180MP超过本地预览预算返回422并显示“预览不可用”，卡片、尺寸、路径和可用文件操作保留。

真实缓存PNG损坏后自动重建（MISS）；所属缓存目录故障使正常预览422，但卡片保留，真实打开文件/目录请求200，继续处理指向同一文件。故障解除后原生预览恢复loaded。缺失文件保留原Result身份和MISSING状态，文件操作/继续处理禁用；不制造新Result。

`image-01`与`image-02`之间完整停止并重新创建前后端和原生桌面进程：11卡ID一致，两个超大图、缺失状态、普通单图与批次压缩预览一致，刷新不隐藏。批次水印缩略图与绑定另由七组矩阵/逐项UI复核。见 `runtime-image-*.json`、`native-image-*.json`、`desktop-fault.json`、`cache-fault.json`及实际截图。Pillow `MAX_IMAGE_PIXELS=89,478,485`未变，未放开像素安全门禁或重新运行图片算法。

## REGRESSION

七组、49子项、26个唯一成功Result的九字段与持久数据一致；正式文件真实解码、Result资产预览字节和SHA一致。KEEP_ORIGINAL、失败、取消均无虚假Result/output_path/SHA。实际选择17个成功压缩/水印子项，详情和继续处理准确绑定；清除过的四组记录仍不回流，正式文件和Result保留。见 `bindings-recheck.json`、`selection-recheck.json`。

最后SHA审计：原34输出、当前49正式输出（包含D61真实正链）、隔离42输出、51个原图/真实A-B输入全部不变；59个相关源码中仅本轮允许的4文件变化，其余55不变，包括D61启动器、算法、批次持久合同及缩略图调度模块。settings SHA保持 `7d904536f0c34b9ae8636b378556f733d32c5d23c5e8f1384a5e09f34271f7d5`。原dist29文件备份字节一致；版本、branch、HEAD和空staging不变。见 `integrity-final.json`。

## REMAINING_RISK / FREEZE_STATUS / NEXT

旧失败和探针竞争完整保留，最终门禁对应当前源码/构建与原生窗口。冷屏距离1000ms仍有约63ms余量；大于40MP的预览不可用是受保护安全行为。正式目录浅层清单仍需读取轻量文件头，未引入跨请求TTL隐瞒缺失。整个软件启动、安装包和OC04开发未开展。

FREEZE_STATUS=S61-OC-02已冻结。

已核验OC-00清除记录合同、真实清除/刷新/重启证据与本轮保留文件/Result复核，覆盖OC-03列表清理要求；无需重做。

NEXT=直接进入S61-OC-04（本轮仅完成覆盖核验，未扩展开发）。

Skill迭代判断：暂不需要更新。
