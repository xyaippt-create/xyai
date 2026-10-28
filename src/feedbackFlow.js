import { CURRENT_BUILD_ID } from "./buildInfo.js";
import { PRODUCT_VERSION_LABEL } from "./productVersion.js";
import { createValidatedFeedbackZip } from "./feedbackZip.js";

export const FEEDBACK_SCHEMA_VERSION = "HDDE-user-feedback-v3";
export const FEEDBACK_DECISIONS = Object.freeze(["ACCEPTED", "NEEDS_ADJUSTMENT", "UNUSABLE"]);
export const FEEDBACK_REASONS = Object.freeze([
  "EFFECT_TOO_WEAK",
  "OVER_PROCESSED",
  "COLOR_ABNORMAL",
  "QUALITY_DEGRADED",
  "LOCAL_DAMAGE",
  "TEXT_OR_LOGO_DAMAGE",
  "EDGE_ARTIFACT",
  "RESULT_NOT_AS_EXPECTED",
  "WORKFLOW_PROBLEM",
  "OTHER",
]);

const BASE_FEATURE_NAMES = Object.freeze({
  enhancement_1080p: "1080P画质",
  enhancement_4k: "4K画质增强",
  image_compression: "图片压缩",
  color_correction: "单图自动颜色校正",
  batch_processing: "多图批处理 / 任务队列",
  processing_center: "处理中心",
  quality_confirm: "对比质检 / 人工结果确认",
  output_center: "输出中心",
  smart_delivery: "文件交付",
  local_retouch: "瑕疵修复",
  runtime_failure: "正式启动 / 本地运行异常",
});

const FEATURE_NAMES = Object.freeze({
  ...BASE_FEATURE_NAMES,
  system_settings: "\u7cfb\u7edf\u8bbe\u7f6e",
});

const FEATURE_MODULES = Object.freeze({
  enhancement_1080p: "hdde.enhancement.1080p",
  enhancement_4k: "hdde.enhancement.4k",
  image_compression: "hdde.image.compression",
  color_correction: "hdde.color.correction",
  batch_processing: "hdde.processing.batch",
  processing_center: "hdde.processing.center",
  quality_confirm: "hdde.quality.confirm",
  output_center: "hdde.output.center",
  smart_delivery: "hdde.smart.delivery",
  local_retouch: "hdde.local.retouch",
  system_settings: "hdde.system.settings",
  runtime_failure: "hdde.runtime.failure",
});

function identifier(prefix) {
  const value = typeof globalThis.crypto?.randomUUID === "function"
    ? globalThis.crypto.randomUUID().replaceAll("-", "")
    : `${Date.now()}${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${value.slice(0, 20).toUpperCase()}`;
}

