import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const geometry = await import(new URL("../../src/localRetouchGeometry.js", import.meta.url).href);
const regions = await import(new URL("../../src/localRetouchRegions.js", import.meta.url).href);
const pageSource = fs.readFileSync(new URL("../../src/LocalRetouchPage.jsx", import.meta.url), "utf8");
const routeSource = fs.readFileSync(new URL("../../src/appRoutes.js", import.meta.url), "utf8");
const appSource = fs.readFileSync(new URL("../../src/App.jsx", import.meta.url), "utf8");
const dashboardSource = fs.readFileSync(new URL("../../src/DashboardPage.jsx", import.meta.url), "utf8");
const taskDetailSource = fs.readFileSync(new URL("../../src/TaskDetailPage.jsx", import.meta.url), "utf8");
const shellSource = fs.readFileSync(new URL("../../src/AppShell.jsx", import.meta.url), "utf8");
const styles = fs.readFileSync(new URL("../../src/index.css", import.meta.url), "utf8");

test("缩放与拖拽后屏幕坐标准确映射回原图", () => {
  const view = { scale: 2.5, offsetX: -140, offsetY: 75 };
  const original = { x: 420, y: 260 };
  const screen = geometry.imageToScreen(original, view);
  assert.deepEqual(geometry.screenToImage(screen, view, { width: 1600, height: 900 }), original);
  const zoomed = geometry.zoomViewAt(view, screen, 4);
  assert.deepEqual(geometry.screenToImage(screen, zoomed, { width: 1600, height: 900 }), original);
});

test("矩形选区在原图边界内规范化", () => {
  assert.deepEqual(
    geometry.normalizedRect({ x: 500, y: 300 }, { x: -20, y: 900 }, { width: 800, height: 600 }),
    { x: 0, y: 300, width: 500, height: 300 },
  );
});

test("letterbox空白不会被识别为图片内容", () => {
  const imageSize = { width: 1600, height: 1200 };
  const view = geometry.fitImageView(imageSize.width, imageSize.height, 1200, 800, 0);
  assert.equal(Math.round(view.offsetX), 67);
  const letterboxPoint = geometry.screenToImage({ x: 20, y: 400 }, view, imageSize, false);
  const imagePoint = geometry.screenToImage({ x: 80, y: 400 }, view, imageSize, false);
  assert.equal(geometry.pointInImage(letterboxPoint, imageSize), false);
  assert.equal(geometry.pointInImage(imagePoint, imageSize), true);
});

test("单矩形移动到四边时保持尺寸并clamp位置", () => {
  const rect = { x: 20, y: 30, width: 40, height: 50 };
  const imageSize = { width: 100, height: 100 };
  assert.deepEqual(geometry.moveSelectionRect(rect, { x: -80, y: 0 }, imageSize), { x: 0, y: 30, width: 40, height: 50 });
  assert.deepEqual(geometry.moveSelectionRect(rect, { x: 80, y: 0 }, imageSize), { x: 60, y: 30, width: 40, height: 50 });
  assert.deepEqual(geometry.moveSelectionRect(rect, { x: 0, y: -80 }, imageSize), { x: 20, y: 0, width: 40, height: 50 });
  assert.deepEqual(geometry.moveSelectionRect(rect, { x: 0, y: 80 }, imageSize), { x: 20, y: 50, width: 40, height: 50 });
  assert.deepEqual(
    geometry.sourcePixelMovedRect(geometry.moveSelectionRect(rect, { x: 10.4, y: 5.7 }, imageSize), imageSize),
    { x: 30, y: 36, width: 40, height: 50 },
  );
});

