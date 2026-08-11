import React, { useEffect, useMemo, useState } from "react";
import HddeIcon from "./HddeIcon.jsx";
import { HddePageHeader, HddeStatusPill } from "./HddeUI.jsx";
import { SliderCompareStage } from "./ImageSliderComparePage.jsx";
import { getFileDisplayName } from "./fileDisplayName.js";

const API_BASE = "";
const FORMAL_PROCESSING_LABELS = Object.freeze({
  "4k": "4K高清画质增强",
  color_correction: "颜色校正",
  compression: "图片压缩",
  local_retouch: "标记修整",
});

function formalProcessingLabel(itemOrType, fallback = "") {
  const item = typeof itemOrType === "object" && itemOrType ? itemOrType : {};
  const processingType = typeof itemOrType === "string" ? itemOrType : item.processing_type;
  if (processingType === "1080p") return "1080P标准增强 / 安全增强";
  return FORMAL_PROCESSING_LABELS[processingType] || fallback || processingType || "正式处理";
}

function formalCategoryLabel(category) {
  if (category.key === "1080p") return "1080P标准增强 / 安全增强";
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
  return getFileDisplayName(item?.file_name || "图片成品");
}

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
  const [loading, setLoading] = useState(!compareItemId);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedDeliveryIds, setSelectedDeliveryIds] = useState([]);

  useEffect(() => {
    if (compareItemId) return undefined;
    let active = true;
    setLoading(true);
    requestJson("/api/output-center/items")
      .then((payload) => {
        if (!active) return;
        const next = payload.data || { items: [], categories: [] };
        setData(next);
        setSelectedId((current) => current || next.items?.[0]?.id || "");
      })
      .catch((reason) => active && setError(reason.message))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [compareItemId]);

  const visibleItems = useMemo(
    () => data.items.filter((item) => activeCategory === "all" || item.processing_type === activeCategory),
    [activeCategory, data.items],
  );
  const selected = data.items.find((item) => item.id === selectedId) || visibleItems[0] || null;
  const selectedForDelivery = selected ? selectedDeliveryIds.includes(selected.id) : false;

  if (compareItemId) return <OutputCompareView itemId={compareItemId} onBack={onBackFromCompare} />;

  const performAction = async (item, action) => {
    if (!item) return;
    setError("");
    setNotice("");
    try {
      await requestJson(`/api/output-center/items/${encodeURIComponent(item.id)}/${action}`, { method: "POST" });
      setNotice(action === "open" ? "已打开当前成品。" : "已打开当前成品所在目录。");
    } catch (reason) {
      setError(reason.message);
    }
  };

  const openCompare = (item) => {
    if (!item?.compare_available || !item.compare_url) return;
    onNavigate?.(item.compare_url);
  };

  const toggleDeliveryItem = (item) => {
    if (!item) return;
    setSelectedDeliveryIds((current) => (
      current.includes(item.id)
        ? current.filter((itemId) => itemId !== item.id)
        : [...current, item.id]
    ));
  };

  const openSmartDelivery = () => {
    if (!selectedDeliveryIds.length) return;
    const selectedItems = selectedDeliveryIds
      .map((itemId) => data.items.find((item) => item.id === itemId))
      .filter(Boolean);
    const unifiedResultIds = selectedItems.map((item) => item.unified_result ? item.result_id : "");
    if (unifiedResultIds.length === selectedItems.length && unifiedResultIds.every(Boolean)) {
      onNavigate?.(`/smart-delivery?results=${encodeURIComponent(unifiedResultIds.join(","))}`);
      return;
    }
    onNavigate?.(`/smart-delivery?items=${encodeURIComponent(selectedDeliveryIds.join(","))}`);
  };

  return (
    <section className="hdde-output-page hdde-page-frame hdde-page-stack" aria-labelledby="output-center-title">
      <HddePageHeader
        eyebrow="成品与交付"
        title="输出中心"
        headingId="output-center-title"
        description="集中查看本机正式输出；这里只显示仍然存在且可以解码的真实成品。"
        meta={<HddeStatusPill tone="neutral">{data.items.length} 份可用成品</HddeStatusPill>}
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
              const first = data.items.find((item) => category.key === "all" || item.processing_type === category.key);
              setSelectedId(first?.id || "");
            }}
          >
            <span>{formalCategoryLabel(category)}</span><strong>{category.count}</strong>
          </button>
        ))}
      </nav>

      <div className="hdde-output-delivery-bar" data-active={selectedDeliveryIds.length > 0}>
        <div>
          <span>交付清单</span>
          <strong>{selectedDeliveryIds.length ? `已选择 ${selectedDeliveryIds.length} 份成品` : "从成品详情加入待交付文件"}</strong>
        </div>
        <button type="button" className="hdde-primary-action" disabled={!selectedDeliveryIds.length} onClick={openSmartDelivery}>进入智能交付</button>
      </div>

      {loading ? <div className="hdde-output-empty" role="status">正在读取正式输出…</div> : null}
      {!loading && !visibleItems.length ? (
        <div className="hdde-output-empty hdde-output-empty--actionable">
          <span className="hdde-output-empty__icon"><HddeIcon name="outputs" size={24} /></span>
          <strong>当前分类还没有正式成品</strong>
          <span>这里只有完成处理并成功登记的结果；预览和未完成任务不会显示。</span>
          <button type="button" className="hdde-primary-action" onClick={() => onNavigate?.("/processing")}>前往处理中心生成结果</button>
        </div>
      ) : null}

      {visibleItems.length ? (
        <div className="hdde-output-layout">
          <div className="hdde-output-grid" aria-label="真实成品列表">
            {visibleItems.map((item) => (
              <button
                type="button"
                className="hdde-output-card"
                data-selected={selected?.id === item.id}
                key={item.id}
                onClick={() => setSelectedId(item.id)}
              >
                <span className="hdde-output-thumb"><img src={apiUrl(item.preview_url)} alt={`${displayName(item)}预览`} loading="lazy" /></span>
                <span className="hdde-output-card-copy">
                  <strong title={item.file_name}>{displayName(item)}</strong>
                  <span>{formalProcessingLabel(item, item.processing_label)}</span>
                  <small>{item.width} × {item.height} · {formatBytes(item.size_bytes)}</small>
                </span>
              </button>
            ))}
          </div>

          {selected ? (
            <aside className="hdde-output-detail" aria-label="成品详情" data-testid="output-center-detail">
              <div className="hdde-output-detail-preview"><img src={apiUrl(selected.preview_url)} alt={`${displayName(selected)}大图预览`} /></div>
              <div>
                <p className="hdde-eyebrow">当前成品</p>
                <h2 title={selected.file_name}>{displayName(selected)}</h2>
                <dl>
                  <div><dt>处理类型</dt><dd>{formalProcessingLabel(selected, selected.processing_label)}</dd></div>
                  <div><dt>图片尺寸</dt><dd>{selected.width} × {selected.height}</dd></div>
                  <div><dt>格式与体积</dt><dd>{selected.format} · {formatBytes(selected.size_bytes)}</dd></div>
                  <div><dt>生成时间</dt><dd>{formatTime(selected.created_at)}</dd></div>
                </dl>
                <div className="hdde-output-next-step">
                  <span>下一步</span>
                  <strong>{selectedForDelivery ? "已加入本次交付" : selected.compare_available ? "先检查成品，再加入交付" : "将当前成品加入交付"}</strong>
                  <small>{selectedForDelivery ? "可从上方交付清单进入智能交付。" : "源成品保持原位，智能交付只会生成独立副本。"}</small>
                </div>
                <div className="hdde-output-actions">
                  <button type="button" className={selectedForDelivery ? "hdde-secondary-action hdde-output-delivery-toggle" : "hdde-primary-action hdde-output-delivery-toggle"} aria-pressed={selectedForDelivery} onClick={() => toggleDeliveryItem(selected)}>{selectedForDelivery ? "移出交付清单" : "加入交付清单"}</button>
                  {selected.compare_available ? <button type="button" className="hdde-secondary-action" data-testid="output-center-compare-action" onClick={() => openCompare(selected)}>进入对比质检</button> : null}
                  <button type="button" className="hdde-secondary-action" onClick={() => performAction(selected, "open")}>打开成品</button>
                  <button type="button" className="hdde-link-action" onClick={() => performAction(selected, "open-folder")}>打开所在目录</button>
                </div>
              </div>
            </aside>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
