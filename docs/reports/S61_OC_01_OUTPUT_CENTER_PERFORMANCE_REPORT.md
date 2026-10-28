# S61-OC-01｜输出中心性能重测与最小优化

日期：2026-10-02。当前版本：0.6.1-dev / V0.6.1 开发版。

STATUS=PASS_AND_FROZEN（经 S61-OC-01R 合法断言对齐、全量测试和真实运行复核收口）。仅冻结已验证的输出中心源码性能和绑定范围，不涉及提交、发布或整个软件启动性能。

S61-OC-01R 最新复核：前端 377/377、Python 51/51、production build 成功；冷可见首屏 929 ms，暖重开 146–401 ms，翻页到绘制 102 ms，展开 49 ms，刷新 931 ms。七组 49 子项、26 个唯一成功 Result 绑定及 SHA 一致；本轮无生产代码修改。完整结论与新证据见 `S61_OC_01R_ASSERTION_AND_PERFORMANCE_CLOSEOUT_REPORT.md`。下文保留 S61-OC-01 原测量和失败分类，不能将原 376/377 误认为收口后的当前状态。

## 实时基线与保护

| 项目 | 实际值 |
| --- | --- |
| 仓库 | `D:\Codex\04_Visual-Master-Pro` |
| Branch | `codex/image-processing-routing-v1` |
| HEAD | `aa0dd93265d270eb5192ebbd44a1fe14488d454a` |
| Staging | 开始和结束均为空 |
| 受保护 dirty 基线 | 开始 243 个 status 条目；结束无旧条目丢失 |
| settings SHA256 | `7d904536f0c34b9ae8636b378556f733d32c5d23c5e8f1384a5e09f34271f7d5`，未变 |
| 正式输出 | 原有 34 个图片的路径集合及全部 SHA256 未变 |
| 并行写入 | 会话列表中同仓库仅当前任务活跃；识别并只管理本任务的运行实例 |
| Git | 仅只读检查；没有 add/commit/reset/stash/checkout 等写操作 |

`src/OutputCenterPage.jsx`、`engine/storage/batch_results.py`、`backend/image_compression_api.py`、`backend/batch_compression_api.py`、`backend/batch_watermark_api.py`、`engine/storage/result_reuse.py` 与本轮受保护快照逐字节一致。未改变 Batch → Item → Source → Task → Result 合同、输出路径合同、压缩或水印算法。未修改版本、正式 settings、旧 dist 或安装包。

完整哈希和保护证据在仓库内 `output/playwright/s61-oc-01-20261002/preflight.json`、`final-integrity.json`。`stage-only.patch` 相对于本轮开始的真实 dirty 文件生成，而非相对于 HEAD。

## ROOT_CAUSE

1. **Vite 递归监听运行数据和验证资产，使事件循环和模块/API 代理响应阻塞。** 实际模块请求耗时数秒；watcher 探针记录 11,153 个条目，名义 1 秒的后续采样被阻塞至 41.9/96.2 秒。排除这些非前端目录后条目数稳定为 1,079，后续采样间隔约 1001/1012/1001 ms。证据：`watcher-before.json`、`watcher-after.json`、`vite-timing-before.log`。
2. **App 静态导入所有页面，使输出中心等待不属于首屏的模块。** watcher 修复后仍有一次可见冷首屏 1149.7 ms，API 仅 98.7 ms，而 DOMContentLoaded 达 965.4 ms。改为路由按需导入后，冷启动资源记录不再请求这 11 个未使用的重页面模块。
3. **启动遮罩的 900 ms 定时从 React effect 开始，额外覆盖已经渲染的列表。** 截图发现仅测卡片 DOM 会漏掉遮罩。修正计时定义后，旧遮罩真实可见首屏为 1099.6 ms。直接进入 `/outputs` 的遮罩改为按导航时间计算剩余等待；品牌图像和其它路径时序保留。

后端真实只读 profile：512 个 Registry 记录，首批构建 89 ms；`current_user_dirs` 在一次请求中只读一次，约 11.5 ms，返回相同 12 个身份和总计 30 张卡片。现有后端先分页、再构建当前页信息，以及前端首批 12 / 后续页 32 / 缩略图按需机制已存在，没有证据支持修改后端或冻结的批次卡片代码。证据：`snapshot-profile.txt`。

## FILES_MODIFIED / IMPLEMENTATION

| 文件 | 本轮变化 |
| --- | --- |
| `vite.config.js` | server.watch 排除虚拟环境、运行数据、输出、测试及验证资产目录，保留 src/public HMR 和显式 API 目标约束 |
| `src/App.jsx` | 11 个非输出中心页面使用 React.lazy；现有三个页面槽增加 Suspense；保留路由、props、key、隐藏条件和修复工作区持久挂载逻辑 |
| `src/main.jsx` | 仅直接 `/outputs` 的品牌遮罩改为 `max(0, 900 - performance.now())`；其它路由仍为原 900 ms |
| `docs/09_CODEX_CHANGELOG.md` | 追加本阶段记录，保留旧内容 |
| 本报告 | 新增阶段结论、证据边界与剩余问题 |
| `output/playwright/s61-oc-01-20261002/` | 本阶段探针、原始测量、截图、日志、保护快照与独立 build 输出 |

