# Codex Changelog

## 2026-08-10 - UI-01B formal-page title baseline closure

- Removed the redundant page-level eyebrow from the shared formal header so every primary page title starts on the same top baseline; section-level eyebrows remain available where they carry real hierarchy.
- Kept the existing shared page frame, breadcrumb alignment, title typography, and business surfaces unchanged.

## 2026-08-10 - UI-01B formal-page alignment and header rhythm closure

- Replaced the work-page-only gutter with one `hdde-page-frame` and `hdde-page-stack` contract shared by the Shell breadcrumb, processing pages, diagnosis, correction, compression, retouch, output center, smart delivery, and settings.
- Standardized the desktop left start line, page-top spacing, header-to-content gap, and responsive gutters; the existing feedback dialog keeps its modal product role while sharing the same title/description spacing rhythm.

## 2026-08-10 - UI-01B shared work-page content gutter

- Added one shared `hdde-work-page` container contract for the processing center, image diagnosis, color correction, image compression, and local retouch workspaces; the 4K entry inherits the same rule through the processing center.
- Standardized the desktop content start line to a 22px safe gutter with responsive 16px/12px fallbacks, without changing upload, processing, Task/Result/Delivery, Settings, or formal-directory behavior.

## 2026-08-10 - Formal output directory naming closure

- Unified new formal output paths to `输出/4K高清增强`, `输出/1080P标准增强`, `输出/1080P安全增强`, `输出/颜色校正`, `输出/图片压缩`, `输出/标记修整`, and `输出/智能交付`; the 4K processing mode remains `4K高清画质增强`.
- Migrated the existing `4K增强` and `1080P标准版` directories by same-volume atomic rename after conflict preflight. All 79 files retained identical SHA256 values; no target was overwritten.
- Added compatibility resolution for historical Task/Result paths while new records use the formal names, and updated only the two directly related Settings path fields.

## 2026-08-10 - UI-01B formal-page rollout and redundancy closure

- 延续 UI-01A 精密工作台语言，将共享页面层级推广到图片压缩、颜色校正、标记修整、智能交付与既有详情/对比/报告页面；跨页面导航同时复位内容滚动位置。
- 处理中心将四步准备区收口为连续流程并移除重复任务标题；系统设置将五个重复信息区收敛为外观、本地目录、产品与版本三个权威区块；输出中心空状态补齐原因与下一步入口。
- 标记修整空载画布改为中性网格工作区，已载入图片仍使用既有深色画布；输出中心与反馈展示统一为正式增强命名，未修改处理算法、Task/Result/Delivery 合同或正式目录。

## 2026-08-10 - UI-01A precision workspace foundation

- 以品牌蓝 `#2D6FE8` 和中性表面建立明暗双主题语义令牌、统一字号/间距/圆角/焦点/禁用/低动效合同，并新增共享页面标题与本地图标组件。
- App Shell 收口为“工作台 / 图片处理 / 交付 / 系统”四组正式导航，移除导航状态徽标和重复页面标题信息；任务队列、历史任务、批量优化未恢复为一级入口。
- 图片诊断、输出中心、系统设置作为代表页接入统一页面结构；图片压缩、图片诊断、系统设置移除错误 Beta 身份，1080P正式命名统一为标准增强与安全增强。

## 2026-08-10 - Image Diagnosis V1 D2 product loop

- 新增一级“图片诊断”入口和正式页面，按结论、关键问题、技术证据三层呈现冻结D1真实结果，并将D1推荐原样映射到既有4K、1080P、颜色校正与图片压缩入口。
- `image_diagnosis` 在调用D1引擎前写入共享Task Registry，完成后在同一Task登记独立结构化Result；不生成无意义图片副本，不进入输出中心，也不建立平行Task/Result系统。
- 推荐动作通过浏览器内存中的当前`File`上下文交给既有正式页面，仅完成安全接收和模式预选，不自动执行处理；处理中心、历史任务、Runtime Log与Feedback Context继续消费统一事实源。

## 2026-08-10 - Image Diagnosis V1 D1 core

- Added a read-only `engine.image_diagnosis` boundary with a Pillow/OpenCV adapter, structured image facts, explainable quality issues, and evidence-based recommended actions; D1 does not create tasks, results, deliveries, or formal output files.
- Added conservative resolution, blur, noise, JPEG blockiness, exposure, highlight, shadow, white-balance, and color-cast diagnostics without a composite quality score or automatic processing.
- Added focused synthetic-sample tests for facts/EXIF/alpha, clear versus blurred content, exposure direction, color cast, noise, JPEG compression artifacts, recommendation consistency, and source SHA256/mtime protection.

## 2026-08-10 - F3 unified framework closure

- 1080P/4K、颜色校正、图片压缩与局部修整统一补齐FEATURE、TASK、RESULT事实字段；输出中心和智能交付继续复用既有合同，并将DELIVERY_ID回写到对应共享Task事实，未新增平行Registry。
- 处理中心在同一页面承载“当前任务 / 历史任务”，历史记录直接读取共享Task/Result/Delivery事实；任务队列、历史任务、批量优化兼容路由继续保留，但不再生成一级导航，既有批量队列与失败重试路径未删除。
- 现有Runtime Log补齐统一生命周期事件与product/test标识；Feedback Context统一携带真实版本、功能、任务、结果、交付、终态和正式目录状态，同时保持图片正文、完整日志及无关敏感数据隔离。

## 2026-08-10 - B-07 unified user feedback exit

