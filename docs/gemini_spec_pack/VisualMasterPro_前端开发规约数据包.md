# VisualMasterPro 前端开发规约数据包

Frontend-Ready Spec Pack for Gemini Pro

## 项目背景

VisualMasterPro 是一套 AI 视觉增强与高质量图像处理系统。当前前端方向不是普通工具界面，而是面向高保真、电影级、未来主义视觉体验的专业软件界面。

前端视觉风格已定调为：

- 极境自然与未来主义融合。
- 电影级景深。
- 参数化发光地表。
- 建筑级 3D 雕刻汉字。
- 极细英文衬线体装饰。

本规约包只定义前端逻辑骨架、数据结构、页面状态、组件职责和 API 契约，不包含 CSS、Tailwind 或具体样式代码。

---

## 1. 核心页面树与路由规划

### 1.1 页面路由总览

```json
{
  "appName": "VisualMasterPro",
  "version": "V0.3 / V0.4 AI Restoration Pipeline 方向",
  "routes": [
    {
      "path": "/",
      "name": "启动页",
      "page": "LaunchPage",
      "purpose": "软件启动、运行环境检查、进入主工作台"
    },
    {
      "path": "/dashboard",
      "name": "主工作台",
      "page": "DashboardPage",
      "purpose": "图片导入、批量任务、增强模式选择、开始处理"
    },
    {
      "path": "/task/:taskId",
      "name": "任务详情页",
      "page": "TaskDetailPage",
      "purpose": "查看单次批量处理任务进度、结果、失败项"
    },
    {
      "path": "/image/:imageId",
      "name": "图片对比页",
      "page": "ImageComparePage",
      "purpose": "查看原图、增强图、对比图、局部细节、画质指标"
    },
    {
      "path": "/quality/:imageId",
      "name": "质量报告页",
      "page": "QualityReportPage",
      "purpose": "查看 clarity、text、edge、structure、color fidelity 等评分"
    },
    {
      "path": "/pipeline",
      "name": "AI 修复管线页",
      "page": "PipelinePage",
      "purpose": "展示当前 restoration pipeline、模型状态、处理策略"
    },
    {
      "path": "/logs",
      "name": "日志中心",
      "page": "LogsPage",
      "purpose": "查看 latest_batch.log、latest_crash.txt、运行状态"
    },
    {
      "path": "/settings",
      "name": "设置页",
      "page": "SettingsPage",
      "purpose": "设置输出目录、默认模式、倍率、格式、模型路径"
    },
    {
      "path": "/help",
      "name": "帮助中心",
      "page": "HelpPage",
      "purpose": "使用说明、FAQ、日志位置说明、快速引导"
    }
  ]
}
```

### 1.2 页面跳转逻辑

```json
{
  "navigationFlow": [
    {
      "from": "/",
      "to": "/dashboard",
      "trigger": "启动检查完成"
    },
    {
      "from": "/dashboard",
      "to": "/task/:taskId",
      "trigger": "点击开始处理后创建批量任务"
    },
    {
      "from": "/task/:taskId",
      "to": "/image/:imageId",
      "trigger": "点击任意处理完成图片"
    },
    {
      "from": "/image/:imageId",
      "to": "/quality/:imageId",
      "trigger": "点击查看质量报告"
    },
    {
      "from": "/dashboard",
      "to": "/pipeline",
      "trigger": "点击 AI Restoration Pipeline 状态入口"
    },
    {
      "from": "any",
      "to": "/logs",
      "trigger": "点击日志中心或发生错误"
    },
    {
      "from": "any",
      "to": "/help",
      "trigger": "点击帮助"
    },
    {
      "from": "any",
      "to": "/settings",
      "trigger": "点击设置"
    }
  ]
}
```

---

## 2. 页面组件级拆解

### 2.1 启动页 LaunchPage

