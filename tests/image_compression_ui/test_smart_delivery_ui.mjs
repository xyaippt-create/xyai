import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { APP_ROUTES } from "../../src/appRoutes.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");
const delivery = read("src/SmartDeliveryPage.jsx");
const outputCenter = read("src/OutputCenterPage.jsx");
const taskDetail = read("src/TaskDetailPage.jsx");
const app = read("src/App.jsx");
const shell = read("src/AppShell.jsx");
const backend = read("backend/image_compression_api.py");
const publishSafety = read("engine/output/publish_safety.py");
const css = read("src/index.css");

test("independent naming is absent from navigation and public copy", () => {
  const route = APP_ROUTES.find((item) => item.key === "smart-delivery");
  assert.equal(route?.name, "文件交付");
  assert.equal(route?.showInNavigation, false);
  assert.match(shell, /\{ label: "交付", items: \["outputs", "print-8k"\] \}/);
  assert.doesNotMatch([delivery, outputCenter, shell].join("\n"), /智能命名|批量命名/);
  assert.equal(fs.existsSync(path.join(root, "src", "BatchImageNamingPanel.jsx")), false);
});

test("output center keeps an internal compatibility handoff without a naming product entry", () => {
  assert.match(outputCenter, /\/smart-delivery\?results=/);
  assert.match(outputCenter, /\/smart-delivery\?items=/);
  assert.match(outputCenter, /生成交付副本\s*<span className="hdde-output-delivery-count"[^>]*>\{deliveryCount\}<\/span>/);
  assert.match(outputCenter, /加入交付清单/);
  assert.doesNotMatch(outputCenter, /发送到智能命名|进入智能命名/);
});

test("compatibility delivery page uses fixed source filenames and one public preflight plan", () => {
  assert.match(delivery, /JSON\.stringify\(\{ \[selectionMode\]: selectedValues, rules: \{\} \}\)/);
  assert.match(delivery, /\/api\/smart-delivery\/preflight/);
  assert.match(delivery, /\/api\/smart-delivery\/execute/);
  assert.match(delivery, /plan_id: preflight\.plan_id, confirmed: true, idempotency_key: requestKey/);
  assert.doesNotMatch(delivery, /type="checkbox"|确认并生成交付副本/);
  const batchPanel = read("src/BatchCompressionPanel.jsx");
  assert.doesNotMatch(batchPanel, /我已核对选择项|确认批量交付|setConfirmOpen/);
  assert.match(batchPanel, /data-testid="batch-delivery-open"[^\n]*beginDelivery\(\)/);
  assert.match(app, /pathname === "\/smart-delivery" \? \{ startDelivery: true \}/);
  assert.doesNotMatch(delivery, /content-names|base_mode|prefix|suffix|find_text|replace_text|sequence_enabled|date_enabled|template/);
});

test("task detail owns the real Result to Delivery confirmation path", () => {
  assert.match(taskDetail, /requestDeliveryJson\("\/api\/smart-delivery\/preflight"/);
  assert.match(taskDetail, /JSON\.stringify\(\{ result_ids: \[resultId\], rules: \{\} \}\)/);
  // Execute goes through the shared idempotent single-Result helper.
  assert.match(taskDetail, /executeSingleResultDelivery\(\{\s*planId: preflight\.plan_id,\s*resultId,\s*idempotencyKey: deliveryRequestKey,\s*request: requestDeliveryJson,/);
  assert.match(taskDetail, /handleOpenDeliveryFolder/);
  assert.doesNotMatch(taskDetail, /openAdvancedDelivery|onOpenAdvancedDelivery/);
  assert.doesNotMatch(app, /onOpenAdvancedDelivery/);
});

test("backend removes A-line APIs while preserving public Delivery safety and copy contracts", () => {
  assert.doesNotMatch(backend, /@app\.post\("\/api\/smart-delivery\/content-names"\)/);
  assert.doesNotMatch(backend, /\/api\/smart-delivery\/batch-naming\//);
  assert.match(backend, /@app\.post\("\/api\/smart-delivery\/preflight"\)/);
  assert.match(backend, /@app\.post\("\/api\/smart-delivery\/execute"\)/);
  assert.match(backend, /def smart_delivery_name_issues/);
  assert.match(backend, /source_name_issues = smart_delivery_name_issues\(source_path\.stem, source_path\.suffix\)/);
  assert.doesNotMatch(backend, /resolve_collision_path\(delivery_root, source_name\)/);
  assert.match(backend, /destination_path\.exists\(\) or windows_filename_key\(destination_path\.name\) in seen_names/);
  assert.match(backend, /publish_verified_file_copy_no_overwrite/);
  assert.match(backend, /registered_output_sha256=entry\["_registered_output_sha256"\]/);
  assert.match(publishSafety, /copied_sha256 != expected/);
  assert.match(publishSafety, /committed_sha256 != expected/);
  assert.match(publishSafety, /_publish_open_file_no_replace\(open_file, private_path, candidate\)/);
  assert.match(backend, /"code": "DELIVERY_NAMING_RULES_RETIRED"/);
});

test("retired naming styles are removed while batch compression and delivery styles remain", () => {
  assert.doesNotMatch(css, /\.hdde-batch-(?:image-)?naming|batch-naming-page/);
  assert.match(css, /\.hdde-batch-compression/);
  assert.match(css, /\.hdde-delivery-page/);
  assert.match(css, /\.hdde-delivery-result-list/);
});

test("receipt groups file and directory actions and shows the source name when it differs", () => {
  assert.match(delivery, /item\.source_file_name !== filename/);
  assert.match(delivery, /total === 1 \? "hdde-primary-action" : "hdde-secondary-action"/);
  assert.match(delivery, /total > 1 && !hasFailures \? "hdde-primary-action" : "hdde-secondary-action"/);
  assert.match(delivery, /<nav className="hdde-receipt-navigation" aria-label="交付完成后的下一步">/);
  assert.match(delivery, /completedPrint && <a [^>]*href="\/print-8k"/);
  assert.doesNotMatch(delivery, /继续查看正式成品|hdde-delivery-result-summary/);
});