- 全局、颜色校正、任务详情与质量报告入口统一复用同一反馈组件、上下文快照API和现有Feedback Context/ZIP生成器；用户打开反馈时冻结真实Task/Error/Runtime事实，后续轮询或任务变化不再改变反馈对象。
- 标准反馈合同升级为`HDDE-user-feedback-v2`，明确反馈包ID、合同版本、生成/捕获时间，包内自带有限相关事件、异常摘要、安全输入元数据、附件与隐私清单，不依赖继续读取用户`hdde.log`、Settings或任务目录。
- 前端仍可打开而后端不可达时，同一流程生成同合同的最低可用本地JSON反馈包；未知Task/Result保持不可用，附件只记录用户主动选择的脱敏技术清单且不自动加入或上传。
- 1080P安全报告与图片压缩页遗留的用户反馈按钮改接同一`UnifiedFeedback`流程；旧后端反馈API仅保留内部兼容，不再由当前用户入口直接调用，1080P历史基线与处理逻辑不变。
- 统一反馈包生成补齐独立`IDLE → GENERATING → SUCCESS/FAILED`交互状态：生成时禁用防重，成功时在操作区附近持续显示安全文件名与大小，后端不可达时明确标识本地安全降级，失败时显示脱敏原因、可用`ERROR_ID`并支持重新生成；反馈合同、B-06日志合同与A线处理逻辑不变。

## 2026-08-10 - B-06 precise local fault correlation

- 继续复用 `hdde.runtime`，在首次日志前建立每次应用运行唯一的 `RUNTIME_ID`，并由启动完成事件固定关联现有产品版本与B-01 Build ID；测试和Playwright可通过隔离运行根将日志物理写入临时目标，不接触正式 `hdde.log`。
- 真正程序异常新增可传播复用的 `ERROR_ID`、稳定脱敏 `ERROR_FINGERPRINT`、`TRACE_ID`、项目相对代码位置及少量调用摘要；同一根异常跨阶段重复记录时保持同一错误身份，普通成功和用户操作警告不生成错误身份。
- 颜色校正任务冻结功能、目的、批次、路由与安全源引用，反馈上下文只携带相关少量事件、安全图片技术元数据及诊断身份；完整业务文件名、绝对路径、敏感值、图片与完整日志均不进入诊断反馈。

## 2026-08-10 - F1 local-retouch unified feature/task/result chain

- `local_retouch` 使用稳定 `feature_key`，每次处理在调用现有 `LocalRetouchEngine → LamaOnnxAdapter` 前先向共享Task Registry登记独立 `retouch_task_*`，并保留pending、processing、completed/failed生命周期与源文件关系。
- Engine成功只生成临时Preview，不创建正式结果；人工确认保存后才生成独立 `retouch_result_*`，并在同一Task记录中建立 `SOURCE → TASK → RESULT`，新Task ID与Result ID严格分离。
- 处理中心继续读取现有 `/api/v1/tasks` 和共享Registry；`/tasks`兼容路由保留但不进入一级导航，未新增任务系统或修改LaMa、Mask、输出中心、智能交付及正式启动链。

## 2026-08-10 - F2 unified result to smart-delivery closure

- 输出中心从共享Task/Result Registry识别完整 `result_id`、`task_id`、`feature_key`、`source`、`result_file`，并将满足合同的正式结果标记为Unified Result；历史输出项继续兼容读取，未新增Output Registry。
- 智能交付新增 `result_ids` 正式输入并在服务端解析回真实输出中心成品；输出中心选择Unified Result后自动传递RESULT_ID，用户无需手工输入ID、路径或JSON。
- 交付记录以源 `result_id` 关联独立 `delivery_id` 和 `delivery_item_id`，同时保留TASK、FEATURE、SOURCE追溯；既有命名预检、冲突阻断、独占副本写入和源文件保护合同保持不变。

## 2026-08-10 - B-05 recent-feature runtime logging closure

- 复用现有 `hdde.runtime` 与正式 `诊断/日志/hdde.log`，为单图颜色校正、批处理队列、人工结果确认和B-04反馈报告生成补齐最低必要的开始、完成、失败及真实TASK_ID/BATCH_ID关联；不存在的RESULT_ID继续保持不存在。
- 处理中心与正式启动/依赖/目录异常继续复用既有正式日志；输出中心、智能交付和局部修整按A线边界标记 `DEFERRED_BY_A_LINE`，未修改其业务核心或结果关系。
- 正式日志新增统一绝对路径和敏感键值脱敏，保留安全文件名或 `诊断/日志/hdde.log` 引用；未建立第二套日志协议，也未将完整日志写入反馈包。

## 2026-08-10 - Delivery marker and local retouch V1 smart-delivery closure

- 局部修整正式结果继续复用阶段6智能交付；预检要求有效共享 `RESULT_ID` 与 `task_registry` 映射，拒绝仅凭目录文件或文件名进入交付。
- 智能交付预览与执行响应透传源正式结果ID和处理类型，执行结果同时绑定真实 `DELIVERY_ID`，形成可追溯的 `SOURCE → RETOUCH RESULT → DELIVERY COPY` 关系；既有命名、冲突和副本完整性合同保持不变。

## 2026-08-10 - B-04 unified recent-feature feedback context

- 新增共享只读 `Feedback Context` 事实适配器，复用现有任务ZIP反馈包与颜色校正JSON反馈报告，统一记录真实功能来源、阶段、状态、现有TASK_ID/RESULT_ID、安全文件引用及B-01/B-02/B-03运行摘要；不存在的业务事实保持为空，不生成虚假标识。
- 单图颜色校正、批处理/任务队列、处理中心、对比质检与运行异常完成覆盖；输出中心、智能交付、局部修整按A线边界标记 `DEFERRED_BY_A_LINE`，未修改其业务核心。
- 现有颜色校正反馈卡片增加脱敏上下文预览与本地附件主动选择提示；附件不写入报告、不自动上传，仍由用户决定是否随报告发送。

## 2026-08-09 - B-03 side-effect-free health check

