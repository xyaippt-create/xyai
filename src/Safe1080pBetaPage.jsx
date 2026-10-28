import React, { useEffect } from "react";

export default function Safe1080pBetaPage({ onBackToDashboard }) {
  useEffect(() => {
    onBackToDashboard?.();
  }, [onBackToDashboard]);

  return (
    <section className="hdde-placeholder-page" aria-live="polite" data-testid="safe-1080p-entry-page">
      <div className="hdde-placeholder-card hdde-existing-empty-card">
        <p className="hdde-eyebrow">历史兼容入口</p>
        <h1>正在进入1080P画质</h1>
        <p className="hdde-placeholder-description">当前入口已合并到正式处理中心，历史任务和内部处理标识保持兼容。</p>
      </div>
    </section>
  );
}
