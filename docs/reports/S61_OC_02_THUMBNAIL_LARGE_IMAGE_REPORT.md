# S61-OC-02｜缩略图与超大图片兼容

日期：2026-10-02。证据目录：`output/playwright/s61-oc-02-20261002/`。

STATUS=BLOCKED，FREEZE_STATUS=NOT_FROZEN。输出中心修复及以下范围内验证已完成，但末次受保护基线检查发现并行 D 线改动，当前共享前端不是全绿。先前通过快照不能覆盖最终当前状态。

## 最终共享状态阻塞

- 本轮验证快照的前端为 377/377、Python 57/57、构建及实际大图/原生桌面重启均通过。
- 收口时 `src/App.jsx` 于 23:14:13 被同仓库活动任务 **V0.6.1｜D线｜颜色校正** 修改：反馈路由集合增加 color-correction、过滤错误 feature_key、为颜色页传入 onTaskContextChange。这是外部写入，不列为本轮 FILES_MODIFIED；没有覆盖或回滚。
- 它未改懒加载、Suspense 等 S61-OC-01 性能逻辑，但整份 App.jsx 的受保护 SHA 已不同；`final-integrity.json` 的 frozen_contract_and_performance_unchanged 仍为 false。没有刷新或放宽基线来伪造通过。
- 当前共享前端重新执行后为 **379/380，1 失败**。唯一失败：`tests/image_compression_ui/test_a61_05_compression_advice.mjs:71` 中要求 FEEDBACK_TASK_ROUTES 精确仅为 TASK_ROUTES + compression 的旧源码断言，与 D 线新增颜色反馈路由冲突。它不是缩略图修复失败，但当前全量门禁确实未通过。本轮不改它来清零，也不把旧 377/377 当成最终当前结果。
- 当前共享 production build 成功。重新测量冷首屏 928.3ms、暖重开 372.4/557.6/608.9ms、刷新 935.7ms；身份与分页数量一致。并行期间翻页 API 达 648–785ms、展开 99.3ms，相比前一稳定快照明显变慢，尚未在并行任务结束后的稳定状态排除竞争或确认回归，禁止继续优化来掩盖这一不确定性。
- 当前证据：`frontend-current-shared.log`、`build-current-shared.log`、`current-shared.json`、`external-app.patch`、`final-integrity.json`。本轮只更新自己的阶段结论；未向另一任务发送消息、修改其测试或停止其服务。

## ROOT_CAUSE

1. 列表的 `Image.open()` 尚未解码像素就执行 Pillow 像素警戒；有效 18000×10000 PNG 触发 DecompressionBombError，被候选筛选的异常分支略过。10000×10000 PNG 则触发 Warning。两文件均验证全部 PNG CRC、zlib 终止和完整解码字节数，未用虚假图头冒充大图。
2. 缓存只检查“存在且非空”，损坏文件仍返回 HTTP 200、HIT，并附 immutable 长缓存头。真实浏览器因此持续显示失败预览。修改前截图 `before.png`；HTTP 事实 `reproduction.json`。
3. 缩略图缓存描述符与结果信息放在同一个异常分支，缓存异常会移除真实卡片。修改前回归返回 count=5、实际 items=[]。源文件状态与预览缓存状态必须分开。
4. 单图候选只来自仍存在的目录文件，明确登记的 Result 文件缺失后卡片消失；批次已有缺失子项保留机制。新增测试在修改前独立失败，未修改旧的无登记文件移除断言。

修改前测试证据：`test-before.log`、`test-descriptor-before.log`、`test-missing-before.log`。这些是测试证明，真实超大图/缓存/桌面证据另列，不用 Mock 代替真实运行。

## FILES_MODIFIED

