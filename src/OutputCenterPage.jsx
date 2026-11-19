import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import HddeIcon from "./HddeIcon.jsx";
import { HddePageHeader, HddeStatusPill } from "./HddeUI.jsx";
import { SliderCompareStage } from "./ImageSliderComparePage.jsx";
import { getFileIdentityName } from "./fileDisplayName.js";
import { processingTypeDisplayName } from "./productDisplay.js";
import { calculateOutputHoverPreviewPosition } from "./outputHoverPreview.js";
import {
  OUTPUT_THUMBNAIL_PREFETCH_MARGIN_PX,
  outputThumbnailQueue,
} from "./outputThumbnailLoader.js";

const API_BASE = "";
const OUTPUT_CENTER_INITIAL_PAGE_SIZE = 12;
const OUTPUT_CENTER_PAGE_SIZE = 32;
const OUTPUT_GALLERY_MIN_COLUMN_WIDTH = 254;
const OUTPUT_GALLERY_PREVIEW_DELAY_MS = 550;
const CONTINUE_PROCESSORS = Object.freeze([
  {
    key: "image_enhancement",
    label: "画质增强",
    description: "将当前成品带入画质增强流程。",
    path: "/processing?mode=4k_v1",
    icon: "sparkle",
  },
  {
    key: "color_correction",
    label: "颜色校正",
    description: "将当前成品带入颜色校正流程。",
    path: "/color-correction",
    icon: "color",
  },
  {
    key: "image_compression",
    label: "图片压缩",
    description: "将当前成品带入图片压缩流程。",
    path: "/compression",
    icon: "compress",
  },
  {
    key: "local_retouch",
    label: "瑕疵修复",
    description: "将当前成品带入瑕疵修复流程。",
    path: "/retouch",
    icon: "retouch",
  },
  {
    key: "batch_watermark",
    label: "添加水印",
    description: "将当前成品带入添加水印流程。",
    path: "/batch-watermark",
    icon: "watermark",
  },
  {
    key: "print_output",
    label: "喷绘出图",
    description: "将当前成品带入喷绘出图，设置尺寸与精度。",
    path: "/print-8k",
    icon: "fit",
  },
]);

function pendingContinueProcessors(reason = "正在确认当前成品的处理资格…") {
  return CONTINUE_PROCESSORS.map((processor) => ({
    ...processor,
    status: "CHECKING",
    reason,
  }));
}

function formalProcessingLabel(itemOrType, fallback = "") {
  const item = typeof itemOrType === "object" && itemOrType ? itemOrType : {};
  const processingType = typeof itemOrType === "string" ? itemOrType : item.processing_type;
  return processingTypeDisplayName(processingType, fallback);
}

function formalCategoryLabel(category) {
  return formalProcessingLabel(category.key, category.label);
}

function apiUrl(path) {
  if (!path) return "";
  if (/^https?:\/\//i.test(path)) return path;
  return `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
}

async function requestJson(path, options = {}) {
  const response = await fetch(apiUrl(path), options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.success === false) {
    const detail = payload?.detail;
    throw Object.assign(new Error(detail?.message || payload?.message || "输出中心暂时无法读取该成品。"), { code: detail?.code });
  }
  return payload;
}

function formatBytes(value) {
  const size = Number(value) || 0;
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(2)} MB`;
}

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未记录";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function displayName(item) {
  return getFileIdentityName(item?.file_name, "图片成品");
}

function deliveryUnavailableReason(item) {
  if (item?.delivery_eligible === true) return "";
  // Status only explains the denial; delivery_eligible remains the authority.
  if (item?.status === "failed") return "结果未通过安全保护，暂不可交付";
  if (item?.result_action === "ACCEPT_ORIGINAL") return "未生成新的校色结果";
  if (item?.result_action === "REVIEW_REQUIRED") return "结果待确认，确认后可加入交付";
  return "当前结果暂不可交付，请检查处理结果";
}

function OutputThumbnail({ item, onPreviewOpen = () => {}, onPreviewClose, compact = false }) {
  const containerRef = useRef(null);
  const releaseRef = useRef(null);
  const activeUrlRef = useRef("");
  const completedUrlRef = useRef("");
  const [loadState, setLoadState] = useState("idle");
  const [loadPriority, setLoadPriority] = useState("prefetch");
  const queueKey = compact ? `batch-cover:${item.id}` : item.id;

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return undefined;
    if (!item.thumbnail_url) {
      setLoadState("failed");
      return undefined;
    }
    const scrollRoot = node.closest("main");
    let visible = false;
    let disposed = false;
    const requestLoad = (priority) => {
      if (activeUrlRef.current === item.thumbnail_url || completedUrlRef.current === item.thumbnail_url) return;
      outputThumbnailQueue.schedule(queueKey, priority, (release) => {
        if (disposed) {
          release();
          return;
        }
        activeUrlRef.current = item.thumbnail_url;
        releaseRef.current = release;
        setLoadPriority(priority);
        setLoadState("loading");
      });
    };
    if (typeof IntersectionObserver === "undefined") {
      requestLoad("visible");
      return () => {
        disposed = true;
        outputThumbnailQueue.cancel(queueKey);
        releaseRef.current?.();
        releaseRef.current = null;
      };
    }
    const visibleObserver = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible) requestLoad("visible");
    }, { root: scrollRoot, threshold: 0.01 });
    const prefetchObserver = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) requestLoad(visible ? "visible" : "prefetch");
      else if (!visible) outputThumbnailQueue.cancel(queueKey);
    }, { root: scrollRoot, rootMargin: `${OUTPUT_THUMBNAIL_PREFETCH_MARGIN_PX}px 0px`, threshold: 0 });
    visibleObserver.observe(node);
    prefetchObserver.observe(node);
    return () => {
      disposed = true;
      visibleObserver.disconnect();
      prefetchObserver.disconnect();
      outputThumbnailQueue.cancel(queueKey);
      releaseRef.current?.();
      releaseRef.current = null;
      if (activeUrlRef.current === item.thumbnail_url) activeUrlRef.current = "";
    };
  }, [queueKey, item.thumbnail_url]);

  const settle = (nextState, thumbnailUrl) => {
    if (activeUrlRef.current !== thumbnailUrl) return;
    activeUrlRef.current = "";
    completedUrlRef.current = thumbnailUrl;
    setLoadState(nextState);
    releaseRef.current?.();
    releaseRef.current = null;
  };

  return (
    <span
      ref={containerRef}
      className="hdde-output-thumb"
      data-testid={compact ? undefined : `output-card-image-${item.id}`}
      data-load-state={loadState}
      aria-busy={loadState === "loading"}
      onPointerEnter={(event) => onPreviewOpen(item, event.currentTarget)}
      onPointerLeave={onPreviewClose}
      onPointerCancel={onPreviewClose}
    >
      <span className="hdde-output-thumb__placeholder" aria-hidden={loadState !== "failed"}>
        {loadState === "failed" ? "预览不可用" : ""}
      </span>
      {loadState !== "idle" && loadState !== "failed" ? (
        <img
          src={apiUrl(item.thumbnail_url)}
          alt={compact ? "" : `${displayName(item)}预览`}
          decoding="async"
          fetchpriority={loadPriority === "visible" ? "high" : "low"}
          onLoad={() => settle("loaded", item.thumbnail_url)}
          onError={() => settle("failed", item.thumbnail_url)}
        />
      ) : null}
    </span>
  );
}

