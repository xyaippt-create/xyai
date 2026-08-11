import { CURRENT_BUILD_ID } from "./buildInfo.js";
import { PRODUCT_VERSION_LABEL } from "./productVersion.js";

export const FEEDBACK_SCHEMA_VERSION = "HDDE-user-feedback-v2";

const FEATURE_NAMES = Object.freeze({
  enhancement_1080p: "1080P标准增强 / 安全增强",
  enhancement_4k: "4K高清画质增强",
  image_compression: "图片压缩",
  color_correction: "单图自动颜色校正",
  batch_processing: "多图批处理 / 任务队列",
  processing_center: "处理中心",
  quality_confirm: "对比质检 / 人工结果确认",
  output_center: "输出中心",
  smart_delivery: "智能交付 / 批量命名",
  local_retouch: "交付标记与局部修整",
  runtime_failure: "正式启动 / 本地运行异常",
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

function offlineContext({ taskId, sourceFeature, stage, connectionError }) {
  const capturedAt = new Date().toISOString();
  const featureKey = FEATURE_NAMES[sourceFeature] ? sourceFeature : "runtime_failure";
  return {
    context_version: "HDDE-feedback-context-v3",
    context_captured_at: capturedAt,
    product_version: PRODUCT_VERSION_LABEL,
    feature_key: featureKey,
    feature: { key: featureKey, name: FEATURE_NAMES[featureKey], coverage_status: "PASS" },
    operation: "feedback",
    purpose: "USER_PROBLEM_FEEDBACK",
    route_family: "unified_feedback",
    stage: sanitizeFeedbackText(stage || "backend_connection", 120),
    task_id: taskId || null,
    batch_id: null,
    result_id: null,
    delivery_id: null,
    status: "backend_unavailable",
    task_status: "unavailable",
    formal_root_status: "unavailable",
    error: {
      code: "BACKEND_UNAVAILABLE",
      stage: "backend_connection",
      error_id: "",
      error_fingerprint: "",
      exception_type: "TypeError",
      code_location: "",
      module: "frontend.feedback",
      trace_id: "",
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

export async function captureFeedbackContext({ taskId = "", sourceFeature = "runtime_failure", stage = "" } = {}) {
  try {
    const response = await fetch("/api/v1/feedback/context-snapshot", {
      method: "POST",
      headers: { "Content-Type": "application/json;charset=UTF-8" },
      body: JSON.stringify({ task_id: taskId || null, source_feature: sourceFeature, stage }),
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
    const context = offlineContext({ taskId, sourceFeature, stage, connectionError: error?.message });
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
        task_reference_available: Boolean(taskId),
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

function offlineBundle(snapshot, description, attachments, connectionError = "") {
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
  return {
    feedback_schema_version: FEEDBACK_SCHEMA_VERSION,
    feedback_version: FEEDBACK_SCHEMA_VERSION,
    feedback_bundle_id: bundleId,
    generated_at: generatedAt,
    created_at: generatedAt,
    context_captured_at: context.context_captured_at,
    application: {
      product: "影界 HDDE",
      version: PRODUCT_VERSION_LABEL,
      build: CURRENT_BUILD_ID || "unavailable",
      runtime_id: context.runtime?.runtime_id || "unavailable",
    },
    task: {
      task_id: context.task_id || null,
      batch_id: context.batch_id || null,
      result_id: context.result_id || null,
      status: context.task_status || "unavailable",
      current_stage: context.stage || "unavailable",
    },
    context,
    related_events: (context.related_events || []).slice(-7),
    trace_summary: context.error?.trace_summary || "",
    attachment_manifest: attachments.map((item) => ({ ...item, included_in_bundle: false })),
    privacy_manifest: {
      contains_original_image: false,
      contains_output_image: false,
      contains_screenshot: false,
      contains_settings: false,
      contains_full_absolute_paths: false,
      contains_other_tasks: false,
      redacted: true,
      attachments_require_user_action: true,
      auto_upload: false,
    },
  };
}

export async function generateUnifiedFeedbackBundle({ snapshot, description, files = [] }) {
  const manifest = attachmentManifest(files);
  if (snapshot.mode === "backend") {
    try {
      const response = await fetch("/api/v1/feedback/bundle", {
        method: "POST",
        headers: { "Content-Type": "application/json;charset=UTF-8" },
        body: JSON.stringify({
          snapshot_id: snapshot.snapshotId,
          description: sanitizeFeedbackText(description),
          attachment_manifest: manifest,
        }),
      });
      const data = await responseJson(response);
      return { mode: "backend", payload: data.bundle_payload, metadata: data };
    } catch (error) {
      return {
        mode: "offline",
        payload: offlineBundle(snapshot, description, manifest, error?.message || "backend_unavailable"),
        connectionError: sanitizeFeedbackText(error?.message || "backend_unavailable", 300),
      };
    }
  }
  return {
    mode: "offline",
    payload: offlineBundle(snapshot, description, manifest, snapshot.connectionError),
    connectionError: snapshot.connectionError,
  };
}

export function feedbackBundleDownload(result) {
  const payload = result?.payload || {};
  const bundleId = payload.feedback_bundle_id || identifier("FB");
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=UTF-8" });
  return {
    url: URL.createObjectURL(blob),
    fileName: `影界HDDE_问题反馈_${bundleId}.json`,
    sizeBytes: blob.size,
  };
}
