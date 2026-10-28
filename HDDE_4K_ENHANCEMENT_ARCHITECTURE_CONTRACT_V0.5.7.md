# 影界 HDDE｜4K画质增强 V0.5.7

# HDDE 4K Enhancement Architecture Contract V1.0

## 0. 合同身份

```text
CONTRACT_ID=HDDE_4K_ENHANCEMENT_ARCHITECTURE_CONTRACT_V0.5.7
VERSION=V0.5.7
LINE=E
STAGE=E-ARCH
CONTRACT_STATUS=FROZEN
FREEZE_DATE=2026-08-21
BASE_BRANCH=codex/image-processing-routing-v1
BASE_HEAD=aa0dd93265d270eb5192ebbd44a1fe14488d454a
VERSION_METADATA_MISMATCH=YES_PRODUCT_VERSION_JSON_IS_V0.5.6_DEV
CURRENT_FORMAL_4K=PILLOW_LANCZOS_HIGH_QUALITY_SIZE_ADAPTATION
REAL_QUALITY_GAIN=NOT_PROVEN
```

本合同是 V0.5.7 E线正式开发前的架构与证据边界。仓库版本元数据仍显示 `V0.5.6-dev`，本轮只记录 `VERSION_METADATA_MISMATCH`，不修改版本文件，也不降低本合同的 V0.5.7 身份。

### 0.1 事实标签

- **FACT**：当前代码、测试或现有产物能够直接证明。
- **INFERENCE**：结构或命名支持，但没有运行时或因果证据。
- **DECISION**：V0.5.7 从本合同起冻结的架构选择。
- **NEED_PROOF**：实现或阈值尚无充分证据，不得当作已成立能力。
- **DEFERRED**：明确不属于 V0.5.7 当前核心范围。

**DECISION**：本合同中的职责清单、字段约束、Gate 规则、状态机、开发阶段和范围清单均属于 `DECISION`；表格中已经显式标为 `FACT`、`INFERENCE`、`NEED_PROOF` 或 `DEFERRED` 的单元格除外。该继承规则只补齐标签，不改变任何既有架构结论。

### 0.2 非目标

- **DECISION**：本合同不实现增强算法、不接入模型、不修改正式 4K 链、不修改 API/UI/测试或版本元数据。
- **DECISION**：V0.5.7 的核心目标不是复制竞品能力，而是第一次证明 HDDE Candidate 相对 Pillow LANCZOS Baseline 具有安全、可重复、可审计的真实质量净增益。
- **DECISION**：在晋级门禁完成前，所有 Candidate 均为实验资产，不得写入正式输出目录，不得冒充正式 4K 能力。

---

## 1. 当前证据与能力分层

### 1.1 FORMAL_PRODUCTION

| 能力 | 当前事实 | 正式结论 |
|---|---|---|
| `four_k_v1.py` | 长边 3840、保持比例、Pillow LANCZOS、PNG、ICC、预乘 Alpha resize、输出尺寸与原图 SHA256 验证 | **FACT：正式生产能力** |
| `/api/upload` 4K 合同 | `mode=4k_v1`、`output_profile=delivery_4k_v1`、`output_format=png`，拒绝自定义 scale 和输出目录 | **FACT：正式生产能力** |
| 正式目录 | 输出固定在正式根目录下的 `输出/4K高清增强` | **FACT：正式生产能力** |
| `NO_PROCESSING_NEEDED` | 原图长边已经达到 3840 时不生成伪输出 | **FACT：正式生产能力** |
| Task → Result → Delivery → Feedback | 当前 4K 任务复用统一任务、结果、对比、报告和反馈载体 | **FACT：正式生产能力** |
| 质量边界 | `HIGH_QUALITY_SIZE_ADAPTATION_ONLY` | **FACT：不是 AI 超分、细节重建或已证明画质增益** |

### 1.2 EXPERIMENTAL_PROVEN

| 能力 | 已证明范围 | 不得扩张的结论 |
|---|---|---|
| HD Core Safe Base | 两个现有 validation 批次各 6/6 样本通过；含 Alpha 与精确 fallback probe | 只证明 `INTERNAL_SAFE_BASE_ONLY_NOT_HD_CORE_V1` |
| 隔离 workspace | 拒绝正式根目录和原图目录，Candidate 产物进入隔离路径 | 不等于正式数据链已经接入 |
| Candidate 注入骨架 | 支持无 Candidate、恒等 Candidate、异常、缺失输出、像素风险与 fallback 测试 | 没有正式 Candidate 注册，没有真实增强证明 |
| fail-closed fallback | Candidate 缺证据或失败时选择像素等价 Baseline | 当前门禁几乎拒绝所有 RGB 变化，不能用于判断真实增强收益 |
| Source Alpha bypass | 现有透明样本记录 Alpha 差异像素为 0，黑白底合成差异为 0 | 不代表所有透明素材分布已经覆盖 |

### 1.3 EXISTING_REUSABLE

| 模块 | 可复用事实 | 当前限制 |
|---|---|---|
| `profile.py` | 格式、尺寸、方向、文件大小、Alpha、动画/多帧、长图等客观画像 | 不是语义内容识别器 |
| `safe_base.diagnose_degradation` | 梯度、Laplacian、编码格式等测量 | 明确 `semantic_detection_performed=False`；不能直接诊断模糊、噪声或压缩原因 |
| `low_quality_fidelity.py` | 压缩、模糊、低频、颜色漂移、文字/平坦区域等代理指标与保守回退机制 | 主要服务既有通用/1080P链；阈值未按 4K Candidate 校准 |
| `image_type_detector.py` | 文字、线条、肤色、灰度等启发式分类 | 不是可靠人脸、Logo、产品或内容识别 |
| `text_clarity.py` | 检测密集笔画状区域并形成局部 mask | 不使用 OCR，不能证明字形或文字语义正确 |
| `fidelity_enhancement.py` | 修复、结构、边缘、文字、颜色锁定的现有组合 | 未接正式 4K；效果和安全性未在 E1-02 证明 |
| `quality_compare.py` / `quality_metrics.py` | 清晰度、文字、边缘、结构、纹理、噪声、色彩等代理分数 | Laplacian/高频分数不能单独证明真实质量收益 |
| E1-01 | 8 样本、16 案例、8 个 GT 案例、固定 ROI、退化族、manifest 与 validation | 16/16 Candidate 为空；所有质量与风险结论均未评估 |

