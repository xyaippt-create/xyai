import React, { useEffect, useMemo, useRef, useState } from "react";

const API_BASE = "http://localhost:8787";
const EXPECTED_LOG_TOTAL = 11;
const PAGE_FOOTER = "© 2026 雪原系统. 保留所有权利。 V0.4 1080P Stable Delivery Pipeline";

const styles = {
  page: { backgroundColor: "#060b0c", fontFamily: "sans-serif" },
  headerBorder: { borderBottom: "1px solid #14282a" },
  card: { backgroundColor: "#091113", border: "1px solid #14282a", borderRadius: "8px" },
  innerCard: { backgroundColor: "#0d181a", border: "1px solid #193336", borderRadius: "4px" },
  progressBg: { backgroundColor: "#0e1d1f", borderRadius: "9999px" },
  progressBar: {
    background: "linear-gradient(90deg, #173a37 0%, #3cb3a0 50%, #8effed 100%)",
    boxShadow: "0 0 10px rgba(60,179,160,0.75)",
  },
  primaryButton: {
    borderRadius: "4px",
    border: "1px solid #2d665f",
    background: "linear-gradient(90deg, #1e4742 0%, #102d2a 100%)",
    color: "#5bf5dc",
    boxShadow: "0 0 12px rgba(45,102,95,0.2)",
  },
  disabledButton: {
    borderRadius: "4px",
    border: "1px solid #193336",
    backgroundColor: "#0b1517",
    color: "#526164",
  },
  secondaryButton: { border: "1px solid #193336", color: "#8a999c", borderRadius: "4px" },
  logBox: { backgroundColor: "#040708", border: "1px solid #0d1a1b", borderRadius: "4px" },
};

const timelines = [
  ["IMAGE INGEST", "图像读取", "读取前端上传图片，解析基础尺寸与任务上下文。"],
  ["VISUAL ANALYSIS", "视觉诊断", "识别文字区域、边缘结构、高光反射与压缩损伤。"],
  ["RESTORATION CORE", "核心修复", "执行压缩修复、结构补偿、文字清晰化与噪声控制。"],
  ["FIDELITY LOCK", "忠实校准", "锁定原图色彩，避免过锐、改色与画风重塑。"],
  ["QUALITY EXPORT", "质量输出", "生成 1080P 稳定交付结果，写入质量报告字段。"],
];

