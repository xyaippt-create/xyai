import React from "react";

const mockReportData = {
  taskId: "task_vmp_v03_core",
  fileName: "3540fe7663cd45bfd4edb5248befc332.png",
  qualityFlag: "有效清晰增强",
  pseudoHD: false,
  signedAt: "2026-06-01",
  scores: [
    { key: "clarity", label: "整体清晰度", original: 8.94, enhanced: 9.85, unit: "" },
    { key: "text", label: "文字清晰度", original: 50.0, enhanced: 71.48, unit: "" },
    { key: "edge", label: "边缘稳定性", original: 50.0, enhanced: 67.91, unit: "" },
    { key: "structure", label: "结构恢复", original: 20.67, enhanced: 21.5, unit: "" },
    { key: "noise", label: "噪声控制", original: 100.0, enhanced: 100.0, unit: "" },
    { key: "color", label: "色彩忠实度", original: 100.0, enhanced: 96.13, unit: "%" }
  ]
};

function GlacierAuditBackdrop() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_52%_0%,rgba(143,244,255,0.18),transparent_30rem),radial-gradient(circle_at_16%_18%,rgba(183,255,212,0.1),transparent_26rem),linear-gradient(180deg,#021015_0%,#07191f_42%,#02070a_100%)]" />
      <div className="absolute inset-y-0 left-0 w-[34rem] bg-[repeating-linear-gradient(180deg,rgba(231,251,255,0.085)_0px,transparent_1px,transparent_18px)] opacity-60" />
      <div className="absolute inset-y-0 right-0 w-[26rem] bg-[repeating-linear-gradient(180deg,rgba(143,244,255,0.06)_0px,transparent_1px,transparent_28px)] opacity-50" />
      <div className="absolute bottom-[-10rem] left-1/2 h-[26rem] w-[90vw] -translate-x-1/2 rounded-[50%] border-t border-glacier/20 bg-[radial-gradient(ellipse_at_top,rgba(143,244,255,0.12),rgba(3,16,20,0.06)_48%,transparent_70%)]" />
    </div>
  );
}

function ScoreCompareBar({ item }) {
  const originalWidth = Math.max(4, Math.min(100, item.original));
  const enhancedWidth = Math.max(4, Math.min(100, item.enhanced));
  const delta = item.enhanced - item.original;
  const deltaText = `${delta >= 0 ? "+" : ""}${delta.toFixed(2)}${item.unit}`;

  return (
    <div className="rounded-2xl border border-white/10 bg-polar-900/70 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-white">{item.label}</p>
          <p className="mt-1 font-display text-[0.62rem] uppercase tracking-[0.32em] text-white/32">{item.key}</p>
        </div>
        <span className={`rounded-full border px-3 py-1 text-xs tracking-[0.18em] ${delta >= 0 ? "border-aurora/30 bg-aurora/10 text-aurora" : "border-ember/30 bg-ember/10 text-ember"}`}>
          {deltaText}
        </span>
      </div>
      <div className="relative h-5 overflow-hidden rounded-full border border-white/10 bg-black/35">
        <div className="absolute inset-y-0 left-0 rounded-full bg-white/18" style={{ width: `${originalWidth}%` }} />
        <div className="absolute inset-y-1 left-0 rounded-full bg-gradient-to-r from-glacier/80 to-aurora/80 shadow-[0_0_22px_rgba(143,244,255,0.26)]" style={{ width: `${enhancedWidth}%` }} />
      </div>
      <div className="mt-2 flex justify-between text-[0.68rem] tracking-[0.18em] text-white/36">
        <span>原图 {item.original}{item.unit}</span>
        <span>增强 {item.enhanced}{item.unit}</span>
      </div>
    </div>
  );
}

