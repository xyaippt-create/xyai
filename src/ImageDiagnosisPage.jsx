import React, { useEffect, useMemo, useRef, useState } from "react";
import { HddePageHeader, HddeStatusPill } from "./HddeUI.jsx";
import UnifiedFeedback from "./UnifiedFeedback.jsx";


const API_BASE = "http://localhost:8787";
const ACCEPTED_TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/tiff", "image/bmp"]);

const ISSUE_LABELS = Object.freeze({
  resolution: "分辨率",
  blur: "清晰度",
  noise: "噪声",
  compression_artifacts: "压缩损伤",
  exposure: "整体曝光",
  highlight_clipping: "高光",
  shadow_blocking: "暗部",
  white_balance: "白平衡",
  color_cast: "整体色偏",
});

const STATUS_LABELS = Object.freeze({
  detected: "发现问题",
  not_detected: "未发现明显异常",
  indeterminate: "无法可靠判断",
  not_applicable: "当前格式不适用",
});

const SEVERITY_LABELS = Object.freeze({
  high: "严重",
  medium: "中等",
  low: "轻度",
  none: "正常",
  unknown: "待判断",
});

const DIAGNOSIS_STEPS = Object.freeze(["导入图片", "诊断结论", "推荐动作", "进入处理"]);

function apiUrl(value) {
  if (!value) return "";
  if (/^https?:\/\//i.test(value)) return value;
  return `${API_BASE}${value.startsWith("/") ? value : `/${value}`}`;
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function metricText(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/\.?0+$/, "");
  return String(value);
}

function issueTone(issue) {
  if (issue?.status === "detected") return issue?.severity === "high" ? "negative" : "warning";
  if (["indeterminate", "not_applicable"].includes(issue?.status)) return "neutral";
  return "positive";
}

function IssueRow({ issueKey, issue }) {
  return (
    <article className="hdde-diagnosis-issue" data-tone={issueTone(issue)}>
      <div className="hdde-diagnosis-issue-heading">
        <h3>{ISSUE_LABELS[issueKey] || issueKey}</h3>
        <span>{STATUS_LABELS[issue?.status] || "无法可靠判断"} · {SEVERITY_LABELS[issue?.severity] || "待判断"}</span>
      </div>
      <p>{issue?.reason || "当前没有可解释的判断依据。"}</p>
      {Array.isArray(issue?.evidence) && issue.evidence.length ? (
        <ul>{issue.evidence.map((item) => <li key={item}>{item}</li>)}</ul>
      ) : null}
    </article>
  );
}

export default function ImageDiagnosisPage({ onRecommendationAction, onTaskCompleted }) {
  const inputRef = useRef(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [state, setState] = useState("idle");
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const taskId = new URLSearchParams(window.location.search).get("task_id") || "";
    if (!taskId) return undefined;
    let active = true;
    setState("running");
    fetch(`${API_BASE}/api/image-diagnosis/tasks/${encodeURIComponent(taskId)}`)
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok || body?.success === false) throw new Error(body?.detail?.message || body?.detail || "图片诊断记录不可用。");
        if (!active) return;
        setPayload(body.data || null);
        setPreviewUrl(apiUrl(body.data?.source_preview_url));
        setState("success");
      })
      .catch((reason) => {
        if (!active) return;
        setError(reason.message || "图片诊断记录不可用。");
        setState("error");
      });
    return () => { active = false; };
  }, []);

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const result = payload?.result || null;
  const findings = result?.diagnosis_findings || {};
  const recommendation = result?.recommended_action || null;
  const facts = result?.image_facts || null;
  const issueEntries = useMemo(() => Object.entries(findings), [findings]);
  const primaryIssues = useMemo(
    () => issueEntries.filter(([, issue]) => issue?.status === "detected"),
    [issueEntries],
  );
  const workflowStep = state === "success" ? 4 : state === "running" ? 2 : selectedFile ? 1 : 0;

  const selectFile = (file) => {
    if (!file || (!ACCEPTED_TYPES.has(file.type) && !/\.(png|jpe?g|webp|tiff?|bmp)$/i.test(file.name))) {
      setError("请选择 PNG、JPG、JPEG、WebP、TIFF 或 BMP 图片。");
      return;
    }
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setSelectedFile(file);
    setPreviewUrl(URL.createObjectURL(file));
    setPayload(null);
    setState("ready");
    setError("");
  };

  const handleFileChange = (event) => {
    selectFile(event.currentTarget.files?.[0]);
    event.currentTarget.value = "";
  };

  const runDiagnosis = async () => {
    if (!selectedFile || state === "running") return;
    const formData = new FormData();
    formData.append("file", selectedFile, selectedFile.name);
    setState("running");
    setError("");
    setPayload(null);
    try {
      const response = await fetch(`${API_BASE}/api/image-diagnosis/tasks`, { method: "POST", body: formData });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || body?.success === false) {
        const detail = body?.detail;
        throw new Error((typeof detail === "object" ? detail?.message : detail) || body?.message || "图片诊断失败，请重试。");
      }
      setPayload(body.data || null);
      setState("success");
      if (typeof onTaskCompleted === "function") onTaskCompleted(body.data || null);
    } catch (reason) {
      setError(reason.message || "图片诊断失败，请重试。");
      setState("error");
    }
  };

  const chooseAgain = () => inputRef.current?.click();
  const runAgain = () => void runDiagnosis();
  const openAction = async (action) => {
    if (!action || action === "无需处理" || typeof onRecommendationAction !== "function") return;
    let sourceFile = selectedFile;
    if (!sourceFile && payload?.source_preview_url) {
      try {
        const response = await fetch(apiUrl(payload.source_preview_url));
        if (!response.ok) throw new Error("无法读取诊断源图片。");
        const blob = await response.blob();
        sourceFile = new File([blob], payload.source_display_name || "诊断图片", { type: blob.type || "application/octet-stream" });
      } catch (reason) {
        setError(reason.message || "无法带入诊断源图片，请重新选择图片。");
        return;
      }
    }
    onRecommendationAction({ action, sourceFile, taskId: payload?.task_id || "" });
  };

  return (
    <section className="hdde-diagnosis-page hdde-page-frame hdde-page-stack" data-testid="image-diagnosis-page">
      <input
        ref={inputRef}
        data-testid="image-diagnosis-file-input"
        type="file"
        accept=".png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp,image/png,image/jpeg,image/webp,image/tiff,image/bmp"
        hidden
        onChange={handleFileChange}
      />

      <HddePageHeader
        eyebrow="图像评估"
        title="图片诊断"
        description="先识别真实画质问题，再决定是否进入增强、校正或压缩流程。诊断不会修改原图。"
        meta={<HddeStatusPill tone="info">本地只读分析</HddeStatusPill>}
      />

      <ol className="hdde-diagnosis-workflow" aria-label="图片诊断流程">
        {DIAGNOSIS_STEPS.map((step, index) => {
          const stepNumber = index + 1;
          const stepState = stepNumber < workflowStep ? "complete" : stepNumber === workflowStep ? "current" : "pending";
          return <li key={step} data-state={stepState} aria-current={stepState === "current" ? "step" : undefined}><span>{stepNumber}</span><strong>{step}</strong></li>;
        })}
      </ol>

      <div className="hdde-diagnosis-layout" data-state={state}>
        <aside className="hdde-diagnosis-source" aria-label="诊断图片">
          <div className="hdde-diagnosis-source-heading">
            <div>
              <p className="hdde-eyebrow">诊断对象</p>
              <h2>{selectedFile?.name || "选择一张图片"}</h2>
            </div>
            {selectedFile ? <button type="button" className="hdde-secondary-action" onClick={chooseAgain}>重新选择</button> : null}
          </div>

          {previewUrl ? (
            <div className="hdde-diagnosis-preview">
              <img src={previewUrl} alt={`${selectedFile?.name || "当前图片"}预览`} data-testid="image-diagnosis-preview" />
            </div>
          ) : (
            <button type="button" className="hdde-diagnosis-empty" onClick={chooseAgain}>
              <strong>导入需要诊断的图片</strong>
              <span>支持 PNG、JPG、WebP、TIFF 与 BMP；诊断只读取图片，不修改原图。</span>
            </button>
          )}

          {selectedFile ? (
            <div className="hdde-diagnosis-source-meta">
              <span>{selectedFile.type || "图片文件"}</span>
              <span>{formatBytes(selectedFile.size)}</span>
              <span>本地只读诊断</span>
            </div>
          ) : null}

          <button
            type="button"
            className="hdde-primary-action hdde-diagnosis-run"
            disabled={!selectedFile || state === "running"}
            onClick={runDiagnosis}
            data-testid="image-diagnosis-run"
          >
            {state === "running" ? "正在分析图片…" : payload ? "重新诊断" : "开始诊断"}
          </button>
          {error ? <p className="hdde-diagnosis-error" role="alert">{error} <button type="button" onClick={runAgain}>重试</button></p> : null}
        </aside>

        <main className="hdde-diagnosis-result" aria-live="polite">
          {state === "idle" || state === "ready" ? (
            <section className="hdde-diagnosis-waiting">
              <p className="hdde-eyebrow">诊断工作台</p>
              <h2>{state === "ready" ? "图片已就绪" : "先了解问题，再选择处理方式"}</h2>
              <p>{state === "ready" ? "点击“开始诊断”，系统将读取真实图片事实并给出可解释建议。" : "导入图片后，这里会先给出结论与依据，再由你决定是否进入正式处理。"}</p>
              <div className="hdde-diagnosis-outcome-preview" aria-label="诊断输出预览">
                <div><span>01</span><strong>诊断结论</strong><small>主要问题、严重程度与判断依据</small></div>
                <div><span>02</span><strong>推荐动作</strong><small>首要建议与可选处理路径</small></div>
              </div>
              <small className="hdde-diagnosis-readonly-note">只读取图片事实，不自动修改原图，也不自动启动其他功能。</small>
            </section>
          ) : null}

          {state === "running" ? (
            <section className="hdde-diagnosis-analyzing" role="status" data-testid="image-diagnosis-analyzing">
              <span className="hdde-diagnosis-spinner" aria-hidden="true" />
              <div><p className="hdde-eyebrow">正在诊断</p><h2>正在读取真实图片指标</h2><p>诊断完成前不会创建处理结果或启动其他功能。</p></div>
            </section>
          ) : null}

          {state === "success" && result ? (
            <div className="hdde-diagnosis-complete" data-testid="image-diagnosis-result">
              <section className="hdde-diagnosis-verdict">
                <div>
                  <p className="hdde-eyebrow">诊断结论</p>
                  <h2>{primaryIssues.length ? `主要问题：${ISSUE_LABELS[primaryIssues[0][0]] || primaryIssues[0][0]}` : "主要指标未发现明确问题"}</h2>
                  <p>{recommendation?.reasons?.[0] || "诊断已完成。"}</p>
                </div>
                <span data-tone={primaryIssues.length ? "warning" : "positive"}>{primaryIssues.length ? `${primaryIssues.length} 项需关注` : "状态正常"}</span>
              </section>

              <section className="hdde-diagnosis-recommendation" aria-labelledby="diagnosis-recommendation-title">
                <div>
                  <p className="hdde-eyebrow">首要建议</p>
                  <h2 id="diagnosis-recommendation-title" data-testid="diagnosis-primary-action">{recommendation?.primary_action || "无法可靠判断"}</h2>
                  <p>{recommendation?.reasons?.[0] || "当前没有可用的推荐理由。"}</p>
                </div>
                {recommendation?.primary_action && recommendation.primary_action !== "无需处理" ? (
                  <button type="button" className="hdde-primary-action" onClick={() => void openAction(recommendation.primary_action)} data-testid="diagnosis-primary-action-button">
                    前往{recommendation.primary_action}
                  </button>
                ) : <span className="hdde-diagnosis-no-action">无需启动其他处理</span>}
              </section>

              {recommendation?.secondary_actions?.length ? (
                <section className="hdde-diagnosis-secondary-actions">
                  <h3>其他可选方案</h3>
                  <div>{recommendation.secondary_actions.map((action, index) => (
                    <button type="button" key={action} onClick={() => void openAction(action)}>
                      <span>{action}</span><small>{recommendation.reasons?.[index + 1] || "基于当前诊断结果"}</small>
                    </button>
                  ))}</div>
                </section>
              ) : null}

              <section className="hdde-diagnosis-findings" aria-labelledby="diagnosis-findings-title">
                <div className="hdde-diagnosis-section-heading">
                  <div><p className="hdde-eyebrow">关键问题</p><h2 id="diagnosis-findings-title">诊断依据</h2></div>
                  <span>结论来自冻结的 D1 诊断引擎</span>
                </div>
                <div className="hdde-diagnosis-issue-list">
                  {(primaryIssues.length ? primaryIssues : issueEntries).map(([key, issue]) => <IssueRow key={key} issueKey={key} issue={issue} />)}
                </div>
              </section>

              <section className="hdde-diagnosis-facts">
                <div className="hdde-diagnosis-section-heading"><div><p className="hdde-eyebrow">图片事实</p><h2>基础信息</h2></div></div>
                <dl>
                  <div><dt>尺寸</dt><dd>{facts?.width} × {facts?.height}</dd></div>
                  <div><dt>宽高比</dt><dd>{facts?.aspect_ratio_label || "—"}</dd></div>
                  <div><dt>格式</dt><dd>{facts?.format || "—"}</dd></div>
                  <div><dt>文件体积</dt><dd>{formatBytes(facts?.file_size_bytes)}</dd></div>
                  <div><dt>色彩模式</dt><dd>{facts?.color_mode || "—"}</dd></div>
                  <div><dt>透明通道</dt><dd>{facts?.has_alpha ? "存在" : "无"}</dd></div>
                  <div><dt>EXIF</dt><dd>{facts?.exif?.present ? `已读取 ${facts.exif.field_count} 项` : "未包含"}</dd></div>
                </dl>
              </section>

              <details className="hdde-diagnosis-technical">
                <summary>查看技术证据与指标</summary>
                <div>{issueEntries.map(([key, issue]) => (
                  <section key={key}>
                    <h3>{ISSUE_LABELS[key] || key}</h3>
                    <dl>{Object.entries(issue?.metrics || {}).map(([metric, value]) => <div key={metric}><dt>{metric}</dt><dd>{metricText(value)}</dd></div>)}</dl>
                  </section>
                ))}</div>
              </details>

              <div className="hdde-diagnosis-footer-actions">
                <button type="button" className="hdde-secondary-action" onClick={chooseAgain}>诊断其他图片</button>
                <button type="button" className="hdde-secondary-action" onClick={runAgain}>重新诊断当前图片</button>
                <UnifiedFeedback
                  sourceFeature="image_diagnosis"
                  taskId={payload?.task_id || ""}
                  triggerLabel="反馈诊断问题"
                  triggerClassName="hdde-secondary-action"
                />
              </div>
            </div>
          ) : null}
        </main>
      </div>
    </section>
  );
}