| 文件 | 本轮变化 |
| --- | --- |
| `backend/output_center_preview.py` | 新增限量图头读取：PNG/WebP 固定小段，JPEG 跳过元数据段且限制图头预算；不解码原图像素 |
| `backend/image_compression_api.py` | 仅输出中心列表、缩略图缓存、缺失记录投影及缩略图异常处理 |
| `src/OutputCenterPage.jsx` | 无缩略图 URL/失败时显示“预览不可用”；缺失文件保留卡片、明确提示及禁用文件操作 |
| `tests/image_compression_ui/test_output_center_api.py` | 六个回归：像素警戒、损坏缓存重建、描述符失败保卡片、明确缺失 Result、缓存路径逃逸、缓存探测权限失败 |
| `docs/09_CODEX_CHANGELOG.md` | 追加本阶段结果 |
| 本报告 | 阶段结论及证据边界 |

另有本阶段运行脚本、原始 JSON/日志、截图、构建及 ReproSight 报告；未改旧阶段证据。

## IMPLEMENTATION

- 列表只读取格式/尺寸图头，仍按现有分页和当前页详情链路处理。没有生成缩略图、完整解码原图或递归扫描全部文件；目录状态提供器单次请求只读一次。
- 缩略图仍按可视区域/预取队列请求，最大边 768、并发 4。已有缓存仅在缩略图 GET 时校验，最大缓存字节 8MiB、尺寸不超过 768、格式匹配且能解码；无效缓存在单键锁下原子替换。源图与正式输出从不被替换。
- 缓存目录和缓存文件解析后的真实路径必须留在批准根目录内。v2 键使旧坏响应失效；签名仍来自实际路径、文件大小、mtime 和预览版本。
- 40MP 是本地缩略图预算，还服从当前 Pillow 安全上限；未赋值或全局关闭 `Image.MAX_IMAGE_PIXELS`。超出预算只返回 OUTPUT_THUMBNAIL_UNAVAILABLE/422，保留图头尺寸、真实卡片和文件操作。处理算法及继续处理自身的限制没有放宽。
- 缓存描述符失败只令 preview unavailable，不改变 Result 的文件 availability。前端显示精确文字“预览不可用”；实际文件缺失时显示“正式文件缺失”，接口文件操作返回缺失错误。
- 只有明确持久 Task/Result/路径/SHA 的完成记录才能保留单图缺失卡片。路径只匹配正式合同目录；不按文件名或时间归组，不给 KEEP_ORIGINAL/失败/取消补造 Result。原批次九字段、来源与绑定验证未变。

## TESTS

| 验证 | 结果 | 当前证据 |
| --- | --- | --- |
| 本轮验证快照前端全量 | 377/377，无跳过/失败 | `frontend-tests.log` |
| 并行改动后的当前共享前端 | 379/380，1 个反馈路由断言失败；未冻结 | `frontend-current-shared.log` |
| Python 输出中心/批次合同/水印/记录删除/品牌 | 57/57 | `python-final-57.log` |
| production build | 原快照与当前共享状态均成功，未覆盖旧 dist | `build.log`、`build-current-shared.log` |
| 列表不解码像素、目录状态单次读取 | 通过实际测试与只读 profile | `api-after.log`、最终 Python 日志、`snapshot-profile.txt` |
| 修改前失败至修改后通过 | 三类根因及缺失记录的失败均保留 | `test-*-before.log`、最终 Python 日志 |

## REAL_RUNTIME

隔离根目录 `C:\Users\xyppt\.codex\visualizations\2026\09\21\01a0c410-c6b2-7562-a3e5-2a0588993e30\s61-oc-02-runtime`。启动前预置并断言输出设置全部位于该根目录；正式根目录仍为 `D:\影界文件`。

| 真实文件 | 尺寸 | 重启后预览 |
| --- | --- | --- |
| JPG | 1600×900 | 缩略图可完整解码、HIT |
| PNG | 1600×900 | 缩略图可完整解码、HIT |
| 透明 PNG | 1200×800 | RGBA，Alpha=80，HIT |
| WebP | 1600×900 | 缩略图可完整解码、HIT |
| 4K PNG | 3840×2160 | 缩略图可完整解码、HIT |
| 24MP JPG | 6000×4000 | 缩略图可完整解码、HIT |
| Warning 大图 PNG | 10000×10000，100MP | 真实卡片/尺寸保留，预览不可用 |
| Error 大图 PNG | 18000×10000，180MP | 真实卡片/尺寸保留，预览不可用 |

