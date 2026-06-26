import React, { useMemo, useRef, useState } from "react";
import { resolveDeliveryStatus } from "./deliveryStatus.js";

const API_BASE = "http://localhost:8787";
const PAGE_FOOTER = "影界 HDDE V0.4.6 RC1 · HD Delivery Engine · 中文视觉高清交付引擎";

const styles = {
  page: { backgroundColor: "#060b0c", fontFamily: "sans-serif" },
  card: { backgroundColor: "#091113", border: "1px solid #132628", borderRadius: "8px" },
  innerCard: { backgroundColor: "#0d181a", border: "1px solid #193336", borderRadius: "4px" },
  primaryButton: {
    borderRadius: "4px",
    border: "1px solid #2d665f",
    background: "#163631",
    color: "#5bf5dc",
  },
  secondaryButton: { border: "1px solid #193336", color: "#8a999c", borderRadius: "4px" },
};

const reviewItems = [
  "小字边界是否更清楚，并且没有白边或黑边",
  "建筑线条或真实结构是否更稳定",
  "高光与玻璃反射是否得到保护",
  "输出颜色是否仍然接近原图",
  "增强结果是否真实有效，而不是单纯文件变大",
];

function normalizeUrl(url) {
  if (!url) return "";
  if (/^[a-zA-Z]:[\\/]/.test(url)) return "";
  if (/^https?:\/\//i.test(url)) return url;
  return `${API_BASE}${url.startsWith("/") ? url : `/${url}`}`;
}

function unwrapTaskPayload(taskConfig, compareAssets) {
  const direct = compareAssets || taskConfig?.compareAssets || taskConfig || {};
  const nested = direct.data || taskConfig?.data || {};
  const taskResult = direct.task_result || nested.task_result || taskConfig?.task_result || {};
  const taskReport = direct.task_report || nested.task_report || taskConfig?.task_report || taskResult.task_report || {};

  return {
    ...nested,
    ...direct,
    task_result: taskResult,
    task_report: taskReport,
  };
}

function resolveAssets(taskConfig, compareAssets) {
  const currentTask = unwrapTaskPayload(taskConfig, compareAssets);
  const result = currentTask.task_result || {};
  const report = currentTask.task_report || {};
  const debugQuality = currentTask.debug_quality || result.debug_quality || {};
  const deliveryMeta = resolveDeliveryStatus(debugQuality, result, report, currentTask);
  const enhancedImgSrc = result.preview_output_url || currentTask.preview_output_url || result.final_output_url || currentTask.final_output_url;
  const originalImgSrc = currentTask.originalUrl || currentTask.original_url || currentTask.input_url || result.original_url || result.input_url;

  return {
    originalUrl: normalizeUrl(originalImgSrc),
    enhancedUrl: normalizeUrl(enhancedImgSrc),
    finalOutputUrl: normalizeUrl(result.final_output_url || currentTask.final_output_url),
    previewOutputUrl: normalizeUrl(result.preview_output_url || currentTask.preview_output_url),
    finalDeliveryStatus: deliveryMeta.status,
    deliveryMeta,
    finalDeliveryReason: result.final_delivery_reason || currentTask.final_delivery_reason || currentTask.debug_quality?.final_delivery_reason || "",
    fileName: currentTask.fileName || currentTask.filename || result.output_filename || result.input_filename || "等待真实上传资产",
    mode: currentTask.mode || taskConfig?.mode || "fidelity",
    result,
    report,
  };
}

function metricValue(report, result, key) {
  if (key === "text_clarity_score") return report.text_clarity_score || result.pixel_diff_score || 0;
  if (key === "edge_quality_score") return report.edge_quality_score || 0;
  if (key === "color_fidelity_score") return report.color_fidelity_score || 0;
  if (key === "texture_score") return report.texture_score || 0;
  return 0;
}

const qaMetrics = [
  ["TEXT CLARITY", "文字清晰度", "text_clarity_score"],
  ["EDGE QUALITY", "边缘质量", "edge_quality_score"],
  ["COLOR FIDELITY", "色彩忠实度", "color_fidelity_score"],
  ["TEXTURE", "纹理保持力", "texture_score"],
];

function PolarBackdrop() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="absolute inset-0 bg-[#060b0c]" />
      <div className="absolute inset-x-0 top-0 h-px bg-[#263738]" />
    </div>
  );
}

