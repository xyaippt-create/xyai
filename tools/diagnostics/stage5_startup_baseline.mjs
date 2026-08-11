import { spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { createReadStream, existsSync, lstatSync, mkdirSync, readFileSync, realpathSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { performance } from "node:perf_hooks";
import { fileURLToPath, pathToFileURL } from "node:url";

const TOOL_PATH = fileURLToPath(import.meta.url);
const PROJECT_ROOT = path.resolve(path.dirname(TOOL_PATH), "../..");
const DIST_ROOT = path.join(PROJECT_ROOT, "dist");
const PYTHON_PATH = path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe");
const SETTINGS_PATH = path.join(PROJECT_ROOT, "settings", "settings.json");
const PRODUCT_VERSION = JSON.parse(readFileSync(path.join(PROJECT_ROOT, "product_version.json"), "utf8")).display_version;
const BACKEND_PORT = 8787;
const DEV_PORT = 5173;
const BUILD_PORT = 4173;
const DEFAULT_VALID_RUNS = 5;
const STARTUP_TIMEOUT_MS = 45_000;
const PROCESS_EXIT_TIMEOUT_MS = 8_000;
const PORT_RELEASE_TIMEOUT_MS = 8_000;
const PROFILE_DELETE_RETRIES = 6;
const PROFILE_DELETE_INTERVAL_MS = 100;
const PROFILE_MARKER_FILE = ".hdde-stage5-profile.json";
export const FINAL_SETTINGS_QUIESCENCE_MS = 750;
export const FINAL_SETTINGS_READ_INTERVAL_MS = 250;
export const FATAL_EXIT_CODE = 2;
export const CHROME_LIFECYCLE_FATAL_EXIT_CODE = 3;
const activeProcesses = new Map();

export class FatalMeasurementStopError extends Error {
  constructor(message, {
    code = "FATAL_MEASUREMENT_STOP",
    stage = "measurement",
    runId = "",
    expectedSemanticSha = "",
    actualSemanticSha = "",
    subcode = "",
    cleanupRequired = true,
    cause,
  } = {}) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = "FatalMeasurementStopError";
    this.code = code;
    this.fatal = true;
    this.stage = stage;
    this.runId = runId;
    this.expectedSemanticSha = expectedSemanticSha;
    this.actualSemanticSha = actualSemanticSha;
    this.subcode = subcode;
    this.cleanupRequired = cleanupRequired;
    if (cause !== undefined && this.cause === undefined) this.cause = cause;
  }
}

export function isFatalMeasurementError(error) {
  return error instanceof FatalMeasurementStopError || error?.fatal === true;
}

export function measurementExitCode(error) {
  if (error?.code === "CHROME_LIFECYCLE_CLEANUP_INCOMPLETE" || error?.code === "MEASUREMENT_RUN_SAFETY_GATE_FAILED") {
    return CHROME_LIFECYCLE_FATAL_EXIT_CODE;
  }
  return isFatalMeasurementError(error) ? FATAL_EXIT_CODE : 1;
}

export function createResourceRegistry({ runSessionId = randomUUID(), profileRoot } = {}) {
  const root = path.resolve(profileRoot || path.join(os.tmpdir(), "hdde-stage5-startup-profiles", runSessionId));
  return {
    runSessionId,
    profileRoot: root,
    currentRunId: "",
    currentGroupId: "",
    processes: new Map(),
    chromeLifecycles: new Set(),
    ports: new Set(),
    profiles: new Map(),
    temporaryFiles: new Set(),
    primaryError: null,
    cleanupErrors: [],
    secondaryFatalErrors: [],
    groupCleanupStates: new Map(),
    pendingCleanupTasks: new Set(),
    finalPortStates: new Map(),
    resourceSafetyValidated: false,
    finalSettingsCheck: null,
    globalAbort: false,
    cleanupStarted: false,
    cleanupCompleted: false,
  };
}

function registerFatalError(registry, error) {
  if (!registry.primaryError) registry.primaryError = error;
  else if (registry.primaryError !== error && !registry.secondaryFatalErrors.includes(error)) registry.secondaryFatalErrors.push(error);
  registry.globalAbort = true;
  return registry.primaryError;
}

function chromeLifecycleFatal(lifecycle, subcode, message) {
  return new FatalMeasurementStopError(message, {
    code: "CHROME_LIFECYCLE_CLEANUP_INCOMPLETE",
    subcode,
    stage: "chrome_lifecycle_cleanup",
    runId: lifecycle?.runId || "",
    cleanupRequired: true,
  });
}

function recordCleanupError(target, stage, error) {
  const row = { stage, message: error?.message || String(error) };
  target.cleanupErrors.push(row);
  return row;
}

function throwIfGlobalAbort(registry) {
  if (registry?.globalAbort) {
    throw registry.primaryError || new FatalMeasurementStopError("Measurement was globally aborted.", { code: "GLOBAL_ABORT" });
  }
}

export function assertSettingsSemanticUnchanged(expectedSemanticSha, digest, context = {}) {
  if (digest.semantic_sha256 === expectedSemanticSha) return digest;
  throw new FatalMeasurementStopError("settings/settings.json semantic SHA changed", {
    code: "SETTINGS_SEMANTIC_SHA_CHANGED",
    stage: context.stage || "settings_integrity_check",
    runId: context.runId || "",
    expectedSemanticSha,
    actualSemanticSha: digest.semantic_sha256,
    cleanupRequired: true,
    cause: context.cause,
  });
}

function parseArgs(argv) {
  const parsed = { command: argv[0] || "--help", output: "", runs: DEFAULT_VALID_RUNS, port: BUILD_PORT };
  for (let index = 1; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--output") parsed.output = path.resolve(argv[++index]);
    else if (value === "--runs") parsed.runs = Number.parseInt(argv[++index], 10);
    else if (value === "--port") parsed.port = Number.parseInt(argv[++index], 10);
  }
  return parsed;
}

function sha256Buffer(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]));
  }
  return value;
}

export function settingsDigest(settingsPath = SETTINGS_PATH) {
  const bytes = readFileSync(settingsPath);
  const canonical = JSON.stringify(canonicalize(JSON.parse(bytes.toString("utf8"))));
  return {
    byte_sha256: sha256Buffer(bytes),
    semantic_sha256: sha256Buffer(Buffer.from(canonical, "utf8")),
    size_bytes: bytes.length,
  };
}

function hashFiles(root) {
  const rows = [];
  function visit(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true }).sort((left, right) => left.name.localeCompare(right.name))) {
      const absolute = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(absolute);
      else if (entry.isFile()) {
        const bytes = readFileSync(absolute);
        rows.push({ path: path.relative(root, absolute).replaceAll("\\", "/"), size_bytes: bytes.length, sha256: sha256Buffer(bytes) });
      }
    }
  }
  visit(root);
  return rows;
}

function writeJson(target, payload) {
  mkdirSync(path.dirname(target), { recursive: true });
  writeFileSync(target, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function utcNow() {
  return new Date().toISOString();
}

function findChrome() {
  const candidates = [
    process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, "Google", "Chrome", "Application", "chrome.exe"),
    process.env.PROGRAMFILES && path.join(process.env.PROGRAMFILES, "Google", "Chrome", "Application", "chrome.exe"),
    process.env["PROGRAMFILES(X86)"] && path.join(process.env["PROGRAMFILES(X86)"], "Google", "Chrome", "Application", "chrome.exe"),
  ].filter(Boolean);
  const result = candidates.find((candidate) => existsSync(candidate));
  if (!result) throw new Error("Google Chrome executable was not found.");
  return result;
}

function startProcess(label, executable, args, options = {}) {
  const child = spawn(executable, args, {
    cwd: PROJECT_ROOT,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", ...options.env },
    windowsHide: options.windowsHide !== false,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const record = { label, child, stdout: "", stderr: "", started_at_utc: utcNow() };
  child.stdout.on("data", (chunk) => { record.stdout += chunk.toString("utf8"); });
  child.stderr.on("data", (chunk) => { record.stderr += chunk.toString("utf8"); });
  activeProcesses.set(child.pid, record);
  child.once("exit", (code, signal) => {
    record.exit_code = code;
    record.exit_signal = signal;
    record.exited_at_utc = utcNow();
    activeProcesses.delete(child.pid);
  });
  return record;
}

async function runCommand(executable, args) {
  return new Promise((resolve) => {
    const child = spawn(executable, args, { cwd: PROJECT_ROOT, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk.toString("utf8"); });
    child.stderr.on("data", (chunk) => { stderr += chunk.toString("utf8"); });
    child.once("exit", (code) => resolve({ code, stdout, stderr }));
  });
}

async function stopProcess(record) {
  if (!record?.child || record.child.exitCode !== null || record.child.signalCode !== null) return;
  if (process.platform === "win32") {
    await runCommand("taskkill.exe", ["/PID", String(record.child.pid), "/T", "/F"]);
  } else {
    record.child.kill("SIGTERM");
  }
  if (record.child.exitCode !== null || record.child.signalCode !== null) return;
  const exited = await new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), PROCESS_EXIT_TIMEOUT_MS);
    record.child.once("exit", () => {
      clearTimeout(timer);
      resolve(true);
    });
    if (record.child.exitCode !== null || record.child.signalCode !== null) {
      clearTimeout(timer);
      resolve(true);
    }
  });
  if (!exited && record.child.exitCode === null && record.child.signalCode === null) throw new Error(`recorded process ${record.child.pid} did not exit within ${PROCESS_EXIT_TIMEOUT_MS}ms`);
}

