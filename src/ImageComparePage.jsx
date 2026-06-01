import React, { useMemo, useRef, useState } from "react";

const metrics = [
  { label: "Text Clarity", value: 71.48, unit: "", tone: "text-glacier" },
  { label: "Edge Quality", value: 67.91, unit: "", tone: "text-aurora" },
  { label: "Color Fidelity", value: 96.13, unit: "%", tone: "text-ember" },
  { label: "Pseudo HD Risk", value: 0, unit: "LOW", tone: "text-aurora" }
];

const checklist = [
  "小字是否更清楚",
  "边缘是否出现白边或黑边",
  "建筑结构是否更稳定",
  "文物纹理是否更真实",
  "高光与玻璃反光是否被保护",
  "色彩是否仍接近原图",
  "是否只是文件变大但信息量没提升"
];

function LakeGlacierBackdrop() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_8%,rgba(143,244,255,0.2),transparent_30rem),radial-gradient(circle_at_82%_18%,rgba(183,255,212,0.12),transparent_26rem),linear-gradient(180deg,#021014_0%,#061818_48%,#020708_100%)]" />
      <div className="absolute left-0 top-0 h-full w-[30rem] bg-[repeating-linear-gradient(180deg,rgba(231,251,255,0.08)_0px,transparent_1px,transparent_20px)] opacity-70" />
      <div className="absolute bottom-[11rem] left-1/2 h-px w-[84vw] -translate-x-1/2 bg-gradient-to-r from-transparent via-glacier/40 to-transparent" />
      <div className="absolute bottom-[-10rem] left-1/2 h-[28rem] w-[110vw] -translate-x-1/2 rounded-[50%] border-t border-glacier/25 bg-[radial-gradient(ellipse_at_top,rgba(143,244,255,0.14),rgba(3,16,20,0.18)_42%,transparent_72%)]" />
      <div className="absolute bottom-0 left-0 right-0 h-56 bg-[linear-gradient(180deg,rgba(143,244,255,0.07),transparent),repeating-linear-gradient(0deg,rgba(255,255,255,0.045)_0px,transparent_1px,transparent_18px)] opacity-80 [transform:perspective(900px)_rotateX(58deg)] [transform-origin:bottom]" />
    </div>
  );
}

function MockImageSurface({ variant, imageUrl }) {
  const enhanced = variant === "enhanced";
  return (
    <div
      className={`absolute inset-0 overflow-hidden rounded-[1.5rem] ${
        enhanced ? "bg-[linear-gradient(135deg,#0b2730,#153a36_48%,#07191f)]" : "bg-[linear-gradient(135deg,#08161b,#152322_48%,#050d10)]"
      }`}
    >
      {imageUrl && <img src={imageUrl} alt={enhanced ? "增强图" : "原图"} className="absolute inset-0 h-full w-full object-contain" />}
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_35%_28%,rgba(246,214,166,0.16),transparent_18rem),radial-gradient(circle_at_72%_35%,rgba(143,244,255,0.14),transparent_20rem)]" />
      {!imageUrl && (
        <>
          <div className={`absolute left-[12%] top-[18%] h-[34%] w-[50%] rounded-[1.2rem] border ${enhanced ? "border-glacier/42" : "border-white/18"} bg-black/20 shadow-[0_30px_100px_rgba(0,0,0,0.32)]`} />
          <div className={`absolute bottom-[17%] left-[13%] h-[18%] w-[73%] rounded-full border-t ${enhanced ? "border-aurora/50" : "border-white/14"} bg-white/[0.035] blur-[0.2px]`} />
          {Array.from({ length: 12 }).map((_, index) => (
            <div
              key={index}
              className={`absolute h-px ${enhanced ? "bg-glacier/50" : "bg-white/20"}`}
              style={{
                left: `${12 + index * 5.8}%`,
                top: `${36 + (index % 4) * 6}%`,
                width: `${18 + (index % 5) * 5}%`,
                transform: `rotate(${index % 2 ? -4 : 3}deg)`,
                opacity: enhanced ? 0.72 : 0.42
              }}
            />
          ))}
          <div className={`absolute right-[13%] top-[22%] grid gap-2 ${enhanced ? "text-glacier/90" : "text-white/45"}`}>
            {["福", "文", "化"].map((char) => (
              <span key={char} className="text-4xl font-black tracking-[0.18em] [text-shadow:0_10px_32px_rgba(143,244,255,0.28)]">
                {char}
              </span>
            ))}
          </div>
          <div className={`absolute bottom-[22%] right-[12%] space-y-2 text-xs ${enhanced ? "text-white/80" : "text-white/42"}`}>
            <p>2026.06.01 / Restoration Sample</p>
            <p>Text clarity · Edge fidelity · Color lock</p>
          </div>
        </>
      )}
      <div className={`absolute inset-0 ${imageUrl ? "bg-black/5" : enhanced ? "backdrop-contrast-125" : "backdrop-blur-[0.4px]"}`} />
    </div>
  );
}