function EmptyImagePlane({ label, error }) {
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-[#05090a]">
      <div className="max-w-md px-8 text-center">
        <div className={`mx-auto mb-4 h-12 w-12 rounded-full border ${error ? "border-rose-400/45 bg-rose-500/10" : "border-[#3cb3a0]/45 bg-[#3cb3a0]/10"}`} />
        <p className={`font-mono text-xs uppercase tracking-[0.28em] ${error ? "text-rose-300" : "text-[#3cb3a0]/70"}`}>{label}</p>
        <p className="mt-3 text-sm leading-7 text-slate-500">
          {error ? "高清资产加载失败，请检查后端 8787 映射路径。" : "等待工作台上传返回真实图像路径。"}
        </p>
      </div>
    </div>
  );
}

function ImagePlane({ src, alt, dim = false, onError }) {
  if (!src) return <EmptyImagePlane label={alt} />;
  return (
    <>
      <img src={src} alt={alt} draggable={false} className="absolute inset-0 h-full w-full object-contain" onError={onError} />
      <div className={`absolute inset-0 ${dim ? "bg-black/10" : "bg-black/0"}`} />
    </>
  );
}

function ZoomGlass({ zoom, originalUrl, enhancedUrl, split }) {
  if (!zoom.active || !enhancedUrl) return null;
  const showOriginal = originalUrl && zoom.xPct <= split;
  const base = {
    backgroundSize: "260% 260%",
    backgroundPosition: `${zoom.xPct}% ${zoom.yPct}%`,
    backgroundRepeat: "no-repeat",
  };

  return (
    <div
      className="pointer-events-none absolute z-40 h-48 w-48 overflow-hidden rounded-lg border border-[#3cb3a0] bg-[#040708]/80 shadow-[0_0_55px_rgba(60,179,160,0.38)] backdrop-blur-md"
      style={{ left: zoom.x, top: zoom.y, transform: "translate(-50%, -50%)" }}
    >
      <div className="absolute inset-0" style={{ ...base, backgroundImage: `url("${enhancedUrl}")` }} />
      {showOriginal && <div className="absolute inset-0" style={{ ...base, backgroundImage: `url("${originalUrl}")` }} />}
      <div className="absolute inset-0 bg-[repeating-linear-gradient(90deg,rgba(255,255,255,0.10)_0px,transparent_1px,transparent_12px),repeating-linear-gradient(0deg,rgba(255,255,255,0.08)_0px,transparent_1px,transparent_12px)] opacity-45" />
      <div className="absolute bottom-2 left-2 right-2 truncate rounded bg-black/65 px-2 py-1 text-center font-mono text-[10px] tracking-[0.18em] text-[#8effed]">
        高清局部对比 · {zoom.xPct}% / {zoom.yPct}%
      </div>
    </div>
  );
}

