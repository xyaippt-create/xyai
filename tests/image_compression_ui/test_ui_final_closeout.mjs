import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { resolveDeliveryStatus } from "../../src/deliveryStatus.js";
import { noCandidateUiState } from "../../src/longImagePolicy.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const read = (relativePath) => fs.readFileSync(path.join(root, relativePath), "utf8");
const styles = read("src/index.css");
const preview = read("src/CompressionPreview.jsx");
const compressionPage = read("src/CompressionPage.jsx");
const dashboard = read("src/DashboardPage.jsx");
const systemSettingsTest = read("tests/image_compression_ui/test_system_settings.mjs");

test("retouch required labels keep a 12px readability floor", () => {
  assert.match(styles, /\.hdde-retouch-inspector__heading span,[\s\S]*?\.hdde-retouch-summary span,[\s\S]*?\.hdde-retouch-range-label > span[\s\S]*?font-size:\s*12px/);
});

test("system settings test harness defaults to the isolated API sink", () => {
  assert.match(systemSettingsTest, /process\.env\.HDDE_API_TARGET \|\|= "http:\/\/127\.0\.0\.1:0"/);
});

test("delivery completion header and card share the result content width", () => {
  assert.match(styles, /\.hdde-detail-page\[data-testid="delivery-completion-state"\][\s\S]*?\.hdde-detail-header,[\s\S]*?\.hdde-delivery-completion[\s\S]*?width:\s*min\(1120px,\s*100%\)/);
});

test("all explicit visible font sizes keep a 12px floor", () => {
  assert.doesNotMatch(styles, /font-size:\s*11px/);
});

test("processing summaries only render for a real current-task context", () => {
  assert.match(dashboard, /const showCurrentSummary = taskView === "current"/);
  assert.match(dashboard, /\{showCurrentSummary \? \([\s\S]*?className="hdde-processing-summary-grid"/);
});

test("processing directory detection remains a neutral loading state", () => {
  assert.match(dashboard, /const workdirPending = !workdirInfo && !workdirError/);
  assert.match(dashboard, /workdirPending \? "正在检测正式目录"/);
  assert.match(dashboard, /workdirPending \? "正在检测正式目录" : !directoryReady \? "请先修复正式目录"/);
});

test("backend final delivery status is authoritative over UI quality hints", () => {
  const delivery = resolveDeliveryStatus({
    final_delivery_status: "PASS",
    text_clarity_score: 20,
    final_delivery_reason: "quality_1080p_gate_not_fully_passed",
  });
  assert.equal(delivery.status, "PASS");
  assert.equal(delivery.label, "已改善");

  const waiting = resolveDeliveryStatus({
    text_clarity_score: 20,
    final_delivery_reason: "quality_1080p_gate_not_fully_passed",
  });
  assert.equal(waiting.status, "WAITING");
});

test("compression confirmation requires a real candidate and preserves the no-processing truth", () => {
  const noProcessing = noCandidateUiState({
    technical_status: "NO_PROCESSING_NEEDED",
    output_created: false,
    candidate_delivery_role: "SOURCE_NO_PROCESSING",
    delivery_gate_status: "DELIVERY_READY",
  });

  assert.equal(noProcessing.candidateDeliveryReady, false);
  assert.match(compressionPage, /const compressionDeliveryReady = candidateState\.candidateDeliveryReady/);
  assert.match(compressionPage, /data-testid="compression-open-folder"[\s\S]*?!compressionDeliveryReady/);
  assert.match(compressionPage, /data-testid="compression-delivery-state"/);
  assert.match(compressionPage, /确认完成，可以交付/);
  assert.match(compressionPage, /candidateState\.sourceNoProcessing[\s\S]*?原图已满足要求/);
  assert.match(compressionPage, /继续使用原图，或调整参数后重新处理/);
});

test("feedback result card, actions and note use one aligned footer grid", () => {
  assert.match(styles, /\.hdde-feedback-dialog > footer[\s\S]*?align-items:\s*center[\s\S]*?gap:\s*12px/);
  assert.match(styles, /\.hdde-feedback-dialog > footer a,[\s\S]*?\.hdde-feedback-dialog > footer button[\s\S]*?height:\s*44px[\s\S]*?margin:\s*0/);
});

test("compression source preview removes duplicate side metadata and uses one compact info band", () => {
  const canvasAt = preview.indexOf('className="hdde-compression-preview-canvas"');
  const summaryAt = preview.indexOf('className="hdde-compression-preview-summary"');
  const toolbarAt = preview.indexOf('className="hdde-compression-preview-toolbar"');
  assert.ok(canvasAt >= 0 && summaryAt > canvasAt && toolbarAt > summaryAt);
  assert.doesNotMatch(compressionPage, /className="hdde-compression-file-meta"/);
  assert.match(preview, /fileName/);
  assert.match(preview, /sourceSizeBytes/);
  assert.match(preview, /actions/);
  assert.match(styles, /\.hdde-compression-preview-file-name[\s\S]*?text-overflow:\s*ellipsis/);
  assert.match(styles, /\.hdde-compression-preview-summary\s*\{[\s\S]*?display:\s*flex/);
  assert.match(styles, /\.hdde-compression-dropzone\.has-file\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1fr\)/);
});
