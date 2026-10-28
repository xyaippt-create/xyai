import React, { useEffect, useMemo, useRef, useState } from "react";
import { HddePageHeader, HddeStatusPill } from "./HddeUI.jsx";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const ACCEPTED_IMAGE = /\.(png|jpe?g)$/i;
const POSITION_OPTIONS = Object.freeze([
  ["top-left", "左上"], ["top-center", "上中"], ["top-right", "右上"],
  ["middle-left", "左中"], ["center", "居中"], ["middle-right", "右中"],
  ["bottom-left", "左下"], ["bottom-center", "下中"], ["bottom-right", "右下"],
]);
const STATUS_LABELS = Object.freeze({ pending: "等待处理", processing: "处理中", completed: "已完成", failed: "失败", canceled: "已取消" });
const BATCH_RESULT_STATUSES = Object.freeze(["FULL_SUCCESS", "PARTIAL_SUCCESS", "FAILED", "CANCELED"]);
const BATCH_ID_PATTERN = /^watermark_batch_[a-f0-9]{16}$/i;
const SCRUB_THRESHOLD_PX = 4;
const FONT_OPTIONS = Object.freeze([
  ["source_han_sans_cn_medium", "思源黑体 CN Medium", "hdde-watermark-font--sans-medium"],
  ["source_han_serif_cn_heavy", "思源宋体 CN Heavy", "hdde-watermark-font--serif-heavy"],
]);
const TEXT_PRESETS = Object.freeze(["仅供预览", "内部资料", "仅供内部使用", "请勿转载", "版权所有", "样稿", "DEMO", "未经授权禁止使用"]);

export function validateNumericDraft(rawValue, { label, min, max, step = 1 }) {
  const raw = String(rawValue ?? "").trim();
  if (!raw) return { valid: false, error: `请输入${label}。` };
  const value = Number(raw);
  if (!Number.isFinite(value)) return { valid: false, error: `${label}必须是有效数字。` };
  if (value < min || value > max) return { valid: false, error: `${label}必须在 ${min} 到 ${max} 之间。` };
  const steps = (value - min) / step;
  if (Math.abs(steps - Math.round(steps)) > 1e-8) return { valid: false, error: `${label}必须按 ${step} 递增。` };
  return { valid: true, value };
}

export function normalizeHexColor(rawValue) {
  const value = String(rawValue ?? "").trim().toUpperCase();
  return /^#[0-9A-F]{6}$/.test(value) ? { valid: true, value } : { valid: false, error: "颜色必须使用 #RRGGBB 格式。" };
}

export function stepScrubbableValue(value, deltaSteps, { min, max, step = 1 }) {
  const next = Math.min(max, Math.max(min, Number(value) + Number(deltaSteps) * step));
  return Number(next.toFixed(8));
}

