import React, { useMemo } from "react";
import { resolveDeliveryStatus } from "./deliveryStatus.js";

function getReport(taskConfig) {
  const report = taskConfig?.task_report || taskConfig?.compareAssets?.task_report || {};
  const result = taskConfig?.task_result || taskConfig?.compareAssets?.task_result || {};
  const debugQuality = taskConfig?.debug_quality || taskConfig?.task_result?.debug_quality || taskConfig?.compareAssets?.task_result?.debug_quality || {};
  return { ...debugQuality, ...result, ...report };
}

function getResult(taskConfig) {
  return taskConfig?.task_result || taskConfig?.compareAssets?.task_result || {};
}

function display(value, fallback = "暂无数据") {
  if (value == null || value === "") return fallback;
  return value;
}

function boolText(value) {
  if (value === true) return "是";
  if (value === false) return "否";
  return "暂无数据";
}

function numberText(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "暂无";
  return number.toFixed(2);
}

function MetricRow({ label, value }) {
  return (
    <div className="flex items-center gap-3 border-b border-dashed border-[#1c1f26] py-2 text-xs">
      <span className="w-24 shrink-0 text-[#64748b]">{label}</span>
      <span className="min-w-0 flex-1 truncate text-right font-mono text-[#94a3b8]" title={String(display(value))}>
        {display(value)}
      </span>
    </div>
  );
}

