import React, { useCallback, useEffect, useMemo, useState } from "react";
import AppShell from "./AppShell.jsx";
import DashboardPage from "./DashboardPage.jsx";
import ImageSliderComparePage from "./ImageSliderComparePage.jsx";
import QualityReportPage from "./QualityReportPage.jsx";
import TaskDetailPage from "./TaskDetailPage.jsx";
import Safe1080pBetaPage from "./Safe1080pBetaPage.jsx";
import CompressionPage from "./CompressionPage.jsx";
import ColorCorrectionPage from "./ColorCorrectionPage.jsx";
import SystemSettingsPage from "./SystemSettingsPage.jsx";
import FeaturePlaceholderPage, { UnknownRoutePage } from "./FeaturePlaceholderPage.jsx";
import FourKEnhancementPage from "./FourKEnhancementPage.jsx";
import OutputCenterPage from "./OutputCenterPage.jsx";
import SmartDeliveryPage from "./SmartDeliveryPage.jsx";
import LocalRetouchPage from "./LocalRetouchPage.jsx";
import ImageDiagnosisPage from "./ImageDiagnosisPage.jsx";
import { DEFAULT_APP_PATH, findAppRoute, normalizeAppPath } from "./appRoutes.js";
import { validateComparisonAssets, validateQualityReport } from "./platformStatus.js";

const API_BASE = "http://localhost:8787";
const TASK_ROUTES = new Set(["task-detail", "task-compare", "task-report"]);
const LEGACY_TASK_ROUTES = Object.freeze({
  compare: "/task-detail/compare",
  "quality-report": "/task-detail/report",
});

function browserPath() {
  return `${window.location.pathname}${window.location.search}`;
}

function initialPathFromBrowser() {
  const current = normalizeAppPath(window.location.pathname);
  if (current === "/") {
    window.history.replaceState({}, "", DEFAULT_APP_PATH);
    return DEFAULT_APP_PATH;
  }
  if (current !== window.location.pathname) {
    window.history.replaceState({}, "", `${current}${window.location.search}`);
  }
  return browserPath();
}

function isNonEmptyRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length > 0;
}

