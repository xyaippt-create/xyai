import React from "react";

export function HddePageHeader({ title, description, meta = null, actions = null, headingId }) {
  return (
    <header className="hdde-page-header">
      <div className="hdde-page-header__copy">
        <div className="hdde-page-header__title-row">
          <h1 id={headingId}>{title}</h1>
          {meta}
        </div>
        {description ? <p className="hdde-page-header__description">{description}</p> : null}
      </div>
      {actions ? <div className="hdde-page-header__actions">{actions}</div> : null}
    </header>
  );
}

export function HddeStatusPill({ tone = "neutral", children }) {
  return <span className="hdde-status-pill" data-tone={tone}>{children}</span>;
}

export function HddeResultHero({ eyebrow = "处理结果", conclusion, tone = "neutral", title, summary, changes = [], protections = [], nextAction = "", actions = null }) {
  return (
    <section className="hdde-result-hero" data-tone={tone} aria-label="结果结论">
      <div className="hdde-result-hero__lead">
        <p className="hdde-eyebrow">{eyebrow}</p>
        <div className="hdde-result-hero__title-row">
          <span className="hdde-result-conclusion" data-tone={tone}>{conclusion}</span>
          <h2>{title}</h2>
        </div>
        {summary ? <p className="hdde-result-hero__summary">{summary}</p> : null}
      </div>
      <div className="hdde-result-hero__facts">
        {changes.length ? <div><span>处理前后变化</span><ul>{changes.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}
        {protections.length ? <div><span>安全保护</span><ul>{protections.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}
        {nextAction ? <div className="hdde-result-hero__next"><span>下一步</span><strong>{nextAction}</strong></div> : null}
      </div>
      {actions ? <div className="hdde-result-hero__actions">{actions}</div> : null}
    </section>
  );
}

export function HddeTechnicalDetails({ summary = "查看技术详情", children, className = "" }) {
  return <details className={`hdde-technical-details ${className}`.trim()}><summary>{summary}</summary><div className="hdde-technical-details__body">{children}</div></details>;
}

export function HddeSectionHeader({ eyebrow, title, description, aside = null, headingId }) {
  return (
    <header className="hdde-section-header">
      <div>
        {eyebrow ? <p className="hdde-eyebrow">{eyebrow}</p> : null}
        <h2 id={headingId}>{title}</h2>
        {description ? <p>{description}</p> : null}
      </div>
      {aside ? <div className="hdde-section-header__aside">{aside}</div> : null}
    </header>
  );
}
