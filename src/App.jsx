import React, { useCallback, useEffect, useMemo, useState } from "react";
import AppShell from "./AppShell.jsx";
import DashboardPage from "./DashboardPage.jsx";
import ImageSliderComparePage from "./ImageSliderComparePage.jsx";
import QualityReportPage from "./QualityReportPage.jsx";
import Safe1080pBetaPage from "./Safe1080pBetaPage.jsx";
import FeaturePlaceholderPage, { UnknownRoutePage } from "./FeaturePlaceholderPage.jsx";
import { DEFAULT_APP_PATH, findAppRoute, normalizeAppPath } from "./appRoutes.js";
import { validateComparisonAssets, validateQualityReport } from "./platformStatus.js";

function initialPathFromBrowser() {
  const current = normalizeAppPath(window.location.pathname);
  if (current === "/") {
    window.history.replaceState({}, "", DEFAULT_APP_PATH);
    return DEFAULT_APP_PATH;
  }
  if (current !== window.location.pathname) {
    window.history.replaceState({}, "", current);
  }
  return current;
}

function isNonEmptyRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length > 0;
}

function ExistingPageEmptyState({ title, description, onBackToProcessing }) {
  return (
    <section className="hdde-placeholder-page" aria-labelledby="existing-empty-title">
      <div className="hdde-placeholder-card hdde-existing-empty-card">
        <p className="hdde-eyebrow">真实空状态</p>
        <h1 id="existing-empty-title">{title}</h1>
        <p className="hdde-placeholder-description">{description}</p>
        <div className="hdde-placeholder-notice" role="note">
          <strong>当前没有可展示的真实任务数据。</strong>
          <span>本页不会生成Mock图片、评分、文件路径或交付结论。</span>
        </div>
        <button type="button" className="hdde-primary-action" onClick={onBackToProcessing}>
          返回处理中心
        </button>
      </div>
    </section>
  );
}

export default function App() {
  const [currentPath, setCurrentPath] = useState(initialPathFromBrowser);
  const [taskContext, setTaskContext] = useState(null);

  const navigateTo = useCallback((nextPath, options = {}) => {
    const normalized = normalizeAppPath(nextPath);
    const targetPath = normalized === "/" ? DEFAULT_APP_PATH : normalized;
    if (window.location.pathname !== targetPath) {
      const method = options.replace ? "replaceState" : "pushState";
      window.history[method]({}, "", targetPath);
    }
    setCurrentPath(targetPath);
  }, []);

  useEffect(() => {
    const handlePopState = () => {
      const nextPath = normalizeAppPath(window.location.pathname);
      if (nextPath === "/") {
        window.history.replaceState({}, "", DEFAULT_APP_PATH);
        setCurrentPath(DEFAULT_APP_PATH);
        return;
      }
      setCurrentPath(nextPath);
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const route = useMemo(() => findAppRoute(currentPath), [currentPath]);
  const compareValidation = useMemo(
    () => validateComparisonAssets(taskContext?.comparisonAssets, { taskId: taskContext?.taskId }),
    [taskContext?.comparisonAssets, taskContext?.taskId],
  );
  const reportValidation = useMemo(
    () => validateQualityReport(taskContext?.taskReport, { taskId: taskContext?.taskId, taskResult: taskContext?.taskResult }),
    [taskContext?.taskId, taskContext?.taskReport, taskContext?.taskResult],
  );

  const rememberTaskContext = useCallback((nextContext) => {
    if (!nextContext?.taskId) return;
    setTaskContext((previous) => {
      const isNewTask = previous?.taskId !== nextContext.taskId;
      return {
        taskId: nextContext.taskId,
        taskResult: isNonEmptyRecord(nextContext.taskResult)
          ? nextContext.taskResult
          : isNewTask
            ? null
            : previous?.taskResult || null,
        taskReport: isNonEmptyRecord(nextContext.taskReport)
          ? nextContext.taskReport
          : isNewTask
            ? null
            : previous?.taskReport || null,
        debugQuality: isNonEmptyRecord(nextContext.debugQuality)
          ? nextContext.debugQuality
          : isNewTask
            ? null
            : previous?.debugQuality || null,
        comparisonAssets: nextContext.comparisonAssets || (isNewTask ? null : previous?.comparisonAssets || null),
      };
    });
  }, []);

  const clearTaskContext = () => {
    setTaskContext(null);
    navigateTo(DEFAULT_APP_PATH);
  };

  let content = null;
  let legacyDarkCompatibility = false;

  if (!route) {
    content = <UnknownRoutePage pathname={currentPath} onBackToProcessing={() => navigateTo(DEFAULT_APP_PATH)} />;
  } else if (route.key === "processing") {
    legacyDarkCompatibility = true;
  } else if (route.key === "compare") {
    if (compareValidation.valid) {
      legacyDarkCompatibility = true;
      const compareAssets = {
        taskId: taskContext.taskId,
        originalUrl: taskContext.comparisonAssets.originalUrl,
        preview_output_url: taskContext.comparisonAssets.resultUrl,
      };
      content = (
        <ImageSliderComparePage
          taskConfig={{
            taskId: taskContext.taskId,
            task_id: taskContext.taskId,
            task_result: taskContext.taskResult || {},
            task_report: taskContext.taskReport || {},
            debug_quality: taskContext.debugQuality || {},
            compareAssets,
          }}
          compareAssets={compareAssets}
          onBackToTask={() => navigateTo(DEFAULT_APP_PATH)}
          onViewReport={() => navigateTo("/quality-report")}
        />
      );
    } else {
      content = (
        <ExistingPageEmptyState
          title="尚无可用对比任务"
          description="请先在处理中心选择并完成真实任务，再进入对比质检查看原图和结果图。"
          onBackToProcessing={() => navigateTo(DEFAULT_APP_PATH)}
        />
      );
    }
  } else if (route.key === "quality-report") {
    if (reportValidation.valid) {
      legacyDarkCompatibility = true;
      content = (
        <QualityReportPage
          taskConfig={{
            taskId: taskContext.taskId,
            task_id: taskContext.taskId,
            task_result: taskContext.taskResult,
            task_report: taskContext.taskReport,
            debug_quality: taskContext.debugQuality || {},
          }}
          onBackToCompare={() => navigateTo("/compare")}
          onArchive={clearTaskContext}
        />
      );
    } else {
      content = (
        <ExistingPageEmptyState
          title="尚无可用质量报告"
          description="当前任务尚未生成结构完整的真实质量报告。本页不会展示评分、风险或交付建议。"
          onBackToProcessing={() => navigateTo(DEFAULT_APP_PATH)}
        />
      );
    }
  } else if (route.key === "safe-1080p-beta") {
    legacyDarkCompatibility = true;
    content = <Safe1080pBetaPage onBackToDashboard={() => navigateTo(DEFAULT_APP_PATH)} />;
  } else {
    content = <FeaturePlaceholderPage route={route} />;
  }

  return (
    <AppShell
      route={route}
      currentPath={currentPath}
      onNavigate={navigateTo}
      legacyDarkCompatibility={legacyDarkCompatibility}
    >
      <div
        hidden={route?.key !== "processing"}
        aria-hidden={route?.key !== "processing"}
        inert={route?.key !== "processing" ? "" : undefined}
      >
        <DashboardPage onTaskContextChange={rememberTaskContext} />
      </div>
      {route?.key === "processing" ? null : content}
    </AppShell>
  );
}