曾试验只延迟 Dashboard，未解决真实阻塞，已恢复当时原字节；最终 App 变化是由剩余首屏模块等待证据支持的按需导入。未重构业务模块或进行 UI 美化。

## PERFORMANCE_BEFORE_AFTER

环境：真实 Windows Edge Chromium，1440×900，独立空缓存浏览器上下文；正式启动器运行当前源码后端 8787 + Vite 5173。无模拟 API、假卡片或预填结果。使用 performance.now、实际网络资源时序和 DOM 身份，并在启动遮罩消失后等待两帧。

**首屏计时从浏览器导航开始，到首批 12 张卡片身份/文本已渲染且启动遮罩不再覆盖。** 缩略图按需加载，不把全部后续页或所有图片解码作为首屏前提。暖重开从真实处理中心切回输出中心，包含点击、原有过渡和请求耗时。

| 测量 | 本轮修复前/中间状态 | 最终代码两次完整重启 |
| --- | --- | --- |
| 冷首屏 | 初始实际样本 13964.5 ms；watcher 修复但遮罩未改时 1099.6 ms；尚未按需导入时有 1149.7 ms 失败 | 938.0 / 926.0 ms，均 ≤1000 |
| 暖重开 | 初始三次 3651.5 / 1908.0 / 957.6 ms | 185.3 / 436.9 / 413.4 / 249.2 / 447.1 / 390.7 ms，均 ≤800 |
| 后续页请求到绘制 | 初始 89.5 ms | 99.6 / 100.1 ms，12 + 18 = 30 张，无重复 |
| 正式单子项批次展开 | 初始 37.8 ms | 43.6 / 46.8 ms，全部 1 项 |
| 刷新可见首屏 | 早期 DOM-only 刷新值不能用于可见门禁 | 921.0 / 929.4 ms，12 张身份一致 |
| 正式启动器至 READY | 单独计时 | 8258.5 / 7941.6 ms |

后续页和展开的少量差异不能解释为加速，本轮修复的是冷首屏与暖重开阻塞。首批、后续页、刷新及跨完整重启的 API/DOM ID 均一致。

**应用从进程退出到 READY 约 8 秒，未达到“整个程序启动 ≤1 秒”。上述 ≤1000 ms 只证明运行时就绪后浏览器导航首屏；两种计时边界不得混用。** 正式 runtime/status 仍引用原有 dist 的历史 build ID，当前实测前端为 5173 源码 Vite。新生产构建仅输出到本阶段证据目录；没有以旧 dist 或安装版冒充最终源码验证。

未沿用旧 3887 ms。所有尝试保留：早期 `watcher-after` 等 DOM-only 快样本被品牌遮罩覆盖，已作废为可见门禁依据；DEBUG 模式超长样本属于诊断环境；中间 1149.7 ms 失败未隐藏。最终有效原始证据：`routes-after.json`、`routes-after-restart.json`、对应 startup JSON 和 first/expanded PNG；汇总：`performance-summary.json`。

## TESTS

| 检查 | 结果及证据 |
| --- | --- |
| Output Center API / batch contract / watermark | 33 项通过，`tests-backend-final.log` |
| 清除记录保持输出 | 14 项通过，`tests-clear-records.log` |
| 品牌资源 | 4 项通过，`tests-brand.log` |
| 直接相关前端 Output Center / 缩略图队列 / 水印 | 35 项通过，`tests-frontend-watcher.log`；全量最终运行覆盖这些测试 |
| 路由静态检查 | 4 项通过，`tests-route.log` |
| 扩展前端测试 | S61-OC-01 原运行 376/377；S61-OC-01R 合法对齐后 377/377，见新收口报告 |
| 生产源码构建 | 成功，`build.log`；输出在证据目录，不覆盖旧 dist |
| 六个主页面真实切换 | 全部显示正确标题，零 pageerror，`route-smoke.json` |

原失败是 `tests/image_compression_ui/test_v1_ui_unification.mjs:97` 期望 `visibleItems.find(...)`；冻结的 S61-OC-00 已使用 `selectableItems` 展开成功子项后选择。受保护原文件和当前 `OutputCenterPage.jsx` SHA 均为 `baeebdc1b06dcdc1f41493c4284cf668e6a313de505e0d000af026c3c3d53657`，同一正则在本轮前文件上也失败，见 `preexisting-test-failure.json`。S61-OC-01R 将其合法归类为旧行为被正式批次合同替代，只更新该断言为成功子项共享选择列表；377/377 通过并有真实 17 子项点击/详情/资格绑定证据。未修改生产合同、删除或跳过测试。