- `GET /api/health` 不再调用会执行写探针的工作目录解析链，改为复用B-02启动校验快照与当前只读存在性检查；连续健康检查不创建临时探针文件、不改变Settings或正式目录元数据。
- 保留既有健康响应和路径字段，并以 `healthy`、`directory_ready`、`settings_status` 及 `degraded` 状态表达真实故障，不将不可写性伪装为永远健康。

## 2026-08-09 - B-02 unified read-only runtime status

- 新增只读 `GET /api/runtime/status`，统一返回现有产品版本、已编译Build ID、应用运行状态、Settings启动加载状态及正式根目录启动校验与当前只读存在性状态。
- Build ID直接读取B-01前端产物，不在运行时调用Git或生成新构建号；状态请求不写Settings、不探测写入、不创建或修复正式目录，也不回退项目tmp。

## 2026-08-09 - V0.5.4-dev unified version and build identity automation

- 将 `product_version.json` 的统一运行身份更新为 `V0.5.4-dev`，系统设置的平台信息与更新信息继续从同一版本源自动读取；版本工具最小增加 `-dev` 预发布标识支持。
- 当前构建改由Vite在构建时固定注入，包含产品版本、Git短SHA、工作区clean/dirty状态和UTC构建时间；同一产物稳定，新构建自动变化，正式页面运行时不读取Git或当前时间。
- 将平台信息中的“目标分辨率”改名为“默认交付分辨率”，准确表达默认1080P配置而不否认独立4K尺寸适配能力；历史 `1080P研究基线 V0.4.6 RC8A` 保持不变。

## 2026-08-02 - V0.5.4-dev Stage 2 visual quality closure V2

- 将颜色校正核心升级为自适应曝光与色调、可信中性色白平衡、选择性色彩平衡、局部层次与受控清晰度处理；所有动作仍只调整现有像素，不改变尺寸、构图、Alpha或内容。
- 会议逆光改为人物/前景与高亮背景独立度量和处理，结果报告记录两者真实增益；新增肤色、高亮背景、暗部噪声及低调设计色彩意图保护，避免普通图和黑金设计图被强行提亮或改色。
- 正式默认输出合同经代码确认仍为`D:\影界文件\输出\颜色校正`，无需修改Settings或目录逻辑；本轮A/B/C三组新对比等待用户人工视觉复核，阶段2状态为`TECHNICAL_PASS_VISUAL_REVIEW_REQUIRED`，未冻结且未进入阶段3。

## 2026-08-02 - V0.5.4-dev Stage 2 single-image automatic color correction

- 将`/color-correction`从占位页接入正式单图闭环：本地图片接收、正式输出目录、自动处理、前后滑杆、真实结果报告、打开结果/目录、复制路径和本地问题反馈报告。
- 新增独立可复用的单图颜色校正核心，采用中性色偏约束、受控亮度曲线、人脸/前景识别和高亮背景保护；不改变尺寸、构图、Alpha或原图，不使用生成式重绘。
- 复用阶段1同一任务注册表与`pending → processing → completed/failed`生命周期；输出完成前强制验证存在、解码、尺寸、格式、扩展名、SHA256与真实像素变化，失败不回退项目临时目录。
- 会议逆光真实样本识别11张人脸，人物/前景亮度由73.51提升至88.58，暗部风险由21.43%降至9.45%，高光风险由0.31%降至0.16%；正式输出为2133×1600 JPEG，本地反馈报告不包含图片、完整路径或外部上传。
- 颜色校正默认输出收口到正式根`输出/颜色校正`，不修改Settings；定向Python测试、前端合同测试、既有压缩生命周期回归、Vite构建和一条Playwright真实路径通过。

## 2026-08-02 - 4K half-product capability freeze

- 根据正式 `four_k_v1` 实现、既有PoC技术证据和用户人工复核结论，将4K能力冻结为 `PILLOW_LANCZOS_SAFE_RESIZE`：安全尺寸适配已完成，真实视觉增益与AI安全增益均未证明。
- `PHOTO_BALANCED` 以 `REJECTED_NO_GAIN` 退出，`CUNET_DEPTH` 以 `REJECTED_TECHNICAL` 退出；两条候选均不接入正式产品，保留LANCZOS安全路线，未来4K增强研究延期。
- 用户可见4K页面继续仅表达高质量尺寸适配与真实输出，并明确不代表细节重建、AI超分辨率或已证明画质增益；正式4K实现、接口和输出合同未修改。
- 下一任务登记为图片压缩正式版；本轮未开始图片压缩开发。

## 2026-07-30 - 4K core processing and single-image product loop

- 在冻结权威模块中实现单图Pillow LANCZOS执行、Alpha预乘缩放、ICC保留、正式PNG原子写入、成品解码/尺寸/原图哈希核对，并通过现有`/api/upload`、任务注册表与SSE返回真实处理阶段。
- 新增`4K增强适配`单图入口，复用现有任务详情、滑杆对比和质量报告组件；4K分支仅展示尺寸适配事实与能力边界，不展示1080P评分或技术路径字段。
- 真实S01样本经产品路径生成2732×3840 PNG，滑杆交互、共享报告、Console/Network、定向Python/前端测试和Vite build通过；Settings与冻结原图哈希保持不变。

## 2026-07-30 - 4K V1 route and single-image contract freeze

- 依据阶段1冻结标准与阶段2负结论，4K V1唯一正式路线确定为`PILLOW_LANCZOS_SAFE_RESIZE`；Route A保持淘汰，Route B保持增益未证明且不进入产品路线。
- 在现有`engine.image_processing_routing`权威入口冻结`4k_v1`/`delivery_4k_v1`请求参数、长边3840与ROUND_HALF_UP尺寸规则、原图直出保护、PNG输出、任务与阻断语义，以及上传、进度、对比、报告和打开结果所需字段。
- 能力边界固定为`HIGH_QUALITY_SIZE_ADAPTATION_ONLY`：不宣称细节重建、超分辨率或已证明画质增益；本轮未接入API/UI、未运行旧PoC或生成新画质包。