export function hexToHsv(hex) {
  const normalized = normalizeHexColor(hex);
  if (!normalized.valid) throw new Error(normalized.error);
  const [r, g, b] = [1, 3, 5].map((offset) => Number.parseInt(normalized.value.slice(offset, offset + 2), 16) / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  let h = 0;
  if (delta) {
    if (max === r) h = 60 * (((g - b) / delta) % 6);
    else if (max === g) h = 60 * ((b - r) / delta + 2);
    else h = 60 * ((r - g) / delta + 4);
  }
  if (h < 0) h += 360;
  return { h, s: max ? (delta / max) * 100 : 0, v: max * 100 };
}

export function hsvToHex(h, s, v) {
  const hue = ((Number(h) % 360) + 360) % 360;
  const saturation = Math.min(100, Math.max(0, Number(s))) / 100;
  const value = Math.min(100, Math.max(0, Number(v))) / 100;
  const chroma = value * saturation;
  const x = chroma * (1 - Math.abs((hue / 60) % 2 - 1));
  const match = value - chroma;
  const [r, g, b] = hue < 60 ? [chroma, x, 0]
    : hue < 120 ? [x, chroma, 0]
      : hue < 180 ? [0, chroma, x]
        : hue < 240 ? [0, x, chroma]
          : hue < 300 ? [x, 0, chroma]
            : [chroma, 0, x];
  return `#${[r, g, b].map((channel) => Math.round((channel + match) * 255).toString(16).padStart(2, "0")).join("").toUpperCase()}`;
}

export function getMarginAvailability(position, tile = false) {
  if (tile) return { horizontal: false, vertical: false };
  return {
    horizontal: !new Set(["top-center", "center", "bottom-center"]).has(position),
    vertical: !new Set(["middle-left", "center", "middle-right"]).has(position),
  };
}

function responseMessage(body, fallback) {
  const detail = body?.detail;
  return (typeof detail === "object" ? detail?.message : detail) || body?.message || fallback;
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function makeItem(file) {
  return { id: `${file.name}-${file.size}-${file.lastModified}-${crypto.randomUUID()}`, file, status: "pending", failureReason: "", outputName: "" };
}

function itemDisplayName(item) {
  return item?.file?.name || item?.fileName || "未命名图片";
}

export function validateRecoveredBatchResult(recovered, requestedBatchId) {
  if (recovered?.batch_id !== requestedBatchId) {
    const mismatch = new Error("返回的批量水印任务与当前链接不一致，已停止显示。");
    mismatch.code = "WATERMARK_BATCH_ID_MISMATCH";
    throw mismatch;
  }
  if (!BATCH_RESULT_STATUSES.includes(recovered?.batch_status) || !Array.isArray(recovered?.items)) {
    throw new Error("批量水印任务尚未形成可恢复的真实结果。");
  }
  return recovered;
}

export function mapRecoveredBatchItems(recovered) {
  return recovered.items.map((item, index) => ({
    id: `${recovered.batch_id}-${item?.item_id || "item"}-${index}`,
    file: null,
    fileName: item?.file_name || item?.original_filename || item?.output_file_name || `第 ${index + 1} 张图片`,
    status: item?.status === "completed" ? "completed" : item?.status === "canceled" ? "canceled" : "failed",
    failureReason: item?.failure_reason || "",
    outputName: item?.output_file_name || "",
    recovered: true,
  }));
}

function useDismissibleMenu(open, setOpen, rootRef) {
  useEffect(() => {
    if (!open) return undefined;
    const dismiss = (event) => {
      if (event.type === "keydown" && event.key !== "Escape") return;
      if (event.type === "pointerdown" && rootRef.current?.contains(event.target)) return;
      setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", dismiss);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", dismiss);
    };
  }, [open, rootRef, setOpen]);
}

function TextPresetField({ value, onChange }) {
  const rootRef = useRef(null);
  const [open, setOpen] = useState(false);
  useDismissibleMenu(open, setOpen, rootRef);
  return (
    <div className="hdde-watermark-field">
      <span id="batch-watermark-text-label">水印文字</span>
      <div className="hdde-watermark-combobox" ref={rootRef}>
        <input data-testid="batch-watermark-text" aria-labelledby="batch-watermark-text-label" value={value} maxLength={200} onChange={(event) => onChange(event.target.value)} />
        <button type="button" aria-label="选择常用水印文字" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((current) => !current)}><span className="hdde-watermark-chevron" aria-hidden="true" /></button>
        {open ? <div className="hdde-watermark-option-menu" role="listbox" aria-label="常用水印文字">
          {TEXT_PRESETS.map((preset) => <button key={preset} type="button" role="option" aria-selected={value === preset} onClick={() => { onChange(preset); setOpen(false); }}>{preset}</button>)}
        </div> : null}
      </div>
    </div>
  );
}

function FontSelector({ value, onChange }) {
  const rootRef = useRef(null);
  const [open, setOpen] = useState(false);
  useDismissibleMenu(open, setOpen, rootRef);
  const selected = FONT_OPTIONS.find(([fontId]) => fontId === value) || FONT_OPTIONS[0];
  return (
    <div className="hdde-watermark-field">
      <span id="batch-watermark-font-label">字体</span>
      <div className="hdde-watermark-select" ref={rootRef}>
        <button type="button" data-testid="batch-watermark-font" className={selected[2]} aria-labelledby="batch-watermark-font-label" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((current) => !current)}>
          <span>{selected[1]}</span><span className="hdde-watermark-chevron" aria-hidden="true" />
        </button>
        {open ? <div className="hdde-watermark-option-menu" role="listbox" aria-label="内置字体">
          {FONT_OPTIONS.map(([fontId, label, previewClass]) => <button key={fontId} type="button" role="option" className={previewClass} aria-selected={value === fontId} onClick={() => { onChange(fontId); setOpen(false); }}>{label}</button>)}
        </div> : null}
      </div>
    </div>
  );
}