test("四边与四角resize有确定边界和最小尺寸", () => {
  const rect = { x: 20, y: 30, width: 40, height: 50 };
  const imageSize = { width: 100, height: 100 };
  const minimum = { width: 10, height: 10 };
  const cases = [
    ["left", { x: -50, y: 50 }, { x: 0, y: 30, width: 60, height: 50 }],
    ["right", { x: 200, y: 50 }, { x: 20, y: 30, width: 80, height: 50 }],
    ["top", { x: 40, y: -50 }, { x: 20, y: 0, width: 40, height: 80 }],
    ["bottom", { x: 40, y: 200 }, { x: 20, y: 30, width: 40, height: 70 }],
    ["top-left", { x: 90, y: 90 }, { x: 50, y: 70, width: 10, height: 10 }],
    ["top-right", { x: 200, y: -20 }, { x: 20, y: 0, width: 80, height: 80 }],
    ["bottom-left", { x: -20, y: 200 }, { x: 0, y: 30, width: 60, height: 70 }],
    ["bottom-right", { x: 200, y: 200 }, { x: 20, y: 30, width: 80, height: 70 }],
  ];
  for (const [handle, point, expected] of cases)
    assert.deepEqual(geometry.resizeSelectionRect(rect, handle, point, imageSize, minimum), expected, handle);
});

test("八向handle与矩形主体命中结果稳定", () => {
  const rect = { x: 20, y: 30, width: 40, height: 50 };
  const view = { scale: 2, offsetX: 10, offsetY: 15 };
  const points = {
    "top-left": { x: 50, y: 75 },
    top: { x: 90, y: 75 },
    "top-right": { x: 130, y: 75 },
    left: { x: 50, y: 125 },
    right: { x: 130, y: 125 },
    "bottom-left": { x: 50, y: 175 },
    bottom: { x: 90, y: 175 },
    "bottom-right": { x: 130, y: 175 },
  };
  for (const [handle, point] of Object.entries(points))
    assert.equal(geometry.hitTestSelection(point, rect, view, 16), handle);
  assert.equal(geometry.hitTestSelection({ x: 90, y: 125 }, rect, view, 16), "move");
  assert.equal(geometry.hitTestSelection({ x: 20, y: 20 }, rect, view, 16), null);
});

test("多矩形命中保持active handle优先并按创建层级选择最上层body", () => {
  const view = { scale: 1, offsetX: 0, offsetY: 0 };
  const rectangles = [
    regions.createRectangleRegion("outer", 1, { x: 10, y: 10, width: 100, height: 100 }),
    regions.createRectangleRegion("inner", 2, { x: 30, y: 30, width: 30, height: 30 }),
    regions.createRectangleRegion("overlap", 3, { x: 70, y: 30, width: 30, height: 30 }),
  ];
  assert.deepEqual(
    geometry.hitTestEditableRectangles({ x: 10, y: 10 }, rectangles, "outer", view, 16),
    { regionId: "outer", handle: "top-left" },
  );
  assert.deepEqual(
    geometry.hitTestEditableRectangles({ x: 45, y: 45 }, rectangles, "outer", view, 16),
    { regionId: "inner", handle: "move" },
  );
  assert.deepEqual(
    geometry.hitTestEditableRectangles({ x: 45, y: 45 }, rectangles, "inner", view, 16),
    { regionId: "inner", handle: "move" },
  );
  assert.deepEqual(
    geometry.hitTestEditableRectangles({ x: 85, y: 45 }, rectangles, "outer", view, 16),
    { regionId: "overlap", handle: "move" },
  );
});

test("矩形工具使用一次性新建意图允许在已有矩形内部拖拽新区域", () => {
  assert.match(pageSource, /const \[rectangleCreateArmed, setRectangleCreateArmed\] = useState\(false\);/);
  assert.match(pageSource, /fallbackRegionId: rectangleCreateArmed \? hit\?\.regionId \|\| null : null/);
  assert.match(pageSource, /setRectangleCreateArmed\(item\.key === "rectangle"\)/);
  assert.match(pageSource, /data-rectangle-create-armed=\{rectangleCreateArmed \? "true" : "false"\}/);
});

