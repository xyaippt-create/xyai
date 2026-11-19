# V0.6.2｜瑕疵修复：同位置批量

## STATUS

STAGE_RESULT: BLOCKED  
FINAL_STATUS: BLOCKED  
FREEZE_STATUS: NOT_READY  
SELF_AUDIT: FAIL

本阶段实现、技术验证及真实界面完整链路已完成，负责人最终画质签收尚未完成；当前唯一剩余项为人工签收。按本轮任务合同继续保持 BLOCKED / NOT_READY，不宣称冻结。

版本 `0.6.2-dev`；分支 `codex/image-processing-routing-v1`；HEAD `b4fdde85dc036537382fb16252e1f1473c215e61`，开工匹配，最终复核见 `output/retouch_batch_20261104/protection-final.json`。开工32个 tracked 修改及原有 untracked 全部保护，staging为空。

## FILES_MODIFIED

本轮界面验收及追加需求实际修改：`backend/local_retouch_api.py`、`backend/batch_local_retouch_api.py`、`src/LocalRetouchPage.jsx`、`main.py`、`tests/local_retouch/test_batch_local_retouch.py` 与三份现有阶段文档（本报告、当前状态、变更日志）。下方原开发阶段文件清单保留。新证据位于 `output/retouch_batch_20261104/ui/`。

- `backend/local_retouch_api.py`
- `backend/batch_local_retouch_api.py`（新增）
- `src/LocalRetouchPage.jsx`
- `src/RetouchBatchPanel.jsx`（新增）
- `src/localRetouchBatch.js`（新增）
- `src/localRetouchBatch.css`（新增）
- `tests/local_retouch/test_batch_local_retouch.py`（新增）
- `tests/image_compression_ui/test_batch_local_retouch.mjs`（新增）
- `scripts/validate_batch_local_retouch.py`（新增）
- `docs/03_CURRENT_STATUS_V0.4.5.1.md`（仅追加本阶段状态）
- `docs/09_CODEX_CHANGELOG.md`（仅追加本阶段记录）
- 本报告（新增）

本地验证证据位于 `output/retouch_batch_20261104/`；正式验收输出位于设置指定的 `D:\影界文件\输出\瑕疵修复`。均非模型、依赖或版本变更。

## IMPLEMENTED

单图现有处理会推进稳定工作图，不能直接在多图试修中反复使用该工作状态。批量对每张导入原图创建独立候选会话，复用实际修复引擎及原确认/正式保存函数；试修不叠加到上一试修。正式批量固定蒙版快照，仅批量推理离开事件循环等待，确保取消请求可以被接收。

页面保留现有单图和画布工具，新增多图导入、原像素位置覆盖核对、逐图试修与前后对比、顺序执行/逐项状态和总进度。尺寸不符与损坏输入有排除原因；失败隔离，取消后当前图可完成，其余不启动。候选按当前蒙版版本显示与选择；编辑选区后旧候选不可冒充新结果。确认另存同时绑定item、候选session、蒙版版本及像素哈希；试修、失败和取消项不能制造正式Result。每图的Source/Task/Result独立，批次与蒙版身份进入现有登记，输出中心沿用既有正式卡片，不重构批量基础设施。

待界面与人工验收后发布的用户更新说明：

> 瑕疵修复新增“同位置批量”：导入多张同尺寸图片，标记一次选区即可逐张独立修补。执行前可切图检查位置并试修；尺寸不同或损坏的图片会明确排除。处理中可取消后续图片，已完成候选保留。查看结果后可逐张或勾选确认另存，原图始终保留。

该文案暂存本报告，未把尚未完成界面验收的阶段写成软件发布完成记录。

## VALIDATION

