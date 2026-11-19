import React from "react";
import { currentBatchCandidate } from "./localRetouchBatch.js";

const LABELS = { ready: "待处理", queued: "排队中", processing: "修复中", candidate: "待另存", saved: "已另存", failed: "修复失败", excluded: "已排除", cancelled: "已取消" };

export default function RetouchBatchPanel({ batch, fullBatch, onGroupChange, intakeIssues, revision, activeId, skipped, busy, resumeMode, selectionError, canStart, canRetry, onSelect, onToggle, onStart, onRetry, onCancel, onClear }) {
  const hasFailed = batch.items.some((item) => item.status === "failed");
  const hasResults = batch.items.some((item) => currentBatchCandidate(item, revision));
  const excludedCount = fullBatch.items.length - fullBatch.total;
  const groupCounts = new Map();
  const exclusions = new Map();
  for (const item of fullBatch.items) {
    if (item.status !== "excluded") {
      groupCounts.set(item.group_id, (groupCounts.get(item.group_id) || 0) + 1);
      continue;
    }
    const reason = item.error?.replace(/^已排除[：:]/, "") || "未通过导入检查。";
    if (!exclusions.has(reason)) exclusions.set(reason, []);
    exclusions.get(reason).push(item.file_name);
  }
  return (
    <section className="hdde-retouch-batch" aria-label="同位置批量修复" data-testid="retouch-batch-panel">
      <div className="hdde-retouch-batch-header">
        <strong>同位置批量修复</strong>
        <button type="button" onClick={onClear} disabled={Boolean(busy) || batch.busy} title="清空当前工作区，保留历史批次和已另存成品">清空当前批次</button>
      </div>
      <div className="hdde-retouch-batch-intake-summary" data-testid="retouch-batch-intake-summary">
        <span>已检查 <b>{fullBatch.items.length}</b> 张</span>
        <span>通过 <b>{fullBatch.total}</b> 张</span>
        <span data-excluded={excludedCount > 0}>排除 <b>{excludedCount}</b> 张</span>
      </div>
      {fullBatch.groups.length > 1 ? <label>尺寸组
        <select className="hdde-retouch-import" value={batch.group_id} onChange={(event) => onGroupChange(event.target.value)} disabled={Boolean(busy) || batch.busy}>
          {fullBatch.groups.map((group) => <option key={group.group_id} value={group.group_id}>
            {group.width} × {group.height} · {groupCounts.get(group.group_id)} 张
          </option>)}
        </select>
      </label> : batch.total > 0 ? <p>本组尺寸 {batch.width} × {batch.height}</p> : null}
      {batch.total > 0 ? <p>选区仅用于本组，可切图核对位置、试修当前图。</p> : null}
      {excludedCount > 0 ? <details className="hdde-retouch-batch-exclusions" open data-testid="retouch-batch-exclusions">
        <summary id="retouch-batch-exclusion-summary">{excludedCount} 张已排除，执行时跳过</summary>
        <div className="hdde-retouch-batch-exclusion-reasons">
          {[...exclusions].map(([reason, names]) => <details key={reason}><summary>{names.length} 张 · {reason}</summary><p>{names.join("、")}</p></details>)}
        </div>
      </details> : null}
      <div role="status" aria-live="polite">{batch.busy ? "处理中" : batch.status === "cancelled" ? "已取消后续处理" : "本组进度"}：{batch.finished} / {batch.total}</div>
      {selectionError || batch.error ? <p role="alert">{selectionError || batch.error}</p> : null}
      {intakeIssues.length ? <details open>
        <summary>{intakeIssues.length} 张未确认导入</summary>
        <p>可继续处理已导入图片。请核对下列图片后再重新导入。</p>
        {intakeIssues.map((item) => <p key={item.clientItemId}>{item.fileName} · {item.reason}</p>)}
      </details> : null}
      <progress max={Math.max(1, batch.total)} value={batch.finished} aria-label="本组修复进度" />
      <ul>
        {batch.items.map((item, index) => {
          const candidate = currentBatchCandidate(item, revision);
          const stale = item.candidate && !candidate;
          const canSelect = candidate && item.status === "candidate" && (!selectionError || item.retried);
          const viewLabel = candidate ? (item.status === "saved" ? "查看成品" : "查看候选")
            : item.preview?.mask_revision === revision ? "查看试修" : "查看覆盖";
          return (
            <li key={item.item_id} data-status={item.status}>
              <label>
                {canSelect ? <input type="checkbox" aria-label={`另存 ${item.file_name}`} checked={!skipped.includes(item.item_id)} disabled={Boolean(busy) || batch.busy} onChange={() => onToggle(item.item_id)} /> : null}
                <span>{index + 1}. {item.file_name}</span>
              </label>
              <button type="button" aria-pressed={activeId === item.item_id} disabled={Boolean(busy) || !item.source || item.status === "excluded"} onClick={() => onSelect(item)}>{viewLabel}</button>
              <span>{item.status === "saved" ? LABELS.saved : stale ? "选区已变，需重新修复" : candidate && item.retried ? "已用原选区重试 · 待另存" : LABELS[item.status]}</span>
              {item.error ? <span role="alert">{item.error}</span> : null}
              {item.source_error ? <span role="alert">{item.source_error}</span> : null}
              {item.candidate_error ? <span role="alert">{item.candidate_error}</span> : null}
            </li>
          );
        })}
      </ul>
      <button type="button" className={hasResults ? "hdde-secondary-action" : "hdde-primary-action"} onClick={onStart} disabled={!canStart} aria-describedby={excludedCount ? "retouch-batch-exclusion-summary" : undefined}>{resumeMode ? "继续未完成项" : fullBatch.groups.length > 1 ? "使用当前选区修复本组" : "使用当前选区执行整批"}</button>
      {hasFailed ? <button type="button" onClick={onRetry} disabled={!canRetry}>仅重试失败项</button> : null}
      {batch.busy ? <button type="button" onClick={onCancel} disabled={batch.cancel_requested || batch.status !== "processing"}>{batch.cancel_requested ? "正在停止后续图片…" : "取消后续处理"}</button> : null}
      {!batch.busy && batch.items.some((item) => item.status === "candidate") ? <p>取消勾选可跳过该图。</p> : null}
    </section>
  );
}
