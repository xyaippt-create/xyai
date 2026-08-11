import test, { after } from "node:test";
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  FATAL_EXIT_CODE,
  CHROME_LIFECYCLE_FATAL_EXIT_CODE,
  FatalMeasurementStopError,
  assertChromeLifecycleSafeForValidSample,
  assertMeasurementRunSafeToSummarize,
  assertSettingsSemanticUnchanged,
  cleanupChromeLifecycle,
  cleanupRegisteredResources,
  collectValidGroup,
  createChromeLifecycle,
  createMarkerTimeoutError,
  createProfileDirectory,
  createResourceRegistry,
  isFatalMeasurementError,
  measurementExitCode,
  runFinalPostCleanupSettingsCheck,
  runGroupSequence,
  safeRemoveProfileDirectory,
  settingsDigest,
  startChrome,
  validateSampleLifecycleOrAbort,
} from "../../tools/diagnostics/stage5_startup_baseline.mjs";

const TEST_FILE = fileURLToPath(import.meta.url);
const PROJECT_ROOT = path.resolve(path.dirname(TEST_FILE), "../..");
const TOOL_PATH = path.join(PROJECT_ROOT, "tools", "diagnostics", "stage5_startup_baseline.mjs");
const REAL_SETTINGS = path.join(PROJECT_ROOT, "settings", "settings.json");
const sandboxes = [];
const testChildren = new Set();

function sha256(file) {
  return createHash("sha256").update(readFileSync(file)).digest("hex");
}

function sandbox() {
  const value = mkdtempSync(path.join(os.tmpdir(), "hdde-stage5-tool-test-"));
  sandboxes.push(value);
  return value;
}

function registryFixture() {
  const root = sandbox();
  return {
    root,
    registry: createResourceRegistry({ profileRoot: path.join(root, "profiles") }),
  };
}

function spawnNodeSleeper() {
  const child = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {
    windowsHide: true,
    stdio: ["ignore", "ignore", "ignore"],
  });
  testChildren.add(child);
  child.once("exit", () => testChildren.delete(child));
  return { label: "test-chrome", child, stdout: "", stderr: "" };
}

async function waitForExit(child, timeoutMs = 3000) {
  if (child.exitCode !== null || child.signalCode !== null) return true;
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), timeoutMs);
    child.once("exit", () => {
      clearTimeout(timer);
      resolve(true);
    });
  });
}

async function terminateTestRecord(record) {
  assert.ok(Number.isInteger(record.child.pid) && record.child.pid > 0);
  if (record.child.exitCode === null && record.child.signalCode === null) record.child.kill();
  assert.equal(await waitForExit(record.child), true);
}

async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const port = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return port;
}

function markerPath(profile) {
  return path.join(profile, ".hdde-stage5-profile.json");
}

after(() => {
  for (const child of testChildren) if (child.exitCode === null && child.signalCode === null) child.kill();
  for (const target of sandboxes.reverse()) rmSync(target, { recursive: true, force: true });
});

test("module import is side-effect free and leaves real settings unchanged", () => {
  const before = sha256(REAL_SETTINGS);
  const imported = spawnSync(process.execPath, [
    "--input-type=module",
    "--eval",
    `await import(${JSON.stringify(pathToFileURL(TOOL_PATH).href)});`,
  ], { cwd: PROJECT_ROOT, timeout: 4000, encoding: "utf8", windowsHide: true });
  assert.equal(imported.status, 0, imported.stderr);
  assert.equal(imported.signal, null);
  assert.equal(sha256(REAL_SETTINGS), before);
});