- Python：`unittest discover -s tests/local_retouch -p test*retouch.py`，最终32/32，通过；记录 `python-tests-final.log`。含批量负路径、取消、错图/旧蒙版阻断，以及原单图连续修复、正式保存、DPI与真实LaMa的RGBA/范围外保护回归。受限沙箱阻断asyncio自通信套接字，最终测试在已获工具审批的本机环境运行；故障注入仅验证失败分支，不冒充真实结果。
- Node：`node --test tests/image_compression_ui/test_local_retouch_ui.mjs tests/image_compression_ui/test_batch_local_retouch.mjs`，26/26，通过；记录 `node-tests-final.log`。这些是几何、状态及源码合同测试，不是实际浏览器测试。
- 前端：`npm.cmd run build -- --outDir output/retouch_batch_20261104/build-final`，通过。构建单独保存，未覆盖正式dist。Python语法与相关差异检查通过。
- 实际引擎：`lama_onnx_2025jan`，`onnxruntime 1.27.0 / CPUExecutionProvider`，模型SHA256 `7df918ac3921d3daf0aae1d219776cf0dc4e4935f035af81841b40adcf74fdf2`，未修改。真实输入为原照片IMG_1032、1034、1035，分别由EXIF方向8、6、8归一化为3648×5472；未缩放图片。
- 蒙版含两处矩形、一段画笔及擦除区域，三图使用同一像素哈希 `a6c73e45158950a5f3d481dba29f364cc92a76cf0c1295e6ce3d68d83678e4a9`。批次 `2a5e5bb004e0429f8932dc70e319a796`。

| 输入 | Task | Result | PNG字节 | 范围外变化像素 |
|---|---|---|---:|---:|
| IMG_1032 | retouch_task_cc42fb5acf774446 | retouch_result_f4482ad6243b4284 | 28,586,375 | 0 |
| IMG_1034 | retouch_task_2a1ee800e0e54250 | retouch_result_98914716822a4860 | 24,706,168 | 0 |
| IMG_1035 | retouch_task_9e2ba8acbbfb4168 | retouch_result_56396e8de501434e | 25,572,948 | 0 |

完整Source、batch/item、路径、SHA与输出中心匹配记录见 `output/retouch_batch_20261104/real/real-validation.json`。三份输出完整解码，方向为1，尺寸3648×5472；PNG物理DPI为72.009，与源72的差0.009符合现有元数据合同0.01容差，EXIF DPI为72。三张照片本身不含Alpha；未把它们作为Alpha通道验收样本。共享登记重新加载后Result身份/哈希不变，输出中心API匹配3份正式结果。

真实取消批次 `9529529240f848da9c056ff7331c9a00`：返回约3.953秒，终态1张候选保留、2张取消、正式结果0。原图及设置哈希不变。三张正式结果的确认标记来自明确调用确认/保存接口的工程验收动作，不代表负责人视觉签收，也不是后台批量生成时自动确认。

整图：`output/retouch_batch_20261104/real/before-after-overview.jpg`；同语义100%局部：`before-after-native.png`。每对左为原图、右为结果，三行局部分别对应三张照片；已检查真实产物，仍由负责人作最终效果判断。

验证宿主是读取当前代码的独立进程，使用实际正式目录和共享登记。输出中心只执行原读接口，不启动压缩恢复任务；没有替换/重启当前主程序，不能把上述API与文件证据称为当前软件界面通过。

### 本轮真实界面验收与追加取消文件大小上限（2026-11-04）

负责人本轮仅授权解除本阶段界面工具停止限制；未授权替换正式dist、部署主程序或关闭其他实例。实际界面通过 Computer Use 浏览器工具操作，前端使用现有隔离构建，后端使用当前源码、实际正式目录和共享登记。先使用 `build-final` 验证批量链路，随后按本轮追加要求构建 `build-no-limit`，仅重启自有8862验收宿主。没有在旧正式页面上验收新功能。每个运行阶段的源码哈希、构建目录及当前生产只读函数来源记录在 `ui/runtime-*.json`；原图、结果真实解码，不使用Mock。

新增要求：单图导入、批量导入以及已有成品继续修复均去掉50MB文件字节上限，界面改为“不限文件体积”。完整解码、格式及4000万像素安全检查保留；内部蒙版安全检查保持。实际54,020,156字节、5000×3600的有效PNG通过单图和批量API及真实界面导入；该随机噪声PNG仅是接收压力夹具，不是商业画质样本，未发布为正式Result。

