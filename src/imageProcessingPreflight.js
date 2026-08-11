import React from "react";

export const PREFLIGHT_PURPOSES = Object.freeze([
  { value: "REDUCE_FILE_SIZE", label: "减小文件体积", description: "评估严格无损或上传适配是否适合当前图片。" },
  { value: "REDUCE_DIMENSIONS", label: "缩小图片尺寸", description: "按一种合同策略等比例缩小，禁止放大。" },
  { value: "MEET_UPLOAD_LIMITS", label: "满足上传限制", description: "按宽度、高度或文件体积上限评估适配方案。" },
  { value: "IMPROVE_LOW_QUALITY", label: "改善低清质量", description: "仅分析并引导后续高清增强，本阶段不执行。" },
]);

export const PREFLIGHT_STATUS_META = Object.freeze({
  READY: { label: "可以处理", tone: "success" },
  READY_WITH_WARNING: { label: "可以处理，但需要注意", tone: "warning" },
  NO_PROCESSING_NEEDED: { label: "无需处理", tone: "neutral" },
  UNSUPPORTED_MODE: { label: "当前模式不支持", tone: "danger" },
  BLOCKED_UNSAFE: { label: "已阻止不安全处理", tone: "danger" },
  ROUTE_TO_ENHANCEMENT: { label: "建议使用高清增强", tone: "info" },
});

export const PREFLIGHT_ACTION_META = Object.freeze({
  NO_PROCESSING: { label: "保持原图，不重新编码", executable: false },
  LOSSLESS_COMPRESSION: { label: "PNG严格无损压缩", executable: true },
  RESIZE_REDUCTION: { label: "图片尺寸缩小", executable: true },
  UPLOAD_ADAPTATION: { label: "上传限制适配", executable: true },
  FUTURE_ENHANCEMENT: { label: "后续高清增强", executable: false },
  UNSUPPORTED: { label: "当前不支持执行", executable: false },
});

