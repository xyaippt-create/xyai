import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { HddePageHeader, HddeStatusPill } from "./HddeUI.jsx";
import { appendPrintSource, detailEstimate, planPrintSize } from "./printPreflight.js";
import PrintLayerEditor from "./PrintLayerEditor.jsx";
import "./ColorCorrectionReference.css";
import "./printPreflight.css";

const MAX_PRINT_PIXELS = 80_000_000;

function display(value) {
  return value > 0 && value < 0.01 ? "< 0.01" : value.toLocaleString("zh-CN", { maximumFractionDigits: 2, useGrouping: false });
}

function PrintSource({ loading, source, busy, error, onSelect, pickerRef }) {
  const [dragging, setDragging] = useState(false);
  const [dropError, setDropError] = useState("");
  const picker = <input ref={pickerRef} id="print-file-input" type="file" aria-label="选择本地图片" accept="image/jpeg,image/png,image/webp"
    disabled={busy} onChange={event => {
      const next = event.target.files?.[0];
      event.target.value = "";
      if (next) { setDropError(""); onSelect(next); }
    }} />;
  return <section className="hdde-color-card hdde-color-source print-source" aria-labelledby="print-original"
    data-dragging={dragging && !busy} onDragOver={event => {
      if (!event.dataTransfer.types.includes("Files")) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = busy ? "none" : "copy";
      setDragging(!busy);
    }} onDragLeave={event => {
      if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false);
    }} onDrop={event => {
      event.preventDefault(); setDragging(false);
      if (busy || !event.dataTransfer.files.length) return;
      if (event.dataTransfer.files.length > 1) { setDropError("请一次选择一张原图。"); return; }
      setDropError(""); onSelect(event.dataTransfer.files[0]);
    }}>
    <div className="hdde-color-section-title"><span aria-hidden="true">1</span>
      <div><h2 id="print-original">{source ? "已选原图" : "选择图片"}</h2>{!source && <p>选择一张 JPG、PNG 或 WebP 原图。</p>}</div>
    </div>
    <div className={`hdde-color-dropzone${source ? " has-file" : ""}`}>
      {picker}
      {source ? <div className="hdde-color-file-list"><article>
        <img src={source.url} alt=""/>
        <div className="hdde-color-file-meta"><strong title={source.name}>{source.name}</strong><span>{source.resultId && "来自已有成品 · "}{source.width} × {source.height} px</span></div>
        <button type="button" className="hdde-secondary-action" disabled={busy} onClick={() => pickerRef.current?.click()}>更换</button>
      </article></div> : <label htmlFor="print-file-input">
        <strong>{loading && !error ? "正在读取原图…" : "拖入图片，或点击选择"}</strong>
        <span>图片在本机预检和出图</span>
      </label>}
    </div>
    {(dropError || error) && <p className="print-feedback" role="alert">{dropError || error}</p>}
  </section>;
}

function PrintSizeSummary({ result, custom, children }) {
  if (!result || result.error) return children || null;
  const up = result.scale > 1;
  const scale = up && result.scale < 1.005 ? "不足 1.01" : display(result.scale);
  return <div className="print-result" aria-live="polite" role="status">
    <div className="print-panel-heading"><h3>{custom ? "画布尺寸预检" : "尺寸预检"}</h3>
      <span className="print-verdict" data-upscale={up}>{up ? `需放大 ${scale} 倍${result.soft ? " · 细节偏软" : ""}` : "原图像素充足"}</span>
    </div>
    <dl>
      <div><dt>目标像素</dt><dd>{result.pixelWidth} × {result.pixelHeight} px</dd></div>
      <div><dt>喷绘尺寸</dt><dd>{display(result.cmWidth)} × {display(result.cmHeight)} cm</dd></div>
    </dl>
    <details className="print-precision">
      <summary>精度详情</summary>
      <dl>
        <div><dt>原图有效精度</dt><dd>{display(result.effectivePpi)} PPI</dd></div>
        <div><dt>缩放倍数</dt><dd>{scale} 倍</dd></div>
        {up && <>
          <div><dt>标称精度</dt><dd>{display(result.nominalPpi)} PPI</dd></div>
          <div><dt>{result.reconstructed ? "超清后有效精度" : "出图有效精度"}</dt><dd>约 {display(result.detailPpi)} PPI</dd></div>
        </>}
      </dl>
      {up && <p className="print-detail-note" data-soft={result.soft}>
        {result.reconstructed ? "出图时先用 4K 超清重建细节（最多 3 倍），再补到目标像素。" : "原图超过 400 万像素，将直接插值放大。"}
        {result.soft && ` 仍需插值放大约 ${display(result.interpolation)} 倍，细节会偏软，建议降低 PPI、缩小喷绘尺寸或换更大的原图。`}
      </p>}
    </details>
    {children}
  </div>;
}

