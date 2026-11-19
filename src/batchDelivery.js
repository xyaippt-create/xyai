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
  "BATCH_ORIGINAL_UNAVAILABLE",
  "BATCH_ORIGINAL_NAME_INVALID",
  "BATCH_ORIGINAL_DELIVERY_CHANGED",
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
    deliveryFileName: String(raw?.deliveryFileName || ""),
    deliveryLocation: String(raw?.deliveryLocation || ""),
    deliveryPath: String(raw?.deliveryPath || ""),
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

export async function loadBatchDeliveryEligibility(batchId, { request = requestBatchDeliveryJson } = {}) {
  const { data } = await request(`/api/image-compression/batches/${encodeURIComponent(batchId)}/delivery/eligibility`);
  return {
    outputItems: Object.fromEntries(data.items.map((item) => [item.result_id, item])),
    originalIds: new Set(data.originalItemIds),
  };
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
    && outputItem?.available !== false
    // A single card reports "completed"; a batch child keeps its batch status "COMPLETED".
    && String(outputItem?.status || "").toLowerCase() === "completed";
}

export function canSelectBatchDeliveryItem(item, { outputItems, originalIds }, blocked) {
  if (item.status === "KEEP_ORIGINAL") {
    return !blocked.has(item.id) && originalIds.has(item.id)
      && /^[a-f0-9]{64}$/i.test(item.sourceSha256 || "");
  }
  return isBatchDeliveryEligible(item, outputItems[item.resultId], blocked.has(item.resultId));
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

// One Result, one idempotency key: when the execute response is lost, ask the server
// what that request did instead of resubmitting and creating a second copy.
// `request` must reject with { status, code } like requestBatchDeliveryJson.
export async function executeSingleResultDelivery({ planId, resultId, idempotencyKey, request = requestBatchDeliveryJson }) {
  try {
    const payload = await request("/api/smart-delivery/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_id: planId, confirmed: true, idempotency_key: idempotencyKey }),
    });
    return { outcome: "settled", data: payload.data };
  } catch (reason) {
    if (!executeOutcomeUnknown(reason)) throw reason;
  }
  return lookupSingleResultDelivery({ resultId, idempotencyKey, request });
}

export async function lookupSingleResultDelivery({ resultId, idempotencyKey, request = requestBatchDeliveryJson }) {
  return lookupDeliveryRequest({ idempotencyKey, query: { result_id: resultId }, request });
}

export async function lookupDeliveryRequest({ idempotencyKey, query, request = requestBatchDeliveryJson }) {
  try {
    const statusPayload = await request(
      `/api/smart-delivery/requests/${encodeURIComponent(idempotencyKey)}?${new URLSearchParams(query)}`,
    );
    const pending = String(statusPayload.data?.status || "").toLowerCase() === "processing";
    return { outcome: pending ? "pending" : "settled", data: statusPayload.data };
  } catch (reason) {
    if (Number(reason?.status) === 404 && String(reason?.code || "") === "SMART_DELIVERY_REQUEST_NOT_FOUND") {
      return { outcome: "not_started", data: null };
    }
    if (executeOutcomeUnknown(reason)) return { outcome: "pending", data: null };
    throw reason;
  }
}

function normalizeDeliveryResult(entry, run) {
  if (String(run?.status || "").toLowerCase() === "processing") {
    return {
      ...unknown(entry, "正在确认交付结果…", "SMART_DELIVERY_PROCESSING"),
      deliveryId: String(run?.delivery_id || ""),
    };
  }
  const result = (run?.results || []).find((item) => item?.source_result_id === entry.resultId);
  if (!result) return unknown(entry, "暂未收到这份成品的交付记录，正在核对。", "DELIVERY_RESULT_MISSING");
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
    return failedDefinite(entry, "交付副本与压缩成品的内容校验不一致。请在输出中心核对压缩成品。", "DELIVERY_SHA_MISMATCH");
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
    deliveryFileName: String(result.delivery_file_name || ""),
    deliveryLocation: String(run?.delivery_location_label || ""),
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
  batchId = "",
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
      original: source.original === true,
    });
  }

  const items = [];
  for (let index = 0; index < unique.length; index += 1) {
    const entry = unique[index];
    if (entry.original) {
      onProgress({ current: index + 1, total: unique.length, name: entry.name, phase: "execute" });
      onItemState(unknown(entry, "正在确认原图副本…", "SMART_DELIVERY_EXECUTING"));
      let result;
      try {
        const { data } = await request(`/api/image-compression/batches/${encodeURIComponent(batchId)}/delivery/originals/${encodeURIComponent(entry.resultId)}`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirmed: true }),
        });
        if (data.itemId !== entry.resultId || data.deliverySha256 !== entry.outputSha256 || !data.deliveryPath || !data.deliveryFileName) {
          result = failedDefinite(entry, "原图副本的内容校验不一致，请核对交付目录。", "DELIVERY_SHA_MISMATCH");
        } else {
          result = { ...entry, status: BATCH_DELIVERY_STATUS.COMPLETED, deliveryPath: data.deliveryPath, deliveryFileName: data.deliveryFileName };
        }
      } catch (reason) {
        result = executeOutcomeUnknown(reason)
          ? unknown(entry, reason?.message || "正在确认原图副本…", reason?.code || "BATCH_ORIGINAL_COPY_PENDING")
          : failedDefinite(entry, reason?.message, reason?.code || "BATCH_ORIGINAL_COPY_FAILED");
      }
      result = { ...result, original: true };
      items.push(result);
      onItemState(result);
      continue;
    }
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
