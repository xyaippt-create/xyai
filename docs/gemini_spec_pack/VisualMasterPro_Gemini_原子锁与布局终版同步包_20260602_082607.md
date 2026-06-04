# VisualMasterPro 给 Gemini 的原子锁与布局终版同步包

同步时间：2026-06-02 08:26:07  
本地项目路径：D:\Codex\04_Visual-Master-Pro  
GitHub 仓库：https://github.com/xyaippt-create/xyai.git  
当前 Git 提交：a97750a  
重要说明：本文档记录的是当前本地最新改动，尚未提交到 GitHub。

---

## 1. 本轮总装目标

本轮针对 VisualMasterPro V0.3 的前端工作台与真实数据流做最终收口：

- 启动页主标题维持冰玉微立体，不使用强霓虹发光。
- 工作台三栏高度拉平，修复中栏底部塌陷。
- 工作台圆角整体收紧，降低肥厚钝感。
- 上传链路加入原子锁与 AbortController，防止重复触发。
- TaskDetailPage 的真实 SSE 日志面板支持自动滚动到底。
- 后端 CORS 和 localhost 链路再次验证通过。

---

## 2. 启动页当前状态

文件：

```text
src/LaunchPage.jsx
```

当前主标题：

```text
高清交付引擎
```

当前标题样式：

```jsx
className="relative z-10 flex flex-row items-center justify-center whitespace-nowrap bg-gradient-to-b from-white via-slate-100 to-emerald-50/20 bg-clip-text text-4xl font-black leading-none tracking-[0.18em] text-transparent md:text-5xl"
style={{
  WebkitTextStroke: "0.7px rgba(255, 255, 255, 0.72)",
  textShadow: "0 1px 0 #ffffff, 0 2px 1px rgba(0,0,0,0.4), 0 4px 6px rgba(0,0,0,0.15)"
}}
```

保留逻辑：

- 环境自检全绿。
- 原地定格 2 秒。
- 页面淡出。
- 自动进入工作台。

注意：

不要再加入大面积霓虹外发光、强 blur 光晕或高亮滤镜。

---

## 3. Dashboard 三栏布局最终状态

文件：

```text
src/DashboardPage.jsx
```

三栏外层当前结构：

```jsx
<div className="grid w-full grid-cols-1 items-stretch gap-8 min-h-[calc(100vh-180px)] lg:grid-cols-3">
```

中栏当前结构：

```jsx
<div className="flex h-full flex-col justify-between gap-6">
```

目标效果：

- 左栏：Input Field + Restoration Modes
- 中栏：Queue + Execution
- 右栏：Output Parameters + Pipeline
- 三栏底部视觉对齐。
- 中栏不再出现底部塌陷坑。
- Queue 卡片有足够高度承载空状态或上传列表。

---

## 4. 工作台圆角收紧

文件：

```text
src/DashboardPage.jsx
```

本轮已将工作台内部主要面板外层圆角从大圆角降档为：

```text
rounded-lg
rounded-md
```

已处理区域：

- 图片拖拽导入卡片
- 待处理列表卡片
- 待处理列表内框
- 四大增强模式卡片
- 输出图片参数卡片
- 参数选择框
- 参数提示框
- 准备执行卡片
- 状态映射卡片
- 状态映射行

设计目的：

- 降低圆润肥厚感。
- 提升精密仪器感。
- 让边框和卡片转角更利落。

---

## 5. 上传链路原子锁

文件：

```text
src/DashboardPage.jsx
```

新增锁：

```jsx
const isUploadingRef = useRef(false);
const uploadAbortRef = useRef(null);
```

上传入口防重复：

```jsx
if (isUploadingRef.current) {
  setUploadState({ message: "已有上传任务正在执行，请等待当前任务完成。", error: false });
  return;
}
```

上传开始：

```jsx
isUploadingRef.current = true;
uploadAbortRef.current?.abort();
uploadAbortRef.current = new AbortController();
```

fetch 绑定 signal：

```jsx
const response = await fetch(`${API_BASE}/api/upload`, {
  method: "POST",
  body: formData,
  signal
});
```

上传完成或失败后释放：

```jsx
finally {
  isUploadingRef.current = false;
  uploadAbortRef.current = null;
}
```

目的：

- 防止 React StrictMode 或用户快速点击造成重复上传。
- 避免同一批文件并发触发造成状态假死。
- 保证一次只存在一个合法上传通道。

---

## 6. FormData 与 localhost 链路

文件：

```text
src/DashboardPage.jsx
```

当前 API 基准：

```jsx
const API_BASE = "http://localhost:8787";
```

FormData 字段：

```jsx
formData.append("file", file);
formData.append("mode", uploadMode);
formData.append("scale", uploadScale);
formData.append("format", uploadFormat);
```

