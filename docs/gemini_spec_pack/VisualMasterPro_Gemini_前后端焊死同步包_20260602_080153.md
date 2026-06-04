# VisualMasterPro 给 Gemini 的最新同步包

同步时间：2026-06-02 08:01:53  
本地项目路径：D:\Codex\04_Visual-Master-Pro  
GitHub 仓库：https://github.com/xyaippt-create/xyai.git  
当前 Git 提交：a97750a  
重要说明：本同步包包含当前本地最新改动，其中 FastAPI 后端重构、启动页标题调整、依赖更新与忽略规则更新尚未提交到 GitHub。

---

## 1. 当前阶段目标

VisualMasterPro 当前正在从“电影级前端样机”进入“真实本地处理闭环”阶段。

当前最重要的目标：

1. 前端能选择用户自己的真实图片。
2. 图片通过 FormData 上传到本地 Python 后端。
3. 后端接收图片字节流，写入本地目录。
4. 后端使用 OpenCV fallback restorator 生成增强图。
5. 后端返回真实原图 URL 与增强图 URL。
6. 前端将任务状态变为绿色 `ready`。
7. 对比页使用真实 URL 渲染原图和增强图。

一句话目标：

让 VisualMasterPro 具备“上传真图、处理真图、查看真图对比”的完整本地闭环。

---

## 2. 本轮已完成重构

### 2.1 启动页结构与主标题

文件：

- `src/LaunchPage.jsx`

已完成：

- 启动页保持“上字下板”结构。
- 主标题已从“原图忠实增强”调整为：

```text
高清交付引擎
```

- 主标题保持单行横向排版。
- 标题使用冰晶渐变、文字描边、多重 text-shadow。
- 四个环境自检面板横向平铺：
  - Runtime
  - Paths
  - Dependencies
  - Models
- 自检全部完成后，保持 2 秒高亮状态，然后自动进入 Dashboard。

### 2.2 工作台参数化文案

文件：

- `src/DashboardPage.jsx`

当前状态：

- `PHYSICAL CONTRACT` 已改为 `OUTPUT PARAMETERS`
- `输出物理契约` 已改为 `输出图片参数`
- `当前契约：` 已改为 `当前参数：`
- 前端上传成功后，任务列表状态写入：

```text
ready
```

注意：该部分已经在上一轮完成，本轮无需重复改动。

### 2.3 后端上传链路重构

文件：

- `backend/restoration_server.py`

已完成：

- 后端从 Flask 服务层升级为 FastAPI 服务层。
- 已使用 `CORSMiddleware` 配置跨域。
- 允许前端来源：

```text
http://localhost:5173
http://127.0.0.1:5173
```

- `/api/upload` 已支持真实 multipart/form-data 图片上传。
- 上传文件保存到：

```text
backend/backend_uploads/
```

- 增强输出保存到：

```text
backend/backend_restored/
```

- 静态访问路径：

```text
/api/file/uploads/<filename>
/api/file/outputs/<filename>
```

---

## 3. 当前后端 API 契约

### 3.1 健康检查

```http
GET /api/health
```

返回结构：

```json
{
  "success": true,
  "data": {
    "name": "VisualMasterPro Realtime Restoration Backend",
    "version": "VisualMasterPro V0.3",
    "streamEndpoint": "/api/stream",
    "restoreEndpoint": "/api/restore",
    "uploadEndpoint": "/api/upload",
    "restorator": "OpenCV lightweight fallback",
    "logLines": 11
  }
}
```

### 3.2 图片上传与增强

```http
POST /api/upload
Content-Type: multipart/form-data
```

FormData 字段：

- `file`：用户选择的真实图片文件
- `mode`：默认 `fidelity`
- `scale`：默认 `2`
- `format`：默认 `png`

返回结构：

```json
{
  "status": "success",
  "filename": "高清测试.png",
  "url": "/api/file/uploads/高清测试.png",
  "success": true,
  "data": {
    "fileName": "高清测试.png",
    "mode": "fidelity",
    "originalPath": "D:\\Codex\\04_Visual-Master-Pro\\backend\\backend_uploads\\高清测试.png",
    "outputPath": "D:\\Codex\\04_Visual-Master-Pro\\backend\\backend_restored\\高清测试_vmp_backend_restored.png",
    "originalUrl": "/api/file/uploads/高清测试.png",
    "enhancedUrl": "/api/file/outputs/高清测试_vmp_backend_restored.png",
    "sourceWidth": 120,
    "sourceHeight": 80,
    "width": 240,
    "height": 160,
    "scale": 2,
    "format": "png",
    "qualityFlag": "有效清晰增强"
  }
}
```

前端当前会把返回 URL 拼接为：

```js
originalUrl: `${API_BASE}${payload.data.originalUrl}`
enhancedUrl: `${API_BASE}${payload.data.enhancedUrl}`
```

其中：

```js
const API_BASE = "http://127.0.0.1:8787";
```

