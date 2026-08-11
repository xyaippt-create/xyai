import React, { useMemo, useRef, useState } from "react";
import { resolveDeliveryStatus } from "./deliveryStatus.js";
import { PRODUCT_VERSION_LABEL } from "./productVersion.js";

const API_BASE = "http://localhost:8787";

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
  const isFourK = (currentTask.mode || taskConfig?.mode) === "4k_v1";
  const deliveryMeta = isFourK
    ? {
        status: result.final_output_exists ? "PASS" : "PASS_WITH_LIMITATION",
        label: result.final_output_exists ? "4K成品已生成" : "无需重复放大",
        badge: "4K处理结果",
      }
    : resolveDeliveryStatus(debugQuality, result, report, currentTask);
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
  ["文字清晰度", "text_clarity_score"],
  ["边缘质量", "edge_quality_score"],
  ["色彩忠实度", "color_fidelity_score"],
  ["纹理保持度", "texture_score"],
];

function modeLabel(mode) {
  if (["fidelity", "texture", "text_safe", "standard"].includes(mode)) return "1080P标准增强";
  if (mode === "safe_1080p_beta") return "1080P安全增强";
  if (mode === "4k_v1") return "4K高清画质增强";
  return mode || "未选择";
}

function EmptyImagePlane({ label, error }) {
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-[#05090a]">
      <div className="max-w-md px-8 text-center">
        <div className={`mx-auto mb-4 h-12 w-12 rounded-full border ${error ? "border-rose-400/45 bg-rose-500/10" : "border-[#8fb0ff]/45 bg-[#2d6fe8]/10"}`} />
        <p className={`font-mono text-xs uppercase tracking-[0.22em] ${error ? "text-rose-300" : "text-[#9ab7ff]"}`}>{label}</p>
        <p className="mt-3 text-sm leading-7 text-slate-500">
          {error ? "高清资产加载失败，请检查本地服务映射路径。" : "等待处理中心返回真实图像路径。"}
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
      className="pointer-events-none absolute z-40 h-48 w-48 overflow-hidden rounded-lg border border-[#8fb0ff] bg-[#080d16]/90 shadow-[0_0_55px_rgba(45,111,232,0.38)] backdrop-blur-md"
      style={{ left: zoom.x, top: zoom.y, transform: "translate(-50%, -50%)" }}
    >
      <div className="absolute inset-0" style={{ ...base, backgroundImage: `url("${enhancedUrl}")` }} />
      {showOriginal && <div className="absolute inset-0" style={{ ...base, backgroundImage: `url("${originalUrl}")` }} />}
      <div className="absolute inset-0 bg-[repeating-linear-gradient(90deg,rgba(255,255,255,0.10)_0px,transparent_1px,transparent_12px),repeating-linear-gradient(0deg,rgba(255,255,255,0.08)_0px,transparent_1px,transparent_12px)] opacity-45" />
      <div className="absolute bottom-2 left-2 right-2 truncate rounded bg-black/65 px-2 py-1 text-center font-mono text-xs tracking-[0.16em] text-[#9ab7ff]">
        高清局部对比 · {zoom.xPct}% / {zoom.yPct}%
      </div>
    </div>
  );
}

export function SliderCompareStage({ originalUrl, enhancedUrl, fileName, deliveryBadge }) {
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
      className="relative h-full min-h-0 overflow-hidden rounded-lg border border-[var(--border-color)] bg-[#080d16] shadow-[0_32px_100px_rgba(45,111,232,0.16)]"
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

      <div className="absolute inset-y-0 z-30 w-px bg-white/85 shadow-[0_0_26px_rgba(143,176,255,0.85)]" style={{ left: `${split}%` }}>
        <button
          type="button"
          aria-label="拖动对比滑杆"
          className="absolute left-1/2 top-1/2 flex h-16 w-16 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-[#9ab7ff]/75 bg-[#080d16]/90 font-mono text-xs tracking-[0.18em] text-[#9ab7ff] backdrop-blur-xl"
          onMouseDown={(event) => {
            event.stopPropagation();
            setDragging(true);
          }}
        >
          拖动
        </button>
      </div>

      <div className="absolute left-5 top-5 z-20 rounded border border-white/10 bg-black/45 px-4 py-2 font-mono text-xs uppercase tracking-[0.18em] text-white/65 backdrop-blur-md">
        原图
      </div>
      <div className="absolute right-5 top-5 z-20 rounded border border-[#8fb0ff]/40 bg-[#2d6fe8]/15 px-4 py-2 font-mono text-xs uppercase tracking-[0.18em] text-[#9ab7ff] backdrop-blur-md">
        {deliveryBadge}
      </div>
      <div className="absolute bottom-4 right-4 z-20 max-w-[85%] truncate rounded border border-white/10 bg-black/55 px-4 py-2 text-right font-mono text-xs tracking-[0.16em] text-white/55 backdrop-blur-md">
        影界 HDDE {PRODUCT_VERSION_LABEL} · {fileName || "等待真实上传资产"} · HD Delivery Engine
      </div>
      <ZoomGlass zoom={zoom} originalUrl={originalUrl} enhancedUrl={enhancedUrl} split={split} />
    </div>
  );
}

