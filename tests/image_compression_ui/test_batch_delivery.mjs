import test from "node:test";
import assert from "node:assert/strict";
import {
  BATCH_DELIVERY_STATUS,
  blocksBatchDeliverySelection,
  deliverBatchResults,
  executeSingleResultDelivery,
  invalidatesBatchDeliveryEligibility,
  isBatchDeliveryEligible,
  loadBatchDeliveryStates,
  loadBatchOutputItems,
  readBatchImportProgress,
  requestBatchDeliveryJson,
  saveBatchDeliveryStates,
} from "../../src/batchDelivery.js";

const sha = (letter) => letter.repeat(64);
const entry = (id, letter = "a") => ({ resultId: `result-${id}`, name: `${id}.png`, outputSha256: sha(letter) });
const jsonResponse = (status, payload, jsonError = null) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => {
    if (jsonError) throw jsonError;
    return payload;
  },
});

test("output center preview and delivery eligibility are joined only by exact result identity", async () => {
  const requested = [];
  const matched = await loadBatchOutputItems(["result-a"], { request: async (path) => {
    requested.push(path);
    return { data: { items: [
      { result_id: "result-other", unified_result: true, delivery_eligible: true, status: "completed" },
      { result_id: "result-a", unified_result: true, delivery_eligible: true, status: "completed", thumbnail_url: "/thumb/a" },
    ] } };
  } });
  assert.deepEqual(requested, ["/api/output-center/items"]);
  assert.equal(matched["result-a"].thumbnail_url, "/thumb/a");
  const batchItem = { status: "COMPLETED", resultId: "result-a", outputSha256: sha("a") };
  assert.equal(isBatchDeliveryEligible(batchItem, matched["result-a"]), true);
  assert.equal(isBatchDeliveryEligible(batchItem, { ...matched["result-a"], result_id: "result-b" }), false);
  assert.equal(isBatchDeliveryEligible(batchItem, { ...matched["result-a"], delivery_eligible: false }), false);
  assert.equal(isBatchDeliveryEligible({ ...batchItem, status: "KEEP_ORIGINAL" }, matched["result-a"]), false);
  assert.equal(isBatchDeliveryEligible(batchItem, matched["result-a"], true), false);
});

test("batch delivery gives every Result an independent preflight and execute with SHA closure", async () => {
  const calls = [];
  const request = async (path, options) => {
    const body = JSON.parse(options.body);
    calls.push({ path, body });
    if (path.endsWith("/preflight")) {
      const resultId = body.result_ids[0];
      return { data: { ready: true, plan_id: `plan-${resultId}` } };
    }
    const resultId = body.plan_id.replace("plan-", "");
    const expected = resultId === "result-one" ? sha("a") : sha("b");
    return { data: { delivery_id: `delivery-${resultId}`, results: [{
      source_result_id: resultId, delivery_id: `delivery-${resultId}`, status: "completed",
      source_sha256: expected, delivery_sha256: expected,
    }] } };
  };
  const progress = [];
  const report = await deliverBatchResults([entry("one", "a"), entry("two", "b")], { request, onProgress: (value) => progress.push(value) });
  assert.equal(report.successCount, 2);
  assert.equal(report.failureCount, 0);
  assert.deepEqual(calls.map((value) => value.path), [
    "/api/smart-delivery/preflight", "/api/smart-delivery/execute",
    "/api/smart-delivery/preflight", "/api/smart-delivery/execute",
  ]);
  assert.ok(calls.filter((value) => value.path.endsWith("preflight")).every((value) => value.body.result_ids.length === 1));
  assert.ok(calls.filter((value) => value.path.endsWith("execute")).every((value) => /^delivery_request_[A-Za-z0-9_-]{16,96}$/.test(value.body.idempotency_key)));
  assert.deepEqual(progress.map((value) => value.phase), ["preflight", "execute", "preflight", "execute"]);
});

