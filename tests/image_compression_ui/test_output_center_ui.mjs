import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { APP_ROUTES } from "../../src/appRoutes.js";
import {
  getFileIdentityName,
  getFileNameFromPath,
  getFileNameFromUrl,
} from "../../src/fileDisplayName.js";
import { FEATURE_STATUSES } from "../../src/platformStatus.js";
import { calculateOutputHoverPreviewPosition } from "../../src/outputHoverPreview.js";

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(currentDirectory, "..", "..");
const page = fs.readFileSync(path.join(root, "src", "OutputCenterPage.jsx"), "utf8");
const app = fs.readFileSync(path.join(root, "src", "App.jsx"), "utf8");
const backend = fs.readFileSync(path.join(root, "backend", "image_compression_api.py"), "utf8");
const fileDisplaySource = fs.readFileSync(path.join(root, "src", "fileDisplayName.js"), "utf8");
const styles = fs.readFileSync(path.join(root, "src", "index.css"), "utf8");
const thumbnailLoader = fs.readFileSync(path.join(root, "src", "outputThumbnailLoader.js"), "utf8");

test("delivery selection rejects backend-ineligible items without recomputing D3", () => {
  const start = page.indexOf("  const toggleDeliveryItem =");
  const end = page.indexOf("  const openSmartDelivery =", start);
  let items = [];
  const context = vm.createContext({
    setSelectedDeliveryItems: (update) => { items = update(items); },
  });
  vm.runInContext(`${page.slice(start, end)}; this.toggle = toggleDeliveryItem;`, context);
  for (const delivery_eligible of [false, undefined, "true"]) {
    context.toggle({ id: "review", delivery_eligible, result_action: "ACCEPT_CORRECTED" });
    assert.equal(items.length, 0, "Only the backend boolean may grant selection");
  }
  context.toggle({ id: "confirmed", delivery_eligible: true, result_action: "REVIEW_REQUIRED" });
  assert.equal(items.map((item) => item.id).join(","), "confirmed");
  context.toggle({ id: "confirmed", delivery_eligible: true });
  assert.equal(items.length, 0);
  assert.match(page, /disabled=\{!selectedDeliveryEligible\}/);
});