默认参数：

```jsx
const uploadMode = activeMode || "fidelity";
const uploadScale = scale || "2";
const uploadFormat = format || "png";
```

注意：

不要改回 `127.0.0.1`。
不要把 `file` 字段改成 `image`、`img` 或其他键名。

---

## 7. Queue 状态互斥渲染

文件：

```text
src/DashboardPage.jsx
```

当前状态渲染函数：

```jsx
const renderStatus = (status) => {
  if (status === "uploading") {
    return <span className="whitespace-nowrap text-yellow-400 font-medium">正在上传...</span>;
  }
  if (status === "ready") {
    return <span className="whitespace-nowrap text-emerald-400 font-bold animate-pulse">ready</span>;
  }
  if (status === "fail") {
    return <span className="whitespace-nowrap text-rose-500 font-medium">上传失败</span>;
  }
  return <span className="whitespace-nowrap text-white/42">{status || "等待"}</span>;
};
```

渲染位置：

```jsx
<span>{renderStatus(image.status)}</span>
```

禁止：

- 禁止改回 `{image.status}`。
- 禁止让 “正在上传...” 和 `ready` 同时出现在一个单元格。

---

## 8. TaskDetailPage 真实 SSE 与自动滚动

文件：

```text
src/TaskDetailPage.jsx
```

当前 API 基准：

```jsx
const API_BASE = "http://localhost:8787";
```

真实 SSE：

```jsx
const eventSource = new EventSource(`${API_BASE}/api/stream`);
```

监听事件：

```jsx
eventSource.addEventListener("restoration.log", (event) => {
  const payload = JSON.parse(event.data);
});
```

日志追加：

```jsx
setLogs((prev) => [...prev, message]);
```

进度驱动：

```jsx
const nextProgress = total > 0 ? Math.round((index / total) * 100) : 0;
setProgress(Math.min(100, nextProgress));
```

完成关闭：

```jsx
if (payload.done === true || index >= total) {
  eventSource.close();
  setCurrentStageIndex(stages.length);
  setProgress(100);
  setTaskStatus("completed");
}
```

---

## 9. 日志面板自动滚动到底

文件：

```text
src/TaskDetailPage.jsx
```

新增：

```jsx
const logEndRef = useRef(null);

useEffect(() => {
  logEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
}, [logs]);
```

日志容器：

```jsx
<div className="h-[27rem] overflow-y-auto ...">
```

尾部锚点：

```jsx
<div ref={logEndRef} />
```

作用：

- 后端每推一条 SSE 日志，前端自动滚动到最新一行。
- 用户不需要手动滚动日志窗口。

---

## 10. 后端 CORS 当前状态

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

---

## 11. 已验证结果

本轮完成后已验证：

```text
Vite build passed
后端基础测试通过
POST /api/upload -> 200
Access-Control-Allow-Origin -> http://localhost:5173
GET /api/stream?delay=0 -> 200
event: restoration.log
任务完成 存在
```

上传模拟返回：

```text
/api/file/uploads/原子锁测试.png
/api/file/outputs/原子锁测试_vmp_backend_restored.png
```

---

## 12. 当前本地未提交变更

当前仍未提交到 GitHub 的内容：

```text
.gitignore
backend/restoration_server.py
requirements.txt
src/DashboardPage.jsx
src/LaunchPage.jsx
src/TaskDetailPage.jsx
docs/gemini_spec_pack/*.md
```

当前 GitHub 最新提交仍是：

```text
a97750a
```

---

## 13. Gemini 下一步建议

请 Gemini 下一步只做增强，不要破坏现有真实链路。

建议优先级：

1. ImageComparePage 放大镜显示真实图片局部，而不是抽象纹理。
2. DashboardPage 增加真实上传缩略图。
3. Queue 增加失败重试按钮。
4. TaskDetailPage 将五阶段时间线与具体 SSE 日志语义精确映射。
5. QualityReportPage 接入后端真实质量指标。

---

## 14. 不允许破坏的关键点

必须保留：

- `const API_BASE = "http://localhost:8787"`
- `isUploadingRef`
- `uploadAbortRef`
- `formData.append("file", file)`
- `formData.append("mode", uploadMode)`
- `formData.append("scale", uploadScale)`
- `formData.append("format", uploadFormat)`
- `renderStatus(status)`
- `new EventSource(`${API_BASE}/api/stream`)`
- `eventSource.addEventListener("restoration.log", ...)`
- 日志自动滚动到底
- 后端 CORS 四个来源

当前产品闭环标准：

```text
添加图片 -> 上传唯一通道 -> Queue ready -> 真实 SSE 日志 -> 日志完成解锁 8K 对比
```