function ScrubbableNumericField({ label, value, min, max, step = 1, suffix, onChange, testId }) {
  const labelId = `${testId}-label`;
  const errorId = `${testId}-error`;
  const [draft, setDraft] = useState(String(value));
  const [fieldError, setFieldError] = useState("");
  const pointerState = useRef(null);

  useEffect(() => {
    setDraft(String(value));
    setFieldError("");
  }, [value]);

  const acceptDraft = (nextDraft, commit = false) => {
    setDraft(nextDraft);
    const checked = validateNumericDraft(nextDraft, { label, min, max, step });
    if (checked.valid) {
      onChange(checked.value);
      setFieldError("");
      if (commit) setDraft(String(checked.value));
    } else if (commit) {
      setFieldError(checked.error);
    }
  };

  const updateBySteps = (deltaSteps) => {
    const next = stepScrubbableValue(value, deltaSteps, { min, max, step });
    setDraft(String(next));
    setFieldError("");
    onChange(next);
  };

  const onPointerDown = (event) => {
    if (event.button !== 0) return;
    pointerState.current = { pointerId: event.pointerId, startX: event.clientX, startValue: value, dragging: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event) => {
    const state = pointerState.current;
    if (!state || state.pointerId !== event.pointerId) return;
    const deltaX = event.clientX - state.startX;
    if (!state.dragging && Math.abs(deltaX) < SCRUB_THRESHOLD_PX) return;
    state.dragging = true;
    const next = stepScrubbableValue(state.startValue, Math.round(deltaX / SCRUB_THRESHOLD_PX), { min, max, step });
    setDraft(String(next));
    setFieldError("");
    onChange(next);
    event.preventDefault();
  };

  const finishPointer = (event) => {
    if (pointerState.current?.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    pointerState.current = null;
  };

  return (
    <div className="hdde-watermark-field">
      <span id={labelId}>{label}</span>
      <div
        className="hdde-watermark-scrub-input"
        data-testid={testId}
        data-control="scrubbable"
        data-min={min}
        data-max={max}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={finishPointer}
        onPointerCancel={finishPointer}
      >
        <input
          data-testid={`${testId}-manual`}
          aria-labelledby={labelId}
          type="text"
          inputMode="numeric"
          value={draft}
          aria-invalid={Boolean(fieldError)}
          aria-describedby={fieldError ? errorId : undefined}
          onChange={(event) => acceptDraft(event.target.value)}
          onBlur={(event) => acceptDraft(event.target.value, true)}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
            if (event.key === "ArrowUp" || event.key === "ArrowDown") {
              event.preventDefault();
              updateBySteps(event.key === "ArrowUp" ? 1 : -1);
            }
          }}
        />
        <span aria-hidden="true">{suffix}</span>
      </div>
      {fieldError ? <small id={errorId} className="hdde-watermark-field-error" role="alert">{fieldError}</small> : null}
    </div>
  );
}

