import React, { useMemo } from "react";
import { resolveDeliveryStatus, resolveReportCenterMeta } from "./deliveryStatus.js";

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

function InfoTag({ label, detail, tone = "#94a3b8" }) {
  return (
    <div className="rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/55 p-2.5">
      <div className="flex items-center justify-between gap-3">
        <span className="min-w-0 truncate text-xs font-medium" style={{ color: tone }} title={label}>
          {label}
        </span>
        <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.18em] text-[#475569]">RC1</span>
      </div>
      <p className="mt-1.5 text-[11px] leading-5 text-[#94a3b8]" title={detail}>
        {detail}
      </p>
    </div>
  );
}

const REPORT_METRIC_FIELDS = [
  ["clarity_score", "清晰度"],
  ["text_clarity_score", "文字清晰度"],
  ["edge_quality_score", "边缘质量"],
  ["color_fidelity_score", "色彩忠实度"],
  ["texture_score", "纹理保持力"],
];

function readMetric(report, key) {
  const value = report?.[key];
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function metricDisplay(report, key) {
  const number = readMetric(report, key);
  return number == null ? "暂无数据" : number.toFixed(2);
}

function normalizeList(value) {
  if (Array.isArray(value)) {
    return value.filter(Boolean).map((item) => (typeof item === "string" ? item : item.label || item.detail || "")).filter(Boolean);
  }
  if (typeof value === "string" && value.trim()) return [value.trim()];
  return [];
}

function resolvePositiveSignalsForReport(report, meta) {
  const explicit = normalizeList(report?.positive_signals);
  if (explicit.length) return explicit;

  const signals = ["已完成 1080P 本地输出"];
  if (readMetric(report, "color_fidelity_score") >= 95) signals.push("色彩忠实度较高，默认保真色彩稳定");
  if (meta.delivery.status !== "FAIL") signals.push("未触发“不建议交付”状态");
  if (report.final_output_url || report.final_output_filename || report.output_filename) signals.push("输出文件已生成，可进入本地查看");
  if (report.feedback_bundle_status === "ready" || report.feedback_bundle_url || report.diagnostics_status === "ready") {
    signals.push("诊断信息已生成，便于后续反馈");
  }
  if (meta.delivery.status === "PASS_WITH_LIMITATION") {
    signals.push("当前属于保护型复核，不是处理失败");
  }
  return signals;
}

function resolveSuggestedUsageForReport(report, meta) {
  const explicit = normalizeList(report?.suggested_usage);
  if (explicit.length) return explicit.join("；");

  const typeText = `${report?.image_type || ""} ${meta.imageType.label || ""}`;
  if (meta.delivery.status === "FAIL") {
    return "当前不建议直接用于正式交付。建议回到原图检查文字、Logo、边缘和低频区域后再决定是否重新处理。";
  }
  if (meta.benefit.label === "低收益提示") {
    return "原图质量或保护约束较强，增强收益有限。建议对比原图和输出图后决定是否使用输出图。";
  }
  if (/文字|海报|信息|poster|text|infographic/i.test(typeText)) {
    return "适合公众号配图、PPT 内容页和客户方案配图；正式使用前建议查看标题、小字、细线、标签文字和白底洁净度。";
  }
  if (/产品|品牌|KV|product|brand/i.test(typeText)) {
    return "适合产品视觉提案、品牌 KV 预览和 PPT 封面；正式使用前建议查看 Logo、包装文字、品牌色、高光和产品轮廓。";
  }
  if (/人物|照片|portrait|person|photo/i.test(typeText)) {
    return "适合内部预览、资料整理和商业视觉初稿；正式使用前建议查看人脸、手部、肤色、现场文字和 Logo。";
  }
  if (/建筑|空间|文旅|architecture|building/i.test(typeText)) {
    return "适合 PPT 封面、文旅海报和视觉提案；正式使用前建议查看小字、建筑边缘、墙面暗部和复杂纹理。";
  }
  return "适合本地预览、PPT 草案和方案初稿；正式使用前建议查看文字、Logo、主体边缘、颜色和低频平滑区域。";
}

function ReportBulletList({ title, items, tone = "#94a3b8" }) {
  return (
    <div className="mt-4">
      <h3 className="mb-2 text-xs font-medium text-[#94a3b8]">{title}</h3>
      <div className="grid gap-1.5">
        {items.map((item, index) => (
          <div key={`${title}-${index}`} className="rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/40 px-3 py-2 text-[11px] leading-5 text-[#cbd5e1]">
            <span className="mr-2 font-mono text-[10px]" style={{ color: tone }}>◆</span>
            {item}
          </div>
        ))}
      </div>
    </div>
  );
}

function DeveloperReportDetails({ report, meta }) {
  const rawStatus = report.final_delivery_status || report.delivery_status || "暂无数据";
  const taskId = report.task_id || report.taskId || report.id || "暂无数据";
  const rows = [
    ["raw delivery status", rawStatus],
    ["resolved delivery status", meta.delivery.status],
    ["task_id", taskId],
    ["image_type", report.image_type || meta.imageType.label],
    ["delivery_score", metricDisplay(report, "delivery_score")],
    ...REPORT_METRIC_FIELDS.map(([key, label]) => [label, metricDisplay(report, key)]),
    ["limitation reasons", meta.reviewReasons.map((item) => item.label).join(" / ") || "暂无数据"],
  ];

  return (
    <details className="mt-4 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/35 p-3">
      <summary className="cursor-pointer select-none text-xs font-medium text-[#64748b] hover:text-[#94a3b8]">
        技术详情 / 开发者信息
      </summary>
      <div className="mt-3 grid gap-1.5 border-t border-[#1c1f26]/70 pt-3">
        {rows.map(([label, value]) => (
          <div key={label} className="flex min-w-0 items-center gap-3 text-[11px]">
            <span className="w-28 shrink-0 truncate font-mono text-[#475569]" title={label}>{label}</span>
            <span className="min-w-0 flex-1 truncate text-right font-mono text-[#94a3b8]" title={String(value || "暂无数据")}>
              {value || "暂无数据"}
            </span>
          </div>
        ))}
      </div>
      <p className="mt-3 border-t border-[#1c1f26]/50 pt-2 text-[10px] leading-4 text-[#475569]">
        以上为后端原始字段与前台解释结果，仅用于排查，不代表向普通用户展示的最终文案。
      </p>
    </details>
  );
}

function ReportCenterMvp({ report }) {
  const meta = resolveReportCenterMeta(report);
  const positiveSignals = resolvePositiveSignalsForReport(report, meta);
  const suggestedUsage = resolveSuggestedUsageForReport(report, meta);

  return (
    <section className="shrink-0 rounded-sm border border-[#1c1f26] bg-[#121418] p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Local Report Center</p>
          <h2 className="mt-2 text-lg font-semibold text-white">本地报告中心</h2>
          <p className="mt-1 text-xs leading-5 text-[#64748b]">面向人工验收的状态解释，不改变后端原始字段。</p>
        </div>
        <div className="shrink-0 rounded-sm border px-2.5 py-1 text-xs font-semibold" style={{ color: meta.delivery.tone, borderColor: meta.delivery.border, backgroundColor: "#0b0c0e" }}>
          {meta.delivery.label}
        </div>
      </div>

      <div className="mt-4 grid gap-2.5">
        <InfoTag label={`图像类型：${meta.imageType.label}`} detail={meta.imageType.detail} tone={meta.imageType.tone} />
        <InfoTag label={`增强判断：${meta.benefit.label}`} detail={meta.benefit.detail} tone={meta.benefit.tone} />
      </div>

      <div className="mt-4 rounded-sm border border-[#66532d]/45 bg-[#100d06]/55 p-3">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-xs font-medium text-[#f0c36f]">PASS_WITH_LIMITATION 解释</h3>
          <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.18em] text-[#856404]">Manual Review</span>
        </div>
        <p className="mt-2 text-xs leading-6 text-[#d8c28c]">{meta.limitationExplanation}</p>
      </div>

      <div className="mt-4">
        <h3 className="mb-2 text-xs font-medium text-[#94a3b8]">复核原因标签</h3>
        <div className="grid gap-2">
          {meta.reviewReasons.map((item, index) => (
            <div key={`${item.label}-${index}`} className="rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/45 px-3 py-2">
              <div className="text-xs font-medium text-[#f0c36f]">{item.label}</div>
              <div className="mt-1 text-[11px] leading-5 text-[#94a3b8]">{item.detail}</div>
            </div>
          ))}
        </div>
      </div>

      <ReportBulletList title="正向信号" items={positiveSignals} tone="#10b981" />

      <div className="mt-4 rounded-sm border border-[#1c1f26] bg-[#0b0c0e]/45 p-3">
        <h3 className="text-xs font-medium text-[#94a3b8]">建议用途</h3>
        <p className="mt-2 text-[11px] leading-5 text-[#cbd5e1]">{suggestedUsage}</p>
      </div>

      <p className="mt-4 border-t border-[#1c1f26]/60 pt-3 text-[11px] leading-5 text-[#64748b]">
        用户友好口径：可交付代表可直接作为 1080P 成品查看；建议人工复核代表已生成本地预览但需查看关键局部；不建议交付代表存在明确交付风险。
      </p>

      <DeveloperReportDetails report={report} meta={meta} />
    </section>
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

      <aside className="scrollbar-none flex h-full w-[320px] shrink-0 flex-col gap-3 overflow-y-auto pr-1">
        <ReportCenterMvp report={report} />
        <PseudoHDWarning report={report} />
        <ArchiveSignature onArchive={onArchive} />
      </aside>
    </div>
  );
}
