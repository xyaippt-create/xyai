import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import HddeIcon from "./HddeIcon.jsx";
import { HddePageHeader } from "./HddeUI.jsx";
import { fitImageView, normalizedRect, screenToImage, zoomViewAt } from "./localRetouchGeometry.js";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const TOOLS = [
  { key: "brush", label: "画笔" },
  { key: "rectangle", label: "矩形" },
  { key: "erase", label: "擦除" },
  { key: "pan", label: "拖动画布" },
];

function apiUrl(path) {
  return path ? `${API_BASE}${path}` : "";
}

async function requestJson(path, options = {}) {
  const response = await fetch(apiUrl(path), options);
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok || payload?.success === false) {
    const detail = payload?.detail;
    throw new Error((typeof detail === "object" ? detail?.message : detail) || payload?.message || "操作失败，请重试。");
  }
  return payload;
}

function loadCanvasImage(source) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.decoding = "async";
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("图片预览加载失败。"));
    image.src = source;
  });
}

function drawOperation(context, operation) {
  if (operation.type === "clear") {
    context.clearRect(0, 0, context.canvas.width, context.canvas.height);
    return;
  }
  context.save();
  context.globalCompositeOperation = operation.erase ? "destination-out" : "source-over";
  context.fillStyle = "#ffffff";
  context.strokeStyle = "#ffffff";
  context.lineCap = "round";
  context.lineJoin = "round";
  if (operation.type === "rectangle") {
    context.fillRect(operation.x, operation.y, operation.width, operation.height);
  } else if (operation.type === "stroke" && operation.points.length) {
    context.lineWidth = operation.size;
    context.beginPath();
    context.moveTo(operation.points[0].x, operation.points[0].y);
    operation.points.slice(1).forEach((point) => context.lineTo(point.x, point.y));
    if (operation.points.length === 1) {
      context.lineTo(operation.points[0].x + 0.01, operation.points[0].y + 0.01);
    }
    context.stroke();
  }
  context.restore();
}

export function renderRetouchMask(width, height, operations, draft = null) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: false });
  [...operations, ...(draft ? [draft] : [])].forEach((operation) => drawOperation(context, operation));
  return canvas;
}

function maskHasPixels(canvas) {
  const context = canvas.getContext("2d", { willReadFrequently: true });
  const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
  for (let index = 3; index < data.length; index += 4) {
    if (data[index] >= 128) return true;
  }
  return false;
}

function StatusStep({ active, complete, children }) {
  return (
    <li data-state={complete ? "complete" : active ? "active" : "pending"}>
      <span aria-hidden="true" />
      {children}
    </li>
  );
}