test("one blocked or failed delivery cannot stop later selected Results", async () => {
  const executed = [];
  const request = async (path, options) => {
    const body = JSON.parse(options.body);
    if (path.endsWith("/preflight")) {
      const resultId = body.result_ids[0];
      if (resultId === "result-bad") return { data: { ready: false, issues: [{ code: "RESULT_IDENTITY_MISMATCH", message: "内容身份不一致" }] } };
      return { data: { ready: true, plan_id: `plan-${resultId}` } };
    }
    const resultId = body.plan_id.replace("plan-", "");
    executed.push(resultId);
    const expected = resultId === "result-one" ? sha("a") : sha("c");
    return { data: { delivery_id: `delivery-${resultId}`, results: [{ source_result_id: resultId, status: "completed", source_sha256: expected, delivery_sha256: expected }] } };
  };
  const report = await deliverBatchResults([entry("one", "a"), entry("bad", "b"), entry("three", "c")], { request });
  assert.deepEqual(executed, ["result-one", "result-three"]);
  assert.equal(report.successCount, 2);
  assert.equal(report.failureCount, 1);
  assert.equal(report.items[1].code, "RESULT_IDENTITY_MISMATCH");
  assert.equal(report.items[1].status, BATCH_DELIVERY_STATUS.FAILED_DEFINITE);
  assert.equal(report.items[1].invalidatesEligibility, true);
  assert.match(report.items[1].reason, /身份不一致/);
});

test("unknown execute outcome keeps its request identity and the next item still runs", async () => {
  const executeCount = new Map();
  const request = async (path, options) => {
    const body = JSON.parse(options.body);
    if (path.endsWith("/preflight")) return { data: { ready: true, plan_id: `plan-${body.result_ids[0]}` } };
    const resultId = body.plan_id.replace("plan-", "");
    executeCount.set(resultId, (executeCount.get(resultId) || 0) + 1);
    if (resultId === "result-one") throw Object.assign(new Error("连接结果未知"), { status: 500, code: "SERVER_ERROR" });
    return { data: { results: [{ source_result_id: resultId, status: "completed", source_sha256: sha("b"), delivery_sha256: sha("b") }] } };
  };
  const report = await deliverBatchResults([entry("one", "a"), entry("two", "b")], { request });
  assert.equal(executeCount.get("result-one"), 1);
  assert.equal(executeCount.get("result-two"), 1);
  assert.equal(report.successCount, 1);
  assert.equal(report.failureCount, 0);
  assert.equal(report.unknownCount, 1);
  assert.equal(report.items[0].status, BATCH_DELIVERY_STATUS.UNKNOWN);
  assert.match(report.items[0].idempotencyKey, /^delivery_request_/);
});

test("a copied file is not shown as successful unless Delivery and registered SHA match", async () => {
  const report = await deliverBatchResults([entry("one", "a")], { request: async (path, options) => {
    const body = JSON.parse(options.body);
    if (path.endsWith("/preflight")) return { data: { ready: true, plan_id: `plan-${body.result_ids[0]}` } };
    return { data: { results: [{ source_result_id: "result-one", status: "completed", source_sha256: sha("a"), delivery_sha256: sha("z") }] } };
  } });
  assert.equal(report.successCount, 0);
  assert.equal(report.items[0].code, "DELIVERY_SHA_MISMATCH");
  assert.equal(report.items[0].status, BATCH_DELIVERY_STATUS.FAILED_DEFINITE);
  assert.equal(report.items[0].invalidatesEligibility, true);
});

test("response loss then same-key confirmation resolves the original Delivery without duplication", async () => {
  const idempotencyKey = `delivery_request_${"e".repeat(32)}`;
  let responseLost = true;
  let deliveryCount = 0;
  let deliveryId = "";
  const executeKeys = [];
  const request = async (path, options) => {
    const body = options?.body ? JSON.parse(options.body) : {};
    if (path.startsWith("/api/smart-delivery/requests/")) {
      return { data: {
        delivery_id: deliveryId,
        idempotent_replay: true,
        results: [{ source_result_id: "result-one", delivery_id: deliveryId, status: "completed", source_sha256: sha("a"), delivery_sha256: sha("a") }],
      } };
    }
    if (path.endsWith("/preflight")) return { data: { ready: true, plan_id: `plan-${body.result_ids[0]}` } };
    executeKeys.push(body.idempotency_key);
    if (!deliveryId) {
      deliveryCount += 1;
      deliveryId = "delivery-original";
    }
    if (responseLost) {
      responseLost = false;
      throw Object.assign(new Error("response lost"), { status: 0, code: "NETWORK_ERROR" });
    }
    return { data: {
      delivery_id: deliveryId,
      idempotent_replay: true,
      results: [{ source_result_id: "result-one", delivery_id: deliveryId, status: "completed", source_sha256: sha("a"), delivery_sha256: sha("a") }],
    } };
  };
  const requested = [{ ...entry("one", "a"), idempotencyKey }];
  const first = await deliverBatchResults(requested, { request });
  assert.equal(first.items[0].status, BATCH_DELIVERY_STATUS.UNKNOWN);
  const recovered = await deliverBatchResults(requested, { request, confirmExisting: true });
  assert.equal(recovered.items[0].status, BATCH_DELIVERY_STATUS.COMPLETED);
  assert.equal(recovered.items[0].deliveryId, deliveryId);
  assert.equal(recovered.items[0].idempotentReplay, true);
  assert.equal(deliveryCount, 1);
  assert.deepEqual(executeKeys, [idempotencyKey]);
});

