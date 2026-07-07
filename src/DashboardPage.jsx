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
const SAFE_BETA_FETCH_TIMEOUT_MS = 300000;

const JPG95_REVIEW_OPTIONS = [
  { decision: "recommend_adopt", label: "建议采用", recommendation: "candidate_recommended" },
  { decision: "keep_png", label: "保留 PNG", recommendation: "png_fallback_recommended" },
  { decision: "reject_candidate", label: "拒绝候选", recommendation: "not_recommended" },
  { decision: "needs_more_check", label: "继续检查", recommendation: "needs_more_check" },
];

const JPG95_REVIEW_FIELD_NAMES = [
  "candidate_is_final_output",
  "jpg95_candidate_review_status",
  "jpg95_candidate_review_decision",
  "jpg95_candidate_review_label",
  "jpg95_candidate_recommendation",
  "jpg95_candidate_recommendation_reason",
  "jpg95_candidate_review_note",
  "jpg95_candidate_reviewed_at",
];

const processingModeOptions = [
  {
    id: PROCESSING_MODE_STANDARD,
    label: "1080P标准版",
    desc: "沿用当前高清交付流程，适合标准 1080P 交付。",
  },
  {
    id: PROCESSING_MODE_SAFE_BETA,
    label: "1080P安全增强版 Beta",
    desc: "适用于中文商业非人像图，使用 35% protected 策略进行安全增强。",
  },
];

const safeBetaBoundaryItems = [
  "不建议用于人像 / 面部主体图",
  "不用于通用 4K 超分",
  "不用于低清照片真实修复",
  "输出结果建议人工查看后使用",
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
  need_reselect: "需重新选择",
};

const statusColor = {
  queued: "#6e7d80",
  uploading: "#f0c36f",
  processing: "#6feaf0",
  completed: "#8be6b1",
  failed: "#ff8a8a",
  need_reselect: "#f0c36f",
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
    return { label: "1080P标准版", className: "text-[#00ffcc]" };
  }
  if (normalized === PROCESSING_MODE_SAFE_BETA) return { label: "1080P安全增强版 Beta", className: "text-[#6feaf0]" };
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

function formatBytesToMb(value, fallback = "-") {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return fallback;
  return `${(number / 1024 / 1024).toFixed(2)} MB`;
}

function formatSizeRatio(value, fallback = "-") {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return fallback;
  return `${number.toFixed(2)}×`;
}

function formatPercentValue(value, fallback = "-") {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return fallback;
  return `${(number * 100).toFixed(2)}%`;
}

function findJpg95ReviewOption(decision) {
  return JPG95_REVIEW_OPTIONS.find((item) => item.decision === decision) || null;
}

function addJpg95ReviewDefaults(item = {}) {
  const hasCandidate = item?.jpg95_candidate_status === "candidate_for_review";
  return {
    ...item,
    candidate_is_final_output: false,
    jpg95_candidate_review_status: item?.jpg95_candidate_review_status || (hasCandidate ? "pending_review" : "not_applicable"),
    jpg95_candidate_review_decision: item?.jpg95_candidate_review_decision || "",
    jpg95_candidate_review_label: item?.jpg95_candidate_review_label || "",
    jpg95_candidate_recommendation: item?.jpg95_candidate_recommendation || "",
    jpg95_candidate_recommendation_reason: item?.jpg95_candidate_recommendation_reason || "",
    jpg95_candidate_review_note: item?.jpg95_candidate_review_note || "",
    jpg95_candidate_reviewed_at: item?.jpg95_candidate_reviewed_at || "",
  };
}

function pickJpg95ReviewFields(source = {}) {
  return JPG95_REVIEW_FIELD_NAMES.reduce((fields, key) => {
    if (source[key] !== undefined) fields[key] = source[key];
    return fields;
  }, {});
}

function isSameSafeBetaRow(row = {}, item = {}) {
  return Boolean(item) && (row.input_name === item.name || row.file === item.name || row.output_name === item.output_filename);
}

