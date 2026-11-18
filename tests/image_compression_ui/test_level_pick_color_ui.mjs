import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const page = fs.readFileSync(new URL("../../src/ColorCorrectionPage.jsx", import.meta.url), "utf8");
const detail = fs.readFileSync(new URL("../../src/TaskDetailPage.jsx", import.meta.url), "utf8");
const display = fs.readFileSync(new URL("../../src/productDisplay.js", import.meta.url), "utf8");
const app = fs.readFileSync(new URL("../../src/App.jsx", import.meta.url), "utf8");
const styles = fs.readFileSync(new URL("../../src/ColorCorrectionReference.css", import.meta.url), "utf8");

test("level pick is the default and first mode, then reference and automatic (S77)", () => {
  assert.match(page, /useState\("level"\)/);
  assert.match(page, /挑档校色<\/button>[\s\S]*参考图校色<\/button>[\s\S]*自动校色<\/button>/);
  assert.match(page, /colorMode === "automatic" \? <p className="hdde-color-mode-note" data-testid="color-auto-note">只在把握很大时才修改，多数图片会保留原图；想自己决定强度，请用挑档校色。<\/p> : null/);
  assert.match(page, /description="修正偏黄、偏蓝等偏色，只调整现有像素，不改变构图和内容。"/);
  assert.match(styles, /\.hdde-color-mode-note \{[\s\S]*font-size: 12px/);
  assert.match(page, /const levelMode = colorMode === "level"/);
  assert.match(page, /multiple=\{!singleSourceMode\}/);
  assert.match(page, /挑档校色每次处理一张图片/);
});

test("level pick asks the backend for four previews and runs only the chosen level", () => {
  assert.match(page, /\/api\/color-correction\/level-preview/);
  assert.match(page, /: \{ source_token: item\.data\.source_token \}\)/);
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
  assert.match(detail, /isLevelPick = isReferenceLevelPick \|\| rawMode === "LEVEL_PICK_COLOR_CORRECTION"/);
  assert.match(detail, /isColorCorrection = isReferenceCorrection \|\| isLevelPick \|\|/);
  assert.match(detail, /persistedReviewConfirmed = persistedReviewStatusConfirmed && !isLevelPick/);
  assert.match(detail, /persistedDeliveryCompleted = persistedReviewStatusConfirmed/);
  assert.match(detail, /isColorCorrection && !isLevelPick && !persistedReviewConfirmed && !sessionReviewConfirmed/);
  assert.match(detail, /!persistedReviewConfirmed && !persistedDeliveryCompleted \? <button/);
  assert.match(detail, /交付所选结果/);
  assert.match(detail, /已选定档位，待交付/);
  assert.match(display, /LEVEL_PICK_COLOR_CORRECTION"\) return "挑档校色"/);
  assert.match(app, /"LEVEL_PICK_COLOR_CORRECTION", "REFERENCE_LEVEL_PICK_COLOR_CORRECTION", "color_correction"\]\.includes\(taskContext\?\.mode\)/);
});

