const PRESERVE_FORMAT = "PRESERVE_FORMAT";
const DELIVERY_OPTIMIZATION = "DELIVERY_OPTIMIZATION";
const MIN_USEFUL_SOURCE_BYTES = 256 * 1024;
const MIN_USEFUL_PIXELS = 480_000;
const LIMITED_RATIO = 0.08;
const LIMITED_SAVED_BYTES = 128 * 1024;

function normalizedFormat(value) {
  const format = String(value || "").trim().toUpperCase();
  return format === "JPEG" ? "JPG" : format;
}

function positiveNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : null;
}

function imagePixels(dimensions) {
  const width = positiveNumber(dimensions?.width);
  const height = positiveNumber(dimensions?.height);
  return width && height ? width * height : 0;
}

function hasLimitedBenefit(result, winner) {
  if (winner?.source_selected) return true;
  const sourceBytes = positiveNumber(result?.source_size_bytes);
  const resultBytes = positiveNumber(result?.output_size_bytes ?? winner?.file_size);
  if (!sourceBytes || resultBytes == null) return false;
  const savedBytes = Math.max(0, sourceBytes - resultBytes);
  const ratio = savedBytes / sourceBytes;
  return (
    sourceBytes >= MIN_USEFUL_SOURCE_BYTES
    && imagePixels(result?.source_dimensions) >= MIN_USEFUL_PIXELS
    && ratio < LIMITED_RATIO
    && savedBytes < LIMITED_SAVED_BYTES
  );
}

/**
 * Build a deterministic, evidence-only suggestion from the completed result.
 * This never estimates another format and never starts another conversion.
 */
export function buildCompressionAdvice({ result, winner, operationMode, targetFormat }) {
  if (
    !result
    || !winner
    || operationMode !== DELIVERY_OPTIMIZATION
    || String(targetFormat || "").toUpperCase() !== PRESERVE_FORMAT
  ) return null;

  const sourceFormat = normalizedFormat(result.source_format);
  const outputFormat = normalizedFormat(result.output_format || winner.format || sourceFormat);
  if (!sourceFormat || outputFormat !== sourceFormat || !hasLimitedBenefit(result, winner)) return null;

  const keepOriginal = winner.source_selected === true;
  const sourceBytes = positiveNumber(result.source_size_bytes) || 0;
  const pixels = imagePixels(result.source_dimensions);
  const hasAlpha = result?.alpha_details?.alpha_present === true;
  const base = keepOriginal
    ? "当前图片已较紧凑，未生成更小且符合质量要求的新文件。"
    : `当前保持 ${sourceFormat} 格式，压缩收益有限。`;

  if (sourceFormat === "PNG" && sourceBytes >= MIN_USEFUL_SOURCE_BYTES && pixels >= MIN_USEFUL_PIXELS) {
    return {
      kind: keepOriginal ? "KEEP_ORIGINAL" : "LIMITED_PNG",
      title: base,
      detail: hasAlpha
        ? "如需保留透明区域且更看重文件体积，可尝试 WebP。"
        : "如更看重文件体积，可尝试 JPG 或 WebP；实际结果以重新处理后的质量检查为准。",
      actions: hasAlpha
        ? [{ targetFormat: "WEBP", label: "选择 WebP 格式" }]
        : [
            { targetFormat: "JPEG", label: "选择 JPG 格式" },
            { targetFormat: "WEBP", label: "选择 WebP 格式" },
          ],
    };
  }

  if (sourceFormat === "JPG" && keepOriginal && sourceBytes >= 1024 * 1024 && pixels >= 1_000_000) {
    return {
      kind: "KEEP_ORIGINAL",
      title: base,
      detail: "如交付环境支持 WebP，可将其作为另一个方向尝试；不保证一定更小。",
      actions: [{ targetFormat: "WEBP", label: "选择 WebP 格式" }],
    };
  }

  if (keepOriginal) {
    return {
      kind: "KEEP_ORIGINAL",
      title: base,
      detail: "可以继续使用原图，或调整当前参数后重新处理。",
      actions: [],
    };
  }

  return null;
}

export const COMPRESSION_ADVICE_POLICY = Object.freeze({
  systemAutoOnly: true,
  autoConversion: false,
  minimumSourceBytes: MIN_USEFUL_SOURCE_BYTES,
  minimumPixels: MIN_USEFUL_PIXELS,
  limitedRatio: LIMITED_RATIO,
  limitedSavedBytes: LIMITED_SAVED_BYTES,
});
