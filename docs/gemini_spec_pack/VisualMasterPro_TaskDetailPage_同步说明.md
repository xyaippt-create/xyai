# VisualMasterPro TaskDetailPage 同步说明

## 当前本地执行状态

已在本地前端工程中完成第三个核心页面接入：

- `src/LaunchPage.jsx`
- `src/DashboardPage.jsx`
- `src/TaskDetailPage.jsx`
- `src/App.jsx`

当前页面状态机已经从两态升级为三态，并预留下一阶段图片对比页：

```text
launch -> dashboard -> task_detail -> image_compare
```

## 新增页面

### TaskDetailPage

本地文件：

```text
src/TaskDetailPage.jsx
```

页面定位：

任务详情页，用于展示 VisualMasterPro 的高技术处理过程，包括 AI Restoration Pipeline 的阶段状态、模拟 SSE 日志流和任务完成后的对比入口。

## 视觉基调

TaskDetailPage 已保持以下视觉方向：

- 垂直冰川肌理。
- 深邃森林暗调。
- 微光参数化地表。
- 暗色透明玻璃面板。
- 高技术实时修复终端感。
- 与 LaunchPage、DashboardPage 保持同一套未来自然融合视觉系统。

## 核心交互组件

### ProgressTimeline

五大阶段时间线：

1. 图像读取
2. 视觉诊断
3. 核心修复
4. 忠实校准
5. 质量输出

状态：

- 等待
- 执行中
- 完成

### RealtimeLogStream

模拟 SSE 实时修复日志终端。

日志内容包括：

- SSE 长连接建立。
- 输入图片读取。
- 图像类型检测。
- 高光保护 mask。
- 压缩损伤修复。
- Text Clarity Engine。
- Edge Safe Enhance。
- Structure Recovery。
- Color Lock。
- Quality Compare。
- 任务完成。

### 查看对比动作

当：

```text
taskStatus === "completed"
```

时，启用“查看对比”按钮。

点击后触发：

```text
onViewCompare()
```

当前在 `App.jsx` 中已跳转到预留状态：

```text
image_compare
```

该状态目前为占位页，下一阶段可替换为正式 `ImageComparePage`。

## 当前 App.jsx 路由状态机

| 当前状态 | 触发动作 | 下一状态 | 说明 |
|---|---|---|---|
| `launch` | 启动页点击进入 | `dashboard` | 进入主工作台 |
| `dashboard` | 点击“开启核心修复管线” | `task_detail` | 进入任务详情页 |
| `task_detail` | 点击“返回工作台” | `dashboard` | 返回主工作台 |
| `task_detail` | 任务完成后点击“查看对比” | `image_compare` | 预留图片对比页 |
| `image_compare` | 点击返回任务详情 | `task_detail` | 当前为占位逻辑 |

## DashboardPage 更新点

DashboardPage 的执行按钮已从：

```text
开始处理
```

更新为：

```text
开启核心修复管线
```

点击后传递当前任务配置：

```json
{
  "mode": "fidelity",
  "scale": "2",
  "format": "png",
  "imageCount": 1,
  "source": "DashboardPage"
}
```

## 给 Gemini 的下一步任务建议

请基于当前已完成的三页系统：

1. LaunchPage
2. DashboardPage
3. TaskDetailPage

继续生成第四个核心页面：

```text
ImageComparePage
```

要求：

- 承接 `task_detail -> image_compare` 的跳转。
- 保持极境自然与未来主义融合视觉基调。
- 支持原图 / 增强图对比。
- 支持滑杆对比。
- 支持局部放大观察。
- 支持质量评分卡片。
- 支持返回 TaskDetailPage。
- 突出以下复核重点：
  - 小字是否更清楚。
  - 边缘是否过锐。
  - 建筑结构是否更稳定。
  - 文物纹理是否更真实。
  - 色彩是否保持原图。
  - 是否存在伪高清。
