const DEFAULT_VIEWPORT_PADDING = 16;
const DEFAULT_PREVIEW_GAP = 12;
const DEFAULT_PREVIEW_WIDTH = 480;
// Match the preview's 10px padding and 1px border on each side.
const PREVIEW_CHROME = 22;

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum);
}

export function calculateOutputHoverPreviewPosition({
  anchorRect,
  viewportWidth,
  viewportHeight,
  imageWidth = 0,
  imageHeight = 0,
  viewportPadding = DEFAULT_VIEWPORT_PADDING,
  previewGap = DEFAULT_PREVIEW_GAP,
  previewWidth = DEFAULT_PREVIEW_WIDTH,
}) {
  const safeViewportWidth = Math.max(0, Number(viewportWidth) || 0);
  const safeViewportHeight = Math.max(0, Number(viewportHeight) || 0);
  const availableWidth = Math.max(0, safeViewportWidth - (viewportPadding * 2));
  const aspectRatio = imageWidth > 0 && imageHeight > 0 ? imageHeight / imageWidth : 0.75;
  const availableHeight = Math.max(
    0,
    Math.min(safeViewportHeight - (viewportPadding * 2), safeViewportHeight * 0.7),
  );
  const imageWidthLimit = Math.max(0, Math.min(previewWidth, availableWidth) - PREVIEW_CHROME);
  const imageHeightLimit = Math.max(0, availableHeight - PREVIEW_CHROME);
  const fittedImageWidth = Math.min(imageWidthLimit, imageHeightLimit / aspectRatio);
  const width = Math.min(availableWidth, fittedImageWidth + PREVIEW_CHROME);
  const height = Math.min(availableHeight, fittedImageWidth * aspectRatio + PREVIEW_CHROME);
  const rightCandidate = anchorRect.right + previewGap;
  const leftCandidate = anchorRect.left - previewGap - width;
  const fitsRight = rightCandidate + width <= safeViewportWidth - viewportPadding;
  const fitsLeft = leftCandidate >= viewportPadding;
  let placement = "right";
  let left = rightCandidate;

  if (!fitsRight && fitsLeft) {
    placement = "left";
    left = leftCandidate;
  } else if (!fitsRight) {
    const rightSpace = safeViewportWidth - anchorRect.right;
    const leftSpace = anchorRect.left;
    placement = rightSpace >= leftSpace ? "right-clamped" : "left-clamped";
    left = placement === "right-clamped" ? rightCandidate : leftCandidate;
  }

  const maximumLeft = Math.max(viewportPadding, safeViewportWidth - viewportPadding - width);
  const maximumTop = Math.max(viewportPadding, safeViewportHeight - viewportPadding - height);
  const centeredTop = anchorRect.top + ((anchorRect.height - height) / 2);

  return {
    left: clamp(left, viewportPadding, maximumLeft),
    top: clamp(centeredTop, viewportPadding, maximumTop),
    width,
    height,
    placement,
  };
}
