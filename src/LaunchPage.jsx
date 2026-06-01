import React, { useEffect, useMemo, useRef, useState } from "react";

const checkGroups = [
  {
    key: "runtime",
    label: "Runtime",
    title: "运行时核心",
    items: ["Python Bridge", "Crash Handler", "Logger", "Startup Check"]
  },
  {
    key: "paths",
    label: "Paths",
    title: "路径与目录",
    items: ["输入图片", "输出成品", "logs", "models"]
  },
  {
    key: "dependencies",
    label: "Dependencies",
    title: "依赖组件",
    items: ["OpenCV", "NumPy", "Pillow", "Tailwind UI Shell"]
  },
  {
    key: "models",
    label: "Models",
    title: "AI 修复模型",
    items: ["Real-ESRGAN Adapter", "SwinIR Adapter", "PaddleOCR Slot", "Fallback CV Core"]
  }
];

const initialStatus = checkGroups.reduce((acc, group) => {
  acc[group.key] = "waiting";
  return acc;
}, {});

function StatusPill({ status }) {
  const config = {
    waiting: "border-white/10 bg-white/5 text-white/45",
    running: "border-glacier/50 bg-glacier/10 text-glacier",
    done: "border-aurora/40 bg-aurora/10 text-aurora"
  };
  const label = {
    waiting: "等待",
    running: "校验中",
    done: "完成"
  };

  return (
    <span className={`rounded-full border px-3 py-1 text-xs tracking-[0.22em] ${config[status]}`}>
      {label[status]}
    </span>
  );
}

function CinematicTerrain() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_18%,rgba(151,244,255,0.18),transparent_30%),linear-gradient(180deg,rgba(3,16,20,0.05),rgba(3,16,20,0.95))]" />
      <div className="absolute left-1/2 top-[60%] h-[44rem] w-[140vw] -translate-x-1/2 rotate-[-3deg] rounded-[50%] border border-glacier/20 bg-[radial-gradient(ellipse_at_center,rgba(143,244,255,0.18),rgba(7,25,31,0.12)_36%,transparent_68%)] blur-[1px]" />
      <div className="absolute bottom-[-14rem] left-1/2 h-[38rem] w-[120vw] -translate-x-1/2 rounded-[50%] border-t border-glacier/30 bg-[linear-gradient(90deg,rgba(143,244,255,0.04)_1px,transparent_1px),linear-gradient(0deg,rgba(143,244,255,0.05)_1px,transparent_1px)] bg-[size:48px_48px] shadow-insetGlow" />
      <div className="absolute bottom-24 left-[18%] h-24 w-24 rounded-full bg-glacier/20 blur-3xl" />
      <div className="absolute right-[18%] top-28 h-36 w-36 rounded-full bg-aurora/10 blur-3xl" />
    </div>
  );
}

function SculptedTitle() {
  return (
    <div className="relative mx-auto max-w-5xl px-12 text-center">
      <p className="font-display text-xs uppercase tracking-[0.72em] text-glacier/70">Visual Master Pro</p>
      <div className="relative mt-8">
        <h1
          className="relative z-10 flex flex-row items-center justify-center whitespace-nowrap bg-gradient-to-b from-white via-glacier to-aurora bg-clip-text text-4xl font-black leading-none tracking-[0.18em] text-transparent md:text-5xl"
          style={{
            WebkitTextStroke: "1px rgba(231, 251, 255, 0.86)",
            textShadow:
              "0 1px 2px rgba(255,255,255,0.6), 0 4px 10px rgba(0,242,254,0.3), 0 10px 30px rgba(0,242,254,0.15), 0 0 1px rgba(231,251,255,0.9)"
          }}
        >
          原图忠实增强
        </h1>
        <div className="absolute inset-x-0 top-[54%] z-0 mx-auto h-16 w-[74%] rounded-full bg-glacier/18 blur-3xl" />
        <p className="mx-auto mt-8 max-w-2xl text-sm leading-8 text-white/62">
          以真实画质恢复为核心，保护构图、色彩与原始风格。下一阶段接入 AI Restoration Pipeline，面向文字、结构、纹理与压缩损伤进行可信修复。
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
      }, 520);
    };
    runCheck();
  }, []);

  const snapshot = useMemo(() => ({
    appVersion: "VisualMasterPro V0.3",
    runtimeReady: allDone,
    checks: statusMap,
    gpuInfo: "Local GPU / CPU Adaptive",
    restorationPipeline: "Quality Core + AI Restoration Slot"
  }), [allDone, statusMap]);

  const enterDashboard = () => {
    if (autoEnteredRef.current || !allDone) return;
    autoEnteredRef.current = true;
    setIsExiting(true);
    window.setTimeout(() => onEnter(snapshot), 320);
  };

  useEffect(() => {
    if (!allDone || autoEnteredRef.current) return undefined;
    const timer = window.setTimeout(() => {
      enterDashboard();
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [allDone, snapshot]);

  return (
    <section className={`relative flex min-h-screen flex-col items-center justify-start overflow-hidden px-8 py-12 text-center transition-opacity duration-300 ${isExiting ? "opacity-0" : "opacity-100"}`}>
      <CinematicTerrain />

      <div className="relative z-10 flex w-full flex-col items-center">
        <SculptedTitle />

        <div className="mt-12 grid w-full max-w-7xl grid-cols-1 items-stretch gap-6 md:grid-cols-2 xl:grid-cols-4">
          {checkGroups.map((group, index) => (
            <div key={group.key} className="flex h-full flex-col rounded-[1.6rem] border border-white/10 bg-white/[0.045] p-5 shadow-cinematic backdrop-blur-2xl">
              <div className="flex items-start justify-between gap-4">
                <div className="text-left">
                  <p className="font-display text-[0.64rem] uppercase tracking-[0.36em] text-white/38">{group.label}</p>
                  <h3 className="mt-2 text-lg font-medium text-white">{group.title}</h3>
                </div>
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-glacier/30 bg-glacier/10 text-sm text-glacier">
                  {statusMap[group.key] === "done" ? "✓" : activeIndex === index ? index + 1 : "·"}
                </div>
              </div>
              <div className="mt-4 flex justify-start">
                <StatusPill status={statusMap[group.key]} />
              </div>
              <div className="mt-4 grid flex-1 grid-cols-1 gap-2">
                {group.items.map((item) => (
                  <div key={item} className="rounded-lg border border-white/5 bg-polar-900/70 px-3 py-2 text-left text-xs text-white/54">
                    {item}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        <button
          type="button"
          disabled={!allDone}
          onClick={enterDashboard}
          className="mt-8 rounded-full border border-glacier/40 bg-glacier/15 px-8 py-4 text-sm font-semibold tracking-[0.28em] text-glacier transition hover:bg-glacier/25 disabled:cursor-not-allowed disabled:border-white/10 disabled:bg-white/5 disabled:text-white/30"
        >
          {allDone ? "2 秒后自动进入主工作台" : "环境自检中"}
        </button>
      </div>
    </section>
  );
}