```json
{
  "page": "LaunchPage",
  "components": [
    {
      "name": "BrandIntroPanel",
      "label": "品牌启动展示区",
      "type": "静态展示",
      "description": "展示 VisualMasterPro V0.3、原图忠实增强、AI Restoration Pipeline 方向"
    },
    {
      "name": "StartupCheckPanel",
      "label": "启动检查面板",
      "type": "动态交互",
      "description": "检查 runtime、logs、输入目录、输出目录、模型目录、依赖状态"
    },
    {
      "name": "QuickGuideModal",
      "label": "首次启动快速引导",
      "type": "动态交互",
      "description": "首次启动时弹出，引导用户添加图片、选择输出目录、开始处理"
    }
  ]
}
```

### 2.2 主工作台 DashboardPage

```json
{
  "page": "DashboardPage",
  "components": [
    {
      "name": "SideNavigation",
      "label": "侧边导航栏",
      "type": "动态交互",
      "items": ["主工作台", "AI管线", "日志", "设置", "帮助"]
    },
    {
      "name": "TopStatusStream",
      "label": "顶部状态动态流",
      "type": "动态交互",
      "description": "显示当前引擎状态、模型状态、GPU/CPU状态、最近任务状态"
    },
    {
      "name": "ImageImportPanel",
      "label": "图片导入区",
      "type": "动态交互",
      "actions": ["添加图片", "选择文件夹", "清空列表"]
    },
    {
      "name": "SelectedImageTable",
      "label": "待处理图片列表",
      "type": "动态交互",
      "columns": ["文件名", "尺寸", "大小", "类型检测", "状态"]
    },
    {
      "name": "EnhancementModePanel",
      "label": "增强模式面板",
      "type": "动态交互",
      "modes": ["fidelity", "text_safe", "ai_image_clean", "sharp_4k"]
    },
    {
      "name": "OutputSettingsPanel",
      "label": "输出设置",
      "type": "动态交互",
      "fields": ["输出目录", "倍率", "格式"]
    },
    {
      "name": "StartProcessButton",
      "label": "开始处理按钮",
      "type": "动态交互",
      "description": "创建批量任务并跳转任务详情页"
    }
  ]
}
```

### 2.3 任务详情页 TaskDetailPage

```json
{
  "page": "TaskDetailPage",
  "components": [
    {
      "name": "TaskHeader",
      "label": "任务头部信息",
      "type": "动态展示",
      "fields": ["任务ID", "模式", "倍率", "格式", "输出目录", "任务状态"]
    },
    {
      "name": "ProgressTimeline",
      "label": "处理进度时间线",
      "type": "动态交互",
      "description": "展示每张图片的处理阶段：读取、分析、修复、放大、质量评估、输出"
    },
    {
      "name": "TaskImageGrid",
      "label": "任务图片网格",
      "type": "动态交互",
      "description": "展示成功、失败、处理中、等待中图片"
    },
    {
      "name": "RealtimeLogStream",
      "label": "实时日志流",
      "type": "动态交互",
      "description": "通过 SSE 接收处理日志"
    },
    {
      "name": "TaskSummaryCard",
      "label": "任务统计卡片",
      "type": "动态展示",
      "fields": ["总数", "成功", "失败", "伪高清风险", "平均色彩忠实度"]
    }
  ]
}
```

### 2.4 图片对比页 ImageComparePage

```json
{
  "page": "ImageComparePage",
  "components": [
    {
      "name": "BeforeAfterViewer",
      "label": "原图/增强图对比查看器",
      "type": "动态交互",
      "features": ["左右对比", "滑杆对比", "局部放大", "100%查看"]
    },
    {
      "name": "DetailFocusPanel",
      "label": "细节观察面板",
      "type": "动态交互",
      "focusAreas": ["小字", "建筑边缘", "文物纹理", "高光反光", "远景结构"]
    },
    {
      "name": "QualityScorePanel",
      "label": "质量评分面板",
      "type": "动态展示",
      "fields": ["文字清晰度", "边缘质量", "结构恢复", "色彩忠实度", "伪高清标记"]
    },
    {
      "name": "OutputFileActions",
      "label": "输出文件操作区",
      "type": "动态交互",
      "actions": ["打开文件夹", "下载图片", "查看报告"]
    }
  ]
}
```

### 2.5 质量报告页 QualityReportPage