### 1.4 UNPROVEN

- **FACT**：`REAL_4K_QUALITY_GAIN=NOT_PROVEN`。
- **FACT**：Stage 2 既有关闭报告为 `AI_SAFE_GAIN_STATUS: NOT_PROVEN`、`CURRENT_ROUTE_B_PRODUCT_ADOPTION: NO`。
- **FACT**：当前 HD Core 的 `new_halo_possible` 由“任意 RGB 变化”触发，是 fail-closed 代理，不是已校准的 Halo 检测器。
- **FACT**：当前没有正式 4K 人脸身份保护、Logo 完整性评价、中文字符级保真评价或材质真实性评价。
- **FACT**：当前没有已晋级的 Enhancement Candidate。
- **FACT**：当前没有已证明的自动 Candidate 路由。
- **DECISION**：`EXISTS != FORMAL_4K_CAPABILITY`。

---

## 2. 目标架构总图

```text
ORIGINAL SOURCE
    │
    ├── Source Contract / Target Plan / Immutable Hash
    │
    ├── Analysis Facts ────────────────┐
    │                                  │
    ├── Safe Baseline Executor         │
    │     └── LANCZOS_BASELINE         │
    │                                  │
    ├── Candidate Runtime              │
    │     ├── Candidate_A              │
    │     ├── Candidate_B              │
    │     └── Future_Candidate         │
    │                                  │
    └──────────────────────────────────┘
                       │
                       ▼
              Per-Candidate Safety Gate
                       │
              PASS / REVIEW / FAIL
                       │
                       ▼
             Baseline-relative Quality Gate
                       │
       QUALITY_GAIN_PROVEN / QUALITY_GAIN_NOT_PROVEN
                       │
                       ▼
              Experimental Selection Decision
                       │
       Candidate / Review-only / Exact Baseline Fallback
                       │
                       ▼
             Production Adoption Gate
                       │
          Only adopted version may enter formal 4K
```

### 2.1 冻结原则

1. **DECISION：BASELINE != ENHANCEMENT。**
2. **DECISION：Baseline 与每个 Candidate 从同一原图和同一 Target Plan 独立运行。** Candidate 不得默认以上采样后的 Baseline 作为增强输入。
3. **DECISION：Baseline 是对照、最低交付结果和精确 fallback，不是 Candidate 的成功证明。**
4. **DECISION：Candidate 生成成功只代表执行成功，不代表安全、质量收益或生产资格。**
5. **DECISION：Safety、Quality Gain、Selection、Production Adoption 是四个不同状态，不得合并为一个 `PASS`。**
6. **DECISION：所有实验路径先隔离，只有通过 Production Adoption Gate 的冻结 Candidate 版本才能进入正式链。**
7. **DECISION：所有不可确认的语义风险必须是 `REVIEW` 或 `NEED_PROOF`，不得用默认 False 伪造成 PASS。**

---

## 3. A｜SAFE BASELINE LAYER

### 3.1 LANCZOS 的永久角色

- **DECISION**：Pillow LANCZOS 永久保留为 4K Safe Baseline。
- **DECISION**：它承担四个角色：固定对照、最低安全输出、Candidate fallback、回归锚点。
- **DECISION**：它的成功结论仍是 `SIZE_ADAPTATION_COMPLETED`，不能升级为 `QUALITY_GAIN_PROVEN`。
- **DECISION**：任何 Candidate 被拒绝、证据缺失、执行异常、输出缺失、解码失败、Alpha/几何/结构门禁失败时，必须选择同一任务生成的 Baseline，而不是旧文件、原图伪结果或临时 fallback。
- **DECISION**：`SOURCE_LONG_EDGE >= 3840` 时保持现有 `NO_PROCESSING_NEEDED`，直接绕过 Candidate Framework；不生成 Baseline artifact，不生成 Candidate，fallback 不适用。

```text
NO_PROCESSING_NEEDED_CANDIDATE_POLICY=BYPASS
NO_PROCESSING_NEEDED_BASELINE_ARTIFACT=NONE
NO_PROCESSING_NEEDED_FALLBACK=NOT_APPLICABLE
```

### 3.2 `four_k_v1.py` 继续负责

- 原图读取事实与 SHA256。
- EXIF 方向规范化。
- 3840 长边与保持比例 Target Plan。
- Pillow LANCZOS Baseline executor。
- RGB/RGBA、预乘 Alpha、ICC 与 PNG Baseline 编码。
- Baseline 输出解码、尺寸与原图哈希验证。
- `NO_PROCESSING_NEEDED`。
- Baseline 合同常量和禁止夸大的质量语义。

### 3.3 不得继续塞入 `four_k_v1.py`

- Candidate 注册、模型加载和 backend 选择。
- 退化语义分类与自动路由。
- Candidate 参数搜索。
- 多 Candidate 并行编排。
- Safety/Quality 聚合裁决。
- 人工复核状态。
- Candidate 晋级和版本治理。
- Topaz 模型名、私有格式或竞品兼容逻辑。

### 3.4 Baseline 不可变合同

```text
baseline_id
source_sha256
target_plan_id
executor_identity=PILLOW_LANCZOS_SAFE_RESIZE
executor_version
parameters
output_reference
output_sha256
output_pixel_sha256
output_width
output_height
output_format=PNG
alpha_contract
icc_contract
runtime_facts
status
```

- **DECISION**：同一 Benchmark 中 Baseline 一经生成并验证，不得在 Candidate 评估过程中被重算或覆盖；需要重算时必须创建新 batch，并保留旧证据。

---

## 4. B｜IMAGE / DEGRADATION ANALYSIS

### 4.1 可靠事实与代理指标

