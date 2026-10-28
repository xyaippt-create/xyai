import { apiErrorMessage } from "./compressionStatus.js";
import { TARGET_FORMAT_OPTIONS } from "./compressionParams.js";

const API_BASE = import.meta.env?.VITE_API_BASE_URL || "";

async function requestJson(path, options) {
  const response = await fetch(`${API_BASE}${path}`, options);
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.success === false || !payload?.data) {
    throw Object.assign(new Error(apiErrorMessage(payload, response.status)), { status: response.status });
  }
  return payload;
}

// Interpret the existing single-image response; never select or register a Result here.
export function batchItemOutcome(data, intake) {
  const { task, result } = data || {};
  const winner = result?.winner;
  if (!task?.task_id || task.task_id !== result?.task_id
    || !intake?.source_sha256 || result.source_sha256 !== intake.source_sha256
    || result.source_size_bytes !== intake.size_bytes) {
    throw new Error("图片与处理结果身份不匹配，请到输出中心核对；本项未作为有效结果使用。");
  }
  if (result.failure_code) throw new Error(apiErrorMessage({ detail: { code: result.failure_code } }));
  const identity = { taskId: task.task_id, sourceSha256: intake.source_sha256 };
  if (result.winner_scheme_id === "keep_original" && winner?.source_selected
    && result.public_output_count === 0 && result.output_created === false
    && !task.result_id && result.candidates?.length === 0) {
    return { ...identity, status: "KEEP_ORIGINAL", finalBytes: intake.size_bytes, savedPercent: 0, resultId: "" };
  }
  if (result.public_output_count !== 1 || result.output_created !== true
    || !task.result_id || !winner || winner.source_selected
    || winner.scheme_id !== result.winner_scheme_id || result.candidates?.length !== 1
    || result.candidates[0].scheme_id !== winner.scheme_id
    || winner.quality_gate?.status !== "PASS" || !result.delivery_eligible
    || !/^[a-f0-9]{64}$/i.test(result.output_sha256 || "")
    // The frozen public candidate card does not expose output_sha256.
    // Result owns the registered hash; cross-check the card's published binding.
    || winner.identity_status !== "VALID" || winner.status !== "AVAILABLE" || !winner.selected
    || winner.file_size !== result.output_size_bytes || winner.output_path !== result.output_path
    || !Number.isSafeInteger(result.output_size_bytes) || result.output_size_bytes <= 0
    || result.output_size_bytes >= intake.size_bytes) {
    throw new Error("未收到质量达标的唯一压缩结果，请到输出中心核对本项。");
  }
  return {
    ...identity, status: "COMPLETED", resultId: task.result_id,
    outputSha256: result.output_sha256, finalBytes: result.output_size_bytes,
    savedPercent: (intake.size_bytes - result.output_size_bytes) * 100 / intake.size_bytes,
  };
}

export function summarizeCompressionBatch(items) {
  const count = (status) => items.filter((item) => item.status === status).length;
  const originalBytes = items.reduce((total, item) => total + item.originalBytes, 0);
  // Failed and unprocessed originals still exist: they must not count as bytes saved.
  const effectiveBytes = items.reduce((total, item) => total + (
    item.status === "COMPLETED" ? item.finalBytes : item.originalBytes
  ), 0);
  return {
    total: items.length, completed: count("COMPLETED"), kept: count("KEEP_ORIGINAL"),
    failed: count("FAILED"), canceled: count("CANCELED"), processing: count("PROCESSING"), waiting: count("QUEUED"),
    originalBytes, effectiveBytes, savedBytes: originalBytes - effectiveBytes,
  };
}

export const BATCH_STORAGE_KEY = "hdde.compression.active-batch.v1";
const END_STATES = new Set(["COMPLETED", "KEEP_ORIGINAL", "FAILED", "CANCELED"]);
const TARGET_FORMAT_VALUES = new Set(TARGET_FORMAT_OPTIONS.map((item) => item.value));

