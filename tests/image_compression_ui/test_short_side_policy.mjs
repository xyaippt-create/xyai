import assert from "node:assert/strict";
import test from "node:test";

import { buildCompressionRequestPlan } from "../../src/compressionParams.js";
import { calculateTargetByShortSide, estimateOutputDimensions } from "../../src/longImagePolicy.js";

const fileInfo = { format: "JPEG", width: 1266, height: 9088 };

function plan(overrides = {}) {
  return buildCompressionRequestPlan({
    fileInfo,
    mode: "RESIZE_REDUCTION",
    resizeStrategy: "short_side",
    shortSidePreset: "1080",
    customShortSide: "",
    ratioPreset: "0.75",
    customRatio: "65",
    customDimension: "",
    uploadLimits: { maxWidth: "1080", maxHeight: "", maxSize: "2", sizeUnit: "MB" },
    ...overrides,
  });
}

const examples = [
  [1266, 9088, 1080, 1080, 7753],
  [1266, 9088, 900, 900, 6461],
  [1920, 1080, 900, 1600, 900],
  [1080, 1350, 900, 900, 1125],
  [1200, 1200, 1080, 1080, 1080],
  [6000, 1000, 900, 5400, 900],
];

for (const [sourceWidth, sourceHeight, targetShortSide, targetWidth, targetHeight] of examples) {
  test(`固定短边 ${sourceWidth}x${sourceHeight} -> ${targetShortSide}`, () => {
    const result = calculateTargetByShortSide(sourceWidth, sourceHeight, targetShortSide);
    assert.equal(result.sourceShortSide, Math.min(sourceWidth, sourceHeight));
    assert.equal(result.targetWidth, targetWidth);
    assert.equal(result.targetHeight, targetHeight);
    assert.equal(result.scale, targetShortSide / Math.min(sourceWidth, sourceHeight));
  });
}

test("短边等于原图时明确无需处理", () => {
  const result = plan({ shortSidePreset: "custom", customShortSide: "1266" });
  assert.equal(result.valid, false);
  assert.equal(result.failureCode, "NO_PROCESSING_NEEDED");
});

test("短边大于原图时执行前阻止放大", () => {
  const result = plan({ shortSidePreset: "custom", customShortSide: "1400" });
  assert.equal(result.valid, false);
  assert.equal(result.failureCode, "TARGET_SHORT_SIDE_UPSCALE_BLOCKED");
  assert.match(result.message, /不超过 1266/);
});

for (const invalid of ["", "0", "-1", "1.5", "abc"]) {
  test(`非法短边 ${JSON.stringify(invalid)} 不生成run参数`, () => {
    const result = plan({ shortSidePreset: "custom", customShortSide: invalid });
    assert.equal(result.valid, false);
    assert.deepEqual(result.params, {});
  });
}

test("非法原图尺寸被纯函数拒绝", () => {
  assert.throws(() => calculateTargetByShortSide(0, 100, 50));
  assert.throws(() => calculateTargetByShortSide(100, 0, 50));
});

test("短边策略只提交target_short_side", () => {
  assert.deepEqual(plan().params, { target_short_side: 1080 });
});

test("比例策略只提交scale_ratio", () => {
  assert.deepEqual(plan({ resizeStrategy: "ratio", ratioPreset: "0.75" }).params, { scale_ratio: 0.75 });
});

test("宽度策略只提交target_width", () => {
  assert.deepEqual(plan({ resizeStrategy: "width", customDimension: "1080" }).params, { target_width: 1080 });
});

test("高度策略只提交target_height并触发长图危险预检", () => {
  const result = plan({ resizeStrategy: "height", customDimension: "1080" });
  assert.deepEqual(result.params, { target_height: 1080 });
  assert.equal(result.valid, false);
  assert.equal(result.estimatedOutputWidth, 150);
});

test("固定短边预计尺寸与通用预估函数一致", () => {
  const request = plan();
  const estimated = estimateOutputDimensions(fileInfo.width, fileInfo.height, request.params);
  assert.equal(Math.abs(request.estimatedOutputWidth - estimated.width) <= 1, true);
  assert.equal(Math.abs(request.estimatedOutputHeight - estimated.height) <= 1, true);
});

test("固定短边显式声明不裁切不补边不拉伸不放大", () => {
  const request = plan();
  assert.equal(request.aspectRatioPreserved, true);
  assert.equal(request.cropApplied, false);
  assert.equal(request.paddingApplied, false);
  assert.equal(request.stretchApplied, false);
  assert.equal(request.upscaleApplied, false);
});
