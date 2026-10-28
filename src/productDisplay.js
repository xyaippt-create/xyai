export const PRODUCT_DISPLAY_NAMES = Object.freeze({
  enhancement1080p: "1080P画质",
  enhancement4k: "4K画质增强",
});

const LEGACY_RECOMMENDATION_ACTIONS = Object.freeze({
  "1080P普通增强": PRODUCT_DISPLAY_NAMES.enhancement1080p,
  "1080P标准增强": PRODUCT_DISPLAY_NAMES.enhancement1080p,
  "1080P安全增强": PRODUCT_DISPLAY_NAMES.enhancement1080p,
  "1080P画质增强": PRODUCT_DISPLAY_NAMES.enhancement1080p,
  "4K尺寸适配": PRODUCT_DISPLAY_NAMES.enhancement4k,
  "4K适配": PRODUCT_DISPLAY_NAMES.enhancement4k,
  "4K高清增强": PRODUCT_DISPLAY_NAMES.enhancement4k,
  "4K高清画质增强": PRODUCT_DISPLAY_NAMES.enhancement4k,
});

export function processingModeDisplayName(mode, fallback = "") {
  const normalized = String(mode || "").trim();
  if (["fidelity", "texture", "text_safe", "standard", "safe_1080p_beta"].includes(normalized)) {
    return PRODUCT_DISPLAY_NAMES.enhancement1080p;
  }
  if (normalized === "4k_v1" || normalized === "4k") return PRODUCT_DISPLAY_NAMES.enhancement4k;
  if (normalized === "AUTO_COLOR_CORRECTION" || normalized === "color_correction") return "颜色校正";
  if (normalized === "LEVEL_PICK_COLOR_CORRECTION") return "挑档校色";
  return fallback || normalized || "未选择";
}

export function processingTypeDisplayName(processingType, fallback = "") {
  const normalized = String(processingType || "").trim();
  if (normalized === "1080p") return PRODUCT_DISPLAY_NAMES.enhancement1080p;
  if (normalized === "4k") return PRODUCT_DISPLAY_NAMES.enhancement4k;
  if (normalized === "color_correction") return "颜色校正";
  if (normalized === "compression") return "图片压缩";
  if (normalized === "local_retouch") return "瑕疵修复";
  return fallback || normalized || "正式处理";
}

export function recommendationDisplayName(action) {
  const normalized = String(action || "").trim();
  return LEGACY_RECOMMENDATION_ACTIONS[normalized] || normalized;
}

export function resultConclusionFromDelivery(status, { improved = true } = {}) {
  const normalized = String(status || "").toUpperCase();
  if (["FAIL", "REJECT", "FAILED", "BLOCKED"].includes(normalized)) {
    return { label: "不可使用", tone: "danger", nextAction: "查看失败原因并重新处理" };
  }
  if (["PASS_WITH_LIMITATION", "WARNING", "NEEDS_REVIEW"].includes(normalized)) {
    return { label: "建议复核", tone: "warning", nextAction: "查看处理前后，再决定是否使用" };
  }
  if (["PASS", "SUCCESS", "COMPLETED"].includes(normalized)) {
    return { label: improved ? "已改善" : "正常", tone: "positive", nextAction: "可查看处理前后或打开成品" };
  }
  return { label: "待确认", tone: "neutral", nextAction: "等待处理完成" };
}
