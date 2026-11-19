import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("../../src/CompressionPage.jsx", import.meta.url), "utf8");
const routes = await readFile(new URL("../../src/appRoutes.js", import.meta.url), "utf8");
const app = await readFile(new URL("../../src/App.jsx", import.meta.url), "utf8");
const styles = await readFile(new URL("../../src/index.css", import.meta.url), "utf8");

test("交付优化沿用原 compression 路由且没有新增一级入口", () => {
  assert.match(routes, /key: "compression"[\s\S]*name: "图片交付优化"[\s\S]*path: "\/compression"/);
  const compressionMount = app.match(/<CompressionPage\b[\s\S]*?\/>/)?.[0] || "";
  assert.match(compressionMount, /active=\{route\?\.key === "compression"\}/);
  assert.match(compressionMount, /continueResultId=\{compressionEntry\.resultId\}/);
  assert.match(compressionMount, /onNavigate=\{navigateTo\}/);
  assert.equal((routes.match(/path: "\/compression"/g) || []).length, 1);
});

test("结果页只展示单一智能择优结果及必要事实", () => {
  for (const label of ["智能择优结果", "处理结果", "最终格式", "最终体积", "分辨率", "节省比例", "选择原因"]) {
    assert.match(page, new RegExp(label));
  }
  assert.match(page, /data-testid="delivery-winner"/);
  assert.match(page, /data-testid=\{`delivery-winner-\$\{deliveryWinner\.scheme_id\}`\}/);
  assert.match(page, /data-testid="delivery-continue"/);
  assert.doesNotMatch(page, /select-candidate/);
  assert.doesNotMatch(page, /其他可选方案/);
  assert.doesNotMatch(page, /选择此方案/);
});

test("胜出与保留原图状态有明确文字且复用原交付动作", () => {
  assert.match(page, /deliveryWinner\.source_selected \? "保留原图" : "已择优"/);
  assert.match(page, /deliveryWinner\.source_selected \? "未找到更小且通过质量检查的结果，已保留原图" : Number\(deliveryWinner\.saved_percent\) > 0 \? "压缩完成" : "转换完成 · 文件未变小"/);
  assert.match(page, /deliveryWinner\.source_selected \? "保留原图，未生成新文件" : "已保存 1 份压缩成品"/);
  assert.match(page, /hasDeliveryOptions \? <button[^>]*data-testid="delivery-continue" onClick=\{continueToDelivery\}/);
  assert.match(styles, /\.hdde-single-winner \.hdde-delivery-option-grid/);
});

test("结果页展示质量门通过与 Source 回退语义", () => {
  assert.match(page, /data-testid="delivery-quality-proof"/);
  assert.match(page, /质量检查通过/);
  assert.match(page, /deliveryWinner\.source_selected \? "可继续使用原图。" : "压缩成品已通过质量和文件校验。"/);
  assert.match(styles, /\.hdde-lossless-proof/);
});