`fixtures.json` 记录源字节 SHA、Pillow 默认 89,478,485 像素门槛，以及 100,010,000 / 180,010,000 个完整解码流字节。大图用流式合法 PNG 生成并验证，未修改正式图像，也没有给文件凭空创建 Task 或 Result。

真实接口另生成三张单图 Result、一个 3 项压缩批次（2 成功、1 KEEP_ORIGINAL）和一个 3 项水印批次（全部成功）。缺失案例把本轮拥有的一个 Result 移到隔离保留目录，原 SHA 不变；原路径缺失且原 Result 身份持续存在，没有删文件或伪造成功。

故障注入只改变本轮缓存：损坏 v2 缓存重新生成 MISS；缓存目录暂时被本轮故障文件占用时，HTTP 422 且 13 张卡片都保留。真实可见 Edge 窗口确认正常 Result 的打开文件/目录接口均成功，继续处理对话框仍绑定同一文件与 Result；无 pageerror。随后恢复原缓存。证据 `cache-fault.json`、`desktop-fault.json`。

先关闭独立浏览器窗口，再停止隔离前后端、重开新进程；HTTP 八个格式案例与批次九字段一致。进一步使用项目真实 `runtime.packaged_launcher.run_desktop_window`、EdgeChromium renderer 创建原生桌面窗口，退出整个窗口进程，再停止并重启前后端，重新启动桌面进程。重开后单图缩略图 loaded、两个批次的五个成功子项缩略图 loaded、两张大图失败占位保留、缺失文件与禁用动作一致。证据 `native-first.json`、`native-reopened.json`、两个 `native-shell-*.json` 均确认 shown/loaded/closed；不是假的 webview 模块。

刷新、不同后端/前端 PID 和独立桌面进程的证据分别在 `runtime-*.json`、服务日志、`desktop-*.json`。最终界面截图 `after-huge.png`、`after-missing.png`。

最终代码补全缓存存在性探测的权限异常边界（修改前真实测试为 PermissionError，`test-cache-permission-before.log`）。再次完整重启正式及隔离服务，并用原生桌面壳复核；清除后的 11 张卡片、正常成功缩略图、超大图及缺失 Result 都一致。证据 `runtime-final-closure.json`、`native-final-closure.json`、`native-shell-final-closure.json`，桌面窗口同样 shown/loaded/closed。

## PERFORMANCE

全部为本轮新测量，没有沿用 3887ms 或旧阶段通过值。正式启动器完整重启 8787/5173，独立空缓存 Edge、1440×900，以首批 12 张卡片身份/文本完整、遮罩消失再等待两帧为首屏终点。

本轮初版缺失投影让暖重开达到 919–931ms；这些未达标结果保留在 `formal-recheck.json`。只修正本轮新增投影中的重复路径解析：先用正式目录键、明确已见路径做廉价过滤。没有回开 `src/App.jsx`、`src/main.jsx`、`vite.config.js`。最终只读 profile 一次请求 92ms、目录状态一次约 10.5ms。

| 项目 | 最终实测 |
| --- | --- |
| 冷首屏 | **930.6ms ≤1000ms** |
| 暖重开（三次） | **157.4 / 377.3 / 375.5ms ≤800ms** |
| 首批 | **12 张，API/DOM ID 完整、无重复** |
| 后续翻页请求至绘制 | **166.6 / 169.7 / 184.5 / 188.6ms**，每页 32 张 |
| 正式批次展开 | **48.3ms**，一个真实子项 |
| 10 项压缩/水印/取消批次展开 | **33.4 / 33.9 / 31.6ms** |
| 刷新 | **930.5ms**，首批身份一致 |

当前正式列表有 144 张卡片（原正常单图/批次加上明确登记的缺失历史），分页完成，ID 一致且唯一。缺失历史没有按文件名/时间迁移归组。最终性能证据 `final-closure.json`；补全权限保护前一轮也达标（冷 933ms、暖 200/370/373ms、展开 41ms、翻页 149–220ms），保留于 `final-performance.json`。另见 `selection-recheck.json`、`snapshot-profile-facts.json`。