export function sanitizeFeedbackText(value, limit = 1000) {
  return String(value || "")
    .replace(/\b[A-Za-z]:[\\/][^\s"'<>]+/g, "<redacted_path>")
    .replace(/\/(?:Users|home)\/[^\s"'<>]+/gi, "<redacted_path>")
    .replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, "<redacted_email>")
    .replace(/\b(api[_-]?key|token|authorization|password|secret)\s*[:=]\s*[^\s,;}]+/gi, "$1=<redacted>")
    .slice(0, limit);
}

export function normalizeFeedbackEvaluation(value) {
  if (!value || !value.decision) return { decision: null, reasons: [] };
  const decision = String(value.decision).trim().toUpperCase();
  const reasons = Array.from(new Set(Array.isArray(value.reasons) ? value.reasons : []))
    .map((item) => String(item || "").trim().toUpperCase())
    .filter(Boolean);
  if (!FEEDBACK_DECISIONS.includes(decision)) throw new Error("结果评价无效。");
  if (reasons.some((reason) => !FEEDBACK_REASONS.includes(reason))) throw new Error("问题原因无效。");
  if (decision === "ACCEPTED" && reasons.length) throw new Error("可以直接使用的结果不应包含问题原因。");
  if (decision !== "ACCEPTED" && !reasons.length) throw new Error("请选择一个问题原因。");
  return { decision, reasons };
}

export function normalizeEvidenceConsent(value) {
  return {
    include_source_image: value?.include_source_image === true,
    include_result_image: value?.include_result_image === true,
  };
}

function offlineContext({ taskId, sourceFeature, stage, route, feedbackTarget, connectionError }) {
  const capturedAt = new Date().toISOString();
  const target = feedbackTarget && typeof feedbackTarget === "object" ? feedbackTarget : {};
  const featureKey = FEATURE_NAMES[target.feature_key || sourceFeature] ? (target.feature_key || sourceFeature) : "runtime_failure";
  const targetTaskId = target.task_id || taskId || null;
  const targetErrorCode = target.error_code || "";
  const commonContext = {
    feature_key: featureKey,
    module_id: target.module_id || FEATURE_MODULES[featureKey],
    operation_id: target.operation_id || null,
    trace_id: target.trace_id || null,
    task_id: targetTaskId,
    result_id: target.result_id || null,
    delivery_id: target.delivery_id || null,
    batch_id: target.batch_id || null,
    route: sanitizeFeedbackText(target.route || route || globalThis.location?.pathname || "", 160) || null,
    stage: sanitizeFeedbackText(target.stage || stage || "backend_connection", 120),
    status: "backend_unavailable",
    task_status: null,
    result_status: null,
    output_created: null,
    second_edit_used: null,
    context_binding: targetTaskId || target.result_id ? "LINKED" : "UNAVAILABLE",
    started_at: null,
    completed_at: null,
    error_id: target.error_id || null,
    error_code: targetErrorCode || "BACKEND_UNAVAILABLE",
    error_fingerprint: target.error_fingerprint || null,
    runtime_id: null,
    build_id: CURRENT_BUILD_ID || null,
  };
  const moduleContext = featureKey === "system_settings"
    ? { settings_status: "unavailable", formal_root_status: "unavailable" }
    : featureKey === "runtime_failure"
      ? { runtime_status: "unavailable", backend_health: "unavailable", error_code: "BACKEND_UNAVAILABLE" }
      : {};
  return {
    context_version: "HDDE-feedback-context-v3",
    feedback_trace_contract: {
      version: "HDDE-feedback-trace-contract-v1",
      fact_policy: "existing_facts_only",
      common_context: commonContext,
      module_context: moduleContext,
      links: {
        operation: commonContext.operation_id ? "LINKED" : "NOT_CREATED",
        trace: commonContext.trace_id ? "LINKED" : "NOT_CREATED",
        task: targetTaskId ? "LINKED" : "NOT_CREATED",
        result: "NOT_CREATED",
        delivery: "NOT_CREATED",
        error: commonContext.error_id || targetErrorCode ? "LINKED" : "NOT_CREATED",
        log: "NOT_CREATED",
        event: "NOT_CREATED",
      },
    },
    common_context: commonContext,
    module_context: moduleContext,
    context_captured_at: capturedAt,
    product_version: PRODUCT_VERSION_LABEL,
    feature_key: featureKey,
    module_id: commonContext.module_id,
    operation_id: commonContext.operation_id,
    trace_id: commonContext.trace_id,
    feature: { key: featureKey, name: FEATURE_NAMES[featureKey], coverage_status: "PASS" },
    operation: "feedback",
    purpose: "USER_PROBLEM_FEEDBACK",
    route_family: "unified_feedback",
    stage: commonContext.stage,
    task_id: targetTaskId,
    batch_id: commonContext.batch_id,
    result_id: commonContext.result_id,
    delivery_id: commonContext.delivery_id,
    status: "backend_unavailable",
    task_status: "unavailable",
    formal_root_status: "unavailable",
    error: {
      code: commonContext.error_code,
      stage: commonContext.stage,
      error_id: commonContext.error_id || "",
      error_fingerprint: commonContext.error_fingerprint || "",
      exception_type: "TypeError",
      code_location: "",
      module: "frontend.feedback",
      trace_id: commonContext.trace_id || "",
      trace_summary: "",
      summary: sanitizeFeedbackText(connectionError || "backend_unavailable", 300),
    },
    references: { source: "", result: "" },
    safe_input_metadata: {},
    related_events: [{
      timestamp: capturedAt,
      event: "BACKEND_UNAVAILABLE",
      feature: featureKey,
      stage: "backend_connection",
      result: "failed",
      impact: "backend_diagnostics_unavailable",
    }],
    review_status: "not_available",
    runtime: {
      app_version: PRODUCT_VERSION_LABEL,
      product_version: PRODUCT_VERSION_LABEL,
      build_id: CURRENT_BUILD_ID || "unavailable",
      runtime_id: "unavailable",
      runtime_status: "unavailable",
      backend_health: "unavailable",
      backend_connection_status: "unavailable",
      frontend_connection_status: "available",
      settings_status: "unavailable",
      formal_root_status: "unavailable",
      runtime_log_reference: "",
      runtime_log_available: false,
    },
    user_description: "",
  };
}

async function responseJson(response) {
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`反馈服务返回了无法解析的响应（HTTP ${response.status}）。`);
  }
  if (!response.ok || payload?.success === false) {
    const detail = payload?.detail;
    throw new Error((typeof detail === "object" ? detail?.message : detail) || payload?.message || `反馈服务不可用（HTTP ${response.status}）。`);
  }
  return payload?.data || payload;
}

