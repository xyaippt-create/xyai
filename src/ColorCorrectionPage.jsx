import React, { useEffect, useRef, useState } from "react";
import { HddePageHeader, HddeResultHero, HddeStatusPill, HddeTechnicalDetails } from "./HddeUI.jsx";
import {
  FILE_SELECTION_STATES,
  effectiveOutputRoot,
  normalizeOutputSettings,
  performFileIntake,
} from "./compressionSession.js";
import HddeIcon from "./HddeIcon.jsx";
import "./ColorCorrectionReference.css";

export function referenceResultSummary(result, status) {
  if (result?.result_action === "ACCEPT_ORIGINAL") return "参考图差异或安全保护导致未采用调整结果，已保留目标原图。";
  if (result?.result_action === "REVIEW_REQUIRED") return "已生成受控参考候选，请按当前复核流程确认；尚未获得自动交付权限。";
  return ({
    FULL_MATCH: "已按参考图完成校色。",
    COLOR_ONLY_MATCH: "已保护原图亮度，仅匹配综合色彩。",
    LIMITED_MATCH: "参考图差异较大，已进行受控色调匹配。",
    INSUFFICIENT_EVIDENCE: "参考图信息不足，已保留安全结果。",
  })[status] || "已完成参考图分析，请查看最终处理结论。";
}

export function ReferenceComparison({ target, reference, candidate, originalSelected = false, onCandidateLoad, onCandidateError }) {
  return <div className="hdde-reference-comparison" data-testid="color-reference-triple">
    <figure><figcaption>目标原图</figcaption><img src={target} alt="目标原图" /></figure>
    <figure className="hdde-reference-comparison-input"><figcaption>参考图</figcaption>{reference ? <img src={reference} alt="只读参考图" /> : <p>参考预览暂不可用</p>}</figure>
    <figure><figcaption>{originalSelected ? "保留的目标原图" : "校色结果"}</figcaption><img src={candidate} alt={originalSelected ? "安全保留的目标原图" : "参考图校色结果"} onLoad={onCandidateLoad} onError={onCandidateError} /></figure>
  </div>;
}

export const LEVEL_PICK_LABELS = { original: "原图", light: "轻", medium: "中", strong: "强" };

export function levelPickSummary(level) {
  const label = LEVEL_PICK_LABELS[level];
  return label && level !== "original"
    ? `已按你选择的“${label}”档修正偏色，只调整现有像素，尺寸与构图不变。`
    : "已选择原图，未生成新文件。";
}

export function LevelPickOptions({ preview, chosen, onChoose, onZoom, disabled = false }) {
  const measurement = preview?.measurement || {};
  return <div className="hdde-level-pick" data-testid="color-level-options">
    <div className="hdde-level-measure" role="status">
      <strong>{measurement.summary || "已完成测量"}</strong>
      <span>系统建议：{measurement.recommended_label || "原图"}{measurement.measured_offset ? ` · 偏色量 ${Number(measurement.measured_offset).toFixed(1)}` : ""}</span>
      {measurement.notice ? <p>{measurement.notice}</p> : null}
    </div>
    <div className="hdde-level-grid" role="radiogroup" aria-label="选择校色档位">
      {(preview?.levels || []).map((item) => {
        const selected = chosen === item.level;
        const recommended = measurement.recommended_level === item.level;
        return <figure key={item.level} className="hdde-level-option" data-selected={selected ? "true" : "false"} data-testid={`color-level-${item.level}`}>
          <button type="button" className="hdde-level-zoom-trigger" onClick={() => onZoom(item)} aria-label={`放大查看${item.label}`}>
            <img src={apiUrl(item.preview_url)} alt={`${item.label}档预览`} />
          </button>
          <figcaption>
            <label>
              <input type="radio" name="color-level" value={item.level} checked={selected} disabled={disabled || !item.selectable} onChange={() => onChoose(item.level)} />
              <span>{item.label}</span>
              {recommended ? <em>建议</em> : null}
            </label>
            {!item.selectable ? <small>未通过安全检查，不可选</small> : null}
          </figcaption>
        </figure>;
      })}
    </div>
  </div>;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const COLOR_PROTECTION_TITLE = "本次未进行自动校正";
const COLOR_PROTECTION_DESCRIPTION = "检测到自动调整可能影响原图质量，已保留原图。";

function isColorProtectionBlocked(task, result) {
  return (task?.d3_status || result?.d3_status) === "PROTECTION_BLOCKED"
    || (task?.output_selected || result?.output_selected) === "NONE";
}

function colorFailureMessage(task, result, fallback = "颜色校正未完成。") {
  if (isColorProtectionBlocked(task, result)) {
    return `${COLOR_PROTECTION_TITLE}。${COLOR_PROTECTION_DESCRIPTION}`;
  }
  return task?.failure_reason || fallback;
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
    const message = typeof detail === "object" ? detail?.message : detail;
    const failure = new Error(message || payload?.message || `本地服务请求失败（${response.status}）。`);
    failure.taskData = payload?.data?.task ? payload.data : null;
    throw failure;
  }
  return payload;
}

function formatBytes(value) {
  const size = Number(value);
  if (!Number.isFinite(size) || size < 0) return "—";
  if (size < 1024) return `${Math.round(size)} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(2)} MB`;
}

function joinOutputDirectory(root) {
  const base = String(root || "").replace(/[\\/]+$/, "");
  if (!base) return "";
  return `${base}${base.includes("\\") ? "\\" : "/"}颜色校正`;
}

function metricNumber(value, digits = 1) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : null;
}

function metricPercent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? (number * 100).toFixed(1) : null;
}

function strategySummary(result) {
  switch (result?.analysis?.strategy_id) {
    case "AUDITORIUM_STRONG_COLOR_DEPTH":
      return "已分别处理会场暗部与强色大屏，恢复层次的同时保留屏幕文字和红色关系。";
    case "MEETING_MIXED_LIGHT_PEOPLE":
      return "已将人物、前景与高亮背景分开处理，优先改善人物，同时保护窗户、屏幕和桌面强色。";
    case "NORMAL_DESIGN_PROTECTION":
      return "原图曝光、色彩和层次基本正常，本次以保护原有设计关系为主。";
    case "BACKLIGHT_DEPTH_RECOVERY":
      return "已针对逆光反差恢复前景层次，并控制高亮背景。";
    case "COLOR_CAST_AND_TONE_BALANCE":
      return "已依据可信中性色修正偏色，并同步整理明暗层次。";
    default:
      return "已根据这张图片的曝光、色彩和层次特征完成针对性校正。";
  }
}

