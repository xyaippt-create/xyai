export function retouchGroup(batch, id) {
  if (!batch) return null;
  const group = batch.groups.find((entry) => entry.group_id === id) || batch.groups[0];
  const items = group ? batch.items.filter((item) => item.group_id === group.group_id) : [];
  return {
    ...batch, ...group, items, total: items.length,
    finished: items.filter((item) => ["candidate", "saved", "failed", "cancelled"].includes(item.status)).length,
  };
}

export function readBatchView(id) {
  try { return JSON.parse(localStorage.getItem(`hdde.retouch.batch.${id}`)) || {}; }
  catch { return {}; }
}

export function rememberBatchView(id, updates) {
  try { localStorage.setItem(`hdde.retouch.batch.${id}`, JSON.stringify({ ...readBatchView(id), ...updates })); }
  catch { /* Batch files and selection checkpoints are kept by the backend. */ }
}

export function currentBatchCandidate(item, revision) {
  const candidate = item?.candidate;
  if (!candidate || item.source_error || item.candidate_error) return null;
  if (item.status === "saved") return candidate;
  return item.status === "candidate" && (item.retried || candidate.mask_revision === revision) ? candidate : null;
}

export function selectedBatchCandidates(batch, selected, revision) {
  return (batch?.items || []).flatMap((item) => {
    const candidate = currentBatchCandidate(item, revision);
    return (selected === null || selected.includes(item.item_id)) && candidate && item.status === "candidate"
      ? [{ item_id: item.item_id, session_id: candidate.session_id }] : [];
  });
}

export async function uploadRetouchBatchItem(requestJson, url, file, clientItemId) {
  const form = new FormData();
  form.append("file", file);
  form.append("client_item_id", clientItemId);

  async function upload() {
    const { data } = await requestJson(`${url}/items`, { method: "POST", body: form });
    if (!data?.items?.some((item) => item.client_item_id === clientItemId)) {
      throw new Error("未收到这张图片的导入确认。");
    }
    return data;
  }

  try {
    return await upload();
  } catch (reason) {
    if (reason.status && reason.status < 500) throw reason;
    const confirmed = await requestJson(url).catch(() => null);
    if (confirmed?.data?.items?.some((item) => item.client_item_id === clientItemId)) return confirmed.data;
    return upload();
  }
}
