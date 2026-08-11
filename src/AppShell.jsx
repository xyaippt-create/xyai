import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { APP_ROUTES } from "./appRoutes.js";
import HddeIcon from "./HddeIcon.jsx";
import UnifiedFeedback from "./UnifiedFeedback.jsx";

const THEME_STORAGE_KEY = "hdde-ui-theme";
const THEME_MODES = Object.freeze([
  { value: "system", label: "跟随系统" },
  { value: "dark", label: "深色" },
  { value: "light", label: "浅色" },
]);

const AppThemeContext = createContext(null);

const NAVIGATION_GROUPS = Object.freeze([
  { label: "工作台", items: ["processing", "image-diagnosis"] },
  { label: "图片处理", items: ["four-k-enhancement", "color-correction", "compression", "retouch"] },
  { label: "交付", items: ["outputs", "smart-delivery"] },
  { label: "系统", items: ["settings"] },
]);

const ROUTE_ICONS = Object.freeze({
  processing: "processing",
  "image-diagnosis": "diagnosis",
  "four-k-enhancement": "sparkle",
  "color-correction": "color",
  compression: "compress",
  retouch: "retouch",
  outputs: "outputs",
  "smart-delivery": "delivery",
  settings: "settings",
});

export function useAppTheme() {
  const context = useContext(AppThemeContext);
  if (!context) throw new Error("useAppTheme must be used inside AppShell.");
  return context;
}

function readStoredThemeMode() {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return THEME_MODES.some((option) => option.value === stored) ? stored : "system";
  } catch {
    return "system";
  }
}

function readSystemTheme() {
  if (typeof window.matchMedia !== "function") return "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function isPlainPrimaryClick(event) {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

export default function AppShell({ route, currentPath, onNavigate, children }) {
  const [themeMode, setThemeMode] = useState(readStoredThemeMode);
  const [systemTheme, setSystemTheme] = useState(readSystemTheme);
  const mainRef = useRef(null);
  const resolvedTheme = themeMode === "system" ? systemTheme : themeMode;

  useEffect(() => {
    if (themeMode !== "system" || typeof window.matchMedia !== "function") return undefined;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const syncSystemTheme = (event) => setSystemTheme(event.matches ? "dark" : "light");
    setSystemTheme(media.matches ? "dark" : "light");
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", syncSystemTheme);
      return () => media.removeEventListener("change", syncSystemTheme);
    }
    media.addListener(syncSystemTheme);
    return () => media.removeListener(syncSystemTheme);
  }, [themeMode]);

  useEffect(() => {
    document.documentElement.dataset.theme = resolvedTheme;
    document.documentElement.dataset.themeMode = themeMode;
    document.documentElement.style.colorScheme = resolvedTheme;
  }, [resolvedTheme, themeMode]);

  useEffect(() => {
    mainRef.current?.scrollTo({ top: 0, left: 0, behavior: "auto" });
    mainRef.current?.focus({ preventScroll: true });
  }, [currentPath]);

  const selectThemeMode = (nextMode) => {
    if (!THEME_MODES.some((option) => option.value === nextMode)) return;
    setThemeMode(nextMode);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, nextMode);
    } catch {
      // Theme still works for the current session when storage is unavailable.
    }
  };

  const handleNavigation = (event, path) => {
    if (!isPlainPrimaryClick(event)) return;
    event.preventDefault();
    onNavigate(path);
  };

  const themeContextValue = { themeMode, resolvedTheme, themeModes: THEME_MODES, selectThemeMode };
  const navigationRoutes = new Map(
    APP_ROUTES.filter((item) => item.showInNavigation !== false).map((item) => [item.key, item]),
  );

  return (
    <AppThemeContext.Provider value={themeContextValue}>
      <a className="hdde-skip-link" href="#hdde-main-content">跳到主要内容</a>
      <div className="hdde-app-shell" data-resolved-theme={resolvedTheme}>
      <aside className="hdde-sidebar" aria-label="影界HDDE一级导航">
        <div className="hdde-sidebar-brand">
          <span className="hdde-brand-mark" aria-hidden="true">界</span>
          <span className="hdde-brand-copy">
            <strong>影界 HDDE</strong>
            <small>高清交付引擎</small>
          </span>
        </div>

        <nav className="hdde-primary-navigation" aria-label="一级导航">
          {NAVIGATION_GROUPS.map((group) => {
            const routes = group.items.map((key) => navigationRoutes.get(key)).filter(Boolean);
            if (!routes.length) return null;
            return (
              <div className="hdde-navigation-group" key={group.label}>
                <p className="hdde-navigation-group__label">{group.label}</p>
                <div className="hdde-navigation-group__items">
                  {routes.map((item) => {
                    const active = item.path === currentPath;
                    return (
                      <a
                        key={item.key}
                        href={item.path}
                        title={item.name}
                        className={`hdde-navigation-item ${active ? "hdde-navigation-item--active" : ""}`}
                        aria-current={active ? "page" : undefined}
                        onClick={(event) => handleNavigation(event, item.path)}
                      >
                        <span className="hdde-navigation-icon"><HddeIcon name={ROUTE_ICONS[item.key]} /></span>
                        <span className="hdde-navigation-name">{item.name}</span>
                        <HddeIcon name="chevron" size={15} className="hdde-navigation-chevron" />
                      </a>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </nav>

        <div className="hdde-sidebar-footnote">
          <span aria-hidden="true" />
          <p><strong>本地工作区</strong><small>图片与结果留在设备中</small></p>
        </div>
      </aside>

      <div className="hdde-shell-main">
        <header className="hdde-topbar">
          <div className="hdde-topbar-inner">
            <div className="hdde-route-context" aria-label="当前位置">
              <span>影界 HDDE</span>
              <HddeIcon name="chevron" size={14} />
              <strong>{route?.pageTitle || "页面不存在"}</strong>
            </div>

            <div className="hdde-topbar-actions">
              <div className="hdde-theme-control" role="group" aria-label="界面主题">
                <HddeIcon name="sun" size={16} />
                <div className="hdde-theme-options">
                  {THEME_MODES.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      className={themeMode === option.value ? "is-selected" : ""}
                      aria-pressed={themeMode === option.value}
                      onClick={() => selectThemeMode(option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
              <UnifiedFeedback
                sourceFeature="runtime_failure"
                stage="application_runtime"
                triggerLabel="反馈问题"
                triggerClassName="hdde-topbar-feedback"
                testId="global-feedback-trigger"
              />
            </div>
          </div>
        </header>

        <main id="hdde-main-content" ref={mainRef} className="hdde-shell-content" tabIndex="-1">
          <div className="hdde-platform-surface">{children}</div>
        </main>
      </div>
      </div>
    </AppThemeContext.Provider>
  );
}