## 2026-07-23 - 4K Stage 2 automatic-audit remediation and review package rebuild

- 修复候选技术状态聚合：`success`现在由来源、解码、目标尺寸、比例、格式、Alpha、几何、方向、拼块缝和结构安全十项强制门禁共同计算；任一`REVIEW/FAIL/BLOCKED/UNKNOWN`均不能成功，几何结论改由真实`transform_trace`提供证据。
- 故障探针记录路径收紧为系统临时隔离根内相对路径；写入前统一解析实际目标并拒绝绝对路径、`..`穿越、符号链接/目录联接/重解析点以及Settings、正式目录、仓库和阶段资产路径。
- Route B在权重模糊后重新施加固定3像素Alpha硬保护带；S08实测保护像素560725、保护区RGB变化0、最大RGB变化0、Alpha变化0，黑底/白底/棋盘格合成变化均为0，非保护区仍有受控增量。
- 新批次`batch_20260723T090034_audit_remediation_8b1edb4b`只读重评旧Route A并保持`REJECTED_UNSAFE`，使用原模型、原执行器和统一参数重生成8张Route B；建立16行执行矩阵、8组全图、14组ROI、28份原生100%局部、Alpha证据和新旧批次替代清单。
- 定向测试`40/40 PASS`；新包仅恢复`PENDING_HUMAN_VISUAL_REVIEW`，不证明视觉增益、不冻结阶段、不进入阶段3。原阶段2批次、阶段1资产、Settings、Skill、报告模板及AGENTS保持不变，未执行Git写操作。

## 2026-07-22 - 4K Stage 2 conservative AI enhancement PoC review package

- 使用本地RealESRGAN_x4plus ncnn Vulkan固定模型与统一参数，对阶段1冻结8张原图真实执行两条候选路线，共生成16个4K PNG；全部通过尺寸、比例、解码、Alpha、无裁切/拉伸/补边等技术门禁。
- Route A直接AI结果在中文、Logo、人物身份、皮肤/头发、材质和复杂纹理中出现结构重构，已标记为`REJECTED_STRUCTURE_UNSAFE`；Route B采用LANCZOS安全底图与受控高频增量，结构安全技术预检通过，作为唯一人工复核候选。
- 复用阶段1全部14组冻结ROI，生成8组完整对照、14组语义对照和42份原生100%裁切；Route B相对LANCZOS的真实可见增益尚未证明，状态保持`PENDING_HUMAN_VISUAL_REVIEW`和`NOT_READY`，未进入阶段3。
- 运行前后8张来源图、8份快照、24个传统候选、阶段1目录树和Settings完全一致；未接入API/UI、未创建正式4K目录或项目根`runtime_data`，未执行Git写操作。

## 2026-07-22 - 4K Stage 1 frozen standard, golden samples and traditional baseline

- 冻结4K V1基础标准：原图直出、长边3840、统一四舍五入、保持比例，禁止裁切、拉伸、补边和从1080P结果二次放大；已达4K明确返回无需处理。
- 从现有真实/历史PoC原始输入固定8张黄金样本并建立字节级快照与完整SHA256 manifest；S08半透明样本的低复杂度覆盖限制保留在清单中，未下载或生成新样本。
- 独立实验入口真实生成Pillow BICUBIC、Pillow LANCZOS、OpenCV INTER_CUBIC共24个无损PNG候选；尺寸、比例、解码、格式、Alpha和原图保护全部通过。
- 修复冻结审核发现的三项证据缺口：重建14组同归一化语义ROI对照并增加42份候选原生100%局部，反向映射最大误差0.246659原图像素；候选六阶段异常统一记录样本、方法、阶段、类型和信息，隔离CLI故障探针退出码2且不生成候选。
- 使用修正对照重新核验后，唯一传统默认基线仍为Pillow LANCZOS；S01中文样本和S03人物样本各由两个独立Python进程重新读取原图生成，文件与像素SHA256完全一致。定向测试`16/16 PASS`，未接入API/UI、未写Settings、未创建正式4K目录或项目运行回退目录。

## 2026-07-22 - V0.5.3 formal directory migration and closure

- 正式目录统一收口为 `输出/1080P标准版`、`输出/1080P安全增强`、`输出/图片压缩` 与 `诊断/日志`、`诊断/反馈包`、`诊断/报告`；活动输入和运行缓存放入对应功能目录的隐藏子目录，不再重建旧一级目录。
- 新增幂等应用数据迁移：同盘优先原子移动，复制时执行大小与流式 SHA256 校验，同内容去重、异内容安全改名，失败保留源文件，仅删除迁移后为空的旧目录。
- 启动仅在 Settings 完整有效、正式根目录就绪且保存根目录一致时检查已知旧路径；正常状态快速返回 `NO_OP`，迁移失败保持目录功能阻断且不提前写 Settings。
- 已对 `D:\影界文件` 执行真实迁移：旧目录均为空，迁移/清理后两份根文件原地保留；Settings 仅更新标准输出、安全增强输出和图片压缩输出三个旧路径字段，独立第二次执行为 `NO_OP`。
- 验证：迁移专项 `4/4 PASS`、相关 Python `py_compile` 通过；未运行前端构建、Chrome E2E、全仓回归或批量图片处理，未执行 Git 写操作。

## 2026-07-20 - V0.5.3 formal directory governance and failure blocking