| 分析项 | 当前等级 | V0.5.7用途 |
|---|---|---|
| 解码、格式、尺寸、方向、Alpha、帧数、文件大小 | **FACT / 可靠** | 硬合同与阻断条件 |
| 原图 SHA、Target Plan、输出尺寸 | **FACT / 可靠** | 可追溯和几何一致性 |
| JPEG/WebP 等有损编码存在 | **FACT / 有限可靠** | 分层统计；不能证明当前可见压缩严重度 |
| 水平/垂直梯度、Laplacian、局部对比度 | **代理指标** | Benchmark 分层、质量/风险特征，不单独路由 |
| compression/blur/noise risk | **代理指标** | 必须经 E1-02/扩展集校准后才能参与候选建议 |
| text-like mask | **代理指标** | ROI 提示与局部保护辅助；不能证明真实文字范围或字符正确 |
| skin/portrait score | **弱代理** | 只可触发保守 REVIEW/回退；不能作为人脸身份判断 |
| image type | **启发式** | 样本分层；不得单独选择高风险 Candidate |
| Logo、产品、建筑、人脸身份识别 | **缺失/未证明** | V0.5.7 先由固定 ROI 和人工 100% 复核兜底 |

### 4.2 可参与 Candidate 选择的前提

- **DECISION**：只有在冻结数据集上完成校准、记录错误类型、置信度与 UNKNOWN 行为的指标，才能作为 Candidate 建议信号。
- **DECISION**：即使完成校准，退化/内容分析也只能生成 `degradation_context` 和候选建议；最终仍由 Safety 与 Quality Gate 决定。
- **NEED_PROOF**：压缩、模糊、噪声、低对比度和局部纹理代理指标的有效阈值。
- **NEED_PROOF**：启发式 image type 对商业素材的混淆矩阵和置信度校准。
- **NEED_PROOF**：文字、Logo、人脸、产品、建筑等语义区域的可靠检测方案。

### 4.3 V0.5.7 是否需要复杂自动路由

- **DECISION**：不需要，也不允许先建设复杂自动路由。
- **DECISION**：V0.5.7 首先采用 `LANCZOS_BASELINE + 一个显式实验 Candidate` 的固定比较结构。
- **DECISION**：实验 Candidate 由 Benchmark manifest 显式指定，不由启发式自动选择。
- **DEFERRED**：多 Candidate 自动路由、阈值路由、设备自适应路由和失败优先级路由。
- **理由**：当前没有任何 Candidate 的真实质量净增益证据，也没有可靠路由标签；先建路由只会放大错误选择并增加无法验证的状态空间。

---

## 5. C｜ENHANCEMENT CANDIDATE LAYER

### 5.1 Candidate 独立性

- **DECISION**：每个 Candidate 必须从不可变原图引用和同一 Target Plan 独立运行。
- **DECISION**：Baseline 与 Candidate 输出必须位于同一隔离 batch，但使用不同、不可覆盖的路径。
- **DECISION**：Candidate 之间不得串联；Candidate_B 不得读取 Candidate_A 输出。
- **DECISION**：Candidate 可以读取只读的 `degradation_context` 与 Target Plan，但不得修改原图、Baseline、manifest 或其他 Candidate 证据。
- **DECISION**：每个 Candidate 独立记录执行、参数、风险、质量、拒绝原因与运行环境。

### 5.2 Candidate 最小合同

```text
candidate_contract_version
candidate_id
candidate_version
algorithm_identity
input_reference
baseline_reference
target_plan
parameters
degradation_context
runtime_facts
output_reference
risk_facts
quality_facts
status
```

字段约束：

| 字段 | 冻结要求 |
|---|---|
| `candidate_id/version` | 唯一标识算法与冻结版本，禁止同名覆盖 |
| `algorithm_identity` | 实现名称、代码/资产身份、依赖版本与合法来源；不得使用竞品权重 |
| `input_reference` | 原图引用、SHA256、尺寸、格式、Alpha/ICC；Candidate 从这里运行 |
| `baseline_reference` | 同一 source/target plan 的 Baseline 引用与哈希，只用于比较和 fallback |
| `target_plan` | 输出宽高、比例、方向、格式、Alpha/ICC 合同 |
| `parameters` | 完整、确定、可序列化；默认值也必须记录 |
| `degradation_context` | 分析事实、代理指标、置信度、UNKNOWN 与生成版本 |
| `runtime_facts` | backend、device、库版本、开始/结束时间、耗时、内存、异常、确定性事实 |
| `output_reference` | 输出路径、文件 SHA、像素 SHA、尺寸、格式、解码状态 |
| `risk_facts` | 每项 Safety Gate 的值、状态、证据路径与拒绝码 |
| `quality_facts` | Baseline-relative、GT/ROI、自动指标与人工复核事实 |
| `status` | 至少拆分 execution、safety、quality_gain、selection、adoption 五个状态域 |

推荐状态域：

```text
execution_status=NOT_RUN|RUNNING|SUCCEEDED|FAILED
safety_status=NOT_ASSESSED|PASS|REVIEW|FAIL
quality_gain_status=NOT_ASSESSED|QUALITY_GAIN_PROVEN|QUALITY_GAIN_NOT_PROVEN
selection_decision=NOT_SELECTED|CANDIDATE|REVIEW_ONLY|BASELINE_FALLBACK
adoption_status=EXPERIMENT_ONLY|NEED_MORE_EVIDENCE|ELIGIBLE_FOR_ADOPTION_GATE|ADOPTED|REJECTED
```

### 5.3 现有 HD Core 的角色

- **DECISION**：HD Core 成为 V0.5.7 的实验 Candidate 与门禁骨架，但当前实现不能原样升级为正式生产链。
- **FACT**：可直接复用隔离 workspace、Candidate 注入、运行记录、异常捕获、风险调用和精确 fallback 思路。
- **FACT**：当前 Candidate 输入是 Safe Baseline 副本，这会把真实增强限制为“在已放大图上二次处理”。
- **DECISION**：未来 Candidate Runtime 必须改为 source-direct 输入，同时显式提供只读 Baseline reference。
- **DECISION**：HD Core 先保持实验层；只有 Candidate 通过 Production Adoption Gate 后，才允许建立正式 orchestration 入口。

### 5.4 `fidelity_enhancement` 的处置

- **DECISION**：降级为实验 Candidate 候选，不作为正式 4K 基础能力，也不直接复用到生产链。
- **DECISION**：如进入实验，必须通过适配器固定 BGR/RGB、位深、Alpha、ICC、Target Plan、参数与输出合同。
- **DECISION**：其 image type、文字、边缘、结构和颜色逻辑必须作为可审计参数记录，不能隐藏在一个笼统 `fidelity` 名称下。
- **NEED_PROOF**：该组合是否在任何 E1-02 分层上真实超过 Baseline。

