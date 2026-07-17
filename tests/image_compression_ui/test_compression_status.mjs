import assert from "node:assert/strict";
import test from "node:test";

import { apiErrorMessage, codeLabel, statusLabel } from "../../src/compressionStatus.js";
import {
  buildCompressionRequestPlan,
  convertUploadSizeUnit,
  linkUploadLimitsToSourceRatio,
} from "../../src/compressionParams.js";

test("压缩状态统一映射为中文", () => {
  assert.equal(statusLabel("technical", "TARGET_MET"), "已达到目标");
  assert.equal(statusLabel("visual", "PENDING"), "等待复核");
  assert.equal(statusLabel("delivery", "CANNOT_MEET_SAFELY"), "无法安全满足当前限制");
});

test("已知失败码与接口错误不会泄漏原始404文案", () => {
  assert.match(codeLabel("JPEG_COEFFICIENT_LOSSLESS_NOT_IMPLEMENTED"), /JPEG/);
  assert.equal(apiErrorMessage(null, 404), "图片会话已失效，请重新选择图片。");
});

test("未知状态保持可诊断原值", () => {
  assert.equal(statusLabel("technical", "FUTURE_STATUS"), "FUTURE_STATUS");
  assert.equal(codeLabel("FUTURE_CODE"), "FUTURE_CODE");
});

const fileInfo = { format: "PNG", width: 400, height: 200 };
const plan = (overrides = {}) => buildCompressionRequestPlan({
  fileInfo,
  mode: "RESIZE_REDUCTION",
  resizeStrategy: "short_side",
  shortSidePreset: "custom",
  customShortSide: "100",
  ratioPreset: "0.75",
  customRatio: "65",
  customDimension: "",
  uploadLimits: { maxWidth: "", maxHeight: "", maxSize: "", sizeUnit: "MB" },
  ...overrides,
});

test("尺寸缩小四种策略只提交当前参数", () => {
  assert.deepEqual(plan().params, { target_short_side: 100 });
  assert.deepEqual(plan({ resizeStrategy: "ratio", ratioPreset: "0.75" }).params, { scale_ratio: 0.75 });
  assert.deepEqual(plan({ resizeStrategy: "ratio", ratioPreset: "0.5" }).params, { scale_ratio: 0.5 });
  assert.deepEqual(plan({ resizeStrategy: "ratio", ratioPreset: "custom", customRatio: "40" }).params, { scale_ratio: 0.4 });
  assert.deepEqual(plan({ resizeStrategy: "width", customDimension: "100" }).params, { target_width: 100 });
  assert.deepEqual(plan({ resizeStrategy: "height", customDimension: "100" }).params, { target_height: 100 });
});

test("尺寸缩小拒绝放大零负数和非数字", () => {
  for (const value of ["400", "500", "0", "-1", "abc"]) {
    assert.equal(plan({ resizeStrategy: "width", customDimension: value }).valid, false);
  }
  assert.equal(plan({ resizeStrategy: "ratio", ratioPreset: "custom", customRatio: "100" }).valid, false);
});

test("JPEG无损模式在执行前禁用且不提交任务", () => {
  const jpeg = plan({ mode: "LOSSLESS_COMPRESSION", fileInfo: { ...fileInfo, format: "JPEG" } });
  assert.equal(jpeg.valid, false);
  assert.equal(jpeg.severity, "danger");
  assert.equal(jpeg.failureCode, "JPEG_COEFFICIENT_LOSSLESS_NOT_IMPLEMENTED");
  assert.match(jpeg.message, /当前图片为JPEG/);
  assert.deepEqual(jpeg.params, {});
});

test("上传限制要求至少一项并正确转换KB和MB", () => {
  const empty = plan({ mode: "UPLOAD_ADAPTATION" });
  assert.equal(empty.valid, false);
  const upload = plan({ mode: "UPLOAD_ADAPTATION", uploadLimits: { maxWidth: "300", maxHeight: "", maxSize: "2", sizeUnit: "MB" } });
  assert.deepEqual(upload.params, { max_width: 300, max_height: null, max_file_size_bytes: 2097152 });
  const kb = convertUploadSizeUnit({ maxWidth: "", maxHeight: "", maxSize: "2", sizeUnit: "MB" }, "KB");
  assert.equal(kb.maxSize, "2048");
  assert.equal(plan({ mode: "UPLOAD_ADAPTATION", uploadLimits: kb }).params.max_file_size_bytes, 2097152);
});

test("上传适配锁定长宽比后修改任一边会按原图比例联动", () => {
  const source = { width: 1920, height: 1080 };
  const limits = { maxWidth: "1920", maxHeight: "1080", maxSize: "2", sizeUnit: "MB" };
  assert.deepEqual(
    linkUploadLimitsToSourceRatio(source, limits, "maxWidth", "1600"),
    { ...limits, maxWidth: "1600", maxHeight: "900" },
  );
  assert.deepEqual(
    linkUploadLimitsToSourceRatio(source, limits, "maxHeight", "720"),
    { ...limits, maxWidth: "1280", maxHeight: "720" },
  );
});

test("长图比例联动使用原图尺寸且清空一边时同步清空另一边", () => {
  const limits = { maxWidth: "1080", maxHeight: "", maxSize: "2", sizeUnit: "MB" };
  assert.deepEqual(
    linkUploadLimitsToSourceRatio({ width: 1266, height: 9088 }, limits, "maxWidth", "1080"),
    { ...limits, maxWidth: "1080", maxHeight: "7753" },
  );
  assert.deepEqual(
    linkUploadLimitsToSourceRatio({ width: 1266, height: 9088 }, limits, "maxWidth", ""),
    { ...limits, maxWidth: "", maxHeight: "" },
  );
});
