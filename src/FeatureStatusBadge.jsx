import React from "react";
import { getFeatureStatusMeta } from "./platformStatus.js";

export default function FeatureStatusBadge({ status, compact = false, source = "FeatureStatusBadge" }) {
  const meta = getFeatureStatusMeta(status, source);
  return (
    <span
      className={`hdde-feature-status ${compact ? "hdde-feature-status--compact" : ""}`}
      data-status-tone={meta.tone}
      aria-label={`功能状态：${meta.label}`}
    >
      {meta.label}
    </span>
  );
}
