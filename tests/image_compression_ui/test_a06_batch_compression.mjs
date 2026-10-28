import test from "node:test";
import assert from "node:assert/strict";
import { BATCH_STORAGE_KEY, createCompressionBatch, summarizeCompressionBatch } from "../../src/batchCompression.js";

const id = "compression_batch_" + "a".repeat(32);
const file = (name = "same.png") => new File(["x".repeat(100)], name);
const storage = () => {
  const data = new Map();
  return { getItem: (key) => data.get(key), setItem: (key, value) => data.set(key, value), removeItem: (key) => data.delete(key) };
};
const row = (index, status = "COMPLETED") => ({ id: `row-${index}`, name: "same.png", taskId: `task-${index}`,
  status, originalBytes: 100, finalBytes: status === "COMPLETED" ? 40 : status === "KEEP_ORIGINAL" ? 100 : null,
  savedPercent: status === "COMPLETED" ? 60 : null, resultId: status === "COMPLETED" ? `result-${index}` : "",
  sourceSha256: "a".repeat(64), outputSha256: status === "COMPLETED" ? "b".repeat(64) : "", error: "" });
const data = (batchId = id, items = [row(0), row(1, "KEEP_ORIGINAL")], overrides = {}) => ({ batchId, items,
  state: "COMPLETED", running: false, control: "RUNNING", revision: 1, ...overrides });

test("start saves exact batch identity before one multipart submission; never calls single run or replays", async () => {
  const saved = storage(), calls = [];
  const batch = createCompressionBatch({ storage: saved, request: async (path, options) => {
    calls.push(path);
    assert.equal(path, "/api/image-compression/batches");
    assert.equal(options.body.getAll("files").length, 2);
    assert.equal(options.body.get("target_format"), "JPEG");
    assert.equal(saved.getItem(BATCH_STORAGE_KEY), options.body.get("batch_id"));
    return { data: data(options.body.get("batch_id")) };
  } });
  batch.add([file(), file("keep.jpg")]);
  batch.setTargetFormat("JPEG");
  await batch.start(); await batch.start();
  assert.equal(calls.length, 1);
  assert.equal(batch.getSnapshot().targetFormat, "JPEG");
  assert.deepEqual(batch.getSnapshot().items.map((i) => i.status), ["COMPLETED", "KEEP_ORIGINAL"]);
});

test("refresh restores the exact persisted batch with only GET, not latest or submit fallback", async () => {
  const saved = storage(); saved.setItem(BATCH_STORAGE_KEY, id);
  const calls = [];
  const batch = createCompressionBatch({ storage: saved, request: async (...args) => { calls.push(args); return { data: data() }; } });
  assert.equal(batch.getSnapshot().batchId, id);
  await batch.refresh(); await batch.start();
  assert.deepEqual(calls, [[`/api/image-compression/batches/${id}`]]);
  assert.equal(batch.getSnapshot().items[1].resultId, "");
});

test("disconnect preserves known completed results and reconnect does not resubmit", async () => {
  const saved = storage(); saved.setItem(BATCH_STORAGE_KEY, id);
  let disconnect = false;
  const batch = createCompressionBatch({ storage: saved, request: async (path, options) => {
    assert.equal(options, undefined); if (disconnect) throw new Error("offline"); return { data: data() };
  } });
  await batch.refresh(); const rows = batch.getSnapshot().items;
  disconnect = true; await batch.refresh();
  assert.deepEqual(batch.getSnapshot().items, rows);
  assert.match(batch.getSnapshot().error, /不会重新提交/);
  disconnect = false; await batch.refresh();
  assert.equal(batch.getSnapshot().error, "");
});

test("pause resume and cancel send control only, retaining completed identity", async () => {
  const saved = storage(); saved.setItem(BATCH_STORAGE_KEY, id);
  const actions = [];
  const batch = createCompressionBatch({ storage: saved, request: async (path, options) => {
    assert.equal(path, `/api/image-compression/batches/${id}/control`);
    actions.push(JSON.parse(options.body).action);
    return { data: data() };
  } });
  await batch.control("pause"); await batch.control("resume"); await batch.control("cancel");
  assert.deepEqual(actions, ["pause", "resume", "cancel"]);
  assert.equal(batch.getSnapshot().items[0].resultId, "result-0");
});

