import React, { useMemo, useState } from "react";

const API_BASE = "http://localhost:8787";
const DEFAULT_INPUT_DIR = "D:\\影界文件\\真实业务测试_6张";
const DEFAULT_OUTPUT_DIR = "runtime/experiments/safe_1080p_beta";

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
  const [error, setError] = useState("");

  const summary = result?.data || {};
  const verification = result?.verification_result || summary?.verification_result || "";
  const processed = summary?.processed_count ?? 0;
  const skipped = summary?.skipped_count ?? 0;
  const outputPath = summary?.output_dir || "";
  const hasEnhanced = processed > 0;
  const hasContactSheet = Array.isArray(summary?.processed) && summary.processed.every((item) => item.contact_sheet);

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
    setRunning(true);
    setError("");
    setResult(null);
    try {
      const response = await fetch(`${API_BASE}/api/beta/safe-1080p/enhance`, {
        method: "POST",
        headers: { "Content-Type": "application/json;charset=UTF-8" },
        body: JSON.stringify({
          input_dir: inputDir,
          output_dir: outputDir,
          mode: "safe_1080p",
        }),
      });
      const payload = await response.json();
      setResult(payload);
      if (!response.ok || payload.success === false) {
        setError(payload.message || "Beta 运行失败");
      }
    } catch (requestError) {
      setError(requestError.message || "无法连接 Beta 接口");
    } finally {
      setRunning(false);
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
            {running ? "运行中..." : "开始安全增强 Beta"}
          </button>

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
            <ResultLine label="生成 enhanced 图" value={hasEnhanced ? `是，${processed} 张` : "否"} />
            <ResultLine label="生成 contact sheet" value={hasContactSheet ? `是，${processed} 张` : "否"} />
            <ResultLine label="跳过图片" value={skipped ? `${skipped} 张` : "无"} />
            <ResultLine label="BLOCKED 原因" value={summary.reason || result?.message || ""} />
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
