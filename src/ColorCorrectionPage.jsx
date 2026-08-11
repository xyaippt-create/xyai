import React, { useEffect, useRef, useState } from "react";
import { HddePageHeader, HddeStatusPill } from "./HddeUI.jsx";
import {
  FILE_SELECTION_STATES,
  effectiveOutputRoot,
  normalizeOutputSettings,
  performFileIntake,
} from "./compressionSession.js";
import UnifiedFeedback from "./UnifiedFeedback.jsx";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

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
    throw new Error(message || payload?.message || `本地服务请求失败（${response.status}）。`);
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

function Metric({ label, before, after, unit = "" }) {
  const showBeforeAfter = before != null && after != null;
  return (
    <div className="hdde-color-metric">
      <span>{label}</span>
      <strong>{showBeforeAfter ? `${before}${unit} → ${after}${unit}` : after ?? "—"}</strong>
    </div>
  );
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

export default function ColorCorrectionPage({
  onOpenProcessing,
  reviewTaskId = "",
  reviewBatchId = "",
  reviewReturnLabel = "返回批次",
  onBackToProcessing,
  initialSourceFile = null,
  initialSourceRequestId = "",
  onInitialSourceConsumed,
}) {
  const inputRef = useRef(null);
  const consumedSourceRequestRef = useRef("");
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
  const [notice, setNotice] = useState("");
  const [reviewBusy, setReviewBusy] = useState(false);

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
    if (!reviewTaskId) return undefined;
    let active = true;
    setBusy(true);
    setError("");
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
  const ui = taskData?.ui || null;
  const review = taskData?.review || null;
  const primaryItem = selectedItems[0] || null;
  const fileInfo = primaryItem?.data || null;
  const selectedFile = primaryItem?.selectedFile || null;
  const sourcePreview = apiUrl(ui?.source_preview_url || fileInfo?.safe_preview_url);
  const outputPreview = apiUrl(ui?.output_preview_url);
  const outputRoot = effectiveOutputRoot(outputSettings, currentTaskOutputRoot);
  const outputDirectory = joinOutputDirectory(outputRoot);
  const completed = task?.status === "completed" && Boolean(result && outputPreview);
  const failed = task?.status === "failed";
  const resultSummary = strategySummary(result);
  const hasReliablePersonRegion = Boolean(result?.analysis?.person_region_reliably_detected);
  const protectionSummary = [
    result?.analysis?.skin_tone_protection_enabled && "人物肤色",
    result?.analysis?.highlight_background_protection_enabled && "高亮背景",
    result?.analysis?.strong_color_protection_enabled && "强色区域",
    result?.analysis?.noise_protection_enabled && "暗部噪声",
  ].filter(Boolean).join("、") || "构图、尺寸与原有色彩关系";

  const clearResult = () => {
    setTaskData(null);
    setBatchData(null);
    setComparePosition(50);
    setNotice("");
  };

  const intakeFiles = async (files) => {
    const incoming = Array.from(files || []).filter((file) => file && ["image/png", "image/jpeg"].includes(file.type));
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
        const known = new Set(current.map((item) => `${item.file.name}-${item.file.size}-${item.file.lastModified}`));
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
    if (!readyItems.length) {
      setError("请先选择 PNG、JPG 或 JPEG 图片。");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    if (readyItems.length === 1) {
      setTaskData({
        task: { status: "processing", progress: 20, operation_mode: "AUTO_COLOR_CORRECTION" },
        result: null,
        ui: { source_preview_url: readyItems[0].data.safe_preview_url },
      });
    }
    try {
      const isBatch = readyItems.length > 1;
      const requestBody = isBatch
        ? { source_tokens: readyItems.map((item) => item.data.source_token) }
        : { source_token: readyItems[0].data.source_token };
      if (currentTaskOutputRoot) requestBody.current_task_output_root = currentTaskOutputRoot;
      const payload = await requestJson(isBatch ? "/api/color-correction/batches" : "/api/color-correction/run", {
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
        if (payload.data?.task?.status === "failed") setError(payload.data.task.failure_reason || "颜色校正未完成。");
      }
    } catch (reason) {
      setTaskData(null);
      setBatchData(null);
      setError(reason.message);
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

  const taskLabel = busy && task?.status === "processing"
    ? "正在分析光线与颜色"
    : completed
      ? "自动校正已完成"
      : failed
        ? "自动校正未完成"
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
            <p>{failed ? task?.failure_reason || "请返回批次查看失败原因。" : "只有完成且可读取的真实结果才能进入人工确认。"}</p>
            <button type="button" className="hdde-secondary-action" onClick={() => onBackToProcessing?.(batchId)}>{reviewReturnLabel}</button>
          </section>
        ) : (
          <section className="hdde-color-card hdde-color-result hdde-color-review-result" aria-label="真实颜色校正结果">
            <div className="hdde-color-result-heading">
              <div><p className="hdde-eyebrow">真实任务结果</p><h2>{ui?.source_display_name || "颜色校正图片"}</h2><p>{resultSummary}</p></div>
              <div className="hdde-color-result-actions">
                <button type="button" className="hdde-primary-action" data-testid="color-review-open-output" onClick={() => performResultAction("/api/color-correction/open-output", "已打开当前成品。")}>打开成品</button>
                <button type="button" className="hdde-secondary-action" data-testid="color-review-open-folder" onClick={() => performResultAction("/api/color-correction/open-output-folder", "已打开当前成品所在目录。")}>打开所在目录</button>
              </div>
            </div>

            <dl className="hdde-color-review-facts">
              <div><dt>文件名称</dt><dd title={ui?.output_display_name}>{ui?.output_display_name || "—"}</dd></div>
              <div><dt>图片尺寸</dt><dd>{result?.width} × {result?.height}</dd></div>
              <div><dt>处理状态</dt><dd>自动颜色校正已完成</dd></div>
              <div><dt>输出位置</dt><dd title={ui?.output_directory}>{ui?.output_directory || "—"}</dd></div>
            </dl>

            <div className="hdde-color-compare" data-testid="color-review-before-after">
              <img src={sourcePreview} alt={`${ui?.source_display_name || "当前图片"}校正前`} />
              <div className="hdde-color-compare-after" style={{ clipPath: `inset(0 ${100 - comparePosition}% 0 0)` }}><img src={outputPreview} alt={`${ui?.source_display_name || "当前图片"}校正后`} /></div>
              <div className="hdde-color-divider" style={{ left: `${comparePosition}%` }} aria-hidden="true"><span>↔</span></div>
              <span className="hdde-color-compare-label is-before">原图</span>
              <span className="hdde-color-compare-label is-after">成品</span>
              <input aria-label="拖动查看原图与成品" type="range" min="0" max="100" value={comparePosition} onChange={(event) => setComparePosition(Number(event.target.value))} />
            </div>

            <div className="hdde-color-review-decision" data-status={reviewConfirmed ? "confirmed" : "pending"} data-testid="color-review-state">
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
            </div>
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

      <div className="hdde-color-flow">
        <section className="hdde-color-card hdde-color-source" aria-label="选择图片">
          <div className="hdde-color-section-title"><span>1</span><div><h2>选择图片</h2><p>支持一次选择多张 PNG、JPG、JPEG；每张最大 50 MB。</p></div>{selectedItems.length ? <strong className="hdde-color-selection-count" data-testid="color-selection-count">{selectedItems.length} 张</strong> : null}</div>
          <div
            className={`hdde-color-dropzone${selectedItems.length ? " has-file" : ""}`}
            onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }}
            onDrop={(event) => { event.preventDefault(); void intakeFiles(event.dataTransfer.files); }}
          >
            <input ref={inputRef} id="color-file-input" data-testid="color-file-input" type="file" accept=".png,.jpg,.jpeg,image/png,image/jpeg" multiple onChange={handleFileChange} disabled={busy} />
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
              <button type="button" className="hdde-secondary-action hdde-color-add-more" onClick={() => inputRef.current?.click()} disabled={busy}>继续添加图片</button>
            </div> : <label htmlFor="color-file-input">
              <strong>{selectedFile ? selectedFile.name : "拖入图片，或点击选择"}</strong>
              <span>{intakeState === FILE_SELECTION_STATES.INTAKE_PENDING ? "正在安全读取图片…" : "图片只在本机处理，不会自动上传"}</span>
            </label>}
          </div>
        </section>

        <section className="hdde-color-card hdde-color-controls" aria-label="输出与处理">
          <div className="hdde-color-section-title"><span>2</span><div><h2>确认输出并开始</h2><p>系统会自动判断，不需要手动调参数。</p></div></div>
          <div className="hdde-color-output-path">
            <span>本次输出目录</span>
            <code title={outputDirectory}>{outputDirectory || "正在读取正式输出目录…"}</code>
            <small>{currentTaskOutputRoot ? "仅当前任务使用，不修改长期设置" : "使用当前正式默认目录"}</small>
            <button type="button" className="hdde-secondary-action" onClick={chooseOutputRoot} disabled={busy || !outputSettings}>仅为本次选择文件夹</button>
          </div>
          <div className="hdde-color-safety">
            <strong>自动保护</strong>
            <span>保持原尺寸与比例</span><span>保护高光、LED屏与透明边缘</span><span>逆光时优先改善人物和前景</span>
          </div>
          <button type="button" className="hdde-primary-action hdde-color-run" data-testid="color-run" onClick={runCorrection} disabled={busy || !selectedItems.length || !outputSettings}>
            {busy ? "正在创建处理任务…" : selectedItems.length > 1 ? `开始处理 ${selectedItems.length} 张图片` : "开始自动校正"}
          </button>
          <p className="hdde-color-task-state" data-status={failed ? "failed" : completed ? "completed" : task?.status || "idle"} role="status">
            {taskLabel}{task?.progress != null ? ` · ${task.progress}%` : ""}
          </p>
        </section>
      </div>

      {error ? <div className="hdde-color-alert" role="alert">{error}</div> : null}
      {notice ? <div className="hdde-color-notice" role="status">{notice}</div> : null}

      {completed ? <>
        <section className="hdde-color-card hdde-color-result" aria-label="校正结果">
          <div className="hdde-color-result-heading">
            <div><p className="hdde-eyebrow">处理结果</p><h2>自动校正已完成</h2><p>{resultSummary}</p></div>
            <div className="hdde-color-result-actions">
              <button type="button" className="hdde-primary-action" data-testid="color-open-output" onClick={() => performResultAction("/api/color-correction/open-output", "已打开校正结果。")}>打开结果</button>
              <button type="button" className="hdde-secondary-action" data-testid="color-open-folder" onClick={() => performResultAction("/api/color-correction/open-output-folder", "已打开输出目录。")}>打开所在目录</button>
              <button type="button" className="hdde-secondary-action" data-testid="color-copy-path" onClick={() => copyPath(ui.output_path, "结果路径已复制。")}>复制路径</button>
            </div>
          </div>

          <div className="hdde-color-compare" data-testid="color-before-after">
            <img src={sourcePreview} alt="校正前" />
            <div className="hdde-color-compare-after" style={{ clipPath: `inset(0 ${100 - comparePosition}% 0 0)` }}><img src={outputPreview} alt="校正后" /></div>
            <div className="hdde-color-divider" style={{ left: `${comparePosition}%` }} aria-hidden="true"><span>↔</span></div>
            <span className="hdde-color-compare-label is-before">校正前</span>
            <span className="hdde-color-compare-label is-after">校正后</span>
            <input aria-label="拖动查看校正前后" type="range" min="0" max="100" value={comparePosition} onChange={(event) => setComparePosition(Number(event.target.value))} />
          </div>
        </section>

        <div className="hdde-color-report-grid">
          <section className="hdde-color-card" aria-label="结果报告">
            <div className="hdde-color-section-title"><span>3</span><div><h2>结果报告</h2><p>先看处理结论；精确指标和策略记录已收进高级信息。</p></div></div>
            <div className="hdde-color-findings">
              <div><strong>处理结论</strong><ul><li>{resultSummary}</li><li>{postReviewSummary(result.analysis?.post_process_review)}</li></ul></div>
              <div><strong>主要问题</strong><ul>{result.detected_issues?.map((item) => <li key={item}>{item}</li>)}</ul></div>
              <div><strong>本次处理</strong><ul>{result.improvements?.map((item) => <li key={item}>{item}</li>)}</ul></div>
              <div><strong>保护与文件安全</strong><ul><li>已保护：{protectionSummary}</li><li>保持原始尺寸、比例和格式，输出为新的本地文件，未覆盖原图。</li></ul></div>
              <div><strong>建议复核</strong><ul>{result.review_points?.map((item) => <li key={item}>{item}</li>)}</ul></div>
            </div>
            <dl className="hdde-color-output-facts">
              <div><dt>输出文件</dt><dd title={ui.output_display_name}>{ui.output_display_name}</dd></div>
              <div><dt>输入/输出</dt><dd>{result.width} × {result.height} · {result.source_format} → {result.width} × {result.height} · {result.output_format}</dd></div>
              <div><dt>输入/输出体积</dt><dd>{formatBytes(result.source_size_bytes)} → {formatBytes(result.output_size_bytes)}</dd></div>
              <div><dt>处理耗时</dt><dd>{(result.processing_time_ms / 1000).toFixed(2)} 秒</dd></div>
            </dl>
          </section>

          <section className="hdde-color-card hdde-color-feedback" aria-label="问题反馈报告">
            <div className="hdde-color-section-title"><span>4</span><div><h2>结果有问题？</h2><p>进入统一反馈流程，自动整理当前任务与诊断事实。</p></div></div>
            <UnifiedFeedback
              taskId={task?.task_id || ""}
              sourceFeature="color_correction"
              stage={task?.stage || task?.status || "color_correction_review"}
              triggerLabel="反馈问题"
              triggerClassName="hdde-secondary-action"
              testId="color-feedback-trigger"
            />
          </section>
        </div>

        <details className="hdde-color-advanced">
          <summary>查看高级处理信息</summary>
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
        </details>
      </> : null}
    </section>
  );
}
