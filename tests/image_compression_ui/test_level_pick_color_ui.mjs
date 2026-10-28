import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const page = fs.readFileSync(new URL("../../src/ColorCorrectionPage.jsx", import.meta.url), "utf8");
const detail = fs.readFileSync(new URL("../../src/TaskDetailPage.jsx", import.meta.url), "utf8");
const display = fs.readFileSync(new URL("../../src/productDisplay.js", import.meta.url), "utf8");
const app = fs.readFileSync(new URL("../../src/App.jsx", import.meta.url), "utf8");
const styles = fs.readFileSync(new URL("../../src/ColorCorrectionReference.css", import.meta.url), "utf8");

test("level pick is a third mode next to automatic and reference, automatic stays default", () => {
  assert.match(page, /useState\("automatic"\)/);
  assert.match(page, /自动校色<\/button>[\s\S]*参考图校色<\/button>[\s\S]*挑档校色<\/button>/);
  assert.match(page, /const levelMode = colorMode === "level"/);
  assert.match(page, /multiple=\{!singleSourceMode\}/);
  assert.match(page, /挑档校色每次处理一张图片/);
});

test("level pick asks the backend for four previews and runs only the chosen level", () => {
  assert.match(page, /\/api\/color-correction\/level-preview/);
  assert.match(page, /JSON\.stringify\(\{ source_token: item\.data\.source_token \}\)/);
  assert.match(page, /\/api\/color-correction\/level-run/);
  assert.match(page, /\{ preview_id: levelPreview\.preview_id, level: chosenLevel \}/);
  assert.match(page, /current_task_output_root = currentTaskOutputRoot/);
  // One preview yields at most one Result: it is cleared after a run and after preview errors.
  const run = page.slice(page.indexOf("const runLevelPick"), page.indexOf("const performResultAction"));
  assert.match(run, /setLevelPreview\(null\);[\s\S]*selected_level === "original"/);
  assert.match(run, /if \(\/预览\/\.test\(reason\.message \|\| ""\)\) setLevelPreview\(null\)/);
  assert.match(run, /onResultReady\(payload\.data\.task\.task_id\)/);
  assert.doesNotMatch(run, /strength|temperature|tint/);
});

test("choosing the original never shows a generated result", () => {
  const fn = page.slice(page.indexOf("export const LEVEL_PICK_LABELS"), page.indexOf("export function LevelPickOptions")).replace(/export /g, "");
  const context = vm.createContext({});
  vm.runInContext(`${fn}; this.levelPickSummary = levelPickSummary;`, context);
  assert.match(context.levelPickSummary("original"), /未生成新文件/);
  assert.match(context.levelPickSummary("medium"), /“中”档/);
  assert.match(context.levelPickSummary("strong"), /尺寸与构图不变/);
  assert.match(page, /使用原图（不生成新文件）/);
});

test("options show measurement, recommendation, zoom and block unsafe levels", () => {
  const options = page.slice(page.indexOf("export function LevelPickOptions"), page.indexOf("const API_BASE"));
  assert.match(options, /measurement\.summary/);
  assert.match(options, /measurement\.notice/);
  assert.match(options, /<em>建议<\/em>/);
  assert.match(options, /disabled=\{disabled \|\| !item\.selectable\}/);
  assert.match(options, /未通过安全检查，不可选/);
  assert.match(options, /onZoom\(item\)/);
  assert.match(page, /role="dialog" aria-modal="true"/);
  assert.match(styles, /\.hdde-level-grid[\s\S]*repeat\(4/);
  assert.match(styles, /@media \(max-width: 900px\)[\s\S]*repeat\(2/);
});

test("result page treats level pick as colour correction and still offers delivery", () => {
  assert.match(detail, /isLevelPick = rawMode === "LEVEL_PICK_COLOR_CORRECTION"/);
  assert.match(detail, /isColorCorrection = isReferenceCorrection \|\| isLevelPick \|\|/);
  assert.match(detail, /persistedReviewConfirmed = persistedReviewStatusConfirmed && !isLevelPick/);
  assert.match(detail, /persistedDeliveryCompleted = persistedReviewStatusConfirmed/);
  assert.match(detail, /isColorCorrection && !isLevelPick && !persistedReviewConfirmed && !sessionReviewConfirmed/);
  assert.match(detail, /!persistedReviewConfirmed && !persistedDeliveryCompleted \? <button/);
  assert.match(detail, /交付所选结果/);
  assert.match(detail, /已选定档位，待交付/);
  assert.match(display, /LEVEL_PICK_COLOR_CORRECTION"\) return "挑档校色"/);
  assert.match(app, /"LEVEL_PICK_COLOR_CORRECTION", "color_correction"\]\.includes\(taskContext\?\.mode\)/);
});
