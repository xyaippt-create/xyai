# 项目结构说明

```text
VisualMasterPro/
  engine/              核心算法、分析、读写、处理流水线
  modes/               视觉模式系统
  rules/               全局视觉规则库
  ai_noise_rules/      AI脏感数据库
  material_rules/      材质规则库
  visual_style_rules/  商业视觉风格库
  configs/             默认引擎配置
  presets/             行业级预设
  tests/               自动化测试
  docs/                设计文档
  main.py              V2 统一命令行入口
  scripts/             旧入口包装、历史脚本和打包文件
  输入图片/             待处理图片
  输出成品/             处理后的成品图片
```

长期方向：

1. `main.py` 是 V2 统一入口。
2. `scripts/master_process.py` 只保留为 EXE 打包兼容入口。
3. 新算法先进入 `engine/algorithms`。
4. 新视觉模式先进入 `modes`。
5. 新判断经验先进入规则库，不直接写死在脚本里。
