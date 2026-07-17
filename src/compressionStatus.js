export const COMPRESSION_STATE_LABELS = Object.freeze({
  IDLE: "等待选择图片",
  FILE_SELECTING: "正在读取所选图片",
  INTAKE_PENDING: "正在校验图片",
  FILE_READY: "图片已准备就绪",
  RUNNING: "正在本地处理",
  REVIEW: "等待人工视觉复核",
  DONE: "处理完成",
  ERROR: "处理未完成",
});

export const TECHNICAL_STATUS_LABELS = Object.freeze({
  INVALID_REQUEST: "参数无效",
  NO_PROCESSING_NEEDED: "无需处理",
  TARGET_MET: "已达到目标",
  TARGET_MET_WITH_REENCODE: "已通过重新编码达到目标",
  CANNOT_MEET_SAFELY: "无法安全满足",
  PROCESSING_FAILED: "处理失败",
});

export const VISUAL_STATUS_LABELS = Object.freeze({
  NOT_REQUIRED: "无需复核",
  PENDING: "等待复核",
  PASS: "复核通过",
  PASS_WITH_NOTES: "有提示但可用",
  FAIL: "复核未通过",
  NOT_AVAILABLE: "暂无复核结果",
});

export const DELIVERY_STATUS_LABELS = Object.freeze({
  DELIVERY_READY: "可以使用",
  DELIVERY_READY_WITH_NOTES: "可以使用，但需注意",
  REVIEW_REQUIRED: "处理完成，建议复核",
  CANNOT_MEET_SAFELY: "无法安全满足当前限制",
});

export const CODE_LABELS = Object.freeze({
  INTAKE_FAILED: "文件读取失败。",
  INVALID_REQUEST: "参数不符合要求。",
  OUTPUT_DIRECTORY_INVALID: "输出目录不可用。",
  OUTPUT_WRITE_PERMISSION_DENIED: "无法写入输出目录。",
  JPEG_COEFFICIENT_LOSSLESS_NOT_IMPLEMENTED: "JPEG 暂不支持真正无损压缩，请改用尺寸缩小或上传适配。",
  MODE_NOT_APPLICABLE: "当前模式不支持此图片。",
  LONG_IMAGE_WIDTH_TOO_LOW: "当前长图输出宽度过低，可能导致文字无法阅读。",
  LONG_IMAGE_WIDTH_CONFIRMATION_REQUIRED: "继续前请确认长图小字清晰度风险。",
  TARGET_SHORT_SIDE_UPSCALE_BLOCKED: "目标短边大于原图短边，尺寸缩小不会放大图片。",
  NO_PROCESSING_NEEDED: "目标尺寸与原图一致，无需重新编码。",
  EXIF_ORIENTATION_REQUIRES_NORMALIZATION: "图片包含旋转方向信息，请先旋转后另存再处理。",
  FEEDBACK_PACKAGE_REQUEST_INVALID: "测试反馈包请求不正确。",
  FEEDBACK_PACKAGE_TASK_NOT_FOUND: "无法找到对应的压缩任务。",
  FEEDBACK_PACKAGE_OUTPUT_REQUIRED: "当前任务没有可关联的输出图片，不能生成测试反馈包。",
  FEEDBACK_PACKAGE_TOKEN_NOT_FOUND: "测试反馈包下载链接无效。",
  FEEDBACK_PACKAGE_TOKEN_EXPIRED: "测试反馈包下载链接已过期，请重新生成。",
  FEEDBACK_PACKAGE_TASK_MISMATCH: "测试反馈包链接与当前任务不一致。",
  FEEDBACK_PACKAGE_FILE_MISSING: "测试反馈包文件已不存在，请重新生成。",
  FEEDBACK_PACKAGE_FILE_INVALID: "测试反馈包文件已损坏，请重新生成。",
  FEEDBACK_PACKAGE_SHA_MISMATCH: "测试反馈包完整性校验失败，请重新生成。",
  NO_SIZE_GAIN: "无损优化没有获得体积收益，因此没有生成副本。",
  UPLOAD_LIMITS_BELOW_SAFE_FLOOR: "约束需要把尺寸降到安全下限以下，系统拒绝生成候选。",
  UPLOAD_LIMITS_CANNOT_MEET_SAFELY: "在最低画质与尺寸安全边界内仍无法满足全部约束。",
  METADATA_NOT_FULLY_PRESERVED: "部分元数据未能完整保留，请在交付前确认。",
  SOURCE_EXTENSION_MAGIC_MISMATCH: "文件扩展名与图片实际格式不一致。",
  SOURCE_DECODE_FAILED: "图片无法完整解码，请更换有效文件。",
  SOURCE_SHA_CHANGED: "原文件在处理期间发生变化。",
  TARGET_DIMENSION_INVALID: "目标尺寸无效、超过原图或未保持原图比例。",
  LIMITS_MISSING: "请至少填写一个上传限制。",
  PROCESSING_EXCEPTION: "处理过程中出现未预期异常。",
  TOKEN_NOT_FOUND_OR_EXPIRED: "图片会话已失效，请重新选择图片。",
});

export function statusLabel(group, value) {
  const registries = {
    state: COMPRESSION_STATE_LABELS,
    technical: TECHNICAL_STATUS_LABELS,
    visual: VISUAL_STATUS_LABELS,
    delivery: DELIVERY_STATUS_LABELS,
  };
  return registries[group]?.[value] || value || "—";
}

export function codeLabel(value) {
  return CODE_LABELS[value] || value || "—";
}

export function apiErrorMessage(payload, httpStatus) {
  const detail = payload?.detail;
  const code = typeof detail === "object" ? detail?.code : payload?.code;
  const message = typeof detail === "string" ? detail : detail?.message || payload?.message;
  if (code && CODE_LABELS[code]) return CODE_LABELS[code];
  if (message) return String(message);
  if (httpStatus === 413) return "图片超过本地安全接收上限。";
  if (httpStatus === 415) return "仅支持 PNG、JPG、JPEG 图片。";
  if (httpStatus === 404) return "图片会话已失效，请重新选择图片。";
  return "本地处理请求未完成，请检查服务状态后重试。";
}
