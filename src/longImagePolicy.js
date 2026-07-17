export const LONG_IMAGE_WIDTH_RISK_POLICY_VERSION = "PRODUCT_PREFLIGHT_HEURISTIC_V1";

export const PREVIEW_MODES = Object.freeze({
  FIT_WIDTH: "fit-width",
  ACTUAL_SIZE: "actual-size",
  OVERVIEW: "overview",
});

export const LONG_IMAGE_CONFIRMATION_TEXT = "我已了解长图小字可能明显变弱";

function positiveInteger(value) {
  return Number.isInteger(value) && value > 0;
}

export function calculateTargetByShortSide(sourceWidth, sourceHeight, targetShortSide) {
  if (!positiveInteger(sourceWidth)) throw new TypeError("sourceWidth must be a positive integer");
  if (!positiveInteger(sourceHeight)) throw new TypeError("sourceHeight must be a positive integer");
  if (!positiveInteger(targetShortSide)) throw new TypeError("targetShortSide must be a positive integer");
  const sourceShortSide = Math.min(sourceWidth, sourceHeight);
  const sourceLongSide = Math.max(sourceWidth, sourceHeight);
  const scale = targetShortSide / sourceShortSide;
  return {
    sourceWidth,
    sourceHeight,
    sourceShortSide,
    sourceLongSide,
    targetShortSide,
    scale,
    targetWidth: Math.max(1, Math.round(sourceWidth * scale)),
    targetHeight: Math.max(1, Math.round(sourceHeight * scale)),
  };
}

export function imageAspectRatio(width, height) {
  if (!positiveInteger(width) || !positiveInteger(height)) return null;
  return height / width;
}

export function isLongImage(width, height) {
  const ratio = imageAspectRatio(width, height);
  if (ratio == null || height <= width) return false;
  // The height threshold catches unusually tall high-resolution material while
  // explicitly excluding ordinary 9:16-or-wider portrait photographs.
  return ratio >= 3 || (height >= 4000 && ratio > (16 / 9));
}

export function defaultPreviewMode(fileInfo) {
  return isLongImage(fileInfo?.width, fileInfo?.height) ? PREVIEW_MODES.FIT_WIDTH : PREVIEW_MODES.OVERVIEW;
}

export function previewModeContract(mode) {
  return {
    mode,
    usesContain: mode === PREVIEW_MODES.OVERVIEW,
    oneImagePixelPerCssPixel: mode === PREVIEW_MODES.ACTUAL_SIZE,
    scrollsInsidePreview: mode !== PREVIEW_MODES.OVERVIEW,
  };
}

export function comparisonMode(fileInfo) {
  return isLongImage(fileInfo?.width, fileInfo?.height) ? "single-toggle" : "side-by-side";
}

export function normalizedScrollPosition(scrollTop, scrollHeight, clientHeight) {
  const available = Math.max(0, Number(scrollHeight) - Number(clientHeight));
  if (!Number.isFinite(available) || available <= 0) return 0;
  return Math.max(0, Math.min(1, Number(scrollTop) / available));
}

export function scrollTopForRatio(ratio, scrollHeight, clientHeight) {
  const available = Math.max(0, Number(scrollHeight) - Number(clientHeight));
  const normalized = Math.max(0, Math.min(1, Number(ratio) || 0));
  return Math.round(available * normalized);
}

export function estimateOutputDimensions(width, height, params = {}) {
  if (!positiveInteger(width) || !positiveInteger(height)) return { width: null, height: null, scale: null };
  let scale = 1;
  if (params.target_short_side != null) {
    try {
      const calculated = calculateTargetByShortSide(width, height, Number(params.target_short_side));
      return { width: calculated.targetWidth, height: calculated.targetHeight, scale: calculated.scale };
    } catch {
      return { width: null, height: null, scale: null };
    }
  } else if (params.scale_ratio != null) {
    const ratio = Number(params.scale_ratio);
    if (!Number.isFinite(ratio) || ratio <= 0) return { width: null, height: null, scale: null };
    scale = Math.min(1, ratio);
  } else if (params.target_width != null) {
    const targetWidth = Number(params.target_width);
    if (!positiveInteger(targetWidth)) return { width: null, height: null, scale: null };
    scale = Math.min(1, targetWidth / width);
  } else if (params.target_height != null) {
    const targetHeight = Number(params.target_height);
    if (!positiveInteger(targetHeight)) return { width: null, height: null, scale: null };
    scale = Math.min(1, targetHeight / height);
  } else {
    const ratios = [
      params.max_width ? Number(params.max_width) / width : 1,
      params.max_height ? Number(params.max_height) / height : 1,
      1,
    ].filter((value) => Number.isFinite(value) && value > 0);
    scale = Math.min(...ratios);
  }
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
    scale,
  };
}