function outputThumbnailStyle(rawWidth, rawHeight) {
  const width = Number(rawWidth);
  const height = Number(rawHeight);
  return Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0
    ? { "--output-thumb-ratio": `${width} / ${height}` }
    : undefined;
}

const OutputRecordCard = React.memo(function OutputRecordCard({
  item, selected, selectItem, performAction, onPreviewOpen, onPreviewClose,
}) {
  const metadata = item.available === false ? "正式文件缺失"
    : `${formalProcessingLabel(item, item.processing_label)} · ${item.width} × ${item.height} · ${formatBytes(item.size_bytes)}`;
  return (
              <section className="hdde-output-card-record" key={item.id} data-testid="output-record-card" style={outputThumbnailStyle(item.width, item.height)}>
              <button
                type="button"
                className="hdde-output-card"
                data-selected={selected}
                key={item.id}
                onClick={() => selectItem(item)}
              >
                <OutputThumbnail item={item} onPreviewOpen={onPreviewOpen} onPreviewClose={onPreviewClose} />
                <span className="hdde-output-card-copy">
                  <strong title={item.file_name}>{displayName(item)}</strong>
                  <small title={metadata}>{metadata}</small>
                </span>
              </button>
              <button type="button" className="hdde-tertiary-action hdde-output-record-remove"
                aria-label="移除记录" title="移除记录" data-remove-id={item.id} onClick={() => performAction(item, "clear")}>
                <HddeIcon name="clear" size={16} />
              </button>
              </section>
  );
});

function OutputMasonry({ items, className, label, renderItem, gallery = false }) {
  const gridRef = useRef(null);

  useLayoutEffect(() => {
    const grid = gridRef.current;
    const cards = Array.from(grid.children);
    const gap = parseFloat(getComputedStyle(grid).rowGap);

    const layout = () => {
      const width = grid.clientWidth;
      const capacity = gallery
        ? Math.max(1, Math.min(5, Math.floor((width + gap) / (OUTPUT_GALLERY_MIN_COLUMN_WIDTH + gap))))
        : width >= 1400 ? 4 : width >= 1030 ? 3 : width >= 612 ? 2 : 1;
      const columns = Math.min(cards.length, capacity);
      grid.dataset.columns = String(columns);
      grid.style.setProperty("--output-column-count", String(columns));
      if (columns < 2) {
        grid.style.height = "";
        return;
      }

      const heights = cards.map((card) => card.getBoundingClientRect().height);
      const columnEnds = Array(columns).fill(0);
      // Position cards in DOM order so appending records only fills space below them.
      cards.forEach((card, index) => {
        const column = columnEnds.indexOf(Math.min(...columnEnds));
        card.style.setProperty("--output-card-column", String(column));
        card.style.setProperty("--output-card-top", `${columnEnds[column]}px`);
        columnEnds[column] += heights[index] + gap;
      });
      grid.style.height = `${Math.max(...columnEnds) - gap}px`;
    };

    if (typeof ResizeObserver === "undefined") return undefined;
    layout();
    let frame;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(layout);
    });
    observer.observe(grid);
    cards.forEach((card) => observer.observe(card));
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [items, gallery]);

  return (
    <div ref={gridRef} className={`hdde-output-masonry ${className}`} aria-label={label}>
      {items.map(renderItem)}
    </div>
  );
}

const BATCH_CHILD_LABELS = {
  COMPLETED: "文件不可用", KEEP_ORIGINAL: "保留原图", FAILED: "失败",
  CANCELED: "已取消", QUEUED: "等待处理", PROCESSING: "处理中",
};

function OutputBatchSummary({ item, expanded, onToggle, onRemove }) {
  const { summary } = item;
  const compressed = item.feature_type === "image_compression";
  const coverItems = item.items
    .filter((child) => (child.available && child.thumbnail_url) ||
      (child.status === "KEEP_ORIGINAL" && child.source_thumbnail_url))
    .slice(0, 2);
  const firstItem = item.items[0];
  const firstFileName = firstItem?.source_file_name || firstItem?.file_name;
  const outcomes = [
    [compressed ? "压缩成品" : item.feature_type === "local_retouch" ? "已另存" : "成功", summary.completed, "success"],
    ["保留原图", summary.keep_original],
    ["失败", summary.failed, "danger"],
    ["取消", summary.canceled],
    ["文件不可用", summary.unavailable, "warning"],
    ["处理中", summary.processing, "active"],
    ["等待", summary.pending],
  ];
  const sizeChange = summary.saved_bytes > 0 ? `节省 ${formatBytes(summary.saved_bytes)}`
    : summary.saved_bytes < 0 ? `增加 ${formatBytes(-summary.saved_bytes)}` : "体积不变";

  return (
    <div className="hdde-output-batch-summary">
      <button type="button" className="hdde-output-batch-toggle" aria-expanded={expanded} onClick={onToggle}>
        <span className="hdde-output-batch-covers" aria-hidden="true">
          {coverItems.length ? coverItems.map((child) => (
            <OutputThumbnail key={child.id} compact
              item={child.available ? child : { ...child, thumbnail_url: child.source_thumbnail_url }} />
          )) : <span className="hdde-output-batch-cover-empty"><HddeIcon name="outputs" size={20} /></span>}
        </span>
        <span className="hdde-output-batch-facts">
          <strong>{item.file_name}</strong>
          <small>{formatTime(item.created_at)}</small>
          {firstFileName ? <small className="hdde-output-batch-first-file" title={firstFileName}>{firstFileName}</small> : null}
        </span>
        <span className="hdde-output-batch-outcomes">
          {outcomes.filter(([, count]) => count > 0).map(([label, count, tone]) => (
            <span key={label} data-tone={tone}>{label} <strong>{count}</strong></span>
          ))}
        </span>
        {compressed ? (
          <span className="hdde-output-batch-size" title="批次体积统计，失败和取消项按原图计入">
            <span>{formatBytes(summary.original_bytes)} → {formatBytes(summary.final_bytes)}</span>
            <small>{sizeChange}</small>
          </span>
        ) : null}
        <span className="hdde-output-batch-disclosure">
          {expanded ? "收起子项" : "展开全部子项"}
          <HddeIcon name="chevron" size={14} />
        </span>
      </button>
      <button type="button" className="hdde-tertiary-action hdde-output-batch-remove"
        disabled={item.running} data-remove-id={item.id} onClick={onRemove}>移除记录</button>
    </div>
  );
}

