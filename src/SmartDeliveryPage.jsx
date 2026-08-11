import React, { useEffect, useMemo, useState } from "react";
import { getFileDisplayName } from "./fileDisplayName.js";
import { HddePageHeader } from "./HddeUI.jsx";

const DEFAULT_RULES = Object.freeze({
  base_mode: "original",
  base_name: "客户交付",
  prefix: "",
  suffix: "",
  find_text: "",
  replace_text: "",
  sequence_enabled: true,
  sequence_start: 1,
  sequence_padding: 2,
  date_enabled: true,
  template: "{prefix}{base}{suffix}_{date}_{seq}",
});

async function requestJson(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.success === false) {
    const detail = payload?.detail;
    const error = new Error(detail?.message || payload?.message || "智能交付暂时无法完成该操作。");
    error.payload = payload;
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

function RuleField({ label, helper, children }) {
  return (
    <label className="hdde-delivery-field">
      <span>{label}</span>
      {children}
      {helper ? <small>{helper}</small> : null}
    </label>
  );
}

export default function SmartDeliveryPage({ selectedItemIds = [], selectedResultIds = [], onBackToOutputs }) {
  const [rules, setRules] = useState(DEFAULT_RULES);
  const [preflight, setPreflight] = useState(null);
  const [preflightState, setPreflightState] = useState("loading");
  const [error, setError] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [delivery, setDelivery] = useState(null);
  const selectionMode = selectedResultIds.length ? "result_ids" : "item_ids";
  const selectedIds = selectedResultIds.length ? selectedResultIds : selectedItemIds;
  const selectionKey = useMemo(() => selectedIds.join("|"), [selectedIds]);

  useEffect(() => {
    const selectedValues = selectionKey ? selectionKey.split("|") : [];
    if (!selectedValues.length || delivery) return undefined;
    let active = true;
    const timer = window.setTimeout(() => {
      setPreflightState("loading");
      setError("");
      setConfirmed(false);
      requestJson("/api/smart-delivery/preflight", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [selectionMode]: selectedValues, rules }),
      })
        .then((payload) => {
          if (!active) return;
          setPreflight(payload.data);
          setPreflightState(payload.data?.ready ? "ready" : "blocked");
        })
        .catch((reason) => {
          if (!active) return;
          setError(reason.message);
          setPreflight(null);
          setPreflightState("failed");
        });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [delivery, rules, selectionKey, selectionMode]);

  const updateRule = (name, value) => {
    setRules((current) => ({ ...current, [name]: value }));
  };

  const executeDelivery = async () => {
    if (!preflight?.ready || !confirmed || executing) return;
    setExecuting(true);
    setError("");
    try {
      const payload = await requestJson("/api/smart-delivery/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_id: preflight.plan_id, confirmed: true }),
      });
      setDelivery(payload.data);
    } catch (reason) {
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
      <section className="hdde-delivery-page hdde-page-frame hdde-page-stack" aria-labelledby="smart-delivery-title">
        <HddePageHeader eyebrow="交付副本" title="智能交付" headingId="smart-delivery-title" description="请先从输出中心选择需要生成交付副本的真实成品。" />
        <div className="hdde-delivery-empty">
          <strong>还没有待交付成品</strong>
          <span>返回输出中心选择一个或多个正式结果，再生成独立交付副本。</span>
          <button type="button" className="hdde-primary-action" onClick={onBackToOutputs}>返回输出中心</button>
        </div>
      </section>
    );
  }

  if (delivery) {
    return (
      <section className="hdde-delivery-page hdde-page-frame hdde-page-stack" aria-labelledby="smart-delivery-title" data-testid="smart-delivery-result">
        <HddePageHeader
          eyebrow={delivery.failure_count ? "交付已结束" : "正式交付完成"}
          title={delivery.failure_count ? "部分交付副本未能生成" : "交付副本已生成"}
          headingId="smart-delivery-title"
          description={delivery.failure_count
            ? "已完成的副本可以正常使用；失败项保留原因，源成品与已生成文件均未被覆盖。"
            : "源成品保持原位，所有交付副本已按确认时的名称写入正式目录。"}
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
          <p>逐项核对源成品、最终文件名与写入结果。</p>
        </div>
        <div className="hdde-delivery-result-list" aria-label="源成品到交付副本映射">
          {delivery.results.map((item) => (
            <article key={item.delivery_item_id || item.result_id} data-status={item.status}>
              <div>
                <span>源成品</span><strong>{getFileDisplayName(item.source_file_name)}</strong>
              </div>
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
        <div className="hdde-delivery-footer-actions">
          <div><span>下一步</span><strong>{delivery.failure_count ? "检查失败原因或返回重新交付" : "继续整理下一批正式成品"}</strong></div>
          <button type="button" className="hdde-primary-action" onClick={onBackToOutputs}>返回输出中心</button>
        </div>
      </section>
    );
  }

  return (
    <section className="hdde-delivery-page hdde-page-frame hdde-page-stack" aria-labelledby="smart-delivery-title" data-testid="smart-delivery-page">
      <HddePageHeader
        eyebrow="交付副本"
        title="智能交付"
        headingId="smart-delivery-title"
        description="为已完成的真实成品生成规范命名副本；源成品、任务映射与对比关系不会改变。"
        actions={<button type="button" className="hdde-secondary-action" onClick={onBackToOutputs}>返回输出中心</button>}
      />

      <ol className="hdde-delivery-steps" aria-label="智能交付步骤">
        <li data-complete="true">选择成品</li>
        <li data-active="true">命名规则</li>
        <li>名称预览</li>
        <li>安全检查</li>
        <li>确认交付</li>
        <li>交付结果</li>
      </ol>

      {error ? <div className="hdde-delivery-alert" role="alert">{error}</div> : null}

      <div className="hdde-delivery-layout">
        <form className="hdde-delivery-rules" onSubmit={(event) => event.preventDefault()}>
          <div className="hdde-delivery-section-heading">
            <div><p className="hdde-eyebrow">命名规则</p><h2>设置最终文件名</h2></div>
            <span>{selectedIds.length} 份成品</span>
          </div>
          <RuleField label="基础名称">
            <select value={rules.base_mode} onChange={(event) => updateRule("base_mode", event.target.value)}>
              <option value="original">保留原文件名</option>
              <option value="custom">使用自定义基础名</option>
            </select>
          </RuleField>
          {rules.base_mode === "custom" ? (
            <RuleField label="自定义基础名">
              <input value={rules.base_name} onChange={(event) => updateRule("base_name", event.target.value)} />
            </RuleField>
          ) : null}
          <div className="hdde-delivery-two-column">
            <RuleField label="前缀"><input value={rules.prefix} onChange={(event) => updateRule("prefix", event.target.value)} /></RuleField>
            <RuleField label="后缀"><input value={rules.suffix} onChange={(event) => updateRule("suffix", event.target.value)} /></RuleField>
            <RuleField label="查找"><input value={rules.find_text} onChange={(event) => updateRule("find_text", event.target.value)} /></RuleField>
            <RuleField label="替换为"><input value={rules.replace_text} onChange={(event) => updateRule("replace_text", event.target.value)} /></RuleField>
          </div>
          <div className="hdde-delivery-option-row">
            <label><input type="checkbox" checked={rules.sequence_enabled} onChange={(event) => updateRule("sequence_enabled", event.target.checked)} />连续编号</label>
            <input aria-label="编号起始值" type="number" min="0" max="999999" value={rules.sequence_start} disabled={!rules.sequence_enabled} onChange={(event) => updateRule("sequence_start", Number(event.target.value))} />
            <select aria-label="编号位数" value={rules.sequence_padding} disabled={!rules.sequence_enabled} onChange={(event) => updateRule("sequence_padding", Number(event.target.value))}>
              <option value="1">1位</option><option value="2">2位</option><option value="3">3位</option><option value="4">4位</option>
            </select>
          </div>
          <label className="hdde-delivery-option-row hdde-delivery-date-option"><input type="checkbox" checked={rules.date_enabled} onChange={(event) => updateRule("date_enabled", event.target.checked)} />加入当天日期</label>
          <RuleField label="简单组合模板" helper="可用字段：{prefix} {base} {suffix} {date} {seq}">
            <input value={rules.template} onChange={(event) => updateRule("template", event.target.value)} />
          </RuleField>
        </form>

        <div className="hdde-delivery-review">
          <div className="hdde-delivery-section-heading">
            <div><p className="hdde-eyebrow">实时结果</p><h2>名称预览与安全检查</h2></div>
            <span data-state={preflightState}>{preflightState === "loading" ? "检查中" : preflight?.ready ? "可以交付" : "需要修正"}</span>
          </div>
          {preflight?.items?.length ? (
            <div className="hdde-delivery-preview-list" aria-label="最终交付名称预览">
              {preflight.items.map((item) => (
                <article key={item.item_id}>
                  <img src={item.preview_url} alt="" />
                  <div><span>{getFileDisplayName(item.source_file_name)}</span><strong>{item.delivery_file_name}</strong></div>
                </article>
              ))}
            </div>
          ) : null}
          {preflight?.issues?.length ? (
            <div className="hdde-delivery-blockers" role="alert">
              <strong>预检已阻止写入</strong>
              <ul>{preflight.issues.map((issue, index) => <li key={`${issue.code}-${issue.item_id}-${index}`}>{issue.file_name ? `${issue.file_name}：` : ""}{issue.message}</li>)}</ul>
            </div>
          ) : null}
          {preflight?.ready ? (
            <div className="hdde-delivery-ready" role="status">
              <strong>安全预检通过</strong>
              <span>未发现批次重名、目标冲突、非法字符、空名称、编号重复、过长名称或扩展名异常。</span>
              <span>交付位置：{preflight.delivery_location_label}</span>
            </div>
          ) : null}
          <label className="hdde-delivery-confirm">
            <input type="checkbox" checked={confirmed} disabled={!preflight?.ready || preflightState === "loading"} onChange={(event) => setConfirmed(event.target.checked)} />
            <span>我已核对源文件名与最终交付文件名，确认生成交付副本。</span>
          </label>
          <button type="button" className="hdde-primary-action hdde-delivery-submit" disabled={!preflight?.ready || !confirmed || executing} onClick={executeDelivery}>
            {executing ? "正在生成交付副本…" : "确认并生成交付副本"}
          </button>
        </div>
      </div>
    </section>
  );
}