### 5.5 `low_quality_fidelity` 的处置

- **DECISION**：承担分析代理、保护 mask 候选和低风险回退策略的实验来源，不直接承担正式自动路由。
- **DECISION**：其现有 policy 必须输出全部输入事实、阈值版本、触发原因和跳过原因。
- **NEED_PROOF**：各代理指标和阈值在 4K Candidate 上的有效性、误判率与内容分层表现。

---

## 6. D｜SAFETY GATE

### 6.1 总体规则

- **DECISION**：Safety Gate 是 Candidate 独立门禁；每个 Candidate 分别通过或拒绝。
- **DECISION**：硬合同失败直接 `FAIL + BASELINE_FALLBACK`。
- **DECISION**：语义风险证据缺失时为 `REVIEW`，不得默认为 PASS。
- **DECISION**：Safety PASS 只表示“没有达到拒绝条件”，不表示质量收益成立。
- **DECISION**：当前“任意 RGB 变化即失败”的门禁保留为 Baseline 等价性检查，不再作为未来 Candidate 的唯一安全判定。

### 6.2 Pixel / Alpha / Geometry 硬门禁

| 检查 | 状态规则 |
|---|---|
| 原图 SHA 未变化 | 不一致即 FAIL |
| Candidate 可解码 | 失败即 FAIL |
| 输出尺寸、比例、方向与 Target Plan 一致 | 不一致即 FAIL |
| 禁止未声明 crop/pad/stretch/rotate | 轨迹缺失为 REVIEW；确认发生为 FAIL |
| PNG/位深/色彩通道合同 | 不一致即 FAIL |
| Alpha 存在性与目标 Alpha 一致 | 丢失或新增即 FAIL |
| Alpha 像素差异 | 对 source-derived resize 合同应为 0；否则 FAIL |
| 透明边缘黑/白底合成 | 出现不可接受边缘污染即 FAIL；数值阈值 NEED_PROOF |
| NaN、Inf、越界、通道错位、BGR/RGB 错配 | 任一出现即 FAIL |

### 6.3 Edge Gate

必须覆盖：

- Halo 与亮边/暗边 overshoot、undershoot。
- Ringing 的重复振荡。
- 黑边、白边和双边。
- 局部过锐与边缘断裂。
- 文字笔画和 Logo 轮廓的宽度、连接和闭合变化。

- **DECISION**：Edge Gate 必须在锁定 ROI 和多尺度邻域上比较 Candidate、Baseline，并在有 GT 时同时比较 GT。
- **DECISION**：不能使用单一全图 Laplacian 或高频总量作为通过依据。
- **NEED_PROOF**：各内容类型的 overshoot、ringing、边缘连续性阈值。

### 6.4 Frequency Gate

- 高频增加必须能对应输入/GT 中可解释的真实结构。
- 平坦区、皮肤、天空、渐变和虚化背景中的新高频默认视为风险。
- 高频提升伴随噪声、规则重复纹理或方向性伪影时必须拒绝或 REVIEW。
- **DECISION**：`更多高频` 只是一项事实，不是收益结论。
- **NEED_PROOF**：分内容的频谱、噪声和纹理异常阈值。

### 6.5 Identity Gate

| 对象 | V0.5.7 门禁 |
|---|---|
| 中文文字 | 固定 ROI；字形、笔画、数字、标点、间距和可读性 100% 复核；自动 mask 仅辅助 |
| Logo | 固定 ROI；轮廓、负空间、字标和颜色结构 100% 复核 |
| 产品/包装 | 外轮廓、结构接缝、文字、材质边界、反射关系 100% 复核 |
| 建筑/工业结构 | 直线、平行关系、角点、重复构件与几何连续性复核 |
| 人脸身份 | 五官、轮廓、眼睛、皮肤、头发和身份一致性复核；缺证据不得 PASS |

- **DECISION**：人脸身份保护属于 V0.5.7 Production Adoption 的 MUST_HAVE。
- **DECISION**：如果首个 Candidate 明确不支持人像，人像样本必须证明能够稳定识别为不适用并精确 fallback；在可靠识别未证明前，不得依赖自动人像排除，必须保守 REVIEW/fallback。
- **NEED_PROOF**：自动中文、Logo、人脸和产品身份评价器。

### 6.6 Color Gate

- ICC 与颜色通道合同必须保持。
- 对 Candidate、Baseline 和原图/GT 记录 LAB 色差、明暗漂移、饱和度变化和局部颜色结构。
- 全局平均色差不能掩盖局部 Logo、肤色、产品色或高饱和区域损坏。
- **DECISION**：颜色指标必须同时提供全图与锁定 ROI 结果。
- **NEED_PROOF**：不同商业内容的颜色、亮度、饱和度安全阈值。

### 6.7 从“拒绝 RGB 变化”到“允许有证据收益”

禁止简单放宽 `maximum_rgb_delta`。

新判定必须同时满足：

1. Candidate 与 Baseline 的变化位置和性质被记录。
2. 变化位于预期受益区域，或能由 GT/原图结构支持。
3. 对应 ROI 的质量收益相对 Baseline 成立。
4. 保护区域和非目标区域没有破坏。
5. Alpha、几何、解码、格式和颜色硬合同通过。
6. Halo、ringing、假纹理和噪声没有新增不可接受风险。
7. 任何关键语义 UNKNOWN 均进入 REVIEW，不自动交付。

---

## 7. QUALITY / DELIVERY GATE

### 7.1 两组独立状态

```text
QUALITY_GAIN_PROVEN
QUALITY_GAIN_NOT_PROVEN
```

与：

```text
PASS
REVIEW
FAIL
```

分别表示：

- `PASS/REVIEW/FAIL`：安全与证据完整性状态。
- `QUALITY_GAIN_*`：Candidate 是否真实超过同任务 Baseline。

### 7.2 决策矩阵

| Safety | Quality Gain | 实验选择 | 正式含义 |
|---|---|---|---|
| FAIL | 任意 | `BASELINE_FALLBACK` | Candidate 拒绝 |
| REVIEW | 任意 | `REVIEW_ONLY` 或 Baseline | 不得自动交付 Candidate |
| PASS | NOT_PROVEN | `BASELINE_FALLBACK` | 安全但没有增益，不算增强成功 |
| PASS | PROVEN | `CANDIDATE` | 仅进入 Production Adoption Gate，不自动上线 |

