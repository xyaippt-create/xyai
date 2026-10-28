import React, { useEffect, useMemo, useState } from "react";
import { resolveDeliveryStatus } from "./deliveryStatus.js";
import { getFileDisplayName } from "./fileDisplayName.js";
import { HddeTechnicalDetails } from "./HddeUI.jsx";
import { SliderCompareStage } from "./ImageSliderComparePage.jsx";
import { processingModeDisplayName, resultConclusionFromDelivery } from "./productDisplay.js";
import { ReferenceComparison, referenceResultSummary } from "./ColorCorrectionPage.jsx";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const EXPECTED_LOG_TOTAL = 11;

const standardTimelines = [
  ["读取图片", "确认原图可用并读取基础信息。"],
  ["分析内容", "识别文字、边缘、纹理与压缩特征。"],
  ["执行处理", "按当前模式完成尺寸与画质处理。"],
  ["核对结果", "检查结构、颜色和输出文件完整性。"],
  ["生成成品", "写入结果并准备对比与报告。"],
];

const fourKTimelines = [
  ["读取图片", "确认原图和正式目录可用。"],
  ["核对策略", "核对4K模式与尺寸处理合同。"],
  ["超分增强", "保持比例，超分重建细节至4K长边。"],
  ["写入成品", "将PNG成品写入正式4K输出目录。"],
  ["核对结果", "检查文件可读取、尺寸正确且原图未改变。"],
];

function normalizeUrl(value) {
  if (!value) return "";
  if (/^https?:\/\//i.test(value)) return value;
  if (/^[a-zA-Z]:[\\/]/.test(value) || /^\\\\/.test(value)) return "";
  return `${API_BASE}${value.startsWith("/") ? value : `/${value}`}`;
}

async function requestDeliveryJson(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.success === false) {
    const detail = payload?.detail;
    const error = new Error(detail?.message || payload?.message || "正式交付暂时无法完成。");
    error.payload = payload;
    throw error;
  }
  return payload;
}

function getTaskId(taskConfig) {
  return taskConfig?.taskId
    || taskConfig?.task_id
    || taskConfig?.compareAssets?.taskId
    || taskConfig?.compareAssets?.task_id
    || "";
}

function modeLabel(mode) {
  return processingModeDisplayName(mode);
}

function statusLabel(status, isFourK) {
  if (status === "completed") return "已完成";
  if (status === "failed" || status === "blocked") return "处理未完成";
  if (status === "queued" || status === "pending") return "等待处理";
  return isFourK ? "正在进行4K画质增强" : "正在处理";
}

function stageLabel(value, status) {
  if (status === "completed") return "处理完成";
  if (status === "failed" || status === "blocked") return "处理未完成";
  const labels = {
    pending: "等待处理",
    contract_validation: "核对处理策略",
    image_processing: "正在处理图片",
    output_file_write: "正在写入成品",
    output_verify: "正在核对结果",
  };
  return labels[String(value || "").toLowerCase()] || "";
}

