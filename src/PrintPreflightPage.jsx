import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { HddePageHeader, HddeStatusPill } from "./HddeUI.jsx";
import { appendPrintSource, planPrintSize } from "./printPreflight.js";
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
      <div><h2 id="print-original">选择图片</h2><p>选择一张 JPG、PNG 或 WebP 原图。</p></div>
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

function PrintSizeSummary({ result, custom }) {
  if (!result || result.error) return null;
  const up = result.scale > 1;
  const scale = up && result.scale < 1.005 ? "不足 1.01" : display(result.scale);
  return <div className="print-result" aria-live="polite" role="status">
    <div className="print-panel-heading"><h3>{custom ? "画布尺寸预检" : "尺寸预检"}</h3>
      <span className="print-verdict" data-upscale={up}>{up ? `需放大 ${scale} 倍` : "原图像素充足"}</span>
    </div>
    <dl>
      <div><dt>目标像素</dt><dd>{result.pixelWidth} × {result.pixelHeight} px</dd></div>
      <div><dt>喷绘尺寸</dt><dd>{display(result.cmWidth)} × {display(result.cmHeight)} cm</dd></div>
      <div><dt>原图有效精度</dt><dd>{display(result.effectivePpi)} PPI</dd></div>
      <div><dt>缩放倍数</dt><dd>{scale} 倍</dd></div>
      {!custom && up && <>
        <div><dt>标称精度</dt><dd>{display(result.nominalPpi)} PPI</dd></div>
        <div><dt>{result.reconstructed ? "超清后有效精度" : "出图有效精度"}</dt><dd>约 {display(result.detailPpi)} PPI</dd></div>
      </>}
    </dl>
    {!custom && up && <p className="print-detail-note" data-soft={result.soft}>
      {result.reconstructed ? "出图时先用 4K 超清重建细节（最多 3 倍），再补到目标像素。" : "原图超过 400 万像素，将直接插值放大。"}
      {result.soft && ` 仍需插值放大约 ${display(result.interpolation)} 倍，细节会偏软，建议降低 PPI、缩小喷绘尺寸或换更大的原图。`}
    </p>}
  </div>;
}

