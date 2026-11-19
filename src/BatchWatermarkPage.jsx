import React, { useEffect, useMemo, useRef, useState } from "react";
import { HddePageHeader } from "./HddeUI.jsx";
import WatermarkPresets from "./WatermarkPresets.jsx";
import { checkBatchOutput } from "./batchOutputPreflight.js";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const ACCEPTED_IMAGE = /\.(png|jpe?g)$/i;
const MAX_WATERMARK_BYTES = 50 * 1024 * 1024;
const MAX_WATERMARK_FILES = 100;
const POSITION_OPTIONS = Object.freeze([
  ["top-left", "左上", "↖"], ["top-center", "上中", "↑"], ["top-right", "右上", "↗"],
  ["middle-left", "左中", "←"], ["center", "居中", "◎"], ["middle-right", "右中", "→"],
  ["bottom-left", "左下", "↙"], ["bottom-center", "下中", "↓"], ["bottom-right", "右下", "↘"],
]);
const STATUS_LABELS = Object.freeze({ pending: "等待处理", processing: "处理中", completed: "已完成", failed: "失败", canceled: "已取消", unconfirmed: "结果未确认" });
const TERMINAL_ITEM_STATUSES = new Set(["completed", "failed", "canceled"]);
const BATCH_RESULT_STATUSES = Object.freeze(["FULL_SUCCESS", "PARTIAL_SUCCESS", "FAILED", "CANCELED"]);
const BATCH_ID_PATTERN = /^watermark_batch_[a-f0-9]{16}$/i;
const BATCH_STATUS_INTERVAL_MS = 300;
const BATCH_CONFIRMATION_TIMEOUT_MS = 60_000;
const BATCH_PRE_SUBMIT_REJECTIONS = new Set([
  "FORMAL_DIRECTORY_NOT_READY", "WATERMARK_OUTPUT_UNSAFE", "WATERMARK_RESULT_IDS_INVALID",
  "WATERMARK_BATCH_ENTRIES_INVALID", "WATERMARK_BATCH_SIZE_INVALID", "WATERMARK_SPEC_INVALID", "WATERMARK_LOGO_INVALID",
  "BATCH_DISK_SPACE_INSUFFICIENT", "BATCH_DISK_SPACE_UNAVAILABLE",
]);
const SCRUB_THRESHOLD_PX = 4;
const FONT_OPTIONS = Object.freeze([
  ["source_han_sans_cn_medium", "思源黑体 CN Medium", "hdde-watermark-font--sans-medium"],
  ["source_han_serif_cn_heavy", "思源宋体 CN Heavy", "hdde-watermark-font--serif-heavy"],
]);
const TEXT_PRESETS = Object.freeze(["仅供预览", "内部资料", "仅供内部使用", "请勿转载", "版权所有", "样稿", "DEMO", "未经授权禁止使用"]);

function watermarkInputIssue(name, size, logo = false) {
  if (!(logo ? /\.png$/i : ACCEPTED_IMAGE).test(name)) return logo ? "图片水印必须是透明 PNG。" : "仅支持 PNG、JPG、JPEG。";
  if (size <= 0) return "文件为空。";
  if (size > MAX_WATERMARK_BYTES) return "单个文件不得超过 50 MiB。";
  return "";
}

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
  return { id: crypto.randomUUID().replaceAll("-", ""), file, status: "pending", failureReason: "", outputName: "" };
}

function itemDisplayName(item) {
  return item?.file?.name || item?.fileName || "未命名图片";
}