### 3.3 静态图片读取

```http
GET /api/file/uploads/<filename>
GET /api/file/outputs/<filename>
```

路径映射：

- `/api/file/uploads` -> `backend/backend_uploads`
- `/api/file/outputs` -> `backend/backend_restored`

### 3.4 SSE 实时日志

```http
GET /api/stream
```

事件类型：

```text
restoration.log
```

返回为标准 SSE：

```text
event: restoration.log
data: {"index":1,"total":11,"message":"SSE CONNECTED /task/task_vmp_v03_core/stream","timestamp":"...","done":false}
```

---

## 4. 当前前端五页闭环

当前路由状态机仍是五页闭环：

```text
launch
  -> dashboard
  -> task_detail
  -> image_compare
  -> quality_report
  -> dashboard
```

核心文件：

- `src/App.jsx`
- `src/LaunchPage.jsx`
- `src/DashboardPage.jsx`
- `src/TaskDetailPage.jsx`
- `src/ImageComparePage.jsx`
- `src/QualityReportPage.jsx`

当前真实数据链路：

1. `DashboardPage` 点击“添加图片”。
2. 前端选择本地图片。
3. 前端构造 `FormData`。
4. 请求 `POST http://127.0.0.1:8787/api/upload`。
5. 后端返回 `originalUrl` 和 `enhancedUrl`。
6. `DashboardPage` 将该行状态设置为 `ready`。
7. `App.jsx` 保存 `compareAssets`。
8. `ImageComparePage` 使用真实 URL 渲染对比图。

---

## 5. 已验证结果

本轮本地验证结果：

- 后端基础测试通过。
- FastAPI `/api/upload` 模拟上传通过。
- CORS 来源返回正常：

```text
http://localhost:5173
```

- 上传原图 URL 可访问：

```text
/api/file/uploads/高清测试.png
```

- 增强输出 URL 可访问：

```text
/api/file/outputs/高清测试_vmp_backend_restored.png
```

- 前端 Vite 构建通过。

---

## 6. 当前依赖变化

文件：

- `requirements.txt`

新增依赖：

```text
fastapi>=0.115
uvicorn>=0.30
python-multipart>=0.0.9
httpx>=0.28
```

保留依赖：

```text
numpy>=2.0
opencv-python-headless>=4.10
Flask>=3.0
Flask-Cors>=4.0
```

说明：

- 当前服务实际入口已切换到 FastAPI。
- Flask 依赖暂时保留，是为了避免历史兼容脚本立刻断裂；后续可清理。

---

## 7. 当前文件管理变化

文件：

- `.gitignore`

新增忽略：

```text
backend/backend_uploads/
backend/backend_restored/
```

目的：

- 避免用户真实上传图片进入 Git。
- 避免增强输出测试图进入 Git。

---

## 8. 启动方式

### 8.1 启动后端

推荐：

```powershell
python -m backend.restoration_server --host 127.0.0.1 --port 8787
```

在 Codex bundled Python 环境：

```powershell
& "C:\Users\xyppt\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m backend.restoration_server --host 127.0.0.1 --port 8787
```

### 8.2 启动前端

推荐：

```powershell
npm run dev
```

如果 `npm` 不在 PATH：

```powershell
& "C:\Users\xyppt\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" .\node_modules\vite\bin\vite.js --host 127.0.0.1 --port 5173
```

前端访问：

```text
http://localhost:5173
```

---

## 9. 请 Gemini 下一步重点处理

请 Gemini 基于当前真实链路继续优化，不要破坏现有工程结构。

优先任务：

1. `TaskDetailPage` 接入真实 EventSource：

```js
new EventSource("http://127.0.0.1:8787/api/stream")
```

2. `ImageComparePage` 的放大镜应显示真实上传图片局部，而不是抽象纹理。
3. `DashboardPage` 增加真实缩略图和多图上传队列。
4. 上传失败时提供清晰中文错误：
   - 后端未启动
   - 图片格式不支持
   - 跨域失败
   - 输出文件无法访问
5. `QualityReportPage` 后续接收真实质量指标，不再只依赖 mockReportData。

---

## 10. 不允许破坏的链路

以下内容不能被重写成纯 Mock：

- `DashboardPage` 的 `FormData` 上传逻辑
- `/api/upload`
- `compareAssets.originalUrl`
- `compareAssets.enhancedUrl`
- `/api/file/uploads`
- `/api/file/outputs`
- `ImageComparePage` 对真实图片 URL 的渲染

---

## 11. 当前最高优先级

当前最高优先级不是继续增加页面，而是稳定真实闭环：

```text
选择本地图片
  -> 上传到 Python 后端
  -> 后端生成增强图
  -> 前端显示 ready
  -> 滑杆页真实对比原图和增强图
```

最终体验标准：

用户不需要命令行理解细节，只需要打开前端、添加图片、等待 ready、查看对比。