function ColorField({ value, onChange }) {
  const rootRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(value);
  const [fieldError, setFieldError] = useState("");
  const currentHsv = useMemo(() => hexToHsv(value), [value]);
  const [hue, setHue] = useState(currentHsv.h);
  useDismissibleMenu(open, setOpen, rootRef);
  useEffect(() => { setDraft(value); setFieldError(""); }, [value]);
  useEffect(() => { if (currentHsv.s > 0) setHue(currentHsv.h); }, [currentHsv.h, currentHsv.s]);

  const acceptDraft = (nextDraft, commit = false) => {
    setDraft(nextDraft);
    const checked = normalizeHexColor(nextDraft);
    if (checked.valid) {
      onChange(checked.value);
      setFieldError("");
      if (commit) setDraft(checked.value);
    } else if (commit) {
      setFieldError(checked.error);
    }
  };

  const updateSaturationValue = (event) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const saturation = Math.min(100, Math.max(0, (event.clientX - bounds.left) * 100 / bounds.width));
    const brightness = Math.min(100, Math.max(0, 100 - (event.clientY - bounds.top) * 100 / bounds.height));
    onChange(hsvToHex(hue, saturation, brightness));
  };

  return (
    <div className="hdde-watermark-field hdde-watermark-color" ref={rootRef}>
      <span id="batch-watermark-color-label">颜色</span>
      <div className="hdde-watermark-color-control">
        <button type="button" data-testid="batch-watermark-color-swatch" aria-label="打开颜色选择器" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((current) => !current)}><span style={{ backgroundColor: value }} /></button>
        <input data-testid="batch-watermark-color-hex" aria-labelledby="batch-watermark-color-label" type="text" inputMode="text" value={draft} maxLength={7} spellCheck="false" aria-invalid={Boolean(fieldError)} aria-describedby={fieldError ? "batch-watermark-color-error" : undefined} onChange={(event) => acceptDraft(event.target.value)} onBlur={(event) => acceptDraft(event.target.value, true)} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} />
        {open ? <div className="hdde-watermark-color-popover" data-testid="batch-watermark-color-popover" role="dialog" aria-label="颜色选择器">
          <div
            className="hdde-watermark-sv-picker"
            data-testid="batch-watermark-saturation-value"
            role="group"
            aria-label="饱和度和明度"
            tabIndex="0"
            style={{ backgroundColor: `hsl(${hue} 100% 50%)` }}
            onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); updateSaturationValue(event); }}
            onPointerMove={(event) => { if (event.currentTarget.hasPointerCapture(event.pointerId)) updateSaturationValue(event); }}
            onPointerUp={(event) => { if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }}
            onKeyDown={(event) => {
              const directions = { ArrowLeft: [-2, 0], ArrowRight: [2, 0], ArrowUp: [0, 2], ArrowDown: [0, -2] };
              if (!directions[event.key]) return;
              event.preventDefault();
              const [sDelta, vDelta] = directions[event.key];
              onChange(hsvToHex(hue, currentHsv.s + sDelta, currentHsv.v + vDelta));
            }}
          >
            <span className="hdde-watermark-sv-marker" style={{ left: `${currentHsv.s}%`, top: `${100 - currentHsv.v}%` }} />
          </div>
          <input
            data-testid="batch-watermark-hue"
            aria-label="色相"
            type="range"
            min="0"
            max="359"
            step="1"
            value={Math.round(hue)}
            onChange={(event) => {
              const nextHue = Number(event.target.value);
              setHue(nextHue);
              onChange(hsvToHex(nextHue, currentHsv.s || 100, currentHsv.v || 100));
            }}
          />
          <label><span>HEX</span><input data-testid="batch-watermark-color-popover-hex" type="text" value={draft} maxLength={7} spellCheck="false" aria-invalid={Boolean(fieldError)} onChange={(event) => acceptDraft(event.target.value)} onBlur={(event) => acceptDraft(event.target.value, true)} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} /></label>
        </div> : null}
      </div>
      {fieldError ? <small id="batch-watermark-color-error" className="hdde-watermark-field-error" role="alert">{fieldError}</small> : null}
    </div>
  );
}

