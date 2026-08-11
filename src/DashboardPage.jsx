import React, { useEffect, useMemo, useRef, useState } from "react";
import TaskDetailPage from "./TaskDetailPage.jsx";
import ImageSliderComparePage from "./ImageSliderComparePage.jsx";
import QualityReportPage from "./QualityReportPage.jsx";
import UnifiedFeedback from "./UnifiedFeedback.jsx";
import { HddePageHeader } from "./HddeUI.jsx";
import { resolveDeliveryStatus, resolveReportCenterMeta } from "./deliveryStatus.js";
import { getFileDisplayName } from "./fileDisplayName.js";
import { PRODUCT_BRAND_LINE, PRODUCT_VERSION_LABEL } from "./productVersion.js";
import { resolve1080pSizeTreatment } from "./sizeTreatment.js";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8787";
const OUTPUT_PROFILE = "delivery_1080p";
const DEFAULT_OUTPUT_FORMAT = "auto";
const DEFAULT_SCALE = "2";
const DEFAULT_LEGACY_FORMAT = "png";
const PROCESSING_MODE_STANDARD = "standard";
const PROCESSING_MODE_SAFE_BETA = "safe_1080p_beta";
const PROCESSING_MODE_FOUR_K = "4k_v1";
const PROCESSING_MODE_COLOR_CORRECTION = "AUTO_COLOR_CORRECTION";
const FOUR_K_OUTPUT_PROFILE = "delivery_4k_v1";
const SAFE_BETA_FETCH_TIMEOUT_MS = 300000;

function resolveProcessingOutputDirectory(workdirInfo, processingMode) {
  if (workdirInfo?.directory_ready === false) return "";
  const standardOutputDir = workdirInfo?.output_dir || "";
  if (processingMode === PROCESSING_MODE_SAFE_BETA) {
    return workdirInfo?.beta_output_dir || standardOutputDir;
  }
  if (processingMode === PROCESSING_MODE_FOUR_K) {
    return workdirInfo?.four_k_output_dir || "";
  }
  return standardOutputDir;
}

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
    label: "1080P标准增强",
    desc: "沿用当前高清交付流程，适合标准 1080P 交付。",
  },
  {
    id: PROCESSING_MODE_SAFE_BETA,
    label: "1080P安全增强",
    desc: "适用于中文商业非人像图，使用 35% protected 策略进行安全增强。",
  },
  {
    id: PROCESSING_MODE_FOUR_K,
    label: "4K高清画质增强",
    desc: "保持原图比例，将长边高质量适配至3840px；不宣称真实细节重建。",
  },
];

const safeBetaBoundaryItems = [
  "不建议用于人像 / 面部主体图",
  "不用于通用 4K 超分",
  "不用于低清照片真实修复",
  "输出结果建议人工查看后使用",
];

const DECOR_LABEL = {
  color: "var(--text-muted)",
  fontSize: "12px",
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
};

const PANEL_STYLE = {
  backgroundColor: "var(--card-background)",
  border: "1px solid var(--border-color)",
  borderRadius: "8px",
};

const TITLE_STYLE = { color: "var(--text-primary)" };

const statusText = {
  pending: "待处理",
  queued: "待处理",
  uploading: "上传中",
  processing: "处理中",
  completed: "已生成",
  failed: "失败",
  need_reselect: "需重新选择",
};
const TERMINAL_TASK_STATUSES = new Set(["completed", "failed", "cancelled", "blocked"]);

const deliveryStatusLabel = {
  PASS: "可交付",
  PASS_WITH_LIMITATION: "建议人工复核",
  FAIL: "不建议交付",
};

function getModeDisplay(mode) {
  const normalized = mode || "";
  if (["fidelity", "texture", "text_safe"].includes(normalized)) {
    return { label: "1080P标准增强", className: "text-[var(--brand-primary)]" };
  }
  if (normalized === PROCESSING_MODE_SAFE_BETA) return { label: "1080P安全增强", className: "text-[var(--brand-primary)]" };
  if (normalized === PROCESSING_MODE_FOUR_K) return { label: "4K高清画质增强", className: "text-[var(--brand-primary)]" };
  if (normalized === PROCESSING_MODE_COLOR_CORRECTION) return { label: "自动颜色校正", className: "text-[var(--brand-primary)]" };
  if (normalized === "image_diagnosis") return { label: "图片诊断", className: "text-[var(--brand-primary)]" };
  return { label: normalized || "未选择", className: "text-[var(--text-secondary)]" };
}
function getOutputFormatDisplay(format) {
  const normalized = (format || DEFAULT_OUTPUT_FORMAT).toString().toLowerCase();
  if (normalized === "auto") return "智能自适应";
  return normalized.toUpperCase();
}

function getProcessingModeDisplay(mode) {
  return processingModeOptions.find((item) => item.id === mode) || processingModeOptions[0];
}

