# S61-OC-01R｜旧断言对齐与性能收口

日期：2026-10-02。

STATUS=PASS_AND_FROZEN。

## ASSERTION_ROOT_CAUSE

归类为用户要求的 **第 1 类：旧断言针对已被正式新实现合法替代的行为**，不是生产代码违约，也不是无关测试排除。

原断言要求 `visibleItems.find((item) => item.id === selectedId)`。S61-OC-00 正式合同规定顶层是一张批次卡片，成功子项可以独立选择、查看详情和继续处理。因此生产代码先把单图与批次中 `available` 的子项形成 `selectableItems`，再按选中身份查找；KEEP_ORIGINAL、失败、取消和不可用成功项不能冒充可操作 Result。直接退回顶层查找会破坏子项绑定。

本轮修改前再次运行原断言并真实失败，记录为 `assertion-before.log`；相关生产代码和 S61-OC-00 报告同时核对。只将旧断言中的选择列表名称对齐为 `selectableItems`，加一条解释注释；保留相等身份匹配、搜索、排序、响应式详情等全部原检查，不放宽为任选旧/新路径，不删除或跳过测试。原文件已保存在本轮 baseline。

## FILES_MODIFIED

| 文件 | 本轮变化 |
| --- | --- |
| `tests/image_compression_ui/test_v1_ui_unification.mjs` | 一条旧选择列表断言及对应说明注释 |
| `docs/09_CODEX_CHANGELOG.md` | 追加本轮收口记录 |
| `docs/reports/S61_OC_01_OUTPUT_CENTER_PERFORMANCE_REPORT.md` | 更新当前收口状态，保留原测量和历史失败事实 |
| 本报告 | 新增归类、验证和冻结结论 |
| `output/playwright/s61-oc-01r-20261002/` | 本轮真实日志、截图、构建输出与保护快照 |

**没有修改生产代码。** `src/App.jsx`、`src/main.jsx`、`vite.config.js` 的 S61-OC-01 成果保持原字节；Output Center、批次投影、Result 重用、压缩和水印 API 同样保持原字节。没有继续优化、算法变更、UI 改动、安装包或 Git 写操作。

## TESTS

| 必要验证 | 实际结果 | 新证据 |
| --- | --- | --- |
| 前端全量 `node --test tests/image_compression_ui/*.mjs` | **377/377**；0 fail / skipped / cancelled | `tests-frontend.log` |
| Python Output Center / batch contract / watermark / record deletion / brand | **51/51** | `tests-python.log` |
| `vite build` | 成功 | `build.log` |

Python 命令为 `python -m unittest tests.image_compression_ui.test_output_center_api tests.image_compression_ui.test_batch_output_contract tests.batch_watermark.test_batch_watermark_api tests.test_task_record_deletion tests.test_brand_assets`。生产构建仅输出本轮 `production-build` 目录，没有覆盖旧 dist。执行时显式设置 `GIT_OPTIONAL_LOCKS=0`。

绑定探针初次复用旧助手时，其期望根仍为更早隔离目录，路径断言因此失败；显式设为已核实的原 v2 根后完成核验。原错误保留为 `bindings-helper-root-failure.log`，没有改产品路径或写入设置来绕过检查。

## PERFORMANCE_RECHECK

正式启动器完全关闭、重开当前源码 8787 后端 + 5173 前端；用独立空缓存 Edge Chromium、1440×900 复核。计时探针复用 S61-OC-01 已校正的版本，结束条件是首批 12 张卡片身份/文本已渲染、品牌遮罩消失，再等待两帧；不把后续页或所有缩略图作为首屏前提。

| 操作 | 实测 |
| --- | --- |
| 冷可见首屏 | **929 ms ≤1000** |
| 三次暖重开 | **145.8 / 401.4 / 385.2 ms，均 ≤800** |
| 翻页请求到绘制 | **102.2 ms**；API 70 ms |
| 正式批次展开 | **48.8 ms**，1 项完整 |
| 刷新可见首屏 | **931 ms** |
| 首批及总数量 | **12 + 18 = 30**；首批无重复，API 与 DOM ID 一致 |
| 跨重开、暖切换、翻页、刷新 | 身份一致 |