function PrintOutput({ source, plan, ppi, busy, setBusy, onNavigate, layers, layered, unavailable, actionHost, pickerRef }) {
  const [requestId] = useState(() => crypto.randomUUID());
  const [output, setOutput] = useState(null);
  const [error, setError] = useState("");
  const [previewReady, setPreviewReady] = useState(false);
  const [detail, setDetail] = useState(null);
  const [reviewedDetail, setReviewedDetail] = useState(null);
  const [detailSize, setDetailSize] = useState({ width: 0, height: 0 });
  const [showEditor, setShowEditor] = useState(false);
  const [point, setPoint] = useState([0.5,0.5]);
  const previewSection = useRef(null);
  const detailWindow = useRef(null);
  const submitting = useRef(false);
  const decodedImages = useRef(null);
  const { width: cropWidth, height: cropHeight } = detailSize;
  const cropX = output ? Math.min(output.width - cropWidth, Math.max(0, Math.round(point[0] * output.width - cropWidth/2))) : 0;
  const cropY = output ? Math.min(output.height - cropHeight, Math.max(0, Math.round(point[1] * output.height - cropHeight/2))) : 0;
  const currentDetail = detail?.x === cropX && detail?.y === cropY && detail.size === detailSize ? detail.images : null;
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
    const { width, height } = detailSize;
    if (!output || !previewReady || !width || !height) return;
    let active = true;
    if (!decodedImages.current) {
      const original = new Image(), finished = new Image();
      original.src = source.url; finished.src = output.preview_url;
      decodedImages.current = Promise.all([original.decode(), finished.decode()]).then(() => [original,finished]);
    }
    decodedImages.current.then(([original, finished]) => {
      if (!active) return;
      const scale = Math.min(output.width/source.width,output.height/source.height);
      const rw=Math.round(source.width*scale), rh=Math.round(source.height*scale);
      const canvas=document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx=canvas.getContext("2d");
      if (layered) {
        ctx.fillStyle=layers.paper;
        ctx.fillRect(0, 0, width, height);
      }
      ctx.imageSmoothingQuality="high";
      ctx.drawImage(original,Math.floor((output.width-rw)/2)-cropX,Math.floor((output.height-rh)/2)-cropY,rw,rh);
      const before=canvas.toDataURL();
      ctx.clearRect(0, 0, width, height);
      ctx.drawImage(finished, cropX, cropY, width, height, 0, 0, width, height);
      setDetail({ x: cropX, y: cropY, size: detailSize, images: [before, canvas.toDataURL()] });
    }).catch(()=>{if(active){ decodedImages.current=null; setError("局部对比加载失败，请重新选择检查位置。"); }});
    return ()=>{active=false;};
  }, [output, layered, layers, previewReady, source, cropX, cropY, detailSize]);

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
    busy ? (!layered && plan?.reconstructed ? "已提交，正在超清重建并生成喷绘成品，约需 1 分钟…" : "已提交，正在生成并登记喷绘成品…") :
    unavailable || "规格已就绪，可以提交出图。";
  const saveBlocked = !previewReady || (layered && (!reviewed || !currentDetail));
  function selectPoint(x, y) {
    setPoint([Math.max(0, Math.min(1, x)), Math.max(0, Math.min(1, y))]);
    setReviewedDetail(null);
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
      <p className="hdde-color-task-state" role="status">{description}</p>
    </>, actionHost)}
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
          <h2 id="print-output-title">喷绘成品预览</h2><p>点击画面或用方向键移动选框，对照同一位置。</p>
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
            <img src={output.preview_url} alt="喷绘成品预览" onClick={event => {
              const r = event.currentTarget.getBoundingClientRect();
              selectPoint((event.clientX-r.left)/r.width, (event.clientY-r.top)/r.height);
            }} onLoad={event => {
              const image = event.currentTarget;
              if (image.naturalWidth === output.width && image.naturalHeight === output.height) setPreviewReady(true);
              else setError("成品像素与预检不一致，请到输出中心核对。");
            }} onError={() => setError("成品预览加载失败，请到输出中心检查已生成的文件。")}/>
            {previewReady && cropWidth > 0 && <span className="print-inspect-box" aria-hidden="true" style={{
              left: `${100*cropX/output.width}%`, top: `${100*cropY/output.height}%`,
              width: `${100*cropWidth/output.width}%`, height: `${100*cropHeight/output.height}%`,
            }}/>}
          </div>
        </div>
        <div className="print-crops">
          <h3 id="print-crop-heading">局部对照</h3>
          <div className="print-detail-pair">{["原图等比参考","成品原像素"].map((label,i) => <figure key={label}>
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
      <p className="print-file-row"><strong>输出 / 喷绘出图 / {output.filename}</strong><span>{output.width} × {output.height} px · {display(output.ppi)} PPI{output.upscale?.method === "SR_FUSION" ? " · 已超清重建" : ""}</span></p>
    </section>}
  </>;
}