test("registered queued rows cannot be edited or forgotten; terminal clear never deletes server results", async () => {
  const saved = storage(); saved.setItem(BATCH_STORAGE_KEY, id);
  let reply = data(id, [row(0), row(1, "QUEUED")], { state: "PAUSED", control: "PAUSED" });
  let calls = 0;
  const batch = createCompressionBatch({ storage: saved, request: async () => { calls++; return { data: reply }; } });
  await batch.refresh(); batch.add([file()]); batch.remove("row-1"); batch.clear();
  assert.equal(batch.getSnapshot().items.length, 2);
  reply = data(id, [row(0), row(1, "CANCELED")], { revision: 2 });
  await batch.refresh(); batch.clear();
  assert.equal(batch.getSnapshot().batchId, "");
  assert.equal(saved.getItem(BATCH_STORAGE_KEY), undefined);
  assert.equal(calls, 2);
});

test("duplicate task/result, wrong batch, invalid SHA and fake KEEP result are not accepted", async () => {
  for (const corrupt of [
    (d) => { d.batchId += "bad"; }, (d) => { d.items[1].taskId = d.items[0].taskId; },
    (d) => { d.items[0].outputSha256 = "invalid"; }, (d) => { d.items[1].resultId = "fake"; },
    (d) => { d.items = [row(0), { ...row(1), resultId: "result-0" }]; },
  ]) {
    const saved = storage(); saved.setItem(BATCH_STORAGE_KEY, id);
    const reply = data(); corrupt(reply);
    const batch = createCompressionBatch({ storage: saved, request: async () => ({ data: reply }) });
    await batch.refresh(); assert.equal(batch.getSnapshot().items.length, 0); assert.ok(batch.getSnapshot().error);
  }
});

test("older poll cannot overwrite a newer control response", async () => {
  const saved = storage(); saved.setItem(BATCH_STORAGE_KEY, id);
  let reply = data(id, [row(0)], { revision: 3 });
  const batch = createCompressionBatch({ storage: saved, request: async () => ({ data: reply }) });
  await batch.refresh(); reply = data(id, [row(0, "PROCESSING")], { revision: 2 }); await batch.refresh();
  assert.equal(batch.getSnapshot().items[0].status, "COMPLETED");
});

test("backend restart accepts its durable revision even after an uncommitted newer live revision", async () => {
  const saved = storage(); saved.setItem(BATCH_STORAGE_KEY, id);
  let reply = data(id, [row(0, "PROCESSING")], { serverSessionId: "old", revision: 20 });
  const batch = createCompressionBatch({ storage: saved, request: async () => ({ data: reply }) });
  await batch.refresh(); reply = data(id, [row(0)], { serverSessionId: "new", revision: 3 }); await batch.refresh();
  assert.equal(batch.getSnapshot().items[0].status, "COMPLETED");
});

test("FAILED and CANCELED originals remain in effective total, never fake savings", () => {
  assert.deepEqual(summarizeCompressionBatch([row(0), row(1, "KEEP_ORIGINAL"), row(2, "FAILED"), row(3, "CANCELED")]), {
    total: 4, completed: 1, kept: 1, failed: 1, canceled: 1, processing: 0, waiting: 0,
    originalBytes: 400, effectiveBytes: 340, savedBytes: 60,
  });
});

test("storage unavailable blocks creation; local remove remains available", async () => {
  const batch = createCompressionBatch({ storage: null, request: async () => assert.fail("must not submit") });
  batch.add([file(), file()]); batch.remove(batch.getSnapshot().items[0].id);
  await batch.start(); assert.equal(batch.getSnapshot().batchId, "");
  assert.match(batch.getSnapshot().error, /存储不可用/);
});