- 新增两阶段统一运行日志：启动早期仅输出控制台，正式目录就绪后按需写入 `诊断/日志/hdde.log`，采用 UTF-8、约 5MB 单文件和3份轮转；接入应用启动、Settings决策、目录校验、标准图片任务、路线、输出异常、结果、错误分类与耗时，文件日志失败仅降级控制台且不回退临时目录。
- 正式根目录与必需子目录统一使用原子创建所有权判定：仅当前 `mkdir` 成功返回时登记为本轮新建；并发创建触发 `FileExistsError` 时继续目录与可写性校验，但不纳入失败清理。

- 正式根目录只读取首次正式默认目录或用户已保存并通过校验的目录；删除正式启动、标准上传与安全增强链路中的项目 `tmp` / `runtime_data` 静默回退。
- 启动校验失败不再改写 `last_app_data_root`，`/api/app/workdir` 返回明确的 `directory_ready`、错误代码与用户提示，且不返回虚假的输出目录。
- 处理中心在正式目录未就绪时显示明确错误、提供系统设置入口并禁用处理；系统设置新增“选择并校验正式目录”，只有校验通过后才持久化用户主动选择。
- 收口图片压缩 intake、预检、执行、输出与文件访问入口的统一目录门禁；目录失败时不创建或改写 Settings，异常 workdir 响应和处理中心不再暴露或开放被拒绝路径。
- 将标准、压缩与安全增强实际使用的必需子目录纳入统一就绪检查；子目录冲突、创建失败或不可写时返回明确失败路径并阻断处理，仅逆序清理本次新建且仍为空的目录。
- 产品版本更新为 V0.5.3「本地目录治理与诊断基础」。

## 2026-07-18 - V0.5.2 Stage 5 image processing preflight, frontend recommendation panel and settings closure

- 新增统一图片画像、确定性处理路由与只读 `POST /api/image-processing/preflight`，复用阶段4 source token resolver，不增加 tombstone，不创建任务或输出。
- 请求体、枚举、目标与冲突错误统一返回 HTTP 400；token 不存在、过期、角色不匹配或源文件不可用统一返回 HTTP 404 `TOKEN_NOT_FOUND_OR_EXPIRED`；冻结合同中的 `IMAGE_DECODE_FAILED` 按合同优先级保留 HTTP 422。
- 新增 `product_version.json` 单一版本源、`tools/manage_version.py` 版本更新工具及前后端 V0.5.2 一致性接线，保留历史 `V0.4.6 RC8A` 研究基线文案。
- 系统设置删除重复功能状态面板和重复二级介绍区，保留顶部主标题、主题快捷切换、左侧导航、外观设置、本地目录、更新信息与关于影界；“可修改/只读”说明下沉到对应卡片。
- 图片压缩页接入阶段5预检推荐面板，支持4种 purpose、6种 status、6种 action、24项 reason code 与10项 error code；只在用户点击后调用正式预检 API，“使用推荐方案”只预填阶段4既有参数，不自动执行。
- 前端增加请求取消、响应序号和图片/目的/参数变更失效保护；Chrome 真实服务覆盖 PNG、JPEG、上传限制、尺寸缩小、长图、未来增强、动画多帧、token 404 和解码 422，并确认无任务、输出或反馈包副作用。
- 系统设置进一步删除“配置默认输出目录”，正常状态不显示仓库内部运行路径；只有真实 `project_tmp` 回退时显示用户可读警告，不修改目录解析与持久化逻辑。
- 验证：阶段5 `66/66`（fixture `48/48`）、阶段3 `39/39`、阶段4 API `75/75`、版本 `11/11`、前端 `104/104`、Vite build、真实 HTTP 服务和 Chrome `11/11` 专项验收均通过；冻结范围 `30/30`、受保护文件 `5/5`，未暂存、commit、push、tag 或创建 PR。

## 2026-07-16 - V0.5.1 Stage 4 image compression product closure

