import assert from "node:assert/strict";
import test from "node:test";

import { buildCompressionRequestPlan } from "../../src/compressionParams.js";
import {
  LONG_IMAGE_CONFIRMATION_TEXT,
  PREVIEW_MODES,
  classifyLongImageWidth,
  comparisonMode,
  defaultPreviewMode,
  defaultUploadLimits,
  estimateOutputDimensions,
  isLongImage,
  longImageFeedbackFields,
  longImageReviewChecklist,
  noCandidateUiState,
  normalizedScrollPosition,
  previewModeContract,
  scrollTopForRatio,
} from "../../src/longImagePolicy.js";

const longJpeg = { format: "JPEG", width: 1266, height: 9088 };
const plan = (overrides = {}) => buildCompressionRequestPlan({
  fileInfo: longJpeg,
  mode: "RESIZE_REDUCTION",
  resizeStrategy: "short_side",
  shortSidePreset: "1080",
  customShortSide: "",
  ratioPreset: "0.75",
  customRatio: "65",
  customDimension: "",
  uploadLimits: defaultUploadLimits(longJpeg),
  ...overrides,
});

test("长图识别覆盖样本并排除普通比例", () => {
  assert.equal(isLongImage(1266, 9088), true);
  assert.equal(isLongImage(3200, 4000), false);
  assert.equal(isLongImage(2250, 4000), false);
  assert.equal(isLongImage(5000, 1200), false);
});

test("长图默认适合宽度且普通图默认全图概览", () => {
  assert.equal(defaultPreviewMode(longJpeg), PREVIEW_MODES.FIT_WIDTH);
  assert.equal(defaultPreviewMode({ width: 1200, height: 900 }), PREVIEW_MODES.OVERVIEW);
});

test("100%真实像素模式不使用contain逻辑", () => {
  const contract = previewModeContract(PREVIEW_MODES.ACTUAL_SIZE);
  assert.equal(contract.usesContain, false);
  assert.equal(contract.oneImagePixelPerCssPixel, true);
});

test("只有全图概览使用contain逻辑", () => {
  assert.equal(previewModeContract(PREVIEW_MODES.OVERVIEW).usesContain, true);
  assert.equal(previewModeContract(PREVIEW_MODES.FIT_WIDTH).usesContain, false);
});

test("长图使用单栏切换而非左右窄栏", () => {
  assert.equal(comparisonMode(longJpeg), "single-toggle");
  assert.equal(comparisonMode({ width: 1200, height: 900 }), "side-by-side");
});

test("原图结果切换可保持归一化滚动位置", () => {
  const ratio = normalizedScrollPosition(450, 1200, 300);
  assert.equal(ratio, 0.5);
  assert.equal(scrollTopForRatio(ratio, 2400, 600), 900);
});

test("不同高度的预览容器可由同一比例独立计算位置", () => {
  assert.equal(scrollTopForRatio(0.5, 2400, 600), 900);
  assert.equal(scrollTopForRatio(0.5, 1800, 400), 700);
  assert.equal(normalizedScrollPosition(900, 2400, 600), 0.5);
  assert.equal(normalizedScrollPosition(700, 1800, 400), 0.5);
});

test("顶部中部底部锚点的滚动比例稳定", () => {
  assert.equal(scrollTopForRatio(0, 2000, 500), 0);
  assert.equal(scrollTopForRatio(0.5, 2000, 500), 750);
  assert.equal(scrollTopForRatio(1, 2000, 500), 1500);
});

test("无候选不复制原图且不显示复核和打开目录", () => {
  const state = noCandidateUiState({ output_created: false, candidate_delivery_role: "NONE", visual_review_status: "PENDING" });
  assert.equal(state.hasCandidate, false);
  assert.equal(state.showComparison, false);
  assert.equal(state.showReview, false);
  assert.equal(state.showOpenFolder, false);
});