test("fatal settings change propagates globally and blocks later samples and groups", async () => {
  const { root, registry } = registryFixture();
  const settingsPath = path.join(root, "settings.json");
  writeFileSync(settingsPath, '{"value":1}\n', "utf8");
  const expected = settingsDigest(settingsPath).semantic_sha256;
  let sampleStarts = 0;
  let laterGroupStarts = 0;
  const fatalSample = async ({ runId }) => {
    sampleStarts += 1;
    writeFileSync(settingsPath, '{"value":2}\n', "utf8");
    return assertSettingsSemanticUnchanged(expected, settingsDigest(settingsPath), { runId, stage: "test" });
  };
  const groups = [{ id: "fatal" }, { id: "later" }];
  let fatal;
  try {
    await runGroupSequence(groups, {
      registry,
      runGroup: async ({ id }) => {
        if (id === "later") {
          laterGroupStarts += 1;
          return [];
        }
        return collectValidGroup({
          mode: "development",
          cacheType: "clean_profile",
          validRuns: 2,
          outputRoot: root,
          expectedSemanticSha: expected,
          registry,
          runSample: fatalSample,
          settingsPath,
        });
      },
    });
    assert.fail("fatal group sequence unexpectedly completed");
  } catch (error) {
    fatal = error;
  }
  assert.equal(fatal.code, "SETTINGS_SEMANTIC_SHA_CHANGED");
  assert.equal(isFatalMeasurementError(fatal), true);
  await cleanupRegisteredResources(registry, { verifyPortReleasedFn: async () => true });
  assert.equal(sampleStarts, 1);
  assert.equal(laterGroupStarts, 0);
  assert.equal(registry.globalAbort, true);
  assert.equal(registry.primaryError.code, "SETTINGS_SEMANTIC_SHA_CHANGED");
  assert.equal(FATAL_EXIT_CODE, 2);
  assert.equal(measurementExitCode(fatal), 2);
  assert.equal(registry.cleanupCompleted, true);
});

test("ordinary invalid samples retain bounded retry behavior", async () => {
  const { root, registry } = registryFixture();
  let attempts = 0;
  const rows = await collectValidGroup({
    mode: "development",
    cacheType: "clean_profile",
    validRuns: 1,
    outputRoot: root,
    expectedSemanticSha: "test",
    registry,
    runSample: async () => {
      attempts += 1;
      return attempts === 1 ? { valid: false, invalid_reason: "ordinary" } : { valid: true };
    },
  });
  assert.equal(attempts, 2);
  assert.equal(rows.length, 2);
  assert.equal(registry.globalAbort, false);
});

test("Chrome PID is captured before an injected CDP failure and then safely cleaned", async () => {
  const { registry } = registryFixture();
  const profile = path.join(registry.profileRoot, "cdp-failure");
  createProfileDirectory(registry, profile, "APPLICATION_CLEAN_PROFILE_START");
  const lifecycle = createChromeLifecycle(registry, {
    runId: "cdp-failure",
    debugPort: await freePort(),
    profileDir: profile,
    profileMode: "clean_profile",
    removeProfileOnCleanup: true,
  });
  let pidSeenBeforeCdp = false;
  await assert.rejects(startChrome(lifecycle, {
    spawnChrome: () => spawnNodeSleeper(),
    connectCdp: async (current) => {
      pidSeenBeforeCdp = Number.isInteger(current.rootPid) && current.rootPid > 0;
      const error = new Error("CDP_CONNECT_FAILED");
      error.code = "CDP_CONNECT_FAILED";
      throw error;
    },
  }), /CDP_CONNECT_FAILED/);
  lifecycle.primaryError = new Error("CDP_CONNECT_FAILED");
  await cleanupChromeLifecycle(lifecycle, { stopProcessFn: terminateTestRecord });
  assert.equal(pidSeenBeforeCdp, true);
  assert.equal(await waitForExit(lifecycle.process), true);
  assert.equal(lifecycle.cleanupCompleted, true);
  assert.equal(lifecycle.debugPortReleased, true);
  assert.equal(lifecycle.profileRemoved, true);
  assert.equal(existsSync(profile), false);
});

