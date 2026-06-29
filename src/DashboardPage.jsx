import React, { useEffect, useMemo, useRef, useState } from "react";
import TaskDetailPage from "./TaskDetailPage.jsx";
import ImageSliderComparePage from "./ImageSliderComparePage.jsx";
import QualityReportPage from "./QualityReportPage.jsx";
import { resolveDeliveryStatus, resolveReportCenterMeta } from "./deliveryStatus.js";

const API_BASE = "http://localhost:8787";
const OUTPUT_PROFILE = "delivery_1080p";
const DEFAULT_OUTPUT_FORMAT = "auto";
const DEFAULT_SCALE = "2";
const DEFAULT_LEGACY_FORMAT = "png";
const PROCESSING_MODE_STANDARD = "standard";
const PROCESSING_MODE_SAFE_BETA = "safe_1080p_beta";
const DEFAULT_SAFE_BETA_INPUT_DIR = "D:\\影界文件\\真实业务测试_6张";
const DEFAULT_SAFE_BETA_OUTPUT_DIR = "D:\\影界文件\\1080P安全增强输出";

const processingModeOptions = [
  {
    id: PROCESSING_MODE_STANDARD,
    label: "标准优化",
    desc: "沿用当前高清交付流程，适合通用图片优化。",
  },
  {
    id: PROCESSING_MODE_SAFE_BETA,
    label: "1080P安全增强 Beta",
    desc: "适用于中文商业非人像图，使用 35% protected 策略进行安全增强。",
  },
];

const safeBetaBoundaryItems = [
  "当前仅建议用于中文商业非人像图",
  "适合中文信息图、产品图、文旅地图、城市科技主视觉、PPT封面",
  "人像 / 面部主体图暂不建议使用",
  "不支持通用4K超分",
  "不支持低清照片真实修复",
  "输出结果需要人工查看后决定是否使用",
];

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

const statusText = {
  queued: "待处理",
  uploading: "上传中",
  processing: "处理中",
  completed: "已生成",
  failed: "失败",
};

const statusColor = {
  queued: "#6e7d80",
  uploading: "#f0c36f",
  processing: "#6feaf0",
  completed: "#8be6b1",
  failed: "#ff8a8a",
};

const deliveryStatusLabel = {
  PASS: "可交付",
  PASS_WITH_LIMITATION: "建议人工复核",
  FAIL: "不建议交付",
};

const deliveryStatusColor = {
  PASS: "#8be6b1",
  PASS_WITH_LIMITATION: "#f0c36f",
  FAIL: "#ff8a8a",
};

function getModeDisplay(mode) {
  const normalized = mode || "";
  if (["fidelity", "texture", "text_safe"].includes(normalized)) {
    return { label: "标准优化", className: "text-[#00ffcc]" };
  }
  return { label: normalized || "未选择", className: "text-[#94a3b8]" };
}
function getOutputFormatDisplay(format) {
  const normalized = (format || DEFAULT_OUTPUT_FORMAT).toString().toLowerCase();
  if (normalized === "auto") return "智能自适应";
  return normalized.toUpperCase();
}

function getProcessingModeDisplay(mode) {
  return processingModeOptions.find((item) => item.id === mode) || processingModeOptions[0];
}

function normalizeApiUrl(url) {
  if (!url) return "";
  if (/^[a-zA-Z]:[\\/]/.test(url) || /^\\\\/.test(url)) return "";
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
  const debugQuality = data.debug_quality || payload?.debug_quality || task.debug_quality || taskResult.debug_quality || {};
  const taskId = payload?.taskId || payload?.task_id || data.taskId || data.task_id || task.taskId || task.task_id;
  const finalOutputUrl =
    taskResult.preview_output_url ||
    task.preview_output_url ||
    data.preview_output_url ||
    payload?.preview_output_url ||
    taskResult.final_output_url ||
    task.final_output_url ||
    data.final_output_url ||
    payload?.final_output_url;
  const originalUrl = data.originalUrl || payload?.originalUrl || task.originalUrl || taskResult.originalUrl || "";
  const finalDeliveryStatus =
    taskResult.final_delivery_status ||
    debugQuality.final_delivery_status ||
    taskReport.final_delivery_status ||
    task.final_delivery_status ||
    data.final_delivery_status ||
    payload?.final_delivery_status ||
    "";

  return {
    data,
    task,
    taskId,
    filename: payload?.filename || data.filename || data.input_filename || data.fileName || data.original_filename || task.input_filename,
    originalUrl: normalizeApiUrl(originalUrl),
    task_result: taskResult,
    task_report: taskReport,
    debug_quality: debugQuality,
    final_output_url: normalizeApiUrl(finalOutputUrl),
    preview_output_url: normalizeApiUrl(taskResult.preview_output_url || task.preview_output_url || data.preview_output_url || payload?.preview_output_url),
    final_delivery_status: finalDeliveryStatus,
    final_delivery_reason:
      taskResult.final_delivery_reason ||
      debugQuality.final_delivery_reason ||
      taskReport.final_delivery_reason ||
      task.final_delivery_reason ||
      data.final_delivery_reason ||
      payload?.final_delivery_reason ||
      "",
    final_delivery_risk_level:
      taskResult.final_delivery_risk_level ||
      debugQuality.final_delivery_risk_level ||
      taskReport.final_delivery_risk_level ||
      task.final_delivery_risk_level ||
      data.final_delivery_risk_level ||
      payload?.final_delivery_risk_level ||
      "",
    final_delivery_recommended_usage:
      taskResult.final_delivery_recommended_usage ||
      debugQuality.final_delivery_recommended_usage ||
      taskReport.final_delivery_recommended_usage ||
      task.final_delivery_recommended_usage ||
      data.final_delivery_recommended_usage ||
      payload?.final_delivery_recommended_usage ||
      "",
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

function requestBetaSafeEnhance(url, items) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const formData = new FormData();
    formData.append("mode", "safe_1080p");
    formData.append("output_dir", DEFAULT_SAFE_BETA_OUTPUT_DIR);
    formData.append("flat_output", "true");
    formData.append("business_output", "true");
    const selectedNames = items.map((item) => item.name || item.file?.name || "image.png");
    formData.append("selected_file_names_encoded", encodeURIComponent(JSON.stringify(selectedNames)));
    items.forEach((item, index) => {
      const selectedName = selectedNames[index];
      formData.append("selected_file_names", selectedName);
      if (item?.file) formData.append("files", item.file, selectedName);
    });
    xhr.open("POST", url, true);
    xhr.onload = () => {
      let payload = {};
      const rawText = xhr.responseText || "";
      try {
        payload = JSON.parse(rawText || "{}");
      } catch (error) {
        if (xhr.status < 200 || xhr.status >= 300) {
          reject(new Error(`Beta request failed: HTTP ${xhr.status}${rawText ? ` - ${rawText.slice(0, 200)}` : ""}`));
          return;
        }
        reject(new Error(`Beta response parse failed: ${error.message}`));
        return;
      }
      if (xhr.status < 200 || xhr.status >= 300 || payload.ok === false || payload.success === false || payload.status === "FAILED" || payload.status === "failed") {
        reject(new Error(payload.error || payload.message || payload.stage || `Beta request failed: HTTP ${xhr.status}`));
        return;
      }
      resolve(payload);
    };
    xhr.onerror = () => reject(new Error("Cannot connect to Beta API."));
    xhr.send(formData);
  });
}

const isBetaSuccess = (data) =>
  data?.ok === true ||
  data?.success === true ||
  data?.status === "SUCCESS" ||
  data?.verification_result === "PASS" ||
  data?.code === 200 ||
  Number(data?.processed_count || 0) > 0 ||
  (Array.isArray(data?.enhanced_files) && data.enhanced_files.length > 0);

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

