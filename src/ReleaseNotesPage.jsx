import React from "react";
import { HddePageHeader } from "./HddeUI.jsx";
import { PRODUCT_VERSION } from "./productVersion.js";
import { RELEASE_NOTES } from "./releaseNotes.js";

export default function ReleaseNotesPage({ onNavigate }) {
  const backToSettings = (event) => {
    if (!onNavigate) return;
    event.preventDefault();
    onNavigate("/settings");
  };

  return (
    <div className="hdde-settings-page hdde-page-frame hdde-page-stack" data-testid="release-notes-page">
      <HddePageHeader
        title="更新日志"
        description="各版本面向使用者的主要变化，最新版本在前。"
        actions={<a className="hdde-secondary-action hdde-release-notes-back" href="/settings" onClick={backToSettings}>返回系统设置</a>}
      />
      <section className="hdde-settings-section">
        <div className="hdde-settings-section__body">
          <div className="hdde-settings-releases" data-testid="settings-release-notes">
            {RELEASE_NOTES.map((release, index) => {
              const current = release.version === PRODUCT_VERSION;
              return (
                <details key={release.version} className="hdde-settings-release" open={index === 0}>
                  <summary>
                    <strong>{release.label}</strong>
                    {current ? <span className="hdde-settings-fact" data-tone="positive">当前版本</span> : null}
                    <time dateTime={release.date}>{release.date}</time>
                  </summary>
                  {release.groups.map((group) => (
                    <section key={group.title} className="hdde-settings-release__group">
                      <h2>{group.title}</h2>
                      <ul>
                        {group.items.map((item) => <li key={item}>{item}</li>)}
                      </ul>
                    </section>
                  ))}
                </details>
              );
            })}
          </div>
        </div>
      </section>
    </div>
  );
}
