import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAppTheme } from "./AppShell.jsx";
import HddeIcon from "./HddeIcon.jsx";
import UnifiedFeedback from "./UnifiedFeedback.jsx";
import {
  fitImageView,
  hitTestEditableRectangles,
  imageToScreen,
  moveSelectionRect,
  normalizedRect,
  pointInImage,
  resizeSelectionRect,
  screenToImage,
  sourcePixelMovedRect,
  sourcePixelRect,
  zoomViewAt,
} from "./localRetouchGeometry.js";
import {
  createRectangleRegion,
  createStrokeRegion,
  editableRectangles,
  latestStrokeRegion,
  removeRepairRegion,
  repairRegionsToMaskOperations,
  replaceRepairRegion,
} from "./localRetouchRegions.js";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const TOOLS = [
  { key: "brush", label: "画笔", icon: "brush" },
  { key: "rectangle", label: "矩形", icon: "rectangle" },
  { key: "erase", label: "擦除", icon: "erase" },
  { key: "pan", label: "拖动", icon: "pan" },
];
const MIN_SELECTION_SCREEN_SIZE = 12;
const SELECTION_HANDLE_HIT_SIZE = 16;
const SELECTION_HANDLE_DRAW_SIZE = 9;
const SELECTION_BORDER_WIDTH = 0.25;
const ACTIVE_SELECTION_COLOR = "#2F8F83";
const INACTIVE_SELECTION_COLOR = "rgba(47, 143, 131, 0.58)";
const SELECTION_FILL_COLOR = "rgba(47, 143, 131, 0.18)";
const SELECTION_HANDLE_FILL = "#FFFFFF";
const SELECTION_HANDLE_STROKE = "#2F8F83";

const SELECTION_CURSORS = {
  move: "move",
  top: "ns-resize",
  bottom: "ns-resize",
  left: "ew-resize",
  right: "ew-resize",
  "top-left": "nwse-resize",
  "bottom-right": "nwse-resize",
  "top-right": "nesw-resize",
  "bottom-left": "nesw-resize",
};

function sameRect(first, second) {
  return Boolean(first && second)
    && first.x === second.x
    && first.y === second.y
    && first.width === second.width
    && first.height === second.height;
}

function drawSelectionFrame(context, selection, view, active, showHandles) {
  const start = imageToScreen({ x: selection.x, y: selection.y }, view);
  const end = imageToScreen({ x: selection.x + selection.width, y: selection.y + selection.height }, view);
  const width = end.x - start.x;
  const height = end.y - start.y;
  const halfHandle = SELECTION_HANDLE_DRAW_SIZE / 2;
  const handles = [
    [start.x, start.y],
    [start.x + width / 2, start.y],
    [end.x, start.y],
    [start.x, start.y + height / 2],
    [end.x, start.y + height / 2],
    [start.x, end.y],
    [start.x + width / 2, end.y],
    [end.x, end.y],
  ];
  context.save();
  context.strokeStyle = active ? ACTIVE_SELECTION_COLOR : INACTIVE_SELECTION_COLOR;
  context.lineWidth = SELECTION_BORDER_WIDTH;
  context.strokeRect(start.x, start.y, width, height);
  if (!showHandles) {
    context.restore();
    return;
  }
  context.fillStyle = SELECTION_HANDLE_FILL;
  context.strokeStyle = SELECTION_HANDLE_STROKE;
  context.lineWidth = 2;
  handles.forEach(([x, y]) => {
    context.fillRect(x - halfHandle, y - halfHandle, SELECTION_HANDLE_DRAW_SIZE, SELECTION_HANDLE_DRAW_SIZE);
    context.strokeRect(x - halfHandle, y - halfHandle, SELECTION_HANDLE_DRAW_SIZE, SELECTION_HANDLE_DRAW_SIZE);
  });
  context.restore();
}

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
  repairRegionsToMaskOperations([...operations, ...(draft ? [draft] : [])])
    .forEach((operation) => drawOperation(context, operation));
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

