const FEEDBACK_TARGET_FIELDS = Object.freeze([
  "feature_key",
  "module_id",
  "operation_id",
  "trace_id",
  "task_id",
  "result_id",
  "delivery_id",
  "batch_id",
  "route",
  "stage",
  "status",
  "error_id",
  "error_code",
  "error_fingerprint",
]);

const STRONG_REFERENCE_FIELDS = Object.freeze([
  "operation_id",
  "trace_id",
  "task_id",
  "result_id",
  "delivery_id",
  "batch_id",
  "error_id",
]);

let currentFeedbackTarget = null;
const listeners = new Set();

function cleanReference(value, limit = 180) {
  const text = typeof value === "string" || typeof value === "number" ? String(value).trim() : "";
  return text ? text.slice(0, limit) : "";
}

export function normalizeFeedbackTarget(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const featureKey = cleanReference(value.feature_key, 80);
  if (!featureKey || !/^[a-z0-9_]+$/.test(featureKey)) return null;
  const normalized = {};
  for (const field of FEEDBACK_TARGET_FIELDS) {
    const clean = cleanReference(value[field], field === "route" ? 200 : 180);
    if (clean) normalized[field] = clean;
  }
  if (!STRONG_REFERENCE_FIELDS.some((field) => normalized[field])) return null;
  return Object.freeze(normalized);
}

export function extractFeedbackTarget(payload) {
  return normalizeFeedbackTarget(payload?.feedback_target || payload?.detail?.feedback_target);
}

export function resolveFeedbackTarget(explicitTarget, currentTarget, sourceFeature) {
  const target = explicitTarget || currentTarget;
  if (sourceFeature === "color_correction" && target?.feature_key !== sourceFeature) return null;
  return target;
}

function emitTargetChange() {
  for (const listener of listeners) listener();
}

export function beginFeedbackOperation() {
  if (currentFeedbackTarget === null) return;
  currentFeedbackTarget = null;
  emitTargetChange();
}

export function setCurrentFeedbackTarget(value) {
  const next = normalizeFeedbackTarget(value);
  if (!next) return null;
  currentFeedbackTarget = next;
  emitTargetChange();
  return next;
}

export function getCurrentFeedbackTarget() {
  return currentFeedbackTarget;
}

export function subscribeFeedbackTarget(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
