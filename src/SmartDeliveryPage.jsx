import React, { useEffect, useState } from "react";
import { HddePageHeader } from "./HddeUI.jsx";
import HddeIcon from "./HddeIcon.jsx";
import "./SmartDeliveryReceipt.css";
import { createDeliveryRequestId, lookupDeliveryRequest } from "./batchDelivery.js";

const UNCONFIRMED_DELIVERY_CODES = new Set([
  "SMART_DELIVERY_IN_PROGRESS", "SMART_DELIVERY_OUTCOME_UNCONFIRMED",
  "SMART_DELIVERY_REQUEST_STATE_INVALID", "SMART_DELIVERY_IDEMPOTENCY_CONFLICT",
]);

async function requestJson(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.success === false) {
    const detail = payload?.detail;
    const error = new Error(detail?.message || payload?.message || "文件交付暂时无法完成该操作。");
    error.payload = payload;
    error.status = response.status;
    error.code = detail?.code || "";
    throw error;
  }
  return payload;
}

function formatBytes(value) {
  const size = Number(value) || 0;
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(2)} MB`;
}

function manifestSize(bytes) {
  return bytes < 1024 ? formatBytes(bytes) : `${formatBytes(bytes)}（${bytes.toLocaleString("zh-CN")} 字节）`;
}

function DeliveryManifestButton({ results }) {
  const [feedback, setFeedback] = useState("");
  const completed = results.filter((item) => item.status === "completed");

  const copyManifest = async () => {
    const totalBytes = completed.reduce((sum, item) => sum + item.size_bytes, 0);
    const lines = completed.map((item) => `${item.delivery_file_name}　${manifestSize(item.size_bytes)}`);
    const text = ["交付清单", `共 ${completed.length} 个文件，合计 ${manifestSize(totalBytes)}`, "", ...lines].join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setFeedback("交付清单已复制");
    } catch {
      setFeedback("复制失败，请允许访问剪贴板后重试");
    }
  };

  return (
    <>
      <span role="status" className="hdde-receipt-feedback">{feedback}</span>
      <button type="button" className="hdde-receipt-link" disabled={!completed.length} onClick={copyManifest}><HddeIcon name="copy" size={16} />复制交付清单</button>
    </>
  );
}

function ReceiptThumbnail({ item }) {
  const [unavailable, setUnavailable] = useState(false);
  const revision = item.source_sha256 || item.delivery_item_id || item.result_id;
  return (
    <span className="hdde-receipt-thumbnail" aria-hidden="true">
      {item.status === "completed" && item.item_id && !unavailable
        ? <img src={`/api/output-center/items/${encodeURIComponent(item.item_id)}/thumbnail?v=${encodeURIComponent(revision)}`} alt="" loading="lazy" onError={() => setUnavailable(true)} />
        : <HddeIcon name="file" size={28} />}
    </span>
  );
}

export default function SmartDeliveryPage({ selectedItemIds = [], selectedResultIds = [], onBackToOutputs, onRetryFailed }) {
  const selectionMode = selectedResultIds.length ? "result_ids" : "item_ids";
  const selectionKey = (selectedResultIds.length ? selectedResultIds : selectedItemIds).join("|");
  return <DeliverySelection key={`${selectionMode}:${selectionKey}`} selectionMode={selectionMode} selectionKey={selectionKey} onBackToOutputs={onBackToOutputs} onRetryFailed={onRetryFailed} />;
}

function DeliverySelection({ selectionMode, selectionKey, onBackToOutputs, onRetryFailed }) {
  const selectedIds = selectionKey ? selectionKey.split("|") : [];
  const storageKey = `hdde.delivery-request:${selectionMode}:${[...selectedIds].sort().join("|")}`;
  const multiFile = selectedIds.length > 1;
  const identityField = selectionMode === "result_ids" ? "source_result_id" : "item_id";
  const [attempt, setAttempt] = useState(() => {
    const entry = window.history.state;
    let stored = entry?.deliveryRequestKey;
    try {
      stored ||= (multiFile && localStorage.getItem(storageKey)) || sessionStorage.getItem(storageKey);
    } catch { /* Storage is checked again before writing a copy. */ }
    if (/^delivery_request_[A-Za-z0-9_-]{16,96}$/.test(stored || "")) return { mode: "lookup", key: stored };
    return { mode: entry?.startDelivery ? "submit" : "idle", key: createDeliveryRequestId() };
  });
  const [state, setState] = useState({ phase: "working" });
  const [error, setError] = useState("");
  const [delivery, setDelivery] = useState(null);

  useEffect(() => {
    if (!selectionKey || attempt.mode === "idle") return;
    let active = true;
    const entryUrl = window.location.href;
    const selectedValues = selectionKey.split("|");
    const requestKey = attempt.key;
    const isCurrent = () => active && window.location.href === entryUrl;
    const rememberEntry = () => window.history.replaceState(
      { ...window.history.state, deliveryRequestKey: requestKey }, "", entryUrl,
    );
    const report = (phase, message, extra = {}) => {
      if (isCurrent()) setState({ phase, message, ...extra });
    };

    function showReceipt(run) {
      if (!isCurrent()) return;
      const ids = Array.isArray(run?.results) ? run.results.map(item => item?.[identityField]) : [];
      if (!["completed", "partial", "failed"].includes(run?.status) || !run.delivery_id ||
          run.idempotency_key !== requestKey || ids.length !== selectedValues.length ||
          new Set(ids).size !== ids.length || !selectedValues.every(id => ids.includes(id))) {
        report("unknown", "未能核对这次交付的回执，请查询原交付请求。");
        return;
      }
      setDelivery(run);
      try {
        if (multiFile) {
          const stored = localStorage.getItem(storageKey);
          if (run.success_count > 0 && !stored) localStorage.setItem(storageKey, requestKey);
          if (run.success_count === 0 && stored === requestKey) localStorage.removeItem(storageKey);
        }
        if (sessionStorage.getItem(storageKey) === requestKey) sessionStorage.removeItem(storageKey);
      } catch { /* The history entry still identifies this receipt on reload. */ }
    }

    async function lookup(expiryMessage) {
      try {
        const query = selectionMode === "result_ids" && selectedValues.length === 1 ? { result_id: selectedValues[0] }
          : { selection_mode: selectionMode, selection_ids: selectedValues.join(",") };
        const outcome = await lookupDeliveryRequest({ query, idempotencyKey: requestKey, request: requestJson });
        if (outcome.outcome === "settled") showReceipt(outcome.data);
        else if (outcome.outcome === "not_started") report("retry", expiryMessage || "暂未查到原请求，可以重试交付。");
        else report("unknown", "暂时无法取得交付回执，请查询原交付请求。");
      } catch (reason) {
        if (reason.payload?.detail?.idempotent_replay && !UNCONFIRMED_DELIVERY_CODES.has(reason.code)) {
          report("retry", reason.message, { newRequest: true });
        } else report("unknown", reason.message);
      }
    }

    async function run() {
      if (attempt.mode === "lookup") {
        rememberEntry();
        await lookup();
        return;
      }
      const payload = await requestJson("/api/smart-delivery/preflight", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [selectionMode]: selectedValues, rules: {} }),
      });
      if (!isCurrent()) return;
      const preflight = payload.data;
      if (!preflight?.ready || !preflight.plan_id) {
        report("retry", "交付条件未通过，请处理后重试。", { issues: preflight?.issues });
        return;
      }
      try {
        (multiFile ? localStorage : sessionStorage).setItem(storageKey, requestKey);
        rememberEntry();
      } catch {
        report("retry", "无法保存交付请求，请重新打开应用后重试。");
        return;
      }
      report("working", "正在生成交付副本…");
      try {
        const response = await requestJson("/api/smart-delivery/execute", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plan_id: preflight.plan_id, confirmed: true, idempotency_key: requestKey }),
        });
        showReceipt(response.data);
      } catch (reason) {
        if (!isCurrent()) return;
        if (reason.code === "SMART_DELIVERY_PLAN_EXPIRED" || !reason.status || reason.status >= 500 ||
            !reason.code || UNCONFIRMED_DELIVERY_CODES.has(reason.code)) {
          await lookup(reason.code === "SMART_DELIVERY_PLAN_EXPIRED" ? reason.message : "");
        } else {
          const detail = reason.payload?.detail;
          if (detail?.delivery_id && detail.success_count !== 0) await lookup();
          else report("retry", reason.message, { issues: detail?.preflight?.issues, newRequest: Boolean(detail?.delivery_id) });
        }
      }
    }
    run().catch(reason => report(attempt.mode === "lookup" ? "unknown" : "retry", reason.message));
    return () => { active = false; };
  }, [attempt, identityField, multiFile, selectionKey, selectionMode, storageKey]);

  const start = (mode, fresh = false) => {
    setDelivery(null);
    setError("");
    setState({ phase: "working" });
    setAttempt({ mode, key: fresh ? createDeliveryRequestId() : attempt.key });
  };

  const retryFailed = () => {
    const failedIds = delivery.results.filter(item => item.status === "failed").map(item => item[identityField]);
    if (!failedIds.length) return;
    if (failedIds.length === selectedIds.length) start("submit", true);
    else onRetryFailed?.(selectionMode, failedIds);
  };

  const openDelivery = async (path) => {
    setError("");
    try {
      await requestJson(path, { method: "POST" });
    } catch (reason) {
      setError(reason.message);
    }
  };

  if (!selectedIds.length) {
    return (
      <section className="hdde-delivery-page hdde-page-frame hdde-page-stack" aria-labelledby="file-delivery-title" data-testid="file-delivery-empty">
        <HddePageHeader
          eyebrow="正式文件交付"
          title="文件交付"
          headingId="file-delivery-title"
          description="请从输出中心选择成品，或在处理结果中生成交付副本。"
          actions={<button type="button" className="hdde-primary-action" onClick={onBackToOutputs}>返回输出中心</button>}
        />
      </section>
    );
  }

  if (delivery) {
    const completedPrint = delivery.success_count > 0 && !delivery.failure_count &&
      delivery.results?.length > 0 && delivery.results.every(item => item.source_processing_type === "print_output");
    const hasFailures = delivery.failure_count > 0;
    const total = delivery.results.length;
    const runPath = `/api/smart-delivery/runs/${encodeURIComponent(delivery.delivery_id)}`;
    return (
      <section className="hdde-delivery-page hdde-receipt" aria-labelledby="file-delivery-title" data-testid="file-delivery-result">
        <header className="hdde-receipt-header">
          <span className="hdde-receipt-mark" data-tone={hasFailures ? (delivery.success_count ? "warning" : "danger") : "success"}><HddeIcon name={hasFailures ? "alert" : "check"} size={25} /></span>
          <div>
            <h1 id="file-delivery-title">{hasFailures ? (delivery.success_count ? "部分交付副本未能生成" : "交付未完成") : "交付副本已生成"}</h1>
            <p>{hasFailures ? `成功 ${delivery.success_count} 个，失败 ${delivery.failure_count} 个。请查看下方原因。` : `已保存 ${total} 个文件，源成品未移动。`}</p>
          </div>
        </header>
        {error ? <div className="hdde-delivery-alert" role="alert">{error}</div> : null}
        <section className="hdde-receipt-card" aria-labelledby="receipt-files-heading">
          <div className="hdde-receipt-toolbar">
            <h2 id="receipt-files-heading">交付副本明细</h2>
            <div className="hdde-receipt-tools"><DeliveryManifestButton key={delivery.delivery_id} results={delivery.results} /></div>
          </div>
          <ul className="hdde-receipt-files">
            {delivery.results.map(item => {
              const saved = item.status === "completed";
              const filename = item.delivery_file_name || item.source_file_name;
              return (
                <li key={item.delivery_item_id || item.result_id}>
                  <ReceiptThumbnail item={item} />
                  <div className="hdde-receipt-file-info">
                    <strong>{filename}</strong>
                    {item.source_file_name && item.source_file_name !== filename && <small>源成品 · {item.source_file_name}</small>}
                    {saved ? <p className="hdde-receipt-meta"><span>{formatBytes(item.size_bytes)}</span><span><HddeIcon name="check" size={14} />内容校验一致</span></p>
                      : <p className="hdde-receipt-error">交付失败 · {item.failure_reason || "请重试此文件。"}</p>}
                  </div>
                  {saved && <button type="button" className={total === 1 ? "hdde-primary-action" : "hdde-secondary-action"}
                    onClick={() => openDelivery(`${runPath}/items/${encodeURIComponent(item.delivery_item_id || item.result_id)}/open`)}>打开交付文件</button>}
                </li>
              );
            })}
          </ul>
          <div className="hdde-receipt-location">
            <HddeIcon name="folder" size={20} />
            <div><span>交付目录</span><strong>{delivery.delivery_location_label}</strong></div>
            <div className="hdde-receipt-tools">
              <button type="button" className={total > 1 && !hasFailures ? "hdde-primary-action" : "hdde-secondary-action"} onClick={() => openDelivery(`${runPath}/open-folder`)}>打开交付目录</button>
              {hasFailures && onRetryFailed && <button type="button" className="hdde-primary-action" onClick={retryFailed}>仅重试失败项</button>}
            </div>
          </div>
        </section>
        <nav className="hdde-receipt-navigation" aria-label="交付完成后的下一步">
          <button type="button" className="hdde-receipt-link" onClick={onBackToOutputs}><HddeIcon name="back" size={16} />返回输出中心</button>
          {completedPrint && <a className="hdde-secondary-action" href="/print-8k">继续喷绘出图<HddeIcon name="chevron" size={16} /></a>}
        </nav>
      </section>
    );
  }

  const idle = attempt.mode === "idle";
  const working = !idle && state.phase === "working";
  const unknown = state.phase === "unknown";
  const title = idle ? "文件交付" : working ? "正在交付" : unknown ? "结果待确认" : "交付未完成";
  return (
    <section className="hdde-delivery-page hdde-page-frame hdde-page-stack" aria-labelledby="file-delivery-title" data-testid="file-delivery-page">
      <HddePageHeader headingId="file-delivery-title" title={title}
        actions={<button type="button" className="hdde-secondary-action" onClick={onBackToOutputs}>返回输出中心</button>} />
      <div className="hdde-delivery-location">
        <div role={working || idle ? "status" : "alert"}>
          {idle ? `已选 ${selectedIds.length} 个文件` : state.message ||
            (attempt.mode === "lookup" ? "正在读取原交付回执…" : "正在检查交付文件…")}
          {state.issues?.length > 0 && <ul>{state.issues.map((issue, index) =>
            <li key={index}>{issue.file_name && `${issue.file_name}：`}{issue.message}</li>)}</ul>}
        </div>
        {!working && <button type="button" className="hdde-secondary-action"
          onClick={() => start(unknown ? "lookup" : "submit", state.newRequest)}>
          {idle ? "生成交付副本" : unknown ? "查询原交付请求" : "重试交付"}
        </button>}
      </div>
    </section>
  );
}
