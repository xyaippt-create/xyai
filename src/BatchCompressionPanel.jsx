import React, { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { HddeSectionHeader, HddeStatusPill } from "./HddeUI.jsx";
import { compressionBatch, summarizeCompressionBatch } from "./batchCompression.js";
import { TARGET_FORMAT_OPTIONS, targetFormatHelper } from "./compressionParams.js";
import {
  BATCH_DELIVERY_STATUS,
  blocksBatchDeliverySelection,
  createDeliveryRequestId,
  deliverBatchResults,
  isBatchDeliveryEligible,
  loadBatchDeliveryStates,
  loadBatchOutputItems,
  readBatchImportProgress,
  resolveBatchMediaUrl,
  saveBatchDeliveryStates,
} from "./batchDelivery.js";
import "./BatchCompressionPanel.css";

const STATES = {
  QUEUED: ["等待处理", "neutral"], PROCESSING: ["处理中", "info"], CANCELED: ["已取消", "neutral"],
  COMPLETED: ["已完成", "positive"], KEEP_ORIGINAL: ["保留原图", "neutral"], FAILED: ["失败", "danger"],
};

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
  const [failed, setFailed] = useState(false);
  const thumbnailUrl = resolveBatchMediaUrl(item.sourcePreviewUrl || "");
  useEffect(() => setFailed(false), [thumbnailUrl]);
  if (!thumbnailUrl || failed) {
    return <span className="hdde-batch-thumbnail hdde-batch-thumbnail--empty" aria-label="暂无可用缩略图">图片</span>;
  }
  return (
    <button type="button" className="hdde-batch-thumbnail" aria-label={`查看 ${item.name} 大图预览`} onClick={onOpen}>
      <img src={thumbnailUrl} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} />
    </button>
  );
}

function deliveryUnavailableReason(item, outputItem, outputLoading, deliveryState) {
  if (deliveryState?.status === BATCH_DELIVERY_STATUS.COMPLETED) return "当前批次已交付成功";
  if (deliveryState?.status === BATCH_DELIVERY_STATUS.UNKNOWN) return "正在确认交付结果，不会创建新的交付请求";
  if (deliveryState?.invalidatesEligibility) return deliveryState.reason || "当前 Result 的交付资格已经失效";
  if (item.status !== "COMPLETED") return "仅有真实 Winner 的已完成项可以交付";
  if (outputLoading) return "正在通过输出中心确认 Result 与交付资格";
  if (!outputItem) return "输出中心中没有找到此 Result 的正式成品";
  if (!outputItem.delivery_eligible) return outputItem.delivery_failure_reason || "当前 Result 不满足既有 Smart Delivery 合同";
  return "当前项不可交付";
}

