import React from "react";

const USAGE_ITEMS = [
  {
    title: "适合处理",
    detail: "中文信息图、产品图、文旅地图、城市科技主视觉和演示封面。",
  },
  {
    title: "自动保护",
    detail: "遇到人物主体或不确定内容时会优先跳过，避免破坏面部和关键结构。",
  },
  {
    title: "交付前确认",
    detail: "处理完成后可拖动查看前后差异，并根据质量报告决定是否交付。",
  },
];

export default function Safe1080pBetaPage({ onBackToDashboard }) {
  return (
    <section
      className="hdde-enhanced-page flex h-full min-h-0 w-full overflow-auto bg-[var(--content-background)] text-[var(--text-primary)]"
      data-testid="safe-1080p-entry-page"
    >
      <div className="mx-auto flex min-h-full w-full max-w-6xl flex-col px-8 py-10">
        <header className="flex items-center gap-6">
          <div>
            <p className="text-xs font-semibold tracking-[0.18em] text-[var(--brand-primary)]">影界 HDDE · 高清交付引擎</p>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight">1080P安全增强</h1>
          </div>
        </header>

        <main className="grid flex-1 items-center gap-8 py-10 lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
          <section>
            <p className="max-w-2xl text-4xl font-semibold leading-tight tracking-tight">
              在保护文字、Logo和画面结构的前提下，完成更清晰的1080P交付。
            </p>
            <p className="mt-5 max-w-2xl text-base leading-7 text-[var(--text-secondary)]">
              选择本地图片后，系统会执行安全增强、生成可拖动前后对比，并给出面向交付的质量结论。所有处理均在本地完成。
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={onBackToDashboard}
                className="min-h-11 rounded-md bg-[var(--brand-primary)] px-6 py-3 text-sm font-semibold text-white transition hover:bg-[var(--brand-primary-hover)]"
              >
                进入处理中心
              </button>
              <p className="text-sm text-[var(--text-muted)]">在处理模式中选择“1080P安全增强”即可开始。</p>
            </div>
          </section>

          <section className="rounded-xl border border-[var(--border-color)] bg-[var(--card-background)] p-6 shadow-sm">
            <p className="text-xs font-semibold tracking-[0.16em] text-[var(--brand-primary)]">使用说明</p>
            <h2 className="mt-2 text-xl font-semibold">处理前请确认</h2>
            <div className="mt-5 space-y-3">
              {USAGE_ITEMS.map((item, index) => (
                <article key={item.title} className="grid grid-cols-[32px_minmax(0,1fr)] gap-3 rounded-lg border border-[var(--divider-color)] bg-[var(--elevated-background)] p-4">
                  <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--brand-primary-soft)] text-sm font-semibold text-[var(--brand-primary)]">
                    {index + 1}
                  </span>
                  <div>
                    <h3 className="text-sm font-semibold">{item.title}</h3>
                    <p className="mt-1 text-sm leading-6 text-[var(--text-secondary)]">{item.detail}</p>
                  </div>
                </article>
              ))}
            </div>
            <p className="mt-5 rounded-lg border border-[var(--feature-development-border)] bg-[var(--feature-development-background)] px-4 py-3 text-sm leading-6 text-[var(--status-warning)]">
              当前不建议用于人物主体、低清照片真实修复或通用4K放大。
            </p>
          </section>
        </main>
      </div>
    </section>
  );
}
