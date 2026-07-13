import React, { createContext, useContext, useEffect, useState } from "react";
import { APP_ROUTES } from "./appRoutes.js";
import FeatureStatusBadge from "./FeatureStatusBadge.jsx";

const THEME_STORAGE_KEY = "hdde-ui-theme";
const THEME_MODES = Object.freeze([
  { value: "system", label: "跟随系统" },
  { value: "dark", label: "深色" },
  { value: "light", label: "浅色" },
]);

const AppThemeContext = createContext(null);

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

export default function AppShell({ route, currentPath, onNavigate, legacyDarkCompatibility = false, children }) {
  const [themeMode, setThemeMode] = useState(readStoredThemeMode);
  const [systemTheme, setSystemTheme] = useState(readSystemTheme);
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

  const showLegacyCompatibilityNotice = legacyDarkCompatibility && resolvedTheme === "light";
  const themeContextValue = { themeMode, resolvedTheme, themeModes: THEME_MODES, selectThemeMode };

  return (
    <AppThemeContext.Provider value={themeContextValue}>
      <div className="hdde-app-shell" data-resolved-theme={resolvedTheme}>
      <aside className="hdde-sidebar" aria-label="影界HDDE一级导航">
        <div className="hdde-sidebar-brand">
          <p className="hdde-eyebrow">多分辨率交付平台</p>
          <strong>影界 HDDE</strong>
          <span>UI Alpha平台底座</span>
        </div>

        <nav className="hdde-primary-navigation" aria-label="一级导航">
          {APP_ROUTES.map((item) => {
            const active = item.path === currentPath;
            return (
              <a
                key={item.key}
                href={item.path}
                className={`hdde-navigation-item ${active ? "hdde-navigation-item--active" : ""}`}
                aria-current={active ? "page" : undefined}
                onClick={(event) => handleNavigation(event, item.path)}
              >
                <span className="hdde-navigation-name">{item.name}</span>
                <FeatureStatusBadge status={item.status} compact source={`navigation:${item.key}`} />
              </a>
            );
          })}
        </nav>
      </aside>

      <div className="hdde-shell-main">
        <header className="hdde-topbar">
          <div className="hdde-current-page">
            <p className="hdde-eyebrow">当前页面</p>
            <div className="hdde-current-page-line">
              <h1>{route?.pageTitle || "页面不存在"}</h1>
              {route?.status ? <FeatureStatusBadge status={route.status} source={`topbar:${route.key}`} /> : null}
            </div>
            <p>{route?.description || "当前地址未对应已知页面。"}</p>
          </div>

          <div className="hdde-theme-control" role="group" aria-label="界面主题">
            <span>主题</span>
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
        </header>

        <main className={`hdde-shell-content ${legacyDarkCompatibility ? "hdde-shell-content--legacy" : ""}`}>
          {showLegacyCompatibilityNotice ? (
            <div className="hdde-legacy-notice" role="note">
              旧页面深色兼容区：当前业务页面保持原有深色视觉，功能与数据逻辑未改变。
            </div>
          ) : null}
          <div className={legacyDarkCompatibility ? "hdde-legacy-surface" : "hdde-platform-surface"}>{children}</div>
        </main>
      </div>
      </div>
    </AppThemeContext.Provider>
  );
}