function pathFormat(value) {
  const filename = String(value || "").split(/[?#]/)[0].split(/[\\/]/).pop() || "";
  const index = filename.lastIndexOf(".");
  return index >= 0 ? filename.slice(index + 1).toLowerCase() : "";
}

function formatSafeBetaStatus(status) {
  const normalized = String(status || "WAITING").toUpperCase();
  if (["PASS", "SUCCESS", "COMPLETED"].includes(normalized)) return "处理完成";
  if (["RUNNING", "PROCESSING"].includes(normalized)) return "处理中";
  if (["FAILED", "BLOCKED"].includes(normalized)) return "处理失败";
  if (normalized === "NEED_RESELECT") return "需重新选择";
  return "待处理";
}

function formatSafeBetaDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  if (total < 60) return `${total}秒`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes}分${String(rest).padStart(2, "0")}秒`;
}

function readSafeBetaCount(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function firstSafeBetaOutputPath(item, result) {
  if (item?.output_path) return item.output_path;
  const results = Array.isArray(result?.results) ? result.results : [];
  const mapped = item?.name ? results.find((row) => row?.input_name === item.name) : null;
  if (mapped?.output_path) return mapped.output_path;
  if (results[0]?.output_path) return results[0].output_path;
  const enhancedFiles = Array.isArray(result?.enhanced_files) ? result.enhanced_files : [];
  return enhancedFiles[0] || "";
}

function normalizeSafeBetaPreviewUrl(url) {
  if (!url) return "";
  const value = String(url);
  if (/^[a-zA-Z]:[\\/]/.test(value) || /^\\\\/.test(value) || /^file:\/\//i.test(value)) return "";
  if (/^https?:\/\//i.test(value)) return value;
  if (value.startsWith("/")) return normalizeApiUrl(value);
  return "";
}

function findSafeBetaResultRow(item, result) {
  const results = Array.isArray(result?.results) ? result.results : [];
  if (!item) return results[0] || {};
  return results.find((row) => row?.input_name === item.name || row?.file === item.name) || results[0] || {};
}

function findSafeBetaProcessedRow(item, result) {
  if (!item) return {};
  if (item.beta_processed) return item.beta_processed;
  const processed = Array.isArray(result?.processed) ? result.processed : [];
  return processed.find((row) => row?.input_name === item.name || row?.file === item.name) || {};
}

function findSafeBetaSkippedRow(item, result) {
  if (!item) return {};
  if (item.beta_skipped) return item.beta_skipped;
  const skipped = Array.isArray(result?.skipped) ? result.skipped : [];
  return skipped.find((row) => row?.input_name === item.name || row?.file === item.name) || {};
}

function firstSafeBetaContactSheet(item, result) {
  if (item?.contact_sheet) return item.contact_sheet;
  const processed = findSafeBetaProcessedRow(item, result);
  return processed?.contact_sheet || "";
}

function firstSafeBetaContactSheetLight(item, result) {
  if (item?.contact_sheet_light) return item.contact_sheet_light;
  const processed = findSafeBetaProcessedRow(item, result);
  return processed?.contact_sheet_light || "";
}

function firstSafeBetaContactSheetPreviewUrl(item, result) {
  const processed = findSafeBetaProcessedRow(item, result);
  const mapped = findSafeBetaResultRow(item, result);
  const candidates = [
    item?.contact_sheet_light_url,
    item?.contact_sheet_light_preview_url,
    item?.contact_sheet_url,
    item?.contact_sheet_preview_url,
    processed?.contact_sheet_light_url,
    processed?.contact_sheet_light_preview_url,
    processed?.contact_sheet_url,
    processed?.contact_sheet_preview_url,
    mapped?.contact_sheet_light_url,
    mapped?.contact_sheet_light_preview_url,
    mapped?.contact_sheet_url,
    mapped?.contact_sheet_preview_url,
    result?.contact_sheet_light_url,
    result?.contact_sheet_light_preview_url,
    result?.contact_sheet_url,
    result?.contact_sheet_preview_url,
    item?.contact_sheet,
    processed?.contact_sheet,
    mapped?.contact_sheet,
  ];
  return candidates.map(normalizeSafeBetaPreviewUrl).find(Boolean) || "";
}

function firstSafeBetaOutputPreviewUrl(item, result) {
  const processed = findSafeBetaProcessedRow(item, result);
  const mapped = findSafeBetaResultRow(item, result);
  const candidates = [
    item?.output_url,
    item?.preview_url,
    item?.public_url,
    item?.final_output_url,
    processed?.output_url,
    processed?.preview_url,
    processed?.public_url,
    processed?.final_output_url,
    mapped?.output_url,
    mapped?.preview_url,
    mapped?.public_url,
    mapped?.final_output_url,
    result?.output_url,
    result?.preview_url,
    result?.public_url,
    result?.final_output_url,
    item?.output_path,
    processed?.output_path,
    mapped?.output_path,
  ];
  return candidates.map(normalizeSafeBetaPreviewUrl).find(Boolean) || "";
}

function safeBetaItemStatusText(item, result) {
  if (!item) return "等待任务";
  if (item.status === "completed") return "已生成";
  if (item.status === "processing") return "处理中";
  if (item.status === "need_reselect") return "需重新选择";
  if (item.status === "failed") {
    const skipped = findSafeBetaSkippedRow(item, result);
    if (skipped?.reason) return `已跳过：${skipped.reason}`;
    return item.error || "处理失败";
  }
  return "待处理";
}

function safeBetaReasonText(item, result) {
  const skipped = findSafeBetaSkippedRow(item, result);
  const reason = skipped?.reason || item?.error || item?.final_delivery_reason || "";
  if (!reason) return "-";
  if (String(reason).includes("skip_portrait_metrics")) return "人物图保护跳过";
  return reason;
}

function SafeBetaMetricBar({ label, keyName, value, active }) {
  const width = active ? 100 : 0;
  return (
    <div className="rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/70 px-3 py-2">
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-xs font-medium text-[#e2e8f0]">{label}</p>
          <p className="mt-0.5 truncate font-mono text-[9px] uppercase tracking-[0.2em] text-[#475569]" title={keyName}>{keyName}</p>
        </div>
        <span className={`shrink-0 font-mono text-sm font-bold tracking-tight ${active ? "text-[#00ffcc]" : "text-[#64748b]"}`}>
          {value || "-"}
        </span>
      </div>
      <div className="relative h-1.5 overflow-hidden rounded-sm border border-[#1c1f26] bg-black/35">
        <div className="absolute inset-y-0 left-0 bg-[#3f6f68]" style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

function isBrowserPreviewablePath(path) {
  return /^https?:\/\//i.test(path || "");
}

function makeSafeBetaQualityMetrics() {
  return [
    ["text_clarity_score", "文字清晰度", "待接入"],
    ["edge_quality_score", "边缘质量", "待接入"],
    ["color_fidelity_score", "色彩忠实度", "待接入"],
    ["texture_score", "纹理保持力", "待接入"],
  ];
}

function makeSafeBetaTimeline(item, result) {
  const progress = Number(item?.progress ?? result?.progress ?? 0);
  const status = item?.status || "";
  const reason = safeBetaReasonText(item, result);
  const hasOutput = Boolean(firstSafeBetaOutputPath(item, result));
  const hasContactSheet = Boolean(firstSafeBetaContactSheet(item, result));
  const failed = status === "failed" || ["BLOCKED", "FAILED"].includes(String(result?.status || "").toUpperCase());
  const skipped = reason !== "-" && (String(reason).includes("跳过") || item?.beta_status === "SKIPPED");
  const completed = status === "completed" || hasOutput;

  const phaseStatus = (threshold) => {
    if (failed) return "失败";
    if (skipped && threshold >= 55) return "跳过";
    if (completed) return "完成";
    if (progress >= threshold) return "执行中";
    return "等待";
  };

  return [
    { name: "图像读取", detail: "读取当前队列上传文件，确认真实 File 对象。", state: progress >= 15 || completed ? "完成" : phaseStatus(15) },
    { name: "安全判定", detail: "判断中文商业非人像 / 人物保护跳过 / 输入缺失。", state: skipped ? "跳过" : progress >= 35 || completed ? "完成" : phaseStatus(35) },
    { name: "安全增强", detail: "执行 1080P安全增强 Beta，不展示不存在的算法细分进度。", state: phaseStatus(55) },
    { name: "对比生成", detail: "生成 contact sheet / 输出映射。", state: hasContactSheet ? "完成" : completed ? "跳过" : phaseStatus(80) },
    { name: "交付输出", detail: "写入 output_path，准备统一反馈包入口。", state: hasOutput ? "完成" : phaseStatus(100) },
  ];
}

function makeSafeBetaStageLogs(item, result) {
  const logs = [];
  if (item?.file) logs.push("BETA_FILE_OBJECT_VALID");
  if (result?.status === "NEED_RESELECT") logs.push("BETA_FILE_OBJECT_MISSING");
  if (result?.beta_run_id) {
    logs.push("BETA_FORMDATA_BUILD_START");
    logs.push("BETA_FETCH_WILL_SEND");
    logs.push("BETA_FETCH_SENT");
  }
  if (result?.status && result.status !== "RUNNING") {
    logs.push("BETA_FETCH_RESPONSE_STATUS");
    logs.push("BETA_FETCH_RESPONSE_JSON");
  }
  if (item?.beta_status === "SKIPPED" || safeBetaReasonText(item, result).includes("跳过")) logs.push("BETA_INPUT_SKIPPED");
  if (item?.status === "completed") logs.push("BETA_DONE");
  if (item?.status === "failed" || ["BLOCKED", "FAILED"].includes(String(result?.status || "").toUpperCase())) logs.push("BETA_FAILED");
  return [...new Set(logs)];
}

function makeQueueId(file) {
  return `${Date.now()}_${Math.random().toString(16).slice(2)}_${file.name}`;
}

function makeBetaRunId() {
  return `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function logSafeBeta(betaRunId, stage, detail = {}) {
  const payload = { beta_run_id: betaRunId, stage, ...detail };
  const responsePayload = detail.payload || {};
  const fileValue = detail.frontend_selected_file_name || detail.current_file || responsePayload.current_file || "";
  const fileText = Array.isArray(fileValue) ? fileValue.filter(Boolean).join(",") : fileValue;
  const parts = [`[Safe1080pBeta] ${stage}`, `beta_run_id=${betaRunId || ""}`];
  if (fileText) parts.push(`file=${fileText}`);
  if (detail.url) parts.push(`url=${detail.url}`);
  if (detail.http_status != null) parts.push(`status=${detail.http_status}`);
  if (responsePayload.ok != null) parts.push(`ok=${responsePayload.ok}`);
  if (responsePayload.status) parts.push(`status=${responsePayload.status}`);
  if (detail.stage) parts.push(`stage=${detail.stage}`);
  if (detail.error) parts.push(`error=${detail.error}`);
  console.info(parts.join(" "), payload);
}

function isUsableLocalFile(file) {
  return (
    typeof File !== "undefined" &&
    file instanceof File &&
    typeof file.name === "string" &&
    typeof file.size === "number" &&
    typeof file.type === "string"
  );
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

async function requestBetaSafeEnhance(url, items, betaRunId) {
  logSafeBeta(betaRunId, "BETA_FORMDATA_BUILD_START", {
    frontend_selected_file_name: items.map((item) => item.name || item.file?.name || "image.png"),
  });
  const formData = new FormData();
  formData.append("beta_run_id", betaRunId);
  formData.append("mode", "safe_1080p");
  formData.append("output_dir", DEFAULT_SAFE_BETA_OUTPUT_DIR);
  formData.append("flat_output", "true");
  formData.append("business_output", "true");
  const selectedNames = items.map((item) => item.name || item.file?.name || "image.png");
  formData.append("selected_file_names_encoded", encodeURIComponent(JSON.stringify(selectedNames)));
  items.forEach((item, index) => {
    const selectedName = selectedNames[index];
    formData.append("selected_file_names", selectedName);
    if (!isUsableLocalFile(item?.file)) {
      logSafeBeta(betaRunId, "BETA_FILE_OBJECT_MISSING", { frontend_selected_file_name: selectedName });
      throw new Error("本地文件访问已失效，请重新选择图片");
    }
    formData.append("files", item.file, selectedName);
    logSafeBeta(betaRunId, "BETA_FORMDATA_FILE_APPENDED", {
      frontend_selected_file_name: selectedName,
      file_size: item.file.size,
      file_type: item.file.type,
    });
  });
  logSafeBeta(betaRunId, "BETA_FORMDATA_BUILD_DONE", {
    request_payload: {
      beta_run_id: betaRunId,
      mode: "safe_1080p",
      output_dir: DEFAULT_SAFE_BETA_OUTPUT_DIR,
      flat_output: true,
      business_output: true,
      files: selectedNames,
      selected_file_names: selectedNames,
      selected_file_names_encoded: true,
    },
  });
  logSafeBeta(betaRunId, "BETA_FETCH_WILL_SEND", { url });
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), SAFE_BETA_FETCH_TIMEOUT_MS);
  let response;
  try {
    const responsePromise = fetch(url, { method: "POST", body: formData, signal: controller.signal });
    logSafeBeta(betaRunId, "BETA_FETCH_SENT", { url });
    response = await responsePromise;
  } catch (error) {
    if (error?.name === "AbortError") {
      const timeoutError = new Error(`Beta request timed out after ${Math.round(SAFE_BETA_FETCH_TIMEOUT_MS / 1000)}s`);
      logSafeBeta(betaRunId, "BETA_FAILED_BRANCH_ENTERED", {
        stage: "BETA_FETCH_TIMEOUT",
        error: timeoutError.message,
        url,
      });
      throw timeoutError;
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
  logSafeBeta(betaRunId, "BETA_FETCH_RESPONSE_STATUS", { http_status: response.status });
  const rawText = await response.text();
  let payload = {};
  try {
    payload = JSON.parse(rawText || "{}");
  } catch (error) {
    throw new Error(`Beta response parse failed: ${error.message}`);
  }
  logSafeBeta(betaRunId, "BETA_FETCH_RESPONSE_JSON", { payload });
  if (!response.ok || payload.ok === false || payload.success === false || payload.status === "FAILED" || payload.status === "failed") {
    const error = new Error(formatBetaFailureMessage(payload, payload.stage || `Beta request failed: HTTP ${response.status}`));
    error.payload = payload;
    throw error;
  }
  return payload;
}

const isBetaSuccess = (data) =>
  data?.ok === true ||
  data?.success === true ||
  data?.status === "SUCCESS" ||
  data?.verification_result === "PASS" ||
  data?.code === 200 ||
  Number(data?.processed_count || 0) > 0 ||
  (Array.isArray(data?.enhanced_files) && data.enhanced_files.length > 0);

function formatBetaFailureMessage(payload, fallback = "1080P安全增强 Beta 处理失败") {
  const data = payload?.data || {};
  const skipped = Array.isArray(payload?.skipped) ? payload.skipped : Array.isArray(data?.skipped) ? data.skipped : [];
  const firstSkip = skipped.find((item) => item && typeof item === "object") || {};
  if (firstSkip.reason) {
    const file = firstSkip.file || payload?.current_file || data?.failed_file || "";
    return `${file ? `${file} ` : ""}被 1080P安全增强 Beta 安全策略跳过：${firstSkip.reason}`;
  }
  return payload?.error || payload?.message || data?.error_message || data?.reason || fallback;
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

  const handleSetJpg95CandidateReview = (decision) => {
    if (!activeItem) return;
    const option = findJpg95ReviewOption(decision);
    if (!option) return;
    const reviewFields = {
      candidate_is_final_output: false,
      jpg95_candidate_review_status: "reviewed",
      jpg95_candidate_review_decision: option.decision,
      jpg95_candidate_review_label: option.label,
      jpg95_candidate_recommendation: option.recommendation,
      jpg95_candidate_recommendation_reason: option.label,
      jpg95_candidate_review_note: option.label,
      jpg95_candidate_reviewed_at: new Date().toISOString(),
      final_output_source: "png_main",
    };
    updateQueueItem(activeItem.id, reviewFields);
    setSafeBetaResult((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        processed: (prev.processed || []).map((row) => (isSameSafeBetaRow(row, activeItem) ? { ...row, ...reviewFields } : row)),
      };
    });
    setNotice(`JPG95 candidate 人工复核建议：${option.label}`);
  };

  const addFiles = (incomingFiles, options = {}) => {
    const replaceQueue = Boolean(options.replaceQueue);
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
    if (replaceQueue) {
      setFileQueue(nextItems);
      setActiveItemId(nextItems[0]?.id || null);
      setDebugItemId(nextItems[0]?.id || null);
      setSafeBetaResult(null);
      setSafeBetaFeedbackResult(null);
      setSafeBetaStartedAt(null);
      setSafeBetaTick(0);
      setCurrentIndex(0);
      setNotice(`已重新选择 ${nextItems.length} 张，Beta 状态已重置。`);
      return;
    }
    setFileQueue((prev) => [...prev, ...nextItems]);
    if (!activeItemId && nextItems[0]) setActiveItemId(nextItems[0].id);
    setNotice(`已选择 ${fileQueue.length + nextItems.length} 张。`);
  };

  const handleFileChange = (event) => {
    addFiles(event.target.files, { replaceQueue: processingMode === PROCESSING_MODE_SAFE_BETA });
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
    const betaRunId = makeBetaRunId();
    const betaItems = fileQueue.filter((item) => item.status === "queued" || item.status === "failed" || item.status === "processing");
    const betaItemIds = betaItems.map((item) => item.id);
    const firstFileName = betaItems[0]?.name || "";
    const firstCurrentFile = firstFileName || "正在连接 Beta 后端";
    logSafeBeta(betaRunId, "BETA_CLICK_HANDLER_ENTERED", {
      selected_count: betaItems.length,
      processing_mode: processingMode,
    });
    logSafeBeta(betaRunId, "BETA_SELECTED_ROWS_SNAPSHOT", {
      rows: betaItems.map((item) => ({
        id: item.id,
        name: item.name,
        status: item.status,
        has_file_object: isUsableLocalFile(item.file),
      })),
    });
    const setBetaQueuePatch = (patch) => {
      if (!betaItemIds.length) return;
      setFileQueue((prev) => prev.map((item) => (betaItemIds.includes(item.id) ? { ...item, ...patch } : item)));
    };
    if (!betaItems.length) {
      setSafeBetaResult({
        status: "BLOCKED",
        beta_run_id: betaRunId,
        progress: 100,
        current_file: "",
        processed_count: 0,
        enhanced_count: 0,
        contact_sheet_count: 0,
        skipped_count: 0,
        output_dir: DEFAULT_SAFE_BETA_OUTPUT_DIR,
        has_enhanced: false,
        has_contact_sheet: false,
        elapsed_seconds: 0,
        message: "队列中没有待处理图片。",
      });
      setNotice("队列中没有待处理图片。");
      return;
    }
    logSafeBeta(betaRunId, "BETA_FILE_OBJECT_CHECK_START", {
      frontend_selected_file_name: betaItems.map((item) => item.name),
    });
    const invalidBetaItems = betaItems.filter((item) => !isUsableLocalFile(item.file));
    if (invalidBetaItems.length) {
      const message = "本地文件访问已失效，请重新选择图片";
      const currentFile = invalidBetaItems[0]?.name || firstFileName || "本地文件";
      logSafeBeta(betaRunId, "BETA_FILE_OBJECT_MISSING", {
        frontend_selected_file_name: invalidBetaItems.map((item) => item.name),
      });
      setSafeBetaResult({
        status: "NEED_RESELECT",
        beta_run_id: betaRunId,
        progress: 100,
        current_file: currentFile,
        processed_count: 0,
        enhanced_count: 0,
        contact_sheet_count: 0,
        skipped_count: 0,
        output_dir: DEFAULT_SAFE_BETA_OUTPUT_DIR,
        has_enhanced: false,
        has_contact_sheet: false,
        elapsed_seconds: 0,
        message,
      });
      setBetaQueuePatch({
        status: "need_reselect",
        progress: 100,
        output_dir: DEFAULT_SAFE_BETA_OUTPUT_DIR,
        output_filename: "",
        final_delivery_status: "",
        final_delivery_reason: message,
        error: message,
        logs: [message],
      });
      logSafeBeta(betaRunId, "BETA_FINAL_STATE_APPLIED", {
        status: "NEED_RESELECT",
        frontend_selected_file_name: currentFile,
      });
      setNotice(message);
      return;
    }
    logSafeBeta(betaRunId, "BETA_FILE_OBJECT_VALID", {
      frontend_selected_file_name: betaItems.map((item) => item.name),
    });
    const setBetaQueueCompleted = (results, processedRows, fallbackOutputPath, fallbackOutputName) => {
      if (!betaItemIds.length) return;
      setFileQueue((prev) =>
        prev.map((item) => {
          if (!betaItemIds.includes(item.id)) return item;
          const mapped = results.find((row) => row.input_name === item.name) || results[0] || {};
          const processed = processedRows.find((row) => row.input_name === item.name || row.file === item.name) || {};
          const outputPath = mapped.output_path || fallbackOutputPath || "";
          const outputName = mapped.output_name || fallbackOutputName || (outputPath ? outputPath.split(/[\\/]/).pop() : "");
          return {
            ...item,
            status: "completed",
            progress: 100,
            output_dir: DEFAULT_SAFE_BETA_OUTPUT_DIR,
            output_filename: outputName || "已生成",
            output_path: outputPath,
            contact_sheet: processed.contact_sheet || "",
            contact_sheet_light: processed.contact_sheet_light || "",
            contact_sheet_light_size_bytes: processed.contact_sheet_light_size_bytes ?? null,
            contact_sheet_light_format: processed.contact_sheet_light_format || "",
            contact_sheet_light_role: processed.contact_sheet_light_role || "preview_only",
            jpg95_candidate_path: processed.jpg95_candidate_path || "",
            jpg95_candidate_size_bytes: processed.jpg95_candidate_size_bytes ?? null,
            jpg95_candidate_saved_ratio: processed.jpg95_candidate_saved_ratio ?? null,
            jpg95_candidate_format: processed.jpg95_candidate_format || "",
            jpg95_candidate_quality: processed.jpg95_candidate_quality ?? null,
            jpg95_candidate_role: processed.jpg95_candidate_role || "",
            jpg95_candidate_status: processed.jpg95_candidate_status || "",
            jpg95_candidate_reason: processed.jpg95_candidate_reason || "",
            light_delivery_path: processed.light_delivery_path || "",
            light_delivery_size_bytes: processed.light_delivery_size_bytes ?? null,
            light_delivery_format: processed.light_delivery_format || "",
            light_delivery_quality: processed.light_delivery_quality ?? null,
            light_delivery_role: processed.light_delivery_role || "",
            light_delivery_source: processed.light_delivery_source || "",
            light_delivery_status: processed.light_delivery_status || "",
            light_delivery_reason: processed.light_delivery_reason || "",
            light_delivery_saved_ratio: processed.light_delivery_saved_ratio ?? null,
            candidate_is_final_output: false,
            jpg95_candidate_review_status: processed.jpg95_candidate_review_status || "",
            jpg95_candidate_review_decision: processed.jpg95_candidate_review_decision || "",
            jpg95_candidate_review_label: processed.jpg95_candidate_review_label || "",
            jpg95_candidate_recommendation: processed.jpg95_candidate_recommendation || "",
            jpg95_candidate_recommendation_reason: processed.jpg95_candidate_recommendation_reason || "",
            jpg95_candidate_review_note: processed.jpg95_candidate_review_note || "",
            jpg95_candidate_reviewed_at: processed.jpg95_candidate_reviewed_at || "",
            final_output_source: processed.final_output_source || "png_main",
            final_output_fallback_reason: processed.final_output_fallback_reason || "",
            contact_sheet_url:
              processed.contact_sheet_light_url ||
              processed.contact_sheet_light_preview_url ||
              processed.contact_sheet_url ||
              processed.contact_sheet_preview_url ||
              mapped.contact_sheet_light_url ||
              mapped.contact_sheet_light_preview_url ||
              mapped.contact_sheet_url ||
              mapped.contact_sheet_preview_url ||
              "",
            output_url: processed.output_url || processed.preview_url || processed.public_url || mapped.output_url || mapped.preview_url || mapped.public_url || "",
            beta_result: mapped,
            beta_processed: processed,
            beta_status: "PASS",
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
    setActiveScreen("safe_beta_task");
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
      beta_run_id: betaRunId,
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
        beta_run_id: betaRunId,
        frontend_selected_file_name: betaItems.map((item) => item.name),
        request_payload: {
          beta_run_id: betaRunId,
          mode: "safe_1080p",
          output_dir: DEFAULT_SAFE_BETA_OUTPUT_DIR,
          flat_output: true,
          business_output: true,
          files: betaItems.map((item) => item.name),
        },
      });
      const payload = await requestBetaSafeEnhance(`${API_BASE}/api/beta/safe-1080p/enhance`, betaItems, betaRunId);
      const data = payload?.data || {};
      if (!isBetaSuccess(payload) && !isBetaSuccess(data)) {
        throw new Error(payload?.error || payload?.message || data?.error_message || data?.reason || "Beta run failed");
      }
      logSafeBeta(betaRunId, "BETA_SUCCESS_BRANCH_ENTERED", {
        response_beta_run_id: payload.beta_run_id || data.beta_run_id || "",
      });
      const results = Array.isArray(payload.results) ? payload.results : Array.isArray(data.results) ? data.results : [];
      const enhancedFiles = Array.isArray(payload.enhanced_files) ? payload.enhanced_files : Array.isArray(data.enhanced_files) ? data.enhanced_files : [];
      const processedItems = (Array.isArray(data.processed) ? data.processed : []).map(addJpg95ReviewDefaults);
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
        beta_run_id: payload.beta_run_id || data.beta_run_id || betaRunId,
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
      setBetaQueueCompleted(results, processedItems, firstEnhanced, firstOutputName);
      logSafeBeta(betaRunId, "BETA_FINAL_STATE_APPLIED", {
        status: resultStatus,
        progress: 100,
        processed_count: processedCount,
      });
      setNotice(`1080P安全增强 Beta 完成：${resultStatus}`);
    } catch (error) {
      const errorPayload = error?.payload || {};
      const errorData = errorPayload?.data || {};
      const skippedRows = Array.isArray(errorPayload.skipped) ? errorPayload.skipped : Array.isArray(errorData.skipped) ? errorData.skipped : [];
      const skippedCount = Number(errorPayload.skipped_count ?? errorData.skipped_count ?? skippedRows.length ?? 0);
      const failureMessage = formatBetaFailureMessage(errorPayload, error.message);
      logSafeBeta(betaRunId, "BETA_FAILED_BRANCH_ENTERED", {
        error: failureMessage,
        stage: errorPayload.stage || "",
      });
      setSafeBetaResult({
        status: "BLOCKED",
        beta_run_id: errorPayload.beta_run_id || betaRunId,
        progress: 100,
        current_file: errorData.failed_file || skippedRows[0]?.file || firstFileName || "处理失败",
        processed_count: 0,
        enhanced_count: 0,
        contact_sheet_count: 0,
        skipped_count: skippedCount,
        output_dir: errorPayload.output_dir || errorData.output_dir || DEFAULT_SAFE_BETA_OUTPUT_DIR,
        has_enhanced: false,
        has_contact_sheet: false,
        elapsed_seconds: Math.round((Date.now() - startedAt) / 1000),
        skipped: skippedRows,
        message: failureMessage,
      });
      setFileQueue((prev) =>
        prev.map((item) => {
          if (!betaItemIds.includes(item.id)) return item;
          const skipped = skippedRows.find((row) => row?.input_name === item.name || row?.file === item.name) || skippedRows[0] || {};
          const itemMessage = skipped?.reason ? `${item.name} 被 1080P安全增强 Beta 安全策略跳过：${skipped.reason}` : failureMessage;
          return {
            ...item,
            status: "failed",
            progress: 100,
            output_dir: errorPayload.output_dir || errorData.output_dir || DEFAULT_SAFE_BETA_OUTPUT_DIR,
            output_filename: "",
            final_delivery_status: "FAIL",
            final_delivery_reason: itemMessage,
            beta_skipped: skipped,
            beta_status: skipped?.reason ? "SKIPPED" : "FAILED",
            error: itemMessage,
            logs: [itemMessage],
          };
        }),
      );
      logSafeBeta(betaRunId, "BETA_FINAL_STATE_APPLIED", {
        status: "BLOCKED",
        error: failureMessage,
      });
      setNotice(`1080P安全增强 Beta 处理失败：${failureMessage}`);
    } finally {
      stageTimers.forEach((timer) => window.clearTimeout(timer));
      processingRef.current = false;
      setIsProcessingQueue(false);
      setCurrentIndex(0);
      setActiveScreen("safe_beta_task");
    }
  };
  const exportSafeBetaFeedbackPackage = async () => {
    if (!safeBetaResult?.output_dir) return;
    try {
      const activeReviewFields = pickJpg95ReviewFields(activeItem || {});
      const processedForFeedback = (safeBetaResult.processed || []).map((row) =>
        isSameSafeBetaRow(row, activeItem) ? { ...row, ...activeReviewFields, candidate_is_final_output: false, final_output_source: "png_main" } : row,
      );
      const payload = await requestJson("POST", `${API_BASE}/api/beta/safe-1080p/feedback-package`, {
        run_result: {
          status: "ok",
          verification_result: safeBetaResult.status,
          mode: "safe_1080p",
          input_dir: safeBetaResult.input_dir || "",
          output_dir: safeBetaResult.output_dir,
          processed_count: safeBetaResult.processed_count || 0,
          skipped_count: safeBetaResult.skipped_count || 0,
          beta_run_id: safeBetaResult.beta_run_id || "",
          current_file: safeBetaResult.current_file || activeItem?.name || "",
          stage: safeBetaResult.stage || "",
          error: safeBetaResult.message || activeItem?.error || "",
          message: safeBetaResult.message || "",
          results: safeBetaResult.results || [],
          enhanced_files: safeBetaResult.enhanced_files || [],
          processed: processedForFeedback,
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

  const locateQueueItem = (item) => {
    if (!item) return;
    setActiveItemId(item.id);
    setDebugItemId(item.id);
    if (item.mode === PROCESSING_MODE_SAFE_BETA) {
      const outputPath = firstSafeBetaOutputPath(item, safeBetaResult);
      const stateText = safeBetaItemStatusText(item, safeBetaResult);
      setActiveScreen("safe_beta_task");
      setNotice(`已定位：${item.name}｜${stateText}${outputPath ? `｜${outputPath}` : ""}`);
      return;
    }
    setNotice(`已定位：${item.name}`);
  };

  const selectForCompare = (item) => {
    if (item?.mode === PROCESSING_MODE_SAFE_BETA) {
      locateQueueItem(item);
      const contactSheet = firstSafeBetaContactSheet(item, safeBetaResult);
      const outputPath = firstSafeBetaOutputPath(item, safeBetaResult);
      if (contactSheet || outputPath) {
        setActiveScreen("safe_beta_compare");
        setNotice(contactSheet ? "已打开 1080P安全增强版 Beta 对比查看。" : "当前图片没有 contact sheet，已显示输出路径，请打开输出目录查看增强图。");
        return;
      }
      setNotice("当前图片尚未生成对比图，请先运行 1080P安全增强 Beta。");
      return;
    }
    if (!item?.final_output_url) return;
    setActiveItemId(item.id);
    setActiveScreen("image_compare");
  };

  const selectForReport = (item) => {
    if (item?.mode === PROCESSING_MODE_SAFE_BETA) {
      locateQueueItem(item);
      setActiveScreen("safe_beta_report");
      setNotice("已打开 1080P安全增强版 Beta 交付报告。");
      return;
    }
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
    if (item?.mode === PROCESSING_MODE_SAFE_BETA) {
      setNotice("Beta 成品为本地文件，请使用“打开当前目录”或复制成品路径查看。");
      return;
    }
    if (!item?.final_output_url) return;
    window.open(item.final_output_url, "_blank", "noopener,noreferrer");
  };

  const handleCopyFinalOutputUrl = async (item) => {
    const betaPath = item?.mode === PROCESSING_MODE_SAFE_BETA ? firstSafeBetaOutputPath(item, safeBetaResult) : "";
    const value = betaPath || item?.final_output_url || "";
    if (!value) {
      setNotice(item?.mode === PROCESSING_MODE_SAFE_BETA ? "当前 Beta 任务还没有可复制的成品路径。" : "当前任务还没有可复制的成品映射路径。");
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      setNotice(betaPath ? "已复制 Beta 成品本地路径。" : "已复制成品映射 URL。");
    } catch (error) {
      setNotice(error.message || "复制成品路径失败。");
    }
  };

  const handleCopySafeBetaPath = async (value, label = "路径") => {
    if (!value) {
      setNotice(`当前没有可复制的 ${label}。`);
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      setNotice(`已复制 ${label}。`);
    } catch (error) {
      setNotice(error.message || `复制 ${label} 失败。`);
    }
  };

  const handleOpenSafeBetaPathDir = (value, label = "文件") => {
    if (!value) {
      setNotice(`当前没有可打开的 ${label} 路径。`);
      return;
    }
    const dir = String(value).replace(/[\\/][^\\/]*$/, "");
    if (!dir || dir === value) {
      setNotice(`无法解析 ${label} 所在文件夹。`);
      return;
    }
    requestJson("POST", `${API_BASE}/api/output/open`, { output_dir: dir })
      .then((payload) => {
        setOutputDirError("");
        setOutputDirSuccess("");
        setNotice(payload.message || `已打开 ${label} 所在文件夹。`);
      })
      .catch((error) => {
        setOutputDirError(error.message);
        setOutputDirSuccess("");
        setNotice(error.message);
      });
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

  if (activeScreen === "safe_beta_task") {
    const outputPath = firstSafeBetaOutputPath(activeItem, safeBetaResult);
    const contactSheet = firstSafeBetaContactSheet(activeItem, safeBetaResult);
    const reasonText = safeBetaReasonText(activeItem, safeBetaResult);
    const statusTextValue = safeBetaItemStatusText(activeItem, safeBetaResult);
    const isPortraitSkip = reasonText === "人物图保护跳过";
    const deliveryConclusion = isPortraitSkip ? "人物图保护跳过" : outputPath ? "建议查看后使用" : activeItem?.status === "failed" ? "不建议交付" : "等待";
    const canViewCompare = Boolean(contactSheet || outputPath);
    const timeline = makeSafeBetaTimeline(activeItem, safeBetaResult);
    const betaLogs = makeSafeBetaStageLogs(activeItem, safeBetaResult);
    return (
      <section className="flex h-[100dvh] w-full flex-col overflow-hidden bg-[#0b0c0e] p-4 text-slate-100">
        <header className="mb-4 flex shrink-0 items-center justify-between gap-5 rounded-sm border border-[#1c1f26] bg-[#121418] p-4">
          <div className="min-w-0">
            <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">SAFE 1080P BETA / CORE TASK</p>
            <h1 className="mt-2 truncate text-xl font-semibold tracking-wide text-white">1080P安全增强版 Beta · 核心增强任务页</h1>
            <p className="mt-1 truncate font-mono text-xs text-[#64748b]" title={activeItem?.name || ""}>
              beta_run_id: {safeBetaResult?.beta_run_id || "-"} · 当前文件：{activeItem?.name || safeBetaResult?.current_file || "等待任务"}
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            <button type="button" onClick={() => setActiveScreen("dashboard")} className="rounded-sm border border-[#333] bg-[#1c1f26] px-3 py-2 text-xs text-[#94a3b8] transition hover:bg-[#2d3139] hover:text-white">返回工作台</button>
            <button type="button" disabled={!canViewCompare} title={!canViewCompare ? "当前尚未生成对比图" : ""} onClick={() => selectForCompare(activeItem)} className="rounded-sm border border-[#2d665f] px-3 py-2 text-xs text-[#5bf5dc] transition hover:bg-[#163631] disabled:cursor-not-allowed disabled:border-[#1c1f26] disabled:text-[#475569]">查看高清对比</button>
            <button type="button" onClick={() => selectForReport(activeItem)} className="rounded-sm border border-[#66532d] bg-[#17130a] px-3 py-2 text-xs text-[#f0c36f] transition hover:bg-[#211b0e]">查看交付报告</button>
          </div>
        </header>

        <main className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_360px] gap-4">
          <section className="flex min-h-0 flex-col gap-4 overflow-hidden">
            <div className="grid shrink-0 grid-cols-2 gap-3 rounded-sm border border-[#1c1f26] bg-[#121418] p-4 text-xs">
              {[
                ["模式", "1080P安全增强版 Beta"],
                ["目标规格", "1080P安全增强"],
                ["当前状态", statusTextValue],
                ["交付结论", deliveryConclusion],
                ["输出路径", outputPath || "未生成"],
                ["contact sheet", contactSheet || "未生成"],
              ].map(([label, value]) => (
                <div key={label} className="min-w-0 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/45 p-3">
                  <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-[#475569]">{label}</p>
                  <p className="mt-1 truncate text-sm text-[#e2e8f0]" title={String(value)}>{value}</p>
                </div>
              ))}
            </div>

            <section className="min-h-0 flex-1 rounded-sm border border-[#1c1f26] bg-[#121418] p-4">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Progress Timeline</p>
                  <h2 className="mt-2 text-lg font-semibold text-white">核心增强阶段</h2>
                </div>
                <span className="font-mono text-xs text-[#64748b]">{safeBetaResult?.progress ?? activeItem?.progress ?? 0}%</span>
              </div>
              <div className="space-y-3">
                {timeline.map((stage, index) => {
                  const color = stage.state === "完成" ? "text-[#8be6b1]" : stage.state === "执行中" ? "text-[#6feaf0]" : stage.state === "跳过" ? "text-[#f0c36f]" : stage.state === "失败" ? "text-[#ff8a8a]" : "text-[#64748b]";
                  return (
                    <div key={stage.name} className="grid grid-cols-[32px_minmax(0,1fr)_72px] items-start gap-3 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/35 p-3">
                      <div className="flex h-7 w-7 items-center justify-center rounded-sm border border-[#263738] font-mono text-xs text-[#94a3b8]">{index + 1}</div>
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-[#e2e8f0]">{stage.name}</p>
                        <p className="mt-1 text-xs leading-5 text-[#64748b]">{stage.detail}</p>
                      </div>
                      <span className={`text-right text-xs font-semibold ${color}`}>{stage.state}</span>
                    </div>
                  );
                })}
              </div>
            </section>
          </section>

          <aside className="flex min-h-0 flex-col gap-4">
            <section className="rounded-sm border border-[#1c1f26] bg-[#121418] p-4">
              <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">BETA STAGE LOG</p>
              <h2 className="mt-2 text-lg font-semibold text-white">安全增强阶段日志</h2>
              <p className="mt-1 text-xs leading-5 text-[#64748b]">这是 Beta 前端阶段日志，不是标准 SSE。</p>
              <div className="mt-4 max-h-[280px] space-y-2 overflow-y-auto pr-1">
                {(betaLogs.length ? betaLogs : ["等待 Beta 阶段日志"]).map((item) => (
                  <div key={item} className="rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/45 px-3 py-2 font-mono text-[11px] text-[#94a3b8]">{item}</div>
                ))}
              </div>
            </section>

            <section className="rounded-sm border border-[#1c1f26] bg-[#121418] p-4">
              <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Unified Actions</p>
              <h2 className="mt-2 text-lg font-semibold text-white">可用操作</h2>
              <div className="mt-4 grid gap-2">
                <button type="button" onClick={handleOpenOutputDir} className="rounded-sm border border-[#333] bg-[#1c1f26] px-4 py-2 text-xs text-[#e2e8f0] transition hover:bg-[#2d3139]">打开输出目录</button>
                <button type="button" disabled={!outputPath} onClick={() => handleCopyFinalOutputUrl(activeItem)} className="rounded-sm border border-[#333] px-4 py-2 text-xs text-[#e2e8f0] transition hover:bg-[#1c1f26] disabled:cursor-not-allowed disabled:text-[#475569]">复制成品路径</button>
                <button type="button" onClick={exportSafeBetaFeedbackPackage} disabled={!safeBetaResult?.output_dir || isProcessingQueue} className="rounded-sm bg-[#10b981] px-4 py-2 text-xs font-bold text-[#0b0c0e] transition hover:bg-[#059669] disabled:cursor-not-allowed disabled:bg-[#1c1f26] disabled:text-[#475569]">导出测试反馈包 / 反馈包中心</button>
              </div>
            </section>
          </aside>
        </main>

        <footer className="mt-3 shrink-0 truncate border-t border-[#1c1f26] pt-2 text-center font-mono text-[10px] tracking-wider text-[#64748b]">
          影界 HDDE V0.4.6 RC1 · HD Delivery Engine · 中文视觉高清交付引擎
        </footer>
      </section>
    );
  }

  if (activeScreen === "safe_beta_compare") {
    const outputPath = firstSafeBetaOutputPath(activeItem, safeBetaResult);
    const contactSheet = firstSafeBetaContactSheet(activeItem, safeBetaResult);
    const contactSheetLight = firstSafeBetaContactSheetLight(activeItem, safeBetaResult);
    const processed = findSafeBetaProcessedRow(activeItem, safeBetaResult);
    const outputName = activeItem?.output_filename || processed?.output_name || (outputPath ? outputPath.split(/[\\/]/).pop() : "");
    const statusTextValue = safeBetaItemStatusText(activeItem, safeBetaResult);
    const deliveryText = activeItem?.final_delivery_status === "PASS_WITH_LIMITATION" ? "建议查看后使用" : activeItem?.final_delivery_reason || statusTextValue;
    const contactSheetPreviewUrl = firstSafeBetaContactSheetPreviewUrl(activeItem, safeBetaResult);
    const outputPreviewUrl = firstSafeBetaOutputPreviewUrl(activeItem, safeBetaResult);
    const previewImageUrl = contactSheetPreviewUrl || outputPreviewUrl;
    const previewImageLabel = contactSheetPreviewUrl ? "CONTACT SHEET" : outputPreviewUrl ? "OUTPUT PREVIEW" : "";
    const compareTitle = previewImageUrl ? "1080P安全增强版 Beta · 对比结果" : "1080P安全增强版 Beta · 本地对比查看";
    const compareMetrics = makeSafeBetaQualityMetrics();
    const compareStatusRows = [
      ["成品状态", outputPath ? "已生成" : statusTextValue],
      ["contact sheet", contactSheet ? "已生成" : "未生成"],
      ["网页预览", previewImageUrl ? "已接入" : "未接入"],
      ["本地路径", contactSheet || outputPath ? "已绑定" : "未绑定"],
      ["交付结论", deliveryText || "-"],
    ];
    return (
      <section className="relative flex h-[100dvh] w-full flex-col overflow-hidden bg-[#060b0c] p-6 text-slate-200">
        <div className="pointer-events-none absolute inset-0 bg-[#060b0c]" />
        <header className="relative z-10 mb-4 flex h-[82px] shrink-0 items-center justify-between gap-6 border-b border-[#14282a] pb-4">
          <div className="min-w-0">
            <p className="font-mono text-[10px] font-bold uppercase tracking-[0.28em] text-[#418c80]">影界 HDDE V0.4.6 RC1 / SAFE BETA COMPARE</p>
            <h1 className="mt-2 truncate text-2xl font-semibold tracking-wide text-slate-100">{compareTitle}</h1>
            <p className="mt-1 truncate font-mono text-xs text-slate-500" title={activeItem?.name || ""}>
              前后对比 · 1080P安全增强版 Beta · {activeItem?.name || "未选择样本"}
            </p>
          </div>

          <div className="flex shrink-0 gap-3">
            <button type="button" onClick={() => setActiveScreen("dashboard")} className="rounded-sm border border-[#193336] px-4 py-2 text-xs tracking-wide text-[#8a999c] transition hover:bg-[#112426] hover:text-slate-200">
              返回工作台
            </button>
            <button type="button" onClick={() => setActiveScreen("safe_beta_report")} className="rounded-sm border border-[#2d665f] bg-[#163631] px-5 py-2 font-mono text-xs font-bold uppercase tracking-widest text-[#5bf5dc] transition hover:brightness-125">
              查看交付报告
            </button>
          </div>
        </header>

        <main className="relative z-10 grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_360px] gap-5">
          <section className="relative h-full min-h-0 overflow-hidden rounded-lg border border-[#193336] bg-[#040708] shadow-[0_40px_140px_rgba(60,179,160,0.14)]">
            {previewImageUrl ? (
              <img src={previewImageUrl} alt="1080P安全增强版 Beta contact sheet" className="absolute inset-0 h-full w-full object-contain" />
            ) : contactSheet ? (
              <div className="absolute inset-0 flex items-center justify-center bg-[#05090a]">
                <div className="max-w-2xl px-8 text-center">
                  <div className="mx-auto mb-4 h-12 w-12 rounded-full border border-[#3cb3a0]/45 bg-[#3cb3a0]/10" />
                  <p className="font-mono text-xs uppercase tracking-[0.28em] text-[#3cb3a0]/70">本地预览未接入</p>
                  <p className="mt-3 text-sm leading-7 text-slate-400">contact sheet 已生成，但当前浏览器页面无法直接读取 Windows 本地文件。请点击“打开输出目录”查看本地对比图，或复制成品路径进行复核。</p>
                  <div className="mt-4 grid grid-cols-3 gap-2 text-left text-xs">
                    <div className="rounded border border-[#193336] bg-[#0d181a] p-2"><span className="text-slate-500">contact sheet：</span><span className="text-[#8effed]">已生成</span></div>
                    <div className="rounded border border-[#193336] bg-[#0d181a] p-2"><span className="text-slate-500">网页预览：</span><span className="text-[#f0c36f]">未接入</span></div>
                    <div className="rounded border border-[#193336] bg-[#0d181a] p-2"><span className="text-slate-500">本地路径：</span><span className="text-[#8effed]">已绑定</span></div>
                  </div>
                  <p className="mt-4 break-all rounded border border-[#193336] bg-[#0d181a] p-3 text-left font-mono text-xs leading-6 text-slate-500">{contactSheet}</p>
                  <div className="mt-4 flex justify-center gap-3">
                    <button type="button" onClick={handleOpenOutputDir} className="rounded-sm border border-[#333] bg-[#1c1f26] px-4 py-2 text-xs text-[#e2e8f0] transition hover:bg-[#2d3139]">打开输出目录</button>
                    <button type="button" disabled={!outputPath} onClick={() => handleCopyFinalOutputUrl(activeItem)} className="rounded-sm border border-[#333] px-4 py-2 text-xs text-[#e2e8f0] transition hover:bg-[#1c1f26] disabled:cursor-not-allowed disabled:text-[#475569]">复制成品路径</button>
                  </div>
                </div>
              </div>
            ) : outputPath ? (
              <div className="absolute inset-0 flex items-center justify-center bg-[#05090a]">
                <div className="max-w-2xl px-8 text-center">
                  <div className="mx-auto mb-4 h-12 w-12 rounded-full border border-[#f0c36f]/45 bg-[#f0c36f]/10" />
                  <p className="font-mono text-xs uppercase tracking-[0.28em] text-[#f0c36f]">Output Ready</p>
                  <p className="mt-3 text-sm leading-7 text-slate-400">本地预览不可用，当前没有 contact sheet，可打开输出目录查看增强图。</p>
                  <p className="mt-4 break-all rounded border border-[#193336] bg-[#0d181a] p-3 text-left font-mono text-xs leading-6 text-slate-500">{outputPath}</p>
                  <div className="mt-4 flex justify-center gap-3">
                    <button type="button" onClick={handleOpenOutputDir} className="rounded-sm border border-[#333] bg-[#1c1f26] px-4 py-2 text-xs text-[#e2e8f0] transition hover:bg-[#2d3139]">打开输出目录</button>
                    <button type="button" onClick={() => handleCopyFinalOutputUrl(activeItem)} className="rounded-sm border border-[#333] px-4 py-2 text-xs text-[#e2e8f0] transition hover:bg-[#1c1f26]">复制成品路径</button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="absolute inset-0 flex items-center justify-center bg-[#05090a]">
                <div className="max-w-md px-8 text-center">
                  <div className="mx-auto mb-4 h-12 w-12 rounded-full border border-[#3cb3a0]/45 bg-[#3cb3a0]/10" />
                  <p className="font-mono text-xs uppercase tracking-[0.28em] text-[#3cb3a0]/70">Waiting Compare</p>
                  <p className="mt-3 text-sm leading-7 text-slate-500">当前尚未生成对比图。</p>
                </div>
              </div>
            )}

            {previewImageUrl ? (
              <div className="absolute left-5 top-5 z-20 rounded border border-[#3cb3a0]/35 bg-[#3cb3a0]/10 px-4 py-2 font-mono text-[10px] uppercase tracking-[0.24em] text-[#8effed] backdrop-blur-md">
                {previewImageLabel}
              </div>
            ) : null}
            <div className="absolute bottom-4 right-4 z-20 max-w-[85%] truncate rounded border border-white/10 bg-black/55 px-4 py-2 text-right font-mono text-[10px] tracking-[0.2em] text-white/40 backdrop-blur-md">
              影界 HDDE V0.4.6 RC1 · {activeItem?.name || "等待真实上传资产"} · HD Delivery Engine
            </div>
          </section>

          <aside className="flex h-full min-h-0 flex-col gap-4">
            <div className="rounded-lg border border-[#132628] bg-[#091113] p-5">
              <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Physical QA</p>
              <h2 className="mt-2 text-xl font-semibold text-slate-100">高清交付指标</h2>
              <p className="mt-2 truncate text-xs text-slate-500">{activeItem?.name || "未选择样本"} · 1080P安全增强版 Beta</p>
              <div className="mt-5 space-y-3">
                {compareMetrics.map(([keyName, name, value]) => (
                  <div key={keyName} className="rounded border border-[#193336] bg-[#0d181a] p-3">
                    <div className="flex items-center justify-between gap-4">
                      <div>
                        <p className="font-mono text-[9px] uppercase tracking-[0.22em] text-[#418c80]">{keyName}</p>
                        <p className="mt-1 text-xs text-slate-400">{name}</p>
                      </div>
                      <span className="font-mono text-sm font-bold text-slate-500">{value}</span>
                    </div>
                    <div className="mt-3 h-[3px] overflow-hidden rounded-full bg-[#0e1d1f]">
                      <div className="h-full rounded-full bg-[#3f6f68]" style={{ width: "0%" }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-[#132628] bg-[#091113] p-5">
              <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Output Binding</p>
              <h2 className="mt-2 text-xl font-semibold text-slate-100">字段绑定</h2>
              <div className="mt-4 space-y-3 font-mono text-xs text-slate-400">
                {[
                  ...compareStatusRows,
                  ["输出文件", outputName || "未生成"],
                  ["输出绑定", outputPath || "未绑定"],
                  ["contact sheet", contactSheet || "未生成"],
                ].map(([label, value]) => (
                  <div key={label} className="min-w-0 overflow-hidden rounded border border-[#193336] bg-[#0d181a] p-3">
                    <span className="text-slate-500">{label}：</span>
                    <span className="break-words" title={String(value)}>{value}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-[#132628] bg-[#091113] p-5">
              <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Manual Review</p>
              <h2 className="mt-2 text-xl font-semibold text-slate-100">人工复核清单</h2>
              <div className="mt-4 min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
                {["文字与 Logo 是否保持可读", "边缘是否无明显光晕", "颜色是否接近原图", "是否适合交付使用"].map((item, index) => (
                  <label key={item} className="flex items-start gap-3 rounded border border-[#193336] bg-[#0d181a] p-3 text-sm text-slate-300">
                    <input className="mt-1 accent-[#3cb3a0]" type="checkbox" defaultChecked={index < 2} />
                    <span>{item}</span>
                  </label>
                ))}
              </div>
            </div>
          </aside>
        </main>

        <footer className="relative z-10 mt-3 w-full shrink-0 truncate border-t border-[#0e1d1f] px-3 pt-2 text-center font-mono text-[10px] tracking-wider text-slate-600">
          影界 HDDE V0.4.6 RC1 · HD Delivery Engine · 中文视觉高清交付引擎
        </footer>
      </section>
    );
  }

  if (activeScreen === "safe_beta_report") {
    const outputPath = firstSafeBetaOutputPath(activeItem, safeBetaResult);
    const contactSheet = firstSafeBetaContactSheet(activeItem, safeBetaResult);
    const contactSheetLight = firstSafeBetaContactSheetLight(activeItem, safeBetaResult);
    const processed = findSafeBetaProcessedRow(activeItem, safeBetaResult);
    const statusTextValue = safeBetaItemStatusText(activeItem, safeBetaResult);
    const reasonText = safeBetaReasonText(activeItem, safeBetaResult);
    const outputName = activeItem?.output_filename || processed?.output_name || (outputPath ? outputPath.split(/[\\/]/).pop() : "");
    const inputSizeBytes = processed?.input_size_bytes ?? activeItem?.input_size_bytes ?? safeBetaResult?.input_size_bytes ?? null;
    const outputSizeBytes = processed?.output_size_bytes ?? activeItem?.output_size_bytes ?? activeItem?.output_size ?? null;
    const contactSheetSizeBytes = processed?.contact_sheet_size_bytes ?? activeItem?.contact_sheet_size_bytes ?? null;
    const contactSheetLightSizeBytes = processed?.contact_sheet_light_size_bytes ?? activeItem?.contact_sheet_light_size_bytes ?? null;
    const jpg95CandidatePath = processed?.jpg95_candidate_path || activeItem?.jpg95_candidate_path || "";
    const jpg95CandidateSizeBytes = processed?.jpg95_candidate_size_bytes ?? activeItem?.jpg95_candidate_size_bytes ?? null;
    const jpg95CandidateSavedRatio = processed?.jpg95_candidate_saved_ratio ?? activeItem?.jpg95_candidate_saved_ratio ?? null;
    const jpg95CandidateStatus = processed?.jpg95_candidate_status || activeItem?.jpg95_candidate_status || "not_applicable";
    const jpg95CandidateReason = processed?.jpg95_candidate_reason || activeItem?.jpg95_candidate_reason || "-";
    const lightDeliveryPath = processed?.light_delivery_path || activeItem?.light_delivery_path || "";
    const lightDeliverySizeBytes = processed?.light_delivery_size_bytes ?? activeItem?.light_delivery_size_bytes ?? null;
    const lightDeliverySavedRatio = processed?.light_delivery_saved_ratio ?? activeItem?.light_delivery_saved_ratio ?? null;
    const lightDeliveryStatus = processed?.light_delivery_status || activeItem?.light_delivery_status || "not_applicable";
    const lightDeliveryReason = processed?.light_delivery_reason || activeItem?.light_delivery_reason || "-";
    const lightDeliveryAvailable = lightDeliveryStatus === "available" && Boolean(lightDeliveryPath);
    const finalOutputSource = processed?.final_output_source || activeItem?.final_output_source || "png_main";
    const finalOutputFallbackReason = processed?.final_output_fallback_reason || activeItem?.final_output_fallback_reason || "-";
    const jpg95ReviewStatus = processed?.jpg95_candidate_review_status || activeItem?.jpg95_candidate_review_status || (jpg95CandidateStatus === "candidate_for_review" ? "pending_review" : "not_applicable");
    const jpg95ReviewDecision = processed?.jpg95_candidate_review_decision || activeItem?.jpg95_candidate_review_decision || "";
    const jpg95ReviewOption = findJpg95ReviewOption(jpg95ReviewDecision);
    const jpg95ReviewLabel = processed?.jpg95_candidate_review_label || activeItem?.jpg95_candidate_review_label || jpg95ReviewOption?.label || (jpg95CandidateStatus === "candidate_for_review" ? "继续检查" : "-");
    const canReviewJpg95Candidate = jpg95CandidateStatus === "candidate_for_review";
    const jpg95CandidateStatusText =
      jpg95CandidateStatus === "candidate_for_review"
        ? "已生成 · 待人工复核"
        : jpg95CandidateStatus === "not_generated"
          ? "未生成"
          : "不适用";
    const lightDeliveryStatusText =
      lightDeliveryStatus === "available"
        ? "available / direct copy"
        : lightDeliveryStatus === "not_generated"
          ? "not generated"
          : "not applicable";
    const computedSizeRatio = inputSizeBytes && outputSizeBytes ? outputSizeBytes / inputSizeBytes : null;
    const sizeRatioValue = processed?.size_ratio ?? activeItem?.size_ratio ?? computedSizeRatio;
    const outputFormatValue = processed?.output_format || activeItem?.output_format || pathFormat(outputPath) || "-";
    const contactSheetFormatValue = processed?.contact_sheet_format || activeItem?.contact_sheet_format || pathFormat(contactSheet) || "-";
    const contactSheetLightFormatValue = processed?.contact_sheet_light_format || activeItem?.contact_sheet_light_format || pathFormat(contactSheetLight) || "-";
    const outputDimensions = activeItem?.output_width && activeItem?.output_height ? `${activeItem.output_width} × ${activeItem.output_height}` : processed?.output_width && processed?.output_height ? `${processed.output_width} × ${processed.output_height}` : "-";
    const deliveryText = activeItem?.final_delivery_status === "PASS_WITH_LIMITATION" ? "建议查看后使用" : activeItem?.final_delivery_reason || statusTextValue;
    const isPortraitSkip = reasonText === "人物图保护跳过";
    const reportConclusion = isPortraitSkip ? "人物图保护跳过" : outputPath ? "已生成" : activeItem?.status === "failed" ? "失败" : "未生成";
    const deliveryAdvice = outputPath ? "建议查看后使用" : "不建议交付";
    const limitationExplanation = isPortraitSkip
      ? "人物图保护跳过，不放开人像增强。"
      : outputPath
        ? "成品已生成，建议打开输出目录查看文字、Logo、边缘和颜色后使用。"
        : "当前未生成成品，请查看失败原因后重新选择合适的中文商业非人像图。";
    const reportStatusSummary = isPortraitSkip
      ? "人物图保护跳过"
      : reasonText && reasonText !== "-"
        ? reasonText
        : outputPath
          ? "1080P安全增强 Beta 已生成，建议查看后使用。"
          : "当前未生成成品，请查看失败原因。";
    const pathSummaryRows = [
      { label: "contact sheet", value: contactSheet, status: contactSheet ? "已生成" : "未生成", copyLabel: "contact sheet 路径" },
      { label: "contact sheet preview", value: contactSheetLight, status: contactSheetLight ? "已生成（preview_only）" : "未生成", copyLabel: "contact sheet preview 路径" },
      { label: "JPG95 candidate", value: jpg95CandidatePath, status: jpg95CandidateStatusText, copyLabel: "JPG95 candidate 路径" },
      { label: "delivery_light", value: lightDeliveryPath, status: lightDeliveryStatusText, copyLabel: "delivery_light path" },
      { label: "output path", value: outputPath, status: outputPath ? "已生成" : "未生成", copyLabel: "output path 路径" },
    ];
    const outputBindingRows = [
      { label: "输入文件名", value: activeItem?.name || "未选择", status: activeItem?.name || "未选择" },
      { label: "输出文件名", value: outputName || "未生成", status: outputName || "未生成" },
      { label: "contact sheet", value: contactSheet, status: contactSheet ? "已生成" : "未生成", copyLabel: "contact sheet 路径" },
      { label: "contact sheet preview", value: contactSheetLight, status: contactSheetLight ? "已生成（preview_only）" : "未生成", copyLabel: "contact sheet preview 路径" },
      { label: "JPG95 candidate", value: jpg95CandidatePath, status: jpg95CandidateStatusText, copyLabel: "JPG95 candidate 路径" },
      { label: "delivery_light", value: lightDeliveryPath, status: lightDeliveryStatusText, copyLabel: "delivery_light path" },
      { label: "output path", value: outputPath, status: outputPath ? "已生成" : "未生成", copyLabel: "output path 路径" },
      ...(outputPath
        ? [
            { label: "输入体积", value: formatBytesToMb(inputSizeBytes) },
            { label: "成品体积", value: formatBytesToMb(outputSizeBytes) },
            { label: "体积倍率", value: formatSizeRatio(sizeRatioValue) },
            { label: "contact sheet 体积", value: formatBytesToMb(contactSheetSizeBytes) },
            { label: "contact sheet preview 体积", value: formatBytesToMb(contactSheetLightSizeBytes) },
            { label: "当前成品来源", value: finalOutputSource === "png_main" ? "PNG 高清主图" : finalOutputSource },
            { label: "JPG95 候选体积", value: formatBytesToMb(jpg95CandidateSizeBytes) },
            { label: "JPG95 节省比例", value: formatPercentValue(jpg95CandidateSavedRatio) },
            { label: "delivery_light 体积", value: formatBytesToMb(lightDeliverySizeBytes) },
            { label: "delivery_light 节省比例", value: formatPercentValue(lightDeliverySavedRatio) },
            { label: "delivery_light 状态", value: lightDeliveryStatusText },
            { label: "候选状态", value: jpg95CandidateStatusText },
            { label: "人工建议", value: jpg95ReviewLabel },
            { label: "candidate_is_final_output", value: "false" },
            { label: "回退原因", value: finalOutputFallbackReason },
            { label: "输出格式", value: outputFormatValue.toUpperCase() },
            { label: "contact sheet 格式", value: contactSheetFormatValue.toUpperCase() },
            { label: "preview 格式", value: contactSheetLightFormatValue.toUpperCase() },
          ]
        : []),
    ];
    const reviewReasons = [
      { label: contactSheet ? "contact sheet 已生成" : "contact sheet 未生成", detail: contactSheet ? "本地对比图已生成，完整路径可通过复制按钮获取。" : "当前样本没有可用 contact sheet。" },
      { label: outputPath ? "output_path 已生成" : "output_path 未生成", detail: outputPath ? "本地成品路径已绑定，完整路径可通过复制按钮获取。" : "当前样本没有可复制的成品路径。" },
      { label: jpg95CandidateStatus === "candidate_for_review" ? "JPG95 候选需人工复核" : "JPG95 候选未采用", detail: jpg95CandidateStatus === "candidate_for_review" ? "当前交付仍使用 PNG 高清主图，JPG95 仅作为体积优化候选。" : jpg95CandidateReason },
      { label: lightDeliveryStatus === "available" ? "delivery_light 可直接取用" : "delivery_light 未生成", detail: lightDeliveryStatus === "available" ? "高质量轻量交付版来自 JPG95 候选，PNG final 与 output_path 不变。" : lightDeliveryReason },
      { label: "当前交付仍使用 PNG 高清主图", detail: `人工建议：${jpg95ReviewLabel}` },
      ...(isPortraitSkip ? [{ label: "人物图保护跳过", detail: "Beta 当前不放开人像增强，避免破坏面部主体。" }] : []),
      ...(reasonText && reasonText !== "-" && !isPortraitSkip ? [{ label: "跳过 / 失败原因", detail: reasonText }] : []),
    ];
    return (
      <section className="flex h-full w-full flex-row gap-4 overflow-hidden bg-[#0b0c0e] p-4 text-slate-100">
        <div className="scrollbar-none flex h-full min-w-0 flex-1 flex-col gap-3 overflow-y-auto pr-1">
          <header className="shrink-0 rounded-sm border border-[#1c1f26] bg-[#121418] p-4">
            <div className="flex items-baseline justify-between gap-5">
              <h1 className="shrink-0 text-xl font-bold tracking-wider text-white">质量报告终审</h1>
              <span className="truncate font-mono text-[10px] uppercase tracking-widest text-[#475569]">影界 HDDE / 高清交付引擎</span>
            </div>
            <p className="mt-2 truncate font-mono text-[11px] text-[#475569]" title={activeItem?.name || ""}>
              1080P安全增强版 Beta / 资产特征值：{activeItem?.name || "未选择样本"}
            </p>
            <button type="button" onClick={() => setActiveScreen("dashboard")} className="mt-3 rounded-sm border border-[#333] bg-[#1c1f26] px-3 py-1.5 text-xs text-[#94a3b8] transition-colors hover:bg-[#2d3139] hover:text-white">
              ← 返回工作台
            </button>
          </header>

          <section className="shrink-0 space-y-3 rounded-sm border border-[#1c1f26] bg-[#121418] p-4">
            <div className="flex items-end justify-between gap-4">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Score Overlay</p>
                <h2 className="mt-2 text-lg font-semibold text-white">核心质量指标</h2>
              </div>
              <div className="text-right font-mono text-xs leading-6 text-white/40">
                <p>输入：待接入</p>
                <p>输出：{outputDimensions}</p>
              </div>
            </div>
            <div className="grid gap-2.5">
              {makeSafeBetaQualityMetrics().map(([keyName, label, value]) => (
                <SafeBetaMetricBar key={keyName} label={label} keyName={keyName} value={value} active={false} />
              ))}
            </div>
          </section>

          <section className="shrink-0 rounded-sm border border-[#1c1f26] bg-[#121418] p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Output Binding</p>
                <h2 className="mt-1 text-sm font-semibold text-white">输出绑定摘要</h2>
              </div>
              <span className="rounded-sm border border-[#1c1f26] bg-[#0b0c0e] px-2 py-1 text-xs text-[#94a3b8]">{reportConclusion}</span>
            </div>
            <div className="grid grid-cols-2 gap-2.5 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/30 p-3">
              {outputBindingRows.map((item) => (
                <div key={item.label} className="min-w-0 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/45 px-3 py-2">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="shrink-0 text-[11px] text-[#64748b]">{item.label}</span>
                    {item.copyLabel ? (
                      <button type="button" disabled={!item.value} onClick={() => handleCopySafeBetaPath(item.value, item.copyLabel)} className="shrink-0 rounded border border-[#2d665f] px-2 py-0.5 text-[10px] text-[#5bf5dc] transition hover:bg-[#12312d] disabled:cursor-not-allowed disabled:border-[#1c1f26] disabled:text-[#475569]">
                        复制路径
                      </button>
                    ) : null}
                  </div>
                  <div className="truncate font-mono text-xs text-[#00ffcc]" title={String(item.value || item.status)}>
                    {item.copyLabel ? item.status : item.value}
                  </div>
                </div>
              ))}
            </div>
            {!outputPath ? (
              <p className="mt-2 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/30 px-3 py-2 text-xs text-[#64748b]">
                成品生成后显示体积信息。
              </p>
            ) : null}
          </section>
        </div>

        <aside className="scrollbar-none flex h-full w-[320px] shrink-0 flex-col gap-3 overflow-y-auto pr-1">
          <section className="rounded-sm border border-[#1c1f26] bg-[#121418] p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Local Report Center</p>
                <h2 className="mt-2 text-lg font-semibold text-white">本地报告中心</h2>
                <p className="mt-1 text-xs leading-5 text-[#64748b]">面向人工验收的状态解释，不改变 Beta 原始结果字段。</p>
              </div>
              <div className="shrink-0 rounded-sm border border-[#66532d] bg-[#0b0c0e] px-2.5 py-1 text-xs font-semibold text-[#f0c36f]">
                {deliveryAdvice}
              </div>
            </div>

            <div className="mt-4 grid gap-2.5">
              <div className="grid gap-1.5 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/45 px-3 py-2">
                {[
                  ["图像类型", "1080P安全增强版 Beta"],
                  ["处理结论", reportConclusion],
                  ["交付建议", deliveryAdvice],
                ].map(([label, value]) => (
                  <div key={label} className="flex items-center justify-between gap-3 text-xs">
                    <span className="shrink-0 text-[#64748b]">{label}</span>
                    <span className="truncate text-right font-medium text-[#e2e8f0]" title={value}>{value}</span>
                  </div>
                ))}
              </div>
              <div className="grid gap-2 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/45 px-3 py-2">
                {pathSummaryRows.map((item) => (
                  <div key={item.label} className="min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs text-[#94a3b8]">{item.label}：{item.status}</span>
                      <button type="button" disabled={!item.value} onClick={() => handleCopySafeBetaPath(item.value, item.copyLabel)} className="shrink-0 rounded border border-[#2d665f] px-2 py-0.5 text-[10px] text-[#5bf5dc] transition hover:bg-[#12312d] disabled:cursor-not-allowed disabled:border-[#1c1f26] disabled:text-[#475569]">
                        复制路径
                      </button>
                    </div>
                    <div className="mt-1 truncate font-mono text-[10px] text-[#475569]" title={item.value || item.status}>{item.value || item.status}</div>
                  </div>
                ))}
              </div>
              <div className={`rounded-sm border px-3 py-2 ${lightDeliveryAvailable ? "border-[#2d665f] bg-[#0d181a]" : "border-[#1c1f26] bg-[#0b0c0e]/45"}`}>
                <div className="flex items-center justify-between gap-3">
                  <span className={`text-xs font-medium ${lightDeliveryAvailable ? "text-[#5bf5dc]" : "text-[#94a3b8]"}`}>
                    {lightDeliveryAvailable ? "高质量轻量交付版 JPG 已生成" : "高质量轻量交付版 JPG 未生成"}
                  </span>
                  <span className="shrink-0 font-mono text-[10px] text-[#64748b]">{lightDeliveryStatusText}</span>
                </div>
                <p className="mt-1 text-[11px] leading-5 text-[#94a3b8]">
                  {lightDeliveryAvailable ? "在保持画面清晰度和商业质感的前提下减小体积，适合发送、上传、PPT 插入。PNG final 仍为正式高清主图。" : lightDeliveryReason}
                </p>
                <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-[#94a3b8]">
                  <div className="rounded border border-[#1c1f26] bg-[#0b0c0e]/45 px-2 py-1">
                    <span className="text-[#64748b]">PNG final：</span>{formatBytesToMb(outputSizeBytes)}
                  </div>
                  <div className="rounded border border-[#1c1f26] bg-[#0b0c0e]/45 px-2 py-1">
                    <span className="text-[#64748b]">delivery_light：</span>{formatBytesToMb(lightDeliverySizeBytes)}
                  </div>
                  <div className="rounded border border-[#1c1f26] bg-[#0b0c0e]/45 px-2 py-1">
                    <span className="text-[#64748b]">节省比例：</span>{formatPercentValue(lightDeliverySavedRatio)}
                  </div>
                  <div className="rounded border border-[#1c1f26] bg-[#0b0c0e]/45 px-2 py-1">
                    <span className="text-[#64748b]">final source：</span>{finalOutputSource}
                  </div>
                </div>
                <div className="mt-2 flex gap-2">
                  <button type="button" disabled={!lightDeliveryPath} onClick={() => handleCopySafeBetaPath(lightDeliveryPath, "delivery_light path")} className="flex-1 rounded border border-[#2d665f] px-2 py-1 text-[11px] text-[#5bf5dc] transition hover:bg-[#12312d] disabled:cursor-not-allowed disabled:border-[#1c1f26] disabled:text-[#475569]">
                    复制轻量版路径
                  </button>
                  <button type="button" disabled={!lightDeliveryPath} onClick={() => handleOpenSafeBetaPathDir(lightDeliveryPath, "delivery_light")} className="flex-1 rounded border border-[#333] px-2 py-1 text-[11px] text-[#cbd5e1] transition hover:bg-[#1c1f26] disabled:cursor-not-allowed disabled:text-[#475569]">
                    打开所在文件夹
                  </button>
                </div>
              </div>
              <div className="rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/45 px-3 py-2">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs font-medium text-[#f0c36f]">{canReviewJpg95Candidate ? "JPG95 候选需人工复核" : "JPG95 候选未采用"}</span>
                  <span className="shrink-0 font-mono text-[10px] text-[#64748b]">{jpg95ReviewStatus}</span>
                </div>
                <p className="mt-1 text-[11px] text-[#94a3b8]">当前交付仍使用 PNG 高清主图</p>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  {JPG95_REVIEW_OPTIONS.map((option) => (
                    <button
                      key={option.decision}
                      type="button"
                      disabled={!canReviewJpg95Candidate}
                      onClick={() => handleSetJpg95CandidateReview(option.decision)}
                      className={`rounded-sm border px-2 py-1 text-[11px] transition disabled:cursor-not-allowed disabled:border-[#1c1f26] disabled:text-[#475569] ${
                        jpg95ReviewDecision === option.decision
                          ? "border-[#5bf5dc] bg-[#12312d] text-[#5bf5dc]"
                          : "border-[#333] text-[#cbd5e1] hover:bg-[#1c1f26]"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <div className="mt-2 truncate text-[11px] text-[#94a3b8]" title={jpg95ReviewLabel}>当前建议：{jpg95ReviewLabel}</div>
              </div>
              <div className="rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/45 px-3 py-2">
                <div className="text-xs font-medium text-[#f0c36f]">状态说明</div>
                <div className="mt-1 truncate text-[11px] text-[#94a3b8]" title={reportStatusSummary}>{reportStatusSummary}</div>
              </div>
            </div>

            <div className="mt-4 rounded-sm border border-[#66532d]/45 bg-[#100d06]/55 p-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-xs font-medium text-[#f0c36f]">PASS_WITH_LIMITATION 解释</h3>
                <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.18em] text-[#856404]">Manual Review</span>
              </div>
              <p className="mt-2 text-xs leading-5 text-[#d8c28c]">{limitationExplanation}</p>
            </div>

            <div className="mt-4">
              <h3 className="mb-2 text-xs font-medium text-[#94a3b8]">复核原因标签</h3>
              <div className="grid gap-2">
                {reviewReasons.map((item, index) => (
                  <div key={`${item.label}-${index}`} className="rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/45 px-3 py-1.5">
                    <div className="truncate text-xs font-medium text-[#f0c36f]" title={item.label}>{item.label}</div>
                    <div className="mt-0.5 truncate text-[11px] text-[#94a3b8]" title={item.detail}>{item.detail}</div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="rounded-sm border border-[#1c1f26] bg-[#121418] p-4 text-xs leading-6 text-[#94a3b8]">
            <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Feedback Package</p>
            <p className="mt-3 text-[#64748b]">反馈包路径</p>
            <p className="truncate font-mono text-[#8be6b1]" title={safeBetaFeedbackResult?.feedback_zip_path || "尚未导出"}>{safeBetaFeedbackResult?.feedback_zip_path || "尚未导出"}</p>
          </section>

          <section className="mt-auto flex shrink-0 flex-col gap-3 rounded-sm border border-[#1c1f26] bg-[#121418] p-4">
            <div>
              <span className="block font-mono text-[10px] uppercase tracking-wider text-[#64748b]">Final Signature</span>
              <h2 className="mt-1 text-sm font-medium text-white">终审操作</h2>
              <p className="mt-1 text-xs leading-relaxed text-[#94a3b8]">导出反馈包或打开本地输出目录后，返回工作台继续验收。</p>
            </div>
            <button type="button" onClick={exportSafeBetaFeedbackPackage} disabled={!safeBetaResult?.output_dir || isProcessingQueue} className="w-full rounded-sm bg-[#10b981] py-2.5 text-xs font-bold tracking-wider text-[#0b0c0e] shadow-md transition-colors hover:bg-[#059669] disabled:cursor-not-allowed disabled:bg-[#1c1f26] disabled:text-[#475569]">
              导出测试反馈包
            </button>
            <button type="button" onClick={handleOpenOutputDir} className="w-full rounded-sm border border-[#333] px-4 py-2 text-xs text-[#e2e8f0] transition hover:bg-[#1c1f26]">打开输出目录</button>
            <button type="button" disabled={!outputPath} onClick={() => handleCopyFinalOutputUrl(activeItem)} className="w-full rounded-sm border border-[#333] px-4 py-2 text-xs text-[#e2e8f0] transition hover:bg-[#1c1f26] disabled:cursor-not-allowed disabled:text-[#475569]">复制成品路径</button>
            <button type="button" onClick={() => setActiveScreen("dashboard")} className="w-full rounded-sm border border-[#333] px-4 py-2 text-xs text-[#94a3b8] transition hover:bg-[#1c1f26]">返回工作台</button>
          </section>
        </aside>
      </section>
    );
  }

  const outputLocationLabel = processingMode === PROCESSING_MODE_SAFE_BETA ? "当前状态：Beta输出目录" : appliedOutputDir.trim() ? "当前状态：自定义目录" : "当前状态：默认目录";
  const currentOutputDir = processingMode === PROCESSING_MODE_SAFE_BETA ? DEFAULT_SAFE_BETA_OUTPUT_DIR : appliedOutputDir.trim() || defaultOutputDir || "等待后端返回默认目录";
  const safeBetaElapsedSeconds =
    safeBetaResult?.status === "RUNNING" && safeBetaStartedAt
      ? Math.max(0, Math.round((Date.now() - safeBetaStartedAt) / 1000) + safeBetaTick * 0)
      : safeBetaResult?.elapsed_seconds || 0;
  const isSafeBetaSelected = processingMode === PROCESSING_MODE_SAFE_BETA;
  const activeSafeBetaItem = isSafeBetaSelected ? activeItem : null;
  const activeSafeBetaOutputPath = isSafeBetaSelected ? firstSafeBetaOutputPath(activeSafeBetaItem, safeBetaResult) : "";
  const activeSafeBetaContactSheet = isSafeBetaSelected ? firstSafeBetaContactSheet(activeSafeBetaItem, safeBetaResult) : "";
  const activeSafeBetaStatusText = isSafeBetaSelected ? safeBetaItemStatusText(activeSafeBetaItem, safeBetaResult) : "";
  const safeBetaUserStatus = formatSafeBetaStatus(safeBetaResult?.status);
  const safeBetaGeneratedCount = readSafeBetaCount(safeBetaResult?.processed_count || safeBetaResult?.enhanced_count);
  const safeBetaSkippedCount = readSafeBetaCount(safeBetaResult?.skipped_count);
  const safeBetaCurrentFile = activeSafeBetaItem?.name || safeBetaResult?.current_file || "等待任务";
  const safeBetaFailureSummary = ["BLOCKED", "FAILED"].includes(String(safeBetaResult?.status || "").toUpperCase())
    ? activeSafeBetaItem?.error || safeBetaResult?.message || activeItem?.error || "处理失败"
    : "";
  const safeBetaDeliveryConclusion =
    activeSafeBetaItem?.status === "completed"
      ? "建议查看后使用"
      : activeSafeBetaItem?.status === "failed"
        ? "处理失败"
    : safeBetaResult?.status === "RUNNING"
      ? "处理中"
      : safeBetaResult?.status === "NEED_RESELECT"
        ? "本地文件访问已失效"
      : safeBetaResult?.status === "BLOCKED"
        ? "处理失败"
        : safeBetaResult?.status
          ? "建议查看后使用"
          : "等待任务";
  const safeBetaOutputUrlText =
    activeSafeBetaOutputPath
      ? activeSafeBetaOutputPath
      : safeBetaResult?.status === "RUNNING"
      ? "等待生成"
      : safeBetaResult?.status === "NEED_RESELECT"
        ? safeBetaResult?.message || "本地文件访问已失效"
      : safeBetaResult?.status === "BLOCKED"
        ? safeBetaResult?.message || "处理失败"
        : safeBetaResult?.status
          ? "请打开输出目录查看"
          : "等待生成";
  const safeBetaCurrentState =
    activeSafeBetaStatusText || (safeBetaResult?.status === "RUNNING"
      ? "Beta 处理中"
      : safeBetaResult?.status === "NEED_RESELECT"
        ? safeBetaResult?.message || "本地文件访问已失效"
      : safeBetaResult?.status === "BLOCKED"
        ? safeBetaResult?.message || "处理失败"
        : safeBetaResult?.status
          ? "处理完成"
          : "等待任务");
  const deliveryActionItem = activeItem?.status === "completed" ? activeItem : completedItems[completedItems.length - 1] || null;
  const betaActionItem = isSafeBetaSelected ? deliveryActionItem || activeItem : null;
  const safeBetaPrimaryOutputPath = isSafeBetaSelected ? firstSafeBetaOutputPath(betaActionItem, safeBetaResult) : "";
  const canCopyDeliveryPath = isSafeBetaSelected ? Boolean(safeBetaPrimaryOutputPath) : Boolean(deliveryActionItem?.final_output_url);

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
          <div className="hidden w-full flex-shrink-0 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/30 p-3">
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

          <div className="hidden w-full flex-shrink-0 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/30 p-3">
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
                {processingMode === PROCESSING_MODE_SAFE_BETA ? "适用：中文商业非人像图｜产品图｜PPT封面｜信息图" : getProcessingModeDisplay(processingMode).desc}
              </p>
              {processingMode === PROCESSING_MODE_SAFE_BETA ? (
                <details className="mt-2 rounded-sm border border-[#1c1f26] bg-[#05090a]/45 px-2 py-1.5 text-[11px] leading-5 text-[#94a3b8]">
                  <summary className="cursor-pointer select-none text-[#6feaf0]">查看使用边界</summary>
                  <ul className="mt-2 space-y-1 text-[#7f8f91]">
                    {safeBetaBoundaryItems.map((item) => (
                      <li key={item}>- {item}</li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </section>
          </div>

          {processingMode === PROCESSING_MODE_SAFE_BETA ? (
            <div className="w-full flex-shrink-0 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/40 p-3">
              <h3 className="mb-3 border-b border-[#1c1f26] pb-1.5 text-xs font-medium uppercase tracking-wide text-[#94a3b8]">
                1080P安全增强 Beta
              </h3>
              <div className="space-y-2 text-xs text-[#94a3b8]">
                <div className="flex items-center justify-between gap-3">
                  <span>当前状态</span>
                  <span className="font-semibold text-[#6feaf0]">{safeBetaUserStatus}</span>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <span className="shrink-0">当前文件</span>
                  <span className="min-w-0 max-w-[150px] truncate text-right font-mono text-[#e2e8f0]" title={safeBetaCurrentFile}>{safeBetaCurrentFile}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>处理进度</span>
                  <span className="font-mono text-[#e2e8f0]">{safeBetaResult?.progress ?? 0}%</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>生成结果</span>
                  <span className="font-mono text-[#e2e8f0]">已生成 {safeBetaGeneratedCount} 张</span>
                </div>
                {safeBetaSkippedCount > 0 ? (
                  <div className="flex items-center justify-between gap-3">
                    <span>跳过图片</span>
                    <span className="font-mono text-[#f0c36f]">跳过 {safeBetaSkippedCount} 张</span>
                  </div>
                ) : null}
                <div className="flex items-center justify-between gap-3">
                  <span>耗时</span>
                  <span className="font-mono text-[#e2e8f0]">{formatSafeBetaDuration(safeBetaElapsedSeconds)}</span>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <span className="shrink-0">输出目录</span>
                  <span className="min-w-0 break-all text-right font-mono text-[#64748b]">{safeBetaResult?.output_dir || DEFAULT_SAFE_BETA_OUTPUT_DIR}</span>
                </div>
                {safeBetaFailureSummary ? (
                  <div className="rounded-sm border border-[#4b1f2a] bg-[#1b0b10] px-2 py-1.5 text-[11px] leading-5 text-[#ff8a8a]">
                    {safeBetaFailureSummary}
                  </div>
                ) : null}
              </div>
              <details className="mt-3 rounded-sm border border-[#1c1f26] bg-[#05090a]/45 px-2 py-1.5 text-[11px] leading-5 text-[#64748b]">
                <summary className="cursor-pointer select-none text-[#94a3b8]">查看技术详情</summary>
                <div className="mt-2 space-y-1.5">
                  <div className="flex justify-between gap-3"><span>raw status</span><span className="font-mono">{safeBetaResult?.status || "WAITING"}</span></div>
                  <div className="flex justify-between gap-3"><span>enhanced</span><span className="font-mono">{safeBetaResult?.has_enhanced ? "true" : "false"}</span></div>
                  <div className="flex justify-between gap-3"><span>contact_sheet</span><span className="font-mono">{safeBetaResult?.has_contact_sheet ? "true" : "false"}</span></div>
                  <div className="flex justify-between gap-3"><span>enhanced_count</span><span className="font-mono">{safeBetaResult?.enhanced_count ?? 0}</span></div>
                  <div className="flex justify-between gap-3"><span>contact_sheet_count</span><span className="font-mono">{safeBetaResult?.contact_sheet_count ?? 0}</span></div>
                  <div className="flex justify-between gap-3"><span>elapsed_seconds</span><span className="font-mono">{safeBetaElapsedSeconds}</span></div>
                  <div className="flex justify-between gap-3"><span>beta_run_id</span><span className="min-w-0 truncate text-right font-mono" title={safeBetaResult?.beta_run_id || ""}>{safeBetaResult?.beta_run_id || "-"}</span></div>
                  <div className="flex justify-between gap-3"><span>stage</span><span className="min-w-0 truncate text-right font-mono" title={safeBetaResult?.stage || ""}>{safeBetaResult?.stage || "-"}</span></div>
                  <div className="flex justify-between gap-3"><span>error</span><span className="min-w-0 truncate text-right font-mono" title={safeBetaResult?.message || ""}>{safeBetaResult?.message || "-"}</span></div>
                  <pre className="max-h-24 overflow-auto rounded bg-black/25 p-2 font-mono text-[10px] leading-4 text-[#475569]">
                    {JSON.stringify({
                      status: safeBetaResult?.status || "",
                      processed_count: safeBetaResult?.processed_count || 0,
                      skipped_count: safeBetaResult?.skipped_count || 0,
                      output_dir: safeBetaResult?.output_dir || DEFAULT_SAFE_BETA_OUTPUT_DIR,
                    }, null, 2)}
                  </pre>
                  <button
                    type="button"
                    onClick={exportSafeBetaFeedbackPackage}
                    disabled={!safeBetaResult?.output_dir || isProcessingQueue}
                    className="w-full rounded border border-[#6feaf0]/40 px-3 py-1.5 text-xs font-semibold text-[#6feaf0] transition hover:border-[#9cffef] hover:text-[#9cffef] disabled:cursor-not-allowed disabled:border-white/10 disabled:text-white/30"
                  >
                    导出测试反馈包
                  </button>
                  {safeBetaFeedbackResult?.feedback_zip_path ? (
                    <p className="break-all font-mono text-[11px] leading-5 text-[#64748b]">
                      {safeBetaFeedbackResult.feedback_zip_path}
                    </p>
                  ) : null}
                </div>
              </details>
              <div className="hidden space-y-2 text-xs text-[#94a3b8]">
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
                className="hidden mt-3 w-full rounded border border-[#6feaf0]/50 px-3 py-2 text-xs font-semibold text-[#6feaf0] transition hover:border-[#9cffef] hover:text-[#9cffef] disabled:cursor-not-allowed disabled:border-white/10 disabled:text-white/30"
              >
                导出测试反馈包
              </button>
              <p className="hidden mt-2 text-[11px] leading-5 text-white/42">
                生成本次测试的运行报告、错误日志、系统环境和对比图，用于发送给开发者定位问题。
              </p>
              {safeBetaFeedbackResult?.feedback_zip_path ? (
                <p className="hidden mt-2 break-all font-mono text-[11px] leading-5 text-[#64748b]">
                  {safeBetaFeedbackResult.feedback_zip_path}
                </p>
              ) : null}
              <div className="hidden mt-3 space-y-1.5">
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
          <div className="mb-4 grid shrink-0 grid-cols-[minmax(180px,1.1fr)_minmax(180px,1fr)_minmax(220px,1.4fr)_160px] gap-3 rounded-sm border border-[#1c1f26] bg-[#121418] p-3">
            <div className="min-w-0">
              <p style={DECOR_LABEL}>Input</p>
              <button type="button" onClick={() => fileInputRef.current?.click()} className="mt-2 w-full rounded-sm border border-[#6feaf0]/50 bg-[#132f33] px-3 py-2.5 text-left text-xs font-semibold text-[#6feaf0] transition hover:border-[#9cffef] hover:text-[#9cffef]">
                图片导入 · 已选择 {fileQueue.length} 张
              </button>
            </div>
            <div className="min-w-0">
              <p style={DECOR_LABEL}>Mode</p>
              <select
                value={processingMode}
                onChange={(event) => setProcessingMode(event.target.value)}
                className="mt-2 w-full rounded-sm border border-[#263738] bg-[#05090a] px-3 py-2.5 text-xs text-[#e2e8f0] outline-none"
              >
                {processingModeOptions.map((option) => (
                  <option key={option.id} value={option.id}>{option.label}</option>
                ))}
              </select>
            </div>
            <div className="min-w-0">
              <p style={DECOR_LABEL}>Output Folder</p>
              <div className="mt-2 flex min-w-0 gap-2">
                <div className="min-w-0 flex-1 truncate rounded-sm border border-[#1c1f26] bg-[#0b0c0e] px-3 py-2.5 font-mono text-xs text-[#94a3b8]" title={currentOutputDir}>
                  {currentOutputDir}
                </div>
                <button type="button" onClick={handleSelectOutputDir} className="shrink-0 rounded-sm border border-[#333] bg-[#1c1f26] px-3 py-2 text-xs text-[#e2e8f0] transition hover:bg-[#2d3139]">更换</button>
              </div>
            </div>
            <div className="flex min-w-0 items-end">
              <button type="button" onClick={handleStartQueue} disabled={!canStartExecution} className="w-full rounded-sm border border-[#6feaf0]/50 bg-[#132f33] px-4 py-2.5 text-xs font-bold text-[#6feaf0] transition hover:border-[#9cffef] hover:text-[#9cffef] disabled:cursor-not-allowed disabled:border-[#263738] disabled:bg-[#0d181a] disabled:text-[#6e7d80]">
                {processingMode === PROCESSING_MODE_SAFE_BETA ? (isProcessingQueue ? "安全增强处理中..." : "开始安全增强 Beta") : "开始处理"}
              </button>
            </div>
          </div>
          <div className="mb-4 flex w-full flex-1 flex-col overflow-hidden rounded-sm border border-[#1c1f26] bg-[#121418] p-4">
            <div className="mb-2 flex items-center justify-between gap-4">
              <div className="min-w-0">
                <p style={DECOR_LABEL}>Queue</p>
                <h3 className="truncate text-xs font-medium text-[#94a3b8]">多图处理队列</h3>
              </div>
              <span style={{ ...DECOR_LABEL, color: "#6feaf0" }}>{fileQueue.length} 张</span>
            </div>
            <div className="scrollbar-thin w-full flex-1 overflow-auto border border-[#263738] bg-[#05090a]">
              <table className="w-full text-left font-mono text-xs" style={{ borderCollapse: "collapse", minWidth: "980px" }}>
                <thead style={{ position: "sticky", top: 0, backgroundColor: "#0d181a", color: "#6e7d80", zIndex: 1 }}>
                  <tr className="border-b border-[#1c1f26] text-[#64748b]">
                    <th className="px-3 py-2 text-left font-medium">文件名</th>
                    <th className="px-3 py-2 text-left font-medium">处理模式</th>
                    <th className="px-3 py-2 text-left font-medium">目标规格</th>
                    <th className="px-3 py-2 text-left font-medium">输出尺寸</th>
                    <th className="px-3 py-2 text-left font-medium">输出体积</th>
                    <th className="px-3 py-2 text-left font-medium">当前状态</th>
                    <th className="px-3 py-2 text-left font-medium">交付状态</th>
                    <th className="px-3 py-2 text-left font-medium">输出文件名</th>
                    <th className="px-3 py-2 text-center font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {!fileQueue.length ? (
                    <tr>
                      <td colSpan={9} style={{ padding: "80px 16px", textAlign: "center", color: "#6e7d80" }}>等待投喂本地影像资产</td>
                    </tr>
                  ) : (
                    fileQueue.map((item) => {
                      const isSafeBetaRow = item.mode === PROCESSING_MODE_SAFE_BETA;
                      const compareDisabled = isSafeBetaRow ? item.status !== "completed" : item.status !== "completed" || !item.final_output_url;
                      const reportDisabled = isSafeBetaRow ? item.status === "queued" || item.status === "processing" : item.status !== "completed" || (!item.task_report && !item.debug_quality);
                      const outputSizeBytes = isSafeBetaRow
                        ? item.beta_processed?.output_size_bytes ?? item.output_size_bytes ?? item.output_size
                        : item.output_size ?? item.final_size_bytes ?? item.debug_quality?.final_size_bytes;
                      const outputSize = formatBytesToMb(outputSizeBytes, isSafeBetaRow ? (item.status === "completed" ? "-" : "待生成") : "待接入");
                      return (
                      <tr key={item.id} className={`border-b border-[#1c1f26]/50 transition-colors hover:bg-[#121418]/50 ${activeItemId === item.id ? "bg-[#0d181a]" : ""}`}>
                        <td className="max-w-[180px] truncate px-3 py-2 font-mono text-[#e2e8f0]" title={item.name}>{item.name}</td>
                        <td className="px-3 py-2 font-sans">
                          {(() => {
                            const display = getModeDisplay(item.mode || activeMode);
                            return <span className={display.className}>{display.label}</span>;
                          })()}
                        </td>
                        <td className="px-3 py-2 font-mono text-[#64748b]">
                          <span className="text-[#94a3b8]">1080P</span>
                        </td>
                        <td className="px-3 py-2 font-mono font-medium text-[#00ffcc]">{item.output_width && item.output_height ? `${item.output_width} × ${item.output_height}` : "待生成"}</td>
                        <td className="px-3 py-2 font-mono text-[#64748b]">{outputSize}</td>
                        <td className="px-3 py-2"><StatusPill status={item.status} /></td>
                        <td className="px-3 py-2"><DeliveryPill status={item.final_delivery_status} item={item} /></td>
                        <td className={`max-w-[150px] truncate px-3 py-2 font-mono ${item.error ? "text-[#ff8a8a]" : "text-[#64748b]"}`} title={item.output_filename || item.error || ""}>
                          {item.output_filename || (item.status === "failed" && item.mode === PROCESSING_MODE_SAFE_BETA ? "未生成" : item.error || "等待输出")}
                        </td>
                        <td className="space-x-2 px-3 py-2 text-center">
                          <button type="button" onClick={() => locateQueueItem(item)} className="text-[11px] text-[#00ffcc] hover:underline">定位</button>
                          <button
                            type="button"
                            disabled={compareDisabled}
                            title={compareDisabled ? "当前图片尚未生成可用对比结果，请先运行处理。" : isSafeBetaRow ? "打开 Beta contact sheet / 对比结果视图。" : ""}
                            onClick={() => selectForCompare(item)}
                            className="text-[11px] text-[#94a3b8] transition-colors hover:text-white disabled:cursor-not-allowed disabled:text-[#475569]"
                          >
                            查看对比
                          </button>
                          <button
                            type="button"
                            disabled={reportDisabled}
                            title={reportDisabled ? "当前图片尚未形成可用报告，请先运行处理。" : isSafeBetaRow ? "打开 1080P安全增强版 Beta 交付报告。" : ""}
                            onClick={() => selectForReport(item)}
                            className="text-[11px] text-[#64748b] transition-colors hover:text-[#94a3b8] disabled:cursor-not-allowed disabled:text-[#475569]"
                          >
                            报告
                          </button>
                        </td>
                      </tr>
                    );
                    })
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
            <button type="button" className="hidden" onClick={handleStartQueue} disabled={!canStartExecution} style={{ backgroundColor: canStartExecution ? "#132f33" : "#0d181a", border: canStartExecution ? "1px solid #6feaf0" : "1px solid #263738", borderRadius: "6px", color: canStartExecution ? "#6feaf0" : "#6e7d80", padding: "10px 20px", cursor: canStartExecution ? "pointer" : "not-allowed", fontSize: "13px", fontWeight: 700, whiteSpace: "nowrap" }}>
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
                  <span className="text-[#94a3b8]">处理模式:</span>
                  <span className="min-w-0 truncate text-right font-mono text-[11px] text-[#e2e8f0]">
                    {isSafeBetaSelected ? "1080P安全增强版 Beta" : "1080P标准版"}
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
                  <span className="text-[#94a3b8]">输出路径:</span>
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
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#94a3b8]">输出尺寸:</span>
                  <span className="font-mono text-[11px] text-[#e2e8f0]">
                    {activeItem?.output_width && activeItem?.output_height ? `${activeItem.output_width} × ${activeItem.output_height}` : "待接入"}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#94a3b8]">输出体积:</span>
                  <span className="font-mono text-[11px] text-[#e2e8f0]">
                    {formatBytesToMb(activeItem?.beta_processed?.output_size_bytes ?? activeItem?.output_size_bytes ?? activeItem?.output_size ?? activeItem?.debug_quality?.final_size_bytes, "待接入")}
                  </span>
                </div>
                {isSafeBetaSelected ? (
                  <div className="flex items-start justify-between gap-3">
                    <span className="shrink-0 text-[#94a3b8]">跳过原因:</span>
                    <span className="min-w-0 truncate text-right font-mono text-[11px] text-[#f0c36f]" title={safeBetaReasonText(activeItem, safeBetaResult)}>
                      {safeBetaReasonText(activeItem, safeBetaResult)}
                    </span>
                  </div>
                ) : null}
              </div>
          </div>

          <div className="hidden w-full flex-shrink-0 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/40 p-3">
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
              {!isSafeBetaSelected ? (
                <button type="button" disabled={!deliveryActionItem?.final_output_url} onClick={() => handleOpenFinalOutput(deliveryActionItem)} className="flex w-full items-center justify-center gap-2 rounded-sm bg-[#10b981] px-4 py-2.5 text-xs font-bold tracking-wider text-[#0b0c0e] shadow-md transition-colors hover:bg-[#059669] disabled:cursor-not-allowed disabled:bg-[#1c1f26] disabled:text-[#475569] disabled:shadow-none">
                  <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true">
                    <path d="M12 5v13M5 12l7 7 7-7" />
                  </svg>
                  <span>下载成品高清图片</span>
                </button>
              ) : null}
              <button
                type="button"
                disabled={!canCopyDeliveryPath}
                title={isSafeBetaSelected && !safeBetaPrimaryOutputPath ? "Beta 尚未生成可复制的本地成品路径。" : ""}
                onClick={() => handleCopyFinalOutputUrl(isSafeBetaSelected ? betaActionItem : deliveryActionItem)}
                className="group flex w-full items-center justify-center gap-2 rounded-sm border border-[#333] bg-[#1c1f26] px-4 py-2 text-xs text-[#e2e8f0] transition-colors hover:bg-[#2d3139] disabled:cursor-not-allowed disabled:text-[#475569]"
              >
                <svg className="h-3.5 w-3.5 text-[#64748b] transition-colors group-hover:text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true">
                  <rect x="9" y="9" width="13" height="13" rx="1" />
                  <path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1" />
                </svg>
                <span>{isSafeBetaSelected ? "复制 Beta 成品路径" : "复制成品映射路径"}</span>
              </button>
              <button
                type="button"
                disabled={isSafeBetaSelected ? !safeBetaResult?.output_dir || isProcessingQueue : !deliveryActionItem?.taskId}
                onClick={() => (isSafeBetaSelected ? exportSafeBetaFeedbackPackage() : handleCreateFeedbackBundle(deliveryActionItem))}
                className="group flex w-full items-center justify-center gap-2 rounded-sm border border-[#856404]/30 bg-[#0b0c0e]/40 px-4 py-2 font-mono text-[11px] text-[#856404] transition-colors hover:border-[#ffc107]/50 hover:bg-[#1c1f26] hover:text-[#ffc107] disabled:cursor-not-allowed disabled:border-[#1c1f26] disabled:text-[#475569]"
              >
                <span>导出测试反馈包 / 反馈包中心</span>
              </button>
            </div>
            <p className="border-t border-[#1c1f26]/30 pt-2 text-[10px] leading-relaxed text-[#475569]">
              {isSafeBetaSelected ? "Beta 成品使用本地 output_path / output_dir，不依赖普通任务映射 URL。" : "成品质检仅依据后端解算映射 URL，不读取本地物理路径。"}
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