test("无需处理的原图不冒充已确认候选结果", () => {
  const state = noCandidateUiState({
    technical_status: "NO_PROCESSING_NEEDED",
    output_created: false,
    candidate_delivery_role: "SOURCE_NO_PROCESSING",
    delivery_gate_status: "DELIVERY_READY",
    visual_review_status: "NOT_REQUIRED",
  });

  assert.equal(state.sourceNoProcessing, true);
  assert.equal(state.candidateDeliveryReady, false);
  assert.equal(state.hasCandidate, false);
  assert.equal(state.showOpenFolder, false);
  assert.match(state.message, /原图已满足要求/);
});

test("JPEG无损被执行前安全阻止且模式不自动切换", () => {
  const request = plan({ mode: "LOSSLESS_COMPRESSION" });
  assert.equal(request.valid, false);
  assert.equal(request.failureCode, "JPEG_COEFFICIENT_LOSSLESS_NOT_IMPLEMENTED");
});

test("长图上传适配默认最大高度为空", () => {
  assert.deepEqual(defaultUploadLimits(longJpeg), { maxWidth: "1080", maxHeight: "", maxSize: "2", sizeUnit: "MB" });
});

test("长图宽度预设和尺寸预估正确", () => {
  assert.deepEqual(estimateOutputDimensions(1266, 9088, { target_short_side: 1080 }), { width: 1080, height: 7753, scale: 1080 / 1266 });
  assert.equal(plan({ shortSidePreset: "900" }).estimatedOutputWidth, 900);
  assert.equal(plan({ shortSidePreset: "900" }).estimatedOutputHeight, 6461);
});

test("高度1080导致约150宽并被硬阻止", () => {
  const request = plan({
    mode: "UPLOAD_ADAPTATION",
    uploadLimits: { maxWidth: "", maxHeight: "1080", maxSize: "2", sizeUnit: "MB" },
  });
  assert.equal(request.estimatedOutputWidth, 150);
  assert.equal(request.valid, false);
  assert.equal(request.longImageRiskLevel, "BLOCKED");
});

test("长图宽度风险四档和二次确认正确", () => {
  assert.equal(classifyLongImageWidth(599).blocked, true);
  assert.equal(classifyLongImageWidth(700).confirmationRequired, true);
  assert.equal(classifyLongImageWidth(800).level, "STRONG_WARNING");
  assert.equal(classifyLongImageWidth(950).level, "REVIEW_NOTICE");
  assert.equal(classifyLongImageWidth(1080).level, "LOWER_RISK");
  const confirmation = plan({ resizeStrategy: "ratio", ratioPreset: "0.5" });
  assert.equal(confirmation.valid, false);
  assert.equal(confirmation.confirmationText, LONG_IMAGE_CONFIRMATION_TEXT);
  assert.equal(plan({ resizeStrategy: "ratio", ratioPreset: "0.5", longImageRiskConfirmed: true }).valid, true);
});

test("长图风险提示与人工复核检查项完整", () => {
  assert.match(plan({ shortSidePreset: "900" }).message, /100%模式/);
  const checklist = longImageReviewChecklist();
  for (const item of ["中段最小文字", "Logo", "二维码"]) assert.ok(checklist.includes(item));
});

test("清除任务可恢复默认长图预览状态", () => {
  assert.equal(defaultPreviewMode(longJpeg), PREVIEW_MODES.FIT_WIDTH);
  assert.equal(normalizedScrollPosition(0, 0, 0), 0);
});

test("长图反馈字段不污染冻结result并包含风险审计", () => {
  const request = plan({ shortSidePreset: "1080" });
  const fields = longImageFeedbackFields(longJpeg, request);
  assert.equal(fields.is_long_image, true);
  assert.equal(fields.preview_default_mode, PREVIEW_MODES.FIT_WIDTH);
  assert.equal(fields.estimated_output_width, 1080);
  assert.equal(fields.height_limit_applied, false);
  assert.equal(fields.long_image_width_risk_policy_version, "PRODUCT_PREFLIGHT_HEURISTIC_V1");
});
