function byCreationOrder(first, second) {
  return first.order - second.order;
}

export function createRectangleRegion(id, order, rect) {
  return {
    id,
    type: "rectangle",
    x: rect.x,
    y: rect.y,
    width: rect.width,
    height: rect.height,
    order,
  };
}

export function createStrokeRegion(id, order, points, brushSize, mode = "paint") {
  return {
    id,
    type: "stroke",
    points,
    brushSize,
    mode: mode === "erase" ? "erase" : "paint",
    order,
  };
}

export function editableRectangles(regions, activeRegionId) {
  return regions
    .filter((region) => region.type === "rectangle")
    .sort(byCreationOrder)
    .map((region) => ({
      ...region,
      selected: region.id === activeRegionId,
      active: region.id === activeRegionId,
    }));
}

export function replaceRepairRegion(regions, nextRegion) {
  return regions.map((region) => (region.id === nextRegion.id ? nextRegion : region));
}

export function removeRepairRegion(regions, regionId) {
  return regions.filter((region) => region.id !== regionId);
}

export function latestStrokeRegion(regions) {
  return [...regions]
    .filter((region) => region.type === "stroke")
    .sort(byCreationOrder)
    .at(-1) || null;
}

export function repairRegionsToMaskOperations(regions) {
  return [...regions].sort(byCreationOrder).map((region) => {
    if (region.type === "rectangle") {
      return {
        type: "rectangle",
        x: region.x,
        y: region.y,
        width: region.width,
        height: region.height,
        erase: false,
      };
    }
    return {
      type: "stroke",
      points: region.points,
      size: region.brushSize,
      erase: region.mode === "erase",
    };
  });
}
