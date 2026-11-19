// Run against isolated HDDE services: node test_workspace_state_edge.cjs <url> <runtime-root> <evidence-dir>
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { createHash } = require("node:crypto");
const path = require("node:path");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

async function submitFromHiddenWorkspace(page, endpoint, button, workspace) {
  let release;
  const sendRequest = new Promise((resolve) => { release = resolve; });
  const isSubmission = (request) => new URL(request.url()).pathname === endpoint && request.method() === "POST";
  await page.route(`**${endpoint}`, async (route) => {
    await sendRequest;
    await route.continue();
  }, { times: 1 });
  const requestStarted = page.waitForRequest(isSubmission);
  const response = page.waitForResponse((item) => isSubmission(item.request()));
  try {
    await button.click();
    await requestStarted;
    await page.getByRole("link", { name: "系统设置", exact: true }).click();
    await workspace.waitFor({ state: "hidden" });
  } finally {
    release();
  }
  const actual = await response;
  assert.equal(actual.ok(), true, await actual.text());
  return (await actual.json()).data;
}

async function main() {
  const [url, runtimeRoot, evidenceDir] = process.argv.slice(2);
  const base = new URL(url);
  assert.equal(base.hostname, "127.0.0.1");
  const health = (await (await fetch(new URL("/api/health", base))).json()).data;
  const isolatedRoot = fs.realpathSync(runtimeRoot);
  assert.equal(fs.realpathSync(health.app_data_root), isolatedRoot);
  assert.equal(health.directory_ready, true);
  const settings = (await (await fetch(new URL("/api/image-compression/output-settings", base))).json()).data;
  assert.equal(fs.realpathSync(settings.effective_output_root), fs.realpathSync(path.join(isolatedRoot, "输出", "图片压缩")));
  const samples = ["sample-a.png", "sample-b.png"].map((file) => path.resolve(evidenceDir, file));
  const hash = (file) => createHash("sha256").update(fs.readFileSync(file)).digest("hex");
  const sourceHashes = samples.map(hash);
  const browser = await chromium.launch({ channel: "msedge" });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(new URL("/batch-watermark", base).href);
    await page.locator(".hdde-startup-splash").waitFor({ state: "hidden" });
    await page.getByTestId("batch-watermark-file-input").setInputFiles(samples);
    const watermark = page.getByTestId("batch-watermark-text");
    await watermark.fill("状态保留验证");
    await page.getByRole("button", { name: "下一张", exact: true }).click();
    const preview = page.getByRole("img", { name: "sample-b.png的真实水印效果", exact: true });
    await preview.waitFor({ state: "visible" });
    const watermarkPreview = await preview.getAttribute("src");
    await page.getByRole("link", { name: "图片交付", exact: true }).click();
    await page.getByTestId("compression-file-input").setInputFiles(samples[0]);
    await page.getByTestId("compression-source-preview").waitFor({ state: "visible" });
    const targetFormat = page.getByTestId("compression-target-format");
    await targetFormat.selectOption("PRESERVE_FORMAT");
    await page.getByRole("link", { name: "批量水印", exact: true }).click();
    await watermark.waitFor({ state: "visible" });
    const watermarkKept = await watermark.inputValue() === "状态保留验证"
      && await preview.count() === 1 && await preview.getAttribute("src") === watermarkPreview;
    await page.screenshot({ path: path.join(evidenceDir, `watermark-${watermarkKept ? "after" : "before"}.png`) });
    await page.getByRole("link", { name: "图片交付", exact: true }).click();
    await targetFormat.waitFor({ state: "visible" });
    const compressionKept = await targetFormat.inputValue() === "PRESERVE_FORMAT"
      && await page.getByTestId("compression-source-preview").isVisible();
    await page.screenshot({ path: path.join(evidenceDir, `compression-${compressionKept ? "after" : "before"}.png`) });
    assert.deepEqual({ watermarkKept, compressionKept }, { watermarkKept: true, compressionKept: true });

    await page.getByRole("tab", { name: "尺寸缩小", exact: true }).click();
    await page.getByTestId("compression-short-side-preset").selectOption("750");
    const compressed = await submitFromHiddenWorkspace(page, "/api/image-compression/run", page.getByTestId("compression-run"), page.getByRole("region", { name: "图片交付优化工作台" }));
    assert.ok(compressed.task.result_id);
    assert.equal(hash(compressed.result.output_path), compressed.result.output_sha256);
    await page.goBack();
    await page.getByRole("region", { name: "处理结果", exact: true }).waitFor({ state: "visible" });

    await page.getByRole("link", { name: "批量水印", exact: true }).click();
    const watermarked = await submitFromHiddenWorkspace(page, "/api/batch-watermark/batches", page.getByTestId("batch-watermark-run"), page.getByTestId("batch-watermark-page"));
    assert.equal(watermarked.completed, 2);
    await page.getByRole("link", { name: "批量水印", exact: true }).click();
    await page.getByRole("button", { name: "进入输出中心", exact: true }).waitFor({ state: "visible" });
    assert.equal(await watermark.inputValue(), "状态保留验证");
    await page.getByRole("button", { name: "进入输出中心", exact: true }).click();
    await page.waitForURL(`**/outputs?batch_id=${watermarked.batch_id}`);
    await page.goBack();
    await page.getByRole("button", { name: "进入输出中心", exact: true }).waitFor({ state: "visible" });

    // Exercise the same in-app route that Output Center opens for a Result.
    const linkedPath = `/compression?continue_result=${encodeURIComponent(compressed.task.result_id)}`;
    const intake = page.waitForResponse((item) => item.url().endsWith("/api/image-compression/intake-result"));
    await page.evaluate((nextPath) => {
      history.pushState({}, "", nextPath);
      dispatchEvent(new PopStateEvent("popstate"));
    }, linkedPath);
    const imported = await intake;
    assert.equal(imported.ok(), true, await imported.text());
    await page.getByText("已有成品预览", { exact: true }).waitFor({ state: "visible" });
    await page.getByRole("link", { name: "系统设置", exact: true }).click();
    await page.getByRole("link", { name: "图片交付", exact: true }).click();
    await page.getByText("已有成品预览", { exact: true }).waitFor({ state: "visible" });
    assert.deepEqual(samples.map(hash), sourceHashes);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ watermarkKept, compressionKept, compressionResultId: compressed.task.result_id, watermarkBatchId: watermarked.batch_id, watermarkCompleted: watermarked.completed, resultImport: true }));
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
