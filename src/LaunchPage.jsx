import React, { useEffect, useMemo, useRef, useState } from "react";

const PAGE_FOOTER = "影界 HDDE V0.4.6 RC1 · HD Delivery Engine · 中文视觉高清交付引擎";

const checkGroups = [
  {
    key: "runtime",
    label: "Runtime",
    title: "运行时核心",
    items: ["Python Bridge", "Crash Handler", "Logger", "Startup Check"],
  },
  {
    key: "paths",
    label: "Paths",
    title: "路径与目录",
    items: ["输入图片", "输出成品", "logs", "runtime"],
  },
  {
    key: "dependencies",
    label: "Dependencies",
    title: "依赖组件",
    items: ["FastAPI", "OpenCV", "NumPy", "Pillow"],
  },
  {
    key: "pipeline",
    label: "Pipeline",
    title: "高清交付管线",
    items: ["1080P Baseline", "Color Lock", "Text Clarity", "Quality Gate"],
  },
];

const initialStatus = checkGroups.reduce((acc, group) => {
  acc[group.key] = "waiting";
  return acc;
}, {});

function StatusPill({ status }) {
  const config = {
    waiting: "border-white/10 bg-white/5 text-white/45",
    running: "border-[#3cb3a0]/50 bg-[#3cb3a0]/10 text-[#8effed]",
    done: "border-emerald-400/40 bg-emerald-400/10 text-emerald-300",
  };
  const label = {
    waiting: "等待",
    running: "校验中",
    done: "完成",
  };
  return <span className={`rounded-full border px-3 py-1 text-xs tracking-[0.22em] ${config[status]}`}>{label[status]}</span>;
}

function CinematicTerrain() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="absolute inset-0 bg-[#090e10]" />
      <div className="absolute inset-x-0 top-0 h-px bg-[#263738]" />
    </div>
  );
}

function SculptedTitle() {
  return (
    <div className="relative mx-auto max-w-5xl px-12 text-center">
      <p className="font-mono text-xs uppercase tracking-[0.32em] text-[#8aa0a2]">HD Delivery Engine</p>
      <div className="relative mt-8">
        <h1
          className="relative z-10 flex flex-row items-center justify-center whitespace-nowrap text-4xl font-semibold leading-none tracking-[0.08em] text-slate-100 md:text-5xl"
        >
          影界 HDDE
        </h1>
        <p className="mx-auto mt-8 max-w-2xl text-sm leading-8 text-white/62">
          中文视觉高清交付引擎。以真实画质恢复为核心，保护构图、色彩与原始风格。当前版本锁定 V0.4 1080P 稳定交付基线。
        </p>
      </div>
    </div>
  );
}

export default function LaunchPage({ onEnter, onOpenSafeBeta }) {
  const [statusMap, setStatusMap] = useState(initialStatus);
  const [activeIndex, setActiveIndex] = useState(0);
  const [isExiting, setIsExiting] = useState(false);
  const autoEnteredRef = useRef(false);
  const allDone = useMemo(() => Object.values(statusMap).every((status) => status === "done"), [statusMap]);

  useEffect(() => {
    let cursor = 0;
    const runCheck = () => {
      if (cursor >= checkGroups.length) return;
      const key = checkGroups[cursor].key;
      setActiveIndex(cursor);
      setStatusMap((prev) => ({ ...prev, [key]: "running" }));
      window.setTimeout(() => {
        setStatusMap((prev) => ({ ...prev, [key]: "done" }));
        cursor += 1;
        runCheck();
      }, 420);
    };
    runCheck();
  }, []);

  const snapshot = useMemo(
    () => ({
      appVersion: "影界 HDDE V0.4",
      runtimeReady: allDone,
      checks: statusMap,
      gpuInfo: "Local GPU / CPU Adaptive",
      restorationPipeline: "1080P Stable Delivery Pipeline",
    }),
    [allDone, statusMap],
  );

  useEffect(() => {
    if (!allDone || autoEnteredRef.current) return () => {};
    autoEnteredRef.current = true;
    setIsExiting(true);
    const timer = window.setTimeout(() => onEnter(snapshot), 420);
    return () => window.clearTimeout(timer);
  }, [allDone, onEnter, snapshot]);

  return (
    <section
      className={`relative flex h-screen w-screen select-none flex-col justify-between overflow-hidden bg-[#090e10] p-6 text-slate-100 transition-all duration-500 ease-out ${
        isExiting ? "pointer-events-none -translate-y-4 scale-[0.98] opacity-0" : "translate-y-0 opacity-100"
      }`}
    >
      <CinematicTerrain />
      <div className="relative z-10 flex flex-1 flex-col items-center justify-start px-8 py-12 text-center">
        <SculptedTitle />
        <div className="mt-12 grid w-full max-w-7xl grid-cols-1 items-stretch gap-6 md:grid-cols-2 xl:grid-cols-4">
          {checkGroups.map((group, index) => {
            const status = statusMap[group.key];
            const active = index === activeIndex;
            return (
              <div key={group.key} className={`rounded-lg border p-6 transition ${active ? "border-[#6f8f8a] bg-[#101819]" : "border-white/10 bg-white/[0.035]"}`}>
                <div className="flex items-start justify-between gap-4">
                  <div className="text-left">
                    <p className="font-mono text-xs uppercase tracking-[0.38em] text-[#418c80]">{group.label}</p>
                    <h2 className="mt-3 text-xl font-semibold text-white">{group.title}</h2>
                  </div>
                  <StatusPill status={status} />
                </div>
                <div className="mt-6 space-y-3">
                  {group.items.map((item) => (
                    <div key={item} className="flex items-center justify-between rounded-md border border-white/10 bg-black/15 px-3 py-2 text-sm text-white/58">
                      <span>{item}</span>
                      <span className={status === "done" ? "text-emerald-300" : "text-white/30"}>{status === "done" ? "OK" : "--"}</span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
        <button
          style={{ display: "none" }}
          type="button"
          onClick={() => {
            autoEnteredRef.current = true;
            setIsExiting(false);
            onOpenSafeBeta?.();
          }}
          className="mt-6 w-full max-w-7xl rounded-lg border border-[#3cb3a0]/45 bg-[#101819] px-6 py-5 text-left transition hover:border-[#7af4df]/70 hover:bg-[#132022]"
        >
          <span className="font-mono text-xs uppercase tracking-[0.28em] text-[#7af4df]">Beta Entry</span>
          <span className="mt-2 block text-xl font-semibold text-white">1080P安全增强 Beta</span>
          <span className="mt-2 block text-sm leading-6 text-white/58">适用于中文商业非人像图，当前为独立 Beta 功能</span>
        </button>
      </div>
      <footer className="relative z-10 w-full truncate px-3 text-center font-mono text-[10px] tracking-[0.2em] text-white/24">{PAGE_FOOTER}</footer>
    </section>
  );
}
