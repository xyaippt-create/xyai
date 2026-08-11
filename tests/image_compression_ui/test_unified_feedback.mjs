import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const sourceUrl = new URL("../../src/feedbackFlow.js", import.meta.url);
const source = (await readFile(sourceUrl, "utf8"))
  .replace(/^import \{ CURRENT_BUILD_ID \} from .*;\r?\n/m, "const CURRENT_BUILD_ID = 'V0.5.4-dev+test-build';\n")
  .replace(/^import \{ PRODUCT_VERSION_LABEL \} from .*;\r?\n/m, "const PRODUCT_VERSION_LABEL = 'V0.5.4-dev';\n");
const flow = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const {
  captureFeedbackContext,
  FEEDBACK_SCHEMA_VERSION,
  feedbackBundleDownload,
  generateUnifiedFeedbackBundle,
} = flow;

test("backend unavailable uses the same self-contained feedback contract without guessing a task", async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new TypeError("fetch failed for C:\\Users\\private-user\\service"); };
  try {
    const snapshot = await captureFeedbackContext({
      sourceFeature: "runtime_failure",
      stage: "application_runtime",
    });
    assert.equal(snapshot.mode, "offline");
    assert.equal(snapshot.context.task_id, null);
    const generated = await generateUnifiedFeedbackBundle({
      snapshot,
      description: "后端无法连接，预期仍能生成反馈包。",
    });
    assert.equal(generated.mode, "offline");
    assert.equal(generated.payload.feedback_schema_version, FEEDBACK_SCHEMA_VERSION);
    assert.equal(generated.payload.task.task_id, null);
    assert.equal(generated.payload.application.runtime_id, "unavailable");
    assert.equal(generated.payload.privacy_manifest.auto_upload, false);
    assert.ok(generated.payload.related_events.some((event) => event.event === "BACKEND_UNAVAILABLE"));
    assert.doesNotMatch(JSON.stringify(generated.payload), /private-user|C:\\Users/i);
    const download = feedbackBundleDownload(generated);
    assert.match(download.url, /^blob:/);
    assert.match(download.fileName, /FB-[A-Z0-9]+\.json$/);
    assert.ok(download.sizeBytes > 0);
    URL.revokeObjectURL(download.url);
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("explicit page task remains explicit in offline degradation", async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new TypeError("backend unavailable"); };
  try {
    const snapshot = await captureFeedbackContext({
      taskId: "explicit-task-001",
      sourceFeature: "quality_confirm",
      stage: "quality_review",
    });
    const generated = await generateUnifiedFeedbackBundle({
      snapshot,
      description: "质量复核无法继续。",
    });
    assert.equal(generated.payload.task.task_id, "explicit-task-001");
    assert.equal(generated.payload.context.feature_key, "quality_confirm");
    assert.equal(generated.payload.context.result_id, null);
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("all current user feedback entry points reuse the same feedback component", async () => {
  const files = await Promise.all([
    "../../src/AppShell.jsx",
    "../../src/ColorCorrectionPage.jsx",
    "../../src/TaskDetailPage.jsx",
    "../../src/QualityReportPage.jsx",
    "../../src/DashboardPage.jsx",
    "../../src/CompressionPage.jsx",
  ].map(async (relativePath) => readFile(new URL(relativePath, import.meta.url), "utf8")));
  for (const content of files) assert.match(content, /UnifiedFeedback/);
  assert.match(files[0], /sourceFeature="runtime_failure"/);
  assert.match(files[1], /sourceFeature="color_correction"/);
  assert.match(files[2], /sourceFeature="processing_center"/);
  assert.match(files[3], /sourceFeature="quality_confirm"/);
  assert.match(files[4], /sourceFeature="enhancement_1080p"/);
  assert.match(files[5], /sourceFeature="image_compression"/);
  assert.doesNotMatch(files[4], /\/api\/beta\/safe-1080p\/feedback-package|\/api\/v1\/tasks\/.*\/feedback-bundle/);
  assert.doesNotMatch(files[5], /\/api\/image-compression\/test-feedback-package/);
});

test("feedback generation exposes persistent generating success offline and retry states", async () => {
  const component = await readFile(new URL("../../src/UnifiedFeedback.jsx", import.meta.url), "utf8");
  assert.match(component, /useState\("idle"\)/);
  assert.match(component, /setGenerationState\("generating"\)/);
  assert.match(component, /setGenerationState\("success"\)/);
  assert.match(component, /setGenerationState\("failed"\)/);
  assert.match(component, /disabled=\{[^}]*generationState === "generating"\}/);
  assert.match(component, /aria-busy=\{generationState === "generating"\}/);
  assert.match(component, /反馈包已生成/);
  assert.match(component, /后端当前不可达，已使用本地安全模式生成反馈包。/);
  assert.match(component, /反馈包生成失败/);
  assert.match(component, /重新生成/);
  assert.match(component, /data-testid="unified-feedback-generation-status"/);
  assert.match(component, /role=\{generationState === "failed" \? "alert" : "status"\}/);
});
