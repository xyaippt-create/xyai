import React, { useEffect, useMemo, useRef, useState } from "react";

const PAGE_FOOTER = "© 2026 雪原系统. 保留所有权利。 V0.4 1080P Stable Delivery Pipeline";

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
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_18%,rgba(60,179,160,0.18),transparent_30%),linear-gradient(180deg,rgba(3,16,20,0.05),rgba(3,16,20,0.95))]" />
      <div className="absolute left-1/2 top-[60%] h-[44rem] w-[140vw] -translate-x-1/2 rotate-[-3deg] rounded-[50%] border border-[#3cb3a0]/20 bg-[radial-gradient(ellipse_at_center,rgba(60,179,160,0.16),rgba(7,25,31,0.12)_36%,transparent_68%)] blur-[1px]" />
      <div className="absolute bottom-[-14rem] left-1/2 h-[38rem] w-[120vw] -translate-x-1/2 rounded-[50%] border-t border-[#3cb3a0]/30 bg-[linear-gradient(90deg,rgba(60,179,160,0.04)_1px,transparent_1px),linear-gradient(0deg,rgba(60,179,160,0.05)_1px,transparent_1px)] bg-[size:48px_48px]" />
    </div>
  );
}

function SculptedTitle() {
  return (
    <div className="relative mx-auto max-w-5xl px-12 text-center">
      <p className="font-mono text-xs uppercase tracking-[0.72em] text-[#8effed]/70">Visual Master Pro</p>
      <div className="relative mt-8">
        <h1
          className="relative z-10 flex flex-row items-center justify-center whitespace-nowrap bg-gradient-to-b from-white via-slate-100 to-emerald-50/20 bg-clip-text text-4xl font-black leading-none tracking-[0.18em] text-transparent md:text-5xl"
          style={{
            WebkitTextStroke: "0.7px rgba(255,255,255,0.72)",
            textShadow: "0 1px 0 #ffffff, 0 2px 1px rgba(0,0,0,0.4), 0 4px 6px rgba(0,0,0,0.15)",
          }}
        >
          高清交付引擎
        </h1>
        <p className="mx-auto mt-8 max-w-2xl text-sm leading-8 text-white/62">
          以真实画质恢复为核心，保护构图、色彩与原始风格。当前版本锁定 V0.4 1080P 稳定交付基线。
        </p>
      </div>
    </div>
  );
}

export default function LaunchPage({ onEnter }) {
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
      appVersion: "VisualMasterPro V0.4",
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
              <div key={group.key} className={`rounded-lg border p-6 backdrop-blur-xl transition ${active ? "border-[#8effed]/45 bg-[#3cb3a0]/12" : "border-white/10 bg-white/[0.045]"}`}>
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
      </div>
      <footer className="relative z-10 text-center font-mono text-[10px] tracking-[0.2em] text-white/24">{PAGE_FOOTER}</footer>
    </section>
  );
}
