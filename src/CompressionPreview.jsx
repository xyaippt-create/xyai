import React, { useEffect, useRef, useState } from "react";
import {
  PREVIEW_MODES,
  normalizedScrollPosition,
  scrollTopForRatio,
} from "./longImagePolicy.js";

const MODE_LABELS = [
  [PREVIEW_MODES.FIT_WIDTH, "适合宽度"],
  [PREVIEW_MODES.ACTUAL_SIZE, "100%"],
  [PREVIEW_MODES.OVERVIEW, "全图概览"],
];

function formatFileSize(value) {
  const size = Number(value || 0);
  if (!size) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(2)} MB`;
}

export default function CompressionPreview({
  title,
  src,
  mode,
  onModeChange,
  isLong = false,
  scrollRatio = 0,
  onScrollRatioChange,
  dimensions,
  sizeBytes,
  sourceSizeBytes,
  reductionRatio,
  fileName,
  actions,
  testId,
}) {
  const canvasRef = useRef(null);
  const programmaticScrollTopRef = useRef(null);
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !isLong) return;
    const nextScrollTop = scrollTopForRatio(scrollRatio, canvas.scrollHeight, canvas.clientHeight);
    if (Math.abs(canvas.scrollTop - nextScrollTop) <= 1) return;
    programmaticScrollTopRef.current = nextScrollTop;
    canvas.scrollTop = nextScrollTop;
  }, [isLong, mode, scrollRatio, src]);

  if (!src) return null;

  const dimensionText = dimensions?.width && dimensions?.height ? `${dimensions.width} × ${dimensions.height}` : "";
  const currentSizeText = formatFileSize(sizeBytes);
  const sourceSizeText = formatFileSize(sourceSizeBytes);
  const reductionValue = Number(reductionRatio);
  const reductionText = reductionRatio != null && Number.isFinite(reductionValue)
    ? reductionValue > 0
      ? `减少 ${(reductionValue * 100).toFixed(1)}%`
      : reductionValue < 0
        ? `增加 ${(Math.abs(reductionValue) * 100).toFixed(1)}%`
        : "大小不变"
    : "";
  const sizeText = sourceSizeText && currentSizeText
    ? `${sourceSizeText} → ${currentSizeText}${reductionText ? ` · ${reductionText}` : ""}`
    : currentSizeText;

  const jumpTo = (ratio) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.scrollTop = scrollTopForRatio(ratio, canvas.scrollHeight, canvas.clientHeight);
    onScrollRatioChange?.(ratio);
  };

  return (
    <figure
      className={`hdde-product-preview is-${mode} ${isLong ? "is-long-image" : ""} ${fullscreen ? "is-fullscreen" : ""}`}
      data-testid={testId}
    >
      <div
        ref={canvasRef}
        className="hdde-compression-preview-canvas"
        onScroll={(event) => {
          if (!isLong) return;
          const target = event.currentTarget;
          const programmaticScrollTop = programmaticScrollTopRef.current;
          if (programmaticScrollTop != null && Math.abs(target.scrollTop - programmaticScrollTop) <= 1) {
            programmaticScrollTopRef.current = null;
            return;
          }
          programmaticScrollTopRef.current = null;
          onScrollRatioChange?.(normalizedScrollPosition(target.scrollTop, target.scrollHeight, target.clientHeight));
        }}
      >
        <img src={src} alt={title} />
      </div>
      <div className="hdde-compression-preview-summary">
        <figcaption>{title}</figcaption>
        {fileName ? <small className="hdde-compression-preview-file-name" title={fileName}>{fileName}</small> : null}
        {dimensionText || sizeText ? <strong>{[dimensionText, sizeText].filter(Boolean).join(" · ")}</strong> : null}
      </div>
      <div className="hdde-compression-preview-toolbar">
        {actions ? <div className="hdde-compression-source-actions">{actions}</div> : null}
        <div className="hdde-compression-preview-modes" aria-label={`${title}查看模式`}>
          {MODE_LABELS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={mode === value ? "is-active" : ""}
              data-testid={`${testId || "preview"}-${value}`}
              onClick={() => onModeChange(value)}
            >
              {label}
            </button>
          ))}
          <button type="button" data-testid={`${testId || "preview"}-fullscreen`} onClick={() => setFullscreen((value) => !value)}>
            {fullscreen ? "退出全屏" : "全屏查看"}
          </button>
        </div>
      </div>
      {isLong ? (
        <div className="hdde-long-image-anchors" aria-label="长图快速定位">
          <button type="button" onClick={() => jumpTo(0)} data-testid={`${testId || "preview"}-top`}>顶部</button>
          <button type="button" onClick={() => jumpTo(0.5)} data-testid={`${testId || "preview"}-middle`}>中部</button>
          <button type="button" onClick={() => jumpTo(1)} data-testid={`${testId || "preview"}-bottom`}>底部</button>
          <span>{Math.round(scrollRatio * 100)}%</span>
        </div>
      ) : null}
      {mode === PREVIEW_MODES.ACTUAL_SIZE ? <small className="hdde-preview-scale-note">1 图片像素约等于 1 CSS 像素；浏览器缩放可能影响查看。</small> : null}
    </figure>
  );
}
