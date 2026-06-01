import React, { useState } from 'react';
import LaunchPage from "./LaunchPage.jsx";
import DashboardPage from "./DashboardPage.jsx";
import TaskDetailPage from "./TaskDetailPage.jsx";
import ImageComparePage from "./ImageComparePage.jsx";
import QualityReportPage from "./QualityReportPage.jsx";

export default function App() {
  const [viewState, setViewState] = useState("launch");
  const [runtimeSnapshot, setRuntimeSnapshot] = useState(null);
  const [taskConfig, setTaskConfig] = useState(null);
  const [compareAssets, setCompareAssets] = useState(null);

  const handleEnterDashboard = (snapshot) => {
    setRuntimeSnapshot(snapshot);
    setViewState("dashboard");
  };

  const handleStartTask = (config) => {
    setTaskConfig({ ...config, compareAssets });
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
    setViewState("dashboard");
  };

  if (viewState === "launch") {
    return (
      <main className="min-h-screen bg-polar-950 text-polar-100">
        <LaunchPage onEnter={handleEnterDashboard} />
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
        <ImageComparePage
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