function OutputBatchItem({ child, running, selected, selectItem, performAction, onContinue, onPreviewOpen, onPreviewClose }) {
  const isMissing = child.file_status === "MISSING";
  const keepOriginal = child.status === "KEEP_ORIGINAL";
  const reason = child.error || child.availability_reason || (keepOriginal ? "原图预览不可用。" : "");
  const statusCopy = (
    <>
      <strong>{child.file_name}</strong>
      <small>{isMissing ? "正式文件缺失" : BATCH_CHILD_LABELS[child.status] || child.status}</small>
      {reason ? <small>{reason}</small> : null}
    </>
  );
  return (
    <div className="hdde-output-batch-item" data-testid="output-batch-item" data-status={child.status} data-result-id={child.result_id}
      style={outputThumbnailStyle(keepOriginal ? child.source_width : child.width, keepOriginal ? child.source_height : child.height)}>
      {child.available ? (
        <button type="button" className="hdde-output-card hdde-output-batch-child" data-selected={selected} onClick={() => selectItem(child)}>
          <OutputThumbnail item={child} onPreviewOpen={onPreviewOpen} onPreviewClose={onPreviewClose} />
          <span className="hdde-output-card-copy"><strong>{child.source_file_name || child.file_name}</strong><small>成功 · {child.output_file_name}</small></span>
        </button>
      ) : keepOriginal && child.source_thumbnail_url ? (
        <div className="hdde-output-card hdde-output-batch-original">
          <OutputThumbnail item={{ ...child, thumbnail_url: child.source_thumbnail_url }} onPreviewOpen={onPreviewOpen} onPreviewClose={onPreviewClose} />
          <span className="hdde-output-card-copy"><strong>{child.file_name}</strong><small>保留原图</small></span>
        </div>
      ) : isMissing ? (
        <button type="button" className="hdde-output-card-copy hdde-output-batch-status" data-selected={selected} onClick={() => selectItem(child)}>{statusCopy}</button>
      ) : <div className="hdde-output-card-copy">{statusCopy}</div>}
      {child.available ? (
        <div className="hdde-output-batch-actions">
          <button type="button" className="hdde-secondary-action" onClick={() => performAction(child, "open")}>打开文件</button>
          <button type="button" className="hdde-secondary-action" onClick={() => performAction(child, "open-folder")}>打开目录</button>
          <button type="button" className="hdde-secondary-action" onClick={() => onContinue(child)}>单图处理</button>
        </div>
      ) : null}
      <button type="button" className="hdde-tertiary-action" disabled={running} data-remove-id={child.record_id} onClick={() => performAction(child, "clear")}>移除记录</button>
    </div>
  );
}

function OutputCompareView({ itemId, siblings = [], onSwitch, onBack }) {
  const [response, setResponse] = useState(null);
  const [split, setSplit] = useState(50);
  const current = response?.itemId === itemId ? response : null;
  const item = current?.item;
  const index = siblings.findIndex((child) => child.id === itemId);

  useEffect(() => {
    const controller = new AbortController();
    requestJson(`/api/output-center/items/${encodeURIComponent(itemId)}/comparison`, { signal: controller.signal })
      .then((payload) => {
        if (!controller.signal.aborted) setResponse({ itemId, item: payload.data });
      })
      .catch((reason) => !controller.signal.aborted && setResponse({ itemId, error: reason.message }));
    return () => controller.abort();
  }, [itemId]);

  return (
    <section className="hdde-output-compare-page" data-testid="output-center-compare">
      <header className="hdde-output-header">
        <div>
          <p className="hdde-eyebrow">对比质检</p>
          <h1>查看处理前后</h1>
          <p>{item ? `${formalProcessingLabel(item, item.processing_label)} · ${displayName(item)}` : "正在核对真实原图与成品映射。"}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {index >= 0 && <>
            <button type="button" className="hdde-secondary-action" disabled={index === 0} onClick={() => onSwitch(siblings[index - 1])}>上一张</button>
            <span className="text-sm" aria-live="polite">第 {index + 1} / {siblings.length} 张</span>
            <button type="button" className="hdde-secondary-action" disabled={index === siblings.length - 1} onClick={() => onSwitch(siblings[index + 1])}>下一张</button>
          </>}
          <button type="button" className="hdde-secondary-action" onClick={onBack}>返回输出中心</button>
        </div>
      </header>
      {!current ? <div className="hdde-output-empty" role="status">正在读取真实成品…</div> : null}
      {current?.error ? <div className="hdde-output-alert" role="alert">{current.error}</div> : null}
      {item ? (
        <div className="hdde-output-compare-layout">
          <SliderCompareStage
            key={itemId}
            split={split}
            onSplitChange={setSplit}
            originalUrl={apiUrl(item.source_preview_url)}
            enhancedUrl={apiUrl(item.preview_url)}
            deliveryBadge="处理后"
            showIdentity={false}
          />
          <aside className="hdde-output-compare-notes">
            <div className="hdde-output-compare-instructions">
              <h2>人工复核</h2>
              <p>拖动中线或按方向键，查看原图与成品。</p>
            </div>
            <dl>
              <div><dt>处理类型</dt><dd>{formalProcessingLabel(item, item.processing_label)}</dd></div>
              <div><dt>成品尺寸</dt><dd>{item.width} × {item.height}</dd></div>
              <div><dt>文件格式</dt><dd>{item.format}</dd></div>
              <div><dt>文件体积</dt><dd>{formatBytes(item.size_bytes)}</dd></div>
            </dl>
          </aside>
        </div>
      ) : null}
    </section>
  );
}

