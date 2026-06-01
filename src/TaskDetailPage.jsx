import React, { useEffect, useMemo, useState } from "react";

const stages = [
  {
    key: "ingest",
    title: "图像读取",
    subtitle: "Image Ingest",
    detail: "载入原图、解析尺寸、建立任务上下文。"
  },
  {
    key: "analysis",
    title: "视觉诊断",
    subtitle: "Visual Analysis",
    detail: "识别文字区域、真实边缘、高光反射与压缩损伤。"
  },
  {
    key: "restoration",
    title: "核心修复",
    subtitle: "Restoration Core",
    detail: "执行压缩修复、结构恢复、文字清晰增强。"
  },
  {
    key: "fidelity",
    title: "忠实校准",
    subtitle: "Fidelity Lock",
    detail: "锁定原图色彩，防止过锐、改色与 AI 乱生成。"
  },
  {
    key: "export",
    title: "质量输出",
    subtitle: "Quality Export",
    detail: "生成增强图、质量指标、对比图与批量日志。"
  }
];

const logScript = [
  "SSE CONNECTED /task/task_vmp_v03_core/stream",
  "读取输入图片：3540fe7663cd45bfd4edb5248befc332.png",
  "完成图像类型检测：architecture / text_poster hybrid",
  "建立高光保护 mask：玻璃反光与过曝区域进入保护区",
  "压缩损伤修复：JPEG block 与高频断层开始清理",
  "Text Clarity Engine：检测疑似小字与展板说明区域",
  "Edge Safe Enhance：过滤随机噪点，仅保留真实结构边缘",
  "Structure Recovery：建筑线条与远景轮廓进入中频补偿",
  "Color Lock：输出色彩回归原图 Lab 色彩坐标",
  "Quality Compare：text +21.48 / edge +17.91 / color fidelity 96.13",
  "任务完成：有效清晰增强"
];

function GlacierBackground() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_18%_8%,rgba(143,244,255,0.16),transparent_28rem),radial-gradient(circle_at_76%_18%,rgba(42,101,70,0.18),transparent_32rem),linear-gradient(180deg,#021015_0%,#071413_48%,#020607_100%)]" />
      <div className="absolute left-[-8rem] top-0 h-full w-[32rem] bg-[linear-gradient(90deg,rgba(143,244,255,0.12),transparent),repeating-linear-gradient(180deg,rgba(255,255,255,0.07)_0px,transparent_1px,transparent_24px)] blur-[0.4px]" />
      <div className="absolute right-[-10rem] top-[-6rem] h-[42rem] w-[42rem] rounded-full bg-aurora/8 blur-3xl" />
      <div className="absolute bottom-[-12rem] left-1/2 h-[28rem] w-[80rem] -translate-x-1/2 rounded-[50%] border-t border-glacier/20 bg-[linear-gradient(90deg,rgba(143,244,255,0.035)_1px,transparent_1px),linear-gradient(0deg,rgba(183,255,212,0.028)_1px,transparent_1px)] bg-[size:42px_42px]" />
    </div>
  );
}

