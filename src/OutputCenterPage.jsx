import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
    throw new Error(detail?.message || payload?.message || "输出中心暂时无法读取该成品。");
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

function OutputThumbnail({ item, onPreviewOpen, onPreviewClose }) {
  const containerRef = useRef(null);
  const releaseRef = useRef(null);
  const activeUrlRef = useRef("");
  const completedUrlRef = useRef("");
  const [loadState, setLoadState] = useState("idle");
  const [loadPriority, setLoadPriority] = useState("prefetch");

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
      outputThumbnailQueue.schedule(item.id, priority, (release) => {
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
        outputThumbnailQueue.cancel(item.id);
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
      else if (!visible) outputThumbnailQueue.cancel(item.id);
    }, { root: scrollRoot, rootMargin: `${OUTPUT_THUMBNAIL_PREFETCH_MARGIN_PX}px 0px`, threshold: 0 });
    visibleObserver.observe(node);
    prefetchObserver.observe(node);
    return () => {
      disposed = true;
      visibleObserver.disconnect();
      prefetchObserver.disconnect();
      outputThumbnailQueue.cancel(item.id);
      releaseRef.current?.();
      releaseRef.current = null;
      if (activeUrlRef.current === item.thumbnail_url) activeUrlRef.current = "";
    };
  }, [item.id, item.thumbnail_url]);

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
      data-testid={`output-card-image-${item.id}`}
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
          alt={`${displayName(item)}预览`}
          decoding="async"
          fetchpriority={loadPriority === "visible" ? "high" : "low"}
          onLoad={() => settle("loaded", item.thumbnail_url)}
          onError={() => settle("failed", item.thumbnail_url)}
        />
      ) : null}
    </span>
  );
}

const OutputRecordCard = React.memo(function OutputRecordCard({
  item, selected, selectItem, performAction, onPreviewOpen, onPreviewClose,
}) {
  return (
              <section className="hdde-output-card-record" key={item.id} data-testid="output-record-card">
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
                  <small>{item.available === false ? "正式文件缺失" : `${formalProcessingLabel(item, item.processing_label)} · ${item.width} × ${item.height} · ${formatBytes(item.size_bytes)}`}</small>
                </span>
              </button>
              <button type="button" className="hdde-tertiary-action" data-remove-id={item.id} onClick={() => performAction(item, "clear")}>移除记录</button>
              </section>
  );
});

