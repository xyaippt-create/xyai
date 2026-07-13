import React from "react";
import FeatureStatusBadge from "./FeatureStatusBadge.jsx";

export default function FeaturePlaceholderPage({ route }) {
  const capabilities = Array.isArray(route?.plannedCapabilities) ? route.plannedCapabilities : [];
  return (
    <section className="hdde-placeholder-page" aria-labelledby={`page-title-${route.key}`}>
      <div className="hdde-placeholder-card">
        <div className="hdde-placeholder-heading">
          <div>
            <p className="hdde-eyebrow">UI Alpha占位</p>
            <h1 id={`page-title-${route.key}`}>{route.pageTitle}</h1>
            <p className="hdde-placeholder-formal-name">一级功能：{route.name}</p>
          </div>
          <FeatureStatusBadge status={route.status} source={`route:${route.key}`} />
        </div>

        <p className="hdde-placeholder-description">{route.description}</p>

        <div className="hdde-placeholder-notice" role="note">
          <strong>尚未接入真实处理能力。</strong>
          <span>本页仅建立平台结构与能力边界，不生成任务、文件、评分或处理结果。</span>
        </div>

        <div className="hdde-placeholder-preview" aria-label="计划能力">
          <h2>主要计划能力</h2>
          <ul>
            {capabilities.map((capability) => (
              <li key={capability}>{capability}</li>
            ))}
          </ul>
          <p>界面结构预览，不代表功能已经接入。</p>
        </div>
      </div>
    </section>
  );
}

export function UnknownRoutePage({ pathname, onBackToProcessing }) {
  return (
    <section className="hdde-placeholder-page" aria-labelledby="unknown-route-title">
      <div className="hdde-placeholder-card hdde-not-found-card">
        <p className="hdde-eyebrow">404</p>
        <h1 id="unknown-route-title">页面不存在</h1>
        <p className="hdde-placeholder-description">当前地址未对应影界HDDE的已知页面。</p>
        <code className="hdde-unknown-path">{pathname}</code>
        <button type="button" className="hdde-primary-action" onClick={onBackToProcessing}>
          返回处理中心
        </button>
      </div>
    </section>
  );
}