async function cleanupAll() {
  for (const record of [...activeProcesses.values()].reverse()) await stopProcess(record);
}

async function delay(milliseconds) {
  await new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 2_000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function pollUntil(check, timeoutMs, label) {
  const deadline = performance.now() + timeoutMs;
  let lastError = null;
  while (performance.now() < deadline) {
    try {
      const value = await check();
      if (value) return value;
    } catch (error) {
      lastError = error;
    }
    await delay(40);
  }
  throw new Error(`${label} timed out${lastError ? `: ${lastError.message}` : ""}`);
}

async function isPortOpen(port) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: "127.0.0.1", port });
    socket.setTimeout(250);
    socket.once("connect", () => { socket.destroy(); resolve(true); });
    socket.once("timeout", () => { socket.destroy(); resolve(false); });
    socket.once("error", () => resolve(false));
  });
}

async function waitForPortClosed(port) {
  await pollUntil(async () => !(await isPortOpen(port)), PORT_RELEASE_TIMEOUT_MS, `port ${port} release`);
}

export async function verifyPortReleased(port, {
  isPortOpenFn = isPortOpen,
  timeoutMs = PORT_RELEASE_TIMEOUT_MS,
  intervalMs = 40,
} = {}) {
  const deadline = performance.now() + timeoutMs;
  do {
    if (!(await isPortOpenFn(port))) return true;
    await delay(intervalMs);
  } while (performance.now() < deadline);
  return !(await isPortOpenFn(port));
}

async function waitForBackend() {
  return pollUntil(async () => {
    const response = await fetchWithTimeout(`http://127.0.0.1:${BACKEND_PORT}/api/health`);
    if (response.status !== 200) return null;
    const payload = await response.json();
    return payload?.success === true && payload?.data?.version === PRODUCT_VERSION ? payload : null;
  }, STARTUP_TIMEOUT_MS, "backend health");
}

function extractAssets(html) {
  const assets = [];
  for (const match of html.matchAll(/(?:src|href)=["']([^"']+\.(?:js|css))["']/g)) assets.push(match[1]);
  return [...new Set(assets)];
}

async function waitForFrontend(port) {
  return pollUntil(async () => {
    const response = await fetchWithTimeout(`http://127.0.0.1:${port}/`);
    if (response.status !== 200) return null;
    const contentType = response.headers.get("content-type") || "";
    const html = await response.text();
    return contentType.includes("text/html") && html.includes('<div id="root"></div>') ? { html, content_type: contentType } : null;
  }, STARTUP_TIMEOUT_MS, "frontend HTML");
}

async function validateAssets(port, html) {
  const rows = [];
  for (const asset of extractAssets(html)) {
    const response = await fetchWithTimeout(new URL(asset, `http://127.0.0.1:${port}/`));
    rows.push({ path: asset, status: response.status, content_type: response.headers.get("content-type") || "" });
  }
  return rows;
}

function safeStaticPath(urlPath) {
  const decoded = decodeURIComponent(urlPath.split("?", 1)[0]);
  const relative = decoded === "/" ? "index.html" : decoded.replace(/^\/+/, "");
  const absolute = path.resolve(DIST_ROOT, relative);
  return absolute.startsWith(`${DIST_ROOT}${path.sep}`) || absolute === path.join(DIST_ROOT, "index.html") ? absolute : null;
}

function contentTypeFor(filePath) {
  if (filePath.endsWith(".html")) return "text/html; charset=utf-8";
  if (filePath.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (filePath.endsWith(".css")) return "text/css; charset=utf-8";
  if (filePath.endsWith(".json")) return "application/json; charset=utf-8";
  if (filePath.endsWith(".png")) return "image/png";
  if (filePath.endsWith(".svg")) return "image/svg+xml";
  return "application/octet-stream";
}

function proxyApi(request, response) {
  const upstream = http.request({
    host: "127.0.0.1",
    port: BACKEND_PORT,
    method: request.method,
    path: request.url,
    headers: { ...request.headers, host: `127.0.0.1:${BACKEND_PORT}` },
  }, (upstreamResponse) => {
    response.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
    upstreamResponse.pipe(response);
  });
  upstream.on("error", (error) => {
    response.writeHead(502, { "content-type": "application/json; charset=utf-8" });
    response.end(JSON.stringify({ success: false, message: "benchmark upstream unavailable", error: error.code || "UPSTREAM_ERROR" }));
  });
  request.pipe(upstream);
}

function serveBuild(port) {
  if (!existsSync(path.join(DIST_ROOT, "index.html"))) throw new Error("dist/index.html is missing; run npm.cmd run build first.");
  const server = http.createServer((request, response) => {
    if ((request.url || "").startsWith("/api/")) {
      proxyApi(request, response);
      return;
    }
    let target = safeStaticPath(request.url || "/");
    if (!target) {
      response.writeHead(403).end("Forbidden");
      return;
    }
    if (!existsSync(target) || !statSync(target).isFile()) target = path.join(DIST_ROOT, "index.html");
    response.writeHead(200, { "content-type": contentTypeFor(target), "cache-control": target.endsWith("index.html") ? "no-cache" : "public, max-age=3600" });
    createReadStream(target).pipe(response);
  });
  server.listen(port, "127.0.0.1", () => process.stdout.write(`${JSON.stringify({ event: "FIXED_BUILD_INTEGRATION_READY", port })}\n`));
}

class CdpSession {
  constructor(url) {
    this.url = url;
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Map();
    this.errorListeners = [];
  }

  async connect() {
    this.socket = new WebSocket(this.url);
    await new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve, { once: true });
      this.socket.addEventListener("error", reject, { once: true });
    });
    this.socket.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.id) {
          const pending = this.pending.get(payload.id);
          if (!pending) return;
          this.pending.delete(payload.id);
          if (payload.error) pending.reject(new Error(payload.error.message));
          else pending.resolve(payload.result || {});
          return;
        }
        for (const listener of this.listeners.get(payload.method) || []) listener(payload.params || {});
      } catch (error) {
        for (const listener of this.errorListeners) listener(error);
      }
    });
  }

  on(method, listener) {
    if (!this.listeners.has(method)) this.listeners.set(method, []);
    this.listeners.get(method).push(listener);
  }

  onError(listener) {
    this.errorListeners.push(listener);
  }

  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.close();
  }
}

function pageObserverSource() {
  return String.raw`(() => {
    const emitted = new Set();
    const critical = { health: null, workdir: null };
    const emit = (kind, detail = {}) => {
      if (emitted.has(kind)) return;
      emitted.add(kind);
      try { globalThis.__hddeMarker(JSON.stringify({ kind, detail })); } catch {}
    };
    const originalFetch = globalThis.fetch.bind(globalThis);
    globalThis.fetch = async (...args) => {
      const raw = typeof args[0] === "string" ? args[0] : args[0]?.url || "";
      const url = new URL(raw, location.href);
      try {
        const response = await originalFetch(...args);
        if (url.pathname === "/api/health") critical.health = { ok: response.ok, status: response.status };
        if (url.pathname === "/api/app/workdir") critical.workdir = { ok: response.ok, status: response.status };
        queueMicrotask(check);
        return response;
      } catch (error) {
        if (url.pathname === "/api/health") critical.health = { ok: false, error: String(error) };
        if (url.pathname === "/api/app/workdir") critical.workdir = { ok: false, error: String(error) };
        queueMicrotask(check);
        throw error;
      }
    };
    const visible = (element) => {
      if (!element) return false;
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0";
    };
    function check() {
      const shell = document.querySelector(".hdde-app-shell");
      const navigation = document.querySelector(".hdde-primary-navigation");
      const page = document.querySelector(".vmp-main-viewport");
      if (visible(shell) && visible(navigation) && visible(page)) emit("T3", { path: location.pathname });
      const control = page?.querySelector("select");
      if (visible(control) && !control.disabled) {
        const rect = control.getBoundingClientRect();
        const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
        if (top && (top === control || control.contains(top))) {
          control.focus({ preventScroll: true });
          emit("T4", { selector: ".vmp-main-viewport select", focus_verified: document.activeElement === control });
        }
      }
      const text = document.body?.innerText || "";
      const requestsReady = critical.health?.ok === true && critical.workdir?.ok === true;
      const stateReady = !text.includes("正在初始化工作目录") && !text.includes("工作目录初始化失败") && !text.includes("无法连接上传接口");
      if (requestsReady && stateReady && location.pathname === "/processing") emit("T5", { critical, path: location.pathname });
    }
    const start = () => {
      new MutationObserver(check).observe(document.documentElement, { childList: true, subtree: true, characterData: true, attributes: true });
      check();
      setInterval(check, 25);
    };
    if (document.readyState === "loading") addEventListener("DOMContentLoaded", start, { once: true }); else start();
  })();`;
}