```json
{
  "page": "QualityReportPage",
  "components": [
    {
      "name": "QualityRadarChart",
      "label": "质量雷达图",
      "type": "动态展示",
      "metrics": ["clarity", "text", "edge", "structure", "texture", "noise", "color"]
    },
    {
      "name": "PseudoHDWarning",
      "label": "伪高清风险提示",
      "type": "动态展示",
      "description": "当文件变大但有效清晰度提升不足时显示警告"
    },
    {
      "name": "MetricDetailTable",
      "label": "指标明细表",
      "type": "动态展示",
      "fields": ["指标名", "原图值", "增强后值", "提升量", "结论"]
    },
    {
      "name": "ManualReviewChecklist",
      "label": "人工复核清单",
      "type": "动态交互",
      "items": ["小字是否更清楚", "是否改色", "是否过锐", "高光是否炸开", "结构是否更稳定"]
    }
  ]
}
```

### 2.6 AI 修复管线页 PipelinePage

```json
{
  "page": "PipelinePage",
  "components": [
    {
      "name": "PipelineGraph",
      "label": "AI Restoration Pipeline 流程图",
      "type": "动态展示",
      "nodes": [
        "图像类型检测",
        "JPEG压缩修复",
        "OCR文字区域检测",
        "AI超分/修复",
        "真实边缘保护",
        "高光保护",
        "色彩锁定",
        "质量对比"
      ]
    },
    {
      "name": "ModelStatusPanel",
      "label": "模型状态面板",
      "type": "动态展示",
      "models": ["Real-ESRGAN", "SwinIR", "HAT", "SCUNet", "PaddleOCR", "SUPIR研究项"]
    },
    {
      "name": "RestorationStrategyPanel",
      "label": "修复策略面板",
      "type": "动态展示",
      "fields": ["图片类型", "推荐策略", "保护区域", "禁用项"]
    }
  ]
}
```

---

## 3. 前后端交互 API 契约

### 3.1 启动检查

`GET /api/runtime/startup-check`

```json
{
  "request": {}
}
```

```json
{
  "success": true,
  "data": {
    "appVersion": "VisualMasterPro V0.3",
    "runtimeReady": true,
    "isPackaged": false,
    "pythonVersion": "3.12",
    "gpuInfo": "RTX 4060 Laptop GPU",
    "paths": {
      "inputDir": "D:/Codex/04_Visual-Master-Pro/输入图片",
      "outputDir": "D:/Codex/04_Visual-Master-Pro/输出成品",
      "logsDir": "D:/Codex/04_Visual-Master-Pro/logs"
    },
    "dependencies": {
      "cv2": "ok",
      "numpy": "ok",
      "PIL": "ok",
      "PaddleOCR": "missing",
      "RealESRGAN": "missing"
    }
  }
}
```

### 3.2 导入图片

`POST /api/images/import`

```json
{
  "inputPaths": [
    "D:/Codex/04_Visual-Master-Pro/输入图片"
  ],
  "recursive": false
}
```

```json
{
  "success": true,
  "data": {
    "total": 1,
    "images": [
      {
        "imageId": "img_001",
        "fileName": "3540fe7663cd45bfd4edb5248befc332.png",
        "path": "D:/Codex/04_Visual-Master-Pro/输入图片/3540fe7663cd45bfd4edb5248befc332.png",
        "width": 1672,
        "height": 941,
        "sizeBytes": 2416984,
        "format": "png",
        "status": "ready"
      }
    ],
    "ignoredFiles": []
  }
}
```

### 3.3 图像类型检测

`POST /api/images/analyze`

```json
{
  "imageIds": ["img_001"]
}
```

```json
{
  "success": true,
  "data": {
    "results": [
      {
        "imageId": "img_001",
        "imageType": "architecture",
        "confidence": 0.82,
        "scores": {
          "text_poster": 0.18,
          "architecture": 0.82,
          "artifact": 0.42,
          "portrait_indoor": 0.06,
          "ink_gray": 0.02,
          "general": 0.28
        },
        "detectedRisks": [
          "high_frequency_noise",
          "highlight_reflection",
          "small_text_unclear"
        ]
      }
    ]
  }
}
```