export function matchBatchItems(items, result, batchId, useServerId = false) {
  const returned = result?.items;
  const lookupId = (item) => useServerId ? item.serverItemId : item.id;
  const byId = new Map((Array.isArray(returned) ? returned : []).map((item) => [useServerId ? item?.item_id : item?.client_item_id, item]));
  if (result?.batch_id !== batchId || returned?.length !== items.length || byId.size !== items.length ||
      items.some((item) => !lookupId(item) || !byId.has(lookupId(item)))) {
    throw new Error("返回的批量水印结果与提交的图片清单不一致，请在输出中心核对批次。");
  }
  return items.map((item) => {
    const outcome = byId.get(lookupId(item));
    if (!Object.hasOwn(STATUS_LABELS, outcome.status) || outcome.status === "unconfirmed") {
      throw new Error("批量水印返回了无法识别的图片状态。");
    }
    return {
      ...item,
      serverItemId: outcome.item_id,
      status: outcome.status,
      failureReason: outcome.failure_reason || "",
      outputName: outcome.output_file_name || "",
      outputResultId: outcome.result_id || "",
    };
  });
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
    serverItemId: item?.item_id,
    file: null,
    fileName: item?.file_name || item?.original_filename || item?.output_file_name || `第 ${index + 1} 张图片`,
    status: item?.status === "completed" ? "completed" : item?.status === "canceled" ? "canceled" : "failed",
    failureReason: item?.failure_reason || "",
    outputName: item?.output_file_name || "",
    outputResultId: item?.result_id || "",
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

export default function BatchWatermarkPage({ active = true, onNavigate, continueResultId = "", requestedBatchId = "" }) {
  const imageInputRef = useRef(null);
  const logoInputRef = useRef(null);
  const batchLocked = useRef(null);
  const outputCheck = useRef(null);
  const unconfirmedBatch = useRef(null);
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
  const [applyingPreset, setApplyingPreset] = useState(false);
  const [presetRevision, setPresetRevision] = useState(0);
  const [sourcePreview, setSourcePreview] = useState(null);
  const [watermarkPreview, setWatermarkPreview] = useState(null);
  const [running, setRunning] = useState(false);
  const [checkingOutput, setCheckingOutput] = useState(false);
  const [runningBatchId, setRunningBatchId] = useState("");
  const [recoveryAction, setRecoveryAction] = useState("");
  const [error, setError] = useState("");
  const [importIssues, setImportIssues] = useState([]);
  const [result, setResult] = useState(null);
  const [recoveryState, setRecoveryState] = useState(requestedBatchId ? "loading" : "idle");
  const [loadedResultId, setLoadedResultId] = useState("");
  const normalizedResultId = String(continueResultId || "").trim();
  const resultLoading = Boolean(normalizedResultId && !requestedBatchId && loadedResultId !== normalizedResultId);

  const activeIndex = Math.max(0, items.findIndex((item) => item.id === activeId));
  const activeItem = items[activeIndex] || null;
  const { id: previewItemId, file: previewFile, resultId: previewResultId, previewUrl: previewAssetUrl } = activeItem || {};
  const sourcePreviewUrl = sourcePreview?.id === activeItem?.id ? sourcePreview?.url : "";
  const hasRunnableItems = items.length > 0 && items.every((item) => item.file || item.resultId);
  const marginAvailability = getMarginAvailability(position, kind === "text" && tile);
  const spec = useMemo(() => ({
    kind, text, font_id: fontId, color, opacity, text_size: textSize, rotation, position,
    margin_x: marginX, margin_y: marginY, tile: kind === "text" && tile,
    image_width_percent: imageWidthPercent,
  }), [kind, text, fontId, color, opacity, textSize, rotation, position, marginX, marginY, tile, imageWidthPercent]);
  const canPreview = Boolean((previewFile || previewResultId) && (kind === "image" ? logoFile : text.trim()));
  const currentPreview = watermarkPreview?.id === previewItemId && watermarkPreview?.spec === spec && watermarkPreview?.logoFile === logoFile ? watermarkPreview : null;
  const previewState = currentPreview?.url ? "ready" : currentPreview?.error ? "error" : canPreview ? "loading" : "idle";

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
    const normalized = normalizedResultId;
    if (!normalized || requestedBatchId) return undefined;
    const controller = new AbortController();
    const loadResult = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/result-assets/${encodeURIComponent(normalized)}`, { cache: "no-store", signal: controller.signal });
        const body = await response.json().catch(() => ({}));
        if (!response.ok || !body?.data) throw new Error(responseMessage(body, "当前成品无法作为水印输入。"));
        if (controller.signal.aborted) return;
        const source = body.data;
        const name = source.file_name || "";
        const size = Number(source.size_bytes || 0);
        const issue = watermarkInputIssue(name, size);
        if (issue) throw new Error(`${name || "当前成品"}：${issue}`);
        const item = {
          id: crypto.randomUUID().replaceAll("-", ""),
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
        setItems((current) => current.some((entry) => entry.resultId === normalized) ? current : [item, ...current.filter((entry) => !entry.recovered)]);
        setResult(null);
        setRecoveryState("idle");
      } catch (reason) {
        if (!controller.signal.aborted) setError(reason.message || "当前成品无法作为水印输入。");
      } finally {
        if (!controller.signal.aborted) setLoadedResultId(normalized);
      }
    };
    void loadResult();
    return () => controller.abort();
  }, [normalizedResultId, requestedBatchId]);

  useEffect(() => {
    if (!previewFile && !previewAssetUrl) {
      setSourcePreview(null);
      return undefined;
    }
    if (previewAssetUrl) {
      setSourcePreview({ id: previewItemId, url: previewAssetUrl });
      return undefined;
    }
    const url = URL.createObjectURL(previewFile);
    setSourcePreview({ id: previewItemId, url });
    return () => URL.revokeObjectURL(url);
  }, [previewItemId, previewFile, previewAssetUrl]);

  useEffect(() => {
    if (!canPreview) {
      setWatermarkPreview(null);
      return undefined;
    }
    const controller = new AbortController();
    const identity = { id: previewItemId, spec, logoFile };
    const timer = window.setTimeout(async () => {
      const formData = new FormData();
      if (previewResultId) formData.append("result_id", previewResultId);
      else formData.append("file", previewFile, previewFile.name);
      formData.append("spec_json", JSON.stringify(spec));
      formData.append("fit_preview", "true");
      if (logoFile) formData.append("watermark_file", logoFile, logoFile.name);
      try {
        const response = await fetch(`${API_BASE}/api/batch-watermark/preview`, { method: "POST", body: formData, signal: controller.signal });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(responseMessage(body, "无法生成真实水印预览。"));
        }
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        const url = URL.createObjectURL(blob);
        setWatermarkPreview({ ...identity, url });
      } catch (reason) {
        if (controller.signal.aborted) return;
        setWatermarkPreview({ ...identity, error: reason.message || "无法生成真实水印预览。" });
      }
    }, 280);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [previewItemId, previewFile, previewResultId, canPreview, logoFile, spec]);

  useEffect(() => () => { if (watermarkPreview?.url) URL.revokeObjectURL(watermarkPreview.url); }, [watermarkPreview]);
  useEffect(() => () => {
    batchLocked.current?.abort();
    outputCheck.current?.abort();
  }, []);

  const submissionLocked = running || checkingOutput || Boolean(recoveryAction) || applyingPreset;
  const inputLocked = submissionLocked || resultLoading || recoveryState === "loading";

  const addImages = (fileList) => {
    if (batchLocked.current || outputCheck.current || unconfirmedBatch.current || inputLocked) return;
    const selected = Array.from(fileList || []);
    if (!selected.length) return;
    const issues = [];
    const valid = selected.filter((file) => {
      const reason = watermarkInputIssue(file.name, file.size);
      if (reason) issues.push({ name: file.name, reason });
      return !reason;
    });
    const alreadyAdded = items.filter((item) => !item.recovered).length;
    if (alreadyAdded + valid.length > MAX_WATERMARK_FILES) {
      const reason = `本次选图超过每批 ${MAX_WATERMARK_FILES} 张的上限，请分批添加。`;
      setImportIssues([...issues, ...valid.map((file) => ({ name: file.name, reason }))]);
      return;
    }
    setImportIssues(issues);
    if (!valid.length) return;
    const additions = valid.map(makeItem);
    const replacingRecoveredItems = items.some((item) => item.recovered);
    setItems((current) => [...current.filter((item) => !item.recovered), ...additions]);
    setActiveId((current) => replacingRecoveredItems ? additions[0].id : current || additions[0].id);
    setResult(null);
    setRecoveryState("idle");
    setError("");
  };

  const removeItem = (id) => {
    if (batchLocked.current || unconfirmedBatch.current || inputLocked) return;
    setItems((current) => current.filter((item) => item.id !== id));
    if (activeId === id) setActiveId("");
    setResult(null);
  };

  const selectLogo = (file) => {
    if (!file || batchLocked.current || outputCheck.current || unconfirmedBatch.current) return;
    const issue = watermarkInputIssue(file.name, file.size, true);
    if (issue) {
      setError(`${file.name}：${issue} 当前文件未加入。`);
      return;
    }
    setLogoFile(file);
    setError("");
    setResult(null);
  };

  const applyPreset = (saved, file, message = "") => {
    setKind(saved.kind);
    setOpacity(saved.opacity);
    setPosition(saved.position);
    setMarginX(saved.margin_x);
    setMarginY(saved.margin_y);
    setLogoFile(file);
    if (saved.kind === "image") {
      setImageWidthPercent(saved.image_width_percent);
    } else {
      setText(saved.text);
      setFontId(saved.font_id);
      setColor(saved.color);
      setTextSize(saved.text_size);
      setRotation(saved.rotation);
      setTile(saved.tile);
    }
    setPresetRevision((revision) => revision + 1);
    setError(message);
  };

  const trackBatch = async (operation, action = "submit") => {
    if (!operation || batchLocked.current) return;
    const { batchId, batchItems, submit, retryOf } = operation;
    const minimumRevision = retryOf ? (retryOf.retry_revision || 0) + 1 : 0;
    const matchSnapshot = (snapshot) => matchBatchItems(batchItems, snapshot, batchId, Boolean(retryOf));
    const controller = new AbortController();
    const isCurrent = () => batchLocked.current === controller && !controller.signal.aborted;
    const statusUrl = `${API_BASE}/api/batch-watermark/batches/${encodeURIComponent(batchId)}`;
    let lastConfirmedAt = Date.now();
    let pollTimer;
    controller.signal.addEventListener("abort", () => window.clearTimeout(pollTimer), { once: true });
    const stopTracking = () => {
      controller.abort();
      batchLocked.current = null;
      setRunning(false);
      setRunningBatchId("");
    };
    const finish = (snapshot, matched) => {
      if ((snapshot.retry_revision || 0) < minimumRevision) {
        throw new Error("返回的批量水印结果早于本次重试。");
      }
      if (matched.some((item) => !TERMINAL_ITEM_STATUSES.has(item.status))) {
        throw new Error("批量水印结果仍有未结束的图片。");
      }
      unconfirmedBatch.current = null;
      stopTracking();
      setItems(matched);
      setResult(snapshot);
      if (snapshot.failed) setError(`${snapshot.failed} 张图片处理失败，请查看文件列表中的真实原因。`);
    };
    const pause = (message, canResubmit = false) => {
      unconfirmedBatch.current = operation;
      stopTracking();
      setRecoveryAction(canResubmit ? "resubmit" : "query");
      setItems((current) => current.map((item) => TERMINAL_ITEM_STATUSES.has(item.status) ? item : { ...item, status: "unconfirmed" }));
      setError(message);
    };
    const pollStatus = async () => {
      const request = new AbortController();
      const abortRequest = () => request.abort();
      const timeout = window.setTimeout(abortRequest, 5000);
      controller.signal.addEventListener("abort", abortRequest, { once: true });
      try {
        const response = await fetch(statusUrl, { cache: "no-store", signal: request.signal });
        const body = await response.json();
        if (!isCurrent()) return;
        if (!response.ok) {
          if (action === "query" && !operation.confirmed && !retryOf &&
              response.status === 404 && body?.detail?.code === "WATERMARK_BATCH_NOT_FOUND") {
            pause("暂未查到原批次，提交结果仍未确认。可以再次查询，或用原图片和参数继续提交。", true);
            return;
          }
          throw new Error("暂时无法查询原批次。");
        }
        const snapshot = body?.data;
        const matched = matchSnapshot(snapshot);
        const terminal = BATCH_RESULT_STATUSES.includes(snapshot.batch_status);
        if ((snapshot.retry_revision || 0) < minimumRevision) {
          if (action === "query" && !operation.confirmed && terminal) {
            pause("尚未确认本次失败项重试。可以再次查询，或继续提交原重试。", true);
            return;
          }
          throw new Error("尚未读到本次重试的状态。");
        }
        if (terminal) {
          operation.confirmed = true;
          finish(snapshot, matched);
        } else if (snapshot.status === "pending" || snapshot.status === "processing") {
          operation.confirmed = true;
          lastConfirmedAt = Date.now();
          setRunningBatchId(batchId);
          setItems(matched);
        } else {
          throw new Error("批量水印返回了无法识别的批次状态。");
        }
      } catch {
        if (isCurrent() && (action === "query" || Date.now() - lastConfirmedAt >= BATCH_CONFIRMATION_TIMEOUT_MS)) {
          pause("暂时无法确认原批次状态，请再次查询。");
        }
      } finally {
        window.clearTimeout(timeout);
        controller.signal.removeEventListener("abort", abortRequest);
        if (isCurrent()) pollTimer = window.setTimeout(pollStatus, BATCH_STATUS_INTERVAL_MS);
      }
    };

    batchLocked.current = controller;
    setRunning(true);
    setRecoveryAction("");
    setError("");
    if (action === "submit") {
      setResult(null);
      setItems(batchItems);
    }
    if (action === "query") {
      await pollStatus();
      return;
    }
    setRunningBatchId(batchId);
    pollTimer = window.setTimeout(pollStatus, BATCH_STATUS_INTERVAL_MS);
    try {
      const response = await submit(statusUrl, controller.signal);
      const body = await response.json();
      if (!isCurrent()) return;
      if (!response.ok) {
        if (action === "submit" && !operation.confirmed && BATCH_PRE_SUBMIT_REJECTIONS.has(body?.detail?.code)) {
          stopTracking();
          setResult(retryOf || null);
          setError(responseMessage(body, "批量水印提交失败。"));
          return;
        }
        throw new Error("批量水印提交结果未确认。");
      }
      if (!BATCH_RESULT_STATUSES.includes(body?.data?.batch_status)) throw new Error("未收到完整的批次结果。");
      finish(body.data, matchSnapshot(body.data));
    } catch {
      if (isCurrent()) pause("批量水印提交结果未确认，请查询原批次状态。");
    }
  };

  const runBatch = async () => {
    if (!hasRunnableItems || batchLocked.current || outputCheck.current || unconfirmedBatch.current || inputLocked || (kind === "image" && !logoFile) || (kind === "text" && !text.trim())) return;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    outputCheck.current = controller;
    setCheckingOutput(true);
    setError("");
    try {
      await checkBatchOutput("batch-watermark", {
        source_bytes: items.reduce((sum, item) => sum + (item.file?.size ?? item.sizeBytes ?? 0), 0),
        logo_bytes: logoFile?.size || 0,
      }, controller.signal);
    } catch (reason) {
      setError(controller.signal.aborted ? "检查输出空间超时，请重试。" : reason.message || "无法检查批次输出空间，请重试。");
      return;
    } finally {
      window.clearTimeout(timeout);
      outputCheck.current = null;
      setCheckingOutput(false);
    }
    if (controller.signal.aborted) return;
    const batchItems = items.map((item) => ({ ...item, status: "pending", failureReason: "", outputName: "", outputResultId: "" }));
    const batchId = `watermark_batch_${crypto.randomUUID().replaceAll("-", "").slice(0, 16)}`;
    const formData = new FormData();
    formData.append("batch_id", batchId);
    formData.append("entries_json", JSON.stringify(batchItems.map((item) => (
      item.file ? { id: item.id } : { id: item.id, result_id: item.resultId, file_name: item.fileName }
    ))));
    for (const item of batchItems) {
      if (item.file) formData.append(`file_${item.id}`, item.file, item.file.name);
    }
    formData.append("spec_json", JSON.stringify(spec));
    if (logoFile) formData.append("watermark_file", logoFile, logoFile.name);
    await trackBatch({
      batchId, batchItems,
      submit: (_, signal) => fetch(`${API_BASE}/api/batch-watermark/batches`, { method: "POST", body: formData, signal }),
    });
  };

  const retryFailed = async () => {
    if (batchLocked.current || outputCheck.current || unconfirmedBatch.current || !result?.failed) return;
    await trackBatch({
      batchId: result.batch_id, batchItems: items, retryOf: result,
      submit: (statusUrl, signal) => fetch(`${statusUrl}/retry-failed`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ retry_revision: result.retry_revision || 0 }),
        signal,
      }),
    });
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

  const counts = { pending: 0, processing: 0, completed: 0, failed: 0, canceled: 0, unconfirmed: 0 };
  for (const item of items) counts[item.status]++;
  const total = items.length;
  const showBatchProgress = Boolean(running || result || recoveryAction);
  const showBatchStatus = showBatchProgress || recoveryState === "loading" || Boolean(error);
  const executionLayout = showBatchStatus ? "status" : "setup";
  const progress = total ? Math.round((counts.completed + counts.failed + counts.canceled) * 100 / total) : 0;

  const handleWatermarkTypeKeyDown = (event) => {
    if (submissionLocked || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const tabs = [...event.currentTarget.querySelectorAll('[role="tab"]')];
    const current = tabs.indexOf(event.target);
    if (current === -1) return;
    const offset = event.key === "ArrowLeft" ? -1 : 1;
    const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (current + offset + tabs.length) % tabs.length;
    event.preventDefault();
    tabs[next].click();
    tabs[next].focus();
  };

  return (
    <section className="hdde-watermark-page hdde-page-frame hdde-page-stack" data-testid="batch-watermark-page" hidden={!active} inert={!active ? "" : undefined}>
      <input ref={imageInputRef} data-testid="batch-watermark-file-input" type="file" multiple hidden accept=".png,.jpg,.jpeg,image/png,image/jpeg" disabled={inputLocked} onChange={(event) => { addImages(event.currentTarget.files); event.currentTarget.value = ""; }} />
      <input ref={logoInputRef} data-testid="batch-watermark-logo-input" type="file" hidden accept=".png,image/png" disabled={submissionLocked} onChange={(event) => { selectLogo(event.currentTarget.files?.[0]); event.currentTarget.value = ""; }} />
      <HddePageHeader
        title="批量水印"
        description="批量叠加文字或透明 PNG 水印，保留原图。"
        actions={items.length ? <button type="button" className="hdde-secondary-action" disabled={inputLocked} onClick={() => imageInputRef.current?.click()}>添加图片</button> : null}
      />

      <div className="hdde-watermark-workbench">
        <section className="hdde-watermark-preview" aria-label="真实水印预览">
          <header>
            <div><h2 title={activeItem ? itemDisplayName(activeItem) : undefined}>{activeItem ? itemDisplayName(activeItem) : "实时预览"}</h2></div>
            {items.length > 1 ? <div className="hdde-watermark-preview-pages" role="group" aria-label="切换预览图片">
              <button type="button" className="hdde-secondary-action" disabled={activeIndex === 0} onClick={() => setActiveId(items[activeIndex - 1].id)}>上一张</button>
              <span aria-live="polite">{activeIndex + 1} / {items.length}</span>
              <button type="button" className="hdde-secondary-action" disabled={activeIndex === items.length - 1} onClick={() => setActiveId(items[activeIndex + 1].id)}>下一张</button>
            </div> : null}
            {activeItem && previewState !== "loading" ? <span data-state={previewState}>{previewState === "ready" ? "水印预览" : previewState === "error" ? "预览不可用" : sourcePreviewUrl ? "原图" : "无预览"}</span> : null}
          </header>
          <div className="hdde-watermark-preview-stage" data-testid="batch-watermark-preview">
            {currentPreview?.error ? <div role="alert"><strong>预览不可用</strong><span>{currentPreview.error}</span></div> : currentPreview?.url ? <img src={currentPreview.url} alt={`${itemDisplayName(activeItem)}的真实水印效果`} /> : sourcePreviewUrl ? <img src={sourcePreviewUrl} alt={`${itemDisplayName(activeItem)}原图预览`} /> : (
              <div>
                {!items.length ? <button type="button" className="hdde-primary-action" disabled={inputLocked} onClick={() => imageInputRef.current?.click()}>添加图片</button> : null}
                <span>{activeItem?.recovered ? "如需预览历史批次，请重新添加原图。" : activeItem ? "暂无图片预览" : "支持批量选择 PNG、JPG 图片"}</span>
              </div>
            )}
            {previewState === "loading" ? <span className="hdde-watermark-preview-loading" role="status">生成真实预览中…</span> : null}
          </div>
          {activeItem ? <footer>
            <span>{STATUS_LABELS[activeItem.status]}{activeItem.outputName ? ` · ${activeItem.outputName}` : ""}{activeItem.failureReason ? ` · ${activeItem.failureReason}` : ""}</span>
            {!activeItem.recovered ? <button type="button" className="hdde-tertiary-action" disabled={inputLocked} onClick={() => removeItem(activeItem.id)}>移除当前图片</button> : null}
          </footer> : null}
        </section>

        <aside className="hdde-watermark-sidebar" aria-label="水印设置与执行" data-execution={executionLayout}>
          <div className="hdde-watermark-settings">
          <fieldset disabled={submissionLocked} style={{ display: "contents" }}>
          <WatermarkPresets active={active} spec={spec} logoFile={logoFile} onApply={applyPreset} setApplying={setApplyingPreset} />
          <div className="hdde-watermark-mode" role="tablist" aria-label="水印类型" onKeyDown={handleWatermarkTypeKeyDown}>
            <button type="button" role="tab" id="watermark-type-text" aria-controls="watermark-type-panel" aria-selected={kind === "text"} tabIndex={kind === "text" ? 0 : -1} onClick={() => setKind("text")}>文字水印</button>
            <button type="button" role="tab" id="watermark-type-image" aria-controls="watermark-type-panel" aria-selected={kind === "image"} tabIndex={kind === "image" ? 0 : -1} onClick={() => setKind("image")}>图片水印</button>
          </div>
          <div key={presetRevision} className="hdde-watermark-form" id="watermark-type-panel" role="tabpanel" aria-labelledby={`watermark-type-${kind}`}>
            <div className="hdde-watermark-appearance">
            {kind === "text" ? <>
              <TextPresetField value={text} onChange={setText} />
              <FontSelector value={fontId} onChange={setFontId} />
              <div className="hdde-watermark-parameter-grid">
                <ColorField value={color} onChange={setColor} />
                <ScrubbableNumericField label="透明度" value={opacity} min={1} max={100} suffix="%" onChange={setOpacity} testId="batch-watermark-opacity" />
                <ScrubbableNumericField label="大小" value={textSize} min={10} max={160} suffix="px" onChange={setTextSize} testId="batch-watermark-text-size" />
                <ScrubbableNumericField label="旋转角度" value={rotation} min={-180} max={180} suffix="°" onChange={setRotation} testId="batch-watermark-rotation" />
              </div>
            </> : <>
              <button type="button" className="hdde-watermark-logo-picker" onClick={() => logoInputRef.current?.click()}><strong>{logoFile?.name || "选择透明 PNG"}</strong><span>{logoFile ? formatBytes(logoFile.size) : "保留 Logo 的 Alpha 透明边缘"}</span></button>
              <div className="hdde-watermark-parameter-grid">
                <ScrubbableNumericField label="大小" value={imageWidthPercent} min={1} max={80} suffix="%" onChange={setImageWidthPercent} testId="batch-watermark-logo-size" />
                <ScrubbableNumericField label="透明度" value={opacity} min={1} max={100} suffix="%" onChange={setOpacity} testId="batch-watermark-opacity" />
              </div>
            </>}
            </div>
          <section className="hdde-watermark-placement" aria-labelledby="watermark-placement-title">
            <header>
              <h3 id="watermark-placement-title">位置与边距</h3>
              {kind === "text" ? <label className="hdde-watermark-switch">
                <input type="checkbox" checked={tile} onChange={(event) => setTile(event.target.checked)} aria-describedby="watermark-tile-note" />
                <strong>平铺文字</strong>
              </label> : null}
            </header>
            {kind === "text" ? <p className={tile ? "hdde-watermark-tile-note" : "sr-only"} id="watermark-tile-note">间距自动计算。</p> : null}
            {kind !== "text" || !tile ? <>
              <div className="hdde-watermark-placement-controls">
                <fieldset className="hdde-watermark-position">
                  <legend>九宫格位置</legend>
                  <div>{POSITION_OPTIONS.map(([value, label, arrow]) => (
                    <button key={value} type="button" title={label} aria-label={label} aria-pressed={position === value} onClick={() => setPosition(value)}>
                      <span aria-hidden="true">{arrow}</span>
                    </button>
                  ))}</div>
                </fieldset>
                <div className="hdde-watermark-margins">
                  <label data-disabled={!marginAvailability.horizontal}>
                    <span>水平边距{!marginAvailability.horizontal ? <small title="当前位置水平居中，不使用">停用</small> : null}</span>
                    <span className="hdde-watermark-margin-input">
                      <input data-testid="batch-watermark-margin-x" type="number" min="0" max="10000" value={marginX} disabled={!marginAvailability.horizontal}
                        onChange={(event) => setMarginX(Math.min(10000, Math.max(0, Number(event.target.value))))} />
                      <span className="hdde-watermark-margin-unit">px</span>
                    </span>
                  </label>
                  <label data-disabled={!marginAvailability.vertical}>
                    <span>垂直边距{!marginAvailability.vertical ? <small title="当前位置垂直居中，不使用">停用</small> : null}</span>
                    <span className="hdde-watermark-margin-input">
                      <input data-testid="batch-watermark-margin-y" type="number" min="0" max="10000" value={marginY} disabled={!marginAvailability.vertical}
                        onChange={(event) => setMarginY(Math.min(10000, Math.max(0, Number(event.target.value))))} />
                      <span className="hdde-watermark-margin-unit">px</span>
                    </span>
                  </label>
                </div>
              </div>
            </> : null}
          </section>
          </div>
          </fieldset>
          </div>
          <section className="hdde-watermark-execution" aria-label="水印执行与结果">
            <div className="hdde-watermark-run-summary">
              <div aria-live="polite">
                {showBatchProgress ? (
                  <><span>处理进度</span><strong>{counts.completed} 成功 / {counts.failed} 失败{counts.canceled ? ` / ${counts.canceled} 取消` : ""} / {total} 总计</strong></>
                ) : !resultLoading && recoveryState !== "loading" ? (
                  <span>{total ? `已添加 ${total} 张图片` : "请先添加图片"}</span>
                ) : null}
              </div>
              {running ? <span>{counts.processing} 处理中 / {counts.pending} 等待处理</span> : null}
              {showBatchProgress ? <progress aria-label="批量水印处理进度" max="100" value={progress}>{`${progress}%`}</progress> : null}
            </div>
            <div className="hdde-watermark-run-actions">
            <button data-testid="batch-watermark-run" type="button" className={result ? "hdde-secondary-action" : "hdde-primary-action"} disabled={!hasRunnableItems || inputLocked || (kind === "image" && !logoFile) || (kind === "text" && !text.trim())} onClick={() => void runBatch()}>{checkingOutput ? "正在检查输出空间…" : running ? "正在确认或处理批次…" : "批量添加水印"}</button>
            {recoveryAction ? <button type="button" className="hdde-secondary-action" onClick={() => void trackBatch(unconfirmedBatch.current, "query")}>查询批次状态</button> : null}
            {recoveryAction === "resubmit" ? <button type="button" className="hdde-secondary-action" onClick={() => void trackBatch(unconfirmedBatch.current, "resubmit")}>继续提交原批次</button> : null}
            {running && runningBatchId ? <button type="button" className="hdde-secondary-action" onClick={async () => {
              const activeBatch = batchLocked.current;
              try {
                const response = await fetch(`${API_BASE}/api/batch-watermark/batches/${encodeURIComponent(runningBatchId)}/control`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "cancel" }) });
                const body = await response.json();
                if (!response.ok) throw new Error(responseMessage(body, "取消请求未成功，请等待批次状态。"));
              } catch (reason) { if (batchLocked.current === activeBatch) setError(reason.message); }
            }}>取消未开始项</button> : null}
            {result?.failed ? <button type="button" className={counts.completed ? "hdde-secondary-action" : "hdde-primary-action"} disabled={checkingOutput} onClick={() => void retryFailed()}>仅重试失败项</button> : null}
            {result ? <div className="hdde-watermark-delivery-actions" data-testid="batch-watermark-delivery-actions"><button type="button" className="hdde-secondary-action" onClick={() => void openFolder()}>打开文件夹</button><button type="button" className={counts.completed ? "hdde-primary-action" : "hdde-secondary-action"} onClick={() => onNavigate?.(`/outputs?batch_id=${encodeURIComponent(result.batch_id)}`)}>进入输出中心</button></div> : null}
            </div>
            {recoveryState === "loading" ? <p role="status">正在恢复批量水印结果…</p> : null}
            {importIssues.length ? <details className="hdde-watermark-import-issues" open={importIssues.length <= 3}>
              <summary>{importIssues.length} 个文件未加入</summary>
              <ul>{importIssues.map(({ name, reason }, index) => <li key={`${index}:${name}`}>{name}：{reason}</li>)}</ul>
            </details> : null}
            {error ? <p role="alert">{error}</p> : null}
          </section>
        </aside>
      </div>
    </section>
  );
}
