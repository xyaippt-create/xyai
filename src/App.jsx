import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import AppShell from "./AppShell.jsx";
import ImageSliderComparePage from "./ImageSliderComparePage.jsx";
import FeaturePlaceholderPage, { UnknownRoutePage } from "./FeaturePlaceholderPage.jsx";
import OutputCenterPage from "./OutputCenterPage.jsx";
import { DEFAULT_APP_PATH, findAppRoute, normalizeAppPath } from "./appRoutes.js";
import { validateComparisonAssets, validateQualityReport } from "./platformStatus.js";

// Other routes must not block Output Center's initial module graph.
const DashboardPage = React.lazy(() => import("./DashboardPage.jsx"));
const QualityReportPage = React.lazy(() => import("./QualityReportPage.jsx"));
const TaskDetailPage = React.lazy(() => import("./TaskDetailPage.jsx"));
const Safe1080pBetaPage = React.lazy(() => import("./Safe1080pBetaPage.jsx"));
const CompressionPage = React.lazy(() => import("./CompressionPage.jsx"));
const ColorCorrectionPage = React.lazy(() => import("./ColorCorrectionPage.jsx"));
const SystemSettingsPage = React.lazy(() => import("./SystemSettingsPage.jsx"));
const FourKEnhancementPage = React.lazy(() => import("./FourKEnhancementPage.jsx"));
const SmartDeliveryPage = React.lazy(() => import("./SmartDeliveryPage.jsx"));
const LocalRetouchPage = React.lazy(() => import("./LocalRetouchPage.jsx"));
const BatchWatermarkPage = React.lazy(() => import("./BatchWatermarkPage.jsx"));

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const TASK_ROUTES = new Set(["task-detail", "task-compare", "task-report"]);
const FEEDBACK_TASK_ROUTES = new Set([...TASK_ROUTES, "compression", "color-correction"]);
const LEGACY_TASK_ROUTES = Object.freeze({
  compare: "/task-detail/compare",
  "quality-report": "/task-detail/report",
  "color-correction-review": "/task-detail",
  "task-compare": "/task-detail",
  "task-report": "/task-detail",
});
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

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
    task?.final_output_url
      || taskResult?.final_output_url
      || task?.preview_output_url
      || taskResult?.preview_output_url
      || task?.enhancedUrl,
  );
  if (!taskId) return null;
  return {
    taskId,
    mode: task?.mode
      || task?.operation_mode
      || task?.processing_type
      || task?.feature_key
      || taskResult?.mode
      || taskResult?.operation_mode
      || taskResult?.feature_key
      || "",
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

async function fetchRetouchResumeAuthority(taskId, resultId) {
  const query = new URLSearchParams({ task_id: taskId, result_id: resultId });
  const response = await fetch(`${API_BASE}/api/local-retouch/resume-authority?${query.toString()}`);
  const payload = await response.json();
  if (!response.ok || payload?.success === false) {
    throw new Error(payload?.detail || payload?.message || "恢复资格不可用");
  }
  return payload?.data || {};
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
  const currentRoutePathRef = useRef(normalizeAppPath(currentPath));
  const activeRouteTransitionRef = useRef(null);
  const [taskContext, setTaskContext] = useState(null);
  const [taskLoadState, setTaskLoadState] = useState("idle");
  const [taskRegistryRevision, setTaskRegistryRevision] = useState(0);
  const [retouchWorkspaceMounted, setRetouchWorkspaceMounted] = useState(false);
  const [, setRetouchResumeContext] = useState(null);
  const [retouchResumeAuthority, setRetouchResumeAuthority] = useState({
    available: false,
    status: "UNAVAILABLE",
    taskId: "",
    resultId: "",
    sessionId: "",
  });

  const commitPathChange = useCallback((targetPath, updateHistory) => {
    const nextRoutePath = normalizeAppPath(targetPath);
    const shouldAnimate = currentRoutePathRef.current !== nextRoutePath;
    let committed = false;
    const commit = () => {
      if (committed) return;
      committed = true;
      updateHistory?.();
      currentRoutePathRef.current = nextRoutePath;
      setCurrentPath(targetPath);
    };
    const reducedMotion = typeof window.matchMedia === "function"
      && window.matchMedia(REDUCED_MOTION_QUERY).matches;

    if (!shouldAnimate || reducedMotion || typeof document.startViewTransition !== "function") {
      commit();
      return;
    }

    activeRouteTransitionRef.current?.skipTransition();
    try {
      const transition = document.startViewTransition(() => flushSync(commit));
      activeRouteTransitionRef.current = transition;
      transition.ready.catch(() => {});
      transition.updateCallbackDone.catch(() => {});
      transition.finished
        .catch(() => {})
        .finally(() => {
          if (activeRouteTransitionRef.current === transition) activeRouteTransitionRef.current = null;
        });
    } catch {
      commit();
    }
  }, []);

  const navigateTo = useCallback((nextPath, options = {}) => {
    const [pathPart, queryPart = ""] = String(nextPath || DEFAULT_APP_PATH).split("?", 2);
    const normalized = normalizeAppPath(pathPart);
    const pathname = normalized === "/" ? DEFAULT_APP_PATH : normalized;
    const targetPath = `${pathname}${queryPart ? `?${queryPart}` : ""}`;
    commitPathChange(targetPath, () => {
      if (browserPath() !== targetPath) {
        const method = options.replace ? "replaceState" : "pushState";
        window.history[method]({}, "", targetPath);
      }
    });
  }, [commitPathChange]);

  useEffect(() => {
    const handlePopState = () => {
      if (normalizeAppPath(window.location.pathname) === "/") {
        commitPathChange(DEFAULT_APP_PATH, () => window.history.replaceState({}, "", DEFAULT_APP_PATH));
        return;
      }
      commitPathChange(browserPath());
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [commitPathChange]);

  const routePath = normalizeAppPath(currentPath);
  const route = useMemo(() => findAppRoute(routePath), [routePath]);
  const retouchResumeResultId = route?.key === "retouch"
    ? new URLSearchParams(window.location.search).get("resume_result") || ""
    : "";
  const continueResultId = ["compression", "color-correction", "retouch", "processing", "batch-watermark"].includes(route?.key)
    ? new URLSearchParams(window.location.search).get("continue_result") || ""
    : "";

  useEffect(() => {
    if (route?.key === "retouch") setRetouchWorkspaceMounted(true);
  }, [route?.key]);

  const rememberTaskContext = useCallback((nextContext) => {
    if (nextContext === null) {
      setTaskContext(null);
      return;
    }
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
    const hasExistingTaskContext = taskContext?.taskId === taskId;
    let active = true;
    setTaskLoadState(hasExistingTaskContext ? "ready" : "loading");
    fetchTask(taskId)
      .then((context) => {
        if (!active || !context) return;
        rememberTaskContext(context);
        setTaskLoadState("ready");
      })
      .catch(() => {
        if (!active) return;
        if (hasExistingTaskContext) {
          setTaskLoadState("ready");
          return;
        }
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
    compareAssets: taskContext.comparisonAssets || null,
  } : null;
  const activeResultId = taskConfig?.result_id || taskConfig?.task_result?.result_id || "";
  const handleTaskDeliveryCompleted = useCallback((deliveryRun) => {
    const deliveryId = String(deliveryRun?.delivery_id || "");
    if (!deliveryId) return;
    setTaskContext((previous) => {
      if (!previous?.taskId) return previous;
      return {
        ...previous,
        taskConfig: { ...(previous.taskConfig || {}), delivery_id: deliveryId },
        taskResult: { ...(previous.taskResult || {}), delivery_id: deliveryId },
      };
    });
  }, []);
  const currentResultFeedbackTarget = useMemo(() => {
    if (!FEEDBACK_TASK_ROUTES.has(route?.key) || !taskConfig?.task_id) return null;
    if (route?.key === "color-correction" && taskConfig.feature_key !== "color_correction") return null;
    const result = taskConfig.task_result || {};
    return {
      feature_key: taskConfig.feature_key || result.feature_key || taskConfig.mode || "runtime_failure",
      module_id: taskConfig.module_id || result.module_id || "",
      operation_id: taskConfig.operation_id || result.operation_id || "",
      trace_id: taskConfig.trace_id || result.trace_id || "",
      task_id: taskConfig.task_id,
      result_id: taskConfig.result_id || result.result_id || "",
      delivery_id: taskConfig.delivery_id || result.delivery_id || "",
      stage: "user_feedback_entry",
      route: routePath,
    };
  }, [route?.key, routePath, taskConfig]);
  const isLocalRetouchResult = ["LOCAL_RETOUCH", "local_retouch"].includes(taskContext?.mode);
  const canResumeCurrentRetouch = Boolean(
    isLocalRetouchResult
      && activeResultId
      && retouchResumeAuthority.available
      && retouchResumeAuthority.status === "AVAILABLE"
      && retouchResumeAuthority.taskId === taskContext?.taskId
      && retouchResumeAuthority.resultId === activeResultId
      && retouchResumeAuthority.sessionId,
  );

  useEffect(() => {
    if (route?.key !== "task-detail") return undefined;
    if (!isLocalRetouchResult || !taskContext?.taskId || !activeResultId) {
      setRetouchResumeAuthority({
        available: false,
        status: "UNAVAILABLE",
        taskId: taskContext?.taskId || "",
        resultId: activeResultId,
        sessionId: "",
      });
      return undefined;
    }
    let active = true;
    const checkAuthority = () => {
      setRetouchResumeAuthority({
        available: false,
        status: "CHECKING",
        taskId: taskContext.taskId,
        resultId: activeResultId,
        sessionId: "",
      });
      fetchRetouchResumeAuthority(taskContext.taskId, activeResultId)
        .then((authority) => {
          if (!active) return;
          setRetouchResumeAuthority({
            available: authority.available === true && authority.status === "AVAILABLE",
            status: authority.status || "UNAVAILABLE",
            taskId: taskContext.taskId,
            resultId: activeResultId,
            sessionId: authority.session_id || "",
          });
        })
        .catch(() => {
          if (!active) return;
          setRetouchResumeAuthority({
            available: false,
            status: "UNAVAILABLE",
            taskId: taskContext.taskId,
            resultId: activeResultId,
            sessionId: "",
          });
        });
    };
    checkAuthority();
    window.addEventListener("focus", checkAuthority);
    return () => {
      active = false;
      window.removeEventListener("focus", checkAuthority);
    };
  }, [activeResultId, isLocalRetouchResult, route?.key, taskContext?.taskId, taskRegistryRevision]);

  const handleRetouchResultReady = useCallback(({ taskId, resultId, sessionId }) => {
    if (!taskId || !resultId || !sessionId) return;
    setRetouchResumeContext({ taskId, resultId, sessionId });
    setTaskRegistryRevision((value) => value + 1);
    navigateTo(`/task-detail?task_id=${encodeURIComponent(taskId)}`);
  }, [navigateTo]);

  const handleRetouchResumeAvailability = useCallback((nextContext) => {
    if (!nextContext?.taskId || !nextContext?.resultId || !nextContext?.sessionId) {
      setRetouchResumeContext(null);
      return;
    }
    setRetouchResumeContext(nextContext);
  }, []);

  const handleRetouchResumeReady = useCallback(() => {
    setRetouchResumeAuthority({ available: false, status: "UNAVAILABLE", taskId: "", resultId: "", sessionId: "" });
    setRetouchResumeContext(null);
  }, []);

  const handleTaskReprocess = useCallback(async () => {
    if (!isLocalRetouchResult) {
      navigateTo(["AUTO_COLOR_CORRECTION", "REFERENCE_COLOR_CORRECTION", "LEVEL_PICK_COLOR_CORRECTION", "REFERENCE_LEVEL_PICK_COLOR_CORRECTION", "color_correction"].includes(taskContext?.mode)
        ? "/color-correction"
        : `${DEFAULT_APP_PATH}?mode=${encodeURIComponent(taskContext?.mode || "standard")}`);
      return;
    }
    if (!taskContext?.taskId || !activeResultId) {
      setRetouchResumeAuthority({ available: false, status: "UNAVAILABLE", taskId: "", resultId: "", sessionId: "" });
      navigateTo("/retouch");
      return;
    }
    try {
      const authority = await fetchRetouchResumeAuthority(taskContext.taskId, activeResultId);
      if (authority.available === true && authority.status === "AVAILABLE" && authority.session_id) {
        setRetouchResumeAuthority({
          available: true,
          status: "AVAILABLE",
          taskId: taskContext.taskId,
          resultId: activeResultId,
          sessionId: authority.session_id,
        });
        navigateTo(`/retouch?resume_result=${encodeURIComponent(activeResultId)}`);
        return;
      }
    } catch {
      // Authority is fail-closed. The safe action is a clean reprocess workspace.
    }
    setRetouchResumeAuthority({
      available: false,
      status: "UNAVAILABLE",
      taskId: taskContext.taskId,
      resultId: activeResultId,
      sessionId: "",
    });
    setRetouchResumeContext(null);
    navigateTo("/retouch");
  }, [activeResultId, isLocalRetouchResult, navigateTo, taskContext?.mode, taskContext?.taskId]);

  let content = null;
  if (!route) {
    content = <UnknownRoutePage pathname={routePath} onBackToProcessing={() => navigateTo(DEFAULT_APP_PATH)} />;
  } else if (["processing", "history"].includes(route.key)) {
    content = null;
  } else if (route.key === "task-detail") {
    content = taskConfig && taskLoadState !== "loading" ? (
      <TaskDetailPage
        taskConfig={taskConfig}
        disableAutoStream={taskConfig?.feature_key === "image_compression"}
        reprocessLabel={isLocalRetouchResult
          ? canResumeCurrentRetouch ? "返回调整" : "重新处理"
          : undefined}
        onReprocess={handleTaskReprocess}
        onContinueProcessing={() => navigateTo(DEFAULT_APP_PATH)}
        onViewOutputs={() => navigateTo("/outputs")}
        onDeliveryCompleted={handleTaskDeliveryCompleted}
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
    content = <Safe1080pBetaPage onBackToDashboard={() => navigateTo("/processing?mode=standard", { replace: true })} />;
  } else if (route.key === "four-k-enhancement") {
    content = (
      <FourKEnhancementPage
        onOpenSharedProcessing={() => navigateTo("/processing?mode=4k_v1", { replace: true })}
      />
    );
  } else if (route.key === "compression") {
    content = <CompressionPage continueResultId={continueResultId} onNavigate={navigateTo} onTaskContextChange={rememberTaskContext} />;
  } else if (route.key === "color-correction") {
    content = (
      <ColorCorrectionPage
        continueResultId={continueResultId}
        onTaskContextChange={rememberTaskContext}
        onOpenProcessing={(batchId) => navigateTo(`/processing?batch=${encodeURIComponent(batchId)}`)}
        onResultReady={(taskId) => navigateTo(`/task-detail?task_id=${encodeURIComponent(taskId)}`)}
      />
    );
  } else if (route.key === "color-correction-review") {
    content = (
      <ExistingPageEmptyState
        title="正在进入处理结果"
        description="颜色校正旧结果入口正在转到统一处理结果。"
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
    content = null;
  } else if (route.key === "batch-watermark") {
    content = <BatchWatermarkPage continueResultId={continueResultId} onNavigate={navigateTo} />;
  } else if (route.key === "settings") {
    content = <SystemSettingsPage />;
  } else {
    content = <FeaturePlaceholderPage route={route} />;
  }

  const requestedMode = route?.key === "processing"
    ? new URLSearchParams(window.location.search).get("mode") || ""
    : "";
  const showsProcessingCenter = ["processing", "history"].includes(route?.key);
  const shellRoute = route?.key === "processing" && requestedMode === "4k_v1"
    ? findAppRoute("/4k-enhancement")
    : route;

  return (
    <AppShell
      route={shellRoute}
      currentPath={routePath}
      onNavigate={navigateTo}
      workspaceMode={route?.key === "retouch"}
      feedbackTarget={currentResultFeedbackTarget}
      feedbackDisabled={TASK_ROUTES.has(route?.key) && !currentResultFeedbackTarget}
    >
      {["compression", "color-correction", "color-correction-review", "outputs", "output-compare", "smart-delivery", "retouch", "batch-watermark"].includes(route?.key) ? null : (
        <div
          hidden={!showsProcessingCenter}
          aria-hidden={!showsProcessingCenter}
          inert={!showsProcessingCenter ? "" : undefined}
        >
          <React.Suspense fallback={null}>
            <DashboardPage
              key={`processing-center-${taskRegistryRevision}`}
              initialProcessingMode={requestedMode}
              initialTaskView={route?.key === "history" ? "history" : "current"}
              onTaskContextChange={rememberTaskContext}
              onNavigate={navigateTo}
              continueResultId={continueResultId}
            />
          </React.Suspense>
        </div>
      )}
      {showsProcessingCenter ? null : <React.Suspense fallback={null}>{content}</React.Suspense>}
      {retouchWorkspaceMounted || route?.key === "retouch" ? (
        <div
          hidden={route?.key !== "retouch"}
          aria-hidden={route?.key !== "retouch"}
          inert={route?.key !== "retouch" ? "" : undefined}
        >
          <React.Suspense fallback={null}>
            <LocalRetouchPage
              onBack={() => navigateTo(DEFAULT_APP_PATH)}
              onOpenOutputCenter={() => navigateTo("/outputs")}
              onResultReady={handleRetouchResultReady}
              onResumeReady={handleRetouchResumeReady}
              onResumeAvailabilityChange={handleRetouchResumeAvailability}
              continueResultId={continueResultId}
              resumeResultId={retouchResumeResultId}
              resumeSessionId={canResumeCurrentRetouch ? retouchResumeAuthority.sessionId : ""}
            />
          </React.Suspense>
        </div>
      ) : null}
    </AppShell>
  );
}