真实复验发现正式单图的原图链接仍依赖临时修复会话，重启后404。已仅在 `main.py/public_task` 中把瑕疵修复正式Task的该链接映射到现有 `/api/v1/tasks/{task_id}/source-file`，不改登记、原图、Result或修复算法。新增回归在会话失效后仍完整读取原图；真实结果页重载后，原图与成品均完整加载为3648×5472。

| 门禁 | 实际验证 | 技术结果 |
|---|---|---|
| 1 导入与共用蒙版 | 界面导入3张真实同尺寸照片；2个矩形、画笔和擦除操作；切图保留相同像素选区；不同尺寸、损坏图明确排除 | PASS |
| 2 逐图试修与版本 | 三图分别试修并显示对应照片；撤销修改蒙版后旧对比入口消失，确认禁用；恢复最终蒙版后使用版本7执行 | PASS |
| 3 执行与进度 | 真实界面顺序执行，观察1张候选/1张修复中/1张排队，最终3/3候选；处理期编辑禁用；3份实际最终蒙版哈希一致；引擎失败隔离复用直接API回归，界面负例均有排除原因 | PASS |
| 4 取消 | 从界面取消后续处理：1张候选保留、2张明确已取消、正式Result为0 | PASS |
| 5 确认另存与输出 | 未确认时输出中心搜索为0；界面逐张另存1张、勾选另存2张；输出中心搜索为3并进入真实对比；逐图核对Source/Task/Result及batch/item、路径、解码、尺寸、方向、DPI、字节和SHA | PASS |
| 6 原单图 | 真实导入、矩形标记、首次修复、调整新区域、二次修复、完成修整、正式结果查看；最终页面重载后原图和成品均完整加载，最终复验接口与控制台无新增错误 | PASS |
| 7 对照与签收材料 | 已检查并提交来自本轮界面结果的整图和原生100%局部；三张批量范围外变化均0，单图两轮分别与蒙版并集之外均0 | 技术PASS；人工签收PENDING |

本轮批次 `10533db1fdcf48dcb26f6ed8ff7b16b8`。完整逐图路径、SHA及字节见 `ui/file-checks.json`，单图及大文件接收、取消、最终接口结果见 `ui/ui-final-checks.json`。原图均保持，三张照片无Alpha；原有10项真实LaMa算法/Alpha证据因算法未变继续复用。本轮追加执行23项受影响API测试及1项会话失效原图回归，均通过；26项Node及隔离构建通过。并非再次运行旧32项全量。

证据保持真实失败边界：首次隔离宿主缺少原有任务列表/工作目录两个读接口，各出现一次404；补挂生产真实读实现后修复。另一次会话原图404定位为上述正式链接缺陷并修复。三条历史失败及原始控制台日志保留，不删除或改写；最终运行阶段重新加载单图与批量成品，实际图像解码成功，接口失败为0、控制台新增错误/警告为0。正式工作目录读接口原样读取现有正式实例；其余验收处理和Task读实现来自当前源码，不触发正式启动迁移、压缩恢复或其他处理。

本轮界面正式文件名称均以“验收_界面”标记；三张批量及一张单图Result是明确点击确认另存所生成的工程验收文件，不冒充用户商业成品或负责人画质签收。原正式8787/5173实例保留，正式dist及用户设置未改。

签收材料：`ui/ui-before-after-overview.jpg`（整图）、`ui/ui-before-after-native.png`（每对左原图、右结果，原生100%，三行对应IMG_1032/1034/1035）、`ui/07-output-center-three-results.jpg`（真实输出中心）、`ui/09-large-single-import.jpg`（54MB单图导入）、`ui/10-large-batch-import.jpg`（54MB批量导入）。

### 签收前复核（2026-11-04，重复任务卡）

