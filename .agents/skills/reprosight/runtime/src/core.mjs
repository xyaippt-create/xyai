import { copyFile, mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import path from "node:path";

export const STORE_DIR = ".reprosight";
export const STAGES = [
  "intake",
  "reproduction",
  "test-before",
  "patch",
  "verification",
  "report",
];

const STATUS_VALUES = new Set(["pending", "complete", "failed", "passed", "blocked"]);
const RUN_ID_PATTERN = /^[a-z0-9][a-z0-9-]{5,100}$/;
const IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"]);

function now() {
  return new Date().toISOString();
}

function slugify(value) {
  return String(value)
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 42) || "bug-report";
}

function timestampToken(date = new Date()) {
  return date.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "z").toLowerCase();
}

function assertRunId(runId) {
  if (!RUN_ID_PATTERN.test(String(runId))) {
    throw new Error(`Invalid run id: ${runId}`);
  }
}

function assertStage(stage) {
  if (!STAGES.includes(stage)) {
    throw new Error(`Unknown stage "${stage}". Expected one of: ${STAGES.join(", ")}`);
  }
}

function assertStatus(status) {
  if (!STATUS_VALUES.has(status)) {
    throw new Error(`Invalid status "${status}".`);
  }
}

function ensureInside(base, target) {
  const relative = path.relative(path.resolve(base), path.resolve(target));
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`Path escapes the allowed directory: ${target}`);
  }
  return path.resolve(target);
}

function safeFilename(value, fallback = "artifact") {
  const ext = path.extname(value).toLowerCase();
  const stem = path.basename(value, ext).replace(/[^a-zA-Z0-9._-]+/g, "-").slice(0, 80);
  return `${stem || fallback}${ext}`;
}

function mimeExtension(mime) {
  return {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
  }[mime];
}

function parseImageDataUrl(dataUrl) {
  const match = /^data:(image\/(?:png|jpeg|webp|gif|svg\+xml));base64,([A-Za-z0-9+/=\r\n]+)$/.exec(
    String(dataUrl || ""),
  );
  if (!match) {
    throw new Error("Screenshot must be a base64 PNG, JPEG, WebP, GIF, or SVG data URL.");
  }
  const buffer = Buffer.from(match[2], "base64");
  if (!buffer.length || buffer.length > 10 * 1024 * 1024) {
    throw new Error("Screenshot must be between 1 byte and 10 MB.");
  }
  return { buffer, extension: mimeExtension(match[1]), mime: match[1] };
}

export async function resolveRepository(repoPath = process.cwd()) {
  const resolved = path.resolve(repoPath);
  const info = await stat(resolved).catch(() => null);
  if (!info?.isDirectory()) {
    throw new Error(`Repository directory does not exist: ${resolved}`);
  }
  return resolved;
}

export function getStorePath(repoPath) {
  return path.join(path.resolve(repoPath), STORE_DIR);
}

export function getRunPath(repoPath, runId) {
  assertRunId(runId);
  const runsRoot = path.join(getStorePath(repoPath), "runs");
  return ensureInside(runsRoot, path.join(runsRoot, runId));
}