function QualityPanel({ assets }) {
  const report = assets.report || {};
  const result = assets.result || {};
  const deliveryMeta = assets.deliveryMeta || resolveDeliveryStatus(result, report);
  const isFourK = assets.mode === "4k_v1";

  if (isFourK) {
    return (
      <aside className="hdde-compare-side">
        <article className="hdde-compare-panel">
          <p className="hdde-eyebrow">4K处理结果</p>
          <h2>尺寸适配信息</h2>
          <p className="hdde-compare-subtitle" title={assets.fileName}>{assets.fileName} · 4K高清画质增强</p>
          <dl className="hdde-compare-output">
            <div><dt>输入尺寸</dt><dd>{result.input_width} × {result.input_height}</dd></div>
            <div><dt>输出尺寸</dt><dd>{result.output_width} × {result.output_height}</dd></div>
            <div><dt>输出格式</dt><dd>{String(result.output_format || "PNG").toUpperCase()}</dd></div>
            <div><dt>处理状态</dt><dd data-tone="positive">{deliveryMeta.label}</dd></div>
          </dl>
        </article>
        <article className="hdde-compare-panel hdde-compare-review">
          <p className="hdde-eyebrow">人工复核</p>
          <h2>查看内容完整性</h2>
          <div className="hdde-compare-checklist">
            {["主体与构图保持完整", "文字和Logo没有被裁切", "比例正确且没有拉伸", "透明边缘与颜色显示正常"].map((item) => (
              <label key={item}><input type="checkbox" /><span>{item}</span></label>
            ))}
          </div>
        </article>
        <article className="hdde-compare-panel">
          <p className="hdde-eyebrow">能力边界</p>
          <p className="hdde-compare-subtitle">本功能属于高质量4K尺寸增强适配，不代表真实细节重建、AI超分辨率或已证明的画质增益。</p>
        </article>
      </aside>
    );
  }

  return (
    <aside className="hdde-compare-side">
      <article className="hdde-compare-panel">
        <p className="hdde-eyebrow">质量指标</p>
        <h2>高清交付指标</h2>
        <p className="hdde-compare-subtitle" title={assets.fileName}>{assets.fileName} · {modeLabel(assets.mode)}</p>
        <div className="hdde-compare-metrics">
          {qaMetrics.map(([name, key]) => {
            const value = metricValue(report, result, key);
            const width = Math.max(0, Math.min(100, Number(value) || 0));
            return (
              <div key={key} className="hdde-compare-metric">
                <div>
                  <strong>{name}</strong>
                  <span>{value}</span>
                </div>
                <div className="hdde-compare-meter" aria-label={`${name} ${value}`}>
                  <span style={{ width: `${width}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      </article>

      <article className="hdde-compare-panel">
        <p className="hdde-eyebrow">交付信息</p>
        <h2>输出与交付</h2>
        <dl className="hdde-compare-output">
          <div>
            <dt>交付状态</dt>
            <dd data-tone={deliveryMeta.status === "PASS" ? "positive" : deliveryMeta.status === "FAIL" ? "negative" : "warning"}>{deliveryMeta.label}</dd>
          </div>
          <div>
            <dt>输出尺寸</dt>
            <dd>{result.output_width || "暂无"} × {result.output_height || "暂无"}</dd>
          </div>
          <div>
            <dt>输出格式</dt>
            <dd>{result.output_format || "暂无数据"}</dd>
          </div>
          <div>
            <dt>输出位置</dt>
            <dd title={assets.finalOutputUrl || assets.previewOutputUrl || "暂无数据"}>
              {assets.finalOutputUrl || assets.previewOutputUrl || "暂无数据"}
            </dd>
          </div>
        </dl>
      </article>

      <article className="hdde-compare-panel hdde-compare-review">
        <p className="hdde-eyebrow">交付复核</p>
        <h2>人工复核清单</h2>
        <div className="hdde-compare-checklist">
          {reviewItems.map((item, index) => (
            <label key={item}>
              <input type="checkbox" defaultChecked={index < 2} />
              <span>{item}</span>
            </label>
          ))}
        </div>
      </article>
    </aside>
  );
}

export default function ImageSliderComparePage({ taskConfig, compareAssets, onBackToTask, onViewReport }) {
  const assets = useMemo(() => resolveAssets(taskConfig, compareAssets), [taskConfig, compareAssets]);
  const isFourK = assets.mode === "4k_v1";

  return (
    <section className="hdde-compare-page" data-testid="comparison-page">
      <header className="hdde-compare-header">
        <div>
          <p className="hdde-eyebrow">{isFourK ? "4K处理结果" : "对比结果"}</p>
          <h1>{isFourK ? "4K处理结果" : "处理前后对比"}</h1>
          <p title={assets.fileName}>{modeLabel(assets.mode)} · {assets.fileName}</p>
        </div>
        <div className="hdde-compare-actions">
          <button type="button" onClick={onBackToTask} className="hdde-compare-button hdde-compare-button--secondary">
            返回任务详情
          </button>
          <button type="button" onClick={onViewReport} className="hdde-compare-button hdde-compare-button--primary">
            {isFourK ? "查看4K处理报告" : "查看交付报告"}
          </button>
        </div>
      </header>

      <main className="hdde-compare-layout">
        <SliderCompareStage originalUrl={assets.originalUrl} enhancedUrl={assets.enhancedUrl} fileName={assets.fileName} deliveryBadge={assets.deliveryMeta?.badge || (isFourK ? "4K处理结果" : "1080P 本地预览")} />
        <QualityPanel assets={assets} />
      </main>
    </section>
  );
}
