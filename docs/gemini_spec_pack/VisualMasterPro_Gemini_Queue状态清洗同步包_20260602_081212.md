# VisualMasterPro 给 Gemini 的 Queue 状态清洗同步包

同步时间：2026-06-02 08:12:12  
本地项目路径：D:\Codex\04_Visual-Master-Pro  
GitHub 仓库：https://github.com/xyaippt-create/xyai.git  
当前 Git 提交：a97750a  
重要说明：本文档记录的是当前本地最新改动，尚未提交到 GitHub。

---

## 1. 本轮核心修复

本轮修复对象：

- `src/DashboardPage.jsx`

修复目标：

彻底清理工作台待处理列表 Queue 区域的状态显示问题，避免上传成功后仍然视觉上显示“上传中”的假象。

---

## 2. 问题诊断

当前前后端真实数据链路已经打通：

```text
前端 FormData 上传
  -> FastAPI /api/upload
  -> 后端写入 backend/backend_uploads
  -> 后端生成 backend/backend_restored
  -> 返回 originalUrl / enhancedUrl
  -> 前端 compareAssets 保存真实 URL
```

但是工作台列表中出现了视觉层面的“上传中卡死”假象。

根本原因：

- Queue 状态列没有严格做互斥状态渲染。
- 旧状态文案和新状态文案可能在视觉层并存。
- 用户看到“上传中”和 `ready` 叠在一起，会误判为上传没有完成。

---

## 3. 已完成的前端修复

文件：

```text
src/DashboardPage.jsx
```

新增了状态渲染函数：

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

状态列现在使用：

```jsx
<span>{renderStatus(image.status)}</span>
```

状态显示规则：

- `uploading`：只显示黄色 `正在上传...`
- `ready`：只显示绿色加粗 `ready`
- `fail`：只显示红色 `上传失败`
- 其他状态：显示灰色等待态

关键原则：

```text
同一个状态单元格内，任何时刻只能显示一个状态文案。
```

---

## 4. 失败状态同步

在上传失败 catch 分支中已补充：

```jsx
setImages((prev) =>
  prev.map((item) =>
    item.name === file.name && item.status === "uploading"
      ? { ...item, status: "fail" }
      : item
  )
);
```

作用：

- 后端未启动时，该行不会永久停留在 `uploading`。
- 网络错误或 CORS 异常时，该行会明确变成 `fail`。
- 用户能直接知道是失败，而不是误以为还在上传。

---

## 5. 当前已验证

已执行前端构建：

```text
Vite build passed
```

说明：

- JSX 结构完整。
- Tailwind 类名正常。
- DashboardPage 状态渲染补丁没有引入阻断型错误。

---

## 6. 当前仍未提交的本地变更

当前本地还有以下未提交改动：

- `.gitignore`
- `backend/restoration_server.py`
- `requirements.txt`
- `src/DashboardPage.jsx`
- `src/LaunchPage.jsx`
- `docs/gemini_spec_pack/VisualMasterPro_Gemini_前后端焊死同步包_20260602_080153.md`
- `docs/gemini_spec_pack/VisualMasterPro_Gemini_工程同步包_20260602.md`
- `docs/gemini_spec_pack/VisualMasterPro_Gemini_Queue状态清洗同步包_20260602_081212.md`

这些改动包含：

- FastAPI 后端重构
- CORSMiddleware 跨域配置
- `/api/upload` 真实上传链路
- `/api/file/uploads` 与 `/api/file/outputs` 静态路径
- 启动页“高清交付引擎”冰玉微立体标题
- Dashboard 三栏等高布局
- Queue 状态互斥清洗

---

## 7. 给 Gemini 的下一步建议

请 Gemini 基于当前本地最新逻辑继续做前端优化时，遵守以下规则：

1. 不要再把 Queue 状态列写回简单的 `{image.status}`。
2. 必须保留互斥状态渲染函数 `renderStatus(status)`。
3. `ready` 状态必须清晰、独占、绿色。
4. `uploading` 和 `ready` 不能出现在同一个单元格。
5. 不要破坏 `FormData.append("file", file)`。
6. 不要破坏 `mode / scale / format` 默认参数。
7. 不要把真实上传链路改回 Mock。

---

## 8. 当前最高优先级

下一步建议优先处理：

1. `TaskDetailPage` 接入真实 SSE `/api/stream`。
2. `ImageComparePage` 放大镜改为真实图片局部放大。
3. `DashboardPage` 增加真实缩略图。
4. `DashboardPage` 支持多图上传进度。
5. `QualityReportPage` 接入真实 quality metrics。

当前最重要的产品体验标准：

```text
用户添加图片后，Queue 状态必须明确从“正在上传...”切换为绿色 ready。
```
