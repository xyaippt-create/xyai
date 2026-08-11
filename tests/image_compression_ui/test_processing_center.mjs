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
const dashboard = fs.readFileSync(path.join(root, "src", "DashboardPage.jsx"), "utf8");
const app = fs.readFileSync(path.join(root, "src", "App.jsx"), "utf8");
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
      "image-diagnosis",
      "color-correction",
    "compression",
    "retouch",
    "smart-delivery",
    "outputs",
    "settings",
  ]);
  assert.equal(APP_ROUTES.find((route) => route.key === "settings")?.implementationType, "existing");
  assert.equal(APP_ROUTES.find((route) => route.key === "compare")?.showInNavigation, false);
  assert.equal(APP_ROUTES.find((route) => route.key === "quality-report")?.showInNavigation, false);
  assert.equal(APP_ROUTES.find((route) => route.key === "tasks")?.showInNavigation, false);
  assert.equal(APP_ROUTES.find((route) => route.key === "history")?.showInNavigation, false);
  assert.equal(APP_ROUTES.find((route) => route.key === "batch")?.showInNavigation, false);
  assert.equal(APP_ROUTES.find((route) => route.key === "tasks")?.path, "/tasks");
  assert.match(appShell, /showInNavigation !== false/);
});

test("processing center owns current and historical tasks from the shared task fact source", () => {
  assert.match(dashboard, /requestJson\("GET", `\$\{API_BASE\}\/api\/v1\/tasks`\)/);
  assert.match(dashboard, /role="tab"[\s\S]*当前任务/);
  assert.match(dashboard, /role="tab"[\s\S]*历史任务/);
  assert.match(dashboard, /historyTaskItems = fileQueue\.filter/);
  for (const field of ["featureKey", "taskId", "resultId", "deliveryId"]) {
    assert.match(dashboard, new RegExp(field));
  }
  assert.match(app, /initialTaskView=\{route\?\.key === "history" \? "history" : "current"\}/);
});

