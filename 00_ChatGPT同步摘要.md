# VisualMasterPro ChatGPT 同步摘要

同步时间：2026-05-25

同步主题：VisualMasterPro V3.6 整体项目状态与中文版本文档体系同步。

## 项目定位

VisualMasterPro（雪原Ai增强引擎）不是普通图片增强脚本，而是面向商业视觉交付的 AI 商业视觉质量引擎。

当前目标已经从“让图片更清晰”升级为：

让 AI 图更像高级商业摄影、商业 CG、发布会主视觉、品牌 KV 和可交付商业终稿。

## 项目路径

`D:\Codex\04_Visual-Master-Pro`

## 当前阶段结论

项目已从 V1 单脚本增强，演进到 VisualMasterPro V0.3 的“图形化批量处理 + 原图忠实增强 + 4K 清晰优化”测试阶段。

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
- 完整版本说明文档体系
- 批量处理系统
- tkinter 图形化界面
- 原图忠实增强算法链
- 文字可辨识度增强

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
| `batch/` | V0.3 批量处理系统，负责批量导入、单张容错、输出命名、批量日志和批量报告。 |
| `gui/` | V0.3 图形化界面，支持添加图片、选择文件夹、选择输出目录、处理进度和任务日志。 |
| `pipelines/` | V3.4 新增的模式管线系统，不同 mode 使用不同处理流程。 |
| `modes/` | mode 配置与注册。 |
| `rules/` | 全局视觉规则库。 |
| `ai_noise_rules/` | AI 脏感、diffusion 纹理、假 HDR、电子锐边规则。 |
| `material_rules/` | 材质规则库。 |
| `visual_style_rules/` | 商业视觉风格库。 |
| `docs/` | 架构说明、文件管理规范、测试报告。 |
| `软件版本历史.md` | 长期版本历史，记录每个版本的功能、技术升级、商业价值与下一步计划。 |
| `项目路线图.md` | 未来版本路线图，覆盖 V3.8、V4.0、V4.5、V5.0。 |
| `更新日志.md` | 中文软件更新日志，采用“新增功能 / 优化内容 / 修复问题 / 架构升级 / 已知问题”结构。 |
| `商业版本规划.md` | 商业版本规划，覆盖免费版、创作者版、工作室版、企业版。 |
| `技术架构说明.md` | 技术架构说明，覆盖模块关系、处理流程、商业签名引擎、预设系统和 GPU 方向。 |
| `项目说明.md` | 中文项目说明，面向中国商业设计用户、中国 AI 视觉创作者和中国视觉工作室。 |
| `README.md` | GitHub 项目首页，已改为中文入口页并链接到中文文档体系。 |
| `tests/outputs/` | 临时测试输出，不作为正式交付。 |
| `输入图片/` | 待处理原图。 |
| `输出成品/images/` | 正式商业交付图。 |
| `scripts/master_process.py` | 历史兼容入口，保留不删除。 |

## V0.3 批量处理与 GUI 状态

当前已新增：

- `batch/batch_processor.py`
- `batch/batch_task.py`
- `batch/batch_logger.py`
- `batch/batch_report.py`
- `gui/app.py`
- `gui/gui_state.py`
- `gui/components.py`

GUI 启动方式：

```powershell
python main.py --gui
python -m gui.app
```

批量处理核心函数：

```python
process_batch(
    input_paths,
    output_dir,
    mode="fidelity",
    scale=2,
    output_format="png"
)
```

V0.3 对外模式：

- `fidelity`：原图忠实增强。
- `text_safe`：文字保护增强。
- `ai_image_clean`：AI 图像清洁增强。
- `sharp_4k`：4K 清晰增强。

输出命名：

```text
原文件名_vmp_v03_4k.png
```

默认原则：

- 不主动修改构图。
- 不主动改色。
- 不重塑画风。
- 不生成新内容。
- 默认输出不加角标。
- debug/developer 模式才允许角标、JSON、Markdown、compare 图。

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

## 中文版本文档体系状态

已建立完整中文版本说明文档体系，用于 Codex 开发同步、GitHub 项目记录、商业化迭代管理、用户更新日志和后续收费版本规划。

### 新增 / 重构文档

| 文档 | 用途 |
|---|---|
| `软件版本历史.md` | 按版本号记录 V1.0、V2.0、V3.0、V3.5、V3.6、V3.7 的完整版本历史。 |
| `项目路线图.md` | 规划 V3.8、V4.0、V4.5、V5.0 的战略目标、核心技术、商业方向、难度和市场定位。 |
| `更新日志.md` | 重构为中文软件更新日志格式，覆盖 V1.0 到 V3.7。 |
| `商业版本规划.md` | 规划免费版、创作者版、工作室版、企业版的功能权限、GPU、输出规格、商业授权、云同步、批量输出、API 和价格定位。 |
| `技术架构说明.md` | 说明项目结构、模块关系、图像处理流程、商业签名引擎、预设系统、GPU 处理流程和 AI 增强逻辑。 |
| `项目说明.md` | 面向中国商业设计用户、中国 AI 视觉创作者和中国视觉工作室的正式中文产品说明。 |
| `README.md` | 改为 GitHub 中文入口页，链接到完整中文文档体系。 |

### 文档定位

这套文档体系把 VisualMasterPro 从“开发中项目”推进为“面向中国商业视觉行业、可被 GitHub 展示、可商业化规划、可长期版本管理的软件项目”。

建议下一次提交信息：

```text
Docs: convert project documentation to full Chinese commercial system
```

## GitHub 备份状态

目标仓库：

```text
https://github.com/xyaippt-create/xyai.git
```

当前状态：

- GitHub 数据备份已完成。
- 当前分支：`main`
- 远程分支：`origin/main`
- 最新 commit id：`bf079bb46dffa72a3b835a39a05e53a9f606dc28`
- Commit 信息：`V3.6 TEST - Single Delivery Output + Mode Pipeline System`
- Push 状态：成功，`main -> origin/main`
- 本次提交：`79 files changed, 4289 insertions(+)`
- `.gitignore` 已存在，并已覆盖缓存、打包产物、测试输出和临时文件。
- 注意：中文版本文档体系是在本次 GitHub 备份后新增 / 重构，当前尚未提交到 GitHub。

已执行关键命令：

```powershell
git status
git add .
git commit -m "V3.6 TEST - Single Delivery Output + Mode Pipeline System"
git push -u origin main
git status --short --branch
```

补充说明：

- 当前 PowerShell 里 `git` 仍不在 PATH。
- 已检测到 Git 安装路径：`C:\Program Files\Git\cmd\git.exe`。
- 本次使用完整路径完成提交与推送。
- 提交前 Git 身份未配置，已在当前仓库设置局部身份：
  - `user.name = xyaippt-create`
  - `user.email = xyaippt-create@users.noreply.github.com`

## 当前已知问题

1. 商业信息角标目前使用 OpenCV 默认字体，英文清晰，但整体字体高级感仍可提升。
2. mode pipeline 已经分流，但视觉差异仍处于第一版，需要继续加深各 mode 的专属算法。
3. 当前 `quality_report` 评分仍是工程化启发式指标，还不是成熟商业审美评分模型。
4. 输出默认只处理第一张图，符合“单图交付”，但后续如果需要批量商业交付，应新增显式 `--batch`。
5. `Material Reconstruction: ON` 当前是交付状态提示，还没有真实材质重建开关系统。
6. 当前 PowerShell PATH 未包含 Git，需要后续补充系统 PATH，避免每次使用完整路径。
7. 中文版本文档体系已建立，但尚未创建新的文档提交。

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