test("S74 white point: picker only in level mode, sends neutral_point, keeps preview on refusal", () => {
  assert.match(page, /pointTools=\{levelMode \? \{/);
  assert.match(page, /neutral_point: point/);
  assert.match(page, /点选白点/);
  assert.match(page, /取消白点，改回自动判断/);
  const pointPreview = page.slice(page.indexOf("const createPointPreview"), page.indexOf("const createLevelPreview"));
  assert.match(pointPreview, /if \(!item \|\| referenceMode\) return;/);
  assert.doesNotMatch(pointPreview, /clearResult\(\)|setLevelPreview\(null\)/);
  assert.match(pointPreview, /setError\(reason\.message\)/);
  assert.match(page, /neutralPickerOpen && levelMode && levelPreview/);
  assert.match(styles, /\.hdde-neutral-picker-frame img[\s\S]*cursor: crosshair/);
});

test("S74 click position maps to 0..1 of the displayed image and is clamped", () => {
  const start = page.indexOf("export function neutralPointFromClick");
  const end = page.indexOf("export function NeutralPointPicker");
  const source = page.slice(start, end).replace("export function", "function");
  const pick = vm.runInNewContext(`${source}; neutralPointFromClick`);
  const target = { getBoundingClientRect: () => ({ left: 100, top: 50, width: 400, height: 200 }) };
  assert.deepEqual({ ...pick({ currentTarget: target, clientX: 300, clientY: 100 }) }, { x: 0.5, y: 0.25 });
  assert.deepEqual({ ...pick({ currentTarget: target, clientX: 900, clientY: 0 }) }, { x: 1, y: 0 });
  assert.equal(pick({ currentTarget: { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) }, clientX: 1, clientY: 1 }), null);
});

test("S75 group level pick: representative previews, the group runs as one batch", () => {
  assert.match(page, /const singleSourceMode = referenceMode;/);
  assert.match(page, /const groupMode = levelMode && selectedItems\.length > 1;/);
  assert.match(page, /selectedItems\.find\(\(item\) => item\.id === representativeId\) \|\| selectedItems\[0\]/);
  const run = page.slice(page.indexOf("const runLevelPick"), page.indexOf("const performResultAction"));
  assert.match(run, /if \(groupMode && chosenLevel !== "original"\)/);
  assert.match(run, /level_pick: \{ preview_id: levelPreview\.preview_id, level: chosenLevel \}/);
  assert.match(run, /"\/api\/color-correction\/batches"/);
  assert.match(run, /onOpenProcessing\(batchPayload\.data\.batch_id\)/);
  const preview = page.slice(page.indexOf("const createLevelPreview"), page.indexOf("const runLevelPick"));
  assert.match(preview, /levelMode \? representativeItem/);
  assert.match(page, /const createPointPreview = async \(point\) => \{\s+const item = representativeItem;/);
  assert.match(page, /设为代表图/);
  assert.match(page, /按“\$\{LEVEL_PICK_LABELS\[chosenLevel\] \|\| ""\}”档处理整组/);
  assert.match(page, /除代表图外的结果需在处理中心复核后才能交付/);
  assert.doesNotMatch(page, /setColorMode\("level"\);[^}]*slice\(0, 1\)/);
  assert.match(styles, /\.hdde-color-representative \{[\s\S]*font-size: 12px/);
});

test("S75 processing centre names group level-pick batches and rows correctly", () => {
  const dashboard = fs.readFileSync(new URL("../../src/DashboardPage.jsx", import.meta.url), "utf8");
  const row = dashboard.slice(dashboard.indexOf("function colorBatchTaskToQueueItem"), dashboard.indexOf("function colorBatchTaskToQueueItem") + 900);
  assert.match(row, /mode: task\.operation_mode \|\| PROCESSING_MODE_COLOR_CORRECTION/);
  assert.match(dashboard, /normalized === "LEVEL_PICK_COLOR_CORRECTION"\) return \{ label: "挑档校色"/);
  assert.match(dashboard, /activeColorBatch\.level_pick\s*\?\s*`按代表图选定的“\$\{activeColorBatch\.level_pick\.label\}”档/);
});

test("S78 single-image level pick checks several levels and makes them as one batch", () => {
  assert.match(page, /const multiLevelMode = levelMode && !groupMode;/);
  assert.match(page, /type=\{multiChosen \? "checkbox" : "radio"\}/);
  assert.match(page, /if \(level === "original"\) next = \["original"\];/);
  const run = page.slice(page.indexOf("const runLevelPick"), page.indexOf("const performResultAction"));
  assert.match(run, /if \(multiLevels\.length > 1\)/);
  assert.match(run, /level_pick: \{ preview_id: levelPreview\.preview_id, levels: multiLevels \}/);
  assert.match(run, /onOpenProcessing\(multiPayload\.data\.batch_id\)/);
  assert.match(page, /生成所选 \$\{multiLevels\.length\} 档/);
  assert.match(page, /multiChosen=\{multiLevelMode \? chosenLevels : null\}/);
  const dashboard = fs.readFileSync(new URL("../../src/DashboardPage.jsx", import.meta.url), "utf8");
  assert.match(dashboard, /activeColorBatch\.level_pick\?\.multi_level\s*\?\s*`同一张图按所选/);
});
