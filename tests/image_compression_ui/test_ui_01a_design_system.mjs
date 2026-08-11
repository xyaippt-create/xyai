import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (relativePath) => fs.readFileSync(path.join(ROOT, relativePath), "utf8");

const shell = read("src/AppShell.jsx");
const routes = read("src/appRoutes.js");
const styles = read("src/index.css");
const diagnosis = read("src/ImageDiagnosisPage.jsx");
const outputs = read("src/OutputCenterPage.jsx");
const settings = read("src/SystemSettingsPage.jsx");
const dashboard = read("src/DashboardPage.jsx");

test("UI-01A shell groups the complete formal navigation without restoring removed entries", () => {
  for (const group of ["工作台", "图片处理", "交付", "系统"]) assert.match(shell, new RegExp(`label: "${group}"`));
  for (const key of ["processing", "image-diagnosis", "four-k-enhancement", "color-correction", "compression", "retouch", "outputs", "smart-delivery", "settings"]) {
    assert.match(shell, new RegExp(`"?${key}"?`));
  }
  assert.match(routes, /key: "tasks"[\s\S]*?showInNavigation: false/);
  assert.match(routes, /key: "history"[\s\S]*?showInNavigation: false/);
  assert.match(routes, /key: "batch"[\s\S]*?showInNavigation: false/);
});

test("UI-01A removes redundant shell status badges and retains accessible navigation", () => {
  assert.doesNotMatch(shell, /FeatureStatusBadge/);
  assert.doesNotMatch(shell, /当前页面/);
  assert.match(shell, /className="hdde-skip-link"/);
  assert.match(shell, /aria-current=\{active \? "page"/);
  assert.match(shell, /mainRef\.current\?\.scrollTo\(\{ top: 0, left: 0, behavior: "auto" \}\)/);
  assert.match(shell, /mainRef\.current\?\.focus/);
  assert.match(shell, /<HddeIcon/);
});

test("formal navigation status and public processing names use the frozen product wording", () => {
  assert.match(routes, /key: "compression"[\s\S]*?status: FEATURE_STATUSES\.ENABLED/);
  assert.match(routes, /key: "settings"[\s\S]*?status: FEATURE_STATUSES\.ENABLED/);
  assert.match(routes, /name: "4K高清增强"/);
  assert.match(dashboard, /label: "1080P标准增强"/);
  assert.match(dashboard, /label: "1080P安全增强"/);
  assert.match(dashboard, /label: "4K高清画质增强"/);
});

test("representative pages consume one shared page hierarchy", () => {
  for (const source of [diagnosis, outputs, settings]) assert.match(source, /HddePageHeader/);
  assert.match(diagnosis, /HddeStatusPill tone="info"/);
  assert.match(outputs, /headingId="output-center-title"/);
});

test("design system owns semantic tokens, responsive shell, focus and reduced motion", () => {
  assert.match(styles, /UI-01A — HDDE precision workspace design system/);
  assert.match(styles, /--hdde-space-4: 16px/);
  assert.match(styles, /--brand-primary: #2d6fe8/i);
  assert.match(styles, /\.hdde-navigation-group__label/);
  assert.match(styles, /@media \(max-width: 820px\)/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(styles, /\.hdde-skip-link:focus/);
});