function SliderCompareStage({ originalUrl, enhancedUrl, fileName, deliveryBadge }) {
  const stageRef = useRef(null);
  const [split, setSplit] = useState(50);
  const [dragging, setDragging] = useState(false);
  const [zoom, setZoom] = useState({ active: false, x: 0, y: 0, xPct: 50, yPct: 50 });
  const [loadError, setLoadError] = useState(false);

  const updatePointer = (clientX, clientY, shouldMoveSplit) => {
    const rect = stageRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = Math.min(Math.max(clientX - rect.left, 0), rect.width);
    const y = Math.min(Math.max(clientY - rect.top, 0), rect.height);
    const xPct = Math.round((x / rect.width) * 100);
    const yPct = Math.round((y / rect.height) * 100);
    if (shouldMoveSplit) setSplit(xPct);
    setZoom({ active: true, x, y, xPct, yPct });
  };

  return (
    <div
      ref={stageRef}
      className="relative h-full min-h-0 overflow-hidden rounded-lg border border-[#193336] bg-[#040708] shadow-[0_40px_140px_rgba(60,179,160,0.14)]"
      onMouseMove={(event) => updatePointer(event.clientX, event.clientY, dragging)}
      onMouseDown={(event) => {
        setDragging(true);
        updatePointer(event.clientX, event.clientY, true);
      }}
      onMouseUp={() => setDragging(false)}
      onMouseLeave={() => {
        setDragging(false);
        setZoom((prev) => ({ ...prev, active: false }));
      }}
    >
      {loadError ? (
        <EmptyImagePlane label="资产加载失败" error />
      ) : (
        <>
          <div className="absolute inset-0">
            <ImagePlane src={enhancedUrl} alt={deliveryBadge} onError={() => setLoadError(true)} />
          </div>
          <div className="absolute inset-0 overflow-hidden" style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }}>
            <ImagePlane src={originalUrl} alt="原图" dim onError={() => {}} />
          </div>
        </>
      )}

      <div className="absolute inset-y-0 z-30 w-px bg-white/85 shadow-[0_0_26px_rgba(142,255,237,0.85)]" style={{ left: `${split}%` }}>
        <button
          type="button"
          aria-label="拖动对比滑杆"
          className="absolute left-1/2 top-1/2 flex h-16 w-16 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-[#8effed]/75 bg-[#060b0c]/90 font-mono text-[10px] tracking-[0.2em] text-[#8effed] backdrop-blur-xl"
          onMouseDown={(event) => {
            event.stopPropagation();
            setDragging(true);
          }}
        >
          DRAG
        </button>
      </div>

      <div className="absolute left-5 top-5 z-20 rounded border border-white/10 bg-black/45 px-4 py-2 font-mono text-[10px] uppercase tracking-[0.24em] text-white/50 backdrop-blur-md">
        Original
      </div>
      <div className="absolute right-5 top-5 z-20 rounded border border-[#3cb3a0]/35 bg-[#3cb3a0]/10 px-4 py-2 font-mono text-[10px] uppercase tracking-[0.24em] text-[#8effed] backdrop-blur-md">
        {deliveryBadge}
      </div>
      <div className="absolute bottom-4 right-4 z-20 max-w-[85%] truncate rounded border border-white/10 bg-black/55 px-4 py-2 text-right font-mono text-[10px] tracking-[0.2em] text-white/40 backdrop-blur-md">
        影界 HDDE V0.4 · {fileName || "等待真实上传资产"} · HD Delivery Engine
      </div>
      <ZoomGlass zoom={zoom} originalUrl={originalUrl} enhancedUrl={enhancedUrl} split={split} />
    </div>
  );
}

