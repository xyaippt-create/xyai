import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const page = fs.readFileSync(path.join(root, "src/ImageDiagnosisPage.jsx"), "utf8");
const app = fs.readFileSync(path.join(root, "src/App.jsx"), "utf8");
const routes = fs.readFileSync(path.join(root, "src/appRoutes.js"), "utf8");
const dashboard = fs.readFileSync(path.join(root, "src/DashboardPage.jsx"), "utf8");
const styles = fs.readFileSync(path.join(root, "src/index.css"), "utf8");

test("image diagnosis is a formal top-level route with the frozen feature identity", () => {
  assert.match(routes, /key: "image-diagnosis"[\s\S]*name: "图片诊断"[\s\S]*path: "\/image-diagnosis"/);
  assert.doesNotMatch(routes.match(/key: "image-diagnosis"[\s\S]*?\n  },/)?.[0] || "", /showInNavigation: false/);
  assert.match(page, /\/api\/image-diagnosis\/tasks/);
  assert.doesNotMatch(page, /laplacian|variance|estimated_noise_sigma\s*[<>]=?|highlight_ratio\s*[<>]=?/i);
  assert.match(page, /sourceFeature="image_diagnosis"/);
});

test("result presentation keeps conclusion issues evidence and D1 recommendation unchanged", () => {
  for (const contract of [
    "诊断结论",
    "首要建议",
    "关键问题",
    "诊断依据",
    "图片事实",
    "查看技术证据与指标",
    "无法可靠判断",
    "当前格式不适用",
    'data-testid="diagnosis-primary-action"',
  ]) assert.ok(page.includes(contract), `missing D2 presentation contract: ${contract}`);
  assert.match(page, /recommendation\?\.primary_action/);
  assert.match(page, /recommendation\.secondary_actions/);
  assert.match(page, /recommendation\?\.reasons/);
  assert.doesNotMatch(page, /综合评分|画质\s*\d+\s*分|自动执行/);
});

test("all allowed recommendations map to existing formal routes without auto-running", () => {
  const mappings = [
    ['"4K高清增强"', '"/processing?mode=4k_v1"'],
    ['"1080P安全增强"', '"/processing?mode=safe_1080p_beta"'],
    ['"1080P标准增强"', '"/processing?mode=standard"'],
    ['"颜色校正"', '"/color-correction"'],
    ['"图片压缩"', '"/compression"'],
  ];
  for (const [action, target] of mappings) {
    assert.ok(app.includes(action), `missing action: ${action}`);
    assert.ok(app.includes(target), `missing target: ${target}`);
  }
  assert.match(app, /sourceHandoff/);
  assert.match(dashboard, /initialSourceFile/);
  assert.match(dashboard, /\/image-diagnosis\?task_id=/);
  assert.match(page, /\/api\/image-diagnosis\/tasks\/\$\{encodeURIComponent\(taskId\)\}/);
  assert.doesNotMatch(page, /\/api\/upload|\/api\/color-correction\/run|\/api\/image-compression\/run/);
});

test("structured diagnosis tasks do not invent image result URLs", () => {
  assert.match(dashboard, /task\?\.result_file \|\| task\?\.output_path \|\| result\?\.result_file \|\| result\?\.output_path/);
  assert.match(dashboard, /featureKey: task\?\.feature_key/);
  assert.match(dashboard, /\["color_correction", "image_diagnosis"\]\.includes\(item\?\.taskFamily\)/);
  assert.match(dashboard, /item\.taskFamily !== "image_diagnosis"/);
  assert.match(styles, /\.hdde-diagnosis-layout/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(styles, /\.hdde-diagnosis-page button:focus-visible/);
});