export function classifyLongImageWidth(width) {
  const value = Number(width);
  if (!Number.isFinite(value) || value < 600) {
    return {
      level: "BLOCKED",
      severity: "error",
      blocked: true,
      confirmationRequired: false,
      message: `当前限制会将长图宽度缩小至约 ${Number.isFinite(value) ? Math.max(0, Math.round(value)) : "未知"} 像素，可能导致文字无法阅读。请提高高度限制、取消最大高度，或改用更大的输出宽度。`,
    };
  }
  if (value < 750) return { level: "CONFIRMATION_REQUIRED", severity: "danger", blocked: false, confirmationRequired: true, message: "长图文字可能明显难以阅读，继续前必须确认风险。" };
  if (value < 900) return { level: "STRONG_WARNING", severity: "warning", blocked: false, confirmationRequired: false, message: "小字清晰度风险明显，请在100%模式下重点复核。" };
  if (value < 1080) return { level: "REVIEW_NOTICE", severity: "warning", blocked: false, confirmationRequired: false, message: "可能影响细小文字，请在100%模式下复核。" };
  return { level: "LOWER_RISK", severity: "info", blocked: false, confirmationRequired: false, message: "宽度风险较低，处理后仍需人工复核。" };
}

export function modeApplicability(fileInfo, mode) {
  if (!fileInfo) return { applicable: false, reason: "选择图片后即可设置处理参数。" };
  if (mode === "LOSSLESS_COMPRESSION" && fileInfo.format !== "PNG") {
    return {
      applicable: false,
      code: "JPEG_COEFFICIENT_LOSSLESS_NOT_IMPLEMENTED",
      reason: "当前图片为JPEG，暂不支持真正无损压缩。请选择“尺寸缩小”或“上传适配”。",
    };
  }
  return { applicable: true, reason: "" };
}

export function defaultUploadLimits(fileInfo) {
  if (isLongImage(fileInfo?.width, fileInfo?.height)) {
    return { maxWidth: "1080", maxHeight: "", maxSize: "2", sizeUnit: "MB" };
  }
  return { maxWidth: "1920", maxHeight: "1080", maxSize: "2", sizeUnit: "MB" };
}

export function longImageReviewChecklist() {
  return ["顶部标题", "中段最小文字", "底部说明", "细线图标", "Logo", "二维码", "人物五官", "边缘与透明区域"];
}

export function noCandidateUiState(result) {
  const candidateRole = String(result?.candidate_delivery_role || "NONE");
  const hasCandidate = Boolean(result?.output_created) && candidateRole !== "NONE";
  return {
    hasCandidate,
    showComparison: hasCandidate,
    showReview: hasCandidate && result?.visual_review_status === "PENDING",
    showOpenFolder: hasCandidate,
    message: hasCandidate ? "" : "未生成处理结果",
  };
}

export function longImageFeedbackFields(fileInfo, plan = {}) {
  const detected = isLongImage(fileInfo?.width, fileInfo?.height);
  return {
    is_long_image: detected,
    source_aspect_ratio: imageAspectRatio(fileInfo?.width, fileInfo?.height),
    source_width: fileInfo?.width ?? null,
    source_height: fileInfo?.height ?? null,
    preview_default_mode: defaultPreviewMode(fileInfo),
    estimated_output_width: plan.estimatedOutputWidth ?? null,
    estimated_output_height: plan.estimatedOutputHeight ?? null,
    long_image_risk_level: plan.longImageRiskLevel ?? null,
    long_image_warnings: plan.longImageWarnings ?? [],
    height_limit_applied: Boolean(plan.params?.max_height),
    width_limit_applied: Boolean(plan.params?.max_width || plan.params?.target_short_side || plan.params?.target_width || plan.params?.scale_ratio),
    file_size_limit_applied: Boolean(plan.params?.max_file_size_bytes),
    long_image_width_risk_policy_version: LONG_IMAGE_WIDTH_RISK_POLICY_VERSION,
  };
}