function PseudoHDWarning() {
  return (
    <section className="rounded-[1.75rem] border border-aurora/25 bg-aurora/[0.07] p-6 shadow-cinematic backdrop-blur-xl">
      <p className="font-display text-xs uppercase tracking-[0.42em] text-aurora/75">Pseudo HD Certification</p>
      <h2 className="mt-3 text-2xl font-semibold text-white">伪高清真无损恢复认证</h2>
      <div className="mt-5 rounded-2xl border border-aurora/25 bg-polar-950/55 p-5">
        <div className="flex items-center gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-full border border-aurora/45 bg-aurora/12 text-2xl text-aurora">✓</div>
          <div>
            <p className="text-lg font-semibold text-aurora">未触发伪高清风险</p>
            <p className="mt-1 text-sm leading-6 text-white/52">
              文件尺寸扩大同时，文字清晰度、边缘质量与色彩忠实度通过物理质检阈值。当前结果可进入人工终审。
            </p>
          </div>
        </div>
      </div>
      <ul className="mt-5 space-y-2 text-sm leading-6 text-white/55">
        <li>· 未检测到明显自动改色。</li>
        <li>· 未检测到高光炸开或反光误增强。</li>
        <li>· 未检测到仅 resize 导致的无效放大标记。</li>
      </ul>
    </section>
  );
}

function ArchiveSignature({ onArchive }) {
  return (
    <section className="rounded-[1.75rem] border border-white/10 bg-white/[0.045] p-6 backdrop-blur-xl">
      <p className="font-display text-xs uppercase tracking-[0.42em] text-ember/75">Final Signature</p>
      <h2 className="mt-3 text-2xl font-semibold text-white">终审签署归档</h2>
      <p className="mt-4 text-sm leading-7 text-white/55">
        签署后视为本次 Quality Core 管线任务完成。系统将清空当前批量状态，并优雅回到主工作台，准备下一轮图片修复。
      </p>
      <button
        type="button"
        onClick={onArchive}
        className="mt-6 w-full rounded-full border border-ember/45 bg-ember/15 px-6 py-4 text-sm font-semibold tracking-[0.22em] text-ember transition hover:bg-ember/25"
      >
        签署物理契约 · 归档成品
      </button>
    </section>
  );
}

export default function QualityReportPage({ taskConfig, onBackToCompare, onArchive }) {
  return (
    <section className="relative min-h-screen overflow-hidden px-6 py-6 text-polar-100">
      <GlacierAuditBackdrop />
      <div className="relative z-10 mx-auto max-w-7xl">
        <header className="mb-6 flex flex-wrap items-center justify-between gap-5 rounded-[2rem] border border-white/10 bg-white/[0.045] p-6 backdrop-blur-2xl">
          <div>
            <p className="font-display text-xs uppercase tracking-[0.52em] text-glacier/70">Quality Report / Physical Audit</p>
            <h1 className="mt-3 text-4xl font-semibold tracking-[0.08em] text-white">质量报告终审</h1>
            <p className="mt-3 text-sm text-white/50">
              {mockReportData.fileName} · {taskConfig?.mode || "fidelity"} · {mockReportData.qualityFlag}
            </p>
          </div>
          <button type="button" onClick={onBackToCompare} className="rounded-full border border-white/10 px-5 py-3 text-sm text-white/62 transition hover:bg-white/5">
            返回滑杆对比
          </button>
        </header>

        <div className="grid gap-6 lg:grid-cols-[1fr_24rem]">
          <section className="rounded-[1.75rem] border border-white/10 bg-white/[0.045] p-6 shadow-cinematic backdrop-blur-xl">
            <div className="mb-6 flex items-end justify-between gap-4">
              <div>
                <p className="font-display text-xs uppercase tracking-[0.42em] text-glacier/70">Score Overlay</p>
                <h2 className="mt-3 text-2xl font-semibold text-white">双色物理质检对比条</h2>
              </div>
              <div className="text-right text-xs leading-6 text-white/40">
                <p>白色：原图</p>
                <p>冰蓝：增强图</p>
              </div>
            </div>
            <div className="grid gap-4">
              {mockReportData.scores.map((item) => (
                <ScoreCompareBar key={item.key} item={item} />
              ))}
            </div>
          </section>

          <div className="space-y-6">
            <PseudoHDWarning />
            <ArchiveSignature onArchive={onArchive} />
          </div>
        </div>
      </div>
    </section>
  );
}
