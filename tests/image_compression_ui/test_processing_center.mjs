import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test, { after } from "node:test";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import { APP_ROUTES, COMPATIBILITY_ROUTES } from "../../src/appRoutes.js";
import { getFileDisplayName } from "../../src/fileDisplayName.js";
import { FEATURE_STATUSES } from "../../src/platformStatus.js";
import { resolve1080pSizeTreatment } from "../../src/sizeTreatment.js";

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(currentDirectory, "..", "..");
process.env.HDDE_API_TARGET ||= "http://127.0.0.1:0";
const dashboard = fs.readFileSync(path.join(root, "src", "DashboardPage.jsx"), "utf8");
const app = fs.readFileSync(path.join(root, "src", "App.jsx"), "utf8");
const colorCorrection = fs.readFileSync(path.join(root, "src", "ColorCorrectionPage.jsx"), "utf8");
const styles = fs.readFileSync(path.join(root, "src", "index.css"), "utf8");
const taskDetail = fs.readFileSync(path.join(root, "src", "TaskDetailPage.jsx"), "utf8");
const comparison = fs.readFileSync(path.join(root, "src", "ImageSliderComparePage.jsx"), "utf8");
const qualityReport = fs.readFileSync(path.join(root, "src", "QualityReportPage.jsx"), "utf8");
const unifiedFeedback = fs.readFileSync(path.join(root, "src", "UnifiedFeedback.jsx"), "utf8");
const feedbackFlow = fs.readFileSync(path.join(root, "src", "feedbackFlow.js"), "utf8");
const safeBeta = fs.readFileSync(path.join(root, "src", "Safe1080pBetaPage.jsx"), "utf8");
const appRoutesSource = fs.readFileSync(path.join(root, "src", "appRoutes.js"), "utf8");
const appShell = fs.readFileSync(path.join(root, "src", "AppShell.jsx"), "utf8");
const fourKPage = fs.readFileSync(path.join(root, "src", "FourKEnhancementPage.jsx"), "utf8");
const hddeReadme = fs.readFileSync(path.join(root, ".agents", "skills", "hdde", "README.md"), "utf8");
const launchPage = fs.readFileSync(path.join(root, "src", "LaunchPage.jsx"), "utf8");
const indexHtml = fs.readFileSync(path.join(root, "index.html"), "utf8");
const formalProcessingDescription = "导入图片，选择处理模式与输出目录，开始处理并查看交付结果。";
let viteServer = null;

async function loadRealComponent(modulePath) {
  if (!viteServer) {
    viteServer = await createServer({
      root,
      appType: "custom",
      logLevel: "silent",
      server: { middlewareMode: true },
    });
  }
  return viteServer.ssrLoadModule(modulePath);
}

after(async () => {
  if (viteServer) await viteServer.close();
});

function processingRouteBlock() {
  const start = app.indexOf('} else if (["processing", "history"].includes(route.key)) {');
  const end = app.indexOf('} else if (route.key === "task-detail") {', start);
  assert.ok(start >= 0 && end > start, "processing route block must remain directly testable");
  return app.slice(start, end);
}

test("all real routes use the shared theme-aware application shell", () => {
  const block = processingRouteBlock();
  assert.doesNotMatch(block, /legacyDarkCompatibility/);
  assert.doesNotMatch(app, /旧页面深色兼容区|hdde-legacy-notice|legacyDarkCompatibility/);
});

test("route audit scope is derived from real enabled and beta route configuration", () => {
  const accessible = APP_ROUTES.filter(
    (route) => route.showInNavigation !== false && [FEATURE_STATUSES.ENABLED, FEATURE_STATUSES.BETA].includes(route.status),
  );
  assert.deepEqual(accessible.map((route) => route.key), [
    "processing",
    "four-k-enhancement",
    "color-correction",
    "compression",
    "retouch",
    "batch-watermark",
    "outputs",
    "settings",
  ]);
  assert.equal(APP_ROUTES.find((route) => route.key === "settings")?.implementationType, "existing");
  assert.equal(APP_ROUTES.find((route) => route.key === "compare")?.showInNavigation, false);
  assert.equal(APP_ROUTES.find((route) => route.key === "quality-report")?.showInNavigation, false);
  assert.equal(APP_ROUTES.find((route) => route.key === "tasks")?.showInNavigation, false);
  assert.equal(APP_ROUTES.find((route) => route.key === "history")?.showInNavigation, false);
  assert.equal(APP_ROUTES.find((route) => route.key === "batch")?.showInNavigation, false);
  assert.equal(APP_ROUTES.some((route) => route.key === "image-diagnosis"), false);
  assert.equal(APP_ROUTES.find((route) => route.key === "tasks")?.path, "/tasks");
  assert.match(appShell, /showInNavigation !== false/);
});

test("comparison and quality report follow the configured same-origin API target", () => {
  for (const source of [comparison, qualityReport]) {
    assert.match(source, /const API_BASE = import\.meta\.env\.VITE_API_BASE_URL \|\| "";/);
    assert.doesNotMatch(source, /(?:localhost|127\.0\.0\.1):8787/);
  }
});

