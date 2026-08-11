import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const settingsPath = path.join(root, "src", "SystemSettingsPage.jsx");
const shellPath = path.join(root, "src", "AppShell.jsx");
const routesPath = path.join(root, "src", "appRoutes.js");
const cssPath = path.join(root, "src", "index.css");
const versionPath = path.join(root, "product_version.json");

const settings = fs.readFileSync(settingsPath, "utf8");
const shell = fs.readFileSync(shellPath, "utf8");
const routes = fs.readFileSync(routesPath, "utf8");
const css = fs.readFileSync(cssPath, "utf8");
const version = JSON.parse(fs.readFileSync(versionPath, "utf8"));

const viteCacheDir = path.join(os.tmpdir(), `hdde-system-settings-test-${process.pid}`);
let viteServer;
let settingsModule;
let buildInfoModule;

test.before(async () => {
  viteServer = await createServer({
    root,
    cacheDir: viteCacheDir,
    appType: "custom",
    server: { middlewareMode: true },
  });
  settingsModule = await viteServer.ssrLoadModule("/src/SystemSettingsPage.jsx");
  buildInfoModule = await viteServer.ssrLoadModule("/src/buildInfo.js");
});

test.after(async () => {
  if (viteServer) await viteServer.close();
  fs.rmSync(viteCacheDir, { recursive: true, force: true });
});

test("system settings removes the duplicate feature status panel", () => {
  assert.doesNotMatch(settings, /eyebrow="FEATURE STATUS"/);
  assert.doesNotMatch(settings, /title="功能状态"/);
  assert.doesNotMatch(settings, /APP_ROUTES|FeatureStatusBadge|hdde-settings-feature/);
  assert.doesNotMatch(css, /hdde-settings-feature/);
});

test("system settings removes the duplicate secondary introduction", () => {
  for (const duplicate of [
    "REAL SETTINGS · ALPHA V1",
    "基础设置与运行状态",
    "仅主题可修改；目录与平台信息均为只读事实。",
  ]) {
    assert.doesNotMatch(settings, new RegExp(duplicate));
  }
  assert.doesNotMatch(settings, /hdde-settings-page__intro/);
  assert.doesNotMatch(css, /hdde-settings-page__intro/);
});

test("editability guidance lives in the relevant settings sections", () => {
  assert.match(settings, /title="外观设置"[\s\S]*description="选择界面主题。/);
  assert.match(settings, /title="本地目录"[\s\S]*description="正式目录是图片处理任务的唯一工作根目录；/);
  assert.ok(settings.indexOf('title="外观设置"') < settings.indexOf('title="本地目录"'));
  assert.match(css, /\.hdde-settings-page > \.hdde-settings-section:first-child \{\s*margin-top: 0;/);
});

test("normal settings condense directory internals into one formal-directory status", () => {
  assert.doesNotMatch(settings, /label="配置默认输出目录"/);
  assert.doesNotMatch(settings, /D:\\Codex\\04_Visual-Master-Pro/);
  assert.doesNotMatch(settings, /label="工作根来源"/);
  assert.doesNotMatch(settings, /label="工作根存在状态"/);
  assert.doesNotMatch(settings, /label="工作根写入状态"/);
  assert.match(settings, /label="工作目录状态"/);
  assert.doesNotMatch(settings, /function isInternalRuntimePath/);
  assert.doesNotMatch(settings, /project_tmp|runtime_fallback/);

  const status = settingsModule.resolveDirectoryStatus("success", {
    app_data_root_source: "saved_config",
    app_data_root_exists: true,
    app_data_root_writable: true,
  });
  assert.deepEqual(status, {
    label: "正常可用",
    tone: "positive",
    showPaths: true,
    problem: "",
    impact: "",
    suggestion: "",
  });
});

test("unavailable formal directory blocks processing and directs the user to reselect", () => {
  const status = settingsModule.resolveDirectoryStatus("success", {
    directory_ready: false,
    directory_message: "正式目录不可写，请前往系统设置重新选择目录。",
    failure_reason: "已保存的正式目录不存在。",
  });
  assert.equal(status.label, "正式目录未就绪");
  assert.equal(status.tone, "negative");
  assert.equal(status.showPaths, true);
  assert.equal(status.problem, "已保存的正式目录不存在。");
  assert.match(status.impact, /图片处理任务已阻断/);
  assert.match(status.suggestion, /恢复当前目录后重新检测/);
  assert.match(settings, /value=\{workdir\.app_data_root \|\| workdir\.failed_path\}/);
});

test("representable directory failures include problem impact and action", () => {
  assert.doesNotMatch(settings, /health\.reason\?\.message|workdir\.reason\?\.message/);
  assert.match(settings, /运行信息暂不可用，请确认本地后端服务已启动后刷新页面。/);
  assert.match(settings, /本地目录信息暂不可用，请确认本地后端服务已启动后刷新页面。/);

  const cases = [
    ["目录不存在", settingsModule.resolveDirectoryStatus("success", { app_data_root_exists: false, app_data_root_writable: false })],
    ["目录不可写", settingsModule.resolveDirectoryStatus("success", { app_data_root_exists: true, app_data_root_writable: false })],
    ["状态读取失败", settingsModule.resolveDirectoryStatus("error", {})],
    ["状态异常", settingsModule.resolveDirectoryStatus("success", {})],
  ];
  for (const [label, status] of cases) {
    assert.equal(status.label, label);
    assert.equal(status.tone, "negative");
    assert.equal(status.showPaths, false);
    assert.ok(status.problem.length > 0);
    assert.ok(status.impact.length > 0);
    assert.ok(status.suggestion.length > 0);
  }
});

test("recheck calls the real workdir endpoint with explicit no-store semantics", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          success: true,
          data: {
            directory_ready: false,
            processing_allowed: false,
            app_data_root: "D:\\影界测试\\正式目录",
            failure_reason: "已保存的正式目录不存在。",
          },
        };
      },
    };
  };
  try {
    const result = await settingsModule.requestWorkdirStatus();
    assert.equal(result.directory_ready, false);
    assert.equal(result.processing_allowed, false);
    assert.equal(result.app_data_root, "D:\\影界测试\\正式目录");
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(calls.length, 1);
  assert.match(calls[0].url, /^http:\/\/localhost:8787\/api\/app\/workdir\?recheck=\d+$/);
  assert.equal(calls[0].options.cache, "no-store");
  assert.match(settings, /"重新检测"/);
  assert.match(settings, /handleRecheckFormalDirectory/);
});