for (const [name, markers] of [
  ["T3", {}],
  ["T4", { T3: 1 }],
  ["T5", { T3: 1, T4: 2 }],
]) {
  test(`${name} timeout preserves the primary error and closes CDP, process, port, and profile`, async () => {
    const { registry } = registryFixture();
    const profile = path.join(registry.profileRoot, `${name.toLowerCase()}-timeout`);
    createProfileDirectory(registry, profile, "APPLICATION_CLEAN_PROFILE_START");
    const lifecycle = createChromeLifecycle(registry, {
      runId: `${name}-timeout`,
      debugPort: await freePort(),
      profileDir: profile,
      profileMode: "clean_profile",
      removeProfileOnCleanup: true,
    });
    const record = spawnNodeSleeper();
    lifecycle.processRecord = record;
    lifecycle.process = record.child;
    lifecycle.pid = record.child.pid;
    lifecycle.rootPid = record.child.pid;
    lifecycle.spawned = true;
    let cdpClosed = false;
    lifecycle.cdpConnection = {
      send: async () => ({}),
      close: () => { cdpClosed = true; },
    };
    lifecycle.primaryError = createMarkerTimeoutError(markers);
    await cleanupChromeLifecycle(lifecycle, { terminationReason: `${name}_TIMEOUT`, stopProcessFn: terminateTestRecord });
    assert.equal(lifecycle.primaryError.code, `${name}_TIMEOUT`);
    assert.equal(cdpClosed, true);
    assert.equal(await waitForExit(record.child), true);
    assert.equal(lifecycle.debugPortReleased, true);
    assert.equal(lifecycle.profileRemoved, true);
    assert.equal(existsSync(profile), false);
  });
}

test("clean profile is removed normally and cleanup is idempotent", async () => {
  const { registry } = registryFixture();
  const profile = path.join(registry.profileRoot, "clean-normal");
  createProfileDirectory(registry, profile, "APPLICATION_CLEAN_PROFILE_START");
  const first = await safeRemoveProfileDirectory(registry, profile);
  const second = await safeRemoveProfileDirectory(registry, profile);
  assert.equal(first.ok, true);
  assert.equal(second.ok, true);
  assert.equal(second.attempts, 0);
  assert.equal(existsSync(profile), false);
});

test("warm profiles persist within a group, separate modes, and clean on normal or fatal exit", async () => {
  const { root, registry } = registryFixture();
  const seen = [];
  for (const mode of ["development", "fixed_build"]) {
    const rows = await collectValidGroup({
      mode,
      cacheType: "warm_cache",
      validRuns: 2,
      outputRoot: root,
      expectedSemanticSha: "test",
      registry,
      prime: true,
      runSample: async ({ profileDirectory }) => {
        assert.equal(existsSync(profileDirectory), true);
        seen.push(profileDirectory);
        return { valid: true };
      },
    });
    assert.equal(rows.length, 3);
    assert.equal(existsSync(seen.at(-1)), false);
  }
  assert.notEqual(seen[0], seen[3]);

  const fatalProfilePaths = [];
  await assert.rejects(collectValidGroup({
    mode: "fatal-mode",
    cacheType: "warm_cache",
    validRuns: 1,
    outputRoot: root,
    expectedSemanticSha: "test",
    registry: createResourceRegistry({ profileRoot: path.join(root, "fatal-profiles") }),
    runSample: async ({ profileDirectory }) => {
      fatalProfilePaths.push(profileDirectory);
      throw new FatalMeasurementStopError("fatal", { code: "SETTINGS_SEMANTIC_SHA_CHANGED" });
    },
  }), (error) => error.code === "SETTINGS_SEMANTIC_SHA_CHANGED");
  assert.equal(existsSync(fatalProfilePaths[0]), false);
});

test("unsafe profile deletion guard rejects empty, root, outside, missing marker, wrong marker, and protected targets", async () => {
  const { root, registry } = registryFixture();
  assert.equal((await safeRemoveProfileDirectory(registry, "")).unsafe, true);
  assert.equal((await safeRemoveProfileDirectory(registry, registry.profileRoot)).unsafe, true);
  assert.equal((await safeRemoveProfileDirectory(registry, path.join(root, "outside"))).unsafe, true);

  const missingMarker = path.join(registry.profileRoot, "missing-marker");
  createProfileDirectory(registry, missingMarker, "APPLICATION_CLEAN_PROFILE_START");
  rmSync(markerPath(missingMarker));
  assert.equal((await safeRemoveProfileDirectory(registry, missingMarker)).unsafe, true);

  const wrongMarker = path.join(registry.profileRoot, "wrong-marker");
  createProfileDirectory(registry, wrongMarker, "APPLICATION_CLEAN_PROFILE_START");
  writeFileSync(markerPath(wrongMarker), JSON.stringify({ runSessionId: "wrong", profilePath: wrongMarker }), "utf8");
  assert.equal((await safeRemoveProfileDirectory(registry, wrongMarker)).unsafe, true);

  const protectedTarget = path.join(registry.profileRoot, "protected-target");
  createProfileDirectory(registry, protectedTarget, "APPLICATION_CLEAN_PROFILE_START");
  assert.equal((await safeRemoveProfileDirectory(registry, protectedTarget, { protectedRoots: [protectedTarget] })).unsafe, true);
});

