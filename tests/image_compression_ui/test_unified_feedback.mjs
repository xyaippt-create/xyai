import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const sourceUrl = new URL("../../src/feedbackFlow.js", import.meta.url);
const zipSource = await readFile(new URL("../../src/feedbackZip.js", import.meta.url), "utf8");
const zipModuleUrl = `data:text/javascript;base64,${Buffer.from(zipSource).toString("base64")}`;
const source = (await readFile(sourceUrl, "utf8"))
  .replace(/^import \{ CURRENT_BUILD_ID \} from .*;\r?\n/m, "const CURRENT_BUILD_ID = 'V0.5.4-dev+test-build';\n")
  .replace(/^import \{ PRODUCT_VERSION_LABEL \} from .*;\r?\n/m, "const PRODUCT_VERSION_LABEL = 'V0.5.4-dev';\n")
  .replace(/^import \{ createValidatedFeedbackZip \} from .*;\r?\n/m, `import { createValidatedFeedbackZip } from "${zipModuleUrl}";\n`);
const flow = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const feedbackTargets = await import(new URL("../../src/feedbackTarget.js", import.meta.url));
const {
  captureFeedbackContext,
  FEEDBACK_SCHEMA_VERSION,
  feedbackBundleDownload,
  generateUnifiedFeedbackBundle,
} = flow;

test("feedback target is generic across all public modules and a new operation clears stale facts", () => {
  const featureKeys = [
    "enhancement_1080p", "enhancement_4k", "image_compression", "color_correction",
    "batch_processing", "processing_center", "quality_confirm", "output_center",
    "smart_delivery", "local_retouch", "runtime_failure", "system_settings",
  ];
  for (const [index, featureKey] of featureKeys.entries()) {
    const target = feedbackTargets.setCurrentFeedbackTarget({
      feature_key: featureKey,
      operation_id: `OP-GENERIC-${index}`,
      trace_id: `TRACE-GENERIC-${index}`,
    });
    assert.equal(target.feature_key, featureKey);
    assert.equal(feedbackTargets.getCurrentFeedbackTarget().trace_id, `TRACE-GENERIC-${index}`);
  }
  feedbackTargets.beginFeedbackOperation();
  assert.equal(feedbackTargets.getCurrentFeedbackTarget(), null);
});

test("explicit feedback target is sent unchanged instead of the route runtime fallback", async () => {
  const previousFetch = globalThis.fetch;
  let requestBody = null;
  const target = {
    feature_key: "enhancement_1080p",
    operation_id: "OP-EXPLICIT-001",
    trace_id: "TRACE-EXPLICIT-001",
    task_id: "task_explicit_001",
    route: "fidelity",
    stage: "input_validation",
  };
  globalThis.fetch = async (_url, options) => {
    requestBody = JSON.parse(options.body);
    return {
      ok: true,
      status: 200,
      json: async () => ({ data: { snapshot_id: "FCS-1", context_captured_at: "now", context: {}, context_preview: {} } }),
    };
  };
  try {
    await captureFeedbackContext({
      sourceFeature: "processing_center",
      stage: "user_feedback_entry",
      route: "/processing",
      feedbackTarget: target,
    });
    assert.deepEqual(requestBody.feedback_target, target);
  } finally {
    globalThis.fetch = previousFetch;
  }
});

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
    assert.equal(snapshot.context.feedback_trace_contract.version, "HDDE-feedback-trace-contract-v1");
    assert.equal(snapshot.context.feedback_trace_contract.fact_policy, "existing_facts_only");
    assert.equal(snapshot.context.common_context.operation_id, null);
    assert.equal(snapshot.context.common_context.trace_id, null);
    const generated = await generateUnifiedFeedbackBundle({
      snapshot,
      description: "后端无法连接，预期仍能生成反馈包。",
    });
    assert.equal(generated.mode, "offline");
    assert.equal(generated.payload.feedback_identity.schema_version, FEEDBACK_SCHEMA_VERSION);
    assert.equal(generated.payload.common_context.task_id, null);
    assert.equal(generated.payload.application_runtime.runtime_id, "unavailable");
    assert.equal(generated.payload.privacy_summary.auto_upload, false);
    assert.equal(generated.payload.package_completeness.related_log, "NOT_FOUND");
    assert.equal(generated.metadata.package_self_check.ZIP_VALIDATION, "PASS");
    assert.doesNotMatch(JSON.stringify(generated.payload), /private-user|C:\\Users/i);
    const download = await feedbackBundleDownload(generated);
    assert.match(download.url, /^blob:/);
    assert.match(download.fileName, /^影界HDDE_问题反馈_FB-[A-Z0-9-]+\.zip$/);
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
    assert.equal(generated.payload.common_context.task_id, "explicit-task-001");
    assert.equal(generated.payload.common_context.feature_key, "quality_confirm");
    assert.equal(generated.payload.common_context.result_id, null);
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
  assert.match(files[0], /UnifiedFeedback/);
  for (const content of files.slice(1)) assert.doesNotMatch(content, /UnifiedFeedback/);
  assert.match(files[0], /FEEDBACK_FEATURE_BY_ROUTE/);
  assert.match(files[0], /settings: "system_settings"/);
  assert.match(files[0], /"smart-delivery": "smart_delivery"/);
  assert.match(files[0], /"color-correction": "color_correction"/);
  assert.match(files[0], /"task-detail": "processing_center"/);
  assert.match(files[0], /"task-report": "quality_confirm"/);
  assert.match(files[0], /processing: "processing_center"/);
  assert.match(files[0], /compression: "image_compression"/);
  assert.doesNotMatch(files[4], /\/api\/beta\/safe-1080p\/feedback-package|\/api\/v1\/tasks\/.*\/feedback-bundle/);
  assert.doesNotMatch(files[5], /\/api\/image-compression\/test-feedback-package/);
});