function SplitCompareViewer({ slider, setSlider, zoom, setZoom, compareAssets }) {
  const containerRef = useRef(null);

  const updateAxis = (clientX, clientY) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = Math.min(Math.max(clientX - rect.left, 0), rect.width);
    const y = Math.min(Math.max(clientY - rect.top, 0), rect.height);
    setSlider(Math.round((x / rect.width) * 100));
    setZoom({
      active: true,
      x,
      y,
      xPct: Math.round((x / rect.width) * 100),
      yPct: Math.round((y / rect.height) * 100)
    });
  };

  return (
    <div
      ref={containerRef}
      onMouseMove={(event) => updateAxis(event.clientX, event.clientY)}
      onMouseLeave={() => setZoom((prev) => ({ ...prev, active: false }))}
      onTouchMove={(event) => {
        const touch = event.touches[0];
        if (touch) updateAxis(touch.clientX, touch.clientY);
      }}
      className="relative h-[38rem] overflow-hidden rounded-[1.75rem] border border-white/10 bg-black/30 shadow-cinematic"
    >
      <MockImageSurface variant="original" imageUrl={compareAssets?.originalUrl} />
      <div className="absolute inset-0 overflow-hidden" style={{ clipPath: `inset(0 ${100 - slider}% 0 0)` }}>
        <MockImageSurface variant="enhanced" imageUrl={compareAssets?.enhancedUrl} />
      </div>

      <div className="absolute inset-y-0 z-20 w-px bg-white/80 shadow-[0_0_28px_rgba(143,244,255,0.75)]" style={{ left: `${slider}%` }}>
        <div className="absolute left-1/2 top-1/2 flex h-14 w-14 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-glacier/70 bg-polar-950/85 text-xs text-glacier backdrop-blur-xl">
          ⇄
        </div>
      </div>

      <div className="absolute left-5 top-5 z-20 rounded-full border border-aurora/35 bg-aurora/10 px-4 py-2 text-xs tracking-[0.22em] text-aurora">
        ENHANCED
      </div>
      <div className="absolute right-5 top-5 z-20 rounded-full border border-white/15 bg-white/[0.08] px-4 py-2 text-xs tracking-[0.22em] text-white/60">
        ORIGINAL
      </div>

      <div className="absolute bottom-4 right-4 z-20 max-w-[85%] truncate rounded-full border border-white/10 bg-black/55 px-4 py-2 text-right text-[0.66rem] tracking-[0.2em] text-white/40 backdrop-blur-md">
        VisualMasterPro V0.3 · {compareAssets?.fileName || "等待真实上传图片"} · Color Lock
      </div>

      {zoom.active && (
        <div
          className="pointer-events-none absolute z-30 h-44 w-44 rounded-full border border-glacier/70 bg-polar-950/60 shadow-[0_0_55px_rgba(143,244,255,0.36)] backdrop-blur-md"
          style={{
            left: zoom.x,
            top: zoom.y,
            transform: "translate(-50%, -50%)"
          }}
        >
          <div className="absolute inset-3 overflow-hidden rounded-full border border-white/10">
            <div
              className="h-full w-full scale-[2.55] bg-[radial-gradient(circle_at_center,rgba(143,244,255,0.45),rgba(7,25,31,0.72)_34%,rgba(2,8,10,0.96)_72%),repeating-linear-gradient(90deg,rgba(255,255,255,0.16)_0px,transparent_1px,transparent_12px)]"
              style={{ transformOrigin: `${zoom.xPct}% ${zoom.yPct}%` }}
            />
          </div>
          <div className="absolute -bottom-8 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full border border-white/10 bg-black/70 px-3 py-1 text-[0.62rem] tracking-[0.2em] text-glacier">
            8K ZOOM {zoom.xPct}% / {zoom.yPct}%
          </div>
        </div>
      )}
    </div>
  );
}