test("corrupt HTTP 200 body stays UNKNOWN and same-key confirmation returns the original Delivery", { concurrency: false }, async () => {
  const originalFetch = globalThis.fetch;
  const idempotencyKey = `delivery_request_${"k".repeat(32)}`;
  const deliveryId = "delivery-corrupt-body-original";
  let deliveryCount = 0;
  const executeKeys = [];
  globalThis.fetch = async (path, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : {};
    if (String(path).startsWith("/api/smart-delivery/requests/")) {
      return jsonResponse(200, { success: true, data: {
        delivery_id: deliveryId,
        idempotent_replay: true,
        results: [{ source_result_id: "result-one", delivery_id: deliveryId, status: "completed", source_sha256: sha("a"), delivery_sha256: sha("a") }],
      } });
    }
    if (String(path).endsWith("/preflight")) {
      return jsonResponse(200, { success: true, data: { ready: true, plan_id: `plan-${body.result_ids[0]}` } });
    }
    deliveryCount += 1;
    executeKeys.push(body.idempotency_key);
    return jsonResponse(200, null, new SyntaxError("truncated response body"));
  };
  try {
    const requested = [{ ...entry("one", "a"), idempotencyKey }];
    const first = await deliverBatchResults(requested, { request: requestBatchDeliveryJson });
    assert.equal(first.items[0].status, BATCH_DELIVERY_STATUS.UNKNOWN);
    assert.equal(first.items[0].idempotencyKey, idempotencyKey);
    const recovered = await deliverBatchResults(requested, { request: requestBatchDeliveryJson, confirmExisting: true });
    assert.equal(recovered.items[0].status, BATCH_DELIVERY_STATUS.COMPLETED);
    assert.equal(recovered.items[0].deliveryId, deliveryId);
    assert.equal(recovered.items[0].idempotencyKey, idempotencyKey);
    assert.equal(deliveryCount, 1);
    assert.deepEqual(executeKeys, [idempotencyKey]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("HTTP 200 without data survives refresh as UNKNOWN and confirms with the same key", { concurrency: false }, async () => {
  const originalFetch = globalThis.fetch;
  const idempotencyKey = `delivery_request_${"l".repeat(32)}`;
  const deliveryId = "delivery-missing-data-original";
  let deliveryCount = 0;
  globalThis.fetch = async (path, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : {};
    if (String(path).startsWith("/api/smart-delivery/requests/")) {
      return jsonResponse(200, { success: true, data: {
        delivery_id: deliveryId,
        idempotent_replay: true,
        results: [{ source_result_id: "result-one", delivery_id: deliveryId, status: "completed", source_sha256: sha("a"), delivery_sha256: sha("a") }],
      } });
    }
    if (String(path).endsWith("/preflight")) {
      return jsonResponse(200, { success: true, data: { ready: true, plan_id: `plan-${body.result_ids[0]}` } });
    }
    deliveryCount += 1;
    return jsonResponse(200, { code: 200, status: "success", success: true });
  };
  try {
    const requested = [{ ...entry("one", "a"), idempotencyKey }];
    const first = await deliverBatchResults(requested, { request: requestBatchDeliveryJson });
    assert.equal(first.items[0].status, BATCH_DELIVERY_STATUS.UNKNOWN);

    const values = new Map();
    const storage = {
      getItem: (key) => values.get(key) || null,
      setItem: (key, value) => values.set(key, value),
    };
    saveBatchDeliveryStates("batch-missing-data", {
      "result-one": { ...first.items[0], outputSha256: sha("a") },
    }, { storage });
    const restored = loadBatchDeliveryStates("batch-missing-data", { storage });
    assert.equal(restored["result-one"].idempotencyKey, idempotencyKey);
    assert.equal(restored["result-one"].status, BATCH_DELIVERY_STATUS.UNKNOWN);

    const recovered = await deliverBatchResults([{ ...entry("one", "a"), ...restored["result-one"] }], {
      request: requestBatchDeliveryJson,
      confirmExisting: true,
    });
    assert.equal(recovered.items[0].status, BATCH_DELIVERY_STATUS.COMPLETED);
    assert.equal(recovered.items[0].deliveryId, deliveryId);
    assert.equal(recovered.items[0].idempotencyKey, idempotencyKey);
    assert.equal(deliveryCount, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("HTTP 408 without a business failure code remains UNKNOWN with its original key", { concurrency: false }, async () => {
  const originalFetch = globalThis.fetch;
  const idempotencyKey = `delivery_request_${"m".repeat(32)}`;
  globalThis.fetch = async (path, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : {};
    if (String(path).endsWith("/preflight")) {
      return jsonResponse(200, { success: true, data: { ready: true, plan_id: `plan-${body.result_ids[0]}` } });
    }
    return jsonResponse(408, { message: "request timeout" });
  };
  try {
    const report = await deliverBatchResults([{ ...entry("one", "a"), idempotencyKey }], { request: requestBatchDeliveryJson });
    assert.equal(report.failureCount, 0);
    assert.equal(report.unknownCount, 1);
    assert.equal(report.items[0].status, BATCH_DELIVERY_STATUS.UNKNOWN);
    assert.equal(report.items[0].idempotencyKey, idempotencyKey);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("explicit execute identity mismatch remains definite and invalidates selection", async () => {
  let executeCalls = 0;

  const report = await deliverBatchResults([entry("explicit-identity-failure", "n")], {
    request: async (path, options) => {
      if (path.includes("/preflight")) {
        const body = JSON.parse(options.body);
        return { data: { ready: true, plan_id: `plan-${body.result_ids[0]}` } };
      }
      executeCalls += 1;
      const error = new Error("result identity mismatch");
      error.status = 409;
      error.code = "RESULT_IDENTITY_MISMATCH";
      throw error;
    },
    createRequestId: () => `delivery_request_${"n".repeat(32)}`,
  });

  assert.equal(executeCalls, 1);
  assert.equal(report.successCount, 0);
  assert.equal(report.failureCount, 1);
  assert.equal(report.unknownCount, 0);
  assert.equal(report.items[0].status, BATCH_DELIVERY_STATUS.FAILED_DEFINITE);
  assert.equal(report.items[0].invalidatesEligibility, true);
  assert.equal(blocksBatchDeliverySelection(report.items[0]), true);
});

test("UNKNOWN refresh state restores the same Result and idempotency key", () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
  };
  const idempotencyKey = `delivery_request_${"f".repeat(32)}`;
  saveBatchDeliveryStates("batch-one", {
    "result-one": {
      resultId: "result-one",
      status: BATCH_DELIVERY_STATUS.UNKNOWN,
      idempotencyKey,
      outputSha256: sha("a"),
      code: "NETWORK_ERROR",
      reason: "正在确认交付结果…",
    },
  }, { storage });
  const restored = loadBatchDeliveryStates("batch-one", { storage });
  assert.equal(restored["result-one"].status, BATCH_DELIVERY_STATUS.UNKNOWN);
  assert.equal(restored["result-one"].idempotencyKey, idempotencyKey);
  assert.equal(restored["result-one"].outputSha256, sha("a"));
});

test("UNKNOWN confirmation with no server fact retries execute using the same key", async () => {
  const idempotencyKey = `delivery_request_${"g".repeat(32)}`;
  const calls = [];
  const request = async (path, options) => {
    calls.push({ path, body: options?.body ? JSON.parse(options.body) : null });
    if (path.startsWith("/api/smart-delivery/requests/")) {
      throw Object.assign(new Error("not registered"), { status: 404, code: "SMART_DELIVERY_REQUEST_NOT_FOUND" });
    }
    if (path.endsWith("/preflight")) return { data: { ready: true, plan_id: "plan-result-one" } };
    return { data: { delivery_id: "delivery-one", results: [{ source_result_id: "result-one", delivery_id: "delivery-one", status: "completed", source_sha256: sha("a"), delivery_sha256: sha("a") }] } };
  };
  const report = await deliverBatchResults([{ ...entry("one", "a"), idempotencyKey }], { request, confirmExisting: true });
  assert.equal(report.items[0].status, BATCH_DELIVERY_STATUS.COMPLETED);
  assert.deepEqual(calls.map((item) => item.path.split("?")[0]), [
    `/api/smart-delivery/requests/${idempotencyKey}`,
    "/api/smart-delivery/preflight",
    "/api/smart-delivery/execute",
  ]);
  assert.equal(calls[2].body.idempotency_key, idempotencyKey);
});

test("only integrity and qualification business codes permanently invalidate batch selection", () => {
  assert.equal(invalidatesBatchDeliveryEligibility("RESULT_IDENTITY_MISMATCH"), true);
  assert.equal(invalidatesBatchDeliveryEligibility("RESULT_NOT_DELIVERABLE"), true);
  assert.equal(invalidatesBatchDeliveryEligibility("RESULT_ARTIFACT_MISSING"), true);
  assert.equal(invalidatesBatchDeliveryEligibility("SMART_DELIVERY_DIRECTORY_UNAVAILABLE"), false);
  assert.equal(invalidatesBatchDeliveryEligibility("NETWORK_ERROR"), false);
  assert.equal(blocksBatchDeliverySelection({ status: BATCH_DELIVERY_STATUS.FAILED_DEFINITE, invalidatesEligibility: true }), true);
  assert.equal(blocksBatchDeliverySelection({ status: BATCH_DELIVERY_STATUS.UNKNOWN }), true);
  assert.equal(blocksBatchDeliverySelection({ status: BATCH_DELIVERY_STATUS.FAILED_DEFINITE, invalidatesEligibility: false }), false);
});

test("mixed batch closes as two successes and one definite failure after UNKNOWN confirmation", async () => {
  const keys = {
    "result-good": `delivery_request_${"h".repeat(32)}`,
    "result-bad": `delivery_request_${"i".repeat(32)}`,
    "result-lost": `delivery_request_${"j".repeat(32)}`,
  };
  const deliveries = new Map();
  let loseResponse = true;
  const request = async (path, options) => {
    const body = options?.body ? JSON.parse(options.body) : {};
    if (path.startsWith("/api/smart-delivery/requests/")) {
      const key = decodeURIComponent(path.split("/requests/")[1].split("?")[0]);
      const delivery = deliveries.get(key);
      if (!delivery) throw Object.assign(new Error("missing"), { status: 404, code: "SMART_DELIVERY_REQUEST_NOT_FOUND" });
      return { data: delivery };
    }
    if (path.endsWith("/preflight")) {
      const resultId = body.result_ids[0];
      if (resultId === "result-bad") return { data: { ready: false, issues: [{ code: "RESULT_IDENTITY_MISMATCH", message: "身份不一致" }] } };
      return { data: { ready: true, plan_id: `plan-${resultId}` } };
    }
    const resultId = body.plan_id.replace("plan-", "");
    const letter = resultId === "result-good" ? "a" : "c";
    const delivery = {
      delivery_id: `delivery-${resultId}`,
      results: [{ source_result_id: resultId, delivery_id: `delivery-${resultId}`, status: "completed", source_sha256: sha(letter), delivery_sha256: sha(letter) }],
    };
    deliveries.set(body.idempotency_key, delivery);
    if (resultId === "result-lost" && loseResponse) {
      loseResponse = false;
      throw Object.assign(new Error("response lost"), { status: 0, code: "NETWORK_ERROR" });
    }
    return { data: delivery };
  };
  const requested = [
    { resultId: "result-good", name: "good.png", outputSha256: sha("a"), idempotencyKey: keys["result-good"] },
    { resultId: "result-bad", name: "bad.png", outputSha256: sha("b"), idempotencyKey: keys["result-bad"] },
    { resultId: "result-lost", name: "lost.png", outputSha256: sha("c"), idempotencyKey: keys["result-lost"] },
  ];
  const initial = await deliverBatchResults(requested, { request });
  assert.deepEqual([initial.successCount, initial.failureCount, initial.unknownCount], [1, 1, 1]);
  const recovered = await deliverBatchResults([requested[2]], { request, confirmExisting: true });
  assert.deepEqual([initial.successCount + recovered.successCount, initial.failureCount, deliveries.size], [2, 1, 2]);
  assert.equal(recovered.items[0].deliveryId, "delivery-result-lost");
});

test("duplicate Result selections never create duplicate delivery requests", async () => {
  let executes = 0;
  const request = async (path, options) => {
    const body = JSON.parse(options.body);
    if (path.endsWith("/preflight")) return { data: { ready: true, plan_id: `plan-${body.result_ids[0]}` } };
    executes += 1;
    return { data: { results: [{ source_result_id: "result-one", status: "completed", source_sha256: sha("a"), delivery_sha256: sha("a") }] } };
  };
  const report = await deliverBatchResults([entry("one", "a"), entry("one", "a")], { request });
  assert.equal(report.selectedCount, 1);
  assert.equal(executes, 1);
});

test("preparing observer reports server facts without creating an expected 404 interval", async () => {
  let path = "";
  assert.deepEqual(await readBatchImportProgress("batch", { request: async (value) => { path = value; return { data: { registered: true, preparedCount: 2, preparingName: "三.png" } }; } }), { preparedCount: 2, preparingName: "三.png" });
  assert.match(path, /\/import-progress$/);
  assert.equal(await readBatchImportProgress("batch", { request: async () => ({ data: { registered: false, preparedCount: 0, preparingName: "" } }) }), null);
  await assert.rejects(() => readBatchImportProgress("batch", { request: async () => { throw Object.assign(new Error("timeout"), { status: 500 }); } }), /timeout/);
});

test("single-Result delivery confirms a lost execute response with the same key", async () => {
  const key = `delivery_request_${"9".repeat(32)}`;
  const calls = [];
  const delivered = { delivery_id: "delivery_1", status: "completed", success_count: 1, failure_count: 0, results: [] };
  const request = async (path, options = {}) => {
    calls.push({ path, body: options.body ? JSON.parse(options.body) : null });
    if (path === "/api/smart-delivery/execute") throw Object.assign(new TypeError("Failed to fetch"), { status: 0, code: "" });
    return { success: true, data: { ...delivered, idempotent_replay: true } };
  };
  const outcome = await executeSingleResultDelivery({ planId: "plan_1", resultId: "result-1", idempotencyKey: key, request });
  assert.equal(outcome.outcome, "settled");
  assert.equal(outcome.data.delivery_id, "delivery_1");
  assert.deepEqual(calls[0].body, { plan_id: "plan_1", confirmed: true, idempotency_key: key });
  assert.equal(calls[1].path, `/api/smart-delivery/requests/${key}?result_id=result-1`);
  assert.equal(calls.length, 2);
});

test("single-Result delivery reports pending, not-started and definite outcomes distinctly", async () => {
  const key = `delivery_request_${"8".repeat(32)}`;
  const lost = Object.assign(new Error("Server Error"), { status: 502, code: "" });
  const run = (statusReply) => executeSingleResultDelivery({
    planId: "plan_2", resultId: "result-2", idempotencyKey: key,
    request: async (path) => {
      if (path === "/api/smart-delivery/execute") throw lost;
      return statusReply();
    },
  });
  assert.equal((await run(() => ({ success: true, data: { status: "processing" } }))).outcome, "pending");
  assert.equal((await run(() => {
    throw Object.assign(new Error("not found"), { status: 404, code: "SMART_DELIVERY_REQUEST_NOT_FOUND" });
  })).outcome, "not_started");
  await assert.rejects(run(() => {
    throw Object.assign(new Error("interrupted"), { status: 409, code: "SMART_DELIVERY_INTERRUPTED" });
  }), /interrupted/);

  const definite = Object.assign(new Error("changed"), { status: 409, code: "SMART_DELIVERY_PREVIEW_CHANGED" });
  const statusCalls = [];
  await assert.rejects(executeSingleResultDelivery({
    planId: "plan_3", resultId: "result-3", idempotencyKey: key,
    request: async (path) => {
      if (path === "/api/smart-delivery/execute") throw definite;
      statusCalls.push(path);
      return { success: true, data: {} };
    },
  }), /changed/);
  assert.deepEqual(statusCalls, []);
});

test("batch Results nested under their batch card are found and eligible only while available", async () => {
  const child = (id, extra = {}) => ({ id: `card-${id}`, result_id: id, unified_result: true, delivery_eligible: true, status: "COMPLETED", available: true, ...extra });
  const matched = await loadBatchOutputItems(["result-a", "result-b"], { request: async () => ({ data: { items: [
    { id: "compression_batch_1", batch_id: "compression_batch_1", items: [child("result-a"), child("result-b", { available: false })] },
  ] } }) });
  assert.equal(matched["result-a"].id, "card-result-a");
  const batchItem = (resultId) => ({ status: "COMPLETED", resultId, outputSha256: sha("a") });
  assert.equal(isBatchDeliveryEligible(batchItem("result-a"), matched["result-a"]), true);
  assert.equal(isBatchDeliveryEligible(batchItem("result-b"), matched["result-b"]), false);
  assert.equal(isBatchDeliveryEligible(batchItem("result-a"), { ...matched["result-a"], status: "FAILED" }), false);
});
