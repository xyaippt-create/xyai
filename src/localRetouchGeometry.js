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

export function pointInImage(point, imageSize) {
  return point.x >= 0 && point.x <= imageSize.width && point.y >= 0 && point.y <= imageSize.height;
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

export function sourcePixelRect(rect, imageSize) {
  const x1 = clamp(Math.floor(rect.x), 0, imageSize.width);
  const y1 = clamp(Math.floor(rect.y), 0, imageSize.height);
  const x2 = clamp(Math.ceil(rect.x + rect.width), x1, imageSize.width);
  const y2 = clamp(Math.ceil(rect.y + rect.height), y1, imageSize.height);
  return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
}

export function sourcePixelMovedRect(rect, imageSize) {
  const width = Math.min(imageSize.width, Math.max(1, Math.round(rect.width)));
  const height = Math.min(imageSize.height, Math.max(1, Math.round(rect.height)));
  return {
    x: clamp(Math.round(rect.x), 0, imageSize.width - width),
    y: clamp(Math.round(rect.y), 0, imageSize.height - height),
    width,
    height,
  };
}

export function moveSelectionRect(rect, delta, imageSize) {
  return {
    ...rect,
    x: clamp(rect.x + delta.x, 0, Math.max(0, imageSize.width - rect.width)),
    y: clamp(rect.y + delta.y, 0, Math.max(0, imageSize.height - rect.height)),
  };
}

export function resizeSelectionRect(rect, handle, point, imageSize, minimumSize) {
  const minimumWidth = Math.min(imageSize.width, Math.max(1, minimumSize.width));
  const minimumHeight = Math.min(imageSize.height, Math.max(1, minimumSize.height));
  const originalRight = rect.x + rect.width;
  const originalBottom = rect.y + rect.height;
  let left = rect.x;
  let top = rect.y;
  let right = originalRight;
  let bottom = originalBottom;

  if (handle.includes("left")) left = clamp(point.x, 0, originalRight - minimumWidth);
  if (handle.includes("right")) right = clamp(point.x, rect.x + minimumWidth, imageSize.width);
  if (handle.includes("top")) top = clamp(point.y, 0, originalBottom - minimumHeight);
  if (handle.includes("bottom")) bottom = clamp(point.y, rect.y + minimumHeight, imageSize.height);

  return { x: left, y: top, width: right - left, height: bottom - top };
}

export function hitTestSelection(screenPoint, rect, view, hitSize = 12) {
  if (!rect) return null;
  const start = imageToScreen({ x: rect.x, y: rect.y }, view);
  const end = imageToScreen({ x: rect.x + rect.width, y: rect.y + rect.height }, view);
  const middleX = (start.x + end.x) / 2;
  const middleY = (start.y + end.y) / 2;
  const radius = Math.max(4, hitSize / 2);
  const handles = [
    ["top-left", start.x, start.y],
    ["top-right", end.x, start.y],
    ["bottom-left", start.x, end.y],
    ["bottom-right", end.x, end.y],
    ["top", middleX, start.y],
    ["bottom", middleX, end.y],
    ["left", start.x, middleY],
    ["right", end.x, middleY],
  ];
  for (const [handle, x, y] of handles) {
    if (Math.abs(screenPoint.x - x) <= radius && Math.abs(screenPoint.y - y) <= radius) return handle;
  }
  const withinX = screenPoint.x >= start.x && screenPoint.x <= end.x;
  const withinY = screenPoint.y >= start.y && screenPoint.y <= end.y;
  if (withinX && Math.abs(screenPoint.y - start.y) <= radius) return "top";
  if (withinX && Math.abs(screenPoint.y - end.y) <= radius) return "bottom";
  if (withinY && Math.abs(screenPoint.x - start.x) <= radius) return "left";
  if (withinY && Math.abs(screenPoint.x - end.x) <= radius) return "right";
  return withinX && withinY ? "move" : null;
}

export function hitTestEditableRectangles(screenPoint, rectangles, activeRegionId, view, hitSize = 12) {
  const active = rectangles.find((rectangle) => rectangle.id === activeRegionId);
  const activeHit = active ? hitTestSelection(screenPoint, active, view, hitSize) : null;
  if (activeHit && activeHit !== "move") {
    return { regionId: active.id, handle: activeHit };
  }
  for (let index = rectangles.length - 1; index >= 0; index -= 1) {
    const rectangle = rectangles[index];
    if (rectangle.id === activeRegionId) {
      if (activeHit) return { regionId: rectangle.id, handle: activeHit };
      continue;
    }
    if (hitTestSelection(screenPoint, rectangle, view, hitSize)) {
      return { regionId: rectangle.id, handle: "move" };
    }
  }
  return null;
}

export function selectionToMaskOperation(rect) {
  return rect ? { type: "rectangle", ...rect, erase: false } : null;
}
