const API_BASE = import.meta.env?.VITE_API_BASE_URL || "";
const DELIVERY_STORAGE_PREFIX = "hdde.batch-delivery.v1:";
const DELIVERY_REQUEST_PATTERN = /^delivery_request_[A-Za-z0-9_-]{16,96}$/;

export const BATCH_DELIVERY_STATUS = Object.freeze({
  COMPLETED: "COMPLETED",
  FAILED_DEFINITE: "FAILED_DEFINITE",
  UNKNOWN: "UNKNOWN",
});

const ELIGIBILITY_INVALIDATING_CODES = new Set([
  "RESULT_IDENTITY_MISMATCH",
  "RESULT_NOT_DELIVERABLE",
  "RESULT_ARTIFACT_MISSING",
  "UNIFIED_RESULT_NOT_FOUND",
  "OUTPUT_ITEM_NOT_FOUND",
  "UNIFIED_RESULT_REQUIRED",
  "COLOR_RESULT_NOT_ACCEPTED",
  "DELIVERY_SHA_MISMATCH",
]);

function browserStorage() {
  try {
    return globalThis?.localStorage || null;
  } catch {
    return null;
  }
}

function deliveryStorageKey(batchId) {
  return `${DELIVERY_STORAGE_PREFIX}${String(batchId || "").trim()}`;
}

export function createDeliveryRequestId() {
  const uuid = globalThis?.crypto?.randomUUID?.();
  if (uuid) return `delivery_request_${uuid.replaceAll("-", "")}`;
  const bytes = new Uint8Array(16);
  globalThis?.crypto?.getRandomValues?.(bytes);
  const value = Array.from(bytes, (item) => item.toString(16).padStart(2, "0")).join("");
  return `delivery_request_${value || `${Date.now()}_${String(Math.random()).slice(2)}`}`;
}

function normalizePersistedState(resultId, raw) {
  const status = String(raw?.status || "").toUpperCase();
  const idempotencyKey = String(raw?.idempotencyKey || "");
  if (!resultId || !Object.values(BATCH_DELIVERY_STATUS).includes(status) || !DELIVERY_REQUEST_PATTERN.test(idempotencyKey)) return null;
  return {
    resultId,
    status,
    idempotencyKey,
    deliveryId: String(raw?.deliveryId || ""),
    outputSha256: String(raw?.outputSha256 || "").toLowerCase(),
    code: String(raw?.code || ""),
    reason: String(raw?.reason || ""),
    invalidatesEligibility: raw?.invalidatesEligibility === true,
  };
}

export function loadBatchDeliveryStates(batchId, { storage = browserStorage() } = {}) {
  if (!batchId || !storage) return {};
  try {
    const payload = JSON.parse(storage.getItem(deliveryStorageKey(batchId)) || "{}");
    const restored = {};
    for (const [resultId, raw] of Object.entries(payload?.items || {})) {
      const state = normalizePersistedState(String(resultId), raw);
      if (state) restored[resultId] = state;
    }
    return restored;
  } catch {
    return {};
  }
}

export function saveBatchDeliveryStates(batchId, states, { storage = browserStorage() } = {}) {
  if (!batchId || !storage) return;
  const items = {};
  for (const [resultId, raw] of Object.entries(states || {})) {
    const state = normalizePersistedState(String(resultId), raw);
    if (state) items[resultId] = state;
  }
  try {
    storage.setItem(deliveryStorageKey(batchId), JSON.stringify({ version: 1, items }));
  } catch {
    // Delivery safety remains server-authoritative; unavailable browser storage only disables refresh recovery.
  }
}

export function invalidatesBatchDeliveryEligibility(code) {
  return ELIGIBILITY_INVALIDATING_CODES.has(String(code || "").toUpperCase());
}

