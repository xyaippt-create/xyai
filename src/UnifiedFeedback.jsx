import React, { useEffect, useState } from "react";
import {
  captureFeedbackContext,
  feedbackBundleDownload,
  generateUnifiedFeedbackBundle,
  sanitizeFeedbackText,
} from "./feedbackFlow.js";

function formatBytes(value) {
  const size = Number(value || 0);
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export default function UnifiedFeedback({
  taskId = "",
  sourceFeature = "runtime_failure",
  stage = "",
  triggerLabel = "反馈问题",
  triggerClassName = "",
  testId = "unified-feedback-trigger",
  disabled = false,
}) {
  const [open, setOpen] = useState(false);
  const [captureState, setCaptureState] = useState("idle");
  const [snapshot, setSnapshot] = useState(null);
  const [description, setDescription] = useState("");
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
    const frozen = await captureFeedbackContext({ taskId, sourceFeature, stage });
    setSnapshot(frozen);
    setCaptureState("ready");
  };

  const closeFeedback = () => {
    setOpen(false);
    setCaptureState("idle");
    setSnapshot(null);
    setDescription("");
    setFiles([]);
    setResult(null);
    setGenerationState("idle");
    setGenerationFailure(null);
    setDownload((current) => {
      if (current?.url) URL.revokeObjectURL(current.url);
      return null;
    });
  };

  const generate = async () => {
    if (!snapshot || !description.trim() || generationState === "generating") return;
    setGenerationState("generating");
    setGenerationFailure(null);
    setResult(null);
    setDownload((current) => {
      if (current?.url) URL.revokeObjectURL(current.url);
      return null;
    });
    try {
      const generated = await generateUnifiedFeedbackBundle({ snapshot, description, files });
      const nextDownload = feedbackBundleDownload(generated);
      if (!generated?.payload?.feedback_bundle_id || !nextDownload?.url || !nextDownload?.sizeBytes) {
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
  const errorId = payload?.context?.error?.error_id || preview.error_id || "";

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
              <button type="button" className="hdde-feedback-close" aria-label="关闭问题反馈" onClick={closeFeedback}>×</button>
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
                <div><dt>反馈包编号</dt><dd>{payload.feedback_bundle_id}</dd></div>
                <div><dt>合同版本</dt><dd>{payload.feedback_schema_version}</dd></div>
                <div><dt>诊断内容</dt><dd>版本与运行身份、冻结上下文、有限相关事件、异常摘要、安全输入元数据</dd></div>
                <div><dt>隐私保护</dt><dd>不含原图、结果文件、Settings、完整日志或未经脱敏绝对路径</dd></div>
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
                disabled={!snapshot || !description.trim() || generationState === "generating"}
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
