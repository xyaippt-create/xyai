const API_BASE = import.meta.env?.VITE_API_BASE_URL || "";

export async function checkBatchOutput(feature, sizes, signal) {
  const response = await fetch(`${API_BASE}/api/${feature}/batches/preflight`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sizes),
    signal: signal || AbortSignal.timeout(10000),
  }).catch(() => { throw new Error("无法检查批次输出空间，请检查本地服务后重试。"); });
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.success !== true) {
    const detail = payload?.detail;
    throw new Error(typeof detail === "string" ? detail : detail?.message || "无法检查批次输出空间，请重试。");
  }
}
