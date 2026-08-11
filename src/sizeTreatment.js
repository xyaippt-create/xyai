function validDimension(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

export function resolve1080pSizeTreatment({
  inputWidth,
  inputHeight,
  outputWidth,
  outputHeight,
  modeLabel = "当前模式",
} = {}) {
  const sourceWidth = validDimension(inputWidth);
  const sourceHeight = validDimension(inputHeight);
  const resultWidth = validDimension(outputWidth);
  const resultHeight = validDimension(outputHeight);

  if (!sourceWidth || !sourceHeight || !resultWidth || !resultHeight) return null;

  const input = `${sourceWidth} × ${sourceHeight}`;
  const output = `${resultWidth} × ${resultHeight}`;
  const preserved = sourceWidth === resultWidth && sourceHeight === resultHeight;
  const upscaled = resultWidth > sourceWidth || resultHeight > sourceHeight;

  if (preserved && Math.min(sourceWidth, sourceHeight) >= 1080) {
    return {
      state: "preserved",
      label: "已达到1080P门槛、保留原尺寸、未执行像素放大",
      detail: `${input} → ${output}；${modeLabel}的尺寸处理与画质增强分别执行。`,
    };
  }

  if (upscaled) {
    return {
      state: "upscaled",
      label: "短边低于1080px，已按原比例放大至1080P门槛",
      detail: `${input} → ${output}；${modeLabel}的尺寸处理与画质增强分别执行。`,
    };
  }

  return {
    state: "adjusted",
    label: preserved ? "已保留原尺寸" : "已按交付规格调整尺寸",
    detail: `${input} → ${output}；${modeLabel}的尺寸处理与画质增强分别执行。`,
  };
}
