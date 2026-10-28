# 影界 HDDE｜V0.5.7 D线颜色校正功能开发报告

- 报告日期：2026-09-01
- 产品版本：`V0.5.7-dev`
- 仓库分支：`codex/image-processing-routing-v1`
- 仓库 HEAD：`aa0dd93265d270eb5192ebbd44a1fe14488d454a`
- 报告范围：D线商业颜色恢复合同、正式V2颜色链、D57-COLOR-00至D57-COLOR-04、当前验证证据及后续阻断
- 报告性质：开发现状与能力边界收口；只冻结D57-COLOR-04使用范围，不是产品发布声明或商业质量证明

## 1. 总结结论

V0.5.7颜色校正已经形成一套可运行、可审计、遇到风险能够保留原图或进入复核的正式工程底座；颜色管理、Alpha保护、人物区域绑定、候选独立审计和结果交付链已经达到较高的技术完整度。

但目标中的“商业图片颜色恢复工具”尚未完成。当前最准确的判断是：

```text
FORMAL_COLOR_RUNTIME: AVAILABLE
FORMAL_RUNTIME_ROUTE: D1 -> D2 -> D3
COLOR_CORE_V2: PROVEN_AND_FROZEN_WITHIN_HISTORICAL_15_SAMPLE_SCOPE
D57_COLOR_00: COMPLETE
D57_COLOR_01: COMPLETE
D57_COLOR_02: INCOMPLETE_INSUFFICIENT_CONTRACT_COMPLETE_REAL_EVIDENCE
D57_COLOR_03: TECHNICALLY_COMPLETE_AT_R11
D57_COLOR_04: RESEARCH_PROTOTYPE_WITH_UNCLOSED_EVIDENCE_GAPS
V3_WHITE_BALANCE_TECHNICAL_GATE: PASS_CONTROLLED_ENGINEERING_SCOPE
D57_COLOR_04_GO_NO_GO: NO_GO_INSUFFICIENT_REAL_EVIDENCE
FORMAL_V3_INTEGRATION: NO
COMMERCIAL_COLOR_RESTORATION_V1: NOT_PROVEN
RELEASE_FREEZE: NO
```

工程安全门禁通过，不等于真实图片效果达到商业可交付。当前已有11条真实来源记录，但仍缺至少19组合同合格来源、完整Ground Truth、数据使用权证明和人工盲评证据。

## 2. 产品目标与边界

V0.5.7 D线的目标不是“自动把颜色调漂亮”，而是把仍保留可恢复信息的图片恢复到可靠、自然、可交付状态：

- 白色、灰色和黑色关系恢复可信；
- 可恢复的曝光层次得到改善，不补造已经丢失的信息；
- 人物肤色自然，不蜡黄、不泛红、不灰白；
- 产品色、品牌色、Logo、文字、结构和材质不被破坏；
- 证据不足时保留原图或要求人工复核；
- 只有通过非补偿式硬门禁的候选才允许进入交付。

明确不开发为滤镜、风格化调色、美颜、HDR幻想、内容生成、产品重新着色或通用RAW开发器。V1正式输入范围保持为单帧8-bit RGB/RGBA JPEG和PNG；16-bit PNG、非sRGB宽色域、CMYK、多帧和颜色元数据冲突继续安全阻断。

## 3. 当前真实运行架构

当前用户路径使用正式D1→D2→D3链，而不是V3白平衡原型：

```text
颜色校正页面
  -> /api/color-correction/run 或 /batches
  -> run_formal_color_runtime
  -> 颜色管理边界
  -> D1 可恢复性、风险和处理授权
  -> D2 有界颜色/曝光候选
  -> D3 独立重放、非补偿式安全审核和唯一接受裁决
  -> ACCEPT_CORRECTED / ACCEPT_ORIGINAL / REVIEW_REQUIRED
  -> Task / Result / Delivery / 输出中心

V3白平衡v0.9
  -> 隔离工程原型
  -> ISOLATED_REVIEW_ONLY
  -> 不导出到正式包，不进入API、页面或正式结果链
```

关键事实：

