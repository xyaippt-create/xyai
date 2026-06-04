# VisualMasterPro 给 Gemini 的 XHR 上传与转场终版同步包

同步时间：2026-06-04 13:47:03  
本地项目路径：D:\Codex\04_Visual-Master-Pro  
GitHub 仓库：https://github.com/xyaippt-create/xyai.git  
当前 GitHub 最新提交：a97750a  
重要说明：本文档记录的是当前本地最新改动，尚未提交到 GitHub。

---

## 1. 本轮任务完成状态

本轮任务已经执行完成。

已完成内容：

- 启动页双向转场动画
- 启动页自检完成后零延迟离场
- 启动页 `transitionend` 后再切换路由
- 工作台入场 `fadeInUp` 动画
- 上传链路从 `fetch` 改为原生 `XMLHttpRequest`
- 上传进度条接入 `xhr.upload.onprogress`
- 外部全局单例锁 `GLOBAL_IS_UPLOADING`
- 外部全局 XHR 引用 `GLOBAL_UPLOAD_XHR`
- 文件选择事件立即硬拷贝 `event.currentTarget.files`
- Queue 状态列显示上传百分比和 2px 极细进度条
- 五页统一底部版权声明
- 前端构建验证通过

---

## 2. 启动页 LaunchPage 当前状态

文件：

```text
src/LaunchPage.jsx
```

当前主标题：

```text
高清交付引擎
```

当前主标题视觉：

```jsx
bg-gradient-to-b from-white via-slate-100 to-emerald-50/20
textShadow: "0 1px 0 #ffffff, 0 2px 1px rgba(0,0,0,0.4), 0 4px 6px rgba(0,0,0,0.15)"
```

当前启动页外层容器：

```jsx
className={`relative h-screen w-screen overflow-hidden flex flex-col justify-between p-6 bg-[#090e10] text-slate-100 select-none transition-all duration-700 ease-out transform ${isExiting ? "opacity-0 -translate-y-4 pointer-events-none scale-98" : "opacity-100 translate-y-0"}`}
```

当前逻辑：

1. 页面挂载后自检面板运行。
2. 自检全部完成后立即设置 `isExiting = true`。
3. 启动页播放离场动画。
4. `transitionend` 触发后调用 `onEnter(snapshot)`。
5. App 状态机切换到 Dashboard。

注意：

- 已移除 2 秒等待。
- 不再硬切路由。
- 路由切换被延后到离场动画结束时执行。

---

## 3. DashboardPage 当前转场状态

文件：

```text
src/DashboardPage.jsx
```

工作台外层容器已改为：

```jsx
className="relative h-screen w-screen overflow-hidden flex flex-col justify-between p-6 bg-[#090e10] text-slate-100 select-none animate-[fadeInUp_0.6s_ease-out_both] opacity-0 translate-y-2"
```

目标效果：

- 承接 LaunchPage 离场。
- Dashboard 挂载时轻微上移渐显。
- 保持一屏无滚动条体验。

---

## 4. 新增全局动画

文件：

```text
src/index.css
```

新增 `fadeInUp`：

```css
@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translate3d(0, 0.75rem, 0);
  }
  to {
    opacity: 1;
    transform: translate3d(0, 0, 0);
  }
}
```

新增 `scale-98` 工具类：

```css
@layer utilities {
  .scale-98 {
    --tw-scale-x: 0.98;
    --tw-scale-y: 0.98;
    transform: translate(var(--tw-translate-x), var(--tw-translate-y)) rotate(var(--tw-rotate)) skewX(var(--tw-skew-x)) skewY(var(--tw-skew-y)) scaleX(var(--tw-scale-x)) scaleY(var(--tw-scale-y));
  }
}
```

---

## 5. Dashboard 上传链路已改为 XHR

文件：

```text
src/DashboardPage.jsx
```

当前上传链路已经从 `fetch` 改为：

```js
const xhr = new XMLHttpRequest();
GLOBAL_UPLOAD_XHR = xhr;
xhr.open("POST", `${API_BASE}/api/upload`, true);
xhr.send(formData);
```

当前 API 基准：

```js
const API_BASE = "http://localhost:8787";
```

没有使用：

```text
http://127.0.0.1:8787
```

---

## 6. 外部全局单例锁

文件：

```text
src/DashboardPage.jsx
```

组件外部新增：

```js
let GLOBAL_IS_UPLOADING = false;
let GLOBAL_UPLOAD_XHR = null;
```

作用：

- 脱离 React 生命周期。
- 避免 StrictMode 双触发。
- 避免布局重绘导致并发请求。
- 避免上传通道假死。

并发拦截逻辑：

```js
if (GLOBAL_IS_UPLOADING) {
  console.warn("[Global Singleton Lock] 成功拦截并发高频请求，主通道安全通车");
  return;
}
```

---

## 7. 文件选择事件硬拷贝

文件：

```text
src/DashboardPage.jsx
```

当前 input onChange 桥接：

```js
const handleInputChange = (event) => {
  const selectedFiles = Array.from(event.currentTarget.files || []);
  onFiles(selectedFiles);
  event.currentTarget.value = "";
};
```

作用：

- 在事件触发瞬间复制文件数组。
- 不依赖异步后的原生事件指针。
- 避免 `event.target.files` 被浏览器重绘清空。

---

## 8. FormData 字段契约

当前 FormData：

```js
const formData = new FormData();
formData.append("file", shadowFile);
formData.append("mode", uploadMode);
formData.append("scale", uploadScale);
formData.append("format", uploadFormat);
```

默认参数：

```js
const uploadMode = activeMode || "fidelity";
const uploadScale = scale || "2";
const uploadFormat = format || "png";
```

禁止修改：

- `file` 不能改成 `image`
- `file` 不能改成 `img`
- `localhost:8787` 不能改回 `127.0.0.1:8787`

---

## 9. 上传进度条

文件：

```text
src/DashboardPage.jsx
```

新增状态：

```js
const [uploadProgress, setUploadProgress] = useState(0);
```

XHR 进度监听：

```js
xhr.upload.onprogress = (event) => {
  if (event.lengthComputable) {
    const percentComplete = Math.round((event.loaded / event.total) * 100);
    setUploadProgress(percentComplete);
  }
};
```

Queue 状态列显示：

```jsx
<span className="whitespace-nowrap text-xs font-medium text-yellow-400">
  正在上传... {uploadProgress}%