- 新增阶段4本地图片压缩 API/UI，保持阶段3冻结50字段结果合同不变，支持 PNG无损压缩、尺寸缩小、上传适配、人工视觉复核和安全预览。
- 长图增加适合宽度、100%真实像素、全图概览、全屏、顶部/中部/底部定位、单栏原图/结果切换及宽度风险预检；无候选时不复制原图冒充结果。
- 尺寸缩小默认改为固定短边，产品层接收 `target_short_side`，按统一舍入规则计算成对宽高后交给冻结引擎；目标短边相等返回无需处理，超过原图时执行前阻止放大。
- 上传适配的最大宽度与最大高度增加可切换的长宽比锁定；锁定后修改任一边会按已选原图比例自动更新另一边，默认保持未锁定以保留长图“高度不限”和平台独立硬限制能力。
- 人工视觉复核区修正主按钮继承全局上边距导致的错位，三个结论按钮统一同一基线、宽高和内容居中。
- 修复长图切换到100%真实像素后其他查看模式可能失效：上方原图预览与下方复核预览改用独立滚动状态，并阻止程序化滚动事件反向回写形成状态循环。
- 进一步修复100%预览的真实点击阻断：预览外框固定为所在工作台列宽，原始像素图片只在内部画布滚动，工具栏不再被固有图片宽度推离可视区域。
- 输出根目录固定映射为 `PNG无损压缩`、`尺寸缩小`、`上传适配` 三个目录；新结果扁平存放，文件名保留中文并包含操作、参数、时间和短ID，不创建日期、task或单任务目录。
- 测试反馈包改为与输出图片同目录、同 `output_stem` 的 `_测试反馈包.zip`，默认不包含原图、输出图或私人绝对路径，并记录长图与固定短边验证字段。
- 补齐测试反馈包安全下载闭环：生成接口返回独立的本地显示路径与 opaque `download_url`，新增限时 `feedback_package` 角色下载令牌、ZIP类型/中文文件名/SHA校验，并在结果区提供真实下载链接、打开目录和复制路径操作；更换图片、清空、重新处理及令牌过期会清除旧链接，无候选任务可生成不含图片的诊断反馈包。
- 自动审核修正无候选诊断反馈包误用源文件 stem 的问题：诊断包现在同样包含操作、时间和短ID，同一源文件重复任务不会发生同名冲突。
- 第二轮自动审核收紧反馈包续期：过期token未经访问直接续期时旧链接仍明确返回410；续期和重复生成前必须重新核对登记路径、ZIP有效性及原SHA，禁止把被篡改的既有ZIP以新SHA重新登记。
- 第三轮自动审核关闭下载校验与实际响应之间的文件替换时间窗：下载端对同一份已捕获ZIP字节复核体积、ZIP结构和双重SHA后再返回；前端同时严格校验包名、显示路径/功能目录、有效期和布尔字段类型。
- 测试反馈包最终统一为 `summary.md`、`task.json`、严格50字段 `result.json`、`review.json`、安全 `environment.json`、`validation.json`、`warnings.json`、`manifest.json`、`manifest.sha256` 和 `evidence/README.md`；普通图不再生成长图冗余文件，只有长图额外生成 `long_image_validation.json`，总结按真实技术/视觉/交付状态动态生成。
- 双manifest对除自身外的全部包内文件使用稳定相对路径、SHA256和体积校验；真实下载继续使用独立opaque反馈令牌，ZIP默认不包含原图、输出图、token或私人绝对路径。
- 验证：阶段3回归 `39/39 PASS`、阶段4 API `75/75 PASS`、前端纯函数/会话 `68/68 PASS`、真实5173代理至8787完整闭环 `79/79 PASS`、反馈包六类真实HTTP下载 `6/6 PASS`、Vite build与 `git diff --check` 通过。
- Codex 已在 Google Chrome（Chromium）中完成真实 GUI 验收：验收记录22/22完成，原8类8/8通过、长图7/7通过、固定短边5/5通过，反馈包可见链接真实点击下载通过，并保存30张截图和25份结构化证据。视觉结论为 AI 辅助 GUI 复核，不代表用户本人复核；当前控制接口未暴露 DevTools Network，由 API、真实服务和下载自动回归补充覆盖，作为非阻断备注保留；Microsoft Edge 未单独完成专项兼容性验证。O08 验收说明“1B”与当前UI最小值“0.01KB”的文字差异已保留为备注，不改变产品行为。阶段状态更新为 `BROWSER_ACCEPTANCE: PASS_WITH_NOTES`、`FEATURE_IMPLEMENTATION: PASS_WITH_NOTES`、`FEATURE_SCOPE: FROZEN`、`STAGE_4_FINAL_STATUS: PASS_WITH_NOTES`、`STAGE_4_COMMIT_READINESS: READY`；未commit、push或tag。

## 2026-07-12 - V0.4.6 RC8A portrait route and small-text truthfulness follow-up

- 修复大面积高置信单人人像被通用fast路线提前接收，以及24人合影因高text_ratio误入全图Real-ESRGAN的问题；新增独立人物RE执行资格门禁和 `portrait_group_guard` 证据。
- 人物上下文缺少身份/结构指标时以 `evidence_missing / portrait_metrics_missing` 阻断，不再允许非人物profile掩盖人物指标缺失。
- 小字链路增加局部放大亮度细节恢复、人物ROI排除、羽化回贴、笔画宽度/结构/过冲/halo/背景侵入及矩形边界检查；候选不足或增益不成立时真实回退。
- 纯内存与固定图块共41项通过；定向01/04/05/06各运行一次。01和06人物路线修复成立；04/05小字均为0增益，05另有容器边缘保护失败，因此小文字继续阻断收口。
- 后续根因修复建立04/05已保存ROI固定调试集，引入文字行几何证据、文字结构掩膜及容器长直线排除；纹理、光点、图标和容器线可输出 `not_applicable` 且保持不变。
- 固定ROI门禁仍为 `BLOCKED`：04三组辅助小字均无正增益；05仅姓名类形成安全正增益，说明和标签仍回退。按门禁未运行04/05完整图片，候选代码不具备提交资格。
- 端到端真实性门禁将 `insufficient_gain / blocked / evidence_missing / automatic_detection_failed / boundary_unverified` 统一映射为同步结果 `BLOCKED`，不再允许 `PASS_WITH_NOTES` 或 `pass_candidate`。
- 固定ROI门禁现同时要求自动候选命中、正确角色覆盖、结构确认和真实边界证据；回退改为文字结构掩膜羽化恢复并实测边界，`reliable_text=false` 时硬禁增强。当前04/05自动检测仍未命中目标角色，因此继续阻断且未运行完整图片。
- 发布链路改为完整画布自动检测后生成带bbox、自动角色及文字/背景/容器掩膜的候选契约，同一候选对象直接驱动小文字增强；手工ROI固定标记为debug-only且无发布、端到端门禁资格。
- 小文字候选状态统一为 `candidate_not_applied / candidate_applied_then_reverted / enhanced`，回退默认精确恢复stage input；边界审核与回退事实独立。新增可达自动结构通过路径及带检测ID、bbox、输入/代码签名和证据文件的人工确认契约。
- 新增17项完整画布端到端接线测试并通过，原14项与现17项回归同时通过；本轮状态为 `PASS_END_TO_END_WIRING`，但 `allow_full_image_run=false`，未处理自动检测召回率或文字角色分组。
- 修复source与stage尺寸变化时自动bbox/三类mask坐标契约：记录source/stage尺寸与坐标空间，按独立 `scale_x/scale_y` 使用floor/ceil映射bbox，三类二值mask以最近邻映射并固定阈值；契约失败在评分和增强前阻断。
- 零候选现区分 `no_applicable_text` 与 `evidence_missing`；后者无release/end-to-end资格。边界审核改为读取完整stage/output画布，逐边比较ROI内环与框外相邻环并记录实际可测边。
- 新增23项多尺度与跨边界专项并通过，原17项接线测试改为包含2倍画布，原14项与现17项继续通过。本轮状态为 `PASS_SCALE_AND_BOUNDARY_CONTRACT`，`allow_full_image_run=false`。
- 本轮未修改Dashboard、delivery guard、`final_output_url`、JPG95、版本号或非人物画质参数，未commit/push/tag。