- 当前正式API在`backend/image_compression_api.py`中调用`run_formal_color_runtime()`。
- D2复用Color Core V2的受控全局映射能力，但D3拥有唯一接受权限。
- D2生成候选不代表候选可交付；D3必须独立重建来源证据和候选结果。
- `engine/color_correction/core.py::process_single_image()`仍保留给历史引擎与评估代码使用，但不是当前颜色API的正式调用入口。后续开发必须避免只修改该历史入口而误以为已经改变正式产品行为。
- 正式默认输出目录为`D:\影界文件\输出\颜色校正`；用户可通过受控设置或当前任务选择正式根目录，功能目录为`<有效正式根>\输出\颜色校正`。目录不可用时明确阻断，不回退仓库或临时目录。

## 4. 阶段完成情况

| 阶段 | 唯一职责 | 当前状态 | 已完成内容 | 未完成边界 |
| --- | --- | --- | --- | --- |
| D57-COLOR-00 | 冻结产品技术合同 | `COMPLETE` | 冻结商业恢复目标、GT等级、P0/P1门禁、240张证据结构和八阶段职责 | 不代表功能已经实现 |
| D57-COLOR-01 | 修复质量指标归因 | `COMPLETE` | 分离颜色、曝光、曝光增量和组合流程归因；10项指标门禁通过 | 只对受控指标有效，不证明颜色执行器能力 |
| D57-COLOR-02 | 建立30张开发集和Ground Truth | `INCOMPLETE_INSUFFICIENT_CONTRACT_COMPLETE_REAL_EVIDENCE` | 合同和证据要求已定义；现有Manifest含11条真实来源记录 | 尚缺至少19组合格来源；现有记录无GT字段和权利字段，未形成合同完整开发集 |
| D57-COLOR-03 | 建立颜色管理、位深和Alpha基础 | `TECHNICALLY_COMPLETE` | sRGB颜色管理、ICC验证、Alpha、人物区域坐标与实例绑定、独立审计重放闭环至R11 | 商业阈值仍未冻结；16-bit和宽色域仍阻断 |
| D57-COLOR-04 | 隔离开发V3并完成30张GO/NO-GO | `RESEARCH_PROTOTYPE_WITH_UNCLOSED_EVIDENCE_GAPS` | 已完成V3白平衡v0.9受控工程安全合同与能力边界收口 | 30张GO/NO-GO为NO-GO；自动保护、商业阈值、独立Artifact Validator、GT和权利证据未成立 |
| D57-COLOR-05 | 冻结240张黄金集 | `NOT_STARTED` | 无 | 依赖D57-COLOR-02和D57-COLOR-04 |
| D57-COLOR-06 | 形成商业质量结论 | `NOT_STARTED` | 无 | 依赖冻结V3、90张验证集和120张盲测 |
| D57-COLOR-07 | 正式集成与版本收口 | `NOT_STARTED` | 无 | 当前明确未授权正式V3集成 |

按阶段计数，三个阶段完成、D57-COLOR-04以隔离研究原型身份完成能力范围收口、一个阶段被真实材料阻断、三个阶段尚未开始。阶段数量不能直接换算为商业完成百分比，因为D57-COLOR-02、05和06承担主要的真实效果证明责任。

## 5. 已完成的核心工程能力

### 5.1 正式产品闭环

- 已有正式颜色校正页面，支持单图和最多20张本地顺序批处理。
- 支持上传、处理、前后对比、结果复核、打开结果、打开目录和本地问题反馈。
- 复用统一Task、Result、Delivery和运行日志，不建立平行结果系统。
- 原图在处理前后进行SHA-256保护；候选文件必须存在、可解码、尺寸、格式、扩展名和摘要一致。
- D3未选择候选时，正式输出路径不得出现修改文件。
- `REVIEW_REQUIRED`不能被映射为正式校正输出，`ACCEPT_CORRECTED`必须绑定真实且已验证的候选。

### 5.2 颜色管理与文件真实性

- 单帧8-bit RGB/RGBA JPEG、PNG进入统一sRGB工作域。
- 有效sRGB ICC通过Pillow ImageCms/LittleCMS语义验证，而不是依赖Profile名称。
- 无ICC输入只有在PNG和EXIF颜色元数据不冲突时才明确按sRGB解释。
- JPEG和PNG输出写入与像素匹配的sRGB ICC。
- 损坏ICC、伪装sRGB的异常Profile、元数据冲突、CMYK、多帧、16-bit和未验证宽色域均安全阻断。
- PNG Alpha逐像素保持；完全透明像素的隐藏RGB不允许被悄然改变。

### 5.3 D1、D2、D3安全链

