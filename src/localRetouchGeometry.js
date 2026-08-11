export function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

export function fitImageView(imageWidth, imageHeight, viewportWidth, viewportHeight, padding = 32) {
  const availableWidth = Math.max(1, viewportWidth - padding * 2);
  const availableHeight = Math.max(1, viewportHeight - padding * 2);
  const scale = clamp(Math.min(availableWidth / imageWidth, availableHeight / imageHeight), 0.05, 8);
  return {
    scale,
    offsetX: (viewportWidth - imageWidth * scale) / 2,
    offsetY: (viewportHeight - imageHeight * scale) / 2,
  };
}

export function screenToImage(point, view, imageSize, clampToImage = true) {
  const raw = {
    x: (point.x - view.offsetX) / view.scale,
    y: (point.y - view.offsetY) / view.scale,
  };
  if (!clampToImage) return raw;
  return {
    x: clamp(raw.x, 0, imageSize.width),
    y: clamp(raw.y, 0, imageSize.height),
  };
}

export function imageToScreen(point, view) {
  return {
    x: view.offsetX + point.x * view.scale,
    y: view.offsetY + point.y * view.scale,
  };
}

export function zoomViewAt(view, screenPoint, nextScale) {
  const scale = clamp(nextScale, 0.05, 8);
  const anchorX = (screenPoint.x - view.offsetX) / view.scale;
  const anchorY = (screenPoint.y - view.offsetY) / view.scale;
  return {
    scale,
    offsetX: screenPoint.x - anchorX * scale,
    offsetY: screenPoint.y - anchorY * scale,
  };
}

export function normalizedRect(first, second, imageSize) {
  const x1 = clamp(Math.min(first.x, second.x), 0, imageSize.width);
  const y1 = clamp(Math.min(first.y, second.y), 0, imageSize.height);
  const x2 = clamp(Math.max(first.x, second.x), 0, imageSize.width);
  const y2 = clamp(Math.max(first.y, second.y), 0, imageSize.height);
  return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
}
