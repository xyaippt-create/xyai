import React, { useEffect, useMemo, useRef, useState } from "react";
import TaskDetailPage from "./TaskDetailPage.jsx";
import ImageSliderComparePage from "./ImageSliderComparePage.jsx";
import QualityReportPage from "./QualityReportPage.jsx";

const API_BASE = "http://localhost:8787";
const OUTPUT_PROFILE = "delivery_1080p";
const DEFAULT_OUTPUT_FORMAT = "auto";
const DEFAULT_SCALE = "2";
const DEFAULT_LEGACY_FORMAT = "png";

const DECOR_LABEL = {
  color: "#6e7d80",
  fontSize: "10px",
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
};

const PANEL_STYLE = {
  backgroundColor: "#101819",
  border: "1px solid #263738",
  borderRadius: "8px",
};

const TITLE_STYLE = { color: "#f4f7f8" };

const modeCards = [
  { id: "fidelity", title: "原图忠实增强", desc: "保持构图、色彩与画风，只做高清清洁。" },
  { id: "text_safe", title: "文字安全清洁", desc: "保护小字边缘，减少压缩毛刺。" },
  { id: "texture", title: "参数纹理保持", desc: "保留材质层次，避免假锐化。" },
];

const statusText = {
  queued: "待处理",
  uploading: "上传中",
  processing: "处理中",
  completed: "已完成",
  failed: "失败",
};

const statusColor = {
  queued: "#6e7d80",
  uploading: "#f0c36f",
  processing: "#6feaf0",
  completed: "#8be6b1",
  failed: "#ff8a8a",
};

function normalizeApiUrl(url) {
  if (!url) return "";
  if (/^https?:\/\//i.test(url)) return url;
  return `${API_BASE}${url.startsWith("/") ? url : `/${url}`}`;
}

function safeText(value, fallback = "暂无数据") {
  if (value == null || value === "") return fallback;
  return value;
}

function formatFileSize(file) {
  if (!file) return "0 MB";
  return `${(file.size / 1024 / 1024).toFixed(2)} MB`;
}

function makeQueueId(file) {
  return `${Date.now()}_${Math.random().toString(16).slice(2)}_${file.name}`;
}

function extractTaskPayload(payload) {
  const data = payload?.data || payload || {};
  const task = data.task || payload?.task || {};
  const taskResult = data.task_result || payload?.task_result || task.task_result || {};
  const taskReport = data.task_report || payload?.task_report || task.task_report || {};
  const taskId = payload?.taskId || payload?.task_id || data.taskId || data.task_id || task.taskId || task.task_id;
  const finalOutputUrl =
    taskResult.final_output_url ||
    task.final_output_url ||
    data.final_output_url ||
    data.enhancedUrl ||
    payload?.final_output_url ||
    payload?.enhancedUrl;
  const originalUrl = data.originalUrl || payload?.originalUrl || task.originalUrl || taskResult.originalUrl || "";

  return {
    data,
    task,
    taskId,
    filename: payload?.filename || data.filename || data.input_filename || data.fileName || data.original_filename || task.input_filename,
    originalUrl: normalizeApiUrl(originalUrl),
    task_result: taskResult,
    task_report: taskReport,
    final_output_url: normalizeApiUrl(finalOutputUrl),
  };
}

function requestJson(method, url, body) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const shouldLogOutputDir = url.includes("/api/output/validate") || url.includes("/api/output/open") || url.includes("/api/output/select-popup");
    if (shouldLogOutputDir) {
      console.info("[VisualMasterPro output_dir] request", { method, url, body: body || null });
    }
    xhr.open(method, url, true);
    if (method !== "GET") xhr.setRequestHeader("Content-Type", "application/json;charset=UTF-8");
    xhr.onload = () => {
      let payload = {};
      try {
        payload = JSON.parse(xhr.responseText || "{}");
      } catch (error) {
        reject(new Error(`响应解析失败：${error.message}`));
        return;
      }
      if (xhr.status < 200 || xhr.status >= 300 || payload.success === false || payload.valid === false) {
        if (shouldLogOutputDir) {
          console.info("[VisualMasterPro output_dir] response", { url, status: xhr.status, payload });
        }
        reject(new Error(payload.message || payload.detail || `请求失败：HTTP ${xhr.status}`));
        return;
      }
      if (shouldLogOutputDir) {
        console.info("[VisualMasterPro output_dir] response", { url, status: xhr.status, payload });
      }
      resolve(payload);
    };
    xhr.onerror = () => reject(new Error("无法连接本地后端服务。"));
    xhr.send(method === "GET" ? null : JSON.stringify(body || {}));
  });
}

