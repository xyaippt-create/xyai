import React, { useEffect, useMemo, useState } from "react";

const API_BASE = "http://localhost:8787";
const DEFAULT_INPUT_DIR = "D:\\影界文件\\真实业务测试_6张";
const DEFAULT_OUTPUT_DIR = "D:\\影界文件\\1080P安全增强输出";

function statusTone(status) {
  if (status === "PASS") return "border-emerald-400/45 bg-emerald-400/10 text-emerald-200";
  if (status === "PASS_WITH_NOTES") return "border-amber-300/45 bg-amber-300/10 text-amber-100";
  if (status === "BLOCKED") return "border-red-300/45 bg-red-300/10 text-red-100";
  return "border-white/15 bg-white/5 text-white/55";
}

function ResultLine({ label, value }) {
  return (
    <div className="grid grid-cols-[180px_minmax(0,1fr)] gap-4 border-b border-white/8 py-3 text-sm">
      <div className="text-white/45">{label}</div>
      <div className="break-all text-white/78">{value || "--"}</div>
    </div>
  );
}

export default function Safe1080pBetaPage({ onBackToDashboard }) {
  const [inputDir, setInputDir] = useState(DEFAULT_INPUT_DIR);
  const [outputDir, setOutputDir] = useState(DEFAULT_OUTPUT_DIR);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [feedbackResult, setFeedbackResult] = useState(null);
  const [error, setError] = useState("");
  const [startedAt, setStartedAt] = useState(null);
  const [tick, setTick] = useState(0);

  const summary = result?.data || {};
  const verification = result?.verification_result || summary?.verification_result || "";
  const processed = summary?.processed_count ?? 0;
  const skipped = summary?.skipped_count ?? 0;
  const outputPath = summary?.output_dir || "";
  const processedItems = Array.isArray(summary?.processed) ? summary.processed : [];
  const enhancedCount = summary?.enhanced_count ?? processedItems.filter((item) => item.enhanced).length;
  const contactSheetCount = summary?.contact_sheet_count ?? processedItems.filter((item) => item.contact_sheet).length;
  const hasEnhanced = running || enhancedCount > 0;
  const hasContactSheet = running || contactSheetCount > 0;
  const elapsedSeconds = running && startedAt ? Math.max(0, Math.round((Date.now() - startedAt) / 1000) + tick * 0) : summary?.elapsed_seconds || 0;

  useEffect(() => {
    if (!running) return () => {};
    const timer = window.setInterval(() => setTick((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  const boundaryItems = useMemo(
    () => [
      "当前仅建议用于中文商业非人像图",
      "适合中文信息图、产品图、文旅地图、城市科技主视觉、PPT封面",
      "人像 / 面部主体图暂不建议使用",
      "不支持通用4K超分",
      "不支持低清照片真实修复",
      "不替代普通高清交付流程",
      "输出结果需要人工查看后决定是否使用",
    ],
    [],
  );

  const runBeta = async () => {
    const started = Date.now();
    setRunning(true);
    setStartedAt(started);
    setTick(0);
    setError("");
    setResult({
      verification_result: "RUNNING",
      data: {
        status: "running",
        verification_result: "RUNNING",
        mode: "safe_1080p",
        input_dir: inputDir,
        output_dir: outputDir,
        progress: 1,
        current_file: "正在连接 Beta 后端",
        processed_count: 0,
        enhanced_count: 0,
        contact_sheet_count: 0,
        skipped_count: 0,
        elapsed_seconds: 0,
        processed: [],
        skipped: [],
      },
    });
    setFeedbackResult(null);
    const stageTimers = [
      window.setTimeout(() => {
        setResult((prev) => (prev?.verification_result === "RUNNING" ? { ...prev, data: { ...prev.data, progress: 15, current_file: "正在读取图片" } } : prev));
      }, 250),
      window.setTimeout(() => {
        setResult((prev) => (prev?.verification_result === "RUNNING" ? { ...prev, data: { ...prev.data, progress: 35, current_file: "正在执行 1080P安全增强，处理中请稍候" } } : prev));
      }, 1000),
    ];
    try {
      const response = await fetch(`${API_BASE}/api/beta/safe-1080p/enhance`, {
        method: "POST",
        headers: { "Content-Type": "application/json;charset=UTF-8" },
        body: JSON.stringify({
          input_dir: inputDir,
          output_dir: outputDir,
          mode: "safe_1080p",
          flat_output: true,
          business_output: true,
        }),
      });
      const payload = await response.json();
      const data = payload?.data || {};
      const items = Array.isArray(data.processed) ? data.processed : [];
      setResult({
        ...payload,
        data: {
          ...data,
          progress: 100,
          current_file: items[items.length - 1]?.file || "处理完成",
          enhanced_count: items.filter((item) => item.enhanced).length,
          contact_sheet_count: items.filter((item) => item.contact_sheet).length,
          elapsed_seconds: data.elapsed_seconds || Math.round((Date.now() - started) / 1000),
        },
      });
      if (!response.ok || payload.success === false) {
        setError(payload.message || "Beta run failed");
      }
    } catch (requestError) {
      setResult({
        verification_result: "BLOCKED",
        data: {
          status: "blocked",
          verification_result: "BLOCKED",
          mode: "safe_1080p",
          input_dir: inputDir,
          output_dir: outputDir,
          progress: 100,
          current_file: "BLOCKED",
          processed_count: 0,
          enhanced_count: 0,
          contact_sheet_count: 0,
          skipped_count: 0,
          elapsed_seconds: Math.round((Date.now() - started) / 1000),
          processed: [],
          skipped: [],
        },
      });
      setError(requestError.message || "Cannot connect to Beta API");
    } finally {
      stageTimers.forEach((timer) => window.clearTimeout(timer));
      setRunning(false);
    }
  };
  const exportFeedbackPackage = async () => {
    if (!summary?.output_dir) return;
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/beta/safe-1080p/feedback-package`, {
        method: "POST",
        headers: { "Content-Type": "application/json;charset=UTF-8" },
        body: JSON.stringify({
          run_result: summary,
        }),
      });
      const payload = await response.json();
      setFeedbackResult(payload?.data || payload);
      if (!response.ok || payload.success === false) {
        setError(payload.message || "反馈包导出失败");
      }
    } catch (requestError) {
      setError(requestError.message || "无法导出测试反馈包");
    }
  };

  return (
    <section className="flex h-screen w-screen flex-col overflow-hidden bg-[#090e10] text-slate-100">
      <header className="flex items-center justify-between border-b border-white/10 px-8 py-5">
        <div>
          <p className="font-mono text-xs uppercase tracking-[0.28em] text-[#7af4df]">Independent Beta</p>
          <h1 className="mt-2 text-2xl font-semibold text-white">1080P安全增强 Beta</h1>
          <p className="mt-1 text-sm text-white/55">中文商业非人像图离线候选入口，不替代普通高清交付流程。</p>
        </div>
        <button
          type="button"
          onClick={onBackToDashboard}
          className="rounded-md border border-white/15 px-4 py-2 text-sm text-white/68 transition hover:border-white/35 hover:text-white"
        >
          返回主工作台
        </button>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(360px,420px)_minmax(0,1fr)] gap-6 overflow-hidden p-6">
        <aside className="min-h-0 overflow-auto rounded-lg border border-white/10 bg-white/[0.035] p-5">
          <div>
            <label className="text-xs uppercase tracking-[0.22em] text-white/42">输入目录</label>
            <input
              value={inputDir}
              onChange={(event) => setInputDir(event.target.value)}
              className="mt-2 w-full rounded-md border border-white/12 bg-black/25 px-3 py-2 text-sm text-white/80 outline-none focus:border-[#7af4df]/60"
            />
          </div>
          <div className="mt-5">
            <label className="text-xs uppercase tracking-[0.22em] text-white/42">输出目录</label>
            <input
              value={outputDir}
              onChange={(event) => setOutputDir(event.target.value)}
              className="mt-2 w-full rounded-md border border-white/12 bg-black/25 px-3 py-2 text-sm text-white/80 outline-none focus:border-[#7af4df]/60"
            />
          </div>
          <div className="mt-5 rounded-md border border-[#7af4df]/20 bg-[#7af4df]/5 p-4">
            <div className="text-xs uppercase tracking-[0.22em] text-[#7af4df]">当前策略</div>
            <div className="mt-2 text-lg font-semibold text-white">35% protected</div>
            <p className="mt-2 text-sm leading-6 text-white/58">疑似人像或不确定类型会跳过；外部模型缺失时直接返回 BLOCKED。</p>
          </div>
          <button
            type="button"
            onClick={runBeta}
            disabled={running}
            className="mt-5 w-full rounded-md bg-[#7af4df] px-4 py-3 text-sm font-semibold text-[#06211d] transition hover:bg-[#9cffef] disabled:cursor-not-allowed disabled:bg-white/18 disabled:text-white/38"
          >
            {running ? "安全增强处理中..." : "开始安全增强 Beta"}
          </button>

          <button
            type="button"
            onClick={exportFeedbackPackage}
            disabled={!summary?.output_dir || running}
            className="mt-3 w-full rounded-md border border-[#7af4df]/45 px-4 py-3 text-sm font-semibold text-[#7af4df] transition hover:border-[#9cffef] hover:text-[#9cffef] disabled:cursor-not-allowed disabled:border-white/12 disabled:text-white/30"
          >
            导出测试反馈包
          </button>
          <p className="mt-2 text-xs leading-5 text-white/42">
            生成本次测试的运行报告、错误日志、系统环境和对比图，用于发送给开发者定位问题。
          </p>

          <div className="mt-6">
            <div className="text-xs uppercase tracking-[0.22em] text-white/42">功能边界</div>
            <div className="mt-3 space-y-2">
              {boundaryItems.map((item) => (
                <div key={item} className="rounded-md border border-white/8 bg-black/15 px-3 py-2 text-sm text-white/62">
                  {item}
                </div>
              ))}
            </div>
          </div>
        </aside>

        <main className="min-h-0 overflow-auto rounded-lg border border-white/10 bg-[#101819] p-6">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="font-mono text-xs uppercase tracking-[0.24em] text-white/42">Run Status</p>
              <h2 className="mt-2 text-xl font-semibold text-white">运行结果</h2>
            </div>
            <span className={`rounded-full border px-4 py-1 text-xs font-semibold tracking-[0.18em] ${statusTone(verification)}`}>
              {verification || (running ? "RUNNING" : "WAITING")}
            </span>
          </div>

          {error ? <div className="mt-5 rounded-md border border-red-300/35 bg-red-300/10 px-4 py-3 text-sm text-red-100">{error}</div> : null}

          <div className="mt-5 rounded-lg border border-white/10 bg-black/15 px-5">
            <ResultLine label="输入目录" value={summary.input_dir || inputDir} />
            <ResultLine label="输出目录" value={outputPath || outputDir} />
            <ResultLine label="模式" value={summary.mode || "safe_1080p"} />
            <ResultLine label="状态" value={verification || (running ? "RUNNING" : "WAITING")} />
            <ResultLine label="生成 enhanced 图" value={running ? "处理中" : hasEnhanced ? `是，${processed} 张` : "否"} />
            <ResultLine label="生成 contact sheet" value={running ? "生成中" : hasContactSheet ? `是，${processed} 张` : "否"} />
            <ResultLine label="跳过图片" value={skipped ? `${skipped} 张` : "无"} />
            <ResultLine label="progress" value={`${summary.progress ?? 0}%`} />
            <ResultLine label="current file" value={summary.current_file || "WAITING"} />
            <ResultLine label="enhanced count" value={running ? "处理中" : String(enhancedCount)} />
            <ResultLine label="contact sheet count" value={running ? "生成中" : String(contactSheetCount)} />
            <ResultLine label="elapsed" value={`${elapsedSeconds}s`} />
            <ResultLine label="BLOCKED 原因" value={summary.reason || result?.message || ""} />
            <ResultLine label="测试反馈包" value={feedbackResult?.feedback_zip_path || ""} />
          </div>

          <div className="mt-5 grid gap-3">
            {(summary.processed || []).map((item) => (
              <div key={item.file} className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
                <div className="font-medium text-white">{item.file}</div>
                <div className="mt-2 grid gap-2 text-xs text-white/55 md:grid-cols-3">
                  <span>enhanced: {item.enhanced}</span>
                  <span>contact: {item.contact_sheet}</span>
                  <span>type: {item.type}</span>
                </div>
              </div>
            ))}
          </div>
        </main>
      </div>
    </section>
  );
}