### 7.3 真实质量净增益证据

Candidate 至少需要同时覆盖：

- 真实细节收益，而不是放大或锐化强度增加。
- 边缘连续性和几何结构。
- 中文字形、数字和 Logo 完整性。
- 主体、产品、建筑和人脸身份。
- 材质、反射、渐变、皮肤和虚化关系。
- 色彩稳定、局部明暗与饱和度。
- Halo、ringing、假纹理、噪声和 AI 感。
- 全图与 100% 原生像素 ROI 人工复核。

自动指标必须是多证据组合：

- 有 GT：Candidate 与 Baseline 分别对 GT 评价；只有 Candidate 对 GT 的距离改善才支持真实恢复。
- 无 GT：自动指标只提供风险和代理事实，必须结合盲化的 Baseline/Candidate 100% ROI 人工复核。
- 任何指标都必须记录 effect direction、幅度、适用 ROI、失败样本和 UNKNOWN。

### 7.4 如何证明“清晰了”不是假锐化

- **DECISION**：Laplacian、边缘数或高频量上升不能单独形成 `QUALITY_GAIN_PROVEN`。
- 必须证明新增响应与 GT 或原图可解释结构对齐，而不是在平坦区、轮廓两侧或噪声区扩散。
- 必须同时验证边缘连续性改善、GT 距离改善或人工可辨识细节改善。
- 必须没有新增 overshoot/undershoot、ringing、双边、噪声、假纹理或文字笔画变形。
- 必须在随机化/盲化的 100% crop 中优于 Baseline，而不是只在缩略图或选择性样本中更“锐”。
- **NEED_PROOF**：自动指标组合、阈值和人工判定一致性。

---

## 8. PRODUCTION ADOPTION GATE

### 8.1 晋级对象

- 晋级对象是冻结的 `candidate_id + candidate_version + algorithm_identity + parameters + runtime contract`，不是算法名称。
- 参数、模型/资产、实现或 backend 任一变化，都必须视为新 Candidate 版本重新验证。

### 8.2 必须满足的晋级条件

| 维度 | 门禁 |
|---|---|
| 样本量 | E1-02 首轮必须完整覆盖现有 16 案例；正式晋级最低扩展样本量为 **NEED_PROOF**，不得用 16 案例冒充广泛生产代表性 |
| 退化族 | 至少覆盖现有 REAL_INPUT_AS_IS、RESIZE、RESIZE_JPEG、BLUR_JPEG、MULTI_RESIZE、SCREENSHOT_LIKE；新增 Candidate 声称的适用退化必须有对应样本 |
| 内容 | 中文、Logo、产品/材质、人像、细节、压缩和已清晰控制组必须覆盖 |
| ROI | 每个高风险内容必须有锁定 ROI；不得在看到 Candidate 后选择 ROI |
| Alpha | 必须包含透明、半透明和复杂透明边缘；当前 S08 只是起点，扩展数量 **NEED_PROOF** |
| 安全失败 | 允许的“Candidate 被正确拒绝并 fallback”；不允许任何已知破坏性 Candidate 被选为交付结果 |
| fallback | 所有执行异常、输出缺失和 Gate FAIL 必须 100% 选择同任务 Baseline，且像素/哈希合同可验证 |
| 失败率 | Candidate 执行失败率与 REVIEW 比例的生产阈值为 **NEED_PROOF**；不能在无运行分布时造数 |
| 人工复核 | 所有高风险 ROI 必须 100% 原生尺寸复核；顺序盲化、评审人数和一致性阈值为 **NEED_PROOF** |
| 回归 | Baseline、Alpha、格式、目录、Task/Result/Delivery/Feedback、失败回退必须回归 |
| E2E | 必须在当前 HEAD 真实运行 `/api/upload → 4k_v1 → Task → SSE → Result → Delivery`，禁止只用 mock 或静态测试 |
| 可复现 | 固定 Candidate 版本、参数和环境下必须可重复；跨设备/backend 要分别证明 |

### 8.3 晋级流程

```text
EXPERIMENT_ONLY
    ↓ E1-02 complete
NEED_MORE_EVIDENCE / ELIGIBLE_FOR_ADOPTION_GATE
    ↓ expanded evidence + regression + human review
SHADOW_ADOPTION_CANDIDATE
    ↓ current-HEAD real E2E + exact fallback
ADOPTED_VERSION
    ↓ explicitly wired into formal 4K orchestration
FORMAL_PRODUCTION
```

- **DECISION**：任何阶段失败都保留 LANCZOS 正式链，不以沉没成本推动上线。
- **DECISION**：单张图效果好、测试脚本通过、输出生成成功或模型知名度均不能跨级晋级。

---

## 9. E1-01 → E1-02 合同

### 9.1 E1-01 的冻结角色

- **FACT**：E1-01 是数据、GT、退化、ROI 和对比合同基线。
- **FACT**：E1-01 不包含 Candidate 结果，不包含质量净增益结论。
- **DECISION**：E1-01 不覆盖、不重写；E1-02 只通过不可变引用复用。

### 9.2 E1-02 输入

```text
e1_01_manifest_reference
e1_01_manifest_sha256
candidate_contract
candidate_output_manifest
baseline_reference_per_case
review_protocol_version
metric_protocol_version
```

- Candidate 对每个案例必须提供输出或结构化失败记录。
- Candidate 与 Baseline 必须使用同一原图、同一方向、同一 Target Plan、同一输出尺寸和格式合同。
- 缺失 Candidate 输出不得丢弃样本；必须进入 failure/fallback 统计。

### 9.3 GT 与 ROI 关系

- 继续使用 E1-01 冻结的 normalized XYXY ROI，不得事后移动。
- GT 案例同时生成：
  - `GT_NATIVE_DOMAIN`：Candidate 与 Baseline 以同一确定性方法映射到 GT 原生域，再分别对 GT 比较。
  - `TARGET_NATIVE_100_PERCENT`：Candidate 与 Baseline 在 4K 输出原生像素域进行同 ROI 100% crop 比较。