export const REASON_CODE_META = Object.freeze({
  PNG_STRICT_LOSSLESS_SUPPORTED: { title: "支持PNG严格无损", description: "保持PNG格式、像素尺寸和透明信息。", severity: "info", requiresAction: false, suggestedAction: "可继续检查推荐方案。" },
  PNG_STRICT_LOSSLESS_MAY_HAVE_NO_GAIN: { title: "体积可能无明显收益", description: "严格无损不保证文件体积一定下降，无收益时不会伪造候选。", severity: "warning", requiresAction: false, suggestedAction: "可执行预填后由用户决定是否处理。" },
  JPEG_STRICT_LOSSLESS_NOT_SUPPORTED: { title: "JPEG不支持严格无损压缩", description: "当前不会把JPEG静默切换为其他处理模式。", severity: "warning", requiresAction: true, suggestedAction: "填写最大文件体积或选择尺寸缩小。" },
  FILE_SIZE_TARGET_REQUIRED: { title: "需要文件体积目标", description: "JPEG减小体积需要明确最大文件体积。", severity: "warning", requiresAction: true, suggestedAction: "填写最大文件体积后重新分析。" },
  TARGET_SMALLER_THAN_SOURCE: { title: "目标小于原图", description: "目标尺寸符合缩小语义。", severity: "info", requiresAction: false, suggestedAction: "核对预计尺寸后可使用推荐方案。" },
  TARGET_EQUALS_SOURCE: { title: "目标等于原图", description: "重新处理不会产生有效尺寸变化。", severity: "info", requiresAction: false, suggestedAction: "直接使用原图。" },
  TARGET_EXCEEDS_SOURCE: { title: "目标超过原图", description: "该目标会导致放大，已按安全规则阻止。", severity: "danger", requiresAction: true, suggestedAction: "改为不超过原图的目标。" },
  NO_UPSCALE: { title: "禁止放大", description: "尺寸缩小与上传适配不会放大图片。", severity: "danger", requiresAction: true, suggestedAction: "降低目标尺寸。" },
  NO_PROCESSING_REQUIRED: { title: "无需处理", description: "当前图片已经满足所选目标，不会为了生成文件而重新编码。", severity: "info", requiresAction: false, suggestedAction: "建议直接使用原图。" },
  UPLOAD_LIMITS_ALREADY_MET: { title: "已满足上传限制", description: "当前尺寸和体积均在填写的限制内。", severity: "info", requiresAction: false, suggestedAction: "直接使用原图。" },
  UPLOAD_LIMITS_REQUIRE_ADAPTATION: { title: "需要上传适配", description: "当前图片至少有一项超过所填限制。", severity: "info", requiresAction: false, suggestedAction: "核对预计输出后可预填上传适配。" },
  UPLOAD_LIMITS_UNSAFE_TO_MEET: { title: "限制无法安全满足", description: "按当前目标处理会使关键尺寸低于安全门槛。", severity: "danger", requiresAction: true, suggestedAction: "采用替代参数或放宽限制。" },
  IMPROVE_LOW_QUALITY_REQUIRES_ENHANCEMENT: { title: "需要高清增强能力", description: "当前阶段只给出路由建议，不执行增强或生成文件。", severity: "info", requiresAction: false, suggestedAction: "等待后续高清增强功能接入。" },
  ANIMATED_IMAGE_NOT_SUPPORTED: { title: "动画图片暂不支持", description: "不会静默只处理第一帧。", severity: "danger", requiresAction: true, suggestedAction: "改用受支持的静态图片。" },
  MULTI_FRAME_IMAGE_NOT_SUPPORTED: { title: "多帧图片暂不支持", description: "当前处理链不接受多帧图片。", severity: "danger", requiresAction: true, suggestedAction: "导出明确的单帧静态图片。" },
  FORMAT_NOT_SUPPORTED: { title: "图片格式暂不支持", description: "当前只支持静态PNG和JPEG。", severity: "danger", requiresAction: true, suggestedAction: "使用受支持格式重新上传。" },
  LONG_IMAGE_DETECTED: { title: "检测到长图", description: "这是结构与处理安全提示，不代表图片质量。", severity: "warning", requiresAction: false, suggestedAction: "重点核对预计短边和替代参数。" },
  ULTRA_WIDE_IMAGE_DETECTED: { title: "检测到超宽图", description: "这是结构与处理安全提示，不代表图片质量。", severity: "warning", requiresAction: false, suggestedAction: "核对预计尺寸并避免过度缩小。" },
  ESTIMATED_SHORT_SIDE_LT_600: { title: "预计短边低于600", description: "关键尺寸过小，已阻止不安全处理。", severity: "danger", requiresAction: true, suggestedAction: "将预计短边提高到至少750。" },
  ESTIMATED_SHORT_SIDE_600_749: { title: "预计短边处于600—749", description: "属于高风险区间，需要明确核对。", severity: "warning", requiresAction: true, suggestedAction: "优先采用短边750或更高的替代参数。" },
  ESTIMATED_SHORT_SIDE_GE_750: { title: "预计短边不低于750", description: "短边门槛通过，仍需结合其他规则判断。", severity: "info", requiresAction: false, suggestedAction: "继续核对其他风险与参数。" },
  ALPHA_CHANNEL_PRESENT: { title: "包含透明通道", description: "透明信息必须在受支持的PNG流程中保留。", severity: "warning", requiresAction: false, suggestedAction: "确认使用保留Alpha的方案。" },
  MANUAL_ACTION_CONFLICTS_WITH_PURPOSE: { title: "手动动作与处理目的不一致", description: "当前动作可能安全，但不完全符合所选目的。", severity: "warning", requiresAction: true, suggestedAction: "核对推荐替代动作。" },
  MANUAL_ACTION_BLOCKED_BY_SAFETY_GATE: { title: "手动动作已被安全门禁阻止", description: "手动选择不能绕过放大、格式或尺寸安全规则。", severity: "danger", requiresAction: true, suggestedAction: "修改目标或采用推荐替代方案。" },
});

export const ERROR_CODE_META = Object.freeze({
  INVALID_REQUEST_BODY: { message: "预检请求结构无效，请检查页面参数。", canRetryParameters: true, requiresReupload: false, requiresFileCheck: false, systemError: false },
  INVALID_PURPOSE: { message: "处理目的无效，请重新选择。", canRetryParameters: true, requiresReupload: false, requiresFileCheck: false, systemError: false },
  INVALID_REQUESTED_ACTION: { message: "请求动作无效，请重新分析。", canRetryParameters: true, requiresReupload: false, requiresFileCheck: false, systemError: false },
  MISSING_RESIZE_TARGET: { message: "请填写唯一的尺寸缩小目标。", canRetryParameters: true, requiresReupload: false, requiresFileCheck: false, systemError: false },
  CONFLICTING_TARGETS: { message: "尺寸目标相互冲突，请只保留一种策略。", canRetryParameters: true, requiresReupload: false, requiresFileCheck: false, systemError: false },
  MISSING_UPLOAD_LIMITS: { message: "请至少填写一项上传限制。", canRetryParameters: true, requiresReupload: false, requiresFileCheck: false, systemError: false },
  INVALID_TARGET_VALUE: { message: "目标值无效，请填写合同允许的正数范围。", canRetryParameters: true, requiresReupload: false, requiresFileCheck: false, systemError: false },
  TOKEN_NOT_FOUND_OR_EXPIRED: { message: "图片会话已失效，请重新选择图片。", canRetryParameters: false, requiresReupload: true, requiresFileCheck: false, systemError: false },
  ABSOLUTE_PATH_NOT_ALLOWED: { message: "预检只接受安全图片会话，不接受本地路径。", canRetryParameters: false, requiresReupload: true, requiresFileCheck: false, systemError: false },
  IMAGE_DECODE_FAILED: { message: "图片无法完整解码，请更换文件或重新导出后上传。", canRetryParameters: false, requiresReupload: true, requiresFileCheck: true, systemError: false },
});

