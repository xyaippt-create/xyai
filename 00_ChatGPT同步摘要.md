# VisualMasterPro ChatGPT 同步摘要

同步时间：2026-05-25

同步主题：VisualMasterPro V3.6 整体项目状态同步。

## 项目定位

VisualMasterPro（雪原Ai增强引擎）不是普通图片增强脚本，而是面向商业视觉交付的 AI 商业视觉质量引擎。

当前目标已经从“让图片更清晰”升级为：

让 AI 图更像高级商业摄影、商业 CG、发布会主视觉、品牌 KV 和可交付商业终稿。

## 项目路径

`D:\Codex\04_Visual-Master-Pro`

## 当前阶段结论

项目已从 V1 单脚本增强，演进到 V3.6 的“单图商业交付系统”。

当前已经具备：

- 统一入口 `main.py`
- `engine.pipeline` 总编排
- 视觉规则加载与解释
- `ProcessingStrategy` 策略结构
- 商业视觉模式系统
- 独立 mode pipeline
- AI 脏感控制
- 中频结构恢复
- 商业光影处理
- 内部质量报告
- 最终交付图商业信息角标
- 默认单图交付逻辑
- 中文路径兼容
- EXE 打包保留

## 当前目录职责

| 目录 / 文件 | 当前职责 |
|---|---|
| `main.py` | 统一入口，支持输入、输出、mode、debug/developer 参数。 |
| `engine/` | 核心引擎层，包含算法、分析、规则解释、图像读写和 pipeline 编排。 |
| `engine/analysis/` | 视觉分析与质量报告内部系统。 |
| `engine/algorithms/` | 可插拔算法模块，如 AI 脏感控制、中频恢复、商业光影。 |
| `engine/pipeline/orchestrator.py` | 主流程编排：读取、分析、选 mode、执行 mode pipeline、生成交付图。 |
| `engine/rules/` | 规则加载与规则解释。 |
| `engine/config/processing_strategy.py` | 视觉处理策略数据结构。 |
| `engine/delivery/` | 交付系统，包括商业信息角标和 debug compare 图。 |
| `pipelines/` | V3.4 新增的模式管线系统，不同 mode 使用不同处理流程。 |
| `modes/` | mode 配置与注册。 |
| `rules/` | 全局视觉规则库。 |
| `ai_noise_rules/` | AI 脏感、diffusion 纹理、假 HDR、电子锐边规则。 |
| `material_rules/` | 材质规则库。 |
| `visual_style_rules/` | 商业视觉风格库。 |
| `docs/` | 架构说明、文件管理规范、测试报告。 |
| `tests/outputs/` | 临时测试输出，不作为正式交付。 |
| `输入图片/` | 待处理原图。 |
| `输出成品/images/` | 正式商业交付图。 |
| `scripts/master_process.py` | 历史兼容入口，保留不删除。 |

## 当前支持的 mode

- `auto`
- `ai_commercial_kv`
- `cosmetics`
- `food`
- `cinematic`
- `architecture`
- `ppt_business`
- `portrait_commercial`
- `luxury_product`

## V3.4 Mode Pipeline System 状态

当前已建立 `pipelines/` 独立模式管线层。

不同 mode 不再只靠 strength 参数区分，而是调用不同处理步骤。

### 已建立 pipeline

| pipeline | 视觉方向 |
|---|---|
| `ai_commercial_kv_pipeline.py` | 商业 KV、主体控制、空气感、高级感。 |
| `food_pipeline.py` | 食品光泽、暖高光、蒸汽空气感、食物结构。 |
| `cosmetics_pipeline.py` | 柔光、低噪波、护肤品 / 美妆质感、奶油高光。 |
| `luxury_product_pipeline.py` | 金属反射、镜面控制、玻璃材质、暗部高级感。 |
| `cinematic_pipeline.py` | 压高光、冷暗部、中间调、电影空气感。 |
| `architecture_pipeline.py` | 建筑直线、空间结构、空气透视、低纹理污染。 |
| `portrait_pipeline.py` | 皮肤干净、柔但不假、棚拍柔光、背景空气化。 |
| `ppt_business_pipeline.py` | 文字保护、背景干净、投影友好、版式稳定。 |

## V3.5 文件管理规范状态

已建立：

- `docs/file_management_rules.md`
- 正式输出目录收敛规则
- 测试输出与正式输出隔离规则
- `.gitignore` 忽略缓存、测试输出、打包产物和临时文件

当前正式输出目录只保留：

```text
输出成品/
└── images/
```

测试输出放入：

```text
tests/outputs/
```

## V3.6 Single Delivery Output System 状态

当前默认运行逻辑已经改为“单图商业交付”。

默认情况下：

- 只处理输入中的第一张图片
- 只输出一张最终商业交付图
- 不输出 JSON
- 不输出 Markdown
- 不输出 compare 图
- 内部仍生成 quality_report，用于评分和角标

正式输出位置：