- 无 GT 案例使用原图、Baseline、Candidate 的锁定 ROI，并进行盲化人工比较；自动指标不得单独产生 `QUALITY_GAIN_PROVEN`。

### 9.4 E1-02 自动事实

至少记录：

- 文件、像素、尺寸、方向、Alpha、ICC、解码与确定性。
- Baseline-relative RGB/颜色/频率/边缘变化。
- 有 GT 时的 Candidate-vs-GT 与 Baseline-vs-GT 差异。
- 全图与 ROI 的 Halo、ringing、边缘连续性、噪声、纹理和颜色代理事实。
- 所有指标实现版本、参数、适用域和 UNKNOWN。

### 9.5 E1-02 人工 100% 复核

每个锁定 ROI 必须记录：

```text
VISIBLE_GAIN
TEXT_FIDELITY
FACE_IDENTITY
LOGO_FIDELITY
STRUCTURE_FIDELITY
MATERIAL_FIDELITY
COLOR_FIDELITY
HALO
RINGING
FALSE_TEXTURE
AI_LOOK
REVIEW_STATUS
REVIEW_REASON
```

- Baseline/Candidate 展示顺序必须可随机化并记录。
- 不允许只展示成功样本或只看缩略图。
- 人工字段未填写时必须保持 `NOT_ASSESSED`，不得从自动分数补成 PASS。

### 9.6 收益、风险与拒绝字段

```text
case_safety_status
case_quality_gain_status
positive_evidence
risk_evidence
unknown_evidence
rejection_codes
fallback_required
review_required
selected_output
```

典型拒绝码：

```text
CANDIDATE_EXECUTION_FAILED
CANDIDATE_OUTPUT_MISSING
OUTPUT_CONTRACT_FAILED
ALPHA_CONTRACT_FAILED
GEOMETRY_TRACE_UNKNOWN
EDGE_ARTIFACT_DETECTED
FALSE_TEXTURE_RISK
TEXT_FIDELITY_FAILED
LOGO_FIDELITY_FAILED
FACE_IDENTITY_FAILED
PRODUCT_STRUCTURE_FAILED
COLOR_FIDELITY_FAILED
QUALITY_GAIN_NOT_PROVEN
HUMAN_REVIEW_REQUIRED
```

### 9.7 E1-02 最终判定

- `CANDIDATE_REJECTED`：任一不可接受安全失败，或关键类别出现结构/身份破坏。
- `NEED_MORE_EVIDENCE`：安全但收益不稳定、UNKNOWN/REVIEW 未关闭或样本不足。
- `ELIGIBLE_FOR_ADOPTION_GATE`：完整覆盖范围内 Safety PASS 且相对 Baseline 的质量净增益成立；仍不等于正式生产。
- **DECISION**：E1-02 不直接修改正式 4K 路由。

---

## 10. Topaz V0.2 研究吸收边界

- **FACT**：研究记录 164 个资产、60/60 JSON、594 条 net 引用、13 个 GCLC 引用配置、10 个 LDCLC 引用配置和 12 个 `autoModel` 静态引用。
- **FACT**：`ROUTING_EVIDENCE=NOT_FOUND`、`RUNTIME_ROUTING_EVIDENCE=NONE`。
- **INFERENCE**：静态配置支持“主网络 + 辅助模块”“专项模型族”“多 backend 描述”的模块化观察。
- **DECISION**：HDDE 只吸收模块化、Candidate 可替换、主增强与安全门禁分离、多 backend 抽象和产品级质量门禁思想。
- **DECISION**：不得复制模型、权重、私有格式、网络结构、模型名或未经证明的路由逻辑。
- **DEFERRED**：在 HDDE 第一个 Candidate 证明净增益之前，不建设多模型自动路由或多 backend 产品调度。

---

## 11. 12 个架构问题的冻结答案

1. **LANCZOS 的未来角色？**  
   **DECISION**：永久 Safe Baseline、对照、fallback 和回归锚点，不是 Enhancement。

2. **`four_k_v1.py` 继续负责什么？**  
   **DECISION**：原图事实、Target Plan、LANCZOS Baseline、Alpha/ICC/PNG 和 Baseline 验证；不承载 Candidate、路由和质量裁决。

3. **HD Core 是否成为未来 4K 实验与 Candidate 骨架？**  
   **DECISION**：是，但先保持实验层；复用隔离、记录和 fallback，升级为 source-direct Candidate 合同后才能继续。

4. **`fidelity_enhancement` 如何处置？**  
   **DECISION**：降级为显式实验 Candidate；先适配合同并通过 E1-02，不直接进入正式 4K。

5. **`low_quality_fidelity` 承担什么？**  
   **DECISION**：提供分析代理、保护 mask 和保守策略的实验来源；不直接承担自动路由或质量真值。

6. **Candidate Framework 与 Delivery Gate 谁先？**  
   **DECISION**：Delivery Gate 先。没有 Baseline-relative 的判定合同，Candidate Framework 只会加速生成无法裁决的结果。E1-02 先提供任何 Candidate 都必须面对的统一验收器。

7. **E1-01 如何升级为 E1-02？**  
   **DECISION**：保持 E1-01 不变，在新 batch 中加入 Candidate output、GT-native 与 4K-native 双域比较、自动事实、盲化 100% ROI 人工复核、风险/收益/拒绝与 fallback 状态。

8. **中文和 Logo 保护在哪一层？**  
   **DECISION**：Analysis 提供区域提示；Safety Gate 判断破坏；Quality Gate 判断是否相对 Baseline 有收益；Production Adoption 聚合覆盖。不能只放在增强算法内部自证安全。

9. **人脸身份保护是否属于 V0.5.7 MUST_HAVE？**  
   **DECISION**：属于 Production Adoption MUST_HAVE。若 Candidate 不支持人像，也必须证明人像稳定 REVIEW/fallback；自动检测未证明前不得自动放行。

10. **自动路由是否属于 V0.5.7 MUST_HAVE？**  
    **DECISION**：不是，属于 FUTURE_VERSION。V0.5.7 只需要显式 Candidate 与 Baseline 比较、门禁和 fallback。