function apiUrl(path) {
  if (!path) return "";
  if (/^https?:\/\//i.test(path)) return path;
  return `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function requestBatchDeliveryJson(path, options = {}) {
  const response = await fetch(apiUrl(path), options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.success === false || !payload?.data) {
    const detail = payload?.detail;
    throw Object.assign(
      new Error(detail?.message || payload?.message || "批量交付暂时无法完成该操作。"),
      { status: response.status, code: detail?.code || "", payload },
    );
  }
  return payload;
}

export function resolveBatchMediaUrl(path) {
  return apiUrl(path);
}

export async function loadBatchOutputItems(resultIds, { request = requestBatchDeliveryJson } = {}) {
  const requested = new Set(Array.from(resultIds || []).map(String).filter(Boolean));
  if (!requested.size) return {};
  const payload = await request("/api/output-center/items");
  const matched = {};
  for (const item of payload.data?.items || []) {
    const resultId = String(item?.result_id || "");
    if (!requested.has(resultId) || matched[resultId]) continue;
    matched[resultId] = item;
  }
  return matched;
}

export function blocksBatchDeliverySelection(deliveryState) {
  return deliveryState?.status === BATCH_DELIVERY_STATUS.COMPLETED
    || deliveryState?.status === BATCH_DELIVERY_STATUS.UNKNOWN
    || deliveryState?.invalidatesEligibility === true;
}

export function isBatchDeliveryEligible(item, outputItem, selectionBlocked = false) {
  return !selectionBlocked
    && item?.status === "COMPLETED"
    && /^[a-f0-9]{64}$/i.test(item?.outputSha256 || "")
    && Boolean(item?.resultId)
    && outputItem?.result_id === item.resultId
    && outputItem?.unified_result === true
    && outputItem?.delivery_eligible === true
    && outputItem?.status === "completed";
}

function issueMessage(preflight) {
  const issue = preflight?.issues?.[0];
  return {
    code: String(issue?.code || "SMART_DELIVERY_PREFLIGHT_BLOCKED"),
    reason: String(issue?.message || "当前成品未通过交付安全检查。"),
  };
}

function failedDefinite(entry, reason, code = "SMART_DELIVERY_FAILED") {
  return {
    resultId: entry.resultId,
    name: entry.name,
    status: BATCH_DELIVERY_STATUS.FAILED_DEFINITE,
    idempotencyKey: entry.idempotencyKey,
    code,
    reason: reason || "交付失败。",
    invalidatesEligibility: invalidatesBatchDeliveryEligibility(code),
    deliveryId: "",
    sourceSha256: "",
    deliverySha256: "",
  };
}

function unknown(entry, reason, code = "SMART_DELIVERY_OUTCOME_UNKNOWN") {
  return {
    resultId: entry.resultId,
    name: entry.name,
    status: BATCH_DELIVERY_STATUS.UNKNOWN,
    idempotencyKey: entry.idempotencyKey,
    code,
    reason: reason || "正在确认交付结果…",
    invalidatesEligibility: false,
    deliveryId: "",
    sourceSha256: "",
    deliverySha256: "",
  };
}

function executeOutcomeUnknown(reason) {
  const status = Number(reason?.status || 0);
  const code = String(reason?.code || "").toUpperCase();
  return !status
    || status >= 500
    || !code
    || reason?.name === "AbortError"
    || ["NETWORK_ERROR", "SERVER_ERROR", "FETCH_ERROR", "ECONNRESET", "ETIMEDOUT"].includes(code);
}

function normalizeDeliveryResult(entry, run) {
  if (String(run?.status || "").toLowerCase() === "processing") {
    return {
      ...unknown(entry, "正在确认交付结果…", "SMART_DELIVERY_PROCESSING"),
      deliveryId: String(run?.delivery_id || ""),
    };
  }
  const result = (run?.results || []).find((item) => item?.source_result_id === entry.resultId);
  if (!result) return unknown(entry, "交付响应缺少对应 Result，正在确认服务端事实。", "DELIVERY_RESULT_MISSING");
  if (result.status !== "completed") {
    return failedDefinite(
      entry,
      result.failure_reason || "交付副本未能生成。",
      result.failure_code || "SMART_DELIVERY_COPY_FAILED",
    );
  }
  const registered = String(entry.outputSha256 || "").toLowerCase();
  const sourceSha256 = String(result.source_sha256 || "").toLowerCase();
  const deliverySha256 = String(result.delivery_sha256 || "").toLowerCase();
  if (!registered || registered !== sourceSha256 || registered !== deliverySha256) {
    return failedDefinite(entry, "Winner、Result 与 Delivery 内容身份不一致，未将本项标记为成功。", "DELIVERY_SHA_MISMATCH");
  }
  return {
    resultId: entry.resultId,
    name: entry.name,
    status: BATCH_DELIVERY_STATUS.COMPLETED,
    idempotencyKey: entry.idempotencyKey,
    code: "",
    reason: "",
    invalidatesEligibility: false,
    deliveryId: String(result.delivery_id || run?.delivery_id || ""),
    sourceSha256,
    deliverySha256,
    idempotentReplay: run?.idempotent_replay === true,
  };
}

export async function deliverBatchResults(entries, {
  request = requestBatchDeliveryJson,
  onProgress = () => {},
  onItemState = () => {},
  createRequestId = createDeliveryRequestId,
  confirmExisting = false,
} = {}) {
  const unique = [];
  const seen = new Set();
  for (const source of entries || []) {
    const resultId = String(source?.resultId || "");
    if (!resultId || seen.has(resultId)) continue;
    seen.add(resultId);
    const suppliedKey = String(source?.idempotencyKey || "");
    unique.push({
      resultId,
      name: String(source?.name || "未命名图片"),
      outputSha256: String(source?.outputSha256 || "").toLowerCase(),
      idempotencyKey: DELIVERY_REQUEST_PATTERN.test(suppliedKey) ? suppliedKey : createRequestId(),
    });
  }

  const items = [];
  for (let index = 0; index < unique.length; index += 1) {
    const entry = unique[index];
    let phase = "preflight";
    if (confirmExisting) {
      phase = "confirm";
      onProgress({ current: index + 1, total: unique.length, name: entry.name, phase: "confirm" });
      try {
        const statusPayload = await request(
          `/api/smart-delivery/requests/${encodeURIComponent(entry.idempotencyKey)}?result_id=${encodeURIComponent(entry.resultId)}`,
        );
        const result = normalizeDeliveryResult(entry, statusPayload.data);
        items.push(result);
        onItemState(result);
        continue;
      } catch (reason) {
        if (Number(reason?.status) !== 404 || String(reason?.code || "") !== "SMART_DELIVERY_REQUEST_NOT_FOUND") {
          const result = executeOutcomeUnknown(reason)
            ? unknown(entry, "正在确认交付结果…", reason?.code || "SMART_DELIVERY_OUTCOME_UNKNOWN")
            : failedDefinite(entry, reason?.message, reason?.code || "SMART_DELIVERY_REQUEST_CONFIRM_FAILED");
          items.push(result);
          onItemState(result);
          continue;
        }
      }
    }
    onProgress({ current: index + 1, total: unique.length, name: entry.name, phase: "preflight" });
    try {
      const preflightPayload = await request("/api/smart-delivery/preflight", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ result_ids: [entry.resultId], rules: {} }),
      });
      const preflight = preflightPayload.data;
      if (!preflight?.ready) {
        const issue = issueMessage(preflight);
        const result = failedDefinite(entry, issue.reason, issue.code);
        items.push(result);
        onItemState(result);
        continue;
      }
      phase = "execute";
      onProgress({ current: index + 1, total: unique.length, name: entry.name, phase: "execute" });
      onItemState(unknown(entry, "正在确认交付结果…", "SMART_DELIVERY_EXECUTING"));
      const deliveryPayload = await request("/api/smart-delivery/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan_id: preflight.plan_id,
          confirmed: true,
          idempotency_key: entry.idempotencyKey,
        }),
      });
      const result = normalizeDeliveryResult(entry, deliveryPayload.data);
      items.push(result);
      onItemState(result);
    } catch (reason) {
      const result = phase === "execute" && executeOutcomeUnknown(reason)
        ? unknown(entry, "正在确认交付结果…", reason?.code || "SMART_DELIVERY_OUTCOME_UNKNOWN")
        : failedDefinite(entry, reason?.message, reason?.code || "SMART_DELIVERY_REQUEST_FAILED");
      items.push(result);
      onItemState(result);
    }
  }

  const successCount = items.filter((item) => item.status === BATCH_DELIVERY_STATUS.COMPLETED).length;
  const failureCount = items.filter((item) => item.status === BATCH_DELIVERY_STATUS.FAILED_DEFINITE).length;
  const unknownCount = items.filter((item) => item.status === BATCH_DELIVERY_STATUS.UNKNOWN).length;
  return {
    selectedCount: unique.length,
    successCount,
    failureCount,
    unknownCount,
    items,
  };
}

export async function readBatchImportProgress(batchId, { request = requestBatchDeliveryJson } = {}) {
  if (!batchId) return null;
  const payload = await request(`/api/image-compression/batches/${encodeURIComponent(batchId)}/import-progress`);
  if (payload.data?.registered !== true) return null;
  return {
    preparedCount: Number(payload.data?.preparedCount) || 0,
    preparingName: String(payload.data?.preparingName || ""),
  };
}
