# VisualMasterPro 给 Gemini 的工程同步包

同步时间：2026-06-02  
本地项目：D:\Codex\04_Visual-Master-Pro  
GitHub 仓库：https://github.com/xyaippt-create/xyai.git  
当前提交：a97750a  
当前版本定位：VisualMasterPro V0.3

---

## 1. 当前项目目标

VisualMasterPro 当前阶段不是单纯图片放大工具，而是面向真实画质恢复的本地图像增强系统。

核心原则：

- 原图忠实增强
- 不主动改色
- 不主动改变构图
- 不重塑画风
- 不生成新内容
- 提升真实清晰度
- 提升文字可辨识度
- 修复压缩损伤
- 保护真实边缘
- 支持本地上传、本地处理、本地对比

---

## 2. 当前前端工程状态

前端技术栈：

- React
- Vite
- Tailwind CSS
- 本地状态机路由
- Fetch + FormData 上传
- 本地后端图片 URL 渲染

前端核心文件：

- src/main.jsx
- src/App.jsx
- src/LaunchPage.jsx
- src/DashboardPage.jsx
- src/TaskDetailPage.jsx
- src/ImageComparePage.jsx
- src/QualityReportPage.jsx
- src/index.css

---

## 3. 五页路由闭环

当前 `src/App.jsx` 已完成五态联动：

1. launch：启动页
2. dashboard：画质核心工作台
3. task_detail：任务详情页
4. image_compare：原图 / 增强图滑杆对比页
5. quality_report：质量报告页

路由流转：

```text
LaunchPage
  -> DashboardPage
  -> TaskDetailPage
  -> ImageComparePage
  -> QualityReportPage
  -> DashboardPage
```

当前关键交互：

- 启动页自检完成后 2 秒自动进入工作台。
- 工作台选择图片后，通过 FormData 上传到后端 `/api/upload`。
- 后端返回真实原图 URL 和增强图 URL。
- 图片对比页使用返回的真实 URL 渲染滑杆对比。
- 质量报告页保留最终质检与归档动作。

---

## 4. 最新 UI 视觉与交互调整

### 启动页 LaunchPage

已完成：

- 废除左右分栏结构。
- 改为上方单行主标题，下方四个自检面板横向平铺。
- “原图忠实增强”保持单行横向展开。
- 字体使用冰晶渐变、文字描边与多层 text-shadow。
- 四个自检模块：
  - Runtime
  - Paths
  - Dependencies
  - Models
- 自检全部完成后，停留 2 秒并自动进入 Dashboard。

### 工作台 DashboardPage

已完成：

- “PHYSICAL CONTRACT” 已改为 “OUTPUT PARAMETERS”。
- “输出物理契约” 已改为 “输出图片参数”。
- “当前契约” 已改为 “当前参数”。
- 添加图片后调用真实后端上传接口。
- 上传成功后任务状态变成绿色 `ready`。
- 默认不再放置硬编码测试图。

### 图片对比页 ImageComparePage

已完成：

- 原图层读取 `compareAssets.originalUrl`。
- 增强图层读取 `compareAssets.enhancedUrl`。
- 保留滑杆对比。
- 保留鼠标移动放大镜。
- 增加右下角低透明水印。
- 修复水印文字溢出：使用 `overflow-hidden`、`right-4`、`max-w-[85%]`、`truncate` 和 `text-white/40`。

---

## 5. 当前后端工程状态

后端技术栈：

- Python
- Flask
- Flask-Cors
- OpenCV
- NumPy

后端核心文件：

- backend/restoration_server.py
- backend/__init__.py
- test_backend_server.py
- requirements.txt

---

## 6. 后端 API 契约

### 健康检查

```http
GET /api/health
```

返回：

```json
{
  "success": true,
  "data": {
    "name": "VisualMasterPro Realtime Restoration Backend",
    "version": "VisualMasterPro V0.3",
    "streamEndpoint": "/api/stream",
    "restoreEndpoint": "/api/restore",
    "restorator": "OpenCV lightweight fallback",
    "logLines": 11
  }
}
```

### SSE 实时日志

```http
GET /api/stream
```

事件类型：

```text
event: restoration.log
```

数据字段：

```json
{
  "index": 1,
  "total": 11,
  "message": "SSE CONNECTED /task/task_vmp_v03_core/stream",
  "timestamp": "2026-06-02T00:00:00",
  "done": false
}
```

### 图片上传与增强

```http
POST /api/upload
Content-Type: multipart/form-data
```

FormData 字段：

- file：用户上传图片
- mode：fidelity / text_safe / ai_image_clean / sharp_4k
- scale：2 或 4
- format：png / jpg

返回示例：

