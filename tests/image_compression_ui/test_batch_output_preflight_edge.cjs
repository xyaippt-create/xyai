// node test_batch_output_preflight_edge.cjs <isolated-url> <data-root> <sample.png>
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
  const settings = (await (await fetch(new URL("/api/image-compression/output-settings", base))).json()).data;
  assert.equal(fs.realpathSync(settings.effective_output_root), fs.realpathSync(path.join(root, "输出", "图片压缩")));
  const sampleBytes = fs.readFileSync(sample);
  const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
  const sourceSha = sha(sampleBytes);

  const browser = await chromium.launch({ channel: "msedge" });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
    const submissions = [];
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      const pathname = new URL(request.url()).pathname;
      if (request.method() === "POST" && pathname.endsWith("/batches")) submissions.push(pathname);
    });
    const watermark = "/api/batch-watermark/batches";
    const compression = "/api/image-compression/batches";
    await page.goto(new URL("/batch-watermark", base).href);
    const files = page.getByTestId("batch-watermark-file-input");
    await files.setInputFiles(sample);
    await files.evaluate((input) => {
      const data = new DataTransfer();
      data.items.add(new File([], "空图.png", { type: "image/png" }));
      data.items.add(new File(["unsupported"], "不支持.webp", { type: "image/webp" }));
      data.items.add(new File([new Uint8Array(50 * 1024 * 1024 + 1)], "超限.png", { type: "image/png" }));
      input.files = data.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await page.getByText("已添加 1 张图片", { exact: true }).waitFor();
    await page.getByText("空图.png：文件为空。", { exact: true }).waitFor();
    await page.getByText("不支持.webp：仅支持 PNG、JPG、JPEG。", { exact: true }).waitFor();
    await page.getByText("超限.png：单个文件不得超过 50 MiB。", { exact: true }).waitFor();
    await files.setInputFiles(Array.from({ length: 100 }, (_, i) => ({ name: `额外-${i}.png`, mimeType: "image/png", buffer: sampleBytes })));
    await page.getByText("100 个文件未加入", { exact: true }).click();
    await page.getByText(/额外-99\.png：本次选图超过每批 100 张/).waitFor();
    assert.deepEqual(submissions, []);
    const watermarkResponse = page.waitForResponse((response) => response.url().endsWith(watermark) && response.request().method() === "POST");
    await page.getByTestId("batch-watermark-run").click();
    const watermarked = (await (await watermarkResponse).json()).data;
    assert.equal(watermarked.completed, 1);
    assert.equal(watermarked.items[0].source_sha_before, sourceSha);
    assert.equal(sha(fs.readFileSync(watermarked.items[0].output_path)), watermarked.items[0].output_sha256);

    await page.getByRole("link", { name: "图片交付", exact: true }).click();
    await page.getByTestId("compression-batch-mode").click();
    await page.getByTestId("batch-compression-files").setInputFiles(sample);
    await page.route(`**${compression}/preflight`, async (route) => {
      // Exercise the real volume check with a reservation larger than the test drive.
      const response = await route.fetch({ postData: { source_bytes: Number.MAX_SAFE_INTEGER, largest_source_bytes: 1 } });
      assert.equal(response.status(), 422, await response.text());
      assert.equal((await response.json()).detail.code, "BATCH_DISK_SPACE_INSUFFICIENT");
      await route.fulfill({ response });
    }, { times: 1 });
    const start = page.getByTestId("batch-compression-start");
    await start.click();
    await page.getByRole("alert").filter({ hasText: /磁盘空间不足/ }).waitFor();
    assert.deepEqual(submissions, [watermark]);
    await page.getByTestId("batch-compression-list").getByText(path.basename(sample), { exact: true }).waitFor();
    await start.click();
    await page.getByTestId("batch-compression-summary").waitFor({ timeout: 60000 });
    assert.deepEqual(submissions, [watermark, compression]);
    assert.equal(sha(fs.readFileSync(sample)), sourceSha);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ rejectedInputs: 3, excessInputs: 100, watermarkCompleted: 1, lowSpaceBlockedBeforeUpload: true, compressionSubmittedAfterRecheck: true }));
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