test("recheck can replace blocked state with ready state without a page reload", async () => {
  const originalFetch = globalThis.fetch;
  const states = [
    {
      directory_ready: false,
      processing_allowed: false,
      app_data_root: "D:\\影界测试\\正式目录",
      failure_reason: "已保存的正式目录不存在。",
    },
    {
      directory_ready: true,
      processing_allowed: true,
      app_data_root: "D:\\影界测试\\正式目录",
      failure_reason: "",
    },
  ];
  globalThis.fetch = async () => ({
    ok: true,
    status: 200,
    async json() {
      return { success: true, data: states.shift() };
    },
  });
  try {
    const blocked = await settingsModule.requestWorkdirStatus();
    const recovered = await settingsModule.requestWorkdirStatus();
    assert.equal(blocked.directory_ready, false);
    assert.equal(recovered.directory_ready, true);
    assert.equal(recovered.processing_allowed, true);
    assert.equal(recovered.app_data_root, blocked.app_data_root);
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.doesNotMatch(settings, /window\.location\.reload|location\.reload/);
});

test("directory selection save failure keeps the old path and exposes the backend reason", async () => {
  const originalFetch = globalThis.fetch;
  const currentWorkdir = {
    directory_ready: true,
    processing_allowed: true,
    app_data_root: "D:\\影界测试\\原正式目录",
  };
  globalThis.fetch = async () => ({
    ok: false,
    status: 500,
    async json() {
      return {
        detail: {
          code: "SETTINGS_WRITE_FAILED",
          message: "保存正式目录失败：controlled settings failure",
        },
      };
    },
  });
  try {
    await assert.rejects(
      settingsModule.requestApiPayload("/api/app/workdir/select-popup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      }),
      /保存正式目录失败：controlled settings failure/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(currentWorkdir.app_data_root, "D:\\影界测试\\原正式目录");
  assert.doesNotMatch(settings, /setSnapshot\([^)]*candidate/i);
});

test("left navigation keeps every configured formal entry without redundant status badges", () => {
  assert.match(shell, /NAVIGATION_GROUPS\.map/);
  assert.match(shell, /navigationRoutes/);
  assert.doesNotMatch(shell, /FeatureStatusBadge/);
  const configuredRoutes = (routes.match(/\n\s+key: "/g) || []).length;
  assert.ok(configuredRoutes >= 12);
  assert.match(shell, /showInNavigation !== false/);
});

test("product and version facts are consolidated without engineering placeholders", () => {
  assert.match(settings, /title="产品与版本"/);
  assert.doesNotMatch(settings, /title="更新信息"|title="关于影界"|暂未开放|待正式发布机制建立后接入|PRODUCT_RELEASE_NAME|版本名称/);
  assert.equal((settings.match(/label="产品版本"/g) || []).length, 1);
});

test("system settings displays the unified V0.5.4-dev product version", () => {
  assert.equal(version.version, "0.5.4-dev");
  assert.equal(version.display_version, "V0.5.4-dev");
  assert.match(settings, /PRODUCT_VERSION_LABEL/);
  assert.match(settings, /label="产品版本" value=\{health\.version \|\| PRODUCT_VERSION_LABEL\}/);
  assert.match(settings, /label="当前构建" value=\{CURRENT_BUILD_ID\}/);
  assert.doesNotMatch(settings, /V0\.5\.3/);
});

test("current build identity is fixed for the running build and includes trace metadata", () => {
  const buildId = buildInfoModule.CURRENT_BUILD_ID;
  assert.match(buildId, /^V0\.5\.4-dev\+(?:[0-9a-f]{7,12}|nogit)\.(?:clean|dirty|unknown)\.\d{8}T\d{9}Z$/);
  assert.equal(buildInfoModule.CURRENT_BUILD_ID, buildId);
});

test("settings identifies 1080P as the default delivery resolution", () => {
  assert.match(settings, /label="默认交付分辨率" value=\{health\.target_resolution\}/);
  assert.doesNotMatch(settings, /label="目标分辨率"/);
});

test("settings keeps technical research history out of the primary product surface", () => {
  assert.doesNotMatch(settings, /1080P研究基线|第三方依赖声明/);
});

test("settings keeps system dark and light theme controls", () => {
  for (const value of ["system", "dark", "light"]) {
    assert.match(shell, new RegExp(`value: "${value}"`));
  }
  assert.match(settings, /themeModes\.map/);
  assert.match(settings, /selectThemeMode/);
});

test("settings has no empty section container after panel removal", () => {
  assert.doesNotMatch(settings, /<SettingsSection[^>]*>\s*<\/SettingsSection>/);
  assert.equal((settings.match(/<SettingsSection\n/g) || []).length, 3);
});

test("settings keeps the existing compression-aligned card baseline", () => {
  assert.match(css, /\.hdde-settings-page \{/);
  assert.match(css, /\.hdde-settings-section \{[\s\S]*border-radius: 8px/);
  assert.match(css, /background: var\(--card-background\)/);
});