11. **第一个真实 Candidate 必须满足什么？**  
    **DECISION**：合法自有；source-direct；固定版本和参数；隔离运行；完整 Candidate 合同；输出与 Target Plan 一致；失败精确 fallback；完成 E1-02；安全通过且真实净增益相对 Baseline 成立；生产前再过 Adoption Gate。

12. **如何证明清晰不是假锐化？**  
    **DECISION**：要求 GT/可解释结构对齐、边缘连续性和人工 100% ROI 改善，同时排除 overshoot、ringing、噪声、假纹理、字形/身份/颜色损坏；Laplacian 或高频增加单独无效。

---

## 12. V0.5.7 范围冻结

### 12.1 MUST_HAVE

1. LANCZOS Baseline 与 Enhancement Candidate 彻底分离。
2. E1-02 Baseline-vs-Candidate Quality/Delivery Gate。
3. source-direct、隔离、可追溯、可复现、可拒绝的 Candidate 最小合同。
4. Pixel/Alpha/Geometry/Edge/Frequency/Identity/Color Safety Gate。
5. `QUALITY_GAIN_PROVEN` 与 `PASS/REVIEW/FAIL` 独立状态机。
6. 任意失败或缺证据时的同任务精确 Baseline fallback。
7. 中文、Logo、产品、材质、人像与 Alpha 的固定覆盖和 100% ROI 复核。
8. 第一个合法自有 Candidate 的 E1-02 真实证据。
9. Candidate 晋级前的扩展样本、回归和当前 HEAD 真实 E2E。
10. 未证明 Candidate 永不进入正式输出。

### 12.2 SHOULD_HAVE

- 退化代理指标的版本化、可解释记录和初步校准。
- Candidate 运行时间、内存、backend/device 与确定性事实。
- 盲化/随机化人工复核工具和分歧记录。
- 失败样本自动进入回归集。
- Candidate 适用范围与明确不适用范围。
- 单一已证明 Candidate 的 shadow adoption 能力。

### 12.3 FUTURE_VERSION

- 多 Candidate 自动路由。
- 多 backend 自动选择与失败优先级。
- 人脸专项增强模型、文字专项增强模型或材质专项模型。
- 在线学习、用户偏好自适应或内容级动态参数搜索。
- macOS/HarmonyOS PC 的 Candidate backend 正式适配与独立证明。
- 超出 4K 的 8K 或印刷承诺。

### 12.4 DO_NOT_BUILD

- Topaz Architecture Clone、Topaz 权重/私有格式/模型名复用。
- 在 Candidate 未证明前建设复杂模型注册中心、自动路由器或 backend 调度平台。
- 以 Laplacian、高频、锐化量或文件尺寸作为单一质量结论。
- 通过简单放宽 RGB delta 让 Candidate 过门禁。
- 通过删除失败样本、修改 ROI 或只展示成功结果制造 PASS。
- 把 Candidate、分析、门禁和晋级逻辑继续堆入 `four_k_v1.py`。
- 无效模型轮换、重复 Benchmark 外壳、重复架构报告或审核套审核。
- 云端主产品、云端存储依赖或与 E线核心目标无关的平台化扩张。

---

## 13. 正式开发阶段（最多 5 个）

### E4K-01｜E1-02 Quality / Delivery Gate V1

```text
TASK_ID=E4K-01
GOAL=建立可接收外部Candidate输出的E1-02评估器，完成Baseline-relative双域ROI、自动事实、人工复核槽位、风险/收益/拒绝状态
WHY_NOW=当前最大缺口不是Candidate数量，而是无法证明任何RGB变化是安全且有净增益；E1-01数据已就绪
CODE_SCOPE=新增E1-02实验评估模块与定向测试；只读引用E1-01；不改正式4K/HD Core/API/UI
REUSE=rerender_candidate_comparisons、E1-01 manifest、GT、ROI、Baseline、full-image comparison、comparison contract、现有hash/image facts、quality proxy
NEW_CAPABILITY=统一Candidate证据输入与可拒绝的Quality/Delivery判定载体
TEST=manifest不可变、hash绑定、缺失/错误尺寸/解码失败、GT-native映射、4K-native 100% crop、NOT_ASSESSED fail-closed
EVIDENCE=新E1-02 batch、validation、每案例完整证据与未评估状态
PASS_GATE=能够完整处理现有16案例且绝不在人工/风险字段缺失时输出QUALITY_GAIN_PROVEN
FAIL_GATE=覆盖E1-01、遗漏失败案例、ROI漂移、无证据自动PASS或触碰正式目录
STOP_CONDITION=评估合同无法区分安全与增益，或无法保持E1-01和正式目录不变
```

### E4K-02｜Source-direct Candidate Runtime V1

```text
TASK_ID=E4K-02
GOAL=把HD Core升级为原图直达、Baseline只读对照、独立Candidate输出和精确fallback的实验Runtime
WHY_NOW=E1-02先定义了Candidate必须提供的证据，Runtime才能按消费合同实现
CODE_SCOPE=HD Core实验层与定向测试；不接正式/api/upload
REUSE=isolated workspace、safe_base、candidate injection、runtime record、fallback
NEW_CAPABILITY=版本化Candidate合同、source-direct输入、多状态记录、独立拒绝
TEST=无Candidate、恒等、RGB变化、异常、缺失、路径越界、Alpha、参数与环境记录、并列Candidate互不污染
EVIDENCE=Runtime manifest和精确fallback证明
PASS_GATE=任一Candidate失败均不污染Baseline/其他Candidate且选择结果可复现
FAIL_GATE=Candidate读取其他Candidate输出、默认从Baseline二次增强、正式路径写入或状态混并
STOP_CONDITION=无法保证原图/Baseline/证据不可变或隔离边界
```

### E4K-03｜First Experimental Candidate A

```text
TASK_ID=E4K-03
GOAL=将一个合法自有现有算法以固定参数包装为第一个实验Candidate并完成16案例E1-02
WHY_NOW=门禁和Runtime已具备，首次Candidate结果可以被真实裁决而不是凭观感上线
CODE_SCOPE=Candidate适配器、定向测试和隔离实验；优先评估fidelity_enhancement但不预设其成功
REUSE=fidelity_enhancement及现有颜色/文字/边缘组件，仅作为实验实现
NEW_CAPABILITY=第一个可复现的真实增强候选输出
TEST=颜色通道、Alpha、ICC、尺寸、参数、确定性、异常fallback、全部E1-02案例
EVIDENCE=Candidate A完整manifest、全案例风险/收益、失败样本与人工100%复核
PASS_GATE=产生可审计候选并由E1-02给出真实结论；允许结论为REJECTED或NEED_MORE_EVIDENCE
FAIL_GATE=把执行成功写成质量成功、跳过失败案例、修改门禁迎合结果或接入正式链
STOP_CONDITION=候选没有稳定受益分层，或出现无法通过fallback隔离的结构/身份风险
```