const ZOOM_STEPS = [1, 1/2, 1/4, 1/8, 1/16];
const MIN_ZOOM = 1/32;

function zoomLabel(zoom) {
  const ratio = 1 / zoom;
  return `1:${ratio >= 10 ? Math.round(ratio) : Number(ratio.toFixed(1))}`;
}

function defaultZoom(windowWidth, windowHeight, outputWidth, outputHeight) {
  // A box of about 6% of the print area, no side longer than 60% of the print.
  const lower = Math.max(windowWidth / (0.6 * outputWidth), windowHeight / (0.6 * outputHeight));
  const target = Math.max(lower, Math.sqrt(windowWidth * windowHeight / (0.06 * outputWidth * outputHeight)));
  const pick = ZOOM_STEPS.find(step => step <= target) || ZOOM_STEPS[ZOOM_STEPS.length - 1];
  return pick >= lower ? pick : [...ZOOM_STEPS].reverse().find(step => step >= lower) || 1;
}

function busiestPoint(image, boxWidth, boxHeight) {
  // Gradient energy on a small thumbnail; return the centre of the box holding the most of it.
  const w = 96, h = Math.max(1, Math.round(96 * image.naturalHeight / image.naturalWidth));
  const canvas = document.createElement("canvas");
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(image, 0, 0, w, h);
  const data = ctx.getImageData(0, 0, w, h).data;
  const luma = new Float32Array(w * h);
  for (let i = 0; i < w * h; i++) luma[i] = 0.299*data[4*i] + 0.587*data[4*i+1] + 0.114*data[4*i+2];
  const energy = new Float32Array((w + 1) * (h + 1));  // summed-area table
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x;
    const g = x + 1 < w && y + 1 < h ? Math.abs(luma[i+1]-luma[i]) + Math.abs(luma[i+w]-luma[i]) : 0;
    energy[(y+1)*(w+1)+x+1] = g + energy[y*(w+1)+x+1] + energy[(y+1)*(w+1)+x] - energy[y*(w+1)+x];
  }
  const bw = Math.max(1, Math.min(w, Math.round(boxWidth * w))), bh = Math.max(1, Math.min(h, Math.round(boxHeight * h)));
  let best = -1, at = null;
  for (let y = 0; y + bh <= h; y++) for (let x = 0; x + bw <= w; x++) {
    const sum = energy[(y+bh)*(w+1)+x+bw] - energy[y*(w+1)+x+bw] - energy[(y+bh)*(w+1)+x] + energy[y*(w+1)+x];
    if (sum > best) { best = sum; at = [(x + bw/2) / w, (y + bh/2) / h]; }
  }
  return at;
}