test("feedback generation exposes persistent generating success offline and retry states", async () => {
  const component = await readFile(new URL("../../src/UnifiedFeedback.jsx", import.meta.url), "utf8");
  assert.match(component, /useSyncExternalStore/);
  assert.match(component, /resolveFeedbackTarget\(explicitTarget, currentFeedbackTarget, sourceFeature\)/);
  assert.match(component, /useState\("idle"\)/);
  assert.match(component, /setGenerationState\("generating"\)/);
  assert.match(component, /setGenerationState\("success"\)/);
  assert.match(component, /setGenerationState\("failed"\)/);
  assert.match(component, /disabled=\{[\s\S]{0,300}generationState === "generating"/);
  assert.match(component, /aria-busy=\{generationState === "generating"\}/);
  assert.match(component, /反馈包已生成/);
  assert.match(component, /后端当前不可达，已使用本地安全模式生成反馈包。/);
  assert.match(component, /反馈包生成失败/);
  assert.match(component, /重新生成/);
  assert.match(component, /data-testid="unified-feedback-generation-status"/);
  assert.match(component, /role=\{generationState === "failed" \? "alert" : "status"\}/);
});

test("T59 evaluation and independent image consent use the existing feedback request", async () => {
  const previousFetch = globalThis.fetch;
  let requestBody = null;
  globalThis.fetch = async (_url, options) => {
    requestBody = JSON.parse(options.body);
    return {
      ok: true,
      status: 200,
      json: async () => ({
        data: {
          bundle_payload: { feedback_identity: { feedback_bundle_id: "FB-T59" } },
          package_self_check: { ZIP_VALIDATION: "PASS" },
          download_url: "/api/v1/feedback/bundle-file/test.zip",
        },
      }),
    };
  };
  try {
    const generated = await generateUnifiedFeedbackBundle({
      snapshot: { mode: "backend", snapshotId: "FCS-T59" },
      description: "边缘出现异常。",
      evaluation: { decision: "NEEDS_ADJUSTMENT", reasons: ["EDGE_ARTIFACT"] },
      evidenceConsent: { include_source_image: false, include_result_image: true },
    });
    assert.equal(generated.mode, "backend");
    assert.deepEqual(requestBody.evaluation, {
      decision: "NEEDS_ADJUSTMENT",
      reasons: ["EDGE_ARTIFACT"],
    });
    assert.deepEqual(requestBody.evidence_consent, {
      include_source_image: false,
      include_result_image: true,
    });
  } finally {
    globalThis.fetch = previousFetch;
  }

  const component = await readFile(new URL("../../src/UnifiedFeedback.jsx", import.meta.url), "utf8");
  assert.match(component, /这次处理结果可以直接使用吗？/);
  assert.match(component, /可以直接使用/);
  assert.match(component, /需要继续调整/);
  assert.match(component, /不能使用/);
  assert.match(component, /decision !== "ACCEPTED"/);
  assert.match(component, /data-testid="unified-feedback-reason"/);
  assert.match(component, /data-testid="unified-feedback-include-result"/);
  assert.match(component, /data-testid="unified-feedback-include-source"/);
  assert.match(component, /useState\(false\)/);
});