const RESIZE_FIELDS = Object.freeze({
  FIXED_SHORT_SIDE: "target_short_side",
  SCALE_RATIO: "scale_ratio",
  FIXED_WIDTH: "target_width",
  FIXED_HEIGHT: "target_height",
});

function parsePositiveInteger(raw, label, { optional = false } = {}) {
  if (raw === "" || raw === null || raw === undefined) return optional ? { value: null } : { error: `请填写${label}。` };
  const value = Number(raw);
  if (!Number.isInteger(value) || value <= 0) return { error: `${label}必须为正整数。` };
  return { value };
}

function parseMaxBytes(raw, { optional = true } = {}) {
  if (raw === "" || raw === null || raw === undefined) return optional ? { value: null } : { error: "请填写最大文件体积。" };
  const kb = Number(raw);
  if (!Number.isFinite(kb) || kb <= 0) return { error: "最大文件体积必须大于0 KB。" };
  return { value: Math.max(1, Math.round(kb * 1024)) };
}

export function buildPreflightRequestPlan({ sourceToken, purpose, targets = {} }) {
  if (!sourceToken) return { valid: false, phase: "NO_FILE", message: "请先上传一张图片。", request: null };
  if (!PREFLIGHT_PURPOSES.some((item) => item.value === purpose)) {
    return { valid: false, phase: "AWAITING_PURPOSE", message: "请选择本次真实处理目的。", request: null };
  }

  const normalizedTargets = {};
  if (purpose === "REDUCE_DIMENSIONS") {
    const strategy = targets.resizeStrategy || "FIXED_SHORT_SIDE";
    const field = RESIZE_FIELDS[strategy];
    if (!field) return { valid: false, phase: "PARAMETERS_INCOMPLETE", message: "请选择合同支持的尺寸策略。", request: null };
    if (strategy === "SCALE_RATIO") {
      const percent = Number(targets.resizeValue);
      if (!Number.isFinite(percent) || percent <= 0 || percent >= 100) {
        return { valid: false, phase: "PARAMETERS_INCOMPLETE", message: "缩放比例必须大于0且小于100%。", request: null };
      }
      normalizedTargets.resize_strategy = strategy;
      normalizedTargets[field] = percent / 100;
    } else {
      const parsed = parsePositiveInteger(targets.resizeValue, strategy === "FIXED_SHORT_SIDE" ? "目标短边" : strategy === "FIXED_WIDTH" ? "目标宽度" : "目标高度");
      if (parsed.error) return { valid: false, phase: "PARAMETERS_INCOMPLETE", message: parsed.error, request: null };
      normalizedTargets.resize_strategy = strategy;
      normalizedTargets[field] = parsed.value;
    }
  }

  if (purpose === "REDUCE_FILE_SIZE") {
    const parsed = parseMaxBytes(targets.maxSizeKb, { optional: true });
    if (parsed.error) return { valid: false, phase: "PARAMETERS_INCOMPLETE", message: parsed.error, request: null };
    if (parsed.value) normalizedTargets.max_bytes = parsed.value;
  }

  if (purpose === "MEET_UPLOAD_LIMITS") {
    const width = parsePositiveInteger(targets.maxWidth, "最大宽度", { optional: true });
    const height = parsePositiveInteger(targets.maxHeight, "最大高度", { optional: true });
    const bytes = parseMaxBytes(targets.maxSizeKb, { optional: true });
    const error = width.error || height.error || bytes.error;
    if (error) return { valid: false, phase: "PARAMETERS_INCOMPLETE", message: error, request: null };
    if (!width.value && !height.value && !bytes.value) {
      return { valid: false, phase: "PARAMETERS_INCOMPLETE", message: "请至少填写最大宽度、最大高度或最大文件体积中的一项。", request: null };
    }
    if (width.value) normalizedTargets.max_width = width.value;
    if (height.value) normalizedTargets.max_height = height.value;
    if (bytes.value) normalizedTargets.max_bytes = bytes.value;
  }

  return {
    valid: true,
    phase: "READY",
    message: purpose === "IMPROVE_LOW_QUALITY" ? "可以分析；当前阶段只给出后续增强建议，不会处理图片。" : "参数已就绪，点击后仅分析并推荐，不会自动处理。",
    request: { file_token: String(sourceToken), purpose, targets: normalizedTargets, requested_action: null },
  };
}

