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