test("symlink or junction escape is rejected without deleting its destination", async () => {
  const { root, registry } = registryFixture();
  const target = path.join(registry.profileRoot, "escape-link");
  const outside = path.join(root, "outside-destination");
  mkdirSync(outside, { recursive: true });
  writeFileSync(path.join(outside, "keep.txt"), "keep", "utf8");
  createProfileDirectory(registry, target, "APPLICATION_CLEAN_PROFILE_START");
  rmSync(target, { recursive: true, force: true });
  symlinkSync(outside, target, process.platform === "win32" ? "junction" : "dir");
  const removed = await safeRemoveProfileDirectory(registry, target);
  assert.equal(removed.ok, false);
  assert.equal(removed.unsafe, true);
  assert.equal(existsSync(path.join(outside, "keep.txt")), true);
});

test("profile deletion retry is bounded for success and terminal failure", async () => {
  const { registry } = registryFixture();
  const successProfile = path.join(registry.profileRoot, "retry-success");
  createProfileDirectory(registry, successProfile, "APPLICATION_CLEAN_PROFILE_START");
  let calls = 0;
  const succeeded = await safeRemoveProfileDirectory(registry, successProfile, {
    retries: 4,
    intervalMs: 0,
    delayFn: async () => {},
    removeFn: (target) => {
      calls += 1;
      if (calls < 3) throw new Error("locked");
      rmSync(target, { recursive: true, force: true });
    },
  });
  assert.equal(succeeded.ok, true);
  assert.equal(succeeded.attempts, 3);

  const failureProfile = path.join(registry.profileRoot, "retry-failure");
  createProfileDirectory(registry, failureProfile, "APPLICATION_CLEAN_PROFILE_START");
  calls = 0;
  const failed = await safeRemoveProfileDirectory(registry, failureProfile, {
    retries: 3,
    intervalMs: 0,
    delayFn: async () => {},
    removeFn: () => { calls += 1; throw new Error("locked"); },
  });
  assert.equal(failed.ok, false);
  assert.equal(failed.attempts, 3);
  assert.equal(calls, 3);
  assert.equal(existsSync(failureProfile), true);
});

test("registered cleanup is idempotent and leaves zero profile resources", async () => {
  const { registry } = registryFixture();
  const profile = path.join(registry.profileRoot, "idempotent");
  createProfileDirectory(registry, profile, "APPLICATION_CLEAN_PROFILE_START");
  const lifecycle = createChromeLifecycle(registry, {
    runId: "idempotent",
    debugPort: await freePort(),
    profileDir: profile,
    profileMode: "clean_profile",
    removeProfileOnCleanup: true,
  });
  await cleanupRegisteredResources(registry, { verifyPortReleasedFn: async () => true });
  const firstErrors = JSON.stringify(registry.cleanupErrors);
  await cleanupRegisteredResources(registry, { verifyPortReleasedFn: async () => { throw new Error("must not rerun"); } });
  assert.equal(lifecycle.cleanupCompleted, true);
  assert.equal(existsSync(profile), false);
  assert.equal(JSON.stringify(registry.cleanupErrors), firstErrors);
  assert.equal([...registry.profiles.values()].filter((item) => !item.removed).length, 0);
});

