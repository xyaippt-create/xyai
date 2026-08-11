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
