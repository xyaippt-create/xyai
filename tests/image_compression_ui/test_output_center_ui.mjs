import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { APP_ROUTES } from "../../src/appRoutes.js";
import { FEATURE_STATUSES } from "../../src/platformStatus.js";

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(currentDirectory, "..", "..");
const page = fs.readFileSync(path.join(root, "src", "OutputCenterPage.jsx"), "utf8");
const app = fs.readFileSync(path.join(root, "src", "App.jsx"), "utf8");
const backend = fs.readFileSync(path.join(root, "backend", "image_compression_api.py"), "utf8");
const styles = fs.readFileSync(path.join(root, "src", "index.css"), "utf8");

test("output center is a real enabled route and its compare route stays out of navigation", () => {
  const outputRoute = APP_ROUTES.find((route) => route.key === "outputs");
  const compareRoute = APP_ROUTES.find((route) => route.key === "output-compare");
  assert.equal(outputRoute?.status, FEATURE_STATUSES.ENABLED);
  assert.equal(outputRoute?.implementationType, "existing");
  assert.equal(compareRoute?.status, FEATURE_STATUSES.ENABLED);
  assert.equal(compareRoute?.showInNavigation, false);
  assert.match(app, /route\.key === "outputs"/);
  assert.match(app, /route\.key === "output-compare"/);
  assert.doesNotMatch(app, /route\.key === "outputs"[\s\S]{0,300}<FeaturePlaceholderPage/);
});

test("output center consumes real indexed items and never accepts a browser filesystem path", () => {
  assert.match(page, /requestJson\("\/api\/output-center\/items"\)/);
  assert.match(page, /encodeURIComponent\(item\.id\)/);
  assert.match(page, /performAction\(selected, "open-folder"\)/);
  assert.match(page, /performAction\(selected, "open"\)/);
  assert.doesNotMatch(page, /output_path|source_path|input_path/);
  assert.doesNotMatch(page, /mock|placeholder|示例数据|样例数据/i);
  assert.match(backend, /formal_contract_directories_only/);
  assert.match(backend, /recursive_scan": False/);
  assert.match(backend, /output_center_index/);
  assert.doesNotMatch(backend, /(?:rglob|os\.walk)\([^\n]*output_center/i);
});

test("categories and comparison are derived from real item contracts", () => {
  assert.match(page, /data\.categories/);
  assert.match(page, /item\.processing_type === activeCategory/);
  assert.match(page, /selected\.compare_available/);
  assert.match(page, /进入对比质检/);
  assert.match(page, /返回输出中心/);
  assert.match(page, /SliderCompareStage/);
  assert.match(app, /returnToOutputs \? "返回输出中心" : "返回批次"/);
});

test("output center keeps the 12px product readability floor and shared theme tokens", () => {
  const start = styles.indexOf("/* Output center:");
  assert.ok(start >= 0);
  const block = styles.slice(start);
  assert.doesNotMatch(block, /font-size:\s*(?:[0-9]|1[01])px/);
  assert.match(block, /var\(--content-background\)/);
  assert.match(block, /var\(--card-background\)/);
  assert.match(block, /var\(--brand-primary\)/);
  assert.match(block, /focus-visible/);
});