export async function captureFeedbackContext({ taskId = "", sourceFeature = "runtime_failure", stage = "", route = "", feedbackTarget = null } = {}) {
  try {
    const response = await fetch("/api/v1/feedback/context-snapshot", {
      method: "POST",
      headers: { "Content-Type": "application/json;charset=UTF-8" },
      body: JSON.stringify({
        ...(taskId ? { task_id: taskId } : {}),
        source_feature: sourceFeature,
        stage,
        route: route || globalThis.location?.pathname || "",
        ...(feedbackTarget ? { feedback_target: feedbackTarget } : {}),
      }),
    });
    const data = await responseJson(response);
    return {
      mode: "backend",
      snapshotId: data.snapshot_id,
      capturedAt: data.context_captured_at,
      context: data.context,
      preview: data.context_preview,
    };
  } catch (error) {
    const context = offlineContext({ taskId, sourceFeature, stage, route, feedbackTarget, connectionError: error?.message });
    return {
      mode: "offline",
      snapshotId: identifier("FCS-OFFLINE"),
      capturedAt: context.context_captured_at,
      context,
      preview: {
        feature_name: context.feature.name,
        stage: context.stage,
        status: context.status,
        app_version: PRODUCT_VERSION_LABEL,
        build_id: CURRENT_BUILD_ID || "unavailable",
        runtime_id: "unavailable",
        error_id: "unavailable",
        backend_health: "unavailable",
        task_reference_available: Boolean(feedbackTarget?.task_id || taskId),
        result_reference_available: false,
      },
      connectionError: sanitizeFeedbackText(error?.message || "backend_unavailable", 300),
    };
  }
}

export function attachmentManifest(files) {
  return Array.from(files || []).slice(0, 10).map((file) => ({
    extension: /\.[a-z0-9]{1,10}$/i.exec(file.name || "")?.[0]?.toLowerCase() || "",
    size_bytes: Number.isFinite(file.size) ? file.size : 0,
    selected_by_user: true,
  }));
}

function localPrivacyReview(payloads) {
  const combined = payloads.join("\n");
  const absolutePath = /\b[A-Za-z]:[\\/]|\/(?:Users|home|var|tmp|etc)\//i.test(combined);
  const sensitive = /\b(?:api[_-]?key|token|authorization|password|secret)\s*[:=]\s*(?!<redacted>)[^\s,;}]+/i.test(combined);
  if (absolutePath || sensitive) throw new Error("本地反馈包隐私校验未通过。");
  return {
    redacted: true,
    contains_original_image: false,
    contains_output_image: false,
    contains_screenshot: false,
    contains_absolute_paths: false,
    contains_other_tasks: false,
    contains_sensitive_credentials: false,
    selected_attachments: [],
    attachments_included: false,
    auto_upload: false,
    review_status: "PASS",
  };
}

function offlineImageEvidence(consent) {
  const item = (requested) => ({
    requested_by_user: requested,
    included: false,
    status: requested ? "CONTEXT_UNAVAILABLE" : "NOT_AUTHORIZED",
    failure_code: requested ? "EVIDENCE_ATTACHMENT_FAILED" : null,
    archive_path: null,
    extension: null,
    size_bytes: 0,
    sha256: null,
  });
  const sourceImage = item(consent.include_source_image);
  const resultImage = item(consent.include_result_image);
  const requested = sourceImage.requested_by_user || resultImage.requested_by_user;
  return {
    status: requested ? "PARTIAL" : "NOT_REQUESTED",
    failure_code: requested ? "EVIDENCE_ATTACHMENT_FAILED" : null,
    source_image: sourceImage,
    result_image: resultImage,
  };
}