</span>
<div className="mt-1 h-[2px] w-full overflow-hidden rounded-full bg-white/5">
  <div
    className="h-full bg-gradient-to-r from-emerald-500 to-cyan-400 transition-all duration-200 ease-out"
    style={{ width: `${uploadProgress}%` }}
  />
</div>
```

状态显示规则：

- `uploading`：显示正在上传和百分比进度条
- `ready`：显示绿色 `ready`
- `fail`：显示上传失败
- 其他：显示等待

---

## 10. 上传成功后数据链路

XHR 成功后解析：

```js
const payload = JSON.parse(xhr.responseText);
```

成功条件：

```js
payload.status === "success" || payload.success === true
```

写入真实对比数据：

```js
const data = {
  ...payload.data,
  originalUrl: `${API_BASE}${payload.data.originalUrl}`,
  enhancedUrl: `${API_BASE}${payload.data.enhancedUrl}`
};

onUploadComplete?.(data);
```

Queue 状态跳转：

```js
status: "ready"
```

上传通道释放：

```js
GLOBAL_IS_UPLOADING = false;
GLOBAL_UPLOAD_XHR = null;
```

---

## 11. 五页底部版权声明

当前五页都已注入：

```text
© 2026 雪原系统. 保留所有权利。 V0.3 CORE Restorator Pipeline
```

涉及文件：

- `src/LaunchPage.jsx`
- `src/DashboardPage.jsx`
- `src/TaskDetailPage.jsx`
- `src/ImageComparePage.jsx`
- `src/QualityReportPage.jsx`

---

## 12. 已验证结果

已执行：

```text
Vite build passed
```

说明：

- React JSX 构建通过。
- XHR 上传逻辑编译通过。
- 转场动画 class 构建通过。
- `fadeInUp` 和 `scale-98` 已被前端识别。

---

## 13. 当前本地未提交状态

当前 GitHub 最新提交仍是：

```text
a97750a
```

当前本地未提交文件包括：

```text
.gitignore
backend/restoration_server.py
requirements.txt
src/DashboardPage.jsx
src/ImageComparePage.jsx
src/LaunchPage.jsx
src/QualityReportPage.jsx
src/TaskDetailPage.jsx
src/index.css
docs/gemini_spec_pack/*.md
```

---

## 14. Gemini 下一步建议

请 Gemini 后续基于当前状态继续优化时，重点注意：

1. 不要把 XHR 上传改回 fetch。
2. 不要移除外部全局单例锁。
3. 不要移除 `uploadProgress`。
4. 不要改动 `file / mode / scale / format` 字段契约。
5. 不要把 `localhost:8787` 改回 `127.0.0.1:8787`。
6. 可继续优化：ImageComparePage 的真实图片放大镜。
7. 可继续优化：Dashboard 的缩略图队列。
8. 可继续优化：TaskDetailPage 的 SSE 阶段语义映射。

当前核心闭环：

```text
启动页自检 -> 离场动画 -> 工作台入场 -> XHR 上传真图 -> 进度条 -> ready -> 真实 SSE -> 8K 对比
```