export default function BatchWatermarkPage({ onNavigate, continueResultId = "" }) {
  const imageInputRef = useRef(null);
  const logoInputRef = useRef(null);
  const [items, setItems] = useState([]);
  const [activeId, setActiveId] = useState("");
  const [kind, setKind] = useState("text");
  const [text, setText] = useState("仅供方案预览");
  const [fontId, setFontId] = useState("source_han_sans_cn_medium");
  const [color, setColor] = useState("#FFFFFF");
  const [opacity, setOpacity] = useState(45);
  const [textSize, setTextSize] = useState(36);
  const [rotation, setRotation] = useState(-18);
  const [position, setPosition] = useState("bottom-right");
  const [marginX, setMarginX] = useState(32);
  const [marginY, setMarginY] = useState(32);
  const [tile, setTile] = useState(false);
  const [logoFile, setLogoFile] = useState(null);
  const [imageWidthPercent, setImageWidthPercent] = useState(18);
  const [sourcePreviewUrl, setSourcePreviewUrl] = useState("");
  const [watermarkPreviewUrl, setWatermarkPreviewUrl] = useState("");
  const [previewState, setPreviewState] = useState("idle");
  const [running, setRunning] = useState(false);
  const [runningBatchId, setRunningBatchId] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const requestedBatchId = typeof window === "undefined" ? "" : (new URLSearchParams(window.location.search).get("batch_id") || "").trim();
  const [recoveryState, setRecoveryState] = useState(requestedBatchId ? "loading" : "idle");

  const activeItem = items.find((item) => item.id === activeId) || items[0] || null;
  const hasRunnableItems = items.length > 0 && items.every((item) => item.file || item.resultId);
  const marginAvailability = getMarginAvailability(position, kind === "text" && tile);
  const spec = useMemo(() => ({
    kind, text, font_id: fontId, color, opacity, text_size: textSize, rotation, position,
    margin_x: marginX, margin_y: marginY, tile: kind === "text" && tile,
    image_width_percent: imageWidthPercent,
  }), [kind, text, fontId, color, opacity, textSize, rotation, position, marginX, marginY, tile, imageWidthPercent]);

  useEffect(() => {
    if (!requestedBatchId) {
      setRecoveryState("idle");
      return undefined;
    }
    if (!BATCH_ID_PATTERN.test(requestedBatchId)) {
      setItems([]);
      setActiveId("");
      setResult(null);
      setRecoveryState("error");
      setError("批量水印任务标识无效，未读取任何批次。");
      return undefined;
    }
    const controller = new AbortController();
    setItems([]);
    setActiveId("");
    setResult(null);
    setRecoveryState("loading");
    setError("");
    const recoverBatch = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/batch-watermark/batches/${encodeURIComponent(requestedBatchId)}`, {
          method: "GET",
          cache: "no-store",
          signal: controller.signal,
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok || !body?.data) {
          throw new Error(responseMessage(body, "批量水印任务不存在或无法恢复。"));
        }
        const recovered = validateRecoveredBatchResult(body.data, requestedBatchId);
        const restoredItems = mapRecoveredBatchItems(recovered);
        setItems(restoredItems);
        setActiveId(restoredItems[0]?.id || "");
        setResult(recovered);
        setRecoveryState("ready");
      } catch (reason) {
        if (reason.name === "AbortError") return;
        setItems([]);
        setActiveId("");
        setResult(null);
        setRecoveryState("error");
        setError(reason.message || "批量水印任务不存在或无法恢复。");
      }
    };
    void recoverBatch();
    return () => controller.abort();
  }, [requestedBatchId]);

  useEffect(() => {
    const normalized = String(continueResultId || "").trim();
    if (!normalized || requestedBatchId) return undefined;
    const controller = new AbortController();
    const loadResult = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/result-assets/${encodeURIComponent(normalized)}`, { cache: "no-store", signal: controller.signal });
        const body = await response.json().catch(() => ({}));
        if (!response.ok || !body?.data) throw new Error(responseMessage(body, "当前成品无法作为水印输入。"));
        const source = body.data;
        const item = {
          id: `result-${normalized}`,
          file: null,
          resultId: normalized,
          fileName: source.file_name || "result.png",
          sizeBytes: Number(source.size_bytes || 0),
          previewUrl: source.preview_url || "",
          width: Number(source.width || 0),
          height: Number(source.height || 0),
          status: "pending",
          failureReason: "",
          outputName: "",
        };
        setItems([item]);
        setActiveId(item.id);
        setResult(null);
        setRecoveryState("idle");
        setError("");
      } catch (reason) {
        if (reason.name !== "AbortError") setError(reason.message || "当前成品无法作为水印输入。");
      }
    };
    void loadResult();
    return () => controller.abort();
  }, [continueResultId, requestedBatchId]);

  useEffect(() => {
    if (!activeItem?.file && !activeItem?.previewUrl) {
      setSourcePreviewUrl("");
      return undefined;
    }
    if (activeItem.previewUrl) {
      setSourcePreviewUrl(activeItem.previewUrl);
      return undefined;
    }
    const url = URL.createObjectURL(activeItem.file);
    setSourcePreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [activeItem]);

  useEffect(() => {
    if ((!activeItem?.file && !activeItem?.resultId) || (kind === "image" && !logoFile) || (kind === "text" && !text.trim())) {
      setPreviewState("idle");
      setWatermarkPreviewUrl((current) => { if (current) URL.revokeObjectURL(current); return ""; });
      return undefined;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setPreviewState("loading");
      const formData = new FormData();
      if (activeItem.resultId) formData.append("result_id", activeItem.resultId);
      else formData.append("file", activeItem.file, activeItem.file.name);
      formData.append("spec_json", JSON.stringify(spec));
      if (logoFile) formData.append("watermark_file", logoFile, logoFile.name);
      try {
        const response = await fetch(`${API_BASE}/api/batch-watermark/preview`, { method: "POST", body: formData, signal: controller.signal });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(responseMessage(body, "无法生成真实水印预览。"));
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        setWatermarkPreviewUrl((current) => { if (current) URL.revokeObjectURL(current); return url; });
        setPreviewState("ready");
        setError("");
      } catch (reason) {
        if (reason.name === "AbortError") return;
        setPreviewState("error");
        setError(reason.message || "无法生成真实水印预览。");
      }
    }, 280);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [activeItem, kind, logoFile, spec, text]);

  useEffect(() => () => { if (watermarkPreviewUrl) URL.revokeObjectURL(watermarkPreviewUrl); }, [watermarkPreviewUrl]);

  const addImages = (fileList) => {
    const selected = Array.from(fileList || []);
    const valid = selected.filter((file) => ACCEPTED_IMAGE.test(file.name));
    if (valid.length !== selected.length) setError("已忽略非 PNG、JPG、JPEG 文件。");
    if (!valid.length) return;
    const additions = valid.map(makeItem);
    const replacingRecoveredItems = items.some((item) => !item.file);
    setItems((current) => current.some((item) => !item.file) ? additions : [...current, ...additions]);
    setActiveId((current) => replacingRecoveredItems ? additions[0].id : current || additions[0].id);
    setResult(null);
    setRecoveryState("idle");
    setError("");
  };

  const removeItem = (id) => {
    setItems((current) => current.filter((item) => item.id !== id));
    if (activeId === id) setActiveId("");
    setResult(null);
  };

  const selectLogo = (file) => {
    if (!file) return;
    if (!/\.png$/i.test(file.name)) {
      setError("图片水印必须选择透明 PNG。当前文件未加入。");
      return;
    }
    setLogoFile(file);
    setError("");
    setResult(null);
  };

  const runBatch = async () => {
    if (!hasRunnableItems || running || (kind === "image" && !logoFile) || (kind === "text" && !text.trim())) return;
    setRunning(true);
    setError("");
    setResult(null);
    setItems((current) => current.map((item) => ({ ...item, status: "processing", failureReason: "", outputName: "" })));
    const formData = new FormData();
    items.filter((item) => item.file).forEach((item) => formData.append("files", item.file, item.file.name));
    const batchId = `watermark_batch_${crypto.randomUUID().replaceAll("-", "").slice(0, 16)}`;
    setRunningBatchId(batchId);
    formData.append("batch_id", batchId);
    formData.append("result_ids_json", JSON.stringify(items.map((item) => item.resultId).filter(Boolean)));
    formData.append("spec_json", JSON.stringify(spec));
    if (logoFile) formData.append("watermark_file", logoFile, logoFile.name);
    try {
      const response = await fetch(`${API_BASE}/api/batch-watermark/batches`, { method: "POST", body: formData });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || !body?.data) throw new Error(responseMessage(body, "批量水印处理失败。"));
      const serverItems = body.data.items || [];
      setItems((current) => current.map((item, index) => ({
        ...item,
        status: serverItems[index]?.status || "failed",
        failureReason: serverItems[index]?.failure_reason || "",
        outputName: serverItems[index]?.output_file_name || "",
        resultId: serverItems[index]?.result_id || item.resultId || "",
      })));
      setResult(body.data);
      if (body.data.failed) setError(`${body.data.failed} 张图片处理失败，请查看文件列表中的真实原因。`);
    } catch (reason) {
      setItems((current) => current.map((item) => ({ ...item, status: "failed", failureReason: reason.message || "请求失败" })));
      setError(reason.message || "批量水印处理失败。");
    } finally {
      setRunning(false);
      setRunningBatchId("");
    }
  };

  const openFolder = async () => {
    if (!result?.batch_id) return;
    try {
      const response = await fetch(`${API_BASE}/api/batch-watermark/open-output-folder`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ batch_id: result.batch_id }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(responseMessage(body, "无法打开输出目录。"));
    } catch (reason) {
      setError(reason.message || "无法打开输出目录。");
    }
  };

  const completed = result ? Number(result.completed || 0) : items.filter((item) => item.status === "completed").length;
  const failed = result ? Number(result.failed || 0) : items.filter((item) => item.status === "failed").length;
  const total = result ? Number(result.total || 0) : items.length;
  const progress = total ? Math.round((completed + failed) * 100 / total) : 0;

  return (
    <section className="hdde-watermark-page hdde-page-frame hdde-page-stack" data-testid="batch-watermark-page">
      <input ref={imageInputRef} data-testid="batch-watermark-file-input" type="file" multiple hidden accept=".png,.jpg,.jpeg,image/png,image/jpeg" onChange={(event) => { addImages(event.currentTarget.files); event.currentTarget.value = ""; }} />
      <input ref={logoInputRef} data-testid="batch-watermark-logo-input" type="file" hidden accept=".png,image/png" onChange={(event) => { selectLogo(event.currentTarget.files?.[0]); event.currentTarget.value = ""; }} />
      <HddePageHeader
        title="批量水印"
        description="在本地为多张图片添加文字或透明 PNG 水印。只叠加水印，不缩放、不增强、不覆盖原图。"
        meta={<HddeStatusPill tone="info">本地批量处理</HddeStatusPill>}
        actions={<button type="button" className="hdde-secondary-action" onClick={() => imageInputRef.current?.click()}>添加图片</button>}
      />

      <div className="hdde-watermark-workbench">
        <aside className="hdde-watermark-files" aria-label="图片列表">
          <header><div><p className="hdde-eyebrow">图片列表</p><h2>{items.length} 张图片</h2></div><button type="button" onClick={() => imageInputRef.current?.click()}>继续添加</button></header>
          {items.length ? <div className="hdde-watermark-file-list">{items.map((item) => (
            <article key={item.id} data-active={item.id === activeItem?.id} data-status={item.status}>
              <button type="button" className="hdde-watermark-file-main" onClick={() => setActiveId(item.id)}>
                <strong title={itemDisplayName(item)}>{itemDisplayName(item)}</strong><span>{item.file ? formatBytes(item.file.size) : item.resultId ? formatBytes(item.sizeBytes) : "历史批次"}</span>
                <small title={item.outputName ? `${STATUS_LABELS[item.status]} · ${item.outputName}` : STATUS_LABELS[item.status]}>{STATUS_LABELS[item.status]}{item.outputName ? ` · ${item.outputName}` : ""}</small>
                {item.failureReason ? <em>{item.failureReason}</em> : null}
              </button>
              <button type="button" className="hdde-watermark-remove" aria-label={item.recovered ? `历史批次条目 ${itemDisplayName(item)}` : `移除 ${itemDisplayName(item)}`} disabled={running || item.recovered} onClick={() => removeItem(item.id)}>{item.recovered ? "历史" : "移除"}</button>
            </article>
          ))}</div> : <button type="button" className="hdde-watermark-empty" onClick={() => imageInputRef.current?.click()}><strong>添加需要加水印的图片</strong><span>支持单张或多张 PNG、JPG、JPEG</span></button>}
        </aside>

        <section className="hdde-watermark-preview" aria-label="真实水印预览">
          <header><div><p className="hdde-eyebrow">实时预览</p><h2>{activeItem ? itemDisplayName(activeItem) : "选择代表图片"}</h2></div><span data-state={previewState}>{previewState === "loading" ? "正在生成" : previewState === "ready" ? "后端真实预览" : "等待图片"}</span></header>
          <div className="hdde-watermark-preview-stage" data-testid="batch-watermark-preview">
            {watermarkPreviewUrl ? <img src={watermarkPreviewUrl} alt={`${itemDisplayName(activeItem)}的真实水印效果`} /> : sourcePreviewUrl ? <img src={sourcePreviewUrl} alt={`${itemDisplayName(activeItem)}原图预览`} /> : <div><strong>预览区</strong><span>{activeItem?.recovered ? "历史批次仅恢复文件状态；如需预览，请重新添加原图。" : "添加图片并设置水印后，这里显示后端真实合成结果。"}</span></div>}
            {previewState === "loading" ? <span className="hdde-watermark-preview-loading" role="status">生成真实预览中…</span> : null}
          </div>
          <footer><span>代表图片可从左侧切换</span><strong>预览与批处理使用同一 Watermark Engine</strong></footer>
        </section>

        <aside className="hdde-watermark-settings" aria-label="水印参数">
          <div className="hdde-watermark-mode" role="tablist" aria-label="水印类型">
            <button type="button" role="tab" aria-selected={kind === "text"} onClick={() => setKind("text")}>文字水印</button>
            <button type="button" role="tab" aria-selected={kind === "image"} onClick={() => setKind("image")}>图片水印</button>
          </div>
          <div className="hdde-watermark-form">
            {kind === "text" ? <>
              <TextPresetField value={text} onChange={setText} />
              <FontSelector value={fontId} onChange={setFontId} />
              <div className="hdde-watermark-parameter-grid">
                <ColorField value={color} onChange={setColor} />
                <ScrubbableNumericField label="透明度" value={opacity} min={1} max={100} suffix="%" onChange={setOpacity} testId="batch-watermark-opacity" />
                <ScrubbableNumericField label="大小" value={textSize} min={10} max={160} suffix="px" onChange={setTextSize} testId="batch-watermark-text-size" />
                <ScrubbableNumericField label="旋转角度" value={rotation} min={-180} max={180} suffix="°" onChange={setRotation} testId="batch-watermark-rotation" />
              </div>
              <label className="hdde-watermark-switch"><span><strong>平铺文字</strong><small>间距由系统按图片尺寸自动计算，平铺不使用九宫格边距</small></span><input type="checkbox" checked={tile} onChange={(event) => setTile(event.target.checked)} /></label>
            </> : <>
              <button type="button" className="hdde-watermark-logo-picker" onClick={() => logoInputRef.current?.click()}><strong>{logoFile?.name || "选择透明 PNG"}</strong><span>{logoFile ? formatBytes(logoFile.size) : "保留 Logo 的 Alpha 透明边缘"}</span></button>
              <div className="hdde-watermark-parameter-grid">
                <ScrubbableNumericField label="大小" value={imageWidthPercent} min={1} max={80} suffix="%" onChange={setImageWidthPercent} testId="batch-watermark-logo-size" />
                <ScrubbableNumericField label="透明度" value={opacity} min={1} max={100} suffix="%" onChange={setOpacity} testId="batch-watermark-opacity" />
              </div>
            </>}
            {kind !== "text" || !tile ? <>
              <fieldset className="hdde-watermark-position"><legend>九宫格位置</legend><div>{POSITION_OPTIONS.map(([value, label]) => <button key={value} type="button" aria-label={label} aria-pressed={position === value} onClick={() => setPosition(value)}>{label}</button>)}</div></fieldset>
              <div className="hdde-watermark-margins">
                <label data-disabled={!marginAvailability.horizontal}><span>水平边距{!marginAvailability.horizontal ? <small>当前位置水平居中，不使用</small> : null}</span><input data-testid="batch-watermark-margin-x" type="number" min="0" max="10000" value={marginX} disabled={!marginAvailability.horizontal} onChange={(event) => setMarginX(Math.min(10000, Math.max(0, Number(event.target.value))))} /></label>
                <label data-disabled={!marginAvailability.vertical}><span>垂直边距{!marginAvailability.vertical ? <small>当前位置垂直居中，不使用</small> : null}</span><input data-testid="batch-watermark-margin-y" type="number" min="0" max="10000" value={marginY} disabled={!marginAvailability.vertical} onChange={(event) => setMarginY(Math.min(10000, Math.max(0, Number(event.target.value))))} /></label>
              </div>
            </> : null}
          </div>
          <section className="hdde-watermark-execution">
            <div aria-live="polite"><span>处理进度</span><strong>{completed} 成功 / {failed} 失败 / {total} 总计</strong></div>
            <progress aria-label={running ? "批量水印处理中" : "批量水印处理进度"} max="100" value={running ? undefined : progress}>{running ? "处理中" : `${progress}%`}</progress>
            <button data-testid="batch-watermark-run" type="button" className="hdde-primary-action" disabled={!hasRunnableItems || running || (kind === "image" && !logoFile) || (kind === "text" && !text.trim())} onClick={() => void runBatch()}>{running ? "正在批量添加水印…" : "批量添加水印"}</button>
            {running && runningBatchId ? <button type="button" className="hdde-secondary-action" onClick={async () => {
              try {
                const response = await fetch(`${API_BASE}/api/batch-watermark/batches/${encodeURIComponent(runningBatchId)}/control`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "cancel" }) });
                const body = await response.json();
                if (!response.ok) throw new Error(responseMessage(body, "取消请求未成功，请等待批次状态。"));
              } catch (reason) { setError(reason.message); }
            }}>取消未开始项</button> : null}
            {recoveryState === "loading" ? <p role="status">正在恢复批量水印结果…</p> : null}
            {error ? <p role="alert">{error}</p> : null}
            {result ? <div className="hdde-watermark-delivery-actions" data-testid="batch-watermark-delivery-actions"><button type="button" className="hdde-secondary-action" onClick={() => void openFolder()}>打开文件夹</button><button type="button" className="hdde-secondary-action" onClick={() => onNavigate?.("/outputs")}>进入输出中心</button></div> : null}
            <small className="hdde-watermark-protection">原图永不覆盖 · 输出自动防重名 · 仅执行局部 Overlay</small>
          </section>
        </aside>
      </div>
    </section>
  );
}