- D1负责可恢复性、颜色/曝光事实、人物/产品风险和处理授权，不修改像素。
- D2只生成有界颜色或曝光候选，颜色与曝光执行路径分离。
- D3不信任候选自身，也不接受调用方提供的“正确结果”；它从源图和受限参数独立重建结果。
- 人物区域已经统一为源图坐标、D1分析域单次映射、三态来源合同和进程内实例级HMAC封印。
- 候选身份绑定源图指纹、D1上下文和执行参数；损坏、替换、移植或结构仿冒均在像素执行前安全阻断。
- 透明边缘按联合RGB向量、Alpha合成连续性、局部来源支持和候选独立重放进行审核，单一平均值不能补偿局部硬失败。

### 5.4 V3白平衡v0.9隔离原型

- 在线性sRGB中估计有界全局增益，最大增益、最小增益和处理强度均受限。
- 需要空间分散的中性色证据；证据不足、偏色不显著、改善不足、亮度漂移或新增裁剪时保留原图。
- RGB图像使用未保护源像素估计光源；RGBA图像只有未保护且`Alpha=255`的源像素具有全局光源授权权。
- 半透明像素可以在Alpha结果门禁通过后接受变换，但不能决定全局白平衡。
- 实际候选必须与独立float64来源重放逐字节一致；同步篡改不能通过。
- 半透明区域必须拥有至少4个可信不透明源像素，并在最长12像素的来源支持范围内；无支持区域安全阻断。
- 所有成功候选仍为`ISOLATED_REVIEW_ONLY`，不能自动交付。
- 合法颜色管理解码结果被复制为私有、连续、只读的处理快照，并绑定解码像素、处理快照和证据摘要；快照后的来源对象替换或并发修改不能改变本次处理结果。
- 当前只证明调用方提供的正确硬Mask可保持受保护像素；未实现或证明自动文字、Logo、肤色和品牌色完整覆盖。

## 6. 审核修复形成的关键经验

D57-COLOR-03和V3白平衡经历了多轮自动审核撤销。撤销本身不是商业进展，但暴露并关闭了以下高风险授权缺陷：

- 全局最大值、分通道分位数或平均指标可能掩盖局部透明边缘污染。
- 候选像素、执行器轨迹和候选派生参考不能为自己提供接受权限。
- 同一Alpha连通域不等于同一物体，远端不透明像素不能被借作局部颜色真值。
- D1、D2、D3必须使用一致的可见Alpha域和同一人物区域来源。
- 人物区域摘要只认证内容仍可能被整体移植，必须绑定到签发的具体D1实例。
- 独立重放只能证明算法执行一致；如果光源证据域本身没有授权资格，重放一致仍然不安全。
- 半透明像素按未加权数量参与光源估计，会让几乎不可见的像素拥有过大的全局改色权限。

最终形成的稳定原则是：来源事实、授权证据、候选执行、结果审核和商业效果证明必须相互分离。

## 7. 当前验证证据

### 7.1 当前最新技术审核证据

| 验证 | 结果 | 能证明什么 | 不能证明什么 |
| --- | --- | --- | --- |
| V3白平衡受控测试 | 25/25 PASS | 原子快照、Provenance、Alpha、硬Mask和候选证据合同通过 | 不能证明自动保护覆盖或真实商业图片效果 |
| 颜色回归 | 116/116 PASS | 当前D1/D2/D3、颜色管理、指标和V3受控回归通过 | 不能证明商业泛化 |
| 正式颜色API测试 | 37/37 PASS | 正式颜色API、任务、结果、目录和错误链合同通过 | 未覆盖真实桌面浏览器视觉体验 |
| 线程并发探针 | 6/6 PASS | 快照后来源对象/像素交错变更不能绕过本次处理证据 | 不能替代生产压力测试 |
| 证据篡改探针 | 3/3 BLOCKED | 受测证据身份篡改按预期安全阻断 | 不是独立完整Artifact Validator |
| 正式导入扫描 | V3引用0处 | V3仍未进入正式包、API、页面和正式运行时 | 不代表V3具备商业效果 |

本次Capability Scope Closure没有修改运行代码；但终验期间检测到V3源码存在并行更新，为保证结论绑定最终稳定源码，实际重新执行并通过25/25 D57-COLOR-04专项、116/116 Color共享回归和37/37 Formal Color API测试。当前源码哈希与正式导入扫描同时用于核对证据适用边界。