test("cleanup errors never replace the original fatal settings error", async () => {
  const { registry } = registryFixture();
  const profile = path.join(registry.profileRoot, "primary-error");
  createProfileDirectory(registry, profile, "APPLICATION_CLEAN_PROFILE_START");
  const primary = new FatalMeasurementStopError("settings changed", { code: "SETTINGS_SEMANTIC_SHA_CHANGED" });
  registry.primaryError = primary;
  const lifecycle = createChromeLifecycle(registry, {
    runId: "primary-error",
    debugPort: await freePort(),
    profileDir: profile,
    profileMode: "clean_profile",
    removeProfileOnCleanup: true,
  });
  const record = spawnNodeSleeper();
  lifecycle.processRecord = record;
  lifecycle.process = record.child;
  lifecycle.pid = record.child.pid;
  lifecycle.rootPid = record.child.pid;
  lifecycle.spawned = true;
  lifecycle.cdpConnection = { send: async () => { throw new Error("cdp close failed"); }, close: () => { throw new Error("socket close failed"); } };
  await cleanupRegisteredResources(registry, {
    stopProcessFn: async (item) => {
      item.child.kill();
      await waitForExit(item.child);
      throw new Error("process cleanup reported failure");
    },
    verifyPortReleasedFn: async () => false,
    removeProfileFn: async () => ({ ok: false, removed: false, error: new Error("profile cleanup failed") }),
  });
  assert.equal(registry.primaryError, primary);
  assert.equal(registry.primaryError.code, "SETTINGS_SEMANTIC_SHA_CHANGED");
  assert.ok(registry.cleanupErrors.length >= 3);
});

test("unknown debug-port owner is protected after the recorded root process exits", async () => {
  const { registry } = registryFixture();
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const port = server.address().port;
  const profile = path.join(registry.profileRoot, "unknown-owner");
  createProfileDirectory(registry, profile, "APPLICATION_CLEAN_PROFILE_START");
  const lifecycle = createChromeLifecycle(registry, {
    runId: "unknown-owner",
    debugPort: port,
    profileDir: profile,
    profileMode: "clean_profile",
    removeProfileOnCleanup: true,
  });
  const record = spawnNodeSleeper();
  lifecycle.processRecord = record;
  lifecycle.process = record.child;
  lifecycle.pid = record.child.pid;
  lifecycle.rootPid = record.child.pid;
  lifecycle.spawned = true;
  await cleanupChromeLifecycle(lifecycle, { verifyPortReleasedFn: async () => false, stopProcessFn: terminateTestRecord });
  assert.equal(await waitForExit(record.child), true);
  assert.equal(lifecycle.debugPortReleased, false);
  assert.ok(lifecycle.cleanupErrors.some((item) => item.stage === "debug_port_release"));
  assert.equal(server.listening, true);
  await new Promise((resolve) => server.close(resolve));
  assert.equal(server.listening, false);
});

test("final post-cleanup settings check catches a delayed semantic mutation and blocks success", async () => {
  const { root, registry } = registryFixture();
  const settingsPath = path.join(root, "settings.json");
  writeFileSync(settingsPath, '{"value":1}\n', "utf8");
  const expected = settingsDigest(settingsPath).semantic_sha256;
  registry.cleanupCompleted = true;
  registry.resourceSafetyValidated = true;
  let delayCalls = 0;
  await assert.rejects(runFinalPostCleanupSettingsCheck({
    registry,
    expectedSemanticSha: expected,
    settingsPath,
    delayFn: async () => {
      delayCalls += 1;
      if (delayCalls === 1) writeFileSync(settingsPath, '{"value":2}\n', "utf8");
    },
  }), (error) => {
    assert.equal(error.code, "SETTINGS_SEMANTIC_SHA_CHANGED_AFTER_FINAL_CLEANUP");
    assert.equal(measurementExitCode(error), FATAL_EXIT_CODE);
    return true;
  });
  assert.equal(registry.globalAbort, true);
  assert.equal(registry.finalSettingsCheck.semanticAssertionPassed, false);
  assert.equal(existsSync(path.join(root, "startup_baseline_summary.json")), false);
});

test("final settings must be quiescent across both bounded reads", async () => {
  const { registry } = registryFixture();
  registry.cleanupCompleted = true;
  registry.resourceSafetyValidated = true;
  let reads = 0;
  await assert.rejects(runFinalPostCleanupSettingsCheck({
    registry,
    expectedSemanticSha: "expected",
    delayFn: async () => {},
    readDigestFn: () => ({ byte_sha256: `byte-${++reads}`, semantic_sha256: `semantic-${reads}`, size_bytes: reads }),
  }), (error) => {
    assert.equal(error.code, "SETTINGS_SEMANTIC_SHA_CHANGED_AFTER_FINAL_CLEANUP");
    assert.equal(error.subcode, "FINAL_SETTINGS_NOT_QUIESCENT");
    return true;
  });
  assert.equal(registry.finalSettingsCheck.stable, false);
});