export function reasonCodeMeta(code) {
  return REASON_CODE_META[code] || {
    title: `未知规则（${String(code || "UNKNOWN")}）`,
    description: "服务返回了当前前端尚未识别的规则，已按安全方式停止执行判断。",
    severity: "danger",
    requiresAction: true,
    suggestedAction: "请重新分析或检查系统版本。",
    unknown: true,
  };
}

export function errorCodeMeta(code, httpStatus = 0) {
  if (ERROR_CODE_META[code]) return { code, ...ERROR_CODE_META[code] };
  return {
    code: String(code || `HTTP_${httpStatus || "UNKNOWN"}`),
    message: httpStatus >= 500 ? "预检服务暂时异常，请稍后重试。" : "预检返回未知错误，已停止执行判断。",
    canRetryParameters: false,
    requiresReupload: false,
    requiresFileCheck: false,
    systemError: httpStatus >= 500 || !httpStatus,
    unknown: true,
  };
}

export function preflightStatusMeta(status) {
  return PREFLIGHT_STATUS_META[status] || { label: "未知预检状态", tone: "danger", unknown: true };
}

export function preflightActionMeta(action) {
  return PREFLIGHT_ACTION_META[action] || { label: "未知推荐动作", executable: false, unknown: true };
}

const ALTERNATIVE_PARAMETER_META = Object.freeze({
  resize_strategy: { label: "缩小策略", type: "strategy" },
  target_short_side: { label: "短边", unit: "像素" },
  target_width: { label: "目标宽度", unit: "像素" },
  target_height: { label: "目标高度", unit: "像素" },
  max_width: { label: "最大宽度", unit: "像素" },
  max_height: { label: "最大高度", unit: "像素" },
  scale_ratio: { label: "缩放比例", type: "ratio" },
  max_bytes: { label: "最大文件体积", type: "bytes" },
  max_file_size_bytes: { label: "最大文件体积", type: "bytes" },
  target_file_size_bytes: { label: "目标文件体积", type: "bytes" },
});

const RESIZE_STRATEGY_LABELS = Object.freeze({
  FIXED_SHORT_SIDE: "固定短边",
  SCALE_RATIO: "按比例缩小",
  FIXED_WIDTH: "固定宽度",
  FIXED_HEIGHT: "固定高度",
});

function alternativeBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return "未识别值，请检查系统版本";
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(2)} MB`;
}

function safeUnknownFieldLabel(field) {
  const text = String(field || "")
    .replace(/[^A-Za-z0-9_\u4e00-\u9fff-]/g, "")
    .slice(0, 40)
    .replace(/_+/g, " ")
    .trim();
  return text ? `其他参数（${text}）` : "其他参数";
}

function safeVisibleText(value) {
  if (typeof value !== "string") return "";
  return value
    .replace(/[A-Za-z]:[\\/][^\s]+/g, "[路径已隐藏]")
    .replace(/file:\/\/[^\s]+/gi, "[路径已隐藏]")
    .trim()
    .slice(0, 160);
}

function alternativeValueText(value, meta) {
  if (meta?.type === "strategy") return RESIZE_STRATEGY_LABELS[value] || "未识别策略，请检查系统版本";
  if (meta?.type === "bytes") return alternativeBytes(value);
  if (meta?.type === "ratio") {
    const ratio = Number(value);
    return Number.isFinite(ratio) && ratio > 0 ? `${Math.round(ratio * 100)}%` : "未识别值，请检查系统版本";
  }
  if (typeof value === "number" && Number.isFinite(value)) return `${value}${meta?.unit || ""}`;
  if (typeof value === "boolean") return value ? "是" : "否";
  if (meta && typeof value === "string" && value.trim()) return `${value.trim().slice(0, 80)}${meta.unit || ""}`;
  return "复杂参数，请检查系统版本";
}

function parameterDisplay(field, value, { required = false } = {}) {
  const meta = ALTERNATIVE_PARAMETER_META[field];
  const label = meta?.label || safeUnknownFieldLabel(field);
  return required ? { field, label } : { field, label, valueText: alternativeValueText(value, meta) };
}

export function buildAlternativeDisplayItems(alternatives) {
  if (!Array.isArray(alternatives)) return [];
  return alternatives.map((item, index) => {
    const candidate = item && typeof item === "object" ? item : {};
    const targets = candidate.targets && typeof candidate.targets === "object" && !Array.isArray(candidate.targets)
      ? Object.entries(candidate.targets)
        .filter(([, value]) => value !== null && value !== undefined && value !== "")
        .map(([field, value]) => parameterDisplay(field, value))
      : [];
    const requiredTargets = Array.isArray(candidate.required_targets)
      ? [...new Set(candidate.required_targets)]
        .filter((field) => typeof field === "string" && field.trim())
        .map((field) => parameterDisplay(field, null, { required: true }))
      : [];
    const notes = [candidate.title, candidate.description, candidate.message, candidate.note]
      .map(safeVisibleText)
      .filter(Boolean);
    return {
      key: `${String(candidate.action || "UNKNOWN")}-${index}`,
      actionLabel: preflightActionMeta(candidate.action).label,
      targets,
      requiredTargets,
      notes,
    };
  });
}

export function AlternativeSuggestions({ alternatives }) {
  const items = buildAlternativeDisplayItems(alternatives);
  if (!items.length) return null;
  return React.createElement(
    "div",
    { className: "hdde-preflight-alternatives", "data-testid": "preflight-alternatives" },
    React.createElement("span", null, "替代建议"),
    React.createElement(
      "div",
      { "data-testid": "preflight-alternative-list" },
      items.map((item) => React.createElement(
        "div",
        { key: item.key, "data-testid": "preflight-alternative" },
        React.createElement("strong", null, item.actionLabel),
        item.targets.length
          ? React.createElement(
            "div",
            { "data-testid": "alternative-suggested-parameters" },
            React.createElement("span", null, "建议参数"),
            React.createElement("strong", null, item.targets.map((target) => `${target.label}：${target.valueText}`).join(" · ")),
          )
          : null,
        item.requiredTargets.length
          ? React.createElement(
            "div",
            { "data-testid": "alternative-required-parameters" },
            React.createElement("span", null, "仍需填写"),
            React.createElement("strong", null, item.requiredTargets.map((target) => target.label).join(" · ")),
          )
          : null,
        item.notes.map((note, noteIndex) => React.createElement("span", { key: `${item.key}-note-${noteIndex}` }, note)),
      )),
    ),
  );
}

export function canApplyRecommendation(result) {
  if (!result || result.executable !== true) return false;
  if (!Object.hasOwn(PREFLIGHT_STATUS_META, result.preflight_status)) return false;
  return ["LOSSLESS_COMPRESSION", "RESIZE_REDUCTION", "UPLOAD_ADAPTATION"].includes(result.recommended_action);
}

function numberText(value) {
  return Number.isFinite(Number(value)) ? String(Number(value)) : "";
}

export function buildRecommendationPrefill(result) {
  if (!canApplyRecommendation(result)) return null;
  const action = result.recommended_action;
  const parameters = result.recommended_parameters || {};
  if (action === "LOSSLESS_COMPRESSION") return { mode: action };
  if (action === "RESIZE_REDUCTION") {
    const strategy = parameters.resize_strategy;
    const mapping = {
      FIXED_SHORT_SIDE: { resizeStrategy: "short_side", field: "target_short_side" },
      SCALE_RATIO: { resizeStrategy: "ratio", field: "scale_ratio" },
      FIXED_WIDTH: { resizeStrategy: "width", field: "target_width" },
      FIXED_HEIGHT: { resizeStrategy: "height", field: "target_height" },
    }[strategy];
    if (!mapping || !Number.isFinite(Number(parameters[mapping.field]))) return null;
    return {
      mode: action,
      resizeStrategy: mapping.resizeStrategy,
      resizeValue: strategy === "SCALE_RATIO" ? String(Number(parameters[mapping.field]) * 100) : numberText(parameters[mapping.field]),
    };
  }
  return {
    mode: action,
    uploadLimits: {
      maxWidth: numberText(parameters.max_width),
      maxHeight: numberText(parameters.max_height),
      maxSize: parameters.max_bytes ? String(Number(parameters.max_bytes) / 1024) : "",
      sizeUnit: "KB",
    },
  };
}

export function isCurrentPreflightResponse(responseSequence, activeSequence) {
  return Number(responseSequence) === Number(activeSequence);
}