function PrintOutput({ source, plan, ppi, busy, setBusy, onNavigate, layers, layered, unavailable, actionHost, intakeStatusHost, pickerRef }) {
  const [requestId] = useState(() => crypto.randomUUID());
  const [output, setOutput] = useState(null);
  const [error, setError] = useState("");
  const [previewReady, setPreviewReady] = useState(false);
  const [detail, setDetail] = useState(null);
  const [reviewedDetail, setReviewedDetail] = useState(null);
  const [detailSize, setDetailSize] = useState({ width: 0, height: 0 });
  const [showEditor, setShowEditor] = useState(false);
  const [point, setPoint] = useState([0.5,0.5]);
  // Comparison-window pixels per output pixel; null until the window size is known.
  const [zoom, setZoom] = useState(null);
  // A dragged area in output pixels; shown exactly, fitted into the comparison window.
  const [dragBox, setDragBox] = useState(null);
  const [draft, setDraft] = useState(null);
  const previewSection = useRef(null);
  const detailWindow = useRef(null);
  const submitting = useRef(false);
  const decodedImages = useRef(null);
  const dragStart = useRef(null);
  const pointMoved = useRef(false);
  const stepScale = zoom || 1;
  const cropWidth = !output ? 0 : Math.min(output.width, Math.max(1, Math.round(dragBox ? dragBox.width : detailSize.width / stepScale)));
  const cropHeight = !output ? 0 : Math.min(output.height, Math.max(1, Math.round(dragBox ? dragBox.height : detailSize.height / stepScale)));
  // Window pixels per output pixel; never above 1, so the comparison never enlarges the print.
  const scale = !output || !zoom || !detailSize.width ? null :
    dragBox ? Math.min(1, detailSize.width / cropWidth, detailSize.height / cropHeight) : zoom;
  const cropX = output ? Math.min(output.width - cropWidth, Math.max(0, Math.round(point[0] * output.width - cropWidth/2))) : 0;
  const cropY = output ? Math.min(output.height - cropHeight, Math.max(0, Math.round(point[1] * output.height - cropHeight/2))) : 0;
  const currentDetail = detail?.x === cropX && detail?.y === cropY && detail.size === detailSize && detail.scale === scale && detail.w === cropWidth && detail.h === cropHeight ? detail.images : null;
  const reviewed = Boolean(currentDetail && reviewedDetail === currentDetail);

  useEffect(() => {
    if (output) previewSection.current?.focus();
  }, [output]);

  useEffect(() => {
    if (!output || !detailWindow.current) return;
    const observer = new ResizeObserver(([entry]) => {
      const width = Math.min(output.width, Math.floor(entry.contentRect.width));
      const height = Math.min(output.height, Math.floor(entry.contentRect.height));
      if (width > 0 && height > 0) {
        setDetailSize(previous => previous.width === width && previous.height === height ? previous : { width, height });
      }
    });
    observer.observe(detailWindow.current);
    return () => observer.disconnect();
  }, [output]);

  useEffect(() => {
    // Start with a box that is clearly visible on large prints.
    if (!output || zoom || !detailSize.width) return;
    setZoom(defaultZoom(detailSize.width, detailSize.height, output.width, output.height));
  }, [output, zoom, detailSize.width, detailSize.height]);

  useEffect(() => {
    // Place the first box where the print has the most detail instead of on flat background.
    if (!output || !previewReady || !zoom || pointMoved.current || !cropWidth) return;
    let active = true;
    const image = new Image();
    image.src = output.preview_url;
    image.decode().then(() => {
      if (!active || pointMoved.current) return;
      const busiest = busiestPoint(image, cropWidth / output.width, cropHeight / output.height);
      if (busiest) setPoint(busiest);
    }).catch(() => {});
    return () => { active = false; };
  }, [output, previewReady, zoom, cropWidth, cropHeight]);

  useEffect(() => {
    if (!output || !previewReady || !scale || !cropWidth || !cropHeight) return;
    const width = Math.max(1, Math.round(cropWidth * scale)), height = Math.max(1, Math.round(cropHeight * scale));
    let active = true;
    if (!decodedImages.current) {
      const original = new Image(), finished = new Image();
      original.src = source.url; finished.src = output.preview_url;
      decodedImages.current = Promise.all([original.decode(), finished.decode()]).then(() => [original,finished]);
    }
    decodedImages.current.then(([original, finished]) => {
      if (!active) return;
      const fit = Math.min(output.width/source.width,output.height/source.height);
      const rw=Math.round(source.width*fit), rh=Math.round(source.height*fit);
      const left=Math.floor((output.width-rw)/2), top=Math.floor((output.height-rh)/2);
      const canvas=document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx=canvas.getContext("2d");
      if (layered) {
        ctx.fillStyle=layers.paper;
        ctx.fillRect(0, 0, width, height);
      }
      ctx.imageSmoothingQuality="high";
      ctx.drawImage(original,(left-cropX)*scale,(top-cropY)*scale,rw*scale,rh*scale);
      const before=canvas.toDataURL();
      ctx.clearRect(0, 0, width, height);
      ctx.drawImage(finished, cropX, cropY, cropWidth, cropHeight, 0, 0, width, height);
      setDetail({ x: cropX, y: cropY, size: detailSize, scale, w: cropWidth, h: cropHeight, images: [before, canvas.toDataURL()] });
    }).catch(()=>{if(active){ decodedImages.current=null; setError("局部对比加载失败，请重新选择检查位置。"); }});
    return ()=>{active=false;};
  }, [output, layered, layers, previewReady, source, cropX, cropY, cropWidth, cropHeight, scale, detailSize]);

  async function generate() {
    if (submitting.current || busy || unavailable || output) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      appendPrintSource(body, source);
      body.append("width", plan.pixelWidth);
      body.append("height", plan.pixelHeight);
      body.append("ppi", ppi);
      body.append("request_id", requestId);
      if (layered) body.append("layers",JSON.stringify(layers));
      const response = await fetch("/api/print-output/render", { method: "POST", body });
      const payload = await response.json();
      if (!response.ok) {
        const detail = payload.detail;
        throw new Error(typeof detail === "string" ? detail : detail?.message || "喷绘出图失败，请重试。");
      }
      setOutput(payload);
    } catch (err) {
      setError(err.message || "连接中断，请重试。");
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  const description = output ? (layered && !reviewed ? "请先核对成品局部，再另存副本。" : "成品已生成，可另存交付副本。") :
    busy ? (plan?.reconstructed ? "已提交，正在超清重建并生成喷绘成品，约需 1 分钟…" : "已提交，正在生成并登记喷绘成品…") :
    unavailable;
  const saveBlocked = !previewReady || (layered && (!reviewed || !currentDetail));
  function selectPoint(x, y) {
    pointMoved.current = true;
    setPoint([Math.max(0, Math.min(1, x)), Math.max(0, Math.min(1, y))]);
    setReviewedDetail(null);
  }
  function framePoint(event) {
    const r = event.currentTarget.getBoundingClientRect();
    return [Math.max(0, Math.min(1, (event.clientX-r.left)/r.width)), Math.max(0, Math.min(1, (event.clientY-r.top)/r.height))];
  }
  function finishDrag(event) {
    const start = dragStart.current;
    dragStart.current = null;
    setDraft(null);
    if (!start || !output) return;
    const end = framePoint(event);
    const w = Math.abs(end[0]-start[0]) * output.width, h = Math.abs(end[1]-start[1]) * output.height;
    if (w < 8 && h < 8) { selectPoint(...end); return; }  // a click moves the box
    // Keep tiny drags readable: no smaller than 1/32 of the window in either direction.
    setDragBox({ width: Math.max(w, detailSize.width * MIN_ZOOM), height: Math.max(h, detailSize.height * MIN_ZOOM) });
    selectPoint((start[0]+end[0])/2, (start[1]+end[1])/2);
  }

  return <>
    {actionHost && createPortal(<>
      {error && <p className="print-feedback" role="alert">{error}</p>}
      {output ?
        <button type="button" className="hdde-primary-action hdde-color-run" disabled={saveBlocked}
          onClick={() => onNavigate("/smart-delivery?results=" + encodeURIComponent(output.result_id))}>
          另存交付副本
        </button> :
        <button type="button" className="hdde-primary-action hdde-color-run" disabled={busy || !!unavailable} onClick={generate}>
          {busy ? "正在出图…" : "提交出图"}
        </button>}
    </>, actionHost)}
    {description && actionHost && createPortal(
      <p className="hdde-color-task-state" role="status">{description}</p>, intakeStatusHost || actionHost)}
    {!output && !(layered && source) && <section className="hdde-color-card hdde-color-outcome-empty print-intake-preview" aria-labelledby="print-preview-title">
      <div className="hdde-color-section-title"><span aria-hidden="true">3</span><div>
        <h2 id="print-preview-title">预览与结果</h2><p>{source ? "当前显示原图。提交后可在这里核对成品局部。" : "选择原图后可在这里预览，出图后可核对成品细节。"}</p>
      </div></div>
      <div className="hdde-color-preview-stage">
        {source ? <img src={source.url} alt="已选原图预览"/> :
          <button type="button" className="hdde-secondary-action" onClick={() => pickerRef.current?.click()}>选择喷绘原图</button>}
      </div>
    </section>}
    {output && <section className="hdde-color-card print-panel print-output" data-show-editor={showEditor} ref={previewSection} tabIndex={-1} aria-labelledby="print-output-title">
      <div className="print-panel-heading">
        <div className="hdde-color-section-title"><span aria-hidden="true">3</span><div>
          <h2 id="print-output-title">喷绘成品预览</h2><p>在画面上拖拽框选要核对的区域；点击或用方向键移动选框。</p>
        </div></div>
        <div className="print-actions">
        {layered && <button type="button" className="hdde-secondary-action" aria-expanded={showEditor} aria-controls="print-layer-section" onClick={() => setShowEditor(!showEditor)}>{showEditor ? "收起分层编辑" : "展开分层编辑"}</button>}
        <button type="button" className="hdde-secondary-action" onClick={() => onNavigate("/outputs")}>查看输出中心</button>
        </div>
      </div>
      <div className="print-review-layout">
        <div className="print-click-preview">
          <div className="print-inspect-frame" role="group" aria-label="选择成品检查位置" aria-describedby="print-crop-heading"
            tabIndex={0} onKeyDown={event => {
              const step = {ArrowLeft:[-1,0], ArrowRight:[1,0], ArrowUp:[0,-1], ArrowDown:[0,1]}[event.key];
              if (!step) return;
              event.preventDefault();
              selectPoint(point[0]+step[0]*cropWidth/output.width/2, point[1]+step[1]*cropHeight/output.height/2);
            }}>
            <img src={output.preview_url} alt="喷绘成品预览" draggable={false}
              onPointerDown={event => {
                if (event.button !== 0) return;
                event.currentTarget.setPointerCapture(event.pointerId);
                dragStart.current = framePoint(event);
              }}
              onPointerMove={event => {
                if (!dragStart.current) return;
                const [x, y] = framePoint(event), [sx, sy] = dragStart.current;
                setDraft({ left: Math.min(x, sx), top: Math.min(y, sy), width: Math.abs(x-sx), height: Math.abs(y-sy) });
              }}
              onPointerUp={finishDrag}
              onPointerCancel={() => { dragStart.current = null; setDraft(null); }}
              onLoad={event => {
              const image = event.currentTarget;
              if (image.naturalWidth === output.width && image.naturalHeight === output.height) setPreviewReady(true);
              else setError("成品像素与预检不一致，请到输出中心核对。");
            }} onError={() => setError("成品预览加载失败，请到输出中心检查已生成的文件。")}/>
            {previewReady && cropWidth > 0 && <span className="print-inspect-box" aria-hidden="true" style={{
              left: `${100*cropX/output.width}%`, top: `${100*cropY/output.height}%`,
              width: `${100*cropWidth/output.width}%`, height: `${100*cropHeight/output.height}%`,
            }}/>}
            {draft && <span className="print-inspect-box print-inspect-draft" aria-hidden="true" style={{
              left: `${100*draft.left}%`, top: `${100*draft.top}%`, width: `${100*draft.width}%`, height: `${100*draft.height}%`,
            }}/>}
          </div>
          <div className="print-zoom" role="group" aria-label="对照比例">
            <span>对照比例</span>
            {ZOOM_STEPS.map(step => <button type="button" key={step} aria-pressed={!dragBox && zoom === step}
              onClick={() => { setZoom(step); setDragBox(null); setReviewedDetail(null); }}>{step === 1 ? "1:1 原像素" : `1:${1/step}`}</button>)}
            {dragBox && scale && <span className="print-zoom-custom">框选区域 {zoomLabel(scale)}</span>}
          </div>
        </div>
        <div className="print-crops">
          <h3 id="print-crop-heading">局部对照</h3>
          <div className="print-detail-pair">{["原图等比参考", !scale || scale === 1 ? "成品原像素" : `成品 ${zoomLabel(scale)} 缩小`].map((label,i) => <figure key={i}>
            <figcaption>{label}</figcaption>
            <div className="print-detail-window" ref={i === 0 ? detailWindow : undefined}>
              {currentDetail ? <img src={currentDetail[i]} alt={i ? (layered ? "分层局部" : "成品局部") : "原图参考局部"}/> :
                i === 0 && <p role="status">正在读取局部像素…</p>}
            </div>
          </figure>)}</div>
          {layered && <label className="print-review"><input type="checkbox" checked={reviewed} disabled={!currentDetail}
            onChange={e=>setReviewedDetail(e.target.checked ? currentDetail : null)}/>已核对图文和主体细节</label>}
        </div>
      </div>
      <p className="print-file-row"><strong>输出 / 喷绘出图 / {output.filename}</strong><span>{output.width} × {output.height} px · {display(output.ppi)} PPI{(output.upscale || output.layers?.base_upscale)?.method === "SR_FUSION" ? " · 已超清重建" : ""}</span></p>
    </section>}
  </>;
}

function PrintWorkflow({loading, source, plan, ppi, busy, setBusy, onNavigate, children, readError, onSelect, layered, setLayered, sizeLabel, planAt, onPpiChange}) {
  const pickerRef = useRef(null);
  const [actionHost, setActionHost] = useState(null);
  const [intakeStatusHost, setIntakeStatusHost] = useState(null);
  const [recipe, setRecipe] = useState(null);
  const [custom, setCustom] = useState(false);
  const [cw, setCw] = useState("80"), [ch, setCh] = useState("120");
  const paperAt = p => layered && custom
    ? {pixelWidth:Math.round(Number(cw)*p/2.54), pixelHeight:Math.round(Number(ch)*p/2.54)} : (p === ppi ? plan : planAt?.(p));
  const fits = d => Boolean(d && !d.error) && [d.pixelWidth,d.pixelHeight].every(n =>
    Number.isSafeInteger(n) && n > 0 && n <= 32768) && d.pixelWidth * d.pixelHeight <= MAX_PRINT_PIXELS;
  const paper = paperAt(ppi);
  const sizeAllowed = fits(paper);
  // Pixel size grows linearly with PPI, so estimate the ceiling and step down to the first value that fits.
  let maxPpi = null;
  if (source && paper && !paper.error && !sizeAllowed && ppi > 1) {
    const w = paper.pixelWidth, h = paper.pixelHeight;
    let p = Math.floor(ppi * Math.min(Math.sqrt(MAX_PRINT_PIXELS / (w * h)), 32768 / Math.max(w, h)));
    for (let i = 0; i < 20 && p >= 1 && !fits(paperAt(p)); i++) p -= 1;
    if (p >= 1 && p < ppi && fits(paperAt(p))) maxPpi = p;
  }
  const sizeError = maxPpi
    ? `当前尺寸太大，超过单张最多 8000 万像素。按这个尺寸最高约 ${maxPpi} PPI。`
    : "请调整出图尺寸，目标单边最多 32768 px，总像素最多 8000 万。";
  let unavailable = "";
  if (!source) unavailable = readError ? "请重新选择原图。" : (loading ? "正在读取原图…" : "等待选择图片");
  else if (plan.error) unavailable = plan.error;
  else if (!sizeAllowed) unavailable = sizeError;
  else if (layered && !recipe) unavailable = "请先标记并检查选区。";
  let summary = plan;
  if (plan && !plan.error && !sizeAllowed) summary = {error:sizeError};
  if (layered && custom && source && sizeAllowed && !plan.error) {
    const fit = Math.min(paper.pixelWidth/source.width, paper.pixelHeight/source.height);
    summary = {...paper, cmWidth:Number(cw), cmHeight:Number(ch), scale:fit, effectivePpi:ppi/fit,
      ...detailEstimate(source, fit, Number(ppi), ppi/fit)};
  }
  return <>
    <HddePageHeader title="喷绘出图" description={source ? undefined : "按成品尺寸检查原图精度，生成喷绘文件并核对局部细节。"}
      meta={<HddeStatusPill tone={source ? "positive" : "neutral"}>{readError ? "原图读取失败" : source ? "原图已载入" : loading ? "正在读取原图" : "待选原图"}</HddeStatusPill>}/>
    <div className="hdde-color-flow hdde-desktop-columns print-flow">
      <div className={`hdde-color-intake${layered && source ? " print-layer-intake" : ""}`}>
        <div className="hdde-reference-tabs print-mode-tabs" role="group" aria-label="出图方式">
          {["等比出图","分层出图"].map((label, index) => {
            const useLayers = index === 1;
            return <button type="button" key={label} disabled={busy} aria-pressed={layered === useLayers}
              className={layered === useLayers ? "hdde-primary-action" : "hdde-secondary-action"}
              onClick={() => { if (layered !== useLayers) { setLayered(useLayers); setRecipe(null); } }}>{label}</button>;
          })}
        </div>
        <div className="hdde-color-intake-body">
          <PrintSource loading={loading} source={source} busy={busy} error={readError} onSelect={onSelect} pickerRef={pickerRef}/>
          <section className="hdde-color-card hdde-color-controls print-panel print-spec" aria-labelledby="print-spec">
            <details className="print-settings" open={Boolean(source)}>
              <summary>
                <h2 id="print-spec" className="hdde-color-section-title"><span aria-hidden="true">2</span>喷绘规格
                  <small>{layered && custom ? `${cw} × ${ch} cm` : sizeLabel} · {ppi || "—"} PPI</small>
                </h2>
              </summary>
              <fieldset className="print-spec-controls" disabled={busy} aria-label="喷绘参数">
                {children}
                {layered && source && <>
                  <label className="print-inline-field">成品画布<select value={custom?"paper":"source"} onChange={e=>setCustom(e.target.value==="paper")}>
                    <option value="source">沿用预检尺寸</option><option value="paper">指定宽高，等比居中留边</option>
                  </select></label>
                  {custom && <div className="print-canvas-dimensions">
                    <label>宽<input aria-label="画布宽度（cm）" type="number" step="any" min="0" value={cw} onChange={e=>setCw(e.target.value)}/></label>
                    <label>高<input aria-label="画布高度（cm）" type="number" step="any" min="0" value={ch} onChange={e=>setCh(e.target.value)}/></label>
                    <span>cm</span>
                  </div>}
                </>}
              </fieldset>
            </details>
            {maxPpi && !busy && <div className="print-max-ppi" role="group" aria-label="出图尺寸超限">
              <span>{ppi} PPI 超出上限，当前尺寸最高 {maxPpi} PPI</span>
              <button type="button" className="hdde-secondary-action" onClick={() => onPpiChange?.(String(maxPpi))}>改为 {maxPpi} PPI</button>
            </div>}
            <PrintSizeSummary result={summary} custom={layered && custom}>
              {layered && source && <div className="print-intake-status" ref={setIntakeStatusHost}/>}
            </PrintSizeSummary>
          </section>
        </div>
        <div className="hdde-color-execution" ref={setActionHost}/>
      </div>
      <div className="hdde-color-outcome print-outcome" data-stage={layered && source ? "layers" : "intake"}>
        <PrintOutput key={JSON.stringify([layered,paper?.pixelWidth,paper?.pixelHeight,ppi,recipe])} source={source}
          plan={paper} ppi={ppi} busy={busy} setBusy={setBusy} onNavigate={onNavigate} layers={recipe} layered={layered}
          unavailable={unavailable} actionHost={actionHost} intakeStatusHost={intakeStatusHost} pickerRef={pickerRef}/>
        {layered && source && <section id="print-layer-section" className="hdde-color-card print-panel print-layer-section" aria-label="分层编辑">
          <PrintLayerEditor source={source} onReady={setRecipe} busy={busy}/>
        </section>}
      </div>
    </div>
  </>;
}

export default function PrintPreflightPage({ onNavigate, continueResultId = "" }) {
  const [file, setFile] = useState(null);
  const [loadedSource, setSource] = useState(null);
  const [readError, setReadError] = useState("");
  const [mode, setMode] = useState("physical");
  const [axis, setAxis] = useState("width");
  const [cm, setCm] = useState("200");
  const [ppi, setPpi] = useState("150");
  const [busy, setBusy] = useState(false);
  const [layered, setLayered] = useState(false);

  useEffect(() => {
    if (!file || continueResultId) return;
    let active = true;
    const url = URL.createObjectURL(file);
    createImageBitmap(file, { imageOrientation: "from-image" }).then(bitmap => {
      if (active) setSource({ file, name: file.name, width: bitmap.width, height: bitmap.height, url });
      bitmap.close();
    }).catch(() => {
      if (active) setReadError("无法读取这张图片，请重新选择 JPG、PNG 或 WebP 文件。");
    });
    return () => {
      active = false;
      URL.revokeObjectURL(url);
    };
  }, [file, continueResultId]);

  useEffect(() => {
    if (!continueResultId) return;
    const controller = new AbortController();
    setReadError("");
    async function loadResult() {
      const response = await fetch("/api/result-assets/" + encodeURIComponent(continueResultId), {
        cache: "no-store", signal: controller.signal,
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail?.message || "已有成品无法读取，请返回输出中心重新选择。");
      const asset = payload.data;
      if (asset.width * asset.height > MAX_PRINT_PIXELS) throw new Error("该成品超过喷绘出图的 8000 万像素输入限制。");
      const image = new Image();
      image.src = asset.preview_url;
      try {
        await image.decode();
      } catch {
        throw new Error("已有成品预览无法读取，请返回输出中心检查文件。");
      }
      if (!controller.signal.aborted) {
        setSource({ resultId: continueResultId, name: asset.file_name, url: asset.preview_url,
          width: image.naturalWidth, height: image.naturalHeight });
      }
    }
    loadResult().catch(error => {
      if (!controller.signal.aborted) setReadError(error.message || "已有成品无法读取。");
    });
    return () => controller.abort();
  }, [continueResultId]);

  const matchesSelection = continueResultId ? loadedSource?.resultId === continueResultId : loadedSource?.file === file;
  const source = matchesSelection ? loadedSource : null;
  const result = source && planPrintSize(source, { mode, axis, cm, ppi });
  function selectFile(next) {
    if (busy || (next === source?.file)) return;
    if (continueResultId) onNavigate("/print-8k", { replace: true });
    setSource(null);
    setReadError("");
    setFile(next);
  }

  return <div className="print-preflight hdde-color-page hdde-page-frame hdde-page-stack">
    <PrintWorkflow key={source?.url || "empty"} source={source} loading={Boolean(file || continueResultId)} plan={result} readError={readError}
      ppi={Number(ppi)} busy={busy} setBusy={setBusy} onNavigate={onNavigate} onSelect={selectFile} layered={layered} setLayered={setLayered}
      planAt={p => source && planPrintSize(source, { mode, axis, cm, ppi: p })} onPpiChange={setPpi}
      sizeLabel={mode === "8k" ? "长边 7680 px" : `${axis === "width" ? "宽" : "高"} ${cm || "—"} cm`}>
      <label className="print-inline-field">计算方式<select value={mode} onChange={e=>setMode(e.target.value)}>
        <option value="physical">按喷绘尺寸计算</option><option value="8k">按 8K 长边估算（7680 px）</option>
      </select></label>
      {mode === "physical" && <div className="print-size-row">
        <span>喷绘尺寸</span>
        <select aria-label="指定边" value={axis} onChange={e=>setAxis(e.target.value)}>
          <option value="width">宽度</option><option value="height">高度</option>
        </select>
        <input aria-label={`喷绘${axis === "width" ? "宽度" : "高度"}（cm）`} type="number" step="any" min="0" value={cm} onChange={e=>setCm(e.target.value)}/>
        <span>cm</span>
      </div>}
      <div className="print-density">
        <label className="print-inline-field">目标 PPI<input aria-label="目标 PPI（像素/英寸）" type="number" step="any" min="0" value={ppi} onChange={e=>setPpi(e.target.value)}/></label>
        <div className="print-presets" role="group" aria-label="常用目标精度">
          {[100,150,300].map(value => <button type="button" key={value} aria-pressed={Number(ppi) === value}
            aria-label={`${value} PPI`} onClick={()=>setPpi(String(value))}>{value}</button>)}
        </div>
      </div>
    </PrintWorkflow>
  </div>;
}
