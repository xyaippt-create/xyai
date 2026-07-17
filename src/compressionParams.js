import {
  LONG_IMAGE_CONFIRMATION_TEXT,
  calculateTargetByShortSide,
  classifyLongImageWidth,
  estimateOutputDimensions,
  isLongImage,
  modeApplicability,
} from "./longImagePolicy.js";

function withEstimatedDimensions(plan, fileInfo) {
  if (!plan.valid) return plan;
  const estimated = estimateOutputDimensions(fileInfo.width, fileInfo.height, plan.params);
  return {
    ...plan,
    estimatedOutputWidth: estimated.width,
    estimatedOutputHeight: estimated.height,
    calculatedScale: estimated.scale,
    aspectRatioPreserved: true,
    cropApplied: false,
    paddingApplied: false,
    stretchApplied: false,
    upscaleApplied: false,
  };
}

function withLongImagePreflight(plan, fileInfo, longImageRiskConfirmed) {
  if (!plan.valid || !isLongImage(fileInfo?.width, fileInfo?.height)) return plan;
  const estimated = estimateOutputDimensions(fileInfo.width, fileInfo.height, plan.params);
  const risk = classifyLongImageWidth(estimated.width);
  const longImageWarnings = ["已识别为长图。建议优先限制宽度和文件体积，不限制总高度。", risk.message];
  const base = {
    ...plan,
    estimatedOutputWidth: estimated.width,
    estimatedOutputHeight: estimated.height,
    calculatedScale: estimated.scale,
    longImageRiskLevel: risk.level,
    longImageWarnings,
    riskPolicyVersion: "PRODUCT_PREFLIGHT_HEURISTIC_V1",
  };
  if (risk.blocked) return { ...base, valid: false, severity: "danger", message: risk.message };
  if (risk.confirmationRequired && !longImageRiskConfirmed) {
    return {
      ...base,
      valid: false,
      severity: "danger",
      requiresLongImageConfirmation: true,
      confirmationText: LONG_IMAGE_CONFIRMATION_TEXT,
      message: `${risk.message} 请勾选“${LONG_IMAGE_CONFIRMATION_TEXT}”。`,
    };
  }
  return {
    ...base,
    severity: risk.severity === "info" ? plan.severity : "warning",
    requiresLongImageConfirmation: risk.confirmationRequired,
    confirmationText: risk.confirmationRequired ? LONG_IMAGE_CONFIRMATION_TEXT : "",
    message: `${plan.message} ${risk.message}`,
  };
}

function resizePlan({
  fileInfo,
  resizeStrategy,
  shortSidePreset,
  customShortSide,
  ratioPreset,
  customRatio,
  customDimension,
}) {
  const strategy = String(resizeStrategy || "short_side");
  if (strategy === "short_side") {
    const raw = shortSidePreset === "custom" ? customShortSide : shortSidePreset;
    const targetShortSide = Number(raw);
    if (!Number.isInteger(targetShortSide) || targetShortSide <= 0) {
      return { valid: false, severity: "danger", message: "目标短边必须为正整数。", params: {} };
    }
    const calculated = calculateTargetByShortSide(fileInfo.width, fileInfo.height, targetShortSide);
    const base = {
      resizeStrategy: "SHORT_SIDE",
      sourceShortSide: calculated.sourceShortSide,
      targetShortSide,
      calculatedScale: calculated.scale,
      estimatedOutputWidth: calculated.targetWidth,
      estimatedOutputHeight: calculated.targetHeight,
      aspectRatioPreserved: true,
      cropApplied: false,
      paddingApplied: false,
      stretchApplied: false,
      upscaleApplied: false,
      params: { target_short_side: targetShortSide },
    };
    if (targetShortSide > calculated.sourceShortSide) {
      return {
        ...base,
        valid: false,
        severity: "danger",
        failureCode: "TARGET_SHORT_SIDE_UPSCALE_BLOCKED",
        upscaleBlocked: true,
        message: `目标短边大于原图短边，图片不会被放大。请选择不超过 ${calculated.sourceShortSide} 像素的目标短边。`,
      };
    }
    if (targetShortSide === calculated.sourceShortSide) {
      return {
        ...base,
        valid: false,
        severity: "warning",
        failureCode: "NO_PROCESSING_NEEDED",
        upscaleBlocked: false,
        message: "目标短边等于原图短边，无需处理，也不会为了生成文件而重新编码。",
      };
    }
    return {
      ...base,
      valid: true,
      upscaleBlocked: false,
      message: `固定短边 ${targetShortSide} 像素，预计尺寸 ${calculated.targetWidth} × ${calculated.targetHeight}。`,
    };
  }

  if (strategy === "ratio") {
    const raw = ratioPreset === "custom" ? Number(customRatio) / 100 : Number(ratioPreset);
    if (!Number.isFinite(raw) || raw <= 0 || raw >= 1) {
      return { valid: false, severity: "danger", message: "缩放比例必须大于 0 且小于 100%。", params: {} };
    }
    return withEstimatedDimensions({
      valid: true,
      resizeStrategy: "RATIO",
      message: `按原图 ${Math.round(raw * 100)}% 等比例缩小。`,
      params: { scale_ratio: raw },
    }, fileInfo);
  }

  if (!["width", "height"].includes(strategy)) {
    return { valid: false, severity: "danger", message: "不支持的尺寸缩小方式。", params: {} };
  }
  const dimension = Number(customDimension);
  const sourceLimit = strategy === "width" ? fileInfo.width : fileInfo.height;
  if (!Number.isInteger(dimension) || dimension <= 0 || dimension >= sourceLimit) {
    return {
      valid: false,
      severity: "danger",
      message: `目标${strategy === "width" ? "宽度" : "高度"}必须为小于原图的正整数，尺寸缩小禁止放大。`,
      params: {},
    };
  }
  const params = strategy === "width" ? { target_width: dimension } : { target_height: dimension };
  const plan = withEstimatedDimensions({
    valid: true,
    resizeStrategy: strategy === "width" ? "WIDTH" : "HEIGHT",
    message: `指定${strategy === "width" ? "宽度" : "高度"} ${dimension} 像素，长边按原比例计算。`,
    params,
  }, fileInfo);
  return plan;
}

