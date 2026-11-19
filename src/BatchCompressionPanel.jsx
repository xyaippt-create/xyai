import React, { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { HddeSectionHeader, HddeStatusPill } from "./HddeUI.jsx";
import { compressionBatch, summarizeCompressionBatch } from "./batchCompression.js";
import { TARGET_FORMAT_OPTIONS, targetFormatHelper } from "./compressionParams.js";
import {
  BATCH_DELIVERY_STATUS,
  blocksBatchDeliverySelection,
  canSelectBatchDeliveryItem,
  deliverBatchResults,
  loadBatchDeliveryEligibility,
  loadBatchDeliveryStates,
  readBatchImportProgress,
  requestBatchDeliveryJson,
  resolveBatchMediaUrl,
  saveBatchDeliveryStates,
} from "./batchDelivery.js";
import "./BatchCompressionPanel.css";

const STATES = {
  QUEUED: ["等待处理", "neutral"], PROCESSING: ["处理中", "info"], CANCELED: ["已取消", "neutral"],
  COMPLETED: ["压缩成品", "positive"], KEEP_ORIGINAL: ["保留原图", "neutral"], FAILED: ["失败", "danger"],
};

function itemFailureMessage(item) {
  return {
    SOURCE_UNAVAILABLE: "批次原图已丢失或无法读取，请重新选择有效的原图。",
    SOURCE_IDENTITY_MISMATCH: "批次原图内容已变化，请重新选择有效的原图。",
    BATCH_OUTPUT_DIRECTORY_CHANGED: "压缩目录与创建批次时不同，请恢复原目录或新建批次。",
  }[item.error] || item.error;
}

function deliveryKey(item) {
  return item.status === "KEEP_ORIGINAL" ? item.id : item.resultId;
}

const EMPTY_ELIGIBILITY = { outputItems: {}, originalIds: new Set() };

function bytes(value) {
  if (value === null || value === undefined) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(2)} MB`;
}

function SelectAllCheckbox({ checked, mixed, disabled, onChange }) {
  const inputRef = useRef(null);
  useEffect(() => {
    if (inputRef.current) inputRef.current.indeterminate = mixed;
  }, [mixed]);
  return (
    <input ref={inputRef} type="checkbox" aria-label="全选当前可交付项" checked={checked}
      disabled={disabled} onChange={onChange} />
  );
}

function BatchThumbnail({ item, onOpen }) {
  const button = useRef(null);
  const [visible, setVisible] = useState(false);
  const [failedUrl, setFailedUrl] = useState("");
  const thumbnailUrl = resolveBatchMediaUrl(item.sourceThumbnailUrl || "");
  useEffect(() => {
    if (visible || !thumbnailUrl || !button.current) return undefined;
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return undefined;
    }
    const node = button.current;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) setVisible(true);
    }, { root: node.closest("main"), rootMargin: "0px 0px 220px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, [thumbnailUrl, visible]);
  if (!item.sourcePreviewUrl) {
    return <span className="hdde-batch-thumbnail hdde-batch-thumbnail--empty" aria-label="原图预览不可用">不可用</span>;
  }
  const failed = !thumbnailUrl || failedUrl === thumbnailUrl;
  return (
    <button ref={button} type="button" className="hdde-batch-thumbnail" aria-label={`查看 ${item.name} 大图预览`} onClick={onOpen}>
      {visible && !failed ? <img src={thumbnailUrl} alt="" decoding="async" onError={() => setFailedUrl(thumbnailUrl)} />
        : failed ? <span title="缩略图不可用">不可用</span> : null}
    </button>
  );
}

function deliveryUnavailableReason(item, outputItem, outputLoading, deliveryState) {
  if (deliveryState?.status === BATCH_DELIVERY_STATUS.COMPLETED) return "当前批次已交付成功";
  if (deliveryState?.status === BATCH_DELIVERY_STATUS.UNKNOWN) return "正在确认交付结果，不会创建新的交付请求";
  if (deliveryState?.invalidatesEligibility) return deliveryState.reason || "成品已无法交付，请在输出中心核对文件。";
  if (outputLoading && ["COMPLETED", "KEEP_ORIGINAL"].includes(item.status)) return "正在核对本项能否交付。";
  if (item.status === "KEEP_ORIGINAL") return "原图无法读取或校验，请重新选择有效的原图。";
  if (item.status !== "COMPLETED") return itemFailureMessage(item) || "本项没有可交付的压缩成品。";
  if (!outputItem) return "输出中心未找到这份成品，请核对保存位置。";
  if (outputItem.available === false) return outputItem.availability_reason || "成品缺失或校验失败。";
  if (!outputItem.delivery_eligible) return outputItem.delivery_failure_reason || "成品无法交付，请在输出中心核对文件。";
  return "当前项不可交付";
}

export default function BatchCompressionPanel({ onNavigate }) {
  const inputRef = useRef(null);
  const { items, running, batchId, loading, state, control, error, targetFormat, allowOpaquePngToJpeg, serverSessionId } = useSyncExternalStore(
    compressionBatch.subscribe,
    compressionBatch.getSnapshot,
  );
  const summary = summarizeCompressionBatch(items);
  const finished = summary.completed + summary.kept + summary.failed + summary.canceled;
  const locked = Boolean(batchId) || loading;
  const activeItems = items.filter((item) => item.status === "PROCESSING");
  const [importProgress, setImportProgress] = useState(null);
  const [eligibility, setEligibility] = useState(null);
  const [outputError, setOutputError] = useState("");
  const [selectedResultIds, setSelectedResultIds] = useState([]);
  const [deliveryStates, setDeliveryStates] = useState({});
  const [preview, setPreview] = useState(null);
  const [deliveryProgress, setDeliveryProgress] = useState(null);
  const [deliveryReport, setDeliveryReport] = useState(null);
  const [recentBatches, setRecentBatches] = useState([]);
  const [recentError, setRecentError] = useState("");
  const [openError, setOpenError] = useState("");
  const openFolder = async (path) => {
    setOpenError("");
    try {
      await requestBatchDeliveryJson(path, { method: "POST" });
    } catch (reason) {
      setOpenError(reason.message || "打开目录失败，请核对保存位置是否可访问。");
    }
  };
  const restoredUnknownResultIds = useRef(new Set());
  const deliveryRunning = useRef(false);
  const terminal = Boolean(batchId)
    && !running
    && summary.waiting === 0
    && !["IMPORTING", "RESTORING", "PAUSING", "CANCELING"].includes(state);
  const retryableCount = items.filter((item) => item.status === "FAILED" && item.retryable).length;
  const resultKey = items.filter((item) => ["COMPLETED", "KEEP_ORIGINAL"].includes(item.status)).map(deliveryKey).join("|");
  const eligibilityKey = `${batchId}:${serverSessionId}:${terminal}:${resultKey}`;
  const knownEligibility = eligibility?.batchId === batchId ? eligibility : EMPTY_ELIGIBILITY;
  const { outputItems } = knownEligibility;
  const eligibilityReady = !outputError && eligibility?.key === eligibilityKey;

  useEffect(() => {
    void compressionBatch.refresh();
    const timer = window.setInterval(() => void compressionBatch.refresh(), 1200);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (batchId || items.length) return undefined;
    let active = true;
    setRecentError("");
    compressionBatch.recent().then((batches) => {
      if (active) setRecentBatches(batches);
    }).catch(() => {
      if (active) setRecentError("无法读取批次记录。请检查正式目录后重新打开此页。");
    });
    return () => { active = false; };
  }, [batchId, items.length]);

  useEffect(() => {
    if (!batchId || state !== "IMPORTING") {
      setImportProgress(null);
      return undefined;
    }
    let active = true;
    let timer = 0;
    const observe = async () => {
      try {
        const next = await readBatchImportProgress(batchId);
        if (active && next) setImportProgress(next);
      } catch {
        // The authoritative POST/refresh path owns error and recovery state.
      }
      if (active) timer = window.setTimeout(observe, 250);
    };
    void observe();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [batchId, state]);

  useEffect(() => {
    const restored = loadBatchDeliveryStates(batchId);
    restoredUnknownResultIds.current = new Set(
      Object.values(restored).filter((item) => item.status === BATCH_DELIVERY_STATUS.UNKNOWN).map((item) => item.resultId),
    );
    setSelectedResultIds([]);
    setDeliveryStates(restored);
    setDeliveryReport(null);
    setDeliveryProgress(null);
  }, [batchId]);

  useEffect(() => {
    setOutputError("");
    if (!batchId || !resultKey) return undefined;
    let active = true;
    let timer;
    const refreshEligibility = async () => {
      try {
        const next = await loadBatchDeliveryEligibility(batchId);
        if (!active) return;
        setEligibility({ ...next, batchId, key: eligibilityKey });
        setOutputError("");
      } catch (reason) {
        if (active) setOutputError(reason?.message || "无法核对批量交付资格，正在重新连接。");
      }
      if (active) timer = window.setTimeout(refreshEligibility, 5000);
    };
    void refreshEligibility();
    return () => { active = false; window.clearTimeout(timer); };
  }, [batchId, eligibilityKey, resultKey]);

  const blockedDeliverySet = useMemo(() => new Set(
    Object.values(deliveryStates).filter(blocksBatchDeliverySelection).map((item) => item.resultId),
  ), [deliveryStates]);
  const eligibleItems = useMemo(() => items.filter((item) => (
    canSelectBatchDeliveryItem(item, knownEligibility, blockedDeliverySet)
  )), [blockedDeliverySet, items, knownEligibility]);
  const eligibleIds = useMemo(() => new Set(eligibleItems.map(deliveryKey)), [eligibleItems]);
  const selectedItems = useMemo(() => items.filter((item) => selectedResultIds.includes(deliveryKey(item)) && eligibleIds.has(deliveryKey(item))), [eligibleIds, items, selectedResultIds]);
  const unknownDeliveryItems = useMemo(() => items.flatMap((item) => {
    const resultId = deliveryKey(item);
    const deliveryState = deliveryStates[resultId];
    if (deliveryState?.status !== BATCH_DELIVERY_STATUS.UNKNOWN) return [];
    const original = item.status === "KEEP_ORIGINAL";
    return [{
      resultId,
      name: item.name,
      original,
      outputSha256: original ? item.sourceSha256 : item.outputSha256,
      idempotencyKey: deliveryState.idempotencyKey,
    }];
  }), [deliveryStates, items]);
  const unknownDeliveryKey = unknownDeliveryItems.map((item) => `${item.resultId}:${item.idempotencyKey}`).join("|");
  const selectedAll = eligibleItems.length > 0 && selectedItems.length === eligibleItems.length;
  const selectedMixed = selectedItems.length > 0 && !selectedAll;

  useEffect(() => {
    if (!eligibilityReady) return;
    setSelectedResultIds((current) => current.filter((resultId) => eligibleIds.has(resultId)));
  }, [eligibilityReady, eligibleIds]);

  useEffect(() => {
    if (!preview) return undefined;
    const close = (event) => {
      if (event.key !== "Escape") return;
      setPreview(null);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [preview]);

  const toggleItem = (item) => {
    const id = deliveryKey(item);
    if (outputError || !eligibleIds.has(id)) return;
    setSelectedResultIds((current) => (
      current.includes(id)
        ? current.filter((resultId) => resultId !== id)
        : [...current, id]
    ));
  };

  const applyDeliveryItemState = useCallback((next) => {
    if (!batchId || !next?.resultId) return;
    if (
      next.status === BATCH_DELIVERY_STATUS.COMPLETED
      || next.status === BATCH_DELIVERY_STATUS.UNKNOWN
      || next.invalidatesEligibility
    ) {
      setSelectedResultIds((current) => current.filter((resultId) => resultId !== next.resultId));
    }
    setDeliveryStates((current) => {
      const updated = { ...current, [next.resultId]: next };
      saveBatchDeliveryStates(batchId, updated);
      return updated;
    });
  }, [batchId]);

  const runDelivery = useCallback(async (requested, { recovery = false } = {}) => {
    if (!requested.length || deliveryProgress) return null;
    setDeliveryReport(null);
    setDeliveryProgress({ current: 0, total: requested.length, name: "", phase: recovery ? "confirm" : "preflight" });
    const report = await deliverBatchResults(requested, {
      onProgress: (progress) => setDeliveryProgress(recovery ? { ...progress, phase: "confirm" } : progress),
      onItemState: applyDeliveryItemState,
      confirmExisting: true,
      batchId,
    });
    const noLongerSelectable = report.items.filter((item) => (
      item.status === BATCH_DELIVERY_STATUS.COMPLETED
      || item.status === BATCH_DELIVERY_STATUS.UNKNOWN
      || item.invalidatesEligibility
    )).map((item) => item.resultId);
    setSelectedResultIds((current) => current.filter((resultId) => !noLongerSelectable.includes(resultId)));
    setDeliveryReport(report);
    setDeliveryProgress(null);
    return report;
  }, [applyDeliveryItemState, batchId, deliveryProgress]);

  const beginDelivery = async () => {
    if (!terminal || !eligibilityReady || deliveryRunning.current || !selectedItems.length || deliveryProgress) return;
    const requested = selectedItems.map((item) => ({
      resultId: deliveryKey(item),
      name: item.name,
      original: item.status === "KEEP_ORIGINAL",
      outputSha256: item.status === "KEEP_ORIGINAL" ? item.sourceSha256 : item.outputSha256,
      idempotencyKey: `delivery_request_${item.id}`,
    }));
    deliveryRunning.current = true;
    try {
      await runDelivery(requested);
    } finally {
      deliveryRunning.current = false;
    }
  };

  const confirmUnknownDeliveries = useCallback(async () => {
    if (!unknownDeliveryItems.length || deliveryProgress || deliveryRunning.current) return;
    deliveryRunning.current = true;
    try {
      await runDelivery(unknownDeliveryItems, { recovery: true });
    } finally {
      deliveryRunning.current = false;
    }
  }, [deliveryProgress, runDelivery, unknownDeliveryItems]);

  useEffect(() => {
    if (!terminal || !unknownDeliveryKey || deliveryProgress || deliveryRunning.current) return;
    const restored = unknownDeliveryItems.filter((item) => restoredUnknownResultIds.current.has(item.resultId));
    if (!restored.length) return;
    restored.forEach((item) => restoredUnknownResultIds.current.delete(item.resultId));
    deliveryRunning.current = true;
    void runDelivery(restored, { recovery: true }).finally(() => {
      deliveryRunning.current = false;
    });
  }, [deliveryProgress, runDelivery, terminal, unknownDeliveryItems, unknownDeliveryKey]);

  const preparedCount = Math.min(summary.total, importProgress?.preparedCount || 0);
  const activeOrdinal = Math.min(summary.total, finished + Math.max(1, summary.processing));
  const savedPercent = summary.originalBytes ? summary.savedBytes * 100 / summary.originalBytes : 0;
  const showProgress = items.length > 0 && !terminal;
  const isPaused = state === "PAUSED";
  const isPreparing = state === "IMPORTING";
  const isRestoring = state === "RESTORING";

  let phaseTitle = `${summary.waiting} 张图片待处理`;
  let phaseDetail = "确认列表后开始；每张图片仍独立复用单图智能压缩。";
  if (isPreparing) {
    phaseTitle = `正在准备 ${preparedCount}/${summary.total}`;
    phaseDetail = importProgress ? `正在保存：${importProgress.preparingName || "正在完成批次登记"}` : "正在登记批次，尚未开始压缩。";
  } else if (isRestoring) {
    phaseTitle = "正在恢复已登记批次";
    phaseDetail = "只按已保存的 batch_id 读取状态，不会重新提交图片。";
  } else if (isPaused) {
    phaseTitle = `已暂停 · ${finished}/${summary.total}`;
    phaseDetail = "未完成项保持等待；继续后只处理尚未完成的图片。";
  } else if (state === "PAUSING") {
    phaseTitle = `正在暂停 · ${finished}/${summary.total}`;
    phaseDetail = "当前图片安全完成后停止启动新任务。";
  } else if (state === "CANCELING") {
    phaseTitle = `正在取消 · ${finished}/${summary.total}`;
    phaseDetail = "未开始项已取消，正在等待当前图片安全收尾。";
  } else if (batchId) {
    phaseTitle = `正在压缩 ${activeOrdinal}/${summary.total}`;
    phaseDetail = activeItems.length ? `当前：${activeItems.map((item) => item.name).join("、")}` : "正在调度下一张图片。";
  }

  return (
    <section className="hdde-batch-compression" data-testid="batch-compression" aria-label="批量图片压缩">
        <section className="hdde-batch-compression-format" aria-labelledby="batch-format-heading">
          <div className="hdde-batch-compression-format__heading">
            <h3 id="batch-format-heading">压缩设置</h3>
            {batchId ? <span>本批次设置已锁定</span> : null}
          </div>
          <div className="hdde-batch-compression-format__fields">
            <label className="hdde-compression-target-field" data-testid="batch-target-format-field">
              <span>目标格式</span>
              <select
                aria-describedby="batch-target-format-help"
                data-testid="batch-target-format"
                value={targetFormat}
                onChange={(event) => compressionBatch.setTargetFormat(event.target.value)}
                disabled={locked}
              >
                {TARGET_FORMAT_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
              <small id="batch-target-format-help" className="hdde-compression-field-helper" data-testid="batch-target-format-helper">
                {targetFormat === "SMART_COMPRESSION" ? "按画质和体积择优。" : targetFormatHelper(targetFormat)}
              </small>
            </label>
            {targetFormat === "SMART_COMPRESSION" ? <label className="hdde-batch-compression-conversion">
              <input type="checkbox" data-testid="batch-allow-opaque-png-to-jpeg" checked={allowOpaquePngToJpeg}
                aria-labelledby="batch-conversion-label" aria-describedby="batch-conversion-help"
                disabled={locked} onChange={(event) => compressionBatch.setAllowOpaquePngToJpeg(event.target.checked)} />
              <span>
                <strong id="batch-conversion-label">允许不透明 PNG 转 JPG</strong>
                <small id="batch-conversion-help">JPG 通过画质检查，且比保留原格式的结果更小时才会采用。透明 PNG 保留透明度。</small>
              </span>
            </label> : null}
          </div>
        </section>
      <section className="hdde-batch-compression-list-card hdde-processing-panel" aria-labelledby="batch-compression-list-title">
        <input ref={inputRef} type="file" multiple hidden accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" disabled={locked}
          data-testid="batch-compression-files" onChange={(event) => { compressionBatch.add(event.currentTarget.files); event.currentTarget.value = ""; }} />
        <HddeSectionHeader
          headingId="batch-compression-list-title"
          title={<>图片列表 <span>{summary.total} 张</span></>}
          description="逐张使用同一套压缩设置，成品保存到系统设置的图片压缩目录。"
          aside={items.length || state === "BATCH_NOT_FOUND" ? <div className="hdde-batch-compression-actions">
            {items.length ? <button type="button" className="hdde-secondary-action" onClick={() => inputRef.current?.click()} disabled={locked}>添加图片</button> : null}
            <button type="button" className="hdde-link-action" onClick={() => compressionBatch.clear()} disabled={loading || running || (batchId && summary.waiting > 0) || (!items.length && state !== "BATCH_NOT_FOUND")}>清空列表</button>
          </div> : null}
        />

        {items.length ? <div className="hdde-batch-compression-table-wrap">
        <table className="hdde-batch-compression-table" data-testid="batch-compression-list">
          <thead><tr><th scope="col" className="hdde-batch-compression-select"><SelectAllCheckbox checked={selectedAll} mixed={selectedMixed} disabled={!eligibleItems.length || Boolean(deliveryProgress || outputError)} onChange={() => setSelectedResultIds(selectedAll ? [] : eligibleItems.map(deliveryKey))} /></th>
            <th scope="col" className="hdde-batch-compression-preview-column">缩略图</th><th scope="col">文件名</th><th scope="col">状态</th><th scope="col">体积变化</th><th scope="col">操作</th></tr></thead>
          <tbody>{items.map((item) => {
            const outputItem = outputItems[item.resultId];
            const id = deliveryKey(item);
            const deliveryState = deliveryStates[id];
            const eligible = eligibleIds.has(id);
            const sourceFormat = item.sourceFormat === "JPEG" ? "JPG" : item.sourceFormat;
            const outputFormat = item.outputFormat === "JPEG" ? "JPG" : item.outputFormat;
            const outputFolder = item.output_path?.split(/[\\/]/).slice(0, -1).filter(Boolean).slice(-2).join(" / ");
            const sourcePreviewUrl = resolveBatchMediaUrl(item.sourcePreviewUrl || "");
            const deliveryLabel = deliveryState?.status === BATCH_DELIVERY_STATUS.COMPLETED
              ? ["已交付", "positive"]
              : deliveryState?.status === BATCH_DELIVERY_STATUS.UNKNOWN
                ? ["正在确认", "info"]
                : deliveryState?.status === BATCH_DELIVERY_STATUS.FAILED_DEFINITE
                  ? ["交付失败", "danger"]
                  : null;
            return <tr key={item.id} data-status={item.status} data-item-id={item.id}>
              <td className="hdde-batch-compression-select"><input type="checkbox" aria-label={`选择 ${item.name}`} checked={eligible && selectedResultIds.includes(id)} aria-invalid={deliveryState?.invalidatesEligibility || Boolean(outputItem?.delivery_failure_code) || undefined} disabled={!eligible || Boolean(deliveryProgress || outputError)} title={outputError || (eligible ? "加入批量交付" : deliveryUnavailableReason(item, outputItem, !eligibilityReady, deliveryState))} onChange={() => toggleItem(item)} /></td>
              <td><BatchThumbnail item={item} onOpen={() => {
                if (!sourcePreviewUrl) return;
                // Browsers can reuse a decoded image within the current document.
                // Each open must revalidate the bound original with the backend.
                const url = new URL(sourcePreviewUrl, window.location.href);
                url.searchParams.set("open", crypto.randomUUID());
                setPreview({ name: item.name, url: url.href });
              }} /></td>
              <td className="hdde-batch-compression-name"><strong title={item.name}>{item.name}</strong>{item.error ? <p className="hdde-batch-compression-error">{itemFailureMessage(item)}</p> : null}
                {deliveryState?.status === BATCH_DELIVERY_STATUS.UNKNOWN ? <p className="hdde-batch-delivery-state" role="status">正在确认交付结果…</p> : null}
                {deliveryState?.status === BATCH_DELIVERY_STATUS.FAILED_DEFINITE ? <p className="hdde-batch-compression-error" role="alert">{deliveryState.reason}（{deliveryState.code}）</p> : null}
                {!deliveryState && outputItem?.delivery_eligible === false && outputItem?.delivery_failure_code ? <p className="hdde-batch-compression-error" role="alert">{outputItem.delivery_failure_reason || "成品已无法交付，请在输出中心核对文件。"}（{outputItem.delivery_failure_code}）</p> : null}
                {item.status === "COMPLETED" && item.output_path ? <small className="hdde-batch-compression-location" title={item.output_path}>保存至 · {outputFolder || "输出目录"}</small> : null}
                {outputFormat ? <small data-testid="batch-result-format">{sourceFormat && sourceFormat !== outputFormat ? `${sourceFormat} → ${outputFormat}` : outputFormat}</small> : null}
                {item.status === "KEEP_ORIGINAL" && eligibilityReady && !eligible && !deliveryState ? <p className="hdde-batch-compression-error">{deliveryUnavailableReason(item, outputItem, false, null)}</p> : null}
              </td>
              <td><HddeStatusPill tone={(deliveryLabel || STATES[item.status])[1]}>{(deliveryLabel || STATES[item.status])[0]}</HddeStatusPill></td>
              <td className="hdde-batch-compression-size-change">
                <span>{bytes(item.originalBytes)} <span aria-hidden="true">→</span> {bytes(item.finalBytes)}</span>
                {item.savedPercent === null ? null : <small>{item.savedPercent.toFixed(1)}%</small>}
              </td>
              <td><div className="hdde-batch-compression-actions">
                {outputItem?.id && outputItem.available !== false ? <button type="button" className="hdde-link-action" onClick={() => void openFolder(`/api/output-center/items/${encodeURIComponent(outputItem.id)}/open-folder`)}>打开所在目录</button> : null}
                {item.status === "COMPLETED" ? <button type="button" className="hdde-link-action" disabled={!onNavigate || !terminal || !eligibilityReady || !eligible} title={!terminal ? "批次结束后可交付" : eligible ? "为这份压缩成品生成交付副本" : deliveryUnavailableReason(item, outputItem, !eligibilityReady, deliveryState)} onClick={() => onNavigate?.(`/smart-delivery?results=${encodeURIComponent(item.resultId)}`)}>生成交付副本</button> : null}
                {!batchId ? <button type="button" className="hdde-link-action" aria-label={`移除 ${item.name}`} disabled={locked} onClick={() => compressionBatch.remove(item.id)}>移除</button> : null}
              </div></td>
            </tr>;
          })}</tbody>
        </table>
        </div> : <div className="hdde-batch-compression-empty">
          <div className="hdde-batch-compression-empty__copy">
            <svg aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="4" /><path d="M12 8v8m-4-4h8" />
            </svg>
            <div><strong>选择要压缩的图片</strong><p>可一次选择多张 PNG、JPG、JPEG 或 WebP。</p></div>
          </div>
          <button type="button" className="hdde-primary-action" onClick={() => inputRef.current?.click()} disabled={locked}>添加图片</button>
        </div>}
        {!batchId && !items.length && recentBatches.length ? <label className="hdde-batch-compression-restore">
          <span>恢复批次</span>
          <select data-testid="batch-compression-restore" value="" onChange={(event) => void compressionBatch.restore(event.target.value)}>
            <option value="">选择已保存的批次</option>
            {recentBatches.map((batch) => <option key={batch.batchId} value={batch.batchId}>{new Date(batch.createdAt * 1000).toLocaleString()} · {batch.firstName} · {batch.count} 张</option>)}
          </select>
        </label> : null}
        {!batchId && !items.length && recentError ? <p role="status">{recentError}</p> : null}
      </section>

      <aside className="hdde-batch-compression-status" aria-label="批量进度与结果">
        {error || openError ? <p role="alert" className="hdde-batch-compression-error hdde-batch-compression-error--global">{error || openError}</p> : null}

        {showProgress ? <section className="hdde-batch-compression-progress" data-phase={isPreparing ? "preparing" : isPaused ? "paused" : batchId ? "processing" : "waiting"} aria-label="批量处理进度">
        <div className="hdde-batch-compression-progress__lead">
          <div><strong>{phaseTitle}</strong><p role="status" aria-live="polite">{phaseDetail}</p></div>
          <div className="hdde-batch-compression-actions">
            {!batchId ? <button type="button" className="hdde-primary-action" data-testid="batch-compression-start" disabled={loading || !summary.waiting} onClick={() => void compressionBatch.start()}>{loading ? "正在检查输出空间…" : "开始批量压缩"}</button> : null}
            {batchId && isPaused && summary.waiting > 0 ? <button type="button" className="hdde-primary-action" data-testid="batch-compression-resume" disabled={loading} onClick={() => void compressionBatch.control("resume")}>继续</button> : null}
            {batchId && !isPreparing && !isRestoring && control === "RUNNING" && (summary.waiting > 0 || summary.processing > 0) ? <button type="button" className="hdde-secondary-action" data-testid="batch-compression-pause" disabled={loading} onClick={() => void compressionBatch.control("pause")}>暂停</button> : null}
            {batchId && !isPreparing && control !== "CANCELED" && (summary.waiting > 0 || summary.processing > 0) ? <button type="button" className="hdde-link-action" data-testid="batch-compression-cancel" disabled={loading} onClick={() => { if (window.confirm("取消未开始的图片？当前图片会安全完成，已生成的成品保留。")) void compressionBatch.control("cancel"); }}>取消批次</button> : null}
          </div>
        </div>
        <div className="hdde-batch-compression-counts" role="status" aria-live="polite" data-testid="batch-compression-counts">
          <span>总数 <strong>{summary.total}</strong></span><span>已完成 <strong>{summary.completed}</strong></span><span>处理中 <strong>{summary.processing}</strong></span>
          <span>保留原图 <strong>{summary.kept}</strong></span><span>失败 <strong>{summary.failed}</strong></span><span>已取消 <strong>{summary.canceled}</strong></span>
        </div>
        {isPreparing ? <progress max={summary.total || 1} value={preparedCount} aria-label="批次原图保存进度" /> : null}
        {batchId && !isPreparing && !isRestoring ? <progress max={summary.total || 1} value={finished} aria-label="批量图片压缩处理进度" /> : null}
        {activeItems.length ? <p className="hdde-batch-compression-current" data-testid="batch-compression-current">{activeItems.map((item) => `${item.name} · ${item.elapsedSeconds || 0} 秒`).join("；")}。大图包含全尺寸质量验证，请等待安全完成。</p> : null}
        {!terminal && resultKey ? <p className="hdde-batch-compression-summary__note">已选 {selectedItems.length} 项。可先勾选已通过校验的图片，批次结束后可直接交付。</p> : null}
        {!terminal && outputError ? <p className="hdde-batch-compression-error" role="alert">{outputError}</p> : null}
        </section> : null}
        {!showProgress && !terminal ? (
          <div className="hdde-batch-compression-progress"><strong>进度与结果</strong><p>添加图片后，可在这里开始压缩并查看结果。</p></div>
        ) : null}
      {terminal ? <section className="hdde-batch-compression-summary hdde-processing-panel" aria-label="批量处理结果" data-testid="batch-compression-summary">
        <div className="hdde-batch-compression-summary__header"><HddeSectionHeader
          eyebrow="批量处理完成"
          title={`${summary.total} 张图片已结束处理`}
          description={`成功 ${summary.completed} · 保留原图 ${summary.kept} · 失败 ${summary.failed} · 已取消 ${summary.canceled}`}
          aside={<div className="hdde-batch-compression-summary__actions"><button type="button" className="hdde-primary-action" data-testid="batch-delivery-open" disabled={!eligibilityReady || !selectedItems.length || Boolean(deliveryProgress)} onClick={() => void beginDelivery()}>批量交付（{selectedItems.length}）</button>
            {retryableCount ? <button type="button" className="hdde-secondary-action" data-testid="batch-compression-retry" disabled={loading || Boolean(deliveryProgress)} onClick={() => void compressionBatch.control("retry_failed")}>重试失败项（{retryableCount}）</button> : null}
            <button type="button" className="hdde-secondary-action" disabled={!onNavigate || !summary.completed} onClick={() => onNavigate?.("/outputs")}>进入输出中心</button></div>}
        /></div>
        <div className="hdde-batch-compression-summary__relation" aria-label="批量处理前后总体积"><div><span>原始总体积</span><strong>{bytes(summary.originalBytes)}</strong></div><span className="hdde-batch-compression-summary__arrow" aria-hidden="true">→</span>
          <div><span>最终有效总体积</span><strong>{bytes(summary.effectiveBytes)}</strong></div><div className="hdde-batch-compression-summary__saving"><span>节省</span><strong>{bytes(summary.savedBytes)} · 约 {savedPercent.toFixed(1)}%</strong></div></div>
        {resultKey && !eligibilityReady && !outputError ? <p className="hdde-batch-compression-summary__note" role="status">正在重新核对可交付项…</p> : null}
        {outputError ? <p className="hdde-batch-compression-error" role="alert">{outputError}</p> : null}
        {deliveryProgress ? <div className="hdde-batch-delivery-progress" role="status" aria-live="polite"><strong>{deliveryProgress.phase === "confirm" ? "正在确认交付结果" : `正在批量交付 ${deliveryProgress.current}/${deliveryProgress.total}`}</strong><span>{deliveryProgress.phase === "preflight" ? "正在安全预检" : deliveryProgress.phase === "confirm" ? "复用原交付请求身份核对服务端事实" : "正在生成交付副本"}：{deliveryProgress.name}</span></div> : null}
        {deliveryReport ? <div className="hdde-batch-delivery-report" role="status" data-testid="batch-delivery-report"><strong>选择 {deliveryReport.selectedCount} 项 · 成功 {deliveryReport.successCount} · 失败 {deliveryReport.failureCount}{deliveryReport.unknownCount ? ` · 确认中 ${deliveryReport.unknownCount}` : ""}</strong>
          <ul>{deliveryReport.items.map((item) => <li key={item.resultId}><span title={item.name}>{item.name}</span> · {item.original ? "原图" : "压缩成品"}：{item.status === BATCH_DELIVERY_STATUS.COMPLETED ? (
            <>{item.deliveryPath || `${item.deliveryLocation} / ${item.deliveryFileName}`} {item.original || item.deliveryId ? <button type="button" className="hdde-link-action" onClick={() => void openFolder(item.original
              ? `/api/image-compression/batches/${encodeURIComponent(batchId)}/delivery/originals/${encodeURIComponent(item.resultId)}/open-folder`
              : `/api/smart-delivery/runs/${encodeURIComponent(item.deliveryId)}/open-folder`)}>打开交付目录</button> : null}</>
          ) : item.status === BATCH_DELIVERY_STATUS.UNKNOWN ? "正在确认交付结果…" : item.reason}</li>)}</ul>
          {summary.failed ? <ul aria-label="处理失败未交付">{items.filter((item) => item.status === "FAILED").map((item) => (
            <li key={item.id}><span>{item.name}</span> · 处理失败，未交付：{itemFailureMessage(item)}</li>
          ))}</ul> : null}
          {deliveryReport.unknownCount ? <button type="button" className="hdde-secondary-action hdde-batch-delivery-confirm" disabled={Boolean(deliveryProgress)} onClick={() => void confirmUnknownDeliveries()}>重新确认交付结果</button> : null}</div> : null}
        <p className="hdde-batch-compression-summary__note">可交付 {eligibleItems.length} 项。全选可一次交付压缩成品与保留的原图。失败和取消项不会生成副本。</p>
      </section> : null}
      </aside>

      {preview && typeof document !== "undefined" ? createPortal(<div className="hdde-batch-dialog-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setPreview(null)}><section className="hdde-batch-preview-dialog" role="dialog" aria-modal="true" aria-labelledby="batch-preview-title"><header><h2 id="batch-preview-title" title={preview.name}>{preview.name}</h2><button type="button" className="hdde-link-action" onClick={() => setPreview(null)}>关闭</button></header>
        {preview.failed ? <p role="alert" className="hdde-batch-compression-error">原图预览不可用。</p> : (
          <img key={preview.url} src={preview.url} alt={`原图预览：${preview.name}`} onError={() => setPreview((current) => current?.url === preview.url ? { ...current, failed: true } : current)} />
        )}</section></div>, document.body) : null}

    </section>
  );
}