function OutputCompareView({ itemId, onBack }) {
  const [item, setItem] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    requestJson("/api/output-center/items")
      .then((payload) => {
        if (!active) return;
        const match = (payload.data?.items || []).find((candidate) => candidate.id === itemId && candidate.compare_available);
        if (!match) throw new Error("当前成品没有可靠的原图映射，无法进入前后对比。");
        setItem(match);
      })
      .catch((reason) => active && setError(reason.message))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [itemId]);

  return (
    <section className="hdde-output-compare-page" data-testid="output-center-compare">
      <header className="hdde-output-header">
        <div>
          <p className="hdde-eyebrow">对比质检</p>
          <h1>查看处理前后</h1>
          <p>{item ? `${formalProcessingLabel(item, item.processing_label)} · ${displayName(item)}` : "正在核对真实原图与成品映射。"}</p>
        </div>
        <button type="button" className="hdde-secondary-action" onClick={onBack}>返回输出中心</button>
      </header>
      {loading ? <div className="hdde-output-empty" role="status">正在读取真实成品…</div> : null}
      {error ? <div className="hdde-output-alert" role="alert">{error}</div> : null}
      {item ? (
        <div className="hdde-output-compare-layout">
          <SliderCompareStage
            originalUrl={apiUrl(item.source_preview_url)}
            enhancedUrl={apiUrl(item.preview_url)}
            fileName={displayName(item)}
            deliveryBadge="处理后"
          />
          <aside className="hdde-output-compare-notes">
            <p className="hdde-eyebrow">人工判断</p>
            <h2>按真实画面确认结果</h2>
            <p>拖动中线查看原图与成品。本页只提供人工复核入口，不自动声明画质通过。</p>
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

export default function OutputCenterPage({ compareItemId = "", onNavigate, onBackFromCompare }) {
  const [data, setData] = useState({ items: [], categories: [], skipped_unavailable_count: 0 });
  const [activeCategory, setActiveCategory] = useState("all");
  const [selectedId, setSelectedId] = useState("");
  const [selectionCleared, setSelectionCleared] = useState(false);
  const [listScope, setListScope] = useState("all");
  const [clearingRecords, setClearingRecords] = useState(false);
  const [lineage, setLineage] = useState({ loading: false, data: null, error: "" });
  const lineageRequestRef = useRef(0);
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
  const [continueDialog, setContinueDialog] = useState({ item: null, loading: false, options: [], error: "" });
  const continueEligibilityCacheRef = useRef(new Map());
  const continueRequestSequenceRef = useRef(0);
  const pageRef = useRef(null);
  const pageLoaderRef = useRef(null);
  const cleanupRefreshRef = useRef(false);
  const cardHandlersRef = useRef(null);
  const cardActions = useMemo(() => ({
    selectItem: (item) => cardHandlersRef.current.selectItem(item),
    performAction: (item, action) => cardHandlersRef.current.performAction(item, action),
  }), []);

  useEffect(() => {
    if (compareItemId) return undefined;
    let active = true;
    const controller = new AbortController();
    let nextTimer = 0;
    let pendingNextOffset = null;
    let paging = false;
    const scrollRoot = pageRef.current?.closest("main");
    const loadNextPage = ({ force = false } = {}) => {
      if (!active || paging || pendingNextOffset == null || !scrollRoot) return;
      const grid = pageRef.current?.querySelector(".hdde-output-grid");
      if (!grid || (!force && grid.getBoundingClientRect().bottom > scrollRoot.getBoundingClientRect().bottom + 120)) return;
      paging = true;
      setLoadingMore(true);
      const offset = pendingNextOffset;
      pendingNextOffset = null;
      loadRemaining(offset);
    };
    pageLoaderRef.current = loadNextPage;
    setLoadingMore(false);
    const cleanupRefresh = cleanupRefreshRef.current;
    cleanupRefreshRef.current = false;
    setLoading(!cleanupRefresh);
    setError("");
    setSelectedId("");
    if (!cleanupRefresh) setData((current) => ({ ...current, items: [], total_count: 0, has_more: false }));

    const baseParams = new URLSearchParams({
      scope: listScope,
      query: searchQuery.trim(),
      sort: sortOrder,
      category: activeCategory,
    });

    const loadRemaining = async (offset) => {
      try {
        const params = new URLSearchParams(baseParams);
        params.set("limit", String(OUTPUT_CENTER_PAGE_SIZE));
        params.set("offset", String(offset));
        const payload = await requestJson(`/api/output-center/items?${params}`, { signal: controller.signal });
        if (!active) return;
        const next = payload.data || { items: [], categories: [] };
        setData((current) => {
          const known = new Set(current.items.map((item) => item.id));
          const appended = (next.items || []).filter((item) => !known.has(item.id));
          return {
            ...next,
            items: [...current.items, ...appended],
            returned_count: current.items.length + appended.length,
          };
        });
        if (next.has_more && next.next_offset != null) {
          pendingNextOffset = next.next_offset;
        }
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
      const params = new URLSearchParams({
        scope: listScope,
        limit: String(OUTPUT_CENTER_INITIAL_PAGE_SIZE),
        offset: "0",
        query: searchQuery.trim(),
        sort: sortOrder,
        category: activeCategory,
      });
      try {
        const payload = await requestJson(`/api/output-center/items?${params}`, { signal: controller.signal });
        if (!active) return;
        const next = payload.data || { items: [], categories: [] };
        setData(next);
        setSelectedId(next.items?.[0]?.id || "");
        if (next.has_more && next.next_offset != null) {
          pendingNextOffset = next.next_offset;
        }
      } catch (reason) {
        if (active && reason?.name !== "AbortError") setError(reason.message);
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
  }, [activeCategory, compareItemId, searchQuery, sortOrder, refreshKey, listScope]);

  const visibleItems = useMemo(() => {
    const query = searchQuery.trim().toLocaleLowerCase("zh-CN");
    return data.items
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
  }, [activeCategory, data.items, searchQuery, sortOrder]);
  const selectableItems = visibleItems.flatMap((item) => item.card_type === "batch" ? item.items.filter((child) => child.available || child.file_status === "MISSING") : [item]);
  const selected = selectionCleared ? null : selectableItems.find((item) => item.id === selectedId) || selectableItems[0] || null;
  const selectedForDelivery = selected
    ? selectedDeliveryItems.some((item) => item.id === selected.id)
    : false;
  const selectedDeliveryEligible = selected?.delivery_eligible === true;
  const deliveryReason = deliveryUnavailableReason(selected);

  useEffect(() => {
    lineageRequestRef.current += 1;
    setLineage({ loading: false, data: null, error: "" });
  }, [selected?.result_id]);

  useEffect(() => {
    if (!data.items.some((item) => item.running)) return undefined;
    const timer = window.setTimeout(() => setRefreshKey((current) => current + 1), 2000);
    return () => window.clearTimeout(timer);
  }, [data.items]);

  const closeHoverPreview = useCallback(() => setHoverPreview(null), []);
  const openHoverPreview = useCallback((item, target) => {
    const image = target.querySelector("img");
    if (!image?.complete || !image.naturalWidth) return;
    const position = calculateOutputHoverPreviewPosition({
      anchorRect: target.getBoundingClientRect(),
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      imageWidth: image?.naturalWidth,
      imageHeight: image?.naturalHeight,
    });
    setHoverPreview({ item, position });
  }, []);

  useEffect(() => {
    if (!hoverPreview) return undefined;
    window.addEventListener("scroll", closeHoverPreview, true);
    window.addEventListener("resize", closeHoverPreview);
    return () => {
      window.removeEventListener("scroll", closeHoverPreview, true);
      window.removeEventListener("resize", closeHoverPreview);
    };
  }, [closeHoverPreview, hoverPreview]);

  useEffect(() => {
    if (hoverPreview && !visibleItems.some((item) => item.id === hoverPreview.item.id)) {
      closeHoverPreview();
    }
  }, [closeHoverPreview, hoverPreview, visibleItems]);

  useEffect(() => {
    if (!continueDialog.item) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setContinueDialog({ item: null, loading: false, options: [], error: "" });
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [continueDialog.item]);

  if (compareItemId) return <OutputCompareView itemId={compareItemId} onBack={onBackFromCompare} />;

  const selectItem = (item) => { setSelectedId(item.id); setSelectionCleared(false); };
  const showLineage = async (item) => {
    const sequence = ++lineageRequestRef.current;
    setLineage({ loading: true, data: null, error: "" });
    try {
      const payload = await requestJson(`/api/output-center/results/${encodeURIComponent(item.result_id)}/lineage`);
      if (sequence === lineageRequestRef.current) setLineage({ loading: false, data: payload.data, error: "" });
    } catch (reason) {
      if (sequence === lineageRequestRef.current) setLineage({ loading: false, data: null, error: reason.message });
    }
  };
  const applyRemoval = (removedIds, outcome = {}) => {
    const removed = new Set(removedIds);
    setSelectionCleared(true);
    setSelectedId("");
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
      const removedCount = removedCards.filter((card) => activeCategory === "all" || card.category === activeCategory).length;
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
      } else {
        setNotice(action === "open" ? "已打开当前成品。" : "已打开当前成品所在目录。");
      }
    } catch (reason) {
      setError(reason.message);
    }
  };

  cardHandlersRef.current = { selectItem, performAction };

  const openCompare = (item) => {
    if (!item?.compare_available || !item.compare_url) return;
    onNavigate?.(item.compare_url);
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

  const chooseContinueProcessor = (processor) => {
    if (processor?.status !== "AVAILABLE") return;
    const resultId = String(continueDialog.item?.result_id || "");
    if (!resultId) return;
    setContinueDialog({ item: null, loading: false, options: [], error: "" });
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

  return (
    <section ref={pageRef} className="hdde-output-page hdde-page-frame hdde-page-stack" aria-labelledby="output-center-title">
      <HddePageHeader
        eyebrow="成品与交付"
        title="输出中心"
        headingId="output-center-title"
        description="集中查看本机正式输出；列表会先读取文件元数据，预览图随后按需加载。"
        meta={<HddeStatusPill tone="neutral">{loading ? "正在读取成品" : `${data.total_count ?? data.items.length} 条输出记录`}</HddeStatusPill>}
      />

      {error ? <div className="hdde-output-alert" role="alert">{error}</div> : null}
      {notice ? <div className="hdde-output-notice" role="status">{notice}</div> : null}
      {data.skipped_unavailable_count ? (
        <div className="hdde-output-notice" role="status">已排除 {data.skipped_unavailable_count} 个不存在或无法读取的文件记录。</div>
      ) : null}

      <nav className="hdde-output-categories" aria-label="成品分类">
        {(data.categories || []).map((category) => (
          <button
            key={category.key}
            type="button"
            data-active={activeCategory === category.key}
            onClick={() => {
              setActiveCategory(category.key);
              setSelectedId("");
            }}
          >
            <span>{formalCategoryLabel(category)}</span><strong>{category.count}</strong>
          </button>
        ))}
      </nav>

      <nav className="hdde-output-categories" aria-label="输出记录范围">
        {[['all', '全部记录'], ['current', '当前列表'], ['history', '历史列表']].map(([scope, label]) => (
          <button key={scope} type="button" data-active={listScope === scope} onClick={() => { setListScope(scope); setSelectedId(""); }}>
            <span>{label}</span>{scope !== "all" ? <strong>{data.scope_counts?.[scope] || 0}</strong> : null}
          </button>
        ))}
      </nav>
      <div className="hdde-output-batch-actions" aria-label="清理列表记录">
        {['current', 'history'].map((scope) => <React.Fragment key={scope}>
          <button type="button" className="hdde-secondary-action" data-testid={`clear-missing-${scope}`} disabled={clearingRecords} onClick={() => cleanupList(scope, 'missing')}>{scope === 'current' ? '当前列表' : '历史列表'}：清除缺失</button>
          <button type="button" className="hdde-tertiary-action" data-testid={`clear-all-${scope}`} disabled={clearingRecords} onClick={() => cleanupList(scope, 'all')}>清空{scope === 'current' ? '当前' : '历史'}列表</button>
        </React.Fragment>)}
      </div>

      <div className="hdde-output-toolbar" role="search" aria-label="搜索和排序成品">
        <label className="hdde-output-search">
          <HddeIcon name="search" size={17} />
          <span className="sr-only">搜索成品</span>
          <input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="搜索文件名" />
        </label>
        <label className="hdde-output-sort">
          <span>时间顺序</span>
          <select value={sortOrder} onChange={(event) => setSortOrder(event.target.value)}>
            <option value="newest">最新在前</option>
            <option value="oldest">最早在前</option>
          </select>
        </label>
      </div>

      <div className="hdde-output-delivery-bar" data-active={selectedDeliveryItems.length > 0}>
        <div>
          <span>交付清单</span>
          <strong>{selectedDeliveryItems.length ? `已选择 ${selectedDeliveryItems.length} 份成品` : "从成品详情加入待交付文件"}</strong>
        </div>
        <button type="button" className="hdde-primary-action" disabled={!selectedDeliveryItems.length} onClick={openSmartDelivery}>准备交付</button>
      </div>

      {loading ? <div className="hdde-output-empty" role="status">正在读取正式输出…</div> : null}
      {!loading && !visibleItems.length ? (
        <div className="hdde-output-empty hdde-output-empty--actionable">
          <span className="hdde-output-empty__icon"><HddeIcon name="outputs" size={24} /></span>
          <strong>{searchQuery ? "没有找到匹配的成品" : "当前分类还没有正式成品"}</strong>
          <span>{searchQuery ? "请缩短关键词或切换成品分类。" : "这里只有完成处理并成功登记的结果；预览和未完成任务不会显示。"}</span>
          <button type="button" className="hdde-primary-action" onClick={() => onNavigate?.("/processing")}>前往处理中心生成结果</button>
        </div>
      ) : null}

      {visibleItems.length ? (
        <div className="hdde-output-layout">
          <div className="hdde-output-grid" aria-label="真实成品列表">
            {visibleItems.map((item) => item.card_type === "batch" ? (
              <section className="hdde-output-batch" key={item.id} data-testid="output-batch-card" data-batch-id={item.batch_id}>
                <button type="button" className="hdde-output-card hdde-output-batch-toggle" aria-expanded={expandedBatches.has(item.id)} onClick={() => setExpandedBatches((current) => {
                  const next = new Set(current);
                  if (next.has(item.id)) next.delete(item.id); else next.add(item.id);
                  return next;
                })}>
                  <span className="hdde-output-card-copy">
                    <strong>{item.file_name}</strong>
                    <small>成功 {item.summary.completed}{item.feature_type === "image_compression" ? ` · KEEP_ORIGINAL ${item.summary.keep_original}` : ""} · 失败 {item.summary.failed} · 取消 {item.summary.canceled}</small>
                    {item.running ? <small>处理中 {item.summary.processing} · 等待 {item.summary.pending}</small> : null}
                    {item.feature_type === "image_compression" ? <small>{formatBytes(item.summary.original_bytes)} → {formatBytes(item.summary.final_bytes)} · {item.summary.saved_bytes >= 0 ? "减少" : "增加"} {formatBytes(Math.abs(item.summary.saved_bytes))}（失败和取消项按原图计入）</small> : null}
                    {item.summary.unavailable ? <small>{item.summary.unavailable} 个正式文件当前不可用</small> : null}
                    <small>{formatTime(item.created_at)} · {expandedBatches.has(item.id) ? "收起子项" : "展开全部子项"}</small>
                  </span>
                </button>
                {expandedBatches.has(item.id) ? (
                  <div className="hdde-output-batch-items" aria-label={`${item.file_name} 子项`}>
                    {item.items.map((child) => (
                      <div className="hdde-output-batch-item" key={child.batch_item_id} data-testid="output-batch-item" data-status={child.status} data-result-id={child.result_id}>
                        {child.available || child.file_status === "MISSING" ? <button type="button" className="hdde-output-card hdde-output-batch-child" data-selected={selected?.id === child.id} onClick={() => selectItem(child)}>
                          <OutputThumbnail item={child} onPreviewOpen={openHoverPreview} onPreviewClose={closeHoverPreview} />
                          <span className="hdde-output-card-copy"><strong>{child.source_file_name || child.file_name}</strong><small>{child.file_status === "MISSING" ? "正式文件缺失" : `成功 · ${child.output_file_name}`}</small></span>
                        </button> : <div className="hdde-output-card-copy"><strong>{child.file_name}</strong><small>{{ COMPLETED: "文件不可用", KEEP_ORIGINAL: "KEEP_ORIGINAL · 保留原图", FAILED: "失败", CANCELED: "已取消", QUEUED: "等待处理", PROCESSING: "处理中" }[child.status] || child.status}</small><small>{child.error || child.availability_reason}</small></div>}
                        {child.available ? <div className="hdde-output-batch-actions">
                          <button type="button" className="hdde-secondary-action" onClick={() => performAction(child, "open")}>打开文件</button>
                          <button type="button" className="hdde-secondary-action" onClick={() => performAction(child, "open-folder")}>打开目录</button>
                          <button type="button" className="hdde-secondary-action" onClick={() => openContinueProcessing(child)}>继续处理</button>
                        </div> : null}
                        <button type="button" className="hdde-tertiary-action" disabled={item.running} data-remove-id={child.record_id} onClick={() => performAction(child, "clear")}>移除记录</button>
                      </div>
                    ))}
                  </div>
                ) : null}
                <button type="button" className="hdde-tertiary-action" disabled={item.running} data-remove-id={item.id} onClick={() => performAction(item, "clear")}>移除记录</button>
              </section>
            ) : (
              <OutputRecordCard key={item.id} item={item} selected={selected?.id === item.id}
                selectItem={cardActions.selectItem} performAction={cardActions.performAction}
                onPreviewOpen={openHoverPreview} onPreviewClose={closeHoverPreview} />
            ))}
            {data.has_more ? (
              <button type="button" className="hdde-secondary-action" style={{ gridColumn: "1 / -1" }}
                data-testid="output-center-load-more" disabled={loadingMore}
                onClick={() => pageLoaderRef.current?.({ force: true })}>
                {loadingMore ? "正在读取…" : "加载更多成品"}
              </button>
            ) : null}
          </div>

          {selected ? (
            <aside className="hdde-output-detail" aria-label="成品详情" data-testid="output-center-detail">
              <div>
                <p className="hdde-eyebrow">当前成品</p>
                <h2 title={selected.file_name}>{displayName(selected)}</h2>
                {selected.available === false ? <p role="status">{selected.availability_reason || "正式文件缺失。"}</p> : null}
                <dl>
                  <div><dt>处理类型</dt><dd>{formalProcessingLabel(selected, selected.processing_label)}</dd></div>
                  <div><dt>图片尺寸</dt><dd>{selected.width} × {selected.height}</dd></div>
                  <div><dt>格式与体积</dt><dd>{selected.format} · {formatBytes(selected.size_bytes)}</dd></div>
                  <div><dt>生成时间</dt><dd>{formatTime(selected.created_at)}</dd></div>
                </dl>
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
                  {selected.unified_result ? <button type="button" className="hdde-secondary-action" data-testid="output-center-lineage-action" onClick={() => showLineage(selected)}>查看编辑链</button> : null}
                  <div className="hdde-output-actions__secondary">
                    {selected.compare_available ? <button type="button" className="hdde-secondary-action hdde-output-action--compact" data-testid="output-center-compare-action" onClick={() => openCompare(selected)}>进入对比质检</button> : null}
                    <button type="button" className="hdde-secondary-action hdde-output-action--compact" disabled={selected.available === false} onClick={() => performAction(selected, "open")}>打开成品</button>
                  </div>
                  <button type="button" className="hdde-tertiary-action hdde-output-action--auxiliary" data-testid="output-center-open-folder-action" disabled={selected.available === false} onClick={() => performAction(selected, "open-folder")}><HddeIcon name="folder" size={15} />打开所在目录</button>
                  <button type="button" className="hdde-tertiary-action" onClick={() => performAction(selected, "clear")}>移除记录</button>
                </div>
                {lineage.loading ? <p role="status">正在读取编辑链…</p> : null}
                {lineage.error ? <p role="alert">{lineage.error}</p> : null}
                {lineage.data ? <section data-testid="output-center-lineage" aria-label="编辑结果追踪">
                  <strong>共 {lineage.data.round_count} 轮 · 初始输入：{lineage.data.initial_source.file_name || "已登记来源"}</strong>
                  <ol>{lineage.data.items.map((round) => <li key={round.result_id} data-result-id={round.result_id}>
                    <p>第 {round.round} 轮 · {formalProcessingLabel(round.feature_key)} · {round.file_name}</p>
                    <small>Task：{round.task_id} · Result：{round.result_id}</small>
                    <p title={round.source_sha256}>输入SHA：{round.source_sha256.slice(0, 12) || "历史记录未提供"}</p>
                  </li>)}</ol>
                </section> : null}
              </div>
            </aside>
          ) : null}
        </div>
      ) : null}
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
          }}
        >
          <img src={apiUrl(hoverPreview.item.thumbnail_url)} alt="" />
        </div>,
        document.body,
      ) : null}
      {continueDialog.item && typeof document !== "undefined" ? createPortal(
        <div
          className="hdde-continue-dialog-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setContinueDialog({ item: null, loading: false, options: [], error: "" });
          }}
        >
          <section className="hdde-continue-dialog" role="dialog" aria-modal="true" aria-labelledby="continue-dialog-title" data-testid="continue-processing-dialog">
            <header>
              <div>
                <p className="hdde-eyebrow">新建独立任务</p>
                <h2 id="continue-dialog-title">选择下一处理功能</h2>
              </div>
              <button type="button" className="hdde-icon-button" aria-label="关闭继续处理" onClick={() => setContinueDialog({ item: null, loading: false, options: [], error: "" })}><HddeIcon name="close" size={18} /></button>
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
          </section>
        </div>,
        document.body,
      ) : null}
    </section>
  );
}