export default function OutputCenterPage({ compareItemId = "", outputBatchId = "", onNavigate, onBackFromCompare }) {
  const [data, setData] = useState({ items: [], categories: [] });
  const [activeCategory, setActiveCategory] = useState("all");
  const [browseKind, setRecordKind] = useState(outputBatchId ? "batch" : "single");
  const recordKind = outputBatchId ? "batch" : browseKind;
  const [selectedId, setSelectedId] = useState("");
  const [detailOpen, setDetailOpen] = useState(false);
  const selectedItemRef = useRef(null);
  const [selectionCleared, setSelectionCleared] = useState(false);
  const [listScope, setListScope] = useState("all");
  const [cleanupOpen, setCleanupOpen] = useState(false);
  const [clearingRecords, setClearingRecords] = useState(false);
  const [expandedBatches, setExpandedBatches] = useState(() => new Set());
  const [refreshKey, setRefreshKey] = useState(0);
  const [loading, setLoading] = useState(!compareItemId);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedDeliveryItems, setSelectedDeliveryItems] = useState([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [sortOrder, setSortOrder] = useState("newest");
  const [hoverPreview, setHoverPreview] = useState(null);
  const hoverPreviewTimerRef = useRef(0);
  const [continueDialog, setContinueDialog] = useState({ item: null, loading: false, options: [], error: "" });
  const continueDialogRef = useRef(null);
  const continueEligibilityCacheRef = useRef(new Map());
  const continueRequestSequenceRef = useRef(0);
  const pageRef = useRef(null);
  const outputListRef = useRef(null);
  const compareReturnRef = useRef(null);
  const pageLoaderRef = useRef(null);
  const cleanupRefreshRef = useRef(false);
  const cardHandlersRef = useRef(null);
  const cardActions = useMemo(() => ({
    selectItem: (item) => cardHandlersRef.current.selectItem(item),
    performAction: (item, action) => cardHandlersRef.current.performAction(item, action),
  }), []);

  useEffect(() => {
    if (outputBatchId) setExpandedBatches((current) => current.has(outputBatchId) ? current : new Set([...current, outputBatchId]));
  }, [outputBatchId]);

  useEffect(() => {
    if (compareItemId) return undefined;
    let active = true;
    const controller = new AbortController();
    let nextTimer = 0;
    let pendingNextOffset = null;
    let listRevision = "";
    let paging = false;
    const scrollRoot = pageRef.current?.closest("main");
    const loadNextPage = ({ force = false } = {}) => {
      if (!active || paging || pendingNextOffset == null || !scrollRoot) return;
      const list = pageRef.current?.querySelector(".hdde-output-list");
      if (!list || (!force && list.getBoundingClientRect().bottom > scrollRoot.getBoundingClientRect().bottom + 120)) return;
      paging = true;
      setLoadingMore(true);
      const offset = pendingNextOffset;
      pendingNextOffset = null;
      loadRemaining(offset);
    };
    pageLoaderRef.current = loadNextPage;
    setLoadingMore(false);
    const cleanupRefresh = cleanupRefreshRef.current;
    const compareReturn = compareReturnRef.current;
    cleanupRefreshRef.current = false;
    setLoading(!cleanupRefresh);
    setError("");
    if (!cleanupRefresh) setData((current) => ({ ...current, items: [], total_count: 0, has_more: false }));

    const baseParams = new URLSearchParams({
      scope: listScope,
      query: searchQuery.trim(),
      sort: sortOrder,
      category: activeCategory,
      record_kind: recordKind,
    });
    if (outputBatchId) baseParams.set("batch_id", outputBatchId);

    const requestPage = async (offset, limit, revision = "") => {
      const params = new URLSearchParams(baseParams);
      params.set("limit", String(limit));
      params.set("offset", String(offset));
      if (revision) params.set("list_revision", revision);
      const selectedItem = selectedItemRef.current;
      if (selectedItem) params.set("selected_id", selectedItem.record_id || selectedItem.id);
      const payload = await requestJson(`/api/output-center/items?${params}`, { signal: controller.signal });
      return payload.data;
    };

    const rememberPage = (page) => {
      listRevision = page.list_revision;
      pendingNextOffset = page.has_more ? page.next_offset : null;
    };

    // Rebuild the loaded range atomically so a new ordering never mixes with old pages.
    const readWindow = async (targetCount) => {
      let page = await requestPage(0, OUTPUT_CENTER_INITIAL_PAGE_SIZE);
      const items = [...page.items];
      while (active && page.has_more && page.next_offset < targetCount) {
        page = await requestPage(page.next_offset, OUTPUT_CENTER_PAGE_SIZE, page.list_revision);
        items.push(...page.items);
      }
      return { ...page, items, returned_count: items.length };
    };

    const loadRemaining = async (offset) => {
      setError("");
      try {
        let next;
        let replace = false;
        try {
          next = await requestPage(offset, OUTPUT_CENTER_PAGE_SIZE, listRevision);
        } catch (reason) {
          if (!active || reason.code !== "OUTPUT_CENTER_LIST_CHANGED") throw reason;
          next = await readWindow(offset + OUTPUT_CENTER_PAGE_SIZE);
          replace = true;
        }
        if (!active) return;
        setData((current) => {
          const items = replace ? next.items : [...current.items, ...next.items];
          return { ...next, items, returned_count: items.length };
        });
        rememberPage(next);
      } catch (reason) {
        if (active && reason?.name !== "AbortError") {
          pendingNextOffset = offset;
          setError(reason.message);
        }
      } finally {
        paging = false;
        if (active) setLoadingMore(false);
      }
    };

    const loadFirstPage = async () => {
      try {
        const targetCount = compareReturn?.loadedCount ?? (cleanupRefresh ? data.items.length : OUTPUT_CENTER_INITIAL_PAGE_SIZE);
        const next = await readWindow(targetCount);
        if (!active) return;
        if (compareReturn) compareReturn.ready = true;
        setData(next);
        rememberPage(next);
      } catch (reason) {
        if (active && reason?.name !== "AbortError") {
          compareReturnRef.current = null;
          setError(reason.message);
        }
      } finally {
        if (active) setLoading(false);
      }
    };

    scrollRoot?.addEventListener("scroll", loadNextPage, { passive: true });
    nextTimer = window.setTimeout(
      loadFirstPage,
      searchQuery.trim() ? 150 : 0,
    );
    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(nextTimer);
      scrollRoot?.removeEventListener("scroll", loadNextPage);
      pageLoaderRef.current = null;
    };
  }, [activeCategory, compareItemId, searchQuery, sortOrder, refreshKey, listScope, recordKind, outputBatchId]);

  const visibleItems = useMemo(() => {
    const query = searchQuery.trim().toLocaleLowerCase("zh-CN");
    return data.items
      .filter((item) => (item.card_type === "batch") === (recordKind === "batch"))
      .filter((item) => !outputBatchId || item.batch_id === outputBatchId)
      .filter((item) => activeCategory === "all" || item.processing_type === activeCategory)
      .filter((item) => {
        if (!query) return true;
        const fileIdentityName = getFileIdentityName(item?.file_name).toLocaleLowerCase("zh-CN");
        const productDisplayName = formalProcessingLabel(item, item.processing_label).toLocaleLowerCase("zh-CN");
        return fileIdentityName.includes(query) || productDisplayName.includes(query)
          || (item.items || []).some((child) => child.file_name.toLocaleLowerCase("zh-CN").includes(query));
      })
      .sort((left, right) => {
        const delta = new Date(right.created_at || 0).getTime() - new Date(left.created_at || 0).getTime();
        return sortOrder === "oldest" ? -delta : delta;
      });
  }, [activeCategory, data.items, searchQuery, sortOrder, recordKind, outputBatchId]);
  const selectableItems = visibleItems.flatMap((item) => item.card_type === "batch" ? item.items.filter((child) => child.available || child.file_status === "MISSING") : [item]);
  const selectedInPage = selectableItems.find((item) => (item.record_id || item.id) === selectedId);
  const retainedSelection = data.selected_id === selectedId && data.selection_matches ? selectedItemRef.current : null;
  const selected = selectionCleared ? null : selectedInPage || retainedSelection || selectableItems[0] || null;
  useEffect(() => {
    if (selectedInPage) selectedItemRef.current = selectedInPage;
  }, [selectedInPage]);
  const selectedForDelivery = selected
    ? selectedDeliveryItems.some((item) => item.id === selected.id)
    : false;
  const selectedDeliveryEligible = selected?.delivery_eligible === true;
  const deliveryReason = deliveryUnavailableReason(selected);

  useEffect(() => {
    if (!data.items.some((item) => item.running)) return undefined;
    const timer = window.setTimeout(() => setRefreshKey((current) => current + 1), 2000);
    return () => window.clearTimeout(timer);
  }, [data.items]);

  const closeHoverPreview = useCallback(() => {
    window.clearTimeout(hoverPreviewTimerRef.current);
    setHoverPreview(null);
  }, []);
  const openHoverPreview = useCallback((item, target) => {
    const image = target.querySelector("img");
    if (!image?.complete || !image.naturalWidth) return;
    const position = calculateOutputHoverPreviewPosition({
      anchorRect: target.getBoundingClientRect(),
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      imageWidth: image?.naturalWidth,
      imageHeight: image?.naturalHeight,
      previewWidth: Math.min(760, Math.max(520, window.innerWidth * 0.46)),
    });
    setHoverPreview({ item, position });
  }, []);
  const scheduleGalleryPreview = useCallback((item, target) => {
    window.clearTimeout(hoverPreviewTimerRef.current);
    hoverPreviewTimerRef.current = window.setTimeout(() => {
      if (target.isConnected && target.matches(":hover")) openHoverPreview(item, target);
    }, OUTPUT_GALLERY_PREVIEW_DELAY_MS);
  }, [openHoverPreview]);

  useEffect(() => {
    window.addEventListener("scroll", closeHoverPreview, true);
    window.addEventListener("resize", closeHoverPreview);
    return () => {
      window.removeEventListener("scroll", closeHoverPreview, true);
      window.removeEventListener("resize", closeHoverPreview);
      window.clearTimeout(hoverPreviewTimerRef.current);
    };
  }, [closeHoverPreview]);

  useEffect(() => {
    if (hoverPreview && !visibleItems.some((item) => item.id === hoverPreview.item.id ||
      (expandedBatches.has(item.id) && item.items?.some((child) => child.id === hoverPreview.item.id)))) {
      closeHoverPreview();
    }
  }, [closeHoverPreview, expandedBatches, hoverPreview, visibleItems]);

  useLayoutEffect(() => {
    const saved = compareReturnRef.current;
    if (compareItemId || loading || !saved?.ready || !outputListRef.current) return;
    // Restore after the previous page range has been rendered so the browser does not clamp the position.
    outputListRef.current.scrollTop = saved.scrollTop;
    if (saved.batchItems) {
      const card = outputListRef.current.querySelector(".hdde-output-batch-child[data-selected='true']");
      card?.focus({ preventScroll: true });
      card?.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
    compareReturnRef.current = null;
  }, [compareItemId, data.items, loading]);

  useLayoutEffect(() => {
    const dialog = continueDialogRef.current;
    if (!dialog) return undefined;
    dialog.showModal();
    return () => dialog.close();
  }, [compareItemId, continueDialog.item]);

  const selectItem = (item) => {
    closeHoverPreview();
    setDetailOpen(true);
    selectedItemRef.current = item;
    setSelectedId(item.record_id || item.id);
    setSelectionCleared(false);
  };
  const comparePath = (item) => outputBatchId ? `${item.compare_url}&batch_id=${encodeURIComponent(outputBatchId)}` : item.compare_url;
  if (compareItemId) return (
    <OutputCompareView itemId={compareItemId} siblings={compareReturnRef.current?.batchItems} onBack={onBackFromCompare}
      onSwitch={(child) => {
        selectItem(child);
        onNavigate?.(comparePath(child), { replace: true });
      }} />
  );
  const applyRemoval = (removedIds, outcome = {}) => {
    const removed = new Set(removedIds);
    if (removed.has(selected?.id) || removed.has(selected?.batch_id) || removed.has(selected?.record_id)) {
      selectedItemRef.current = null;
      setSelectionCleared(true);
      setSelectedId("");
    }
    closeHoverPreview();
    setContinueDialog({ item: null, loading: false, options: [], error: "" });
    setSelectedDeliveryItems((current) => current.filter((item) => !removed.has(item.id) && !removed.has(item.batch_id) && !removed.has(item.record_id)));
    setData((current) => {
      const batchUpdates = new Map((outcome.updated_batches || []).map((batch) => [batch.id, batch]));
      const items = current.items.filter((item) => !removed.has(item.id)).map((item) => item.card_type === "batch"
        ? { ...item, ...batchUpdates.get(item.id), items: item.items.filter((child) => !removed.has(child.id) && !removed.has(child.record_id)) } : item)
        .filter((item) => item.card_type !== "batch" || item.items.length);
      const removedCards = (outcome.removed_cards || []).filter((card) => listScope === "all" || card.scope === listScope);
      const categories = current.categories.map((category) => ({ ...category,
        count: Math.max(0, category.count - removedCards.filter((card) => category.key === "all" || category.key === card.category).length) }));
      const removedCount = current.items.length - items.length;
      return { ...current, items, categories, scope_counts: outcome.scope_counts || current.scope_counts,
        total_count: Math.max(0, (current.total_count ?? current.items.length) - removedCount) };
    });
    cleanupRefreshRef.current = true;
    setRefreshKey((current) => current + 1);
  };
  const cleanupList = async (scope, mode) => {
    if (clearingRecords) return;
    if (mode === "all" && !window.confirm(`确定清空${scope === "current" ? "当前" : "历史"}列表吗？仅移除列表记录，保留正式成品文件。`)) return;
    setClearingRecords(true); setError("");
    try {
      const payload = await requestJson("/api/output-center/cleanup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scope, mode }) });
      applyRemoval(payload.data.removed_ids || [], payload.data);
      setNotice(`已移除 ${payload.data.removed_count} 条记录，正式输出文件保持不变。`);
    } catch (reason) { setError(reason.message); }
    finally { setClearingRecords(false); }
  };

  const performAction = async (item, action) => {
    if (!item) return;
    setError("");
    setNotice("");
    try {
      const payload = await requestJson(`/api/output-center/items/${encodeURIComponent(action === "clear" ? item.record_id || item.id : item.id)}/${action}`, { method: "POST" });
      if (action === "clear") {
        applyRemoval(payload.data.removed_ids || [item.id], payload.data);
        setNotice("已移除列表记录，正式输出文件保持不变。");
      }
    } catch (reason) {
      setError(reason.message);
    }
  };

  cardHandlersRef.current = { selectItem, performAction };

  const openCompare = (item) => {
    if (!item?.compare_available || !item.compare_url) return;
    const batch = visibleItems.find((card) => card.card_type === "batch" && card.id === item.batch_id);
    if (batch) {
      selectItem(item);
      setExpandedBatches((current) => current.has(batch.id) ? current : new Set([...current, batch.id]));
    }
    compareReturnRef.current = {
      batchItems: batch?.items.filter((child) => child.available && child.compare_available && child.compare_url),
      scrollTop: outputListRef.current?.scrollTop ?? 0,
      loadedCount: data.items.length,
      ready: false,
    };
    onNavigate?.(comparePath(item));
  };

  const openContinueProcessing = async (item) => {
    const resultId = String(item?.result_id || "");
    const version = String(item?.continue_eligibility_version || "");
    const cacheKey = `${resultId}|${version}`;
    const cached = continueEligibilityCacheRef.current.get(cacheKey);
    const requestSequence = continueRequestSequenceRef.current + 1;
    continueRequestSequenceRef.current = requestSequence;
    setError("");
    if (!item?.unified_result || !resultId) {
      setContinueDialog({
        item,
        loading: false,
        options: pendingContinueProcessors("当前成品缺少完整 Result 来源关系。").map((processor) => ({
          ...processor,
          status: "UNAVAILABLE",
        })),
        error: "",
      });
      return;
    }
    if (cached) {
      setContinueDialog({ item, loading: false, options: cached, error: "" });
      return;
    }
    setContinueDialog({ item, loading: true, options: pendingContinueProcessors(), error: "" });
    try {
      const payload = await requestJson(`/api/output-center/items/${encodeURIComponent(item.id)}/continue-eligibility`);
      const states = new Map((payload.data?.processors || []).map((entry) => [entry.key, entry]));
      const options = CONTINUE_PROCESSORS.map((processor) => ({
        ...processor,
        status: states.get(processor.key)?.status || "UNAVAILABLE",
        historyStatus: states.get(processor.key)?.history_status || "NOT_PROCESSED",
        repeatable: states.get(processor.key)?.repeatable === true,
        reason: states.get(processor.key)?.reason || "当前处理器资格信息不可用。",
      }));
      continueEligibilityCacheRef.current.set(cacheKey, options);
      if (continueRequestSequenceRef.current !== requestSequence) return;
      setContinueDialog((current) => (
        current.item?.id === item.id
          ? { ...current, loading: false, options, error: "" }
          : current
      ));
    } catch (reason) {
      if (continueRequestSequenceRef.current !== requestSequence) return;
      setContinueDialog((current) => (
        current.item?.id === item.id
          ? {
            ...current,
            loading: false,
            options: pendingContinueProcessors(reason.message).map((processor) => ({ ...processor, status: "UNAVAILABLE" })),
            error: "资格状态读取失败，请刷新输出中心后重试。",
          }
          : current
      ));
    }
  };

  const closeContinueProcessing = () => {
    continueDialogRef.current?.close();
    setContinueDialog({ item: null, loading: false, options: [], error: "" });
  };

  const keepContinueFocus = (event) => {
    if (event.key !== "Tab") return;
    const buttons = event.currentTarget.querySelectorAll("button:not(:disabled)");
    const first = buttons[0];
    const last = buttons[buttons.length - 1];
    if (document.activeElement !== (event.shiftKey ? first : last)) return;
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
  };

  const chooseContinueProcessor = (processor) => {
    if (processor?.status !== "AVAILABLE") return;
    const resultId = String(continueDialog.item?.result_id || "");
    if (!resultId) return;
    closeContinueProcessing();
    const separator = processor.path.includes("?") ? "&" : "?";
    onNavigate?.(`${processor.path}${separator}continue_result=${encodeURIComponent(resultId)}`);
  };

  const toggleDeliveryItem = (item) => {
    if (item?.delivery_eligible !== true) return;
    setSelectedDeliveryItems((current) => (
      current.some((selectedItem) => selectedItem.id === item.id)
        ? current.filter((selectedItem) => selectedItem.id !== item.id)
        : [...current, item]
    ));
  };

  const openSmartDelivery = () => {
    if (!selectedDeliveryItems.length) return;
    if (selectedDeliveryItems.some((item) => item.delivery_eligible !== true)) {
      setError("交付清单中的结果已不可交付，请重新选择可交付成品。");
      return;
    }
    const unifiedResultIds = selectedDeliveryItems.map((item) => item.unified_result ? item.result_id : "");
    if (unifiedResultIds.length === selectedDeliveryItems.length && unifiedResultIds.every(Boolean)) {
      onNavigate?.(`/smart-delivery?results=${encodeURIComponent(unifiedResultIds.join(","))}`);
      return;
    }
    const selectedItemIds = selectedDeliveryItems.map((item) => item.id);
    onNavigate?.(`/smart-delivery?items=${encodeURIComponent(selectedItemIds.join(","))}`);
  };

  const deliveryCount = selectedDeliveryItems.length;

  const selectRecordKind = (kind, showAllBatches = false) => {
    if (kind === recordKind && !showAllBatches) return;
    if (showAllBatches) {
      setActiveCategory("all");
      setListScope("all");
      setSearchQuery("");
    }
    cleanupRefreshRef.current = false;
    selectedItemRef.current = null;
    setSelectedId("");
    setSelectionCleared(false);
    setDetailOpen(false);
    closeHoverPreview();
    if (outputListRef.current) outputListRef.current.scrollTop = 0;
    setLoading(true);
    setRecordKind(kind);
    if (outputBatchId) onNavigate?.("/outputs");
  };

  return (
    <section ref={pageRef} className="hdde-output-page hdde-page-frame hdde-page-stack" aria-labelledby="output-center-title">
      <HddePageHeader
        eyebrow="成品与交付"
        title="输出中心"
        headingId="output-center-title"
        meta={<HddeStatusPill tone="neutral">{loading ? "正在读取成品" : `${data.total_count ?? data.items.length} 条${recordKind === "batch" ? "批量" : "单张"}记录`}</HddeStatusPill>}
        actions={<>
          {outputBatchId ? <button type="button" className="hdde-secondary-action" onClick={() => selectRecordKind("batch", true)}>查看全部批次</button> : null}
          {selected ? (
            <button type="button" className="hdde-secondary-action hdde-output-detail-toggle"
              aria-expanded={detailOpen} aria-controls="output-current-detail" onClick={() => setDetailOpen((open) => !open)}>
              {detailOpen ? "收起成品详情" : "查看成品详情"}
            </button>
          ) : null}
          <button type="button" className="hdde-primary-action hdde-output-prepare-delivery"
            disabled={!deliveryCount} onClick={openSmartDelivery}>
            生成交付副本 <span className="hdde-output-delivery-count" aria-hidden="true">{deliveryCount}</span>
          </button>
          <span className="sr-only" role="status">交付清单已选 {deliveryCount} 份成品</span>
        </>}
      />

      {error ? <div className="hdde-output-alert" role="alert">{error}</div> : null}
      {notice ? <div className="hdde-output-notice" role="status">{notice}</div> : null}
      <div className="hdde-desktop-columns hdde-output-columns">
        <aside className="hdde-output-filters" aria-label="筛选与搜索">
      <nav className="hdde-output-categories" aria-label="成品分类">
        {(data.categories || []).map((category) => (
          <button
            key={category.key}
            type="button"
            data-active={activeCategory === category.key}
            aria-pressed={activeCategory === category.key}
            onClick={() => setActiveCategory(category.key)}
          >
            <span>{formalCategoryLabel(category)}</span><strong>{category.count}</strong>
          </button>
        ))}
      </nav>

      <div className="hdde-output-toolbar" role="group" aria-label="记录范围、搜索、排序和清理">
        <label className="hdde-output-sort">
          <span className="sr-only">输出记录范围</span>
          <select value={listScope} onChange={(event) => setListScope(event.target.value)}>
            <option value="all">全部记录</option>
            <option value="current">当前列表（{data.scope_counts?.current ?? 0}）</option>
            <option value="history">历史列表（{data.scope_counts?.history ?? 0}）</option>
          </select>
        </label>
        <label className="hdde-output-search">
          <HddeIcon name="search" size={17} />
          <span className="sr-only">搜索成品</span>
          <input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="搜索文件名" />
        </label>
        <label className="hdde-output-sort">
          <span className="sr-only">时间顺序</span>
          <select value={sortOrder} onChange={(event) => setSortOrder(event.target.value)}>
            <option value="newest">最新在前</option>
            <option value="oldest">最早在前</option>
          </select>
        </label>
        <button id="output-cleanup-toggle" type="button" className="hdde-secondary-action hdde-output-cleanup-toggle"
          aria-expanded={cleanupOpen} aria-controls="output-cleanup-panel" onClick={() => setCleanupOpen((open) => !open)}>
          清理记录
          <HddeIcon name="chevron" size={14} />
        </button>
      </div>
      <section id="output-cleanup-panel" className="hdde-output-cleanup-panel" aria-labelledby="output-cleanup-toggle" hidden={!cleanupOpen}>
        <p>清理仅移除列表记录，已生成的图片文件会保留</p>
        {[["current", "当前列表"], ["history", "历史列表"]].map(([scope, label]) => (
          <div key={scope} className="hdde-output-cleanup-group" role="group" aria-labelledby={`output-cleanup-${scope}`}>
            <strong id={`output-cleanup-${scope}`}>{label}</strong>
            <div className="hdde-output-cleanup-actions">
              <button type="button" className="hdde-secondary-action" data-testid={`clear-missing-${scope}`} disabled={clearingRecords} onClick={() => cleanupList(scope, "missing")}>清除缺失记录</button>
              <button type="button" className="hdde-danger-action" data-testid={`clear-all-${scope}`} disabled={clearingRecords} onClick={() => cleanupList(scope, "all")}>清空{label}</button>
            </div>
          </div>
        ))}
      </section>
        </aside>
        <div className="hdde-output-browser">
          <div className="hdde-workbench-switch hdde-output-kind-tabs" role="tablist" aria-label="处理方式"
            onKeyDown={(event) => {
              if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
              event.preventDefault();
              const next = event.key === "Home" ? "single" : event.key === "End" ? "batch" : recordKind === "single" ? "batch" : "single";
              selectRecordKind(next);
              event.currentTarget.querySelector(`#output-kind-${next}`)?.focus();
            }}>
            {[["single", "单张处理"], ["batch", "批量处理"]].map(([kind, label]) => (
              <button key={kind} id={`output-kind-${kind}`} type="button" role="tab"
                aria-selected={recordKind === kind} aria-controls="output-kind-panel"
                tabIndex={recordKind === kind ? 0 : -1} onClick={() => selectRecordKind(kind)}>{label}</button>
            ))}
          </div>
        <div ref={outputListRef} id="output-kind-panel" className="hdde-output-list-column" role="tabpanel" aria-labelledby={`output-kind-${recordKind}`} tabIndex={0}
          onScroll={(event) => {
            const list = event.currentTarget;
            if (list.scrollHeight - list.scrollTop - list.clientHeight < 120) {
              pageLoaderRef.current?.({ force: true });
            }
          }}>
      {loading ? <div className="hdde-output-empty" role="status">正在读取正式输出…</div> : null}
      {!loading && !data.has_more && !visibleItems.length ? (
        <div className="hdde-output-empty hdde-output-empty--actionable">
          <span className="hdde-output-empty__icon"><HddeIcon name="outputs" size={24} /></span>
          <strong>{recordKind === "batch" ? "没有匹配的批量处理记录" : "没有匹配的单张处理记录"}</strong>
          <span>可切换处理方式或调整筛选条件。</span>
          <button type="button" className="hdde-primary-action" onClick={() => onNavigate?.("/processing")}>前往处理中心生成结果</button>
        </div>
      ) : null}

          {!loading && (visibleItems.length || data.has_more) ? (
          <section className="hdde-output-list" aria-label="真实成品列表">
            {recordKind === "single" && visibleItems.length ? (
                <OutputMasonry items={visibleItems} gallery className="hdde-output-single-grid" renderItem={(item) => (
                  <OutputRecordCard key={item.id} item={item} selected={selected?.id === item.id}
                    selectItem={cardActions.selectItem} performAction={cardActions.performAction}
                    onPreviewOpen={scheduleGalleryPreview} onPreviewClose={closeHoverPreview} />
                )} />
            ) : null}
            {recordKind === "batch" && visibleItems.length ? (
                <div className="hdde-output-batch-list">
                  {visibleItems.map((item) => (
                    <section className="hdde-output-batch" key={item.id} data-testid="output-batch-card" data-batch-id={item.batch_id} data-expanded={expandedBatches.has(item.id)}>
                      <OutputBatchSummary item={item} expanded={expandedBatches.has(item.id)}
                        onToggle={() => setExpandedBatches((current) => {
                          const next = new Set(current);
                          if (next.has(item.id)) next.delete(item.id); else next.add(item.id);
                          return next;
                        })} onRemove={() => performAction(item, "clear")} />
                      {expandedBatches.has(item.id) ? (
                        <OutputMasonry items={item.items} className="hdde-output-batch-items" label={`${item.file_name} 子项`}
                          renderItem={(child) => (
                            <OutputBatchItem key={child.batch_item_id} child={child} running={item.running} selected={selected?.id === child.id}
                              selectItem={selectItem} performAction={performAction} onContinue={openContinueProcessing}
                              onPreviewOpen={openHoverPreview} onPreviewClose={closeHoverPreview} />
                          )} />
                      ) : null}
                    </section>
                  ))}
                </div>
            ) : null}
            {data.has_more ? (
              <button type="button" className="hdde-secondary-action"
                data-testid="output-center-load-more" disabled={loadingMore}
                onClick={() => pageLoaderRef.current?.({ force: true })}>
                {loadingMore ? "正在读取…" : "加载更多成品"}
              </button>
            ) : null}
          </section>
          ) : null}
        </div>
        </div>
        <div className="hdde-output-inspector" hidden={!selected || !detailOpen}>
          {selected ? (
            <aside id="output-current-detail" className="hdde-output-detail" hidden={!detailOpen} aria-label="成品详情" data-testid="output-center-detail">
              <div>
                <div className="hdde-output-detail-heading">
                  <p className="hdde-eyebrow">当前成品</p>
                  <h2 title={selected.file_name}>{displayName(selected)}</h2>
                  {selected.available === false ? <p role="status">{selected.availability_reason || "正式文件缺失。"}</p> : null}
                </div>
                <div className="hdde-output-actions" data-testid="output-center-current-actions">
                  <button type="button" className="hdde-primary-action hdde-output-action--primary hdde-output-delivery-toggle" aria-pressed={selectedForDelivery} disabled={!selectedDeliveryEligible} aria-describedby={!selectedDeliveryEligible ? "output-delivery-reason" : undefined} onClick={() => toggleDeliveryItem(selected)}>{selectedForDelivery ? "移出交付清单" : "加入交付清单"}</button>
                  {!selectedDeliveryEligible && <p id="output-delivery-reason" role="status">{deliveryReason}</p>}
                  <button
                    type="button"
                    className="hdde-secondary-action hdde-output-action--continue"
                    data-testid="output-center-continue-action"
                    title="查看下一处理功能"
                    disabled={selected.available === false}
                    onClick={() => openContinueProcessing(selected)}
                  >
                    继续编辑
                  </button>
                  <div className="hdde-output-actions__secondary">
                    {selected.compare_available ? <button type="button" className="hdde-secondary-action hdde-output-action--compact" data-testid="output-center-compare-action" onClick={() => openCompare(selected)}>进入对比质检</button> : null}
                    <button type="button" className="hdde-secondary-action hdde-output-action--compact" disabled={selected.available === false} onClick={() => performAction(selected, "open")}>打开成品</button>
                  </div>
                  <button type="button" className="hdde-tertiary-action hdde-output-action--auxiliary" data-testid="output-center-open-folder-action" disabled={selected.available === false} onClick={() => performAction(selected, "open-folder")}><HddeIcon name="folder" size={15} />打开所在目录</button>
                  <button type="button" className="hdde-tertiary-action" onClick={() => performAction(selected, "clear")}>移除记录</button>
                </div>
                <details className="hdde-output-file-facts">
                  <summary>文件信息</summary>
                <dl>
                  <div><dt>处理类型</dt><dd>{formalProcessingLabel(selected, selected.processing_label)}</dd></div>
                  <div><dt>图片尺寸</dt><dd>{selected.width} × {selected.height}</dd></div>
                  <div><dt>格式与体积</dt><dd>{selected.format} · {formatBytes(selected.size_bytes)}</dd></div>
                  <div><dt>生成时间</dt><dd>{formatTime(selected.created_at)}</dd></div>
                </dl>
                </details>
              </div>
            </aside>
          ) : null}
        </div>
      </div>
      {hoverPreview && typeof document !== "undefined" ? createPortal(
        <div
          className="hdde-output-hover-preview"
          data-item-id={hoverPreview.item.id}
          data-placement={hoverPreview.position.placement}
          data-testid="output-hover-preview"
          aria-hidden="true"
          style={{
            left: hoverPreview.position.left,
            top: hoverPreview.position.top,
            width: hoverPreview.position.width,
            height: hoverPreview.position.height,
          }}
        >
          <img src={apiUrl(hoverPreview.item.thumbnail_url)} alt="" />
        </div>,
        document.body,
      ) : null}
      {continueDialog.item && typeof document !== "undefined" ? createPortal(
        <dialog
          ref={continueDialogRef}
          className="hdde-continue-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="continue-dialog-title"
          data-testid="continue-processing-dialog"
          onCancel={(event) => {
            event.preventDefault();
            closeContinueProcessing();
          }}
          onKeyDown={keepContinueFocus}
          onClick={(event) => {
            if (event.target !== event.currentTarget) return;
            const { left, right, top, bottom } = event.currentTarget.getBoundingClientRect();
            if (event.clientX < left || event.clientX > right || event.clientY < top || event.clientY > bottom) closeContinueProcessing();
          }}
        >
          <header>
            <div>
              <p className="hdde-eyebrow">新建独立任务</p>
              <h2 id="continue-dialog-title">选择下一处理功能</h2>
            </div>
            <button type="button" className="hdde-icon-button" aria-label="关闭继续处理" onClick={closeContinueProcessing}><HddeIcon name="close" size={18} /></button>
          </header>
          <p className="hdde-continue-dialog__source" title={continueDialog.item.file_name}>当前成品：{displayName(continueDialog.item)}</p>
          {continueDialog.error ? <div className="hdde-output-alert" role="alert">{continueDialog.error}</div> : null}
          <div className="hdde-continue-dialog__options" aria-busy={continueDialog.loading}>
            {continueDialog.options.map((processor) => (
              <button
                key={processor.key}
                type="button"
                disabled={processor.status !== "AVAILABLE"}
                data-status={processor.status}
                data-history-status={processor.historyStatus || "NOT_PROCESSED"}
                onClick={() => chooseContinueProcessor(processor)}
                data-testid={`continue-processor-${processor.key}`}
              >
                <span><HddeIcon name={processor.icon} size={20} /></span>
                <strong>{processor.label}</strong>
                <small>{processor.status === "CHECKING" || processor.status === "UNAVAILABLE" || processor.historyStatus === "PROCESSED" ? processor.reason : processor.description}</small>
                {processor.status === "AVAILABLE" ? <HddeIcon name="chevron" size={17} /> : null}
              </button>
            ))}
          </div>
          <p className="hdde-continue-dialog__note">将当前成品作为新任务继续处理，原文件不会被覆盖。</p>
        </dialog>,
        document.body,
      ) : null}
    </section>
  );
}