async function offlineBundle(snapshot, description, attachments, evaluation, evidenceConsent, connectionError = "") {
  const generatedAt = new Date().toISOString();
  const context = JSON.parse(JSON.stringify(snapshot.context));
  context.user_description = sanitizeFeedbackText(description);
  context.runtime = { ...context.runtime, frontend_connection_status: "available" };
  if (connectionError) {
    context.runtime.backend_connection_status = "unavailable";
    context.runtime.backend_health = "unavailable";
    context.related_events = [...(context.related_events || []).slice(-6), {
      timestamp: generatedAt,
      event: "BACKEND_UNAVAILABLE",
      feature: context.feature_key,
      stage: "feedback_bundle_generation",
      result: "failed",
      impact: "server_bundle_generation_unavailable",
    }];
  }
  const bundleId = identifier("FB");
  const commonContext = context.feedback_trace_contract?.common_context || context.common_context || {};
  const links = context.feedback_trace_contract?.links || {};
  const linkStatus = (name) => {
    const value = links[name];
    if (value === "LINKED") return "PASS";
    if (value === "NOT_APPLICABLE") return "NOT_APPLICABLE";
    return value ? "NOT_FOUND" : "NOT_FOUND";
  };
  const selectedAttachments = attachments.map((item) => ({ ...item, included_in_bundle: false }));
  const imageEvidence = offlineImageEvidence(evidenceConsent);
  const timelineEvents = (context.related_events || []).map((event) => ({
    timestamp: event.timestamp,
    event_type: event.event,
    stage: event.stage || null,
    status: event.result || null,
    feature_key: commonContext.feature_key || context.feature_key || null,
    operation_id: commonContext.operation_id || null,
    trace_id: commonContext.trace_id || null,
    task_id: commonContext.task_id || null,
    result_id: commonContext.result_id || null,
    delivery_id: commonContext.delivery_id || null,
    error_id: commonContext.error_id || null,
    summary: sanitizeFeedbackText(event.impact || "", 300) || null,
    source: "existing_frontend_event",
  })).filter((event) => event.timestamp && event.event_type);
  timelineEvents.push({
    timestamp: generatedAt,
    event_type: "FEEDBACK_BUNDLE_GENERATED",
    stage: "feedback_bundle_generation",
    status: "success",
    feature_key: commonContext.feature_key || context.feature_key || null,
    operation_id: commonContext.operation_id || null,
    trace_id: commonContext.trace_id || null,
    task_id: commonContext.task_id || null,
    result_id: commonContext.result_id || null,
    delivery_id: commonContext.delivery_id || null,
    error_id: commonContext.error_id || null,
    summary: "local_safe_mode",
    source: "feedback_generator",
  });
  timelineEvents.sort((left, right) => String(left.timestamp).localeCompare(String(right.timestamp)));
  const timeline = { timeline_status: "PARTIAL", event_count: timelineEvents.length, events: timelineEvents };
  const feedback = {
    feedback_identity: {
      schema_version: FEEDBACK_SCHEMA_VERSION,
      feedback_bundle_id: bundleId,
      generated_at: generatedAt,
      context_captured_at: context.context_captured_at || null,
    },
    application_runtime: {
      product: "影界 HDDE",
      product_version: PRODUCT_VERSION_LABEL,
      build_id: commonContext.build_id || CURRENT_BUILD_ID || "unavailable",
      runtime_id: commonContext.runtime_id || "unavailable",
      runtime_status: context.runtime?.runtime_status || "unavailable",
      backend_health: "unavailable",
      settings_status: context.runtime?.settings_status || "unavailable",
      formal_root_status: context.runtime?.formal_root_status || "unavailable",
    },
    user_description: context.user_description,
    evaluation,
    common_context: commonContext,
    module_context: context.feedback_trace_contract?.module_context || context.module_context || {},
    safe_input_metadata: context.safe_input_metadata || {},
    output_validation: { status: "NOT_APPLICABLE", exists: false, decodable: false, width: null, height: null, format: "" },
    image_evidence: imageEvidence,
    package_completeness: {
      trace_context: linkStatus("trace"),
      task_context: linkStatus("task"),
      result_context: linkStatus("result"),
      delivery_context: linkStatus("delivery"),
      related_log: "NOT_FOUND",
      timeline: "PARTIAL",
    },
  };
  const relatedLog = "RELATED_LOG_STATUS=NOT_FOUND\nP1_MATCH_COUNT=0\nP2_MATCH_COUNT=0\nTIME_WINDOW_USED=NO\nDETAIL=Backend runtime log was unavailable to local safe mode.\n";
  const privacy = localPrivacyReview([
    JSON.stringify(feedback), relatedLog, JSON.stringify(timeline), JSON.stringify(selectedAttachments),
  ]);
  feedback.privacy_summary = { ...privacy, selected_attachments: selectedAttachments };
  feedback.privacy_summary.image_consent_enforced = true;
  feedback.privacy_summary.image_evidence_included = false;
  const manifestBase = {
    package_schema_version: FEEDBACK_SCHEMA_VERSION,
    feedback_bundle_id: bundleId,
    generated_at: generatedAt,
    trace_id: commonContext.trace_id || null,
    feature_key: commonContext.feature_key || context.feature_key || null,
    completeness: { feedback_json: "PASS", related_log: "NOT_FOUND", timeline: "PARTIAL" },
    evidence_files: {},
    image_evidence: imageEvidence,
    privacy: {
      redacted: true,
      contains_original_image: false,
      contains_output_image: false,
      contains_screenshot: false,
      contains_absolute_paths: false,
      contains_other_tasks: false,
      contains_sensitive_credentials: false,
    },
  };
  const zip = await createValidatedFeedbackZip({ feedback, relatedLog, timeline, manifestBase, generatedAt });
  return {
    payload: feedback,
    zipBlob: zip.blob,
    metadata: {
      feedback_bundle_status: "PASS",
      feedback_bundle_name: `影界HDDE_问题反馈_${bundleId}.zip`,
      feedback_bundle_size: zip.blob.size,
      feedback_bundle_id: bundleId,
      feedback_schema_version: FEEDBACK_SCHEMA_VERSION,
      package_self_check: { ZIP_VALIDATION: zip.validation, MANIFEST_SHA: "PASS", PRIVACY_REVIEW: "PASS" },
      atomic_package_write: "PASS",
    },
  };
}

