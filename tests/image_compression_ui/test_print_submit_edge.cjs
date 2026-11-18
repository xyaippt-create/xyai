const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

async function run() {
  const [origin, folder, phase, source] = process.argv.slice(2);
  assert.equal(new URL(origin).hostname, "127.0.0.1");
  const browser = await chromium.launch({ channel: "msedge" });
  const page = await browser.newPage({ viewport: { width: 1528, height: 720 } });
  try {
    const health = await (await page.request.get(origin + "/api/health")).json();
    assert.equal(path.resolve(health.data.app_data_root), path.resolve(process.env.PRINT_VALIDATION_ROOT));
    await page.goto(origin + "/print-8k");
    await page.getByRole("heading", {name:"喷绘出图", exact:true}).waitFor();
    await page.locator(".hdde-startup-splash").waitFor({ state:"hidden" });
    await page.screenshot({path:path.join(folder, phase + "-empty.png")});
    const submit = page.getByRole("button", {name:"提交出图", exact:true});
    assert.equal(await submit.count(), 1, "首屏应有唯一提交入口");
    const box = await submit.boundingBox();
    assert.ok(box && box.y >= 0 && box.y + box.height <= 720, "提交应在首屏");
    assert.ok(await submit.isDisabled(), "未选图时禁止空提交");
    await page.getByLabel("选择本地图片").setInputFiles(source);
    await page.getByLabel("计算方式").selectOption("8k");
    await page.getByLabel("目标 PPI（像素/英寸）").fill("162.56");
    await page.getByText("5120 × 7680 px", {exact:true}).waitFor();
    await page.getByLabel("目标 PPI（像素/英寸）").fill("0");
    assert.ok(await submit.isDisabled(), "无效规格应取消提交资格");
    await page.getByLabel("目标 PPI（像素/英寸）").fill("162.56");
    await page.getByRole("button", {name:"分层出图", exact:true}).click();
    assert.ok(await submit.isDisabled(), "未检查选区时不应提交分层任务");
    await page.getByRole("button", {name:"等比出图", exact:true}).click();
    await page.screenshot({path:path.join(folder,phase+"-ready.png")});
    // Drop one outgoing request before it reaches the server. The real retry
    // below must recover and publish only the backend-confirmed result.
    await page.route("**/api/print-output/render", route => route.abort("failed"), {times:1});
    await submit.click();
    await page.getByRole("alert").waitFor();
    assert.ok(await submit.isEnabled());
    const completed=page.waitForResponse(r=>r.url().endsWith("/api/print-output/render"),{timeout:120000});
    await submit.click();
    assert.ok(await page.getByRole("button",{name:"正在出图…"}).isDisabled());
    const response=await completed;
    assert.ok(response.ok(), await response.text());
    const result=await response.json();
    assert.deepEqual([result.width,result.height],[5120,7680]);
    const preview=page.getByRole("img",{name:"喷绘成品预览",exact:true});
    await preview.waitFor();
    const dimensions=await preview.evaluate(async im=>{await im.decode();return [im.naturalWidth,im.naturalHeight]});
    assert.deepEqual(dimensions,[5120,7680]);
    const imageBox = await preview.boundingBox();
    await preview.click({position:{x:imageBox.width*.52,y:imageBox.height*.26}});
    await page.getByRole("img",{name:"成品局部",exact:true}).waitFor();
    await page.screenshot({path:path.join(folder,phase+"-preview.png")});
    const saving=page.waitForResponse(r=>r.url().endsWith("/api/smart-delivery/execute"));
    await page.getByRole("button",{name:"另存交付副本"}).click();
    const receipt=(await (await saving).json()).data;
    assert.equal(receipt.success_count,1);
    assert.equal(receipt.results[0].result_id,result.result_id);
    await page.getByRole("heading",{name:"交付副本已生成"}).waitFor();
    await page.screenshot({path:path.join(folder,phase+"-saved.png")});
    fs.writeFileSync(path.join(folder,phase+"-receipt.json"),JSON.stringify({result,receipt},null,2));
    await page.getByRole("link",{name:"继续喷绘出图"}).click();
    await page.waitForURL("**/print-8k");
    await submit.waitFor();
    assert.ok(await submit.isDisabled());
  } finally {
    await browser.close();
  }
}
run().catch(err=>{console.error(err);process.exitCode=1;});