### E4K-04｜Candidate Evidence Expansion and Gate Calibration

```text
TASK_ID=E4K-04
GOAL=扩展商业样本与退化覆盖，校准Safety/Quality代理指标并决定Candidate是否有晋级价值
WHY_NOW=16案例足以首轮证伪/发现问题，不足以证明广泛生产适用性
CODE_SCOPE=样本manifest、评估与回归测试；Candidate只允许最小必要修正，不做无效模型轮换
REUSE=E1-02、Candidate Runtime、失败样本回归、固定ROI协议
NEW_CAPABILITY=分内容/退化的证据边界、阈值版本和适用范围
TEST=扩展样本、Alpha、中文、Logo、产品、人像、already-clear控制、重复运行和人工复核一致性
EVIDENCE=扩展batch、完整失败率/REVIEW率、人工与自动指标一致性、Candidate冻结版本
PASS_GATE=Safety和Quality证据足以进入Production Adoption Gate
FAIL_GATE=净增益不稳定、关键类别破坏、阈值依赖事后调参或样本量仍不足
STOP_CONDITION=在预先限定迭代内无法证明超过Baseline的稳定净增益，则停止该Candidate路线
```

### E4K-05｜Production Adoption and Current-HEAD E2E

```text
TASK_ID=E4K-05
GOAL=仅将已晋级的冻结Candidate版本接入4K正式编排，并保留同任务Baseline与精确fallback
WHY_NOW=只有完成前四阶段后，生产接入才有真实价值且风险可控
CODE_SCOPE=正式HD Core orchestration、main.py最小接线、Task/Result/Delivery事实、定向E2E；four_k_v1保持Baseline职责
REUSE=现有/api/upload、任务、SSE、Result、Delivery、Feedback和正式目录合同
NEW_CAPABILITY=有证据的Candidate生产选择与可审计fallback
TEST=当前HEAD真实上传到交付、异常fallback、重启/任务状态、Alpha、目录、结果注册、回归和用户路径
EVIDENCE=真实运行记录、正式输出、Candidate/Baseline决策、当前HEAD E2E与人工验收
PASS_GATE=只有Safety PASS、QUALITY_GAIN_PROVEN、adoption已批准的Candidate可成为正式结果；其他情况精确Baseline
FAIL_GATE=任意无证据Candidate交付、假completed、内部路径泄漏、fallback不等价或破坏既有结果链
STOP_CONDITION=Candidate未达到晋级门禁时不得开始本阶段；保持现有LANCZOS正式链
```

---

## 14. 第一正式开发任务

```text
FIRST_DEVELOPMENT_TASK=E4K-01_E1_02_QUALITY_DELIVERY_GATE_V1
```

### 14.1 为什么是现在收益最高、风险最低的一步

- **FACT**：E1-01 已有固定样本、GT、ROI、退化族、Baseline 和 validation，但 Candidate 与所有质量判断为空。
- **FACT**：当前 HD Core 能安全拒绝 RGB 变化，却不能判断哪些变化是有益的。
- **DECISION**：先建立 E1-02 可以立即把任何现有或未来 Candidate 放入同一证据合同，减少模型轮换、主观挑图和事后改门禁。
- **DECISION**：该任务不触碰正式 4K、API/UI、正式目录或生产结果，失败成本最低。
- **DECISION**：完成后下一步可直接开发 source-direct Candidate Runtime，不再重新规划架构。

### 14.2 第一任务明确不做

- 不开发或选择新的模型。
- 不把 `fidelity_enhancement` 接入正式链。
- 不修改 `four_k_v1.py`、`main.py`、UI 或正式目录。
- 不设置未经校准的质量阈值。
- 不输出 `QUALITY_GAIN_PROVEN`，除非自动事实、人工复核和拒绝字段全部满足合同。

---

## 15. 冻结结论

```text
TARGET_ARCHITECTURE_DEFINED=YES
SAFE_BASELINE_ROLE=PERMANENT_CONTROL_FALLBACK_REGRESSION_ANCHOR
FOUR_K_V1_ROLE=FROZEN_BASELINE_CONTRACT_AND_EXECUTOR
HD_CORE_ROLE=EXPERIMENTAL_SOURCE_DIRECT_CANDIDATE_AND_GATE_BACKBONE_AFTER_UPGRADE
CANDIDATE_ARCHITECTURE=DEFINED
SAFETY_GATE_DEFINED=YES
QUALITY_GATE_DEFINED=YES
PRODUCTION_ADOPTION_GATE_DEFINED=YES
E1_02_DEFINED=YES
V0_5_7_MUST_HAVE=FROZEN
V0_5_7_SHOULD_HAVE=FROZEN
FUTURE_VERSION=FROZEN
DO_NOT_BUILD=FROZEN
DEVELOPMENT_STAGE_COUNT=5
FIRST_TASK_REFERENCE=E4K-01_E1_02_QUALITY_DELIVERY_GATE_V1
BLOCKER=NONE
```

### 15.1 仍需证据但不阻断架构冻结

- **NEED_PROOF**：生产晋级所需扩展样本的数值下限。
- **NEED_PROOF**：Candidate 运行失败率、REVIEW 比例和人工评审一致性阈值。
- **NEED_PROOF**：颜色、频率、Halo、ringing、文字、Logo、人脸和材质的自动指标及阈值。
- **NEED_PROOF**：`fidelity_enhancement` 或任何其他 Candidate 是否存在稳定净增益。
- **NEED_PROOF**：未来正式 Candidate 的 Windows/macOS/HarmonyOS PC backend 事实。

这些未知被显式隔离在 E1-02、Evidence Expansion 和 Production Adoption Gate 中，不要求在本轮凭空给出数值，因此不构成架构矛盾。