export function postReviewSummary(review) {
  if (!review?.post_review_complete) {
    return "本次处理已完成可执行的安全检查；部分项目因画面条件不足未单独判断，建议查看前后对比。";
  }
  const candidateLevel = String(review?.final_candidate_level || "");
  if (candidateLevel === "ORIGINAL") {
    return "为避免画质劣化，本次采用了更轻的处理结果。";
  }
  if (Array.isArray(review?.convergence_actions) && review.convergence_actions.length > 0) {
    return "检测到潜在画质风险，系统已自动降低处理强度。";
  }
  const checks = [
    review?.white_balance_review,
    review?.skin_tone_review,
    review?.noise_review,
    review?.sharpening_and_halo_review,
  ];
  if (checks.some((item) => item?.status === "LOW_CONFIDENCE" || item?.status === "NOT_APPLICABLE")) {
    return "本次处理已完成可执行的安全检查；部分项目因画面条件不足未单独判断，建议查看前后对比。";
  }
  return "本次处理已完成必要的画面安全检查，未发现需要回退的明显风险。";
}

export function colorResultConclusion(result) {
  const postReview = result?.analysis?.post_process_review || {};
  if (postReview.rollback_applied || String(postReview.final_candidate_level || "") === "ORIGINAL") {
    return { label: "已安全回退", tone: "warning", nextAction: "查看处理前后，确认较轻结果是否适合使用" };
  }
  const checks = [postReview.white_balance_review, postReview.skin_tone_review, postReview.noise_review, postReview.sharpening_and_halo_review];
  if (!postReview.post_review_complete || checks.some((item) => ["LOW_CONFIDENCE", "NOT_APPLICABLE"].includes(item?.status)) || result?.review_points?.length) {
    return { label: "建议复核", tone: "warning", nextAction: "查看校正前后，再决定是否使用" };
  }
  if (result?.improvements?.length) return { label: "已改善", tone: "positive", nextAction: "可打开成品，或先查看校正前后" };
  return { label: "正常", tone: "positive", nextAction: "可直接使用当前结果" };
}