function PrintWorkflow({loading, source, plan, ppi, busy, setBusy, onNavigate, children, readError, onSelect, layered, setLayered, sizeLabel}) {
  const pickerRef = useRef(null);
  const [actionHost, setActionHost] = useState(null);
  const [recipe, setRecipe] = useState(null);
  const [custom, setCustom] = useState(false);
  const [cw, setCw] = useState("80"), [ch, setCh] = useState("120");
  const paper = layered && custom
    ? {pixelWidth:Math.round(Number(cw)*ppi/2.54), pixelHeight:Math.round(Number(ch)*ppi/2.54)} : plan;
  const sizeAllowed = paper && [paper.pixelWidth,paper.pixelHeight].every(n =>
    Number.isSafeInteger(n) && n > 0 && n <= 32768) && paper.pixelWidth * paper.pixelHeight <= MAX_PRINT_PIXELS;
  const sizeError = "请调整出图尺寸，目标单边最多 32768 px，总像素最多 8000 万。";
  let unavailable = "";
  if (!source) unavailable = readError ? "请重新选择原图。" : (loading ? "正在读取原图…" : "等待选择图片");
  else if (plan.error) unavailable = plan.error;
  else if (!sizeAllowed) unavailable = sizeError;
  else if (layered && !recipe) unavailable = "请先标记并检查分层选区，然后提交出图。";
  let summary = plan;
  if (plan && !plan.error && !sizeAllowed) summary = {error:sizeError};
  if (layered && custom && source && sizeAllowed && !plan.error) {
    const fit = Math.min(paper.pixelWidth/source.width, paper.pixelHeight/source.height);
    summary = {...paper, cmWidth:Number(cw), cmHeight:Number(ch), scale:fit, effectivePpi:ppi/fit};
  }
  return <>
    <HddePageHeader title="喷绘出图" description="按成品尺寸检查原图精度，生成喷绘文件并核对局部细节。"
      meta={<HddeStatusPill tone={source ? "positive" : "neutral"}>{readError ? "原图读取失败" : source ? "原图已载入" : loading ? "正在读取原图" : "待选原图"}</HddeStatusPill>}/>
    <div className="hdde-color-flow hdde-desktop-columns print-flow">
      <div className="hdde-color-intake">
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
            <div className="hdde-color-section-title"><span aria-hidden="true">2</span><h2 id="print-spec">喷绘规格</h2></div>
            <details className="hdde-color-output-path print-settings" open={Boolean(source)}>
              <summary>尺寸与精度<span>{layered && custom ? `${cw} × ${ch} cm` : sizeLabel} · {ppi || "—"} PPI</span></summary>
              <fieldset className="print-spec-controls" disabled={busy} aria-label="喷绘参数">
                {children}
                {layered && source && <>
                  <label>成品画布<select value={custom?"paper":"source"} onChange={e=>setCustom(e.target.value==="paper")}>
                    <option value="source">沿用预检尺寸</option><option value="paper">指定宽高，等比居中留边</option>
                  </select></label>
                  {custom && <div className="print-fields">
                    <label>画布宽度（cm）<input type="number" step="any" min="0" value={cw} onChange={e=>setCw(e.target.value)}/></label>
                    <label>画布高度（cm）<input type="number" step="any" min="0" value={ch} onChange={e=>setCh(e.target.value)}/></label>
                  </div>}
                </>}
              </fieldset>
            </details>
            <PrintSizeSummary result={summary} custom={layered && custom}/>
          </section>
        </div>
        <div className="hdde-color-execution" ref={setActionHost}/>
      </div>
      <div className="hdde-color-outcome print-outcome" data-stage={layered && source ? "layers" : "intake"}>
        <PrintOutput key={JSON.stringify([layered,paper?.pixelWidth,paper?.pixelHeight,ppi,recipe])} source={source}
          plan={paper} ppi={ppi} busy={busy} setBusy={setBusy} onNavigate={onNavigate} layers={recipe} layered={layered}
          unavailable={unavailable} actionHost={actionHost} pickerRef={pickerRef}/>
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
      sizeLabel={mode === "8k" ? "长边 7680 px" : `${axis === "width" ? "宽" : "高"} ${cm || "—"} cm`}>
      <label>计算方式<select value={mode} onChange={e=>setMode(e.target.value)}>
        <option value="physical">按喷绘尺寸计算</option><option value="8k">按 8K 长边估算（7680 px）</option>
      </select></label>
      {mode === "physical" && <div className="print-fields">
        <label>指定边<select value={axis} onChange={e=>setAxis(e.target.value)}>
          <option value="width">宽度</option><option value="height">高度</option>
        </select></label>
        <label>喷绘{axis === "width" ? "宽度" : "高度"}（cm）
          <input type="number" step="any" min="0" value={cm} onChange={e=>setCm(e.target.value)}/>
        </label>
      </div>}
      <div className="print-density">
        <label>目标 PPI（像素/英寸）<input type="number" step="any" min="0" value={ppi} onChange={e=>setPpi(e.target.value)}/></label>
        <div className="print-presets" role="group" aria-label="常用目标精度">
          {[100,150,300].map(value => <button type="button" key={value} aria-pressed={Number(ppi) === value}
            aria-label={`${value} PPI`} onClick={()=>setPpi(String(value))}>{value}</button>)}
        </div>
      </div>
    </PrintWorkflow>
  </div>;
}
