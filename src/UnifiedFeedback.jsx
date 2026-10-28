import React, { useEffect, useState, useSyncExternalStore } from "react";
import {
  captureFeedbackContext,
  feedbackBundleDownload,
  generateUnifiedFeedbackBundle,
  sanitizeFeedbackText,
} from "./feedbackFlow.js";
import HddeIcon from "./HddeIcon.jsx";
import {
  getCurrentFeedbackTarget,
  normalizeFeedbackTarget,
  resolveFeedbackTarget,
  subscribeFeedbackTarget,
} from "./feedbackTarget.js";

function formatBytes(value) {
  const size = Number(value || 0);
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

const DECISION_OPTIONS = Object.freeze([
  ["ACCEPTED", "可以直接使用"],
  ["NEEDS_ADJUSTMENT", "需要继续调整"],
  ["UNUSABLE", "不能使用"],
]);

const REASON_OPTIONS = Object.freeze([
  ["EFFECT_TOO_WEAK", "效果不明显"],
  ["OVER_PROCESSED", "处理过度"],
  ["COLOR_ABNORMAL", "颜色异常"],
  ["QUALITY_DEGRADED", "画质下降"],
  ["LOCAL_DAMAGE", "局部损坏"],
  ["TEXT_OR_LOGO_DAMAGE", "文字 / Logo 损坏"],
  ["EDGE_ARTIFACT", "边缘异常"],
  ["RESULT_NOT_AS_EXPECTED", "结果与预期不符"],
  ["WORKFLOW_PROBLEM", "操作流程有问题"],
  ["OTHER", "其他"],
]);

export default function UnifiedFeedback({
  taskId = "",
  sourceFeature = "runtime_failure",
  stage = "",
  route = "",
  triggerLabel = "反馈问题",
  triggerClassName = "",
  testId = "unified-feedback-trigger",
  disabled = false,
  feedbackTarget = null,
}) {
  const currentFeedbackTarget = useSyncExternalStore(
    subscribeFeedbackTarget,
    getCurrentFeedbackTarget,
    getCurrentFeedbackTarget,
  );
  const [open, setOpen] = useState(false);
  const [captureState, setCaptureState] = useState("idle");
  const [snapshot, setSnapshot] = useState(null);
  const [description, setDescription] = useState("");
  const [decision, setDecision] = useState("");
  const [reason, setReason] = useState("");
  const [includeSourceImage, setIncludeSourceImage] = useState(false);
  const [includeResultImage, setIncludeResultImage] = useState(false);
  const [files, setFiles] = useState([]);
  const [result, setResult] = useState(null);
  const [download, setDownload] = useState(null);
  const [generationState, setGenerationState] = useState("idle");
  const [generationFailure, setGenerationFailure] = useState(null);

  useEffect(() => () => {
    if (download?.url) URL.revokeObjectURL(download.url);
  }, [download]);

  const beginFeedback = async () => {
    setOpen(true);
    setCaptureState("loading");
    setSnapshot(null);
    setResult(null);
    setGenerationState("idle");
    setGenerationFailure(null);
    const explicitTarget = normalizeFeedbackTarget(
      feedbackTarget || (taskId ? { feature_key: sourceFeature, task_id: taskId, route, stage } : null),
    );
    const resolvedTarget = resolveFeedbackTarget(explicitTarget, currentFeedbackTarget, sourceFeature);
    const frozen = await captureFeedbackContext({
      taskId: resolvedTarget?.task_id || taskId,
      sourceFeature: resolvedTarget?.feature_key || sourceFeature,
      stage: resolvedTarget?.stage || stage,
      route: resolvedTarget?.route || route,
      feedbackTarget: resolvedTarget,
    });
    setSnapshot(frozen);
    setCaptureState("ready");
  };

  const closeFeedback = () => {
    setOpen(false);
    setCaptureState("idle");
    setSnapshot(null);
    setDescription("");
    setDecision("");
    setReason("");
    setIncludeSourceImage(false);
    setIncludeResultImage(false);
    setFiles([]);
    setResult(null);
    setGenerationState("idle");
    setGenerationFailure(null);
    setDownload((current) => {
      if (current?.url) URL.revokeObjectURL(current.url);
      return null;
    });
  };

  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === "Escape") closeFeedback();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  const generate = async () => {
    if (
      !snapshot
      || !description.trim()
      || !decision
      || (decision !== "ACCEPTED" && !reason)
      || generationState === "generating"
    ) return;
    setGenerationState("generating");
    setGenerationFailure(null);
    setResult(null);
    setDownload((current) => {
      if (current?.url) URL.revokeObjectURL(current.url);
      return null;
    });
    try {
      const generated = await generateUnifiedFeedbackBundle({
        snapshot,
        description,
        files,
        evaluation: { decision, reasons: reason ? [reason] : [] },
        evidenceConsent: {
          include_source_image: includeSourceImage,
          include_result_image: includeResultImage,
        },
      });
      const nextDownload = await feedbackBundleDownload(generated);
      if (!generated?.payload?.feedback_identity?.feedback_bundle_id || !nextDownload?.url || !nextDownload?.sizeBytes) {
        if (nextDownload?.url) URL.revokeObjectURL(nextDownload.url);
        throw new Error("反馈包数据不完整，未生成可下载文件。");
      }
      setDownload((current) => {
        if (current?.url) URL.revokeObjectURL(current.url);
        return nextDownload;
      });
      setResult(generated);
      setGenerationState("success");
    } catch (error) {
      const errorId = error?.error_id || error?.errorId || snapshot?.context?.error?.error_id || "";
      setGenerationFailure({
        reason: sanitizeFeedbackText(error?.message || "未能创建本地反馈包。", 300),
        errorId: errorId && errorId !== "unavailable" ? sanitizeFeedbackText(errorId, 120) : "",
      });
      setGenerationState("failed");
    }
  };

  const preview = snapshot?.preview || {};
  const payload = result?.payload || null;
  const errorId = payload?.common_context?.error_id || preview.error_id || "";

  return (
    <>
      <button type="button" className={triggerClassName} data-testid={testId} onClick={beginFeedback} disabled={disabled}>
        {triggerLabel}
      </button>
      {open ? (
        <div className="hdde-feedback-overlay" role="presentation">
          <section className="hdde-feedback-dialog" role="dialog" aria-modal="true" aria-labelledby="hdde-feedback-title" data-testid="unified-feedback-dialog">
            <header>
              <div>
                <p className="hdde-eyebrow">问题反馈</p>
                <h2 id="hdde-feedback-title">告诉我们发生了什么</h2>
                <p>版本、运行与任务诊断事实由系统自动整理；无需填写技术编号。</p>
              </div>
              <button type="button" className="hdde-feedback-close" aria-label="关闭问题反馈" onClick={closeFeedback}><HddeIcon name="close" size={18} /></button>
            </header>

            {captureState === "loading" ? <p role="status">正在冻结当前反馈上下文…</p> : null}

            <label className="hdde-feedback-field" htmlFor={`${testId}-description`}>
              <span>问题描述</span>
              <textarea
                id={`${testId}-description`}
                data-testid="unified-feedback-description"
                maxLength="1000"
                required
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="请描述：我做了什么、发生了什么、我预期应该怎样"
              />
              <small>请勿填写客户名称、完整路径或其他隐私信息。</small>
            </label>

            <fieldset className="hdde-feedback-field hdde-feedback-evaluation" data-testid="unified-feedback-evaluation">
              <legend>这次处理结果可以直接使用吗？</legend>
              <div className="hdde-feedback-choice-grid">
                {DECISION_OPTIONS.map(([value, label]) => (
                  <label key={value} className="hdde-feedback-choice">
                    <input
                      type="radio"
                      name={`${testId}-decision`}
                      value={value}
                      checked={decision === value}
                      onChange={() => {
                        setDecision(value);
                        if (value === "ACCEPTED") setReason("");
                      }}
                    />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            {decision && decision !== "ACCEPTED" ? (
              <label className="hdde-feedback-field" htmlFor={`${testId}-reason`}>
                <span>主要问题原因</span>
                <select
                  id={`${testId}-reason`}
                  data-testid="unified-feedback-reason"
                  required
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                >
                  <option value="">请选择一个最主要的原因</option>
                  {REASON_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
            ) : null}

            <fieldset className="hdde-feedback-field hdde-feedback-evidence" data-testid="unified-feedback-evidence">
              <legend>图片证据（可选）</legend>
              <p>默认不包含图片。仅在你主动勾选后，系统才会尝试把当前任务对应图片复制进反馈包。</p>
              <label className="hdde-feedback-checkbox">
                <input
                  type="checkbox"
                  checked={includeResultImage}
                  onChange={(event) => setIncludeResultImage(event.target.checked)}
                  data-testid="unified-feedback-include-result"
                />
                <span>附加当前结果图</span>
              </label>
              <label className="hdde-feedback-checkbox">
                <input
                  type="checkbox"
                  checked={includeSourceImage}
                  onChange={(event) => setIncludeSourceImage(event.target.checked)}
                  data-testid="unified-feedback-include-source"
                />
                <span>附加当前原图</span>
              </label>
            </fieldset>

            <label className="hdde-feedback-field hdde-feedback-attachment-field" htmlFor={`${testId}-attachments`}>
              <span>附件（可选）</span>
              <span className="hdde-feedback-upload">
                <strong>选择本地文件</strong>
                <small>最多 10 个，仅记录类型和体积</small>
                <input
                  id={`${testId}-attachments`}
                  className="hdde-feedback-file-input"
                  data-testid="unified-feedback-attachments"
                  type="file"
                  multiple
                  onChange={(event) => setFiles(Array.from(event.target.files || []).slice(0, 10))}
                />
              </span>
              <small>附件不会自动加入反馈包或上传；仅记录你主动选择的文件类型和体积。</small>
            </label>
            {files.length ? <ul className="hdde-feedback-attachments" aria-label="已主动选择的附件">
              {files.map((file, index) => <li key={`${index}-${file.size}`}>附件 {index + 1} · {formatBytes(file.size)}</li>)}
            </ul> : null}

            {snapshot ? (
              <details className="hdde-feedback-context" data-testid="unified-feedback-context">
                <summary><span>系统已整理的辅助信息</span><small>版本、任务状态与必要诊断事实</small></summary>
                <dl className="hdde-feedback-context-preview" aria-label="反馈上下文预览">
                  <div><dt>问题来源</dt><dd>{preview.feature_name || "当前功能"}</dd></div>
                  <div><dt>发生阶段</dt><dd>{preview.stage || "不可用"}</dd></div>
                  <div><dt>当前状态</dt><dd>{preview.status || "不可用"}</dd></div>
                  <div><dt>运行环境</dt><dd>{preview.app_version || "不可用"} · 后端{snapshot.mode === "backend" ? "已连接" : "不可达"}</dd></div>
                  <div><dt>诊断事实</dt><dd>{preview.task_reference_available ? "已关联当前任务" : "Runtime级反馈，不猜测任务"}{errorId && errorId !== "unavailable" ? ` · 错误编号 ${errorId}` : ""}</dd></div>
                </dl>
              </details>
            ) : null}

            {payload ? (
              <dl className="hdde-feedback-bundle-preview" data-testid="unified-feedback-preview" aria-label="标准反馈包预览">
                <div><dt>反馈包编号</dt><dd>{payload.feedback_identity?.feedback_bundle_id}</dd></div>
                <div><dt>合同版本</dt><dd>{payload.feedback_identity?.schema_version}</dd></div>
                <div><dt>诊断内容</dt><dd>版本与运行身份、冻结上下文、有限相关事件、异常摘要、安全输入元数据</dd></div>
                <div><dt>隐私保护</dt><dd>图片仅按本次明确勾选授权加入；不含 Settings、完整日志或未经脱敏绝对路径</dd></div>
                <div><dt>图片证据</dt><dd>{payload.image_evidence?.status || "未请求"}</dd></div>
              </dl>
            ) : null}

            {generationState !== "idle" ? (
              <section
                className="hdde-feedback-generation-result"
                data-state={generationState}
                data-testid="unified-feedback-generation-status"
                role={generationState === "failed" ? "alert" : "status"}
                aria-live="polite"
              >
                {generationState === "generating" ? (
                  <>
                    <strong>正在生成反馈包</strong>
                    <p>正在整理脱敏诊断信息并创建本地文件，请稍候。</p>
                  </>
                ) : null}
                {generationState === "success" ? (
                  <>
                    <strong>反馈包已生成</strong>
                    <p>{result?.mode === "offline"
                      ? "后端当前不可达，已使用本地安全模式生成反馈包。"
                      : "标准反馈包已生成，请确认后下载并发送。"}</p>
                    <dl aria-label="已生成反馈包文件信息">
                      <div><dt>安全文件</dt><dd>{download?.fileName}</dd></div>
                      <div><dt>文件大小</dt><dd>{formatBytes(download?.sizeBytes)}</dd></div>
                    </dl>
                  </>
                ) : null}
                {generationState === "failed" ? (
                  <>
                    <strong>反馈包生成失败</strong>
                    <p>{generationFailure?.reason || "未能创建本地反馈包。"}</p>
                    {generationFailure?.errorId ? <p>ERROR_ID：{generationFailure.errorId}</p> : null}
                    <small>请检查问题描述后重新生成。</small>
                  </>
                ) : null}
              </section>
            ) : null}

            <footer>
              <button
                type="button"
                className={download ? "hdde-secondary-action" : "hdde-primary-action"}
                data-testid="unified-feedback-generate"
                disabled={
                  !snapshot
                  || !description.trim()
                  || !decision
                  || (decision !== "ACCEPTED" && !reason)
                  || generationState === "generating"
                }
                aria-busy={generationState === "generating"}
                onClick={generate}
              >
                {generationState === "generating"
                  ? "正在生成…"
                  : generationState === "failed" || download ? "重新生成" : "生成反馈包"}
              </button>
              {download ? <a className="hdde-primary-action" data-testid="unified-feedback-download" href={download.url} download={download.fileName}>下载反馈包</a> : null}
            </footer>
            <small className="hdde-feedback-auto-upload">不会自动上传。是否下载和发送完全由你决定。</small>
          </section>
        </div>
      ) : null}
    </>
  );
}
