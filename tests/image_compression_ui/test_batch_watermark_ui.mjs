import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test, { after } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");
process.env.HDDE_API_TARGET ||= "http://127.0.0.1:0";
let viteServer = null;

async function loadRealComponent(modulePath) {
  if (!viteServer) {
    viteServer = await createServer({ root, appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  }
  return viteServer.ssrLoadModule(modulePath);
}

after(async () => {
  if (viteServer) await viteServer.close();
});

test("batch watermark is a formal route and not a placeholder", () => {
  const routes = read("src/appRoutes.js");
  const app = read("src/App.jsx");
  assert.match(routes, /key:\s*"batch-watermark"[\s\S]*?implementationType:\s*"existing"/);
  assert.match(app, /route\.key === "batch-watermark"/);
  assert.match(app, /<BatchWatermarkPage/);
  assert.doesNotMatch(read("src/BatchWatermarkPage.jsx"), /<main\b/);
});

test("formal UI wires real preview, batch execution and completion actions", () => {
  const page = read("src/BatchWatermarkPage.jsx");
  assert.match(page, /\/api\/batch-watermark\/preview/);
  assert.match(page, /\/api\/batch-watermark\/batches/);
  assert.match(page, /\/api\/batch-watermark\/open-output-folder/);
  assert.match(page, /multiple hidden accept="\.png,\.jpg,\.jpeg/);
  assert.match(page, /文字水印/);
  assert.match(page, /图片水印/);
  assert.match(page, /九宫格位置/);
  assert.equal((page.match(/>打开文件夹<\/button>/g) || []).length, 1);
  assert.equal((page.match(/>进入输出中心<\/button>/g) || []).length, 1);
  assert.equal((page.match(/data-testid="batch-watermark-run"/g) || []).length, 1);
  assert.doesNotMatch(page, />打开输出目录<\/button>|>查看输出目录<\/button>|>查看结果<\/button>|>返回处理中<\/button>|>返回处理中心<\/button>|PNG图片水印/);
  assert.doesNotMatch(page, /TOTAL=|COMPLETED=|FAILED=/);
});

test("batch result deep link restores the exact persisted batch without task-detail contracts", () => {
  const page = read("src/BatchWatermarkPage.jsx");
  assert.match(page, /new URLSearchParams\(window\.location\.search\)\.get\("batch_id"\)/);
  assert.match(page, /fetch\(`\$\{API_BASE\}\/api\/batch-watermark\/batches\/\$\{encodeURIComponent\(requestedBatchId\)\}`/);
  assert.match(page, /method:\s*"GET"/);
  assert.match(page, /recovered\?\.batch_id !== requestedBatchId/);
  assert.match(page, /WATERMARK_BATCH_ID_MISMATCH/);
  assert.match(page, /validateRecoveredBatchResult/);
  assert.match(page, /result\?\.batch_id/);
  assert.doesNotMatch(page, /result\.items\.map|hdde-watermark-result-items/);
  assert.doesNotMatch(page, />返回处理中<\/button>|>返回处理中心<\/button>/);
  const recovery = page.match(/const recoverBatch = async \(\) => \{([\s\S]*?)\n    \};\n    void recoverBatch\(\);/);
  assert.ok(recovery, "persisted batch recovery must remain separate from Result input loading");
  assert.doesNotMatch(recovery[1], /result_id|task_result|\/api\/result-assets/);
  assert.match(page, /if \(!normalized \|\| requestedBatchId\) return undefined;/);
});

test("recovered batch result keeps full partial and failed contracts distinct", async () => {
  const { mapRecoveredBatchItems, validateRecoveredBatchResult } = await loadRealComponent("/src/BatchWatermarkPage.jsx");
  for (const batchStatus of ["FULL_SUCCESS", "PARTIAL_SUCCESS", "FAILED"]) {
    const validBatchId = `watermark_batch_${batchStatus === "FULL_SUCCESS" ? "a".repeat(16) : batchStatus === "PARTIAL_SUCCESS" ? "b".repeat(16) : "c".repeat(16)}`;
    const recovered = {
      batch_id: validBatchId,
      batch_status: batchStatus,
      items: [{ item_id: `${batchStatus}-1`, file_name: "样本.png", status: batchStatus === "FAILED" ? "failed" : "completed", failure_reason: batchStatus === "FAILED" ? "真实失败原因" : "" }],
    };
    assert.equal(validateRecoveredBatchResult(recovered, validBatchId), recovered);
  }
  assert.throws(
    () => validateRecoveredBatchResult({ batch_id: "watermark_batch_aaaaaaaaaaaaaaaa", batch_status: "FULL_SUCCESS", items: [] }, "watermark_batch_bbbbbbbbbbbbbbbb"),
    (error) => error.code === "WATERMARK_BATCH_ID_MISMATCH",
  );
  assert.throws(
    () => validateRecoveredBatchResult({ batch_id: "watermark_batch_aaaaaaaaaaaaaaaa", batch_status: "completed", items: [] }, "watermark_batch_aaaaaaaaaaaaaaaa"),
    /尚未形成可恢复的真实结果/,
  );

  const partialBatch = {
    batch_id: "watermark_batch_bbbbbbbbbbbbbbbb",
    batch_status: "PARTIAL_SUCCESS",
    total: 21,
    completed: 19,
    failed: 2,
    items: Array.from({ length: 21 }, (_, index) => ({
      item_id: `item-${index + 1}`,
      file_name: index >= 19 ? `失败样本_${index - 18}.png` : `成功样本_${index + 1}.png`,
      status: index >= 19 ? "failed" : "completed",
      failure_reason: index >= 19 ? `真实失败原因 ${index - 18}` : "",
      output_file_name: index >= 19 ? "" : `成功样本_${index + 1}_水印.png`,
    })),
  };
  const restoredItems = mapRecoveredBatchItems(validateRecoveredBatchResult(partialBatch, partialBatch.batch_id));
  assert.equal(restoredItems.length, 21);
  assert.equal(restoredItems.filter((item) => item.status === "completed").length, 19);
  assert.equal(restoredItems.filter((item) => item.status === "failed").length, 2);
  assert.deepEqual(restoredItems.slice(-2).map((item) => item.failureReason), ["真实失败原因 1", "真实失败原因 2"]);
  assert.deepEqual(restoredItems.slice(-2).map((item) => item.fileName), ["失败样本_1.png", "失败样本_2.png"]);
  assert.ok(restoredItems.every((item) => item.file === null && item.recovered === true));
});

test("recovery hydrates the only left list and keeps history read-only", () => {
  const page = read("src/BatchWatermarkPage.jsx");
  assert.match(page, /const restoredItems = mapRecoveredBatchItems\(recovered\)/);
  assert.match(page, /setItems\(restoredItems\)/);
  assert.match(page, /setActiveId\(restoredItems\[0\]\?\.id \|\| ""\)/);
  assert.match(page, /if \(!activeItem\?\.file && !activeItem\?\.previewUrl\)\s*\{\s*setSourcePreviewUrl\(""\)/);
  assert.match(page, /if \(activeItem\.previewUrl\)\s*\{\s*setSourcePreviewUrl\(activeItem\.previewUrl\);\s*return undefined;/);
  assert.match(page, /const hasRunnableItems = items\.length > 0 && items\.every\(\(item\) => item\.file \|\| item\.resultId\)/);
  assert.match(page, /disabled=\{running \|\| item\.recovered\}/);
  assert.match(page, /disabled=\{!hasRunnableItems \|\| running/);
  assert.equal((page.match(/className="hdde-watermark-file-list"/g) || []).length, 1);
  assert.doesNotMatch(page, /result\.items\.map|hdde-watermark-result-items/);
});

test("image watermark exposes relative width but no tile control", () => {
  const page = read("src/BatchWatermarkPage.jsx");
  const imageBranch = page.split('kind === "text" ? <>')[1].split('</> : <>')[1].split("</>}")[0];
  assert.match(imageBranch, /ScrubbableNumericField label="大小"/);
  assert.match(imageBranch, /imageWidthPercent/);
  assert.doesNotMatch(imageBranch, /平铺文字/);
});

test("parameter labels and progress remain concise and truthful", () => {
  const page = read("src/BatchWatermarkPage.jsx");
  assert.match(page, /<span id="batch-watermark-color-label">颜色<\/span>/);
  assert.match(page, /ScrubbableNumericField label="大小" value=\{textSize\}/);
  assert.match(page, /value=\{running \? undefined : progress\}/);
  assert.doesNotMatch(page, /Math\.max\(5, progress\)|文字颜色|文字大小|图片宽度/);
  assert.match(page, /<strong>\{completed\} 成功 \/ \{failed\} 失败 \/ \{total\} 总计<\/strong>/);
  assert.doesNotMatch(page, /TOTAL=|COMPLETED=|FAILED=/);
});

test("font selector exposes exactly two bundled self-preview fonts and defaults to Source Han Sans CN Medium", () => {
  const page = read("src/BatchWatermarkPage.jsx");
  const css = read("src/index.css");
  assert.match(page, /const \[fontId, setFontId\] = useState\("source_han_sans_cn_medium"\)/);
  assert.match(page, /kind, text, font_id: fontId, color, opacity/);
  assert.match(page, /data-testid="batch-watermark-font"/);
  assert.equal((page.match(/\["source_han_(?:sans_cn_medium|serif_cn_heavy)",/g) || []).length, 2);
  assert.match(page, /\["source_han_sans_cn_medium", "思源黑体 CN Medium", "hdde-watermark-font--sans-medium"\]/);
  assert.match(page, /\["source_han_serif_cn_heavy", "思源宋体 CN Heavy", "hdde-watermark-font--serif-heavy"\]/);
  assert.doesNotMatch(page, /当前默认字体|\["default",/);
  assert.match(page, /role="listbox" aria-label="内置字体"/);
  assert.match(page, /role="option" className=\{previewClass\}/);
  assert.match(css, /@font-face[\s\S]*?SourceHanSansCN-Medium\.otf[\s\S]*?font-weight:\s*500/);
  assert.match(css, /@font-face[\s\S]*?SourceHanSerifCN-Heavy\.otf/);
  assert.match(css, /\.hdde-watermark-font--sans-medium\s*\{[^}]*HDDE Source Han Sans Medium[^}]*font-weight:\s*500/);
  assert.match(css, /\.hdde-watermark-font--serif-heavy\s*\{[^}]*HDDE Source Han Serif Heavy/);
});

test("editable watermark text integrates the eight presets without a button wall or second text state", () => {
  const page = read("src/BatchWatermarkPage.jsx");
  for (const preset of ["仅供预览", "内部资料", "仅供内部使用", "请勿转载", "版权所有", "样稿", "DEMO", "未经授权禁止使用"]) {
    assert.ok(page.includes(preset));
  }
  assert.match(page, /aria-label="选择常用水印文字"[\s\S]*?aria-haspopup="listbox"/);
  assert.match(page, /TEXT_PRESETS\.map\(\(preset\) => <button[\s\S]*?onChange\(preset\)/);
  assert.match(page, /<TextPresetField value=\{text\} onChange=\{setText\}/);
  assert.match(page, /data-testid="batch-watermark-text"[\s\S]*?onChange=\{\(event\) => onChange\(event\.target\.value\)\}/);
  assert.equal((page.match(/const \[text, setText\]/g) || []).length, 1);
  assert.doesNotMatch(page, /hdde-watermark-presets|常用文字<\/span>/);
});

test("compact color and scrubbable numeric controls share authoritative state and reject invalid drafts", async () => {
  const page = read("src/BatchWatermarkPage.jsx");
  for (const testId of ["batch-watermark-color-hex", "batch-watermark-color-swatch", "batch-watermark-color-popover", "batch-watermark-saturation-value", "batch-watermark-hue"]) {
    assert.ok(page.includes(testId));
  }
  assert.match(page, /data-testid=\{`\$\{testId\}-manual`\}/);
  assert.match(page, /testId="batch-watermark-opacity"/);
  assert.match(page, /testId="batch-watermark-text-size"/);
  assert.match(page, /testId="batch-watermark-rotation"/);
  assert.match(page, /data-control="scrubbable"/);
  assert.match(page, /SCRUB_THRESHOLD_PX = 4/);
  assert.match(page, /Math\.abs\(deltaX\) < SCRUB_THRESHOLD_PX/);
  assert.match(page, /event\.key === "ArrowUp" \|\| event\.key === "ArrowDown"/);
  assert.doesNotMatch(page, /data-testid=\{testId\}[^>]*type="range"/);
  assert.match(page, /aria-invalid=\{Boolean\(fieldError\)\}/);
  assert.match(page, /if \(event\.key === "Enter"\) event\.currentTarget\.blur\(\)/);
  assert.match(page, /kind, text, font_id: fontId, color, opacity, text_size: textSize, rotation/);

  const { hsvToHex, hexToHsv, normalizeHexColor, stepScrubbableValue, validateNumericDraft } = await loadRealComponent("/src/BatchWatermarkPage.jsx");
  for (const color of ["#FFFFFF", "#000000", "#2D6FE8"]) assert.deepEqual(normalizeHexColor(color), { valid: true, value: color });
  assert.equal(normalizeHexColor("blue").valid, false);
  const contract = { label: "透明度", min: 1, max: 100, step: 1 };
  assert.deepEqual(validateNumericDraft("37", contract), { valid: true, value: 37 });
  assert.deepEqual(validateNumericDraft("1", contract), { valid: true, value: 1 });
  assert.deepEqual(validateNumericDraft("100", contract), { valid: true, value: 100 });
  for (const invalid of ["", "abc", "0", "101", "37.5"]) assert.equal(validateNumericDraft(invalid, contract).valid, false);
  assert.equal(stepScrubbableValue(45, 3, contract), 48);
  assert.equal(stepScrubbableValue(100, 20, contract), 100);
  assert.equal(stepScrubbableValue(1, -20, contract), 1);
  const brandHsv = hexToHsv("#2D6FE8");
  assert.equal(hsvToHex(brandHsv.h, brandHsv.s, brandHsv.v), "#2D6FE8");
  assert.ok(brandHsv.h > 210 && brandHsv.h < 225);
  assert.equal((page.match(/const \[color, setColor\]/g) || []).length, 1);
  assert.doesNotMatch(page, /pickerColor|hexColor|taskColor/);
});

test("result area removes the duplicate file list and keeps only two delivery actions", () => {
  const page = read("src/BatchWatermarkPage.jsx");
  assert.equal((page.match(/<strong>\{completed\} 成功 \/ \{failed\} 失败 \/ \{total\} 总计<\/strong>/g) || []).length, 1);
  assert.equal((page.match(/>打开文件夹<\/button>/g) || []).length, 1);
  assert.equal((page.match(/>进入输出中心<\/button>/g) || []).length, 1);
  assert.match(page, /hdde-watermark-delivery-actions/);
  assert.equal((page.match(/className="hdde-secondary-action"[^>]*onClick[^>]*>[^<]*(?:打开文件夹|进入输出中心)/g) || []).length, 2);
  assert.doesNotMatch(page, /className="hdde-tertiary-action"[^>]*>进入输出中心/);
  assert.doesNotMatch(page, /全部处理完成|部分处理完成|result\.items\.map|hdde-watermark-result-items/);
  assert.doesNotMatch(page, /TOTAL=|COMPLETED=|FAILED=|返回处理中|返回处理中心|查看结果|查看输出目录/);
});

test("watermark parameters use compact paired controls without numeric sliders", () => {
  const page = read("src/BatchWatermarkPage.jsx");
  const css = read("src/index.css");
  assert.equal((page.match(/className="hdde-watermark-parameter-grid"/g) || []).length, 2);
  assert.match(page, /<ColorField value=\{color\}[\s\S]*?ScrubbableNumericField label="透明度"[\s\S]*?ScrubbableNumericField label="大小" value=\{textSize\}[\s\S]*?ScrubbableNumericField label="旋转角度"/);
  assert.doesNotMatch(page, /function SliderField|<SliderField/);
  assert.match(page, /平铺文字[\s\S]*?平铺不使用九宫格边距/);
  assert.match(css, /\.hdde-watermark-parameter-grid\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/);
  assert.match(css, /\.hdde-watermark-scrub-input\s*\{[^}]*min-height:\s*44px[^}]*border-radius:\s*8px[^}]*cursor:\s*ew-resize/);
});

test("margin UI mirrors nine-grid renderer semantics and hides ineffective tile controls", async () => {
  const page = read("src/BatchWatermarkPage.jsx");
  const { getMarginAvailability } = await loadRealComponent("/src/BatchWatermarkPage.jsx");
  const expected = {
    "top-left": [true, true], "top-center": [false, true], "top-right": [true, true],
    "middle-left": [true, false], center: [false, false], "middle-right": [true, false],
    "bottom-left": [true, true], "bottom-center": [false, true], "bottom-right": [true, true],
  };
  for (const [position, availability] of Object.entries(expected)) {
    const actual = getMarginAvailability(position);
    assert.deepEqual([actual.horizontal, actual.vertical], availability);
  }
  assert.deepEqual(getMarginAvailability("top-left", true), { horizontal: false, vertical: false });
  assert.match(page, /kind !== "text" \|\| !tile \? <>[\s\S]*?九宫格位置[\s\S]*?batch-watermark-margin-x[\s\S]*?batch-watermark-margin-y[\s\S]*?: null/);
  assert.match(page, /disabled=\{!marginAvailability\.horizontal\}/);
  assert.match(page, /disabled=\{!marginAvailability\.vertical\}/);
});

test("long filenames use a shrinkable information column and fixed remove action", () => {
  const css = read("src/index.css");
  assert.match(css, /\.hdde-watermark-file-list\s*\{[^}]*min-width:\s*0[^}]*grid-auto-rows:\s*max-content[^}]*overflow-x:\s*hidden/);
  assert.match(css, /\.hdde-watermark-file-list article\s*\{[^}]*min-width:\s*0[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+52px[^}]*overflow:\s*hidden/);
  assert.match(css, /\.hdde-watermark-file-main strong\s*\{[^}]*text-overflow:\s*ellipsis[^}]*white-space:\s*nowrap/);
  assert.match(css, /\.hdde-watermark-file-main small\s*\{[^}]*-webkit-line-clamp:\s*2[^}]*line-clamp:\s*2/);
  assert.match(css, /\.hdde-watermark-remove\s*\{[^}]*width:\s*48px[^}]*min-width:\s*48px/);
  assert.match(css, /\.hdde-watermark-preview\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)[^}]*overflow:\s*hidden/);
});

test("backend and formal startup register the dedicated API", () => {
  const backend = read("backend/batch_watermark_api.py");
  const main = read("main.py");
  assert.match(backend, /def register_batch_watermark_routes/);
  assert.match(backend, /"FULL_SUCCESS"/);
  assert.match(backend, /"PARTIAL_SUCCESS"/);
  assert.match(main, /register_batch_watermark_routes\(/);
});
