const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createHash } = require("node:crypto");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

async function run() {
  const [origin, evidence, resultId] = process.argv.slice(2);
  assert.equal(new URL(origin).hostname, "127.0.0.1");
  const browser = await chromium.launch({ channel: "msedge" });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    async function getData(url) {
      const response = await page.request.get(origin + url);
      assert.equal(response.status(), 200);
      return (await response.json()).data;
    }
    const health = await getData("/api/health");
    assert.equal(path.resolve(health.app_data_root), path.resolve(process.env.PRINT_VALIDATION_ROOT));
    const asset = await getData("/api/result-assets/" + resultId);
    const parentBytes = async () => (await page.request.get(origin + asset.preview_url)).body();
    const digest = bytes => createHash("sha256").update(bytes).digest("hex");
    const hash = digest(await parentBytes());
    assert.equal(hash, asset.source_result_sha256);
    await page.goto(origin + "/outputs");
    const card = page.locator(".hdde-output-card").filter({ hasText: asset.file_name });
    await card.waitFor();
    await page.locator(".hdde-startup-splash").waitFor({ state: "hidden" });
    await card.click();
    await page.getByTestId("output-center-continue-action").click();
    const print = page.getByTestId("continue-processor-print_output");
    await page.locator('[data-testid="continue-processor-print_output"][data-status="AVAILABLE"]').waitFor();
    await print.scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(evidence, "continue-menu.png") });
    await print.click();
    await page.waitForURL("**/print-8k?continue_result=" + resultId);
    await page.reload();
    await page.getByText(/来自已有成品/).waitFor();
    await page.locator(".hdde-startup-splash").waitFor({ state: "hidden" });
    await page.getByText(asset.file_name, { exact: true }).waitFor();
    const original = page.getByRole("img", { name: "已选原图预览" });
    await original.evaluate(image => image.decode());
    const width = page.getByLabel("喷绘宽度（cm）", { exact: true });
    await width.fill("25.4");
    await page.getByRole("button", { name: "100 PPI", exact: true }).click();
    async function submit() {
      const done = page.waitForResponse(r => r.url().endsWith("/api/print-output/render"));
      await page.getByRole("button", { name: "提交出图", exact: true }).click();
      const response = await done;
      assert.equal(response.status(), 200, await response.text());
      const result = await response.json();
      const preview = page.getByRole("img", { name: "喷绘成品预览", exact: true });
      assert.deepEqual(await preview.evaluate(async image => {
        await image.decode();
        return [image.naturalWidth, image.naturalHeight];
      }), [result.width, result.height]);
      return result;
    }
    const child = await submit();
    assert.equal(child.width, 1000);
    assert.notEqual(child.result_id, resultId);
    const chain = await getData("/api/output-center/results/" + child.result_id + "/lineage");
    assert.equal(chain.items.at(-2).result_id, resultId);
    assert.equal(chain.items.at(-1).source_sha256, hash);
    assert.equal(digest(await parentBytes()), hash);
    await page.getByRole("img", { name: "成品局部", exact: true }).waitFor();
    await page.screenshot({ path: path.join(evidence, "print-result.png") });

    // A local replacement starts its own chain even when it has the same pixels.
    await page.getByLabel("选择本地图片").setInputFiles({
      name: asset.file_name, mimeType: "image/" + asset.format.toLowerCase(), buffer: await parentBytes(),
    });
    await page.waitForURL("**/print-8k");
    await original.evaluate(image => image.decode());
    assert.equal(await page.getByText(/来自已有成品/).count(), 0);
    const local = await submit();
    assert.equal((await getData("/api/output-center/results/" + local.result_id + "/lineage")).round_count, 1);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ parent: resultId, hash, child, local: local.result_id, rounds: chain.round_count }));
  } finally {
    await browser.close();
  }
}
run().catch(error => { console.error(error); process.exitCode = 1; });