test("processing center owns current and historical tasks from the shared task fact source", () => {
  assert.match(dashboard, /requestJson\("GET", `\$\{API_BASE\}\/api\/v1\/tasks\?\$\{params\}`/);
  assert.match(dashboard, /role="tab"[\s\S]*当前任务/);
  assert.match(dashboard, /role="tab"[\s\S]*历史任务/);
  assert.match(dashboard, /splitProcessingTaskLists\(/);
  for (const field of ["featureKey", "taskId", "resultId", "deliveryId"]) {
    assert.match(dashboard, new RegExp(field));
  }
  assert.match(app, /initialTaskView=\{route\?\.key === "history" \? "history" : "current"\}/);
});

test("processing task list derives current and history views without a parallel hidden fact source", async () => {
  const { splitProcessingTaskLists } = await loadRealComponent("/src/DashboardPage.jsx");
  const tasks = [
    { id: "local-running", taskId: "task-running", status: "processing" },
    { id: "local-completed", taskId: "task-completed", status: "completed", resultId: "result-completed", deliveryId: "delivery-completed" },
    { id: "restored-failed", taskId: "task-failed", status: "failed", resultId: "result-failed", deliveryId: "delivery-failed" },
  ];
  const sessionIds = new Set(["local-running", "local-completed"]);
  const initial = splitProcessingTaskLists(tasks, sessionIds);
  assert.deepEqual(initial.current.map((item) => item.id), ["local-running", "local-completed"]);
  assert.deepEqual(initial.history.map((item) => item.id), ["restored-failed"]);

  sessionIds.delete("local-completed");
  const afterSession = splitProcessingTaskLists(tasks, sessionIds);
  assert.deepEqual(afterSession.current.map((item) => item.id), ["local-running"]);
  assert.deepEqual(afterSession.history.map((item) => item.id), ["local-completed", "restored-failed"]);

  tasks.splice(1, 2);
  tasks.push({ id: "local-new", taskId: "", status: "queued" });
  sessionIds.add("local-new");
  const afterNewTask = splitProcessingTaskLists(tasks, sessionIds);
  assert.deepEqual(afterNewTask.current.map((item) => item.id), ["local-running", "local-new"]);
  assert.deepEqual(afterNewTask.history, []);

  const ordered = splitProcessingTaskLists([
    { id: "task-older", taskId: "task-older", status: "completed", created_at: "2026-09-09T08:00:00Z" },
    { id: "task-newer-a", taskId: "task-newer-a", status: "completed", created_at: "2026-09-09T09:00:00Z" },
    { id: "task-newer-b", taskId: "task-newer-b", status: "completed", created_at: "2026-09-09T09:00:00Z" },
  ]);
  assert.deepEqual(ordered.history.map((item) => item.id), ["task-newer-b", "task-newer-a", "task-older"]);
});

test("processing failure keeps the selected file retryable and distinguishes backend interruption", async () => {
  const {
    BACKEND_INTERRUPTION_NOTICE,
    isBackendServiceInterruption,
  } = await loadRealComponent("/src/DashboardPage.jsx");

  assert.equal(isBackendServiceInterruption("SSE 流式日志通道异常。"), true);
  assert.equal(isBackendServiceInterruption("无法连接上传接口，请确认 FastAPI 服务已启动。"), true);
  assert.equal(isBackendServiceInterruption("4K成品元数据写入失败"), false);
  assert.match(BACKEND_INTERRUPTION_NOTICE, /处理服务异常中断，本次任务未完成/);
  assert.match(BACKEND_INTERRUPTION_NOTICE, /当前图片已保留/);
  assert.match(BACKEND_INTERRUPTION_NOTICE, /服务恢复后重新处理/);
  assert.match(dashboard, /failedOutcomes\.length[\s\S]*setActiveItemId\(failedOutcomes\[0\]\.itemId\)/);
  assert.match(dashboard, /filter\(\(outcome\) => outcome\.status === "completed"\)[\s\S]*currentSessionTaskIdsRef\.current\.delete/);
  assert.doesNotMatch(
    dashboard,
    /setActiveScreen\("dashboard"\);\s*currentSessionTaskIdsRef\.current\.clear\(\);\s*setActiveItemId\(""\);/,
  );
  const processOneItem = dashboard.slice(
    dashboard.indexOf("const processOneItem ="),
    dashboard.indexOf("const handleStartQueue ="),
  );
  assert.match(processOneItem, /status: "uploading"[\s\S]*taskId: ""[\s\S]*resultId: ""[\s\S]*deliveryId: ""/);
  assert.match(processOneItem, /task_result: null[\s\S]*task_report: null[\s\S]*final_output_url: ""/);
});

test("batch watermark terminal tasks resolve to their dedicated batch result route", async () => {
  const { resolveProcessingTaskBusinessRoute } = await loadRealComponent("/src/DashboardPage.jsx");
  const batchId = "watermark_batch_real_001";
  for (const status of ["completed", "partial_success", "failed"]) {
    assert.equal(
      resolveProcessingTaskBusinessRoute({ taskFamily: "batch_watermark", taskId: batchId, status }),
      `/batch-watermark?batch_id=${encodeURIComponent(batchId)}`,
    );
  }
  assert.equal(
    resolveProcessingTaskBusinessRoute({ taskFamily: "image_diagnosis", taskId: "diagnosis_real_001" }),
    "",
  );
  assert.equal(
    resolveProcessingTaskBusinessRoute({ taskFamily: "standard", taskId: "task_real_001" }),
    "/task-detail?task_id=task_real_001",
  );
  assert.equal(
    resolveProcessingTaskBusinessRoute({ taskFamily: "color_correction", taskId: "color_real_001" }),
    "/task-detail?task_id=color_real_001",
  );
  assert.equal(
    resolveProcessingTaskBusinessRoute({ taskFamily: "local_retouch", taskId: "retouch_real_001" }),
    "/task-detail?task_id=retouch_real_001",
  );
  assert.equal(resolveProcessingTaskBusinessRoute({ taskFamily: "batch_watermark", taskId: "" }), "");
});

test("processing summary isolates local files current tasks history and result presentation", async () => {
  const {
    processingPathDisplayName,
    processingResultDisplayName,
  } = await loadRealComponent("/src/DashboardPage.jsx");
  assert.equal(
    processingPathDisplayName("D:\\影界文件\\输出\\1080P标准增强"),
    "D:\\影界文件\\输出\\1080P画质",
  );
  assert.equal(
    processingResultDisplayName({ final_output_url: "http://localhost:8787/api/v1/tasks/internal/result-file" }),
    "成品已生成，可打开查看",
  );
  assert.doesNotMatch(processingResultDisplayName({ final_output_url: "http://localhost:8787/api/v1/tasks/internal/result-file" }), /localhost|api\/v1/i);
  assert.match(dashboard, /const localQueueItems = currentTaskItems\.filter\(\(item\) => Boolean\(item\.file \|\| item\.sourceResultId\) && isRunnableProcessingItem\(item\)\);/);
  assert.match(dashboard, /const summaryItem = taskView === "current" \? activeItem : null/);
  assert.match(dashboard, /const deliveryActionItem = taskView === "current"/);
  assert.match(dashboard, /const \[notice, setNotice\] = useState\(""\)/);
  assert.doesNotMatch(dashboard, /useState\("请选择图片，或更换输出文件夹后开始处理。"\)/);
  assert.doesNotMatch(dashboard, /deliveryActionItem\?\.final_output_url \|\| currentOutputDir/);
});

test("processing task list clear actions call the shared deletion API and expose protected partial results", () => {
  for (const contract of [
    'data-testid="clear-current-task-list"',
    'data-testid="clear-history-task-list"',
    'className="hdde-secondary-action hdde-processing-clear-action"',
    'taskIds.slice(offset, offset + 100)',
    'requestJson("DELETE", `${API_BASE}/api/v1/tasks`, { task_ids: batchTaskIds })',
    "window.confirm(",
    "isClearingTasks || !clearableCurrentTaskItems.length",
    "isClearingTasks || !clearableHistoryTaskItems.length",
    "protected_count",
    "Result、Delivery",
  ]) {
    assert.ok(dashboard.includes(contract), `missing list-clear UI contract: ${contract}`);
  }
  assert.match(styles, /\.hdde-processing-clear-action[\s\S]*min-height:\s*34px/);
  assert.match(styles, /\.hdde-secondary-action:hover:not\(:disabled\)/);
  assert.match(styles, /\.hdde-processing-page button:disabled/);
  assert.doesNotMatch(dashboard, /hiddenCurrentTaskIds|hiddenHistoryTaskIds/);
});

test("processing task facts restore progressively and clear reloads the persisted source", () => {
  assert.match(dashboard, /TASK_LIST_INITIAL_PAGE_SIZE\s*=\s*24/);
  assert.match(dashboard, /TASK_LIST_PAGE_SIZE\s*=\s*50/);
  assert.match(dashboard, /new URLSearchParams\(\{ limit: String\(limit\), offset: String\(offset\) \}\)/);
  assert.match(dashboard, /loadTaskPage\(data\.next_offset, TASK_LIST_PAGE_SIZE, false\)/);
  assert.match(dashboard, /taskListLoadGenerationRef\.current !== generation/);
  assert.match(dashboard, /const controller = new AbortController\(\)/);
  assert.match(dashboard, /signal: controller\.signal/);
  assert.match(dashboard, /controller\.abort\(\)/);
  assert.match(dashboard, /reuseSharedStateRequest\(endpoint, \(\) => requestJson\("GET", endpoint\)\)/);
  assert.match(dashboard, /window\.setTimeout\([\s\S]*?loadTaskPage\(0, TASK_LIST_INITIAL_PAGE_SIZE, true\)/);
  assert.match(dashboard, /setTaskListReloadVersion\(\(current\) => current \+ 1\)/);
  assert.match(dashboard, /deleted_task_ids/);
  assert.doesNotMatch(dashboard, /requestJson\("GET", `\$\{API_BASE\}\/api\/v1\/tasks`\)/);
});

test("processing shared state reuses only the active request and never caches settled values", async () => {
  const { reuseSharedStateRequest } = await loadRealComponent("/src/DashboardPage.jsx");
  let calls = 0;
  let resolveRequest;
  const first = reuseSharedStateRequest("/api/shared-state/test", () => {
    calls += 1;
    return new Promise((resolve) => {
      resolveRequest = resolve;
    });
  });
  const duplicate = reuseSharedStateRequest("/api/shared-state/test", () => {
    calls += 1;
    return Promise.resolve("unexpected");
  });
  assert.equal(first, duplicate);
  assert.equal(calls, 0);
  await Promise.resolve();
  assert.equal(calls, 1);
  resolveRequest("fresh");
  assert.equal(await duplicate, "fresh");
  await Promise.resolve();
  assert.equal(await reuseSharedStateRequest("/api/shared-state/test", async () => {
    calls += 1;
    return "next";
  }), "next");
  assert.equal(calls, 2);
  for (const endpoint of ["/api/app/workdir", "/api/color-correction/batches"]) {
    assert.equal((dashboard.match(new RegExp(endpoint.replaceAll("/", "\\/"), "g")) || []).length, 1);
  }
});

test("4K shortcut reuses the processing center upload task comparison and report flow", () => {
  const route = APP_ROUTES.find((item) => item.key === "four-k-enhancement");
  assert.equal(route?.name, "4K画质增强");
  assert.equal(route?.implementationType, "shortcut");
  assert.match(fourKPage, /onOpenSharedProcessing\?\.\("4k_v1"\)/);
  assert.doesNotMatch(fourKPage, /XMLHttpRequest|EventSource|FormData|\/api\/upload/);
  assert.match(app, /<ImageSliderComparePage/);
  assert.match(app, /<QualityReportPage/);
  assert.doesNotMatch(appRoutesSource, /4k-(?:compare|report)/i);
  assert.match(dashboard, /id:\s*PROCESSING_MODE_FOUR_K/);
  assert.match(dashboard, /activeMode === PROCESSING_MODE_FOUR_K/);
  assert.match(dashboard, /formData\.append\("output_profile", FOUR_K_OUTPUT_PROFILE\)/);
  assert.match(dashboard, /formData\.append\("output_format", "png"\)/);
  const fourKUploadBranch = dashboard.slice(
    dashboard.indexOf("if (activeMode === PROCESSING_MODE_FOUR_K)"),
    dashboard.indexOf("} else {", dashboard.indexOf("if (activeMode === PROCESSING_MODE_FOUR_K)")),
  );
  assert.doesNotMatch(fourKUploadBranch, /formData\.append\("(?:scale|output_dir|target_width|target_height)"/);
});

test("task result routes refresh an existing task context from the formal task source", () => {
  assert.match(app, /const hasExistingTaskContext = taskContext\?\.taskId === taskId/);
  assert.match(app, /setTaskLoadState\(hasExistingTaskContext \? "ready" : "loading"\)[\s\S]*fetchTask\(taskId\)/);
  assert.doesNotMatch(app, /if \(taskContext\?\.taskId === taskId\) \{[\s\S]{0,120}return;/);
});

test("image compression task detail never attaches the enhancement SSE progress writer", () => {
  assert.match(app, /disableAutoStream=\{taskConfig\?\.feature_key === "image_compression"\}/);
});

test("queue can enter uploading before any post-stream task result exists", () => {
  const processStart = dashboard.indexOf("const processOneItem = async");
  const streamStart = dashboard.indexOf("const streamPayload = await streamTask", processStart);
  assert.ok(processStart >= 0 && streamStart > processStart, "processOneItem pre-stream block must remain directly testable");
  const preStreamBlock = dashboard.slice(processStart, streamStart);
  assert.doesNotMatch(preStreamBlock, /taskResult\./);
  assert.match(preStreamBlock, /output_format:\s*requestMode === PROCESSING_MODE_FOUR_K \? "png" : outputFormat/);
});

test("task routes stay task-scoped and legacy global routes fall back safely", () => {
  for (const routeKey of ["task-detail", "task-compare", "task-report"]) {
    const route = APP_ROUTES.find((item) => item.key === routeKey);
    assert.equal(route?.showInNavigation, false);
  }
  assert.match(app, /query\.get\("task_id"\)/);
  assert.match(app, /LEGACY_TASK_ROUTES/);
  assert.match(app, /navigateTo\(DEFAULT_APP_PATH, \{ replace: true \}\)/);
  assert.match(app, /compare:\s*"\/task-detail\/compare"/);
  assert.match(app, /"quality-report":\s*"\/task-detail\/report"/);
  assert.match(app, /`\/task-detail\$\{suffix\}\?task_id=\$\{encodeURIComponent\(taskId\)\}`/);
  assert.match(dashboard, /\/task-detail\/compare\?task_id=/);
  assert.match(dashboard, /\/task-detail\/report\?task_id=/);
});

test("favicon uses the local HDDE brand resource", () => {
  assert.match(indexHtml, /<link rel="icon" type="image\/png" href="\/branding\/hdde\/app-icon\.png"\s*\/>/);
  const faviconPath = path.join(root, "public", "branding", "hdde", "app-icon.png");
  assert.ok(fs.existsSync(faviconPath));
});

test("processing route exposes only the formal product description", () => {
  const processingRoute = APP_ROUTES.find((route) => route.key === "processing");
  assert.ok(processingRoute, "processing route must exist in the real route configuration");
  assert.equal(processingRoute.description, formalProcessingDescription);
  assert.doesNotMatch(
    `${processingRoute.pageTitle}\n${processingRoute.description}`,
    /工作台|兼容区|旧版|临时/,
  );
});

test("processing center uses one platform surface instead of the old fixed dark workbench", () => {
  assert.match(dashboard, /data-testid="processing-center"/);
  assert.doesNotMatch(dashboard, /vmp-main-viewport/);
  assert.doesNotMatch(dashboard, /画质核心工作台|Python Runtime 8787/);
  assert.match(styles, /\.hdde-processing-page\s*\{/);
  assert.match(styles, /background:\s*var\(--content-background\)/);
});

test("task preparation keeps the real input mode output and start controls in one sequence", () => {
  for (const contract of [
    'data-testid="processing-file-input"',
    'data-testid="processing-select-image"',
    'data-testid="processing-mode"',
    "currentOutputDir",
    'data-testid="processing-start"',
    "handleStartQueue",
  ]) {
    assert.ok(dashboard.includes(contract), `missing real preparation contract: ${contract}`);
  }
  assert.equal((dashboard.match(/className="hdde-processing-primary-action"/g) || []).length, 1);
});

test("blocked directory state preserves full path reason repair entry and start blocking", () => {
  assert.match(dashboard, /workdirInfo\?\.app_data_root \|\| workdirInfo\?\.failed_path/);
  assert.match(dashboard, /workdirInfo\?\.failure_reason \|\| directoryMessage/);
  assert.match(dashboard, /data-testid="processing-blocked-message"/);
  assert.match(dashboard, /前往系统设置修复/);
  assert.match(dashboard, /disabled=\{!canStartExecution\}/);
  assert.doesNotMatch(dashboard, /runtime_data.*currentOutputDir|currentOutputDir.*runtime_data/s);
});

test("queue keeps real task status progress result and delivery actions", () => {
  for (const label of ["文件名称", "处理模式", "状态与进度", "结果与交付", "查看详情", "打开成品", "打开文件夹"]) {
    assert.ok(dashboard.includes(label), `missing queue contract: ${label}`);
  }
  assert.match(dashboard, /<StatusPill status=\{item\.status\}/);
  assert.match(dashboard, /const noticeIsError =/);
  assert.doesNotMatch(dashboard, /notice\.includes\("失败"\)/);
  assert.match(dashboard, /itemProgress/);
  assert.match(dashboard, /<DeliveryPill status=\{item\.final_delivery_status\}/);
});

test("current status and delivery sections only display existing runtime data", () => {
  for (const contract of [
    "currentStageLabel",
    "currentNextAction",
    "deliveryActionItem",
    "deliveryOutputPath",
    "handleOpenOutputDir",
    "handleOpenFinalOutput",
    "handleCopyFinalOutputUrl",
  ]) {
    assert.ok(dashboard.includes(contract), `missing status or delivery contract: ${contract}`);
  }
  assert.match(dashboard, /真实输出与结果/);
});

test("color correction delivery opens its actual result folder while standard mode keeps the existing action", () => {
  assert.match(
    dashboard,
    /const handleOpenDeliveryOutputDirectory = \(\) => \{[\s\S]*?deliveryActionItem\?\.taskFamily === "color_correction"[\s\S]*?handleOpenItemOutputFolder\(deliveryActionItem\);[\s\S]*?handleOpenOutputDir\(\);[\s\S]*?\};/,
  );
  assert.match(dashboard, /onClick=\{handleOpenDeliveryOutputDirectory\}[^>]*>打开输出目录<\/button>/);
});

test("light and dark processing center share token-driven structure", () => {
  assert.match(styles, /\.hdde-processing-panel\s*\{/);
  assert.match(styles, /background:\s*var\(--card-background\)/);
  assert.match(styles, /color:\s*var\(--text-primary\)/);
  assert.match(styles, /border:\s*1px solid var\(--border-color\)/);
  assert.match(styles, /var\(--brand-primary\)/);
  assert.doesNotMatch(styles, /:root\[data-theme="light"\]\s+\.hdde-processing|:root\[data-theme="dark"\]\s+\.hdde-processing/);
});

test("global typography and semantic color roles are explicit", () => {
  for (const role of [
    "--font-size-page-title: 24px",
    "--font-size-section-title: 18px",
    "--font-size-card-title: 16px",
    "--font-size-body: 14px",
    "--font-size-label: 13px",
    "--font-size-caption: 12px",
    "--brand-primary: #2d6fe8",
    "--status-success:",
    "--status-warning:",
    "--status-danger:",
    "--status-info:",
  ]) {
    assert.ok(styles.toLowerCase().includes(role.toLowerCase()), `missing visual role: ${role}`);
  }
});

test("standard and enhanced workflows share the HDDE brand palette", () => {
  const enhancedSources = `${dashboard}\n${safeBeta}\n${comparison}\n${launchPage}`.toLowerCase();
  for (const retiredAccent of ["#00ffcc", "#6feaf0", "#3cb3a0", "#8effed", "#7af4df", "#5bf5dc", "#418c80"]) {
    assert.ok(!enhancedSources.includes(retiredAccent), `retired teal accent remains visible: ${retiredAccent}`);
  }
  assert.match(dashboard, /label: "1080P画质"/);
  assert.match(dashboard, /processingModeDisplayName\(normalized\)/);
  assert.doesNotMatch(dashboard, /label: "1080P(?:标准|安全|普通)增强"/);
  assert.match(dashboard, /className="hdde-enhanced-page/);
  assert.match(styles, /\.hdde-enhanced-page\s*\{/);
  assert.match(styles, /\.hdde-enhanced-page[\s\S]*background:\s*var\(--content-background\)/);
});

test("processing readiness uses brand blue instead of completion green", () => {
  const readinessStart = styles.indexOf('.hdde-processing-readiness[data-tone="positive"]');
  const readinessEnd = styles.indexOf('.hdde-processing-readiness[data-tone="negative"]', readinessStart);
  assert.ok(readinessStart >= 0 && readinessEnd > readinessStart);
  const readinessBlock = styles.slice(readinessStart, readinessEnd);
  assert.match(readinessBlock, /var\(--brand-primary\)/);
  assert.match(readinessBlock, /var\(--brand-primary-soft\)/);
  assert.doesNotMatch(readinessBlock, /var\(--status-success\)/);
});

test("enhanced task UI hides internal run ids while keeping runtime data", () => {
  assert.doesNotMatch(dashboard, /beta_run_id:\s*\{/);
  assert.match(dashboard, /beta_run_id:\s*betaRunId/);
  assert.match(dashboard, /formData\.append\("beta_run_id", betaRunId\)/);
  assert.match(dashboard, /const rawInputName = activeItem\?\.name \|\| safeBetaResult\?\.current_file/);
  assert.match(dashboard, /当前文件：\{inputDisplayName\}/);
});

test("HDDE skill README keeps only resolvable markdown file references", () => {
  assert.doesNotMatch(hddeReadme, /AGENTS_HDDE_APPEND\.md/);
  const skillRoot = path.join(root, ".agents", "skills", "hdde");
  const references = [...hddeReadme.matchAll(/`([^`]+\.md)`/g)].map((match) => match[1]);
  assert.ok(references.length > 0);
  for (const reference of references) {
    const existsInSkill = fs.existsSync(path.resolve(skillRoot, reference));
    const existsInRepository = fs.existsSync(path.resolve(root, reference));
    assert.ok(existsInSkill || existsInRepository, `missing HDDE README reference: ${reference}`);
  }
});

test("safe enhancement compatibility entry redirects to the unified visible product", () => {
  for (const contract of ["历史兼容入口", "正在进入1080P画质", "历史任务和内部处理标识保持兼容"]) {
    assert.ok(safeBeta.includes(contract), `missing safe entry contract: ${contract}`);
  }
  assert.doesNotMatch(safeBeta, />[^<]*Beta[^<]*</);
  assert.doesNotMatch(safeBeta, /试用功能|独立测试入口|运行结果|BETA_|runBeta|ResultLine|输入目录|输出目录|导出测试反馈包/);
  assert.match(appRoutesSource, /name: "1080P画质"/);
  assert.match(appRoutesSource, /pageTitle: "1080P画质"/);
  assert.equal(COMPATIBILITY_ROUTES.find((route) => route.key === "safe-1080p-beta")?.status, FEATURE_STATUSES.ENABLED);
});

test("clipboard GUID names are friendly in the UI without changing ordinary filenames", () => {
  const clipboardName = "codex-clipboard-b87d416a-976c-4407-95b0-43dc8406edb6.png";
  assert.equal(getFileDisplayName(clipboardName), "剪贴板图片");
  assert.equal(getFileDisplayName(`D:\\输入\\${clipboardName}`), "剪贴板图片");
  assert.equal(getFileDisplayName("普通交付图片_最终版.png"), "普通交付图片_最终版.png");
  assert.equal(
    getFileDisplayName("历史图_影界瑕疵修整_20260830.png"),
    "历史图_影界瑕疵修整_20260830.png",
  );
  assert.equal(
    getFileDisplayName("客户_影界瑕疵修整_项目_影界瑕疵修复_20260901.png"),
    "客户_影界瑕疵修整_项目_影界瑕疵修复_20260901.png",
  );
  assert.match(dashboard, /title=\{rawInputName\}/);
  assert.match(qualityReport, /title=\{fileName\}>\{fileDisplayName\}/);
});

test("safe enhancement task, comparison, and report expose product language only", () => {
  const taskStart = dashboard.indexOf('if (activeScreen === "safe_beta_task")');
  const compareStart = dashboard.indexOf('if (activeScreen === "safe_beta_compare")', taskStart);
  const reportStart = dashboard.indexOf('if (activeScreen === "safe_beta_report")', compareStart);
  const reportEnd = dashboard.indexOf("const outputLocationLabel =", reportStart);
  const sliderStart = dashboard.indexOf("function SafeBetaBeforeAfterCompare");
  const sliderEnd = dashboard.indexOf("function isBrowserPreviewablePath", sliderStart);
  const taskUi = dashboard.slice(taskStart, compareStart);
  const compareUi = `${dashboard.slice(sliderStart, sliderEnd)}\n${dashboard.slice(compareStart, reportStart)}`;
  const reportUi = dashboard.slice(reportStart, reportEnd);

  assert.doesNotMatch(taskUi, /安全增强阶段日志|不是标准 SSE|BETA_|contact sheet|输出路径|导出测试反馈包/);
  for (const heading of ["正在处理你的图片", "图片处理已完成", "图片处理未完成", "已保护原图"]) {
    assert.match(taskUi, new RegExp(heading));
  }
  assert.equal((taskUi.match(/>\s*查看前后对比\s*</g) || []).length, 1, "safe task must keep one primary comparison action");

  for (const contract of [
    'data-testid="safe-before-after-comparison"',
    'data-testid="safe-comparison-slider"',
    'type="range"',
    "clipPath:",
    "originalFile={activeItem?.file}",
    "outputUrl={outputPreviewUrl}",
    "object-contain",
    "拖动中线查看差异",
  ]) {
    assert.ok(compareUi.includes(contract), `missing safe comparison contract: ${contract}`);
  }
  assert.doesNotMatch(compareUi, /contact sheet|字段绑定|OUTPUT PREVIEW|CONTACT SHEET|bg-\[#080d16\]/);

  for (const contract of ["高清交付评估", "输出结果", "交付结论", "复核重点", "正向信号", "建议用途", "结果操作"])
    assert.ok(reportUi.includes(contract), `missing safe report contract: ${contract}`);
  for (const contract of ["HddeResultHero", "HddeTechnicalDetails", "处理前后变化", "安全保护", "下一步"])
    assert.ok(`${qualityReport}\n${fs.readFileSync(path.join(root, "src", "HddeUI.jsx"), "utf8")}`.includes(contract), `missing standard result hierarchy: ${contract}`);
  assert.doesNotMatch(reportUi, /PASS_WITH_LIMITATION 解释|Manual Review|字段绑定|反馈包路径|资产特征值|本地报告中心|contact sheet/);
  assert.doesNotMatch(qualityReport, /<code>\{feedbackDirectory\}<\/code>/);
  assert.doesNotMatch(reportUi, /text_logo_risk/);
  for (const retiredField of ["执行像素提升", "执行降采样", "输出发生变化"]) {
    assert.doesNotMatch(qualityReport, new RegExp(retiredField));
  }
  assert.doesNotMatch(qualityReport, /未触发不建议交付状态|当前为保护型复核，不是处理失败/);
  const safeFacts = reportUi.slice(reportUi.indexOf('<dl className="hdde-report-facts">'), reportUi.indexOf("</dl>", reportUi.indexOf('<dl className="hdde-report-facts">')));
  const standardFacts = qualityReport.slice(qualityReport.indexOf('<dl className="hdde-report-facts">'), qualityReport.indexOf("</dl>", qualityReport.indexOf('<dl className="hdde-report-facts">')));
  assert.doesNotMatch(safeFacts, /未生成|暂无数据|暂无/);
  assert.doesNotMatch(standardFacts, /未生成|暂无数据|暂无/);
  assert.ok(reportUi.indexOf("hdde-report-archive") < reportUi.indexOf("正向信号"), "safe report actions must precede secondary signals");
  assert.ok(qualityReport.indexOf("hdde-report-archive") < qualityReport.indexOf("正向信号"), "standard report actions must precede secondary signals");

  assert.doesNotMatch(reportUi, /<UnifiedFeedback/);
  assert.doesNotMatch(reportUi, /exportSafeBetaFeedbackPackage|\/api\/beta\/safe-1080p\/feedback-package/);
});

test("standard and safe reports explain the same 1080P size contract from real dimensions", () => {
  const upscaled = resolve1080pSizeTreatment({
    inputWidth: 1280,
    inputHeight: 720,
    outputWidth: 1920,
    outputHeight: 1080,
    modeLabel: "1080P画质",
  });
  const preserved = resolve1080pSizeTreatment({
    inputWidth: 1122,
    inputHeight: 1402,
    outputWidth: 1122,
    outputHeight: 1402,
    modeLabel: "1080P画质",
  });

  assert.equal(upscaled?.state, "upscaled");
  assert.equal(upscaled?.label, "短边低于1080px，已按原比例放大至1080P门槛");
  assert.match(upscaled?.detail || "", /1280 × 720 → 1920 × 1080/);
  assert.equal(preserved?.state, "preserved");
  assert.equal(preserved?.label, "已达到1080P门槛、保留原尺寸、未执行像素放大");
  assert.match(preserved?.detail || "", /1122 × 1402 → 1122 × 1402/);

  assert.match(qualityReport, /resolve1080pSizeTreatment/);
  assert.match(qualityReport, /modeLabel: "1080P画质"/);
  assert.match(dashboard, /modeLabel: "1080P画质"/);
  assert.match(dashboard, /sizeTreatment \? \["尺寸处理", sizeTreatment\.label, sizeTreatment\.detail\]/);
});

test("safe enhancement pages keep all explicit user-visible text at 12px or larger", () => {
  const metricStart = dashboard.indexOf("function SafeBetaMetricBar");
  const metricEnd = dashboard.indexOf("function isBrowserPreviewablePath", metricStart);
  const taskStart = dashboard.indexOf('if (activeScreen === "safe_beta_task")');
  const compareStart = dashboard.indexOf('if (activeScreen === "safe_beta_compare")', taskStart);
  const reportStart = dashboard.indexOf('if (activeScreen === "safe_beta_report")', compareStart);
  const reportEnd = dashboard.indexOf("const outputLocationLabel =", reportStart);
  assert.ok(metricStart >= 0 && metricEnd > metricStart);
  assert.ok(taskStart >= 0 && compareStart > taskStart && reportStart > compareStart && reportEnd > reportStart);
  const targetUi = [
    safeBeta,
    dashboard.slice(metricStart, metricEnd),
    dashboard.slice(taskStart, compareStart),
    dashboard.slice(compareStart, reportStart),
    dashboard.slice(reportStart, reportEnd),
  ].join("\n");
  assert.doesNotMatch(targetUi, /text-\[(?:[0-9]|1[01])px\]/);
  assert.doesNotMatch(targetUi, /fontSize:\s*["'](?:[0-9]|1[01])px["']/);
  assert.match(targetUi, /text-xs/);
  assert.match(styles, /body:has\(\.hdde-enhanced-page\) \.hdde-eyebrow[\s\S]*font-size:\s*12px/);
  assert.match(styles, /body:has\(\.hdde-report-page\) \.hdde-feature-status[\s\S]*font-size:\s*12px/);
});

test("processing center has explicit focus reduced-motion and disabled states", () => {
  assert.match(styles, /\.hdde-processing-page button:focus-visible/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(styles, /\.hdde-processing-page button:disabled/);
});

test("unified result keeps real task output with exactly two user decisions", () => {
  for (const contract of [
    'data-testid="unified-result-page"',
    'data-testid="result-compare-anchor"',
    'data-testid="result-review-focus"',
    'data-testid="result-product-summary"',
    "前后对比",
    "复核重点",
    "成品摘要",
    "技术详情",
    "返回调整 / 重新处理",
    "确认结果并交付",
    "resultId",
    "taskConfig?.fileName",
    "outputPath",
    "progress",
    "resultConclusion.label",
  ]) {
    assert.ok(taskDetail.includes(contract), `missing task detail contract: ${contract}`);
  }
  const compareIndex = taskDetail.indexOf('data-testid="result-compare-anchor"');
  const reviewIndex = taskDetail.indexOf('data-testid="result-review-focus"');
  const summaryIndex = taskDetail.indexOf('data-testid="result-product-summary"');
  const decisionsIndex = taskDetail.indexOf('aria-label="处理结果决策"');
  assert.ok(compareIndex > -1 && compareIndex < reviewIndex && reviewIndex < summaryIndex && summaryIndex < decisionsIndex);
  assert.match(taskDetail, /<HddeTechnicalDetails summary="技术详情"/);
  assert.doesNotMatch(taskDetail, /HddeResultHero/);
  assert.doesNotMatch(taskDetail, /查看前后对比|查看处理报告|打开成品/);
  assert.doesNotMatch(
    taskDetail,
    /返回工作台|SAFE 1080P BETA|CORE TASK|BETA STAGE LOG|PROGRESS TIMELINE|UNIFIED ACTIONS|BETA_FETCH|BETA_DONE|Realtime SSE Log/,
  );
  assert.match(taskDetail, /className="hdde-detail-page"/);
  assert.match(styles, /\.hdde-detail-page[\s\S]*background:\s*var\(--content-background\)/);
  assert.match(styles, /\.hdde-detail-panel[\s\S]*background:\s*var\(--card-background\)/);
});

test("automatic processing completion enters the existing unified result route", () => {
  assert.match(dashboard, /let lastCompletedTaskId = ""/);
  assert.match(dashboard, /onNavigate\(`\/task-detail\?task_id=\$\{encodeURIComponent\(lastCompletedTaskId\)\}`\)/);
  assert.match(dashboard, /item\.taskFamily === "color_correction"[\s\S]*onNavigate\(`\/task-detail\?task_id=\$\{encodeURIComponent\(item\.taskId\)\}`\)/);
  assert.match(colorCorrection, /onResultReady/);
  assert.match(colorCorrection, /payload\.data\?\.task\?\.status === "completed"[\s\S]*onResultReady\(payload\.data\.task\.task_id\)/);
  assert.match(app, /"color-correction-review": "\/task-detail"/);
  assert.match(app, /"task-compare": "\/task-detail"/);
  assert.match(app, /"task-report": "\/task-detail"/);
  assert.match(app, /compareAssets: taskContext\.comparisonAssets \|\| null/);
  assert.match(app, /onResultReady=\{\(taskId\) => navigateTo\(`\/task-detail\?task_id=/);
  assert.doesNotMatch(app, /onOpenAdvancedDelivery/);
  assert.doesNotMatch(taskDetail, /onViewCompare|onViewReport/);
});

test("result confirmation reuses real smart delivery and ends in a focused saved state", () => {
  assert.match(taskDetail, /requestDeliveryJson\("\/api\/smart-delivery\/preflight"/);
  assert.match(taskDetail, /JSON\.stringify\(\{ result_ids: \[resultId\], rules: \{\} \}\)/);
  assert.match(taskDetail, /requestDeliveryJson\("\/api\/smart-delivery\/execute"/);
  assert.match(taskDetail, /plan_id: preflight\.plan_id, confirmed: true/);
  assert.match(taskDetail, /completedDelivery\.failure_count > 0 \|\| completedDelivery\.success_count !== 1/);
  assert.match(taskDetail, /failedItem\?\.failure_reason/);
  assert.match(taskDetail, /data-testid="delivery-completion-state"/);
  for (const text of ["成品已保存", "成品文件名", "必要规格", "正式输出目录", "打开输出文件夹", "继续处理", "在输出中心查看"]) {
    assert.ok(taskDetail.includes(text), `missing direct delivery completion contract: ${text}`);
  }
  assert.match(taskDetail, /smart-delivery\/runs\/\$\{encodeURIComponent\(activeDeliveryId\)\}\/open-folder/);
  assert.match(app, /onContinueProcessing=\{\(\) => navigateTo\(DEFAULT_APP_PATH\)\}/);
  assert.match(app, /onViewOutputs=\{\(\) => navigateTo\("\/outputs"\)\}/);
  assert.doesNotMatch(taskDetail, /content-names|USER_CONFIRMED|delivery_location_label/);
});

test("completed result decisions use a compact sticky action bar", () => {
  assert.match(taskDetail, /data-testid="result-action-bar"/);
  assert.match(taskDetail, /className="hdde-detail-result-status">[\s\S]*?结果待确认[\s\S]*?<\/span>/);
  assert.match(taskDetail, /className="hdde-detail-result-action-buttons"[\s\S]*?\{reprocessLabel\}[\s\S]*?确认结果并交付/);
  assert.match(taskDetail, /className="hdde-detail-result-action-buttons"[\s\S]*?onClick=\{onReprocess\}[\s\S]*?disabled=\{!canConfirmAndDeliver\}[\s\S]*?onClick=\{handleConfirmAndDeliver\}/);

  const actionBarStyles = styles.match(/\.hdde-detail-result-decisions\s*\{([\s\S]*?)\n\}/)?.[1] || "";
  assert.match(actionBarStyles, /position:\s*sticky/);
  assert.match(actionBarStyles, /bottom:\s*0/);
  assert.match(actionBarStyles, /min-height:\s*68px/);
  assert.match(actionBarStyles, /justify-content:\s*space-between/);
  assert.match(actionBarStyles, /border-top:\s*1px solid var\(--divider-color\)/);
  assert.doesNotMatch(actionBarStyles, /flex-wrap:\s*wrap/);
});

test("completed result confirmation waits for the browser-readable canonical asset", () => {
  assert.match(app, /task\?\.final_output_url[\s\S]*taskResult\?\.preview_output_url/);
  assert.match(taskDetail, /const \[resultAssetCheck, setResultAssetCheck\] = useState/);
  assert.match(taskDetail, /resultAssetState === "available"/);
  assert.match(taskDetail, /处理结果暂时无法读取，无法确认交付/);
  assert.match(taskDetail, /重新检测结果/);
  assert.match(taskDetail, /onEnhancedAssetLoad=\{\(\) => setResultAssetCheck\(\{ url: compareOutputUrl, status: "available" \}\)\}/);
  assert.match(taskDetail, /onEnhancedAssetError=\{\(\) => setResultAssetCheck\(\{ url: compareOutputUrl, status: "unavailable" \}\)\}/);
  assert.match(comparison, /onEnhancedAssetLoad/);
  assert.match(comparison, /onEnhancedAssetError/);
});

test("task detail keeps task identity internal while preserving data and navigation contracts", () => {
  assert.doesNotMatch(taskDetail, />\s*任务标识\s*</);
  assert.doesNotMatch(taskDetail, /title=\{taskId\b|>\{taskId\b/);
  assert.match(taskDetail, /const taskId = useMemo\(\(\) => getTaskId\(taskConfig\)/);
  assert.doesNotMatch(taskDetail, /<UnifiedFeedback/);
  assert.match(appShell, /<UnifiedFeedback/);
  assert.match(feedbackFlow, /\/api\/v1\/feedback\/context-snapshot/);
  assert.match(feedbackFlow, /\/api\/v1\/feedback\/bundle/);
  assert.match(app, /\/api\/v1\/tasks\/\$\{encodeURIComponent\(taskId\)\}/);
  assert.match(dashboard, /taskId:\s*item\.taskId/);
  assert.match(dashboard, /taskConfig=\{makeTaskConfig\(activeItem\)\}/);
  assert.match(dashboard, /setActiveScreen\("task_detail"\)/);
});

test("rendered task detail never exposes its internal task id", async () => {
  const { default: TaskDetailPage } = await loadRealComponent("/src/TaskDetailPage.jsx");
  const internalTaskId = "task_20260729_065348_98c43e3f";
  const markup = renderToStaticMarkup(React.createElement(TaskDetailPage, {
    taskConfig: {
      taskId: internalTaskId,
      fileName: "真实任务样本.png",
      mode: "texture",
      created_at: "2026-07-30T09:06:24.000Z",
      completed_at: "2026-07-30T09:06:25.500Z",
      task_result: {
        result_id: "result_real_001",
        output_filename: "真实任务样本_1080P.png",
        output_path: "D:\\影界文件\\输出\\1080P标准增强\\真实任务样本_1080P.png",
        final_output_url: "/api/v1/tasks/task-real/result-file",
        target_resolution: "1080P",
        output_format: "png",
        final_delivery_status: "PASS_WITH_LIMITATION",
        input_width: 720,
        input_height: 1080,
        output_width: 1080,
        output_height: 1620,
      },
      task_report: { clarity_score: 82.5, color_fidelity_score: 96.4 },
      compareAssets: {
        originalUrl: "/api/file/uploads/real-input.png",
        resultUrl: "/api/v1/tasks/task-real/result-file",
      },
    },
    disableAutoStream: true,
    taskStatusOverride: "completed",
    progressOverride: 100,
    logsOverride: [],
  }));
  assert.match(markup, /真实任务样本/);
  assert.match(markup, /处理用时/);
  assert.match(markup, /1\.5 秒/);
  assert.match(markup, /前后对比/);
  assert.match(markup, /复核重点/);
  assert.match(markup, /成品摘要/);
  assert.match(markup, /技术详情/);
  assert.match(markup, /82\.5/);
  assert.match(markup, /96\.4/);
  assert.match(markup, /返回调整 \/ 重新处理/);
  assert.match(markup, /确认结果并交付/);
  const decisionMarkup = markup.match(/aria-label="处理结果决策"[^>]*>([\s\S]*?)<\/div>/)?.[1] || "";
  assert.equal((decisionMarkup.match(/<button/g) || []).length, 2);
  assert.doesNotMatch(markup, /任务标识/);
  assert.ok(!markup.includes(internalTaskId), "rendered task detail must not contain taskId");
  assert.ok(!markup.includes("D:\\影界文件"), "main result markup must not expose the engineering path");
});

test("rendered color result turns change protection and review into scan-friendly items", async () => {
  const { default: TaskDetailPage } = await loadRealComponent("/src/TaskDetailPage.jsx");
  const markup = renderToStaticMarkup(React.createElement(TaskDetailPage, {
    taskConfig: {
      taskId: "color_internal_001",
      fileName: "会议照片.jpg",
      operation_mode: "AUTO_COLOR_CORRECTION",
      result_id: "color_result_001",
      originalUrl: "/api/file/uploads/color-input.jpg",
      task_result: {
        result_id: "color_result_001",
        result_action: "ACCEPT_CORRECTED",
        output_selected: "CORRECTED_CANDIDATE",
        delivery_eligible: true,
        final_output_exists: true,
        preview_output_url: "/api/file/outputs/color-output.jpg",
        output_filename: "会议照片_影界自动校正.jpg",
        output_format: "jpg",
        width: 1600,
        height: 1067,
        output_size_bytes: 245760,
        engine_version: "hdde.auto-color-correction.v7-color-core-v2",
        improvements: [
          "保留原始尺寸、构图与透明通道",
          "可信中性色偏差已受控校正",
          "原图哈希保持不变，未覆盖或修改原图",
        ],
        review_points: ["请复核肤色、LED屏文字与品牌色是否自然"],
      },
    },
    disableAutoStream: true,
    taskStatusOverride: "completed",
    progressOverride: 100,
  }));
  for (const text of ["变化", "中性色偏已受控", "保护", "原图未覆盖", "复核", "肤色、屏幕文字与品牌色"]) {
    assert.ok(markup.includes(text), `missing compact color result item: ${text}`);
  }
  assert.match(markup, /<summary>技术详情<\/summary>/);
  assert.match(markup, /hdde\.auto-color-correction\.v7-color-core-v2/);
  assert.ok(!markup.includes("color_internal_001"), "color task id must stay internal");
  assert.match(markup, /确认结果并交付/);
});

test("accept-original color result shows a completed no-output state without review or delivery", async () => {
  const { default: TaskDetailPage } = await loadRealComponent("/src/TaskDetailPage.jsx");
  const markup = renderToStaticMarkup(React.createElement(TaskDetailPage, {
    taskConfig: {
      taskId: "color_original_internal_001",
      fileName: "无需校正.jpg",
      operation_mode: "AUTO_COLOR_CORRECTION",
      status: "completed",
      result_id: "color_original_result_001",
      final_output_exists: false,
      final_output_url: "/api/v1/tasks/color_original_internal_001/result-file",
      originalUrl: "/api/v1/tasks/color_original_internal_001/source-file",
      task_result: {
        result_id: "color_original_result_001",
        result_action: "ACCEPT_ORIGINAL",
        output_selected: "ORIGINAL",
        result_file: "D:\\影界文件\\输出\\图片压缩\\.运行缓存\\source.jpg",
        output_path: "",
        final_output_exists: false,
        delivery_eligible: false,
        improvements: ["原图哈希保持不变，未覆盖或修改原图", "D3 选择保留原图，未生成正式修改结果"],
      },
    },
    disableAutoStream: true,
    taskStatusOverride: "completed",
    progressOverride: 100,
  }));
  assert.match(markup, /保留原图/);
  assert.match(markup, /当前图片无需生成新的校正成品/);
  assert.doesNotMatch(markup, /待确认/);
  assert.doesNotMatch(markup, /data-testid="result-compare-anchor"/);
  assert.doesNotMatch(markup, /确认结果并交付|重试交付/);
  assert.ok(!markup.includes("color_original_internal_001"), "accept-original task id must stay internal");
});

test("review-required color candidate keeps its human confirmation entry", async () => {
  const { default: TaskDetailPage } = await loadRealComponent("/src/TaskDetailPage.jsx");
  const markup = renderToStaticMarkup(React.createElement(TaskDetailPage, {
    taskConfig: {
      taskId: "color_review_internal_001",
      fileName: "待复核.jpg",
      operation_mode: "AUTO_COLOR_CORRECTION",
      status: "completed",
      result_id: "color_review_result_001",
      result_review_status: "pending",
      delivery_id: null,
      task_result: {
        result_id: "color_review_result_001",
        result_action: "REVIEW_REQUIRED",
        output_selected: "REVIEW_CANDIDATE",
        preview_output_url: "/api/v1/tasks/color_review_internal_001/result-file",
        output_path: "D:\\影界文件\\输出\\颜色校正\\review.jpg",
        final_output_exists: true,
        delivery_eligible: false,
      },
    },
    disableAutoStream: true,
    taskStatusOverride: "completed",
    progressOverride: 100,
  }));
  assert.match(markup, /data-testid="result-compare-anchor"/);
  assert.match(markup, /确认结果并交付/);
  assert.doesNotMatch(markup, /保留原图/);
});

test("confirmed delivered color candidate restores its persisted completion state after refresh", async () => {
  const { default: TaskDetailPage } = await loadRealComponent("/src/TaskDetailPage.jsx");
  const internalTaskId = "color_delivered_internal_001";
  const internalDeliveryPath = "D:\\影界文件\\输出\\正式交付\\已确认交付.jpg";
  const markup = renderToStaticMarkup(React.createElement(TaskDetailPage, {
    taskConfig: {
      taskId: internalTaskId,
      fileName: "已确认候选.jpg",
      operation_mode: "AUTO_COLOR_CORRECTION",
      status: "completed",
      result_id: "color_delivered_result_001",
      result_review_status: "confirmed",
      delivery_id: "delivery_color_completed_001",
      deliveries: [{
        id: "delivery_color_completed_001",
        status: "completed",
        final_filename: "已确认交付.jpg",
        delivery_file: internalDeliveryPath,
        size_bytes: 245760,
      }],
      task_result: {
        result_id: "color_delivered_result_001",
        result_action: "REVIEW_REQUIRED",
        output_selected: "REVIEW_CANDIDATE",
        preview_output_url: "/api/v1/tasks/color_delivered_internal_001/result-file",
        output_path: "D:\\影界文件\\输出\\颜色校正\\candidate.jpg",
        output_format: "jpg",
        output_width: 1600,
        output_height: 1067,
        final_output_exists: true,
        delivery_eligible: true,
      },
    },
    disableAutoStream: true,
    taskStatusOverride: "completed",
    progressOverride: 100,
  }));
  assert.match(markup, /data-testid="delivery-completion-state"/);
  assert.match(markup, /正式交付完成/);
  assert.match(markup, /成品已保存/);
  assert.match(markup, /已确认交付\.jpg/);
  assert.doesNotMatch(markup, /待确认|确认结果并交付|重试交付/);
  assert.ok(!markup.includes(internalTaskId), "completed color task id must stay internal");
  assert.ok(!markup.includes(internalDeliveryPath), "completed color delivery path must stay internal");
});

test("persisted color review confirmation prevents duplicate review and delivery submission", () => {
  assert.match(taskDetail, /!persistedReviewConfirmed && !sessionReviewConfirmed/);
  assert.match(taskDetail, /setSessionReviewConfirmed\(true\)/);
  assert.match(taskDetail, /colorDeliveryAllowed && !acceptOriginal && !persistedReviewConfirmed/);
  assert.match(taskDetail, /persistedDeliveryStatus === "completed"/);
});

test("rendered protection-blocked color task explains safety gate without a broken result", async () => {
  const { default: TaskDetailPage } = await loadRealComponent("/src/TaskDetailPage.jsx");
  const markup = renderToStaticMarkup(React.createElement(TaskDetailPage, {
    taskConfig: {
      taskId: "color_blocked_internal_001",
      fileName: "受保护样本.png",
      operation_mode: "AUTO_COLOR_CORRECTION",
      status: "completed",
      progress: 100,
      result_id: "legacy_empty_result_001",
      task_result: {
        result_id: "legacy_empty_result_001",
        d3_status: "PROTECTION_BLOCKED",
        output_selected: "NONE",
      },
    },
    disableAutoStream: true,
    taskStatusOverride: "completed",
    progressOverride: 100,
  }));
  assert.match(markup, /本次未进行自动校正/);
  assert.match(markup, /检测到自动调整可能影响原图质量，已保留原图。/);
  assert.doesNotMatch(markup, /保护门禁|可审核结果|D1|D2|D3/);
  assert.doesNotMatch(markup, /处理结果暂时无法读取/);
  assert.doesNotMatch(markup, /data-testid="result-compare-anchor"/);
  assert.doesNotMatch(markup, /确认结果并交付/);
});

test("rendered 4K result keeps comparison first and dimensions in one product summary", async () => {
  const { default: TaskDetailPage } = await loadRealComponent("/src/TaskDetailPage.jsx");
  const markup = renderToStaticMarkup(React.createElement(TaskDetailPage, {
    taskConfig: {
      taskId: "fourk_internal_001",
      fileName: "商业海报.png",
      mode: "4k_v1",
      result_id: "fourk_result_001",
      originalUrl: "/api/file/uploads/fourk-input.png",
      task_result: {
        result_id: "fourk_result_001",
        preview_output_url: "/api/file/outputs/fourk-output.png",
        output_filename: "商业海报_4K.png",
        output_format: "png",
        final_output_exists: true,
        input_width: 1080,
        input_height: 1440,
        output_width: 2880,
        output_height: 3840,
      },
      task_report: { source_hash_unchanged: true },
    },
    disableAutoStream: true,
    taskStatusOverride: "completed",
    progressOverride: 100,
  }));
  assert.ok(markup.indexOf("前后对比") < markup.indexOf("复核重点"));
  assert.equal((markup.match(/尺寸变化/g) || []).length, 1);
  assert.match(markup, /1080 × 1440 → 2880 × 3840/);
  assert.match(markup, /保持原图比例与构图，长边提升至3840像素：超分重建细节，并以原图保真融合，防止色偏、重绘与过锐光晕/);
  assert.ok(!markup.includes("fourk_internal_001"), "4K task id must stay internal");
});

test("comparison keeps real assets metrics and delivery actions with formal Chinese sections", () => {
  for (const contract of [
    'data-testid="comparison-page"',
    "处理前后对比",
    "技术指标",
    "输出与交付",
    "文字清晰度",
    "边缘质量",
    "色彩忠实度",
    "纹理保持度",
    "查看交付报告",
    "resolveAssets(taskConfig, compareAssets)",
    "metricValue(report, result, key)",
    "assets.originalUrl",
    "assets.enhancedUrl",
  ]) {
    assert.ok(comparison.includes(contract), `missing comparison contract: ${contract}`);
  }
  assert.doesNotMatch(comparison, /CONTACT SHEET|PHYSICAL QA|OUTPUT BINDING|TEXT_CLARITY_SCORE|EDGE_QUALITY_SCORE|COLOR_FIDELITY_SCORE|返回工作台/);
  assert.match(comparison, /className="hdde-compare-page"/);
  assert.match(styles, /\.hdde-compare-page[\s\S]*background:\s*var\(--content-background\)/);
  assert.match(styles, /\.hdde-compare-panel[\s\S]*background:\s*var\(--card-background\)/);
});

test("rendered comparison preserves real assets and quality metrics", async () => {
  const { default: ImageSliderComparePage } = await loadRealComponent("/src/ImageSliderComparePage.jsx");
  const markup = renderToStaticMarkup(React.createElement(ImageSliderComparePage, {
    taskConfig: {
      fileName: "真实对比样本.png",
      task_result: {
        output_filename: "真实对比样本.png",
        preview_output_url: "/api/file/outputs/real-output.png",
        final_output_url: "/api/file/outputs/real-output.png",
        output_width: 1080,
        output_height: 1518,
        output_format: "png",
        final_delivery_status: "PASS_WITH_LIMITATION",
      },
      task_report: {
        text_clarity_score: 71.25,
        edge_quality_score: 83.5,
        color_fidelity_score: 97.6,
        texture_score: 74.2,
      },
      compareAssets: { fileName: "真实对比样本.png", originalUrl: "/api/file/uploads/real-input.png" },
    },
    compareAssets: { fileName: "真实对比样本.png", originalUrl: "/api/file/uploads/real-input.png" },
  }));
  assert.match(markup, /真实对比样本/);
  assert.match(markup, /71\.25/);
  assert.match(markup, /97\.6/);
  assert.match(markup, /\/api\/file\/uploads\/real-input\.png/);
  assert.match(markup, /\/api\/file\/outputs\/real-output\.png/);
});

test("quality report renders real metrics without internal fields or duplicate feedback", async () => {
  const { default: QualityReportPage } = await loadRealComponent("/src/QualityReportPage.jsx");
  const internalTaskId = "task_20260729_065348_98c43e3f";
  const markup = renderToStaticMarkup(React.createElement(QualityReportPage, {
    taskConfig: {
      taskId: internalTaskId,
      task_result: {
        input_filename: "真实质量样本.png",
        output_filename: "真实质量样本_1080P.png",
        input_width: 1058,
        input_height: 1487,
        output_width: 1080,
        output_height: 1518,
        output_format: "png",
        resize_policy: "保持比例输出",
        output_changed: true,
        final_delivery_status: "PASS_WITH_LIMITATION",
      },
      task_report: {
        clarity_score: 82.5,
        text_clarity_score: 71.25,
        edge_quality_score: 83.5,
        color_fidelity_score: 97.6,
        texture_score: 74.2,
        delivery_score: 81.4,
        final_delivery_status: "PASS_WITH_LIMITATION",
      },
    },
  }));
  assert.match(markup, /真实质量样本/);
  assert.match(markup, /82\.50/);
  assert.match(markup, /查看技术评分/);
  assert.ok(!markup.includes(internalTaskId), "rendered quality report must not contain taskId");
  assert.doesNotMatch(markup, /task_id|taskId|技术详情|开发者信息|raw delivery|RC1/);
  assert.doesNotMatch(qualityReport, /<UnifiedFeedback/);
  assert.match(appShell, /<UnifiedFeedback/);
  assert.match(unifiedFeedback, /captureFeedbackContext/);
  assert.match(unifiedFeedback, /generateUnifiedFeedbackBundle/);
  assert.match(qualityReport, /\/api\/output\/open/);
  assert.doesNotMatch(qualityReport, /feedback_bundle_path|\{feedback\.path\}<\/code>/);
});

test("rendered local retouch result uses unified comparison review and delivery decisions", async () => {
  const { default: TaskDetailPage } = await loadRealComponent("/src/TaskDetailPage.jsx");
  const markup = renderToStaticMarkup(React.createElement(TaskDetailPage, {
    taskConfig: {
      taskId: "retouch_internal_001",
      processing_type: "local_retouch",
      status: "completed",
      result_id: "retouch_result_001",
      originalUrl: "/api/local-retouch/sessions/session_001/source",
      task_result: {
        result_id: "retouch_result_001",
        processing_type: "local_retouch",
        preview_output_url: "/api/v1/tasks/retouch_internal_001/result-file",
        output_filename: "retouch-final.png",
        output_format: "PNG",
        final_output_exists: true,
        source_hash_unchanged: true,
        working_revision: 3,
        input_width: 96,
        input_height: 72,
        output_width: 96,
        output_height: 72,
      },
      compareAssets: {
        originalUrl: "/api/local-retouch/sessions/session_001/source",
        resultUrl: "/api/v1/tasks/retouch_internal_001/result-file",
      },
    },
    disableAutoStream: true,
    taskStatusOverride: "completed",
  }));
  assert.match(markup, /data-testid="result-compare-anchor"/);
  assert.match(markup, /边缘衔接与纹理连续性/);
  assert.match(markup, /累计 3 次修整/);
  assert.match(markup, /返回调整 \/ 重新处理/);
  assert.match(markup, /确认结果并交付/);
  assert.match(markup, /\/api\/local-retouch\/sessions\/session_001\/source/);
  assert.match(markup, /\/api\/v1\/tasks\/retouch_internal_001\/result-file/);
  assert.doesNotMatch(markup, /瑕疵修整报告/);
});
