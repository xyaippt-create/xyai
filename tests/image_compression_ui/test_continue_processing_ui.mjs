import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const outputCenter = fs.readFileSync(new URL("../../src/OutputCenterPage.jsx", import.meta.url), "utf8");
const compression = fs.readFileSync(new URL("../../src/CompressionPage.jsx", import.meta.url), "utf8");
const retouch = fs.readFileSync(new URL("../../src/LocalRetouchPage.jsx", import.meta.url), "utf8");
const processing = fs.readFileSync(new URL("../../src/DashboardPage.jsx", import.meta.url), "utf8");
const color = fs.readFileSync(new URL("../../src/ColorCorrectionPage.jsx", import.meta.url), "utf8");
const watermark = fs.readFileSync(new URL("../../src/BatchWatermarkPage.jsx", import.meta.url), "utf8");
const app = fs.readFileSync(new URL("../../src/App.jsx", import.meta.url), "utf8");
const styles = fs.readFileSync(new URL("../../src/index.css", import.meta.url), "utf8");

test("输出中心瞬时展示固定顺序的五个继续处理器", () => {
  const labels = ["画质增强", "颜色校正", "图片压缩", "瑕疵修复", "添加水印"];
  let previousIndex = -1;
  for (const label of labels) {
    const index = outputCenter.indexOf(`label: "${label}"`);
    assert.ok(index > previousIndex, `${label} 应固定存在且顺序正确`);
    previousIndex = index;
  }
  assert.match(outputCenter, /pendingContinueProcessors\(\)/);
  assert.match(outputCenter, /continue-eligibility/);
  assert.match(outputCenter, /continueEligibilityCacheRef/);
  assert.match(outputCenter, /status: "CHECKING"/);
  assert.match(outputCenter, /processor\.status !== "AVAILABLE"/);
  assert.match(outputCenter, /data-status=\{processor\.status\}/);
  assert.match(outputCenter, /data-testid="output-center-continue-action"/);
  assert.match(outputCenter, /data-testid="continue-processing-dialog"/);
  assert.doesNotMatch(outputCenter, /\/api\/image-compression\/capabilities/);
  assert.doesNotMatch(outputCenter, /\/api\/local-retouch\/capabilities/);
  assert.doesNotMatch(outputCenter, /\/api\/batch-watermark\/capabilities/);
});

test("跨页只传 Result 身份，不把路径或 URL 伪装成上传", () => {
  assert.match(outputCenter, /continue_result=\$\{encodeURIComponent\(resultId\)\}/);
  assert.match(app, /get\("continue_result"\)/);
  assert.match(compression, /\/api\/image-compression\/intake-result/);
  assert.match(color, /\/api\/color-correction\/intake-result/);
  assert.match(retouch, /\/api\/local-retouch\/intake-result/);
  assert.match(compression, /JSON\.stringify\(\{ result_id: continueResultId \}\)/);
  assert.match(color, /JSON\.stringify\(\{ result_id: continueResultId \}\)/);
  assert.match(retouch, /JSON\.stringify\(\{ result_id: continueResultId \}\)/);
  assert.match(processing, /formData\.append\("result_id", item\.sourceResultId\)/);
  assert.match(watermark, /formData\.append\("result_ids_json"/);
  assert.match(watermark, /\/api\/result-assets\//);
  assert.doesNotMatch(outputCenter, /output_path|source_path|input_path/);
});

test("继续处理入口具备明确的独立任务和原结果不变说明", () => {
  assert.match(outputCenter, /新建独立任务/);
  assert.match(outputCenter, /将当前成品作为新任务继续处理，原文件不会被覆盖。/);
  assert.match(outputCenter, /aria-modal="true"/);
  assert.match(outputCenter, /event\.key === "Escape"/);
  assert.match(styles, /\.hdde-continue-dialog-backdrop\s*\{[\s\S]*?position:\s*fixed/);
  assert.match(styles, /\.hdde-continue-dialog__options > button\s*\{[\s\S]*?min-height:\s*74px/);
});

test("目标页明确显示已有成品来源并保留独立 intake 生命周期", () => {
  assert.match(compression, /source_origin === "EXISTING_RESULT" \? "已有成品预览"/);
  assert.match(retouch, /来自已有成品/);
  assert.match(compression, /handledContinueResultRef/);
  assert.match(color, /handledContinueResultRef/);
  assert.match(retouch, /handledContinueResultRef/);
  assert.match(compression, /setState\(FILE_SELECTION_STATES\.INTAKE_PENDING\)/);
  assert.match(retouch, /建立新的本地工作副本/);
});