export default function LocalRetouchPage({
  onBack,
  onOpenOutputCenter,
  onResultReady,
  onResumeReady,
  onResumeAvailabilityChange,
  continueResultId = "",
  resumeResultId = "",
  resumeSessionId = "",
}) {
  const { resolvedTheme } = useAppTheme();
  const fileInputRef = useRef(null);
  const fileDragDepthRef = useRef(0);
  const canvasRef = useRef(null);
  const canvasWrapRef = useRef(null);
  const sourceImageRef = useRef(null);
  const compareSourceImageRef = useRef(null);
  const resultImageRef = useRef(null);
  const viewRef = useRef({ scale: 1, offsetX: 0, offsetY: 0 });
  const pointerRef = useRef(null);
  const regionSequenceRef = useRef(0);
  const maskRevisionRef = useRef(0);
  const workspaceActionRef = useRef(false);
  const handledContinueResultRef = useRef("");
  const continueIntakeRef = useRef({ resultId: "", promise: null });
  const handledResumeResultRef = useRef("");
  const [capabilities, setCapabilities] = useState(null);
  const [session, setSession] = useState(null);
  const [sourceImage, setSourceImage] = useState(null);
  const [compareSourceImage, setCompareSourceImage] = useState(null);
  const [resultImage, setResultImage] = useState(null);
  const [repairRegions, setRepairRegions] = useState([]);
  const [undoStack, setUndoStack] = useState([]);
  const [redoStack, setRedoStack] = useState([]);
  const [draft, setDraft] = useState(null);
  const [activeRegionId, setActiveRegionId] = useState(null);
  const [selectionDraft, setSelectionDraft] = useState(null);
  const [selectionHover, setSelectionHover] = useState(null);
  const [tool, setTool] = useState("rectangle");
  const [rectangleCreateArmed, setRectangleCreateArmed] = useState(false);
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
  const [fileDragActive, setFileDragActive] = useState(false);

  useEffect(() => {
    requestJson("/api/local-retouch/capabilities")
      .then((payload) => setCapabilities(payload.data))
      .catch((reason) => setError(reason.message));
  }, []);

  useEffect(() => {
    const taskId = saved?.task_id || "";
    const resultId = saved?.result_id || "";
    const sessionId = session?.session_id || "";
    onResumeAvailabilityChange?.(
      taskId && resultId && sessionId ? { taskId, resultId, sessionId } : null,
    );
  }, [onResumeAvailabilityChange, saved?.result_id, saved?.task_id, session?.session_id]);

  useEffect(() => {
    if (!continueResultId || resumeResultId || handledContinueResultRef.current === continueResultId) return undefined;
    let active = true;
    setBusy("intake");
    setError("");
    setNotice("正在从已有成品建立新的本地工作副本…");
    if (continueIntakeRef.current.resultId !== continueResultId || !continueIntakeRef.current.promise) {
      continueIntakeRef.current = {
        resultId: continueResultId,
        promise: requestJson("/api/local-retouch/intake-result", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ result_id: continueResultId }),
        }).then(async (payload) => ({
          nextSession: payload.data,
          image: await loadCanvasImage(apiUrl(`${payload.data.working_source_url || payload.data.source_url}?v=${Date.now()}`)),
        })),
      };
    }
    continueIntakeRef.current.promise
      .then(({ nextSession, image }) => {
        if (!active) return;
        handledContinueResultRef.current = continueResultId;
        setSession(nextSession);
        setSourceImage(image);
        setCompareSourceImage(null);
        setResult(null);
        setResultImage(null);
        setRepairRegions([]);
        setUndoStack([]);
        setRedoStack([]);
        setDraft(null);
        setActiveRegionId(null);
        setSelectionDraft(null);
        setSelectionHover(null);
        setConfirmed(false);
        setSaved(null);
        setDisplayMode("edit");
        maskRevisionRef.current = 0;
        regionSequenceRef.current = 0;
        setNotice("已有成品已成为新的合法输入。请标记本轮需要修整的小范围区域。");
      })
      .catch((reason) => {
        if (!active) return;
        setError(reason.message);
        setNotice("");
      })
      .finally(() => active && setBusy(""));
    return () => { active = false; };
  }, [continueResultId, resumeResultId]);

  useEffect(() => {
    if (!resumeResultId || handledResumeResultRef.current === resumeResultId) return undefined;
    if (!resumeSessionId) {
      setError("当前正式结果没有有效的后端恢复资格，请重新处理。");
      return undefined;
    }
    let active = true;
    workspaceActionRef.current = true;
    setBusy("resume");
    setError("");
    setNotice("正在恢复当前修整上下文…");
    requestJson(`/api/local-retouch/sessions/${resumeSessionId}/resume-adjustment`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ result_id: resumeResultId }),
    })
      .then(async (payload) => {
        const prepared = payload.data;
        const cacheKey = Date.now();
        const [image, originalImage] = await Promise.all([
          loadCanvasImage(apiUrl(`${prepared.working_source_url || prepared.result_url}?v=${cacheKey}`)),
          loadCanvasImage(apiUrl(`${prepared.source_url}?v=${cacheKey}`)),
        ]);
        if (!active) return;
        const commitResume = () => requestJson(`/api/local-retouch/sessions/${resumeSessionId}/resume-adjustment/commit`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ result_id: resumeResultId }),
        });
        let committedPayload;
        try {
          committedPayload = await commitResume();
        } catch {
          if (!active) return;
          committedPayload = await commitResume();
        }
        if (!active) return;
        const next = committedPayload.data;
        handledResumeResultRef.current = resumeResultId;
        setSession(next);
        setSourceImage(image);
        setCompareSourceImage(originalImage);
        setResult(next);
        setResultImage(image);
        setRepairRegions([]);
        setUndoStack([]);
        setRedoStack([]);
        setDraft(null);
        setActiveRegionId(null);
        setSelectionDraft(null);
        setSelectionHover(null);
        setConfirmed(false);
        setSaved(null);
        setDisplayMode("edit");
        setNotice("已回到当前修整结果，可继续标记并处理。");
        onResumeReady?.(next);
      })
      .catch((reason) => {
        if (!active) return;
        handledResumeResultRef.current = "";
        setError(reason.message);
        setNotice("");
      })
      .finally(() => {
        if (!active) return;
        workspaceActionRef.current = false;
        setBusy("");
      });
    return () => {
      active = false;
    };
  }, [onResumeReady, resumeResultId, resumeSessionId]);

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
  const rectangles = useMemo(
    () => editableRectangles(repairRegions, activeRegionId),
    [activeRegionId, repairRegions],
  );
  const activeRectangle = useMemo(
    () => rectangles.find((rectangle) => rectangle.active) || null,
    [rectangles],
  );
  const strokeCount = useMemo(
    () => repairRegions.filter((region) => region.type === "stroke").length,
    [repairRegions],
  );

  const nextRegionIdentity = () => {
    regionSequenceRef.current += 1;
    return { id: `repair-region-${regionSequenceRef.current}`, order: regionSequenceRef.current };
  };

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
    compareSourceImageRef.current = compareSourceImage;
  }, [compareSourceImage]);
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
    context.fillStyle = window.getComputedStyle(canvas).color || "#080c12";
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
      drawImage(compareSourceImageRef.current || source);
      context.restore();
      const divider = width * (comparePosition / 100);
      context.fillStyle = "#ffffff";
      context.fillRect(divider - 1, 0, 2, height);
      context.fillStyle = "rgba(9, 13, 20, 0.82)";
      context.fillRect(12, 12, 56, 28);
      context.fillRect(width - 68, 12, 56, 28);
      context.fillStyle = "#ffffff";
      context.font = "600 13px Microsoft YaHei UI";
      context.fillText("处理前", 20, 31);
      context.fillText("当前", width - 54, 31);
    } else {
      drawImage(source);
      const visibleRegions = selectionDraft
        ? (repairRegions.some((region) => region.id === selectionDraft.id)
          ? replaceRepairRegion(repairRegions, selectionDraft)
          : [...repairRegions, selectionDraft])
        : repairRegions;
      const visibleRectangles = editableRectangles(
        visibleRegions,
        selectionDraft?.id || activeRegionId,
      );
      const mask = renderRetouchMask(
        session.width,
        session.height,
        visibleRegions,
        draft,
      );
      const overlay = document.createElement("canvas");
      overlay.width = session.width;
      overlay.height = session.height;
      const overlayContext = overlay.getContext("2d");
      overlayContext.drawImage(mask, 0, 0);
      overlayContext.globalCompositeOperation = "source-in";
      overlayContext.fillStyle = SELECTION_FILL_COLOR;
      overlayContext.fillRect(0, 0, overlay.width, overlay.height);
      drawImage(overlay);
      visibleRectangles.forEach((rectangle) => drawSelectionFrame(
        context,
        rectangle,
        currentView,
        rectangle.active,
        rectangle.active && tool === "rectangle",
      ));
    }
  }, [activeRegionId, canvasSize, comparePosition, displayMode, draft, repairRegions, resolvedTheme, selectionDraft, session, tool]);

  useEffect(() => {
    draw();
  }, [draw, view]);

  const invalidateResult = useCallback(() => {
    maskRevisionRef.current += 1;
    setConfirmed(false);
    setSaved(null);
    setDisplayMode("edit");
    setNotice("选区已更新，请重新处理后查看结果。");
  }, []);

  const commitRepairRegions = useCallback((nextRegions, nextActiveRegionId = activeRegionId) => {
    setUndoStack((current) => [...current, { regions: repairRegions, activeRegionId }]);
    setRepairRegions(nextRegions);
    setActiveRegionId(nextActiveRegionId);
    setRedoStack([]);
    invalidateResult();
  }, [activeRegionId, invalidateResult, repairRegions]);

  const resetFileDragState = () => {
    fileDragDepthRef.current = 0;
    setFileDragActive(false);
  };

  const intakeFile = async (file) => {
    if (!file || busy) return;
    resetFileDragState();
    setBusy("intake");
    setError("");
    setNotice("正在读取图片并建立本地工作副本…");
    const form = new FormData();
    form.append("file", file);
    try {
      const payload = await requestJson("/api/local-retouch/intake", { method: "POST", body: form });
      const nextSession = payload.data;
      const image = await loadCanvasImage(apiUrl(`${nextSession.working_source_url || nextSession.source_url}?v=${Date.now()}`));
      setSession(nextSession);
      setSourceImage(image);
      setCompareSourceImage(null);
      setResult(null);
      setResultImage(null);
      setRepairRegions([]);
      setUndoStack([]);
      setRedoStack([]);
      setDraft(null);
      setActiveRegionId(null);
      setSelectionDraft(null);
      setSelectionHover(null);
      setConfirmed(false);
      setSaved(null);
      setDisplayMode("edit");
      maskRevisionRef.current = 0;
      regionSequenceRef.current = 0;
      setNotice("图片已导入。请用画笔或矩形标记需要修整的小范围区域。");
    } catch (reason) {
      setError(reason.message);
      setNotice("");
    } finally {
      setBusy("");
    }
  };

  const chooseFile = (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) void intakeFile(file);
  };

  const handleFileDragEnter = (event) => {
    if (!Array.from(event.dataTransfer?.types || []).includes("Files")) return;
    event.preventDefault();
    event.stopPropagation();
    if (busy) {
      event.dataTransfer.dropEffect = "none";
      return;
    }
    fileDragDepthRef.current += 1;
    setFileDragActive(true);
  };

  const handleFileDragOver = (event) => {
    if (!Array.from(event.dataTransfer?.types || []).includes("Files")) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = busy ? "none" : "copy";
    if (!busy) setFileDragActive(true);
  };

  const handleFileDragLeave = (event) => {
    if (!fileDragActive) return;
    event.preventDefault();
    event.stopPropagation();
    fileDragDepthRef.current = Math.max(0, fileDragDepthRef.current - 1);
    if (!fileDragDepthRef.current) setFileDragActive(false);
  };

  const handleFileDrop = (event) => {
    const files = Array.from(event.dataTransfer?.files || []);
    if (!files.length && !Array.from(event.dataTransfer?.types || []).includes("Files")) return;
    event.preventDefault();
    event.stopPropagation();
    resetFileDragState();
    if (busy) return;
    if (files.length !== 1) {
      setError(files.length > 1 ? "当前仅支持单张图片" : "未读取到图片文件，请重新拖入。");
      setNotice("");
      return;
    }
    void intakeFile(files[0]);
  };

  const canvasPoint = (event) => {
    const rect = canvasRef.current.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };

  const cancelPointerInteraction = useCallback(() => {
    pointerRef.current = null;
    setDraft(null);
    setSelectionDraft(null);
    setSelectionHover(null);
  }, []);

  useEffect(() => {
    window.addEventListener("blur", cancelPointerInteraction);
    return () => window.removeEventListener("blur", cancelPointerInteraction);
  }, [cancelPointerInteraction]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !session) return undefined;
    const handleWheel = (event) => {
      event.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const point = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      updateView(zoomViewAt(
        viewRef.current,
        point,
        viewRef.current.scale * (event.deltaY > 0 ? 0.9 : 1.1),
      ));
    };
    canvas.addEventListener("wheel", handleWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", handleWheel);
  }, [session, updateView]);

  const handlePointerDown = (event) => {
    if (!session || busy || displayMode === "compare") return;
    const screen = canvasPoint(event);
    if (tool === "pan" || event.button === 1 || event.altKey) {
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      pointerRef.current = { type: "pan", screen, view: { ...viewRef.current } };
      return;
    }
    if (event.button !== 0) return;
    const rawImage = screenToImage(screen, viewRef.current, imageSize, false);
    if (tool === "rectangle") {
      const hit = hitTestEditableRectangles(
        screen,
        rectangles,
        activeRegionId,
        viewRef.current,
        SELECTION_HANDLE_HIT_SIZE,
      );
      if (hit && !rectangleCreateArmed) {
        const selection = rectangles.find((rectangle) => rectangle.id === hit.regionId);
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        const image = screenToImage(screen, viewRef.current, imageSize);
        pointerRef.current = {
          type: hit.handle === "move" ? "selection-move" : "selection-resize",
          handle: hit.handle,
          start: image,
          selection: { ...selection },
        };
        setActiveRegionId(selection.id);
        setSelectionDraft(selection);
        setSelectionHover(hit.handle);
        return;
      }
      if (!pointInImage(rawImage, imageSize)) return;
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      const identity = nextRegionIdentity();
      pointerRef.current = {
        type: "selection-create",
        start: rawImage,
        fallbackRegionId: rectangleCreateArmed ? hit?.regionId || null : null,
        ...identity,
      };
      setRectangleCreateArmed(false);
      setSelectionDraft(createRectangleRegion(identity.id, identity.order, {
        x: rawImage.x, y: rawImage.y, width: 0, height: 0,
      }));
    } else {
      if (!pointInImage(rawImage, imageSize)) return;
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      const image = screenToImage(screen, viewRef.current, imageSize);
      const identity = nextRegionIdentity();
      const operation = createStrokeRegion(
        identity.id,
        identity.order,
        [image],
        brushSize,
        tool === "erase" ? "erase" : "paint",
      );
      pointerRef.current = operation;
      setDraft(operation);
    }
  };

  const handlePointerMove = (event) => {
    const pointer = pointerRef.current;
    const screen = canvasPoint(event);
    if (!pointer || !session) {
      const hit = tool === "rectangle" && !rectangleCreateArmed
        ? hitTestEditableRectangles(screen, rectangles, activeRegionId, viewRef.current, SELECTION_HANDLE_HIT_SIZE)
        : null;
      setSelectionHover(hit?.handle || null);
      return;
    }
    if (pointer.type === "pan") {
      updateView({
        ...pointer.view,
        offsetX: pointer.view.offsetX + screen.x - pointer.screen.x,
        offsetY: pointer.view.offsetY + screen.y - pointer.screen.y,
      });
      return;
    }
    const image = screenToImage(screen, viewRef.current, imageSize);
    if (pointer.type === "selection-create") {
      setSelectionDraft(createRectangleRegion(
        pointer.id,
        pointer.order,
        normalizedRect(pointer.start, image, imageSize),
      ));
    } else if (pointer.type === "selection-move") {
      setSelectionDraft(moveSelectionRect(
        pointer.selection,
        { x: image.x - pointer.start.x, y: image.y - pointer.start.y },
        imageSize,
      ));
    } else if (pointer.type === "selection-resize") {
      setSelectionDraft(createRectangleRegion(
        pointer.selection.id,
        pointer.selection.order,
        resizeSelectionRect(
          pointer.selection,
          pointer.handle,
          image,
          imageSize,
          {
            width: MIN_SELECTION_SCREEN_SIZE / viewRef.current.scale,
            height: MIN_SELECTION_SCREEN_SIZE / viewRef.current.scale,
          },
        ),
      ));
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
    setSelectionDraft(null);
    setSelectionHover(null);
    if (!pointer || pointer.type === "pan" || !session) return;
    const screen = canvasPoint(event);
    const image = screenToImage(screen, viewRef.current, imageSize);
    if (pointer.type === "selection-create") {
      const next = normalizedRect(pointer.start, image, imageSize);
      if (next.width * viewRef.current.scale < MIN_SELECTION_SCREEN_SIZE
        || next.height * viewRef.current.scale < MIN_SELECTION_SCREEN_SIZE) {
        if (pointer.fallbackRegionId) setActiveRegionId(pointer.fallbackRegionId);
        return;
      }
      const committed = sourcePixelRect(next, imageSize);
      const region = createRectangleRegion(pointer.id, pointer.order, committed);
      commitRepairRegions([...repairRegions, region], region.id);
      return;
    }
    if (pointer.type === "selection-move" || pointer.type === "selection-resize") {
      const minimumSize = {
        width: MIN_SELECTION_SCREEN_SIZE / viewRef.current.scale,
        height: MIN_SELECTION_SCREEN_SIZE / viewRef.current.scale,
      };
      const next = pointer.type === "selection-move"
        ? moveSelectionRect(
          pointer.selection,
          { x: image.x - pointer.start.x, y: image.y - pointer.start.y },
          imageSize,
        )
        : resizeSelectionRect(pointer.selection, pointer.handle, image, imageSize, minimumSize);
      const committed = pointer.type === "selection-move"
        ? sourcePixelMovedRect(next, imageSize)
        : sourcePixelRect(next, imageSize);
      const current = repairRegions.find((region) => region.id === pointer.selection.id);
      if (!sameRect(committed, current)) {
        const region = createRectangleRegion(pointer.selection.id, pointer.selection.order, committed);
        commitRepairRegions(replaceRepairRegion(repairRegions, region), region.id);
      }
      return;
    }
    const operation = { ...pointer, points: [...pointer.points, image] };
    commitRepairRegions([...repairRegions, operation]);
  };

  const zoomBy = (factor) => {
    const current = viewRef.current;
    updateView(zoomViewAt(current, { x: canvasSize.width / 2, y: canvasSize.height / 2 }, current.scale * factor));
  };

  const undo = () => {
    if (!undoStack.length || busy) return;
    const previous = undoStack[undoStack.length - 1];
    setUndoStack(undoStack.slice(0, -1));
    setRedoStack((current) => [...current, { regions: repairRegions, activeRegionId }]);
    setRepairRegions(previous.regions);
    setActiveRegionId(previous.activeRegionId);
    invalidateResult();
  };

  const redo = () => {
    if (!redoStack.length || busy) return;
    const next = redoStack[redoStack.length - 1];
    setRedoStack(redoStack.slice(0, -1));
    setUndoStack((current) => [...current, { regions: repairRegions, activeRegionId }]);
    setRepairRegions(next.regions);
    setActiveRegionId(next.activeRegionId);
    invalidateResult();
  };

  const clearMask = () => {
    if (!repairRegions.length || busy) return;
    commitRepairRegions([], null);
    setSelectionDraft(null);
    setSelectionHover(null);
  };

  const deleteSelection = () => {
    if (!activeRectangle || busy) return;
    commitRepairRegions(removeRepairRegion(repairRegions, activeRectangle.id), null);
    setSelectionDraft(null);
    setSelectionHover(null);
    setNotice("当前矩形已删除，其他修复区域保持不变。");
  };

  const deleteLastStroke = () => {
    const stroke = latestStrokeRegion(repairRegions);
    if (!stroke || busy) return;
    commitRepairRegions(removeRepairRegion(repairRegions, stroke.id));
    setNotice("上一笔已删除，可撤销恢复。");
  };

  const processMask = async () => {
    if (!session || busy || workspaceActionRef.current) return;
    const mask = renderRetouchMask(
      session.width,
      session.height,
      repairRegions,
    );
    if (!maskHasPixels(mask)) {
      setError("请先标记需要修整的区域。");
      return;
    }
    const revision = Math.max(1, maskRevisionRef.current);
    workspaceActionRef.current = true;
    setBusy("process");
    setError("");
    setNotice("正在使用本地修整引擎处理当前选区，请稍候…");
    const previousWorkingImage = sourceImageRef.current;
    try {
      const payload = await requestJson(`/api/local-retouch/sessions/${session.session_id}/process`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mask_png_base64: mask.toDataURL("image/png"), mask_revision: revision }),
      });
      const next = payload.data;
      const image = await loadCanvasImage(apiUrl(`${next.result_url}?v=${Date.now()}`));
      setSession(next);
      setCompareSourceImage(previousWorkingImage);
      setSourceImage(image);
      setResult(next);
      setResultImage(image);
      setRepairRegions([]);
      setUndoStack([]);
      setRedoStack([]);
      setDraft(null);
      setActiveRegionId(null);
      setSelectionDraft(null);
      setSelectionHover(null);
      setConfirmed(false);
      setSaved(null);
      setDisplayMode("edit");
      setNotice("修整完成，可继续处理其他瑕疵");
    } catch (reason) {
      setError("修整未完成，当前结果已保留");
      setNotice("");
    } finally {
      workspaceActionRef.current = false;
      setBusy("");
    }
  };

  const backToPreviousResult = async () => {
    if (!session?.can_back_to_previous || busy || saved || workspaceActionRef.current) return;
    workspaceActionRef.current = true;
    setBusy("back");
    setError("");
    setNotice("正在恢复上一稳定修整结果…");
    try {
      const payload = await requestJson(`/api/local-retouch/sessions/${session.session_id}/back-to-previous`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const next = payload.data;
      const targetRevision = Math.max(0, Number(next.working_revision) || 0);
      const targetImageUrl = targetRevision === 0 ? next.source_url : (next.result_url || next.working_source_url);
      const image = await loadCanvasImage(apiUrl(`${targetImageUrl}?v=${Date.now()}`));
      let comparisonImage = null;
      if (next.previous_result_url) {
        try {
          comparisonImage = await loadCanvasImage(apiUrl(`${next.previous_result_url}?v=${Date.now()}`));
        } catch {
          comparisonImage = null;
        }
      }
      setSession(next);
      setSourceImage(image);
      setCompareSourceImage(comparisonImage);
      setResult(targetRevision > 0 ? next : null);
      setResultImage(targetRevision > 0 ? image : null);
      setRepairRegions([]);
      setUndoStack([]);
      setRedoStack([]);
      setDraft(null);
      setActiveRegionId(null);
      setSelectionDraft(null);
      setSelectionHover(null);
      setConfirmed(false);
      setSaved(null);
      setDisplayMode("edit");
      maskRevisionRef.current += 1;
      setNotice(targetRevision === 0 ? "已回到原图，可重新选择需要修整的区域" : "已回到上一修整结果");
    } catch (reason) {
      setError(reason.message);
      setNotice("");
    } finally {
      workspaceActionRef.current = false;
      setBusy("");
    }
  };

  const continueEditing = () => {
    if (!session || busy || saved) return;
    setDisplayMode("edit");
    canvasRef.current?.focus({ preventScroll: true });
  };

  const confirmAndSaveResult = async () => {
    if (!result || repairRegions.length || busy || saved) return;
    setBusy("save");
    setError("");
    try {
      if (!confirmed) {
        const confirmedPayload = await requestJson(`/api/local-retouch/sessions/${session.session_id}/confirm`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mask_revision: result.mask_revision }),
        });
        setConfirmed(true);
        setResult(confirmedPayload.data);
      }
      const payload = await requestJson(`/api/local-retouch/sessions/${session.session_id}/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const completed = payload.data;
      if (!completed?.task_id || !completed?.result_id) {
        throw new Error("正式结果登记未返回完整标识，未进入处理结果页。");
      }
      setSession(completed);
      setResult(completed);
      setSaved(completed);
      setNotice("当前结果已保存");
      onResultReady?.({
        taskId: completed.task_id,
        resultId: completed.result_id,
        sessionId: completed.session_id,
      });
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy("");
    }
  };

  const canProcess = Boolean(session && repairRegions.length && !busy && capabilities?.available);
  const editDepth = Math.max(0, Number(session?.working_revision) || 0);
  const canConfirmAndSave = Boolean(result && !repairRegions.length && !busy && !saved);
  const canvasCursor = tool === "rectangle"
    ? (rectangleCreateArmed ? "crosshair" : (SELECTION_CURSORS[selectionHover] || "crosshair"))
    : undefined;

  return (
    <section className="hdde-retouch-workspace" data-testid="retouch-workspace" aria-labelledby="retouch-title">
      <input ref={fileInputRef} type="file" accept="image/png,image/jpeg" hidden onChange={chooseFile} data-testid="retouch-file-input" />
      <header className="hdde-retouch-workspace__topbar">
        <div className="hdde-retouch-workspace__identity">
          <button type="button" className="hdde-retouch-back" onClick={onBack} data-testid="retouch-back">
            <HddeIcon name="back" size={18} />
            <span>返回</span>
          </button>
          <span className="hdde-retouch-workspace__divider" aria-hidden="true" />
          <div>
            <h1 id="retouch-title">瑕疵修复</h1>
            <span>{session ? `${session.file_name} · ${session.width} × ${session.height}${session.source_origin === "EXISTING_RESULT" ? " · 来自已有成品" : ""}` : "应用内独立工作台"}</span>
          </div>
        </div>
        <div className="hdde-retouch-workspace__status" role={error ? "alert" : "status"} data-tone={error ? "error" : busy ? "loading" : "info"}>
          <span className="hdde-retouch-workspace__status-dot" aria-hidden="true" />
          <span>{error || notice}</span>
        </div>
        <div className="hdde-retouch-workspace__actions">
          <UnifiedFeedback taskId={session?.task_id || ""} sourceFeature="local_retouch" stage={busy || (result ? "result_review" : "editing")} triggerLabel="反馈问题" triggerClassName="hdde-retouch-feedback" testId="retouch-feedback-trigger" />
          <button type="button" className="hdde-retouch-import" onClick={() => fileInputRef.current?.click()} disabled={Boolean(busy)} data-testid="retouch-import">{session ? "更换图片" : "导入图片"}</button>
        </div>
      </header>

      <div className="hdde-retouch-workspace__body">
        <aside className="hdde-retouch-toolrail" aria-label="修整工具">
          <div className="hdde-retouch-toolrail__group" role="group" aria-label="选区工具">
            {TOOLS.map((item) => (
              <button
                key={item.key}
                type="button"
                title={item.label}
                aria-label={item.label}
                aria-pressed={tool === item.key}
                className={tool === item.key ? "is-active" : ""}
                onClick={() => {
                  setTool(item.key);
                  setDisplayMode("edit");
                  setRectangleCreateArmed(item.key === "rectangle");
                  if (item.key === "rectangle") {
                    setActiveRegionId(null);
                    setSelectionHover(null);
                    setNotice("可在画布任意位置拖拽新建矩形，包括现有矩形内部。");
                  }
                }}
                disabled={!session || Boolean(busy)}
                data-testid={`retouch-tool-${item.key}`}
              >
                <HddeIcon name={item.icon} size={20} />
                <span>{item.label}</span>
              </button>
            ))}
          </div>
          <span className="hdde-retouch-toolrail__separator" aria-hidden="true" />
          <div className="hdde-retouch-toolrail__group" role="group" aria-label="编辑历史">
            <button type="button" title="撤销当前选区操作" aria-label="撤销选区" onClick={undo} disabled={!undoStack.length || Boolean(busy)}><HddeIcon name="undo" size={20} /><span>撤销选区</span></button>
            <button type="button" title="重做当前选区操作" aria-label="重做选区" onClick={redo} disabled={!redoStack.length || Boolean(busy)}><HddeIcon name="redo" size={20} /><span>重做选区</span></button>
            <button type="button" title="清除选区" aria-label="清除选区" onClick={clearMask} disabled={!repairRegions.length || Boolean(busy)}><HddeIcon name="clear" size={20} /><span>清除</span></button>
          </div>
          <div className="hdde-retouch-toolrail__zoom" aria-label="画布缩放">
            <button type="button" title="缩小" aria-label="缩小" onClick={() => zoomBy(0.8)} disabled={!session}><HddeIcon name="minus" size={19} /></button>
            <span>{session ? `${Math.round(view.scale * 100)}%` : "—"}</span>
            <button type="button" title="适合画布" aria-label="适合画布" onClick={fitView} disabled={!session}><HddeIcon name="fit" size={19} /></button>
            <button type="button" title="放大" aria-label="放大" onClick={() => zoomBy(1.25)} disabled={!session}><HddeIcon name="plus" size={19} /></button>
          </div>
        </aside>

        <div className={`hdde-retouch-stage hdde-retouch-workspace__stage ${session ? "has-image" : "is-empty"}`} role="region" aria-label="瑕疵修复画布">
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
          <div
            ref={canvasWrapRef}
            className={`hdde-retouch-canvas-wrap ${session ? "has-image" : "is-empty"}${fileDragActive ? " is-file-drag-active" : ""}`}
            data-testid="retouch-canvas-wrap"
            data-retouch-drop-zone="true"
            data-file-drag-active={fileDragActive ? "true" : "false"}
            onDragEnter={handleFileDragEnter}
            onDragOver={handleFileDragOver}
            onDragLeave={handleFileDragLeave}
            onDragEnd={resetFileDragState}
            onDrop={handleFileDrop}
          >
            <canvas
              ref={canvasRef}
              className={`hdde-retouch-canvas is-${tool}`}
              style={canvasCursor ? { cursor: canvasCursor } : undefined}
              width={Math.round(canvasSize.width * canvasSize.dpr)}
              height={Math.round(canvasSize.height * canvasSize.dpr)}
              aria-label={session ? "瑕疵修复主画布，可创建、选择、移动和缩放多个矩形，并使用画笔与擦除" : "等待导入图片的瑕疵修复画布"}
              data-testid="retouch-canvas"
              data-image-width={session?.width || ""}
              data-image-height={session?.height || ""}
              data-view-scale={view.scale}
              data-view-offset-x={view.offsetX}
              data-view-offset-y={view.offsetY}
              data-region-count={repairRegions.length}
              data-rectangle-count={rectangles.length}
              data-stroke-count={strokeCount}
              data-active-region-id={activeRectangle?.id || ""}
              data-rectangle-create-armed={rectangleCreateArmed ? "true" : "false"}
              data-selection-x={activeRectangle?.x ?? ""}
              data-selection-y={activeRectangle?.y ?? ""}
              data-selection-width={activeRectangle?.width ?? ""}
              data-selection-height={activeRectangle?.height ?? ""}
              tabIndex={session ? 0 : -1}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerCancel={cancelPointerInteraction}
              onLostPointerCapture={cancelPointerInteraction}
              onPointerLeave={() => { if (!pointerRef.current) setSelectionHover(null); }}
            />
            {!session ? (
              <button type="button" className="hdde-retouch-empty" onClick={() => fileInputRef.current?.click()}>
                <span className="hdde-retouch-empty__icon"><HddeIcon name="retouch" size={24} /></span>
                <strong>拖入一张图片，或点击导入</strong>
                <span>图片导入后即可标记瑕疵；图片只在本机处理。</span>
                <small>支持 PNG、JPG、JPEG · 单图最大 50 MB</small>
              </button>
            ) : null}
            {fileDragActive ? (
              <div className="hdde-retouch-file-drop-indicator" role="status" aria-live="polite" data-testid="retouch-drop-indicator">
                <strong>松手导入这张图片</strong>
                <span>{session ? "将使用现有导入流程更换当前图片" : "将使用现有导入流程建立本地工作副本"}</span>
              </div>
            ) : null}
          </div>
          {displayMode === "compare" && result ? (
            <label className="hdde-retouch-compare-control">
              <span>拖动查看原图与修整结果</span>
              <input data-testid="retouch-compare-slider" type="range" min="0" max="100" value={comparePosition} onChange={(event) => setComparePosition(Number(event.target.value))} />
            </label>
          ) : null}
        </div>

        <aside className="hdde-retouch-inspector" aria-label="瑕疵修复操作">
          <section className="hdde-retouch-inspector__section">
            <div className="hdde-retouch-inspector__heading">
              <span>选区设置</span>
              <strong>{tool === "brush" ? "画笔" : tool === "rectangle" ? (activeRectangle ? `${activeRectangle.width} × ${activeRectangle.height}px` : `${rectangles.length} 个矩形`) : tool === "erase" ? "擦除" : "拖动画布"}</strong>
            </div>
            <button
              type="button"
              className="hdde-retouch-delete-selection"
              onClick={deleteSelection}
              disabled={!activeRectangle || Boolean(busy)}
              data-testid="retouch-delete-selection"
            >
              <HddeIcon name="clear" size={18} />
              <span>删除当前矩形</span>
            </button>
            <button
              type="button"
              className="hdde-retouch-delete-stroke"
              onClick={deleteLastStroke}
              disabled={!latestStrokeRegion(repairRegions) || Boolean(busy)}
              data-testid="retouch-delete-last-stroke"
            >
              <HddeIcon name="undo" size={18} />
              <span>删除上一笔</span>
            </button>
            <label className="hdde-retouch-range-label">
              <span>画笔大小</span>
              <strong>{brushSize}px</strong>
              <input type="range" min="8" max="120" step="2" value={brushSize} onChange={(event) => setBrushSize(Number(event.target.value))} disabled={!session || Boolean(busy)} />
            </label>
          </section>
          <section className="hdde-retouch-inspector__section hdde-retouch-inspector__section--result">
          <div className="hdde-retouch-summary">
            <span>当前状态</span>
            <strong>{saved ? "当前结果已保存" : editDepth ? "当前结果可继续修整" : session ? "等待首次修整" : "等待导入"}</strong>
            <span className="hdde-retouch-summary__depth" data-testid="retouch-edit-depth">
              {editDepth ? `已完成 ${editDepth} 次修整` : "尚未开始修整"}
            </span>
          </div>
          <button type="button" className="hdde-primary-action" onClick={processMask} disabled={!canProcess} data-testid="retouch-process">
            {busy === "process" ? "正在进行瑕疵修复…" : editDepth ? "执行本次修复" : "开始瑕疵修复"}
          </button>
          {editDepth ? (
            <div className="hdde-retouch-result-actions" aria-label="当前结果操作">
              <button type="button" className="hdde-retouch-continue" onClick={continueEditing} disabled={Boolean(busy) || Boolean(saved)} data-testid="retouch-continue">
                <HddeIcon name="brush" size={18} />
                <span>继续修整</span>
              </button>
              <button
                type="button"
                className="hdde-retouch-result-back"
                onClick={backToPreviousResult}
                disabled={!session.can_back_to_previous || Boolean(busy) || Boolean(saved)}
                title={session.can_back_to_previous ? "回到上一次已完成的修整结果；不会撤销当前选区操作" : "当前没有可回退的上一修整结果"}
                data-testid="retouch-back-to-previous"
              >
                <HddeIcon name="back" size={18} />
                <span>{busy === "back" ? "正在回到上一结果…" : "回到上一结果"}</span>
              </button>
              <button type="button" className="hdde-primary-action hdde-retouch-confirm-save" onClick={confirmAndSaveResult} disabled={!canConfirmAndSave} title={repairRegions.length ? "请先执行或清除当前选区" : "确认当前累计结果并保存为正式结果"} data-testid="retouch-confirm-and-save">
                {busy === "save" ? "正在生成正式结果…" : saved ? "当前结果已保存" : "完成修整"}
              </button>
            </div>
          ) : null}
          <p className="hdde-retouch-mask-history-note">撤销选区 / 重做选区只影响当前尚未执行的选区。</p>
          {saved ? (
            <div className="hdde-retouch-saved" data-testid="retouch-saved-result">
              <span>保存结果</span>
              <strong title={saved.output_file_name}>{saved.output_file_name}</strong>
              <small>瑕疵修复结果</small>
              <a href={apiUrl(saved.output_url)} target="_blank" rel="noreferrer">查看派生结果</a>
              <button type="button" onClick={() => requestJson(`/api/local-retouch/sessions/${session.session_id}/open-folder`, { method: "POST" }).catch((reason) => setError(reason.message))}>
                打开所在目录
              </button>
              <button type="button" onClick={onOpenOutputCenter} data-testid="retouch-open-output-center">
                前往输出中心
              </button>
            </div>
          ) : null}
          </section>
          <p className="hdde-retouch-workspace__protection">原图始终保留，结果仅另存为派生文件。</p>
        </aside>
      </div>
    </section>
  );
}
