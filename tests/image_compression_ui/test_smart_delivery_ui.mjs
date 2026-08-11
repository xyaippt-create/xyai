import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { APP_ROUTES } from "../../src/appRoutes.js";
import { FEATURE_STATUSES } from "../../src/platformStatus.js";

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(currentDirectory, "..", "..");
const app = fs.readFileSync(path.join(root, "src", "App.jsx"), "utf8");
const outputs = fs.readFileSync(path.join(root, "src", "OutputCenterPage.jsx"), "utf8");
const delivery = fs.readFileSync(path.join(root, "src", "SmartDeliveryPage.jsx"), "utf8");
const backend = fs.readFileSync(path.join(root, "backend", "image_compression_api.py"), "utf8");
const styles = fs.readFileSync(path.join(root, "src", "index.css"), "utf8");

test("smart delivery accepts unified result ids from the output center without exposing paths", () => {
  const route = APP_ROUTES.find((item) => item.key === "smart-delivery");
  assert.equal(route?.status, FEATURE_STATUSES.ENABLED);
  assert.equal(route?.implementationType, "existing");
  assert.match(app, /<SmartDeliveryPage/);
  assert.match(outputs, /selectedDeliveryIds/);
  assert.match(outputs, /unifiedResultIds/);
  assert.match(outputs, /\/smart-delivery\?results=/);
  assert.match(outputs, /\/smart-delivery\?items=/);
  assert.doesNotMatch(outputs, /output_path|source_path|input_path/);
});

test("preview and execution use one server-issued plan and explicit confirmation", () => {
  assert.match(delivery, /\/api\/smart-delivery\/preflight/);
  assert.match(delivery, /const selectionMode = selectedResultIds\.length \? "result_ids" : "item_ids"/);
  assert.match(delivery, /\{ \[selectionMode\]: selectedValues, rules \}/);
  assert.match(delivery, /plan_id:\s*preflight\.plan_id/);
  assert.match(delivery, /confirmed:\s*true/);
  assert.match(delivery, /!preflight\?\.ready \|\| !confirmed \|\| executing/);
  assert.match(delivery, /源成品.*最终交付文件名/s);
  assert.match(delivery, /预检已阻止写入/);
  assert.doesNotMatch(delivery, /output_path|source_path|input_path/);
});

test("backend keeps preflight all-or-nothing and execution copy-only", () => {
  assert.match(backend, /SMART_DELIVERY_PREFLIGHT_BLOCKED/);
  assert.match(backend, /destination_path\.open\("xb"\)/);
  assert.match(backend, /source_hash_before != source_hash_after/);
  assert.match(backend, /delivery_hash != source_hash_before/);
  assert.match(backend, /TARGET_ALREADY_EXISTS/);
  assert.match(backend, /WINDOWS_INVALID_CHARACTER/);
  assert.match(backend, /DUPLICATE_FINAL_NAME/);
  assert.match(backend, /UNIFIED_RESULT_REQUIRED/);
  assert.match(backend, /UNIFIED_RESULT_NOT_FOUND/);
  assert.match(backend, /delivery_item_id/);
  assert.match(backend, /source_result_id/);
  assert.match(backend, /source_processing_type/);
  assert.doesNotMatch(delivery, /tmp|runtime_data|mock|placeholder/i);
});

test("smart delivery uses shared themes, accessible focus and the 12px floor", () => {
  const start = styles.indexOf("/* Smart delivery:");
  assert.ok(start >= 0);
  const block = styles.slice(start);
  assert.doesNotMatch(block, /font-size:\s*(?:[0-9]|1[01])px/);
  assert.match(block, /var\(--content-background\)/);
  assert.match(block, /var\(--card-background\)/);
  assert.match(block, /focus-visible/);
  assert.match(block, /prefers-reduced-motion/);
});
