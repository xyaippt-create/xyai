import React, { useEffect, useMemo, useState } from "react";
import { resolveDeliveryStatus } from "./deliveryStatus.js";
import { getFileDisplayName } from "./fileDisplayName.js";
import UnifiedFeedback from "./UnifiedFeedback.jsx";

const API_BASE = "http://localhost:8787";
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
  ["尺寸适配", "保持比例，高质量适配至4K长边。"],
  ["写入成品", "将PNG成品写入正式4K输出目录。"],
  ["核对结果", "检查文件可读取、尺寸正确且原图未改变。"],
];

function normalizeUrl(value) {
  if (!value) return "";
  if (/^https?:\/\//i.test(value)) return value;
  if (/^[a-zA-Z]:[\\/]/.test(value) || /^\\\\/.test(value)) return "";
  return `${API_BASE}${value.startsWith("/") ? value : `/${value}`}`;
}

function getTaskId(taskConfig) {
  return taskConfig?.taskId
    || taskConfig?.task_id
    || taskConfig?.compareAssets?.taskId
    || taskConfig?.compareAssets?.task_id
    || "";
}

function modeLabel(mode) {
  if (["fidelity", "texture", "text_safe", "standard"].includes(mode)) return "1080P标准增强";
  if (mode === "safe_1080p_beta") return "1080P安全增强";
  if (mode === "4k_v1") return "4K高清画质增强";
  return mode || "未选择";
}

function statusLabel(status, isFourK) {
  if (status === "completed") return isFourK ? "4K适配已完成" : "处理已完成";
  if (status === "failed" || status === "blocked") return "处理未完成";
  if (status === "queued" || status === "pending") return "等待处理";
  return isFourK ? "正在进行4K适配" : "正在处理";
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
  onBackToDashboard,
  onViewCompare,
  onViewReport,
  onReprocess,
  disableAutoStream = false,
  taskStatusOverride = null,
  progressOverride = null,
  processingStageOverride = "",
}) {
  const taskId = useMemo(() => getTaskId(taskConfig), [taskConfig]);
  const result = taskConfig?.task_result || taskConfig?.compareAssets?.task_result || {};
  const report = taskConfig?.task_report || taskConfig?.compareAssets?.task_report || {};
  const debugQuality = taskConfig?.debug_quality || result?.debug_quality || {};
  const rawMode = taskConfig?.mode || result?.mode || "fidelity";
  const isFourK = rawMode === "4k_v1";
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
  const [operation, setOperation] = useState({ status: "", message: "" });

  const delivery = resolveDeliveryStatus(debugQuality, result, report, taskConfig || {});
  const outputPath = result?.output_path
    || taskConfig?.output_path
    || result?.final_output_path
    || taskConfig?.final_output_path
    || "";
  const outputUrl = normalizeUrl(
    result?.preview_output_url
      || taskConfig?.preview_output_url
      || result?.final_output_url
      || taskConfig?.final_output_url
      || taskConfig?.enhancedUrl,
  );
  const outputFileName = result?.output_filename || fileNameFromPath(outputPath);
  const outputDirectory = taskConfig?.output_directory
    || result?.output_dir
    || String(outputPath).replace(/[\\/][^\\/]+$/, "");
  const outputExists = Boolean(
    result?.final_output_exists
      ?? taskConfig?.final_output_exists
      ?? outputUrl
      ?? outputPath,
  );
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
  const stageName = processingStageOverride || taskConfig?.processing_stage || taskConfig?.current_stage || "";
  const stageText = stageLabel(stageName, taskStatus);
  const canCompare = taskStatus === "completed" && outputExists && Boolean(outputUrl);
  const canViewReport = Object.keys(report || {}).length > 0;
  const statusText = statusLabel(taskStatus, isFourK);

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

  const openOutputFolder = async () => {
    if (!outputDirectory) return;
    setOperation({ status: "loading", message: "正在打开输出文件夹…" });
    try {
      const response = await fetch(`${API_BASE}/api/output/open`, {
        method: "POST",
        headers: { "Content-Type": "application/json;charset=UTF-8" },
        body: JSON.stringify({ output_dir: outputDirectory }),
      });
      const payload = await response.json();
      if (!response.ok || payload?.success === false) throw new Error(payload?.message || "无法打开输出文件夹。");
      setOperation({ status: "success", message: payload?.message || "已打开输出文件夹。" });
    } catch (error) {
      setOperation({ status: "error", message: error.message || "无法打开输出文件夹。" });
    }
  };

  const facts = [
    ["处理模式", modeLabel(rawMode)],
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

  return (
    <section className="hdde-detail-page" data-testid="task-detail-page">
      <header className="hdde-detail-header">
        <div className="hdde-detail-heading">
          <p className="hdde-eyebrow">任务详情</p>
          <h1>{statusText}</h1>
          <p title={displayName}>{displayName}</p>
        </div>
        <div className="hdde-detail-actions">
          <button type="button" onClick={onBackToDashboard} className="hdde-detail-button hdde-detail-button--secondary">
            返回处理中心
          </button>
          <button
            type="button"
            disabled={!canCompare}
            onClick={onViewCompare}
            className="hdde-detail-button hdde-detail-button--primary"
          >
            查看前后对比
          </button>
        </div>
      </header>

      <div className="hdde-detail-overview" aria-label="任务概览">
        {facts.slice(0, 4).map(([label, value]) => (
          <article key={label}>
            <span>{label}</span>
            <strong data-tone={label === "当前状态" ? (taskStatus === "completed" ? "positive" : taskStatus === "failed" ? "negative" : "info") : undefined}>
              {value}
            </strong>
          </article>
        ))}
      </div>

      <div className="hdde-detail-grid">
        <article className="hdde-detail-panel hdde-detail-progress-panel">
          <div className="hdde-detail-section-heading">
            <div>
              <p className="hdde-eyebrow">处理进度</p>
              <h2>{taskStatus === "completed" ? "全部步骤已完成" : statusText}</h2>
            </div>
            <strong>{taskStatus === "completed" ? 100 : progress}%</strong>
          </div>
          <div className="hdde-detail-progress" aria-label={`处理进度 ${taskStatus === "completed" ? 100 : progress}%`}>
            <span style={{ width: `${taskStatus === "completed" ? 100 : progress}%` }} />
          </div>
          <ProgressTimeline items={timelines} currentStageIndex={currentStageIndex} taskStatus={taskStatus} />
        </article>

        <aside className="hdde-detail-side">
          <article className="hdde-detail-panel">
            <div className="hdde-detail-section-heading">
              <div>
                <p className="hdde-eyebrow">结果概览</p>
                <h2>{isFourK ? (outputExists ? "4K成品已生成" : statusText) : delivery.label}</h2>
              </div>
              <span className="hdde-detail-delivery-badge" data-status={delivery.status}>
                {outputExists ? "结果可用" : "等待结果"}
              </span>
            </div>
            <p className="hdde-detail-description">
              {isFourK
                ? "已按4K尺寸适配合同处理；该能力不代表真实细节重建或超分辨率增强。"
                : delivery.description}
            </p>
            <dl className="hdde-detail-output-list">
              {facts.slice(4).map(([label, value]) => (
                <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
              ))}
              <div>
                <dt>输出位置</dt>
                <dd>{outputFileName ? `正式输出目录 / ${getFileDisplayName(outputFileName, "成品文件")}` : "尚未生成成品"}</dd>
              </div>
            </dl>
          </article>

          <article className="hdde-detail-panel hdde-detail-result-actions">
            <p className="hdde-eyebrow">任务操作</p>
            <div className="hdde-detail-result-action-grid">
              <button type="button" disabled={!outputUrl} onClick={() => window.open(outputUrl, "_blank", "noopener,noreferrer")}>打开成品</button>
              <button type="button" disabled={!outputDirectory} onClick={openOutputFolder}>打开输出文件夹</button>
              <button type="button" disabled={!canCompare} onClick={onViewCompare}>查看前后对比</button>
              <button type="button" disabled={!canViewReport} onClick={onViewReport}>查看处理报告</button>
              <button type="button" onClick={onReprocess}>重新处理</button>
              <UnifiedFeedback
                taskId={taskId}
                sourceFeature="processing_center"
                stage={stageText}
                triggerLabel="反馈问题"
                testId="task-feedback-trigger"
              />
            </div>
            {operation.message ? <p className="hdde-detail-operation-message" data-tone={operation.status}>{operation.message}</p> : null}
          </article>
        </aside>
      </div>
    </section>
  );
}