function formatBytes(value) {
  const size = Number(value);
  if (!Number.isFinite(size) || size <= 0) return "";
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(2)} MB`;
  return `${Math.max(1, Math.round(size / 1024))} KB`;
}

function formatDuration(value) {
  const duration = Number(value);
  if (!Number.isFinite(duration) || duration < 0) return "";
  if (duration < 1000) return `${Math.round(duration)} 毫秒`;
  return `${(duration / 1000).toFixed(duration >= 10000 ? 0 : 1)} 秒`;
}

function formatDurationBetween(startValue, endValue) {
  if (!startValue || !endValue) return "";
  const start = new Date(startValue).getTime();
  const end = new Date(endValue).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return "";
  return formatDuration(end - start);
}

function formatDate(value) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleString("zh-CN");
}

function fileNameFromPath(value) {
  return String(value || "").split(/[\\/]/).pop() || "";
}

function firstList(value) {
  return Array.isArray(value) ? value.filter((item) => typeof item === "string" && item.trim()) : [];
}

function compactColorChange(items) {
  const value = items.find((item) => !/原图哈希|输出已完成|保留原始尺寸/.test(item)) || "";
  if (/中性色偏差/.test(value)) return "中性色偏已受控";
  if (/中间调层次/.test(value)) return "层次与局部清晰度已调整";
  if (/人物或前景平均亮度/.test(value)) return "人物与前景亮度已调整";
  if (/深色区域/.test(value)) return "暗部堵塞已降低";
  if (/低强度保护性处理/.test(value)) return "采用低强度保护处理";
  if (/品牌强色/.test(value)) return "品牌强色已保护";
  if (/处理后复核/.test(value)) return "处理强度已安全回收";
  return value ? value.replace(/[，。].*$/, "") : "变化幅度待对比确认";
}

function compactColorReview(items) {
  const value = items[0] || "";
  if (/肤色.*LED屏文字.*品牌色/.test(value)) return "肤色、屏幕文字与品牌色";
  if (/中性色证据/.test(value)) return "白平衡变化";
  if (/饱和度变化/.test(value)) return "饱和度变化";
  if (/纯黑或纯白/.test(value)) return "纯黑与纯白区域";
  return value ? value.replace(/^请复核/, "").replace(/[，。].*$/, "") : "颜色与层次自然度";
}

function displayMetric(value) {
  if (value === undefined || value === null || value === "") return "";
  return typeof value === "number" ? String(Number(value.toFixed(2))) : String(value);
}

function ProgressTimeline({ items, currentStageIndex, taskStatus }) {
  return (
    <ol className="hdde-detail-timeline" aria-label="任务处理阶段">
      {items.map(([title, description], index) => {
        const done = taskStatus === "completed" || index < currentStageIndex;
        const failed = ["failed", "blocked"].includes(taskStatus) && index === currentStageIndex;
        const active = !done && !failed && index === currentStageIndex;
        return (
          <li
            key={title}
            className="hdde-detail-stage"
            data-state={done ? "done" : active ? "active" : failed ? "failed" : "pending"}
          >
            <span className="hdde-detail-stage-index" aria-hidden="true">{done ? "✓" : index + 1}</span>
            <span className="hdde-detail-stage-copy">
              <strong>{title}</strong>
              <small>{description}</small>
            </span>
            <span className="hdde-detail-stage-status">
              {done ? "完成" : active ? "进行中" : failed ? "未完成" : "等待"}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export default function TaskDetailPage({
  taskConfig,
  onReprocess,
  reprocessLabel = "返回调整 / 重新处理",
  onConfirmAndDeliver,
  onDeliveryCompleted,
  onContinueProcessing,
  onViewOutputs,
  disableAutoStream = false,
  taskStatusOverride = null,
  progressOverride = null,
  processingStageOverride = "",
}) {
  const taskId = useMemo(() => getTaskId(taskConfig), [taskConfig]);
  const result = taskConfig?.task_result || taskConfig?.compareAssets?.task_result || {};
  const report = taskConfig?.task_report || taskConfig?.compareAssets?.task_report || {};
  const debugQuality = taskConfig?.debug_quality || result?.debug_quality || {};
  const rawMode = taskConfig?.mode
    || taskConfig?.operation_mode
    || taskConfig?.processing_type
    || taskConfig?.feature_key
    || result?.mode
    || result?.operation_mode
    || result?.feature_key
    || "fidelity";
  const isFourK = rawMode === "4k_v1";
  const isReferenceCorrection = rawMode === "REFERENCE_COLOR_CORRECTION" || result?.operation_mode === "REFERENCE_COLOR_CORRECTION";
  const isLevelPick = rawMode === "LEVEL_PICK_COLOR_CORRECTION" || result?.operation_mode === "LEVEL_PICK_COLOR_CORRECTION";
  const isColorCorrection = isReferenceCorrection || isLevelPick || ["AUTO_COLOR_CORRECTION", "color_correction"].includes(rawMode);
  const displayMode = isReferenceCorrection ? "参考图校色" : isLevelPick ? "挑档校色" : modeLabel(rawMode);
  const [referenceDetails, setReferenceDetails] = useState(null);
  useEffect(() => {
    let active = true;
    setReferenceDetails(null);
    if (isReferenceCorrection && taskId) {
      requestDeliveryJson(normalizeUrl(`/api/color-correction/tasks/${encodeURIComponent(taskId)}`))
        .then((payload) => { if (active) setReferenceDetails(payload.data); })
        .catch(() => { if (active) setReferenceDetails(null); });
    }
    return () => { active = false; };
  }, [isReferenceCorrection, taskId]);
  const isLocalRetouch = ["LOCAL_RETOUCH", "local_retouch"].includes(rawMode);
  const resultAction = String(taskConfig?.result_action || result?.result_action || result?.d3_final_action || "").toUpperCase();
  const outputSelected = String(taskConfig?.output_selected || result?.output_selected || "").toUpperCase();
  const acceptOriginal = isColorCorrection && (resultAction === "ACCEPT_ORIGINAL" || outputSelected === "ORIGINAL");
  const reviewRequired = isColorCorrection
    && resultAction === "REVIEW_REQUIRED"
    && outputSelected === "REVIEW_CANDIDATE";
  const persistedReviewStatus = String(
    taskConfig?.result_review_status || result?.result_review_status || "",
  ).toLowerCase();
  const persistedReviewStatusConfirmed = isColorCorrection && persistedReviewStatus === "confirmed";
  // A level-pick Result is confirmed by the user's choice itself but not yet delivered:
  // that confirmation must not count as "already reviewed", or the delivery action would hide.
  const persistedReviewConfirmed = persistedReviewStatusConfirmed && !isLevelPick;
  const persistedDeliveryId = String(taskConfig?.delivery_id || result?.delivery_id || "");
  const persistedDeliveries = Array.isArray(taskConfig?.deliveries)
    ? taskConfig.deliveries
    : Array.isArray(result?.deliveries) ? result.deliveries : [];
  const persistedDelivery = persistedDeliveries.find(
    (item) => String(item?.delivery_id || item?.id || "") === persistedDeliveryId,
  ) || null;
  const persistedDeliveryStatus = String(persistedDelivery?.status || "").toLowerCase();
  const persistedDeliveryCompleted = persistedReviewStatusConfirmed
    && Boolean(persistedDeliveryId)
    && persistedDeliveryStatus === "completed";
  const persistedDeliveryInProgress = persistedReviewStatusConfirmed
    && Boolean(persistedDeliveryId)
    && ["pending", "queued", "running", "processing", "preflight", "delivering"].includes(persistedDeliveryStatus);
  const timelines = isFourK ? fourKTimelines : standardTimelines;
  const initialStatus = taskStatusOverride || taskConfig?.task_status || taskConfig?.status || "processing";
  const initialProgress = initialStatus === "completed"
    ? 100
    : Number(progressOverride ?? taskConfig?.task_progress ?? taskConfig?.progress ?? 0);
  const [taskStatus, setTaskStatus] = useState(initialStatus);
  const [progress, setProgress] = useState(initialProgress);
  const [currentStageIndex, setCurrentStageIndex] = useState(
    initialStatus === "completed"
      ? timelines.length
      : Math.min(timelines.length - 1, Math.floor((initialProgress / 100) * timelines.length)),
  );
  const [deliveryPhase, setDeliveryPhase] = useState("idle");
  const [deliveryRun, setDeliveryRun] = useState(null);
  const [deliveryError, setDeliveryError] = useState("");
  const [deliveryNotice, setDeliveryNotice] = useState("");
  const [sessionReviewConfirmed, setSessionReviewConfirmed] = useState(false);
  const protectionBlocked = isColorCorrection && (
    (taskConfig?.d3_status || result?.d3_status) === "PROTECTION_BLOCKED"
      || (taskConfig?.output_selected || result?.output_selected) === "NONE"
  );
  const visibleTaskStatus = protectionBlocked ? "failed" : taskStatus;
  const delivery = resolveDeliveryStatus(debugQuality, result, report, taskConfig || {});
  const outputPath = result?.output_path
    || taskConfig?.output_path
    || result?.final_output_path
    || taskConfig?.final_output_path
    || "";
  const compareAssets = taskConfig?.compareAssets || {};
  const outputUrl = normalizeUrl(
    compareAssets.resultUrl
      || compareAssets.final_output_url
      || taskConfig?.final_output_url
      || result?.final_output_url
      || compareAssets.preview_output_url
      || taskConfig?.preview_output_url
      || result?.preview_output_url
      || taskConfig?.enhancedUrl,
  );
  const originalUrl = normalizeUrl(
    compareAssets.originalUrl
      || compareAssets.original_url
      || taskConfig?.originalUrl
      || taskConfig?.original_url
      || taskConfig?.source_preview_url
      || taskConfig?.ui?.source_preview_url
      || result?.originalUrl
      || result?.original_url
      || result?.input_url,
  );
  const compareOutputUrl = outputUrl;
  const [resultAssetCheck, setResultAssetCheck] = useState({
    url: compareOutputUrl,
    status: compareOutputUrl ? "checking" : "unavailable",
  });
  const [resultAssetRetryKey, setResultAssetRetryKey] = useState(0);
  const resultAssetState = resultAssetCheck.url === compareOutputUrl
    ? resultAssetCheck.status
    : compareOutputUrl ? "checking" : "unavailable";
  const outputFileName = result?.output_filename || fileNameFromPath(outputPath);
  const explicitOutputExists = result?.final_output_exists ?? taskConfig?.final_output_exists;
  const outputExists = explicitOutputExists === undefined || explicitOutputExists === null
    ? Boolean(outputUrl || outputPath)
    : explicitOutputExists === true;
  const explicitDeliveryEligible = result?.delivery_eligible ?? taskConfig?.delivery_eligible;
  const colorDeliveryAllowed = !isColorCorrection
    || explicitDeliveryEligible === true
    || reviewRequired
    || explicitDeliveryEligible === undefined
    || explicitDeliveryEligible === null;
  const resultId = taskConfig?.result_id || result?.result_id || "";
  const displayName = getFileDisplayName(
    taskConfig?.fileName
      || taskConfig?.filename
      || taskConfig?.original_filename
      || result?.input_filename
      || fileNameFromPath(taskConfig?.input_path),
    "当前图片",
  );
  const inputWidth = taskConfig?.input_width || result?.input_width;
  const inputHeight = taskConfig?.input_height || result?.input_height;
  const outputWidth = taskConfig?.output_width || result?.output_width || result?.width;
  const outputHeight = taskConfig?.output_height || result?.output_height || result?.height;
  const outputFormat = String(result?.output_format || taskConfig?.output_format || "PNG").toUpperCase();
  const inputSize = formatBytes(taskConfig?.input_size_bytes || result?.input_size_bytes);
  const outputSize = formatBytes(taskConfig?.output_size_bytes || result?.output_size_bytes || result?.output_size);
  const duration = formatDuration(taskConfig?.duration_ms ?? result?.duration_ms)
    || formatDurationBetween(
      taskConfig?.created_at,
      taskConfig?.completed_at || taskConfig?.updated_at,
    );
  const createdAt = formatDate(taskConfig?.created_at);
  const completedAt = formatDate(taskConfig?.completed_at || taskConfig?.updated_at);
  const displayTaskNumber = taskConfig?.display_task_number || result?.display_task_number || "";
  const stageName = processingStageOverride || taskConfig?.processing_stage || taskConfig?.current_stage || "";
  const stageText = stageLabel(stageName, visibleTaskStatus);
  const canConfirmAndDeliver = visibleTaskStatus === "completed"
    && outputExists
    && colorDeliveryAllowed
    && Boolean(resultId)
    && resultAssetState === "available"
    && !persistedReviewConfirmed
    && !persistedDeliveryCompleted
    && !persistedDeliveryInProgress
    && !["preflight", "delivering"].includes(deliveryPhase);
  const statusText = statusLabel(visibleTaskStatus, isFourK);
  const resultConclusion = acceptOriginal
    ? { label: "保留原图", tone: "positive", nextAction: "当前图片无需生成新的校正成品" }
    : isFourK
      ? resultConclusionFromDelivery(resultAssetState === "available" ? "PASS" : "", { improved: false })
      : resultConclusionFromDelivery(resultAssetState === "available" ? delivery.status : "");
  const dimensionChange = inputWidth && inputHeight && outputWidth && outputHeight
    ? `${inputWidth} × ${inputHeight} → ${outputWidth} × ${outputHeight}`
    : outputWidth && outputHeight ? `${outputWidth} × ${outputHeight}` : "未提供";
  const inputRatio = Number(inputWidth) > 0 && Number(inputHeight) > 0 ? Number(inputWidth) / Number(inputHeight) : null;
  const outputRatio = Number(outputWidth) > 0 && Number(outputHeight) > 0 ? Number(outputWidth) / Number(outputHeight) : null;
  const colorImprovements = firstList(result?.improvements);
  const colorReviewPoints = firstList(result?.review_points);
  const ratioProtected = Boolean(
    (inputRatio && outputRatio && Math.abs(inputRatio - outputRatio) <= 0.002)
      || colorImprovements.some((item) => /保留原始尺寸|构图/.test(item)),
  );
  const sourceProtected = Boolean(
    result?.source_hash_unchanged === true
      || report?.source_hash_unchanged === true
      || taskConfig?.source_hash_unchanged === true
      || colorImprovements.some((item) => /原图哈希保持不变|未覆盖或修改原图/.test(item)),
  );
  const reviewItems = isLocalRetouch
    ? [
        { label: "修整区域", value: "边缘衔接与纹理连续性", status: "重点查看", tone: "review" },
        { label: "当前结果", value: result?.working_revision ? `累计 ${result.working_revision} 次修整` : "当前正式修整结果", status: "已登记", tone: "positive" },
        { label: "原图", value: "原件未覆盖，仅生成派生结果", status: sourceProtected ? "已校验" : "已保护", tone: "positive" },
      ]
    : acceptOriginal
    ? [
        { label: "结果", value: "保留原图", status: "已完成", tone: "positive" },
        { label: "成品", value: isReferenceCorrection ? "参考调整未被采用" : "无需生成新的校正成品", status: "未生成", tone: "positive" },
        { label: "保护", value: sourceProtected ? "原图未覆盖" : "原图保持不变", status: sourceProtected ? "已校验" : "已保护", tone: "positive" },
      ]
    : isColorCorrection
    ? [
        { label: "变化", value: compactColorChange(colorImprovements), status: colorImprovements.length ? "已处理" : "待确认", tone: colorImprovements.length ? "positive" : "review" },
        { label: "保护", value: sourceProtected ? "原图未覆盖" : "原图与构图", status: sourceProtected ? "已校验" : "待确认", tone: sourceProtected ? "positive" : "review" },
        { label: "复核", value: compactColorReview(colorReviewPoints), status: "重点查看", tone: "review" },
      ]
    : [
        { label: "细节", value: "文字、边缘与纹理", status: "对比确认", tone: "review" },
        { label: "比例", value: "构图与画面比例", status: ratioProtected ? "比例保持" : "待确认", tone: ratioProtected ? "positive" : "review" },
        { label: "颜色", value: "肤色、Logo 与品牌色", status: "对比确认", tone: "review" },
        { label: "原图", value: "源文件完整性", status: sourceProtected ? "已校验" : "待确认", tone: sourceProtected ? "positive" : "review" },
      ];
  const summaryFacts = [
    ["结果状态", resultConclusion.label],
    ["处理模式", displayMode],
    ["尺寸变化", dimensionChange],
    ["成品格式", outputExists ? outputFormat : "未生成"],
    ["文件体积", outputSize || "未提供"],
  ];
  const technicalMetrics = [
    ["清晰度", report?.clarity_score],
    ["文字清晰度", report?.text_clarity_score],
    ["边缘质量", report?.edge_quality_score],
    ["色彩忠实度", report?.color_fidelity_score],
    ["纹理保持度", report?.texture_score],
    ["交付评分", report?.delivery_score],
  ].map(([label, value]) => [label, displayMetric(value)]).filter(([, value]) => value);
  const strategyFacts = [
    ["算法版本", result?.engine_version || taskConfig?.engine_version || "未提供"],
    ["任务编号", displayTaskNumber || "未提供"],
    ["输出配置", taskConfig?.output_profile || result?.output_profile || "未提供"],
    ["内部策略", isLevelPick ? `用户选定档位：${({ light: "轻", medium: "中", strong: "强" })[result?.selected_level || result?.parameters?.level] || "未提供"}` : result?.parameters?.strategy_id || result?.resize_policy || taskConfig?.resize_policy || "未提供"],
  ];
  const capabilityBoundary = isReferenceCorrection
    ? referenceResultSummary(result, referenceDetails?.ui?.reference_match_status || result?.reference_provenance?.reference_match_status)
    : isFourK
    ? "保持原图比例与构图，长边提升至3840像素：超分重建细节，并以原图保真融合，防止色偏、重绘与过锐光晕。"
    : isLevelPick
      ? "按你选定的档位修正偏色，只调整现有像素，不重绘内容，不改变尺寸与构图。"
    : isColorCorrection
      ? acceptOriginal
        ? "当前图片无需生成新的校正成品；原图保持不变，不进入交付。"
        : "只校正现有像素，不重绘内容，不改变尺寸与构图。"
      : isLocalRetouch
        ? "只对用户标记区域执行修整；正式 Result 与原图、工作版本保持独立。"
        : "技术指标只作辅助，最终以处理前后人工复核为准。";

  useEffect(() => {
    setResultAssetCheck({
      url: compareOutputUrl,
      status: compareOutputUrl ? "checking" : "unavailable",
    });
    setResultAssetRetryKey(0);
  }, [compareOutputUrl]);

  useEffect(() => {
    const nextStatus = taskStatusOverride || taskConfig?.task_status || taskConfig?.status || "processing";
    const nextProgress = nextStatus === "completed"
      ? 100
      : Number(progressOverride ?? taskConfig?.task_progress ?? taskConfig?.progress ?? 0);
    setTaskStatus(nextStatus);
    setProgress(Math.max(0, Math.min(100, nextProgress)));
    setCurrentStageIndex(
      nextStatus === "completed"
        ? timelines.length
        : Math.min(timelines.length - 1, Math.floor((nextProgress / 100) * timelines.length)),
    );
  }, [progressOverride, taskConfig, taskStatusOverride, timelines.length]);

  useEffect(() => {
    if (disableAutoStream || ["completed", "failed", "blocked"].includes(taskStatus) || !taskId) return undefined;
    const endpoint = taskConfig?.streamEndpoint || `/api/v1/tasks/${taskId}/stream`;
    const streamUrl = normalizeUrl(endpoint);
    const eventSource = new EventSource(streamUrl);

    const finish = () => {
      setProgress(100);
      setCurrentStageIndex(timelines.length);
      setTaskStatus("completed");
      eventSource.close();
    };
    eventSource.onmessage = (event) => {
      if (event.data === "[DONE]") finish();
    };
    eventSource.addEventListener("restoration.log", (event) => {
      try {
        if (event.data === "[DONE]") {
          finish();
          return;
        }
        const payload = JSON.parse(event.data);
        const index = Number(payload.index || 0);
        const total = Number(payload.total || EXPECTED_LOG_TOTAL);
        const nextProgress = Number(payload.task_progress ?? (total > 0 ? Math.round((index / total) * 100) : 0));
        setProgress(Math.max(0, Math.min(100, nextProgress)));
        setCurrentStageIndex(Math.min(timelines.length - 1, Math.floor((nextProgress / 100) * timelines.length)));
        if (payload.done === true || nextProgress >= 100 || index >= total) finish();
      } catch {
        setTaskStatus("failed");
        eventSource.close();
      }
    });
    eventSource.onerror = () => {
      eventSource.close();
    };
    return () => eventSource.close();
  }, [disableAutoStream, taskConfig?.streamEndpoint, taskId, taskStatus, timelines.length]);

  useEffect(() => {
    setDeliveryPhase("idle");
    setDeliveryRun(null);
    setDeliveryError("");
    setDeliveryNotice("");
    setSessionReviewConfirmed(false);
  }, [resultId]);

  const facts = [
    ["处理模式", displayMode],
    ["当前状态", statusText],
    ["输入尺寸", inputWidth && inputHeight ? `${inputWidth} × ${inputHeight}` : ""],
    ["输出尺寸", outputWidth && outputHeight ? `${outputWidth} × ${outputHeight}` : ""],
    ["输出格式", outputExists ? outputFormat : ""],
    ["文件体积", inputSize || outputSize ? `${inputSize || "未知"} → ${outputSize || "未知"}` : ""],
    ["处理用时", duration],
    ["创建时间", createdAt],
    ["完成时间", completedAt],
    ["当前阶段", stageText],
  ].filter(([, value]) => Boolean(value));

  const handleRetryResultAsset = () => {
    setResultAssetCheck({ url: compareOutputUrl, status: compareOutputUrl ? "checking" : "unavailable" });
    setResultAssetRetryKey((value) => value + 1);
  };

  const handleConfirmAndDeliver = async () => {
    if (!canConfirmAndDeliver) return;
    setDeliveryPhase("preflight");
    setDeliveryError("");
    setDeliveryNotice("");
    try {
      if (isColorCorrection && !isLevelPick && !persistedReviewConfirmed && !sessionReviewConfirmed) {
        await requestDeliveryJson(`/api/color-correction/tasks/${encodeURIComponent(taskId)}/review`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: "confirmed" }),
        });
        setSessionReviewConfirmed(true);
      }
      const preflightPayload = await requestDeliveryJson("/api/smart-delivery/preflight", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ result_ids: [resultId], rules: {} }),
      });
      const preflight = preflightPayload.data;
      if (!preflight?.ready) {
        setDeliveryError(preflight?.issues?.[0]?.message || "当前文件未通过交付安全检查。");
        setDeliveryPhase("failed");
        return;
      }

      setDeliveryPhase("delivering");
      const deliveryPayload = await requestDeliveryJson("/api/smart-delivery/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_id: preflight.plan_id, confirmed: true }),
      });
      const completedDelivery = deliveryPayload.data;
      const failedItem = completedDelivery?.results?.find((item) => item.status !== "completed");
      if (!completedDelivery || completedDelivery.failure_count > 0 || completedDelivery.success_count !== 1) {
        setDeliveryRun(completedDelivery || null);
        setDeliveryError(failedItem?.failure_reason || "交付副本未能成功生成。");
        setDeliveryPhase("failed");
        return;
      }
      setDeliveryRun(completedDelivery);
      setDeliveryPhase("saved");
      onDeliveryCompleted?.(completedDelivery);
    } catch (reason) {
      const refreshed = reason.payload?.detail?.preflight;
      setDeliveryError(refreshed?.issues?.[0]?.message || reason.message || "正式交付失败。");
      setDeliveryPhase("failed");
    }
  };

  const activeDeliveryId = deliveryRun?.delivery_id || persistedDeliveryId;

  const handleOpenDeliveryFolder = async () => {
    if (!activeDeliveryId || deliveryPhase === "opening") return;
    setDeliveryPhase("opening");
    setDeliveryError("");
    setDeliveryNotice("");
    try {
      await requestDeliveryJson(`/api/smart-delivery/runs/${encodeURIComponent(activeDeliveryId)}/open-folder`, { method: "POST" });
      setDeliveryNotice("已打开输出文件夹。");
      setDeliveryPhase("saved");
    } catch (reason) {
      setDeliveryError(reason.message || "打开输出文件夹失败。");
      setDeliveryPhase("saved");
    }
  };

  const localDeliveryCompleted = deliveryRun && ["saved", "opening"].includes(deliveryPhase);
  if (localDeliveryCompleted || persistedDeliveryCompleted) {
    const deliveredItem = deliveryRun?.results?.find((item) => item.status === "completed") || persistedDelivery || {};
    const deliveredFileName = getFileDisplayName(
      deliveredItem.delivery_file_name
        || deliveredItem.final_filename
        || deliveredItem.source_filename
        || deliveredItem.delivery_file
        || deliveredItem.delivery_path
        || outputFileName,
      "交付成品",
    );
    const deliverySpecs = [
      outputWidth && outputHeight ? `${outputWidth} × ${outputHeight}` : "",
      outputFormat,
      formatBytes(deliveredItem.size_bytes),
    ].filter(Boolean).join(" · ");
    return (
      <section className="hdde-detail-page" data-testid="delivery-completion-state">
        <header className="hdde-detail-header">
          <div className="hdde-detail-heading">
            <p className="hdde-eyebrow">正式交付完成</p>
            <h1>成品已保存</h1>
            <p>已生成可独立使用的正式交付副本，源成品保持不变。</p>
          </div>
          <span className="hdde-detail-delivery-badge" data-status="PASS">已保存</span>
        </header>
        <section className="hdde-detail-panel hdde-delivery-completion" aria-labelledby="delivery-completion-title">
          <div className="hdde-delivery-completion__file">
            <span>成品文件名</span>
            <h2 id="delivery-completion-title">{deliveredFileName}</h2>
          </div>
          <dl className="hdde-delivery-completion__facts">
            <div><dt>必要规格</dt><dd>{deliverySpecs || "规格随原成品保持"}</dd></div>
            <div><dt>保存位置</dt><dd>正式输出目录</dd></div>
          </dl>
          {deliveryError ? <div className="hdde-delivery-completion__message" role="alert">{deliveryError}</div> : null}
          {deliveryNotice ? <div className="hdde-delivery-completion__message" role="status">{deliveryNotice}</div> : null}
          <div className="hdde-delivery-completion__actions" aria-label="交付完成操作">
            <button type="button" className="hdde-detail-button hdde-detail-button--primary" disabled={deliveryPhase === "opening"} onClick={handleOpenDeliveryFolder}>
              {deliveryPhase === "opening" ? "正在打开…" : "打开输出文件夹"}
            </button>
            <button type="button" className="hdde-detail-button hdde-detail-button--secondary" onClick={onContinueProcessing}>继续处理</button>
          </div>
          <div className="hdde-delivery-completion__links">
            <button type="button" className="hdde-link-action" onClick={onViewOutputs}>在输出中心查看</button>
          </div>
        </section>
      </section>
    );
  }

  return (
    <section className="hdde-detail-page" data-testid="unified-result-page">
      <header className="hdde-detail-header">
        <div className="hdde-detail-heading">
          <p className="hdde-eyebrow">{visibleTaskStatus === "completed" ? "统一结果" : "任务状态"}</p>
          <h1>{visibleTaskStatus === "completed" ? "处理结果" : statusText}</h1>
          <p title={displayName}>{displayName}</p>
        </div>
        <span className="hdde-detail-delivery-badge" data-status={visibleTaskStatus === "completed" ? delivery.status : undefined}>
          {statusText}
        </span>
      </header>

      {visibleTaskStatus === "completed" ? (
        <div className="hdde-detail-result-flow">
          {isReferenceCorrection ? <section className="hdde-detail-panel hdde-detail-compare-anchor" data-testid="result-compare-anchor" aria-label="参考图校色对照">
            <h2>目标原图 · 参考图 · 校色结果</h2>
            <p>{capabilityBoundary}</p>
            <ReferenceComparison
              key={`${compareOutputUrl}-${resultAssetRetryKey}`}
              target={originalUrl || normalizeUrl(referenceDetails?.ui?.source_preview_url)}
              reference={normalizeUrl(referenceDetails?.ui?.reference_preview_url)}
              candidate={acceptOriginal ? (originalUrl || normalizeUrl(referenceDetails?.ui?.source_preview_url)) : compareOutputUrl}
              originalSelected={acceptOriginal}
              onCandidateLoad={() => setResultAssetCheck({ url: compareOutputUrl, status: "available" })}
              onCandidateError={() => setResultAssetCheck({ url: compareOutputUrl, status: "unavailable" })}
            />
            {!acceptOriginal && resultAssetState === "unavailable" && <p role="alert">处理结果暂时无法读取，无法确认交付。<button type="button" className="hdde-link-action" onClick={handleRetryResultAsset}>重新检测结果</button></p>}
          </section> : acceptOriginal ? null : <section className="hdde-detail-panel hdde-detail-compare-anchor" data-testid="result-compare-anchor" aria-labelledby="result-compare-title">
            <div className="hdde-detail-section-heading">
              <div>
                <p className="hdde-eyebrow">第一步</p>
                <h2 id="result-compare-title">前后对比</h2>
              </div>
              <span className="hdde-detail-section-hint">拖动中线检查原图与成品</span>
            </div>
            <div className="hdde-detail-compare-stage">
              <SliderCompareStage
                key={`${compareOutputUrl}-${resultAssetRetryKey}`}
                originalUrl={originalUrl}
                enhancedUrl={compareOutputUrl}
                fileName={displayName}
                deliveryBadge="处理后"
                onEnhancedAssetLoad={() => setResultAssetCheck({ url: compareOutputUrl, status: "available" })}
                onEnhancedAssetError={() => setResultAssetCheck({ url: compareOutputUrl, status: "unavailable" })}
              />
            </div>
            {resultAssetState === "checking" ? (
              <div className="hdde-delivery-completion__message" role="status">
                <strong>正在验证处理结果…</strong>
                <span>确认成品可以读取后，才能继续交付。</span>
              </div>
            ) : null}
            {resultAssetState === "unavailable" ? (
              <div className="hdde-delivery-completion__message" role="alert">
                <strong>处理结果暂时无法读取，无法确认交付。</strong>
                <span>可以重新检测；如果仍然失败，请返回调整并重新处理。</span>
                <button type="button" className="hdde-link-action" onClick={handleRetryResultAsset}>重新检测结果</button>
              </div>
            ) : null}
          </section>}

          <section className="hdde-detail-panel" data-testid="result-review-focus" aria-labelledby="result-review-title">
            <div className="hdde-detail-section-heading">
              <div>
                <p className="hdde-eyebrow">{acceptOriginal ? "处理结论" : "第二步"}</p>
                <h2 id="result-review-title">{acceptOriginal ? "保留原图" : "复核重点"}</h2>
              </div>
            </div>
            <ul className="hdde-detail-review-list">
              {reviewItems.map((item) => (
                <li key={`${item.label}-${item.value}`} data-tone={item.tone}>
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                  <small>{item.status}</small>
                </li>
              ))}
            </ul>
          </section>

          <section className="hdde-detail-panel" data-testid="result-product-summary" aria-labelledby="result-summary-title">
            <div className="hdde-detail-section-heading">
              <div>
                <p className="hdde-eyebrow">{acceptOriginal ? "结果事实" : "第三步"}</p>
                <h2 id="result-summary-title">{acceptOriginal ? "结果摘要" : "成品摘要"}</h2>
              </div>
            </div>
            <dl className="hdde-detail-summary-grid">
              {summaryFacts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
            </dl>
          </section>

          <HddeTechnicalDetails summary="技术详情" className="hdde-detail-technical" >
            <div className="hdde-detail-technical-grid">
              <section>
                <h3>任务与输出</h3>
                <dl className="hdde-detail-output-list">
                  {facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
                  <div><dt>成品文件</dt><dd>{outputFileName ? getFileDisplayName(outputFileName, "成品文件") : "尚未生成成品"}</dd></div>
                </dl>
              </section>
              <section>
                <h3>技术指标</h3>
                {technicalMetrics.length ? (
                  <dl className="hdde-detail-output-list">
                    {technicalMetrics.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
                  </dl>
                ) : <p className="hdde-detail-description">当前任务未提供技术指标。</p>}
              </section>
              <section>
                <h3>能力边界与策略</h3>
                <p className="hdde-detail-description">{capabilityBoundary}</p>
                <dl className="hdde-detail-output-list">
                  {strategyFacts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
                </dl>
              </section>
              <section>
                <h3>处理过程</h3>
                <ProgressTimeline items={timelines} currentStageIndex={currentStageIndex} taskStatus={visibleTaskStatus} />
              </section>
              {isColorCorrection && (colorImprovements.length || colorReviewPoints.length) ? (
                <section className="hdde-detail-technical-wide">
                  <h3>颜色校正记录</h3>
                  {colorImprovements.length ? <div><strong>变化与保护</strong><ul>{colorImprovements.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}
                  {colorReviewPoints.length ? <div><strong>复核记录</strong><ul>{colorReviewPoints.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}
                </section>
              ) : null}
            </div>
          </HddeTechnicalDetails>

          {deliveryError ? (
            <div className="hdde-delivery-completion__message" role="alert">
              <strong>交付未完成</strong>
              <span>{deliveryError}</span>
            </div>
          ) : null}
          {(["preflight", "delivering"].includes(deliveryPhase) || persistedDeliveryInProgress) ? (
            <div className="hdde-delivery-completion__message" role="status">
              {deliveryPhase === "preflight" ? "正在检查交付条件…" : "正在生成正式交付副本…"}
            </div>
          ) : null}

          <div className="hdde-detail-actions hdde-detail-result-decisions" aria-label="处理结果决策" data-testid="result-action-bar">
            <span className="hdde-detail-result-status">
              {acceptOriginal ? "无需交付" : isLevelPick && !persistedDeliveryCompleted ? "已选定档位，待交付" : persistedReviewStatusConfirmed ? "结果已确认" : "结果待确认"}
            </span>
            <div className="hdde-detail-result-action-buttons">
              <button type="button" className="hdde-detail-button hdde-detail-button--secondary" onClick={onReprocess}>
                {reprocessLabel}
              </button>
              {colorDeliveryAllowed && !acceptOriginal && !persistedReviewConfirmed && !persistedDeliveryCompleted ? <button
                type="button"
                className="hdde-detail-button hdde-detail-button--primary"
                disabled={!canConfirmAndDeliver}
                onClick={handleConfirmAndDeliver}
              >
                {deliveryPhase === "preflight" ? "正在检查…" : deliveryPhase === "delivering" ? "正在交付…" : deliveryPhase === "failed" ? "重试交付" : isLevelPick ? "交付所选结果" : "确认结果并交付"}
              </button> : null}
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="hdde-detail-overview" aria-label="任务概览">
            {facts.slice(0, 4).map(([label, value]) => (
              <article key={label}>
                <span>{label}</span>
                <strong data-tone={label === "当前状态" ? (visibleTaskStatus === "failed" ? "negative" : "info") : undefined}>{value}</strong>
              </article>
            ))}
          </div>
          {protectionBlocked ? (
            <div className="hdde-delivery-completion__message" role="alert">
              <strong>本次未进行自动校正</strong>
              <span>检测到自动调整可能影响原图质量，已保留原图。</span>
            </div>
          ) : null}
          <div className="hdde-detail-grid">
            <article className="hdde-detail-panel hdde-detail-progress-panel">
              <div className="hdde-detail-section-heading">
                <div>
                  <p className="hdde-eyebrow">处理进度</p>
                  <h2>{statusText}</h2>
                </div>
                <strong>{protectionBlocked ? "已阻断" : `${progress}%`}</strong>
              </div>
              {protectionBlocked ? null : (
                <div className="hdde-detail-progress" aria-label={`处理进度 ${progress}%`}><span style={{ width: `${progress}%` }} /></div>
              )}
              <ProgressTimeline items={timelines} currentStageIndex={currentStageIndex} taskStatus={visibleTaskStatus} />
            </article>
          </div>
        </>
      )}
    </section>
  );
}
