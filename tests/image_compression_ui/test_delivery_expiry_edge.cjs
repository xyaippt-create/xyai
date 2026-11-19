// Run against an isolated HDDE build with SMART_DELIVERY_PLAN_TTL_SECONDS = 3.
// node test_delivery_expiry_edge.cjs <loopback-url> <sample.png> <evidence-dir>
// The server must use <evidence-dir>/data as its data root. PLAYWRIGHT_MODULE
// may point to an existing Playwright installation.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createHash } = require("node:crypto");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const [url, sample, evidenceDir] = process.argv.slice(2);
const base = new URL(url);
assert.equal(base.hostname, "127.0.0.1");
const api = "/api/smart-delivery/";
const sha = (file) => createHash("sha256").update(fs.readFileSync(file)).digest("hex");
const expire = () => new Promise((resolve) => setTimeout(resolve, 3300));

async function run() {
  const health = (await (await fetch(new URL("/api/health", base))).json()).data;
  const root = fs.realpathSync(path.join(evidenceDir, "data"));
  assert.equal(fs.realpathSync(health.app_data_root), root);
  assert.equal(health.directory_ready, true);
  const output = path.join(root, "输出", "智能交付");
  const listFiles = () => fs.existsSync(output) ? fs.readdirSync(output).sort() : [];
  assert.deepEqual(listFiles(), []);
  const form = new FormData();
  const names = ["single", "multi-a", "multi-b", "unselected", "lost-reply", "removed"];
  for (const name of names) form.append("files", new Blob([fs.readFileSync(sample)], { type: "image/png" }), name + ".png");
  form.append("spec_json", JSON.stringify({ kind: "text", text: "Delivery check" }));
  const seed = await fetch(new URL("/api/batch-watermark/batches", base), { method: "POST", body: form });
  const sources = (await seed.json()).data.items;
  assert.ok(sources.every((source) => source.status === "completed" && sha(source.output_path) === source.output_sha256));
  const snapshot = (await (await fetch(new URL("/api/output-center/items", base))).json()).data;
  const outputItems = snapshot.items.flatMap((item) => [item, ...(item.items || [])]);
  const itemId = (resultId) => outputItems.find((item) => item.result_id === resultId).id;
  const browser = await chromium.launch({ channel: "msedge" });
  const evidence = { port: health.port, sources };
  try {
    for (const [mode, selected] of [
      ["single", [sources[0]]], ["multi", sources.slice(1, 3)], ["lost-reply", [sources[4]]], ["removed", [sources[5]]],
    ]) {
      const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
      const requests = [];
      evidence[mode] = { requests };
      const errors = [];
      const copyBefore = listFiles();
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("request", (request) => {
        const url = new URL(request.url());
        if (url.pathname.startsWith(api)) requests.push({ method: request.method(), path: url.pathname + url.search, body: request.postDataJSON() });
      });
      await page.addInitScript((mode) => {
        const actualFetch = window.fetch.bind(window);
        let dropExecute = mode === "lost-reply";
        let dropStatus = dropExecute;
        let checks = 0;
        window.fetch = async (input, init) => {
          const url = String(input);
          if (dropStatus && url.includes("/api/smart-delivery/requests/")) {
            dropStatus = false;
            throw new TypeError("Edge test: initial status query disconnected");
          }
          const response = await actualFetch(input, init);
          if (dropExecute && url.endsWith("/api/smart-delivery/execute")) {
            dropExecute = false;
            throw new TypeError("Edge test: reply lost after copy");
          }
          if (url.endsWith("/api/smart-delivery/preflight")) {
            checks++;
            if (checks === 1 && mode !== "lost-reply") await new Promise(resolve => setTimeout(resolve, 3300));
            if (checks === 2) await new Promise(resolve => setTimeout(resolve, 400));
          }
          return response;
        };
      }, mode);
      const getResponse = (endpoint) => page.waitForResponse((response) => new URL(response.url()).pathname.startsWith(api + endpoint));
      const check = page.getByRole("checkbox", { name: /我已核对/ });
      const submit = page.getByRole("button", { name: "生成交付副本", exact:true });
      const refresh = page.getByRole("button", { name: "重试交付" });
      const initial = getResponse("preflight");
      const ids = selected.map((source) => mode === "multi" ? itemId(source.result_id) : source.result_id);
      const selection = { [mode === "multi" ? "item_ids" : "result_ids"]: ids, rules: {} };
      const pageUrl = new URL("/smart-delivery", base);
      pageUrl.searchParams.set(mode === "multi" ? "items" : "results", ids.join(","));
      await page.goto(pageUrl.href);
      await page.locator(".hdde-startup-splash").waitFor({ state: "hidden" });
      const execute = getResponse("execute");
      await submit.click();
      const oldPlan = (await (await initial).json()).data;
      evidence[mode].oldPlan = oldPlan;
      const oldResponse = await execute;
      const oldBody = await oldResponse.json();
      evidence[mode].executeStatus = oldResponse.status();
      let newPlan, runResult, probeCode;

      if (mode === "lost-reply") {
        const query = page.getByRole("button", { name: "查询原交付请求" });
        await query.waitFor();
        assert.equal(await submit.count(), 0);
        assert.equal(await refresh.count(), 0);
        assert.equal(oldBody.data.success_count, 1);
        assert.equal(listFiles().length, copyBefore.length + 1);
        await expire();
        const replay = await page.request.post(new URL(api + "execute", base).href, { data: oldResponse.request().postDataJSON() });
        assert.equal(replay.status(), 404);
        probeCode = (await replay.json()).detail.code;
        assert.equal(probeCode, "SMART_DELIVERY_PLAN_EXPIRED");
        const lookup = getResponse("requests/");
        await query.evaluate((button) => { button.click(); button.click(); });
        runResult = (await (await lookup).json()).data;
        assert.equal(runResult.delivery_id, oldBody.data.delivery_id);
        assert.equal(runResult.idempotent_replay, true);
        assert.equal(requests.filter((request) => request.path === api + "execute").length, 1);
        assert.equal(requests.filter((request) => request.path.startsWith(api + "requests/")).length, 1);
        assert.equal(requests.filter((request) => request.path === api + "preflight").length, 1);
      } else {
        assert.equal(oldResponse.status(), 404);
        assert.equal(oldBody.detail.code, "SMART_DELIVERY_PLAN_EXPIRED");
        await page.getByText(oldBody.detail.message, { exact: true }).waitFor();
        assert.equal(await submit.count(), 0);
        await refresh.waitFor();
        assert.equal(await check.count(), 0);
        assert.deepEqual(oldPlan.items.map(item => item.source_result_id), selected.map(source => source.result_id));
        if (mode === "single") {
          await refresh.scrollIntoViewIfNeeded();
          await page.screenshot({ path: path.join(evidenceDir, "expired.png") });
        }
        if (mode === "removed") {
          const sourcePath = fs.realpathSync(selected[0].output_path);
          assert.ok(path.relative(root, sourcePath).startsWith("输出" + path.sep));
          fs.renameSync(sourcePath, path.join(root, "removed-fixture.png"));
        }
        const recheck = getResponse("preflight");
        const completed = mode === "removed" ? null : getResponse("execute");
        await refresh.evaluate((button) => { button.click(); button.click(); });
        assert.equal(await submit.count(), 0);
        const newResponse = await recheck;
        const newBody = await newResponse.json();
        assert.deepEqual(requests.filter((request) => request.path === api + "preflight").map((request) => request.body), [selection, selection]);
        assert.equal(requests.filter((request) => request.path === api + "execute").length, 1);
        if (mode === "removed") {
          assert.equal(newResponse.status(), 404);
          await page.getByText(newBody.detail.message, { exact: true }).waitFor();
          assert.equal(newBody.detail.code, "UNIFIED_RESULT_NOT_FOUND");
          assert.equal(await submit.count(), 0);
          assert.deepEqual(listFiles(), copyBefore);
          evidence[mode] = { requests, oldPlan, blocked: newBody.detail, files: listFiles() };
          await page.screenshot({ path: path.join(evidenceDir, "blocked.png") });
          await page.close();
          continue;
        }
        newPlan = newBody.data;
        assert.ok(newPlan.ready && newPlan.plan_id !== oldPlan.plan_id);
        assert.deepEqual(newPlan.items.map((item) => item.source_result_id), selected.map((source) => source.result_id));
        runResult = (await (await completed).json()).data;
        if (mode === "single") {
          const executions = requests.filter((request) => request.path === api + "execute");
          assert.equal(executions[0].body.idempotency_key, executions[1].body.idempotency_key);
        }
      }
      await page.getByText("交付副本已生成", { exact: true }).waitFor();
      assert.equal(runResult.success_count, selected.length);
      const copies = runResult.results.map((item, index) => {
        const source = selected[index];
        assert.equal(item.source_result_id, source.result_id);
        const copyPath = path.join(output, item.delivery_file_name);
        assert.equal(fs.realpathSync(path.dirname(copyPath)), fs.realpathSync(output));
        const hash = sha(copyPath);
        assert.equal(hash, sha(source.output_path));
        assert.equal(hash, source.output_sha256);
        assert.equal(hash, item.delivery_sha256);
        return { resultId: source.result_id, sourcePath: source.output_path, copyPath, sha256: hash };
      });
      assert.deepEqual(listFiles(), [...copyBefore, ...copies.map((copy) => path.basename(copy.copyPath))].sort());
      assert.deepEqual(errors, []);
      evidence[mode] = { requests, oldPlan, newPlan, probeCode, deliveryId: runResult.delivery_id, copies, files: listFiles() };
      await page.screenshot({ path: path.join(evidenceDir, mode + "-completed.png") });
      await page.close();
    }
  } finally {
    fs.writeFileSync(path.join(evidenceDir, "edge-results.json"), JSON.stringify(evidence, null, 2));
    await browser.close();
  }
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
