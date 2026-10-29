import React, { useEffect, useMemo, useState } from "react";
import { HddePageHeader } from "./HddeUI.jsx";
import { createDeliveryRequestId, executeSingleResultDelivery } from "./batchDelivery.js";

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

export default function SmartDeliveryPage({ selectedItemIds = [], selectedResultIds = [], onBackToOutputs }) {
  const [preflight, setPreflight] = useState(null);
  const [preflightState, setPreflightState] = useState("loading");
  const [error, setError] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [delivery, setDelivery] = useState(null);
  const [requestKey, setRequestKey] = useState(() => createDeliveryRequestId());
  const selectionMode = selectedResultIds.length ? "result_ids" : "item_ids";
  const selectedIds = selectedResultIds.length ? selectedResultIds : selectedItemIds;
  const selectionKey = useMemo(() => selectedIds.join("|"), [selectedIds]);
  const singleResult = selectionMode === "result_ids" && selectedIds.length === 1;

  useEffect(() => {
    const selectedValues = selectionKey ? selectionKey.split("|") : [];
    if (!selectedValues.length || delivery) return undefined;
    let active = true;
    setPreflightState("loading");
    setError("");
    setConfirmed(false);
    requestJson("/api/smart-delivery/preflight", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [selectionMode]: selectedValues, rules: {} }),
    })
      .then((payload) => {
        if (!active) return;
        setPreflight(payload.data);
        setPreflightState(payload.data?.ready ? "ready" : "blocked");
        setRequestKey(createDeliveryRequestId());
      })
      .catch((reason) => {
        if (!active) return;
        setError(reason.message);
        setPreflight(null);
        setPreflightState("failed");
      });
    return () => {
      active = false;
    };
  }, [delivery, selectionKey, selectionMode]);

  const executeDelivery = async () => {
    if (!preflight?.ready || !confirmed || executing) return;
    setExecuting(true);
    setError("");
    try {
      if (singleResult) {
        const outcome = await executeSingleResultDelivery({
          planId: preflight.plan_id,
          resultId: selectedIds[0],
          idempotencyKey: requestKey,
          request: requestJson,
        });
        if (outcome.outcome === "settled") {
          setDelivery(outcome.data);
        } else {
          setError(outcome.outcome === "pending"
            ? "交付结果正在确认，请稍后再次点击确认；不会重复生成副本。"
            : "交付请求没有到达服务端，可以再次点击确认。");
        }
        return;
      }
      const payload = await requestJson("/api/smart-delivery/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_id: preflight.plan_id, confirmed: true }),
      });
      setDelivery(payload.data);
    } catch (reason) {
      // A definite failure ends this request; the next attempt is a new one.
      if (singleResult) setRequestKey(createDeliveryRequestId());
      const refreshed = reason.payload?.detail?.preflight;
      if (refreshed) {
        setPreflight(refreshed);
        setPreflightState("blocked");
        setConfirmed(false);
      }
      setError(reason.message);
    } finally {
      setExecuting(false);
    }
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
          description="请从输出中心选择正式成品，或在处理结果中直接确认交付。"
          actions={<button type="button" className="hdde-primary-action" onClick={onBackToOutputs}>返回输出中心</button>}
        />
      </section>
    );
  }

  if (delivery) {
    return (
      <section className="hdde-delivery-page hdde-page-frame hdde-page-stack" aria-labelledby="file-delivery-title" data-testid="file-delivery-result">
        <HddePageHeader
          eyebrow={delivery.failure_count ? "交付已结束" : "正式交付完成"}
          title={delivery.failure_count ? "部分交付副本未能生成" : "交付副本已生成"}
          headingId="file-delivery-title"
          description={delivery.failure_count
            ? "已完成的副本可以正常使用；失败项保留原因，源成品与已生成文件均未被覆盖。"
            : "源成品保持原位，交付副本已写入正式目录。"}
          actions={<div className="hdde-delivery-result-summary">
            <strong>{delivery.success_count}</strong><span>成功</span>
            <strong data-tone={delivery.failure_count ? "danger" : "success"}>{delivery.failure_count}</strong><span>失败</span>
          </div>}
        />
        {error ? <div className="hdde-delivery-alert" role="alert">{error}</div> : null}
        <div className="hdde-delivery-location">
          <div><span>交付目录</span><strong>{delivery.delivery_location_label}</strong><small>{delivery.success_count} 个独立副本已写入，源成品未移动</small></div>
          <button type="button" className="hdde-secondary-action" onClick={() => openDelivery(`/api/smart-delivery/runs/${encodeURIComponent(delivery.delivery_id)}/open-folder`)}>打开交付目录</button>
        </div>
        <div className="hdde-delivery-result-heading">
          <div><p className="hdde-eyebrow">文件映射</p><h2>交付副本明细</h2></div>
          <p>逐项核对源成品、交付文件与写入结果。</p>
        </div>
        <div className="hdde-delivery-result-list" aria-label="源成品到交付副本映射">
          {delivery.results.map((item) => (
            <article key={item.delivery_item_id || item.result_id} data-status={item.status}>
              <div><span>源成品</span><strong>{item.source_file_name}</strong></div>
              <div className="hdde-delivery-arrow" aria-hidden="true">→</div>
              <div className="hdde-delivery-target">
                <span>交付副本</span><strong>{item.delivery_file_name}</strong>
                <small>{item.status === "completed" ? `${formatBytes(item.size_bytes)} · 内容校验一致` : item.failure_reason}</small>
                {item.status === "completed" ? (
                  <button type="button" className="hdde-secondary-action" onClick={() => openDelivery(`/api/smart-delivery/runs/${encodeURIComponent(delivery.delivery_id)}/items/${encodeURIComponent(item.delivery_item_id || item.result_id)}/open`)}>打开交付文件</button>
                ) : null}
              </div>
            </article>
          ))}
        </div>
        <div className="hdde-delivery-footer-actions" aria-label="交付完成后的下一步">
          <div className="hdde-delivery-footer-actions__copy"><span>下一步</span><strong>{delivery.failure_count ? "检查失败原因或返回输出中心" : "继续查看正式成品"}</strong></div>
          <button type="button" className="hdde-primary-action" onClick={onBackToOutputs}>返回输出中心</button>
        </div>
      </section>
    );
  }

  return (
    <section className="hdde-delivery-page hdde-page-frame hdde-page-stack" aria-labelledby="file-delivery-title" data-testid="file-delivery-page">
      <HddePageHeader
        eyebrow="正式文件交付"
        title="确认交付"
        headingId="file-delivery-title"
        description="核对从输出中心选择的正式成品与目标文件；源成品、Result 映射和对比关系不会改变。"
        actions={<button type="button" className="hdde-secondary-action" onClick={onBackToOutputs}>返回输出中心</button>}
      />

      {error ? <div className="hdde-delivery-alert" role="alert">{error}</div> : null}

      <div className="hdde-delivery-review">
        <div className="hdde-delivery-section-heading">
          <div><p className="hdde-eyebrow">交付清单</p><h2>文件与安全状态</h2></div>
          <span data-state={preflightState}>{preflightState === "loading" ? "检查中" : preflight?.ready ? "可以交付" : "已阻断"}</span>
        </div>
        {preflight?.items?.length ? (
          <div className="hdde-delivery-preview-list" aria-label="待交付文件清单">
            {preflight.items.map((item) => (
              <article key={item.item_id}>
                <img src={item.preview_url} alt={`待交付成品：${item.source_file_name}`} />
                <div><span>{item.source_file_name}</span><strong>{item.delivery_file_name}</strong></div>
              </article>
            ))}
          </div>
        ) : null}
        {preflight?.issues?.length ? (
          <div className="hdde-delivery-blockers" role="alert">
            <strong>安全检查已阻止写入</strong>
            <ul>{preflight.issues.map((issue, index) => <li key={`${issue.code}-${issue.item_id}-${index}`}>{issue.file_name ? `${issue.file_name}：` : ""}{issue.message}</li>)}</ul>
          </div>
        ) : null}
        {preflight?.ready ? (
          <div className="hdde-delivery-ready" role="status">
            <strong>公共文件安全检查通过</strong>
            <span>目标路径、文件名、扩展名、批次唯一性与同名冲突均已检查；不会静默覆盖现有文件。</span>
            <span>交付位置：{preflight.delivery_location_label}</span>
          </div>
        ) : null}
        <label className="hdde-delivery-confirm">
          <input type="checkbox" checked={confirmed} disabled={!preflight?.ready || preflightState === "loading"} onChange={(event) => setConfirmed(event.target.checked)} />
          <span>我已核对源成品与交付文件，确认生成独立副本。</span>
        </label>
        <button type="button" className="hdde-primary-action hdde-delivery-submit" disabled={!preflight?.ready || !confirmed || executing} onClick={executeDelivery}>
          {executing ? "正在生成交付副本…" : "确认并生成交付副本"}
        </button>
      </div>
    </section>
  );
}