### 7.2 指标与历史证据

- D57-COLOR-01受控指标集：5张参考、20个受控错误、40个候选、10个曝光控制、10项指标门禁。
- 当前结论为`METRIC_CONTRACT_STATUS=PASS`、`QUALITY_BASELINE_AUTHORITY=VALID_FOR_CONTROLLED_METRIC_USE`。
- 同一证据明确记录`COLOR_EXECUTOR_CAPABILITY=NOT_PROVEN`和`COMMERCIAL_COLOR_RESTORATION_V1=NOT_PROVEN`。
- Color Core V2历史评估含15条记录；当前状态文件登记后续人工复核为PASS并冻结V2。原始评估JSON仍保留生成当时的`human_final_review=PENDING`，属于时间先后的记录差异，不能把旧JSON单独当作最终冻结权威。

### 7.3 V3白平衡当前源码与真实记录边界

当前V3源文件、颜色管理和直接测试SHA-256为：

```text
V3_WHITE_BALANCE=9F45675E7E398810185B6217A5E320D411DFBE6C516D31C520506F6F4532A9FF
COLOR_MANAGEMENT=07C73D8B774432A649B2123B560E3C479A3A908D1670F26E6BCF55CF635BD4E9
V3_DIRECT_TESTS=E296256847306072D592FE8550A3CF5EDA62FB028CA34CF9AD0EECEF5FF5D651
```

当前v0.9技术审核验证了：

- Alpha为3、16、128、254的半透明像素不能授权光源估计；
- 大幅改变全部半透明RGB不会影响不透明区域的全局白平衡结果；
- 半透明区域同步篡改触发`PARTIAL_ALPHA_INDEPENDENT_REPLAY_MISMATCH`；
- 超过12跳借用远端不透明参考触发`PARTIAL_ALPHA_SOURCE_SUPPORT_NOT_EVALUABLE`。

因此V3白平衡v0.9的工程安全门禁可以判定为通过，但证据范围仍严格限定为受控工程夹具。

最新可见真实运行Manifest包含11条真实来源记录，其中9条标记`REAL_CONFIRMED`、2条标记`REAL_BUT_SOURCE_LIMITED`，但没有GT字段和权利字段，11条记录均无可用候选。该Manifest绑定V3 v0.7及旧源码摘要，与当前v0.9源码摘要不一致，故只能作为历史真实来源执行记录，不能证明当前原型的真实效果、商业泛化或商业GO。

## 8. 当前能力成熟度

| 能力维度 | 当前判断 | 说明 |
| --- | --- | --- |
| 产品目标与边界 | 已冻结 | 商业颜色恢复而非AI调色 |
| 正式V2单图/批量闭环 | 可运行 | 当前用户功能由V2/D1-D3承担 |
| 颜色管理与Alpha基础 | 技术完成 | 支持范围内通过，范围外安全阻断 |
| 候选与结果安全审核 | 技术完成 | 已形成来源独立、非补偿式审核 |
| V3白平衡 | 隔离研究原型，证据缺口未关闭 | 工程安全核心通过；仅受控夹具，未进入正式链 |
| 调用方硬Mask保护 | 受控夹具证明 | 不等于自动识别文字、Logo、肤色或品牌色 |
| 独立Artifact Validator | 未建立 | 当前禁止自动证据晋级和生产采用，因此是已知研究限制 |
| 阈值来源 | 固定工程常量 | 仅限研究，不是商业校准阈值 |
| V3曝光恢复 | 未形成商业证据 | 现有V2曝光能力不能替代V3证据 |
| V3肤色恢复 | 未形成商业证据 | 人物保护基础已完成，商业自然度未证明 |
| V3产品/品牌色保护 | 未形成商业证据 | 缺GT-B和真实产品区域，阈值不能冻结 |
| 30张开发集GO/NO-GO | `NO_GO_INSUFFICIENT_REAL_EVIDENCE` | 仅有11条非合同完整来源记录，GT和权利证据为0 |
| 240张黄金集与盲测 | 未开始 | 90张验证和120张盲测尚未建设 |
| V3正式集成 | 未授权 | 当前正式链保持V2 |
| 商业直接使用能力 | 未证明 | 不能宣称处理后无需PS/LR二次调整 |

## 9. 主要问题与风险