function QualityPanel({ assets }) {
  const report = assets.report || {};
  const result = assets.result || {};
  const deliveryMeta = assets.deliveryMeta || resolveDeliveryStatus(result, report);

  return (
    <aside className="flex h-full min-h-0 flex-col gap-4">
      <div className="p-5" style={styles.card}>
        <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Physical QA</p>
        <h2 className="mt-2 text-xl font-semibold text-slate-100">高清交付指标</h2>
        <p className="mt-2 truncate text-xs text-slate-500">{assets.fileName} · {assets.mode}</p>
        <div className="mt-5 space-y-3">
          {qaMetrics.map(([label, name, key]) => {
            const value = metricValue(report, result, key);
            const width = Math.max(0, Math.min(100, Number(value) || 0));
            return (
              <div key={label} className="p-3" style={styles.innerCard}>
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="font-mono text-[9px] uppercase tracking-[0.22em] text-[#418c80]">{label}</p>
                    <p className="mt-1 text-xs text-slate-400">{name}</p>
                  </div>
                  <span className="font-mono text-sm font-bold text-[#8effed]">{value}</span>
                </div>
                <div className="mt-3 h-[3px] overflow-hidden rounded-full bg-[#0e1d1f]">
                  <div className="h-full rounded-full bg-[#3f6f68]" style={{ width: `${width}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="p-5" style={styles.card}>
        <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Output Binding</p>
        <h2 className="mt-2 text-xl font-semibold text-slate-100">字段绑定</h2>
        <div className="mt-4 space-y-3 font-mono text-xs text-slate-400">
          <div style={styles.innerCard} className="min-w-0 overflow-hidden p-3">
            <span className="text-slate-500">交付状态：</span>
            <span style={{ color: deliveryMeta.tone }}>{deliveryMeta.label}</span>
          </div>
          <div style={styles.innerCard} className="min-w-0 overflow-hidden p-3">
            <span className="text-slate-500">交付原因：</span>
            <span className="break-words" title={assets.finalDeliveryReason || "暂无数据"}>{assets.finalDeliveryReason || "暂无数据"}</span>
          </div>
          <div style={styles.innerCard} className="min-w-0 overflow-hidden p-3">输出尺寸：{result.output_width || "暂无"} × {result.output_height || "暂无"}</div>
          <div style={styles.innerCard} className="min-w-0 overflow-hidden p-3">
            <span className="text-slate-500">尺寸策略：</span>
            <span className="break-words" title={result.resize_policy || "暂无数据"}>{result.resize_policy || "暂无数据"}</span>
          </div>
          <div style={styles.innerCard} className="min-w-0 overflow-hidden p-3">输出格式：{result.output_format || "暂无数据"}</div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col p-5" style={styles.card}>
        <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[#418c80]">Manual Review</p>
        <h2 className="mt-2 text-xl font-semibold text-slate-100">人工复核清单</h2>
        <div className="mt-4 min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
          {reviewItems.map((item, index) => (
            <label key={item} className="flex items-start gap-3 p-3 text-sm text-slate-300" style={styles.innerCard}>
              <input className="mt-1 accent-[#3cb3a0]" type="checkbox" defaultChecked={index < 2} />
              <span>{item}</span>
            </label>
          ))}
        </div>
      </div>
    </aside>
  );
}

export default function ImageSliderComparePage({ taskConfig, compareAssets, onBackToTask, onViewReport }) {
  const assets = useMemo(() => resolveAssets(taskConfig, compareAssets), [taskConfig, compareAssets]);

  return (
    <section className="relative flex h-[100dvh] w-full flex-col overflow-hidden p-6 text-slate-200" style={styles.page}>
      <PolarBackdrop />
      <header className="relative z-10 mb-4 flex h-[82px] shrink-0 items-center justify-between gap-6 border-b border-[#14282a] pb-4">
        <div className="min-w-0">
          <p className="font-mono text-[10px] font-bold uppercase tracking-[0.28em] text-[#418c80]">V0.4 / Image Slider Compare</p>
          <h1 className="mt-2 truncate text-2xl font-semibold tracking-wide text-slate-100">高清滑杆对比与局部放大镜</h1>
          <p className="mt-1 truncate font-mono text-xs text-slate-500">
            前后对比 · {assets.mode} · {assets.fileName}
          </p>
        </div>
        <div className="flex shrink-0 gap-3">
          <button type="button" onClick={onBackToTask} className="px-4 py-2 text-xs tracking-wide transition hover:bg-[#112426] hover:text-slate-200" style={styles.secondaryButton}>
            返回任务详情
          </button>
          <button type="button" onClick={onViewReport} className="px-5 py-2 font-mono text-xs font-bold uppercase tracking-widest transition hover:brightness-125" style={styles.primaryButton}>
            查看质量报告
          </button>
        </div>
      </header>

      <main className="relative z-10 grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_360px] gap-5">
        <SliderCompareStage originalUrl={assets.originalUrl} enhancedUrl={assets.enhancedUrl} fileName={assets.fileName} deliveryBadge={assets.deliveryMeta?.badge || "1080P 本地预览"} />
        <QualityPanel assets={assets} />
      </main>

      <footer className="relative z-10 mt-3 w-full shrink-0 truncate border-t border-[#0e1d1f] px-3 pt-2 text-center font-mono text-[10px] tracking-wider text-slate-600">{PAGE_FOOTER}</footer>
    </section>
  );
}