export function buildCompressionRequestPlan({
  fileInfo,
  mode,
  resizeStrategy = "short_side",
  shortSidePreset = "1080",
  customShortSide = "",
  ratioPreset = "0.75",
  customRatio = "65",
  customDimension = "",
  uploadLimits,
  longImageRiskConfirmed = false,
}) {
  if (!fileInfo) return { valid: false, message: "选择图片后即可设置处理参数。", params: {} };
  const applicability = modeApplicability(fileInfo, mode);
  if (!applicability.applicable) {
    return {
      valid: false,
      severity: "danger",
      message: applicability.reason,
      failureCode: applicability.code || null,
      params: {},
    };
  }
  if (mode === "LOSSLESS_COMPRESSION") {
    return { valid: true, message: "将执行 PNG 严格无损体积优化。", params: {} };
  }
  if (mode === "RESIZE_REDUCTION") {
    const plan = resizePlan({
      fileInfo,
      resizeStrategy,
      shortSidePreset,
      customShortSide,
      ratioPreset,
      customRatio,
      customDimension,
    });
    return withLongImagePreflight(plan, fileInfo, longImageRiskConfirmed);
  }
  if (mode !== "UPLOAD_ADAPTATION") return { valid: false, message: "不支持的处理方式。", params: {} };
  const parseLimit = (raw, label) => {
    if (raw === "") return { value: null };
    const value = Number(raw);
    return Number.isInteger(value) && value > 0 ? { value } : { error: `${label}必须为正整数。` };
  };
  const width = parseLimit(uploadLimits.maxWidth, "最大宽度");
  const height = parseLimit(uploadLimits.maxHeight, "最大高度");
  const sizeNumber = uploadLimits.maxSize === "" ? null : Number(uploadLimits.maxSize);
  if (width.error || height.error) return { valid: false, message: width.error || height.error, params: {} };
  if (sizeNumber !== null && (!Number.isFinite(sizeNumber) || sizeNumber <= 0)) return { valid: false, message: "最大文件体积必须大于 0。", params: {} };
  const sizeBytes = sizeNumber === null ? null : Math.round(sizeNumber * (uploadLimits.sizeUnit === "MB" ? 1024 * 1024 : 1024));
  if (!width.value && !height.value && !sizeBytes) return { valid: false, message: "上传适配至少需要填写一个限制条件。", params: {} };
  const plan = withEstimatedDimensions({
    valid: true,
    message: `实际提交：宽 ${width.value || "不限"} px，高 ${height.value || "不限"} px，体积 ${sizeBytes || "不限"} B。`,
    params: { max_width: width.value, max_height: height.value, max_file_size_bytes: sizeBytes },
  }, fileInfo);
  return withLongImagePreflight(plan, fileInfo, longImageRiskConfirmed);
}

export function convertUploadSizeUnit(limits, nextUnit) {
  if (nextUnit === limits.sizeUnit) return limits;
  const current = Number(limits.maxSize);
  if (!Number.isFinite(current) || limits.maxSize === "") return { ...limits, sizeUnit: nextUnit };
  const converted = limits.sizeUnit === "MB" && nextUnit === "KB" ? current * 1024 : current / 1024;
  return { ...limits, maxSize: String(Number(converted.toFixed(6))), sizeUnit: nextUnit };
}

export function linkUploadLimitsToSourceRatio(fileInfo, limits, changedField, rawValue) {
  if (!["maxWidth", "maxHeight"].includes(changedField)) return limits;
  const next = { ...limits, [changedField]: rawValue };
  const sourceWidth = Number(fileInfo?.width);
  const sourceHeight = Number(fileInfo?.height);
  if (!Number.isInteger(sourceWidth) || sourceWidth <= 0 || !Number.isInteger(sourceHeight) || sourceHeight <= 0) return next;

  const counterpart = changedField === "maxWidth" ? "maxHeight" : "maxWidth";
  if (rawValue === "") return { ...next, [counterpart]: "" };
  const changedValue = Number(rawValue);
  if (!Number.isInteger(changedValue) || changedValue <= 0) return next;

  const linkedValue = changedField === "maxWidth"
    ? Math.max(1, Math.round(changedValue * sourceHeight / sourceWidth))
    : Math.max(1, Math.round(changedValue * sourceWidth / sourceHeight));
  return { ...next, [counterpart]: String(linkedValue) };
}