function normalizeUrl(endpoint, taskId) {
  if (endpoint) {
    if (/^https?:\/\//i.test(endpoint)) return endpoint;
    return `${API_BASE}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;
  }
  if (taskId) return `${API_BASE}/api/v1/tasks/${taskId}/stream`;
  return "";
}

function getTaskId(taskConfig) {
  return (
    taskConfig?.taskId ||
    taskConfig?.task_id ||
    taskConfig?.compareAssets?.taskId ||
    taskConfig?.compareAssets?.task_id ||
    ""
  );
}

function ProgressTimeline({ currentStageIndex, taskStatus }) {
  return (
    <div className="flex h-full w-[45%] flex-col p-4" style={styles.card}>
      <div className="mb-3 flex shrink-0 items-center justify-between">
        <h3 className="font-mono text-xs uppercase tracking-widest text-slate-400">Progress Timeline</h3>
        <span
          className="rounded-full border px-2 py-0.5 font-mono text-[10px] font-bold"
          style={{
            color: taskStatus === "failed" ? "#fb7185" : "#2ecc71",
            backgroundColor: taskStatus === "failed" ? "#2b1018" : "#102a1c",
            borderColor: taskStatus === "failed" ? "#7f1d1d" : "#1b4c32",
          }}
        >
          {taskStatus === "completed" ? "COMPLETED" : taskStatus === "failed" ? "FAILED" : "STREAMING"}
        </span>
      </div>

      <div className="flex min-h-0 flex-1 flex-col justify-between py-1">
        {timelines.map(([label, title, desc], index) => {
          const done = taskStatus === "completed" || index < currentStageIndex;
          const active = taskStatus !== "completed" && taskStatus !== "failed" && index === currentStageIndex;

          return (
            <div key={label} className="flex items-start space-x-3">
              <div className="flex h-full flex-col items-center">
                <div
                  className="flex h-5 w-5 items-center justify-center rounded-full border font-mono text-[10px] font-bold"
                  style={{
                    color: done ? "#2ecc71" : active ? "#8effed" : "#526164",
                    backgroundColor: done ? "#113025" : active ? "#102624" : "#0b1416",
                    borderColor: done ? "#2ecc71" : active ? "#3cb3a0" : "#26383a",
                  }}
                >
                  {done ? "✓" : index + 1}
                </div>
                {index !== timelines.length - 1 && (
                  <div className="my-1 min-h-[14px] w-px flex-1" style={{ background: done ? "linear-gradient(#2ecc71, #14282a)" : "linear-gradient(#274d52, #14282a)" }} />
                )}
              </div>
              <div className="flex min-h-0 flex-1 items-center justify-between p-2" style={styles.innerCard}>
                <div className="min-h-0 flex-1 pr-4">
                  <span className="mb-1 block font-mono text-[9px] uppercase leading-none tracking-wider" style={{ color: "#418c80" }}>
                    {label}
                  </span>
                  <h4 className="text-xs font-medium text-slate-200">{title}</h4>
                  <p className="mt-0.5 truncate text-[11px] text-slate-500">{desc}</p>
                </div>
                <span className="shrink-0 font-mono text-[10px] text-slate-400">{done ? "完成" : active ? "执行中" : "等待"}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function RealtimeLogStream({ logs, taskStatus }) {
  const logEndRef = useRef(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [logs]);

  return (
    <div className="flex h-full w-[55%] flex-col p-4" style={styles.card}>
      <div className="mb-3 flex shrink-0 items-center justify-between">
        <h3 className="flex items-center space-x-2 font-mono text-xs uppercase tracking-widest text-slate-400">
          <span>Realtime SSE Log</span>
          <span
            className="h-1.5 w-1.5 animate-pulse rounded-full"
            style={{
              backgroundColor: taskStatus === "failed" ? "#f43f5e" : "#2ecc71",
              boxShadow: taskStatus === "failed" ? "0 0 6px #f43f5e" : "0 0 6px #2ecc71",
            }}
          />
        </h3>
        <span className="font-mono text-[10px] text-slate-500">RESTORATION.LOG</span>
      </div>

      <div className="flex min-h-0 w-full flex-1 flex-col space-y-1.5 overflow-y-auto p-3 font-mono text-[11px] leading-relaxed select-text" style={styles.logBox}>
        {logs.map((log, index) => {
          const important = index === 0 || index === logs.length - 1 || String(log).includes("任务完成");
          return (
            <div key={`${log}-${index}`} className="whitespace-pre-wrap" style={{ color: important ? "#3cb3a0" : "#8a999c", fontWeight: important ? "bold" : "normal" }}>
              {String(index + 1).padStart(2, "0")} {log}
            </div>
          );
        })}
        {taskStatus === "processing" && (
          <div className="animate-pulse whitespace-pre-wrap font-bold text-[#3cb3a0]">
            {String(logs.length + 1).padStart(2, "0")} 等待修复日志流...
          </div>
        )}
        {taskStatus === "failed" && <div className="whitespace-pre-wrap font-bold text-rose-400">!! SSE 连接中断，请确认本地后端服务 http://localhost:8787 已启动。</div>}
        <div ref={logEndRef} />
      </div>
    </div>
  );
}

export default function TaskDetailPage({
  taskConfig,
  onBackToDashboard,
  onViewCompare,
  disableAutoStream = false,
  logsOverride = null,
  taskStatusOverride = null,
  progressOverride = null,
}) {
  const [logs, setLogs] = useState([]);
  const [currentStageIndex, setCurrentStageIndex] = useState(0);
  const [taskStatus, setTaskStatus] = useState("processing");
  const [progress, setProgress] = useState(0);

  const taskId = useMemo(() => getTaskId(taskConfig), [taskConfig]);
  const streamUrl = useMemo(() => normalizeUrl(taskConfig?.streamEndpoint || taskConfig?.compareAssets?.streamEndpoint, taskId), [taskConfig, taskId]);
  const result = taskConfig?.task_result || taskConfig?.compareAssets?.task_result || {};
  const report = taskConfig?.task_report || taskConfig?.compareAssets?.task_report || null;
  const mode = taskConfig?.mode || taskConfig?.compareAssets?.mode || "fidelity";
  const format = result.output_format || taskConfig?.output_format || taskConfig?.format || "auto";
  const target = result.target_resolution || "1080P 稳定交付";

  useEffect(() => {
    if (disableAutoStream) {
      const nextLogs = Array.isArray(logsOverride) ? logsOverride : [];
      const nextProgress = Number(progressOverride || 0);
      const nextStatus = taskStatusOverride || (nextProgress >= 100 ? "completed" : "processing");
      setLogs(nextLogs);
      setProgress(nextProgress);
      setTaskStatus(nextStatus);
      setCurrentStageIndex(nextStatus === "completed" ? timelines.length : Math.min(timelines.length - 1, Math.floor((nextProgress / 100) * timelines.length)));
      return () => {};
    }

    setLogs([]);
    setCurrentStageIndex(0);
    setTaskStatus("processing");
    setProgress(0);

    if (!streamUrl) {
      setLogs(["缺少 streamEndpoint，无法连接后端 SSE 任务流。"]);
      setTaskStatus("failed");
      return () => {};
    }

    const eventSource = new EventSource(streamUrl);

    eventSource.onmessage = (event) => {
      if (event.data === "[DONE]") {
        eventSource.close();
        setCurrentStageIndex(timelines.length);
        setProgress(100);
        setTaskStatus("completed");
      }
    };

    eventSource.addEventListener("restoration.log", (event) => {
      try {
        if (event.data === "[DONE]") {
          eventSource.close();
          setCurrentStageIndex(timelines.length);
          setProgress(100);
          setTaskStatus("completed");
          return;
        }
        const payload = JSON.parse(event.data);
        const index = Number(payload.index || 0);
        const total = Number(payload.total || EXPECTED_LOG_TOTAL);
        const message = payload.message || "收到空日志包";
        const nextProgress = total > 0 ? Math.round((index / total) * 100) : 0;

        setLogs((prev) => [...prev, message]);
        setProgress(Math.min(100, nextProgress));
        setCurrentStageIndex(Math.min(timelines.length - 1, Math.floor((nextProgress / 100) * timelines.length)));

        if (payload.done === true || index >= total) {
          eventSource.close();
          setCurrentStageIndex(timelines.length);
          setProgress(100);
          setTaskStatus("completed");
        }
      } catch {
        setLogs((prev) => [...prev, "SSE 数据解析失败，请检查后端 restoration.log 格式。"]);
        setTaskStatus("failed");
        eventSource.close();
      }
    });

    eventSource.onerror = () => {
      setLogs((prev) => [...prev, "SSE 连接失败，请先启动本地后端服务。"]);
      setTaskStatus("failed");
      eventSource.close();
    };

    return () => eventSource.close();
  }, [disableAutoStream, logsOverride, progressOverride, streamUrl, taskStatusOverride]);

  return (
    <div className="flex h-[100dvh] w-full select-none flex-col overflow-hidden p-6 text-slate-200" style={styles.page}>
      <div className="mb-4 flex shrink-0 items-start justify-between pb-4" style={styles.headerBorder}>
        <div>
          <span className="mb-1 block font-mono text-[10px] font-bold uppercase tracking-[0.2em]" style={{ color: "#418c80" }}>
            V0.4 / 1080P Stable Delivery Pipeline
          </span>
          <h1 className="flex items-center space-x-3 text-2xl font-semibold tracking-wide text-slate-100">
            <span>核心修复任务</span>
            <span className="px-2 py-0.5 font-mono text-xs font-normal" style={styles.innerCard}>
              {taskId || "等待 taskId"}
            </span>
          </h1>
          <p className="mt-1 font-mono text-xs text-slate-500">
            模式: <span className="text-slate-400">{mode}</span> · 目标规格: <span className="text-slate-400">{target}</span> · 格式:{" "}
            <span className="text-slate-400">{format}</span> · 质量报告: <span className="text-slate-400">{report ? "已绑定" : "等待生成"}</span>
          </p>
        </div>

        <div className="mt-1 flex space-x-3">
          <button type="button" onClick={onBackToDashboard} className="px-4 py-1.5 text-xs tracking-wide transition-all duration-300 hover:bg-[#112426] hover:text-slate-200" style={styles.secondaryButton}>
            返回工作台
          </button>
          <button
            type="button"
            disabled={taskStatus !== "completed"}
            onClick={onViewCompare}
            className={`px-5 py-1.5 font-mono text-xs font-bold uppercase tracking-widest transition-all duration-300 ${taskStatus === "completed" ? "hover:brightness-125" : "cursor-not-allowed"}`}
            style={taskStatus === "completed" ? styles.primaryButton : styles.disabledButton}
          >
            查看高清对比
          </button>
        </div>
      </div>

      <div className="mb-6 w-full shrink-0">
        <div className="relative h-[3px] w-full overflow-hidden" style={styles.progressBg}>
          <div className="absolute left-0 top-0 h-full transition-all duration-500" style={{ ...styles.progressBar, width: `${progress}%` }} />
        </div>
        <div className="mt-1.5 flex items-center justify-between font-mono text-[10px] text-slate-500">
          <span>PIPELINE EXECUTION STATE</span>
          <span className="font-bold" style={{ color: "#3cb3a0" }}>
            {taskStatus === "completed" ? "100% COMPLETE" : taskStatus === "failed" ? "STREAM FAILED" : `${progress}% STREAMING`}
          </span>
        </div>
      </div>

      <div className="flex min-h-0 w-full flex-1 space-x-6 pb-4">
        <ProgressTimeline currentStageIndex={currentStageIndex} taskStatus={taskStatus} />
        <RealtimeLogStream logs={logs} taskStatus={taskStatus} />
      </div>

      <footer className="mt-auto w-full shrink-0 border-t border-[#0e1d1f] py-1 text-center font-mono text-[10px] tracking-wider text-slate-600">{PAGE_FOOTER}</footer>
    </div>
  );
}
