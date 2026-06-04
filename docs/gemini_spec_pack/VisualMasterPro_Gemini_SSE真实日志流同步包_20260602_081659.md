# VisualMasterPro 给 Gemini 的 SSE 真实日志流同步包

同步时间：2026-06-02 08:16:59  
本地项目路径：D:\Codex\04_Visual-Master-Pro  
GitHub 仓库：https://github.com/xyaippt-create/xyai.git  
当前 Git 提交：a97750a  
重要说明：本文档记录的是当前本地最新改动，尚未提交到 GitHub。

---

## 1. 本轮总装目标

本轮目标是把 VisualMasterPro V0.3 的前后端真实链路进一步焊死：

- 前端网络域统一为 `localhost`
- 工作台上传继续使用真实 FormData
- Queue 状态继续保持互斥显示
- 任务详情页废除模拟日志
- 任务详情页接入后端真实 SSE 日志流
- 后端 CORS 补齐 localhost 与 127.0.0.1 两套来源

一句话目标：

```text
用户上传真图后，进入任务详情页时，日志不再是假跑，而是由后端 /api/stream 真实推送。
```

---

## 2. 前端网络域统一

文件：

```text
src/DashboardPage.jsx
src/TaskDetailPage.jsx
```

已将前端后端基准地址统一为：

```js
const API_BASE = "http://localhost:8787";
```

已替换旧地址：

```text
http://127.0.0.1:8787
```

目的：

- 统一浏览器访问域
- 降低跨端口本地请求的拦截概率
- 让上传接口与 SSE 接口使用同一套来源策略

---

## 3. DashboardPage 当前状态

文件：

```text
src/DashboardPage.jsx
```

当前上传接口：

```js
fetch(`${API_BASE}/api/upload`, {
  method: "POST",
  body: formData
});
```

FormData 字段保持：

```js
formData.append("file", file);
formData.append("mode", uploadMode);
formData.append("scale", uploadScale);
formData.append("format", uploadFormat);
```

默认兜底：

```js
const uploadMode = activeMode || "fidelity";
const uploadScale = scale || "2";
const uploadFormat = format || "png";
```

状态列继续保持互斥渲染：

```jsx
uploading -> 正在上传...
ready -> ready
fail -> 上传失败
```

注意：

不要把状态列改回 `{image.status}`，否则会重新引入“上传中”和 `ready` 重叠的视觉假象。

---

## 4. TaskDetailPage 已接入真实 SSE

文件：

```text
src/TaskDetailPage.jsx
```

已删除原模拟日志滚动逻辑：

```text
setInterval / setTimeout 假跑日志
```

已改为原生 EventSource：

```js
const eventSource = new EventSource(`${API_BASE}/api/stream`);
```

监听事件类型：

```js
eventSource.addEventListener("restoration.log", (event) => {
  const payload = JSON.parse(event.data);
});
```

后端 payload 字段：

```json
{
  "index": 1,
  "total": 11,
  "message": "SSE CONNECTED /task/task_vmp_v03_core/stream",
  "timestamp": "2026-06-02T00:00:00",
  "done": false
}
```

前端处理逻辑：

- 将 `payload.message` 追加到日志列表
- 使用 `payload.index / payload.total` 计算进度
- 进度条按真实日志包推进
- `payload.done === true` 或 `index >= total` 时关闭 SSE
- SSE 完成后将 `taskStatus` 设为 `completed`
- 只有 `completed` 后，“进入 8K 滑杆对比”按钮才解锁

---

## 5. 任务详情页按钮解锁逻辑

当前按钮文案：

```text
进入 8K 滑杆对比
```

按钮状态：

```jsx
disabled={taskStatus !== "completed"}
```

完成后样式：

- 极光青蓝色
- 呼吸动效
- 可点击进入 `image_compare`

未完成时：

- 不可点击
- 低透明
- 不允许提前进入对比页

---

## 6. 后端 CORS 已补齐

文件：

```text
backend/restoration_server.py
```

当前允许来源：

```python
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:8787",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8787",
]
```

当前中间件：

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

说明：

- `localhost:5173` 用于 Vite 前端开发服务。
- `localhost:8787` 用于后端同源或未来内置页面。
- `127.0.0.1` 两项保留兼容。

---

## 7. 已验证结果

本轮已完成以下验证：

### 7.1 前端构建

```text
Vite build passed
```

说明：

- React JSX 结构无阻断错误。
- TaskDetailPage 的 EventSource 代码可正常构建。

### 7.2 后端基础测试

```text
实时修复后端基础测试通过
```

说明：

- 11 行 SSE 日志仍然存在。
- `lightweight_restorator` 基础输出正常。

### 7.3 上传接口模拟

验证结果：

```text
POST /api/upload -> 200
Access-Control-Allow-Origin -> http://localhost:5173
originalUrl -> /api/file/uploads/localhost测试.png
enhancedUrl -> /api/file/outputs/localhost测试_vmp_backend_restored.png
GET enhancedUrl -> 200
```

### 7.4 SSE 接口模拟

验证结果：

```text
GET /api/stream?delay=0 -> 200
Access-Control-Allow-Origin -> http://localhost:5173
event: restoration.log
data: {"index":1,"total":11,...}
```

并确认：

```text
restoration.log 存在
任务完成 存在
```

---

## 8. 当前本地未提交变更

当前本地仍有以下未提交内容：

```text
.gitignore
backend/restoration_server.py
requirements.txt
src/DashboardPage.jsx
src/LaunchPage.jsx
src/TaskDetailPage.jsx
docs/gemini_spec_pack/*.md
```

其中包含：

- FastAPI 后端重构
- CORS 补齐
- localhost 统一
- Dashboard 三栏布局
- Queue 状态互斥
- LaunchPage 冰玉微立体标题
- TaskDetailPage 真实 SSE 日志流
- Gemini 同步包

---

## 9. 给 Gemini 的下一步任务

请 Gemini 在当前基础上继续优化时，重点处理以下内容：

1. 让 `TaskDetailPage` 的日志面板自动滚动到最新一行。
2. 给 SSE 连接失败增加更友好的中文提示区。
3. 将 `TaskDetailPage` 的五阶段时间线与具体日志语义进一步映射，而不是只按百分比推进。
4. 让 `ImageComparePage` 的放大镜显示真实图片局部，而不是抽象纹理。
5. 给 `DashboardPage` 队列增加真实缩略图。
6. 给上传队列增加多文件进度和失败重试。

---

## 10. 不允许破坏的链路

以下内容必须保留：

- `const API_BASE = "http://localhost:8787"`
- `formData.append("file", file)`
- `formData.append("mode", uploadMode)`
- `formData.append("scale", uploadScale)`
- `formData.append("format", uploadFormat)`
- `renderStatus(status)` 互斥状态渲染
- `new EventSource(`${API_BASE}/api/stream`)`
- `eventSource.addEventListener("restoration.log", ...)`
- `/api/upload`
- `/api/stream`
- `/api/file/uploads`
- `/api/file/outputs`

---

## 11. 当前产品闭环标准

当前标准闭环：

```text
启动页自检
  -> 自动进入工作台
  -> 添加真实图片
  -> 后端处理并返回 URL
  -> Queue 显示 ready
  -> 进入任务详情页
  -> 后端 SSE 真实推送日志
  -> 日志完成后解锁 8K 对比
  -> 滑杆页显示真实原图和增强图
```

核心体验判断：

用户看到的任务日志必须是真实后端流式数据，不再是前端假跑动画。
