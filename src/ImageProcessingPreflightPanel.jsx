import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  PREFLIGHT_PURPOSES,
  AlternativeSuggestions,
  buildPreflightRequestPlan,
  canApplyRecommendation,
  errorCodeMeta,
  isCurrentPreflightResponse,
  preflightActionMeta,
  preflightStatusMeta,
  reasonCodeMeta,
} from "./imageProcessingPreflight.js";

const INITIAL_TARGETS = Object.freeze({
  resizeStrategy: "FIXED_SHORT_SIDE",
  resizeValue: "",
  maxWidth: "",
  maxHeight: "",
  maxSizeKb: "",
});

const ORIENTATION_LABELS = Object.freeze({ LANDSCAPE: "横向", PORTRAIT: "纵向", SQUARE: "方形" });
const ELIGIBILITY_LABELS = Object.freeze({ ELIGIBLE: "可进入预检", ELIGIBLE_WITH_WARNING: "可进入预检，但有提示", UNSUPPORTED: "当前不支持处理" });
const RESOLUTION_LABELS = Object.freeze({
  SHORT_SIDE_LT_600: "短边低于600像素",
  SHORT_SIDE_600_1079: "短边600—1079像素",
  SHORT_SIDE_1080_1439: "短边1080—1439像素",
  SHORT_SIDE_1440_2159: "短边1440—2159像素",
  SHORT_SIDE_2160_4319: "短边2160—4319像素",
  SHORT_SIDE_GE_4320: "短边不低于4320像素",
});

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(2)} MB`;
}

function BooleanText({ value }) {
  return <>{value ? "是" : "否"}</>;
}

function ProfileGrid({ profile }) {
  const rows = [
    ["图片格式", profile.format || "—"],
    ["MIME类型", profile.mime_type || "—"],
    ["原始尺寸", `${profile.width} × ${profile.height}`],
    ["短边 / 长边", `${profile.short_side} / ${profile.long_side} px`],
    ["宽高比", profile.aspect_ratio ?? "—"],
    ["图片方向", ORIENTATION_LABELS[profile.orientation] || profile.orientation || "—"],
    ["文件体积", formatBytes(profile.size_bytes)],
    ["透明通道", <BooleanText value={profile.has_alpha} />],
    ["动画 / 多帧", `${profile.is_animated ? "动画" : "非动画"} · ${Number(profile.frame_count || 1)} 帧`],
    ["长图", <BooleanText value={profile.is_long_image} />],
    ["超宽图", <BooleanText value={profile.is_ultra_wide} />],
    ["像素层级", RESOLUTION_LABELS[profile.resolution_bucket] || profile.resolution_bucket || "—"],
    ["处理资格", ELIGIBILITY_LABELS[profile.processing_eligibility] || profile.processing_eligibility || "—"],
  ];
  return (
    <div className="hdde-preflight-profile" data-testid="preflight-profile">
      {rows.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}
    </div>
  );
}

function ReasonCards({ result }) {
  const codes = [...new Set([
    ...(result.reason_codes || []),
    ...(result.blocking_reasons || []),
    ...(result.warnings || []),
  ])];
  if (!codes.length) return null;
  return (
    <div className="hdde-preflight-reasons" data-testid="preflight-reasons">
      {codes.map((code) => {
        const meta = reasonCodeMeta(code);
        return (
          <article key={code} data-tone={meta.severity}>
            <div><strong>{meta.title}</strong><small>{code}</small></div>
            <p>{meta.description}</p>
            <span>{meta.requiresAction ? "需要操作" : "信息提示"} · {meta.suggestedAction}</span>
          </article>
        );
      })}
    </div>
  );
}

function EstimatedOutput({ result }) {
  const output = result.estimated_output || {};
  const alternatives = Array.isArray(result.alternatives) ? result.alternatives : [];
  return (
    <div className="hdde-preflight-estimate" data-testid="preflight-estimate">
      <div><span>预计尺寸</span><strong>{output.width && output.height ? `${output.width} × ${output.height}` : "暂不适用"}</strong></div>
      <div><span>预计短边</span><strong>{output.short_side ?? "暂不适用"}</strong></div>
      <div><span>预计长边</span><strong>{output.long_side ?? "暂不适用"}</strong></div>
      <div><span>最大体积目标</span><strong>{output.max_bytes ? formatBytes(output.max_bytes) : "未设置"}</strong></div>
      <AlternativeSuggestions alternatives={alternatives} />
    </div>
  );
}

function ErrorState({ error, onReplaceImage }) {
  const meta = errorCodeMeta(error?.code, error?.httpStatus);
  const actions = [
    meta.canRetryParameters ? "可修改参数后重试" : "不建议原样重试",
    meta.requiresReupload ? "需要重新上传" : "无需重新上传",
    meta.requiresFileCheck ? "需要检查图片文件" : "无需检查图片文件",
    meta.systemError ? "属于系统异常" : "不属于系统异常",
  ];
  return (
    <div className="hdde-preflight-error" role="alert" data-testid="preflight-error">
      <strong>{meta.message}</strong>
      <span>{actions.join(" · ")}</span>
      <small>{meta.code}</small>
      {meta.requiresReupload ? <button type="button" className="hdde-secondary-action" onClick={onReplaceImage}>重新选择图片</button> : null}
    </div>
  );
}

export default function ImageProcessingPreflightPanel({ fileInfo, request, onApplyRecommendation, onReplaceImage }) {
  const [purpose, setPurpose] = useState("");
  const [targets, setTargets] = useState(INITIAL_TARGETS);
  const [outcome, setOutcome] = useState({ status: "IDLE", result: null, error: null, notice: "" });
  const sequenceRef = useRef(0);
  const controllerRef = useRef(null);

  const plan = useMemo(() => buildPreflightRequestPlan({
    sourceToken: fileInfo?.source_token,
    purpose,
    targets,
  }), [fileInfo?.source_token, purpose, targets]);

  useEffect(() => {
    controllerRef.current?.abort();
    sequenceRef.current += 1;
    setOutcome((current) => current.status === "SUCCESS"
      ? { status: "STALE", result: null, error: null, notice: "图片已更换，原推荐结果已失效。" }
      : { status: "IDLE", result: null, error: null, notice: "" });
  }, [fileInfo?.source_token]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const invalidate = (notice) => {
    controllerRef.current?.abort();
    sequenceRef.current += 1;
    setOutcome((current) => (current.status === "SUCCESS" || current.status === "LOADING")
      ? { status: "STALE", result: null, error: null, notice }
      : { status: "IDLE", result: null, error: null, notice: "" });
  };

  const changePurpose = (value) => {
    setPurpose(value);
    invalidate("处理目的已修改，原推荐结果已失效。");
  };

  const changeTarget = (field, value) => {
    setTargets((current) => ({ ...current, [field]: value }));
    invalidate("目标参数已修改，原推荐结果已失效。");
  };

  const analyze = async () => {
    if (!plan.valid || typeof request !== "function") return;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const sequence = sequenceRef.current + 1;
    sequenceRef.current = sequence;
    setOutcome({ status: "LOADING", result: null, error: null, notice: "" });
    try {
      const payload = await request("/api/image-processing/preflight", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(plan.request),
        signal: controller.signal,
      });
      if (!isCurrentPreflightResponse(sequence, sequenceRef.current)) return;
      setOutcome({ status: "SUCCESS", result: payload?.data || payload, error: null, notice: "" });
    } catch (reason) {
      if (reason?.name === "AbortError" || !isCurrentPreflightResponse(sequence, sequenceRef.current)) return;
      setOutcome({ status: "ERROR", result: null, error: reason, notice: "" });
    }
  };

  const applyRecommendation = () => {
    if (!canApplyRecommendation(outcome.result)) return;
    const applied = onApplyRecommendation?.(outcome.result) === true;
    if (applied) setOutcome((current) => ({ ...current, notice: "推荐方案已预填到现有处理区域，请检查参数后再主动执行。" }));
  };

  const statusMessage = !fileInfo
    ? "请先上传图片，再选择处理目的。"
    : !purpose
      ? "图片已就绪，请选择本次真实处理目的。"
      : !plan.valid
        ? plan.message
        : outcome.status === "LOADING"
          ? "正在分析图片画像与处理路由…"
          : outcome.status === "STALE"
            ? outcome.notice
            : plan.message;

  const result = outcome.result;
  const statusMeta = result ? preflightStatusMeta(result.preflight_status) : null;
  const actionMeta = result ? preflightActionMeta(result.recommended_action) : null;
  const applyAllowed = canApplyRecommendation(result);

  return (
    <section className="hdde-preflight-panel" aria-label="图片分析与处理建议" data-testid="preflight-panel">
      <header className="hdde-preflight-heading">
        <div><span className="hdde-compression-section-label">阶段5预检</span><h2>图片分析与处理建议</h2></div>
        <p>只分析、推荐和预填参数；不会自动处理、生成输出或下载文件。</p>
      </header>

      <div className="hdde-preflight-purpose" role="group" aria-label="处理目的">
        {PREFLIGHT_PURPOSES.map((item) => (
          <button
            key={item.value}
            type="button"
            aria-pressed={purpose === item.value}
            data-testid={`preflight-purpose-${item.value.toLowerCase()}`}
            className={purpose === item.value ? "is-selected" : ""}
            onClick={() => changePurpose(item.value)}
            disabled={outcome.status === "LOADING"}
          >
            <strong>{item.label}</strong><span>{item.description}</span>
          </button>
        ))}
      </div>

      {purpose ? <div className="hdde-preflight-targets" data-testid="preflight-targets">
        {purpose === "REDUCE_FILE_SIZE" ? (
          <label>最大文件体积（KB，可选）<input data-testid="preflight-file-size" type="number" min="0.01" step="0.01" value={targets.maxSizeKb} onChange={(event) => changeTarget("maxSizeKb", event.target.value)} /></label>
        ) : null}
        {purpose === "REDUCE_DIMENSIONS" ? <>
          <label>缩小策略<select data-testid="preflight-resize-strategy" value={targets.resizeStrategy} onChange={(event) => changeTarget("resizeStrategy", event.target.value)}>
            <option value="FIXED_SHORT_SIDE">固定短边</option>
            <option value="SCALE_RATIO">等比例缩小</option>
            <option value="FIXED_WIDTH">固定宽度</option>
            <option value="FIXED_HEIGHT">固定高度</option>
          </select></label>
          <label>{targets.resizeStrategy === "SCALE_RATIO" ? "缩放比例（%）" : targets.resizeStrategy === "FIXED_SHORT_SIDE" ? "目标短边（px）" : targets.resizeStrategy === "FIXED_WIDTH" ? "目标宽度（px）" : "目标高度（px）"}<input data-testid="preflight-resize-value" type="number" min="1" step="1" value={targets.resizeValue} onChange={(event) => changeTarget("resizeValue", event.target.value)} /></label>
        </> : null}
        {purpose === "MEET_UPLOAD_LIMITS" ? <>
          <label>最大宽度（px）<input data-testid="preflight-max-width" type="number" min="1" step="1" value={targets.maxWidth} onChange={(event) => changeTarget("maxWidth", event.target.value)} /></label>
          <label>最大高度（px）<input data-testid="preflight-max-height" type="number" min="1" step="1" value={targets.maxHeight} onChange={(event) => changeTarget("maxHeight", event.target.value)} /></label>
          <label>最大文件体积（KB）<input data-testid="preflight-max-size" type="number" min="0.01" step="0.01" value={targets.maxSizeKb} onChange={(event) => changeTarget("maxSizeKb", event.target.value)} /></label>
        </> : null}
        {purpose === "IMPROVE_LOW_QUALITY" ? <p>高清增强能力将在后续版本接入；当前阶段不会自动处理或生成文件。</p> : null}
      </div> : null}

      <div className="hdde-preflight-request-row">
        <div className={`hdde-preflight-state is-${outcome.status.toLowerCase()}`} role="status" data-testid="preflight-state">{statusMessage}</div>
        <button type="button" className="hdde-primary-action" data-testid="preflight-analyze" onClick={analyze} disabled={!plan.valid || outcome.status === "LOADING"}>{outcome.status === "LOADING" ? "正在分析…" : "分析并推荐"}</button>
      </div>

      {outcome.status === "ERROR" ? <ErrorState error={outcome.error} onReplaceImage={onReplaceImage} /> : null}

      {result ? <div className="hdde-preflight-result" data-testid="preflight-result">
        <div className="hdde-preflight-summary" data-tone={statusMeta.tone}>
          <div><span>推荐状态</span><strong>{statusMeta.label}</strong><small>{result.preflight_status}</small></div>
          <div><span>推荐动作</span><strong>{actionMeta.label}</strong><small>{result.recommended_action}</small></div>
          <div><span>是否允许执行</span><strong>{result.executable === true && !statusMeta.unknown && !actionMeta.unknown ? "允许用户继续" : "不可执行"}</strong><small>预检不会自动执行</small></div>
        </div>
        {result.profile ? <ProfileGrid profile={result.profile} /> : null}
        <ReasonCards result={result} />
        <EstimatedOutput result={result} />
        {result.recommended_action === "NO_PROCESSING" ? <p className="hdde-preflight-next-step">当前图片已经满足目标，建议直接使用原图；不会重新编码。</p> : null}
        {result.recommended_action === "FUTURE_ENHANCEMENT" ? <p className="hdde-preflight-next-step">高清增强功能后续接入，本阶段没有可点击的执行入口。</p> : null}
        {!applyAllowed && !["NO_PROCESSING", "FUTURE_ENHANCEMENT"].includes(result.recommended_action) ? <p className="hdde-preflight-next-step">请根据阻止原因修改目标或更换受支持的图片；当前推荐不会启用处理入口。</p> : null}
        {applyAllowed ? <button type="button" className="hdde-secondary-action hdde-preflight-apply" data-testid="preflight-apply" onClick={applyRecommendation}>使用推荐方案</button> : null}
        {outcome.notice ? <p className="hdde-preflight-notice" role="status">{outcome.notice}</p> : null}
      </div> : null}
    </section>
  );
}