### 3.4 创建批量处理任务

`POST /api/tasks`

```json
{
  "imageIds": ["img_001"],
  "mode": "fidelity",
  "scale": 2,
  "outputFormat": "png",
  "outputDir": "D:/Codex/04_Visual-Master-Pro/tests/outputs/quality_core_test",
  "debug": true,
  "pipeline": {
    "jpegRepair": true,
    "textClarity": true,
    "edgeSafeEnhance": true,
    "structureRecovery": true,
    "highlightProtection": true,
    "colorLock": true,
    "qualityCompare": true
  }
}
```

```json
{
  "success": true,
  "data": {
    "taskId": "task_20260601_001",
    "status": "queued",
    "total": 1,
    "createdAt": "2026-06-01T10:30:00+08:00"
  }
}
```

### 3.5 任务进度流式接口

需要支持 Streaming / SSE。

`GET /api/tasks/task_20260601_001/stream`

```json
{
  "streaming": true,
  "protocol": "SSE",
  "events": [
    {
      "event": "task.started",
      "data": {
        "taskId": "task_20260601_001",
        "status": "running"
      }
    },
    {
      "event": "image.processing",
      "data": {
        "imageId": "img_001",
        "fileName": "3540fe7663cd45bfd4edb5248befc332.png",
        "stage": "structure_recovery",
        "progress": 0.62,
        "message": "正在恢复真实边缘与中频结构"
      }
    },
    {
      "event": "image.completed",
      "data": {
        "imageId": "img_001",
        "status": "success",
        "outputPath": "tests/outputs/quality_core_test/3540fe7663cd45bfd4edb5248befc332_vmp_v03_4k.png"
      }
    },
    {
      "event": "task.completed",
      "data": {
        "taskId": "task_20260601_001",
        "success": 1,
        "failed": 0
      }
    }
  ]
}
```

### 3.6 获取任务详情

`GET /api/tasks/task_20260601_001`

```json
{
  "success": true,
  "data": {
    "taskId": "task_20260601_001",
    "mode": "fidelity",
    "scale": 2,
    "outputFormat": "png",
    "status": "completed",
    "total": 1,
    "successCount": 1,
    "failedCount": 0,
    "outputDir": "tests/outputs/quality_core_test",
    "items": [
      {
        "imageId": "img_001",
        "sourcePath": "输入图片/3540fe7663cd45bfd4edb5248befc332.png",
        "outputPath": "tests/outputs/quality_core_test/3540fe7663cd45bfd4edb5248befc332_vmp_v03_4k.png",
        "comparePath": "tests/outputs/quality_core_test/compare/3540fe7663cd45bfd4edb5248befc332_compare.png",
        "qualityReportPath": "tests/outputs/quality_core_test/reports_json/quality_report.json",
        "status": "success",
        "message": "有效清晰增强"
      }
    ]
  }
}
```

### 3.7 获取质量报告

`GET /api/images/img_001/quality-report`

```json
{
  "success": true,
  "data": {
    "imageId": "img_001",
    "qualityFlag": "有效清晰增强",
    "isPseudoHD": false,
    "scores": {
      "clarityScore": 9.85,
      "textClarityScore": 71.48,
      "edgeQualityScore": 67.91,
      "structureScore": 21.5,
      "textureScore": 2.85,
      "noiseScore": 100.0,
      "colorFidelityScore": 96.13,
      "fidelityScore": 85.56
    },
    "gains": {
      "clarityGain": 0.91,
      "textClarityGain": 21.48,
      "edgeQualityGain": 17.91,
      "structureGain": 0.83,
      "noiseDelta": 0.0
    },
    "manualReviewFocus": [
      "小字是否更清楚",
      "边缘是否过锐",
      "建筑结构是否更稳定",
      "高光区域是否被错误增强",
      "整体是否仍然像原图"
    ]
  }
}
```

### 3.8 获取日志

`GET /api/logs/latest-batch`