test("released debug port cannot hide a live registered Chrome process", async () => {
  const { registry } = registryFixture();
  const lifecycle = createChromeLifecycle(registry, {
    runId: "live-process",
    debugPort: 9444,
    profileDir: path.join(registry.profileRoot, "live-process"),
    profileMode: "clean_profile",
    removeProfileOnCleanup: true,
  });
  lifecycle.cleanupCompleted = true;
  lifecycle.processExited = false;
  lifecycle.cdpConnection = null;
  lifecycle.debugPortReleased = true;
  assert.throws(() => validateSampleLifecycleOrAbort(registry, lifecycle), (error) => {
    assert.equal(error.code, "CHROME_LIFECYCLE_CLEANUP_INCOMPLETE");
    assert.equal(error.subcode, "CHROME_PROCESS_NOT_EXITED");
    assert.equal(measurementExitCode(error), CHROME_LIFECYCLE_FATAL_EXIT_CODE);
    return true;
  });
  assert.equal(lifecycle.lifecycleValidated, false);
  assert.equal(registry.globalAbort, true);
  let laterGroups = 0;
  await assert.rejects(runGroupSequence([{ id: "later" }], {
    registry,
    runGroup: async () => { laterGroups += 1; return []; },
  }), (error) => error.subcode === "CHROME_PROCESS_NOT_EXITED");
  assert.equal(laterGroups, 0);
});

test("Chrome cleanup errors make lifecycle validation globally fatal", () => {
  const { registry } = registryFixture();
  const lifecycle = createChromeLifecycle(registry, {
    runId: "cleanup-error",
    debugPort: 9445,
    profileDir: path.join(registry.profileRoot, "cleanup-error"),
    profileMode: "clean_profile",
    removeProfileOnCleanup: true,
  });
  lifecycle.cleanupCompleted = true;
  lifecycle.processExited = true;
  lifecycle.cdpConnection = null;
  lifecycle.debugPortReleased = true;
  lifecycle.cleanupErrors.push({ stage: "chrome_process_tree", message: "injected" });
  assert.throws(() => validateSampleLifecycleOrAbort(registry, lifecycle), (error) => {
    assert.equal(error.subcode, "CHROME_CLEANUP_ERRORS_PRESENT");
    return true;
  });
  assert.equal(lifecycle.lifecycleValidated, false);
  assert.equal(registry.globalAbort, true);
});

test("clean lifecycle becomes valid only after cleanup and profile removal", async () => {
  const { registry } = registryFixture();
  const profile = path.join(registry.profileRoot, "clean-gated");
  createProfileDirectory(registry, profile, "APPLICATION_CLEAN_PROFILE_START", { groupId: "clean-group", runId: "clean-gated" });
  const lifecycle = createChromeLifecycle(registry, {
    runId: "clean-gated",
    debugPort: await freePort(),
    profileDir: profile,
    profileMode: "clean_profile",
    removeProfileOnCleanup: true,
  });
  assert.throws(() => assertChromeLifecycleSafeForValidSample(lifecycle), /cleanup did not complete/);
  await cleanupChromeLifecycle(lifecycle);
  assertChromeLifecycleSafeForValidSample(lifecycle);
  assert.equal(lifecycle.lifecycleValidated, true);
  assert.equal(lifecycle.profileStatus, "REMOVED");
  assert.equal(existsSync(profile), false);
});