export default function ColorCorrectionPage({
  onOpenProcessing,
  onResultReady,
  onTaskContextChange,
  reviewTaskId = "",
  reviewBatchId = "",
  reviewReturnLabel = "返回批次",
  onBackToProcessing,
  initialSourceFile = null,
  initialSourceRequestId = "",
  continueResultId = "",
  onInitialSourceConsumed,
}) {
  const inputRef = useRef(null);
  const referenceInputRef = useRef(null);
  const [colorMode, setColorMode] = useState("automatic");
  const [referenceInput, setReferenceInput] = useState(null);
  const referenceMode = colorMode === "reference";
  const levelMode = colorMode === "level";
  const singleSourceMode = referenceMode || levelMode;
  const [levelPreview, setLevelPreview] = useState(null);
  const [chosenLevel, setChosenLevel] = useState("");
  const [zoomItem, setZoomItem] = useState(null);
  const consumedSourceRequestRef = useRef("");
  const handledContinueResultRef = useRef("");
  const continueIntakeRef = useRef({ resultId: "", promise: null });
  const reviewMode = Boolean(reviewTaskId);
  const [capabilities, setCapabilities] = useState(null);
  const [outputSettings, setOutputSettings] = useState(null);
  const [currentTaskOutputRoot, setCurrentTaskOutputRoot] = useState("");
  const [selectedItems, setSelectedItems] = useState([]);
  const [intakeState, setIntakeState] = useState(FILE_SELECTION_STATES.IDLE);
  const [taskData, setTaskData] = useState(null);
  const [batchData, setBatchData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [comparePosition, setComparePosition] = useState(50);
  const [previewUnavailable, setPreviewUnavailable] = useState(false);
  const [notice, setNotice] = useState("");
  const [reviewBusy, setReviewBusy] = useState(false);

  useEffect(() => {
    onTaskContextChange?.(null);
  }, [onTaskContextChange]);

  useEffect(() => {
    if (reviewMode) return undefined;
    requestJson("/api/color-correction/capabilities")
      .then((payload) => setCapabilities(payload.data || null))
      .catch(() => setCapabilities(null));
    requestJson("/api/color-correction/output-settings")
      .then((payload) => setOutputSettings(normalizeOutputSettings(payload.data)))
      .catch((reason) => setError(reason.message));
    return undefined;
  }, [reviewMode]);

  useEffect(() => {
    if (reviewMode || !continueResultId || handledContinueResultRef.current === continueResultId) return undefined;
    let active = true;
    setBusy(true);
    setError("");
    setNotice("正在从已有成品建立新的颜色校正任务输入…");
    setIntakeState(FILE_SELECTION_STATES.INTAKE_PENDING);
    if (continueIntakeRef.current.resultId !== continueResultId || !continueIntakeRef.current.promise) {
      continueIntakeRef.current = {
        resultId: continueResultId,
        promise: requestJson("/api/color-correction/intake-result", {
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
        setSelectedItems([{
          id: `result-${continueResultId}`,
          file: null,
          selectedFile: {
            name: data.display_name,
            size: data.size_bytes,
            type: data.format === "PNG" ? "image/png" : "image/jpeg",
            lastModified: 0,
          },
          data,
        }]);
        setTaskData(null);
        setBatchData(null);
        setIntakeState(FILE_SELECTION_STATES.FILE_READY);
        setNotice("已从当前成品建立独立颜色校正输入，原文件不会被覆盖。");
      })
      .catch((reason) => {
        if (!active) return;
        continueIntakeRef.current = { resultId: "", promise: null };
        setIntakeState(FILE_SELECTION_STATES.ERROR);
        setError(reason.message);
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [continueResultId, reviewMode]);

  useEffect(() => {
    if (!reviewTaskId) return undefined;
    let active = true;
    setBusy(true);
    setError("");
    setPreviewUnavailable(false);
    requestJson(`/api/color-correction/tasks/${encodeURIComponent(reviewTaskId)}`)
      .then((payload) => {
        if (active) setTaskData(payload.data || null);
      })
      .catch((reason) => {
        if (active) setError(reason.message);
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [reviewTaskId]);

  const task = taskData?.task || null;
  const result = taskData?.result || null;
  const decision = taskData?.decision || result;
  const ui = taskData?.ui || null;
  const review = taskData?.review || null;
  const primaryItem = selectedItems[0] || null;
  const fileInfo = primaryItem?.data || null;
  const selectedFile = primaryItem?.selectedFile || null;
  const sourcePreview = apiUrl(ui?.source_preview_url || fileInfo?.safe_preview_url);
  const outputPreview = apiUrl(ui?.output_preview_url);
  const referencePreview = apiUrl(ui?.reference_preview_url || referenceInput?.data?.safe_preview_url);
  const referenceResult = task?.operation_mode === "REFERENCE_COLOR_CORRECTION";
  const levelResult = task?.operation_mode === "LEVEL_PICK_COLOR_CORRECTION";
  const selectedLevel = ui?.level_pick?.level || decision?.selected_level || "";
  const originalSelected = decision?.result_action === "ACCEPT_ORIGINAL";
  const outputRoot = effectiveOutputRoot(outputSettings, currentTaskOutputRoot);
  const outputDirectory = joinOutputDirectory(outputRoot);
  const completed = task?.status === "completed" && Boolean(originalSelected || (result && outputPreview));
  const failed = task?.status === "failed";
  const protectionBlocked = isColorProtectionBlocked(task, decision);
  const resultSummary = referenceResult
    ? referenceResultSummary(decision, ui?.reference_match_status)
    : levelResult
      ? levelPickSummary(selectedLevel)
      : strategySummary(decision);
  const hasReliablePersonRegion = Boolean(decision?.analysis?.person_region_reliably_detected);
  const resultConclusion = referenceResult ? {
    label: originalSelected ? "已保留原图" : decision?.result_action === "ACCEPT_CORRECTED" ? "已完成受控校色" : "待复核",
    tone: decision?.result_action === "ACCEPT_CORRECTED" ? "positive" : "warning",
    nextAction: originalSelected ? "本次未输出修改结果，可更换参考图后重新处理" : "查看三图对照，再决定是否使用",
  } : levelResult ? {
    label: `已按“${LEVEL_PICK_LABELS[selectedLevel] || "所选"}”档完成`,
    tone: "positive",
    nextAction: "可打开成品，或拖动查看校正前后",
  } : originalSelected ? {
    label: "已保留当前成品",
    tone: "warning",
    nextAction: "本次未生成新 Result，可返回输出中心继续处理原成品",
  } : colorResultConclusion(decision);
  const protectionItems = [
    decision?.analysis?.skin_tone_protection_enabled && "人物肤色已保护",
    decision?.analysis?.highlight_background_protection_enabled && "高亮背景已保护",
    decision?.analysis?.strong_color_protection_enabled && "强色区域已保护",
    decision?.analysis?.noise_protection_enabled && "暗部噪声已保护",
    decision && "原尺寸、比例与原图已保持",
  ].filter(Boolean);

  const clearResult = () => {
    onTaskContextChange?.(null);
    setTaskData(null);
    setBatchData(null);
    setComparePosition(50);
    setNotice("");
    setLevelPreview(null);
    setChosenLevel("");
    setZoomItem(null);
  };

  const intakeFiles = async (files) => {
    const incoming = Array.from(files || []).filter((file) => file && ["image/png", "image/jpeg"].includes(file.type));
    if (singleSourceMode && incoming.length !== 1) {
      setError(levelMode ? "挑档校色每次处理一张图片，请选择一张图片。" : "参考图校色每次处理一张目标图片，请选择一张图片。");
      return;
    }
    if (!incoming.length) {
      setError("请选择 PNG、JPG 或 JPEG 图片。");
      return;
    }
    setBusy(true);
    setError("");
    clearResult();
    const accepted = [];
    const failures = [];
    try {
      for (const file of incoming) {
        try {
          // 串行接收可保持本地内存与磁盘压力可控，批次执行仍由后端队列负责。
          // eslint-disable-next-line no-await-in-loop
          const intake = await performFileIntake(file, {
            request: requestJson,
            onTransition: (nextState) => setIntakeState(nextState),
          });
          accepted.push({
            id: `${file.name}-${file.size}-${file.lastModified}-${accepted.length}`,
            file,
            selectedFile: intake.selectedFile,
            data: intake.data,
          });
        } catch (reason) {
          failures.push(`${file.name}：${reason.message}`);
        }
      }
      setSelectedItems((current) => {
        if (singleSourceMode) return accepted.length ? accepted : current;
        const known = new Set(current.map((item) => (
          item.file
            ? `${item.file.name}-${item.file.size}-${item.file.lastModified}`
            : `result-${item.data?.source_result_id || item.id}`
        )));
        const unique = accepted.filter((item) => !known.has(`${item.file.name}-${item.file.size}-${item.file.lastModified}`));
        return [...current, ...unique];
      });
      setIntakeState(accepted.length ? FILE_SELECTION_STATES.FILE_READY : FILE_SELECTION_STATES.ERROR);
      if (failures.length) setError(`有 ${failures.length} 张图片未加入：${failures.join("；")}`);
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  useEffect(() => {
    if (reviewMode || !initialSourceFile || !initialSourceRequestId || consumedSourceRequestRef.current === initialSourceRequestId) return;
    consumedSourceRequestRef.current = initialSourceRequestId;
    void intakeFiles([initialSourceFile]).finally(() => {
      if (typeof onInitialSourceConsumed === "function") onInitialSourceConsumed(initialSourceRequestId);
    });
  }, [initialSourceFile, initialSourceRequestId, onInitialSourceConsumed, reviewMode]);

  const handleFileChange = (event) => {
    void intakeFiles(event.currentTarget.files);
  };

  const intakeReference = async (event) => {
    const file = event.currentTarget.files?.[0];
    if (!file || busy) return;
    setBusy(true);
    setError("");
    clearResult();
    try {
      const intake = await performFileIntake(file, { request: requestJson });
      setReferenceInput(intake);
    } catch (reason) {
      setError(`参考图片：${reason.message}`);
    } finally {
      setBusy(false);
      if (referenceInputRef.current) referenceInputRef.current.value = "";
    }
  };

  const removeSelectedItem = (id) => {
    setSelectedItems((current) => current.filter((item) => item.id !== id));
    clearResult();
  };

  const chooseOutputRoot = async () => {
    setBusy(true);
    setError("");
    try {
      const selected = await requestJson("/api/output/select-popup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ persist_last_output_dir: false }),
      });
      if (selected.status !== "cancelled" && selected.output_dir) {
        setCurrentTaskOutputRoot(selected.output_dir);
        clearResult();
      }
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };

  const runCorrection = async () => {
    const readyItems = selectedItems.filter((item) => item.data?.source_token);
    if (referenceMode && (readyItems.length !== 1 || !referenceInput?.data?.source_token)) {
      setError("请选择一张目标图片和一张合法参考图片。");
      return;
    }
    if (!readyItems.length) {
      setError("请先选择 PNG、JPG 或 JPEG 图片。");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    onTaskContextChange?.(null);
    if (readyItems.length === 1) {
      setTaskData({
        task: { status: "processing", progress: 20, operation_mode: referenceMode ? "REFERENCE_COLOR_CORRECTION" : "AUTO_COLOR_CORRECTION" },
        result: null,
        ui: { source_preview_url: readyItems[0].data.safe_preview_url, reference_preview_url: referenceInput?.data?.safe_preview_url },
      });
    }
    try {
      const isBatch = !referenceMode && readyItems.length > 1;
      const requestBody = referenceMode
        ? { target_source_token: readyItems[0].data.source_token, reference_source_token: referenceInput.data.source_token }
        : isBatch
        ? { source_tokens: readyItems.map((item) => item.data.source_token) }
        : { source_token: readyItems[0].data.source_token };
      if (currentTaskOutputRoot) requestBody.current_task_output_root = currentTaskOutputRoot;
      const payload = await requestJson(referenceMode ? "/api/color-correction/reference-run" : isBatch ? "/api/color-correction/batches" : "/api/color-correction/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      });
      if (isBatch) {
        setBatchData(payload.data);
        setTaskData(null);
        setNotice(`批量任务已创建，共 ${payload.data?.total_count || readyItems.length} 张，正在进入处理中心。`);
        if (payload.data?.batch_id && typeof onOpenProcessing === "function") onOpenProcessing(payload.data.batch_id);
      } else {
        setTaskData(payload.data);
        if (payload.data?.task?.task_id) onTaskContextChange?.({
          taskId: payload.data.task.task_id,
          mode: payload.data.task.operation_mode,
          taskConfig: payload.data.task,
          taskResult: payload.data.result || {},
        });
        if (payload.data?.task?.status === "failed") {
          setError(colorFailureMessage(payload.data.task, payload.data.result));
        } else if (payload.data?.task?.status === "completed" && payload.data?.task?.task_id && typeof onResultReady === "function") {
          onResultReady(payload.data.task.task_id);
        }
      }
    } catch (reason) {
      setTaskData(reason.taskData || null);
      if (reason.taskData?.task?.task_id) onTaskContextChange?.({
        taskId: reason.taskData.task.task_id,
        mode: reason.taskData.task.operation_mode,
        taskConfig: reason.taskData.task,
        taskResult: reason.taskData.result || {},
      });
      setBatchData(null);
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };

  const createLevelPreview = async () => {
    const item = selectedItems.find((entry) => entry.data?.source_token);
    if (!item || selectedItems.length !== 1) {
      setError("挑档校色每次处理一张图片，请先选择一张图片。");
      return;
    }
    setBusy(true);
    setError("");
    clearResult();
    setNotice("正在生成原图、轻、中、强四档预览，大图可能需要十几秒…");
    try {
      const payload = await requestJson("/api/color-correction/level-preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_token: item.data.source_token }),
      });
      setLevelPreview(payload.data);
      setChosenLevel(payload.data?.measurement?.recommended_level || "original");
      setNotice("");
    } catch (reason) {
      setNotice("");
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };

  const runLevelPick = async () => {
    if (!levelPreview?.preview_id || !chosenLevel) return;
    setBusy(true);
    setError("");
    setNotice("");
    onTaskContextChange?.(null);
    try {
      const requestBody = { preview_id: levelPreview.preview_id, level: chosenLevel };
      if (currentTaskOutputRoot) requestBody.current_task_output_root = currentTaskOutputRoot;
      const payload = await requestJson("/api/color-correction/level-run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      });
      // One preview yields at most one Result; a new choice needs a new preview.
      setLevelPreview(null);
      setZoomItem(null);
      if (payload.data?.selected_level === "original") {
        setChosenLevel("");
        setNotice(payload.data.message || levelPickSummary("original"));
        return;
      }
      setTaskData(payload.data);
      if (payload.data?.task?.task_id) {
        onTaskContextChange?.({
          taskId: payload.data.task.task_id,
          mode: payload.data.task.operation_mode,
          taskConfig: payload.data.task,
          taskResult: payload.data.result || {},
        });
        if (typeof onResultReady === "function") onResultReady(payload.data.task.task_id);
      }
    } catch (reason) {
      setTaskData(reason.taskData || null);
      setError(reason.message);
      // An expired, restarted or already used preview cannot be selected again.
      if (/预览/.test(reason.message || "")) setLevelPreview(null);
    } finally {
      setBusy(false);
    }
  };

  const performResultAction = async (endpoint, successMessage) => {
    if (!task?.task_id) return;
    setNotice("");
    try {
      await requestJson(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: task.task_id }),
      });
      setNotice(successMessage);
    } catch (reason) {
      setError(reason.message);
    }
  };

  const copyPath = async (value, message) => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setNotice(message);
    } catch {
      setError("复制失败，请从路径栏手动复制。");
    }
  };

  const updateResultReview = async (status) => {
    if (!task?.task_id) return;
    setReviewBusy(true);
    setError("");
    setNotice("");
    try {
      const payload = await requestJson(`/api/color-correction/tasks/${encodeURIComponent(task.task_id)}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      setTaskData(payload.data);
      setNotice(status === "confirmed" ? "当前结果已标记为已确认。" : "当前结果已恢复为待确认。可继续查看前后对比。" );
    } catch (reason) {
      setError(reason.message);
    } finally {
      setReviewBusy(false);
    }
  };

  const taskLabel = levelMode && !completed
    ? busy ? (levelPreview ? "正在按所选档位生成结果" : "正在生成四档预览") : levelPreview ? "请选择一档后生成结果" : selectedItems.length ? "图片已就绪，可生成四档预览" : "等待选择图片"
    : busy && task?.status === "processing"
    ? referenceMode ? "正在分析目标与参考图并校色" : "正在分析光线与颜色"
    : completed
      ? referenceResult ? resultConclusion.label : "自动校正已完成"
      : failed
        ? protectionBlocked ? COLOR_PROTECTION_TITLE : "自动校正未完成"
        : batchData
          ? "批量任务已进入队列"
          : selectedItems.length
            ? `${selectedItems.length} 张图片已就绪`
             : "等待选择图片";

  if (reviewMode) {
    const batchId = reviewBatchId || ui?.batch_id || task?.batch_id || "";
    const reviewConfirmed = review?.status === "confirmed";
    return (
      <section className="hdde-color-page hdde-color-review-page hdde-page-frame hdde-page-stack" aria-label="颜色校正结果复核">
        <HddePageHeader
          eyebrow="人工结果确认"
          title="颜色校正结果复核"
          description="对照真实原图与成品后，再记录是否接受当前结果。"
          meta={<HddeStatusPill tone={reviewConfirmed ? "positive" : "warning"}>{reviewConfirmed ? "已确认" : "待确认"}</HddeStatusPill>}
          actions={<div className="hdde-color-review-header-actions">
            <button type="button" className="hdde-secondary-action" onClick={() => onBackToProcessing?.(batchId)}>{reviewReturnLabel}</button>
          </div>}
        />

        {error ? <div className="hdde-color-alert" role="alert">{error}</div> : null}
        {notice ? <div className="hdde-color-notice" role="status">{notice}</div> : null}

        {!completed ? (
          <section className="hdde-color-card hdde-color-review-empty" aria-live="polite">
            <strong>{busy ? "正在读取真实处理结果…" : failed ? "当前任务没有可复核成品" : "结果尚未准备完成"}</strong>
            <p>{failed ? colorFailureMessage(task, result, "请返回批次查看失败原因。") : "只有完成且可读取的真实结果才能进入人工确认。"}</p>
            <button type="button" className="hdde-secondary-action" onClick={() => onBackToProcessing?.(batchId)}>{reviewReturnLabel}</button>
          </section>
        ) : (
          <section className="hdde-color-card hdde-color-result hdde-color-review-result" aria-label="真实颜色校正结果">
            <HddeResultHero
              conclusion={resultConclusion.label}
              tone={resultConclusion.tone}
              title={ui?.source_display_name || "颜色校正图片"}
              summary={resultSummary}
              changes={(decision?.improvements || []).slice(0, 3)}
              protections={protectionItems.slice(0, 4)}
              nextAction={reviewConfirmed ? "已确认，可继续使用或返回输出中心" : "查看处理前后，再记录是否接受"}
              actions={<><button type="button" disabled={!ui?.can_open_output} className="hdde-primary-action" data-testid="color-review-open-output" onClick={() => performResultAction("/api/color-correction/open-output", "已打开当前成品。")}>打开成品</button><button type="button" disabled={!ui?.can_open_folder} className="hdde-secondary-action" data-testid="color-review-open-folder" onClick={() => performResultAction("/api/color-correction/open-output-folder", "已打开当前成品所在目录。")}>打开所在目录</button></>}
            />

            <dl className="hdde-color-review-facts">
              <div><dt>文件名称</dt><dd title={ui?.output_display_name}>{ui?.output_display_name || "—"}</dd></div>
              <div><dt>图片尺寸</dt><dd>{decision?.width} × {decision?.height}</dd></div>
              <div><dt>处理状态</dt><dd>{referenceResult || levelResult ? resultConclusion.label : "自动颜色校正已完成"}</dd></div>
              <div><dt>输出位置</dt><dd title={ui?.output_directory}>{ui?.output_directory || "—"}</dd></div>
            </dl>

            {originalSelected ? <div className="hdde-color-preview-fallback" role="status" data-testid="color-original-no-result"><strong>未生成新 Result</strong><p>本次颜色校正决定保留当前成品；未登记指向缓存文件的输出，可从原成品继续处理。</p></div> : referenceResult ? <ReferenceComparison target={sourcePreview} reference={referencePreview} candidate={outputPreview} /> : previewUnavailable ? (
              <div className="hdde-color-preview-fallback" role="status" data-testid="color-review-preview-fallback">
                <strong>当前预览暂不可用</strong>
                <p>历史预览资源未能读取，但结果结论、保护信息和成品操作仍可继续使用。</p>
              </div>
            ) : (
              <div className="hdde-color-compare" data-testid="color-review-before-after">
                <img src={sourcePreview} alt={`${ui?.source_display_name || "当前图片"}校正前`} onError={() => setPreviewUnavailable(true)} />
                <div className="hdde-color-compare-after" style={{ clipPath: `inset(0 ${100 - comparePosition}% 0 0)` }}><img src={outputPreview} alt={`${ui?.source_display_name || "当前图片"}校正后`} onError={() => setPreviewUnavailable(true)} /></div>
                <div className="hdde-color-divider" style={{ left: `${comparePosition}%` }} aria-hidden="true"><span>↔</span></div>
                <span className="hdde-color-compare-label is-before">原图</span>
                <span className="hdde-color-compare-label is-after">成品</span>
                <input aria-label="拖动查看原图与成品" type="range" min="0" max="100" value={comparePosition} onChange={(event) => setComparePosition(Number(event.target.value))} />
              </div>
            )}

            {!originalSelected && <div className="hdde-color-review-decision" data-status={reviewConfirmed ? "confirmed" : "pending"} data-testid="color-review-state">
              <div>
                <span>人工确认状态</span>
                <strong>{reviewConfirmed ? "已确认" : "待确认"}</strong>
                <p>“已确认”只表示你已查看并接受当前结果，不代表自动视觉评分或软件判定质量通过。</p>
              </div>
              <button
                type="button"
                className={reviewConfirmed ? "hdde-secondary-action" : "hdde-primary-action"}
                data-testid="color-review-confirm"
                aria-pressed={reviewConfirmed}
                disabled={reviewBusy}
                onClick={() => updateResultReview(reviewConfirmed ? "pending" : "confirmed")}
              >
                {reviewBusy ? "正在保存…" : reviewConfirmed ? "恢复为待确认" : "标记为已确认"}
              </button>
            </div>}
          </section>
        )}
      </section>
    );
  }

  return (
    <section className="hdde-color-page hdde-page-frame hdde-page-stack" aria-label="自动颜色校正">
      <HddePageHeader
        eyebrow="单图与多图处理"
        title="颜色校正"
        description="自动识别逆光、偏色和暗部问题，只调整现有像素，不改变构图和内容。"
        meta={<HddeStatusPill tone={capabilities ? "positive" : "neutral"}>{capabilities ? "本地服务已连接" : "正在连接本地服务"}</HddeStatusPill>}
      />

      <div className="hdde-reference-tabs" role="group" aria-label="颜色校正模式">
        <button type="button" className={colorMode === "automatic" ? "hdde-primary-action" : "hdde-secondary-action"} aria-pressed={colorMode === "automatic"} disabled={busy} onClick={() => { setColorMode("automatic"); clearResult(); setError(""); }}>自动校色</button>
        <button type="button" className={referenceMode ? "hdde-primary-action" : "hdde-secondary-action"} aria-pressed={referenceMode} disabled={busy} onClick={() => { setColorMode("reference"); clearResult(); setError(""); }}>参考图校色</button>
        <button type="button" className={levelMode ? "hdde-primary-action" : "hdde-secondary-action"} aria-pressed={levelMode} disabled={busy} data-testid="color-mode-level" onClick={() => { setColorMode("level"); clearResult(); setError(""); setSelectedItems((current) => current.slice(0, 1)); }}>挑档校色</button>
      </div>

      <div className="hdde-color-flow">
        <section className="hdde-color-card hdde-color-source" aria-label="选择图片">
          <div className="hdde-color-section-title"><span>1</span><div><h2>{referenceMode ? "目标图片" : "选择图片"}</h2><p>{referenceMode ? "选择一张需要校色的目标图片；不会覆盖原图。" : levelMode ? "选择一张偏黄、偏蓝或发灰的图片；不会覆盖原图。" : "支持一次选择多张 PNG、JPG、JPEG；每张最大 50 MB。"}</p></div>{selectedItems.length ? <strong className="hdde-color-selection-count" data-testid="color-selection-count">{selectedItems.length} 张</strong> : null}</div>
          <div
            className={`hdde-color-dropzone${selectedItems.length ? " has-file" : ""}`}
            onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }}
            onDrop={(event) => { event.preventDefault(); void intakeFiles(event.dataTransfer.files); }}
          >
            <input ref={inputRef} id="color-file-input" data-testid="color-file-input" type="file" accept=".png,.jpg,.jpeg,image/png,image/jpeg" multiple={!singleSourceMode} onChange={handleFileChange} disabled={busy} />
            {selectedItems.length ? <div className="hdde-color-file-list" data-testid="color-file-list">
              {selectedItems.map((item) => (
                <article key={item.id}>
                  <img src={apiUrl(item.data.safe_preview_url)} alt="待校正原图预览" data-testid="color-source-preview" />
                  <div className="hdde-color-file-meta">
                    <strong title={item.data.display_name}>{item.data.display_name}</strong>
                    <span>{item.data.format} · {item.data.width} × {item.data.height} · {formatBytes(item.data.size_bytes)}</span>
                  </div>
                  <button type="button" className="hdde-secondary-action" data-testid="color-remove-file" onClick={() => removeSelectedItem(item.id)} disabled={busy} aria-label={`移除 ${item.data.display_name}`}>移除</button>
                </article>
              ))}
              <button type="button" className="hdde-secondary-action hdde-color-add-more" onClick={() => inputRef.current?.click()} disabled={busy}>{singleSourceMode ? "替换图片" : "继续添加图片"}</button>
            </div> : <label htmlFor="color-file-input">
              <strong>{selectedFile ? selectedFile.name : "拖入图片，或点击选择"}</strong>
              <span>{intakeState === FILE_SELECTION_STATES.INTAKE_PENDING ? "正在安全读取图片…" : "图片只在本机处理，不会自动上传"}</span>
            </label>}
          </div>
          {referenceMode && <div className="hdde-reference-input" aria-label="参考图片">
            <h3>参考图片</h3>
            <p>仅用于分析综合色调，不会被修改或作为成品输出。支持 PNG、JPEG，最大 50 MB。</p>
            <input ref={referenceInputRef} id="color-reference-input" data-testid="color-reference-input" type="file" accept=".png,.jpg,.jpeg,image/png,image/jpeg" onChange={intakeReference} disabled={busy} aria-label="上传参考图片" />
            {referenceInput?.data && <div className="hdde-reference-input-preview">
              <img src={apiUrl(referenceInput.data.safe_preview_url)} alt="参考图片预览" />
              <span>{referenceInput.data.display_name}</span>
            </div>}
            <div className="hdde-reference-input-actions">
              <button type="button" className="hdde-secondary-action" disabled={busy} onClick={() => referenceInputRef.current?.click()}>{referenceInput ? "替换参考图" : "上传参考图"}</button>
              {referenceInput && <button type="button" className="hdde-secondary-action" disabled={busy} onClick={() => { setReferenceInput(null); clearResult(); }}>删除参考图</button>}
            </div>
            {selectedItems.length > 1 && <p role="status">当前有多张目标图，请保留一张后再执行参考图校色。</p>}
          </div>}
        </section>

        <section className="hdde-color-card hdde-color-controls" aria-label="输出与处理">
          <div className="hdde-color-section-title"><span>2</span><div><h2>确认输出并开始</h2><p>{levelMode ? "先看四档预览，由你选定一档；系统不替你决定改不改。" : "系统会自动判断，不需要手动调参数。"}</p></div></div>
          <div className="hdde-color-output-path">
            <span>本次输出目录</span>
            <code title={outputDirectory}>{outputDirectory || "正在读取正式输出目录…"}</code>
            <small>{currentTaskOutputRoot ? "仅当前任务使用，不修改长期设置" : "使用当前正式默认目录"}</small>
            <button type="button" className="hdde-secondary-action" onClick={chooseOutputRoot} disabled={busy || !outputSettings}>仅为本次选择文件夹</button>
          </div>
          <div className="hdde-color-safety">
            <strong>自动保护</strong>
            {levelMode
              ? <><span>保持原尺寸与比例</span><span>人物肤色保留原有暖调</span><span>高光不过曝、暗部不死黑</span></>
              : <><span>保持原尺寸与比例</span><span>保护高光、LED屏与透明边缘</span><span>逆光时优先改善人物和前景</span></>}
          </div>
          {levelMode ? <button type="button" className="hdde-primary-action hdde-color-run" data-testid="color-level-preview" onClick={createLevelPreview} disabled={busy || selectedItems.length !== 1 || !outputSettings}>
            {busy && !levelPreview ? "正在生成四档预览…" : levelPreview ? "重新生成四档预览" : "生成四档预览"}
          </button> : <button type="button" className="hdde-primary-action hdde-color-run" data-testid="color-run" onClick={runCorrection} disabled={busy || !selectedItems.length || !outputSettings || (referenceMode && (selectedItems.length !== 1 || !referenceInput?.data?.source_token))}>
            {busy ? "正在创建处理任务…" : referenceMode ? "开始参考图校色" : selectedItems.length > 1 ? `开始处理 ${selectedItems.length} 张图片` : "开始自动校正"}
          </button>}
          <p className="hdde-color-task-state" data-status={failed ? "failed" : completed ? "completed" : task?.status || "idle"} role="status">
            {taskLabel}{task?.progress != null ? ` · ${task.progress}%` : ""}
          </p>
        </section>
      </div>

      {error ? <div className="hdde-color-alert" role="alert">{error}</div> : null}
      {notice ? <div className="hdde-color-notice" role="status">{notice}</div> : null}

      {levelMode && levelPreview && !completed ? <section className="hdde-color-card hdde-color-level-card" aria-label="选择校色档位">
        <div className="hdde-color-section-title"><span>3</span><div><h2>选择一档</h2><p>点击图片可放大查看。选定后才会生成正式结果；选“原图”不会生成新文件。</p></div></div>
        <LevelPickOptions preview={levelPreview} chosen={chosenLevel} onChoose={setChosenLevel} onZoom={setZoomItem} disabled={busy} />
        <div className="hdde-level-actions">
          <button type="button" className="hdde-primary-action" data-testid="color-level-run" disabled={busy || !chosenLevel} onClick={runLevelPick}>
            {busy ? "正在生成结果…" : chosenLevel === "original" ? "使用原图（不生成新文件）" : `使用“${LEVEL_PICK_LABELS[chosenLevel] || ""}”档生成结果`}
          </button>
        </div>
      </section> : null}

      {zoomItem ? <div className="hdde-level-zoom" role="dialog" aria-modal="true" aria-label={`${zoomItem.label}档原尺寸查看`} onClick={() => setZoomItem(null)}>
        <div className="hdde-level-zoom-bar"><strong>{zoomItem.label}</strong><button type="button" className="hdde-secondary-action" onClick={() => setZoomItem(null)}>关闭</button></div>
        <div className="hdde-level-zoom-body"><img src={apiUrl(zoomItem.preview_url)} alt={`${zoomItem.label}档原尺寸`} /></div>
      </div> : null}

      {completed ? <>
        <section className="hdde-color-card hdde-color-result" aria-label="校正结果">
          <HddeResultHero
            conclusion={resultConclusion.label}
            tone={resultConclusion.tone}
            title={referenceResult || levelResult ? resultConclusion.label : "颜色校正已完成"}
            summary={resultSummary}
            changes={(decision?.improvements || []).slice(0, 3)}
            protections={protectionItems.slice(0, 4)}
            nextAction={resultConclusion.nextAction}
            actions={<>
              <button type="button" disabled={!ui?.can_open_output} className="hdde-primary-action" data-testid="color-open-output" onClick={() => performResultAction("/api/color-correction/open-output", "已打开校正结果。")}>打开结果</button>
              <button type="button" disabled={!ui?.can_open_folder} className="hdde-secondary-action" data-testid="color-open-folder" onClick={() => performResultAction("/api/color-correction/open-output-folder", "已打开输出目录。")}> <HddeIcon name="folder" size={16} />打开所在目录</button>
              <button type="button" disabled={!ui?.output_path} className="hdde-tertiary-action" data-testid="color-copy-path" onClick={() => copyPath(ui.output_path, "结果路径已复制。")}> <HddeIcon name="copy" size={16} />复制路径</button>
            </>}
          />

          {originalSelected ? <div className="hdde-color-preview-fallback" role="status" data-testid="color-original-no-result"><strong>未生成新 Result</strong><p>本次颜色校正决定保留当前成品；原成品身份与文件保持不变，可继续执行其他处理。</p></div> : referenceResult ? <ReferenceComparison target={sourcePreview} reference={referencePreview} candidate={outputPreview} /> : <div className="hdde-color-compare" data-testid="color-before-after">
            <img src={sourcePreview} alt="校正前" />
            <div className="hdde-color-compare-after" style={{ clipPath: `inset(0 ${100 - comparePosition}% 0 0)` }}><img src={outputPreview} alt="校正后" /></div>
            <div className="hdde-color-divider" style={{ left: `${comparePosition}%` }} aria-hidden="true"><span>↔</span></div>
            <span className="hdde-color-compare-label is-before">校正前</span>
            <span className="hdde-color-compare-label is-after">校正后</span>
            <input aria-label="拖动查看校正前后" type="range" min="0" max="100" value={comparePosition} onChange={(event) => setComparePosition(Number(event.target.value))} />
          </div>}
        </section>

        {!originalSelected && <div className="hdde-color-report-grid">
          <section className="hdde-color-card" aria-label="结果报告">
            <div className="hdde-color-section-title"><span>3</span><div><h2>变化、保护与复核</h2><p>只保留影响使用决定的信息；工程指标在技术详情中。</p></div></div>
            <div className="hdde-color-findings hdde-color-findings--decision">
              <div><strong>本次变化</strong><ul>{(result.improvements?.length ? result.improvements : [resultSummary]).map((item) => <li key={item}>{item}</li>)}</ul></div>
              <div><strong>安全保护</strong><ul>{protectionItems.map((item) => <li key={item}>{item}</li>)}</ul></div>
              <div><strong>建议复核</strong><ul>{(result.review_points?.length ? result.review_points : [postReviewSummary(result.analysis?.post_process_review)]).map((item) => <li key={item}>{item}</li>)}</ul></div>
            </div>
            <dl className="hdde-color-output-facts">
              <div><dt>输出文件</dt><dd title={ui.output_display_name}>{ui.output_display_name}</dd></div>
              <div><dt>输入/输出</dt><dd>{result.width} × {result.height} · {result.source_format} → {result.width} × {result.height} · {result.output_format}</dd></div>
              <div><dt>输入/输出体积</dt><dd>{formatBytes(result.source_size_bytes)} → {formatBytes(result.output_size_bytes)}</dd></div>
              <div><dt>处理耗时</dt><dd>{(result.processing_time_ms / 1000).toFixed(2)} 秒</dd></div>
            </dl>
          </section>

        </div>}

        {!referenceResult && !levelResult && !originalSelected && <HddeTechnicalDetails summary="查看技术详情" className="hdde-color-advanced">
          <dl>
            <div><dt>任务状态</dt><dd>{task.status} · {task.progress}%</dd></div>
            <div><dt>处理方式</dt><dd>单图自动颜色校正</dd></div>
            <div><dt>任务编号</dt><dd>{ui.display_task_number}</dd></div>
            <div><dt>引擎版本</dt><dd>{result.engine_version}</dd></div>
            <div><dt>逐图策略</dt><dd>{result.analysis?.strategy_label || "自适应颜色与层次校正"}</dd></div>
            <div><dt>模块顺序</dt><dd>{result.analysis?.module_order?.join(" → ") || "按图片分析结果执行"}</dd></div>
            <div><dt>曝光判断</dt><dd>{result.analysis?.exposure_state || "—"}</dd></div>
            <div><dt>白平衡判断</dt><dd>{result.analysis?.color_cast || "—"} · 可信度 {metricNumber(result.analysis?.white_balance_confidence, 2) || "—"}</dd></div>
            <div><dt>人物/背景增益</dt><dd>{hasReliablePersonRegion ? `${metricNumber(result.analysis?.foreground_luminance_gain)} / ${metricNumber(result.analysis?.background_luminance_gain)}` : "未检测到需要独立处理的人物区域"}</dd></div>
            <div><dt>对比与通透</dt><dd>全局 {metricNumber(result.parameters?.contrast_strength, 3) || "0.000"} · 局部 {metricNumber(result.parameters?.local_contrast_strength, 3) || "0.000"} · 清晰度 {metricNumber(result.parameters?.clarity_strength, 3) || "0.000"}</dd></div>
            <div><dt>色彩处理</dt><dd>{result.parameters?.saturation_adjustment_mode || "保持原有色彩强度"} · 强度 {metricNumber(result.parameters?.selective_color_strength, 3) || "0.000"}</dd></div>
            <div><dt>强色区域</dt><dd>{result.analysis?.strong_color_protection_enabled ? `已保护 · 色彩强度 ${metricPercent(result.analysis?.strong_color_saturation_before)}% → ${metricPercent(result.analysis?.strong_color_saturation_after)}%` : "未启用独立强色保护"}</dd></div>
            <div><dt>处理后复核</dt><dd>{result.analysis?.post_process_review?.rollback_applied ? `已回退至 ${metricPercent(result.analysis?.post_process_review?.selected_candidate_blend)}% 强度` : "通过，无需回退"}</dd></div>
            <div><dt>输出编码</dt><dd>{result.output_format === "JPEG" ? `质量 ${result.parameters?.jpeg_quality ?? "—"} · 色度采样 ${result.parameters?.jpeg_subsampling ?? "—"}` : "PNG 保留透明与无损像素"}{result.parameters?.encoding_retry_applied ? " · 已执行体积控制重试" : ""}</dd></div>
            <div><dt>保护状态</dt><dd>{[
              result.analysis?.skin_tone_protection_enabled && "肤色",
              result.analysis?.highlight_background_protection_enabled && "高亮背景",
              result.analysis?.strong_color_protection_enabled && "强色区域",
              result.analysis?.noise_protection_enabled && "暗部噪声",
            ].filter(Boolean).join("、") || "常规结构保护"}</dd></div>
            <div><dt>处理动作</dt><dd>{result.applied_actions?.join("、") || "低强度保护处理"}</dd></div>
            <div><dt>整体亮度</dt><dd>{metricNumber(result.before_metrics?.mean_luminance)} → {metricNumber(result.after_metrics?.mean_luminance)}</dd></div>
            <div><dt>黑位 / 中间调 / 白位</dt><dd>{metricNumber(result.before_metrics?.black_point)} / {metricNumber(result.before_metrics?.midtone_point)} / {metricNumber(result.before_metrics?.white_point)} → {metricNumber(result.after_metrics?.black_point)} / {metricNumber(result.after_metrics?.midtone_point)} / {metricNumber(result.after_metrics?.white_point)}</dd></div>
            <div><dt>局部层次</dt><dd>{metricNumber(result.before_metrics?.local_contrast, 2)} → {metricNumber(result.after_metrics?.local_contrast, 2)}</dd></div>
            <div><dt>色彩强度</dt><dd>{metricPercent(result.before_metrics?.mean_saturation)}% → {metricPercent(result.after_metrics?.mean_saturation)}%</dd></div>
            <div><dt>暗部 / 高光占比</dt><dd>{metricPercent(result.before_metrics?.shadow_ratio)}% / {metricPercent(result.before_metrics?.highlight_ratio)}% → {metricPercent(result.after_metrics?.shadow_ratio)}% / {metricPercent(result.after_metrics?.highlight_ratio)}%</dd></div>
            <div><dt>创建/完成</dt><dd>{task.created_at} / {task.completed_at}</dd></div>
          </dl>
        </HddeTechnicalDetails>}
      </> : null}
    </section>
  );
}