```json
{
  "success": true,
  "data": {
    "logType": "latest_batch",
    "path": "logs/latest_batch.log",
    "content": [
      {
        "time": "2026-06-01 10:30:02",
        "level": "info",
        "message": "开始批量处理，模式=fidelity，倍率=2x，格式=png"
      },
      {
        "time": "2026-06-01 10:30:40",
        "level": "success",
        "message": "3540fe7663cd45bfd4edb5248befc332.png -> output.png"
      }
    ]
  }
}
```

### 3.9 AI 修复长任务接口

需要支持 Streaming / SSE。

`POST /api/restoration/run`

```json
{
  "imageId": "img_001",
  "strategy": {
    "jpegRepair": true,
    "realESRGAN": false,
    "swinIR": true,
    "paddleOCR": true,
    "textRegionProtection": true,
    "preventHallucination": true
  }
}
```

```json
{
  "success": true,
  "data": {
    "restorationTaskId": "restore_001",
    "status": "queued",
    "streamUrl": "/api/restoration/restore_001/stream"
  }
}
```

---

## 4. 前端状态机与异常边界

### 4.1 全局状态机

```json
{
  "states": [
    "initializing",
    "ready",
    "importing",
    "analyzing",
    "queued",
    "processing",
    "completed",
    "partial_failed",
    "failed",
    "empty",
    "offline"
  ],
  "transitions": [
    {
      "from": "initializing",
      "to": "ready",
      "condition": "启动检查通过"
    },
    {
      "from": "ready",
      "to": "importing",
      "condition": "用户添加图片或选择文件夹"
    },
    {
      "from": "importing",
      "to": "analyzing",
      "condition": "图片导入成功"
    },
    {
      "from": "analyzing",
      "to": "queued",
      "condition": "用户点击开始处理"
    },
    {
      "from": "queued",
      "to": "processing",
      "condition": "后端任务开始"
    },
    {
      "from": "processing",
      "to": "completed",
      "condition": "全部图片成功"
    },
    {
      "from": "processing",
      "to": "partial_failed",
      "condition": "部分图片失败"
    },
    {
      "from": "processing",
      "to": "failed",
      "condition": "任务整体失败"
    },
    {
      "from": "ready",
      "to": "empty",
      "condition": "没有可处理图片"
    },
    {
      "from": "any",
      "to": "offline",
      "condition": "接口断开或网络异常"
    }
  ]
}
```

### 4.2 加载中 Loading State

```json
{
  "loadingState": {
    "startup": {
      "title": "正在检查运行环境",
      "message": "正在检查依赖、目录、日志系统和模型状态。",
      "uiBehavior": [
        "禁用开始处理按钮",
        "显示分步骤检查状态",
        "允许进入日志中心"
      ]
    },
    "importingImages": {
      "title": "正在读取图片",
      "message": "正在分析图片尺寸、格式和文件状态。",
      "uiBehavior": [
        "显示导入进度",
        "列表行显示 skeleton",
        "允许取消导入"
      ]
    },
    "processing": {
      "title": "正在增强图片",
      "message": "正在执行压缩修复、文字增强、结构恢复和质量评估。",
      "uiBehavior": [
        "显示当前处理文件名",
        "显示 pipeline stage",
        "显示实时日志",
        "允许停止后续任务"
      ]
    }
  }
}
```

### 4.3 空数据 Empty State

```json
{
  "emptyState": {
    "noImages": {
      "title": "未检测到待处理图片",
      "message": "请添加图片，或选择包含图片的文件夹。",
      "actions": [
        {
          "label": "添加图片",
          "action": "openFilePicker"
        },
        {
          "label": "选择文件夹",
          "action": "openFolderPicker"
        }
      ]
    },
    "noReports": {
      "title": "暂无质量报告",
      "message": "请先完成一次 debug 模式处理，或在任务完成后查看质量报告。",
      "actions": [
        {
          "label": "返回主工作台",
          "action": "navigate:/dashboard"
        }
      ]
    },
    "noLogs": {
      "title": "暂无日志",
      "message": "当前还没有批量处理或错误记录。",
      "actions": [
        {
          "label": "开始处理",
          "action": "navigate:/dashboard"
        }
      ]
    }
  }
}
```