export async function generateUnifiedFeedbackBundle({
  snapshot,
  description,
  files = [],
  evaluation = null,
  evidenceConsent = null,
}) {
  const manifest = attachmentManifest(files);
  const normalizedEvaluation = normalizeFeedbackEvaluation(evaluation);
  const normalizedEvidenceConsent = normalizeEvidenceConsent(evidenceConsent);
  if (snapshot.mode === "backend") {
    try {
      const response = await fetch("/api/v1/feedback/bundle", {
        method: "POST",
        headers: { "Content-Type": "application/json;charset=UTF-8" },
        body: JSON.stringify({
          snapshot_id: snapshot.snapshotId,
          description: sanitizeFeedbackText(description),
          attachment_manifest: manifest,
          evaluation: normalizedEvaluation,
          evidence_consent: normalizedEvidenceConsent,
        }),
      });
      const data = await responseJson(response);
      return { mode: "backend", payload: data.bundle_payload, metadata: data };
    } catch (error) {
      return {
        mode: "offline",
        ...(await offlineBundle(
          snapshot,
          description,
          manifest,
          normalizedEvaluation,
          normalizedEvidenceConsent,
          error?.message || "backend_unavailable",
        )),
        connectionError: sanitizeFeedbackText(error?.message || "backend_unavailable", 300),
      };
    }
  }
  return {
    mode: "offline",
    ...(await offlineBundle(
      snapshot,
      description,
      manifest,
      normalizedEvaluation,
      normalizedEvidenceConsent,
      snapshot.connectionError,
    )),
    connectionError: snapshot.connectionError,
  };
}

export async function feedbackBundleDownload(result) {
  if (result?.mode === "backend") {
    if (result.metadata?.package_self_check?.ZIP_VALIDATION !== "PASS" || !result.metadata?.download_url) {
      throw new Error("后端反馈包未通过完整性校验。");
    }
    const response = await fetch(result.metadata.download_url, { cache: "no-store" });
    if (!response.ok) throw new Error(`反馈包下载失败（HTTP ${response.status}）。`);
    const blob = await response.blob();
    if (!blob.size) throw new Error("反馈包下载内容为空。");
    return { url: URL.createObjectURL(blob), fileName: result.metadata.feedback_bundle_name, sizeBytes: blob.size };
  }
  const blob = result?.zipBlob;
  if (!(blob instanceof Blob) || !blob.size) throw new Error("本地反馈包数据不完整。");
  return {
    url: URL.createObjectURL(blob),
    fileName: result.metadata.feedback_bundle_name,
    sizeBytes: blob.size,
  };
}