async function writeJson(filePath, data) {
  await writeFile(filePath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
}

async function copyArtifact(runPath, sourcePath, stage, label) {
  const source = path.resolve(sourcePath);
  const info = await stat(source).catch(() => null);
  if (!info?.isFile()) {
    throw new Error(`Artifact does not exist: ${source}`);
  }
  const artifactsDir = path.join(runPath, "artifacts");
  await mkdir(artifactsDir, { recursive: true });
  const sourceName = safeFilename(path.basename(source));
  const extension = path.extname(sourceName).toLowerCase();
  const prefix = `${stage}-${slugify(label || path.basename(source, extension))}`;
  let destinationName = `${prefix}${extension}`;
  let destination = path.join(artifactsDir, destinationName);
  let counter = 2;
  while (await stat(destination).catch(() => null)) {
    destinationName = `${prefix}-${counter}${extension}`;
    destination = path.join(artifactsDir, destinationName);
    counter += 1;
  }
  await copyFile(source, destination);
  return path.posix.join("artifacts", destinationName);
}

function stageDefaults() {
  return Object.fromEntries(
    STAGES.map((stage) => [stage, { status: stage === "intake" ? "complete" : "pending", artifacts: [] }]),
  );
}

export function isRunVerified(run) {
  const reproduction = run.stages.reproduction;
  const testBefore = run.stages["test-before"];
  const patch = run.stages.patch;
  const verification = run.stages.verification;
  return (
    reproduction.status === "complete" &&
    testBefore.status === "failed" &&
    Boolean(testBefore.command) &&
    Number.isFinite(testBefore.exitCode) &&
    testBefore.exitCode !== 0 &&
    patch.status === "complete" &&
    Array.isArray(patch.files) &&
    patch.files.length > 0 &&
    verification.status === "passed" &&
    Boolean(verification.command) &&
    verification.exitCode === 0
  );
}

function deriveState(run, latestStage) {
  if (latestStage === "verification") {
    if (run.stages.verification.status === "failed") return "verification-failed";
    return isRunVerified(run) ? "verified" : "verification-incomplete";
  }
  if (latestStage === "report" && isRunVerified(run)) {
    return "verified";
  }
  return latestStage;
}

export async function createRun({
  repoPath,
  title,
  description,
  targetUrl = "",
  screenshotPath,
  screenshotDataUrl,
  screenshotName = "intake.png",
}) {
  const repoRoot = await resolveRepository(repoPath);
  if (!String(title || "").trim()) throw new Error("A title is required.");
  if (!String(description || "").trim()) throw new Error("A bug description is required.");

  const runsRoot = path.join(getStorePath(repoRoot), "runs");
  await mkdir(runsRoot, { recursive: true });
  const token = timestampToken();
  let runId = `${token}-${slugify(title)}`;
  let suffix = 2;
  while (await stat(path.join(runsRoot, runId)).catch(() => null)) {
    runId = `${token}-${slugify(title)}-${suffix}`;
    suffix += 1;
  }

  const createdAt = now();
  const runPath = path.join(runsRoot, runId);
  await mkdir(path.join(runPath, "artifacts"), { recursive: true });

  const stages = stageDefaults();
  stages.intake.summary = "Bug report captured.";
  stages.intake.at = createdAt;
  const artifacts = [];

  if (screenshotPath) {
    const relativePath = await copyArtifact(runPath, screenshotPath, "intake", "source");
    const artifact = { stage: "intake", label: "Source screenshot", path: relativePath };
    artifacts.push(artifact);
    stages.intake.artifacts.push(relativePath);
  } else if (screenshotDataUrl) {
    const parsed = parseImageDataUrl(screenshotDataUrl);
    const requestedExt = path.extname(screenshotName).toLowerCase();
    const extension = IMAGE_EXTENSIONS.has(requestedExt) ? requestedExt : parsed.extension;
    const destinationName = `intake-source${extension}`;
    const relativePath = path.posix.join("artifacts", destinationName);
    await writeFile(path.join(runPath, "artifacts", destinationName), parsed.buffer);
    const artifact = { stage: "intake", label: "Source screenshot", path: relativePath, mime: parsed.mime };
    artifacts.push(artifact);
    stages.intake.artifacts.push(relativePath);
  }

  const run = {
    schemaVersion: 1,
    id: runId,
    title: String(title).trim(),
    description: String(description).trim(),
    targetUrl: String(targetUrl || "").trim(),
    repoRoot,
    state: "intake",
    createdAt,
    updatedAt: createdAt,
    stages,
    artifacts,
    events: [{ at: createdAt, type: "run-created", summary: "Bug report captured." }],
  };

  await writeJson(path.join(runPath, "case.json"), run);
  return run;
}

export async function readRun(repoPath, runId) {
  const repoRoot = await resolveRepository(repoPath);
  const filePath = path.join(getRunPath(repoRoot, runId), "case.json");
  const raw = await readFile(filePath, "utf8").catch(() => null);
  if (!raw) throw new Error(`Run not found: ${runId}`);
  return JSON.parse(raw);
}

export async function listRuns(repoPath) {
  const repoRoot = await resolveRepository(repoPath);
  const runsRoot = path.join(getStorePath(repoRoot), "runs");
  const entries = await readdir(runsRoot, { withFileTypes: true }).catch(() => []);
  const runs = [];
  for (const entry of entries) {
    if (!entry.isDirectory() || !RUN_ID_PATTERN.test(entry.name)) continue;
    try {
      runs.push(await readRun(repoRoot, entry.name));
    } catch {
      // Ignore interrupted runs so one bad directory cannot break the dashboard.
    }
  }
  return runs.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

export async function recordStage({
  repoPath,
  runId,
  stage,
  status,
  summary = "",
  command = "",
  exitCode,
  artifactPath,
  artifactLabel = "",
  files = [],
}) {
  assertStage(stage);
  assertStatus(status);
  const repoRoot = await resolveRepository(repoPath);
  const run = await readRun(repoRoot, runId);
  const runPath = getRunPath(repoRoot, runId);
  let relativeArtifact;
  if (artifactPath) {
    relativeArtifact = await copyArtifact(runPath, artifactPath, stage, artifactLabel || stage);
    run.artifacts.push({ stage, label: artifactLabel || stage, path: relativeArtifact });
  }

  const at = now();
  const previousArtifacts = Array.isArray(run.stages[stage]?.artifacts) ? run.stages[stage].artifacts : [];
  run.stages[stage] = {
    status,
    summary: String(summary || "").trim(),
    command: String(command || "").trim(),
    ...(exitCode === undefined ? {} : { exitCode: Number(exitCode) }),
    files: Array.isArray(files) ? files.filter(Boolean) : [],
    artifacts: relativeArtifact ? [...previousArtifacts, relativeArtifact] : previousArtifacts,
    at,
  };
  run.state = deriveState(run, stage);
  run.updatedAt = at;
  run.events.push({ at, type: "stage-recorded", stage, status, summary: run.stages[stage].summary });
  await writeJson(path.join(runPath, "case.json"), run);
  return run;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function stageLabel(stage) {
  return {
    intake: "Intake",
    reproduction: "Reproduction",
    "test-before": "Failing test",
    patch: "Patch",
    verification: "Verification",
    report: "Report",
  }[stage];
}

function isImageArtifact(artifact) {
  return IMAGE_EXTENSIONS.has(path.extname(artifact.path).toLowerCase());
}

export async function generateReport(repoPath, runId) {
  const repoRoot = await resolveRepository(repoPath);
  const run = await readRun(repoRoot, runId);
  const runPath = getRunPath(repoRoot, runId);
  const createdAt = now();
  const stageRows = STAGES.filter((stage) => stage !== "report")
    .map((stage) => {
      const item = run.stages[stage];
      return `<tr><th>${escapeHtml(stageLabel(stage))}</th><td><span class="status ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span></td><td>${escapeHtml(item.summary || "—")}</td><td><code>${escapeHtml(item.command || "—")}</code></td></tr>`;
    })
    .join("\n");
  const images = run.artifacts.filter(isImageArtifact);
  const imageCards = images.length
    ? images
        .map(
          (artifact) =>
            `<figure><img src="${escapeHtml(artifact.path)}" alt="${escapeHtml(artifact.label)}"><figcaption>${escapeHtml(artifact.label)} · ${escapeHtml(stageLabel(artifact.stage))}</figcaption></figure>`,
        )
        .join("\n")
    : '<p class="muted">No image evidence recorded.</p>';
  const changedFiles = run.stages.patch.files?.length
    ? `<ul>${run.stages.patch.files.map((file) => `<li><code>${escapeHtml(file)}</code></li>`).join("")}</ul>`
    : '<p class="muted">No changed files recorded.</p>';
  const verified = isRunVerified(run);

  const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escapeHtml(run.title)} · ReproSight</title>
<style>
:root{color-scheme:dark;--bg:#090b13;--panel:#121625;--line:#29314a;--text:#f4f5fb;--muted:#9da6bd;--cyan:#56d7d0;--red:#ff6f83;--green:#59dfa0}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 80% 0,#242050 0,transparent 35%),var(--bg);font:15px/1.55 Inter,ui-sans-serif,system-ui;color:var(--text)}main{width:min(1120px,calc(100% - 32px));margin:0 auto;padding:56px 0 80px}.brand{color:var(--cyan);font-weight:800;letter-spacing:.12em;text-transform:uppercase}.hero{display:grid;grid-template-columns:1fr auto;gap:24px;align-items:end;margin:20px 0 28px}.hero h1{font-size:clamp(34px,6vw,64px);line-height:1;margin:0}.verdict{padding:12px 18px;border:1px solid;border-radius:999px;font-weight:800}.verdict.pass{color:var(--green);background:#59dfa012}.verdict.fail{color:var(--red);background:#ff6f8312}.panel{background:#121625dd;border:1px solid var(--line);border-radius:20px;padding:24px;margin:18px 0;box-shadow:0 24px 80px #0005}.meta{display:flex;gap:20px;flex-wrap:wrap;color:var(--muted)}.meta strong{color:var(--text)}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:14px;border-bottom:1px solid var(--line);vertical-align:top}th{width:145px}.status{display:inline-block;padding:3px 9px;border-radius:999px;background:#ffffff10;color:var(--muted);font-size:12px;font-weight:800;text-transform:uppercase}.status.passed,.status.complete{color:var(--green);background:#59dfa014}.status.failed{color:var(--red);background:#ff6f8314}.gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}figure{margin:0;background:#0d101b;border:1px solid var(--line);border-radius:14px;overflow:hidden}figure img{width:100%;aspect-ratio:16/10;object-fit:cover;display:block}figcaption{padding:12px;color:var(--muted)}code{color:#b9c4ff;white-space:pre-wrap;overflow-wrap:anywhere}.muted{color:var(--muted)}@media(max-width:700px){.hero{grid-template-columns:1fr}th{width:auto}table,tbody,tr,th,td{display:block}th{border:0;padding-bottom:2px}td{padding-top:2px}.panel{padding:18px}}
</style></head><body><main>
<div class="brand">ReproSight · Evidence report</div>
<section class="hero"><div><h1>${escapeHtml(run.title)}</h1><p class="muted">${escapeHtml(run.description)}</p></div><div class="verdict ${verified ? "pass" : "fail"}">${verified ? "Verified fix" : "Incomplete run"}</div></section>
<div class="meta"><span><strong>Run</strong> ${escapeHtml(run.id)}</span><span><strong>Updated</strong> ${escapeHtml(run.updatedAt)}</span>${run.targetUrl ? `<span><strong>Target</strong> ${escapeHtml(run.targetUrl)}</span>` : ""}</div>
<section class="panel"><h2>Verification trail</h2><table><tbody>${stageRows}</tbody></table></section>
<section class="panel"><h2>Before and after evidence</h2><div class="gallery">${imageCards}</div></section>
<section class="panel"><h2>Changed files</h2>${changedFiles}</section>
<p class="muted">Generated ${escapeHtml(createdAt)} by ReproSight.</p>
</main></body></html>`;

  const markdownRows = STAGES.filter((stage) => stage !== "report")
    .map(
      (stage) =>
        `| ${stageLabel(stage)} | ${run.stages[stage].status} | ${String(run.stages[stage].summary || "—").replaceAll("|", "\\|")} |`,
    )
    .join("\n");
  const markdown = `# ${run.title}\n\n**Verdict:** ${verified ? "Verified fix" : "Incomplete run"}\n\n${run.description}\n\n| Stage | Status | Evidence |\n| --- | --- | --- |\n${markdownRows}\n\n## Changed files\n\n${run.stages.patch.files?.length ? run.stages.patch.files.map((file) => `- \`${file}\``).join("\n") : "No changed files recorded."}\n\n## Artifacts\n\n${run.artifacts.length ? run.artifacts.map((artifact) => `- [${artifact.label}](${artifact.path})`).join("\n") : "No artifacts recorded."}\n`;

  await writeFile(path.join(runPath, "report.html"), html, "utf8");
  await writeFile(path.join(runPath, "report.md"), markdown, "utf8");
  const reportAt = now();
  run.stages.report = {
    status: "complete",
    summary: verified
      ? "Evidence report generated for a verified fix."
      : "Evidence report generated with missing verification gates.",
    command: "reprosight report",
    files: [],
    artifacts: ["report.html", "report.md"],
    at: reportAt,
  };
  for (const artifact of [
    { stage: "report", label: "HTML report", path: "report.html" },
    { stage: "report", label: "Markdown report", path: "report.md" },
  ]) {
    if (!run.artifacts.some((current) => current.path === artifact.path)) run.artifacts.push(artifact);
  }
  run.state = verified ? "verified" : run.state;
  run.updatedAt = reportAt;
  run.events.push({ at: reportAt, type: "report-generated", stage: "report", status: "complete" });
  await writeJson(path.join(runPath, "case.json"), run);
  return {
    run,
    htmlPath: path.join(runPath, "report.html"),
    markdownPath: path.join(runPath, "report.md"),
  };
}

export async function doctor(repoPath) {
  const repoRoot = await resolveRepository(repoPath);
  const major = Number(process.versions.node.split(".")[0]);
  return {
    ok: major >= 20,
    node: process.versions.node,
    repoRoot,
    storePath: getStorePath(repoRoot),
    checks: [
      { name: "Node.js 20+", ok: major >= 20, value: process.versions.node },
      { name: "Repository exists", ok: true, value: repoRoot },
    ],
  };
}

export function contentTypeFor(filePath) {
  return {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
  }[path.extname(filePath).toLowerCase()] || "application/octet-stream";
}

export { ensureInside };
