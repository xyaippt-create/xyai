// The isolated server uses <evidence-dir>/data as its root. Delay batch rendering
// for the processing/cancel scenarios and fail one write of write-fails-once.png.
// node test_submit_recovery_edge.cjs <url> <sample.png> <evidence-dir>
// PLAYWRIGHT_MODULE can point to an installed Playwright package.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createHash } = require("node:crypto");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const [url, source, evidenceDir] = process.argv.slice(2);
const base = new URL(url);
assert.equal(base.hostname, "127.0.0.1");
const endpoint = new URL("/api/batch-watermark/batches", base).href;
const sha = (file) => createHash("sha256").update(fs.readFileSync(file)).digest("hex");
const sourceSha = sha(source);

async function run() {
  const { data: health } = await (await fetch(new URL("/api/health", base))).json();
  const dataRoot = fs.realpathSync(path.join(evidenceDir, "data"));
  assert.equal(fs.realpathSync(health.app_data_root), dataRoot, "test requires its own isolated data root");
  assert.equal(health.directory_ready, true);
  const outputDir = path.join(dataRoot, "输出", "批量水印");
  assert.ok(!fs.existsSync(outputDir) || fs.readdirSync(outputDir).length === 0);
  const browser = await chromium.launch({ channel: "msedge" });
  const evidence = {};
  try {
    for (const mode of ["completed", "processing", "unsent", "cancel-retry"]) {
      const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
      await page.addInitScript((mode) => {
        const fetchReal = window.fetch.bind(window);
        window.submissions = [];
        window.dropStatus = false;
        window.fetch = async (input, init) => {
          const url = String(input);
          if (window.dropStatus && url.includes("/api/batch-watermark/batches/") && !init?.method) {
            throw new TypeError("Edge test: status connection lost");
          }
          if (!url.endsWith("/api/batch-watermark/batches") || init?.method !== "POST") return fetchReal(input, init);
          const body = init.body;
          window.submissions.push([body.get("batch_id"), body.get("entries_json"), body.get("spec_json")]);
          if (window.submissions.length > 1 || mode === "cancel-retry") return fetchReal(input, init);
          if (mode === "unsent") throw new TypeError("Edge test: request never reached the server");
          // The service continues processing even when the page loses its response.
          const actual = fetchReal(input, { ...init, signal: undefined });
          if (mode === "completed") {
            await actual;
            throw new TypeError("Edge test: response lost after the server completed");
          }
          return Promise.race([actual, new Promise((_, reject) => {
            window.dropSubmitResponse = () => reject(new TypeError("Edge test: response lost while processing"));
          })]);
        };
      }, mode);
      const requests = [];
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("response", (response) => {
        if (response.url().startsWith(endpoint)) requests.push({
          method: response.request().method(), path: new URL(response.url()).pathname, status: response.status(),
        });
      });
      await page.goto(new URL("/batch-watermark", base).href);
      await page.locator(".hdde-startup-splash").waitFor({ state: "hidden" });
      const file = fs.readFileSync(source);
      const names = mode === "cancel-retry" ? ["normal.png", "write-fails-once.png", "cancel-me.png"] : [mode + ".png"];
      await page.getByTestId("batch-watermark-file-input").setInputFiles(names.map((name) => ({
        name, mimeType: "image/png", buffer: file,
      })));
      await page.getByTestId("batch-watermark-text").fill(mode);
      const runBatch = page.getByTestId("batch-watermark-run");
      const query = page.getByRole("button", { name: "查询批次状态" });
      const replay = page.getByRole("button", { name: "继续提交原批次" });
      await runBatch.click();
      const batchId = await page.evaluate(() => window.submissions[0][0]);
      const statusUrl = endpoint + "/" + batchId;
      const lookup = async () => {
        const response = await page.request.get(statusUrl);
        return response.ok() ? (await response.json()).data : response.status();
      };
      let initialResult;
      let recoveryRequestIndex;
      if (mode === "processing") {
        await page.locator('article[data-status="processing"]').waitFor();
        assert.equal((await lookup()).items[0].status, "processing");
        await page.evaluate(() => window.dropSubmitResponse());
      } else if (mode === "cancel-retry") {
        await page.locator('article[data-status="processing"]').filter({ hasText: "write-fails-once.png" }).waitFor();
        await page.getByRole("button", { name: "取消未开始项" }).click();
        const retry = page.getByRole("button", { name: "仅重试失败项" });
        await retry.waitFor();
        initialResult = await lookup();
        assert.deepEqual(initialResult.items.map((item) => item.status), ["completed", "failed", "canceled"]);
        await retry.click();
        await page.locator('article[data-status="completed"]').filter({ hasText: "write-fails-once.png" }).waitFor();
      }

      if (mode !== "cancel-retry") {
        await page.getByText("结果未确认", { exact: true }).first().waitFor();
        if (mode === "completed") {
          initialResult = await lookup();
          assert.equal(initialResult.items[0].status, "completed");
          recoveryRequestIndex = requests.length;
        }
        assert.ok(await runBatch.isDisabled(), "a lost reply must prevent a new batch");
        await query.scrollIntoViewIfNeeded();
        await page.screenshot({ path: path.join(evidenceDir, mode + "-unconfirmed.png") });
        if (mode === "unsent") {
          assert.equal(await lookup(), 404);
          await query.click();
          await replay.waitFor();
          assert.ok(await runBatch.isDisabled());
          await page.evaluate(() => { window.dropStatus = true; });
          await query.click();
          await replay.waitFor({ state: "hidden" });
          assert.ok(await runBatch.isDisabled());
          assert.equal(await page.evaluate(() => window.submissions.length), 1);
          await page.evaluate(() => { window.dropStatus = false; });
          await query.click();
          await replay.waitFor();
          await replay.evaluate((button) => { button.click(); button.click(); });
        } else {
          const firstQuery = page.waitForResponse((response) => response.url() === statusUrl && response.request().method() === "GET");
          await query.evaluate((button) => { button.click(); button.click(); });
          const response = await firstQuery;
          if (mode === "processing") {
            assert.equal((await response.json()).data.items[0].status, "processing");
            await page.locator('article[data-status="processing"]').waitFor();
            await page.screenshot({ path: path.join(evidenceDir, "processing-recovered.png") });
          }
        }
        await page.locator('article[data-status="completed"]').waitFor();
      }

      const result = await lookup();
      assert.equal(result.batch_id, batchId);
      if (mode === "cancel-retry") {
        assert.equal(result.retry_revision, 1);
        assert.deepEqual(result.items.map((item) => item.status), ["completed", "completed", "canceled"]);
        assert.deepEqual(result.items[0], initialResult.items[0]);
        assert.deepEqual(result.items[2], initialResult.items[2]);
        assert.equal(requests.filter((request) => request.path.endsWith("/retry-failed")).length, 1);
      } else if (initialResult) {
        assert.deepEqual(result, initialResult);
        assert.equal(requests.slice(recoveryRequestIndex).filter((request) => request.method === "GET").length, 1);
      }
      const submissions = await page.evaluate(() => window.submissions);
      assert.equal(submissions.length, mode === "unsent" ? 2 : 1);
      if (mode === "unsent") assert.deepEqual(submissions[0], submissions[1]);
      const files = result.items.filter((item) => item.status === "completed").map((item) => {
        assert.equal(fs.realpathSync(path.dirname(item.output_path)), fs.realpathSync(outputDir));
        assert.equal(sha(item.output_path), item.output_sha256);
        assert.equal(item.source_sha_before, sourceSha);
        assert.equal(item.source_sha_after, sourceSha);
        return { resultId: item.result_id, path: item.output_path, sha256: item.output_sha256 };
      });
      assert.deepEqual(await page.locator('article[data-status="completed"]').evaluateAll(
        (rows) => rows.map((row) => row.dataset.resultId),
      ), files.map((file) => file.resultId));
      await page.getByTestId("batch-watermark-delivery-actions").waitFor();
      const actualFiles = fs.readdirSync(outputDir).sort();
      const expectedFiles = [...Object.values(evidence).flatMap((row) => row.files), ...files]
        .map((file) => path.basename(file.path)).sort();
      assert.deepEqual(actualFiles, expectedFiles);
      assert.equal(sha(source), sourceSha);
      assert.deepEqual(errors, []);
      evidence[mode] = {
        batchId, submissions, requests, files, actualFiles, sourceSha, port: health.port,
        ...(initialResult && { beforeRecovery: initialResult.items.map((item) => ({
          status: item.status, resultId: item.result_id, path: item.output_path,
          sha256: item.output_sha256, failureReason: item.failure_reason,
        })) }),
      };
      fs.writeFileSync(path.join(evidenceDir, "edge-results.json"), JSON.stringify(evidence, null, 2));
      await page.screenshot({ path: path.join(evidenceDir, mode + "-finished.png") });
      await page.close();
    }
  } finally {
    await browser.close();
  }
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
