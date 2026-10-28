import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (relativePath) => fs.readFileSync(path.join(ROOT, relativePath), "utf8");

const app = read("src/App.jsx");
const shell = read("src/AppShell.jsx");
const routes = read("src/appRoutes.js");
const dashboard = read("src/DashboardPage.jsx");
const display = read("src/productDisplay.js");
const feedback = read("src/UnifiedFeedback.jsx");
const feedbackFlow = read("src/feedbackFlow.js");
const output = read("src/OutputCenterPage.jsx");
const settings = read("src/SystemSettingsPage.jsx");
const styles = read("src/index.css");

test("V1 public product names are unified and the retired diagnosis bridge stays removed", () => {
  assert.match(routes, /name: "1080P画质"/);
  assert.match(routes, /name: "4K画质增强"/);
  assert.doesNotMatch(routes, /name: "(?:1080P普通增强|1080P标准增强|1080P画质增强|4K尺寸适配|4K高清增强)"/);
  assert.doesNotMatch(dashboard, /label: "(?:1080P普通增强|1080P标准增强|1080P画质增强|4K尺寸适配|4K高清增强)"/);
  assert.match(display, /"1080P普通增强": PRODUCT_DISPLAY_NAMES\.enhancement1080p/);
  assert.match(display, /"1080P标准增强": PRODUCT_DISPLAY_NAMES\.enhancement1080p/);
  assert.match(display, /"4K尺寸适配": PRODUCT_DISPLAY_NAMES\.enhancement4k/);
  assert.match(display, /"4K高清增强": PRODUCT_DISPLAY_NAMES\.enhancement4k/);
  assert.doesNotMatch(app, /handleDiagnosisRecommendation|from=image-diagnosis/);
  assert.doesNotMatch(routes, /image-diagnosis/);
  assert.match(dashboard, /PROCESSING_MODE_SAFE_BETA = "safe_1080p_beta"/);
});

test("4K shortcut keeps the shared processing context and a single selected navigation item", () => {
  assert.match(app, /shellRoute = route\?\.key === "processing" && requestedMode === "4k_v1"/);
  assert.match(shell, /const active = item\.key === \(NAVIGATION_CONTEXT_BY_ROUTE\[route\?\.key\] \|\| route\?\.key\)/);
  assert.doesNotMatch(shell, /item\.path === currentPath/);
  assert.match(dashboard, /processingMode === PROCESSING_MODE_FOUR_K \? "4K画质增强" : "处理中心"/);
});

test("application shell owns the only main landmark and feedback entry", () => {
  const srcFiles = fs.readdirSync(path.join(ROOT, "src")).filter((name) => /\.(?:jsx|js)$/.test(name));
  const combined = srcFiles.map((name) => read(`src/${name}`)).join("\n");
  assert.equal((combined.match(/<main\b/g) || []).length, 1);
  assert.equal((combined.match(/<\/main>/g) || []).length, 1);
  assert.match(shell, /<UnifiedFeedback/);
  assert.equal((combined.match(/<UnifiedFeedback\b/g) || []).length, 2, "shell plus immersive retouch workspace only");
  assert.match(feedback, /aria-label="关闭问题反馈"/);
  assert.match(feedback, /<HddeIcon name="close"/);
  assert.match(feedback, /event\.key === "Escape"/);
});

test("feedback context supports ordinary no-task pages without manufacturing an id", () => {
  assert.match(feedbackFlow, /\.\.\.\(taskId \? \{ task_id: taskId \} : \{\}\)/);
  const requestBlock = feedbackFlow.slice(feedbackFlow.indexOf("export async function captureFeedbackContext"), feedbackFlow.indexOf("export async function generateUnifiedFeedbackBundle"));
  assert.doesNotMatch(requestBlock, /task_id:\s*taskId\s*\|\|\s*null/);
});

test("result pages keep the frozen result hierarchy and technical metrics folded", () => {
  const taskDetail = read("src/TaskDetailPage.jsx");
  const compareIndex = taskDetail.indexOf('data-testid="result-compare-anchor"');
  const reviewIndex = taskDetail.indexOf('data-testid="result-review-focus"');
  const summaryIndex = taskDetail.indexOf('data-testid="result-product-summary"');
  assert.ok(compareIndex >= 0 && compareIndex < reviewIndex && reviewIndex < summaryIndex);
  assert.match(taskDetail, /HddeTechnicalDetails/);
  assert.doesNotMatch(taskDetail, /HddeResultHero/);
  for (const file of [
    "src/ImageSliderComparePage.jsx",
    "src/QualityReportPage.jsx",
    "src/ColorCorrectionPage.jsx",
    "src/CompressionPage.jsx",
  ]) {
    const source = read(file);
    assert.match(source, /HddeResultHero/, `${file} must expose a conclusion-first result`);
    assert.match(source, /HddeTechnicalDetails/, `${file} must fold technical details`);
  }
  assert.match(read("src/HddeUI.jsx"), /结果结论/);
  assert.match(read("src/HddeUI.jsx"), /处理前后变化/);
  assert.match(read("src/HddeUI.jsx"), /安全保护/);
  assert.match(read("src/HddeUI.jsx"), /下一步/);
});

test("task state result conclusion and manual review remain separate user concepts", () => {
  assert.match(dashboard, /已选素材/);
  assert.match(dashboard, /等待创建任务/);
  assert.doesNotMatch(dashboard, /TASK_ID：|RESULT_ID：|DELIVERY_ID：/);
  assert.match(read("src/deliveryStatus.js"), /label: "已改善"/);
  assert.match(read("src/deliveryStatus.js"), /label: "建议复核"/);
  assert.match(read("src/deliveryStatus.js"), /label: "不可使用"/);
  assert.match(dashboard, /review_status === "confirmed"/);
});

test("output center exposes compact search sort selection and responsive detail behavior", () => {
  assert.match(output, /placeholder="搜索文件名"/);
  assert.match(output, /value=\{sortOrder\}/);
  // S61-OC-00 selects single cards and available batch children through the shared list.
  assert.match(output, /selectableItems\.find\(\(item\) => item\.id === selectedId\)/);
  assert.match(styles, /\.hdde-output-toolbar/);
  assert.match(styles, /@media \(min-width: 900px\) and \(max-width: 1120px\)/);
  assert.match(styles, /overflow-wrap: anywhere/);
});

test("shared interaction system defines clear action levels, focus and disabled states", () => {
  for (const selector of ["hdde-primary-action", "hdde-secondary-action", "hdde-tertiary-action", "hdde-danger-action"]) {
    assert.ok(styles.includes(`.${selector}`), `missing ${selector}`);
  }
  assert.match(styles, /min-height: 44px/);
  assert.match(styles, /:focus-visible/);
  assert.match(styles, /:disabled/);
  assert.match(styles, /\.hdde-feedback-close[\s\S]*width: 44px;[\s\S]*height: 44px/);
});

test("settings keeps the product version but hides developer build identity", () => {
  assert.match(settings, /health\.version \|\| PRODUCT_VERSION_LABEL/);
  assert.doesNotMatch(settings, /CURRENT_BUILD_ID|dirty|commit/i);
});