test("delivery reasons explain backend denial without granting permission from an action", () => {
  const start = page.indexOf("function deliveryUnavailableReason");
  const context = vm.createContext({});
  vm.runInContext(page.slice(start, page.indexOf("function OutputThumbnail", start)), context);
  const reason = context.deliveryUnavailableReason;
  assert.equal(reason({ delivery_eligible: true, result_action: "REVIEW_REQUIRED" }), "");
  assert.match(reason({ delivery_eligible: false, result_action: "REVIEW_REQUIRED" }), /结果待确认/);
  assert.match(reason({ delivery_eligible: false, result_action: "ACCEPT_ORIGINAL" }), /未生成新的校色结果/);
  assert.match(reason({ delivery_eligible: false, status: "failed" }), /安全保护/);
  assert.match(reason({ result_action: "ACCEPT_CORRECTED" }), /暂不可交付/);
  assert.match(page, /aria-describedby=\{!selectedDeliveryEligible/);
  assert.match(page, /id="output-delivery-reason" role="status"/);
});

test("delivery preparation fails closed when selected facts are no longer eligible", () => {
  const start = page.indexOf("  const openSmartDelivery =");
  const implementation = page.slice(start, page.indexOf("\n  return (", start));
  for (const items of [[], [{ id: "selected", delivery_eligible: false }], [{ id: "selected", delivery_eligible: true, unified_result: true, result_id: "confirmed" }]]) {
    const navigations = [], errors = [];
    const context = vm.createContext({
      selectedDeliveryItems: items,
      setError: (value) => errors.push(value), onNavigate: (value) => navigations.push(value),
    });
    vm.runInContext(`${implementation}; openSmartDelivery();`, context);
    assert.equal(navigations.length, items[0]?.delivery_eligible === true ? 1 : 0);
    assert.equal(errors.length, items.length && !navigations.length ? 1 : 0);
  }
});

test("delivery selection keeps authoritative result facts when filters hide selected cards", () => {
  assert.match(page, /const \[selectedDeliveryItems, setSelectedDeliveryItems\] = useState\(\[\]\)/);
  const toggleStart = page.indexOf("  const toggleDeliveryItem =");
  const openStart = page.indexOf("  const openSmartDelivery =", toggleStart);
  const implementation = page.slice(toggleStart, page.indexOf("\n  return (", openStart));
  let selectedDeliveryItems = [];
  const navigations = [];
  const errors = [];
  const context = vm.createContext({
    selectedDeliveryItems,
    setSelectedDeliveryItems: (update) => {
      selectedDeliveryItems = update(selectedDeliveryItems);
      context.selectedDeliveryItems = selectedDeliveryItems;
    },
    setError: (value) => errors.push(value),
    onNavigate: (value) => navigations.push(value),
  });
  vm.runInContext(`${implementation}; this.toggle = toggleDeliveryItem; this.open = openSmartDelivery;`, context);

  context.toggle({ id: "item-a", unified_result: true, result_id: "result-a", delivery_eligible: true });
  context.toggle({ id: "item-b", unified_result: true, result_id: "result-b", delivery_eligible: true });
  context.toggle({ id: "item-c", unified_result: true, result_id: "result-c", delivery_eligible: false });
  assert.equal(selectedDeliveryItems.map((item) => item.result_id).join(","), "result-a,result-b");

  context.open();
  assert.deepEqual(errors, []);
  assert.deepEqual(navigations, ["/smart-delivery?results=result-a%2Cresult-b"]);
  assert.doesNotMatch(implementation, /data\.items\.find/);
});

test("output center is a real enabled route and its compare route stays out of navigation", () => {
  const outputRoute = APP_ROUTES.find((route) => route.key === "outputs");
  const compareRoute = APP_ROUTES.find((route) => route.key === "output-compare");
  assert.equal(outputRoute?.status, FEATURE_STATUSES.ENABLED);
  assert.equal(outputRoute?.implementationType, "existing");
  assert.equal(compareRoute?.status, FEATURE_STATUSES.ENABLED);
  assert.equal(compareRoute?.showInNavigation, false);
  assert.match(app, /route\.key === "outputs"/);
  assert.match(app, /route\.key === "output-compare"/);
  assert.doesNotMatch(app, /route\.key === "outputs"[\s\S]{0,300}<FeaturePlaceholderPage/);
});

test("output center consumes real indexed items and never accepts a browser filesystem path", () => {
  assert.match(page, /requestJson\("\/api\/output-center\/items"\)/);
  assert.match(page, /encodeURIComponent\(item\.id\)/);
  assert.match(page, /performAction\(selected, "open-folder"\)/);
  assert.match(page, /performAction\(selected, "open"\)/);
  assert.doesNotMatch(page, /output_path|source_path|input_path/);
  assert.doesNotMatch(page, /mock|示例数据|样例数据/i);
  assert.match(backend, /formal_contract_directories_only/);
  assert.match(backend, /recursive_scan": False/);
  assert.match(backend, /output_center_index/);
  assert.doesNotMatch(backend, /(?:rglob|os\.walk)\([^\n]*output_center/i);
});

test("categories and comparison are derived from real item contracts", () => {
  assert.match(page, /data\.categories/);
  assert.match(page, /item\.processing_type === activeCategory/);
  assert.match(page, /selected\.compare_available/);
  assert.match(page, /进入对比质检/);
  assert.match(page, /返回输出中心/);
  assert.match(page, /SliderCompareStage/);
  assert.match(app, /onBackFromCompare=\{\(\) => navigateTo\("\/outputs"\)\}/);
});

test("output center preserves real file identity and searches filename separately from product labels", () => {
  const sourceName = "客户_影界瑕疵修整_项目.png";
  const mixedName = "客户_影界瑕疵修整_项目_影界瑕疵修复_20260901.png";
  assert.equal(getFileIdentityName("客户#项目.png"), "客户#项目.png");
  assert.equal(getFileIdentityName("客户?项目.png"), "客户?项目.png");
  assert.equal(getFileIdentityName(" 客户项目.png"), " 客户项目.png");
  assert.equal(getFileIdentityName(sourceName), sourceName);
  assert.equal(getFileIdentityName(mixedName), mixedName);
  assert.equal(getFileNameFromPath(`D:\\影界文件\\输出\\瑕疵修复\\${sourceName}`), sourceName);
  assert.equal(
    getFileNameFromUrl("http://127.0.0.1:5173/api/file/outputs/%E5%AE%A2%E6%88%B7%23%E9%A1%B9%E7%9B%AE.png?download=1#preview"),
    "客户#项目.png",
  );
  assert.match(page, /return getFileIdentityName\(item\?\.file_name, "图片成品"\)/);
  assert.match(page, /const fileIdentityName = getFileIdentityName\(item\?\.file_name\)/);
  assert.match(page, /fileIdentityName\.includes\(query\) \|\| productDisplayName\.includes\(query\)/);
  assert.match(page, /processingTypeDisplayName\(processingType, fallback\)/);
  const identityStart = fileDisplaySource.indexOf("export function getFileIdentityName");
  const pathStart = fileDisplaySource.indexOf("export function getFileNameFromPath", identityStart);
  const identityImplementation = fileDisplaySource.slice(identityStart, pathStart);
  assert.doesNotMatch(identityImplementation, /\.trim\(|split\(|replace(?:All)?\(/);
});

test("output detail keeps compact secondary actions without the next-step card", () => {
  assert.match(page, /加入交付清单/);
  assert.match(page, /打开成品/);
  assert.match(page, /打开所在目录/);
  assert.match(page, /hdde-output-action--compact/);
  assert.doesNotMatch(page, /hdde-output-next-step|将当前成品加入交付/);
  assert.match(page, /aria-pressed=\{selectedForDelivery\}/);
});

test("current output actions keep a clear primary, secondary, and auxiliary hierarchy", () => {
  assert.match(page, /data-testid="output-center-current-actions"/);
  assert.match(page, /hdde-primary-action hdde-output-action--primary hdde-output-delivery-toggle/);
  assert.match(page, /hdde-output-actions__secondary/);
  assert.match(page, /hdde-tertiary-action hdde-output-action--auxiliary/);
  assert.match(page, /data-testid="output-center-open-folder-action"/);
  assert.match(styles, /\.hdde-output-action--primary[\s\S]*?min-height:\s*44px/);
  assert.match(styles, /\.hdde-output-actions__secondary[\s\S]*?grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/);
  assert.match(styles, /\.hdde-output-action--auxiliary[\s\S]*?justify-self:\s*center/);

  const secondaryStart = page.indexOf('className="hdde-output-actions__secondary"');
  const secondaryEnd = page.indexOf("</div>", secondaryStart);
  const secondaryActions = page.slice(secondaryStart, secondaryEnd);
  assert.match(secondaryActions, /进入对比质检/);
  assert.match(secondaryActions, /打开成品/);
  assert.doesNotMatch(secondaryActions, /打开所在目录/);
});

test("output cards are image-first, truncate the real filename, and keep card selection", () => {
  // OC-03 also clears the blank-detail state when a user explicitly selects a card.
  assert.match(page, /className="hdde-output-card"[\s\S]*?onClick=\{\(\) => selectItem\(item\)\}/);
  assert.match(page, /setSelectedId\(item\.id\); setSelectionCleared\(false\)/);
  assert.match(page, /className="hdde-output-thumb"[\s\S]*?title=\{item\.file_name\}/);
  assert.match(styles, /\.hdde-output-card\s*\{[\s\S]*?grid-template-rows:\s*clamp\(180px,\s*18vw,\s*240px\)\s*auto/);
  assert.match(styles, /\.hdde-output-thumb\s*\{[\s\S]*?align-self:\s*stretch/);
  assert.match(styles, /\.hdde-output-thumb img\s*\{[\s\S]*?max-height:\s*100%/);
  assert.match(styles, /\.hdde-output-card-copy strong,[\s\S]*?text-overflow:\s*ellipsis;[\s\S]*?white-space:\s*nowrap/);
});

test("record removal separates current/history and clears detail without file deletion", () => {
  assert.match(page, /scope: listScope/);
  assert.match(page, /清除缺失/);
  assert.match(page, /清空.*当前.*历史/s);
  assert.match(page, /data-remove-id=\{child\.record_id\}/);
  assert.match(page, /data-remove-id=\{item\.id\}/);
  assert.match(page, /setSelectionCleared\(true\)/);
  assert.match(page, /正式输出文件保持不变/);
  assert.doesNotMatch(page, /delete-file|删除正式文件/);
});

test("hover preview is triggered only by the image region and closes without changing card layout", () => {
  const cardStart = page.indexOf('className="hdde-output-card"');
  const cardEnd = page.indexOf("</button>", cardStart);
  const cardSource = page.slice(cardStart, cardEnd);
  const thumbnailStart = page.indexOf("function OutputThumbnail");
  const thumbnailEnd = page.indexOf("function OutputCompareView", thumbnailStart);
  const thumbnailSource = page.slice(thumbnailStart, thumbnailEnd);
  assert.match(cardSource, /<OutputThumbnail item=\{item\}/);
  assert.match(thumbnailSource, /onPointerEnter=\{\(event\) => onPreviewOpen\(item, event\.currentTarget\)\}/);
  assert.match(thumbnailSource, /onPointerLeave=\{onPreviewClose\}/);
  assert.match(thumbnailSource, /onPointerCancel=\{onPreviewClose\}/);
  assert.doesNotMatch(cardSource.slice(0, cardSource.indexOf("<OutputThumbnail")), /onPointerEnter|onPointerLeave/);
  assert.match(page, /setHoverPreview\(\{ item, position \}\)/);
  assert.match(page, /createPortal\([\s\S]*?document\.body/);
  assert.match(page, /window\.addEventListener\("scroll", closeHoverPreview, true\)/);
  assert.match(styles, /\.hdde-output-hover-preview\s*\{[\s\S]*?position:\s*fixed;[\s\S]*?pointer-events:\s*none/);
  assert.doesNotMatch(styles, /\.hdde-output-thumb:hover[^}]*transform:\s*scale/);
});

test("output cards load cached thumbnails progressively without changing original actions", () => {
  assert.match(page, /new IntersectionObserver/);
  assert.match(page, /OUTPUT_THUMBNAIL_PREFETCH_MARGIN_PX/);
  assert.match(page, /item\.thumbnail_url/);
  assert.doesNotMatch(page, /<img[^>]+src=\{apiUrl\(item\.preview_url\)/);
  assert.match(page, /decoding="async"/);
  assert.match(page, /fetchpriority=\{loadPriority === "visible" \? "high" : "low"\}/);
  assert.match(styles, /\.hdde-output-thumb__placeholder[\s\S]*?width:\s*100%;[\s\S]*?height:\s*100%/);
  assert.match(thumbnailLoader, /OUTPUT_THUMBNAIL_MAX_CONCURRENCY\s*=\s*4/);
  assert.match(thumbnailLoader, /left\.priority - right\.priority/);
});

test("hover positioning prefers right, flips left, and clamps to the viewport", () => {
  const right = calculateOutputHoverPreviewPosition({
    anchorRect: { left: 120, right: 320, top: 80, height: 180 },
    viewportWidth: 1200,
    viewportHeight: 800,
    imageWidth: 1600,
    imageHeight: 900,
  });
  assert.equal(right.placement, "right");
  assert.equal(right.left, 332);
  assert.ok(right.top >= 16);

  const left = calculateOutputHoverPreviewPosition({
    anchorRect: { left: 760, right: 960, top: 690, height: 140 },
    viewportWidth: 1000,
    viewportHeight: 760,
    imageWidth: 900,
    imageHeight: 1600,
  });
  assert.equal(left.placement, "left");
  assert.equal(left.left, 268);
  assert.ok(left.top + left.height <= 744);

  const narrow = calculateOutputHoverPreviewPosition({
    anchorRect: { left: 120, right: 260, top: 10, height: 120 },
    viewportWidth: 375,
    viewportHeight: 640,
    imageWidth: 1920,
    imageHeight: 1080,
  });
  assert.equal(narrow.width, 343);
  assert.equal(narrow.left, 16);
  assert.equal(narrow.top, 16);
});

test("right detail removes the duplicate image while preserving real data and actions", () => {
  assert.doesNotMatch(page, /hdde-output-detail-preview/);
  assert.match(page, /<h2 title=\{selected\.file_name\}>\{displayName\(selected\)\}<\/h2>/);
  assert.match(page, /selected\.width[\s\S]*?selected\.height/);
  assert.match(page, /selected\.format[\s\S]*?selected\.size_bytes/);
  assert.match(page, /selected\.created_at/);
  assert.match(page, /toggleDeliveryItem\(selected\)/);
  assert.match(page, /performAction\(selected, "open"\)/);
  assert.match(page, /performAction\(selected, "open-folder"\)/);
});

test("search and sort contracts remain connected to the visible output list", () => {
  assert.match(page, /value=\{searchQuery\}[\s\S]*?setSearchQuery\(event\.target\.value\)/);
  assert.match(page, /fileIdentityName\.includes\(query\) \|\| productDisplayName\.includes\(query\)/);
  assert.match(page, /value=\{sortOrder\}[\s\S]*?setSortOrder\(event\.target\.value\)/);
  assert.match(page, /sortOrder === "oldest" \? -delta : delta/);
});

test("output center renders a small first batch and loads globally filtered pages", () => {
  assert.match(page, /OUTPUT_CENTER_INITIAL_PAGE_SIZE\s*=\s*12/);
  assert.match(page, /OUTPUT_CENTER_PAGE_SIZE\s*=\s*32/);
  assert.match(page, /new URLSearchParams\(\{/);
  assert.match(page, /query:\s*searchQuery\.trim\(\)/);
  assert.match(page, /sort:\s*sortOrder/);
  assert.match(page, /category:\s*activeCategory/);
  assert.match(page, /next\.has_more/);
  // Later pages are requested on scroll, after the current page has painted.
  assert.match(page, /pendingNextOffset = next\.next_offset/);
  assert.match(page, /addEventListener\("scroll", loadNextPage/);
  assert.doesNotMatch(page, /setTimeout\(\(\) => loadRemaining/);
  assert.match(page, /params\.set\("limit", String\(OUTPUT_CENTER_PAGE_SIZE\)\)/);
  assert.match(page, /params\.set\("offset", String\(offset\)\)/);
  assert.doesNotMatch(page, /appendInBatches/);
  assert.match(backend, /def select_output_center_page\(/);
  assert.match(backend, /selected_paths = page\["selected_paths"\]/);
  assert.match(backend, /if resolved not in selected_paths/);
  assert.doesNotMatch(backend, /def paginate_output_center_snapshot\(/);
});

test("output center keeps the 12px product readability floor and shared theme tokens", () => {
  const start = styles.indexOf("/* Output center:");
  const end = styles.indexOf("/* Smart delivery:", start);
  assert.ok(start >= 0);
  assert.ok(end > start);
  const block = styles.slice(start, end);
  assert.doesNotMatch(block, /font-size:\s*(?:[0-9]|1[01])px/);
  assert.match(block, /var\(--content-background\)/);
  assert.match(block, /var\(--card-background\)/);
  assert.match(block, /var\(--brand-primary\)/);
  assert.match(styles, /\.hdde-output-page button:focus-visible/);
});


test("edit lineage loads only on demand and never replaces the selected Result", () => {
  assert.match(page, /data-testid="output-center-lineage-action"/);
  assert.match(page, /showLineage\(selected\)/);
  assert.match(page, /lineageRequestRef/);
  assert.match(page, /round_count/);
  assert.match(page, /initial_source\.file_name/);
  assert.match(page, /continue_result=\$\{encodeURIComponent\(resultId\)\}/);
});