最终正式启动到 READY 约 7.87 秒，前一轮约 7.27 秒，另一次负载下约 11.06 秒；这是整个进程启动时段，不属于上述导航至首屏门禁，本轮没有优化或把它写成一秒启动。

## REGRESSION

- 七组原批次：49 子项、26 唯一成功 Result；每项九字段/终态一致，成功文件 SHA、解码尺寸、原图预览字节与 result-assets 绑定一致。KEEP_ORIGINAL、失败、取消都没有 Result/输出路径/SHA。
- 为保护原冻结证据，复制 133 个文件到新的 `s61-oc-02-regression-copy`。只在副本 JSON 中机械替换确切根路径前缀，身份和图像字节不变；原目录前后 133 文件全部 SHA 相同。原始期望仍按明确 Batch Item/Task/Result 对应，比对时对根路径作相同替换。API 复核只有 GET。
- 真实浏览器分别选择 8 个压缩成功子项、9 个水印成功子项，核对详情文件名和继续处理请求；取消批次无成功项可操作，零 pageerror、零非 GET 请求。路径派生 UI ID 使用副本的明确子项身份重新绑定，没有猜测。
- 本轮清除一个真实单图记录及一个 3 项水印批次记录，刷新并完整重启后仍清除，15 个隔离正式输出全部保留且 SHA 不变；缺失案例的保留文件也未变。证据 `clear-records.json`。
- 正式 34 个输出路径与 SHA 集合不变；settings SHA 仍为 `7d904536f0c34b9ae8636b378556f733d32c5d23c5e8f1384a5e09f34271f7d5`。
- V0.6.1-dev、分支 `codex/image-processing-routing-v1`、HEAD `aa0dd93265d270eb5192ebbd44a1fe14488d454a` 不变，staging 为空，245 个原 dirty 条目均保留。冻结批次存储/水印/压缩批次/Result 复用模块，以及 main.jsx/vite.config.js 字节不变；本轮没有修改 App.jsx，但最终外部 D 线写入导致其全文件 SHA 改变，不能宣称三份性能源文件均字节不变。自身 patch 与外部 App 差异分别记录。见 `preflight.json`、`final-integrity.json`、`stage-only.patch`、`external-app.patch`。

## REMAINING_RISK

- 并行写入造成最终工作区不同于本轮通过快照；当前共享前端 1 项失败、App.jsx 基线不一致及并行期间分页变慢均未关闭，是本阶段不能冻结的实际阻塞。
- 大于 40MP 的图片默认不解码生成缩略图，只显示真实卡片与“预览不可用”；现有处理器各自的格式/像素/文件大小/SHA 资格限制继续生效。本阶段不承诺这些处理算法能处理任意超大图片。
- JPEG 图头扫描有 1MiB 元数据预算；不支持的/无效图头不会被伪造成正常图片。未登记的已丢失文件无法凭空恢复为 Result 卡片。
- 缓存损坏、目录不可用、两类 Pillow 门槛及缺失场景已验证；未穷举所有系统权限、所有编码器异常或磁盘损坏方式。
- 已验证 production build 和真实桌面壳，未运行新的安装包或打包 EXE；没有把源码/Vite 的结果冒充已安装版本验收。

自动审核曾拒绝直接启动原冻结 runtime-v2 目录的服务，因为启动可能写日志或缓存，与只读复核不符。未绕过；改用审核建议的新副本完成验证，原证据最终全部 SHA 一致。

## FREEZE_STATUS

S61-OC-02=NOT_FROZEN。已有真实超大图、前后端重启和桌面窗口完整退出重开证据，但最终共享前端与受保护基线门禁未满足。S61-OC-00 批次合同及本轮未触碰的性能逻辑继续受保护；不将外部 App 改动偷偷归为本轮修改或已审核新基线。

## NEXT

停止本阶段产品代码修改；保留正式 8787/5173 服务，关闭本轮 8791/5178 服务及验证窗口。待 D 线写入稳定并完成其相关断言/集成处理，再复核当前共享前端、生产构建、性能与基线，满足门禁后才冻结 S61-OC-02。不得回滚 D 线或为清零测试改动无关代码。本阶段没有 Git 写操作、提交、安装包或无关重构。