```text
输出成品/images/
```

正式输出命名：

```text
原文件名_mode_雪原Ai·PPT设计.png
```

示例：

```text
3540fe7663cd45bfd4edb5248befc332_ai_commercial_kv_雪原Ai·PPT设计.png
```

## 商业信息角标

最终图右下角自动生成商业信息角标。

内容：

```text
VisualMasterPro V3.5
Mode: ai_commercial_kv
Commercial Score: XX
Structure Score: XX
Material Reconstruction: ON
```

角标设计要求：

- 半透明
- 小字清晰
- 不影响主体
- 商业摄影风格
- 右下角固定
- 使用内部 quality_report 的评分数据

相关文件：

- `engine/delivery/badge.py`
- `engine/delivery/compare.py`

## Debug / Developer 模式

仅在以下参数开启时输出开发文件：

```powershell
--debug
--developer
```

debug/developer 模式输出：

- `images/`：最终图
- `reports_json/`：JSON 质量报告
- `reports_md/`：Markdown 质量报告
- `compare/`：前后对比图

默认商业交付模式不输出这些调试文件。

## 当前验证状态

已验证：

- `main.py --help` 正常。
- 默认模式只生成 1 张最终图片。
- debug 模式生成 1 张图片、1 个 JSON、1 个 Markdown、1 张 compare 图。
- 正式 `输出成品/` 当前只保留 `images/` 目录。
- `tests/outputs/v3_6_default/` 中默认交付测试文件数量为 1。
- `tests/outputs/v3_6_debug/` 中 debug 测试文件数量为 4。
- 本次语法检查通过。
- 本次产生的 `__pycache__` 已清理。

## GitHub 备份状态

目标仓库：

```text
https://github.com/xyaippt-create/xyai.git
```

当前状态：

- `.git` 目录不存在，项目尚未完成 Git 初始化。
- `.gitignore` 已存在，并已覆盖缓存、打包产物、测试输出和临时文件。
- 本机 PowerShell 当前无法识别 `git`。
- 本机 PowerShell 当前无法识别 `gh`。
- 常见安装位置未检测到 Git 或 GitHub CLI。
- `winget`、`choco`、`scoop` 当前也不可用，因此无法自动安装。

已执行检测：

```powershell
git --version
gh --version
where.exe git
where.exe gh
winget --version
choco --version
scoop --version
```

结论：

GitHub 完整备份暂未完成。需要先安装 Git for Windows，并重新打开 PowerShell 后继续执行初始化、commit 和 push。

计划 commit 信息：

```text
V3.6 TEST - Single Delivery Output + Mode Pipeline System
```

安装 Git 后下一步：

1. `git init`
2. `git branch -M main`
3. `git add .`
4. `git commit -m "V3.6 TEST - Single Delivery Output + Mode Pipeline System"`
5. `git remote add origin https://github.com/xyaippt-create/xyai.git`
6. `git push -u origin main`

## 当前已知问题

1. 商业信息角标目前使用 OpenCV 默认字体，英文清晰，但整体字体高级感仍可提升。
2. mode pipeline 已经分流，但视觉差异仍处于第一版，需要继续加深各 mode 的专属算法。
3. 当前 `quality_report` 评分仍是工程化启发式指标，还不是成熟商业审美评分模型。
4. 输出默认只处理第一张图，符合“单图交付”，但后续如果需要批量商业交付，应新增显式 `--batch`。
5. `Material Reconstruction: ON` 当前是交付状态提示，还没有真实材质重建开关系统。
6. 当前没有 GitHub 成功上传记录，本机环境未检测到 Git。

## 请 ChatGPT 重点分析

1. V3.6 的“单图商业交付系统”是否符合商业软件默认交付逻辑。
2. 右下角商业信息角标是否应该保留，还是改为无角标交付、角标仅 debug 可见。
3. 当前 mode pipeline 的方向是否合理，哪些 mode 最需要先增强视觉差异。
4. `quality_report` 是否应该继续作为内部系统，还是生成可选客户版报告。
5. 下一阶段应优先开发：
   - 更真实的材质识别
   - 更强的商业光影重建
   - 更明显的 mode 风格差异
   - 批量交付模式
   - UI / EXE 双击交付体验

## 推荐下一阶段方向

建议进入：

```text
V3.7 Commercial Signature Engine
```

目标：

让每个商业 mode 拥有更明显的视觉签名。

优先级：

1. `cosmetics`：奶油高光、玻璃通透、干净背景。
2. `food`：食欲色彩、热气空气、湿润表皮。
3. `luxury_product`：黑金层次、金属反射、珠宝高光。
4. `portrait_commercial`：皮肤干净、柔光、发丝克制。
5. `architecture`：空间纵深、直线稳定、空气透视。
6. `ppt_business`：文字保护、低噪背景、版式安全。

长期目标仍然是：

VisualMasterPro 不是图片增强工具，而是 AI 商业视觉质量引擎。
