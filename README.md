# VisualMasterPro（雪原Ai增强引擎）

VisualMasterPro 的目标不是普通图片增强，而是建立一套“商业高级感视觉引擎”。项目面向 AI 图、商业 KV、PPT 商业图、产品图、食品图、建筑图和电影感图像，逐步形成可复用、可配置、可扩展的商业视觉工业化系统。

## 核心方向

- AI图高级感增强
- 商业CG质感
- 电影空气感
- AI脏感清理
- 微对比增强
- 材质通透感
- 高频污染控制
- 不同材质不同增强逻辑

## 项目结构

| 目录或文件 | 保存内容 |
|---|---|
| `engine/` | 核心算法、图片读写、分析模块、处理流水线。未来所有稳定算法应沉淀到这里。 |
| `engine/algorithms/` | 单一职责图像算法，例如 AI 脏感清理、微对比增强、高频控制、材质增强、色调控制、放大。 |
| `engine/analysis/` | 图片检测和质检逻辑，例如亮度、对比度、锐度、材质线索、污染风险评分。 |
| `engine/io/` | 图片读写、中文路径兼容、批量图片收集、输出编码。 |
| `engine/pipeline/` | 把算法按商业视觉流程串起来，负责完整处理链路。 |
| `modes/` | 视觉模式系统。保存化妆品、食品、建筑、电影感、PPT商业、AI商业KV等模式。 |
| `rules/` | 全局视觉规则库。保存跨模式通用规则、输出策略、流水线顺序、禁止项。 |
| `ai_noise_rules/` | AI脏感数据库。保存 AI 糊纹、脏高光、假细节、边缘光晕等污染规则。 |
| `material_rules/` | 材质规则库。保存玻璃、金属、皮肤、食物、文字、天空等不同材质的增强逻辑。 |
| `visual_style_rules/` | 商业视觉风格库。保存高级感、CG感、电影空气感、PPT商业感等风格语言。 |
| `configs/` | 引擎默认配置，例如默认模式、目标宽度、输入输出目录、规则目录。 |
| `presets/` | 更细的行业预设，例如高透玻璃化妆品、暖色食品、建筑日景、AI商业KV。 |
| `tests/` | 后续自动化测试，验证中文路径、批量处理、输出尺寸、模式注册等。 |
| `docs/` | 架构说明、决策记录、版本规划、视觉标准文档。 |
| `scripts/` | 当前可运行脚本、历史脚本、打包文件。稳定后再逐步迁移到 `engine/`。 |
| `输入图片/` | 待处理图片。 |
| `输出成品/` | 处理后的成品图片。 |
| `00_ChatGPT同步摘要.md` | 给 ChatGPT 或人工复盘用的同步摘要。 |
| `AGENTS.md` | Codex 与 ChatGPT 在本项目里的协作规则。 |

## 长期架构原则

1. 算法和视觉规则分离：算法放 `engine/`，审美经验放规则库。
2. 模式和预设分离：模式是行业方向，预设是具体交付风格。
3. 全局规则和材质规则分离：材质规则优先于全局增强逻辑。
4. 可运行入口和核心引擎分离：`scripts/` 保持交付可用，`engine/` 逐步沉淀工业化能力。
5. 输出永远不覆盖原图。
6. 中文路径必须作为基础能力支持。

## V2 统一入口

V2 阶段统一入口为：

```powershell
python "D:\Codex\04_Visual-Master-Pro\main.py" "D:\Codex\04_Visual-Master-Pro\输入图片" "D:\Codex\04_Visual-Master-Pro\输出成品" --mode ai_commercial_kv
```

支持模式：

```text
cosmetics
food
cinematic
ppt_business
architecture
ai_commercial_kv
```

每张输出图会自动生成同名质量报告：

```text
*_quality_report.json
```

报告字段：

```json
{
  "premium_score": 0,
  "ai_noise_risk": "low",
  "high_frequency_risk": "low",
  "texture_cleanliness": "strong",
  "cinematic_depth": "moderate",
  "material_transparency": "strong"
}
```

## 旧脚本兼容入口

旧入口仍可继续使用，并已改为调用 V2 引擎：

```powershell
python "D:\Codex\04_Visual-Master-Pro\scripts\master_process.py" "D:\Codex\04_Visual-Master-Pro\输入图片" "D:\Codex\04_Visual-Master-Pro\输出成品"
```

也可以追加 `--mode` 参数。

## 未来模式

- 化妆品模式：玻璃、液体、皮肤、金属，高级通透感。
- 食品模式：食欲色、真实纹理、湿润感、油光控制。
- 建筑模式：线条稳定、空间通透、天空干净、材质清楚。
- 电影感模式：空气感、柔和层次、高光克制、暗部细节。
- PPT商业模式：文字清晰、版式安全、图表边缘稳定。
- AI商业KV模式：商业CG质感、主体高级感、AI脏感清理。

## 下一步建议

1. 为典型素材建立测试图集。
2. 将更多材质检测逻辑接入 `engine/analysis/material_detector.py`。
3. 把规则库参数进一步配置化，减少模式参数中的代码常量。
4. 开始积累真实案例的参数复盘。