function normalizeApiUrl(value) {
  if (!value) return "";
  if (/^https?:\/\//i.test(value)) return value;
  if (/^[a-zA-Z]:[\\/]/.test(value) || /^\\\\/.test(value)) return "";
  return `${API_BASE}${value.startsWith("/") ? value : `/${value}`}`;
}

function taskToContext(task) {
  const taskId = task?.task_id || task?.taskId || "";
  const taskResult = task?.task_result || {};
  const taskReport = task?.task_report || {};
  const originalUrl = normalizeApiUrl(task?.originalUrl || task?.original_url || taskResult?.originalUrl);
  const resultUrl = normalizeApiUrl(
    taskResult?.preview_output_url
      || task?.preview_output_url
      || taskResult?.final_output_url
      || task?.final_output_url
      || task?.enhancedUrl,
  );
  if (!taskId) return null;
  return {
    taskId,
    mode: task?.mode || taskResult?.mode || "",
    taskConfig: task,
    taskResult,
    taskReport,
    debugQuality: task?.debug_quality || taskResult?.debug_quality || {},
    comparisonAssets: originalUrl && resultUrl ? { originalUrl, resultUrl } : null,
  };
}

async function fetchTask(taskId) {
  const response = await fetch(`${API_BASE}/api/v1/tasks/${encodeURIComponent(taskId)}`);
  const payload = await response.json();
  if (!response.ok || payload?.success === false) {
    throw new Error(payload?.detail || payload?.message || "任务不存在");
  }
  return taskToContext(payload?.data || payload?.task || payload);
}

function ExistingPageEmptyState({ title, description, onBackToProcessing }) {
  return (
    <section className="hdde-placeholder-page" aria-labelledby="existing-empty-title">
      <div className="hdde-placeholder-card hdde-existing-empty-card">
        <p className="hdde-eyebrow">任务数据不可用</p>
        <h1 id="existing-empty-title">{title}</h1>
        <p className="hdde-placeholder-description">{description}</p>
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
  const [taskLoadState, setTaskLoadState] = useState("idle");
  const [sourceHandoff, setSourceHandoff] = useState(null);
  const [taskRegistryRevision, setTaskRegistryRevision] = useState(0);

  const navigateTo = useCallback((nextPath, options = {}) => {
    const [pathPart, queryPart = ""] = String(nextPath || DEFAULT_APP_PATH).split("?", 2);
    const normalized = normalizeAppPath(pathPart);
    const pathname = normalized === "/" ? DEFAULT_APP_PATH : normalized;
    const targetPath = `${pathname}${queryPart ? `?${queryPart}` : ""}`;
    if (browserPath() !== targetPath) {
      const method = options.replace ? "replaceState" : "pushState";
      window.history[method]({}, "", targetPath);
    }
    setCurrentPath(targetPath);
  }, []);

  const consumeSourceHandoff = useCallback((requestId) => {
    setSourceHandoff((current) => current?.requestId === requestId ? null : current);
  }, []);

  const handleDiagnosisRecommendation = useCallback(({ action, sourceFile, taskId }) => {
    const targets = {
      "4K高清增强": { path: "/processing?mode=4k_v1", routeKey: "processing" },
      "1080P安全增强": { path: "/processing?mode=safe_1080p_beta", routeKey: "processing" },
      "1080P标准增强": { path: "/processing?mode=standard", routeKey: "processing" },
      "颜色校正": { path: "/color-correction", routeKey: "color-correction" },
      "图片压缩": { path: "/compression", routeKey: "compression" },
    };
    const target = targets[action];
    if (!target || !sourceFile) return;
    const requestId = `${taskId || "diagnosis"}-${Date.now()}`;
    setSourceHandoff({ requestId, sourceFile, routeKey: target.routeKey });
    navigateTo(`${target.path}${target.path.includes("?") ? "&" : "?"}from=image-diagnosis`);
  }, [navigateTo]);

  useEffect(() => {
    const handlePopState = () => {
      if (normalizeAppPath(window.location.pathname) === "/") {
        window.history.replaceState({}, "", DEFAULT_APP_PATH);
        setCurrentPath(DEFAULT_APP_PATH);
        return;
      }
      setCurrentPath(browserPath());
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const routePath = normalizeAppPath(currentPath);
  const route = useMemo(() => findAppRoute(routePath), [routePath]);

  const rememberTaskContext = useCallback((nextContext) => {
    if (!nextContext?.taskId) return;
    setTaskContext((previous) => {
      const isNewTask = previous?.taskId !== nextContext.taskId;
      return {
        taskId: nextContext.taskId,
        mode: nextContext.mode || (isNewTask ? "" : previous?.mode || ""),
        taskConfig: nextContext.taskConfig || (isNewTask ? null : previous?.taskConfig || null),
        taskResult: isNonEmptyRecord(nextContext.taskResult)
          ? nextContext.taskResult
          : isNewTask ? null : previous?.taskResult || null,
        taskReport: isNonEmptyRecord(nextContext.taskReport)
          ? nextContext.taskReport
          : isNewTask ? null : previous?.taskReport || null,
        debugQuality: isNonEmptyRecord(nextContext.debugQuality)
          ? nextContext.debugQuality
          : isNewTask ? null : previous?.debugQuality || null,
        comparisonAssets: nextContext.comparisonAssets
          || (isNewTask ? null : previous?.comparisonAssets || null),
      };
    });
  }, []);

  useEffect(() => {
    if (!route) return;
    const query = new URLSearchParams(window.location.search);
    const taskId = query.get("task_id") || "";
    const legacyTarget = LEGACY_TASK_ROUTES[route.key];
    if (legacyTarget) {
      navigateTo(taskId ? `${legacyTarget}?task_id=${encodeURIComponent(taskId)}` : DEFAULT_APP_PATH, { replace: true });
      return;
    }
    if (!TASK_ROUTES.has(route.key)) return;
    if (!taskId) {
      navigateTo(DEFAULT_APP_PATH, { replace: true });
      return;
    }
    if (taskContext?.taskId === taskId) {
      setTaskLoadState("ready");
      return;
    }
    let active = true;
    setTaskLoadState("loading");
    fetchTask(taskId)
      .then((context) => {
        if (!active || !context) return;
        rememberTaskContext(context);
        setTaskLoadState("ready");
      })
      .catch(() => {
        if (!active) return;
        setTaskLoadState("missing");
        navigateTo(DEFAULT_APP_PATH, { replace: true });
      });
    return () => {
      active = false;
    };
  }, [navigateTo, rememberTaskContext, route, taskContext?.taskId]);

  const taskUrl = useCallback(
    (suffix = "", taskId = taskContext?.taskId) => (
      taskId ? `/task-detail${suffix}?task_id=${encodeURIComponent(taskId)}` : DEFAULT_APP_PATH
    ),
    [taskContext?.taskId],
  );

  const compareValidation = useMemo(
    () => validateComparisonAssets(taskContext?.comparisonAssets, { taskId: taskContext?.taskId }),
    [taskContext?.comparisonAssets, taskContext?.taskId],
  );
  const reportValidation = useMemo(
    () => validateQualityReport(taskContext?.taskReport, {
      taskId: taskContext?.taskId,
      taskResult: taskContext?.taskResult,
      mode: taskContext?.mode,
    }),
    [taskContext?.mode, taskContext?.taskId, taskContext?.taskReport, taskContext?.taskResult],
  );

  const taskConfig = taskContext ? {
    ...(taskContext.taskConfig || {}),
    taskId: taskContext.taskId,
    task_id: taskContext.taskId,
    mode: taskContext.mode,
    task_result: taskContext.taskResult || {},
    task_report: taskContext.taskReport || {},
    debug_quality: taskContext.debugQuality || {},
  } : null;

  let content = null;
  if (!route) {
    content = <UnknownRoutePage pathname={routePath} onBackToProcessing={() => navigateTo(DEFAULT_APP_PATH)} />;
  } else if (["processing", "history"].includes(route.key)) {
    content = null;
  } else if (route.key === "task-detail") {
    content = taskConfig && taskLoadState !== "loading" ? (
      <TaskDetailPage
        taskConfig={taskConfig}
        onBackToDashboard={() => navigateTo(DEFAULT_APP_PATH)}
        onViewCompare={() => navigateTo(taskUrl("/compare"))}
        onViewReport={() => navigateTo(taskUrl("/report"))}
        onReprocess={() => navigateTo(`${DEFAULT_APP_PATH}?mode=${encodeURIComponent(taskContext.mode || "standard")}`)}
      />
    ) : (
      <ExistingPageEmptyState
        title="正在读取任务"
        description="正在从本地处理服务读取真实任务信息。"
        onBackToProcessing={() => navigateTo(DEFAULT_APP_PATH)}
      />
    );
  } else if (route.key === "task-compare") {
    if (compareValidation.valid) {
      const compareAssets = {
        taskId: taskContext.taskId,
        originalUrl: taskContext.comparisonAssets.originalUrl,
        preview_output_url: taskContext.comparisonAssets.resultUrl,
        mode: taskContext.mode,
        task_result: taskContext.taskResult || {},
        task_report: taskContext.taskReport || {},
      };
      content = (
        <ImageSliderComparePage
          taskConfig={{ ...taskConfig, compareAssets }}
          compareAssets={compareAssets}
          onBackToTask={() => navigateTo(taskUrl())}
          onViewReport={() => navigateTo(taskUrl("/report"))}
        />
      );
    } else {
      content = (
        <ExistingPageEmptyState
          title="当前任务暂无可用对比"
          description="请等待当前任务生成可读取的原图与结果图。"
          onBackToProcessing={() => navigateTo(taskUrl())}
        />
      );
    }
  } else if (route.key === "task-report") {
    if (reportValidation.valid) {
      content = (
        <QualityReportPage
          taskConfig={taskConfig}
          onBackToCompare={() => navigateTo(taskUrl("/compare"))}
          onArchive={() => navigateTo(taskUrl())}
        />
      );
    } else {
      content = (
        <ExistingPageEmptyState
          title="当前任务暂无完整报告"
          description="任务详情仍可查看真实状态、输出信息和问题反馈入口。"
          onBackToProcessing={() => navigateTo(taskUrl())}
        />
      );
    }
  } else if (route.key === "safe-1080p-beta") {
    content = <Safe1080pBetaPage onBackToDashboard={() => navigateTo(DEFAULT_APP_PATH)} />;
  } else if (route.key === "four-k-enhancement") {
    content = (
      <FourKEnhancementPage
        onOpenSharedProcessing={() => navigateTo("/processing?mode=4k_v1", { replace: true })}
      />
    );
  } else if (route.key === "compression") {
    content = (
      <CompressionPage
        initialSourceFile={sourceHandoff?.routeKey === "compression" ? sourceHandoff.sourceFile : null}
        initialSourceRequestId={sourceHandoff?.routeKey === "compression" ? sourceHandoff.requestId : ""}
        onInitialSourceConsumed={consumeSourceHandoff}
      />
    );
  } else if (route.key === "color-correction") {
    content = (
      <ColorCorrectionPage
        onOpenProcessing={(batchId) => navigateTo(`/processing?batch=${encodeURIComponent(batchId)}`)}
        initialSourceFile={sourceHandoff?.routeKey === "color-correction" ? sourceHandoff.sourceFile : null}
        initialSourceRequestId={sourceHandoff?.routeKey === "color-correction" ? sourceHandoff.requestId : ""}
        onInitialSourceConsumed={consumeSourceHandoff}
      />
    );
  } else if (route.key === "color-correction-review") {
    const query = new URLSearchParams(window.location.search);
    const reviewTaskId = query.get("task_id") || "";
    const reviewBatchId = query.get("batch") || "";
    const returnToOutputs = query.get("from") === "outputs";
    content = reviewTaskId ? (
      <ColorCorrectionPage
        reviewTaskId={reviewTaskId}
        reviewBatchId={reviewBatchId}
        reviewReturnLabel={returnToOutputs ? "返回输出中心" : "返回批次"}
        onBackToProcessing={(batchId) => navigateTo(returnToOutputs ? "/outputs" : (batchId ? `/processing?batch=${encodeURIComponent(batchId)}` : "/processing"))}
      />
    ) : (
      <ExistingPageEmptyState
        title="缺少可复核结果"
        description="请从处理中心选择一张已完成的颜色校正结果。"
        onBackToProcessing={() => navigateTo(DEFAULT_APP_PATH)}
      />
    );
  } else if (route.key === "outputs") {
    content = <OutputCenterPage onNavigate={navigateTo} />;
  } else if (route.key === "output-compare") {
    const compareItemId = new URLSearchParams(window.location.search).get("item") || "";
    content = (
      <OutputCenterPage
        compareItemId={compareItemId}
        onNavigate={navigateTo}
        onBackFromCompare={() => navigateTo("/outputs")}
      />
    );
  } else if (route.key === "smart-delivery") {
    const searchParams = new URLSearchParams(window.location.search);
    const selectedItemIds = (searchParams.get("items") || "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const selectedResultIds = (searchParams.get("results") || "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    content = (
      <SmartDeliveryPage
        selectedItemIds={selectedItemIds}
        selectedResultIds={selectedResultIds}
        onBackToOutputs={() => navigateTo("/outputs")}
      />
    );
  } else if (route.key === "retouch") {
    content = <LocalRetouchPage onOpenOutputCenter={() => navigateTo("/outputs")} />;
  } else if (route.key === "image-diagnosis") {
    content = (
      <ImageDiagnosisPage
        onRecommendationAction={handleDiagnosisRecommendation}
        onTaskCompleted={() => setTaskRegistryRevision((value) => value + 1)}
      />
    );
  } else if (route.key === "settings") {
    content = <SystemSettingsPage />;
  } else {
    content = <FeaturePlaceholderPage route={route} />;
  }

  const requestedMode = route.key === "processing"
    ? new URLSearchParams(window.location.search).get("mode") || ""
    : "";
  const showsProcessingCenter = ["processing", "history"].includes(route?.key);

  return (
    <AppShell route={route} currentPath={routePath} onNavigate={navigateTo}>
      {["compression", "color-correction", "color-correction-review", "outputs", "output-compare", "smart-delivery", "retouch"].includes(route?.key) ? null : (
        <div
          hidden={!showsProcessingCenter}
          aria-hidden={!showsProcessingCenter}
          inert={!showsProcessingCenter ? "" : undefined}
        >
          <DashboardPage
            key={`processing-center-${taskRegistryRevision}`}
            initialProcessingMode={requestedMode}
            initialTaskView={route?.key === "history" ? "history" : "current"}
            onTaskContextChange={rememberTaskContext}
            onNavigate={navigateTo}
            initialSourceFile={sourceHandoff?.routeKey === "processing" ? sourceHandoff.sourceFile : null}
            initialSourceRequestId={sourceHandoff?.routeKey === "processing" ? sourceHandoff.requestId : ""}
            onInitialSourceConsumed={consumeSourceHandoff}
          />
        </div>
      )}
      {showsProcessingCenter ? null : content}
    </AppShell>
  );
}