async function findFreePort(start = 9333) {
  for (let port = start; port < start + 200; port += 1) if (!(await isPortOpen(port))) return port;
  throw new Error("No free Chrome debugging port was found.");
}

function comparablePath(value) {
  const normalized = path.resolve(value).replace(/[\\/]+$/, "");
  return process.platform === "win32" ? normalized.toLowerCase() : normalized;
}

function isStrictChildPath(parent, child) {
  const relative = path.relative(path.resolve(parent), path.resolve(child));
  return relative !== "" && relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}

function assertNoReparsePointBetween(parent, child) {
  const relative = path.relative(path.resolve(parent), path.resolve(child));
  let cursor = path.resolve(parent);
  for (const part of relative.split(path.sep).filter(Boolean)) {
    cursor = path.join(cursor, part);
    if (!existsSync(cursor)) continue;
    const stat = lstatSync(cursor);
    if (stat.isSymbolicLink()) throw new Error(`profile path contains a symbolic link or junction: ${cursor}`);
  }
}

function validateProfileDeleteTarget(registry, profileDirectory, { protectedRoots = [] } = {}) {
  if (!profileDirectory) throw new Error("profile directory is empty");
  const root = path.resolve(registry.profileRoot);
  const target = path.resolve(profileDirectory);
  const tempRoot = path.resolve(os.tmpdir());
  if (!isStrictChildPath(tempRoot, root)) throw new Error("profile root is not a dedicated child of the system temp directory");
  if (!isStrictChildPath(root, target)) throw new Error("profile directory is outside the registered profile root or equals it");
  const forbidden = [PROJECT_ROOT, os.homedir(), tempRoot, root, ...protectedRoots].map(comparablePath);
  if (forbidden.includes(comparablePath(target))) throw new Error("profile directory resolves to a protected root");
  const profile = registry.profiles.get(comparablePath(target));
  if (!profile || profile.runSessionId !== registry.runSessionId) throw new Error("profile directory is not registered for this run");
  assertNoReparsePointBetween(tempRoot, target);
  if (existsSync(root) && existsSync(target)) {
    const realRoot = realpathSync(root);
    const realTarget = realpathSync(target);
    if (!isStrictChildPath(realRoot, realTarget)) throw new Error("profile real path escapes the registered profile root");
  }
  if (!existsSync(target)) {
    if (profile.removed) return { target, profile, alreadyRemoved: true };
    throw new Error("registered profile directory is missing before cleanup");
  }
  const marker = path.join(target, PROFILE_MARKER_FILE);
  if (!existsSync(marker) || lstatSync(marker).isSymbolicLink()) throw new Error("profile marker is missing or unsafe");
  const markerPayload = JSON.parse(readFileSync(marker, "utf8"));
  if (markerPayload.runSessionId !== registry.runSessionId || markerPayload.profilePath !== target) throw new Error("profile marker does not match the registered run");
  return { target, profile, alreadyRemoved: false };
}

export function createProfileDirectory(registry, profileDirectory, profileMode, { groupId = "", runId = "" } = {}) {
  const root = path.resolve(registry.profileRoot);
  const target = path.resolve(profileDirectory);
  mkdirSync(root, { recursive: true });
  if (!isStrictChildPath(path.resolve(os.tmpdir()), root) || !isStrictChildPath(root, target)) throw new Error("unsafe profile directory location");
  assertNoReparsePointBetween(path.resolve(os.tmpdir()), root);
  mkdirSync(target, { recursive: false });
  const record = {
    path: target,
    profileMode,
    groupId,
    runId,
    runSessionId: registry.runSessionId,
    created: true,
    removed: false,
  };
  registry.profiles.set(comparablePath(target), record);
  writeFileSync(path.join(target, PROFILE_MARKER_FILE), `${JSON.stringify({
    schemaVersion: 1,
    runSessionId: registry.runSessionId,
    profilePath: target,
    profileMode,
    groupId,
    runId,
  })}\n`, "utf8");
  return record;
}

export async function safeRemoveProfileDirectory(registry, profileDirectory, {
  removeFn = (target) => rmSync(target, { recursive: true, force: true, maxRetries: 0 }),
  retries = PROFILE_DELETE_RETRIES,
  intervalMs = PROFILE_DELETE_INTERVAL_MS,
  delayFn = delay,
  protectedRoots = [],
} = {}) {
  let validation;
  try {
    validation = validateProfileDeleteTarget(registry, profileDirectory, { protectedRoots });
    if (validation.alreadyRemoved) return { ok: true, removed: true, attempts: 0 };
  } catch (error) {
    return { ok: false, removed: false, unsafe: true, attempts: 0, error };
  }
  let lastError;
  const maxAttempts = Math.max(1, Math.min(Number(retries) || 1, PROFILE_DELETE_RETRIES));
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      removeFn(validation.target);
      if (existsSync(validation.target)) throw new Error("profile directory still exists after removal");
      validation.profile.removed = true;
      return { ok: true, removed: true, attempts: attempt };
    } catch (error) {
      lastError = error;
      if (attempt < maxAttempts) await delayFn(intervalMs);
    }
  }
  return { ok: false, removed: false, unsafe: false, attempts: maxAttempts, error: lastError };
}

export function createChromeLifecycle(registry, {
  runId,
  debugPort,
  profileDir,
  profileMode,
  removeProfileOnCleanup,
} = {}) {
  const lifecycle = {
    registry,
    runId,
    process: null,
    processRecord: null,
    pid: null,
    rootPid: null,
    debugPort,
    profileDir: path.resolve(profileDir),
    profileMode,
    removeProfileOnCleanup: Boolean(removeProfileOnCleanup),
    cdpConnection: null,
    spawned: false,
    startedAt: null,
    navigationStarted: false,
    cleanupStarted: false,
    cleanupCompleted: false,
    lifecycleValidated: false,
    processExited: false,
    debugPortReleased: false,
    profileRemoved: false,
    profileStatus: "PENDING",
    terminationReason: "",
    primaryError: null,
    cleanupErrors: [],
  };
  registry.chromeLifecycles.add(lifecycle);
  if (Number.isInteger(debugPort) && debugPort > 0) registry.ports.add(debugPort);
  return lifecycle;
}

export async function startChrome(lifecycle, { spawnChrome, connectCdp } = {}) {
  const chrome = spawnChrome ? "test-chrome" : findChrome();
  const launch = spawnChrome || ((executable, args) => startProcess("chrome", executable, args, { windowsHide: false }));
  const record = launch(chrome, [
    `--remote-debugging-port=${lifecycle.debugPort}`,
    `--user-data-dir=${lifecycle.profileDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--window-position=40,40",
    "--window-size=1440,900",
    "about:blank",
  ]);
  lifecycle.processRecord = record;
  lifecycle.process = record.child;
  lifecycle.pid = record.child?.pid;
  lifecycle.rootPid = lifecycle.pid;
  lifecycle.spawned = Number.isInteger(lifecycle.rootPid) && lifecycle.rootPid > 0;
  lifecycle.startedAt = utcNow();
  if (!lifecycle.spawned) throw new Error("Chrome spawn did not provide a valid root PID");
  lifecycle.registry.processes.set(lifecycle.rootPid, record);
  if (connectCdp) {
    const injectedSession = await connectCdp(lifecycle);
    lifecycle.cdpConnection = injectedSession;
    return lifecycle;
  }
  const target = await pollUntil(async () => {
    const response = await fetchWithTimeout(`http://127.0.0.1:${lifecycle.debugPort}/json/list`);
    const targets = await response.json();
    return targets.find((item) => item.type === "page" && item.webSocketDebuggerUrl) || null;
  }, STARTUP_TIMEOUT_MS, "Chrome CDP target");
  const session = new CdpSession(target.webSocketDebuggerUrl);
  await session.connect();
  lifecycle.cdpConnection = session;
  return lifecycle;
}