### P0：真实商业证据不足且不完整

D57-COLOR-02要求30组合同完整的真实来源图、Ground Truth和权利材料。当前只有11条真实来源记录，GT和权利字段均为0，且记录绑定旧版v0.7源码；因此真实商业证据仍不成立。程序生成的色块、渐变、Alpha和异常Profile只能验证工程规则，不能用于白平衡、曝光、肤色或品牌色的商业结论。

### P0：V3能力不完整

V3当前只完成白平衡隔离原型。目标要求的曝光恢复、肤色恢复、产品/品牌色保护及其联合冲突裁决，尚未获得同级V3实现与证据。

### P0：没有正式GO/NO-GO和盲测

30张开发集未成立，后续90张独立验证和120张盲测未开始。直接使用率、Wilson 95%置信区间、分路线充分性和高风险P0零错误均无法计算。

### 已知研究限制：自动保护、Artifact Validator和阈值校准

当前只有调用方硬Mask保护的受控夹具证据；自动文字、Logo、肤色、品牌色保护未证明。代码存在单条V3 evidence record内容绑定校验，但没有独立正式Artifact包验证器；固定工程阈值也未用合法真实数据完成商业校准。由于原型禁止生产采用、商业GO和无人值守证据晋级，这些缺口不构成正式链安全缺陷，但阻止D57-COLOR-04升级为完整可信原型或商业能力。

### P2：双入口认知风险

历史`core.py::process_single_image()`和当前正式`formal_runtime.py::run_formal_color_runtime()`同时存在。当前API只调用后者。后续任务必须明确目标入口，避免算法只在历史评估链生效、正式产品行为却没有变化。

## 10. 商业研发重新开放门禁

D57商业颜色恢复研发当前关闭。只有以下九项全部满足才允许重新打开：

1. 至少30组合同要求的真实Source样本；
2. 每组来源合法、可追踪；
3. 研究、验证及预期商业使用权明确；
4. GT-A/GT-B/GT-C或合格GT-D/可靠Reference成立；
5. 白平衡、曝光、人物、产品/品牌、混合光、正常暖冷光和无需处理控制样本达到合同覆盖；
6. 自动Protected Region能力达到未来正式要求；
7. 商业阈值在合法数据上预先校准并冻结；
8. 必要的独立Artifact Validator建立；
9. 独立审核通过。

在门禁未满足前，D57-COLOR-04只允许开发/实验环境研究，不得生产采用、自动交付、商业GO或证据自动晋级。下一产品级任务是`V0.5.7_CAPABILITY_SCOPE_CLOSURE`，不是继续扩展D57算法。

## 11. 最终判断

V0.5.7颜色校正不是“没有开发”，也不是“已经完成”。准确状态是：

- 正式V2颜色校正产品闭环已经存在并保持可运行；
- V0.5.7商业颜色恢复的合同、指标和底层安全基础已经建立；
- V3白平衡v0.9完成了受控工程范围的技术安全闭环，并以`RESEARCH_PROTOTYPE_WITH_UNCLOSED_EVIDENCE_GAPS`冻结身份；
- 真实商业效果、完整V3能力、30张GO/NO-GO、240张黄金集、正式集成和版本冻结均未完成；
- 当前最关键的成功条件是取得真实、合法、可建立Ground Truth的图片材料，而不是继续增加无数据支撑的算法版本。

```text
REPORT_CONCLUSION: ENGINEERING_FOUNDATION_SUBSTANTIAL_COMMERCIAL_CAPABILITY_NOT_PROVEN
FORMAL_COLOR_CAPABILITY: COLOR_CORE_V2_PASS_AND_FROZEN
EXPERIMENTAL_COLOR_CAPABILITY: D57_COLOR_04_RESEARCH_PROTOTYPE_WITH_UNCLOSED_EVIDENCE_GAPS
UNPROVEN_COLOR_CAPABILITY: COMMERCIAL_COLOR_RESTORATION_V1
D57_04_BLOCKS_V0_5_7_RELEASE: NO_RESEARCH_PROTOTYPE_ISOLATED
NEXT_REQUIRED_STAGE: V0.5.7_CAPABILITY_SCOPE_CLOSURE
FORMAL_V3_INTEGRATION_ALLOWED: NO
D57_COMMERCIAL_COLOR_RESTORATION_RELEASE_ALLOWED: NO
```
