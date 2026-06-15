import React, { useMemo } from "react";

const PAGE_FOOTER = "© 2026 雪原系统. 保留所有权利。 V0.4 1080P Stable Delivery Pipeline";

function getReport(taskConfig) {
  const report = taskConfig?.task_report || taskConfig?.compareAssets?.task_report || {};
  const debugQuality = taskConfig?.debug_quality || taskConfig?.task_result?.debug_quality || taskConfig?.compareAssets?.task_result?.debug_quality || {};
  return { ...debugQuality, ...report };
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

function GlacierAuditBackdrop() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_52%_0%,rgba(60,179,160,0.18),transparent_30rem),radial-gradient(circle_at_16%_18%,rgba(142,255,237,0.08),transparent_26rem),linear-gradient(180deg,#060b0c_0%,#07191f_42%,#02070a_100%)]" />
      <div className="absolute inset-y-0 left-0 w-[34rem] bg-[repeating-linear-gradient(180deg,rgba(142,255,237,0.06)_0px,transparent_1px,transparent_18px)] opacity-60" />
      <div className="absolute bottom-[-10rem] left-1/2 h-[26rem] w-[90vw] -translate-x-1/2 rounded-[50%] border-t border-[#3cb3a0]/20 bg-[radial-gradient(ellipse_at_top,rgba(60,179,160,0.12),rgba(3,16,20,0.06)_48%,transparent_70%)]" />
    </div>
  );
}

function MetricRow({ label, value }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-white/10 bg-[#0d181a] px-4 py-3 font-mono text-xs">
      <span className="text-slate-400">{label}</span>
      <span className="max-w-[55%] truncate text-right text-[#8effed]">{display(value)}</span>
    </div>
  );
}

function ScoreCompareBar({ label, keyName, enhanced }) {
  const number = typeof enhanced === "number" ? enhanced : null;
  const width = number === null ? 16 : Math.max(4, Math.min(100, number));
  return (
    <div className="rounded-lg border border-white/10 bg-[#0d181a] p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-white">{label}</p>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.28em] text-white/32">{keyName}</p>
        </div>
        <span className="rounded border border-[#3cb3a0]/30 bg-[#3cb3a0]/10 px-3 py-1 font-mono text-xs tracking-[0.16em] text-[#8effed]">
          {display(enhanced)}
        </span>
      </div>
      <div className="relative h-4 overflow-hidden rounded-full border border-white/10 bg-black/35">
        <div className="absolute inset-y-1 left-0 rounded-full bg-gradient-to-r from-[#3cb3a0]/80 to-[#8effed]/80" style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

function PseudoHDWarning({ report }) {
  const pseudoRisk = report.pseudo_hd_risk == null ? "安全" : report.pseudo_hd_risk;
  const artifactRisk = report.artifact_risk || "低风险";
  const qualityPreserved = report.quality_preserved === false ? "需要复核" : "通过";

  return (
    <section className="rounded-lg border border-[#3cb3a0]/25 bg-[#3cb3a0]/[0.07] p-6 backdrop-blur-xl">
      <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Delivery Certification</p>
      <h2 className="mt-3 text-2xl font-semibold text-white">高清影像交付评估</h2>
      <div className="mt-5 rounded-lg border border-[#3cb3a0]/25 bg-[#040708]/55 p-5">
        <p className="text-lg font-semibold text-[#8effed]">质量守门：{qualityPreserved}</p>
        <p className="mt-2 text-sm leading-7 text-white/52">
          当前报告用于评估输出图是否保持文字、边缘、色彩与层次稳定。此处不声明神经网络重建能力，只记录 V0.4 1080P 稳定交付结果。
        </p>
      </div>
      <div className="mt-5 grid gap-3 font-mono text-xs">
        <MetricRow label="伪高清风险提示" value={pseudoRisk} />
        <MetricRow label="伪影伪作风险" value={artifactRisk} />
        <MetricRow label="编码提示" value={report.encoding_warning || "暂无数据"} />
      </div>
    </section>
  );
}

function ArchiveSignature({ onArchive }) {
  return (
    <section className="rounded-lg border border-white/10 bg-white/[0.045] p-6 backdrop-blur-xl">
      <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Final Signature</p>
      <h2 className="mt-3 text-2xl font-semibold text-white">终审签署归档</h2>
      <p className="mt-4 text-sm leading-7 text-white/55">
        签署后视为本次高清影像交付评估完成。系统将清空当前任务上下文，并返回工作台。
      </p>
      <button type="button" onClick={onArchive} className="mt-6 w-full rounded-lg border border-[#3cb3a0]/45 bg-[#3cb3a0]/15 px-6 py-4 text-sm font-semibold tracking-[0.18em] text-[#8effed] transition hover:bg-[#3cb3a0]/25">
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
    <section className="relative flex h-[100dvh] w-full flex-col overflow-hidden px-6 py-6 text-slate-100">
      <GlacierAuditBackdrop />
      <div className="relative z-10 mx-auto flex min-h-0 w-full max-w-7xl flex-1 flex-col">
        <header className="mb-6 flex shrink-0 flex-wrap items-center justify-between gap-5 rounded-lg border border-white/10 bg-white/[0.045] p-6 backdrop-blur-2xl">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Quality Report / Delivery Audit</p>
            <h1 className="mt-3 text-4xl font-semibold tracking-[0.08em] text-white">质量报告终审</h1>
            <p className="mt-3 text-sm text-white/50">
              {fileName} · {taskConfig?.mode || "fidelity"} · 高清影像交付评估
            </p>
          </div>
          <button type="button" onClick={onBackToCompare} className="rounded-lg border border-white/10 px-5 py-3 text-sm text-white/62 transition hover:bg-white/5">
            返回滑杆对比
          </button>
        </header>

        <div className="grid min-h-0 flex-1 gap-6 overflow-hidden lg:grid-cols-[1fr_24rem]">
          <section className="min-h-0 overflow-y-auto rounded-lg border border-white/10 bg-white/[0.045] p-6 backdrop-blur-xl">
            <div className="mb-6 flex items-end justify-between gap-4">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Score Overlay</p>
                <h2 className="mt-3 text-2xl font-semibold text-white">核心质量指标</h2>
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
            <div className="mt-6 grid gap-3 md:grid-cols-2">
              <MetricRow label="尺寸策略" value={result.resize_policy} />
              <MetricRow label="输出格式" value={result.output_format} />
              <MetricRow label="是否执行像素提升" value={boolText(result.was_upscaled)} />
              <MetricRow label="是否触发默认降采样" value={boolText(result.was_downscaled)} />
              <MetricRow label="输出是否变化" value={boolText(result.output_changed)} />
              <MetricRow label="哈希是否相同" value={boolText(result.hash_equal)} />
            </div>
          </section>

          <div className="min-h-0 space-y-6 overflow-y-auto pr-1">
            <PseudoHDWarning report={report} />
            <ArchiveSignature onArchive={onArchive} />
          </div>
        </div>
      </div>
      <footer className="pointer-events-none relative z-20 mt-3 shrink-0 border-t border-[#0e1d1f] pt-2 text-center font-mono text-[10px] tracking-wider text-slate-600">{PAGE_FOOTER}</footer>
    </section>
  );
}