export default function BatchCompressionPanel({ onNavigate }) {
  const inputRef = useRef(null);
  const { items, running, batchId, loading, state, control, error, targetFormat } = useSyncExternalStore(
    compressionBatch.subscribe,
    compressionBatch.getSnapshot,
  );
  const summary = summarizeCompressionBatch(items);
  const finished = summary.completed + summary.kept + summary.failed + summary.canceled;
  const locked = Boolean(batchId) || loading;
  const activeItems = items.filter((item) => item.status === "PROCESSING");
  const [importProgress, setImportProgress] = useState(null);
  const [outputItems, setOutputItems] = useState({});
  const [outputState, setOutputState] = useState("idle");
  const [outputError, setOutputError] = useState("");
  const [selectedResultIds, setSelectedResultIds] = useState([]);
  const [deliveryStates, setDeliveryStates] = useState({});
  const [preview, setPreview] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deliveryConfirmed, setDeliveryConfirmed] = useState(false);
  const [deliveryProgress, setDeliveryProgress] = useState(null);
  const [deliveryReport, setDeliveryReport] = useState(null);
  const restoredUnknownResultIds = useRef(new Set());
  const recoveryRunning = useRef(false);
  const terminal = Boolean(batchId)
    && !running
    && summary.waiting === 0
    && !["IMPORTING", "RESTORING", "PAUSING", "CANCELING"].includes(state);
  const completedResultKey = terminal
    ? items.filter((item) => item.status === "COMPLETED").map((item) => item.resultId).sort().join("|")
    : "";

  useEffect(() => {
    void compressionBatch.refresh();
    const timer = window.setInterval(() => void compressionBatch.refresh(), 1200);
    return () => window.clearInterval(timer);
  }, []);

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
    if (!completedResultKey) {
      setOutputItems({});
      setOutputState("idle");
      setOutputError("");
      return undefined;
    }
    let active = true;
    setOutputState("loading");
    setOutputError("");
    loadBatchOutputItems(completedResultKey.split("|"))
      .then((matched) => {
        if (!active) return;
        setOutputItems(matched);
        setOutputState("ready");
      })
      .catch((reason) => {
        if (!active) return;
        setOutputItems({});
        setOutputState("failed");
        setOutputError(reason?.message || "无法确认批量成品的预览与交付资格。");
      });
    return () => { active = false; };
  }, [completedResultKey]);

  const blockedDeliverySet = useMemo(() => new Set(
    Object.values(deliveryStates).filter(blocksBatchDeliverySelection).map((item) => item.resultId),
  ), [deliveryStates]);
  const eligibleItems = useMemo(() => items.filter((item) => (
    isBatchDeliveryEligible(item, outputItems[item.resultId], blockedDeliverySet.has(item.resultId))
  )), [blockedDeliverySet, items, outputItems]);
  const eligibleIds = useMemo(() => new Set(eligibleItems.map((item) => item.resultId)), [eligibleItems]);
  const selectedItems = useMemo(() => items.filter((item) => selectedResultIds.includes(item.resultId) && eligibleIds.has(item.resultId)), [eligibleIds, items, selectedResultIds]);
  const unknownDeliveryItems = useMemo(() => items.flatMap((item) => {
    const deliveryState = deliveryStates[item.resultId];
    if (deliveryState?.status !== BATCH_DELIVERY_STATUS.UNKNOWN) return [];
    return [{
      resultId: item.resultId,
      name: item.name,
      outputSha256: item.outputSha256,
      idempotencyKey: deliveryState.idempotencyKey,
    }];
  }), [deliveryStates, items]);
  const unknownDeliveryKey = unknownDeliveryItems.map((item) => `${item.resultId}:${item.idempotencyKey}`).join("|");
  const selectedAll = eligibleItems.length > 0 && selectedItems.length === eligibleItems.length;
  const selectedMixed = selectedItems.length > 0 && !selectedAll;

  useEffect(() => {
    setSelectedResultIds((current) => current.filter((resultId) => eligibleIds.has(resultId)));
  }, [eligibleIds]);

  useEffect(() => {
    if (!preview && !confirmOpen) return undefined;
    const close = (event) => {
      if (event.key !== "Escape") return;
      setPreview(null);
      setConfirmOpen(false);
      setDeliveryConfirmed(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [confirmOpen, preview]);

  const toggleItem = (item) => {
    if (!eligibleIds.has(item.resultId)) return;
    setSelectedResultIds((current) => (
      current.includes(item.resultId)
        ? current.filter((resultId) => resultId !== item.resultId)
        : [...current, item.resultId]
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
      confirmExisting: recovery,
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
  }, [applyDeliveryItemState, deliveryProgress]);

  const beginDelivery = async () => {
    if (!deliveryConfirmed || !selectedItems.length || deliveryProgress) return;
    const requested = selectedItems.map((item) => ({
      resultId: item.resultId,
      name: item.name,
      outputSha256: item.outputSha256,
      idempotencyKey: createDeliveryRequestId(),
    }));
    setConfirmOpen(false);
    setDeliveryConfirmed(false);
    await runDelivery(requested);
  };

  const confirmUnknownDeliveries = useCallback(async () => {
    if (!unknownDeliveryItems.length || deliveryProgress || recoveryRunning.current) return;
    recoveryRunning.current = true;
    try {
      await runDelivery(unknownDeliveryItems, { recovery: true });
    } finally {
      recoveryRunning.current = false;
    }
  }, [deliveryProgress, runDelivery, unknownDeliveryItems]);

  useEffect(() => {
    if (!terminal || outputState !== "ready" || !unknownDeliveryKey || deliveryProgress || recoveryRunning.current) return;
    const restored = unknownDeliveryItems.filter((item) => restoredUnknownResultIds.current.has(item.resultId));
    if (!restored.length) return;
    restored.forEach((item) => restoredUnknownResultIds.current.delete(item.resultId));
    recoveryRunning.current = true;
    void runDelivery(restored, { recovery: true }).finally(() => {
      recoveryRunning.current = false;
    });
  }, [deliveryProgress, outputState, runDelivery, terminal, unknownDeliveryItems, unknownDeliveryKey]);

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
      <section className="hdde-batch-compression-list-card hdde-processing-panel" aria-labelledby="batch-compression-list-title">
        <input ref={inputRef} type="file" multiple hidden accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" disabled={locked}
          data-testid="batch-compression-files" onChange={(event) => { compressionBatch.add(event.currentTarget.files); event.currentTarget.value = ""; }} />
        <HddeSectionHeader
          headingId="batch-compression-list-title"
          title={<>图片列表 <span>{summary.total} 张</span></>}
          description="每张独立执行同一目标格式策略，最多生成一个成品或保留原图。输出沿用系统已设置的图片压缩目录。"
          aside={<div className="hdde-batch-compression-actions">
            <button type="button" className="hdde-secondary-action" onClick={() => inputRef.current?.click()} disabled={locked}>添加图片</button>
            <button type="button" className="hdde-link-action" onClick={() => compressionBatch.clear()} disabled={loading || running || (batchId && summary.waiting > 0) || (!items.length && state !== "BATCH_NOT_FOUND")}>清空列表</button>
          </div>}
        />

        <div className="hdde-batch-compression-format">
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
            <small id="batch-target-format-help" className="hdde-compression-field-helper" data-testid="batch-target-format-helper">{targetFormatHelper(targetFormat)}</small>
          </label>
        </div>

        {error ? <p role="alert" className="hdde-batch-compression-error hdde-batch-compression-error--global">{error}</p> : null}

        {showProgress ? <section className="hdde-batch-compression-progress" data-phase={isPreparing ? "preparing" : isPaused ? "paused" : batchId ? "processing" : "waiting"} aria-label="批量处理进度">
        <div className="hdde-batch-compression-progress__lead">
          <div><strong>{phaseTitle}</strong><p role="status" aria-live="polite">{phaseDetail}</p></div>
          <div className="hdde-batch-compression-actions">
            {!batchId ? <button type="button" className="hdde-primary-action" data-testid="batch-compression-start" disabled={loading || !summary.waiting} onClick={() => void compressionBatch.start()}>开始批量压缩</button> : null}
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
        </section> : null}

        {items.length ? <div className="hdde-batch-compression-table-wrap">
        <table className="hdde-batch-compression-table" data-testid="batch-compression-list">
          <thead><tr><th scope="col" className="hdde-batch-compression-select"><SelectAllCheckbox checked={selectedAll} mixed={selectedMixed} disabled={!eligibleItems.length || Boolean(deliveryProgress)} onChange={() => setSelectedResultIds(selectedAll ? [] : eligibleItems.map((item) => item.resultId))} /></th>
            <th scope="col" className="hdde-batch-compression-preview-column">缩略图</th><th scope="col">文件名</th><th scope="col">状态</th><th scope="col">体积变化</th><th scope="col">减少</th><th scope="col">操作</th></tr></thead>
          <tbody>{items.map((item) => {
            const outputItem = outputItems[item.resultId];
            const deliveryState = deliveryStates[item.resultId];
            const deliveryBlocked = blockedDeliverySet.has(item.resultId);
            const eligible = isBatchDeliveryEligible(item, outputItem, deliveryBlocked);
            const sourcePreviewUrl = resolveBatchMediaUrl(item.sourcePreviewUrl || "");
            const deliveryLabel = deliveryState?.status === BATCH_DELIVERY_STATUS.COMPLETED
              ? ["已交付", "positive"]
              : deliveryState?.status === BATCH_DELIVERY_STATUS.UNKNOWN
                ? ["正在确认", "info"]
                : deliveryState?.status === BATCH_DELIVERY_STATUS.FAILED_DEFINITE
                  ? ["交付失败", "danger"]
                  : null;
            return <tr key={item.id} data-status={item.status} data-item-id={item.id}>
              <td className="hdde-batch-compression-select"><input type="checkbox" aria-label={`选择 ${item.name}`} checked={selectedResultIds.includes(item.resultId)} aria-invalid={deliveryState?.invalidatesEligibility || Boolean(outputItem?.delivery_failure_code) || undefined} disabled={!eligible || Boolean(deliveryProgress)} title={eligible ? "加入批量交付" : deliveryUnavailableReason(item, outputItem, outputState === "loading", deliveryState)} onChange={() => toggleItem(item)} /></td>
              <td><BatchThumbnail item={item} onOpen={() => sourcePreviewUrl && setPreview({ name: item.name, url: sourcePreviewUrl })} /></td>
              <td className="hdde-batch-compression-name"><strong title={item.name}>{item.name}</strong>{item.error ? <p className="hdde-batch-compression-error">{item.error}</p> : null}
                {deliveryState?.status === BATCH_DELIVERY_STATUS.UNKNOWN ? <p className="hdde-batch-delivery-state" role="status">正在确认交付结果…</p> : null}
                {deliveryState?.status === BATCH_DELIVERY_STATUS.FAILED_DEFINITE ? <p className="hdde-batch-compression-error" role="alert">{deliveryState.reason}（{deliveryState.code}）</p> : null}
                {!deliveryState && outputItem?.delivery_eligible === false && outputItem?.delivery_failure_code ? <p className="hdde-batch-compression-error" role="alert">{outputItem.delivery_failure_reason || "当前 Result 的交付资格已经失效"}（{outputItem.delivery_failure_code}）</p> : null}
              </td>
              <td><HddeStatusPill tone={(deliveryLabel || STATES[item.status])[1]}>{(deliveryLabel || STATES[item.status])[0]}</HddeStatusPill></td>
              <td>{bytes(item.originalBytes)} <span aria-hidden="true">→</span> {bytes(item.finalBytes)}</td><td>{item.savedPercent === null ? "—" : `${item.savedPercent.toFixed(1)}%`}</td>
              <td><div className="hdde-batch-compression-actions">
                {item.status === "COMPLETED" ? <button type="button" className="hdde-link-action" disabled={!onNavigate || !eligible || deliveryState?.status === BATCH_DELIVERY_STATUS.UNKNOWN || deliveryState?.invalidatesEligibility} title={eligible ? "进入当前 Result 的交付流程" : deliveryUnavailableReason(item, outputItem, outputState === "loading", deliveryState)} onClick={() => onNavigate?.(`/smart-delivery?results=${encodeURIComponent(item.resultId)}`)}>继续交付</button> : null}
                {!batchId ? <button type="button" className="hdde-link-action" aria-label={`移除 ${item.name}`} disabled={locked} onClick={() => compressionBatch.remove(item.id)}>移除</button> : null}
              </div></td>
            </tr>;
          })}</tbody>
        </table>
        </div> : <button type="button" className="hdde-watermark-empty" onClick={() => inputRef.current?.click()}><strong>添加需要压缩的图片</strong><span>可一次选择多张 PNG、JPG、JPEG、WebP</span></button>}
      </section>

      {terminal ? <section className="hdde-batch-compression-summary hdde-processing-panel" aria-label="批量处理结果" data-testid="batch-compression-summary">
        <div className="hdde-batch-compression-summary__header"><HddeSectionHeader
          eyebrow="批量处理完成"
          title={`${summary.total} 张图片已结束处理`}
          description={`成功 ${summary.completed} · 保留原图 ${summary.kept} · 失败 ${summary.failed} · 已取消 ${summary.canceled}`}
          aside={<div className="hdde-batch-compression-summary__actions"><button type="button" className="hdde-primary-action" data-testid="batch-delivery-open" disabled={!selectedItems.length || Boolean(deliveryProgress)} onClick={() => { setDeliveryConfirmed(false); setConfirmOpen(true); }}>批量交付（{selectedItems.length}）</button>
            <button type="button" className="hdde-secondary-action" disabled={!onNavigate || !summary.completed} onClick={() => onNavigate?.("/outputs")}>进入输出中心</button></div>}
        /></div>
        <div className="hdde-batch-compression-summary__relation" aria-label="批量处理前后总体积"><div><span>原始总体积</span><strong>{bytes(summary.originalBytes)}</strong></div><span className="hdde-batch-compression-summary__arrow" aria-hidden="true">→</span>
          <div><span>最终有效总体积</span><strong>{bytes(summary.effectiveBytes)}</strong></div><div className="hdde-batch-compression-summary__saving"><span>节省</span><strong>{bytes(summary.savedBytes)} · 约 {savedPercent.toFixed(1)}%</strong></div></div>
        {outputState === "loading" ? <p className="hdde-batch-compression-summary__note" role="status">正在通过输出中心确认预览与可交付 Result…</p> : null}
        {outputError ? <p className="hdde-batch-compression-error" role="alert">{outputError}</p> : null}
        {deliveryProgress ? <div className="hdde-batch-delivery-progress" role="status" aria-live="polite"><strong>{deliveryProgress.phase === "confirm" ? "正在确认交付结果" : `正在批量交付 ${deliveryProgress.current}/${deliveryProgress.total}`}</strong><span>{deliveryProgress.phase === "preflight" ? "正在安全预检" : deliveryProgress.phase === "confirm" ? "复用原交付请求身份核对服务端事实" : "正在生成交付副本"}：{deliveryProgress.name}</span></div> : null}
        {deliveryReport ? <div className="hdde-batch-delivery-report" role="status" data-testid="batch-delivery-report"><strong>选择 {deliveryReport.selectedCount} 项 · 成功 {deliveryReport.successCount} · 失败 {deliveryReport.failureCount}{deliveryReport.unknownCount ? ` · 确认中 ${deliveryReport.unknownCount}` : ""}</strong>
          {deliveryReport.failureCount || deliveryReport.unknownCount ? <ul>{deliveryReport.items.filter((item) => item.status !== BATCH_DELIVERY_STATUS.COMPLETED).map((item) => <li key={item.resultId}><span title={item.name}>{item.name}</span>：{item.status === BATCH_DELIVERY_STATUS.UNKNOWN ? "正在确认交付结果…" : `${item.reason}（${item.code}）`}</li>)}</ul> : <span>Winner、Result 与 Delivery SHA 已逐项核对一致。</span>}
          {deliveryReport.unknownCount ? <button type="button" className="hdde-secondary-action hdde-batch-delivery-confirm" disabled={Boolean(deliveryProgress)} onClick={() => void confirmUnknownDeliveries()}>重新确认交付结果</button> : null}</div> : null}
        <p className="hdde-batch-compression-summary__note">保留原图、失败及取消项按原始体积计入；批量交付不会重新压缩、创建 Result 或移动 Winner。</p>
      </section> : null}

      {preview && typeof document !== "undefined" ? createPortal(<div className="hdde-batch-dialog-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setPreview(null)}><section className="hdde-batch-preview-dialog" role="dialog" aria-modal="true" aria-labelledby="batch-preview-title"><header><h2 id="batch-preview-title" title={preview.name}>{preview.name}</h2><button type="button" className="hdde-link-action" onClick={() => setPreview(null)}>关闭</button></header><img src={preview.url} alt={`原图预览：${preview.name}`} /></section></div>, document.body) : null}

      {confirmOpen && typeof document !== "undefined" ? createPortal(<div className="hdde-batch-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) { setConfirmOpen(false); setDeliveryConfirmed(false); } }}><section className="hdde-batch-delivery-dialog" role="dialog" aria-modal="true" aria-labelledby="batch-delivery-title"><div><p className="hdde-eyebrow">正式文件交付</p><h2 id="batch-delivery-title">确认批量交付 {selectedItems.length} 项</h2></div><p>每项将按 Result 身份独立执行 Smart Delivery 预检与复制；一个项目失败不会阻止其他项目。</p><label><input type="checkbox" checked={deliveryConfirmed} onChange={(event) => setDeliveryConfirmed(event.target.checked)} /><span>我已核对选择项，确认生成独立交付副本。</span></label><div className="hdde-batch-compression-actions"><button type="button" className="hdde-secondary-action" onClick={() => { setConfirmOpen(false); setDeliveryConfirmed(false); }}>取消</button><button type="button" className="hdde-primary-action" disabled={!deliveryConfirmed} onClick={() => void beginDelivery()}>确认并交付（{selectedItems.length}）</button></div></section></div>, document.body) : null}
    </section>
  );
}