function ScoreCompareBar({ label, keyName, enhanced }) {
  const number = typeof enhanced === "number" ? enhanced : null;
  const width = number === null ? 16 : Math.max(4, Math.min(100, number));
  const isDelivery = keyName === "delivery_score";
  const isTexture = keyName === "texture_score";
  const unit = isDelivery ? "分" : isTexture ? "阶" : "";
  const valueColor = isDelivery ? "text-[#00ffcc]" : isTexture ? "text-[#10b981]" : "text-[#8effed]";
  const valueSize = isDelivery ? "text-xl" : "text-lg";
  return (
    <div className="rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/70 p-3">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-[13px] font-medium text-[#e2e8f0]">{label}</p>
          <p className="mt-0.5 truncate font-mono text-[9px] uppercase tracking-[0.2em] text-[#475569]" title={keyName}>{keyName}</p>
        </div>
        <span className={`shrink-0 font-mono ${valueSize} font-bold tracking-tight ${valueColor}`}>
          {numberText(enhanced)} {unit ? <span className="font-sans text-xs font-normal text-[#64748b]">{unit}</span> : null}
        </span>
      </div>
      <div className="relative h-2 overflow-hidden rounded-sm border border-[#1c1f26] bg-black/35">
        <div className="absolute inset-y-0 left-0 bg-[#3f6f68]" style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

function PseudoHDWarning({ report }) {
  const pseudoRisk = report.pseudo_hd_risk == null ? "安全" : report.pseudo_hd_risk;
  const artifactRisk = report.artifact_risk || "低风险";
  const deliveryMeta = resolveDeliveryStatus(report);

  return (
    <section className="shrink-0 rounded-sm border border-[#1c1f26] bg-[#121418] p-4">
      <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Delivery Certification</p>
      <h2 className="mt-2 text-lg font-semibold text-white">高清影像交付评估</h2>
      <div className="mt-4 rounded-sm border border-[#3cb3a0]/25 bg-[#040708]/55 p-4">
        <p className="text-base font-semibold" style={{ color: deliveryMeta.tone }}>最终交付：{deliveryMeta.label}</p>
        <p className="mt-2 text-xs leading-6 text-white/52">
          {deliveryMeta.description} 当前报告只记录 V0.4.6 1080P 本地交付结果，不声明重绘或生成能力。
        </p>
      </div>
      <div className="mt-4 grid font-mono text-xs">
        <MetricRow label="交付原因" value={report.final_delivery_reason} />
        <MetricRow label="风险等级" value={report.final_delivery_risk_level} />
        <MetricRow label="建议用途" value={report.final_delivery_recommended_usage} />
        <MetricRow label="伪高清风险提示" value={pseudoRisk} />
        <MetricRow label="伪影伪作风险" value={artifactRisk} />
        <MetricRow label="编码提示" value={report.encoding_warning || "暂无数据"} />
      </div>
    </section>
  );
}

function ArchiveSignature({ onArchive }) {
  return (
    <section className="mt-auto flex shrink-0 flex-col gap-3 rounded-sm border border-[#1c1f26] bg-[#121418] p-4">
      <div>
        <span className="block font-mono text-[10px] uppercase tracking-wider text-[#64748b]">Final Signature</span>
        <h2 className="mt-1 text-sm font-medium text-white">终审签署归档</h2>
        <p className="mt-1 text-xs leading-relaxed text-[#94a3b8]">
          签署后视为本次高清影像交付评估完成。系统将清空当前任务上下文，并返回工作台。
        </p>
      </div>
      <button type="button" onClick={onArchive} className="w-full rounded-sm bg-[#10b981] py-2.5 text-xs font-bold tracking-wider text-[#0b0c0e] shadow-md transition-colors hover:bg-[#059669]">
        签署交付评估 · 归档成品
      </button>
    </section>
  );
}

export default function QualityReportPage({ taskConfig, onBackToCompare, onArchive }) {
  const report = useMemo(() => getReport(taskConfig), [taskConfig]);
  const result = useMemo(() => getResult(taskConfig), [taskConfig]);
  const fileName = result.output_filename || result.input_filename || taskConfig?.fileName || taskConfig?.compareAssets?.fileName || "等待真实任务";

  const scores = [
    ["清晰度评分", "clarity_score", report.clarity_score],
    ["文本清晰度", "text_clarity_score", report.text_clarity_score],
    ["边缘质量分", "edge_quality_score", report.edge_quality_score],
    ["色彩忠实度", "color_fidelity_score", report.color_fidelity_score],
    ["纹理保持力", "texture_score", report.texture_score],
    ["综合交付分值", "delivery_score", report.delivery_score || "计算中"],
  ];

  return (
    <div className="flex h-full w-full flex-row gap-4 overflow-hidden bg-[#0b0c0e] p-4 text-slate-100 select-none">
      <div className="scrollbar-none flex h-full min-w-0 flex-1 flex-col gap-3 overflow-y-auto pr-1">
        <header className="shrink-0 rounded-sm border border-[#1c1f26] bg-[#121418] p-4">
          <div className="flex items-baseline justify-between gap-5">
            <h1 className="shrink-0 text-xl font-bold tracking-wider text-white">质量报告终审</h1>
            <span className="truncate font-serif text-[10px] uppercase tracking-widest text-[#475569]">
              SNOWFIELD GRAPHICS COMPLIANCE AUDIT
            </span>
          </div>
          <p className="mt-2 truncate font-mono text-[11px] text-[#475569]" title={fileName}>
            资产特征值：{fileName || "未命名交付样本"}
          </p>
          <button type="button" onClick={onBackToCompare} className="mt-3 rounded-sm border border-[#333] bg-[#1c1f26] px-3 py-1.5 text-xs text-[#94a3b8] transition-colors hover:bg-[#2d3139] hover:text-white">
            ← 返回滑块对比
          </button>
        </header>

        <section className="shrink-0 space-y-4 rounded-sm border border-[#1c1f26] bg-[#121418] p-4">
          <div className="flex items-end justify-between gap-4">
            <div>
              <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Score Overlay</p>
              <h2 className="mt-2 text-lg font-semibold text-white">核心质量指标</h2>
            </div>
            <div className="text-right font-mono text-xs leading-6 text-white/40">
              <p>输入：{display(result.input_width)} × {display(result.input_height)}</p>
              <p>输出：{display(result.output_width)} × {display(result.output_height)}</p>
            </div>
          </div>
            <div className="grid gap-4">
              {scores.map(([label, keyName, value]) => (
                <ScoreCompareBar key={keyName} label={label} keyName={keyName} enhanced={value} />
              ))}
            </div>
        </section>

        <section className="shrink-0 rounded-sm border border-[#1c1f26] bg-[#121418] p-4">
            <div className="grid grid-cols-2 gap-x-6 gap-y-3 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/30 p-4">
              {[
                { label: "尺寸策略", value: result.resize_policy, isLong: true },
                { label: "输出格式", value: result.output_format?.toUpperCase(), isLong: false },
                { label: "执行像素提升", value: boolText(result.was_upscaled), isLong: false },
                { label: "触发防跳跃降采样", value: boolText(result.was_downscaled), isLong: false },
                { label: "输出是否空变化", value: boolText(result.output_changed), isLong: false },
                { label: "哈希是否相同", value: boolText(result.hash_equal), isLong: false },
              ].map((param) => (
                <div key={param.label} className="flex min-h-[24px] w-full items-center">
                  <span className="min-w-[100px] shrink-0 text-left text-xs text-[#64748b]">{param.label}</span>
                  <div className="mx-2 h-3 flex-1 border-b border-dashed border-[#1c1f26]" />
                  <span className="shrink-0 truncate text-right font-mono text-xs max-w-[240px] text-[#00ffcc]" title={String(param.value || "暂无数据")}>
                    {param.value || "暂无数据"}
                  </span>
                </div>
              ))}
            </div>
        </section>
      </div>

      <aside className="flex h-full w-[320px] shrink-0 flex-col gap-3">
        <PseudoHDWarning report={report} />
        <ArchiveSignature onArchive={onArchive} />
      </aside>
    </div>
  );
}
