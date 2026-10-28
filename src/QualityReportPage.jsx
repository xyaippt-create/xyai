import React, { useMemo, useState } from "react";
import { resolveDeliveryStatus, resolveReportCenterMeta } from "./deliveryStatus.js";
import { getFileDisplayName } from "./fileDisplayName.js";
import { resolve1080pSizeTreatment } from "./sizeTreatment.js";
import { HddeResultHero, HddeTechnicalDetails } from "./HddeUI.jsx";
import { resultConclusionFromDelivery } from "./productDisplay.js";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

function getReport(taskConfig) {
  const report = taskConfig?.task_report || taskConfig?.compareAssets?.task_report || {};
  const result = taskConfig?.task_result || taskConfig?.compareAssets?.task_result || {};
  const debugQuality =
    taskConfig?.debug_quality ||
    taskConfig?.task_result?.debug_quality ||
    taskConfig?.compareAssets?.task_result?.debug_quality ||
    {};
  return { ...debugQuality, ...result, ...report };
}

function getResult(taskConfig) {
  return taskConfig?.task_result || taskConfig?.compareAssets?.task_result || {};
}

function score(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function scoreText(value) {
  const number = score(value);
  return number == null ? "暂无" : number.toFixed(2);
}

function reviewDetailText(value) {
  return String(value || "")
    .replace(/\b(?:text_clarity_score|texture_score|edge_quality_score)=/gi, "评分 ")
    .replace(/\bRC\d+[A-Z0-9-]*\b/gi, "当前交付规则");
}

function normalizeList(value) {
  if (Array.isArray(value)) {
    return value
      .filter(Boolean)
      .map((item) => (typeof item === "string" ? item : item.label || item.detail || ""))
      .filter(Boolean);
  }
  if (typeof value === "string" && value.trim()) return [value.trim()];
  return [];
}

function feedbackErrorMessage(payload, status) {
  const detail = payload?.detail;
  if (detail && typeof detail === "object") return detail.message || detail.reason || `反馈包生成失败（HTTP ${status}）。`;
  return payload?.message || detail || `反馈包生成失败（HTTP ${status}）。`;
}

function ScoreCard({ label, value }) {
  const number = score(value);
  const width = number == null ? 0 : Math.max(0, Math.min(100, number));
  return (
    <article className="hdde-report-score-card">
      <div>
        <span>{label}</span>
        <strong>{scoreText(value)}</strong>
      </div>
      <div className="hdde-report-score-meter" aria-label={`${label} ${scoreText(value)}`}>
        <span style={{ width: `${width}%` }} />
      </div>
    </article>
  );
}

function ReportList({ title, items, tone = "neutral" }) {
  if (!items.length) return null;
  return (
    <section className="hdde-report-list" data-tone={tone}>
      <h3>{title}</h3>
      <ul>
        {items.map((item, index) => <li key={`${title}-${index}`}>{item}</li>)}
      </ul>
    </section>
  );
}

function resolvePositiveSignals(report, meta) {
  const explicit = normalizeList(report?.positive_signals);
  if (explicit.length) return explicit;
  const signals = ["已完成 1080P 本地输出"];
  if (score(report.color_fidelity_score) >= 95) signals.push("色彩忠实度较高");
  if (report.final_output_url || report.final_output_filename || report.output_filename) signals.push("输出文件已生成，可进入本地查看");
  return signals;
}

function resolveSuggestedUsage(report, meta) {
  const explicit = normalizeList(report?.suggested_usage);
  if (explicit.length) return explicit.join("；");
  if (meta.delivery.status === "FAIL") {
    return "当前不建议直接用于正式交付。请返回对比页面检查文字、Logo、边缘与颜色后再决定是否重新处理。";
  }
  if (meta.benefit.label === "低收益提示") {
    return "增强收益有限，建议在对比页面检查原图与输出图后决定是否采用。";
  }
  return "适合本地预览、PPT草案与方案初稿；正式使用前请检查文字、Logo、主体边缘、颜色和低频平滑区域。";
}

export default function QualityReportPage({ taskConfig, onBackToCompare, onArchive }) {
  const report = useMemo(() => getReport(taskConfig), [taskConfig]);
  const result = useMemo(() => getResult(taskConfig), [taskConfig]);
  const isFourK = (taskConfig?.mode || result.mode) === "4k_v1";
  const delivery = useMemo(
    () => resolveDeliveryStatus(report, result, report, taskConfig || {}),
    [report, result, taskConfig],
  );
  const reportMeta = useMemo(() => resolveReportCenterMeta(report), [report]);
  const positiveSignals = useMemo(() => resolvePositiveSignals(report, reportMeta), [report, reportMeta]);
  const suggestedUsage = useMemo(() => resolveSuggestedUsage(report, reportMeta), [report, reportMeta]);
  const fileName = result.output_filename || result.input_filename || taskConfig?.fileName || "等待真实任务";
  const fileDisplayName = getFileDisplayName(fileName, "等待真实任务");
  const outputPath =
    result.output_path ||
    result.final_output_path ||
    taskConfig?.output_path ||
    taskConfig?.compareAssets?.output_path ||
    "";
  const outputDirectory = outputPath.replace(/[\\/][^\\/]+$/, "");
  const [operationMessage, setOperationMessage] = useState("");

  const scores = [
    ["清晰度", report.clarity_score],
    ["文字清晰度", report.text_clarity_score],
    ["边缘质量", report.edge_quality_score],
    ["色彩忠实度", report.color_fidelity_score],
    ["纹理保持度", report.texture_score],
    ["综合交付分", report.delivery_score],
  ];
  const visibleScores = scores.filter(([, value]) => score(value) != null);
  const inputDimensions = result.input_width && result.input_height ? `${result.input_width} × ${result.input_height}` : "";
  const outputDimensions = result.output_width && result.output_height ? `${result.output_width} × ${result.output_height}` : "";
  const sizeTreatment = isFourK
    ? {
        label: result.processing_disposition === "NO_PROCESSING_NEEDED" ? "已达到4K门槛" : "4K成品已生成",
        detail: result.processing_disposition === "NO_PROCESSING_NEEDED"
          ? "原图长边已达到3840像素，未执行像素放大。"
          : "保持原图比例，长边已提升至3840像素并完成超分细节增强。",
      }
    : resolve1080pSizeTreatment({
        inputWidth: result.input_width,
        inputHeight: result.input_height,
        outputWidth: result.output_width,
        outputHeight: result.output_height,
        modeLabel: "1080P画质",
      });
  const dimensionSummary = [
    inputDimensions ? `输入 ${inputDimensions}` : "",
    outputDimensions ? `输出 ${outputDimensions}` : "",
  ].filter(Boolean).join(" · ");
  const outputFileName = result.output_filename || "";
  const outputFileDisplayName = getFileDisplayName(outputFileName);
  const outputFacts = [
    inputDimensions ? ["输入尺寸", inputDimensions, ""] : null,
    outputDimensions ? ["输出尺寸", outputDimensions, ""] : null,
    sizeTreatment ? ["尺寸处理", sizeTreatment.label, sizeTreatment.detail] : null,
    result.output_format ? ["输出格式", String(result.output_format).toUpperCase(), ""] : null,
    outputFileName ? ["输出文件", outputFileDisplayName, outputFileName] : null,
  ].filter(Boolean);
  const conclusion = resultConclusionFromDelivery(
    isFourK ? (result.final_output_exists ? "PASS" : "PASS_WITH_LIMITATION") : delivery.status,
    { improved: !isFourK },
  );

  const openOutputFolder = async () => {
    if (!outputDirectory) {
      setOperationMessage("当前没有可打开的输出文件夹。");
      return;
    }
    try {
      const response = await fetch(`${API_BASE}/api/output/open`, {
        method: "POST",
        headers: { "Content-Type": "application/json;charset=UTF-8" },
        body: JSON.stringify({ output_dir: outputDirectory }),
      });
      const payload = await response.json();
      if (!response.ok || payload?.success === false) throw new Error(feedbackErrorMessage(payload, response.status));
      setOperationMessage(payload.message || "已打开输出文件夹。");
    } catch (error) {
      setOperationMessage(error.message || "无法打开输出文件夹。");
    }
  };

  const copyOutputPath = async () => {
    if (!outputPath) {
      setOperationMessage("当前没有可复制的成品路径。");
      return;
    }
    try {
      await navigator.clipboard.writeText(outputPath);
      setOperationMessage("成品路径已复制。");
    } catch (error) {
      setOperationMessage(error.message || "复制成品路径失败。");
    }
  };

  return (
    <section className="hdde-report-page" data-testid="quality-report-page">
      <header className="hdde-report-header">
        <div className="hdde-report-heading">
          <p className="hdde-eyebrow">{isFourK ? "4K处理报告" : "质量报告"}</p>
          <h1>{isFourK ? "4K处理报告" : "高清交付评估"}</h1>
          <p title={fileName}>{fileDisplayName}</p>
        </div>
        <div className="hdde-report-actions">
          <button type="button" className="hdde-report-button hdde-report-button--secondary" onClick={onBackToCompare}>
            返回对比结果
          </button>
        </div>
      </header>

      <HddeResultHero
        conclusion={conclusion.label}
        tone={conclusion.tone}
        title={isFourK ? (result.final_output_exists ? "4K成品已生成" : "无需重复放大") : delivery.label}
        summary={isFourK ? "已保持原图比例完成4K画质增强；该结论不代表凭空重建细节。" : delivery.description}
        changes={[dimensionSummary || "处理前后信息已记录"]}
        protections={[isFourK && report.source_hash_unchanged ? "原图完整性已确认" : "原图未覆盖", "文字、Logo、颜色与结构需在对比页确认"]}
        nextAction={conclusion.nextAction}
      />

      <div className="hdde-report-layout">
        <div className="hdde-report-main">
          {isFourK ? (
            <section className="hdde-report-panel">
              <div className="hdde-report-section-heading">
                <div>
                  <p className="hdde-eyebrow">处理摘要</p>
                  <h2>4K画质增强报告</h2>
                </div>
                {dimensionSummary ? <span>{dimensionSummary}</span> : null}
              </div>
              <dl className="hdde-report-facts">
                <div><dt>比例策略</dt><dd>保持原图比例</dd></div>
                <div><dt>原图完整性</dt><dd>{report.source_hash_unchanged ? "已确认" : "需要复核"}</dd></div>
              </dl>
            </section>
          ) : (
          <HddeTechnicalDetails summary="查看技术评分" className="hdde-report-panel">
            <p className="hdde-technical-note">评分仅用于诊断，没有统一量表解释，不作为用户层质量结论。</p>
            <div className="hdde-report-score-grid">{visibleScores.map(([label, value]) => <ScoreCard key={label} label={label} value={value} />)}</div>
          </HddeTechnicalDetails>
          )}

          <section className="hdde-report-panel">
            <div className="hdde-report-section-heading">
              <div>
                <p className="hdde-eyebrow">输出结果</p>
                <h2>交付文件</h2>
              </div>
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
        </div>

        <aside className="hdde-report-side">
          <section className="hdde-report-panel hdde-report-verdict">
            <p className="hdde-eyebrow">交付结论</p>
            <div className="hdde-report-verdict-line">
              <h2>{isFourK ? (result.final_output_exists ? "4K成品已生成" : "无需重复放大") : delivery.label}</h2>
              <span data-tone={isFourK ? "positive" : delivery.status === "PASS" ? "positive" : delivery.status === "FAIL" ? "negative" : "warning"}>
                {isFourK ? "尺寸核对完成" : delivery.badge}
              </span>
            </div>
            <p>{isFourK ? "将图片高质量适配至4K尺寸，保持原图比例与内容完整。" : delivery.description}</p>
          </section>

          <ReportList
            title="复核重点"
            items={isFourK
              ? ["检查主体、文字与Logo是否完整", "检查画面比例是否正确且没有拉伸", "检查透明边缘、颜色与渐变显示是否正常"]
              : reportMeta.reviewReasons.map((item) => `${item.label}：${reviewDetailText(item.detail)}`)}
            tone="warning"
          />

          <section className="hdde-report-panel hdde-report-archive">
            <h2>结果操作</h2>
            <p>文件位置不会直接显示在报告中，可通过以下操作获取。</p>
            {operationMessage ? <p role="status">{operationMessage}</p> : null}
            <button type="button" className="hdde-report-button hdde-report-button--primary" disabled={!outputDirectory} onClick={openOutputFolder}>
              打开输出文件夹
            </button>
            <button type="button" className="hdde-report-button hdde-report-button--secondary" disabled={!outputPath} onClick={copyOutputPath}>
              复制成品路径
            </button>
            <button type="button" className="hdde-report-button hdde-report-button--secondary" onClick={onArchive}>
              {isFourK ? "完成复核并返回4K画质增强" : "完成复核并返回"}
            </button>
          </section>

          {!isFourK ? <ReportList title="正向信号" items={positiveSignals} tone="positive" /> : null}

          <section className="hdde-report-panel">
            <p className="hdde-eyebrow">{isFourK ? "能力边界" : "建议用途"}</p>
            <h2>{isFourK ? "4K超分细节增强" : "交付建议"}</h2>
            <p className="hdde-report-usage">
              {isFourK
                ? "保持原图比例与构图，长边提升至3840像素：超分重建细节，并以原图保真融合，防止色偏、重绘与过锐光晕。"
                : suggestedUsage}
            </p>
          </section>
        </aside>
      </div>
    </section>
  );
}
