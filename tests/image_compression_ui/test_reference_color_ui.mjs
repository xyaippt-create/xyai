import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const page = fs.readFileSync(new URL("../../src/ColorCorrectionPage.jsx", import.meta.url), "utf8");
const detail = fs.readFileSync(new URL("../../src/TaskDetailPage.jsx", import.meta.url), "utf8");

test("protection API error preserves the failed task without creating a successful Result", async () => {
  const data = { task: { status: "failed", d3_status: "PROTECTION_BLOCKED", d3_final_action: "REVIEW_REQUIRED", output_selected: "NONE", result_id: "" }, result: null };
  const context = vm.createContext({
    API_BASE: "", fetch: async () => ({ ok: false, status: 422, json: async () => ({
      success: false, code: "PROTECTION_BLOCKED", message: "本次未采用参考调整，已保留原图。", data,
    }) }),
  });
  const start = page.indexOf("const COLOR_PROTECTION_TITLE");
  vm.runInContext(page.slice(start, page.indexOf("function formatBytes", start)), context);
  await assert.rejects(context.requestJson("/api/color-correction/reference-run"), (error) => {
    assert.equal(error.taskData, data);
    assert.equal(error.taskData.result, null);
    assert.match(error.message, /已保留原图/);
    assert.doesNotMatch(error.message, /PROTECTION_BLOCKED|校色成功/);
    return true;
  });
  assert.equal(context.isColorProtectionBlocked(data.task, data.result), true);
  assert.match(context.colorFailureMessage(data.task, data.result), /未进行自动校正/);
  const startCatch = page.indexOf("setTaskData(reason.taskData || null)");
  assert.ok(startCatch > 0);
  assert.match(page.slice(startCatch, page.indexOf("const performResultAction", startCatch)), /finally\s*\{\s*setBusy\(false\)/);
});

test("reference mode keeps automatic default and separates intake roles and payload", () => {
  assert.match(page, /useState\("automatic"\)/);
  // S66 option A: the reference tab uses the level-pick preview with the reference token; the old reference-run is no longer called.
  assert.match(page, /const pickMode = levelMode \|\| referenceMode/);
  assert.match(page, /referenceMode && !referenceInput\?\.data\?\.source_token/);
  assert.match(page, /\{ source_token: item\.data\.source_token, reference_source_token: referenceInput\.data\.source_token \}/);
  assert.doesNotMatch(page, /\/api\/color-correction\/reference-run/);
  assert.doesNotMatch(page, /target_source_token/);
  assert.doesNotMatch(page, /开始参考图校色/);
  assert.match(page, /pickMode && levelPreview && !completed/);
  assert.match(page, /结果会采用参考图的白/);
  // A level locked by an unusable reference must not be blamed on the safety check.
  assert.match(page, /measurement\.reference_usable === false \? "参考图不可用，不可选" : "未通过安全检查，不可选"/);
  assert.match(page, /REFERENCE_LEVEL_PICK_COLOR_CORRECTION/);
  // Reference and level-pick modes both take exactly one source image.
  assert.match(page, /const singleSourceMode = referenceMode \|\| levelMode/);
  assert.match(page, /multiple=\{!singleSourceMode\}/);
  assert.match(page, /setReferenceInput\(null\)/);
  assert.match(page, /替换参考图/);
  assert.match(page, /failure.taskData = payload\?\.data\?\.task/);
  assert.doesNotMatch(page, /match_strength|type="range"[^>]*(temperature|tint|saturation)/);
});

test("reference status text never pretends original or review is accepted correction", () => {
  const fn = page.slice(page.indexOf("export function referenceResultSummary"), page.indexOf("export function ReferenceComparison")).replace("export ", "");
  const context = vm.createContext({});
  vm.runInContext(fn, context);
  assert.match(context.referenceResultSummary({ result_action: "ACCEPT_ORIGINAL" }, "FULL_MATCH"), /未采用调整结果.*保留目标原图/);
  assert.match(context.referenceResultSummary({ result_action: "REVIEW_REQUIRED" }, "FULL_MATCH"), /尚未获得自动交付权限/);
  for (const status of ["FULL_MATCH", "COLOR_ONLY_MATCH", "LIMITED_MATCH", "INSUFFICIENT_EVIDENCE"])
    assert.doesNotMatch(context.referenceResultSummary({}, status), /FULL_MATCH|LIMITED_MATCH|INSUFFICIENT|100%/);
});

test("unified Result page recognizes reference mode without replacing delivery authority", () => {
  assert.match(detail, /isReferenceCorrection.*REFERENCE_COLOR_CORRECTION/);
  assert.match(detail, /isColorCorrection = isReferenceCorrection \|\|/);
  // Reference level-pick Results reuse level-pick delivery semantics and the reference comparison.
  assert.match(detail, /isLevelPick = isReferenceLevelPick \|\|/);
  assert.match(detail, /showReferenceCompare = isReferenceCorrection \|\| isReferenceLevelPick/);
  assert.match(detail, /\{showReferenceCompare \? <section/);
  assert.match(detail, /<ReferenceComparison/);
  assert.match(detail, /referenceDetails\?\.ui\?\.reference_preview_url/);
  assert.match(detail, /candidate=\{acceptOriginal \?/);
  assert.match(detail, /onCandidateError=.*status: "unavailable"/);
  assert.match(detail, /\/api\/smart-delivery\/preflight/);
  assert.match(detail, /result_ids: \[resultId\]/);
  assert.doesNotMatch(detail, /result_ids:.*reference/);
});
