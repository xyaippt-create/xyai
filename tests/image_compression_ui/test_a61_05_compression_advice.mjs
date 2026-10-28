import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  COMPRESSION_ADVICE_POLICY,
  buildCompressionAdvice,
} from "../../src/compressionAdvice.js";

function result(overrides = {}) {
  return {
    source_format: "PNG",
    output_format: "PNG",
    source_size_bytes: 2 * 1024 * 1024,
    output_size_bytes: 1_990_000,
    source_dimensions: { width: 1600, height: 1200 },
    alpha_details: { alpha_present: false },
    ...overrides,
  };
}

function adviceFor(resultValue, winner = { source_selected: false, format: "PNG", file_size: 1_990_000 }) {
  return buildCompressionAdvice({
    result: resultValue,
    winner,
    operationMode: "DELIVERY_OPTIMIZATION",
    targetFormat: "PRESERVE_FORMAT",
  });
}

test("preserve-format PNG with limited benefit offers user-controlled JPG and WebP directions", () => {
  const advice = adviceFor(result());
  assert.equal(advice.kind, "LIMITED_PNG");
  assert.deepEqual(advice.actions.map((item) => item.targetFormat), ["JPEG", "WEBP"]);
  assert.match(advice.detail, /实际结果以重新处理后的质量检查为准/);
  assert.doesNotMatch(`${advice.title}${advice.detail}`, /预计|一定更小|\d+\s*(?:KB|MB|%)/i);
});

test("transparent PNG only offers the transparency-preserving WebP direction", () => {
  const advice = adviceFor(result({ alpha_details: { alpha_present: true } }));
  assert.deepEqual(advice.actions.map((item) => item.targetFormat), ["WEBP"]);
  assert.match(advice.detail, /保留透明区域/);
});

test("a useful same-format winner and every manual target stay quiet", () => {
  assert.equal(adviceFor(result({ output_size_bytes: 900_000 }), { source_selected: false, format: "PNG", file_size: 900_000 }), null);
  assert.equal(buildCompressionAdvice({
    result: result(),
    winner: { source_selected: true, format: "PNG" },
    operationMode: "DELIVERY_OPTIMIZATION",
    targetFormat: "JPEG",
  }), null);
});

test("KEEP_ORIGINAL explains the outcome without inventing cross-format candidates", () => {
  const webpAdvice = adviceFor(result({ source_format: "WEBP", output_format: "WEBP" }), {
    source_selected: true,
    format: "WEBP",
  });
  assert.equal(webpAdvice.kind, "KEEP_ORIGINAL");
  assert.deepEqual(webpAdvice.actions, []);
  assert.match(webpAdvice.title, /未生成更小且符合质量要求的新文件/);

  const jpgAdvice = adviceFor(result({ source_format: "JPEG", output_format: "JPEG" }), {
    source_selected: true,
    format: "JPG",
  });
  assert.deepEqual(jpgAdvice.actions.map((item) => item.targetFormat), ["WEBP"]);
  assert.match(jpgAdvice.detail, /不保证一定更小/);
});

test("advice actions only prepare the existing target-format control", () => {
  const pageSource = readFileSync(new URL("../../src/CompressionPage.jsx", import.meta.url), "utf8");
  const appSource = readFileSync(new URL("../../src/App.jsx", import.meta.url), "utf8");
  const start = pageSource.indexOf("const prepareSuggestedFormat");
  const end = pageSource.indexOf("const openOutputFolder", start);
  const actionBlock = pageSource.slice(start, end);
  assert.match(actionBlock, /setTargetFormat\(nextTargetFormat\)/);
  assert.match(actionBlock, /resetResult\(\)/);
  assert.doesNotMatch(actionBlock, /requestJson|fetch\s*\(/);
  assert.match(pageSource, /onTaskContextChange\?\.\(\{/);
  // D61 adds current color-task feedback alongside the existing compression route.
  assert.match(appSource, /FEEDBACK_TASK_ROUTES = new Set\(\[\.\.\.TASK_ROUTES, "compression", "color-correction"\]\)/);
  assert.match(appSource, /FEEDBACK_TASK_ROUTES\.has\(route\?\.key\)/);
  assert.equal(COMPRESSION_ADVICE_POLICY.systemAutoOnly, true);
  assert.equal(COMPRESSION_ADVICE_POLICY.autoConversion, false);
});