另在隔离真实 10 项批次验证展开：压缩约 59.6 ms、水印 34.8 ms、压缩取消 33.1 ms，均显示全部 10 项。本轮没有调整任何性能实现。

这是**运行时就绪后浏览器导航的首屏性能**。整个软件启动约 8 秒的旧问题不属于本轮门禁，没有处理；安装版也没有本轮实测或制作。不能把上述 929 ms 当作整机应用启动时间。

证据：`recheck.json`、`recheck-first.png`、`recheck-expanded.png`、`startup-recheck.json`；截图已检查，没有以遮罩后的 DOM 计时冒充可见首屏。

## REGRESSION

复用上一阶段真实隔离根 `s61-oc-01-runtime-v2` 的原七组批次。本轮绑定检查和 UI 检查只有 GET 请求，不创建新批次、提交处理、清除记录或保存设置。

| 用例 | 子项持久化状态 |
| --- | --- |
| 压缩 3 张 | 2 成功、1 KEEP_ORIGINAL；记录已清除 |
| JPG/PNG/WebP 混合压缩 10 张 | 8 成功、1 KEEP_ORIGINAL、1 失败 |
| 压缩取消 10 张 | 1 KEEP_ORIGINAL、9 取消 |
| 水印 3 张 | 3 成功；记录已清除 |
| 水印 10 张 | 9 成功、1 失败 |
| 水印取消 10 张 | 1 成功、9 取消；记录已清除 |
| 清除记录 3 张 | 3 成功；记录已清除 |

**7 组 / 49 子项 / 26 个成功输出 / 26 个唯一 Result 全部复核一致。** 包括已清除批次的持久化九字段 `batch_id / batch_item_id / feature_type / source_id / task_id / result_id / status / output_path / output_sha256`，不是仅复用旧报告中的静态绑定。成功项的实际路径位于原隔离根，文件可完整解码，尺寸正确；Result-assets 返回的 Result、Task、处理类型、SHA 及预览响应字节与原文件一致。非成功项的 Result、路径、SHA 仍为空。

当前可见批次统计和全部子项与原矩阵一致；原清除记录保持隐藏，输出仍可读取。真实浏览器逐一点击压缩 8 个、水印 9 个成功子项，核对选中状态、详情文件名及唯一子项的继续处理资格请求，17 项全部一致；KEEP_ORIGINAL、失败和取消没有可选 Result 卡片。零 pageerror、零 API 写请求。该运行证据证明新断言对应现行正式用户行为，而非只改文字让测试变绿。

证据：`bindings-recheck.json`、`bindings-recheck.log`、`binding-probe.json`、`selection-recheck.json`、`selection-recheck.log`、`selection-recheck.png`。

## 保护与 FREEZE_STATUS

| 项目 | 最终结果 |
| --- | --- |
| Version | `0.6.1-dev / V0.6.1 开发版`，未改 |
| Branch | `codex/image-processing-routing-v1`，未改 |
| HEAD | `aa0dd93265d270eb5192ebbd44a1fe14488d454a`，未改 |
| Staging | EMPTY |
| Dirty 基线 | 本轮开始 244 个 status 条目，结束没有旧条目丢失 |
| 正式输出 | **原有 34 个文件的路径集合与全部 SHA256 不变** |
| settings SHA256 | `7d904536f0c34b9ae8636b378556f733d32c5d23c5e8f1384a5e09f34271f7d5`，不变 |
| 生产/性能源文件 | 本轮逐字节不变 |
| 并行写入 | 同仓库仅当前任务活跃；运行实例归属已核对 |

证据：`preflight.json`、`final-integrity.json`、相对于本轮 dirty 快照的 `stage-only.patch`。本轮结束只关闭自己启动的隔离 8791/5178 服务，保留复核后的正式 8787/5173 实例。

FREEZE_STATUS=FROZEN：S61-OC-01 的输出中心性能及相应断言/绑定验证正式收口，S61-OC-00 批次合同保持冻结。冻结不代表 Git 提交、打包、安装或发布，不外推其它机器/负载下的性能上界。

NEXT=本阶段关闭；后续工作只依据新的明确任务，不继续优化或处理整个软件启动问题。
