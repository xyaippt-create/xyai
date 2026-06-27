import React, { useState } from 'react';
import LaunchPage from "./LaunchPage.jsx";
import DashboardPage from "./DashboardPage.jsx";
import TaskDetailPage from "./TaskDetailPage.jsx";
import ImageSliderComparePage from "./ImageSliderComparePage.jsx";
import QualityReportPage from "./QualityReportPage.jsx";
import Safe1080pBetaPage from "./Safe1080pBetaPage.jsx";

export default function App() {
  const [viewState, setViewState] = useState(() => (window.location.pathname === "/safe-1080p-beta" ? "safe_1080p_beta" : "launch"));
  const [runtimeSnapshot, setRuntimeSnapshot] = useState(null);
  const [taskConfig, setTaskConfig] = useState(null);
  const [compareAssets, setCompareAssets] = useState(null);

  const navigateTo = (nextView, path = "/") => {
    if (window.location.pathname !== path) {
      window.history.pushState({}, "", path);
    }
    setViewState(nextView);
  };

  const handleEnterDashboard = (snapshot) => {
    setRuntimeSnapshot(snapshot);
    navigateTo("dashboard");
  };

  const handleStartTask = (config) => {
    const nextAssets = config?.compareAssets || compareAssets || config;
    setCompareAssets(nextAssets);
    setTaskConfig({ ...config, compareAssets: nextAssets });
    setViewState("task_detail");
  };

  const handleViewCompare = () => {
    setViewState("image_compare");
  };

  const handleViewReport = () => {
    setViewState("quality_report");
  };

  const handleArchiveAndReset = () => {
    setTaskConfig(null);
    setCompareAssets(null);
    navigateTo("dashboard");
  };

  if (viewState === "launch") {
    return (
      <main className="min-h-screen bg-polar-950 text-polar-100">
        <LaunchPage onEnter={handleEnterDashboard} onOpenSafeBeta={() => navigateTo("safe_1080p_beta", "/safe-1080p-beta")} />
      </main>
    );
  }

  if (viewState === "safe_1080p_beta") {
    return (
      <main className="min-h-screen bg-polar-950 text-polar-100">
        <Safe1080pBetaPage onBackToDashboard={() => navigateTo("dashboard")} />
      </main>
    );
  }

  if (viewState === "task_detail") {
    return (
      <main className="min-h-screen bg-polar-950 text-polar-100">
        <TaskDetailPage
          taskConfig={taskConfig}
          onBackToDashboard={() => setViewState("dashboard")}
          onViewCompare={handleViewCompare}
        />
      </main>
    );
  }

  if (viewState === "image_compare") {
    return (
      <main className="min-h-screen bg-polar-950 text-polar-100">
        <ImageSliderComparePage
          taskConfig={taskConfig}
          compareAssets={compareAssets || taskConfig?.compareAssets}
          onBackToTask={() => setViewState("task_detail")}
          onViewReport={handleViewReport}
        />
      </main>
    );
  }

  if (viewState === "quality_report") {
    return (
      <main className="min-h-screen bg-polar-950 text-polar-100">
        <QualityReportPage
          taskConfig={taskConfig}
          onBackToCompare={() => setViewState("image_compare")}
          onArchive={handleArchiveAndReset}
        />
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-polar-950 text-polar-100">
      <DashboardPage
        runtimeSnapshot={runtimeSnapshot}
        onBackToLaunch={() => setViewState("launch")}
        onStartTask={handleStartTask}
        onUploadComplete={setCompareAssets}
      />
    </main>
  );
}
