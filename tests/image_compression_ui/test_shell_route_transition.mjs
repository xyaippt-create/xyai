import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (relativePath) => fs.readFileSync(path.join(ROOT, relativePath), "utf8");
const app = read("src/App.jsx");
const shell = read("src/AppShell.jsx");
const styles = read("src/index.css");

test("route transitions are committed once at the router boundary", () => {
  assert.match(app, /document\.startViewTransition\(\(\) => flushSync\(commit\)\)/);
  assert.match(app, /currentRoutePathRef\.current !== nextRoutePath/);
  assert.match(app, /activeRouteTransitionRef\.current\?\.skipTransition\(\)/);
  assert.match(app, /transition\.ready\.catch\(\(\) => \{\}\)/);
  assert.match(app, /transition\.updateCallbackDone\.catch\(\(\) => \{\}\)/);
  assert.match(app, /commitPathChange\(browserPath\(\)\)/);
});

test("same-route state updates and reduced motion bypass the page transition", () => {
  assert.match(app, /!shouldAnimate \|\| reducedMotion/);
  assert.match(app, /prefers-reduced-motion: reduce/);
  assert.doesNotMatch(shell, /<main[^>]*hdde-shell-content[^>]*key=/);
});

test("only the existing Shell content surface owns the restrained animation", () => {
  assert.match(styles, /\.hdde-app-shell \.hdde-shell-content \{\s*view-transition-name: hdde-route-content;/);
  assert.match(styles, /hdde-route-content-out 160ms/);
  assert.match(styles, /hdde-route-content-in 200ms/);
  assert.match(styles, /translateY\(-4px\)/);
  assert.match(styles, /translateY\(6px\)/);
  assert.match(styles, /::view-transition-group\(root\),[\s\S]*animation: none;/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)[\s\S]*::view-transition-group\(hdde-route-content\)/);
});

test("unknown routes keep the recovery page renderable without route metadata", () => {
  assert.match(app, /if \(!route\)\s*\{[\s\S]*<UnknownRoutePage/);
  assert.match(app, /const requestedMode = route\?\.key === "processing"/);
  assert.doesNotMatch(app, /const requestedMode = route\.key === "processing"/);
});
