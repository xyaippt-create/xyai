import React, { useEffect, useMemo, useRef, useState } from "react";
import CompressionPreview from "./CompressionPreview.jsx";
import BatchCompressionPanel from "./BatchCompressionPanel.jsx";
import { compressionBatch } from "./batchCompression.js";
import HddeIcon from "./HddeIcon.jsx";
import { HddePageHeader, HddeResultHero, HddeStatusPill, HddeTechnicalDetails } from "./HddeUI.jsx";
import {
  TARGET_FORMAT_OPTIONS,
  buildCompressionRequestPlan,
  convertUploadSizeUnit,
  linkUploadLimitsToSourceRatio,
  targetFormatHelper,
} from "./compressionParams.js";
import {
  FILE_SELECTION_STATES,
  TOKEN_SESSION_ERROR_MESSAGE,
  applyOutputSelection,
  buildCompressionRunPayload,
  captureFileFromChangeEvent,
  effectiveOutputRoot,
  functionOutputDirectory,
  intakeSuccessPatch,
  isTokenSessionError,
  newFileSessionPatch,
  normalizeOutputSettings,
  performFileIntake,
  resetImageSessionPatch,
  restoreBuiltInOutput,
  serverSessionChanged,
} from "./compressionSession.js";
import { apiErrorMessage, codeLabel, statusLabel } from "./compressionStatus.js";
import { buildCompressionAdvice } from "./compressionAdvice.js";
import {
  PREVIEW_MODES,
  comparisonMode,
  defaultPreviewMode,
  defaultUploadLimits,
  isLongImage,
  longImageFeedbackFields,
  longImageReviewChecklist,
  noCandidateUiState,
} from "./longImagePolicy.js";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const MODES = [
  { value: "DELIVERY_OPTIMIZATION", label: "交付方案", help: "按目标格式策略选择质量达标且体积更小的单一交付结果。" },
  { value: "LOSSLESS_COMPRESSION", label: "PNG 无损压缩", help: "仅在严格无损且体积变小时生成候选。" },
  { value: "RESIZE_REDUCTION", label: "尺寸缩小", help: "默认固定短边，长边按原比例自动计算，不裁切、不拉伸、不放大。" },
  { value: "UPLOAD_ADAPTATION", label: "上传适配", help: "按尺寸或体积上限生成安全候选，不执行在线上传。" },
];

function formatBytes(value) {
  const size = Number(value);
  if (!Number.isFinite(size) || size < 0) return "—";
  if (size < 1024) return `${Math.round(size)} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(2)} MB`;
}

function formatDimensions(value) {
  return value?.width && value?.height ? `${value.width} × ${value.height}` : "—";
}

function formatImageFormat(value) {
  return String(value || "").toUpperCase() === "JPEG" ? "JPG" : String(value || "—").toUpperCase();
}

function apiUrl(path) {
  return path ? `${API_BASE}${path}` : "";
}

async function requestJson(path, options = {}) {
  const response = await fetch(apiUrl(path), options);
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok || payload?.success === false) {
    const detail = payload?.detail;
    const reason = new Error(apiErrorMessage(payload, response.status));
    reason.code = typeof detail === "object" ? detail?.code : payload?.code;
    reason.httpStatus = response.status;
    reason.payload = payload;
    throw reason;
  }
  return payload;
}

function Metric({ label, value, title }) {
  return (
    <div className="hdde-compression-metric" title={title || String(value || "")}>
      <span>{label}</span>
      <strong>{value ?? "—"}</strong>
    </div>
  );
}

function CodeList({ title, values }) {
  if (!values?.length) return null;
  return (
    <div className="hdde-compression-code-list">
      <strong>{title}</strong>
      <ul>{values.map((value) => <li key={value}>{codeLabel(value)}</li>)}</ul>
    </div>
  );
}