function ProgressTimeline({ currentStageIndex, taskStatus }) {
  return (
    <section className="rounded-[1.75rem] border border-white/10 bg-white/[0.045] p-6 shadow-cinematic backdrop-blur-xl">
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <p className="font-display text-xs uppercase tracking-[0.42em] text-glacier/70">Progress Timeline</p>
          <h2 className="mt-3 text-2xl font-semibold text-white">五大阶段时间线</h2>
        </div>
        <span className="rounded-full border border-aurora/30 bg-aurora/10 px-4 py-2 text-xs tracking-[0.22em] text-aurora">
          {taskStatus === "completed" ? "COMPLETED" : "STREAMING"}
        </span>
      </div>

      <div className="relative space-y-4">
        <div className="absolute bottom-8 left-5 top-8 w-px bg-gradient-to-b from-glacier/70 via-white/10 to-aurora/40" />
        {stages.map((stage, index) => {
          const done = index < currentStageIndex || taskStatus === "completed";
          const active = index === currentStageIndex && taskStatus !== "completed";
          return (
            <div key={stage.key} className="relative grid grid-cols-[2.75rem_1fr] gap-4">
              <div
                className={`relative z-10 flex h-10 w-10 items-center justify-center rounded-full border ${
                  done
                    ? "border-aurora/50 bg-aurora/15 text-aurora"
                    : active
                      ? "border-glacier/70 bg-glacier/15 text-glacier shadow-[0_0_28px_rgba(143,244,255,0.28)]"
                      : "border-white/10 bg-polar-900 text-white/28"
                }`}
              >
                {done ? "✓" : index + 1}
              </div>
              <div className={`rounded-2xl border p-4 ${active ? "border-glacier/35 bg-glacier/10" : "border-white/10 bg-polar-900/65"}`}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-display text-[0.62rem] uppercase tracking-[0.36em] text-white/36">{stage.subtitle}</p>
                    <h3 className="mt-2 text-lg font-semibold text-white">{stage.title}</h3>
                  </div>
                  <span className="text-xs tracking-[0.18em] text-white/38">{done ? "完成" : active ? "执行中" : "等待"}</span>
                </div>
                <p className="mt-3 text-sm leading-6 text-white/52">{stage.detail}</p>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function RealtimeLogStream({ logs }) {
  return (
    <section className="rounded-[1.75rem] border border-white/10 bg-[#02080a]/80 p-6 shadow-cinematic backdrop-blur-xl">
      <div className="mb-5 flex items-center justify-between gap-4">
        <div>
          <p className="font-display text-xs uppercase tracking-[0.42em] text-aurora/70">Realtime Log Stream</p>
          <h2 className="mt-3 text-2xl font-semibold text-white">SSE 实时修复日志</h2>
        </div>
        <span className="h-3 w-3 rounded-full bg-aurora shadow-[0_0_22px_rgba(183,255,212,0.9)]" />
      </div>
      <div className="h-[27rem] overflow-hidden rounded-2xl border border-aurora/10 bg-black/45 p-4 font-mono text-xs leading-7 text-aurora/82">
        {logs.map((line, index) => (
          <div key={`${line}-${index}`} className="flex gap-3 border-b border-white/[0.035] py-1">
            <span className="w-12 shrink-0 text-white/24">{String(index + 1).padStart(2, "0")}</span>
            <span>{line}</span>
          </div>
        ))}
        {logs.length < logScript.length && (
          <div className="mt-2 flex gap-3 text-glacier">
            <span className="w-12 shrink-0 text-white/24">...</span>
            <span className="animate-pulse">stream packet receiving</span>
          </div>
        )}
      </div>
    </section>
  );
}

export default function TaskDetailPage({ taskConfig, onBackToDashboard, onViewCompare }) {
  const [logs, setLogs] = useState([]);
  const [currentStageIndex, setCurrentStageIndex] = useState(0);
  const [taskStatus, setTaskStatus] = useState("processing");

  useEffect(() => {
    setLogs([]);
    setCurrentStageIndex(0);
    setTaskStatus("processing");

    let cursor = 0;
    const timer = window.setInterval(() => {
      cursor += 1;
      setLogs(logScript.slice(0, cursor));
      setCurrentStageIndex(Math.min(stages.length - 1, Math.floor((cursor / logScript.length) * stages.length)));
      if (cursor >= logScript.length) {
        window.clearInterval(timer);
        setCurrentStageIndex(stages.length);
        setTaskStatus("completed");
      }
    }, 560);

    return () => window.clearInterval(timer);
  }, []);

  const progress = useMemo(() => {
    if (taskStatus === "completed") return 100;
    return Math.min(96, Math.round((logs.length / logScript.length) * 100));
  }, [logs.length, taskStatus]);

  return (
    <section className="relative min-h-screen overflow-hidden px-6 py-6 text-polar-100">
      <GlacierBackground />
      <div className="relative z-10 mx-auto max-w-7xl">
        <header className="mb-6 rounded-[2rem] border border-white/10 bg-white/[0.045] p-6 backdrop-blur-2xl">
          <div className="flex flex-wrap items-center justify-between gap-5">
            <div>
              <p className="font-display text-xs uppercase tracking-[0.52em] text-glacier/70">Task Detail / AI Restoration Pipeline</p>
              <h1 className="mt-3 text-4xl font-semibold tracking-[0.08em] text-white">核心修复任务</h1>
              <p className="mt-3 text-sm text-white/50">
                模式：{taskConfig?.mode || "fidelity"} · 倍率：{taskConfig?.scale || "2"}x · 格式：{taskConfig?.format || "png"}
              </p>
            </div>
            <div className="flex flex-wrap gap-3">
              <button type="button" onClick={onBackToDashboard} className="rounded-full border border-white/10 px-5 py-3 text-sm text-white/62 transition hover:bg-white/5">
                返回工作台
              </button>
              <button
                type="button"
                disabled={taskStatus !== "completed"}
                onClick={onViewCompare}
                className="rounded-full border border-glacier/45 bg-glacier/15 px-5 py-3 text-sm font-semibold tracking-[0.18em] text-glacier transition hover:bg-glacier/25 disabled:cursor-not-allowed disabled:border-white/10 disabled:bg-white/5 disabled:text-white/28"
              >
                查看对比
              </button>
            </div>
          </div>

          <div className="mt-6 h-2 overflow-hidden rounded-full bg-white/10">
            <div className="h-full rounded-full bg-gradient-to-r from-glacier via-aurora to-ember transition-all duration-500" style={{ width: `${progress}%` }} />
          </div>
          <div className="mt-3 flex justify-between text-xs tracking-[0.18em] text-white/38">
            <span>task_vmp_v03_core</span>
            <span>{progress}%</span>
          </div>
        </header>

        <div className="grid gap-6 lg:grid-cols-[0.92fr_1.08fr]">
          <ProgressTimeline currentStageIndex={currentStageIndex} taskStatus={taskStatus} />
          <RealtimeLogStream logs={logs} />
        </div>
      </div>
    </section>
  );
}
