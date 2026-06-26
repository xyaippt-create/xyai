const LIMITATION_STATUS = "PASS_WITH_LIMITATION";

const LIMITATION_REASON_TOKENS = [
  "PASS_WITH_LIMITATION",
  "manual_review",
  "quality_1080p_gate_not_fully_passed",
  "smooth_region_guard",
  "very_large_size_limited_benefit",
  "limited_benefit",
  "size_guard",
  "quality_gate_not_fully_passed",
];

function readNumber(payload, key) {
  const value = payload?.[key];
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function hasLimitationReason(payload) {
  const text = [
    payload?.final_delivery_status,
    payload?.final_delivery_reason,
    payload?.final_delivery_risk_level,
    payload?.final_delivery_recommended_usage,
    payload?.quality_1080p_level,
    payload?.phase6_size_fallback_reason,
    payload?.phase6_smooth_region_fallback_reason,
    payload?.phase4_fallback_reason,
    payload?.warnings,
  ]
    .flat()
    .filter(Boolean)
    .join(" ");
  return LIMITATION_REASON_TOKENS.some((token) => text.includes(token));
}

export function resolveDeliveryStatus(...sources) {
  const payload = Object.assign({}, ...sources.filter(Boolean));
  const rawStatus = String(payload.final_delivery_status || payload.delivery_status || "").toUpperCase();
  const textScore = readNumber(payload, "text_clarity_score");
  const textureScore = readNumber(payload, "texture_score");
  const edgeScore = readNumber(payload, "edge_quality_score");
  const lowScore =
    (textScore !== null && textScore < 60) ||
    (textureScore !== null && textureScore < 60) ||
    (edgeScore !== null && edgeScore < 65);
  const limited = rawStatus === LIMITATION_STATUS || lowScore || hasLimitationReason(payload);

  if (rawStatus === "FAIL" || rawStatus === "REJECT") {
    return {
      status: "FAIL",
      label: "不建议交付",
      badge: "不建议交付",
      tone: "#ff8a8a",
      border: "#5a2525",
      description: "系统检测到交付风险，不建议作为正式成品使用。",
      limited,
    };
  }

  if (limited) {
    return {
      status: LIMITATION_STATUS,
      label: "建议人工复核",
      badge: "1080P 本地预览",
      tone: "#f0c36f",
      border: "#66532d",
      description: "成品已生成，但存在质量门、体积收益比、低分指标或保护策略限制，正式使用前建议人工查看。",
      limited: true,
    };
  }

  if (rawStatus === "PASS") {
    return {
      status: "PASS",
      label: "可交付",
      badge: "1080P 高清成品",
      tone: "#8be6b1",
      border: "#315342",
      description: "最终交付门通过，可用于 1080P 本地交付。",
      limited: false,
    };
  }

  return {
    status: "WAITING",
    label: "等待判定",
    badge: "1080P 本地预览",
    tone: "#6e7d80",
    border: "#263738",
    description: "等待后端交付状态或人工确认。",
    limited: false,
  };
}

export function getDeliveryLabel(...sources) {
  return resolveDeliveryStatus(...sources).label;
}

function normalizedText(payload) {
  return [
    payload?.final_delivery_status,
    payload?.final_delivery_reason,
    payload?.final_delivery_risk_level,
    payload?.final_delivery_recommended_usage,
    payload?.quality_1080p_level,
    payload?.phase6_size_fallback_reason,
    payload?.phase6_smooth_region_fallback_reason,
    payload?.phase4_fallback_reason,
    payload?.warnings,
  ]
    .flat()
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

export function resolveImageTypeTag(...sources) {
  const payload = Object.assign({}, ...sources.filter(Boolean));
  const imageType = String(payload.image_type || payload.imageType || "unknown").toLowerCase();
  const hasAlpha = payload.has_alpha === true || payload.has_real_alpha === true || payload.alpha_used === true;

  if (hasAlpha) return { label: "透明 PNG", detail: "包含 Alpha 或透明边缘，优先保护透明通道。", tone: "#8be6b1" };
  if (imageType.includes("text")) return { label: "中文文字 / 海报", detail: "文字、小字、图标和版式边缘优先保护。", tone: "#f0c36f" };
  if (imageType.includes("product") || imageType.includes("kv")) return { label: "产品 / 品牌 KV", detail: "优先保护 Logo、包装字、品牌色和高光。", tone: "#8effed" };
  if (imageType.includes("portrait") || imageType.includes("person") || imageType.includes("face")) return { label: "人物 / 商业照片", detail: "优先保护人脸、肤色、手部和身份特征。", tone: "#d6b4ff" };
  if (imageType.includes("architecture") || imageType.includes("building")) return { label: "建筑 / 空间", detail: "重点观察结构线、天空交界和低频墙面。", tone: "#9cc7ff" };
  if (imageType.includes("gradient") || imageType.includes("synthetic")) return { label: "合成渐变 / 高光", detail: "重点保护渐变、色带、高光和品牌色气质。", tone: "#f0c36f" };
  if (imageType.includes("landscape")) return { label: "风景 / 场景", detail: "重点观察低频天空、地面纹理和远景层次。", tone: "#8be6b1" };

  return { label: "普通图像", detail: "未命中特定高风险类型，按通用 1080P 保真规则评估。", tone: "#94a3b8" };
}

export function resolveReviewReasonTags(...sources) {
  const payload = Object.assign({}, ...sources.filter(Boolean));
  const text = normalizedText(payload);
  const textScore = readNumber(payload, "text_clarity_score");
  const textureScore = readNumber(payload, "texture_score");
  const edgeScore = readNumber(payload, "edge_quality_score");
  const colorScore = readNumber(payload, "color_fidelity_score");
  const sizeGrowth = readNumber(payload, "phase6_size_growth_ratio") ?? readNumber(payload, "file_size_ratio");
  const visibleBenefit = readNumber(payload, "phase6_visible_benefit_score");
  const tags = [];

  if (textScore !== null && textScore < 60) {
    tags.push({ label: "文字清晰度偏低", detail: `text_clarity_score=${textScore.toFixed(2)}，正式使用前建议查看小字和 Logo。` });
  }
  if (textureScore !== null && textureScore < 60) {
    tags.push({ label: "材质收益偏弱", detail: `texture_score=${textureScore.toFixed(2)}，可能更偏保护而非明显增强。` });
  }
  if (edgeScore !== null && edgeScore < 65) {
    tags.push({ label: "边缘质量需复核", detail: `edge_quality_score=${edgeScore.toFixed(2)}，建议查看文字边、产品边和高光边缘。` });
  }
  if (sizeGrowth !== null && visibleBenefit !== null && sizeGrowth > 10 && visibleBenefit < 3) {
    tags.push({ label: "体积收益比偏低", detail: `体积倍率 ${sizeGrowth.toFixed(2)}，可见收益 ${visibleBenefit.toFixed(2)}，建议人工判断是否值得采用。` });
  } else if (sizeGrowth !== null && sizeGrowth > 30) {
    tags.push({ label: "文件体积增长明显", detail: `体积倍率 ${sizeGrowth.toFixed(2)}，建议确认交付场景是否接受。` });
  }
  if (text.includes("quality_1080p_gate_not_fully_passed") || text.includes("quality_gate_not_fully_passed")) {
    tags.push({ label: "1080P 质量门未完全通过", detail: "后端已输出成品，但前台按 RC1 规则提示复核。" });
  }
  if (text.includes("smooth_region_guard") || payload.phase6_smooth_region_fallback === true) {
    tags.push({ label: "平滑区域保护触发", detail: "天空、白底、渐变或低频区域采用更保守保护策略。" });
  }
  if (text.includes("very_large_size_limited_benefit") || text.includes("limited_benefit")) {
    tags.push({ label: "可见收益有限", detail: "系统检测到增强收益有限，建议查看 100% 局部细节后决定。" });
  }
  if (payload.brand_color_risk === true || payload.phase5_color_drift_detected === true || (colorScore !== null && colorScore < 95)) {
    tags.push({ label: "颜色 / 品牌色需确认", detail: "默认保真色彩稳定已启用，品牌色或风格色仍建议人工查看。" });
  }

  if (!tags.length) {
    tags.push({ label: "暂无明确复核风险", detail: "当前没有命中低分、体积或保护类限制原因。" });
  }

  return tags;
}

export function resolveBenefitTag(...sources) {
  const payload = Object.assign({}, ...sources.filter(Boolean));
  const delivery = resolveDeliveryStatus(payload);
  const visibleBenefit = readNumber(payload, "phase6_visible_benefit_score");
  const clarityScore = readNumber(payload, "clarity_score");
  const textureScore = readNumber(payload, "texture_score");
  const sizeGrowth = readNumber(payload, "phase6_size_growth_ratio") ?? readNumber(payload, "file_size_ratio");

  if (delivery.status === "FAIL") {
    return { label: "不建议通过", detail: "当前结果存在交付风险，不建议作为正式成品使用。", tone: "#ff8a8a" };
  }
  if (delivery.status === LIMITATION_STATUS) {
    if (sizeGrowth !== null && sizeGrowth > 10 && (visibleBenefit === null || visibleBenefit < 3)) {
      return { label: "低收益提示", detail: "成品已生成，但体积增长或指标限制使收益需要人工确认。", tone: "#f0c36f" };
    }
    return { label: "建议人工复核", detail: "成品可预览，但正式使用前应查看关键局部。", tone: "#f0c36f" };
  }
  if ((visibleBenefit !== null && visibleBenefit >= 4) || (clarityScore !== null && clarityScore >= 85 && textureScore !== null && textureScore >= 60)) {
    return { label: "明显提升", detail: "指标显示清晰度或材质收益较明确，仍建议查看局部确认。", tone: "#8be6b1" };
  }
  if ((visibleBenefit !== null && visibleBenefit >= 2) || (clarityScore !== null && clarityScore >= 70)) {
    return { label: "轻微提升", detail: "画质有一定改善，但不应理解为强效果重绘。", tone: "#8effed" };
  }
  return { label: "保护通过", detail: "当前更偏保真保护，变化较小属于可接受结果。", tone: "#94a3b8" };
}

export function resolveReportCenterMeta(...sources) {
  const payload = Object.assign({}, ...sources.filter(Boolean));
  const delivery = resolveDeliveryStatus(payload);
  const imageType = resolveImageTypeTag(payload);
  const reviewReasons = resolveReviewReasonTags(payload);
  const benefit = resolveBenefitTag(payload);
  const limitationExplanation =
    delivery.status === LIMITATION_STATUS
      ? "“建议人工复核”不是失败。它表示成品已生成，但文字、材质、边缘、体积收益比或保护策略触发了 RC1 保守交付提示，正式使用前建议人工查看。"
      : delivery.status === "PASS"
        ? "当前结果满足前台 RC1 可交付口径，可作为 1080P 高清成品查看。"
        : delivery.status === "FAIL"
          ? "当前结果不建议交付，需要回到原图或调整输入后重新处理。"
          : "当前仍在等待后端任务或质量字段。";

  return {
    delivery,
    imageType,
    reviewReasons,
    benefit,
    limitationExplanation,
  };
}
