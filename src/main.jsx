import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./index.css";

function BrandedApplication() {
  const [showSplash, setShowSplash] = useState(true);

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