初期沙箱导致 esbuild/临时目录权限错误，已在自动审核允许的正常进程权限下执行正确测试；测试脚本一度错误假设修复独立工作区拥有侧栏，已改用既有返回按钮并通过。失败日志仍在证据目录，不作为产品通过证据。

## REAL_RUNTIME / REGRESSION

真实隔离根目录为 `C:\Users\xyppt\.codex\visualizations\2026\09\21\01a0c410-c6b2-7562-a3e5-2a0588993e30\s61-oc-01-runtime-v2`，后端 8791，前端 5178。创建前已预置并断言所有输出设置位于此根目录。非 Mock、非伪 Result。

| 用例 | 子项结果 |
| --- | --- |
| 压缩 3 张 | 2 成功、1 KEEP_ORIGINAL |
| 压缩 10 张 JPG/PNG/WebP 混合且含损坏输入 | 8 成功、1 KEEP_ORIGINAL、1 失败 |
| 压缩取消 10 张 | 1 KEEP_ORIGINAL、9 取消 |
| 水印 3 张 | 3 成功 |
| 水印 10 张且含损坏输入 | 9 成功、1 失败 |
| 水印取消 10 张 | 1 成功、9 取消 |
| 清除记录 3 张 | 3 成功；清除后卡片消失，文件保留 |

总计 49 子项、26 个真实成功输出。所有成功文件均解码并核对尺寸和完整 SHA；预览响应字节 SHA、缩略图解码、Task/Result/path/SHA、统计和继续处理资格一致。KEEP_ORIGINAL、失败和取消无虚假 Result、路径或 SHA。

最终源码 UI 展开压缩/水印成功及取消四个 10 项批次，分别约 52/36/34/36 ms，全部 10 项数量/状态/Result 一致，共解码 18 张成功缩略图。继续处理请求明确提交唯一 WebP Result ID，intake 返回来源 Result/Task/SHA，与解码后 405×720 预览的 SHA `d29dfc87c9a7e119e9e746127a42a9faff6f62a9b8db25e55bb0778f12d23895` 一致；没有重新提交处理任务来冒充继续输入。

API 清除一个 3 张批次，UI 另清除压缩 3 张、水印 3 张及取消水印批次；刷新和最终隔离后端完整重启后记录均保持清除，26 个原成功输出仍存在且 SHA 一致。其余批次重启后九字段身份、全部子项、统计保持一致。正式 8787/5173 完整退出、重开、独立浏览器关闭/新建上下文后 30 张卡片及首批 12 身份一致。

最后还明确检查所有本任务 8791 Python 引导/子进程已经退出、8791 没有监听，再直接以项目虚拟环境重开。新的 runtime ID 为 `RUN-20261002T214320-A11612E010`、PID 16712，七组核验成功；不以仅停止 Python 父进程冒充完整退出。

证据：`runtime-regression.json`、`runtime-restart.json`、`runtime-restart-final.log`、`runtime-clean-reopen.log`、`isolated-clean-reopen.log`、`ui-regression.json`、`ui-regression-final.log`、`continue-preview.json`、无遮挡 `continue-preview-decoded.png`、`formal-runtime-final.json`、`final-safety-summary.json`。

### 隔离准备失误与恢复

第一版新隔离根的默认压缩设置仍指向正式输出目录，确实创建了两个本任务测试文件。发现后立即停止该实例，逐一核对新增路径、SHA 和唯一测试 batch/Task 归属，将原文件字节移动到本任务 `spillover-preserved` 目录保留，没有删除、覆盖或篡改原有 34 个输出。重新使用预置设置的 v2 隔离根才执行上表矩阵。

路径、所有权、移动前后 SHA 见 `spillover-preservation.json`。原正式文件路径集合、SHA 和 settings 均已复核恢复一致；这次失败不能列作成功隔离验证，也不因此扩大修改正式 settings 默认规则的任务范围。

## REMAINING_RISK / NEXT

- 原旧正则断言已在 S61-OC-01R 合法对齐并完成 377/377 全量复测，不再阻断本阶段。
- 本机两个最终样本有约 62-74 ms 冷首屏余量，不能外推其它机器或负载下的上界。
- 从完整进程启动到 READY 仍约 8 秒；浏览器首屏达标不能代替全应用启动门禁。打包应用没有本轮实测或更新，旧 dist 保持原样。
- 正式历史中已有 330 个不可用文件记录和一个不可用水印子项，明确显示不可用；未按文件名/时间猜测修复或迁移，未删除历史数据。
- 初始测试默认目录失误的两份自有测试文件已核实并保留在隔离证据根；后续测试应继续预置所有输出目录并在提交前断言路径。

FREEZE_STATUS=FROZEN（S61-OC-01 输出中心范围）。NEXT=本阶段关闭；下一阶段仅依据新的明确任务开展。当前不处理全软件启动、不制作安装包、不发布、不写 Git。
