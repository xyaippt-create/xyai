export const FEATURE_STATUSES = Object.freeze({
  ENABLED: "已启用",
  BETA: "Beta",
  IN_DEVELOPMENT: "开发中",
  PLANNED: "待开发",
});

export const FEATURE_STATUS_VALUES = Object.freeze(Object.values(FEATURE_STATUSES));

export const FEATURE_STATUS_META = Object.freeze({
  [FEATURE_STATUSES.ENABLED]: { tone: "success", label: FEATURE_STATUSES.ENABLED },
  [FEATURE_STATUSES.BETA]: { tone: "info", label: FEATURE_STATUSES.BETA },
  [FEATURE_STATUSES.IN_DEVELOPMENT]: { tone: "warning", label: FEATURE_STATUSES.IN_DEVELOPMENT },
  [FEATURE_STATUSES.PLANNED]: { tone: "muted", label: FEATURE_STATUSES.PLANNED },
});

export function isValidFeatureStatus(status) {
  return FEATURE_STATUS_VALUES.includes(status);
}

export function normalizeFeatureStatus(status, source = "unknown") {
  if (isValidFeatureStatus(status)) return status;
  if (import.meta.env.DEV) {
    console.warn(`[HDDE UI] Invalid feature status from ${source}:`, status, `Falling back to ${FEATURE_STATUSES.PLANNED}.`);
  }
  return FEATURE_STATUSES.PLANNED;
}

export function getFeatureStatusMeta(status, source) {
  const normalized = normalizeFeatureStatus(status, source);
  return FEATURE_STATUS_META[normalized];
}

function isPlainRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isMeaningfulText(value) {
  if (typeof value !== "string") return false;
  const normalized = value.trim();
  if (!normalized) return false;
  return !/^(?:-|--|n\/?a|null|undefined|unknown|placeholder|mock|waiting|待接入|暂无数据|计算中|等待)$/i.test(normalized);
}

function isPositiveNumber(value) {
  return Number.isFinite(value) && value > 0;
}

function isFiniteReportNumber(report, field) {
  return Number.isFinite(report?.[field]);
}

function firstMeaningfulText(...values) {
  return values.find(isMeaningfulText) || "";
}

function isUsableAssetSource(value) {
  if (!isMeaningfulText(value)) return false;
  const source = value.trim();
  if (/\b(?:placeholder|mock|waiting)\b/i.test(source)) return false;
  if (/^[a-zA-Z]:[\\/]/.test(source)) return false;
  return /^https?:\/\//i.test(source) || /^\/(?!\/)/.test(source);
}

function isFinalDeliveryStatus(value) {
  if (!isMeaningfulText(value)) return false;
  return ["PASS", "PASS_WITH_LIMITATION", "FAIL", "REJECT"].includes(value.trim().toUpperCase());
}

export function validateComparisonAssets(assets, context = {}) {
  const missingFields = [];
  if (!isPlainRecord(assets)) {
    return { valid: false, missingFields: ["comparison_assets"], reason: "缺少真实对比资产。" };
  }

  const taskId = firstMeaningfulText(context.taskId, context.task_id, assets.taskId, assets.task_id);
  const originalSource = firstMeaningfulText(assets.originalUrl, assets.original_url, assets.input_url);
  const resultSource = firstMeaningfulText(assets.resultUrl, assets.outputUrl, assets.preview_output_url, assets.final_output_url);

  if (!taskId) missingFields.push("task_id");
  if (!isUsableAssetSource(originalSource)) missingFields.push("original_source");
  if (!isUsableAssetSource(resultSource)) missingFields.push("result_source");

  return {
    valid: missingFields.length === 0,
    missingFields,
    reason: missingFields.length ? `对比资产不完整：${missingFields.join(", ")}` : "真实任务的原图与结果图来源完整。",
  };
}

export function validateQualityReport(report, context = {}) {
  if (!isPlainRecord(report) || Object.keys(report).length === 0) {
    return { valid: false, missingFields: ["task_report"], reason: "尚未生成真实task_report。" };
  }

  const taskResult = isPlainRecord(context.taskResult) ? context.taskResult : {};
  const missingFields = [];
  const taskId = firstMeaningfulText(report.task_id, report.report_id, context.taskId, context.task_id);
  const inputIdentity = firstMeaningfulText(taskResult.input_filename, taskResult.input_path);
  const outputIdentity = firstMeaningfulText(
    taskResult.output_filename,
    taskResult.output_path,
    taskResult.final_output_filename,
    taskResult.final_output_path,
  );
  const processingFact = firstMeaningfulText(
    taskResult.processing_profile,
    taskResult.mode,
    taskResult.resize_policy,
    taskResult.output_format,
  );

  if (!taskId) missingFields.push("task_identity");
  if (!inputIdentity || !isPositiveNumber(taskResult.input_width) || !isPositiveNumber(taskResult.input_height)) {
    missingFields.push("input_facts");
  }
  if (!outputIdentity || !isPositiveNumber(taskResult.output_width) || !isPositiveNumber(taskResult.output_height)) {
    missingFields.push("output_facts");
  }
  if (!processingFact) missingFields.push("processing_fact");

  ["clarity_score", "text_clarity_score", "edge_quality_score", "color_fidelity_score", "texture_score", "delivery_score"].forEach((field) => {
    if (!isFiniteReportNumber(report, field)) missingFields.push(field);
  });
  ["pseudo_hd_risk", "artifact_risk"].forEach((field) => {
    if (!isMeaningfulText(report[field])) missingFields.push(field);
  });
  if (!isFinalDeliveryStatus(report.final_delivery_status)) missingFields.push("final_delivery_status");
  ["final_delivery_reason", "final_delivery_risk_level", "final_delivery_recommended_usage"].forEach((field) => {
    if (!isMeaningfulText(report[field])) missingFields.push(field);
  });

  return {
    valid: missingFields.length === 0,
    missingFields,
    reason: missingFields.length ? `质量报告合同不完整：${missingFields.join(", ")}` : "真实task_report合同完整。",
  };
}

// Minimal compatibility envelope only. It preserves raw backend facts and does
// not replace deliveryStatus.js or reinterpret any quality/delivery gate.
export function preserveRawPlatformStatus(rawStatus) {
  return {
    raw_status: rawStatus ?? null,
    processing_status: null,
    quality_status: null,
    delivery_status: null,
    output_status: null,
  };
}