function resolveQueueDelivery(item, status) {
  return resolveDeliveryStatus(
    item?.debug_quality,
    item?.task_result,
    item?.task_report,
    item || {},
    { final_delivery_status: status || item?.final_delivery_status || "" },
  );
}

function DeliveryPill({ status, item }) {
  const delivery = resolveQueueDelivery(item, status);
  const normalized = delivery.status || "WAITING";
  const color = delivery.tone || deliveryStatusColor[normalized] || "#6e7d80";
  const label = normalized === "PASS_WITH_LIMITATION" ? "已生成｜建议查看后使用" : delivery.label || deliveryStatusLabel[normalized] || "等待判定";
  return (
    <span
      style={{
        color,
        background: "#0d181a",
        border: `1px solid ${delivery.border || (normalized === "PASS" ? "#315342" : normalized === "PASS_WITH_LIMITATION" ? "#66532d" : normalized === "FAIL" ? "#5a2525" : "#263738")}`,
        borderRadius: "4px",
        padding: "4px 8px",
        fontSize: "10px",
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
        whiteSpace: "nowrap",
      }}
      title={`${delivery.label || label} · ${normalized}`}
    >
      {label}
    </span>
  );
}

function readScore(payload, key) {
  const value = payload?.[key];
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function buildQualityPayload(item) {
  return {
    ...(item?.debug_quality || {}),
    ...(item?.task_result || {}),
    ...(item?.task_report || {}),
    ...(item || {}),
  };
}

function resolveReviewType(meta) {
  if (meta.delivery.status === "FAIL") return "不可交付复核";
  const labels = meta.reviewReasons.map((item) => item.label).join(" ");
  if (labels.includes("颜色") || labels.includes("品牌色")) return "颜色与品牌保护复核";
  if (labels.includes("文字")) return "文字与 Logo 保护复核";
  if (labels.includes("体积") || labels.includes("收益")) return "低收益复核";
  if (labels.includes("平滑")) return "低频平滑区复核";
  if (meta.delivery.status === "PASS_WITH_LIMITATION") return "安全保护复核";
  return "常规交付确认";
}

function resolveSuggestedUsage(meta, item) {
  const rawUsage = item?.final_delivery_recommended_usage || item?.task_result?.final_delivery_recommended_usage || "";
  if (meta.delivery.status === "PASS") return rawUsage || "可用于 1080P 本地交付，正式使用前建议快速查看成品。";
  if (meta.delivery.status === "PASS_WITH_LIMITATION") return rawUsage || "已生成本地预览，建议查看文字、Logo、边缘、品牌色和关键局部后使用。";
  if (meta.delivery.status === "FAIL") return rawUsage || "不建议作为正式成品使用，请回到原图或调整输入后重新处理。";
  return rawUsage || "等待任务完成后再判断用途。";
}

function resolvePositiveSignals(payload) {
  const signals = [];
  const clarity = readScore(payload, "clarity_score");
  const text = readScore(payload, "text_clarity_score");
  const edge = readScore(payload, "edge_quality_score");
  const texture = readScore(payload, "texture_score");
  const color = readScore(payload, "color_fidelity_score");
  const benefit = readScore(payload, "phase6_visible_benefit_score");

  if (clarity !== null && clarity >= 70) signals.push(`清晰度基础较好：${clarity.toFixed(2)}`);
  if (text !== null && text >= 60) signals.push(`文字清晰度通过：${text.toFixed(2)}`);
  if (edge !== null && edge >= 65) signals.push(`边缘质量通过：${edge.toFixed(2)}`);
  if (texture !== null && texture >= 60) signals.push(`材质保持通过：${texture.toFixed(2)}`);
  if (color !== null && color >= 95) signals.push(`默认保真色彩稳定：${color.toFixed(2)}`);
  if (benefit !== null && benefit >= 2) signals.push(`存在可见收益信号：${benefit.toFixed(2)}`);
  if (!signals.length) signals.push("当前更偏保护型输出，建议查看局部后判断收益。");
  return signals;
}

function buildBatchReport(fileQueue) {
  const items = fileQueue.map((item, index) => {
    const payload = buildQualityPayload(item);
    const meta = resolveReportCenterMeta(payload);
    const userStatusLabel = meta.delivery.status === "PASS_WITH_LIMITATION" ? "已生成｜建议查看后使用" : meta.delivery.label;
    return {
      index: index + 1,
      filename: item.name,
      task_id: item.taskId || "",
      task_status: item.status,
      image_type: payload.image_type || "",
      image_type_label: meta.imageType.label,
      raw_delivery_status: payload.final_delivery_status || item.final_delivery_status || "",
      resolved_delivery_status: meta.delivery.status,
      user_status_label: userStatusLabel,
      review_type: resolveReviewType(meta),
      review_reasons: meta.reviewReasons.map((reason) => ({ label: reason.label, detail: reason.detail })),
      positive_signals: resolvePositiveSignals(payload),
      suggested_usage: resolveSuggestedUsage(meta, item),
      benefit_label: meta.benefit.label,
      final_output_url: item.final_output_url || "",
      preview_output_url: item.preview_output_url || "",
      output_filename: item.output_filename || "",
      metrics: {
        clarity_score: readScore(payload, "clarity_score"),
        text_clarity_score: readScore(payload, "text_clarity_score"),
        edge_quality_score: readScore(payload, "edge_quality_score"),
        texture_score: readScore(payload, "texture_score"),
        color_fidelity_score: readScore(payload, "color_fidelity_score"),
        delivery_score: readScore(payload, "delivery_score"),
        phase6_visible_benefit_score: readScore(payload, "phase6_visible_benefit_score"),
        phase6_size_growth_ratio: readScore(payload, "phase6_size_growth_ratio") ?? readScore(payload, "file_size_ratio"),
      },
    };
  });
  const summary = items.reduce(
    (acc, item) => {
      acc.total += 1;
      if (item.task_status === "completed") acc.completed += 1;
      if (item.task_status === "failed") acc.failed += 1;
      if (item.resolved_delivery_status === "PASS") acc.pass += 1;
      if (item.resolved_delivery_status === "PASS_WITH_LIMITATION") acc.manual_review += 1;
      if (item.resolved_delivery_status === "FAIL") acc.not_recommended += 1;
      return acc;
    },
    { total: 0, completed: 0, failed: 0, pass: 0, manual_review: 0, not_recommended: 0 },
  );

  return {
    report_name: "batch_report.json",
    product: "影界 / VisualMasterPro",
    version: "V0.4.6 RC1",
    scope: "local_report_center_mvp",
    generated_at: new Date().toISOString(),
    note: "本报告为前台解释层导出，不改变后端 raw 字段、delivery guard 或真实交付判断逻辑。",
    summary,
    items,
  };
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
    final_output_url: item.final_output_url,
    preview_output_url: item.preview_output_url,
    final_delivery_status: item.final_delivery_status,
    final_delivery_reason: item.final_delivery_reason,
    final_delivery_risk_level: item.final_delivery_risk_level,
    final_delivery_recommended_usage: item.final_delivery_recommended_usage,
    mode: item.mode,
    output_format: item.output_format,
    task_status: item.status,
    task_result: {
      ...(item.task_result || {}),
      final_output_url: item.final_output_url || item.task_result?.final_output_url || "",
      preview_output_url: item.preview_output_url || item.task_result?.preview_output_url || "",
      originalUrl: item.originalUrl || "",
      output_filename: item.output_filename || item.task_result?.output_filename || "",
      final_delivery_status: item.final_delivery_status || item.task_result?.final_delivery_status || "",
      final_delivery_reason: item.final_delivery_reason || item.task_result?.final_delivery_reason || "",
      final_delivery_risk_level: item.final_delivery_risk_level || item.task_result?.final_delivery_risk_level || "",
      final_delivery_recommended_usage: item.final_delivery_recommended_usage || item.task_result?.final_delivery_recommended_usage || "",
    },
    task_report: item.task_report || {},
    debug_quality: item.debug_quality || item.task_result?.debug_quality || {},
    compareAssets: {
      taskId: item.taskId,
      fileName: item.name,
      originalUrl: item.originalUrl,
      final_output_url: item.final_output_url,
      preview_output_url: item.preview_output_url,
      final_delivery_status: item.final_delivery_status,
      final_delivery_reason: item.final_delivery_reason,
      mode: item.mode,
      task_result: {
        ...(item.task_result || {}),
        final_output_url: item.final_output_url || item.task_result?.final_output_url || "",
        preview_output_url: item.preview_output_url || item.task_result?.preview_output_url || "",
        originalUrl: item.originalUrl || "",
        final_delivery_status: item.final_delivery_status || item.task_result?.final_delivery_status || "",
        final_delivery_reason: item.final_delivery_reason || item.task_result?.final_delivery_reason || "",
        final_delivery_risk_level: item.final_delivery_risk_level || item.task_result?.final_delivery_risk_level || "",
        final_delivery_recommended_usage: item.final_delivery_recommended_usage || item.task_result?.final_delivery_recommended_usage || "",
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
  const [processingMode, setProcessingMode] = useState(PROCESSING_MODE_STANDARD);
  const [activeMode] = useState("fidelity");
  const [outputFormat, setOutputFormat] = useState(DEFAULT_OUTPUT_FORMAT);
  const [safeBetaResult, setSafeBetaResult] = useState(null);
  const [safeBetaFeedbackResult, setSafeBetaFeedbackResult] = useState(null);
  const [safeBetaStartedAt, setSafeBetaStartedAt] = useState(null);
  const [safeBetaTick, setSafeBetaTick] = useState(0);
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

  useEffect(() => {
    if (safeBetaResult?.status !== "RUNNING") return () => {};
    const timer = window.setInterval(() => setSafeBetaTick((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [safeBetaResult?.status]);

  const activeItem = useMemo(() => fileQueue.find((item) => item.id === activeItemId) || fileQueue.find((item) => item.status === "processing") || fileQueue.find((item) => item.status === "completed") || null, [fileQueue, activeItemId]);
  const debugItem = useMemo(() => fileQueue.find((item) => item.id === debugItemId) || activeItem, [fileQueue, debugItemId, activeItem]);
  const completedItems = fileQueue.filter((item) => item.status === "completed");
  const canStartExecution = (processingMode === PROCESSING_MODE_SAFE_BETA || fileQueue.length > 0) && !isProcessingQueue;

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
      preview_output_url: "",
      final_delivery_status: "",
      final_delivery_reason: "",
      final_delivery_risk_level: "",
      final_delivery_recommended_usage: "",
      feedback_bundle_status: "",
      feedback_bundle_path: "",
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
    const target = processingMode === PROCESSING_MODE_SAFE_BETA ? DEFAULT_SAFE_BETA_OUTPUT_DIR : appliedOutputDir.trim() || defaultOutputDir;
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

  const runSafeBetaMode = async () => {
    processingRef.current = true;
    setIsProcessingQueue(true);
    setCurrentIndex(1);
    setSafeBetaFeedbackResult(null);
    setSafeBetaResult({
      status: "RUNNING",
      processed_count: 0,
      skipped_count: 0,
      output_dir: DEFAULT_SAFE_BETA_OUTPUT_DIR,
      has_enhanced: false,
      has_contact_sheet: false,
      message: "运行中",
    });
    setNotice("1080P安全增强 Beta 运行中。");
    try {
      const payload = await requestJson("POST", `${API_BASE}/api/beta/safe-1080p/enhance`, {
        input_dir: DEFAULT_SAFE_BETA_INPUT_DIR,
        output_dir: DEFAULT_SAFE_BETA_OUTPUT_DIR,
        mode: "safe_1080p",
      });
      const data = payload?.data || {};
      const processedItems = Array.isArray(data.processed) ? data.processed : [];
      const hasEnhanced = processedItems.length > 0 && processedItems.every((row) => Boolean(row.enhanced));
      const hasContactSheet = processedItems.length > 0 && processedItems.every((row) => Boolean(row.contact_sheet));
      setSafeBetaResult({
        status: payload.verification_result || data.verification_result || "PASS_WITH_NOTES",
        processed_count: data.processed_count || 0,
        skipped_count: data.skipped_count || 0,
        output_dir: data.output_dir || "",
        has_enhanced: hasEnhanced,
        has_contact_sheet: hasContactSheet,
        input_dir: data.input_dir || DEFAULT_SAFE_BETA_INPUT_DIR,
        processed: processedItems,
        skipped: Array.isArray(data.skipped) ? data.skipped : [],
        started_at: data.started_at || "",
        finished_at: data.finished_at || "",
        elapsed_seconds: data.elapsed_seconds || "",
        message: payload.message || "",
      });
      setNotice(`1080P安全增强 Beta 完成：${payload.verification_result || data.verification_result || "PASS_WITH_NOTES"}`);
    } catch (error) {
      setSafeBetaResult({
        status: "BLOCKED",
        processed_count: 0,
        skipped_count: 0,
        output_dir: "",
        has_enhanced: false,
        has_contact_sheet: false,
        message: error.message,
      });
      setNotice(`1080P安全增强 Beta 阻断：${error.message}`);
    } finally {
      processingRef.current = false;
      setIsProcessingQueue(false);
      setCurrentIndex(0);
      setActiveScreen("dashboard");
    }
  };

  const runSafeBetaModeV2 = async () => {
    const startedAt = Date.now();
    const betaItems = fileQueue.filter((item) => item.status === "queued" || item.status === "failed" || item.status === "processing");
    const betaItemIds = betaItems.map((item) => item.id);
    const firstFileName = betaItems[0]?.name || "";
    const firstCurrentFile = firstFileName || "正在连接 Beta 后端";
    const setBetaQueuePatch = (patch) => {
      if (!betaItemIds.length) return;
      setFileQueue((prev) => prev.map((item) => (betaItemIds.includes(item.id) ? { ...item, ...patch } : item)));
    };
    const setBetaQueueCompleted = (results, fallbackOutputPath, fallbackOutputName) => {
      if (!betaItemIds.length) return;
      setFileQueue((prev) =>
        prev.map((item) => {
          if (!betaItemIds.includes(item.id)) return item;
          const mapped = results.find((row) => row.input_name === item.name) || results[0] || {};
          const outputPath = mapped.output_path || fallbackOutputPath || "";
          const outputName = mapped.output_name || fallbackOutputName || (outputPath ? outputPath.split(/[\\/]/).pop() : "");
          return {
            ...item,
            status: "completed",
            progress: 100,
            output_dir: DEFAULT_SAFE_BETA_OUTPUT_DIR,
            output_filename: outputName || "已生成",
            output_path: outputPath,
            final_delivery_status: "PASS_WITH_LIMITATION",
            final_delivery_reason: "1080P安全增强 Beta 已生成，建议查看后使用。",
            final_delivery_recommended_usage: "打开输出目录查看增强图，确认文字、Logo、边缘和颜色后使用。",
            error: "",
            logs: ["处理完成"],
          };
        }),
      );
    };
    const setBetaStage = (progress, currentFile, message) => {
      setSafeBetaResult((prev) => (prev?.status === "RUNNING" ? { ...prev, progress, current_file: currentFile, message } : prev));
      setBetaQueuePatch({ status: "processing", progress, error: "", logs: [message], output_dir: DEFAULT_SAFE_BETA_OUTPUT_DIR, mode: PROCESSING_MODE_SAFE_BETA });
      if (currentFile) setNotice(`${message}：${currentFile}`);
    };
    processingRef.current = true;
    setIsProcessingQueue(true);
    setCurrentIndex(1);
    if (betaItems[0]) {
      setActiveItemId(betaItems[0].id);
      setDebugItemId(betaItems[0].id);
    }
    setSafeBetaStartedAt(startedAt);
    setSafeBetaTick(0);
    setSafeBetaFeedbackResult(null);
    setBetaQueuePatch({
      status: "processing",
      progress: 5,
      mode: PROCESSING_MODE_SAFE_BETA,
      output_dir: DEFAULT_SAFE_BETA_OUTPUT_DIR,
      output_filename: "",
      final_delivery_status: "",
      final_delivery_reason: "Beta 处理中",
      final_output_url: "",
      error: "",
      logs: ["正在连接 Beta 后端"],
    });
    setSafeBetaResult({
      status: "RUNNING",
      progress: 5,
      current_file: firstCurrentFile,
      processed_count: 0,
      enhanced_count: "处理中",
      contact_sheet_count: "生成中",
      skipped_count: 0,
      output_dir: DEFAULT_SAFE_BETA_OUTPUT_DIR,
      has_enhanced: false,
      has_contact_sheet: false,
      elapsed_seconds: 0,
      message: "正在连接 Beta 后端",
    });
    setNotice("1080P安全增强 Beta：正在连接 Beta 后端。");
    const stageTimers = [
      window.setTimeout(() => setBetaStage(15, firstFileName || "正在读取图片", "正在读取图片"), 250),
      window.setTimeout(() => setBetaStage(35, firstFileName || "正在执行 1080P安全增强", "正在执行 1080P安全增强，处理中请稍候"), 1000),
    ];
    try {
      if (!betaItems.some((item) => item.file)) {
        throw new Error("未收到当前选择的输入文件，已拒绝使用默认测试样本");
      }
      console.info("[Safe1080pBeta] request", {
        frontend_selected_file_name: betaItems.map((item) => item.name),
        request_payload: {
          mode: "safe_1080p",
          output_dir: DEFAULT_SAFE_BETA_OUTPUT_DIR,
          flat_output: true,
          business_output: true,
          files: betaItems.map((item) => item.name),
        },
      });
      const payload = await requestBetaSafeEnhance(`${API_BASE}/api/beta/safe-1080p/enhance`, betaItems);
      const data = payload?.data || {};
      if (!isBetaSuccess(payload) && !isBetaSuccess(data)) {
        throw new Error(payload?.error || payload?.message || data?.error_message || data?.reason || "Beta run failed");
      }
      const results = Array.isArray(payload.results) ? payload.results : Array.isArray(data.results) ? data.results : [];
      const enhancedFiles = Array.isArray(payload.enhanced_files) ? payload.enhanced_files : Array.isArray(data.enhanced_files) ? data.enhanced_files : [];
      const processedItems = Array.isArray(data.processed) ? data.processed : [];
      const processedCount = Number(payload.processed_count ?? data.processed_count ?? results.length ?? enhancedFiles.length ?? 0);
      const skippedCount = Number(payload.skipped_count ?? data.skipped_count ?? 0);
      const enhancedCount = processedCount || enhancedFiles.length || processedItems.filter((row) => Boolean(row.enhanced || row.output_path)).length;
      const contactSheetCount = processedItems.filter((row) => Boolean(row.contact_sheet)).length;
      const firstResult = results.find((row) => row.input_name === firstFileName) || results[0] || {};
      const firstEnhanced = firstResult.output_path || enhancedFiles[0] || processedItems.find((row) => row.output_path)?.output_path || processedItems.find((row) => row.enhanced)?.enhanced || "";
      const firstOutputName = firstEnhanced ? firstEnhanced.split(/[\\/]/).pop() : "";
      const resultStatus = payload.verification_result || data.verification_result || "PASS";
      setSafeBetaResult({
        status: resultStatus,
        progress: 100,
        current_file: firstResult.input_name || processedItems[processedItems.length - 1]?.file || firstFileName || "处理完成",
        processed_count: processedCount,
        enhanced_count: enhancedCount,
        contact_sheet_count: contactSheetCount,
        skipped_count: skippedCount,
        output_dir: payload.output_dir || data.output_dir || DEFAULT_SAFE_BETA_OUTPUT_DIR,
        has_enhanced: enhancedCount > 0,
        has_contact_sheet: contactSheetCount > 0,
        input_dir: data.input_dir || "",
        results,
        enhanced_files: enhancedFiles,
        processed: processedItems,
        skipped: Array.isArray(data.skipped) ? data.skipped : [],
        started_at: data.started_at || "",
        finished_at: data.finished_at || "",
        elapsed_seconds: data.elapsed_seconds || Math.round((Date.now() - startedAt) / 1000),
        message: payload.message || "处理完成",
      });
      setBetaQueueCompleted(results, firstEnhanced, firstOutputName);
      setNotice(`1080P安全增强 Beta 完成：${resultStatus}`);
    } catch (error) {
      setSafeBetaResult({
        status: "BLOCKED",
        progress: 100,
        current_file: firstFileName || "处理失败",
        processed_count: 0,
        enhanced_count: 0,
        contact_sheet_count: 0,
        skipped_count: 0,
        output_dir: DEFAULT_SAFE_BETA_OUTPUT_DIR,
        has_enhanced: false,
        has_contact_sheet: false,
        elapsed_seconds: Math.round((Date.now() - startedAt) / 1000),
        message: error.message,
      });
      setBetaQueuePatch({
        status: "failed",
        progress: 100,
        output_dir: DEFAULT_SAFE_BETA_OUTPUT_DIR,
        output_filename: "",
        final_delivery_status: "FAIL",
        final_delivery_reason: error.message,
        error: error.message,
        logs: [error.message],
      });
      setNotice(`1080P安全增强 Beta 处理失败：${error.message}`);
    } finally {
      stageTimers.forEach((timer) => window.clearTimeout(timer));
      processingRef.current = false;
      setIsProcessingQueue(false);
      setCurrentIndex(0);
      setActiveScreen("dashboard");
    }
  };
  const exportSafeBetaFeedbackPackage = async () => {
    if (!safeBetaResult?.output_dir) return;
    try {
      const payload = await requestJson("POST", `${API_BASE}/api/beta/safe-1080p/feedback-package`, {
        run_result: {
          status: "ok",
          verification_result: safeBetaResult.status,
          mode: "safe_1080p",
          input_dir: safeBetaResult.input_dir || DEFAULT_SAFE_BETA_INPUT_DIR,
          output_dir: safeBetaResult.output_dir,
          processed_count: safeBetaResult.processed_count || 0,
          skipped_count: safeBetaResult.skipped_count || 0,
          processed: safeBetaResult.processed || [],
          skipped: safeBetaResult.skipped || [],
          started_at: safeBetaResult.started_at || "",
          finished_at: safeBetaResult.finished_at || "",
          elapsed_seconds: safeBetaResult.elapsed_seconds || "",
        },
      });
      setSafeBetaFeedbackResult(payload?.data || payload);
      setNotice("测试反馈包已导出。");
    } catch (error) {
      setSafeBetaFeedbackResult({
        feedback_bundle_status: "BLOCKED",
        feedback_zip_path: "",
        feedback_bundle_error: error.message,
      });
      setNotice(`测试反馈包导出失败：${error.message}`);
    }
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
      const finalOutputUrl = normalizeApiUrl(taskResult.preview_output_url || merged.preview_output_url || taskResult.final_output_url || merged.final_output_url);
      const debugQuality = taskResult.debug_quality || merged.debug_quality || {};
      const finalDeliveryStatus = merged.final_delivery_status || taskResult.final_delivery_status || debugQuality.final_delivery_status || "";

      updateQueueItem(item.id, {
        status: "completed",
        progress: 100,
        task_result: taskResult,
        task_report: taskReport,
        debug_quality: debugQuality,
        final_output_url: finalOutputUrl,
        preview_output_url: normalizeApiUrl(taskResult.preview_output_url || merged.preview_output_url),
        final_delivery_status: finalDeliveryStatus,
        final_delivery_reason: merged.final_delivery_reason || taskResult.final_delivery_reason || debugQuality.final_delivery_reason || "",
        final_delivery_risk_level: merged.final_delivery_risk_level || taskResult.final_delivery_risk_level || debugQuality.final_delivery_risk_level || "",
        final_delivery_recommended_usage: merged.final_delivery_recommended_usage || taskResult.final_delivery_recommended_usage || debugQuality.final_delivery_recommended_usage || "",
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
    if (processingMode === PROCESSING_MODE_SAFE_BETA) {
      await runSafeBetaModeV2();
      return;
    }
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

  const handleCreateFeedbackBundle = async (item) => {
    if (!item?.taskId) return;
    try {
      const payload = await requestJson("POST", `${API_BASE}/api/v1/tasks/${encodeURIComponent(item.taskId)}/feedback-bundle`, {});
      const bundle = payload?.data || payload || {};
      updateQueueItem(item.id, {
        feedback_bundle_status: bundle.feedback_bundle_status || "",
        feedback_bundle_path: bundle.feedback_bundle_path || "",
        feedback_bundle_size: bundle.feedback_bundle_size || 0,
      });
      setNotice(bundle.feedback_bundle_status === "PASS" ? "诊断反馈包已生成。" : "诊断反馈包生成失败。");
    } catch (error) {
      updateQueueItem(item.id, { feedback_bundle_status: "FAIL" });
      setNotice(error.message || "诊断反馈包生成失败。");
    }
  };

  const handleOpenFinalOutput = (item) => {
    if (!item?.final_output_url) return;
    window.open(item.final_output_url, "_blank", "noopener,noreferrer");
  };

  const handleCopyFinalOutputUrl = async (item) => {
    if (!item?.final_output_url) return;
    try {
      await navigator.clipboard.writeText(item.final_output_url);
      setNotice("已复制成品映射 URL。");
    } catch (error) {
      setNotice(error.message || "复制成品映射 URL 失败。");
    }
  };

  const handleDownloadBatchReport = () => {
    if (!fileQueue.length) {
      setNotice("当前没有可导出的批次报告。");
      return;
    }
    const report = buildBatchReport(fileQueue);
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "batch_report.json";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    setNotice("已生成 batch_report.json，本地报告中心导出完成。");
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

  const outputLocationLabel = processingMode === PROCESSING_MODE_SAFE_BETA ? "当前状态：Beta输出目录" : appliedOutputDir.trim() ? "当前状态：自定义目录" : "当前状态：默认目录";
  const currentOutputDir = processingMode === PROCESSING_MODE_SAFE_BETA ? DEFAULT_SAFE_BETA_OUTPUT_DIR : appliedOutputDir.trim() || defaultOutputDir || "等待后端返回默认目录";
  const safeBetaElapsedSeconds =
    safeBetaResult?.status === "RUNNING" && safeBetaStartedAt
      ? Math.max(0, Math.round((Date.now() - safeBetaStartedAt) / 1000) + safeBetaTick * 0)
      : safeBetaResult?.elapsed_seconds || 0;
  const isSafeBetaSelected = processingMode === PROCESSING_MODE_SAFE_BETA;
  const safeBetaDeliveryConclusion =
    safeBetaResult?.status === "RUNNING"
      ? "处理中"
      : safeBetaResult?.status === "BLOCKED"
        ? "处理失败"
        : safeBetaResult?.status
          ? "建议查看后使用"
          : "等待任务";
  const safeBetaOutputUrlText =
    safeBetaResult?.status === "RUNNING"
      ? "等待生成"
      : safeBetaResult?.status === "BLOCKED"
        ? safeBetaResult?.message || "处理失败"
        : safeBetaResult?.status
          ? "请打开输出目录查看"
          : "等待生成";
  const safeBetaCurrentState =
    safeBetaResult?.status === "RUNNING"
      ? "Beta 处理中"
      : safeBetaResult?.status === "BLOCKED"
        ? safeBetaResult?.message || "处理失败"
        : safeBetaResult?.status
          ? "处理完成"
          : "等待任务";
  const deliveryActionItem = activeItem?.status === "completed" ? activeItem : completedItems[completedItems.length - 1] || null;

  return (
    <section
      className="vmp-main-viewport text-[#f4f7f8]"
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
    >
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-[#1c1f26] bg-[#0b0c0e] px-4">
        <div className="min-w-0">
          <p style={DECOR_LABEL}>HD Delivery Engine</p>
          <h1 className="truncate text-base font-semibold tracking-[0.08em]" style={TITLE_STYLE}>影界 HDDE · 画质核心工作台</h1>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-[#6feaf0]" />
          <span style={{ ...DECOR_LABEL, color: "#6feaf0" }}>Python Runtime 8787</span>
        </div>
      </header>

      <div className="vmp-workspace-container">
        <section className="scrollbar-none flex h-full w-[280px] shrink-0 flex-col gap-2.5 overflow-y-auto border-r border-[#1c1f26] bg-[#121418] p-3">
          <div className="w-full flex-shrink-0 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/30 p-3">
            <section>
              <p style={DECOR_LABEL}>Input Field</p>
              <h2 style={{ ...TITLE_STYLE, marginTop: "8px", fontSize: "18px", fontWeight: 600 }}>图片导入</h2>
              <div
                style={{
                  marginTop: "12px",
                  border: isDragging ? "1px dashed #6feaf0" : "1px dashed #263738",
                  borderRadius: "8px",
                  backgroundColor: isDragging ? "#0d181a" : "#05090a",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  textAlign: "center",
                  padding: "18px 12px",
                  boxSizing: "border-box",
                }}
              >
                <input ref={fileInputRef} type="file" accept="image/*" multiple onChange={handleFileChange} style={{ display: "none" }} />
                <button type="button" onClick={() => fileInputRef.current?.click()} style={{ backgroundColor: "#132f33", border: "1px solid #6feaf0", borderRadius: "6px", color: "#6feaf0", cursor: "pointer", padding: "10px 14px", fontSize: "12px", fontWeight: 700 }}>
                  选择本地影像资产
                </button>
                <p style={{ margin: "12px 0 0", color: fileQueue.length ? "#6feaf0" : "#6e7d80", fontSize: "12px" }}>已选择 {fileQueue.length} 张</p>
                <p style={{ margin: "6px 0 0", color: "#6e7d80", fontSize: "11px" }}>支持多选和多图拖拽导入</p>
              </div>
            </section>
          </div>

          <div className="w-full flex-shrink-0 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/30 p-3">
            <section style={{ display: "flex", flexDirection: "column" }}>
              <p style={DECOR_LABEL}>Processing Mode</p>
              <h2 style={{ ...TITLE_STYLE, marginTop: "8px", fontSize: "18px", fontWeight: 600 }}>处理模式</h2>
              <select
                value={processingMode}
                onChange={(event) => setProcessingMode(event.target.value)}
                style={{
                  marginTop: "12px",
                  width: "100%",
                  backgroundColor: "#05090a",
                  border: "1px solid #263738",
                  borderRadius: "6px",
                  color: "#e2e8f0",
                  padding: "9px 10px",
                  fontSize: "12px",
                  outline: "none",
                }}
              >
                {processingModeOptions.map((option) => (
                  <option key={option.id} value={option.id}>{option.label}</option>
                ))}
              </select>
              <p style={{ margin: "10px 0 0", color: "#7f8f91", fontSize: "12px", lineHeight: 1.7 }}>
                {getProcessingModeDisplay(processingMode).desc}
              </p>
            </section>
          </div>

          {processingMode === PROCESSING_MODE_SAFE_BETA ? (
            <div className="w-full flex-shrink-0 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/40 p-3">
              <h3 className="mb-3 border-b border-[#1c1f26] pb-1.5 text-xs font-medium uppercase tracking-wide text-[#94a3b8]">
                1080P安全增强 Beta
              </h3>
              <div className="space-y-2 text-xs text-[#94a3b8]">
                <div className="flex items-center justify-between gap-3">
                  <span>运行状态:</span>
                  <span className="font-mono text-[#6feaf0]">{safeBetaResult?.status || "WAITING"}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>enhanced:</span>
                  <span className={safeBetaResult?.has_enhanced || safeBetaResult?.status === "RUNNING" ? "text-[#8be6b1]" : "text-[#64748b]"}>{safeBetaResult?.status === "RUNNING" ? "处理中" : safeBetaResult?.has_enhanced ? "是" : "否"}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>contact sheet:</span>
                  <span className={safeBetaResult?.has_contact_sheet || safeBetaResult?.status === "RUNNING" ? "text-[#8be6b1]" : "text-[#64748b]"}>{safeBetaResult?.status === "RUNNING" ? "生成中" : safeBetaResult?.has_contact_sheet ? "是" : "否"}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>跳过图片:</span>
                  <span className="font-mono text-[#e2e8f0]">{safeBetaResult?.skipped_count ?? 0}</span>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <span className="shrink-0">输出目录:</span>
                  <span className="min-w-0 break-all text-right font-mono text-[#64748b]">{safeBetaResult?.output_dir || DEFAULT_SAFE_BETA_OUTPUT_DIR}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>progress:</span>
                  <span className="font-mono text-[#e2e8f0]">{safeBetaResult?.progress ?? 0}%</span>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <span className="shrink-0">current file:</span>
                  <span className="min-w-0 break-all text-right font-mono text-[#64748b]">{safeBetaResult?.current_file || "WAITING"}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>enhanced count:</span>
                  <span className="font-mono text-[#e2e8f0]">{safeBetaResult?.status === "RUNNING" ? "处理中" : safeBetaResult?.enhanced_count ?? 0}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>contact sheet count:</span>
                  <span className="font-mono text-[#e2e8f0]">{safeBetaResult?.status === "RUNNING" ? "生成中" : safeBetaResult?.contact_sheet_count ?? 0}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>elapsed:</span>
                  <span className="font-mono text-[#e2e8f0]">{safeBetaElapsedSeconds}s</span>
                </div>
              </div>
              <button
                type="button"
                onClick={exportSafeBetaFeedbackPackage}
                disabled={!safeBetaResult?.output_dir || isProcessingQueue}
                className="mt-3 w-full rounded border border-[#6feaf0]/50 px-3 py-2 text-xs font-semibold text-[#6feaf0] transition hover:border-[#9cffef] hover:text-[#9cffef] disabled:cursor-not-allowed disabled:border-white/10 disabled:text-white/30"
              >
                导出测试反馈包
              </button>
              <p className="mt-2 text-[11px] leading-5 text-white/42">
                生成本次测试的运行报告、错误日志、系统环境和对比图，用于发送给开发者定位问题。
              </p>
              {safeBetaFeedbackResult?.feedback_zip_path ? (
                <p className="mt-2 break-all font-mono text-[11px] leading-5 text-[#64748b]">
                  {safeBetaFeedbackResult.feedback_zip_path}
                </p>
              ) : null}
              <div className="mt-3 space-y-1.5">
                {safeBetaBoundaryItems.map((item) => (
                  <div key={item} className="rounded border border-white/8 bg-black/15 px-2 py-1.5 text-[11px] leading-5 text-white/52">
                    {item}
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <div className="w-full flex-shrink-0 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/40 p-3">
            <h3 className="mb-3 border-b border-[#1c1f26] pb-1.5 text-xs font-medium uppercase tracking-wide text-[#94a3b8]">
              输出图片参数
            </h3>
            <ul className="space-y-2 font-sans text-xs">
              {[
                { label: "交付方案", value: "高清交付 1080P", color: "text-white" },
                { label: "目标格式", value: getOutputFormatDisplay(outputFormat), color: "text-[#94a3b8]" },
                { label: "核心总线", value: "1080P 高清稳定交付", color: "text-white font-mono" },
                { label: "尺寸策略", value: "智能无损自适应缩放", color: "text-[#94a3b8]" },
              ].map((item) => (
                <li key={item.label} className="flex w-full items-center">
                  <span className="w-16 shrink-0 text-left text-[#64748b]">{item.label}</span>
                  <div className="mx-2 h-2 flex-1 border-b border-dashed border-[#1c1f26]" />
                  <span className={`shrink-0 text-right ${item.color}`} title={item.value}>
                    {item.value}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="flex h-full flex-1 flex-col overflow-hidden bg-[#0b0c0e] p-4">
          <div className="mb-4 flex w-full flex-1 flex-col overflow-hidden rounded-sm border border-[#1c1f26] bg-[#121418] p-4">
            <div className="mb-2 flex items-center justify-between gap-4">
              <div className="min-w-0">
                <p style={DECOR_LABEL}>Queue</p>
                <h3 className="truncate text-xs font-medium text-[#94a3b8]">多图处理队列</h3>
              </div>
              <span style={{ ...DECOR_LABEL, color: "#6feaf0" }}>{fileQueue.length} 张</span>
            </div>
            <div className="scrollbar-thin w-full flex-1 overflow-auto border border-[#263738] bg-[#05090a]">
              <table className="w-full text-left font-mono text-xs" style={{ borderCollapse: "collapse", minWidth: "820px" }}>
                <thead style={{ position: "sticky", top: 0, backgroundColor: "#0d181a", color: "#6e7d80", zIndex: 1 }}>
                  <tr className="border-b border-[#1c1f26] text-[#64748b]">
                    <th className="px-3 py-2 text-left font-medium">文件名</th>
                    <th className="px-3 py-2 text-left font-medium">输出尺寸</th>
                    <th className="px-3 py-2 text-left font-medium">处理模式</th>
                    <th className="px-3 py-2 text-left font-medium">输出格式</th>
                    <th className="px-3 py-2 text-left font-medium">当前状态</th>
                    <th className="px-3 py-2 text-left font-medium">交付状态</th>
                    <th className="px-3 py-2 text-left font-medium">输出文件名</th>
                    <th className="px-3 py-2 text-center font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {!fileQueue.length ? (
                    <tr>
                      <td colSpan={8} style={{ padding: "80px 16px", textAlign: "center", color: "#6e7d80" }}>等待投喂本地影像资产</td>
                    </tr>
                  ) : (
                    fileQueue.map((item) => (
                      <tr key={item.id} className={`border-b border-[#1c1f26]/50 transition-colors hover:bg-[#121418]/50 ${activeItemId === item.id ? "bg-[#0d181a]" : ""}`}>
                        <td className="max-w-[180px] truncate px-3 py-2 font-mono text-[#e2e8f0]" title={item.name}>{item.name}</td>
                        <td className="px-3 py-2 font-mono font-medium text-[#00ffcc]">{item.output_width && item.output_height ? `${item.output_width} × ${item.output_height}` : "待生成"}</td>
                        <td className="px-3 py-2 font-sans">
                          {(() => {
                            const display = getModeDisplay(item.mode || activeMode);
                            return <span className={display.className}>{display.label}</span>;
                          })()}
                        </td>
                        <td className="px-3 py-2 font-mono text-[#64748b]">
                          <span className="text-[#64748b]">{getOutputFormatDisplay(item.output_format || outputFormat)}</span>
                        </td>
                        <td className="px-3 py-2"><StatusPill status={item.status} /></td>
                        <td className="px-3 py-2"><DeliveryPill status={item.final_delivery_status} item={item} /></td>
                        <td className={`max-w-[150px] truncate px-3 py-2 font-mono ${item.error ? "text-[#ff8a8a]" : "text-[#64748b]"}`} title={item.output_filename || item.error}>{item.output_filename || item.error || "等待输出"}</td>
                        <td className="space-x-2 px-3 py-2 text-center">
                          <button type="button" onClick={() => { setActiveItemId(item.id); setDebugItemId(item.id); }} className="text-[11px] text-[#00ffcc] hover:underline">定位</button>
                          <button type="button" disabled={item.status !== "completed"} onClick={() => selectForCompare(item)} className="text-[11px] text-[#94a3b8] transition-colors hover:text-white disabled:cursor-not-allowed disabled:text-[#475569]">查看对比</button>
                          <button type="button" disabled={item.status !== "completed"} onClick={() => selectForReport(item)} className="text-[11px] text-[#64748b] transition-colors hover:text-[#94a3b8] disabled:cursor-not-allowed disabled:text-[#475569]">报告</button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            <details className="shrink-0" style={{ marginTop: "10px", color: "#6e7d80", fontSize: "11px" }}>
              <summary style={{ cursor: "pointer", color: "#6feaf0" }}>Debug Runtime Monitor</summary>
              <p style={{ margin: "8px 0 0", color: "#7f8c8d", fontSize: "11px", lineHeight: 1.6 }}>
                技术详情：下方为后端原始运行字段，不代表面向用户的最终交付结论。用户交付口径以队列表格、交付质检看板、任务详情和质量报告中的“建议人工复核 / 可交付 / 不建议交付”为准。
              </p>
              <pre className="scrollbar-thin" style={{ margin: "8px 0 0", overflow: "auto", backgroundColor: "#040708", border: "1px solid #132628", borderRadius: "4px", padding: "10px", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
                {debugItem ? JSON.stringify({
                  task_id: debugItem.taskId,
                  raw_delivery_status: buildQualityPayload(debugItem).final_delivery_status || debugItem.final_delivery_status,
                  resolved_delivery_status: resolveReportCenterMeta(buildQualityPayload(debugItem)).delivery.status,
                  user_status_label: resolveReportCenterMeta(buildQualityPayload(debugItem)).delivery.status === "PASS_WITH_LIMITATION" ? "已生成｜建议查看后使用" : resolveReportCenterMeta(buildQualityPayload(debugItem)).delivery.label,
                  image_type: buildQualityPayload(debugItem).image_type || "",
                  image_type_label: resolveReportCenterMeta(buildQualityPayload(debugItem)).imageType.label,
                  review_type: resolveReviewType(resolveReportCenterMeta(buildQualityPayload(debugItem))),
                  review_reasons: resolveReportCenterMeta(buildQualityPayload(debugItem)).reviewReasons,
                  delivery_score: readScore(buildQualityPayload(debugItem), "delivery_score"),
                  metrics: {
                    clarity_score: readScore(buildQualityPayload(debugItem), "clarity_score"),
                    text_clarity_score: readScore(buildQualityPayload(debugItem), "text_clarity_score"),
                    edge_quality_score: readScore(buildQualityPayload(debugItem), "edge_quality_score"),
                    texture_score: readScore(buildQualityPayload(debugItem), "texture_score"),
                    color_fidelity_score: readScore(buildQualityPayload(debugItem), "color_fidelity_score"),
                  },
                  final_delivery_reason: debugItem.final_delivery_reason,
                  final_delivery_risk_level: debugItem.final_delivery_risk_level,
                  final_output_url: debugItem.final_output_url,
                  preview_output_url: debugItem.preview_output_url,
                  feedback_bundle_status: debugItem.feedback_bundle_status,
                }, null, 2) : "请选择一张队列图片查看运行时字段。"}
              </pre>
            </details>
          </div>

          <div className="flex h-16 w-full shrink-0 items-center justify-between rounded-sm border border-[#1c1f26] bg-[#121418] p-3">
            <div className="min-w-0">
              <p style={DECOR_LABEL}>Execution</p>
              <p style={{ margin: "4px 0 0", color: notice.includes("失败") || notice.includes("不是目录") ? "#f0c36f" : "#9ba9ab", fontSize: "12px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {isProcessingQueue && currentIndex ? `逐张高清处理 · 当前处理：第 ${currentIndex} / ${fileQueue.length} 张 · ` : ""}
                {notice}
              </p>
            </div>
            <button type="button" onClick={handleStartQueue} disabled={!canStartExecution} style={{ backgroundColor: canStartExecution ? "#132f33" : "#0d181a", border: canStartExecution ? "1px solid #6feaf0" : "1px solid #263738", borderRadius: "6px", color: canStartExecution ? "#6feaf0" : "#6e7d80", padding: "10px 20px", cursor: canStartExecution ? "pointer" : "not-allowed", fontSize: "13px", fontWeight: 700, whiteSpace: "nowrap" }}>
              {processingMode === PROCESSING_MODE_SAFE_BETA ? (isProcessingQueue ? "安全增强处理中..." : "开始安全增强 Beta") : "开启核心修复管线"}
            </button>
          </div>
        </section>

        <section className="scrollbar-none flex h-full w-[320px] shrink-0 flex-col gap-2.5 overflow-y-auto border-l border-[#1c1f26] bg-[#121418] p-3">
          <div className="w-full flex-shrink-0 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/40 p-3">
              <h3 className="mb-3 border-b border-[#1c1f26] pb-1.5 text-xs font-medium uppercase tracking-wide text-[#94a3b8]">
                交付质检看板
              </h3>
              <div className="space-y-2 text-xs">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#94a3b8]">当前样本:</span>
                  <span className="min-w-0 truncate text-right font-mono text-[#e2e8f0]" title={isSafeBetaSelected ? safeBetaResult?.current_file || activeItem?.name || "等待任务" : activeItem?.name || "等待任务"}>
                    {isSafeBetaSelected ? safeBetaResult?.current_file || activeItem?.name || "等待任务" : activeItem?.name || "等待任务"}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#94a3b8]">交付结论:</span>
                  {isSafeBetaSelected ? (
                    <span className="rounded border border-[#263738] bg-[#0d181a] px-2 py-1 font-mono text-[10px] text-[#6feaf0]">
                      {safeBetaDeliveryConclusion}
                    </span>
                  ) : (
                    <DeliveryPill status={activeItem?.final_delivery_status} item={activeItem} />
                  )}
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#94a3b8]">输出 URL:</span>
                  <span className="block max-w-[180px] truncate font-mono text-[11px] text-[#10b981]" title={isSafeBetaSelected ? safeBetaOutputUrlText : activeItem?.final_output_url || "等待成品"}>
                    {isSafeBetaSelected ? safeBetaOutputUrlText : activeItem?.final_output_url || "等待成品"}
                  </span>
                </div>
                {isSafeBetaSelected ? (
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-[#94a3b8]">当前状态:</span>
                    <span className="block max-w-[180px] truncate text-right font-mono text-[11px] text-[#6feaf0]" title={safeBetaCurrentState}>
                      {safeBetaCurrentState}
                    </span>
                  </div>
                ) : null}
              </div>
          </div>

          <div className="w-full flex-shrink-0 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/40 p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <h3 className="text-xs font-medium text-[#94a3b8]">输出文件夹</h3>
              <span className="rounded-sm border border-[#333] bg-[#1c1f26] px-2 py-0.5 text-[10px] text-[#10b981]">
                {outputLocationLabel}
              </span>
            </div>
            <div className="scrollbar-none vmp-path-scroll-container mb-3 rounded-sm border border-[#1c1f26] bg-[#0b0c0e] p-2.5 font-mono text-xs text-[#e2e8f0]">
              {currentOutputDir}
            </div>
            <button
              type="button"
              onClick={handleSelectOutputDir}
              className="w-full rounded-sm border border-[#00ffcc]/30 bg-[#1c1f26] px-4 py-2.5 text-xs font-medium tracking-wide text-[#00ffcc] transition-colors hover:bg-[#20242c]"
            >
              更换文件夹
            </button>
            <div className="mt-2 grid grid-cols-2 gap-2">
              <button type="button" onClick={handleOpenOutputDir} className="rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/30 py-1.5 text-[11px] text-[#94a3b8] transition-colors hover:bg-[#1c1f26] hover:text-white">
                📂 打开当前目录
              </button>
              <button type="button" onClick={handleResetOutputDir} className="rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/30 py-1.5 text-[11px] text-[#64748b] transition-colors hover:bg-[#1c1f26] hover:text-[#94a3b8]">
                🔄 重置默认路径
              </button>
            </div>
            {outputDirSuccess ? <p className="mt-2 text-xs text-[#8be6b1]">{outputDirSuccess}</p> : null}
            {outputDirError ? <p className="mt-2 text-xs text-[#ff8a8a]">路径不可用，请检查权限。</p> : null}
          </div>

          <div className="mt-auto w-full flex-shrink-0 space-y-2 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/80 p-3">
            <h3 className="border-b border-[#1c1f26] pb-1.5 text-xs font-medium uppercase tracking-wide text-[#94a3b8]">
              Pipeline 状态映射
            </h3>
            <div className="space-y-1.5 border-b border-[#1c1f26]/50 pb-1.5 font-mono text-[11px]">
              <div className="flex items-center justify-between gap-3">
                <span className="shrink-0 text-[#475569]">前台连接:</span>
                <span className="max-w-[180px] truncate text-[#10b981]" title="http://localhost:5173">http://localhost:5173</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="shrink-0 text-[#475569]">后台运行:</span>
                <span className="max-w-[180px] truncate text-[#10b981]" title="http://localhost:8787">http://localhost:8787</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="shrink-0 text-[#475569]">交付方案:</span>
                <span className="min-w-0 truncate text-[#94a3b8]" title="高清交付 1080P">高清交付 1080P</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="shrink-0 text-[#475569]">目标规格:</span>
                <span className="min-w-0 truncate text-[#f59e0b]" title="1080P 稳定基线">1080P 稳定基线</span>
              </div>
            </div>
            <div className="space-y-0.5 pt-1.5 text-xs font-medium">
              <div className="flex items-center justify-between text-[#94a3b8]">
                <span>已完成任务:</span>
                <span className="font-mono">{completedItems.length} / {fileQueue.length} 张</span>
              </div>
              <div className="flex items-center justify-between text-[#f59e0b]">
                <span>已生成｜建议查看后使用:</span>
                <span className="rounded-sm bg-[#f59e0b]/10 px-1.5 font-mono">{fileQueue.filter((item) => resolveQueueDelivery(item).status === "PASS_WITH_LIMITATION").length} 张</span>
              </div>
              <div className="flex items-center justify-between text-[#f43f5e]">
                <span>不建议交付状态:</span>
                <span className="rounded-sm bg-[#f43f5e]/10 px-1.5 font-mono">{fileQueue.filter((item) => resolveQueueDelivery(item).status === "FAIL").length} 张</span>
              </div>
            </div>
            <div className="space-y-2 border-t border-[#1c1f26]/30 pt-2">
              <button type="button" disabled={!deliveryActionItem?.final_output_url} onClick={() => handleOpenFinalOutput(deliveryActionItem)} className="flex w-full items-center justify-center gap-2 rounded-sm bg-[#10b981] px-4 py-2.5 text-xs font-bold tracking-wider text-[#0b0c0e] shadow-md transition-colors hover:bg-[#059669] disabled:cursor-not-allowed disabled:bg-[#1c1f26] disabled:text-[#475569] disabled:shadow-none">
                <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true">
                  <path d="M12 5v13M5 12l7 7 7-7" />
                </svg>
                <span>下载成品高清图片</span>
              </button>
              <button type="button" disabled={!deliveryActionItem?.final_output_url} onClick={() => handleCopyFinalOutputUrl(deliveryActionItem)} className="group flex w-full items-center justify-center gap-2 rounded-sm border border-[#333] bg-[#1c1f26] px-4 py-2 text-xs text-[#e2e8f0] transition-colors hover:bg-[#2d3139] disabled:cursor-not-allowed disabled:text-[#475569]">
                <svg className="h-3.5 w-3.5 text-[#64748b] transition-colors group-hover:text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true">
                  <rect x="9" y="9" width="13" height="13" rx="1" />
                  <path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1" />
                </svg>
                <span>复制成品映射路径</span>
              </button>
              <button type="button" disabled={!deliveryActionItem?.taskId} onClick={() => handleCreateFeedbackBundle(deliveryActionItem)} className="group flex w-full items-center justify-center gap-2 rounded-sm border border-[#856404]/30 bg-[#0b0c0e]/40 px-4 py-2 font-mono text-[11px] text-[#856404] transition-colors hover:border-[#ffc107]/50 hover:bg-[#1c1f26] hover:text-[#ffc107] disabled:cursor-not-allowed disabled:border-[#1c1f26] disabled:text-[#475569]">
                <svg className="animate-spin-slow h-3.5 w-3.5 text-[#856404] transition-colors group-hover:text-[#ffc107]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="square" aria-hidden="true">
                  <circle cx="12" cy="12" r="3" />
                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                </svg>
                <span>生成系统脱敏诊断包</span>
              </button>
              <button type="button" disabled={!fileQueue.length} onClick={handleDownloadBatchReport} className="w-full rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/50 px-4 py-2 text-[11px] font-medium tracking-wide text-[#94a3b8] transition-colors hover:border-[#00ffcc]/30 hover:text-[#00ffcc] disabled:cursor-not-allowed disabled:text-[#475569]">
                生成 batch_report.json
              </button>
            </div>
            <p className="border-t border-[#1c1f26]/30 pt-2 text-[10px] leading-relaxed text-[#475569]">
              成品质检仅依据后端解算映射 URL，不读取本地物理路径。
            </p>
          </div>
        </section>
      </div>

      <footer className="flex h-6 w-full shrink-0 items-center justify-center overflow-hidden border-t border-[#1c1f26] bg-[#0b0c0e] px-3 text-center font-mono text-[10px] tracking-[0.16em] text-[#6e7d80]">
        影界 HDDE V0.4.6 RC1 · HD Delivery Engine · 中文视觉高清交付引擎
      </footer>
    </section>
  );
}