## 2026-07-05 - V0.4.6 RC1 delivery_light lightweight delivery copy

- Beta 在 JPG95 candidate 通过安全门后新增 `delivery_light/` 轻量交付副本，直接复制 candidate，不重新编码，不替换 PNG final。
- 新增 `light_delivery_*` 字段并同步 Dashboard / Beta 报告页与反馈包 CSV，用于区分 PNG final、JPG95 candidate 和可直接取用的小体积交付副本。
- 本轮不改变 `output_path`、`output_size_bytes`、`output_format`、`final_output_url`、delivery guard、compression gate 或标准版 final 选择逻辑。

## 2026-07-05 - V0.4.7 planning delivery naming rule engine

- 新增 `engine/delivery_naming` 独立规则命名引擎，支持用户模板、序号位数、字段来源、字段缺失标记、Windows 文件名安全清理、重名消解和 `rename_map.csv` 导出。
- 新增 `tools/experiments/delivery_naming_smoke.py`，用临时文件验证规则命名、字段缺失、非法字符清理、重名处理和映射表字段。
- 本轮不接 Dashboard UI，不修改图像增强流程、`output_path`、`final_output_url`、delivery guard、compression gate 或标准版 final 选择逻辑。

## 2026-07-02 - V0.4.6 RC1 JPG95 candidate manual review recommendation

- C-2-B 仅接入路线 B：Dashboard / Beta 报告页可记录 JPG95 candidate 人工复核建议（建议采用 / 保留 PNG / 拒绝候选 / 继续检查）。
- 反馈包 CSV 增加 JPG95 candidate review 字段与 `candidate_is_final_output=false` 记录，继续保持 `output_path`、`output_size_bytes`、`output_format` 指向 PNG final。
- 本轮不替换 final output，不改变 `final_output_url`、delivery guard、compression gate、标准版 final 选择逻辑或 JPG95 candidate 生成阈值。

## 2026-07-02 - V0.4.6 RC1 feedback package size field alignment

- 对齐 1080P 安全增强 Beta 反馈包体积字段：`image_results.csv` 优先读取 `processed` 中的 `input_size_bytes`、`output_size_bytes`、`size_ratio`、contact sheet light 与 JPG95 candidate 字段，避免 Dashboard minimal package 缺少持久输入目录时 `input_size` 回退为 0。
- `diagnostics.json` 增加 `generated_at`、branch、dirty worktree、modified/untracked 计数与 `git status --short` 摘要，用于区分反馈包采集 commit 与当前未提交工作区状态。
- 本轮只修复反馈包 / CSV / diagnostics 字段一致性，不改变 final output、JPG95 candidate 采用策略、`final_output_url`、delivery guard、compression gate 或标准版流程。

## 2026-06-29 - V0.4.6 RC1 safe 1080P Beta selected input binding