test("warm lifecycle defers profile deletion to its group and supports reuse", async () => {
  const { registry } = registryFixture();
  const groupId = "development:warm_cache";
  registry.currentGroupId = groupId;
  const profile = path.join(registry.profileRoot, "warm-reuse");
  createProfileDirectory(registry, profile, "APPLICATION_WARM_CACHE_START", { groupId });
  for (const runId of ["warm-1", "warm-2"]) {
    const lifecycle = createChromeLifecycle(registry, {
      runId,
      debugPort: await freePort(),
      profileDir: profile,
      profileMode: "warm_cache",
      removeProfileOnCleanup: false,
    });
    await cleanupChromeLifecycle(lifecycle);
    assertChromeLifecycleSafeForValidSample(lifecycle);
    assert.equal(lifecycle.profileStatus, "DEFERRED_TO_WARM_GROUP");
    assert.equal(existsSync(profile), true);
  }
  const removed = await safeRemoveProfileDirectory(registry, profile);
  assert.equal(removed.ok, true);
  assert.equal(existsSync(profile), false);
});

test("summary gate rejects valid samples without lifecycle validation", () => {
  const { registry } = registryFixture();
  registry.cleanupCompleted = true;
  registry.resourceSafetyValidated = true;
  registry.finalSettingsCheck = { afterAllCleanup: true, stable: true, semanticAssertionPassed: true };
  assert.throws(() => assertMeasurementRunSafeToSummarize({
    registry,
    samples: [{ valid: true, lifecycleValidated: false }],
  }), (error) => error.code === "MEASUREMENT_RUN_SAFETY_GATE_FAILED");
});

test("summary gate rejects a residual warm-group profile", () => {
  const { registry } = registryFixture();
  const profile = path.join(registry.profileRoot, "warm-residual");
  createProfileDirectory(registry, profile, "APPLICATION_WARM_CACHE_START", { groupId: "fixed_build:warm_cache" });
  registry.groupCleanupStates.set("fixed_build:warm_cache", {
    groupId: "fixed_build:warm_cache",
    cacheType: "warm_cache",
    cleanupStarted: true,
    cleanupCompleted: false,
    profileRemoved: false,
    errors: [],
  });
  registry.cleanupCompleted = true;
  registry.resourceSafetyValidated = true;
  registry.finalSettingsCheck = { afterAllCleanup: true, stable: true, semanticAssertionPassed: true };
  assert.throws(() => assertMeasurementRunSafeToSummarize({ registry, samples: [] }), (error) => error.code === "MEASUREMENT_RUN_SAFETY_GATE_FAILED");
  assert.equal(existsSync(profile), true);
});

test("final settings fatal is secondary when an earlier primary error exists", async () => {
  const { root, registry } = registryFixture();
  const settingsPath = path.join(root, "settings.json");
  writeFileSync(settingsPath, '{"value":2}\n', "utf8");
  const primary = new FatalMeasurementStopError("earlier failure", { code: "EARLIER_PRIMARY" });
  registry.primaryError = primary;
  registry.globalAbort = true;
  registry.cleanupCompleted = true;
  registry.resourceSafetyValidated = true;
  await assert.rejects(runFinalPostCleanupSettingsCheck({
    registry,
    expectedSemanticSha: settingsDigest(path.join(PROJECT_ROOT, "settings", "settings.json")).semantic_sha256,
    settingsPath,
    delayFn: async () => {},
  }), (error) => error === primary);
  assert.equal(registry.primaryError, primary);
  assert.equal(registry.secondaryFatalErrors.length, 1);
  assert.equal(registry.secondaryFatalErrors[0].code, "SETTINGS_SEMANTIC_SHA_CHANGED_AFTER_FINAL_CLEANUP");
});

test("sample valid assignment is structurally after cleanup and lifecycle validation", () => {
  const source = readFileSync(TOOL_PATH, "utf8");
  const start = source.indexOf("async function runStartupSample");
  const end = source.indexOf("function nearestRank", start);
  const sampleSource = source.slice(start, end);
  const cleanupIndex = sampleSource.indexOf("await cleanupChromeLifecycle");
  const lifecycleGateIndex = sampleSource.indexOf("validateSampleLifecycleOrAbort");
  const validIndex = sampleSource.indexOf("result.valid = true");
  assert.ok(cleanupIndex >= 0);
  assert.ok(lifecycleGateIndex > cleanupIndex);
  assert.ok(validIndex > lifecycleGateIndex);
  assert.equal(sampleSource.match(/result\.valid = true/g)?.length, 1);
});
