import React, { useEffect, useRef, useState } from "react";

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

const API_BASE = "http://localhost:8787";
const EXPECTED_LOG_TOTAL = 11;
const PAGE_FOOTER = "© 2026 雪原系统. 保留所有权利。 V0.3 CORE Restorator Pipeline";

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
    <section className="rounded-lg border border-white/10 bg-white/[0.045] p-6 shadow-cinematic backdrop-blur-xl">
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
              <div className={`rounded-lg border p-4 ${active ? "border-glacier/35 bg-glacier/10" : "border-white/10 bg-polar-900/65"}`}>
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

function RealtimeLogStream({ logs, taskStatus }) {
  const logEndRef = useRef(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [logs]);

  return (
    <section className="rounded-lg border border-white/10 bg-[#02080a]/80 p-6 shadow-cinematic backdrop-blur-xl">
      <div className="mb-5 flex items-center justify-between gap-4">
        <div>
          <p className="font-display text-xs uppercase tracking-[0.42em] text-aurora/70">Realtime Log Stream</p>
          <h2 className="mt-3 text-2xl font-semibold text-white">SSE 实时修复日志</h2>
        </div>
        <span className="h-3 w-3 rounded-full bg-aurora shadow-[0_0_22px_rgba(183,255,212,0.9)]" />
      </div>
      <div className="h-[27rem] overflow-y-auto rounded-lg border border-aurora/10 bg-black/45 p-4 font-mono text-xs leading-7 text-aurora/82">
        {logs.map((line, index) => (
          <div key={`${line}-${index}`} className="flex gap-3 border-b border-white/[0.035] py-1">
            <span className="w-12 shrink-0 text-white/24">{String(index + 1).padStart(2, "0")}</span>
            <span>{line}</span>
          </div>
        ))}
        {taskStatus !== "completed" && (
          <div className="mt-2 flex gap-3 text-glacier">
            <span className="w-12 shrink-0 text-white/24">...</span>
            <span className="animate-pulse">{taskStatus === "failed" ? "stream connection interrupted" : "stream packet receiving"}</span>
          </div>
        )}
        <div ref={logEndRef} />
      </div>
    </section>
  );
}

export default function TaskDetailPage({ taskConfig, onBackToDashboard, onViewCompare }) {
  const [logs, setLogs] = useState([]);
  const [currentStageIndex, setCurrentStageIndex] = useState(0);
  const [taskStatus, setTaskStatus] = useState("processing");
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    setLogs([]);
    setCurrentStageIndex(0);
    setTaskStatus("processing");
    setProgress(0);

    const eventSource = new EventSource(`${API_BASE}/api/stream`);

    eventSource.addEventListener("restoration.log", (event) => {
      try {
        const payload = JSON.parse(event.data);
        const index = Number(payload.index || 0);
        const total = Number(payload.total || EXPECTED_LOG_TOTAL);
        const message = payload.message || "接收到空日志包";
        const nextProgress = total > 0 ? Math.round((index / total) * 100) : 0;

        setLogs((prev) => [...prev, message]);
        setProgress(Math.min(100, nextProgress));
        setCurrentStageIndex(Math.min(stages.length - 1, Math.floor((nextProgress / 100) * stages.length)));

        if (payload.done === true || index >= total) {
          eventSource.close();
          setCurrentStageIndex(stages.length);
          setProgress(100);
          setTaskStatus("completed");
        }
      } catch (error) {
        setLogs((prev) => [...prev, "SSE 数据解析失败：请检查后端日志格式。"]);
        setTaskStatus("failed");
        eventSource.close();
      }
    });

    eventSource.onerror = () => {
      setLogs((prev) => [...prev, "SSE 连接中断：请确认后端服务 http://localhost:8787 已启动。"]);
      setTaskStatus("failed");
      eventSource.close();
    };

    return () => eventSource.close();
  }, []);

  return (
    <section className="relative min-h-screen overflow-hidden px-6 py-6 text-polar-100">
      <GlacierBackground />
      <div className="relative z-10 mx-auto max-w-7xl">
        <header className="mb-6 rounded-lg border border-white/10 bg-white/[0.045] p-6 backdrop-blur-2xl">
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
                className={`rounded-full px-5 py-3 text-sm font-semibold tracking-[0.18em] transition disabled:cursor-not-allowed ${
                  taskStatus === "completed"
                    ? "border border-glacier/60 bg-glacier/20 text-glacier shadow-[0_0_32px_rgba(143,244,255,0.28)] animate-pulse hover:bg-glacier/30"
                    : "border border-white/10 bg-white/5 text-white/28"
                }`}
              >
                进入 8K 滑杆对比
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
          <RealtimeLogStream logs={logs} taskStatus={taskStatus} />
        </div>
      </div>
      <footer className="pointer-events-none absolute bottom-4 left-0 right-0 z-20 text-center font-display text-[0.62rem] tracking-[0.24em] text-white/24">
        {PAGE_FOOTER}
      </footer>
    </section>
  );
}
