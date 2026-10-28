# S61-OC-00 批量结果合同与输出中心绑定

STATUS=PASS_AND_FROZEN（仅本阶段；无提交、合并、Tag 或发布）

VERSION=V0.6.1 开发版 / 0.6.1-dev  
BRANCH=codex/image-processing-routing-v1  
HEAD=aa0dd93265d270eb5192ebbd44a1fe14488d454a  
STAGING=EMPTY  
DIRTY_BASELINE=初始 106 个 tracked 变更、134 个 untracked 条目，按受保护基线保留。未执行任何 Git 写操作。  
ACTIVE_CODE_WRITERS=预检和收口时，同仓库仅本任务 active；A/C 线 notLoaded。其他 active 任务位于其他仓库。

ROOT_CAUSE=

1. 原输出中心按实际文件建立列表并按文件分页，没有统一批次投影；批次被拆散，KEEP_ORIGINAL、失败、取消因没有输出文件而消失。
2. 压缩批次成员关系与 Task/Result 分开持久化；旧批次快照还可能覆盖已正式登记的成功结果，导致重复卡片或继续处理绑定不可用。
3. 原水印批次把全部结果嵌入同一个父 Task，没有独立子 Task；清除父 Task 只保留顶层 Result，嵌套结果失去可查询身份。修复前真实 3 张水印复现：文件 SHA 不变，Result API 由 200 变成 404。
4. WebP 压缩结果能显示，但公共 Result 资产入口原先拒绝 WebP，使继续处理断链。

FILES_MODIFIED=

| 文件 | 本阶段修改 |
|---|---|
| `engine/storage/batch_results.py`（新增） | 统一批次投影、显式成员关系、状态和体积统计 |
| `backend/batch_compression_api.py` | 子项身份和终态持久化、与真实 Task/Result 绑定 |
| `backend/batch_watermark_api.py` | 独立子 Task、源图快照、批次保留引用、可响应取消 |
| `engine/storage/shared_task_registry.py` | 清除 Task 时保留水印批次和真实嵌套 Result |
| `engine/storage/result_reuse.py` | 子 Task 优先，批次引用不冒充 Result 权威事实 |
| `backend/image_compression_api.py` | 批次分页与子项 hydration、路径/SHA 门禁、清除显示记录、继续处理 |
| `main.py` | 公共 Result 元数据和文件接口支持 WebP；处理器原格式门禁保持 |
| `src/OutputCenterPage.jsx` | 批次展开、逐项操作、压缩统计和清除记录 |
| `src/BatchWatermarkPage.jsx` | 取消未开始项并显示真实取消状态 |
| `src/index.css` | 批次/子项所需的局部布局 |
| `tests/image_compression_ui/test_batch_output_contract.py`（新增） | 真实 API 合同与文件绑定回归 |
| `tests/image_compression_ui/test_a06_batch_stability.py` | 将旧平铺列表断言调整为批次及全部子项断言 |
| `docs/09_CODEX_CHANGELOG.md`、本报告 | 变更与证据记录 |

另更新生成目录 `dist`，原构建已备份在本轮 evidence/baseline/dist；运行证据位于 `output/playwright/s61-oc-00-20260921` 和对应 `.reprosight/runs`，不作为正式输出交付文件。

IMPLEMENTATION=

- 统一合同 `HDDE_BATCH_RESULTS_V1`：Batch → Batch Item → Source → Task → Result。每项含 `batch_id / batch_item_id / feature_type / source_id / task_id / result_id / status / output_path / output_sha256`。
- 成功子项必须匹配真实 Task/Result、正式路径及文件 SHA 才启用预览与操作；缺失或不匹配时保留子项并明确不可用。
- KEEP_ORIGINAL、失败和取消不创建虚假 Result，结果 ID、输出路径和输出 SHA 均为空。压缩汇总中失败/取消按原图体积计入，界面明确说明。
- 新水印任务逐项保留源图快照并分配独立 Task/Result；清除 Task 不丢失真实 Result。输出中心清除使用显示隐藏记录，不删除正式文件。
- 仅使用已有 `batch.items`、稳定子项 ID 和明确 Task/Result 引用读取历史批次；没有可靠关系的旧文件保持单图卡片，不按时间或名称猜测。
- 未改变压缩引擎、水印绘制算法、智能交付算法、正式根目录设置、单图操作流程或其他冻结模块。

TESTS=

| 验证 | 结果 | 证据 |
|---|---:|---|
| 修复前真实 3+3 批次复现 | 6 张平铺卡；水印 Task 清除丢失 Result 查询 | `reproduction.json`、`reproduction-clear.json`、`before.png` |
| 修复前回归测试 | 如预期失败：3 个文件卡片 != 1 个批次卡片 | `test-before.log` |
| 批次合同、输出中心、水印与记录清除 | 47/47 | `tests-contract-final-clean.log` |
| 原批量压缩稳定性 | 24/24（与新增 6 项共同运行，日志总计 30） | `tests-batch-binding-final.log` |
| 单图 KEEP_ORIGINAL 与 Smart Delivery | 16/16 | `tests-single-delivery-final.log` |
| 前端输出中心、水印、继续处理和批量交付 | 53/53 | `tests-frontend-final.log` |
| Python 编译、限定文件 diff 检查、生产构建 | 通过；构建保留原有大 chunk 提示 | `build-final.log`、最终完整性记录 |
| 扩展 Source 生命周期测试 | 8/10；另 2 项属于既有 reference-color 失败 | `tests-source-lifecycle.log` 与 `tests-source-lifecycle-baseline.log` |