function MetricPanel() {
  return (
    <aside className="rounded-[1.75rem] border border-white/10 bg-white/[0.045] p-6 shadow-cinematic backdrop-blur-xl">
      <p className="font-display text-xs uppercase tracking-[0.42em] text-glacier/70">Physical QA</p>
      <h2 className="mt-3 text-2xl font-semibold text-white">物理质检量化</h2>
      <div className="mt-6 space-y-4">
        {metrics.map((metric) => (
          <div key={metric.label} className="rounded-2xl border border-white/10 bg-polar-900/70 p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-[0.28em] text-white/38">{metric.label}</span>
              <span className={`font-display text-2xl ${metric.tone}`}>
                {metric.value}
                <span className="ml-1 text-xs">{metric.unit}</span>
              </span>
            </div>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10">
              <div className="h-full rounded-full bg-gradient-to-r from-glacier via-aurora to-ember" style={{ width: `${metric.unit === "LOW" ? 18 : metric.value}%` }} />
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}

function ManualReviewChecklist() {
  const [checked, setChecked] = useState(() => new Set(["小字是否更清楚", "色彩是否仍接近原图"]));
  return (
    <section className="rounded-[1.75rem] border border-white/10 bg-white/[0.045] p-6 backdrop-blur-xl">
      <p className="font-display text-xs uppercase tracking-[0.42em] text-aurora/70">Manual Review</p>
      <h2 className="mt-3 text-2xl font-semibold text-white">人工复核清单</h2>
      <div className="mt-5 space-y-3">
        {checklist.map((item) => {
          const active = checked.has(item);
          return (
            <button
              key={item}
              type="button"
              onClick={() =>
                setChecked((prev) => {
                  const next = new Set(prev);
                  if (next.has(item)) next.delete(item);
                  else next.add(item);
                  return next;
                })
              }
              className={`flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left text-sm transition ${
                active ? "border-aurora/35 bg-aurora/10 text-aurora" : "border-white/10 bg-polar-900/65 text-white/55"
              }`}
            >
              <span className="flex h-5 w-5 items-center justify-center rounded-full border border-current text-[0.68rem]">{active ? "✓" : ""}</span>
              {item}
            </button>
          );
        })}
      </div>
    </section>
  );
}

export default function ImageComparePage({ taskConfig, compareAssets, onBackToTask, onViewReport }) {
  const [slider, setSlider] = useState(52);
  const [zoom, setZoom] = useState({ active: false, x: 0, y: 0, xPct: 50, yPct: 50 });
  const modeLabel = useMemo(() => taskConfig?.mode || "fidelity", [taskConfig]);

  return (
    <section className="relative min-h-screen overflow-hidden px-6 py-6 text-polar-100">
      <LakeGlacierBackdrop />
      <div className="relative z-10 mx-auto max-w-7xl">
        <header className="mb-6 flex flex-wrap items-center justify-between gap-5 rounded-[2rem] border border-white/10 bg-white/[0.045] p-6 backdrop-blur-2xl">
          <div>
            <p className="font-display text-xs uppercase tracking-[0.52em] text-glacier/70">Image Compare / Split Slider</p>
            <h1 className="mt-3 text-4xl font-semibold tracking-[0.08em] text-white">原图与增强图对比</h1>
            <p className="mt-3 max-w-4xl truncate text-sm text-white/50">
              模式：{modeLabel} · {compareAssets?.fileName || "Mock Restoration Sample"} · 8K 局部悬浮放大镜
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <button type="button" onClick={onBackToTask} className="rounded-full border border-white/10 px-5 py-3 text-sm text-white/62 transition hover:bg-white/5">
              返回任务详情
            </button>
            <button type="button" onClick={onViewReport} className="rounded-full border border-glacier/45 bg-glacier/15 px-5 py-3 text-sm font-semibold tracking-[0.18em] text-glacier transition hover:bg-glacier/25">
              查看报告
            </button>
          </div>
        </header>

        <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
          <div className="space-y-5">
            <SplitCompareViewer slider={slider} setSlider={setSlider} zoom={zoom} setZoom={setZoom} compareAssets={compareAssets} />
            <div className="rounded-[1.2rem] border border-white/10 bg-white/[0.045] px-5 py-4 text-sm text-white/52 backdrop-blur-xl">
              拖动或移动鼠标即可改变左右分割轴。左侧为增强图，右侧为原图；悬浮圆镜用于查看局部文字、边缘、纹理与高光保护状态。
            </div>
          </div>
          <div className="space-y-6">
            <MetricPanel />
            <ManualReviewChecklist />
          </div>
        </div>
      </div>
    </section>
  );
}