export default function CompressionPage({ initialSourceFile = null, initialSourceRequestId = "", continueResultId = "", onInitialSourceConsumed, onNavigate, onTaskContextChange }) {
  const [batchMode, setBatchMode] = useState(() => !continueResultId && !initialSourceFile && Boolean(compressionBatch.getSnapshot().batchId || compressionBatch.getSnapshot().items.length));
  const inputRef = useRef(null);
  const controlPanelRef = useRef(null);
  const targetFormatRef = useRef(null);
  const serverSessionRef = useRef(null);
  const consumedSourceRequestRef = useRef("");
  const handledContinueResultRef = useRef("");
  const continueIntakeRef = useRef({ resultId: "", promise: null });
  const [capabilities, setCapabilities] = useState(null);
  const [mode, setMode] = useState(MODES[0].value);
  const [targetFormat, setTargetFormat] = useState("SMART_COMPRESSION");
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileInfo, setFileInfo] = useState(null);
  const [resultData, setResultData] = useState(null);
  const [state, setState] = useState("IDLE");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [resizeStrategy, setResizeStrategy] = useState("short_side");
  const [shortSidePreset, setShortSidePreset] = useState("1080");
  const [customShortSide, setCustomShortSide] = useState("");
  const [ratioPreset, setRatioPreset] = useState("0.75");
  const [customRatio, setCustomRatio] = useState("65");
  const [customDimension, setCustomDimension] = useState("");
  const [uploadLimits, setUploadLimits] = useState({ maxWidth: "1920", maxHeight: "1080", maxSize: "2", sizeUnit: "MB" });
  const [uploadAspectLocked, setUploadAspectLocked] = useState(false);
  const [reviewNote, setReviewNote] = useState("");
  const [showReviewNote, setShowReviewNote] = useState(false);
  const [previewMode, setPreviewMode] = useState(PREVIEW_MODES.OVERVIEW);
  const [longPreviewTarget, setLongPreviewTarget] = useState("source");
  const [sourcePreviewScrollRatio, setSourcePreviewScrollRatio] = useState(0);
  const [longScrollRatio, setLongScrollRatio] = useState(0);
  const [longImageRiskConfirmed, setLongImageRiskConfirmed] = useState(false);
  const [outputSettings, setOutputSettings] = useState(null);
  const [currentTaskOutputRoot, setCurrentTaskOutputRoot] = useState("");
  const [outputSelectionScope, setOutputSelectionScope] = useState("current_task");

  useEffect(() => {
    requestJson("/api/image-compression/capabilities")
      .then((payload) => {
        setCapabilities(payload.data || null);
        serverSessionRef.current = payload.data?.server_session_id || null;
      })
      .catch(() => setCapabilities(null));
    requestJson("/api/image-compression/output-settings")
      .then((payload) => setOutputSettings(normalizeOutputSettings(payload.data)))
      .catch(() => setOutputSettings(null));
  }, []);

  useEffect(() => {
    onTaskContextChange?.(null);
  }, [onTaskContextChange]);

  useEffect(() => {
    setUploadLimits(defaultUploadLimits(fileInfo));
    setUploadAspectLocked(false);
    setPreviewMode(defaultPreviewMode(fileInfo));
    setLongPreviewTarget("source");
    setSourcePreviewScrollRatio(0);
    setLongScrollRatio(0);
    setLongImageRiskConfirmed(false);
    setResizeStrategy("short_side");
    setShortSidePreset("1080");
    setCustomShortSide("");
    setRatioPreset("0.75");
    setCustomRatio("65");
    setCustomDimension("");
  }, [fileInfo]);

  const result = resultData?.result || null;
  const ui = resultData?.ui || null;
  const deliveryWinner = result?.winner || null;
  const hasDeliveryWinner = Boolean(deliveryWinner);
  const hasDeliveryOptions = Boolean(deliveryWinner && !deliveryWinner.source_selected);
  const selectedMode = MODES.find((item) => item.value === mode) || MODES[0];
  const sourcePreview = apiUrl(ui?.source_preview_url || fileInfo?.safe_preview_url);
  const outputPreview = apiUrl(ui?.output_preview_url);
  const activeOutputRoot = effectiveOutputRoot(outputSettings, currentTaskOutputRoot);
  const activeFunctionDirectory = functionOutputDirectory(activeOutputRoot, mode);
  const longImage = isLongImage(fileInfo?.width, fileInfo?.height);
  const compareMode = comparisonMode(fileInfo);
  const candidateState = noCandidateUiState(result);
  const compressionDeliveryReady = candidateState.candidateDeliveryReady;
  const compressionDeliveryBlocked = Boolean(result?.failure_code) || result?.delivery_gate_status === "CANNOT_MEET_SAFELY";
  const resultHeadline = result?.failure_code === "JPEG_COEFFICIENT_LOSSLESS_NOT_IMPLEMENTED"
    ? "当前模式不支持此图片"
    : candidateState.sourceNoProcessing
      ? "原图已满足要求"
      : statusLabel("delivery", result?.delivery_gate_status);
  const compressionConclusion = !result
    ? { label: "待确认", tone: "neutral", next: "等待处理完成" }
    : compressionDeliveryBlocked
      ? { label: "不可使用", tone: "danger", next: "查看失败原因并调整设置" }
      : result.visual_review_status === "PENDING" || result.delivery_gate_status === "REVIEW_REQUIRED"
        ? { label: "建议复核", tone: "warning", next: "比较原图与候选结果，再提交人工结论" }
        : candidateState.sourceNoProcessing
          ? { label: "无需处理", tone: "neutral", next: "继续使用原图，或调整参数后重新处理" }
          : compressionDeliveryReady
            ? { label: "已确认", tone: "positive", next: "打开输出目录使用已确认结果" }
            : { label: "正常", tone: "positive", next: "无需生成候选，原图保持不变" };
  const outputFacts = result?.output_created ? {
    dimensions: result.output_dimensions,
    size: result.output_size_bytes,
  } : {
    dimensions: result?.source_dimensions,
    size: result?.source_size_bytes,
  };
  const resultReduction = Number(result?.size_reduction_ratio);
  const resultChangeSummary = result
    ? `${formatImageFormat(result.source_format)} → ${formatImageFormat(result.output_format)} · ${formatBytes(result.source_size_bytes)} → ${formatBytes(outputFacts.size)}${Number.isFinite(resultReduction) ? ` · ${resultReduction >= 0 ? "减少" : "增加"} ${Math.abs(resultReduction * 100).toFixed(1)}%` : ""}`
    : "";
  const resultAdvice = useMemo(() => buildCompressionAdvice({
    result,
    winner: deliveryWinner,
    operationMode: mode,
    targetFormat,
  }), [deliveryWinner, mode, result, targetFormat]);

  const requestPlan = useMemo(() => buildCompressionRequestPlan({
    fileInfo,
    mode,
    targetFormat,
    resizeStrategy,
    shortSidePreset,
    customShortSide,
    ratioPreset,
    customRatio,
    customDimension,
    uploadLimits,
    longImageRiskConfirmed,
  }), [customDimension, customRatio, customShortSide, fileInfo, longImageRiskConfirmed, mode, targetFormat, ratioPreset, resizeStrategy, shortSidePreset, uploadLimits]);
  const longFeedback = longImageFeedbackFields(fileInfo, requestPlan);
  const updateUploadDimension = (changedField, rawValue) => {
    setUploadLimits((current) => (
      uploadAspectLocked
        ? linkUploadLimitsToSourceRatio(fileInfo, current, changedField, rawValue)
        : { ...current, [changedField]: rawValue }
    ));
    setLongImageRiskConfirmed(false);
  };

  const toggleUploadAspectLock = () => {
    const nextLocked = !uploadAspectLocked;
    setUploadAspectLocked(nextLocked);
    if (nextLocked) {
      setUploadLimits((current) => {
        const anchorField = current.maxWidth ? "maxWidth" : "maxHeight";
        return linkUploadLimitsToSourceRatio(fileInfo, current, anchorField, current[anchorField]);
      });
    }
    setLongImageRiskConfirmed(false);
  };

  const runButtonLabel = {
    DELIVERY_OPTIMIZATION: "生成交付方案",
    LOSSLESS_COMPRESSION: "开始无损压缩",
    RESIZE_REDUCTION: "开始缩小",
    UPLOAD_ADAPTATION: "开始上传适配",
  }[mode];

  const applySessionPatch = (patch) => {
    if ("selectedFile" in patch) setSelectedFile(patch.selectedFile);
    if ("fileInfo" in patch) setFileInfo(patch.fileInfo);
    if ("resultData" in patch) setResultData(patch.resultData);
    if ("reviewNote" in patch) setReviewNote(patch.reviewNote);
    if ("showReviewNote" in patch) setShowReviewNote(patch.showReviewNote);
    if ("state" in patch) setState(patch.state);
    if ("error" in patch) setError(patch.error);
  };

  const resetResult = () => {
    setResultData(null);
    onTaskContextChange?.(null);
    setReviewNote("");
    setShowReviewNote(false);
    setLongPreviewTarget("source");
    setLongScrollRatio(0);
    setLongImageRiskConfirmed(false);
    setState(fileInfo ? FILE_SELECTION_STATES.FILE_READY : FILE_SELECTION_STATES.IDLE);
    setError("");
  };

  const resetImageSession = (message = "") => {
    applySessionPatch(resetImageSessionPatch(message));
    onTaskContextChange?.(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  const clearAll = () => resetImageSession();

  const replaceImage = () => {
    resetImageSession();
    inputRef.current?.click();
  };

  const refreshServerSession = async () => {
    const payload = await requestJson("/api/image-compression/capabilities");
    const nextCapabilities = payload.data || null;
    const nextSessionId = nextCapabilities?.server_session_id || null;
    const changed = serverSessionChanged(serverSessionRef.current, nextSessionId);
    serverSessionRef.current = nextSessionId;
    setCapabilities(nextCapabilities);
    if (changed) {
      resetImageSession(TOKEN_SESSION_ERROR_MESSAGE);
      return false;
    }
    return true;
  };

  const intakeFile = async (file) => {
    if (!file) return;
    onTaskContextChange?.(null);
    setBusy(true);
    try {
      await performFileIntake(file, {
        request: requestJson,
        onTransition: (nextState, payload) => {
          if (nextState === FILE_SELECTION_STATES.FILE_SELECTING) {
            applySessionPatch(newFileSessionPatch(file));
          } else if (nextState === FILE_SELECTION_STATES.INTAKE_PENDING) {
            setState(nextState);
          } else if (nextState === FILE_SELECTION_STATES.FILE_READY) {
            applySessionPatch(intakeSuccessPatch(payload.data, payload.selectedFile));
          }
        },
      });
    } catch (reason) {
      applySessionPatch(resetImageSessionPatch(reason.message));
      setError(reason.message);
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  useEffect(() => {
    if (!initialSourceFile || !initialSourceRequestId || consumedSourceRequestRef.current === initialSourceRequestId) return;
    setBatchMode(false);
    consumedSourceRequestRef.current = initialSourceRequestId;
    void intakeFile(initialSourceFile).finally(() => {
      if (typeof onInitialSourceConsumed === "function") onInitialSourceConsumed(initialSourceRequestId);
    });
  }, [initialSourceFile, initialSourceRequestId, onInitialSourceConsumed]);

  useEffect(() => {
    if (!continueResultId || handledContinueResultRef.current === continueResultId) return undefined;
    setBatchMode(false);
    let active = true;
    setBusy(true);
    setError("");
    setState(FILE_SELECTION_STATES.INTAKE_PENDING);
    if (continueIntakeRef.current.resultId !== continueResultId || !continueIntakeRef.current.promise) {
      continueIntakeRef.current = {
        resultId: continueResultId,
        promise: requestJson("/api/image-compression/intake-result", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ result_id: continueResultId }),
        }),
      };
    }
    continueIntakeRef.current.promise
      .then((payload) => {
        if (!active) return;
        const data = payload.data;
        handledContinueResultRef.current = continueResultId;
        applySessionPatch(intakeSuccessPatch(data, {
          name: data.display_name,
          size: data.size_bytes,
          type: data.format === "PNG" ? "image/png" : data.format === "WEBP" ? "image/webp" : "image/jpeg",
          lastModified: 0,
        }));
      })
      .catch((reason) => {
        if (!active) return;
        applySessionPatch(resetImageSessionPatch(reason.message));
        setError(reason.message);
      })
      .finally(() => active && setBusy(false));
    return () => { active = false; };
  }, [continueResultId]);

  const handleFileChange = (event) => {
    const file = captureFileFromChangeEvent(event);
    if (file) void intakeFile(file);
  };

  const runCompression = async () => {
    if (!fileInfo?.source_token) {
      setError("请先选择 PNG、JPG、JPEG 或 WebP 图片。");
      return;
    }
    if (!requestPlan.valid) return;
    setBusy(true);
    setError("");
    setResultData(null);
    setState("RUNNING");
    try {
      if (!await refreshServerSession()) return;
      const payload = await requestJson("/api/image-compression/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildCompressionRunPayload({
          sourceToken: fileInfo.source_token,
          operationMode: mode,
          params: requestPlan.params,
          currentTaskOutputRoot,
          longImageRiskConfirmed,
        })),
      });
      setResultData(payload.data);
      const task = payload.data?.task || {};
      const completedResult = payload.data?.result || {};
      const taskId = task.task_id || completedResult.task_id || "";
      if (taskId) {
        onTaskContextChange?.({
          taskId,
          mode: "image_compression",
          taskConfig: { ...task, feature_key: "image_compression" },
          taskResult: {
            feature_key: "image_compression",
            module_id: task.module_id || "hdde.image.compression",
            operation_id: task.operation_id || "",
            trace_id: task.trace_id || "",
            task_id: taskId,
            result_id: task.result_id || "",
            output_path: task.output_path || "",
          },
        });
      }
      setState(payload.data?.result?.visual_review_status === "PENDING" ? "REVIEW" : "DONE");
    } catch (reason) {
      if (isTokenSessionError(reason)) {
        resetImageSession(TOKEN_SESSION_ERROR_MESSAGE);
      } else {
        setState("ERROR");
        setError(reason.message);
      }
    } finally {
      setBusy(false);
    }
  };

  const selectOutputFolder = async () => {
    setBusy(true);
    setError("");
    try {
      const selected = await requestJson("/api/output/select-popup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ persist_last_output_dir: false }),
      });
      if (selected.status === "cancelled" || !selected.output_dir) return;
      let path = selected.output_dir;
      if (outputSelectionScope === "saved_default") {
        const saved = await requestJson("/api/image-compression/output-settings/default", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ output_root: path }),
        });
        path = saved.data.saved_default_root;
      }
      const applied = applyOutputSelection(outputSettings, currentTaskOutputRoot, path, outputSelectionScope);
      setOutputSettings(applied.settings);
      setCurrentTaskOutputRoot(applied.currentTaskOutputRoot);
      resetResult();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };

  const restoreDefaultOutputRoot = async () => {
    setBusy(true);
    setError("");
    try {
      await requestJson("/api/image-compression/output-settings/restore", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const restored = restoreBuiltInOutput(outputSettings);
      setOutputSettings(restored.settings);
      setCurrentTaskOutputRoot(restored.currentTaskOutputRoot);
      resetResult();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };

  const review = async (decision) => {
    if (!result?.task_id || result.visual_review_status !== "PENDING") return;
    if (decision === "PASS_WITH_NOTES" && !reviewNote.trim()) {
      setShowReviewNote(true);
      setError("通过并备注时，请先填写复核说明。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload = await requestJson("/api/image-compression/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: result.task_id, decision, note: decision === "PASS_WITH_NOTES" ? reviewNote.trim() : "" }),
      });
      setResultData(payload.data);
      const task = payload.data?.task || {};
      const reviewedResult = payload.data?.result || {};
      const taskId = task.task_id || reviewedResult.task_id || "";
      if (taskId) {
        onTaskContextChange?.({
          taskId,
          mode: "image_compression",
          taskConfig: { ...task, feature_key: "image_compression" },
          taskResult: {
            feature_key: "image_compression",
            module_id: task.module_id || "hdde.image.compression",
            operation_id: task.operation_id || "",
            trace_id: task.trace_id || "",
            task_id: taskId,
            result_id: task.result_id || "",
            output_path: task.output_path || "",
          },
        });
      }
      setState("DONE");
      setShowReviewNote(false);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };

  const continueToDelivery = () => {
    if (!resultData?.task?.result_id || !result?.delivery_eligible) return;
    onNavigate?.(`/smart-delivery?results=${encodeURIComponent(resultData.task.result_id)}`);
  };

  const prepareSuggestedFormat = (nextTargetFormat) => {
    setMode("DELIVERY_OPTIMIZATION");
    setTargetFormat(nextTargetFormat);
    resetResult();
    window.requestAnimationFrame(() => {
      controlPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      targetFormatRef.current?.focus({ preventScroll: true });
    });
  };

  const openOutputFolder = async () => {
    if (!activeOutputRoot) return;
    setBusy(true);
    setError("");
    try {
      if (result?.task_id && ui?.can_open_folder) {
        await requestJson("/api/image-compression/open-output-folder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ task_id: result.task_id }),
        });
      } else {
        await requestJson("/api/image-compression/open-function-folder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            operation_mode: mode,
            ...(currentTaskOutputRoot ? { current_task_output_root: currentTaskOutputRoot } : {}),
          }),
        });
      }
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };

  const constraintRows = mode === "UPLOAD_ADAPTATION" && result ? [
    ["宽度限制", ui?.applied_limits?.max_width, outputFacts.dimensions?.width, "px"],
    ["高度限制", ui?.applied_limits?.max_height, outputFacts.dimensions?.height, "px"],
    ["体积限制", ui?.applied_limits?.max_file_size_bytes, outputFacts.size, "B"],
  ].filter(([, limit]) => limit) : [];

  return (
    <section className="hdde-compression-page hdde-page-frame hdde-page-stack" aria-label="图片交付优化工作台">
      <HddePageHeader
        eyebrow="本地图片处理"
        title={batchMode ? "批量图片压缩" : "图片交付优化"}
        description={batchMode ? "每张图片独立使用智能压缩策略，生成唯一成品或保留原图。" : "从同一原图生成推荐与备选交付方案；保留原有压缩、缩小和上传适配能力。"}
        meta={batchMode ? null : <HddeStatusPill tone={state === "failed" ? "danger" : capabilities ? "positive" : "neutral"}>{statusLabel("state", state)}</HddeStatusPill>}
        actions={<div className="hdde-compression-mode-tabs" aria-label="图片处理数量">
          <button type="button" aria-pressed={!batchMode} disabled={busy} onClick={() => setBatchMode(false)}>单图处理</button>
          <button type="button" data-testid="compression-batch-mode" aria-pressed={batchMode} disabled={busy} onClick={() => setBatchMode(true)}>批量压缩</button>
        </div>}
      />

      {batchMode ? <BatchCompressionPanel onNavigate={onNavigate} /> : null}
      <div className="hdde-page-stack" style={batchMode ? { display: "none" } : undefined}>
      <div className="hdde-compression-workbench">
        <section className="hdde-compression-source-panel" aria-label="图片选择与预览">
          <div
            className={`hdde-compression-dropzone ${fileInfo ? "has-file" : ""}`}
            onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }}
            onDrop={(event) => { event.preventDefault(); intakeFile(event.dataTransfer.files?.[0]); }}
          >
            <input ref={inputRef} id="compression-file-input" data-testid="compression-file-input" type="file" accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" onChange={handleFileChange} disabled={busy} />
            {fileInfo ? (
              <CompressionPreview
                title={fileInfo.source_origin === "EXISTING_RESULT" ? "已有成品预览" : "原图预览"}
                src={sourcePreview}
                mode={previewMode}
                onModeChange={setPreviewMode}
                isLong={longImage}
                scrollRatio={sourcePreviewScrollRatio}
                onScrollRatioChange={setSourcePreviewScrollRatio}
                dimensions={{ width: fileInfo.width, height: fileInfo.height }}
                sizeBytes={fileInfo.size_bytes}
                fileName={fileInfo.display_name}
                actions={(
                  <>
                    <button type="button" className="hdde-secondary-action" onClick={replaceImage} disabled={busy}>更换图片</button>
                    <button type="button" className="hdde-link-action" onClick={clearAll} disabled={busy}>清空</button>
                  </>
                )}
                testId="compression-source-preview"
              />
            ) : selectedFile ? (
              <div className="hdde-compression-pending-source" role="status">
                <strong>{selectedFile.name}</strong>
                <span>{statusLabel("state", state)}</span>
              </div>
            ) : (
              <label htmlFor="compression-file-input" className="hdde-compression-empty-source">
                <strong>拖入图片到这里</strong>
                <span>或</span>
                <b>选择本地图片</b>
                <span>支持 PNG、JPG、JPEG、WebP；最大 50 MB</span>
              </label>
            )}
          </div>
        </section>

        <aside ref={controlPanelRef} className="hdde-compression-control-panel" aria-label="交付优化设置">
          <div><span className="hdde-compression-section-label">处理方式</span><div className="hdde-compression-mode-tabs" role="tablist">
            {MODES.map((item) => {
              const unsupportedLossless = Boolean(fileInfo && fileInfo.format !== "PNG" && item.value === "LOSSLESS_COMPRESSION");
              return (
                <button
                  key={item.value}
                  type="button"
                  role="tab"
                  aria-selected={mode === item.value}
                  aria-disabled={unsupportedLossless}
                  title={unsupportedLossless ? "仅支持PNG" : item.help}
                  data-testid={`compression-mode-${item.value.toLowerCase()}`}
                  className={mode === item.value ? "is-active" : ""}
                  onClick={() => { setMode(item.value); resetResult(); }}
                  disabled={busy || unsupportedLossless}
                >
                  {item.label}{item.value === "LOSSLESS_COMPRESSION" ? <small>仅支持PNG</small> : null}
                </button>
              );
            })}
          </div></div>
          <p className="hdde-compression-mode-help">{selectedMode.help}</p>
          {mode === "DELIVERY_OPTIMIZATION" ? <div className="hdde-compression-settings">
            <label className="hdde-compression-target-field" data-testid="compression-target-format-field"><span>目标格式</span>
              <select ref={targetFormatRef} aria-describedby="compression-target-format-help" data-testid="compression-target-format" value={targetFormat} onChange={(event) => { setTargetFormat(event.target.value); resetResult(); }} disabled={busy}>
                {TARGET_FORMAT_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
              <small id="compression-target-format-help" className="hdde-compression-field-helper" data-testid="compression-target-format-helper">{targetFormatHelper(targetFormat)}</small>
            </label>
          </div> : null}

          {mode === "RESIZE_REDUCTION" ? <div className="hdde-compression-settings" data-testid="compression-resize-settings">
            <label>缩小方式
              <select
                data-testid="compression-resize-strategy"
                value={resizeStrategy}
                onChange={(event) => {
                  setResizeStrategy(event.target.value);
                  setCustomDimension("");
                  setLongImageRiskConfirmed(false);
                }}
                disabled={busy}
              >
                <option value="short_side">按短边</option>
                <option value="ratio">按比例</option>
                <option value="width">指定宽度</option>
                <option value="height">指定高度</option>
              </select>
            </label>
            {resizeStrategy === "short_side" ? <>
              <label>目标短边
                <select data-testid="compression-short-side-preset" value={shortSidePreset} onChange={(event) => { setShortSidePreset(event.target.value); setLongImageRiskConfirmed(false); }} disabled={busy}>
                  <option value="1080">短边 1080</option>
                  <option value="900">短边 900</option>
                  <option value="750">短边 750</option>
                  <option value="custom">自定义短边</option>
                </select>
              </label>
              {shortSidePreset === "custom" ? <label>自定义短边（px）<input data-testid="compression-custom-short-side" type="number" min="1" step="1" value={customShortSide} onChange={(event) => { setCustomShortSide(event.target.value); setLongImageRiskConfirmed(false); }} /></label> : null}
            </> : null}
            {resizeStrategy === "ratio" ? <>
              <label>缩放比例
                <select data-testid="compression-ratio-preset" value={ratioPreset} onChange={(event) => { setRatioPreset(event.target.value); setLongImageRiskConfirmed(false); }} disabled={busy}>
                  <option value="0.75">75%</option>
                  <option value="0.5">50%</option>
                  <option value="custom">自定义比例</option>
                </select>
              </label>
              {ratioPreset === "custom" ? <label>自定义比例（%）<input data-testid="compression-custom-ratio" type="number" min="1" max="99" step="1" value={customRatio} onChange={(event) => { setCustomRatio(event.target.value); setLongImageRiskConfirmed(false); }} /></label> : null}
            </> : null}
            {resizeStrategy === "width" || resizeStrategy === "height" ? <label>目标{resizeStrategy === "width" ? "宽度" : "高度"}（px）<input data-testid="compression-custom-dimension" type="number" min="1" step="1" value={customDimension} onChange={(event) => { setCustomDimension(event.target.value); setLongImageRiskConfirmed(false); }} /></label> : null}
            {longImage && resizeStrategy === "height" ? <p className="hdde-long-image-field-warning">高级风险参数：固定总高度可能显著降低长图短边，请核对实时预估。建议改用“按短边”。</p> : null}
            {fileInfo ? <div className="hdde-resize-estimate" data-testid="compression-resize-estimate">
              <span>原始尺寸：<strong>{fileInfo.width} × {fileInfo.height}</strong></span>
              <span>原始短边：<strong>{Math.min(fileInfo.width, fileInfo.height)}</strong></span>
              <span>目标短边：<strong>{requestPlan.targetShortSide || "—"}</strong></span>
              <span>预计尺寸：<strong>{requestPlan.estimatedOutputWidth || "—"} × {requestPlan.estimatedOutputHeight || "—"}</strong></span>
              <span>预计缩放比例：<strong>{Number.isFinite(requestPlan.calculatedScale) ? `${(requestPlan.calculatedScale * 100).toFixed(2)}%` : "—"}</strong></span>
              <span>保持原始比例：<strong>是</strong></span>
              <span>裁切：<strong>否</strong></span>
              <span>放大：<strong>否</strong></span>
            </div> : null}
          </div> : null}

          {mode === "UPLOAD_ADAPTATION" ? <div className="hdde-compression-settings" data-testid="compression-upload-settings">
            <div className="hdde-upload-dimension-row">
              <label>最大宽度（px）<input data-testid="compression-max-width" type="number" min="1" step="1" value={uploadLimits.maxWidth} onChange={(event) => updateUploadDimension("maxWidth", event.target.value)} /></label>
              <button
                type="button"
                className={`hdde-aspect-ratio-lock${uploadAspectLocked ? " is-locked" : ""}`}
                data-testid="compression-aspect-ratio-lock"
                aria-pressed={uploadAspectLocked}
                title={fileInfo ? `按原图 ${fileInfo.width} × ${fileInfo.height} 的比例联动` : "选择图片后可锁定原图比例"}
                onClick={toggleUploadAspectLock}
                disabled={!fileInfo || busy}
              >
                <HddeIcon name={uploadAspectLocked ? "lock" : "unlock"} size={16} />
                {uploadAspectLocked ? "比例已锁定" : "锁定长宽比"}
              </button>
              <label>最大高度（px）<input data-testid="compression-max-height" type="number" min="1" step="1" value={uploadLimits.maxHeight} placeholder={longImage ? "长图默认不限制" : ""} onChange={(event) => updateUploadDimension("maxHeight", event.target.value)} /></label>
            </div>
            <label>最大文件体积<div className="hdde-compression-size-input"><input data-testid="compression-max-size" type="number" min="0.01" step="0.01" value={uploadLimits.maxSize} onChange={(event) => setUploadLimits((current) => ({ ...current, maxSize: event.target.value }))} /><select aria-label="文件体积单位" value={uploadLimits.sizeUnit} onChange={(event) => setUploadLimits((current) => convertUploadSizeUnit(current, event.target.value))}><option value="KB">KB</option><option value="MB">MB</option></select></div></label>
            {uploadAspectLocked ? <p className="hdde-upload-aspect-ratio-note">已按原图比例联动宽高限制；修改任一数值会自动更新另一项。</p> : null}
            {longImage ? <p className="hdde-long-image-field-warning">已识别为长图。建议优先限制宽度和文件体积，不限制总高度。</p> : null}
          </div> : null}

          {longImage && requestPlan.estimatedOutputWidth ? (
            <div className={`hdde-long-image-preflight is-${String(requestPlan.longImageRiskLevel || "none").toLowerCase()}`} data-testid="compression-long-image-preflight">
              <strong>长图输出预估：{requestPlan.estimatedOutputWidth} × {requestPlan.estimatedOutputHeight}</strong>
              <span>宽度风险：{requestPlan.longImageRiskLevel || "—"} · {requestPlan.riskPolicyVersion}</span>
              {requestPlan.longImageWarnings?.map((warning) => <p key={warning}>{warning}</p>)}
              {requestPlan.requiresLongImageConfirmation ? (
                <label>
                  <input
                    type="checkbox"
                    data-testid="compression-long-image-confirmation"
                    checked={longImageRiskConfirmed}
                    onChange={(event) => setLongImageRiskConfirmed(event.target.checked)}
                  />
                  {requestPlan.confirmationText}
                </label>
              ) : null}
            </div>
          ) : null}

          <div className="hdde-compression-output-location" data-testid="compression-output-location">
            <span className="hdde-compression-section-label">输出位置</span>
            <code title={activeFunctionDirectory}>{activeFunctionDirectory || "正在读取输出目录…"}</code>
            <small>根目录：{activeOutputRoot || "—"} · {currentTaskOutputRoot ? "当前任务临时根目录" : "长期默认根目录"}{outputSettings?.outputRootWritable ? " · 可写" : ""}</small>
            <div className="hdde-compression-output-actions">
              <label htmlFor="compression-output-scope">应用范围</label>
              <select id="compression-output-scope" value={outputSelectionScope} onChange={(event) => setOutputSelectionScope(event.target.value)} disabled={busy || !outputSettings}>
                <option value="current_task">仅当前任务</option>
                <option value="saved_default">保存为长期默认</option>
              </select>
              <button type="button" className="hdde-secondary-action" data-testid="compression-select-output" onClick={selectOutputFolder} disabled={busy || !outputSettings}>选择文件夹</button>
              <button type="button" className="hdde-link-action" data-testid="compression-restore-output" onClick={restoreDefaultOutputRoot} disabled={busy || !outputSettings}>恢复默认</button>
              <button type="button" className="hdde-link-action" data-testid="compression-open-folder" onClick={openOutputFolder} disabled={busy || !activeFunctionDirectory || Boolean(result && (!candidateState.hasCandidate || !compressionDeliveryReady))}>打开输出目录</button>
            </div>
          </div>

          {!error ? <div className={`hdde-compression-safety ${requestPlan.severity === "warning" ? "is-warning" : requestPlan.severity === "danger" ? "is-invalid" : requestPlan.valid ? "is-valid" : fileInfo ? "is-invalid" : "is-neutral"}`} role="status">{requestPlan.message}</div> : null}
          {error ? <div className="hdde-compression-error" role="alert">{error}</div> : null}
          <button type="button" className="hdde-primary-action hdde-compression-run" data-testid="compression-run" onClick={runCompression} disabled={busy || !fileInfo || !requestPlan.valid}>{busy ? "正在执行…" : runButtonLabel}</button>
          <small className="hdde-compression-offline-note">仅在本地执行，不覆盖原图，不自动上传。</small>
        </aside>
      </div>

      <section className={`hdde-compression-results ${result ? "has-result" : "is-empty"}`} aria-live="polite" aria-label="处理结果">
        {result ? <>
          <div className="hdde-compression-results-heading">
            <div><span className="hdde-compression-section-label">处理结果</span><strong>{resultHeadline}</strong></div>
            <div className="hdde-compression-result-actions">
              <button type="button" className="hdde-secondary-action" data-testid="compression-reprocess" onClick={runCompression} disabled={!fileInfo || !requestPlan.valid || busy}>重新处理</button>
              <button type="button" className="hdde-secondary-action" onClick={replaceImage} disabled={busy}>更换图片</button>
              <button type="button" className="hdde-link-action" onClick={clearAll} disabled={busy}>清空</button>
            </div>
          </div>
          <HddeResultHero
            conclusion={compressionConclusion.label}
            tone={compressionConclusion.tone}
            title={resultHeadline}
            summary={result.output_created
              ? compressionDeliveryReady
                ? "结果已确认，可从正式输出目录使用；原图保持不变。"
                : "候选结果已生成，确认前不会开放交付入口；原图保持不变。"
              : candidateState.sourceNoProcessing
                ? "原图已经满足当前要求，未生成重复文件；可以继续使用原图。"
                : "本次没有用原图冒充处理结果。"}
            changes={[resultChangeSummary]}
            protections={["原图未覆盖", ui?.aspect_ratio_preserved === false ? "比例需要复核" : "原图比例已保持"]}
            nextAction={compressionConclusion.next}
          />

          {ui?.smart_compression_summary ? (
            <p className="hdde-compression-smart-note" data-testid="compression-smart-summary">
              {ui.smart_compression_summary}
            </p>
          ) : null}

          {hasDeliveryWinner ? (
            <section className="hdde-delivery-options hdde-single-winner" aria-label="智能择优结果" data-testid="delivery-winner">
              <div className="hdde-delivery-options-heading">
                <div>
                  <span className="hdde-compression-section-label">智能择优结果</span>
                  <strong>{deliveryWinner.source_selected ? "已接近最优" : Number(deliveryWinner.saved_percent) > 0 ? "压缩完成" : "转换完成 · 文件未变小"}</strong>
                </div>
                <span>{deliveryWinner.source_selected ? "未生成新文件 · 保留原图" : "仅登记 1 个正式结果"} · {deliveryWinner.display_name}</span>
              </div>
              <div className="hdde-delivery-option-grid">
                <article className="hdde-delivery-option is-recommended is-selected" data-testid={`delivery-winner-${deliveryWinner.scheme_id}`}>
                  <div className="hdde-delivery-option-title">
                    <div><span>最终结果</span><strong>{deliveryWinner.display_name}</strong></div>
                    <em>{deliveryWinner.source_selected ? "保留原图" : "已择优"}</em>
                  </div>
                  <dl>
                    <div><dt>最终格式</dt><dd>{deliveryWinner.format}</dd></div>
                    <div><dt>最终体积</dt><dd>{formatBytes(deliveryWinner.file_size)}</dd></div>
                    <div><dt>分辨率</dt><dd>{deliveryWinner.width && deliveryWinner.height ? `${deliveryWinner.width} × ${deliveryWinner.height}` : "—"}</dd></div>
                    <div><dt>节省比例</dt><dd>{Number(deliveryWinner.saved_percent || 0).toFixed(2)}%</dd></div>
                  </dl>
                  <div className="hdde-lossless-proof" data-testid="delivery-quality-proof">
                    <strong>质量检查通过</strong>
                    <span>{deliveryWinner.source_selected ? "未发现兼具质量与体积收益的新文件，原图保持不变。" : "胜出文件已通过对应质量门并完成正式文件验证。"}</span>
                  </div>
                  <p><span>选择原因</span>{deliveryWinner.reason}</p>
                  <small>原图 {formatBytes(result.source_size_bytes)} → 最终 {formatBytes(deliveryWinner.file_size)}</small>
                </article>
              </div>
            </section>
          ) : null}

          {resultAdvice ? (
            <aside className="hdde-compression-advice" data-testid="compression-result-advice" aria-label="压缩结果建议">
              <div>
                <span className="hdde-compression-section-label">可选下一步</span>
                <strong>{resultAdvice.title}</strong>
                <p>{resultAdvice.detail}</p>
              </div>
              {resultAdvice.actions.length ? (
                <div className="hdde-compression-advice-actions" role="group" aria-label="选择其他目标格式">
                  {resultAdvice.actions.map((action) => (
                    <button
                      key={action.targetFormat}
                      type="button"
                      className="hdde-link-action"
                      data-testid={`compression-advice-${action.targetFormat.toLowerCase()}`}
                      onClick={() => prepareSuggestedFormat(action.targetFormat)}
                      disabled={busy}
                    >
                      {action.label}
                    </button>
                  ))}
                </div>
              ) : null}
              <small>选择只会更新目标格式，仍需由你点击“生成交付方案”后才会处理。</small>
            </aside>
          ) : null}

          <HddeTechnicalDetails summary="查看压缩与编码详情">
            <div className="hdde-compression-metrics">
              <Metric label="技术状态" value={statusLabel("technical", result.technical_status)} />
              <Metric label="视觉复核" value={statusLabel("visual", result.visual_review_status)} />
              <Metric label="交付结论" value={statusLabel("delivery", result.delivery_gate_status)} />
              <Metric label="体积变化" value={result.size_reduction_ratio == null ? "—" : `${(result.size_reduction_ratio * 100).toFixed(1)}%`} />
              <Metric label="节省字节" value={result.size_reduction_bytes == null ? "—" : formatBytes(result.size_reduction_bytes)} />
              <Metric label="是否有损" value={result.lossy == null ? "—" : result.lossy ? "是" : "否"} />
              <Metric label="是否重编码" value={result.reencoded == null ? "—" : result.reencoded ? "是" : "否"} />
              <Metric label="是否缩小" value={result.resized == null ? "—" : result.resized ? "是" : "否"} />
              <Metric label="处理耗时" value={`${Number(result.processing_seconds || 0).toFixed(3)} 秒`} />
              <Metric label="输出位置" value={ui?.output_directory || "无输出"} />
            </div>
            {constraintRows.length ? <div className="hdde-compression-constraints">{constraintRows.map(([label, limit, actual, unit]) => <span key={label} className={actual <= limit ? "is-met" : "is-unmet"}>{label}：{actual} / {limit} {unit} · {actual <= limit ? "满足" : "未满足"}</span>)}</div> : null}
            {mode === "RESIZE_REDUCTION" && ui?.resize_strategy ? <div className="hdde-resize-result-audit" data-testid="compression-resize-result-audit"><strong>尺寸缩小验证</strong><span>策略：{ui.resize_strategy}</span><span>原图短边：{ui.source_short_side || "—"}</span><span>目标短边：{ui.target_short_side || "—"}</span><span>实际尺寸：{ui.actual_target_width || "—"} × {ui.actual_target_height || "—"}</span><span>保持比例：{ui.aspect_ratio_preserved ? "是" : "待确认"} · 裁切：否 · 补边：否 · 放大：否</span></div> : null}
            {longImage ? <div className="hdde-long-image-result-audit"><strong>长图输出核对</strong><span>预计输出：{ui?.estimated_output_width || longFeedback.estimated_output_width || "—"} × {ui?.estimated_output_height || longFeedback.estimated_output_height || "—"}</span><span>风险级别：{ui?.long_image_risk_level || longFeedback.long_image_risk_level || "—"}</span><span>规则：{ui?.long_image_width_risk_policy_version || longFeedback.long_image_width_risk_policy_version}</span></div> : null}
          </HddeTechnicalDetails>

          {candidateState.hasCandidate && compareMode === "single-toggle" ? (
            <div className="hdde-long-image-compare" data-testid="compression-long-image-compare">
              <div className="hdde-long-image-switch" role="tablist" aria-label="长图原图与处理结果">
                <button type="button" role="tab" aria-selected={longPreviewTarget === "source"} className={longPreviewTarget === "source" ? "is-active" : ""} onClick={() => setLongPreviewTarget("source")}>原图</button>
                <button type="button" role="tab" aria-selected={longPreviewTarget === "output"} className={longPreviewTarget === "output" ? "is-active" : ""} onClick={() => setLongPreviewTarget("output")}>处理结果</button>
              </div>
              <CompressionPreview
                title={longPreviewTarget === "source" ? "原图" : "处理结果"}
                src={longPreviewTarget === "source" ? sourcePreview : outputPreview}
                mode={previewMode}
                onModeChange={setPreviewMode}
                isLong
                scrollRatio={longScrollRatio}
                onScrollRatioChange={setLongScrollRatio}
                dimensions={longPreviewTarget === "source" ? result.source_dimensions : result.output_dimensions}
                sizeBytes={longPreviewTarget === "source" ? result.source_size_bytes : result.output_size_bytes}
                sourceSizeBytes={longPreviewTarget === "output" ? result.source_size_bytes : undefined}
                reductionRatio={longPreviewTarget === "output" ? result.size_reduction_ratio : undefined}
                fileName={longPreviewTarget === "source" ? ui?.source_display_name : ui?.output_display_name}
                testId="compression-long-image-active-preview"
              />
            </div>
          ) : candidateState.hasCandidate ? (
            <div className="hdde-compression-previews">
              <CompressionPreview title="原图" src={sourcePreview} mode={previewMode} onModeChange={setPreviewMode} dimensions={result.source_dimensions} sizeBytes={result.source_size_bytes} fileName={ui?.source_display_name} testId="compression-result-source-preview" />
              <CompressionPreview title="压缩后" src={outputPreview} mode={previewMode} onModeChange={setPreviewMode} dimensions={result.output_dimensions} sizeBytes={result.output_size_bytes} sourceSizeBytes={result.source_size_bytes} reductionRatio={result.size_reduction_ratio} fileName={ui?.output_display_name} testId="compression-output-preview" />
            </div>
          ) : (
            <div className="hdde-no-candidate-state" data-testid="compression-no-candidate-state">
              <CompressionPreview
                title="原图"
                src={sourcePreview}
                mode={previewMode}
                onModeChange={setPreviewMode}
                isLong={longImage}
                scrollRatio={longScrollRatio}
                onScrollRatioChange={setLongScrollRatio}
                dimensions={result.source_dimensions}
                sizeBytes={result.source_size_bytes}
                fileName={ui?.source_display_name}
                testId="compression-no-candidate-source"
              />
              <div>
                <strong>{candidateState.sourceNoProcessing ? "原图已满足要求" : "未生成处理结果"}</strong>
                <span>{candidateState.sourceNoProcessing ? "没有生成新成品；可继续使用原图，或调整参数后重新处理。" : "当前任务没有候选图片，不会复制原图冒充处理结果。"}</span>
              </div>
            </div>
          )}

          <CodeList title="警告" values={result.warnings} />
          <CodeList title="风险原因" values={result.risk_reasons} />
          {result.failure_code || result.failure_reason ? <div className="hdde-compression-code-list is-danger"><strong>未完成原因</strong><p>{codeLabel(result.failure_code)}{result.failure_reason ? `（${result.failure_reason}）` : ""}</p></div> : null}

          {candidateState.showReview ? <div className="hdde-compression-review" data-testid="compression-review-panel">
            <div><strong>{longImage ? "长图人工视觉复核" : "人工视觉复核"}</strong><span>请比较文字、Logo、颜色、结构、边缘和透明区域，再提交结论。</span></div>
            {longImage ? <div className="hdde-long-image-review-checklist"><strong>长图复核提示</strong><span>请在100%模式下重点检查：</span><ul>{longImageReviewChecklist().map((item) => <li key={item}>{item}</li>)}</ul></div> : null}
            <div className="hdde-compression-review-actions">
              <button type="button" className="hdde-primary-action" data-testid="compression-review-pass" onClick={() => review("PASS")} disabled={busy}>确认可用</button>
              <button type="button" className="hdde-secondary-action" data-testid="compression-review-notes" onClick={() => setShowReviewNote(true)} disabled={busy}>有提示但可用</button>
              <button type="button" className="hdde-danger-action" data-testid="compression-review-fail" onClick={() => review("FAIL")} disabled={busy}>结果不可用</button>
            </div>
            {showReviewNote ? <div className="hdde-compression-review-note"><label htmlFor="compression-review-note">复核说明</label><textarea id="compression-review-note" data-testid="compression-review-note" maxLength="500" value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="说明可接受的轻微变化或交付注意事项" /><button type="button" className="hdde-primary-action" data-testid="compression-review-notes-confirm" onClick={() => review("PASS_WITH_NOTES")} disabled={busy || !reviewNote.trim()}>确认通过并备注</button></div> : null}
          </div> : null}

          {candidateState.hasCandidate && !candidateState.showReview ? (
            <div
              className="hdde-compression-delivery-state"
              data-testid="compression-delivery-state"
              data-status={compressionDeliveryReady ? "ready" : "blocked"}
            >
              <div>
                <strong>{compressionDeliveryReady ? "确认完成，可以交付" : "当前结果不可交付"}</strong>
                <span>{compressionDeliveryReady ? "当前选择已写入原有单结果登记，可继续交付或打开正式输出目录。" : "人工复核未通过，请调整设置后重新处理。"}</span>
              </div>
              {compressionDeliveryReady ? <div className="hdde-compression-delivery-actions">
                {hasDeliveryOptions ? <button type="button" className="hdde-primary-action" data-testid="delivery-continue" onClick={continueToDelivery} disabled={busy || typeof onNavigate !== "function"}>继续交付</button> : null}
                <button type="button" className={hasDeliveryOptions ? "hdde-secondary-action" : "hdde-primary-action"} onClick={openOutputFolder} disabled={busy}>{busy ? "正在打开…" : "打开输出目录"}</button>
              </div> : null}
            </div>
          ) : null}

          <details className="hdde-compression-sha"><summary>查看完整SHA与技术标识</summary><div><span>原图 SHA256</span><code>{result.source_sha256 || "—"}</code>{candidateState.hasCandidate ? <><span>候选 SHA256</span><code>{result.output_sha256 || "—"}</code></> : null}</div></details>
        </> : <div className="hdde-compression-empty-result">处理完成后将在这里显示体积、尺寸、预览与交付状态。</div>}
      </section>
      </div>
    </section>
  );
}