扩展测试的两项失败在本轮修改前备份模块上同样复现：`test_original_result_and_reference_previews_survive_expiry_and_reload` 得到空 Result；`test_deleted_task_retains_result_source_but_releases_unused_reference` 因同一空 Result 未保留引用。未修改该功能，也未把全仓测试称为通过。

REAL_RUNTIME=

以下均调用实际生产接口、编码器和持久化 Registry，无 Mock。输入含从既有图片只读派生的 JPG/PNG/WebP、确定性 KEEP_ORIGINAL 样本及故意损坏的失败样本；输入来源和 SHA 见 `runtime-matrix.json`。

| 独立前后端实例 | 总项 | 成功 | KEEP_ORIGINAL | 失败 | 取消 |
|---|---:|---:|---:|---:|---:|
| 压缩 3 张，JPG/PNG/WebP | 3 | 2 | 1 | 0 | 0 |
| 压缩 10 张，JPG/PNG/WebP | 10 | 8 | 1 | 1 | 0 |
| 压缩取消 | 10 | 0 | 1 | 0 | 9 |
| 水印 3 张 | 3 | 3 | 0 | 0 | 0 |
| 水印 10 张 | 10 | 9 | 0 | 1 | 0 |
| 水印取消 | 10 | 1 | 0 | 0 | 9 |
| 水印清除记录验证 | 3 | 3 | 0 | 0 | 0 |

- 压缩 3 张汇总 1,142,010 → 560,297 bytes；压缩 10 张 3,602,487 → 1,736,330 bytes，与逐项真实文件一致。
- 成功项逐一校验路径边界、图片解码、尺寸、SHA、原图预览响应 SHA、缩略图解码、Result 资产查询和继续处理资格。非成功项逐一确认没有结果身份/路径/SHA。
- 浏览器实际展开压缩 10 项和水印 10 项，分别核对 8/9 张成功缩略图全部解码；WebP 继续处理进入精确 Result 并显示真实成品文件名。清除 3 张水印批次后刷新不回流，3 个文件及 Result 查询保持正常。
- 前端 5176 与后端 8791 停止并重新启动；7 组批次身份、状态、汇总和 26 个成功文件 SHA 均一致，见 `restart-verification.json`。
- 当前源码真实桌面入口 `runtime.packaged_launcher`、生产构建、EdgeChromium 8792 再运行 6 组矩阵。水印取消时已有 2 项完成、8 项取消；其余统计同上。24 个成功文件逐项通过。
- 桌面完整退出证据含 `window_closed/backend_stopped/shutdown_complete`，端口和生命周期事件均消失；重开后 `window_loaded=true`、`document_ready_state=complete`，新 runtime_id 下 6 组身份与 24 个 SHA 不变。见 `desktop-stopped-2.json`、`desktop-reopen2-verification.json`。
- 沙盒内的 WebView2/Windows Shell 打开受限；按授权在正常权限下重开同一隔离目录后，页面加载、WebP 打开、目录打开均成功。这是运行环境差异，未修改产品作为绕过。见 `browser-desktop-open.txt`。
- 主实例 8787/5173 已按正式 launcher 正常退出并重启。`/api/health` 与 `/api/runtime/status` ready，版本仍为 V0.6.1 开发版，正式根目录仍为 `D:\影界文件`；主实例显示 29 条记录，其中 9 个显式历史批次。

REGRESSION=

- 原有单图卡片和现有交付/源资产引用路径保留。
- 清除批次 Task、重载 Registry、输出中心清除/刷新/重启均不删除文件；真实文件和源图 SHA 逐项验证。
- 初始 `D:\影界文件\输出` 下全部 30 个正式输出文件及 settings SHA 未变化；主实例无验证样本写入。所有测试 Registry、输出和缓存均在独立验证根目录。
- 分支、HEAD、staging 保持原状；本阶段差异按修改前文件备份审阅，未执行 Git 写操作。

REMAINING_RISK=

- 正式目录仍有 330 条原先就不存在或无法读取的文件记录；未伪造、重建或按名称补绑。明确历史批次中的缺失文件显示不可用。
- 上述两项 reference-color 既有测试失败仍在。本阶段结论仅覆盖批量结果与输出中心绑定。
- 验证对象为当前源码和真实桌面入口，未重新制作或验证安装包；不构成安装包发布结论。

NEXT=本阶段收口；保留正式主实例供使用，不自动进入下一阶段。Skill 迭代判断：暂不需要更新。

证据目录：`D:\Codex\04_Visual-Master-Pro\output\playwright\s61-oc-00-20260921`。本报告统计不合并重复运行次数。