重新读取真实仓库：版本仍为0.6.2-dev，分支与HEAD符合任务卡，staging为空。当前源码哈希与上述验收运行身份一致，三张批量和一张单图正式文件的实际路径、字节、SHA、Task/Result登记及原图哈希均与既有证据一致；因此复用已通过的Python、Node、隔离构建和完整界面链路，不重复开发、重测或生成正式结果。

Computer Use连接恢复后，重新打开已有批量成品的真实对比页；原图和成品均完整解码为3648×5472，本次页面控制台错误/警告为0。记录见 `ui/signoff-rendered-assets.json`，真实页面截图为 `ui/signoff-current.jpg`；整图和100%局部仍使用上节已核对的真实界面产物。该只读复核不代替负责人画质签收。

当前只观察到自有8862隔离宿主监听，8787/5173已未监听；本轮未启停任何宿主，也未修复、重启或部署正式实例。前次完整界面验收证据没有因本次环境变化失效；本次没有重新声明全链路运行通过。复核及保护记录见 `ui/signoff-precheck.json`、`ui/signoff-final.json`。技术门禁结论保持，唯一待完成项仍为下方负责人签收。

## BLOCKER

当前唯一未完成项：负责人最终画质签收。请对三张真实界面结果确认：

- 修复区域及共用位置正确；
- 100%局部的纹理、接缝和修复效果可接受；
- 整体构图、人物与未选区域保持，并同意本阶段收口。

本轮Computer Use已按明确授权恢复，原界面阻塞已解除。未收到签收前继续保持 `BLOCKED / NOT_READY`；不自动发布或部署，不进入下一阶段。

## PROTECTION

STAGING_EMPTY: YES。无Git写操作，无分支切换、stash、清理或回滚。原有32个tracked修改、原有untracked成果、压缩代码、正式设置、版本文件、现有主程序及正式dist受保护；文档原有内容保留，最终逐文件哈希与追加前副本核对见 `protection-final.json`。

没有修改模型/算法、新增依赖或改动输出中心合同；本轮仅依明确授权恢复本阶段界面工具。原图只读，新正式文件带验收名称并经既有防覆盖机制发布；没有删除验收结果、既有输出或用途不明文件。已识别并仅结束本轮被沙箱阻断的自有挂起测试进程，未结束用户软件。

Skill迭代判断：暂不需要更新；本次新增是阶段功能与验证记录，不回写Runtime Skill或Memory。

本轮最终保护证据：`output/retouch_batch_20261104/ui/protection-final.json`。请求的开发模型/推理配置为 gpt-6.1-terra/xhigh，客户端配置无法由现有执行工具核验或切换；全程单智能体，无子智能体。修复引擎仍为 lama_onnx_2025jan / CPUExecutionProvider。


## 2026-11-04｜按负责人授权部署，画质签收后置

负责人明确要求“先部署，后面测试后再沟通”，本轮据此覆盖此前暂不部署的限制；不代表画质签收或阶段冻结。正式前端已备份后更新，桌面入口 packaged_main.py --port 8787 已启动，当前进程25252，构建 V0.6.2-dev+b4fdde85dc03.dirty.20261104T015910829Z。运行状态 ready、正式目录就绪、LaMa 可用、max_upload_bytes=null，7条批量接口已注册；实际返回的入口、主脚本、样式与瑕疵修复脚本SHA均与部署文件一致，独立后续命令确认桌面窗口“影界 HDDE”响应。仅做部署与启动核验，没有重新运行图片处理或人工画质测试。

现有135份dist文件已完整备份并校验；本次发布32份构建文件，117份未被覆盖的旧资源原样保留，未清理。未修改产品源码、模型、算法、设置、版本或压缩成果，原8862隔离宿主未启停，无Git写操作。阶段仍为 BLOCKED / NOT_READY，负责人画质签收留待后续测试。部署证据与备份：output/retouch_batch_20261104/deploy_20261104/。


运行目录说明：本次桌面启动按既有实现生成 settings/webview/（WebView2 用户数据），因此 Git 新增 ?? settings/；该运行目录保留，未清理。settings/settings.json 的内容与部署前SHA一致，产品源码及受保护成果未改变。