test("4K shortcut reuses the processing center upload task comparison and report flow", () => {
  const route = APP_ROUTES.find((item) => item.key === "four-k-enhancement");
  assert.equal(route?.name, "4K高清增强");
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
  assert.match(indexHtml, /<link rel="icon" type="image\/svg\+xml" href="\/favicon\.svg"\s*\/>/);
  const faviconPath = path.join(root, "public", "favicon.svg");
  assert.ok(fs.existsSync(faviconPath));
  const favicon = fs.readFileSync(faviconPath, "utf8");
  assert.match(favicon, /#2D6FE8/i);
  assert.match(favicon, /aria-label="影界 HDDE"/);
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
  assert.match(dashboard, /1080P标准增强", className: "text-\[var\(--brand-primary\)\]"/);
  assert.match(dashboard, /1080P安全增强", className: "text-\[var\(--brand-primary\)\]"/);
  assert.doesNotMatch(dashboard, /1080P安全增强.*Beta/);
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

test("safe enhancement entry is a product entry instead of a beta test console", () => {
  for (const contract of ["1080P安全增强", "进入处理中心", "处理前请确认"]) {
    assert.ok(safeBeta.includes(contract), `missing safe entry contract: ${contract}`);
  }
  assert.doesNotMatch(safeBeta, />[^<]*Beta[^<]*</);
  assert.doesNotMatch(safeBeta, /试用功能|独立测试入口|运行结果|BETA_|runBeta|ResultLine|输入目录|输出目录|导出测试反馈包/);
  assert.match(appRoutesSource, /name: "1080P安全增强"/);
  assert.match(appRoutesSource, /pageTitle: "1080P安全增强"/);
  assert.equal(COMPATIBILITY_ROUTES.find((route) => route.key === "safe-1080p-beta")?.status, FEATURE_STATUSES.ENABLED);
});

test("clipboard GUID names are friendly in the UI without changing ordinary filenames", () => {
  const clipboardName = "codex-clipboard-b87d416a-976c-4407-95b0-43dc8406edb6.png";
  assert.equal(getFileDisplayName(clipboardName), "剪贴板图片");
  assert.equal(getFileDisplayName(`D:\\输入\\${clipboardName}`), "剪贴板图片");
  assert.equal(getFileDisplayName("普通交付图片_最终版.png"), "普通交付图片_最终版.png");
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

  for (const contract of ["高清交付评估", "质量评分", "输出结果", "交付结论", "复核重点", "正向信号", "建议用途", "结果操作"]) {
    assert.ok(reportUi.includes(contract), `missing safe report contract: ${contract}`);
    assert.ok(qualityReport.includes(contract), `missing standard report contract: ${contract}`);
  }
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

  assert.match(reportUi, /<UnifiedFeedback/);
  assert.match(reportUi, /sourceFeature="enhancement_1080p"/);
  assert.match(reportUi, /triggerLabel="反馈问题"/);
  assert.doesNotMatch(reportUi, /exportSafeBetaFeedbackPackage|\/api\/beta\/safe-1080p\/feedback-package/);
});

test("standard and safe reports explain the same 1080P size contract from real dimensions", () => {
  const upscaled = resolve1080pSizeTreatment({
    inputWidth: 1280,
    inputHeight: 720,
    outputWidth: 1920,
    outputHeight: 1080,
    modeLabel: "1080P标准增强",
  });
  const preserved = resolve1080pSizeTreatment({
    inputWidth: 1122,
    inputHeight: 1402,
    outputWidth: 1122,
    outputHeight: 1402,
    modeLabel: "1080P安全增强",
  });

  assert.equal(upscaled?.state, "upscaled");
  assert.equal(upscaled?.label, "短边低于1080px，已按原比例放大至1080P门槛");
  assert.match(upscaled?.detail || "", /1280 × 720 → 1920 × 1080/);
  assert.equal(preserved?.state, "preserved");
  assert.equal(preserved?.label, "已达到1080P门槛、保留原尺寸、未执行像素放大");
  assert.match(preserved?.detail || "", /1122 × 1402 → 1122 × 1402/);

  assert.match(qualityReport, /resolve1080pSizeTreatment/);
  assert.match(qualityReport, /modeLabel: "1080P标准增强"/);
  assert.match(dashboard, /modeLabel: "1080P安全增强"/);
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

test("task detail keeps real task output and actions without internal beta console labels", () => {
  for (const contract of [
    'data-testid="task-detail-page"',
    "返回处理中心",
    "查看前后对比",
    "查看处理报告",
    "反馈问题",
    "打开输出文件夹",
    "打开成品",
    "重新处理",
    "taskConfig?.fileName",
    "outputPath",
    "progress",
    "delivery.label",
  ]) {
    assert.ok(taskDetail.includes(contract), `missing task detail contract: ${contract}`);
  }
  assert.match(dashboard, /setActiveScreen\("task_detail"\)/);
  assert.match(
    dashboard,
    /item\.taskFamily === "color_correction" \? "复核结果" : item\.taskFamily === "image_diagnosis" \? "查看诊断" : "查看详情"/,
  );
  assert.match(dashboard, /onBackToTask=\{\(\) => setActiveScreen\("task_detail"\)\}/);
  assert.doesNotMatch(
    taskDetail,
    /返回工作台|SAFE 1080P BETA|CORE TASK|BETA STAGE LOG|PROGRESS TIMELINE|UNIFIED ACTIONS|BETA_FETCH|BETA_DONE|Realtime SSE Log/,
  );
  assert.match(taskDetail, /className="hdde-detail-page"/);
  assert.match(styles, /\.hdde-detail-page[\s\S]*background:\s*var\(--content-background\)/);
  assert.match(styles, /\.hdde-detail-panel[\s\S]*background:\s*var\(--card-background\)/);
});

test("task detail keeps task identity internal while preserving data and navigation contracts", () => {
  assert.doesNotMatch(taskDetail, />\s*任务标识\s*</);
  assert.doesNotMatch(taskDetail, /title=\{taskId\b|>\{taskId\b/);
  assert.match(taskDetail, /const taskId = useMemo\(\(\) => getTaskId\(taskConfig\)/);
  assert.match(taskDetail, /<UnifiedFeedback[\s\S]*taskId=\{taskId\}[\s\S]*sourceFeature="processing_center"/);
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
        output_filename: "真实任务样本_1080P.png",
        output_path: "D:\\影界文件\\输出\\1080P标准增强\\真实任务样本_1080P.png",
        target_resolution: "1080P",
        output_format: "png",
        final_delivery_status: "PASS_WITH_LIMITATION",
      },
      task_report: { clarity_score: 82.5 },
    },
    disableAutoStream: true,
    taskStatusOverride: "completed",
    progressOverride: 100,
    logsOverride: [],
  }));
  assert.match(markup, /真实任务样本/);
  assert.match(markup, /处理用时/);
  assert.match(markup, /1\.5 秒/);
  assert.doesNotMatch(markup, /任务标识/);
  assert.ok(!markup.includes(internalTaskId), "rendered task detail must not contain taskId");
});

test("comparison keeps real assets metrics and delivery actions with formal Chinese sections", () => {
  for (const contract of [
    'data-testid="comparison-page"',
    "处理前后对比",
    "高清交付指标",
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

test("quality report renders real metrics and feedback action without internal fields", async () => {
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
  assert.match(markup, /反馈问题/);
  assert.match(markup, /用于问题反馈和故障排查/);
  assert.ok(!markup.includes(internalTaskId), "rendered quality report must not contain taskId");
  assert.doesNotMatch(markup, /task_id|taskId|技术详情|开发者信息|raw delivery|RC1/);
  assert.match(qualityReport, /<UnifiedFeedback[\s\S]*taskId=\{taskId\}[\s\S]*sourceFeature="quality_confirm"/);
  assert.match(unifiedFeedback, /captureFeedbackContext/);
  assert.match(unifiedFeedback, /generateUnifiedFeedbackBundle/);
  assert.match(qualityReport, /\/api\/output\/open/);
  assert.doesNotMatch(qualityReport, /feedback_bundle_path|\{feedback\.path\}<\/code>/);
});