export default function LocalRetouchPage({ onOpenOutputCenter }) {
  const fileInputRef = useRef(null);
  const canvasRef = useRef(null);
  const canvasWrapRef = useRef(null);
  const sourceImageRef = useRef(null);
  const resultImageRef = useRef(null);
  const viewRef = useRef({ scale: 1, offsetX: 0, offsetY: 0 });
  const pointerRef = useRef(null);
  const maskRevisionRef = useRef(0);
  const [capabilities, setCapabilities] = useState(null);
  const [session, setSession] = useState(null);
  const [sourceImage, setSourceImage] = useState(null);
  const [resultImage, setResultImage] = useState(null);
  const [operations, setOperations] = useState([]);
  const [redoStack, setRedoStack] = useState([]);
  const [draft, setDraft] = useState(null);
  const [tool, setTool] = useState("brush");
  const [brushSize, setBrushSize] = useState(36);
  const [view, setView] = useState(viewRef.current);
  const [canvasSize, setCanvasSize] = useState({ width: 960, height: 620, dpr: 1 });
  const [displayMode, setDisplayMode] = useState("edit");
  const [comparePosition, setComparePosition] = useState(50);
  const [result, setResult] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [saved, setSaved] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("请选择一张自有或已授权图片开始修整。");

  useEffect(() => {
    requestJson("/api/local-retouch/capabilities")
      .then((payload) => setCapabilities(payload.data))
      .catch((reason) => setError(reason.message));
  }, []);

  useEffect(() => {
    const element = canvasWrapRef.current;
    if (!element) return undefined;
    const update = () => {
      const rect = element.getBoundingClientRect();
      setCanvasSize({
        width: Math.max(320, Math.round(rect.width)),
        height: Math.max(360, Math.round(rect.height)),
        dpr: Math.min(2, window.devicePixelRatio || 1),
      });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const imageSize = useMemo(() => ({ width: session?.width || 1, height: session?.height || 1 }), [session]);

  const updateView = useCallback((next) => {
    viewRef.current = next;
    setView(next);
  }, []);

  const fitView = useCallback(() => {
    if (!session) return;
    updateView(fitImageView(session.width, session.height, canvasSize.width, canvasSize.height, 36));
  }, [canvasSize.height, canvasSize.width, session, updateView]);

  useEffect(() => {
    if (session && sourceImage) fitView();
  }, [fitView, session, sourceImage]);

  useEffect(() => {
    sourceImageRef.current = sourceImage;
  }, [sourceImage]);
  useEffect(() => {
    resultImageRef.current = resultImage;
  }, [resultImage]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const source = sourceImageRef.current;
    if (!canvas) return;
    const { width, height, dpr } = canvasSize;
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
    }
    const context = canvas.getContext("2d");
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#080c12";
    context.fillRect(0, 0, width, height);
    if (!source || !session) return;
    const currentView = viewRef.current;
    const drawImage = (image) => context.drawImage(
      image,
      currentView.offsetX,
      currentView.offsetY,
      session.width * currentView.scale,
      session.height * currentView.scale,
    );
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = "high";
    if (displayMode === "compare" && resultImageRef.current) {
      drawImage(resultImageRef.current);
      context.save();
      context.beginPath();
      context.rect(0, 0, width * (comparePosition / 100), height);
      context.clip();
      drawImage(source);
      context.restore();
      const divider = width * (comparePosition / 100);
      context.fillStyle = "#ffffff";
      context.fillRect(divider - 1, 0, 2, height);
      context.fillStyle = "rgba(9, 13, 20, 0.82)";
      context.fillRect(12, 12, 56, 28);
      context.fillRect(width - 68, 12, 56, 28);
      context.fillStyle = "#ffffff";
      context.font = "600 13px Microsoft YaHei UI";
      context.fillText("原图", 26, 31);
      context.fillText("结果", width - 54, 31);
    } else {
      drawImage(source);
      const mask = renderRetouchMask(session.width, session.height, operations, draft);
      const overlay = document.createElement("canvas");
      overlay.width = session.width;
      overlay.height = session.height;
      const overlayContext = overlay.getContext("2d");
      overlayContext.drawImage(mask, 0, 0);
      overlayContext.globalCompositeOperation = "source-in";
      overlayContext.fillStyle = "rgba(45, 111, 232, 0.62)";
      overlayContext.fillRect(0, 0, overlay.width, overlay.height);
      drawImage(overlay);
    }
  }, [canvasSize, comparePosition, displayMode, draft, operations, session]);

  useEffect(() => {
    draw();
  }, [draw, view]);

  const invalidateResult = useCallback(() => {
    maskRevisionRef.current += 1;
    setResult(null);
    setResultImage(null);
    setConfirmed(false);
    setSaved(null);
    setDisplayMode("edit");
    setNotice("选区已更新，请重新处理后查看结果。");
  }, []);

  const commitOperation = useCallback((operation) => {
    setOperations((current) => [...current, operation]);
    setRedoStack([]);
    invalidateResult();
  }, [invalidateResult]);

  const chooseFile = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy("intake");
    setError("");
    setNotice("正在读取图片并建立本地工作副本…");
    const form = new FormData();
    form.append("file", file);
    try {
      const payload = await requestJson("/api/local-retouch/intake", { method: "POST", body: form });
      const nextSession = payload.data;
      const image = await loadCanvasImage(apiUrl(`${nextSession.source_url}?v=${Date.now()}`));
      setSession(nextSession);
      setSourceImage(image);
      setResult(null);
      setResultImage(null);
      setOperations([]);
      setRedoStack([]);
      setConfirmed(false);
      setSaved(null);
      setDisplayMode("edit");
      maskRevisionRef.current = 0;
      setNotice("图片已导入。请用画笔或矩形标记需要修整的小范围区域。");
    } catch (reason) {
      setError(reason.message);
      setNotice("");
    } finally {
      setBusy("");
    }
  };

  const canvasPoint = (event) => {
    const rect = canvasRef.current.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };

  const handlePointerDown = (event) => {
    if (!session || busy || displayMode === "compare") return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const screen = canvasPoint(event);
    if (tool === "pan" || event.button === 1 || event.altKey) {
      pointerRef.current = { type: "pan", screen, view: { ...viewRef.current } };
      return;
    }
    const image = screenToImage(screen, viewRef.current, imageSize);
    if (tool === "rectangle") {
      pointerRef.current = { type: "rectangle", start: image };
      setDraft({ type: "rectangle", x: image.x, y: image.y, width: 0, height: 0, erase: false });
    } else {
      const operation = { type: "stroke", points: [image], size: brushSize, erase: tool === "erase" };
      pointerRef.current = operation;
      setDraft(operation);
    }
  };

  const handlePointerMove = (event) => {
    const pointer = pointerRef.current;
    if (!pointer || !session) return;
    const screen = canvasPoint(event);
    if (pointer.type === "pan") {
      updateView({
        ...pointer.view,
        offsetX: pointer.view.offsetX + screen.x - pointer.screen.x,
        offsetY: pointer.view.offsetY + screen.y - pointer.screen.y,
      });
      return;
    }
    const image = screenToImage(screen, viewRef.current, imageSize);
    if (pointer.type === "rectangle") {
      setDraft({ type: "rectangle", ...normalizedRect(pointer.start, image, imageSize), erase: false });
    } else {
      const next = { ...pointer, points: [...pointer.points, image] };
      pointerRef.current = next;
      setDraft(next);
    }
  };

  const handlePointerUp = (event) => {
    const pointer = pointerRef.current;
    pointerRef.current = null;
    setDraft(null);
    if (!pointer || pointer.type === "pan" || !session) return;
    const screen = canvasPoint(event);
    const image = screenToImage(screen, viewRef.current, imageSize);
    const operation = pointer.type === "rectangle"
      ? { type: "rectangle", ...normalizedRect(pointer.start, image, imageSize), erase: false }
      : { ...pointer, points: [...pointer.points, image] };
    if (operation.type === "rectangle" && (operation.width < 1 || operation.height < 1)) return;
    commitOperation(operation);
  };

  const zoomBy = (factor) => {
    const current = viewRef.current;
    updateView(zoomViewAt(current, { x: canvasSize.width / 2, y: canvasSize.height / 2 }, current.scale * factor));
  };

  const undo = () => {
    if (!operations.length || busy) return;
    const last = operations[operations.length - 1];
    setOperations(operations.slice(0, -1));
    setRedoStack((current) => [...current, last]);
    invalidateResult();
  };

  const redo = () => {
    if (!redoStack.length || busy) return;
    const last = redoStack[redoStack.length - 1];
    setRedoStack(redoStack.slice(0, -1));
    setOperations((current) => [...current, last]);
    invalidateResult();
  };

  const clearMask = () => {
    if (!operations.length || busy) return;
    commitOperation({ type: "clear" });
  };

  const processMask = async () => {
    if (!session || busy) return;
    const mask = renderRetouchMask(session.width, session.height, operations);
    if (!maskHasPixels(mask)) {
      setError("请先标记需要修整的区域。");
      return;
    }
    const revision = Math.max(1, maskRevisionRef.current);
    setBusy("process");
    setError("");
    setNotice("正在使用本地修整引擎处理当前选区，请稍候…");
    try {
      const payload = await requestJson(`/api/local-retouch/sessions/${session.session_id}/process`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mask_png_base64: mask.toDataURL("image/png"), mask_revision: revision }),
      });
      const next = payload.data;
      const image = await loadCanvasImage(apiUrl(`${next.result_url}?v=${Date.now()}`));
      setResult(next);
      setResultImage(image);
      setConfirmed(false);
      setSaved(null);
      setDisplayMode("compare");
      setNotice("修整结果已生成。请拖动对比滑杆检查；如需调整，请返回编辑选区后重新处理。");
    } catch (reason) {
      setError(reason.message);
      setNotice("");
    } finally {
      setBusy("");
    }
  };

  const confirmResult = async () => {
    if (!result || busy) return;
    setBusy("confirm");
    setError("");
    try {
      const payload = await requestJson(`/api/local-retouch/sessions/${session.session_id}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mask_revision: result.mask_revision }),
      });
      setConfirmed(true);
      setResult(payload.data);
      setNotice("当前结果已人工确认。确认只代表您已查看并接受当前画面，尚未写入派生文件。");
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy("");
    }
  };

  const saveResult = async () => {
    if (!confirmed || busy) return;
    setBusy("save");
    setError("");
    try {
      const payload = await requestJson(`/api/local-retouch/sessions/${session.session_id}/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      setSaved(payload.data);
      setNotice("派生结果已保存并进入输出中心，原图和当前工作源均未被覆盖。");
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy("");
    }
  };

  const canProcess = Boolean(session && operations.length && !busy && capabilities?.available);

  return (
    <section className="hdde-retouch-page hdde-page-frame hdde-page-stack" data-testid="retouch-product-page" aria-labelledby="retouch-title">
      <input ref={fileInputRef} type="file" accept="image/png,image/jpeg" hidden onChange={chooseFile} data-testid="retouch-file-input" />
      <HddePageHeader
        title="标记修整"
        headingId="retouch-title"
        description="只处理您人工标记的小范围区域；原图始终保留，确认后另存派生结果。"
        actions={<button type="button" className="hdde-primary-action" onClick={() => fileInputRef.current?.click()} disabled={Boolean(busy)}>
          {session ? "更换图片" : "导入图片"}
        </button>}
      />

      <div className="hdde-retouch-status" role={error ? "alert" : "status"} data-tone={error ? "error" : busy ? "loading" : "info"}>
        <strong>{error ? "当前操作未完成" : busy ? "正在处理" : "本地安全工作流"}</strong>
        <span>{error || notice}</span>
      </div>

      <div className="hdde-retouch-layout">
        <aside className="hdde-retouch-tools" aria-label="修整工具">
          <div className="hdde-retouch-tool-group">
            <span className="hdde-retouch-tool-label">选区工具</span>
            {TOOLS.map((item) => (
              <button
                key={item.key}
                type="button"
                aria-pressed={tool === item.key}
                className={tool === item.key ? "is-active" : ""}
                onClick={() => { setTool(item.key); setDisplayMode("edit"); }}
                disabled={!session || Boolean(busy)}
                data-testid={`retouch-tool-${item.key}`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <label className="hdde-retouch-range-label">
            <span>画笔大小</span>
            <strong>{brushSize}px</strong>
            <input type="range" min="8" max="120" step="2" value={brushSize} onChange={(event) => setBrushSize(Number(event.target.value))} disabled={!session || Boolean(busy)} />
          </label>
          <div className="hdde-retouch-inline-actions">
            <button type="button" onClick={undo} disabled={!operations.length || Boolean(busy)}>撤销</button>
            <button type="button" onClick={redo} disabled={!redoStack.length || Boolean(busy)}>重做</button>
            <button type="button" onClick={clearMask} disabled={!operations.length || Boolean(busy)}>清除</button>
          </div>
          <div className="hdde-retouch-tool-group">
            <span className="hdde-retouch-tool-label">画布视图</span>
            <div className="hdde-retouch-inline-actions">
              <button type="button" onClick={() => zoomBy(0.8)} disabled={!session}>缩小</button>
              <button type="button" onClick={fitView} disabled={!session}>适合</button>
              <button type="button" onClick={() => zoomBy(1.25)} disabled={!session}>放大</button>
            </div>
            <small>{session ? `${Math.round(view.scale * 100)}%` : "—"}</small>
          </div>
          <ol className="hdde-retouch-steps" aria-label="处理步骤">
            <StatusStep active={!session} complete={Boolean(session)}>导入图片</StatusStep>
            <StatusStep active={Boolean(session && !result)} complete={Boolean(result)}>标记并处理</StatusStep>
            <StatusStep active={Boolean(result && !confirmed)} complete={confirmed}>人工确认</StatusStep>
            <StatusStep active={Boolean(confirmed && !saved)} complete={Boolean(saved)}>另存结果</StatusStep>
          </ol>
        </aside>

        <main className={`hdde-retouch-stage ${session ? "has-image" : "is-empty"}`}>
          <div className="hdde-retouch-stage-bar">
            <div>
              <strong>{session?.file_name || "尚未导入图片"}</strong>
              <span>{session ? `${session.width} × ${session.height} · ${session.format}` : "支持PNG、JPG、JPEG，单图最大50MB"}</span>
            </div>
            {result ? (
              <div className="hdde-retouch-view-tabs" role="group" aria-label="画面查看模式">
                <button type="button" aria-pressed={displayMode === "edit"} onClick={() => setDisplayMode("edit")}>编辑选区</button>
                <button type="button" aria-pressed={displayMode === "compare"} onClick={() => setDisplayMode("compare")}>前后对比</button>
              </div>
            ) : null}
          </div>
          <div ref={canvasWrapRef} className={`hdde-retouch-canvas-wrap ${session ? "has-image" : "is-empty"}`} data-testid="retouch-canvas-wrap">
            <canvas
              ref={canvasRef}
              className={`hdde-retouch-canvas is-${tool}`}
              width={Math.round(canvasSize.width * canvasSize.dpr)}
              height={Math.round(canvasSize.height * canvasSize.dpr)}
              aria-label={session ? "局部修整主画布" : "等待导入图片的局部修整画布"}
              data-testid="retouch-canvas"
              data-image-width={session?.width || ""}
              data-image-height={session?.height || ""}
              data-view-scale={view.scale}
              data-view-offset-x={view.offsetX}
              data-view-offset-y={view.offsetY}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerCancel={handlePointerUp}
              onWheel={(event) => {
                if (!session) return;
                event.preventDefault();
                const point = canvasPoint(event);
                updateView(zoomViewAt(viewRef.current, point, viewRef.current.scale * (event.deltaY > 0 ? 0.9 : 1.1)));
              }}
            />
            {!session ? (
              <button type="button" className="hdde-retouch-empty" onClick={() => fileInputRef.current?.click()}>
                <span className="hdde-retouch-empty__icon"><HddeIcon name="retouch" size={24} /></span>
                <strong>导入一张图片开始局部修整</strong>
                <span>画布将在图片导入后启用；图片只在本机处理。</span>
                <small>支持 PNG、JPG、JPEG · 单图最大 50 MB</small>
              </button>
            ) : null}
          </div>
          {displayMode === "compare" && result ? (
            <label className="hdde-retouch-compare-control">
              <span>拖动查看原图与修整结果</span>
              <input data-testid="retouch-compare-slider" type="range" min="0" max="100" value={comparePosition} onChange={(event) => setComparePosition(Number(event.target.value))} />
            </label>
          ) : null}
        </main>

        <aside className="hdde-retouch-actions" aria-label="结果操作">
          <div className="hdde-retouch-summary">
            <span>当前状态</span>
            <strong>{saved ? "派生结果已保存" : confirmed ? "结果已确认" : result ? "等待人工确认" : session ? "等待处理" : "等待导入"}</strong>
          </div>
          <button type="button" className="hdde-primary-action" onClick={processMask} disabled={!canProcess} data-testid="retouch-process">
            {busy === "process" ? "正在本地修整…" : result ? "按当前选区重新处理" : "开始局部修整"}
          </button>
          {result ? (
            <button type="button" onClick={confirmResult} disabled={Boolean(busy) || confirmed} data-testid="retouch-confirm">
              {confirmed ? "已人工确认" : "确认当前结果"}
            </button>
          ) : null}
          <button type="button" onClick={saveResult} disabled={!confirmed || Boolean(busy) || Boolean(saved)} data-testid="retouch-save">
            {busy === "save" ? "正在保存…" : saved ? "已另存派生结果" : "另存派生结果"}
          </button>
          {saved ? (
            <div className="hdde-retouch-saved" data-testid="retouch-saved-result">
              <span>保存结果</span>
              <strong title={saved.output_file_name}>{saved.output_file_name}</strong>
              <small>{saved.output_directory_name}</small>
              <a href={apiUrl(saved.output_url)} target="_blank" rel="noreferrer">查看派生结果</a>
              <button type="button" onClick={() => requestJson(`/api/local-retouch/sessions/${session.session_id}/open-folder`, { method: "POST" }).catch((reason) => setError(reason.message))}>
                打开所在目录
              </button>
              <button type="button" onClick={onOpenOutputCenter} data-testid="retouch-open-output-center">
                前往输出中心
              </button>
            </div>
          ) : null}
          <div className="hdde-retouch-boundary" role="note">
            <strong>使用边界</strong>
            <p>仅处理自有、已授权素材中的内部标记、污点、划痕和局部瑕疵。复杂人物、文字、Logo或产品结构附近请放大检查。</p>
          </div>
        </aside>
      </div>
    </section>
  );
}
