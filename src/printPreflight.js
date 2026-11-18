const CM_PER_INCH = 2.54;
const EIGHT_K_LONG_EDGE = 7680;
// Mirrors engine/print_upscale.py: colour sources up to 4 MP enlarged at least 1.25x are
// reconstructed by the 4K engine, which adds detail up to its native 3x.
const SR_MIN_SCALE = 1.25;
const SR_MAX_SOURCE_PIXELS = 4_000_000;
const SR_NATIVE_SCALE = 3;
const SOFT_INTERPOLATION = 2;

export function appendPrintSource(form, source) {
  if (source.resultId) form.append("result_id", source.resultId);
  else form.append("file", source.file);
}

function minimumPixels(exact) {
  // A decimal cm measurement can land just above an integral pixel in floating point.
  const nearest = Math.round(exact);
  const tolerance = Math.min(1e-7, 4 * Number.EPSILON * exact);
  return nearest > 0 && Math.abs(exact - nearest) <= tolerance ? nearest : Math.ceil(exact);
}

export function planPrintSize({ width, height }, { mode, axis, cm, ppi }) {
  const density = Number(ppi);
  const length = Number(cm);
  if (!Number.isFinite(density) || density <= 0) return { error: "请输入大于 0 的目标 PPI。" };
  if (mode === "physical" && (!Number.isFinite(length) || length <= 0)) {
    return { error: "请输入大于 0 的喷绘尺寸。" };
  }

  const byWidth = mode === "8k" ? width >= height : axis === "width";
  const sourceEdge = byWidth ? width : height;
  const otherEdge = byWidth ? height : width;
  const exactPixels = mode === "8k" ? EIGHT_K_LONG_EDGE : length * density / CM_PER_INCH;
  const target = minimumPixels(exactPixels);
  // Derive both pixel requirements before rounding either edge.
  const exactOther = exactPixels * (otherEdge / sourceEdge);
  const otherTarget = mode === "8k" ? Math.max(1, Math.round(exactOther)) : minimumPixels(exactOther);
  const physical = mode === "8k" ? target * CM_PER_INCH / density : length;
  const otherPhysical = mode === "8k" ? otherTarget * CM_PER_INCH / density : physical * otherEdge / sourceEdge;
  const effectivePpi = sourceEdge * CM_PER_INCH / physical;
  if (![target, otherTarget].every(value => Number.isSafeInteger(value) && value > 0)
      || ![physical, otherPhysical, effectivePpi].every(value => Number.isFinite(value) && value > 0)) {
    return { error: "数值超出可计算范围，请检查尺寸和目标 PPI。" };
  }
  const scale = mode === "8k" ? target / sourceEdge : Math.max(target / sourceEdge, otherTarget / otherEdge);
  const reconstructed = scale >= SR_MIN_SCALE && width * height <= SR_MAX_SOURCE_PIXELS;
  const detailScale = reconstructed ? Math.min(scale, SR_NATIVE_SCALE) : Math.min(scale, 1);
  return {
    cmWidth: byWidth ? physical : otherPhysical,
    cmHeight: byWidth ? otherPhysical : physical,
    pixelWidth: byWidth ? target : otherTarget,
    pixelHeight: byWidth ? otherTarget : target,
    effectivePpi,
    scale,
    nominalPpi: density,
    reconstructed,
    // Detail density of the print after reconstruction, never above the requested PPI.
    detailPpi: Math.min(density, effectivePpi * detailScale),
    interpolation: scale / Math.max(detailScale, 1),
    soft: scale / Math.max(detailScale, 1) > SOFT_INTERPOLATION,
  };
}