test("拖入单张图片与点击导入复用同一intake并提供明确拖拽状态", () => {
  const intakeCalls = pageSource.match(/requestJson\("\/api\/local-retouch\/intake"/g) || [];
  assert.equal(intakeCalls.length, 1, "click and drop must share one intake request path");
  assert.match(pageSource, /const intakeFile = async \(file\) => \{/);
  assert.match(pageSource, /if \(file\) void intakeFile\(file\)/);
  assert.match(pageSource, /const handleFileDrop = \(event\) => \{[\s\S]*?files\.length !== 1[\s\S]*?当前仅支持单张图片[\s\S]*?void intakeFile\(files\[0\]\)/);
  assert.match(pageSource, /onDragEnter=\{handleFileDragEnter\}/);
  assert.match(pageSource, /onDragOver=\{handleFileDragOver\}/);
  assert.match(pageSource, /onDragLeave=\{handleFileDragLeave\}/);
  assert.match(pageSource, /onDrop=\{handleFileDrop\}/);
  assert.match(pageSource, /event\.preventDefault\(\);[\s\S]*?event\.dataTransfer\.dropEffect = busy \? "none" : "copy"/);
  assert.match(pageSource, /data-file-drag-active=\{fileDragActive \? "true" : "false"\}/);
  assert.match(pageSource, /data-testid="retouch-drop-indicator"/);
  assert.match(pageSource, /拖入一张图片，或点击导入/);
  assert.match(pageSource, /data-testid="retouch-canvas-wrap"/);
  assert.match(pageSource, /data-retouch-drop-zone="true"/);
  assert.match(styles, /\.hdde-retouch-canvas-wrap\.is-file-drag-active\s*\{[\s\S]*?var\(--brand-primary\)/);
  assert.match(styles, /\.hdde-retouch-file-drop-indicator\s*\{[\s\S]*?pointer-events:\s*none/);
});

test("矩形与画笔使用统一可编辑区域模型并按创建顺序派生单一Mask", () => {
  const rectangle = regions.createRectangleRegion("r1", 1, { x: 10, y: 20, width: 30, height: 40 });
  const paint = regions.createStrokeRegion("s1", 2, [{ x: 5, y: 6 }, { x: 8, y: 9 }], 24, "paint");
  const erase = regions.createStrokeRegion("s2", 3, [{ x: 12, y: 14 }], 18, "erase");
  const model = [erase, paint, rectangle];

  assert.deepEqual(regions.editableRectangles(model, "r1")[0], {
    ...rectangle, selected: true, active: true,
  });
  assert.deepEqual(regions.repairRegionsToMaskOperations(model), [
    { type: "rectangle", x: 10, y: 20, width: 30, height: 40, erase: false },
    { type: "stroke", points: paint.points, size: 24, erase: false },
    { type: "stroke", points: erase.points, size: 18, erase: true },
  ]);
  assert.equal(regions.latestStrokeRegion(model).id, "s2");
  assert.deepEqual(regions.removeRepairRegion(model, "s2"), [paint, rectangle]);
  assert.equal(regions.replaceRepairRegion(model, { ...rectangle, width: 55 })[2].width, 55);
});

test("最终selection按明确像素舍入直接成为Mask矩形", () => {
  const rect = geometry.sourcePixelRect(
    { x: 10.8, y: 20.2, width: 30.1, height: 40.4 },
    { width: 100, height: 100 },
  );
  assert.deepEqual(rect, { x: 10, y: 20, width: 31, height: 41 });
  assert.deepEqual(
    geometry.selectionToMaskOperation(rect),
    { type: "rectangle", x: 10, y: 20, width: 31, height: 41, erase: false },
  );
});

test("窗口变化只重投影视觉矩形而不改变原图selection", () => {
  const imageSize = { width: 2400, height: 1600 };
  const selection = { x: 1800, y: 1200, width: 420, height: 260 };
  for (const viewport of [{ width: 1200, height: 800 }, { width: 820, height: 920 }]) {
    const view = geometry.fitImageView(imageSize.width, imageSize.height, viewport.width, viewport.height, 36);
    const screen = geometry.imageToScreen({ x: selection.x, y: selection.y }, view);
    const projected = geometry.screenToImage(screen, view, imageSize);
    assert.ok(Math.abs(projected.x - selection.x) < 1e-9);
    assert.ok(Math.abs(projected.y - selection.y) < 1e-9);
  }
});

test("页面以统一可编辑区域驱动多矩形与画笔的最终请求Mask", () => {
  assert.match(pageSource, /const SELECTION_BORDER_WIDTH = 0\.25;/);
  assert.match(pageSource, /context\.lineWidth = SELECTION_BORDER_WIDTH;[\s\S]*?context\.strokeRect\(start\.x, start\.y, width, height\);/);
  assert.match(pageSource, /const ACTIVE_SELECTION_COLOR = "#2F8F83";/);
  assert.match(pageSource, /const SELECTION_FILL_COLOR = "rgba\(47, 143, 131, 0\.18\)";/);
  assert.match(pageSource, /const SELECTION_HANDLE_FILL = "#FFFFFF";/);
  assert.match(pageSource, /const SELECTION_HANDLE_STROKE = "#2F8F83";/);
  assert.doesNotMatch(pageSource, /const BRUSH_SELECTION_COLOR =/);
  assert.match(pageSource, /overlayContext\.fillStyle = SELECTION_FILL_COLOR;/);
  assert.doesNotMatch(pageSource, /overlayContext\.fillStyle = "rgba\([^)]*, 0\.62\)";/);
  assert.match(pageSource, /repairRegionsToMaskOperations\(\[\.\.\.operations, \.\.\.\(draft \? \[draft\] : \[\]\)\]\)/);
  assert.match(pageSource, /context\.strokeStyle = active \? ACTIVE_SELECTION_COLOR : INACTIVE_SELECTION_COLOR;/);
  assert.match(pageSource, /context\.fillStyle = SELECTION_HANDLE_FILL;[\s\S]*?context\.strokeStyle = SELECTION_HANDLE_STROKE;/);
  const selectionFrameBlock = pageSource.match(/function drawSelectionFrame\([\s\S]*?\n\}/)?.[0] || "";
  const selectionBorderBlock = selectionFrameBlock.split("context.fillStyle = SELECTION_HANDLE_FILL;")[0];
  assert.equal((selectionBorderBlock.match(/context\.strokeRect/g) || []).length, 1, "selection frame must have one border stroke");
  assert.doesNotMatch(selectionBorderBlock, /context\.lineWidth = 4;/);
  assert.match(pageSource, /const \[repairRegions, setRepairRegions\] = useState\(\[\]\);/);
  assert.match(pageSource, /const \[activeRegionId, setActiveRegionId\] = useState\(null\);/);
  assert.doesNotMatch(pageSource, /const \[selection, setSelection\]/);
  const processBlock = pageSource.match(/const processMask = async \(\) => \{[\s\S]*?\n  \};/)?.[0] || "";
  assert.match(processBlock, /renderRetouchMask\([\s\S]*?repairRegions/);
  assert.match(processBlock, /mask_png_base64: mask\.toDataURL\("image\/png"\)/);
  assert.match(processBlock, /setRepairRegions\(\[\]\)/);
  assert.match(pageSource, /hitTestEditableRectangles/);
  assert.match(pageSource, /rectangles\.find\(\(rectangle\) => rectangle\.id === hit\.regionId\)/);
  assert.match(pageSource, /setSelectionDraft\(createRectangleRegion\([\s\S]*?resizeSelectionRect\(/);
  assert.match(pageSource, /data-testid="retouch-delete-selection"/);
  assert.match(pageSource, /data-testid="retouch-delete-last-stroke"/);
  assert.match(styles, /\.hdde-retouch-workspace \.hdde-retouch-delete-selection\s*\{[\s\S]*?min-height:\s*44px;[\s\S]*?var\(--status-danger\)/);
  assert.match(pageSource, /data-rectangle-count=\{rectangles\.length\}/);
  assert.match(pageSource, /data-stroke-count=\{strokeCount\}/);
  assert.match(pageSource, /onPointerCancel=\{cancelPointerInteraction\}/);
  assert.match(pageSource, /onLostPointerCapture=\{cancelPointerInteraction\}/);
  assert.match(pageSource, /window\.addEventListener\("blur", cancelPointerInteraction\)/);
});

test("首次进入默认使用矩形且保留全部修整工具", () => {
  assert.match(pageSource, /const \[tool, setTool\] = useState\("rectangle"\);/);
  for (const tool of ["brush", "rectangle", "erase", "pan"])
    assert.match(pageSource, new RegExp(`key: "${tool}"`));
});

test("正式页面使用产品API、工作源重试和人工确认保存合同", () => {
  assert.match(pageSource, /瑕疵修复/);
  assert.match(routeSource, /name: "瑕疵修复"/);
  assert.doesNotMatch(`${pageSource}\n${routeSource}`, /瑕疵修整|局部修复|标记修整/);
  assert.match(pageSource, /\/api\/local-retouch\/intake/);
  assert.match(pageSource, /\/process/);
  assert.match(pageSource, /\/confirm/);
  assert.match(pageSource, /\/save/);
  assert.match(pageSource, /retry_source|选区已更新，请重新处理/);
  assert.match(pageSource, /前后对比/);
  assert.match(pageSource, /撤销/);
  assert.match(pageSource, /重做/);
  assert.match(pageSource, /擦除/);
  assert.doesNotMatch(pageSource, /models\//);
  assert.doesNotMatch(pageSource, /onnxruntime|Torch|model_path/);
  assert.doesNotMatch(`${pageSource}\n${routeSource}`, /LaMa|LAMA|lama/);
  assert.match(pageSource, /本地修整引擎/);
  assert.match(routeSource, /本地智能修整/);
  assert.match(pageSource, /retouch-open-output-center/);
  assert.match(pageSource, /前往输出中心/);
  assert.match(appSource, /<LocalRetouchPage[\s\S]*?onOpenOutputCenter=\{\(\) => navigateTo\("\/outputs"\)\}/);
});

test("连续修整成功后自动切换稳定底图并隔离下一轮Mask历史", () => {
  assert.match(pageSource, /const previousWorkingImage = sourceImageRef\.current/);
  assert.match(pageSource, /setCompareSourceImage\(previousWorkingImage\)/);
  assert.match(pageSource, /setSourceImage\(image\)/);
  assert.match(pageSource, /setRepairRegions\(\[\]\)/);
  assert.match(pageSource, /setUndoStack\(\[\]\)/);
  assert.match(pageSource, /setRedoStack\(\[\]\)/);
  assert.match(pageSource, /const editDepth = Math\.max\(0, Number\(session\?\.working_revision\) \|\| 0\)/);
  assert.match(pageSource, /setDisplayMode\("edit"\)/);
  assert.match(pageSource, /修整完成，可继续处理其他瑕疵/);
  assert.match(pageSource, /当前结果可继续修整/);
  assert.match(pageSource, /已完成 \$\{editDepth\} 次修整/);
  assert.match(pageSource, /data-testid="retouch-continue"/);
  assert.match(pageSource, /workspaceActionRef\.current/);
});

test("结果级回退独立于Mask撤销重做并恢复上一稳定底图", () => {
  const backBlock = pageSource.match(/const backToPreviousResult = async \(\) => \{[\s\S]*?\n  \};/)?.[0] || "";
  assert.match(pageSource, /\/back-to-previous/);
  assert.match(pageSource, /data-testid="retouch-back-to-previous"/);
  assert.match(pageSource, /回到上一结果/);
  assert.match(pageSource, /session\.can_back_to_previous/);
  assert.match(backBlock, /const targetRevision = Math\.max\(0, Number\(next\.working_revision\) \|\| 0\)/);
  assert.match(backBlock, /targetRevision === 0 \? next\.source_url : \(next\.result_url \|\| next\.working_source_url\)/);
  assert.match(pageSource, /setSourceImage\(image\)/);
  assert.match(backBlock, /setResult\(targetRevision > 0 \? next : null\)/);
  assert.match(backBlock, /setResultImage\(targetRevision > 0 \? image : null\)/);
  assert.match(pageSource, /setRepairRegions\(\[\]\)/);
  assert.match(pageSource, /setRedoStack\(\[\]\)/);
  assert.match(pageSource, /已回到上一修整结果/);
  assert.match(backBlock, /已回到原图，可重新选择需要修整的区域/);
  assert.match(pageSource, /撤销选区/);
  assert.match(pageSource, /重做选区/);
  const undoBlock = pageSource.match(/const undo = \(\) => \{[\s\S]*?\n  \};/)?.[0] || "";
  const redoBlock = pageSource.match(/const redo = \(\) => \{[\s\S]*?\n  \};/)?.[0] || "";
  assert.doesNotMatch(`${undoBlock}\n${redoBlock}`, /back-to-previous|working_revision/);
  assert.match(styles, /\.hdde-retouch-result-actions > \.hdde-retouch-result-back/);
});

test("连续编辑显性操作保持直达并只在最终确认后保存正式结果", () => {
  assert.match(pageSource, /const continueEditing = \(\) => \{[\s\S]*?setDisplayMode\("edit"\)[\s\S]*?canvasRef\.current\?\.focus/);
  assert.doesNotMatch(pageSource.match(/const continueEditing = \(\) => \{[\s\S]*?\n  \};/)?.[0] || "", /fetch|requestJson|setSession|setResult/);
  assert.match(pageSource, /const confirmAndSaveResult = async \(\) => \{[\s\S]*?\/confirm[\s\S]*?\/save/);
  assert.match(pageSource, /data-testid="retouch-confirm-and-save"/);
  assert.match(pageSource, /完成修整/);
  assert.match(pageSource, /当前结果已保存/);
  assert.doesNotMatch(pageSource, /第 \$\{session\.working_revision\} 轮结果|第 \$\{session\.working_revision\} 轮底图/);
  assert.match(pageSource, /修整未完成，当前结果已保留/);
});

test("retouch路由是正式现有页面而非占位页", () => {
  const routeBlock = routeSource.match(/key: "retouch",[\s\S]*?\n  },/)?.[0] || "";
  assert.match(routeBlock, /status: FEATURE_STATUSES\.ENABLED/);
  assert.match(routeBlock, /implementationType: "existing"/);
  assert.doesNotMatch(routeBlock, /placeholder|PLANNED/);
  assert.match(appSource, /route\.key === "retouch"/);
  assert.match(appSource, /<LocalRetouchPage/);
});

test("画布滚轮缩放使用可阻止默认行为的原生监听", () => {
  assert.match(pageSource, /addEventListener\("wheel", handleWheel, \{ passive: false \}\)/);
  assert.match(pageSource, /removeEventListener\("wheel", handleWheel\)/);
  assert.doesNotMatch(pageSource, /onWheel=/);
});

test("瑕疵修整使用应用内独立工作台并提供明确返回路径", () => {
  assert.match(appSource, /workspaceMode=\{route\?\.key === "retouch"\}/);
  assert.match(appSource, /onBack=\{\(\) => navigateTo\(DEFAULT_APP_PATH\)\}/);
  assert.match(shellSource, /hdde-app-shell--workspace/);
  assert.match(shellSource, /workspaceMode \? null : <aside/);
  assert.match(shellSource, /workspaceMode \? null : <header/);
  assert.match(pageSource, /data-testid="retouch-workspace"/);
  assert.match(pageSource, /data-testid="retouch-back"/);
});

test("瑕疵修整工作台复用全局主题Token且主要视图操作不低于44px", () => {
  assert.match(styles, /\.hdde-retouch-workspace\s*\{[\s\S]*?--retouch-chrome:\s*var\(--surface-overlay\)/);
  assert.match(styles, /--retouch-panel:\s*var\(--card-background\)/);
  assert.match(styles, /--retouch-text:\s*var\(--text-primary\)/);
  assert.match(styles, /--retouch-border:\s*var\(--border-color\)/);
  assert.match(pageSource, /useAppTheme\(\)/);
  assert.match(pageSource, /window\.getComputedStyle\(canvas\)\.color/);
  assert.match(styles, /\.hdde-retouch-workspace__stage \.hdde-retouch-view-tabs button\s*\{\s*min-height:\s*44px/);
});

test("瑕疵修整关键工具标签与保护说明不低于12px", () => {
  assert.match(styles, /\.hdde-retouch-toolrail__group button span\s*\{[\s\S]*?font-size:\s*12px/);
  assert.match(styles, /\.hdde-retouch-inspector__heading span,[\s\S]*?\.hdde-retouch-summary span,[\s\S]*?\.hdde-retouch-range-label > span\s*\{[\s\S]*?font-size:\s*12px/);
  assert.match(styles, /\.hdde-retouch-mask-history-note\s*\{[\s\S]*?font-size:\s*12px/);
  assert.match(styles, /\.hdde-retouch-workspace__protection\s*\{[\s\S]*?font-size:\s*12px/);
  for (const label of ["撤销选区", "重做选区", "撤销选区 / 重做选区只影响当前尚未执行的选区。", "原图始终保留，结果仅另存为派生文件。"])
    assert.ok(pageSource.includes(label), `missing required retouch guidance: ${label}`);
});

test("UI-05 uses backend authority and commits only after working assets load", () => {
  assert.match(pageSource, /resumeResultId/);
  assert.match(pageSource, /resumeSessionId/);
  assert.match(pageSource, /\/resume-adjustment/);
  assert.match(pageSource, /\/resume-adjustment\/commit/);
  assert.match(pageSource, /const \[image, originalImage\] = await Promise\.all/);
  assert.ok(
    pageSource.indexOf("await Promise.all") < pageSource.indexOf("/resume-adjustment/commit"),
    "working images must decode before resume commit",
  );
  assert.match(pageSource, /let committedPayload;[\s\S]*?committedPayload = await commitResume\(\);[\s\S]*?catch[\s\S]*?committedPayload = await commitResume\(\);/);
  assert.ok(
    pageSource.indexOf("handledResumeResultRef.current = resumeResultId") > pageSource.indexOf("const next = committedPayload.data"),
    "resume must be marked handled only after commit succeeds",
  );
  assert.match(pageSource, /onResultReady\?\.\(\{[\s\S]*?taskId:[\s\S]*?resultId:[\s\S]*?sessionId:/);
  assert.match(pageSource, /onResumeAvailabilityChange\?\.\([\s\S]*?taskId, resultId, sessionId/);
  assert.match(pageSource, /prepared\.working_source_url \|\| prepared\.result_url/);
  assert.match(pageSource, /完成修整/);
  assert.match(appSource, /handleRetouchResultReady[\s\S]*?\/task-detail\?task_id=/);
  assert.match(appSource, /\/api\/local-retouch\/resume-authority/);
  assert.match(appSource, /const canResumeCurrentRetouch = Boolean\([\s\S]*?retouchResumeAuthority\.available[\s\S]*?retouchResumeAuthority\.status === "AVAILABLE"/);
  const canResumeBlock = appSource.match(/const canResumeCurrentRetouch = Boolean\([\s\S]*?\n  \);/)?.[0] || "";
  assert.doesNotMatch(canResumeBlock, /retouchResumeContext/);
  assert.match(appSource, /reprocessLabel=\{isLocalRetouchResult[\s\S]*?"返回调整"[\s\S]*?"重新处理"/);
  assert.match(appSource, /fetchRetouchResumeAuthority\(taskContext\.taskId, activeResultId\)/);
  assert.match(appSource, /\.catch\(\(\) => \{[\s\S]*?available: false,[\s\S]*?status: "UNAVAILABLE"/);
  assert.match(appSource, /onReprocess=\{handleTaskReprocess\}/);
  assert.match(appSource, /\["LOCAL_RETOUCH", "local_retouch"\]\.includes\(taskContext\?\.mode\)/);
  assert.match(appSource, /retouchWorkspaceMounted[\s\S]*?hidden=\{route\?\.key !== "retouch"\}/);
  assert.match(taskDetailSource, /const isLocalRetouch = \["LOCAL_RETOUCH", "local_retouch"\]\.includes\(rawMode\)/);
  assert.match(taskDetailSource, /边缘衔接与纹理连续性/);
  assert.match(taskDetailSource, /reprocessLabel = "返回调整 \/ 重新处理"/);
  assert.doesNotMatch(`${appSource}\n${pageSource}`, /retouch-report|瑕疵修整报告/);
});

test("保存后的任务详情链复用当前API目标且不固定访问8787", () => {
  const taskDetailChain = `${appSource}\n${dashboardSource}\n${taskDetailSource}`;
  assert.match(appSource, /fetch\(`\$\{API_BASE\}\/api\/v1\/tasks\/\$\{encodeURIComponent\(taskId\)\}`\)/);
  assert.match(appSource, /const API_BASE = import\.meta\.env\.VITE_API_BASE_URL \|\| "";/);
  assert.match(dashboardSource, /const API_BASE = import\.meta\.env\.VITE_API_BASE_URL \|\| "";/);
  assert.match(taskDetailSource, /const API_BASE = import\.meta\.env\.VITE_API_BASE_URL \|\| "";/);
  assert.doesNotMatch(taskDetailChain, /https?:\/\/(?:localhost|127\.0\.0\.1):8787/i);
});
