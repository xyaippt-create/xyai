import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./index.css";
import "./workbench.css";

function BrandedApplication() {
  const [showSplash, setShowSplash] = useState(true);

  useEffect(() => {
    // Browsers also match :focus-visible when a text field is clicked.
    const root = document.documentElement;
    const onPointer = () => root.setAttribute("data-pointer-focus", "");
    const onKey = (event) => {
      if (event.key === "Tab" || event.key.startsWith("Arrow") || event.key === "Escape") {
        root.removeAttribute("data-pointer-focus");
      }
    };
    window.addEventListener("pointerdown", onPointer, true);
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("pointerdown", onPointer, true);
      window.removeEventListener("keydown", onKey, true);
      root.removeAttribute("data-pointer-focus");
    };
  }, []);

  useEffect(() => {
    // Output Center's first-screen budget starts at navigation, not module readiness.
    const splashDelay = window.location.pathname === "/outputs"
      ? Math.max(0, 900 - window.performance.now())
      : 900;
    const timer = window.setTimeout(() => setShowSplash(false), splashDelay);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <>
      <App />
      {showSplash ? (
        <div className="hdde-startup-splash" role="status" aria-label="影界 HDDE 正在启动">
          <img className="hdde-startup-splash__image hdde-startup-splash__image--light" src="/branding/hdde/splash-light.png" alt="" />
          <img className="hdde-startup-splash__image hdde-startup-splash__image--dark" src="/branding/hdde/splash-dark.png" alt="" />
        </div>
      ) : null}
    </>
  );
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrandedApplication />
  </React.StrictMode>
);
