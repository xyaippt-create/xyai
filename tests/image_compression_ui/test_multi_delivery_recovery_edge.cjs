// node test_multi_delivery_recovery_edge.cjs <isolated-url> <data-root> <sample.png>
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createHash } = require("node:crypto");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

async function main() {
  const [url, dataRoot, sample] = process.argv.slice(2);
  const base = new URL(url);
  assert.equal(base.hostname, "127.0.0.1");
  const root = fs.realpathSync(dataRoot);
  const health = (await (await fetch(new URL("/api/health", base))).json()).data;
  assert.equal(fs.realpathSync(health.app_data_root), root);
  assert.equal(health.directory_ready, true);
  const output = path.join(root, "输出", "智能交付");
  const listCopies = () => fs.existsSync(output) ? fs.readdirSync(output).sort() : [];
  const hash = (file) => createHash("sha256").update(fs.readFileSync(file)).digest("hex");
  const form = new FormData();
  for (const name of ["response-a", "response-b", "unsent-a", "unsent-b"]) {
    form.append("files", new Blob([fs.readFileSync(sample)], { type: "image/png" }), `${name}.png`);
  }
  form.append("spec_json", JSON.stringify({ kind: "text", text: "Delivery recovery" }));
  const seed = await fetch(new URL("/api/batch-watermark/batches", base), { method: "POST", body: form });
  assert.equal(seed.ok, true);
  const sources = (await seed.json()).data.items;
  assert.equal(sources.length, 4);
  assert.ok(sources.every((item) => item.status === "completed" && hash(item.output_path) === item.output_sha256));
  const snapshot = (await (await fetch(new URL("/api/output-center/items", base))).json()).data;
  const outputItems = snapshot.items.flatMap((item) => [item, ...(item.items || [])]);
  const itemIds = sources.map((source) => outputItems.find((item) => item.result_id === source.result_id).id);
  const browser = await chromium.launch({ channel: "msedge" });
  try {
    for (const droppedReply of [true, false]) {
      const context = await browser.newContext({ reducedMotion: "reduce" });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      const chosen = droppedReply ? sources.slice(0, 2) : sources.slice(2);
      const ids = droppedReply ? chosen.map((item) => item.result_id) : itemIds.slice(2);
      const queryKey = droppedReply ? "results" : "items";
      const deliveryUrl = new URL("/smart-delivery", base);
      deliveryUrl.searchParams.set(queryKey, ids.join(","));
      const before = listCopies();
      const submitted = [];
      let realRun;
      await page.route("**/api/smart-delivery/execute", async (route) => {
        submitted.push(route.request().postDataJSON());
        if (submitted.length === 1) {
          if (droppedReply) {
            const real = await route.fetch();
            assert.equal(real.ok(), true, await real.text());
            realRun = (await real.json()).data;
          }
          await route.abort("failed");
          return;
        }
        await route.continue();
      });
      if (droppedReply) await page.route("**/api/smart-delivery/requests/**", (route) => route.abort("failed"), { times: 1 });
      await page.goto(deliveryUrl.href);
      const submit = page.getByRole("button", { name: "生成交付副本", exact:true });
      assert.equal(await page.getByRole("checkbox", {name:/我已核对/}).count(), 0);
      await submit.click();

      if (droppedReply) {
        await page.getByText("结果待确认", { exact: true }).waitFor();
        assert.equal(listCopies().length, before.length + 2);
        deliveryUrl.searchParams.set(queryKey, [...ids].reverse().join(","));
        await page.goto(deliveryUrl.href);
        await page.getByTestId("file-delivery-result").waitFor();
        assert.equal(submitted.length, 1);
      } else {
        await page.getByText(/暂未查到原请求/).waitFor();
        assert.deepEqual(listCopies(), before);
        const settled = page.waitForResponse((response) => response.url().endsWith("/api/smart-delivery/execute") && response.ok());
        await page.getByRole("button", {name:"重试交付"}).click();
        realRun = (await (await settled).json()).data;
        assert.equal(submitted.length, 2);
        assert.equal(submitted[0].idempotency_key, submitted[1].idempotency_key);
      }

      await page.getByTestId("file-delivery-result").waitFor();
      assert.equal(await page.locator("article[data-status=completed]").count(), 2);
      assert.equal(realRun.success_count, 2);
      for (const result of realRun.results) {
        const original = chosen.find((item) => item.result_id === result.source_result_id);
        assert.equal(hash(path.join(output, result.delivery_file_name)), original.output_sha256);
        assert.equal(hash(original.output_path), original.output_sha256);
      }
      const expectedCopies = [...before, ...realRun.results.map((item) => item.delivery_file_name)].sort();
      assert.deepEqual(listCopies(), expectedCopies);
      const reopened = await context.newPage();
      const receipt = reopened.waitForResponse((response) => response.url().includes("/api/smart-delivery/requests/") && response.ok());
      await reopened.goto(deliveryUrl.href);
      const replay = (await (await receipt).json()).data;
      await reopened.getByTestId("file-delivery-result").waitFor();
      assert.equal(replay.delivery_id, realRun.delivery_id);
      assert.equal(replay.idempotency_key, realRun.idempotency_key);
      assert.deepEqual(listCopies(), expectedCopies);
      assert.deepEqual(errors, []);
      console.log(JSON.stringify({ droppedReply, selectionMode: queryKey, deliveryId: realRun.delivery_id, copies: realRun.success_count }));
      await context.close();
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
