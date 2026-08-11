import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const geometry = await import(new URL("../../src/localRetouchGeometry.js", import.meta.url).href);
const pageSource = fs.readFileSync(new URL("../../src/LocalRetouchPage.jsx", import.meta.url), "utf8");
const routeSource = fs.readFileSync(new URL("../../src/appRoutes.js", import.meta.url), "utf8");
const appSource = fs.readFileSync(new URL("../../src/App.jsx", import.meta.url), "utf8");

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

test("正式页面使用产品API、工作源重试和人工确认保存合同", () => {
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
  assert.match(appSource, /<LocalRetouchPage onOpenOutputCenter=\{\(\) => navigateTo\("\/outputs"\)\}/);
});

test("retouch路由是正式现有页面而非占位页", () => {
  const routeBlock = routeSource.match(/key: "retouch",[\s\S]*?\n  },/)?.[0] || "";
  assert.match(routeBlock, /status: FEATURE_STATUSES\.ENABLED/);
  assert.match(routeBlock, /implementationType: "existing"/);
  assert.doesNotMatch(routeBlock, /placeholder|PLANNED/);
  assert.match(appSource, /route\.key === "retouch"/);
  assert.match(appSource, /<LocalRetouchPage/);
});