### 4.4 接口报错 / 网络异常 Error State

```json
{
  "errorState": {
    "runtimeError": {
      "title": "软件运行异常",
      "message": "软件遇到问题，已自动生成错误日志。请查看日志中心。",
      "actions": [
        {
          "label": "查看日志",
          "action": "navigate:/logs"
        },
        {
          "label": "重新检查环境",
          "action": "retry:startup-check"
        }
      ],
      "doNotShow": [
        "Python traceback 原文",
        "底层异常堆栈弹窗",
        "英文错误提示"
      ]
    },
    "imageReadFailed": {
      "title": "图片读取失败",
      "message": "当前图片可能已损坏，或格式暂不支持。",
      "recovery": [
        "跳过当前图片",
        "继续处理后续图片",
        "在任务详情中标记失败"
      ]
    },
    "modelMissing": {
      "title": "AI 修复模型未就绪",
      "message": "当前模型文件缺失，将使用基础画质核心流程继续处理。",
      "recovery": [
        "启用 CV fallback",
        "提示配置模型路径",
        "允许继续 fidelity 模式"
      ]
    },
    "pseudoHDDetected": {
      "title": "疑似伪高清",
      "message": "文件尺寸已变大，但有效清晰度提升不足。建议人工复核。",
      "recovery": [
        "显示质量报告",
        "提示尝试 text_safe 或 sharp_4k",
        "保留原图忠实版本"
      ]
    },
    "networkError": {
      "title": "连接异常",
      "message": "前端暂时无法连接本地处理服务。",
      "recovery": [
        "自动重连",
        "保留当前图片列表",
        "禁止重复提交任务"
      ]
    }
  }
}
```

### 4.5 前端核心数据模型

```json
{
  "ImageItem": {
    "imageId": "img_001",
    "fileName": "example.png",
    "sourcePath": "输入图片/example.png",
    "width": 1672,
    "height": 941,
    "sizeBytes": 2416984,
    "format": "png",
    "imageType": "architecture",
    "status": "ready",
    "selected": true
  },
  "BatchTask": {
    "taskId": "task_001",
    "mode": "fidelity",
    "scale": 2,
    "outputFormat": "png",
    "status": "processing",
    "progress": 0.62,
    "total": 10,
    "success": 6,
    "failed": 0,
    "waiting": 4
  },
  "QualityReport": {
    "imageId": "img_001",
    "qualityFlag": "有效清晰增强",
    "isPseudoHD": false,
    "scores": {
      "clarityScore": 9.85,
      "textClarityScore": 71.48,
      "edgeQualityScore": 67.91,
      "structureScore": 21.5,
      "textureScore": 2.85,
      "noiseScore": 100.0,
      "colorFidelityScore": 96.13,
      "fidelityScore": 85.56
    }
  },
  "PipelineStatus": {
    "currentStage": "structure_recovery",
    "stages": [
      {
        "key": "image_type_detection",
        "label": "图像类型检测",
        "status": "done"
      },
      {
        "key": "compression_repair",
        "label": "压缩损伤修复",
        "status": "done"
      },
      {
        "key": "text_clarity",
        "label": "文字清晰增强",
        "status": "running"
      },
      {
        "key": "quality_compare",
        "label": "质量对比",
        "status": "waiting"
      }
    ]
  }
}
```

### 4.6 前端开发重点约束

```json
{
  "frontendRules": [
    "所有用户可见文案使用中文。",
    "不要展示 Python 原始报错。",
    "处理失败时必须给出日志入口。",
    "默认正式输出不展示角标、不展示调试信息。",
    "debug 模式才展示 compare、quality_report、batch_report。",
    "界面重点表达真实画质恢复，不表达单纯放大。",
    "质量报告必须突出：是否伪高清、是否改色、文字是否提升、边缘是否过锐。",
    "AI Restoration Pipeline 后续模型接入时，必须保留防止 AI 乱生成的状态提示。"
  ]
}
```