function uploadFileWithXhr(item, activeMode, requestedOutputDir, outputFormat, onProgress) {
  return new Promise((resolve, reject) => {
    const outputDirForRequest = (requestedOutputDir || "").trim();
    const formData = new FormData();
    formData.append("file", item.file);
    formData.append("mode", activeMode);
    formData.append("scale", DEFAULT_SCALE);
    formData.append("format", DEFAULT_LEGACY_FORMAT);
    formData.append("output_profile", OUTPUT_PROFILE);
    formData.append("output_format", outputFormat || DEFAULT_OUTPUT_FORMAT);
    if (outputDirForRequest) formData.append("output_dir", outputDirForRequest);
    console.info("[VisualMasterPro output_dir] upload FormData", {
      filename: item.name,
      output_dir: outputDirForRequest,
      has_output_dir: formData.has("output_dir"),
      keys: Array.from(formData.keys()),
    });

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/api/upload`, true);
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      onProgress?.(Math.max(1, Math.round((event.loaded / event.total) * 100)));
    };
    xhr.onload = () => {
      let payload = {};
      try {
        payload = JSON.parse(xhr.responseText || "{}");
      } catch (error) {
        reject(new Error(`上传响应解析失败：${error.message}`));
        return;
      }
      if (xhr.status < 200 || xhr.status >= 300 || payload.success === false) {
        reject(new Error(payload.message || payload.detail || `上传失败：HTTP ${xhr.status}`));
        return;
      }
      resolve(extractTaskPayload(payload));
    };
    xhr.onerror = () => reject(new Error("无法连接上传接口，请确认 FastAPI 服务已启动。"));
    xhr.send(formData);
  });
}

function streamTask(taskId, onLog, onProgress) {
  return new Promise((resolve, reject) => {
    if (!taskId) {
      reject(new Error("缺少任务编号，无法监听任务日志。"));
      return;
    }
    const eventSource = new EventSource(`${API_BASE}/api/v1/tasks/${encodeURIComponent(taskId)}/stream`);
    let finalPayload = {};
    let closed = false;
    const close = () => {
      if (closed) return;
      closed = true;
      eventSource.close();
    };

    eventSource.addEventListener("restoration.log", (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.message) onLog?.(payload.message);
        if (payload.total && payload.index) onProgress?.(Math.min(99, Math.round((payload.index / payload.total) * 100)));
        const extracted = extractTaskPayload(payload);
        finalPayload = {
          ...finalPayload,
          ...extracted,
          task_result: Object.keys(extracted.task_result || {}).length ? extracted.task_result : finalPayload.task_result,
          task_report: Object.keys(extracted.task_report || {}).length ? extracted.task_report : finalPayload.task_report,
        };
        if (payload.done === true) {
          close();
          if (payload.task_status === "failed") reject(new Error(payload.message || "任务处理失败。"));
          else resolve(finalPayload);
        }
      } catch (error) {
        onLog?.(`SSE 数据解析失败：${error.message}`);
      }
    });

    eventSource.onmessage = (event) => {
      if (event.data === "[DONE]") {
        close();
        resolve(finalPayload);
      }
    };

    eventSource.onerror = () => {
      close();
      reject(new Error("SSE 流式日志通道异常。"));
    };
  });
}

function StatusPill({ status }) {
  const color = statusColor[status] || "#6e7d80";
  return (
    <span
      style={{
        color,
        background: "#0d181a",
        border: `1px solid ${status === "completed" ? "#8be6b1" : status === "failed" ? "#5a2525" : "#263738"}`,
        borderRadius: "4px",
        padding: "4px 8px",
        fontSize: "10px",
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
        whiteSpace: "nowrap",
      }}
    >
      {statusText[status] || "未知"}
    </span>
  );
}

function ParameterPanel({ outputFormat }) {
  const rows = [
    { label: "交付方案", value: "高清交付 1080P" },
    { label: "目标格式", value: outputFormat === "auto" ? "智能自动选择" : `${outputFormat.toUpperCase()} 格式落盘` },
    { label: "核心基线", value: "1080P 高清稳定交付" },
    { label: "尺寸策略", value: "智能无损自适应缩放" },
  ];

  return (
    <section style={{ ...PANEL_STYLE, padding: "18px" }}>
      <p style={DECOR_LABEL}>Output Parameters</p>
      <h2 style={{ ...TITLE_STYLE, marginTop: "10px", fontSize: "21px", fontWeight: 600 }}>输出图片参数</h2>
      <div style={{ backgroundColor: "#0e1516", border: "1px solid #263738", borderRadius: "6px", padding: "14px", marginTop: "14px", display: "grid", gap: "8px" }}>
        {rows.map((row) => (
          <div key={row.label} style={{ display: "flex", alignItems: "center", fontSize: "12px", lineHeight: 1.25 }}>
            <span style={{ color: "#6feaf0", marginRight: "6px" }}>·</span>
            <span style={{ color: "#9ba9ab" }}>{row.label}：</span>
            <span style={{ color: "#f4f7f8" }}>{row.value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function makeTaskConfig(item) {
  if (!item) return null;
  return {
    taskId: item.taskId,
    task_id: item.taskId,
    streamEndpoint: item.streamEndpoint,
    fileName: item.name,
    filename: item.name,
    originalUrl: item.originalUrl,
    enhancedUrl: item.final_output_url,
    final_output_url: item.final_output_url,
    mode: item.mode,
    output_format: item.output_format,
    task_status: item.status,
    task_result: {
      ...(item.task_result || {}),
      final_output_url: item.final_output_url || item.task_result?.final_output_url || "",
      originalUrl: item.originalUrl || "",
      output_filename: item.output_filename || item.task_result?.output_filename || "",
    },
    task_report: item.task_report || {},
    debug_quality: item.debug_quality || item.task_result?.debug_quality || {},
    compareAssets: {
      taskId: item.taskId,
      fileName: item.name,
      originalUrl: item.originalUrl,
      enhancedUrl: item.final_output_url,
      final_output_url: item.final_output_url,
      mode: item.mode,
      task_result: {
        ...(item.task_result || {}),
        final_output_url: item.final_output_url || item.task_result?.final_output_url || "",
        originalUrl: item.originalUrl || "",
      },
      task_report: item.task_report || {},
    },
  };
}

export default function DashboardPage() {
  const fileInputRef = useRef(null);
  const processingRef = useRef(false);
  const [activeScreen, setActiveScreen] = useState("dashboard");
  const [activeItemId, setActiveItemId] = useState("");
  const [debugItemId, setDebugItemId] = useState("");
  const [fileQueue, setFileQueue] = useState([]);
  const [activeMode, setActiveMode] = useState("fidelity");
  const [outputFormat, setOutputFormat] = useState(DEFAULT_OUTPUT_FORMAT);
  const [appliedOutputDir, setAppliedOutputDir] = useState("");
  const [defaultOutputDir, setDefaultOutputDir] = useState("");
  const [outputDirError, setOutputDirError] = useState("");
  const [outputDirSuccess, setOutputDirSuccess] = useState("");
  const [notice, setNotice] = useState("请选择图片，或更换输出文件夹后开始处理。");
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [isProcessingQueue, setIsProcessingQueue] = useState(false);

  useEffect(() => {
    requestJson("GET", `${API_BASE}/api/health`)
      .then(async (payload) => {
        const dir = payload?.data?.default_output_dir || payload?.data?.outputDir || "";
        setDefaultOutputDir(dir);
      })
      .catch(() => setDefaultOutputDir(""));
  }, []);

  const activeItem = useMemo(() => fileQueue.find((item) => item.id === activeItemId) || fileQueue.find((item) => item.status === "processing") || fileQueue.find((item) => item.status === "completed") || null, [fileQueue, activeItemId]);
  const debugItem = useMemo(() => fileQueue.find((item) => item.id === debugItemId) || activeItem, [fileQueue, debugItemId, activeItem]);
  const completedItems = fileQueue.filter((item) => item.status === "completed");

  const updateQueueItem = (id, patch) => {
    setFileQueue((prev) => prev.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  };

  const addFiles = (incomingFiles) => {
    const images = Array.from(incomingFiles || []).filter((file) => file?.type?.startsWith("image/"));
    if (!images.length) {
      setNotice("未检测到可用图片文件。");
      return;
    }
    const nextItems = images.map((file) => ({
      id: makeQueueId(file),
      file,
      name: file.name,
      size: formatFileSize(file),
      type: file.type || "image",
      status: "queued",
      mode: activeMode,
      output_format: outputFormat,
      output_dir: appliedOutputDir,
      taskId: "",
      streamEndpoint: "",
      originalUrl: "",
      input_width: 0,
      input_height: 0,
      output_width: 0,
      output_height: 0,
      resize_policy: "",
      final_output_url: "",
      output_path: "",
      output_filename: "",
      input_path: "",
      hash_equal: null,
      pixel_diff_score: null,
      debug_timing: null,
      debug_quality: null,
      task_result: null,
      task_report: null,
      error: "",
      logs: [],
      progress: 0,
    }));
    setFileQueue((prev) => [...prev, ...nextItems]);
    if (!activeItemId && nextItems[0]) setActiveItemId(nextItems[0].id);
    setNotice(`已选择 ${fileQueue.length + nextItems.length} 张。`);
  };

  const handleFileChange = (event) => {
    addFiles(event.target.files);
    event.target.value = "";
  };

  const resolveOutputDirForRequest = () => appliedOutputDir.trim() || defaultOutputDir.trim();

  const handleSelectOutputDir = () => {
    setOutputDirError("");
    setOutputDirSuccess("");
    setNotice("正在等待本地文件夹选择。");
    requestJson("POST", `${API_BASE}/api/output/select-popup`, {})
      .then(async (payload) => {
        if (payload.status === "cancelled" || !payload.output_dir) {
          setNotice("已取消更换输出文件夹。");
          return;
        }
        const normalized = payload.output_dir || payload?.data?.normalized_path || "";
        const validatePayload = await requestJson("POST", `${API_BASE}/api/output/validate`, { output_dir: normalized });
        const checkedPath = validatePayload?.normalized_path || validatePayload?.data?.normalized_path || normalized;
        setAppliedOutputDir(checkedPath === defaultOutputDir ? "" : checkedPath);
        setOutputDirError("");
        setOutputDirSuccess(normalized === defaultOutputDir ? "✓ 已恢复默认输出位置" : "✓ 已成功绑定本地输出文件夹");
        setNotice(normalized === defaultOutputDir ? "已恢复默认输出位置。" : "已成功绑定本地输出文件夹。");
      })
      .catch((error) => {
        setOutputDirSuccess("");
        setOutputDirError(error.message || "本地文件夹选择失败。");
        setNotice("本地文件夹选择失败。");
      });
  };

  const handleOpenOutputDir = () => {
    const target = appliedOutputDir.trim() || defaultOutputDir;
    if (!target) {
      setOutputDirError("当前没有可打开的输出目录。");
      return;
    }
    requestJson("POST", `${API_BASE}/api/output/open`, { output_dir: target })
      .then((payload) => {
        setOutputDirError("");
        setOutputDirSuccess("");
        setNotice(payload.message || "已打开输出目录。");
      })
      .catch((error) => {
        setOutputDirError(error.message);
        setOutputDirSuccess("");
        setNotice(error.message);
      });
  };

  const handleResetOutputDir = () => {
    setAppliedOutputDir("");
    setOutputDirError("");
    setOutputDirSuccess("✓ 已恢复默认输出位置");
    setNotice("已恢复默认输出位置。");
  };

  const processOneItem = async (item, index, total, queueOutputDir) => {
    const activeOutputDir = (queueOutputDir || defaultOutputDir || "").trim();
    setCurrentIndex(index + 1);
    setActiveItemId(item.id);
    setActiveScreen("task_detail");
    updateQueueItem(item.id, {
      status: "uploading",
      mode: activeMode,
      output_format: outputFormat,
      output_dir: activeOutputDir,
      error: "",
      logs: ["正在确认输出目录"],
      progress: 1,
    });

    try {
      const uploadPayload = await uploadFileWithXhr(item, activeMode, activeOutputDir, outputFormat, (percent) => {
        updateQueueItem(item.id, { progress: Math.min(30, percent) });
      });
      const taskId = uploadPayload.taskId;
      if (!taskId) throw new Error("后端未返回任务编号。");

      updateQueueItem(item.id, {
        status: "processing",
        taskId,
        streamEndpoint: uploadPayload.data?.streamEndpoint || `/api/v1/tasks/${taskId}/stream`,
        originalUrl: uploadPayload.originalUrl,
        input_width: uploadPayload.data?.input_width || 0,
        input_height: uploadPayload.data?.input_height || 0,
        output_width: uploadPayload.data?.output_width || 0,
        output_height: uploadPayload.data?.output_height || 0,
        progress: 35,
        logs: ["上传完成，正在监听后端 SSE 日志。"],
      });

      const streamPayload = await streamTask(
        taskId,
        (message) => {
          setFileQueue((prev) => prev.map((row) => (row.id === item.id ? { ...row, logs: [...(row.logs || []), message] } : row)));
        },
        (percent) => updateQueueItem(item.id, { progress: Math.max(35, percent) }),
      );

      let merged = { ...uploadPayload, ...streamPayload };
      if (!Object.keys(merged.task_result || {}).length) {
        try {
          const statusPayload = await requestJson("GET", `${API_BASE}/api/v1/tasks/${encodeURIComponent(taskId)}`);
          merged = { ...merged, ...extractTaskPayload(statusPayload) };
        } catch {
          merged = { ...merged };
        }
      }

      const taskResult = merged.task_result || {};
      const taskReport = merged.task_report || {};
      const finalOutputUrl = normalizeApiUrl(taskResult.final_output_url || merged.final_output_url);
      const debugQuality = taskResult.debug_quality || merged.debug_quality || {};

      updateQueueItem(item.id, {
        status: "completed",
        progress: 100,
        task_result: taskResult,
        task_report: taskReport,
        debug_quality: debugQuality,
        final_output_url: finalOutputUrl,
        output_path: taskResult.output_path || "",
        output_filename: taskResult.output_filename || "",
        output_dir: taskResult.output_dir || activeOutputDir,
        input_path: taskResult.input_path || uploadPayload.data?.input_path || "",
        input_width: taskResult.input_width || uploadPayload.data?.input_width || 0,
        input_height: taskResult.input_height || uploadPayload.data?.input_height || 0,
        output_width: taskResult.output_width || taskResult.width || 0,
        output_height: taskResult.output_height || taskResult.height || 0,
        resize_policy: taskResult.resize_policy || "",
        hash_equal: taskResult.hash_equal ?? debugQuality.hash_equal ?? null,
        pixel_diff_score: taskResult.pixel_diff_score ?? debugQuality.pixel_diff_score ?? null,
        debug_timing: taskResult.debug_timing || merged.data?.debug_timing || null,
        error: "",
      });
      setNotice(`当前处理：第 ${index + 1} / ${total} 张已完成。`);
      return true;
    } catch (error) {
      updateQueueItem(item.id, {
        status: "failed",
        progress: 0,
        error: error.message,
        logs: [...(item.logs || []), error.message],
      });
      setNotice(`第 ${index + 1} 张处理失败，已自动顺延后续队列：${error.message}`);
      return false;
    }
  };

  const handleStartQueue = async () => {
    if (processingRef.current) return;
    const runnable = fileQueue.filter((item) => item.status === "queued" || item.status === "failed");
    if (!runnable.length) {
      setNotice("队列中没有待处理图片。");
      return;
    }
    processingRef.current = true;
    setIsProcessingQueue(true);
    const queueOutputDir = resolveOutputDirForRequest();
    console.info("[VisualMasterPro output_dir] queue start", {
      total: runnable.length,
      output_dir: queueOutputDir,
      has_output_dir: Boolean(queueOutputDir),
    });
    setNotice(`逐张高清处理，共 ${runnable.length} 张。`);
    let successCount = fileQueue.filter((item) => item.status === "completed").length;
    let failedCount = 0;
    for (let index = 0; index < runnable.length; index += 1) {
      // 串行处理是 V0.4.4 的安全边界，不能改成并发。
      // eslint-disable-next-line no-await-in-loop
      const success = await processOneItem(runnable[index], index, runnable.length, queueOutputDir);
      if (success) successCount += 1;
      else failedCount += 1;
    }
    processingRef.current = false;
    setIsProcessingQueue(false);
    setCurrentIndex(0);
    setActiveScreen("dashboard");
    setNotice(`全部处理完成：成功 ${successCount} 张，失败 ${failedCount} 张。`);
  };

  const selectForCompare = (item) => {
    if (!item?.final_output_url) return;
    setActiveItemId(item.id);
    setActiveScreen("image_compare");
  };

  const selectForReport = (item) => {
    if (!item?.task_report && !item?.debug_quality) return;
    setActiveItemId(item.id);
    setActiveScreen("quality_report");
  };

  if (activeScreen === "task_detail") {
    return (
      <TaskDetailPage
        taskConfig={makeTaskConfig(activeItem)}
        disableAutoStream
        logsOverride={activeItem?.logs || []}
        taskStatusOverride={activeItem?.status === "failed" ? "failed" : activeItem?.status === "completed" ? "completed" : "processing"}
        progressOverride={activeItem?.progress || 0}
        onBackToDashboard={() => setActiveScreen("dashboard")}
        onViewCompare={() => selectForCompare(activeItem)}
      />
    );
  }

  if (activeScreen === "image_compare") {
    return (
      <ImageSliderComparePage
        taskConfig={makeTaskConfig(activeItem)}
        compareAssets={makeTaskConfig(activeItem)?.compareAssets}
        onBackToTask={() => setActiveScreen("dashboard")}
        onViewReport={() => selectForReport(activeItem)}
      />
    );
  }

  if (activeScreen === "quality_report") {
    return (
      <QualityReportPage
        taskConfig={makeTaskConfig(activeItem)}
        onBackToCompare={() => setActiveScreen("image_compare")}
        onArchive={() => setActiveScreen("dashboard")}
      />
    );
  }

  const outputLocationLabel = appliedOutputDir.trim() ? "当前状态：自定义目录" : "当前状态：默认目录";
  const currentOutputDir = appliedOutputDir.trim() || defaultOutputDir || "等待后端返回默认目录";

  return (
    <section
      onDragOver={(event) => {
        event.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setIsDragging(false);
        addFiles(event.dataTransfer.files);
      }}
      style={{ minHeight: "100dvh", backgroundColor: "#060b0c", color: "#f4f7f8", padding: "24px", boxSizing: "border-box", overflow: "hidden" }}
    >
      <div style={{ maxWidth: "1360px", height: "calc(100dvh - 48px)", margin: "0 auto", display: "flex", flexDirection: "column", gap: "16px" }}>
        <header style={{ height: "70px", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #263738" }}>
          <div>
            <p style={DECOR_LABEL}>Visual Master Pro</p>
            <h1 style={{ ...TITLE_STYLE, margin: "6px 0 0", fontSize: "28px", letterSpacing: "0.06em" }}>画质核心工作台</h1>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span style={{ width: "8px", height: "8px", borderRadius: "50%", backgroundColor: "#6feaf0", boxShadow: "0 0 12px rgba(111,234,240,0.7)" }} />
            <span style={{ ...DECOR_LABEL, color: "#6feaf0" }}>Python Runtime 8787</span>
          </div>
        </header>

        <div style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "0.9fr 1.55fr 0.95fr", gap: "16px", alignItems: "start" }}>
          <div style={{ minHeight: 0, display: "flex", flexDirection: "column", gap: "16px" }}>
            <section style={{ ...PANEL_STYLE, padding: "18px", flex: "0 0 auto" }}>
              <p style={DECOR_LABEL}>Input Field</p>
              <h2 style={{ ...TITLE_STYLE, marginTop: "10px", fontSize: "21px", fontWeight: 600 }}>图片导入</h2>
              <div
                style={{
                  marginTop: "16px",
                  height: "176px",
                  border: isDragging ? "1px dashed #6feaf0" : "1px dashed #263738",
                  borderRadius: "8px",
                  backgroundColor: isDragging ? "#0d181a" : "#05090a",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  textAlign: "center",
                  padding: "16px",
                  boxSizing: "border-box",
                }}
              >
                <input ref={fileInputRef} type="file" accept="image/*" multiple onChange={handleFileChange} style={{ display: "none" }} />
                <button type="button" onClick={() => fileInputRef.current?.click()} style={{ backgroundColor: "#132f33", border: "1px solid #6feaf0", borderRadius: "6px", color: "#6feaf0", cursor: "pointer", padding: "12px 20px", fontSize: "13px", fontWeight: 700 }}>
                  选择本地影像资产
                </button>
                <p style={{ margin: "14px 0 0", color: fileQueue.length ? "#6feaf0" : "#6e7d80", fontSize: "12px" }}>已选择 {fileQueue.length} 张</p>
                <p style={{ margin: "8px 0 0", color: "#6e7d80", fontSize: "11px" }}>支持多选和多图拖拽导入</p>
              </div>
            </section>

            <section style={{ ...PANEL_STYLE, padding: "18px", minHeight: "140px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <p style={DECOR_LABEL}>Restoration Modes</p>
              <h2 style={{ ...TITLE_STYLE, marginTop: "10px", fontSize: "21px", fontWeight: 600 }}>三种增强模式</h2>
              <div style={{ marginTop: "16px", display: "flex", gap: "10px" }}>
                {modeCards.map((mode) => {
                  const active = activeMode === mode.id;
                  return (
                    <button key={mode.id} type="button" onClick={() => setActiveMode(mode.id)} style={{ flex: 1, minWidth: 0, textAlign: "center", background: active ? "#102629" : "#0d181a", border: active ? "1px solid #6feaf0" : "1px solid #263738", color: active ? "#6feaf0" : "#6e7d80", padding: "10px 6px", borderRadius: "4px", fontSize: "11px", cursor: "pointer", transition: "all 0.2s", boxShadow: active ? "0 0 8px rgba(111,234,240,0.15)" : "none" }}>
                      {mode.title}
                    </button>
                  );
                })}
              </div>
              <p style={{ margin: "16px 0 0", color: "#7f8f91", fontSize: "12px", lineHeight: 1.8 }}>{modeCards.find((mode) => mode.id === activeMode)?.desc}</p>
            </section>
          </div>

          <section style={{ ...PANEL_STYLE, padding: "18px", height: "240px", minHeight: "240px", maxHeight: "240px", boxSizing: "border-box", display: "flex", flexDirection: "column", overflow: "hidden" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "12px" }}>
              <div>
                <p style={DECOR_LABEL}>Queue</p>
                <h2 style={{ ...TITLE_STYLE, marginTop: "10px", fontSize: "21px", fontWeight: 600 }}>多图处理队列</h2>
              </div>
              <span style={{ ...DECOR_LABEL, color: "#6feaf0" }}>{fileQueue.length} 张</span>
            </div>
            <div className="custom-scrollbar" style={{ marginTop: "12px", flex: 1, minHeight: 0, maxHeight: "160px", overflowY: "auto", overflowX: "auto", border: "1px solid #263738", borderRadius: "6px", backgroundColor: "#05090a" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", minWidth: "880px", fontSize: "11px" }}>
                <thead style={{ position: "sticky", top: 0, backgroundColor: "#0d181a", color: "#6e7d80", zIndex: 1 }}>
                  <tr>
                    {["文件名", "输入尺寸", "输出尺寸", "处理模式", "输出格式", "当前状态", "输出文件名", "操作"].map((head) => (
                      <th key={head} style={{ padding: "9px 8px", textAlign: "left", borderBottom: "1px solid #263738", whiteSpace: "nowrap", fontWeight: 500 }}>{head}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {!fileQueue.length ? (
                    <tr>
                      <td colSpan={8} style={{ padding: "80px 16px", textAlign: "center", color: "#6e7d80" }}>等待投喂本地影像资产</td>
                    </tr>
                  ) : (
                    fileQueue.map((item) => (
                      <tr key={item.id} style={{ backgroundColor: activeItemId === item.id ? "#0d181a" : "transparent" }}>
                        <td style={{ padding: "9px 8px", borderBottom: "1px solid #132628", maxWidth: "160px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#f4f7f8" }} title={item.name}>{item.name}</td>
                        <td style={{ padding: "9px 8px", borderBottom: "1px solid #132628", color: "#9ba9ab", whiteSpace: "nowrap" }}>{item.input_width && item.input_height ? `${item.input_width} × ${item.input_height}` : "待识别"}</td>
                        <td style={{ padding: "9px 8px", borderBottom: "1px solid #132628", color: "#9ba9ab", whiteSpace: "nowrap" }}>{item.output_width && item.output_height ? `${item.output_width} × ${item.output_height}` : "待生成"}</td>
                        <td style={{ padding: "9px 8px", borderBottom: "1px solid #132628", color: "#9ba9ab", whiteSpace: "nowrap" }}>{item.mode || activeMode}</td>
                        <td style={{ padding: "9px 8px", borderBottom: "1px solid #132628", color: "#9ba9ab", whiteSpace: "nowrap" }}>{(item.output_format || outputFormat).toUpperCase()}</td>
                        <td style={{ padding: "9px 8px", borderBottom: "1px solid #132628" }}><StatusPill status={item.status} /></td>
                        <td style={{ padding: "9px 8px", borderBottom: "1px solid #132628", color: item.error ? "#ff8a8a" : "#9ba9ab", maxWidth: "190px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={item.output_filename || item.error}>{item.output_filename || item.error || "等待输出"}</td>
                        <td style={{ padding: "9px 8px", borderBottom: "1px solid #132628", whiteSpace: "nowrap" }}>
                          <button type="button" onClick={() => { setActiveItemId(item.id); setDebugItemId(item.id); }} style={{ marginRight: "8px", color: "#6feaf0", background: "none", border: 0, cursor: "pointer", fontSize: "11px" }}>定位</button>
                          <button type="button" disabled={item.status !== "completed"} onClick={() => selectForCompare(item)} style={{ marginRight: "8px", color: item.status === "completed" ? "#8be6b1" : "#4f5d60", background: "none", border: 0, cursor: item.status === "completed" ? "pointer" : "not-allowed", fontSize: "11px" }}>查看对比</button>
                          <button type="button" disabled={item.status !== "completed"} onClick={() => selectForReport(item)} style={{ color: item.status === "completed" ? "#8be6b1" : "#4f5d60", background: "none", border: 0, cursor: item.status === "completed" ? "pointer" : "not-allowed", fontSize: "11px" }}>查看报告</button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            <details style={{ marginTop: "10px", color: "#6e7d80", fontSize: "11px" }}>
              <summary style={{ cursor: "pointer", color: "#6feaf0" }}>Debug Runtime Monitor</summary>
              <pre style={{ margin: "8px 0 0", maxHeight: "120px", overflow: "auto", backgroundColor: "#040708", border: "1px solid #132628", borderRadius: "4px", padding: "10px", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
                {debugItem ? JSON.stringify({
                  input_path: debugItem.input_path,
                  output_path: debugItem.output_path,
                  hash_equal: debugItem.hash_equal,
                  pixel_diff_score: debugItem.pixel_diff_score,
                  debug_timing: debugItem.debug_timing,
                }, null, 2) : "请选择一张队列图片查看运行时字段。"}
              </pre>
            </details>
          </section>

          <div style={{ minHeight: 0, display: "flex", flexDirection: "column", gap: "16px" }}>
            <ParameterPanel outputFormat={outputFormat} />
            <section style={{ ...PANEL_STYLE, padding: "18px", minHeight: "140px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <p style={DECOR_LABEL}>Pipeline</p>
              <h2 style={{ ...TITLE_STYLE, marginTop: "10px", fontSize: "21px", fontWeight: 600 }}>状态映射</h2>
              <div style={{ marginTop: "14px", display: "grid", gap: "5px", fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace", fontSize: "11px", color: "#6e7d80" }}>
                <div style={{ color: "#8be6b1", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>✓ CLIENT ONLINE : http://localhost:5173</div>
                <div style={{ color: "#8be6b1", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>✓ RUNTIME ONLINE : http://localhost:8787</div>
                <div style={{ color: "#8be6b1", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>✓ OUTPUT PROFILE : 高清交付 1080P</div>
                <div style={{ color: "#8be6b1", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>✓ TARGET REZ : 1080P 稳定基线</div>
                <div style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>✓ 当前输出：{appliedOutputDir.trim() ? "自定义目录" : "默认输出目录"}</div>
                <div style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{completedItems.length ? "✓ final_output_url 已绑定" : "⏳ 质量守门检测流就绪"}</div>
              </div>
            </section>
          </div>
        </div>

        <section style={{ ...PANEL_STYLE, flexShrink: 0, padding: "14px 18px" }}>
          <div style={{ display: "grid", gap: "10px" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "16px" }}>
              <div>
                <p style={DECOR_LABEL}>OUTPUT DIRECTORY MANAGEMENT</p>
                <h2 style={{ ...TITLE_STYLE, margin: "5px 0 0", fontSize: "16px", fontWeight: 700 }}>输出文件夹</h2>
              </div>
              <span
                style={{
                  border: appliedOutputDir.trim() ? "1px solid #6feaf0" : "1px solid #263738",
                  backgroundColor: appliedOutputDir.trim() ? "rgba(111,234,240,0.12)" : "#0d181a",
                  color: appliedOutputDir.trim() ? "#6feaf0" : "#8be6b1",
                  borderRadius: "999px",
                  padding: "7px 12px",
                  fontSize: "12px",
                  whiteSpace: "nowrap",
                }}
              >
                {outputLocationLabel}
              </span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "auto minmax(0, 1fr)", gap: "10px", alignItems: "center" }}>
              <span style={{ color: "#9ba9ab", fontSize: "12px", whiteSpace: "nowrap" }}>当前路径：</span>
              <div className="custom-scrollbar" style={{ overflowX: "auto", whiteSpace: "nowrap", backgroundColor: "#05090a", border: "1px solid #263738", borderRadius: "6px", padding: "9px 10px", color: "#f4f7f8", fontSize: "12px", fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" }}>
                {currentOutputDir}
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, auto)", gap: "8px", alignItems: "center", justifyContent: "start" }}>
              <button type="button" onClick={handleSelectOutputDir} style={{ border: "1px solid #6feaf0", backgroundColor: "rgba(111,234,240,0.1)", color: "#6feaf0", borderRadius: "5px", padding: "10px 14px", cursor: "pointer", whiteSpace: "nowrap", fontWeight: 700 }}>
                更换文件夹
              </button>
              <button type="button" onClick={handleOpenOutputDir} style={{ border: "1px solid #263738", backgroundColor: "#0d181a", color: "#9ba9ab", borderRadius: "5px", padding: "9px", cursor: "pointer", whiteSpace: "nowrap" }}>
                打开输出文件夹
              </button>
              <button type="button" onClick={handleResetOutputDir} style={{ border: "1px solid #263738", backgroundColor: "#0d181a", color: "#9ba9ab", borderRadius: "5px", padding: "9px", cursor: "pointer", whiteSpace: "nowrap" }}>
                恢复默认
              </button>
            </div>

            {outputDirSuccess ? <p style={{ margin: 0, color: "#8be6b1", fontSize: "12px" }}>{outputDirSuccess}</p> : null}
            {outputDirError ? <p style={{ margin: 0, color: "#ff8a8a", fontSize: "12px" }}>❌ 路径不可用，请检查目录是否存在或权限是否允许写入</p> : null}
          </div>
        </section>

        <footer style={{ ...PANEL_STYLE, flexShrink: 0, padding: "14px 18px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: "18px" }}>
          <div style={{ minWidth: 0 }}>
            <p style={DECOR_LABEL}>Execution</p>
            <p style={{ margin: "6px 0 0", color: notice.includes("失败") || notice.includes("不是目录") ? "#f0c36f" : "#9ba9ab", fontSize: "12px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {isProcessingQueue && currentIndex ? `逐张高清处理 · 当前处理：第 ${currentIndex} / ${fileQueue.length} 张 · ` : ""}
              {notice}
            </p>
          </div>
          <button type="button" onClick={handleStartQueue} disabled={isProcessingQueue} style={{ backgroundColor: fileQueue.length && !isProcessingQueue ? "#132f33" : "#0d181a", border: fileQueue.length && !isProcessingQueue ? "1px solid #6feaf0" : "1px solid #263738", borderRadius: "6px", color: fileQueue.length && !isProcessingQueue ? "#6feaf0" : "#6e7d80", padding: "13px 28px", cursor: isProcessingQueue ? "not-allowed" : "pointer", fontSize: "13px", fontWeight: 700, whiteSpace: "nowrap" }}>
            开启核心修复管线
          </button>
        </footer>
      </div>
    </section>
  );
}