function processingStageLabel(value, status = "") {
  if (status === "completed") return "处理完成";
  if (status === "failed" || status === "blocked") return "处理未完成";
  const labels = {
    pending: "等待处理",
    upload: "正在上传",
    uploading: "正在上传",
    contract_validation: "核对处理策略",
    image_processing: "正在处理图片",
    output_file_write: "正在写入成品",
    output_verify: "正在核对结果",
    completed: "处理完成",
  };
  return labels[String(value || "").toLowerCase()] || (status === "processing" ? "正在处理" : "");
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
  let value = String(url).trim();
  if (!value) return "";
  if (/^\/[a-zA-Z]:[\\/]/.test(value)) value = value.slice(1);
  if (/^[a-zA-Z]:[\\/]/.test(value) || /^\\\\/.test(value) || /^file:\/\//i.test(value)) {
    let localPath = value.replace(/^file:\/\//i, "");
    if (/^\/[a-zA-Z]:[\\/]/.test(localPath)) localPath = localPath.slice(1);
    return `${API_BASE}/api/file/safe-beta/${encodeURIComponent(localPath)}`;
  }
  if (/^https?:\/\//i.test(value)) return value;
  if (value.startsWith("/")) return normalizeApiUrl(value);
  if (/^[^?#]+\.(png|jpe?g|webp|bmp)$/i.test(value) || value.includes("\\") || value.startsWith("tmp/")) {
    return `${API_BASE}/api/file/safe-beta/${encodeURIComponent(value)}`;
  }
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
    item?.contact_sheet_light,
    item?.contact_sheet,
    processed?.contact_sheet_light,
    processed?.contact_sheet,
    mapped?.contact_sheet_light,
    mapped?.contact_sheet,
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
  if (String(reason).includes("text_logo_risk")) {
    return "文字与Logo需要重点复核，请在前后对比中确认清晰度与形状后再决定是否交付。";
  }
  return reason;
}

function SafeBetaMetricBar({ label, keyName, value, active }) {
  const number = Number(value);
  const hasMetric = Number.isFinite(number);
  const width = hasMetric ? Math.max(0, Math.min(100, number)) : active ? 100 : 0;
  return (
    <article className="hdde-report-score-card" data-metric={keyName}>
      <div>
        <span>{label}</span>
        <strong>{value || "暂无"}</strong>
      </div>
      <div className="hdde-report-score-meter" aria-label={`${label} ${value || "暂无"}`}>
        <span style={{ width: `${width}%` }} />
      </div>
    </article>
  );
}

function SafeBetaBeforeAfterCompare({ originalFile, originalUrl, outputUrl, filename }) {
  const [position, setPosition] = useState(50);
  const [localOriginalUrl, setLocalOriginalUrl] = useState("");

  useEffect(() => {
    if (originalUrl || !originalFile || typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
      setLocalOriginalUrl("");
      return () => {};
    }
    const objectUrl = URL.createObjectURL(originalFile);
    setLocalOriginalUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [originalFile, originalUrl]);

  const beforeUrl = originalUrl || localOriginalUrl;
  const ready = Boolean(beforeUrl && outputUrl);

  if (!ready) {
    return (
      <div className="flex h-full min-h-[420px] items-center justify-center rounded-xl border border-[var(--border-color)] bg-[var(--elevated-background)] px-8 text-center">
        <div className="max-w-lg">
          <p className="text-lg font-semibold text-[var(--text-primary)]">对比图正在准备</p>
          <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">
            需要同时取得处理前图片和处理后成品，才能进行拖动对比。你仍可打开输出文件夹查看当前结果。
          </p>
        </div>
      </div>
    );
  }

  return (
    <figure
      className="relative h-full min-h-[420px] overflow-hidden rounded-xl border border-[var(--border-color)] bg-[var(--elevated-background)] shadow-sm"
      data-testid="safe-before-after-comparison"
    >
      <img src={beforeUrl} alt={`${filename || "当前图片"}处理前`} className="absolute inset-0 h-full w-full select-none object-contain" draggable="false" />
      <div className="absolute inset-0 overflow-hidden" style={{ clipPath: `inset(0 ${100 - position}% 0 0)` }}>
        <img src={outputUrl} alt={`${filename || "当前图片"}处理后`} className="absolute inset-0 h-full w-full select-none object-contain" draggable="false" />
      </div>

      <div className="pointer-events-none absolute inset-y-0 z-20 w-0.5 bg-white shadow-[0_0_0_1px_rgba(15,23,42,0.35)]" style={{ left: `${position}%` }}>
        <span className="absolute left-1/2 top-1/2 flex h-11 w-11 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-2 border-white bg-[var(--brand-primary)] text-sm font-bold text-white shadow-lg">
          ↔
        </span>
      </div>

      <span className="pointer-events-none absolute left-4 top-4 z-30 rounded-full bg-black/65 px-3 py-1.5 text-xs font-semibold text-white backdrop-blur-sm">处理后</span>
      <span className="pointer-events-none absolute right-4 top-4 z-30 rounded-full bg-black/65 px-3 py-1.5 text-xs font-semibold text-white backdrop-blur-sm">处理前</span>

      <input
        type="range"
        min="0"
        max="100"
        value={position}
        onChange={(event) => setPosition(Number(event.target.value))}
        aria-label="拖动查看处理前后差异"
        className="absolute inset-0 z-40 h-full w-full cursor-ew-resize opacity-0"
        data-testid="safe-comparison-slider"
      />
      <figcaption className="pointer-events-none absolute bottom-4 left-1/2 z-30 -translate-x-1/2 rounded-full bg-black/65 px-4 py-2 text-xs text-white backdrop-blur-sm">
        拖动中线查看差异
      </figcaption>
    </figure>
  );
}

function isBrowserPreviewablePath(path) {
  return /^https?:\/\//i.test(path || "");
}

function readSafeBetaMetric(item, result, key) {
  const processed = findSafeBetaProcessedRow(item, result);
  const mapped = findSafeBetaResultRow(item, result);
  const value = processed?.[key] ?? mapped?.[key] ?? item?.[key] ?? result?.[key] ?? null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function makeSafeBetaQualityMetrics(item, result) {
  const fields = [
    ["text_clarity_score", "文字清晰度"],
    ["edge_quality_score", "边缘质量"],
    ["color_fidelity_score", "色彩忠实度"],
    ["texture_score", "纹理保持力"],
  ];
  return [
    ...fields.map(([key, label]) => {
      const metric = readSafeBetaMetric(item, result, key);
      return [key, label, metric == null ? "需重新运行生成" : metric.toFixed(2)];
    }),
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
    { name: "读取图片", detail: "确认当前图片可以安全读取。", state: progress >= 15 || completed ? "完成" : phaseStatus(15) },
    { name: "内容检查", detail: "识别不适合增强的内容并优先保护原图。", state: skipped ? "跳过" : progress >= 35 || completed ? "完成" : phaseStatus(35) },
    { name: "安全增强", detail: "在保持文字、Logo和画面结构的前提下提升清晰度。", state: phaseStatus(55) },
    { name: "生成对比", detail: "准备可拖动的处理前后对比。", state: hasContactSheet ? "完成" : completed ? "完成" : phaseStatus(80) },
    { name: "保存结果", detail: "将成品保存到当前输出文件夹。", state: hasOutput ? "完成" : phaseStatus(100) },
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

function isCurrentSafeBetaInputItem(item) {
  return isUsableLocalFile(item?.file);
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

async function requestBetaSafeEnhance(url, items, betaRunId, outputDir = "") {
  logSafeBeta(betaRunId, "BETA_FORMDATA_BUILD_START", {
    frontend_selected_file_name: items.map((item) => item.name || item.file?.name || "image.png"),
  });
  const formData = new FormData();
  formData.append("beta_run_id", betaRunId);
  formData.append("mode", "safe_1080p");
  if (outputDir) formData.append("output_dir", outputDir);
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
      output_dir: outputDir,
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
      const timeoutError = new Error(`安全增强请求超时（${Math.round(SAFE_BETA_FETCH_TIMEOUT_MS / 1000)}秒）`);
      timeoutError.isSafeBetaTimeout = true;
      timeoutError.timeout_source = "frontend";
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
    throw new Error(`安全增强响应解析失败：${error.message}`);
  }
  logSafeBeta(betaRunId, "BETA_FETCH_RESPONSE_JSON", { payload });
  if (!response.ok || payload.ok === false || payload.success === false || payload.status === "FAILED" || payload.status === "failed") {
    const error = new Error(formatBetaFailureMessage(payload, payload.stage || `安全增强请求失败：HTTP ${response.status}`));
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

function betaPayloadArrays(payload = {}, data = {}) {
  const processed = Array.isArray(payload.processed) ? payload.processed : Array.isArray(data.processed) ? data.processed : [];
  const results = Array.isArray(payload.results) ? payload.results : Array.isArray(data.results) ? data.results : [];
  const enhancedFiles = Array.isArray(payload.enhanced_files) ? payload.enhanced_files : Array.isArray(data.enhanced_files) ? data.enhanced_files : [];
  return { processed: processed.map(addJpg95ReviewDefaults), results, enhancedFiles };
}

function processedOutputPath(row = {}) {
  return row.output_path || row.enhanced || "";
}

function isTextLogoRiskRow(row = {}) {
  const reason = `${row.jpg95_candidate_reason || ""} ${row.final_output_fallback_reason || ""}`;
  return reason.includes("text_logo_risk");
}

function betaQueuePatchFromProcessed(item, processedRows, results, fallbackOutputDir, fallbackMessage) {
  const processed = processedRows.find((row) => row.input_name === item.name || row.file === item.name) || {};
  const mapped = results.find((row) => row.input_name === item.name || row.file === item.name) || {};
  const outputPath = processedOutputPath(processed) || mapped.output_path || "";
  if (!outputPath) return null;
  const outputName = mapped.output_name || processed.output_name || outputPath.split(/[\\/]/).pop() || "";
  const textLogoRisk = isTextLogoRiskRow(processed);
  const reason = textLogoRisk ? "文字与Logo需要重点复核，请在前后对比中确认清晰度与形状后再决定是否交付。" : fallbackMessage;
  return {
    status: "completed",
    progress: 100,
    output_dir: fallbackOutputDir,
    output_filename: outputName || "已生成",
    output_path: outputPath,
    contact_sheet: processed.contact_sheet || "",
    contact_sheet_light: processed.contact_sheet_light || "",
    jpg95_candidate_status: processed.jpg95_candidate_status || "",
    jpg95_candidate_reason: processed.jpg95_candidate_reason || "",
    final_output_source: processed.final_output_source || "png_main",
    final_output_fallback_reason: processed.final_output_fallback_reason || "",
    beta_result: mapped,
    beta_processed: processed,
    beta_status: textLogoRisk ? "PASS_WITH_LIMITATION" : "PASS",
    final_delivery_status: "PASS_WITH_LIMITATION",
    final_delivery_reason: reason,
    error: "",
    logs: [reason],
  };
}

function formatBetaFailureMessage(payload, fallback = "1080P安全增强处理失败") {
  const data = payload?.data || {};
  const skipped = Array.isArray(payload?.skipped) ? payload.skipped : Array.isArray(data?.skipped) ? data.skipped : [];
  const firstSkip = skipped.find((item) => item && typeof item === "object") || {};
  if (firstSkip.reason) {
    const file = firstSkip.file || payload?.current_file || data?.failed_file || "";
    return `${file ? `${file} ` : ""}被1080P安全增强策略跳过：${firstSkip.reason}`;
  }
  return payload?.error || payload?.message || data?.error_message || data?.reason || fallback;
}

function uploadFileWithXhr(item, activeMode, requestedOutputDir, outputFormat, onProgress) {
  return new Promise((resolve, reject) => {
    const outputDirForRequest = (requestedOutputDir || "").trim();
    const formData = new FormData();
    formData.append("file", item.file);
    formData.append("mode", activeMode);
    if (activeMode === PROCESSING_MODE_FOUR_K) {
      formData.append("output_profile", FOUR_K_OUTPUT_PROFILE);
      formData.append("output_format", "png");
    } else {
      formData.append("scale", DEFAULT_SCALE);
      formData.append("format", DEFAULT_LEGACY_FORMAT);
      formData.append("output_profile", OUTPUT_PROFILE);
      formData.append("output_format", outputFormat || DEFAULT_OUTPUT_FORMAT);
      if (outputDirForRequest) formData.append("output_dir", outputDirForRequest);
    }
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
  return (
    <span className="hdde-processing-status-pill" data-status={status || "unknown"}>
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
  const label = normalized === "PASS_WITH_LIMITATION" ? "已生成｜建议查看后使用" : delivery.label || deliveryStatusLabel[normalized] || "等待判定";
  return (
    <span
      className="hdde-processing-delivery-pill"
      data-status={normalized}
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
    product: "影界 HDDE",
    version: PRODUCT_VERSION_LABEL,
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
    original_filename: item.name,
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
    input_width: item.input_width,
    input_height: item.input_height,
    input_size_bytes: item.input_size_bytes,
    output_width: item.output_width,
    output_height: item.output_height,
    output_size_bytes: item.output_size_bytes,
    output_path: item.output_path,
    output_directory: item.output_dir,
    final_output_exists: item.final_output_exists,
    processing_stage: item.processing_stage,
    created_at: item.created_at,
    completed_at: item.completed_at,
    duration_ms: item.duration_ms,
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

function taskToQueueItem(task) {
  const taskId = task?.task_id || task?.taskId || "";
  const result = task?.task_result || {};
  const inputPath = String(task?.input_path || result?.input_path || "");
  const fallbackName = inputPath.split(/[\\/]/).pop() || result?.input_filename || "已创建任务";
  const status = task?.task_status || task?.status || ((task?.result_id || result?.result_id) && (task?.result_file || task?.output_path || result?.result_file || result?.output_path) ? "completed" : "queued");
  return {
    id: `task-${taskId}`,
    file: null,
    name: getFileDisplayName(task?.original_filename || fallbackName, "已创建任务"),
    size: formatBytesToMb(task?.input_size_bytes || result?.input_size_bytes, "-"),
    type: task?.input_format || result?.input_format || "image",
    status,
    mode: task?.feature_key === "image_diagnosis" ? "image_diagnosis" : task?.mode || "fidelity",
    taskFamily: task?.task_family || task?.feature_key || "",
    output_format: result?.output_format || task?.output_format || "",
    output_dir: task?.output_directory || result?.output_dir || "",
    taskId,
    featureKey: task?.feature_key || result?.feature_key || task?.processing_type || task?.task_family || "",
    resultId: task?.result_id || result?.result_id || "",
    deliveryId: task?.delivery_id || result?.delivery_id || "",
    streamEndpoint: task?.streamEndpoint || `/api/v1/tasks/${taskId}/stream`,
    originalUrl: normalizeApiUrl(task?.originalUrl || result?.originalUrl),
    input_width: task?.input_width || result?.input_width || 0,
    input_height: task?.input_height || result?.input_height || 0,
    input_size_bytes: task?.input_size_bytes || result?.input_size_bytes || 0,
    output_width: task?.output_width || result?.output_width || 0,
    output_height: task?.output_height || result?.output_height || 0,
    output_size_bytes: task?.output_size_bytes || result?.output_size_bytes || result?.output_size || 0,
    resize_policy: task?.resize_policy || result?.resize_policy || "",
    final_output_url: normalizeApiUrl(task?.final_output_url || task?.enhancedUrl || result?.final_output_url || (
      taskId
      && (task?.result_id || result?.result_id)
      && (task?.result_file || task?.output_path || result?.result_file || result?.output_path)
        ? `/api/v1/tasks/${encodeURIComponent(taskId)}/result-file`
        : ""
    )),
    preview_output_url: normalizeApiUrl(task?.preview_output_url || result?.preview_output_url),
    final_delivery_status: task?.final_delivery_status || result?.final_delivery_status || "",
    final_delivery_reason: task?.final_delivery_reason || result?.final_delivery_reason || "",
    final_delivery_risk_level: task?.final_delivery_risk_level || result?.final_delivery_risk_level || "",
    final_delivery_recommended_usage: task?.final_delivery_recommended_usage || result?.final_delivery_recommended_usage || "",
    output_path: result?.output_path || task?.output_path || "",
    output_filename: result?.output_filename || "",
    input_path: inputPath,
    task_result: result,
    task_report: task?.task_report || {},
    debug_quality: task?.debug_quality || result?.debug_quality || {},
    error: task?.error_message || task?.task_error || "",
    logs: [],
    progress: Number(task?.task_progress ?? (status === "completed" ? 100 : 0)),
    processing_stage: task?.processing_stage || task?.current_stage || "",
    created_at: task?.created_at || "",
    completed_at: task?.completed_at || task?.updated_at || "",
    duration_ms: task?.duration_ms || result?.duration_ms || null,
    final_output_exists: task?.final_output_exists ?? result?.final_output_exists ?? false,
  };
}

function isRunnableProcessingItem(item) {
  return !["color_correction", "image_diagnosis"].includes(item?.taskFamily);
}

function colorBatchTaskToQueueItem(entry, batch) {
  const task = entry?.task || {};
  const result = entry?.result || {};
  const ui = entry?.ui || {};
  const taskId = task.task_id || "";
  return {
    id: `color-task-${taskId}`,
    file: null,
    name: getFileDisplayName(ui.source_display_name, "颜色校正图片"),
    size: formatBytesToMb(result.source_size_bytes, "-"),
    type: result.source_format || "image",
    status: task.status || "pending",
    mode: PROCESSING_MODE_COLOR_CORRECTION,
    taskFamily: "color_correction",
    batchId: batch.batch_id,
    output_format: result.output_format || "",
    output_dir: ui.output_directory || batch.output_directory || "",
    taskId,
    featureKey: task.feature_key || result.feature_key || "color_correction",
    resultId: task.result_id || result.result_id || "",
    deliveryId: task.delivery_id || result.delivery_id || "",
    streamEndpoint: "",
    originalUrl: normalizeApiUrl(ui.source_preview_url),
    input_width: result.width || 0,
    input_height: result.height || 0,
    input_size_bytes: result.source_size_bytes || 0,
    output_width: result.width || 0,
    output_height: result.height || 0,
    output_size_bytes: result.output_size_bytes || 0,
    final_output_url: normalizeApiUrl(ui.output_preview_url),
    preview_output_url: normalizeApiUrl(ui.output_preview_url),
    output_path: ui.output_path || "",
    output_filename: ui.output_display_name || "",
    task_result: {
      ...result,
      output_path: ui.output_path || "",
      output_dir: ui.output_directory || batch.output_directory || "",
      output_filename: ui.output_display_name || "",
    },
    task_report: null,
    debug_quality: null,
    error: task.failure_reason || "",
    logs: [],
    progress: Number(task.progress || 0),
    processing_stage: task.status || "pending",
    created_at: task.created_at || "",
    completed_at: task.completed_at || "",
    duration_ms: result.processing_time_ms || null,
    final_output_exists: Boolean(ui.output_path),
    review_status: entry?.review?.status || "not_available",
    reviewed_at: entry?.review?.reviewed_at || "",
  };
}

export default function DashboardPage({
  initialProcessingMode = "",
  initialTaskView = "current",
  onTaskContextChange,
  onNavigate,
  initialSourceFile = null,
  initialSourceRequestId = "",
  onInitialSourceConsumed,
}) {
  const fileInputRef = useRef(null);
  const processingRef = useRef(false);
  const consumedSourceRequestRef = useRef("");
  const [activeScreen, setActiveScreen] = useState("dashboard");
  const [activeItemId, setActiveItemId] = useState("");
  const [debugItemId, setDebugItemId] = useState("");
  const [fileQueue, setFileQueue] = useState([]);
  const [taskView, setTaskView] = useState(initialTaskView === "history" ? "history" : "current");
  const [colorBatches, setColorBatches] = useState([]);
  const [processingMode, setProcessingMode] = useState(PROCESSING_MODE_STANDARD);
  const [activeMode] = useState("fidelity");
  const [outputFormat, setOutputFormat] = useState(DEFAULT_OUTPUT_FORMAT);
  const [safeBetaResult, setSafeBetaResult] = useState(null);
  const [safeBetaStartedAt, setSafeBetaStartedAt] = useState(null);
  const [safeBetaTick, setSafeBetaTick] = useState(0);
  const [appliedOutputDir, setAppliedOutputDir] = useState("");
  const [workdirInfo, setWorkdirInfo] = useState(null);
  const [workdirError, setWorkdirError] = useState("");
  const [outputDirError, setOutputDirError] = useState("");
  const [outputDirSuccess, setOutputDirSuccess] = useState("");
  const [notice, setNotice] = useState("请选择图片，或更换输出文件夹后开始处理。");
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [isProcessingQueue, setIsProcessingQueue] = useState(false);

  useEffect(() => {
    if (processingModeOptions.some((option) => option.id === initialProcessingMode)) {
      setProcessingMode(initialProcessingMode);
      setAppliedOutputDir("");
    }
  }, [initialProcessingMode]);

  useEffect(() => {
    setTaskView(initialTaskView === "history" ? "history" : "current");
  }, [initialTaskView]);

  useEffect(() => {
    requestJson("GET", `${API_BASE}/api/app/workdir`)
      .then((payload) => {
        const data = payload?.data || payload || {};
        setWorkdirInfo(data);
        setWorkdirError(data.directory_ready === false ? data.directory_message || "正式目录未就绪，请前往系统设置重新选择目录。" : "");
      })
      .catch((error) => {
        setWorkdirInfo(null);
        setWorkdirError(error.message || "工作目录初始化失败，请检查权限");
      });
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    const requestedBatchId = new URLSearchParams(window.location.search).get("batch") || "";
    const loadColorBatches = async () => {
      try {
        const payload = await requestJson("GET", `${API_BASE}/api/color-correction/batches`);
        if (cancelled) return;
        const batches = payload?.data?.batches || [];
        setColorBatches(batches);
        const colorItems = batches.flatMap((batch) => (batch.items || []).map((item) => colorBatchTaskToQueueItem(item, batch)));
        setFileQueue((current) => {
          const otherItems = current.filter((item) => item.taskFamily !== "color_correction");
          return [...colorItems, ...otherItems];
        });
        if (requestedBatchId) {
          const requestedItems = colorItems.filter((item) => item.batchId === requestedBatchId);
          const preferred = requestedItems.find((item) => ["processing", "pending"].includes(item.status)) || requestedItems[0];
          if (preferred) setActiveItemId((current) => current || preferred.id);
        }
        if (batches.some((batch) => ["pending", "processing"].includes(batch.status))) {
          timer = window.setTimeout(loadColorBatches, 700);
        }
      } catch {
        // 旧运行实例没有批量颜色校正接口时，保留现有处理中心能力。
      }
    };
    void loadColorBatches();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    requestJson("GET", `${API_BASE}/api/v1/tasks`)
      .then((payload) => {
        const tasks = payload?.data?.tasks || payload?.tasks || [];
        const restored = tasks.map(taskToQueueItem).filter((item) => item.taskId);
        if (!restored.length) return;
        setFileQueue((current) => {
          const known = new Set(current.map((item) => item.taskId).filter(Boolean));
          return [...restored.filter((item) => !known.has(item.taskId)), ...current];
        });
      })
      .catch(() => {
        // 当前运行实例没有可恢复任务时，处理中心仍可正常创建新任务。
      });
  }, []);

  useEffect(() => {
    if (safeBetaResult?.status !== "RUNNING") return () => {};
    const timer = window.setInterval(() => setSafeBetaTick((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [safeBetaResult?.status]);

  const activeItem = useMemo(() => {
    const belongsToView = (item) => (taskView === "history" ? TERMINAL_TASK_STATUSES.has(item.status) : !TERMINAL_TASK_STATUSES.has(item.status));
    const selected = fileQueue.find((item) => item.id === activeItemId);
    if (selected && belongsToView(selected)) return selected;
    return fileQueue.find((item) => belongsToView(item) && item.status === "processing") || fileQueue.find(belongsToView) || null;
  }, [fileQueue, activeItemId, taskView]);
  const debugItem = useMemo(() => fileQueue.find((item) => item.id === debugItemId) || activeItem, [fileQueue, debugItemId, activeItem]);
  const taskContextSnapshot = useMemo(() => {
    if (!activeItem?.taskId || activeItem?.taskFamily === "color_correction") return null;
    const originalSource = activeItem.originalUrl || activeItem.task_result?.original_url || activeItem.task_result?.input_url || "";
    const resultSource =
      activeItem.preview_output_url ||
      activeItem.final_output_url ||
      activeItem.task_result?.preview_output_url ||
      activeItem.task_result?.final_output_url ||
      "";
    return {
      taskId: activeItem.taskId,
      mode: activeItem.mode,
      taskConfig: makeTaskConfig(activeItem),
      taskResult: activeItem.task_result && typeof activeItem.task_result === "object" ? activeItem.task_result : null,
      taskReport: activeItem.task_report && typeof activeItem.task_report === "object" ? activeItem.task_report : null,
      debugQuality: activeItem.debug_quality && typeof activeItem.debug_quality === "object" ? activeItem.debug_quality : null,
      comparisonAssets: originalSource && resultSource ? { originalUrl: originalSource, resultUrl: resultSource } : null,
    };
  }, [
    activeItem?.taskId,
    activeItem?.taskFamily,
    activeItem?.mode,
    activeItem?.originalUrl,
    activeItem?.preview_output_url,
    activeItem?.final_output_url,
    activeItem?.task_result,
    activeItem?.task_report,
    activeItem?.debug_quality,
  ]);

  useEffect(() => {
    if (!taskContextSnapshot || typeof onTaskContextChange !== "function") return;
    onTaskContextChange(taskContextSnapshot);
  }, [onTaskContextChange, taskContextSnapshot]);

  const completedItems = fileQueue.filter((item) => item.status === "completed" && item.taskFamily !== "image_diagnosis");
  const currentTaskItems = fileQueue.filter((item) => !TERMINAL_TASK_STATUSES.has(item.status));
  const historyTaskItems = fileQueue.filter((item) => item.taskId && TERMINAL_TASK_STATUSES.has(item.status));
  const visibleTaskItems = taskView === "history" ? historyTaskItems : currentTaskItems;
  const requestedColorBatchId = new URLSearchParams(window.location.search).get("batch") || "";
  const activeColorBatch = colorBatches.find((batch) => batch.batch_id === requestedColorBatchId) || colorBatches[0] || null;
  const localQueueItems = fileQueue.filter(isRunnableProcessingItem);
  const directoryReady = Boolean(workdirInfo?.directory_ready) && !workdirError;
  const directoryMessage = workdirError || workdirInfo?.directory_message || "正式目录未就绪，请前往系统设置重新选择目录。";
  const canStartExecution = directoryReady && (processingMode === PROCESSING_MODE_SAFE_BETA || localQueueItems.length > 0) && !isProcessingQueue;
  const standardOutputDir = resolveProcessingOutputDirectory(workdirInfo, PROCESSING_MODE_STANDARD);
  const safeBetaDefaultOutputDir = resolveProcessingOutputDirectory(workdirInfo, PROCESSING_MODE_SAFE_BETA);
  const currentWorkdirRoot = directoryReady ? workdirInfo?.app_data_root || "" : "";
  const currentWorkdirSource = directoryReady ? workdirInfo?.app_data_root_source || "" : "";
  const currentWorkdirWritable = directoryReady && Boolean(workdirInfo?.app_data_root_writable);

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
      mode: processingMode === PROCESSING_MODE_FOUR_K ? PROCESSING_MODE_FOUR_K : activeMode,
      output_format: outputFormat,
      output_dir: appliedOutputDir,
      taskId: "",
      streamEndpoint: "",
      originalUrl: "",
      input_width: 0,
      input_height: 0,
      input_size_bytes: file.size,
      output_width: 0,
      output_height: 0,
      output_size_bytes: 0,
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
      processing_stage: "",
      created_at: "",
      completed_at: "",
      duration_ms: null,
      final_output_exists: false,
    }));
    if (replaceQueue) {
      setFileQueue(nextItems);
      setActiveItemId(nextItems[0]?.id || null);
      setDebugItemId(nextItems[0]?.id || null);
      setSafeBetaResult(null);
      setSafeBetaStartedAt(null);
      setSafeBetaTick(0);
      setCurrentIndex(0);
      setNotice(`已重新选择 ${nextItems.length} 张，安全增强状态已重置。`);
      return;
    }
    setFileQueue((prev) => [...prev, ...nextItems]);
    if (!activeItemId && nextItems[0]) setActiveItemId(nextItems[0].id);
    setNotice(`已选择 ${fileQueue.length + nextItems.length} 张。`);
  };

  useEffect(() => {
    if (!initialSourceFile || !initialSourceRequestId || consumedSourceRequestRef.current === initialSourceRequestId) return;
    consumedSourceRequestRef.current = initialSourceRequestId;
    addFiles([initialSourceFile], { replaceQueue: processingMode === PROCESSING_MODE_SAFE_BETA });
    if (typeof onInitialSourceConsumed === "function") onInitialSourceConsumed(initialSourceRequestId);
  }, [initialSourceFile, initialSourceRequestId, onInitialSourceConsumed, processingMode]);

  const handleFileChange = (event) => {
    addFiles(event.target.files, { replaceQueue: processingMode === PROCESSING_MODE_SAFE_BETA });
    event.target.value = "";
  };

  const resolveOutputDirForRequest = () => (
    processingMode === PROCESSING_MODE_FOUR_K
      ? ""
      : appliedOutputDir.trim() || standardOutputDir.trim()
  );

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
        setAppliedOutputDir(checkedPath === standardOutputDir ? "" : checkedPath);
        setOutputDirError("");
        setOutputDirSuccess(normalized === standardOutputDir ? "✓ 已恢复默认输出位置" : "✓ 已成功绑定本地输出文件夹");
        setNotice(normalized === standardOutputDir ? "已恢复默认输出位置。" : "已成功绑定本地输出文件夹。");
      })
      .catch((error) => {
        setOutputDirSuccess("");
        setOutputDirError(error.message || "本地文件夹选择失败。");
        setNotice("本地文件夹选择失败。");
      });
  };

  const handleOpenOutputDir = () => {
    const target = processingMode === PROCESSING_MODE_SAFE_BETA
      ? appliedOutputDir.trim() || safeBetaDefaultOutputDir
      : processingMode === PROCESSING_MODE_FOUR_K
        ? resolveProcessingOutputDirectory(workdirInfo, PROCESSING_MODE_FOUR_K)
        : appliedOutputDir.trim() || standardOutputDir;
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

  const handleOpenWorkdir = () => {
    if (!directoryReady || !currentWorkdirRoot) {
      setNotice(directoryMessage);
      return;
    }
    requestJson("POST", `${API_BASE}/api/output/open`, { output_dir: currentWorkdirRoot })
      .then((payload) => {
        setOutputDirError("");
        setOutputDirSuccess("");
        setNotice(payload.message || "已打开当前工作目录。");
      })
      .catch((error) => {
        setOutputDirError(error.message);
        setOutputDirSuccess("");
        setNotice(error.message || "打开当前工作目录失败。");
      });
  };

  const handleOpenSafeBetaInputDir = () => {
    const target = safeBetaResult?.input_dir || "";
    const fileCount = Number(safeBetaResult?.input_file_count ?? safeBetaResult?.input_file_names?.length ?? 0);
    const fileNames = Array.isArray(safeBetaResult?.input_file_names) ? safeBetaResult.input_file_names : [];
    if (!target || fileCount <= 0) {
      setNotice("当前任务输入目录为空，请重新添加图片后执行增强版");
      console.info("[Safe1080pBeta] INPUT_DIR_OPEN_BLOCKED", {
        api_input_dir: safeBetaResult?.input_dir || "",
        ui_input_dir: safeBetaResult?.input_dir || "",
        explorer_open_path: "",
        input_dir_file_count: fileCount,
        input_dir_files: fileNames,
      });
      return;
    }
    console.info("[Safe1080pBeta] INPUT_DIR_OPEN", {
      api_input_dir: safeBetaResult?.input_dir || "",
      ui_input_dir: target,
      explorer_open_path: target,
      input_dir_file_count: fileCount,
      input_dir_files: fileNames,
    });
    requestJson("POST", `${API_BASE}/api/output/open`, { output_dir: target })
      .then((payload) => {
        setOutputDirError("");
        setOutputDirSuccess("");
        setNotice(payload.message || "已打开本次输入目录。");
      })
      .catch((error) => {
        setOutputDirError(error.message);
        setOutputDirSuccess("");
        setNotice(error.message || "打开本次输入目录失败。");
      });
  };

  const handleResetOutputDir = () => {
    setAppliedOutputDir("");
    setOutputDirError("");
    setOutputDirSuccess("✓ 已恢复默认输出位置");
    setNotice("已恢复默认输出位置。");
  };

  const runSafeBetaMode = async () => {
    return runSafeBetaModeV2();
  };

  const runSafeBetaModeV2 = async () => {
    if (!directoryReady) {
      setNotice(directoryMessage);
      return;
    }
    const startedAt = Date.now();
    const betaRunId = makeBetaRunId();
    const betaOutputDir = appliedOutputDir.trim() || safeBetaDefaultOutputDir;
    const betaItems = fileQueue.filter(isCurrentSafeBetaInputItem);
    const betaItemIds = betaItems.map((item) => item.id);
    const firstFileName = betaItems[0]?.name || "";
    const firstCurrentFile = firstFileName || "正在连接安全增强服务";
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
        output_dir: betaOutputDir,
        input_dir: "",
        input_files: [],
        input_file_names: [],
        input_file_count: 0,
        has_enhanced: false,
        has_contact_sheet: false,
        elapsed_seconds: 0,
        stage: "BETA_INPUT_MISSING",
        reason: "BETA_INPUT_MISSING",
        error: "BETA_INPUT_MISSING / 请先添加图片",
        message: "BETA_INPUT_MISSING / 请先添加图片",
      });
      setNotice("BETA_INPUT_MISSING / 请先添加图片");
      return;
    }
    if (!betaOutputDir) {
      const message = workdirError || "工作目录初始化失败，请检查权限";
      setSafeBetaResult({
        status: "BLOCKED",
        beta_run_id: betaRunId,
        progress: 100,
        current_file: firstFileName || "",
        processed_count: 0,
        enhanced_count: 0,
        contact_sheet_count: 0,
        skipped_count: 0,
        output_dir: "",
        input_dir: "",
        input_files: [],
        input_file_names: [],
        input_file_count: 0,
        has_enhanced: false,
        has_contact_sheet: false,
        elapsed_seconds: 0,
        stage: "BETA_OUTPUT_DIR_MISSING",
        reason: "BETA_OUTPUT_DIR_MISSING",
        error: message,
        message,
      });
      setNotice(message);
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
        output_dir: betaOutputDir,
        input_dir: "",
        input_files: [],
        input_file_names: [],
        input_file_count: 0,
        has_enhanced: false,
        has_contact_sheet: false,
        elapsed_seconds: 0,
        message,
      });
      setBetaQueuePatch({
        status: "need_reselect",
        progress: 100,
        output_dir: betaOutputDir,
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
            output_dir: betaOutputDir,
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
            final_delivery_reason: "1080P安全增强成品已生成，建议查看后使用。",
            final_delivery_recommended_usage: "打开输出目录查看增强图，确认文字、Logo、边缘和颜色后使用。",
            error: "",
            logs: ["处理完成"],
          };
        }),
      );
    };
    const setBetaStage = (progress, currentFile, message) => {
      setSafeBetaResult((prev) => (prev?.status === "RUNNING" ? { ...prev, progress, current_file: currentFile, message } : prev));
      setBetaQueuePatch({ status: "processing", progress, error: "", logs: [message], output_dir: betaOutputDir, mode: PROCESSING_MODE_SAFE_BETA });
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
    setBetaQueuePatch({
      status: "processing",
      progress: 5,
      mode: PROCESSING_MODE_SAFE_BETA,
      output_dir: betaOutputDir,
      output_filename: "",
      final_delivery_status: "",
      final_delivery_reason: "安全增强处理中",
      final_output_url: "",
      error: "",
      logs: ["正在连接安全增强服务"],
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
      output_dir: betaOutputDir,
      has_enhanced: false,
      has_contact_sheet: false,
      elapsed_seconds: 0,
      message: "正在连接安全增强服务",
    });
    setNotice("1080P安全增强：正在连接处理服务。");
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
          output_dir: betaOutputDir,
          flat_output: true,
          business_output: true,
          files: betaItems.map((item) => item.name),
        },
      });
      const payload = await requestBetaSafeEnhance(`${API_BASE}/api/beta/safe-1080p/enhance`, betaItems, betaRunId, betaOutputDir);
      const data = payload?.data || {};
      if (!isBetaSuccess(payload) && !isBetaSuccess(data)) {
        throw new Error(payload?.error || payload?.message || data?.error_message || data?.reason || "安全增强处理失败");
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
      const inputDir = payload.input_dir || data.input_dir || "";
      const inputFileNames = Array.isArray(payload.input_file_names) ? payload.input_file_names : Array.isArray(data.input_file_names) ? data.input_file_names : [];
      const inputFileCount = Number(payload.input_file_count ?? data.input_file_count ?? inputFileNames.length ?? 0);
      console.info("[Safe1080pBeta] INPUT_DIR_SYNC", {
        api_input_dir: inputDir,
        ui_input_dir: inputDir,
        explorer_open_path: inputDir,
        input_dir_file_count: inputFileCount,
        input_dir_files: inputFileNames,
      });
      setSafeBetaResult({
        status: resultStatus,
        beta_run_id: payload.beta_run_id || data.beta_run_id || betaRunId,
        progress: 100,
        current_file: firstResult.input_name || processedItems[processedItems.length - 1]?.file || firstFileName || "处理完成",
        processed_count: processedCount,
        enhanced_count: enhancedCount,
        contact_sheet_count: contactSheetCount,
        skipped_count: skippedCount,
        output_dir: payload.output_dir || data.output_dir || betaOutputDir,
        app_data_root: payload.app_data_root || data.app_data_root || workdirInfo?.app_data_root || "",
        app_data_root_source: payload.app_data_root_source || data.app_data_root_source || workdirInfo?.app_data_root_source || "",
        app_data_root_exists: payload.app_data_root_exists ?? data.app_data_root_exists ?? workdirInfo?.app_data_root_exists ?? false,
        app_data_root_writable: payload.app_data_root_writable ?? data.app_data_root_writable ?? workdirInfo?.app_data_root_writable ?? false,
        report_dir: payload.report_dir || data.report_dir || workdirInfo?.report_dir || "",
        feedback_dir: payload.feedback_dir || data.feedback_dir || workdirInfo?.feedback_dir || "",
        beta_upload_dir: payload.beta_upload_dir || data.beta_upload_dir || workdirInfo?.beta_upload_dir || "",
        has_enhanced: enhancedCount > 0,
        has_contact_sheet: contactSheetCount > 0,
        input_dir: inputDir,
        input_files: Array.isArray(payload.input_files) ? payload.input_files : Array.isArray(data.input_files) ? data.input_files : [],
        input_file_names: inputFileNames,
        input_file_count: inputFileCount,
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
      setNotice(`1080P安全增强完成：${resultStatus}`);
    } catch (error) {
      const errorPayload = error?.payload || {};
      const errorData = errorPayload?.data || {};
      const timeoutSource = error?.timeout_source || errorPayload.timeout_source || errorData.timeout_source || (error?.isSafeBetaTimeout ? "frontend" : "unknown");
      const isFrontendTimeout = error?.isSafeBetaTimeout || timeoutSource === "frontend";
      const partialPayload = betaPayloadArrays(errorPayload, errorData);
      const skippedRows = Array.isArray(errorPayload.skipped) ? errorPayload.skipped : Array.isArray(errorData.skipped) ? errorData.skipped : [];
      const skippedCount = Number(errorPayload.skipped_count ?? errorData.skipped_count ?? skippedRows.length ?? 0);
      const failureMessage = formatBetaFailureMessage(errorPayload, error.message);
      const failedInputDir = errorPayload.input_dir || errorData.input_dir || "";
      const failedInputFileNames = Array.isArray(errorPayload.input_file_names) ? errorPayload.input_file_names : Array.isArray(errorData.input_file_names) ? errorData.input_file_names : [];
      const failedInputFileCount = Number(errorPayload.input_file_count ?? errorData.input_file_count ?? failedInputFileNames.length ?? 0);
      const partialProcessedCount = Number(errorPayload.processed_count ?? errorData.processed_count ?? partialPayload.processed.length ?? partialPayload.results.length ?? partialPayload.enhancedFiles.length ?? 0);
      const hasPartialOutput = partialProcessedCount > 0 || partialPayload.enhancedFiles.length > 0 || partialPayload.results.some((row) => row.output_path);
      const timeoutMessage = isFrontendTimeout ? "前端请求超时，后台可能仍在处理；已生成文件会保留映射，请稍后查看输出目录或反馈包。" : failureMessage;
      console.info("[Safe1080pBeta] INPUT_DIR_SYNC", {
        api_input_dir: failedInputDir,
        ui_input_dir: failedInputDir,
        explorer_open_path: failedInputDir,
        input_dir_file_count: failedInputFileCount,
        input_dir_files: failedInputFileNames,
      });
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
        output_dir: errorPayload.output_dir || errorData.output_dir || betaOutputDir,
        app_data_root: errorPayload.app_data_root || errorData.app_data_root || workdirInfo?.app_data_root || "",
        app_data_root_source: errorPayload.app_data_root_source || errorData.app_data_root_source || workdirInfo?.app_data_root_source || "",
        app_data_root_exists: errorPayload.app_data_root_exists ?? errorData.app_data_root_exists ?? workdirInfo?.app_data_root_exists ?? false,
        app_data_root_writable: errorPayload.app_data_root_writable ?? errorData.app_data_root_writable ?? workdirInfo?.app_data_root_writable ?? false,
        report_dir: errorPayload.report_dir || errorData.report_dir || workdirInfo?.report_dir || "",
        feedback_dir: errorPayload.feedback_dir || errorData.feedback_dir || workdirInfo?.feedback_dir || "",
        beta_upload_dir: errorPayload.beta_upload_dir || errorData.beta_upload_dir || workdirInfo?.beta_upload_dir || "",
        input_dir: failedInputDir,
        input_files: Array.isArray(errorPayload.input_files) ? errorPayload.input_files : Array.isArray(errorData.input_files) ? errorData.input_files : [],
        input_file_names: failedInputFileNames,
        input_file_count: failedInputFileCount,
        has_enhanced: false,
        has_contact_sheet: false,
        elapsed_seconds: Math.round((Date.now() - startedAt) / 1000),
        skipped: skippedRows,
        timeout_source: timeoutSource,
        message: timeoutMessage,
      });
      setSafeBetaResult((prev) => ({
        ...(prev || {}),
        status: isFrontendTimeout ? "TIMEOUT_PENDING" : hasPartialOutput ? "PASS_WITH_NOTES" : prev?.status || "BLOCKED",
        progress: isFrontendTimeout && !hasPartialOutput ? 75 : 100,
        processed_count: partialProcessedCount,
        enhanced_count: partialProcessedCount || partialPayload.enhancedFiles.length,
        contact_sheet_count: partialPayload.processed.filter((row) => Boolean(row.contact_sheet)).length,
        has_enhanced: hasPartialOutput,
        has_contact_sheet: partialPayload.processed.some((row) => Boolean(row.contact_sheet)),
        results: partialPayload.results,
        enhanced_files: partialPayload.enhancedFiles,
        processed: partialPayload.processed,
        timeout_source: timeoutSource,
        message: timeoutMessage,
      }));
      setFileQueue((prev) =>
        prev.map((item) => {
          if (!betaItemIds.includes(item.id)) return item;
          const skipped = skippedRows.find((row) => row?.input_name === item.name || row?.file === item.name) || skippedRows[0] || {};
          const partialPatch = betaQueuePatchFromProcessed(item, partialPayload.processed, partialPayload.results, errorPayload.output_dir || errorData.output_dir || betaOutputDir, timeoutMessage);
          if (partialPatch) return { ...item, ...partialPatch };
          if (isFrontendTimeout) {
            return {
              ...item,
              status: "processing",
              progress: Math.max(Number(item.progress || 0), 75),
              output_dir: errorPayload.output_dir || errorData.output_dir || betaOutputDir,
              final_delivery_status: "",
              final_delivery_reason: timeoutMessage,
              beta_status: "TIMEOUT_PENDING",
              error: "",
              logs: [timeoutMessage],
            };
          }
          const itemMessage = skipped?.reason ? `${item.name} 被1080P安全增强策略跳过：${skipped.reason}` : failureMessage;
          return {
            ...item,
            status: "failed",
            progress: 100,
            output_dir: errorPayload.output_dir || errorData.output_dir || betaOutputDir,
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
        status: isFrontendTimeout ? "TIMEOUT_PENDING" : hasPartialOutput ? "PASS_WITH_NOTES" : "BLOCKED",
        error: timeoutMessage,
      });
      setNotice(`1080P安全增强处理失败：${failureMessage}`);
      setNotice(timeoutMessage);
    } finally {
      stageTimers.forEach((timer) => window.clearTimeout(timer));
      processingRef.current = false;
      setIsProcessingQueue(false);
      setCurrentIndex(0);
      setActiveScreen("safe_beta_task");
    }
  };
  const processOneItem = async (item, index, total, queueOutputDir) => {
    const requestMode = processingMode === PROCESSING_MODE_FOUR_K ? PROCESSING_MODE_FOUR_K : activeMode;
    const activeOutputDir = requestMode === PROCESSING_MODE_FOUR_K
      ? resolveProcessingOutputDirectory(workdirInfo, PROCESSING_MODE_FOUR_K)
      : (queueOutputDir || standardOutputDir || "").trim();
    setCurrentIndex(index + 1);
    setActiveItemId(item.id);
    updateQueueItem(item.id, {
      status: "uploading",
      mode: requestMode,
      output_format: requestMode === PROCESSING_MODE_FOUR_K ? "png" : outputFormat,
      output_dir: activeOutputDir,
      error: "",
      logs: ["正在确认输出目录"],
      progress: 1,
    });

    try {
      const uploadPayload = await uploadFileWithXhr(item, requestMode, activeOutputDir, outputFormat, (percent) => {
        updateQueueItem(item.id, { progress: Math.min(30, percent) });
      });
      const taskId = uploadPayload.taskId;
      if (!taskId) throw new Error("后端未返回任务编号。");

      updateQueueItem(item.id, {
        status: "processing",
        taskId,
        streamEndpoint: uploadPayload.data?.streamEndpoint || `/api/v1/tasks/${taskId}/stream`,
        originalUrl: uploadPayload.originalUrl,
        mode: requestMode,
        input_width: uploadPayload.data?.input_width || 0,
        input_height: uploadPayload.data?.input_height || 0,
        input_size_bytes: uploadPayload.data?.input_size_bytes || item.file?.size || 0,
        output_width: uploadPayload.data?.output_width || 0,
        output_height: uploadPayload.data?.output_height || 0,
        created_at: uploadPayload.data?.created_at || "",
        processing_stage: uploadPayload.data?.processing_stage || "pending",
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
        output_size_bytes: taskResult.output_size_bytes || taskResult.output_size || 0,
        resize_policy: taskResult.resize_policy || "",
        hash_equal: taskResult.hash_equal ?? debugQuality.hash_equal ?? null,
        pixel_diff_score: taskResult.pixel_diff_score ?? debugQuality.pixel_diff_score ?? null,
        debug_timing: taskResult.debug_timing || merged.data?.debug_timing || null,
        processing_stage: merged.data?.processing_stage || "completed",
        completed_at: merged.data?.completed_at || "",
        duration_ms: taskResult.duration_ms || merged.data?.duration_ms || null,
        final_output_exists: taskResult.final_output_exists ?? merged.data?.final_output_exists ?? Boolean(finalOutputUrl),
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
    if (!directoryReady) {
      setNotice(directoryMessage);
      return;
    }
    if (processingMode === PROCESSING_MODE_SAFE_BETA) {
      await runSafeBetaModeV2();
      return;
    }
    const runnable = fileQueue.filter((item) => isRunnableProcessingItem(item) && (item.status === "queued" || item.status === "failed"));
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
    if (item.taskFamily === "color_correction") {
      if (item.status === "completed" && item.taskId && typeof onNavigate === "function") {
        const batchQuery = item.batchId ? `&batch=${encodeURIComponent(item.batchId)}` : "";
        onNavigate(`/color-correction/result?task_id=${encodeURIComponent(item.taskId)}${batchQuery}`);
        return;
      }
      setNotice(item.status === "failed" ? `已定位失败图片：${item.name}。${item.error || "请查看失败原因。"}` : `当前颜色校正结果尚未完成：${item.name}。`);
      return;
    }
    if (item.taskFamily === "image_diagnosis") {
      if (item.taskId && typeof onNavigate === "function") {
        onNavigate(`/image-diagnosis?task_id=${encodeURIComponent(item.taskId)}`);
      }
      return;
    }
    if (item.mode === PROCESSING_MODE_SAFE_BETA) {
      const outputPath = firstSafeBetaOutputPath(item, safeBetaResult);
      const stateText = safeBetaItemStatusText(item, safeBetaResult);
      setActiveScreen("safe_beta_task");
      setNotice(`已定位：${item.name}｜${stateText}${outputPath ? `｜${outputPath}` : ""}`);
      return;
    }
    if (item.taskId && typeof onNavigate === "function") {
      onNavigate(`/task-detail?task_id=${encodeURIComponent(item.taskId)}`);
      return;
    }
    setActiveScreen("task_detail");
    setNotice(`已定位：${item.name}`);
  };

  const selectForCompare = (item) => {
    if (item?.mode === PROCESSING_MODE_SAFE_BETA) {
      locateQueueItem(item);
      const contactSheet = firstSafeBetaContactSheet(item, safeBetaResult);
      const outputPath = firstSafeBetaOutputPath(item, safeBetaResult);
      if (contactSheet || outputPath) {
        setActiveScreen("safe_beta_compare");
        setNotice(contactSheet ? "已打开1080P安全增强前后对比。" : "当前图片没有可用对比图，请打开输出目录查看增强图。");
        return;
      }
      setNotice("当前图片尚未生成对比图，请先运行1080P安全增强。");
      return;
    }
    if (!item?.final_output_url) return;
    setActiveItemId(item.id);
    if (item.taskId && typeof onNavigate === "function") {
      onNavigate(`/task-detail/compare?task_id=${encodeURIComponent(item.taskId)}`);
      return;
    }
    setActiveScreen("image_compare");
  };

  const selectForReport = (item) => {
    if (item?.taskFamily === "color_correction") {
      setNotice("批量颜色校正结果可在当前列表逐图查看并打开，不额外生成整批质量报告。");
      return;
    }
    if (item?.mode === PROCESSING_MODE_SAFE_BETA) {
      locateQueueItem(item);
      setActiveScreen("safe_beta_report");
      setNotice("已打开1080P安全增强交付报告。");
      return;
    }
    if (!item?.task_report && !item?.debug_quality) return;
    setActiveItemId(item.id);
    if (item.taskId && typeof onNavigate === "function") {
      onNavigate(`/task-detail/report?task_id=${encodeURIComponent(item.taskId)}`);
      return;
    }
    setActiveScreen("quality_report");
  };

  const handleOpenFinalOutput = (item) => {
    if (item?.taskFamily === "color_correction") {
      if (!item.output_path) return;
      requestJson("POST", `${API_BASE}/api/color-correction/open-output`, { task_id: item.taskId })
        .then(() => setNotice(`已打开颜色校正结果：${item.name}。`))
        .catch((error) => setNotice(error.message || "无法打开颜色校正结果。"));
      return;
    }
    if (item?.mode === PROCESSING_MODE_SAFE_BETA) {
      setNotice("安全增强成品为本地文件，请使用“打开当前目录”或复制成品路径查看。");
      return;
    }
    if (!item?.final_output_url) return;
    window.open(item.final_output_url, "_blank", "noopener,noreferrer");
  };

  const handleOpenItemOutputFolder = (item) => {
    if (item?.taskFamily === "color_correction") {
      if (!item.output_path) {
        setNotice("当前图片尚未生成可打开的输出文件夹。");
        return;
      }
      requestJson("POST", `${API_BASE}/api/color-correction/open-output-folder`, { task_id: item.taskId })
        .then(() => setNotice("已打开颜色校正输出文件夹。"))
        .catch((error) => setNotice(error.message || "无法打开颜色校正输出文件夹。"));
      return;
    }
    const safePath = item?.mode === PROCESSING_MODE_SAFE_BETA
      ? firstSafeBetaOutputPath(item, safeBetaResult)
      : "";
    const pathValue = safePath || item?.output_path || item?.task_result?.output_path || "";
    const target = item?.output_dir || item?.task_result?.output_dir || String(pathValue).replace(/[\\/][^\\/]+$/, "");
    if (!target) {
      setNotice("当前任务还没有可打开的输出文件夹。");
      return;
    }
    requestJson("POST", `${API_BASE}/api/output/open`, { output_dir: target })
      .then((payload) => setNotice(payload.message || "已打开输出文件夹。"))
      .catch((error) => setNotice(error.message || "无法打开输出文件夹。"));
  };

  const handleCopyFinalOutputUrl = async (item) => {
    const betaPath = item?.mode === PROCESSING_MODE_SAFE_BETA ? firstSafeBetaOutputPath(item, safeBetaResult) : "";
    const colorPath = item?.taskFamily === "color_correction" ? item?.output_path || "" : "";
    const value = colorPath || betaPath || item?.final_output_url || "";
    if (!value) {
      setNotice(item?.mode === PROCESSING_MODE_SAFE_BETA ? "当前安全增强任务还没有可复制的成品路径。" : "当前任务还没有可复制的成品映射路径。");
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      setNotice(colorPath ? "已复制颜色校正成品路径。" : betaPath ? "已复制安全增强成品路径。" : "已复制成品映射 URL。");
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
        onBackToTask={() => setActiveScreen("task_detail")}
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
    const reasonText = safeBetaReasonText(activeItem, safeBetaResult);
    const statusTextValue = safeBetaItemStatusText(activeItem, safeBetaResult);
    const isPortraitSkip = reasonText === "人物图保护跳过";
    const deliveryConclusion = isPortraitSkip ? "人物图保护跳过" : outputPath ? "建议查看后使用" : activeItem?.status === "failed" ? "不建议交付" : "等待";
    const canViewCompare = Boolean(outputPath);
    const timeline = makeSafeBetaTimeline(activeItem, safeBetaResult);
    const progressValue = safeBetaResult?.progress ?? activeItem?.progress ?? 0;
    const rawInputName = activeItem?.name || safeBetaResult?.current_file || "";
    const inputDisplayName = getFileDisplayName(rawInputName, "等待任务");
    const taskHeading = isPortraitSkip
      ? "已保护原图"
      : outputPath || activeItem?.status === "completed"
        ? "图片处理已完成"
        : activeItem?.status === "failed"
          ? "图片处理未完成"
          : "正在处理你的图片";
    return (
      <section
        className="hdde-enhanced-page flex h-full min-h-0 w-full flex-col overflow-hidden bg-[var(--content-background)] p-4 text-[var(--text-primary)]"
        data-testid="safe-task-detail-page"
      >
        <header className="mb-4 flex shrink-0 items-center justify-between gap-5 rounded-lg border border-[var(--border-color)] bg-[var(--card-background)] p-4 shadow-sm">
          <div className="min-w-0">
            <p className="text-xs font-semibold tracking-[0.18em] text-[var(--brand-primary)]">安全增强任务</p>
            <h1 className="mt-2 truncate text-xl font-semibold tracking-wide text-[var(--text-primary)]">{taskHeading}</h1>
            <p className="mt-1 truncate text-sm text-[var(--text-secondary)]" title={rawInputName}>
              当前文件：{inputDisplayName}
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            <button type="button" onClick={() => setActiveScreen("dashboard")} className="rounded-md border border-[var(--border-color)] bg-[var(--card-background)] px-3 py-2 text-sm text-[var(--text-secondary)] transition hover:border-[var(--brand-primary)] hover:text-[var(--brand-primary)]">返回处理中心</button>
          </div>
        </header>

        <main className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_340px] gap-4">
          <section className="flex min-h-0 flex-col gap-4 overflow-hidden">
            <div className="grid shrink-0 grid-cols-3 gap-3 rounded-lg border border-[var(--border-color)] bg-[var(--card-background)] p-4 text-sm">
              {[
                ["处理方式", "1080P安全增强"],
                ["当前状态", statusTextValue],
                ["结果建议", deliveryConclusion],
              ].map(([label, value]) => (
                <div key={label} className="min-w-0 rounded-md border border-[var(--divider-color)] bg-[var(--elevated-background)] p-3">
                  <p className="text-xs font-medium text-[var(--text-muted)]">{label}</p>
                  <p className="mt-1 break-words text-sm font-medium leading-5 text-[var(--text-primary)]">{value}</p>
                </div>
              ))}
            </div>

            <section className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-[var(--border-color)] bg-[var(--card-background)] p-4">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold tracking-[0.18em] text-[var(--brand-primary)]">处理进度</p>
                  <h2 className="mt-2 text-lg font-semibold text-[var(--text-primary)]">本次处理步骤</h2>
                </div>
                <span className="text-sm font-semibold text-[var(--brand-primary)]">{progressValue}%</span>
              </div>
              <div className="mb-4 h-2 overflow-hidden rounded-full bg-[var(--divider-color)]">
                <div className="h-full rounded-full bg-[var(--brand-primary)] transition-[width] duration-200" style={{ width: `${Math.max(0, Math.min(100, Number(progressValue) || 0))}%` }} />
              </div>
              <div className="space-y-3">
                {timeline.map((stage, index) => {
                  const color = stage.state === "完成" ? "text-[var(--status-success)]" : stage.state === "执行中" ? "text-[var(--brand-primary)]" : stage.state === "跳过" ? "text-[var(--status-warning)]" : stage.state === "失败" ? "text-[var(--status-danger)]" : "text-[var(--text-muted)]";
                  return (
                    <div key={stage.name} className="grid grid-cols-[32px_minmax(0,1fr)_72px] items-start gap-3 rounded-md border border-[var(--divider-color)] bg-[var(--elevated-background)] p-3">
                      <div className="flex h-7 w-7 items-center justify-center rounded-md border border-[var(--border-color)] font-mono text-xs text-[var(--text-secondary)]">{index + 1}</div>
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-[var(--text-primary)]">{stage.name}</p>
                        <p className="mt-1 text-sm leading-5 text-[var(--text-secondary)]">{stage.detail}</p>
                      </div>
                      <span className={`text-right text-xs font-semibold ${color}`}>{stage.state}</span>
                    </div>
                  );
                })}
              </div>
            </section>
          </section>

          <aside className="flex min-h-0 flex-col gap-4">
            <section className="rounded-lg border border-[var(--border-color)] bg-[var(--card-background)] p-5">
              <p className="text-xs font-semibold tracking-[0.18em] text-[var(--brand-primary)]">本次结果</p>
              <h2 className="mt-2 text-lg font-semibold text-[var(--text-primary)]">{deliveryConclusion}</h2>
              <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">
                {outputPath
                  ? "成品已经保存。请先查看前后对比和质量报告，再决定是否用于正式交付。"
                  : isPortraitSkip
                    ? "检测到人物主体，为保护原图已停止增强。"
                    : reasonText !== "-"
                      ? reasonText
                      : "处理完成后，这里会给出交付建议。"}
              </p>
            </section>

            <section className="rounded-lg border border-[var(--border-color)] bg-[var(--card-background)] p-5">
              <p className="text-xs font-semibold tracking-[0.18em] text-[var(--brand-primary)]">下一步</p>
              <h2 className="mt-2 text-lg font-semibold text-[var(--text-primary)]">查看与交付</h2>
              <div className="mt-4 grid gap-2.5">
                <button type="button" disabled={!canViewCompare} onClick={() => selectForCompare(activeItem)} className="rounded-md bg-[var(--brand-primary)] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[var(--brand-primary-hover)] disabled:cursor-not-allowed disabled:bg-[var(--disabled-background)] disabled:text-[var(--text-muted)]">查看前后对比</button>
                <button type="button" onClick={() => selectForReport(activeItem)} className="rounded-md border border-[var(--feature-enabled-border)] px-4 py-2.5 text-sm font-medium text-[var(--brand-primary)] transition hover:bg-[var(--brand-primary-soft)]">查看质量报告</button>
                <button type="button" onClick={handleOpenOutputDir} className="rounded-md border border-[var(--border-color)] bg-[var(--card-background)] px-4 py-2 text-sm text-[var(--text-primary)] transition hover:border-[var(--brand-primary)] hover:text-[var(--brand-primary)]">打开输出目录</button>
                <button type="button" disabled={!outputPath} onClick={() => handleCopyFinalOutputUrl(activeItem)} className="rounded-md border border-[var(--border-color)] px-4 py-2 text-sm text-[var(--text-primary)] transition hover:bg-[var(--brand-primary-soft)] disabled:cursor-not-allowed disabled:text-[var(--text-muted)]">复制成品路径</button>
              </div>
            </section>
          </aside>
        </main>

        <footer className="mt-3 shrink-0 truncate border-t border-[var(--divider-color)] pt-2 text-center font-mono text-xs tracking-wider text-[var(--text-muted)]">
          {PRODUCT_BRAND_LINE}
        </footer>
      </section>
    );
  }

  if (activeScreen === "safe_beta_compare") {
    const outputPath = firstSafeBetaOutputPath(activeItem, safeBetaResult);
    const processed = findSafeBetaProcessedRow(activeItem, safeBetaResult);
    const outputName = activeItem?.output_filename || processed?.output_name || (outputPath ? outputPath.split(/[\\/]/).pop() : "");
    const statusTextValue = safeBetaItemStatusText(activeItem, safeBetaResult);
    const deliveryText = activeItem?.final_delivery_status === "PASS_WITH_LIMITATION" ? "建议查看后使用" : activeItem?.final_delivery_reason || statusTextValue;
    const outputPreviewUrl = firstSafeBetaOutputPreviewUrl(activeItem, safeBetaResult);
    const originalPreviewUrl = activeItem?.originalUrl || activeItem?.task_result?.original_url || activeItem?.task_result?.input_url || "";
    const compareMetrics = makeSafeBetaQualityMetrics(activeItem, safeBetaResult);
    const rawInputName = activeItem?.name || "";
    const inputDisplayName = getFileDisplayName(rawInputName, "未选择图片");
    const outputDisplayName = getFileDisplayName(outputName, "成品尚未生成");
    return (
      <section className="hdde-enhanced-page relative flex h-full min-h-0 w-full flex-col overflow-hidden bg-[var(--content-background)] p-6 text-[var(--text-primary)]">
        <div className="pointer-events-none absolute inset-0 bg-[var(--content-background)]" />
        <header className="relative z-10 mb-4 flex h-[82px] shrink-0 items-center justify-between gap-6 border-b border-[var(--divider-color)] pb-4">
          <div className="min-w-0">
            <p className="text-xs font-semibold tracking-[0.18em] text-[var(--brand-primary)]">安全增强对比</p>
            <h1 className="mt-2 truncate text-2xl font-semibold tracking-wide text-[var(--text-primary)]">处理前后对比</h1>
            <p className="mt-1 truncate text-sm text-[var(--text-secondary)]" title={rawInputName}>
              {inputDisplayName} · 拖动中线查看清晰度、边缘与颜色变化
            </p>
          </div>

          <div className="flex shrink-0 gap-3">
            <button type="button" onClick={() => setActiveScreen("dashboard")} className="rounded-md border border-[var(--border-color)] px-4 py-2 text-sm tracking-wide text-[var(--text-secondary)] transition hover:border-[var(--brand-primary)] hover:text-[var(--brand-primary)]">
              返回处理中心
            </button>
            <button type="button" onClick={() => setActiveScreen("safe_beta_report")} className="rounded-md border border-[var(--brand-primary)] bg-[var(--brand-primary)] px-5 py-2 text-sm font-bold text-white transition hover:bg-[var(--brand-primary-hover)]">
              查看交付报告
            </button>
          </div>
        </header>

        <main className="relative z-10 grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_340px] gap-5">
          <SafeBetaBeforeAfterCompare
            originalFile={activeItem?.file}
            originalUrl={originalPreviewUrl}
            outputUrl={outputPreviewUrl}
            filename={inputDisplayName}
          />

          <aside className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto pr-1">
            <section className="rounded-lg border border-[var(--border-color)] bg-[var(--card-background)] p-5">
              <p className="text-xs font-semibold tracking-[0.18em] text-[var(--brand-primary)]">对比结论</p>
              <h2 className="mt-2 text-xl font-semibold text-[var(--text-primary)]">{deliveryText || "等待处理结果"}</h2>
              <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">
                重点查看文字与Logo、主体边缘、颜色和低频平滑区域。确认没有明显失真后再用于交付。
              </p>
            </section>

            <section className="rounded-lg border border-[var(--border-color)] bg-[var(--card-background)] p-5">
              <p className="text-xs font-semibold tracking-[0.18em] text-[var(--brand-primary)]">核心评分</p>
              <h2 className="mt-2 text-lg font-semibold text-[var(--text-primary)]">质量概览</h2>
              <div className="mt-4 space-y-3">
                {compareMetrics.map(([keyName, name, value]) => (
                  <SafeBetaMetricBar key={keyName} keyName={keyName} label={name} value={value} active={Number.isFinite(Number(value))} />
                ))}
              </div>
            </section>

            <section className="mt-auto rounded-lg border border-[var(--border-color)] bg-[var(--card-background)] p-5">
              <p className="text-xs font-semibold tracking-[0.18em] text-[var(--brand-primary)]">结果操作</p>
              <h2 className="mt-2 truncate text-lg font-semibold text-[var(--text-primary)]" title={outputName}>{outputDisplayName}</h2>
              <div className="mt-4 grid gap-2.5">
                <button type="button" onClick={() => setActiveScreen("safe_beta_report")} className="rounded-md bg-[var(--brand-primary)] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[var(--brand-primary-hover)]">
                  查看质量报告
                </button>
                <button type="button" onClick={handleOpenOutputDir} className="rounded-md border border-[var(--border-color)] px-4 py-2.5 text-sm text-[var(--text-primary)] transition hover:bg-[var(--brand-primary-soft)]">
                  打开输出文件夹
                </button>
                <button type="button" disabled={!outputPath} onClick={() => handleCopyFinalOutputUrl(activeItem)} className="rounded-md border border-[var(--border-color)] px-4 py-2.5 text-sm text-[var(--text-primary)] transition hover:bg-[var(--brand-primary-soft)] disabled:cursor-not-allowed disabled:text-[var(--text-muted)]">
                  复制成品路径
                </button>
              </div>
            </section>
          </aside>
        </main>

        <footer className="relative z-10 mt-3 w-full shrink-0 truncate border-t border-[var(--divider-color)] px-3 pt-2 text-center font-mono text-xs tracking-wider text-[var(--text-muted)]">
          {PRODUCT_BRAND_LINE}
        </footer>
      </section>
    );
  }

  if (activeScreen === "safe_beta_report") {
    const outputPath = firstSafeBetaOutputPath(activeItem, safeBetaResult);
    const processed = findSafeBetaProcessedRow(activeItem, safeBetaResult);
    const statusTextValue = safeBetaItemStatusText(activeItem, safeBetaResult);
    const reasonText = safeBetaReasonText(activeItem, safeBetaResult);
    const outputName = activeItem?.output_filename || processed?.output_name || (outputPath ? outputPath.split(/[\\/]/).pop() : "");
    const inputSizeBytes = processed?.input_size_bytes ?? activeItem?.input_size_bytes ?? safeBetaResult?.input_size_bytes ?? null;
    const outputSizeBytes = processed?.output_size_bytes ?? activeItem?.output_size_bytes ?? activeItem?.output_size ?? null;
    const jpg95CandidateStatus = processed?.jpg95_candidate_status || activeItem?.jpg95_candidate_status || "not_applicable";
    const lightDeliveryPath = processed?.light_delivery_path || activeItem?.light_delivery_path || "";
    const lightDeliverySizeBytes = processed?.light_delivery_size_bytes ?? activeItem?.light_delivery_size_bytes ?? null;
    const lightDeliverySavedRatio = processed?.light_delivery_saved_ratio ?? activeItem?.light_delivery_saved_ratio ?? null;
    const lightDeliveryStatus = processed?.light_delivery_status || activeItem?.light_delivery_status || "not_applicable";
    const lightDeliveryAvailable = lightDeliveryStatus === "available" && Boolean(lightDeliveryPath);
    const jpg95ReviewDecision = processed?.jpg95_candidate_review_decision || activeItem?.jpg95_candidate_review_decision || "";
    const jpg95ReviewOption = findJpg95ReviewOption(jpg95ReviewDecision);
    const jpg95ReviewLabel = processed?.jpg95_candidate_review_label || activeItem?.jpg95_candidate_review_label || jpg95ReviewOption?.label || (jpg95CandidateStatus === "candidate_for_review" ? "继续检查" : "-");
    const canReviewJpg95Candidate = jpg95CandidateStatus === "candidate_for_review";
    const outputFormatValue = processed?.output_format || activeItem?.output_format || pathFormat(outputPath) || "-";
    const outputDimensions = activeItem?.output_width && activeItem?.output_height ? `${activeItem.output_width} × ${activeItem.output_height}` : processed?.output_width && processed?.output_height ? `${processed.output_width} × ${processed.output_height}` : "-";
    const inputDimensions = processed?.input_width && processed?.input_height ? `${processed.input_width} × ${processed.input_height}` : "-";
    const sizeTreatment = resolve1080pSizeTreatment({
      inputWidth: processed?.input_width,
      inputHeight: processed?.input_height,
      outputWidth: activeItem?.output_width || processed?.output_width,
      outputHeight: activeItem?.output_height || processed?.output_height,
      modeLabel: "1080P安全增强",
    });
    const reportMetrics = makeSafeBetaQualityMetrics(activeItem, safeBetaResult);
    const visibleReportMetrics = reportMetrics.filter(([, , value]) => Number.isFinite(Number(value)));
    const isPortraitSkip = reasonText === "人物图保护跳过";
    const reportConclusion = isPortraitSkip ? "已保护原图" : outputPath ? "成品已生成" : activeItem?.status === "failed" ? "未生成成品" : "等待处理";
    const deliveryAdvice = outputPath ? "建议查看后使用" : "不建议交付";
    const reviewReasons = [
      "检查文字与Logo是否保持清晰、没有笔画变形",
      "检查主体边缘是否自然、没有明显光晕",
      "检查颜色是否接近原图、没有异常偏色",
      ...(isPortraitSkip ? ["检测到人物主体，本次已优先保护原图"] : []),
      ...(reasonText && reasonText !== "-" && !isPortraitSkip ? [reasonText] : []),
    ];
    const positiveSignals = [
      ...(outputPath ? ["1080P成品已生成并保存"] : []),
      ...(outputDimensions !== "-" ? [`输出尺寸为 ${outputDimensions}`] : []),
      ...(lightDeliveryAvailable ? ["已生成便于发送和上传的轻量版本"] : []),
    ];
    const reportMessage = isPortraitSkip
      ? "检测到人物主体，为保护面部和关键结构，本次没有执行增强。"
      : outputPath
        ? "成品已经生成。请结合前后对比检查文字、Logo、边缘和颜色后再决定是否交付。"
        : "当前没有可交付成品，请根据页面提示重新处理。";
    const rawInputName = activeItem?.name || "";
    const inputDisplayName = getFileDisplayName(rawInputName, "未选择图片");
    const outputDisplayName = getFileDisplayName(outputName);
    const dimensionSummary = [
      inputDimensions !== "-" ? `输入 ${inputDimensions}` : "",
      outputDimensions !== "-" ? `输出 ${outputDimensions}` : "",
    ].filter(Boolean).join(" · ");
    const outputFacts = [
      outputName ? ["输出文件", outputDisplayName, outputName] : null,
      inputDimensions !== "-" ? ["输入尺寸", inputDimensions, ""] : null,
      outputDimensions !== "-" ? ["输出尺寸", outputDimensions, ""] : null,
      sizeTreatment ? ["尺寸处理", sizeTreatment.label, sizeTreatment.detail] : null,
      outputFormatValue !== "-" ? ["输出格式", outputFormatValue.toUpperCase(), ""] : null,
      inputSizeBytes ? ["输入体积", formatBytesToMb(inputSizeBytes), ""] : null,
      outputSizeBytes ? ["成品体积", formatBytesToMb(outputSizeBytes), ""] : null,
      lightDeliveryAvailable
        ? ["轻量版本", `${formatBytesToMb(lightDeliverySizeBytes)} · 节省 ${formatPercentValue(lightDeliverySavedRatio)}`, lightDeliveryPath]
        : null,
    ].filter(Boolean);
    return (
      <section className="hdde-report-page hdde-enhanced-page" data-testid="safe-quality-report-page">
        <header className="hdde-report-header">
          <div className="hdde-report-heading">
            <p className="hdde-eyebrow">质量报告</p>
            <h1>高清交付评估</h1>
            <p title={rawInputName}>{inputDisplayName} · 1080P安全增强</p>
          </div>
          <div className="hdde-report-actions">
            <button type="button" className="hdde-report-button hdde-report-button--secondary" onClick={() => setActiveScreen("safe_beta_compare")}>
              返回对比结果
            </button>
            <UnifiedFeedback
              taskId={activeItem?.taskId || ""}
              sourceFeature="enhancement_1080p"
              stage="quality_review"
              triggerLabel="反馈问题"
              triggerClassName="hdde-report-button hdde-report-button--primary"
              testId="safe-quality-report-feedback-package"
              disabled={!safeBetaResult?.output_dir || isProcessingQueue}
            />
          </div>
        </header>

        <div className="hdde-report-layout">
          <main className="hdde-report-main">
            <section className="hdde-report-panel">
              <div className="hdde-report-section-heading">
                <div>
                  <p className="hdde-eyebrow">核心指标</p>
                  <h2>质量评分</h2>
                </div>
                {dimensionSummary ? <span>{dimensionSummary}</span> : null}
              </div>
              <div className="hdde-report-score-grid">
                {visibleReportMetrics.map(([keyName, label, value]) => (
                  <SafeBetaMetricBar key={keyName} label={label} keyName={keyName} value={value} active={Number.isFinite(Number(value))} />
                ))}
              </div>
            </section>

            <section className="hdde-report-panel">
              <div className="hdde-report-section-heading">
                <div>
                  <p className="hdde-eyebrow">输出结果</p>
                  <h2>交付文件</h2>
                </div>
                <span>{reportConclusion}</span>
              </div>
              <dl className="hdde-report-facts">
                {outputFacts.map(([label, value, title]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd title={title}>{value}</dd>
                  </div>
                ))}
              </dl>
            </section>
          </main>

          <aside className="hdde-report-side">
            <section className="hdde-report-panel hdde-report-verdict">
              <p className="hdde-eyebrow">交付结论</p>
              <div className="hdde-report-verdict-line">
                <h2>{deliveryAdvice}</h2>
                <span data-tone={outputPath ? "warning" : "negative"}>{reportConclusion}</span>
              </div>
              <p>{reportMessage}</p>
            </section>

            <section className="hdde-report-list" data-tone="warning">
              <h3>复核重点</h3>
              <ul>{reviewReasons.map((item, index) => <li key={`review-${index}`}>{item}</li>)}</ul>
            </section>

            <section className="hdde-report-panel hdde-report-archive">
              <h2>结果操作</h2>
              <p>文件位置不会直接显示在报告中，可通过以下操作获取。</p>
              <button type="button" className="hdde-report-button hdde-report-button--primary" onClick={handleOpenOutputDir}>打开输出文件夹</button>
              <button type="button" className="hdde-report-button hdde-report-button--secondary" disabled={!outputPath} onClick={() => handleCopyFinalOutputUrl(activeItem)}>复制成品路径</button>
              <button type="button" className="hdde-report-button hdde-report-button--secondary" onClick={() => setActiveScreen("dashboard")}>完成复核并返回</button>
            </section>

            {positiveSignals.length ? (
              <section className="hdde-report-list" data-tone="positive">
                <h3>正向信号</h3>
                <ul>{positiveSignals.map((item, index) => <li key={`positive-${index}`}>{item}</li>)}</ul>
              </section>
            ) : null}

            <section className="hdde-report-panel">
              <p className="hdde-eyebrow">建议用途</p>
              <h2>交付建议</h2>
              <p className="hdde-report-usage">
                {outputPath ? "适合本地预览、演示稿和方案初稿；正式使用前请完成前后对比复核。" : "当前不建议用于正式交付。"}
              </p>
            </section>

            {canReviewJpg95Candidate ? (
              <section className="hdde-report-panel">
                <p className="hdde-eyebrow">轻量版候选</p>
                <h2>选择使用建议</h2>
                <p className="hdde-report-usage">高清主图保持不变；可为便于发送和上传的轻量版本记录建议。</p>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  {JPG95_REVIEW_OPTIONS.map((option) => (
                    <button
                      key={option.decision}
                      type="button"
                      onClick={() => handleSetJpg95CandidateReview(option.decision)}
                      className={`rounded-md border px-3 py-2 text-xs transition ${
                        jpg95ReviewDecision === option.decision
                          ? "border-[var(--brand-primary)] bg-[var(--brand-primary-soft)] text-[var(--brand-primary)]"
                          : "border-[var(--border-color)] text-[var(--text-primary)] hover:bg-[var(--brand-primary-soft)]"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <p className="mt-2 text-xs text-[var(--text-secondary)]">当前建议：{jpg95ReviewLabel}</p>
              </section>
            ) : null}

          </aside>
        </div>
      </section>
    );
  }

  const outputLocationLabel = processingMode === PROCESSING_MODE_SAFE_BETA
    ? "当前状态：安全增强输出目录"
    : processingMode === PROCESSING_MODE_FOUR_K
      ? "当前状态：固定4K输出目录"
      : appliedOutputDir.trim()
        ? "当前状态：自定义目录"
        : "当前状态：默认目录";
  const currentOutputDir = directoryReady
    ? appliedOutputDir.trim() || resolveProcessingOutputDirectory(workdirInfo, processingMode)
    : workdirInfo || workdirError
      ? directoryMessage
      : "正在初始化工作目录";
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
      ? "安全增强处理中"
      : safeBetaResult?.status === "NEED_RESELECT"
        ? safeBetaResult?.message || "本地文件访问已失效"
      : safeBetaResult?.status === "BLOCKED"
        ? safeBetaResult?.message || "处理失败"
        : safeBetaResult?.status
          ? "处理完成"
          : "等待任务");
  const isDiagnosisActive = activeItem?.taskFamily === "image_diagnosis";
  const deliveryActionItem = activeItem?.status === "completed" && !isDiagnosisActive
    ? activeItem
    : completedItems[completedItems.length - 1] || null;
  const betaActionItem = isSafeBetaSelected ? deliveryActionItem || activeItem : null;
  const safeBetaPrimaryOutputPath = isSafeBetaSelected ? firstSafeBetaOutputPath(betaActionItem, safeBetaResult) : "";
  const canCopyDeliveryPath = isSafeBetaSelected ? Boolean(safeBetaPrimaryOutputPath) : Boolean(deliveryActionItem?.final_output_url);

  const queueCompletedCount = fileQueue.filter((item) => item.status === "completed" && item.taskFamily !== "image_diagnosis").length;
  const queueFailedCount = fileQueue.filter((item) => (item.status === "failed" || item.status === "blocked") && item.taskFamily !== "image_diagnosis").length;
  const currentProgress = isProcessingQueue
    ? Math.max(0, Math.min(100, Number(activeItem?.progress || safeBetaResult?.progress || 0)))
    : activeItem?.status === "completed"
      ? 100
      : Math.max(0, Math.min(100, Number(activeItem?.progress || 0)));
  const currentStageLabel = !directoryReady
    ? "正式目录阻断"
    : isProcessingQueue
      ? currentIndex
        ? `正在处理第 ${currentIndex} 张`
        : "正在处理"
      : isDiagnosisActive && activeItem?.status === "completed"
        ? "诊断完成"
      : activeItem?.status === "processing"
        ? "正在处理图片"
        : activeItem?.status === "pending"
          ? "等待队列处理"
      : activeItem?.status === "completed"
        ? "处理完成"
        : activeItem?.status === "failed"
          ? "处理失败"
          : fileQueue.length
            ? "等待开始"
            : "等待导入";
  const currentNextAction = !directoryReady
    ? "前往系统设置恢复或重新选择正式目录"
    : isProcessingQueue
      ? "请保持应用运行，等待当前任务完成"
      : isDiagnosisActive && activeItem?.status === "completed"
        ? "打开图片诊断记录查看结论与推荐"
      : activeItem?.status === "processing" || activeItem?.status === "pending"
        ? "请保持应用运行，队列会逐张完成处理"
      : activeItem?.status === "completed"
        ? "查看结果并确认交付信息"
        : activeItem?.status === "failed"
          ? "查看失败原因后重新处理"
          : fileQueue.length
            ? "确认模式和输出目录后开始处理"
            : "选择或拖入一张图片";
  const blockedFormalPath = workdirInfo?.app_data_root || workdirInfo?.failed_path || "";
  const blockedFormalReason = workdirInfo?.failure_reason || directoryMessage;
  const noticeIsError =
    !directoryReady ||
    activeItem?.status === "failed" ||
    activeItem?.status === "blocked" ||
    safeBetaResult?.status === "BLOCKED" ||
    safeBetaResult?.status === "NEED_RESELECT";
  const deliveryOutputPath = isSafeBetaSelected
    ? safeBetaPrimaryOutputPath || safeBetaResult?.output_dir || currentOutputDir
    : activeItem?.taskFamily === "color_correction" && !deliveryActionItem?.output_path
      ? activeItem.output_path || activeItem.output_dir || currentOutputDir
    : deliveryActionItem?.taskFamily === "color_correction"
      ? deliveryActionItem.output_path || deliveryActionItem.output_dir || currentOutputDir
      : deliveryActionItem?.final_output_url || currentOutputDir;
  const deliveryOutputDirectory = activeItem?.taskFamily === "color_correction"
    ? activeItem.output_dir || currentOutputDir
    : deliveryActionItem?.taskFamily === "color_correction"
    ? deliveryActionItem.output_dir || currentOutputDir
    : currentOutputDir;
  const handleOpenDeliveryOutputDirectory = () => {
    if (deliveryActionItem?.taskFamily === "color_correction") {
      handleOpenItemOutputFolder(deliveryActionItem);
      return;
    }
    handleOpenOutputDir();
  };
  const batchStatusLabel = activeColorBatch?.status === "processing"
    ? "处理中"
    : activeColorBatch?.status === "completed"
      ? "已完成"
      : activeColorBatch?.status === "failed"
        ? "处理失败"
        : "等待处理";

  return (
    <section
      className={`hdde-processing-page hdde-page-frame ${isDragging ? "is-dragging" : ""}`}
      data-testid="processing-center"
      onDragOver={(event) => {
        event.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setIsDragging(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setIsDragging(false);
        addFiles(event.dataTransfer.files);
      }}
    >
      <input
        ref={fileInputRef}
        data-testid="processing-file-input"
        type="file"
        accept="image/*"
        multiple
        hidden
        onChange={handleFileChange}
      />

      <div className="hdde-processing-stack hdde-page-stack">
        <HddePageHeader
          title="处理中心"
          description="集中创建与查看当前任务，已结束记录继续保留在同一处理中心的历史任务中。"
        />
        <section className="hdde-processing-panel hdde-processing-prepare" aria-labelledby="processing-prepare-title">
          <header className="hdde-processing-section-heading">
            <div>
              <p className="hdde-eyebrow">任务准备</p>
              <h2 id="processing-prepare-title">准备新任务</h2>
              <p>依次确认图片、处理模式与输出目录，然后开始处理。</p>
            </div>
            <span
              className="hdde-processing-readiness"
              data-tone={directoryReady ? "positive" : "negative"}
              data-testid="processing-directory-status"
            >
              {directoryReady ? "正式目录可用" : "正式目录不可用"}
            </span>
          </header>

          {!directoryReady && (workdirInfo || workdirError) ? (
            <div className="hdde-processing-blocked" role="alert" data-testid="processing-blocked-message">
              <div>
                <strong>正式目录当前不可用，图片处理已暂停。</strong>
                <p>{blockedFormalReason}</p>
                {blockedFormalPath ? <code>{blockedFormalPath}</code> : null}
              </div>
              <a href="/settings">前往系统设置修复</a>
            </div>
          ) : null}

          <div className="hdde-processing-steps">
            <article className="hdde-processing-step">
              <span className="hdde-processing-step-index">1</span>
              <div className="hdde-processing-step-body">
                <label>图片导入</label>
                <button
                  type="button"
                  className="hdde-processing-secondary-action"
                  data-testid="processing-select-image"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isProcessingQueue}
                >
                  选择本地图片
                </button>
                <p>{localQueueItems.length ? `已选择 ${localQueueItems.length} 张：${localQueueItems.slice(0, 2).map((item) => item.name).join("、")}${localQueueItems.length > 2 ? "…" : ""}` : "也可将图片拖入当前页面"}</p>
              </div>
            </article>

            <article className="hdde-processing-step">
              <span className="hdde-processing-step-index">2</span>
              <div className="hdde-processing-step-body">
                <label htmlFor="processing-mode">处理模式</label>
                <select
                  id="processing-mode"
                  data-testid="processing-mode"
                  value={processingMode}
                  onChange={(event) => setProcessingMode(event.target.value)}
                  disabled={isProcessingQueue}
                >
                  {processingModeOptions.map((option) => (
                    <option key={option.id} value={option.id}>{option.label}</option>
                  ))}
                </select>
                <p>{processingMode === PROCESSING_MODE_SAFE_BETA ? "适用于当前已证明范围内的中文商业非人像图。" : getProcessingModeDisplay(processingMode).desc}</p>
              </div>
            </article>

            <article className="hdde-processing-step">
              <span className="hdde-processing-step-index">3</span>
              <div className="hdde-processing-step-body">
                <label>输出目录</label>
                <code className="hdde-processing-path" title={currentOutputDir}>{currentOutputDir}</code>
                <button
                  type="button"
                  className="hdde-processing-tertiary-action"
                  onClick={handleSelectOutputDir}
                  disabled={!directoryReady || isProcessingQueue || processingMode === PROCESSING_MODE_FOUR_K}
                >
                  {processingMode === PROCESSING_MODE_FOUR_K ? "4K输出目录由合同固定" : "更换输出目录"}
                </button>
              </div>
            </article>

            <article className="hdde-processing-step hdde-processing-step--action">
              <span className="hdde-processing-step-index">4</span>
              <div className="hdde-processing-step-body">
                <label>开始处理</label>
                <button
                  type="button"
                  className="hdde-processing-primary-action"
                  data-testid="processing-start"
                  onClick={handleStartQueue}
                  disabled={!canStartExecution}
                >
                  {isProcessingQueue ? "正在处理…" : "开始处理"}
                </button>
                <p>{!directoryReady ? "请先修复正式目录" : !localQueueItems.length && processingMode !== PROCESSING_MODE_SAFE_BETA ? "请先选择图片" : isProcessingQueue ? "任务执行期间不可重复提交" : "所有必要条件已满足"}</p>
              </div>
            </article>
          </div>

          {processingMode === PROCESSING_MODE_SAFE_BETA ? (
            <details className="hdde-processing-boundary">
              <summary>查看1080P安全增强使用边界</summary>
              <ul>
                {safeBetaBoundaryItems.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </details>
          ) : null}
          {outputDirSuccess ? <p className="hdde-processing-inline-feedback" data-tone="positive">{outputDirSuccess}</p> : null}
          {outputDirError ? <p className="hdde-processing-inline-feedback" data-tone="negative">{outputDirError}</p> : null}
        </section>

        {activeColorBatch ? (
          <section className="hdde-processing-panel hdde-processing-batch-summary" aria-labelledby="color-batch-summary-title" data-testid="color-batch-summary">
            <header className="hdde-processing-section-heading hdde-processing-section-heading--compact">
              <div>
                <p className="hdde-eyebrow">批量颜色校正</p>
                <h2 id="color-batch-summary-title">{batchStatusLabel}</h2>
                <p>每张图片独立分析与处理；单张失败不会中断其他图片。</p>
              </div>
              <StatusPill status={activeColorBatch.status} />
            </header>
            <div className="hdde-processing-batch-facts">
              <div><span>总数</span><strong>{activeColorBatch.total_count}</strong></div>
              <div><span>已完成</span><strong>{activeColorBatch.completed_count}</strong></div>
              <div><span>失败</span><strong>{activeColorBatch.failed_count}</strong></div>
              <div><span>待确认</span><strong>{activeColorBatch.pending_review_count || 0}</strong></div>
              <div><span>已确认</span><strong>{activeColorBatch.confirmed_count || 0}</strong></div>
              <div><span>整体进度</span><strong>{activeColorBatch.progress}%</strong></div>
            </div>
            <div className="hdde-processing-progress hdde-processing-progress--large" aria-label={`批量颜色校正整体进度 ${activeColorBatch.progress}%`}>
              <span style={{ width: `${Math.max(0, Math.min(100, Number(activeColorBatch.progress || 0)))}%` }} />
            </div>
            <p className="hdde-processing-batch-output" title={activeColorBatch.output_directory}>成功结果保存到颜色校正正式输出目录；可在下方逐图打开结果或文件夹。</p>
          </section>
        ) : null}

        <section className="hdde-processing-panel hdde-processing-queue" aria-labelledby="processing-queue-title">
          <div className="hdde-processing-task-tabs" role="tablist" aria-label="处理中心任务范围">
            <button type="button" role="tab" aria-selected={taskView === "current"} onClick={() => setTaskView("current")}>当前任务</button>
            <button type="button" role="tab" aria-selected={taskView === "history"} onClick={() => setTaskView("history")}>历史任务</button>
          </div>
          <header className="hdde-processing-section-heading hdde-processing-section-heading--compact">
            <div>
              <h2 id="processing-queue-title">任务列表</h2>
            </div>
            <span className="hdde-processing-count">{visibleTaskItems.length} 条</span>
          </header>

          <div className="hdde-processing-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>文件名称</th>
                  <th>处理模式</th>
                  <th>状态与进度</th>
                  <th>结果与交付</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {!visibleTaskItems.length ? (
                  <tr>
                    <td colSpan={5}>
                      <div className="hdde-processing-empty">
                        <strong>{taskView === "history" ? "暂无历史任务" : "暂无当前任务"}</strong>
                        <span>{taskView === "history" ? "已结束的真实任务会从统一任务事实源显示在这里。" : "选择或拖入图片后，进行中的任务会在这里显示。"}</span>
                      </div>
                    </td>
                  </tr>
                ) : visibleTaskItems.map((item) => {
                  const isSafeBetaRow = item.mode === PROCESSING_MODE_SAFE_BETA;
                  const compareDisabled = isSafeBetaRow ? item.status !== "completed" : item.status !== "completed" || !item.final_output_url;
                  const itemProgress = Math.max(0, Math.min(100, Number(item.progress || 0)));
                  const resultText = item.output_filename || item.error || (
                    item.status === "completed"
                      ? item.taskFamily === "image_diagnosis" ? "诊断结果已记录" : "已生成结果"
                      : "等待输出"
                  );
                  return (
                    <tr key={item.id} data-status={item.status}>
                      <td>
                        <strong title={item.name}>{item.name}</strong>
                        <span>
                          {item.input_width && item.input_height ? `${item.input_width} × ${item.input_height}` : item.size}
                          {item.created_at ? ` · ${new Date(item.created_at).toLocaleString("zh-CN")}` : ""}
                        </span>
                        {taskView === "history" ? <small className="hdde-processing-trace">功能：{item.featureKey || "未记录"}<br />TASK_ID：{item.taskId}</small> : null}
                      </td>
                      <td>{getModeDisplay(item.mode || activeMode).label}</td>
                      <td>
                        <div className="hdde-processing-status-cell">
                          <StatusPill status={item.status} />
                          <span>{itemProgress}%</span>
                        </div>
                        {processingStageLabel(item.processing_stage, item.status) ? (
                          <small>{processingStageLabel(item.processing_stage, item.status)}</small>
                        ) : null}
                        <div className="hdde-processing-progress" aria-label={`${item.name} 处理进度 ${itemProgress}%`}>
                          <span style={{ width: `${itemProgress}%` }} />
                        </div>
                      </td>
                      <td>
                        <span className={item.error ? "hdde-processing-result is-error" : "hdde-processing-result"} title={resultText}>{resultText}</span>
                        <small>
                          {item.output_width && item.output_height
                            ? `${item.output_width} × ${item.output_height} · ${String(item.output_format || "PNG").toUpperCase()}`
                            : item.status === "completed" ? "未生成新的输出文件" : "等待输出"}
                          {item.completed_at ? ` · ${new Date(item.completed_at).toLocaleString("zh-CN")}` : ""}
                        </small>
                        <DeliveryPill status={item.final_delivery_status} item={item} />
                        {item.taskFamily === "color_correction" && item.status === "completed" ? (
                          <span className="hdde-processing-review-state" data-status={item.review_status}>{item.review_status === "confirmed" ? "已确认" : "待确认"}</span>
                        ) : null}
                        {taskView === "history" ? (
                          <small className="hdde-processing-trace">RESULT_ID：{item.resultId || "无"}<br />DELIVERY_ID：{item.deliveryId || "无"}</small>
                        ) : null}
                      </td>
                      <td>
                        <div className="hdde-processing-row-actions">
                          <button type="button" disabled={!item.taskId} onClick={() => locateQueueItem(item)}>{item.taskFamily === "color_correction" ? "复核结果" : item.taskFamily === "image_diagnosis" ? "查看诊断" : "查看详情"}</button>
                          <button type="button" disabled={compareDisabled} onClick={() => handleOpenFinalOutput(item)}>打开成品</button>
                          <button type="button" disabled={!item.output_path && !isSafeBetaRow} onClick={() => handleOpenItemOutputFolder(item)}>打开文件夹</button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <div className="hdde-processing-summary-grid">
          <section className="hdde-processing-panel hdde-processing-summary" aria-labelledby="processing-status-title">
            <header className="hdde-processing-section-heading hdde-processing-section-heading--compact">
              <div>
                <p className="hdde-eyebrow">任务进度</p>
                <h2 id="processing-status-title">进度与下一步</h2>
              </div>
              <span className="hdde-processing-readiness" data-tone={directoryReady ? "positive" : "negative"}>
                {directoryReady ? "允许处理" : "禁止处理"}
              </span>
            </header>
            <dl>
              <div><dt>当前任务</dt><dd>{activeItem?.name || "尚未选择图片"}</dd></div>
              <div><dt>当前阶段</dt><dd>{currentStageLabel}</dd></div>
              <div><dt>整体进度</dt><dd>{currentProgress}%</dd></div>
              <div><dt>下一步</dt><dd>{currentNextAction}</dd></div>
            </dl>
            <div className="hdde-processing-progress hdde-processing-progress--large" aria-label={`当前任务进度 ${currentProgress}%`}>
              <span style={{ width: `${currentProgress}%` }} />
            </div>
            <p className={noticeIsError ? "hdde-processing-notice is-error" : "hdde-processing-notice"} aria-live="polite">
              {activeColorBatch && ["pending", "processing"].includes(activeColorBatch.status)
                ? `批量颜色校正正在逐张处理 · ${activeColorBatch.completed_count + activeColorBatch.failed_count} / ${activeColorBatch.total_count} 张已结束`
                : <>{isProcessingQueue && currentIndex ? `逐张处理 · 第 ${currentIndex} / ${fileQueue.length} 张 · ` : ""}{notice}</>}
            </p>
          </section>

          <section className="hdde-processing-panel hdde-processing-summary" aria-labelledby="processing-delivery-title">
            <header className="hdde-processing-section-heading hdde-processing-section-heading--compact">
              <div>
                <p className="hdde-eyebrow">交付信息</p>
                <h2 id="processing-delivery-title">真实输出与结果</h2>
              </div>
              <span className="hdde-processing-count">{queueCompletedCount} 已完成</span>
            </header>
            <dl>
              <div><dt>输出目录</dt><dd><code title={deliveryOutputDirectory}>{deliveryOutputDirectory}</code></dd></div>
              <div><dt>结果数量</dt><dd>{queueCompletedCount} 成功 / {queueFailedCount} 失败</dd></div>
              <div><dt>当前结果</dt><dd><code title={deliveryOutputPath}>{deliveryOutputPath || "尚未生成"}</code></dd></div>
              <div><dt>交付状态</dt><dd>{deliveryActionItem ? <DeliveryPill status={deliveryActionItem.final_delivery_status} item={deliveryActionItem} /> : "等待结果"}</dd></div>
            </dl>
            <div className="hdde-processing-delivery-actions">
              <button type="button" onClick={handleOpenDeliveryOutputDirectory} disabled={!directoryReady}>打开输出目录</button>
              <button type="button" onClick={() => handleOpenFinalOutput(deliveryActionItem)} disabled={!deliveryActionItem?.final_output_url}>打开结果</button>
              <button type="button" onClick={() => handleCopyFinalOutputUrl(isSafeBetaSelected ? betaActionItem : deliveryActionItem)} disabled={!canCopyDeliveryPath}>复制成品路径</button>
              <button type="button" onClick={() => selectForReport(deliveryActionItem)} disabled={!deliveryActionItem || deliveryActionItem.taskFamily === "color_correction"}>查看交付报告</button>
            </div>
          </section>
        </div>
      </div>
    </section>
  );
}