test("definite creation rejection keeps files editable, but uncertain transport never resubmits", async () => {
  for (const status of [400, undefined]) {
    const saved = storage(); let calls = 0;
    const batch = createCompressionBatch({ storage: saved, request: async () => {
      calls++; throw Object.assign(new Error("rejected"), { status });
    } });
    batch.add([file()]); await batch.start();
    assert.equal(Boolean(batch.getSnapshot().batchId), status === undefined);
    assert.equal(batch.getSnapshot().items.length, 1);
    if (status === undefined) { await batch.start(); assert.equal(calls, 1); }
    else { batch.remove(batch.getSnapshot().items[0].id); assert.equal(batch.getSnapshot().items.length, 0); }
  }
});

test("oversized batch is rejected before any upload rather than silently dropping files", () => {
  const batch = createCompressionBatch({ storage: storage() });
  batch.add(Array.from({ length: 101 }, () => file()));
  assert.equal(batch.getSnapshot().items.length, 0);
  assert.match(batch.getSnapshot().error, /100/);
});

test("POST disconnected before registration then GET 404 clears stale identity without resubmission", async () => {
  const saved = storage(), calls = [];
  const batch = createCompressionBatch({ storage: saved, request: async (path, options) => {
    calls.push({path, method:options?.method || "GET"});
    if (options?.method === "POST") throw new TypeError("disconnected before registration");
    throw Object.assign(new Error("missing"), {status:404});
  } });
  batch.add([file()]); await batch.start();
  const submittedId = batch.getSnapshot().batchId;
  assert.equal(saved.getItem(BATCH_STORAGE_KEY), submittedId);
  await batch.refresh();
  assert.equal(batch.getSnapshot().state, "BATCH_NOT_FOUND");
  assert.equal(batch.getSnapshot().batchId, "");
  assert.equal(saved.getItem(BATCH_STORAGE_KEY), undefined);
  assert.deepEqual(batch.getSnapshot().items, []);
  assert.equal(batch.getSnapshot().running, false);
  assert.match(batch.getSnapshot().error, /当前批次不存在/);
  await batch.refresh(); await batch.start();
  assert.deepEqual(calls.map(c => c.method), ["POST", "GET"]);
  assert.equal(calls[1].path, `/api/image-compression/batches/${submittedId}`);
  batch.add([file()]); assert.equal(batch.getSnapshot().items.length, 1);
  batch.clear(); assert.equal(batch.getSnapshot().items.length, 0);
  assert.equal(batch.getSnapshot().state, "LOCAL");
});

test("restored nonexistent batch becomes an editable empty state on definite 404", async () => {
  const saved = storage(); saved.setItem(BATCH_STORAGE_KEY, id);
  let requests = 0;
  const batch = createCompressionBatch({storage:saved, request:async () => {
    requests++; throw Object.assign(new Error("missing"), {status:404});
  }});
  await batch.refresh();
  assert.equal(batch.getSnapshot().state, "BATCH_NOT_FOUND");
  assert.equal(batch.getSnapshot().batchId, "");
  assert.equal(saved.getItem(BATCH_STORAGE_KEY), undefined);
  batch.clear(); assert.equal(batch.getSnapshot().state, "LOCAL");
  batch.add([file()]); assert.equal(batch.getSnapshot().items.length, 1);
  assert.equal(requests, 1);
});

test("GET timeout 500 and unknown network errors preserve exact recovery identity and results", async () => {
  for (const status of [undefined, 500, 408]) {
    const saved = storage(); saved.setItem(BATCH_STORAGE_KEY, id);
    let fail = false, posts = 0;
    const batch = createCompressionBatch({storage:saved, request:async (path, options) => {
      if (options?.method === "POST") posts++;
      if (fail) throw Object.assign(new Error("temporary failure"), {status});
      return {data:data(id, [row(0), row(1, "QUEUED")], {state:"PAUSED"})};
    }});
    await batch.refresh(); const previous = batch.getSnapshot();
    fail = true; await batch.refresh(); await batch.start(); batch.clear();
    assert.equal(batch.getSnapshot().batchId, id);
    assert.equal(saved.getItem(BATCH_STORAGE_KEY), id);
    assert.equal(batch.getSnapshot().state, previous.state);
    assert.deepEqual(batch.getSnapshot().items, previous.items);
    assert.match(batch.getSnapshot().error, /不会重新提交/);
    assert.equal(posts, 0);
  }
});