async function settleWithin(promise, timeoutMs, label) {
  let timer;
  try {
    return await Promise.race([
      Promise.resolve(promise),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${label} timed out`)), timeoutMs); }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

export async function cleanupChromeLifecycle(lifecycle, {
  stopProcessFn = stopProcess,
  verifyPortReleasedFn = verifyPortReleased,
  removeProfileFn = safeRemoveProfileDirectory,
  terminationReason = "sample_complete",
} = {}) {
  if (lifecycle.cleanupCompleted) return lifecycle;
  lifecycle.cleanupStarted = true;
  lifecycle.terminationReason ||= terminationReason;
  const session = lifecycle.cdpConnection;
  if (session) {
    try {
      if (typeof session.send === "function") await settleWithin(session.send("Browser.close"), PROCESS_EXIT_TIMEOUT_MS, "CDP Browser.close");
    } catch (error) {
      recordCleanupError(lifecycle, "cdp_browser_close", error);
    }
    try {
      if (typeof session.close === "function") await settleWithin(session.close(), PROCESS_EXIT_TIMEOUT_MS, "CDP connection close");
    } catch (error) {
      recordCleanupError(lifecycle, "cdp_connection_close", error);
    }
    lifecycle.cdpConnection = null;
  }
  if (lifecycle.spawned && Number.isInteger(lifecycle.rootPid) && lifecycle.rootPid > 0 && lifecycle.processRecord?.child?.pid === lifecycle.rootPid) {
    try {
      await stopProcessFn(lifecycle.processRecord);
    } catch (error) {
      recordCleanupError(lifecycle, "chrome_process_tree", error);
    }
  }
  lifecycle.processExited = !lifecycle.processRecord?.child || lifecycle.processRecord.child.exitCode !== null || lifecycle.processRecord.child.signalCode !== null;
  if (Number.isInteger(lifecycle.debugPort) && lifecycle.debugPort > 0) {
    try {
      lifecycle.debugPortReleased = await verifyPortReleasedFn(lifecycle.debugPort);
      if (!lifecycle.debugPortReleased) throw new Error(`debug port ${lifecycle.debugPort} remains occupied; unknown processes were not terminated`);
    } catch (error) {
      lifecycle.debugPortReleased = false;
      recordCleanupError(lifecycle, "debug_port_release", error);
    }
  } else {
    lifecycle.debugPortReleased = true;
  }
  if (lifecycle.removeProfileOnCleanup) {
    try {
      const removed = await removeProfileFn(lifecycle.registry, lifecycle.profileDir);
      lifecycle.profileRemoved = removed.ok && removed.removed;
      if (!removed.ok) throw removed.error || new Error("profile cleanup failed");
    } catch (error) {
      lifecycle.profileRemoved = false;
      recordCleanupError(lifecycle, "profile_cleanup", error);
    }
  }
  lifecycle.profileStatus = lifecycle.removeProfileOnCleanup
    ? (lifecycle.profileRemoved && !existsSync(lifecycle.profileDir) ? "REMOVED" : "CLEAN_PROFILE_NOT_REMOVED")
    : "DEFERRED_TO_WARM_GROUP";
  lifecycle.cleanupCompleted = true;
  return lifecycle;
}

export function assertChromeLifecycleSafeForValidSample(lifecycle, {
  settingsSampleCheckPassed = true,
  fatalState = false,
} = {}) {
  const fail = (subcode, message) => { throw chromeLifecycleFatal(lifecycle, subcode, message); };
  if (!lifecycle?.cleanupCompleted) fail("LIFECYCLE_STATE_INCONSISTENT", "Chrome lifecycle cleanup did not complete");
  if (!lifecycle.processExited) fail("CHROME_PROCESS_NOT_EXITED", "registered Chrome root process did not exit");
  if (lifecycle.cdpConnection !== null) fail("CDP_CONNECTION_NOT_CLOSED", "Chrome CDP connection is still open");
  if (!lifecycle.debugPortReleased) fail("DEBUG_PORT_NOT_RELEASED", "Chrome debugging port was not released");
  if (lifecycle.cleanupErrors.length > 0) fail("CHROME_CLEANUP_ERRORS_PRESENT", "Chrome lifecycle cleanup reported errors");
  if (!settingsSampleCheckPassed || fatalState) fail("LIFECYCLE_STATE_INCONSISTENT", "sample settings or fatal-state gate did not pass");
  const profile = lifecycle.registry.profiles.get(comparablePath(lifecycle.profileDir));
  if (!profile) fail(lifecycle.removeProfileOnCleanup ? "CLEAN_PROFILE_NOT_REMOVED" : "WARM_PROFILE_NOT_REGISTERED", "Chrome profile is not registered");
  if (lifecycle.removeProfileOnCleanup) {
    if (!lifecycle.profileRemoved || !profile.removed || existsSync(lifecycle.profileDir)) {
      fail("CLEAN_PROFILE_NOT_REMOVED", "clean Chrome profile was not removed");
    }
    lifecycle.profileStatus = "REMOVED";
  } else {
    if (profile.removed || !existsSync(lifecycle.profileDir)) fail("WARM_PROFILE_NOT_REGISTERED", "warm Chrome profile is not available for group reuse");
    if (!profile.groupId || profile.groupId !== lifecycle.registry.currentGroupId || lifecycle.profileMode !== "warm_cache") {
      fail("WARM_PROFILE_NOT_REGISTERED", "warm Chrome profile registration does not match the current group");
    }
    lifecycle.profileStatus = "DEFERRED_TO_WARM_GROUP";
  }
  lifecycle.lifecycleValidated = true;
  return lifecycle;
}

export function validateSampleLifecycleOrAbort(registry, lifecycle, options = {}) {
  try {
    return assertChromeLifecycleSafeForValidSample(lifecycle, options);
  } catch (error) {
    throw registerFatalError(registry, error);
  }
}

export async function cleanupRegisteredResources(registry, dependencies = {}) {
  if (registry.cleanupCompleted) return registry;
  registry.cleanupStarted = true;
  registry.globalAbort = true;
  for (const lifecycle of [...registry.chromeLifecycles].reverse()) {
    try {
      await cleanupChromeLifecycle(lifecycle, { ...dependencies, terminationReason: dependencies.terminationReason || "global_abort" });
      for (const error of lifecycle.cleanupErrors) {
        if (!registry.cleanupErrors.some((item) => item.stage === `chrome:${lifecycle.runId}:${error.stage}`)) {
          registry.cleanupErrors.push({ stage: `chrome:${lifecycle.runId}:${error.stage}`, message: error.message });
        }
      }
    } catch (error) {
      recordCleanupError(registry, `chrome:${lifecycle.runId}`, error);
    }
  }
  for (const [pid, record] of [...registry.processes.entries()].reverse()) {
    if (![...registry.chromeLifecycles].some((item) => item.rootPid === pid)) {
      try {
        await (dependencies.stopProcessFn || stopProcess)(record);
      } catch (error) {
        recordCleanupError(registry, `process:${pid}`, error);
      }
    }
  }
  for (const port of registry.ports) {
    try {
      const released = await (dependencies.verifyPortReleasedFn || verifyPortReleased)(port);
      if (!released) throw new Error(`port ${port} remains occupied; unknown processes were not terminated`);
    } catch (error) {
      recordCleanupError(registry, `port:${port}`, error);
    }
  }
  for (const profile of [...registry.profiles.values()].reverse()) {
    if (profile.removed) continue;
    try {
      const removed = await (dependencies.removeProfileFn || safeRemoveProfileDirectory)(registry, profile.path);
      if (!removed.ok) throw removed.error || new Error("profile cleanup failed");
    } catch (error) {
      recordCleanupError(registry, `profile:${path.basename(profile.path)}`, error);
    }
  }
  registry.cleanupCompleted = true;
  if (registry.cleanupErrors.length > 0) {
    registerFatalError(registry, new FatalMeasurementStopError("registered resource cleanup was incomplete", {
      code: "CHROME_LIFECYCLE_CLEANUP_INCOMPLETE",
      subcode: "LIFECYCLE_STATE_INCONSISTENT",
      stage: "global_resource_cleanup",
      runId: registry.currentRunId,
    }));
  }
  return registry;
}

function sanitizeUrl(raw) {
  try {
    const url = new URL(raw);
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) return "[EXTERNAL_URL_REDACTED]";
    if (url.pathname.includes("/preview/")) return `${url.origin}${url.pathname.replace(/\/preview\/[^/?#]+/, "/preview/[REDACTED_TOKEN]")}`;
    return `${url.origin}${url.pathname}`;
  } catch {
    return "[INVALID_URL]";
  }
}

export function createMarkerTimeoutError(markers) {
  const missing = ["T3", "T4", "T5"].find((name) => markers[name] === undefined) || "T5";
  const error = new Error(`${missing} marker timed out`);
  error.code = `${missing}_TIMEOUT`;
  return error;
}

async function collectChromeStartup(frontendPort, lifecycle, nodeClock, warmCache) {
  await startChrome(lifecycle);
  const session = lifecycle.cdpConnection;
  const markers = {};
  const consoleErrors = [];
  const requests = new Map();
  const responses = [];
  const bindingEvents = [];
  let rejectMarkers;
  let markerTimeout;
  const markerPromise = new Promise((resolve, reject) => {
    rejectMarkers = (error) => {
      clearTimeout(markerTimeout);
      reject(error);
    };
    markerTimeout = setTimeout(() => rejectMarkers(createMarkerTimeoutError(markers)), STARTUP_TIMEOUT_MS);
    session.on("Runtime.bindingCalled", ({ name, payload }) => {
      if (name !== "__hddeMarker") return;
      try {
        const event = JSON.parse(payload);
        bindingEvents.push(event);
        if (["T3", "T4", "T5"].includes(event.kind) && markers[event.kind] === undefined) markers[event.kind] = nodeClock();
        if (markers.T3 !== undefined && markers.T4 !== undefined && markers.T5 !== undefined) {
          clearTimeout(markerTimeout);
          resolve();
        }
      } catch (error) {
        rejectMarkers(error);
      }
    });
  });
  session.onError((error) => rejectMarkers(error));
  session.on("Runtime.exceptionThrown", ({ exceptionDetails }) => {
    try {
      consoleErrors.push({ type: "exception", text: exceptionDetails?.text || "Runtime exception" });
    } catch (error) {
      rejectMarkers(error);
    }
  });
  session.on("Runtime.consoleAPICalled", ({ type, args }) => {
    if (type === "error") consoleErrors.push({ type: "console", text: args?.map((item) => item.value || item.description || "").join(" ") });
  });
  session.on("Network.requestWillBeSent", ({ requestId, request, timestamp }) => requests.set(requestId, { method: request.method, url: sanitizeUrl(request.url), cdp_start: timestamp }));
  session.on("Network.responseReceived", ({ requestId, response, timestamp }) => {
    const request = requests.get(requestId) || {};
    responses.push({ method: request.method || "", url: request.url || sanitizeUrl(response.url), status: response.status, mime_type: response.mimeType, cdp_duration_ms: request.cdp_start ? Number(((timestamp - request.cdp_start) * 1000).toFixed(3)) : null });
  });
  await session.send("Runtime.enable");
  await session.send("Page.enable");
  await session.send("Network.enable");
  await session.send("Runtime.addBinding", { name: "__hddeMarker" });
  await session.send("Page.addScriptToEvaluateOnNewDocument", { source: pageObserverSource() });
  const version = await session.send("Browser.getVersion");
  const initialUrl = `http://127.0.0.1:${frontendPort}/`;
  const n0 = nodeClock();
  lifecycle.navigationStarted = true;
  await session.send("Page.navigate", { url: initialUrl });
  await markerPromise;
  const finalLocation = await session.send("Runtime.evaluate", { expression: "location.href", returnByValue: true });
  const navigationTiming = await session.send("Runtime.evaluate", { expression: "JSON.stringify(performance.getEntriesByType('navigation')[0]?.toJSON?.() || {})", returnByValue: true });
  if (warmCache) {
    const origin = `http://127.0.0.1:${frontendPort}`;
    await session.send("Storage.clearDataForOrigin", { origin, storageTypes: "cookies,local_storage,indexeddb,websql,service_workers,cache_storage" });
    await session.send("Storage.clearDataForOrigin", { origin: `http://127.0.0.1:${BACKEND_PORT}`, storageTypes: "cookies,local_storage,indexeddb,websql,service_workers,cache_storage" });
  }
  return {
    lifecycle,
    markers,
    n0,
    browser_product: version.product,
    browser_user_agent: version.userAgent,
    initial_url: initialUrl,
    final_url: finalLocation.result?.value || "",
    console_errors: consoleErrors,
    network_responses: responses,
    binding_events: bindingEvents,
    navigation_timing_auxiliary: JSON.parse(navigationTiming.result?.value || "{}"),
  };
}

function processCommandForMode(mode, port) {
  if (mode === "development") {
    return { label: "vite-dev", executable: "cmd.exe", args: ["/d", "/s", "/c", `npm.cmd run dev -- --host 127.0.0.1 --port ${port} --strictPort`] };
  }
  return { label: "fixed-build-integration", executable: process.execPath, args: [TOOL_PATH, "--serve-build", "--port", String(port)] };
}

async function runStartupSample({
  mode,
  cacheType,
  runId,
  profileDirectory,
  rawDirectory,
  expectedSemanticSha,
  registry,
  settingsPath = SETTINGS_PATH,
}) {
  const frontendPort = mode === "development" ? DEV_PORT : BUILD_PORT;
  const result = {
    run_id: runId,
    mode,
    cache_type: cacheType,
    valid: false,
    lifecycleValidated: false,
    started_at_utc: utcNow(),
    ports: { backend: BACKEND_PORT, frontend: frontendPort },
    pids: {},
    timing_clock: "node:performance.now monotonic",
  };
  const sampleZero = performance.now();
  const clock = () => Number((performance.now() - sampleZero).toFixed(3));
  let backend;
  let frontend;
  let lifecycle;
  let chromeResult;
  let fatalError;
  let sampleError;
  let sampleReadyForValidation = false;
  try {
    throwIfGlobalAbort(registry);
    registry.currentRunId = runId;
    assertSettingsSemanticUnchanged(expectedSemanticSha, settingsDigest(settingsPath), { stage: "sample_start", runId });
    if (await isPortOpen(BACKEND_PORT) || await isPortOpen(frontendPort)) throw new Error("required port was already in use");
    registry.ports.add(BACKEND_PORT);
    registry.ports.add(frontendPort);
    result.T0 = clock();
    backend = startProcess("backend", PYTHON_PATH, ["main.py", "--server"]);
    result.pids.backend = backend.child.pid;
    registry.processes.set(backend.child.pid, backend);
    await waitForBackend();
    result.T1 = clock();
    const frontCommand = processCommandForMode(mode, frontendPort);
    frontend = startProcess(frontCommand.label, frontCommand.executable, frontCommand.args);
    result.pids.frontend = frontend.child.pid;
    registry.processes.set(frontend.child.pid, frontend);
    const frontendReady = await waitForFrontend(frontendPort);
    result.T2 = clock();
    result.asset_validation = await validateAssets(frontendPort, frontendReady.html);
    if (result.asset_validation.some((item) => item.status !== 200)) throw new Error("one or more frontend assets were unavailable");
    const debugPort = await findFreePort(9333);
    result.ports.chrome_debug = debugPort;
    lifecycle = createChromeLifecycle(registry, {
      runId,
      debugPort,
      profileDir: profileDirectory,
      profileMode: cacheType,
      removeProfileOnCleanup: cacheType === "clean_profile",
    });
    chromeResult = await collectChromeStartup(frontendPort, lifecycle, clock, cacheType === "warm_cache");
    result.pids.chrome = lifecycle.rootPid;
    result.N0 = chromeResult.n0;
    result.T3 = chromeResult.markers.T3;
    result.T4 = chromeResult.markers.T4;
    result.T5 = chromeResult.markers.T5;
    result.initial_url = chromeResult.initial_url;
    result.final_url = chromeResult.final_url;
    result.browser_product = chromeResult.browser_product;
    result.browser_user_agent = chromeResult.browser_user_agent;
    result.console_errors = chromeResult.console_errors;
    result.network_responses = chromeResult.network_responses;
    result.marker_events = chromeResult.binding_events;
    result.navigation_timing_auxiliary = chromeResult.navigation_timing_auxiliary;
    result.intervals_ms = {
      t0_t1: Number((result.T1 - result.T0).toFixed(3)),
      t1_t2: Number((result.T2 - result.T1).toFixed(3)),
      t2_t3: Number((result.T3 - result.T2).toFixed(3)),
      t3_t4: Number((result.T4 - result.T3).toFixed(3)),
      t4_t5: Number((result.T5 - result.T4).toFixed(3)),
      t0_t5: Number((result.T5 - result.T0).toFixed(3)),
    };
    if (result.console_errors.length) throw new Error("Chrome reported blocking console errors");
    if (!result.final_url.endsWith("/processing")) throw new Error(`unexpected default final URL: ${result.final_url}`);
    result.settings_digest = settingsDigest(settingsPath);
    assertSettingsSemanticUnchanged(expectedSemanticSha, result.settings_digest, { stage: "sample_complete", runId });
    sampleReadyForValidation = true;
  } catch (error) {
    let primaryError = error;
    try {
      result.settings_digest = settingsDigest(settingsPath);
      assertSettingsSemanticUnchanged(expectedSemanticSha, result.settings_digest, { stage: "sample_error", runId, cause: error });
    } catch (settingsError) {
      if (isFatalMeasurementError(settingsError)) primaryError = settingsError;
      else if (!result.settings_digest) primaryError = settingsError;
    }
    if (isFatalMeasurementError(primaryError)) {
      fatalError = registerFatalError(registry, primaryError);
    } else {
      sampleError = primaryError;
      result.invalid_reason = primaryError.stack || primaryError.message || String(primaryError);
    }
  } finally {
    if (lifecycle) {
      if (lifecycle.rootPid) result.pids.chrome = lifecycle.rootPid;
      lifecycle.primaryError ||= fatalError;
      try {
        await cleanupChromeLifecycle(lifecycle, { terminationReason: fatalError ? "fatal_stop" : "sample_complete" });
      } catch (error) {
        recordCleanupError(lifecycle, "lifecycle_cleanup_throw", error);
        lifecycle.cleanupCompleted = false;
      }
      result.chrome_cleanup = {
        cleanup_completed: lifecycle.cleanupCompleted,
        process_exited: lifecycle.processExited,
        cdp_connection_closed: lifecycle.cdpConnection === null,
        debug_port_released: lifecycle.debugPortReleased,
        profile_removed: lifecycle.profileRemoved,
        profile_status: lifecycle.profileStatus,
        cleanup_errors: lifecycle.cleanupErrors,
      };
    }
    for (const [label, record] of [["frontend", frontend], ["backend", backend]]) {
      try {
        await stopProcess(record);
      } catch (error) {
        recordCleanupError(registry, `${runId}:${label}_process_cleanup`, error);
      }
    }
    for (const port of [frontendPort, BACKEND_PORT, result.ports.chrome_debug].filter(Boolean)) {
      try {
        await waitForPortClosed(port);
        registry.finalPortStates.set(port, true);
      } catch (error) {
        result.port_cleanup_error = error.message;
        registry.finalPortStates.set(port, false);
        recordCleanupError(registry, `${runId}:port:${port}`, error);
      }
    }
    result.ended_at_utc = utcNow();
    result.port_cleanup = !result.port_cleanup_error;
  }

  let settingsSampleCheckPassed = false;
  try {
    result.settings_digest = settingsDigest(settingsPath);
    assertSettingsSemanticUnchanged(expectedSemanticSha, result.settings_digest, { stage: "sample_post_cleanup", runId, cause: sampleError || fatalError });
    settingsSampleCheckPassed = true;
  } catch (error) {
    if (isFatalMeasurementError(error)) fatalError = registerFatalError(registry, error);
    else if (!sampleError) sampleError = error;
  }

  if (registry.cleanupErrors.some((item) => item.stage.startsWith(`${runId}:`))) {
    fatalError = registerFatalError(registry, chromeLifecycleFatal(lifecycle, "LIFECYCLE_STATE_INCONSISTENT", "sample process or port cleanup was incomplete"));
  }
  if (lifecycle) {
    try {
      validateSampleLifecycleOrAbort(registry, lifecycle, {
        settingsSampleCheckPassed: settingsSampleCheckPassed || Boolean(fatalError),
        fatalState: false,
      });
      result.lifecycleValidated = !fatalError;
      if (fatalError) lifecycle.lifecycleValidated = false;
    } catch (error) {
      lifecycle.lifecycleValidated = false;
      result.lifecycleValidated = false;
      fatalError = registerFatalError(registry, error);
    }
  }
  if (sampleReadyForValidation && !sampleError && !fatalError && settingsSampleCheckPassed && result.lifecycleValidated) result.valid = true;

  if (registry.primaryError && isFatalMeasurementError(registry.primaryError)) {
    fatalError = registry.primaryError;
    result.fatal_stop = {
      triggered: true,
      code: fatalError.code,
      subcode: fatalError.subcode || "",
      exit_code: measurementExitCode(fatalError),
      measurement_aborted_immediately: true,
    };
  }
  try {
    if (backend) writeFileSync(path.join(rawDirectory, `${runId}_backend.log`), `${backend.stdout}\n${backend.stderr}`, "utf8");
    if (frontend) writeFileSync(path.join(rawDirectory, `${runId}_frontend.log`), `${frontend.stdout}\n${frontend.stderr}`, "utf8");
    if (lifecycle?.processRecord) writeFileSync(path.join(rawDirectory, `${runId}_chrome.log`), `${lifecycle.processRecord.stdout}\n${lifecycle.processRecord.stderr}`, "utf8");
    writeJson(path.join(rawDirectory, `${runId}.json`), result);
  } catch (error) {
    recordCleanupError(registry, `${runId}:raw_diagnostics`, error);
    fatalError = registerFatalError(registry, new FatalMeasurementStopError("raw diagnostics could not be completed safely", {
      code: "MEASUREMENT_RUN_SAFETY_GATE_FAILED",
      stage: "raw_diagnostics",
      runId,
      cause: error,
    }));
  }
  if (fatalError) throw fatalError;
  return result;
}

function nearestRank(values, percentile) {
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.max(0, Math.ceil(percentile * sorted.length) - 1)];
}

function median(values) {
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function summarizeValues(values) {
  const med = median(values);
  const deviations = values.map((value) => Math.abs(value - med));
  return {
    count: values.length,
    min: Math.min(...values),
    median: Number(med.toFixed(3)),
    max: Math.max(...values),
    p75: Number(nearestRank(values, 0.75).toFixed(3)),
    mad: Number(median(deviations).toFixed(3)),
    p90_nearest_rank: Number(nearestRank(values, 0.9).toFixed(3)),
  };
}

function summarizeGroup(samples) {
  const keys = ["t0_t1", "t1_t2", "t2_t3", "t3_t4", "t4_t5", "t0_t5"];
  return Object.fromEntries(keys.map((key) => [key, summarizeValues(samples.map((sample) => sample.intervals_ms[key]))]));
}

export async function collectValidGroup({
  mode,
  cacheType,
  validRuns,
  outputRoot,
  expectedSemanticSha,
  registry,
  prime = false,
  runSample = runStartupSample,
  settingsPath = SETTINGS_PATH,
}) {
  throwIfGlobalAbort(registry);
  const groupDirectory = path.join(outputRoot, "runs", mode, cacheType);
  mkdirSync(groupDirectory, { recursive: true });
  const groupId = `${mode}:${cacheType}`;
  registry.currentGroupId = groupId;
  const groupCleanup = { groupId, cacheType, cleanupStarted: false, cleanupCompleted: false, profileRemoved: cacheType !== "warm_cache", errors: [] };
  registry.groupCleanupStates.set(groupId, groupCleanup);
  const all = [];
  const warmProfile = cacheType === "warm_cache"
    ? path.join(registry.profileRoot, `${mode}-warm-${registry.runSessionId}`)
    : "";
  let primaryError;
  if (warmProfile) createProfileDirectory(registry, warmProfile, "APPLICATION_WARM_CACHE_START", { groupId });
  const execute = async (runId, attempt) => {
    throwIfGlobalAbort(registry);
    const profileDirectory = warmProfile || path.join(registry.profileRoot, `${mode}-clean-${String(attempt).padStart(2, "0")}-${registry.runSessionId}`);
    if (!warmProfile) createProfileDirectory(registry, profileDirectory, "APPLICATION_CLEAN_PROFILE_START", { groupId, runId });
    try {
      return await runSample({ mode, cacheType, runId, profileDirectory, rawDirectory: groupDirectory, expectedSemanticSha, registry, settingsPath });
    } finally {
      if (!warmProfile) {
        const removed = await safeRemoveProfileDirectory(registry, profileDirectory);
        if (!removed.ok) {
          const cleanupError = removed.error || new Error("clean profile cleanup failed");
          recordCleanupError(registry, `profile:${runId}`, cleanupError);
          const fatal = chromeLifecycleFatal(null, "CLEAN_PROFILE_NOT_REMOVED", "clean profile cleanup failed");
          fatal.runId = runId;
          throw registerFatalError(registry, fatal);
        }
      }
    }
  };
  try {
    if (prime) {
      const primeResult = await execute(`${mode}-${cacheType}-prime`, 0);
      primeResult.excluded_from_statistics = true;
      all.push(primeResult);
      if (!primeResult.valid) throw new Error(`${mode} warm-cache prime failed: ${primeResult.invalid_reason}`);
    }
    let validCount = 0;
    let attempt = 0;
    while (validCount < validRuns && attempt < validRuns + 4) {
      throwIfGlobalAbort(registry);
      attempt += 1;
      const runId = `${mode}-${cacheType}-${String(attempt).padStart(2, "0")}`;
      const sample = await execute(runId, attempt);
      all.push(sample);
      if (sample.valid) validCount += 1;
    }
    if (validCount < validRuns) throw new Error(`${mode}/${cacheType} produced only ${validCount}/${validRuns} valid samples`);
  } catch (error) {
    primaryError = error;
    if (isFatalMeasurementError(error)) {
      registry.primaryError ||= error;
      registry.globalAbort = true;
    }
    throw error;
  } finally {
    groupCleanup.cleanupStarted = true;
    if (warmProfile) {
      const removed = await safeRemoveProfileDirectory(registry, warmProfile);
      if (!removed.ok) {
        const cleanupError = removed.error || new Error("warm profile cleanup failed");
        recordCleanupError(registry, `profile:${groupId}`, cleanupError);
        groupCleanup.errors.push(cleanupError.message);
        const fatal = chromeLifecycleFatal(null, "WARM_PROFILE_NOT_REMOVED", "warm group profile cleanup failed");
        fatal.runId = groupId;
        const preserved = registerFatalError(registry, fatal);
        if (!primaryError) throw preserved;
      } else {
        groupCleanup.profileRemoved = true;
      }
    }
    groupCleanup.cleanupCompleted = groupCleanup.errors.length === 0;
  }
  return all;
}

export async function runGroupSequence(groups, { registry, runGroup = collectValidGroup } = {}) {
  const results = [];
  for (const group of groups) {
    throwIfGlobalAbort(registry);
    results.push(...await runGroup({ ...group, registry }));
  }
  return results;
}

export async function finalizeRegisteredResourcesForSuccess(registry, {
  stopProcessFn = stopProcess,
  verifyPortReleasedFn = verifyPortReleased,
} = {}) {
  registry.cleanupStarted = true;
  for (const lifecycle of registry.chromeLifecycles) {
    if (!lifecycle.cleanupCompleted) recordCleanupError(registry, `chrome:${lifecycle.runId}:cleanup`, new Error("lifecycle cleanup did not complete"));
    if (!lifecycle.processExited) recordCleanupError(registry, `chrome:${lifecycle.runId}:process`, new Error("registered Chrome process did not exit"));
    if (lifecycle.cdpConnection !== null) recordCleanupError(registry, `chrome:${lifecycle.runId}:cdp`, new Error("CDP connection is still open"));
    if (!lifecycle.debugPortReleased) recordCleanupError(registry, `chrome:${lifecycle.runId}:port`, new Error("debug port was not released"));
    for (const error of lifecycle.cleanupErrors) recordCleanupError(registry, `chrome:${lifecycle.runId}:${error.stage}`, new Error(error.message));
  }
  for (const [pid, record] of registry.processes) {
    if (record?.child && record.child.exitCode === null && record.child.signalCode === null) {
      try { await stopProcessFn(record); } catch (error) { recordCleanupError(registry, `process:${pid}`, error); }
    }
    if (record?.child && record.child.exitCode === null && record.child.signalCode === null) {
      recordCleanupError(registry, `process:${pid}:exit`, new Error("registered process is still running"));
    }
  }
  for (const port of registry.ports) {
    try {
      const released = await verifyPortReleasedFn(port);
      registry.finalPortStates.set(port, released);
      if (!released) throw new Error(`port ${port} remains occupied; unknown processes were not terminated`);
    } catch (error) {
      registry.finalPortStates.set(port, false);
      recordCleanupError(registry, `port:${port}`, error);
    }
  }
  for (const profile of registry.profiles.values()) {
    if (!profile.removed || existsSync(profile.path)) recordCleanupError(registry, `profile:${path.basename(profile.path)}`, new Error("registered profile remains after group cleanup"));
  }
  for (const state of registry.groupCleanupStates.values()) {
    if (!state.cleanupCompleted || (state.cacheType === "warm_cache" && !state.profileRemoved)) {
      recordCleanupError(registry, `group:${state.groupId}`, new Error("group cleanup is incomplete"));
    }
  }
  registry.cleanupCompleted = true;
  if (registry.cleanupErrors.length > 0 || registry.pendingCleanupTasks.size > 0) {
    throw registerFatalError(registry, new FatalMeasurementStopError("final resource cleanup verification failed", {
      code: "CHROME_LIFECYCLE_CLEANUP_INCOMPLETE",
      subcode: "LIFECYCLE_STATE_INCONSISTENT",
      stage: "final_resource_cleanup",
      runId: registry.currentRunId,
    }));
  }
  registry.resourceSafetyValidated = true;
  return registry;
}

function finalSettingsFatal(expectedSemanticSha, digest, subcode = "", cause) {
  return new FatalMeasurementStopError("settings/settings.json changed after final cleanup", {
    code: "SETTINGS_SEMANTIC_SHA_CHANGED_AFTER_FINAL_CLEANUP",
    subcode,
    stage: "FINAL_POST_CLEANUP_SETTINGS_CHECK",
    expectedSemanticSha,
    actualSemanticSha: digest?.semantic_sha256 || "",
    cleanupRequired: false,
    cause,
  });
}

export async function runFinalPostCleanupSettingsCheck({
  registry,
  expectedSemanticSha,
  settingsPath = SETTINGS_PATH,
  quiescenceMs = FINAL_SETTINGS_QUIESCENCE_MS,
  readIntervalMs = FINAL_SETTINGS_READ_INTERVAL_MS,
  delayFn = delay,
  readDigestFn = settingsDigest,
} = {}) {
  const check = {
    stage: "FINAL_POST_CLEANUP_SETTINGS_CHECK",
    afterAllCleanup: registry.cleanupCompleted && registry.resourceSafetyValidated,
    stable: false,
    semanticAssertionPassed: false,
    first: null,
    second: null,
  };
  registry.finalSettingsCheck = check;
  if (!check.afterAllCleanup) {
    throw registerFatalError(registry, new FatalMeasurementStopError("final settings check was reached before resource cleanup completed", {
      code: "MEASUREMENT_RUN_SAFETY_GATE_FAILED",
      stage: check.stage,
    }));
  }
  try {
    await delayFn(quiescenceMs);
    check.first = readDigestFn(settingsPath);
    await delayFn(readIntervalMs);
    check.second = readDigestFn(settingsPath);
    check.stable = check.first.byte_sha256 === check.second.byte_sha256
      && check.first.semantic_sha256 === check.second.semantic_sha256
      && check.first.size_bytes === check.second.size_bytes;
    if (!check.stable) throw finalSettingsFatal(expectedSemanticSha, check.second, "FINAL_SETTINGS_NOT_QUIESCENT");
    try {
      assertSettingsSemanticUnchanged(expectedSemanticSha, check.second, { stage: check.stage });
    } catch (error) {
      throw finalSettingsFatal(expectedSemanticSha, check.second, "", error);
    }
    check.semanticAssertionPassed = true;
    return check;
  } catch (error) {
    const fatal = isFatalMeasurementError(error) ? error : finalSettingsFatal(expectedSemanticSha, check.second, "", error);
    throw registerFatalError(registry, fatal);
  }
}

export function assertMeasurementRunSafeToSummarize({ registry, samples = [], finalSettingsCheck = registry.finalSettingsCheck } = {}) {
  const fail = (message) => {
    throw registerFatalError(registry, new FatalMeasurementStopError(message, {
      code: "MEASUREMENT_RUN_SAFETY_GATE_FAILED",
      stage: "measurement_summary_gate",
      runId: registry.currentRunId,
    }));
  };
  if (registry.globalAbort) fail("measurement registry is globally aborted");
  if (registry.primaryError) fail("measurement registry has a primary error");
  if (registry.secondaryFatalErrors.length > 0) fail("measurement registry has secondary fatal errors");
  if (registry.cleanupErrors.length > 0) fail("measurement registry has cleanup errors");
  if (!registry.cleanupCompleted || !registry.resourceSafetyValidated) fail("final resource cleanup has not been validated");
  if (registry.pendingCleanupTasks.size > 0) fail("cleanup tasks are still pending");
  if (!finalSettingsCheck?.afterAllCleanup || !finalSettingsCheck.stable || !finalSettingsCheck.semanticAssertionPassed) fail("final post-cleanup settings check did not pass");
  if (samples.some((sample) => sample.valid && sample.lifecycleValidated !== true)) fail("a valid sample lacks lifecycle validation");
  if ([...registry.chromeLifecycles].some((lifecycle) => !lifecycle.cleanupCompleted || lifecycle.cleanupErrors.length > 0 || !lifecycle.processExited || lifecycle.cdpConnection !== null || !lifecycle.debugPortReleased)) {
    fail("one or more Chrome lifecycles are not safely closed");
  }
  if ([...registry.profiles.values()].some((profile) => !profile.removed || existsSync(profile.path))) fail("one or more registered profiles remain");
  if ([...registry.groupCleanupStates.values()].some((state) => !state.cleanupCompleted || (state.cacheType === "warm_cache" && !state.profileRemoved))) fail("one or more group cleanups are incomplete");
  if ([...registry.processes.values()].some((record) => record?.child && record.child.exitCode === null && record.child.signalCode === null)) fail("one or more registered processes remain active");
  if ([...registry.ports].some((port) => registry.finalPortStates.get(port) !== true)) fail("one or more registered ports were not finally verified as released");
  registry.runSafetyGatePassed = true;
  return true;
}

async function validatePreview(output) {
  const result = { tested_at_utc: utcNow(), mode: "VITE_PREVIEW_VALIDATION", preview_port: BUILD_PORT };
  let backend;
  let preview;
  try {
    backend = startProcess("backend", PYTHON_PATH, ["main.py", "--server"]);
    await waitForBackend();
    preview = startProcess("vite-preview", "cmd.exe", ["/d", "/s", "/c", `npm.cmd run preview -- --host 127.0.0.1 --port ${BUILD_PORT} --strictPort`]);
    const root = await waitForFrontend(BUILD_PORT);
    const deep = await fetchWithTimeout(`http://127.0.0.1:${BUILD_PORT}/processing`, {}, 5_000);
    const health = await fetchWithTimeout(`http://127.0.0.1:${BUILD_PORT}/api/health`, {}, 5_000);
    const workdir = await fetchWithTimeout(`http://127.0.0.1:${BUILD_PORT}/api/app/workdir`, {}, 5_000);
    const healthType = health.headers.get("content-type") || "";
    const workdirType = workdir.headers.get("content-type") || "";
    result.root_html = Boolean(root.html);
    result.deep_route_status = deep.status;
    result.deep_route_content_type = deep.headers.get("content-type") || "";
    result.same_origin_health_status = health.status;
    result.same_origin_health_content_type = healthType;
    result.same_origin_workdir_status = workdir.status;
    result.same_origin_workdir_content_type = workdirType;
    result.preview_api_proxy = health.status === 200 && workdir.status === 200 && healthType.includes("application/json") && workdirType.includes("application/json");
    result.selected_build_mode = result.preview_api_proxy ? "VITE_BUILD_PREVIEW_INTEGRATED" : "FIXED_BUILD_INTEGRATION_HARNESS";
  } finally {
    await stopProcess(preview);
    await stopProcess(backend);
    await waitForPortClosed(BUILD_PORT);
    await waitForPortClosed(BACKEND_PORT);
    result.settings_digest = settingsDigest();
    writeJson(output, result);
  }
  return result;
}

async function runBaseline(outputRoot, validRuns, registry) {
  mkdirSync(outputRoot, { recursive: true });
  const initialSettings = settingsDigest();
  const buildManifest = hashFiles(DIST_ROOT);
  const metadata = {
    schema_version: "hdde.stage5.startup-baseline.raw.v1",
    created_at_utc: utcNow(),
    project_version: PRODUCT_VERSION,
    build_mode: "FIXED_BUILD_INTEGRATION_HARNESS",
    build_manifest: buildManifest,
    build_manifest_sha256: sha256Buffer(Buffer.from(JSON.stringify(buildManifest), "utf8")),
    timing_clock: "one Node process performance.now monotonic clock per sample",
    cold_definition: "APPLICATION_CLEAN_PROFILE_START",
    warm_definition: "APPLICATION_WARM_CACHE_START",
    os_cache_claimed_cold: false,
    settings_before: initialSettings,
  };
  const descriptors = ["development", "fixed_build"].flatMap((mode) => [
    { mode, cacheType: "clean_profile", validRuns, outputRoot, expectedSemanticSha: initialSettings.semantic_sha256 },
    { mode, cacheType: "warm_cache", validRuns, outputRoot, expectedSemanticSha: initialSettings.semantic_sha256, prime: true },
  ]);
  const groups = await runGroupSequence(descriptors, { registry });
  await finalizeRegisteredResourcesForSuccess(registry);
  const finalSettingsCheck = await runFinalPostCleanupSettingsCheck({
    registry,
    expectedSemanticSha: initialSettings.semantic_sha256,
  });
  metadata.settings_after = finalSettingsCheck.second;
  metadata.final_post_cleanup_settings_check = finalSettingsCheck;
  metadata.samples = groups;
  const valid = groups.filter((sample) => sample.valid && !sample.excluded_from_statistics);
  const summary = {};
  for (const mode of ["development", "fixed_build"]) {
    for (const cacheType of ["clean_profile", "warm_cache"]) {
      const key = `${mode}_${cacheType}`;
      summary[key] = summarizeGroup(valid.filter((sample) => sample.mode === mode && sample.cache_type === cacheType));
    }
  }
  assertMeasurementRunSafeToSummarize({ registry, samples: groups, finalSettingsCheck });
  writeJson(path.join(outputRoot, "startup_baseline_raw.json"), metadata);
  writeJson(path.join(outputRoot, "startup_baseline_summary.json"), { schema_version: "hdde.stage5.startup-baseline.summary.v1", groups: summary });
  return { metadata, summary };
}

async function main(registry) {
  const args = parseArgs(process.argv.slice(2));
  if (args.command === "--serve-build") {
    serveBuild(args.port);
    return;
  }
  if (args.command === "--settings-digest") {
    process.stdout.write(`${JSON.stringify(settingsDigest(), null, 2)}\n`);
    return;
  }
  const outputRoot = args.output || path.join(os.tmpdir(), `hdde_stage5_command4_runs_${Date.now()}`);
  if (args.command === "--validate-preview") {
    const result = await validatePreview(path.join(outputRoot, "preview_validation.json"));
    process.stdout.write(`${JSON.stringify({ output_root: outputRoot, result }, null, 2)}\n`);
    return;
  }
  if (args.command === "--baseline") {
    const result = await runBaseline(outputRoot, args.runs, registry);
    process.stdout.write(`${JSON.stringify({ output_root: outputRoot, summary: result.summary }, null, 2)}\n`);
    return;
  }
  process.stdout.write("Usage: node tools/diagnostics/stage5_startup_baseline.mjs --settings-digest | --validate-preview --output <dir> | --baseline --output <dir> [--runs 5] | --serve-build [--port 4173]\n");
}

function isDirectExecution() {
  if (!process.argv[1]) return false;
  return pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;
}

if (isDirectExecution()) {
  const registry = createResourceRegistry();
  const terminate = async (exitCode) => {
    registry.primaryError ||= new FatalMeasurementStopError("Measurement interrupted by a termination signal.", {
      code: "MEASUREMENT_INTERRUPTED",
      stage: "signal",
    });
    await cleanupRegisteredResources(registry, { terminationReason: "termination_signal" });
    await cleanupAll();
    process.exit(exitCode);
  };
  process.once("SIGINT", () => { void terminate(130); });
  process.once("SIGTERM", () => { void terminate(143); });
  main(registry).catch(async (error) => {
    registry.primaryError ||= error;
    registry.globalAbort = true;
    await cleanupRegisteredResources(registry, { terminationReason: "top_level_error" });
    await cleanupAll();
    if (isFatalMeasurementError(error)) {
      process.stderr.write(`${JSON.stringify({
        FATAL_STOP_TRIGGERED: "YES",
        FATAL_STOP_CODE: error.code,
        MEASUREMENT_ABORTED_IMMEDIATELY: "YES",
        ADDITIONAL_SAMPLE_STARTED_AFTER_FATAL_STOP: "NO",
        LATER_GROUP_STARTED_AFTER_FATAL_STOP: "NO",
        FATAL_EXIT_CODE: measurementExitCode(error),
        primaryError: { name: error.name, code: error.code, stage: error.stage, runId: error.runId },
        cleanupErrors: registry.cleanupErrors,
        secondaryFatalErrors: registry.secondaryFatalErrors.map((item) => ({ name: item.name, code: item.code, subcode: item.subcode, stage: item.stage, runId: item.runId })),
      }, null, 2)}\n`);
      process.exitCode = measurementExitCode(error);
      return;
    }
    process.stderr.write(`${error.stack || error.message || error}\n`);
    process.exitCode = measurementExitCode(error);
  });
}