```json
{
  "success": true,
  "data": {
    "fileName": "test.png",
    "mode": "fidelity",
    "originalPath": "D:\\Codex\\04_Visual-Master-Pro\\tests\\outputs\\backend_uploads\\xxx.png",
    "outputPath": "D:\\Codex\\04_Visual-Master-Pro\\tests\\outputs\\backend_restored\\xxx.png",
    "originalUrl": "/api/file/uploads/xxx.png",
    "enhancedUrl": "/api/file/outputs/xxx.png",
    "sourceWidth": 1200,
    "sourceHeight": 800,
    "width": 2400,
    "height": 1600,
    "scale": 2,
    "format": "png",
    "qualityFlag": "有效清晰增强"
  }
}
```

### 静态图片访问

```http
GET /api/file/uploads/<filename>
GET /api/file/outputs/<filename>
```

路径映射：

- `/api/file/uploads` -> `tests/outputs/backend_uploads`
- `/api/file/outputs` -> `tests/outputs/backend_restored`

---

## 7. 已修复的问题

本轮已修复：

- React 页面缺少显式 React import 导致黑屏。
- 启动页左右分栏导致标题换行和视觉重叠。
- 启动页不能自动进入工作台。
- 工作台文案过于抽象。
- 前端上传状态卡在 uploading。
- 后端跨域导致 Failed to fetch。
- 对比页仍使用 Mock / 老图视觉。
- 对比页右下角水印文字溢出。
- 后端返回文件 URL 与前端渲染路径错配。
- `node_modules/` 已加入 `.gitignore`，避免依赖目录进入 Git。

---

## 8. 当前运行方式

### 启动后端

```powershell
python -m backend.restoration_server --host 127.0.0.1 --port 8787
```

如果本机没有系统 Python，可使用 Codex bundled Python：

```powershell
& "C:\Users\xyppt\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m backend.restoration_server --host 127.0.0.1 --port 8787
```

### 启动前端

```powershell
npm run dev
```

如果 npm 不在 PATH，可使用：

```powershell
& "C:\Users\xyppt\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" .\node_modules\vite\bin\vite.js --host 127.0.0.1 --port 5173
```

### 前端访问

```text
http://localhost:5173
```

---

## 9. 已验证项目

已完成验证：

- React/Vite 构建通过。
- 后端 Python 语法检查通过。
- 后端基础测试 `test_backend_server.py` 通过。
- Flask 测试客户端模拟上传通过。
- CORS 对 `http://localhost:5173` 返回正常。
- `/api/file/uploads` 和 `/api/file/outputs` 可返回图片资源。
- GitHub 已同步到 main 分支。

最新提交：

```text
a97750a Sync VisualMasterPro frontend backend integration
```

---

## 10. 给 Gemini 的下一步任务建议

请基于当前工程状态继续优化前端体验，不要重写工程结构。

优先任务：

1. 继续保持五页路由闭环不变。
2. 优化 DashboardPage 上传后的任务列表体验：
   - 多图上传队列
   - 失败重试
   - 真实缩略图
   - 上传进度
3. 优化 ImageComparePage：
   - 真实图片加载中状态
   - 图片加载失败状态
   - 放大镜显示真实图像局部，而不是抽象纹理
   - 支持拖动滑杆按钮
4. 优化 TaskDetailPage：
   - 将 Mock SSE 日志替换为真实 EventSource `/api/stream`
   - 日志完成后自动允许查看对比
5. 优化 QualityReportPage：
   - 从后端返回的质量指标生成真实报告
   - 将伪高清风险和清晰度提升用真实指标驱动
6. 保持视觉风格：
   - 极境自然
   - 未来主义
   - 冰川肌理
   - 深邃森林暗调
   - 极细英文衬线体装饰
   - 中文主视觉强识别

禁止事项：

- 不要把系统改成纯 Mock。
- 不要移除真实上传接口。
- 不要破坏 `compareAssets.originalUrl` 和 `compareAssets.enhancedUrl` 的真实数据链路。
- 不要引入后端无法支持的云端依赖。
- 不要重写为复杂路由库，当前状态机足够支持测试闭环。

---

## 11. 当前最重要的闭环标准

最终体验应达到：

1. 用户打开前端。
2. 启动页自检自动完成。
3. 2 秒后进入工作台。
4. 用户点击添加图片。
5. 前端上传真实图片到本地 Python 后端。
6. 后端生成增强图。
7. 前端进入任务详情并展示修复日志。
8. 用户进入滑杆对比页。
9. 对比页真实显示原图与增强图。
10. 用户查看质量报告。
11. 用户归档后回到工作台。

一句话目标：

让 VisualMasterPro 从“电影级前端样机”正式变成“可以上传真图、处理真图、对比真图的本地画质恢复系统”。