// The browser retains only an exact batch ID. The shared backend registry owns
// sources, scheduling and results; reload/reconnect never submits another run.
export function createCompressionBatch({ request = requestJson, storage = globalThis.localStorage } = {}) {
  let savedId = "";
  try { savedId = storage?.getItem(BATCH_STORAGE_KEY) || ""; } catch { /* start reports unavailable storage */ }
  if (!/^compression_batch_[a-f0-9]{32}$/.test(savedId)) savedId = "";
  let snapshot = { items: [], running: false, batchId: savedId, loading: false, state: savedId ? "RESTORING" : "LOCAL", error: "", targetFormat: "SMART_COMPRESSION" };
  const listeners = new Set();
  let refreshing = false;
  const publish = (patch) => {
    snapshot = { ...snapshot, ...patch };
    listeners.forEach((listener) => listener());
  };
  const accept = (data) => {
    if (data?.batchId !== snapshot.batchId || !Array.isArray(data.items)) throw new Error("批次身份不匹配，未使用该响应。");
    const responseTargetFormat = data.targetFormat || snapshot.targetFormat;
    if (!TARGET_FORMAT_VALUES.has(responseTargetFormat)) throw new Error("批次目标格式无效，未使用该响应。");
    const tasks = new Set(), results = new Set();
    for (const row of data.items) {
      if ((!END_STATES.has(row.status) && !["QUEUED", "PROCESSING"].includes(row.status))
        || !row.taskId || tasks.has(row.taskId)
        || (row.status === "COMPLETED" && (!row.resultId || results.has(row.resultId)
          || !/^[a-f0-9]{64}$/i.test(row.outputSha256 || "") || !/^[a-f0-9]{64}$/i.test(row.sourceSha256 || "")
          || !Number.isSafeInteger(row.finalBytes) || row.finalBytes <= 0
          || (row.finalBytes >= row.originalBytes && row.formatConversion !== true)))
        || (row.status !== "COMPLETED" && row.resultId)) throw new Error("批次结果身份或状态不一致，未作为有效结果展示。");
      tasks.add(row.taskId);
      if (row.resultId) results.add(row.resultId);
    }
    if (data.serverSessionId === snapshot.serverSessionId && (data.revision || 0) < (snapshot.revision || 0)) return;
    publish({ ...data, targetFormat: responseTargetFormat, error: "", loading: false });
  };
  const editable = () => !snapshot.batchId && !snapshot.loading;
  const batch = {
    getSnapshot: () => snapshot,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    add(files) {
      if (!editable()) return;
      if (snapshot.items.length + Array.from(files || []).length > 100) {
        publish({ error: "每批最多100张图片，请分批添加。" });
        return;
      }
      const additions = Array.from(files || []).map((file) => {
        const error = !/\.(png|jpe?g|webp)$/i.test(file.name)
          ? "仅支持 PNG、JPG、JPEG、WebP，请移除此项后添加支持的图片。"
          : !file.size ? "文件为空，请重新添加有效图片。" : file.size > 50 * 1024 * 1024 ? "单张图片不能超过50MB。" : "";
        return {
          id: crypto.randomUUID(), file, name: file.name,
          originalBytes: file.size, finalBytes: null, savedPercent: null,
          status: error ? "FAILED" : "QUEUED", error, resultId: "",
        };
      });
      publish({ items: [...snapshot.items, ...additions], state: "LOCAL", error: "" });
    },
    remove(id) {
      if (editable()) publish({ items: snapshot.items.filter((item) => item.id !== id) });
    },
    clear() {
      if (snapshot.loading || snapshot.running || (snapshot.batchId && snapshot.items.some((item) => !END_STATES.has(item.status)))) return;
      try { storage?.removeItem(BATCH_STORAGE_KEY); } catch { publish({ error: "无法更新批次恢复记录。" }); return; }
      publish({ items: [], batchId: "", running: false, state: "LOCAL", revision: 0, error: "", targetFormat: "SMART_COMPRESSION" });
    },
    setTargetFormat(value) {
      if (!editable() || !TARGET_FORMAT_VALUES.has(value)) return;
      publish({ targetFormat: value, error: "" });
    },
    async start() {
      if (!editable() || !snapshot.items.length) return;
      const batchId = `compression_batch_${crypto.randomUUID().replaceAll("-", "")}`;
      try {
        if (!storage) throw new Error("浏览器批次恢复存储不可用，未开始处理。");
        storage.setItem(BATCH_STORAGE_KEY, batchId);
        const body = new FormData();
        body.set("batch_id", batchId);
        body.set("target_format", snapshot.targetFormat);
        snapshot.items.forEach((item) => body.append("files", item.file));
        publish({ batchId, loading: true, state: "IMPORTING", error: "" });
        accept((await request("/api/image-compression/batches", { method: "POST", body })).data);
      } catch (reason) {
        if ([400, 413, 415, 422].includes(reason.status)) {
          // These creation rejections occur before batch registration. Keep local
          // files editable; uncertain network/5xx outcomes still recover by exact ID.
          try { storage?.removeItem(BATCH_STORAGE_KEY); } catch { /* keep the displayed failure */ }
          publish({ batchId: "", state: "LOCAL" });
        }
        publish({ loading: false, error: reason.message || "导入响应中断，将按已保存批次身份重新连接；不会重复提交。" });
      }
    },
    async refresh() {
      if (!snapshot.batchId || snapshot.loading || refreshing) return;
      refreshing = true;
      const id = snapshot.batchId;
      try {
        const response = await request(`/api/image-compression/batches/${encodeURIComponent(id)}`);
        if (snapshot.batchId === id) accept(response.data);
      } catch (reason) {
        if (snapshot.batchId === id) {
          if (reason.status === 404) {
            // Only a definite missing-batch response invalidates the saved ID.
            // Do not retain phantom rows or automatically create another batch.
            try { storage?.removeItem(BATCH_STORAGE_KEY); }
            catch { publish({ error: "当前批次不存在，但无法清除恢复记录；请检查浏览器存储后重试。" }); return; }
            publish({ batchId: "", items: [], running: false, loading: false, state: "BATCH_NOT_FOUND",
              revision: 0, control: undefined, serverSessionId: undefined,
              error: "当前批次不存在，请重新创建批次。" });
          } else {
            publish({ error: `${reason.message || "服务连接中断"} 将继续尝试恢复此批次，不会重新提交图片。` });
          }
        }
      } finally { refreshing = false; }
    },
    async control(action) {
      if (!snapshot.batchId || snapshot.loading) return;
      publish({ loading: true });
      try {
        accept((await request(`/api/image-compression/batches/${encodeURIComponent(snapshot.batchId)}/control`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }),
        })).data);
      } catch (reason) { publish({ loading: false, error: reason.message || "控制操作未确认，请重新连接后核对状态。" }); }
    },
  };
  return batch;
}

export const compressionBatch = createCompressionBatch();