- 修复 Dashboard 1080P安全增强 Beta 处理默认测试样本而非当前队列图片的问题。
- Dashboard Beta 请求改为 multipart 上传当前队列文件，不再发送默认测试样本目录作为输入源。
- Dashboard Beta 增加 `beta_run_id`、前端点击阶段日志与 `NEED_RESELECT` 状态，真实 `File` 对象失效时阻止请求并提示重新选择。
- Dashboard Beta 日志改为首层可读文本，并为 Beta fetch 增加 300 秒超时兜底，避免永久停留在 35%。
- Beta 后端阶段日志改为有界队列异步写入，避免 stderr 输出阻塞 uvicorn worker。
- Beta 输入被安全策略跳过时，API 和 Dashboard 透出 `BETA_INPUT_SKIPPED`、具体文件名、skip reason 与 metrics，不再显示泛化失败文案。
- 修正暖色/橙色高文字密度商业图被 `skip_portrait_metrics` 误杀的问题，高文字密度且有足够边缘结构的非人像商业图可进入 Beta 增强。
- 重新选择本地图片时清理旧 Beta 失败态、旧输出与旧错误，当前队列回到待生成状态。
- Beta API 读取并回显 `beta_run_id`，新增 `BETA_API_*` 请求、字段、文件、增强与响应阶段日志。
- Dashboard Beta 增加 `selected_file_names_encoded`，避免中文文件名在 multipart 边界被转码后影响输出命名。
- Beta API 加固 multipart 字段解析、中文文件名解码、临时文件保存和结果归一化，避免异常时返回裸 500。
- Beta API 业务失败改为 HTTP 200 + `ok=false` 结构化 JSON，避免浏览器 Network 只显示 `500 Internal Server Error`。
- Dashboard Beta 点击前校验真实 `File` 对象，文件访问失效时提示重新选择并阻止无效请求。
- Beta API 增加 `BETA_REQUEST_INPUT_FILES` 与 `BETA_RESOLVED_INPUT_FILES` 阶段日志；没有显式输入文件时返回 `BETA_INPUT_MISSING`。
- `safe_1080p_enhance.py` 在 flat/business 模式下只处理显式 `input_files`，并在结果中返回 input/output 映射。
- Dashboard Beta 前台按钮改为使用 `output_path` / `results` / `enhanced_files`，复制成品路径不再依赖普通任务 `final_output_url`；对比、报告、系统诊断与 batch report 在 Beta 下禁用或隐藏并说明原因。
- Dashboard Beta 队列行 `定位`、`查看对比`、`报告` 改为 Beta 专用行为：定位同步当前队列样本，对比使用 contact sheet / output_path，报告展示轻量结果摘要和反馈包入口。
- Dashboard Beta 对比查看按标准版对比结果骨架收口，交付报告按“质量报告终审 / 本地报告中心”骨架收口，保留 Beta 本地结果映射与反馈包入口，不强接标准 QualityReportPage。
- Dashboard 增加 1080P安全增强版 Beta 核心增强任务页，使用前端阶段状态和 API 返回结果映射 Progress Timeline / BETA STAGE LOG，不强接标准 SSE。
- Dashboard 主控区收口为“图片导入 / 处理模式 / 输出文件夹 / 开始处理”任务准备条，队列、交付看板与反馈包入口统一标准版和 Beta 展示字段。
- Dashboard Beta 对比页补充 contact sheet 网页预览排查与最小接入：若返回 `contact_sheet_url` / `contact_sheet_preview_url` 等可浏览器访问 URL 则直接渲染，否则保留本地预览未接入降级态并强化说明；不改后端 API、SSE、`final_output_url` 或标准版流程。
- Dashboard Beta 提交前收口：清理旧反馈包死代码，确认 contact sheet 无可用 URL 时继续保留本地预览未接入降级态，统一 Beta 对比页版本标识与返回工作台文案；不涉及后端 API、SSE、`final_output_url`、delivery guard 或标准版流程。
- Dashboard Beta 交付报告页进行视觉减负：压缩核心质量指标展示高度，收敛本地报告中心路径信息，输出绑定改为摘要展示；不改变后端接口、标准版流程和质量字段策略。
- Dashboard Beta 补齐输出体积诊断字段：区分 final output 与 contact sheet 体积，前端展示输入体积、成品体积、体积倍率、contact sheet 体积和输出格式；本轮只统计，不改变任何压缩、格式、增强或交付策略。
- 新增输出文件体积压缩试验脚本，支持 PNG/JPG/WebP 候选体积对比，区分 final output、透明 PNG、contact sheet / preview；本轮只做实验，不改变正式交付链路、压缩策略、`final_output_url` 或 delivery guard。
- 新增压缩候选视觉 QA 守门打包脚本，生成候选对比 contact sheet、视觉风险摘要与补丁 C 候选判断；本轮只做实验 QA，不接入正式链路、不改变 `final_output_url`、delivery guard 或 compression gate。
- Beta contact sheet / preview 接入轻量 JPG90 保存，新增 `contact_sheet_light`、`contact_sheet_light_size_bytes`、`contact_sheet_light_format` 和 `preview_only` 标记；final output、`final_output_url`、delivery guard、compression gate 与正式成品保存策略不变。
- C-2-A 新增 1080P安全增强版 Beta 非透明产品广告图 JPG95 candidate，仅在 `commercial_non_portrait`、无真实 alpha、低文字密度且体积收益达标时生成；candidate 仅供人工复核，不替换 `output_path`、`final_output_url`，不改变 delivery guard、compression gate 或标准版流程。
- Beta 测试反馈包支持 Dashboard multipart minimal package，缺少持久输入目录时不再只返回 `Diagnostic feedback package blocked`。
- 测试反馈包环境信息拆分为 Windows 友好显示字段与底层诊断字段，`10.0.xxxxx` 内核版本不再作为用户系统版本展示。

## 2026-06-29 - V0.4.6 RC1 safe 1080P Beta API timeout

- 修复 `/api/beta/safe-1080p/enhance` 在 Real-ESRGAN 子进程卡住时长期不返回的问题。
- Beta 后端增加阶段日志：请求、路径解析、增强开始、Real-ESRGAN 子进程、扁平输出写入、contact sheet、响应与失败。
- Real-ESRGAN 子进程增加 `timeout_seconds=300`，超时或异常返回结构化 `FAILED` JSON，前端可进入失败态并恢复按钮。
- Beta 阶段日志、stderr tail、error message 与失败 summary 增加用户名、设备名、IP、MAC 脱敏。
- 验证：`npm.cmd run build`、`py_compile`、1 张真实图脚本 smoke、Beta API smoke、`tests/diagnostics/test_v0453_api_pipeline.py` 均通过。

## 2026-06-17 - V0.4.6 quality engine phase 1

### 已完成

- 增强小字区域识别：增加微小笔画、低分辨率中文小字和说明文字的 mask 检测。
- 增强 `text_safe` 模式下的小字局部可读性处理，仅调整 Lab 亮度通道，不重绘内容、不改色相。
- 修正文本评分，避免中文小字图出现 `text_clarity_score=0` 的失真结果。
- 增加 V0.4.6 诊断字段：`v046_text_engine_active`、`v046_quality_profile`、`before_text_region_density`、`after_text_region_density`、`text_region_density_delta`。
- 新增 `tests/diagnostics/test_v046_quality_pipeline.py`。
- 通过 V0.4.6 核心诊断与 V0.4.5.3 API/SSE 回归。

### 验证结果

- `tests/diagnostics/test_v046_quality_pipeline.py`：PASS。
- `tests/diagnostics/test_v0453_core_pipeline.py`：PASS。
- `tests/diagnostics/test_v0453_api_pipeline.py`：PASS。

### 未解决

- 普通 PNG 与中文小字图仍未完全通过 1080P 质量守门。
- 多个低分辨率小样本输出体积比例仍偏高。
- 编号核心文档仍不完整。
